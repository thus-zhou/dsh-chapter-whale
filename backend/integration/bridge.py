"""把 webnovel-writer 的 Markdown 章节安全地交给番茄发布器。

这个文件只依赖 Python 标准库。两个上游仓库保持独立，桥接层负责：

* 从 webnovel 项目读取 ``正文/*.md``；
* 去掉 Markdown 标记并写入 ``fanqie_auto_publish/chapters/<书名>/*.txt``；
* 用 manifest 记录源文件、哈希和发布状态，避免重复排队；
* 调用 fanqie_auto_publish 原有的 Playwright 发布脚本；
* 根据 ``uploaded/`` 归档目录同步状态。

默认目录是当前组合工程的两个兄弟目录，也可用环境变量覆盖：
``NOVEL_HELPER_ROOT``、``NOVEL_HELPER_WEBNOVEL_ROOT``、
``NOVEL_HELPER_FANQIE_ROOT``、``NOVEL_HELPER_MANIFEST``、
``NOVEL_HELPER_ACCOUNTS_ROOT``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fanqie_auto_publish.publication_safety import (
    PublicationBlocked, account_lock, atomic_json, creative_contract_hash, digest_file, file_lock, review_eligible, body_digest,
    journal_path, queue_lock, read_json_strict, valid_receipt,
)


def park_unsubmitted_queue_for_revision(project,book,account,chapter,source):
    """Recoverably park only an exact local draft with NO publisher journal.

    A changed author length requirement must not leave stale queued bytes that
    permanently prevent the next recovery. Any remote attempt stays read-only.
    """
    with queue_lock(FANQIE_ROOT):
        record=load_manifest().get('books',{}).get(safe_dir_name(book),{})
        if Path(record.get('project_root','')).resolve()!=Path(project).resolve() or record.get('account')!=account:
            raise ValueError('修订队列的账号或作品不匹配')
        queued=queued_chapters(QUEUE_ROOT/safe_dir_name(book))
        path=queued.get(chapter)
        if path is None:return None
        if journal_path(path).exists():raise ValueError('该章已有发布器记录，必须先核验，不能自动改写或覆盖')
        expected=markdown_to_plaintext(Path(source).read_text(encoding='utf-8-sig'),chapter)
        if digest_file(path)!=hashlib.sha256(expected.encode('utf-8')).hexdigest():
            raise ValueError('待修订队列正文与来源不一致，禁止覆盖')
        backup=RUNTIME_ROOT/'queue-revisions'/safe_dir_name(book)/uuid.uuid4().hex/path.name
        backup.parent.mkdir(parents=True,exist_ok=False)
        atomic_json(backup.parent/'revision.json',{'chapter':chapter,'book':book,'account':account,
            'original_queue':str(path),'sha256':digest_file(path),'at':now_iso(),'reason':'author_length_revision_before_publisher'})
        path.replace(backup)
        return str(backup)


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser().resolve() if value else default.resolve()


SCRIPT_ROOT = Path(__file__).resolve().parent
COMBINED_ROOT = _path_from_env("NOVEL_HELPER_ROOT", SCRIPT_ROOT.parent)
WEBNOVEL_ROOT = _path_from_env(
    "NOVEL_HELPER_WEBNOVEL_ROOT", COMBINED_ROOT / "webnovel-writer"
)
FANQIE_ROOT = _path_from_env(
    "NOVEL_HELPER_FANQIE_ROOT", COMBINED_ROOT / "fanqie_auto_publish"
)
QUEUE_ROOT = FANQIE_ROOT / "chapters"
UPLOADED_ROOT = FANQIE_ROOT / "uploaded"
MANIFEST_PATH = _path_from_env(
    "NOVEL_HELPER_MANIFEST", COMBINED_ROOT / "integration_data" / "manifest.json"
)
ACCOUNTS_ROOT = _path_from_env(
    "NOVEL_HELPER_ACCOUNTS_ROOT", COMBINED_ROOT / "accounts"
)
RUNTIME_ROOT = COMBINED_ROOT / "integration_data" / "runtime"
PUBLISH_SCRIPT = FANQIE_ROOT / "publish.py"

_CHAPTER_PATTERNS = (
    re.compile(r"第\s*0*(\d+)\s*章(?:[：:\-＿_\s]*(.*))?$"),
    re.compile(r"^\s*0*(\d+)(?:[：:\-＿_\s]*(.*))?$"),
)
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_dir_name(value: str) -> str:
    """生成 Windows 可用且不带路径穿越含义的目录名。"""

    value = str(value or "").strip()
    value = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", value)
    value = value.rstrip(" .")
    if not value:
        value = "未命名小说"
    if value.upper().split(".", 1)[0] in _RESERVED_WINDOWS_NAMES:
        value = "_" + value
    return value[:96]


def account_dir(account_name: str) -> Path:
    """返回账号资料目录；目录名只允许经过安全化处理。"""

    name = str(account_name or "").strip()
    if not name:
        raise ValueError("账号名称不能为空")
    if safe_dir_name(name) != name:
        raise ValueError("账号名称包含不安全字符或会与其他名称混淆")
    folder = ACCOUNTS_ROOT / name
    if folder.is_symlink() or folder.resolve().parent != ACCOUNTS_ROOT.resolve():
        raise ValueError("不安全的账号目录")
    profile = read_json_strict(folder / "profile.json") if (folder / "profile.json").exists() else {}
    if profile.get("name", name) != name:
        raise ValueError("账号目录与登记名称不匹配")
    return folder


def account_state_path(account_name: str) -> Path:
    return account_dir(account_name) / "state.json"


def list_accounts() -> List[Dict[str, Any]]:
    """列出 O 盘账号资料，不读取或打印 Cookie 内容。"""

    result: List[Dict[str, Any]] = []
    if not ACCOUNTS_ROOT.is_dir():
        return result
    for folder in sorted(ACCOUNTS_ROOT.iterdir(), key=lambda item: item.name.casefold()):
        if not folder.is_dir():
            continue
        profile = read_json(folder / "profile.json", {})
        display_name = (
            profile.get("name") if isinstance(profile, dict) else None
        ) or folder.name
        result.append(
            {
                "name": str(display_name),
                "folder": folder.name,
                "logged_in": (folder / "state.json").is_file(),
                "state_file": str(folder / "state.json"),
            }
        )
    return result


@contextmanager
def runtime_lock(lock_name: str):
    """OS locks auto-release after a crash; never use os.kill(pid, 0) on Windows."""
    if lock_name.startswith("account-login-"):
        with account_lock(account_state_path(lock_name[len("account-login-"):])) as path:
            yield path
    else:
        with file_lock(RUNTIME_ROOT / f"{safe_dir_name(lock_name)}.lock") as path:
            yield path


@contextmanager
def account_runtime(account_name: Optional[str]):
    """Yield an explicit isolated state path. Never exchange root state files.

    Callers must pass this path to the publisher. No Cookie writeback occurs.
    """
    source_state = account_state_path(account_name) if account_name else FANQIE_ROOT / "state.json"
    if not source_state.is_file():
        raise FileNotFoundError("账号尚未登录，请先执行 login --account")
    with account_lock(source_state):
        yield source_state.resolve()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def write_json_atomic(path: Path, data: Any) -> None:
    atomic_json(path, data)


def load_manifest() -> Dict[str, Any]:
    data = read_json_strict(MANIFEST_PATH) if MANIFEST_PATH.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("manifest 必须是对象，禁止清空损坏状态")
    data.setdefault("version", 1)
    data.setdefault("updated_at", "")
    data.setdefault("books", {})
    if not isinstance(data["books"], dict):
        raise ValueError("manifest books 必须是对象")
    return data


def save_manifest(data: Dict[str, Any]) -> None:
    data["updated_at"] = now_iso()
    write_json_atomic(MANIFEST_PATH, data)


def project_title(project_root: Path, override: Optional[str] = None) -> str:
    if override and override.strip():
        return override.strip()
    state_path = project_root / ".webnovel" / "state.json"
    state = read_json(state_path, {})
    if isinstance(state, dict):
        nested = state.get("project_info")
        if isinstance(nested, dict) and nested.get("title"):
            return str(nested["title"]).strip()
        if state.get("title"):
            return str(state["title"]).strip()
    return project_root.name


def parse_chapter_name(name: str) -> Optional[Tuple[int, str]]:
    stem = Path(name).stem.strip()
    for pattern in _CHAPTER_PATTERNS:
        match = pattern.search(stem)
        if match:
            chapter_id = int(match.group(1))
            title = (match.group(2) or "").strip(" -—–_：:　")
            return chapter_id, title
    return None


def title_from_content(content: str, chapter_id: int) -> str:
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s*", "", line).strip()
        parsed = parse_chapter_name(line)
        if parsed and parsed[0] == chapter_id:
            return parsed[1]
        break
    return ""


def iter_source_chapters(project_root: Path) -> Iterable[Tuple[Path, int, str, str]]:
    chapters_dir = project_root / "正文"
    if not chapters_dir.is_dir():
        raise FileNotFoundError(f"项目没有找到正文目录：{chapters_dir}")
    files = sorted(chapters_dir.glob("*.md"), key=lambda path: path.name.casefold())
    parsed_files: List[Tuple[Path, int, str]] = []
    for path in files:
        parsed = parse_chapter_name(path.name)
        if not parsed:
            continue
        chapter_id, title = parsed
        content = path.read_text(encoding="utf-8-sig")
        title = title or title_from_content(content, chapter_id)
        parsed_files.append((path, chapter_id, title))
    parsed_files.sort(key=lambda item: (item[1], item[0].name.casefold()))
    for path, chapter_id, title in parsed_files:
        yield path, chapter_id, title, path.read_text(encoding="utf-8-sig")


def markdown_to_plaintext(content: str, chapter_id: int = 0) -> str:
    """把章节 Markdown 转成番茄编辑器可接受的纯文本。"""

    # 作者用记事本/Word 保存的 .md 常带 BOM：统一剥离，避免首行标题既进正文
    # 又让 bridge 与 writer_runner 的正文摘要不一致。
    content = content.lstrip("\ufeff")
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    result: List[str] = []
    for raw_line in content.split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            result.append("")
            continue

        heading = re.match(r"^\s*#{1,6}\s*(.*)$", line)
        if heading:
            heading_text = heading.group(1).strip()
            parsed = parse_chapter_name(heading_text)
            if parsed and (not chapter_id or parsed[0] == chapter_id):
                continue
            line = heading_text

        # 链接保留可读文本，图片只保留替代文字。
        line = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        line = re.sub(r"(\*\*|__)(.*?)\1", r"\2", line)
        line = re.sub(r"(~~)(.*?)\1", r"\2", line)
        line = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", line)
        line = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", line)
        line = re.sub(r"^\s*>\s?", "", line)
        result.append(line)

    while result and not result[0].strip():
        result.pop(0)
    while result and not result[-1].strip():
        result.pop()
    return "\n".join(result) + ("\n" if result else "")


def output_filename(chapter_id: int, title: str) -> str:
    if title and (re.search(r'[\x00-\x1f<>:"/\\|?*]', title) or title.endswith((" ", "."))):
        raise ValueError("章节标题不适合作为安全文件名")
    width = max(3, len(str(chapter_id)))
    suffix = f" {title}" if title else ""
    return f"{chapter_id:0{width}d} 第{chapter_id}章{suffix}.txt"


def _chapter_number_from_txt(path: Path) -> Optional[int]:
    parsed = parse_chapter_name(path.name)
    return parsed[0] if parsed else None


def archived_chapters(book_dir: Path) -> Dict[int, Path]:
    result: Dict[int, Path] = {}
    if not book_dir.is_dir():
        return result
    for path in sorted(book_dir.rglob("*.txt"), key=lambda item: str(item).casefold()):
        chapter_id = _chapter_number_from_txt(path)
        if chapter_id is not None:
            if chapter_id in result:
                raise ValueError("同章号存在多个队列或归档文件")
            if path.is_symlink() or book_dir.resolve() not in path.resolve().parents:
                raise ValueError("不安全的章节路径")
            result[chapter_id] = path
    return result


def queued_chapters(book_dir: Path) -> Dict[int, Path]:
    return archived_chapters(book_dir)


def _record_for_book(manifest: Dict[str, Any], safe_book: str, display_name: str, project_root: Path) -> Dict[str, Any]:
    books = manifest.setdefault("books", {})
    record = books.setdefault(safe_book, {})
    if record and (record.get("display_name") != display_name or
                   Path(record.get("project_root", "")).resolve() != project_root.resolve()):
        raise ValueError("书籍队列已绑定其他项目或平台书名")
    record.setdefault("display_name", display_name)
    record.setdefault("project_root", str(project_root))
    record.setdefault("chapters", {})
    if not isinstance(record["chapters"], dict):
        record["chapters"] = {}
    return record


def _select_ids(
    chapter_id: int,
    selected: Optional[Set[int]],
    start: Optional[int],
    end: Optional[int],
) -> bool:
    if selected and chapter_id not in selected:
        return False
    if start is not None and chapter_id < start:
        return False
    if end is not None and chapter_id > end:
        return False
    return True


def _queue_serialized(function):
    @wraps(function)
    def call(*args, **kwargs):
        with queue_lock(FANQIE_ROOT):
            return function(*args, **kwargs)
    return call


def _stage_serialized(function):
    @wraps(function)
    def call(project_path, *args, **kwargs):
        book = project_title(Path(project_path), kwargs.get("book_name") or (args[0] if args else None))
        with book_runtime(Path(project_path), book), queue_lock(FANQIE_ROOT):
            return function(project_path, *args, **kwargs)
    return call


@contextmanager
def book_runtime(project: Path, book: str):
    """Serialize a project's stage/publish transaction without locking the child.

    Does not imply review approval. validate_queue_origin performs that check.
    """
    token = hashlib.sha256(safe_dir_name(book).casefold().encode("utf-8")).hexdigest()
    with file_lock(FANQIE_ROOT / ".publication" / f"book-{token}.lock"):
        manifest = load_manifest()
        _record_for_book(manifest, safe_dir_name(book), book, Path(project).resolve())
        yield


@_stage_serialized
def stage_project(
    project_path: Path,
    book_name: Optional[str] = None,
    selected_ids: Optional[Set[int]] = None,
    start: Optional[int] = None,
    end: Optional[int] = None,
    force: bool = False,
    include_published: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """把一个 webnovel 项目排入 fanqie_auto_publish 队列。"""

    project_root = project_path.expanduser().resolve()
    if not project_root.is_dir():
        raise FileNotFoundError(f"项目目录不存在：{project_root}")

    display_name = project_title(project_root, book_name)
    safe_book = safe_dir_name(display_name)
    queue_dir = QUEUE_ROOT / safe_book
    uploaded_dir = UPLOADED_ROOT / safe_book
    archived = archived_chapters(uploaded_dir)
    manifest = load_manifest()
    record = _record_for_book(manifest, safe_book, display_name, project_root)
    record["display_name"] = display_name
    record["project_root"] = str(project_root)

    staged: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    invalid: List[Dict[str, Any]] = []
    # Check all filenames before writing any files in a potentially mixed batch.
    for _, number, title, _ in iter_source_chapters(project_root):
        output_filename(number, title)

    sources = list(iter_source_chapters(project_root))
    ids = [item[1] for item in sources]
    if len(set(ids)) != len(ids):
        raise ValueError("源项目中同章号对应多个文件")
    for source, chapter_id, title, markdown in sources:
        if not _select_ids(chapter_id, selected_ids, start, end):
            continue
        if chapter_id in archived and not include_published:
            item = {
                "chapter_id": chapter_id,
                "source": str(source),
                "status": "published" if valid_receipt(archived[chapter_id], display_name, chapter_id) else "archive_unverified",
                "uploaded_path": str(archived[chapter_id]),
            }
            record["chapters"][str(chapter_id)] = {
                **record["chapters"].get(str(chapter_id), {}),
                **item,
            }
            skipped.append(item)
            continue

        body = markdown_to_plaintext(markdown, chapter_id)
        if not body.strip():
            item = {"chapter_id": chapter_id, "source": str(source), "status": "empty"}
            invalid.append(item)
            record["chapters"][str(chapter_id)] = {
                **record["chapters"].get(str(chapter_id), {}),
                **item,
            }
            continue

        filename = output_filename(chapter_id, title)
        destination = queue_dir / filename
        content_hash = sha256_text(body)
        existing_same_number = [
            path
            for path in queued_chapters(queue_dir).values()
            if _chapter_number_from_txt(path) == chapter_id and path != destination
        ]
        existing_path = destination if destination.exists() else (existing_same_number[0] if existing_same_number else None)
        if destination.resolve().parent != queue_dir.resolve() or queue_dir.is_symlink():
            raise ValueError("不安全的队列路径")
        if existing_path and journal_path(existing_path).exists():
            attempt = read_json_strict(journal_path(existing_path))
            if attempt.get("state") not in {"preparing", "blocked_before_submit"}:
                raise ValueError("已有发布尝试结果待核验，禁止覆盖或重排")

        item = {
            "chapter_id": chapter_id,
            "title": title,
            "source": str(source),
            "source_relative": str(source.relative_to(project_root)),
            "destination": str(destination),
            "sha256": content_hash,
            "source_sha256": digest_file(source),
        }

        if existing_path is not None:
            existing_hash = sha256_text(existing_path.read_text(encoding="utf-8"))
            if existing_hash == content_hash:
                item["status"] = "queued"
                item["destination"] = str(existing_path)
                skipped.append(item)
            elif not force or existing_path != destination:
                item["status"] = "conflict"
                item["existing_path"] = str(existing_path)
                conflicts.append(item)
            elif not dry_run:
                queue_dir.mkdir(parents=True, exist_ok=True)
                _write_text_atomic(destination, body)
                item["status"] = "queued"
                staged.append(item)
            else:
                item["status"] = "would_replace"
                staged.append(item)
        elif not dry_run:
            queue_dir.mkdir(parents=True, exist_ok=True)
            _write_text_atomic(destination, body)
            item["status"] = "queued"
            staged.append(item)
        else:
            item["status"] = "would_stage"
            staged.append(item)

        record["chapters"][str(chapter_id)] = {
            **record["chapters"].get(str(chapter_id), {}),
            **item,
            "updated_at": now_iso(),
        }

    if not dry_run:
        save_manifest(manifest)

    return {
        "project": str(project_root),
        "book": display_name,
        "queue_dir": str(queue_dir),
        "staged": staged,
        "skipped": skipped,
        "conflicts": conflicts,
        "invalid": invalid,
        "staged_count": len(staged),
        "queued_count": len(queued_chapters(queue_dir)),
    }


def _write_text_atomic(path: Path, content: str):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def harden_secret_file(path: Path) -> None:
    """把含密钥/登录态的文件 ACL 收紧为“仅当前用户可读写”（Windows）。

    Windows 默认继承的 Users/Authenticated Users 权限会让同机其他账户读取
    API Key 与番茄 Cookie。失败时只记录日志，不阻断主流程（例如非 NTFS 盘）。
    """
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return
    import getpass
    import subprocess
    try:
        user = getpass.getuser()
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(F)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _refresh_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """根据待发/归档目录计算桥接状态（纯内存，不落盘）。"""
    summary: Dict[str, Any] = {"books": [], "queued": 0, "published": 0, "missing": 0, "archive_unverified": 0, "unconfirmed": 0}
    for safe_book, record in manifest.get("books", {}).items():
        if not isinstance(record, dict):
            continue
        queue = queued_chapters(QUEUE_ROOT / safe_book)
        uploaded = archived_chapters(UPLOADED_ROOT / safe_book)
        chapters = record.get("chapters", {})
        if not isinstance(chapters, dict):
            chapters = {}
            record["chapters"] = chapters
        for raw_id, item in chapters.items():
            if not isinstance(item, dict):
                continue
            try:
                chapter_id = int(raw_id)
            except ValueError:
                continue
            if chapter_id in uploaded:
                receipt = valid_receipt(uploaded[chapter_id], record.get("display_name"), chapter_id, record.get("account"))
                item["status"] = "published" if receipt else "archive_unverified"
                item["uploaded_path"] = str(uploaded[chapter_id])
                item["published_seen_at"] = item.get("published_seen_at") or now_iso()
                summary[item["status"]] += 1
            elif chapter_id in queue:
                item["status"] = "queued"
                attempt_path = journal_path(queue[chapter_id])
                if attempt_path.exists():
                    attempt = read_json_strict(attempt_path)
                    if attempt.get("state") in {"submitting", "unconfirmed", "platform_confirmed"}:
                        item["status"] = "unconfirmed"
                        summary["unconfirmed"] += 1
                item["destination"] = str(queue[chapter_id])
                summary["queued"] += 1
            elif Path(str(item.get("source", ""))).exists():
                item["status"] = "source_only"
            else:
                item["status"] = "missing"
                summary["missing"] += 1

        summary["books"].append(
            {
                "book": record.get("display_name", safe_book),
                "folder": safe_book,
                "queued": len(queue),
                "published": sum(valid_receipt(p, record.get("display_name"), n, record.get("account")) is not None for n, p in uploaded.items()),
                "archive_unverified": sum(valid_receipt(p, record.get("display_name"), n, record.get("account")) is None for n, p in uploaded.items()),
            }
        )
    return summary


def manifest_snapshot() -> Dict[str, Any]:
    """只读刷新队列状态：供 GET /api/overview 使用，绝不写 manifest。

    旧实现每个 8 秒轮询都会在非阻塞队列锁下写 manifest；发布/入队持锁时
    整个仪表盘会返回 400（resource_busy），且多设备轮询会互相争锁。
    """
    manifest = load_manifest()
    return _refresh_manifest(manifest)


@_queue_serialized
def sync_manifest() -> Dict[str, Any]:
    """根据待发和归档目录刷新桥接状态，不触碰源项目。"""

    manifest = load_manifest()
    summary = _refresh_manifest(manifest)
    save_manifest(manifest)
    return summary


def find_queue_book(book: str) -> Tuple[int, str, Path]:
    """返回 standalone publish.py 所需的 1-based 书籍序号。"""

    candidates: List[Tuple[str, Path]] = []
    if QUEUE_ROOT.is_dir():
        for path in sorted(QUEUE_ROOT.iterdir(), key=lambda item: item.name.casefold()):
            if path.is_dir() and list(path.glob("*.txt")):
                candidates.append((path.name, path))
    wanted = book.strip()
    safe_wanted = safe_dir_name(wanted)
    for index, (name, path) in enumerate(candidates, 1):
        if wanted == name or wanted == safe_wanted:
            return index, name, path
        record = load_manifest().get("books", {}).get(name, {})
        if isinstance(record, dict) and wanted == str(record.get("display_name", "")):
            return index, name, path
    choices = ", ".join(name for name, _ in candidates) or "（没有待发书籍）"
    raise ValueError(f"找不到待发书籍“{book}”。当前队列：{choices}")


@_queue_serialized
def validate_queue_origin(book: str, project: Optional[Path] = None,
                          account: Optional[str] = None, reconcile_only: bool = False,
                          chapter_filter: Optional[Set[int]] = None) -> Dict[str, Any]:
    """Read-only precondition; raises on origin/review/account/hash conflicts.

    Return a credential-free plan. A missing account binding may be claimed by
    run_publish; a different existing binding is never automatically changed.
    Review receipts are the writer's exact source-byte receipts, not a flag in
    the queue manifest. Validate again immediately before invoking publication.
    """
    from fanqie_auto_publish.publication_safety import qualification_contract_matches
    _, folder, queue = find_queue_book(book)
    record = load_manifest().get("books", {}).get(folder)
    if not isinstance(record, dict) or not record.get("project_root"):
        raise ValueError("待发队列缺少项目来源绑定")
    display = record.get("display_name")
    if book not in {folder, display}:
        raise ValueError("目标平台书名与队列不匹配")
    origin = Path(record["project_root"]).resolve()
    if project is not None and origin != Path(project).resolve():
        raise ValueError("待发队列来源项目与请求不匹配")
    identity = str(account).strip() if account else "legacy-root"
    if record.get("account") and record["account"] != identity:
        raise ValueError("待发队列已绑定其他账号")
    state = account_state_path(account) if account else FANQIE_ROOT / "state.json"
    if not state.is_file() or state.is_symlink():
        raise ValueError("发布账号缺少安全登录状态文件")
    receipt_path = origin / ".webnovel" / "writer_receipts.json"
    receipts = read_json_strict(receipt_path) if receipt_path.exists() else {}
    if not isinstance(receipts, dict):
        raise ValueError("审查回执损坏")
    sources = list(iter_source_chapters(origin))
    contract_hash = creative_contract_hash(origin)
    source_map = {}
    for source, number, title, markdown in sources:
        if number in source_map:
            raise ValueError("源项目同章号不唯一")
        source_map[number] = (source, title, markdown)
    chapters = []
    for number, queued in sorted(queued_chapters(queue).items()):
        if chapter_filter is not None and number not in chapter_filter:
            # 只读核对只针对“已经点过提交”的章节；未尝试的章节不要求 journal，
            # 也不进入 reconcile 计划（否则一次批次中断后永远无法核对）。
            continue
        item = record.get("chapters", {}).get(str(number), {})
        if number not in source_map or not isinstance(item, dict):
            raise ValueError("待发章节缺少唯一来源")
        source, title, markdown = source_map[number]
        receipt = receipts.get(str(number), {})
        review = receipt.get("review", {}) if isinstance(receipt, dict) else {}
        if not (review_eligible(review,body_digest(markdown),origin,number) and
                receipt.get("destination") == str(source.resolve()) and
                receipt.get("sha256") == digest_file(source) and
                qualification_contract_matches(origin,number,receipt,contract_hash)):
            raise ValueError("待发内容未通过与源文件及当前创作约定绑定的审查，请重新审查")
        body = markdown_to_plaintext(markdown, number)
        from integration.length_policy import require
        require(origin, markdown, number)
        if (Path(item.get("source", "")).resolve() != source.resolve() or
            Path(item.get("destination", "")).resolve() != queued.resolve() or
            item.get("title") != title or item.get("sha256") != sha256_text(body) or
            digest_file(queued) != sha256_text(body)):
            raise ValueError("待发内容或标题与已审查来源不一致")
        if journal_path(queued).exists():
            attempt = read_json_strict(journal_path(queued))
            state = attempt.get("state") if isinstance(attempt, dict) else None
            from fanqie_auto_publish.publication_safety import requires_reconciliation
            needs_check = requires_reconciliation(attempt)
            if reconcile_only and state in {"preparing", "blocked_before_submit"} and not needs_check:
                # 未写入 submitting 的 journal 证明提交按钮从未点击，只读核对
                # 没有可核对的对象：跳过而不是报“已有发布尝试”，否则会与
                # serial_delivery 的“确认未提交→重试”路径互相锁死。
                continue
            states={'submitting','unconfirmed','platform_confirmed','preparing','blocked_before_submit'} if reconcile_only else {'preparing','blocked_before_submit'}
            if not isinstance(attempt, dict) or state not in states or not reconcile_only and needs_check:
                raise ValueError("已有发布尝试须自动只读核验，禁止重复提交")
            if attempt.get("account") != identity:
                raise ValueError("章节发布尝试属于其他账号")
            if reconcile_only and (attempt.get('book')!=display or attempt.get('chapter_id')!=number
                or attempt.get('file_sha256')!=digest_file(queued)):
                raise ValueError('只读核验的提交身份或正文不匹配')
        elif reconcile_only:
            # 队列章节没有任何 journal = 从未尝试提交，不是待核对对象。
            continue
        chapters.append({"chapter_id": number, "filename": queued.name, "source": str(source.resolve()),
                         "source_sha256": digest_file(source), "file_sha256": digest_file(queued),"review_status":review.get("review_decision")})
    if not chapters:
        raise ValueError("没有需要只读核对的提交记录" if reconcile_only else "没有待发章节")
    binding=read_json(origin/".webnovel"/"platform_binding.json",{})
    allow_typo=(isinstance(binding,dict) and binding.get("book")==display and
                binding.get("account")==identity and binding.get("allow_typo_advisory") is True)
    return {"schema": 1, "book": display, "queue_book": folder, "project": str(origin),
            "account": identity, "chapters": chapters,"allow_typo_advisory":allow_typo,
            'reconcile_only':reconcile_only}


def _report_key(book: str, account: Optional[str]) -> str:
    return hashlib.sha256((book + "\0" + (account or "legacy-root")).encode("utf-8")).hexdigest()


def latest_publish_report(book: str, account: Optional[str] = None) -> Dict[str, Any]:
    """Public machine interface: {report_path, verified_success, ...report}.

    verified_success requires exit 0 plus every confirmed receipt and archive;
    never infer it from the exit code alone. Missing/corrupt evidence raises.
    """
    pointer = FANQIE_ROOT / ".publication" / "reports" / (_report_key(book, account) + ".latest.json")
    index = read_json_strict(pointer)
    report = read_json_strict(Path(index["report_path"]))
    if report.get("requested_book") != book or report.get("account") != (account or "legacy-root"):
        raise ValueError("发布报告目标不匹配")
    chapters = report.get("chapters", [])
    verified = report.get("exit_code") == 0 and bool(chapters) and report.get("confirmed_count") == len(chapters)
    for item in chapters:
        path = Path(item.get("archive_path", ""))
        verified = verified and item.get("state") == "platform_confirmed" and item.get("archived") is True and path.is_file()
        if verified:
            verified = valid_receipt(path, report.get("book"), item.get("chapter_id"), report.get("account")) is not None
    return {**report, "report_path": index["report_path"], "verified_success": bool(verified)}


def reconcile_uncertain(book: str, project: Optional[Path] = None,
                        account: Optional[str] = None) -> Dict[str, Any]:
    """只读核对“已点提交但结果不明”的章节；绝不重新提交。

    batch 模式没有 serial 的自动恢复路径：发布中断后 stage/validate 会因
    journal 状态永久抛错。这里给出一条显式、可审计的恢复命令：
    python integration/bridge.py reconcile --book ... --account ...
    """
    try:
        _, folder, queue = find_queue_book(book)
    except (ValueError, OSError) as exc:
        return {"reconciled": False, "reason": f"队列不可用: {exc}"}
    pending = set()
    for number, path in queued_chapters(queue).items():
        journal = journal_path(path)
        if not journal.exists():
            continue
        try:
            attempt = read_json_strict(journal)
        except ValueError:
            continue
        if not isinstance(attempt, dict):
            continue
        from fanqie_auto_publish.publication_safety import requires_reconciliation
        if requires_reconciliation(attempt):
            try:
                pending.add(int(number))
            except (TypeError, ValueError):
                continue
    if not pending:
        return {"reconciled": False, "reason": "没有需要只读核对的提交记录", "queue_book": folder}
    code = run_publish(book, count=None, volume=None, account=account, project=project,
                       reconcile_only=True, reconcile_chapters=pending)
    try:
        report = latest_publish_report(book, account)
        verified = bool(report.get("verified_success"))
    except (ValueError, OSError, KeyError, TypeError):
        verified = False
    return {"reconciled": code == 0, "exit_code": code,
            "chapters": sorted(pending), "queue_book": folder,
            "verified_success": verified,
            "hint": "只读核对不会重发；确认已发布后可从运行记录重新执行原批次"}


def _run_publish_process(command: List[str], timeout: float):
    """运行发布子进程并施加整体超时。

    旧实现 subprocess.run 没有 timeout：浏览器卡住会永久占住
    scheduler-execution 锁，整个日更管线冻结且 watchdog 无法识别。
    超时被上层视为“结果不明”，不会自动重发。
    """
    return subprocess.run(
        command,
        cwd=str(FANQIE_ROOT),
        text=True,
        check=False,
        env=child_environment(),
        timeout=timeout,
    )


def run_publish(
    book: str,
    count: Optional[int] = None,
    volume: Optional[int] = None,
    account: Optional[str] = None,
    project: Optional[Path] = None,
    reconcile_only: bool = False,
    reconcile_chapters: Optional[Set[int]] = None,
    invocation_id: Optional[str] = None,
) -> int:
    """Compatible int exit code; use latest_publish_report for success evidence.

    Explicit project/account/book/hash plan replaces positional menu selection
    and temporary state exchange. The child owns queue/account OS locks.
    """
    reports = FANQIE_ROOT / ".publication" / "reports"
    report_path = reports / (uuid.uuid4().hex + ".json")
    pointer = reports / (_report_key(book, account) + ".latest.json")
    identity = account or "legacy-root"
    report = {"schema": 1, "requested_book": book, "account": identity,
              "exit_code": 2, "confirmed_count": 0, "chapters": [], "started_at": now_iso(),
              'publisher_started':False,'invocation_id':invocation_id}
    publisher_started=False
    try:
        token = hashlib.sha256(safe_dir_name(book).casefold().encode("utf-8")).hexdigest()
        with runtime_lock("fanqie-publish"), file_lock(FANQIE_ROOT / ".publication" / f"book-{token}.lock"):
            atomic_json(report_path, report)
            atomic_json(pointer, {"report_path": str(report_path)})
            if count is not None and count <= 0 or volume is not None and volume <= 0:
                raise ValueError("发布数量和分卷必须大于零")
            if not (FANQIE_ROOT / "publish.py").is_file():
                raise ValueError("发布脚本不存在")
            with queue_lock(FANQIE_ROOT):
                plan = validate_queue_origin(
                    book, project, account,
                    reconcile_only=reconcile_only,
                    chapter_filter=reconcile_chapters if reconcile_only else None,
                )
                if plan.get("chapters"):
                    plan["chapters"] = plan["chapters"][:count] if count is not None else plan["chapters"]
                elif not reconcile_only:
                    raise ValueError("没有待发章节")
                manifest = load_manifest()
                manifest["books"][plan["queue_book"]]["account"] = identity
                save_manifest(manifest)
                plan_path = reports / (report_path.stem + ".plan.json")
                atomic_json(plan_path, plan)
            report['plan_chapters']=[{k:c[k] for k in ('chapter_id','file_sha256')} for c in plan['chapters']]
            atomic_json(report_path,report)
            from integration import model_roles
            from integration import costs
            with costs.scope(project=plan.get("project"),chapter=plan['chapters'][0]['chapter_id'] if len(plan['chapters'])==1 else 0):
                gate={'mode':'read_only_reconciliation'} if reconcile_only else model_roles.publication_gate(plan)
            report["executor_stage"]=gate
            atomic_json(report_path,report)
            state = account_state_path(account) if account else FANQIE_ROOT / "state.json"
            command = [sys.executable, '-X', 'utf8', str(FANQIE_ROOT / "publish.py"), "--book", plan["book"],
                       "--queue-book", plan["queue_book"], "--state-file", str(state.resolve()),
                       "--account", identity, "--report", str(report_path), "--plan", str(plan_path)]
            if count is not None:
                command.extend(["--count", str(count)])
            if volume is not None:
                command.extend(["--volume", str(volume)])
            if reconcile_only:command.append('--reconcile-only')
            try:
                publish_timeout=float(os.getenv('NOVEL_HELPER_PUBLISH_TIMEOUT','1800'))
            except ValueError:
                publish_timeout=1800.0
            try:
                publisher_started=True
                report['publisher_started']=True
                atomic_json(report_path,report)
                completed = _run_publish_process(command, publish_timeout)
            except subprocess.TimeoutExpired:
                # 超时只代表“结果不明”，绝不能当作失败后自动重发。
                child = read_json_strict(report_path)
                child.update(requested_book=book, account=identity, subprocess_exit_code=2,
                             exit_code=2, reason='publish_subprocess_timeout',
                             executor_stage=gate, finished_at=now_iso(),invocation_id=invocation_id)
                atomic_json(report_path, child)
                sync_manifest()
                print(f"发布子进程超过 {publish_timeout:.0f}s 未结束，已终止并保留未确认记录；报告：{report_path}", file=sys.stderr)
                return 2
            child = read_json_strict(report_path)
            child.update(requested_book=book, account=identity, subprocess_exit_code=int(completed.returncode),executor_stage=gate,invocation_id=invocation_id)
            if [item.get("chapter_id") for item in child.get("chapters", [])] != [item["chapter_id"] for item in plan["chapters"]]:
                child["exit_code"] = 2
                child["reason"] = "publisher_plan_report_mismatch"
            if completed.returncode != 0:
                child["exit_code"] = 2
            atomic_json(report_path, child)
            sync_manifest()
            evidence = latest_publish_report(book, account)
            if not evidence["verified_success"]:
                child["exit_code"] = 2
                child.setdefault("reason", "publication_evidence_incomplete")
                atomic_json(report_path, child)
                return 2
            return 0
    except Exception as exc:
        # No exception/page/credential payloads in machine reports.
        if report_path.exists():
            saved = read_json_strict(report_path)
            if isinstance(saved, dict):
                report = saved
        report.update(exit_code=2, requested_book=book, account=identity,
                      reason=str(exc) if isinstance(exc, PublicationBlocked) else "bridge_precondition_or_execution_failed", finished_at=now_iso())
        from integration.failure_info import details
        report.update(publisher_started=publisher_started,invocation_id=invocation_id,failure=details(exc))
        if isinstance(exc, ValueError):
            from integration import model_roles
            detail=str(exc)
            for secret in model_roles.secrets(model_roles.load_config()):
                detail=detail.replace(secret,"[redacted]")
            report["detail"]=detail[:1200]
        atomic_json(report_path, report)
        # A busy invocation must not replace an active invocation's pointer.
        if not isinstance(exc, PublicationBlocked) or str(exc) != "resource_busy":
            atomic_json(pointer, {"report_path": str(report_path)})
        print(f"发布已停止；报告：{report_path}", file=sys.stderr)
        return 2


def child_environment() -> Dict[str, str]:
    """为子进程自动指向组合目录内的 Playwright 浏览器。"""

    environment = os.environ.copy()
    browser_dir = COMBINED_ROOT / "playwright-browsers"
    if not environment.get("PLAYWRIGHT_BROWSERS_PATH") and browser_dir.is_dir():
        environment["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_dir)
    # 组合层的日更发布是无人值守调用；同时如实声明章节由 AI 生成。
    environment.setdefault("NOVEL_HELPER_UNATTENDED", "1")
    environment.setdefault("NOVEL_HELPER_AI_USED", "1")
    return environment


def run_login(account: Optional[str] = None) -> int:
    login_script = FANQIE_ROOT / "login.py"
    if not login_script.is_file():
        raise FileNotFoundError(f"找不到登录脚本：{login_script}")
    target_dir = FANQIE_ROOT
    if account:
        target_dir = account_dir(account)
        target_dir.mkdir(parents=True, exist_ok=True)
    with account_lock(target_dir / "state.json"):
        completed = subprocess.run(
            [sys.executable, '-X', 'utf8', str(login_script)], cwd=str(target_dir),
            check=False, env=child_environment(),
        )
    if account and completed.returncode == 0:
        write_json_atomic(
            target_dir / "profile.json",
            {
                "name": str(account).strip(),
                "folder": target_dir.name,
                "updated_at": now_iso(),
            },
        )
    return int(completed.returncode)


def print_status() -> int:
    summary = sync_manifest()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _stage_args(args: argparse.Namespace) -> Dict[str, Any]:
    selected = set(args.chapter or []) or None
    return stage_project(
        Path(args.project),
        book_name=args.book_name,
        selected_ids=selected,
        start=args.start,
        end=args.end,
        force=args.force,
        include_published=args.include_published,
        dry_run=args.dry_run,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小说助手：写作项目 → 番茄增强发布队列")
    sub = parser.add_subparsers(dest="command", required=True)

    stage = sub.add_parser("stage", help="把一个 webnovel 项目转换并排入发布队列")
    stage.add_argument("--project", required=True, help="webnovel 项目目录")
    stage.add_argument("--book-name", help="覆盖番茄书名；默认读取 .webnovel/state.json")
    stage.add_argument("--chapter", action="append", type=int, help="只同步指定章节，可重复")
    stage.add_argument("--start", type=int, help="起始章节号")
    stage.add_argument("--end", type=int, help="结束章节号")
    stage.add_argument("--force", action="store_true", help="覆盖同名且内容不同的待发文件")
    stage.add_argument("--include-published", action="store_true", help="允许重新排队已归档章节")
    stage.add_argument("--dry-run", action="store_true", help="只预览，不写入队列或 manifest")

    publish = sub.add_parser("publish", help="调用 fanqie_auto_publish 发布队列")
    publish.add_argument("--book", required=True, help="书名或 chapters 下的目录名")
    publish.add_argument("--project", help="先同步此 webnovel 项目，再发布")
    publish.add_argument("--book-name", help="同步时覆盖番茄书名")
    publish.add_argument("--count", type=int, help="本次最多发布多少章；默认全部")
    publish.add_argument("--volume", type=int, help="本次切换到第几卷；默认不切换")
    publish.add_argument("--account", help="使用 accounts/ 下的指定账号；省略时使用旧版根 state.json")
    publish.add_argument("--force", action="store_true", help="同步时覆盖冲突的待发文件")

    login = sub.add_parser("login", help="使用组合目录内的 Playwright 浏览器扫码登录番茄")
    login.add_argument("--account", help="将登录状态保存到 accounts/ 下的独立账号目录")
    reconcile = sub.add_parser("reconcile", help="只读核对提交后结果不明的章节（不重新提交）")
    reconcile.add_argument("--book", required=True, help="书名或 chapters 下的目录名")
    reconcile.add_argument("--project", help="webnovel 项目目录（用于校验队列来源）")
    reconcile.add_argument("--account", help="使用 accounts/ 下的指定账号")
    sub.add_parser("accounts", help="列出已登记账号（不显示 Cookie）")
    sub.add_parser("sync", help="扫描 uploaded/ 和 chapters/，刷新 manifest")
    sub.add_parser("status", help="显示当前组合发布队列状态")

    watch = sub.add_parser("watch", help="定期同步项目；可选自动调用发布器")
    watch.add_argument("--project", required=True, help="webnovel 项目目录")
    watch.add_argument("--book-name", help="覆盖番茄书名")
    watch.add_argument("--interval", type=int, default=60, help="轮询间隔秒数，默认 60")
    watch.add_argument("--auto-publish", action="store_true", help="发现队列后自动发布全部待发章节")
    watch.add_argument("--count", type=int, help="自动发布每轮最多多少章")
    watch.add_argument("--volume", type=int, help="自动发布时切换到第几卷")
    watch.add_argument("--account", help="自动发布使用的独立账号")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    os.environ.setdefault("NOVEL_HELPER_COST_DB",str(COMBINED_ROOT / "integration_data" / "costs.sqlite3"))
    args = build_parser().parse_args(argv)
    try:
        if args.command == "stage":
            result = _stage_args(args)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["conflicts"] or result["invalid"] else 0
        if args.command == "publish":
            if args.project:
                result = stage_project(
                    Path(args.project),
                    book_name=args.book_name,
                    force=args.force,
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                if result["conflicts"] or result["invalid"]:
                    return 1
            return run_publish(
                args.book,
                count=args.count,
                volume=args.volume,
                account=args.account,
                project=Path(args.project) if args.project else None,
            )
        if args.command == "login":
            return run_login(args.account)
        if args.command == "reconcile":
            result = reconcile_uncertain(
                args.book,
                project=Path(args.project) if args.project else None,
                account=args.account,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("reconciled") else 1
        if args.command == "accounts":
            print(json.dumps(list_accounts(), ensure_ascii=False, indent=2))
            return 0
        if args.command in {"sync", "status"}:
            return print_status()
        if args.command == "watch":
            if args.interval < 5:
                raise ValueError("--interval 不能小于 5 秒")
            while True:
                result = stage_project(Path(args.project), book_name=args.book_name)
                print(f"[{now_iso()}] 同步完成：新增 {result['staged_count']}，队列 {result['queued_count']}")
                if args.auto_publish and result["queued_count"]:
                    book = result["book"]
                    code = run_publish(
                        book,
                        count=args.count,
                        volume=args.volume,
                        account=args.account,
                    )
                    if code != 0:
                        print(f"发布器返回退出码 {code}，轮询停止，请先核验发布报告。")
                        return code
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n已停止桥接轮询。")
        return 130
    except Exception as exc:
        print(f"[小说助手] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
