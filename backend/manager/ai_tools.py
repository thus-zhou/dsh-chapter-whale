"""Bounded, credential-safe model discovery and per-book creative conversation."""
import asyncio
import json
import os
import time
from urllib.parse import urlsplit
import httpx
from integration import writer_runner
from integration import model_roles
from integration import costs


def services():
    writer_runner._load_webnovel_services()
    from services.ai_service import AIService
    from services import creative_brief
    return AIService, creative_brief


def validate_url(value):
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("请填写合法 API 基础地址，不要在 URL 中放密钥或查询参数")
    if parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("远程接口必须使用 HTTPS，避免明文传输密钥；本机接口可用 HTTP")
    try:
        parts.port
    except ValueError as exc:
        raise ValueError("API 地址端口不合法") from exc
    return value


def resolved_key(base_url, key, saved):
    if key and key.strip():
        return key.strip()
    previous = saved.get("base_url", "https://api.openai.com/v1")
    if validate_url(previous) != base_url:
        raise ValueError("接口地址已改变，请填写该接口的密钥；不会将旧密钥发送给新地址")
    return saved.get("api_key") or os.getenv("AI_API_KEY", "")


def _targets_private_network(host: str) -> bool:
    """解析主机名，判断是否指向内网/本机/链路本地/云元数据地址。"""
    import ipaddress
    import socket

    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not address.is_global:
            return True
        # 云元数据/链路本地常见地址（部分实现下 is_global 仍为 False，兜底明确判断）
        if str(address).startswith("169.254."):
            return True
    return False


def _local_proxy_fake_ip(host):
    """Recognize only the benchmark Fake-IP range via a loopback proxy.

    Used for explicitly saved providers, never arbitrary discovery form URLs.
    The HTTPS request still validates the original hostname's certificate.
    """
    import ipaddress
    import socket
    from urllib.request import getproxies
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:pass
    proxy=urlsplit(getproxies().get('https',''))
    if proxy.scheme not in {'http','https'} or proxy.hostname not in {'127.0.0.1','localhost','::1'}:return False
    try:
        addresses={ipaddress.ip_address(x[4][0]) for x in socket.getaddrinfo(host,443)}
        block=ipaddress.ip_network('198.18.0.0/15')
        return bool(addresses) and all(x in block for x in addresses)
    except (ValueError,OSError):return False


def _assert_no_ssrf(base_url: str, registered=False) -> None:
    """阻止“读取模型列表”被用来探测内网/本机服务（SSRF）。

    远程接口本来要求 HTTPS 公网主机；如需内网自建网关，可由运维显式设置
    NOVEL_HELPER_ALLOW_PRIVATE_AI=1 放行。
    """
    if os.getenv("NOVEL_HELPER_ALLOW_PRIVATE_AI", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    parts = urlsplit(base_url)
    if parts.scheme == "http":
        return  # 仅允许 localhost/127.0.0.1，已由 validate_url 限制
    hostname = (parts.hostname or "").lower()
    # 测试/文档保留域名不是真实可路由目标，放行以便离线测试。
    if hostname in {"localhost", "testserver"} or hostname.endswith((".test", ".invalid", ".example", ".localhost")):
        return
    if hostname and _targets_private_network(hostname):
        if registered and parts.scheme=='https' and _local_proxy_fake_ip(hostname):return
        raise ValueError("模型接口地址不能指向内网/本机地址；如确需内网网关，请设置 NOVEL_HELPER_ALLOW_PRIVATE_AI=1")


def discover(base_url, key, saved, registered=False):
    base_url = validate_url(base_url)
    _assert_no_ssrf(base_url,registered=registered)
    secret = resolved_key(base_url, key, saved)
    AIService, _ = services()
    endpoint = AIService(base_url=base_url, api_key=secret, model="discovery")._endpoint_url("models")
    headers = {"Accept": "application/json"}
    if secret:
        headers["Authorization"] = "Bearer " + secret
    try:
        deadline = time.monotonic() + 20
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=True) as client:
            with client.stream("GET", endpoint, headers=headers) as response:
                status = response.status_code
                if status != 200:
                    reasons = {401:"密钥无效或未授权",403:"账号没有读取模型列表的权限",404:"接口未提供模型列表，可手动填写模型 ID",429:"请求过于频繁，请稍后重试"}
                    raise ValueError(reasons.get(status, f"读取模型列表失败（HTTP {status}）；请检查接口，或手动输入模型 ID"))
                body = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() >= deadline:
                        raise ValueError("读取模型列表超时，可稍后重试或手动填写模型 ID")
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise ValueError("模型列表响应过大，已停止读取")
        payload = json.loads(body)
    except httpx.TimeoutException as exc:
        raise ValueError("读取模型列表超时，请检查网络或手动填写模型 ID") from exc
    except httpx.HTTPError as exc:
        raise ValueError("无法连接模型接口，请检查网络、TLS 或代理") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("接口返回的不是有效模型列表 JSON，可手动填写模型 ID") from exc
    entries = payload.get("data", payload.get("models")) if isinstance(payload, dict) else payload
    if not isinstance(entries, list) or len(entries) > 10000:
        raise ValueError("接口返回的模型列表格式不支持，可手动填写模型 ID")
    ids = set()
    for entry in entries:
        identity = entry.get("id") if isinstance(entry, dict) else entry
        if isinstance(identity, str) and identity.strip() and len(identity) <= 200 and not any(ord(c) < 32 for c in identity):
            # Never echo a provider response that accidentally contains the key.
            if secret and secret in identity:
                continue
            ids.add(identity.strip())
    return {"models": sorted(ids, key=str.casefold), "count": len(ids),
            "message": "列表由当前接口返回；列出不代表支持小说写作，请选择文本对话模型并测试连接。" if ids else "接口未返回模型，可手动填写模型 ID。"}


@costs.attributed("conversation",project="project",role="E")
def converse(project, title, message, saved, revision):
    AIService, brief_service = services()
    # Sync route holds this process/thread + OS lock for a bounded API call.
    # Two chats or a save cannot silently overwrite each other's history.
    with writer_runner.file_lock(project / ".webnovel" / "creative.lock"):
        doc = brief_service.read_document(project)
        if revision != doc["revision"]:
            raise ValueError("创作约定已被更新，请重新载入后继续沟通")
        selected=model_roles.connection("E",saved)
        base_url,key=selected["base_url"],selected["api_key"]
        message = message.replace(key, "[redacted]")
        chapter = writer_runner.next_chapter_id(project)
        outline = writer_runner._find_outline(project, chapter)[:4000]
        prompt = (f"你是作者的小说策划搭档。作品：{title}。请使用中文，帮助作者明确小说具体怎么写；"
            "先澄清缺失或矛盾的要求，每轮最多问三个关键问题，可给出具体选项。"
            "可以讨论题材、文风、人物、世界观、视角、节奏、读者、主线和结局。"
            "不要输出整章正文，不声称已修改文件、发布或一定赚钱。只在理解足够清楚时提出创作约定建议。"
            "作者已确认的要求如下：\n" + brief_service.render_brief(doc["brief"]) +
            f"\n下一章为第{chapter}章，已有章节大纲（仅参考，不得声称已改写）：\n{outline or '尚无章节大纲'}\n" +
            "\n严格返回 JSON 对象：{\"reply\":\"给作者的自然语言回复\",\"proposal\":{}}。"
            "proposal 是可选的部分修改建议，仅使用以下字段，值必须是字符串，未改变字段不要包含：" +
            json.dumps(brief_service.FIELDS, ensure_ascii=False) +
            "。建议只有作者点击采用后才生效；不得将聊天中的未确认建议说成已生效。")
        recent = []
        from integration import memory_library
        prompt += "\n" + memory_library.context(project,"E",chapter,message)["text"]
        total = 0
        for item in reversed(doc["history"][-12:]):
            if total + len(item["content"]) > 18000:
                break
            recent.insert(0, {"role": item["role"], "content": item["content"]})
            total += len(item["content"])
        ai = model_roles.service('E',saved) if saved.get('provider_schema')==1 else AIService(**selected)
        ai.timeout = 25
        try:
            raw = asyncio.run(asyncio.wait_for(ai.chat([{"role":"system","content":prompt}, *recent,
                {"role":"user","content":message}], temperature=0.6, max_tokens=2200), timeout=35))
        except Exception as exc:
            raise ValueError("AI 沟通失败或超时；请检查已保存的模型连接，原有约定与对话未改变") from exc
        raw = str(raw or "").strip()
        if not raw or raw.startswith("[ERROR]"):
            raise ValueError("AI 没有返回有效回复，原有约定未改变")
        # Defense against accidental credential echo in an external response.
        raw = raw.replace(key, "[redacted]")
        proposal = {}
        try:
            parsed = json.loads(raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip())
            reply = parsed.get("reply", "")
            if not isinstance(reply, str) or not reply.strip():
                raise ValueError()
            suggested = parsed.get("proposal", {})
            if suggested:
                normalized = brief_service.validate_brief(suggested)
                proposal = {k:normalized[k] for k in suggested}
                brief_service.validate_brief({**doc["brief"], **proposal})
        except (ValueError, TypeError, AttributeError):
            reply, proposal = raw, {}
        reply = reply[:12000]
        doc["history"] = [*doc["history"], {"role":"user","content":message},
            {"role":"assistant","content":reply,"proposal":proposal}][-40:]
        doc["revision"] += 1
        writer_runner.atomic_json(project / ".webnovel" / "creative_brief.json", doc)
        return {**doc, "reply":reply, "proposal":proposal}
