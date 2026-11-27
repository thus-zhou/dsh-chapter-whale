"""Local and paired-device management API, durable operations and static UI.

Long-running AI/browser work runs in subprocesses so the API stays responsive.
The SQLite ledger survives restart; incomplete operations are explicitly interrupted.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import math
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
from integration import concurrent_engine
from manager import ai_tools, device_access, api_v08, api_v085, api_v09
from integration import model_roles, studio, memory_library, style_profile, secret_store, character_state, continuity, scenes, scene_writer, workflow
from integration import entity_state, evidence_usage, invalidation, retrieval_plan, style_rules
from integration import observation, reader_metrics
from integration import browser_target
from integration import publishing
from integration import costs

DATA = bridge.COMBINED_ROOT / "integration_data"
# 后台通知投递间隔；测试可改小以免等待 3 秒。
NOTIFY_INTERVAL_SECONDS = 3.0
# main() 在监听前写入实际端口；进程内 create_app() 测试时保持 None。
_LISTEN_PORT = None
# Serializes "find existing (project, publication_mode) + create/update" in this
# process. Lock order is always _JOBS_CREATE_LOCK -> scheduler config lock.
_JOBS_CREATE_LOCK = threading.Lock()


def project_path_key(path_str: str) -> str:
    """Stable, non-empty project key for unregistered/CLI paths."""
    try:
        target = str(Path(path_str).expanduser().resolve())
    except (OSError, RuntimeError):
        target = str(path_str or "").strip()
    if not target:
        return ""
    return "path:" + hashlib.sha1(target.casefold().encode("utf-8")).hexdigest()


def _deliver_notifications_once(owner):
    """每次调用各自开连接：sqlite3 连接不可跨线程复用。"""
    from integration import notification_hooks, notifications
    db = notification_hooks.connection()
    try:
        notifications.recover_stale_leases(db)
        return notifications.run_once(db, owner, limit=5)
    finally:
        db.close()
DB_PATH = Path(os.getenv("NOVEL_HELPER_MANAGER_DB", str(DATA / "manager.sqlite3"))).resolve()
# 允许用 NOVEL_HELPER_AI_CONFIG 覆盖（README 承诺；旧实现硬编码 O 盘路径，
# 导致界面与 CLI 可能读写不同配置文件）。
AI_PATH = Path(os.getenv("NOVEL_HELPER_AI_CONFIG") or str(DATA / "ai_config.json")).resolve()
STATIC = Path(__file__).resolve().parent / "static"
PYTHON = Path(sys.executable) if sys.executable else (
    bridge.COMBINED_ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")
)
logger = logging.getLogger("chapter_whale.manager")


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
                CREATE UNIQUE INDEX IF NOT EXISTS operations_operation_key
                    ON operations(json_extract(payload, '$.operation_key'))
                    WHERE json_extract(payload, '$.operation_key') IS NOT NULL;
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

    def operation_by_key(self, operation_key):
        """同一个操作键永久只对应一条运行记录，跨重启有效。"""
        if not operation_key:
            return None
        with self.connect() as db:
            row = db.execute("SELECT payload FROM operations WHERE json_extract(payload, '$.operation_key')=?",
                             (operation_key,)).fetchone()
        return json.loads(row[0]) if row else None

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
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        import signal
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except OSError:
                process.terminate()


class Operations:
    def __init__(self, store: Store):
        self.store = store
        self.lock = threading.RLock()
        self.processes: dict[str, subprocess.Popen] = {}
        self.cancelled: set[str] = set()
        self.login_confirmed: set[str] = set()
        # Reconciliation prevents a restart from showing indefinitely "running".
        for old in store.operations(active_only=True):
            if old.get("status") in {"queued", "running", "awaiting_login"}:
                old.update(status="interrupted", finished_at=bridge.now_iso(), error="管理服务已重启；请核对队列后重新执行")
                store.save_operation(old)

    def start(self, *args, **kwargs):
        try:
            with writer_runner.file_lock(DATA / 'upgrade-admission.lock'):
                return self._start_admitted(*args, **kwargs)
        except RuntimeError as exc:
            if '已有任务正在运行' not in str(exc):
                raise
            raise HTTPException(409, '正在维护或接收其他任务，请稍后重试') from None

    def _project_id_for_path(self, path_str: str) -> str:
        raw = str(path_str or "").strip()
        if not raw:
            return ""
        try:
            target = str(Path(raw).expanduser().resolve())
        except (OSError, RuntimeError):
            target = raw
        for p in self.store.projects():
            try:
                if str(Path(p["path"]).expanduser().resolve()) == target:
                    return p["id"]
            except (OSError, RuntimeError, KeyError, TypeError):
                continue
        return project_path_key(target)

    def _start_admitted(self, kind: str, args: list[str], identity: str, metadata: dict | None = None,
              operation_key: str | None = None):
        signature = None
        if operation_key:
            from hashlib import sha256
            request_args = list(args)
            if kind == "generate" and "--batch-id" in request_args:
                position = request_args.index("--batch-id")
                del request_args[position:position + 2]
            signature = sha256(json.dumps(request_args).encode()).hexdigest()

        def reused(existing):
            if (existing.get("identity") != identity or existing.get("kind") != kind
                    or existing.get("request_signature", signature) != signature):
                raise HTTPException(409, "操作键已用于另一作品、操作或参数，请重新提交")
            return {**existing, "deduplicated": True}

        with self.lock:
            # 稳定操作键先于任何派发检查：刷新、双击或丢应答后的重试都回到同一条记录。
            if operation_key:
                existing = self.store.operation_by_key(operation_key)
                if existing:
                    return reused(existing)
            # 审计 C-09：「全站急停」必须拦住真正的自动化入口，而不只是
            # 没有消费者的 v0.9 /tasks/claim。
            if concurrent_engine.global_paused(DATA / "global_pause.json"):
                raise HTTPException(503, "全站急停中，已阻止新的操作；恢复后可重试")
            pause_project = str((metadata or {}).get("project_path") or "")
            if not pause_project:
                try:
                    pause_project = str(args[list(args).index("--project") + 1])
                except (ValueError, IndexError):
                    pause_project = ""
            if pause_project and concurrent_engine.project_paused(pause_project):
                raise HTTPException(409, "该作品已暂停自动化，请恢复后再执行")
            if writer_runner.strict_json(DATA/'maintenance.json',{}).get('state')=='maintenance':
                raise HTTPException(409,'正在维护升级，暂不派发新操作；完成后可继续原任务')
            active = self.store.operations(active_only=True)
            if any(x.get("identity") == identity for x in active):
                raise HTTPException(409, "同一操作正在执行，请查看运行记录")
            meta_pid = (metadata or {}).get("project_id")
            if kind in {"generate", "daily"}:
                if not meta_pid and kind == "daily":
                    # 审计 P2-14：daily 通常只带 --job-id，必须从调度任务解析项目，
                    # 否则项目互斥会被空 project_id 静默跳过。
                    try:
                        position = list(args).index("--job-id")
                        daily_job = scheduler.load_scheduler().get("jobs", {}).get(str(args[position + 1]))
                    except (ValueError, IndexError, OSError, RuntimeError):
                        daily_job = None
                    if isinstance(daily_job, dict):
                        meta_pid = self._project_id_for_path(str(daily_job.get("project") or ""))
                        if meta_pid:
                            metadata = {**(metadata or {}), "project_id": meta_pid}
                if not meta_pid:
                    # Unregistered/CLI paths still get a stable key; an empty
                    # project_id must never silently disable the project mutex.
                    try:
                        position = list(args).index("--project")
                        meta_pid = self._project_id_for_path(str(args[position + 1]))
                    except (ValueError, IndexError):
                        meta_pid = ""
                    if meta_pid:
                        metadata = {**(metadata or {}), "project_id": meta_pid}
                if meta_pid and any(
                    x.get("project_id") == meta_pid and x.get("kind") in {"generate", "daily"}
                    and x.get("status") in {"queued", "running", "awaiting_login", "waiting"}
                    for x in active
                ):
                    raise HTTPException(409, "该作品已有写作或日更任务正在执行，请等待完成后再试")
            payload = {"id": uuid.uuid4().hex, "kind": kind, "identity": identity,
                       "created_at": bridge.now_iso(), "status": "queued", "log_tail": "",
                       "progress": {"percent": 0, "stage": "queued", "label": "等待执行", "current": 0, "total": 0, "indeterminate": True},
                       **(metadata or {})}
            if operation_key:
                payload["operation_key"] = operation_key
                payload["request_signature"] = signature
            try:
                self.store.save_operation(payload)
            except sqlite3.IntegrityError:
                # 另一个进程抢先写入同一个操作键：返回它，绝不再派发第二次。
                existing = self.store.operation_by_key(operation_key)
                if not existing:
                    raise
                return reused(existing)
            thread = threading.Thread(target=self._execute, args=(payload["id"], args), daemon=True)
            thread.start()
        return payload

    @staticmethod
    def _percent(value, default=0):
        if isinstance(value, bool):
            return default
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(number):
            return default
        return max(0, min(100, int(round(number))))

    @classmethod
    def _merge_progress(cls, current, incoming):
        """Monotonic, type-checked progress; malformed values are ignored, not fatal."""
        cur = dict(current or {})
        previous = cls._percent(cur.get("percent"), 0)
        if "percent" in incoming:
            cur["percent"] = max(previous, cls._percent(incoming.get("percent"), previous))
        if isinstance(incoming.get("stage"), str):
            cur["stage"] = incoming["stage"][:40]
        if isinstance(incoming.get("label"), str):
            cur["label"] = incoming["label"][:200]
        for key in ("current", "total", "chapter"):
            value = incoming.get(key)
            if type(value) is int and value >= 0:
                cur[key] = value
        cur["indeterminate"] = False
        return cur

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
                    project=next((x for x in self.store.projects() if x['id']==payload.get('project_id')),None)
                    if project is None:
                        try:
                            wanted=Path(str(result.get('project') or '')).expanduser().resolve()
                        except (OSError, RuntimeError):
                            wanted=None
                        project=next((x for x in self.store.projects()
                                      if wanted is not None and Path(x['path']).expanduser().resolve()==wanted),None)
                    if project is None:
                        raise ValueError('等待批次的作品已不在登记表中')
                    if concurrent_engine.project_paused(project['path']):
                        continue
                    project_key=project['id']
                    if payload.get('project_id')!=project_key:
                        payload['project_id']=project_key
                    # 在唤醒前复检项目互斥：另一个同项目操作可能已排队/运行/等待。
                    if any(x['id']!=payload['id'] and x.get('kind') in {'generate','daily'}
                           and x.get('project_id')==project_key
                           and x.get('status') in {'queued','running','awaiting_login','waiting'}
                           for x in records):
                        continue
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
            cancelled_before_spawn = False
            with self.lock:
                if identity in self.cancelled:
                    payload.update(status="cancelled", finished_at=bridge.now_iso())
                    self.store.save_operation(payload)
                    return
            popen_kwargs: dict[str, Any] = {
                "cwd": str(ROOT), "env": env, "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                "text": True, "encoding": "utf-8", "errors": "replace",
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            else:
                popen_kwargs["start_new_session"] = True
            process = subprocess.Popen([str(PYTHON), "-X", "utf8", "-u", str(ROOT / "manager" / "worker.py"), *args], **popen_kwargs)
            with self.lock:
                self.processes[identity] = process
                cancelled_before_spawn = identity in self.cancelled
            if cancelled_before_spawn:
                stop_process_tree(process)
            payload.update(
                status="running",
                pid=process.pid,
                progress={
                    **(payload.get("progress") or {}),
                    "stage": "running",
                    "label": "正在执行",
                    "percent": max(5, self._percent((payload.get("progress") or {}).get("percent"), 0)),
                    "indeterminate": True,
                },
            )
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
                    stripped = line.strip()
                    if stripped.startswith("NOVEL_HELPER_PROGRESS:"):
                        try:
                            prog = json.loads(stripped[len("NOVEL_HELPER_PROGRESS:"):])
                            if isinstance(prog, dict):
                                payload["progress"] = self._merge_progress(payload.get("progress"), prog)
                                self.store.save_operation(payload)
                                continue
                        except ValueError:
                            pass
                    payload["log_tail"] = (payload.get("log_tail", "") + redact(line))[-16000:]
                    with self.lock:
                        confirmed = identity in self.login_confirmed
                    if line.startswith("NOVEL_HELPER_WAITING_LOGIN"):
                        if not confirmed:
                            payload["status"] = "awaiting_login"
                            payload["progress"] = {**(payload.get("progress") or {}), "stage": "login", "label": "等待浏览器登录确认", "indeterminate": True}
                    elif confirmed and payload.get("status") == "awaiting_login":
                        payload["status"] = "running"
                    else:
                        inferred = None
                        if "创作第" in stripped:
                            inferred = ("B", stripped[:40], 20, False)
                        elif "模型 C 正在润色" in stripped:
                            inferred = ("C", "模型 C 润色中", 55, False)
                        elif "自动审查" in stripped or "审查" in stripped:
                            inferred = ("D", "模型 D 审查中", 75, False)
                        elif "示范分析" in stripped:
                            inferred = ("learn", stripped[:40], 50, False)
                        elif "共享记忆补建" in stripped:
                            inferred = ("memory", stripped[:40], 60, False)
                        if inferred:
                            cur = dict(payload.get("progress") or {})
                            cur.update(stage=inferred[0], label=inferred[1], percent=max(self._percent(cur.get("percent"), 0), inferred[2]), indeterminate=inferred[3])
                            payload["progress"] = cur
                    self.store.save_operation(payload)
                code = process.wait(timeout=30)
            finally:
                timer.cancel()
            result = bridge.read_json(result_path, {})
            result = json.loads(redact(json.dumps(result, ensure_ascii=False)))
            child_status = result.get("status") if isinstance(result, dict) else None
            benign = {"success", "progress", "generated", "reviewed", "authorized", "queued", "logged_in", "configured", "already_run", "already_ran", "ok", "learned", "planned", "polished", "preview", "memory_synced"}
            if timed_out.is_set():
                payload.update(status="failed", error="运行超过一小时，已停止；请核对平台状态后再试")
            elif code == 0 and child_status in benign:
                payload["status"] = "success"
                payload["progress"] = {**(payload.get("progress") or {}), "percent": 100, "stage": "done", "label": "已完成", "indeterminate": False}
            elif child_status=='waiting' and payload.get('kind')=='generate' and payload.get('batch_id') and result.get('failure_kind') in {'recovery_cooldown','free_pool_wait'} and result.get('next_retry_at'):
                payload.update(status='waiting',error=result.get('error','等待模型恢复'))
                payload["progress"] = {**(payload.get("progress") or {}), "stage": "waiting", "label": "等待模型恢复", "indeterminate": False}
            elif child_status == 'waiting' and result.get('next_retry_at'):
                payload.update(status='deferred', error='等待模型恢复，调度器将继续原批次')
                payload["progress"] = {**(payload.get("progress") or {}), "stage": "waiting", "label": "等待模型恢复", "indeterminate": False}
            elif child_status in {'metadata_pending', 'needs_revision', 'blocked'}:
                payload.update(status=child_status, error=result.get('next_action') or result.get('reason_code') or '需要处理后继续')
                payload["progress"] = {**(payload.get("progress") or {}), "stage": child_status, "label": "需要处理后继续", "indeterminate": False}
            elif child_status in {"awaiting_approval", "disabled", "already_run", "already_ran", "busy"}:
                payload["status"] = child_status
                payload["progress"] = {**(payload.get("progress") or {}), "stage": child_status, "indeterminate": False}
            else:
                payload.update(status="failed", error=result.get("error", "操作失败，请查看日志") if isinstance(result, dict) else "操作失败")
                payload["progress"] = {**(payload.get("progress") or {}), "stage": "failed", "label": "执行失败", "indeterminate": False}
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
                self.login_confirmed.discard(identity)
                if identity in self.cancelled:
                    payload.update(status="cancelled", error="已由用户取消；已提交到平台的章节请核对状态")
                    self.cancelled.discard(identity)
            payload["finished_at"] = bridge.now_iso()
            self.store.save_operation(payload)

    def cancel(self, identity: str):
        process = None
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
                    if process and process.poll() is None and process.stdin:
                        try:
                            process.stdin.write("\n")
                            process.stdin.flush()
                        except (BrokenPipeError, OSError) as exc:
                            raise HTTPException(409, "登录窗口进程已关闭，请重新启动登录") from exc
                        self.login_confirmed.add(op["id"])
                        op["status"] = "running"
                        self.store.save_operation(op)
                        return op
        raise HTTPException(409, "没有等待确认的登录窗口，请先启动登录")

    def shutdown(self):
        with self.lock:
            targets = [process for process in self.processes.values() if process.poll() is None]
        for process in targets:
            stop_process_tree(process)


class ProjectInput(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


class NewProject(BaseModel):
    title: str = Field(min_length=1, max_length=90)
    genre: str = Field(default="玄幻", max_length=90)
    outline: str = Field(default="", max_length=500000)
    premise: str = Field(default="", max_length=3000)


class ContentInput(BaseModel):
    content: str = Field(max_length=500000)


class OutlineInput(ContentInput):
    project_id: str | None = None
    revision: str | None = None


class GenerateInput(BaseModel):
    word_count: int = Field(default=3500, ge=500, le=10000)
    max_revisions: int = Field(default=1, ge=0, le=3)
    count: int = Field(default=1, ge=1, le=30)
    scenes: int = Field(default=0, ge=0, le=3)
    operation_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")


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


class StyleIgnoreInput(BaseModel):
    terms: list[str] = Field(default_factory=list, max_length=40)


class StyleActionInput(BaseModel):
    rule_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z_]+\.[a-z_]+$")
    action: str = Field(pattern=r"^(accepted|ignored|false_positive)$")
    note: str = Field(default="", max_length=200)


class ReaderImportInput(BaseModel):
    csv: str = Field(default="", max_length=2 * 1024 * 1024)
    rows: list[dict] | None = None
    work_id: str = Field(default="", max_length=64)
    platform: str = Field(default="fanqie", max_length=32)
    filename: str = Field(default="", max_length=200)
    token: str = Field(default="", max_length=64)
    allow_partial: bool = False


class ReaderCommentInput(BaseModel):
    chapter: int = Field(ge=1)
    texts: list[str] = Field(default_factory=list, max_length=200)


class ObservationInput(BaseModel):
    chapter: int = Field(ge=1)
    metric: str = Field(default="chapter_completion_rate", max_length=64)
    chapters: int = Field(default=3, ge=1, le=20)
    days: int = Field(default=14, ge=1, le=120)


class ObservationActionInput(BaseModel):
    action: str = Field(pattern=r"^(adopt|ignore|revoke)$")
    chapters: int | None = Field(default=None, ge=1, le=20)
    reason: str = Field(default="", max_length=200)


class BrowserTargetInput(BaseModel):
    os: str = Field(min_length=1, max_length=32)
    arch: str = Field(min_length=1, max_length=16)
    runtime: str = Field(pattern=r"^(native|container)$")
    browser: str = Field(min_length=1, max_length=64)
    browser_version: str = Field(min_length=1, max_length=64)
    driver: str = Field(min_length=1, max_length=64)
    credential: str = Field(min_length=1, max_length=64)
    scope: str = Field(pattern=r"^(read_only|publish)$")
    authorization: str = Field(default="", max_length=200)
    profile: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=64)
    platform: str = Field(default="fanqie", max_length=32)
    account: str = Field(default="", max_length=64)


class BrowserLoginInput(BaseModel):
    status: str = Field(pattern=r"^(unknown|valid|expired|needs_human|cancelled)$")
    account: str = Field(default="", max_length=64)
    evidence: str = Field(default="", max_length=300)
    reason: str = Field(default="", max_length=200)


class BrowserReadonlyInput(BaseModel):
    book_id: str = Field(min_length=1, max_length=64)
    chapter: int = Field(ge=1, le=100000)
    body_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")


class BrowserPublishInput(BaseModel):
    book_id: str = Field(min_length=1, max_length=64)
    chapter: int = Field(ge=1, le=100000)
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    replace: bool = False


class BrowserReconcileInput(BaseModel):
    key: str = Field(default="", pattern=r"^$|^[0-9a-f]{16}$")
    book_id: str = Field(default="", max_length=64)
    chapter: int = Field(default=0, ge=0, le=100000)
    resolution: str = Field(pattern=r"^(accepted|abandoned)$")
    note: str = Field(default="", max_length=200)


class PublishTargetInput(BaseModel):
    platform: str = Field(pattern=r"^(fanqie|qimao)$")
    account: str = Field(default="", max_length=64)
    platform_book_id: str = Field(default="", max_length=64)
    book: str = Field(default="", max_length=96)


class PublishExportInput(BaseModel):
    platform: str = Field(pattern=r"^(fanqie|qimao)$")
    chapter: int = Field(ge=1, le=100000)
    title: str = Field(default="", max_length=120)
    body: str = Field(min_length=1, max_length=400000)
    account: str = Field(min_length=1, max_length=64)
    platform_book_id: str = Field(min_length=1, max_length=64)

    @field_validator("body")
    @classmethod
    def _body_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > publishing.MAX_EXPORT_BYTES:
            raise ValueError(f"正文超过 {publishing.MAX_EXPORT_BYTES} 字节上限（按 UTF-8 计算）")
        return value


class PublishBindInput(BaseModel):
    platform: str = Field(pattern=r"^(fanqie|qimao)$")
    account: str = Field(min_length=1, max_length=64)
    platform_book_id: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=120)
    verified_via: str = Field(default="manual", pattern=r"^(manual|readonly_probe)$")
    observed_chapters: list[int] = Field(default_factory=list, max_length=2000)
    probe_evidence: dict | None = None


class PublishAuthorizeInput(BaseModel):
    platform: str = Field(pattern=r"^(fanqie|qimao)$")
    account: str = Field(min_length=1, max_length=64)
    platform_book_id: str = Field(min_length=1, max_length=64)
    chapters: list[int] = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=300)
    expires_at: str = Field(default="", max_length=40)


class PublishSubmitInput(BaseModel):
    platform: str = Field(pattern=r"^(fanqie|qimao)$")
    account: str = Field(min_length=1, max_length=64)
    platform_book_id: str = Field(min_length=1, max_length=64)
    chapter: int = Field(ge=1, le=100000)
    title: str = Field(default="", max_length=120)
    body: str = Field(min_length=1, max_length=400000)

    @field_validator("body")
    @classmethod
    def _body_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > publishing.MAX_EXPORT_BYTES:
            raise ValueError(f"正文超过 {publishing.MAX_EXPORT_BYTES} 字节上限（按 UTF-8 计算）")
        return value


class PublishReconcileInput(BaseModel):
    platform: str = Field(pattern=r"^(fanqie|qimao)$")
    account: str = Field(min_length=1, max_length=64)
    platform_book_id: str = Field(min_length=1, max_length=64)
    chapter: int = Field(ge=1, le=100000)
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolution: str = Field(pattern=r"^(accepted|abandoned)$")
    note: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=300)


class RestoreInput(BaseModel):
    version_id: str = Field(pattern=r"^(?:[0-9a-f]{64}|ver_\d{4,}_[0-9a-f]{8})$")
    restore_title: bool = True
    op_id: str | None = None


class StageInput(BaseModel):
    book: str = Field(min_length=1, max_length=96)
    chapters: list[int] | None = None


class MemoryItemInput(BaseModel):
    revision: int = Field(ge=0)
    category: str = Field(pattern="^(canon|fact|foreshadow|preference)$")
    title: str = Field(min_length=1,max_length=120)
    content: str = Field(min_length=1,max_length=2000)
    pinned: bool = False
    status: str = Field(default="active",pattern="^(active|conflict|archived|superseded)$")
    source_chapter: int = Field(default=0,ge=0,le=100000)
    due_chapter: int = Field(default=0,ge=0,le=100000)
    clue_state: str = Field(default="",pattern="^(|planned|planted|resolved)$")
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
    preview_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class JobInput(BaseModel):
    job_id: str | None = None
    id: str | None = None
    name: str = Field(default="日更任务", min_length=1, max_length=96)
    project: str
    book: str = Field(min_length=1, max_length=96)
    account: str = Field(default="", max_length=96)
    daily_time: str = "08:00"
    daily_times: list[str] = Field(default_factory=list,max_length=8)
    timezone: str = "Asia/Shanghai"
    chapters_per_run: int = Field(default=1, ge=1, le=50)
    word_count: int = Field(default=3500, ge=500, le=10000)
    quota_phases: list[dict] = Field(default_factory=list, max_length=24)
    slot_quotas: dict[str, int] | None = None
    delivery_mode: str = Field(default="batch", pattern="^(batch|serial)$")
    # None 表示“这个客户端没提这件事”：新建时落到 draft_only，更新时保留原值不擦除。
    publication_mode: str | None = Field(default=None, pattern="^(draft_only|publish_now|platform_scheduled)$")
    # 平台排期缓冲（0.6.1）：None/缺省表示“这个客户端没提”，更新时保留原值。
    schedule_buffer: dict | None = None
    # 非 Optional 的默认值会出现在 model_dump 里：旧客户端不带这些键时，
    # edit_job 必须按 model_fields_set 把它们 pop 掉，否则一次普通保存就会
    # 把 platform 重置成 fanqie、account 清空（审计 P1-7）。
    platform: str = Field(default="fanqie", max_length=32)
    max_revisions: int = Field(default=1, ge=0, le=3)
    enabled: bool = False
    approval_mode: str = "unattended"


class ApproveInput(BaseModel):
    for_date: str | None = None


class RecipientInput(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    secret: str | None = Field(default=None, max_length=512)


class ScheduleBufferInput(BaseModel):
    schedule_buffer: dict = Field(default_factory=dict)
    # 乐观并发：带上客户端看到的台账版本（revision 更强；updated_at 兼容旧客户端）。
    # 两者都没带表示“不申领租约”，允许写入；带了就必须对上，落后即 409。
    expected_updated_at: str | None = Field(default=None, max_length=64)
    expected_revision: int | None = Field(default=None, ge=0)


class ScheduleCapabilityInput(BaseModel):
    observed_at: str | None = Field(default=None, max_length=64)
    source: str = Field(default="", max_length=200)
    evidence: str = Field(default="", max_length=2000)
    can_read_schedule: bool | None = None
    can_schedule: bool | None = None
    can_confirm_schedule: bool | None = None
    can_confirm_body: bool | None = None
    lead_time_minutes: int | None = Field(default=None, ge=0, le=10080)
    max_scheduled: int | None = Field(default=None, ge=0, le=500)
    max_chapters_per_day: int | None = Field(default=None, ge=0, le=200)


class ScheduleReconcileInput(BaseModel):
    """对账输入：既可用适配器回读，也可由作者粘贴/导入只读清单。"""

    rows: list[dict] = Field(default_factory=list)
    complete: bool = True
    source: str = Field(default="", max_length=200)


class ScheduleResolveInput(BaseModel):
    """销账：作者确认平台没有该章，或确认要重新排。"""

    chapter_id: int | str
    resolution: str = Field(default="cancelled", pattern="^(cancelled|planned)$")
    note: str = Field(default="", max_length=400)


class OutboxResolveInput(BaseModel):
    state: str = Field(pattern="^(sent|failed|dead)$")
    note: str = Field(default="", max_length=400)


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
        return secret_store.save(AI_PATH.parent, config, _write_ai_config)
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
        config = secret_store.load(AI_PATH.parent, read_config(AI_PATH))
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
            "credential_store":secret_store.status(AI_PATH.parent)}


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
    next_outline_ready = False
    if outlines and not problem:
        try:
            next_outline_ready = bool(writer_runner._find_outline(path, writer_runner.next_chapter_id(path)))
        except (OSError, ValueError, RuntimeError):
            problem = "无法读取作品细纲或章节进度"
    import hashlib
    revision=hashlib.sha256()
    for entry in sorted([x[0] for x in chapters]+[path/'.webnovel/writer_receipts.json']):
        if entry.is_file():
            stat=entry.stat()
            revision.update(f'{entry.name}:{stat.st_mtime_ns}:{stat.st_size}'.encode())
    return {**item, "title": info.get("title") or state.get("title") or path.name,
            "genre": info.get("genre") or state.get("genre", "未设定"),
            "chapters": len(chapters), "words": sum(len(x[3]) for x in chapters),
            "latest_chapter_id": max((x[1] for x in chapters), default=0),
            "chapters_revision":revision.hexdigest()[:16],
            "outline_count": len(outlines), "ready": next_outline_ready and not problem,
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

    def project_title(path_str: str) -> str:
        p = Path(path_str)
        try:
            state = writer_runner.strict_json(p / ".webnovel" / "state.json", {})
            info = state.get("project_info") if isinstance(state, dict) else {}
            if isinstance(info, dict) and str(info.get("title") or "").strip():
                return str(info["title"]).strip()
            if isinstance(state, dict) and str(state.get("title") or "").strip():
                return str(state["title"]).strip()
        except (OSError, ValueError):
            pass
        return p.name

    def project_id_for_path(path_str: str) -> str:
        try:
            target = str(Path(path_str).expanduser().resolve())
        except (OSError, RuntimeError):
            target = str(path_str or "")
        for p in store.projects():
            try:
                if str(Path(p["path"]).resolve()) == target:
                    return p["id"]
            except OSError:
                continue
        # 未登记/CLI 项目也必须有稳定身份，项目互斥才不会被空串跳过。
        return project_path_key(target)

    async def dispatch():
        while True:
            await asyncio.sleep(20)
            try:
                # 审计 C-09：急停期间连 resume_due / 定时任务派发一起停。
                if concurrent_engine.global_paused(DATA / "global_pause.json"):
                    continue
                await asyncio.to_thread(ops.resume_due)
                for job in await asyncio.to_thread(scheduler.due_jobs):
                    if concurrent_engine.global_paused(DATA / "global_pause.json"):
                        break
                    identity = job["id"]
                    meta = {
                        "job_id": identity,
                        "project_id": project_id_for_path(job.get("project", "")),
                        "project_path": job.get("project", ""),
                        "book": job.get("book") or project_title(job.get("project", "")),
                    }
                    try:
                        ops.start("daily", ["run", "--job-id", identity], f"job:{identity}", meta)
                    except HTTPException:
                        continue
            except (ValueError, KeyError, RuntimeError, OSError, sqlite3.Error) as exc:
                # Malformed config or a transient DB error must not kill the
                # dispatcher: an uncaught sqlite3.OperationalError used to end
                # this coroutine permanently, silently stopping all schedules.
                print(f"调度配置不可用：{redact(str(exc))}", file=sys.stderr)

    async def deliver_notifications():
        """通知发件箱投递循环：只在后台线程发 HTTP，绝不改章节与调度状态。"""
        if os.environ.get("CHAPTER_WHALE_NOTIFY_WORKER", "1") == "0":
            return
        owner = f"notify-{os.getpid()}"
        while True:
            await asyncio.sleep(NOTIFY_INTERVAL_SECONDS)
            try:
                await asyncio.to_thread(_deliver_notifications_once, owner)
            except (ValueError, KeyError, RuntimeError, OSError, sqlite3.Error) as exc:
                print(f"通知投递暂不可用：{redact(str(exc))}", file=sys.stderr)

    @asynccontextmanager
    async def lifespan(app):
        # 审计 C-38：start_dispatcher=False（所有 API 测试）不得启动任何
        # 后台任务；通知投递会写真实通知库并可能发邮件/webhook。
        task = asyncio.create_task(dispatch()) if start_dispatcher else None
        notify_task = asyncio.create_task(deliver_notifications()) if start_dispatcher else None
        if start_dispatcher:
            def _restore_ofm():
                try:
                    from integration import ofm_runtime
                    ofm_runtime.restore_if_enabled()
                except Exception:
                    pass
            threading.Thread(target=_restore_ofm, daemon=True).start()
        yield
        for pending in (task, notify_task):
            if pending:
                pending.cancel()
                try:
                    await pending
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
    provider_api.install(app, load_ai, AI_PATH, costs_db=DATA / "costs.sqlite3")
    api_v08.install(app, project=project, ops=ops, load_ai=load_ai,
                    project_title=project_title, data_dir=DATA)
    api_v085.install(app, project=project, data_dir=DATA)
    api_v09.install(app, project=project, data_dir=DATA)
    # 审计 C-47：并发引擎的唤醒路径 /internal/events/notify 曾完全不存在。
    fanout = concurrent_engine.EventFanout()
    app.state.event_fanout = fanout

    @app.post("/internal/events/notify")
    async def internal_events_notify(request: Request):
        expected = os.environ.get("CHAPTER_WHALE_INTERNAL_TOKEN", "")
        actual = request.headers.get("x-internal-token", "")
        if not expected or not hmac.compare_digest(str(actual), str(expected)):
            return JSONResponse(status_code=403,
                                content={"code": "forbidden", "message": "内部令牌无效"})
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {"value": payload}
        dropped = fanout.publish({"kind": "wake", **payload})
        return {"ok": True, "subscribers_dropped": len(dropped)}
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
            return JSONResponse({"code": "invalid_length", "message": "请求长度无效"},
                                status_code=400)
        if content_length > 32 * 1024 * 1024:
            return JSONResponse({"code": "payload_too_large", "message": "请求体超过32MB上限"},
                                status_code=413)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and \
                request.url.path != "/internal/events/notify":
            if request.headers.get("X-Novel-Helper") != "1":
                return JSONResponse({"code": "header_missing",
                                     "message": "需要管理界面的请求标识"},
                                    status_code=403)
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse({"code": "cross_origin", "message": "拒绝跨站修改请求"},
                                    status_code=403)
            if request.url.path.endswith("/samples"):
                length = content_length
                if length > studio.MAX_UPLOAD + 65536:
                    return JSONResponse({"code": "file_too_large", "message": "文件超过 5 MB"},
                                        status_code=413)
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
                return JSONResponse({"code": "resource_busy", "message": "系统正忙，请稍后重试"},
                                    status_code=503, headers={"Retry-After": "2"})
            try:
                from integration import lock_manager as _locks
                if isinstance(exc, _locks.LockError):
                    status = 503 if exc.code in {"lock_busy", "resource_busy"} else int(exc.status or 409)
                    headers = {"Retry-After": "2"} if status == 503 else None
                    return JSONResponse({"code": exc.code, "message": redact(str(exc))},
                                        status_code=status, headers=headers)
            except Exception:
                pass
            code = 404 if isinstance(exc, (KeyError, FileNotFoundError)) else 409 if isinstance(exc, FileExistsError) else 400
            return JSONResponse({"code": "request_failed", "message": redact(str(exc))},
                                status_code=code)
        app.add_exception_handler(exception, handler)

    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse as _JSON

    async def validation_handler(request, exc):
        first = (exc.errors() or [{}])[0]
        field = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        return _JSON({"code": "invalid_request",
                      "message": f"请求字段不合法：{field or 'body'}（{first.get('msg', '校验失败')}）"},
                     status_code=422)

    app.add_exception_handler(RequestValidationError, validation_handler)

    from fastapi import HTTPException as _HTTPException

    async def http_error_handler(request, exc: "_HTTPException"):
        detail = exc.detail if isinstance(exc.detail, str) else "请求未通过"
        code = {400: "invalid_request", 401: "unauthorized", 403: "forbidden",
                404: "not_found", 405: "method_not_allowed", 409: "conflict",
                413: "payload_too_large", 429: "too_many_requests"}.get(exc.status_code,
                                                                    "request_failed")
        return _JSON({"code": code, "message": detail}, status_code=exc.status_code,
                     headers=getattr(exc, "headers", None))

    app.add_exception_handler(_HTTPException, http_error_handler)

    async def unhandled_handler(request, exc: Exception):
        # 兜底：未登记异常也要给同一个 {"code","message"} 形状，不能让框架返回纯文本 500。
        try:
            logger.exception("未处理的异常：%s %s", request.method, request.url.path)
        except Exception:
            pass
        return _JSON({"code": "internal_error",
                      "message": f"服务内部错误：{redact(str(exc)) or exc.__class__.__name__}"},
                     status_code=500)

    app.add_exception_handler(Exception, unhandled_handler)

    @app.get("/api/health")
    def health():
        maintenance = bridge.read_json(DATA / 'maintenance.json', {})
        return {"status": "healthy", "service": "novel-helper-manager", 'release_id':loaded_release,
            'pid':os.getpid(),'startup_id':STARTUP_ID,'started_at':STARTED_AT,
            'root':str(bridge.COMBINED_ROOT.resolve()),'port':_LISTEN_PORT,
            'mode':os.getenv('CHAPTER_WHALE_SERVICE_MODE','standalone'),
            'schema_version':1, 'upgrade_guard':1,
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
        if data.premise.strip():
            _, service = ai_tools.services()
            doc = service.read_document(path)
            doc.update(brief=service.validate_brief({"premise": data.premise.strip(), "genre": data.genre}),
                       revision=doc["revision"] + 1)
            writer_runner.atomic_json(path / ".webnovel" / "creative_brief.json", doc)
        identity = store.register(path)
        return project_summary(project(identity))

    @app.get("/api/projects/{identity}/chapters")
    def chapters(identity: str):
        path = Path(project(identity)["path"])
        reviewed = writer_runner.reviewed_chapters(path)
        committed = writer_runner.committed_chapters(path)
        rows = []
        for source, cid, title, content in bridge.iter_source_chapters(path):
            receipt = committed.get(cid) or reviewed.get(cid) or {}
            review = receipt.get("review") or {}
            rows.append({
                "id": cid,
                "title": title,
                "words": len(content),
                "path": str(source),
                "reviewed": cid in reviewed,
                "human_review_required": cid in committed and cid not in reviewed,
                "review_status": review.get("review_decision"),
                "auto_review_count": review.get("auto_review_count"),
            })
        return {"chapters": rows}

    @app.get("/api/projects/{identity}/entities")
    def project_entities(identity: str, chapter: int = 0):
        path = Path(project(identity)["path"])
        return entity_state.view(path, max(0, chapter))

    @app.get("/api/projects/{identity}/precheck")
    def project_precheck(identity: str, chapter: int = 1):
        path = Path(project(identity)["path"])
        try:
            body, _sha = memory_library._chapter(path, max(1, chapter))
        except ValueError as error:
            raise HTTPException(404, f"章节不存在：{error}") from None
        terms = style_rules.ignore_terms(path)
        # 只读：查看预检不得累加指标（指标只在 revision_workflow 的实际检测里记）。
        result = style_rules.check(body, scope="precheck", project=path, ignore_terms=terms,
                                   record=False)
        return {**result, "ignore_terms": terms, "metrics": style_rules.metrics(path),
                "rules": style_rules.public()}

    @app.put("/api/projects/{identity}/precheck/ignore")
    def save_precheck_ignore(identity: str, data: StyleIgnoreInput):
        path = Path(project(identity)["path"])
        try:
            return {"terms": style_rules.ignore_terms(path, data.terms)}
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.post("/api/projects/{identity}/precheck/action")
    def precheck_action(identity: str, data: StyleActionInput):
        path = Path(project(identity)["path"])
        try:
            return style_rules.record_action(path, data.rule_id, data.action, note=data.note)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.get("/api/projects/{identity}/retrieval")
    def project_retrieval(identity: str, chapter: int = 1, query: str = ""):
        path = Path(project(identity)["path"])
        if chapter < 1:
            raise HTTPException(400, "章号无效")
        try:
            planned = retrieval_plan.plan(path, chapter, query[:200], trace=True)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        return {"plan": planned, "report": retrieval_plan.report(path),
                "index": retrieval_plan.active_index(path), "ready": retrieval_plan.index_ready(path)}

    @app.get("/api/projects/{identity}/evidence/impact")
    def project_evidence_impact(identity: str, chapter: int = 1):
        path = Path(project(identity)["path"])
        chapter = max(1, chapter)
        return {"chapter": chapter, "affected": invalidation.affected_facts(path, [chapter]),
                "index": evidence_usage.reverse_index(path), "log": invalidation.summary(path),
                "coverage": evidence_usage.coverage(path)}

    @app.get("/api/projects/{identity}/readers/dictionary")
    def readers_dictionary(identity: str):
        project(identity)
        return {"metrics": reader_metrics.dictionary(), "caliber": reader_metrics.CALIBER_VERSION,
                "batches": reader_metrics.batches(Path(project(identity)["path"]))}

    @app.post("/api/projects/{identity}/readers/preview")
    def readers_preview(identity: str, data: ReaderImportInput):
        path = Path(project(identity)["path"])
        try:
            rows = data.rows if data.rows is not None else reader_metrics.parse_csv(data.csv)["rows"]
            return reader_metrics.preview(path, rows, platform_default=data.platform,
                                         work_id=data.work_id or None)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.post("/api/projects/{identity}/readers/import")
    def readers_import(identity: str, data: ReaderImportInput):
        path = Path(project(identity)["path"])
        try:
            return reader_metrics.commit(path, filename=data.filename, token=data.token or None,
                                         allow_partial=bool(data.allow_partial))
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.delete("/api/projects/{identity}/readers/batches/{batch}")
    def readers_remove_batch(identity: str, batch: str):
        path = Path(project(identity)["path"])
        try:
            return reader_metrics.remove_batch(path, batch)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.get("/api/projects/{identity}/readers/series")
    def readers_series(identity: str, metric: str = "chapter_completion_rate",
                       work_id: str = "", limit: int = 60):
        path = Path(project(identity)["path"])
        try:
            return reader_metrics.series(path, metric=metric, work_id=work_id or None,
                                         limit=max(1, min(200, limit)))
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.get("/api/projects/{identity}/readers/comments")
    def readers_comments(identity: str, chapter: int = 1, limit: int = 5):
        path = Path(project(identity)["path"])
        return {"chapter": chapter,
                "clusters": reader_metrics.cluster_comments(path, chapter, limit=max(1, min(10, limit))),
                "trace": reader_metrics.rows_for(path, metric="comments", chapter_id=chapter)}

    @app.post("/api/projects/{identity}/readers/comments")
    def readers_add_comments(identity: str, data: ReaderCommentInput):
        path = Path(project(identity)["path"])
        try:
            return reader_metrics.add_comments(path, [{"text": text} for text in data.texts],
                                               chapter_id=data.chapter)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.post("/api/projects/{identity}/readers/observations")
    def readers_build_observation(identity: str, data: ObservationInput):
        path = Path(project(identity)["path"])
        try:
            return observation.build(path, chapter=data.chapter, metric=data.metric,
                                     chapters=data.chapters, days=data.days,
                                     work_id=observation.current_work_id(path))
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.get("/api/projects/{identity}/readers/observations")
    def readers_list_observations(identity: str, status: str = "", chapter: int = 0,
                                  work_id: str = "", touch: bool = False):
        path = Path(project(identity)["path"])
        book = work_id or observation.current_work_id(path)
        return {"cards": observation.list_cards(path, status=status or None,
                                                chapter=chapter or None, work_id=book, touch=touch),
                "active": observation.active_cards(path, max(1, chapter), work_id=book) if chapter else []}

    @app.post("/api/projects/{identity}/readers/observations/expire")
    def readers_expire_observations(identity: str):
        path = Path(project(identity)["path"])
        return observation.expire_due(path)

    @app.get("/api/projects/{identity}/readers/observations/{card_id}")
    def readers_get_observation(identity: str, card_id: str):
        path = Path(project(identity)["path"])
        try:
            return observation.get(path, card_id)
        except ValueError as error:
            raise HTTPException(404, str(error)) from None

    @app.get("/api/projects/{identity}/readers/observations/{card_id}/outline")
    def readers_observation_outline(identity: str, card_id: str):
        path = Path(project(identity)["path"])
        try:
            return observation.outline_diff(path, card_id)
        except ValueError as error:
            raise HTTPException(404, str(error)) from None

    @app.post("/api/projects/{identity}/readers/observations/{card_id}/action")
    def readers_observation_action(identity: str, card_id: str, data: ObservationActionInput):
        path = Path(project(identity)["path"])
        try:
            if data.action == "adopt":
                return observation.adopt(path, card_id, chapters=data.chapters)
            if data.action == "ignore":
                return observation.ignore(path, card_id)
            return observation.revoke(path, card_id, reason=data.reason or "作者撤销")
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.get("/api/projects/{identity}/browser/status")
    def browser_status(identity: str):
        try:
            return browser_target.status(Path(project(identity)["path"]))
        except ValueError as error:
            return JSONResponse({"code": "target_invalid", "message": str(error)},
                                status_code=409)

    @app.get("/api/projects/{identity}/browser/target")
    def browser_get_target(identity: str):
        try:
            return {"target": browser_target.load_target(Path(project(identity)["path"]))}
        except ValueError as error:
            return JSONResponse({"code": "target_invalid", "message": str(error)},
                                status_code=409)

    @app.put("/api/projects/{identity}/browser/target")
    def browser_put_target(identity: str, data: BrowserTargetInput):
        path = Path(project(identity)["path"])
        try:
            return {"target": browser_target.save_target(path, data.model_dump())}
        except ValueError as error:
            return JSONResponse({"code": "invalid_target", "message": str(error)},
                                status_code=400)

    @app.post("/api/projects/{identity}/browser/launch")
    def browser_launch(identity: str, headless: bool = False):
        path = Path(project(identity)["path"])
        try:
            if not browser_target.load_target(path):
                return JSONResponse({"code": "target_missing",
                                     "message": "还没有配置 target：先写唯一目标再启动浏览器"},
                                    status_code=409)
            return browser_target.launch(browser_target.current(), path, headless=headless)
        except browser_target.AdapterNeedsHuman as error:
            return JSONResponse({"code": "needs_human", "message": str(error)}, status_code=409)
        except browser_target.AdapterUnavailable as error:
            return JSONResponse({"code": "adapter_unavailable", "message": str(error)},
                                status_code=409)
        except OSError as error:
            return JSONResponse({"code": "adapter_os_error", "message": str(error)},
                                status_code=409)
        except ValueError as error:
            return JSONResponse({"code": "invalid_target", "message": str(error)},
                                status_code=409)

    @app.post("/api/projects/{identity}/browser/stop")
    def browser_stop(identity: str):
        path = Path(project(identity)["path"])
        try:
            result = browser_target.stop(browser_target.current(), path)
        except (ValueError, OSError) as error:
            return JSONResponse({"code": "invalid_request", "message": str(error)},
                                status_code=400)
        if not result.get("stopped"):
            code = "adapter_unavailable" if browser_target.current() is None else "stop_failed"
            return JSONResponse({"code": code, "message": result.get("error") or "浏览器没有停止"},
                                status_code=409)
        return result

    @app.get("/api/projects/{identity}/browser/health")
    def browser_health(identity: str):
        try:
            return browser_target.health(browser_target.current())
        except (ValueError, OSError, RuntimeError) as error:
            return JSONResponse({"code": "adapter_error", "message": str(error)},
                                status_code=409)

    @app.post("/api/projects/{identity}/browser/login")
    def browser_login(identity: str, data: BrowserLoginInput):
        path = Path(project(identity)["path"])
        try:
            # source="client"：客户端只能报 unknown/needs_human/cancelled，
            # valid/expired 必须由适配器回读 profile 后写入。
            return browser_target.record_login(path, status=data.status, account=data.account,
                                              evidence=data.evidence, reason=data.reason,
                                              source="client")
        except ValueError as error:
            return JSONResponse({"code": "invalid_login", "message": str(error)},
                                status_code=400)

    @app.post("/api/projects/{identity}/browser/readonly")
    def browser_readonly(identity: str, data: BrowserReadonlyInput):
        path = Path(project(identity)["path"])
        try:
            return browser_target.verify_readonly(browser_target.current(), path,
                                                  book_id=data.book_id, chapter=data.chapter,
                                                  expect_body_sha256=data.body_sha256)
        except ValueError as error:
            return JSONResponse({"code": "invalid_request", "message": str(error)},
                                status_code=400)

    @app.post("/api/projects/{identity}/browser/publish")
    def browser_publish(identity: str, data: BrowserPublishInput):
        path = Path(project(identity)["path"])
        try:
            # 不把请求体里的 authorization 当依据：授权只认 target 上服务端保存的记录。
            report = browser_target.publish_once(
                browser_target.current(), path, book_id=data.book_id, chapter=data.chapter,
                body_sha256=data.body_sha256, replace=bool(data.replace))
        except ValueError as error:
            return JSONResponse({"code": "invalid_request", "message": str(error)},
                                status_code=400)
        if report["status"] in ("unavailable", "refused"):
            return JSONResponse({"code": report["status"], "message": report["reason"]},
                                status_code=409)
        return report

    @app.post("/api/projects/{identity}/browser/publish/reconcile")
    def browser_publish_reconcile(identity: str, data: BrowserReconcileInput):
        path = Path(project(identity)["path"])
        try:
            return browser_target.reconcile_publish(
                path, key=data.key, book_id=data.book_id, chapter=data.chapter,
                resolution=data.resolution, note=data.note)
        except ValueError as error:
            return JSONResponse({"code": "invalid_reconcile", "message": str(error)},
                                status_code=400)

    @app.get("/api/projects/{identity}/browser/capabilities")
    def browser_capabilities(identity: str):
        path = Path(project(identity)["path"])
        try:
            return {"columns": list(browser_target.COLUMNS),
                    "row": browser_target.capability_row(path),
                    "evidence": browser_target.capability_evidence(path)}
        except ValueError as error:
            return JSONResponse({"code": "target_invalid", "message": str(error)},
                                status_code=409)

    @app.get("/api/projects/{identity}/publish/platforms")
    def publish_platforms(identity: str):
        project(identity)
        return {"platforms": publishing.capabilities(),
                "target": publishing.target_platform(Path(project(identity)["path"]))}

    @app.put("/api/projects/{identity}/publish/target")
    def publish_target(identity: str, data: PublishTargetInput):
        path = Path(project(identity)["path"])
        try:
            return publishing.set_target_platform(
                path, data.platform, account=data.account,
                platform_book_id=data.platform_book_id, book=data.book)
        except publishing.PublishError as error:
            return JSONResponse({"code": "invalid_target", "message": str(error)},
                                status_code=400)

    @app.post("/api/projects/{identity}/publish/export")
    def publish_export(identity: str, data: PublishExportInput):
        path = Path(project(identity)["path"])
        try:
            return publishing.export_chapter(
                path, platform=data.platform, chapter=data.chapter, title=data.title,
                body=data.body, account=data.account,
                platform_book_id=data.platform_book_id)
        except publishing.PublishError as error:
            return JSONResponse({"code": "invalid_export", "message": str(error)},
                                status_code=400)

    @app.get("/api/projects/{identity}/publish/exports")
    def publish_exports(identity: str, platform: str = "fanqie", account: str = "",
                        platform_book_id: str = ""):
        path = Path(project(identity)["path"])
        try:
            return publishing.exports(path, platform=platform, account=account,
                                      platform_book_id=platform_book_id)
        except publishing.PublishError as error:
            return JSONResponse({"code": "unknown_platform", "message": str(error)},
                                status_code=400)

    @app.post("/api/projects/{identity}/publish/bind")
    def publish_bind(identity: str, data: PublishBindInput):
        path = Path(project(identity)["path"])
        try:
            return publishing.bind_book(
                path, platform=data.platform, account=data.account,
                platform_book_id=data.platform_book_id, title=data.title,
                verified_via=data.verified_via,
                observed_chapters=data.observed_chapters,
                probe_evidence=data.probe_evidence)
        except publishing.PublishError as error:
            return JSONResponse({"code": "invalid_binding", "message": str(error)},
                                status_code=400)

    @app.post("/api/projects/{identity}/publish/authorize")
    def publish_authorize(identity: str, data: PublishAuthorizeInput):
        path = Path(project(identity)["path"])
        try:
            return publishing.authorize(
                path, platform=data.platform, account=data.account,
                platform_book_id=data.platform_book_id, chapters=data.chapters,
                note=data.note, expires_at=data.expires_at)
        except publishing.PublishError as error:
            return JSONResponse({"code": "invalid_authorization", "message": str(error)},
                                status_code=400)

    @app.post("/api/projects/{identity}/publish/submit")
    def publish_submit(identity: str, data: PublishSubmitInput):
        path = Path(project(identity)["path"])
        try:
            return publishing.submit_chapter(
                path, platform=data.platform, account=data.account,
                platform_book_id=data.platform_book_id, chapter=data.chapter,
                title=data.title, body=data.body)
        except publishing.PublishError as error:
            return JSONResponse({"code": "invalid_submit", "message": str(error)},
                                status_code=400)

    @app.post("/api/projects/{identity}/publish/reconcile")
    def publish_reconcile(identity: str, data: PublishReconcileInput):
        path = Path(project(identity)["path"])
        try:
            return publishing.reconcile(
                path, platform=data.platform, account=data.account,
                platform_book_id=data.platform_book_id, chapter=data.chapter,
                body_sha256=data.body_sha256, resolution=data.resolution,
                note=data.note, evidence=data.evidence)
        except publishing.PublishError as error:
            return JSONResponse({"code": "invalid_reconcile", "message": str(error)},
                                status_code=400)

    @app.get("/api/projects/{identity}/publish/status")
    def publish_status(identity: str):
        return publishing.status(Path(project(identity)["path"]))

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
        path = Path(project(identity)["path"])
        return {**workflow.state(path), "pending_batches": studio.pending_batches(path)}

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
        return ops.start("memory",["memory-rebuild","--project",item["path"]],f"project:{identity}",{"project_id":identity,"book":project_title(item["path"])})

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
        return ops.start("learn",args,f"project:{identity}",{"project_id":identity,"book":project_title(item["path"]),"sample_id":sample})

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
        return ops.start("plan",["plan","--project",item["path"],"--count",str(data.count)],f"project:{identity}",{"project_id":identity,"book":project_title(item["path"])})

    @app.get("/api/projects/{identity}/plan")
    def current_plan(identity: str):
        return studio.recover_plan(Path(project(identity)["path"]),persist=False)

    @app.post("/api/projects/{identity}/batches/{batch}/resume")
    def resume_batch(identity: str,batch: str):
        item=project(identity);path=studio.project_file(Path(item["path"]),"batches",batch)
        if not path.is_file():raise KeyError("批次不存在")
        return ops.start("generate",["batch","--project",item["path"],"--batch-id",batch],f"project:{identity}",{"project_id":identity,"book":project_title(item["path"]),"batch_id":batch})

    @app.post("/api/projects/{identity}/batches/{batch}/abandon")
    def abandon_batch(identity: str, batch: str):
        item = project(identity)
        return studio.abandon_batch(Path(item["path"]), None if batch == "all" else batch)

    @app.post("/api/projects/{identity}/chapters/{chapter}/polish")
    def polish_chapter(identity: str,chapter: int):
        if chapter<=0:raise ValueError("章节号无效")
        item=project(identity)
        if not public_ai()["configured"]:raise ValueError("请先配置 AI 模型")
        return ops.start("polish",["polish","--project",item["path"],"--chapter",str(chapter)],f"project:{identity}",{"project_id":identity,"book":project_title(item["path"]),"chapter":chapter})

    @app.get("/api/projects/{identity}/chapters/{chapter}")
    def chapter(identity: str, chapter: int):
        path = Path(project(identity)["path"])
        from integration import chapter_editor
        try:
            return chapter_editor.chapter_state(path, chapter)
        except chapter_editor.ChapterError as exc:
            raise HTTPException(exc.status, exc.code) from None
        except Exception as exc:
            # 保持 v0.7.5 的 409/404 语义：章节重复或未找到
            from integration.chapter_versions import VersionConflict, VersionNotFound
            if isinstance(exc, VersionConflict):
                raise HTTPException(409, "章节重复，请检查正文文件") from None
            if isinstance(exc, VersionNotFound):
                raise HTTPException(404, "未找到章节") from None
            raise

    @app.post("/api/projects/{identity}/chapters/{chapter}/approve-review")
    def approve_chapter_review(identity: str, chapter: int, data: dict | None = None):
        if chapter <= 0:
            raise ValueError("章节号无效")
        item = project(identity)
        note = str((data or {}).get("note") or "")
        expected = str((data or {}).get("expected_sha256") or "").strip() or None
        return writer_runner.approve_chapter_review(Path(item["path"]), chapter, note=note,
                                                    expected_sha256=expected)

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
                         f"project:{identity}", {"project_id": identity, "book": project_title(item["path"]), "chapter": chapter})

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
        if not re.fullmatch(r"(?:[0-9a-f]{64}|ver_\d{4,}_[0-9a-f]{8})", version): raise ValueError("版本标识无效")
        from integration import version_history
        return version_history.read(Path(project(identity)["path"]), chapter, version)

    @app.post("/api/projects/{identity}/chapters/{chapter}/restore")
    def restore_chapter(identity: str, chapter: int, data: RestoreInput):
        if chapter <= 0: raise ValueError("章节号无效")
        from integration import version_history
        return version_history.restore(Path(project(identity)["path"]), chapter, data.version_id,
                                       op_id=data.op_id, restore_title=data.restore_title,
                                       config=load_ai())

    @app.post("/api/projects/{identity}/chapters/{chapter}/review")
    def review_existing(identity: str, chapter: int):
        item = project(identity)
        if chapter <= 0:
            raise ValueError("章节号必须大于 0")
        if not public_ai()["configured"]:
            raise ValueError("请先完成 AI 设置")
        return ops.start("review", ["review", "--project", item["path"], "--chapter", str(chapter)], f"project:{identity}",
                         {"project_id": identity, "book": project_title(item["path"]), "chapter": chapter})

    def read_outline(identity, path):
        from hashlib import sha256
        files = sorted((path / "大纲").glob("*.md"))
        contents = [(p.name, p.read_bytes()) for p in files]
        revision = sha256(json.dumps(
            [(name, sha256(body).hexdigest()) for name, body in contents]
        ).encode()).hexdigest()
        return {"project_id": identity, "revision": revision, "editable": len(files) <= 1,
                "content": "\n\n".join(body.decode("utf-8-sig") for _, body in contents),
                "files": [name for name, _ in contents]}

    @app.get("/api/projects/{identity}/outline")
    def outline(identity: str):
        return read_outline(identity, Path(project(identity)["path"]))

    @app.put("/api/projects/{identity}/outline")
    def save_outline(identity: str, data: OutlineInput):
        path = Path(project(identity)["path"])
        if data.project_id is not None and data.project_id != identity:
            raise HTTPException(409, "大纲属于另一部作品，请切回对应作品")
        with writer_runner.file_lock(path / ".webnovel" / "writer.lock"):
            current = read_outline(identity, path)
            if not current["editable"]:
                raise HTTPException(409, "多文件大纲请在写作系统中按卷编辑，避免合并造成重复")
            if data.revision is not None and data.revision != current["revision"]:
                raise HTTPException(409, "大纲已更新，请重新载入再保存")
            target = path / "大纲" / (current["files"][0] if current["files"] else "卷一.md")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                backup = DATA / "backups" / f"{identity}-{uuid.uuid4().hex}-outline.md"
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(target.read_bytes())
            bridge._write_text_atomic(target, data.content)
            return {**read_outline(identity, path), "success": True}

    @app.post("/api/projects/{identity}/generate")
    def generate(identity: str, data: GenerateInput):
        item = project(identity)
        if not public_ai()["configured"]:
            raise ValueError("请先完成 AI 设置")
        batch=uuid.uuid4().hex
        return ops.start("generate", ["batch", "--project", item["path"], "--word-count", str(data.word_count),
                          "--max-revisions", str(data.max_revisions),"--count",str(data.count),"--batch-id",batch,
                          "--scenes",str(data.scenes)], f"project:{identity}",{"project_id":identity,"book":project_title(item["path"]),"batch_id":batch,"scenes":data.scenes},
                          operation_key=data.operation_key)

    @app.post("/api/projects/{identity}/stage")
    def stage(identity: str, data: StageInput):
        item = project(identity)
        book = platform_book(item) or data.book.strip()
        if not book:
            raise ValueError("请填写平台书名")
        args = ["stage", "--project", item["path"], "--book", book]
        for cid in data.chapters or []:
            if cid <= 0:
                raise ValueError("章节号必须大于 0")
            args.extend(["--chapter", str(cid)])
        return ops.start("stage", args, f"project:{identity}", {"project_id": identity, "book": book})

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

    def publish_destination(data):
        item = project(data.project_id)
        if not bridge.account_state_path(data.account).is_file():
            raise ValueError("请先登录所选番茄账号")
        book = platform_book(item) or data.book.strip()
        if not book:
            raise ValueError("请填写平台书名")
        return item, book

    def queued_publish_preview(data, item, book):
        plan = bridge.validate_queue_origin(book, Path(item["path"]), data.account)
        chapters = plan["chapters"][:data.count]
        return {"project_id": data.project_id, "account": plan["account"], "book": plan["book"],
                "chapters": [chapter["chapter_id"] for chapter in chapters],
                "revision": bridge.publish_plan_revision(plan, chapters)}

    @app.post("/api/publish/preview")
    def preview_publish(data: PublishInput):
        return queued_publish_preview(data, *publish_destination(data))

    @app.post("/api/publish")
    def publish(data: PublishInput):
        item, book = publish_destination(data)
        args = ["publish", "--project", item["path"], "--book", book, "--account", data.account,
                "--count", str(data.count), "--ai-used", "1" if data.ai_used else "0"]
        if data.preview_revision:
            preview = queued_publish_preview(data, item, book)
            if preview["revision"] != data.preview_revision or preview["book"] != data.book:
                raise HTTPException(409, "发布目标或章节已变化，请重新预览并确认")
            args.extend(["--preview-revision", data.preview_revision])
        elif book != data.book.strip():
            raise HTTPException(409, f"已绑定《{book}》，请核对平台书名后再发布")
        return ops.start("publish", args, f"project:{data.project_id}",
                         {"book": book, "account": data.account, "project_id": data.project_id})

    def list_jobs():
        return [scheduler._job_summary(identity, job) | {
                    "max_revisions": job.get("max_revisions", 1),
                    "project_id": project_id_for_path(job.get("project", "")),
                }
                for identity, job in scheduler.load_scheduler()["jobs"].items() if isinstance(job, dict)]

    @app.get("/api/jobs")
    def jobs_listing():
        return list_jobs()

    @app.post("/api/jobs")
    def add_job(data: JobInput):
        if not any(Path(x["path"]).resolve() == Path(data.project).resolve() for x in store.projects()):
            raise ValueError("请先登记写作项目")
        supplied = set(data.model_fields_set)
        values = data.model_dump(exclude={"id", "job_id"})
        if "name" not in supplied or not values.get("name") or values["name"].strip() in {"", "日更任务"}:
            # P2-15: 书名本身可到 96 字，默认名必须截断到 JobInput.name 的同一上限。
            values["name"] = f"《{data.book.strip()}》 · 日更"[:96]
        explicit_id = data.job_id or data.id
        normalized_explicit = None
        if explicit_id:
            raw_id = str(explicit_id)
            # P2-13: 非法 ID 直接 400，绝不静默 safe_dir_name 成另一个 ID。
            if "/" in raw_id or "\\" in raw_id or ".." in raw_id:
                raise HTTPException(400, "任务 ID 不能包含路径分隔符或 ..")
            normalized_explicit = scheduler.normalize_job_id(raw_id)
            if normalized_explicit != raw_id.replace(" ", "-"):
                raise HTTPException(400, "任务 ID 含非法字符、首尾空白或超过 80 字；请改用合法 ID")
        target_project = str(Path(data.project).expanduser().resolve())
        # 查重与创建/更新必须串行；否则两个并发 POST 都看不到对方而各写一条。
        # 锁序：_JOBS_CREATE_LOCK -> scheduler config lock，反向不存在。
        with _JOBS_CREATE_LOCK:
            snapshot = scheduler.load_scheduler()
            jobs = snapshot.get("jobs", {})
            existing_id = None
            if normalized_explicit and isinstance(jobs.get(normalized_explicit), dict):
                existing_job = jobs[normalized_explicit]
                if str(Path(existing_job.get("project", "")).expanduser().resolve()) != target_project:
                    raise HTTPException(409, "该任务 ID 已用于其他作品，不能重复使用")
                existing_id = normalized_explicit
            if existing_id is None:
                explicit_mode = values.get("publication_mode") if "publication_mode" in supplied else None
                target_mode = explicit_mode or "draft_only"
                existing_id = next(
                    (jid for jid, job in jobs.items()
                     if isinstance(job, dict)
                     and str(Path(job.get("project", "")).expanduser().resolve()) == target_project
                     and scheduler.publication_mode(job) == target_mode),
                    None,
                )
                if existing_id and normalized_explicit and existing_id != normalized_explicit:
                    raise HTTPException(409, f"该作品已有同发布方式的任务：{existing_id}")
                if existing_id is None and explicit_mode is None:
                    # P2-12: 旧客户端裸 POST 不能在有发布/排期任务的书上悄悄再生一个只存稿任务。
                    legacy = next(
                        (jid for jid, job in jobs.items()
                         if isinstance(job, dict)
                         and str(Path(job.get("project", "")).expanduser().resolve()) == target_project
                         and scheduler.publication_mode(job) in {"publish_now", "platform_scheduled"}),
                        None,
                    )
                    if legacy:
                        raise HTTPException(409, f"该作品已有发布/排期任务（{legacy}）；"
                                                 "新建只存稿任务请显式提交 publication_mode=draft_only")
            if existing_id:
                # P0-2: 只合并客户端真正提交的字段，绝不拿 model_dump 默认值
                # 覆盖 serial/配额/时段/排期/enabled 等已保存配置。
                changes = {k: v for k, v in values.items() if k in supplied}
                if changes.get("publication_mode") is None:
                    changes.pop("publication_mode", None)
                return scheduler.update_job(existing_id, changes)
            if normalized_explicit and normalized_explicit in jobs:
                raise HTTPException(409, f"任务已存在：{normalized_explicit}")
            values["job_id"] = normalized_explicit or uuid.uuid4().hex[:12]
            values["disabled"] = not data.enabled
            values["volume"] = None
            if values.get("publication_mode") is None:
                # 新客户端没指定就用默认 draft_only。
                values.pop("publication_mode", None)
            return scheduler.add_job(argparse.Namespace(**values))

    @app.delete("/api/jobs/{identity}")
    def delete_job(identity: str):
        if any(x.get("identity") == f"job:{identity}" for x in store.operations(active_only=True)):
            raise HTTPException(409, "该任务正在执行中，请先停止后再删除")
        scheduler.remove_job(identity)
        return {"deleted": identity}

    @app.put("/api/jobs/{identity}")
    def edit_job(identity: str, data: JobInput):
        if not any(Path(x["path"]).resolve() == Path(data.project).resolve() for x in store.projects()):
            raise ValueError("请先登记写作项目")
        # P2-10/P2-11: 与 POST 一致，只合并客户端显式提交的字段。缺省 = 不改；
        # 显式 null 仅对 schedule_buffer 表示“清空”，publication_mode 的 null 仍视为未提交。
        values = {k: v for k, v in data.model_dump(exclude={"id", "job_id"}).items()
                  if k in data.model_fields_set}
        if values.get("publication_mode") is None:
            # 旧 PUT 不带这个键时必须保留任务原值，否则发布任务会被静默降级成只存稿。
            values.pop("publication_mode", None)
        if hasattr(scheduler, "update_job"):
            with _JOBS_CREATE_LOCK:
                return scheduler.update_job(identity, values)
        raise HTTPException(503, "任务更新接口尚不可用")

    # ---- 平台排期缓冲（0.6.1） ------------------------------------------------
    from integration import platform_adapters, platform_schedule, schedule_buffer, scheduled_delivery

    def _schedule_job(identity: str):
        job = scheduler.load_scheduler()["jobs"].get(identity)
        if not isinstance(job, dict):
            raise HTTPException(404, "任务不存在")
        return job

    def _schedule_context(identity: str, job):
        settings = schedule_buffer.normalize_settings(job.get("schedule_buffer"))
        platform = str(job.get("platform") or "fanqie")
        account, book = str(job.get("account") or ""), str(job.get("book") or "")
        capability = platform_schedule.capability_for(platform, account, book)
        try:
            published = scheduler._published_ids(book, account or None) if book else []
        except Exception:
            published = []
        approved = schedule_buffer.approved_candidates(Path(job["project"]), published=published)
        store = schedule_buffer.load_store(identity)
        last = store.get("last_reconcile") if isinstance(store.get("last_reconcile"), dict) else {}
        remote = [row for row in (last.get("rows") or []) if isinstance(row, dict)]
        planned = schedule_buffer.plan({**job, "job_id": identity}, approved=approved, remote=remote,
                                       intents=store.get("intents") or [],
                                       capability=capability, settings=settings)
        return {"settings": settings, "platform": platform, "account": account, "book": book,
                "capability": capability, "approved": approved, "store": store,
                "planned": planned}

    def _schedule_view(identity: str, job):
        ctx = _schedule_context(identity, job)
        state = scheduled_delivery.state_for_job(identity, job)
        return {"job_id": identity, "settings": ctx["settings"], "platform": ctx["platform"],
                "capability": ctx["capability"].get("capabilities") or {},
                "capability_observed_at": ctx["capability"].get("observed_at", ""),
                "capability_source": ctx["capability"].get("source", ""),
                "capability_evidence": ctx["capability"].get("evidence", ""),
                "review": schedule_buffer.review_items(identity, ctx["store"]),
                "preview": ctx["planned"], "state": state}

    @app.get("/api/jobs/{identity}/schedule")
    def get_schedule(identity: str):
        return _schedule_view(identity, _schedule_job(identity))

    @app.post("/api/jobs/{identity}/schedule/preview")
    def preview_schedule(identity: str):
        # 纯计算：不写任务、不写台账、不碰平台。
        return _schedule_view(identity, _schedule_job(identity))

    @app.post("/api/jobs/{identity}/schedule/capability")
    def set_schedule_capability(identity: str, data: ScheduleCapabilityInput):
        job = _schedule_job(identity)
        platform = str(job.get("platform") or "fanqie")
        record = platform_schedule.record_capability({
            "platform": platform,
            "account": str(job.get("account") or ""),
            "book_id": str(job.get("book") or ""),
            "observed_at": data.observed_at or "",
            "source": data.source or "author_confirmed",
            "evidence": data.evidence,
            "timezone": str(job.get("timezone") or "Asia/Shanghai"),
            "capabilities": {
                "can_read_schedule": data.can_read_schedule,
                "can_schedule": data.can_schedule,
                "can_confirm_schedule": data.can_confirm_schedule,
                "can_confirm_body": data.can_confirm_body,
                "lead_time_minutes": data.lead_time_minutes,
                "max_scheduled": data.max_scheduled,
                "max_chapters_per_day": data.max_chapters_per_day,
            },
        })
        allowed, reason = platform_schedule.can_auto_schedule(record)
        return {"capability": record["capabilities"], "auto_allowed": allowed, "reason": reason}

    @app.post("/api/jobs/{identity}/schedule/apply")
    def apply_schedule(identity: str, data: ScheduleBufferInput):
        job = _schedule_job(identity)
        if scheduler.publication_mode(job) != "platform_scheduled":
            # 只存稿/立即发布任务没有排期语义；在这里建意图只会在切模式时被一次性补写。
            return JSONResponse(status_code=409, content={
                "code": "not_scheduled_job",
                "message": "只有 publication_mode=platform_scheduled 的任务可以建排期计划"})
        try:
            settings = schedule_buffer.validate_settings(data.schedule_buffer)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={
                "code": "invalid_settings", "message": str(exc)[:300]})
        store = schedule_buffer.load_store(identity)
        stale = False
        if data.expected_revision is not None:
            stale = int(data.expected_revision) != int(store.get("revision") or 0)
        elif data.expected_updated_at:
            # 旧客户端用时间戳做租约；空串等于“没带租约”，保持向后兼容。
            stale = data.expected_updated_at != str(store.get("updated_at") or "")
        if stale:
            return JSONResponse(status_code=409, content={
                "code": "stale_buffer",
                "message": "排期台账已被其他窗口更新，请刷新后再改",
                "updated_at": store.get("updated_at") or "",
                "revision": int(store.get("revision") or 0)})
        try:
            updated = scheduler.update_job(identity, {"schedule_buffer": settings})
        except ValueError as exc:
            return JSONResponse(status_code=400, content={
                "code": "update_rejected", "message": str(exc)[:300]})
        # 用更新后的任务重新计算，避免拿旧字段生成计划（审计 P2-2）。
        job = _schedule_job(identity)
        platform = str(job.get("platform") or "fanqie")
        account, book = str(job.get("account") or ""), str(job.get("book") or "")
        capability = platform_schedule.capability_for(platform, account, book)
        allowed, reason = platform_schedule.can_auto_schedule(capability)
        try:
            published = scheduler._published_ids(book, account or None) if book else []
        except Exception:
            published = []
        approved = schedule_buffer.approved_candidates(Path(job["project"]), published=published)
        last = store.get("last_reconcile") if isinstance(store.get("last_reconcile"), dict) else {}
        remote = [row for row in (last.get("rows") or []) if isinstance(row, dict)]
        planned = schedule_buffer.plan({**job, "job_id": identity}, approved=approved, remote=remote,
                                       intents=store.get("intents") or [],
                                       capability=capability, settings=settings)
        if settings["enabled"] and not allowed:
            # 能力未证实：设置可以保存（只读清单/本地存稿），但不生成投递意图。
            return JSONResponse(status_code=409, content={
                "code": "capability_unknown", "reason": reason,
                "settings": settings, "preview": planned,
                "message": "平台排期能力未证实：已保存设置，只交本地存稿候选"})
        if not settings["enabled"]:
            # 关闭补货：只保存设置，不把已有台账的 plan 覆盖成空预览（审计 P2-6）。
            return {"settings": settings, "applied": 0, "intents": len(store.get("intents") or []),
                    "preview": planned, "job": updated}
        result = schedule_buffer.apply_plan(identity, job, planned, store=store)
        return {"settings": settings, "applied": result["added"], "replaced": result["replaced"],
                "cancelled": result["cancelled"], "blocked": result["blocked"][:5],
                "intents": result["total"], "preview": planned, "job": updated}

    @app.post("/api/jobs/{identity}/schedule/stop")
    def stop_schedule(identity: str):
        _schedule_job(identity)
        return schedule_buffer.stop_replenish(identity)

    @app.post("/api/jobs/{identity}/schedule/resume")
    def resume_schedule(identity: str):
        _schedule_job(identity)
        return schedule_buffer.resume_replenish(identity)

    @app.post("/api/jobs/{identity}/schedule/resolve")
    def resolve_schedule(identity: str, data: ScheduleResolveInput):
        """销账：把一条“结果未知”的意图解除，否则排期会永久停写（审计 P1-4）。"""
        _schedule_job(identity)
        try:
            return schedule_buffer.resolve_review(identity, data.chapter_id,
                                                  data.resolution, note=data.note)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={
                "code": "invalid_resolution", "message": str(exc)[:200]})

    @app.get("/api/jobs/{identity}/schedule/review")
    def schedule_review(identity: str):
        """只读：列出所有需要人工/对账处理的意图，界面据此给销账入口。"""
        _schedule_job(identity)
        return {"items": schedule_buffer.review_items(identity)}

    @app.post("/api/jobs/{identity}/schedule/reconcile")
    def reconcile_schedule(identity: str, data: ScheduleReconcileInput | None = None):
        job = _schedule_job(identity)
        platform = str(job.get("platform") or "fanqie")
        account, book = str(job.get("account") or ""), str(job.get("book") or "")
        complete = True
        source = ""
        rows: list = []
        if data is not None and data.rows:
            # 没有适配器时也能对账：作者粘贴/导入的只读清单是可验证的输入。
            rows = list(data.rows)
            complete = bool(data.complete)
            source = str(data.source or "author_import")
        else:
            adapter = platform_adapters.get_adapter(platform)
            if adapter is None:
                return JSONResponse(status_code=409, content={
                    "code": "adapter_unavailable",
                    "message": "没有该平台的排期回读适配器；可在请求体里传 rows 用只读清单对账"})
            raw = adapter.read_schedule(platform, account, book)
            if isinstance(raw, dict):
                rows = raw.get("rows") or raw.get("entries") or []
                complete = bool(raw.get("complete", True))
                source = str(raw.get("source") or "")
            else:
                rows = raw or []
        snapshot = platform_schedule.read_snapshot(
            rows, platform=platform, account=account, book_id=book,
            timezone_name=str(job.get("timezone") or "Asia/Shanghai"),
            complete=complete, source=source)
        capability = platform_schedule.capability_for(platform, account, book)
        result = schedule_buffer.reconcile(identity, snapshot, capability=capability)
        return {"reconcile": result, "snapshot": {
            "entries": len(snapshot["entries"]),
            "needs_review": len(snapshot["needs_review"]),
            "conflicts": len(snapshot["conflicts"]),
            "duplicates": snapshot.get("duplicates", 0),
            "complete": snapshot.get("complete", True),
        }}

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
        meta = {
            "job_id": identity,
            "project_id": project_id_for_path(job.get("project", "")),
            "project_path": job.get("project", ""),
            "book": job.get("book") or project_title(job.get("project", "")),
        }
        return ops.start("daily", ["run", "--job-id", identity, *extra], f"job:{identity}", meta)

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

    @app.get("/api/jobs/{identity}/runs")
    def job_runs(identity: str, limit: int = 20):
        """只读：列出任务运行记录，不启动 worker、不发通知、不碰平台。"""
        from integration import run_report
        document = scheduler.load_scheduler()
        if not isinstance(document["jobs"].get(identity), dict):
            raise HTTPException(404, "任务不存在")
        return run_report.list_runs(identity, limit=max(1, min(int(limit or 20), 100)))

    @app.get("/api/jobs/{identity}/runs/{run_id}")
    def job_run_detail(identity: str, run_id: str):
        """只读投影：逐章状态、费用覆盖、最近事件与可行动作。"""
        from integration import run_report
        document = scheduler.load_scheduler()
        job = document["jobs"].get(identity)
        if not isinstance(job, dict):
            raise HTTPException(404, "任务不存在")
        try:
            return run_report.project_run(identity, job, run_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc).strip("'\"")) from exc
        except ValueError as exc:
            raise HTTPException(400, redact(str(exc))[:200]) from exc

    @app.get("/api/notifications")
    def notifications_overview(limit: int = 20):
        """本地事件列表与发件箱；不发起任何网络请求。"""
        from integration import notification_hooks, notifications
        db = notification_hooks.connection()
        try:
            return {
                "events": notifications.list_events(db, limit=max(1, min(int(limit or 20), 100))),
                "outbox": notifications.list_outbox(db, state={"unknown", "failed", "dead"},
                                                    limit=50),
                "recipients": notifications.list_recipients(db),
                "pending": len(notifications.list_outbox(db, state={"pending", "leased"}, limit=200)),
            }
        finally:
            db.close()

    @app.post("/api/notifications/recipients")
    def add_notification_recipient(data: RecipientInput):
        from integration import notification_hooks, notifications
        db = notification_hooks.connection()
        try:
            return notifications.add_recipient(db, data.url.strip(), data.secret)
        except notifications.UnsafeTarget as exc:
            raise HTTPException(400, str(exc)[:300]) from exc
        except notifications.NotificationError as exc:
            raise HTTPException(409, str(exc)[:300]) from exc
        finally:
            db.close()

    @app.post("/api/notifications/recipients/{recipient_id}/test")
    def test_notification_recipient(recipient_id: str):
        from integration import notification_hooks, notifications
        db = notification_hooks.connection()
        try:
            return notifications.test_send(db, recipient_id)
        except notifications.NotificationError as exc:
            raise HTTPException(409, str(exc)[:300]) from exc
        finally:
            db.close()

    @app.delete("/api/notifications/recipients/{recipient_id}")
    def disable_notification_recipient(recipient_id: str):
        from integration import notification_hooks, notifications
        db = notification_hooks.connection()
        try:
            return notifications.disable_recipient(db, recipient_id)
        except notifications.NotificationError as exc:
            raise HTTPException(404, str(exc)[:200]) from exc
        finally:
            db.close()

    @app.post("/api/notifications/outbox/{outbox_id}/requeue")
    def requeue_notification(outbox_id: int):
        from integration import notification_hooks, notifications
        db = notification_hooks.connection()
        try:
            return notifications.requeue(db, outbox_id)
        except notifications.NotificationError as exc:
            raise HTTPException(409, str(exc)[:200]) from exc
        finally:
            db.close()

    @app.post("/api/notifications/outbox/{outbox_id}/resolve")
    def resolve_notification(outbox_id: int, data: OutboxResolveInput):
        from integration import notification_hooks, notifications
        db = notification_hooks.connection()
        try:
            return notifications.resolve_unknown(db, outbox_id, state=data.state, note=data.note)
        except notifications.NotificationError as exc:
            raise HTTPException(409, str(exc)[:200]) from exc
        finally:
            db.close()

    @app.post("/api/jobs/{identity}/notifications/resolve")
    def resolve_job_incidents(identity: str):
        """作者确认已处理：关闭该任务打开中的故障事件（不重发章节）。"""
        from integration import notification_hooks
        document = scheduler.load_scheduler()
        if not isinstance(document["jobs"].get(identity), dict):
            raise HTTPException(404, "任务不存在")
        return {"resolved": notification_hooks.resolve(identity)}

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
    global _LISTEN_PORT
    parser = argparse.ArgumentParser(description="小说助手本地管理界面")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--lan", action="store_true", help="允许已配对设备通过局域网或 Tailscale 访问")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error(f"--port 必须是 1-65535 的本机端口，收到 {args.port}")
    _LISTEN_PORT = args.port
    hosts = device_access.local_addresses() if args.lan else []
    # Bind explicit private interfaces only. Never listen on a campus/public IP.
    sockets = device_access.listen_sockets(["127.0.0.1", *hosts], args.port)
    try:
        config = uvicorn.Config(create_app(network_hosts=hosts, port=args.port,
                                          device_pairing_required=args.lan),
                                proxy_headers=False, access_log=False)
        uvicorn.Server(config).run(sockets=sockets)
    finally:
        for sock in sockets:
            sock.close()


if __name__ == "__main__":
    main()
