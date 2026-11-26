"""平台排期执行器（0.6.1 B02，审计后修订）。

职责顺序刻意固定：**先在本机把章节写到“已审定未变”，再算覆盖，最后才谈提交**。

1. 生成/审查/落稿复用 ``draft_delivery.step``（同一套代码，不同记录口径），
   所以“排期模式”不会绕开审查，也不会在平台侧留下半章；
2. 排期能力未证实（``can_auto_schedule`` 为假）时，本章只产出本地存稿候选，
   并如实写 ``capability_unknown``，不假装排上；
3. 能力证实后才把计划落成本地意图（先意图、后单章写入）；每次写入前重读
   回执哈希，正文被改过就作废该意图，不提交旧版本；
4. **过期不补写**：``planned_at`` 已过的意图标 ``expired``，只做只读对账——
   迟到提交在平台上等于“立即发布”，比漏排更糟；
5. **结果未知不重试**：适配器异常/返回形状不明标 ``needs_review`` 并停止本轮
   写入，等对账，避免 T06 的重复预约；
6. 关闭补货只停本地新增，远端预约保持原样。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from . import bridge, draft_delivery, platform_adapters, platform_schedule as ps
from . import schedule_buffer as sb
from . import scheduler as s, writer_runner as writer

SCHEDULED_VERIFICATION = "platform_schedule_intent_and_readback_identity"
_REMOTE_KEYS = ("remote_id", "planned_at", "chapter_id", "book_id", "account", "content_sha256")


def _platform_of(job: Mapping[str, Any]) -> str:
    return str(job.get("platform") or job.get("publisher") or "fanqie").strip().lower()


def _inside_runs_root(path: Path) -> bool:
    try:
        path.resolve().relative_to(Path(s.RUNS_ROOT).resolve())
        return True
    except (ValueError, OSError):
        return False


def _patch_record(record: Dict[str, Any], schedule: Mapping[str, Any],
                  remote_state: str) -> Dict[str, Any]:
    """把排期结果补进同一份运行记录，不产生第二条 run。"""
    record["schedule"] = dict(schedule)
    # 运行记录自身的 status 描述“生成/审查这一步”，排期结论单独记，二者不互相覆盖。
    record["schedule_status"] = str(schedule.get("status") or "")
    record["remote_state"] = remote_state
    record["publication"] = {
        "mode": "platform_scheduled",
        "schedule_status": record["schedule_status"],
        "remote_state": remote_state,
    }
    raw = record.get("run_record")
    if isinstance(raw, str) and raw:
        target = Path(raw)
        if _inside_runs_root(target):
            try:
                bridge.write_json_atomic(target, record)
            except (OSError, TypeError, ValueError):
                pass
    return record


def _caps(capability: Mapping[str, Any]) -> Mapping[str, Any]:
    caps = capability.get("capabilities") if isinstance(capability, Mapping) else {}
    return caps if isinstance(caps, Mapping) else {}


def _submit_planned(job_id: str, job: Mapping[str, Any], capability: Mapping[str, Any],
                    store: Dict[str, Any]) -> Dict[str, Any]:
    """按计划提交单章；返回写入统计。绝不因为异常而重复写同一章。"""
    caps = _caps(capability)
    platform = _platform_of(job)
    limit = caps.get("max_scheduled")
    lead = caps.get("lead_time_minutes")
    lead_minutes = lead if isinstance(lead, int) and not isinstance(lead, bool) else 0
    now = datetime.now(timezone.utc)
    intents = [item for item in store.get("intents", [])
               if isinstance(item, dict) and item.get("state") == "planned"]
    intents.sort(key=lambda item: (str(item.get("planned_at")), int(item.get("chapter_id") or 0)))
    in_flight = sum(1 for item in store.get("intents", [])
                    if isinstance(item, Mapping) and item.get("state") in sb.PLATFORM_STATES)
    remaining = None
    if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
        remaining = max(0, limit - in_flight)
    done_chapters = {str(item.get("chapter_id")) for item in store.get("intents", [])
                     if isinstance(item, Mapping)
                     and item.get("state") in ("submitted", "scheduled_verified", "published")}
    stats: Dict[str, Any] = {"submitted": 0, "stale": 0, "expired": 0, "unknown": 0,
                             "rejected": 0, "too_soon": 0, "duplicate": 0, "blocked": ""}
    project = Path(str(job["project"]))
    try:
        pending = sorted(set(writer.committed_chapters(project)) - set(writer.reviewed_chapters(project)))
        pending = [c for c in pending if c in writer.existing_chapter_ids(project)]
    except Exception:  # noqa: BLE001 - 项目不可读时由后续逐章回执校验兜底
        pending = []
    first_pending = pending[0] if pending else 0
    # 有待对账的章时，本轮一条都不写：先把“可能已收”的那条弄清，否则就会重复预约（T06）。
    if any(isinstance(item, Mapping) and item.get("state") == "needs_review"
           for item in store.get("intents", [])):
        stats["blocked"] = "存在待对账意图：先只读对账，再继续排期"
        return stats
    for intent in intents:
        chapter = int(intent.get("chapter_id") or 0)
        if first_pending and chapter >= first_pending:
            stats["blocked"] = f"第 {pending} 章待人工复核，已停止排期后续章节"
            break
        if str(chapter) in done_chapters:
            stats["duplicate"] += 1
            continue
        moment = ps.parse_instant(intent.get("planned_at"), timezone.utc)
        if moment is None:
            intent["state"] = "needs_review"
            intent["last_error"] = "计划时刻不可解析"
            stats["unknown"] += 1
            continue
        if moment <= now:
            intent["state"] = "expired"
            intent["last_error"] = "计划时刻已过：不自动补写，请对账后人工处理"
            stats["expired"] += 1
            continue
        if lead_minutes and moment < now + timedelta(minutes=lead_minutes):
            # 还在平台提前量之内：这一轮不写，保留意图等下一轮。
            stats["too_soon"] += 1
            continue
        if remaining is not None and stats["submitted"] >= remaining:
            stats["blocked"] = "达到平台在排总量上限"
            break
        receipt = writer.reviewed_chapters(project).get(chapter)
        if receipt is None or str(receipt.get("sha256") or "") != str(intent.get("version_sha256") or ""):
            intent["state"] = "stale"
            intent["last_error"] = "提交前重读：正文版本已变化，作废该意图"
            stats["stale"] += 1
            continue
        path = str(receipt.get("destination") or "")
        try:
            result = platform_adapters.submit_scheduled(platform, job, intent, path)
        except platform_adapters.AdapterUnavailable as exc:
            # 没有适配器是“还没这个能力”，不是“提交失败”，不计尝试次数。
            stats["blocked"] = str(exc)[:200]
            break
        except platform_adapters.AdapterRejected as exc:
            intent["attempts"] = int(intent.get("attempts") or 0) + 1
            intent["state"] = "failed"
            intent["last_error"] = f"平台明确拒绝：{str(exc)[:200]}"
            stats["rejected"] += 1
            continue
        except platform_adapters.AdapterResultUnknown as exc:
            intent["attempts"] = int(intent.get("attempts") or 0) + 1
            intent["state"] = "needs_review"
            intent["last_error"] = f"提交结果未知，需只读对账：{str(exc)[:200]}"
            stats["unknown"] += 1
            # 结果未知时立刻停止本轮后续写入，先把这一章弄清。
            stats["blocked"] = "提交结果未知：已停止本轮写入，先只读对账"
            # 先把“可能已收”写进台账再退出：否则崩溃重跑会再提交一次（T06）。
            sb.save_store(job_id, store)
            break
        except Exception as exc:  # noqa: BLE001 - 未分类异常一律按未知处理
            intent["attempts"] = int(intent.get("attempts") or 0) + 1
            intent["state"] = "needs_review"
            intent["last_error"] = f"提交结果未知，需只读对账：{str(exc)[:200]}"
            stats["unknown"] += 1
            stats["blocked"] = "提交结果未知：已停止本轮写入，先只读对账"
            sb.save_store(job_id, store)
            break
        intent["attempts"] = int(intent.get("attempts") or 0) + 1
        intent["state"] = "submitted"
        intent["submitted_at"] = bridge.now_iso()
        intent["remote"] = {key: result.get(key) for key in _REMOTE_KEYS}
        intent["last_error"] = ""
        done_chapters.add(str(chapter))
        stats["submitted"] += 1
        # 每写一章就落一次台账：写入成功与落盘之间崩溃时，下一轮能看到“已提交”。
        sb.save_store(job_id, store)
    sb.save_store(job_id, store)
    return stats


def _remote_state_from(store: Mapping[str, Any], planned: Mapping[str, Any],
                       stats: Mapping[str, Any]) -> str:
    intents = [item for item in store.get("intents") or [] if isinstance(item, Mapping)]
    states = {str(item.get("state")) for item in intents}
    if "scheduled_verified" in states:
        return "scheduled_verified"
    if stats.get("unknown") or "needs_review" in states:
        return "needs_review"
    if stats.get("submitted") or "submitted" in states or "planned" in states:
        return "scheduled_pending"
    if planned.get("planned_count"):
        return "scheduled_pending"
    return "local_draft"


def step(job_id: str, job: Dict[str, Any], cycle: Dict[str, Any], quota: Dict[str, Any],
         record: Dict[str, Any], force: bool) -> Dict[str, Any]:
    settings = sb.normalize_settings(job.get("schedule_buffer"))
    platform = _platform_of(job)
    account, book = str(job.get("account") or ""), str(job.get("book") or "")
    capability = ps.capability_for(platform, account, book)
    auto_ok, auto_reason = ps.can_auto_schedule(capability)
    store = sb.load_store(job_id)

    # 先把本机写到“已审定未变”；这步不碰平台。
    # 注意：不得在调用前改写 cycle，否则空新批次会被误判为旧批次残留而丢失 run_date/slot。
    base = draft_delivery.step(job_id, job, cycle, quota, record, force,
                               mode="platform_scheduled", verification=SCHEDULED_VERIFICATION)
    active_cycle = base.get("cycle") if isinstance(base.get("cycle"), dict) else cycle
    if active_cycle is not cycle and isinstance(active_cycle, dict):
        cycle.clear()
        cycle.update(active_cycle)
    # 上一轮可能留下 scheduled_verified；本轮若一条都没确认，状态必须往下走，不能粘住。
    cycle["remote_state"] = "not_attempted"
    cycle["schedule_status"] = ""
    if base.get("status") == "blocked" and base.get("reason_code") == "model_unavailable":
        return _patch_record(base, {"status": "blocked", "reason": auto_reason or "模型不可用"},
                             "not_attempted")
    if base.get("status") not in {"success", "needs_revision", "blocked", "already_ran"}:
        return base

    project = Path(str(job["project"]))
    approved = sb.approved_candidates(project)
    # 上一轮对账看到的“平台已占章”要参与本轮去重，否则平台侧已排的章会被再排一次。
    last = store.get("last_reconcile") if isinstance(store.get("last_reconcile"), Mapping) else {}
    remote_rows = [row for row in (last.get("rows") or []) if isinstance(row, Mapping)]
    planned = sb.plan({**job, "job_id": job_id}, approved=approved, remote=remote_rows,
                      intents=store.get("intents") or [],
                      capability=capability, settings=settings)
    info: Dict[str, Any] = {
        "status": "preview_only", "capability": capability.get("capabilities") or {},
        "auto_allowed": auto_ok, "reason": auto_reason,
        "planned_count": planned.get("planned_count", 0),
        "coverage": planned.get("coverage") or {},
        "local_remaining": planned.get("local_remaining", 0),
        "replenish_stopped": bool(store.get("replenish_stopped")),
        "plan_status": planned.get("status"),
    }
    if store.get("replenish_stopped"):
        info["status"] = "stopped"
        info["reason"] = "已关闭补货：不新增排期，远端已有预约不动"
        remote = "scheduled_pending" if (store.get("intents") or []) else "local_draft"
        cycle["remote_state"] = remote
        cycle["schedule_status"] = info["status"]
        s._update_run(job_id, {"cycle": cycle})
        return _patch_record(base, info, remote)
    if not auto_ok:
        # 关键分支：平台排期与草稿分不清时，只交本地存稿候选。
        info["status"] = "capability_unknown"
        cycle["remote_state"] = "capability_unknown"
        cycle["schedule_status"] = info["status"]
        s._update_run(job_id, {"cycle": cycle})
        return _patch_record(base, info, "capability_unknown")

    applied = sb.apply_plan(job_id, job, planned, store=store)
    store = sb.load_store(job_id)
    submitted = _submit_planned(job_id, job, capability, store)
    store = sb.load_store(job_id)
    remote_state = _remote_state_from(store, planned, submitted)
    info.update({"status": "submitted" if submitted["submitted"] else "planned",
                 "intents_added": applied["added"], "replaced": applied["replaced"],
                 "cancelled": applied["cancelled"], "intents_total": applied["total"],
                 "submitted": submitted["submitted"], "stale": submitted["stale"],
                 "expired": submitted["expired"], "unknown": submitted["unknown"],
                 "rejected": submitted["rejected"], "too_soon": submitted["too_soon"],
                 "duplicate": submitted["duplicate"], "blocked": submitted["blocked"]})
    if submitted["blocked"]:
        info["status"] = "submit_blocked"
        info["reason"] = submitted["blocked"]
    if applied["blocked"]:
        info["apply_blocked"] = applied["blocked"][:5]
    # 让 job summary 与运行记录看到同一份事实：本地成功 ≠ 已发布。
    cycle["remote_state"] = remote_state
    cycle["schedule_status"] = info["status"]
    base["cycle"] = cycle
    s._update_run(job_id, {"cycle": cycle})
    return _patch_record(base, info, remote_state)


def state_for_job(job_id: str, job: Mapping[str, Any]) -> Dict[str, Any]:
    platform = _platform_of(job)
    account, book = str(job.get("account") or ""), str(job.get("book") or "")
    capability = ps.capability_for(platform, account, book)
    auto_ok, reason = ps.can_auto_schedule(capability)
    summary = sb.coverage_summary(job_id, job)
    return {"coverage": summary, "capability": capability.get("capabilities") or {},
            "capability_observed_at": capability.get("observed_at") or "",
            "auto_allowed": auto_ok, "reason": reason,
            "replenish_stopped": bool(summary.get("replenish_stopped")),
            "needs_reconcile": bool(summary.get("needs_review") or summary.get("recompute_required"))}
