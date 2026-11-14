"""质量门禁：全项目唯一的"能否算质量通过"程序判断。

分工：模型只给分项、问题与证据；总分、权重、门槛、放行、哈希、报告是否过期都由这里算。
作者接受风险（waived_by_author_rule）与 E 授权（waived_by_E）是**另外两件事**，不伪装成质量通过。
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import quality_score as score

SCHEMA = 1


def _now():
    return datetime.now(timezone.utc).isoformat()


def _config():
    try:
        from . import model_roles
        return model_roles.load_config()
    except Exception:
        return {}


def values(config=None):
    config = _config() if config is None else config
    return score.settings(config)


def judge(review, config=None):
    """返回质量判断。quality_pass 为 True/False/None（None = 证据不足，不等于通过）。"""
    parsed = (review or {}).get("quality") if isinstance(review, dict) else None
    computed = score.compute(parsed if parsed is not None else (review or {}).get("raw_review", ""), values(config))
    verdict = (review or {}).get("review_decision") if isinstance(review, dict) else None
    reasons, failures, restricted = [], [], []
    if computed["blocking"]:
        reasons.append("blocking_issue")
        failures = [issue["issue"] for issue in computed["blocking"]]
        restricted = sorted({score.NAMES.get(issue["dimension"], "未标注维度") for issue in computed["blocking"]})
        passed = False
    elif computed["total"] is None:
        reasons.append("scores_missing")
        passed = None
    elif not computed["complete"]:
        reasons.append("dimensions_missing")
        passed = None
    else:
        short = [key for key, value in computed["scores"].items() if value < computed["thresholds"]["item"]]
        if computed["total"] < computed["thresholds"]["total"]:
            reasons.append("total_below_threshold")
            failures.append(f"总分 {computed['total']} < {computed['thresholds']['total']}")
        if short:
            reasons.append("dimension_below_threshold")
            failures.extend(f"{score.NAMES[key]} {computed['scores'][key]} < {computed['thresholds']['item']}" for key in short)
            restricted = [score.NAMES[key] for key in short]
        passed = not reasons
        if passed and verdict == "needs_revision":
            passed = False
            reasons.append("model_verdict_conflict")
            failures.append("模型结论为需修改，但分项均在门槛之上")
    return {
        "schema_version": SCHEMA,
        "quality_pass": passed,
        "reasons": reasons,
        "failures": failures,
        "restricted": restricted,
        "legacy_unscored": computed["format"] != "json",
        "unverified": computed["unverified"],
        "computed": computed,
        "config_hash": computed["config_hash"],
        "thresholds": computed["thresholds"],
        "judged_at": _now(),
    }


def legacy_passed(review):
    """旧的 review_passed 语义：成功且模型没要求修改。保留给兼容调用方。"""
    return bool(isinstance(review, dict) and review.get("success") is True and review.get("needs_revision") is False)


def review_passed(review, config=None):
    """review_passed 的新实现：旧语义 + 按**当前**门槛重算的质量判断。

    缓存里的 quality_gate 只是当时的结论；门槛改过之后必须重新计算，不能沿用旧通过。
    """
    if not legacy_passed(review):
        return False
    return judge(review, config).get("quality_pass") is not False


def pass_ok(review, body_sha256=None, project=None, chapter=None, config=None):
    """质量通过分支的唯一判定：旧的无分项回执仍可兼容，但必须按当前门槛重算。"""
    if not isinstance(review, dict):
        return False
    result = judge(review, config)
    if body_sha256 is not None:
        bound = review.get("body_sha256") or (review.get("quality") or {}).get("body_sha256")
        if bound and bound != body_sha256:
            return False
    if result.get("quality_pass") is False:
        return False
    return True


def blocked_reason(review):
    result = review.get("quality_gate") if isinstance(review, dict) else None
    result = result if isinstance(result, dict) else judge(review)
    return result.get("reasons") or []


# ==================== 报告持久化与过期 ====================

def reports_dir(project):
    return Path(project) / ".webnovel" / "quality_reports"


def report_id(review):
    payload = json.dumps({"raw": (review or {}).get("raw_review", ""), "quality": (review or {}).get("quality")},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def save_report(project, chapter, review, *, body_sha256, version_id=None, contract_hash=None, config=None):
    """把审查结果与它绑定的正文、约定、审查配置一起留档；正文一变，报告即过期。"""
    values_ = values(config)
    record = {
        "schema_version": SCHEMA,
        "chapter_id": int(chapter),
        "report_id": report_id(review),
        "created_at": _now(),
        "body_sha256": body_sha256,
        "version_id": version_id,
        "contract_hash": contract_hash,
        "review_config_hash": score.config_hash(values_),
        "review_config": {"weights": values_["weights"], "threshold_total": values_["threshold_total"],
                          "threshold_item": values_["threshold_item"], "source": values_["source"]},
        "review": review,
    }
    directory = reports_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{int(chapter):04d}-{record['report_id']}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    os.replace(tmp, target)
    return record


def history(project, chapter):
    directory = reports_dir(project)
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob(f"{int(chapter):04d}-*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("chapter_id") == int(chapter):
            doc["path"] = str(path)
            records.append(doc)
    records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return records


def latest(project, chapter):
    records = history(project, chapter)
    return records[0] if records else None


def _current_digests(project, chapter):
    """当前正文的两种指纹：原始字节 sha256 与规范化文本摘要。"""
    from .chapter_versions import chapter_path, raw_sha256
    from fanqie_auto_publish.publication_safety import body_digest

    path = chapter_path(project, chapter)
    if not path or not Path(path).exists():
        return None, None
    data = Path(path).read_bytes()
    return raw_sha256(data), body_digest(data.decode("utf-8-sig", errors="replace"))


def status(project, chapter, record=None, body_sha256=None, contract_hash=None, config=None):
    """报告是否仍然适用。仅门槛/权重变化时只要求重算，不要求重新调用模型。"""
    record = latest(project, chapter) if record is None else record
    if not record:
        return {"valid": False, "stale_reason": "no_report", "recompute_only": False}
    raw, digest = _current_digests(project, chapter)
    if body_sha256 is None:
        body_sha256 = raw
    bound = {value for value in (raw, digest, body_sha256) if value}
    if bound and record.get("body_sha256") and record["body_sha256"] not in bound:
        return {"valid": False, "stale_reason": "body_changed", "recompute_only": False}
    if contract_hash is None:
        try:
            from . import bridge
            contract_hash = bridge.creative_contract_hash(project)
        except Exception:
            contract_hash = ""
    bound_contract = record.get("contract_hash")
    if contract_hash:
        if not bound_contract:
            return {"valid": False, "stale_reason": "contract_unbound", "recompute_only": False}
        if contract_hash != bound_contract:
            return {"valid": False, "stale_reason": "contract_changed", "recompute_only": False}
    if score.config_hash(values(config)) != record.get("review_config_hash"):
        return {"valid": True, "stale_reason": "config_changed", "recompute_only": True,
                "current_pass": judge(record.get("review") or {}, config).get("quality_pass")}
    return {"valid": True, "stale_reason": None, "recompute_only": False}


def public_report(project, chapter, config=None):
    """面板用最小视图：结论、总分、主要问题、受限范围、过期原因。"""
    record = latest(project, chapter)
    if not record:
        return {"chapter_id": int(chapter), "report": None, "status": {"valid": False, "stale_reason": "no_report"}}
    review = record.get("review") or {}
    # 永远按当前配置重算：报告的分数是证据，能否通过由现在的门槛决定。
    result = judge(review, config)
    computed = result.get("computed") or {}
    return {
        "chapter_id": int(chapter),
        "report": {
            "report_id": record.get("report_id"),
            "created_at": record.get("created_at"),
            "review_decision": review.get("review_decision"),
            "quality_pass": result.get("quality_pass"),
            "total": computed.get("total"),
            "scores": computed.get("scores"),
            "names": computed.get("names"),
            "thresholds": computed.get("thresholds"),
            "missing": computed.get("missing"),
            "reasons": result.get("reasons"),
            "failures": result.get("failures"),
            "restricted": result.get("restricted"),
            "issues": (computed.get("issues") or [])[:8],
            "summary": (computed.get("evidence") or "")[:600],
            "legacy_unscored": result.get("legacy_unscored"),
        },
        "status": status(project, chapter, record, config=config),
    }
