"""Durable, per-book daily extension budget. Never reset by process restart."""
import hashlib
from datetime import datetime, timedelta
from . import bridge, writer_runner


class RecoveryDeferred(RuntimeError):
    retryable=True
    failure_kind='recovery_cooldown'
    def __init__(self, target):
        super().__init__('本书额外恢复正在冷却，等待下一次恢复时间')
        self.next_retry_at=target


class RecoveryBudgetExhausted(RecoveryDeferred):
    """A daily limit is a durable wait, not an unclassified permanent failure."""
    error_code='daily_recovery_budget_exhausted'
    def __init__(self, now=None):
        from zoneinfo import ZoneInfo
        zone=ZoneInfo('Asia/Shanghai')
        local=(now or datetime.now(zone)).astimezone(zone)
        target=datetime.combine(local.date()+timedelta(days=1),datetime.min.time(),tzinfo=zone)
        super().__init__(target.isoformat())
        self.args=('本书今日6次额外恢复已用完，等待北京时间次日00:00恢复；已完成正文和发布证据保留',)


def daily_limit(project, default=6):
    from pathlib import Path
    root=Path(project).resolve()
    path=root/'.webnovel/recovery_policy.json'
    if path.is_symlink() or path.parent.is_symlink():raise ValueError('恢复策略路径无效')
    maximum=default
    if path.exists():
        policy=writer_runner.strict_json(path,{})
        if (not isinstance(policy,dict) or policy.get('schema')!=1
                or policy.get('project')!=str(root) or 'extra_attempts_per_day' not in policy):
            raise ValueError('本书恢复策略损坏或作品身份不匹配')
        maximum=policy['extra_attempts_per_day']
    if maximum is None:return None
    if type(maximum) is not int or maximum<0:raise ValueError('恢复次数策略无效')
    return min(6,maximum)


def status(project,now):
    from pathlib import Path
    identity=hashlib.sha256(str(Path(project).resolve()).casefold().encode()).hexdigest()
    data=writer_runner.strict_json(bridge.RUNTIME_ROOT/'recovery-budget.json',{})
    entry=data.get(identity,{})
    used=entry.get('used',0) if entry.get('date')==now.date().isoformat() else 0
    maximum=daily_limit(project)
    if maximum is None:return {'used':used,'remaining':None,'limit':None,'unlimited':True}
    return {'used':used,'remaining':max(0,maximum-used),'limit':maximum}


def extension(job, now, immediate=False, routing=False):
    policy = job.get('recovery_policy') or {}
    maximum = daily_limit(job['project'],policy.get('extra_attempts_per_day',0))
    if maximum == 0:
        return None
    path = bridge.RUNTIME_ROOT / 'recovery-budget.json'
    from pathlib import Path
    identity = hashlib.sha256(str(Path(job['project']).resolve()).casefold().encode()).hexdigest()
    with writer_runner.file_lock(path.with_suffix('.lock'), blocking=True):
        data = writer_runner.strict_json(path, {})
        entry = data.get(identity, {})
        day = now.date().isoformat()
        used = entry.get('used', 0) if entry.get('date') == day else 0
        if type(used) is not int or used<0:raise ValueError('恢复计数损坏，未覆盖')
        if maximum is not None and used >= maximum:
            return None
        last = datetime.fromisoformat(entry['next_retry_at']) if entry.get('date') == day and entry.get('next_retry_at') else now
        if immediate and last>now and not routing:raise RecoveryDeferred(last.isoformat())
        target = max(now, last) + timedelta(minutes=30)
        data[identity] = {'date': day, 'used': used + 1, 'limit': maximum, 'next_retry_at': target.isoformat()}
        bridge.write_json_atomic(path, data)
        return data[identity]
