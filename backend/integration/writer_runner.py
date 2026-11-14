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


def reviewed_chapters(project_root: Path) -> Dict[int, Dict[str, Any]]:
    """Return only receipts bound to the exact, uniquely named saved body."""
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
        if len(paths) != 1 or not review_eligible(receipt.get("review"),body_digest(paths[0].read_text(encoding="utf-8-sig")),project_root,chapter):
            continue
        path = paths[0]
        if (receipt.get("destination") == str(path.resolve())
                and receipt.get("sha256") == hashlib.sha256(path.read_bytes()).hexdigest()
                and qualification_contract_matches(project_root,chapter,receipt,contract_hash)):
            result[chapter] = receipt
    return result


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


def _find_outline(project_root: Path, chapter: int) -> str:
    # Local, read-only lookup makes --dry-run independent of AI initialization.
    header = re.compile(r"^(?:#+\s*)?(?:[-*]\s+)?(?:\*\*|__)?\s*(?:第\s*0*(\d+)\s*章|0*(\d+)\s*\.\s*(?:《|\s))")
    for path in sorted((project_root / "大纲").glob("*.md")):
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        start = None
        for i, line in enumerate(lines):
            match = header.match(line.strip())
            if match:
                if start is not None:
                    return "\n".join(lines[start:i]).strip()
                if int(match.group(1) or match.group(2)) == chapter:
                    start = i
        if start is not None:
            return "\n".join(lines[start:]).strip()
    return ""


def _outline_title(outline: str, chapter_id: int) -> str:
    for raw_line in str(outline or "").splitlines():
        line = raw_line.strip().lstrip("#").strip().replace("**", "").replace("__", "")
        match = re.search(
            rf"第\s*0*{chapter_id}\s*章(?:[：:\-—–_\s]+(.+?))?(?:\s*)$",
            line,
        )
        if match:
            title = (match.group(1) or "").strip(" -—–_：:　")
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


def _commit_review_candidates(project, chapter, content, review):
    """正文落盘后才核对并提交 D 的候选；失败保留待处理文件，不重新生成正文。"""
    raw = hashlib.sha256(content.encode("utf-8")).hexdigest()
    out = {}
    for name in ("memory_library", "character_state"):
        try:
            module = __import__(f"integration.{name}", fromlist=["save_candidates"])
            saved = module.save_candidates(project, chapter, review, raw_sha256=raw)
            committed = module.commit_candidates(project, chapter, raw)
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
    if (not isinstance(history,list) or len(history)>editorial.MAX_CORRECTIONS+4
            or any(not isinstance(item,dict) for item in history)
            or type(attempts) is not int or attempts<0):
        raise ValueError('编辑纠偏检查点损坏，未覆盖')
    if multi and history:
        executor.editorial_review_context=(editorial.canonical_context(project_root,chapter_id)+
            '\n'+editorial.revision_guidance(history,history[-1]))

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

    reused='draft' in checkpoint
    if reused:
        print(f'恢复第{chapter_id}章已保存的 B 中间稿（尚未具备发布资格）',flush=True)
        first={'content':checkpoint['draft'],'review':None}
    elif scenes:
        from . import scene_writer
        first = await scene_writer.draft(project_root, chapter_id, word_count, scenes, config=config)
        if not first.get('content'):
            raise RuntimeError('场景生成没有产出可保存的正文')
        preserve('draft', first['content'])
    else:
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
    from . import editorial_release
    if editorial_release.public(config).get('enabled'):
        content,review=await editorial_release.run(project_root,chapter_id,content,executor,config,
            checkpoint,checkpoint_path,minimum_words,normalize_title)
        return {'content':content,'review':review,'reviews':[review],
            'revision_rounds':checkpoint.get('revision_attempts',0),'executor':executor}
    if multi and (config.get("polish_mode","key") == "all" or config.get("polish_mode","key") == "key" and studio.is_key_scene(project_root,chapter_id)):
        if 'polished' in checkpoint:
            content=checkpoint['polished']
            print(f'恢复第{chapter_id}章 C 润色中间稿，重新进行当前审查',flush=True)
        else:
            print(f'模型 C 正在润色第{chapter_id}章；B 中间稿已保留',flush=True)
            polished=await executor.execute_polish(chapter_id,content,"优化重点场景的对话和情绪张力，去掉空泛总结、套路句、过密形容词和 AI 腔；不改变事件、人设与伏笔，不扩写下一章。",mode="rewrite")
            content=require_polish(polished,'模型 C 重点章润色未完成；B 中间稿已保留，可继续原批次')
            preserve('polished',content)
        content = normalize_title(content)
        review=await executor.execute_review(chapter_id,content)
        reviews.append(review)
    elif reused or multi or review is None:
        content = normalize_title(content)
        review=await executor.execute_review(chapter_id,content)
        reviews.append(review)

    if minimum_words and body_chars(content,chapter_id)<minimum_words:
        content=await ensure_length(content)
        preserve('polished',content)
        review=await executor.execute_review(chapter_id,content)
        reviews.append(review)
    checked=await ensure_counts(content)
    if body_digest(checked)!=body_digest(content):
        content=checked
        review=await executor.execute_review(chapter_id,content)
        reviews.append(review)
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
        if decision != "needs_revision":
            raise RuntimeError("审查结论不明确，已阻止发布")
        if revision_round >= max_revisions:
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
        review = await executor.execute_review(chapter_id=chapter_id, content=content)
        _record_review_attempt(project_root,chapter_id,content,review)
        remember_review(review)
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
        entities = {"status": "failed", "error_type": type(exc).__name__}
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
    receipt["post_save"] = post_save
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
        if model_roles.enabled():
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
    if not review_eligible(generated.get("review"),body_digest(str(generated.get("content","")).strip()),project_root,selected_chapter):
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
    if selected_chapter in existing_chapter_ids(project_root):
        raise FileExistsError(f"第{selected_chapter}章在生成期间已被保存")
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
    receipts[str(selected_chapter)] = receipt
    # Receipt first, then a fully written body published without replacement.
    # A crash at either boundary leaves recoverable evidence, never half a body.
    atomic_json(receipts_path, receipts)
    fd, name = tempfile.mkstemp(prefix=".writer-", suffix=".tmp", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    _save_progress(project_root, selected_chapter)
    candidates = _commit_review_candidates(project_root, selected_chapter, content, generated["review"])
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
        # A failed fresh review must revoke an earlier pass for the same body.
        receipt["candidates"] = _commit_review_candidates(project, chapter_id, content, review)
        receipts[str(chapter_id)] = receipt
        atomic_json(receipts_path, receipts)
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
