"""凭据存储适配层：优先 Windows DPAPI，失败时明确降级为受 ACL 保护的明文。

职责边界：
- 只处理配置文件里的 ``api_key``；其余字段原样保留。
- 迁移顺序固定为“写受保护存储 → 读回校验 → 再移除明文”，任何一步失败都保留旧明文。
- 受保护备份只保存加密块，不复制明文密钥。
- DPAPI 不可用时返回 ``mode='plaintext-acl'``，绝不伪称迁移完成。
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

STORE_NAME = "secrets.dpapi"
BACKUP_NAME = "secrets.dpapi.bak"
SCHEMA = 1

Protect = Callable[[bytes], bytes]
Unprotect = Callable[[bytes], bytes]

_UNSET = object()  # 区分“未传参，按平台探测”与“显式要求无保护”


class SecretUnavailable(RuntimeError):
    """当前环境没有可用的系统凭据保护。"""


class SecretCorrupt(RuntimeError):
    """受保护存储无法解密或结构损坏。"""


def _windows_codec() -> Tuple[Protect, Unprotect]:
    if os.name != "nt":
        raise SecretUnavailable("only Windows DPAPI is available")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from integration.credential_codec import transform

    return (lambda raw: transform(raw, True), lambda raw: transform(raw, False))


def codec() -> Optional[Tuple[Protect, Unprotect]]:
    """返回 (protect, unprotect)；不可用时返回 None 而不是抛错。"""
    try:
        return _windows_codec()
    except Exception:
        return None


def store_path(root: Path) -> Path:
    return Path(root) / STORE_NAME


def status(root: Path, codec_pair: Optional[Tuple[Protect, Unprotect]] = _UNSET) -> Dict[str, Any]:
    pair = codec() if codec_pair is _UNSET else codec_pair
    exists = store_path(root).is_file()
    if pair is None:
        return {"mode": "plaintext-acl", "available": False, "store": False,
                "detail": "当前系统没有可用的凭据保护；密钥保存在仅当前用户可读的配置文件中"}
    if not exists:
        return {"mode": "dpapi", "available": True, "store": False,
                "detail": "系统凭据保护可用；尚未迁移旧密钥"}
    return {"mode": "dpapi", "available": True, "store": True, "detail": "密钥保存在系统凭据保护下"}


def _raw_store(root: Path) -> Dict[str, str]:
    path = store_path(root)
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SecretCorrupt("受保护凭据文件无法解析") from error
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA:
        raise SecretCorrupt("受保护凭据文件版本不受支持")
    values = doc.get("secrets")
    if not isinstance(values, dict):
        raise SecretCorrupt("受保护凭据文件结构损坏")
    return {str(key): str(value) for key, value in values.items()}


def _decrypt(root: Path, pair: Tuple[Protect, Unprotect]) -> Dict[str, str]:
    result = {}
    for key, blob in _raw_store(root).items():
        try:
            result[key] = pair[1](base64.b64decode(blob, validate=True)).decode("utf-8")
        except Exception as error:
            raise SecretCorrupt(f"凭据无法解密：{key}") from error
    return result


def _write_atomic(path: Path, payload: Dict[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _persist(root: Path, pair: Tuple[Protect, Unprotect], values: Dict[str, str]) -> None:
    encrypted = {key: base64.b64encode(pair[0](value.encode("utf-8"))).decode("ascii") for key, value in values.items()}
    _write_atomic(store_path(root), {"schema_version": SCHEMA, "cipher": "dpapi", "secrets": encrypted})
    if _decrypt(root, pair) != values:
        raise SecretCorrupt("凭据写入后无法读回")


def backup(root: Path, pair: Tuple[Protect, Unprotect]) -> Optional[Path]:
    """受保护备份：只复制加密块，不复制明文。"""
    source = store_path(root)
    if not source.is_file():
        return None
    target = Path(root) / BACKUP_NAME
    _write_atomic(target, json.loads(source.read_text(encoding="utf-8")))
    return target


def _paths(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """可写密钥的位置：根、每个角色、每个渠道。"""
    slots = {"root": config}
    for name in ("roles", "providers"):
        section = config.get(name)
        if isinstance(section, dict):
            for key, value in section.items():
                if isinstance(value, dict):
                    slots[f"{name}:{key}"] = value
    return slots


def collect(config: Dict[str, Any]) -> Dict[str, str]:
    values = {}
    for name, slot in _paths(config).items():
        value = slot.get("api_key")
        if isinstance(value, str) and value.strip():
            values[name] = value.strip()
    return values


def attach(config: Dict[str, Any], secrets: Dict[str, str]) -> Dict[str, Any]:
    """把受保护存储里的密钥合并回内存配置（调用方只见明文内存副本）。"""
    for name, slot in _paths(config).items():
        if name in secrets and not slot.get("api_key"):
            slot["api_key"] = secrets[name]
    return config


def strip(config: Dict[str, Any]) -> Dict[str, Any]:
    for slot in _paths(config).values():
        if slot.get("api_key"):
            slot["api_key"] = ""
    config["secret_store"] = "dpapi"
    return config


def load(root: Path, config: Dict[str, Any], codec_pair: Optional[Tuple[Protect, Unprotect]] = _UNSET) -> Dict[str, Any]:
    pair = codec() if codec_pair is _UNSET else codec_pair
    if pair is None:
        return config
    try:
        secrets = _decrypt(root, pair)
    except SecretCorrupt:
        return config
    return attach(config, secrets)


def save(root: Path, config: Dict[str, Any], write_config: Callable[[Dict[str, Any]], None],
         codec_pair: Optional[Tuple[Protect, Unprotect]] = _UNSET) -> Dict[str, Any]:
    """保存配置：可用时先写受保护存储并校验，再写不含明文的配置。

    ``write_config`` 由调用方提供（负责原子写与 ACL 收紧）。迁移失败时回退为写明文，
    返回 ``migrated=False``，绝不清空已有密钥。
    """
    pair = codec() if codec_pair is _UNSET else codec_pair
    secrets = collect(config)
    if pair is None or not secrets:
        write_config(config)
        return {"mode": "plaintext-acl" if pair is None else "dpapi", "migrated": False,
                "stored": len(secrets), "detail": status(root, pair)["detail"]}
    try:
        existing = _decrypt(root, pair) if store_path(root).is_file() else {}
    except SecretCorrupt:
        existing = {}
    merged = {**existing, **secrets}
    try:
        backup(root, pair)
        _persist(root, pair, merged)
    except Exception:
        write_config(config)
        return {"mode": "plaintext-acl", "migrated": False, "stored": 0,
                "detail": "凭据保护暂不可用，已保留明文配置"}
    write_config(strip(json.loads(json.dumps(config))))
    return {"mode": "dpapi", "migrated": True, "stored": len(secrets), "detail": "密钥已迁移到系统凭据保护"}


def restore_backup(root: Path, write_config: Callable[[Dict[str, Any]], None],
                   codec_pair: Optional[Tuple[Protect, Unprotect]] = _UNSET) -> Dict[str, Any]:
    """用受保护备份恢复存储；返回恢复后的密钥键名，不返回明文。"""
    pair = codec() if codec_pair is _UNSET else codec_pair
    if pair is None:
        raise SecretUnavailable("当前系统没有可用的凭据保护")
    source = Path(root) / BACKUP_NAME
    if not source.is_file():
        raise SecretCorrupt("没有可用的凭据备份")
    payload = json.loads(source.read_text(encoding="utf-8"))
    _write_atomic(store_path(root), payload)
    values = _decrypt(root, pair)
    write_config({})
    return {"restored": sorted(values), "count": len(values)}
