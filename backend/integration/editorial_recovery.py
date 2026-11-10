"""Bounded, source-aware editing; never authorizes a platform submission."""
import hashlib
from pathlib import Path

MAX_CORRECTIONS = 9
MAX_RECOVERIES = 2
# Independently bounded blocks fit both C prompt paths without a second,
# whole-message cut dropping facts from between the retained head and tail.
SOURCE_CHARS = 6000
HISTORY_CHARS = 1200
LATEST_REVIEW_CHARS = 4000


class EditorialReviewPending(RuntimeError):
    def __init__(self, chapter, rounds, checkpoint, digest):
        super().__init__(f'第{chapter}章在 {rounds} 轮自动修改后仍未通过审查；保留现稿，等待有界编辑纠偏')
        self.chapter = chapter
        self.checkpoint = Path(checkpoint)
        self.digest = digest


def canonical_context(project, chapter):
    from .writer_runner import _chapter_files
    parts = ['【编辑纠偏规则】已保存前章原文中的已发生事实优先于未来大纲；不能为迁就大纲改写前章。'
             '若大纲与前章冲突，以前章原文为准，说明规划偏差，不把正确承接当成正文错误。'
             '当前章必须保留既定核心动作、物证新旧层次与人物能力；不新增规则或抢写后章。'
             '历轮意见仅是待核对清单，已修好的不要再改；有原文反证的意见不可机械采纳。']
    parts.append(length_context(project,chapter))
    for path, number in _chapter_files(Path(project)):
        if chapter - 2 <= number < chapter:
            raw = path.read_bytes()
            text = raw.decode('utf-8-sig')
            # A bounded excerpt is explicitly labelled, never described as full coverage.
            shown = text if len(text) <= SOURCE_CHARS else text[:2800] + '\n【中段省略】\n' + text[-3200:]
            parts.append(f'【第{number}章已保存原文参考 SHA256={hashlib.sha256(raw).hexdigest()}】\n{shown}')
    return '\n\n'.join(parts)


def length_context(project,chapter):
    from .length_policy import minimum
    limit=minimum(project,chapter)
    return (f'【当前作者字数要求】第{chapter}章正文不含标题和空白至少{limit}字。'
            '这是当前生效的作者指令，优先于旧模板、大纲、记忆中4000字等冲突篇幅上限；'
            '不得为了旧上限删短正文。只核验实际内容质量、事实与本章边界，不因超过旧字数上限否决。') if limit else ''


def revision_guidance(history, latest):
    older = [str(item.get('raw_review', ''))[:HISTORY_CHARS] for item in history[:-1]]
    return ('保留已修好的部分，按最新意见定点修改；不要整章重排或重新发明细节。'
            '\n【历轮防回归清单（需核对，不代表仍有错误）】\n' + '\n'.join(older[-8:]) +
            '\n【本轮需要解决的问题】\n' + str(latest.get('raw_review') or '修正有效审查问题')[:LATEST_REVIEW_CHARS])


def can_retry(exc, project, chapter):
    from .writer_runner import strict_json, body_digest
    if not isinstance(exc, EditorialReviewPending) or exc.chapter != chapter:
        return False
    folder = Path(project).resolve() / '.webnovel' / 'draft_checkpoints'
    if exc.checkpoint.resolve().parent != folder or exc.checkpoint.is_symlink():
        return False
    try:
        saved = strict_json(exc.checkpoint, {})
    except (ValueError, OSError):
        return False
    if not isinstance(saved,dict):
        return False
    text = saved.get('polished') or saved.get('draft')
    attempts = saved.get('revision_attempts', 0)
    return (saved.get('chapter') == chapter and isinstance(text, str) and bool(text.strip())
            and body_digest(text) == exc.digest and type(attempts) is int
            and 0 <= attempts < MAX_CORRECTIONS)
