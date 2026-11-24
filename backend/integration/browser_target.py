"""0.9.4：单目标浏览器与登录试点（只读优先，写入默认关闭）。

设计边界（见 `design/码章鲸_按版本执行包_2026-11-16/09_v0.9.4_单目标浏览器与登录.md`）：

- 一个版本只扩一个已有支持格的浏览器/登录；本模块不选平台，只接受显式 target 配置。
- profile 与凭据目录参数化为作品内的受管路径：默认 `.webnovel/browser/profile`，
  拒绝符号链接、目录联接（reparse point）与越界路径。
- 「浏览器能启动」不算登录成功，「点了登录按钮」也不算：`valid/expired` 只能由
  适配器回读 profile 后写入（`source="adapter"`），客户端只能报 unknown/needs_human/cancelled。
- 真实投递是单独支持格：先落意图（独立账本，不受 journal 裁剪影响）再写一次，
  回读不通过或结果未知只进对账，不重试、不累加「已发」。
- 本模块不实现 Playwright 细节：驱动通过 `BrowserAdapter` 协议注入，
  默认没有生产适配器（`get_adapter()` 返回 None），所以默认路径下零平台写入。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import bridge

SCHEMA = 1
STATE_DIR = "browser"
TARGET_NAME = "target.json"
LOGIN_NAME = "login.json"
JOURNAL_NAME = "journal.jsonl"
JOURNAL_LOCK = "journal.lock"
LEDGER_DIR = "publish_ledger"
PROFILE_DIR = "profile"
MAX_JOURNAL = 200

READ_ONLY = "read_only"
PUBLISH = "publish"
SCOPES = (READ_ONLY, PUBLISH)

REAL, SIMULATED, PENDING = "real", "simulated", "pending"
STATUSES = (REAL, SIMULATED, PENDING)

LOGIN_STATES = ("unknown", "valid", "expired", "needs_human", "cancelled")
LOGIN_MAX_AGE_HOURS = 24.0
IDENTITY_KEYS = ("platform", "account", "book_id", "chapter_id", "content_sha256")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_PLATFORM = "fanqie"

COLUMNS = ("launch", "model", "credential", "schedule", "browser_login",
           "readonly", "publish", "install")

_OS_VALUES = ("windows", "linux", "macos")
_ARCH_VALUES = ("x64", "arm64", "amd64")
_VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.\-]{0,39}$")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class BrowserTargetError(ValueError):
    """目标配置或路径不合法；一律拒绝而不是猜。"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def state_dir(project) -> Path:
    return Path(project) / ".webnovel" / STATE_DIR


def profile_path(project) -> Path:
    return state_dir(project) / PROFILE_DIR


def _read(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.is_file():
        return dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BrowserTargetError(f"配置不可读：{path.name}（{error}）") from error
    if not isinstance(data, dict):
        raise BrowserTargetError(f"配置格式不对：{path.name} 必须是对象")
    return data


def _write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bridge.write_json_atomic(path, data)


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _is_link(path: Path) -> bool:
    """符号链接或 Windows 目录联接（junction）。

    Windows 上 `mklink /J` 不需要管理员权限，`Path.is_symlink()` 却是 False，
    所以还要看 reparse point 属性，否则 profile 可以落到作品目录之外。
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _check_profile(profile: Path, project) -> Path:
    """profile 必须落在作品的浏览器状态目录下，不能是项目根或稿件目录。

    审计实测 `profile="."` 会被接受：浏览器的 cookie/密钥就会落进稿件目录，
    用户打包或同步稿件时一起泄出去。这里要求它是 `.webnovel/browser` 的后代。
    """
    resolved = Path(os.path.abspath(str(profile)))
    if _is_link(resolved):
        raise BrowserTargetError("profile 不能是符号链接或目录联接")
    if project is not None:
        root = Path(os.path.abspath(str(project)))
        if not _within(resolved, root):
            raise BrowserTargetError("profile 必须位于作品目录内，拒绝越界路径")
        state = Path(os.path.abspath(str(state_dir(project))))
        if resolved == root or resolved == state or not _within(resolved, state):
            raise BrowserTargetError(
                "profile 必须是作品浏览器状态目录下的子路径（不能是作品根或稿件目录）")
    return resolved


def validate_target(config: Dict[str, Any], *, project=None) -> Dict[str, Any]:
    """校验唯一 target；任何一项缺失或越界都拒绝，不填默认值。"""
    if not isinstance(config, dict):
        raise BrowserTargetError("target 必须是对象")
    required = ("os", "arch", "runtime", "browser", "browser_version", "driver",
                "credential", "scope")
    missing = [key for key in required if not str(config.get(key) or "").strip()]
    if missing:
        raise BrowserTargetError("target 缺少字段：" + "、".join(missing))
    if str(config["os"]).strip().lower() not in _OS_VALUES:
        raise BrowserTargetError("os 只能是 windows、linux 或 macos")
    if str(config["arch"]).strip().lower() not in _ARCH_VALUES:
        raise BrowserTargetError("arch 只能是 x64、arm64 或 amd64")
    if not _VERSION_RE.match(str(config["browser_version"]).strip()):
        raise BrowserTargetError("browser_version 必须写成版本号形状（如 131.0.6778.86）")
    if not re.match(r"^[A-Za-z][A-Za-z0-9 ._\-]{0,63}$", str(config["driver"]).strip()):
        raise BrowserTargetError("driver 只能是驱动名或版本号（字母开头，不含路径分隔符/引号）")
    if config["runtime"] not in ("native", "container"):
        raise BrowserTargetError("runtime 只能是 native 或 container")
    if config["scope"] not in SCOPES:
        raise BrowserTargetError("scope 只能是 read_only 或 publish")
    if config["scope"] == PUBLISH and not str(config.get("authorization") or "").strip():
        raise BrowserTargetError("publish 范围必须写明授权依据（账号/书/章）")
    platform = str(config.get("platform") or DEFAULT_PLATFORM).strip().lower()
    if not re.match(r"^[a-z0-9_\-]{2,32}$", platform):
        raise BrowserTargetError("platform 只能是平台短名（小写字母/数字/下划线）")
    profile = Path(str(config.get("profile") or profile_path(project)))
    if not profile.is_absolute() and project is not None:
        profile = Path(project) / profile
    profile = _check_profile(profile, project)
    config = dict(config)
    config["profile"] = str(profile)
    config["platform"] = platform
    return config


def save_target(project, config: Dict[str, Any]) -> Dict[str, Any]:
    clean = validate_target(config, project=project)
    clean.update({"schema": SCHEMA, "updated_at": _now()})
    _write(state_dir(project) / TARGET_NAME, clean)
    return clean


def load_target(project) -> Dict[str, Any]:
    path = state_dir(project) / TARGET_NAME
    if not path.is_file():
        return {}
    data = _read(path, {})
    # 磁盘上的 target 也要复核：手改 profile 到项目外不能被直接信任。
    return validate_target(data, project=project)


def ensure_profile(project, *, project_target: Optional[Dict[str, Any]] = None,
                   mode: int = 0o700) -> Path:
    """建 profile 目录；已存在时校验不是链接/联接、属主可写。"""
    target = project_target if project_target is not None else load_target(project)
    raw = target.get("profile") if target else None
    path = _check_profile(Path(str(raw or profile_path(project))), project)
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        current = stat.S_IMODE(path.stat().st_mode)
        if current & 0o077:
            os.chmod(path, mode)
    elif os.name == "nt":
        _harden_windows_acl(path)
    return path


def _harden_windows_acl(path: Path) -> None:
    """Windows 上把 profile 的继承权限收掉，只留当前用户。

    审计指出 POSIX 的 0700 在 Windows 不生效、而插件主战场是 Windows；
    `icacls` 在系统自带路径，失败时写 stderr 诊断但不阻止启动（profile 仍可用）。
    """
    import subprocess

    user = os.environ.get("USERNAME") or ""
    if not user:
        return
    try:
        subprocess.run(["icacls", str(path), "/inheritance:r",
                        "/grant:r", f"{user}:(OI)(CI)F"],
                       capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def _journal_path(project) -> Path:
    return state_dir(project) / JOURNAL_NAME


def _lock_path(project) -> Path:
    return state_dir(project) / JOURNAL_LOCK


class _JournalLock:
    """跨进程互斥：O_EXCL 抢锁文件，忙等有上限。

    拒绝路径也会删掉自己刚创建的锁（否则每次崩溃残留都要等满超时）；
    锁目录不可写时转成可读错误，不让 `PermissionError` 冒到 HTTP 层。
    """

    def __init__(self, path: Path, timeout: float = 0.2, stale_after: float = 5.0):
        self.path = path
        self.timeout = timeout
        self.stale_after = stale_after
        self.handle = None

    def _try(self):
        self.handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(self.handle, str(os.getpid()).encode("ascii"))

    def __enter__(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise BrowserTargetError(f"journal 目录不可用：{error}") from error
        deadline = time.monotonic() + self.timeout
        retried = False
        while True:
            try:
                self._try()
                return self
            except PermissionError as error:
                raise BrowserTargetError(f"journal 不可写：{error}") from error
            except FileExistsError:
                try:
                    stale = time.time() - self.path.stat().st_mtime > self.stale_after
                except OSError:
                    stale = True
                if stale:
                    try:
                        self.path.unlink(missing_ok=True)
                    except OSError as error:
                        raise BrowserTargetError(f"journal 锁不可清理：{error}") from error
                    continue
                if time.monotonic() > deadline:
                    if retried:
                        raise BrowserTargetError("journal 被另一个进程占用：稍后重试")
                    # 第二次机会：确认锁仍是别人的就放弃，不制造永久 5 秒延迟
                    retried = True
                    deadline = time.monotonic() + self.timeout
                    continue
                time.sleep(0.02)

    def __exit__(self, *exc):
        if self.handle is not None:
            os.close(self.handle)
            self.handle = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def read_journal(project, *, limit: int = MAX_JOURNAL) -> List[Dict[str, Any]]:
    """读 JSONL 日志尾部的最近 `limit` 条（文件只追加，不重写）。

    坏行（半行写入、非法 UTF-8）跳过而不是让整份日志不可读。
    """
    path = _journal_path(project)
    if not path.is_file():
        return []
    entries: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict):
                    entries.append(item)
    except OSError as error:
        raise BrowserTargetError(f"journal 不可读：{error}") from error
    return entries[-limit:] if limit else entries


def append_journal(project, entry: Dict[str, Any]) -> Dict[str, Any]:
    """只追加一行；并发下不丢条目（整文件重写会丢，已在审计中复现）。"""
    path = _journal_path(project)
    record = dict(entry, at=_now())
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with _JournalLock(_lock_path(project)):
        try:
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise BrowserTargetError(f"journal 不可写：{error}") from error
        _fsync_dir(path.parent)
    return record


def _fsync_dir(folder: Path) -> None:
    """目录 fsync：断电后最后一次 rename/append 才真的落盘（POSIX 有效）。"""
    try:
        fd = os.open(str(folder), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def login_state(project, *, max_age_hours: float = LOGIN_MAX_AGE_HOURS) -> Dict[str, Any]:
    """读登录态，并在读路径上复校验：形状、证据、时效。

    `valid` 必须是适配器写入、带 64 位证据摘要、且在时效内；否则降级为
    `unknown` 并标 `stale`/`invalid_evidence`——手写 login.json 不能冒充登录有效。
    """
    data = _read(state_dir(project) / LOGIN_NAME, {"status": "unknown"})
    status = str(data.get("status") or "unknown")
    if status not in LOGIN_STATES:
        status = "unknown"
    result = dict(data, status=status)
    if status == "valid":
        evidence = str(data.get("evidence") or "").strip().lower()
        if data.get("source") != "adapter" or not SHA256_RE.match(evidence):
            return dict(result, status="unknown", stale=True,
                        invalid_evidence="登录记录缺少适配器证据摘要，不能算有效")
        checked = str(data.get("checked_at") or "")
        stamp = _parse_instant(checked)
        if stamp is None:
            return dict(result, status="unknown", stale=True,
                        invalid_evidence=f"登录记录时间无法解析：{checked}")
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        if age > max_age_hours * 3600:
            return dict(result, status="unknown", stale=True,
                        invalid_evidence=f"登录证据已过期：{checked}")
    return result


def _parse_instant(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone(timedelta(hours=8)))
    return stamp.astimezone(timezone.utc)


def record_login(project, *, status: str, account: str = "", evidence: str = "",
                 reason: str = "", source: str = "adapter") -> Dict[str, Any]:
    """只在适配器真正回读到账号/页面证据时记 valid；客户端只能报非 valid 状态。"""
    if status not in LOGIN_STATES:
        raise BrowserTargetError(f"未知登录状态：{status}")
    if status in ("valid", "expired") and source != "adapter":
        raise BrowserTargetError(
            "valid/expired 只能由适配器回读 profile 后写入：客户端不能自证登录状态")
    if status == "valid":
        if not (account.strip() and evidence.strip()):
            raise BrowserTargetError("没有账号别名与页面证据，不能记登录有效")
        if not SHA256_RE.match(str(evidence).strip().lower()):
            raise BrowserTargetError("evidence 必须是页面证据摘要（64 位十六进制）")
    data = {"schema": SCHEMA, "status": status, "account": account.strip(),
            "evidence": evidence.strip().lower(), "reason": reason.strip(),
            "source": source, "checked_at": _now()}
    _write(state_dir(project) / LOGIN_NAME, data)
    return data


class AdapterUnavailable(RuntimeError):
    """没有可用适配器 / 二进制缺失 / 依赖缺失。"""


class AdapterNeedsHuman(RuntimeError):
    """需要本人扫码/验证码/授权回调。"""


class AdapterResultUnknown(RuntimeError):
    """写入结果未知：只对账，不重试。"""


def launch(adapter, project, *, headless: bool = False) -> Dict[str, Any]:
    """启动浏览器并返回会话描述；失败按原因分类，不吞异常。"""
    target = load_target(project)
    if not target:
        raise BrowserTargetError("还没有配置 target：先写唯一目标再启动浏览器")
    profile = ensure_profile(project, project_target=target)
    if adapter is None:
        raise AdapterUnavailable("没有可用的浏览器适配器：本机未提供驱动，拒绝对外写入")
    try:
        session = adapter.launch(profile=str(profile), headless=bool(headless),
                                 browser=target.get("browser"),
                                 version=target.get("browser_version"))
    except FileNotFoundError as error:
        raise AdapterUnavailable(f"浏览器或驱动不存在：{error}") from error
    except PermissionError as error:
        raise AdapterUnavailable(f"profile 权限不足：{error}") from error
    except TimeoutError as error:
        raise AdapterNeedsHuman(f"启动等待超时：{error}") from error
    if not isinstance(session, dict) or not session.get("started"):
        raise AdapterUnavailable("适配器未确认浏览器已启动")
    append_journal(project, {"kind": "launch", "headless": bool(headless),
                             "browser": target.get("browser"),
                             "version": target.get("browser_version")})
    return dict(session, profile=str(profile))


def health(adapter) -> Dict[str, Any]:
    if adapter is None:
        return {"ok": False, "reason": "adapter_unavailable"}
    try:
        report = adapter.health()
    except AdapterUnavailable:
        return {"ok": False, "reason": "adapter_unavailable"}
    except Exception as error:  # 适配器自己的异常不当作健康
        return {"ok": False, "reason": f"health_error:{error}"}
    return dict(report or {"ok": False, "reason": "no_report"})


def stop(adapter, project, *, reason: str = "author") -> Dict[str, Any]:
    result = {"stopped": False, "reason": reason}
    if adapter is None:
        return result
    try:
        result["stopped"] = bool(adapter.close())
    except Exception as error:  # 退出失败只记，不抛
        result["error"] = str(error)
    append_journal(project, {"kind": "stop", "reason": reason,
                             "stopped": result["stopped"]})
    return result


def _writes(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def verify_readonly(adapter, project, *, book_id: str, chapter: int,
                    expect_body_sha256: str = "") -> Dict[str, Any]:
    """只读核验：五项身份必须与请求一致，任何一项不符都具体说明。

    `expect_body_sha256` 是从本地正文算出的期望摘要：给了就必须相等，否则只能
    证明「页面返回过某个 64 位十六进制」，不能证明「读到了这一章的这一版」。
    """
    if adapter is None:
        return {"status": "unavailable", "reason": "adapter_unavailable",
                "writes": 0, "writes_confirmed": 0}
    if not str(book_id or "").strip():
        return {"status": "needs_review", "reason": "缺少作品稳定 ID",
                "writes": 0, "writes_confirmed": 0}
    expected = str(expect_body_sha256 or "").strip().lower()
    if expected and not SHA256_RE.match(expected):
        return {"status": "needs_review", "writes": 0, "writes_confirmed": 0,
                "reason": "期望正文摘要不是 64 位十六进制：无法据此核对"}
    target = load_target(project) or {}
    platform = str(target.get("platform") or DEFAULT_PLATFORM)
    try:
        row = adapter.read_chapter(book_id=book_id, chapter=int(chapter))
    except AdapterNeedsHuman as error:
        return {"status": "needs_human", "reason": str(error), "writes": 0,
                "writes_confirmed": 0}
    except AdapterUnavailable as error:
        return {"status": "unavailable", "reason": str(error), "writes": 0,
                "writes_confirmed": 0}
    except Exception as error:
        return {"status": "needs_review", "reason": f"读取失败：{error}", "writes": 0,
                "writes_confirmed": 0}
    if not isinstance(row, dict):
        return {"status": "needs_review", "reason": "适配器没有返回结构化行",
                "writes": 0, "writes_confirmed": 0}
    writes = _writes(row.get("writes"))
    missing = [key for key in IDENTITY_KEYS if not str(row.get(key) or "").strip()]
    if missing:
        return {"status": "needs_review", "writes": writes, "writes_confirmed": 0,
                "reason": "缺少身份字段：" + "、".join(missing)}
    if str(row.get("platform") or "").strip().lower() != platform:
        return {"status": "needs_review", "writes": writes, "writes_confirmed": 0,
                "reason": f"平台不符：页面是 {row.get('platform')}，target 是 {platform}"}
    expected_account = str(target.get("account") or "").strip()
    if expected_account and str(row.get("account") or "").strip() != expected_account:
        return {"status": "needs_review", "writes": writes, "writes_confirmed": 0,
                "reason": f"账号不符：页面是 {row.get('account')}，target 是 {expected_account}"}
    if str(row.get("book_id") or "").strip() != str(book_id).strip():
        return {"status": "needs_review", "writes": writes, "writes_confirmed": 0,
                "reason": "作品 ID 与请求不一致（可能是同名的另一本书）"}
    try:
        seen_chapter = int(str(row.get("chapter_id")).strip())
    except (TypeError, ValueError):
        return {"status": "needs_review", "writes": writes, "writes_confirmed": 0,
                "reason": "章节 ID 不是数字，无法核对"}
    if seen_chapter != int(chapter):
        return {"status": "needs_review", "writes": writes, "writes_confirmed": 0,
                "reason": "章号与请求不一致"}
    body = str(row.get("content_sha256") or "").strip().lower()
    if not SHA256_RE.match(body):
        return {"status": "needs_review", "writes": writes, "writes_confirmed": 0,
                "reason": "正文证据不是 sha256 摘要，不能算回读成功"}
    if expected and body != expected:
        return {"status": "needs_review", "writes": writes, "writes_confirmed": 0,
                "reason": "正文摘要与本地期望不一致：页面上的这一章不是当前版本",
                "expected_sha256": expected, "observed_sha256": body}
    if writes:
        return {"status": "needs_review", "writes": writes, "writes_confirmed": 0,
                "reason": f"只读核验期间适配器报告了 {writes} 次写入"}
    append_journal(project, {"kind": "readonly", "book_id": book_id,
                             "chapter": int(chapter), "content_sha256": body,
                             "expected_sha256": expected, "writes": 0,
                             "status": "verified"})
    return {"status": "verified", "reason": "", "writes": 0, "writes_confirmed": 0,
            "expected_sha256": expected, "observed_sha256": body,
            "identity": {key: row[key] for key in IDENTITY_KEYS}}


def _intent_key(book_id: str, chapter: int, body_sha256: str = "") -> str:
    seed = f"{book_id}|{int(chapter)}|{str(body_sha256 or '').strip().lower()}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


LEDGER_KEY_RE = re.compile(r"^[0-9a-f]{16}$")


def _ledger_dir(project) -> Path:
    return state_dir(project) / LEDGER_DIR


def _ledger_path(project, key: str) -> Path:
    """账本路径：键必须是 16 位十六进制，且解析后仍在本目录内。

    审计实测过 `key="..\\..\\..\\victim"` 能把任意 JSON 覆盖掉，这里两道闸：
    形状校验 + 解析后父目录比对。
    """
    folder = _ledger_dir(project)
    text = str(key or "")
    if not LEDGER_KEY_RE.match(text):
        raise BrowserTargetError(f"账本键不合法：{text!r}（应为 16 位十六进制）")
    path = folder / f"{text}.json"
    try:
        folder_resolved = folder.resolve()
        path_resolved = path.resolve()
    except OSError as error:
        raise BrowserTargetError(f"账本路径不可解析：{error}") from error
    if path_resolved.parent != folder_resolved:
        raise BrowserTargetError(f"账本路径越界：{text}")
    return path


def ledger_state(project, key: str) -> Dict[str, Any]:
    path = _ledger_path(project, key)
    if not path.is_file():
        return {}
    return _read(path, {})


def _ledger_write(project, key: str, data: Dict[str, Any]) -> Dict[str, Any]:
    record = dict(data, schema=SCHEMA, key=key, updated_at=_now())
    _write(_ledger_path(project, key), record)
    return record


def _claim_ledger(project, key: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """用 O_EXCL 占位：两个进程只有一个能拿到该键，另一个直接判重复。"""
    path = _ledger_path(project, key)
    record = dict(data, schema=SCHEMA, key=key, created_at=_now(), updated_at=_now())
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    except OSError as error:
        raise BrowserTargetError(f"账本不可写：{error}") from error
    try:
        os.write(handle, json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        os.fsync(handle)
    finally:
        os.close(handle)
    _fsync_dir(path.parent)
    return record


def _other_body_ledger(project, *, book_id: str, chapter: int,
                       body: str) -> Dict[str, Any]:
    """同一章、不同正文摘要的既有记录（用于拦住「改稿即重投」）。"""
    folder = _ledger_dir(project)
    if not folder.is_dir():
        return {}
    for path in sorted(folder.glob("*.json")):
        data = _read(path, {})
        if not isinstance(data, dict):
            continue
        if str(data.get("book_id")) != str(book_id):
            continue
        try:
            same_chapter = int(data.get("chapter") or 0) == int(chapter)
        except (TypeError, ValueError):
            continue
        if not same_chapter:
            continue
        if str(data.get("body_sha256") or "").lower() == body:
            continue
        if str(data.get("state")) in ("superseded", "abandoned"):
            continue
        return dict(data, key=str(data.get("key") or path.stem))
    return {}


_ADAPTER = None


def register(adapter) -> None:
    """登记唯一适配器（试点只有一个目标，因此只允许一个槽）。"""
    global _ADAPTER
    _ADAPTER = adapter


def current():
    return _ADAPTER


def clear_adapter() -> None:
    global _ADAPTER
    _ADAPTER = None


def publish_once(adapter, project, *, book_id: str, chapter: int,
                 body_sha256: str, replace: bool = False) -> Dict[str, Any]:
    """真实投递：先落意图账本，再写一次，再回读；未知结果只进对账。

    幂等键用「作品 + 章 + 正文摘要」。同一章已有别的正文摘要时**默认拒绝**：
    改稿后再写一次属于第二次真实写入，必须由作者显式 `replace=True`，并要求
    先把旧键对账成 `superseded`。同键用 `O_EXCL` 占位，两个进程只有一个能写。
    """
    target = load_target(project)
    if target.get("scope") != PUBLISH:
        return {"status": "refused", "reason": "target 未声明 publish 范围", "writes": 0}
    if not str(target.get("authorization") or "").strip():
        return {"status": "refused", "reason": "缺少授权依据（target 未记录授权）", "writes": 0}
    if adapter is None:
        return {"status": "unavailable", "reason": "adapter_unavailable", "writes": 0}
    body = str(body_sha256 or "").strip().lower()
    if not SHA256_RE.match(body):
        raise BrowserTargetError("body_sha256 必须是 64 位十六进制摘要")
    key = _intent_key(book_id, chapter, body)
    seen = ledger_state(project, key)
    if seen and seen.get("state") != "abandoned":
        return {"status": "duplicate",
                "reason": f"该章该版本已有投递记录（{seen.get('state')}），先去对账",
                "writes": 0, "ledger": seen}
    previous = _other_body_ledger(project, book_id=book_id, chapter=chapter, body=body)
    if previous and str(previous.get("state")) != "abandoned" and not replace:
        return {"status": "refused", "writes": 0,
                "reason": "该章已有另一版本的投递记录：改稿后重投要显式 replace，"
                          "并先把旧记录对账成 superseded",
                "previous": {"key": previous.get("key"), "state": previous.get("state"),
                             "body_sha256": previous.get("body_sha256")}}
    if previous and replace:
        _ledger_write(project, str(previous.get("key") or ""),
                      dict(previous, state="superseded", superseded_at=_now()))
        append_journal(project, {"kind": "publish", "key": previous.get("key"),
                                 "state": "superseded"})
    writes = 1
    if seen and seen.get("state") == "abandoned":
        # 作者已把这条记录对账成放弃：清掉旧文件才能重新占位，同时留一条 journal。
        try:
            _ledger_path(project, key).unlink(missing_ok=True)
        except OSError as error:
            raise BrowserTargetError(f"旧账本不可清理：{error}") from error
        append_journal(project, {"kind": "publish", "key": key, "state": "reopened"})
    claim = _claim_ledger(project, key, {"state": "intent", "book_id": book_id,
                                         "chapter": int(chapter), "body_sha256": body,
                                         "writes_attempted": 0, "writes_confirmed": 0})
    if claim is None:
        return {"status": "duplicate", "writes": 0,
                "reason": "另一个进程已抢先占用该章该版本的账本：直接对账，不重复写",
                "ledger": ledger_state(project, key)}
    append_journal(project, {"kind": "publish", "key": key, "book_id": book_id,
                             "chapter": int(chapter), "body_sha256": body,
                             "state": "intent"})
    try:
        result = adapter.publish_chapter(book_id=book_id, chapter=int(chapter),
                                         body_sha256=body)
    except AdapterNeedsHuman as error:
        _ledger_write(project, key, {"state": "needs_human", "book_id": book_id,
                                     "chapter": int(chapter), "body_sha256": body,
                                     "writes_attempted": 0, "writes_confirmed": 0,
                                     "reason": str(error)})
        append_journal(project, {"kind": "publish", "key": key, "state": "needs_human"})
        return {"status": "needs_human", "reason": str(error), "writes": 0}
    except AdapterUnavailable as error:
        _ledger_write(project, key, {"state": "aborted", "book_id": book_id,
                                     "chapter": int(chapter), "body_sha256": body,
                                     "writes_attempted": 0, "writes_confirmed": 0,
                                     "reason": str(error)})
        append_journal(project, {"kind": "publish", "key": key, "state": "aborted"})
        return {"status": "unavailable", "reason": str(error), "writes": 0}
    except Exception as error:
        _ledger_write(project, key, {"state": "unknown", "book_id": book_id,
                                     "chapter": int(chapter), "body_sha256": body,
                                     "writes_attempted": writes, "writes_confirmed": 0,
                                     "error": str(error)})
        append_journal(project, {"kind": "publish", "key": key, "state": "unknown",
                                 "error": str(error)})
        return {"status": "unknown", "reason": "提交结果未知：只对账，不重试",
                "writes": writes, "writes_confirmed": 0}
    if not isinstance(result, dict) or not result.get("accepted"):
        _ledger_write(project, key, {"state": "unknown", "book_id": book_id,
                                     "chapter": int(chapter), "body_sha256": body,
                                     "writes_attempted": writes, "writes_confirmed": 0,
                                     "result": result})
        append_journal(project, {"kind": "publish", "key": key, "state": "unknown",
                                 "result": result})
        return {"status": "unknown", "reason": "适配器未确认接收", "writes": writes,
                "writes_confirmed": 0}
    echoed = str(result.get("content_sha256") or "").strip().lower()
    matches = bool(echoed) and echoed == body
    _ledger_write(project, key, {"state": "accepted", "book_id": book_id,
                                 "chapter": int(chapter), "body_sha256": body,
                                 "writes_attempted": writes, "writes_confirmed": 1 if matches else 0,
                                 "echoed_sha256": echoed, "body_matches": matches,
                                 "result": result})
    append_journal(project, {"kind": "publish", "key": key, "state": "accepted",
                             "body_matches": matches})
    return {"status": "accepted", "reason": "", "writes": writes,
            "writes_confirmed": 1 if matches else 0,
            "body_matches": matches, "result": result}


def reconcile_publish(project, *, key: str = "", book_id: str = "", chapter: int = 0,
                      resolution: str = "", note: str = "") -> Dict[str, Any]:
    """人工对账：把 unknown/needs_human/aborted 的账本条目标成已确认或已放弃。

    `key` 必须符合账本键形状（16 位十六进制），否则拒绝——审计里这条路径曾能
    覆写作品目录外的任意 JSON。扫描时坏账本只跳过并计数，不让一条脏数据锁死对账。
    """
    resolution = (resolution or "").strip()
    if resolution not in ("accepted", "abandoned"):
        raise BrowserTargetError("resolution 只能是 accepted 或 abandoned")
    keys: List[str] = []
    if key:
        keys = [str(key).strip()]
    skipped = 0
    corrupt = 0
    if not keys:
        base = _ledger_dir(project)
        if base.is_dir():
            for path in sorted(base.glob("*.json")):
                try:
                    data = _read(path, {})
                except BrowserTargetError:
                    corrupt += 1
                    continue
                if not isinstance(data, dict) or not data:
                    corrupt += 1
                    continue
                if book_id and str(data.get("book_id")) != str(book_id):
                    continue
                if chapter:
                    try:
                        if int(data.get("chapter") or 0) != int(chapter):
                            continue
                    except (TypeError, ValueError):
                        skipped += 1
                        continue
                if not LEDGER_KEY_RE.match(path.stem):
                    skipped += 1
                    continue
                keys.append(path.stem)
    changed = 0
    for item in keys:
        data = ledger_state(project, item)
        if not data:
            continue
        if resolution == "accepted":
            _ledger_write(project, item, dict(data, state="accepted",
                                              writes_confirmed=1,
                                              reconciled_by="author", note=note))
        else:
            _ledger_write(project, item, dict(data, state="abandoned",
                                              reconciled_by="author", note=note))
        append_journal(project, {"kind": "publish", "key": item,
                                 "state": f"reconciled_{resolution}"})
        changed += 1
    return {"changed": changed, "resolution": resolution, "keys": keys,
            "skipped": skipped, "corrupt": corrupt}


def _last_readonly(project) -> Dict[str, Any]:
    """最近一条真实只读核验记录；没有就是空串/空字典，不合成指针。"""
    if project is None:
        return {}
    for entry in reversed(read_journal(project, limit=MAX_JOURNAL)):
        if entry.get("kind") == "readonly" and entry.get("status") == "verified":
            return entry
    return {}


def capability_row(project=None, *, target: Optional[Dict[str, Any]] = None,
                   login: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """八列状态：每列只写 real/simulated/pending，不把「配了」当成「验过」。

    `readonly` 只认 journal 里真有 `status=verified` 的记录；手写 login.json 不够。
    """
    target = target if target is not None else (load_target(project) if project else {})
    login = login if login is not None else (login_state(project) if project else {})
    readonly = _last_readonly(project)
    row = {column: PENDING for column in COLUMNS}
    if target:
        verified_login = login.get("status") == "valid" and login.get("source") == "adapter"
        row["launch"] = SIMULATED if target.get("browser") else PENDING
        row["credential"] = SIMULATED if target.get("credential") else PENDING
        row["browser_login"] = SIMULATED if verified_login else PENDING
        row["readonly"] = SIMULATED if readonly else PENDING
        row["publish"] = PENDING
        row["schedule"] = PENDING
        row["model"] = SIMULATED if target.get("model") else PENDING
        row["install"] = PENDING
    return row


def capability_evidence(project, *, target: Optional[Dict[str, Any]] = None,
                        login: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """每列的「证据」：适配器名/时间/journal 指针，空串表示没有证据。"""
    target = target if target is not None else (load_target(project) if project else {})
    login = login if login is not None else (login_state(project) if project else {})
    readonly = _last_readonly(project)
    evidence = {column: "" for column in COLUMNS}
    if target:
        evidence["launch"] = "target:browser=%s@%s" % (target.get("browser"),
                                                       target.get("browser_version"))
        evidence["credential"] = "target:credential=%s" % target.get("credential")
    if login.get("status") == "valid" and login.get("source") == "adapter":
        evidence["browser_login"] = "login:%s@%s" % (login.get("status"),
                                                     login.get("checked_at"))
    if readonly:
        evidence["readonly"] = "journal:readonly:%s@%s" % (
            readonly.get("chapter"), readonly.get("at"))
    return evidence


def status(project) -> Dict[str, Any]:
    target = load_target(project)
    login = login_state(project)
    return {"schema": SCHEMA, "target": target, "login": login,
            "profile": str(Path(str((target or {}).get("profile") or profile_path(project)))),
            "journal": len(read_journal(project)),
            "capabilities": capability_row(project, target=target, login=login),
            "evidence": capability_evidence(project, target=target, login=login)}
