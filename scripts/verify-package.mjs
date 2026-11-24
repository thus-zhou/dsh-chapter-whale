// Verify the actual tarball in an isolated workspace, never a developer install.
// Optional second tarball supplies the exact download body before publication.
import assert from 'node:assert/strict';
import { execFile, spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { promisify } from 'node:util';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, writeFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createServer } from 'node:http';
import { extractPackage } from '../managed-runtime.mjs';

const [archiveArg, downloadArg, outputArg] = process.argv.slice(2);
assert.ok(archiveArg, 'Usage: node scripts/verify-package.mjs package.tgz [download.tgz|-] [result.json]');
const execute = promisify(execFile);
const isolated = await mkdtemp(join(tmpdir(), 'cw-package-'));
await extractPackage(resolve(archiveArg), isolated);
const root = join(isolated, 'package');
const npmCli = [
  join(dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js'),
  join(dirname(dirname(process.execPath)), 'lib/node_modules/npm/bin/npm-cli.js'),
].find((candidate) => existsSync(candidate));
assert.ok(npmCli, 'Cannot locate npm-cli.js alongside Node');
await execute(process.execPath,
  [npmCli, 'install', '--omit=dev', '--ignore-scripts', '--no-audit', '--no-fund'],
  { cwd: root, windowsHide: true, timeout: 180000 });
const { prepareManaged, managedEnvironment, managedPythonPath } = await import(pathToFileURL(join(root, 'managed-runtime.mjs')));
const { resolveConfig, createHandler } = await import(pathToFileURL(join(root, 'index.js')));
const manifest = JSON.parse(await readFile(join(root, 'runtime-manifest.json'), 'utf8'));
const reservation = createServer();
await new Promise(done => reservation.listen(0, '127.0.0.1', done));
const port = reservation.address().port;
await new Promise(done => reservation.close(done));
const workspace = join(isolated, 'workspace');
await mkdir(workspace);
const pythonBin = typeof managedPythonPath === 'function'
  ? managedPythonPath(workspace)
  : (process.platform === 'win32'
    ? join(workspace, '.venv', 'Scripts', 'python.exe')
    : join(workspace, '.venv', 'bin', 'python3'));
const config = resolveConfig({ rootDir: workspace, port });
Object.assign(config, { managed: true, configuredRoot: false, python: pythonBin });
const realFetch = globalThis.fetch;
let downloads = 0;
if (downloadArg && downloadArg !== '-') {
  const spec = JSON.parse(await readFile(join(root, 'runtime-download.json'), 'utf8'));
  globalThis.fetch = async (url, options) => {
    if (url === spec.url) {
      downloads += 1;
      return new Response(await readFile(resolve(downloadArg)));
    }
    return realFetch(url, options);
  };
}
const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
const archiveBytes = await readFile(resolve(archiveArg));
const result = { archive: resolve(archiveArg), version: pkg.version, runtimeVersion: manifest.version, buildId: manifest.buildId,
  archiveBytes: archiveBytes.length,
  archiveSha256: createHash('sha256').update(archiveBytes).digest('hex'),
  workspace, source: downloadArg && downloadArg !== '-' ? 'exact-local-release-bytes' : 'bundled-or-live', checks: [] };
const handler = createHandler(config, 'isolated-package-check');
const server = createServer(handler);
await new Promise(done => server.listen(0, '127.0.0.1', done));
const base = `http://127.0.0.1:${server.address().port}/novel-helper`;
async function api(path, body) {
  const response = await realFetch(base + path, { method: body ? 'POST' : 'GET',
    headers: { 'x-novel-helper-token': 'isolated-package-check', 'content-type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined });
  const data = await response.json();
  assert.ok(response.ok, JSON.stringify(data));
  return data;
}
try {
  await prepareManaged(config);
  const marker = JSON.parse(await readFile(join(workspace, '.chapter-whale-release.json'), 'utf8'));
  assert.equal(marker.buildId, manifest.buildId);
  if (marker.runtimeKind === 'downloaded') {
    const spec = JSON.parse(await readFile(join(root, 'runtime-download.json'), 'utf8'));
    if (spec.runtimeAssetBuildId) {
      assert.equal(marker.runtimeBuildId, spec.runtimeAssetBuildId);
      assert.equal(marker.codeBuildId, manifest.buildId);
      result.checks.push('downloaded runtime and installed backend retain separate pinned build IDs');
    }
  }
  result.checks.push('actual package prepareManaged and complete backend hash verification');
  const started = await api('/_service', {});
  assert.equal(started.running, true, JSON.stringify(started));
  const overview = await api('/api/overview');
  assert.equal(overview.projects.length, 0);
  assert.equal(overview.accounts.length, 0);
  assert.equal(overview.ai.configured, false);
  assert.equal(overview.settings.scheduler_enabled, false);
  result.checks.push('server starts with empty books/accounts/credentials and scheduling disabled');
  const python = spawn(config.python, ['-B', '-c',
    "from integration.writer_runner import _load_webnovel_services; _load_webnovel_services(); from services.skill_executor import SKILLS_DIR; assert SKILLS_DIR.is_dir(); print('writer-loaded')"],
    { cwd: workspace, windowsHide: true, env: managedEnvironment(config), stdio: ['ignore', 'pipe', 'pipe'] });
  let logs = '';
  python.stdout.on('data', chunk => logs += chunk);
  python.stderr.on('data', chunk => logs += chunk);
  assert.equal(await new Promise(done => python.on('exit', done)), 0, logs);
  result.checks.push('bundled interpreter imports writing service and complete prompts');
  result.success = true;
} catch (error) {
  result.success = false;
  result.error = String(error?.stack || error);
  process.exitCode = 1;
} finally {
  globalThis.fetch = realFetch;
  try { result.stopped = await api('/_stop', {}); } catch (error) { result.stopError = String(error); }
  server.closeAllConnections();
  await new Promise(done => server.close(done));
  result.downloads = downloads;
  if (outputArg) {
    await mkdir(resolve(outputArg, '..'), { recursive: true });
    await writeFile(outputArg, JSON.stringify(result, null, 2) + '\n');
  }
  console.log(JSON.stringify(result, null, 2));
}
