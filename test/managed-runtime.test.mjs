// P01：代码来源与运行环境来源必须彻底分离。
// 夹具模拟“轻量包”：代码只有本包的 backend，运行环境要么内置、要么按清单下载。
// 下载替身里故意放一份“旧版本后端标记”，任何情况下都不允许被复制进工作区。
import test from 'node:test';
import assert from 'node:assert/strict';
import { cp, mkdir, mkdtemp, readFile, rm, writeFile, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { c as createTar } from 'tar';

const PACKAGE_SOURCE = new URL('../managed-runtime.mjs', import.meta.url);
const TEST_ROOT = fileURLToPath(new URL('.', import.meta.url));

const NEW_MARKER = 'NEW-BACKEND-0.6.0';
const OLD_MARKER = 'OLD-BACKEND-0.4.2';

function sha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

async function freshDir(prefix) {
  return mkdtemp(join(TEST_ROOT, `${prefix}-`));
}

async function writeTree(root, files) {
  for (const [relative, content] of Object.entries(files)) {
    const target = join(root, ...relative.split('/'));
    await mkdir(join(target, '..'), { recursive: true });
    await writeFile(target, content);
  }
}

async function readTree(root, files) {
  const out = {};
  for (const relative of Object.keys(files)) {
    try { out[relative] = await readFile(join(root, ...relative.split('/')), 'utf8'); } catch { out[relative] = null; }
  }
  return out;
}

const CODE = {
  'manager/app.py': `${NEW_MARKER}\nprint("manager")\n`,
  'integration/writer_runner.py': `${NEW_MARKER}\nprint("integration")\n`,
  'webnovel-writer/skill.md': `${NEW_MARKER}\n`,
  'fanqie_auto_publish/publish.py': `${NEW_MARKER}\n`,
  'vendor/ofm.py': `${NEW_MARKER}\n`,
};

async function manifestFor(files, buildId, includeRuntime) {
  const entries = {};
  for (const [relative, content] of Object.entries(files)) {
    entries[`backend/${relative}`] = sha256(Buffer.from(content));
  }
  if (includeRuntime) {
    entries['runtime/python/python.exe'] = sha256(Buffer.from('interpreter'));
    entries['runtime/browsers/chromium/icudtl.dat'] = sha256(Buffer.from('browser'));
  }
  return { version: '0.6.0', buildId, platform: 'win32-x64', files: entries };
}

// 一个“完整包”（内置 runtime）或“轻量包”（只有代码 + 下载描述）。
async function makePackage({ buildId = 'cand-a', bundled = true, code = CODE, extra = {} } = {}) {
  const root = await freshDir('pkg');
  await writeTree(join(root, 'backend'), code);
  for (const [relative, content] of Object.entries(extra)) {
    await writeFile(join(root, ...relative.split('/')), content);
  }
  await cp(PACKAGE_SOURCE, join(root, 'managed-runtime.mjs'));
  if (bundled) {
    await mkdir(join(root, 'runtime', 'python'), { recursive: true });
    await mkdir(join(root, 'runtime', 'browsers', 'chromium'), { recursive: true });
    await writeFile(join(root, 'runtime', 'python', 'python.exe'), 'interpreter');
    await writeFile(join(root, 'runtime', 'browsers', 'chromium', 'icudtl.dat'), 'browser');
  }
  const manifest = await manifestFor(code, buildId, bundled);
  await writeFile(join(root, 'runtime-manifest.json'), JSON.stringify(manifest, null, 2));
  return { root, manifest };
}

// 下载替身：一个带 package/ 前缀的 tgz，内部 backend 是旧版本，runtime 与运行时清单是本版。
async function makePayload({ buildId = 'cand-a', backendMarker = OLD_MARKER } = {}) {
  const stage = await freshDir('payload');
  const payload = join(stage, 'package');
  const oldCode = Object.fromEntries(Object.keys(CODE).map((key) => [key, `${backendMarker}\n`]));
  await writeTree(join(payload, 'backend'), oldCode);
  await mkdir(join(payload, 'runtime', 'python'), { recursive: true });
  await mkdir(join(payload, 'runtime', 'browsers', 'chromium'), { recursive: true });
  await writeFile(join(payload, 'runtime', 'python', 'python.exe'), 'interpreter');
  await writeFile(join(payload, 'runtime', 'browsers', 'chromium', 'icudtl.dat'), 'browser');
  await writeFile(join(payload, 'runtime-manifest.json'),
    JSON.stringify(await manifestFor(oldCode, buildId, true), null, 2));
  const archive = join(stage, 'runtime.tgz');
  await createTar({ file: archive, cwd: stage, gzip: true }, ['package']);
  const bytes = await readFile(archive);
  return { stage, archive, bytes, sha256: sha256(bytes), buildId };
}

async function writeDownloadSpec(root, payload, overrides = {}) {
  const spec = {
    url: `https://github.com/thus-zhou/dsh-chapter-whale/releases/download/v0.6.0/${'dsh-chapter-whale-runtime-win32-x64-0.6.0.tgz'}`,
    bytes: payload.bytes.length,
    sha256: payload.sha256,
    buildId: payload.buildId,
    ...overrides,
  };
  await writeFile(join(root, 'runtime-download.json'), JSON.stringify(spec));
  return spec;
}

async function loadModule(packageRoot) {
  // 每个夹具都有自己的 managed-runtime.mjs，PACKAGE_ROOT 才指向夹具而不是本仓库。
  return import(`${pathToFileURL(join(packageRoot, 'managed-runtime.mjs')).href}?v=${Date.now()}-${Math.random()}`);
}

function configFor(workspace) {
  return {
    managed: true,
    rootDir: workspace,
    python: join(workspace, '.venv', 'Scripts', 'python.exe'),
    entry: join(workspace, 'manager', 'app.py'),
  };
}

async function withFetch(bytes, worker) {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(bytes);
  try { return await worker(); } finally { globalThis.fetch = original; }
}

test('P01 代码来源恒为本包 backend，内置 runtime 时运行环境同源', async () => {
  const pkg = await makePackage();
  const mod = await loadModule(pkg.root);
  assert.equal(mod.codeSource(), pkg.root);
  const runtime = await mod.resolveRuntimeSource(join(pkg.root, 'ws'), pkg.manifest);
  assert.equal(runtime.kind, 'bundled');
  assert.equal(runtime.buildId, 'cand-a');
  await rm(pkg.root, { recursive: true, force: true });
});

test('P01 轻量包内置 runtime 时安装成功并写入候选标记', { skip: process.platform !== 'win32' }, async () => {
  const pkg = await makePackage({ bundled: true });
  const mod = await loadModule(pkg.root);
  const workspace = await freshDir('ws');
  const config = configFor(workspace);
  await mod.prepareManaged(config);
  assert.equal(config.entryExists, true);
  const installed = await readTree(workspace, CODE);
  for (const [key, value] of Object.entries(CODE)) assert.equal(installed[key], value, key);
  const marker = JSON.parse(await readFile(join(workspace, '.chapter-whale-release.json'), 'utf8'));
  assert.equal(marker.buildId, 'cand-a');
  assert.equal(marker.codeBuildId, 'cand-a');
  assert.equal(marker.runtimeBuildId, 'cand-a');
  assert.equal(marker.runtimeKind, 'bundled');
  assert.ok(marker.codeFiles.includes('backend/manager/app.py'));
  assert.ok(existsSync(join(workspace, '.venv', 'Scripts', 'python.exe')));
  assert.ok(existsSync(join(workspace, 'playwright-browsers', 'chromium', 'icudtl.dat')));
  assert.ok(existsSync(join(workspace, 'integration_data')));
  assert.ok(!existsSync(join(workspace, '.install-lock')));
  await rm(pkg.root, { recursive: true, force: true });
  await rm(workspace, { recursive: true, force: true });
});

test('P01 下载替身夹带旧 backend 时绝不复用，安装后后端仍是本包代码', { skip: process.platform !== 'win32' }, async () => {
  const pkg = await makePackage({ bundled: false, code: Object.fromEntries(
    Object.entries(CODE).map(([key, value]) => [key, value])) });
  const payload = await makePayload({ backendMarker: OLD_MARKER });
  await writeDownloadSpec(pkg.root, payload);
  const mod = await loadModule(pkg.root);
  const workspace = await freshDir('ws');
  const config = configFor(workspace);
  await withFetch(payload.bytes, () => mod.prepareManaged(config));
  assert.equal(config.entryExists, true);
  const installed = await readTree(workspace, CODE);
  for (const [key, value] of Object.entries(CODE)) {
    assert.equal(installed[key], value, `下载包不得覆盖 ${key}`);
    assert.ok(!installed[key].includes(OLD_MARKER), `旧后端被写入 ${key}`);
  }
  const marker = JSON.parse(await readFile(join(workspace, '.chapter-whale-release.json'), 'utf8'));
  assert.equal(marker.runtimeKind, 'downloaded');
  assert.equal(marker.codeBuildId, marker.runtimeBuildId);
  // 下载包的 backend 连临时解包目录里的字节都不该被读进工作区
  assert.ok(!existsSync(join(workspace, 'runtime')));
  await rm(pkg.root, { recursive: true, force: true });
  await rm(payload.stage, { recursive: true, force: true });
  await rm(workspace, { recursive: true, force: true });
});

test('P01 下载字节与清单不符时明确拒绝且不写发行标记', { skip: process.platform !== 'win32' }, async () => {
  const pkg = await makePackage({ bundled: false });
  const payload = await makePayload();
  await writeDownloadSpec(pkg.root, payload, { sha256: 'f'.repeat(64) });
  const mod = await loadModule(pkg.root);
  const workspace = await freshDir('ws');
  await assert.rejects(
    () => withFetch(payload.bytes, () => mod.prepareManaged(configFor(workspace))),
    /运行环境校验失败/,
  );
  assert.ok(!existsSync(join(workspace, '.chapter-whale-release.json')));
  assert.ok(!existsSync(join(workspace, '.install-lock')));
  assert.ok(!existsSync(join(workspace, 'manager', 'app.py')));
  await rm(pkg.root, { recursive: true, force: true });
  await rm(payload.stage, { recursive: true, force: true });
  await rm(workspace, { recursive: true, force: true });
});

test('P01 下载包 buildId 与代码清单不一致时拒绝安装', { skip: process.platform !== 'win32' }, async () => {
  const pkg = await makePackage({ bundled: false, buildId: 'cand-a' });
  const payload = await makePayload({ buildId: 'cand-a' });
  // 下载描述与代码清单一致，但包内 runtime-manifest.json 是另一个候选
  const stage = await freshDir('payload-b');
  const inner = join(stage, 'package');
  await mkdir(join(inner, 'runtime', 'python'), { recursive: true });
  await mkdir(join(inner, 'runtime', 'browsers', 'chromium'), { recursive: true });
  await writeFile(join(inner, 'runtime', 'python', 'python.exe'), 'interpreter');
  await writeFile(join(inner, 'runtime', 'browsers', 'chromium', 'icudtl.dat'), 'browser');
  await writeFile(join(inner, 'runtime-manifest.json'), JSON.stringify({ buildId: 'cand-z', files: {} }));
  const archive = join(stage, 'runtime.tgz');
  await createTar({ file: archive, cwd: stage, gzip: true }, ['package']);
  const bytes = await readFile(archive);
  await writeDownloadSpec(pkg.root, { bytes, sha256: sha256(bytes), buildId: 'cand-a' });
  const mod = await loadModule(pkg.root);
  const workspace = await freshDir('ws');
  await assert.rejects(
    () => withFetch(bytes, () => mod.prepareManaged(configFor(workspace))),
    /发行包版本不匹配/,
  );
  assert.ok(!existsSync(join(workspace, '.chapter-whale-release.json')));
  await rm(pkg.root, { recursive: true, force: true });
  await rm(stage, { recursive: true, force: true });
  await rm(payload.stage, { recursive: true, force: true });
  await rm(workspace, { recursive: true, force: true });
});

test('P01 缺少后端源码时明确失败，不回退到下载包后端', { skip: process.platform !== 'win32' }, async () => {
  const pkg = await makePackage({ bundled: false });
  await rm(join(pkg.root, 'backend', 'manager'), { recursive: true, force: true });
  const mod = await loadModule(pkg.root);
  assert.throws(() => mod.codeSource(), /backend\/manager\/app\.py/);
  const workspace = await freshDir('ws');
  await assert.rejects(() => mod.prepareManaged(configFor(workspace)), /安装包缺少运行环境/);
  assert.ok(!existsSync(join(workspace, '.chapter-whale-release.json')));
  await rm(pkg.root, { recursive: true, force: true });
  await rm(workspace, { recursive: true, force: true });
});

test('P01 两个安装者并发时后到者被安装锁拒绝', { skip: process.platform !== 'win32' }, async () => {
  const pkg = await makePackage();
  const mod = await loadModule(pkg.root);
  const workspace = await freshDir('ws');
  await mkdir(join(workspace, '.install-lock'));
  await assert.rejects(() => mod.prepareManaged(configFor(workspace)), /另一个码章鲸实例正在准备环境/);
  await rm(pkg.root, { recursive: true, force: true });
  await rm(workspace, { recursive: true, force: true });
});

test('P01 升级清理只删旧清单管理的代码文件，作者数据与凭据保持原样', { skip: process.platform !== 'win32' }, async () => {
  const stale = { ...CODE, 'integration/legacy_module.py': 'LEGACY\n' };
  const v1 = await makePackage({ buildId: 'cand-v1', code: stale });
  const mod1 = await loadModule(v1.root);
  const workspace = await freshDir('ws');
  const config = configFor(workspace);
  await mod1.prepareManaged(config);
  // 作者数据、账本、登录态与旧版本残留
  const authorFiles = {
    'accounts/primary.json': '{"cookie":"secret"}',
    'books/潮汐钟/chapters.json': '{"chapter":1}',
    'integration_data/ledger.sqlite': 'ledger',
    'integration_data/.dpapi': 'keyfile',
    'scheduler.json': '{"jobs":{}}',
    '正文/第1章.txt': '旧稿',
  };
  await writeTree(workspace, authorFiles);
  const v2 = await makePackage({ buildId: 'cand-v2', code: CODE });
  const mod2 = await loadModule(v2.root);
  const config2 = configFor(workspace);
  await mod2.prepareManaged(config2);
  assert.ok(!existsSync(join(workspace, 'integration', 'legacy_module.py')), '旧版本代码应被清理');
  assert.equal(await readFile(join(workspace, 'manager', 'app.py'), 'utf8'), CODE['manager/app.py']);
  const after = await readTree(workspace, authorFiles);
  for (const [key, value] of Object.entries(authorFiles)) assert.equal(after[key], value, `${key} 不得被清理`);
  const marker = JSON.parse(await readFile(join(workspace, '.chapter-whale-release.json'), 'utf8'));
  assert.equal(marker.buildId, 'cand-v2');
  assert.ok(!marker.codeFiles.includes('backend/integration/legacy_module.py'));
  await rm(v1.root, { recursive: true, force: true });
  await rm(v2.root, { recursive: true, force: true });
  await rm(workspace, { recursive: true, force: true });
});

test('P01 staleCodeFiles 永不返回作者数据或跨界路径', async () => {
  const pkg = await makePackage();
  const mod = await loadModule(pkg.root);
  const workspace = await freshDir('ws');
  const stale = mod.staleCodeFiles(workspace, [
    'backend/manager/gone.py',
    'backend/integration_data/secret.json',
    'backend/accounts/cookie.json',
    'backend/books/x/chapters.json',
    'backend/vendor/.dpapi',
    'backend/playwright-browsers/x.bin',
    'backend/../escape.py',
    'backend/manager/../../../escape.py',
    'runtime/python/python.exe',
    'docs/readme.md',
    'backend/manager/app.py',
  ], ['backend/manager/app.py']);
  assert.deepEqual(stale, [join(workspace, 'manager', 'gone.py')]);
  await rm(pkg.root, { recursive: true, force: true });
  await rm(workspace, { recursive: true, force: true });
});

test('P01 已装候选再次启动时只做校验，不重复复制', { skip: process.platform !== 'win32' }, async () => {
  const pkg = await makePackage();
  const mod = await loadModule(pkg.root);
  const workspace = await freshDir('ws');
  const config = configFor(workspace);
  await mod.prepareManaged(config);
  const marker = JSON.parse(await readFile(join(workspace, '.chapter-whale-release.json'), 'utf8'));
  await writeTree(workspace, { 'manager/app.py': 'TAMPERED\n' });
  await assert.rejects(() => mod.prepareManaged(config), /已安装的后端与发行清单不一致/);
  assert.equal(config.entryExists, false);
  // 标记仍在，但下次启动会因为校验失败继续要求重装，不会静默使用被改写的后端
  assert.equal(JSON.parse(await readFile(join(workspace, '.chapter-whale-release.json'), 'utf8')).buildId, marker.buildId);
  await rm(pkg.root, { recursive: true, force: true });
  await rm(workspace, { recursive: true, force: true });
});
