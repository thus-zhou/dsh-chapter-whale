"""0.10.0：平台适配契约与单个第二平台（导出 → 只读登记 → 获准单章）。

本模块只做三件事，且分层开放：
1. 把「平台能力 / 账号引用 / 平台书 / 章身份 / 稿件版本 / 意图 / 回执」写成契约，
   能力未确认的一律按「不可发布」处理，未知不等于可发布；
2. 队列/归档按 `平台/账号/平台作品ID` 命名空间落盘，旧番茄文件只在身份唯一时显式迁移；
3. 第二平台（本版只接七猫）只开放本地导出与只读登记，提交必须另有适配器与授权。

刻意不做：不自动切片上传、不猜官方接口、不把 A 平台的凭据/格式/排期注入 B。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from fanqie_auto_publish.publication_safety import body_digest

from . import bridge, chapter_versions, publication_state

SCHEMA = 1
STATE_DIR = "publish"
DEFAULT_PLATFORM = "fanqie"
SECOND_PLATFORM = "qimao"
PLATFORMS = ("fanqie", "qimao")
TARGETS_NAME = "targets.json"
AUTHORIZATIONS_NAME = "authorizations.json"
BINDINGS_NAME = "bindings.json"
LEDGER_DIR = "intents"
EXPORT_DIR = "exports"
MIGRATION_NAME = "migration.json"
MAX_EXPORT_BYTES = 1 << 20
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CHAPTER_PREFIX_RE = re.compile(r"^第\s*(\d{1,6})\s*章")

# 能力表：True 已证实 / False 已确认不支持 / None 尚未确认。
# `publishable` 只有四项都不为 False 且 `can_submit is True` 才成立；
# 未知（None）永远不当作可发布。
CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "fanqie": {
        "label": "番茄小说",
        "can_export": True,
        "can_draft": True,
        "can_schedule": True,
        "can_verify_body": True,
        "can_submit": True,
        "submission": "browser_authorized",
        "format": "plain_text",
        "note": "排期与浏览器投递走 0.6.1/0.9.4 的既有链路；真实投递需单独授权。",
    },
    "qimao": {
        "label": "七猫中文网",
        "can_export": True,
        "can_draft": False,
        "can_schedule": False,
        "can_verify_body": False,
        "can_submit": False,
        "submission": "manual_upload",
        "format": "plain_text",
        "note": "官方没有公开可复现的提交接口：本版只开放导出与人工登记，不假设可自动提交。",
    },
}


class PublishError(ValueError):
    """契约被违反（内容或参数不合法）。"""


class PublishUnavailable(RuntimeError):
    """能力/适配器/授权不具备：拒绝写入，但不算错误输入。"""


# --- 基础路径与读写 ---------------------------------------------------------

def workspace(project) -> Path:
    return Path(project) / ".webnovel" / STATE_DIR


def _read(path: Path, default: Any, *, strict: bool = False) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        if strict:
            raise PublishError(f"台账无法读取：{path.name}（{error.__class__.__name__}）") from error
        return default


def _write(path: Path, data: Any) -> None:
    writer_atomic = getattr(bridge, "write_json_atomic", None)
    if writer_atomic is not None:
        writer_atomic(path, data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def _ensure_within(project, path: Path) -> Path:
    """写盘前的最后一道边界：目标必须落在项目目录内，且父目录不是符号链接。

    `namespace()` 用占位名兜底，仍可能因为项目内某个中间目录被替换成链接而写到
    项目外；这里在真正写文件前解析一次，越界就拒绝而不是静默跟随。
    """
    root = Path(project).resolve()
    target = Path(path)
    probe = target if target.exists() else target.parent
    if not probe.exists():
        probe = probe.parent
    resolved = probe.resolve()
    if resolved != root and root not in resolved.parents:
        raise PublishError(f"目标路径越界：{target} 不在作品目录内")
    return target


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def capabilities(platform: Optional[str] = None) -> List[Dict[str, Any]]:
    """能力表副本；`publishable` 由能力推导，不由调用方声明。"""
    names = [platform] if platform else list(PLATFORMS)
    rows = []
    for name in names:
        if name not in CAPABILITIES:
            raise PublishError(f"未知平台：{name}")
        row = dict(CAPABILITIES[name], platform=name)
        row["publishable"] = all(row.get(key) is True
                                 for key in ("can_draft", "can_schedule",
                                             "can_verify_body", "can_submit"))
        rows.append(row)
    return rows


def supported(platform: str) -> bool:
    return platform in CAPABILITIES


def require_platform(platform: str) -> Dict[str, Any]:
    if not supported(platform):
        raise PublishError(f"未知平台：{platform}（本版只接 {'/'.join(PLATFORMS)}）")
    return dict(CAPABILITIES[platform], platform=platform)


# --- target_platform 与命名空间 -------------------------------------------

def load_targets(project) -> Dict[str, Any]:
    return _read(workspace(project) / TARGETS_NAME, {"schema": SCHEMA, "target": {}})


def set_target_platform(project, platform: str, *, account: str = "",
                        platform_book_id: str = "", book: str = "") -> Dict[str, Any]:
    """写入唯一 target_platform；不覆盖已有平台的能力结论。"""
    require_platform(platform)
    data = load_targets(project)
    target = {"platform": platform, "account": str(account or "").strip(),
              "platform_book_id": str(platform_book_id or "").strip(),
              "book": str(book or "").strip(), "updated_at": _now()}
    data["schema"] = SCHEMA
    data["target"] = target
    _write(workspace(project) / TARGETS_NAME, data)
    return target


def target_platform(project) -> Dict[str, Any]:
    return dict(load_targets(project).get("target") or {})


def namespace(project, platform: str, *, account: str = "",
              platform_book_id: str = "", book: str = "") -> Path:
    """平台/账号/平台作品ID 三级命名空间；缺身份时直接拒绝，不用占位名兜底。

    供多本同名书/多账号共存：作品层追加身份短 hash，避免同名聚合到同一目录。
    """
    require_platform(platform)
    if not str(account).strip() or not str(platform_book_id).strip():
        raise PublishError("缺账号或平台作品 ID：无法确定唯一的平台命名空间")
    account_part = bridge.safe_dir_name(account)
    book_part = bridge.safe_dir_name(platform_book_id)
    if not account_part or not book_part:
        raise PublishError("账号或平台作品 ID 清洗后为空：请改用可识别的值")
    digest = sha256_text(f"{platform}|{account}|{platform_book_id}")[:8]
    return workspace(project) / platform / f"{account_part}-{digest}" / book_part


def _legacy_roots(project, book: str) -> Dict[str, Path]:
    safe = bridge.safe_dir_name(book)
    return {"queue": Path(bridge.QUEUE_ROOT) / safe,
            "archive": Path(bridge.UPLOADED_ROOT) / safe}


def migrate_legacy(project, *, platform: str = DEFAULT_PLATFORM, account: str = "",
                   platform_book_id: str = "", book: str = "") -> Dict[str, Any]:
    """旧番茄队列/归档 → 平台命名空间。

    只在账号与作品 ID 都齐全、且旧文件能唯一归到这本书时才复制；否则保持原位并
    返回 `needs_review`。重复执行按内容摘要去重，不产生第二份意图。
    """
    require_platform(platform)
    if not str(account).strip() or not str(platform_book_id).strip():
        return {"schema": SCHEMA, "status": "needs_review",
                "reason": "缺账号或平台作品 ID：旧文件保留原位供核对，不做迁移",
                "copied": 0, "skipped": 0}
    if not str(book).strip():
        return {"schema": SCHEMA, "status": "needs_review",
                "reason": "缺书名：旧队列按书名分目录，没有书名无法唯一归到这本书，不做迁移",
                "copied": 0, "skipped": 0}
    dest_root = namespace(project, platform, account=account,
                          platform_book_id=platform_book_id, book=book)
    if platform != DEFAULT_PLATFORM:
        return {"schema": SCHEMA, "status": "needs_review",
                "reason": "旧队列只属于番茄：其它平台没有可迁移的旧记录，不做迁移",
                "copied": 0, "skipped": 0}
    ledger_path = dest_root / MIGRATION_NAME
    ledger = _read(ledger_path, {"schema": SCHEMA, "entries": []})
    if not isinstance(ledger, dict):
        ledger = {"schema": SCHEMA, "entries": []}
    entries = ledger.get("entries") if isinstance(ledger.get("entries"), list) else []
    ledger["entries"] = entries
    # 只有「已复制且校验通过」才算迁移完成；停在 copying 的条目要在本轮复核目标，
    # 否则一次崩溃会让那一章永远既不复制也不报错。
    seen = {(str(entry.get("kind")), int(entry.get("chapter") or 0), str(entry.get("sha256")))
            for entry in entries
            if isinstance(entry, dict) and entry.get("state") == "copied" and entry.get("verified")}
    pending = {(str(entry.get("kind")), int(entry.get("chapter") or 0), str(entry.get("sha256"))): entry
               for entry in entries
               if isinstance(entry, dict) and entry.get("state") == "copying"}
    copied: List[Dict[str, Any]] = []
    skipped = 0
    roots = _legacy_roots(project, book)
    if not any(root.is_dir() for root in roots.values()):
        return {"schema": SCHEMA, "status": "nothing_to_migrate", "copied": 0,
                "skipped": 0, "reason": "没有找到旧队列/归档目录"}
    for kind, root in roots.items():
        if not root.is_dir():
            continue
        for chapter, path in bridge.queued_chapters(root).items():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return {"schema": SCHEMA, "status": "needs_review",
                        "reason": f"旧文件不可读：{path.name}（保留原位）",
                        "copied": len(copied), "skipped": skipped}
            digest = sha256_text(text)
            key = (kind, int(chapter), digest)
            if key in seen:
                skipped += 1
                continue
            if key in pending:
                resumed = _ensure_within(project, dest_root / kind / f"第{int(chapter):04d}章.txt")
                if resumed.is_file() and sha256_text(
                        resumed.read_text(encoding="utf-8", errors="replace")) == digest:
                    entry = pending[key]
                    entry["state"] = "copied"
                    entry["verified"] = True
                    entry["recovered_at"] = _now()
                    ledger["updated_at"] = _now()
                    _write(ledger_path, ledger)
                    seen.add(key)
                    copied.append(entry)
                    continue
            target = _ensure_within(project, dest_root / kind / f"第{int(chapter):04d}章.txt")
            if target.is_file():
                existing = sha256_text(target.read_text(encoding="utf-8", errors="replace"))
                if existing != digest:
                    conflict = {"kind": kind, "chapter": int(chapter),
                                "existing_sha256": existing, "source_sha256": digest,
                                "source": str(path), "at": _now()}
                    ledger.setdefault("conflicts", []).append(conflict)
                    ledger["updated_at"] = _now()
                    _write(ledger_path, ledger)
                    return {"schema": SCHEMA, "status": "needs_review",
                            "reason": f"目标已存在且内容不同：{target.name}（不覆盖，先核对）",
                            "copied": len(copied), "skipped": skipped,
                            "conflicts": [conflict]}
            target.parent.mkdir(parents=True, exist_ok=True)
            # 先落台账再复制：中途崩溃时下一次能看出「已登记但可能没写完」。
            entry = {"chapter": int(chapter), "kind": kind, "sha256": digest,
                     "bytes": len(text.encode("utf-8")), "state": "copying",
                     "source": str(path), "dest": str(target), "at": _now()}
            ledger.setdefault("entries", []).append(entry)
            ledger["updated_at"] = _now()
            _write(ledger_path, ledger)
            target.write_text(text, encoding="utf-8", newline="\n")
            entry["state"] = "copied"
            entry["verified"] = sha256_text(target.read_text(encoding="utf-8")) == digest
            ledger["updated_at"] = _now()
            _write(ledger_path, ledger)
            seen.add((kind, int(chapter), digest))
            copied.append(entry)
    ledger["schema"] = SCHEMA
    ledger["platform"] = platform
    ledger["account"] = account
    ledger["platform_book_id"] = platform_book_id
    ledger["updated_at"] = _now()
    _write(ledger_path, ledger)
    return {"schema": SCHEMA, "status": "migrated" if copied else "already_migrated",
            "copied": len(copied), "skipped": skipped,
            "namespace": str(dest_root), "entries": copied}


# --- 第一层：本地导出 ------------------------------------------------------

def format_chapter(chapter: int, title: str, body: str, *, platform: str) -> Dict[str, Any]:
    """按平台格式生成导出文本；不写盘、不上传。"""
    require_platform(platform)
    number = int(chapter)
    if number < 1:
        raise PublishError("章号必须从 1 开始")
    clean_title = str(title or "").strip() or f"第{number}章"
    if not CHAPTER_PREFIX_RE.match(clean_title):
        clean_title = f"第{number}章 {clean_title}"
    paragraphs = [line.strip() for line in str(body or "").splitlines()]
    kept = [line for line in paragraphs if line]
    if not kept:
        raise PublishError("正文为空：没有可导出的段落")
    text = clean_title + "\n\n" + "\n\n".join(kept) + "\n"
    data = text.encode("utf-8")
    if len(data) > MAX_EXPORT_BYTES:
        raise PublishError(f"单章超过 {MAX_EXPORT_BYTES} 字节：请先拆分再导出")
    return {"platform": platform, "chapter": number, "title": clean_title,
            "text": text, "bytes": len(data), "sha256": sha256_text(text),
            "paragraphs": len(kept),
            "chars": len(re.sub(r"\s+", "", "\n".join(kept))),
            "format": CAPABILITIES[platform]["format"]}


def _export_binding(project, chapter: int, *, title: str, body: str) -> Dict[str, Any]:
    """导出正文与服务器版本的绑定信息（E-03）。

    章节已存在：请求正文/标题必须逐字等于当前版本，否则拒绝——不能把从未
    进入版本层、也未审查的正文导出成“当前稿”。章节不存在（例如先导出大纲
    草稿）仍允许导出，但必须显式标注 ``review_bound=False``/``version_id=None``，
    不能与已审查版本混用。只读，不创建版本。
    """
    try:
        path = chapter_versions.chapter_path(project, int(chapter))
    except chapter_versions.VersionError:
        path = None
    if path is None:
        return {"version_bound": False, "review_bound": False, "version_id": None,
                "content_sha256": None, "binding": "chapter_missing",
                "review_reason": "chapter_missing"}
    content = _submission_content(project, chapter, title=title, body=body)
    reviewed = publication_state.review_binding(
        project, chapter, content_sha256=content["content_sha256"], text=content["text"])
    return {"version_bound": True, "review_bound": bool(reviewed.get("ok")),
            "version_id": content.get("version_id"),
            "content_sha256": content["content_sha256"], "binding": "current",
            "review_reason": None if reviewed.get("ok") else reviewed.get("reason")}


def export_chapter(project, *, platform: str, chapter: int, title: str, body: str,
                   account: str = "", platform_book_id: str = "") -> Dict[str, Any]:
    """导出到 `.webnovel/publish/<platform>/<账号-hash>/<平台作品ID>/exports/`。

    缺账号或平台作品 ID 直接拒绝（否则两本书会落到同一目录互相覆盖）；每次导出把
    上一版摘要压进 `versions`，绝不顺带上传。导出 manifest 明确记录
    ``version_bound``/``review_bound``，未绑定当前版本的导出不得冒充已审查稿（E-03）。
    """
    binding = _export_binding(project, chapter, title=title, body=body)
    built = format_chapter(chapter, title, body, platform=platform)
    folder = namespace(project, platform, account=account,
                       platform_book_id=platform_book_id) / EXPORT_DIR
    path = _ensure_within(project, folder / f"第{int(chapter):04d}章.txt")
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(built["text"], encoding="utf-8", newline="\n")
    manifest_path = folder / "manifest.json"
    manifest = _read(manifest_path, {"schema": SCHEMA, "platform": platform, "items": []})
    if not isinstance(manifest, dict) or not isinstance(manifest.get("items", []), list):
        manifest = {"schema": SCHEMA, "platform": platform, "items": [],
                    "corrupt": True}
    items = [item for item in manifest.get("items", [])
             if isinstance(item, dict) and int(item.get("chapter") or 0) != int(chapter)]
    previous = next((item for item in manifest.get("items", [])
                     if isinstance(item, dict) and int(item.get("chapter") or 0) == int(chapter)),
                    None)
    versions = list(previous.get("versions") or []) if previous else []
    if previous and previous.get("sha256") != built["sha256"]:
        versions.append({key: previous.get(key) for key in
                         ("sha256", "bytes", "chars", "title", "at")})
        versions = versions[-10:]
    items.append({"chapter": int(chapter), "sha256": built["sha256"],
                  "bytes": built["bytes"], "paragraphs": built["paragraphs"],
                  "chars": built["chars"], "title": built["title"],
                  "file": path.name, "at": _now(), "versions": versions,
                  "version_bound": binding["version_bound"],
                  "review_bound": binding["review_bound"],
                  "version_id": binding["version_id"],
                  "review_reason": binding["review_reason"]})
    manifest.update({"schema": SCHEMA, "platform": platform, "items": sorted(
        items, key=lambda item: int(item.get("chapter") or 0))})
    _write(manifest_path, manifest)
    return {key: built[key] for key in ("platform", "chapter", "title", "bytes",
                                        "sha256", "paragraphs", "chars")} | {
        "status": "exported", "path": str(path), "uploaded": False,
        "versions_kept": len(versions),
        "version_bound": binding["version_bound"],
        "review_bound": binding["review_bound"],
        "version_id": binding["version_id"],
        "review_reason": binding["review_reason"]}


def exports(project, *, platform: str, account: str = "", platform_book_id: str = "") -> Dict[str, Any]:
    folder = namespace(project, platform, account=account,
                       platform_book_id=platform_book_id) / EXPORT_DIR
    manifest = _read(folder / "manifest.json", {"schema": SCHEMA, "items": []})
    if not isinstance(manifest, dict):
        manifest = {"schema": SCHEMA, "items": [], "corrupt": True}
    items = [item for item in manifest.get("items", []) if isinstance(item, dict)]
    return {"platform": platform, "items": items, "folder": str(folder),
            "corrupt": bool(manifest.get("corrupt"))}


# --- 第二层：只读登记（人工上传结果与远端核验分开） ------------------------

def load_bindings(project) -> Dict[str, Any]:
    return _read(workspace(project) / BINDINGS_NAME, {"schema": SCHEMA, "items": []})


def bind_book(project, *, platform: str, account: str, platform_book_id: str,
              title: str = "", verified_via: str = "manual",
              observed_chapters: Optional[Sequence[int]] = None,
              probe_evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """登记平台书身份。

    `verified_via="readonly_probe"` 才可能写 `verified`；人工登记一律 `registered`，
    这样「人工上传成功」不会冒充「远端核验通过」。
    """
    require_platform(platform)
    if not str(account).strip() or not str(platform_book_id).strip():
        raise PublishError("绑定必须给出账号与平台作品稳定 ID")
    if verified_via not in ("manual", "readonly_probe"):
        raise PublishError("verified_via 只能是 manual 或 readonly_probe")
    chapters = sorted({int(item) for item in (observed_chapters or []) if int(item) > 0})
    evidence = probe_evidence if isinstance(probe_evidence, dict) else {}
    matches = (str(evidence.get("platform") or "") == platform
               and str(evidence.get("platform_book_id") or "") == str(platform_book_id)
               and set(int(item) for item in (evidence.get("chapters") or [])) >= set(chapters))
    verified = verified_via == "readonly_probe" and bool(chapters) and matches
    if verified_via == "readonly_probe" and not verified:
        note = "声称只读探测，但没有匹配的探测证据：只记为人工登记"
    else:
        note = ""
    status = "verified" if verified else "registered"
    data = load_bindings(project)
    items = [item for item in data.get("items", [])
             if not (item.get("platform") == platform and item.get("account") == account
                     and item.get("platform_book_id") == platform_book_id)]
    record = {"platform": platform, "account": account,
              "platform_book_id": platform_book_id, "title": str(title or "").strip(),
              "status": status, "verified_via": verified_via if verified else "manual",
              "evidence": {"chapters": evidence.get("chapters") or []} if verified else {},
              "note": note, "observed_chapters": chapters, "at": _now()}
    items.append(record)
    data.update({"schema": SCHEMA, "items": items})
    _write(workspace(project) / BINDINGS_NAME, data)
    return record


def binding(project, *, platform: str, account: str, platform_book_id: str) -> Dict[str, Any]:
    for item in load_bindings(project).get("items", []):
        if (item.get("platform") == platform and item.get("account") == account
                and item.get("platform_book_id") == platform_book_id):
            return dict(item)
    return {}


# --- 授权：只认服务端记录，不认请求体里的文本 ------------------------------

def load_authorizations(project) -> Dict[str, Any]:
    return _read(workspace(project) / AUTHORIZATIONS_NAME,
                 {"schema": SCHEMA, "items": []})


def authorize(project, *, platform: str, account: str, platform_book_id: str,
              chapters: Sequence[int], note: str, actor: str = "author",
              expires_at: str = "") -> Dict[str, Any]:
    require_platform(platform)
    if not str(note or "").strip():
        raise PublishError("授权必须写明依据（谁、哪本书、哪几章、什么时间）")
    numbers = sorted({int(item) for item in chapters if int(item) > 0})
    if not numbers:
        raise PublishError("授权至少要指定一章")
    scope = {"platform": platform, "account": str(account).strip(),
             "platform_book_id": str(platform_book_id).strip()}
    if not (scope["account"] and scope["platform_book_id"]):
        raise PublishError("授权必须绑定账号与平台作品 ID")
    data = load_authorizations(project)
    record = dict(scope, chapters=numbers, note=str(note).strip(), actor=actor,
                  granted_at=_now(), expires_at=str(expires_at or ""),
                  active=True)
    kept = []
    for item in data.get("items", []):
        if (item.get("active") and all(item.get(key) == scope[key] for key in scope)):
            # 保留历史：旧授权置为已撤销，不物理删除，审计链还在。
            kept.append(dict(item, active=False, revoked_at=_now(),
                             revoked_by=actor, revoke_reason="被新的授权替换"))
        else:
            kept.append(item)
    data["items"] = kept + [record]
    data["schema"] = SCHEMA
    _write(workspace(project) / AUTHORIZATIONS_NAME, data)
    return record


def authorization_for(project, *, platform: str, account: str,
                      platform_book_id: str, chapter: int) -> Dict[str, Any]:
    now = datetime.now(timezone(timedelta(hours=8)))
    for item in load_authorizations(project).get("items", []):
        if not item.get("active"):
            continue
        if (item.get("platform"), item.get("account"), item.get("platform_book_id")) != (
                platform, account, platform_book_id):
            continue
        if int(chapter) not in [int(value) for value in item.get("chapters", [])]:
            continue
        expires = str(item.get("expires_at") or "")
        if expires:
            try:
                stamp = datetime.fromisoformat(expires)
            except ValueError:
                continue
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=now.tzinfo)
            if stamp <= now:
                continue
        return dict(item)
    return {}


# --- 第三层：获准单章提交（意图先落盘） ------------------------------------

class PublishAdapter:
    """平台提交适配器的鸭子类型：返回 `{"accepted": bool, ...}`。"""

    def submit_draft(self, **kwargs):  # pragma: no cover - 生产实现由宿主提供
        raise NotImplementedError

    def read_chapter(self, **kwargs):  # pragma: no cover
        raise NotImplementedError


_ADAPTERS: Dict[str, Any] = {}


def register_adapter(platform: str, adapter) -> None:
    require_platform(platform)
    _ADAPTERS[platform] = adapter


def current_adapter(platform: str):
    return _ADAPTERS.get(platform)


def clear_adapters() -> None:
    _ADAPTERS.clear()


def _ledger_path(project, platform: str, account: str, book_id: str, chapter: int,
                 body_sha: str) -> Path:
    key = sha256_text("|".join([platform, account, book_id, str(int(chapter)), body_sha]))[:24]
    return namespace(project, platform, account=account,
                     platform_book_id=book_id) / LEDGER_DIR / f"{key}.json"


def ledger_entry(project, *, platform: str, account: str, platform_book_id: str,
                 chapter: int, body_sha256: str) -> Dict[str, Any]:
    path = _ledger_path(project, platform, account, platform_book_id, chapter, body_sha256)
    return _read(path, {})


def _submission_content(project, chapter: int, *, title: str, body: str) -> Dict[str, Any]:
    """取服务器当前版本正文；请求体只能与之逐字相符，不能自带任意正文。

    E-03：第三层提交的信任边界必须是“当前已审查版本”，不是客户端声明。
    版本索引与磁盘不一致时拒绝（要求先重新保存），绝不把旧对象当当前稿提交。
    """
    try:
        path = chapter_versions.chapter_path(project, int(chapter))
    except chapter_versions.VersionError as error:
        raise PublishError(f"章节版本不可用：{error}") from error
    if path is None:
        raise PublishError("章节不存在：先保存正文再提交")
    try:
        meta = chapter_versions.current_version(project, int(chapter))
        disk_sha = chapter_versions.file_sha256(path)
        if not disk_sha:
            raise PublishError("章节正文不可读")
        if isinstance(meta, dict):
            indexed = meta.get("sha256") or meta.get("content_sha256")
            if indexed and indexed != disk_sha:
                raise PublishError("章节版本与磁盘正文不一致：先重新保存再提交")
        resolved = chapter_versions.read_version(project, int(chapter))
        if resolved.get("sha256") != disk_sha or not isinstance(resolved.get("text"), str):
            raise PublishError("章节版本与磁盘正文不一致：先重新保存再提交")
        parsed = chapter_versions.parse_chapter_name(path.name)
        current_title = parsed[1] if parsed else ""
    except chapter_versions.VersionError as error:
        raise PublishError(f"章节版本不可用：{error}") from error
    text = resolved["text"]
    if body is None or not str(body).strip():
        raise PublishError("正文为空：没有可提交的正文")
    if body_digest(str(body)) != body_digest(text):
        raise PublishError("请求正文不是服务器当前版本：请先保存并重新审查当前稿")
    if str(title or "").strip():
        wanted = str(title).strip()
        parsed_title = chapter_versions.parse_chapter_name(wanted if wanted.endswith(".md") else wanted + ".md")
        if not (wanted == current_title
                or (parsed_title and parsed_title[0] == int(chapter)
                    and parsed_title[1] == current_title)):
            raise PublishError("请求标题与当前章节不一致：只能提交当前版本")
    return {"text": text, "title": current_title, "content_sha256": disk_sha,
            "version_id": (meta or {}).get("version_id")}


def submit_chapter(project, *, platform: str, account: str, platform_book_id: str,
                   chapter: int, title: str, body: str) -> Dict[str, Any]:
    """获准单章提交：能力 → 适配器 → 授权 → 当前版本/审查 → 意图 → 写入 → 回读。

    任何一步不满足就停在原地，不调用适配器；不做跨平台转投。
    已存在意图/结果未知/正文不符时一律返回 duplicate——只能先对账，不能强发。
    """
    caps = require_platform(platform)
    if caps.get("can_submit") is not True:
        return {"platform": platform, "chapter": int(chapter), "status": "refused",
                "writes": 0,
                "reason": f"{caps['label']} 没有可确认的提交方式（{caps['submission']}）："
                          "本版只开放导出与只读登记"}
    adapter = current_adapter(platform)
    if adapter is None:
        return {"platform": platform, "chapter": int(chapter), "status": "unavailable",
                "writes": 0, "reason": "该平台没有注册提交适配器：不写入，先配适配器"}
    if not binding(project, platform=platform, account=account,
                   platform_book_id=platform_book_id):
        return {"platform": platform, "chapter": int(chapter), "status": "refused",
                "writes": 0, "reason": "目标书尚未登记：先做只读绑定"}
    if not authorization_for(project, platform=platform, account=account,
                             platform_book_id=platform_book_id, chapter=chapter):
        return {"platform": platform, "chapter": int(chapter), "status": "refused",
                "writes": 0, "reason": "没有覆盖该章的授权记录：先在服务端登记授权"}
    content = _submission_content(project, chapter, title=title, body=body)
    reviewed = publication_state.review_binding(
        project, chapter, content_sha256=content["content_sha256"], text=content["text"])
    if not reviewed.get("ok"):
        return {"platform": platform, "chapter": int(chapter), "status": "refused",
                "writes": 0, "version_id": content.get("version_id"),
                "reason": f"正文未绑定当前版本的审查回执（{reviewed.get('reason')}）："
                          "先审查当前稿再提交"}
    # E-01G：v0.9 质量层是第二事实源。只拦“与当前版本一致”的 block 结论；
    # 未审查/旧版本结论不阻断 legacy 路径，但会随响应返回给调用方。
    quality = publication_state.quality_advisory(
        project, chapter, content_sha256=content["content_sha256"],
        version_id=str(content.get("version_id") or ""))
    if quality.get("gate") == "block":
        return {"platform": platform, "chapter": int(chapter), "status": "refused",
                "writes": 0, "version_id": content.get("version_id"),
                "quality": quality,
                "reason": "v0.9 质量审查结论为 block：先修订并重新审查当前稿再提交"}
    built = format_chapter(chapter, content["title"], content["text"], platform=platform)
    path = _ledger_path(project, platform, account, platform_book_id, count := int(chapter),
                        built["sha256"])
    entry = _read(path, {})
    state = str(entry.get("state") or "")
    if state in ("intent", "accepted"):
        return {"platform": platform, "chapter": count, "status": "duplicate",
                "writes": 0, "reason": "该章该版本已有提交记录：先去对账",
                "ledger": str(path)}
    if state in ("unknown", "mismatch"):
        # 结果未知或回执不符：只允许对账，绝不因「再来一次」而真实重发。
        return {"platform": platform, "chapter": count, "status": "duplicate",
                "writes": 0,
                "reason": f"上一条记录状态是 {state}：只对账，不重发（对账后才能再投）",
                "ledger": str(path)}
    intent = {"schema": SCHEMA, "platform": platform, "account": account,
              "platform_book_id": platform_book_id, "chapter": count,
              "body_sha256": built["sha256"], "bytes": built["bytes"],
              "content_sha256": content["content_sha256"],
              "version_id": content.get("version_id"),
              "state": "intent", "attempts": int(entry.get("attempts") or 0) + 1,
              "created_at": entry.get("created_at") or _now(), "updated_at": _now()}
    _write(path, intent)
    # E-01D：在真正调用适配器前先落“结果待核对”回执。回执写不进去时拒绝
    # 调用平台，避免出现“平台已写入、本地仍可删除”的无回执窗口。
    pending = publication_state.record_pending(
        project, count, content_sha256=content["content_sha256"], platform=platform,
        account=account, platform_book_id=platform_book_id,
        source="publishing.submit_chapter", evidence=str(path),
        reason="adapter_result_pending")
    if not pending.get("recorded"):
        intent.update({"state": "abandoned", "updated_at": _now(),
                       "reason": f"发布回执不可写：{pending.get('reason')}"})
        _write(path, intent)
        return {"platform": platform, "chapter": count, "status": "refused",
                "writes_attempted": 0, "writes_confirmed": 0,
                "publication_state": pending, "ledger": str(path),
                "reason": "发布回执不可写，未调用适配器（避免无回执的平台写入）"}
    try:
        result = adapter.submit_draft(platform=platform, account=account,
                                      platform_book_id=platform_book_id,
                                      chapter=count, title=built["title"],
                                      body=built["text"], body_sha256=built["sha256"])
    except Exception as error:  # 结果未知：只对账，不重试
        intent.update({"state": "unknown", "updated_at": _now(),
                       "reason": f"提交结果未知：{error}"})
        _write(path, intent)
        return {"platform": platform, "chapter": count, "status": "unknown",
                "writes_attempted": 1, "writes_confirmed": 0,
                "publication_state": pending,
                "reason": "提交结果未知：只对账，不重试", "ledger": str(path)}
    if not isinstance(result, dict) or result.get("accepted") is not True:
        intent.update({"state": "unknown", "updated_at": _now(),
                       "reason": "适配器未确认接收"})
        _write(path, intent)
        return {"platform": platform, "chapter": count, "status": "unknown",
                "writes_attempted": 1, "writes_confirmed": 0,
                "publication_state": pending,
                "reason": "适配器未确认接收：只对账，不重试", "ledger": str(path)}
    echoed = str(result.get("body_sha256") or "")
    matched = echoed == built["sha256"]
    if not matched:
        # 回执与提交正文不一致：不记「已确认写入」，交给作者对账。
        intent.update({"state": "mismatch", "updated_at": _now(),
                       "remote_id": str(result.get("remote_id") or ""),
                       "echoed_sha256": echoed, "body_matches": False,
                       "reason": "平台回执的正文摘要与提交的正文不一致：只对账，不重试"})
        _write(path, intent)
        return {"platform": platform, "chapter": count, "status": "mismatch",
                "writes_attempted": 1, "writes_confirmed": 0,
                "body_matches": False, "remote_id": intent["remote_id"],
                "publication_state": pending,
                "reason": intent["reason"], "ledger": str(path)}
    intent.update({"state": "accepted", "updated_at": _now(),
                   "remote_id": str(result.get("remote_id") or ""),
                   "echoed_sha256": echoed, "body_matches": True})
    _write(path, intent)
    recorded = publication_state.record_published(
        project, count, content_sha256=content["content_sha256"],
        platform=platform, account=account, platform_book_id=platform_book_id,
        remote_id=intent["remote_id"], source="publishing.submit_chapter",
        evidence=str(path))
    return {"platform": platform, "chapter": count, "status": "accepted",
            "writes_attempted": 1, "writes_confirmed": 1,
            "body_matches": True, "remote_id": intent["remote_id"],
            "ledger": str(path), "publication_state": recorded}


TRANSITIONS = {"intent": ("accepted", "abandoned"),
               "unknown": ("accepted", "abandoned"),
               "mismatch": ("accepted", "abandoned")}


def reconcile(project, *, platform: str, account: str, platform_book_id: str,
              chapter: int, body_sha256: str, resolution: str,
              note: str = "", evidence: str = "") -> Dict[str, Any]:
    """人工对账：只允许从在途/未知/回执不符走到终态；abandoned 是终态。"""
    require_platform(platform)
    if resolution not in ("accepted", "abandoned"):
        raise PublishError("resolution 只能是 accepted 或 abandoned")
    if not str(note or "").strip():
        raise PublishError("对账必须写明依据：看到了什么、在哪里看到的")
    if not str(evidence or "").strip():
        raise PublishError("对账必须给出证据（平台页面/回执编号/截图路径）")
    path = _ledger_path(project, platform, account, platform_book_id, chapter, body_sha256)
    entry = _read(path, {})
    if not entry:
        raise PublishError("没有这条提交记录：先核对平台侧再对账")
    current = str(entry.get("state") or "")
    allowed = TRANSITIONS.get(current, ())
    if resolution not in allowed:
        raise PublishError(f"当前状态是 {current or '空'}，不能改成 {resolution}")
    entry.update({"state": "accepted" if resolution == "accepted" else "abandoned",
                  "resolution": resolution, "note": str(note).strip(),
                  "evidence": str(evidence).strip(),
                  "writes_confirmed": 1 if resolution == "accepted" else 0,
                  "updated_at": _now()})
    _write(path, entry)
    result = {"platform": platform, "chapter": int(chapter), "state": entry["state"],
              "resolution": resolution, "ledger": str(path)}
    if resolution == "accepted":
        # 人工对账确认平台已发布：也要成为章节只读状态的证据（E-01）。
        result["publication_state"] = publication_state.record_published(
            project, chapter, content_sha256=str(entry.get("content_sha256") or ""),
            platform=platform, account=account, platform_book_id=platform_book_id,
            remote_id=str(entry.get("remote_id") or ""), source="publishing.reconcile",
            evidence=str(evidence).strip())
    else:
        # abandoned 证明平台没有写入，清除待核对标记；已发布事实不受影响。
        result["publication_state"] = publication_state.clear_pending(
            project, chapter, reason="reconcile_abandoned", evidence=str(path))
    return result


# --- 状态汇总（只读） ------------------------------------------------------

def status(project) -> Dict[str, Any]:
    target = target_platform(project)
    exports_summary = {}
    for name in PLATFORMS:
        candidates = [item for item in load_bindings(project).get("items", [])
                      if isinstance(item, dict) and item.get("platform") == name]
        if target.get("platform") == name and target:
            candidates.insert(0, {"account": target.get("account", ""),
                                  "platform_book_id": target.get("platform_book_id", "")})
        for item in candidates:
            account = str(item.get("account") or "")
            book = str(item.get("platform_book_id") or "")
            if not account or not book:
                continue
            try:
                exports_summary[name] = exports(project, platform=name, account=account,
                                                platform_book_id=book)
            except PublishError:
                continue
            break
    ledger = []
    root = workspace(project)
    paths = sorted(root.rglob(f"{LEDGER_DIR}/*.json")) if root.is_dir() else []
    corrupt = 0
    for path in paths:
        try:
            data = _read(path, None, strict=True)
        except PublishError:
            corrupt += 1
            continue
        if not isinstance(data, dict) or not data:
            corrupt += 1
            continue
        ledger.append({"platform": data.get("platform"), "chapter": data.get("chapter"),
                       "state": data.get("state"), "body_sha256": data.get("body_sha256"),
                       "file": str(path)})
    return {"schema": SCHEMA, "platforms": capabilities(), "target": target_platform(project),
            "exports": exports_summary, "corrupt_ledgers": corrupt,
            "bindings": load_bindings(project).get("items", []),
            "authorizations": load_authorizations(project).get("items", []),
            "ledger": ledger}
