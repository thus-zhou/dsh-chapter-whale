"""Immutable role routing with explicit, budgeted fallback connections."""
import copy
import os
from contextlib import contextmanager
from contextvars import ContextVar
from . import costs

EXECUTION_ROUTES=ContextVar('novel_execution_routes',default=None)

@contextmanager
def execution_routes():
    if EXECUTION_ROUTES.get() is not None:
        yield
        return
    token=EXECUTION_ROUTES.set({'grants':set(),'pins':{}})
    try:yield
    finally:EXECUTION_ROUTES.reset(token)


class ProviderClient:
    def __init__(self,role,config,primary,factory):
        object.__setattr__(self,'_role',role)
        object.__setattr__(self,'_config',copy.deepcopy(config))
        object.__setattr__(self,'_primary',primary)
        object.__setattr__(self,'_client',primary)
        object.__setattr__(self,'_factory',factory)
        object.__setattr__(self,'_pinned',None)
        object.__setattr__(self,'_pinned_project',None)
        object.__setattr__(self,'_granted',set())
    def __getattr__(self,key):return getattr(self._client,key)
    def __setattr__(self,key,value):
        setattr(self._primary,key,value)
        if self._client is not self._primary:setattr(self._client,key,value)
    def _binding(self):
        value=self._config.get('roles',{}).get(self._role,{}) if self._config.get('multi_model') else {}
        return value if value.get('provider_id') else self._config['default_binding']
    def _options(self):
        binding=self._binding()
        return [binding,*binding.get('fallbacks',[])]
    def _project(self):
        from pathlib import Path
        value=costs.META.get().get('project')
        return str(Path(value).resolve()).casefold() if value else None
    def _remember(self,index,client):
        object.__setattr__(self,'_client',client)
        object.__setattr__(self,'_pinned',index if index>0 else None)
        object.__setattr__(self,'_pinned_project',self._project())
        state=EXECUTION_ROUTES.get()
        if state is not None and index>0:state['pins'][self._route_key()]=index
    def _route_key(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        import json
        bindings=[(b['provider_id'],b['model_id'],self._config['providers'][b['provider_id']].get('revision')) for b in self._options()]
        return (self._project(),self._role,datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(),json.dumps(bindings))
    def _candidates(self):
        from .provider_circuit import active
        options=self._options()
        state=EXECUTION_ROUTES.get()
        shared=state['pins'].get(self._route_key()) if state is not None else None
        if shared is not None:return [(i,b) for i,b in enumerate(options) if i>=shared]
        if self._pinned is not None and self._pinned_project==self._project():
            return [(i,b) for i,b in enumerate(options) if i>=self._pinned]
        skip=len(options)>1 and active(costs.META.get().get('project'),self._role,self._config,options[0])
        return [(i,b) for i,b in enumerate(options) if not (i==0 and skip)]
    def _failed(self,index,binding,detail):
        if index==0 and len(self._options())>1 and (detail.get('retryable') is True or detail.get('failure_kind') in {'authentication','configuration_or_access'}):
            from .provider_circuit import defer
            defer(costs.META.get().get('project'),self._role,self._config,binding,detail)
    @contextmanager
    def _scope(self,binding,fallback,messages,max_tokens):
        item=self._config['providers'][binding['provider_id']]
        if item.get('protocol')=='ofm_standalone':
            from . import ofm_runtime
            from pathlib import Path
            info=ofm_runtime.ensure_started()
            if item['base_url']!=info['url']+'/v1':raise ValueError('独立服务端口已变化，请在网页重新同步模型')
            project=costs.META.get().get('project')
            permitted={str(Path(x).resolve()).casefold() for x in item.get('allowed_projects',[])}
            if costs.META.get().get('stage')!='probe' and (not project or str(Path(project).resolve()).casefold() not in permitted):raise ValueError('此作品未授权独立免费渠道处理正文与记忆')
        if item.get('protocol') in {'dsh_local','dsh_channel'}:
            if item.get('protocol')=='dsh_channel':
                from .free_channels import verify_endpoint
                verify_endpoint(item['base_url'])
            else:
                from .providers import verify_dsh_gateway
                verify_dsh_gateway(item['base_url'])
            from pathlib import Path
            meta=costs.META.get()
            permitted={str(Path(x).resolve()).casefold() for x in item.get('allowed_projects',[])}
            if meta.get('stage')!='probe' and (not meta.get('project') or str(Path(meta['project']).resolve()).casefold() not in permitted):
                raise ValueError('此作品尚未授权免费渠道处理正文与记忆')
            from .writer_runner import strict_json
            settings=strict_json(Path.home()/'.dsh/our-free-model/settings.json',{})
            if settings.get('tokenSaver',{}).get('enabled',True):raise ValueError('dsh 提示词压缩已开启，已停止发送原始创作材料')
        price=item.get('pricing',{}).get(binding['model_id'])
        if item.get('protocol')=='free_pool':price={'input':'0','output':'0','cached':'0','currency':'CNY'}
        if binding['model_id'] in item.get('free_models',[]):
            price={'input':'0','output':'0','cached':'0','currency':'CNY','revision':item.get('revision',0)}
        reservation=None;db=costs.META.get().get('db') or os.getenv('NOVEL_HELPER_COST_DB')
        if price is None and item.get('legacy_pricing') and db:
            price=costs.price_for(costs.pricing(db),costs.provider(item['base_url']),binding['model_id'],item['id'])
        if fallback:
            # Explicit chains only; neither model names nor a missing quote imply free.
            from .retry_budget import extension
            from . import bridge
            project=costs.META.get().get('project')
            if not project:raise ValueError('备选请求缺少作品归属')
            from datetime import datetime
            from zoneinfo import ZoneInfo
            # A successful failover grants this connection for the remainder
            # of this role execution, including tool rounds and the draft.
            # Paid requests still reserve and settle separately below. The
            # grant is never shared across books or process restarts.
            state=EXECUTION_ROUTES.get();key=self._route_key()
            reused=key in self._granted or state is not None and key in state['grants']
            budget=True if reused else extension({'project':project,'book':str(project),'account':'provider-fallback',
                'recovery_policy':{'extra_attempts_per_day':6}},datetime.now(ZoneInfo('Asia/Shanghai')),immediate=True,
                routing=self._config['providers'][self._binding()['provider_id']].get('protocol')=='free_pool')
            if budget is None:
                if self._config['providers'][self._binding()['provider_id']].get('protocol')=='free_pool':
                    from .free_pool import PoolWait,next_day
                    raise PoolWait('今日额外恢复次数已用完，等待次日恢复',next_day())
                from .retry_budget import RecoveryBudgetExhausted
                raise RecoveryBudgetExhausted(datetime.now(ZoneInfo('Asia/Shanghai')))
            self._granted.add(key)
            if state is not None:state['grants'].add(key)
            from decimal import Decimal
            free=bool(price and price.get('currency') in {'CNY','USD'} and all(Decimal(str(price.get(k,price.get('input','-1'))))==0 for k in ('input','output','cached')))
            from .resource_policy import public as resource_policy
            if not free and resource_policy(self._config)['fallback_cost_limit_cny'] is not None:
                from .fallback_budget import reserve
                try:reservation=reserve(db,project,price,messages,max_tokens)
                except ValueError as exc:
                    if '20元' in str(exc) and self._config['providers'][self._binding()['provider_id']].get('protocol')=='free_pool':
                        from .free_pool import PoolWait,next_day
                        raise PoolWait('今日20元付费回退预算已用完，等待免费额度恢复',next_day()) from None
                    raise
        try:
            with costs.scope(provider_id=item['id'],provider_name=item['name'],provider_price=price if price is not None else False,
                pricing_scope='legacy' if item.get('legacy_pricing') else 'provider',
                fallback_from=self._binding()['provider_id'] if fallback else None,
                fallback_from_model=self._binding().get('model_id') if fallback else None,
                fallback_reason='primary_failure_or_cooldown' if fallback else None,
                fallback_reservation=reservation):yield
        finally:
            if reservation:
                from .fallback_budget import settle
                settle(db,reservation)
    async def chat(self,messages,temperature=0.7,max_tokens=4000,response_format=None):
        return await self._call('chat',messages,temperature=temperature,max_tokens=max_tokens,response_format=response_format)
    async def chat_with_tools(self,messages,tools,temperature=0.3,max_tokens=2000):
        return await self._call('chat_with_tools',messages,tools=tools,temperature=temperature,max_tokens=max_tokens)
    async def _call(self,method,messages,*args,**kwargs):
        from .failure_info import details
        for index,binding in self._candidates():
            client=self._primary if index==0 else self._factory(binding)
            object.__setattr__(self,'_client',client)
            try:
                inputs={'messages':messages,'tools':kwargs['tools']} if 'tools' in kwargs else messages
                with self._scope(binding,index>0,inputs,kwargs.get('max_tokens',4000)):
                    result=await getattr(client,method)(messages,*args,**kwargs)
                self._remember(index,client);return result
            except Exception as exc:
                # Output exhaustion belongs to the caller's bounded format/
                # budget repair. It is not evidence that a connection is down.
                meta=getattr(client,'last_response_meta',{})
                if type(exc).__name__=='AIOutputError' and isinstance(meta,dict) and meta.get('finish_reason')=='length':raise
                detail=details(exc)
                self._failed(index,binding,detail)
                if detail.get('failure_kind')=='recovery_cooldown' or index>0 and detail.get('failure_kind')=='free_pool_wait':raise
                if index==len(self._options())-1 or not (detail.get('retryable') is True or detail.get('failure_kind') in {'authentication','configuration_or_access'}):raise
    async def chat_stream(self,messages,temperature=0.7,max_tokens=16000):
        from .failure_info import details
        for index,binding in self._candidates():
            client=self._primary if index==0 else self._factory(binding);emitted=False
            try:
                with self._scope(binding,index>0,messages,max_tokens):
                    async for chunk in client.chat_stream(messages,temperature=temperature,max_tokens=max_tokens):
                        if str(chunk).startswith('[ERROR]'):raise RuntimeError(str(chunk))
                        emitted=emitted or bool(str(chunk or '').strip())
                        yield chunk
                    if not emitted:
                        from .failure_info import EmptyModelStream
                        raise EmptyModelStream('模型流未返回可见正文，尝试已配置且预算允许的备选')
                self._remember(index,client);return
            except Exception as exc:
                self._failed(index,binding,details(exc))
                if details(exc).get('failure_kind')=='recovery_cooldown' or index>0 and details(exc).get('failure_kind')=='free_pool_wait':raise
                if emitted or index==len(self._options())-1 or details(exc).get('retryable') is False:raise
