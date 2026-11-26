"""平台排期缓冲：纯计算计划、覆盖截止、意图台账（0.6.1 B02，审计后修订）。

设计要点（逐条对应审计发现）：

- **纯计算**：``plan()`` 不写文件、不联网、不读平台；只吃“已审定回执 + 当前
  台账 + 能力记录 + 设置”。界面预览与真正排期走同一个函数。
- **一章一版一个意图**：意图键不含计划时刻（见
  :func:`platform_schedule.schedule_intent_key`）。跨天重排只会更新同一意图的
  ``planned_at``，不会生成第二条写入意图，更不会把已提交的章再提交一次。
- **从下个应发时段连续计算**：候选时刻从 ``now + lead_time`` 之后的第一个
  时段开始，按“有效天数”而不是日历日计数；23:30 排明早 08:00 也成立。
- **过期不补写**：``planned_at <= now`` 的意图标 ``expired``，交给只读对账，
  绝不自动提交（迟到提交在平台上等于“立即发布”）。
- **关闭补货不撤计划**：``stop_replenish`` 只改标记，已有意图原样保留。
- **对账只升不降**：``scheduled_verified`` 只有平台明确给出撤销/改期证据才降级；
  不完整快照与缺行都不做否定判断。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import platform_schedule as ps

SCHEMA_VERSION = 2
DEFAULT_SETTINGS: Dict[str, Any] = {
    "enabled": False,
    "target_days": 2,
    "slots": [],
    "chapters_per_slot": 1,
    "keep_local": 2,
    "stop_after_gap": True,
    "updated_at": "",
}
TERMINAL_STATES = ("scheduled_verified", "published")
IN_FLIGHT_STATES = ("planned", "submitted")
# 真正占平台“在排总量”的状态：本地 planned 还没交出去，不该算进平台限额。
PLATFORM_STATES = ("submitted", "scheduled_verified")
BLOCKING_STATES = ("submitted", "needs_review", "failed")


def store_dir() -> Path:
    raw = os.environ.get("NOVEL_HELPER_DATA")
    base = Path(raw) if raw else Path(__file__).resolve().parents[1] / "integration_data"
    return base / "schedule_buffers"


def store_path(job_id: str) -> Path:
    digest = hashlib.sha256(str(job_id or "").encode("utf-8")).hexdigest()[:16]
    return store_dir() / f"buffer-{digest}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_store(job_id: str) -> Dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "job_id": str(job_id or ""),
        "updated_at": "",
        "revision": 0,
        "replenish_stopped": False,
        "stop_reason": "",
        "recompute_required": False,
        "gap_notified_at": "",
        "plan": {},
        "intents": [],
        "last_reconcile": {},
    }


def load_store(job_id: str, path: Optional[Path] = None) -> Dict[str, Any]:
    target = Path(path) if path else store_path(job_id)
    empty = _empty_store(job_id)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty
    merged = {**empty, **data}
    merged["intents"] = [item for item in merged.get("intents") or [] if isinstance(item, dict)]
    if not isinstance(merged.get("plan"), dict):
        merged["plan"] = {}
    return merged


def save_store(job_id: str, store: Mapping[str, Any], path: Optional[Path] = None) -> Path:
    import uuid
    from fanqie_auto_publish.publication_safety import replace_with_retry
    target = Path(path) if path else store_path(job_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(store or {})
    payload["job_id"] = str(job_id or payload.get("job_id") or "")
    payload["schema"] = SCHEMA_VERSION
    payload["updated_at"] = _now_iso()
    payload["revision"] = int(payload.get("revision") or 0) + 1
    temp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_with_retry(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target


# ---- 设置 -------------------------------------------------------------------

def normalize_settings(raw: Any) -> Dict[str, Any]:
    """把任意输入收敛成可用的设置；坏值回落默认，不抛异常（供预览）。"""
    data = dict(DEFAULT_SETTINGS)
    if isinstance(raw, Mapping):
        data.update({key: raw[key] for key in DEFAULT_SETTINGS if key in raw})
    data["enabled"] = bool(data.get("enabled"))
    data["stop_after_gap"] = bool(data.get("stop_after_gap"))
    try:
        data["target_days"] = min(14, max(1, int(data.get("target_days") or 2)))
    except (TypeError, ValueError):
        data["target_days"] = DEFAULT_SETTINGS["target_days"]
    try:
        data["chapters_per_slot"] = min(10, max(1, int(data.get("chapters_per_slot") or 1)))
    except (TypeError, ValueError):
        data["chapters_per_slot"] = DEFAULT_SETTINGS["chapters_per_slot"]
    try:
        data["keep_local"] = min(50, max(0, int(data.get("keep_local") or 0)))
    except (TypeError, ValueError):
        data["keep_local"] = DEFAULT_SETTINGS["keep_local"]
    slots = data.get("slots") if isinstance(data.get("slots"), (list, tuple)) else []
    cleaned: List[str] = []
    for item in slots:
        text = str(item or "").strip()
        try:
            hour, minute = text.split(":")[0:2]
            moment = time(int(hour), int(minute))
        except (ValueError, IndexError):
            continue
        label = moment.strftime("%H:%M")
        if label not in cleaned:
            cleaned.append(label)
    data["slots"] = sorted(cleaned)[:8]
    data["updated_at"] = str(data.get("updated_at") or "")
    return data


def validate_settings(raw: Any) -> Dict[str, Any]:
    """写入前的严格校验：显式坏时段直接拒绝，不静默丢弃。"""
    if raw is not None and not isinstance(raw, Mapping):
        raise ValueError("排期设置必须是对象")
    source = raw if isinstance(raw, Mapping) else {}
    slots = source.get("slots")
    if slots is not None:
        if not isinstance(slots, (list, tuple)):
            raise ValueError("slots 必须是时段数组")
        for item in slots:
            text = str(item or "").strip()
            parts = text.split(":")
            if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
                raise ValueError(f"时段格式必须是 HH:MM：{text!r}")
            if not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59):
                raise ValueError(f"时段超出范围：{text!r}")
    settings = normalize_settings(source)
    if settings["enabled"] and not settings["slots"]:
        # 没写时段时沿用任务既有时段，这里不回填，只标记由调用方决定。
        settings["slots"] = []
    return settings


# ---- 已审定稿件 -------------------------------------------------------------

def approved_candidates(project: Any, *, published: Optional[Iterable[int]] = None,
                        book: str = "") -> List[Dict[str, Any]]:
    """只认本机回执（reviewed_chapters）；没有回执的章一律不进排期候选。

    ``blocking = existing - reviewed - published``：更早的未审查、needs_revision、
    改稿后回执失效、重复章号，都会成为阻塞章；所有 ``>= first_blocking`` 的章
    都不得排期，避免平台出现章号缺口。``published`` 由调用方传入（已上平台的章
    不再需要本地回执）；未传时按空集合处理，``book`` 仅在需要从归档推导时使用。
    """
    from . import writer_runner as writer

    path = Path(project)
    try:
        receipts = writer.reviewed_chapters(path)
    except Exception:  # noqa: BLE001 - 项目不可读时按“没有可用稿件”处理
        return []
    try:
        existing = writer.existing_chapter_ids(path)
    except Exception:  # noqa: BLE001 - 无法枚举正文时不能证明没有阻塞章
        return []
    published_set = set()
    if published is None:
        if book:
            try:
                from . import scheduler as s
                published_set = {int(c) for c in s._published_ids(book)}
            except Exception:  # noqa: BLE001 - 归档不可读时按“没有已发布章”处理
                published_set = set()
    else:
        for value in published:
            try:
                published_set.add(int(value))
            except (TypeError, ValueError):
                continue
    blocking = sorted((set(existing) - set(receipts)) - published_set)
    first_blocking = blocking[0] if blocking else 0
    candidates: List[Dict[str, Any]] = []
    for chapter_id, receipt in sorted((receipts or {}).items()):
        if not isinstance(receipt, Mapping):
            continue
        version = str(receipt.get("sha256") or receipt.get("body_sha256") or "").strip().lower()
        if not version:
            continue
        try:
            number = int(chapter_id)
        except (TypeError, ValueError):
            continue
        if first_blocking and number >= first_blocking:
            # A later reviewed chapter must not jump over an earlier chapter
            # that still lacks a valid review receipt.
            continue
        candidates.append({"chapter_id": number, "version_sha256": version,
                           "words": int(receipt.get("word_count") or receipt.get("words") or 0),
                           "destination": str(receipt.get("destination") or "")})
    return candidates


# ---- 计划（纯计算） ---------------------------------------------------------

def _job_platforms(job: Mapping[str, Any]) -> Tuple[str, str, str]:
    platform = str(job.get("platform") or "fanqie").strip().lower()
    account = str(job.get("account") or "").strip()
    book = str(job.get("book") or "").strip()
    return platform, account, book


def _slot_times(job: Mapping[str, Any], settings: Mapping[str, Any]) -> List[str]:
    slots = list(settings.get("slots") or [])
    if slots:
        return slots
    from . import scheduler as s

    try:
        return list(s.job_times(dict(job)) or [])
    except Exception:  # noqa: BLE001 - 任务字段不全时不猜时段
        return []


def _intent_chapters(intents: Iterable[Mapping[str, Any]]) -> Dict[Tuple[str, str], str]:
    """已被台账占用的 (章号, 版本) → 状态。

    ``cancelled``（被重算取消）不算占用：同一版本应该能被重新排进去；
    ``needs_review``/``failed`` 算占用，否则待对账的章会被反复排进新档位。
    """
    occupied: Dict[Tuple[str, str], str] = {}
    for item in intents or []:
        if not isinstance(item, Mapping):
            continue
        state = str(item.get("state") or "")
        if state == "cancelled":
            continue
        if state in TERMINAL_STATES + IN_FLIGHT_STATES + ("expired", "stale", "needs_review", "failed", "superseded"):
            key = (str(item.get("chapter_id") or ""), str(item.get("version_sha256") or ""))
            occupied[key] = state
    return occupied


def _open_states() -> Tuple[str, ...]:
    """占平台“在排总量”的状态；已核验但没发布仍然占着平台档位。"""
    return IN_FLIGHT_STATES + ("scheduled_verified",)


def plan(job: Mapping[str, Any], *, now: Optional[datetime] = None, approved: Iterable[Mapping[str, Any]] = (),
         remote: Iterable[Mapping[str, Any]] = (), intents: Optional[Iterable[Mapping[str, Any]]] = None,
         capability: Optional[Mapping[str, Any]] = None,
         settings: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """纯计算：给出现有稿件能填满的时段，缺口处截断并写清原因。"""
    settings = normalize_settings(settings if settings is not None else job.get("schedule_buffer"))
    platform, account, book = _job_platforms(job)
    tz, tz_fallback = ps.job_zone(str(job.get("timezone") or ps.DEFAULT_TIMEZONE))
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    current = current.astimezone(tz)

    caps = capability.get("capabilities") if isinstance(capability, Mapping) \
        and isinstance(capability.get("capabilities"), Mapping) else (capability or {})
    caps = caps if isinstance(caps, Mapping) else {}
    auto_allowed, auto_reason = ps.can_auto_schedule(capability or {})
    lead = caps.get("lead_time_minutes")
    lead_minutes = lead if isinstance(lead, int) and not isinstance(lead, bool) and lead >= 0 else 0
    max_scheduled = caps.get("max_scheduled")
    daily_limit = caps.get("max_chapters_per_day")

    resolved_job_id = str(job.get("job_id") or job.get("id") or "")
    store_intents = list(intents if intents is not None else load_store(resolved_job_id).get("intents") or [])
    occupied = _intent_chapters(store_intents)
    # 在排总量要算上“已核验但还没发布”的章：它们同样占着平台档位；
    # 但本地 planned 还没交出去，不算平台占用。
    in_flight = sum(1 for item in store_intents
                    if isinstance(item, Mapping) and item.get("state") in PLATFORM_STATES)
    # 同一章只要还有未取消的意图，就不能用另一个版本再排一次——否则一次改稿
    # 会让同一章在平台上出现两条预约，或在台账里留下两份占用。
    occupied_chapters = {str(item.get("chapter_id") or ""): str(item.get("state") or "")
                         for item in store_intents
                         if isinstance(item, Mapping)
                         and str(item.get("state") or "") not in ("cancelled", "expired", "stale")}

    candidates = [item for item in approved or [] if isinstance(item, Mapping) and item.get("chapter_id")]
    selected: List[Dict[str, Any]] = []
    blocked: List[str] = []
    keep_chapters: List[int] = []
    for item in sorted(candidates, key=lambda entry: int(entry.get("chapter_id") or 0)):
        chapter = str(int(item["chapter_id"]))
        version = str(item.get("version_sha256") or "")
        state = occupied.get((chapter, version))
        if state in TERMINAL_STATES + IN_FLIGHT_STATES + ("needs_review", "failed"):
            blocked.append(f"第{chapter}章已在台账（{state}），不重复排期")
            # 已占用的章必须留在 apply 的白名单里，否则重算会把在途意图误取消。
            keep_chapters.append(int(item["chapter_id"]))
            continue
        other = occupied_chapters.get(chapter)
        if other:
            blocked.append(f"第{chapter}章已有另一版本的意图（{other}），先对账或取消再用新版本排期")
            keep_chapters.append(int(item["chapter_id"]))
            continue
        selected.append({"chapter_id": int(item["chapter_id"]),
                         "version_sha256": version,
                         "words": int(item.get("words") or 0)})

    remote_ids = set()
    for item in remote or []:
        if isinstance(item, Mapping) and item.get("state") in (ps.STATE_SCHEDULED, ps.STATE_PUBLISHED):
            remote_ids.add(str(item.get("chapter_id") or ""))
    if remote_ids:
        selected = [item for item in selected if str(item["chapter_id"]) not in remote_ids]

    keep = int(settings.get("keep_local") or 0)
    kept_count = 0
    if keep and len(selected) > keep:
        kept_count = keep
        selected = selected[: len(selected) - keep]
    elif keep:
        kept_count = len(selected)
        selected = []
    local_remaining = len(selected) + kept_count

    slots = _slot_times(job, settings)
    result: Dict[str, Any] = {
        "job_id": resolved_job_id,
        "platform": platform,
        "account": account,
        "book_id": book,
        "timezone": str(job.get("timezone") or ps.DEFAULT_TIMEZONE),
        "timezone_fallback": tz_fallback,
        "generated_at": current.isoformat(timespec="seconds"),
        "settings": settings,
        "auto_allowed": auto_allowed,
        "auto_reason": auto_reason,
        "in_flight": in_flight,
        "blockers": blocked,
        "keep": keep_chapters,
        "entries": [],
        "coverage": {"until": "", "gap_at": "", "gap_reason": "", "days": []},
        "local_remaining": local_remaining,
        "planned_count": 0,
        "status": "ok",
        "reason": "",
    }
    if not settings["enabled"]:
        result.update(status="disabled", reason="排期缓冲未开启")
        return result
    if not slots:
        result.update(status="no_slots", reason="没有可用时段：请先设置每日时段")
        return result
    if isinstance(daily_limit, int) and not isinstance(daily_limit, bool) and daily_limit <= 0:
        result.update(status="capacity_exhausted", reason="平台每日排期上限为 0（无容量）")
        return result
    if isinstance(max_scheduled, int) and not isinstance(max_scheduled, bool) and max_scheduled <= 0:
        result.update(status="capacity_exhausted", reason="平台在排总量上限为 0（无容量）")
        return result

    # 候选时刻：从 now + lead 之后的第一个未来时段起，按“有效天数”计数，
    # 不按日历日计数——23:30 时明早 08:00 必须仍然算在目标天数里。
    chapters_per_slot = max(1, int(settings["chapters_per_slot"]))
    per_day = chapters_per_slot * len(slots)
    if isinstance(daily_limit, int) and not isinstance(daily_limit, bool):
        per_day = min(per_day, max(0, daily_limit))
    horizon_days = int(settings["target_days"])
    start = current + timedelta(minutes=lead_minutes)
    moments: List[datetime] = []
    cursor_date: date = start.date()
    scanned = 0
    while scanned < horizon_days + 2 and len({m.date() for m in moments}) < horizon_days:
        day_added = 0
        for label in slots:
            if day_added >= per_day:
                break
            hour, minute = (int(part) for part in label.split(":")[:2])
            moment = datetime.combine(cursor_date, time(hour, minute), tzinfo=start.tzinfo)
            if moment >= start:
                for _ in range(chapters_per_slot):
                    if day_added >= per_day:
                        break
                    moments.append(moment)
                    day_added += 1
        cursor_date += timedelta(days=1)
        scanned += 1
    # 只保留“有效天数”窗口：把已过去的时段剔除后再截取天数。
    valid_dates: List[date] = []
    for moment in moments:
        if moment.date() not in valid_dates:
            valid_dates.append(moment.date())
    window = set(valid_dates[:horizon_days])
    moments = [moment for moment in moments if moment.date() in window][: per_day * horizon_days]

    remaining_capacity = None
    if isinstance(max_scheduled, int) and not isinstance(max_scheduled, bool) and max_scheduled > 0:
        remaining_capacity = max(0, max_scheduled - in_flight)

    entries: List[Dict[str, Any]] = []
    day_counts: Dict[str, int] = {}
    for moment in moments:
        if not selected:
            break
        if remaining_capacity is not None and len(entries) >= remaining_capacity:
            break
        key = moment.date().isoformat()
        if day_counts.get(key, 0) >= per_day:
            continue
        item = selected.pop(0)
        planned_at = moment.isoformat(timespec="seconds")
        entries.append({
            "chapter_id": item["chapter_id"],
            "version_sha256": item["version_sha256"],
            "planned_at": planned_at,
            "planned_at_utc": moment.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "slot": key,
            "key": ps.schedule_intent_key(resolved_job_id, platform, account, book,
                                          item["chapter_id"], item["version_sha256"]),
        })
        day_counts[key] = day_counts.get(key, 0) + 1

    gap_at = ""
    gap_reason = ""
    if remaining_capacity is not None and len(entries) >= remaining_capacity and (selected or len(entries) < len(moments)):
        gap_reason = "达到平台在排总量上限"
        gap_at = (moments[len(entries)].isoformat(timespec="seconds")
                  if len(entries) < len(moments) else "")
    elif selected:
        if len(entries) < len(moments):
            gap_at = moments[len(entries)].isoformat(timespec="seconds")
            gap_reason = "达到平台每日排期上限"
    elif len(entries) < len(moments):
        # 稿件已排完但目标缓冲仍未填满：缺口从下一个空档开始，不能装作已覆盖。
        gap_at = moments[len(entries)].isoformat(timespec="seconds")
        gap_reason = (f"已审定稿件已全部排完，目标缓冲 {horizon_days} 天未填满"
                      f"（空 {len(moments) - len(entries)} 档）")

    days = [{"date": key, "count": value} for key, value in sorted(day_counts.items())]
    result["entries"] = entries
    result["planned_count"] = len(entries)
    result["coverage"] = {
        "until": entries[-1]["planned_at"] if entries else "",
        "gap_at": gap_at,
        "gap_reason": gap_reason,
        "days": days,
        "verified_until": "",
    }
    result["local_remaining"] = len(selected) + kept_count
    if not entries:
        result.update(status="no_candidate",
                      reason="没有可排期的已审定稿件" if not candidates else "所有时段都已过或在提前量之内")
    return result


# ---- 台账 -------------------------------------------------------------------

def _find(intents: Sequence[Mapping[str, Any]], key: str) -> Optional[Mapping[str, Any]]:
    for item in intents:
        if isinstance(item, Mapping) and item.get("key") == key:
            return item
    return None


def apply_plan(job_id: str, job: Mapping[str, Any], planned: Mapping[str, Any],
               store: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把计划写进台账。同一章同版本只更新时刻；已提交/已核验的章拒绝重排。"""
    store = store if store is not None else load_store(job_id)
    platform, account, book = _job_platforms(job)
    entries = [item for item in planned.get("entries") or [] if isinstance(item, Mapping)]
    planned_keys = {str(item.get("key") or "") for item in entries}
    added = replaced = cancelled = superseded = 0
    blocked: List[str] = []
    intents = [item for item in store.get("intents") or [] if isinstance(item, Mapping)]

    for entry in entries:
        key = str(entry.get("key") or "")
        existing = _find(intents, key)
        if existing is None:
            chapter_key = str(entry.get("chapter_id"))
            # 同一章换了新版本时，旧版本留下的 expired 意图不再与 planned 并存：
            # 它已经错过自己的档位，新版本排进来后只保留一条有效台账。
            for old in intents:
                if not isinstance(old, dict):
                    continue
                if (str(old.get("job_id") or "") == str(job_id)
                        and str(old.get("chapter_id") or "") == chapter_key
                        and str(old.get("state") or "") == "expired"):
                    old["state"] = "superseded"
                    old["last_error"] = "superseded_by_new_version"
                    superseded += 1
            intents.append({
                "key": key,
                "job_id": str(job_id),
                "platform": platform,
                "account": account,
                "book_id": book,
                "chapter_id": str(entry.get("chapter_id")),
                "version_sha256": str(entry.get("version_sha256") or ""),
                "planned_at": str(entry.get("planned_at") or ""),
                "state": "planned",
                "attempts": 0,
                "submitted_at": "",
                "remote": {},
                "last_error": "",
                "created_at": _now_iso(),
            })
            added += 1
            continue
        state = str(existing.get("state") or "")
        if state in TERMINAL_STATES or state == "submitted":
            blocked.append(f"第{entry.get('chapter_id')}章已{state}，拒绝重复排期")
            continue
        if state in ("needs_review", "failed"):
            blocked.append(f"第{entry.get('chapter_id')}章上次结果未确认（{state}），先对账")
            continue
        if state in ("planned", "expired") \
                and str(existing.get("planned_at") or "") != str(entry.get("planned_at") or ""):
            # 过期只是“这一档错过了”，章还没写；改到新时刻继续用同一条意图。
            existing["planned_at"] = str(entry.get("planned_at") or "")
            existing["state"] = "planned"
            existing["attempts"] = 0
            existing["last_error"] = ""
            replaced += 1
            continue
        if state == "cancelled":
            # 取消只是“这一轮不排”，不是墓碑：同一章同版本重新进计划时必须复活，
            # 否则台账永远留着 cancelled，预览说“要排 N 章”而 apply 什么也不做。
            existing["planned_at"] = str(entry.get("planned_at") or "")
            existing["state"] = "planned"
            existing["attempts"] = 0
            existing["last_error"] = ""
            existing["created_at"] = _now_iso()
            replaced += 1

    keep_chapters = {str(item) for item in planned.get("keep") or []}
    for item in intents:
        if not isinstance(item, dict):
            continue
        if item.get("state") == "planned" and item.get("key") not in planned_keys \
                and str(item.get("job_id") or "") == str(job_id) \
                and str(item.get("chapter_id") or "") not in keep_chapters:
            item["state"] = "cancelled"
            item["last_error"] = "replanned_out"
            cancelled += 1

    store["intents"] = [dict(item) for item in intents]
    store["plan"] = {
        "generated_at": planned.get("generated_at") or _now_iso(),
        "status": planned.get("status"),
        "coverage": planned.get("coverage") or {},
        "planned_count": planned.get("planned_count") or 0,
        "local_remaining": planned.get("local_remaining") or 0,
        "entries": [dict(item) for item in entries[:40]],
    }
    save_store(job_id, store)
    return {"added": added, "replaced": replaced, "cancelled": cancelled,
            "superseded": superseded, "blocked": blocked, "total": len(store["intents"])}


def stop_replenish(job_id: str, reason: str = "author_stopped") -> Dict[str, Any]:
    """关闭补货：只停未来的新建，不撤已有计划，也不碰平台。"""
    store = load_store(job_id)
    store["replenish_stopped"] = True
    store["stop_reason"] = str(reason or "author_stopped")
    store["recompute_required"] = False
    save_store(job_id, store)
    untouched = [item for item in store["intents"]
                 if isinstance(item, Mapping) and item.get("state") not in TERMINAL_STATES + ("cancelled",)]
    return {"stopped": True, "reason": store["stop_reason"], "remote_untouched": len(untouched)}


def resume_replenish(job_id: str) -> Dict[str, Any]:
    store = load_store(job_id)
    store["replenish_stopped"] = False
    store["stop_reason"] = ""
    save_store(job_id, store)
    return {"stopped": False, "recompute_required": bool(store.get("recompute_required"))}


def note_manual_change(job_id: str, kind: str = "manual_change") -> Dict[str, Any]:
    """作者在平台侧取消/改期/替稿/删章：标记需重算，并只提醒一次。"""
    store = load_store(job_id)
    store["recompute_required"] = True
    notify = not store.get("gap_notified_at")
    if notify:
        store["gap_notified_at"] = _now_iso()
    store["last_manual_change"] = {"kind": str(kind or "manual_change"), "at": _now_iso()}
    save_store(job_id, store)
    return {"recompute_required": True, "notify": notify, "kind": store["last_manual_change"]["kind"]}


def pending_intents(job_id: str, states: Sequence[str] = ("planned",)) -> List[Dict[str, Any]]:
    store = load_store(job_id)
    wanted = set(states)
    return [dict(item) for item in store["intents"]
            if isinstance(item, Mapping) and item.get("state") in wanted]


def mark_submitted(job_id: str, key: str, remote: Mapping[str, Any],
                   store: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    store = store if store is not None else load_store(job_id)
    for item in store["intents"]:
        if isinstance(item, dict) and item.get("key") == key:
            item["state"] = "submitted"
            item["submitted_at"] = _now_iso()
            item["remote"] = dict(remote or {})
            item["attempts"] = int(item.get("attempts") or 0) + 1
            item["last_error"] = ""
            break
    save_store(job_id, store)
    return store


def mark_failed(job_id: str, key: str, error: str, state: str = "needs_review",
                store: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """记录失败。``needs_review`` 表示“结果未知”，禁止自动重试。"""
    store = store if store is not None else load_store(job_id)
    for item in store["intents"]:
        if isinstance(item, dict) and item.get("key") == key:
            item["state"] = str(state or "needs_review")
            item["last_error"] = str(error or "")[:300]
            item["attempts"] = int(item.get("attempts") or 0) + 1
            break
    save_store(job_id, store)
    return store


# ---- 待对账销账 -------------------------------------------------------------

REVIEW_STATES = ("needs_review", "failed", "stale")


def review_items(job_id: str, store: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """列出需要作者/对账处理才能继续的意图（只读，不写盘）。"""
    data = store if store is not None else load_store(job_id)
    return [{"chapter_id": item.get("chapter_id"), "state": item.get("state"),
             "planned_at": item.get("planned_at"), "last_error": item.get("last_error"),
             "attempts": item.get("attempts")}
            for item in data.get("intents") or []
            if isinstance(item, Mapping) and item.get("state") in REVIEW_STATES]


def resolve_review(job_id: str, chapter_id: Any, resolution: str = "cancelled", *,
                   note: str = "", store: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """销账：作者确认平台没有这章 → 取消并回到候选池；确认要重排 → 放回 planned。

    没有这个入口时，一条结果未知的意图会让排期永久停写（scheduled_delivery 遇到
    needs_review 就整轮不写），而被卡住的章既不重试也无法人工解除。
    """
    store = store if store is not None else load_store(job_id)
    wanted = str(resolution or "cancelled")
    if wanted not in ("cancelled", "planned"):
        raise ValueError("resolution 只支持 cancelled 或 planned")
    target = str(chapter_id)
    changed = 0
    for item in store["intents"]:
        if not isinstance(item, dict) or str(item.get("chapter_id")) != target:
            continue
        if item.get("state") not in REVIEW_STATES:
            continue
        item["state"] = wanted
        item["last_error"] = str(note or f"作者销账：{wanted}")[:300]
        item["attempts"] = 0 if wanted == "planned" else int(item.get("attempts") or 0)
        item["resolved_at"] = _now_iso()
        changed += 1
    if not changed:
        return {"changed": 0, "state": "", "reason": "没有待对账的意图"}
    store["recompute_required"] = wanted == "planned"
    save_store(job_id, store)
    return {"changed": changed, "state": wanted, "chapter_id": target,
            "remaining": len(review_items(job_id))}


# ---- 对账 -------------------------------------------------------------------

def reconcile(job_id: str, snapshot: Mapping[str, Any], *, capability: Optional[Mapping[str, Any]] = None,
              store: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """只读对账：五项身份 + 正文身份都对上才算已排期；终态不因缺行降级。"""
    store = store if store is not None else load_store(job_id)
    allowed, reason = ps.can_auto_schedule(capability or {})
    if not allowed:
        # 能力未证实时只记录“无法判定”，不改动任何意图状态，也不虚增已发数。
        result = {"status": "capability_unknown", "reason": reason, "checked": 0,
                  "verified": 0, "needs_review": 0, "published": 0, "missing": 0}
        store["last_reconcile"] = {**result, "at": _now_iso()}
        save_store(job_id, store)
        return result

    complete = bool(snapshot.get("complete", True))
    index: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
    for row in snapshot.get("entries") or []:
        if not isinstance(row, Mapping) or not row.get("identity_ok", True):
            continue
        index[(str(row.get("platform") or ""), str(row.get("account") or ""),
               str(row.get("book_id") or ""), str(row.get("chapter_id") or ""))] = dict(row)

    verified = review = published = missing = unchanged = 0
    for item in store["intents"]:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "")
        if state in ("cancelled",) or state == "published":
            continue
        if state == "scheduled_verified":
            unchanged += 1
            continue
        if state not in ("planned", "submitted", "needs_review", "stale", "expired"):
            unchanged += 1
            continue
        row = index.get((str(item.get("platform") or ""), str(item.get("account") or ""),
                         str(item.get("book_id") or ""), str(item.get("chapter_id") or "")))
        if row is None:
            if complete and state in ("submitted",):
                item["state"] = "needs_review"
                item["last_error"] = "平台快照中没有该章记录"
                review += 1
            else:
                missing += 1
            continue
        row_state = str(row.get("state") or "")
        if row_state in (ps.STATE_PUBLISHED,):
            # 已发布不是“跳过校验”的理由：平台若返回了正文身份/计划时刻，必须对上，
            # 否则可能把别章、别版本的发布记到这条意图上。
            problems = []
            body = str(row.get("content_sha256") or "").lower()
            if body and body != str(item.get("version_sha256") or "").lower():
                problems.append("平台已发正文身份与审定版本不一致")
            planned = row.get("planned_at")
            if planned and not ps.same_instant(planned, item.get("planned_at")):
                problems.append("平台记录的计划时刻与意图不一致")
            if problems:
                item["state"] = "needs_review"
                item["last_error"] = "；".join(problems)[:300]
                review += 1
                continue
            item["state"] = "published"
            item["remote"] = {"chapter_id": row.get("chapter_id"), "book_id": row.get("book_id"),
                              "account": row.get("account"), "planned_at": row.get("planned_at"),
                              "content_sha256": body,
                              "body_verified": bool(body),
                              "planned_at_verified": bool(planned)}
            published += 1
            continue
        problems: List[str] = []
        if row_state != ps.STATE_SCHEDULED:
            problems.append(f"平台状态为 {row_state or 'unknown'}，不是已排期")
        if not ps.same_instant(row.get("planned_at"), item.get("planned_at")):
            problems.append("计划时刻与意图不一致")
        body = str(row.get("content_sha256") or "").lower()
        if not body:
            problems.append("平台未返回正文身份")
        elif body != str(item.get("version_sha256") or "").lower():
            problems.append("平台正文身份与审定版本不一致")
        if problems:
            item["state"] = "needs_review"
            item["last_error"] = "；".join(problems)[:300]
            review += 1
            continue
        item["state"] = "scheduled_verified"
        item["remote"] = {"chapter_id": row.get("chapter_id"), "book_id": row.get("book_id"),
                          "account": row.get("account"), "planned_at": row.get("planned_at"),
                          "content_sha256": body}
        item["verified_at"] = _now_iso()
        verified += 1

    result = {"status": "ok", "checked": verified + review + published + missing,
              "verified": verified, "needs_review": review, "published": published,
              "missing": missing, "unchanged": unchanged, "complete": complete}
    store["last_reconcile"] = {
        **result,
        "at": _now_iso(),
        # 只留判断“平台已占哪些章”所需的最小字段，供下一轮 plan 去重。
        "rows": [{"chapter_id": row.get("chapter_id"), "state": row.get("state"),
                  "platform": row.get("platform"), "account": row.get("account"),
                  "book_id": row.get("book_id"), "planned_at": row.get("planned_at"),
                  "content_sha256": row.get("content_sha256")}
                 for row in index.values()][:400],
    }
    store["recompute_required"] = False
    save_store(job_id, store)
    return result


def coverage_summary(job_id: str, job: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """给界面/交接看的一行事实：平台确认到哪、在途多少、待核对多少、本地剩多少。"""
    store = load_store(job_id)
    verified = [item for item in store["intents"]
                if isinstance(item, Mapping) and item.get("state") == "scheduled_verified"]
    in_flight = [item for item in store["intents"]
                 if isinstance(item, Mapping) and item.get("state") in _open_states()]
    review = [item for item in store["intents"]
              if isinstance(item, Mapping) and item.get("state") in ("needs_review", "failed", "stale")]
    published = [item for item in store["intents"]
                 if isinstance(item, Mapping) and item.get("state") == "published"]
    until = max((str(item.get("planned_at") or "") for item in verified), default="")
    plan_data = store.get("plan") if isinstance(store.get("plan"), dict) else {}
    coverage = plan_data.get("coverage") if isinstance(plan_data.get("coverage"), dict) else {}
    return {
        "job_id": str(job_id),
        "verified": len(verified),
        "verified_until": until,
        "in_flight": len(in_flight),
        "needs_review": len(review),
        "published": len(published),
        "replenish_stopped": bool(store.get("replenish_stopped")),
        "recompute_required": bool(store.get("recompute_required")),
        "local_remaining": int(plan_data.get("local_remaining") or 0),
        "planned_until": str(coverage.get("until") or ""),
        "gap_at": str(coverage.get("gap_at") or ""),
        "gap_reason": str(coverage.get("gap_reason") or ""),
        "last_reconcile": store.get("last_reconcile") or {},
        "updated_at": str(store.get("updated_at") or ""),
        "revision": int(store.get("revision") or 0),
    }
