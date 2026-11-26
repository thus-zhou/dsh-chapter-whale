import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, rm, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createHandler, resolveConfig } from '../index.js';
import { expectedManagerRelease } from '../managed-runtime.mjs';

test('managed manager fingerprint matches the actual distributed Python algorithm', () => {
  const result = spawnSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'), ['-B', '-c',
    "import sys; sys.path.insert(0, 'backend'); from manager.runtime_health import release_id; print(release_id())"],
    { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(expectedManagerRelease(), result.stdout.trim());
});

test('same workspace old backend is not ready and an unverified process is preserved', async () => {
  const root = await mkdtemp(join(tmpdir(), 'cw-upgrade-'));
  const marker = join(root, '.chapter-whale-release.json');
  await writeFile(marker, JSON.stringify({ buildId: 'old-release' }));
  const backend = createServer((req, res) => {
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ service: 'novel-helper-manager', root, release_id: 'old-code',
      pid: process.pid, startup_id: 'old-instance', mode: 'dsh_managed' }));
  });
  await new Promise(r => backend.listen(0, '127.0.0.1', r));
  const config = resolveConfig({ rootDir: root, python: process.env.PYTHON || 'python', port: backend.address().port });
  config.managed = true;
  const host = createServer(createHandler(config, 'fixture'));
  await new Promise(r => host.listen(0, '127.0.0.1', r));
  try {
    const url = `http://127.0.0.1:${host.address().port}/novel-helper/_service`;
    for (const method of ['GET', 'POST']) {
      const response = await fetch(url, { method, headers: { 'x-novel-helper-token': 'fixture' } });
      const state = await response.json();
      assert.equal(state.running, false);
      assert.equal(state.ok, false);
      assert.equal(state.upgradeRequired, true);
    }
    assert.equal(JSON.parse(await readFile(marker, 'utf8')).buildId, 'old-release');
    assert.equal(backend.listening, true);
  } finally {
    host.closeAllConnections(); backend.closeAllConnections();
    await Promise.all([new Promise(r => host.close(r)), new Promise(r => backend.close(r))]);
    await rm(root, { recursive: true, force: true });
  }
});
