"""Small explicit role probes: no novels, no fallback and no saved binding edits."""
import asyncio
import copy
import time
import json
from datetime import datetime,timezone
from fastapi import HTTPException
from integration import bridge,costs,model_roles,providers,reasoning,writer_runner
from integration.failure_info import details


class ProbeIncomplete(ValueError):
    pass


async def exercise(client,role):
    """One synthetic request for the capability actually used by this role."""
    if role=='B':
        chunks=[]
        async for chunk in client.chat_stream([{'role':'user','content':'连接检测：请用中文写一句完整的话，不要解释。'}],temperature=0,max_tokens=4096):
            chunks.append(str(chunk or ''))
            if sum(map(len,chunks))>32768:raise ProbeIncomplete('检测响应过长，未验收')
        if not ''.join(chunks).strip():raise ProbeIncomplete('流式接口未返回有效文字')
        return 'stream'
    if role=='E':
        reply=await client.chat_with_tools([{'role':'user','content':'请调用 connectivity_check 工具一次。它只是连接检测，不执行任何外部操作。'}],
            [{'type':'function','function':{'name':'connectivity_check','description':'无副作用的连接检测','parameters':{'type':'object','properties':{},'additionalProperties':False}}}],temperature=0,max_tokens=4096)
        if not isinstance(reply,dict) or not any(isinstance(call,dict) and call.get('name')=='connectivity_check' for call in reply.get('tool_calls',[])):
            raise ProbeIncomplete('未收到指定工具调用，工具能力尚未验证')
        return 'tools'
    structured=role in {'A','D'}
    text=await client.chat([{'role':'user','content':'连接检测：只输出JSON对象 {"ok":true}。' if structured else '这是连接检测，不是创作任务。请仅回复：连接成功。'}],temperature=0,max_tokens=4096,**({'response_format':'json_object'} if structured else {}))
    if not str(text or '').strip():raise ProbeIncomplete('模型未返回有效短文本')
    if structured:
        try:value=json.loads(str(text).strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
        except ValueError:raise ProbeIncomplete('接口有响应，但未返回有效JSON，结构化能力尚未验证') from None
        if not isinstance(value,dict) or value.get('ok') is not True:raise ProbeIncomplete('结构化响应未通过检测')
    return 'json' if structured else 'text'


def snapshot(config_path):
    doc=writer_runner.strict_json(config_path.parent/'role_checks.json',{})
    if not isinstance(doc,dict):raise ValueError('模型检测记录损坏')
    allowed={'role','provider_id','model_id','reasoning_effort','provider_revision','tested_provider_id','tested_model_id',
             'checked_at','scope','note','status','content_received','probe_mode','failure_kind','http_status','error_code','retryable','message','elapsed_ms','next_retry_at'}
    if any(role not in {'default',*model_roles.ROLES} or not isinstance(value,dict) or set(value)-allowed for role,value in doc.items()):
        raise ValueError('模型检测记录损坏，未覆盖原文件')
    for value in doc.values():
        try:
            if value.get('status') not in {'ok','failed','inconclusive'} or datetime.fromisoformat(value['checked_at']).tzinfo is None:raise ValueError()
            reasoning.validate(value.get('reasoning_effort','auto'))
        except (ValueError,KeyError,TypeError):raise ValueError('模型检测记录损坏，未覆盖原文件') from None
    return doc


def install(app,load,config_path):
    path=config_path.parent/'role_checks.json'
    locks={role:asyncio.Lock() for role in ('default',*model_roles.ROLES)}

    def read():
        return snapshot(config_path)

    @app.get('/api/ai/role-checks')
    def listing():return read()

    @app.post('/api/ai/roles/{role}/test')
    async def probe(role:str,payload:dict):
        if role not in locks:raise ValueError('分工只能为通用模型或A–E')
        if set(payload)-{'binding','provider_revision'}:raise ValueError('模型检测包含未知字段')
        read()  # Refuse a paid probe before touching a corrupt evidence file.
        config=providers.migrate(load())
        own=config.get('roles',{}).get(role,{})
        default=config.get('default_binding',{})
        saved=own if own.get('provider_id') else default
        binding=copy.deepcopy(payload['binding']) if 'binding' in payload else {k:v for k,v in saved.items() if k in {'provider_id','model_id','reasoning_effort'}}
        if not isinstance(binding,dict) or set(binding)-{'provider_id','model_id','reasoning_effort'}:raise ValueError('检测绑定无效')
        if 'reasoning_effort' not in binding:binding['reasoning_effort']=own.get('reasoning_effort',default.get('reasoning_effort','auto')) if role!='default' else default.get('reasoning_effort','auto')
        providers.resolve(config,binding)
        provider=config['providers'][binding['provider_id']]
        revision=provider.get('revision',0)
        if 'provider_revision' in payload and payload['provider_revision']!=revision:raise ValueError('供应商已更新，请刷新后检测')
        if locks[role].locked():raise HTTPException(409,'此角色正在检测，请等待当前结果')
        tested=copy.deepcopy(binding)
        if provider.get('protocol')=='free_pool':
            # A synthetic probe checks one configured candidate, not every
            # channel, and must not mutate production recovery budgets/state.
            candidates=[r for r in provider.get('pool_members',[]) if (role if role!='default' else 'B') in r.get('roles',[])]
            if not candidates:raise ValueError('免费池没有为此角色配置候选模型')
            tested.update(provider_id='ofm-standalone',model_id=candidates[0]['model_id'])
            providers.resolve(config,tested)
        config.update(multi_model=False,default_binding=tested)
        async with locks[role]:
            started=time.monotonic()
            result={'role':role,'provider_id':binding['provider_id'],'model_id':binding['model_id'],
                    'reasoning_effort':binding['reasoning_effort'],'provider_revision':revision,
                    'tested_provider_id':tested['provider_id'],'tested_model_id':tested['model_id'],
                    'checked_at':datetime.now(timezone.utc).isoformat(),
                    'scope':'one_pool_candidate' if binding['provider_id']!=tested['provider_id'] else 'selected_connection',
                    'note':'仅验证此角色的短请求能力，不代表长篇连续生成或平台发布均正常。思考档位是否被采纳由接口决定。'}
            client=None
            try:
                client=model_roles.service(role if role!='default' else 'B',config)
                client.timeout=45
                # The normal role context is preserved for attribution, but
                # the one-off snapshot contains no production fallback chain.
                with costs.scope(stage='probe',role=role):
                    mode=await asyncio.wait_for(exercise(client,role),timeout=60)
                result.update(status='ok',content_received=mode!='tools',probe_mode=mode)
            except Exception as exc:
                info=details(exc)
                # Never return raw exceptions, prompts, response bodies or keys.
                result.update(status='failed',content_received=False,**info,
                    message=('接口返回 HTTP '+str(info['http_status'])) if info.get('http_status') else '未收到有效响应，请检查模型能力、思考档位或稍后重试')
                meta=getattr(client,'last_response_meta',{})
                if isinstance(meta,dict) and meta.get('finish_reason')=='length':
                    result.update(status='inconclusive',message='接口已响应，但检测输出预算耗尽；请降低思考强度或在实际任务中验证')
                elif isinstance(exc,ProbeIncomplete):result.update(status='inconclusive',message=str(exc))
                elif info.get('http_status') in (400,422):result['message']='接口拒绝参数，请核对模型 ID 和思考档位是否受支持'
                elif info.get('http_status') in (401,403):result['message']='接口认证或权限失败，请检查该供应商密钥或渠道登录状态'
                elif info.get('http_status')==429:result['message']='渠道限流或额度不足，请稍后重试或检查额度'
            result['elapsed_ms']=round((time.monotonic()-started)*1000)
            def save():
                with writer_runner.file_lock(path.with_suffix('.lock'),blocking=True):
                    doc=read();doc[role]=result;bridge.write_json_atomic(path,doc)
            await asyncio.to_thread(save)
            return result
