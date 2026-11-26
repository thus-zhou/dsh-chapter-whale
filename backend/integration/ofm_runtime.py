"""托管独立免费渠道（OFM）进程、私有数据目录与受限的管理接口。

凭据编解码子进程的解释器契约（P03：确定性、可校验、不依赖 PATH 命中顺序）：

1. 运行进程自身 ``sys.executable``：非空、绝对路径、存在、是文件、可执行且能真正跑起来时
   直接采用。托管模式下它就是 Node 复制出来的 ``<工作区>/.venv/Scripts/python.exe``，
   与父进程同一 Windows 用户、同一 DPAPI 作用域，因此能解开旧密文。
2. 显式配置 ``NOVEL_HELPER_PYTHON``：只在第 1 条不可用（宿主嵌入解释器为空或无效）时
   才采用；一旦设置就必须校验通过，校验失败直接报错、不静默回退，避免换错用户作用域。
3. 托管/构建包路径 ``<工作区>/.venv/Scripts/python.exe``：Node 把发行包 ``runtime/python``
   复制到这里（即 ``config.python`` 的落点），宿主解释器不可用时用它兜底。
4. 以上都不可用：抛中文可操作错误（说明缺什么、下一步做什么）；全程不硬编码盘符，
   也不裸用 ``"python"`` 依赖 PATH 顺序。

``ensure_started()`` 在拉起 Node 服务之前先跑 ``credential_runtime()``：解释器与
``credential_codec.py`` 必须完成一次当前用户 DPAPI 的加解密往返。失败时 Node 侧凭据仓库
根本拿不到控制权，旧密文保持原样——Node 的保存路径同样是“先加密成功，才原子落盘”。
"""
import getpass
import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple
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
# 解释器契约用到的常量：只在这里写一次，避免调用点各处拼路径。
HELPER_PYTHON_ENV='NOVEL_HELPER_PYTHON'
HELPER_CODEC_ENV='NOVEL_HELPER_CREDENTIAL_CODEC'
# Node 托管模式把发行包 runtime/python 复制到 <工作区>/.venv/Scripts，裸 Windows 布局。
MANAGED_PYTHON=Path('.venv')/'Scripts'/'python.exe'
# 编解码脚本与本模块同目录；开发模式（<repo>/backend/integration）和托管模式
# （<工作区>/integration）都必定成立，不依赖 NOVEL_HELPER_ROOT 是否已设置。
CODEC_SCRIPT=Path(__file__).resolve().parent/'credential_codec.py'
_NO_WINDOW=getattr(subprocess,'CREATE_NO_WINDOW',0)
_VERSION_PROBE='import sys;sys.stdout.write(str(sys.version_info[0]))'


def _validate_helper_python(value:object, source:str, timeout:float=15.0) -> Path:
    """校验候选解释器：绝对路径、存在、是文件、可执行，且真的能作为 Python 3 跑起来。

    失败一律抛中文 ``ValueError``，消息里带来源与路径，便于直接照着修。
    """
    text='' if value is None else str(value).strip()
    if not text:raise ValueError(f'{source}不可用：路径为空')
    try:candidate=Path(text).expanduser()
    except (OSError,ValueError) as error:raise ValueError(f'{source}不可用：路径无法解析') from error
    if not candidate.is_absolute():raise ValueError(f'{source}不可用：{candidate} 不是绝对路径')
    candidate=candidate.resolve()
    if not candidate.exists():raise ValueError(f'{source}不可用：{candidate} 不存在')
    if not candidate.is_file():raise ValueError(f'{source}不可用：{candidate} 不是文件')
    if os.name=='nt' and candidate.suffix.lower()!='.exe':raise ValueError(f'{source}不可用：{candidate} 不是 Windows 可执行文件（需要 python.exe）')
    if not os.access(candidate,os.X_OK):raise ValueError(f'{source}不可用：{candidate} 不可执行')
    try:
        probe=subprocess.run([str(candidate),'-B','-X','utf8','-c',_VERSION_PROBE],stdin=subprocess.DEVNULL,
            capture_output=True,timeout=timeout,creationflags=_NO_WINDOW)
    except (OSError,subprocess.SubprocessError) as error:
        raise ValueError(f'{source}不可用：{candidate} 无法运行（{error.__class__.__name__}）') from error
    if probe.returncode!=0 or probe.stdout.strip()!=b'3':
        raise ValueError(f'{source}不可用：{candidate} 无法作为 Python 3 运行（退出码 {probe.returncode}）')
    return candidate


def resolve_helper_python(self_python:Optional[object]=None, configured:Optional[object]=None,
        bundled:Optional[object]=None, root:Optional[object]=None) -> Path:
    """按模块 docstring 的三条优先级选出凭据编解码子进程的解释器。

    ``self_python``/``configured``/``bundled`` 允许测试注入；默认分别取
    ``sys.executable``、``os.environ[HELPER_PYTHON_ENV]``、``<root>/.venv/Scripts/python.exe``。
    """
    if self_python is None:self_python=sys.executable
    if configured is None:configured=os.environ.get(HELPER_PYTHON_ENV,'')
    if bundled is None:bundled=str(Path(root or ROOT)/MANAGED_PYTHON)
    reasons:List[str]=[]
    try:
        return _validate_helper_python(self_python,'运行进程自身（sys.executable）')
    except ValueError as error:
        reasons.append(str(error))
    # 显式配置只在自身解释器不可用时才看；一旦设置就必须可用，不做静默回退。
    if configured is not None and str(configured).strip():
        return _validate_helper_python(configured,f'显式配置 {HELPER_PYTHON_ENV}')
    try:
        return _validate_helper_python(bundled,'托管发行包解释器')
    except ValueError as error:
        reasons.append(str(error))
    raise ValueError('未找到可用的 Python 解释器：'+'；'.join(reasons)
        +f'。请重新安装完整发行包，或在设置里指定 python 路径（{HELPER_PYTHON_ENV} 指向 python.exe 的绝对路径，'
        +f'托管默认位置 {Path(root or ROOT)/MANAGED_PYTHON}）。')


def verify_credential_codec(python:object, codec:object=CODEC_SCRIPT, timeout:float=20.0) -> Path:
    """确认解释器 + 编解码脚本可用：子进程里跑一次当前用户 DPAPI 加解密往返。

    子进程不换用户名、不换令牌、不注入其它环境，因此与父进程是同一个 Windows 用户、
    同一个 DPAPI 作用域；只有它返回 ``ok`` 才允许 Node 侧凭据仓库开始读写。
    """
    interpreter=Path(str(python)).resolve()
    script=Path(str(codec)).resolve()
    if not interpreter.is_file():raise ValueError(f'凭据编解码组件不可用：解释器 {interpreter} 不存在或不是文件，旧凭据未被改动；请重新安装完整发行包')
    if not script.is_file():raise ValueError(f'凭据编解码组件不可用：{script} 不存在，旧凭据未被改动；请重新安装完整发行包')
    try:
        probe=subprocess.run([str(interpreter),'-B','-X','utf8',str(script),'probe'],input=b'',
            capture_output=True,timeout=timeout,creationflags=_NO_WINDOW)
    except (OSError,subprocess.SubprocessError) as error:
        raise ValueError(f'凭据编解码组件无法启动：{error.__class__.__name__}，旧凭据未被改动；请重新安装完整发行包') from error
    if probe.returncode!=0 or probe.stdout.strip()!=b'ok':
        detail=probe.stderr.decode('utf-8','replace').strip().replace('\n',' ')[:200] or f'退出码 {probe.returncode}'
        raise ValueError(f'凭据编解码组件不可用：{detail}，旧凭据未被改动；请确认当前 Windows 账号能访问用户配置目录，或重新安装完整发行包')
    return script


def credential_runtime(root:Optional[object]=None) -> Tuple[Path,Path]:
    """返回已经验证过的 (解释器, 编解码脚本)；任一环节不可用都抛中文错误。"""
    python=resolve_helper_python(root=root)
    return python,verify_credential_codec(python,CODEC_SCRIPT)


def verify_credential_store(path:object) -> Optional[Path]:
    """已有独立凭据文件必须是 DPAPI 信封；格式不对时宁可不启动，也不让新仓库覆盖旧值。"""
    target=Path(str(path))
    if not target.exists():return None
    doc=strict(target)
    if doc.get('schema')!='novel-helper.dpapi.v1' or not isinstance(doc.get('protected'),str) or not doc.get('protected'):
        raise ValueError(f'独立凭据文件不是 DPAPI 格式（{target.name}），未启动服务，也未改动旧凭据；请先备份该文件后重试')
    return target


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


def persist_service_url(live_base: str) -> bool:
    """Persist a self-healed loopback endpoint into the AI config.

    Only provider ``base_url`` fields are touched; the file is re-read first so
    keys already moved into the protected store stay out of this write, and the
    pre-heal file is kept as ``<name>.bak``. Best-effort: a failed write must
    never stop the in-flight model request.
    """
    from . import model_roles, writer_runner
    path = model_roles.config_path()
    if not path.is_file():
        return False
    try:
        with writer_runner.file_lock(path.with_suffix('.lock'), blocking=True):
            raw = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(raw, dict):
                return False
            providers = raw.get('providers')
            if not isinstance(providers, dict):
                return False
            changed = False
            for item in providers.values():
                if not isinstance(item, dict) or item.get('protocol') not in {'ofm_standalone', 'free_pool'}:
                    continue
                if item.get('base_url') != live_base:
                    item['base_url'] = live_base
                    changed = True
            if not changed:
                return False
            shutil.copy2(path, path.with_name(path.name + '.bak'))
            bridge.write_json_atomic(path, raw)
            return True
    except (OSError, ValueError):
        return False


def _resolve_node_runtime() -> Tuple[str, dict]:
    """Resolve Node.js or Electron-as-Node runtime without relying strictly on system PATH.

    ``NOVEL_HELPER_NODE`` is the host-selected runtime and outranks whatever
    ``node`` happens to be first on PATH; a stale Node 20 on PATH must not
    silently replace the DSH-managed binary.
    """
    candidates = [
        os.environ.get('NOVEL_HELPER_NODE', '').strip(),
        shutil.which('node'),
    ]
    if os.name == 'nt':
        pf = os.environ.get('ProgramFiles', r'C:\Program Files')
        local = os.environ.get('LOCALAPPDATA', '')
        candidates.extend([
            str(Path(pf) / 'nodejs' / 'node.exe'),
            str(Path(local) / 'Programs' / 'nodejs' / 'node.exe') if local else '',
        ])
    else:
        candidates.extend(['/opt/homebrew/bin/node', '/usr/local/bin/node', '/usr/bin/node'])
    for item in candidates:
        if item and Path(item).is_file():
            return str(Path(item).resolve()), {}
    electron = os.environ.get('NOVEL_HELPER_NODE_ELECTRON', '').strip()
    if electron and Path(electron).is_file():
        return str(Path(electron).resolve()), {'ELECTRON_RUN_AS_NODE': '1'}
    raise ValueError('未找到 Node.js 运行环境（需要 Node.js ≥22.21 或 ≥24.5，或从 DSH 桌面端启动插件）')


def node_version_supported(version: object) -> bool:
    """Whether this Node.js version honours ``NODE_USE_ENV_PROXY``.

    Node added env-proxy support in v22.21.0 and v24.5.0. Node 23 never
    received that backport (it was EOL before the change), so a bare
    ``>=22.21`` semver comparison is not enough.
    """
    text = str(version or '').strip().lower()
    match = re.match(r'^v?(\d+)\.(\d+)', text)
    if not match:
        return False
    major, minor = int(match.group(1)), int(match.group(2))
    if major == 22:
        return minor >= 21
    if major == 23:
        return False
    if major == 24:
        return minor >= 5
    return major >= 25


def _node_version(node: str, extra_env: dict) -> Optional[str]:
    env = os.environ.copy()
    env.update(extra_env or {})
    try:
        probe = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=10,
            stdin=subprocess.DEVNULL, env=env, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if probe.returncode:
        return None
    return (probe.stdout or probe.stderr or '').strip() or None


def _check_node_runtime(node: str, extra_env: dict, proxy_configured: bool) -> Tuple[bool, str]:
    """Validate the OFM Node runtime before spawning it.

    Without a proxy an old Node still works for direct connections, so it only
    produces a startup warning. With a proxy configured the request would fail
    with an opaque ``ENOTFOUND``, so an old Node is a hard, actionable error.
    """
    version = _node_version(node, extra_env)
    if version and node_version_supported(version):
        return True, version
    detail = f'当前 {version}' if version else '无法读取版本'
    message = (f'免费渠道代理需要 Node.js ≥22.21 或 ≥24.5（NODE_USE_ENV_PROXY 从这些版本才生效），{detail}；'
        '请安装受支持的 Node.js，或改用受支持的 Node 运行环境')
    if proxy_configured:
        raise ValueError(message)
    return False, f'{message}。未检测到代理，继续启动但不会经代理连接。'


def _detect_proxy_env() -> dict:
    """Propagate explicit or Windows system proxy so Node 22 fetch() reaches upstream free lanes."""
    env = {'NO_PROXY': '127.0.0.1,localhost,::1', 'no_proxy': '127.0.0.1,localhost,::1', 'NODE_USE_ENV_PROXY': '1'}
    for k in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy'):
        if os.environ.get(k):
            for name in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy'):
                if os.environ.get(name): env[name] = os.environ[name]
            return env
    if os.name != 'nt':
        return env
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as key:
            enabled, _ = winreg.QueryValueEx(key, 'ProxyEnable')
            if not enabled:
                return env
            server, _ = winreg.QueryValueEx(key, 'ProxyServer')
        raw = str(server or '').strip()
        if not raw:
            return env
        proxy_url = ''
        if '=' in raw:
            parts = dict(part.split('=', 1) for part in raw.split(';') if '=' in part)
            chosen = parts.get('https') or parts.get('http') or parts.get('socks')
            if chosen:
                proxy_url = chosen if '://' in chosen else f'http://{chosen}'
        else:
            proxy_url = raw if '://' in raw else f'http://{raw}'
        if proxy_url:
            env['HTTP_PROXY'] = proxy_url
            env['HTTPS_PROXY'] = proxy_url
    except Exception:
        pass
    return env


def _icacls_principal() -> str:
    """Resolve SID or qualified account name so Microsoft/AzureAD accounts don't fail icacls."""
    if os.name == 'nt':
        try:
            res = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True, text=True, timeout=8, creationflags=_NO_WINDOW)
            if res.returncode == 0 and res.stdout.strip():
                cols = [c.strip().strip('"') for c in res.stdout.strip().splitlines()[0].split(',')]
                if len(cols) >= 2 and cols[1].startswith('S-1-'):
                    return '*' + cols[1]
        except Exception:
            pass
        domain = os.environ.get('USERDOMAIN', '').strip()
        user = (os.environ.get('USERNAME') or getpass.getuser()).strip()
        if domain and user and '\\' not in user:
            return f'{domain}\\{user}'
        return user
    return getpass.getuser()


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
        # This check runs on every health() call: a 20s cache used to skip it,
        # so a listener that reused the port after a crash could pass.
        pid=info.get('pid')
        if type(pid) is not int or pid<=0:raise ValueError('服务进程标识无效')
        script=str(ROOT/'integration/ofm_service.mjs').replace("'","''")
        code=f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; if(-not $p -or $p.Name -notmatch '^node[.]exe$' -or -not $p.CommandLine -or $p.CommandLine.IndexOf('{script}',[System.StringComparison]::OrdinalIgnoreCase) -lt 0){{exit 2}}; $c=Get-NetTCPConnection -State Listen -LocalPort {parts.port} -ErrorAction SilentlyContinue; if(-not ($c | Where-Object {{$_.OwningProcess -eq {pid} -and $_.LocalAddress -eq '127.0.0.1'}})){{exit 3}}"
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


def _terminate_process(proc) -> None:
    """Stop an OFM child we started; never leave an orphan behind."""
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
    except OSError:
        return
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except OSError:
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def ensure_started(start=False):
    with writer_runner.file_lock(DATA/'ofm-service-start.lock',blocking=True):
        control=strict(CONTROL)
        if not start and not control.get('enabled'):raise ValueError('请先在网页启动独立免费渠道服务')
        try:return health()
        except (OSError,ValueError,subprocess.SubprocessError):pass
        HOME.mkdir(parents=True,exist_ok=True)
        if os.name!='nt':raise ValueError('本版本凭据保护要求Windows DPAPI')
        # 先把解释器与编解码组件验证通过：Node 侧凭据仓库在构造时解密、保存时先加密后落盘，
        # 这里的失败发生在任何写入之前，旧密文因此不会被清零或降级成明文。
        python,codec=credential_runtime()
        # New independent directory only. Do not touch the user's dsh directory.
        if HOME.resolve()!=HOME.absolute() or HOME.is_symlink():raise ValueError('凭据目录不可为链接')
        principal=_icacls_principal()
        result=subprocess.run(['icacls',str(HOME),'/inheritance:r','/grant:r',f'{principal}:(OI)(CI)F'],capture_output=True,timeout=15,creationflags=_NO_WINDOW)
        if result.returncode:
            fallback_user = os.environ.get('USERNAME') or getpass.getuser()
            if fallback_user != principal:
                result=subprocess.run(['icacls',str(HOME),'/inheritance:r','/grant:r',f'{fallback_user}:(OI)(CI)F'],capture_output=True,timeout=15,creationflags=_NO_WINDOW)
            if result.returncode:raise ValueError('无法限制独立凭据目录权限，尚未启动')
        # Fail before the upstream JsonStore can replace a damaged file.
        for name in ('settings.json','stats.json','catalog.json','availability.json','channel-credentials.json'):
            if (HOME/name).exists():strict(HOME/name)
        verify_credential_store(HOME/'channel-credentials.json')
        node, extra_env = _resolve_node_runtime()
        verify_source()
        env=os.environ.copy()
        for key in list(env):
            if key.startswith('DSH_') or key.startswith('OFM_'):env.pop(key,None)
        proxy_env = _detect_proxy_env()
        env.update(proxy_env)
        env.update(extra_env)
        env.update(NOVEL_HELPER_CREDENTIAL_CODEC=str(codec),NOVEL_HELPER_PYTHON=str(python),
            NOVEL_HELPER_CHECKIN_OPT_IN='1')
        log_dir = DATA / 'manager-logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        err_log = log_dir / 'ofm-service.err.log'
        proxy_configured = any(name in proxy_env for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'))
        supported, version_note = _check_node_runtime(node, extra_env, proxy_configured)
        if not supported:
            # Old but proxy-less runtimes still work for direct connections; say so
            # in the service log instead of silently claiming Node 20 is supported.
            try:
                with err_log.open('ab') as warning:
                    warning.write(f'[chapter-whale] Node.js 版本告警：{version_note}\n'.encode('utf-8'))
            except OSError:
                pass
        err_file = err_log.open('ab')
        try:
            proc = subprocess.Popen([node,str(ROOT/'integration/ofm_service.mjs')],cwd=str(ROOT),env=env,
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=err_file,
                creationflags=_NO_WINDOW)
        except OSError as error:
            err_file.close()
            raise ValueError(f'无法启动独立渠道服务的 Node.js（{error.__class__.__name__}）；请安装 Node.js ≥22.21 或 ≥24.5') from error
        else:
            err_file.close()
        try:
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise ValueError(f'独立渠道服务启动退出（退出码 {proc.returncode}），请查看 manager-logs/ofm-service.err.log')
                try:
                    ready_info=health()
                    if start:bridge.write_json_atomic(CONTROL,{'enabled':True,'updated_at':bridge.now_iso()})
                    return ready_info
                except (OSError,ValueError,subprocess.SubprocessError):
                    time.sleep(min(.5, max(0.0, deadline - time.monotonic())))
            raise ValueError('独立渠道服务未就绪，未更改正式模型；请检查运行环境或端口占用')
        except BaseException:
            _terminate_process(proc)
            raise


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
