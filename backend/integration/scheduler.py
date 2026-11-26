"""小说助手的日更调度层。

每个 job 独立记录：写作项目、番茄书名、番茄账号、每日时间和每次章节数。
Codex/GPT 的定时任务只需要调用 ``run-once --job-id <id>``；本地 ``daemon``
则是没有外部调度器时的备用方案。所有调度状态和运行日志都留在 O 盘。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time as time_module
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from . import bridge, writer_runner
except ImportError:
    import bridge
    import writer_runner


COMBINED_ROOT = bridge.COMBINED_ROOT
SCHEDULER_PATH = bridge._path_from_env(
    "NOVEL_HELPER_SCHEDULER", COMBINED_ROOT / "integration_data" / "scheduler.json"
)
RUNS_ROOT = COMBINED_ROOT / "integration_data" / "runs"


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


def _now_for_job(job: Dict[str, Any]) -> datetime:
    timezone_name = str(job.get("timezone", "Asia/Shanghai") or "Asia/Shanghai")
    try:
        return datetime.now(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"无法加载时区：{timezone_name}；请检查 tzdata") from exc


def _job_today(job: Dict[str, Any]) -> str:
    return _now_for_job(job).date().isoformat()


def _now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")


def _read_scheduler() -> Dict[str, Any]:
    data = writer_runner.strict_json(SCHEDULER_PATH, {})
    if not isinstance(data, dict):
        raise ValueError("scheduler.json 必须是对象")
    data.setdefault("version", 2)
    data.setdefault("revision", 0)
    data.setdefault("updated_at", "")
    data.setdefault("jobs", {})
    if not isinstance(data["jobs"], dict):
        raise ValueError("scheduler jobs 必须是对象")
    # Legacy date approvals are no longer an execution gate. Preserve frozen
    # chapters, evidence and all author choices; normalize only the old mode.
    for job in data['jobs'].values():
        if isinstance(job,dict) and job.get('approval_mode')=='confirm_24h':
            job['enabled']=False
    data.setdefault("settings", {"auto_schedule": False})
    if not isinstance(data["settings"], dict):
        raise ValueError("scheduler settings 必须是对象")
    data["settings"].setdefault("auto_schedule", False)
    return data


def config_lock():
    """Shared CLI/API configuration lock; prefer public mutation helpers."""
    return writer_runner.file_lock(SCHEDULER_PATH.with_name(SCHEDULER_PATH.name + ".lock"), blocking=True)


def load_scheduler() -> Dict[str, Any]:
    with config_lock():
        return _read_scheduler()


def _save_scheduler(data: Dict[str, Any]) -> None:
    data["version"] = 2
    data["revision"] = int(data.get("revision", 0)) + 1
    data["updated_at"] = bridge.now_iso()
    writer_runner.atomic_json(SCHEDULER_PATH, data)


def save_scheduler(data: Dict[str, Any]) -> None:
    with config_lock():
        if data.get("revision", 0) != _read_scheduler().get("revision", 0):
            raise RuntimeError("配置已更新，请重新读取后修改")
        _save_scheduler(data)


@contextmanager
def config_transaction():
    """Read/modify/write under one lock; yields a mutable config snapshot."""
    with config_lock():
        data = _read_scheduler()
        yield data
        _save_scheduler(data)


_JOB_FIELDS = {"name", "project", "book", "account", "daily_time", "timezone",
               "chapters_per_run", "word_count", "max_revisions", "volume",
               "approval_mode", "enabled", "daily_times", "quota_phases", "slot_quotas", "delivery_mode",
               "daily_word_goals", "recovery_policy", "publication_mode", "schedule_buffer",
               "platform"}

# 投递方式与发布方式是两个正交概念：
#   delivery_mode    = batch | serial   —— 一次跑几章、怎么串起来
#   publication_mode = draft_only | publish_now | platform_scheduled
#                      —— 写完是本机存稿、立刻投平台，还是先进排期缓冲等平台定时发布
# 旧任务没有 publication_mode 字段，它们是在只有发布语义的版本里建的，一律按 publish_now 处理；
# platform_scheduled 只在排期能力被证实后才真正代提交，否则降级为本地存稿候选（见 scheduled_delivery）。
PUBLICATION_MODES = ("draft_only", "publish_now", "platform_scheduled")
UNSUPPORTED_PUBLICATION_MODES: tuple = ()
LEGACY_PUBLICATION_MODE = "publish_now"


def publication_mode(job: Dict[str, Any]) -> str:
    raw = job.get("publication_mode")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return LEGACY_PUBLICATION_MODE
    return str(raw).strip()


def is_draft_only(job: Dict[str, Any]) -> bool:
    return publication_mode(job) == "draft_only"


def is_publish_job(job: Dict[str, Any]) -> bool:
    """这条任务是否会立刻向平台写入。只存稿与排期任务返回 False。"""
    return publication_mode(job) == "publish_now"


def is_scheduled_job(job: Dict[str, Any]) -> bool:
    """排期任务：先本机审定，再按能力决定是否代提交定时发布。"""
    return publication_mode(job) == "platform_scheduled"


def remote_state(job: Dict[str, Any]) -> str:
    """平台侧状态。只存稿任务没有远端意图，明确标注为不适用，绝不显示成“已发”。"""
    if is_draft_only(job):
        return "not_applicable"
    cycle = job.get("cycle") if isinstance(job.get("cycle"), dict) else {}
    if is_scheduled_job(job):
        # 排期任务的本地存稿成功只代表“稿子写好了”。已发布只能来自对账证据
        # （scheduled_verified / published），绝不能从 last_status 推断。
        state = str(cycle.get("remote_state") or "")
        if state in {"capability_unknown", "scheduled_pending", "local_draft",
                     "scheduled_verified", "needs_review", "published", "not_attempted"}:
            return state
        return "not_submitted"
    if cycle.get("status") == "failed":
        return "unknown"
    if cycle.get("remote_state") in {"pending_verification", "published", "unknown", "not_submitted"}:
        return cycle["remote_state"]
    if job.get("last_status") == "success":
        return "published"
    return "not_submitted"


def draft_tally(job: Dict[str, Any]) -> Dict[str, Any]:
    """按本地回执统计存稿进度：正文已保存 / 审查通过 / 待处理。全部来自本机文件事实。"""
    cycle = job.get("cycle") if isinstance(job.get("cycle"), dict) else {}
    chapters = [item for item in cycle.get("draft_chapters", []) if isinstance(item, dict)]
    saved = [item for item in chapters if item.get("body_saved")]
    reviewed = [item for item in chapters if item.get("review_passed")]
    return {
        "saved": len(saved),
        "reviewed": len(reviewed),
        "pending": len([i for i in cycle.get("target_ids", []) if i not in {c.get("chapter_id") for c in reviewed}]),
        "words": sum(int(item.get("words") or 0) for item in reviewed),
        "updated_at": cycle.get("updated_at", ""),
    }


def validate_publication_mode(value: Any) -> str:
    if value is None:
        return LEGACY_PUBLICATION_MODE
    if not isinstance(value, str) or not value.strip():
        raise ValueError("publication_mode 必须是 draft_only、publish_now 或 platform_scheduled")
    mode = value.strip()
    if mode in UNSUPPORTED_PUBLICATION_MODES:
        raise ValueError("本版不支持该发布方式")
    if mode not in PUBLICATION_MODES:
        raise ValueError("publication_mode 必须是 draft_only、publish_now 或 platform_scheduled")
    return mode


def validate_slot_quotas(value):
    if value is None:
        return
    if not isinstance(value, dict) or not 1 <= len(value) <= 8:
        raise ValueError("slot_quotas 必须是1–8个时间点的章数映射")
    for slot, count in value.items():
        if _validate_time(slot) != slot or type(count) is not int or not 1 <= count <= 50:
            raise ValueError("时段配额必须是HH:MM和1–50章")


def validate_quota_phases(phases):
    if not isinstance(phases, list) or len(phases) > 24:
        raise ValueError("quota_phases 必须是最多24项的列表")
    previous_end = None
    for phase in phases:
        required = {"start_date", "end_date", "chapters_per_run", "word_count"}
        if not isinstance(phase, dict) or not required <= set(phase) or set(phase) - required - {"slot_quotas"}:
            raise ValueError("阶段必须明确起止日期、章数和单章目标字数")
        dates = []
        for key in ("start_date", "end_date"):
            value = phase[key]
            if not isinstance(value, str):
                raise ValueError("阶段日期必须为YYYY-MM-DD")
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError as exc:
                raise ValueError("阶段日期必须为YYYY-MM-DD") from exc
            if parsed.isoformat() != value:
                raise ValueError("阶段日期必须为YYYY-MM-DD")
            dates.append(parsed)
        start, end = dates
        if start > end or previous_end is not None and start <= previous_end:
            raise ValueError("阶段日期需递增且不能重叠")
        previous_end = end
        if type(phase["chapters_per_run"]) is not int or not 1 <= phase["chapters_per_run"] <= 50:
            raise ValueError("阶段每次章节数需为1–50")
        if type(phase["word_count"]) is not int or not 500 <= phase["word_count"] <= 10000:
            raise ValueError("阶段单章目标字数需为500–10000")
        validate_slot_quotas(phase.get("slot_quotas"))


def quota_for_date(job, day, slot=None):
    """Date-bound overrides; the normal quota resumes without a timer mutation."""
    phases = job.get("quota_phases", [])
    validate_quota_phases(phases)
    quota = {"chapters_per_run": job.get("chapters_per_run", 1),
             "word_count": job.get("word_count", 3500)}
    slots = job.get("slot_quotas")
    validate_slot_quotas(slots)
    for phase in phases:
        if phase["start_date"] <= day <= phase["end_date"]:
            quota.update({key: phase[key] for key in quota})
            slots = phase.get("slot_quotas", slots)
            break
    if slots is not None:
        if set(slots) - set(job_times(job)):
            raise ValueError("时段配额含未登记的每日时间")
        if slot is not None:
            quota["chapters_per_run"] = slots.get(slot.rsplit('@', 1)[-1], 0)
        quota["daily_chapters"] = sum(slots.values())
    else:
        quota["daily_chapters"] = quota["chapters_per_run"] * len(job_times(job))
    return quota


def job_times(job):
    values=job.get("daily_times") or [job.get("daily_time","00:00")]
    if not isinstance(values,list) or not 1<=len(values)<=8 or any(not isinstance(v,str) for v in values):
        raise ValueError("每日时间需为 1–8 个 HH:MM")
    times=[_validate_time(v) for v in values]
    if len(set(times))!=len(times):raise ValueError("每日时间不能重复")
    return sorted(times)


def completed_slots(job,day):
    if "completed_slots" not in job and job.get("last_run_date")==day:
        # 旧版本只有单个 daily_time：迁移时只能确定“第一个时段”已跑过。
        # 旧实现返回全部时段，会在多时段任务上静默吞掉当天剩余配额。
        return {day+"@"+job_times(job)[0]}
    values=job.get("completed_slots",[])
    if not isinstance(values,list) or any(not isinstance(v,str) for v in values):raise ValueError("调度完成记录损坏")
    return set(values)


def material_change(first,second):
    # A word goal authorizes future supplemental cycles, never changes the
    # frozen IDs, account, content qualification or quota of an active cycle.
    for key in _JOB_FIELDS-{"name","enabled","daily_word_goals","recovery_policy"}:
        a=job_times(first) if key=="daily_times" else job_times(first)[0] if key=="daily_time" else first.get(key)
        b=job_times(second) if key=="daily_times" else job_times(second)[0] if key=="daily_time" else second.get(key)
        if a!=b:return True
    return False


def _validate_job(job: Dict[str, Any]) -> None:
    goals = job.get('daily_word_goals', {})
    if not isinstance(goals, dict) or len(goals) > 31:
        raise ValueError('每日字数目标必须为最多31个日期的映射')
    for day, target in goals.items():
        try:
            if datetime.strptime(day, '%Y-%m-%d').date().isoformat() != day:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('每日字数目标日期无效') from None
        if type(target) is not int or not 1 <= target <= 2000000:
            raise ValueError('每日字数目标需为1–2000000的整数')
    if job.get("delivery_mode", "batch") not in {"batch", "serial"}:
        raise ValueError("delivery_mode 必须为batch或serial")
    policy = job.get('recovery_policy', {})
    if not isinstance(policy,dict) or set(policy)-{'extra_attempts_per_day'}:
        raise ValueError('额外恢复策略无效')
    maximum=policy.get('extra_attempts_per_day',0)
    if maximum is not None and (type(maximum) is not int or not 0<=maximum<=6):
        raise ValueError('额外恢复次数需为0–6的整数，或null表示不限次数')
    validate_quota_phases(job.get("quota_phases", []))
    validate_slot_quotas(job.get("slot_quotas"))
    mode = validate_publication_mode(job.get("publication_mode"))
    job["publication_mode"] = mode
    # 只存稿只要求“作品已登记 + 时间合法 + 有可用模型”；账号、平台绑定、登录态都属于发布资格，
    # 在这里分流，避免作者为了往本地写稿被迫先登录平台。排期任务最终仍会写平台，所以
    # 账号是必填；但登录态只在真正代提交那一刻检查，能力未证实时不拦本地存稿。
    for field in ("project", "book") + (("account",) if mode != "draft_only" else ()):
        if not isinstance(job.get(field), str) or not job[field].strip():
            raise ValueError(f"任务缺少 {field}")
        job[field] = job[field].strip()
    if mode == "draft_only":
        job["account"] = str(job.get("account") or "").strip()
    if mode == "platform_scheduled":
        from integration import schedule_buffer
        job["schedule_buffer"] = schedule_buffer.validate_settings(job.get("schedule_buffer") or {})
    root = Path(job["project"]).expanduser().resolve()
    if not root.is_dir() or not (root / "正文").is_dir():
        raise FileNotFoundError(f"项目或正文目录不存在：{root}")
    job["project"] = str(root)
    if mode == "publish_now" and not bridge.account_state_path(job["account"]).is_file():
        raise FileNotFoundError("任务账号尚未登录")
    job["daily_time"] = _validate_time(job.get("daily_time", "00:00"))
    if job.get("daily_times"):
        job["daily_times"]=job_times(job)
        job["daily_time"]=job["daily_times"][0]
    job["timezone"] = str(job.get("timezone", "Asia/Shanghai") or "Asia/Shanghai").strip()
    job["platform"] = str(job.get("platform") or "fanqie").strip().lower()
    _now_for_job(job)
    for field, minimum, default in (("chapters_per_run", 1, 1), ("word_count", 1, 3500), ("max_revisions", 0, 1)):
        value = job.get(field, default)
        if type(value) is not int or value < minimum:
            raise ValueError(f"{field} 必须是大于等于 {minimum} 的整数")
    if job.get("volume") is not None and (type(job["volume"]) is not int or job["volume"] <= 0):
        raise ValueError("volume 必须是正整数或 null")
    name = job.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 96:
        raise ValueError("name 必须是 1–96 字")
    if type(job.get("enabled", True)) is not bool:
        raise ValueError("enabled 必须是布尔值")
    if job.get("approval_mode", "unattended") not in {"unattended", "confirm_24h"}:
        raise ValueError("approval_mode 无效")
    if job.get("slot_quotas") is not None and set(job["slot_quotas"]) - set(job_times(job)):
        raise ValueError("时段配额含未登记的每日时间")
    for phase in job.get("quota_phases", []):
        quota_for_date(job, phase["start_date"])


def _binding_key(job: Dict[str, Any]) -> tuple:
    return (str(job.get("platform") or "fanqie").strip().lower(),
            bridge.safe_dir_name(job.get("account", "")).casefold(),
            bridge.safe_dir_name(job.get("book", "")).casefold())


def _check_binding(data: Dict[str, Any], job_id: str, job: Dict[str, Any]) -> None:
    # 只存稿任务不占平台队列/归档，因此既不与别人抢书名，也不该被别的任务的绑定卡住。
    if is_draft_only(job):
        return
    book = bridge.safe_dir_name(job["book"]).casefold()
    key = _binding_key(job)
    for other_id, other in data["jobs"].items():
        if other_id == job_id or not isinstance(other, dict) or is_draft_only(other):
            continue
        if bridge.safe_dir_name(other.get("book", "")).casefold() != book:
            continue
        # Queue/archive/manifest are keyed by book only, not by account.
        if _binding_key(other) != key:
            raise ValueError("同名或安全化后同名书籍不能绑定不同项目或账号")
        if Path(other.get("project", "")).resolve() != Path(job["project"]).resolve():
            raise ValueError("同名或安全化后同名书籍不能绑定不同项目或账号")
        if is_scheduled_job(job) and is_scheduled_job(other):
            # 两个排期任务各自记账、各自提交，同一本书会双写；T10/T27 要求单执行者。
            raise ValueError("同一平台账号与书籍只能有一个排期任务")


class DuplicatePublicationMode(ValueError, FileExistsError):
    """A second job for the same project + mode would double-write the book.

    Inherits both ValueError (scheduler/API callers already treat it as a
    request conflict) and FileExistsError so the manager's existing exception
    handler answers HTTP 409 instead of 400.
    """


def _check_duplicate_publication_mode(data: Dict[str, Any], job_id: str, job: Dict[str, Any]) -> None:
    """One job per project + publication mode.

    Two tasks with the same project and the same mode each keep their own cycle
    and quota and would write the same book twice. POST already collapses this
    case; PUT must not reintroduce it by changing one job's mode.
    """
    mode = publication_mode(job)
    project = str(Path(job.get("project") or "").expanduser().resolve())
    for other_id, other in data["jobs"].items():
        if other_id == job_id or not isinstance(other, dict):
            continue
        if publication_mode(other) != mode:
            continue
        if str(Path(other.get("project") or "").expanduser().resolve()) == project:
            raise DuplicatePublicationMode(f"该作品已有相同发布方式（{mode}）的任务：{other_id}")


def update_job(job_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(changes, dict) or set(changes) - _JOB_FIELDS:
        raise ValueError("changes 含未知或运行状态字段")
    with config_transaction() as data:
        old = data["jobs"].get(job_id)
        if not isinstance(old, dict):
            raise KeyError(f"找不到日更任务：{job_id}")
        job = {**old, **changes}
        _validate_job(job)
        job['approval_mode']=changes.get('approval_mode', old.get('approval_mode', 'unattended'))
        if old.get("cycle", {}).get("status") != "success" and old.get("cycle"):
            if material_change(job,old):
                cycle = old["cycle"]
                without_phase_change = {**job, "quota_phases": old.get("quota_phases")}
                future_phase_only = (
                    cycle.get("status") in {"failed", "partial"}
                    and not material_change(without_phase_change, old)
                    and quota_for_date(job, cycle["run_date"], cycle.get("slot"))
                        == quota_for_date(old, cycle["run_date"], cycle.get("slot"))
                )
                if not future_phase_only:
                    raise ValueError("未完成批次只能修改 name、enabled或不影响原批次的未来阶段；请先恢复该批次")
        _check_binding(data, job_id, job)
        _check_duplicate_publication_mode(data, job_id, job)
        if material_change(job,old):
            job.pop("approved_for", None)
        data["jobs"][job_id] = job
    return _job_summary(job_id, job)


def update_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
    if set(changes) != {"auto_schedule"} or type(changes["auto_schedule"]) is not bool:
        raise ValueError("settings 仅接受布尔 auto_schedule")
    with config_transaction() as data:
        data["settings"].update(changes)
        result = dict(data["settings"])
    return result


def next_due(job: Dict[str, Any], now: Optional[datetime] = None) -> Optional[str]:
    """Next daily instant in job timezone (ISO string); disabled => None."""
    if not job.get("enabled", True):
        return None
    current = now.astimezone(ZoneInfo(job.get("timezone", "Asia/Shanghai"))) if now else _now_for_job(job)
    retry_at = _draft_retry_at(job)
    if retry_at:
        return retry_at.isoformat()
    day=current.date().isoformat();completed=completed_slots(job,day)
    attempted = str(job.get("last_attempt_slot") or "")
    cycle_status = (job.get("cycle") or {}).get("status")
    for value in job_times(job):
        slot = day + "@" + value
        if job.get("last_status") != "awaiting_approval" and cycle_status != "continuing" and attempted.startswith(day + "@") and slot <= attempted:
            continue
        if slot not in completed:
            hh,mm=map(int,value.split(":"))
            return current.replace(hour=hh,minute=mm,second=0,microsecond=0).isoformat()
    if job.get('delivery_mode')=='serial' and job.get('daily_word_goals',{}).get(day):
        from integration.daily_word_goal import progress
        goal=progress(job,day)
        if goal['confirmed_words']<goal['target']:
            hh,mm=map(int,job_times(job)[0].split(':'))
            return current.replace(hour=hh,minute=mm,second=0,microsecond=0).isoformat()
    hh,mm=map(int,job_times(job)[0].split(":"))
    return (current.replace(hour=hh,minute=mm,second=0,microsecond=0)+timedelta(days=1)).isoformat()


def _draft_retry_at(job):
    cycle = job.get("cycle") or {}
    if (publication_mode(job) not in {"draft_only", "platform_scheduled"}
            or cycle.get("status") != "waiting"
            or not (cycle.get("recovery") or {}).get("automatic_retry")):
        return None
    try:
        value = datetime.fromisoformat(cycle["next_retry_at"])
        return value if value.tzinfo else None
    except (KeyError, ValueError, TypeError):
        return None


def retryable(job: Dict[str, Any], slot: str) -> bool:
    """上一个时段留下的 running/failed/needs_revision 允许在新时段重试。

    同一时段内不重试：崩溃或审查未过可能是确定性原因，循环重跑只会烧钱。
    跨时段重试才符合「只补缺步」——强杀留下的 running 不会永久停更。
    """
    status = (job.get("cycle") or {}).get("status")
    if status not in {"running", "continuing", "failed", "needs_revision"}:
        return False
    attempted = str(job.get("last_attempt_slot") or "")
    return bool(attempted) and attempted != slot


def due_jobs(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Due job summaries; master switch defaults off. Does not run jobs."""
    data = load_scheduler()
    if data["settings"].get("auto_schedule") is not True:
        return []
    result = []
    for job_id, job in data["jobs"].items():
        if not isinstance(job, dict):
            continue
        current = now.astimezone(ZoneInfo(job.get("timezone", "Asia/Shanghai"))) if now else _now_for_job(job)
        due = next_due(job, current)
        if not due or datetime.fromisoformat(due) > current:
            continue
        today = current.date().isoformat()
        if _check_approval(job, today):
            continue
        # A failed publication may have reached the server. Retry is an explicit
        # run-once action, not a daemon loop which blindly repeats side effects.
        slot=today+"@"+datetime.fromisoformat(due).strftime("%H:%M")
        recovering = retryable(job, slot) or _draft_retry_at(job) is not None
        cycle_status = (job.get("cycle") or {}).get("status")
        if cycle_status not in {"success", "continuing", None} and job.get("last_status") != "awaiting_approval" and not recovering:
            continue
        late_goal=False
        if job.get('delivery_mode')=='serial' and (job.get('cycle') or {}).get('status') in {None,'success'} and job.get('daily_word_goals',{}).get(today):
            from integration.daily_word_goal import progress
            goal=progress(job,today);late_goal=goal['confirmed_words']<goal['target'] and not goal['unknown_word_counts']
        if not late_goal and not recovering and cycle_status != "continuing" and (job.get("last_attempt_slot")==slot or not job.get("last_attempt_slot") and job.get("last_attempt_date")==today) and job.get("last_status")!="awaiting_approval":
            continue
        result.append(_job_summary(job_id, job) | {"next_due": due, "recovering": bool(recovering)})
    return result


def normalize_job_id(value: str) -> str:
    value = str(value or "").strip()
    value = value.replace(" ", "-")
    value = bridge.safe_dir_name(value).strip(" .")
    if not value:
        value = f"job-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    return value[:80]


def _validate_time(value: str) -> str:
    try:
        parsed = datetime.strptime(str(value).strip(), "%H:%M")
    except ValueError as exc:
        raise ValueError("--time 必须是 HH:MM，例如 08:30") from exc
    return parsed.strftime("%H:%M")


def _job_summary(job_id: str, job: Dict[str, Any]) -> Dict[str, Any]:
    from integration.daily_word_goal import progress
    from manager.job_progress import read as runtime_progress
    try:runtime=runtime_progress(job,SCHEDULER_PATH.parent/'costs.sqlite3',_now_for_job(job))
    except (ValueError,OSError,KeyError,__import__('sqlite3').Error):runtime={'unavailable':True}
    return {
        "id": job_id,
        "name": job.get("name", job_id),
        "enabled": bool(job.get("enabled", True)),
        "project": job.get("project"),
        "platform": job.get("platform") or "fanqie",
        "book": job.get("book"),
        "account": job.get("account"),
        "daily_time": job.get("daily_time"),
        "daily_times": job_times(job),
        "next_due": next_due(job),
        "timezone": job.get("timezone", "Asia/Shanghai"),
        "chapters_per_run": job.get("chapters_per_run", 1),
        "word_count": job.get("word_count", 3500),
        "max_revisions": job.get("max_revisions", 1),
        "volume": job.get("volume"),
        "approval_mode": job.get("approval_mode", "unattended"),
        "last_attempt_date": job.get("last_attempt_date", ""),
        "last_run_date": job.get("last_run_date", ""),
        "last_status": job.get("last_status", ""),
        "last_message": job.get("last_message", ""),
        "approved_for": job.get("approved_for", ""),
        "cycle": copy.deepcopy(job.get("cycle", {})),
        "quota_phases": copy.deepcopy(job.get("quota_phases", [])),
        "effective_quota": quota_for_date(job, _job_today(job)),
        "slot_quotas": copy.deepcopy(job.get("slot_quotas")),
        "delivery_mode": job.get("delivery_mode", "batch"),
        "publication_mode": publication_mode(job),
        "remote_state": remote_state(job),
        "drafts": draft_tally(job),
        "daily_word_goals": copy.deepcopy(job.get('daily_word_goals',{})),
        "daily_word_goal": progress(job,_job_today(job)),
        'runtime':runtime,
    }


def add_job(args: argparse.Namespace) -> Dict[str, Any]:
    job_id = normalize_job_id(args.job_id)
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        raise FileNotFoundError(f"项目目录不存在：{project}")
    # 新任务默认只存稿：先把正文稳定写进本机，需要发布时由作者显式改成 publish_now。
    mode = validate_publication_mode(getattr(args, "publication_mode", None) or "draft_only")
    account = str(getattr(args, "account", "") or "").strip()
    if mode in {"publish_now", "platform_scheduled"} and not account:
        raise ValueError("发布或排期任务必须指定账号")
    if mode == "publish_now":
        if not bridge.account_state_path(account).is_file():
            raise FileNotFoundError(
                f"账号“{account}”尚未登录：{bridge.account_state_path(account)}。"
                "请先执行 bridge.py login --account。"
            )
    chapters_per_run = int(args.chapters_per_run)
    word_count = int(args.word_count)
    max_revisions = int(args.max_revisions)
    if chapters_per_run <= 0:
        raise ValueError("--chapters-per-run 必须大于 0")
    if word_count <= 0:
        raise ValueError("--word-count 必须大于 0")
    if max_revisions < 0:
        raise ValueError("--max-revisions 不能小于 0")
    approval_mode = args.approval_mode
    if approval_mode not in {"unattended", "confirm_24h"}:
        raise ValueError("approval_mode 只能是 unattended 或 confirm_24h")
    if approval_mode == 'confirm_24h':
        raise ValueError('旧版按日期确认模式不再自动执行，请明确选择无人值守或手动运行')

    job = {
        "name": args.name or job_id,
        "project": str(project),
        "book": args.book.strip(),
        "account": account,
        "publication_mode": mode,
        "platform": str(getattr(args, "platform", "fanqie") or "fanqie"),
        "schedule_buffer": copy.deepcopy(getattr(args, "schedule_buffer", None) or {}),
        "daily_time": _validate_time(args.daily_time),
        "daily_times": getattr(args,"daily_times",None) or [],
        "quota_phases": copy.deepcopy(getattr(args, "quota_phases", [])),
        "slot_quotas": copy.deepcopy(getattr(args, "slot_quotas", None)),
        "delivery_mode": getattr(args, "delivery_mode", "batch"),
        "timezone": args.timezone.strip() or "Asia/Shanghai",
        "chapters_per_run": chapters_per_run,
        "word_count": word_count,
        "max_revisions": max_revisions,
        "volume": args.volume,
        "approval_mode": approval_mode,
        "enabled": getattr(args, "enabled", not getattr(args, "disabled", False)),
        "created_at": bridge.now_iso(),
        "last_attempt_date": "",
        "last_run_date": "",
        "last_status": "",
    }
    if not job["book"]:
        raise ValueError("--book 不能为空")
    _validate_job(job)
    with config_transaction() as data:
        if job_id in data["jobs"]:
            raise ValueError(f"任务已存在：{job_id}")
        _check_binding(data, job_id, job)
        data["jobs"][job_id] = job
    return _job_summary(job_id, job)


def _compact_generation(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key not in {"review", "executor"}
    }


def _write_run_record(job_id: str, record: Dict[str, Any]) -> str:
    destination = RUNS_ROOT / bridge.safe_dir_name(job_id) / f"{_now_stamp()}-{uuid.uuid4().hex[:8]}.json"
    bridge.write_json_atomic(destination, record)
    return str(destination)


def _published_ids(book: str, account: Optional[str] = None) -> List[int]:
    folder = bridge.UPLOADED_ROOT / bridge.safe_dir_name(book)
    return sorted(chapter for chapter, path in bridge.archived_chapters(folder).items()
                  if bridge.valid_receipt(path, book, chapter, account))


def _queue_ids(book: str) -> List[int]:
    folder = bridge.QUEUE_ROOT / bridge.safe_dir_name(book)
    return sorted(bridge.queued_chapters(folder))


def _blocking_chapters(project: Path, published: Iterable[int] = ()) -> List[int]:
    """Chapters with an existing body but no valid publication receipt.

    ``blocking = existing - reviewed - published``. This covers every way a
    chapter can lose publication eligibility: never reviewed, needs_revision,
    handoff edited after its receipt, and duplicate chapter numbers (the receipt
    collection drops a chapter that maps to more than one body file).
    """
    path = Path(project)
    receipts = writer_runner.reviewed_chapters(path)
    existing = writer_runner.existing_chapter_ids(path)
    published_set = set()
    for value in published or ():
        try:
            published_set.add(int(value))
        except (TypeError, ValueError):
            continue
    return sorted((existing - set(receipts)) - published_set)


def human_pending_chapters(project: Path, published: Iterable[int] = ()) -> List[int]:
    """Chapters that block later scheduling.

    The historical name is kept for callers and receipts that still speak of
    "handoff"; the set is now the wider blocking set (unreviewed/needs_revision/
    stale receipt/duplicate), not just two-review handoffs.
    """
    return _blocking_chapters(Path(project), published)


def scheduled_human_pending_block(project: Path, published: Iterable[int] = ()) -> Optional[str]:
    """Block platform scheduling only when a later reviewed chapter would skip a blocking chapter."""
    path = Path(project)
    pending = human_pending_chapters(path, published)
    if not pending:
        return None
    published_set = set()
    for value in published or ():
        try:
            published_set.add(int(value))
        except (TypeError, ValueError):
            continue
    later = sorted(c for c in writer_runner.reviewed_chapters(path)
                   if c > pending[0] and c not in published_set)
    if later:
        return f"第 {pending} 章待人工复核，已阻止排期后续章节 {later}"
    return None


def split_targets_by_pending(pending: Sequence[int], targets: Sequence[int]):
    """Keep publishable targets before the earliest handoff; return (allowed, skipped)."""
    if not pending:
        return list(targets), []
    first = min(pending)
    return [t for t in targets if t < first], [t for t in targets if t >= first]


def targets_blocked_by_pending(pending: Sequence[int], targets: Sequence[int]) -> List[int]:
    """Targets at or after the earliest handoff must wait; earlier chapters may publish."""
    return split_targets_by_pending(pending, targets)[1]


def _check_approval(job: Dict[str, Any], run_date: str) -> Optional[str]:
    mode = job.get("approval_mode", "unattended")
    if mode not in {"unattended", "confirm_24h"}:
        raise ValueError("approval_mode 无效")
    if mode == 'confirm_24h':
        return '旧版确认任务已暂停，请重新选择执行方式'
    return None


def _update_run(job_id: str, changes: Dict[str, Any]) -> None:
    with config_transaction() as data:
        job = data["jobs"].get(job_id)
        if not isinstance(job, dict):
            raise KeyError(f"任务已删除：{job_id}")
        job.update(copy.deepcopy(changes))


def _unique_txt(folder: Path) -> Dict[int, Path]:
    result = {}
    for path in folder.rglob("*.txt"):
        parsed = bridge.parse_chapter_name(path.name)
        if path.is_symlink() or folder.resolve() not in path.resolve().parents:
            raise RuntimeError("不安全的章节路径")
        if not parsed or parsed[0] <= 0 or parsed[0] in result:
            raise RuntimeError(f"队列或归档存在无效/重复章节：{path.name}")
        result[parsed[0]] = path
    return result


def _body_hash(receipt: Dict[str, Any], chapter: int) -> str:
    body = bridge.markdown_to_plaintext(
        Path(receipt["destination"]).read_text(encoding="utf-8"), chapter
    )
    if not body.strip():
        raise RuntimeError(f"第{chapter}章转换后为空")
    return bridge.sha256_text(body)


def _verified_archive(book: str, receipts: Dict[int, Dict[str, Any]], account: str) -> List[int]:
    result = []
    archive = _unique_txt(bridge.UPLOADED_ROOT / bridge.safe_dir_name(book))
    for chapter, path in archive.items():
        if chapter in receipts:
            if bridge.sha256_text(path.read_text(encoding="utf-8")) != _body_hash(receipts[chapter], chapter):
                raise RuntimeError(f"第{chapter}章本地归档内容不匹配")
            if not bridge.valid_receipt(path, book, chapter, account):
                raise RuntimeError(f"第{chapter}章归档缺少对应账号的平台确认凭据，自动挂起并保留证据")
            result.append(chapter)
    return result


def _verify_queue(book: str, receipts: Dict[int, Dict[str, Any]]) -> Dict[int, Path]:
    folder = bridge.QUEUE_ROOT / bridge.safe_dir_name(book)
    queue = _unique_txt(folder)
    for chapter, path in queue.items():
        if path.parent != folder:
            raise RuntimeError("发布队列不能嵌套分卷目录")
        if chapter not in receipts:
            raise RuntimeError(f"队列第{chapter}章缺少绑定正文的通过审查记录")
        if bridge.sha256_text(path.read_text(encoding="utf-8")) != _body_hash(receipts[chapter], chapter):
            raise RuntimeError(f"队列第{chapter}章已被修改")
    return queue


def run_once(job_id: str, force: bool = False) -> Dict[str, Any]:
    # One pipeline lock protects shared book queues and bridge's global manifest
    # across jobs/config files. The writer has its own per-project process lock.
    try:
        from .model_roles import execution_snapshot
        with execution_snapshot(), writer_runner.file_lock(bridge.RUNTIME_ROOT / "scheduler-execution.lock"):
            candidate = load_scheduler()["jobs"].get(job_id)
            if (
                isinstance(candidate, dict)
                and is_publish_job(candidate)
                and candidate.get("project")
                and candidate.get("book")
                and (candidate.get("enabled", True) or force)
            ):
                # This is the bridge book lock, not the writer project lock.
                # Bridge nested calls share its reentrant implementation.
                with bridge.book_runtime(Path(candidate["project"]), candidate["book"]):
                    return _run_once_locked(job_id, force)
            return _run_once_locked(job_id, force)
    except RuntimeError as exc:
        if str(exc).startswith("已有任务正在运行：") or str(exc) == "resource_busy":
            return {"job_id": job_id, "status": "busy"}
        raise


def _run_once_locked(job_id: str, force: bool) -> Dict[str, Any]:
    data = load_scheduler()
    job = data["jobs"].get(job_id)
    if not isinstance(job, dict):
        raise KeyError(f"找不到日更任务：{job_id}")
    if not job.get("enabled", True) and not force:
        return {"job_id": job_id, "status": "disabled"}
    today = _job_today(job)
    cycle = copy.deepcopy(job.get("cycle") or {})
    if not isinstance(cycle, dict):
        raise ValueError("任务 cycle 必须是对象")
    remaining_slots=[today+"@"+value for value in job_times(job) if today+"@"+value not in completed_slots(job,today)]
    if not remaining_slots and (not cycle or cycle.get("status") == "success"):
        from integration.daily_word_goal import reserve
        extra=reserve(job,today) if job.get('delivery_mode')=='serial' else None
        if extra is None:
            return {"job_id": job_id, "status": "already_ran", "run_date": today}
        cycle=extra
    slot=cycle.get("slot") if cycle and cycle.get("status")!="success" else None
    slot=slot or (remaining_slots[0] if remaining_slots else today+"@"+job_times(job)[0])
    # --force retains its CLI meaning for enabled/date approval, but never
    # overrides a successful day's quota, review, or content integrity.
    run_date = cycle.get("run_date", today) if cycle and cycle.get("status") != "success" else today
    if cycle.get("status") == "success":
        cycle = {}
    _validate_job(job)
    _check_binding(data, job_id, job)
    quota = quota_for_date(job, run_date, slot)
    if not cycle and quota["chapters_per_run"] == 0:
        # Old manager processes can still dispatch a phase-only timer after the
        # phase ends. Consume that inactive slot without writing or publishing.
        completed = completed_slots(job, today)
        completed.add(slot)
        _update_run(job_id, {"completed_slots": sorted(completed)[-56:],
                            "last_attempt_slot": slot, "last_attempt_date": today})
        return {"job_id": job_id, "status": "already_ran", "reason": "inactive_slot", "slot": slot}
    project = Path(job["project"])
    book, account = job["book"], job["account"]
    if is_publish_job(job):
        binding = bridge.load_manifest().get("books", {}).get(bridge.safe_dir_name(book), {})
        if binding.get("project_root") and Path(binding["project_root"]).resolve() != project:
            raise RuntimeError("manifest 书籍已绑定其他项目")
    record = {"job_id": job_id, "started_at": bridge.now_iso(), "project": str(project),
              "book": book, "account": account, "run_date": run_date, "slot":slot, "status": "running",
              "generated": [], "verification": "platform_receipt_and_body_hash"}
    from integration.model_roles import routing_snapshot
    record['routing_snapshot']=routing_snapshot()
    dispatch_time = _now_for_job(job)
    dispatch_due = next_due(job, dispatch_time)
    dispatch_slot = slot
    if dispatch_due and datetime.fromisoformat(dispatch_due) <= dispatch_time:
        dispatch_slot = today + "@" + datetime.fromisoformat(dispatch_due).strftime("%H:%M")
    elif str(job.get("last_attempt_slot", "")).startswith(today + "@"):
        dispatch_slot = job["last_attempt_slot"]
    _update_run(job_id, {"last_attempt_date": today, "last_attempt_at": bridge.now_iso(),
                        "last_status": "running", "last_attempt_slot": dispatch_slot, "last_message": ""})
    try:
        if cycle.get('local_only') is True:
            # Explicit author-approved offline completion keeps the original
            # publisher queue/journal untouched, including rejected chapter51.
            # Route before publication qualification/queue gates: this mode
            # confers local-writing authority, never publication authority.
            if job.get('delivery_mode') != 'serial':
                raise ValueError('本地完稿必须使用原逐章执行器')
            from integration.local_completion import step as local_step
            record['quota']={'chapters_per_run':len(cycle['target_ids']),'word_count':cycle['word_count']}
            record['target_ids']=list(cycle['target_ids'])
            record['verification']='local_qualification_and_memory_only_not_platform_publication'
            return local_step(job_id,job,cycle,record,force)
        if is_scheduled_job(job):
            # 排期路径在 draft 生成前先过人工复核门禁：若更早章节待复核，
            # 后面已通过的章节不得被排到平台（否则读者看到跳章）。published
            # 章已落在平台上，不再参与“会被跳过”的阻塞集合。
            try:
                published_now = set(_published_ids(book, account))
            except Exception:  # noqa: BLE001 - 归档读不到时按“没有已发布章”处理
                published_now = set()
            scheduled_block = scheduled_human_pending_block(project, published=published_now)
            if scheduled_block:
                raise RuntimeError(scheduled_block)
            # 排期：同一套生成/审查/落稿，收尾后按平台能力决定是否代提交定时发布。
            # 能力未证实时这里只产出本地存稿候选，绝不会误报“已排期”。
            from integration.scheduled_delivery import step as scheduled_step
            record['verification']='platform_schedule_intent_and_readback_identity'
            record['remote_state']='scheduled_pending'
            return scheduled_step(job_id,job,cycle,quota,record,force)
        if is_draft_only(job):
            # 只存稿：在这里就分流，绕开归档凭据、发布队列、平台绑定与账号登录这些
            # “发表资格”检查。整条路径不会调用 stage_project / run_publish。
            from integration.draft_delivery import step as draft_step
            record['verification']='local_body_review_and_memory_only_no_remote_delivery'
            record['remote_state']='not_applicable'
            return draft_step(job_id,job,cycle,quota,record,force)
        receipts = writer_runner.reviewed_chapters(project)
        committed = writer_runner.committed_chapters(project)
        archive = _verified_archive(book, receipts, account)
        queue = _verify_queue(book, receipts)
        # Legacy/manual bodies have no review evidence. Never stage them in the
        # recovery path, or silently skip over them to publish later chapters.
        all_existing = writer_runner.existing_chapter_ids(project)
        published_set = set(_published_ids(book, account))
        human_pending = sorted((set(committed) - set(receipts)) & all_existing - published_set)
        # Handoff chapters are not "missing review" — they are blocked pending
        # human approval. Only targets at/after the earliest handoff are barred.
        unreviewed = all_existing - set(receipts) - set(committed) - published_set
        if unreviewed:
            raise RuntimeError(f"正文缺少有效审查记录：{sorted(unreviewed)}")
        if not cycle or cycle.get("status") == "success":
            pending = sorted(set(receipts) - set(archive))
            quota = quota_for_date(job, today, slot)
            count = quota["chapters_per_run"]
            targets = pending[:count]
            next_id = writer_runner.next_chapter_id(project)
            targets += list(range(next_id, next_id + count - len(targets)))
            cycle = {"run_date": today, "slot":slot,"target_ids": targets, "status": "running",
                     "word_count": quota["word_count"], "max_revisions": job["max_revisions"]}
            record["run_date"] = today
            _update_run(job_id, {"cycle": cycle})
        targets = cycle["target_ids"]
        # A recovery crossing midnight or the phase boundary keeps its original
        # chapter IDs and writing target. It never expands into the next quota.
        cycle.setdefault("word_count", quota_for_date(job, cycle["run_date"])["word_count"])
        cycle.setdefault("max_revisions", job["max_revisions"])
        record["quota"] = {"chapters_per_run": len(targets), "word_count": cycle["word_count"]}
        if (not isinstance(targets, list) or not targets
                or any(type(i) is not int or i <= 0 for i in targets)
                or len(set(targets)) != len(targets)):
            raise ValueError("持久化批次章节列表无效")
        targets, blocked_targets = split_targets_by_pending(human_pending, targets)
        if blocked_targets:
            if not targets:
                raise RuntimeError(
                    f"第 {min(human_pending)} 章待人工复核通过后再发布；本批目标 {blocked_targets} 已阻止")
            # 已通过的前序章继续发布，只跳过待复核章及其后续。
            cycle["target_ids"] = list(targets)
            cycle["skipped_pending"] = blocked_targets
            record["skipped_pending"] = blocked_targets
            record["target_ids"] = list(targets)
            record["quota"] = {"chapters_per_run": len(targets), "word_count": cycle["word_count"]}
        cycle['status']='running'
        cycle['stage']='B'
        cycle['total_count']=len(targets)
        cycle['completed_count']=0
        _update_run(job_id,{'cycle':cycle})
        record["target_ids"] = list(targets)
        if job.get("delivery_mode") == "serial":
            from integration.serial_delivery import step
            return step(job_id, job, cycle, record, force)
        for index, chapter in enumerate(targets):
            if chapter in archive:
                continue
            cycle['current_chapter']=chapter
            cycle['stage']='B'
            cycle['completed_count']=index
            _update_run(job_id,{'cycle':cycle})
            # Explicit IDs recover committed chapters after state/staging failure
            # instead of expanding this day's reserved batch.
            generated = writer_runner.generate_chapter(
                project, word_count=cycle["word_count"], max_revisions=cycle["max_revisions"],
                chapter_id=chapter,
            )
            record["generated"].append(_compact_generation(generated))
        receipts = writer_runner.reviewed_chapters(project)
        pending_now = human_pending_chapters(project, published_set)
        targets, blocked_now = split_targets_by_pending(pending_now, targets)
        if blocked_now:
            if not targets:
                raise RuntimeError(
                    f"第 {min(pending_now)} 章待人工复核通过后再发布；本批目标 {blocked_now} 已阻止")
            cycle["target_ids"] = list(targets)
            cycle["skipped_pending"] = blocked_now
            record["skipped_pending"] = blocked_now
            record["target_ids"] = list(targets)
            record["quota"] = {"chapters_per_run": len(targets), "word_count": cycle["word_count"]}
        if not set(targets).issubset(receipts):
            raise RuntimeError("批次存在未通过审查或正文被修改的章节")
        archive = _verified_archive(book, receipts, account)
        remaining = [i for i in targets if i not in archive]
        if remaining:
            staged = bridge.stage_project(project, book_name=book, selected_ids=set(remaining))
            if staged["conflicts"] or staged["invalid"]:
                raise RuntimeError("章节入队失败：冲突或空正文")
            queue = _verify_queue(book, receipts)
            if set(queue) & set(archive):
                raise RuntimeError("队列包含已归档章节，已阻止重复发布")
            # The publisher sorts by chapter number, then filename. Only the
            # exact remaining batch may occupy its selected prefix.
            prefix = sorted(queue)[:len(remaining)]
            if prefix != sorted(remaining):
                raise RuntimeError("发布器队列顺序与本批次不一致")
            latest = load_scheduler()["jobs"].get(job_id)
            if not latest or material_change(latest,job):
                raise RuntimeError("运行中任务配置已改变")
            if not force and (not latest.get("enabled", True) or _check_approval(latest, _job_today(latest))):
                raise RuntimeError("发布前任务已停用或当前日期未批准")
            # Re-read receipts immediately before calling the publisher.
            receipts = writer_runner.reviewed_chapters(project)
            pending_now = human_pending_chapters(project, published_set)
            targets, blocked_now = split_targets_by_pending(pending_now, targets)
            if blocked_now:
                if not targets:
                    raise RuntimeError(
                        f"第 {min(pending_now)} 章待人工复核通过后再发布；本批目标 {blocked_now} 已阻止")
                cycle["target_ids"] = list(targets)
                cycle["skipped_pending"] = blocked_now
                record["skipped_pending"] = blocked_now
                record["target_ids"] = list(targets)
                record["quota"] = {"chapters_per_run": len(targets), "word_count": cycle["word_count"]}
            if not set(targets).issubset(receipts):
                raise RuntimeError("发布前正文审查记录失效")
            _verify_queue(book, receipts)
            bridge.validate_queue_origin(book, project=project, account=account)
            record["queued_before_publish"] = sorted(queue)
            code = bridge.run_publish(book, count=len(remaining), volume=job.get("volume"), account=account)
            record["publish_exit_code"] = code
            bridge.sync_manifest()
        else:
            code = 0
            record["mode"] = "reconcile_archive"
        archive = _verified_archive(book, receipts, account)
        queue = _verify_queue(book, receipts)
        complete = set(targets).issubset(archive) and not set(targets).intersection(queue)
        status = "success" if complete and code == 0 else ("partial" if code == 0 else "publish_failed")
        cycle["status"] = status
        record.update(status=status, finished_at=bridge.now_iso(),
                      published_ids_seen_in_local_archive=archive, queue_after_publish=sorted(queue),
                      generated_ids_published=[i for i in targets if i in archive])
        changes = {"cycle": cycle, "last_status": status, "last_message": ""}
        if status == "success":
            changes["last_run_date"] = cycle["run_date"]
            completed=completed_slots(job,cycle["run_date"])
            completed.add(cycle.get("slot") or cycle["run_date"]+"@"+job_times(job)[0])
            changes["completed_slots"]=sorted(completed)[-56:]
        _update_run(job_id, changes)
        record["run_record"] = _write_run_record(job_id, record)
        return record
    except Exception as exc:
        cycle["status"] = "failed"
        if job.get('delivery_mode')=='serial':
            # This handler owns preflight failures before serial_delivery.step.
            # Never leave an older retry flag active after validation throws.
            cycle['recovery']={**cycle.get('recovery',{}),'automatic_retry':False,
                'chapter_id':cycle.get('current_chapter'),'message':str(exc)[:1200],
                'failure_kind':'preflight_validation'}
        record.update(status="failed", error=str(exc), finished_at=bridge.now_iso())
        changes = {"last_status": "failed", "last_message": str(exc)}
        if cycle.get("target_ids"):
            changes["cycle"] = cycle
        _update_run(job_id, changes)
        record["run_record"] = _write_run_record(job_id, record)
        raise


def approve_job(job_id: str, for_date: Optional[str] = None) -> Dict[str, Any]:
    with config_transaction() as data:
        job = data["jobs"].get(job_id)
        if not isinstance(job, dict):
            raise KeyError(f"找不到日更任务：{job_id}")
        target_date = for_date or _job_today(job)
        try:
            parsed = datetime.strptime(target_date, "%Y-%m-%d")
            if parsed.strftime("%Y-%m-%d") != target_date:
                raise ValueError()
        except ValueError as exc:
            raise ValueError("--for-date 必须是 YYYY-MM-DD") from exc
        job["approved_for"] = target_date
        job["approved_at"] = bridge.now_iso()
    return _job_summary(job_id, job) | {"approved_for": target_date}


def set_job_enabled(job_id: str, enabled: bool) -> Dict[str, Any]:
    if type(enabled) is not bool:
        raise ValueError("enabled 必须是布尔值")
    with config_transaction() as data:
        job = data["jobs"].get(job_id)
        if not isinstance(job, dict):
            raise KeyError(f"找不到日更任务：{job_id}")
        job["enabled"] = enabled
    return _job_summary(job_id, job)


def remove_job(job_id: str) -> None:
    with writer_runner.file_lock(bridge.RUNTIME_ROOT / "scheduler-execution.lock"):
        with config_transaction() as data:
            if job_id not in data["jobs"]:
                raise KeyError(f"找不到日更任务：{job_id}")
            job = data["jobs"][job_id]
            if job.get("cycle") and job["cycle"].get("status") != "success":
                raise ValueError("不能移除尚有未完成批次的任务")
            del data["jobs"][job_id]


def daemon(interval: int = 30) -> int:
    if interval < 5:
        raise ValueError("--interval 不能小于 5 秒")
    print(f"小说助手日更守护进程已启动，轮询间隔 {interval} 秒。按 Ctrl+C 停止。")
    while True:
        try:
            summaries = due_jobs()
        except Exception as exc:
            # 单个坏任务/损坏配置不能让整个守护进程退出（否则其余任务当天全部停摆）。
            print(f"[{bridge.now_iso()}] 读取到期任务失败：{exc}", file=sys.stderr)
            summaries = []
        for summary in summaries:
            job_id = summary["id"]
            try:
                result = run_once(job_id)
                print(json.dumps(result, ensure_ascii=False, indent=2))
            except Exception as exc:
                print(f"[{bridge.now_iso()}] 任务 {job_id} 失败：{exc}", file=sys.stderr)
        time_module.sleep(interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小说助手：AI 日更、审查、番茄发布调度器")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="登记一个每日任务")
    add.add_argument("--job-id", required=True, help="任务 ID，例如 xuanhuan-main")
    add.add_argument("--name", help="任务显示名")
    add.add_argument("--project", required=True, help="webnovel 项目目录")
    add.add_argument("--book", required=True, help="番茄书名")
    add.add_argument("--account", default="", help="accounts/ 下的账号名；publish_now 必填，draft_only 可留空")
    add.add_argument(
        "--publication-mode",
        choices=list(PUBLICATION_MODES),
        default="draft_only",
        help="draft_only 只写本机存稿（默认），publish_now 生成后投递到平台",
    )
    add.add_argument("--time", dest="daily_time", required=True, help="每日运行时间 HH:MM")
    add.add_argument("--timezone", default="Asia/Shanghai", help="时区标签，默认 Asia/Shanghai")
    add.add_argument("--chapters-per-run", type=int, default=1, help="每次生成/发布章节数，默认 1")
    add.add_argument("--word-count", type=int, default=3500, help="每章目标字数，默认 3500")
    add.add_argument("--max-revisions", type=int, default=1, help="每章最多自动修改轮数，默认 1；最终以资源策略 revision_rounds 封顶")
    add.add_argument("--volume", type=int, help="发布前切换到的番茄分卷")
    add.add_argument(
        "--approval-mode",
        choices=["unattended", "confirm_24h"],
        default="unattended",
        help="统一无人值守；confirm_24h 为旧客户端兼容值，不再要求日期批准",
    )
    add.add_argument("--disabled", action="store_true", help="创建后先不启用")

    sub.add_parser("list", help="列出任务")
    settings = sub.add_parser("settings", help="查看或设置全局自动调度开关（默认关闭）")
    settings.add_argument("--auto-schedule", choices=["on", "off"])
    approve = sub.add_parser("approve", help="兼容旧日期记录（不再作为执行门槛）")
    approve.add_argument("--job-id", required=True)
    approve.add_argument("--for-date", help="YYYY-MM-DD，默认今天")
    for command, enabled in (("enable", True), ("disable", False)):
        item = sub.add_parser(command, help=f"{'启用' if enabled else '停用'}任务")
        item.add_argument("--job-id", required=True)
    remove = sub.add_parser("remove", help="移除任务配置（不删除作品和运行日志）")
    remove.add_argument("--job-id", required=True)
    # 管理服务用 ``run`` 调用“立即执行一次”，命令行历史用 ``run-once``；两者等价。
    for command in ("run-once", "run"):
        run = sub.add_parser(command, help="立即执行一次指定任务")
        run.add_argument("--job-id", required=True)
        run.add_argument("--force", action="store_true", help="忽略任务停用；不跳过审查、配额或平台证据")
        # 兼容旧客户端的显式串行开关：串行与批量走同一次 run，参数只做接受不改变语义。
        run.add_argument("--serial-step", action="store_true", help=argparse.SUPPRESS)
    daemon_parser = sub.add_parser("daemon", help="本地轮询日更任务")
    daemon_parser.add_argument("--interval", type=int, default=30, help="轮询间隔秒数，默认 30")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    os.environ.setdefault("NOVEL_HELPER_COST_DB",str(COMBINED_ROOT / "integration_data" / "costs.sqlite3"))
    args = build_parser().parse_args(argv)
    try:
        if args.command == "add":
            result = add_job(args)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "list":
            data = load_scheduler()
            print(
                json.dumps(
                    [_job_summary(job_id, job) for job_id, job in data["jobs"].items()],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "approve":
            print(json.dumps(approve_job(args.job_id, args.for_date), ensure_ascii=False, indent=2))
            return 0
        if args.command == "settings":
            result = (update_settings({"auto_schedule": args.auto_schedule == "on"})
                      if args.auto_schedule else load_scheduler()["settings"])
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "enable":
            print(json.dumps(set_job_enabled(args.job_id, True), ensure_ascii=False, indent=2))
            return 0
        if args.command == "disable":
            print(json.dumps(set_job_enabled(args.job_id, False), ensure_ascii=False, indent=2))
            return 0
        if args.command == "remove":
            remove_job(args.job_id)
            print(json.dumps({"removed": args.job_id}, ensure_ascii=False))
            return 0
        if args.command in {"run-once", "run"}:
            result = run_once(args.job_id, force=args.force)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("status") in {"success", "published_existing", "already_ran"} else 2
        if args.command == "daemon":
            return daemon(args.interval)
    except KeyboardInterrupt:
        print("\n已停止日更守护进程。")
        return 130
    except Exception as exc:
        print(f"[小说助手] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
