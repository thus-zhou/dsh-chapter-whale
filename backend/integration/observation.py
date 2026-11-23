"""D02：读者反馈观察卡与可撤销建议。

规则（`04_v0.8.0_读者反馈与可撤销建议.md`）：
- 卡片只引用固定快照（批次/窗口/分母/阶段），把相关性写成「备选解释」，不当因果；
- 生命周期：候选 → 采纳（指定章段生效）→ 到期/撤销；忽略是终态；
- 未被采纳、已撤销、超出章段、已到期、已忽略的卡片**一律不进**规划/提示/审查/配置，
  唯一出口是 `reminder_block()`，所有注入点都只能调它；
- 撤销只移除未来注入；已写的正文用独立的版本工具回退，本模块不碰正文；
- 评论恶意文本在导入时已被标记，这里只当数据展示，绝不执行其中指令。
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from integration import bridge, reader_metrics

SCHEMA = 1
STATUSES = ("candidate", "adopted", "ignored", "revoked", "expired")
MAX_CARDS = 500
DEFAULT_CHAPTERS = 3
DEFAULT_DAYS = 14


def store_path(project: Path) -> Path:
    return Path(project) / ".webnovel" / "observations.json"


def _now(now: Optional[dt.datetime] = None) -> dt.datetime:
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)


def _empty() -> Dict[str, Any]:
    return {"schema": SCHEMA, "updated_at": "", "cards": []}


def load(project: Path) -> Dict[str, Any]:
    data = bridge.read_json(store_path(project), {})
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("schema", SCHEMA)
    data.setdefault("updated_at", "")
    if not isinstance(data.get("cards"), list):
        data["cards"] = []
    return data


def save(project: Path, data: Dict[str, Any]) -> None:
    data["updated_at"] = _now().isoformat()
    bridge.write_json_atomic(store_path(project), data)


def _card(data: Dict[str, Any], card_id: str) -> Dict[str, Any]:
    for card in data["cards"]:
        if isinstance(card, dict) and card.get("id") == card_id:
            return card
    raise ValueError(f"找不到观察卡：{card_id}")


# --- 生成 -------------------------------------------------------------------

def build(project: Path, *, chapter: int, metric: str = "chapter_completion_rate",
          chapters: int = DEFAULT_CHAPTERS, days: int = DEFAULT_DAYS,
          work_id: str = "", now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """从已有读数生成候选卡；没有可回源读数就不造卡。"""
    chapter = int(chapter)
    if chapter < 1:
        raise ValueError("章号无效")
    if not 1 <= int(chapters) <= 20:
        raise ValueError("建议范围必须是 1–20 章")
    if not 1 <= int(days) <= 120:
        raise ValueError("到期天数必须是 1–120")
    rows = reader_metrics.rows_for(project, metric=metric, chapter_id=chapter, work_id=work_id)
    if not rows:
        raise ValueError("该章还没有可回源的读数，先导入读者数据")
    latest = rows[-1]
    book = str(work_id or latest.get("work_id") or "")
    previous = None
    for item in reversed(rows[:-1]):
        if item.get("metric") == metric:
            previous = item
            break
    stage = "new" if _days_since(latest.get("window_end"), now) < 7 else "mature"
    limitations: List[str] = []
    if not latest.get("denominator_known"):
        limitations.append("分母未知：只能说读数变化，不能算比例差异。")
    if stage == "new":
        limitations.append("窗口结束不足 7 天：不与累积数周的章直接比较。")
    if previous is None:
        limitations.append("没有上一窗口的对照读数，无法判断趋势。")
    comments = reader_metrics.cluster_comments(project, chapter)
    sanitized = []
    for group in comments[:3]:
        sanitized.append({"topic": group["topic"], "count": group["count"],
                          "samples": [text[:80] for text in group.get("samples", [])[:1]]})
    delta = None
    if previous is not None:
        try:
            delta = round(float(latest["value"]) - float(previous["value"]), 2)
        except (TypeError, ValueError):
            delta = None
    alternatives = [
        "曝光变化：推荐位、封面或标题调整会改变进入人数。",
        "更新间隔：断更或加更都会改变单章读数。",
        "窗口错位：不同成熟窗口的读数不可直接相减。",
    ]
    stamp = _now(now)
    seed = f"{project}|{book}|{chapter}|{metric}|{latest.get('key')}|{stamp.isoformat()}"
    card = {
        "id": hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16],
        "status": "candidate",
        "work_id": book,
        "chapter": chapter,
        "metric": metric,
        "metric_label": reader_metrics.METRICS.get(metric, {}).get("label", metric),
        "snapshot": {
            "key": latest.get("key"),
            "value": latest.get("value"),
            "unit": latest.get("unit"),
            "window": [latest.get("window_start"), latest.get("window_end")],
            "observed_at": latest.get("observed_at"),
            "denominator": latest.get("denominator"),
            "denominator_known": bool(latest.get("denominator_known")),
            "batch": latest.get("batch"),
            "caliber_version": latest.get("caliber_version"),
            "stage": stage,
        },
        "previous": None if previous is None else {
            "value": previous.get("value"),
            "window": [previous.get("window_start"), previous.get("window_end")],
            "batch": previous.get("batch"),
        },
        "delta": delta,
        "comments": sanitized,
        "alternatives": alternatives,
        "limitations": limitations,
        "suggested_range": {"from": chapter + 1, "to": chapter + int(chapters), "chapters": int(chapters)},
        "expires_at": (stamp + dt.timedelta(days=int(days))).isoformat(),
        "created_at": stamp.isoformat(),
        "updated_at": stamp.isoformat(),
        "actor": "",
        "basis": {"caliber_version": reader_metrics.CALIBER_VERSION, "batch": latest.get("batch")},
    }
    data = load(project)
    data["cards"].append(card)
    data["cards"] = data["cards"][-MAX_CARDS:]
    save(project, data)
    return card


def _days_since(window_end: Any, now: Optional[dt.datetime]) -> int:
    try:
        end = dt.date.fromisoformat(str(window_end))
    except (TypeError, ValueError):
        return 999
    return (_now(now).date() - end).days


# --- 生命周期 ----------------------------------------------------------------

def adopt(project: Path, card_id: str, *, chapters: Optional[int] = None,
          expires_at: Optional[str] = None, actor: str = "author",
          now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """采纳：只在指定章段内生效，到期自动结束；不写正文、不改创作约定。"""
    data = load(project)
    card = _card(data, card_id)
    if card.get("status") != "candidate":
        raise ValueError(f"只有候选卡可以采纳，当前状态：{card.get('status')}")
    stamp = _now(now)
    start = int(card["chapter"]) + 1
    span = int(chapters if chapters is not None else card["suggested_range"]["chapters"])
    if not 1 <= span <= 20:
        raise ValueError("生效章数必须是 1–20")
    if expires_at:
        try:
            expires = dt.datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("到期时间不是 ISO 时刻")
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=dt.timezone.utc)
    else:
        expires = stamp + dt.timedelta(days=DEFAULT_DAYS)
    if expires <= stamp:
        raise ValueError("到期时间必须晚于现在")
    card["status"] = "adopted"
    card["actor"] = str(actor or "author")
    card["adopted_at"] = stamp.isoformat()
    card["updated_at"] = stamp.isoformat()
    card["range"] = {"from": start, "to": start + span - 1}
    card["expires_at"] = expires.astimezone(dt.timezone.utc).isoformat()
    card["reminder"] = _reminder_text(card)
    save(project, data)
    return card


def ignore(project: Path, card_id: str, *, actor: str = "author",
           now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    data = load(project)
    card = _card(data, card_id)
    if card.get("status") != "candidate":
        raise ValueError(f"只有候选卡可以忽略，当前状态：{card.get('status')}")
    stamp = _now(now)
    card["status"] = "ignored"
    card["actor"] = str(actor or "author")
    card["updated_at"] = stamp.isoformat()
    save(project, data)
    return card


def revoke(project: Path, card_id: str, *, reason: str = "", actor: str = "author",
           now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """撤销：移除未来注入，已写正文不动（要用版本工具单独回退）。"""
    data = load(project)
    card = _card(data, card_id)
    if card.get("status") not in ("adopted", "candidate"):
        raise ValueError(f"当前状态不能撤销：{card.get('status')}")
    stamp = _now(now)
    card["status"] = "revoked"
    card["actor"] = str(actor or "author")
    card["revoked_at"] = stamp.isoformat()
    card["updated_at"] = stamp.isoformat()
    card["revoke_reason"] = str(reason or "")
    save(project, data)
    return card


def expire_due(project: Path, *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """把到期的采纳卡标为 expired；候选卡不动。"""
    stamp = _now(now)
    data = load(project)
    changed = 0
    for card in data["cards"]:
        if not isinstance(card, dict) or card.get("status") != "adopted":
            continue
        try:
            expires = dt.datetime.fromisoformat(str(card.get("expires_at")))
        except ValueError:
            continue
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=dt.timezone.utc)
        if expires <= stamp:
            card["status"] = "expired"
            card["updated_at"] = stamp.isoformat()
            changed += 1
    if changed:
        save(project, data)
    return {"expired": changed}


def get(project: Path, card_id: str) -> Dict[str, Any]:
    return _card(load(project), card_id)


def list_cards(project: Path, *, status: str = "", chapter: Optional[int] = None,
               work_id: str = "", now: Optional[dt.datetime] = None,
               touch: bool = False) -> List[Dict[str, Any]]:
    """读列表默认是纯计算（到期只按 now 过滤，不写盘）；需要落库时显式传 touch=True。"""
    if touch:
        expire_due(project, now=now)
    stamp = _now(now)
    cards = []
    for card in load(project)["cards"]:
        if not isinstance(card, dict):
            continue
        if not touch and card.get("status") == "adopted" and _is_expired(card, stamp):
            continue
        if status and card.get("status") != status:
            continue
        if work_id and str(card.get("work_id") or "") != str(work_id):
            continue
        if chapter is not None and int(card.get("chapter") or 0) != int(chapter):
            continue
        cards.append(card)
    cards.sort(key=lambda item: str(item.get("created_at")), reverse=True)
    return cards


def current_work_id(project: Path) -> str:
    """当前作品标识：取最近一次读数导入的 work_id；没有就返回空串（不过滤）。"""
    try:
        data = reader_metrics.load(project)
    except (OSError, ValueError, TypeError):
        return ""
    for batch in reversed(data.get("batches") or []):
        if isinstance(batch, dict) and batch.get("work_id"):
            return str(batch["work_id"])
    return ""


def _is_expired(card: Dict[str, Any], stamp: dt.datetime) -> bool:
    try:
        expires = dt.datetime.fromisoformat(str(card.get("expires_at")))
    except ValueError:
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=dt.timezone.utc)
    return expires <= stamp


# --- 注入闸门（唯一出口） -----------------------------------------------------

def active_cards(project: Path, chapter: int, *, work_id: str = "",
                 now: Optional[dt.datetime] = None) -> List[Dict[str, Any]]:
    """生效卡：已采纳、章段覆盖、未到期，且属于当前作品（同章号不同作品不串用）。"""
    stamp = _now(now)
    out = []
    for card in load(project)["cards"]:
        if not isinstance(card, dict) or card.get("status") != "adopted":
            continue
        if work_id and str(card.get("work_id") or "") != str(work_id):
            continue
        scope = card.get("range") or {}
        try:
            low, high = int(scope.get("from")), int(scope.get("to"))
        except (TypeError, ValueError):
            continue
        if not (low <= int(chapter) <= high):
            continue
        if _is_expired(card, stamp):
            continue
        out.append(card)
    return out


def reminder_block(project: Path, chapter: int, *, work_id: str = "",
                   now: Optional[dt.datetime] = None) -> str:
    """审查/修订/上下文唯一允许的注入形式；没有生效卡就返回空串。"""
    cards = active_cards(project, chapter, work_id=work_id, now=now)
    if not cards:
        return ""
    lines = ["【作者已采纳的读者反馈提醒（仅限提示范围，不得据此改动作者锁定设定）】"]
    for card in cards:
        scope = card.get("range") or {}
        snapshot = card.get("snapshot") or {}
        lines.append(
            f"- 第{scope.get('from')}–{scope.get('to')}章：{card.get('reminder')}"
            f"（依据：{snapshot.get('value')}{snapshot.get('unit')}，窗口 {snapshot.get('window')}，"
            f"批次 {snapshot.get('batch')}）"
        )
        for limit in card.get("limitations") or []:
            lines.append(f"  局限：{limit}")
    lines.append("这些是读者反馈的相关性提示，不是因果结论；与创作约定冲突时以约定为准并指出冲突。")
    return "\n".join(lines)


def _reminder_text(card: Dict[str, Any]) -> str:
    metric = card.get("metric_label") or card.get("metric")
    delta = card.get("delta")
    if delta is None:
        core = f"{metric}读数为 {card['snapshot'].get('value')}{card['snapshot'].get('unit') or ''}，尚无对照窗口"
    else:
        direction = "上升" if delta > 0 else ("下降" if delta < 0 else "持平")
        core = f"{metric}{direction} {abs(delta)}{card['snapshot'].get('unit') or ''}（与上一窗口比）"
    topics = "、".join(group["topic"] for group in (card.get("comments") or [])[:2])
    tail = f"；评论主题集中在{topics}" if topics else ""
    return f"在接下来几章审视节奏与信息密度{core}{tail}"


# --- 大纲差异（只比较，不覆盖） -----------------------------------------------

def outline_diff(project: Path, card_id: str) -> Dict[str, Any]:
    """把建议与作者创作约定逐字段比较，列出冲突与可选项；本函数不写任何文件。"""
    card = _card(load(project), card_id)
    doc = bridge.read_json(Path(project) / ".webnovel" / "creative_brief.json", {})
    brief = doc.get("brief") if isinstance(doc, dict) else {}
    if not isinstance(brief, dict):
        brief = {}
    pacing = str(brief.get("pacing") or "")
    ending = str(brief.get("ending") or "")
    suggestion = str(card.get("reminder") or "")
    conflicts = []
    if pacing:
        conflicts.append({"field": "pacing", "current": pacing[:200],
                          "proposal": suggestion,
                          "choice": "保留原节奏，只做局部调整；或改写 pacing 后重新生成预览。"})
    else:
        conflicts.append({"field": "pacing", "current": "",
                          "proposal": suggestion,
                          "choice": "先在创作约定里补节奏描述，再决定是否采纳。"})
    if ending:
        conflicts.append({"field": "ending", "current": ending[:120],
                          "proposal": "读者反馈不指向结局，不要据此改动主线结局。",
                          "choice": "保持主线不变。"})
    return {
        "card": card.get("id"),
        "revision": int(doc.get("revision") or 0) if isinstance(doc, dict) else 0,
        "conflicts": conflicts,
        "applied": False,
        "note": "差异只作选择材料；接受需在创作约定页面按版本条件更新（expected revision），本接口不覆盖作者设定。",
    }
