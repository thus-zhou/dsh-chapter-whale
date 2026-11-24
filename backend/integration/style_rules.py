"""C04 本地文风规则：规则带 ID 与正反例，先本地精确定位，平台规则只作提醒。

不做「AI 味下降百分比」这类无法证明的宣称：只报每百段提示数、采纳/忽略/误报计数。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import bridge

SCHEMA = 1
SEVERITIES = ("info", "minor", "major")
CATEGORIES = ("writing", "platform")
ACTIONS = ("accepted", "ignored", "false_positive")
MAX_FINDINGS = 200
LEDGER_LIMIT = 2000

RULES = {
    "style.dup_summary": {
        "category": "writing", "severity": "minor", "advisory": False,
        "condition": "同一章出现两次以上总结性段落，或末段与前面段落高度重复",
        "scope": "chapter", "source_date": "2026-11-21",
        "positive": "他把伞收起来，走了。",
        "negative": "总之，这一天的经历让他明白了很多。",
        "ignore_scope": "作品词表中的口癖、诗句、刻意重复",
    },
    "style.explainer_tail": {
        "category": "writing", "severity": "minor", "advisory": False,
        "condition": "结尾用解释性连词或「终于明白」把意思讲透",
        "scope": "chapter", "source_date": "2026-11-21",
        "positive": "雨还在下。他没有回头。",
        "negative": "也就是说，他终于明白，自己再也不会回来了。",
        "ignore_scope": "作品词表",
    },
    "style.tautology": {
        "category": "writing", "severity": "info", "advisory": False,
        "condition": "相邻重复同一词组（高兴高兴、非常非常）",
        "scope": "paragraph", "source_date": "2026-11-21",
        "positive": "他慢慢走过去。",
        "negative": "他非常非常高兴，高兴高兴得说不出话。",
        "ignore_scope": "叠词白名单（慢慢、渐渐、悄悄）",
    },
    "style.homogeneous_dialogue": {
        "category": "writing", "severity": "info", "advisory": False,
        "condition": "连续四句以上对白长度接近、开头人称相同",
        "scope": "paragraph", "source_date": "2026-11-21",
        "positive": "「走。」\n「去哪。」\n「随便。」",
        "negative": "「我觉得我们应该先去找老周问问情况。」\n「我觉得也是，先找老周问问情况。」",
        "ignore_scope": "作品词表",
    },
    "platform.no_basis_claim": {
        "category": "platform", "severity": "info", "advisory": True,
        "condition": "出现「保证过审」「一定能上榜」这类无依据承诺",
        "scope": "chapter", "source_date": "2026-11-21",
        "positive": "本章按平台常见格式检查了段落长度。",
        "negative": "这样写保证过审，一定能上推荐。",
        "ignore_scope": "无（平台规则始终只提醒）",
    },
}

SUMMARY_MARKERS = ("总之", "总而言之", "综上", "总的来说", "这一刻他明白", "就这样，", "从此以后")
EXPLAIN_MARKERS = ("也就是说", "换句话说", "这意味着", "他终于明白", "她终于明白", "因为这一切")
STACK_WHITELIST = ("慢慢", "渐渐", "悄悄", "轻轻", "缓缓", "刚刚", "常常")
# 合法动词/名词重叠：这些是正常说法，不是「同义反复」。
REDUP_WHITELIST = ("商量", "研究", "考虑", "休息", "打听", "收拾", "整理", "活动",
                   "热闹", "干净", "明白", "清楚", "舒服", "高兴", "漂亮", "老实",
                   "客气", "冷静", "安静", "认真", "仔细", "小心", "暖和", "凉快")
DIALOGUE = re.compile(r"^\s*[「“\"](.+?)[」”\"]\s*$")


def _path(project):
    return Path(project).resolve() / ".webnovel" / "style_rules.json"


def _load(project):
    path = _path(project)
    if not path.exists():
        return {"schema": SCHEMA, "checks": 0, "paragraphs": 0, "findings": 0,
                "actions": {key: 0 for key in ACTIONS}, "samples": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": SCHEMA, "checks": 0, "paragraphs": 0, "findings": 0,
                "actions": {key: 0 for key in ACTIONS}, "samples": []}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return {"schema": SCHEMA, "checks": 0, "paragraphs": 0, "findings": 0,
                "actions": {key: 0 for key in ACTIONS}, "samples": []}
    data.setdefault("actions", {key: 0 for key in ACTIONS})
    return data


def _save(project, data):
    path = _path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["schema"] = SCHEMA
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(path)


def paragraphs_of(text):
    return [row.strip() for row in re.split(r"\n\s*\n", str(text or "")) if row.strip()]


def _finding(rule_id, quote, *, paragraph, start, end, suggestion):
    rule = RULES[rule_id]
    return {"rule_id": rule_id, "category": rule["category"], "severity": rule["severity"],
            "advisory": bool(rule["advisory"]), "paragraph": paragraph, "range": [start, end],
            "quote": quote[:200], "suggestion": suggestion, "condition": rule["condition"]}


def _ignored(quote, ignore_terms):
    for term in ignore_terms or ():
        if term and str(term) in quote:
            return str(term)
    return ""


def _body_of(row, marker):
    """去掉标记词本身，只留这一段真正说的话，用来判断两段收束是否真的重复。"""
    return re.sub(r"\s+", "", str(row).replace(marker, "", 1))


def _similar_paragraph(first, second):
    if not first or not second:
        return False
    if first == second:
        return True
    grams = {first[index:index + 2] for index in range(len(first) - 1)}
    other = {second[index:index + 2] for index in range(len(second) - 1)}
    if not grams or not other:
        return False
    return len(grams & other) / min(len(grams), len(other)) >= 0.5


def check(text, *, scope="chapter", ignore_terms=(), record=True, project=None):
    """本地检测：只给定位与建议，不改正文、不调模型。"""
    rows = paragraphs_of(text)
    findings, ignored = [], 0
    summary_hits = []
    for index, row in enumerate(rows):
        marker = next((word for word in SUMMARY_MARKERS if word in row), "")
        if marker:
            summary_hits.append((index, marker, _body_of(row, marker)))
        # 「重复小结」要真有两个内容相近的收束段，不能只要出现两次标记词就报。
        if len(summary_hits) >= 2:
            previous = summary_hits[-2]
            if _similar_paragraph(previous[2], summary_hits[-1][2]):
                if _ignored(row, ignore_terms):
                    ignored += 1
                else:
                    findings.append(_finding("style.dup_summary", row, paragraph=index,
                                             start=0, end=len(row),
                                             suggestion="总结性段落只留一处，或改成动作/物件收束"))
        if index == len(rows) - 1:
            tail = next((word for word in EXPLAIN_MARKERS if word in row), "")
            if tail:
                if _ignored(row, ignore_terms):
                    ignored += 1
                else:
                    findings.append(_finding("style.explainer_tail", row, paragraph=index,
                                             start=row.index(tail), end=len(row),
                                             suggestion="删掉解释句，让结尾停在动作或画面上"))
        if any(word in row for word in ("保证过审", "一定能上榜", "必上推荐")):
            findings.append(_finding("platform.no_basis_claim", row, paragraph=index,
                                     start=0, end=len(row), suggestion="平台规则只作提醒，不承诺过审"))
        flat = re.sub(r"\s+", "", row)
        for match in re.finditer(r"([\u4e00-\u9fff]{2})\1", flat):
            word = match.group(0)
            if word[:2] in STACK_WHITELIST or word[:2] in REDUP_WHITELIST or _ignored(word, ignore_terms):
                ignored += 1
                continue
            findings.append(_finding("style.tautology", word, paragraph=index,
                                     start=match.start(), end=match.end(),
                                     suggestion=f"「{word}」重复，删掉一个或换说法"))
    # 同质对白：连续四句长度接近且同以「我/你/他/她」开头
    run = []
    for index, row in enumerate(rows):
        match = DIALOGUE.match(row)
        if not match:
            run = []
            continue
        line = match.group(1).strip()
        if run and (abs(len(line) - len(run[-1][1])) <= 6 and line[:1] == run[-1][1][:1]):
            run.append((index, line))
        elif not run:
            run = [(index, line)]
        else:
            run = [(index, line)]
        if len(run) >= 4:
            quote = " / ".join(item[1][:20] for item in run)
            if not _ignored(quote, ignore_terms):
                findings.append(_finding("style.homogeneous_dialogue", quote, paragraph=run[0][0],
                                         start=0, end=len(quote),
                                         suggestion="给其中一两句换长度、换开头或改成动作"))
            run = []
    findings = findings[:MAX_FINDINGS]
    if record and project is not None:
        data = _load(project)
        data["checks"] = int(data.get("checks") or 0) + 1
        data["paragraphs"] = int(data.get("paragraphs") or 0) + len(rows)
        data["findings"] = int(data.get("findings") or 0) + len(findings)
        data["last_check_at"] = bridge.now_iso()
        data["last_scope"] = str(scope or "")
        _save(project, data)
    return {"scope": scope, "paragraphs": len(rows), "findings": findings,
            "counts": {rule_id: sum(1 for row in findings if row["rule_id"] == rule_id) for rule_id in RULES},
            "ignored": ignored, "advisory_only": [row["rule_id"] for row in findings if row["advisory"]]}


def record_action(project, rule_id, action, *, note="", actor="author"):
    """采纳/忽略/误报都记原数；误报样本用于后续收紧规则。"""
    if rule_id not in RULES:
        raise ValueError("规则 ID 无效")
    if action not in ACTIONS:
        raise ValueError("动作无效")
    data = _load(project)
    data["actions"][action] = int(data["actions"].get(action) or 0) + 1
    samples = data.setdefault("samples", [])
    samples.append({"rule_id": rule_id, "action": action, "at": bridge.now_iso(),
                    "actor": str(actor or ""), "note": str(note or "")[:200]})
    del samples[:-LEDGER_LIMIT]
    _save(project, data)
    return {"status": "recorded", "rule_id": rule_id, "action": action}


def metrics(project):
    data = _load(project)
    rows = int(data.get("paragraphs") or 0)
    findings = int(data.get("findings") or 0)
    actions = data.get("actions") or {}
    return {"checks": int(data.get("checks") or 0), "paragraphs": rows, "findings": findings,
            "per_100_paragraphs": round(findings * 100 / rows, 2) if rows else None,
            "accepted": int(actions.get("accepted") or 0), "ignored": int(actions.get("ignored") or 0),
            "false_positive": int(actions.get("false_positive") or 0),
            "samples": len(data.get("samples") or []),
            "note": "只报计数与每百段提示数；样本不足时不宣称文风指标下降。"}


def ignore_terms(project, terms=None, *, limit=20):
    """作品级忽略词表（口癖、诗句、刻意重复），只用于抑制本作品的提示。"""
    path = Path(project).resolve() / ".webnovel" / "style_ignore.json"
    if terms is None:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [str(row) for row in data.get("terms") or []][:limit]
    values = []
    for row in terms:
        text = str(row or "").strip()
        if not text or len(text) > 40:
            raise ValueError("忽略词无效")
        if text not in values:
            values.append(text)
    if len(values) > limit:
        raise ValueError("忽略词过多")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"terms": values}, ensure_ascii=False), encoding="utf-8")
    return values


def public(project=None):
    """给界面/文档用的规则清单：每条都带正反例与是否只提醒。"""
    return [{"rule_id": key, **{field: value for field, value in rule.items()}} for key, rule in RULES.items()]
