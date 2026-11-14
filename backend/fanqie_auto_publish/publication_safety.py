"""Local publication evidence, durable writes and process locks (no credentials)."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class PublicationBlocked(RuntimeError):
    """A stable reason code, deliberately excluding page/exception contents."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_json_strict(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublicationBlocked("invalid_json") from exc


def replace_with_retry(source,target):
    """Windows sharing/AV contention only; never delete target to force a write."""
    for attempt in range(6):
        try:return os.replace(source,target)
        except PermissionError as exc:
            if os.name!='nt' or getattr(exc,'winerror',None) not in (5,32,33) or attempt==5:raise
            time.sleep(.05*(2**attempt))


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        replace_with_retry(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


_locks = threading.local()


@contextmanager
def file_lock(path):
    """Nonblocking OS lock; released by the OS after death. Never kill/check PIDs.

    The inode is permanent: removing lock files permits two owners. Same-thread
    nesting is supported; other threads/processes are refused, not queued.
    """
    path = Path(path).resolve()
    key = os.path.normcase(str(path))
    held = getattr(_locks, "held", None)
    if held is None:
        held = _locks.held = {}
    if key in held:
        held[key] += 1
        try:
            yield path
        finally:
            held[key] -= 1
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise PublicationBlocked("resource_busy") from exc
        held[key] = 1
        try:
            yield path
        finally:
            del held[key]
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def queue_lock(root):
    return file_lock(Path(root) / ".publication" / "queue.lock")


def account_lock(state_path):
    return file_lock(Path(state_path).with_name(".publication-account.lock"))


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def creative_contract_hash(project):
    """Chat history is advisory; only confirmed requirements bind a review."""
    path = Path(project) / ".webnovel" / "creative_brief.json"
    document = read_json_strict(path) if path.exists() else {"brief":{}}
    brief = document.get("brief") if isinstance(document, dict) else None
    if not isinstance(brief, dict) or any(not isinstance(v, str) for v in brief.values()):
        raise PublicationBlocked("invalid_creative_contract")
    values = {k:v.strip() for k,v in brief.items() if v.strip()}
    learning=document.get("learning",{})
    if not isinstance(learning,dict) or not isinstance(learning.get("guide",""),str):
        raise PublicationBlocked("invalid_creative_contract")
    if learning.get("guide","").strip():values["__learned_guide__"]=learning["guide"].strip()
    memory_path=Path(project)/".webnovel"/"shared_memory.json"
    if memory_path.exists() or memory_path.is_symlink():
        import sys
        root=str(Path(__file__).resolve().parents[1])
        if root not in sys.path:sys.path.insert(0,root)
        from integration import memory_library
        decisions=memory_library.contract(project)
        if decisions:values["__author_memory__"]=decisions
    if not values:
        return ""
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def qualification_contract_matches(project, chapter, receipt, current_hash=None):
    """Narrow, evidenced author scope: a future-only change need not revoke51.

    This never manufactures a review or replaces its old contract. Only an
    exact preserved source/receipt and explicitly approved current contract
    can inherit the earlier qualification; another edit invalidates the scope.
    """
    current_hash=creative_contract_hash(project) if current_hash is None else current_hash
    if not isinstance(receipt,dict):return False
    if receipt.get('creative_contract_hash','')==current_hash:return True
    if type(chapter) is not int or chapter!=51:return False
    try:
        root=Path(project).resolve();folder=root/'.webnovel/qualification_scopes'
        scope_path=folder/'0051.json'
        if folder.is_symlink() or scope_path.is_symlink():return False
        scope=read_json_strict(scope_path)
        if not isinstance(scope,dict) or scope.get('schema')!=1 or scope.get('approved') is not True:return False
        if scope.get('chapter')!=chapter or scope.get('project')!=str(root):return False
        if scope.get('current_contract')!=current_hash or scope.get('original_contract')!=receipt.get('creative_contract_hash'):return False
        origin_path=Path(scope['origin_record'])
        if origin_path.is_symlink() or origin_path.resolve()!=folder/'0051-origin.json':return False
        if digest_file(origin_path)!=scope.get('origin_record_sha256'):return False
        origin=read_json_strict(origin_path)
        if origin.get('project')!=str(root) or origin.get('chapter')!=chapter:return False
        original=origin.get('qualified_receipt')
        if not isinstance(original,dict) or receipt!=original:return False
        source=Path(receipt['destination'])
        if source.is_symlink() or source.resolve().parent!=root/'正文':return False
        if str(source.resolve())!=origin.get('source'):return False
        sha=digest_file(source)
        if sha!=receipt.get('sha256') or sha!=scope.get('source_sha256') or sha!=origin.get('source_sha256'):return False
        raw=source.read_text(encoding='utf-8-sig')
        return review_eligible(receipt.get('review'),body_digest(raw),root,chapter)
    except (OSError,ValueError,KeyError,TypeError,PublicationBlocked):return False


def normalized_body(text):
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def body_digest(text):
    return hashlib.sha256(normalized_body(text).encode("utf-8")).hexdigest()


def _quality_pass_ok(review,body_sha256=None,project=None,chapter=None):
    """质量通过分支再交由唯一门禁复查；旧的无分项回执保持兼容。"""
    try:
        import sys
        root=str(Path(__file__).resolve().parents[1])
        if root not in sys.path:sys.path.insert(0,root)
        from integration import quality_gate
        return quality_gate.pass_ok(review,body_sha256,project,chapter)
    except Exception:
        return False


def review_eligible(review,body_sha256,project=None,chapter=None):
    if not isinstance(review,dict):return False
    if review.get("success") is True and review.get("review_decision")=="pass" and review.get("needs_revision",False) is False:
        return _quality_pass_ok(review,body_sha256,project,chapter)
    if review.get('review_decision')=='waived_by_author_rule':
        from integration.editorial_release import valid
        auth=review.get('author_rule_authorization',{})
        if not isinstance(auth,dict):return False
        if project is not None and str(Path(auth.get('project','')).resolve()).casefold()!=str(Path(project).resolve()).casefold():return False
        if chapter is not None and (type(auth.get('chapter')) is not int or auth['chapter']!=chapter):return False
        return valid(review,body_sha256)
    if review.get("review_decision")!="waived_by_E":return False
    import sys
    root=str(Path(__file__).resolve().parents[1])
    if root not in sys.path:sys.path.insert(0,root)
    from integration import model_roles
    config=model_roles.load_config();authorization=review.get("executor_authorization",{})
    return (model_roles.enabled(config) and config.get("review_policy")=="e_decides" and isinstance(authorization,dict)
        and authorization.get("approved") is True and authorization.get("role")=="E" and authorization.get("policy")=="e_decides"
        and authorization.get("body_sha256")==body_sha256)


def journal_path(source):
    return Path(source).with_name(Path(source).name + ".publish.json")


def requires_reconciliation(record):
    """A local pre-submit marker cannot overrule observed remote side effects."""
    return isinstance(record, dict) and (
        record.get('state') in {'submitting', 'unconfirmed', 'platform_confirmed'}
        or bool(record.get('submitted_at'))
        or record.get('reason') in {
            'existing_chapter_requires_reconciliation', 'existing_chapter_not_draft', 'publish_settings_timeout',
            'submission_transition_timeout', 'publish_subprocess_timeout',
        })


def valid_receipt(path, book=None, chapter_id=None, account=None):
    """An old TXT alone is never publication evidence."""
    path = Path(path)
    evidence = journal_path(path)
    if not evidence.exists():
        return None
    record = read_json_strict(evidence)
    if not isinstance(record, dict):
        return None
    checks = (
        record.get("schema") == 1,
        record.get("state") == "platform_confirmed",
        record.get("platform_status") == "已发布",
        record.get("verification") == "chapter_list_and_body",
        isinstance(record.get("verified_at"), str) and bool(record["verified_at"]),
        isinstance(record.get("account"), str) and bool(record["account"]),
        isinstance(record.get("book_url"), str) and record["book_url"].startswith("https://fanqienovel.com/"),
        record.get("file_sha256") == digest_file(path),
        book is None or record.get("book") == book,
        chapter_id is None or record.get("chapter_id") == chapter_id,
        account is None or record.get("account") == account,
    )
    return record if all(checks) else None


def archive_confirmed(source, destination, receipt):
    source, destination = Path(source), Path(destination)
    if receipt.get("state") != "platform_confirmed" or receipt.get("file_sha256") != digest_file(source):
        raise PublicationBlocked("archive_evidence_mismatch")
    if valid_receipt(source, receipt["book"], receipt["chapter_id"], receipt["account"]) != receipt:
        raise PublicationBlocked("archive_receipt_missing")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or journal_path(destination).exists():
        raise PublicationBlocked("archive_collision")
    # Receipt first, then non-overwriting link/unlink on this same-volume queue.
    # A crash at any step leaves evidence; it never permits a new submit.
    atomic_json(journal_path(destination), receipt)
    os.link(source, destination)
    if digest_file(source) != receipt["file_sha256"]:
        raise PublicationBlocked("queue_changed")
    source.unlink()


def validate_origin_plan(plan, files, book, account):
    """Recheck the reviewed source and queue bytes under the publisher lock."""
    if not isinstance(plan, dict) or plan.get("schema") != 1 or plan.get("book") != book or plan.get("account") != account:
        raise PublicationBlocked("origin_plan_identity_mismatch")
    project = Path(plan.get("project", "")).resolve()
    receipts = read_json_strict(project / ".webnovel" / "writer_receipts.json")
    contract_hash = creative_contract_hash(project)
    entries = plan.get("chapters", [])
    if not isinstance(receipts, dict) or len(entries) != len(files):
        raise PublicationBlocked("origin_plan_chapters_mismatch")
    for entry, queued in zip(entries, files):
        source = Path(entry.get("source", "")).resolve()
        if source.parent != (project / "正文").resolve() or source.is_symlink():
            raise PublicationBlocked("origin_source_path_mismatch")
        from integration.length_policy import require
        require(project, source.read_text(encoding="utf-8-sig"), entry.get("chapter_id"))
        receipt = receipts.get(str(entry.get("chapter_id")), {})
        review = receipt.get("review", {}) if isinstance(receipt, dict) else {}
        if (entry.get("filename") != Path(queued).name or entry.get("file_sha256") != digest_file(queued) or
            entry.get("source_sha256") != digest_file(source) or receipt.get("destination") != str(source) or
            receipt.get("sha256") != digest_file(source) or not qualification_contract_matches(project,entry.get('chapter_id'),receipt,contract_hash) or
            not review_eligible(review,body_digest(source.read_text(encoding="utf-8-sig")),project,entry.get('chapter_id'))):
            raise PublicationBlocked("origin_review_or_content_mismatch")
