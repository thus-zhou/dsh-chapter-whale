"""Single local coordinator. One child per chapter avoids the manager's batch timeout."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from integration import bridge, scheduler as s, writer_runner as writer

DATA = ROOT / 'integration_data' / 'serial_service'
PENDING = DATA / 'pending_schedule.json'
LOCK = DATA / 'service.lock'
STATE = DATA / 'heartbeat.json'
from manager.runtime_health import release_id, STARTUP_ID, STARTED_AT
LOADED_RELEASE = release_id()


def heartbeat(value):
    bridge.write_json_atomic(STATE,{'release_id':LOADED_RELEASE,'startup_id':STARTUP_ID,'started_at':STARTED_AT,**value})


def apply_pending():
    request = bridge.read_json(PENDING, {})
    if request.get('state') != 'pending':
        return False
    try:
        with writer.file_lock(bridge.RUNTIME_ROOT / 'scheduler-execution.lock'):
            with s.config_transaction() as document:
                job = document['jobs'][request['job_id']]
                if job['book'] != request['book'] or job['account'] != request['account']:
                    raise ValueError('Pending schedule account/book mismatch')
                changes = request['changes']
                if set(changes) - s._JOB_FIELDS:
                    raise ValueError('Pending schedule contains runtime fields')
                updated = {**job, **changes}
                if request.get('unfinished_word_target'):
                    target = request['unfinished_word_target']
                    if type(target) is not int or not 5001 <= target <= 10000:
                        raise ValueError('Invalid author-approved unfinished chapter word target')
                    cycle = dict(updated.get('cycle') or {})
                    if cycle and cycle.get('status') != 'success':
                        # Explicit NEW author length requirement, not quota expansion.
                        cycle['word_count'] = target
                        updated['cycle'] = cycle
                s._validate_job(updated)
                s._check_binding(document, request['job_id'], updated)
                # The old process must have released the execution lock first.
                # Freeze its chapter IDs and previous writing target unchanged.
                if job.get('last_status') == 'running':
                    cycle = dict(updated.get('cycle') or {})
                    cycle.update(status='failed', stage='legacy_unknown', recovery={
                        'automatic_retry': False, 'message': '旧进程结束但结果未知，需先核对平台'})
                    updated.update(cycle=cycle, last_status='failed', last_message='旧进程结果未知，禁止自动重发')
                elif job.get('last_status') == 'failed':
                    # Only a matching completed pre-submission run record can
                    # establish that a legacy failure is safe to retry.
                    records = sorted((s.RUNS_ROOT/request['job_id']).glob('*.json'), key=lambda p: p.stat().st_mtime)
                    proof = bridge.read_json(records[-1], {}) if records else {}
                    from integration.serial_delivery import transient_generation_error
                    if (proof.get('started_at') == job.get('last_attempt_at')
                        and proof.get('status') == 'failed' and proof.get('error')
                        and 'queued_before_publish' not in proof and 'publish_exit_code' not in proof
                        and transient_generation_error(RuntimeError(proof['error']))):
                        cycle = dict(updated.get('cycle') or {})
                        cycle['recovery'] = {'automatic_retry': True, 'attempts': 0,
                            'next_retry_at': bridge.now_iso(), 'message': '已核对原记录为提交前临时故障'}
                        updated['cycle'] = cycle
                document['jobs'][request['job_id']] = updated
            request.update(state='applied', applied_at=bridge.now_iso())
            bridge.write_json_atomic(PENDING, request)
            return True
    except RuntimeError as exc:
        if '已有任务正在运行' in str(exc) or 'resource_busy' in str(exc):
            return False
        raise


def eligible(job, now=None):
    if not job.get('enabled', True) or job.get('delivery_mode') != 'serial':
        return False
    now = now or s._now_for_job(job)
    if s._check_approval(job, now.date().isoformat()):
        return False
    cycle = job.get('cycle') or {}
    if cycle.get('local_only'):
        recovery=(cycle.get('batch_recovery') if cycle.get('publication_batch_active') else cycle.get('local_recovery')) or {}
        if recovery and not recovery.get('resolved'):
            if not recovery.get('automatic_retry'):
                return False
            try:
                target=datetime.fromisoformat(recovery['next_retry_at'])
                return target.tzinfo is not None and target<=now
            except (KeyError,TypeError,ValueError):
                return False
    if cycle.get('status') in {'continuing'}:
        return True
    if cycle and cycle.get('status') != 'success':
        recovery = cycle.get('recovery') or {}
        if not recovery.get('automatic_retry'):
            return False
        target = recovery.get('next_retry_at')
        return bool(target and datetime.fromisoformat(target) <= now)
    due = s.next_due(job, now)
    return bool(due and datetime.fromisoformat(due) <= now)


def dispatch_allowed(document):
    return (document.get('settings',{}).get('auto_schedule') is True
        and writer.strict_json(DATA.parent/'maintenance.json',{}).get('state')!='maintenance')


def ensure_started():
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        with writer.file_lock(LOCK):
            pass
    except RuntimeError as exc:
        if 'resource_busy' not in str(exc) and '已有任务正在运行' not in str(exc):raise
        state = bridge.read_json(STATE, {})
        try:
            from datetime import timezone
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(state['checked_at'])).total_seconds()
        except (ValueError, TypeError, KeyError):
            age = 999999
        if age > 90:
            return {'status': 'needs_attention', 'service': 'serial_delivery', 'already_running': True, 'reason': 'stale_heartbeat_lock_held'}
        return {'status': 'configured', 'service': 'serial_delivery', 'already_running': True}
    log = DATA / 'service.log'
    if log.exists() and log.stat().st_size > 2 * 1024 * 1024:
        log.replace(DATA / 'service.previous.log')
    env = bridge.child_environment()
    # Never inherit a manager operation's result destination into a daemon.
    for key in ('NOVEL_HELPER_MANAGER_RESULT', 'NOVEL_HELPER_OPERATION_ID'):
        env.pop(key, None)
    with log.open('ab') as output:
        process = subprocess.Popen([sys.executable, '-X', 'utf8', '-u', str(Path(__file__).resolve())],
            cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    return {'status': 'configured', 'service': 'serial_delivery', 'pid': process.pid}


def run_child(job_id):
    env = bridge.child_environment()
    env['PYTHONUTF8'] = '1'
    env['NOVEL_HELPER_COST_DB'] = str(ROOT/'integration_data'/'costs.sqlite3')
    env['NOVEL_HELPER_AI_CONFIG'] = str(ROOT/'integration_data'/'ai_config.json')
    for key in ('NOVEL_HELPER_MANAGER_RESULT', 'NOVEL_HELPER_OPERATION_ID'):
        env.pop(key, None)
    # Model/browser timeouts remain in force; no overall one-hour DAILY timer.
    # The service only runs one verified chapter in each process.
    chapter_log = DATA / 'chapters.log'
    if chapter_log.exists() and chapter_log.stat().st_size > 5 * 1024 * 1024:
        chapter_log.replace(DATA / 'chapters.previous.log')
    with chapter_log.open('ab') as output:
        process = subprocess.Popen([sys.executable, '-X', 'utf8', '-u', str(ROOT/'manager'/'worker.py'),
                   'run', '--job-id', job_id, '--serial-step'], cwd=str(ROOT), env=env,
                   stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        while process.poll() is None:
            heartbeat({'pid':os.getpid(),'checked_at':bridge.now_iso(),
                'status':'running','active_job':job_id,'child_pid':process.pid})
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
    # A competing worker may own the checkpoint after this child returned busy.
    # Recovery acquires the execution lock; it cannot mutate a live owner's job.
    recover_interrupted()
    return process.returncode


def recover_interrupted():
    """Recover a dead coordinator only after the chapter execution lock is free."""
    try:
        with writer.file_lock(bridge.RUNTIME_ROOT/'scheduler-execution.lock'):
            with s.config_transaction() as document:
                for identity,job in document['jobs'].items():
                    cycle=job.get('cycle') or {}
                    if job.get('delivery_mode')!='serial' or cycle.get('status')!='running':continue
                    if cycle.get('stage') not in {None,'generation','publish_started','platform_confirmed','publication_retry','local_generation','local_post_save_repair','group_publish_started','group_reconciliation'}:continue
                    chapter=cycle.get('current_chapter')
                    attempts=cycle.get('interruption_count',0) if cycle.get('interruption_chapter')==chapter else 0
                    cycle.update(interruption_chapter=chapter,interruption_count=attempts+1,
                        restart_recovered_at=bridge.now_iso())
                    if attempts>=3:
                        message='本章执行进程连续异常退出，已保留检查点，需检查运行环境'
                        cycle.update(status='failed',recovery={**cycle.get('recovery',{}),
                            'automatic_retry':False,'message':message})
                        job.update(last_status='failed',last_message=message)
                        from integration.serial_delivery import alert
                        alert(identity,chapter or 'unknown',message,'needs_attention')
                    else:
                        cycle['status']='continuing'
                        job.update(last_status='continuing',last_message='执行器重启，按持久化检查点恢复原章节')
            return True
    except RuntimeError as exc:
        if '已有任务正在运行' in str(exc) or 'resource_busy' in str(exc):return False
        raise


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        with writer.file_lock(LOCK):
            recovered = False
            while True:
                try:
                    if not recovered:
                        recovered=recover_interrupted()
                        if not recovered:
                            heartbeat({'pid':os.getpid(),'checked_at':bridge.now_iso(),
                                'status':'waiting_for_existing_worker','active_job':None})
                            time.sleep(15)
                            continue
                    try:
                        apply_pending()
                    except (ValueError, KeyError, OSError) as exc:
                        # 非法/损坏的 pending 请求不能每轮重试同一错误、阻塞所有任务；
                        # 标记为 needs_attention 后继续调度其它任务。
                        request = bridge.read_json(PENDING, {})
                        if isinstance(request, dict) and request.get("state") == "pending":
                            request.update(state="needs_attention", error=str(exc)[:1200],
                                           updated_at=bridge.now_iso())
                            bridge.write_json_atomic(PENDING, request)
                        print(f"[serial] pending 调度请求不可用，已标记待处理：{exc}", flush=True)
                    document = s.load_scheduler()
                    active = None
                    if dispatch_allowed(document):
                        from integration.recovery import reconcile_waiting
                        if reconcile_waiting(document):document=s.load_scheduler()
                        candidates = [(job.get('last_attempt_at', ''), identity) for identity, job in document['jobs'].items() if eligible(job)]
                        active = min(candidates)[1] if candidates else None
                    heartbeat({'pid': os.getpid(), 'checked_at': bridge.now_iso(),
                            'status': 'running', 'active_job': active,
                            'pending_schedule': bridge.read_json(PENDING, {}).get('state')})
                    if active:
                        run_child(active)
                    else:
                        time.sleep(15)
                except Exception as exc:
                    from integration.serial_delivery import safe_message
                    heartbeat({'pid': os.getpid(), 'checked_at': bridge.now_iso(),
                                'status': 'error', 'message': safe_message(exc)})
                    time.sleep(30)
    except RuntimeError as exc:
        if '已有任务正在运行' not in str(exc) and 'resource_busy' not in str(exc):
            raise


if __name__ == '__main__':
    main()
