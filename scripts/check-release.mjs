import { readFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const root = dirname(dirname(fileURLToPath(import.meta.url)));
const pkg = JSON.parse(readFileSync(join(root, 'package.json')));
const manifest = JSON.parse(readFileSync(join(root, 'runtime-manifest.json')));
const errors = [];
const bundledRuntime = existsSync(join(root, 'runtime', 'python', 'python.exe'));
for (const [name, hash] of Object.entries(manifest.files)) {
  if (name.startsWith('runtime/') && !bundledRuntime) continue;
  const path = join(root, name);
  if (!existsSync(path) || createHash('sha256').update(readFileSync(path)).digest('hex') !== hash) errors.push('缺失或变化：' + name);
}
for (const name of ['accounts', 'books', 'integration_data', 'playwright-browsers', '.env']) {
  if (existsSync(join(root, 'backend', name))) errors.push('后端包混入本地状态：' + name);
}
const residue = [/\/__pycache__\//, /\.py[co]$/, /(^|\/)\.webnovel\//, /(^|\/)正文\//,
  /integration_data\//, /(^|\/)accounts\//, /(^|\/)books\//, /\.dpapi(\.bak)?$/, /\.publish\.json$/, /scheduler\.json/];
for (const name of Object.keys(manifest.files)) {
  const hit = residue.find((pattern) => pattern.test(name));
  if (hit) errors.push('发行清单包含不应分发的文件：' + name);
  if (/^runtime\/python\/Lib\/site-packages\/(manager|integration|fanqie_auto_publish|services|routers)(\/|$)/.test(name)) {
    errors.push('运行时内置了后端源码，可能覆盖新版本：' + name);
  }
}
for (const required of ['backend/manager/app.py', 'backend/integration/writer_runner.py',
  'backend/fanqie_auto_publish/publication_safety.py', 'runtime/python/python.exe']) {
  if (!Object.hasOwn(manifest.files, required)) errors.push('发行清单缺少关键文件：' + required);
}
if (!bundledRuntime) {
  const spec = JSON.parse(readFileSync(join(root, 'runtime-download.json')));
  if (spec.buildId !== manifest.buildId || !/^[a-f0-9]{64}$/.test(spec.sha256)
      || !Number.isSafeInteger(spec.bytes) || spec.bytes <= 0
      || !/^https:\/\/github\.com\/thus-zhou\/dsh-chapter-whale\/releases\/download\/[^/]+\/[^/]+\.tgz$/.test(spec.url)) {
    errors.push('首次启动环境下载清单不完整或版本不匹配。');
  }
}
if (!process.argv.includes('--local') && pkg.private) errors.push('package.json 仍标记为 private，禁止发布。');
if (errors.length) { console.error(errors.slice(0, 20).join('\n')); process.exit(1); }
console.log('发行清单校验通过');
