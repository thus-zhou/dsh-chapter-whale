"""Own independent OFM process, private data, bounded server-side management."""
import json
import hashlib
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import Request,build_opener,ProxyHandler
from . import bridge,writer_runner
from .free_channels import NoRedirect

ROOT=bridge.COMBINED_ROOT
DATA=ROOT/'integration_data'
HOME=DATA/'ofm-home'
INFO=DATA/'ofm-service.json'
CONTROL=DATA/'ofm-control.json'
SOURCE_REVISION='25151bab43ff28bfc0eef5a3dbec4443ecc6d2f2'


def verify_source():
    source=ROOT/'vendor/our-free-model-source'
    doc=strict(ROOT/'vendor/ofm-source-lock.json')
    if doc.get('revision')!=SOURCE_REVISION or not doc.get('files'):raise ValueError('独立服务来源锁定信息不完整')
    for name,digest in doc['files'].items():
        target=source/name
        if not target.resolve().is_relative_to(source.resolve()) or target.is_symlink():raise ValueError('独立服务源文件路径异常')
        if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('独立服务源码已变化，需重新审查；未执行变更后的代码')


def strict(path):
    value=writer_runner.strict_json(path,{})
    if not isinstance(value,dict):raise ValueError('免费渠道状态损坏，未按空数据覆盖')
    return value


def endpoint():
    info=strict(INFO);parts=urlsplit(info.get('url',''))
    if info.get('product')!='novel-helper-ofm' or parts.scheme!='http' or parts.hostname!='127.0.0.1' or not parts.port or parts.path or parts.query or parts.username or parts.password or parts.fragment:
        raise ValueError('独立免费渠道服务尚未启动')
    return info,parts


def health():
    info,parts=endpoint()
    with build_opener(ProxyHandler({}),NoRedirect()).open(info['url']+'/health',timeout=2) as response:
        raw=response.read(4097)
    if len(raw)>4096:raise ValueError('免费渠道身份响应异常')
    value=json.loads(raw)
    lock=strict(HOME/'service.lock')
    if value.get('service')!='our-free-model-standalone' or value.get('ok') is not True or lock.get('pid')!=info.get('pid') or info.get('source_lock_sha256')!=hashlib.sha256((ROOT/'vendor/ofm-source-lock.json').read_bytes()).hexdigest():
        raise ValueError('无法确认免费渠道服务身份，未发送密钥')
    if os.name=='nt':
        # Pin the owner and command line, including the data-isolated wrapper.
        pid=info.get('pid')
        if type(pid) is not int or pid<=0:raise ValueError('服务进程标识无效')
        script=str(ROOT/'integration/ofm_service.mjs').replace("'","''")
        code=f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; if($p.Name -notmatch '^node[.]exe$' -or $p.CommandLine -notlike '*{script}*'){{exit 2}}; $c=Get-NetTCPConnection -State Listen -LocalPort {parts.port} -ErrorAction SilentlyContinue; if(-not ($c | Where-Object {{$_.OwningProcess -eq {pid} -and $_.LocalAddress -eq '127.0.0.1'}})){{exit 3}}"
        result=subprocess.run(['powershell.exe','-NoProfile','-Command',code],capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise ValueError('独立渠道端口归属不符，未发送密钥')
    return info


def status():
    try:
        info=health()
        return {'running':True,'enabled':strict(CONTROL).get('enabled',False),'mode':'independent',
            'version':info.get('version'),'endpoint':info['url']+'/v1','source_revision':info.get('source_revision')}
    except (OSError,ValueError,subprocess.SubprocessError):
        return {'running':False,'enabled':strict(CONTROL).get('enabled',False),'mode':'independent'}


def ensure_started(start=False):
    with writer_runner.file_lock(DATA/'ofm-service-start.lock',blocking=True):
        control=strict(CONTROL)
        if not start and not control.get('enabled'):raise ValueError('请先在网页启动独立免费渠道服务')
        try:return health()
        except (OSError,ValueError,subprocess.SubprocessError):pass
        HOME.mkdir(parents=True,exist_ok=True)
        if os.name!='nt':raise ValueError('本版本凭据保护要求Windows DPAPI')
        # New independent directory only. Do not touch the user's dsh directory.
        if HOME.resolve()!=HOME.absolute() or HOME.is_symlink():raise ValueError('凭据目录不可为链接')
        user=os.environ.get('USERNAME')
        result=subprocess.run(['icacls',str(HOME),'/inheritance:r','/grant:r',f'{user}:(OI)(CI)F'],capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise ValueError('无法限制独立凭据目录权限，尚未启动')
        # Fail before the upstream JsonStore can replace a damaged file.
        for name in ('settings.json','stats.json','catalog.json','availability.json','channel-credentials.json'):
            if (HOME/name).exists():strict(HOME/name)
        node=shutil.which('node')
        if not node:raise ValueError('未找到Node.js运行环境')
        verify_source()
        env=os.environ.copy()
        for key in list(env):
            if key.startswith('DSH_') or key.startswith('OFM_'):env.pop(key,None)
        env.update(NOVEL_HELPER_CREDENTIAL_CODEC=str(ROOT/'integration/credential_codec.py'),
            NOVEL_HELPER_PYTHON=str(ROOT/'.venv/Scripts/python.exe'),NOVEL_HELPER_CHECKIN_OPT_IN='1')
        subprocess.Popen([node,str(ROOT/'integration/ofm_service.mjs')],cwd=str(ROOT),env=env,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if start:bridge.write_json_atomic(CONTROL,{'enabled':True,'updated_at':bridge.now_iso()})
        for _ in range(25):
            try:return health()
            except (OSError,ValueError,subprocess.SubprocessError):time.sleep(.5)
        raise ValueError('独立渠道服务未就绪，未更改正式模型；请检查运行环境或占用')


def request(path,body=None,timeout=30):
    if path not in {'/api/management/summary','/api/management/channels/rpc','/api/management/models/refresh'}:
        raise ValueError('未开放该免费服务管理操作')
    info=health()
    key=strict(HOME/'settings.json').get('forwardKey')
    if not isinstance(key,str) or not key:raise ValueError('独立渠道密钥不可用')
    headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
    wire=None if body is None else json.dumps(body,ensure_ascii=False).encode('utf-8')
    req=Request(info['url']+path,data=wire,headers=headers)
    try:
        with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=timeout) as response:
            raw=response.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:raise ValueError('免费渠道响应过大')
        return json.loads(raw)
    except HTTPError as exc:
        raise ValueError(f'渠道服务拒绝操作（HTTP {exc.code}），请检查登录、额度或服务状态') from None


RPC_FIELDS={
 'provider.status':{'providers'},'provider.setEnabled':{'provider','enabled'},
 'account.list':{'provider'},'account.create':{'provider','zcodeProvider'},
 'account.delete':{'accountId'},'account.refresh':{'accountId'},'account.test':{'accountId'},
 'account.update':{'accountId','patch'},'login.poll':{'provider','accountId'},
 'login.sendSms':{'provider','accountId','phone'},'login.submitSms':{'provider','accountId','code','msgid','phone'},
 'credits.status':{'provider'},'credits.balances':{'provider','force'},'credits.claimAll':{'provider'},
 'model.list':{'provider'},'model.setDisabled':{'provider','modelId','disabled'},
 'model.clearDead':{'provider','modelId'},'model.setAllDisabled':{'provider','disabled'},
 'usage.autoCheckin':{'enabled'},
}


def clean(value):
    """No credential export, gateway key or upstream error-body passthrough."""
    forbidden={'access_token','refresh_token','api_key','apiKey','forwardKey','secret_access_key','security_token','credential','credentials','credentialRef','token','key','secret','raw','headers','request','details','stack'}
    if isinstance(value,dict):return {k:('渠道返回提示，请检查授权、额度或网络。' if k in {'error','message'} and v else clean(v)) for k,v in value.items() if k not in forbidden}
    if isinstance(value,list):return [clean(x) for x in value]
    return value


def rpc(method,payload):
    from .free_channels import CHANNEL_IDS
    if not isinstance(method,str):raise ValueError('渠道操作名无效')
    fields=RPC_FIELDS.get(method)
    if fields is None or not isinstance(payload,dict) or set(payload)-fields:raise ValueError('未开放该渠道操作或字段')
    required=({'providers'} if method=='provider.status' else {'provider'} if 'provider' in fields else set())
    if 'accountId' in fields and method not in {'login.sendSms','login.submitSms'}:required.add('accountId')
    if not required.issubset(payload):raise ValueError('渠道操作缺少必要字段')
    if 'provider' in payload and payload['provider'] not in CHANNEL_IDS:raise ValueError('渠道无效')
    if 'providers' in payload and (not isinstance(payload['providers'],list) or any(x not in CHANNEL_IDS for x in payload['providers'])):raise ValueError('渠道列表无效')
    if method=='account.update' and (not isinstance(payload.get('patch'),dict) or set(payload['patch'])-{'nickname','enabled'}):raise ValueError('账号更新字段无效')
    if 'accountId' in payload and (not isinstance(payload['accountId'],str) or not re.fullmatch(r'[a-z0-9-]{1,160}',payload['accountId'])):raise ValueError('账号标识无效')
    if 'accountId' in payload and 'provider' in payload and not payload['accountId'].startswith(payload['provider']+'-'):raise ValueError('账号与渠道不匹配')
    if method=='account.update':
        patch=payload['patch']
        if 'enabled' in patch and type(patch['enabled']) is not bool:raise ValueError('账号开关必须为布尔值')
        if 'nickname' in patch and (not isinstance(patch['nickname'],str) or len(patch['nickname'])>120):raise ValueError('账号昵称过长或无效')
    for key in ('enabled','disabled','force'):
        if key in payload and type(payload[key]) is not bool:raise ValueError('开关字段必须为布尔值')
    if len(json.dumps(payload))>16384:raise ValueError('渠道请求过大')
    result=request('/api/management/channels/rpc',{'method':method,'payload':payload},timeout=190)
    if result.get('ok') is not True:
        return {'ok':False,'error':{'code':'channel_operation_failed','message':'渠道操作未完成，请检查登录、验证码、额度或网络后重试。'}}
    if method=='login.poll' and result.get('value',{}).get('done') is True and result.get('value',{}).get('success') is True:
        from .free_pool import authorized_login
        authorized_login(payload['provider'])
    return clean(result)


def restore_if_enabled():
    if strict(DATA/'maintenance.json').get('state')=='maintenance':return {'state':'maintenance'}
    if not strict(CONTROL).get('enabled'):return {'state':'disabled'}
    try:
        info=ensure_started()
        bridge.write_json_atomic(DATA/'ofm-alert.json',{'state':'healthy','checked_at':bridge.now_iso()})
        return {'state':'running','pid':info['pid']}
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError):
        bridge.write_json_atomic(DATA/'ofm-alert.json',{'state':'needs_attention','checked_at':bridge.now_iso(),
            'message':'独立免费渠道服务未恢复；正式账号和模型未改动。请在免费额度工作台检查。'})
        return {'state':'needs_attention'}


if __name__=='__main__':print(restore_if_enabled())
