"""正文版本、候选与提交（方案 v3.0 M01）。

单一职责：为报告、修订和恢复提供最小可靠存储。不换数据库，也不改现有
正文目录（``正文/*.md`` 仍是唯一"当前稿"）。本模块只追加：

* 按内容哈希保存的不可变正文（``objects/<sha256>.txt``）；
* 每章一份轻量索引（当前版本 + 版本列表）；
* 候选稿（含基线版本、来源引用），提交前不碰当前稿；
* 提交记录（``commits/<op_id>.json``）：幂等标识与多文件提交标记。

两种哈希分工明确，不可混用：

* ``sha256``：**原始字节**哈希，用于校验对象文件、判断"保存后读回一致"、
  比较并发修改。与 ``publication_safety.digest_file`` 同算法。
* ``body_digest``：**规范化文本**哈希（统一换行、去行尾空白），用于审查
  报告绑定，与既有 review 回执里的 ``body_sha256`` 同一算法。

多文件提交不是事务：先写提交标记（prepared）→ 对象 → 正文 → 索引 → 标记
committed。任何一步崩溃都靠 ``recover_pending()`` 补齐或明确停在 conflict，
不会把半完成结果当成当前稿。
"""
from __future__ import annotations

import errno
import hashlib
import os
import re
import sys
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from fanqie_auto_publish.publication_safety import (
        atomic_json, body_digest, file_lock, read_json_strict, replace_with_retry,
    )
except ImportError:  # 直接以脚本运行本文件所在目录时
    from publication_safety import (  # type: ignore
        atomic_json, body_digest, file_lock, read_json_strict, replace_with_retry,
    )

SCHEMA_VERSION = 1
_LOCK_NAME = ".lock"
_ORIGINAL_REPLACE = replace_with_retry
_WINDOWS_BAD = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_FS_NAME_LIMIT = 255
_TEMP_NAME_EXTRA = 1 + 32 + 4  # ".<32 hex>.tmp"


def _require_id(value: str, code: str = "invalid_operation_id") -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text):
        raise VersionConflict(code)
    return text
_CHAPTER_PATTERNS = (
    re.compile(r"第\s*0*(\d+)\s*章(?:[：:\-＿_\s]*(.*))?$"),
    re.compile(r"^\s*0*(\d+)(?:[：:\-＿_\s]*(.*))?$"),
)
_VERSION_SUBDIRS = ("objects", "candidates", "commits", "staging")


class VersionError(RuntimeError):
    """稳定的原因码，不包含正文内容。"""


class VersionConflict(VersionError):
    pass


class VersionNotFound(VersionError):
    pass


class VersionCorrupt(VersionError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_title(title: str) -> str:
    """章节标题的统一比较形态：NFC + 去首尾空白（不改写磁盘文件名）。"""
    return unicodedata.normalize("NFC", str(title or "")).strip()


def title_digest(title: str) -> str:
    return hashlib.sha256(normalize_title(title).encode("utf-8")).hexdigest()


def version_fingerprint(content_sha256: str, title_sha256: str) -> str:
    """综合版本指纹：正文原始字节哈希 + NUL + 标题摘要（全套件统一）。"""
    return hashlib.sha256((str(content_sha256) + "\x00" + str(title_sha256)).encode("utf-8")).hexdigest()


def new_version_id(seq: int) -> str:
    return f"ver_{int(seq):04d}_{uuid.uuid4().hex[:8]}"


def _assert_version_store(project) -> None:
    """Reject ``.webnovel`` / ``chapter_versions`` and nested store symlinks.

    A project directory may arrive through a sync tool or a hostile archive;
    writing objects/index through a directory symlink would silently place
    version data outside the project (A-P2-12).  Checking only the two outer
    directories left ``objects``/``candidates``/``commits``/``staging`` free to
    point outside the book (A-P2-10).
    """
    root = Path(project).resolve()
    current = Path(project)
    for part in (".webnovel", "chapter_versions"):
        current = current / part
        try:
            linked = current.is_symlink()
        except OSError:
            linked = True
        if linked:
            raise VersionConflict("unsafe_version_store")
    store = Path(project) / ".webnovel" / "chapter_versions"
    if store.exists():
        try:
            resolved = store.resolve()
        except OSError as exc:
            raise VersionConflict("unsafe_version_store") from exc
        if resolved != root and root not in resolved.parents:
            raise VersionConflict("unsafe_version_store")
        for name in _VERSION_SUBDIRS:
            child = store / name
            try:
                if not child.exists() and not child.is_symlink():
                    continue
                if child.is_symlink():
                    raise VersionConflict("unsafe_version_store")
                child_resolved = child.resolve()
            except OSError as exc:
                raise VersionConflict("unsafe_version_store") from exc
            if child_resolved != resolved and resolved not in child_resolved.parents:
                raise VersionConflict("unsafe_version_store")


def store_root(project) -> Path:
    _assert_version_store(project)
    return Path(project) / ".webnovel" / "chapter_versions"


def project_id(project) -> str:
    return str(Path(project).resolve()).replace("\\", "/")


def _paths(project) -> Dict[str, Path]:
    root = store_root(project)
    return {
        "root": root,
        "index": root / "index.json",
        "objects": root / "objects",
        "candidates": root / "candidates",
        "commits": root / "commits",
        "staging": root / "staging",
        "lock": root / _LOCK_NAME,
    }


def _ensure(project) -> Dict[str, Path]:
    paths = _paths(project)
    for key in ("root", "objects", "candidates", "commits", "staging"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


# --------------------------------------------------------------------------- 索引

def _empty_index(project) -> Dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "project_id": project_id(project),
            "updated_at": _now(), "chapters": {}, "unattributed": []}


def load_index(project) -> Dict[str, Any]:
    """读取索引；旧/缺失索引按空索引处理，不重写任何已有数据。"""
    paths = _paths(project)
    if not paths["index"].exists():
        return _empty_index(project)
    data = read_json_strict(paths["index"])
    if not isinstance(data, dict):
        raise VersionCorrupt("index_not_object")
    if "schema_version" not in data and "schema" in data:
        data["schema_version"] = data["schema"]
    if data.get("schema_version") != SCHEMA_VERSION:
        raise VersionCorrupt("index_schema_unsupported")
    data.setdefault("chapters", {})
    data.setdefault("unattributed", [])
    return data


def _save_index(project, index: Dict[str, Any]) -> None:
    index["project_id"] = project_id(project)
    index["schema_version"] = SCHEMA_VERSION
    index["updated_at"] = _now()
    atomic_json(_paths(project)["index"], index)


def _chapter_entry(index, chapter: int) -> Dict[str, Any]:
    entry = index["chapters"].get(str(int(chapter)))
    if not isinstance(entry, dict):
        entry = {"current": None, "versions": []}
        index["chapters"][str(int(chapter))] = entry
    entry.setdefault("current", None)
    entry.setdefault("versions", [])
    return entry


def _next_seq(entry) -> int:
    return 1 + max([int(v.get("seq", 0)) for v in entry["versions"]] or [0])


# ----------------------------------------------------------------------- 正文定位

def parse_chapter_name(name: str) -> Optional[Tuple[int, str]]:
    stem = Path(name).stem.strip()
    for pattern in _CHAPTER_PATTERNS:
        match = pattern.search(stem)
        if match:
            title = (match.group(2) or "").strip(" -—–_：:　")
            return int(match.group(1)), title
    return None


def body_dir(project) -> Path:
    return Path(project) / "正文"


def chapter_path(project, chapter: int) -> Optional[Path]:
    """按章号找现有正文；多个同名章号视为冲突，不猜。

    大小写不敏感卷（APFS 默认）上 `*.MD` 不会被 `glob("*.md")` 列出，
    所以这里按后缀小写过滤并单独检测「同一名字只差大小写」的冲突——
    否则会在同一 inode 上新建第二个文件，静默覆盖作者原稿。
    """
    folder = body_dir(project)
    if not folder.is_dir():
        return None
    wanted = int(chapter)
    found = []
    seen = {}
    with os.scandir(folder) as entries:
        for entry in entries:
            name = entry.name
            if not name.lower().endswith(".md"):
                continue
            try:
                if not entry.is_file():
                    continue
            except OSError:
                continue
            parsed = parse_chapter_name(name)
            if not parsed or parsed[0] != wanted:
                continue
            found.append(Path(entry.path))
            key = unicodedata.normalize("NFC", name).casefold()
            if key in seen and seen[key] != name:
                # 只有「同一章号、名字只差大小写」才算冲突；`ﬁ`/`é` 这类
                # casefold/NFC 等价的无关文件不应拖累别的章。
                raise VersionConflict("case_conflict")
            seen[key] = name
    if len(found) > 1:
        raise VersionConflict("duplicate_chapter_files")
    return found[0] if found else None


def chapter_map(project) -> Dict[int, Path]:
    """一次枚举正文目录，返回 {章号: 路径}。

    批量场景（如 `adopt_legacy`）必须用它：逐章调 `chapter_path` 是 O(N²)，
    300 章项目会从毫秒退化到几十秒，升级看起来像卡死。
    """
    folder = body_dir(project)
    if not folder.is_dir():
        return {}
    mapping: Dict[int, Path] = {}
    seen = {}
    with os.scandir(folder) as entries:
        for entry in entries:
            name = entry.name
            if not name.lower().endswith(".md"):
                continue
            try:
                if not entry.is_file():
                    continue
            except OSError:
                continue
            parsed = parse_chapter_name(name)
            if not parsed:
                continue
            number, _title = parsed
            key = unicodedata.normalize("NFC", name).casefold()
            if key in seen and seen[key] != name:
                raise VersionConflict("case_conflict")
            seen[key] = name
            if number in mapping:
                raise VersionConflict("duplicate_chapter_files")
            mapping[number] = Path(entry.path)
    return mapping


def _chapter_title(project, chapter: int, path: Optional[Path] = None) -> str:
    path = path or chapter_path(project, chapter)
    if path is None:
        return ""
    parsed = parse_chapter_name(path.name)
    return parsed[1] if parsed else ""


def validate_chapter_filename(chapter: int, title: str, *, with_temporary: bool = False) -> str:
    """Return the on-disk name, refusing titles whose UTF-8 name exceeds 255 bytes.

    ``MAX_TITLE_CHARS`` counts characters, but ext4/APFS/NTFS limit a *name*
    to 255 bytes; 120 CJK characters are 360 bytes.  The temporary suffix used
    by every atomic write must be included in the budget (A-P2-6).
    """
    safe = unicodedata.normalize("NFC", title or "").strip()
    name = f"第{int(chapter)}章" + (f"-{safe}" if safe else "") + ".md"
    budget = _FS_NAME_LIMIT
    if with_temporary:
        # ".<uuid hex>.tmp" is added by every atomic writer.
        if len(name.encode("utf-8")) + _TEMP_NAME_EXTRA > budget:
            raise VersionConflict("title_too_long_for_filesystem")
        return name
    if len(name.encode("utf-8")) > budget:
        raise VersionConflict("title_too_long_for_filesystem")
    return name


def _new_chapter_path(project, chapter: int, title: str) -> Path:
    safe = unicodedata.normalize("NFC", title or "").strip()
    if safe and (_WINDOWS_BAD.search(safe) or safe.endswith((" ", "."))):
        raise VersionConflict("invalid_chapter_title")
    name = validate_chapter_filename(chapter, safe, with_temporary=True)
    return body_dir(project) / name


def raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _encode(text: str) -> bytes:
    return text.encode("utf-8")


def _decode(data: bytes) -> str:
    return data.decode("utf-8-sig")


def file_sha256(path) -> Optional[str]:
    if path is None:
        return None
    path = Path(path)
    return raw_sha256(path.read_bytes()) if path.is_file() else None


# ------------------------------------------------------------------------- 对象

def _object_path(project, sha: str) -> Path:
    return _paths(project)["objects"] / f"{sha}.txt"


def _store_object(project, data: bytes) -> str:
    sha = raw_sha256(data)
    target = _object_path(project, sha)
    if target.is_file():
        if file_sha256(target) != sha:
            raise VersionCorrupt("object_hash_mismatch")
        return sha
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        replace_with_retry(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    if file_sha256(target) != sha:
        raise VersionCorrupt("object_write_mismatch")
    return sha


def read_object(project, sha: str) -> bytes:
    selector = str(sha or "")
    if not re.fullmatch(r"[0-9a-f]{64}", selector):
        raise VersionNotFound("object_missing")
    path = _object_path(project, selector)
    if not path.is_file():
        raise VersionNotFound("object_missing")
    data = path.read_bytes()
    if raw_sha256(data) != selector:
        raise VersionCorrupt("object_hash_mismatch")
    return data


# ------------------------------------------------------------------------- 候选

def save_candidate(project, chapter: int, content: str, *, source: str = "candidate",
                   base_sha256: Optional[str] = None, run_id: Optional[str] = None,
                   attempt_id: Optional[str] = None, note: str = "",
                   title: Optional[str] = None, op_id: Optional[str] = None) -> Dict[str, Any]:
    """登记一份候选稿。不修改当前正文；重复登记同一 op_id 返回原记录。"""
    if not isinstance(content, str):
        raise VersionConflict("content_not_text")
    paths = _ensure(project)
    candidate_id = _require_id(op_id) if op_id else uuid.uuid4().hex
    target = paths["candidates"] / f"{candidate_id}.json"
    data = _encode(content)
    record = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "project_id": project_id(project),
        "chapter_id": int(chapter),
        "title": _chapter_title(project, chapter) if title is None else title,
        "sha256": raw_sha256(data),
        "body_digest": body_digest(content),
        "bytes": len(data),
        "base_sha256": base_sha256,
        "source": source,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "note": note,
        "created_at": _now(),
        "content": content,
    }
    with file_lock(paths["lock"]):
        if target.is_file():
            existing = read_json_strict(target)
            if existing.get("sha256") != record["sha256"] or existing.get("chapter_id") != record["chapter_id"]:
                raise VersionConflict("candidate_id_reused")
            return {k: v for k, v in existing.items() if k != "content"}
        atomic_json(target, record)
    return {k: v for k, v in record.items() if k != "content"}


def read_candidate(project, candidate_id: str) -> Dict[str, Any]:
    path = _paths(project)["candidates"] / f"{_require_id(candidate_id, 'invalid_candidate_id')}.json"
    if not path.is_file():
        raise VersionNotFound("candidate_missing")
    record = read_json_strict(path)
    if not isinstance(record, dict):
        raise VersionCorrupt("candidate_not_object")
    return record


# ------------------------------------------------------------------- 提交与恢复

def _commit_path(project, op_id: str) -> Path:
    return _paths(project)["commits"] / f"{_require_id(op_id)}.json"


def _load_commit(project, op_id: str) -> Optional[Dict[str, Any]]:
    path = _commit_path(project, op_id)
    return read_json_strict(path) if path.is_file() else None


def _register_version(entry, *, sha256: str, digest: str, size: int, source: str,
                      op_id: Optional[str], run_id: Optional[str],
                      attempt_id: Optional[str], parent: Optional[str],
                      title: str, note: str) -> Dict[str, Any]:
    seq = _next_seq(entry)
    version_id = new_version_id(seq)
    t_digest = title_digest(title)
    meta = {"seq": seq, "version_seq": seq, "version_id": version_id,
            "sha256": sha256, "content_sha256": sha256, "body_digest": digest,
            "bytes": size, "source": source, "op_id": op_id, "run_id": run_id,
            "attempt_id": attempt_id, "parent": parent, "title": title,
            "title_digest": t_digest,
            "version_fingerprint": version_fingerprint(sha256, t_digest),
            "note": note, "created_at": _now()}
    entry["versions"].append(meta)
    return meta


def _write_chapter_bytes(project, chapter: int, data: bytes, title: str) -> Path:
    path = chapter_path(project, chapter)
    if path is None:
        path = _new_chapter_path(project, chapter, title or "")
        path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        replace_with_retry(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def commit_candidate(project, chapter: int, candidate_id: str, *, op_id: Optional[str] = None,
                     expected_sha256: Optional[str] = None,
                     title: Optional[str] = None, allow_new: bool = False,
                     action: str = "chapter_save") -> Dict[str, Any]:
    """把候选稿提交为当前正文，并登记版本。

    ``expected_sha256`` 是调用方读到的当前正文原始字节哈希；与实际不符即
    ``VersionConflict('concurrent_modification')``，绝不覆盖。为 ``None`` 时
    以本次加锁后读到的当前状态为准（不拒绝，但也不声明没有并发）。
    """
    paths = _ensure(project)
    op = op_id or uuid.uuid4().hex
    candidate = read_candidate(project, candidate_id)
    if int(candidate.get("chapter_id", -1)) != int(chapter):
        raise VersionConflict("candidate_chapter_mismatch")
    data = _encode(candidate["content"])
    sha = raw_sha256(data)
    if sha != candidate.get("sha256"):
        raise VersionCorrupt("candidate_content_changed")

    with file_lock(paths["lock"]):
        existing = _load_commit(project, op)
        if existing is not None and existing.get("state") == "abandoned":
            _commit_path(project, op).unlink(missing_ok=True)
            existing = None
        if existing is not None:
            if str(existing.get("action") or "chapter_save") != str(action or "chapter_save"):
                # The same op_id must not be reclaimed by a different kind of
                # operation (new/split/import/restore): returning "saved" for
                # another action's commit hid the save from idempotency and
                # version history (A-P3-08).
                raise VersionConflict("operation_id_action_conflict")
            if existing.get("chapter_id") == int(chapter) and existing.get("content_sha256") == sha:
                index = load_index(project)
                entry = _chapter_entry(index, chapter)
                if (existing.get("state") == "committed"
                        and file_sha256(chapter_path(project, chapter)) == sha
                        and entry.get("current") == sha):
                    return existing
                raise VersionConflict("operation_incomplete")
            raise VersionConflict("operation_id_reused")

        current_path = chapter_path(project, chapter)
        current_sha = file_sha256(current_path)
        if current_sha is None and not allow_new:
            raise VersionNotFound("chapter_missing")
        if expected_sha256 is not None and expected_sha256 != current_sha:
            raise VersionConflict("concurrent_modification")

        index = load_index(project)
        entry = _chapter_entry(index, chapter)
        index_reconciled = entry.get("current") not in (None, current_sha)
        final_title = title if title is not None else (candidate.get("title") or _chapter_title(project, chapter))
        title_before = _chapter_title(project, chapter, current_path) if current_path is not None else None
        title_pending = bool(current_path is not None
                             and normalize_title(final_title or "") != normalize_title(title_before or ""))
        if current_path is None:
            # Refuse an impossible filesystem name before leaving a prepared
            # commit record behind (A-P2-6).
            validate_chapter_filename(chapter, final_title or "", with_temporary=True)

        record = {
            "schema_version": SCHEMA_VERSION, "op_id": op, "project_id": project_id(project),
            "chapter_id": int(chapter), "candidate_id": candidate_id, "content_sha256": sha,
            "previous_sha256": current_sha, "state": "prepared", "done": [],
            "title": final_title, "title_before": title_before,
            "title_pending": title_pending, "title_rename_done": not title_pending,
            "index_reconciled": index_reconciled, "action": str(action or "chapter_save"),
            "created_at": _now(), "updated_at": _now(),
        }
        atomic_json(_commit_path(project, op), record)
        _store_object(project, data)
        record["done"].append("object")
        atomic_json(_commit_path(project, op), record)

        path = _write_chapter_bytes(project, chapter, data, final_title or "")
        record["chapter_path"] = str(path)
        record["done"].append("chapter")
        record["state"] = "chapter_written"
        atomic_json(_commit_path(project, op), record)

        meta = _register_version(entry, sha256=sha, digest=candidate.get("body_digest") or body_digest(candidate["content"]),
                                 size=len(data), source=candidate.get("source", "candidate"), op_id=op,
                                 run_id=candidate.get("run_id"), attempt_id=candidate.get("attempt_id"),
                                 parent=current_sha, title=final_title, note=candidate.get("note", ""))
        entry["current"] = sha
        entry["current_version_id"] = meta["version_id"]
        _save_index(project, index)
        record["done"].append("index")
        record["version"] = meta
        record["version_id"] = meta["version_id"]
        record["state"] = "committed"
        record["updated_at"] = _now()
        atomic_json(_commit_path(project, op), record)
        return record


def write_chapter(project, chapter: int, content: str, *, op_id: Optional[str] = None,
                  expected_sha256: Optional[str] = None, source: str = "writer",
                  run_id: Optional[str] = None, attempt_id: Optional[str] = None,
                  note: str = "", title: Optional[str] = None,
                  allow_new: bool = False, action: str = "chapter_save") -> Dict[str, Any]:
    """保存候选 + 提交，一步完成（供写作/修订路径调用）。"""
    document = save_candidate(project, chapter, content, source=source,
                              base_sha256=expected_sha256, run_id=run_id,
                              attempt_id=attempt_id, note=note, title=title,
                              op_id=op_id)
    result = commit_candidate(project, chapter, document["candidate_id"], op_id=op_id,
                              expected_sha256=expected_sha256, title=title, allow_new=allow_new,
                              action=action)
    if str(result.get("state") or "") == "committed":
        # 正文一旦换了版本，依据旧正文的事实就不再成立：走统一失效入口，不各写一套。
        try:
            from . import invalidation
            digest = str(result.get("content_sha256") or result.get("sha256") or expected_sha256 or "")[:12]
            result["invalidation"] = invalidation.invalidate(
                project, chapters=[chapter], reason="chapter_edited",
                source=f"versions:write_chapter:{digest}",
                op_id=str(op_id or f"write-{chapter}-{digest}"))
        except (ValueError, OSError, RuntimeError) as exc:
            result["invalidation"] = {"status": "skipped", "error": str(exc)[:200]}
    return result


def _material_for_commit(project, record: Dict[str, Any], current_sha: Optional[str]) -> bytes:
    """Return the bytes a pending commit should land, never fabricating content.

    Raw commits (``candidate_id=None``) have no candidate fallback: if the
    object is missing and the body is not already the committed bytes, the
    only safe outcome is a terminal ``conflict(source_missing)`` (A-P1-1).
    """
    sha = str(record.get("content_sha256") or "")
    try:
        return read_object(project, sha)
    except VersionError:
        pass
    chapter = int(record.get("chapter_id") or 0)
    if current_sha == sha and chapter > 0:
        path = chapter_path(project, chapter)
        if path is not None:
            data = path.read_bytes()
            if raw_sha256(data) == sha:
                _store_object(project, data)
                return data
    candidate_id = record.get("candidate_id")
    if candidate_id:
        try:
            candidate = read_candidate(project, candidate_id)
        except VersionError:
            candidate = {}
        content = candidate.get("content") if isinstance(candidate, dict) else None
        if isinstance(content, str):
            data = _encode(content)
            if raw_sha256(data) == sha:
                _store_object(project, data)
                return data
    raise VersionNotFound("source_missing")


def _candidate_meta(project, record: Dict[str, Any]) -> Dict[str, Any]:
    candidate_id = record.get("candidate_id")
    if not candidate_id:
        return {}
    try:
        value = read_candidate(project, str(candidate_id))
    except VersionError:
        return {}
    return value if isinstance(value, dict) else {}


def _digest_or_empty(data: bytes) -> str:
    try:
        return body_digest(_decode(data))
    except (UnicodeDecodeError, ValueError):
        return body_digest("")


def _mark_recovery_failure(path: Path, record: Dict[str, Any], exc: BaseException,
                           state: str, reason: str) -> None:
    record["state"] = state
    record["conflict_reason"] = reason
    record["recovery_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    record["updated_at"] = _now()
    try:
        atomic_json(path, record)
    except Exception:
        pass


def _is_lock_busy(exc: BaseException) -> bool:
    return (isinstance(exc, BlockingIOError)
            or exc.__class__.__name__ == "PublicationBlocked"
            or "resource_busy" in str(exc))


def recover_pending(project) -> List[Dict[str, Any]]:
    """补齐被中断的提交；逐条隔离，无法判定的标记终态并保留现场。

    ``conflict``/``abandoned`` 是终态，绝不在下一次恢复时重新评估——否则
    作者明确回退或删除的正文会被旧候选静默覆盖 (A-P1-3)。``committed``
    的正文不再重写，但若标题改名/回执同步尚未完成，会做一次幂等对账
    (A-R-03/A-R-06)。
    """
    paths = _ensure(project)
    results: List[Dict[str, Any]] = []
    for path in sorted(paths["commits"].glob("*.json")):
        try:
            record = read_json_strict(path)
        except Exception as exc:  # noqa: BLE001 - one corrupt record must not stop the rest
            results.append({"op_id": path.stem, "chapter_id": 0,
                            "state": "recovery_error", "error": str(exc)[:200]})
            continue
        if not isinstance(record, dict):
            continue
        state = str(record.get("state") or "")
        if state == "committed":
            # A crash between the body/index commit and the filename/receipt
            # update leaves a real committed version with a stale filename.
            # Finish only that metadata work; never replay the body.
            if record.get("title_pending") or record.get("title_rename_done") is False:
                try:
                    chapter = int(record.get("chapter_id") or 0)
                except (TypeError, ValueError):
                    chapter = 0
                if chapter <= 0:
                    continue
                try:
                    current_entry = load_index(project)["chapters"].get(str(chapter)) or {}
                except Exception:  # noqa: BLE001 - corrupt index must not stop recovery
                    current_entry = {}
                if (record.get("content_sha256") and current_entry.get("current")
                        and current_entry.get("current") != record.get("content_sha256")):
                    # Superseded commit: its title belongs to an old version.
                    continue
                op = str(record.get("op_id") or path.stem)
                try:
                    with file_lock(paths["lock"]):
                        outcome = reconcile_title(project, chapter, op_id=op, record=record)
                    if outcome.get("renamed") or outcome.get("status") == "partial":
                        results.append({"op_id": op, "chapter_id": chapter, "state": "committed",
                                        "title": outcome.get("status"),
                                        "renamed": bool(outcome.get("renamed")),
                                        "title_conflict": bool(outcome.get("title_conflict"))})
                except Exception as exc:  # noqa: BLE001 - keep every record isolated
                    if _is_lock_busy(exc):
                        results.append({"op_id": op, "chapter_id": chapter,
                                        "state": "deferred", "reason": "lock_busy"})
                    else:
                        results.append({"op_id": op, "chapter_id": chapter, "state": "committed",
                                        "title": "error", "error": str(exc)[:200]})
            continue
        if state in {"conflict", "abandoned"}:
            continue
        try:
            chapter = int(record.get("chapter_id") or 0)
        except (TypeError, ValueError):
            results.append({"op_id": record.get("op_id") or path.stem, "chapter_id": 0,
                            "state": "recovery_error", "error": "chapter_id_invalid"})
            continue
        sha = str(record.get("content_sha256") or "")
        if not sha or chapter <= 0:
            continue
        try:
            with file_lock(paths["lock"]):
                current_path = chapter_path(project, chapter)
                current_sha = file_sha256(current_path)
                try:
                    data = _material_for_commit(project, record, current_sha)
                except VersionNotFound:
                    record["conflict_current"] = current_sha
                    _mark_recovery_failure(path, record, VersionNotFound("source_missing"),
                                           "conflict", "source_missing")
                    results.append({"op_id": record.get("op_id"), "chapter_id": chapter,
                                    "state": "conflict", "reason": "source_missing"})
                    continue
                index = load_index(project)
                entry = _chapter_entry(index, chapter)
                digest = _digest_or_empty(data)
                candidate = _candidate_meta(project, record)
                if entry.get("current") == sha:
                    record.setdefault("done", []).append("index")
                    record["state"] = "committed"
                    record["version_id"] = entry.get("current_version_id")
                elif current_sha == sha:
                    # 正文已写、索引未写：向前补索引，不能把现场判成冲突。
                    entry.setdefault("versions", [])
                    meta = next((v for v in entry["versions"]
                                 if v.get("op_id") == record.get("op_id")), None)
                    if meta is None:
                        meta = _register_version(entry, sha256=sha, digest=digest,
                                                 size=len(data), source=candidate.get("source", "recovered"),
                                                 op_id=record.get("op_id"), run_id=candidate.get("run_id"),
                                                 attempt_id=candidate.get("attempt_id"),
                                                 parent=record.get("previous_sha256"),
                                                 title=record.get("title") or _chapter_title(project, chapter),
                                                 note="recovered after interrupted commit")
                    record["version_id"] = meta.get("version_id")
                    entry["current"] = sha
                    entry["current_version_id"] = record["version_id"] or entry.get("current_version_id")
                    _save_index(project, index)
                    record.setdefault("done", []).append("index")
                    record["state"] = "committed"
                elif current_sha in (record.get("previous_sha256"), None):
                    done = record.get("done") if isinstance(record.get("done"), list) else []
                    previous_sha = record.get("previous_sha256")
                    # Only a commit whose body was never written may move
                    # forward.  If the body was written and the author has
                    # since restored the previous version, or deleted the
                    # chapter, replaying the candidate would silently undo the
                    # author's action (A-R-01/A-R-02).
                    if current_sha == previous_sha and "chapter" in done:
                        record["state"] = "conflict"
                        record["conflict_current"] = current_sha
                        record["conflict_reason"] = "author_reverted"
                        record["updated_at"] = _now()
                        atomic_json(path, record)
                        results.append({"op_id": record.get("op_id"), "chapter_id": chapter,
                                        "state": "conflict", "reason": "author_reverted"})
                        continue
                    if current_sha is None and not (previous_sha is None and "chapter" not in done):
                        record["state"] = "conflict"
                        record["conflict_current"] = current_sha
                        record["conflict_reason"] = "author_deleted"
                        record["updated_at"] = _now()
                        atomic_json(path, record)
                        results.append({"op_id": record.get("op_id"), "chapter_id": chapter,
                                        "state": "conflict", "reason": "author_deleted"})
                        continue
                    _write_chapter_bytes(project, chapter, data,
                                         record.get("title") or _chapter_title(project, chapter))
                    entry.setdefault("versions", [])
                    if not any(v.get("op_id") == record.get("op_id") for v in entry["versions"]):
                        meta = _register_version(entry, sha256=sha, digest=digest,
                                                 size=len(data), source=candidate.get("source", "recovered"),
                                                 op_id=record.get("op_id"), run_id=candidate.get("run_id"),
                                                 attempt_id=candidate.get("attempt_id"),
                                                 parent=record.get("previous_sha256"),
                                                 title=record.get("title") or _chapter_title(project, chapter),
                                                 note="recovered after interrupted commit")
                        record["version_id"] = meta.get("version_id")
                    entry["current"] = sha
                    entry["current_version_id"] = record.get("version_id") or entry.get("current_version_id")
                    _save_index(project, index)
                    record["state"] = "committed"
                else:
                    record["state"] = "conflict"
                    record["conflict_current"] = current_sha
                record["updated_at"] = _now()
                atomic_json(path, record)
                if record.get("state") == "committed":
                    # The body/index are committed; finish the title rename and
                    # receipt sync while we still hold the store lock.
                    reconcile_title(project, chapter,
                                    op_id=str(record.get("op_id") or ""),
                                    record=record)
                results.append({"op_id": record.get("op_id"), "chapter_id": chapter,
                                "state": record["state"]})
        except OSError as exc:
            if _is_lock_busy(exc):
                results.append({"op_id": record.get("op_id"), "chapter_id": chapter,
                                "state": "deferred", "reason": "lock_busy"})
                continue
            # 文件名过长 / 磁盘错误：单条记录标 conflict，后续记录继续恢复。
            _mark_recovery_failure(path, record, exc, "conflict",
                                   f"recovery_failed:{type(exc).__name__}")
            results.append({"op_id": record.get("op_id"), "chapter_id": chapter,
                            "state": "conflict", "reason": f"recovery_failed:{type(exc).__name__}"})
        except Exception as exc:  # noqa: BLE001 - isolate every commit record
            if _is_lock_busy(exc):
                # A concurrent writer owns the store lock: defer this record;
                # never rewrite an in-flight commit as recovery_error (A-P3-07).
                results.append({"op_id": record.get("op_id"), "chapter_id": chapter,
                                "state": "deferred", "reason": "lock_busy"})
                continue
            _mark_recovery_failure(path, record, exc, "recovery_error",
                                   f"recovery_failed:{type(exc).__name__}")
            results.append({"op_id": record.get("op_id"), "chapter_id": chapter,
                            "state": "recovery_error", "error": str(exc)[:200]})
    return results


def resolve_conflict(project, op_id: str, action: str) -> Dict[str, Any]:
    """Resolve one terminal ``conflict`` commit under explicit author control.

    ``replay`` re-applies the candidate/object bytes (only when the author
    explicitly asks); ``discard`` marks the record abandoned and leaves the
    current body untouched.  Recovery never performs either action on its own.
    """
    op = _require_id(op_id)
    paths = _ensure(project)
    resolution = str(action or "").strip().lower()
    if resolution not in {"replay", "discard"}:
        raise VersionConflict("invalid_conflict_action")
    with file_lock(paths["lock"]):
        record = _load_commit(project, op)
        if record is None:
            raise VersionNotFound("commit_missing")
        if record.get("state") != "conflict":
            raise VersionConflict("not_in_conflict")
        chapter = int(record.get("chapter_id") or 0)
        sha = str(record.get("content_sha256") or "")
        if resolution == "discard":
            record["state"] = "abandoned"
            record["resolution"] = "author_discard"
            record["resolved_at"] = _now()
            record["updated_at"] = record["resolved_at"]
            atomic_json(_commit_path(project, op), record)
            return {"status": "discarded", "op_id": op, "chapter_id": chapter,
                    "state": "abandoned"}
        if not sha or chapter <= 0:
            raise VersionConflict("source_missing")
        current_path = chapter_path(project, chapter)
        current_sha = file_sha256(current_path)
        try:
            data = _material_for_commit(project, record, current_sha)
        except VersionNotFound as exc:
            raise VersionConflict("source_missing") from exc
        index = load_index(project)
        entry = _chapter_entry(index, chapter)
        title = record.get("title") or _chapter_title(project, chapter)
        _write_chapter_bytes(project, chapter, data, title)
        meta = next((v for v in entry.get("versions", [])
                     if v.get("op_id") == record.get("op_id")), None)
        if meta is None:
            meta = _register_version(entry, sha256=sha, digest=_digest_or_empty(data),
                                     size=len(data), source="recovered",
                                     op_id=record.get("op_id"), run_id=None, attempt_id=None,
                                     parent=current_sha, title=title,
                                     note="author replayed conflict")
        entry["current"] = sha
        entry["current_version_id"] = meta.get("version_id")
        _save_index(project, index)
        record["version_id"] = meta.get("version_id")
        record["state"] = "committed"
        record["resolution"] = "author_replay"
        record["resolved_at"] = _now()
        record["updated_at"] = record["resolved_at"]
        atomic_json(_commit_path(project, op), record)
        return {"status": "replayed", "op_id": op, "chapter_id": chapter,
                "state": "committed", "version_id": meta.get("version_id"),
                "sha256": sha}


def discard_commit(project, op_id: str) -> bool:
    """Remove a commit marker created by a rolled-back composite operation.

    Used by split/merge rollback so an identical retry is not permanently
    rejected with ``operation_incomplete`` (A-P2-5).
    """
    op = _require_id(op_id)
    paths = _ensure(project)
    with file_lock(paths["lock"]):
        path = _commit_path(project, op)
        existed = path.is_file()
        path.unlink(missing_ok=True)
        return existed


# ----------------------------------------------------------------------- 读取

def list_versions(project, chapter: int) -> List[Dict[str, Any]]:
    entry = load_index(project)["chapters"].get(str(int(chapter))) or {}
    versions = entry.get("versions") if isinstance(entry, dict) else None
    return list(versions or [])


def current_version(project, chapter: int) -> Optional[Dict[str, Any]]:
    entry = load_index(project)["chapters"].get(str(int(chapter))) or {}
    current = entry.get("current") if isinstance(entry, dict) else None
    current_uid = entry.get("current_version_id") if isinstance(entry, dict) else None
    versions = entry.get("versions", []) if isinstance(entry, dict) else []
    if current_uid:
        for meta in versions:
            if meta.get("version_id") == current_uid:
                return meta
    for meta in versions:
        if meta.get("sha256") == current:
            return meta
    return None


def read_version(project, chapter: int, version_id: Optional[str] = None) -> Dict[str, Any]:
    """按版本读取正文。默认读索引里的当前版本；不存在则回退到磁盘当前稿。"""
    meta: Optional[Dict[str, Any]] = None
    if version_id is None:
        meta = current_version(project, chapter)
        if meta is None:
            path = chapter_path(project, chapter)
            if path is None:
                raise VersionNotFound("chapter_missing")
            data = path.read_bytes()
            return {"text": _decode(data), "meta": None, "path": str(path),
                    "sha256": raw_sha256(data), "source": "disk"}
        version_id = str(meta.get("sha256"))
    else:
        meta, version_id = _resolve_version(project, chapter, version_id)
    data = read_object(project, version_id)
    if meta is None:
        meta = next((m for m in list_versions(project, chapter) if m.get("sha256") == version_id), None)
    return {"text": _decode(data), "meta": meta, "path": str(_object_path(project, version_id)),
            "sha256": version_id, "version_id": (meta or {}).get("version_id"),
            "source": "object"}


def compare_current(project, chapter: int, expected_sha256: str) -> Dict[str, Any]:
    path = chapter_path(project, chapter)
    current = file_sha256(path)
    meta = current_version(project, chapter)
    return {"equal": current == expected_sha256, "current_sha256": current,
            "chapter_path": str(path) if path else None,
            "version_sha256": (meta or {}).get("sha256"),
            "version_id": (meta or {}).get("version_id"),
            "version_fingerprint": (meta or {}).get("version_fingerprint"),
            "body_digest": (meta or {}).get("body_digest"),
            "version_matches_disk": bool(meta) and meta.get("sha256") == current}


def find_by_body_digest(project, digest: str, chapter: Optional[int] = None) -> List[Dict[str, Any]]:
    """报告绑定用：按规范化正文哈希找版本（含未归属的旧原稿）。"""
    index = load_index(project)
    hits: List[Dict[str, Any]] = []
    chapters = [str(int(chapter))] if chapter is not None else list(index["chapters"])
    for key in chapters:
        for meta in (index["chapters"].get(key) or {}).get("versions", []):
            if meta.get("body_digest") == digest:
                hits.append({"chapter_id": int(key), **meta})
    for meta in index.get("unattributed", []):
        if meta.get("body_digest") == digest:
            hits.append({"chapter_id": None, **meta})
    return hits


def report_ref(project, chapter: int, version_id: Optional[str] = None) -> Dict[str, Any]:
    """给审查报告用的最小引用契约；报告正文变化即视为过期。"""
    if version_id is None:
        meta = current_version(project, chapter)
    else:
        meta, _sha = _resolve_version(project, chapter, version_id)
    path = chapter_path(project, chapter)
    disk = file_sha256(path)
    if meta is None:
        return {"chapter_id": int(chapter), "version_id": None, "version_uid": None,
                "sha256": disk, "body_digest": None, "path": str(path) if path else None,
                "stale": True, "reason": "no_version_record"}
    return {"chapter_id": int(chapter), "version_id": meta.get("sha256"),
            "version_uid": meta.get("version_id"), "sha256": meta.get("sha256"),
            "content_sha256": meta.get("content_sha256") or meta.get("sha256"),
            "version_fingerprint": meta.get("version_fingerprint"),
            "body_digest": meta.get("body_digest"), "path": str(path) if path else None,
            "stale": disk != meta.get("sha256"), "reason": None if disk == meta.get("sha256") else "chapter_changed"}


def snapshot(project, chapter: int, *, source: str = "backup", note: str = "") -> Optional[Dict[str, Any]]:
    """把当前磁盘正文登记为一个版本，不改变正文。

    恢复之前用它保底：作者在两次操作之间的手改不会因为恢复而消失。
    """
    paths = _ensure(project)
    path = chapter_path(project, chapter)
    if path is None:
        return None
    data = path.read_bytes()
    sha = raw_sha256(data)
    text = _decode(data)
    with file_lock(paths["lock"]):
        index = load_index(project)
        entry = _chapter_entry(index, chapter)
        for meta in reversed(entry.get("versions", [])):
            if meta.get("sha256") != sha:
                continue
            if entry.get("current") == sha and entry.get("current_version_id"):
                meta = next((item for item in entry.get("versions", [])
                             if item.get("version_id") == entry.get("current_version_id")), meta)
            entry["current"] = sha
            if meta.get("version_id"):
                entry["current_version_id"] = meta["version_id"]
            _save_index(project, index)
            return meta
        _store_object(project, data)
        meta = _register_version(entry, sha256=sha, digest=body_digest(text), size=len(data),
                                 source=source, op_id=None, run_id=None, attempt_id=None,
                                 parent=entry.get("current"), title=_chapter_title(project, chapter),
                                 note=note or "恢复前备份")
        entry["current"] = sha
        entry["current_version_id"] = meta["version_id"]
        _save_index(project, index)
    return meta


def _resolve_version(project, chapter: int, version_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Resolve either a ``ver_...`` identity or a legacy 64-hex content sha."""
    selector = str(version_id or "").strip()
    meta = next((m for m in list_versions(project, chapter)
                 if selector and (m.get("version_id") == selector or m.get("sha256") == selector)), None)
    if meta is not None:
        return meta, str(meta.get("sha256") or selector)
    raise VersionNotFound("version_not_found")


def commit_raw_bytes(project, chapter: int, data: bytes, *, title: Optional[str] = None,
                     op_id: Optional[str] = None, expected_sha256: Optional[str] = None,
                     source: str = "restored", note: str = "",
                     allow_new: bool = False, expect_absent: bool = False,
                     action: str = "chapter_save",
                     invalidation_reason: Optional[str] = "chapter_edited") -> Dict[str, Any]:
    """Byte-exact commit used for legacy restore (keeps BOM and CRLF intact).

    Unlike :func:`write_chapter` the payload is never decoded/re-encoded, so the
    SHA-256 of the restored file equals the archived object byte for byte.
    """
    if chapter <= 0:
        raise VersionConflict("chapter_invalid")
    paths = _ensure(project)
    data = bytes(data)
    sha = raw_sha256(data)
    op = op_id or uuid.uuid4().hex
    with file_lock(paths["lock"]):
        existing = _load_commit(project, op)
        if existing is not None and existing.get("state") == "abandoned":
            _commit_path(project, op).unlink(missing_ok=True)
            existing = None
        if existing is not None:
            if str(existing.get("action") or "chapter_save") != str(action or "chapter_save"):
                raise VersionConflict("operation_id_action_conflict")
            if existing.get("chapter_id") == int(chapter) and existing.get("content_sha256") == sha:
                index = load_index(project)
                entry = _chapter_entry(index, chapter)
                if (existing.get("state") == "committed"
                        and file_sha256(chapter_path(project, chapter)) == sha
                        and entry.get("current") == sha):
                    return existing
                raise VersionConflict("operation_incomplete")
            raise VersionConflict("operation_id_reused")
        current_path = chapter_path(project, chapter)
        current_sha = file_sha256(current_path)
        if current_sha is None and not allow_new:
            raise VersionNotFound("chapter_missing")
        if expect_absent and current_sha is not None:
            raise VersionConflict("chapter_exists")
        if expected_sha256 is not None and expected_sha256 != current_sha:
            raise VersionConflict("concurrent_modification")
        index = load_index(project)
        entry = _chapter_entry(index, chapter)
        final_title = title if title is not None else _chapter_title(project, chapter)
        title_before = _chapter_title(project, chapter, current_path) if current_path is not None else None
        title_pending = bool(current_path is not None
                             and normalize_title(final_title or "") != normalize_title(title_before or ""))
        if current_path is None:
            # Refuse an impossible filesystem name before leaving a prepared
            # commit record behind (A-P2-6).
            validate_chapter_filename(chapter, final_title or "", with_temporary=True)
        record = {
            "schema_version": SCHEMA_VERSION, "op_id": op, "project_id": project_id(project),
            "chapter_id": int(chapter), "candidate_id": None, "content_sha256": sha,
            "previous_sha256": current_sha, "state": "prepared", "done": [],
            "title": final_title, "title_before": title_before,
            "title_pending": title_pending, "title_rename_done": not title_pending,
            "index_reconciled": entry.get("current") not in (None, current_sha),
            "raw_bytes": True, "action": str(action or "chapter_save"),
            "created_at": _now(), "updated_at": _now(),
        }
        atomic_json(_commit_path(project, op), record)
        _store_object(project, data)
        record["done"].append("object")
        atomic_json(_commit_path(project, op), record)
        path = _write_chapter_bytes(project, chapter, data, final_title)
        record["chapter_path"] = str(path)
        record["done"].append("chapter")
        record["state"] = "chapter_written"
        atomic_json(_commit_path(project, op), record)
        meta = _register_version(entry, sha256=sha, digest=body_digest(_decode(data)), size=len(data),
                                 source=source, op_id=op, run_id=None, attempt_id=None,
                                 parent=current_sha, title=final_title, note=note)
        entry["current"] = sha
        entry["current_version_id"] = meta["version_id"]
        _save_index(project, index)
        record["done"].append("index")
        record["version"] = meta
        record["version_id"] = meta["version_id"]
        record["state"] = "committed"
        record["updated_at"] = _now()
        atomic_json(_commit_path(project, op), record)
    if invalidation_reason:
        try:
            from . import invalidation
            record["invalidation"] = invalidation.invalidate(
                project, chapters=[chapter], reason=invalidation_reason,
                source=f"versions:{source}:{sha[:12]}", op_id=str(op_id or op))
        except (ValueError, OSError, RuntimeError) as exc:
            record["invalidation"] = {"status": "skipped", "error": str(exc)[:200]}
    return record


def _sync_receipt_destination(project, chapter: int, destination: str) -> Dict[str, Any]:
    """Read-latest, change only ``destination``, write under ``receipts.lock``.

    Never rewrite the whole entry from a stale snapshot (A-P2-14) and never
    let a corrupt/locked receipts table escape as a 500 after the body has
    already been committed (A-R-03).
    """
    path = Path(project) / ".webnovel" / "writer_receipts.json"
    if not path.is_file():
        return {"status": "missing"}
    lock = path.parent / "receipts.lock"
    try:
        with file_lock(lock):
            try:
                receipts = read_json_strict(path)
            except (OSError, ValueError, RuntimeError) as exc:
                return {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
            if not isinstance(receipts, dict):
                return {"status": "failed", "error": "receipts_not_object"}
            entry = receipts.get(str(int(chapter)))
            if not isinstance(entry, dict):
                return {"status": "missing"}
            if entry.get("destination") == destination:
                return {"status": "unchanged"}
            entry["destination"] = destination
            try:
                atomic_json(path, receipts)
            except (OSError, RuntimeError) as exc:
                return {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
            return {"status": "updated"}
    except RuntimeError as exc:
        return {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


def _update_receipt_destination(project, chapter: int, destination: str) -> bool:
    """Keep ``writer_receipts.json`` pointing at the renamed chapter file."""
    return _sync_receipt_destination(project, chapter, destination).get("status") in {"updated", "unchanged"}


def _receipt_entry_present(project, chapter: int) -> bool:
    path = Path(project) / ".webnovel" / "writer_receipts.json"
    if not path.is_file():
        return False
    try:
        receipts = read_json_strict(path)
    except (OSError, ValueError, RuntimeError):
        return True
    return isinstance(receipts, dict) and isinstance(receipts.get(str(int(chapter))), dict)


def _update_commit_chapter_path(project, op_id: Optional[str], chapter_path_value: str) -> bool:
    if not op_id:
        return False
    paths = _paths(project)
    with file_lock(paths["lock"]):
        record = _load_commit(project, str(op_id))
        if record is None:
            return False
        record["chapter_path"] = chapter_path_value
        record["updated_at"] = _now()
        atomic_json(_commit_path(project, str(op_id)), record)
        return True


def _rename_no_replace(source: Path, target: Path) -> None:
    """Rename without silently overwriting a file that appeared meanwhile.

    ``os.replace`` overwrites an external file created between the existence
    check and the rename (A-P3-10).  A hard link is atomic and fails with
    ``FileExistsError`` instead; Windows sharing violations are retried like
    ``transaction_journal.rename_with_retry``.  On filesystems without hard
    links we fall back to a re-checked ``os.replace``.
    """
    last_error: Optional[BaseException] = None
    for attempt in range(6):
        try:
            os.link(source, target)
            break
        except FileExistsError:
            raise
        except OSError as exc:
            retryable = (isinstance(exc, PermissionError)
                         or getattr(exc, "winerror", None) in (5, 32, 33))
            if retryable:
                last_error = exc
                if attempt + 1 >= 6:
                    raise
                time.sleep(0.05 * (2 ** attempt))
                continue
            unsupported = {errno.EPERM, errno.EACCES, errno.EXDEV, errno.ENOSYS,
                           errno.EOPNOTSUPP if hasattr(errno, "EOPNOTSUPP") else errno.EPERM,
                           errno.ENOTSUP if hasattr(errno, "ENOTSUP") else errno.EPERM}
            if getattr(exc, "errno", None) not in unsupported:
                raise
            if target.exists():
                raise FileExistsError(str(target))
            os.replace(source, target)
            return
    else:  # pragma: no cover - the loop either breaks or raises
        raise last_error or OSError("rename_failed")
    try:
        os.unlink(source)
    except OSError:
        # Never leave two names for one chapter if the source unlink fails.
        try:
            os.unlink(target)
        finally:
            raise


def reconcile_title(project, chapter: int, *, title: Optional[str] = None,
                    op_id: Optional[str] = None,
                    record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Make filename, receipt and commit record agree, idempotently.

    The commit marker records ``title_pending`` when the body landed under a
    filename whose title differs from the version title.  Every retry and
    ``recover_pending`` can therefore finish the rename and receipt sync
    without guessing; a rename that loses a race returns a structured partial
    result instead of claiming success (A-R-03/A-R-06).
    """
    chapter = int(chapter)
    paths = _ensure(project)
    with file_lock(paths["lock"]):
        if op_id:
            fresh = _load_commit(project, str(op_id))
            if isinstance(fresh, dict):
                record = fresh
        try:
            path = chapter_path(project, chapter)
        except VersionConflict as exc:
            # Two files for one chapter number: do not guess, and do not let
            # the reconciliation crash after the body has been committed.
            return {"chapter_id": chapter, "status": "partial", "renamed": False,
                    "title_renamed": False, "title_conflict": True,
                    "error": str(exc)[:160]}
        if path is None:
            return {"chapter_id": chapter, "status": "chapter_missing",
                    "renamed": False, "title_renamed": False}
        if isinstance(record, dict) and record.get("content_sha256"):
            index_entry = load_index(project)["chapters"].get(str(chapter)) or {}
            current = index_entry.get("current")
            if current and current != record.get("content_sha256"):
                # An older commit must never rename the file that a newer
                # version now owns.
                return {"chapter_id": chapter, "status": "stale",
                        "renamed": False, "title_renamed": False}
        actual_title = _chapter_title(project, chapter, path)
        desired = title
        if desired is None and isinstance(record, dict):
            desired = record.get("title")
        if desired is None:
            desired = actual_title
        desired = str(desired or "")
        outcome: Dict[str, Any] = {
            "chapter_id": chapter, "status": "ok", "renamed": False,
            "title_renamed": normalize_title(actual_title) == normalize_title(desired),
            "actual_title": actual_title, "desired_title": desired,
        }
        if not outcome["title_renamed"]:
            try:
                validate_chapter_filename(chapter, desired, with_temporary=True)
                target = path.with_name(f"第{chapter}章" + (f"-{desired}" if desired else "") + ".md")
                if target.resolve() != path.resolve():
                    if target.exists():
                        raise FileExistsError(str(target))
                    if replace_with_retry is not _ORIGINAL_REPLACE:
                        # A caller-supplied/fault-injected replace strategy
                        # stays authoritative for this atomic move.
                        replace_with_retry(path, target)
                    else:
                        _rename_no_replace(path, target)
                    path = target
                    outcome["renamed"] = True
                    outcome["title_renamed"] = True
            except (OSError, ValueError, RuntimeError) as exc:
                outcome.update(status="partial", title_conflict=True,
                               error=f"{type(exc).__name__}: {str(exc)[:160]}")
                if isinstance(exc, FileExistsError):
                    outcome["conflict_path"] = str(getattr(exc, "filename", "") or target)
                    outcome["message"] = "目标文件名已被占用；请删除该文件后重试，或改用其他标题"
        receipt_present = _receipt_entry_present(project, chapter)
        try:
            receipt_synced_now = _update_receipt_destination(project, chapter, str(path.resolve()))
            receipt = {"status": "synced" if receipt_synced_now
                       else ("missing" if not receipt_present else "failed")}
        except Exception as exc:  # noqa: BLE001 - body is committed; report partial
            receipt_synced_now = False
            receipt = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        outcome["receipt_status"] = receipt.get("status")
        outcome["receipt_synced"] = bool(receipt_synced_now) or receipt.get("status") == "missing"
        if receipt.get("status") == "failed":
            outcome["status"] = "partial"
            outcome["receipt_error"] = receipt.get("error")
        if isinstance(record, dict) and record.get("op_id"):
            changed = {
                "chapter_path": str(path),
                "title_rename_done": bool(outcome["title_renamed"]),
                "title_pending": not (outcome["title_renamed"] and outcome["receipt_synced"]),
                "receipt_synced": bool(outcome["receipt_synced"]),
            }
            if any(record.get(key) != value for key, value in changed.items()):
                record.update(changed)
                record["updated_at"] = _now()
                try:
                    atomic_json(_commit_path(project, str(record["op_id"])), record)
                except (OSError, RuntimeError) as exc:
                    outcome["status"] = "partial"
                    outcome["record_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return outcome


def restore_version(project, chapter: int, version_id: str, *, op_id: Optional[str] = None,
                    note: str = "", restore_title: bool = True) -> Dict[str, Any]:
    """Restore a historical version byte-exactly (BOM/CRLF preserved).

    ``version_id`` accepts both the new ``ver_...`` identity and a legacy
    64-hex content sha.  When ``restore_title`` is false the current on-disk
    title is kept and only the body bytes are restored.

    The target filename is checked *before* the body commit so a title
    collision cannot report failure after silently changing the body
    (A-P2-2); a race that still loses the rename returns a structured
    partial result instead of a misleading 409.
    """
    meta, sha = _resolve_version(project, chapter, version_id)
    if not sha:
        raise VersionNotFound("version_not_found")
    data = read_object(project, sha)
    path = chapter_path(project, chapter)
    current_title = _chapter_title(project, chapter, path)
    title = None
    if restore_title and meta and meta.get("title") is not None:
        title = str(meta.get("title") or "")
    elif not restore_title:
        title = current_title
    target: Optional[Path] = None
    needs_rename = False
    if path is not None and restore_title and title is not None:
        validate_chapter_filename(chapter, title, with_temporary=True)
        target = path.with_name(f"第{int(chapter)}章" + (f"-{title}" if title else "") + ".md")
        needs_rename = target.resolve() != path.resolve()
        if needs_rename and target.exists():
            raise VersionConflict("restore_title_conflict")
    elif path is None and title is not None:
        validate_chapter_filename(chapter, title, with_temporary=True)
    result = commit_raw_bytes(project, chapter, data, title=title, op_id=op_id,
                              expected_sha256=file_sha256(path),
                              source="restored", note=note or f"restore {sha[:12]}",
                              allow_new=path is None, action="version_restore",
                              invalidation_reason="version_restored")
    # The body commit deliberately does not rename: finish the title/receipt/
    # commit-path state through one idempotent reconciliation, so a retry with
    # the same op_id repairs an earlier partial write instead of reporting a
    # bare success (A-R-03/A-R-06).
    outcome = reconcile_title(project, chapter, title=title, op_id=result.get("op_id"))
    result["title_renamed"] = bool(outcome.get("title_renamed"))
    result["renamed"] = bool(outcome.get("renamed"))
    result["receipt_synced"] = bool(outcome.get("receipt_synced"))
    if outcome.get("status") == "partial":
        result["status"] = "partial"
        result["title_conflict"] = bool(outcome.get("title_conflict"))
        if outcome.get("error"):
            result["title_error"] = outcome["error"]
        if outcome.get("receipt_error"):
            result["receipt_error"] = outcome["receipt_error"]
    else:
        result["status"] = "restored"
    result["restored_version_id"] = (meta or {}).get("version_id") or sha
    return result


def prune_adopted(project, chapter: Optional[int] = None) -> Dict[str, Any]:
    """只回滚本模块登记过的兼容条目（不动用户正文和真实提交）。"""
    paths = _ensure(project)
    with file_lock(paths["lock"]):
        index = load_index(project)
        dropped: List[Dict[str, Any]] = []
        keys = [str(int(chapter))] if chapter is not None else list(index["chapters"])
        for key in keys:
            entry = index["chapters"].get(key)
            if not isinstance(entry, dict):
                continue
            keep = []
            for meta in entry.get("versions", []):
                if meta.get("source") in ("legacy-adopted", "originals-legacy") and not meta.get("op_id"):
                    dropped.append(meta)
                else:
                    keep.append(meta)
            if len(keep) == len(entry.get("versions", [])):
                continue
            entry["versions"] = keep
            entry["current"] = keep[-1]["sha256"] if keep else None
            entry["current_version_id"] = keep[-1].get("version_id") if keep else None
            if not keep:
                index["chapters"].pop(key, None)
        if chapter is None:
            unattributed = [m for m in index.get("unattributed", []) if m.get("source") != "originals-legacy"]
            dropped += [m for m in index.get("unattributed", []) if m.get("source") == "originals-legacy"]
            index["unattributed"] = unattributed
        _save_index(project, index)
        referenced = {v.get("sha256") for e in index["chapters"].values() for v in e.get("versions", [])}
        referenced |= {m.get("sha256") for m in index.get("unattributed", [])}
        for meta in dropped:
            sha = meta.get("sha256")
            if sha and sha not in referenced:
                _object_path(project, sha).unlink(missing_ok=True)
        return {"removed": len(dropped), "versions": dropped}


# ------------------------------------------------------------------------- 兼容

def adopt_legacy(project, chapter: Optional[int] = None) -> List[Dict[str, Any]]:
    """把磁盘上的现有正文登记为版本（只读，不修改 .md）。幂等。"""
    index = load_index(project)
    mapping = chapter_map(project)
    chapters: Iterable[int]
    if chapter is not None:
        chapters = [int(chapter)]
    else:
        chapters = sorted(mapping)
    added: List[Dict[str, Any]] = []
    for number in chapters:
        path = mapping.get(int(number))
        if path is None:
            continue
        data = path.read_bytes()
        sha = raw_sha256(data)
        entry = _chapter_entry(index, number)
        if any(v.get("sha256") == sha for v in entry["versions"]):
            if entry.get("current") is None:
                entry["current"] = sha
                existing = next((v for v in entry["versions"] if v.get("sha256") == sha), None)
                entry["current_version_id"] = (existing or {}).get("version_id")
            continue
        _store_object(project, data)
        meta = _register_version(entry, sha256=sha, digest=body_digest(_decode(data)), size=len(data),
                                 source="legacy-adopted", op_id=None, run_id=None, attempt_id=None,
                                 parent=entry.get("current"),
                                 title=_chapter_title(project, number, path),
                                 note="adopted from 正文 without changing the file")
        entry["current"] = sha
        entry["current_version_id"] = meta["version_id"]
        added.append(meta)
    if added:
        _save_index(project, index)
    return added


def adopt_originals(project) -> List[Dict[str, Any]]:
    """引用既有 ``.webnovel/originals/*.md`` 不可变原稿（按哈希去重，不猜章号）。"""
    folder = Path(project) / ".webnovel" / "originals"
    index = load_index(project)
    known = {v.get("sha256") for entry in index["chapters"].values() for v in entry.get("versions", [])}
    known |= {v.get("sha256") for v in index.get("unattributed", [])}
    added: List[Dict[str, Any]] = []
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        data = path.read_bytes()
        sha = raw_sha256(data)
        if sha in known:
            continue
        _store_object(project, data)
        meta = {"seq": None, "sha256": sha, "body_digest": body_digest(_decode(data)), "bytes": len(data),
                "source": "originals-legacy", "op_id": None, "run_id": None, "attempt_id": None,
                "parent": None, "title": "", "note": f"original:{path.name}", "created_at": _now()}
        index["unattributed"].append(meta)
        known.add(sha)
        added.append(meta)
    if added:
        _save_index(project, index)
    return added


def link_review_attempts(project, chapter: int) -> List[Dict[str, Any]]:
    """把既有 review_attempts 与版本按规范化哈希关联（只读，不迁移）。"""
    folder = Path(project) / ".webnovel" / "review_attempts"
    versions = {m.get("body_digest"): m for m in list_versions(project, chapter)}
    linked: List[Dict[str, Any]] = []
    for path in sorted(folder.glob(f"{int(chapter):04d}-*.json")) if folder.is_dir() else []:
        try:
            record = read_json_strict(path)
        except (OSError, ValueError, RuntimeError):
            continue
        digest = record.get("body_sha256") if isinstance(record, dict) else None
        meta = versions.get(digest)
        if meta is None:
            continue
        linked.append({"attempt": path.name, "version_id": meta["sha256"],
                       "current": meta["sha256"] == (current_version(project, chapter) or {}).get("sha256")})
    return linked
