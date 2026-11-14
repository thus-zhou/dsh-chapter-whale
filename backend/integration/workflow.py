"""单本书的创作流程状态：普通用户按步骤走完，不必理解内部结构。"""

import json
from pathlib import Path

SCHEMA = 1
CREATIVE = ".webnovel/creative_brief.json"
PLAN = ".webnovel/story_plan.json"
REQUIRED = (("genre", "题材"), ("premise", "一句话创意"), ("style", "文风"))


def _read(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _brief(project):
    doc = _read(Path(project) / CREATIVE)
    brief = doc.get("brief")
    return brief if isinstance(brief, dict) else {}


def _plan_chapters(project):
    """规划章节既可能是列表，也可能是 {章号: {...}}；两种都算已规划。"""
    doc = _read(Path(project) / PLAN)
    chapters = doc.get("chapters")
    if isinstance(chapters, (list, dict)):
        return len(chapters)
    return 0


def _chapters(project):
    from . import writer_runner

    return sorted(chapter for _, chapter in writer_runner._chapter_files(Path(project)))


def _samples(project):
    from . import studio

    try:
        return studio.sample_list(project)
    except (OSError, ValueError):
        return []


def _report(project, chapter):
    from . import quality_gate

    if not chapter:
        return {}, {}
    try:
        return quality_gate.public_report(Path(project), chapter) or {}, quality_gate.status(Path(project), chapter) or {}
    except (OSError, ValueError):
        return {}, {}


def _step(identity, title, done, detail, page, label, blocked=""):
    return {"id": identity, "title": title, "done": bool(done), "detail": detail,
            "action": {"page": page, "label": label}, "blocked_reason": blocked}


def state(project):
    """Return the six-step flow plus what still blocks the next step.

    Read-only: nothing here writes, generates or calls a model.
    """
    from . import writer_runner

    root = Path(project)
    brief = _brief(root)
    filled = [label for key, label in REQUIRED if str(brief.get(key) or "").strip()]
    missing = [label for key, label in REQUIRED if not str(brief.get(key) or "").strip()]
    plan_count = _plan_chapters(root)
    chapters = _chapters(root)
    samples = _samples(root)
    latest = chapters[-1] if chapters else 0
    report, status = _report(root, latest)
    quality = (report or {}).get("report") or {}

    steps = [
        _step("idea", "输入创意", bool(str(brief.get("premise") or "").strip()),
              "一句话创意已填写" if brief.get("premise") else "先写一句这本书要讲什么", "brief", "去填写"),
        _step("essentials", "补充必要信息", len(filled) == len(REQUIRED),
              f"已填写 {'、'.join(filled)}" if filled else "题材、创意、文风三项必填",
              "brief", "补充", "" if len(filled) == len(REQUIRED) else f"还缺：{'、'.join(missing)}"),
        _step("direction", "确认方向", plan_count > 0,
              f"已有 {plan_count} 章规划" if plan_count else "还没有规划，可以先让 A 生成大纲",
              "outline", "去规划", "" if plan_count else "确认方向后再开始写作，避免整章返工"),
        _step("samples", "可选样本", True,
              f"已上传 {len(samples)} 份示范样本" if samples else "可以跳过；上传示范能让文风更接近你的写法",
              "brief", "上传样本"),
        _step("writing", "开始创作", bool(chapters),
              f"已写 {len(chapters)} 章，最新第 {latest} 章" if chapters else "还没有正文",
              "chapters", "去写作"),
        _step("results", "查看结果", bool(quality),
              ("最新一章有质量报告" + ("（报告已过期）" if status.get("stale_reason") else "")) if quality else "写完一章并审查后才会出现质量报告",
              "chapters", "查看报告"),
    ]
    next_step = next((item for item in steps if not item["done"]), None)
    return {
        "schema_version": SCHEMA,
        "chapter": writer_runner.next_chapter_id(root),
        "steps": steps,
        "next": next_step["id"] if next_step else "done",
        "counts": {"chapters": len(chapters), "samples": len(samples), "plan_chapters": plan_count,
                   "filled": len(filled), "required": len(REQUIRED)},
        "note": "流程只做提示：不会自动修改正文、不会自动发布，也不会替你调用模型。",
    }
