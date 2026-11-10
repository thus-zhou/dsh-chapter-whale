"""Author-controlled minimum body length; titles and whitespace do not count."""
import json
import re
from pathlib import Path


def minimum(project,chapter=None):
    path = Path(project)/'.webnovel'/'publication_policy.json'
    if not path.exists():
        return 0
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    limit = value.get('min_body_chars') if isinstance(value, dict) else None
    if type(limit) is not int or not 1 <= limit <= 10000:
        raise ValueError('发布字数策略损坏，禁止发布')
    overrides=value.get('chapter_overrides',{})
    if not isinstance(overrides,dict):raise ValueError('章数字数策略损坏，禁止发布')
    if chapter is not None and str(chapter) in overrides:
        item=overrides[str(chapter)]
        limit=item.get('min_body_chars') if isinstance(item,dict) else None
        if type(limit) is not int or not 1<=limit<=10000:raise ValueError('章数字数策略损坏，禁止发布')
    return limit


def body_chars(text, chapter):
    from .bridge import markdown_to_plaintext
    return len(re.sub(r'\s+', '', markdown_to_plaintext(text, chapter)))


def require(project, text, chapter):
    from .text_checks import require as require_counts
    require_counts(project, text)
    limit = minimum(project,chapter)
    actual = body_chars(text, chapter)
    if actual < limit:
        raise ValueError(f'第{chapter}章正文{actual}字，少于最低{limit}字，禁止发布')
    return actual
