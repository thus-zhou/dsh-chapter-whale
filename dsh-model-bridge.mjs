import { createServer } from 'node:http';
import { randomBytes, timingSafeEqual } from 'node:crypto';

const PREFIX = '/chapter-whale-host/v1';
const NAME = 'DSH 模型';
const json = (res, status, value) => {
  res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' });
  res.end(JSON.stringify(value));
};

/**
 * P04 bounds. A response is buffered until its terminal frame is known, so every
 * retained string is charged to one counter measured in **UTF-16 code units**
 * (`String.prototype.length`, not bytes): each text delta, each reasoning delta,
 * and every tool call's name + argument delta. The counter only grows, so it equals
 * the resident text at all times; 16 Mi code units ≈ 32 MiB of UTF-8 payload in the
 * worst case (2 bytes per unit). Crossing the cap aborts the provider call and the
 * buffered draft is discarded — never written as a chapter.
 */
const MAX_RESPONSE_CHARS = 16 * 1024 * 1024;
/** No delta at all for this long means the provider is wedged: abort. Covers prepareCall. */
const FIRST_CHUNK_MS = 120_000;
/** Hard wall clock for the whole call (prepareCall + stream iteration + terminal write). */
const TOTAL_MS = 900_000;
const HEARTBEAT_MS = 10_000;
/** After the terminal frame, how long trailing usage chunks are still honoured (ms). */
const TRAILING_USAGE_MS = 2_000;

const positive = (value, fallback) => (Number.isFinite(value) && value > 0 ? Math.trunc(value) : fallback);

/**
 * Host contract (dsh-llm `src/types.ts` `TokenUsage`, lines 174-196 of the asar bundle):
 * "Counts are DISJOINT: `inputTokens` is uncached input only; cached input is reported
 * separately as `cacheReadTokens`/`cacheWriteTokens` (billed input = sum of the three)."
 * `totalTokens` is optional and "adapters omit it when unavailable or inconsistent".
 *
 * So the OpenAI-shaped view must ADD the cache components exactly once, and
 * `cached_tokens` is a subset of `prompt_tokens` (OpenAI semantics). Missing optional
 * components stay absent instead of being invented as 0; invalid (NaN/Infinity/negative)
 * numbers are dropped rather than serialized as null.
 */
const count = (value) => (typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : undefined);

function contractUsage(usage) {
  if (!usage || typeof usage !== 'object') return undefined;
  const input = count(usage.inputTokens);
  const output = count(usage.outputTokens);
  const cacheRead = count(usage.cacheReadTokens);
  const cacheWrite = count(usage.cacheWriteTokens);
  const total = count(usage.totalTokens);
  if (input === undefined && output === undefined) return undefined;
  const value = {};
  if (input !== undefined) value.prompt_tokens = input + (cacheRead || 0) + (cacheWrite || 0);
  if (output !== undefined) value.completion_tokens = output;
  if (total !== undefined) value.total_tokens = total;
  if (cacheRead !== undefined || cacheWrite !== undefined) {
    value.prompt_tokens_details = { cached_tokens: cacheRead || 0 };
    if (cacheWrite !== undefined) value.prompt_tokens_details.cache_write_tokens = cacheWrite;
  }
  value.x_usage = { source: input === undefined || output === undefined ? 'partial' : 'reported', input_excludes_cache: true };
  return value;
}

/** Credentials remain inside the owning DSH adapter. This token only gates loopback. */
export class DshModelBridge {
  constructor(ctx, options = {}) {
    this.ctx = ctx;
    this.catalog = new Map();
    this.errors = [];
    this.token = randomBytes(32).toString('base64url');
    this.calls = new Set();
    /** Injectable so tests can prove bounds/timeouts without waiting minutes. */
    this.limits = {
      maxChars: positive(options.maxChars, MAX_RESPONSE_CHARS),
      firstChunkMs: positive(options.firstChunkMs, FIRST_CHUNK_MS),
      totalMs: positive(options.totalMs, TOTAL_MS),
      heartbeatMs: positive(options.heartbeatMs, HEARTBEAT_MS),
    };
    /** Live heartbeat handle; null whenever no stream is waiting (tests assert this). */
    this.heartbeat = null;
    this.server = createServer((req, res) => this.handle(req, res));
    this.ready = new Promise((resolve, reject) => {
      this.server.once('error', reject);
      this.server.listen(0, '127.0.0.1', () => {
        this.url = `http://127.0.0.1:${this.server.address().port}${PREFIX}`;
        this.server.unref();
        resolve();
      });
    });
    // Injection can disappear before the first UI request consumes ready.
    this.ready.catch(() => {});
  }

  async refresh() {
    const catalog = new Map();
    const errors = [];
    await Promise.all(this.ctx.llm.listProviders().map(async (provider) => {
      try {
        let timeout;
        let models;
        try {
          models = await Promise.race([
            this.ctx.llm.listModels(provider.id),
            new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error('timeout')), 15000); timeout.unref(); }),
          ]);
        } finally { clearTimeout(timeout); }
        for (const model of models) {
          const id = `${provider.id}/${model.id}`;
          if (id.length > 200 || catalog.has(id)) continue;
          catalog.set(id, { id, name: `${provider.name} · ${model.name}`, provider: provider.id, model: model.id });
        }
      } catch {
        // Adapter diagnostics may contain credentials; only publish its display name.
        errors.push({ provider: provider.id, name: provider.name, message: '模型列表暂不可用' });
      }
    }));
    this.catalog = catalog;
    this.errors = errors;
    const selection = this.ctx.get?.('agentDefaultModel')?.currentSelection();
    const selected = selection && `${selection.provider}/${selection.model}`;
    this.defaultModel = catalog.has(selected) ? selected : catalog.keys().next().value;
    this.reasoningEffort = catalog.has(selected) ? selection.reasoningEffort : undefined;
    this.checkedAt = Date.now();
    return this.status();
  }

  status() {
    return { available: true, models: [...this.catalog.values()], default_model: this.defaultModel || null, errors: this.errors };
  }

  async sync(request, force = false) {
    if (this.syncing) return this.syncing;
    this.syncing = this.syncOnce(request, force);
    try { return await this.syncing; } finally { this.syncing = null; }
  }

  async syncOnce(request, force) {
    await this.ready;
    if (force || !this.checkedAt || Date.now() - this.checkedAt > 60000) await this.refresh();
    if (!this.catalog.size) return this.status();
    const call = async (method, path, body) => {
      const { response, parsed } = await request(method, path, body);
      if (!response.ok) throw new Error('DSH 模型同步失败，请刷新重试');
      return parsed;
    };
    let settings = await call('GET', '/api/ai/providers');
    // The owned URL suffix identifies only this bridge; independent providers survive.
    let provider = settings.providers.find((p) => p.name === NAME && /^http:\/\/127\.0\.0\.1:\d+\/chapter-whale-host\/v1$/.test(p.base_url));
    if (!provider) {
      const result = await call('POST', '/api/ai/providers', { name: NAME, base_url: this.url, api_key: this.token });
      provider = result.providers.find((p) => p.id === result.id);
      settings = result;
    } else if (provider.base_url !== this.url || this.syncedProvider !== provider.id) {
      settings = await call('PUT', `/api/ai/providers/${provider.id}`, { base_url: this.url, api_key: this.token });
      provider = settings.providers.find((p) => p.id === provider.id);
    }
    this.syncedProvider = provider.id;
    const ids = [...this.catalog.keys()].sort();
    if (force || JSON.stringify([...(provider.models || [])].sort()) !== JSON.stringify(ids)) {
      await call('POST', `/api/ai/providers/${provider.id}/models`, {});
    }
    const binding = settings.default_binding || {};
    const current = settings.providers.find((p) => p.id === binding.provider_id);
    if (!binding.model_id || !current?.has_key || (current.id === provider.id && !this.catalog.has(binding.model_id))) {
      await call('PUT', '/api/ai/bindings', { default_binding: { provider_id: provider.id, model_id: this.defaultModel,
        reasoning_effort: 'auto' } });
    }
    return { ...this.status(), provider_id: provider.id };
  }

  async handle(req, res) {
    const expected = `Bearer ${this.token}`;
    const auth = req.headers.authorization;
    if (req.headers.origin || typeof auth !== 'string' || Buffer.byteLength(auth) !== Buffer.byteLength(expected)
        || !timingSafeEqual(Buffer.from(auth), Buffer.from(expected))) {
      return json(res, 401, { error: { message: 'DSH 本机连接未授权' } });
    }
    if (req.method === 'GET' && req.url === `${PREFIX}/models`) {
      return json(res, 200, { object: 'list', data: [...this.catalog.keys()].map((id) => ({ id, object: 'model', owned_by: 'dsh' })) });
    }
    if (req.method !== 'POST' || req.url !== `${PREFIX}/chat/completions`) return json(res, 404, { error: { message: '未知接口' } });
    const controller = new AbortController();
    const limits = this.limits;
    this.calls.add(controller);
    /** First abort reason wins; it outranks whatever the provider reports afterwards. */
    let stopReason = null;
    const stop = (reason) => {
      if (stopReason) return;
      stopReason = reason;
      controller.abort();
    };
    // A closed client must stop generation: otherwise a discarded chapter burns tokens
    // to completion with nobody to receive it.
    res.once('close', () => { if (!res.writableEnded) stop('client_closed'); });
    let heartbeat = null;
    let firstChunk = null;
    let deadline = null;
    let terminal = false;
    const clearTimers = () => {
      if (heartbeat) { clearInterval(heartbeat); heartbeat = null; }
      this.heartbeat = null;
      if (firstChunk) { clearTimeout(firstChunk); firstChunk = null; }
      if (deadline) { clearTimeout(deadline); deadline = null; }
    };
    /** Exactly one terminal SSE frame per response: payload + [DONE], heartbeat stopped. */
    const terminate = (payload) => {
      if (terminal) return false;
      terminal = true;
      clearTimers();
      if (res.writableEnded || res.destroyed) return false;
      res.write(`data: ${JSON.stringify(payload)}\n\ndata: [DONE]\n\n`);
      res.end();
      return true;
    };
    try {
      let bytes = 0;
      const chunks = [];
      for await (const chunk of req) {
        bytes += chunk.length;
        if (bytes > 8 * 1024 * 1024) throw new Error('request-too-large');
        chunks.push(chunk);
      }
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      const route = this.catalog.get(body.model);
      if (!route) return json(res, 400, { error: { message: '请刷新 DSH 模型后重新选择' } });
      if (!Array.isArray(body.messages) || body.messages.some((m) => !['system', 'developer', 'user', 'assistant', 'tool'].includes(m.role) || (m.content != null && typeof m.content !== 'string'))) {
        return json(res, 400, { error: { message: '仅支持文本创作消息' } });
      }
      let system = body.messages.filter((m) => ['system', 'developer'].includes(m.role)).map((m) => m.content).join('\n\n');
      if (body.response_format?.type === 'json_object') system += '\n请只输出一个有效的 JSON 对象，不要使用 Markdown 代码块。';
      const options = {
        provider: route.provider, model: route.model, system,
        messages: body.messages.filter((m) => ['user', 'assistant', 'tool'].includes(m.role)).map((m) => ({
          role: m.role,
          ...(m.role === 'assistant' ? { source: { kind: 'model', provider: route.provider, model: route.model } } : {}),
          ...(m.role === 'tool' ? { toolCallId: m.tool_call_id } : {}),
          content: [
            ...(m.content ? [{ type: 'text', text: m.content }] : []),
            ...(m.role === 'assistant' ? (m.tool_calls || []).map((t) => ({ type: 'tool-call', id: t.id, name: t.function.name, arguments: t.function.arguments })) : []),
          ],
        })),
        ...(body.tools ? { tools: body.tools.map((t) => ({ name: t.function.name, description: t.function.description || '', parameters: t.function.parameters })) } : {}),
        purpose: 'chapter-whale', signal: controller.signal,
        ...(body.temperature === undefined ? {} : { temperature: body.temperature }),
        ...(body.max_tokens === undefined ? {} : { maxTokens: body.max_tokens }),
        ...(body.reasoning_effort && body.reasoning_effort !== 'auto' ? { reasoningEffort: body.reasoning_effort === 'none' ? 'off' : body.reasoning_effort }
          : body.thinking?.type === 'disabled' ? { reasoningEffort: 'off' }
          : body.model === this.defaultModel && this.reasoningEffort ? { reasoningEffort: this.reasoningEffort } : {}),
      };
      const { provider, model, temperature, maxTokens, reasoningEffort } = options;
      // The wall clock starts before prepareCall: a wedged provider handshake must not hang the tool.
      deadline = setTimeout(() => stop('generation_timeout'), limits.totalMs);
      deadline.unref?.();
      const prepared = await this.ctx.llm.prepareCall({ provider, model,
        ...(temperature === undefined ? {} : { temperature }),
        ...(maxTokens === undefined ? {} : { maxTokens }),
        ...(reasoningEffort === undefined ? {} : { reasoningEffort }),
      }, controller.signal);
      let content = '', reasoning = '', finish, usage, finishedAt = 0;
      /** Single counter over every retained string; see MAX_RESPONSE_CHARS for unit and semantics. */
      let buffered = 0;
      let sawChunk = false;
      const toolCalls = new Map();
      const retain = (text) => {
        if (!text) return;
        buffered += text.length;
        if (buffered > limits.maxChars) {
          stop('response_too_large');
          throw new Error('response-too-large');
        }
      };
      // Buffer one response so a terminal auth/provider failure never becomes a saved partial chapter.
      if (body.stream) {
        res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store' });
        heartbeat = setInterval(() => {
          if (!res.writableEnded && !res.destroyed) res.write(': working\n\n');
        }, limits.heartbeatMs);
        this.heartbeat = heartbeat;
        heartbeat.unref?.();
      }
      firstChunk = setTimeout(() => stop('first_chunk_timeout'), limits.firstChunkMs);
      firstChunk.unref?.();
      for await (const chunk of prepared.stream({ ...options, ...prepared.config })) {
        // OpenAI's `stream_options.include_usage` puts the token counts in a chunk that
        // arrives *after* the finish_reason, so a terminal must not close the door on
        // usage — only on body text. Past the grace window the stream is simply cut.
        if (finish) {
          if (Date.now() - finishedAt > TRAILING_USAGE_MS) break;
          if (chunk.type === 'usage') usage = chunk.usage || usage;
          continue;
        }
        if (!sawChunk) {
          sawChunk = true;
          clearTimeout(firstChunk);
          firstChunk = null;
        }
        if (chunk.type === 'text-delta') { retain(chunk.text); content += chunk.text; }
        else if (chunk.type === 'reasoning-delta') { retain(chunk.text); reasoning += chunk.text; }
        else if (chunk.type === 'usage') usage = chunk.usage || usage;
        else if (chunk.type === 'finish') { finish = chunk.reason; finishedAt = Date.now(); }
        else if (chunk.type === 'tool-call-delta') {
          retain(chunk.name);
          retain(chunk.argumentsDelta);
          const call = toolCalls.get(chunk.index) || { id: chunk.id, type: 'function', function: { name: '', arguments: '' } };
          if (chunk.name) call.function.name = chunk.name;
          call.function.arguments += chunk.argumentsDelta || '';
          toolCalls.set(chunk.index, call);
        }
      }
      // An abort the provider swallowed must still fail instead of committing a stub.
      if (stopReason) throw new Error(stopReason);
      if (!finish || !['stop', 'max-tokens', 'tool-calls'].includes(finish.kind) || (!content.trim() && !toolCalls.size)) {
        throw Object.assign(new Error('model-failed'), { failure: finish?.failure });
      }
      // A max-tokens cut keeps the draft for diagnostics, but the frame says `length`:
      // callers must not treat it as a finished, review-ready chapter.
      const truncated = finish.kind === 'max-tokens';
      const usageFrame = contractUsage(usage);
      const choice = { index: 0, finish_reason: truncated ? 'length' : finish.kind === 'tool-calls' ? 'tool_calls' : 'stop' };
      const tool_calls = toolCalls.size ? [...toolCalls.values()] : undefined;
      const diagnostic = { truncated, finish: finish.kind, buffered_chars: buffered };
      if (body.stream) {
        terminate({ choices: [{ ...choice, delta: { content, reasoning_content: reasoning, tool_calls } }],
          ...(usageFrame ? { usage: usageFrame } : {}), x_chapter_whale: diagnostic });
      } else {
        json(res, 200, { model: body.model,
          choices: [{ ...choice, message: { role: 'assistant', content, reasoning_content: reasoning, tool_calls } }],
          ...(usageFrame ? { usage: usageFrame } : {}), x_chapter_whale: diagnostic });
      }
    } catch (error) {
      const reason = stopReason;
      const code = reason === 'first_chunk_timeout' ? 'DSH_MODEL_FIRST_CHUNK_TIMEOUT'
        : reason === 'generation_timeout' ? 'DSH_MODEL_TIMEOUT'
        : reason === 'response_too_large' ? 'DSH_MODEL_TOO_LARGE'
        : reason === 'client_closed' ? 'DSH_MODEL_ABORTED'
        : 'DSH_MODEL_FAILED';
      const status = reason === 'first_chunk_timeout' || reason === 'generation_timeout' ? 504
        : reason === 'response_too_large' ? 413
        : reason === 'client_closed' ? 499
        : Number.isInteger(error.failure?.status) && error.failure.status >= 400 && error.failure.status <= 599 ? error.failure.status : 502;
      const message = reason === 'first_chunk_timeout' ? `DSH 模型首块响应超时（${limits.firstChunkMs} 毫秒）`
        : reason === 'generation_timeout' ? `DSH 模型生成超时（${limits.totalMs} 毫秒）`
        : reason === 'response_too_large' ? `DSH 模型响应超过缓冲上限（${limits.maxChars} 字符）`
        : reason === 'client_closed' ? '客户端已断开，本次生成已中止'
        : 'DSH 模型调用失败，请检查宿主中的登录状态和模型设置';
      // A disconnected client cannot receive a frame; never fake a success either.
      if (reason === 'client_closed' || res.destroyed) return;
      const failure = { error: { message, status, code } };
      if (!res.headersSent) json(res, status, failure);
      else terminate(failure);
    } finally {
      clearTimers();
      this.calls.delete(controller);
    }
  }

  close() {
    for (const controller of this.calls) controller.abort();
    this.server.close();
    this.server.closeAllConnections();
  }
}
