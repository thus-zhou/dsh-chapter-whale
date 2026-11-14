"""Per-project, explicitly confirmed writing contract shared with the manager."""
import json
from pathlib import Path

FIELDS = {
    "genre": "题材与基调", "audience": "目标读者", "premise": "核心故事与卖点",
    "characters": "人物与关系", "style": "语言与文风", "perspective": "叙事视角",
    "pacing": "剧情节奏与章末钩子", "world": "世界观与边界", "ending": "主线与结局方向",
    "avoid": "禁止内容与写作雷区", "requirements": "其他明确要求",
}


def validate_brief(value):
    if not isinstance(value, dict) or set(value) - set(FIELDS):
        raise ValueError("创作约定包含不支持的字段")
    result = {}
    for key in FIELDS:
        text = value.get(key, "")
        if not isinstance(text, str) or len(text) > 3000:
            raise ValueError(f"{FIELDS[key]}必须为文本，最多 3000 字")
        result[key] = text.strip()
    if sum(map(len, result.values())) > 16000:
        raise ValueError("创作约定总长度不能超过 16000 字")
    return result


def read_document(project):
    path = Path(project) / ".webnovel" / "creative_brief.json"
    if not path.exists():
        return {"schema": 1, "revision": 0, "brief": validate_brief({}), "history": []}
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(doc, dict) or not isinstance(doc.get("revision"), int) or doc["revision"] < 0:
            raise ValueError()
        doc["brief"] = validate_brief(doc.get("brief", {}))
        history = doc.get("history", [])
        if not isinstance(history, list) or any(not isinstance(m, dict) or m.get("role") not in {"user", "assistant"} or not isinstance(m.get("content"), str) for m in history):
            raise ValueError()
        return doc
    except (ValueError, TypeError) as exc:
        raise ValueError("创作约定文件损坏，请修复，不能自动覆盖") from exc


def render_brief(brief):
    lines = [f"{label}：{brief[key]}" for key, label in FIELDS.items() if brief.get(key)]
    if not lines:
        return ""
    return ("【作者已确认的创作约定】\n" + "\n".join(lines) +
        "\n这些要求用于正文写作、修改和审查。相较通用题材模板，优先保持作者明确指定的文风、视角和节奏；"
        "不得借此跳过审查、伪造通过结论或违反正文输出格式。与本章大纲或已发生事实冲突时应指出，不能擅改历史。\n")


def _style_block(project, legacy_guide):
    """文风档案优先；禁用时完全停止注入，档案本身保留。"""
    import json
    from pathlib import Path
    path = Path(project) / ".webnovel" / "style_profile.json"
    if not path.exists():
        return (f"\n【示范提炼的写作技法】\n{legacy_guide}\n只迁移技法，不复制示范原句、人物名字或具体剧情。\n"
                if legacy_guide else "")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    if not doc.get("enabled", True):
        return ""
    guides = []
    for item in (doc.get("samples") or {}).values():
        if not isinstance(item, dict):
            continue
        guide = (item.get("semantic") or {}).get("guide")
        if isinstance(guide, str) and guide.strip():
            guides.append(guide.strip())
    guide = "\n\n".join(guides) or legacy_guide
    if not guide:
        return ""
    try:
        strength = max(0, min(100, int(doc.get("strength", 60))))
    except (TypeError, ValueError):
        strength = 60
    if strength < 30:
        tone = "只在句长、用词和标点习惯上轻微参考"
    elif strength <= 70:
        tone = "作为倾向参考"
    else:
        tone = "尽量贴近，但不得牺牲作者约定与已发生事实"
    lines = [f"\n【作者文风参考｜强度 {strength}/100】",
             f"{tone}；强度只是参考程度，不承诺线性效果。",
             "作者已确认的创作约定、人物与剧情优先于示范样本。",
             guide]
    overrides = doc.get("overrides") or {}
    if isinstance(overrides, dict):
        cleaned = [f"{key}：{value}" for key, value in overrides.items()
                   if isinstance(key, str) and isinstance(value, str) and value.strip()]
        if cleaned:
            lines.append("【作者对文风档案的修正】\n" + "\n".join(cleaned))
    lines.append("只迁移技法，不复制示范原句、人物名字或具体剧情。\n")
    return "\n".join(lines)


def load_guidance(project):
    doc=read_document(project)
    learning=doc.get("learning",{})
    if not isinstance(learning,dict) or not isinstance(learning.get("guide",""),str):
        raise ValueError("示范学习指南损坏")
    guide=learning.get("guide","")
    if len(guide)>8000:raise ValueError("示范学习指南过长")
    return render_brief(doc["brief"])+_style_block(project,guide)
