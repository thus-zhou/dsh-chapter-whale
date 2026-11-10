"""Windows task entry: restore local services; never reset publication evidence."""
import json
import socket
import subprocess
import time
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import urlopen
from . import bridge, writer_runner
from .serial_service import ensure_started,LOCK as SERIAL_LOCK,STATE as SERIAL_STATE

ROOT=Path(__file__).resolve().parents[1]


def manager_ready():
    try:
        with urlopen('http://127.0.0.1:8765/api/health',timeout=3) as response:
            return json.load(response).get('service')=='novel-helper-manager'
    except (OSError,ValueError):return False


def serial_ready():
    try:
        with writer_runner.file_lock(SERIAL_LOCK):
            return False
    except RuntimeError as exc:
        if '已有任务正在运行' not in str(exc) and 'resource_busy' not in str(exc):raise
    value=bridge.read_json(SERIAL_STATE,{})
    try:
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(value['checked_at'])).total_seconds()
        return 0<=age<60 and value.get('status') in {'running','waiting_for_existing_worker'}
    except (KeyError,TypeError,ValueError):return False


def check():
    with writer_runner.file_lock(bridge.RUNTIME_ROOT/'watchdog.lock'):
        healthy=manager_ready()
        if not healthy:
            with socket.socket() as probe:
                probe.settimeout(2)
                occupied=probe.connect_ex(('127.0.0.1',8765))==0
            if occupied:
                raise RuntimeError('8765端口已有服务但健康检查未通过；保留现有进程')
            subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',
                '-File',str(ROOT/'启动小说助手.ps1'),'-NoBrowser'],cwd=ROOT,
                check=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
            if not manager_ready():raise RuntimeError('管理服务启动后未通过健康检查')
        result=ensure_started()
        if not serial_ready():
            from .owned_service import restart_stale_coordinator
            if restart_stale_coordinator(ROOT,SERIAL_STATE):
                result=ensure_started()
                result['recovered_owned_idle_service']=True
        deadline=time.monotonic()+20
        while not serial_ready():
            if time.monotonic()>=deadline:raise RuntimeError('逐章执行器未提供有效心跳，请检查服务日志')
            time.sleep(.5)
        bridge.write_json_atomic(ROOT/'integration_data/serial_service/watchdog.json',
            {'checked_at':bridge.now_iso(),'status':'healthy','manager_restarted':not healthy,
             'serial_service':result})
        return result


if __name__=='__main__':
    try:
        check()
        from .ofm_runtime import restore_if_enabled
        restore_if_enabled()
    except Exception as exc:
        from .serial_delivery import safe_message
        bridge.write_json_atomic(ROOT/'integration_data/serial_service/watchdog.json',
            {'checked_at':bridge.now_iso(),'status':'error','message':safe_message(exc)})
        raise SystemExit(1)
