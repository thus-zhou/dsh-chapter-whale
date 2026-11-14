"""文风档案：把确定性统计、语义提炼、用户覆盖和参考强度放在一处。

样本正文不复制进档案（只存哈希与统计）；语义部分来自模型，标 semantic=True。
禁用后不再注入提示，但档案保留，方便重新启用。
"""
import hashlib
import json
from pathlib import Path

from . import bridge
from .style_stats import statistics, sample_plan, summary

SCHEMA_VERSION = 1
DEFAULT_STRENGTH = 60


def profile_path(project):
    return Path(project).resolve() / ".webnovel" / "style_profile.json"


def _skeleton():
    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": True,
        "strength": DEFAULT_STRENGTH,
        "status": "unavailable",
        "samples": {},
        "overrides": {},
        "updated_at": bridge.now_iso(),
    }


def read(project):
    path = profile_path(project)
    if not path.is_file():
        return _skeleton()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return _skeleton()
    if not isinstance(doc, dict):
        return _skeleton()
    base = _skeleton()
    base.update({key: doc[key] for key in doc if key in base})
    if not isinstance(base.get("samples"), dict):
        base["samples"] = {}
    if not isinstance(base.get("overrides"), dict):
        base["overrides"] = {}
    base["schema_version"] = SCHEMA_VERSION
    return base


def _write(project, doc):
    doc["schema_version"] = SCHEMA_VERSION
    doc["updated_at"] = bridge.now_iso()
    doc["status"] = _status(doc)
    bridge.write_json_atomic(profile_path(project), doc)
    return doc


def _status(doc):
    samples = doc.get("samples") or {}
    if not samples:
        return "unavailable"
    learned = [item for item in samples.values() if item.get("semantic")]
    if not doc.get("enabled", True):
        return "disabled"
    if learned:
        return "ready"
    return "limited"


def _entry(sample_id, sha256, characters, stats, plan, semantic=None, status="stats_only"):
    return {
        "sample_id": sample_id,
        "sha256": sha256,
        "characters": characters,
        "stats": stats,
        "sampling": plan,
        "semantic": semantic or {},
        "state": status,
        "updated_at": bridge.now_iso(),
    }


def record_sample(project, sample_id, *, sha256, characters, stats, plan, semantic=None, status="stats_only"):
    doc = read(project)
    doc["samples"][sample_id] = _entry(sample_id, sha256, characters, stats, plan, semantic, status)
    return _write(project, doc)


def stat_sample(project, sample_id, text, sha256=None):
    """上传后即可登记统计；不需要模型，失败也不影响写作。"""
    text = text or ""
    stats = statistics(text)
    plan = sample_plan(text)
    return record_sample(
        project,
        sample_id,
        sha256=sha256 or hashlib.sha256(text.encode("utf-8")).hexdigest(),
        characters=len(text),
        stats=stats,
        plan=plan,
    )


def rebuild(project, samples=None):
    """按现有样本重建档案；已有语义结果保留，除非样本哈希变了。"""
    doc = read(project)
    if samples is None:
        from . import studio

        samples = studio.sample_list(project)
    keep = {}
    for meta in samples:
        identity = str(meta.get("id") or "")
        if not identity:
            continue
        try:
            text = (Path(project) / ".webnovel" / "samples" / (identity + ".txt")).read_text(encoding="utf-8")
        except OSError:
            continue
        current = doc["samples"].get(identity) or {}
        same = current.get("sha256") == meta.get("sha256")
        stats = current.get("stats") if same and current.get("stats") else statistics(text)
        plan = current.get("sampling") if same and current.get("sampling") else sample_plan(text)
        semantic = current.get("semantic") if same else {}
        keep[identity] = _entry(identity, meta.get("sha256", ""), len(text), stats, plan, semantic,
                                current.get("state", "stats_only") if same else "stats_only")
    doc["samples"] = keep
    return _write(project, doc)


def after_learn(project, sample_id, *, guide, semantic=None, mode="representative", segments=0):
    doc = read(project)
    entry = doc["samples"].get(sample_id) or _entry(sample_id, "", 0, {}, [])
    entry["semantic"] = {"guide": (guide or "").strip(), "mode": mode, "segments": int(segments or 0),
                          "learned_at": bridge.now_iso(), **(semantic or {})}
    entry["state"] = "learned"
    doc["samples"][sample_id] = entry
    return _write(project, doc)


def mark_failed(project, sample_id, error=""):
    """学习失败保留统计并按有限状态降级，不把整份档案清空。"""
    doc = read(project)
    entry = doc["samples"].get(sample_id)
    if entry is None:
        return doc
    entry["state"] = "failed"
    entry["error"] = str(error)[:300]
    return _write(project, doc)


def remove_sample(project, sample_id):
    doc = read(project)
    doc["samples"].pop(sample_id, None)
    return _write(project, doc)


def options(project, *, enabled=None, strength=None, overrides=None):
    doc = read(project)
    if enabled is not None:
        doc["enabled"] = bool(enabled)
    if strength is not None:
        try:
            value = int(strength)
        except (TypeError, ValueError):
            raise ValueError("参考强度必须是 0 到 100 的整数")
        if not 0 <= value <= 100:
            raise ValueError("参考强度必须是 0 到 100 的整数")
        doc["strength"] = value
    if overrides is not None:
        if not isinstance(overrides, dict):
            raise ValueError("档案覆盖必须是对象")
        if len(overrides) > 20 or any(not isinstance(key, str) or len(key) > 40 for key in overrides):
            raise ValueError("档案覆盖字段过多")
        if any(not isinstance(value, str) or len(value) > 400 for value in overrides.values()):
            raise ValueError("档案覆盖内容过长")
        doc["overrides"] = {key: value for key, value in overrides.items() if value.strip()}
    return _write(project, doc)


def _weighted(samples, pick, digits=1):
    total = sum(int(item.get("characters") or 0) for item in samples)
    if not total:
        return 0
    return round(sum(float(pick(item.get("stats") or {})) * int(item.get("characters") or 0) for item in samples) / total, digits)


def merged_stats(doc):
    samples = list((doc.get("samples") or {}).values())
    if not samples:
        return {}
    return {
        "characters": sum(int(item.get("characters") or 0) for item in samples),
        "sentences": sum(int((item.get("stats") or {}).get("sentences") or 0) for item in samples),
        "sentence_length": {
            "median": _weighted(samples, lambda s: (s.get("sentence_length") or {}).get("median", 0), 0),
            "p90": _weighted(samples, lambda s: (s.get("sentence_length") or {}).get("p90", 0), 0),
        },
        "paragraph_length": {
            "median": _weighted(samples, lambda s: (s.get("paragraph_length") or {}).get("median", 0), 0),
            "max": max(int((item.get("stats") or {}).get("paragraph_length", {}).get("max") or 0) for item in samples),
        },
        "dialogue_ratio": _weighted(samples, lambda s: s.get("dialogue_ratio", 0), 3),
        "note": "多样本按字数加权合并；语义判断不在其中",
    }


def instruction(doc):
    strength = int(doc.get("strength") or DEFAULT_STRENGTH)
    return (f"作者文风参考强度 {strength}/100（只是倾向参考，不承诺线性效果）。"
            "作者约定与已确认的人物、剧情优先于示范样本；不复制示范的原句、人名或情节。")


def effective(project):
    doc = read(project)
    enabled = bool(doc.get("enabled", True))
    guides = [str((item.get("semantic") or {}).get("guide") or "").strip()
              for item in (doc.get("samples") or {}).values()]
    guides = [item for item in guides if item]
    overrides = doc.get("overrides") or {}
    if not enabled:
        return {"enabled": False, "status": "disabled", "strength": doc.get("strength"),
                "guide": "", "overrides": overrides, "instruction": "", "stats": merged_stats(doc)}
    guide = "\n\n".join(guides)
    return {
        "enabled": True,
        "status": doc.get("status") or _status(doc),
        "strength": doc.get("strength", DEFAULT_STRENGTH),
        "guide": guide,
        "overrides": overrides,
        "instruction": instruction(doc) if guides else "",
        "stats": merged_stats(doc),
    }


def digest(doc=None, project=None):
    """给创作约定哈希用；没有启用或没有内容时返回空串，保证旧项目哈希不变。"""
    doc = doc if doc is not None else read(project)
    payload = effective(project) if project is not None else None
    if payload is None:
        enabled = bool(doc.get("enabled", True))
        guides = [str((item.get("semantic") or {}).get("guide") or "").strip()
                  for item in (doc.get("samples") or {}).values()]
        payload = {"enabled": enabled, "strength": doc.get("strength"),
                   "guide": "\n\n".join(item for item in guides if item),
                   "overrides": doc.get("overrides") or {}}
    if not payload.get("enabled") or not (payload.get("guide") or payload.get("overrides")):
        return ""
    material = json.dumps({"strength": payload.get("strength"), "guide": payload.get("guide"),
                           "overrides": payload.get("overrides")}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def public(project):
    doc = read(project)
    effective_doc = effective(project)
    rows = []
    names = {}
    try:
        from . import studio

        names = {str(item.get("id")): str(item.get("name") or "") for item in studio.sample_list(project)}
    except (ValueError, OSError):
        names = {}
    for item in (doc.get("samples") or {}).values():
        rows.append({
            "sample_id": item.get("sample_id"),
            "name": names.get(str(item.get("sample_id")), ""),
            "characters": item.get("characters", 0),
            "state": item.get("state", "stats_only"),
            "learned_at": (item.get("semantic") or {}).get("learned_at", ""),
            "error": item.get("error", ""),
            "summary": summary(item.get("stats") or {}),
        })
    rows.sort(key=lambda row: str(row.get("sample_id")))
    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": bool(doc.get("enabled", True)),
        "strength": doc.get("strength", DEFAULT_STRENGTH),
        "status": effective_doc["status"],
        "overrides": doc.get("overrides") or {},
        "samples": rows,
        "stats": effective_doc["stats"],
        "instruction": effective_doc["instruction"],
        "digest": digest(doc),
        "note": "样本全文可能发送给已配置的模型服务；档案只保存哈希与统计，不保存样本正文。",
    }
