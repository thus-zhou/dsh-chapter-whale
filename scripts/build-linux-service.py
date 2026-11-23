"""Build the Linux resident-service archive (amd64 or arm64).

独立入口：不复用 Windows runtime 清单参数，也不指向 Windows runtime-download。
架构由 --arch 决定，清单与文件名都带架构；构建机与目标架构不一致时不冒充实机验证。
输出（默认 .tmp/linux-service/）：
  dsh-chapter-whale-service-linux-<arch>-<version>.tar.gz
  dsh-chapter-whale-service-linux-<arch>-<version>.tar.gz.sha256
  linux-service-manifest-<arch>.json
"""
import argparse
import gzip
import hashlib
import io
import json
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.tmp' / 'linux-service'
BACKEND_DIRS = ('manager', 'integration', 'webnovel-writer', 'fanqie_auto_publish', 'vendor')
EXTRA_PATHS = ('deploy/linux', 'LICENSES', 'THIRD_PARTY_NOTICES.md', 'README.md', 'CHANGELOG.md',
               'LICENSE', 'docs/distribution.md')
SKIP_DIR_NAMES = {'__pycache__', '.links', 'node_modules', '.git'}
SKIP_SUFFIXES = ('.pyc', '.pyo', '.lock', '.tar.gz', '.tgz', '.sha256', '.restore.tmp')
TEXT_SUFFIXES = ('.py', '.pyi', '.sh', '.md', '.json', '.txt', '.yml', '.yaml', '.service',
                 '.toml', '.cfg', '.ini')
STRICT_SUFFIXES = ('.py', '.pyi', '.sh', '.json', '.yml', '.yaml', '.service', '.toml', '.cfg', '.ini')
ARCHS = ('amd64', 'arm64')


def collect():
    files = []
    for name in BACKEND_DIRS:
        base = ROOT / 'backend' / name
        if not base.is_dir():
            raise SystemExit(f'发行目录缺失：{base}')
        for path in sorted(base.rglob('*')):
            if not path.is_file():
                continue
            if SKIP_DIR_NAMES & set(path.parts):
                continue
            if path.name.endswith(SKIP_SUFFIXES):
                continue
            if path.name.startswith('test_') and path.suffix == '.py':
                continue
            files.append(path)
    for name in EXTRA_PATHS:
        path = ROOT / name
        if not path.exists():
            continue
        if path.is_file():
            files.append(path)
            continue
        for item in sorted(path.rglob('*')):
            if item.is_file() and not (SKIP_DIR_NAMES & set(item.parts)) \
                    and not item.name.endswith(SKIP_SUFFIXES):
                files.append(item)
    unique = {}
    for path in files:
        unique[path.relative_to(ROOT).as_posix()] = path
    return dict(sorted(unique.items()))


def normalize(name, data):
    """文档进归档时统一转 LF；脚本与配置仍要求源文件本身就是 LF。"""
    if name.lower().endswith(('.md', '.txt')) and b'\0' not in data:
        return data.replace(b'\r\n', b'\n')
    return data


def check_lf(names):
    broken = []
    for name, path in names.items():
        if not name.lower().endswith(STRICT_SUFFIXES):
            continue
        data = path.read_bytes()
        if b'\0' in data:
            continue
        if b'\r\n' in data:
            broken.append(name)
    if broken:
        detail = '\n'.join(f'  {name}' for name in broken[:40])
        raise SystemExit('以下服务文本文件使用 CRLF，请先转 LF 再打包：\n' + detail)


def digest(names):
    return {name: hashlib.sha256(normalize(name, path.read_bytes())).hexdigest()
            for name, path in names.items()}


def build_archive(names, target, extra=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.PAX_FORMAT) as tar:
        for name, path in names.items():
            info = tarfile.TarInfo(name)
            data = normalize(name, path.read_bytes())
            info.size = len(data)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = 'root'
            info.mode = 0o755 if name.endswith('.sh') else 0o644
            tar.addfile(info, io.BytesIO(data))
        for name, data in (extra or {}).items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = 'root'
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    payload = raw.getvalue()
    with target.open('wb') as handle:
        with gzip.GzipFile(fileobj=handle, mode='wb', mtime=0) as gz:
            gz.write(payload)
    return target


def _sidecar_problems(archive: Path, *, require: bool = True, version: str = '') -> list:
    """外部回执（.sha256 与 linux-service-manifest-*.json）必须与归档字节一致。

    候选目录里这两份外部记录是「外部锚点」：少了就等于没人担保来源，
    所以默认必需（require=True），只有显式 --allow-missing-sidecar 才放行。
    """
    problems = []
    data = archive.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    sidecar = archive.with_name(archive.name + '.sha256')
    if sidecar.is_file():
        try:
            first = sidecar.read_text(encoding='utf-8').split()[0].strip().lower()
        except (OSError, IndexError, UnicodeDecodeError) as error:
            problems.append(f'sidecar_unreadable:{sidecar.name}:{error}')
        else:
            if first != actual:
                problems.append(f'sidecar_sha256_mismatch:{first[:12]}!={actual[:12]}')
    elif require:
        problems.append(f'sidecar_missing:{sidecar.name}')
    for manifest_path in sorted(archive.parent.glob('linux-service-manifest-*.json')):
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            problems.append(f'external_manifest_unreadable:{manifest_path.name}:{error}')
            continue
        archive_info = manifest.get('archive') or {}
        if archive_info.get('name') and archive_info['name'] != archive.name:
            continue
        if archive_info.get('sha256') and archive_info['sha256'] != actual:
            problems.append(f'external_manifest_sha256_mismatch:{archive_path_label(manifest_path)}')
        if archive_info.get('bytes') is not None:
            try:
                declared = int(archive_info['bytes'])
            except (TypeError, ValueError):
                problems.append(
                    f'external_manifest_field_type:{archive_path_label(manifest_path)}:bytes')
            else:
                if declared != len(data):
                    problems.append(
                        f'external_manifest_bytes_mismatch:{archive_path_label(manifest_path)}')
        if version and str(manifest.get('version') or '') not in ('', version):
            problems.append(
                f'external_manifest_version_mismatch:{archive_path_label(manifest_path)}')
    return problems


def archive_path_label(path: Path) -> str:
    return path.name


def main():
    parser = argparse.ArgumentParser(description='打包 Linux 常驻存稿服务（amd64/arm64）')
    parser.add_argument('--manifest-only', action='store_true')
    parser.add_argument('--arch', choices=ARCHS, default='amd64',
                        help='目标架构；arm64 需在真实 aarch64 主机上验证')
    parser.add_argument('--out', default=str(OUT))
    parser.add_argument('--verify', default='', help='校验既有归档后退出')
    parser.add_argument('--expect-sha256', default='',
                        help='外部锚点：归档 sha256 必须等于该值（HASHES.txt 里的记录）')
    parser.add_argument('--allow-missing-sidecar', action='store_true',
                        help='允许缺少 .sha256/外部清单（仅限非候选目录的自查）')
    args = parser.parse_args()

    version = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['version']
    if args.verify:
        import sys
        from importlib import util as _util
        backend = ROOT / 'backend'
        sys.path.insert(0, str(backend))
        spec = _util.spec_from_file_location('platform_support',
                                             backend / 'integration' / 'platform_support.py')
        module = _util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = module.verify_archive(args.verify, expect_target=f'linux-{args.arch}')
        problems = list(report.get('problems') or [])
        actual = hashlib.sha256(Path(args.verify).read_bytes()).hexdigest()
        pinned = (args.expect_sha256 or '').strip().lower()
        if pinned and pinned != actual:
            problems.append(f'archive_pin_mismatch:{actual[:12]}!={pinned[:12]}')
        if str(report.get('version') or '') != version:
            problems.append(f'archive_version_mismatch:{report.get("version")}!={version}')
        problems += _sidecar_problems(Path(args.verify),
                                      require=not args.allow_missing_sidecar, version=version)
        report['problems'] = problems
        report['expected_sha256'] = pinned
        report['actual_sha256'] = actual
        report['ok'] = not problems
        print(json.dumps(report, ensure_ascii=False))
        raise SystemExit(0 if report['ok'] else 1)

    names = collect()
    check_lf(names)
    files = digest(names)
    summary = {'version': version, 'platform': f'linux-{args.arch}', 'arch': args.arch,
               'files': len(files),
               'sha256': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}
    if args.manifest_only:
        print(json.dumps(summary, ensure_ascii=False))
        return

    out = Path(args.out)
    roots = [ROOT / 'backend' / name for name in BACKEND_DIRS] + [ROOT / name for name in EXTRA_PATHS]
    for root in roots:
        try:
            out.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        raise SystemExit(f'输出目录不能落在收集范围里（会把上次的归档打进新归档）：{out}')
    out.mkdir(parents=True, exist_ok=True)
    name = f'dsh-chapter-whale-service-linux-{args.arch}-{version}.tar.gz'
    build_manifest = {'schema': 1, 'version': version, 'platform': f'linux-{args.arch}',
                      'arch': args.arch, 'files': len(files), 'sha256': summary['sha256']}
    embedded = {'service-build.json': (json.dumps(build_manifest, ensure_ascii=False, indent=2)
                                       + '\n').encode('utf-8')}
    target = build_archive(names, out / name, embedded)
    data = target.read_bytes()
    (out / f'{name}.sha256').write_text(
        f'{hashlib.sha256(data).hexdigest()}  {name}\n', encoding='utf-8', newline='\n')
    manifest = {**summary, 'archive': {'name': name, 'bytes': len(data),
                                       'sha256': hashlib.sha256(data).hexdigest()},
                'built_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'files_detail': files}
    manifest_name = f'linux-service-manifest-{args.arch}.json'
    (out / manifest_name).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: manifest[k] for k in ('version', 'platform', 'files', 'archive')},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
