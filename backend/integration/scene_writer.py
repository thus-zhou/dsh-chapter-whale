"""按场景生成正文：每场景一次 B 请求，完成即存；失败从未完成处恢复。"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

from . import bridge, costs, memory_library, model_roles, scenes, writer_runner as writer

SCHEMA = 1
PREVIOUS_TAIL = 600
PROMPT_LIMIT = 24000


def _path(project, chapter, scene_id, plan_hash):
    return scenes._folder(project) / f"{int(chapter):04d}-{plan_hash[:16]}-{scene_id}.json"


def _saved(path):
    if not path.exists():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    text = row.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    if row.get("sha256") != hashlib.sha256(text.encode("utf-8")).hexdigest():
        return None
    return row


def _prompt(project, chapter, card, previous, guidance):
    pieces = [guidance.strip()[:6000]]
    try:
        context = memory_library.context(project, role="B", chapter=chapter)
        if context.get("text"):
            pieces.append(context["text"][:6000])
    except (ValueError, OSError):
        pass
    try:
        from . import character_state
        people = character_state.context(project, chapter).get("text") or ""
        if people:
            pieces.append(people[:6000])
    except Exception:
        pass
    pieces.append("本章场景卡（只写这一段，不要写其他场景）：\n" + json.dumps(card, ensure_ascii=False))
    if previous:
        pieces.append("上一场景的最后一段（用于衔接，不要重复）：\n" + previous[-PREVIOUS_TAIL:])
    pieces.append("要求：保持人物、设定与已发生事实一致；只输出一个 JSON 对象，键为 text，值为场景正文。"
                  "不要输出标题、流程说明或 Markdown 围栏。")
    return "\n\n".join(pieces)[:PROMPT_LIMIT]


async def draft(project, chapter, word_count, count=2, *, config=None):
    """返回与整章模式相同的 draft 结构；已完成的场景直接复用。"""
    project = Path(project).resolve()
    planned = scenes.plan(project, chapter, count=count, word_count=word_count)
    scenes.store(project, chapter, planned)
    guidance = ""
    try:
        from . import studio
        guidance = studio.brief_service().load_guidance(project)
    except Exception:
        guidance = ""
    config = config or model_roles.load_config()
    done, previous, requests = [], "", 0
    for card in planned["cards"]:
        path = _path(project, chapter, card["id"], planned["plan_hash"])
        row = _saved(path)
        if row:
            done.append({"id": card["id"], "chars": len(row["text"]), "reused": True})
            previous = row["text"]
            continue
        # 每次场景生成都要记进同一本费用账：否则预算只看得到整章调用。
        with costs.scope(stage="draft", chapter=int(chapter), project=str(Path(project).resolve())):
            result = await model_roles.json_call("B", _prompt(project, chapter, card, previous, guidance),
                                                 config=config, max_tokens=min(6000, max(1200, card["target_chars"] * 2)),
                                                 timeout=240)
        text = str(result.get("text") or "").strip()
        if len(text) < 50:
            raise ValueError(f"场景 {card['id']} 生成内容过短，未保存")
        requests += 1
        payload = {"schema_version": SCHEMA, "chapter": int(chapter), "plan_hash": planned["plan_hash"],
                   "scene_id": card["id"], "index": card["position"], "text": text,
                   "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                   "chars": len(text), "created_at": bridge.now_iso()}
        writer.atomic_json(path, payload)
        done.append({"id": card["id"], "chars": len(text), "reused": False})
        previous = text
    content = "\n\n".join(_saved(_path(project, chapter, card["id"], planned["plan_hash"]))["text"]
                          for card in planned["cards"])
    return {"content": content, "errors": [], "success": True, "review": None,
            "scenes": done, "requests": requests, "plan_hash": planned["plan_hash"],
            "plan_source": planned["source"]}


def estimate(count=2):
    count = max(1, min(3, int(count or 2)))
    return {"mode": "scenes", "scenes": count, "requests": count + 1,
            "note": f"预计 {count} 次场景生成 + 1 次整章审查；重试计入统一预算。"}
