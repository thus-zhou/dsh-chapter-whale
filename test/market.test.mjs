/**
 * `market/index.json` validated with the host's own parser.
 *
 * A market entry is not documentation: the plugin market feeds it straight into
 * `parseMarketIndex()`, and a schema miss means the whole index fails to load.
 * This file was invalid once already (declarations written as arrays), so it is
 * checked by the same code the market runs, not by eyeballing the shape.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const INDEX_URL = 'https://github.com/thus-zhou/dsh-chapter-whale/raw/main/market/index.json';

/** Locate the host's own market-index module across common install layouts. */
function hostModule() {
  const candidates = [];
  if (process.env.LOCALAPPDATA) {
    candidates.push(
      join(
        process.env.LOCALAPPDATA,
        'Programs',
        'DeepSeek Harness',
        'resources',
        'app',
        'dsh',
        'node_modules',
        '@deepseek-ai',
        'dsh-plugin-market-index',
        'lib',
        'index.js',
      ),
    );
  }
  if (process.env.HOME) {
    candidates.push(
      join(
        process.env.HOME,
        '.dsh',
        'node_modules',
        '@deepseek-ai',
        'dsh-plugin-market-index',
        'lib',
        'index.js',
      ),
    );
  }
  for (const candidate of candidates) {
    try {
      if (!existsSync(candidate)) continue;
      return pathToFileURL(candidate).href;
    } catch {
      /* keep looking */
    }
  }
  return null;
}

const moduleUrl = hostModule();
const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const index = JSON.parse(readFileSync(join(root, 'market', 'index.json'), 'utf8'));

test('market index 通过宿主的 parseMarketIndex()', { skip: !moduleUrl && 'host checkout not found' }, async () => {
  const { parseMarketIndex } = await import(moduleUrl);
  const parsed = parseMarketIndex(index, INDEX_URL);
  assert.equal(parsed.plugins.length, 1);
});

test('市场条目与 package.json 说的是同一件事', { skip: !moduleUrl && 'host checkout not found' }, async () => {
  const { marketInstallTarget, parseMarketIndex } = await import(moduleUrl);
  const parsed = parseMarketIndex(index, INDEX_URL);
  const [plugin] = parsed.plugins;
  assert.equal(plugin.name, manifest.name);

  const latest = plugin.versions.at(-1);
  assert.equal(latest.version, manifest.version, 'market 版本必须与 package.json 一致');
  assert.equal(latest.engines.dsh, manifest.engines.dsh);
  // Second argument is the *version object*, not the version string: the spec is
  // built from version.source, so passing "0.1.0" would look for its `.type`.
  assert.equal(
    marketInstallTarget(plugin.name, latest).spec,
    `${manifest.name}@${manifest.version}`,
  );
});

test('市场条目里没有残留占位符，且图标走 https', () => {
  const text = JSON.stringify(index);
  assert.equal(/OWNER/.test(text), false, 'OWNER 占位符会被市场原样显示');
  const [plugin] = index.plugins;
  assert.match(plugin.icon, /^https:\/\//);
  assert.equal(/localhost|127\.0\.0\.1/.test(plugin.icon), false);
});

test('publishTimestamp 是秒级整数且不是 0', () => {
  const stamp = index.plugins[0].versions[0].publishTimestamp;
  assert.ok(Number.isInteger(stamp), '必须是整数');
  assert.ok(stamp > 1_700_000_000, '0 能过校验，但市场会显示 1970 年');
  assert.ok(stamp < 1e11, '毫秒级时间戳会越过宿主上限');
});
