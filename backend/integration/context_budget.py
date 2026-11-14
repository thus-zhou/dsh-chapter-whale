"""输入预算：把一次请求的上下文限制在可解释的上限内（方案 v3.0 M02）。

三条硬规则：

1. 档位上限（快速 8000 / 标准 16000 / 充分资料 32000）只是**上界**，实际
   可用额度还要同时受模型总窗口、输出上限、安全余量约束，取最小值。
2. 模型窗口未知时用**显式配置**的保守值；没有可靠配置就明确报
   ``BudgetUnconfigured``（需要配置），绝不偷偷放大窗口。
3. 当前任务、核心约定、必要原文标为 ``required``，装不下就停止并说明缺多少，
   不做无声截断；可选块（参考资料、示例、历史摘要）按顺序填充，装不下就
   记入 ``dropped`` 并标注。

Token 数一律沿用 ``costs.estimate`` 的估算，返回值带 ``estimated=True``。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

PROFILES = {"quick": 8000, "standard": 16000, "generous": 32000}
DEFAULT_PROFILE = "standard"


class BudgetUnconfigured(ValueError):
    """没有可靠的窗口配置：需要作者显式给出，不能猜。"""

    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


class CannotFit(ValueError):
    """必要内容已经超过可用额度：停止，而不是裁掉任务或约定。"""

    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def _estimate(value, estimator=None) -> int:
    if estimator is not None:
        return int(estimator(value))
    from . import costs
    return int(costs.estimate(value))


def profile_limit(profile: str) -> int:
    if profile not in PROFILES:
        raise BudgetUnconfigured("unknown_profile", {"profile": profile, "allowed": sorted(PROFILES)})
    return PROFILES[profile]


def available_tokens(profile: str = DEFAULT_PROFILE, *, model_window: Optional[int] = None,
                     max_output: Optional[int] = None, safety: Optional[int] = None,
                     conservative_window: Optional[int] = None) -> Dict[str, Any]:
    """计算本次可用输入额度；窗口未知且无保守配置时明确要求配置。"""
    ceiling = profile_limit(profile)
    if model_window is None:
        if conservative_window is None:
            raise BudgetUnconfigured("model_window_unknown", {"profile": profile, "ceiling": ceiling})
        if type(conservative_window) is not int or conservative_window < 1024:
            raise BudgetUnconfigured("conservative_window_invalid", {"value": conservative_window})
        model_window = conservative_window
        window_origin = "configured_conservative"
    else:
        if type(model_window) is not int or model_window < 1024:
            raise BudgetUnconfigured("model_window_invalid", {"value": model_window})
        window_origin = "model_reported"
    output = 4096 if max_output is None else max_output
    margin = 1024 if safety is None else safety
    if type(output) is not int or output < 0 or type(margin) is not int or margin < 0:
        raise BudgetUnconfigured("output_or_safety_invalid", {"max_output": output, "safety": margin})
    headroom = max(0, model_window - output - margin)
    return {"profile": profile, "ceiling": ceiling, "model_window": model_window,
            "window_origin": window_origin, "reserved_output": output,
            "safety": margin, "available": min(ceiling, headroom)}


def plan(blocks: Sequence[Dict[str, Any]] = (), profile: str = DEFAULT_PROFILE, *,
         model_window: Optional[int] = None, max_output: Optional[int] = None,
         safety: Optional[int] = None, conservative_window: Optional[int] = None,
         estimator=None) -> Dict[str, Any]:
    """按块规划一次请求的上下文。

    每个块形如 ``{"name": "task", "content": "...", "required": True}``。
    必要块装不下抛 ``CannotFit``；可选块按给出顺序填充，放不下的进 ``dropped``。
    """
    budget = available_tokens(profile, model_window=model_window, max_output=max_output,
                              safety=safety, conservative_window=conservative_window)
    sized = []
    for block in blocks:
        if not isinstance(block, dict) or "name" not in block:
            raise CannotFit("block_malformed", {"block": str(block)[:80]})
        content = block.get("content") or ""
        sized.append({"name": str(block["name"]), "required": bool(block.get("required")),
                      "tokens": _estimate(content, estimator), "chars": len(content)})

    required = [item for item in sized if item["required"]]
    required_tokens = sum(item["tokens"] for item in required)
    if required_tokens > budget["available"]:
        raise CannotFit("required_exceeds_budget", {
            "required_tokens": required_tokens, "available": budget["available"],
            "profile": budget["profile"], "over_by": required_tokens - budget["available"],
            "blocks": [item["name"] for item in required]})

    used = required_tokens
    included = [item["name"] for item in required]
    dropped: List[Dict[str, Any]] = []
    for item in sized:
        if item["required"]:
            continue
        if used + item["tokens"] <= budget["available"]:
            used += item["tokens"]
            included.append(item["name"])
        else:
            dropped.append({"name": item["name"], "tokens": item["tokens"],
                            "reason": "budget_exhausted"})
    return {**budget, "required_tokens": required_tokens, "used_tokens": used,
            "remaining_tokens": max(0, budget["available"] - used),
            "included": included, "dropped": dropped, "estimated": True,
            "over_budget": False}


def fits(blocks: Iterable[Dict[str, Any]], **options) -> bool:
    """只回答"装不装得下"，不改变调用方的组装方式。"""
    try:
        plan(list(blocks), **options)
    except (CannotFit, BudgetUnconfigured):
        return False
    return True
