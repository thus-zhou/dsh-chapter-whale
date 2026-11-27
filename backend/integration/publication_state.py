"""发布状态回写：真实入队/发布成功后写 ``writer_receipts``（E-01）。

读侧 :func:`integration.chapter_editor._published_state` 只认两个事实：
``published_sha256``（或 ``publish.sha256``）表示已发布，``staged_at`` 表示已入队。
本模块是这两个字段唯一的生产者，边界如下：

* 写入前重新解析该章正文：摘要必须等于当前磁盘正文，或该章版本库里的真实
  历史版本；调用方随便给的摘要不会被写成发布事实（E-03 的伪造正文场景）。
* 在 ``receipts.lock`` 内读取最新回执再原子合并：保留审查结果、其他章节以及
  ``destination``/``sha256`` 等既有字段，兼容没有发布字段的旧回执。
* 写入失败（锁忙、回执损坏）返回 ``recorded=False``，绝不伪造成功；真实平台
  写入已经完成时调用方不应因此回滚发布，只需把原因暴露给诊断面板。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fanqie_auto_publish import publication_safety as safety

from . import chapter_versions

RECEIPTS_NAME = "writer_receipts.json"
LOCK_NAME = "receipts.lock"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def receipts_path(project) -> Path:
    return Path(project) / ".webnovel" / RECEIPTS_NAME


def load_receipts(project) -> Dict[str, Any]:
    """读取回执表；文件损坏或根节点不是对象时抛出 ``ValueError``。"""
    path = receipts_path(project)
    if not path.is_file():
        return {}
    value = safety.read_json_strict(path)
    if not isinstance(value, dict):
        raise ValueError("receipts_corrupt")
    return value


def chapter_receipt(project, chapter: int) -> Dict[str, Any]:
    """只读单章回执；损坏/旧格式一律按空回执处理，不影响调用方。"""
    try:
        value = load_receipts(project).get(str(int(chapter)))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _resolve_binding(project, chapter, content_sha256: str,
                     *, require_current: bool) -> Tuple[Optional[Path], str]:
    """确认 ``content_sha256`` 是该章真实正文，返回 ``(正文路径, 绑定类型)``。

    ``require_current=True`` 用于入队：只接受当前磁盘正文；发布回写允许历史
    版本（作者在发布过程中改稿时，已发布内容仍必须可追溯），但该摘要必须真的
    存在于该章版本库，不能是调用方编造的。
    """
    if not isinstance(content_sha256, str) or not _SHA256_RE.fullmatch(content_sha256):
        return None, "sha256_invalid"
    try:
        number = int(chapter)
    except (TypeError, ValueError):
        return None, "chapter_invalid"
    if number <= 0:
        return None, "chapter_invalid"
    try:
        path = chapter_versions.chapter_path(project, number)
        if path is None:
            return None, "chapter_missing"
        disk = chapter_versions.file_sha256(path)
        if not disk:
            return None, "chapter_missing"
        meta = chapter_versions.current_version(project, number)
        if disk == content_sha256:
            if isinstance(meta, dict):
                indexed = meta.get("sha256") or meta.get("content_sha256")
                if indexed and indexed != disk:
                    return None, "version_mismatch"
            return path, "current"
        if require_current:
            return None, "chapter_changed"
        versions = chapter_versions.list_versions(project, number)
        if any(isinstance(item, dict)
               and content_sha256 in {item.get("sha256"), item.get("content_sha256")}
               for item in versions):
            return path, "version"
        return None, "sha256_not_bound"
    except (OSError, ValueError, RuntimeError):
        return None, "version_store_unavailable"


def _update(project, chapter: int, mutate) -> Dict[str, Any]:
    """在 ``receipts.lock`` 内读最新表 → 改单章 → 原子写回。"""
    path = receipts_path(project)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with safety.file_lock(path.parent / LOCK_NAME):
            latest = load_receipts(project)
            key = str(int(chapter))
            entry = latest.get(key)
            if entry is None:
                entry = {}
            elif not isinstance(entry, dict):
                return {"recorded": False, "reason": "receipt_not_object"}
            mutate(entry)
            latest[key] = entry
            safety.atomic_json(path, latest)
            return {"recorded": True}
    except safety.PublicationBlocked:
        return {"recorded": False, "reason": "receipts_busy"}
    except (OSError, ValueError):
        return {"recorded": False, "reason": "receipts_corrupt"}


def record_staged(project, chapter: int, *, content_sha256: str,
                  source_path=None, book: str = "", queue_file: str = "",
                  body_sha256: str = "", at: str = "") -> Dict[str, Any]:
    """把“该章已真实写入发布队列”写成 ``staged_at``（delete/split/merge 据此只读）。

    只接受当前磁盘正文摘要；队列写入与正文读取之间发生改稿时宁可不写，也不
    把旧摘要冒充成当前稿。
    """
    path, binding = _resolve_binding(project, chapter, content_sha256, require_current=True)
    if path is None:
        return {"recorded": False, "reason": binding, "chapter": int(chapter)}
    if source_path is not None:
        try:
            if Path(source_path).resolve() != path.resolve():
                return {"recorded": False, "reason": "source_mismatch", "chapter": int(chapter)}
        except OSError:
            return {"recorded": False, "reason": "source_mismatch", "chapter": int(chapter)}
    stamp = str(at or _now())

    def mutate(entry: Dict[str, Any]) -> None:
        entry["staged_at"] = stamp
        entry["staged_sha256"] = content_sha256
        entry["stage"] = {
            "sha256": content_sha256,
            "body_sha256": str(body_sha256 or ""),
            "book": str(book or ""),
            "queue_file": str(queue_file or ""),
            "at": stamp,
        }

    result = _update(project, chapter, mutate)
    result.update({"chapter": int(chapter), "sha256": content_sha256,
                   "binding": binding, "at": stamp})
    return result


def record_published(project, chapter: int, *, content_sha256: str,
                     platform: str = "", account: str = "", platform_book_id: str = "",
                     remote_id: str = "", source: str = "", evidence: str = "",
                     at: str = "") -> Dict[str, Any]:
    """把真实平台成功写成 ``published_sha256`` / ``publish`` 回执。

    摘要必须是当前正文或该章版本库中的历史版本；仅凭调用方声明不会写入。
    """
    path, binding = _resolve_binding(project, chapter, content_sha256, require_current=False)
    if path is None:
        return {"recorded": False, "reason": binding, "chapter": int(chapter)}
    stamp = str(at or _now())

    def mutate(entry: Dict[str, Any]) -> None:
        entry["published_sha256"] = content_sha256
        entry["published_at"] = stamp
        publish = entry.get("publish")
        publish = dict(publish) if isinstance(publish, dict) else {}
        publish.update({
            "sha256": content_sha256,
            "platform": str(platform or ""),
            "account": str(account or ""),
            "platform_book_id": str(platform_book_id or ""),
            "remote_id": str(remote_id or ""),
            "source": str(source or ""),
            "evidence": str(evidence or ""),
            "at": stamp,
        })
        entry["publish"] = publish

    result = _update(project, chapter, mutate)
    result.update({"chapter": int(chapter), "sha256": content_sha256,
                   "binding": binding, "at": stamp})
    return result


def review_binding(project, chapter: int, *, content_sha256: str, text: str) -> Dict[str, Any]:
    """校验回执是否绑定“这份正文 + 这个版本”，供 publish/submit 门禁使用。

    ``ok=False`` 的 reason 是稳定短码，可直接进 API 说明；不返回正文。
    """
    entry = chapter_receipt(project, chapter)
    review = entry.get("review")
    if not isinstance(review, dict):
        return {"ok": False, "reason": "review_missing"}
    try:
        number = int(chapter)
        path = chapter_versions.chapter_path(project, number)
        if path is None:
            return {"ok": False, "reason": "chapter_missing"}
        if str(entry.get("destination") or "") != str(path.resolve()):
            return {"ok": False, "reason": "review_destination_mismatch"}
        if str(entry.get("sha256") or "") != content_sha256:
            return {"ok": False, "reason": "review_sha256_mismatch"}
        if not safety.review_eligible(review, safety.body_digest(text), project, number):
            return {"ok": False, "reason": "review_not_eligible"}
        # 回执可能由旧发布门禁按全局约定写入，也可能由 author_confirm 按单章
        # 约定写入；两者都与当前值一致才算未过期。
        hashes = {safety.creative_contract_hash(project),
                  safety.creative_contract_hash_for_chapter(project, number)}
        if not any(safety.qualification_contract_matches(project, number, entry, value)
                   for value in hashes):
            return {"ok": False, "reason": "creative_contract_mismatch"}
        return {"ok": True, "review": review, "version_id": entry.get("version_id")}
    except (OSError, ValueError, RuntimeError, TypeError):
        return {"ok": False, "reason": "review_unreadable"}
