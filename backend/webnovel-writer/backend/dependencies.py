from pathlib import Path
from typing import Optional
from fastapi import Header, Query, HTTPException
from urllib.parse import unquote
import os


def _validate_project_root(path: Path) -> Path:
    """校验客户端传入的项目根目录，拒绝盘符根/用户目录/系统目录。

    旧实现直接 `Path(project_root).resolve()` 返回，配合
    DELETE /api/projects/reset 可对任意路径（含 C:\\ 或用户目录）执行
    “删除 正文/大纲/设定集 后重建”；这里做最小但必要的边界校验。
    """
    try:
        path = path.expanduser().resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"项目路径无法解析: {exc}") from None
    if path.parent == path or path == Path(path.anchor):
        raise HTTPException(status_code=400, detail="项目路径不能是磁盘根目录")
    if path == Path.home().resolve() or path == Path.cwd().resolve():
        raise HTTPException(status_code=400, detail="项目路径不能是用户目录或当前工作目录")
    system_roots = []
    for env_name in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        value = os.environ.get(env_name)
        if value:
            try:
                system_roots.append(Path(value).resolve())
            except OSError:
                pass
    for system_root in system_roots:
        try:
            if path == system_root or system_root in path.parents:
                raise HTTPException(status_code=400, detail="项目路径不能位于系统目录")
        except ValueError:
            continue
    if len(path.parts) < 3:
        raise HTTPException(status_code=400, detail="项目路径层级过浅，拒绝作为项目根目录")
    return path


def get_project_root(
    project_root: Optional[str] = Query(None),
    x_project_root: Optional[str] = Header(None, alias="X-Project-Root")
) -> Path:
    """
    确定当前操作的项目根路径。
    优先级：
    1. URL 查询参数 project_root
    2. HTTP Header X-Project-Root
    3. 全局 projects_manager 记录的当前项目
    4. 报错（不再静默回退到默认路径）
    """
    # 1. 查询参数
    if project_root:
        return _validate_project_root(Path(project_root))

    # 2. Header 参数
    if x_project_root:
        if x_project_root.lower() not in ["null", "undefined", "none"]:
            try:
                decoded = unquote(x_project_root)
                path = _validate_project_root(Path(decoded))
                if not path.exists():
                    # 显式传入的项目路径失效时必须报错：静默回退到全局当前项目会
                    # 把章节/设定写入另一本书。
                    raise HTTPException(status_code=400, detail=f"项目路径不存在: {path}")
                return path
            except HTTPException:
                raise
            except Exception:
                pass

    # 3. 后端全局状态
    try:
        from services import projects_manager
        current = projects_manager.get_current_project_path()

        if current and current.exists():
            return current
    except ImportError:
        pass

    # 4. 报错，要求前端传递项目路径
    raise HTTPException(
        status_code=400,
        detail="未指定项目路径。请先在首页选择一个项目。"
    )
