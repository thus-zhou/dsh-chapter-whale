// E 域（发行/文档/入口）回归：P2-21、P2-22、P2-23、P2-25、P3-3、P3-4、P3-5。
//
// Run: node --test scripts/test-release-fix.mjs
//
// 发行检查的夹具全部落在系统临时目录；只有 market/README/docs 的结构断言
// 读取本仓库快照。P3-5 用真实子进程验证 signal 中止会在启动超时前返回。
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { mkdtemp, mkdir, writeFile, readFile, rm, chmod, copyFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import net from 'node:net';

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const CHECKER = join(REPO, 'scripts', 'check-release.mjs');
const PACK_BUNDLE = join(REPO, 'scripts', 'pack-bundle.py');
const PACKAGE_VERSION = '0.7.5';
const RUNTIME_VERSION = '0.7.0';

// Python 的 sha256(json.dumps(files, sort_keys=True))。由 python3 预先算出，
// 用来证明 JS 复算逐字节一致，而不是拿 JS 结果自证。
const BASE_BUILD_ID = 'e5bacf281c1203df7716ad0e8dd738aa7ec149213534f8881ad10469222c0bb5';
const RESIDUE_BUILD_ID = '72f7c32a5d52543c15f28c2a7b1188801d983007645676c8d066d4cb4fdea449';

const SOURCES = {
  'backend/manager/app.py': 'print("manager")\n',
  'backend/integration/writer_runner.py': 'print("writer")\n',
  'backend/integration/__init__.py': '\n',
  'backend/fanqie_auto_publish/publication_safety.py': 'print("safety")\n',
  'backend/webnovel-writer/skill.md': '# skill\n',
  'backend/vendor/ofm.py': 'print("ofm")\n',
};

const sha = (buffer) => createHash('sha256').update(buffer).digest('hex');

async function makePackage({ buildId = BASE_BUILD_ID, packageVersion = PACKAGE_VERSION, extra = {} } = {}) {
  const root = await mkdtemp(join(tmpdir(), 'cw-release-'));
  const bodies = { ...SOURCES, ...extra };
  const files = {};
  for (const [name, body] of Object.entries(bodies)) {
    const path = join(root, ...name.split('/'));
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, body);
    files[name] = sha(Buffer.from(body));
  }
  // 薄源码检出不带 runtime，但清单里仍然要有它：--local 跳过磁盘检查，
  // 非 --local 必须把它当成完整包损坏。
  files['runtime/python/python.exe'] = sha(Buffer.from('interpreter'));
  await writeFile(join(root, 'runtime-manifest.json'), JSON.stringify({
    version: RUNTIME_VERSION, packageVersion, buildId, files,
  }, null, 2));
  await writeFile(join(root, 'package.json'), JSON.stringify({
    name: 'dsh-chapter-whale', version: PACKAGE_VERSION, license: 'GPL-3.0-only',
  }));
  await writeFile(join(root, 'runtime-download.json'), JSON.stringify({
    url: `https://github.com/thus-zhou/dsh-chapter-whale/releases/download/v${RUNTIME_VERSION}/dsh-chapter-whale-runtime-win32-x64-${RUNTIME_VERSION}.tgz`,
    bytes: 1234, sha256: 'a'.repeat(64), buildId,
    runtimeAssetBuildId: 'b'.repeat(64),
  }));
  return root;
}

function run(root, extra = []) {
  const result = spawnSync(process.execPath, [CHECKER, '--root', root, ...extra], { encoding: 'utf8' });
  return { code: result.status, out: `${result.stdout}${result.stderr}` };
}

async function withPackage(options, worker) {
  const root = await makePackage(options);
  try { return await worker(root); } finally { await rm(root, { recursive: true, force: true }); }
}

test('P2-21 只有 --local 允许跳过缺席的 runtime；完整包模式直接失败', async () => {
  await withPackage({}, async (root) => {
    const reportPath = join(root, 'report.json');
    const local = run(root, ['--local', '--json', reportPath]);
    assert.equal(local.code, 0, local.out);
    const report = JSON.parse(await readFile(reportPath, 'utf8'));
    assert.equal(report.checked, 6);
    assert.ok(report.skippedRuntime >= 1, '薄检出应报告跳过的 runtime 项数');

    const strict = run(root);
    assert.equal(strict.code, 1, '非 --local 缺 runtime 必须失败');
    assert.match(strict.out, /完整发行包缺少 runtime/i);
    assert.doesNotMatch(strict.out, /发行清单校验通过/);

    // 同一份清单补上真实 runtime 字节后，完整包模式必须通过（不是一味拒绝）。
    await mkdir(join(root, 'runtime', 'python'), { recursive: true });
    await writeFile(join(root, 'runtime', 'python', 'python.exe'), 'interpreter');
    const complete = run(root);
    assert.equal(complete.code, 0, complete.out);
    assert.match(complete.out, /发行清单校验通过：7 个文件/);
  });
});

test('P3-3 buildId 必须按 Python json.dumps 复算，packageVersion 必须等于 package.json', async () => {
  await withPackage({}, async (root) => {
    assert.equal(run(root, ['--local']).code, 0);
    const manifestPath = join(root, 'runtime-manifest.json');
    const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));

    manifest.buildId = '0'.repeat(64);
    await writeFile(manifestPath, JSON.stringify(manifest, null, 2));
    const stale = run(root, ['--local']);
    assert.equal(stale.code, 1);
    assert.match(stale.out, /buildId 与文件清单复算值不一致/);

    manifest.buildId = BASE_BUILD_ID;
    manifest.packageVersion = '0.7.4';
    await writeFile(manifestPath, JSON.stringify(manifest, null, 2));
    const wrongVersion = run(root, ['--local']);
    assert.equal(wrongVersion.code, 1);
    assert.match(wrongVersion.out, /packageVersion.*0\.7\.4.*package\.json 0\.7\.5/);
  });

  await withPackage({
    buildId: RESIDUE_BUILD_ID,
    extra: { 'backend/integration/test_residue.py': 'print("test")\n' },
  }, async (root) => {
    const residue = run(root, ['--local']);
    assert.equal(residue.code, 1);
    assert.match(residue.out, /test_residue\.py/);
    assert.doesNotMatch(residue.out, /buildId 与文件清单复算值不一致/, '本夹具的 buildId 是有效值');
  });
});

test('P2-23 market 保持已发布的 0.7.4；落后允许并给出 note，超前拒绝', async () => {
  const index = JSON.parse(await readFile(join(REPO, 'market', 'index.json'), 'utf8'));
  const losebird = JSON.parse(await readFile(join(REPO, 'market', 'losebird-entry.json'), 'utf8'));
  const catalog = await readFile(join(REPO, 'market', 'catalog-entry.yml'), 'utf8');
  assert.equal(index.plugins[0].versions.length, 1);
  assert.equal(index.plugins[0].versions[0].version, '0.7.4');
  assert.equal(losebird.version, '0.7.4');
  assert.equal(losebird.latestVersion, '0.7.4');
  assert.match(catalog, /releases\/download\/v0\.7\.4\//);
  for (const text of [JSON.stringify(index), JSON.stringify(losebird), catalog]) {
    assert.equal(text.includes('0.7.5'), false, '市场元数据不得指向尚未发布的 0.7.5');
  }

  const market = (version) => JSON.stringify({
    format: 1,
    plugins: [{ name: 'dsh-chapter-whale', versions: [{ version }] }],
  });
  await withPackage({}, async (root) => {
    await mkdir(join(root, 'market'));
    await writeFile(join(root, 'market', 'index.json'), market('0.7.4'));
    const lagging = run(root, ['--local']);
    assert.equal(lagging.code, 0, lagging.out);
    assert.match(lagging.out, /market\/index\.json 仍指向 0\.7\.4/);
  });
  await withPackage({}, async (root) => {
    await mkdir(join(root, 'market'));
    await writeFile(join(root, 'market', 'index.json'), market('0.8.0'));
    const ahead = run(root, ['--local']);
    assert.equal(ahead.code, 1);
    assert.match(ahead.out, /高于 package\.json 0\.7\.5/);
  });
});

test('P2-22 完整包按 manifest.version 命名且不覆盖已发布 runtime 描述', {
  skip: !pythonBinary() && 'python3/python not found',
  timeout: 120_000,
}, async () => {
  const root = await mkdtemp(join(tmpdir(), 'cw-pack-'));
  try {
    for (const tree of ['manager', 'integration', 'webnovel-writer', 'fanqie_auto_publish', 'vendor']) {
      await mkdir(join(root, 'backend', tree), { recursive: true });
    }
    await mkdir(join(root, 'scripts'), { recursive: true });
    await mkdir(join(root, 'runtime', 'python'), { recursive: true });
    await writeFile(join(root, 'backend', 'manager', 'app.py'), 'print("manager")\n');
    await writeFile(join(root, 'backend', 'integration', 'writer_runner.py'), 'print("writer")\n');
    await writeFile(join(root, 'backend', 'integration', '__init__.py'), '\n');
    await writeFile(join(root, 'backend', 'fanqie_auto_publish', 'publication_safety.py'), 'print("safety")\n');
    await writeFile(join(root, 'backend', 'webnovel-writer', 'skill.md'), '# skill\n');
    await writeFile(join(root, 'backend', 'vendor', 'ofm.py'), 'print("ofm")\n');
    await writeFile(join(root, 'runtime', 'python', 'python.exe'), 'interpreter');
    await copyFile(CHECKER, join(root, 'scripts', 'check-release.mjs'));
    await copyFile(PACK_BUNDLE, join(root, 'scripts', 'pack-bundle.py'));

    // Python 生成清单与 buildId，避免用被测的 JS 复算逻辑自证。
    const setup = `
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
files = {}
for path in sorted(root.glob('backend/**/*')):
    if path.is_file():
        files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
for name in ['scripts/check-release.mjs', 'runtime/python/python.exe']:
    files[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
build = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
(root / 'runtime-manifest.json').write_text(json.dumps({
    'version': '0.7.0', 'packageVersion': '0.7.5', 'buildId': build, 'files': files,
}, indent=2) + '\\n', encoding='utf-8', newline='\\n')
(root / 'package.json').write_text(json.dumps({
    'name': 'dsh-chapter-whale', 'version': '0.7.5', 'license': 'GPL-3.0-only',
    'files': ['scripts/check-release.mjs', 'runtime-manifest.json', 'backend/'],
}, indent=2) + '\\n', encoding='utf-8', newline='\\n')
(root / 'runtime-download.json').write_text(json.dumps({
    'url': 'https://github.com/thus-zhou/dsh-chapter-whale/releases/download/v0.7.0/dsh-chapter-whale-runtime-win32-x64-0.7.0.tgz',
    'bytes': 1234, 'sha256': 'a' * 64, 'buildId': build, 'runtimeAssetBuildId': 'b' * 64,
}, indent=2) + '\\n', encoding='utf-8', newline='\\n')
`;
    const prepared = spawnSync(pythonBinary(), ['-c', setup, root], { encoding: 'utf8' });
    assert.equal(prepared.status, 0, prepared.stderr || prepared.stdout);

    const originalSpec = JSON.parse(await readFile(join(root, 'runtime-download.json'), 'utf8'));
    const first = spawnSync(pythonBinary(), [join(root, 'scripts', 'pack-bundle.py')], { cwd: root, encoding: 'utf8' });
    assert.equal(first.status, 0, first.stderr || first.stdout);
    const bundle = JSON.parse(await readFile(join(root, '.tmp', 'bundle', 'bundle.json'), 'utf8'));
    assert.equal(bundle.file, `dsh-chapter-whale-runtime-win32-x64-${RUNTIME_VERSION}.tgz`);
    assert.equal(bundle.runtimeVersion, RUNTIME_VERSION);
    assert.equal(bundle.packageVersion, PACKAGE_VERSION);
    // A full bundle must not rewrite the lightweight installer's runtime spec:
    // that spec describes the published v0.7.0 runtime asset, not this bundle.
    const spec = JSON.parse(await readFile(join(root, 'runtime-download.json'), 'utf8'));
    assert.deepEqual(spec, originalSpec);
    assert.equal(existsSync(join(root, 'runtime-download.json.tmp')), false, '临时描述不应残留');

    // A failed bundle must leave the published runtime spec untouched too.
    const beforeFailure = await readFile(join(root, 'runtime-download.json'), 'utf8');
    const pkgPath = join(root, 'package.json');
    const originalPkg = await readFile(pkgPath, 'utf8');
    await writeFile(pkgPath, JSON.stringify({ ...JSON.parse(originalPkg), private: true }, null, 2));
    const privateFailed = spawnSync(pythonBinary(), [join(root, 'scripts', 'pack-bundle.py')], { cwd: root, encoding: 'utf8' });
    assert.notEqual(privateFailed.status, 0, '完整包门禁不得传 --local，private 包必须失败');
    await writeFile(pkgPath, originalPkg);

    await mkdir(join(root, 'backend', 'integration_data'), { recursive: true });
    await writeFile(join(root, 'backend', 'integration_data', 'state.json'), '{}');
    const failed = spawnSync(pythonBinary(), [join(root, 'scripts', 'pack-bundle.py')], { cwd: root, encoding: 'utf8' });
    assert.notEqual(failed.status, 0, '混入本地状态时应失败');
    assert.equal(await readFile(join(root, 'runtime-download.json'), 'utf8'), beforeFailure, '失败后不得改写下载描述');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('P2-25 文档先跑发行门禁再跑 backend 测试，并明确清理 integration_data', async () => {
  const retest = await readFile(join(REPO, 'docs', 'retest-0.7.5.md'), 'utf8');
  const block = retest.slice(retest.indexOf('## 离线自动化验证结果'));
  const gate = block.indexOf('node scripts/check-release.mjs --local');
  const npm = block.indexOf('npm test');
  const integration = block.indexOf('unittest discover -s backend/integration');
  assert.ok(gate >= 0 && npm > gate && integration > npm, '命令顺序必须是 gate → npm test → backend tests');
  assert.match(block, /rm -rf backend\/integration_data/);

  const distribution = await readFile(join(REPO, 'docs', 'distribution.md'), 'utf8');
  const order = distribution.slice(distribution.indexOf('本地复跑顺序'));
  assert.ok(order.indexOf('check-release.mjs --local') < order.indexOf('backend 测试'));

  await withPackage({}, async (root) => {
    await mkdir(join(root, 'backend', 'integration_data'), { recursive: true });
    await writeFile(join(root, 'backend', 'integration_data', 'state.json'), '{}');
    const residue = run(root, ['--local']);
    assert.equal(residue.code, 1);
    assert.match(residue.out, /混入本地状态：backend\/integration_data/);
  });
});

test('P3-4 README 平台说明与 0.7.5 一致', async () => {
  const readme = await readFile(join(REPO, 'README.md'), 'utf8');
  assert.match(readme, /当前(?:分支)? `0\.7\.5` 插件正式声明支持/);
  assert.doesNotMatch(readme, /当前 `0\.7\.4` 插件正式声明支持/);
  assert.match(readme, /当前(?:分支)?版本为 `0\.7\.5`/);
});

function pythonBinary() {
  for (const candidate of ['python3', 'python']) {
    if (spawnSync(candidate, ['--version'], { encoding: 'utf8' }).status === 0) return candidate;
  }
  return null;
}

async function freePort() {
  const server = net.createServer();
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  const { port } = server.address();
  await new Promise((done) => server.close(done));
  return port;
}

test('P3-5 ensureStarted 在启动等待中收到 abort 时立即 kill 并返回 aborted', {
  skip: process.platform === 'win32' && 'shell stub is POSIX-only',
  timeout: 20_000,
}, async () => {
  const root = await mkdtemp(join(tmpdir(), 'cw-abort-'));
  const marker = join(root, 'child-terminated');
  try {
    await mkdir(join(root, 'manager'), { recursive: true });
    await writeFile(join(root, 'manager', 'app.py'), '# stub\n');
    const python = join(root, 'slow-python.sh');
    await writeFile(python, `#!/bin/sh\ntrap 'echo dead > "${marker}"' TERM\nwhile true; do sleep 1; done\n`);
    await chmod(python, 0o755);

    const { resolveConfig, __internals } = await import(pathToFileURL(join(REPO, 'index.js')).href);
    const config = resolveConfig({
      rootDir: root,
      python,
      port: await freePort(),
      startTimeoutMs: 600_000,
    });
    const controller = new AbortController();
    const startedAt = Date.now();
    setTimeout(() => controller.abort(), 100);
    const result = await __internals.ensureStarted(config, controller.signal);
    const elapsed = Date.now() - startedAt;
    assert.equal(result.aborted, true);
    assert.equal(result.started, false);
    assert.ok(elapsed < 5_000, `abort 后应立即返回，实际 ${elapsed}ms`);

    let terminated = false;
    for (let attempt = 0; attempt < 30; attempt += 1) {
      if (existsSync(marker)) { terminated = true; break; }
      await new Promise((done) => setTimeout(done, 100));
    }
    assert.equal(terminated, true, '中止时必须 kill 已 spawn 的子进程');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
