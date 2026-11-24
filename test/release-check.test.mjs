// P02 负例：清单与真实分发字节必须互相印证，任何一处偏差都要非零退出。
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, writeFile, readFile, rm, appendFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const REPO = fileURLToPath(new URL('..', import.meta.url));
const CHECKER = join(REPO, 'scripts', 'check-release.mjs');
const VERSION = '0.6.0';
const sha = (buffer) => createHash('sha256').update(buffer).digest('hex');

const SOURCES = {
  'backend/manager/app.py': 'print("manager")\n',
  'backend/integration/writer_runner.py': 'print("writer")\n',
  'backend/integration/__init__.py': '\n',
  'backend/fanqie_auto_publish/publication_safety.py': 'print("safety")\n',
  'backend/webnovel-writer/skill.md': '# skill\n',
  'backend/vendor/ofm.py': 'print("ofm")\n',
};

async function makePackage() {
  const root = await mkdtemp(join(REPO, 'test', 'release-'));
  for (const [name, body] of Object.entries(SOURCES)) {
    const path = join(root, ...name.split('/'));
    await mkdir(join(path, '..'), { recursive: true });
    await writeFile(path, body);
  }
  const files = Object.fromEntries(Object.entries(SOURCES).map(([name, body]) => [name, sha(Buffer.from(body))]));
  // 薄源码检出不带 runtime，但清单里仍然要有它（跳过磁盘检查，不跳过清单项）。
  files['runtime/python/python.exe'] = sha(Buffer.from('interpreter'));
  await writeFile(join(root, 'runtime-manifest.json'), JSON.stringify({
    version: VERSION, buildId: sha(Buffer.from(JSON.stringify(files))), files,
  }, null, 2));
  await writeFile(join(root, 'package.json'), JSON.stringify({ name: 'dsh-chapter-whale', version: VERSION, license: 'GPL-3.0-only' }));
  await writeFile(join(root, 'runtime-download.json'), JSON.stringify({
    url: `https://github.com/thus-zhou/dsh-chapter-whale/releases/download/v${VERSION}/dsh-chapter-whale-runtime-win32-x64-${VERSION}.tgz`,
    bytes: 1234, sha256: 'a'.repeat(64), buildId: sha(Buffer.from(JSON.stringify(files))),
  }));
  return root;
}

function run(root, extra = []) {
  const result = spawnSync(process.execPath, [CHECKER, '--root', root, ...extra], { encoding: 'utf8' });
  return { code: result.status, out: `${result.stdout}${result.stderr}` };
}

async function withPackage(worker) {
  const root = await makePackage();
  try { return await worker(root); } finally { await rm(root, { recursive: true, force: true }); }
}

test('P02 干净薄检出的清单一致性校验通过', async () => {
  await withPackage(async (root) => {
    const result = run(root, ['--local']);
    assert.equal(result.code, 0, result.out);
    assert.match(result.out, /发行清单校验通过/);
    // 非 --local 时 private 才有意义；这里断言 --local 也能通过同一份清单
    const json = join(root, 'report.json');
    const second = run(root, ['--local', '--json', json]);
    assert.equal(second.code, 0, second.out);
    const report = JSON.parse(await readFile(json, 'utf8'));
    assert.equal(report.errors, 0);
    assert.ok(report.skippedRuntime >= 1);
  });
});

test('P02 改一个受管源码字节立刻非零退出', async () => {
  await withPackage(async (root) => {
    await appendFile(join(root, 'backend', 'manager', 'app.py'), '# tampered\n');
    const result = run(root, ['--local']);
    assert.equal(result.code, 1);
    assert.match(result.out, /哈希不符：backend\/manager\/app\.py/);
  });
});

test('P02 清单列了磁盘上没有的文件必须失败', async () => {
  await withPackage(async (root) => {
    const manifest = JSON.parse(await readFile(join(root, 'runtime-manifest.json'), 'utf8'));
    manifest.files['backend/vendor/missing_module.py'] = 'b'.repeat(64);
    await writeFile(join(root, 'runtime-manifest.json'), JSON.stringify(manifest, null, 2));
    const result = run(root, ['--local']);
    assert.equal(result.code, 1);
    assert.match(result.out, /缺失：backend\/vendor\/missing_module\.py/);
  });
});

test('P02 下载描述 buildId 与清单不一致必须失败', async () => {
  await withPackage(async (root) => {
    const spec = JSON.parse(await readFile(join(root, 'runtime-download.json'), 'utf8'));
    spec.buildId = 'c'.repeat(64);
    await writeFile(join(root, 'runtime-download.json'), JSON.stringify(spec));
    const result = run(root, ['--local']);
    assert.equal(result.code, 1);
    assert.match(result.out, /buildId 与发行清单不一致/);
  });
});

test('P02 下载描述 URL 必须是本版本的完整包名', async () => {
  await withPackage(async (root) => {
    const spec = JSON.parse(await readFile(join(root, 'runtime-download.json'), 'utf8'));
    spec.url = spec.url.replace('runtime-win32-x64-', '');
    await writeFile(join(root, 'runtime-download.json'), JSON.stringify(spec));
    const result = run(root, ['--local']);
    assert.equal(result.code, 1);
    assert.match(result.out, /URL 与版本不符/);
  });
});

test('P02 清单哈希覆盖 CRLF 字节时必须失败（同提交在 autocrlf 机器上会失配）', async () => {
  await withPackage(async (root) => {
    const path = join(root, 'backend', 'integration', '__init__.py');
    const crlf = Buffer.from('import os\r\nimport sys\r\n');
    await writeFile(path, crlf);
    const manifest = JSON.parse(await readFile(join(root, 'runtime-manifest.json'), 'utf8'));
    manifest.files['backend/integration/__init__.py'] = sha(crlf);
    await writeFile(join(root, 'runtime-manifest.json'), JSON.stringify(manifest, null, 2));
    const result = run(root, ['--local']);
    assert.equal(result.code, 1);
    assert.match(result.out, /CRLF/);
  });
});

test('P02 后端混入本机状态目录必须失败', async () => {
  await withPackage(async (root) => {
    await mkdir(join(root, 'backend', 'integration_data'), { recursive: true });
    await writeFile(join(root, 'backend', 'integration_data', 'state.json'), '{}');
    const result = run(root, ['--local']);
    assert.equal(result.code, 1);
    assert.match(result.out, /混入本地状态：backend\/integration_data/);
  });
});

test('P02 清单混入作者数据必须失败', async () => {
  await withPackage(async (root) => {
    const path = join(root, 'backend', 'books', '潮汐钟', 'chapters.json');
    await mkdir(join(path, '..'), { recursive: true });
    await writeFile(path, '{}');
    const manifest = JSON.parse(await readFile(join(root, 'runtime-manifest.json'), 'utf8'));
    manifest.files['backend/books/潮汐钟/chapters.json'] = sha(Buffer.from('{}'));
    await writeFile(join(root, 'runtime-manifest.json'), JSON.stringify(manifest, null, 2));
    const result = run(root, ['--local']);
    assert.equal(result.code, 1);
    assert.match(result.out, /不应分发/);
  });
});

test('P02 private 包只在非 --local 时被拒绝', async () => {
  await withPackage(async (root) => {
    const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
    pkg.private = true;
    await writeFile(join(root, 'package.json'), JSON.stringify(pkg));
    assert.equal(run(root, ['--local']).code, 0);
    const strict = run(root);
    assert.equal(strict.code, 1);
    assert.match(strict.out, /private/);
  });
});

test('P02 插件补丁版复用上一版 runtime-manifest 时通过校验', async () => {
  await withPackage(async (root) => {
    const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
    pkg.version = '0.7.1';
    pkg.dsh = { bundle: { platforms: ['win32', 'darwin'] } };
    await writeFile(join(root, 'package.json'), JSON.stringify(pkg));
    const manifest = JSON.parse(await readFile(join(root, 'runtime-manifest.json'), 'utf8'));
    manifest.version = '0.7.0';
    await writeFile(join(root, 'runtime-manifest.json'), JSON.stringify(manifest, null, 2));
    await writeFile(join(root, 'runtime-download.json'), JSON.stringify({
      url: 'https://github.com/thus-zhou/dsh-chapter-whale/releases/download/v0.7.0/dsh-chapter-whale-runtime-win32-x64-0.7.0.tgz',
      bytes: 1234, sha256: 'a'.repeat(64), buildId: manifest.buildId,
    }));
    await mkdir(join(root, 'deploy', 'macos'), { recursive: true });
    await writeFile(join(root, 'deploy', 'macos', 'requirements-macos.txt'), 'fastapi>=0.115\n');
    const result = run(root, ['--local']);
    assert.equal(result.code, 0, result.out);
  });
});
