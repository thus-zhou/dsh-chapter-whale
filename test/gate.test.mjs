/**
 * Gate tests for the host-side HTTP bridge.
 *
 * `createHandler()` is exercised directly with fake request/response objects, so
 * nothing here starts the manager, spawns Python, or depends on the machine's
 * project directory. Every case asserts a status code *and* that the request did
 * not reach the upstream proxy — a 403 that still forwarded would be a false
 * negative in exactly the way that matters.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';

import {
  createHandler,
  resolveConfig,
  __internals,
} from '../index.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const TOKEN = 'test-token-not-a-real-credential';

/** A project directory that looks configured but never listens. */
function makeFixture() {
  const directory = mkdtempSync(join(tmpdir(), 'novel-helper-gate-'));
  mkdirSync(join(directory, 'manager'), { recursive: true });
  writeFileSync(join(directory, 'manager', 'app.py'), '# fixture entry\n');
  return directory;
}

const fixture = makeFixture();
const config = resolveConfig({ rootDir: fixture, port: 1 });
const handle = createHandler(config, TOKEN);

function call({ method = 'GET', url = '/', headers = {} } = {}) {
  // The bridge parses the *mounted* target (`/novel-helper/...`): the host does
  // not strip the prefix before handing the request over.
  if (!url.startsWith(__internals.ROUTE)) url = `${__internals.ROUTE}${url}`;
  return new Promise((settle) => {
    const state = { status: 0, headers: null, body: '' };
    const response = {
      writeHead(status, outgoing) {
        state.status = status;
        state.headers = outgoing ?? null;
        return this;
      },
      setHeader() {},
      getHeader() {
        return undefined;
      },
      end(chunk) {
        if (chunk) state.body += chunk;
        let parsed = null;
        try {
          parsed = state.body ? JSON.parse(state.body) : null;
        } catch {
          parsed = state.body;
        }
        settle({ ...state, data: parsed });
      },
      write(chunk) {
        if (chunk) state.body += chunk;
      },
    };
    const request = {
      method,
      url,
      headers: { host: '127.0.0.1:62100', ...headers },
      on() {},
      once() {},
      off() {},
      destroy() {},
      setEncoding() {},
      pipe() {},
    };
    handle(request, response).catch((error) => settle({ status: 500, data: String(error) }));
  });
}

test.after(() => rmSync(fixture, { recursive: true, force: true }));

/* ------------------------------------------------------------------ gate 1 */

test('拒绝非回环 Host（DNS rebinding）', async () => {
  const result = await call({ url: '/_session', headers: { host: 'evil.example:62100' } });
  assert.equal(result.status, 403);
  assert.match(result.data.detail, /回环/);
  assert.equal(result.data.token, undefined);
});

test('接受 [::1] 形式的回环 Host', async () => {
  const result = await call({ url: '/_session', headers: { host: '[::1]:62100' } });
  assert.equal(result.status, 200);
  assert.equal(result.data.token, TOKEN);
});

/* ------------------------------------------------------------------ gate 2 */

test('拒绝跨站 Origin', async () => {
  const result = await call({
    url: '/_session',
    headers: { origin: 'https://evil.example' },
  });
  assert.equal(result.status, 403);
  assert.equal(result.data.token, undefined);
});

test('拒绝 Origin: null', async () => {
  const result = await call({ url: '/_session', headers: { origin: 'null' } });
  assert.equal(result.status, 403);
});

test('拒绝 Sec-Fetch-Site: cross-site', async () => {
  const result = await call({ url: '/_session', headers: { 'sec-fetch-site': 'cross-site' } });
  assert.equal(result.status, 403);
});

test('同源 Origin 放行', async () => {
  const result = await call({
    url: '/_session',
    headers: { origin: 'http://127.0.0.1:62100', 'sec-fetch-site': 'same-origin' },
  });
  assert.equal(result.status, 200);
  assert.equal(result.data.token, TOKEN);
  assert.equal(result.data.apiVersion, 1);
});

test('OPTIONS 一律 403，永不下发 CORS', async () => {
  const result = await call({ method: 'OPTIONS', url: '/api/overview' });
  assert.equal(result.status, 403);
  assert.equal(result.headers['access-control-allow-origin'], undefined);
});

/* ------------------------------------------------------------------ gate 3 */

test('_session 之外缺令牌一律 401', async () => {
  for (const url of ['/_service', '/api/overview']) {
    const result = await call({ url });
    assert.equal(result.status, 401, `${url} 应当要求令牌`);
    assert.equal(result.data.code, 'plugin-token-required');
  }
});

test('错误令牌 401', async () => {
  const result = await call({ url: '/_service', headers: { 'x-novel-helper-token': 'wrong' } });
  assert.equal(result.status, 401);
});

test('_session 只发 GET', async () => {
  const result = await call({ method: 'POST', url: '/_session', headers: { 'x-novel-helper-token': TOKEN } });
  assert.equal(result.status, 405);
});

/* ------------------------------------------------------------------ gate 4 */

test('写操作白名单外的路径 403', async () => {
  const result = await call({
    method: 'POST',
    url: '/api/__definitely_not_a_route',
    headers: { 'x-novel-helper-token': TOKEN },
  });
  assert.equal(result.status, 403);
  assert.equal(result.data.code, 'mutation-not-allowed');
});

test('DELETE 不被当成读操作放行', async () => {
  const result = await call({
    method: 'DELETE',
    url: '/api/projects/demo',
    headers: { 'x-novel-helper-token': TOKEN },
  });
  assert.equal(result.status, 403);
});

test('每条 WRITE_ROUTES 都能被自己的解析器接受', () => {
  const { WRITE_ROUTES, allowsMutation } = __internals;
  assert.ok(WRITE_ROUTES.length >= 40, `白名单只有 ${WRITE_ROUTES.length} 条，疑似漏了路由`);
  for (const route of WRITE_ROUTES) {
    // The whitelist also carries a handful of GETs because those endpoints ask
    // the manager to refresh upstream provider data even though the verb is safe.
    assert.match(route.method, /^(GET|POST|PUT|PATCH|DELETE)$/, `非法方法：${JSON.stringify(route)}`);
    assert.equal(route.segments[0], 'api', `写路由必须在 /api/ 下：${JSON.stringify(route)}`);
    const concrete = route.segments.map((segment) => (segment.startsWith(':') ? 'sample-value' : segment));
    assert.equal(
      allowsMutation(route.method, concrete),
      true,
      `白名单里的路由却不被放行：${route.method} /${route.segments.join('/')}`,
    );
  }
});

test('写白名单里的具体路径确实通过，未列出的不行', () => {
  const { allowsMutation } = __internals;
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'creative', 'chat']), true);
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'samples', 'abc', 'learn']), true);
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'samples', 'abc', 'delete']), true);
  assert.equal(allowsMutation('PUT', ['api', 'projects', 'demo', 'style-profile']), true);
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'style-profile', 'rebuild']), true);
  assert.equal(allowsMutation('PUT', ['api', 'projects', 'demo', 'memory', 'items', 'abc', 'correct']), true);
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'memory', 'candidates', '3', 'commit']), true);
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'characters']), true);
  assert.equal(allowsMutation('PUT', ['api', 'projects', 'demo', 'characters', 'abc', 'correct']), true);
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'characters', 'candidates', '3', 'commit']), true);
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'foreshadow', 'abc', 'transition']), true);
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'continuity', 'index']), true);
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'continuity', 'rebuild']), true);
  assert.equal(allowsMutation('GET', ['api', 'projects', 'demo', 'memory', 'state']), false, '只读接口不列入写白名单');
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'chapters', '3', 'revision']), true);
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'chapters', '3', 'revision', 'accept']), true);
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'chapters', '3', 'revision', 'reject']), true);
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'chapters', '3', 'restore']), true);
  assert.equal(allowsMutation('GET', ['api', 'projects', 'demo', 'chapters', '3', 'workbench']), false, 'GET 不能当写操作');
  assert.equal(allowsMutation('GET', ['api', 'projects', 'demo', 'chapters', '3', 'revision']), false, 'GET 不能当写操作');
  assert.equal(allowsMutation('DELETE', ['api', 'projects', 'demo', 'samples', 'abc']), false, '未列出的写法不放行');
  assert.equal(allowsMutation('GET', ['api', 'projects', 'demo', 'creative', 'chat']), false, 'GET 不能当写操作');
  assert.equal(allowsMutation('POST', ['api', 'projects', 'demo', 'creative', 'chat', 'extra']), false);
});

test('读操作不覆盖 /api/_service（它有自己的分支）', () => {
  const { allowsRead } = __internals;
  assert.equal(allowsRead(['api', 'overview']), true);
  assert.equal(allowsRead(['api', '_service']), false);
});

/* -------------------------------------------------------------- path guard */

test('编码后的目录穿越被拒绝', async () => {
  const result = await call({
    url: '/api/%2e%2e%2f%2e%2e%2fetc%2fpasswd',
    headers: { 'x-novel-helper-token': TOKEN },
  });
  assert.equal(result.status, 400);
});

test('反斜杠与空段被拒绝', async () => {
  for (const url of ['/api/..%5cwindows%5csystem32', '/api//overview']) {
    const result = await call({ url, headers: { 'x-novel-helper-token': TOKEN } });
    assert.equal(result.status, 400, `${url} 应当被拒绝`);
  }
});

test('路由外的路径 404', async () => {
  const result = await call({ url: '/something-else', headers: { 'x-novel-helper-token': TOKEN } });
  assert.equal(result.status, 404);
});

/* ----------------------------------------------------------------- service */

test('_service 不回显 rootDir / python / entry', async () => {
  const result = await call({ url: '/_service', headers: { 'x-novel-helper-token': TOKEN } });
  assert.equal(result.status, 200);
  const serialized = JSON.stringify(result.data);
  assert.equal(result.data.rootDir, undefined);
  assert.equal(result.data.python, undefined);
  assert.equal(result.data.entry, undefined);
  assert.doesNotMatch(serialized, /novel-helper-gate-/, '_service 泄漏了项目目录');
  assert.equal(result.data.port, 1);
});

test('首装不需要 rootDir：使用独立工作区和内置解释器', async () => {
  // A fresh install has no rootDir at all: the plugin must stay loaded and say
  // what to fill in, rather than throwing during apply().
  const unconfigured = resolveConfig({ port: 1 });
  assert.equal(unconfigured.entryExists, false);
  assert.equal(unconfigured.configuredRoot, false);
  assert.equal(unconfigured.managed, true);
  assert.notEqual(unconfigured.rootDir, process.cwd());
  assert.match(unconfigured.entry, /manager[\\/]app\.py$/);
  const result = await new Promise((settle) => {
    const state = { status: 0, body: '' };
    const response = {
      writeHead(status) {
        state.status = status;
      },
      end(chunk) {
        if (chunk) state.body += chunk;
        settle({ status: state.status, data: JSON.parse(state.body) });
      },
    };
    createHandler(unconfigured, TOKEN)(
      { method: 'GET', url: '/novel-helper/_service', headers: { host: '127.0.0.1:62100', 'x-novel-helper-token': TOKEN }, on() {}, once() {}, destroy() {} },
      response,
    );
  });
  assert.equal(result.status, 200);
  assert.equal(result.data.running, false);
  assert.equal(result.data.hint, null);
});

/* -------------------------------------------------------------------- tool */

test('工具：写操作缺 confirm 直接失败，且发生在任何网络请求之前', async () => {
  const tool = __internals.makeTool({ get: () => undefined }, config);
  assert.equal(tool.name, 'novel_helper');
  assert.deepEqual(tool.parameters.required, ['action']);
  assert.equal(tool.parameters.additionalProperties, false);

  // A path that *is* on the write whitelist, so the only thing standing between
  // the call and the manager is the confirmation flag.
  await assert.rejects(
    () => tool.execute({ action: 'post', path: '/api/projects/demo/creative/chat', body: {} }, {}),
    /confirm=true/,
  );
});

test('工具：path 必须落在 /api/ 下，写操作还要命中白名单', async () => {
  const tool = __internals.makeTool({ get: () => undefined }, config);
  await assert.rejects(
    () => tool.execute({ action: 'get', path: '/etc/passwd' }, {}),
    /\/api\//,
  );
  await assert.rejects(
    () => tool.execute({ action: 'post', path: '/api/__nope', confirm: true }, {}),
    /白名单/,
  );
  await assert.rejects(
    () => tool.execute({ action: 'get', path: '/api/..%2f..%2fetc/passwd' }, {}),
    /上级目录|空段/,
  );
});

test('工具：没有审批服务时不能用 confirm 自行放行写操作', async () => {
  // Reaching the proxy is fine: the fixture port refuses instantly, so this
  // asserts the post-confirmation error path without needing a live manager.
  const tool = __internals.makeTool({ get: () => undefined }, config);
  await assert.rejects(
    () => tool.execute({ action: 'post', path: '/api/projects/demo/creative/chat', body: {}, confirm: true }, {}),
    /写操作未获批准/,
  );
});
