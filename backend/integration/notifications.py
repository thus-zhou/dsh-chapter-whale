"""通知子系统内核：故障事件、发件箱与通用 HTTPS Webhook 投递。

设计边界（接线前请先读这一段）：

- **纯库**：本模块只依赖标准库与 :mod:`integration.credential_codec`，不 import
  写作器、调度器或 bridge，因此**通知失败不会回滚章节、不会改调度状态**。
- **不递归告警**：通知自身的失败只写进 ``outbox`` 的 ``last_error`` / ``unknown``，
  绝不因为“通知发不出去”再产生一条通知。
- **只支持**：①本地事件列表（SQLite 持久化、可查询）；②通用 HTTPS Webhook（POST JSON）；
  ③测试发送（``test_send``，载荷带 ``test: true``）。
  飞书/钉钉/企业微信/Bark/Telegram 的签名与字段差异**未验证**，本模块不实现、也不声称支持。
- **隐私**：载荷只放别名、事件类型、时间与建议动作；正文、令牌、绝对路径一律不进载荷，
  ``_scrub`` 做兜底丢弃。收件地址与密钥只以掩码形式对外展示（``mask_url`` / ``redact_error``）。

发件箱状态机（``outbox.state``）：:

    pending ──claim──► leased ──2xx──────────► sent
       ▲                 ├──429/5xx/连接拒绝──► pending（按 next_attempt_at 退避）
       │                 ├──4xx（地址失效）───► dead（待处理，不删除）
       │                 ├──超时/连接中断─────► unknown（请求可能已到达，绝不自动重发）
       │                 └──租约过期且已尝试─► unknown（同上，保守处理）
       └──人工 requeue──── failed / dead / unknown

``unknown`` 只能由人工通过 ``resolve_unknown`` 落到 ``sent`` 或 ``failed``；
``failed`` 表示“人工确认没送达”，可以通过 ``requeue`` 重新排队。

时间：所有列存的都是带时区的 ISO8601（UTC，微秒精度），因此可以按字符串比较排序。
外部传入的 ``now`` 一律可注入，测试里不要真的 sleep。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import random
import re
import socket
import sqlite3
import subprocess
import time as time_module
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlsplit

try:  # 包内导入（unittest -t backend 时走这里）
    from . import credential_codec
except ImportError:  # pragma: no cover - 以脚本/扁平目录方式导入时的退路
    import credential_codec  # type: ignore[no-redef]

LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 1
"""当前库结构版本；``connect()`` 会把低版本库原地补齐到该版本。"""

MAX_BODY_BYTES = 64 * 1024
"""单次 Webhook 请求体上限（字节）。超限直接判死，不发请求。"""

REQUEST_TIMEOUT = 10
"""单跳 HTTP 超时（秒）。"""

MAX_REDIRECTS = 3
"""最多跟随的重定向跳数；每跳都重新校验 scheme 与 host。"""

BACKOFF_CAP = 3600
"""指数退避封顶（秒）。"""

EVENT_TYPES = (
    "job.paused",
    "review_exhausted",
    "publication.needs_check",
    "incident.resolved",
    "run.summary",
)
"""对外承诺的事件类型。新增类型必须同步文档与前端文案。"""

EVENT_TEST = "notification.test"
"""测试发送专用事件类型，不属于业务事件。"""

STATES = ("pending", "leased", "sent", "unknown", "failed", "dead")
"""发件箱状态全集。"""

VAULT_DIR_NAME = "notification-secrets"
"""无 DPAPI 时，收件地址与密钥落在库文件同级的该目录（0o700 + icacls 收紧）。"""

_SENSITIVE_KEY = re.compile(
    r"token|secret|password|authorization|cookie|api_key|content|body|text|draft|path|cwd",
    re.IGNORECASE,
)
_URL_IN_TEXT = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*)://([^\s\"'<>]+)")
_BEARER_IN_TEXT = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]+")
_QUERY_SECRET_IN_TEXT = re.compile(
    r"(?i)\b(token|secret|key|api_key|password|signature|authorization)=([^&\s]+)"
)
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
_PRIVATE_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_ACCEPTED_CODES = frozenset({200, 201, 202})
_DEAD_CODES = frozenset({400, 401, 403, 404, 405, 406, 410, 411, 413, 414, 415, 422})
_RETRYABLE_CLIENT_CODES = frozenset({408, 425, 429})
_UNSET = object()


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #


class NotificationError(RuntimeError):
    """通知子系统的可预期错误；消息直接面向作者，不要塞技术栈。"""


class UnsafeTarget(NotificationError):
    """收件地址或重定向目标不符合发送安全要求。"""


# --------------------------------------------------------------------------- #
# 版本、时间与序列化
# --------------------------------------------------------------------------- #


def _package_version() -> str:
    """从仓库根 package.json 读版本；读不到就退回 0.0.0（不抛错）。"""
    candidate = Path(__file__).resolve().parents[2] / "package.json"
    try:
        document = json.loads(candidate.read_text(encoding="utf-8"))
        version = document.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    except (OSError, ValueError):
        pass
    return "0.0.0"


VERSION = _package_version()
USER_AGENT = f"dsh-chapter-whale/{VERSION}"


def _now(value: Any = None) -> datetime:
    """统一成带时区的 UTC 时间；接受 None/datetime/时间戳/ISO8601 字符串。"""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, (int, float)):
        moment = datetime.fromtimestamp(float(value), timezone.utc)
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError as error:
            raise NotificationError("时间格式无法识别") from error
    else:
        raise NotificationError("时间参数类型无法识别")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(moment: Any) -> str:
    """落库用 ISO8601（UTC，微秒），保证字符串比较等价于时间比较。"""
    return _now(moment).isoformat(timespec="microseconds")


def _parse_iso(text: Any) -> Optional[datetime]:
    if not text:
        return None
    try:
        return _now(str(text))
    except NotificationError:
        return None


def _loads(text: Any, default: Any = None) -> Any:
    if not text:
        return default
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return default
    return default if value is None else value


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row(value: sqlite3.Row) -> Dict[str, Any]:
    return {key: value[key] for key in value.keys()}


def _idempotency(event_id: str, recipient_id: str) -> str:
    """同一条事件 × 同一个收件人 → 恒定幂等键（可安全外发到对端做去重）。"""
    return hashlib.sha256(f"{event_id}|{recipient_id}".encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# 脱敏
# --------------------------------------------------------------------------- #


def _scrub(payload: Any) -> Any:
    """递归丢弃敏感键（令牌、正文、路径……）；列表逐个处理，其他类型原样返回。"""
    if isinstance(payload, dict):
        cleaned: Dict[str, Any] = {}
        for key, value in payload.items():
            name = str(key)
            if _SENSITIVE_KEY.search(name):
                continue
            cleaned[name] = _scrub(value)
        return cleaned
    if isinstance(payload, (list, tuple)):
        return [_scrub(item) for item in payload]
    return payload


def mask_url(url: Any) -> str:
    """只保留 scheme 与 host 前 6 字符：``https://hooks…/••••``。"""
    parts = urlsplit(str(url or "").strip())
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if not scheme or not host:
        return "••••"
    prefix = host[:6]
    if prefix.endswith("."):
        prefix = prefix[:-1]
    return f"{scheme}://{prefix}…/••••"


def redact_error(text: Any) -> str:
    """抹掉错误文本里的 URL 查询串、userinfo、Bearer 令牌与常见凭据参数。"""
    value = str(text or "")

    def _clean(match: re.Match) -> str:
        scheme = match.group(1).lower()
        host = match.group(2).split("@")[-1]
        host = re.split(r"[/?#]", host)[0]
        return f"{scheme}://{host}/••••"

    value = _URL_IN_TEXT.sub(_clean, value)
    value = _BEARER_IN_TEXT.sub(r"\1••••", value)
    value = _QUERY_SECRET_IN_TEXT.sub(r"\1=••••", value)
    return value.strip()[:400]


def alias_mask(text: Any, label: str = "对象") -> str:
    """把书名/项目名折成稳定别名（``书-3f9a``），同一输入恒定同一别名。"""
    raw = str(text or "").strip()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:4]
    head = label.strip() or "对象"
    return f"{head}-{digest}"


# --------------------------------------------------------------------------- #
# 目标地址安全校验
# --------------------------------------------------------------------------- #


def _is_private_host(host: str) -> bool:
    """判断 host 是否落在回环/内网/保留地址；无法判定时按“公网”处理。"""
    if not host:
        return True
    if host in _LOOPBACK_HOSTS:
        return True
    if host.endswith(_PRIVATE_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def validate_url(url: Any, *, allow_loopback: bool = False, require_public: bool = False) -> str:
    """校验收件地址：只允许 https；http 仅限显式放行的本机回环。

    ``require_public=True`` 用于重定向落点：除 scheme 外，还必须不是内网/回环。
    """
    text = str(url or "").strip()
    if not text:
        raise UnsafeTarget("收件地址为空")
    parts = urlsplit(text)
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if not host:
        raise UnsafeTarget("收件地址缺少主机名")
    if parts.username or parts.password:
        raise UnsafeTarget("收件地址不能包含用户名或密码")
    private = _is_private_host(host)
    if scheme == "https":
        if require_public and private and not allow_loopback:
            raise UnsafeTarget("重定向目标指向内网或回环地址，已拒绝")
        return text
    if scheme == "http":
        if host in _LOOPBACK_HOSTS and allow_loopback:
            return text
        raise UnsafeTarget("只允许 https 收件地址；http 仅限显式允许的本机回环")
    raise UnsafeTarget(f"不支持的协议：{scheme or '空'}")


# --------------------------------------------------------------------------- #
# 库结构
# --------------------------------------------------------------------------- #


_DDL_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    event_type TEXT NOT NULL,
    job_id TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    book TEXT NOT NULL DEFAULT '',
    opened_at TEXT NOT NULL,
    resolved_at TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    sequence INTEGER NOT NULL DEFAULT 1,
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS incidents_open_fingerprint
    ON incidents(fingerprint) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS incidents_fingerprint_sequence
    ON incidents(fingerprint, sequence);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT REFERENCES incidents(id) ON DELETE SET NULL,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    delivery_state TEXT NOT NULL DEFAULT 'pending',
    dedupe TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS events_dedupe ON events(dedupe) WHERE dedupe <> '';
CREATE INDEX IF NOT EXISTS events_occurred ON events(occurred_at);

CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    event_idempotency TEXT NOT NULL DEFAULT '',
    recipient_id TEXT NOT NULL,
    recipient_masked TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending','leased','sent','unknown','failed','dead')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    lease_until TEXT,
    lease_owner TEXT,
    sent_at TEXT,
    response_code INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS outbox_event_recipient
    ON outbox(event_id, recipient_id);
CREATE INDEX IF NOT EXISTS outbox_state_next ON outbox(state, next_attempt_at);

CREATE TABLE IF NOT EXISTS recipients (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'webhook',
    masked TEXT NOT NULL DEFAULT '',
    url_blob TEXT NOT NULL DEFAULT '',
    secret_blob TEXT NOT NULL DEFAULT '',
    protection TEXT NOT NULL DEFAULT 'dpapi',
    vault_ref TEXT NOT NULL DEFAULT '',
    warning TEXT NOT NULL DEFAULT '',
    allow_loopback INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _db_file(db: sqlite3.Connection) -> Optional[Path]:
    for entry in db.execute("PRAGMA database_list"):
        if entry[1] == "main" and entry[2]:
            return Path(entry[2])
    return None


def _migrate(db: sqlite3.Connection) -> int:
    """幂等建表/升级；返回升级后的版本号。"""
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL)"
    )
    db.execute("INSERT OR IGNORE INTO schema_version (id, version) VALUES (1, 0)")
    current = int(db.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()[0])
    if current < SCHEMA_VERSION:
        db.executescript(_DDL_V1)
        db.execute("UPDATE schema_version SET version = ? WHERE id = 1", (SCHEMA_VERSION,))
        current = SCHEMA_VERSION
    if current > SCHEMA_VERSION:
        raise NotificationError(
            f"通知库结构版本 {current} 高于当前插件支持的 {SCHEMA_VERSION}，请升级插件后再试"
        )
    return current


def connect(path: Any) -> sqlite3.Connection:
    """打开（并初始化）通知库；建表与迁移幂等，可重复调用。

    沿用仓库既有做法：``sqlite3.connect(..., timeout=20)`` + ``row_factory``。
    这里额外关掉隐式事务（``isolation_level=None``），因为发件箱必须显式
    ``BEGIN IMMEDIATE`` 才能保证两个 worker 不重复取件。
    """
    target = str(path)
    if target != ":memory:":
        parent = Path(target).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)
        target = str(Path(target).expanduser().resolve())
    db = sqlite3.connect(target, timeout=20, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL").fetchone()
    except sqlite3.DatabaseError as error:  # 网络盘/只读盘等环境降级为默认日志模式
        LOGGER.warning("通知库无法启用 WAL：%s", redact_error(str(error)))
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=20000")
    _migrate(db)
    return db


@contextmanager
def _transaction(db: sqlite3.Connection, *, immediate: bool = False) -> Iterable[None]:
    """显式事务；已在事务里时退化为 SAVEPOINT，避免嵌套报错。"""
    nested = bool(getattr(db, "in_transaction", False))
    if nested:
        name = f"notification_{uuid.uuid4().hex[:8]}"
        db.execute(f"SAVEPOINT {name}")
        try:
            yield
        except BaseException:
            db.execute(f"ROLLBACK TO {name}")
            db.execute(f"RELEASE {name}")
            raise
        db.execute(f"RELEASE {name}")
        return
    db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield
    except BaseException:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")


# --------------------------------------------------------------------------- #
# 事件载荷
# --------------------------------------------------------------------------- #


def _ensure_event_type(event_type: Any) -> str:
    name = str(event_type or "").strip()
    if not name:
        raise NotificationError("事件类型不能为空")
    if name not in EVENT_TYPES and name != EVENT_TEST:
        raise NotificationError(f"未知的事件类型：{name}")
    return name


def _split_payload(payload: Any) -> Tuple[str, str, Optional[str], Dict[str, Any]]:
    """把调用方 payload 里的规范字段摘出来，其余作为附加信息保留。"""
    data = dict(payload) if isinstance(payload, dict) else {}
    reason = str(data.pop("reason", "") or "")
    next_action = str(data.pop("next_action", "") or "")
    chapter = data.pop("chapter_id", None)
    chapter_id = str(chapter) if chapter not in (None, "") else None
    return reason, next_action, chapter_id, data


def _build_payload(
    *,
    event_id: str,
    event_type: str,
    occurred_at: Any,
    job_id: str = "",
    project_alias: str = "",
    book_alias: str = "",
    chapter_id: Optional[str] = None,
    reason: str = "",
    next_action: str = "",
    sequence: int = 0,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造对外载荷；规范字段最后覆盖，保证调用方附加信息无法篡改它们。"""
    payload: Dict[str, Any] = dict(extra) if isinstance(extra, dict) else {}
    payload.update(
        {
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": _iso(occurred_at),
            "job_id": str(job_id or ""),
            "project_alias": str(project_alias or ""),
            "book_alias": str(book_alias or ""),
            "chapter_id": chapter_id or None,
            "reason": str(reason or ""),
            "next_action": str(next_action or ""),
            "sequence": int(sequence or 0),
        }
    )
    return _scrub(payload)


def _fingerprint(
    event_type: str, job_id: str, project_alias: str, book_alias: str, chapter_id: Optional[str]
) -> str:
    """``sha256(event_type + job_id + 关键对象)``，关键对象=项目别名+书名别名+章节。"""
    material = "|".join(
        [
            str(event_type),
            str(job_id or ""),
            str(project_alias or ""),
            str(book_alias or ""),
            str(chapter_id or ""),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _ensure_event(
    db: sqlite3.Connection,
    *,
    incident_id: Optional[str],
    event_type: str,
    occurred_at: Any,
    payload: Dict[str, Any],
    dedupe: str,
    event_id: Optional[str] = None,
) -> Dict[str, Any]:
    """幂等写入事件；同一 dedupe 键永远复用同一条事件（同一 event_id）。"""
    if dedupe:
        existing = db.execute("SELECT * FROM events WHERE dedupe = ?", (dedupe,)).fetchone()
        if existing is not None:
            return _row(existing)
    identity = event_id or str(uuid.uuid4())
    db.execute(
        "INSERT OR IGNORE INTO events (incident_id, event_id, event_type, occurred_at, payload, delivery_state, dedupe)"
        " VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (incident_id, identity, event_type, _iso(occurred_at), _dumps(payload), dedupe),
    )
    stored = db.execute("SELECT * FROM events WHERE event_id = ?", (identity,)).fetchone()
    if stored is None:  # pragma: no cover - 只有并发写坏 dedupe 才会走到
        raise NotificationError("事件写入后无法读回")
    return _row(stored)


# --------------------------------------------------------------------------- #
# 故障（incident）
# --------------------------------------------------------------------------- #


def open_incident(
    db: sqlite3.Connection,
    event_type: str,
    job_id: str,
    project_alias: str,
    book_alias: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    now: Any = None,
    chapter_id: Optional[str] = None,
) -> Dict[str, Any]:
    """开一个故障；同 fingerprint 已有打开中的故障则复用（``deduplicated=True``）。

    恢复后再发生才新建一条，并把 ``sequence`` 加一。重复失败只保留一条事件，
    因此 ``event_id`` 恒定，重试不会在发件箱里长出新行。
    """
    name = _ensure_event_type(event_type)
    moment = _now(now)
    reason, next_action, chapter, extra = _split_payload(payload)
    chapter = chapter_id or chapter
    fingerprint = _fingerprint(name, job_id, project_alias, book_alias, chapter)

    with _transaction(db, immediate=True):
        existing = db.execute(
            "SELECT * FROM incidents WHERE fingerprint = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (fingerprint,),
        ).fetchone()
        if existing is not None:
            incident = _row(existing)
            event = _ensure_event(
                db,
                incident_id=incident["id"],
                event_type=incident["event_type"],
                occurred_at=incident["opened_at"],
                payload=_loads(incident["payload"], {}),
                dedupe=f"incident:{incident['id']}:{incident['event_type']}",
            )
            result = dict(incident)
            result.update(
                {
                    "incident_id": incident["id"],
                    "event_id": event["event_id"],
                    "event": event,
                    "deduplicated": True,
                    "payload": _loads(incident["payload"], {}),
                }
            )
            return result

        sequence = int(
            db.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM incidents WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()[0]
        ) + 1
        incident_id = f"inc_{uuid.uuid4().hex[:16]}"
        event_id = str(uuid.uuid4())
        body = _build_payload(
            event_id=event_id,
            event_type=name,
            occurred_at=moment,
            job_id=job_id,
            project_alias=project_alias,
            book_alias=book_alias,
            chapter_id=chapter,
            reason=reason,
            next_action=next_action,
            sequence=sequence,
            extra=extra,
        )
        db.execute(
            "INSERT INTO incidents (id, fingerprint, event_type, job_id, project, book, opened_at,"
            " resolved_at, status, sequence, payload) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'open', ?, ?)",
            (
                incident_id,
                fingerprint,
                name,
                str(job_id or ""),
                str(project_alias or ""),
                str(book_alias or ""),
                _iso(moment),
                sequence,
                _dumps(body),
            ),
        )
        event = _ensure_event(
            db,
            incident_id=incident_id,
            event_type=name,
            occurred_at=moment,
            payload=body,
            dedupe=f"incident:{incident_id}:{name}",
            event_id=event_id,
        )
        return {
            "id": incident_id,
            "incident_id": incident_id,
            "fingerprint": fingerprint,
            "event_type": name,
            "job_id": str(job_id or ""),
            "project": str(project_alias or ""),
            "book": str(book_alias or ""),
            "opened_at": _iso(moment),
            "resolved_at": None,
            "status": "open",
            "sequence": sequence,
            "event_id": event["event_id"],
            "event": event,
            "deduplicated": False,
            "payload": body,
        }


def resolve_incident(
    db: sqlite3.Connection, incident_id: str, note: str = "", *, now: Any = None
) -> Dict[str, Any]:
    """把故障标记为已恢复；``note`` 只以脱敏形式写进载荷。"""
    moment = _now(now)
    if not incident_id:
        raise NotificationError("故障编号不能为空")
    with _transaction(db, immediate=True):
        current = db.execute("SELECT * FROM incidents WHERE id = ?", (str(incident_id),)).fetchone()
        if current is None:
            raise NotificationError("故障记录不存在")
        incident = _row(current)
        if incident["status"] == "resolved":
            result = dict(incident)
            result.update({"incident_id": incident["id"], "resolved": False, "already": True})
            return result
        payload = _loads(incident["payload"], {})
        if note:
            payload["resolution_note"] = str(note)
        payload = _scrub(payload)
        db.execute(
            "UPDATE incidents SET status = 'resolved', resolved_at = ?, payload = ? WHERE id = ?",
            (_iso(moment), _dumps(payload), incident["id"]),
        )
        incident.update({"status": "resolved", "resolved_at": _iso(moment)})
        incident["payload"] = payload
    result = dict(incident)
    result.update({"incident_id": incident["id"], "resolved": True, "already": False})
    return result


def list_incidents(
    db: sqlite3.Connection,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """本地故障列表（按最近打开倒序），载荷已解析。"""
    statement = "SELECT * FROM incidents"
    params: List[Any] = []
    if status:
        statement += " WHERE status = ?"
        params.append(str(status))
    statement += " ORDER BY opened_at DESC, rowid DESC LIMIT ?"
    params.append(max(1, int(limit)))
    result = []
    for entry in db.execute(statement, params):
        item = _row(entry)
        item["payload"] = _loads(item.get("payload"), {})
        result.append(item)
    return result


# --------------------------------------------------------------------------- #
# 事件与发件箱入队
# --------------------------------------------------------------------------- #


def _refresh_event_state(db: sqlite3.Connection, event_id: str) -> str:
    states = {
        entry[0] for entry in db.execute("SELECT state FROM outbox WHERE event_id = ?", (event_id,)).fetchall()
    }
    if not states:
        state = "pending"
    elif states <= {"sent"}:
        state = "sent"
    elif states & {"dead", "failed"}:
        state = "failed"
    elif "unknown" in states:
        state = "unknown"
    elif "leased" in states:
        state = "pending"
    else:
        state = "pending"
    db.execute("UPDATE events SET delivery_state = ? WHERE event_id = ?", (state, event_id))
    return state


def _resolve_recipients(db: sqlite3.Connection, recipients: Any) -> List[Dict[str, Any]]:
    """收件人既可以是收件配置字典，也可以是 id 字符串。"""
    if recipients is None:
        return []
    if isinstance(recipients, (str, bytes)):
        items: Sequence[Any] = [recipients]
    elif isinstance(recipients, dict):
        items = [recipients]
    else:
        items = list(recipients)
    resolved: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            identity = str(item.get("id") or "").strip()
            masked = str(item.get("masked") or "").strip()
            if not identity:
                raise NotificationError("收件配置缺少 id")
        else:
            identity = str(item or "").strip()
            masked = ""
            if not identity:
                raise NotificationError("收件配置缺少 id")
        if not masked:
            stored = db.execute("SELECT masked FROM recipients WHERE id = ?", (identity,)).fetchone()
            masked = str(stored["masked"]) if stored is not None else identity
        resolved.append({"id": identity, "masked": masked})
    return resolved


def enqueue(
    db: sqlite3.Connection,
    incident_id: Optional[str],
    event_type: str,
    payload: Optional[Dict[str, Any]],
    recipients: Any,
    *,
    now: Any = None,
    dedupe_key: str = "",
    event_id: Optional[str] = None,
    store_without_recipients: bool = False,
) -> List[Dict[str, Any]]:
    """把一条事件排进发件箱：每个收件人一行，``(event_id, recipient_id)`` 唯一。

    重复调用返回既有行（不新增），重试永远更新同一行并复用同一个 ``event_id``。
    ``dedupe_key`` 用于没有故障归属的独立事件（例如 ``run.summary``）：同一个键
    重复入队仍然只有一条事件。
    ``store_without_recipients`` 供本地事件列表使用：没有配置收件人时仍写入
    ``events``（不发任何请求、不产生 ``outbox`` 行），默认关闭以保持“没配收件人
    就不建事件”的旧行为。
    """
    name = _ensure_event_type(event_type)
    moment = _now(now)
    incident: Optional[Dict[str, Any]] = None
    if incident_id:
        found = db.execute("SELECT * FROM incidents WHERE id = ?", (str(incident_id),)).fetchone()
        if found is None:
            raise NotificationError("故障记录不存在")
        incident = _row(found)
    reason, next_action, chapter, extra = _split_payload(payload)
    if incident is not None:
        chapter = chapter or (_loads(incident["payload"], {}) or {}).get("chapter_id")
    targets = _resolve_recipients(db, recipients)
    if not targets and not store_without_recipients:
        return []

    if incident is not None:
        dedupe = f"incident:{incident['id']}:{name}"
    elif dedupe_key:
        dedupe = f"key:{dedupe_key}:{name}"
    else:
        dedupe = ""

    identity = str(event_id or uuid.uuid4())
    with _transaction(db, immediate=True):
        body = _build_payload(
            event_id=identity,
            event_type=name,
            occurred_at=moment,
            job_id=(incident or {}).get("job_id", ""),
            project_alias=(incident or {}).get("project", ""),
            book_alias=(incident or {}).get("book", ""),
            chapter_id=chapter,
            reason=reason,
            next_action=next_action,
            sequence=int((incident or {}).get("sequence") or 0),
            extra=extra,
        )
        event = _ensure_event(
            db,
            incident_id=(incident or {}).get("id"),
            event_type=name,
            occurred_at=moment,
            payload=body,
            dedupe=dedupe,
            event_id=identity,
        )
        stable_event = str(event["event_id"])
        if _loads(event["payload"], {}).get("event_id") != stable_event:
            # 复用已有事件时以库里的 event_id 为准，保证重试恒等。
            stored = _loads(event["payload"], {})
            stored["event_id"] = stable_event
            db.execute("UPDATE events SET payload = ? WHERE event_id = ?", (_dumps(stored), stable_event))
            event["payload"] = _dumps(stored)
        stamp = _iso(moment)
        for target in targets:
            db.execute(
                "INSERT OR IGNORE INTO outbox (event_id, event_idempotency, recipient_id, recipient_masked,"
                " state, attempts, next_attempt_at, last_error, updated_at, created_at)"
                " VALUES (?, ?, ?, ?, 'pending', 0, ?, '', ?, ?)",
                (
                    stable_event,
                    _idempotency(stable_event, target["id"]),
                    target["id"],
                    target["masked"],
                    stamp,
                    stamp,
                    stamp,
                ),
            )
        rows = db.execute(
            "SELECT * FROM outbox WHERE event_id = ? AND recipient_id IN (%s) ORDER BY id"
            % ",".join("?" for _ in targets),
            (stable_event, *[target["id"] for target in targets]),
        ).fetchall()
        _refresh_event_state(db, stable_event)
        return [_row(entry) for entry in rows]


# --------------------------------------------------------------------------- #
# 取件
# --------------------------------------------------------------------------- #


def recover_stale_leases(db: sqlite3.Connection, *, now: Any = None) -> Dict[str, int]:
    """处理过期租约：已尝试过的转 ``unknown``，从未尝试的退回 ``pending``。

    “尝试过”意味着请求可能已经到达对端，因此只能人工确认，绝不自动重发。
    """
    moment = _now(now)
    unknown = 0
    requeued = 0
    with _transaction(db, immediate=True):
        stale = db.execute(
            "SELECT * FROM outbox WHERE state = 'leased' AND lease_until IS NOT NULL AND lease_until <= ?",
            (_iso(moment),),
        ).fetchall()
        for entry in stale:
            item = _row(entry)
            if int(item["attempts"] or 0) > 0:
                db.execute(
                    "UPDATE outbox SET state = 'unknown', lease_owner = NULL, lease_until = NULL,"
                    " last_error = ?, updated_at = ? WHERE id = ?",
                    ("租约过期：请求可能已到达对端，等待人工确认", _iso(moment), item["id"]),
                )
                _refresh_event_state(db, item["event_id"])
                unknown += 1
            else:
                db.execute(
                    "UPDATE outbox SET state = 'pending', lease_owner = NULL, lease_until = NULL,"
                    " updated_at = ? WHERE id = ?",
                    (_iso(moment), item["id"]),
                )
                requeued += 1
    return {"unknown": unknown, "requeued": requeued}


def claim(
    db: sqlite3.Connection,
    owner: str,
    limit: int = 20,
    lease_seconds: int = 60,
    *,
    now: Any = None,
) -> List[Dict[str, Any]]:
    """短租约取件：``BEGIN IMMEDIATE`` 内把到期的 ``pending`` 置为 ``leased``。

    两个 worker 同时取件时只会有一个拿到某一行；过期租约按“已尝试→unknown、
    未尝试→pending”处理，因此崩溃留下的记录既能被重新取件，也不会被盲目重发。
    """
    moment = _now(now)
    token = str(owner or "").strip() or f"worker-{os.getpid()}"
    lease_until = _iso(moment + timedelta(seconds=max(1, int(lease_seconds))))
    limit = max(1, int(limit))
    recover_stale_leases(db, now=moment)
    with _transaction(db, immediate=True):
        candidates = db.execute(
            "SELECT id FROM outbox WHERE state = 'pending' AND next_attempt_at <= ?"
            " ORDER BY next_attempt_at, id LIMIT ?",
            (_iso(moment), limit),
        ).fetchall()
        identities = [entry[0] for entry in candidates]
        if not identities:
            return []
        if sqlite3.sqlite_version_info >= (3, 35):
            rows = db.execute(
                "UPDATE outbox SET state = 'leased', lease_owner = ?, lease_until = ?, updated_at = ?"
                " WHERE id IN (%s) AND state = 'pending' RETURNING *"
                % ",".join("?" for _ in identities),
                (token, lease_until, _iso(moment), *identities),
            ).fetchall()
        else:  # pragma: no cover - 老运行时退路
            db.executemany(
                "UPDATE outbox SET state = 'leased', lease_owner = ?, lease_until = ?, updated_at = ?"
                " WHERE id = ? AND state = 'pending'",
                [(token, lease_until, _iso(moment), identity) for identity in identities],
            )
            rows = db.execute(
                "SELECT * FROM outbox WHERE lease_owner = ? AND lease_until = ? ORDER BY id",
                (token, lease_until),
            ).fetchall()
        return [_row(entry) for entry in rows]


# --------------------------------------------------------------------------- #
# 凭据保护：DPAPI 优先，失败降级为受 ACL 保护的明文文件
# --------------------------------------------------------------------------- #


_CODEC_CACHE: Any = _UNSET


def _dpapi_pair() -> Optional[Tuple[Callable[[bytes], bytes], Callable[[bytes], bytes]]]:
    """返回 DPAPI 加解密函数对；不可用时返回 None（不抛错，结果缓存）。"""
    global _CODEC_CACHE
    if _CODEC_CACHE is not _UNSET:
        return _CODEC_CACHE
    try:
        available = bool(credential_codec.probe())
    except BaseException:  # pragma: no cover - 探针本身在非 Windows 上会直接返回 False
        available = False
    if not available:
        _CODEC_CACHE = None
        return None
    _CODEC_CACHE = (
        lambda raw: credential_codec.transform(raw, True),
        lambda raw: credential_codec.transform(raw, False),
    )
    return _CODEC_CACHE


def _harden(path: Path, *, directory: bool = False) -> Tuple[bool, str]:
    """收紧权限：Windows 用 icacls，其他系统用 0o700/0o600。失败只记录不阻断。"""
    if os.name != "nt":
        try:
            os.chmod(path, 0o700 if directory else 0o600)
            return True, ""
        except OSError as error:
            return False, f"无法收紧权限：{error}"
    try:
        import getpass

        user = getpass.getuser()
        grant = f"{user}:(OI)(CI)F" if directory else f"{user}:(F)"
        result = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", grant],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return False, "icacls 未能收紧权限，收件配置改为按继承权限保存"
        return True, ""
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"icacls 执行失败：{error}"


def _vault_dir(db: sqlite3.Connection) -> Path:
    source = _db_file(db)
    if source is None:
        raise NotificationError("通知库必须使用文件路径，才能保存收件地址")
    folder = source.parent / VAULT_DIR_NAME
    created = not folder.exists()
    folder.mkdir(parents=True, exist_ok=True)
    if created:
        _harden(folder, directory=True)
    return folder


def _write_vault_file(db: sqlite3.Connection, recipient_id: str, values: Dict[str, str]) -> Tuple[str, str]:
    folder = _vault_dir(db)
    name = f"{recipient_id}.json"
    path = folder / name
    temporary = path.with_name(f"{name}.{os.getpid()}.tmp")
    temporary.write_text(_dumps({"schema_version": 1, "values": values}), encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    ok, warning = _harden(path)
    if not ok:
        LOGGER.warning("收件配置权限收紧失败：%s", warning)
    return name, warning


def _read_vault_file(db: sqlite3.Connection, name: str) -> Dict[str, str]:
    if not name:
        return {}
    path = _vault_dir(db) / name
    try:
        document = _loads(path.read_text(encoding="utf-8"), {})
    except OSError:
        return {}
    values = document.get("values") if isinstance(document, dict) else None
    return {str(key): str(value) for key, value in values.items()} if isinstance(values, dict) else {}


def _store_material(
    db: sqlite3.Connection,
    recipient_id: str,
    url: str,
    secret: Optional[str],
    pair: Optional[Tuple[Callable[[bytes], bytes], Callable[[bytes], bytes]]],
) -> Dict[str, Any]:
    """把地址与密钥写进库里（DPAPI 密文）或受保护文件（降级）。"""
    if pair is not None:
        encrypt, _ = pair
        url_blob = "dpapi:" + base64.b64encode(encrypt(url.encode("utf-8"))).decode("ascii")
        secret_blob = (
            "dpapi:" + base64.b64encode(encrypt(secret.encode("utf-8"))).decode("ascii") if secret else ""
        )
        return {
            "url_blob": url_blob,
            "secret_blob": secret_blob,
            "protection": "dpapi",
            "vault_ref": "",
            "warning": "",
        }
    values = {"url": url}
    if secret:
        values["secret"] = secret
    reference, warning = _write_vault_file(db, recipient_id, values)
    LOGGER.warning("当前系统没有可用的凭据保护，收件地址以受 ACL 保护的明文保存")
    return {
        "url_blob": "",
        "secret_blob": "",
        "protection": "plaintext-acl",
        "vault_ref": reference,
        "warning": warning or "当前系统无凭据保护，收件地址以受 ACL 保护的明文保存",
    }


def _load_material(
    db: sqlite3.Connection,
    record: Dict[str, Any],
    pair: Optional[Tuple[Callable[[bytes], bytes], Callable[[bytes], bytes]]],
) -> Dict[str, str]:
    if record.get("protection") == "dpapi":
        if pair is None:
            return {}
        _, decrypt = pair
        values: Dict[str, str] = {}
        for field, column in (("url", "url_blob"), ("secret", "secret_blob")):
            blob = str(record.get(column) or "")
            if not blob.startswith("dpapi:"):
                continue
            try:
                values[field] = decrypt(base64.b64decode(blob[6:])).decode("utf-8")
            except BaseException as error:
                LOGGER.warning("收件配置无法解密：%s", redact_error(str(error)))
        return values
    return _read_vault_file(db, str(record.get("vault_ref") or ""))


def _public_recipient(record: Dict[str, Any]) -> Dict[str, Any]:
    """对外可见的收件配置：只有掩码，绝无明文地址与密钥。"""
    return {
        "id": record.get("id", ""),
        "kind": record.get("kind", "webhook"),
        "masked": record.get("masked", ""),
        "enabled": bool(record.get("enabled")),
        "protection": record.get("protection", "dpapi"),
        "allow_loopback": bool(record.get("allow_loopback")),
        "warning": record.get("warning", ""),
        "created_at": record.get("created_at", ""),
        "updated_at": record.get("updated_at", ""),
    }


def add_recipient(
    db: sqlite3.Connection,
    url: str,
    secret: Optional[str] = None,
    *,
    kind: str = "webhook",
    allow_loopback: bool = False,
    now: Any = None,
    codec_pair: Any = _UNSET,
) -> Dict[str, Any]:
    """新增（或更新）一条收件配置；只返回掩码，永不回显明文。"""
    text = validate_url(url, allow_loopback=allow_loopback)
    moment = _iso(_now(now))
    identity = "rcp_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    pair = _dpapi_pair() if codec_pair is _UNSET else codec_pair
    material = _store_material(db, identity, text, (secret or None), pair)
    masked = mask_url(text)
    with _transaction(db, immediate=True):
        existing = db.execute("SELECT * FROM recipients WHERE id = ?", (identity,)).fetchone()
        if existing is None:
            db.execute(
                "INSERT INTO recipients (id, kind, masked, url_blob, secret_blob, protection, vault_ref,"
                " warning, allow_loopback, enabled, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    identity,
                    str(kind or "webhook"),
                    masked,
                    material["url_blob"],
                    material["secret_blob"],
                    material["protection"],
                    material["vault_ref"],
                    material["warning"],
                    1 if allow_loopback else 0,
                    moment,
                    moment,
                ),
            )
        else:
            db.execute(
                "UPDATE recipients SET kind = ?, masked = ?, url_blob = ?, secret_blob = ?, protection = ?,"
                " vault_ref = ?, warning = ?, allow_loopback = ?, enabled = 1, updated_at = ? WHERE id = ?",
                (
                    str(kind or "webhook"),
                    masked,
                    material["url_blob"],
                    material["secret_blob"],
                    material["protection"],
                    material["vault_ref"],
                    material["warning"],
                    1 if allow_loopback else 0,
                    moment,
                    identity,
                ),
            )
        stored = db.execute("SELECT * FROM recipients WHERE id = ?", (identity,)).fetchone()
    return _public_recipient(_row(stored))


def list_recipients(db: sqlite3.Connection) -> List[Dict[str, Any]]:
    """列出收件配置（只有掩码）；解析失败时 ``available`` 为 False。"""
    result = []
    for entry in db.execute("SELECT * FROM recipients ORDER BY created_at, id"):
        record = _row(entry)
        item = _public_recipient(record)
        item["available"] = bool(record.get("protection")) and record.get("enabled") == 1
        result.append(item)
    return result


def disable_recipient(db: sqlite3.Connection, recipient_id: str, *, now: Any = None) -> Dict[str, Any]:
    """停用一条收件配置（不删除历史发件记录）。"""
    moment = _iso(_now(now))
    with _transaction(db, immediate=True):
        found = db.execute("SELECT * FROM recipients WHERE id = ?", (str(recipient_id),)).fetchone()
        if found is None:
            raise NotificationError("收件配置不存在")
        db.execute("UPDATE recipients SET enabled = 0, updated_at = ? WHERE id = ?", (moment, str(recipient_id)))
        stored = db.execute("SELECT * FROM recipients WHERE id = ?", (str(recipient_id),)).fetchone()
    item = _public_recipient(_row(stored))
    item["disabled"] = True
    return item


def _recipient_material(
    db: sqlite3.Connection,
    recipient: Any,
    *,
    codec_pair: Any = _UNSET,
) -> Dict[str, Any]:
    """取投递所需的明文（仅进程内内存使用，绝不写日志、绝不返回给界面）。"""
    if isinstance(recipient, (str, bytes)):
        data: Dict[str, Any] = {"id": str(recipient)}
    elif isinstance(recipient, dict):
        data = dict(recipient)
    else:
        raise NotificationError("收件配置格式无法识别")
    if data.get("url"):
        data.setdefault("secret", "")
        return data
    identity = str(data.get("id") or "")
    if not identity:
        raise NotificationError("收件配置缺少 id")
    stored = db.execute("SELECT * FROM recipients WHERE id = ?", (identity,)).fetchone()
    if stored is None:
        raise NotificationError("收件配置不存在")
    record = _row(stored)
    if not record.get("enabled"):
        raise NotificationError("收件配置已停用")
    pair = _dpapi_pair() if codec_pair is _UNSET else codec_pair
    material = _load_material(db, record, pair)
    if not material.get("url"):
        raise NotificationError("收件配置无法解密，请重新填写收件地址")
    data.update(
        {
            "id": identity,
            "url": material["url"],
            "secret": material.get("secret") or "",
            "masked": record.get("masked") or data.get("masked") or "",
            "kind": record.get("kind") or "webhook",
            "allow_loopback": bool(record.get("allow_loopback")),
        }
    )
    return data


# --------------------------------------------------------------------------- #
# HTTP 投递
# --------------------------------------------------------------------------- #


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """不自动跟随重定向：把 3xx 原样交回调用方，由我们逐跳校验 scheme 与 host。"""

    def _passthrough(self, req, fp, code, msg, headers):  # noqa: D401 - urllib 钩子
        return fp

    http_error_301 = _passthrough
    http_error_302 = _passthrough
    http_error_303 = _passthrough
    http_error_307 = _passthrough
    http_error_308 = _passthrough


_OPENER: Optional[urllib.request.OpenerDirector] = None


def _default_opener() -> urllib.request.OpenerDirector:
    global _OPENER
    if _OPENER is None:
        _OPENER = urllib.request.build_opener(_NoRedirectHandler())
    return _OPENER


def _header(headers: Any, name: str) -> Optional[str]:
    if headers is None:
        return None
    for candidate in (name, name.lower(), name.title()):
        try:
            value = headers.get(candidate)
        except AttributeError:
            return None
        if value:
            return str(value)
    return None


def _encode(envelope: Dict[str, Any]) -> bytes:
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _envelope(payload: Dict[str, Any], recipient: Dict[str, Any], idempotency: str) -> Dict[str, Any]:
    """webhook 外层信封；``body`` 只出现在这一层，不进入业务载荷。"""
    envelope = {
        "schema": SCHEMA_VERSION,
        "source": "dsh-chapter-whale",
        "version": VERSION,
        "event_id": payload.get("event_id", ""),
        "event_type": payload.get("event_type", ""),
        "occurred_at": payload.get("occurred_at", ""),
        "idempotency": idempotency,
        "recipient": recipient.get("masked", ""),
        "body": payload,
    }
    if payload.get("test") is True:
        envelope["test"] = True
    return envelope


def _build_request(url: str, body: bytes, envelope: Dict[str, Any], secret: str) -> urllib.request.Request:
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", "application/json")
    request.add_header("X-ChapterWhale-Event", str(envelope.get("event_type", "")))
    request.add_header("X-ChapterWhale-Event-Id", str(envelope.get("event_id", "")))
    request.add_header("X-ChapterWhale-Idempotency", str(envelope.get("idempotency", "")))
    if secret:
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        request.add_header("X-ChapterWhale-Signature", f"sha256={signature}")
        request.add_header("X-ChapterWhale-Timestamp", str(int(time_module.time())))
    return request


def _read_body(response: Any) -> str:
    try:
        raw = response.read(65536)
    except BaseException:  # pragma: no cover - 对端提前断开
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw or "")


def _close(response: Any) -> None:
    closer = getattr(response, "close", None)
    if callable(closer):
        try:
            closer()
        except BaseException:  # pragma: no cover - 关闭失败无关紧要
            pass


def _send(
    recipient: Dict[str, Any],
    body: bytes,
    envelope: Dict[str, Any],
    *,
    opener: Any = None,
    allow_loopback: bool = False,
    sleeper: Optional[Callable[[float], Any]] = None,
    now: Any = None,
) -> Dict[str, Any]:
    """发一跳或按重定向发多跳；返回 ``{"status", "kind", "error", "retry_after"}``。

    ``kind`` 取值：``response`` / ``timeout`` / ``reset`` / ``refused`` / ``error``。
    """
    url = str(recipient.get("url") or "")
    secret = str(recipient.get("secret") or "")
    runner = opener or _default_opener()
    loopback_allowed = bool(allow_loopback or recipient.get("allow_loopback"))
    clock = _now(now)
    validate_url(url, allow_loopback=loopback_allowed)
    current = url
    if sleeper is not None:
        sleeper(0)  # 只为兼容调度器注入；退避一律靠 next_attempt_at，从不在进程里睡眠
    for hop in range(MAX_REDIRECTS + 1):
        if hop:
            validate_url(current, allow_loopback=loopback_allowed, require_public=True)
        request = _build_request(current, body, envelope, secret)
        try:
            response = runner(request, timeout=REQUEST_TIMEOUT)
        except urllib.error.HTTPError as error:
            response = error
        except (socket.timeout, TimeoutError) as error:
            return {"status": None, "kind": "timeout", "error": f"请求超时：{error}", "retry_after": None}
        except urllib.error.URLError as error:
            reason = getattr(error, "reason", error)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                return {"status": None, "kind": "timeout", "error": f"请求超时：{reason}", "retry_after": None}
            if isinstance(reason, socket.gaierror):
                return {"status": None, "kind": "refused", "error": "解析不到收件地址的主机", "retry_after": None}
            if isinstance(reason, ConnectionRefusedError):
                return {"status": None, "kind": "refused", "error": "对端拒绝连接", "retry_after": None}
            if isinstance(reason, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
                return {"status": None, "kind": "reset", "error": "连接中断，响应可能丢失", "retry_after": None}
            return {"status": None, "kind": "error", "error": str(reason), "retry_after": None}
        except ConnectionRefusedError as error:
            return {"status": None, "kind": "refused", "error": f"对端拒绝连接：{error}", "retry_after": None}
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as error:
            return {"status": None, "kind": "reset", "error": f"连接中断，响应可能丢失：{error}", "retry_after": None}
        except UnsafeTarget:
            raise
        except Exception as error:  # 未知异常按“可能已到达”处理，宁可人工确认
            return {"status": None, "kind": "error", "error": f"{error.__class__.__name__}: {error}", "retry_after": None}

        status = getattr(response, "status", None)
        if status is None:
            status = getattr(response, "code", None)
        headers = getattr(response, "headers", None)
        try:
            status_code = int(status) if status is not None else None
        except (TypeError, ValueError):
            status_code = None
        if status_code in _REDIRECT_CODES:
            location = _header(headers, "Location")
            _close(response)
            if not location:
                return {"status": status_code, "kind": "response", "error": "重定向缺少目标地址", "retry_after": None}
            if hop >= MAX_REDIRECTS:
                return {
                    "status": status_code,
                    "kind": "response",
                    "error": f"重定向超过 {MAX_REDIRECTS} 跳，已停止",
                    "retry_after": None,
                }
            current = urljoin(current, location)
            continue
        snippet = redact_error(_read_body(response))
        _close(response)
        return {
            "status": status_code,
            "kind": "response",
            "error": snippet,
            "retry_after": parse_retry_after(_header(headers, "Retry-After"), clock),
        }
    return {"status": None, "kind": "response", "error": f"重定向超过 {MAX_REDIRECTS} 跳，已停止", "retry_after": None}


def parse_retry_after(value: Any, now: Any = None) -> Optional[float]:
    """解析 ``Retry-After``：秒数或 HTTP 日期都支持；无法识别返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    moment = _now(now)
    if text.isdigit():
        return float(min(int(text), 86400))
    try:
        moment_target = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if moment_target.tzinfo is None:
        moment_target = moment_target.replace(tzinfo=timezone.utc)
    seconds = (moment_target.astimezone(timezone.utc) - moment).total_seconds()
    return float(min(max(seconds, 0.0), 86400))


def backoff_delay(attempts: int, rng: Callable[[], float] = random.random) -> float:
    """指数退避：``2**attempts`` 秒，封顶 1 小时，叠加 0..20% 抖动。"""
    try:
        count = max(1, int(attempts))
    except (TypeError, ValueError):
        count = 1
    base = float(min(BACKOFF_CAP, 2 ** min(count, 20)))
    jitter = float(rng()) * 0.2
    return float(min(float(BACKOFF_CAP), base * (1.0 + jitter)))


# --------------------------------------------------------------------------- #
# 投递与结算
# --------------------------------------------------------------------------- #


def _reload_outbox(db: sqlite3.Connection, row: Any) -> Dict[str, Any]:
    identity = row.get("id") if isinstance(row, dict) else row["id"]
    if identity is None:
        raise NotificationError("发件记录缺少 id")
    found = db.execute("SELECT * FROM outbox WHERE id = ?", (int(identity),)).fetchone()
    if found is None:
        raise NotificationError("发件记录不存在")
    return _row(found)


def _settle(
    db: sqlite3.Connection,
    record: Dict[str, Any],
    state: str,
    moment: datetime,
    *,
    error: str = "",
    response_code: Optional[int] = None,
    delay: Optional[float] = None,
) -> Dict[str, Any]:
    """写终态/中间态并刷新事件投递状态；返回对外结果字典。"""
    if state not in STATES:
        raise NotificationError(f"未知的发件状态：{state}")
    stamp = _iso(moment)
    values: Dict[str, Any] = {
        "state": state,
        "last_error": redact_error(error) if error else "",
        "updated_at": stamp,
        "lease_owner": None,
        "lease_until": None,
    }
    if response_code is not None:
        values["response_code"] = int(response_code)
    if state == "sent":
        values["sent_at"] = stamp
        values["last_error"] = ""
    if state == "pending":
        wait = float(delay if delay is not None else 0.0)
        values["next_attempt_at"] = _iso(moment + timedelta(seconds=max(0.0, wait)))
    assignments = ", ".join(f"{key} = ?" for key in values)
    db.execute(f"UPDATE outbox SET {assignments} WHERE id = ?", (*values.values(), int(record["id"])))
    _refresh_event_state(db, str(record["event_id"]))
    updated = db.execute("SELECT * FROM outbox WHERE id = ?", (int(record["id"]),)).fetchone()
    current = _row(updated) if updated is not None else dict(record)
    current["error"] = values["last_error"]
    return current


def deliver(
    db: sqlite3.Connection,
    row: Any,
    recipient: Any,
    *,
    opener: Any = None,
    now: Any = None,
    sleeper: Optional[Callable[[float], Any]] = None,
    allow_loopback: bool = False,
    codec_pair: Any = _UNSET,
) -> Dict[str, Any]:
    """投递一条发件记录；返回更新后的行（含 ``state`` / ``error``）。

    分类规则见模块 docstring：2xx→sent；429 按 Retry-After；5xx/连接被拒→退避重试；
    地址类 4xx→dead（待处理，不删除）；超时/连接中断/未知异常→unknown（绝不自动重发）。
    """
    moment = _now(now)
    record = _reload_outbox(db, row)
    if record["state"] in {"sent", "dead", "unknown", "failed"}:
        result = dict(record)
        result["error"] = record.get("last_error", "")
        result["skipped"] = True
        return result

    event = db.execute("SELECT * FROM events WHERE event_id = ?", (record["event_id"],)).fetchone()
    if event is None:
        return _settle(db, record, "dead", moment, error="事件记录已丢失，无法投递")
    payload = _loads(event["payload"], {})
    try:
        data = _recipient_material(db, recipient, codec_pair=codec_pair)
    except NotificationError as error:
        return _settle(db, record, "dead", moment, error=str(error))

    idempotency = str(record.get("event_idempotency") or "") or _idempotency(
        str(record["event_id"]), str(record["recipient_id"])
    )
    envelope = _envelope(payload, data, idempotency)
    body = _encode(envelope)
    if len(body) > MAX_BODY_BYTES:
        return _settle(
            db, record, "dead", moment, error=f"请求体超过 {MAX_BODY_BYTES // 1024} KiB 上限，未发送"
        )
    try:
        validate_url(str(data.get("url") or ""), allow_loopback=allow_loopback or bool(data.get("allow_loopback")))
    except UnsafeTarget as error:
        return _settle(db, record, "dead", moment, error=str(error))

    attempts = int(record.get("attempts") or 0) + 1
    db.execute(
        "UPDATE outbox SET state = 'leased', attempts = ?, updated_at = ?,"
        " lease_until = ?, last_error = '' WHERE id = ?",
        (
            attempts,
            _iso(moment),
            _iso(moment + timedelta(seconds=60)),
            int(record["id"]),
        ),
    )
    record["attempts"] = attempts

    try:
        outcome = _send(
            data,
            body,
            envelope,
            opener=opener,
            allow_loopback=allow_loopback,
            sleeper=sleeper,
            now=moment,
        )
    except UnsafeTarget as error:
        return _settle(db, record, "dead", moment, error=str(error))
    except NotificationError as error:
        return _settle(db, record, "dead", moment, error=str(error))

    status = outcome.get("status")
    kind = outcome.get("kind")
    if status is not None:
        if status in _ACCEPTED_CODES:
            return _settle(db, record, "sent", moment, response_code=status)
        if status == 429:
            wait = outcome.get("retry_after")
            delay = float(wait) if wait is not None else backoff_delay(attempts)
            return _settle(
                db,
                record,
                "pending",
                moment,
                error=f"对端限流（429），{int(round(delay))} 秒后重试",
                response_code=status,
                delay=delay,
            )
        if status in _REDIRECT_CODES:
            detail = str(outcome.get("error") or "").strip()
            message = f"重定向无法跟随（{status}）"
            return _settle(
                db,
                record,
                "dead",
                moment,
                error=f"{message}：{detail}" if detail else message,
                response_code=status,
            )
        if status in _DEAD_CODES or (400 <= status < 500 and status not in _RETRYABLE_CLIENT_CODES):
            detail = str(outcome.get("error") or "").strip()
            message = f"收件地址失效或签名错误（{status}）"
            return _settle(
                db,
                record,
                "dead",
                moment,
                error=f"{message}：{detail}" if detail else message,
                response_code=status,
            )
        detail = str(outcome.get("error") or "").strip()
        delay = backoff_delay(attempts)
        return _settle(
            db,
            record,
            "pending",
            moment,
            error=f"对端暂时不可用（{status}），{int(round(delay))} 秒后重试" + (f"：{detail}" if detail else ""),
            response_code=status,
            delay=delay,
        )

    detail = str(outcome.get("error") or "").strip()
    if kind in {"refused"}:
        delay = backoff_delay(attempts)
        return _settle(
            db,
            record,
            "pending",
            moment,
            error=f"连接失败，{int(round(delay))} 秒后重试" + (f"：{detail}" if detail else ""),
            delay=delay,
        )
    message = "响应丢失：请求可能已到达对端，等待人工确认"
    return _settle(db, record, "unknown", moment, error=f"{message}" + (f"（{detail}）" if detail else ""))


def run_once(
    db: sqlite3.Connection,
    owner: str,
    limit: int = 20,
    opener: Any = None,
    *,
    now: Any = None,
    sleeper: Optional[Callable[[float], Any]] = None,
    allow_loopback: bool = False,
) -> Dict[str, int]:
    """取一批发件记录并逐条投递；返回 ``{"sent","retry","dead","unknown"}`` 汇总。"""
    rows = claim(db, owner, limit=limit, now=now)
    summary = {"sent": 0, "retry": 0, "dead": 0, "unknown": 0}
    for row in rows:
        try:
            result = deliver(
                db, row, row["recipient_id"], opener=opener, now=now, sleeper=sleeper, allow_loopback=allow_loopback
            )
        except NotificationError:
            LOGGER.warning("发件记录 %s 投递异常，保留原状态", row.get("id"))
            continue
        state = result.get("state")
        if state == "sent":
            summary["sent"] += 1
        elif state == "dead":
            summary["dead"] += 1
        elif state == "unknown":
            summary["unknown"] += 1
        else:
            summary["retry"] += 1
    return summary


def mark_unknown(db: sqlite3.Connection, outbox_id: int, error: str = "", *, now: Any = None) -> Dict[str, Any]:
    """把一条发件记录标记为 ``unknown``（响应丢失，绝不自动重发）。"""
    moment = _now(now)
    record = _reload_outbox(db, {"id": outbox_id})
    if record["state"] in {"sent", "dead"}:
        raise NotificationError("已完成的发件记录不能改为未知")
    return _settle(db, record, "unknown", moment, error=error or "响应丢失，等待人工确认")


def resolve_unknown(
    db: sqlite3.Connection, outbox_id: int, state: str = "sent", note: str = "", *, now: Any = None
) -> Dict[str, Any]:
    """人工确认 ``unknown`` 的真实结果：``sent``（已送达）或 ``failed``（没送达）。"""
    target = str(state or "").strip()
    if target not in {"sent", "failed", "dead"}:
        raise NotificationError("只能人工确认为 sent / failed / dead")
    moment = _now(now)
    record = _reload_outbox(db, {"id": outbox_id})
    if record["state"] != "unknown":
        raise NotificationError("只有 unknown 状态的记录可以人工确认")
    message = redact_error(note) if note else "人工确认"
    return _settle(db, record, target, moment, error="" if target == "sent" else message)


def requeue(db: sqlite3.Connection, outbox_id: int, *, now: Any = None) -> Dict[str, Any]:
    """把 ``failed`` / ``dead`` / ``unknown`` 的人工结论重新排队（保留 attempts 作为历史）。"""
    moment = _now(now)
    record = _reload_outbox(db, {"id": outbox_id})
    if record["state"] not in {"failed", "dead", "unknown", "pending"}:
        raise NotificationError("当前状态不能重新排队")
    return _settle(db, record, "pending", moment, error="", delay=0.0)


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #


def list_events(db: sqlite3.Connection, limit: int = 50, since: Any = None) -> List[Dict[str, Any]]:
    """本地事件列表（最近在前）；``since`` 接受 ISO8601 或 datetime。"""
    statement = (
        "SELECT e.*,"
        " (SELECT COUNT(*) FROM outbox o WHERE o.event_id = e.event_id) AS recipient_count,"
        " (SELECT COUNT(*) FROM outbox o WHERE o.event_id = e.event_id AND o.state = 'sent') AS sent_count"
        " FROM events e"
    )
    params: List[Any] = []
    if since is not None:
        statement += " WHERE e.occurred_at >= ?"
        params.append(_iso(since))
    statement += " ORDER BY e.occurred_at DESC, e.id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    result = []
    for entry in db.execute(statement, params):
        item = _row(entry)
        item["payload"] = _loads(item.get("payload"), {})
        result.append(item)
    return result


def list_outbox(db: sqlite3.Connection, state: Any = None, limit: int = 100) -> List[Dict[str, Any]]:
    """发件箱列表；``state`` 可以是单个状态或状态集合（如待处理 ``("dead","failed")``）。"""
    statement = "SELECT * FROM outbox"
    params: List[Any] = []
    if state:
        wanted = [str(item) for item in (state if isinstance(state, (list, tuple, set, frozenset)) else [state])]
        statement += " WHERE state IN (%s)" % ",".join("?" for _ in wanted)
        params.extend(wanted)
    statement += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    return [_row(entry) for entry in db.execute(statement, params)]


# --------------------------------------------------------------------------- #
# 测试发送
# --------------------------------------------------------------------------- #


def test_send(
    db: sqlite3.Connection,
    recipient_id: str,
    opener: Any = None,
    *,
    now: Any = None,
    codec_pair: Any = _UNSET,
) -> Dict[str, Any]:
    """给指定收件配置发一条 ``test: true`` 的测试消息（同步投递，不排队等 worker）。"""
    moment = _now(now)
    data = _recipient_material(db, recipient_id, codec_pair=codec_pair)
    event_id = str(uuid.uuid4())
    payload = _build_payload(
        event_id=event_id,
        event_type=EVENT_TEST,
        occurred_at=moment,
        reason="测试发送",
        next_action="收到即说明收件配置可用",
        sequence=0,
        extra={"test": True},
    )
    stamp = _iso(moment)
    with _transaction(db, immediate=True):
        _ensure_event(
            db,
            incident_id=None,
            event_type=EVENT_TEST,
            occurred_at=moment,
            payload=payload,
            dedupe="",
            event_id=event_id,
        )
        db.execute(
            "INSERT OR IGNORE INTO outbox (event_id, event_idempotency, recipient_id, recipient_masked,"
            " state, attempts, next_attempt_at, last_error, updated_at, created_at, lease_owner, lease_until)"
            " VALUES (?, ?, ?, ?, 'leased', 0, ?, '', ?, ?, ?, ?)",
            (
                event_id,
                _idempotency(event_id, str(data["id"])),
                str(data["id"]),
                str(data.get("masked") or ""),
                stamp,
                stamp,
                stamp,
                "direct-test",
                _iso(moment + timedelta(seconds=60)),
            ),
        )
        entry = db.execute(
            "SELECT * FROM outbox WHERE event_id = ? AND recipient_id = ?", (event_id, str(data["id"]))
        ).fetchone()
    result = deliver(db, _row(entry), data, opener=opener, now=moment, codec_pair=codec_pair)
    result["event_id"] = event_id
    result["test"] = True
    return result


# --------------------------------------------------------------------------- #
# 便捷门面
# --------------------------------------------------------------------------- #


class EventStore:
    """把连接与默认 owner 绑在一起的薄门面；实现仍是上面的模块级函数。"""

    def __init__(self, path: Any, *, owner: Optional[str] = None):
        self.path = path
        self.db = connect(path)
        self.owner = owner or f"worker-{os.getpid()}"

    # -- 生命周期 -------------------------------------------------------- #
    def close(self) -> None:
        try:
            self.db.close()
        except sqlite3.Error:  # pragma: no cover - 关闭失败无需上报
            pass

    def __enter__(self) -> "EventStore":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- 转发 ------------------------------------------------------------ #
    def open_incident(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return open_incident(self.db, *args, **kwargs)

    def resolve_incident(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return resolve_incident(self.db, *args, **kwargs)

    def enqueue(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        return enqueue(self.db, *args, **kwargs)

    def claim(self, limit: int = 20, lease_seconds: int = 60, **kwargs: Any) -> List[Dict[str, Any]]:
        return claim(self.db, self.owner, limit=limit, lease_seconds=lease_seconds, **kwargs)

    def deliver(self, row: Any, recipient: Any, **kwargs: Any) -> Dict[str, Any]:
        return deliver(self.db, row, recipient, **kwargs)

    def run_once(self, limit: int = 20, opener: Any = None, **kwargs: Any) -> Dict[str, int]:
        return run_once(self.db, self.owner, limit=limit, opener=opener, **kwargs)

    def list_events(self, limit: int = 50, since: Any = None) -> List[Dict[str, Any]]:
        return list_events(self.db, limit=limit, since=since)

    def list_outbox(self, state: Any = None, limit: int = 100) -> List[Dict[str, Any]]:
        return list_outbox(self.db, state=state, limit=limit)

    def add_recipient(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return add_recipient(self.db, *args, **kwargs)

    def list_recipients(self) -> List[Dict[str, Any]]:
        return list_recipients(self.db)

    def disable_recipient(self, recipient_id: str, **kwargs: Any) -> Dict[str, Any]:
        return disable_recipient(self.db, recipient_id, **kwargs)

    def test_send(self, recipient_id: str, opener: Any = None, **kwargs: Any) -> Dict[str, Any]:
        return test_send(self.db, recipient_id, opener=opener, **kwargs)

    def resolve_unknown(self, outbox_id: int, state: str = "sent", **kwargs: Any) -> Dict[str, Any]:
        return resolve_unknown(self.db, outbox_id, state, **kwargs)


__all__ = [
    # 常量
    "SCHEMA_VERSION",
    "MAX_BODY_BYTES",
    "REQUEST_TIMEOUT",
    "MAX_REDIRECTS",
    "BACKOFF_CAP",
    "EVENT_TYPES",
    "EVENT_TEST",
    "STATES",
    "VERSION",
    "USER_AGENT",
    # 异常
    "NotificationError",
    "UnsafeTarget",
    # 库
    "connect",
    "EventStore",
    # 故障与事件
    "open_incident",
    "resolve_incident",
    "list_incidents",
    "enqueue",
    # 发件箱
    "claim",
    "recover_stale_leases",
    "deliver",
    "run_once",
    "mark_unknown",
    "resolve_unknown",
    "requeue",
    "list_events",
    "list_outbox",
    # 收件配置
    "add_recipient",
    "list_recipients",
    "disable_recipient",
    "test_send",
    # 工具
    "mask_url",
    "redact_error",
    "alias_mask",
    "parse_retry_after",
    "backoff_delay",
    "validate_url",
    "_scrub",
]
