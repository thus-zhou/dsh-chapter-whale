from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from dependencies import get_project_root

router = APIRouter()
TYPE_NAMES = {"character": "角色", "location": "地点", "item": "物品", "skill": "招式", "faction": "势力", "foreshadowing": "伏笔"}
TIER_NAMES = {"core": "核心", "major": "重要", "minor": "次要", "decor": "装饰"}


def _api_entity(entity):
    if entity is None:
        return None
    result = dict(entity)
    result["name"] = result.get("canonical_name", result.get("name", ""))
    result["description"] = result.get("desc", result.get("description", ""))
    result["current"] = result.get("current_json", result.get("current", {}))
    result["type"] = next((key for key, value in TYPE_NAMES.items() if value == result.get("type")), result.get("type"))
    result["tier"] = next((key for key, value in TIER_NAMES.items() if value == result.get("tier")), result.get("tier"))
    return result

def get_index_manager(project_root: Path):
    """获取 IndexManager 实例；失败时打印原因并返回 None。"""
    try:
        from data_modules.config import DataModulesConfig
        from data_modules.index_manager import IndexManager
        config = DataModulesConfig.from_project_root(project_root)
        return IndexManager(config)
    except Exception as e:
        print(f"[entities] 索引管理器不可用: {e}")
        return None


def _index_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="实体索引数据库不可用；请先执行索引重建（RAG 页面）后重试")


@router.get("")
async def get_entities(
    entity_type: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    root: Path = Depends(get_project_root)
):
    """获取实体列表"""
    manager = get_index_manager(root)
    
    if not manager:
        raise _index_unavailable()
    
    try:
        if entity_type:
            entities = manager.get_entities_by_type(TYPE_NAMES.get(entity_type, entity_type))
        elif tier:
            entities = manager.get_entities_by_tier(TIER_NAMES.get(tier, tier))
        else:
            # 获取所有核心实体
            entities = manager.get_all_entities()
        
        return {"entities": [_api_entity(e) for e in entities]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取实体列表失败: {e}") from e


@router.get("/types")
async def get_entity_types():
    """获取实体类型列表"""
    return {
        "types": [
            {"id": "character", "name": "角色", "icon": "👤"},
            {"id": "location", "name": "地点", "icon": "📍"},
            {"id": "item", "name": "物品", "icon": "🎁"},
            {"id": "skill", "name": "招式/技能", "icon": "⚔️"},
            {"id": "faction", "name": "势力", "icon": "🏰"},
            {"id": "foreshadowing", "name": "伏笔", "icon": "🔮"},
        ]
    }


@router.get("/tiers")
async def get_entity_tiers():
    """获取实体重要度列表"""
    return {
        "tiers": [
            {"id": "core", "name": "核心", "color": "#FF4444"},
            {"id": "major", "name": "重要", "color": "#FF8800"},
            {"id": "minor", "name": "次要", "color": "#44AA44"},
            {"id": "decor", "name": "装饰", "color": "#888888"},
        ]
    }


@router.get("/type/{entity_type}")
async def get_entities_by_type(entity_type: str, root: Path = Depends(get_project_root)):
    """按类型获取实体"""
    manager = get_index_manager(root)

    if not manager:
        raise _index_unavailable()

    try:
        entities = manager.get_entities_by_type(TYPE_NAMES.get(entity_type, entity_type))
        return {"entities": [_api_entity(e) for e in entities], "type": entity_type}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取实体列表失败: {e}") from e


@router.get("/search")
async def search_entities(
    q: str = Query(..., description="搜索关键词"),
    root: Path = Depends(get_project_root)
):
    """搜索实体"""
    manager = get_index_manager(root)

    if not manager:
        raise _index_unavailable()

    try:
        # 搜索实体（按名称/别名匹配）
        results = manager.search_entities(q)
        return {"results": [_api_entity(e) for e in results], "query": q}
    except AttributeError:
        # 如果 search_entities 方法不存在，返回空结果
        return {"results": [], "query": q, "error": "搜索功能未实现"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索实体失败: {e}") from e


@router.get("/protagonist")
async def get_protagonist(root: Path = Depends(get_project_root)):
    """获取主角信息"""
    manager = get_index_manager(root)

    if not manager:
        raise _index_unavailable()

    try:
        protagonist = manager.get_protagonist()
        return {"protagonist": _api_entity(protagonist)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取主角信息失败: {e}") from e


@router.get("/characters")
async def get_characters(root: Path = Depends(get_project_root)):
    """获取角色列表"""
    # 尝试从 IndexManager 获取
    manager = get_index_manager(root)
    if manager:
        try:
            entities = manager.get_entities_by_type("角色")
            return {"characters": [_api_entity(e) for e in entities]}
        except Exception:
            pass

    # 回退：从设定集/角色库（主要角色/次要角色/反派角色 等子目录）读取
    characters_dir = root / "设定集" / "角色库"
    characters = []

    if characters_dir.exists():
        for f in sorted(characters_dir.rglob("*.md")):
            try:
                content = f.read_text(encoding="utf-8-sig")
            except OSError:
                continue
            characters.append({
                "id": f.stem,
                "name": f.stem,
                "content": content
            })

    return {"characters": characters}


@router.get("/foreshadowing")
async def get_foreshadowing(
    status: Optional[str] = Query(None, description="pending/resolved"),
    root: Path = Depends(get_project_root)
):
    """获取伏笔列表"""
    manager = get_index_manager(root)

    if not manager:
        raise _index_unavailable()

    try:
        entities = [_api_entity(e) for e in manager.get_entities_by_type("伏笔")]

        # 按状态过滤
        if status:
            entities = [e for e in entities if e.get("current", {}).get("status") == status]

        return {"foreshadowing": entities}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取伏笔失败: {e}") from e


@router.get("/{entity_id}")
async def get_entity(entity_id: str, root: Path = Depends(get_project_root)):
    """获取实体详情（必须放在所有固定路径之后）"""
    manager = get_index_manager(root)

    if not manager:
        raise HTTPException(status_code=500, detail="索引管理器未初始化")

    try:
        entity = manager.get_entity(entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail=f"未找到实体: {entity_id}")

        # 获取出场记录
        appearances = manager.get_entity_appearances(entity_id, limit=20)

        return {"entity": _api_entity(entity), "appearances": appearances}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
