import { readFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const root = dirname(dirname(fileURLToPath(import.meta.url)));
const pkg = JSON.parse(readFileSync(join(root, 'package.json')));
const manifest = JSON.parse(readFileSync(join(root, 'runtime-manifest.json')));
const errors = [];
for (const [name, hash] of Object.entries(manifest.files)) {
  const path = join(root, name);
  if (!existsSync(path) || createHash('sha256').update(readFileSync(path)).digest('hex') !== hash) errors.push('缺失或变化：' + name);
}
for (const name of ['accounts', 'books', 'integration_data', 'playwright-browsers', '.env']) {
  if (existsSync(join(root, 'backend', name))) errors.push('后端包混入本地状态：' + name);
}
if (!process.argv.includes('--local') && pkg.private) errors.push('本项目通过 GitHub 发行；npm publish 当前关闭。');
if (errors.length) { console.error(errors.slice(0, 20).join('\n')); process.exit(1); }
console.log('发行清单校验通过');
