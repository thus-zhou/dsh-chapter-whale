"""Read-only OFM channel metadata and explicit, loopback-only gateway import.

Never read the host credential vault, log in, claim credits or change dsh settings.
The channel gateway is NOT OFM's anonymous forward listener.
"""
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from integration import bridge, writer_runner, providers

CHANNELS = (
    ('codearts','CodeArts','华为云','CA'),
    ('buddy','WorkBuddy 国内版','腾讯','WB'),
    ('workbuddy','WorkBuddy 国际版','腾讯','WI'),
    ('lobsterai','LobsterAI','有道','LA'),
    ('qoder','Qoder','阿里系','QD'),
    ('qodercn','Qoder 中国版','阿里系','QC'),
    ('trae','TRAE','字节','TR'),
    ('cline','Cline','Cline','CL'),
    ('loomy','Loomy','讯飞','LM'),
    ('raccoon','Raccoon','商汤','RC'),
    ('minimax','MiniMax Code','MiniMax','MM'),
    ('zcode','ZCode','智谱','ZC'),
    ('gemini','Gemini','Google Code Assist','GM'),
)
CHANNEL_IDS={x[0] for x in CHANNELS}


def home():return Path.home()/'.dsh'


def cache_path():return bridge.RUNTIME_ROOT/'free-channel-catalog.json'


def verify_endpoint(base_url):
    from urllib.parse import urlsplit
    parts=urlsplit(base_url)
    if parts.scheme!='http' or parts.hostname!='127.0.0.1' or parts.path!='/v1' or parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError('账号渠道网关仅允许本机127.0.0.1的/v1端点')
    if parts.port not in owned_ports():raise ValueError('账号渠道网关不可用或端口已换用，尚未发送密钥')


def read_object(path):
    if not path.exists():return {}
    if path.is_symlink() or path.stat().st_size>2*1024*1024:raise ValueError('渠道元数据不安全或过大')
    value=writer_runner.strict_json(path,{})
    if not isinstance(value,dict):raise ValueError('渠道元数据损坏，请在 dsh 检查；本助手不会覆盖它')
    return value


def owned_ports():
    """Do not send a key to a port until its owner is the installed host."""
    if os.name!='nt':return []
    host=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'Programs/DeepSeek Harness/DeepSeek Harness.exe'
    expected=str(host).replace("'","''")
    script=f"""$ErrorActionPreference='Stop'
$taskHost='{expected}'
$taskOwners=@(Get-CimInstance Win32_Process | Where-Object {{$_.ExecutablePath -eq $taskHost}} | Select-Object -ExpandProperty ProcessId)
if ($taskOwners.Count -eq 0) {{ Write-Output '[]'; exit }}
$taskPorts=@(Get-NetTCPConnection -State Listen | Where-Object {{$_.LocalAddress -in @('127.0.0.1','::1') -and $_.OwningProcess -in $taskOwners}} | Select-Object -ExpandProperty LocalPort -Unique)
ConvertTo-Json -InputObject $taskPorts -Compress
"""
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,timeout=12,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise ValueError('暂时无法核实 dsh 监听进程，尚未发送密钥')
    ports=json.loads(result.stdout.decode('utf-8-sig').strip() or '[]')
    return sorted(p for p in ports if type(p) is int and 1<=p<=65535)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def get_json(url,key=None):
    headers={'Accept':'application/json'}
    if key:headers['Authorization']='Bearer '+key
    request=Request(url,headers=headers)
    with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=8) as response:
        body=response.read(2*1024*1024+1)
    if len(body)>2*1024*1024:raise ValueError('网关模型清单过大')
    return json.loads(body)


def scan(port=None):
    if port is not None and (type(port) is not int or not 1<=port<=65535):raise ValueError('端口应为1–65535')
    state=read_object(home()/'channel-pack/state.json')
    if state.get('gatewayEnabled') is False:raise ValueError('账号渠道网关已关闭，请在 dsh 中启用；不会自动改动开关')
    ports=owned_ports()
    if port is not None and port not in ports:raise ValueError('该端口并非已核实的 dsh 本机监听端口')
    candidates=[port] if port is not None else ports
    # Only this purpose-specific gateway key, not the dsh credential vault.
    key_path=home()/'openai-gateway/api-key'
    if not key_path.is_file() or key_path.is_symlink() or key_path.stat().st_size>8192:raise ValueError('未找到本机账号渠道网关密钥，请在插件中核对')
    key=key_path.read_text(encoding='utf-8').strip()
    if not key or any(ord(c)<33 for c in key):raise ValueError('本机网关密钥格式异常')
    for candidate in candidates:
        endpoint=f'http://127.0.0.1:{candidate}/v1'
        try:
            # Require this gateway's unauthenticated rejection before using key.
            try:get_json(endpoint+'/models')
            except HTTPError as exc:
                if exc.code!=401:continue
                body=exc.read(4096)
                if json.loads(body).get('error',{}).get('code')!='invalid_api_key':continue
            else:continue
            raw=get_json(endpoint+'/models',key)
            models=[]
            for row in raw.get('data',[]):
                identity=row.get('id') if isinstance(row,dict) else None
                if isinstance(identity,str) and 0<len(identity)<=200 and not any(ord(c)<32 for c in identity):
                    channel,separator,model=identity.partition('/')
                    if channel in CHANNEL_IDS and separator and model:models.append({'id':identity,'channel':channel})
            if not models:continue
            return {'endpoint':endpoint,'models':list({x['id']:x for x in models}.values()),'checked_at':bridge.now_iso()},key
        except (OSError,ValueError,AttributeError,TypeError):continue
    raise ValueError('尚未读到账号渠道模型。请保持 dsh 运行，并在插件“白嫖模型接入→网关”核对端口；未调用生成模型')


def snapshot(config,db_path):
    state=read_object(home()/'channel-pack/state.json')
    settings=read_object(home()/'our-free-model/settings.json')
    cache=read_object(cache_path())
    accounts=state.get('accounts',[])
    if not isinstance(accounts,list) or any(not isinstance(a,dict) for a in accounts):raise ValueError('渠道账号索引损坏')
    from integration import costs
    from zoneinfo import ZoneInfo
    day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    events=costs.event_rows(db_path) if Path(db_path).is_file() else []
    today=[]
    for event in events:
        try:
            at=datetime.fromisoformat(event.get('created_at','')).astimezone(ZoneInfo('Asia/Shanghai'))
            if at.date().isoformat()==day:today.append(event)
        except (ValueError,TypeError):continue
    rows=[]
    for identity,name,org,mark in CHANNELS:
        selected=[p for p in config.get('providers',{}).values() if p.get('protocol')=='dsh_channel' and p.get('channel_id')==identity]
        identifiers={p['id'] for p in selected}
        usage=[e for e in today if e.get('provider_id') in identifiers]
        tokens=sum(int(e.get('input_tokens') or 0)+int(e.get('output_tokens') or 0) for e in usage)
        local=[a for a in accounts if a.get('provider')==identity]
        models=[x['id'] for x in cache.get('models',[]) if x.get('channel')==identity]
        rows.append({'id':identity,'name':name,'org':org,'mark':mark,'accounts':len(local),
            'enabled_accounts':sum(a.get('enabled') is not False for a in local),'models':models,
            'imported':bool(selected),'provider_ids':list(identifiers),'today_calls':len(usage),'today_tokens':tokens,
            'usage_unknown':sum(e.get('metering')!='reported' for e in usage),
            'official_balance':None,'balance_source':'not_exposed_by_inference_gateway'})
    return {'channels':rows,'connected_channels':sum(x['accounts']>0 for x in rows),'channel_count':len(rows),
        'gateway_enabled':state.get('gatewayEnabled') is not False,'endpoint':cache.get('endpoint'),
        'checked_at':cache.get('checked_at'),'compression_enabled':settings.get('tokenSaver',{}).get('enabled',True),
        'model_count':sum(len(x['models']) for x in rows),'today':day,
        'management':'请在 dsh → Our Free Model → 白嫖模型接入中添加账号、刷新官方余额或领取额度。',
        'notice':'本地调用量不是官方剩余额度；网关可能包含付费模型，不自动标记为免费。'}


def import_channel(config,payload):
    channel=payload.get('channel_id')
    if channel not in CHANNEL_IDS:raise ValueError('渠道无效')
    if payload.get('authorize_project') is not True:raise ValueError('请确认本项目正文及必要记忆的渠道处理授权')
    from integration import scheduler
    projects={x['project'] for x in scheduler.load_scheduler().get('jobs',{}).values() if x.get('enabled')}
    if len(projects)!=1:raise ValueError('需要明确唯一作品的隐私授权，尚未接入')
    catalog,key=scan(payload.get('port'))
    models=[x['id'] for x in catalog['models'] if x['channel']==channel]
    if not models:raise ValueError('此渠道未返回可用模型，请先在 dsh 登录并刷新模型')
    existing=next((k for k,p in config.get('providers',{}).items() if p.get('protocol')=='dsh_channel' and p.get('channel_id')==channel),None)
    name=next(x[1] for x in CHANNELS if x[0]==channel)
    updated,identity=providers.save(config,existing,{'name':'OFM · '+name,'base_url':catalog['endpoint'],
        'api_key':key,'protocol':'dsh_channel','allowed_projects':list(projects)})
    updated['providers'][identity].update(channel_id=channel,models=models,last_check={'at':catalog['checked_at'],'status':'models_read','count':len(models)})
    return updated,identity,catalog
