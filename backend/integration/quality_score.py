"""六维质量评分：只做"结构化结果 → 加权总分"的确定性计算。

模型只负责给分项、问题与证据；总分、权重、门槛、放行与否全部由程序算。
任何缺失/无法解析的情况都如实记录，不补造分数。
"""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

DIMENSIONS = (
    ("setting", "设定自洽"),
    ("plot", "情节推进"),
    ("character", "人物塑造"),
    ("prose", "文笔"),
    ("dialogue", "对话"),
    ("style", "文风"),
)
NAMES = dict(DIMENSIONS)
ALIASES = {
    "设定自洽": "setting", "设定": "setting", "setting": "setting", "consistency": "setting",
    "情节推进": "plot", "情节": "plot", "plot": "plot", "pacing": "plot",
    "人物塑造": "character", "人物": "character", "角色": "character", "character": "character",
    "文笔": "prose", "文字": "prose", "prose": "prose",
    "对话": "dialogue", "对白": "dialogue", "dialogue": "dialogue",
    "文风": "style", "风格": "style", "style": "style",
}
DEFAULT_WEIGHTS = {"setting": 15, "plot": 20, "character": 15, "prose": 15, "dialogue": 15, "style": 20}
DEFAULT_TOTAL = 85
DEFAULT_ITEM = 70
SEVERITIES = ("critical", "high", "advisory")
SEVERITY_ALIASES = {
    "critical": "critical", "严重": "critical", "阻断": "critical", "致命": "critical", "p0": "critical",
    "high": "high", "高": "high", "重要": "high", "p1": "high",
    "advisory": "advisory", "medium": "advisory", "low": "advisory", "中": "advisory", "低": "advisory",
    "建议": "advisory", "p2": "advisory", "p3": "advisory",
}


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = Decimal(str(value))
    elif isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if not match:
            return None
        number = Decimal(match.group(0))
    else:
        return None
    if number != number or number < 0 or number > 100:  # NaN 或越界都视为无效
        return None
    return float(number)


def _normalized_weights(weights):
    # 显式给了权重就只用给的维度：没写的维度记 0，等价于"本次不参与加权"。
    provided = isinstance(weights, dict) and bool(weights)
    values = {}
    for key, _ in DIMENSIONS:
        raw = weights.get(key, 0 if provided else DEFAULT_WEIGHTS[key]) if isinstance(weights, dict) else DEFAULT_WEIGHTS[key]
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f"维度权重无效：{key}")
        if value < 0:
            raise ValueError(f"维度权重无效：{key}")
        values[key] = value
    total = sum(values.values())
    if total <= 0:
        raise ValueError("维度权重之和必须大于 0")
    return {key: float(value * 100 / total) for key, value in values.items()}


def settings(config=None):
    """审查配置：权重、总门槛、单项门槛。缺省值是可调的初始启发式，不冒充客观标准。"""
    doc = (config or {}).get("review_quality") if isinstance(config, dict) else None
    doc = doc if isinstance(doc, dict) else {}
    weights = _normalized_weights(doc.get("weights") if isinstance(doc.get("weights"), dict) else {})
    total = _number(doc.get("threshold_total")) if doc.get("threshold_total") is not None else float(DEFAULT_TOTAL)
    item = _number(doc.get("threshold_item")) if doc.get("threshold_item") is not None else float(DEFAULT_ITEM)
    if total is None:
        raise ValueError("审查总分门槛无效")
    if item is None:
        raise ValueError("审查单项门槛无效")
    return {"weights": weights, "threshold_total": total, "threshold_item": item,
            "source": "ai_internal_heuristic", "dimensions": [{"key": key, "name": name} for key, name in DIMENSIONS]}


def config_hash(values=None):
    values = settings() if values is None else values
    payload = json.dumps({"weights": values["weights"], "total": values["threshold_total"],
                          "item": values["threshold_item"]}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _balanced_object(text):
    start = text.find("{")
    while start != -1:
        depth = 0
        for index in range(start, len(text)):
            char = text[index]
            if char == '"':
                index += 1
                while index < len(text) and text[index] != '"':
                    index += 2 if text[index] == "\\" else 1
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    yield text[start:index + 1]
                    break
        start = text.find("{", start + 1)


def _dimension_key(name):
    if not isinstance(name, str):
        return None
    key = name.strip().lower()
    return ALIASES.get(name.strip()) or ALIASES.get(key)


def _severity(value):
    if not isinstance(value, str):
        return "advisory"
    return SEVERITY_ALIASES.get(value.strip().lower(), SEVERITY_ALIASES.get(value.strip(), "advisory"))


def extract(payload):
    """从模型输出里取出分项与问题。接受 dict 或文本；解析失败如实返回，不猜分数。"""
    result = {"format": "none", "scores": {}, "not_applicable": [], "issues": [], "verdict": None,
              "evidence": "", "error": None, "raw": payload if isinstance(payload, str) else None}
    if isinstance(payload, dict):
        source, result["format"] = payload, "json"
    elif isinstance(payload, str):
        text = payload.strip()
        if text.startswith("```"):
            body = text.split("\n", 1)[-1]
            text = body.rsplit("```", 1)[0] if body.rstrip().endswith("```") else body
        for chunk in _balanced_object(text):
            try:
                source = json.loads(chunk)
            except ValueError:
                continue
            if isinstance(source, dict):
                result["format"] = "json"
                break
        else:
            result["format"] = "text"
            result["verdict"] = _text_verdict(payload)
            return result
    else:
        result["error"] = "unsupported_payload"
        return result

    raw_scores = source.get("scores") if isinstance(source.get("scores"), dict) else source.get("dimensions")
    if isinstance(raw_scores, dict):
        for name, value in raw_scores.items():
            key = _dimension_key(name)
            if not key:
                continue
            score = _number(value.get("score") if isinstance(value, dict) else value)
            if score is None:
                result["error"] = result["error"] or f"score_invalid:{key}"
                continue
            result["scores"][key] = score
    for name in source.get("not_applicable") or []:
        key = _dimension_key(name)
        if key and key not in result["scores"]:
            result["not_applicable"].append(key)
    for item in source.get("issues") or []:
        if not isinstance(item, dict):
            continue
        dimension = _dimension_key(item.get("dimension") or item.get("维度"))
        text = str(item.get("issue") or item.get("problem") or item.get("问题") or "").strip()
        if not text:
            continue
        result["issues"].append({
            "dimension": dimension,
            "severity": _severity(item.get("severity") or item.get("级别")),
            "issue": text[:600],
            "evidence": str(item.get("evidence") or item.get("依据") or item.get("source") or "").strip()[:600],
            "advice": str(item.get("advice") or item.get("建议") or "").strip()[:400],
        })
    verdict = source.get("verdict") or source.get("decision") or source.get("conclusion") or source.get("结论")
    if isinstance(verdict, str):
        token = verdict.strip().lower()
        if token in ("pass", "ok", "approved"):
            result["verdict"] = "pass"
        elif token in ("needs_revision", "needs-revision", "revise", "reject"):
            result["verdict"] = "needs_revision"
        elif re.search(r"无需修改|不需要修改|通过|可直接采用", verdict):
            result["verdict"] = "pass"
        elif re.search(r"需(?:要)?修改|需要改|退回", verdict):
            result["verdict"] = "needs_revision"
        else:
            result["verdict"] = None
    result["evidence"] = str(source.get("summary") or source.get("reason") or source.get("原因") or "").strip()[:800]
    return result


def _text_verdict(text):
    if re.search(r"结论\s*[:：]\s*无需修改|未发现(?:明显)?问题|审查通过", text):
        return "pass"
    if re.search(r"结论\s*[:：]\s*需修改|^P[01]", text, re.MULTILINE):
        return "needs_revision"
    return None


def compute(payload, values=None):
    """加权总分。缺维度不算分：标记 incomplete，不拿 0 分充数。"""
    values = settings() if values is None else values
    parsed = extract(payload) if not (isinstance(payload, dict) and "scores" in payload and "format" in payload) else payload
    scores = dict(parsed.get("scores") or {})
    applicable = [key for key, _ in DIMENSIONS if key in parsed.get("not_applicable", []) or key in scores]
    scored = [key for key, _ in DIMENSIONS if key in scores]
    missing = [key for key, _ in DIMENSIONS if key not in scores and key not in parsed.get("not_applicable", [])]
    weight_sum = sum(values["weights"][key] for key in scored)
    total = None
    if scored and weight_sum > 0:
        total = round(sum(scores[key] * values["weights"][key] for key in scored) / weight_sum, 2)
    blocking = [issue for issue in parsed.get("issues", []) if issue["severity"] in ("critical", "high") and issue["evidence"]]
    unverified = [issue for issue in parsed.get("issues", []) if issue["severity"] in ("critical", "high") and not issue["evidence"]]
    return {
        "format": parsed.get("format", "none"),
        "total": total,
        "scores": {key: scores[key] for key in scored},
        "names": {key: NAMES[key] for key in scored},
        "missing": missing,
        "not_applicable": list(parsed.get("not_applicable") or []),
        "incomplete": bool(missing),
        "complete": not missing and bool(scored),
        "issues": parsed.get("issues", []),
        "blocking": blocking,
        "unverified": unverified,
        "verdict": parsed.get("verdict"),
        "evidence": parsed.get("evidence", ""),
        "error": parsed.get("error"),
        "thresholds": {"total": values["threshold_total"], "item": values["threshold_item"]},
        "weights": {key: values["weights"][key] for key in scored},
        "config_hash": config_hash(values),
        "source": values.get("source"),
    }
