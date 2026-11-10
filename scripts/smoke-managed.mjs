import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, readFile, writeFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { resolveConfig, createHandler } from '../index.js';
import { managedEnvironment } from '../managed-runtime.mjs';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const workspace = await mkdtemp(join(tmpdir(), 'chapter-whale-clean-'));
const reservation = createServer();
await new Promise((done) => reservation.listen(0, '127.0.0.1', done));
const port = reservation.address().port;
await new Promise((done) => reservation.close(done));
const config = resolveConfig({ rootDir: workspace, port });
Object.assign(config, { managed: true, configuredRoot: false, python: join(workspace, '.venv', 'Scripts', 'python.exe') });
const token = 'isolated-smoke-test-token';
const bridge = createHandler(config, token);
const uiRoot = join(root, '.tmp', 'ui', 'node_modules');
const server = createServer(async (req, res) => {
  if (req.url.startsWith('/novel-helper')) return bridge(req, res);
  const resources = { '/react.js': join(uiRoot, 'react', 'umd', 'react.development.js'),
    '/react-dom.js': join(uiRoot, 'react-dom', 'umd', 'react-dom.development.js'), '/client.js': join(root, 'client.js') };
  if (resources[req.url]) { res.setHeader('content-type', 'application/javascript'); res.end(await readFile(resources[req.url])); return; }
  res.setHeader('content-type', 'text/html; charset=utf-8');
  res.end(`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0"><div id="app"></div><script src="/react.js"></script><script src="/react-dom.js"></script><script>
  window.__ModuleLoader__={load(def){const mod=def.factory(x=>{if(x==='react')return React;throw Error(x)});mod.apply({effect(fn){return fn()},get(){return undefined},slots:{inject(name,fn){return fn()},register(meta,view){if(meta.name==='main')ReactDOM.createRoot(document.getElementById('app')).render(React.createElement(view));return ()=>{}}}})}};
  </script><script src="/client.js"></script></body></html>`);
});
await new Promise((done) => server.listen(0, '127.0.0.1', done));
const base = `http://127.0.0.1:${server.address().port}`;
async function api(path, body) {
  const response = await fetch(base + '/novel-helper' + path, { method: body === undefined ? 'GET' : 'POST',
    headers: { 'x-novel-helper-token': token, 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json();
  assert.ok(response.ok, JSON.stringify(data));
  return data;
}
const results = { workspace, node: process.version, port, checks: [] };
try {
  const started = await api('/_service', {});
  assert.equal(started.running, true, JSON.stringify(started));
  results.checks.push('fresh workspace starts with bundled Python; no developer rootDir or Python used');
  const overview = await api('/api/overview');
  assert.equal(overview.projects.length, 0); assert.equal(overview.accounts.length, 0); assert.equal(overview.ai.configured, false);
  assert.equal(overview.settings.scheduler_enabled, false);
  results.checks.push('no inherited books, accounts, model credentials or enabled schedules');
  const python = spawn(config.python, ['-c', "from integration.writer_runner import _load_webnovel_services; E,_=_load_webnovel_services(); from services.skill_executor import SKILLS_DIR; assert SKILLS_DIR.is_dir(); print('writer-loaded')"],
    { cwd: workspace, windowsHide: true, env: managedEnvironment(config), stdio: ['ignore', 'pipe', 'pipe'] });
  let logs=''; python.stdout.on('data',x=>logs+=x);python.stderr.on('data',x=>logs+=x);
  const code = await new Promise((done) => python.on('exit',done));
  assert.equal(code,0,logs); results.checks.push('bundled interpreter imports complete writing engine and prompts');
  const browser = spawn(config.python, [join(root, 'scripts', 'smoke-ui.py'), base, root], { cwd: workspace, windowsHide: true, env: managedEnvironment(config), stdio: 'inherit' });
  assert.equal(await new Promise((done) => browser.on('exit',done)),0);
  results.checks.push('browser: create project, route to AI settings, choose project, open publish and verify disabled submission without login');
  results.success=true;
} catch(error) { results.success=false;results.error=String(error?.stack||error);console.error(results.error); process.exitCode=1; }
finally {
  try { results.stopped=await api('/_stop',{}); } catch(error){results.stopError=String(error)}
  server.closeAllConnections();await new Promise((done)=>server.close(done));
  await mkdir(join(root,'verification'),{recursive:true});
  await writeFile(join(root,'verification','smoke-managed.json'), JSON.stringify(results,null,2)+'\n');
  console.log(JSON.stringify(results,null,2));
}
