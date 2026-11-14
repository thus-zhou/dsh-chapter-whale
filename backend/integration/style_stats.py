"""文风样本的确定性统计与代表片段抽样。

只做可复现的字符/句段/标点统计；"叙事比例""情绪曲线"这类语义判断交给模型，
并且永远标注为模型推断，不混进程序统计里。
"""
import re
from collections import Counter

SENTENCE_END = "。！？…!?；;"
DIALOGUE_WRAPPERS = (("「", "」"), ("『", "』"), ("“", "”"), ("\"", "\""))
PUNCTUATION = "，。！？…、；：“”‘’（）《》—「」『』,.!?;:\"'()"
MAX_STAT_CHARS = 400_000


def _sentences(text):
    buffer, result = [], []
    for char in text:
        buffer.append(char)
        if char in SENTENCE_END:
            result.append("".join(buffer).strip())
            buffer = []
    tail = "".join(buffer).strip()
    if tail:
        result.append(tail)
    return [item for item in result if item]


def _dialogue_chars(text):
    total = 0
    for opener, closer in DIALOGUE_WRAPPERS:
        start = 0
        while True:
            left = text.find(opener, start)
            if left < 0:
                break
            right = text.find(closer, left + len(opener))
            if right < 0:
                break
            total += right - left - len(opener)
            start = right + len(closer)
    return total


def _distribution(values):
    if not values:
        return {"count": 0, "mean": 0, "median": 0, "p90": 0, "max": 0}
    ordered = sorted(values)
    count = len(ordered)
    return {
        "count": count,
        "mean": round(sum(ordered) / count, 1),
        "median": ordered[count // 2],
        "p90": ordered[min(count - 1, int(count * 0.9))],
        "max": ordered[-1],
    }


def statistics(text):
    """同一文本永远得到同一结果；只统计前 40 万字，并在返回里写明范围。"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    scope = text[:MAX_STAT_CHARS]
    paragraphs = [line.strip() for line in scope.split("\n") if line.strip()]
    sentences = _sentences(scope)
    characters = len(scope)
    punctuation = Counter(char for char in scope if char in PUNCTUATION)
    repeated = Counter(char for char in scope if not char.isspace() and char not in PUNCTUATION)
    dialogue = _dialogue_chars(scope)
    return {
        "characters": characters,
        "truncated": len(text) > MAX_STAT_CHARS,
        "paragraphs": len(paragraphs),
        "sentences": len(sentences),
        "sentence_length": _distribution([len(item) for item in sentences]),
        "paragraph_length": _distribution([len(item) for item in paragraphs]),
        "punctuation": {char: punctuation[char] for char in sorted(punctuation, key=lambda c: (-punctuation[c], c))[:12]},
        "dialogue_ratio": round(dialogue / characters, 3) if characters else 0.0,
        "top_characters": [{"char": char, "count": count} for char, count in repeated.most_common(5)],
        "note": "程序统计；叙事比例、情绪等语义判断不在其中",
    }


def sample_plan(text, budget=42000):
    """代表片段：开头、中部、结尾，加一段对话最密集的片段。预算内能少取就不多取。"""
    text = (text or "").replace("\r\n", "\n")
    length = len(text)
    if length == 0:
        return []
    if length <= budget:
        return [{"index": 0, "label": "全文", "start": 0, "length": length}]
    window = min(14000, budget)
    picks = [{"label": "开头", "start": 0}]
    if length > window * 2:
        picks.append({"label": "中部", "start": max(0, length // 2 - window // 2)})
    picks.append({"label": "结尾", "start": max(0, length - window)})
    dialogue_at = _densest_dialogue(text, window)
    if dialogue_at is not None and all(abs(dialogue_at - item["start"]) > window for item in picks):
        picks.append({"label": "对话", "start": dialogue_at})
    plan, used = [], 0
    for item in picks:
        if used + window > budget:
            break
        plan.append({"index": len(plan), "label": item["label"], "start": item["start"], "length": window})
        used += window
    return plan


def _densest_dialogue(text, window):
    if len(text) <= window:
        return None
    step = max(2000, window // 4)
    best, best_at = -1, None
    for start in range(0, len(text) - window + 1, step):
        score = _dialogue_chars(text[start:start + window])
        if score > best:
            best, best_at = score, start
    return best_at if best > 0 else None


def excerpt(text, plan):
    return [text[item["start"]:item["start"] + item["length"]] for item in plan]


def summary(stats):
    """给界面用的一行行中文说明。"""
    if not stats:
        return ["暂无统计"]
    sentence = stats.get("sentence_length", {})
    paragraph = stats.get("paragraph_length", {})
    rows = [
        f"样本 {stats.get('characters', 0)} 字（程序统计，{'仅统计前 40 万字' if stats.get('truncated') else '全文'}）",
        f"句长：中位 {sentence.get('median', 0)} 字，90% 不超过 {sentence.get('p90', 0)} 字",
        f"段长：中位 {paragraph.get('median', 0)} 字，最长 {paragraph.get('max', 0)} 字",
        f"对话占比约 {round(float(stats.get('dialogue_ratio', 0)) * 100)}%（按引号内字符估算）",
    ]
    top = stats.get("top_characters") or []
    if top:
        rows.append("高频字：" + "、".join(f"{item['char']}({item['count']})" for item in top))
    return rows
