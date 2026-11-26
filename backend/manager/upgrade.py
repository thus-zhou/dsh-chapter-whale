"""Stop a verified, idle managed instance before replacing its code.

Runs from the NEW package, not from the old workspace. Never stops a process
on port identity alone. Maintenance blocks new work while execution locks and
the operation ledger are checked. Active work returns an actionable wait.
"""
from __future__ import annotations
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integration import writer_runner as writer


def command_matches(pid, entry):
    if type(pid) is not int or pid <= 0 or pid == os.getpid():
        return False
    try:
        if os.name == 'nt':
            # PID is validated as an integer, never interpolate a path into shell code.
            command = subprocess.check_output(['powershell', '-NoProfile', '-Command',
                '[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); '
                f'(Get-CimInstance Win32_Process -Filter "ProcessId = {pid}").CommandLine'],
                encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
        else:
            command = subprocess.check_output(['ps', '-p', str(pid), '-o', 'args='], text=True, timeout=5)
        expected = str(entry.resolve()).replace('\\', '/').casefold()
        actual = command.replace('\\', '/').casefold()
        return expected in actual
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return False


def _stop(pid):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/F'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
    else:
        os.kill(pid, signal.SIGTERM)


def stop_idle(root, port, pid, startup_id, explicit_stop=False):
    root = Path(root).resolve()
    def get(path):
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                f'http://127.0.0.1:{port}{path}', timeout=5) as response:
            return json.load(response)
    def identity(health):
        return (health.get('service') == 'novel-helper-manager'
                and health.get('pid') == pid and health.get('startup_id') == startup_id
                and Path(health.get('root') or '.').resolve() == root
                and health.get('mode') == 'dsh_managed')
    description = writer.strict_json(root / 'integration_data/run-description.json', {})
    health = get('/api/health')
    if (description.get('owner') != 'plugin' or description.get('mode') != 'dsh_managed'
            or description.get('pid') != pid or description.get('startup_id') != startup_id
            or not identity(health)
            or not command_matches(pid, root / 'manager/app.py')):
        return {'stopped': False, 'reason': '无法确认旧实例归属，请从原启动器停止旧服务后重试'}
    if health.get('upgrade_guard') != 1 and not explicit_stop:
        return {'stopped': False, 'reason': '旧版不支持任务派发屏障，请先点击停止旧后端，再重试升级；已有任务可先完成或取消'}
    maintenance = root / 'integration_data/maintenance.json'
    with writer.file_lock(root / 'integration_data/upgrade-admission.lock'):
        previous = maintenance.read_bytes() if maintenance.exists() else None
        if previous and writer.strict_json(maintenance, {}).get('state') == 'maintenance':
            return {'stopped': False, 'reason': '工作区正在维护，请完成维护后重试升级'}
        writer.atomic_json(maintenance, {'state': 'maintenance', 'reason': 'plugin_upgrade'})
        coordinator_stopped = False
        upgrade_stopped = False
        try:
            with writer.file_lock(root / 'integration_data/runtime/scheduler-execution.lock'):
                operations = get('/api/overview').get('operations') or []
                if any(op.get('status') in {'queued', 'running', 'awaiting_login', 'waiting'} for op in operations):
                    return {'stopped': False, 'reason': '旧后端有活动任务，已保留原任务；完成或取消后重试升级'}
                state = writer.strict_json(root / 'integration_data/serial_service/heartbeat.json', {})
                daemon = state.get('pid')
                daemon_alive = bool(daemon and command_matches(daemon, root / 'integration/serial_service.py'))
                if state.get('active_job') and daemon_alive:
                    return {'stopped': False, 'reason': '逐章执行器仍有活动任务，请完成后重试升级'}
                restart_serial = False
                if daemon_alive:
                    _stop(daemon)
                    coordinator_stopped = True
                    restart_serial = True
                    writer.atomic_json(root / 'integration_data/upgrade-resume.json', {'restart_serial':True})
                if not identity(get('/api/health')) or not command_matches(pid, root / 'manager/app.py'):
                    return {'stopped': False, 'reason': '升级期间实例已变化，请重试'}
                _stop(pid)
                for _ in range(40):
                    try:
                        get('/api/health')
                    except (OSError, ValueError):
                        upgrade_stopped = True
                        return {'stopped': True, 'restart_serial': restart_serial}
                    time.sleep(0.1)
                return {'stopped': False, 'reason': '旧后端尚未退出，请稍后重试'}
        except RuntimeError:
            return {'stopped': False, 'reason': '后台任务持有执行锁，已保留任务；完成后重试升级'}
        finally:
            try:
                if coordinator_stopped and not upgrade_stopped:
                    subprocess.run([sys.executable, '-X', 'utf8', '-c',
                        'from integration.serial_service import ensure_started; ensure_started()'],
                        cwd=root, check=True, timeout=15, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
                    (root / 'integration_data/upgrade-resume.json').unlink(missing_ok=True)
            finally:
                if previous is None:
                    maintenance.unlink(missing_ok=True)
                else:
                    maintenance.write_bytes(previous)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--startup-id', required=True)
    parser.add_argument('--explicit-stop', action='store_true')
    args = parser.parse_args()
    try:
        result = stop_idle(args.root, args.port, args.pid, args.startup_id, args.explicit_stop)
    except (OSError, ValueError, subprocess.SubprocessError):
        result = {'stopped': False, 'reason': '无法核验旧实例状态，请从原启动器停止后重试'}
    print(json.dumps(result, ensure_ascii=False))
