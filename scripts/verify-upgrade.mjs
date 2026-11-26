// Verify the actual previous and current package bytes across Host sessions.
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createServer } from 'node:http';
import { extractPackage } from '../managed-runtime.mjs';

const [oldArg, newArg, runtimeArg, outputArg] = process.argv.slice(2);
assert.ok(oldArg && newArg && runtimeArg && outputArg, 'old.tgz new.tgz runtime.tgz result.json');
const execute = promisify(execFile);
const sandbox = await mkdtemp(join(tmpdir(), 'cw-upgrade-'));
const workspace = join(sandbox, 'workspace');
await mkdir(workspace);
const npmCli = [join(dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js'),
  join(dirname(dirname(process.execPath)), 'lib/node_modules/npm/bin/npm-cli.js')].find(existsSync);
const packages = [];
for (const [name, archive] of [['old', oldArg], ['new', newArg]]) {
  const dir = join(sandbox, name);
  await mkdir(dir);
  await extractPackage(resolve(archive), dir);
  const root = join(dir, 'package');
  await execute(process.execPath, [npmCli, 'install', '--omit=dev', '--ignore-scripts', '--no-audit', '--no-fund'],
    { cwd: root, windowsHide: true, timeout: 180000 });
  packages.push({ root, runtime: await import(pathToFileURL(join(root, 'managed-runtime.mjs'))),
    host: await import(pathToFileURL(join(root, 'index.js'))) });
}
const reservation = createServer();
await new Promise(r => reservation.listen(0, '127.0.0.1', r));
const port = reservation.address().port;
await new Promise(r => reservation.close(r));
const originalFetch = globalThis.fetch;
const runtimeBytes = await readFile(resolve(runtimeArg));
const spec = JSON.parse(await readFile(join(packages[0].root, 'runtime-download.json'), 'utf8'));
globalThis.fetch = (url, options) => url === spec.url ? Promise.resolve(new Response(runtimeBytes)) : originalFetch(url, options);
const servers = [];
async function connect(pkg) {
  const config = pkg.host.resolveConfig({ rootDir: workspace, port });
  Object.assign(config, { managed: true, configuredRoot: false, python: pkg.runtime.managedPythonPath(workspace) });
  const server = createServer(pkg.host.createHandler(config, 'upgrade-fixture'));
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  servers.push(server);
  return async (path, method = 'GET') => {
    const response = await originalFetch(`http://127.0.0.1:${server.address().port}/novel-helper${path}`,
      { method, headers: { 'x-novel-helper-token': 'upgrade-fixture' } });
    assert.ok(response.ok);
    return response.json();
  };
}
const result = { workspace, checks: [] };
let oldApi, newApi;
try {
  await packages[0].runtime.prepareManaged({ managed: true, rootDir: workspace,
    python: packages[0].runtime.managedPythonPath(workspace), entry: join(workspace, 'manager/app.py') });
  oldApi = await connect(packages[0]);
  assert.equal((await oldApi('/_service', 'POST')).running, true);
  const oldHealth = await (await originalFetch(`http://127.0.0.1:${port}/api/health`)).json();
  newApi = await connect(packages[1]);
  const stale = await newApi('/_service');
  assert.equal(stale.running, false);
  assert.equal(stale.upgradeRequired, true);
  result.checks.push('previous package process is detected as stale across Host sessions');
  let started = await newApi('/_service', 'POST');
  if (!started.running && started.upgradeRequired) {
    assert.equal((await newApi('/_stop', 'POST')).stopped, true);
    result.checks.push('legacy backend without dispatch barrier requires an explicit stop before upgrading');
    started = await newApi('/_service', 'POST');
  }
  assert.equal(started.running, true, JSON.stringify(started));
  const health = await (await originalFetch(`http://127.0.0.1:${port}/api/health`)).json();
  assert.notEqual(health.pid, oldHealth.pid);
  assert.notEqual(health.release_id, oldHealth.release_id);
  assert.equal(health.release_id, packages[1].runtime.expectedManagerRelease());
  const marker = JSON.parse(await readFile(join(workspace, '.chapter-whale-release.json'), 'utf8'));
  const manifest = JSON.parse(await readFile(join(packages[1].root, 'runtime-manifest.json'), 'utf8'));
  assert.equal(marker.buildId, manifest.buildId);
  result.checks.push('verified idle instance is stopped, new backend installed, new process fingerprint and marker verified');
  result.oldRelease = oldHealth.release_id;
  result.newRelease = health.release_id;
  result.success = true;
} catch (error) {
  result.success = false;
  result.error = String(error.stack || error);
  process.exitCode = 1;
} finally {
  try { result.stopped = await (newApi || oldApi)('/_stop', 'POST'); } catch {}
  for (const server of servers) {
    server.closeAllConnections();
    await new Promise(r => server.close(r));
  }
  globalThis.fetch = originalFetch;
  await writeFile(outputArg, JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
}
