"""Restart only an identity-verified idle coordinator, never a writer/browser."""
import base64
import os
import subprocess
from datetime import datetime,timezone
from pathlib import Path
from . import bridge,writer_runner


def restart_stale_coordinator(root,state,now=None):
    if os.name!='nt':return False
    value=writer_runner.strict_json(Path(state),{})
    if not isinstance(value,dict) or value.get('active_job') or value.get('child_pid'):return False
    pid=value.get('pid');started=value.get('started_at');checked=value.get('checked_at')
    if type(pid) is not int or pid<=0 or not started or not checked:return False
    current=now or datetime.now(timezone.utc)
    if (current-datetime.fromisoformat(checked)).total_seconds()<90:return False
    # The held scheduler lock proves there is no current chapter owner. If a
    # worker exists we do nothing, regardless of a stale coordinator heartbeat.
    try:
        with writer_runner.file_lock(bridge.RUNTIME_ROOT/'scheduler-execution.lock'):
            script=Path(root).resolve()/'integration/serial_service.py'
            expected=str(script).replace("'","''")
            timestamp=datetime.fromisoformat(started).astimezone(timezone.utc).isoformat()
            code=f"""$ErrorActionPreference='Stop'
$taskPid={pid}
$taskProcess=Get-Process -Id $taskPid
$taskHandle=$taskProcess.Handle
$taskInfo=Get-CimInstance Win32_Process -Filter "ProcessId=$taskPid"
$taskExpected='{expected}'
if ($taskInfo.CommandLine -notlike ('*'+$taskExpected+'*')) {{ exit 2 }}
$taskStarted=[DateTimeOffset]::Parse('{timestamp}').UtcDateTime
if ([Math]::Abs(($taskProcess.StartTime.ToUniversalTime()-$taskStarted).TotalSeconds) -gt 20) {{ exit 3 }}
if ($taskInfo.Name -notmatch '^python(w)?[.]exe$') {{ exit 4 }}
Stop-Process -InputObject $taskProcess
Write-Output 'owned-idle-coordinator-stopped'
"""
            encoded=base64.b64encode(code.encode('utf-16le')).decode('ascii')
            result=subprocess.run(['powershell.exe','-NoProfile','-EncodedCommand',encoded],
                capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
            return result.returncode==0 and b'owned-idle-coordinator-stopped' in result.stdout
    except RuntimeError as exc:
        if '已有任务正在运行' in str(exc) or str(exc)=='resource_busy':return False
        raise
