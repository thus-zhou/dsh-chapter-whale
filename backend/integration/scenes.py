"""场景卡：来自 A 规划的同一次输出，或按现有细纲确定性拆分。不调用模型。"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

from . import bridge, writer_runner as writer

SCHEMA = 1
MAX_SCENES = 3
MIN_SCENES = 1
MAX_TARGET = 12000
CALM_WORDS = ("过渡", "日常", "安静", "休整", "路上", "回忆")
TENSE_WORDS = ("冲突", "反转", "危机", "追逐", "决裂", "揭露", "打斗")


def _folder(project):
    project = Path(project).resolve()
    folder = project / ".webnovel" / "scenes"
    if folder.exists() and (folder.is_symlink() or project not in folder.resolve().parents):
        raise ValueError("场景目录不安全")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def plan_hash(project):
    path = Path(project).resolve() / ".webnovel" / "story_plan.json"
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def _chapter_entry(project, chapter):
    path = Path(project).resolve() / ".webnovel" / "story_plan.json"
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = doc.get("chapters") or []
    # 规划作者可能把章节写成列表，也可能写成 {章号: {...}}；两种都要能读。
    if isinstance(rows, dict):
        rows = [dict(value, id=value.get("id") or key) if isinstance(value, dict) else {"id": key}
                for key, value in rows.items()]
    for row in rows:
        if not isinstance(row, dict):
            continue
        if int(row.get("id") or 0) == int(chapter):
            return row
    return {}


def _calm(text):
    if any(word in text for word in TENSE_WORDS):
        return False
    return any(word in text for word in CALM_WORDS)


def _split_outline(outline, count):
    text = re.sub(r"\s+", " ", str(outline or "")).strip()
    if not text:
        return [""] * count
    parts = [x for x in re.split(r"(?<=[。！？；;])", text) if x.strip()]
    if len(parts) <= count:
        return (parts + [""] * count)[:count]
    size = max(1, len(parts) // count)
    return ["".join(parts[i * size:(i + 1) * size])[:400] for i in range(count)]


def _card(index, purpose, target, *, characters=None, facts=None, calm=False, must_follow=""):
    return {"id": f"s{index + 1}", "position": index + 1,
            "characters": list(characters or []), "purpose": purpose[:200],
            "facts": list(facts or []), "info_change": "", "target_chars": int(target),
            "must_follow": str(must_follow or "")[:200], "calm": bool(calm)}


def validate(cards, word_count):
    if not isinstance(cards, list) or not (MIN_SCENES <= len(cards) <= MAX_SCENES):
        raise ValueError(f"场景数量必须是 {MIN_SCENES} 到 {MAX_SCENES} 个")
    seen = set()
    total = 0
    for card in cards:
        if not isinstance(card, dict):
            raise ValueError("场景卡格式无效")
        identifier = str(card.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", identifier) or identifier in seen:
            raise ValueError("场景 ID 无效或重复")
        seen.add(identifier)
        target = int(card.get("target_chars") or 0)
        if not (200 <= target <= MAX_TARGET):
            raise ValueError("场景预计长度超出范围")
        total += target
        for field in ("purpose", "must_follow"):
            if len(str(card.get(field) or "")) > 400:
                raise ValueError("场景卡文字过长")
    expected = int(word_count or 0)
    if expected and not (expected * 0.6 <= total <= expected * 1.6):
        raise ValueError("场景预计长度与本章目标差距过大")
    return cards


def plan(project, chapter, *, count=2, word_count=3500):
    """优先用 A 规划返回的场景卡；没有就按细纲拆，不额外请求模型。"""
    count = max(MIN_SCENES, min(MAX_SCENES, int(count or 2)))
    entry = _chapter_entry(project, chapter)
    supplied = entry.get("scenes")
    if isinstance(supplied, list) and supplied:
        cards = []
        for index, row in enumerate(supplied[:MAX_SCENES]):
            if not isinstance(row, dict):
                raise ValueError("场景卡格式无效")
            cards.append(_card(index, str(row.get("purpose") or row.get("goal") or ""),
                               int(row.get("target_chars") or max(800, word_count // max(1, len(supplied)))),
                               characters=row.get("characters"), facts=row.get("facts"),
                               calm=bool(row.get("calm")), must_follow=row.get("must_follow")))
        source = "plan"
    else:
        purpose = _split_outline(entry.get("outline"), count)
        target = max(600, int(word_count or 3500) // count)
        cards = [_card(index, purpose[index], target, calm=_calm(purpose[index])) for index in range(count)]
        source = "derived"
    validate(cards, word_count)
    return {"schema_version": SCHEMA, "chapter": int(chapter), "source": source,
            "plan_hash": plan_hash(project), "cards": cards}


def store(project, chapter, planned):
    path = _folder(project) / f"{int(chapter):04d}-{planned['plan_hash'][:16]}.json"
    payload = {"schema_version": SCHEMA, "chapter": int(chapter), "plan_hash": planned["plan_hash"],
               "source": planned["source"], "cards": planned["cards"], "created_at": bridge.now_iso()}
    writer.atomic_json(path, payload)
    return path


def load(project, chapter):
    folder = _folder(project)
    files = sorted(folder.glob(f"{int(chapter):04d}-*.json"))
    if not files:
        return None
    payload = json.loads(files[-1].read_text(encoding="utf-8"))
    payload["stale"] = payload.get("plan_hash") != plan_hash(project)
    payload["path"] = str(files[-1])
    return payload


def public(project, chapter, *, count=2, word_count=3500):
    stored = load(project, chapter)
    current = plan(project, chapter, count=count, word_count=word_count)
    return {"schema_version": SCHEMA, "chapter": int(chapter),
            "mode": "scenes", "estimate": {"requests": count, "review_requests": 1},
            "stored": stored, "current": current,
            "stale": bool(stored and stored.get("plan_hash") != current["plan_hash"]),
            "note": "场景模式不保证文笔更好；安静过渡场景不强制冲突、反转或钩子。"}
