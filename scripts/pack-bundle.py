"""Build the full release tarball: npm files + the runtime tree from the manifest.

The manifest is the single source of truth for what ships. Copying ``runtime/``
wholesale used to drag ``__pycache__`` and other non-manifest files into the
published archive; this script copies exactly the listed files and then refuses
to package if any residue slipped in.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / ".tmp" / "bundle"
RESIDUE = ("__pycache__", ".pyc", ".pyo")


def manifest_files(root=ROOT):
    data = json.loads((root / "runtime-manifest.json").read_text(encoding="utf-8"))
    files = data.get("files") or {}
    if not isinstance(files, dict) or not files:
        raise SystemExit("runtime-manifest.json 没有 files")
    return data, files


def unwanted(names):
    """Return staged paths that must never be shipped."""
    bad = []
    for name in names:
        parts = Path(name).parts
        if any(part == "__pycache__" for part in parts):
            bad.append(name)
        elif str(name).endswith(RESIDUE[1:]):
            bad.append(name)
        elif parts and Path(parts[-1]).name.startswith("test_") and str(name).endswith(".py"):
            bad.append(name)
    return bad


def stage(root, stage_dir):
    data, files = manifest_files(root)
    package = stage_dir / "package"
    for relative in files:
        source = root / relative
        if not source.is_file() or source.is_symlink() or root.resolve() not in source.resolve().parents:
            raise SystemExit(f"清单文件缺失：{relative}")
        if hashlib.sha256(source.read_bytes()).hexdigest() != files[relative]:
            raise SystemExit(f"清单摘要不匹配：{relative}")
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    # The bundled installer never downloads itself. A self-hash inside the same
    # archive cannot be correct; only the lightweight package carries this spec.
    download = package / "runtime-download.json"
    if download.is_file():
        download.unlink()
    names = [str(path.relative_to(stage_dir)) for path in stage_dir.rglob("*") if path.is_file()]
    bad = unwanted(names)
    if bad:
        raise SystemExit("暂存目录含不应发布的内容：\n" + "\n".join(sorted(bad)))
    return data, len(files)


def bundle_name(version):
    """完整包名带上运行环境与架构：同一版本号的轻量包与完整包不能撞名。"""
    return f"dsh-chapter-whale-runtime-win32-x64-{version}.tgz"


def runtime_release_version(manifest, package_version):
    """完整包描述的是 runtime 资产：版本取 manifest.version，而不是插件版本。

    轻量安装器会去 ``v{runtime}/dsh-chapter-whale-runtime-win32-x64-{runtime}.tgz``
    取同一个资产；插件 0.7.5 复用 runtime 0.7.0 时写成 0.7.5 会得到 404。
    """
    return str(manifest.get("version") or package_version)


def build(keep_stage=False):
    package_version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    manifest, _ = manifest_files(ROOT)
    version = runtime_release_version(manifest, package_version)
    target = TMP / bundle_name(version)
    if TMP.is_symlink() or ROOT.resolve() not in TMP.resolve().parents:
        raise SystemExit("暂存目录必须位于当前发行工作区")
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    subprocess.run([shutil.which("npm.cmd") or shutil.which("npm"), "pack", "--ignore-scripts", "--pack-destination", str(TMP)], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    packs = sorted(TMP.glob("*.tgz"))
    if len(packs) != 1:
        raise SystemExit(f"应只有一个 npm 包，实际：{packs}")
    stage_dir = TMP / "stage"
    stage_dir.mkdir()
    with tarfile.open(packs[0]) as tar:
        tar.extractall(stage_dir, filter="data")
    packs[0].unlink()
    data, copied = stage(ROOT, stage_dir)
    subprocess.run(["node", str(stage_dir / "package/scripts/check-release.mjs"),
                    "--root", str(stage_dir / "package")], check=True)
    with tarfile.open(target, "w:gz", compresslevel=6) as tar:
        tar.add(stage_dir / "package", arcname="package")
    blob = target.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    sums = TMP / "SHA256SUMS.txt"
    sums.write_text(f"{digest}  {target.name}\n", encoding="utf-8", newline="\n")
    result = {"file": target.name, "bytes": len(blob), "sha256": digest,
              "buildId": data.get("buildId"), "packageVersion": package_version,
              "runtimeVersion": version, "manifest_files": copied}
    (TMP / "bundle.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8", newline="\n")
    # A full bundle carries its own runtime; it must NOT overwrite the root
    # runtime-download.json, which describes the published v0.7.0 runtime asset
    # used by the lightweight installer. Writing the full-bundle SHA here made
    # downloadRuntime reject the archive (buildId/runtimeAssetBuildId mismatch).
    if not keep_stage:
        shutil.rmtree(stage_dir, ignore_errors=True)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="打包完整发行包（npm 文件 + 清单内的 runtime）")
    parser.add_argument("--keep-stage", action="store_true", help="保留解包目录便于检查")
    build(keep_stage=parser.parse_args().keep_stage)
