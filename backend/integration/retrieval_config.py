"""Project-specific embedding connection referencing an existing role secret."""
import hashlib
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from . import model_roles as roles, writer_runner as writer


def _endpoint_base(url: str) -> str:
    """归一化接口地址，避免 /v1、/chat/completions 等写法差异导致误判“地址已改变”。"""
    parts = urlsplit(str(url).strip().rstrip("/"))
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions", "/embeddings", "/models", "/rerank"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    if not path.endswith(("/v1", "/openai")):
        path += "/v1"
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if parts.port:
        host += f":{parts.port}"
    return urlunsplit((parts.scheme, host, path, "", ""))


def apply(config):
    path=Path(config.project_root)/'.webnovel'/'retrieval_config.json'
    if not path.exists():return
    value=writer.strict_json(path,{})
    if not isinstance(value,dict):
        raise ValueError('本书向量接口配置必须是 JSON 对象')
    role=value.get('source_role');model=value.get('model')
    if role not in roles.ROLES or not isinstance(model,str) or not model.strip():
        raise ValueError('本书向量接口配置无效')
    connection=roles.connection(role,roles.load_config())
    # Never reuse a saved role key when its configured provider has changed.
    if _endpoint_base(connection['base_url'])!=_endpoint_base(str(value.get('base_url',''))):
        raise ValueError('向量接口来源地址已改变，请重新确认，未发送旧密钥')
    config.embed_base_url=connection['base_url']
    config.embed_api_key=connection['api_key']
    config.embed_model=model.strip()
    config.embed_api_type='openai'
    config.rerank_api_type='embedding'
    config._novel_namespace=hashlib.sha256((config.embed_base_url+'\n'+config.embed_model).encode()).hexdigest()[:16]
