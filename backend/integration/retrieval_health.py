"""Persist an authentication circuit breaker without storing credentials."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from . import bridge


def identity(config):
    payload=[config.embed_base_url,config.embed_model,str(config.embed_api_key or '')]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def path():
    value=os.getenv('NOVEL_HELPER_RETRIEVAL_HEALTH')
    return Path(value) if value else None


def blocked(config):
    location=path()
    if location is None:return False
    try:
        value=bridge.read_json(location,{})
        # 健康文件可能被写成 list/str 等非对象 JSON，先校验类型
        if not isinstance(value,dict):return False
        return value.get('status')=='auth_blocked' and value.get('identity')==identity(config)
    except (ValueError,OSError):
        return False


def denied(config, status):
    location=path()
    if location is None:return
    bridge.write_json_atomic(location,{'status':'auth_blocked','identity':identity(config),
        'provider_host':urlsplit(config.embed_base_url).hostname,'model':config.embed_model,
        'http_status':status,'updated_at':bridge.now_iso(),
        'fallback':'BM25及本书共享记忆可用；向量接口凭据被拒绝，需更新独立配置，不复用主模型密钥到其他地址'})


def available(config):
    location=path()
    if location is not None:
        bridge.write_json_atomic(location,{'status':'available','identity':identity(config),
            'provider_host':urlsplit(config.embed_base_url).hostname,'model':config.embed_model,
            'updated_at':bridge.now_iso()})
