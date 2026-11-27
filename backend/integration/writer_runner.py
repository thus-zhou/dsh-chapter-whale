"""把 webnovel-writer 的 AI 写作、审查、修改封装成一次可调度运行。

这个模块不改动上游写作系统的核心代码，只复用 ``SkillExecutor`` 的完整工作流，
并在审查通过后负责把章节落盘。调度器和未来的 Codex 定时任务都调用这里，保证
手动运行与无人值守运行走同一条链路。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


SCRIPT_ROOT = Path(__file__).resolve().parent
COMBINED_ROOT = SCRIPT_ROOT.parent
WEBNOVEL_BACKEND = COMBINED_ROOT / "webnovel-writer" / "backend"
if str(WEBNOVEL_BACKEND) not in sys.path:
    sys.path.insert(0, str(WEBNOVEL_BACKEND))

try:
    from .bridge import creative_contract_hash, now_iso, parse_chapter_name, safe_dir_name, review_eligible, body_digest
except ImportError:
    from bridge import creative_contract_hash, now_iso, parse_chapter_name, safe_dir_name, review_eligible, body_digest
from integration import costs
from . import publication_state


def _load_webnovel_services():
    """延迟导入上游服务，令 ``--help`` 和队列诊断不依赖 AI 初始化。"""

    from services import ai_service
    from services.skill_executor import SkillExecutor

    config = os.environ.get("NOVEL_HELPER_AI_CONFIG", "").strip()
    ai_service.CONFIG_FILE = Path(config).expanduser().resolve() if config else (
        COMBINED_ROOT / "integration_data" / "ai_config.json"
    )
    def configured_service():
        from integration import model_roles
        current = model_roles.load_config()
        if current.get('provider_schema') == 1:
            return model_roles.service('B', current)
        path = ai_service.CONFIG_FILE
        stat = path.stat() if path.exists() else None
        token = (str(path), stat.st_mtime_ns if stat else None, stat.st_size if stat else None)
        if getattr(ai_service, "_novel_helper_config_token", None) != token:
            ai_service._ai_service = None
            ai_service._novel_helper_config_token = token
        return ai_service.get_ai_service()

    return SkillExecutor, configured_service


_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


@contextmanager
def file_lock(path: Path, blocking: bool = False, timeout: float = 15):
    """Thread + OS advisory lock; a terminated process releases the OS lock.

    Keep the lock file in place: unlinking it allows two different file handles
    to lock different inodes. CLI and API callers must use this same helper.
    """
    path = path.resolve()
    with _LOCKS_GUARD:
        local = _LOCKS.setdefault(str(path).casefold(), threading.Lock())
    import time
    deadline = time.monotonic() + timeout
    acquired = local.acquire(timeout=timeout) if blocking else local.acquire(blocking=False)
    if not acquired:
        raise RuntimeError(f"已有任务正在运行：{path}")
    handle = None
    locked = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+b")
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            # LK_LOCK has a finite retry limit; configuration transactions need
            # an actual blocking lock, including when another process owns it.
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if not blocking or time.monotonic() >= deadline:
                        raise RuntimeError(f"已有任务正在运行：{path}") from None
                    import time
                    time.sleep(0.05)
        else:
            import fcntl
            try:
                while True:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if not blocking or time.monotonic() >= deadline:raise
                        time.sleep(0.05)
            except BlockingIOError:
                raise RuntimeError(f"已有任务正在运行：{path}") from None
        locked = True
        yield
    finally:
        if handle is not None:
            if locked:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()
        local.release()


def strict_json(path: Path, default: Any) -> Any:
    """Only a missing file is optional; corrupt state must never become empty."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        from fanqie_auto_publish.publication_safety import replace_with_retry
        replace_with_retry(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def review_passed(review: Any) -> bool:
    """兼容包装器：质量判断唯一入口是 quality_gate，这里只做旧签名的转发。"""
    from . import quality_gate
    return quality_gate.review_passed(review)


MAX_AUTO_REVIEWS = 2


def human_review_handoff(review: Any, body_sha256: str) -> bool:
    """Two-review cap handoff: saved locally with honest non-pass quality state."""
    return (
        isinstance(review, dict)
        and review.get("review_decision") == "needs_human_review"
        and review.get("human_review_required") is True
        and review.get("body_sha256") == body_sha256
    )


def human_handoff_review(base: Any, body_sha256: str, auto_review_count: int,
                         *, reason: str = "auto_review_cap") -> Dict[str, Any]:
    """Build the single handoff receipt shape shared by generation and polish.

    The failing review is kept (it still carries the author-facing issues and D
    candidates), but the decision is always a non-publishable human handoff.
    """
    review = dict(base) if isinstance(base, dict) else {}
    review.update({
        "success": True,
        "review_decision": "needs_human_review",
        "human_review_required": True,
        "review_capped": reason == "auto_review_cap",
        "auto_review_count": int(auto_review_count),
        "body_sha256": body_sha256,
        "handoff_reason": reason,
    })
    return review


def _receipt_collection(project_root: Path, include_handoff: bool = False) -> Dict[int, Dict[str, Any]]:
    """Return receipts bound to the exact, uniquely named saved body."""
    from fanqie_auto_publish.publication_safety import qualification_contract_matches
    data = strict_json(project_root / ".webnovel" / "writer_receipts.json", {})
    if not isinstance(data, dict):
        raise ValueError("writer_receipts.json 必须是对象")
    files: Dict[int, List[Path]] = {}
    for path, chapter in _chapter_files(project_root):
        files.setdefault(chapter, []).append(path)
    result = {}
    contract_hash = creative_contract_hash(project_root)
    for raw_id, receipt in data.items():
        if not str(raw_id).isdigit() or not isinstance(receipt, dict):
            continue
        chapter = int(raw_id)
        paths = files.get(chapter, [])
        if len(paths) != 1:
            continue
        path = paths[0]
        digest = body_digest(path.read_text(encoding="utf-8-sig"))
        review = receipt.get("review")
        eligible = review_eligible(review, digest, project_root, chapter)
        handoff = include_handoff and human_review_handoff(review, digest)
        if not (eligible or handoff):
            continue
        if (receipt.get("destination") == str(path.resolve())
                and receipt.get("sha256") == hashlib.sha256(path.read_bytes()).hexdigest()
                and (handoff or qualification_contract_matches(project_root, chapter, receipt, contract_hash))):
            result[chapter] = receipt
    return result


def reviewed_chapters(project_root: Path) -> Dict[int, Dict[str, Any]]:
    """Return only publication-eligible receipts bound to the exact saved body."""
    return _receipt_collection(project_root, include_handoff=False)


def committed_chapters(project_root: Path) -> Dict[int, Dict[str, Any]]:
    """Return locally committed chapters (passed or handed off to human review)."""
    base = reviewed_chapters(project_root)
    extra = _receipt_collection(project_root, include_handoff=True)
    return {**extra, **base}


def approve_chapter_review(project_path: Path, chapter_id: int, note: str = "",
                           expected_sha256: Optional[str] = None) -> Dict[str, Any]:
    """Approve only a genuine two-review handoff bound to the current body."""
    if type(chapter_id) is not int or chapter_id <= 0:
        raise ValueError("chapter_id 必须是正整数")
    root = Path(project_path).expanduser().resolve()
    with file_lock(root / ".webnovel" / "writer.lock"):
        paths = [p for p, i in _chapter_files(root) if i == chapter_id]
        if len(paths) != 1:
            raise ValueError("指定章节必须唯一对应一个正文文件")
        source = paths[0]
        if source.is_symlink() or (root / "正文").resolve() not in source.resolve().parents:
            raise ValueError("不安全的正文路径")
        raw = source.read_bytes()
        text = raw.decode("utf-8-sig")
        digest = body_digest(text)
        expected = str(expected_sha256 or "").strip().lower()
        if expected and expected not in {hashlib.sha256(raw).hexdigest(), digest}:
            raise ValueError("正文已变化，请刷新后重新确认人工复核")
        receipts_path = root / ".webnovel" / "writer_receipts.json"
        receipts = strict_json(receipts_path, {})
        if not isinstance(receipts, dict):
            raise ValueError("writer_receipts.json 必须是对象")
        existing = receipts.get(str(chapter_id)) if isinstance(receipts.get(str(chapter_id)), dict) else {}
        review = dict(existing.get("review") or {})
        # 只有真正走完两次自动审查并交回人工的章节才可批准；普通未审/需修订
        # 章节不能借这个接口直接取得发布资格。先判断回执类型，再校验正文指纹，
        # 这样普通章节得到“不是交接稿”，而不是含混的指纹错误。
        if not (review.get("review_decision") == "needs_human_review"
                and review.get("human_review_required") is True):
            if (review.get("review_decision") == "human_approved"
                    and review.get("human_review_approved") is True):
                bound_body = review.get("body_sha256")
                if not isinstance(bound_body, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", bound_body):
                    raise ValueError("审查回执缺少有效的正文指纹，不能批准")
                if bound_body.lower() != digest:
                    raise ValueError("待复核正文已变化，请重新审查后再批准")
                # 已批准且正文一致的重复调用是幂等的，不再报“不是待复核交接稿”。
                return {"status": "approved", "reused": True, "chapter_id": chapter_id,
                        "review_decision": "human_approved", "receipt": existing}
            raise ValueError("该章不是待人工复核的交接稿，不能直接批准")
        # 审批必须绑定到当前正文的规范化摘要；缺失或格式错误不允许“跳过校验”。
        bound_body = review.get("body_sha256")
        if not isinstance(bound_body, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", bound_body):
            raise ValueError("审查回执缺少有效的正文指纹，不能批准")
        if bound_body.lower() != digest:
            raise ValueError("待复核正文已变化，请重新审查后再批准")
        # max_revisions=0 的首次交接只有一次 D 审查，用独立 reason 允许 >=1，
        # 其他 reason 仍要求满两次。
        count = review.get("auto_review_count")
        required = 1 if review.get("handoff_reason") == "zero_revision_budget" else MAX_AUTO_REVIEWS
        if type(count) is not int or count < required:
            raise ValueError(f"该章自动审查次数不足 {required} 次，不能按交接稿批准")
        review.update({
            "success": True,
            "review_decision": "human_approved",
            "human_review_approved": True,
            "human_review_required": False,
            "needs_revision": False,
            "body_sha256": digest,
            "human_approved_at": now_iso(),
            "human_review_note": str(note or "").strip()[:400],
        })
        receipt = {
            **existing,
            "destination": str(source.resolve()),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "review": review,
            "creative_contract_hash": creative_contract_hash(root),
            "reviewed_at": existing.get("reviewed_at") or now_iso(),
            "human_approved_at": review["human_approved_at"],
        }
        receipts[str(chapter_id)] = receipt
        atomic_json(receipts_path, receipts)
        # 交接时只保存了 pending 候选；人工批准后才写入共享记忆与人物档案。
        receipt["candidates"] = _commit_review_candidates(
            root, chapter_id, text, review, _writer_locked=True, force_commit=True)
        # P2-4: approval does not block the HTTP request on model calls. Mark the
        # downstream artifacts as pending so the next generation can finish them
        # with the same executor instead of silently leaving them half-synced.
        receipt["post_save"] = {
            "status": "pending_approval",
            "entities": {"status": "pending_approval"},
            "shared_memory": {"status": "pending_approval", "reason": "human_approved"},
            "rag_indexed": False,
            "continuity_written": False,
        }
        atomic_json(receipts_path, receipts)
        _save_progress(root, chapter_id)
        return {"status": "approved", "chapter_id": chapter_id, "review_decision": "human_approved", "receipt": receipt}


def _chapter_files(project_root: Path) -> Iterable[Tuple[Path, int]]:
    chapters_dir = project_root / "正文"
    if not chapters_dir.is_dir():
        return []
    result: List[Tuple[Path, int]] = []
    for path in chapters_dir.glob("*.md"):
        parsed = parse_chapter_name(path.name)
        if parsed:
            result.append((path, parsed[0]))
    return sorted(result, key=lambda item: (item[1], item[0].name.casefold()))


def existing_chapter_ids(project_root: Path) -> Set[int]:
    return {chapter_id for _, chapter_id in _chapter_files(project_root)}


def next_chapter_id(project_root: Path) -> int:
    """按正文文件和项目进度取下一个顺序章节，不覆盖已有正文。"""

    ids = existing_chapter_ids(project_root)
    state = strict_json(project_root / ".webnovel" / "state.json", {})
    if not isinstance(state, dict):
        raise ValueError("state.json 必须是对象")
    current = 0
    progress = state.get("progress", {})
    if not isinstance(progress, dict):
        raise ValueError("state progress 必须是对象")
    current = max(int(state.get("current_chapter", 0) or 0),
                  int(progress.get("current_chapter", 0) or 0))
    return max(max(ids, default=0), current) + 1


_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def _chinese_to_int(text: str) -> Optional[int]:
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    total = 0
    section = 0
    number = 0
    for ch in raw:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = 0
            else:
                if number == 0 and unit == 10 and section == 0:
                    number = 1
                section += number * unit
            number = 0
        else:
            return None
    value = total + section + number
    return value if value > 0 else None


_HEADING_ARABIC = re.compile(
    r"^(?:"
    r"(?:#{1,6}\s*|\*\*\s*|__\s*)0*(\d+)\s*\."          # # 1. / **1. / __1.
    r"|0*(\d+)\s*\.\s*《"                                  # 1. 《书名》
    r"|(?:#{0,6}\s*|\s*[-*•]\s+)?(?:\*\*|__)?\s*第\s*0*(\d+)\s*章"  # 第1章 / 第 1 章
    r")"
)
_HEADING_CHINESE = re.compile(r"^(?:#+\s*)?(?:[-*•]\s+)?(?:\*\*|__)?\s*第\s*([零〇一二两三四五六七八九十百千万]+)\s*章")


def _chapter_heading_number(line: str) -> Optional[int]:
    stripped = str(line or "").strip()
    match = _HEADING_ARABIC.match(stripped)
    if match:
        return int(match.group(1) or match.group(2) or match.group(3))
    match = _HEADING_CHINESE.match(stripped)
    if match:
        return _chinese_to_int(match.group(1))
    return None


def _find_outline(project_root: Path, chapter: int) -> str:
    # Local, read-only lookup makes --dry-run independent of AI initialization.
    for path in sorted((project_root / "大纲").glob("*.md")):
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        start = None
        for i, line in enumerate(lines):
            found = _chapter_heading_number(line)
            if found is not None:
                if start is not None:
                    return "\n".join(lines[start:i]).strip()
                if found == chapter:
                    start = i
        if start is not None:
            return "\n".join(lines[start:]).strip()
    return ""


def _outline_title(outline: str, chapter_id: int) -> str:
    for raw_line in str(outline or "").splitlines():
        line = raw_line.strip().lstrip("#").strip().lstrip("-*•").strip().replace("**", "").replace("__", "")
        if _chapter_heading_number(raw_line) != chapter_id:
            continue
        match = re.search(
            rf"(?:第\s*(?:0*{chapter_id}|[零〇一二两三四五六七八九十百千万]+)\s*章|0*{chapter_id}\s*\.)(?:[：:\-—–_\s]+(.+?))?(?:\s*)$",
            line,
        )
        if match:
            title = (match.group(1) or "").strip(" -—–_：:《》　")
            if title:
                return title
    return ""


def _chapter_path(project_root: Path, chapter_id: int, title: str) -> Path:
    safe_title = safe_dir_name(title).strip(" .") if title else ""
    suffix = f"-{safe_title}" if safe_title else ""
    return project_root / "正文" / f"第{chapter_id}章{suffix}.md"

def _unique_chapter_title(project_root: Path, chapter_id: int, title: str) -> str:
    """Fanqie refuses a chapter whose title repeats an existing one (-3011).

    Planning can legitimately reuse a title (for example a two-part chapter).
    Suffix the new chapter instead of failing the whole daily batch later.
    """
    if not title:
        return title
    from . import bridge
    used = {
        str(entry_title).strip()
        for _path, cid, entry_title, _text in bridge.iter_source_chapters(project_root)
        if cid != chapter_id
    }
    if title not in used:
        return title
    candidate = f"{title}（续）"
    index = 1
    while candidate in used:
        index += 1
        candidate = f"{title}（续{index}）"
    return candidate


def _retitle_chapter_heading(content: str, chapter_id: int, title: str) -> str:
    """Apply the de-duplicated title to the generated H1 only."""
    pattern = re.compile(rf"^#\s*第\s*0*{chapter_id}\s*章(?:\s+.*)?$")
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if pattern.match(line.strip()):
            lines[index] = f"# 第{chapter_id}章 {title}"
            return "\n".join(lines)
    return content


async def _read_stream_result(event_stream: Any) -> Dict[str, Any]:
    content = ""
    review: Optional[Dict[str, Any]] = None
    errors: List[str] = []
    failure = {}
    success = False
    done = False
    reviewed_content = None
    async for event_text in event_stream:
        try:
            event = json.loads(event_text)
        except (TypeError, ValueError):
            errors.append("写作事件不是有效 JSON")
            continue
        if not isinstance(event, dict):
            errors.append("写作事件格式无效")
            continue
        event_type = event.get("type")
        if done:
            errors.append("完成事件后仍有写作事件")
            continue
        if event_type == "content":
            if event.get("replace") and event.get("full") is not None:
                content = str(event.get("full") or "")
            else:
                content += str(event.get("chunk") or "")
        elif event_type == "review":
            value = event.get("result")
            if isinstance(value, dict):
                review = value
                reviewed_content = content
            else:
                review = None
        elif event_type == "error":
            message = str(event.get("message") or "未知写作错误")
            errors.append(message)
            failure = {key:event[key] for key in ('failure_kind','retryable','http_status','error_code','next_retry_at') if key in event}
        elif event_type == "done":
            done = True
            success = event.get("success") is True
            if "content" in event:
                content = str(event.get("content") or "")
    if reviewed_content is None or content.strip() != reviewed_content.strip():
        review = None
    return {
        "content": content.strip(),
        "review": review,
        "errors": errors,
        "failure": failure,
        "success": success,
    }


def _record_review_attempt(project,chapter,content,review):
    """Keep D evidence even if E vetoes the current draft; never grants approval."""
    from . import quality_gate
    if isinstance(review,dict) and 'quality_gate' not in review:
        review=dict(review); review['quality_gate']=quality_gate.judge(review)
    path=Path(project)/'.webnovel'/'review_attempts'/f'{chapter:04d}-{uuid.uuid4().hex}.json'
    digest=body_digest(content)
    atomic_json(path,{'chapter_id':chapter,'reviewed_at':now_iso(),'body_sha256':digest,'review':review})
    try:
        quality_gate.save_report(project,chapter,review,body_sha256=digest,
                                 contract_hash=creative_contract_hash(project))
    except Exception:
        pass  # 报告留档失败不阻断既有回执写入；过期状态由 no_report 表达


def _commit_review_candidates(project, chapter, content, review, *, _writer_locked=False,
                              force_commit=False):
    """正文落盘后才核对并提交 D 的候选；失败保留待处理文件，不重新生成正文。

    ``needs_human_review``/``human_review_required`` 的交接稿只保存候选为
    pending，绝不写入共享记忆或人物档案；人工批准后再用 ``force_commit`` 提交。
    """
    digest = body_digest(content)
    pending_only = not force_commit and isinstance(review, dict) and (
        review.get("review_decision") == "needs_human_review"
        or review.get("human_review_required") is True
    )
    out = {}
    for name in ("memory_library", "character_state"):
        try:
            module = __import__(f"integration.{name}", fromlist=["save_candidates"])
            saved = module.save_candidates(project, chapter, review, body_sha256=digest)
            if pending_only:
                out[name] = {"saved": saved.get("status"), "committed": "pending_review",
                             "added": 0}
                continue
            options = {"_writer_locked": _writer_locked} if name == "character_state" else {}
            committed = module.commit_candidates(project, chapter, digest, **options)
            out[name] = {"saved": saved.get("status"), "committed": committed.get("status"),
                         "added": committed.get("added")}
        except Exception as exc:
            out[name] = {"status": "failed", "error_type": type(exc).__name__}
    return out


def _safe_error(exc):
    from integration import model_roles
    message=str(exc) or type(exc).__name__
    for secret in model_roles.secrets(model_roles.load_config()):message=message.replace(secret,'[redacted]')
    from .failure_info import details
    return {'error_type':type(exc).__name__,'message':message[:1200],**details(exc)}


def effective_revisions(max_revisions, config=None):
    """自动修订轮数以资源策略为准：界面多填也不能超过 revision_rounds（0—3）。"""
    from . import model_roles, resource_policy
    policy = resource_policy.limits(model_roles.load_config() if config is None else config)
    return max(0, min(int(max_revisions), int(policy["revision_rounds"])))


async def _repair_approved_artifacts(project_root: Path, before_chapter: int, executor: Any) -> None:
    """Finish post-save extraction for chapters approved after a handoff.

    Approval itself must stay synchronous/fast; the next generation has an
    executor and can complete memory, entities, RAG and continuity exactly once.
    """
    receipts_path = project_root / ".webnovel" / "writer_receipts.json"
    receipts = strict_json(receipts_path, {})
    if not isinstance(receipts, dict):
        return
    for chapter, _ in sorted(reviewed_chapters(project_root).items()):
        if chapter >= before_chapter:
            continue
        receipt = receipts.get(str(chapter))
        if not isinstance(receipt, dict):
            continue
        review = receipt.get("review") if isinstance(receipt.get("review"), dict) else {}
        if review.get("review_decision") != "human_approved":
            continue
        post = receipt.get("post_save")
        if not isinstance(post, dict) or not post:
            continue
        shared = post.get("shared_memory") if isinstance(post.get("shared_memory"), dict) else {}
        entities = post.get("entities") if isinstance(post.get("entities"), dict) else {}
        needs_sync = (
            post.get("status") in {"pending_approval", "failed"}
            or shared.get("status") in {"pending_approval", "failed"}
            or entities.get("status") in {"pending_approval", "failed"}
            or post.get("rag_indexed") is False
            or post.get("continuity_written") is False
        )
        if not needs_sync:
            continue
        destination = Path(str(receipt.get("destination") or ""))
        try:
            content = destination.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        await _sync_committed_artifacts(executor, chapter, content, receipt, receipts, receipts_path)


async def _generate_and_review(
    project_root: Path,
    chapter_id: int,
    word_count: int,
    max_revisions: int,
    scenes: int = 0,
) -> Dict[str, Any]:
    SkillExecutor, get_ai_service = _load_webnovel_services()
    ai_service = get_ai_service()
    from integration import model_roles, studio
    config=model_roles.load_config()
    max_revisions=effective_revisions(max_revisions,config)
    multi=model_roles.enabled(config)
    if multi:
        studio.recover_plan(project_root)
        ai_service=model_roles.RoleRouter(config,ai_service)
    executor = SkillExecutor(project_root=project_root, ai_service=ai_service)
    await _repair_approved_artifacts(project_root, chapter_id, executor)
    from . import editorial_recovery as editorial
    if multi:
        executor.editorial_review_context = editorial.canonical_context(project_root, chapter_id)
    from integration.length_policy import minimum, body_chars
    from .failure_info import require_polish
    minimum_words = minimum(project_root,chapter_id)
    if minimum_words:
        executor.polish_token_budget = 24000

    async def ensure_length(text):
        if not minimum_words or body_chars(text,chapter_id)>=minimum_words:
            return text
        for _ in range(2):
            result=await executor.execute_polish(chapter_id,text,
                f"本章正文实际{body_chars(text,chapter_id)}字，作者要求不含标题和空白至少{minimum_words}字，目标约{max(word_count,minimum_words)}字。只深化本章已有行动、对话、细节和因果，不写下一章，不重复灌水，输出完整正文。",mode='rewrite')
            text=require_polish(result,'模型 C 字数补写未完成；中间稿保留')
            if body_chars(text,chapter_id)>=minimum_words:return text
        raise RuntimeError('本章字数补写后仍不足，禁止保存与发布')

    async def ensure_counts(text):
        from .text_checks import issues, require
        found=issues(project_root,text)
        if not found:
            return text
        corrected=await executor.execute_polish(chapter_id,text,
            '只修正以下程序可复核的计数错误，不改变故事事件；输出完整正文：'+'；'.join(found),mode='rewrite')
        fixed=await ensure_length(require_polish(corrected,'文字计数纠错失败，中间稿保留'))
        require(project_root,fixed)
        preserve('polished',fixed)
        return fixed
    # The orchestrated path reviews the final B/C body with D below. Do not
    # repeat the legacy B guard or pre-polish review inside the upstream stream.
    executor.external_review_pipeline = multi

    # Unqualified intermediate prose stays outside 正文 and the publishing queue.
    # Bind checkpoints to author requirements, planning, chapter, and word target.
    contract=creative_contract_hash(project_root)
    outline=_find_outline(project_root,chapter_id)
    plan=project_root/'.webnovel'/'story_plan.json'
    plan_hash=hashlib.sha256(plan.read_bytes() if plan.exists() else b'').hexdigest()
    key=hashlib.sha256(json.dumps([chapter_id,word_count,contract,outline,plan_hash],ensure_ascii=False).encode()).hexdigest()
    checkpoint_path=project_root/'.webnovel'/'draft_checkpoints'/f'{chapter_id:04d}-{key}.json'
    checkpoint=strict_json(checkpoint_path,{})
    if not isinstance(checkpoint,dict):raise ValueError('正文中间稿检查点损坏，未覆盖')
    for stage in ('draft','polished'):
        if stage in checkpoint:
            text=checkpoint[stage]
            if not isinstance(text,str) or not text.strip() or checkpoint.get(stage+'_sha256')!=body_digest(text):
                raise ValueError('正文中间稿校验失败，未覆盖')
    def preserve(stage,text):
        checkpoint.update(schema=1,chapter=chapter_id,contract=contract,word_count=word_count,updated_at=now_iso())
        checkpoint[stage]=text
        checkpoint[stage+'_sha256']=body_digest(text)
        atomic_json(checkpoint_path,checkpoint)

    history=checkpoint.get('review_history', [])
    attempts=checkpoint.get('revision_attempts', 0)
    auto_review_count=checkpoint.get('auto_review_count', 0)
    if (not isinstance(history,list) or len(history)>editorial.MAX_CORRECTIONS+4
            or any(not isinstance(item,dict) for item in history)
            or type(attempts) is not int or attempts<0
            or type(auto_review_count) is not int or auto_review_count<0):
        raise ValueError('编辑纠偏检查点损坏，未覆盖')
    if multi and history:
        executor.editorial_review_context=(editorial.canonical_context(project_root,chapter_id)+
            '\n'+editorial.revision_guidance(history,history[-1]))

    def emit_progress(stage_name, label, percent):
        print(
            f"NOVEL_HELPER_PROGRESS:{json.dumps({'stage': stage_name, 'label': label, 'percent': percent, 'chapter': chapter_id}, ensure_ascii=False)}",
            flush=True,
        )

    def remember_review(current):
        if isinstance(current,dict):
            item={'body_sha256':body_digest(content), 'raw_review':str(current.get('raw_review') or '')[:4000],
                  'review_decision':current.get('review_decision')}
            if not history or history[-1]!=item:
                history.append(item)
            checkpoint['review_history']=history[-(editorial.MAX_CORRECTIONS+4):]
            if multi:
                executor.editorial_review_context=(editorial.canonical_context(project_root,chapter_id)+
                    '\n'+editorial.revision_guidance(history,current))
            preserve('polished',content)

    def record_completed_review(current):
        nonlocal auto_review_count
        if isinstance(current, dict) and current.get('success') is True:
            # The count was already reserved and atomically persisted before D
            # was called; never increment here or a crash could refund a review.
            checkpoint['last_reviewed_sha256'] = body_digest(content)
            checkpoint['last_review'] = current
            _record_review_attempt(project_root, chapter_id, content, current)
            remember_review(current)

    def count_existing_review(current):
        """Count a review that arrived with the B stream without ever exceeding the cap."""
        nonlocal auto_review_count
        if isinstance(current, dict) and current.get('success') is True:
            if auto_review_count < MAX_AUTO_REVIEWS:
                auto_review_count += 1
            checkpoint['auto_review_count'] = auto_review_count
            checkpoint['last_reviewed_sha256'] = body_digest(content)
            checkpoint['last_review'] = current

    def capped_handoff(current):
        """Use the review already in hand; never call D just to discover the cap."""
        nonlocal review
        effective = current if (isinstance(current, dict) and current.get('success') is True) else checkpoint.get('last_review')
        if not (isinstance(effective, dict) and effective.get('success') is True):
            from integration.failure_info import ReviewIncomplete
            raise ReviewIncomplete(current, f'第{chapter_id}章自动审查预算已耗尽且未获得有效审查结果，禁止按交接稿保存')
        review = human_handoff_review(effective, body_digest(content), auto_review_count)
        checkpoint['last_reviewed_sha256'] = body_digest(content)
        checkpoint['last_review'] = review
        preserve('polished', content)
        return review

    async def review_with_budget(current, label, percent):
        """The only path allowed to call D for the generated body."""
        nonlocal auto_review_count
        if auto_review_count >= MAX_AUTO_REVIEWS:
            return capped_handoff(current)
        # Reserve the review before calling D and persist the count first: a
        # crash after the model call can only lose the review, never refund it
        # and buy a third call on restart.
        auto_review_count += 1
        checkpoint['auto_review_count'] = auto_review_count
        checkpoint['review_reserved_sha256'] = body_digest(content)
        atomic_json(checkpoint_path, checkpoint)
        emit_progress('D', label, percent)
        current = await executor.execute_review(chapter_id=chapter_id, content=content)
        record_completed_review(current)
        return current

    def make_human_handoff(current):
        studio.reject_sample_copy(project_root, content)
        reason = "zero_revision_budget" if max_revisions == 0 else "auto_review_cap"
        handoff = human_handoff_review(current, body_digest(content), auto_review_count, reason=reason)
        checkpoint['last_reviewed_sha256'] = body_digest(content)
        checkpoint['last_review'] = handoff
        preserve('polished', content)
        return {
            'content': content,
            'review': handoff,
            'reviews': reviews,
            'revision_rounds': checkpoint.get('revision_attempts', 0),
            'executor': executor,
            'human_review_required': True,
        }

    reused='draft' in checkpoint
    if reused:
        print(f'恢复第{chapter_id}章已保存的 B 中间稿（尚未具备发布资格）',flush=True)
        emit_progress('B', f'恢复第{chapter_id}章初稿', 35)
        first={'content':checkpoint['draft'],'review':None}
    elif scenes:
        from . import scene_writer
        emit_progress('B', f'生成第{chapter_id}章场景初稿', 25)
        first = await scene_writer.draft(project_root, chapter_id, word_count, scenes, config=config)
        if not first.get('content'):
            raise RuntimeError('场景生成没有产出可保存的正文')
        preserve('draft', first['content'])
    else:
        emit_progress('B', f'撰写第{chapter_id}章初稿', 25)
        first = await _read_stream_result(executor.execute_write_stream(chapter_id, word_count=word_count))
        if first['errors']:
            from .failure_info import WriteIncomplete
            raise WriteIncomplete({**first.get('failure',{}),'error':'；'.join(first['errors'])},'模型 B 初稿未完成')
        if not first['success'] or not first['content']:raise RuntimeError('AI 写作没有产出可保存的正文')
        preserve('draft',first['content'])
    content=checkpoint.get('polished',first['content'])
    final_title = _unique_chapter_title(project_root, chapter_id, _outline_title(outline, chapter_id))
    def normalize_title(text):
        return _retitle_chapter_heading(text, chapter_id, final_title).strip()
    original_digest = body_digest(content)
    content = normalize_title(content)

    reviews: List[Dict[str, Any]] = []
    review = first.get("review")
    if body_digest(content) != original_digest:
        review = None
    if isinstance(review, dict):
        reviews.append(review)
        if review.get("success") is True:
            count_existing_review(review)
    from . import editorial_release
    if editorial_release.public(config).get('enabled'):
        content,review=await editorial_release.run(project_root,chapter_id,content,executor,config,
            checkpoint,checkpoint_path,minimum_words,normalize_title)
        return {'content':content,'review':review,'reviews':[review],
            'revision_rounds':checkpoint.get('revision_attempts',0),'executor':executor}
    if multi and (config.get("polish_mode","key") == "all" or config.get("polish_mode","key") == "key" and studio.is_key_scene(project_root,chapter_id)):
        if 'polished' in checkpoint:
            content=checkpoint['polished']
            print(f'恢复第{chapter_id}章 C 润色中间稿',flush=True)
        else:
            emit_progress('C', f'模型 C 润色第{chapter_id}章', 50)
            print(f'模型 C 正在润色第{chapter_id}章；B 中间稿已保留',flush=True)
            polished=await executor.execute_polish(chapter_id,content,"优化重点场景的对话和情绪张力，去掉空泛总结、套路句、过密形容词和 AI 腔；不改变事件、人设与伏笔，不扩写下一章。",mode="rewrite")
            content=require_polish(polished,'模型 C 重点章润色未完成；B 中间稿已保留，可继续原批次')
            preserve('polished',content)
        content = normalize_title(content)
        if (
            (max_revisions > 0 or auto_review_count >= MAX_AUTO_REVIEWS)
            and checkpoint.get('last_reviewed_sha256') == body_digest(content)
            and isinstance(checkpoint.get('last_review'), dict)
            and checkpoint['last_review'].get('success') is True
        ):
            review = checkpoint['last_review']
        else:
            review = await review_with_budget(review, f'模型 D 审查第{chapter_id}章', 65)
        reviews.append(review)
    elif reused or multi or review is None:
        content = normalize_title(content)
        if (
            (max_revisions > 0 or auto_review_count >= MAX_AUTO_REVIEWS)
            and 'polished' in checkpoint
            and checkpoint.get('last_reviewed_sha256') == body_digest(content)
            and isinstance(checkpoint.get('last_review'), dict)
            and checkpoint['last_review'].get('success') is True
        ):
            review = checkpoint['last_review']
        else:
            review = await review_with_budget(review, f'模型 D 审查第{chapter_id}章', 65)
        reviews.append(review)

    if minimum_words and body_chars(content,chapter_id)<minimum_words:
        content=normalize_title(await ensure_length(content))
        preserve('polished',content)
        review = await review_with_budget(review, f'模型 D 复审字数补写后的第{chapter_id}章', 65)
        reviews.append(review)
    checked=await ensure_counts(content)
    if body_digest(checked)!=body_digest(content):
        content=normalize_title(checked)
        preserve('polished',content)
        review = await review_with_budget(review, f'模型 D 复审计数纠错后的第{chapter_id}章', 65)
        reviews.append(review)
    if not history and isinstance(review, dict):
        _record_review_attempt(project_root,chapter_id,content,review)
        remember_review(review)

    for revision_round in range(max_revisions + 1):
        if not review_eligible(review,body_digest(content)) and multi and config.get("review_policy")=="e_decides":
            review=await model_roles.authorize_draft(content,review,config,project_root,chapter_id)
            reviews.append(review)
            checkpoint['executor_decision']=review.get('executor_decision') or review.get('executor_authorization')
            preserve('polished',content)
        if review_eligible(review,body_digest(content)):
            studio.reject_sample_copy(project_root,content)
            return {"content":content,"review":review,"reviews":reviews,"revision_rounds":revision_round,"executor":executor}
        if not isinstance(review, dict) or review.get("success") is not True:
            from integration.failure_info import ReviewIncomplete
            raise ReviewIncomplete(review, '审查没有返回可验证结果，已阻止发布')
        decision = review.get("review_decision")
        if review_passed(review):
            studio.reject_sample_copy(project_root,content)
            return {
                "content": content,
                "review": review,
                "reviews": reviews,
                "revision_rounds": revision_round,
                "executor": executor,
            }
        if decision == "needs_human_review" or (decision == "needs_revision" and auto_review_count >= MAX_AUTO_REVIEWS):
            print(f'第{chapter_id}章已自动审查 {auto_review_count} 次，停止继续自动审查并转人工复核',flush=True)
            emit_progress('D', f'第{chapter_id}章转待人工复核', 90)
            return make_human_handoff(review)
        if decision != "needs_revision":
            raise RuntimeError("审查结论不明确，已阻止发布")
        if revision_round >= max_revisions:
            if max_revisions == 0:
                # 资源策略允许 0 轮自动修改：首次未通过就应转人工，而不是
                # 抛出没有 handoff、没有正文的错误。
                emit_progress('D', f'第{chapter_id}章转待人工复核', 90)
                return make_human_handoff(review)
            if max_revisions and attempts < editorial.MAX_CORRECTIONS:
                raise editorial.EditorialReviewPending(chapter_id,max_revisions,checkpoint_path,body_digest(content))
            raise RuntimeError(
                f"第{chapter_id}章在 {max_revisions} 轮自动修改后仍未通过审查"
            )

        if attempts >= editorial.MAX_CORRECTIONS:
            raise RuntimeError(f'第{chapter_id}章累计编辑纠偏已达{editorial.MAX_CORRECTIONS}次上限；保留现稿，需检查事实或规划冲突')
        attempts+=1
        checkpoint['revision_attempts']=attempts
        preserve('polished',content)

        emit_progress('C', f'按审查意见修改第{chapter_id}章（第{attempts}次）', 75)
        suggestions = (editorial.canonical_context(project_root,chapter_id)+'\n' if multi else '')
        suggestions += editorial.revision_guidance(history,review)
        polished = await executor.execute_polish(
            chapter_id,
            content,
            suggestions,
            mode="targeted_fix",
        )
        require_polish(polished,f'第{chapter_id}章自动修改未完成；原稿保留')
        if body_digest(str(polished['content']))==body_digest(content):
            print(f'第{chapter_id}章定点补丁未改变正文，模型 C 改用完整修订，之后仍需 D 重审',flush=True)
            polished=await executor.execute_polish(chapter_id,content,
                suggestions+'\n上一次定点补丁未实际改变正文。本次必须落实上述修订意见，保留未涉及的情节与设定，输出修订后的完整正文；不能仅给建议或原样返回。',mode='rewrite')
            require_polish(polished,f'第{chapter_id}章完整修订未完成；原稿保留')
            if body_digest(str(polished['content']))==body_digest(content):
                raise RuntimeError(f'第{chapter_id}章修订没有产生实际有效修改，已保留中间稿，未提交')
        content = normalize_title(await ensure_counts(await ensure_length(str(polished["content"]).strip())))
        preserve('polished',content)
        review = await review_with_budget(review, f'模型 D 第 {revision_round + 2} 次审查第{chapter_id}章', 85)
        reviews.append(review)

    raise RuntimeError("审查流程异常结束")


async def generate_chapter_async(
    project_path: Path,
    word_count: int = 3500,
    max_revisions: int = 1,
    chapter_id: Optional[int] = None,
    dry_run: bool = False,
    scenes: int = 0,
) -> Dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    if dry_run:
        return await _generate_chapter_locked(root, word_count, max_revisions, chapter_id, True, scenes)
    if not root.is_dir():
        raise FileNotFoundError(f"项目目录不存在：{root}")
    with file_lock(root / ".webnovel" / "writer.lock"):
        return await _generate_chapter_locked(root, word_count, max_revisions, chapter_id, False, scenes)


def _save_progress(project_root: Path, chapter: int) -> None:
    path = project_root / ".webnovel" / "state.json"
    state = strict_json(path, {})
    if not isinstance(state, dict) or not isinstance(state.get("progress", {}), dict):
        raise ValueError("state.json 或 progress 格式无效")
    state["current_chapter"] = max(int(state.get("current_chapter", 0) or 0), chapter)
    progress = state.setdefault("progress", {})
    progress["current_chapter"] = max(int(progress.get("current_chapter", 0) or 0), chapter)
    atomic_json(path, state)


async def _sync_committed_artifacts(
    executor: Any, chapter: int, content: str, receipt: Dict[str, Any],
    receipts: Dict[str, Any], receipts_path: Path,
) -> Dict[str, Any]:
    review = receipt.get("review") if isinstance(receipt.get("review"), dict) else {}
    if review.get("review_decision") == "needs_human_review" and review.get("human_review_required") is True:
        # 交接稿尚未通过审查：只落一个明确的 pending 回执，不提取事实、人物或实体。
        post_save = {
            "status": "pending_review",
            "entities": {"status": "pending_review"},
            "shared_memory": {"status": "pending_review", "reason": "human_review_required"},
            "rag_indexed": False,
            "continuity_written": False,
        }
        receipt["post_save"] = post_save
        try:
            atomic_json(receipts_path, receipts)
        except OSError:
            post_save = {"status": "receipt_update_failed", "result": post_save}
        return post_save
    previous=receipt.get('post_save',{})
    if not isinstance(previous,dict):previous={}
    router=getattr(executor,'ai_service',None)
    routed=type(router).__name__=='RoleRouter'
    operation_scope=lambda:router.stage('E') if routed else nullcontext()
    entities: Dict[str, Any]
    try:
        if previous.get('entities',{}).get('status')=='synced':
            entities={**previous['entities'],'reused':True}
        else:
                with operation_scope(),costs.scope(**({'role':'E'} if routed else {})), (router.without_thinking() if routed else nullcontext()):
                    extraction = await executor._extract_chapter_entities(chapter, content)
                if not isinstance(extraction, dict) or not isinstance(extraction.get("extraction"), dict):
                    entities = {"status": "failed", "reason": "no_valid_extraction"}
                else:
                    summary = await executor._apply_extraction_results(chapter, content, extraction["extraction"])
                    entities = {"status": "synced" if isinstance(summary, dict) and summary.get('success') is True else "failed", "summary": summary}
    except Exception as exc:
        entities = {"status": "failed", **_safe_error(exc)}
    try:
        if previous.get('rag_indexed') is True:
            post_save={**previous,'reused_source_artifacts':True}
            if previous.get('continuity_written') is not True:
                from integration import bridge
                with operation_scope(),costs.scope(**({'role':'E'} if routed else {})):
                    summary=await executor._generate_continuity_summary(chapter,content)
                if str(summary or '').strip():
                    directory=receipts_path.parent.parent/'正文'/'.continuity'
                    directory.mkdir(parents=True,exist_ok=True)
                    bridge._write_text_atomic(directory/f'第{chapter}章_状态.md',summary)
                    post_save['continuity_written']=True
                    post_save.pop('continuity_failure', None)
        else:
            with operation_scope(),costs.scope(**({'role':'E'} if routed else {})):
                post_save = await executor.sync_post_save_artifacts(chapter, content)
    except Exception as exc:
        # Body + review are already committed. A downstream failure never
        # invalidates the body or triggers another chapter on retry.
        post_save = {**previous, "status": "failed", "continuity_failure": _safe_error(exc)}
    if not isinstance(post_save, dict):
        post_save = {"status": "failed", "reason": "invalid_artifact_result"}
    post_save = {**post_save, "entities": entities}
    from integration import memory_library
    facts = (receipt.get("candidates") or {}).get("memory_library") or {}
    if isinstance(facts.get("added"), int) and facts["added"] > 0:
        # D 的候选取代一轮额外的记忆抽取调用：同一份正文，不再花第二次钱。
        post_save["shared_memory"] = {"status": "synced", "source": "d_candidates", "added": facts["added"]}
    else:
        try:
            post_save["shared_memory"] = await memory_library.sync_chapter(receipts_path.parent.parent, chapter, content)
        except Exception as exc:
            # A committed draft is never regenerated because memory extraction failed.
            post_save['shared_memory'] = {'status':'failed',**_safe_error(exc)}
    if (post_save.get("status") == "pending_approval"
            and entities.get("status") == "synced"
            and post_save.get("shared_memory", {}).get("status") == "synced"
            and post_save.get("rag_indexed") is True
            and post_save.get("continuity_written") is True):
        post_save["status"] = "synced"
    receipt["post_save"] = post_save
    receipts[str(chapter)] = receipt
    try:
        atomic_json(receipts_path, receipts)
    except OSError:
        post_save = {"status": "receipt_update_failed", "result": post_save}
    return post_save


@costs.attributed("draft",project="project_path",chapter="chapter_id",role="B")
async def _generate_chapter_locked(
    project_path: Path,
    word_count: int,
    max_revisions: int,
    chapter_id: Optional[int],
    dry_run: bool,
    scenes: int = 0,
) -> Dict[str, Any]:
    project_root = project_path.expanduser().resolve()
    if not project_root.is_dir():
        raise FileNotFoundError(f"项目目录不存在：{project_root}")
    if not (project_root / "正文").is_dir():
        raise FileNotFoundError(f"项目没有找到正文目录：{project_root / '正文'}")
    if type(word_count) is not int or word_count <= 0:
        raise ValueError("word_count 必须大于 0")
    if type(max_revisions) is not int or max_revisions < 0:
        raise ValueError("max_revisions 不能小于 0")

    if chapter_id is not None and (type(chapter_id) is not int or chapter_id <= 0):
        raise ValueError("chapter_id 必须是正整数")
    # Validate state before any AI call or durable chapter write.
    next_id = next_chapter_id(project_root)
    selected_chapter = next_id if chapter_id is None else chapter_id
    # A zero-byte/whitespace body is not a real chapter. Quarantine it and let
    # the normal generation path recreate the chapter instead of FileExistsError.
    if selected_chapter in existing_chapter_ids(project_root):
        empty = [p for p, number in _chapter_files(project_root) if number == selected_chapter]
        if len(empty) == 1:
            try:
                text = empty[0].read_text(encoding="utf-8-sig")
            except OSError:
                text = ""
            if not text.strip():
                original = project_root / ".webnovel" / "originals" / f"empty-{selected_chapter:04d}-{uuid.uuid4().hex}.md"
                original.parent.mkdir(parents=True, exist_ok=True)
                empty[0].replace(original)
    if selected_chapter in existing_chapter_ids(project_root):
        receipt = reviewed_chapters(project_root).get(selected_chapter)
        if receipt and not dry_run:
            _save_progress(project_root, selected_chapter)
            if receipt.get("post_save",{}).get("shared_memory",{}).get("status") != "synced":
                receipts_path = project_root / ".webnovel" / "writer_receipts.json"
                receipts = strict_json(receipts_path,{})
                receipt = receipts[str(selected_chapter)]
                from integration import memory_library
                try:
                    memory_result = await memory_library.sync_chapter(project_root,selected_chapter,Path(receipt["destination"]).read_text(encoding="utf-8-sig"))
                except Exception as exc:
                    memory_result = {'status':'failed',**_safe_error(exc)}
                receipt["post_save"] = {**receipt.get("post_save",{}),"shared_memory":memory_result}
                atomic_json(receipts_path,receipts)
            return {"project": str(project_root), "chapter_id": selected_chapter,
                    "destination": receipt["destination"], "status": "recovered",
                    "review_decision": receipt["review"].get("review_decision"), "review": receipt["review"],
                    "revision_rounds": receipt.get("revision_rounds", 0),
                    "post_save": receipt.get("post_save", {"status": "unknown"})}
        handoff = committed_chapters(project_root).get(selected_chapter)
        if handoff and not dry_run:
            # 正文已写、批次 completed 未更新的崩溃窗口：不要再报 FileExistsError，
            # 让调度器恢复成“待人工复核”，人工批准后即可继续。
            review = handoff.get("review") if isinstance(handoff.get("review"), dict) else {}
            return {"project": str(project_root), "chapter_id": selected_chapter,
                    "destination": handoff["destination"], "status": "needs_human_review",
                    "recovered": True,
                    "review_decision": review.get("review_decision"), "review": review,
                    "human_review_required": True,
                    "revision_rounds": handoff.get("revision_rounds", 0),
                    "post_save": handoff.get("post_save", {"status": "unknown"})}
        raise FileExistsError(
            f"第{selected_chapter}章已经存在，自动写作不会覆盖已有正文：{project_root / '正文'}"
        )
    # Known failures from the new shared-memory path must be repaired before
    # another draft, rather than silently writing with missing historical facts.
    from integration import memory_library
    qualified={} if dry_run else reviewed_chapters(project_root)
    for previous,record in sorted(qualified.items()):
        if previous>=selected_chapter or record.get("post_save",{}).get("shared_memory",{}).get("status")!="failed":continue
        try:
            repaired=await memory_library.sync_chapter(project_root,previous,Path(record["destination"]).read_text(encoding="utf-8-sig"))
        except Exception as exc:
            raise RuntimeError(f"第{previous}章的共享记忆仍未完成；已保留正文，请检查接口后继续原批次或补建记忆") from exc
        records_path=project_root/".webnovel/writer_receipts.json"
        records=strict_json(records_path,{})
        records[str(previous)].setdefault("post_save",{})["shared_memory"]=repaired
        atomic_json(records_path,records)
    outline = _find_outline(project_root, selected_chapter)
    if not outline and not dry_run:
        from integration import model_roles, studio
        cfg = model_roles.load_config()
        has_ai = bool(
            model_roles.enabled(cfg)
            or cfg.get("provider_schema") == 1
            or cfg.get("api_key")
            or os.getenv("AI_API_KEY")
        )
        if has_ai:
            await studio.plan_async(project_root,count=1,start=selected_chapter,locked=True)
            outline=_find_outline(project_root,selected_chapter)
    if not str(outline or "").strip():
        raise RuntimeError(f"未找到第{selected_chapter}章大纲，已阻止自动生成")
    title = _outline_title(outline, selected_chapter)
    title = _unique_chapter_title(project_root, selected_chapter, title)
    destination = _chapter_path(project_root, selected_chapter, title)

    result: Dict[str, Any] = {
        "project": str(project_root),
        "chapter_id": selected_chapter,
        "title": title,
        "destination": str(destination),
        "word_count_target": word_count,
        "max_revisions": max_revisions,
    }
    if dry_run:
        result["status"] = "would_generate"
        return result

    contract_hash = creative_contract_hash(project_root)
    generated = await _generate_and_review(
        project_root,
        selected_chapter,
        word_count,
        max_revisions,
        scenes,
    )
    gen_digest = body_digest(str(generated.get("content", "")).strip())
    gen_review = generated.get("review")
    if not (review_eligible(gen_review, gen_digest, project_root, selected_chapter) or human_review_handoff(gen_review, gen_digest)):
        raise RuntimeError("保存前审查验证失败")
    content = str(generated["content"]).strip()
    normalized = _retitle_chapter_heading(content, selected_chapter, title).strip()
    if body_digest(normalized) != body_digest(content):
        raise RuntimeError('最终标题与已审查正文不一致，保留中间稿，需重新审查')
    content = normalized + "\n"
    from integration.length_policy import require
    require(project_root, content, selected_chapter)
    if not content.strip():
        raise RuntimeError("正文不能为空")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = content.encode("utf-8")
    receipts_path = project_root / ".webnovel" / "writer_receipts.json"
    receipts = strict_json(receipts_path, {})
    if not isinstance(receipts, dict):
        raise ValueError("writer_receipts.json 必须是对象")
    receipt = {"destination": str(destination.resolve()),
               "sha256": hashlib.sha256(payload).hexdigest(),
               "review": generated["review"], "revision_rounds": generated["revision_rounds"],
               "reviewed_at": now_iso()}
    if creative_contract_hash(project_root) != contract_hash:
        raise RuntimeError("生成期间创作约定已改变，未保存正文，请按最新约定重新生成")
    receipt["creative_contract_hash"] = contract_hash
    # 正文的唯一发布入口是版本层：章锁内提交正文与索引，提交成功后才写回执。
    # 回执先写会留下指向未提交正文的记录；先 os.link 再补索引会让生成章在
    # chapter_versions 中缺席。新章用 expect_absent 拒绝并发出现的同名章。
    from . import chapter_editor, chapter_versions
    op_id = f"writer-{selected_chapter}-{uuid.uuid4().hex}"
    with chapter_editor._locked(project_root, selected_chapter):
        if selected_chapter in existing_chapter_ids(project_root):
            raise FileExistsError(f"第{selected_chapter}章在生成期间已被保存")
        # 版本层按标题落盘；用已算好的目标文件名反推标题，避免二次清洗
        # 把正文写到与 destination 不同的文件。
        prefix = f"第{selected_chapter}章-"
        version_title = (destination.name[len(prefix):-3]
                         if destination.name.startswith(prefix)
                         and destination.name.endswith(".md") else "")
        record = chapter_versions.commit_raw_bytes(
            project_root, selected_chapter, payload, title=version_title,
            op_id=op_id, source="writer_runner",
            allow_new=True, expect_absent=True,
            invalidation_reason="chapter_generated")
        if record.get("state") != "committed":
            raise RuntimeError(f"正文版本未提交：{record.get('state')}")
        committed = chapter_versions.chapter_path(project_root, selected_chapter)
        if committed is None or chapter_versions.file_sha256(committed) != receipt["sha256"]:
            raise RuntimeError("正文版本提交后校验失败，回执未写入")
        destination = committed
        receipt["destination"] = str(destination.resolve())
        receipt["version_id"] = record.get("version_id")
        receipt["op_id"] = op_id
        receipts[str(selected_chapter)] = receipt
        atomic_json(receipts_path, receipts)
    result["destination"] = str(destination)
    result["version_id"] = record.get("version_id")
    _save_progress(project_root, selected_chapter)
    candidates = _commit_review_candidates(project_root, selected_chapter, content, generated["review"], _writer_locked=True)
    receipt["candidates"] = candidates
    receipts[str(selected_chapter)] = receipt
    try:
        atomic_json(receipts_path, receipts)
    except OSError:
        pass
    post_save = await _sync_committed_artifacts(
        generated["executor"], selected_chapter, content, receipt, receipts, receipts_path
    )
    result.update(
        {
            "status": "generated",
            "review_decision": generated["review"].get("review_decision"),
            "human_review_required": bool(human_review_handoff(generated["review"], body_digest(content.strip()))),
            "revision_rounds": generated["revision_rounds"],
            "review": generated["review"],
            "post_save": post_save,
            "generated_at": now_iso(),
        }
    )
    return result


async def review_existing_chapter_async(
    project_path: Path, chapter_id: int, max_revisions: int = 0,
) -> Dict[str, Any]:
    """Review one imported/manual chapter without modifying its body.

    A pass commits the same sha-bound receipt/progress/artifact sync as generation.
    Nonzero max_revisions is rejected: this entry point never rewrites user prose.
    """
    if type(chapter_id) is not int or chapter_id <= 0:
        raise ValueError("chapter_id 必须是正整数")
    if type(max_revisions) is not int or max_revisions != 0:
        raise ValueError("现有正文审查仅支持 max_revisions=0，不自动修改原文")
    project = Path(project_path).expanduser().resolve()
    if not project.is_dir() or not (project / "正文").is_dir():
        raise FileNotFoundError("项目或正文目录不存在")
    with file_lock(project / ".webnovel" / "writer.lock"):
        next_chapter_id(project)  # Validate progress before AI or receipts.
        paths = [p for p, i in _chapter_files(project) if i == chapter_id]
        if len(paths) != 1:
            raise ValueError("指定章节必须唯一对应一个正文文件")
        source = paths[0]
        if source.is_symlink() or (project / "正文").resolve() not in source.resolve().parents:
            raise ValueError("不安全的正文路径")
        payload = source.read_bytes()
        content = payload.decode("utf-8-sig")
        if not content.strip():
            raise ValueError("正文不能为空")
        # 待人工复核的回执不得被一次“最终审查”不可逆覆盖；否则新结论若仍是
        # needs_revision，该章会从 committed 消失，复核按钮也一起消失。
        receipts_path = project / ".webnovel" / "writer_receipts.json"
        existing_receipts = strict_json(receipts_path, {})
        previous_receipt = existing_receipts.get(str(chapter_id)) if isinstance(existing_receipts, dict) else {}
        previous_review = previous_receipt.get("review") if isinstance(previous_receipt, dict) else {}
        current_digest = body_digest(content)
        raw_digest = hashlib.sha256(payload).hexdigest()
        same_body = (
            previous_receipt.get("sha256") == raw_digest
            if isinstance(previous_receipt, dict) else False
        ) or (
            isinstance(previous_review, dict)
            and str(previous_review.get("body_sha256") or "").lower() == current_digest
        )
        if (isinstance(previous_review, dict)
                and previous_review.get("review_decision") == "human_approved"
                and same_body):
            raise ValueError("该章已人工批准；如需重新审查，请先修改正文")
        if (isinstance(previous_review, dict)
                and previous_review.get("review_decision") == "needs_human_review"
                and previous_review.get("human_review_required") is True
                and same_body):
            raise ValueError("该章仍在等待人工复核；请先人工批准，或改稿后再重新审查")
        SkillExecutor, get_ai_service = _load_webnovel_services()
        contract_hash = creative_contract_hash(project)
        ai=get_ai_service()
        from integration import model_roles
        config=model_roles.load_config()
        if model_roles.enabled(config):ai=model_roles.RoleRouter(config,ai)
        executor = SkillExecutor(project_root=project, ai_service=ai)
        review = await executor.execute_review(chapter_id=chapter_id, content=content)
        _record_review_attempt(project,chapter_id,content,review)
        if not review_passed(review) and model_roles.enabled(config) and config.get("review_policy")=="e_decides":
            review=await model_roles.authorize_draft(content,review,config,project,chapter_id)
        # UI/manual editors may not use our advisory lock. Bind only the exact
        # bytes reviewed, including checking for newly created duplicate files.
        if source.read_bytes() != payload or [p for p, i in _chapter_files(project) if i == chapter_id] != paths:
            raise RuntimeError("审查期间正文已改变，请重新审查")
        if creative_contract_hash(project) != contract_hash:
            raise RuntimeError("审查期间创作约定已改变，请重新审查")
        receipts_path = project / ".webnovel" / "writer_receipts.json"
        receipts = strict_json(receipts_path, {})
        if not isinstance(receipts, dict):
            raise ValueError("writer_receipts.json 必须是对象")
        receipt = {"destination": str(source.resolve()), "sha256": hashlib.sha256(payload).hexdigest(),
                   "review": review if isinstance(review, dict) else {"success": False},
                   "revision_rounds": 0, "reviewed_at": now_iso()}
        receipt["creative_contract_hash"] = contract_hash
        previous_receipt=receipts.get(str(chapter_id),{})
        if isinstance(previous_receipt,dict) and previous_receipt.get('sha256')==receipt['sha256']:
            receipt['post_save']=previous_receipt.get('post_save',{})
        # A failed fresh review must revoke an earlier pass for the same body,
        # but it must not erase publication facts (published_sha256/staged_at)
        # written by stage/publish (E-01R).  Update only this chapter's review
        # fields under receipts.lock.
        publication_state._update(project, chapter_id, lambda entry: entry.update(receipt))
        receipts = strict_json(receipts_path, {})
        receipt = receipts.get(str(chapter_id), receipt)
        receipt["candidates"] = _commit_review_candidates(project, chapter_id, content, review, _writer_locked=True)
        publication_state._update(project, chapter_id,
                                  lambda entry: entry.update({"candidates": receipt["candidates"]}))
        result = {"project": str(project), "chapter_id": chapter_id, "destination": str(source),
                  "review": receipt["review"], "review_decision": receipt["review"].get("review_decision"),
                  "revision_rounds": 0, "status": "review_failed"}
        if not review_eligible(review,body_digest(content)):
            return result
        _save_progress(project, chapter_id)
        result["post_save"] = await _sync_committed_artifacts(
            executor, chapter_id, content, receipt, receipts, receipts_path
        )
        result["status"] = "authorized" if review.get("review_decision")=="waived_by_E" else "reviewed"
        return result


def review_existing_chapter(
    project_path: Path, chapter_id: int, max_revisions: int = 0,
) -> Dict[str, Any]:
    return asyncio.run(review_existing_chapter_async(project_path, chapter_id, max_revisions))


def generate_chapter(
    project_path: Path,
    word_count: int = 3500,
    max_revisions: int = 1,
    chapter_id: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    return asyncio.run(
        generate_chapter_async(
            project_path,
            word_count=word_count,
            max_revisions=max_revisions,
            chapter_id=chapter_id,
            dry_run=dry_run,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小说助手：AI 生成、审查并保存下一章")
    parser.add_argument("--project", required=True, help="webnovel 项目目录")
    parser.add_argument("--word-count", type=int, default=3500, help="目标字数，默认 3500")
    parser.add_argument("--max-revisions", type=int, default=1, help="最多自动修改轮数，默认 1；最终以资源策略 revision_rounds 封顶")
    parser.add_argument("--chapter", type=int, help="指定章节号；省略时自动取下一章")
    parser.add_argument("--dry-run", action="store_true", help="只检查大纲和目标文件，不调用 AI")
    parser.add_argument("--review-existing", action="store_true", help="仅审查指定的已有正文，不修改原文")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    os.environ.setdefault("NOVEL_HELPER_COST_DB",str(COMBINED_ROOT / "integration_data" / "costs.sqlite3"))
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.review_existing and (args.chapter is None or args.dry_run):
        parser.error("--review-existing 必须提供 --chapter，且不能与 --dry-run 同用")
    try:
        result = review_existing_chapter(Path(args.project), args.chapter) if args.review_existing else generate_chapter(
            Path(args.project),
            word_count=args.word_count,
            max_revisions=args.max_revisions,
            chapter_id=args.chapter,
            dry_run=args.dry_run,
        )
        # 审查原文可能很长，命令行只输出可供调度器记录的元数据。
        result.pop("review", None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get("status") == "review_failed" else 0
    except KeyboardInterrupt:
        print("\n已停止 AI 写作。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"[小说助手] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
