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
        if not source.is_file():
            raise SystemExit(f"清单文件缺失：{relative}")
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    # 包内 json 只用于说明这次发行：buildId 跟随清单，字节与摘要以 Release 资产为准。
    download = package / "runtime-download.json"
    if download.is_file():
        payload = json.loads(download.read_text(encoding="utf-8"))
        payload["buildId"] = data.get("buildId")
        payload["note"] = "归档内的摘要仅供参考；安装器以 Release 页与 SHA256SUMS.txt 为准。"
        download.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    names = [str(path.relative_to(stage_dir)) for path in stage_dir.rglob("*") if path.is_file()]
    bad = unwanted(names)
    if bad:
        raise SystemExit("暂存目录含不应发布的内容：\n" + "\n".join(sorted(bad)[:20]))
    return data, len(files)


def build(keep_stage=False):
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    target = TMP / f"dsh-chapter-whale-{version}.tgz"
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    subprocess.run(["npm", "pack", "--pack-destination", str(TMP)], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, shell=True)
    packs = sorted(TMP.glob("*.tgz"))
    if len(packs) != 1:
        raise SystemExit(f"应只有一个 npm 包，实际：{packs}")
    stage_dir = TMP / "stage"
    stage_dir.mkdir()
    with tarfile.open(packs[0]) as tar:
        tar.extractall(stage_dir)
    packs[0].unlink()
    data, copied = stage(ROOT, stage_dir)
    with tarfile.open(target, "w:gz", compresslevel=6) as tar:
        tar.add(stage_dir / "package", arcname="package")
    blob = target.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    sums = TMP / "SHA256SUMS.txt"
    sums.write_text(f"{digest}  {target.name}\n", encoding="utf-8", newline="\n")
    result = {"file": target.name, "bytes": len(blob), "sha256": digest,
              "buildId": data.get("buildId"), "manifest_files": copied}
    (TMP / "bundle.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8", newline="\n")
    if not keep_stage:
        shutil.rmtree(stage_dir, ignore_errors=True)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="打包完整发行包（npm 文件 + 清单内的 runtime）")
    parser.add_argument("--keep-stage", action="store_true", help="保留解包目录便于检查")
    build(keep_stage=parser.parse_args().keep_stage)
