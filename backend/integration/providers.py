"""Credential-isolated provider registry and legacy-preserving migration."""
import copy
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROTOCOLS = {'openai_compatible', 'dsh_local', 'dsh_channel','ofm_standalone','free_pool'}


def migrate(config):
    doc = copy.deepcopy(config)
    if doc.get('provider_schema') == 1:
        return doc
    pool = doc.setdefault('providers', {})
    def register(url, key):
        from .model_roles import validate_url
        url = validate_url(url or 'https://api.openai.com/v1')
        # Credential equality is evaluated locally, never exposed or persisted as a hash.
        found = next((k for k, v in pool.items() if v['base_url'] == url and v.get('api_key', '') == key), None)
        if found:return found
        identity = 'provider-' + uuid.uuid4().hex[:12]
        pool[identity] = {'id': identity, 'name': '现有接口 ' + str(len(pool) + 1),
            'base_url': url, 'api_key': key, 'protocol': 'openai_compatible',
            'enabled': True, 'revision': 1, 'models': [], 'pricing': {}, 'last_check': None}
        pool[identity]['legacy_pricing']=True
        return identity
    base_url = doc.get('base_url') or 'https://api.openai.com/v1'
    base_key = doc.get('api_key') or os.getenv('AI_API_KEY', '')
    default_id = register(base_url, base_key)
    doc['default_binding'] = {'provider_id': default_id, 'model_id': doc.get('model', ''), 'fallbacks': []}
    for role, item in doc.get('roles', {}).items():
        url = item.get('base_url') or base_url
        key = item.get('api_key') or (base_key if url.rstrip('/') == base_url.rstrip('/') else '')
        item.update(provider_id=register(url, key), model_id=item.get('model') or doc.get('model', ''), fallbacks=[])
    doc['provider_schema'] = 1
    return doc


def public(config):
    return [{k: copy.deepcopy(v) for k, v in item.items() if k != 'api_key'} |
            {'has_key': bool(item.get('api_key'))} for item in config.get('providers', {}).values()]


def bind_legacy(config, roles):
    """Map legacy form writes onto the registry, preserving unrelated bindings."""
    if config.get('provider_schema') != 1:return
    from .model_roles import connection
    legacy=copy.deepcopy(config);legacy.pop('provider_schema',None)
    for role in roles:
        connection_role='B' if role=='default' else role
        settings=copy.deepcopy(legacy)
        if role=='default':settings['multi_model']=False
        else:settings['multi_model']=True
        resolved=connection(connection_role,settings)
        identity=next((k for k,v in config['providers'].items() if v.get('enabled') and v['base_url']==resolved['base_url'] and v.get('api_key')==resolved['api_key']),None)
        if identity is None:
            updated,identity=save(config,None,{'name':'现有接口 '+str(len(config['providers'])+1),'base_url':resolved['base_url'],'api_key':resolved['api_key']})
            config['providers']=updated['providers']
        binding=config.get('default_binding',{}) if role=='default' else config.get('roles',{}).get(role,{})
        unchanged=binding.get('provider_id')==identity and binding.get('model_id')==resolved['model']
        value={'provider_id':identity,'model_id':resolved['model'],'fallbacks':binding.get('fallbacks',[]) if unchanged else []}
        if 'reasoning_effort' in binding:value['reasoning_effort']=binding['reasoning_effort']
        if role=='default':config['default_binding']=value
        else:config['roles'][role].update(value)


def refresh_legacy(config):
    """Keep older entry points mapped to the same saved provider connection."""
    default=config.get('default_binding',{})
    if default.get('provider_id') and default.get('model_id'):config.update(resolve(config,default))
    for value in config.get('roles',{}).values():
        if value.get('provider_id') and value.get('model_id'):value.update(resolve(config,value))


def resolve(config, binding):
    if not isinstance(binding, dict):raise ValueError('模型绑定必须为对象')
    from .reasoning import validate
    validate(binding.get('reasoning_effort','auto'))
    pool = config.get('providers', {})
    identity = binding.get('provider_id')
    if not isinstance(identity,str) or not identity:raise ValueError('供应商ID无效')
    provider = pool.get(identity)
    if not isinstance(provider, dict) or not provider.get('enabled', True):
        raise ValueError('模型供应商不存在或已停用')
    if provider.get('protocol') not in PROTOCOLS:
        raise ValueError('暂不支持此原生协议，请使用 OpenAI 兼容接口')
    from .model_roles import validate_url
    url = validate_url(provider['base_url'])
    model = binding.get('model_id')
    if not isinstance(model,str) or len(model)>200 or any(ord(c)<32 for c in model):raise ValueError('模型ID无效')
    model=model.strip()
    if not model or not provider.get('api_key'):
        raise ValueError('供应商缺少模型或密钥')
    if provider.get('protocol')=='dsh_channel' and not model.startswith(provider.get('channel_id','!')+'/'):
        raise ValueError('模型不属于此账号渠道，请读取本渠道模型后选择')
    if provider.get('protocol')=='free_pool' and model!='auto':raise ValueError('免费渠道池请选择auto模型')
    return {'base_url': url, 'api_key': provider['api_key'], 'model': model}


def save(config, identity, payload):
    from .model_roles import validate_url
    doc = migrate(config)
    identity = identity or 'provider-' + uuid.uuid4().hex[:12]
    old = doc['providers'].get(identity, {})
    allowed = {'name', 'base_url', 'api_key', 'protocol', 'enabled', 'pricing', 'free_models', 'allowed_projects'}
    if not isinstance(payload,dict) or set(payload) - allowed:raise ValueError('供应商包含未知字段')
    if 'enabled' in payload and type(payload['enabled']) is not bool:raise ValueError('启用状态必须为布尔值')
    url = validate_url(payload.get('base_url', old.get('base_url', '')))
    protocol = payload.get('protocol', old.get('protocol', 'openai_compatible'))
    if protocol not in PROTOCOLS:raise ValueError('不支持的供应商协议')
    if protocol in {'dsh_local','dsh_channel','ofm_standalone','free_pool'}:
        from urllib.parse import urlsplit
        if urlsplit(url).hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise ValueError('dsh 网关必须是本机地址')
    changed = old.get('base_url') != url
    supplied = payload.get('api_key')
    if supplied is not None and (not isinstance(supplied,str) or len(supplied)>8192):raise ValueError('密钥格式无效')
    if changed and old and not supplied:raise ValueError('接口地址改变，需要提供新密钥')
    key = old.get('api_key', '') if supplied is None else str(supplied).strip()
    name = str(payload.get('name', old.get('name', ''))).strip()
    if not name or len(name) > 100:raise ValueError('供应商名称应为1–100字')
    if payload.get('enabled') is False and referenced(doc, identity):raise ValueError('请先解除通用模型、角色及备选链绑定')
    price = copy.deepcopy(payload.get('pricing', old.get('pricing', {})))
    if not isinstance(price, dict):raise ValueError('价格必须为模型映射')
    from .costs import number
    for model, value in price.items():
        if not isinstance(model,str) or not model.strip() or len(model)>200:raise ValueError('报价模型ID无效')
        if not isinstance(value, dict) or value.get('currency', 'CNY') not in {'CNY', 'USD'} or any(k not in value for k in ('input','output')):raise ValueError('模型报价必须包含输入和输出价格')
        for field in ('input', 'output', 'cached'):
            if field in value:number(value[field])
        value.setdefault('cached',value.get('input','0'))
        value.setdefault('currency','CNY')
        if 'usd_to_cny' in value and float(number(value['usd_to_cny'])) <= 0:raise ValueError('汇率必须大于零')
    free = payload.get('free_models',old.get('free_models',[]))
    if not isinstance(free,list) or len(free)>10000 or any(not isinstance(x,str) or not x.strip() or len(x)>200 for x in free):raise ValueError('免费模型清单无效')
    permitted=payload.get('allowed_projects',old.get('allowed_projects',[]))
    if not isinstance(permitted,list) or any(not isinstance(x,str) or not Path(x).is_absolute() for x in permitted):raise ValueError('作品隐私授权无效')
    doc['providers'][identity] = {**old, 'id': identity, 'name': name, 'base_url': url, 'api_key': key,
        'protocol': protocol, 'enabled': payload.get('enabled', old.get('enabled', True)),
        'revision': old.get('revision', 0) + 1, 'pricing': price,
        'free_models': free,
        'allowed_projects': permitted,
        'models': [] if changed or supplied is not None and supplied != old.get('api_key') else old.get('models', []),
        'last_check': None if changed or supplied is not None and supplied != old.get('api_key') else old.get('last_check')}
    refresh_legacy(doc)
    return doc, identity


def referenced(doc, identity):
    if identity=='ofm-standalone' and 'free-pool' in doc.get('providers',{}):return True
    for binding in [doc.get('default_binding', {}), *doc.get('roles', {}).values()]:
        if binding.get('provider_id') == identity or any(b.get('provider_id') == identity for b in binding.get('fallbacks', [])):
            return True
    return False


def discover(config, identity):
    from manager import ai_tools
    item = config.get('providers', {}).get(identity)
    if not item:raise KeyError('供应商不存在')
    if not item.get('api_key'):raise ValueError('此供应商尚未保存密钥，不会借用环境或其他供应商凭据')
    if item.get('protocol')=='free_pool':return {'models':['auto'],'count':1}
    if item.get('protocol')=='ofm_standalone':
        from . import ofm_runtime
        value=ofm_runtime.request('/api/management/summary')
        models=[r['id'] for r in value.get('catalog',[]) if r.get('routable')]
        item.update(models=models,last_check={'at':datetime.now(timezone.utc).isoformat(),'status':'models_read','count':len(models)})
        return {'models':models,'count':len(models)}
    if item.get('protocol')=='dsh_channel':
        from . import free_channels
        from urllib.parse import urlsplit
        result,key=free_channels.scan(urlsplit(item['base_url']).port)
        if key!=item['api_key']:raise ValueError('渠道网关密钥已轮换，请重新接入此渠道')
        models=[x['id'] for x in result['models'] if x['channel']==item.get('channel_id')]
        item.update(models=models,last_check={'at':result['checked_at'],'status':'models_read','count':len(models)})
        return {'models':models,'count':len(models)}
    result = ai_tools.discover(item['base_url'], None, item,registered=True)
    item.update(models=result['models'], last_check={'at': datetime.now(timezone.utc).isoformat(), 'status': 'models_read', 'count': result['count']})
    return result


def verify_dsh_gateway(base_url):
    from urllib.request import build_opener,ProxyHandler
    from urllib.parse import urlsplit
    parts=urlsplit(base_url)
    if parts.scheme!='http' or parts.hostname not in {'127.0.0.1','localhost','::1'}:raise ValueError('dsh 仅允许本机网关')
    endpoint=f'{parts.scheme}://{parts.netloc}/health'
    try:
        with build_opener(ProxyHandler({})).open(endpoint,timeout=3) as response:
            body=response.read(4097)
        if len(body)>4096:raise ValueError('网关身份响应过大')
        data=json.loads(body)
        if data.get('service')!='our-free-model' or data.get('ok') is not True:raise ValueError('不是 Our Free Model 网关')
    except (OSError,ValueError,AttributeError) as exc:
        raise ValueError('未核实 dsh 实际监听地址；尚未发送网关密钥，请在插件核对实际端口') from exc


def import_dsh(config, settings_path=None):
    """Read only the named plugin's local forward configuration; never its accounts."""
    from .writer_runner import strict_json
    path = Path(settings_path) if settings_path else Path.home() / '.dsh' / 'our-free-model' / 'settings.json'
    settings = strict_json(path, {})
    forward = settings.get('forward') or settings.get('forwarding') or {}
    if not isinstance(forward, dict) or not forward.get('enabled'):
        raise ValueError('请先在 dsh → Our Free Model → 本地转发中启用网关')
    if settings.get('tokenSaver',{}).get('enabled',True):
        raise ValueError('dsh 提示词压缩仍开启，尚不能用于正式小说；请先关闭插件的提示词压缩，再连接。本助手不会擅自修改其他 dsh 使用场景')
    port = forward.get('port')
    key = settings.get('forwardKey') or forward.get('key')
    if type(port) is not int or not 1 <= port <= 65535 or not isinstance(key, str) or not key:
        raise ValueError('dsh 本地转发端口或密钥不可用；请在插件中核对')
    verify_dsh_gateway(f'http://127.0.0.1:{port}/v1')
    existing = next((k for k,v in config.get('providers',{}).items() if v.get('protocol') == 'dsh_local'), None)
    from . import scheduler
    projects={job['project'] for job in scheduler.load_scheduler().get('jobs',{}).values() if job.get('enabled')}
    if len(projects)!=1:raise ValueError('dsh 正文隐私授权需明确唯一作品，目前不会自动扩大至其他书籍')
    return save(config, existing, {'name': 'Our Free Model · 本机', 'base_url': f'http://127.0.0.1:{port}/v1',
        'api_key': key, 'protocol': 'dsh_local', 'enabled': True,'allowed_projects':list(projects)})
