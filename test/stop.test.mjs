/**
 * `POST /novel-helper/_stop` — the only endpoint that can end a process.
 *
 * The interesting property is not "does SIGTERM arrive" (that would need a real
 * child) but "does it ever reach a manager this plugin did not start". So the
 * fixture is a fake manager that answers /api/health with a pid nobody owns:
 * the handler must answer 409 and leave it running.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';

import { createHandler, resolveConfig, __internals } from '../index.js';

const TOKEN = 'test-token-stop';
const FOREIGN_PID = 999_999;

function makeFixture() {
  const directory = mkdtempSync(join(tmpdir(), 'novel-helper-stop-'));
  mkdirSync(join(directory, 'manager'), { recursive: true });
  writeFileSync(join(directory, 'manager', 'app.py'), '# fixture entry\n');
  return directory;
}

const fixture = makeFixture();

/** Start a fake manager that claims `pid` and counts hits. */
async function fakeManager(pid) {
  const hits = { health: 0 };
  const server = createServer((request, response) => {
    if (request.url === '/api/health') hits.health += 1;
    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ service: 'novel-helper-manager', status: 'healthy', pid }));
  });
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  return {
    port: server.address().port,
    hits,
    close: () => new Promise((done) => server.close(done)),
  };
}

function bridge(port) {
  const config = resolveConfig({ rootDir: fixture, port });
  const handle = createHandler(config, TOKEN);
  return ({ method = 'GET', url = '/', headers = {}, token = true } = {}) => {
    if (!url.startsWith(__internals.ROUTE)) url = `${__internals.ROUTE}${url}`;
    return new Promise((settle) => {
      const state = { status: 0, data: null };
      const response = {
        writeHead(status) {
          state.status = status;
          return this;
        },
        setHeader() {},
        getHeader() {
          return undefined;
        },
        end(chunk) {
          try {
            state.data = chunk ? JSON.parse(chunk) : null;
          } catch {
            state.data = chunk ? String(chunk) : null;
          }
          settle(state);
        },
        write() {},
      };
      const request = {
        method,
        url,
        headers: {
          host: '127.0.0.1:62100',
          ...(token ? { 'x-novel-helper-token': TOKEN } : {}),
          ...headers,
        },
        on() {},
        once() {},
        off() {},
        destroy() {},
        setEncoding() {},
        pipe() {},
      };
      handle(request, response).catch((error) => settle({ status: 500, data: String(error) }));
    });
  };
}

test.after(() => rmSync(fixture, { recursive: true, force: true }));

test('_stop 只接受 POST', async () => {
  const call = bridge(1);
  const result = await call({ url: '/_stop' });
  assert.equal(result.status, 405);
  assert.match(result.data.detail, /POST/);
});

test('_stop 需要令牌（和其余端点一样）', async () => {
  const call = bridge(1);
  const result = await call({ url: '/_stop', method: 'POST', token: false });
  assert.equal(result.status, 401);
  assert.equal(result.data.code, 'plugin-token-required');
});

test('_stop：没有服务在跑时是空操作，不是错误', async () => {
  const call = bridge(1); // port 1 never listens
  const result = await call({ url: '/_stop', method: 'POST' });
  assert.equal(result.status, 200);
  assert.equal(result.data.ok, false);
  assert.equal(result.data.running, false);
});

test('_stop 绝不动别人起的 manager：返回 409 且进程仍在', async () => {
  const manager = await fakeManager(FOREIGN_PID);
  try {
    const call = bridge(manager.port);
    const result = await call({ url: '/_stop', method: 'POST' });
    assert.equal(result.status, 409);
    assert.equal(result.data.code, 'foreign-process');
    assert.equal(result.data.pid, FOREIGN_PID);
    assert.match(result.data.detail, /不是本插件启动/);

    // Still serving: a foreign process must survive a stop request.
    const afterwards = await fetch(`http://127.0.0.1:${manager.port}/api/health`);
    assert.equal(afterwards.status, 200);
    assert.ok(manager.hits.health >= 2);
  } finally {
    await manager.close();
  }
});

test('P0 回归：/novel-helper/api/_stop 路由放行，多字节 UTF-8 令牌不抛 RangeError，陈旧 run-description 自动刷新', async () => {
  const { readFileSync } = await import('node:fs');
  const { writeRunDescription, SERVICE_NAME } = await import('../managed-runtime.mjs');
  const workspace = mkdtempSync(join(tmpdir(), 'cw-stop-reg-'));
  let port = 0;
  const fakePortServer = createServer((req, res) => {
    if (req.url === '/api/health') {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({
        ok: true,
        service: SERVICE_NAME,
        root: workspace,
        port,
        startup_id: 'startup-new-2',
        pid: process.pid,
      }));
      return;
    }
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ ok: true }));
  });
  await new Promise((resolve) => fakePortServer.listen(0, '127.0.0.1', resolve));
  port = fakePortServer.address().port;

  // Write stale startup_id for the same workspace rootDir + port
  writeRunDescription({ rootDir: workspace, port }, {
    root: workspace,
    port,
    startup_id: 'startup-old-1',
    pid: 99999999,
  });

  const config = resolveConfig({ rootDir: workspace, port, managed: false });
  const handle = createHandler(config, TOKEN);
  const hostServer = createServer(handle);
  await new Promise((resolve) => hostServer.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${hostServer.address().port}`;
  const base = `${origin}/novel-helper/api`;

  try {
    // Multi-byte UTF-8 token with same char length as TOKEN must return 401 cleanly (no RangeError)
    const badStatus = await new Promise((resolve, reject) => {
      const res = {
        statusCode: 0,
        setHeader() {},
        writeHead(status) { res.statusCode = status; },
        end() { resolve(res.statusCode); },
      };
      Promise.resolve(handle({
        method: 'GET',
        url: '/novel-helper/api/_service',
        headers: {
          host: '127.0.0.1',
          'x-novel-helper-token': '中'.repeat(TOKEN.length),
        },
        socket: { remoteAddress: '127.0.0.1' },
      }, res)).catch(reject);
    });
    assert.equal(badStatus, 401);

    // Stale startup_id matching same normalized root recovers via /_service and refreshes run-description.json
    const svcRes = await fetch(`${base}/_service`, {
      method: 'GET',
      headers: { 'x-novel-helper-token': TOKEN },
    });
    assert.equal(svcRes.status, 200);
    const svcData = await svcRes.json();
    assert.equal(svcData.running, true);
    assert.ok(!svcData.foreign);
    const refreshed = JSON.parse(readFileSync(join(workspace, 'integration_data', 'run-description.json'), 'utf8'));
    assert.equal(refreshed.startup_id, 'startup-new-2');

    // Close fakePortServer first so _stop sees an idle managed endpoint and returns 200 (not 403 route rejection)
    fakePortServer.closeAllConnections?.();
    await new Promise((resolve) => fakePortServer.close(() => resolve()));

    const stopRes = await fetch(`${base}/_stop`, {
      method: 'POST',
      headers: {
        'x-novel-helper-token': TOKEN,
        origin,
      },
    });
    assert.equal(stopRes.status, 200);
  } finally {
    hostServer.closeAllConnections?.();
    fakePortServer.closeAllConnections?.();
    await new Promise((resolve) => hostServer.close(() => resolve()));
    if (fakePortServer.listening) {
      await new Promise((resolve) => fakePortServer.close(() => resolve()));
    }
    rmSync(workspace, { recursive: true, force: true });
  }
});
