"""只存稿执行器：生成 + 完整审查 + 本机落稿，全程不触碰平台。

与 serial_delivery / local_completion 的区别：
- local_completion 是给“已封存特殊批次”补完本地章节的专用分支；
- 本模块是普通的 publication_mode=draft_only 通道，新任务默认走它。

硬约束（缺一不可）：
1. 不调用 bridge.stage_project / run_publish / sync_manifest，也不读写归档凭据；
2. 章节是否算完成，只看 writer_runner.reviewed_chapters() 的本地回执
   （回执绑定正文 sha256 + 创作约定摘要 + 章版本），不看平台；
3. 审查不通过时保留正文与问题，批次以 needs_revision 结束，重跑只补没过的那几章；
4. 受控收尾（缺模型、无目标、审查未过）通过返回值表达，不抛异常，
   这样调度器的 except 分支不会把只存稿的“待修订”改写成“失败”。
"""
from __future__ import annotations

import copy
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import bridge, costs, model_roles, scheduler as s, writer_runner as writer

DRAFT_VERIFICATION = "local_body_review_and_memory_only_no_remote_delivery"


def _require_model() -> Optional[str]:
    """只存稿不要求平台资格，但必须真有可用模型，否则会静默空跑。"""
    try:
        config = model_roles.load_config()
    except Exception:
        return "模型配置无法读取；请先在侧栏重新选择模型或填入接口后重试。"
    try:
        ready = bool(model_roles.enabled(config))
    except Exception:
        ready = False
    if not ready:
        return "尚未配置可用模型，无法生成存稿；请先在侧栏选择模型或填写接口后重试。"
    return None


def _words(receipt: Dict[str, Any]) -> int:
    """字数按已落盘正文计，和审查用的口径一致（不含标题与空白）。"""
    try:
        path = Path(str(receipt.get("destination") or ""))
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return 0
    try:
        from integration.length_policy import body_chars
        return int(body_chars(text, int(receipt.get("chapter_id") or 0) or None))
    except Exception:
        return len("".join(text.split()))


def _issues(receipt: Optional[Dict[str, Any]]) -> List[str]:
    """把审查结果压缩成作者能照着改的短句，不泄露提示词与正文。"""
    review = (receipt or {}).get("review")
    if not isinstance(review, dict):
        return []
    found: List[str] = []
    for key in ("issues", "problems", "blocking_issues", "violations"):
        value = review.get(key)
        if isinstance(value, list):
            for item in value[:20]:
                text = item if isinstance(item, str) else (
                    item.get("message") if isinstance(item, dict) else None)
                if isinstance(text, str) and text.strip():
                    found.append(text.strip()[:300])
    if not found:
        decision = review.get("review_decision") or review.get("decision") or ""
        if isinstance(decision, str) and decision and decision not in {"pass", "reviewed", "waived_by_E"}:
            found.append(f"审查结论：{decision[:120]}")
    return found


def _entry(chapter: int, receipt: Optional[Dict[str, Any]],
           *, reviewed: bool, issue: str = "") -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "chapter_id": chapter,
        "body_saved": receipt is not None,
        "review_passed": bool(receipt is not None and reviewed),
        "remote_state": "not_applicable",
        "words": _words(receipt) if receipt else 0,
        "updated_at": bridge.now_iso(),
    }
    if receipt is not None:
        item["sha256"] = receipt.get("sha256", "")
        item["reviewed_at"] = receipt.get("reviewed_at", "")
        item["review_decision"] = (receipt.get("review") or {}).get("review_decision", "")
        item["post_save"] = copy.deepcopy(receipt.get("post_save", {}))
    if issue:
        item["issue"] = issue
    return item


def _select_targets(project: Path, cycle: Dict[str, Any], quota: Dict[str, Any]) -> List[int]:
    """目标快照在第一个 run 里冻结，恢复时沿用同一批章号。"""
    if cycle and cycle.get("target_ids"):
        targets = [i for i in cycle["target_ids"] if type(i) is int and i > 0]
        if targets:
            return targets
    count = max(1, int(quota.get("chapters_per_run") or 1))
    existing = writer.existing_chapter_ids(project)
    start = writer.next_chapter_id(project)
    return [i for i in range(start, start + count) if i not in existing]


def _body_ids(project: Path) -> set:
    chapters = project / "正文"
    found = set()
    if not chapters.is_dir():
        return found
    for path in chapters.glob("*.md"):
        parsed = bridge.parse_chapter_name(path.name)
        if parsed:
            found.add(parsed[0])
    return found


def _finish(job_id: str, job: Dict[str, Any], today: str, cycle: Dict[str, Any],
            record: Dict[str, Any], status: str, message: str,
            reason_code: str = "", next_action: str = "", *,
            publication_mode: str = "draft_only",
            verification: str = DRAFT_VERIFICATION,
            remote_state: str = "not_applicable") -> Dict[str, Any]:
    cycle["status"] = status
    cycle["remote_state"] = remote_state
    cycle["updated_at"] = bridge.now_iso()
    changes: Dict[str, Any] = {"cycle": cycle, "last_status": status, "last_message": message}
    if status == "success":
        completed = s.completed_slots(job, today)
        completed.add(cycle.get("slot") or today + "@" + s.job_times(job)[0])
        changes["completed_slots"] = sorted(completed)[-56:]
        changes["last_run_date"] = today
        changes["last_body_saved_at"] = bridge.now_iso()
    s._update_run(job_id, changes)
    # 运行记录自带本次快照：job.cycle 会被下一时段覆盖，投影不能依赖可变状态。
    record["publication_mode"] = publication_mode
    record["verification"] = verification
    record["cycle"] = copy.deepcopy(cycle)
    record["target_ids"] = [int(item) for item in cycle.get("target_ids") or []]
    record.update(status=status, finished_at=bridge.now_iso(), remote_state=remote_state)
    if reason_code:
        record["reason_code"] = reason_code
    if next_action:
        record["next_action"] = next_action
    try:
        from . import notification_hooks
        record["notifications"] = notification_hooks.on_run_finished(job_id, job, record)
    except Exception as exc:  # noqa: BLE001 - 通知失败不回滚章节，也不改运行结果
        record["notifications"] = {"state": "failed", "error": str(exc)[:200]}
    record["run_record"] = s._write_run_record(job_id, record)
    return record


def step(job_id: str, job: Dict[str, Any], cycle: Dict[str, Any], quota: Dict[str, Any],
         record: Dict[str, Any], force: bool, *, mode: str = "draft_only",
         verification: str = DRAFT_VERIFICATION) -> Dict[str, Any]:
    project = Path(job["project"])
    today = s._job_today(job)
    slot = record.get("slot")
    # 生成/审查/落稿逻辑对“只存稿”和“平台排期”是同一套，差别只在记录口径与
    # 收尾之后要不要排期；用闭包统一带上模式，避免两处硬编码漂移。
    finish = partial(_finish, job_id, job, today,
                     publication_mode=mode, verification=verification)

    record["verification"] = verification
    record["remote_state"] = "not_applicable"

    blocked = _require_model()
    if blocked:
        return finish(cycle or {"run_date": today, "slot": slot}, record,
                      "blocked", blocked, "model_unavailable",
                      "在侧栏选择可用模型或填写接口后重新运行该任务")

    if not cycle or cycle.get("status") == "success":
        targets = _select_targets(project, {}, quota)
        cycle = {"run_date": today, "slot": slot, "target_ids": targets, "status": "running",
                 "word_count": quota.get("word_count"),
                 "max_revisions": job.get("max_revisions", 1),
                 "publication_mode": mode, "draft_chapters": [],
                 "updated_at": bridge.now_iso()}
        record["run_date"] = today
    else:
        targets = _select_targets(project, cycle, quota)
        cycle["target_ids"] = targets
        cycle.setdefault("word_count", quota.get("word_count"))
        cycle.setdefault("max_revisions", job.get("max_revisions", 1))
    record["quota"] = {"chapters_per_run": len(targets), "word_count": cycle.get("word_count")}
    record["target_ids"] = list(targets)

    if not targets:
        return finish(cycle, record, "already_ran",
                      "没有需要新写的章节：目标章节在正文里已存在。",
                      "no_targets", "如需继续日更，请确认项目进度里的下一章号")

    cycle["status"] = "running"
    cycle["publication_mode"] = mode
    s._update_run(job_id, {"cycle": cycle})

    receipts = writer.reviewed_chapters(project)
    entries: Dict[int, Dict[str, Any]] = {
        int(item["chapter_id"]): item for item in cycle.get("draft_chapters", [])
        if isinstance(item, dict) and type(item.get("chapter_id")) is int
    }
    for chapter in targets:
        if chapter in receipts:
            # 上一轮已经存好且回执仍绑定当前正文：不重写，只刷新统计。
            entries[chapter] = _entry(chapter, receipts[chapter], reviewed=True)
            cycle["draft_chapters"] = [entries[i] for i in sorted(entries)]
            continue
        try:
            generated = writer.generate_chapter(
                project, word_count=int(cycle.get("word_count") or 3500),
                max_revisions=int(cycle.get("max_revisions") or 1), chapter_id=chapter,
            )
            record["generated"].append(s._compact_generation(generated))
        except (RuntimeError, ValueError) as exc:
            # 审查不通过、字数不足、预算超限都会在这里抛出；正文与审查记录仍留在项目里。
            message = str(exc)[:500]
            if isinstance(exc, costs.BudgetExceeded):
                # 预算按全局/作品/任务上限预留，继续下一章只会再次失败；保留已存稿并交给作者。
                cycle["failure_kind"] = "budget_exceeded"
                done = [c for c in targets if c in writer.reviewed_chapters(project)]
                record["saved_ids"] = done
                record["saved_words"] = sum(int(entries[c].get("words") or 0)
                                            for c in done if c in entries)
                return finish(
                    cycle, record, "blocked",
                    f"预算不足，已停止本批次：{message}；已存稿 {len(done)} 章不会重写",
                    "budget_exceeded",
                    "调整全局/作品/任务的预算上限，或等预算重置后重新运行；已存稿章节不会重写")
            fresh = writer.reviewed_chapters(project).get(chapter)
            if fresh is None:
                entries[chapter] = _entry(chapter, None, reviewed=False, issue=message)
                cycle["draft_chapters"] = [entries[i] for i in sorted(entries)]
                cycle["updated_at"] = bridge.now_iso()
                s._update_run(job_id, {"cycle": cycle})
                continue
            # 正文与回执都在，只是后续记忆/实体同步失败：只补记忆，不重写正文。
            record.setdefault("memory_pending", []).append(chapter)
            entries[chapter] = _entry(chapter, fresh, reviewed=True)
            cycle["draft_chapters"] = [entries[i] for i in sorted(entries)]
            continue
        receipts = writer.reviewed_chapters(project)
        fresh = receipts.get(chapter)
        if fresh is None:
            saved = chapter in _body_ids(project)
            entries[chapter] = _entry(
                chapter, None, reviewed=False,
                issue="正文已生成但审查未通过" if saved else "正文没有落盘")
        else:
            entries[chapter] = _entry(chapter, fresh, reviewed=True)
        cycle["draft_chapters"] = [entries[i] for i in sorted(entries)]
        cycle["updated_at"] = bridge.now_iso()
        s._update_run(job_id, {"cycle": cycle})

    # 收尾复核：回执必须仍与正文、创作约定、章版本一致（作者可能在中途改了稿）。
    receipts = writer.reviewed_chapters(project)
    missing = [c for c in targets if c not in receipts]
    for chapter in missing:
        entry = entries.get(chapter)
        if entry is not None and entry.get("review_passed"):
            entry["review_passed"] = False
            entry["issue"] = "审查回执与当前正文不一致，需要重新审查"
    cycle["draft_chapters"] = [entries[i] for i in sorted(entries)]

    if missing:
        problems = []
        for chapter in missing:
            entry = entries.get(chapter) or {}
            detail = _issues(receipts.get(chapter)) or ([entry["issue"]] if entry.get("issue") else [])
            problems.append({"chapter_id": chapter, "issues": detail})
        record["needs_revision"] = problems
        record["saved_ids"] = [c for c in targets if c not in missing]
        record["saved_words"] = sum(int(entries[c].get("words") or 0) for c in targets if c not in missing)
        return finish(
            cycle, record, "needs_revision",
            "存稿未通过审查，正文与问题已保留：" + "；".join(
                f"第 {item['chapter_id']} 章 " + ("；".join(item["issues"])[:200] or "需要人工确认")
                for item in problems)[:600],
            "review_failed", "按审查问题修改对应章节后重新运行该任务，已通过审查的章节不会重写")

    words = sum(int(entries[c].get("words") or 0) for c in targets)
    cycle["saved_words"] = words
    cycle.pop("failure_kind", None)
    record["saved_words"] = words
    record["saved_ids"] = list(targets)
    if not record.get("memory_pending"):
        record.pop("memory_pending", None)
    # 口径必须跟着模式走：排期模式的本章只完成“本地已审定”，远端还没确认。
    tail = "本地已审定，排期待平台回读确认" if mode == "platform_scheduled" else "仅本机，未发布"
    return finish(cycle, record, "success",
                  f"已存稿 {len(targets)} 章（{words} 字，{tail}）")


__all__ = ["step", "DRAFT_VERIFICATION"]
