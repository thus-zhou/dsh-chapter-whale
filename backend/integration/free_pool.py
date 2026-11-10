"""Explicit model pool, bounded free rotation and durable wait state."""
import copy
import hashlib
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from . import bridge,costs,writer_runner,retry_budget

ZONE=ZoneInfo('Asia/Shanghai')


def now():return datetime.now(ZONE)


class PoolWait(RuntimeError):
    failure_kind='free_pool_wait'
    retryable=True
    def __init__(self,message='免费渠道暂不可用，等待恢复',target=None):
        super().__init__(message)
        self.next_retry_at=(target or now()+timedelta(minutes=30)).isoformat()


def next_day():return (now()+timedelta(days=1)).replace(hour=0,minute=5,second=0,microsecond=0)


def state_path():return bridge.RUNTIME_ROOT/'free-pool-recovery.json'


def identity(project,model):return hashlib.sha256((str(Path(project).resolve()).casefold()+'|'+model).encode()).hexdigest()


def states():
    value=writer_runner.strict_json(state_path(),{})
    if not isinstance(value,dict):raise ValueError('免费池恢复记录损坏')
    return value


def blocked(project,model):
    entry=states().get(identity(project,model),{})
    if entry.get('requires_login'):return next_day()
    until=entry.get('next_retry_at')
    return datetime.fromisoformat(until) if until and datetime.fromisoformat(until)>now() else None


def defer(project,model,failure):
    status=failure.get('http_status')
    target=next_day() if status in (401,403,429) or failure.get('failure_kind')=='configuration_or_access' else now()+timedelta(minutes=30)
    path=state_path()
    with writer_runner.file_lock(path.with_suffix('.lock'),blocking=True):
        doc=states();key=identity(project,model);previous=doc.get(key,{})
        doc[key]={'model':model,'project':str(project),'next_retry_at':target.isoformat(),
            'attempts':previous.get('attempts',0)+1,'status':'failed','failure_kind':failure.get('failure_kind'),'http_status':status,
            'requires_login':status in (401,403) or failure.get('failure_kind')=='configuration_or_access' and failure.get('error_code') not in {'insufficient_quota','billing_hard_limit_reached'}}
        bridge.write_json_atomic(path,doc)


def recovered(project,model):
    path=state_path()
    with writer_runner.file_lock(path.with_suffix('.lock'),blocking=True):
        doc=states();key=identity(project,model)
        if key in doc:
            doc[key].update(status='recovered',recovered_at=now().isoformat(),next_retry_at=None)
            bridge.write_json_atomic(path,doc)


def authorized_login(channel):
    path=state_path()
    with writer_runner.file_lock(path.with_suffix('.lock'),blocking=True):
        doc=states();changed=False
        for entry in doc.values():
            if entry.get('requires_login') and entry.get('model','').startswith(channel+'/'):
                entry.update(requires_login=False,next_retry_at=None,login_confirmed_at=now().isoformat());changed=True
        if changed:bridge.write_json_atomic(path,doc)


def validate_members(rows,catalog):
    if not isinstance(rows,list) or not 1<=len(rows)<=20:raise ValueError('请选择1–20个免费池模型')
    available={r['id'] for r in catalog}
    result=[];seen=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)-{'model_id','roles','quota_confirmed'}:raise ValueError('免费池模型配置无效')
        model=row.get('model_id');roles=row.get('roles')
        if model not in available or model in seen:raise ValueError('模型未在当前清单中或已重复')
        if row.get('quota_confirmed') is not True:raise ValueError('请确认此模型使用免费额度，而非付费订阅或按量计费')
        if not isinstance(roles,list) or not roles or any(not isinstance(r,str) or r not in 'ABCDE' or len(r)!=1 for r in roles):raise ValueError('免费池角色范围无效')
        result.append({'model_id':model,'roles':list(dict.fromkeys(roles)),'quota_confirmed':True});seen.add(model)
    return result


class FreePoolClient:
    def __init__(self,role,config,factory):
        self.role=role;self.config=copy.deepcopy(config);self.factory=factory
        self.model='auto';self.max_retries=1;self.timeout=600;self.last_response_meta={}
        self.base_url=config['providers']['free-pool']['base_url']
        self._thinking_disabled = ContextVar('free_pool_thinking_disabled', default=False)

    @contextmanager
    def without_thinking(self):
        token = self._thinking_disabled.set(True)
        try:
            yield
        finally:
            self._thinking_disabled.reset(token)

    def _thinking_scope(self, client):
        method = getattr(client, 'without_thinking', None)
        return method() if self._thinking_disabled.get() and callable(method) else nullcontext()

    def _choices(self):
        from . import ofm_runtime
        info=ofm_runtime.ensure_started()
        if self.config['providers']['ofm-standalone']['base_url']!=info['url']+'/v1':raise ValueError('独立服务端口已变化，请在网页重新保存免费池')
        project=costs.META.get().get('project')
        if not project:raise ValueError('免费池请求缺少作品归属')
        pool=self.config['providers']['free-pool']
        permitted={str(Path(p).resolve()).casefold() for p in pool.get('allowed_projects',[])}
        if str(Path(project).resolve()).casefold() not in permitted:raise ValueError('此作品未授权免费渠道处理正文与必要记忆')
        rows=[r for r in pool.get('pool_members',[]) if self.role in r['roles']]
        if not rows:raise ValueError(f'免费池尚未为角色{self.role}选择模型')
        available=[r for r in rows if not blocked(project,r['model_id'])]
        if not available:
            deadlines=[blocked(project,r['model_id']) for r in rows]
            raise PoolWait(target=min((d for d in deadlines if d),default=now()+timedelta(minutes=30)))
        return project,available

    def _client(self,row,project,index):
        if index or states().get(identity(project,row['model_id']),{}).get('status')=='failed':
            extra=retry_budget.extension({'project':project,'recovery_policy':{'extra_attempts_per_day':6}},now(),immediate=True,routing=True)
            if not extra:raise PoolWait('今日额外恢复次数已用完，等待次日恢复',next_day())
        return self.factory({'provider_id':'ofm-standalone','model_id':row['model_id']})

    async def _run(self,method,messages,**kwargs):
        from .failure_info import details
        project,rows=self._choices()
        for index,row in enumerate(rows):
            client=self._client(row,project,index);client.timeout=self.timeout
            try:
                with costs.scope(provider_id='ofm-standalone',provider_name='免费额度 · '+row['model_id'].split('/')[0],
                    provider_price={'input':'0','output':'0','cached':'0','currency':'CNY'},pricing_scope='provider',
                    free_quota_declared=True,pool_role=self.role,fallback_reason='free_channel_rotation' if index else None):
                    with self._thinking_scope(client):
                        result=await getattr(client,method)(messages,**kwargs)
                recovered(project,row['model_id'])
                self.last_response_meta=getattr(client,'last_response_meta',{});return result
            except Exception as exc:
                info=details(exc)
                if info.get('retryable') is False and info.get('failure_kind') not in {'authentication','configuration_or_access'} and info.get('http_status') not in (404,429):raise
                if info.get('retryable') is None:raise
                defer(project,row['model_id'],info)
        raise PoolWait('所选免费渠道均暂不可用，将尝试已配置的付费备选或等待额度恢复')

    async def chat(self,messages,temperature=.7,max_tokens=4000,response_format=None):
        return await self._run('chat',messages,temperature=temperature,max_tokens=max_tokens,response_format=response_format)

    async def chat_with_tools(self,messages,tools,temperature=.3,max_tokens=2000):
        return await self._run('chat_with_tools',messages,tools=tools,temperature=temperature,max_tokens=max_tokens)

    async def chat_stream(self,messages,temperature=.7,max_tokens=16000):
        from .failure_info import details
        project,rows=self._choices()
        for index,row in enumerate(rows):
            client=self._client(row,project,index);client.timeout=self.timeout;emitted=False
            try:
                with costs.scope(provider_id='ofm-standalone',provider_name='免费额度 · '+row['model_id'].split('/')[0],
                    provider_price={'input':'0','output':'0','cached':'0','currency':'CNY'},pricing_scope='provider',
                    free_quota_declared=True,pool_role=self.role):
                    with self._thinking_scope(client):
                        async for chunk in client.chat_stream(messages,temperature=temperature,max_tokens=max_tokens):
                            if str(chunk).startswith('[ERROR]'):raise RuntimeError(str(chunk))
                            emitted=emitted or bool(chunk);yield chunk
                recovered(project,row['model_id'])
                self.last_response_meta=getattr(client,'last_response_meta',{});return
            except Exception as exc:
                info=details(exc)
                if emitted or info.get('retryable') is None or (info.get('retryable') is False and info.get('failure_kind') not in {'authentication','configuration_or_access'} and info.get('http_status') not in (404,429)):raise
                defer(project,row['model_id'],info)
        raise PoolWait('所选免费渠道均暂不可用，将使用明确配置的备选或等待恢复')
