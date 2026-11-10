"""Small deterministic checks. Never treat a model's arithmetic as evidence."""
import re
import unicodedata

NUMBERS = {'一':1, '二':2, '两':2, '三':3, '四':4, '五':5, '六':6, '七':7, '八':8, '九':9, '十':10}
LITERAL = re.compile(r'''[“「『'\"]([^“”「」『』'\"\n]{1,40})[”」』'\"]\s*([一二两三四五六七八九十]|\d{1,2})个?字''')


def count(text):
    return sum(unicodedata.category(c)[0] in {'L','N'} for c in text)


def literal_issues(text):
    result=[]
    for match in LITERAL.finditer(text):
        literal, written = match.groups()
        stated = NUMBERS[written] if written in NUMBERS else int(written)
        actual = count(literal)
        if stated != actual:
            result.append({'literal':literal, 'stated':stated, 'actual':actual,
                           'start':match.start(2), 'end':match.end(2)})
    return result


def memory_display(text):
    """Display a derived arithmetic correction; preserve source-bound originals."""
    issues=literal_issues(text)
    for issue in reversed(issues):
        text=text[:issue['start']]+str(issue['actual'])+text[issue['end']:]
    return text + ('（字数由程序校对；来源原文及原始记录未改写）' if issues else '')


def guidance(project, doc=None, chapter=None):
    # This quotation is already in this book's source-bound memory. Do not
    # introduce another book's characters/plot, or turn an author plan into fact.
    from . import memory_library
    doc=memory_library.read(project) if doc is None else doc
    cache={}
    if any('别接第三次' in item.get('content','') and item.get('status')=='active'
           and (chapter is None or not item['source'].get('chapter') or item['source']['chapter']<chapter)
           and memory_library.freshness(project,item,cache)!='stale' for item in doc['items']):
        return '【程序可复核纠错】“别接第三次”不含引号和标点是5个字。旧章/旧记忆所称“四个字”是计数错误，不能为追求前文一致而沿用。'
    return ''


def issues(project, text):
    problems=[f'引用“{i["literal"]}”实际{i["actual"]}字，不是{i["stated"]}字' for i in literal_issues(text)]
    # Indirect references ("another photo's four words") are semantic, not a
    # provable literal-count error. Never hard-block them by keyword alone.
    return problems


def require(project, text):
    found=issues(project,text)
    if found:
        raise ValueError('确定性文字计数校验未通过：'+'；'.join(found[:5]))
