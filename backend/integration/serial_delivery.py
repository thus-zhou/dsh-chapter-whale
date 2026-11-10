"""One qualified chapter per isolated step, with durable publication intent."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import uuid
import hashlib
from pathlib import Path
from . import bridge, model_roles, scheduler as s, writer_runner as writer

BACKOFF_SECONDS = (60, 300, 900)


def recoverable_before_submit(job, chapter):
    """Whether a durable journal proves the submit click was never sent.

    `publish.py` writes `state="submitting"` together with `submitted_at`
    immediately *before* clicking 提交, so any journal that is still in
    `preparing` / `blocked_before_submit` and has no `submitted_at` proves the
    click never happened.  The reason code is diagnostic only and must not
    decide retryability (an `automation_error` before submit is just as safe
    to retry as an `editor_readback_mismatch`).
    """
    from fanqie_auto_publish.publish import parse_chapter
    from fanqie_auto_publish.publication_safety import journal_path, read_json_strict
    try:
        bridge.validate_queue_origin(job['book'],project=Path(job['project']),account=job['account'])
        _,_,folder=bridge.find_queue_book(job['book'])
        queued=bridge.queued_chapters(folder)
        if sorted(queued)[:1]!=[chapter]:return None
        source=queued[chapter]
        parsed=parse_chapter(source)
        entry=read_json_strict(journal_path(source))
        from fanqie_auto_publish.publication_safety import requires_reconciliation
        if requires_reconciliation(entry):return None
        if not isinstance(entry,dict):return None
        if (entry.get('state') not in {'preparing','blocked_before_submit'} or entry.get('submitted_at')
            or any(entry.get(k)!=v for k,v in {'book':job['book'],'account':job['account'],
                **{k:parsed[k] for k in ('chapter_id','title','body_sha256','file_sha256')}}.items())):
            return None
        reason = str(entry.get('reason') or 'unsubmitted')
        if any(token in reason for token in ('login','account','identity','ambiguous','conflict','rejected','blocker','captcha','unexpected','declaration','unconfirmed','route_changed','route_missing')):
            return None
        if reason=='automation_error' and entry.get('error_type') not in {'TimeoutError','ConnectionError','ClientConnectionError'}:
            return None
        return reason
    except (ValueError,RuntimeError,OSError,KeyError,TypeError):
        return None


def safe_message(exc):
    value = str(exc) or type(exc).__name__
    for secret in model_roles.secrets(model_roles.load_config()):
        value = value.replace(secret, '[redacted]')
    return value[:2000]


def transient_generation_error(exc):
    chain = []
    current = exc
    for _ in range(8):
        if current is None:
            break
        chain.append(str(current).casefold())
        current = current.__cause__ or current.__context__
    value = ' '.join(chain)
    blocked = ('401', '403', 'insufficient_quota', 'invalid_api_key', '余额', '额度', '密钥',
               '验证码', '风控', '账号', '冲突', '哈希', '未通过', '未确认', '已提交', '授权', '暂停')
    if any(word in value for word in blocked):
        return False
    return any(word in value for word in ('timeout', 'timed out', '超时', '429', '502', '503', '504',
               'connection', '连接中断', '未返回有效', '完整有效的 json', 'stream error', '章节编号或数量不符合请求', '记忆同步未完成', '共享记忆仍未完成', '记忆内容为空或超过长度限制'))


def alert(job_id, chapter, message, state):
    root = s.RUNS_ROOT.parent / 'alerts'
    bridge.write_json_atomic(root / f'{bridge.safe_dir_name(job_id)}-{chapter}.json', {
        'job_id': job_id, 'chapter_id': chapter, 'state': state,
        'message': message, 'updated_at': bridge.now_iso(),
    })


def step(job_id, job, cycle, record, force=False):
    """Caller owns global and book locks and has frozen the full daily target set."""
    project = Path(job['project'])
    book, account = job['book'], job['account']
    targets = cycle['target_ids']
    if job.get('daily_word_goals',{}).get(cycle['run_date']):
        cycle['word_goal_target']=job['daily_word_goals'][cycle['run_date']]
    chapter = None
    verification_conflict=False
    def expired():
        return cycle.get('word_goal_supplement') and s._job_today(job)!=cycle['run_date']
    def close_expired():
        cycle.update(status='success',closed_without_publication=True,completion_reason='word_goal_date_expired')
        s._update_run(job_id,{'cycle':cycle,'last_status':'expired','last_message':'当天补量已到期；正文与证据保留，未继续提交'})
        record.update(status='expired',finished_at=bridge.now_iso(),closed_without_publication=True)
        record['run_record']=s._write_run_record(job_id,record)
        return record
    try:
        from fanqie_auto_publish.publication_safety import requires_reconciliation
        if requires_reconciliation(cycle.get('recovery', {})) and cycle.get('current_chapter'):
            cycle['stage'] = 'publish_started'
            cycle.setdefault('publish_attempt', {'chapter_id': cycle['current_chapter']})
        # Even an expired supplement must reconcile a previous remote attempt.
        if expired() and cycle.get('stage') != 'publish_started':return close_expired()
        receipts = writer.reviewed_chapters(project)
        archive = s._verified_archive(book, receipts, account)
        remaining = [number for number in targets if number not in archive]
        if cycle.get('stage')=='publish_started' and cycle.get('publish_attempt',{}).get('chapter_id') in archive:
            verification_conflict=True # Validation itself can raise; fail closed then, too.
            chapter=cycle['publish_attempt']['chapter_id']
            if chapter not in targets or chapter in s._verify_queue(book,receipts):
                verification_conflict=True
                raise RuntimeError('已归档提交与原批次或队列冲突，禁止再次发布')
            verification_conflict=False
            record['archive_reconciliation']=True
            cycle.update(stage='platform_confirmed')
            cycle.pop('recovery',None)
            alert(job_id,chapter,'既有平台及归档证据已核对，无需再次提交','resolved')
            remaining=[]
        if (remaining and cycle.get('stage')=='publish_started'
            and cycle.get('publish_attempt',{}).get('chapter_id')==remaining[0]
            and recoverable_before_submit(job,remaining[0])):
            cycle['stage']='publication_retry'
            record['pre_submit_recovery']=True
        if remaining and cycle.get('stage')=='publish_started':
            chapter=remaining[0]
            if cycle.get('publish_attempt',{}).get('chapter_id')!=chapter:
                verification_conflict=True
                raise RuntimeError('提交记录与原批次章节不符，禁止自动恢复')
            record['reconciliation']=True
            record['publish_exit_code']=bridge.run_publish(book,count=1,volume=job.get('volume'),
                account=account,project=project,reconcile_only=True)
            bridge.sync_manifest()
            archive=s._verified_archive(book,receipts,account)
            if record['publish_exit_code']!=0 or chapter not in archive:
                raise RuntimeError('已提交章节只读核验未完成；禁止重新提交')
            cycle.update(stage='platform_confirmed')
            cycle.pop('recovery',None)
            alert(job_id,chapter,'只读核验已确认发布，未再次提交','resolved')
            remaining=[] # One confirmed chapter per child, including recovery.
        if remaining:
            if expired():return close_expired()
            chapter = remaining[0]
            previous_recovery = cycle.get('recovery', {})
            if previous_recovery.get('chapter_id') != chapter:
                cycle.pop('recovery', None)
            cycle.update(stage='generation', current_chapter=chapter)
            cycle.pop('publish_attempt', None)
            s._update_run(job_id, {'cycle': cycle})
            if chapter not in receipts and not writer._find_outline(project,chapter) and model_roles.enabled():
                import asyncio
                from . import studio
                count=1;limit=5
                if cycle.get('word_goal_supplement'):
                    from .daily_word_goal import progress
                    value=progress(job,cycle['run_date'])
                    limit=min(5,max(1,(value['target']-value['confirmed_words']+job['word_count']-1)//job['word_count']))
                existing=writer.existing_chapter_ids(project)
                while (count<limit and (cycle.get('word_goal_supplement') or chapter+count in targets)
                       and chapter+count not in existing and not writer._find_outline(project,chapter+count)):count+=1
                # Plan only; no future prose is generated or submitted. Writing
                # and publication remain one verified chapter at a time.
                planned=asyncio.run(studio.plan_async(project,count=count,start=chapter))
                record['planning']={key:planned[key] for key in ('status','chapters','path')}
            generated = writer.generate_chapter(project, word_count=cycle['word_count'],
                        max_revisions=cycle['max_revisions'], chapter_id=chapter)
            record['generated'].append(s._compact_generation(generated))
            receipts = writer.reviewed_chapters(project)
            memory_error=receipts.get(chapter,{}).get('post_save',{}).get('shared_memory',{})
            if memory_error.get('status')=='failed':
                from .failure_info import PostSaveIncomplete
                raise PostSaveIncomplete(memory_error)
            from .length_policy import minimum, body_chars, require
            limit = minimum(project,chapter)
            if chapter in receipts:
                source = Path(receipts[chapter]['destination'])
                if limit and body_chars(source.read_text(encoding='utf-8-sig'),chapter)<limit:
                    from .studio import polish_existing
                    record['parked_unsubmitted_queue']=bridge.park_unsubmitted_queue_for_revision(project,book,account,chapter,source)
                    record['length_repair'] = polish_existing(project, chapter, min_words=limit)
                    receipts = writer.reviewed_chapters(project)
                require(project, Path(receipts[chapter]['destination']).read_text(encoding='utf-8-sig'), chapter)
            if chapter not in receipts:
                raise RuntimeError('本章缺少当前有效审查记录，禁止发布')
            def memory_ready(receipt):
                post=receipt.get('post_save') or {}
                return (post.get('shared_memory',{}).get('status')=='synced'
                        and post.get('entities',{}).get('status')=='synced'
                        and post.get('continuity_written') is True and post.get('rag_indexed') is True)
            source_post=receipts[chapter].get('post_save') or {}
            if source_post.get('shared_memory',{}).get('status')=='failed':
                from .failure_info import PostSaveIncomplete
                raise PostSaveIncomplete(source_post['shared_memory'])
            artifacts_ready=(source_post.get('entities',{}).get('status')=='synced'
                and source_post.get('continuity_written') is True and source_post.get('rag_indexed') is True)
            if not artifacts_ready and generated.get('status')=='recovered' and not record.get('length_repair'):
                from .studio import sync_existing_artifacts
                record['memory_repair']=sync_existing_artifacts(project,chapter)
                receipts=writer.reviewed_chapters(project)
            if not memory_ready(receipts[chapter]):
                from .failure_info import PostSaveIncomplete
                raise PostSaveIncomplete(receipts[chapter].get('post_save',{}).get('shared_memory',{}))
            archive = s._verified_archive(book, receipts, account)
            if chapter not in archive:
                if expired():return close_expired()
                staged = bridge.stage_project(project, book_name=book, selected_ids={chapter})
                if staged['conflicts'] or staged['invalid']:
                    raise RuntimeError('章节入队冲突或正文无效')
                queue = s._verify_queue(book, receipts)
                if set(queue) & set(archive) or sorted(queue)[:1] != [chapter]:
                    raise RuntimeError('队列顺序或归档冲突，禁止提交')
                latest = s.load_scheduler()['jobs'].get(job_id)
                if not latest or s.material_change(latest, job):
                    raise RuntimeError('运行中任务配置已改变')
                if not force and (not latest.get('enabled', True) or s._check_approval(latest, s._job_today(latest))):
                    raise RuntimeError('发布前任务已暂停或日期未获批准')
                bridge.validate_queue_origin(book, project=project, account=account)
                # A crash from this point onward is NOT safe for a blind retry.
                cycle.update(stage='publish_started', publish_attempt={'chapter_id': chapter,'invocation_id':uuid.uuid4().hex,
                             'started_at': bridge.now_iso()})
                s._update_run(job_id, {'cycle': cycle})
                record['queued_before_publish'] = sorted(queue)
                if expired():return close_expired()
                previous_deadline=os.environ.get('NOVEL_HELPER_SUBMIT_BEFORE')
                if cycle.get('word_goal_supplement'):
                    midnight=datetime.fromisoformat(cycle['run_date']).replace(tzinfo=ZoneInfo(job['timezone']))+timedelta(days=1)
                    os.environ['NOVEL_HELPER_SUBMIT_BEFORE']=midnight.isoformat()
                try:
                    record['publish_exit_code'] = bridge.run_publish(book, count=1,
                                      volume=job.get('volume'), account=account,invocation_id=cycle['publish_attempt']['invocation_id'])
                finally:
                    if previous_deadline is None:os.environ.pop('NOVEL_HELPER_SUBMIT_BEFORE',None)
                    else:os.environ['NOVEL_HELPER_SUBMIT_BEFORE']=previous_deadline
                bridge.sync_manifest()
                receipts = writer.reviewed_chapters(project)
                archive = s._verified_archive(book, receipts, account)
                queue = s._verify_queue(book, receipts)
                if record['publish_exit_code'] != 0 or chapter not in archive or chapter in queue:
                    detail=''
                    try:
                        evidence=bridge.latest_publish_report(book,account)
                        detail=str(evidence.get('detail') or evidence.get('reason') or '')[:400]
                        if (evidence.get('publisher_started') is False and evidence.get('invocation_id')==cycle['publish_attempt']['invocation_id']
                            and evidence.get('plan_chapters')==[{'chapter_id':chapter,'file_sha256':hashlib.sha256(queue[chapter].read_bytes()).hexdigest()}]):
                            from .failure_info import PublicationPreflightIncomplete
                            raise PublicationPreflightIncomplete({'error':detail,**evidence.get('failure',{})},'发布前模型检查未完成，发布器尚未启动')
                    except (ValueError,OSError,KeyError):
                        detail=''
                    reason=(f'发布结果未确认；保留原章节，需先核对平台，禁止自动重发。'
                            f'可运行 python integration/bridge.py reconcile --book {book} --account {account} 做只读核对')
                    if detail:
                        reason=f'{reason}；发布报告：{detail}'
                    raise RuntimeError(reason)
                cycle['stage'] = 'platform_confirmed'
                cycle.pop('recovery', None)
                alert(job_id, chapter, '本章已核验发布，恢复记录关闭', 'resolved')
        receipts = writer.reviewed_chapters(project)
        archive = s._verified_archive(book, receipts, account)
        queue = s._verify_queue(book, receipts)
        complete = set(targets).issubset(archive) and not set(targets).intersection(queue)
        cycle['status'] = 'success' if complete else 'continuing'
        record.update(status='success' if complete else 'progress', finished_at=bridge.now_iso(),
                      generated_ids_published=[i for i in targets if i in archive],
                      published_ids_seen_in_local_archive=archive, queue_after_publish=sorted(queue),
                      delivery_mode='serial')
        changes = {'cycle': cycle, 'last_status': cycle['status'], 'last_message': ''}
        if complete:
            completed = s.completed_slots(job, cycle['run_date'])
            if not cycle.get('word_goal_supplement'):
                completed.add(cycle['slot'])
            changes.update(last_run_date=cycle['run_date'], completed_slots=sorted(completed)[-56:])
            from .daily_word_goal import supplement
            additional = supplement(job, cycle, record)
            if additional is not None:
                record['completed_cycle'] = cycle.copy()
                record['next_cycle'] = additional.copy()
                changes.update(cycle=additional, last_status='continuing')
        s._update_run(job_id, changes)
        record['run_record'] = s._write_run_record(job_id, record)
        return record
    except Exception as exc:
        message = safe_message(exc)
        previous = cycle.get('recovery', {})
        attempts = previous.get('attempts', 0) if previous.get('chapter_id') == chapter else 0
        from . import editorial_recovery as editorial
        from .failure_info import details
        failure=details(exc)
        pre_submit=(recoverable_before_submit(job,chapter)
            if cycle.get('stage')=='publish_started' and chapter is not None else None)
        from .failure_info import PublicationPreflightIncomplete
        if isinstance(exc,PublicationPreflightIncomplete):pre_submit='model_gate_pre_submit'
        if pre_submit and (failure.get('retryable') is False or pre_submit=='model_gate_pre_submit' and failure.get('retryable') is not True):
            cycle['stage']='publication_blocked'
            failure['retryable']=False
            pre_submit=None
        if not pre_submit and cycle.get('stage')=='publish_started' and chapter is not None:
            from .recovery import _queue_entry
            from fanqie_auto_publish.publication_safety import requires_reconciliation
            try:
                _,entry=_queue_entry(job,chapter)
                if isinstance(entry,dict) and entry.get('state') in {'preparing','blocked_before_submit'} and not requires_reconciliation(entry):
                    cycle['stage']='publication_blocked'
                    failure.update(retryable=False,failure_kind='platform_or_configuration_blocked')
            except (ValueError,KeyError,TypeError,OSError):
                verification_conflict=True
                failure.update(retryable=False,failure_kind='evidence_corrupt')
        publish_retries=previous.get('publication_attempts',0) if previous.get('chapter_id')==chapter else 0
        if pre_submit:
            cycle['stage']='publication_retry'
            message=f'已确认本章尚未提交（{safe_message(exc)[:300]}）；将重试同一章草稿'
        verification_attempts=previous.get('verification_attempts',0) if previous.get('chapter_id')==chapter else 0
        if record.get('reconciliation'):verification_attempts+=1
        reconcile=(not verification_conflict and cycle.get('stage')=='publish_started'
            and cycle.get('publish_attempt',{}).get('chapter_id')==chapter)
        editing = cycle.get('stage') == 'generation' and editorial.can_retry(exc,project,chapter)
        editorial_attempts=previous.get('editorial_attempts',0) if previous.get('chapter_id')==chapter else 0
        retryable = reconcile and verification_attempts<3 or cycle.get('stage') == 'generation' and (
            editing and editorial_attempts < editorial.MAX_RECOVERIES or
            not editing and failure.get('retryable') is not False and
            (failure.get('retryable') is True or transient_generation_error(exc)) and attempts < len(BACKOFF_SECONDS))
        waiting=failure.get('failure_kind') in {'recovery_cooldown','free_pool_wait'}
        recovery = {'chapter_id': chapter, 'attempts': attempts + (0 if waiting else 1), 'automatic_retry': retryable,
                    'message': message,**failure}
        if failure.get('failure_kind') in {'recovery_cooldown','free_pool_wait'}:
            retryable=True
            recovery.update(automatic_retry=True,cooldown=True)
            if failure.get('next_retry_at'):recovery['next_retry_at']=failure['next_retry_at']
        if pre_submit:
            retryable=waiting or publish_retries<len(BACKOFF_SECONDS)
            recovery.update(automatic_retry=retryable,mode='pre_submit_retry',
                publication_attempts=publish_retries+(0 if waiting else 1),reason=pre_submit)
        elif publish_retries:
            recovery['publication_attempts']=publish_retries
        if reconcile:recovery.update(mode='read_only_reconciliation',verification_attempts=verification_attempts)
        if reconcile:
            now = s._now_for_job(job)
            since = previous.get('first_unknown_at') or now.isoformat()
            recovery['first_unknown_at'] = since
            retryable = (now - datetime.fromisoformat(since)).total_seconds() < 86400
            recovery['automatic_retry'] = retryable
            if retryable:
                recovery['next_retry_at'] = (now + timedelta(seconds=BACKOFF_SECONDS[min(verification_attempts, 2)] if verification_attempts < 3 else 1800)).isoformat()
        elif not retryable and (pre_submit or cycle.get('stage') == 'generation' and failure.get('retryable') is True):
            from .retry_budget import extension
            extra = extension(job, s._now_for_job(job))
            if extra:
                retryable = True
                recovery.update(automatic_retry=True, cooldown=True, extra_budget=extra, next_retry_at=extra['next_retry_at'])
        if editing:
            recovery.update(kind='editorial',editorial_attempts=editorial_attempts+1)
        elif editorial_attempts:
            recovery['editorial_attempts']=editorial_attempts
        if retryable and not recovery.get('next_retry_at'):
            retry_index=publish_retries if pre_submit else verification_attempts if reconcile else editorial_attempts if editing else attempts
            delay=BACKOFF_SECONDS[min(retry_index,len(BACKOFF_SECONDS)-1)]
            recovery['next_retry_at'] = (s._now_for_job(job) + timedelta(seconds=delay)).isoformat()
        cycle.update(status='failed', recovery=recovery)
        s._update_run(job_id, {'cycle': cycle, 'last_status': 'failed', 'last_message': message})
        record.update(status='failed', error=message, recovery=recovery, finished_at=bridge.now_iso())
        record['run_record'] = s._write_run_record(job_id, record)
        alert(job_id, chapter or 'unknown', message, 'retry_wait' if retryable else 'needs_attention')
        return record
