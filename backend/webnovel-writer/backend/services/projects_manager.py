 
# projects_manager.py - 多项目管理服务
import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from services.genre_catalog import canonical_genre_id, canonical_substyle_id
from services.project_prompt_store import ensure_project_prompts

# 全局配置目录
GLOBAL_CONFIG_DIR = Path(os.getenv('NOVEL_HELPER_WEBNOVEL_HOME') or str(Path.home() / '.webnovel'))
PROJECTS_FILE = GLOBAL_CONFIG_DIR / "projects.json"

# projects.json 是单文件读改写：并发请求（两个标签页/API 调用）必须串行化，
# 否则会互相覆盖；写入必须原子，避免崩溃留下半截 JSON 后又被当成空列表覆盖。
_PROJECTS_LOCK = threading.RLock()


def _ensure_config_dir():
    """确保全局配置目录存在"""
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_projects_data() -> Dict[str, Any]:
    """加载项目列表数据。

    损坏的 projects.json 不再“当作空列表”继续，而是备份后报错，避免下一次
    保存把空列表固化、永久丢失全部项目登记。
    """
    _ensure_config_dir()
    data = {"current_project": None, "projects": []}

    if PROJECTS_FILE.exists():
        try:
            value = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("projects", []), list):
                raise ValueError("projects.json 结构无效")
            data = value
            data.setdefault("projects", [])
            data.setdefault("current_project", None)
        except Exception as exc:
            backup = PROJECTS_FILE.with_name(
                PROJECTS_FILE.name + ".corrupt-" + datetime.now().strftime("%Y%m%dT%H%M%S"))
            try:
                PROJECTS_FILE.replace(backup)
            except OSError:
                pass
            raise ValueError(
                f"projects.json 损坏（已备份为 {backup.name}），请修复后重试；未覆盖现有项目登记"
            ) from exc
    
    # 自动发现根目录项目 (兼容旧版本) - 仅当没有任何项目时
    if not data["projects"]:
        # 注意：此处不应盲目将根目录设为项目，除非它确实包含正文/大纲目录
        root_path = Path(__file__).parent.parent.parent
        if (root_path / "大纲").exists() or (root_path / "正文").exists():
            state_file = root_path / ".webnovel" / "state.json"
            # ... (rest of the discovery logic remains similar but limited)
            try:
                if state_file.exists():
                    state = json.loads(state_file.read_text(encoding="utf-8"))
                    name = state.get("project_info", {}).get("title", state.get("title", "默认项目"))
                else:
                    name = "默认项目"
            except Exception:
                name = "默认项目"
            
            default_project = {
                "id": str(uuid.uuid4()),
                "name": name,
                "path": str(root_path.absolute()),
                "genre": "未知",
                "created_at": datetime.now().strftime("%Y-%m-%d"),
                "last_opened": datetime.now().strftime("%Y-%m-%d"),
                "exists": True
            }
            data["projects"].append(default_project)
            if not data["current_project"]:
                data["current_project"] = default_project["path"]
            _save_projects_data(data)
            
    return data

def find_project_by_path(path: Path) -> Optional[Dict[str, Any]]:
    """根据路径回溯查找所属项目"""
    data = _load_projects_data()
    path = path.expanduser().resolve()
    
    # 尝试匹配路径或其父目录
    best_match = None
    max_len = -1
    
    for p in data.get("projects", []):
        p_path = Path(p["path"]).expanduser().resolve()
        try:
            if path == p_path or p_path in path.parents:
                # 选取最长匹配路径（最具体的子项目）
                if len(str(p_path)) > max_len:
                    max_len = len(str(p_path))
                    best_match = p
        except ValueError:
            continue
            
    return best_match

def _save_projects_data(data: Dict[str, Any]):
    """保存项目列表数据（原子替换）"""
    _ensure_config_dir()
    if not isinstance(data, dict) or not isinstance(data.get("projects", []), list):
        raise ValueError("projects.json 数据无效，拒绝保存")
    _write_json_atomic(PROJECTS_FILE, data)

def list_projects() -> List[Dict[str, Any]]:
    """获取所有项目列表（并同步最新标题、章节数、字数）"""
    data = _load_projects_data()
    projects = data.get("projects", [])
    updated = False

    # 检查项目路径是否存在，并同步标题
    for p in projects:
        p_path = Path(p["path"])
        p["exists"] = p_path.exists()

        if p["exists"]:
            # 尝试读取最新的 state.json
            state_file = p_path / ".webnovel" / "state.json"
            if state_file.exists():
                try:
                    state = json.loads(state_file.read_text(encoding="utf-8"))
                    # 获取最新标题
                    new_title = ""
                    new_genre = ""
                    if "project_info" in state:
                        new_title = state["project_info"].get("title", "")
                        new_genre = state["project_info"].get("genre", "")
                    else:
                        new_title = state.get("title", "")
                        new_genre = state.get("genre", "")

                    # 如果标题不一致，更新缓存
                    if new_title and new_title != p["name"]:
                        p["name"] = new_title
                        updated = True
                    if new_genre and new_genre != p.get("genre"):
                        p["genre"] = new_genre
                        updated = True
                except Exception:
                    pass

            # 统计章节数和总字数
            chapters_dir = p_path / "正文"
            if chapters_dir.exists():
                try:
                    chapter_files = list(chapters_dir.glob("第*章*.md"))
                    p["total_chapters"] = len(chapter_files)
                    total_words = 0
                    for f in chapter_files:
                        try:
                            total_words += len(f.read_text(encoding="utf-8"))
                        except Exception:
                            pass
                    p["total_words"] = total_words
                except Exception:
                    p["total_chapters"] = 0
                    p["total_words"] = 0
            else:
                p["total_chapters"] = 0
                p["total_words"] = 0
        else:
            p["total_chapters"] = 0
            p["total_words"] = 0

    # 如果有更新，保存回 projects.json
    if updated:
        _save_projects_data(data)

    return projects

def get_current_project() -> Optional[Dict[str, Any]]:
    """获取当前项目"""
    data = _load_projects_data()
    current_path = data.get("current_project")
    if not current_path:
        return None
    for p in data.get("projects", []):
        if p["path"] == current_path:
            p["exists"] = Path(p["path"]).exists()
            return p
    return None

def set_current_project(path: Path):
    """设置当前项目路径"""
    with _PROJECTS_LOCK:
        data = _load_projects_data()
        abs_path = str(path.expanduser().resolve())

        # 确保保存为绝对路径
        data["current_project"] = abs_path

        # 更新最后打开时间
        for p in data["projects"]:
            if str(Path(p["path"]).expanduser().resolve()) == abs_path:
                p["last_opened"] = datetime.now().strftime("%Y-%m-%d")
                break

        _save_projects_data(data)


def get_current_project_path() -> Optional[Path]:
    """获取当前项目路径"""
    project = get_current_project()
    if project and project.get("exists"):
        return Path(project["path"])
    return None

def create_project(name: str, path: str, genre: str = "修仙", substyle: str = "") -> Dict[str, Any]:
    """新建项目"""
    project_path = Path(path).expanduser().resolve()
    genre = canonical_genre_id(genre) or "玄幻"
    substyle = canonical_substyle_id(genre, substyle)

    with _PROJECTS_LOCK:
        # 先查重，再操作文件系统
        data = _load_projects_data()
        for p in data["projects"]:
            if Path(p["path"]).expanduser().resolve() == project_path:
                return {"error": "项目路径已存在", "project": p}

        if (project_path / ".webnovel" / "state.json").exists():
            return {"error": "该目录已有小说数据，请使用导入项目"}

        # 安全：后续操作文件系统
        project_path.mkdir(parents=True, exist_ok=True)

        # 创建项目基础目录结构
        (project_path / "大纲").mkdir(exist_ok=True)
        (project_path / "正文").mkdir(exist_ok=True)
        (project_path / "设定集").mkdir(exist_ok=True)
        (project_path / ".webnovel").mkdir(exist_ok=True)

        # 初始化 state.json
        state_file = project_path / ".webnovel" / "state.json"
        state = {
            "title": name,
            "genre": genre,
            "substyle": substyle,
            "created_at": datetime.now().isoformat(),
            "initialized": False  # 新建项目默认未初始化，需通过 AI Init 完成
        }
        _write_json_atomic(state_file, state)
        ensure_project_prompts(project_path, genre, substyle)

        # 添加到项目列表（复用已加载的 data）
        project = {
            "id": str(uuid.uuid4()),
            "name": name,
            "path": str(project_path),
            "genre": genre,
            "substyle": substyle,
            "created_at": datetime.now().strftime("%Y-%m-%d"),
            "last_opened": datetime.now().strftime("%Y-%m-%d")
        }

        data["projects"].append(project)
        data["current_project"] = project["path"]
        _save_projects_data(data)

    return {"success": True, "project": project}


def switch_project(project_id: str) -> Dict[str, Any]:
    """切换当前项目"""
    with _PROJECTS_LOCK:
        data = _load_projects_data()
        for p in data["projects"]:
            if p["id"] == project_id:
                if not Path(p["path"]).expanduser().exists():
                    return {"error": "项目路径不存在", "path": p["path"]}
                data["current_project"] = p["path"]
                p["last_opened"] = datetime.now().strftime("%Y-%m-%d")
                _save_projects_data(data)
                return {"success": True, "project": p}
    return {"error": "项目不存在"}


def import_project(path: str) -> Dict[str, Any]:
    """导入现有项目"""
    project_path = Path(path).expanduser().resolve()
    if not project_path.exists():
        return {"error": "路径不存在"}

    # 尝试读取项目信息
    state_file = project_path / ".webnovel" / "state.json"
    name = project_path.name
    genre = "未知"
    substyle = ""

    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("state.json 结构无效")
            if "project_info" in state:
                name = state.get("project_info", {}).get("title", state.get("title", name))
                genre = state.get("project_info", {}).get("genre", state.get("genre", genre))
                substyle = state.get("project_info", {}).get("substyle", state.get("substyle", ""))
            else:
                name = state.get("title", name)
                genre = state.get("genre", genre)
                substyle = state.get("substyle", "")
        except Exception:
            pass

    with _PROJECTS_LOCK:
        data = _load_projects_data()
        # 检查是否已存在
        for p in data["projects"]:
            if p["path"] == str(project_path.absolute()):
                data["current_project"] = p["path"]
                _save_projects_data(data)
                return {"success": True, "project": p, "already_exists": True}

        # 新增
        project = {
            "id": str(uuid.uuid4()),
            "name": name,
            "path": str(project_path.absolute()),
            "genre": genre,
            "substyle": substyle,
            "created_at": datetime.now().strftime("%Y-%m-%d"),
            "last_opened": datetime.now().strftime("%Y-%m-%d")
        }
        data["projects"].append(project)
        data["current_project"] = project["path"]
        _save_projects_data(data)

    # 登记成功后再确保 Prompt 快照（生成失败不应阻断导入）
    try:
        ensure_project_prompts(project_path, genre, substyle)
    except Exception:
        pass

    return {"success": True, "project": project}


def _deletion_problem(target: Path) -> str:
    """递归删除前的安全校验，防止误删盘符根/用户目录/普通目录。"""
    try:
        target = target.expanduser().resolve()
    except OSError:
        return "项目路径无法解析，拒绝删除"
    if not target.is_dir():
        return "项目目录不存在，未从列表移除"
    if target.parent == target or target == Path(target.anchor):
        return "拒绝删除磁盘根目录"
    if target == Path.home().resolve() or target == Path.cwd().resolve():
        return "拒绝删除用户目录或当前工作目录"
    if len(target.parts) < 3:
        return "拒绝删除层级过浅的目录"
    if not (target / ".webnovel").is_dir():
        return "拒绝删除：目录缺少 .webnovel 标记（可能不是小说项目）"
    return ""


def delete_project(project_id: str, delete_files: bool = False) -> Dict[str, Any]:
    """删除项目（从索引移除，可选删除文件）"""
    with _PROJECTS_LOCK:
        data = _load_projects_data()
        for i, p in enumerate(data["projects"]):
            if p["id"] != project_id:
                continue
            removed = p
            if delete_files:
                import shutil
                target = Path(removed["path"])
                problem = _deletion_problem(target)
                if problem:
                    return {"error": problem}
                try:
                    shutil.rmtree(target.resolve())
                except Exception as exc:
                    # 删除失败时保留登记，避免“列表没了、文件还在”无法再管理
                    return {"error": f"文件删除失败，未从项目列表移除: {exc}"}
            data["projects"].pop(i)
            if data["current_project"] == removed["path"]:
                data["current_project"] = data["projects"][0]["path"] if data["projects"] else None
            _save_projects_data(data)
            return {"success": True}
    return {"error": "项目不存在"}
