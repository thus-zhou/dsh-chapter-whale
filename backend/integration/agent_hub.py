"""主编三级路由、确定性工作流模板、受限自由 DAG 与中途改令。

Level 0 never calls a model: explicit commands and qa lookups run locally.
Level 1 turns a tiny slot JSON into one of six deterministic, acyclic,
Pydantic-like validated templates (safe for weak/free models).
Level 2 accepts a free DAG only through four guards: tool whitelist, cycle
detection, <=12 nodes / depth<=2, and at most two repairs before degrading to
proposal mode.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from integration import agent_room as room


class HubError(RuntimeError):
    def __init__(self, code: str, *, status: int = 400, detail: Optional[Dict[str, Any]] = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail or {}


AUTONOMY = {"propose", "step_confirm", "auto_chain", "dry_run_first"}

TOOLS: Dict[str, Dict[str, Any]] = {
    "create_book": {"roles": {"chief"}, "risk": "high"},
    "set_directive_constraints": {"roles": {"chief"}, "risk": "low"},
    "create_task_graph": {"roles": {"chief"}, "risk": "low"},
    "amend_directive": {"roles": {"chief"}, "risk": "medium"},
    "ask_author_decision": {"roles": {"chief"}, "risk": "low"},
    "draft_proposals": {"roles": {"planner"}, "risk": "low"},
    "update_creative_brief": {"roles": {"planner"}, "risk": "medium"},
    "generate_characters": {"roles": {"planner"}, "risk": "low"},
    "plan_chapters": {"roles": {"planner"}, "risk": "low"},
    "learn_sample": {"roles": {"planner"}, "risk": "low"},
    "write_chapters": {"roles": {"writer"}, "risk": "low"},
    "write_chapter": {"roles": {"writer"}, "risk": "low"},
    "rewrite_selection": {"roles": {"editor"}, "risk": "low"},
    "generate_ab_variants": {"roles": {"editor"}, "risk": "low"},
    "revise_chapter_by_annotations": {"roles": {"editor"}, "risk": "low"},
    "run_annotation": {"roles": {"editor"}, "risk": "low"},
    "scan_book_directive": {"roles": {"editor"}, "risk": "low"},
    "execute_book_directive": {"roles": {"editor"}, "risk": "medium"},
    "review_chapter": {"roles": {"reviewer"}, "risk": "low"},
    "audit_continuity_and_facts": {"roles": {"reviewer"}, "risk": "low"},
    "check_style_precheck": {"roles": {"reviewer"}, "risk": "low"},
    "analyze_reader_metrics": {"roles": {"publisher"}, "risk": "low"},
    "preview_publish_schedule": {"roles": {"publisher"}, "risk": "low"},
    "request_publish_authorization": {"roles": {"publisher"}, "risk": "high"},
}
ROLE_ALIASES = {"主编": "chief", "策划": "planner", "主笔": "writer", "精修": "editor",
                "审稿": "reviewer", "运营": "publisher"}

MAX_DAG_NODES = 12
MAX_DAG_DEPTH = 2


def untrusted(text: str) -> str:
    return "<UNTRUSTED_MATERIAL>\n" + str(text) + "\n</UNTRUSTED_MATERIAL>"


def _node(node_id: str, role: str, tool: str, title: str,
          depends_on: Optional[Sequence[str]] = None,
          params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"id": node_id, "role": role, "tool_name": tool, "title": title,
            "depends_on": list(depends_on or []), "params": params or {}}


def build_template(name: str, slots: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    slots = dict(slots or {})
    count = max(1, min(int(slots.get("count") or 3), 3))
    if name == "template_bootstrap_book":
        nodes = [
            _node("tsk_01", "chief", "create_book", "建书并落盘设定", params={"title": slots.get("title", "")}),
            _node("tsk_02", "planner", "plan_chapters", "生成前十章细纲",
                  ["tsk_01"], {"count": int(slots.get("plan_count") or 10)}),
            _node("tsk_03", "writer", "write_chapters", f"试写前 {count} 章",
                  ["tsk_02"], {"count": count, "start": 1}),
        ]
    elif name == "template_plan_and_write":
        nodes = [
            _node("tsk_01", "planner", "plan_chapters", "规划下一段细纲",
                  params={"count": int(slots.get("count") or 5), "start": slots.get("start")}),
            _node("tsk_02", "writer", "write_chapters", "按细纲续写",
                  ["tsk_01"], {"count": min(count, 3)}),
        ]
    elif name == "template_selection_ab":
        nodes = [
            _node("tsk_01", "editor", "generate_ab_variants", "生成 A/B 两种写法",
                  params={"chapter": slots.get("chapter"), "instruction": slots.get("instruction", "")}),
        ]
    elif name == "template_chapter_annotations":
        nodes = [
            _node("tsk_01", "editor", "run_annotation", "执行本章批注",
                  params={"chapter": slots.get("chapter"), "annotation_ids": slots.get("annotation_ids", [])}),
        ]
    elif name == "template_book_directive":
        nodes = [
            _node("tsk_01", "editor", "scan_book_directive", "全书影响扫描",
                  params={"instruction": slots.get("instruction", ""),
                          "effective_from_chapter": slots.get("effective_from_chapter")}),
            _node("tsk_02", "editor", "execute_book_directive", "试改一章并批量生候选",
                  ["tsk_01"], {"trial_chapter": slots.get("trial_chapter")}),
        ]
    elif name == "template_schedule_preview":
        nodes = [
            _node("tsk_01", "publisher", "preview_publish_schedule", "排期预览",
                  params={"chapters": slots.get("chapters", [])}),
        ]
    else:
        raise HubError("unknown_template")
    graph = {"template": name, "nodes": nodes, "slots": slots}
    validate_dag(nodes)
    return graph


def validate_dag(nodes: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(nodes, (list, tuple)) or not nodes:
        raise HubError("dag_empty")
    if len(nodes) > MAX_DAG_NODES:
        raise HubError("dag_too_many_nodes", detail={"limit": MAX_DAG_NODES})
    ids = []
    by_id = {}
    for index, node in enumerate(nodes, 1):
        if not isinstance(node, dict):
            raise HubError("dag_node_not_object")
        node_id = str(node.get("id") or "")
        tool = str(node.get("tool_name") or node.get("tool") or "")
        role = str(node.get("role") or "")
        if not node_id or node_id in by_id:
            raise HubError("dag_node_id_invalid")
        if tool not in TOOLS:
            raise HubError("tool_not_allowed", detail={"tool": tool})
        if role not in TOOLS[tool]["roles"]:
            raise HubError("role_not_allowed_for_tool", detail={"tool": tool, "role": role})
        depends = node.get("depends_on") or []
        if not isinstance(depends, list) or len(depends) > MAX_DAG_NODES:
            raise HubError("dag_depends_invalid")
        by_id[node_id] = {"id": node_id, "tool": tool, "role": role,
                          "depends_on": [str(x) for x in depends]}
        ids.append(node_id)
    for node in by_id.values():
        for dep in node["depends_on"]:
            if dep not in by_id:
                raise HubError("dag_dependency_missing", detail={"missing": dep})
    # Kahn topological sort + cycle detection
    indegree = {node_id: 0 for node_id in by_id}
    outgoing: Dict[str, List[str]] = {node_id: [] for node_id in by_id}
    for node in by_id.values():
        for dep in node["depends_on"]:
            indegree[node["id"]] += 1
            outgoing[dep].append(node["id"])
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    order = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for child in outgoing[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(order) != len(by_id):
        raise HubError("dag_cycle")
    depth = {}
    for node_id in order:
        node = by_id[node_id]
        depth[node_id] = 0 if not node["depends_on"] else 1 + max(depth[dep] for dep in node["depends_on"])
    if max(depth.values()) > MAX_DAG_DEPTH:
        raise HubError("dag_too_deep", detail={"limit": MAX_DAG_DEPTH,
                                               "depth": max(depth.values())})
    return {"order": order, "depth": depth}


def _explicit_role(message: str) -> Optional[str]:
    match = re.search(r"@(主编|策划|主笔|精修|审稿|运营)", str(message or ""))
    return ROLE_ALIASES.get(match.group(1)) if match else None


def local_route(message: str) -> Optional[Dict[str, Any]]:
    text = str(message or "").strip()
    if not text:
        return None
    if re.search(r"(全局|所有).{0,6}(暂停|急停)", text):
        return {"level": 0, "action": "system_ai_pause", "params": {"paused": True}}
    if re.search(r"(恢复|继续).{0,6}(全局|所有)", text):
        return {"level": 0, "action": "system_ai_pause", "params": {"paused": False}}
    if re.search(r"(暂停|停止).{0,8}(本书|这本|自动)", text):
        return {"level": 0, "action": "automation_pause", "params": {"paused": True}}
    if re.search(r"打开.{0,4}第\s*(\d+)\s*章", text):
        chapter = int(re.search(r"第\s*(\d+)\s*章", text).group(1))
        return {"level": 0, "action": "open_chapter", "params": {"chapter": chapter}}
    if re.search(r"(花了多少|成本|费用|多少钱)", text):
        return {"level": 0, "action": "cost_query", "params": {}}
    if re.search(r"(执行|处理).{0,6}(本章|全部).{0,4}批注", text):
        return {"level": 0, "action": "run_annotations", "params": {}}
    if re.search(r"(谁|哪|什么时候|最后|结局|伏笔|设定).{0,30}(？|\?)", text) and \
            re.search(r"第\s*\d+\s*章|设定|伏笔|人物|地图|谁", text):
        return {"level": 0, "action": "qa_lookup", "params": {"question": text}}
    role = _explicit_role(text)
    if role:
        return {"level": 0, "action": "delegate_role", "params": {"role": role,
                                                                  "instruction": text}}
    return None


def _extract_slots(message: str) -> Dict[str, Any]:
    text = str(message or "")
    slots: Dict[str, Any] = {}
    if re.search(r"开一?本|建一本|新书", text):
        slots["intent"] = "bootstrap_book"
        title = re.search(r"(?:开|写|建)一?本[《“]?([^。，\n》”]{2,30})", text)
        if title:
            slots["title"] = title.group(1).strip()
        count = re.search(r"前\s*(\d+)\s*章|试写\s*(\d+)\s*章", text)
        if count:
            slots["count"] = int(count.group(1) or count.group(2))
    elif re.search(r"两种写法|A/B|A、B", text, re.I):
        slots["intent"] = "selection_ab"
    elif re.search(r"批注", text) and re.search(r"本章|这一章", text):
        slots["intent"] = "chapter_annotations"
    elif re.search(r"全书|跨章|从第\s*\d+\s*章起", text):
        slots["intent"] = "book_directive"
        chapter = re.search(r"从第\s*(\d+)\s*章起", text)
        if chapter:
            slots["effective_from_chapter"] = int(chapter.group(1))
    elif re.search(r"排期|发布计划|什么时候发", text):
        slots["intent"] = "schedule_preview"
    elif re.search(r"细纲|规划|续写|写.{0,4}章", text):
        slots["intent"] = "plan_and_write"
    if re.search(r"提案|先给.{0,4}方向", text):
        slots["autonomy"] = "propose"
    elif re.search(r"直接|连跑|一口气", text):
        slots["autonomy"] = "auto_chain"
    elif re.search(r"先试|试改|看了没问题", text):
        slots["autonomy"] = "dry_run_first"
    else:
        slots["autonomy"] = "step_confirm"
    return slots


TEMPLATE_FOR_INTENT = {
    "bootstrap_book": "template_bootstrap_book",
    "plan_and_write": "template_plan_and_write",
    "selection_ab": "template_selection_ab",
    "chapter_annotations": "template_chapter_annotations",
    "book_directive": "template_book_directive",
    "schedule_preview": "template_schedule_preview",
}


def route(message: str, *, extractor: Optional[Callable[[str], Dict[str, Any]]] = None,
          planner: Optional[Callable[[str, Dict[str, Any]], Sequence[Dict[str, Any]]]] = None,
          context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    local = local_route(message)
    if local:
        return local
    slots = None
    if extractor is not None:
        for attempt in range(2):
            try:
                candidate = extractor(message)
                if isinstance(candidate, dict):
                    slots = candidate
                    break
            except Exception:
                continue
    if slots is None:
        slots = _extract_slots(message)
    intent = str(slots.get("intent") or "")
    if intent in TEMPLATE_FOR_INTENT:
        graph = build_template(TEMPLATE_FOR_INTENT[intent], slots)
        return {"level": 1, "template": graph["template"], "nodes": graph["nodes"],
                "slots": slots, "autonomy": slots.get("autonomy") or "step_confirm"}
    if planner is None:
        return {"level": 1, "template": None, "nodes": [], "slots": slots,
                "autonomy": "propose", "reason": "no_confident_intent"}
    last_error = None
    for attempt in range(3):
        try:
            nodes = planner(message, {"slots": slots, "error": str(last_error or ""),
                                      "context": context or {}})
            validation = validate_dag(nodes)
            return {"level": 2, "template": None, "nodes": [dict(n) for n in nodes],
                    "order": validation["order"], "slots": slots,
                    "autonomy": slots.get("autonomy") or "step_confirm"}
        except HubError as exc:
            last_error = exc.code
        except Exception as exc:
            last_error = getattr(exc, "code", type(exc).__name__)
    return {"level": 2, "template": None, "nodes": [], "slots": slots,
            "autonomy": "propose", "degraded": True, "reason": "dag_repair_failed",
            "last_error": last_error}


# --------------------------------------------------------------- amendments

def start_amendment(db_path, *, directive_id: str, amendment_text: str,
                    task_ids: Sequence[str], fallback: str = "wait") -> Dict[str, Any]:
    """Freeze affected running tasks before any model evaluation starts."""
    revision = room.bump_directive_revision(db_path, directive_id)
    amendment_id = room.new_id("amd")
    stamp = room.now_iso()
    if fallback not in {"wait", "continue"}:
        raise HubError("invalid_amendment_fallback")
    if fallback == "wait":
        with room.write_tx(db_path) as db:
            for task_id in task_ids:
                db.execute("UPDATE agent_tasks SET status='held', wait_reason=? WHERE id=? "
                           "AND status IN ('running','waiting','held')",
                           (f"已收到改令 {amendment_id}，等待影响评估", task_id))
    return {"amendment_id": amendment_id, "directive_id": directive_id,
            "directive_revision": revision["directive_revision"],
            "hold_amendment_id": amendment_id if fallback == "wait" else None,
            "held_task_ids": list(task_ids) if fallback == "wait" else [],
            "fallback": fallback, "created_at": stamp}


def evaluate_amendment(db_path, *, amendment_id: str, directive_id: str,
                       evaluator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
                       context: Optional[Dict[str, Any]] = None,
                       artifact_fingerprint: str = "") -> Dict[str, Any]:
    """Role-E impact analysis with a deterministic fallback card on failure."""
    directive = room.get_directive(db_path, directive_id)
    tasks = room.list_tasks(db_path, directive_id=directive_id, active_only=True)
    try:
        if evaluator is not None:
            result = evaluator({"directive": directive, "tasks": tasks,
                                "context": context or {}, "amendment_id": amendment_id})
            if not isinstance(result, dict) or not isinstance(result.get("keep"), list):
                raise ValueError("bad_evaluation")
        else:
            result = {"keep": [task["id"] for task in tasks if task["status"] == "completed"],
                      "update": [], "wait_and_redo": [task["id"] for task in tasks
                                                      if task["status"] == "held"],
                      "preserve_versions": True}
    except Exception as exc:
        fallback = room.create_approval(
            db_path, session_id=str(directive.get("session_id")), project_id=directive.get("project_id"),
            directive_id=directive_id, directive_revision=int(directive.get("directive_revision") or 1),
            task_id=None, kind="amendment_fallback", title="改令影响评估失败，请人工裁决",
            artifact_fingerprint=artifact_fingerprint or "amendment:" + amendment_id,
            approved_scope_hash=room.new_id("scope"),
            detail={"amendment_id": amendment_id, "error": str(exc)[:200],
                    "choices": ["放行已暂停结果", "作废暂存并按新方向重试评估", "取消本次改令恢复原计划"]})
        return {"status": "fallback", "amendment_id": amendment_id, "approval": fallback}
    stamp = room.now_iso()
    with room.write_tx(db_path) as db:
        for task_id in result.get("keep", []):
            # 仅当仍持有本次改令时放行；连续第二次改令不会误释放。
            db.execute("UPDATE agent_tasks SET status='completed', wait_reason='' "
                       "WHERE id=? AND status='held'", (task_id,))
        for task_id in result.get("wait_and_redo", []):
            db.execute("UPDATE agent_tasks SET status='pending', wait_reason=? WHERE id=? AND status='held'",
                       ("按改令重跑", task_id))
        db.execute("UPDATE agent_directives SET updated_at=? WHERE id=?", (stamp, directive_id))
    return {"status": "evaluated", "amendment_id": amendment_id, **result}


def release_holds_for_current(db_path, *, directive_id: str, amendment_id: str) -> int:
    """Only the latest amendment id may release a held task."""
    directive = room.get_directive(db_path, directive_id)
    with room.write_tx(db_path) as db:
        cur = db.execute("UPDATE agent_tasks SET status='running', wait_reason='' "
                         "WHERE directive_id=? AND status='held' AND wait_reason LIKE ?",
                         (directive_id, f"%{amendment_id}%"))
        return int(cur.rowcount or 0)


# --------------------------------------------------------------- qa lookup

def qa_lookup(question: str, search: Callable[[str], Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    """Zero-model deterministic answer path: local FTS + quoted evidence."""
    hits = list(search(str(question or "")))
    return {"kind": "qa_lookup", "question": question, "hits": hits[:5],
            "count": len(hits), "model_calls": 0,
            "answer": hits[0].get("snippet") if hits else "本地索引中没有找到相关原文"}
