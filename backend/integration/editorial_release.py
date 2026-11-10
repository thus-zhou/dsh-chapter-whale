"""Author-approved two-review/third-polish release, distinct from a D pass."""
import hashlib
import json
import re
from pathlib import Path

RULE='two_reviews_third_polish_v1'
MAX_CALLS=12


def public(config):
    value=config.get('editorial_release_rule',{})
    if not isinstance(value,dict):raise ValueError('作者免审规则损坏')
    if not value:return {'enabled':False}
    if type(value.get('enabled')) is not bool:raise ValueError('作者免审规则无效')
    if value.get('enabled') and (value.get('rule_id')!=RULE or value.get('review_count')!=2 or value.get('polish_count')!=3):raise ValueError('作者免审规则版本或次数无效')
    return dict(value)


def _digest(events):
    return hashlib.sha256(json.dumps(events,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def counts(progress):
    reviews=polishes=0
    events=progress.get('events')
    if not isinstance(events,list):raise ValueError('创作轮次记录损坏')
    for index,event in enumerate(events):
        if not isinstance(event,dict):raise ValueError('创作轮次事件损坏')
        if event.get('kind')=='legacy_lower_bound':
            hashes=event.get('reviewed_body_hashes',[])
            if index!=0 or not isinstance(hashes,list) or len(set(hashes))<3 or not all(isinstance(x,str) and re.fullmatch('[a-f0-9]{64}',x) for x in hashes):raise ValueError('历史轮次证据不足')
            reviews+=2;polishes+=2
        elif event.get('status')=='success':
            if not isinstance(event.get('body_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',event['body_sha256']):raise ValueError('轮次正文证据损坏')
            if event.get('kind')=='review':
                result=event.get('result',{})
                if not isinstance(result,dict) or result.get('success') is not True or result.get('review_decision') not in {'pass','needs_revision'}:raise ValueError('未完成审查不能计次')
                reviews+=1
            elif event.get('kind')=='polish':polishes+=1
            else:raise ValueError('未知创作轮次')
    return reviews,polishes


def valid(review,body_sha256):
    from . import model_roles,writer_runner as writer,bridge
    try:
        if not public(model_roles.load_config()).get('enabled'):return False
        auth=review.get('author_rule_authorization',{})
        if not isinstance(auth,dict) or auth.get('approved') is not True or auth.get('policy_id')!=RULE or auth.get('body_sha256')!=body_sha256:return False
        project=Path(auth['project']).resolve();path=Path(auth['checkpoint'])
        if path.is_symlink() or path.parent.is_symlink() or path.resolve().parent!=project/'.webnovel/draft_checkpoints':return False
        state=writer.strict_json(path,{})
        if not isinstance(state,dict):return False
        if state.get('chapter')!=auth.get('chapter'):return False
        progress=state.get('author_rule_progress',{})
        if not isinstance(progress,dict):return False
        if progress.get('phase')!='qualified' or progress.get('qualification')!=review or progress.get('policy_id')!=RULE:return False
        if bridge.body_digest(state.get('polished',''))!=body_sha256:return False
        events=progress.get('events',[]);r,p=counts(progress)
        if r<2 or p<3 or auth.get('review_count')!=r or auth.get('polish_count')!=p or auth.get('events_sha256')!=_digest(events):return False
        successful=[e for e in events if e.get('status')=='success' or e.get('kind')=='legacy_lower_bound']
        return bool(successful and successful[-1].get('kind')=='polish' and successful[-1].get('body_sha256')==body_sha256)
    except (ValueError,OSError,KeyError,TypeError):return False


async def run(project,chapter,content,executor,config,state,path,min_words=0,normalize=None):
    from . import bridge,writer_runner as writer,editorial_recovery as editorial
    from .failure_info import require_polish,ReviewIncomplete,ExecutorStopped
    from .length_policy import body_chars
    from .text_checks import issues
    from .studio import reject_sample_copy
    if not public(config).get('enabled'):raise ValueError('作者免审规则未启用')
    project=Path(project).resolve();path=Path(path)
    if path.is_symlink() or path.parent.is_symlink():raise ValueError('免审检查点路径不安全')
    path=path.resolve()
    if path.parent!=project/'.webnovel/draft_checkpoints':raise ValueError('免审检查点路径不安全')
    normalize=normalize or (lambda value:value.strip())
    content=normalize(content)
    progress=state.get('author_rule_progress')
    if progress is None:
        events=[]
        history=state.get('review_history',[])
        hashes=list(dict.fromkeys(item.get('body_sha256') for item in history if isinstance(item,dict)
            and item.get('review_decision') in {'pass','needs_revision'} and isinstance(item.get('body_sha256'),str)
            and re.fullmatch('[a-f0-9]{64}',item['body_sha256'])))
        if len(hashes)>=3 and type(state.get('revision_attempts')) is int and state['revision_attempts']>=2:
            # Three distinct, completed D-reviewed candidates prove at least
            # two completed edits in this same contract-bound checkpoint.
            events.append({'kind':'legacy_lower_bound','reviewed_body_hashes':hashes,'source_revision_attempts':state['revision_attempts'],
                'note':'conservative lower bound; full old history and counters retained'})
        progress={'policy_id':RULE,'events':events,'phase':'polish','candidate_sha256':bridge.body_digest(content)}
        state['author_rule_progress']=progress
    if not isinstance(progress,dict) or progress.get('policy_id')!=RULE:raise ValueError('免审轮次状态损坏')
    counts(progress)
    if progress.get('candidate_sha256')!=bridge.body_digest(content):raise ValueError('候选正文已改变，不能复用免审轮次资格')
    def save():
        state.update(chapter=chapter,polished=content,polished_sha256=bridge.body_digest(content),updated_at=bridge.now_iso())
        progress['candidate_sha256']=bridge.body_digest(content);writer.atomic_json(path,state)
    def clean():
        return not issues(project,content) and (not min_words or body_chars(content,chapter)>=min_words)
    def finish(review):
        reject_sample_copy(project,content)
        progress.update(phase='qualified',qualification=review);save()
        return content,review
    if progress.get('explicit_stop'):raise ExecutorStopped(progress['explicit_stop'])
    if progress.get('phase')=='qualified':
        result=progress.get('qualification',{})
        if clean() and bridge.review_eligible(result,bridge.body_digest(content)):return content,result
        raise ValueError('当前作者规则资格已失效，未发布')
    history=state.get('review_history') or state.get('reviews') or []
    latest=next((e['result'] for e in reversed(progress['events']) if e.get('kind')=='review' and e.get('status')=='success'),history[-1] if history else {})
    save()
    while True:
        reviews,polishes=counts(progress)
        if progress.get('phase')=='post_polish':
            if not clean():progress['phase']='polish';save();continue
            if reviews>=2 and polishes>=3:
                review={'success':False,'review_decision':'waived_by_author_rule','needs_revision':None,
                    'raw_review':'按作者规则：已完成两次审查及第三次润色，不再D复审；不代表D审查通过。',
                    'author_rule_authorization':{'approved':True,'policy_id':RULE,'project':str(project),'chapter':chapter,'checkpoint':str(path),
                        'body_sha256':bridge.body_digest(content),'review_count':reviews,'polish_count':polishes,'events_sha256':_digest(progress['events'])}}
                return finish(review)
            progress['phase']='review';save()
        if progress.get('phase')=='polish':
            attempts=sum(e.get('kind')=='polish' for e in progress['events'])
            if attempts>=MAX_CALLS:raise RuntimeError('作者规则润色未完成，保留检查点；未获得免审资格')
            suggestions=(editorial.canonical_context(project,chapter)+'\n保留本章已修好的部分，完成当前有效修订，不写下一章、不灌水。'
                + (f'正文不含标题和空白至少{min_words}字。' if min_words else '')
                + '\n'+editorial.revision_guidance(history,latest))
            found=issues(project,content)
            if found:suggestions+='\n程序可复核问题：'+'；'.join(found)
            if min_words and body_chars(content,chapter)<min_words:suggestions+=f'\n当前仅{body_chars(content,chapter)}字，需要补足有效内容。'
            mode='targeted_fix' if polishes and clean() and not progress.get('force_rewrite') else 'rewrite'
            if progress.get('force_rewrite'):suggestions+='\n上次补丁未实际修改正文，请输出落实有效修订的完整改稿。'
            event={'kind':'polish','status':'pending','started_at':bridge.now_iso(),'input_sha256':bridge.body_digest(content),'mode':mode}
            progress['events'].append(event)
            state['revision_attempts']=state.get('revision_attempts',0)+1;save()
            try:result=await executor.execute_polish(chapter,content,suggestions,mode=mode);candidate=normalize(require_polish(result,'润色未成功，不能按作者规则免审'))
            except Exception:
                event['status']='failed';save();raise
            if bridge.body_digest(candidate)==bridge.body_digest(content) and polishes:
                event['status']='no_change';progress['force_rewrite']=True;save();continue
            content=candidate;event.update(status='success',body_sha256=bridge.body_digest(content),finished_at=bridge.now_iso())
            progress.pop('force_rewrite',None);state.pop('review',None);state.pop('authorization',None)
            progress['phase']='post_polish';save();continue
        if progress.get('phase')!='review':raise ValueError('创作轮次阶段不明确')
        event={'kind':'review','status':'pending','body_sha256':bridge.body_digest(content),'started_at':bridge.now_iso()}
        progress['events'].append(event);save()
        try:review=await executor.execute_review(chapter,content)
        except Exception:
            event['status']='failed';save();raise
        writer._record_review_attempt(project,chapter,content,review)
        if not isinstance(review,dict) or review.get('success') is not True or review.get('review_decision') not in {'pass','needs_revision'}:
            event['status']='failed';save();raise ReviewIncomplete(review,'D审查未完成，不计入两次有效审查')
        event.update(status='success',result=review,finished_at=bridge.now_iso());latest=review
        if writer.review_passed(review) and clean():return finish(review)
        progress['phase']='polish';save()
