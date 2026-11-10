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


def load_guidance(project):
    doc=read_document(project)
    learning=doc.get("learning",{})
    if not isinstance(learning,dict) or not isinstance(learning.get("guide",""),str):
        raise ValueError("示范学习指南损坏")
    guide=learning.get("guide","")
    if len(guide)>8000:raise ValueError("示范学习指南过长")
    return render_brief(doc["brief"])+(f"\n【示范提炼的写作技法】\n{guide}\n只迁移技法，不复制示范原句、人物名字或具体剧情。\n" if guide else "")
