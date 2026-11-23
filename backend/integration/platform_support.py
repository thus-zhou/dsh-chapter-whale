"""0.9.1 目标平台支持：只在受支持的 Linux 架构上构建/运行，并拒绝错架构的归档。

本模块只做三件事，不触碰平台写入、浏览器或 DSH 宿主：
1. 把 `uname -m` 一类的机器名归一成 `amd64`/`arm64`，其余一律不认。
2. 判断当前主机能否直接运行某个目标（跨架构构建不冒充实机验证）。
3. 校验服务归档：清单平台与文件名一致、没有 Windows 二进制、脚本仍是 LF。

设计取舍：
- 不假装能在 x86_64 上「验证」arm64。`check_target()` 对不匹配主机返回 `ok=False`
  并给出 `host_arch_mismatch`，让调用方把结果写成「待实机」而不是「通过」。
- 归档校验读 tar 成员本身，不信文件名：改名绕过在 `verify_archive()` 里会被
  `platform_mismatch` 或 `foreign_binary` 拦住。
"""
import hashlib
import io
import json
import platform as platform_module
import re
import subprocess
import tarfile
from pathlib import Path

SCHEMA = 1
TARGETS = {
    "linux-amd64": {
        "arch": "amd64",
        "system": "linux",
        "machines": ("x86_64", "amd64", "x64"),
        "python": "3.11+",
        "container": "linux/amd64",
        "launcher": "systemd",
        "note": "0.9.0 起支持；容器与 systemd 两种跑法。",
    },
    "linux-arm64": {
        "arch": "arm64",
        "system": "linux",
        "machines": ("aarch64", "arm64"),
        "python": "3.11+",
        "container": "linux/arm64",
        "launcher": "systemd",
        "note": "0.9.1 起支持；需要真实 aarch64 主机验证，交叉构建不算实机。",
    },
    "macos-arm64": {
        "arch": "arm64",
        "system": "darwin",
        "machines": ("aarch64", "arm64"),
        "python": "3.11+",
        "container": "",
        "launcher": "launchd",
        "note": "0.9.2 起支持；需要真实 Apple Silicon 验证，交叉构建不算实机。",
    },
    "macos-amd64": {
        "arch": "amd64",
        "system": "darwin",
        "machines": ("x86_64", "amd64", "x64"),
        "python": "3.11+",
        "container": "",
        "launcher": "launchd",
        "note": "0.9.3 起支持；需要真实 Intel Mac（或原生 x86_64 解释器）验证，Rosetta 结果单列不算实机。",
    },
}
STRICT_SUFFIXES = (".py", ".pyi", ".sh", ".json", ".yml", ".yaml", ".service", ".toml", ".cfg", ".ini",
                   ".plist", ".command")
FOREIGN_SUFFIXES = (".exe", ".dll", ".pyd", ".dylib", ".msi", ".bat", ".ps1")
ELF_MAGIC = b"\x7fELF"
MANIFEST_PATTERN = re.compile(r"^service-build(?:-[a-z0-9]+)?\.json$")
LEGACY_MANIFEST_PATTERN = re.compile(r"^linux-service-manifest-(?P<arch>amd64|arm64)\.json$")


class TargetError(ValueError):
    """目标平台不受支持或归档与目标不符。"""


def normalize_arch(machine):
    """把机器名归一成 amd64/arm64；认不出返回空串，绝不猜。"""
    text = str(machine or "").strip().lower()
    for target, info in TARGETS.items():
        if text in info["machines"]:
            return info["arch"]
    return ""


def target_for_arch(arch):
    for target, info in TARGETS.items():
        if info["arch"] == arch:
            return target
    return ""


def current_machine():
    return platform_module.machine()


def rosetta_translated():
    """Darwin 上判断当前进程是否经 Rosetta 转译；拿不到 sysctl 时按否处理。"""
    if platform_module.system().lower() != "darwin":
        return False
    try:
        proc = subprocess.run(["sysctl", "-n", "sysctl.proc_translated"],
                              capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return False
    return (proc.stdout or "").strip() == "1"


def check_target(target, *, machine=None, system=None, translated=None):
    """返回当前主机能否直接跑该目标；不匹配时 ok=False，原因可读。"""
    if target not in TARGETS:
        raise TargetError(f"不支持的目标平台：{target}")
    info = TARGETS[target]
    machine = current_machine() if machine is None else machine
    system = platform_module.system().lower() if system is None else str(system).lower()
    host_arch = normalize_arch(machine)
    translated = rosetta_translated() if translated is None else bool(translated)
    report = {
        "target": target,
        "arch": info["arch"],
        "system": info["system"],
        "machine": machine,
        "host_system": system,
        "host_arch": host_arch,
        "translated": translated,
        "python": platform_module.python_version(),
        "ok": False,
        "reason": "",
        "note": info["note"],
    }
    if system != info["system"]:
        report["reason"] = f"host_system_mismatch:{system or 'unknown'}!={info['system']}"
        return report
    if not host_arch:
        report["reason"] = f"unknown_arch:{machine}"
        return report
    if host_arch != info["arch"]:
        report["reason"] = f"host_arch_mismatch:{host_arch}!={info['arch']}"
        return report
    if translated:
        # Rosetta 下 x86_64 只是转译层，不能当成 Intel Mac 的实机证据。
        report["reason"] = "rosetta_translation:not_native"
        return report
    report["ok"] = True
    report["reason"] = "host_matches_target"
    return report


def _platform_of_manifest(manifest):
    return str((manifest or {}).get("platform") or "")


def _manifest_fields(manifest):
    """返回清单必填字段缺失列表；缺字段不允许被默认值补成「对的」。"""
    missing = []
    for key in ("schema", "version", "platform", "arch", "files", "sha256"):
        if manifest.get(key) in (None, "", 0):
            missing.append(key)
    return missing


def verify_manifest(manifest, *, expect_target=None, archive_name=""):
    """清单自洽性检查：必填字段、平台、架构、归档名一致。"""
    problems = []
    missing = _manifest_fields(manifest or {})
    for key in missing:
        problems.append(f"manifest_missing_field:{key}")
    target = _platform_of_manifest(manifest)
    if target and target not in TARGETS:
        problems.append(f"unknown_platform:{target}")
    if expect_target and target and target != expect_target:
        problems.append(f"platform_mismatch:{target}!={expect_target}")
    if target in TARGETS:
        arch = TARGETS[target]["arch"]
        listed = str((manifest or {}).get("arch") or "")
        if listed and listed != arch:
            problems.append(f"arch_mismatch:{listed}!={arch}")
    if archive_name and target in TARGETS:
        if f"-{TARGETS[target]['arch']}-" not in archive_name:
            problems.append(f"archive_name_arch_mismatch:{archive_name}")
    return {"ok": not problems, "target": target, "problems": problems}


def _payload_digest(members):
    """按构建脚本的口径重算载荷摘要：文档先转 LF，再按名字排序聚合。"""
    files = {}
    for name, data in members.items():
        if isinstance(data, str):
            data = data.encode("utf-8")
        if name.lower().endswith((".md", ".txt")) and b"\0" not in data:
            data = data.replace(b"\r\n", b"\n")
        files[name] = hashlib.sha256(data).hexdigest()
    return files, hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


ELF_MACHINES = {"amd64": 0x3E, "arm64": 0xB7}


def _elf_arch_mismatch(target, members):
    """Linux 归档里的 ELF 必须与目标架构一致（amd64=0x3E，arm64=0xB7）。"""
    want = (TARGETS.get(target) or {}).get("arch")
    wanted = ELF_MACHINES.get(want)
    if wanted is None:
        return []
    wrong = []
    for name, data in members.items():
        if data[:4] != ELF_MAGIC or len(data) < 20:
            continue
        machine = int.from_bytes(data[18:20], "little")
        if machine != wanted:
            wrong.append(f"{name}={machine:#x}")
    return wrong


def _crlf_members(members):
    broken = []
    for name, data in members.items():
        if not name.lower().endswith(STRICT_SUFFIXES):
            continue
        # NUL 只说明「不是纯文本」，不能当成「不用查 CRLF」的理由。
        if b"\r\n" in data:
            broken.append(name)
    return broken


def verify_archive(path, *, expect_target=None):
    """读归档本身判断平台与内容：清单、载荷摘要、二进制、CRLF。"""
    path = Path(path)
    if not path.is_file():
        raise TargetError(f"归档不存在：{path}")
    members = {}
    duplicates = []
    links = []
    unsafe = []
    try:
        with tarfile.open(path, mode="r:gz") as tar:
            for info in tar.getmembers():
                if info.issym() or info.islnk():
                    links.append(info.name)
                    continue
                if info.name.startswith("/") or ".." in Path(info.name).parts:
                    unsafe.append(info.name)
                    continue
                if not info.isfile():
                    continue
                handle = tar.extractfile(info)
                if handle is None:
                    continue
                if info.name in members:
                    duplicates.append(info.name)
                    continue
                members[info.name] = handle.read()
    except (tarfile.TarError, OSError, EOFError) as error:
        return {"ok": False, "target": "", "files": 0,
                "problems": [f"archive_unreadable:{error}"], "path": str(path)}
    problems = []
    if links:
        problems.append("link_member:" + ",".join(sorted(links)[:5]))
    if unsafe:
        problems.append("unsafe_path:" + ",".join(sorted(unsafe)[:5]))
    if duplicates:
        problems.append("duplicate_member:" + ",".join(sorted(duplicates)[:5]))
    manifests = [name for name in members
                 if "/" not in name
                 and (MANIFEST_PATTERN.match(name) or LEGACY_MANIFEST_PATTERN.match(name))]
    nested = [name for name in members
              if "/" in name
              and (MANIFEST_PATTERN.match(Path(name).name)
                   or LEGACY_MANIFEST_PATTERN.match(Path(name).name))]
    if nested:
        problems.append("manifest_not_at_root:" + ",".join(sorted(nested)[:5]))
    manifest = {}
    if len(manifests) != 1:
        problems.append(f"manifest_count:{len(manifests)}")
    else:
        try:
            manifest = json.loads(members[manifests[0]].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            problems.append(f"manifest_unreadable:{error}")
    check = verify_manifest(manifest, expect_target=expect_target, archive_name=path.name)
    problems.extend(check["problems"])
    target = check["target"] or str(expect_target or "")
    payload = {name: data for name, data in members.items() if name not in manifests}
    files, aggregate = _payload_digest(payload)
    listed_files = manifest.get("files")
    if isinstance(listed_files, bool) or not isinstance(listed_files, int):
        problems.append("manifest_field_type:files")
    elif listed_files != len(payload):
        problems.append(f"file_count_mismatch:{listed_files}!={len(payload)}")
    listed_digest = str(manifest.get("sha256") or "")
    if listed_digest and listed_digest != aggregate:
        problems.append(f"payload_digest_mismatch:{listed_digest[:12]}!={aggregate[:12]}")
    foreign = [name for name in members if name.lower().endswith(FOREIGN_SUFFIXES)]
    if foreign:
        problems.append("foreign_binary:" + ",".join(sorted(foreign)[:5]))
    if target.startswith("macos"):
        # macOS 归档里出现 ELF 说明混进了 Linux 产物；纯 Python 载荷不该有它。
        elf = [name for name in members if members[name][:4] == ELF_MAGIC]
        if elf:
            problems.append("elf_binary:" + ",".join(sorted(elf)[:5]))
        shared = [name for name in members if name.lower().endswith((".so", ".so.1", ".a"))]
        if shared:
            problems.append("linux_object:" + ",".join(sorted(shared)[:5]))
    else:
        # Linux 归档里允许 ELF（vendored 运行时），但架构必须与目标一致。
        wrong = _elf_arch_mismatch(target, members)
        if wrong:
            problems.append("elf_arch_mismatch:" + ",".join(sorted(wrong)[:5]))
    broken = _crlf_members(members)
    if broken:
        problems.append("crlf:" + ",".join(sorted(broken)[:5]))
    return {"ok": not problems, "target": check["target"],
            "version": str(manifest.get("version") or ""),
            "files": len(members),
            "payload_files": len(payload), "digest": aggregate,
            "problems": problems, "path": str(path)}


def matrix():
    """给文档与界面用的能力矩阵：主机匹配与实机验证分开写。"""
    rows = []
    for target, info in TARGETS.items():
        report = check_target(target)
        rows.append({"target": target, "arch": info["arch"], "system": info["system"],
                     "container": info["container"], "launcher": info["launcher"],
                     "python": info["python"],
                     "host_matches": report["ok"],
                     # 真机验证只能由真实运行写回；当前版本没有写回渠道，因此恒为 False。
                     "verified_here": False,
                     "reason": report["reason"], "note": info["note"]})
    return {"schema": SCHEMA, "host": {"system": platform_module.system().lower(),
                                       "machine": current_machine()}, "rows": rows}
