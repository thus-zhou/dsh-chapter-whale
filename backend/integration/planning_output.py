"""Durable planning responses and one bounded, restart-safe schema correction."""
import hashlib
import json
import re
from pathlib import Path
from . import bridge,writer_runner as writer,model_roles


class PlanningOutputInvalid(ValueError):
    retryable=False
    failure_kind='model_output'
    def __init__(self,code):
        self.error_code=code
        super().__init__('模型A规划字段校验失败：'+code+'；原规划输出和纠偏记录已保留，未覆盖已有章节')


def schema_error(value,ids):
    if not isinstance(value,dict):return 'planning_not_object'
    chapters=value.get('chapters')
    if not isinstance(chapters,list) or [c.get('id') if isinstance(c,dict) else None for c in chapters]!=ids or any(type(c.get('id')) is not int for c in chapters):return 'planning_chapter_ids_invalid'
    for item in chapters:
        title=item.get('title');outline=item.get('outline')
        if not isinstance(title,str) or not title.strip() or len(title)>60 or any(x in title for x in '\r\n'):return 'planning_chapter_title_invalid'
        if not isinstance(outline,str) or not outline.strip() or len(outline)>8000:return 'planning_chapter_outline_invalid'
        if type(item.get('key_scene')) is not bool:return 'planning_key_scene_invalid'
        if re.search(r'(?m)^\s*(?:#+\s*)?第\s*\d+\s*章',outline):return 'planning_nested_heading'
    for field in ['master_outline','volumes','character_arcs','foreshadowing']:
        if not isinstance(value.get(field),str) or not value[field].strip() or len(value[field])>12000:return 'planning_'+field+'_invalid'
    return None


def _safe(value):
    try:
        text=json.dumps(value,ensure_ascii=False)
        if len(text)>2*1024*1024:raise ValueError('large result')
        for secret in model_roles.secrets(model_roles.load_config()):
            if len(secret)>=8:text=text.replace(secret,'[redacted]')
        text=re.sub(r'\bsk-[A-Za-z0-9_-]{8,}','[redacted]',text)
        return json.loads(text)
    except Exception:raise PlanningOutputInvalid('planning_checkpoint_redaction_failed') from None


async def validated_call(project,ids,prompt,call,max_tokens):
    project=Path(project).resolve()
    key=hashlib.sha256(json.dumps([ids,prompt],ensure_ascii=False).encode()).hexdigest()[:20]
    path=project/'.webnovel/planning_checkpoints'/f'{ids[0]:04d}-{ids[-1]:04d}-{key}.json'
    if path.is_symlink() or path.parent.is_symlink():raise PlanningOutputInvalid('planning_checkpoint_path_invalid')
    state=writer.strict_json(path,{})
    if not isinstance(state,dict):raise PlanningOutputInvalid('planning_checkpoint_invalid')
    if state and (state.get('ids')!=ids or state.get('context_sha256')!=key):raise PlanningOutputInvalid('planning_checkpoint_identity_invalid')
    state={**state,'schema':1,'ids':ids,'context_sha256':key}
    def save():
        state['updated_at']=bridge.now_iso();writer.atomic_json(path,state)
    async def request(text):
        try:
            try:return await call(text,max_tokens=max_tokens,timeout=600,response_format='json_object')
            except ValueError as exc:
                if not str(exc).startswith('模型 A 达到输出 Token 上限') or max_tokens>=32000:raise
                return await call(text,max_tokens=32000,timeout=600,response_format='json_object')
        except Exception as exc:
            from .failure_info import details
            # Never persist str(exc), response bodies, prompts or credentials.
            failure={'at':bridge.now_iso(),**details(exc)}
            kind=type(exc).__name__
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}',kind):failure['exception_type']=kind
            state.update(phase='request_failed',last_failure=failure,
                         request_failures=[*state.get('request_failures',[])[-9:],failure])
            save()
            raise
    if 'response' not in state:
        state['phase']='requesting';save()
        state['response']=_safe(await request(prompt));state['phase']='received';save()
    value=state['response'];error=schema_error(value,ids)
    if not error:
        state['phase']='validated';save();return value
    if state.get('phase')=='schema_invalid_final':raise PlanningOutputInvalid(state.get('schema_error',error))
    state.setdefault('original_response',value)
    state.update(schema_error=error,schema_repair_used=True,phase='schema_repair_pending');save()
    fix=(prompt+'\n本次结构字段不合格，错误码='+error+'。只纠正JSON结构和字段，不更换既有故事方向。'
        +'所有章节id必须依次严格为'+json.dumps(ids)+'；key_scene必须为JSON布尔true/false；四个总规划字段必须非空文本；outline不嵌入章节标题。'
        +'\n待纠正输出：'+json.dumps(value,ensure_ascii=False))
    # A transport interruption may retry this same pending correction through
    # the caller's shared recovery budget, but never gets a second bad response.
    fixed=_safe(await request(fix));state['response']=fixed
    error=schema_error(fixed,ids)
    state.update(phase='schema_invalid_final' if error else 'validated',schema_error=error);save()
    if error:raise PlanningOutputInvalid(error)
    return fixed
