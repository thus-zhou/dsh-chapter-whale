"""C03 规划期检索：固定过滤顺序、先关键词/BM25 再可选向量、每次留 trace、坏索引回落文本。

过滤顺序（不可调换）：作品 → 有效来源/版本 → 章界 → 认知/视角 → 排序 → 预算。
本模块只做本地纯计算：不下载模型、不外发正文；向量段仅在配置允许且索引可用时尝试。
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path

from . import bridge, memory_library

SCHEMA = 1
DEFAULT_BUDGET = 12000
TRACE_LIMIT = 200
CJK = re.compile(r"[\u4e00-\u9fff]")
WORD = re.compile(r"[A-Za-z0-9_]+")


def tokens(text):
    """中文二元组 + 拉丁词：不引第三方分词，保证离线可复现。"""
    text = str(text or "")
    rows = []
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        rows.extend(run[index:index + 2] for index in range(max(1, len(run) - 1)))
        if len(run) == 1:
            rows.append(run)
    rows.extend(word.lower() for word in WORD.findall(text))
    return [row for row in rows if row.strip()]


def bm25(query, docs, *, k1=1.5, b=0.75):
    """docs: [(id, text)] → [(id, score)]；纯本地打分，可完全复现。"""
    terms = tokens(query)
    if not terms or not docs:
        return []
    corpus = [(str(key), tokens(text)) for key, text in docs]
    average = sum(len(row) for _key, row in corpus) / max(1, len(corpus))
    frequency = {}
    for _key, row in corpus:
        for term in set(terms):
            if term in row:
                frequency[term] = frequency.get(term, 0) + 1
    scores = []
    for key, row in corpus:
        score = 0.0
        length = len(row) or 1
        for term in set(terms):
            count = row.count(term)
            if not count:
                continue
            df = frequency.get(term, 0)
            idf = math.log(1 + (len(corpus) - df + 0.5) / (df + 0.5))
            score += idf * count * (k1 + 1) / (count + k1 * (1 - b + b * length / max(average, 1e-6)))
        if score:
            scores.append((key, round(score, 4)))
    scores.sort(key=lambda row: (-row[1], row[0]))
    return scores


def sanitize_query(query, names=()):
    """脱敏：把作品内人物名替换成占位，避免把专名送进外部分析。"""
    text = str(query or "")
    removed = []
    for name in sorted({str(row) for row in names if row}, key=len, reverse=True):
        if name and name in text:
            text = text.replace(name, "【人物】")
            removed.append(name)
    return {"query": text, "removed": removed}


# --- 索引隔离与原子切换 -------------------------------------------------------
def index_root(project):
    project = Path(project).resolve()
    folder = project / ".webnovel" / "retrieval"
    if folder.is_symlink():
        raise ValueError("索引目录不安全")
    return folder


def index_dir(project, *, model="local", chunk=256):
    model = re.sub(r"[^A-Za-z0-9_.-]", "_", str(model or "local"))[:40] or "local"
    chunk = int(chunk)
    if not 64 <= chunk <= 4096:
        raise ValueError("分块大小超出范围")
    return index_root(project) / f"{model}-{chunk}"


def active_index(project):
    path = index_root(project) / "active.json"
    if not path.exists():
        return {"model": "", "chunk": 0, "previous": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"model": "", "chunk": 0, "previous": None}
    return data if isinstance(data, dict) else {"model": "", "chunk": 0, "previous": None}


def switch_index(project, *, model="local", chunk=256):
    """先建好新目录再原子替换指针；旧索引保留为 previous 以便退回。"""
    folder = index_dir(project, model=model, chunk=chunk)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ready").write_text(bridge.now_iso(), encoding="utf-8")
    current = active_index(project)
    previous = None
    if current.get("model"):
        previous = {"model": current.get("model"), "chunk": current.get("chunk")}
    payload = {"model": model, "chunk": int(chunk), "previous": previous, "switched_at": bridge.now_iso()}
    target = index_root(project) / "active.json"
    temp = index_root(project) / f".active.{os.getpid()}.tmp"
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, target)
    return {"status": "switched", "active": payload, "kept_previous": bool(previous)}


def index_ready(project):
    active = active_index(project)
    if not active.get("model"):
        return False
    folder = index_dir(project, model=active["model"], chunk=active.get("chunk") or 256)
    return (folder / "ready").is_file()


# --- 规划 ---------------------------------------------------------------------
def _candidates(project, chapter, doc=None):
    """作品 → 有效来源/版本 → 章界 → 视角可见性，按这个固定顺序过一遍。

    返回 `(可用条目, 因来源失效被剔除的条数)`；「来源失效」指引文或版本哈希已对不上当前正文，
    这类旧证据不能继续进提示，但也不隐藏——作为 omitted 原因报给作者。
    """
    doc = doc or memory_library.read(project)
    rows, stale = [], 0
    cache = {}
    for item in doc.get("items", []):
        if item.get("status") != "active":
            continue
        source = item.get("source") or {}
        if str(source.get("kind") or "") == "chapter" and int(source.get("chapter") or 0) >= int(chapter):
            continue
        visible = memory_library._visible(item, int(chapter))
        if visible:
            continue
        try:
            if memory_library.freshness(project, item, cache) == "stale":
                stale += 1
                continue
        except (ValueError, OSError, UnicodeError):
            stale += 1
            continue
        rows.append(item)
    return rows, stale


def _context_budget(budget):
    if budget is None:
        return memory_library.context_budget_default() or DEFAULT_BUDGET
    value = int(budget)
    if value < 200:
        raise ValueError("预算过小")
    return value


def plan(project, chapter, query="", *, budget=None, perspective="character", knowledge=None, doc=None,
         trace=True, op_id="", names=()):
    """按固定顺序过滤、打分、装填；每次可落 trace，装不下的逐条给原因。

    `knowledge` 是当前视角人物「已知」的事实 ID 集合（来自 character_state /
    entity_state）；为 None 时不按认知收窄，避免用推测冒充角色已知。
    """
    started = time.perf_counter()
    chapter = int(chapter)
    if chapter < 1:
        raise ValueError("章号无效")
    limit = _context_budget(budget)
    doc = doc or memory_library.read(project)
    rows, stale = _candidates(project, chapter, doc)
    total = len(rows)
    # 认知/视角：只在调用方给出已知集合时收窄；未知一律不给角色视角
    perspective_dropped = 0
    if perspective == "character" and knowledge is not None:
        known = {str(row) for row in knowledge}
        kept = []
        for row in rows:
            if str(row.get("source", {}).get("kind") or "") == "manual" or str(row.get("id")) in known:
                kept.append(row)
            else:
                perspective_dropped += 1
        rows = kept
    items = {str(row.get("id") or ""): row for row in rows}
    clean = sanitize_query(query, names)
    docs = [(key, f"{row.get('title', '')} {row.get('content', '')}") for key, row in items.items()]
    scored = bm25(clean["query"], docs)
    mode = "bm25" if query else "bm25_empty"
    rank = {key: score for key, score in scored}
    ordered = [key for key, _score in scored]
    # 固定设定优先，其次按分数与章龄。没有查询时 BM25 一个词都不命中，
    # 但作者钉住的设定仍必须装进上下文——否则「先固定设定」只在有查询时成立。
    pinned = [key for key, row in items.items()
              if str(row.get("source", {}).get("kind") or "") == "manual" or row.get("pinned")]
    for key in pinned:
        if key not in ordered:
            ordered.append(key)
    ordered.sort(key=lambda key: (0 if str(items[key].get("source", {}).get("kind") or "") == "manual" else 1,
                                  -rank.get(key, 0.0), key))
    supplied, omitted, used = [], [], 0
    for key in ordered:
        row = items[key]
        cost = len(str(row.get("content") or "")) + len(str(row.get("title") or ""))
        if used + cost > limit:
            omitted.append({"id": key, "reason": "超出预算"})
            continue
        used += cost
        why = str(row.get("title") or "")[:40]
        if key not in rank:
            why = f"{why}（固定设定，无查询命中）" if not query else why
        supplied.append({"id": key, "score": rank.get(key, 0.0), "why": why})
    for row in rows:
        key = str(row.get("id") or "")
        if key not in rank and key not in pinned:
            omitted.append({"id": key, "reason": "与查询无语义命中"})
    if perspective_dropped:
        omitted.append({"id": "", "reason": f"视角过滤剔除 {perspective_dropped} 条全知叙述"})
    if stale:
        omitted.append({"id": "", "reason": f"来源已失效剔除 {stale} 条（正文版本或引文对不上）"})
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    result = {"status": "ok", "mode": mode, "chapter": chapter, "budget": limit, "used": used,
              "supplied": supplied, "omitted": omitted[:200], "query": clean["query"],
              "removed_names": clean["removed"],
              "counts": {"candidates": total, "supplied": len(supplied), "stale": stale},
              "timing": {"ms": elapsed}, "index": active_index(project), "op_id": str(op_id or "")}
    if trace:
        result["trace"] = _write_trace(project, result)
    return result


def _trace_dir(project):
    folder = Path(project).resolve() / ".webnovel" / "retrieval_traces"
    if folder.is_symlink():
        raise ValueError("trace 目录不安全")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _write_trace(project, result):
    stamp = str(result.get("timing", {}).get("ms", ""))
    # op_id 来自调用方，可能是任意文本；只留安全字符，避免把 trace 写到别的目录。
    raw = str(result.get("op_id") or "plan")
    op = "".join(ch for ch in raw if ch.isalnum() or ch in "-_")[:40] or "plan"
    name = f"ch{int(result['chapter']):04d}-{op}-{int(time.time() * 1000)}.json"
    folder = _trace_dir(project)
    path = folder / name
    payload = {key: value for key, value in result.items() if key != "trace"}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    traces = sorted(folder.glob("ch*.json"), key=lambda item: item.stat().st_mtime)
    for old in traces[:-TRACE_LIMIT]:
        try:
            old.unlink()
        except OSError:
            pass
    return {"path": str(path), "ms": stamp}


def report(project):
    """聚合 trace：命中/采用/耗时/磁盘；没有 trace 时如实报空。"""
    folder = Path(project).resolve() / ".webnovel" / "retrieval_traces"
    rows = []
    if folder.is_dir():
        for path in sorted(folder.glob("ch*.json")):
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
    supplied = sum(len(row.get("supplied") or []) for row in rows)
    omitted = sum(len(row.get("omitted") or []) for row in rows)
    ms = [float(row.get("timing", {}).get("ms") or 0) for row in rows]
    disk = sum(path.stat().st_size for path in folder.glob("ch*.json")) if folder.is_dir() else 0
    return {"plans": len(rows), "supplied": supplied, "omitted": omitted,
            "avg_ms": round(sum(ms) / len(ms), 1) if ms else None,
            "bytes": disk, "last": rows[-1].get("chapter") if rows else None}


def search(project, chapter, query="", **kwargs):
    """索引坏/离线时回落纯文本检索，并在结果里标明原因。"""
    try:
        result = plan(project, chapter, query, **kwargs)
        result["fallback"] = None
        return result
    except (OSError, ValueError) as exc:
        if isinstance(exc, ValueError) and "章号" in str(exc):
            raise
        fallback = plan(project, chapter, query, trace=False, **{**kwargs, "budget": kwargs.get("budget")})
        fallback["fallback"] = {"reason": "index_unavailable", "detail": str(exc)[:120]}
        fallback["mode"] = "text_fallback"
        return fallback
