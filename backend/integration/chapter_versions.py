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

import hashlib
import os
import re
import sys
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
_WINDOWS_BAD = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_CHAPTER_PATTERNS = (
    re.compile(r"第\s*0*(\d+)\s*章(?:[：:\-＿_\s]*(.*))?$"),
    re.compile(r"^\s*0*(\d+)(?:[：:\-＿_\s]*(.*))?$"),
)


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


def store_root(project) -> Path:
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


def _new_chapter_path(project, chapter: int, title: str) -> Path:
    safe = unicodedata.normalize("NFC", title or "").strip()
    if safe and (_WINDOWS_BAD.search(safe) or safe.endswith((" ", "."))):
        raise VersionConflict("invalid_chapter_title")
    name = f"第{int(chapter)}章" + (f"-{safe}" if safe else "") + ".md"
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
    path = _object_path(project, sha)
    if not path.is_file():
        raise VersionNotFound("object_missing")
    data = path.read_bytes()
    if raw_sha256(data) != sha:
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
    candidate_id = op_id or uuid.uuid4().hex
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
    path = _paths(project)["candidates"] / f"{candidate_id}.json"
    if not path.is_file():
        raise VersionNotFound("candidate_missing")
    record = read_json_strict(path)
    if not isinstance(record, dict):
        raise VersionCorrupt("candidate_not_object")
    return record


# ------------------------------------------------------------------- 提交与恢复

def _commit_path(project, op_id: str) -> Path:
    return _paths(project)["commits"] / f"{op_id}.json"


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
                     title: Optional[str] = None, allow_new: bool = False) -> Dict[str, Any]:
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
        if existing is not None:
            if existing.get("chapter_id") == int(chapter) and existing.get("content_sha256") == sha:
                return existing  # 幂等：同一操作不重复加版本
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

        record = {
            "schema_version": SCHEMA_VERSION, "op_id": op, "project_id": project_id(project),
            "chapter_id": int(chapter), "candidate_id": candidate_id, "content_sha256": sha,
            "previous_sha256": current_sha, "state": "prepared", "done": [],
            "title": title if title is not None else (candidate.get("title") or _chapter_title(project, chapter)),
            "index_reconciled": index_reconciled,
            "created_at": _now(), "updated_at": _now(),
        }
        atomic_json(_commit_path(project, op), record)
        _store_object(project, data)
        record["done"].append("object")
        atomic_json(_commit_path(project, op), record)

        final_title = title if title is not None else (candidate.get("title") or _chapter_title(project, chapter))
        path = _write_chapter_bytes(project, chapter, data, final_title)
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
                  allow_new: bool = False) -> Dict[str, Any]:
    """保存候选 + 提交，一步完成（供写作/修订路径调用）。"""
    document = save_candidate(project, chapter, content, source=source,
                              base_sha256=expected_sha256, run_id=run_id,
                              attempt_id=attempt_id, note=note, title=title,
                              op_id=op_id)
    result = commit_candidate(project, chapter, document["candidate_id"], op_id=op_id,
                              expected_sha256=expected_sha256, title=title, allow_new=allow_new)
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


def recover_pending(project) -> List[Dict[str, Any]]:
    """补齐被中断的提交；无法判定的标记 conflict 并保留现场。"""
    paths = _ensure(project)
    results: List[Dict[str, Any]] = []
    for path in sorted(paths["commits"].glob("*.json")):
        record = read_json_strict(path)
        if not isinstance(record, dict) or record.get("state") == "committed":
            continue
        chapter = int(record.get("chapter_id", 0))
        sha = record.get("content_sha256")
        if not sha:
            continue
        with file_lock(paths["lock"]):
            candidate = read_candidate(project, record["candidate_id"]) if record.get("candidate_id") else {}
            try:
                data = read_object(project, sha)
            except VersionError:
                _store_object(project, _encode(candidate["content"]))
                data = read_object(project, sha)
            current_path = chapter_path(project, chapter)
            current_sha = file_sha256(current_path)
            index = load_index(project)
            entry = _chapter_entry(index, chapter)
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
                    meta = _register_version(entry, sha256=sha, digest=body_digest(_decode(data)),
                                             size=len(data), source=candidate.get("source", "recovered"),
                                             op_id=record.get("op_id"), run_id=None, attempt_id=None,
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
                _write_chapter_bytes(project, chapter, data, record.get("title") or _chapter_title(project, chapter))
                entry.setdefault("versions", [])
                if not any(v.get("op_id") == record.get("op_id") for v in entry["versions"]):
                    meta = _register_version(entry, sha256=sha, digest=body_digest(_decode(data)),
                                      size=len(data), source=candidate.get("source", "recovered"), op_id=record.get("op_id"),
                                      run_id=None, attempt_id=None, parent=record.get("previous_sha256"),
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
            results.append({"op_id": record.get("op_id"), "chapter_id": chapter, "state": record["state"]})
    return results


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
        for meta in entry.get("versions", []):
            if meta.get("sha256") == sha:
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
    if re.fullmatch(r"[0-9a-f]{64}", selector):
        return None, selector
    raise VersionNotFound("version_not_found")


def commit_raw_bytes(project, chapter: int, data: bytes, *, title: Optional[str] = None,
                     op_id: Optional[str] = None, expected_sha256: Optional[str] = None,
                     source: str = "restored", note: str = "",
                     allow_new: bool = False,
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
        if existing is not None:
            if existing.get("chapter_id") == int(chapter) and existing.get("content_sha256") == sha:
                return existing
            raise VersionConflict("operation_id_reused")
        current_path = chapter_path(project, chapter)
        current_sha = file_sha256(current_path)
        if current_sha is None and not allow_new:
            raise VersionNotFound("chapter_missing")
        if expected_sha256 is not None and expected_sha256 != current_sha:
            raise VersionConflict("concurrent_modification")
        index = load_index(project)
        entry = _chapter_entry(index, chapter)
        final_title = title if title is not None else _chapter_title(project, chapter)
        record = {
            "schema_version": SCHEMA_VERSION, "op_id": op, "project_id": project_id(project),
            "chapter_id": int(chapter), "candidate_id": None, "content_sha256": sha,
            "previous_sha256": current_sha, "state": "prepared", "done": [],
            "title": final_title, "index_reconciled": entry.get("current") not in (None, current_sha),
            "raw_bytes": True, "created_at": _now(), "updated_at": _now(),
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


def restore_version(project, chapter: int, version_id: str, *, op_id: Optional[str] = None,
                    note: str = "", restore_title: bool = True) -> Dict[str, Any]:
    """Restore a historical version byte-exactly (BOM/CRLF preserved).

    ``version_id`` accepts both the new ``ver_...`` identity and a legacy
    64-hex content sha.  When ``restore_title`` is false the current on-disk
    title is kept and only the body bytes are restored.
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
    result = commit_raw_bytes(project, chapter, data, title=title, op_id=op_id,
                              expected_sha256=file_sha256(path),
                              source="restored", note=note or f"restore {sha[:12]}",
                              allow_new=path is None,
                              invalidation_reason="version_restored")
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
