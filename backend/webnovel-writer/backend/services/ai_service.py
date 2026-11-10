 
"""AI 服务模块 - 对接 OpenAI 兼容 API"""

import os
import re
import json
import asyncio
import weakref
import httpx
import codecs
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlsplit, urlunsplit
from typing import Optional, List, Dict, Any
from pathlib import Path

from services.projects_manager import GLOBAL_CONFIG_DIR
from services.usage_meter import costs

# 默认 AI API 配置
DEFAULT_AI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_AI_API_KEY = ""
DEFAULT_AI_MODEL = "gpt-4"


class ToolsUnsupportedError(Exception):
    """当前 AI 供应商/模型不支持 function calling 时抛出，上层应降级。"""
    pass


class AIHTTPError(RuntimeError):
    SAFE_CODES = frozenset({'insufficient_quota','billing_hard_limit_reached','billing_not_active',
                            'invalid_api_key','account_deactivated','rate_limit_exceeded'})
    HARD_CODES = SAFE_CODES - {'rate_limit_exceeded'}

    def __init__(self,status,error_code=None):
        self.http_status=status
        self.error_code=error_code if error_code in self.SAFE_CODES else None
        self.retryable=False if self.error_code in self.HARD_CODES else status==429 or status>=500
        super().__init__(f'AI API returned HTTP {status}')


class AIOutputError(ValueError):
    """A paid response is not necessarily a complete, usable workflow result."""
    retryable = True
    failure_kind = 'model_output'


class AIService:
    """AI 服务封装"""

    def __init__(self, base_url: str = None, api_key: str = None, model: str = None):
        self.base_url = base_url or os.getenv("AI_BASE_URL", DEFAULT_AI_BASE_URL)
        self.api_key = os.getenv("AI_API_KEY", DEFAULT_AI_API_KEY) if api_key is None else api_key
        self.model = model or os.getenv("AI_MODEL", DEFAULT_AI_MODEL)
        self.timeout = 1800  # 3分钟超时
        self.reasoning_effort = None
        self.reasoning_setting = 'auto'
        self.provider_managed_tokens = False
        self._thinking_override=ContextVar('thinking_override',default=None)
        # “本次调用结果”必须按调用隔离：AIService 是进程级单例，多章节并发时
        # 共享属性会互相覆盖，导致把正常结束误判为截断（或反之）。
        self._meta_by_task = weakref.WeakKeyDictionary()
        self._meta_global = {"finish_reason": None, "content_chars": 0, "reasoning_chars": 0}
        self._finish_by_task = weakref.WeakKeyDictionary()
        self._finish_global = None

    def _current_task(self):
        try:
            return asyncio.current_task()
        except RuntimeError:
            return None

    @property
    def last_response_meta(self) -> Dict[str, Any]:
        task = self._current_task()
        if task is not None:
            try:
                return self._meta_by_task.get(task, self._meta_global)
            except TypeError:
                return self._meta_global
        return self._meta_global

    @last_response_meta.setter
    def last_response_meta(self, value: Dict[str, Any]) -> None:
        self._meta_global = value
        task = self._current_task()
        if task is not None:
            try:
                self._meta_by_task[task] = value
            except TypeError:
                pass

    @property
    def last_finish_reason(self):
        task = self._current_task()
        if task is not None:
            try:
                return self._finish_by_task.get(task, self._finish_global)
            except TypeError:
                return self._finish_global
        return self._finish_global

    @last_finish_reason.setter
    def last_finish_reason(self, value) -> None:
        self._finish_global = value
        task = self._current_task()
        if task is not None:
            try:
                self._finish_by_task[task] = value
            except TypeError:
                pass

    @contextmanager
    def without_thinking(self):
        supported=self.model.casefold().startswith('deepseek-v4') or self.model.casefold()=='deepseek-flash'
        token=self._thinking_override.set('disabled') if supported else None
        try:yield
        finally:
            if token is not None:self._thinking_override.reset(token)

    def _reasoning_options(self):
        # User settings take precedence over automatic stage recommendations.
        # Gateways accept OpenAI effort names and map their native levels.
        if self.reasoning_setting!='auto':
            native=self.model.casefold().split('/')[-1]
            local=urlsplit(self.base_url).hostname in {'127.0.0.1','localhost','::1'}
            if not local and (native.startswith('deepseek-') or native.startswith('glm-')):
                return {'thinking':{'type':'disabled'}} if self.reasoning_setting=='off' else {'thinking':{'type':'enabled'},'reasoning_effort':self.reasoning_setting}
            return {'reasoning_effort':'none' if self.reasoning_setting=='off' else self.reasoning_setting}
        if self.provider_managed_tokens:
            # Auto means the provider's default, not an implicit per-stage
            # low effort or a hidden without_thinking override.
            return {}
        if self._thinking_override.get()=='disabled':
            return {'thinking':{'type':'disabled'}}
        if self.reasoning_effort is None:
            return {}
        if self.reasoning_effort not in {'low','high','max'}:
            raise ValueError('Unsupported reasoning effort')
        return {'thinking':{'type':'enabled'}, 'reasoning_effort':self.reasoning_effort}

    def _debug_enabled(self) -> bool:
        flag = os.getenv("WEBNOVEL_DEBUG", "").strip().lower()
        return flag in {"1", "true", "yes", "on", "debug"}

    def _debug(self, message: str) -> None:
        if self._debug_enabled():
            print(message)

    def _endpoint_url(self, endpoint: str) -> str:
        parts = urlsplit(self.base_url.strip())
        path = parts.path.rstrip("/")
        for suffix in ("/chat/completions", "/models"):
            if path.endswith(suffix):
                path = path[:-len(suffix)]
                break
        if not path.endswith(("/v1", "/openai")):
            path += "/v1"
        return urlunsplit((parts.scheme, parts.netloc, f"{path}/{endpoint}", parts.query, ""))

    async def chat(self, messages: List[Dict], temperature: float = 0.7, max_tokens: int = 4000, response_format: str = None) -> str:
        """发送聊天请求 - 使用 aiohttp 提升稳定性"""
        import aiohttp
        
        # 智能处理 URL
        url = self._endpoint_url("chat/completions")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            **({} if self.provider_managed_tokens else {"max_tokens": max_tokens}),
            "stream": False
        }
        payload.update(self._reasoning_options())
        
        # 添加 response_format 参数（强制 JSON 输出）
        if response_format in {"json", "json_object"}:
            payload["response_format"] = {"type": "json_object"}

        self._debug(f"Applying AI Request (Model: {self.model})")
        
        max_retries = getattr(self, 'max_retries', 3)
        last_error = None
        
        for attempt in range(max_retries):
            meter = costs.Attempt(self.base_url,self.model,payload,attempt+1,secret=self.api_key)
            try:
                # 每次重试都创建新的 connector 和 session，确保连接干净
                connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
                timeout = aiohttp.ClientTimeout(total=self.timeout, connect=30, sock_read=self.timeout)
                # trust_env=True 允许使用系统代理，解决全球区域访问限制问题
                async with aiohttp.ClientSession(connector=connector, timeout=timeout, trust_env=True) as session:
                    async with session.post(url, json=payload, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            meter.observe(data)
                            choices = data.get("choices") if isinstance(data, dict) else None
                            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                                # 已付费但不可用的 200：不能原样重试（会重复计费），
                                # 也不能返回 None 让上层以为成功。
                                raise AIOutputError("provider returned no usable choices")
                            choice = choices[0]
                            message = choice.get('message') or {}
                            # Diagnostics only: never persist content, reasoning, or credentials.
                            self.last_response_meta = {
                                'finish_reason': choice.get('finish_reason'),
                                'content_chars': len(message.get('content') or ''),
                                'reasoning_chars': len(message.get('reasoning_content') or ''),
                            }
                            content = message.get('content')
                            meter.output(content or "")
                            if not isinstance(content, str) or not content.strip():
                                # reasoning 模型在 length/空回复时可能返回 null content
                                raise AIOutputError("provider returned empty content")
                            meter.completed = True
                            return content
                        else:
                            # Only an allowlisted machine code crosses this boundary;
                            # provider messages, payloads and credentials never do.
                            code=None
                            try:
                                error_data=await response.json(content_type=None)
                                error=error_data.get('error') if isinstance(error_data,dict) else None
                                if isinstance(error,dict):
                                    for candidate in (error.get('code'),error.get('type')):
                                        if isinstance(candidate,str) and candidate in AIHTTPError.SAFE_CODES:
                                            code=candidate;break
                            except (Exception,):
                                pass
                            print(f"AI Error {response.status}")
                            raise AIHTTPError(response.status,code)
            except Exception as e:
                if isinstance(e,AIHTTPError) and not e.retryable:
                    raise
                if isinstance(e, AIOutputError):
                    # 模型返回不可用内容属于确定性结果，重试只会重复付费；
                    # 交由上层决定是否升预算/换模型。
                    raise
                last_error = RuntimeError(f"AI request failed ({type(e).__name__})")
                detail = str(e)
                if self.api_key:
                    detail = detail.replace(self.api_key, "[redacted]")
                print(f"AI Request Failed (attempt {attempt + 1}/{max_retries}): {type(e).__name__}: {detail[:300]}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(3 + attempt * 2)  # 递增等待：3s, 5s
                    continue
                raise last_error from e
            finally:
                meter.finish()


    async def chat_with_tools(
        self,
        messages: List[Dict],
        tools: List[Dict],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        """带 function calling 的单轮请求（agent 侦查阶段专用）。

        返回 {"content": str, "tool_calls": [{"id","name","arguments"(dict)}]}。
        供应商不支持 tools 时抛 ToolsUnsupportedError，由上层降级为预打包模式。
        """
        import aiohttp

        url = self._endpoint_url("chat/completions")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            **({} if self.provider_managed_tokens else {"max_tokens": max_tokens}),
            "stream": False,
            "tools": tools,
            "tool_choice": "auto",
        }
        payload.update(self._reasoning_options())

        self._debug(f"AI Tools Request (Model: {self.model}, tools={len(tools)})")

        max_retries = getattr(self, 'max_retries', 2)
        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            meter = costs.Attempt(self.base_url,self.model,payload,attempt+1,secret=self.api_key)
            try:
                connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
                timeout = aiohttp.ClientTimeout(total=300, connect=30, sock_read=300)
                async with aiohttp.ClientSession(connector=connector, timeout=timeout, trust_env=True) as session:
                    async with session.post(url, json=payload, headers=headers) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            # 供应商不支持 tools：典型为 400 且报错提到 tools/functions
                            lowered = error_text.lower()
                            if response.status in (400, 404, 422) and (
                                "tool" in lowered or "function" in lowered
                            ):
                                raise ToolsUnsupportedError(
                                    f"Provider rejected tools (HTTP {response.status})"
                                )
                            raise Exception(f"AI API returned {response.status}")

                        data = await response.json()
                        meter.observe(data)
                        choices = data.get("choices") if isinstance(data, dict) else None
                        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                            raise AIOutputError("tools response returned no usable choices")
                        choice = choices[0]
                        message = choice.get("message", {}) or {}
                        self.last_response_meta = {
                            'finish_reason': choice.get('finish_reason'),
                            'content_chars': len(message.get('content') or ''),
                            'reasoning_chars': len(message.get('reasoning_content') or ''),
                        }
                        meter.output(message)
                        meter.completed = True
                        raw_calls = message.get("tool_calls") or []
                        tool_calls = []
                        for tc in raw_calls:
                            fn = tc.get("function", {}) or {}
                            try:
                                args = json.loads(fn.get("arguments") or "{}")
                            except json.JSONDecodeError:
                                args = {}
                            tool_calls.append({
                                "id": tc.get("id") or f"call_{len(tool_calls)}",
                                "name": fn.get("name", ""),
                                "arguments": args,
                            })
                        return {
                            "content": message.get("content") or "",
                            "tool_calls": tool_calls,
                        }
            except ToolsUnsupportedError:
                raise
            except AIOutputError:
                raise
            except Exception as e:
                last_error = RuntimeError(f"AI tools request failed ({type(e).__name__})")
                print(f"AI Tools Request Failed (attempt {attempt + 1}/{max_retries}): {type(e).__name__}")
                if attempt < max_retries - 1:
                    import asyncio
                    await asyncio.sleep(2)
                    continue
                raise last_error
            finally:
                meter.finish()


    async def chat_stream(self, messages: List[Dict], temperature: float = 0.7, max_tokens: int = 16000):
        """流式发送聊天请求"""
        import aiohttp
        
        url = self._endpoint_url("chat/completions")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/event-stream"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            
        # 本次流式调用的结束原因（"stop"=自然结束，"length"=被 max_tokens 截断）。
        # 调用方在流结束后读取，用于识别截断并自动续写。
        self.last_finish_reason = None
        # 断线续传：流中途断开时，把已收到内容作 assistant 上下文回传续写（最多 2 轮），
        # 避免「已输出一半 → 整段重发重复 / 直接报错丢内容」。

        self._debug(f"Applying AI Stream Request (Model: {self.model})")
        # 调试：打印请求消息的长度和摘要
        try:
            msg_preview = json.dumps(messages, ensure_ascii=False)[:500]
            self._debug(f"Request Messages Preview: {msg_preview}...")
            self._debug(f"Total Messages count: {len(messages)}")
        except:
            pass
        
        max_retries = getattr(self, 'max_retries', 3)
        resume_rounds = 0
        current_messages = messages
        accumulated = ""
        request_usage = True
        usage_negotiated = False
        for attempt in range(max_retries + 1):
            if attempt >= max_retries and not usage_negotiated:
                break
            payload = {
                "model": self.model,
                "messages": current_messages,
                "temperature": temperature,
                **({} if self.provider_managed_tokens else {"max_tokens": max_tokens}),
                "stream": True
            }
            payload.update(self._reasoning_options())
            if request_usage:
                payload["stream_options"] = {"include_usage":True}
            meter = costs.Attempt(self.base_url,self.model,payload,attempt+1,secret=self.api_key)
            try:
                connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
                timeout = aiohttp.ClientTimeout(total=self.timeout, connect=30, sock_read=300)
                # trust_env=True 允许使用系统代理
                async with aiohttp.ClientSession(connector=connector, timeout=timeout, trust_env=True) as session:
                    async with session.post(url, json=payload, headers=headers) as response:
                        self._debug(f"AI Stream Response Status: {response.status}")
                        self._debug(f"AI Stream Content-Type: {response.headers.get('Content-Type', 'unknown')}")
                        
                        if response.status != 200:
                            error_text = await response.text()
                            if response.status in (400,422) and request_usage and ("stream_options" in error_text or "include_usage" in error_text):
                                request_usage=False
                                usage_negotiated=True  # At most one protocol negotiation, never another generation retry.
                                continue
                            print(f"AI Stream Error (attempt {attempt + 1}/{max_retries}): {response.status}")
                            # 429/5xx 属于服务商临时性错误，退避后重试；4xx 配置类错误直接报出
                            if response.status in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                                import asyncio
                                await asyncio.sleep(3 + attempt * 3)
                                continue
                            yield f"[ERROR] AI API returned {response.status}"
                            return

                        content_type = response.headers.get('Content-Type', '')
                        
                        # 如果返回的是 JSON 而不是 SSE，直接解析
                        if 'application/json' in content_type:
                            self._debug("AI returned JSON instead of SSE, parsing as single response")
                            raw_text = await response.text()
                            try:
                                data = json.loads(raw_text)
                                meter.observe(data)
                                if "choices" in data and len(data["choices"]) > 0:
                                    self.last_finish_reason = data["choices"][0].get("finish_reason") or self.last_finish_reason
                                    content = data["choices"][0].get("message", {}).get("content", "")
                                    if content:
                                        meter.output(content)
                                        meter.completed=True
                                        accumulated += content
                                        yield content
                                        self._debug(f"AI JSON response length: {len(content)}")
                                        return
                            except json.JSONDecodeError as e:
                                print(f"Failed to parse JSON response: {e}")
                                yield f"[ERROR] Failed to parse AI response"
                                return
                            # 供应商返回 JSON 且 content 为空/缺 choices：不能继续按 SSE
                            # 迭代已消费的响应体（会静默产出空章节），必须显式报错。
                            yield "[ERROR] AI returned JSON response without usable content"
                            return
                         
                        # SSE 流式处理 - 使用 buffer 累积并按行分割
                        chunk_count = 0
                        buffer = ""
                        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                        self._debug("Starting SSE stream reading...")
                        
                        async for chunk in response.content.iter_any():
                            raw_chunk = decoder.decode(chunk)
                            # 调试：打印原始数据块的前50个字符
                            self._debug(f"Raw chunk received ({len(raw_chunk)}): {raw_chunk[:100]}...")
                            buffer += raw_chunk
                            
                            # 按行分割处理
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                line = line.strip()
                                
                                if not line:
                                    continue
                                if line.startswith('data:') and line[5:].strip() == '[DONE]':
                                    meter.completed=True
                                    self._debug(f"AI Stream completed, total chunks: {chunk_count}")
                                    return
                                
                                if line.startswith("data:"):
                                    try:
                                        data = json.loads(line[5:].lstrip())
                                        meter.observe(data)
                                        if isinstance(data.get('error'),dict):
                                            failure=data['error'];status=failure.get('status')
                                            raise AIHTTPError(status if type(status) is int and 400<=status<600 else 502,failure.get('code'))
                                        if "choices" in data and len(data["choices"]) > 0:
                                            fr = data["choices"][0].get("finish_reason")
                                            if fr:
                                                self.last_finish_reason = fr
                                            delta = data["choices"][0].get("delta", {})
                                            if "content" in delta:
                                                chunk_count += 1
                                                if chunk_count == 1:
                                                    self._debug("First SSE chunk received!")
                                                piece = delta["content"] or ""
                                                meter.output(piece)
                                                accumulated += piece
                                                yield piece
                                    except json.JSONDecodeError:
                                        continue

                        # 某些网关可能在最后一个 data 行后不补换行；补一次 flush，避免丢失尾块导致“半句截断”。
                        buffer += decoder.decode(b"", final=True)
                        if buffer.strip():
                            buffer += "\n"
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                line = line.strip()

                                if not line:
                                    continue
                                if line.startswith('data:') and line[5:].strip() == '[DONE]':
                                    meter.completed=True
                                    self._debug(f"AI Stream completed (tail flush), total chunks: {chunk_count}")
                                    return

                                if line.startswith("data:"):
                                    try:
                                        data = json.loads(line[5:].lstrip())
                                        meter.observe(data)
                                        if isinstance(data.get('error'),dict):
                                            failure=data['error'];status=failure.get('status')
                                            raise AIHTTPError(status if type(status) is int and 400<=status<600 else 502,failure.get('code'))
                                        if "choices" in data and len(data["choices"]) > 0:
                                            fr = data["choices"][0].get("finish_reason")
                                            if fr:
                                                self.last_finish_reason = fr
                                            delta = data["choices"][0].get("delta", {})
                                            if "content" in delta:
                                                chunk_count += 1
                                                if chunk_count == 1:
                                                    self._debug("First SSE chunk received (tail flush)!")
                                                piece = delta["content"] or ""
                                                meter.output(piece)
                                                accumulated += piece
                                                yield piece
                                    except json.JSONDecodeError:
                                        continue
                        
                        meter.completed=True
                        self._debug(f"AI Stream ended, total chunks: {chunk_count}")
                        return
            except AIHTTPError:
                # A gateway may emit an error frame after HTTP 200. Preserve
                # its safe status/code; never log the upstream body or retry
                # permanent authentication/quota failures as empty prose.
                raise
            except Exception as e:
                print(f"AI Stream Request Failed (attempt {attempt + 1}/{max_retries}): {type(e).__name__}")
                if attempt < max_retries - 1:
                    import asyncio
                    await asyncio.sleep(3 + attempt * 2)
                    if accumulated and resume_rounds < 2:
                        # 断点续传：已输出部分内容时，带上下文续写而不是整段重发
                        resume_rounds += 1
                        self._debug(f"Stream dropped mid-response, resuming (round {resume_rounds}), got {len(accumulated)} chars")
                        current_messages = list(messages) + [
                            {"role": "assistant", "content": accumulated},
                            {"role": "user", "content": (
                                "你的上一条回复因网络中断被截断。请从中断处无缝继续输出剩余内容"
                                "（若最后一句不完整先补完该句），禁止重复已输出内容，禁止任何前言或解释。"
                            )},
                        ]
                    continue
                yield f"[ERROR] 连接中断且重试失败: {type(e).__name__}"
            finally:
                meter.finish()




    async def list_models(self) -> List[str]:
        """获取可用模型列表"""
        url = self._endpoint_url("models")

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            proxy_url = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY") or None
            async with httpx.AsyncClient(timeout=10, follow_redirects=True, proxy=proxy_url) as client:
                response = await client.get(url, headers=headers)
                if response.status_code != 200:
                    raise RuntimeError(f"模型列表请求失败 (HTTP {response.status_code})")

                data = response.json()
                if "data" in data and isinstance(data["data"], list):
                    return [m["id"] for m in data["data"]]
                return [self.model]
        except Exception as e:
            print(f"Error fetching models: {type(e).__name__}")
            raise RuntimeError("无法获取模型列表，请检查 AI 配置和连接") from None

    async def write_chapter(
        self,
        chapter_num: int,
        chapter_outline: str,
        previous_summary: str = "",
        characters: List[str] = None,
        settings: str = "",
        word_count: int = 4000
    ) -> str:
        """AI 写作章节"""
        system_prompt = f"""你是一位专业的网文作者。请根据大纲和上下文，创作精彩的章节内容。

写作要求：
1. 字数：{word_count} 字左右
2. 风格：节奏紧凑、对话生动、描写细腻
3. 结构：开头引人入胜、中间层层推进、结尾留有悬念
4. 遵循大纲设定，不要擅自发挥
5. 保持与前文的一致性"""

        context = f"""## 第 {chapter_num} 章大纲
{chapter_outline}

## 前情摘要
{previous_summary or '（这是第一章，无前情）'}

## 出场角色
{', '.join(characters) if characters else '（根据大纲安排）'}

## 世界观设定
{settings or '（使用默认设定）'}

请开始创作第 {chapter_num} 章正文："""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context}
        ]

        return await self.chat(messages, temperature=0.7, max_tokens=8000)

    async def review_chapter(self, content: str, previous_context: str = "", chapter_outline: str = "") -> Dict[str, Any]:
        """审查章节质量（含上下文重复性检查与大纲一致性检查）"""
        system_prompt = """你是一位“找茬”专家的网文主编，专门负责揪出正文与大纲不符的错误。你的审核标准极度严苛，绝不容忍任何设定偏差。

        【审核核心任务】
        请对比【本章大纲】与【正文内容】，重点检查以下几点：
        1. **专有名词一致性**：大纲里的宗门、地名、人名、物品名，正文必须完全一致。
           - 例子：大纲写“落云宗”，正文写“流云宗” -> ❌ 严重错误！
           - 例子：大纲写“万剑窟”，正文写“矿山” -> ❌ 严重错误！
        2. **核心剧情一致性**：大纲规定的核心冲突起因、经过、结果，正文是否篡改？

        【评分规则】
        1. **Consistency (一致性)**：初始 100 分。发现 1 个名词错误扣 20 分；发现 1 个剧情篡改扣 30 分。必须严格！
        2. **High Point (爽点)**：评估剧情是否能调动情绪（期待感、震惊、满足感）。无爽点=0-40，平淡=41-60，有亮点=61-80，极爽=81-100。
        3. **Pacing (节奏)**：评估剧情推进速度。太拖沓或太赶=0-50，正常=60-80，起伏有致=81-100。
        4. **OOC (人设)**：人物行为是否符合性格。严重崩坏=0-50，符合=60-100。
        5. **Continuity (连贯性)**：场景切换是否自然。

        【返回格式（JSON）】
        {
          "comparison_log": {
             "outline_entities": ["大纲名词1", "大纲名词2"],
             "content_entities": ["正文名词1", "正文名词2"],
             "mismatch_found": true/false
          },
          "scores": {
              "high_point": 85, 
              "consistency": 95, 
              "pacing": 70, 
              "ooc": 90, 
              "continuity": 88
          },
          "issues": [
             "❌ 宗门名称错误：大纲为[落云宗]，正文写成了[流云宗]",
             "⚠️ 节奏建议：开篇说明文略多"
          ],
          "suggestions": ["建议1", "建议2"],
          "summary": "简短评价"
        }"""

        user_content = f"请审查以下章节：\n\n{content}"
        
        context_info = []
        if chapter_outline:
            context_info.append(f"【本章大纲（用于检查剧情一致性）】\n{chapter_outline}")
        if previous_context:
            context_info.append(f"【上一章结尾（用于检查衔接与重复）】\n{previous_context}\n\n【特别注意】请仔细检查新章节开头是否机械复述了上一章结尾。")
            
        if context_info:
            user_content = "\n\n".join(context_info) + "\n\n" + user_content

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        result = await self.chat(messages, temperature=0.3, max_tokens=2000)

        # 尝试解析 JSON
        try:
            # 提取 JSON 部分
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return json.loads(result.strip())
        except Exception:
            return {
                "scores": {"high_point": 0, "consistency": 0, "pacing": 0, "ooc": 0, "continuity": 0},
                "issues": ["无法解析审查结果"],
                "suggestions": [],
                "summary": result
            }

    async def generate_titles(self, genre: str, outline: str) -> List[str]:
        """根据大纲生成书名"""
        system_prompt = f"""你是一位深谙网文市场规律的金牌主编，擅长打造爆款书名。
请根据大纲，为这部{genre}小说起 8 个极具吸引力、充满噱头和点击欲望的书名。

【起名核心法则】
1. **突出核心卖点**：必须一秒展示金手指、极致反差或核心爽点。
2. **拒绝平庸**：不要“xx传”、“xx记”这种古早文名，要“开局...”、“我...”、夸张对比。
3. **情绪调动**：利用震惊、好奇、贪婪（金手指）、优越感（无敌）等情绪。
4. **流派定制**：
   - 修仙/玄幻：要霸气宏大或极致苟道/稳健（如《我有一剑...》《开局签到...》）。
   - 都市/系统：要直白爽快，突出身份反差或系统功能（如《让你...没让你...》《校花...》）。
   - 悬疑/惊悚：要细思恐极或规则怪谈感。

【输出要求】
1. 只输出书名，每行一个。
2. 不要有任何解释或序号。
3. 必须生成 8 个。
4. **字数限制**：严格控制在 15 个字以内，短小精悍。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"【小说大纲】\n{outline[:3000]}"}
        ]

        content = await self.chat(messages, temperature=0.8, max_tokens=200)
        
        # 清洗数据
        titles = []
        for line in content.split("\n"):
            line = line.strip()
            # 去除序号 (1. xxx)
            line = re.sub(r"^\d+[\.、\s]*", "", line)
            # 去除书名号
            line = line.replace("《", "").replace("》", "")
            if line:
                titles.append(line)
        
        return titles[:8]

    async def polish_chapter(self, content: str, suggestions: List[str] = None) -> str:
        """AI 润色章节"""
        system_prompt = """你是一位专业的网文主编。请根据改进建议，对用户提供的章节内容进行润色和重写。

要求：
1. **严格遵循改进建议**：针对性地解决提出的问题（如节奏、爽点、人设等）。
2. **提升文笔**：优化描写，增强代入感，使用 show-don't-tell 手法。
3. **保持原意**：不要随意更改核心剧情走向，除非建议中明确要求。
4. **输出完整正文**：直接输出润色后的内容，不要包含“好的”、“这是润色后的版本”等废话。"""

        user_prompt = f"""请润色以下章节内容：

【改进建议】
{chr(10).join([f"- {s}" for s in suggestions]) if suggestions else "- 请全面提升文笔，增强画面感和代入感。"}

【原文】
{content}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        return await self.chat(messages, temperature=0.7, max_tokens=8000)

    async def generate_chapter_summary(self, content: str) -> str:
        """生成章节摘要"""
        messages = [
            {"role": "system", "content": "请用 100-200 字概括以下章节的主要情节，用于后续章节的上下文参考。"},
            {"role": "user", "content": content}
        ]
        return await self.chat(messages, temperature=0.3, max_tokens=500)



CONFIG_FILE = GLOBAL_CONFIG_DIR / "ai_config.json"

def _load_config_from_file() -> Dict[str, str]:
    """从文件加载 AI 配置"""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Warning: Failed to load AI config: {e}")
    return {}

def _save_config_to_file(config: Dict[str, str]):
    """保存 AI 配置到文件"""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        raise RuntimeError("无法保存 AI 配置") from None

# 全局实例
_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None:
        # 1. 尝试从文件加载
        file_config = _load_config_from_file()
        
        # 2. 环境变量覆盖（可选）
        base_url = file_config.get("base_url") or os.getenv("AI_BASE_URL", DEFAULT_AI_BASE_URL)
        api_key = file_config.get("api_key", os.getenv("AI_API_KEY", DEFAULT_AI_API_KEY))
        model = file_config.get("model") or os.getenv("AI_MODEL", DEFAULT_AI_MODEL)
        
        _ai_service = AIService(base_url, api_key, model)
        _ai_service.provider_managed_tokens = file_config.get('resource_policy',{}).get('provider_managed_tokens',False) is True
    return _ai_service


def configure_ai_service(base_url: str = None, api_key: str = None, model: str = None):
    global _ai_service

    # 合并保存（保留 agent_mode 等其他配置项）；省略的参数表示“保持不变”，
    # 不能被重置成 OpenAI 官方地址/gpt-4（否则只改模型也会把全系统指错接口）。
    config_data = _load_config_from_file()
    if base_url is None:
        resolved_base = config_data.get("base_url") or get_ai_service().base_url
    else:
        resolved_base = base_url
    if model is None:
        resolved_model = config_data.get("model") or get_ai_service().model
    else:
        resolved_model = model
    config_data.update({
        "base_url": resolved_base or DEFAULT_AI_BASE_URL,
        "api_key": get_ai_service().api_key if api_key is None else api_key,
        "model": resolved_model or DEFAULT_AI_MODEL,
    })
    _save_config_to_file(config_data)

    # 更新内存实例
    _ai_service = AIService(config_data["base_url"], config_data["api_key"], config_data["model"])
    _ai_service.provider_managed_tokens = config_data.get('resource_policy',{}).get('provider_managed_tokens',False) is True


def get_agent_mode() -> bool:
    """写手 Agent 模式开关（默认开启；调用失败会自动降级，因此默认开是安全的）。"""
    cfg = _load_config_from_file()
    val = cfg.get("agent_mode")
    if val is None:
        return True
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return bool(val)


def set_agent_mode(enabled: bool) -> None:
    cfg = _load_config_from_file()
    cfg["agent_mode"] = bool(enabled)
    _save_config_to_file(cfg)
