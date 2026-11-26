"""Build portable, offline-capable Windows x64 runtime from pinned dependencies."""
import hashlib
import argparse
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


TEXT_SUFFIXES = ('.py', '.pyi', '.md', '.json', '.txt', '.css', '.html', '.js', '.mjs', '.cjs',
                 '.yml', '.yaml', '.toml', '.cfg', '.ini', '.sh', '.bat', '.ps1', '.lua', '.xml',
                 '.svg', '.csv', '.tsv', '.rst', '.po', '.pot', '.lock', '.gitignore', '.gitattributes')


def check_line_endings(files):
    """分发字节必须是 LF：清单哈希一旦覆盖 CRLF，autocrlf=true 的机器检出就会全部失配。"""
    broken = []
    for name in files:
        path = ROOT / name
        # runtime/ 是第三方 wheel 的原样分发字节，换行由上游决定；
        # 这里只约束本仓库自己的源码文本，避免改写第三方文件后哈希失真。
        if name.replace('\\', '/').startswith('runtime/'):
            continue
        if not path.name.lower().endswith(TEXT_SUFFIXES):
            continue
        data = path.read_bytes()
        if b'\0' in data:
            continue
        if b'\r\n' in data:
            broken.append(name)
    if broken:
        detail = '\n'.join(f'  {name}' for name in broken[:40])
        more = '' if len(broken) <= 40 else f'\n  ……共 {len(broken)} 个文件'
        raise ValueError('以下分发文本文件使用了 CRLF，必须先转换为 LF 再生成清单：\n'
                         f'{detail}{more}')


def write_manifest(runtime_version=None):
    runtime = ROOT / 'runtime'
    previous = json.loads((ROOT / 'runtime-manifest.json').read_text(encoding='utf-8'))
    files = {}
    roots = [ROOT / 'backend' / name for name in
             ('manager', 'integration', 'webnovel-writer', 'fanqie_auto_publish', 'vendor')]
    roots += [runtime / 'python', runtime / 'browsers']
    for base in roots:
        if not base.is_dir():
            raise ValueError(f'发行目录缺失：{base}')
        for path in sorted(base.rglob('*')):
            if (path.is_file() and '__pycache__' not in path.parts and '.links' not in path.parts
                    and path.name != '.npmignore' and not path.name.endswith(('.pyc', '.pyo', '.lock'))
                    and not (path.name.startswith('test_') and path.suffix == '.py')):
                if path.is_symlink():
                    raise ValueError(f'发行目录不接受符号链接：{path}')
                files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    check_line_endings(files)
    package_version = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['version']
    previous.update(version=runtime_version or package_version, packageVersion=package_version,
                    buildId=hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(), files=files)
    (ROOT / 'runtime-manifest.json').write_text(json.dumps(previous, indent=2) + '\n',
                                                 encoding='utf-8', newline='\n')
    print(json.dumps({'files': len(files), 'buildId': previous['buildId']}, ensure_ascii=False))


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
    (python / 'python313._pth').write_text('python313.zip\n.\nLib/site-packages\n../../backend\n',
                                            encoding='utf-8', newline='\n')
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
        for p in dependencies) + '\n', encoding='utf-8', newline='\n')
    # Browser binaries are installed by the pinned Playwright driver, never taken from a browser profile.
    browsers = runtime / 'browsers'
    if not list(browsers.glob('chromium-*')):
        environment = {**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': str(browsers), 'PYTHONUTF8': '1'}
        subprocess.run([str(python/'python.exe'), '-m', 'playwright', 'install', 'chromium', '--no-shell'], env=environment, check=True)
    manifest = {'platform': 'win32-x64', 'python': '3.13.17',
                'pythonSource': PYTHON_URL, 'pythonSha256': digest,
                'distributionStatus': 'tested-without-live-publish'}
    (ROOT/'runtime-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n',
                                              encoding='utf-8', newline='\n')
    write_manifest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest-only', action='store_true', help='复用现有运行时，只重建源码与运行时清单')
    parser.add_argument('--runtime-version', help='轻量包复用的已发布运行时版本；仅配合 --manifest-only')
    args = parser.parse_args()
    if args.manifest_only:
        write_manifest(args.runtime_version)
    else:
        main()
