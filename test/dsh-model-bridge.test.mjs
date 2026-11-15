import test from 'node:test';
import assert from 'node:assert/strict';
import { DshModelBridge } from '../dsh-model-bridge.mjs';

async function fixture(t, chunks) {
  const captured = [];
  const llm = {
    listProviders: () => [{ id: 'account', name: '已登录账号' }, { id: 'empty', name: '未登录' }],
    listModels: async (id) => id === 'account' ? [{ id: 'writer', name: '写作模型' }] : [],
    prepareCall: async (config, signal) => ({ config, stream: async function* (options) {
      captured.push(options);
      for (const chunk of chunks || [{ type: 'text-delta', text: '连接成功' }, { type: 'finish', reason: { kind: 'stop' } }]) yield chunk;
      assert.equal(signal.aborted, false);
    } }),
  };
  const bridge = new DshModelBridge({ llm, get: () => ({ currentSelection: () => ({ provider: 'account', model: 'writer' }) }) });
  t.after(() => bridge.close());
  await bridge.ready; await bridge.refresh();
  const request = async (body, token = bridge.token) => fetch(`${bridge.url}/chat/completions`, {
    method: 'POST', headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
    body: JSON.stringify({ model: 'account/writer', messages: [{ role: 'user', content: '连接检测' }], ...body }),
  });
  return { bridge, captured, request };
}

test('复用宿主路由、思考强度、JSON 指令及用量；不读取账号凭据', async (t) => {
  const { bridge, captured, request } = await fixture(t, [
    { type: 'reasoning-delta', text: '思考' }, { type: 'text-delta', text: '{"ok":true}' },
    { type: 'usage', usage: { inputTokens: 10, outputTokens: 5, cacheReadTokens: 3, totalTokens: 18 } },
    { type: 'finish', reason: { kind: 'stop' } },
  ]);
  assert.equal(bridge.catalog.size, 1);
  assert.equal(bridge.defaultModel, 'account/writer');
  const result = await (await request({ reasoning_effort: 'none', response_format: { type: 'json_object' }, max_tokens: 100 })).json();
  assert.equal(result.choices[0].message.content, '{"ok":true}');
  assert.equal(result.usage.prompt_tokens, 13);
  assert.equal(captured[0].provider, 'account');
  assert.equal(captured[0].model, 'writer');
  assert.equal(captured[0].reasoningEffort, 'off');
  assert.match(captured[0].system, /JSON/);
  assert.equal(captured[0].apiKey, undefined);
});

test('工具调用和工具结果完整往返宿主，不在桥内执行工具', async (t) => {
  const { request, captured } = await fixture(t, [
    { type: 'tool-call-delta', index: 0, id: 'call1', name: 'connectivity_check', argumentsDelta: '{' },
    { type: 'tool-call-delta', index: 0, id: 'call1', argumentsDelta: '}' },
    { type: 'finish', reason: { kind: 'tool-calls' } },
  ]);
  const result = await (await request({ tools: [{ type: 'function', function: { name: 'connectivity_check', parameters: { type: 'object' } } }], messages: [
    { role: 'user', content: '检查' },
    { role: 'assistant', content: null, tool_calls: [{ id: 'previous', function: { name: 'check', arguments: '{}' } }] },
    { role: 'tool', tool_call_id: 'previous', content: 'ok' },
  ] })).json();
  assert.equal(result.choices[0].finish_reason, 'tool_calls');
  assert.equal(result.choices[0].message.tool_calls[0].function.arguments, '{}');
  assert.equal(captured[0].tools[0].name, 'connectivity_check');
  assert.equal(captured[0].messages[1].content[0].type, 'tool-call');
  assert.equal(captured[0].messages[2].toolCallId, 'previous');
});

test('流式终端失败不返回已生成的半章，也不暴露异常凭据', async (t) => {
  const { request } = await fixture(t, [
    { type: 'text-delta', text: '这是一段未完成的正文' },
    { type: 'finish', reason: { kind: 'error', failure: { message: 'secret-token' } } },
  ]);
  const result = await request({ stream: true });
  const body = await result.text();
  assert.match(body, /DSH_MODEL_FAILED/);
  assert.doesNotMatch(body, /未完成的正文|secret-token/);
});

test('本机桥要求令牌，拒绝跨站和未知模型；没有模型调用', async (t) => {
  const { request, bridge, captured } = await fixture(t);
  assert.equal((await request({}, 'invalid')).status, 401);
  const foreign = await fetch(`${bridge.url}/models`, { headers: { authorization: `Bearer ${bridge.token}`, origin: 'https://other.test' } });
  assert.equal(foreign.status, 401);
  assert.equal((await request({ model: 'unknown' })).status, 400);
  assert.equal(captured.length, 0);
});

test('自动接入保留独立模型配置，空配置选择宿主当前模型，重载只更新自己的连接', async (t) => {
  const { bridge } = await fixture(t);
  let settings = { providers: [{ id: 'manual', name: '独立接口', base_url: 'https://api.example/v1', has_key: true, models: ['existing'] }], default_binding: { provider_id: 'manual', model_id: 'existing' } };
  const writes = [];
  const request = async (method, path, body) => {
    if (method !== 'GET') writes.push({ method, path, body });
    if (method === 'POST' && path === '/api/ai/providers') settings = { ...settings, id: 'host', providers: [...settings.providers, { id: 'host', ...body, has_key: true, models: [] }] };
    if (method === 'PUT' && path === '/api/ai/providers/host') Object.assign(settings.providers.find((p) => p.id === 'host'), body);
    if (path.endsWith('/models')) settings.providers.find((p) => p.id === 'host').models = [...bridge.catalog.keys()];
    if (path === '/api/ai/bindings') settings.default_binding = body.default_binding;
    return { response: { ok: true }, parsed: structuredClone(settings) };
  };
  await bridge.sync(request);
  assert.equal(settings.default_binding.provider_id, 'manual');
  settings.default_binding = {};
  await bridge.sync(request);
  assert.equal(settings.default_binding.model_id, 'account/writer');
  settings.providers.find((p) => p.id === 'host').base_url = 'http://127.0.0.1:2/chapter-whale-host/v1';
  await bridge.sync(request);
  assert.equal(settings.providers.length, 2);
  assert.equal(settings.providers.find((p) => p.id === 'host').base_url, bridge.url);
  assert.equal(writes.filter((w) => w.path === '/api/ai/providers').length, 1);
});
