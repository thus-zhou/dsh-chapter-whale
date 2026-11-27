"""跨文件事务日志、一致性备份与安全降级导出（v0.8）。

本模块只依赖标准库，落地 ``docs/plans/v0.8-v0.9/05`` §3–§4：

* **事务日志**：``<project>/.webnovel/transactions/tx_{tx_id}.json`` 记录每一步
  的 ``from_path`` / ``to_path`` / ``sha256`` / ``size`` 与暂存文件名；恢复时
  **只信任该记录与暂存字节**，绝不反查 ``index.json``，也绝不按目录猜文件名。
* **崩溃安全**：正文写入一律「同目录临时文件 + fsync + 原子替换」，每一步真正
  完成后才推进 ``done``。进程在任意一步崩溃，``recover`` 都能从记录继续；
  无法判定时标记 ``conflict`` 并保留现场，绝不删除证据。
* **备份屏障**：``barrier`` 等待活动事务清零，``backup`` 用 SQLite Online
  Backup API 拷贝各库、原子复制文本，最后写带 SHA-256 的
  ``backup_manifest.json``。
* **安全恢复与降级导出**：拒绝 zip-slip、绝对路径、符号链接/重解析点与压缩
  炸弹；``export_legacy`` 只拷贝 v0.7.5 认识的纯文件，绝不携带
  ``workbench.sqlite3`` 或任何凭据。

事务步骤路径均为项目内相对 POSIX 字符串；绝对路径与 ``..`` 一律拒绝。
"""
from __future__ import annotations

import base64
import errno
import hashlib
import json
import os
import re
import sqlite3
import stat
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "RecoveryInProgress", "TransactionConflict", "BarrierTimeout", "FileInUse",
    "UnsafePath", "tx_root", "pending", "prepare", "apply", "recover",
    "assert_readable", "write_text", "write_bytes", "rename", "delete",
    "rename_with_retry", "validate_windows_name", "assert_within", "barrier",
    "backup", "inspect_backup", "restore_backup", "export_legacy",
    "write_publication_snapshot", "verify_publication_snapshot",
    "PUBLICATION_FIELDS",
]

SCHEMA_VERSION = 1
BACKUP_FORMAT = 1

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
"""Windows 重解析点（含 Junction）标志位。"""

_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_TX_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")

_MAX_FILE_BYTES = 512 * 1024 * 1024
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_MAX_RATIO = 200
_SMALL_FILE_BYTES = 1024 * 1024

_ACTIVE_STATES = ("prepared", "applying")
_CONFLICT_CODES = frozenset({
    "staged_missing", "staged_corrupt", "staged_size_mismatch",
    "source_missing", "source_changed", "source_not_file",
    "target_not_file", "target_changed", "target_exists",
    "delete_changed", "delete_appeared",
    "write_verify_failed", "rename_verify_failed",
    "unsafe_path", "tx_record_tampered",
})

PUBLICATION_FIELDS = (
    "platform", "account_id", "project_id", "chapter_uid", "chapter_number",
    "version_id", "content_sha256", "body_digest", "title", "title_digest",
    "contract_hash", "scheduled_at", "approval_id",
)

_DROP_RECEIPT_KEYS = ("version_id", "content_sha256", "title_digest",
                      "version_fingerprint", "author_confirmed")


# --------------------------------------------------------------------------- 异常


class RecoveryInProgress(RuntimeError):
    """存在未完成事务，关键读取者必须返回 409 或先触发恢复。"""

    def __init__(self, message: Optional[str] = None,
                 transactions: Optional[Sequence[Mapping[str, Any]]] = None):
        self.transactions = [dict(item) for item in (transactions or [])]
        self.count = len(self.transactions)
        super().__init__(message or f"recovery_in_progress: {self.count}")


class TransactionConflict(RuntimeError):
    """事务无法继续；``code`` 是稳定机器码，调用方据此返回 409 或降级。"""

    def __init__(self, code: str, detail: Optional[str] = None, *,
                 tx_id: Optional[str] = None, step: Optional[int] = None):
        self.code = str(code)
        self.detail = detail
        self.tx_id = tx_id
        self.step = step
        text = self.code if not detail else f"{self.code}: {detail}"
        super().__init__(text)


class BarrierTimeout(RuntimeError):
    """等待活动事务清零超时（默认 5 秒后向作者降级提示）。"""

    def __init__(self, message: Optional[str] = None,
                 pending: Optional[Sequence[Mapping[str, Any]]] = None):
        self.pending = [dict(item) for item in (pending or [])]
        super().__init__(message or f"barrier_timeout: {len(self.pending)}")


class FileInUse(RuntimeError):
    """重命名在 Windows 共享/杀软占用下重试耗尽；源文件从未被删除。"""

    def __init__(self, message: str, *, source: Optional[str] = None,
                 target: Optional[str] = None, attempts: int = 0,
                 last_error: Optional[BaseException] = None):
        self.source = source
        self.target = target
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(message)


class UnsafePath(ValueError):
    """路径越界、符号链接、Windows 设备名或压缩炸弹等安全拒绝。"""

    def __init__(self, code: str, detail: Optional[str] = None):
        self.code = str(code)
        self.detail = detail
        super().__init__(self.code if not detail else f"{self.code}: {detail}")


# --------------------------------------------------------------------------- 基础工具


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_bytes(data: Any) -> bytes:
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)
    return (text.replace("\r\n", "\n") + "\n").encode("utf-8")


def _fsync_dir(path: Path) -> None:
    """目录项也要落盘；Windows 上目录不可 fsync，直接跳过。"""
    if os.name == "nt":
        return
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _rename_retryable(exc: OSError) -> bool:
    if isinstance(exc, FileNotFoundError):
        return False
    if isinstance(exc, PermissionError):
        return True
    if getattr(exc, "winerror", None) in (5, 32, 33):
        return True
    return getattr(exc, "errno", None) in (errno.EBUSY, errno.EACCES, errno.EPERM)


def rename_with_retry(source, target, attempts: int = 6, base_delay: float = 0.05) -> Path:
    """带指数退避的原子改名（Windows ``WinError 5/32/33`` 与 EBUSY 等）。

    只在「源文件仍被其他进程/杀软占用」时重试，绝不通过删除目标或删除源来
    强行成功；重试耗尽抛 :class:`FileInUse`，源文件保持原样。
    """
    source_path = Path(source)
    target_path = Path(target)
    total = max(1, int(attempts))
    last_error: Optional[BaseException] = None
    for attempt in range(total):
        try:
            os.replace(source_path, target_path)
            return target_path
        except OSError as exc:
            last_error = exc
            if not _rename_retryable(exc):
                raise
            if attempt + 1 >= total:
                raise FileInUse(
                    f"rename_failed: {source_path} -> {target_path}: {exc}",
                    source=str(source_path), target=str(target_path),
                    attempts=attempt + 1, last_error=exc,
                ) from exc
            delay = float(base_delay) * (2 ** attempt)
            if delay > 0:
                time.sleep(delay)
    raise FileInUse(
        f"rename_failed: {source_path} -> {target_path}",
        source=str(source_path), target=str(target_path),
        attempts=total, last_error=last_error,
    )


def _atomic_write_bytes(path, data: bytes) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        rename_with_retry(temporary, path)
        _fsync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _create_bytes_exclusive(path, data: bytes) -> bool:
    """原子「不存在才创建」；返回 False 表示已存在（不覆盖）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        except (AttributeError, NotImplementedError, OSError) as exc:
            unsupported = {errno.EPERM, errno.EACCES, errno.EXDEV, errno.ENOSYS}
            for name in ("EOPNOTSUPP", "ENOTSUP"):
                code = getattr(errno, name, None)
                if code is not None:
                    unsupported.add(code)
            if isinstance(exc, OSError) and getattr(exc, "errno", None) not in unsupported:
                raise
            if path.exists():
                return False
            rename_with_retry(temporary, path)
        _fsync_dir(path.parent)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _file_sha(path) -> Optional[str]:
    """返回常规文件 sha256；不存在或不是文件返回 None，其余 OSError 照常抛出。"""
    target = Path(path)
    try:
        info = os.stat(target)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _link_reason(path) -> Optional[str]:
    """返回 ``symlink`` / ``reparse_point``；普通路径返回 None。"""
    target = Path(path)
    try:
        if target.is_symlink():
            return "symlink"
    except OSError:
        return "symlink"
    try:
        info = os.lstat(target)
    except OSError:
        return None
    if getattr(info, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
        return "reparse_point"
    return None


def _is_link_like(path) -> bool:
    """符号链接、Windows Junction 或其他重解析点。"""
    return _link_reason(path) is not None


def _join(root, relative: str) -> Path:
    return Path(root).joinpath(*PurePosixPath(relative).parts)


def _is_within(root, path) -> bool:
    try:
        Path(path).resolve(strict=False).relative_to(Path(root).resolve(strict=False))
        return True
    except (ValueError, OSError):
        return False


# --------------------------------------------------------------------------- Windows 路径安全


def validate_windows_name(name: str) -> str:
    """校验单个路径片段；不合法抛 :class:`UnsafePath`，合法原样返回。

    拦截控制字符、尾随空格/点、NTFS 备用数据流（``:``）以及
    ``CON/PRN/AUX/NUL/COM1-9/LPT1-9``（带不带扩展名都拦截）。
    """
    if not isinstance(name, str) or not name:
        raise UnsafePath("empty_name")
    if name in (".", ".."):
        raise UnsafePath("relative_name", name)
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise UnsafePath("control_char", repr(name))
    if name[-1] in (" ", "."):
        raise UnsafePath("trailing_space_or_dot", name)
    if ":" in name:
        raise UnsafePath("alternate_data_stream", name)
    stem = name.split(".", 1)[0].rstrip(" ")
    if stem.upper() in _RESERVED_NAMES:
        raise UnsafePath("reserved_name", name)
    return name


def _relative_path(value) -> str:
    """把调用方路径规范化为项目内相对 POSIX 字符串。"""
    if isinstance(value, PurePosixPath):
        text = value.as_posix()
    elif isinstance(value, os.PathLike):
        text = Path(value).as_posix()
    elif isinstance(value, str):
        text = value
    else:
        raise UnsafePath("path_not_string")
    text = text.replace("\\", "/")
    if text.startswith("/"):
        raise UnsafePath("absolute_path", text)
    if _DRIVE_PREFIX.match(text):
        raise UnsafePath("absolute_path", text)
    parts: List[str] = []
    for raw in text.split("/"):
        if raw in ("", "."):
            continue
        if raw == "..":
            raise UnsafePath("path_traversal", text)
        parts.append(validate_windows_name(raw))
    if not parts:
        raise UnsafePath("empty_path", text)
    return "/".join(parts)


def assert_within(root, path) -> Path:
    """确认 ``path`` 位于 ``root`` 内，且路径上没有任何符号链接/重解析点。

    返回解析后的绝对路径；任何越界、``..``、链接或设备名都会抛
    :class:`UnsafePath`。``path`` 为相对路径时按 ``root`` 解析。
    """
    root_path = Path(root)
    try:
        root_abs = Path(os.path.abspath(str(root_path)))
    except OSError:
        root_abs = root_path
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root_abs / candidate
    candidate = Path(os.path.normpath(str(candidate)))
    try:
        relative = candidate.relative_to(root_abs)
    except ValueError:
        # macOS /var → /private/var、Windows 8.3 短路径等：两边都 realpath 后再比。
        try:
            relative = candidate.resolve(strict=False).relative_to(root_abs.resolve(strict=False))
        except (OSError, ValueError):
            raise UnsafePath("path_escape", str(path)) from None
    current = root_abs
    for part in relative.parts:
        if part == "..":
            raise UnsafePath("path_traversal", str(path))
        validate_windows_name(part)
        current = current / part
        reason = _link_reason(current)
        if reason is not None:
            raise UnsafePath(reason, str(current))
    try:
        return candidate.resolve(strict=False)
    except OSError:
        return candidate


# --------------------------------------------------------------------------- 事务日志


def tx_root(project) -> Path:
    """返回 ``<project>/.webnovel/transactions``（不创建目录）。"""
    return Path(project) / ".webnovel" / "transactions"


def _canonical_tx_id(tx_id) -> str:
    if not isinstance(tx_id, str):
        raise UnsafePath("invalid_tx_id")
    text = tx_id.strip()
    while text.startswith("tx_"):
        text = text[3:]
    if not text or not _TX_ID.match(text) or text in (".", ".."):
        raise UnsafePath("invalid_tx_id", tx_id)
    validate_windows_name(text)
    return text


def _new_tx_id() -> str:
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "_" + uuid.uuid4().hex[:12]


def _tx_path(project, tx_id: str) -> Path:
    return tx_root(project) / f"tx_{tx_id}.json"


def _staging_dir(project, tx_id: str) -> Path:
    return tx_root(project) / tx_id


def _normalise_step(project: Path, index: int, step: Mapping[str, Any],
                    virtual: Dict[str, Optional[bytes]]) -> Tuple[Dict[str, Any], Optional[bytes]]:
    """规范化一步并返回 (记录, 需要暂存的写入字节)。

    ``virtual`` 记录本事务内前面步骤造成的路径状态（``None`` 表示已删除），
    这样「先写后改名/删除」的步骤校验的是事务自己的预期字节，而不是过期的
    磁盘旧内容。
    """
    if not isinstance(step, Mapping):
        raise TransactionConflict("invalid_step", f"step {index} 不是对象")
    kind = step.get("kind")
    if kind == "write":
        if "path" not in step:
            raise TransactionConflict("invalid_step", f"step {index} 缺少 path")
        relative = _relative_path(step["path"])
        has_text = step.get("content") is not None
        has_b64 = step.get("content_b64") is not None
        if has_text and has_b64:
            raise TransactionConflict("ambiguous_content", f"step {index} 同时给出 content 与 content_b64")
        if has_b64:
            try:
                data = base64.b64decode(str(step["content_b64"]), validate=True)
            except (ValueError, TypeError) as exc:
                raise TransactionConflict("invalid_base64", f"step {index}") from exc
        elif has_text:
            data = str(step["content"]).encode("utf-8")
        else:
            data = b""
        virtual[relative] = data
        record = {"kind": "write", "index": index, "path": relative,
                  "sha256": _sha256(data), "size": len(data)}
        return record, data
    if kind == "rename":
        if "from_path" not in step or "to_path" not in step:
            raise TransactionConflict("invalid_step", f"step {index} 缺少 from_path/to_path")
        source_rel = _relative_path(step["from_path"])
        target_rel = _relative_path(step["to_path"])
        if source_rel == target_rel:
            raise TransactionConflict("rename_noop", f"step {index}")
        if source_rel in virtual:
            data = virtual[source_rel]
            if data is None:
                raise TransactionConflict("source_missing", source_rel, step=index)
        else:
            source = assert_within(project, source_rel)
            if not source.is_file():
                raise TransactionConflict("source_missing", source_rel, step=index)
            data = source.read_bytes()
        virtual[target_rel] = data
        virtual[source_rel] = None
        record = {"kind": "rename", "index": index,
                  "from_path": source_rel, "to_path": target_rel,
                  "sha256": _sha256(data), "size": len(data)}
        return record, None
    if kind == "delete":
        if "path" not in step:
            raise TransactionConflict("invalid_step", f"step {index} 缺少 path")
        relative = _relative_path(step["path"])
        if relative in virtual:
            data = virtual[relative]
        else:
            target = assert_within(project, relative)
            if target.is_file():
                data = target.read_bytes()
            elif target.exists():
                raise TransactionConflict("not_a_file", relative, step=index)
            else:
                data = None
        virtual[relative] = None
        record = {"kind": "delete", "index": index, "path": relative,
                  "existed": data is not None,
                  "sha256": _sha256(data) if data is not None else None,
                  "size": len(data) if data is not None else 0}
        return record, None
    raise TransactionConflict("unknown_step_kind", str(kind), step=index)


def _fingerprint(steps: Sequence[Mapping[str, Any]]) -> str:
    payload = [
        {key: value for key, value in step.items() if key != "staged"}
        for step in steps
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return _sha256(encoded)


def prepare(project, steps, tx_id: Optional[str] = None,
            meta: Optional[Mapping[str, Any]] = None) -> str:
    """把一组步骤写入事务日志并暂存全部写入字节，返回 ``tx_id``。

    暂存文件位于 ``<project>/.webnovel/transactions/<tx_id>/``，记录位于
    ``tx_<tx_id>.json``。同一 ``tx_id`` 重复提交完全相同内容时幂等返回；
    内容不同或事务已开始则抛 :class:`TransactionConflict`。
    """
    project_path = Path(project)
    project_path.mkdir(parents=True, exist_ok=True)
    if isinstance(steps, (str, bytes, Mapping)):
        raise TransactionConflict("invalid_steps", "steps 必须是非空序列")
    try:
        steps = list(steps)
    except TypeError as exc:
        raise TransactionConflict("invalid_steps", "steps 必须是非空序列") from exc
    if not steps:
        raise TransactionConflict("invalid_steps", "steps 必须是非空序列")
    canonical = _canonical_tx_id(tx_id) if tx_id is not None else _new_tx_id()
    normalised: List[Dict[str, Any]] = []
    payloads: Dict[int, bytes] = {}
    virtual: Dict[str, Optional[bytes]] = {}
    for index, step in enumerate(steps):
        record, payload = _normalise_step(project_path, index, step, virtual)
        normalised.append(record)
        if payload is not None:
            payloads[index] = payload
    fingerprint = _fingerprint(normalised)
    path = _tx_path(project_path, canonical)
    if path.exists():
        existing = _load_record(project_path, canonical)
        if existing.get("state") == "prepared" and existing.get("fingerprint") == fingerprint:
            return canonical
        raise TransactionConflict("tx_exists", canonical, tx_id=canonical)
    if meta is not None and not isinstance(meta, Mapping):
        raise TransactionConflict("invalid_meta", "meta 必须是对象")
    stamp = _now()
    record: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "tx_id": canonical,
        "state": "prepared",
        "fingerprint": fingerprint,
        "staged_dir": canonical,
        "created_at": stamp,
        "updated_at": stamp,
        "meta": dict(meta or {}),
        "steps": normalised,
        "done": [],
    }
    staging = _staging_dir(project_path, canonical)
    staging.mkdir(parents=True, exist_ok=True)
    for index, payload in payloads.items():
        staged_name = f"step_{index:03d}.bin"
        _atomic_write_bytes(staging / staged_name, payload)
        record["steps"][index]["staged"] = staged_name
    try:
        _atomic_write_bytes(path, _json_bytes(record))
    except (TypeError, ValueError) as exc:
        raise TransactionConflict("meta_not_serializable", str(exc)[:200], tx_id=canonical) from exc
    return canonical


def _load_record(project, tx_id: str) -> Dict[str, Any]:
    path = _tx_path(project, tx_id)
    try:
        record = _read_json(path)
    except FileNotFoundError as exc:
        raise TransactionConflict("tx_missing", str(path), tx_id=tx_id) from exc
    except (OSError, ValueError) as exc:
        raise TransactionConflict("tx_corrupt", str(path), tx_id=tx_id) from exc
    if not isinstance(record, dict) or record.get("schema") != SCHEMA_VERSION:
        raise TransactionConflict("tx_corrupt", str(path), tx_id=tx_id)
    if record.get("tx_id") != tx_id:
        raise TransactionConflict("tx_identity_mismatch", tx_id, tx_id=tx_id)
    steps = record.get("steps")
    if not isinstance(steps, list) or not steps:
        raise TransactionConflict("tx_corrupt", str(path), tx_id=tx_id)
    for step in steps:
        if not isinstance(step, dict):
            raise TransactionConflict("tx_corrupt", "step", tx_id=tx_id)
        kind = step.get("kind")
        if kind == "write":
            if not isinstance(step.get("path"), str) or not isinstance(step.get("sha256"), str):
                raise TransactionConflict("tx_corrupt", "write step", tx_id=tx_id)
        elif kind == "rename":
            if not isinstance(step.get("from_path"), str) or not isinstance(step.get("to_path"), str):
                raise TransactionConflict("tx_corrupt", "rename step", tx_id=tx_id)
        elif kind == "delete":
            if not isinstance(step.get("path"), str):
                raise TransactionConflict("tx_corrupt", "delete step", tx_id=tx_id)
        else:
            raise TransactionConflict("tx_corrupt", "step kind", tx_id=tx_id)
        if not isinstance(step.get("index"), int):
            raise TransactionConflict("tx_corrupt", "step index", tx_id=tx_id)
    if not isinstance(record.get("done") or [], list):
        raise TransactionConflict("tx_corrupt", "done", tx_id=tx_id)
    return record


def _save_record(project, record: Mapping[str, Any]) -> None:
    tx_id = record.get("tx_id")
    if not isinstance(tx_id, str) or not tx_id:
        raise TransactionConflict("tx_corrupt", "缺少 tx_id")
    _atomic_write_bytes(_tx_path(project, tx_id), _json_bytes(record))


def _read_staged(project, record: Mapping[str, Any], step: Mapping[str, Any]) -> bytes:
    staged_name = step.get("staged")
    if not isinstance(staged_name, str) or not staged_name:
        raise TransactionConflict("staged_missing", f"step {step.get('index')}", step=step.get("index"))
    if "/" in staged_name or "\\" in staged_name or staged_name in (".", ".."):
        raise TransactionConflict("tx_record_tampered", "staged name", step=step.get("index"))
    validate_windows_name(staged_name)
    try:
        directory_name = _canonical_tx_id(str(record.get("staged_dir") or record.get("tx_id")))
    except UnsafePath as exc:
        raise TransactionConflict("tx_record_tampered", exc.code, step=step.get("index")) from exc
    path = _staging_dir(project, directory_name) / staged_name
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise TransactionConflict("staged_missing", f"step {step.get('index')}",
                                  step=step.get("index")) from exc
    if len(data) != int(step.get("size") or 0):
        raise TransactionConflict("staged_size_mismatch", f"step {step.get('index')}",
                                  step=step.get("index"))
    if _sha256(data) != step.get("sha256"):
        raise TransactionConflict("staged_corrupt", f"step {step.get('index')}",
                                  step=step.get("index"))
    return data


def _apply_step(project: Path, record: Mapping[str, Any], step: Mapping[str, Any]) -> None:
    kind = step.get("kind")
    expected = step.get("sha256")
    index = step.get("index")
    if kind == "write":
        target = assert_within(project, step["path"])
        if expected and _file_sha(target) == expected:
            return  # 幂等：目标已是事务写入的字节
        if target.exists() and not target.is_file():
            raise TransactionConflict("target_not_file", str(target), step=index)
        data = _read_staged(project, record, step)
        _atomic_write_bytes(target, data)
        if _file_sha(target) != expected:
            raise TransactionConflict("write_verify_failed", str(target), step=index)
        return
    if kind == "rename":
        source = assert_within(project, step["from_path"])
        target = assert_within(project, step["to_path"])
        target_sha = _file_sha(target)
        if expected and target_sha == expected:
            return  # 幂等：改名已经完成
        if target.exists() and not target.is_file():
            raise TransactionConflict("target_not_file", str(target), step=index)
        if target_sha is not None:
            raise TransactionConflict("target_exists", str(target), step=index)
        source_sha = _file_sha(source)
        if source_sha is None:
            raise TransactionConflict("source_missing", str(source), step=index)
        if expected and source_sha != expected:
            raise TransactionConflict("source_changed", str(source), step=index)
        target.parent.mkdir(parents=True, exist_ok=True)
        rename_with_retry(source, target)
        _fsync_dir(target.parent)
        if _file_sha(target) != expected:
            raise TransactionConflict("rename_verify_failed", str(target), step=index)
        return
    if kind == "delete":
        target = assert_within(project, step["path"])
        current = _file_sha(target)
        if current is None:
            if target.exists():
                raise TransactionConflict("target_not_file", str(target), step=index)
            return  # 已不存在：幂等
        if step.get("existed") is False:
            raise TransactionConflict("delete_appeared", str(target), step=index)
        if expected and current != expected:
            raise TransactionConflict("delete_changed", str(target), step=index)
        os.unlink(target)
        _fsync_dir(target.parent)
        return
    raise TransactionConflict("unknown_step_kind", str(kind), step=index)


def _summary(record: Mapping[str, Any], *, applied: bool) -> Dict[str, Any]:
    return {
        "tx_id": record.get("tx_id"),
        "state": record.get("state"),
        "steps": len(record.get("steps") or []),
        "done": list(record.get("done") or []),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "completed_at": record.get("completed_at"),
        "meta": record.get("meta") or {},
        "applied": applied,
        "conflict": record.get("conflict"),
    }


def apply(project, tx_id) -> Dict[str, Any]:
    """按 ``tx.json`` 与暂存字节执行事务；已 ``done`` 时幂等返回。

    执行前先落盘 ``state=applying``，每完成一步推进一次 ``done``。任何步骤
    校验失败或 I/O 错误都会保持 ``applying``、记录 ``last_error`` 并抛出
    :class:`TransactionConflict`（带机器码），绝不截断目标文件。
    """
    project_path = Path(project)
    canonical = _canonical_tx_id(tx_id)
    record = _load_record(project_path, canonical)
    state = record.get("state")
    if state == "done":
        return _summary(record, applied=False)
    if state == "conflict":
        conflict = record.get("conflict") or {}
        raise TransactionConflict(str(conflict.get("code") or "tx_conflict"),
                                  str(conflict.get("detail") or ""), tx_id=canonical)
    if state not in _ACTIVE_STATES:
        raise TransactionConflict("tx_state_invalid", str(state), tx_id=canonical)
    if state == "prepared":
        record["state"] = "applying"
        record["started_at"] = _now()
        record["updated_at"] = record["started_at"]
        try:
            _save_record(project_path, record)
        except (OSError, FileInUse) as exc:
            raise TransactionConflict("os_error", str(exc), tx_id=canonical) from exc
    try:
        done = {int(value) for value in (record.get("done") or [])}
    except (TypeError, ValueError) as exc:
        raise TransactionConflict("tx_corrupt", "done", tx_id=canonical) from exc
    for step in record.get("steps") or []:
        index = int(step.get("index"))
        if index in done:
            continue
        try:
            _apply_step(project_path, record, step)
        except TransactionConflict as exc:
            _record_error(project_path, record, exc.code, index, str(exc))
            raise
        except UnsafePath as exc:
            error = TransactionConflict("unsafe_path", exc.code, tx_id=canonical, step=index)
            _record_error(project_path, record, error.code, index, str(exc))
            raise error from exc
        except FileInUse as exc:
            error = TransactionConflict("file_in_use", str(exc), tx_id=canonical, step=index)
            _record_error(project_path, record, error.code, index, str(exc))
            raise error from exc
        except OSError as exc:
            error = TransactionConflict("os_error", str(exc), tx_id=canonical, step=index)
            _record_error(project_path, record, error.code, index, str(exc))
            raise error from exc
        done.add(index)
        record["done"] = sorted(done)
        record["updated_at"] = _now()
        record.pop("last_error", None)
        try:
            _save_record(project_path, record)
        except (OSError, FileInUse) as exc:
            raise TransactionConflict("os_error", str(exc), tx_id=canonical, step=index) from exc
    record["state"] = "done"
    record["completed_at"] = _now()
    record["updated_at"] = record["completed_at"]
    record["done"] = sorted(done)
    record.pop("last_error", None)
    try:
        _save_record(project_path, record)
    except (OSError, FileInUse) as exc:
        raise TransactionConflict("os_error", str(exc), tx_id=canonical) from exc
    return _summary(record, applied=True)


def _record_error(project, record: Dict[str, Any], code: str, step: int, message: str) -> None:
    record["updated_at"] = _now()
    record["last_error"] = {"code": code, "step": step, "at": record["updated_at"],
                            "message": message[:400]}
    try:
        _save_record(project, record)
    except (OSError, TransactionConflict):
        pass  # 记录失败不能掩盖原始错误；重启后仍可从磁盘现状恢复


def _mark_conflict(project, record: Dict[str, Any], code: str, step: Optional[int],
                   message: str) -> Dict[str, Any]:
    record["state"] = "conflict"
    record["updated_at"] = _now()
    record["conflict"] = {"code": code, "step": step, "at": record["updated_at"],
                          "detail": message[:400]}
    _save_record(project, record)
    return record


def _mark_raw_conflict(path, code: str, step: Optional[int], message: str) -> Optional[Dict[str, Any]]:
    """记录本身已损坏、无法走 ``_load_record`` 时，仍保留现场并标记 conflict。"""
    try:
        record = _read_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    record["state"] = "conflict"
    record["updated_at"] = _now()
    record["conflict"] = {"code": code, "step": step, "at": record["updated_at"],
                          "detail": message[:400]}
    try:
        _atomic_write_bytes(Path(path), _json_bytes(record))
    except (OSError, ValueError, TypeError):
        return None
    return record


def pending(project) -> List[Dict[str, Any]]:
    """列出处于 ``prepared`` / ``applying`` 的事务（按创建时间排序）。"""
    root = tx_root(project)
    if not root.is_dir():
        return []
    result: List[Dict[str, Any]] = []
    for path in sorted(root.glob("tx_*.json")):
        try:
            record = _read_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or record.get("state") not in _ACTIVE_STATES:
            continue
        item = dict(record)
        item["path"] = str(path)
        result.append(item)
    result.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("tx_id") or "")))
    return result


def assert_readable(project) -> None:
    """读取一致性门面：存在未完成事务时抛 ``RecoveryInProgress``。

    本函数**不会**自动恢复，避免读取路径悄悄写盘；调用方应自行决定是返回
    409 还是先调用 :func:`recover`。
    """
    active = pending(project)
    if active:
        ids = ", ".join(str(item.get("tx_id")) for item in active[:5])
        raise RecoveryInProgress(
            f"recovery_in_progress: {len(active)} 个事务未完成（{ids}）", active)


def recover(project) -> List[Dict[str, Any]]:
    """扫描 ``tx_*.json``，按各事务自己的记录续跑 prepared/applying。

    ``done`` 是提示，不是信任来源：每一步都会重新校验磁盘实际内容。若暂存
    载荷丢失且目标也不匹配，标记 ``conflict`` 并保留事务文件，绝不删除。
    返回每个事务的摘要（含 ``action``：applied / conflict / deferred / skipped）。
    """
    project_path = Path(project)
    root = tx_root(project_path)
    results: List[Dict[str, Any]] = []
    if not root.is_dir():
        return results
    for path in sorted(root.glob("tx_*.json")):
        try:
            record = _read_json(path)
        except (OSError, ValueError):
            results.append({"tx_id": path.stem[3:], "path": str(path),
                            "state": "invalid", "action": "skipped",
                            "error": "invalid_record"})
            continue
        if not isinstance(record, dict):
            results.append({"tx_id": path.stem[3:], "path": str(path),
                            "state": "invalid", "action": "skipped",
                            "error": "invalid_record"})
            continue
        tx_id = str(record.get("tx_id") or path.stem[3:])
        raw_steps = record.get("steps")
        raw_done = record.get("done")
        base = {"tx_id": tx_id, "path": str(path), "state": record.get("state"),
                "steps": len(raw_steps) if isinstance(raw_steps, list) else 0,
                "done": list(raw_done) if isinstance(raw_done, list) else []}
        if record.get("state") not in _ACTIVE_STATES:
            base["action"] = "skipped"
            results.append(base)
            continue
        try:
            summary = apply(project_path, tx_id)
        except UnsafePath as exc:
            fresh = _mark_raw_conflict(path, exc.code, None, str(exc))
            if fresh is None:
                base.update({"state": record.get("state"), "action": "deferred",
                             "error": exc.code})
            else:
                base.update({"state": "conflict", "action": "conflict",
                             "error": exc.code, "conflict": fresh.get("conflict")})
            results.append(base)
            continue
        except TransactionConflict as exc:
            if exc.code in _CONFLICT_CODES:
                try:
                    fresh = _load_record(project_path, tx_id)
                    fresh = _mark_conflict(project_path, fresh, exc.code, exc.step, str(exc))
                    base.update({"state": "conflict", "action": "conflict",
                                 "error": exc.code, "conflict": fresh.get("conflict"),
                                 "done": list(fresh.get("done") or [])})
                except (OSError, TransactionConflict) as save_exc:
                    base.update({"state": "applying", "action": "deferred",
                                 "error": f"{exc.code}:{save_exc}"})
            elif exc.code in ("tx_corrupt", "tx_identity_mismatch", "tx_state_invalid"):
                fresh = _mark_raw_conflict(path, exc.code, exc.step, str(exc))
                if fresh is None:
                    base.update({"state": record.get("state"), "action": "deferred",
                                 "error": exc.code})
                else:
                    base.update({"state": "conflict", "action": "conflict",
                                 "error": exc.code, "conflict": fresh.get("conflict")})
            else:
                base.update({"state": record.get("state"), "action": "deferred",
                             "error": exc.code})
            results.append(base)
            continue
        except (OSError, FileInUse) as exc:
            base.update({"state": record.get("state"), "action": "deferred",
                         "error": str(exc)[:200]})
            results.append(base)
            continue
        base.update({"state": summary.get("state"), "action": "applied",
                     "done": summary.get("done") or []})
        results.append(base)
    return results


# --------------------------------------------------------------------------- 便捷单步 API


def write_text(project, path, text, **kwargs) -> Dict[str, Any]:
    """便捷写入：``prepare`` + ``apply`` 单步文本（UTF-8）。"""
    if not isinstance(text, str):
        raise TypeError("text 必须是 str")
    tx_id = prepare(project, [{"kind": "write", "path": path, "content": text}], **kwargs)
    return apply(project, tx_id)


def write_bytes(project, path, data: bytes, **kwargs) -> Dict[str, Any]:
    """便捷写入：``prepare`` + ``apply`` 单步二进制（走 ``content_b64``）。"""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data 必须是 bytes")
    encoded = base64.b64encode(bytes(data)).decode("ascii")
    tx_id = prepare(project, [{"kind": "write", "path": path, "content_b64": encoded}], **kwargs)
    return apply(project, tx_id)


def rename(project, src, dst, **kwargs) -> Dict[str, Any]:
    """便捷改名：``prepare`` + ``apply`` 单步。"""
    tx_id = prepare(project, [{"kind": "rename", "from_path": src, "to_path": dst}], **kwargs)
    return apply(project, tx_id)


def delete(project, path, **kwargs) -> Dict[str, Any]:
    """便捷删除：``prepare`` + ``apply`` 单步。"""
    tx_id = prepare(project, [{"kind": "delete", "path": path}], **kwargs)
    return apply(project, tx_id)


# --------------------------------------------------------------------------- 备份屏障


@contextmanager
def barrier(project, timeout: float = 5.0):
    """等待活动事务清零的轻量屏障；超时抛 :class:`BarrierTimeout`。"""
    started = time.monotonic()
    limit = max(0.0, float(timeout))
    while True:
        active = pending(project)
        if not active:
            break
        if time.monotonic() - started >= limit:
            raise BarrierTimeout(f"barrier_timeout: 仍有 {len(active)} 个事务", active)
        time.sleep(0.05)
    yield


# --------------------------------------------------------------------------- 一致性备份


def _as_path_list(value) -> List[Path]:
    if value is None:
        return []
    if isinstance(value, (str, os.PathLike)):
        return [Path(value)]
    if isinstance(value, (list, tuple, set)):
        return [Path(item) for item in value]
    raise TypeError("extra_sqlite 必须是路径或路径序列")


def _safe_db_name(name: str, index: int) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "_", str(name or "db"))[:60].strip("._-") or "db"
    return f"extra-{index:02d}-{cleaned}"


def _copy_file_atomic(source, target) -> Tuple[str, int]:
    source = Path(source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            while True:
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        rename_with_retry(temporary, target)
        _fsync_dir(target.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return digest.hexdigest(), size


def _copy_tree(source_dir, dest_root, records: List[Dict[str, Any]], *,
               skipped: List[Dict[str, Any]], prefix: str = "") -> None:
    """复制目录树（不跟随链接），逐文件原子写入并登记 sha256/大小。"""
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        return
    if _is_link_like(source_dir):
        skipped.append({"path": str(source_dir), "reason": "symlink"})
        return
    for current, dirs, names in os.walk(source_dir, followlinks=False):
        current_path = Path(current)
        kept: List[str] = []
        for name in sorted(dirs):
            candidate = current_path / name
            if _is_link_like(candidate):
                skipped.append({"path": str(candidate), "reason": "symlink"})
            else:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(names):
            source = current_path / name
            if _is_link_like(source):
                skipped.append({"path": str(source), "reason": "symlink"})
                continue
            if not source.is_file():
                continue
            relative = source.relative_to(source_dir)
            parts = list(relative.parts)
            rel = "/".join(([prefix] if prefix else []) + parts)
            try:
                rel = _relative_path(rel)
            except UnsafePath:
                skipped.append({"path": str(source), "reason": "unsafe_name"})
                continue
            target = _join(dest_root, rel)
            checksum, size = _copy_file_atomic(source, target)
            records.append({"path": rel, "kind": "file",
                            "sha256": checksum, "size": size})


def _copy_single(source, target, rel: str, records: List[Dict[str, Any]]) -> None:
    checksum, size = _copy_file_atomic(source, target)
    records.append({"path": rel, "kind": "file", "sha256": checksum, "size": size})


def _first_file(root, candidates: Sequence[str]):
    for rel in candidates:
        path = assert_within(root, rel)
        if path.is_file():
            return path, rel
    return None, None


def _first_dir(root, candidates: Sequence[str]):
    for rel in candidates:
        path = assert_within(root, rel)
        if path.is_dir():
            return path, rel
    return None, None


_BODY_CHAPTER = re.compile(r"^(?:第\s*0*(\d+)\s*章|\s*0*(\d+)(?:[：:\-＿_\s]|$))")


def _body_chapter_number(name: str) -> Optional[int]:
    match = _BODY_CHAPTER.search(Path(name).stem.strip())
    if not match:
        return None
    value = match.group(1) or match.group(2)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _body_sha_map(folder) -> Dict[int, str]:
    folder = Path(folder)
    result: Dict[int, str] = {}
    if not folder.is_dir():
        return result
    for path in sorted(folder.glob("*.md")):
        if _is_link_like(path) or not path.is_file():
            continue
        number = _body_chapter_number(path.name)
        if number is None or number in result:
            continue
        result[number] = _file_sha(path) or ""
    return result


def _index_current(index_data: Any) -> Dict[int, str]:
    result: Dict[int, str] = {}
    if not isinstance(index_data, dict):
        return result
    chapters = index_data.get("chapters")
    if not isinstance(chapters, dict):
        return result
    for key, entry in chapters.items():
        if not isinstance(entry, dict):
            continue
        try:
            number = int(key)
        except (TypeError, ValueError):
            continue
        current = str(entry.get("current") or "")
        if current:
            result[number] = current
    return result


_OBJECT_SHA = re.compile(r"^[0-9a-f]{64}$")


def _index_version_objects(index_data: Any) -> List[Tuple[int, str]]:
    """Every version-object sha referenced by an index (versions + current)."""
    result: List[Tuple[int, str]] = []
    seen = set()
    if not isinstance(index_data, dict):
        return result
    chapters = index_data.get("chapters")
    if not isinstance(chapters, dict):
        return result
    for key, entry in chapters.items():
        if not isinstance(entry, dict):
            continue
        try:
            number = int(key)
        except (TypeError, ValueError):
            continue
        candidates = [entry.get("current")]
        for item in entry.get("versions") or []:
            if isinstance(item, dict):
                candidates.append(item.get("sha256"))
        for value in candidates:
            sha = str(value or "")
            if _OBJECT_SHA.match(sha) and (number, sha) not in seen:
                seen.add((number, sha))
                result.append((number, sha))
    return result


def _objects_rel_for(index_rel: str) -> str:
    base = index_rel.rsplit("/", 1)[0] if "/" in index_rel else ""
    return (base + "/objects") if base else "objects"


def _drop_record(records: List[Dict[str, Any]], rel: str) -> None:
    records[:] = [item for item in records if item.get("path") != rel]


def _drop_stale_bodies(dest_body_dir: Path, number: int, keep_name: str,
                       records: List[Dict[str, Any]]) -> None:
    """Remove other backup files for the same chapter number.

    A title rename during backup leaves both the old and new filename; the
    manifest then lists the old body first and ``restore`` rejects the whole
    backup with ``index_body_mismatch`` (A-P2-04).
    """
    if not dest_body_dir.is_dir():
        return
    for path in sorted(dest_body_dir.glob("*.md")):
        if path.name == keep_name:
            continue
        if _body_chapter_number(path.name) != int(number):
            continue
        try:
            path.unlink()
        except OSError:
            continue
        _drop_record(records, "正文/" + path.name)


@contextmanager
def _versions_lock(project, timeout: float):
    """Exclusive lock shared with ``chapter_versions`` (same ``.lock`` file)."""
    path = Path(project) / ".webnovel" / "chapter_versions" / ".lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    deadline = time.monotonic() + max(0.0, float(timeout))
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise BarrierTimeout("backup_versions_busy") from exc
                time.sleep(0.05)
        yield
    finally:
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        stream.close()


def _recopy_file(source, target, rel: str, records: List[Dict[str, Any]]) -> None:
    checksum, size = _copy_file_atomic(source, target)
    for entry in records:
        if entry.get("path") == rel:
            entry["sha256"] = checksum
            entry["size"] = size
            return
    records.append({"path": rel, "kind": "file", "sha256": checksum, "size": size})


def _reconcile_backup_index(project_path: Path, dest: Path, records: List[Dict[str, Any]],
                            wait_seconds: float) -> Dict[str, Any]:
    """Copy the version index and bodies as one consistent generation.

    A save can land between the body copy and the index copy.  Re-reading the
    index under the version lock and re-copying only mismatched bodies closes
    that window without holding the lock for the whole backup (A-P2-7).
    """
    index_rel = None
    for candidate in (".webnovel/chapter_versions/index.json", "chapter_versions/index.json"):
        if (dest / Path(candidate)).is_file():
            index_rel = candidate
            break
    if index_rel is None:
        return {"ok": True, "chapters": 0}
    problems: List[str] = []
    objects_rel = _objects_rel_for(index_rel)
    for attempt in range(4):
        with _versions_lock(project_path, wait_seconds):
            source_index = project_path / Path(index_rel)
            if not source_index.is_file():
                return {"ok": True, "chapters": 0, "attempts": attempt + 1}
            _recopy_file(source_index, dest / Path(index_rel), index_rel, records)
            try:
                index_data = json.loads((dest / Path(index_rel)).read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                return {"ok": False, "problems": ["index_unreadable"]}
            current = _index_current(index_data)
            project_bodies = _body_sha_map(project_path / "正文")
            problems = []
            for number, sha in sorted(current.items()):
                source = project_bodies.get(number)
                if not source or source != sha:
                    problems.append(f"index_body_missing:{number}")
                    continue
                body_path = None
                for path in (project_path / "正文").glob("*.md"):
                    if _body_chapter_number(path.name) == number and not _is_link_like(path):
                        body_path = path
                        break
                if body_path is None:
                    problems.append(f"index_body_missing:{number}")
                    continue
                # Remove a same-chapter file left by a rename during the copy
                # before/after writing the current body (A-P2-04).
                _drop_stale_bodies(dest / "正文", number, body_path.name, records)
                target_body = dest / "正文" / body_path.name
                if not (target_body.is_file() and _file_sha(target_body) == sha):
                    rel = "正文/" + body_path.name
                    _recopy_file(body_path, target_body, rel, records)
            # The backup must contain every version object the index points at,
            # not just the current body: restored history otherwise fails with
            # VersionNotFound("object_missing") (A-P2-03).
            for number, sha in _index_version_objects(index_data):
                source_object = project_path / Path(objects_rel) / f"{sha}.txt"
                dest_object = dest / Path(objects_rel) / f"{sha}.txt"
                if not source_object.is_file():
                    problems.append(f"index_object_missing:{number}:{sha}")
                    continue
                if _file_sha(source_object) != sha:
                    problems.append(f"index_object_corrupt:{number}:{sha}")
                    continue
                if _file_sha(dest_object) != sha:
                    _recopy_file(source_object, dest_object, f"{objects_rel}/{sha}.txt", records)
            if not problems:
                return {"ok": True, "chapters": len(current),
                        "objects": len(_index_version_objects(index_data)),
                        "attempts": attempt + 1}
        time.sleep(0.05)
    return {"ok": False, "problems": problems}


def _backup_index_problems(reader, manifest: Mapping[str, Any]) -> List[str]:
    index_rel = None
    for candidate in (".webnovel/chapter_versions/index.json", "chapter_versions/index.json"):
        if any(isinstance(item, dict) and item.get("path") == candidate
               for item in (manifest.get("files") or [])):
            index_rel = candidate
            break
    if index_rel is None:
        return []
    try:
        index_data = json.loads(reader.read(index_rel).decode("utf-8-sig"))
    except (OSError, ValueError, UnsafePath, FileNotFoundError):
        return ["index_unreadable"]
    current = _index_current(index_data)
    if not current:
        return []
    body_entries: Dict[int, str] = {}
    for item in manifest.get("files") or []:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("path") or "")
        if not rel.startswith("正文/"):
            continue
        number = _body_chapter_number(Path(rel).name)
        if number is None or number in body_entries:
            continue
        try:
            body_entries[number] = _sha256(reader.read(rel))
        except (OSError, UnsafePath, FileNotFoundError):
            continue
    problems: List[str] = []
    duplicates: Dict[int, set] = {}
    for item in manifest.get("files") or []:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("path") or "")
        if rel.startswith("正文/"):
            number = _body_chapter_number(Path(rel).name)
            if number is not None:
                duplicates.setdefault(number, set()).add(rel)
    for number, shas in sorted(duplicates.items()):
        if len(shas) > 1:
            problems.append(f"index_body_duplicate:{number}")
    for number, sha in sorted(current.items()):
        actual = body_entries.get(number)
        if actual is None:
            problems.append(f"index_body_missing:{number}")
        elif actual != sha:
            problems.append(f"index_body_mismatch:{number}")
    # Version objects are part of the backup contract: an index entry whose
    # object is absent makes every historical read fail after restore
    # (A-P2-03).
    objects_rel = _objects_rel_for(index_rel)
    manifest_paths = {str(item.get("path") or "") for item in manifest.get("files") or []
                      if isinstance(item, dict)}
    for number, sha in _index_version_objects(index_data):
        rel = f"{objects_rel}/{sha}.txt"
        if rel not in manifest_paths:
            problems.append(f"index_object_missing:{number}:{sha}")
            continue
        try:
            data = reader.read(rel)
        except (OSError, UnsafePath, FileNotFoundError):
            problems.append(f"index_object_missing:{number}:{sha}")
            continue
        if _sha256(data) != sha:
            problems.append(f"index_object_mismatch:{number}:{sha}")
    return problems


def _annotation_snapshot_refs(sqlite_bytes: bytes) -> set:
    """Snapshot ids referenced by annotations/preview_index in a backup DB."""
    import tempfile
    refs: set = set()
    handle = tempfile.NamedTemporaryFile(prefix="backup-refs-", suffix=".sqlite3", delete=False)
    try:
        handle.write(sqlite_bytes)
        handle.flush()
        handle.close()
        connection = sqlite3.connect(handle.name)
        try:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "annotations" in tables:
                for (raw,) in connection.execute(
                        "SELECT anchor_json FROM annotations WHERE anchor_json IS NOT NULL"):
                    try:
                        value = json.loads(raw or "null")
                    except (TypeError, ValueError):
                        continue
                    if isinstance(value, dict) and value.get("base_snapshot_id"):
                        refs.add(str(value["base_snapshot_id"]))
            if "preview_index" in tables:
                for (raw,) in connection.execute(
                        "SELECT base_snapshot_id FROM preview_index WHERE base_snapshot_id IS NOT NULL"):
                    if raw:
                        refs.add(str(raw))
        except sqlite3.Error:
            return refs
        finally:
            connection.close()
    except OSError:
        return refs
    finally:
        handle.close()
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    return refs


def _revision_candidate_refs(json_bytes: bytes) -> List[str]:
    try:
        value = json.loads(json_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return []
    if not isinstance(value, dict) or not value.get("candidate_id"):
        return []
    return [str(value["candidate_id"])]


def _reconcile_backup_evidence(project_path: Path, dest: Path,
                               records: List[Dict[str, Any]],
                               skipped: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Make ID-referenced evidence (snapshots/previews/trash) complete.

    ``workbench.sqlite3`` is backed up by the SQLite API because it is a live
    database; the files it references are plain files copied tree-by-tree.  A
    write between the two copies can reference a snapshot the tree copy
    missed, so re-check every id under the same rules as the index reconcile.
    """
    problems: List[str] = []
    snapshots = 0
    previews = 0
    trash = 0
    workbench = dest / ".webnovel" / "workbench.sqlite3"
    refs = _annotation_snapshot_refs(workbench.read_bytes()) if workbench.is_file() else set()
    for digest in sorted(refs):
        if not _OBJECT_SHA.match(digest):
            continue
        snapshots += 1
        rel = f".webnovel/snapshots/{digest}.txt"
        target = _join(dest, rel)
        source = project_path / ".webnovel" / "snapshots" / f"{digest}.txt"
        if target.is_file() and _file_sha(target) == digest:
            continue
        if source.is_file() and _file_sha(source) == digest:
            _recopy_file(source, target, rel, records)
        else:
            problems.append(f"annotation_snapshot_missing:{digest}")
    candidates_root = None
    for candidate in (".webnovel/chapter_versions/candidates", "chapter_versions/candidates"):
        if (dest / Path(candidate)).is_dir():
            candidates_root = Path(candidate)
            break
    for path in sorted((dest / ".webnovel" / "revision_previews").glob("*.json")) \
            if (dest / ".webnovel" / "revision_previews").is_dir() else []:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        for candidate_id in _revision_candidate_refs(data):
            previews += 1
            if candidates_root is None:
                problems.append(f"revision_candidate_missing:{candidate_id}")
                continue
            rel = (candidates_root / f"{candidate_id}.json").as_posix()
            target = _join(dest, rel)
            source = project_path / Path(rel)
            if target.is_file():
                continue
            if source.is_file():
                _recopy_file(source, target, rel, records)
            else:
                problems.append(f"revision_candidate_missing:{candidate_id}")
    trash_root = dest / ".webnovel" / "trash"
    for manifest_path in sorted(trash_root.glob("*/manifest.json")) if trash_root.is_dir() else []:
        try:
            entry = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        payload_sha = str(entry.get("payload_sha256") or entry.get("content_sha256") or "")
        if not payload_sha:
            continue
        trash += 1
        if any(_file_sha(candidate) == payload_sha
               for candidate in sorted(manifest_path.parent.glob("*.md"))):
            continue
        problems.append(f"trash_payload_missing:{manifest_path.parent.name}")
    if problems:
        skipped.append({"path": ".webnovel/evidence", "reason": "evidence_inconsistent",
                        "problems": problems[:20]})
    return {"ok": not problems, "problems": problems, "snapshots": snapshots,
            "previews": previews, "trash": trash}


def _backup_evidence_problems(reader, manifest: Mapping[str, Any]) -> List[str]:
    """Validate ID references inside a backup before declaring it restorable."""
    problems: List[str] = []
    entries = [item for item in (manifest.get("files") or []) if isinstance(item, dict)]
    manifest_paths = {str(item.get("path") or "") for item in entries}
    workbench_rel = ".webnovel/workbench.sqlite3"
    refs: set = set()
    if workbench_rel in manifest_paths:
        try:
            refs = _annotation_snapshot_refs(reader.read(workbench_rel))
        except (OSError, UnsafePath, FileNotFoundError):
            problems.append("annotation_snapshot_unreadable")
    for digest in sorted(refs):
        if not _OBJECT_SHA.match(digest):
            continue
        rel = f".webnovel/snapshots/{digest}.txt"
        if rel not in manifest_paths:
            problems.append(f"annotation_snapshot_missing:{digest}")
            continue
        try:
            if _sha256(reader.read(rel)) != digest:
                problems.append(f"annotation_snapshot_mismatch:{digest}")
        except (OSError, UnsafePath, FileNotFoundError):
            problems.append(f"annotation_snapshot_missing:{digest}")
    candidate_paths = {path for path in manifest_paths
                       if path.endswith(".json") and "chapter_versions/candidates/" in path}
    for rel in sorted(path for path in manifest_paths
                      if path.startswith(".webnovel/revision_previews/") and path.endswith(".json")):
        try:
            data = reader.read(rel)
        except (OSError, UnsafePath, FileNotFoundError):
            continue
        for candidate_id in _revision_candidate_refs(data):
            if not any(path.endswith(f"/{candidate_id}.json") for path in candidate_paths):
                problems.append(f"revision_candidate_missing:{candidate_id}")
    trash_manifests = [path for path in manifest_paths
                       if path.startswith(".webnovel/trash/") and path.endswith("/manifest.json")]
    for rel in sorted(trash_manifests):
        try:
            entry = json.loads(reader.read(rel).decode("utf-8-sig"))
        except (OSError, UnsafePath, FileNotFoundError, UnicodeDecodeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        payload_sha = str(entry.get("payload_sha256") or entry.get("content_sha256") or "")
        if not payload_sha:
            continue
        folder = rel.rsplit("/", 1)[0] + "/"
        matched = False
        for path in manifest_paths:
            if not path.startswith(folder) or not path.endswith(".md"):
                continue
            try:
                if _sha256(reader.read(path)) == payload_sha:
                    matched = True
                    break
            except (OSError, UnsafePath, FileNotFoundError):
                continue
        if not matched:
            problems.append(f"trash_payload_missing:{folder.rstrip('/').rsplit('/', 1)[-1]}")
    return problems


def _sqlite_backup(source, target) -> Tuple[str, int]:
    source = Path(source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
    uri = source.as_uri() + "?mode=ro"
    try:
        source_db = sqlite3.connect(uri, uri=True)
        try:
            source_db.execute("PRAGMA busy_timeout=15000")
            target_db = sqlite3.connect(str(temporary))
            try:
                target_db.execute("PRAGMA busy_timeout=15000")
                source_db.backup(target_db)
                target_db.commit()
            finally:
                target_db.close()
        finally:
            source_db.close()
        with temporary.open("rb+") as stream:
            os.fsync(stream.fileno())
        rename_with_retry(temporary, target)
        _fsync_dir(target.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return _file_sha(target) or "", target.stat().st_size


def backup(project, destination, extra_sqlite=None, wait_seconds: float = 5.0,
           allowed_dir=None) -> Dict[str, Any]:
    """跨存储一致性备份：先过屏障，再 SQLite 在线备份 + 原子复制文本。

    目标目录必须位于作品目录之外且为空（避免自我递归与覆盖旧备份）。
    审计 C3-02：``allowed_dir`` 把目标限制在调用方给定的目录树内（API 传入
    ``data_dir/backups``），任意客户端路径在落盘前就被拒绝。返回摘要；
    ``backup_manifest.json`` 记录每个文件的 sha256/大小与代次。
    """
    project_path = Path(project).resolve()
    if not project_path.is_dir():
        raise FileNotFoundError(f"作品目录不存在：{project_path}")
    dest = Path(destination)
    if allowed_dir is not None and not _is_within(allowed_dir, dest):
        raise UnsafePath("destination_outside_allowed", str(dest))
    if _is_within(project_path, dest):
        raise UnsafePath("destination_inside_project", str(dest))
    records: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    sqlite_records: List[Dict[str, Any]] = []
    with barrier(project_path, wait_seconds):
        if dest.exists():
            if not dest.is_dir():
                raise FileExistsError(f"备份目标不是目录：{dest}")
            if any(dest.iterdir()):
                raise FileExistsError(f"备份目标必须为空：{dest}")
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("正文", "大纲", "设定"):
            _copy_tree(project_path / name, dest, records,
                       skipped=skipped, prefix=name)
        index, index_rel = _first_file(project_path, (
            ".webnovel/chapter_versions/index.json", "chapter_versions/index.json"))
        if index is not None:
            _copy_single(index, _join(dest, index_rel), index_rel, records)
        objects, objects_rel = _first_dir(project_path, (
            ".webnovel/chapter_versions/objects", "chapter_versions/objects"))
        if objects is not None:
            _copy_tree(objects, dest, records, skipped=skipped, prefix=objects_rel)
        # User-visible state that SQLite/JSON references by id: trash payloads,
        # annotation snapshots, revision previews and candidates.  Omitting
        # them made a "valid" backup restore books whose trash was empty and
        # whose annotations could never be relocated or applied (A-P2-12).
        for name in ("trash", "snapshots", "revision_previews"):
            folder = project_path / ".webnovel" / name
            _copy_tree(folder, dest, records, skipped=skipped,
                       prefix=f".webnovel/{name}")
        candidates, candidates_rel = _first_dir(project_path, (
            ".webnovel/chapter_versions/candidates", "chapter_versions/candidates"))
        if candidates is not None:
            _copy_tree(candidates, dest, records, skipped=skipped, prefix=candidates_rel)
        consistency = _reconcile_backup_index(project_path, dest, records, wait_seconds)
        if not consistency.get("ok"):
            skipped.append({"path": ".webnovel/chapter_versions/index.json",
                            "reason": "chapter_versions_inconsistent",
                            "problems": consistency.get("problems", [])})
        for names, dest_rel in (
            ((".webnovel/writer_receipts.json", "writer_receipts.json"), ".webnovel/writer_receipts.json"),
            ((".webnovel/story_plan.json", "story_plan.json"), ".webnovel/story_plan.json"),
            ((".webnovel/story_plan_meta.json", "story_plan_meta.json"), ".webnovel/story_plan_meta.json"),
            ((".webnovel/state.json", "state.json"), ".webnovel/state.json"),
            ((".webnovel/invalidation_log.json", "invalidation_log.json"),
             ".webnovel/invalidation_log.json"),
            ((".webnovel/shared_memory.json", "shared_memory.json"),
             ".webnovel/shared_memory.json"),
        ):
            source, actual_rel = _first_file(project_path, names)
            if source is None:
                continue
            target_rel = actual_rel if actual_rel.startswith(".webnovel/") else dest_rel
            _copy_single(source, _join(dest, target_rel), target_rel, records)

        workbench = assert_within(project_path, ".webnovel/workbench.sqlite3")
        db_sources: List[Tuple[str, Path, Optional[str], str]] = []
        if workbench.is_file():
            db_sources.append(("workbench", workbench, ".webnovel/workbench.sqlite3", str(workbench)))
        for index_no, extra in enumerate(_as_path_list(extra_sqlite)):
            extra_path = extra if extra.is_absolute() else project_path / extra
            extra_path = extra_path.resolve()
            if not extra_path.is_file():
                skipped.append({"path": str(extra), "reason": "sqlite_missing"})
                continue
            if extra_path == workbench:
                continue
            db_sources.append((_safe_db_name(extra_path.name, index_no), extra_path, None, str(extra)))
        for ordinal, (logical, source, restore_rel, source_label) in enumerate(db_sources):
            rel = f"db/{ordinal:02d}-{Path(logical).name if '/' in logical else logical}"
            if not rel.endswith(".sqlite3"):
                rel += ".sqlite3"
            checksum, size = _sqlite_backup(source, _join(dest, rel))
            entry = {"path": rel, "kind": "sqlite", "logical": logical,
                     "source": source_label, "restore": restore_rel,
                     "sha256": checksum, "size": size}
            sqlite_records.append(entry)
            records.append(entry)
        evidence = _reconcile_backup_evidence(project_path, dest, records, skipped)
        generation = time.time_ns()
        stamp = _now()
        manifest = {
            "format": BACKUP_FORMAT,
            "kind": "backup",
            "generation": generation,
            "stamp": stamp,
            "created_at": stamp,
            "project": str(project_path),
            "files": records,
            "skipped": skipped,
            "count": len(records),
            "total_bytes": sum(int(item.get("size") or 0) for item in records),
            "chapter_versions_consistency": consistency,
            "evidence_consistency": evidence,
        }
        _atomic_write_bytes(dest / "backup_manifest.json", _json_bytes(manifest))
    return {
        "destination": str(dest),
        "manifest": str(dest / "backup_manifest.json"),
        "files": len(records),
        "sqlite": len(sqlite_records),
        "bytes": manifest["total_bytes"],
        "generation": manifest["generation"],
        "stamp": manifest["stamp"],
        "skipped": skipped,
    }


# --------------------------------------------------------------------------- 安全恢复


class _BackupReader:
    """只读备份源（目录或 ZIP）；成员路径与压缩比在打开时统一校验。"""

    def __init__(self, path, *, max_total_bytes: int = _MAX_TOTAL_BYTES,
                 max_ratio: int = _MAX_RATIO):
        self.path = Path(path)
        self.max_total_bytes = int(max_total_bytes)
        self.max_ratio = int(max_ratio)
        self.kind: Optional[str] = None
        self._zip: Optional[zipfile.ZipFile] = None
        self._infos: Dict[str, zipfile.ZipInfo] = {}
        self._root: Optional[Path] = None

    def __enter__(self):
        if self.path.is_dir():
            self.kind = "dir"
            self._root = self.path.resolve(strict=True)
            return self
        if self.path.is_file() and zipfile.is_zipfile(self.path):
            self.kind = "zip"
            try:
                self._zip = zipfile.ZipFile(self.path)
                self._scan_zip()
            except zipfile.BadZipFile as exc:
                if self._zip is not None:
                    self._zip.close()
                    self._zip = None
                raise UnsafePath("zip_corrupt", str(self.path)) from exc
            except BaseException:
                if self._zip is not None:
                    self._zip.close()
                    self._zip = None
                raise
            return self
        raise FileNotFoundError(f"备份不存在或不是目录/ZIP：{self.path}")

    def __exit__(self, exc_type, exc, traceback):
        if self._zip is not None:
            self._zip.close()
        return False

    def _scan_zip(self) -> None:
        assert self._zip is not None
        total = 0
        for info in self._zip.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/"):
                continue
            rel = _relative_path(name)
            if rel != name:
                raise UnsafePath("non_canonical_member", name)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise UnsafePath("zip_symlink", name)
            if info.flag_bits & 0x1:
                raise UnsafePath("zip_encrypted", name)
            total += info.file_size
            if info.file_size > self.max_total_bytes or total > self.max_total_bytes:
                raise UnsafePath("zip_bomb_total", name)
            if info.file_size > _SMALL_FILE_BYTES:
                if info.compress_size <= 0:
                    raise UnsafePath("zip_bomb_ratio", name)
                if info.file_size / info.compress_size > self.max_ratio:
                    raise UnsafePath("zip_bomb_ratio", name)
            self._infos[rel] = info

    def manifest(self) -> Dict[str, Any]:
        data = self.read("backup_manifest.json", limit=_MAX_MANIFEST_BYTES)
        try:
            manifest = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise TransactionConflict("backup_manifest_invalid", str(exc)[:200]) from exc
        if not isinstance(manifest, dict) or manifest.get("format") != BACKUP_FORMAT:
            raise TransactionConflict("backup_manifest_invalid", "格式不匹配")
        if not isinstance(manifest.get("files"), list):
            raise TransactionConflict("backup_manifest_invalid", "files 缺失")
        return manifest

    def size(self, relative: str) -> int:
        rel = _relative_path(relative)
        if self.kind == "zip":
            info = self._infos.get(rel)
            if info is None:
                raise FileNotFoundError(rel)
            return int(info.file_size)
        target = assert_within(self._root, rel)
        if not target.is_file():
            raise FileNotFoundError(rel)
        return int(target.stat().st_size)

    def read(self, relative: str, limit: int = _MAX_FILE_BYTES) -> bytes:
        rel = _relative_path(relative)
        cap = min(int(limit), self.max_total_bytes)
        if self.kind == "zip":
            info = self._infos.get(rel)
            if info is None:
                raise FileNotFoundError(rel)
            if info.file_size > cap:
                raise UnsafePath("member_too_large", rel)
            assert self._zip is not None
            try:
                return self._zip.read(info)
            except zipfile.BadZipFile as exc:
                raise UnsafePath("zip_corrupt", rel) from exc
        target = assert_within(self._root, rel)
        if not target.is_file():
            raise FileNotFoundError(rel)
        if target.stat().st_size > cap:
            raise UnsafePath("member_too_large", rel)
        return target.read_bytes()

    def sha256(self, relative: str) -> str:
        return _sha256(self.read(relative))

    def verify(self, manifest: Mapping[str, Any]) -> List[str]:
        problems: List[str] = []
        entries = manifest.get("files")
        if not isinstance(entries, list):
            return ["manifest_files_invalid"]
        for entry in entries:
            if not isinstance(entry, dict):
                problems.append("entry_invalid")
                continue
            try:
                rel = _relative_path(entry.get("path"))
            except UnsafePath as exc:
                problems.append(f"unsafe_path:{exc.code}")
                continue
            expected = str(entry.get("sha256") or "")
            if not expected:
                problems.append(f"sha256_missing:{rel}")
                continue
            try:
                declared_size = int(entry.get("size") if entry.get("size") is not None else -1)
            except (TypeError, ValueError):
                problems.append(f"size_invalid:{rel}")
                continue
            try:
                actual_size = self.size(rel)
            except FileNotFoundError:
                problems.append(f"missing:{rel}")
                continue
            except (OSError, UnsafePath):
                problems.append(f"unreadable:{rel}")
                continue
            if declared_size != actual_size:
                problems.append(f"size_mismatch:{rel}")
                continue
            try:
                actual = self.sha256(rel)
            except (OSError, UnsafePath):
                problems.append(f"unreadable:{rel}")
                continue
            if actual != expected:
                problems.append(f"sha256_mismatch:{rel}")
        return problems


_PROTECTED_POSIX_ROOTS = ("/etc", "/usr", "/bin", "/sbin", "/boot", "/dev", "/proc", "/sys")
_DATABASE_SUFFIXES = (".sqlite3", ".sqlite", ".db")


def _is_protected_system_path(path) -> bool:
    """系统目录禁止被备份恢复覆盖，即使作者点了确认。"""
    resolved = Path(path).resolve(strict=False)
    if os.name == "nt":
        candidates = []
        for name in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            value = os.environ.get(name)
            if value:
                candidates.append(Path(value))
    else:
        candidates = [Path(item) for item in _PROTECTED_POSIX_ROOTS]
    for root in candidates:
        try:
            resolved.relative_to(root.resolve(strict=False))
            return True
        except (ValueError, OSError):
            continue
    return False


def _validate_outside_target(target: Path) -> None:
    if _is_protected_system_path(target):
        raise UnsafePath("protected_path", str(target))
    if target.suffix.lower() not in _DATABASE_SUFFIXES:
        raise UnsafePath("unsafe_outside_target", str(target))


def _backup_plan(project: Path, manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []
    for entry in manifest.get("files") or []:
        if not isinstance(entry, dict):
            raise TransactionConflict("backup_manifest_invalid", "entry")
        rel = _relative_path(entry.get("path"))
        kind = entry.get("kind") or "file"
        if kind == "sqlite":
            restore_rel = entry.get("restore")
            if restore_rel:
                target = assert_within(project, _relative_path(restore_rel))
                outside = False
            else:
                source_text = entry.get("source")
                if not isinstance(source_text, str) or not source_text:
                    raise TransactionConflict("backup_manifest_invalid", "sqlite source")
                target = Path(source_text)
                if not target.is_absolute():
                    raise UnsafePath("absolute_path", source_text)
                outside = True
        else:
            target = assert_within(project, rel)
            outside = False
        if outside:
            _validate_outside_target(target)
        if target.exists() and target.is_dir():
            raise TransactionConflict("target_not_file", str(target))
        action = "overwrite" if target.exists() else "create"
        plan.append({"path": rel, "target": str(target), "kind": kind,
                     "outside_project": outside, "action": action,
                     "sha256": entry.get("sha256"), "size": entry.get("size")})
    return plan


def _write_restored_file(target: Path, data: bytes, *, outside_project: bool) -> None:
    if _is_link_like(target):
        raise UnsafePath("symlink_target", str(target))
    if outside_project and not target.parent.is_dir():
        raise FileNotFoundError(f"恢复目标父目录不存在：{target.parent}")
    _atomic_write_bytes(target, data)


def inspect_backup(path, *, max_total_bytes: int = _MAX_TOTAL_BYTES,
                   max_ratio: int = _MAX_RATIO) -> Dict[str, Any]:
    """只读检查备份完整性与安全性；任何异常都收敛为 ``valid=False``。"""
    result: Dict[str, Any] = {"path": str(path), "kind": None, "valid": False,
                              "problems": [], "manifest": None, "files": 0,
                              "sqlite": 0, "stamp": None, "generation": None}
    try:
        with _BackupReader(path, max_total_bytes=max_total_bytes,
                           max_ratio=max_ratio) as reader:
            result["kind"] = reader.kind
            manifest = reader.manifest()
            result["manifest"] = manifest
            result["stamp"] = manifest.get("stamp")
            result["generation"] = manifest.get("generation")
            entries = manifest.get("files") or []
            result["files"] = len(entries)
            result["sqlite"] = sum(1 for item in entries
                                   if isinstance(item, dict) and item.get("kind") == "sqlite")
            problems = reader.verify(manifest)
            problems += _backup_index_problems(reader, manifest)
            problems += _backup_evidence_problems(reader, manifest)
            result["problems"] = problems
            result["valid"] = not problems
    except UnsafePath as exc:
        result["problems"] = [f"unsafe:{exc.code}"]
    except TransactionConflict as exc:
        result["problems"] = [f"manifest:{exc.code}"]
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        result["problems"] = [f"unreadable:{str(exc)[:160]}"]
    return result


def restore_backup(project, backup_path, confirmed: bool = False, *,
                   max_total_bytes: int = _MAX_TOTAL_BYTES,
                   max_ratio: int = _MAX_RATIO) -> Dict[str, Any]:
    """预览式安全恢复。

    ``confirmed=False`` 只返回将写入的目标列表，绝不落盘；``confirmed=True``
    才执行。所有条目先整体校验 sha256/大小，任何一项不符都整体拒绝。
    备份内路径必须是项目内相对 POSIX 路径；``..``、绝对路径、符号链接、
    重解析点与压缩炸弹一律拒绝。作品目录之外的 SQLite（如
    ``manager.sqlite3``）只有在 ``confirmed=True`` 时才允许写回，且系统目录
    与数据库后缀不符的目标始终拒绝。恢复会覆盖 ``workbench.sqlite3``，请先
    停止 Manager/Worker 再执行。
    """
    project_path = Path(project).resolve()
    if not project_path.is_dir():
        raise FileNotFoundError(f"作品目录不存在：{project_path}")
    with _BackupReader(backup_path, max_total_bytes=max_total_bytes,
                       max_ratio=max_ratio) as reader:
        manifest = reader.manifest()
        plan = _backup_plan(project_path, manifest)
        problems = reader.verify(manifest)
        problems += _backup_index_problems(reader, manifest)
        problems += _backup_evidence_problems(reader, manifest)
        if problems:
            raise TransactionConflict("backup_corrupt", "; ".join(problems[:5]))
        preview = {
            "confirmed": False,
            "backup": str(backup_path),
            "manifest": manifest,
            "files": plan,
            "paths": [item["path"] for item in plan],
            "targets": [item["target"] for item in plan],
            "count": len(plan),
            "stamp": manifest.get("stamp"),
            "generation": manifest.get("generation"),
            "requires_confirmation": True,
        }
        if not confirmed:
            return preview
        restored: List[str] = []
        outside: List[str] = []
        for item in plan:
            data = reader.read(item["path"])
            if item.get("sha256") and _sha256(data) != item["sha256"]:
                raise TransactionConflict("backup_corrupt", f"写入前复验失败：{item['path']}")
            target = Path(item["target"])
            _write_restored_file(target, data, outside_project=item["outside_project"])
            if item["kind"] == "sqlite" and target.suffix == ".sqlite3":
                for suffix in ("-wal", "-shm"):
                    Path(str(target) + suffix).unlink(missing_ok=True)
            restored.append(item["path"])
            if item["outside_project"]:
                outside.append(str(target))
    return {
        "confirmed": True,
        "backup": str(backup_path),
        "restored": restored,
        "count": len(restored),
        "outside_project": outside,
        "stamp": manifest.get("stamp"),
        "generation": manifest.get("generation"),
    }


# --------------------------------------------------------------------------- 降级导出


def _strip_receipt_keys(value, dropped: List[str]):
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            if key in _DROP_RECEIPT_KEYS:
                dropped.append(key)
                continue
            cleaned[key] = _strip_receipt_keys(item, dropped)
        return cleaned
    if isinstance(value, list):
        return [_strip_receipt_keys(item, dropped) for item in value]
    return value


_ROLLBACK_README = """v0.7.5 降级导出副本
生成时间：{stamp}
来源作品目录：{source}
导出模式：{mode}

请务必注意：
1. 本副本仅供旧版 v0.7.5 打开或修改；新版 v0.8+ 仍保留在原作品目录。
2. 严禁新旧两个版本同时打开同一作品目录，否则会互相覆盖正文、回执与版本索引。
3. 本副本不含 workbench.sqlite3、实时草稿、批注、检索索引等新版内部状态；
   如需回到新版，请使用原目录或升级前的快照。
4. 在旧版修改正文后，请先关闭旧版，再人工决定是否把修改合并回新版；本工具
   不做也不建议任何双向自动同步。
"""


def export_legacy(project, destination, mode: str = "current",
                  snapshot_dir=None, allowed_dir=None,
                  allowed_snapshot_roots=None) -> Dict[str, Any]:
    """导出 v0.7.5 可读的纯文件副本。

    ``mode``：

    * ``current`` —— 复制当前作品（回执原样保留新字段）；
    * ``snapshot`` —— 从 ``snapshot_dir``（升级前快照或 :func:`backup` 目录）复制；
    * ``clean`` —— 复制当前作品，并从回执中剔除新版专用键
      （``version_id`` / ``content_sha256`` / ``title_digest`` /
      ``version_fingerprint`` / ``author_confirmed``），保留 ``current`` 与
      ``sha256``，方便旧版安全读取。

    审计 C3-02：``allowed_dir`` 限制写目标，``allowed_snapshot_roots`` 限制
    ``snapshot_dir`` 的可读根；任意目录既不能当来源也不能当目标。

    本函数按白名单复制，绝不携带 ``workbench.sqlite3``、``.webnovel/transactions``
    或任何凭据文件。
    """
    if mode not in ("current", "snapshot", "clean"):
        raise ValueError(f"未知导出模式：{mode}")
    project_path = Path(project).resolve()
    if not project_path.is_dir():
        raise FileNotFoundError(f"作品目录不存在：{project_path}")
    if mode == "snapshot":
        if snapshot_dir is None:
            raise ValueError("snapshot 模式必须提供 snapshot_dir")
        source = Path(snapshot_dir)
        if not source.is_dir():
            raise FileNotFoundError(f"快照目录不存在：{source}")
        source = source.resolve()
        if allowed_snapshot_roots:
            roots = [Path(root) for root in allowed_snapshot_roots]
            if not any(_is_within(root, source) for root in roots):
                raise UnsafePath("snapshot_outside_allowed", str(source))
    else:
        source = project_path
    dest = Path(destination)
    if allowed_dir is not None and not _is_within(allowed_dir, dest):
        raise UnsafePath("destination_outside_allowed", str(dest))
    if _is_within(project_path, dest):
        raise UnsafePath("destination_inside_project", str(dest))
    if _is_within(source, dest):
        raise UnsafePath("destination_inside_source", str(dest))
    if dest.exists():
        if not dest.is_dir():
            raise FileExistsError(f"导出目标不是目录：{dest}")
        if any(dest.iterdir()):
            raise FileExistsError(f"导出目标必须为空：{dest}")
    dest.mkdir(parents=True, exist_ok=True)
    records: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    dropped: List[str] = []
    for name in ("正文", "大纲", "设定"):
        _copy_tree(source / name, dest, records, skipped=skipped, prefix=name)
    index, _ = _first_file(source, (".webnovel/chapter_versions/index.json",
                                    "chapter_versions/index.json"))
    if index is not None:
        _copy_single(index, dest / ".webnovel" / "chapter_versions" / "index.json",
                     ".webnovel/chapter_versions/index.json", records)
    objects, _ = _first_dir(source, (".webnovel/chapter_versions/objects",
                                     "chapter_versions/objects"))
    if objects is not None:
        _copy_tree(objects, dest, records, skipped=skipped,
                   prefix=".webnovel/chapter_versions/objects")
    receipts, _ = _first_file(source, (".webnovel/writer_receipts.json",
                                       "writer_receipts.json"))
    if receipts is not None:
        target = dest / ".webnovel" / "writer_receipts.json"
        if mode == "clean":
            try:
                raw = json.loads(receipts.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                raise TransactionConflict("receipts_invalid", str(exc)[:200]) from exc
            cleaned = _strip_receipt_keys(raw, dropped)
            data = _json_bytes(cleaned)
            _atomic_write_bytes(target, data)
            records.append({"path": ".webnovel/writer_receipts.json", "kind": "file",
                            "sha256": _sha256(data), "size": len(data)})
        else:
            _copy_single(receipts, target, ".webnovel/writer_receipts.json", records)
    for name in ("story_plan.json", "story_plan_meta.json", "state.json"):
        source_file, _ = _first_file(source, (f".webnovel/{name}", name))
        if source_file is not None:
            rel = f".webnovel/{name}"
            _copy_single(source_file, _join(dest, rel), rel, records)
    readme = dest / "ROLLBACK-README.txt"
    _atomic_write_bytes(readme, _ROLLBACK_README.format(
        stamp=_now(), source=str(source), mode=mode).encode("utf-8"))
    return {
        "destination": str(dest),
        "mode": mode,
        "source": str(source),
        "files": records,
        "count": len(records),
        "dropped_receipt_keys": len(dropped),
        "skipped": skipped,
        "readme": str(readme),
    }


# --------------------------------------------------------------------------- 不可变发布快照


def _snapshot_path(project, approval_id) -> Path:
    if not isinstance(approval_id, str):
        raise UnsafePath("invalid_approval_id")
    text = approval_id.strip()
    if not _SAFE_ID.match(text) or text in (".", ".."):
        raise UnsafePath("invalid_approval_id", str(approval_id))
    validate_windows_name(text)
    return Path(project) / ".publication" / "snapshots" / f"pub_{text}.json"


def _missing_snapshot_fields(record: Mapping[str, Any]) -> List[str]:
    missing: List[str] = []
    for field in PUBLICATION_FIELDS:
        value = record.get(field)
        if field == "chapter_number":
            try:
                valid = int(value) > 0
            except (TypeError, ValueError):
                valid = False
        else:
            valid = isinstance(value, str) and bool(value.strip())
        if not valid:
            missing.append(field)
    return missing


def write_publication_snapshot(project, snapshot) -> Path:
    """固化不可变发布快照到 ``.publication/snapshots/pub_{approval_id}.json``。

    写前强制核验 ``platform/account_id/.../approval_id`` 全部字段；同一
    ``approval_id`` 内容相同视为幂等，内容不同则拒绝覆盖（不可变快照）。
    """
    if not isinstance(snapshot, Mapping):
        raise TransactionConflict("snapshot_invalid", "快照必须是对象")
    missing = _missing_snapshot_fields(snapshot)
    if missing:
        raise TransactionConflict("snapshot_incomplete", ",".join(missing))
    approval_id = str(snapshot["approval_id"]).strip()
    record: Dict[str, Any] = {"format": 1}
    for field in PUBLICATION_FIELDS:
        if field == "approval_id":
            value = approval_id
        elif field == "chapter_number":
            value = int(snapshot[field])
        else:
            value = snapshot[field]
        record[field] = value
    path = _snapshot_path(project, approval_id)
    data = _json_bytes(record)
    if _create_bytes_exclusive(path, data):
        return path
    try:
        existing_bytes = path.read_bytes()
    except OSError as exc:
        raise TransactionConflict("snapshot_unreadable", str(exc)[:200]) from exc
    if existing_bytes == data:
        return path
    try:
        existing = json.loads(existing_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        existing = None
    if existing == record:
        return path
    raise TransactionConflict("snapshot_immutable", approval_id)


def verify_publication_snapshot(project, approval_id,
                                current_version_id: Optional[str] = None) -> Dict[str, Any]:
    """复验不可变快照；返回 ``{valid, reason, snapshot}``。

    ``current_version_id`` 给出时，若当前正式版本已演进，返回
    ``version_changed``，调用方应暂停排期并要求作者重新确认。
    """
    try:
        path = _snapshot_path(project, approval_id)
    except UnsafePath as exc:
        return {"approval_id": str(approval_id), "valid": False,
                "reason": "invalid_approval_id", "path": None, "snapshot": None,
                "detail": exc.code}
    result: Dict[str, Any] = {"approval_id": str(approval_id), "valid": False,
                              "reason": None, "path": str(path), "snapshot": None}
    if not path.is_file():
        result["reason"] = "snapshot_missing"
        return result
    try:
        record = _read_json(path)
    except (OSError, ValueError):
        result["reason"] = "snapshot_corrupt"
        return result
    if not isinstance(record, dict):
        result["reason"] = "snapshot_corrupt"
        return result
    result["snapshot"] = record
    missing = _missing_snapshot_fields(record)
    if missing:
        result["reason"] = "snapshot_incomplete"
        result["missing"] = missing
        return result
    if str(record.get("approval_id")) != str(approval_id).strip():
        result["reason"] = "approval_mismatch"
        return result
    if current_version_id is not None and str(record.get("version_id")) != str(current_version_id):
        result["reason"] = "version_changed"
        return result
    result["valid"] = True
    return result
