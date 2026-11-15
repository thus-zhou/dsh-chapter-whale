import { createServer } from 'node:http';
import { randomBytes, timingSafeEqual } from 'node:crypto';

const PREFIX = '/chapter-whale-host/v1';
const NAME = 'DSH 模型';
const json = (res, status, value) => {
  res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' });
  res.end(JSON.stringify(value));
};

/** Credentials remain inside the owning DSH adapter. This token only gates loopback. */
export class DshModelBridge {
  constructor(ctx) {
    this.ctx = ctx;
    this.catalog = new Map();
    this.errors = [];
    this.token = randomBytes(32).toString('base64url');
    this.calls = new Set();
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
    this.calls.add(controller);
    res.once('close', () => { if (!res.writableEnded) controller.abort(); });
    let timer;
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
      const prepared = await this.ctx.llm.prepareCall({ provider, model,
        ...(temperature === undefined ? {} : { temperature }),
        ...(maxTokens === undefined ? {} : { maxTokens }),
        ...(reasoningEffort === undefined ? {} : { reasoningEffort }),
      }, controller.signal);
      let content = '', reasoning = '', finish, usage, outputSize = 0;
      const toolCalls = new Map();
      // Buffer one response so a terminal auth/provider failure never becomes a saved partial chapter.
      if (body.stream) {
        res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store' });
        timer = setInterval(() => res.write(': working\n\n'), 10000);
      }
      for await (const chunk of prepared.stream({ ...options, ...prepared.config })) {
        outputSize += (chunk.text || chunk.argumentsDelta || '').length;
        if (chunk.type === 'text-delta') content += chunk.text;
        else if (chunk.type === 'reasoning-delta') reasoning += chunk.text;
        else if (chunk.type === 'usage') usage = chunk.usage;
        else if (chunk.type === 'finish') finish = chunk.reason;
        else if (chunk.type === 'tool-call-delta') {
          const call = toolCalls.get(chunk.index) || { id: chunk.id, type: 'function', function: { name: '', arguments: '' } };
          if (chunk.name) call.function.name = chunk.name;
          call.function.arguments += chunk.argumentsDelta || '';
          toolCalls.set(chunk.index, call);
        }
        if (outputSize > 16 * 1024 * 1024) { controller.abort(); throw new Error('response-too-large'); }
      }
      if (!finish || !['stop', 'max-tokens', 'tool-calls'].includes(finish.kind) || (!content.trim() && !toolCalls.size)) {
        throw Object.assign(new Error('model-failed'), { failure: finish?.failure });
      }
      const openUsage = usage && {
        prompt_tokens: usage.inputTokens + (usage.cacheReadTokens || 0) + (usage.cacheWriteTokens || 0),
        completion_tokens: usage.outputTokens, total_tokens: usage.totalTokens,
        prompt_tokens_details: { cached_tokens: usage.cacheReadTokens || 0 },
      };
      const choice = { index: 0, finish_reason: finish.kind === 'max-tokens' ? 'length' : finish.kind === 'tool-calls' ? 'tool_calls' : 'stop' };
      const tool_calls = toolCalls.size ? [...toolCalls.values()] : undefined;
      if (body.stream) {
        res.write(`data: ${JSON.stringify({ choices: [{ ...choice, delta: { content, reasoning_content: reasoning, tool_calls } }], usage: openUsage })}\n\ndata: [DONE]\n\n`);
        res.end();
      } else json(res, 200, { model: body.model, choices: [{ ...choice, message: { role: 'assistant', content, reasoning_content: reasoning, tool_calls } }], usage: openUsage });
    } catch (error) {
      const status = Number.isInteger(error.failure?.status) && error.failure.status >= 400 && error.failure.status <= 599 ? error.failure.status : 502;
      const failure = { error: { message: 'DSH 模型调用失败，请检查宿主中的登录状态和模型设置', status, code: 'DSH_MODEL_FAILED' } };
      if (!res.headersSent) json(res, status, failure);
      else { res.write(`data: ${JSON.stringify(failure)}\n\ndata: [DONE]\n\n`); res.end(); }
    } finally {
      clearInterval(timer);
      this.calls.delete(controller);
    }
  }

  close() {
    for (const controller of this.calls) controller.abort();
    this.server.close();
    this.server.closeAllConnections();
  }
}
