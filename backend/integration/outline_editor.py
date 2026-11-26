"""多文件大纲、AI 规划双轨同步与独立「设定与资料」资料夹。

Authority boundary (plan ``01`` §3.3):

* chapter outlines: the ``大纲/AI规划-*.md`` that owns the chapter range;
* book-level fields: ``.webnovel/story_plan_meta.json`` (monotonic
  ``meta_revision``);
* ``.webnovel/story_plan.json``: a rebuildable derived cache only.

Writes are short-locked (``locks/outline.lock``), backed up first, and commit
the authoritative Markdown before refreshing the derived index.  Removed
chapters are represented by explicit tombstones so a stale cache can never
resurrect them.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fanqie_auto_publish import publication_safety as safety

MAX_FILE_BYTES = 500 * 1024
MAX_LORE_BYTES = 2 * 1024 * 1024
_WINDOWS_BAD = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}
_PLAN_HEADING = re.compile(r"^##\s*第\s*(\d+)\s*章\s*(.*)$", re.MULTILINE)
_COMMENT = re.compile(r"^\s*<!--\s*novel-plan:(.*?)-->\s*$")


class OutlineError(RuntimeError):
    def __init__(self, code: str, *, status: int = 400, detail: Optional[Dict[str, Any]] = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail or {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _book(project) -> Path:
    return Path(project)


def _outline_dir(project) -> Path:
    return _book(project) / "大纲"


def _lore_dir(project) -> Path:
    return _book(project) / "设定"


def _meta_path(project) -> Path:
    return _book(project) / ".webnovel" / "story_plan_meta.json"


def _story_plan_path(project) -> Path:
    return _book(project) / ".webnovel" / "story_plan.json"


def _backup_dir(project) -> Path:
    return _book(project) / ".webnovel" / "outline-backups"


@contextmanager
def _lock(project):
    folder = _book(project) / ".webnovel" / "locks"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with safety.file_lock(folder / "outline.lock"):
            yield
    except Exception as exc:
        if exc.__class__.__name__ == "PublicationBlocked":
            raise OutlineError("outline_busy", status=409) from None
        raise


def _validate_filename(filename: str) -> str:
    name = unicodedata.normalize("NFC", str(filename or "")).strip()
    if not name or name.endswith((" ", ".")) or _WINDOWS_BAD.search(name):
        raise OutlineError("invalid_filename")
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise OutlineError("invalid_filename")
    if not name.lower().endswith(".md") or name.lower().count(".md") != 1:
        raise OutlineError("invalid_filename")
    stem = name[:-3]
    if not stem or stem.endswith((" ", ".")) or stem.split(".")[0].upper() in _RESERVED:
        raise OutlineError("invalid_filename")
    if len(name) > 160:
        raise OutlineError("filename_too_long")
    return name


def _safe_outline_path(project, filename: str) -> Path:
    name = _validate_filename(filename)
    base = _outline_dir(project).resolve()
    path = (base / name).resolve()
    if path.parent != base:
        raise OutlineError("path_escape")
    if path.exists() and path.is_symlink():
        raise OutlineError("path_escape")
    return path


def _decode(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    return text[1:] if text.startswith("\ufeff") else text


def _read_text(path: Path) -> str:
    return _decode(path.read_bytes())


def _strip_plan_comment(text: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Return visible Markdown and the embedded JSON plan (if any)."""
    lines = text.split("\n")
    meta = None
    if lines and lines[0].lstrip().startswith("<!-- novel-plan:"):
        match = _COMMENT.match(lines[0])
        if match:
            raw = match.group(1).strip()
            try:
                value = json.loads(raw)
                if isinstance(value, dict):
                    meta = value
            except ValueError:
                meta = None
        return "\n".join(lines[1:]).lstrip("\n"), meta
    return text, None


def _parse_visible(text: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    matches = list(_PLAN_HEADING.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip("\n")
        rows.append({"id": int(match.group(1)), "title": match.group(2).strip(),
                     "outline": body})
    return rows


def _chapter_rev(meta: Optional[Dict[str, Any]], chapter: int) -> int:
    if not isinstance(meta, dict):
        return 0
    for item in meta.get("chapters") or []:
        if isinstance(item, dict) and str(item.get("id")) == str(chapter):
            try:
                return int(item.get("chapter_rev") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _tombstones(meta: Optional[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    result = {}
    if isinstance(meta, dict):
        for item in meta.get("chapters") or []:
            if isinstance(item, dict) and item.get("deleted"):
                try:
                    result[int(item["id"])] = item
                except (TypeError, ValueError, KeyError):
                    continue
    return result


def load_meta(project) -> Dict[str, Any]:
    """Load the single authoritative book-level metadata, migrating once."""
    path = _meta_path(project)
    if path.is_file():
        try:
            data = safety.read_json_strict(path)
        except Exception as exc:
            raise OutlineError("story_plan_meta_corrupt") from exc
        if not isinstance(data, dict):
            raise OutlineError("story_plan_meta_corrupt")
        data.setdefault("meta_revision", 0)
        data.setdefault("master_outline", "")
        data.setdefault("volumes", "")
        data.setdefault("character_arcs", "")
        data.setdefault("foreshadowing", "")
        return data
    # 兼容 v0.7.5：仅当 meta 尚不存在时，从旧 story_plan.json 一次性回填。
    legacy = {}
    story = _story_plan_path(project)
    if story.is_file():
        try:
            value = safety.read_json_strict(story)
            if isinstance(value, dict):
                legacy = value
        except (OSError, ValueError):
            legacy = {}
    meta = {
        "schema_version": 1,
        "meta_revision": int(legacy.get("meta_revision") or 0) or 1,
        "master_outline": str(legacy.get("master_outline") or ""),
        "volumes": str(legacy.get("volumes") or ""),
        "character_arcs": str(legacy.get("character_arcs") or ""),
        "foreshadowing": str(legacy.get("foreshadowing") or ""),
        "updated_at": _now(),
    }
    safety.atomic_json(path, meta)
    return meta


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safety.atomic_json(path, data)


def _sync_story_plan(project, meta: Dict[str, Any], chapters: Dict[str, Dict[str, Any]],
                     conflicts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    story = {
        "schema_version": 1,
        "plan_revision": int(meta.get("plan_revision") or meta.get("meta_revision") or 0),
        "meta_revision": int(meta.get("meta_revision") or 0),
        "master_outline": meta.get("master_outline", ""),
        "volumes": meta.get("volumes", ""),
        "character_arcs": meta.get("character_arcs", ""),
        "foreshadowing": meta.get("foreshadowing", ""),
        "chapters": chapters,
        "conflicts": conflicts or [],
        "updated_at": _now(),
    }
    _write_json(_story_plan_path(project), story)
    return story


def _backup(project, path: Path) -> Optional[Path]:
    if not path.is_file():
        return None
    folder = _backup_dir(project)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    target = folder / f"{path.stem}-{stamp}{path.suffix}"
    shutil.copy2(path, target)
    keep = sorted(folder.glob(f"{path.stem}-*{path.suffix}"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in keep[30:]:
        old.unlink(missing_ok=True)
    return target


def _plan_files(project) -> List[Path]:
    folder = _outline_dir(project)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("AI规划-*.md") if p.is_file() and not p.is_symlink())


def _all_files(project) -> List[Path]:
    folder = _outline_dir(project)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.md") if p.is_file() and not p.is_symlink())


def files(project) -> Dict[str, Any]:
    meta = load_meta(project)
    rows = []
    for path in _all_files(project):
        raw = path.read_bytes()
        text = _decode(raw)
        visible, plan = _strip_plan_comment(text)
        chapters = _parse_visible(visible)
        numbers = [item["id"] for item in chapters]
        rows.append({
            "name": path.name,
            "kind": "ai_plan" if path.name.startswith("AI规划-") else "manual",
            "revision": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            "chapter_range": [min(numbers), max(numbers)] if numbers else [],
            "chapter_revs": {str(item["id"]): _chapter_rev(plan, item["id"]) for item in chapters},
            "editable": True,
            "tombstones": sorted(_tombstones(plan).keys()),
        })
    return {"files": rows, "meta": meta, "conflicts": conflicts(project)}


def read_file(project, filename: str) -> Dict[str, Any]:
    path = _safe_outline_path(project, filename)
    if not path.is_file():
        raise OutlineError("outline_file_missing", status=404)
    raw = path.read_bytes()
    text = _decode(raw)
    visible, plan = _strip_plan_comment(text)
    return {"name": path.name, "content": visible, "raw_content": text,
            "revision": hashlib.sha256(raw).hexdigest(),
            "chapter_revs": {str(c["id"]): _chapter_rev(plan, c["id"]) for c in _parse_visible(visible)},
            "tombstones": sorted(_tombstones(plan).keys()),
            "kind": "ai_plan" if path.name.startswith("AI规划-") else "manual"}


def _revision_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _merge_chapters(meta: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Rebuild the derived chapter index from every authoritative AI plan."""
    chapters: Dict[str, Dict[str, Any]] = {}
    conflicts: List[Dict[str, Any]] = []
    seen_in: Dict[str, str] = {}
    tombstones: Dict[int, int] = {}
    for path in _plan_files(_book_path(meta)):
        text = _read_text(path)
        visible, plan = _strip_plan_comment(text)
        visible_rows = {int(row["id"]): row for row in _parse_visible(visible)}
        embedded_rows = {}
        if isinstance(plan, dict):
            for item in plan.get("chapters") or []:
                if isinstance(item, dict) and "id" in item:
                    try:
                        embedded_rows[int(item["id"])] = item
                    except (TypeError, ValueError):
                        continue
        for number, row in visible_rows.items():
            key = str(number)
            rev = max(_chapter_rev(plan, number), int((embedded_rows.get(number) or {}).get("chapter_rev") or 0))
            entry = {
                "id": number, "title": row["title"], "outline": row["outline"],
                "key_scene": bool((embedded_rows.get(number) or {}).get("key_scene")),
                "chapter_rev": rev, "outline_sha256": _sha(row["outline"]),
                "source_file": path.name,
            }
            if key in chapters:
                previous = chapters[key]
                if previous.get("outline_sha256") != entry["outline_sha256"]:
                    conflicts.append({"kind": "duplicate_chapter", "chapter": number,
                                      "files": [seen_in.get(key), path.name]})
                    if rev > int(previous.get("chapter_rev") or 0):
                        chapters[key] = entry
                        seen_in[key] = path.name
                continue
            chapters[key] = entry
            seen_in[key] = path.name
        for number, item in embedded_rows.items():
            if item.get("deleted"):
                try:
                    tomb_rev = int(item.get("chapter_rev") or 0)
                except (TypeError, ValueError):
                    tomb_rev = 0
                tombstones[int(number)] = max(tombstones.get(int(number), 0), tomb_rev)
    # 墓碑统一在全部可见行之后结算：陈旧副本不能复活已删除章节。
    for number, tomb_rev in tombstones.items():
        current = chapters.get(str(number))
        if current is None or tomb_rev >= int(current.get("chapter_rev") or 0):
            chapters.pop(str(number), None)
    # 外部 Markdown 编辑但未更新首行 JSON：可见正文优先，并显性报冲突
    for path in _plan_files(_book_path(meta)):
        text = _read_text(path)
        visible, plan = _strip_plan_comment(text)
        if not isinstance(plan, dict):
            conflicts.append({"kind": "plan_comment_missing", "file": path.name})
            continue
        for row in _parse_visible(visible):
            stored = next((x for x in plan.get("chapters") or []
                           if isinstance(x, dict) and str(x.get("id")) == str(row["id"])), None)
            if stored is not None and _sha(str(stored.get("outline") or "")) != _sha(row["outline"]):
                conflicts.append({"kind": "visible_text_edited", "file": path.name,
                                  "chapter": row["id"]})
    return chapters, conflicts


def _book_path(meta: Dict[str, Any]) -> Path:
    # The project path is stored non-persistently by callers via the private key.
    return Path(meta["_project"])


def conflicts(project) -> List[Dict[str, Any]]:
    meta = load_meta(project)
    meta["_project"] = str(project)
    _, found = _merge_chapters(meta)
    folder = _outline_dir(project)
    indexed = set()
    try:
        story = safety.read_json_strict(_story_plan_path(project)) if _story_plan_path(project).is_file() else {}
    except (OSError, ValueError):
        story = {}
    if isinstance(story, dict):
        indexed = set((story.get("chapters") or {}).keys())
    present = set()
    for path in _plan_files(project):
        visible, _ = _strip_plan_comment(_read_text(path))
        present |= {str(row["id"]) for row in _parse_visible(visible)}
    for missing in sorted(indexed - present, key=lambda x: int(x) if str(x).isdigit() else 0):
        found.append({"kind": "outline_file_missing_chapter", "chapter": missing})
    if folder.is_dir():
        known = {p.name for p in _all_files(project)}
        for path in _plan_files(project):
            if path.name not in known:
                found.append({"kind": "outline_file_missing", "file": path.name})
    # 人工总纲与 meta 显著分歧（仅提示，不自动覆盖）
    manual_total = folder / "总纲.md" if folder.is_dir() else None
    if manual_total and manual_total.is_file() and meta.get("master_outline"):
        manual = _read_text(manual_total).strip()
        if manual and _sha(manual) != _sha(str(meta["master_outline"]).strip()):
            found.append({"kind": "manual_outline_diverged", "file": manual_total.name})
    return found


def recover_plan(project, persist: bool = True) -> Dict[str, Any]:
    """Authoritative, tombstone-aware rebuild of ``story_plan.json``.

    Unlike the v0.7.5 fill-only version this always reflects the current
    Markdown (new ending, edited outline, deleted chapter) and never
    resurrects a deleted chapter from a stale cache.
    """
    meta = load_meta(project)
    meta["_project"] = str(project)
    chapters, found = _merge_chapters(meta)
    if not _plan_files(_book_path(meta)):
        previous = {}
        story = _story_plan_path(project)
        if story.is_file():
            try:
                value = safety.read_json_strict(story)
                if isinstance(value, dict):
                    previous = value.get("chapters") or {}
            except Exception:
                previous = {}
        if previous:
            found.append({"kind": "outline_file_missing",
                          "chapters": sorted(previous, key=lambda key: int(key))[:20]})
    meta.pop("_project", None)
    if persist:
        _sync_story_plan(project, meta, chapters, found)
    return {"master_outline": meta.get("master_outline", ""),
            "volumes": meta.get("volumes", ""),
            "character_arcs": meta.get("character_arcs", ""),
            "foreshadowing": meta.get("foreshadowing", ""),
            "chapters": chapters, "conflicts": found,
            "meta_revision": meta.get("meta_revision", 0)}


def write_file(project, filename: str, *, content: str, revision: Optional[str] = None,
               confirm_removed_chapters: Optional[Iterable[int]] = None,
               op_id: Optional[str] = None) -> Dict[str, Any]:
    if not isinstance(content, str):
        raise OutlineError("content_required")
    data = content.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise OutlineError("outline_too_large", status=413)
    if "\x00" in content:
        raise OutlineError("invalid_content")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    with _lock(project):
        path = _safe_outline_path(project, filename)
        if not path.is_file():
            raise OutlineError("outline_file_missing", status=404)
        current_raw = path.read_bytes()
        current_rev = hashlib.sha256(current_raw).hexdigest()
        if revision and revision != current_rev:
            raise OutlineError("outline_conflict", status=409,
                               detail={"current_revision": current_rev})
        _backup(project, path)
        old_visible, old_plan = _strip_plan_comment(_decode(current_raw))
        old_numbers = {row["id"] for row in _parse_visible(old_visible)}
        new_rows = _parse_visible(normalized)
        if not new_rows and old_numbers:
            raise OutlineError("missing_chapter_headings", status=409,
                               detail={"missing_chapters": sorted(old_numbers)})
        new_numbers = {row["id"] for row in new_rows}
        removed = sorted(old_numbers - new_numbers)
        confirmed = {int(x) for x in (confirm_removed_chapters or [])}
        missing = [number for number in removed if number not in confirmed]
        if missing:
            raise OutlineError("missing_chapter_headings", status=409,
                               detail={"missing_chapters": missing})
        meta = load_meta(project)
        meta["_project"] = str(project)
        chapters, _ = _merge_chapters(meta)
        tombstones = _tombstones(old_plan)
        stamp = _now()
        payload_chapters = []
        for row in new_rows:
            key = str(row["id"])
            old_item = next((item for item in (old_plan or {}).get("chapters") or []
                             if isinstance(item, dict) and str(item.get("id")) == key), {})
            if old_item.get("deleted"):
                rev = int(old_item.get("chapter_rev") or 0) or 1
            else:
                rev = max(_chapter_rev(old_plan, row["id"]),
                          int((chapters.get(key) or {}).get("chapter_rev") or 0)) + 1
            payload_chapters.append({
                "id": row["id"], "title": row["title"], "outline": row["outline"],
                "key_scene": bool((chapters.get(key) or {}).get("key_scene")),
                "chapter_rev": rev, "outline_sha256": _sha(row["outline"]),
                "author_edited": True,
            })
        for number in confirmed:
            if number in old_numbers:
                tombstones[number] = {"id": number, "deleted": True,
                                      "chapter_rev": _chapter_rev(old_plan, number) + 1}
        for number, item in tombstones.items():
            if number not in new_numbers:
                payload_chapters.append(item)
        payload = {
            "schema_version": 2,
            "chapters": payload_chapters,
            "meta_revision": int(meta.get("meta_revision") or 0),
            "updated_at": stamp,
        }
        visible = "\n\n".join(
            f"## 第{row['id']}章 {row['title']}".rstrip() + "\n" + row["outline"]
            for row in new_rows
        ).rstrip() + "\n"
        comment = "<!-- novel-plan:" + json.dumps(payload, ensure_ascii=False).replace("-->", "--\\u003e") + " -->\n\n"
        if len((comment + visible).encode("utf-8")) > MAX_FILE_BYTES:
            raise OutlineError("outline_too_large", status=413)
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write((comment + visible).encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            safety.replace_with_retry(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        # 权威 .md 已落盘，再刷新派生索引；若此处崩溃，recover_plan 从 .md 重建。
        meta.pop("_project", None)
        if not _story_plan_path(project).is_file():
            meta["plan_revision"] = int(meta.get("meta_revision") or 0)
        rebuild = recover_plan(project, persist=True)
    return {"status": "saved", "name": path.name, "revision": _revision_of(path),
            "chapter_revs": {str(c["id"]): c["chapter_rev"] for c in payload_chapters if not c.get("deleted")},
            "tombstones": sorted(tombstones), "removed_chapters": removed,
            "plan": rebuild, "op_id": op_id}


def create_file(project, *, filename: str, content: str = "") -> Dict[str, Any]:
    name = _validate_filename(filename)
    path = _outline_dir(project) / name
    if path.exists():
        raise OutlineError("outline_file_exists", status=409)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(content, str) or "\x00" in content:
        raise OutlineError("invalid_content")
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise OutlineError("invalid_content") from exc
    if len(encoded) > MAX_FILE_BYTES:
        raise OutlineError("outline_too_large", status=413)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        safety.replace_with_retry(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"status": "created", "name": name, "revision": _revision_of(path)}


def write_meta(project, data: Dict[str, Any], *, expected_meta_revision: Optional[int] = None) -> Dict[str, Any]:
    if expected_meta_revision is not None:
        if isinstance(expected_meta_revision, bool):
            raise OutlineError("meta_revision_invalid")
        try:
            expected_meta_revision = int(expected_meta_revision)
        except (TypeError, ValueError) as exc:
            raise OutlineError("meta_revision_invalid") from exc
    with _lock(project):
        meta = load_meta(project)
        if expected_meta_revision is not None and expected_meta_revision != int(meta.get("meta_revision") or 0):
            raise OutlineError("meta_conflict", status=409,
                               detail={"current_meta_revision": meta.get("meta_revision", 0)})
        for field in ("master_outline", "volumes", "character_arcs", "foreshadowing"):
            if field in data:
                value = data.get(field)
                if not isinstance(value, str) or "\x00" in value:
                    raise OutlineError("invalid_meta_field")
                try:
                    value.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise OutlineError("invalid_meta_field") from exc
                meta[field] = value
        meta["meta_revision"] = int(meta.get("meta_revision") or 0) + 1
        meta["plan_revision"] = int(meta.get("plan_revision") or 0) + 1
        meta["updated_at"] = _now()
        _write_json(_meta_path(project), meta)
        rebuild = recover_plan(project, persist=True)
    return {"status": "saved", "meta": meta, "plan": rebuild}


# --------------------------------------------------------------------- lore

def _safe_lore_path(project, filename: str) -> Path:
    name = _validate_filename(filename)
    base = _lore_dir(project).resolve()
    base.mkdir(parents=True, exist_ok=True)
    path = (base / name).resolve()
    if path.parent != base:
        raise OutlineError("path_escape")
    if path.exists() and path.is_symlink():
        raise OutlineError("path_escape")
    return path


def lore_files(project) -> Dict[str, Any]:
    folder = _lore_dir(project)
    rows = []
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        if path.is_file() and not path.is_symlink():
            raw = path.read_bytes()
            rows.append({"name": path.name, "bytes": len(raw),
                         "revision": hashlib.sha256(raw).hexdigest(),
                         "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()})
    return {"files": rows}


def read_lore(project, filename: str) -> Dict[str, Any]:
    path = _safe_lore_path(project, filename)
    if not path.is_file():
        raise OutlineError("lore_file_missing", status=404)
    raw = path.read_bytes()
    return {"name": path.name, "content": _decode(raw),
            "revision": hashlib.sha256(raw).hexdigest()}


def write_lore(project, filename: str, *, content: str, revision: Optional[str] = None) -> Dict[str, Any]:
    if not isinstance(content, str) or "\x00" in content:
        raise OutlineError("invalid_content")
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    if len(text.encode("utf-8")) > MAX_LORE_BYTES:
        raise OutlineError("lore_too_large", status=413)
    with _lock(project):
        path = _safe_lore_path(project, filename)
        if path.is_file() and revision and revision != _revision_of(path):
            raise OutlineError("lore_conflict", status=409)
        if path.is_file():
            _backup(project, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(text.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            safety.replace_with_retry(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return {"status": "saved", "name": path.name, "revision": _revision_of(path)}
