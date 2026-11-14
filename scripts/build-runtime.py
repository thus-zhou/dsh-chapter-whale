"""Build portable, offline-capable Windows x64 runtime from pinned dependencies."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_URL = 'https://www.python.org/ftp/python/3.13.17/python-3.13.17-embeddable-amd64.zip'
PYTHON_HASH = '0ba1ee4bfcbdc3a559d27e2e9ce76d04a7839947a23f46375872c755c0d463b8'
REQUIREMENTS = ['fastapi==0.141.1', 'uvicorn==0.53.0', 'pydantic==2.13.5', 'httpx==0.28.1',
                'aiohttp==3.14.3', 'playwright==1.63.0', 'filelock==4.1.1', 'tzdata==2026.5',
                'python-multipart', 'aiofiles', 'pillow', 'requests']


def main():
    runtime = ROOT / 'runtime'
    python = runtime / 'python'
    python.mkdir(parents=True, exist_ok=True)
    archive = runtime / 'python-embeddable.zip'
    if not archive.exists():
        urllib.request.urlretrieve(PYTHON_URL, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != PYTHON_HASH:
        raise ValueError('Python archive does not match the official release manifest')
    with zipfile.ZipFile(archive) as source:
        source.extractall(python)
    (python / 'python313._pth').write_text('python313.zip\n.\nLib/site-packages\n../../backend\n', encoding='utf-8')
    packages = python / 'Lib/site-packages'
    report = runtime / 'pip-report.json'
    if not report.exists():
        lock = ROOT / 'requirements-runtime.lock'
        requested = ['--require-hashes', '-r', str(lock)] if lock.exists() else REQUIREMENTS
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:', '--no-compile',
                        '--target', str(packages), '--report', str(report), *requested], check=True)
    dependencies = json.loads(report.read_text(encoding='utf-8'))['install']
    (ROOT / 'requirements-runtime.lock').write_text('\n'.join(
        f"{p['metadata']['name']}=={p['metadata']['version']} --hash=sha256:{p['download_info']['archive_info']['hashes']['sha256']}"
        for p in dependencies) + '\n', encoding='utf-8')
    # Browser binaries are installed by the pinned Playwright driver, never taken from a browser profile.
    browsers = runtime / 'browsers'
    if not list(browsers.glob('chromium-*')):
        environment = {**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': str(browsers), 'PYTHONUTF8': '1'}
        subprocess.run([str(python/'python.exe'), '-m', 'playwright', 'install', 'chromium', '--no-shell'], env=environment, check=True)
    files = {}
    for base in [ROOT/'backend', runtime/'python', browsers]:
        for path in sorted(base.rglob('*')):
            if (path.is_file() and '__pycache__' not in path.parts and '.links' not in path.parts
                    and path.name != '.npmignore' and not path.name.endswith(('.pyc', '.pyo'))
                    and not (path.name.startswith('test_') and path.suffix == '.py')
                    and path.parts[1:2] != ('integration_data',) and not path.name.endswith('.lock')):
                files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    build_id = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    manifest = {'version': '0.4.0', 'platform': 'win32-x64', 'python': '3.13.17',
                'pythonSource': PYTHON_URL, 'pythonSha256': digest, 'buildId': build_id,
                'files': files, 'distributionStatus': 'prerelease-tested-without-live-publish'}
    (ROOT/'runtime-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'files': len(files), 'buildId': build_id}, ensure_ascii=False))


if __name__ == '__main__':
    main()
