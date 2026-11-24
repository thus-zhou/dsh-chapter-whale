"""证据使用台账：哪一章拿到过哪条证据、正文里能否定位、作者是否确认。不调用模型。

设计约束（03_v0.7.0 C02）：
- 组装上下文时记账，生成后定位；「模型说自己用了」只算候选，不等于采纳；
- 反向索引（来源章 → 事实 → 使用章）可从日志重建，不依赖内存缓存；
- 旧章可以做无模型局部回填，但必须标注覆盖范围，不能宣称全库精确；
- 已定位靠正文引文锚点，不沿用旧字符偏移。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import bridge, memory_library, writer_runner as writer

SCHEMA = 1
MAX_LINES = 20000
STATES = ("supplied", "candidate", "located", "confirmed", "missing")


def _path(project, name="evidence_log.jsonl"):
    project = Path(project).resolve()
    folder = project / ".webnovel"
    path = folder / name
    if folder.is_symlink() or path.is_symlink() or project not in path.resolve().parents:
        raise ValueError("证据日志目录不安全")
    return path


def _append(project, row):
    path = _path(project)
    lines = 0
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            lines = sum(1 for _ in handle)
    if lines >= MAX_LINES:
        raise ValueError("证据日志已达上限，请先归档")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_log(project, chapter=None):
    path = _path(project)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or row.get("schema") != SCHEMA:
                continue
            if chapter is not None and int(row.get("chapter") or 0) != int(chapter):
                continue
            rows.append(row)
    return rows


def log_supply(project, *, chapter, stage, version_sha, evidence_ids, omitted=(), op_id=""):
    """记一次上下文组装：送进提示的证据 ID 与未选原因。同一章+阶段+版本只记一次。"""
    if type(chapter) is not int or not 1 <= chapter <= 100000:
        raise ValueError("目标章无效")
    if not str(stage or "").strip():
        raise ValueError("阶段不能为空")
    ids = [str(item) for item in (evidence_ids or [])][:200]
    reasons = []
    for row in list(omitted or [])[:200]:
        if isinstance(row, dict):
            reasons.append({"id": str(row.get("id") or ""), "reason": str(row.get("reason") or "")[:80]})
        else:
            reasons.append({"id": str(row), "reason": ""})
    key = (int(chapter), str(stage), str(version_sha or ""))
    for old in read_log(project, chapter):
        if (int(old.get("chapter") or 0), str(old.get("stage") or ""), str(old.get("version_sha") or "")) == key:
            return {"status": "reused", "entry": old}
    row = {"schema": SCHEMA, "at": bridge.now_iso(), "chapter": int(chapter), "stage": str(stage),
           "version_sha": str(version_sha or ""), "supplied": ids, "omitted": reasons,
           "op_id": str(op_id or "")}
    _append(project, row)
    return {"status": "logged", "entry": row}


def record_use(project, *, chapter, fact_id, state="candidate", quote="", note="", version_sha="", actor="model"):
    """记录一条证据在本章的实际使用状态；只有作者能升到 confirmed。"""
    if state not in STATES:
        raise ValueError("使用状态无效")
    if state == "confirmed" and actor != "author":
        raise ValueError("模型自述不等于确认采用；确认必须由作者操作")
    row = {"schema": SCHEMA, "at": bridge.now_iso(), "kind": "use", "chapter": int(chapter),
           "fact_id": str(fact_id or ""), "state": state, "quote": str(quote or "")[:800],
           "note": str(note or "")[:200], "version_sha": str(version_sha or ""), "actor": str(actor or "")}
    _append(project, row)
    return {"status": "recorded", "entry": row}


def _paragraphs(text):
    return [row.strip() for row in re.split(r"\n\s*\n", str(text or "")) if row.strip()]


def _similar(quote, body):
    """语义相近只给候选：字符二元组重合度，不做语义模型推理。"""
    quote = re.sub(r"\s+", "", quote or "")
    if len(quote) < 8:
        return 0.0
    grams = {quote[index:index + 2] for index in range(len(quote) - 1)}
    best = 0.0
    for paragraph in _paragraphs(body):
        flat = re.sub(r"\s+", "", paragraph)
        if not flat:
            continue
        row = {flat[index:index + 2] for index in range(len(flat) - 1)}
        if not row:
            continue
        best = max(best, len(grams & row) / len(grams))
    return round(best, 3)


def locate_use(project, *, chapter, version_sha, quote, body=None):
    """在当前正文定位引文：逐字命中记 located；否则给候选或缺失，绝不沿用旧偏移。"""
    current = None
    if body is None:
        body, current = memory_library._chapter(project, int(chapter))
    body = str(body or "")
    quote = str(quote or "").strip()
    if not quote:
        raise ValueError("定位必须带引文")
    wanted = str(version_sha or "")
    # 版本对不上就不是「可定位」：旧正文的字符偏移搬到新正文上会指到别的句子。
    if current is not None and wanted and wanted != current:
        return {"status": "stale_version", "chapter": int(chapter), "quote": quote,
                "version_sha": wanted, "current_sha": current,
                "note": "正文已改版，需要按当前版本重新定位"}
    if quote in body:
        index = next((pos for pos, row in enumerate(_paragraphs(body)) if quote in row), -1)
        if index < 0:
            return {"status": "ambiguous", "chapter": int(chapter), "quote": quote,
                    "version_sha": wanted, "note": "引文跨段或落在段界上，只算候选"}
        return {"status": "located", "chapter": int(chapter), "paragraph": index, "quote": quote,
                "version_sha": wanted}
    score = _similar(quote, body)
    if score >= 0.25:
        return {"status": "candidate", "chapter": int(chapter), "similarity": score, "quote": quote,
                "note": "语义相近只算可能相关，需作者确认"}
    return {"status": "missing", "chapter": int(chapter), "similarity": score, "quote": quote}


def reverse_index(project, chapter_limit=None):
    """来源章 → 事实 → 使用章；完全从日志折叠，可从零重建。"""
    facts = {}
    for item in memory_library.read(project).get("items", []):
        source = item.get("source") or {}
        facts[str(item.get("id") or "")] = {"source_chapter": int(source.get("chapter") or 0),
                                            "title": item.get("title", ""), "category": item.get("category", "")}
    index = {}
    for row in read_log(project):
        if row.get("kind") != "use":
            continue
        use_chapter = int(row.get("chapter") or 0)
        if chapter_limit and use_chapter > int(chapter_limit):
            continue
        fact = facts.get(str(row.get("fact_id") or ""))
        if not fact or not fact["source_chapter"]:
            continue
        source = fact["source_chapter"]
        bucket = index.setdefault(str(source), {})
        entry = bucket.setdefault(str(row["fact_id"]), {"title": fact["title"], "uses": []})
        state = str(row.get("state") or "")
        if use_chapter not in [item["chapter"] for item in entry["uses"]]:
            entry["uses"].append({"chapter": use_chapter, "state": state})
        elif state in ("located", "confirmed"):
            for item in entry["uses"]:
                if item["chapter"] == use_chapter and item["state"] not in ("located", "confirmed"):
                    item["state"] = state
    return index


def supplies(project, chapter=None):
    rows = [row for row in read_log(project, chapter) if row.get("kind") != "use"]
    return {"count": len(rows), "entries": rows[-50:]}


def coverage(project):
    """覆盖范围：哪些章有组装记录（exact），哪些只有回填（backfilled）。"""
    rows = [row for row in read_log(project) if row.get("kind") != "use"]
    exact = sorted({int(row.get("chapter") or 0) for row in rows if not row.get("backfilled")})
    backfilled = sorted({int(row.get("chapter") or 0) for row in rows if row.get("backfilled")})
    top = max(exact + backfilled) if (exact or backfilled) else 0
    return {"exact": exact, "backfilled": backfilled, "range": f"<=ch{top}" if top else "",
            "note": "回填章节只有摘要级证据；未记录的章节不宣称精确。"}


def metrics(project, fixture=None):
    """精确率/召回率只在有标注夹具时给；没有夹具只报计数。

    `located` 只表示「正文里找到了这段引文」，不等于作者确认采用；因此
    `confirmed` 只统计作者确认过的使用，`located` 单列，避免把机器定位说成已确认。
    """
    index = reverse_index(project)
    uses = [row for row in read_log(project) if row.get("kind") == "use"]
    confirmed = [row for row in uses if row.get("state") == "confirmed"]
    located = [row for row in uses if row.get("state") == "located"]
    report = {"uses": len(uses), "confirmed": len(confirmed), "located_only": len(located),
              "sources": len(index), "samples": 0, "precision": None, "recall": None,
              "precision_scope": "", "missed": []}
    if not fixture:
        return report
    dependencies = fixture.get("dependencies") or []
    distractors = fixture.get("distractors") or []
    expected = {(int(row["source_chapter"]), int(chapter)) for row in dependencies
                for chapter in row.get("use_chapters") or []}
    found = {(int(source), int(entry["chapter"])) for source, bucket in index.items()
             for entry in bucket.values() for entry in entry["uses"] if entry["state"] in ("located", "confirmed")}
    # 精确率只在该夹具声明的依赖上算：没被标注的「使用」既不算对也不算错。
    judged = expected & found
    wrong = {(int(row["source_chapter"]), int(row["chapter"])) for row in distractors} & judged
    report.update(samples=len(expected),
                  precision=round((len(judged) - len(wrong)) / len(judged), 3) if judged else None,
                  precision_scope="仅标注依赖",
                  recall=round(len(judged) / len(expected), 3) if expected else None,
                  found_total=len(found),
                  missed=sorted(f"{source}->{chapter}" for source, chapter in expected - found),
                  false_positive=sorted(f"{source}->{chapter}" for source, chapter in wrong),
                  distractor_count=len(distractors))
    return report
