"""Local and paired-device management API, durable operations and static UI.

Long-running AI/browser work runs in subprocesses so the API stays responsive.
The SQLite ledger survives restart; incomplete operations are explicitly interrupted.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from integration import bridge, scheduler, recovery, writer_runner
from manager import ai_tools, device_access
from integration import model_roles, studio, memory_library, style_profile, secret_store, character_state, continuity, scenes, scene_writer, workflow
from integration import costs

DATA = bridge.COMBINED_ROOT / "integration_data"
DB_PATH = Path(os.getenv("NOVEL_HELPER_MANAGER_DB", str(DATA / "manager.sqlite3"))).resolve()
# 允许用 NOVEL_HELPER_AI_CONFIG 覆盖（README 承诺；旧实现硬编码 O 盘路径，
# 导致界面与 CLI 可能读写不同配置文件）。
AI_PATH = Path(os.getenv("NOVEL_HELPER_AI_CONFIG") or str(DATA / "ai_config.json")).resolve()
STATIC = Path(__file__).resolve().parent / "static"
PYTHON = bridge.COMBINED_ROOT / ".venv" / "Scripts" / "python.exe"


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def projects(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY rowid")]

    def register(self, path: Path):
        value = str(path.resolve())
        identity = hashlib.sha256(os.path.normcase(value).encode()).hexdigest()[:16]
        with self.lock, self.connect() as db:
            db.execute("INSERT OR IGNORE INTO projects VALUES (?, ?)", (identity, value))
        return identity

    def operations(self, active_only=False):
        with self.connect() as db:
            query = "SELECT payload FROM operations"
            query += " WHERE json_extract(payload, '$.status') IN ('queued','running','awaiting_login','waiting') ORDER BY rowid DESC" if active_only else " ORDER BY rowid DESC LIMIT 100"
            return [json.loads(row[0]) for row in db.execute(query)]

    def operation(self, identity):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM operations WHERE id=?", (identity,)).fetchone()
        if not row:
            raise KeyError("运行记录不存在")
        return json.loads(row[0])

    def save_operation(self, payload):
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO operations VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                       (payload["id"], json.dumps(payload, ensure_ascii=False)))

    def settings(self):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM settings WHERE key='manager' ").fetchone()
        return json.loads(row[0]) if row else {"scheduler_enabled": False}

    def set_settings(self, payload):
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO settings VALUES ('manager', ?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload",
                       (json.dumps(payload),))


def redact(value: str) -> str:
    """Remove known key and common credential formats before persistence."""
    try:
        config = load_ai()
    except (OSError, ValueError):
        config = {}
    for secret in model_roles.secrets(config):
        value = value.replace(secret, "[redacted]")
    value = re.sub(r"\bsk-[A-Za-z0-9_\-]{8,}", "[redacted]", value)
    value = re.sub(r"(?i)(authorization[\s\"':=]+(?:bearer\s+)?)[^\s,\"}]+", r"\1[redacted]", value)
    return value


def stop_process_tree(process: subprocess.Popen):
    """Stop only descendants of the worker launched by this manager."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)
    else:
        process.terminate()


class Operations:
    def __init__(self, store: Store):
        self.store = store
        self.lock = threading.RLock()
        self.processes: dict[str, subprocess.Popen] = {}
        self.cancelled: set[str] = set()
        # Reconciliation prevents a restart from showing indefinitely "running".
        for old in store.operations(active_only=True):
            if old.get("status") in {"queued", "running", "awaiting_login"}:
                old.update(status="interrupted", finished_at=bridge.now_iso(), error="管理服务已重启；请核对队列后重新执行")
                store.save_operation(old)

    def start(self, kind: str, args: list[str], identity: str, metadata: dict | None = None):
        with self.lock:
            if writer_runner.strict_json(DATA/'maintenance.json',{}).get('state')=='maintenance':
                raise HTTPException(409,'正在维护升级，暂不派发新操作；完成后可继续原任务')
            active = self.store.operations(active_only=True)
            if any(x.get("identity") == identity for x in active):
                raise HTTPException(409, "同一操作正在执行，请查看运行记录")
            payload = {"id": uuid.uuid4().hex, "kind": kind, "identity": identity,
                       "created_at": bridge.now_iso(), "status": "queued", "log_tail": "", **(metadata or {})}
            self.store.save_operation(payload)
            thread = threading.Thread(target=self._execute, args=(payload["id"], args), daemon=True)
            thread.start()
        return payload

    def resume_due(self, now=None):
        """Wake only durable, explicitly deferred creation batches, never publish."""
        from datetime import datetime, timezone
        now=now or datetime.now(timezone.utc)
        if writer_runner.strict_json(DATA/'maintenance.json',{}).get('state')=='maintenance':return
        with self.lock:
            records=self.store.operations(active_only=True)
            for payload in records:
                if payload.get('status')!='waiting':continue
                result=payload.get('result') or {}
                if result.get('failure_kind') not in {'recovery_cooldown','free_pool_wait'}:continue
                try:
                    target=datetime.fromisoformat(result['next_retry_at'])
                    if target.tzinfo is None:raise ValueError('等待时间缺少时区')
                    if target>now:continue
                    if any(x['id']!=payload['id'] and x.get('identity')==payload.get('identity') for x in records):continue
                    project=next(x for x in self.store.projects() if x['id']==payload['project_id'])
                    if payload.get('kind')!='generate' or Path(project['path']).resolve()!=Path(result['project']).resolve():
                        raise ValueError('等待批次作品身份不一致')
                    if result.get('batch_id')!=payload['batch_id']:raise ValueError('等待批次身份不一致')
                    path=studio.project_file(Path(project['path']),'batches',payload['batch_id'])
                    batch=writer_runner.strict_json(path,{})
                    if not isinstance(batch,dict) or batch.get('id')!=payload['batch_id'] or batch.get('status')!='waiting' or batch.get('recovery',{}).get('next_retry_at')!=result['next_retry_at']:
                        raise ValueError('原批次等待检查点已变化')
                    args=['batch','--project',project['path'],'--batch-id',payload['batch_id']]
                    payload.update(status='queued',resume_count=payload.get('resume_count',0)+1,last_resumed_at=bridge.now_iso())
                    payload.pop('finished_at',None);payload.pop('error',None)
                    self.store.save_operation(payload)
                    threading.Thread(target=self._execute,args=(payload['id'],args),daemon=True).start()
                except (KeyError,ValueError,TypeError,StopIteration,OSError) as exc:
                    payload.update(status='failed',error=redact(str(exc) or '等待批次检查点无效'))
                    self.store.save_operation(payload)

    def _execute(self, identity: str, args: list[str]):
        payload = self.store.operation(identity)
        process = None
        try:
            env = bridge.child_environment()
            env["PYTHONUTF8"] = "1"
            env["PYTHONUNBUFFERED"] = "1"
            env["NOVEL_HELPER_AI_CONFIG"] = str(AI_PATH)
            config = load_ai()
            for field, variable in (("base_url", "AI_BASE_URL"), ("model", "AI_MODEL"), ("api_key", "AI_API_KEY")):
                if config.get(field):
                    env[variable] = str(config[field])
            env["NOVEL_HELPER_MANAGER_DATA"] = str(DATA)
            env["NOVEL_HELPER_COST_DB"] = str(DATA / "costs.sqlite3")
            env["NOVEL_HELPER_OPERATION_ID"] = identity
            suffix=f"-resume-{payload['resume_count']}" if payload.get('resume_count') else ''
            env["NOVEL_HELPER_MANAGER_RESULT"] = str(DATA / "operations" / f"{identity}{suffix}.json")
            result_path = Path(env["NOVEL_HELPER_MANAGER_RESULT"])
            with self.lock:
                if identity in self.cancelled:
                    payload.update(status="cancelled", finished_at=bridge.now_iso())
                    self.store.save_operation(payload)
                    return
            process = subprocess.Popen([str(PYTHON), "-X", "utf8", "-u", str(ROOT / "manager" / "worker.py"), *args],
                cwd=str(ROOT), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            with self.lock:
                self.processes[identity] = process
                if identity in self.cancelled:
                    stop_process_tree(process)
            payload.update(status="running", pid=process.pid)
            self.store.save_operation(payload)
            # Bound the child even if the website or model stops responding.
            timed_out = threading.Event()
            def timeout_child():
                timed_out.set()
                stop_process_tree(process)
            timer = threading.Timer(3600, timeout_child)
            timer.daemon = True
            timer.start()
            try:
                for line in process.stdout:
                    payload["log_tail"] = (payload.get("log_tail", "") + redact(line))[-16000:]
                    if line.startswith("NOVEL_HELPER_WAITING_LOGIN"):
                        payload["status"] = "awaiting_login"
                    self.store.save_operation(payload)
                code = process.wait(timeout=10)
            finally:
                timer.cancel()
            result = bridge.read_json(result_path, {})
            result = json.loads(redact(json.dumps(result, ensure_ascii=False)))
            child_status = result.get("status") if isinstance(result, dict) else None
            benign = {"success", "progress", "generated", "reviewed", "authorized", "queued", "logged_in", "configured", "already_run", "already_ran", "ok", "learned", "planned", "polished", "memory_synced"}
            if timed_out.is_set():
                payload.update(status="failed", error="运行超过一小时，已停止；请核对平台状态后再试")
            elif code == 0 and child_status in benign:
                payload["status"] = "success"
            elif child_status=='waiting' and payload.get('kind')=='generate' and payload.get('batch_id') and result.get('failure_kind') in {'recovery_cooldown','free_pool_wait'} and result.get('next_retry_at'):
                payload.update(status='waiting',error=result.get('error','等待模型恢复'))
            elif child_status in {"awaiting_approval", "disabled", "already_run", "already_ran", "busy"}:
                payload["status"] = child_status
            else:
                payload.update(status="failed", error=result.get("error", "操作失败，请查看日志") if isinstance(result, dict) else "操作失败")
            payload.update(result=result, exit_code=code)
        except Exception as exc:
            payload.update(status="failed", error=redact(str(exc)))
        finally:
            if process:
                if process.poll() is None:
                    stop_process_tree(process)
                for pipe in (process.stdin, process.stdout):
                    if pipe:
                        pipe.close()
            with self.lock:
                self.processes.pop(identity, None)
                if identity in self.cancelled:
                    payload.update(status="cancelled", error="已由用户取消；已提交到平台的章节请核对状态")
                    self.cancelled.discard(identity)
            payload["finished_at"] = bridge.now_iso()
            self.store.save_operation(payload)

    def cancel(self, identity: str):
        with self.lock:
            payload = self.store.operation(identity)
            if payload.get('status')=='waiting':
                payload.update(status='cancelled',finished_at=bridge.now_iso(),error='已取消等待；原稿与批次保留')
                self.store.save_operation(payload)
                return {'id':identity,'status':'cancelled'}
            if payload.get("status") not in {"queued", "running", "awaiting_login"}:
                raise HTTPException(409, "该操作已经结束")
            self.cancelled.add(identity)
            process = self.processes.get(identity)
            if process:
                stop_process_tree(process)
            return {"id": identity, "status": "cancelling"}

    def confirm_login(self, name: str):
        with self.lock:
            for op in self.store.operations(active_only=True):
                if op.get("identity") == f"login:{name}" and op.get("status") == "awaiting_login":
                    process = self.processes.get(op["id"])
                    if process and process.poll() is None:
                        process.stdin.write("\n")
                        process.stdin.flush()
                        op["status"] = "running"
                        self.store.save_operation(op)
                        return op
        raise HTTPException(409, "没有等待确认的登录窗口，请先启动登录")

    def shutdown(self):
        with self.lock:
            for process in self.processes.values():
                if process.poll() is None:
                    stop_process_tree(process)


class ProjectInput(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


class NewProject(BaseModel):
    title: str = Field(min_length=1, max_length=90)
    genre: str = Field(default="玄幻", max_length=90)
    outline: str = Field(default="", max_length=500000)


class ContentInput(BaseModel):
    content: str = Field(max_length=500000)


class GenerateInput(BaseModel):
    word_count: int = Field(default=3500, ge=500, le=10000)
    max_revisions: int = Field(default=1, ge=0, le=3)
    count: int = Field(default=1, ge=1, le=30)
    scenes: int = Field(default=0, ge=0, le=3)


class PlanInput(BaseModel):
    count: int = Field(default=5,ge=1,le=30)


class LearnInput(BaseModel):
    revision: int = Field(ge=0)
    full: bool = False


class StyleProfileInput(BaseModel):
    enabled: bool | None = None
    strength: int | None = Field(default=None, ge=0, le=100)
    overrides: dict[str, str] | None = None


class RevisionClose(BaseModel):
    preview_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    reason: str = Field(default="", max_length=200)


class RestoreInput(BaseModel):
    version_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class StageInput(BaseModel):
    book: str = Field(min_length=1, max_length=96)
    chapters: list[int] | None = None


class MemoryItemInput(BaseModel):
    revision: int = Field(ge=0)
    category: str = Field(pattern="^(canon|fact|foreshadow|preference)$")
    title: str = Field(min_length=1,max_length=120)
    content: str = Field(min_length=1,max_length=2000)
    pinned: bool = False
    status: str = Field(default="active",pattern="^(active|conflict|archived)$")
    source_chapter: int = Field(default=0,ge=0,le=100000)
    due_chapter: int = Field(default=0,ge=0,le=100000)
    clue_state: str = Field(default="planned",pattern="^(planned|planted|resolved)$")
    valid_to: int = Field(default=0,ge=0,le=100000)
    story_time: str = Field(default="",max_length=80)


class MemoryRevisionInput(BaseModel):
    revision: int = Field(ge=0)


class MemoryCorrectionInput(MemoryItemInput):
    reason: str = Field(default="", max_length=400)


class CharacterInput(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    identity: str = Field(default="", max_length=2000)


class CharacterCorrectionInput(BaseModel):
    field: str = Field(pattern="^(identity|goal|motive|limits|voice|history)$")
    value: str = Field(min_length=1, max_length=2000)
    reason: str = Field(default="", max_length=400)


class ForeshadowInput(BaseModel):
    revision: int = Field(ge=0)
    state: str = Field(pattern="^(planned|planted|developing|resolved|paused|cancelled)$")
    chapter: int = Field(default=0, ge=0, le=100000)
    event: str = Field(default="", max_length=200)
    quote: str = Field(default="", max_length=800)
    sha256: str = Field(default="", max_length=64)
    expected: str = Field(default="", max_length=400)
    note: str = Field(default="", max_length=400)
    author: bool = False


class AccountInput(BaseModel):
    name: str = Field(min_length=1, max_length=96)


class PublishInput(BaseModel):
    project_id: str
    account: str = Field(min_length=1, max_length=96)
    book: str = Field(min_length=1, max_length=96)
    count: int = Field(default=1, ge=1, le=50)
    ai_used: bool = True


class JobInput(BaseModel):
    job_id: str | None = None
    id: str | None = None
    name: str = Field(default="日更任务", min_length=1, max_length=96)
    project: str
    book: str = Field(min_length=1, max_length=96)
    account: str = Field(min_length=1, max_length=96)
    daily_time: str = "08:00"
    daily_times: list[str] = Field(default_factory=list,max_length=8)
    timezone: str = "Asia/Shanghai"
    chapters_per_run: int = Field(default=1, ge=1, le=50)
    word_count: int = Field(default=3500, ge=500, le=10000)
    quota_phases: list[dict] = Field(default_factory=list, max_length=24)
    slot_quotas: dict[str, int] | None = None
    delivery_mode: str = Field(default="batch", pattern="^(batch|serial)$")
    max_revisions: int = Field(default=1, ge=0, le=3)
    enabled: bool = False
    approval_mode: str = "unattended"


class ApproveInput(BaseModel):
    for_date: str | None = None


class AIInput(BaseModel):
    base_url: str = Field(min_length=1, max_length=1000)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=4096)


class ModelDiscoveryInput(BaseModel):
    base_url: str = Field(min_length=1, max_length=1000)
    api_key: str | None = Field(default=None, max_length=4096)
    role: str | None = Field(default=None,pattern="^[ABCDE]$")


class RoleInput(BaseModel):
    base_url: str = Field(default="",max_length=1000)
    model: str = Field(default="",max_length=200)
    api_key: str | None = Field(default=None,max_length=4096)


class RolesInput(BaseModel):
    multi_model: bool
    roles: dict[str,RoleInput]
    polish_mode: str = Field(default="key",pattern="^(key|all|none)$")
    review_policy: str = Field(default="strict",pattern="^(strict|e_decides)$")


class BriefInput(BaseModel):
    brief: dict[str, str]
    revision: int = Field(ge=0)

    @field_validator("brief")
    @classmethod
    def _limit_brief(cls, value):
        # 防止超大 JSON 占满内存/磁盘：字段数与单字段长度都设上限。
        if len(value) > 64:
            raise ValueError("创作约定字段过多")
        for key, text in value.items():
            if len(str(key)) > 64 or len(str(text)) > 20000:
                raise ValueError("创作约定字段过长")
        return value


class CreativeMessage(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    revision: int = Field(ge=0)


class SettingsInput(BaseModel):
    scheduler_enabled: bool


class CostRateInput(BaseModel):
    base_url: str = Field(min_length=1,max_length=500)
    model: str = Field(min_length=1,max_length=200)
    currency: str = "CNY"
    input_per_million: float = Field(ge=0,le=1000000,allow_inf_nan=False)
    output_per_million: float = Field(ge=0,le=1000000,allow_inf_nan=False)
    cached_per_million: float | None = Field(default=None,ge=0,le=1000000,allow_inf_nan=False)


class CostPricingInput(BaseModel):
    revision: int = Field(ge=0)
    usd_to_cny: float | None = Field(default=None,gt=0,le=1000000,allow_inf_nan=False)
    rates: list[CostRateInput] = Field(max_length=100)
    reprice_unpriced: bool = False


def _write_ai_config(config):
    """配置落盘：密钥交给凭据适配层，非秘密字段照旧原子写入并收紧 ACL。"""
    bridge.write_json_atomic(AI_PATH, config)
    bridge.harden_secret_file(AI_PATH)


def _persist_ai(config):
    try:
        return secret_store.save(DATA, config, _write_ai_config)
    except (OSError, ValueError, secret_store.SecretCorrupt):
        _write_ai_config(config)
        return {"mode": "plaintext-acl", "migrated": False, "stored": 0,
                "detail": "凭据保护暂不可用，已保留明文配置"}


_AI_MIGRATION_TRIED = False


def load_ai():
    global _AI_MIGRATION_TRIED

    def read_config(path):
        config = writer_runner.strict_json(path, {})
        if not isinstance(config, dict):
            raise ValueError("AI 配置必须是 JSON 对象，请修复配置文件")
        role_values=config.get("roles",{})
        if not isinstance(role_values,dict) or set(role_values)-set(model_roles.ROLES) or any(not isinstance(v,dict) for v in role_values.values()):raise ValueError("多模型配置损坏")
        return config
    if AI_PATH.is_file():
        config = secret_store.load(DATA, read_config(AI_PATH))
        plaintext = secret_store.collect({key: value for key, value in config.items() if key != "secret_store"})
        if plaintext and not _AI_MIGRATION_TRIED and secret_store.codec() is not None:
            # 迁移只尝试一次：写受保护存储 → 读回校验 → 再移除明文。
            _AI_MIGRATION_TRIED = True
            _persist_ai(config)
        return config
    if os.getenv('CHAPTER_WHALE_MANAGED') == '1':
        return {}
    # Read-only fallback for users with an existing upstream configuration.
    legacy = Path.home() / ".webnovel" / "ai_config.json"
    return read_config(legacy)


def public_ai():
    try:
        config = load_ai()
    except (OSError, ValueError):
        return {"configured": False, "base_url": "", "model": "", "key_masked": "",
                "error": "AI 配置文件损坏，请修复后重试", "config_path": str(AI_PATH)}
    key = config.get("api_key") or os.getenv("AI_API_KEY", "")
    configured = bool(key and "your-" not in key and "here" not in key)
    if model_roles.enabled(config):
        try:
            for role in model_roles.ROLES:model_roles.connection(role,config)
            configured=True
        except ValueError:configured=False
    return {"configured": configured, "base_url": config.get("base_url", "https://api.openai.com/v1"),
            "model": config.get("model", ""), "key_masked": "••••••••" if configured else "", "config_path": str(AI_PATH),
            "multi_model":model_roles.enabled(config),"polish_mode":config.get("polish_mode","key"),"review_policy":config.get("review_policy","e_decides"),
            "roles":{role:{"model":config.get("roles",{}).get(role,{}).get("model",""),
                "base_url":config.get("roles",{}).get(role,{}).get("base_url",""),
                "key_masked":"••••••••" if config.get("roles",{}).get(role,{}).get("api_key") else ""} for role in model_roles.ROLES},
            "credential_store":secret_store.status(DATA)}


def project_summary(item: dict):
    path = Path(item["path"])
    problem = ""
    try:
        state = writer_runner.strict_json(path / ".webnovel" / "state.json", {})
        if not isinstance(state, dict):
            raise ValueError("作品状态必须是 JSON 对象")
    except (ValueError, OSError):
        state = {}
        problem = "作品状态文件损坏，请修复 .webnovel/state.json"
    info = state.get("project_info", {}) if isinstance(state, dict) else {}
    if not isinstance(info, dict):
        info = {}
    try:
        chapters = list(bridge.iter_source_chapters(path)) if (path / "正文").is_dir() else []
    except (OSError, ValueError, RuntimeError):
        chapters = []
        problem = problem or "正文文件存在重复或读取错误，请检查作品目录"
    outlines = list((path / "大纲").glob("*.md"))
    import hashlib
    revision=hashlib.sha256()
    for entry in sorted([x[0] for x in chapters]+[path/'.webnovel/writer_receipts.json']):
        if entry.is_file():
            stat=entry.stat()
            revision.update(f'{entry.name}:{stat.st_mtime_ns}:{stat.st_size}'.encode())
    return {**item, "title": info.get("title") or state.get("title") or path.name,
            "genre": info.get("genre") or state.get("genre", "未设定"),
            "chapters": len(chapters), "words": sum(len(x[3]) for x in chapters),
            "chapters_revision":revision.hexdigest()[:16],
            "outline_count": len(outlines), "ready": path.is_dir() and bool(outlines) and not problem,
            "exists": path.is_dir(), "error": problem}


def diagnostics():
    checks = [
        {"name": "Python 环境", "ok": PYTHON.is_file(), "detail": str(PYTHON)},
        {"name": "写作引擎", "ok": (bridge.WEBNOVEL_ROOT / "backend" / "services" / "skill_executor.py").is_file(), "detail": str(bridge.WEBNOVEL_ROOT)},
        {"name": "发布执行器", "ok": (bridge.FANQIE_ROOT / "publish.py").is_file(), "detail": str(bridge.FANQIE_ROOT)},
        {"name": "浏览器内核", "ok": any((bridge.COMBINED_ROOT / "playwright-browsers").glob("chromium-*")), "detail": "O 盘 Playwright Chromium"},
        {"name": "AI 配置", "ok": public_ai()["configured"], "detail": public_ai().get("error") or ("已配置" if public_ai()["configured"] else "请在 AI 设置中配置模型与 API Key")},
        {"name": "番茄账号", "ok": any(x["logged_in"] for x in bridge.list_accounts()), "detail": "登录状态需在试发时验证"},
    ]
    return {"checks": checks, "ready": all(x["ok"] for x in checks), "root": str(bridge.COMBINED_ROOT)}


def create_app(db_path: Path | None = None, start_dispatcher: bool = True, network_hosts=(), port=8765, device_pairing_required=False):
    store = Store(db_path or DB_PATH)
    ops = Operations(store)

    def project(identity):
        for item in store.projects():
            if item["id"] == identity:
                path = Path(item["path"])
                if not path.is_dir():
                    raise HTTPException(404, "作品目录已经不存在")
                return item
        raise HTTPException(404, "未登记此作品")

    def platform_book(item):
        """The platform title recorded in the binding, if one exists.

        The UI used to pass the local project title straight to the publisher;
        a project named differently from the real platform book then failed
        with “目标平台书名与队列不匹配” after the queue had been prepared.
        """
        path = Path(item["path"]) / ".webnovel" / "platform_binding.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        value = data.get("book") if isinstance(data, dict) else None
        return value.strip() if isinstance(value, str) and value.strip() else None

    async def dispatch():
        while True:
            await asyncio.sleep(20)
            try:
                await asyncio.to_thread(ops.resume_due)
                for job in await asyncio.to_thread(scheduler.due_jobs):
                    identity = job["id"]
                    try:
                        ops.start("daily", ["run", "--job-id", identity], f"job:{identity}")
                    except HTTPException:
                        continue
            except (ValueError, KeyError, RuntimeError, OSError, sqlite3.Error) as exc:
                # Malformed config or a transient DB error must not kill the
                # dispatcher: an uncaught sqlite3.OperationalError used to end
                # this coroutine permanently, silently stopping all schedules.
                print(f"调度配置不可用：{redact(str(exc))}", file=sys.stderr)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(dispatch()) if start_dispatcher else None
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        ops.shutdown()

    app = FastAPI(title="番茄小说发布助手", lifespan=lifespan)
    from manager.runtime_health import BodyLimitMiddleware, release_id, STARTUP_ID, STARTED_AT
    loaded_release = release_id()
    app.add_middleware(BodyLimitMiddleware)
    app.state.store = store
    app.state.operations = ops
    from manager import provider_api
    provider_api.install(app, load_ai, AI_PATH)
    access = device_access.DeviceAccess(network_hosts, port, pairing_required=device_pairing_required)
    app.state.device_access = access
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver", *network_hosts])

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        denied = access.guard(request)
        if denied is not None:
            return denied
        # 全局请求体上限（分块上传没有 Content-Length，先放行给具体端点，
        # 采样上传在下面单独限制；其余超大 JSON 直接拒绝）。
        try:
            content_length = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            return JSONResponse({"detail": "请求长度无效"}, status_code=400)
        if content_length > 32 * 1024 * 1024:
            return JSONResponse({"detail": "请求体过大"}, status_code=413)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("X-Novel-Helper") != "1":
                return JSONResponse({"detail": "需要管理界面的请求标识"}, status_code=403)
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "拒绝跨站修改请求"}, status_code=403)
            if request.url.path.endswith("/samples"):
                length = content_length
                if length > studio.MAX_UPLOAD + 65536:
                    return JSONResponse({"detail": "文件超过 5 MB"}, status_code=413)
        with costs.scope(db=str(DATA / "costs.sqlite3")):
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else "no-cache"
        return response

    for exception in (ValueError, FileNotFoundError, RuntimeError, KeyError, FileExistsError):
        async def handler(request, exc):
            if "resource_busy" in str(exc):
                # 发布/入队持锁属于“暂时不可用”，不是客户端请求错误。
                return JSONResponse({"detail": "系统正忙，请稍后重试"}, status_code=503,
                                    headers={"Retry-After": "2"})
            code = 404 if isinstance(exc, (KeyError, FileNotFoundError)) else 409 if isinstance(exc, FileExistsError) else 400
            return JSONResponse({"detail": redact(str(exc))}, status_code=code)
        app.add_exception_handler(exception, handler)

    @app.get("/api/health")
    def health():
        maintenance = bridge.read_json(DATA / 'maintenance.json', {})
        return {"status": "healthy", "service": "novel-helper-manager", 'release_id':loaded_release,
            'pid':os.getpid(),'startup_id':STARTUP_ID,'started_at':STARTED_AT,
            'maintenance':maintenance.get('state') == 'maintenance'}

    device_access.install_routes(app, access, STATIC)

    @app.get("/api/overview")
    def overview():
        accounts = bridge.list_accounts()
        operations = list({item["id"]: item for item in [*store.operations(active_only=True), *store.operations()]}.values())
        for item in accounts:
            item["login_operation"] = next((o for o in operations if o.get("identity") == f"login:{item['name']}" and o["status"] in {"running", "awaiting_login", "queued"}), None)
        return {"projects": [project_summary(x) for x in store.projects()], "accounts": accounts,
                "jobs": list_jobs(), "operations": operations,
                "queue": bridge.manifest_snapshot(), "diagnostics": diagnostics(), "ai": public_ai(),
                "settings": settings()}

    @app.get("/api/projects")
    def list_projects():
        return [project_summary(x) for x in store.projects()]

    @app.post("/api/projects")
    def register(data: ProjectInput):
        path = Path(data.path).expanduser().resolve()
        if not path.is_dir() or not (path / ".webnovel" / "state.json").is_file() or not (path / "正文").is_dir():
            raise ValueError("请选择包含 .webnovel/state.json 和 正文 的写作项目")
        state = json.loads((path / ".webnovel" / "state.json").read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("作品状态必须是 JSON 对象")
        identity = store.register(path)
        return project_summary(project(identity))

    @app.post("/api/projects/create")
    def new_project(data: NewProject):
        title = data.title.strip()
        if not title:
            raise ValueError("请输入书名")
        path = bridge.COMBINED_ROOT / "books" / bridge.safe_dir_name(title)
        path.mkdir(parents=True, exist_ok=False)
        for name in ("正文", "大纲", ".webnovel", "设定集"):
            (path / name).mkdir()
        if data.outline.strip():
            (path / "大纲" / "卷一.md").write_text(data.outline, encoding="utf-8")
        bridge.write_json_atomic(path / ".webnovel" / "state.json", {
            "project_info": {"title": title, "genre": data.genre}, "current_chapter": 0,
            "protagonist_state": {}, "initialized": True, "created_at": bridge.now_iso()})
        identity = store.register(path)
        return project_summary(project(identity))

    @app.get("/api/projects/{identity}/chapters")
    def chapters(identity: str):
        path = Path(project(identity)["path"])
        receipts = writer_runner.reviewed_chapters(path)
        return {"chapters": [{"id": cid, "title": title, "words": len(content), "path": str(source), "reviewed": cid in receipts, "review_status":receipts.get(cid,{}).get("review",{}).get("review_decision")}
                             for source, cid, title, content in bridge.iter_source_chapters(path)]}

    @app.get("/api/projects/{identity}/creative")
    def creative_settings(identity: str):
        _, service = ai_tools.services()
        return service.read_document(Path(project(identity)["path"]))

    @app.put("/api/projects/{identity}/creative")
    def save_creative(identity: str, data: BriefInput):
        path = Path(project(identity)["path"])
        _, service = ai_tools.services()
        with writer_runner.file_lock(path / ".webnovel" / "writer.lock"), writer_runner.file_lock(path / ".webnovel" / "creative.lock"):
            doc = service.read_document(path)
            if doc["revision"] != data.revision:
                raise ValueError("创作约定已被更新，请重新载入，避免覆盖其他修改")
            doc.update(brief=service.validate_brief(data.brief), revision=doc["revision"] + 1)
            if doc["history"]:
                last = doc["history"][-1]
                proposal = last.get("proposal", {})
                if isinstance(proposal, dict) and proposal and all(doc["brief"].get(k) == v for k,v in proposal.items()):
                    last["proposal_applied"] = True
            writer_runner.atomic_json(path / ".webnovel" / "creative_brief.json", doc)
        return doc

    @app.post("/api/projects/{identity}/creative/chat")
    def creative_chat(identity: str, data: CreativeMessage):
        item = project(identity)
        message = data.message.strip()
        if not message:
            raise ValueError("请输入想讨论的写作要求")
        return ai_tools.converse(Path(item["path"]), project_summary(item)["title"], message, load_ai(), data.revision)

    @app.post("/api/projects/{identity}/creative/expand")
    def expand_creative(identity: str,data: BriefInput):
        # Only a preview is returned. The existing save route binds the version.
        return studio.expand_brief(Path(project(identity)["path"]),data.brief,data.revision,config=load_ai())

    @app.get("/api/projects/{identity}/samples")
    def samples(identity: str):
        return studio.sample_list(Path(project(identity)["path"]))

    @app.get("/api/projects/{identity}/memory")
    def shared_memory(identity: str):
        return memory_library.public(Path(project(identity)["path"]))

    @app.post("/api/projects/{identity}/memory/items")
    def add_memory(identity: str,data: MemoryItemInput):
        return memory_library.save_item(Path(project(identity)["path"]),data.model_dump(),data.revision)

    @app.put("/api/projects/{identity}/memory/items/{item}")
    def edit_memory(identity: str,item: str,data: MemoryItemInput):
        return memory_library.save_item(Path(project(identity)["path"]),data.model_dump(),data.revision,item)

    @app.post("/api/projects/{identity}/memory/items/{item}/archive")
    def archive_memory(identity: str,item: str,data: MemoryRevisionInput):
        return memory_library.archive(Path(project(identity)["path"]),item,data.revision)

    @app.get("/api/projects/{identity}/memory/context")
    def memory_context(identity: str,role: str="B",chapter: int=0,q: str=""):
        path=Path(project(identity)["path"])
        return memory_library.context(path,role,chapter or writer_runner.next_chapter_id(path),q[:8000])

    @app.get("/api/projects/{identity}/memory/state")
    def memory_state(identity: str,chapter: int=0):
        path=Path(project(identity)["path"])
        return memory_library.state(path,chapter or None)

    @app.put("/api/projects/{identity}/memory/items/{item}/correct")
    def correct_memory(identity: str,item: str,data: MemoryCorrectionInput):
        return memory_library.correct(Path(project(identity)["path"]),item,data.revision,
                                      data.model_dump(),data.reason)

    @app.post("/api/projects/{identity}/memory/candidates/{chapter}/commit")
    def commit_memory_candidates(identity: str,chapter: int):
        if chapter<=0:raise ValueError("章节号无效")
        path=Path(project(identity)["path"])
        return memory_library.commit_candidates(path,chapter,memory_library.current_digest(path,chapter))

    @app.get("/api/projects/{identity}/characters")
    def characters(identity: str,chapter: int=0):
        return character_state.view(Path(project(identity)["path"]),chapter)

    @app.get("/api/projects/{identity}/continuity")
    def continuity_view(identity: str,chapter: int=0):
        return continuity.view(Path(project(identity)["path"]),chapter)

    @app.post("/api/projects/{identity}/foreshadow/{item}/transition")
    def foreshadow_transition(identity: str,item: str,data: ForeshadowInput):
        return continuity.transition(Path(project(identity)["path"]),item,data.revision,data.state,
                                     chapter=data.chapter,event=data.event,quote=data.quote,sha256=data.sha256,
                                     expected=data.expected,note=data.note,author=data.author)

    @app.get("/api/projects/{identity}/workflow")
    def workflow_state(identity: str):
        return workflow.state(Path(project(identity)["path"]))

    @app.get("/api/projects/{identity}/scenes")
    def scenes_view(identity: str,chapter: int=0,count: int=2,word_count: int=3500):
        root=Path(project(identity)["path"])
        target=chapter if chapter>0 else writer_runner.next_chapter_id(root)
        return {**scenes.public(root,target,count=count,word_count=word_count),"estimate_detail":scene_writer.estimate(count)}

    @app.post("/api/projects/{identity}/continuity/index")
    def continuity_index(identity: str):
        return continuity.build_index(Path(project(identity)["path"]))

    @app.post("/api/projects/{identity}/continuity/rebuild")
    def continuity_rebuild(identity: str,chapter: int=0):
        return continuity.rebuild(Path(project(identity)["path"]),chapter or None)

    @app.post("/api/projects/{identity}/characters")
    def add_character(identity: str,data: CharacterInput):
        profile = {"identity": data.identity} if data.identity else {}
        return character_state.upsert_person(Path(project(identity)["path"]),name=data.name,
                                             aliases=data.aliases,profile=profile,origin="作者录入")

    @app.put("/api/projects/{identity}/characters/{person}/correct")
    def correct_character(identity: str,person: str,data: CharacterCorrectionInput):
        return character_state.correct(Path(project(identity)["path"]),person,field=data.field,
                                       value=data.value,reason=data.reason)

    @app.post("/api/projects/{identity}/characters/candidates/{chapter}/commit")
    def commit_character_candidates(identity: str,chapter: int):
        if chapter<=0:raise ValueError("章节号无效")
        path=Path(project(identity)["path"])
        body=[p for p,n in writer_runner._chapter_files(path) if n==chapter]
        if len(body)!=1:raise ValueError("正文来源缺失或章节重复")
        digest=hashlib.sha256(body[0].read_bytes()).hexdigest()
        return character_state.commit_candidates(path,chapter,digest)

    @app.post("/api/projects/{identity}/memory/rebuild")
    def rebuild_memory(identity: str):
        item=project(identity)
        if not public_ai()["configured"]:raise ValueError("请先配置 AI 模型")
        return ops.start("memory",["memory-rebuild","--project",item["path"]],f"project:{identity}",{"project_id":identity})

    @app.post("/api/projects/{identity}/samples")
    async def upload_sample(identity: str,file: UploadFile=File(...)):
        try:
            raw=await file.read(studio.MAX_UPLOAD+1)
            return studio.upload(Path(project(identity)["path"]),file.filename or "",raw)
        finally:await file.close()

    @app.post("/api/projects/{identity}/samples/{sample}/learn")
    def learn_sample(identity: str,sample: str,data: LearnInput):
        item=project(identity);studio.project_file(Path(item["path"]),"samples",sample)
        if not public_ai()["configured"]:raise ValueError("请先配置 AI 模型")
        args=["learn","--project",item["path"],"--sample-id",sample,"--revision",str(data.revision)]
        if data.full:args.append("--full")
        return ops.start("learn",args,f"project:{identity}",{"project_id":identity,"sample_id":sample})

    @app.get("/api/projects/{identity}/style-profile")
    def style_public(identity: str):
        return style_profile.public(Path(project(identity)["path"]))

    @app.put("/api/projects/{identity}/style-profile")
    def style_options(identity: str,data: StyleProfileInput):
        path=Path(project(identity)["path"])
        style_profile.options(path,enabled=data.enabled,strength=data.strength,overrides=data.overrides)
        return style_profile.public(path)

    @app.post("/api/projects/{identity}/style-profile/rebuild")
    def style_rebuild(identity: str):
        path=Path(project(identity)["path"])
        style_profile.rebuild(path)
        return style_profile.public(path)

    @app.post("/api/projects/{identity}/samples/{sample}/delete")
    def delete_sample(identity: str,sample: str):
        path=Path(project(identity)["path"])
        studio.project_file(path,"samples",sample)
        return studio.delete_sample(path,sample)

    @app.post("/api/projects/{identity}/plan")
    def plan_project(identity: str,data: PlanInput):
        item=project(identity)
        if not public_ai()["configured"]:raise ValueError("请先配置 AI 模型")
        return ops.start("plan",["plan","--project",item["path"],"--count",str(data.count)],f"project:{identity}",{"project_id":identity})

    @app.get("/api/projects/{identity}/plan")
    def current_plan(identity: str):
        return studio.recover_plan(Path(project(identity)["path"]),persist=False)

    @app.post("/api/projects/{identity}/batches/{batch}/resume")
    def resume_batch(identity: str,batch: str):
        item=project(identity);path=studio.project_file(Path(item["path"]),"batches",batch)
        if not path.is_file():raise KeyError("批次不存在")
        return ops.start("generate",["batch","--project",item["path"],"--batch-id",batch],f"project:{identity}",{"project_id":identity,"batch_id":batch})

    @app.post("/api/projects/{identity}/chapters/{chapter}/polish")
    def polish_chapter(identity: str,chapter: int):
        if chapter<=0:raise ValueError("章节号无效")
        item=project(identity)
        if not public_ai()["configured"]:raise ValueError("请先配置 AI 模型")
        return ops.start("polish",["polish","--project",item["path"],"--chapter",str(chapter)],f"project:{identity}",{"project_id":identity})

    @app.get("/api/projects/{identity}/chapters/{chapter}")
    def chapter(identity: str, chapter: int):
        items = [x for x in bridge.iter_source_chapters(Path(project(identity)["path"])) if x[1] == chapter]
        if len(items) != 1:
            raise HTTPException(409 if items else 404, "章节重复，请检查正文文件" if items else "未找到章节")
        words = len([c for c in items[0][3] if not c.isspace()])
        from integration import quality_gate, writer_runner
        receipts = writer_runner.reviewed_chapters(Path(project(identity)["path"]))
        return {"content": items[0][3], "title": items[0][2], "id": chapter, "words": words,
                "reviewed": chapter in receipts,
                "review_status": (receipts.get(chapter) or {}).get("review", {}).get("review_decision")}

    @app.get("/api/projects/{identity}/chapters/{chapter}/quality")
    def chapter_quality(identity: str, chapter: int):
        """最小质量入口：结论、总分、主要问题、受限范围、过期原因。只读，不调用模型。"""
        if chapter <= 0: raise ValueError("章节号无效")
        from integration import quality_gate
        return quality_gate.public_report(Path(project(identity)["path"]), chapter)

    @app.get("/api/projects/{identity}/chapters/{chapter}/revision")
    def chapter_revision(identity: str, chapter: int):
        """最后一次待处理的修订候选：差异、原因、留给作者的问题。只读。"""
        if chapter <= 0: raise ValueError("章节号无效")
        from integration import revision_plan
        return revision_plan.public(Path(project(identity)["path"]), chapter)

    @app.post("/api/projects/{identity}/chapters/{chapter}/revision")
    def start_revision(identity: str, chapter: int):
        if chapter <= 0: raise ValueError("章节号无效")
        item = project(identity)
        if not public_ai()["configured"]: raise ValueError("请先配置 AI 模型")
        return ops.start("polish", ["polish", "--project", item["path"], "--chapter", str(chapter), "--preview"],
                         f"project:{identity}", {"project_id": identity})

    @app.post("/api/projects/{identity}/chapters/{chapter}/revision/accept")
    def accept_revision(identity: str, chapter: int, data: RevisionClose):
        if chapter <= 0: raise ValueError("章节号无效")
        from integration import revision_plan
        return revision_plan.accept(Path(project(identity)["path"]), chapter, data.preview_id)

    @app.post("/api/projects/{identity}/chapters/{chapter}/revision/reject")
    def reject_revision(identity: str, chapter: int, data: RevisionClose):
        if chapter <= 0: raise ValueError("章节号无效")
        from integration import revision_plan
        return revision_plan.reject(Path(project(identity)["path"]), chapter, data.preview_id, data.reason)

    @app.get("/api/projects/{identity}/chapters/{chapter}/workbench")
    def chapter_workbench(identity: str, chapter: int):
        """质量工作台：报告、版本、候选、最佳推荐一次返回，正文按需另取。"""
        if chapter <= 0: raise ValueError("章节号无效")
        from integration import version_history
        return version_history.workbench(Path(project(identity)["path"]), chapter, config=load_ai())

    @app.get("/api/projects/{identity}/chapters/{chapter}/versions")
    def chapter_versions_list(identity: str, chapter: int):
        if chapter <= 0: raise ValueError("章节号无效")
        from integration import version_history
        return version_history.history(Path(project(identity)["path"]), chapter, config=load_ai())

    @app.get("/api/projects/{identity}/chapters/{chapter}/versions/{version}")
    def chapter_version_body(identity: str, chapter: int, version: str):
        if chapter <= 0: raise ValueError("章节号无效")
        if not re.fullmatch(r"[0-9a-f]{64}", version): raise ValueError("版本标识无效")
        from integration import version_history
        return version_history.read(Path(project(identity)["path"]), chapter, version)

    @app.post("/api/projects/{identity}/chapters/{chapter}/restore")
    def restore_chapter(identity: str, chapter: int, data: RestoreInput):
        if chapter <= 0: raise ValueError("章节号无效")
        from integration import version_history
        return version_history.restore(Path(project(identity)["path"]), chapter, data.version_id, config=load_ai())

    @app.post("/api/projects/{identity}/chapters/{chapter}/review")
    def review_existing(identity: str, chapter: int):
        item = project(identity)
        if chapter <= 0:
            raise ValueError("章节号必须大于 0")
        if not public_ai()["configured"]:
            raise ValueError("请先完成 AI 设置")
        return ops.start("review", ["review", "--project", item["path"], "--chapter", str(chapter)], f"project:{identity}")

    @app.get("/api/projects/{identity}/outline")
    def outline(identity: str):
        folder = Path(project(identity)["path"]) / "大纲"
        files = sorted(folder.glob("*.md"))
        # Editing a multi-file outline as a concatenation would duplicate chapters.
        return {"content": "\n\n".join(p.read_text(encoding="utf-8") for p in files), "editable": len(files) <= 1,
                "files": [p.name for p in files]}

    @app.put("/api/projects/{identity}/outline")
    def save_outline(identity: str, data: ContentInput):
        path = Path(project(identity)["path"])
        files = sorted((path / "大纲").glob("*.md"))
        if len(files) > 1:
            raise HTTPException(409, "多文件大纲请在写作系统中按卷编辑，避免合并造成重复")
        target = files[0] if files else path / "大纲" / "卷一.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        # The writer uses this same OS lock for context collection and save.
        with writer_runner.file_lock(path / ".webnovel" / "writer.lock"):
            if target.exists():
                backup = DATA / "backups" / f"{identity}-{uuid.uuid4().hex}-outline.md"
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(target.read_bytes())
            bridge._write_text_atomic(target, data.content)
        return {"success": True}

    @app.post("/api/projects/{identity}/generate")
    def generate(identity: str, data: GenerateInput):
        item = project(identity)
        if not public_ai()["configured"]:
            raise ValueError("请先完成 AI 设置")
        batch=uuid.uuid4().hex
        return ops.start("generate", ["batch", "--project", item["path"], "--word-count", str(data.word_count),
                          "--max-revisions", str(data.max_revisions),"--count",str(data.count),"--batch-id",batch,
                          "--scenes",str(data.scenes)], f"project:{identity}",{"project_id":identity,"batch_id":batch,"scenes":data.scenes})

    @app.post("/api/projects/{identity}/stage")
    def stage(identity: str, data: StageInput):
        item = project(identity)
        args = ["stage", "--project", item["path"], "--book", data.book]
        for cid in data.chapters or []:
            if cid <= 0:
                raise ValueError("章节号必须大于 0")
            args.extend(["--chapter", str(cid)])
        return ops.start("stage", args, f"project:{identity}")

    @app.get("/api/accounts")
    def accounts():
        return bridge.list_accounts()

    @app.post("/api/accounts/login")
    def login(data: AccountInput):
        name = data.name.strip()
        if bridge.safe_dir_name(name) != name:
            raise ValueError("账号名称不能含路径分隔符、保留名或特殊文件字符")
        folder = bridge.account_dir(name)
        folder.mkdir(parents=True, exist_ok=True)
        if not (folder / "profile.json").exists():
            bridge.write_json_atomic(folder / "profile.json", {"name": name})
        return ops.start("login", ["login", "--account", name], f"login:{name}", {"account": name})

    @app.post("/api/accounts/{name}/confirm-login")
    def confirm(name: str):
        return ops.confirm_login(name)

    @app.post("/api/publish")
    def publish(data: PublishInput):
        item = project(data.project_id)
        if not bridge.account_state_path(data.account).is_file():
            raise ValueError("请先登录所选番茄账号")
        book = platform_book(item) or data.book.strip()
        if not book:
            raise ValueError("请填写平台书名")
        return ops.start("publish", ["publish", "--project", item["path"], "--book", book,
            "--account", data.account, "--count", str(data.count), "--ai-used", "1" if data.ai_used else "0"],
            f"project:{data.project_id}", {"book": book, "account": data.account})

    @app.get("/api/jobs")
    def list_jobs():
        return [scheduler._job_summary(identity, job) | {"max_revisions": job.get("max_revisions", 2)}
                for identity, job in scheduler.load_scheduler()["jobs"].items() if isinstance(job, dict)]

    @app.post("/api/jobs")
    def add_job(data: JobInput):
        if not any(Path(x["path"]).resolve() == Path(data.project).resolve() for x in store.projects()):
            raise ValueError("请先登记写作项目")
        values = data.model_dump()
        values["job_id"] = data.job_id or data.id or uuid.uuid4().hex[:12]
        values["disabled"] = not data.enabled
        values["volume"] = None
        return scheduler.add_job(argparse.Namespace(**values))

    @app.put("/api/jobs/{identity}")
    def edit_job(identity: str, data: JobInput):
        if not any(Path(x["path"]).resolve() == Path(data.project).resolve() for x in store.projects()):
            raise ValueError("请先登记写作项目")
        values = data.model_dump(exclude={"id", "job_id"})
        if "quota_phases" not in data.model_fields_set:
            # Older clients editing ordinary fields must not erase a saved plan.
            values.pop("quota_phases", None)
        if "slot_quotas" not in data.model_fields_set:
            values.pop("slot_quotas", None)
        if "delivery_mode" not in data.model_fields_set:
            values.pop("delivery_mode", None)
        if hasattr(scheduler, "update_job"):
            return scheduler.update_job(identity, values)
        raise HTTPException(503, "任务更新接口尚不可用")

    @app.post("/api/jobs/{identity}/run")
    def run(identity: str):
        document = scheduler.load_scheduler()
        job = document["jobs"].get(identity)
        if not isinstance(job, dict):
            raise KeyError("任务不存在")
        # serial 模式的执行由常驻协调器完成；但“立即执行”必须真正跑一步，
        # 否则 worker 只调用 ensure_started() 并返回 configured，界面显示成功
        # 而任务从未执行（曾导致失败批次无法从界面恢复）。
        extra = ["--serial-step"] if job.get("delivery_mode") == "serial" else []
        return ops.start("daily", ["run", "--job-id", identity, *extra], f"job:{identity}")

    @app.post("/api/jobs/{identity}/recover")
    def recover_job(identity: str):
        """Diagnose and, when provably safe, un-stick a stopped serial batch."""
        document = scheduler.load_scheduler()
        if not isinstance(document["jobs"].get(identity), dict):
            raise HTTPException(404, "任务不存在")
        try:
            return recovery.recover(identity, apply=True)
        except (ValueError, KeyError, RuntimeError, OSError) as exc:
            raise HTTPException(409, redact(str(exc))[:2000]) from exc

    @app.post("/api/jobs/{identity}/approve")
    def approve(identity: str, data: ApproveInput):
        return scheduler.approve_job(identity, data.for_date)

    @app.get("/api/operations/{identity}")
    def operation(identity: str):
        return store.operation(identity)

    @app.post("/api/operations/{identity}/cancel")
    def cancel(identity: str):
        return ops.cancel(identity)

    @app.get("/api/ai")
    def ai_settings():
        return public_ai()

    @app.put("/api/ai")
    def save_ai(data: AIInput):
        base_url = ai_tools.validate_url(data.base_url)
        if not data.model.strip():
            raise ValueError("请选择或填写模型 ID")
        with writer_runner.file_lock(AI_PATH.with_suffix(".lock"),blocking=True):
            config = load_ai()
            key = ai_tools.resolved_key(base_url, data.api_key, config)
            for role in config.get("roles",{}).values():
                if isinstance(role,dict) and role.get("api_key") and not role.get("base_url"):
                    role["base_url"]=config.get("base_url","https://api.openai.com/v1")
            config.update(base_url=base_url, model=data.model.strip())
            if key:config["api_key"] = key
            from integration.providers import bind_legacy
            bind_legacy(config,['default'])
            _persist_ai(config)
        return public_ai()

    @app.put("/api/ai/roles")
    def save_roles(data: RolesInput):
        if set(data.roles)-set(model_roles.ROLES):raise ValueError("分工只能为 A–E")
        with writer_runner.file_lock(AI_PATH.with_suffix(".lock"),blocking=True):
            config=load_ai();old=config.get("roles",{});selected={}
            for role in model_roles.ROLES:
                value=data.roles.get(role,RoleInput()).model_dump()
                previous=old.get(role,{})
                url=ai_tools.validate_url(value["base_url"]) if value["base_url"].strip() else ""
                old_url=previous.get("base_url") or config.get("base_url","https://api.openai.com/v1")
                key=value.get("api_key","")
                effective=url or config.get("base_url","https://api.openai.com/v1")
                if key and key.strip():secret=key.strip()
                elif previous.get("api_key") and ai_tools.validate_url(old_url)!=ai_tools.validate_url(effective):raise ValueError(f"模型 {role} 接口已变更，需要填写新密钥")
                else:secret=previous.get("api_key","")
                selected[role]={**previous,"base_url":url or (effective if secret else ""),"model":value["model"].strip(),"api_key":secret}
            config.update(roles=selected,multi_model=data.multi_model,polish_mode=data.polish_mode,review_policy=data.review_policy)
            from integration.providers import bind_legacy
            bind_legacy(config,list(model_roles.ROLES))
            if data.multi_model:
                for role in model_roles.ROLES:model_roles.connection(role,config)
            _persist_ai(config)
        return public_ai()

    @app.post("/api/ai/models")
    def discover_models(data: ModelDiscoveryInput):
        saved=load_ai()
        if data.role:
            connection=saved.get("roles",{}).get(data.role,{})
            saved={"base_url":connection.get("base_url") or saved.get("base_url","https://api.openai.com/v1"),
                "api_key":connection.get("api_key") or (saved.get("api_key","") if not connection.get("base_url") or connection.get("base_url")==saved.get("base_url") else "")}
        return ai_tools.discover(data.base_url, data.api_key, saved)

    @app.post("/api/ai/test")
    def test_ai():
        if not public_ai()["configured"]:
            raise ValueError("请先保存 AI 配置")
        return ops.start("ai_test", ["ai-test"], "ai-test")

    @app.post("/api/ai/roles/{role}/test")
    def test_role(role: str):
        model_roles.connection(role,load_ai())
        return ops.start("ai_test",["ai-test","--role",role],f"ai-test:{role}")

    @app.post("/api/ai/roles/test")
    def test_all_roles():
        config=load_ai()
        for role in model_roles.ROLES:model_roles.connection(role,config)
        return ops.start("ai_test",["ai-roles-test"],"ai-test:roles")

    @app.get("/api/settings")
    def settings():
        return {"scheduler_enabled": bool(scheduler.load_scheduler().get("settings", {}).get("auto_schedule", False))}

    @app.put("/api/settings")
    def save_settings(data: SettingsInput):
        if data.scheduler_enabled and writer_runner.strict_json(DATA/'maintenance.json',{}).get('state')=='maintenance':
            raise HTTPException(409,'正在维护升级，暂不能开启新任务派发')
        scheduler.update_settings({"auto_schedule": data.scheduler_enabled})
        return settings()

    @app.get("/api/diagnostics")
    def checks():
        return diagnostics()

    def cost_filters(project_id, chapter, days):
        if chapter is not None and (chapter < 0 or chapter > 100000): raise ValueError("章节号无效")
        if days not in {0,7,30,90}: raise ValueError("统计范围支持全部、7、30 或 90 天")
        return {"project":Path(project(project_id)["path"]) if project_id else None,"chapter":chapter,"days":days}

    @app.get("/api/costs")
    def cost_report(project_id: str="", chapter: int | None=None, days: int=0):
        return costs.report(DATA / "costs.sqlite3",**cost_filters(project_id,chapter,days))

    @app.get("/api/costs/pricing")
    def cost_pricing():
        return costs.catalog(DATA / "costs.sqlite3",load_ai())

    @app.put("/api/costs/pricing")
    def set_cost_pricing(data: CostPricingInput):
        return costs.save_prices(DATA / "costs.sqlite3",data.model_dump())

    @app.get("/api/costs/export")
    def cost_export(project_id: str="", chapter: int | None=None, days: int=0):
        value=costs.export_csv(DATA / "costs.sqlite3",**cost_filters(project_id,chapter,days))
        return Response(value,media_type="text/csv",headers={"Content-Disposition":'attachment; filename="novel-costs.csv"'})

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    if STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="小说助手本地管理界面")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--lan", action="store_true", help="允许已配对设备通过局域网或 Tailscale 访问")
    args = parser.parse_args()
    hosts = device_access.local_addresses() if args.lan else []
    # Bind explicit private interfaces only. Never listen on a campus/public IP.
    sockets = device_access.listen_sockets(["127.0.0.1", *hosts], args.port)
    try:
        config = uvicorn.Config(create_app(network_hosts=hosts, port=args.port), proxy_headers=False, access_log=False)
        uvicorn.Server(config).run(sockets=sockets)
    finally:
        for sock in sockets:
            sock.close()


if __name__ == "__main__":
    main()
