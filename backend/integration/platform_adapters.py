"""平台排期适配器注册表（0.6.1 B02，审计后修订）。

默认**没有任何生产适配器**：本版不替作者向真实平台写入任何东西。测试或后续版本
可以注册替身/真实适配器，注册表本身不做网络访问。

三种失败必须分开，否则“已写入”和“没写入”会被混成同一种可重试状态：

- :class:`AdapterUnavailable` —— 没有这个能力（没注册适配器）。可以下次再说，
  但不能当成“平台没收”。
- :class:`AdapterRejected` —— 平台明确拒绝（``scheduled is False``）。确定没写入，
  但重试同样的内容没有意义，标失败等人处理。
- :class:`AdapterResultUnknown` —— 结果未知（抛异常、返回不是对象、缺字段）。
  平台**可能已经收下**，只能只读对账，绝不允许自动重试写入（T06）。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Protocol, runtime_checkable


class AdapterUnavailable(RuntimeError):
    """没有该平台的适配器/能力：本次不写，下轮可再评估。"""


class AdapterRejected(RuntimeError):
    """平台明确拒绝：确定没有写入，但不自动重试。"""


class AdapterResultUnknown(RuntimeError):
    """提交结果未知：平台可能已收，必须先只读对账。"""


@runtime_checkable
class PlatformAdapter(Protocol):
    def submit_scheduled(self, job: Mapping[str, Any], intent: Mapping[str, Any],
                         chapter_path: str) -> Mapping[str, Any]:
        ...

    def read_schedule(self, platform: str, account: str,
                      book_id: str) -> Any:
        ...


_REGISTRY: Dict[str, Any] = {}


def _norm(platform: Any) -> str:
    return str(platform or "").strip().lower()


def register(platform: str, adapter: Any) -> None:
    name = _norm(platform)
    if not name:
        raise ValueError("platform 不能为空")
    if adapter is None:
        raise ValueError("adapter 不能为空")
    _REGISTRY[name] = adapter


def unregister(platform: str) -> None:
    _REGISTRY.pop(_norm(platform), None)


def get_adapter(platform: str) -> Optional[Any]:
    return _REGISTRY.get(_norm(platform))


def registered() -> Dict[str, Any]:
    return dict(_REGISTRY)


def clear() -> None:
    _REGISTRY.clear()


def submit_scheduled(platform: str, job: Mapping[str, Any], intent: Mapping[str, Any],
                     chapter_path: str) -> Dict[str, Any]:
    """调用适配器并严格判定结果类型；判定不了就是“未知”，不是成功也不是失败。"""
    adapter = get_adapter(platform)
    if adapter is None:
        raise AdapterUnavailable(f"没有 {platform or '该平台'} 的排期适配器（本版默认不写入）")
    try:
        result = adapter.submit_scheduled(dict(job), dict(intent), str(chapter_path or ""))
    except (AdapterUnavailable, AdapterRejected, AdapterResultUnknown):
        raise
    except Exception as exc:  # noqa: BLE001 - 超时/网络异常都可能已经写入
        raise AdapterResultUnknown(f"适配器调用异常，结果未知：{str(exc)[:160]}") from exc
    if not isinstance(result, Mapping):
        raise AdapterResultUnknown("适配器返回不是对象，无法判定是否写入")
    flag = result.get("scheduled")
    if flag is False:
        raise AdapterRejected(str(result.get("reason") or "平台拒绝排期")[:200])
    if flag is not True:
        raise AdapterResultUnknown("适配器未明确返回 scheduled=True/False，结果未知")
    return dict(result)
