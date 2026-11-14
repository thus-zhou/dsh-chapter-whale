"""Durable, bounded C/D/E revision of an existing unsubmitted chapter."""
import hashlib
import json
from pathlib import Path
from . import writer_runner as writer,bridge,model_roles as roles,editorial_recovery as editorial
from .failure_info import ReviewIncomplete,require_polish
from .length_policy import body_chars
from .text_checks import issues


async def revise(project,chapter,content,source_sha,contract,executor,config,min_words=0,meta=None):
    project=Path(project)
    from . import revision_plan,resource_policy
    strict=meta is not None
    cap=max(1,min(3,int(resource_policy.limits(config).get('revision_rounds') or 1)))
    rounds=0
    if strict:meta.setdefault('mode','targeted_fix')
    if roles.enabled(config):executor.editorial_review_context=editorial.canonical_context(project,chapter)
    identity={'chapter':chapter,'source_sha256':source_sha,'contract':contract,'min_words':min_words}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:20]
    path=project/'.webnovel/draft_checkpoints'/f'revision-{chapter}-{key}.json'
    if path.is_symlink() or path.parent.is_symlink():raise ValueError('修订检查点路径不安全')
    state=writer.strict_json(path,{})
    if not isinstance(state,dict) or state and any(state.get(k)!=v for k,v in identity.items()):raise ValueError('修订检查点损坏，原稿保留')
    state={**identity,**state}
    from . import editorial_release
    if editorial_release.public(config).get('enabled'):
        return await editorial_release.run(project,chapter,state.get('polished') or content,executor,config,state,path,min_words)
    attempts=state.get('revision_attempts',0)
    if type(attempts) is not int or not 0<=attempts<=editorial.MAX_CORRECTIONS:raise ValueError('修订次数记录损坏')
    rewritten=state.get('polished') or content
    if not isinstance(rewritten,str):raise ValueError('修订正文检查点损坏')
    history=state.setdefault('reviews',[])
    if not isinstance(history,list):raise ValueError('修订审查历史损坏')
    def save():
        state.update(revision_attempts=attempts,updated_at=bridge.now_iso())
        writer.atomic_json(path,state)
    base=('保留设定、事件、人物弧线和伏笔，优化对话与重点场景，减少空泛旁白和AI腔。'
          f'本章正文不含标题和空白至少{min_words}字；只深化本章，不写下一章、不重复灌水。')
    need_edit=not state.get('polished')
    # Initial expansion plus at most three editorial corrections per execution.
    # Total corrections persist across restarts and share the original limit.
    for _ in range(4):
        failures=issues(project,rewritten)
        too_short=bool(min_words and body_chars(rewritten,chapter)<min_words)
        if need_edit or failures or too_short:
            if attempts>=editorial.MAX_CORRECTIONS:raise RuntimeError('本章累计编辑纠偏已达上限；保留修订检查点，未提交')
            suggestions=base+'\n'+editorial.canonical_context(project,chapter)
            if failures:suggestions+='\n程序可复核错误：'+'；'.join(failures)
            if too_short:suggestions+=f'\n当前正文仅{body_chars(rewritten,chapter)}字，必须补足有效内容。'
            if state.get('review'):suggestions+='\n'+editorial.revision_guidance(history,state['review'])
            mode=('targeted_fix' if state.get('review',{}).get('review_decision')=='needs_revision'
                  and not too_short and not state.get('force_rewrite') else 'rewrite')
            plan=None
            if state.get('review') and state['review'].get('review_decision')=='needs_revision':
                plan=revision_plan.classify(state['review'])
                if strict:
                    if plan['mode']=='none' and not failures and not too_short:
                        state['phase']='stopped';save()
                        raise revision_plan.RevisionStopped('author_decision_required',
                            '审查提出的问题涉及情节、动机或事实，已保留候选并转作者处理',
                            candidate=rewritten,author_issues=plan['author'])
                    if rounds>=cap:
                        state['phase']='stopped';save()
                        raise revision_plan.RevisionStopped('revision_rounds_exhausted',
                            f'已达到设定的 {cap} 轮修订上限；候选正文已保留',
                            candidate=rewritten,author_issues=plan['author'])
                    if plan['mode']=='targeted_fix' and plan['auto']:
                        suggestions+='\n'+revision_plan.instructions(plan['auto'])
                        mode='targeted_fix'
                    meta['plan']=plan
                rounds+=1
            if state.get('force_rewrite'):suggestions+='\n上次定点补丁未实际修改正文；请修正有效冲突并输出完整改稿，保留其余已修好部分。'
            if strict:meta['mode']=mode
            attempts+=1;state['phase']='editing';save()
            result=await executor.execute_polish(chapter,rewritten,suggestions,mode=mode)
            candidate=require_polish(result,'修订模型未完成；已完成稿件和原文均保留')
            if strict:
                if isinstance(meta,dict) and result.get('patch_report'):meta['patch_report']=result['patch_report']
                check=(revision_plan.check_scope(rewritten,candidate,result.get('patch_report'))
                       if mode=='targeted_fix' else {'ok':True})
                if not check.get('ok'):
                    state['phase']='stopped';save()
                    raise revision_plan.RevisionStopped(check.get('reason','outside_patch'),
                        '补丁超出声明范围或没有实际改动，未提交',
                        author_issues=(plan or {}).get('author',[]))
                length=revision_plan.validate_length(rewritten,candidate,chapter=chapter,mode=mode,min_words=min_words)
                if not length.get('ok'):
                    state['phase']='stopped';save()
                    raise revision_plan.RevisionStopped(length.get('reason','length_policy'),
                        '修订稿未通过长度策略，未提交',candidate=candidate)
            if mode=='targeted_fix' and bridge.body_digest(candidate)==bridge.body_digest(rewritten):
                if strict:
                    state['phase']='stopped';save()
                    raise revision_plan.RevisionStopped('no_change','补丁未改变正文，未再调用审查')
                state.update(force_rewrite=True,phase='needs_revision');save()
                need_edit=True
                continue
            rewritten=candidate;state.pop('force_rewrite',None)
            state.update(polished=rewritten,phase='review')
            state.pop('review',None);state.pop('authorization',None);save()
            if issues(project,rewritten) or min_words and body_chars(rewritten,chapter)<min_words:
                need_edit=True
                continue
        from .studio import reject_sample_copy
        reject_sample_copy(project,rewritten)
        digest=bridge.body_digest(rewritten)
        review=state.get('review')
        if state.get('review_body_sha256')!=digest:
            review=None;state.pop('review',None);state.pop('authorization',None)
        if not review:
            review=await executor.execute_review(chapter,rewritten)
            writer._record_review_attempt(project,chapter,rewritten,review)
            if not isinstance(review,dict) or review.get('success') is not True:
                raise ReviewIncomplete(review,'修订审查未完成；补写稿已保存为检查点')
            state.update(review=review,review_body_sha256=digest);history.append(review);save()
        qualified=review
        if not writer.review_passed(review) and roles.enabled(config) and config.get('review_policy')=='e_decides':
            qualified=state.get('authorization')
            if not qualified:
                qualified=await roles.authorize_draft(rewritten,review,config,project,chapter)
                state['authorization']=qualified;save()
        if bridge.review_eligible(qualified,digest):
            state.update(phase='qualified',qualified_review=qualified);save()
            return rewritten,qualified
        if not min_words and (not roles.enabled(config) or config.get('review_policy')!='e_decides'):
            # Preserve the existing strict manual-polish contract. A
            # later explicit retry rechecks D, but never overwrites its source.
            state.pop('review',None);state.pop('authorization',None);save()
            raise ValueError('润色稿未通过最终审查，原文未改变')
        if review.get('review_decision')!='needs_revision':raise ReviewIncomplete(review,'修订审查结论不明确；补写稿保留')
        # E's 'revise' is an instruction to edit, not a terminal failure.
        need_edit=True;state['phase']='needs_revision';save()
    raise editorial.EditorialReviewPending(chapter,3,path,bridge.body_digest(rewritten))
