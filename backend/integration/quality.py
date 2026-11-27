"""双轨质量体检（v0.9.5 四期）。

A 轨是纯本地确定性指标（随时可跑、零模型费用）；B 轨是六维审稿融合，
默认最多两次自动审稿，作者手动触发不受该上限约束。两轨数据都落
``quality_reviews``，仪表盘只读最新一条，不覆盖历史。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from integration import chapter_versions as versions
from integration import workbench_db as wb

DIMENSIONS = ("plot", "character", "prose", "continuity", "pacing", "commercial")
DIMENSION_LABELS = {
    "plot": "情节推进", "character": "人物塑造", "prose": "文笔表达",
    "continuity": "连续性", "pacing": "节奏", "commercial": "商业性",
}
WEIGHTS = {"plot": 0.25, "character": 0.20, "prose": 0.20,
           "continuity": 0.15, "pacing": 0.10, "commercial": 0.10}
MAX_AUTO_REVIEWS = 2
THRESHOLD = 60.0


class QualityError(RuntimeError):
    def __init__(self, code: str, *, status: int = 400, detail: Optional[Dict] = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail or {}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _chapter_text(project, chapter: int) -> str:
    path = versions.chapter_path(project, int(chapter))
    if path is None:
        raise QualityError("chapter_missing", status=404)
    return path.read_bytes().decode("utf-8", errors="replace").lstrip("\ufeff")


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def local_scores(text: str) -> Dict[str, float]:
    """A 轨：确定性的六维粗估，不调用模型。"""
    chars = len(text)
    paragraphs = [line for line in text.split("\n") if line.strip()]
    dialogue = sum(1 for line in paragraphs if re.search(r"[“”\"「」]", line))
    unique = len(set(text))
    repeated = 0
    for line in paragraphs:
        if len(line) > 8 and text.count(line) > 3:
            repeated += 1
    length_score = _clamp(50 + min(40, chars / 60))
    prose = _clamp(52 + min(28, unique / 25) - repeated * 5)
    character = _clamp(48 + min(30, dialogue * 2.5))
    plot = _clamp(45 + min(35, len(paragraphs) * 0.8))
    continuity = _clamp(70 - repeated * 6)
    pacing = _clamp(88 - abs(len(paragraphs) - 18) * 1.6)
    commercial = _clamp(50 + min(25, dialogue * 2) + (8 if chars > 1200 else 0))
    return {"plot": round(plot, 1), "character": round(character, 1), "prose": round(prose, 1),
            "continuity": round(continuity, 1), "pacing": round(pacing, 1),
            "commercial": round(commercial, 1)}


def fuse(judgments: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """六维加权融合；缺维度或越界直接拒绝，避免“平均出一个假高分”。"""
    rows = list(judgments)
    if not rows:
        raise QualityError("review_required")
    totals = {dim: [] for dim in DIMENSIONS}
    for row in rows:
        scores = row.get("scores") if isinstance(row, dict) else None
        if not isinstance(scores, dict):
            raise QualityError("invalid_scores")
        for dim in DIMENSIONS:
            if dim not in scores:
                raise QualityError("missing_dimension", detail={"dimension": dim})
            value = scores[dim]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise QualityError("invalid_score", detail={"dimension": dim})
            if not 0 <= float(value) <= 100:
                raise QualityError("score_out_of_range", detail={"dimension": dim})
            totals[dim].append(float(value))
    average = {dim: round(sum(values) / len(values), 2) for dim, values in totals.items()}
    total = round(sum(average[dim] * WEIGHTS[dim] for dim in DIMENSIONS), 2)
    verdict = "pass" if total >= 75 else ("revise" if total >= THRESHOLD else "block")
    return {"scores": average, "total": total, "verdict": verdict,
            "weights": dict(WEIGHTS), "reviewers": len(rows)}


def _auto_count(project, chapter: int, version_id: str) -> int:
    wb.initialize(project)
    with wb.connect(project) as db:
        row = db.execute("SELECT COUNT(*) FROM quality_reviews WHERE chapter_id=? AND "
                         "reviewer NOT IN ('author','A-local') AND (version_id=? OR ?='')",
                         (int(chapter), version_id, version_id)).fetchone()
    return int(row[0] if row else 0)


def review(project, chapter: int, *, judgments: Optional[Iterable[Dict[str, Any]]] = None,
           reviewer: str = "auto", force: bool = False) -> Dict[str, Any]:
    chapter = int(chapter)
    if reviewer not in {"auto", "author"}:
        raise QualityError("invalid_reviewer")
    judgment_list = list(judgments) if judgments is not None else None
    if judgment_list is not None and len(judgment_list) > 8:
        raise QualityError("too_many_reviewers")
    text = _chapter_text(project, chapter)
    meta = versions.current_version(project, chapter) or {}
    version_id = str(meta.get("version_id") or "")
    rows = judgment_list if judgment_list is not None else [
        {"scores": local_scores(text), "reviewer": "A-local"},
    ]
    fused = fuse(rows)
    wb.initialize(project)
    stored_reviewer = reviewer if judgment_list is not None else "A-local"
    with wb.write_tx(project) as db:
        if judgment_list is not None and reviewer != "author" and not force:
            row = db.execute("SELECT COUNT(*) FROM quality_reviews WHERE chapter_id=? AND "
                             "reviewer NOT IN ('author','A-local') AND (version_id=? OR ?='')",
                             (chapter, version_id, version_id)).fetchone()
            if int(row[0] if row else 0) >= MAX_AUTO_REVIEWS:
                raise QualityError("auto_review_limit", status=409,
                                   detail={"max_auto_reviews": MAX_AUTO_REVIEWS})
        db.execute("INSERT INTO quality_reviews(chapter_id, chapter_uid, version_id, reviewer, "
                   "scores_json, total, verdict, created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (chapter, wb.chapter_uid(project, chapter), version_id, stored_reviewer,
                    json.dumps(fused["scores"], ensure_ascii=False), fused["total"],
                    fused["verdict"], _now()))
    return {"status": "reviewed", "chapter_id": chapter, "version_id": version_id,
            **fused, "track": "A" if reviewer == "auto" else "B"}


def history(project, chapter: int) -> List[Dict[str, Any]]:
    wb.initialize(project)
    with wb.connect(project) as db:
        rows = db.execute("SELECT * FROM quality_reviews WHERE chapter_id=? ORDER BY id DESC",
                          (int(chapter),)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["scores"] = json.loads(item.pop("scores_json"))
        except ValueError:
            item["scores"] = {}
        result.append(item)
    return result


def dashboard(project, *, limit: int = 200) -> Dict[str, Any]:
    wb.initialize(project)
    mapping = versions.chapter_map(project)
    with wb.connect(project) as db:
        latest = {}
        for row in db.execute("SELECT * FROM quality_reviews ORDER BY id"):
            latest[int(row["chapter_id"])] = dict(row)
    chapters = []
    for chapter in sorted(mapping)[:int(limit)]:
        row = latest.get(chapter)
        item = {"chapter_id": chapter, "title": versions.parse_chapter_name(mapping[chapter].name)[1]}
        if row:
            try:
                item["scores"] = json.loads(row["scores_json"])
            except ValueError:
                item["scores"] = {}
            item.update({"total": row["total"], "verdict": row["verdict"],
                         "reviewed_at": row["created_at"], "version_id": row["version_id"]})
            current_id = str((versions.current_version(project, chapter) or {}).get("version_id") or "")
            item["stale_review"] = bool(row["version_id"] and current_id and row["version_id"] != current_id)
            if item["stale_review"]:
                item["verdict"] = "stale"
        else:
            item["scores"] = local_scores(_chapter_text(project, chapter))
            item["total"] = round(sum(item["scores"][dim] * WEIGHTS[dim] for dim in DIMENSIONS), 2)
            item["verdict"] = "unreviewed"
            item["reviewed_at"] = None
        item["flags"] = [DIMENSION_LABELS[dim] for dim in DIMENSIONS
                         if item["scores"].get(dim, 100) < THRESHOLD]
        chapters.append(item)
    averages = {dim: round(sum(row["scores"].get(dim, 0) for row in chapters) / max(1, len(chapters)), 2)
                for dim in DIMENSIONS}
    return {"chapters": chapters, "averages": averages,
            "labels": DIMENSION_LABELS, "weights": dict(WEIGHTS),
            "reviewed": sum(1 for row in chapters if row["reviewed_at"] and not row.get("stale_review")),
            "total": len(chapters)}
