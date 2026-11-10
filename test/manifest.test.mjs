/**
 * Manifest tests.
 *
 * The point of these is to let the *host's own* compatibility code judge the
 * manifest instead of re-implementing SemVer rules here: a plugin that passes a
 * hand-written check but is skipped at boot has not been tested at all. When the
 * DSH installation cannot be located the suite skips instead of failing, so the
 * package can still be tested on a machine without DSH (CI, a contributor
 * without the app) while never pretending those checks ran.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));

function candidateBootPaths() {
  const app = join('resources', 'app', 'dsh', 'node_modules', '@deepseek-ai', 'dsh-app-boot', 'lib', 'index.js');
  const list = [];
  if (process.env.DSH_APP_BOOT) list.push(process.env.DSH_APP_BOOT);
  if (process.env.LOCALAPPDATA) list.push(join(process.env.LOCALAPPDATA, 'Programs', 'DeepSeek Harness', app));
  if (process.env.HOME) list.push(join(process.env.HOME, '.local', 'share', 'deepseek-harness', app));
  if (process.env.HOME) list.push(join(process.env.HOME, 'Library', 'Application Support', 'DeepSeek Harness', app));
  list.push(join('/opt', 'deepseek-harness', app));
  return list.filter((path) => typeof path === 'string' && existsSync(path));
}

const bootPath = candidateBootPaths()[0];
const boot = bootPath ? await import(pathToFileURL(bootPath).href) : null;
const skip = boot
  ? false
  : '未找到本机 DSH 安装，跳过宿主侧兼容性校验（可用 DSH_APP_BOOT 指定 dsh-app-boot/lib/index.js）';

test('宿主认为这个 manifest 与当前 DSH 兼容', { skip }, () => {
  const issue = boot.evaluatePluginCompatibility(manifest);
  assert.equal(
    issue,
    undefined,
    issue ? `宿主会跳过这个插件：${JSON.stringify(issue.requirements)}` : '',
  );
});

test('兼容性判断读的是 engines.dsh，不是 dsh.engines.dsh', { skip }, () => {
  // Guards the one mistake that silently disables a bundle: putting the range
  // under dsh.engines makes the host fall back to peerDependencies instead.
  const bogus = { ...manifest, engines: { ...manifest.engines, dsh: '>=99.0.0' } };
  const issue = boot.evaluatePluginCompatibility(bogus);
  assert.ok(issue, '一个不可能满足的 engines.dsh 必须被宿主识别为不兼容');
  assert.equal(issue.requirements['engines.dsh'], '>=99.0.0');

  const misplaced = { ...manifest, engines: { node: '>=22' }, dsh: { ...manifest.dsh, engines: { dsh: '>=0.2.2-rc.1' } } };
  const misplacedIssue = boot.evaluatePluginCompatibility(misplaced);
  assert.equal(misplacedIssue, undefined, '没有 engines.dsh 时宿主回退 peer 检查；这里应当仍然通过，但不能依赖它');
});

test('bundle 平台声明：win32 放行，其他平台是硬拦截', { skip }, () => {
  assert.doesNotThrow(() => boot.assertBundlePlatform(manifest.dsh.bundle.platforms, 'win32'));
  // Non-Windows is a hard stop in dsh-app-boot (`UnsupportedBundlePlatformError`),
  // not a warning. Asserting it here keeps the README's "Windows-only" claim honest
  // and makes the suite pass on any CI runner regardless of its own platform.
  if (process.platform !== 'win32') {
    assert.throws(
      () => boot.assertBundlePlatform(manifest.dsh.bundle.platforms, process.platform),
      /platform|win32/i,
    );
  }
});

test('manifest 具备发布所需的元数据', () => {
  assert.equal(typeof manifest.private, 'boolean');
  assert.equal(manifest.type, 'module');
  assert.equal(manifest.license, 'SEE LICENSE IN THIRD_PARTY_NOTICES.md');
  assert.ok(existsSync(join(root, 'LICENSE')), '缺少 LICENSE 文件');
  assert.match(manifest.version, /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/);
  assert.ok(manifest.icon, '缺少顶层 icon');
  assert.ok(manifest.repository, '缺少 repository');
  assert.ok(manifest.author, '缺少 author');
  assert.ok(typeof manifest.engines?.dsh === 'string' && manifest.engines.dsh.length > 0, 'engines.dsh 必须是字符串');
});

test('files 覆盖 exports 里出现的每个具体文件', () => {
  const files = manifest.files;
  for (const [key, value] of Object.entries(manifest.exports)) {
    if (typeof value !== 'string' || value.includes('*')) continue;
    const target = value.replace(/^\.\//, '');
    assert.ok(existsSync(join(root, target)), `exports["${key}"] 指向的 ${target} 不存在`);
    const covered = files.some((entry) => {
      if (entry === target) return true;
      if (!entry.includes('*')) return false;
      const [prefix, suffix] = entry.split('*');
      return target.startsWith(prefix) && target.endsWith(suffix);
    });
    assert.ok(covered, `exports["${key}"] 的 ${target} 没有被 files 覆盖`);
  }
});

test('files 里列出的每一项都真实存在', () => {
  for (const entry of manifest.files) {
    if ((entry === 'runtime/python/' || entry === 'runtime/browsers/') && !existsSync(join(root, entry))) {
      assert.ok(existsSync(join(root, 'runtime-download.json')), '源码安装必须带有固定版本的环境下载清单');
      continue;
    }
    if (entry.includes('*')) {
      const directory = entry.split('*')[0].replace(/\/$/, '');
      assert.ok(existsSync(join(root, directory)), `通配目录不存在：${entry}`);
      continue;
    }
    assert.ok(existsSync(join(root, entry)), `files 里列出的文件不存在：${entry}`);
  }
});

test('icon 在宿主的体积与格式限制之内', () => {
  const iconPath = join(root, manifest.icon);
  assert.match(manifest.icon, /\.(svg|png|jpe?g|webp)$/i);
  assert.ok(statSync(iconPath).size <= 256 * 1024, 'icon 超过 256 KiB');
});

test('cordis.patch.yml 只声明身份，不写死机器相关的配置', () => {
  const patch = readFileSync(join(root, 'cordis.patch.yml'), 'utf8');
  // Comments legitimately mention rootDir/port while explaining how a *user*
  // overrides them; only the live YAML matters here.
  const live = patch
    .split(/\r?\n/)
    .filter((line) => !line.trimStart().startsWith('#'))
    .join('\n');
  assert.match(live, /^-\s*insert:/m);
  assert.match(live, /name:\s*dsh-chapter-whale/);
  assert.doesNotMatch(live, /rootDir/, 'patch 不应写死 rootDir');
  assert.doesNotMatch(live, /port:/, 'patch 不应写死 port');
  assert.doesNotMatch(live, /python:/, 'patch 不应写死解释器路径');
});

test('locale 词典满足插件管理器的字段要求', () => {
  for (const locale of ['zh', 'en']) {
    const dictionary = JSON.parse(readFileSync(join(root, 'locale', `${locale}.json`), 'utf8'));
    assert.equal(typeof dictionary.meta?.title, 'string', `${locale}.json 缺少 meta.title`);
    assert.equal(typeof dictionary.meta?.description, 'string', `${locale}.json 缺少 meta.description`);
  }
});
