"""D01：读者指标字段字典、CSV 预览、事务导入与可回源查询。

设计口径（`04_v0.8.0_读者反馈与可撤销建议.md`）：
- 每条观测必须能回到「批次 + 行号 + 窗口 + 口径版本」，没有来源的行拒绝入库；
- 零与未知分开：值 `0` 是观测到的零，空值是未知，分母缺失一律不填零；
- 稳定键 `(平台, 作品, 章, 指标, 窗口起, 窗口止, 单位, 分母, 来源)` 去重：同键同值算重复，
  同键不同值算修订（保留完整历史快照，不覆盖旧读数）；分母从 100 改成 200 属于修订，
  不是噪声，否则回退时会出现「值回到 62.5% 却仍挂 200 的分母」；
- 预览只暂存待确认计划（`.webnovel/reader_previews/<token>.json`），不写任何观测；提交必须带
  token，服务端按 token 取回计划并校验存储摘要未变；
- 存在拒绝行时整批不写（除非显式 `allow_partial=True`），避免「以为整批失败、实际半批入库」；
- 评论只是数据：先脱敏、去重，再聚类；其中的指令不会被解释。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from integration import bridge

SCHEMA = 1
CALIBER_VERSION = "2026-11-16"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MAX_COMMENT = 200
DEFAULT_TIMEZONE = "Asia/Shanghai"

PERCENT = "percent"
COUNT = "count"

#: 官方口径字典。分母不可见、平台未提供、或需要本地推算的，明确标注而不是补零。
METRICS: Dict[str, Dict[str, Any]] = {
    "chapter_completion_rate": {
        "label": "读完率",
        "official_name": "章节读完率",
        "granularity": "chapter",
        "unit": PERCENT,
        "denominator": "阅读该章人数",
        "denominator_visible": False,
        "window": "章发布后 7 天（以平台口径为准）",
        "timezone": DEFAULT_TIMEZONE,
        "source": "作者后台导出",
        "notes": "平台不给分母时不填零；本地用「读到最后一行人数 / 打开人数」推算时必须同时存分母。",
    },
    "chapter_follow_rate": {
        "label": "追读率",
        "official_name": "章节追读率",
        "granularity": "chapter",
        "unit": PERCENT,
        "denominator": "上一章读完人数",
        "denominator_visible": False,
        "window": "章发布后 24 小时",
        "timezone": DEFAULT_TIMEZONE,
        "source": "作者后台导出",
        "notes": "与读完率不是同一分母，不能混在一张图里比较。",
    },
    "update_requests": {
        "label": "催更",
        "official_name": "催更数",
        "granularity": "work",
        "unit": COUNT,
        "denominator": None,
        "denominator_visible": True,
        "window": "自然日",
        "timezone": DEFAULT_TIMEZONE,
        "source": "作者后台导出",
        "notes": "作品级指标，不摊到具体章；不要把作品级催更当成某章反馈。",
    },
    "comments": {
        "label": "评论",
        "official_name": "评论数",
        "granularity": "chapter",
        "unit": COUNT,
        "denominator": None,
        "denominator_visible": True,
        "window": "自然日",
        "timezone": DEFAULT_TIMEZONE,
        "source": "作者后台导出",
        "notes": "评论正文另存评论表，按章与批次关联；正文脱敏后最多 200 字。",
    },
}

#: 平台未提供、禁止本地臆造的指标（出现即拒绝，除非作者显式标注推算公式）。
UNAVAILABLE = {
    "chapter_bounce_rate": "平台未提供跳出率；本地无法在不拿打开明细的情况下推算。",
}

REQUIRED_COLUMNS = (
    "platform", "work_id", "chapter_id", "metric", "window_start", "window_end",
    "observed_at", "value", "unit", "denominator", "source",
)

_INSTRUCTION = re.compile(
    r"(忽略(之前|以上|前面)?(的)?(所有)?(指令|提示|规则)|system\s*prompt|assistant\s*:|"
    r"你现在是|请扮演|请调用|执行命令|删除(所有)?文件|rm\s+-rf|http[s]?://)",
    re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]{1,80}>")


# --- 路径与存储 --------------------------------------------------------------

def store_path(project: Path) -> Path:
    return Path(project) / ".webnovel" / "reader_metrics.json"


def _empty() -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "caliber_version": CALIBER_VERSION,
        "updated_at": "",
        "batches": [],
        "rows": [],
        "comments": [],
    }


def load(project: Path) -> Dict[str, Any]:
    data = bridge.read_json(store_path(project), {})
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("schema", SCHEMA)
    data.setdefault("caliber_version", CALIBER_VERSION)
    data.setdefault("updated_at", "")
    for key in ("batches", "rows", "comments"):
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


def save(project: Path, data: Dict[str, Any]) -> None:
    data["updated_at"] = _now()
    bridge.write_json_atomic(store_path(project), data)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


# --- 解析与校验 --------------------------------------------------------------

def dictionary() -> List[Dict[str, Any]]:
    """字段字典：给界面和导出用，按字典顺序。"""
    out: List[Dict[str, Any]] = []
    for key, meta in METRICS.items():
        item = {"metric": key}
        item.update(meta)
        item["caliber_version"] = CALIBER_VERSION
        out.append(item)
    return out


def metric_meta(metric: str) -> Dict[str, Any]:
    meta = METRICS.get(str(metric or "").strip())
    if not isinstance(meta, dict):
        if metric in UNAVAILABLE:
            raise ValueError(UNAVAILABLE[metric])
        raise ValueError(f"未知指标：{metric}")
    return meta


def parse_csv(text: str) -> Dict[str, Any]:
    """解析 CSV 文本（首个非空行为表头）。只解析，不做业务校验。"""
    if not isinstance(text, str):
        raise ValueError("CSV 必须是文本")
    raw = text.encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"CSV 超过 {MAX_BYTES // 1024 // 1024} MB 上限")
    if raw.startswith(b"\xef\xbb\xbf"):
        text = text.lstrip("\ufeff")
    lines = [line for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    if not lines:
        raise ValueError("CSV 为空")
    header = [cell.strip().lower() for cell in lines[0].split(",")]
    missing = [name for name in REQUIRED_COLUMNS if name not in header]
    if missing:
        raise ValueError("CSV 缺少列：" + "、".join(missing))
    if len(lines) - 1 > MAX_ROWS:
        raise ValueError(f"CSV 超过 {MAX_ROWS} 行上限")
    rows: List[Dict[str, str]] = []
    for index, line in enumerate(lines[1:], start=2):
        cells = line.split(",")
        if len(cells) < len(header):
            cells = cells + [""] * (len(header) - len(cells))
        row = {name: cells[header.index(name)].strip() for name in header}
        row["_line"] = str(index)
        rows.append(row)
    return {"header": header, "rows": rows}


def _number(value: str, *, field: str, unit: str) -> Optional[float]:
    text = str(value or "").strip()
    if text == "":
        return None
    try:
        number = float(text.replace("%", "").strip())
    except ValueError:
        raise ValueError(f"{field} 不是数字：{value}")
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{field} 不是有限数值：{value}")
    if unit == PERCENT and not (0 <= number <= 100):
        raise ValueError(f"{field} 超出 0–100：{value}")
    if unit == COUNT and (number < 0 or int(number) != number):
        raise ValueError(f"{field} 必须是非负整数：{value}")
    return number


def _date(value: str, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} 不能为空")
    try:
        parsed = dt.date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{field} 不是 ISO 日期：{value}")
    return parsed.isoformat()


def _zone():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(DEFAULT_TIMEZONE)
    except Exception:
        return dt.timezone(dt.timedelta(hours=8))


def _today() -> dt.date:
    """口径日期一律按字典时区取，避免同一条读数跨零点时一边 new 一边 mature。"""
    return dt.datetime.now(_zone()).date()


def _instant(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"observed_at 不是 ISO 时刻：{value}")
    if parsed.tzinfo is None:
        # 字典口径是 Asia/Shanghai；无偏移的时刻按该时区解释，不再静默当 UTC。
        parsed = parsed.replace(tzinfo=_zone())
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def key_of(row: Dict[str, Any]) -> str:
    """稳定键只看「哪一次观测」：分母是数值属性，修正分母应成为修订而不是新行。"""
    parts = [
        row.get("platform", ""), row.get("work_id", ""), str(row.get("chapter_id", "")),
        row.get("metric", ""), row.get("window_start", ""), row.get("window_end", ""),
        row.get("unit", ""), row.get("source", ""),
    ]
    return hashlib.sha256("\u0001".join(parts).encode("utf-8")).hexdigest()[:24]


def normalize_row(row: Dict[str, Any], *, platform_default: str = "fanqie") -> Dict[str, Any]:
    """把一行 CSV 归一成待写入的观测；不合格直接抛 ValueError（由调用方收进拒绝行）。"""
    metric = str(row.get("metric") or "").strip()
    meta = metric_meta(metric)
    unit = str(row.get("unit") or meta["unit"]).strip()
    if unit not in (PERCENT, COUNT):
        raise ValueError(f"unit 只能是 percent 或 count：{unit}")
    if unit != meta["unit"]:
        raise ValueError(f"{meta['label']} 的单位应为 {meta['unit']}，收到 {unit}")
    platform = str(row.get("platform") or platform_default).strip().lower()
    if not platform:
        raise ValueError("platform 不能为空")
    work_id = str(row.get("work_id") or "").strip()
    if not work_id:
        raise ValueError("work_id 不能为空")
    chapter_raw = str(row.get("chapter_id") or "").strip()
    if meta["granularity"] == "chapter":
        if not chapter_raw:
            raise ValueError("章级指标必须给 chapter_id")
        if not chapter_raw.isdigit():
            raise ValueError(f"chapter_id 必须是章号：{chapter_raw}")
        chapter_id = str(int(chapter_raw))
    else:
        if chapter_raw not in ("", "0") and not chapter_raw.isdigit():
            raise ValueError(f"{meta['label']} 是作品级指标，chapter_id 必须为空或 0，收到 {chapter_raw}")
        if chapter_raw.isdigit() and int(chapter_raw) != 0:
            raise ValueError(f"{meta['label']} 是作品级指标，不接受章号 {chapter_raw}")
        chapter_id = "0"
    window_start = _date(row.get("window_start"), field="window_start")
    window_end = _date(row.get("window_end"), field="window_end")
    if window_end < window_start:
        raise ValueError("window_end 早于 window_start")
    observed_at = _instant(row.get("observed_at"))
    if not observed_at:
        raise ValueError("observed_at 不能为空")
    value = _number(row.get("value"), field="value", unit=unit)
    if value is None:
        raise ValueError("value 为空：零要写 0，未知就不要写这一行")
    denominator = _number(row.get("denominator"), field="denominator", unit=COUNT)
    if denominator is not None and denominator <= 0:
        raise ValueError("denominator 必须大于 0；未知请留空")
    source = str(row.get("source") or "").strip()
    if not source:
        raise ValueError("source 不能为空（要能回源到导出文件或手工录入）")
    item = {
        "platform": platform,
        "work_id": work_id,
        "chapter_id": chapter_id,
        "metric": metric,
        "window_start": window_start,
        "window_end": window_end,
        "observed_at": observed_at,
        "value": value,
        "unit": unit,
        "denominator": denominator,
        "denominator_known": denominator is not None,
        "source": source,
        "caliber_version": CALIBER_VERSION,
        "observed_timezone": meta["timezone"],
        "granularity": meta["granularity"],
    }
    item["key"] = key_of(item)
    return item


def _stage(item: Dict[str, Any], now: dt.date) -> str:
    """相对成熟度：窗口结束不足 7 天的读数算「新」，不与累积数周的章直接排行。"""
    try:
        end = dt.date.fromisoformat(item["window_end"])
    except (KeyError, ValueError):
        return "unknown"
    days = (now - end).days
    if days < 0:
        return "future"
    return "new" if days < 7 else "mature"


PREVIEW_DIR = "reader_previews"
PREVIEW_TTL_SECONDS = 30 * 60


def preview_dir(project: Path) -> Path:
    return Path(project) / ".webnovel" / PREVIEW_DIR


def _store_digest(data: Dict[str, Any]) -> str:
    rows = [item for item in data.get("rows") or [] if isinstance(item, dict)]
    payload = sorted(
        f"{item.get('key')}|{item.get('value')}|{item.get('observed_at')}|"
        f"{item.get('denominator')}|{item.get('revision')}" for item in rows)
    return hashlib.sha256(("\n".join(payload) + f"\n#{len(rows)}").encode("utf-8")).hexdigest()


def _plan_path(project: Path, token: str) -> Path:
    return preview_dir(project) / f"{token}.json"


def load_plan(project: Path, token: str, *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """按 token 取回待确认计划；过期、被篡改或不存在一律要求重新预览。"""
    if not token:
        raise ValueError("提交必须带预览 token：先预览再确认")
    path = _plan_path(project, str(token))
    if not path.exists():
        raise ValueError("预览已过期或不存在：请重新预览")
    try:
        plan = bridge.read_json(path, {}) or {}
    except Exception:
        raise ValueError("预览计划损坏：请重新预览")
    if not isinstance(plan, dict) or plan.get("token") != str(token):
        raise ValueError("预览计划与 token 不匹配：请重新预览")
    created = str(plan.get("created_at") or "")
    current = now or dt.datetime.now(dt.timezone.utc)
    try:
        age = (current - dt.datetime.fromisoformat(created)).total_seconds()
    except (TypeError, ValueError):
        age = PREVIEW_TTL_SECONDS + 1
    if age > PREVIEW_TTL_SECONDS:
        raise ValueError("预览已过期：请重新预览")
    return plan


def preview(project: Path, rows: Sequence[Dict[str, Any]], *, platform_default: str = "fanqie",
            work_id: Optional[str] = None, now: Optional[dt.date] = None) -> Dict[str, Any]:
    """预览：不写任何观测，只把待确认计划暂存到 `.webnovel/reader_previews/`。"""
    data = load(project)
    existing = {str(item.get("key")): item for item in data["rows"] if isinstance(item, dict)}
    today = now or _today()
    valid: List[Dict[str, Any]] = []
    duplicates: List[Dict[str, Any]] = []
    revisions: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    mismatched: List[str] = []
    for index, raw in enumerate(rows, start=1):
        try:
            item = normalize_row(raw, platform_default=platform_default)
        except ValueError as exc:
            rejected.append({"line": str(raw.get("_line") or index), "reason": str(exc)})
            continue
        if work_id and item["work_id"] != str(work_id):
            mismatched.append(item["work_id"])
            rejected.append({"line": str(raw.get("_line") or index),
                             "reason": f"作品不匹配：本批目标是 {work_id}，行内是 {item['work_id']}"})
            continue
        item["stage"] = _stage(item, today)
        previous = existing.get(item["key"])
        if previous is None:
            valid.append(item)
            continue
        if _same_value(previous, item):
            duplicates.append({"line": str(raw.get("_line") or index), "key": item["key"],
                               "metric": item["metric"], "chapter_id": item["chapter_id"]})
        else:
            item["previous"] = {key: previous.get(key) for key in
                                ("value", "observed_at", "batch", "denominator", "denominator_known",
                                 "unit", "revision")}
            revisions.append(item)
    accepted = len(valid) + len(revisions)
    digest = _store_digest(data)
    token = hashlib.sha256(
        (digest + "\u0001" + "\u0001".join(
            str(item["key"]) + ":" + repr(item["value"]) + ":" + repr(item.get("denominator"))
            for item in valid + revisions)).encode("utf-8")).hexdigest()[:16]
    plan = {
        "schema": SCHEMA,
        "token": token,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "store_digest": digest,
        "work_id": str(work_id or ""),
        "valid": valid,
        "duplicates": duplicates,
        "revisions": revisions,
        "rejected": rejected,
        "mismatched_work": sorted(set(mismatched)),
        "counts": {"rows": len(rows), "valid": len(valid), "duplicate": len(duplicates),
                   "revision": len(revisions), "rejected": len(rejected), "accepted": accepted},
        "caliber_version": CALIBER_VERSION,
    }
    target = _plan_path(project, token)
    target.parent.mkdir(parents=True, exist_ok=True)
    bridge.write_json_atomic(target, plan)
    # 只清理最旧的计划，保留最近 30 个（不能把当前之外的都删掉）。
    existing_plans = sorted(preview_dir(project).glob("*.json"),
                            key=lambda path: path.stat().st_mtime)
    for stale in existing_plans[:-30]:
        try:
            stale.unlink()
        except OSError:
            pass
    return {
        "project": str(project),
        "work_id": str(work_id or ""),
        "valid": valid,
        "duplicates": duplicates,
        "revisions": revisions,
        "rejected": rejected,
        "mismatched_work": sorted(set(mismatched)),
        "counts": plan["counts"],
        "token": token,
        "caliber_version": CALIBER_VERSION,
    }


def _same_value(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    """同键同值才算重复：分母不同也是不同读数（平台回填最常改的就是分母）。"""
    try:
        if float(left.get("value")) != float(right.get("value")):
            return False
    except (TypeError, ValueError):
        return False
    if str(left.get("observed_at")) != str(right.get("observed_at")):
        return False
    left_den = left.get("denominator")
    right_den = right.get("denominator")
    if left_den is None or right_den is None:
        return left_den is None and right_den is None
    return float(left_den) == float(right_den)


def _snapshot(item: Dict[str, Any]) -> Dict[str, Any]:
    """修订历史存完整读数快照：回退时整条替换，避免值/分母错配。"""
    keys = ("metric", "platform", "work_id", "chapter_id", "window_start", "window_end",
            "observed_at", "value", "unit", "denominator", "denominator_known", "source",
            "caliber_version", "observed_timezone", "granularity", "stage", "batch", "revision")
    return {key: item.get(key) for key in keys if key in item}


def commit(project: Path, preview_result: Optional[Dict[str, Any]] = None, *, actor: str = "author",
           filename: str = "", token: Optional[str] = None,
           allow_partial: bool = False) -> Dict[str, Any]:
    """事务提交：按 token 取回计划、校验存储摘要，要么整批写入，要么一行不写。"""
    plan = load_plan(project, str(token or ""))
    data = load(project)
    if str(plan.get("store_digest")) != _store_digest(data):
        raise ValueError("预览已过期：数据在这期间变了，请重新预览")
    rejected = plan.get("rejected") or []
    if rejected and not allow_partial:
        raise ValueError(f"存在 {len(rejected)} 行拒绝：整批未写入；修正后重新预览，或显式允许部分写入")
    existing = {str(item.get("key")): item for item in data["rows"] if isinstance(item, dict)}
    batch_id = _batch_id(project, data)
    added: List[Dict[str, Any]] = []
    revised: List[Dict[str, Any]] = []
    for item in plan.get("valid") or []:
        copied = dict(item)
        copied["batch"] = batch_id
        copied["revision"] = 1
        copied["history"] = []
        if copied["key"] in existing:
            continue
        added.append(copied)
    for item in plan.get("revisions") or []:
        copied = dict(item)
        previous = existing.get(copied["key"])
        if previous is None:
            copied["batch"] = batch_id
            copied["revision"] = 1
            copied["history"] = []
            added.append(copied)
            continue
        history = list(previous.get("history") or [])
        history.append(_snapshot(previous))
        merged = dict(copied)
        merged["batch"] = batch_id
        merged["revision"] = int(previous.get("revision", 1)) + 1
        merged["history"] = history[-20:]
        revised.append(merged)
    if not added and not revised:
        _discard_plan(project, plan["token"])
        return {"status": "noop", "batch": batch_id, "added": 0, "revised": 0,
                "duplicate": len(plan.get("duplicates") or []), "counts": plan.get("counts", {})}
    replaced = {item["key"]: item for item in revised}
    rows = [replaced.get(str(item.get("key")), item) for item in data["rows"] if isinstance(item, dict)]
    rows.extend(added)
    batches = list(data.get("batches") or [])
    batches.append({
        "id": batch_id,
        "at": _now(),
        "actor": str(actor or "author"),
        "filename": str(filename or ""),
        "work_id": str(plan.get("work_id") or ""),
        "added": len(added),
        "revised": len(revised),
        "duplicate": len(plan.get("duplicates") or []),
        "rejected": [row.get("reason") for row in rejected][:50],
        "partial": bool(rejected),
        "caliber_version": CALIBER_VERSION,
    })
    data["rows"] = rows
    data["batches"] = batches[-200:]
    save(project, data)
    _discard_plan(project, plan["token"])
    return {"status": "committed", "batch": batch_id, "added": len(added), "revised": len(revised),
            "duplicate": len(plan.get("duplicates") or []), "partial": bool(rejected),
            "counts": plan.get("counts", {})}


def _discard_plan(project: Path, token: str) -> None:
    try:
        _plan_path(project, token).unlink()
    except OSError:
        pass


def _batch_id(project: Path, data: Dict[str, Any]) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    seed = f"{project}|{stamp}|{len(data.get('batches') or [])}"
    return stamp + "-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:6]


# --- 查询与回源 --------------------------------------------------------------

def rows_for(project: Path, *, metric: str = "", chapter_id: Any = None, work_id: str = "") -> List[Dict[str, Any]]:
    data = load(project)
    out = []
    for item in data["rows"]:
        if not isinstance(item, dict):
            continue
        if metric and item.get("metric") != metric:
            continue
        if chapter_id is not None and str(item.get("chapter_id")) != str(chapter_id):
            continue
        if work_id and item.get("work_id") != work_id:
            continue
        out.append(item)
    out.sort(key=lambda item: (str(item.get("window_start")), str(item.get("observed_at")), str(item.get("chapter_id"))))
    return out


def trace(project: Path, key: str) -> Dict[str, Any]:
    """回源：一行观测 → 批次、文件、口径版本、窗口、修订历史。"""
    data = load(project)
    for item in data["rows"]:
        if isinstance(item, dict) and item.get("key") == key:
            batch = next((b for b in data["batches"] if b.get("id") == item.get("batch")), {})
            return {"row": item, "batch": batch, "caliber_version": item.get("caliber_version")}
    raise ValueError(f"找不到该观测：{key}")


def series(project: Path, *, metric: str, work_id: str = "", limit: int = 60) -> Dict[str, Any]:
    """给图表用：按章序返回点，附带阶段与限制，不在本函数里下结论。"""
    meta = metric_meta(metric)
    points = []
    for item in rows_for(project, metric=metric, work_id=work_id)[-limit:]:
        points.append({
            "chapter_id": item.get("chapter_id"),
            "value": item.get("value"),
            "unit": item.get("unit"),
            "window": [item.get("window_start"), item.get("window_end")],
            "observed_at": item.get("observed_at"),
            "denominator": item.get("denominator"),
            "denominator_known": bool(item.get("denominator_known")),
            "stage": _stage(item, dt.date.today()),
            "source": item.get("source"),
            "batch": item.get("batch"),
            "key": item.get("key"),
        })
    limitations = []
    if any(not point["denominator_known"] for point in points):
        limitations.append("有读数的分母未知；不要把它当零，也不要跨分母比较。")
    if any(point["stage"] == "new" for point in points):
        limitations.append("含发布不足 7 天的章；不要与累积数周的章直接排行。")
    if len(points) < 5:
        limitations.append(f"样本只有 {len(points)} 个点，不足以支持趋势结论。")
    return {"metric": metric, "label": meta["label"], "unit": meta["unit"],
            "granularity": meta["granularity"], "points": points, "limitations": limitations}


def batches(project: Path, limit: int = 20) -> List[Dict[str, Any]]:
    return list(load(project).get("batches") or [])[-limit:]


# --- 评论：脱敏、去重、聚类 ---------------------------------------------------

def sanitize_comment(text: str, *, limit: int = MAX_COMMENT) -> Dict[str, Any]:
    """评论只是数据：去标签、压空白、截断，并标记是否含指令话术（不执行）。"""
    raw = str(text or "")
    cleaned = _TAG.sub(" ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    flagged = bool(_INSTRUCTION.search(cleaned))
    # 指纹用原文算：否则所有被标记的评论会撞成同一条，去重与计数都失真。
    digest = hashlib.sha256(re.sub(r"\s+", " ", raw).strip().encode("utf-8")).hexdigest()[:16]
    if flagged:
        # 疑似控制指令的整条评论一律丢弃原文，只留标记：既不执行，也不把要求转述进提示。
        cleaned = "[疑似指令已忽略]"
    truncated = len(cleaned) > limit
    cleaned = cleaned[:limit]
    return {"text": cleaned, "truncated": truncated, "flagged": flagged, "hash": digest}


def add_comments(project: Path, rows: Iterable[Dict[str, Any]], *, batch: str = "",
                 chapter_id: Any = None) -> Dict[str, Any]:
    """导入评论：按脱敏前原文哈希在同章内去重，不覆盖已有；未指定批次时自动生成。"""
    items = list(rows or [])
    data = load(project)
    batch_id = str(batch or "").strip() or f"comments-{_now()[:19].replace(':', '').replace('-', '')}"
    known = {(str(item.get("chapter_id")), item.get("hash")) for item in data["comments"] if isinstance(item, dict)}
    added = 0
    flagged = 0
    for row in items:
        result = sanitize_comment(row.get("text") if isinstance(row, dict) else str(row))
        if not result["text"]:
            continue
        chapter = row.get("chapter_id") if isinstance(row, dict) else None
        if chapter in (None, ""):
            chapter = chapter_id
        chapter = str(chapter if chapter not in (None, "") else "0")
        if (chapter, result["hash"]) in known:
            continue
        known.add((chapter, result["hash"]))
        data["comments"].append({"chapter_id": chapter, "text": result["text"], "hash": result["hash"],
                                 "truncated": result["truncated"], "flagged": result["flagged"],
                                 "batch": batch_id, "at": _now()})
        added += 1
        flagged += 1 if result["flagged"] else 0
    if added:
        data["comments"] = data["comments"][-5000:]
        save(project, data)
    return {"added": added, "flagged": flagged, "batch": batch_id, "skipped": len(items) - added}


def comments_for(project: Path, chapter_id: Any) -> List[Dict[str, Any]]:
    return [item for item in load(project)["comments"]
            if isinstance(item, dict) and str(item.get("chapter_id")) == str(chapter_id)]


TOPICS = {
    "节奏": ("拖", "水", "节奏", "太慢", "快点", "卡"),
    "人物": ("人设", "性格", "主角", "配角", "讨厌", "喜欢"),
    "情节": ("剧情", "转折", "伏笔", "结局", "逻辑"),
    "更新": ("更新", "加更", "催更", "断更"),
}


def cluster_comments(project: Path, chapter_id: Any, *, limit: int = 5) -> List[Dict[str, Any]]:
    """按关键词聚主题，给代表性短摘要；被标记的评论不进样本，也不推断情绪强度。"""
    items = [item for item in comments_for(project, chapter_id) if not item.get("flagged")]
    buckets: Dict[str, List[str]] = {}
    for item in items:
        text = str(item.get("text") or "")
        for topic, words in TOPICS.items():
            if any(word in text for word in words):
                buckets.setdefault(topic, []).append(text)
                break
    out = []
    for topic, texts in sorted(buckets.items(), key=lambda pair: -len(pair[1]))[:limit]:
        out.append({"topic": topic, "count": len(texts), "samples": texts[:2]})
    if items and not out:
        sample = str(items[0].get("text") or "")[:MAX_COMMENT]
        out.append({"topic": "其他", "count": len(items), "samples": [sample], "framed_as": "uncategorized"})
    return out


def remove_batch(project: Path, batch: str) -> Dict[str, Any]:
    """作者撤销一次导入：删掉该批次新增的行，修订行整条回退到上一版快照。"""
    identifier = str(batch or "").strip()
    if not identifier:
        raise ValueError("撤销批次必须指定 batch id")
    data = load(project)
    kept: List[Dict[str, Any]] = []
    removed = 0
    restored = 0
    for item in data["rows"]:
        if not isinstance(item, dict):
            continue
        if item.get("batch") != identifier:
            kept.append(item)
            continue
        removed += 1
        history = list(item.get("history") or [])
        if history:
            previous = history.pop()
            merged = dict(previous)
            merged["key"] = item.get("key")
            merged["metric"] = item.get("metric")
            merged["platform"] = item.get("platform")
            merged["work_id"] = item.get("work_id")
            merged["chapter_id"] = item.get("chapter_id")
            merged["history"] = history
            kept.append(merged)
            restored += 1
    data["rows"] = kept
    data["comments"] = [item for item in data["comments"] if item.get("batch") != identifier]
    data["batches"] = [item for item in data["batches"] if item.get("id") != identifier]
    save(project, data)
    return {"removed": removed, "restored": restored, "batch": identifier}
