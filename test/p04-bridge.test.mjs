/**
 * P04 契约测试（禁止真实网络/真实模型：上游全是 127.0.0.1 上的临时 http 服务，
 * 模型侧全是注入的假 ctx.llm）。
 *
 * 覆盖三块：
 *  1. 派发前同步：写操作先 sync 再 requestUpstream；只读不 sync；sync 失败有独立 reason_code。
 *  2. usage 规范化：host 契约（inputTokens 不含 cache）下不重复相加、缺分量不补零、无 NaN/null。
 *  3. 流式桥接：SSE 心跳/终态唯一/usage 不丢；缓冲超限 abort 且心跳定时器清理；非流式 JSON；
 *     首块超时/总超时/客户端断开/max-tokens 截断/宿主报错各自独立断言。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { spawnSync } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { DshModelBridge } from '../dsh-model-bridge.mjs';
import { __internals, resolveConfig } from '../index.js';

const REPO = fileURLToPath(new URL('..', import.meta.url));
const delay = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });
/** 可被 abort 立即唤醒的等待：超时用例因此只需几十毫秒。 */
const wait = (ms, signal) => new Promise((resolve) => {
  if (signal?.aborted) return resolve();
  const timer = setTimeout(done, ms);
  function done() { clearTimeout(timer); signal?.removeEventListener('abort', done); resolve(); }
  signal?.addEventListener('abort', done, { once: true });
});

/* ------------------------------------------------------- 1. 工具派发前同步 */

async function upstream(t, handler) {
  const requests = [];
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    let body = '';
    for await (const chunk of req) body += chunk;
    const call = { method: req.method, path: url.pathname, body };
    requests.push(call);
    const reply = (await handler(call)) || {};
    res.writeHead(reply.status ?? 200, { 'content-type': 'application/json' });
    res.end(JSON.stringify(reply.json ?? {}));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => {
    server.closeAllConnections?.();
    return new Promise((resolve) => server.close(() => resolve()));
  });
  return { port: server.address().port, requests };
}

async function rootFixture(t) {
  const dir = await mkdtemp(join(tmpdir(), 'p04-root-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return dir;
}

function toolFor(config, approval = 'allowed-once') {
  const ctx = { get: (name) => (name === 'approval' && approval ? { request: async () => approval } : undefined) };
  return __internals.makeTool(ctx, config);
}

test('P04 写操作在派发前 sync 一次，且 sync 拿到的是真实 requestUpstream', async (t) => {
  const server = await upstream(t, ({ path }) => (path === '/api/ai/providers' ? { json: { providers: [], echoed: true } } : { json: { generated: true } }));
  const config = resolveConfig({ rootDir: await rootFixture(t), port: server.port });
  const order = [];
  const seen = [];
  config.hostModels = {
    async sync(request) {
      order.push('sync:start');
      const { parsed } = await request('GET', '/api/ai/providers');
      seen.push(parsed);
      order.push('sync:end');
    },
  };
  const tool = toolFor(config);
  const result = await tool.execute({ action: 'post', path: '/api/projects/p1/generate', confirm: true, body: { n: 1 } }, {});

  assert.equal(result.ok, true);
  assert.deepEqual(order, ['sync:start', 'sync:end']);
  assert.equal(seen[0].echoed, true, 'sync 必须能用同一个 requestUpstream 打到服务');
  assert.deepEqual(server.requests.map((r) => `${r.method} ${r.path}`), [
    'GET /api/ai/providers',
    'POST /api/projects/p1/generate',
  ]);
  assert.equal(JSON.parse(server.requests[1].body).n, 1);
});

test('P04 sync 抛错时不发上游写请求，返回独立 reason_code', async (t) => {
  const server = await upstream(t, () => ({ json: { generated: true } }));
  const config = resolveConfig({ rootDir: await rootFixture(t), port: server.port });
  let syncs = 0;
  config.hostModels = { sync: async () => { syncs += 1; throw new Error('宿主编排忙'); } };
  const tool = toolFor(config);
  const result = await tool.execute({ action: 'post', path: '/api/projects/p1/generate', confirm: true }, {});

  assert.equal(syncs, 1);
  assert.equal(result.ok, false);
  assert.equal(result.reason_code, 'bridge_sync_failed');
  assert.match(result.error, /^模型桥同步失败：宿主编排忙/);
  assert.equal(server.requests.length, 0, '同步失败后不得继续用旧端口/旧 Token 生成');
});

test('P04 只读路径（action=status、GET）不触发 sync，也不改写默认绑定', async (t) => {
  const server = await upstream(t, ({ path }) => {
    if (path === '/api/health') return { json: { service: 'novel-helper-manager', status: 'ok' } };
    if (path === '/api/overview') return { json: { projects: [], accounts: [], queue: {}, diagnostics: {}, jobs: [] } };
    return { json: { ok: true } };
  });
  const config = resolveConfig({ rootDir: await rootFixture(t), port: server.port });
  let syncs = 0;
  config.hostModels = { sync: async () => { syncs += 1; } };
  const tool = toolFor(config);

  const status = await tool.execute({ action: 'status' }, {});
  assert.equal(status.running, true);
  assert.equal(status.overview.projects.length, 0);

  const read = await tool.execute({ action: 'get', path: '/api/projects' }, {});
  assert.equal(read.ok, true);
  assert.equal(syncs, 0, '只读路径不得触发模型桥同步');
  assert.equal(server.requests.filter((r) => r.method !== 'GET').length, 0);
});

test('P04 未注入 hostModels 时不阻断普通写操作（旧配置仍可用）', async (t) => {
  const server = await upstream(t, () => ({ json: { ok: true } }));
  const config = resolveConfig({ rootDir: await rootFixture(t), port: server.port });
  const tool = toolFor(config);
  const result = await tool.execute({ action: 'post', path: '/api/jobs/j1/run', confirm: true }, {});
  assert.equal(result.ok, true);
  assert.equal(server.requests.length, 1);
  assert.equal(server.requests[0].path, '/api/jobs/j1/run');
});

/* ---------------------------------------------------- 2. usage 契约（Python） */

const PY_USAGE = String.raw`
import json, sys
sys.path.insert(0, 'backend')
from integration import costs
cases = json.loads(sys.argv[1])
out = {name: costs.parse_usage(value) for name, value in cases.items()}
print(json.dumps(out, allow_nan=False))
`;

function pythonAvailable() {
  const probe = spawnSync(process.env.PYTHON || 'python', ['-c', 'import sys; print(sys.version_info[0])'], { encoding: 'utf8' });
  return probe.status === 0 && probe.stdout.trim() === '3';
}

test('P04 parse_usage：缺分量不补零、不重复相加、无 NaN/Infinity/null 冒充数值', (t) => {
  if (!pythonAvailable()) return t.skip('本机没有 python 3，跳过 Python 侧契约测试');
  // 桥发出的形状：prompt_tokens 已含 cache（113 = 100 基础 + 10 read + 3 write）。
  const cases = {
    complete: { prompt_tokens: 113, completion_tokens: 20, total_tokens: 133, prompt_tokens_details: { cached_tokens: 10, cache_write_tokens: 3 } },
    cache_without_input: { completion_tokens: 20, prompt_tokens_details: { cached_tokens: 7 } },
    output_only: { output_tokens: 20 },
    negative_input: { prompt_tokens: -5, completion_tokens: 20 },
    valid_zero: { prompt_tokens: 0, completion_tokens: 0 },
    invalid: { prompt_tokens: -5, completion_tokens: null },
    numeric_strings: { prompt_tokens: '100', completion_tokens: '20' },
    anthropic_shape: { input_tokens: 100, cache_read_input_tokens: 10, cache_creation_input_tokens: 3, output_tokens: 20 },
  };
  const run = spawnSync(process.env.PYTHON || 'python', ['-c', PY_USAGE, JSON.stringify(cases)], { cwd: REPO, encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  assert.doesNotMatch(run.stdout, /\bNaN\b|\bInfinity\b/);
  const parsed = JSON.parse(run.stdout);

  // 契约核心：prompt_tokens 已包含缓存，不得再加一次。
  assert.equal(parsed.complete.input_tokens, 113);
  assert.equal(parsed.complete.cached_tokens, 10);
  assert.equal(parsed.complete.cache_write_tokens, 3);
  assert.equal(parsed.complete.total_tokens, 133);
  assert.equal(parsed.complete.usage_source, 'reported');
  assert.equal(parsed.complete.total_source, 'reported');

  // Anthropic 形状（无 prompt_tokens）才把 cache 加回。
  assert.equal(parsed.anthropic_shape.input_tokens, 113);
  assert.equal(parsed.anthropic_shape.cached_tokens, 10);

  // 缺基础输入：保留未知，只带缓存分量，不造“真实零用量”。
  assert.equal(parsed.cache_without_input.input_tokens, null);
  assert.equal(parsed.cache_without_input.usage_source, 'partial');
  assert.deepEqual(parsed.cache_without_input.usage_missing, ['input_tokens']);
  assert.equal(parsed.cache_without_input.cached_tokens, 7);
  assert.equal(parsed.output_only.input_tokens, null);
  assert.equal(parsed.output_only.usage_source, 'partial');

  // 宿主明确说 0 才是 0。
  assert.equal(parsed.valid_zero.input_tokens, 0);
  assert.equal(parsed.valid_zero.output_tokens, 0);
  assert.equal(parsed.valid_zero.usage_source, 'reported');

  // 负数/非法数不可信 → 未知或整体丢弃，但绝不变成 0。
  assert.equal(parsed.negative_input.input_tokens, null);
  assert.equal(parsed.negative_input.usage_source, 'partial');
  assert.equal(parsed.invalid, null);

  // 纯数字字符串按整数收下。
  assert.equal(parsed.numeric_strings.input_tokens, 100);
  assert.equal(parsed.numeric_strings.output_tokens, 20);

  // 已知分量必须是整数，未知分量为 null 且列在 usage_missing 里。
  for (const [name, value] of Object.entries(parsed)) {
    if (!value) continue;
    for (const key of ['input_tokens', 'output_tokens', 'cached_tokens', 'cache_write_tokens', 'total_tokens']) {
      if (value[key] !== null) assert.ok(Number.isInteger(value[key]) && value[key] >= 0, `${name}.${key} 必须是整数`);
    }
    for (const key of value.usage_missing || []) assert.equal(value[key], null, `${name}.${key} 未知时必须为 null`);
  }
});

/* ------------------------------------------------------------ 3. 流式桥接 */

async function bridgeFixture(t, { limits = {}, prepare, stream }) {
  const state = { aborted: false, calls: [] };
  const llm = {
    listProviders: () => [{ id: 'account', name: '已登录账号' }],
    listModels: async () => [{ id: 'writer', name: '写作模型' }],
    prepareCall: (config, signal) => (prepare
      ? prepare(config, signal, state)
      : Promise.resolve({ config, stream: (options) => stream(options, state) })),
  };
  const bridge = new DshModelBridge({ llm, get: () => ({ currentSelection: () => ({ provider: 'account', model: 'writer' }) }) }, limits);
  t.after(() => bridge.close());
  await bridge.ready;
  await bridge.refresh();
  const post = (body, signal) => fetch(`${bridge.url}/chat/completions`, {
    method: 'POST',
    headers: { authorization: `Bearer ${bridge.token}`, 'content-type': 'application/json' },
    body: JSON.stringify({ model: 'account/writer', messages: [{ role: 'user', content: '写' }], ...body }),
    signal,
  });
  return { bridge, state, post };
}

const frames = (text) => text.split('\n\n').filter((frame) => frame.length > 0);
const payloads = (text) => frames(text).filter((f) => f.startsWith('data: ') && f !== 'data: [DONE]').map((f) => JSON.parse(f.slice(6)));

test('P04 SSE：真换行分帧、心跳可识别、重复终态只提交一次、usage 不丢', async (t) => {
  const { bridge, post } = await bridgeFixture(t, {
    limits: { heartbeatMs: 20 },
    async *stream() {
      yield { type: 'text-delta', text: '第一段' };
      await delay(70); // 让心跳至少出现一次
      yield { type: 'reasoning-delta', text: '推理' };
      yield { type: 'usage', usage: { inputTokens: 10, outputTokens: 5, cacheReadTokens: 3, cacheWriteTokens: 2, totalTokens: 20 } };
      yield { type: 'finish', reason: { kind: 'stop' } };
      yield { type: 'finish', reason: { kind: 'stop' } }; // 宿主重复终态
      yield { type: 'text-delta', text: '终态之后不得提交' };
    },
  });
  const response = await post({ stream: true });
  const text = await response.text();
  const list = frames(text);

  assert.equal(response.headers.get('content-type'), 'text/event-stream');
  assert.ok(list.filter((f) => f.startsWith(':')).length >= 1, '心跳必须以注释行出现');
  assert.equal(list.filter((f) => f === 'data: [DONE]').length, 1, '终态只能出现一次');
  assert.equal(payloads(text).length, 1, '只提交一个终态帧');
  const [body] = payloads(text);
  assert.equal(body.choices[0].delta.content, '第一段');
  assert.equal(body.choices[0].delta.reasoning_content, '推理');
  assert.equal(body.choices[0].finish_reason, 'stop');
  assert.equal(body.usage.prompt_tokens, 15, 'inputTokens 不含 cache，此处必须加回且只加一次');
  assert.equal(body.usage.completion_tokens, 5);
  assert.equal(body.usage.total_tokens, 20);
  assert.equal(body.usage.prompt_tokens_details.cached_tokens, 3);
  assert.equal(body.x_chapter_whale.truncated, false);
  assert.doesNotMatch(text, /NaN|Infinity|"usage":null/);
  assert.equal(bridge.heartbeat, null, '终态后心跳定时器必须清空');
  assert.equal(bridge.calls.size, 0);
});

test('P04 终态之后的 usage 仍然入账，但正文不再延长', async (t) => {
  const { post } = await bridgeFixture(t, {
    async *stream() {
      yield { type: 'text-delta', text: '正文' };
      yield { type: 'finish', reason: { kind: 'stop' } };
      // OpenAI `stream_options.include_usage`：usage 在 finish_reason 之后单独一帧到达。
      yield { type: 'usage', usage: { inputTokens: 4, outputTokens: 6, cacheReadTokens: 1 } };
      yield { type: 'text-delta', text: '尾巴' };
    },
  });
  const response = await post({ stream: true });
  const [body] = payloads(await response.text());
  assert.equal(body.choices[0].delta.content, '正文', '终态之后不得追加正文');
  assert.equal(body.usage.prompt_tokens, 5, '4 input + 1 cacheRead，只加一次');
  assert.equal(body.usage.completion_tokens, 6);
  assert.equal(body.x_chapter_whale.truncated, false);
});

test('P04 缓冲上限：超限 abort 提供方，心跳定时器清理，失败帧明确', async (t) => {
  const { bridge, state, post } = await bridgeFixture(t, {
    limits: { maxChars: 32, heartbeatMs: 20 },
    async *stream(options) {
      try {
        yield { type: 'text-delta', text: 'x'.repeat(20) };
        yield { type: 'text-delta', text: 'y'.repeat(20) };
        yield { type: 'finish', reason: { kind: 'stop' } };
      } finally {
        state.aborted = Boolean(options.signal?.aborted);
      }
    },
  });
  const text = await (await post({ stream: true })).text();
  assert.match(text, /DSH_MODEL_TOO_LARGE/);
  assert.match(text, /缓冲上限（32 字符）/);
  assert.doesNotMatch(text, /xxxxx/, '超限后不得提交半章');
  assert.equal(state.aborted, true, '取消必须传到提供方');
  assert.equal(bridge.heartbeat, null);
  assert.equal(bridge.calls.size, 0);
});

test('P04 非流式：buffer 超限返回 413，且不写 body', async (t) => {
  const { post } = await bridgeFixture(t, {
    limits: { maxChars: 8 },
    async *stream() {
      yield { type: 'text-delta', text: 'z'.repeat(9) };
      yield { type: 'finish', reason: { kind: 'stop' } };
    },
  });
  const response = await post({ stream: false });
  assert.equal(response.status, 413);
  const body = await response.json();
  assert.equal(body.error.code, 'DSH_MODEL_TOO_LARGE');
  assert.equal(body.choices, undefined);
});

test('P04 非流式 JSON：正文/推理/usage/截断标记齐全，没有 null 冒充数值', async (t) => {
  const { post } = await bridgeFixture(t, {
    async *stream() {
      yield { type: 'text-delta', text: '整章正文' };
      yield { type: 'usage', usage: { inputTokens: 4, outputTokens: 2 } };
      yield { type: 'finish', reason: { kind: 'stop' } };
    },
  });
  const response = await post({ stream: false });
  assert.equal(response.status, 200);
  const text = await response.text();
  assert.doesNotMatch(text, /NaN|Infinity|:null/);
  const body = JSON.parse(text);
  assert.equal(body.choices[0].message.content, '整章正文');
  assert.equal(body.choices[0].finish_reason, 'stop');
  assert.equal(body.usage.prompt_tokens, 4);
  assert.equal(body.usage.completion_tokens, 2);
  assert.equal(body.x_chapter_whale.truncated, false);
});

test('P04 max-tokens 截断：保留诊断稿，但标记 length/truncated（不是审查通过）', async (t) => {
  const { post } = await bridgeFixture(t, {
    async *stream() {
      yield { type: 'text-delta', text: '只写了一半' };
      yield { type: 'finish', reason: { kind: 'max-tokens' } };
    },
  });
  const body = await (await post({ stream: false })).json();
  assert.equal(body.choices[0].finish_reason, 'length');
  assert.equal(body.x_chapter_whale.truncated, true);
  assert.equal(body.x_chapter_whale.finish, 'max-tokens');
  assert.equal(body.choices[0].message.content, '只写了一半');
  assert.equal(body.reviewed, undefined);
  assert.equal(body.approved, undefined);
});

test('P04 首块超时：独立失败码，取消传到提供方', async (t) => {
  const { bridge, state, post } = await bridgeFixture(t, {
    limits: { firstChunkMs: 40 },
    async *stream(options) {
      await wait(2000, options.signal);
      state.aborted = Boolean(options.signal?.aborted);
      yield { type: 'finish', reason: { kind: 'stop' } };
    },
  });
  const started = Date.now();
  const text = await (await post({ stream: true })).text();
  assert.ok(Date.now() - started < 1500, '首块超时必须及时中止，而不是等提供方');
  assert.match(text, /DSH_MODEL_FIRST_CHUNK_TIMEOUT/);
  assert.equal(state.aborted, true);
  assert.equal(bridge.heartbeat, null);
});

test('P04 总时限覆盖 prepareCall：握手卡住也按生成超时失败', async (t) => {
  const { state, post } = await bridgeFixture(t, {
    limits: { totalMs: 40, firstChunkMs: 5000 },
    prepare: async (config, signal) => {
      await wait(2000, signal);
      state.aborted = Boolean(signal?.aborted);
      return { config, stream: async function* () { yield { type: 'finish', reason: { kind: 'stop' } }; } };
    },
  });
  const started = Date.now();
  const response = await post({ stream: false });
  assert.ok(Date.now() - started < 1500);
  assert.equal(response.status, 504);
  const body = await response.json();
  assert.equal(body.error.code, 'DSH_MODEL_TIMEOUT');
  assert.equal(state.aborted, true, 'prepareCall 也必须收到取消');
});

test('P04 客户端断开：立即中止生成，不再继续写入', async (t) => {
  let produced = 0;
  let sawAbort = false;
  const { bridge, post } = await bridgeFixture(t, {
    limits: { heartbeatMs: 20 },
    async *stream(options) {
      for (let index = 0; index < 200; index += 1) {
        await wait(15, options.signal);
        if (options.signal?.aborted) { sawAbort = true; return; }
        produced += 1;
        yield { type: 'text-delta', text: 'x' };
      }
    },
  });
  const controller = new AbortController();
  const response = await post({ stream: true }, controller.signal);
  const reader = response.body.getReader();
  await reader.read(); // 至少一个心跳/正文
  controller.abort();
  await delay(150);
  assert.equal(sawAbort, true, '断开必须传到提供方');
  assert.ok(produced < 200, '断开后不得继续无界生成');
  assert.equal(bridge.heartbeat, null, '断开心跳定时器必须清理');
  assert.equal(bridge.calls.size, 0, '断开的调用必须从 calls 里移除');
});

test('P04 宿主报错（已发头）：只发一个失败终态，不含半章', async (t) => {
  const { post } = await bridgeFixture(t, {
    async *stream() {
      yield { type: 'text-delta', text: '不该出现的半章' };
      yield { type: 'finish', reason: { kind: 'error', failure: { message: 'secret-token', status: 401 } } };
    },
  });
  const text = await (await post({ stream: true })).text();
  assert.match(text, /DSH_MODEL_FAILED/);
  assert.doesNotMatch(text, /不该出现的半章|secret-token/);
  assert.equal(frames(text).filter((f) => f === 'data: [DONE]').length, 1);
});

test('P04 并发心跳与非法 JSON 校验：双流共存不互相清零，坏 JSON 返回 400', async (t) => {
  let concurrent = 0;
  let maxConcurrent = 0;
  let sawMultipleHeartbeats = false;
  const { bridge, post } = await bridgeFixture(t, {
    limits: { heartbeatMs: 15 },
    async *stream() {
      concurrent += 1;
      maxConcurrent = Math.max(maxConcurrent, concurrent);
      await delay(50);
      if (bridge.heartbeats.size >= 2 && bridge.heartbeat !== null) {
        sawMultipleHeartbeats = true;
      }
      concurrent -= 1;
      yield { type: 'text-delta', text: 'ok' };
      yield { type: 'finish', reason: { kind: 'stop' } };
    },
  });
  const [r1, r2] = await Promise.all([post({ stream: true }), post({ stream: true })]);
  await Promise.all([r1.text(), r2.text()]);
  assert.equal(maxConcurrent, 2);
  assert.equal(sawMultipleHeartbeats, true, '并发流应各自持有独立心跳定时器');
  assert.equal(bridge.heartbeats.size, 0);
  assert.equal(bridge.heartbeat, null);

  const badJson = await fetch(`${bridge.url}/chat/completions`, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${bridge.token}`,
      'content-type': 'application/json',
    },
    body: '{bad-json',
  });
  assert.equal(badJson.status, 400);
});
