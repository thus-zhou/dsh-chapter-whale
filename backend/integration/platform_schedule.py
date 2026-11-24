"""平台排期识别与能力记录（0.6.1 B01，审计后修订）。

三件事，刻意分开：

1. **解析**：把从平台读到的原始行（文字状态 + 字段）解析成带稳定身份的记录。
   解析器不联网、不写平台、不按列表序号猜章节身份；行里缺什么就记什么，
   绝不用调用参数把缺的字段补齐——否则“身份核对”只是拿参数和自己比。
2. **冲突判定**：同一章多条记录互相矛盾、缺章节 ID、缺作品 ID、缺账号、缺
   计划时刻，一律 ``needs_review``，由作者核对，不计入已排期统计。
3. **能力记录**：把“实际观察到过什么”写成显式能力项（能读排期？能确认排期？
   能确认正文身份？提前量多少？平台在排总量与每日上限各是多少？）。没观察
   过的一律保持 ``None``（未知），未知永远不等于“可以”。

硬约束（与 B01/B02 验收对应）：

- 作品 ID、账号、计划时刻、正文身份只认**平台返回的行**（账号可由本次采集
  所用的登录账号提供，并记录来源）；与任务期望不一致即 ``needs_review``；
- 反义词优先：``定时发布失败``/``已取消`` 不得判成 ``scheduled``；
- ``can_auto_schedule`` 要求六项全部为真/为正数；``0`` 表示“没有容量”，
  不是“不限制”；
- 排期意图的幂等键不含计划时刻：同一章同一版本只有一个意图，改期只更新
  时刻，不产生第二条写入。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:  # pragma: no cover - 时区库在 Windows 上依赖 tzdata
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

# 平台端可观察状态。local_pending 是本机视角，平台不会返回它，保留它是为了
# 让“本地有稿但平台没有任何记录”和“平台草稿”在清单里不会混为一谈。
STATE_LOCAL_PENDING = "local_pending"
STATE_PLAIN_DRAFT = "plain_draft"
STATE_SCHEDULED = "scheduled"
STATE_IN_REVIEW = "in_review"
STATE_PUBLISHED = "published"
STATE_RETURNED = "returned"
STATE_UNKNOWN = "unknown"

SAVE_STATES = (STATE_LOCAL_PENDING, STATE_PLAIN_DRAFT, STATE_SCHEDULED,
               STATE_IN_REVIEW, STATE_PUBLISHED, STATE_RETURNED, STATE_UNKNOWN)

# 正向文案规则。顺序有意义：退回文案里常同时出现“已发布”，先判退回。
_TEXT_RULES: Sequence[Tuple[str, Tuple[str, ...]]] = (
    (STATE_RETURNED, ("审核不通过", "未通过", "被驳回", "驳回", "退回", "未过审")),
    (STATE_IN_REVIEW, ("审核中", "待审核", "安全审核", "审核队列")),
    (STATE_SCHEDULED, ("定时发布", "定时待发", "预约发布", "已定时", "待定时发布",
                       "已排期", "已预约", "排期中", "已安排发布")),
    (STATE_PUBLISHED, ("已发布", "已发表", "已通过", "发布成功")),
    (STATE_PLAIN_DRAFT, ("草稿", "未发布", "待发布", "未提交")),
    (STATE_LOCAL_PENDING, ("仅本地", "本地存稿")),
)

# 反义词：出现即说明“正向词描述的是愿望或失败的动作”，不能算已排期。
# 审计实例：``定时发布失败`` / ``定时发布未成功`` 曾被判成 scheduled。
_NEGATIVE_MARKERS = (
    "失败", "未成功", "未通过", "未过审", "审核不通过", "驳回", "退回",
    "已取消", "取消", "撤回", "撤销", "作废", "下架", "已删除", "删除",
)
# 明确“平台已拒绝或作者已撤销”的反义词：压过正向词，归 returned。
_HARD_NEGATIVE = (
    "失败", "未成功", "未通过", "未过审", "审核不通过", "驳回", "退回",
    "已取消", "取消", "撤回", "撤销", "作废", "下架", "已删除", "删除",
)

DEFAULT_TIMEZONE = "Asia/Shanghai"
CAPABILITY_FILENAME = "platform_capabilities.json"
SCHEMA_VERSION = 2

# 未知能力的安全默认值：只读都算“未证实”，写能力全部关闭。
CAPABILITY_KEYS = (
    "can_read_schedule", "can_schedule", "can_confirm_schedule", "can_confirm_body",
    "lead_time_minutes", "max_scheduled", "max_chapters_per_day",
)
_UNKNOWN_CAPABILITY: Dict[str, Any] = {key: None for key in CAPABILITY_KEYS}


def job_zone(name: Optional[str]) -> Tuple[Any, bool]:
    """返回 (tzinfo, fallback)。时区库缺失时退回固定 +08:00 并标记。"""
    raw = str(name or "").strip() or DEFAULT_TIMEZONE
    if raw.upper() in {"UTC", "Z"}:
        return timezone.utc, False
    try:
        if ZoneInfo is not None:
            return ZoneInfo(raw), False
    except Exception:
        pass
    # 中国无夏令时，固定偏移与 Asia/Shanghai 在 1991 年后等价；仍标 fallback，
    # 让调用方在证据里如实记录“用了固定偏移”。
    return timezone(timedelta(hours=8)), True


def parse_instant(value: Any, tz: Any) -> Optional[datetime]:
    """把平台返回的时刻解析成带时区的 datetime；无法解析返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                            "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
                try:
                    moment = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
            else:
                return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    return moment


def _text_negative(text: str) -> Optional[str]:
    for word in _HARD_NEGATIVE:
        if word in text:
            return word
    return None


def classify_state_detail(text: Any) -> Tuple[str, str]:
    """文字状态 → (状态, 判据)。判据写进证据，便于回源复核。"""
    raw = str(text or "").strip()
    if not raw:
        return STATE_UNKNOWN, "empty"
    hits: List[str] = []
    for state, words in _TEXT_RULES:
        if any(word in raw for word in words):
            hits.append(state)
    negative = _text_negative(raw)
    if negative:
        # 明确失败/撤销压过正向词：``定时发布失败`` 绝不能算已排期。
        return STATE_RETURNED, "negative_text:" + negative
    if len(set(hits)) > 1:
        return STATE_UNKNOWN, "multiple_states:" + ",".join(sorted(set(hits)))
    if hits:
        return hits[0], "text"
    return STATE_UNKNOWN, "unmatched"


def classify_state(text: Any) -> str:
    return classify_state_detail(text)[0]


def _first(row: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _norm_chapter(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    if text.lower().startswith("chapter"):
        text = text[7:].lstrip("_-: ")
    return text


def normalize_row(row: Mapping[str, Any], *, platform: str, account: str = "",
                  book_id: Optional[str] = None,
                  timezone_name: str = DEFAULT_TIMEZONE,
                  source: str = "") -> Dict[str, Any]:
    """解析一行平台记录。缺身份只记录缺什么，不用期望值补。"""
    tz, fallback = job_zone(timezone_name)
    if not isinstance(row, Mapping):
        row = {}
    chapter_id = _norm_chapter(_first(row, ("chapter_id", "chapterId", "chapter", "id")))
    row_book = _first(row, ("book_id", "bookId", "work_id", "workId", "book"))
    row_book = "" if row_book is None else str(row_book).strip()
    expected_book = "" if book_id in (None, "") else str(book_id).strip()
    row_account = _first(row, ("account", "account_id", "accountId"))
    row_account = "" if row_account is None else str(row_account).strip()

    raw_state = _first(row, ("state", "status", "state_text", "status_text"))
    reasons: List[str] = []
    if isinstance(raw_state, str) and raw_state.strip() in SAVE_STATES:
        state, state_reason = raw_state.strip(), "explicit"
    else:
        state, state_reason = classify_state_detail(raw_state)

    planned_raw = _first(row, ("planned_at", "plannedAt", "publish_at", "publishAt",
                               "scheduled_at", "scheduledAt"))
    planned = parse_instant(planned_raw, tz)
    # 是否“补了时区”只看解析结果有没有 tzinfo，不靠字符串里有没有 "T"/"+"——平台可能给
    # “2026-11-22 08:00”这种带空格、不带时区的写法。
    timezone_assumed = False
    if isinstance(planned_raw, str) and planned_raw.strip() and planned is not None:
        raw_time = str(planned_raw).strip()
        try:
            parsed_raw = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            timezone_assumed = parsed_raw.tzinfo is None
        except ValueError:
            timezone_assumed = not bool(re.search(r"(?:Z|[+-]\d{2}:?\d{2})$", raw_time, re.IGNORECASE))
    if state == STATE_SCHEDULED and planned is None:
        reasons.append("已排期行缺少可解析的计划时刻")
    if planned is not None and timezone_assumed:
        reasons.append("计划时刻未带时区，已按任务时区补齐")

    content_sha = _first(row, ("content_sha256", "body_sha256", "contentSha256", "sha256"))
    content_sha = str(content_sha or "").strip().lower()

    if not chapter_id:
        reasons.append("缺少平台章节 ID")
    if not row_book:
        reasons.append("缺少作品 ID")
    elif expected_book and row_book != expected_book:
        reasons.append("作品 ID 与任务不一致")
    if row_account and account and row_account != account:
        reasons.append("账号与本次采集账号不一致")
    account_value = row_account or str(account or "")
    account_source = "row" if row_account else ("collector" if account_value else "unknown")
    if not account_value:
        reasons.append("缺少账号")

    return {
        "platform": str(platform or ""),
        "account": account_value,
        "account_source": account_source,
        "book_id": row_book,
        "chapter_id": chapter_id,
        "chapter_title": str(_first(row, ("chapter_title", "title", "name")) or ""),
        "state": state,
        "state_reason": state_reason,
        "raw_state": "" if raw_state is None else str(raw_state),
        "planned_at": planned.isoformat() if planned else "",
        "planned_at_utc": planned.astimezone(timezone.utc).isoformat() if planned else "",
        "timezone": str(timezone_name or DEFAULT_TIMEZONE),
        "timezone_fallback": fallback,
        "timezone_assumed": timezone_assumed,
        "content_sha256": content_sha,
        "needs_review": reasons,
        "identity_ok": not reasons,
        "source": str(source or ""),
    }


def _same_moment(first: str, second: str) -> bool:
    if not first or not second:
        return first == second
    return same_instant(first, second)


def read_snapshot(rows: Iterable[Mapping[str, Any]], *, platform: str, account: str = "",
                  book_id: Optional[str] = None,
                  timezone_name: str = DEFAULT_TIMEZONE,
                  complete: bool = True, source: str = "") -> Dict[str, Any]:
    """解析整份快照：完全相同的重复行去重，互相矛盾的同行全部待核对。"""
    normalized = [normalize_row(row, platform=platform, account=account, book_id=book_id,
                                timezone_name=timezone_name, source=source)
                  for row in (rows or [])]
    groups: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = {}
    for item in normalized:
        groups.setdefault((item["platform"], item["account"], item["book_id"],
                           item["chapter_id"]), []).append(item)

    entries: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    duplicates = 0
    for key, items in groups.items():
        if not key[3]:
            review.extend(items)
            continue
        distinct: List[Dict[str, Any]] = []
        for item in items:
            twin = next((seen for seen in distinct
                         if seen["state"] == item["state"]
                         and seen["content_sha256"] == item["content_sha256"]
                         and _same_moment(seen["planned_at"], item["planned_at"])), None)
            if twin is None:
                distinct.append(item)
            else:
                duplicates += 1
        if len(distinct) > 1:
            detail = {"platform": key[0], "account": key[1], "book_id": key[2],
                      "chapter_id": key[3],
                      "states": [item["state"] for item in distinct],
                      "planned_at": [item["planned_at"] for item in distinct],
                      "reason": "同章多条记录互相矛盾"}
            conflicts.append(detail)
            for item in distinct:
                item["needs_review"].append("同章多条记录互相矛盾")
                item["identity_ok"] = False
            review.extend(distinct)
            continue
        item = distinct[0]
        (review if item["needs_review"] else entries).append(item)

    counts: Dict[str, int] = {}
    for item in entries:
        counts[item["state"]] = counts.get(item["state"], 0) + 1
    return {
        "platform": str(platform or ""),
        "account": str(account or ""),
        "book_id": "" if book_id in (None, "") else str(book_id),
        "timezone": str(timezone_name or DEFAULT_TIMEZONE),
        "complete": bool(complete),
        "source": str(source or ""),
        "entries": entries,
        "needs_review": review,
        "conflicts": conflicts,
        "counts": counts,
        "duplicates": duplicates,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---- 能力记录 ---------------------------------------------------------------

def capabilities_path() -> Path:
    raw = os.environ.get("NOVEL_HELPER_DATA")
    base = Path(raw) if raw else Path(__file__).resolve().parents[1] / "integration_data"
    return base / CAPABILITY_FILENAME


def _capability_key(platform: str, account: str, book_id: str) -> str:
    raw = "|".join([str(platform or ""), str(account or ""), str(book_id or "")])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def load_capabilities(path: Optional[Path] = None) -> Dict[str, Any]:
    target = Path(path) if path else capabilities_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict) or not isinstance(data.get("records"), dict):
        data = {}
    return {"schema": SCHEMA_VERSION, "records": data.get("records") or {}}


def save_capabilities(document: Mapping[str, Any], path: Optional[Path] = None) -> Path:
    import uuid
    from fanqie_auto_publish.publication_safety import replace_with_retry
    target = Path(path) if path else capabilities_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": SCHEMA_VERSION,
               "records": dict((document or {}).get("records") or {})}
    temp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_with_retry(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target


def _clean_capabilities(raw: Mapping[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key in CAPABILITY_KEYS:
        value = raw.get(key) if isinstance(raw, Mapping) else None
        if key.startswith("can_"):
            result[key] = None if value is None else bool(value)
        else:
            try:
                number = None if value in (None, "") else int(value)
            except (TypeError, ValueError):
                number = None
            result[key] = None if number is None or number < 0 else number
    return result


def record_capability(observation: Mapping[str, Any]) -> Dict[str, Any]:
    """按观察证据写一条能力记录；未知项保持 None，绝不写“默认可以”。"""
    platform = str((observation or {}).get("platform") or "")
    account = str((observation or {}).get("account") or "")
    book_id = str((observation or {}).get("book_id") or "")
    record = {
        "platform": platform,
        "account": account,
        "book_id": book_id,
        "observed_at": str((observation or {}).get("observed_at") or ""),
        "source": str((observation or {}).get("source") or ""),
        "evidence": (observation or {}).get("evidence") or {},
        "timezone": str((observation or {}).get("timezone") or DEFAULT_TIMEZONE),
        "capabilities": _clean_capabilities((observation or {}).get("capabilities") or {}),
    }
    document = load_capabilities()
    document["records"][_capability_key(platform, account, book_id)] = record
    save_capabilities(document)
    return record


def capability_for(platform: str, account: str = "", book_id: str = "") -> Dict[str, Any]:
    document = load_capabilities()
    record = document["records"].get(_capability_key(platform, account, book_id))
    if not isinstance(record, dict):
        return {"platform": str(platform or ""), "account": str(account or ""),
                "book_id": str(book_id or ""), "observed_at": "", "source": "",
                "evidence": {}, "timezone": DEFAULT_TIMEZONE,
                "capabilities": dict(_UNKNOWN_CAPABILITY)}
    record = dict(record)
    record["capabilities"] = _clean_capabilities(record.get("capabilities") or {})
    return record


def can_auto_schedule(capability: Mapping[str, Any]) -> Tuple[bool, str]:
    """六项能力全部证实才允许自动排期。0 表示“没有容量”，不是“不限制”。"""
    if not isinstance(capability, Mapping):
        return False, "没有平台排期能力记录"
    caps = capability.get("capabilities") if isinstance(capability.get("capabilities"), Mapping) \
        else capability
    checks = (
        ("can_read_schedule", "未证实可读取平台排期"),
        ("can_schedule", "未证实可代提交定时发布"),
        ("can_confirm_schedule", "未证实可回读确认排期"),
        ("can_confirm_body", "未证实可回读正文身份"),
    )
    for key, reason in checks:
        if caps.get(key) is not True:
            return False, reason
    for key, reason in (("lead_time_minutes", "未知平台提前量（分钟）"),
                        ("max_scheduled", "未知平台在排总量上限"),
                        ("max_chapters_per_day", "未知平台每日排期上限")):
        value = caps.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            return False, reason
        if key == "lead_time_minutes":
            if value < 0:
                return False, "平台提前量为负数"
            continue
        if value <= 0:
            return False, reason.replace("未知", "为 0（无容量）")
    return True, ""


# ---- 意图键与时刻比较 -------------------------------------------------------

def schedule_intent_key(job_id: str, platform: str, account: str, book_id: str,
                        chapter_id: Any, version_sha256: str) -> str:
    """一章一版一个键；计划时刻只是可更新字段，改期不得产生第二条写入意图。"""
    raw = "|".join([str(job_id or ""), str(platform or ""), str(account or ""),
                    str(book_id or ""), _norm_chapter(chapter_id),
                    str(version_sha256 or "").strip().lower()])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def same_instant(first: Any, second: Any, tolerance_seconds: int = 1) -> bool:
    """同一预约时刻的容差比较。默认 1 秒，避免把相邻两档判成同一档。

    不带时区的裸时刻按 UTC 解释（``parse_instant`` 的既有约定）；两值都补成 UTC
    后再比，避免 naive/aware 相减抛 ``TypeError``。
    """
    tz = timezone.utc
    left = parse_instant(first, tz)
    right = parse_instant(second, tz)
    if left is None or right is None:
        return False
    if left.tzinfo is None:
        left = left.replace(tzinfo=tz)
    if right.tzinfo is None:
        right = right.replace(tzinfo=tz)
    return abs((left - right).total_seconds()) <= max(0, int(tolerance_seconds))
