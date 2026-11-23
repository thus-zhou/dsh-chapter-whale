// 发行前一致性校验：分发字节 == 清单哈希 == 干净检出可复现。
// 用法：
//   node scripts/check-release.mjs [--local] [--root <dir>] [--json <file>]
// --local   允许包内没有内置 runtime（薄源码检出）；此时只跳过缺席的 runtime/ 项，
//           backend/ 的每一项都必须存在且哈希一致，绝不静默跳过。
// --root    校验指定目录（打包暂存目录、干净检出或完整包解包目录）。
import { readFileSync, existsSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const scriptRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const argOf = (flag) => {
  const at = process.argv.indexOf(flag);
  return at > 0 ? process.argv[at + 1] : null;
};
const root = argOf('--root') || scriptRoot;
const jsonAt = argOf('--json');
const local = process.argv.includes('--local');

const errors = [];
const notes = [];
const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const manifestText = readFileSync(join(root, 'runtime-manifest.json'), 'utf8');
if (manifestText.includes('\r\n')) {
  errors.push("runtime-manifest.json 必须是 LF 换行（Windows 生成时需 newline='\\n'）。");
}
const manifest = JSON.parse(manifestText);
// 固定 LF 的文本类型；.bat/.cmd/.ps1 在 .gitattributes 里被固定为 CRLF（同样可复现），不在此列。
const TEXT_SOURCE = /\.(py|pyi|js|mjs|cjs|ts|tsx|jsx|json|md|css|html|txt|yml|yaml|toml|cfg|ini|sh|lua|xml|svg)$/i;
const BINARY_SOURCE = /\.(png|jpe?g|gif|webp|ico|woff2?|ttf|otf|zip|gz|tgz|exe|dll|pyd|so|dylib|pdf|pyc|bin|dat|sqlite|db|mp3|mp4|wasm)$/i;

function digest(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}

const bundledRuntime = existsSync(join(root, 'runtime', 'python', 'python.exe'));
let skippedRuntime = 0;
let checked = 0;
for (const [name, hash] of Object.entries(manifest.files || {})) {
  if (name.startsWith('runtime/') && !bundledRuntime) { skippedRuntime += 1; continue; }
  const path = join(root, name);
  if (!existsSync(path) || !statSync(path).isFile()) {
    errors.push(`缺失：${name}`);
    continue;
  }
  const buffer = readFileSync(path);
  checked += 1;
  if (createHash('sha256').update(buffer).digest('hex') !== hash) {
    errors.push(`哈希不符：${name}`);
    continue;
  }
  // 清单哈希只证明“这份字节与清单一致”。文本文件还必须以 LF 分发，
  // 否则同一个提交在 autocrlf=true 的机器上检出就会变成另一份字节。
  // runtime/ 是第三方 wheel 的原样分发字节，换行由上游决定；LF 约束只覆盖本仓库源码。
  if (!name.startsWith('runtime/') && TEXT_SOURCE.test(name)
      && buffer.includes(0x0d) && buffer.includes(0x0a)
      && buffer.toString('utf8').includes('\r\n')) {
    errors.push(`文本文件含 CRLF，分发字节必须是 LF：${name}`);
  }
}

for (const name of ['accounts', 'books', 'integration_data', 'playwright-browsers', '.env', '.dpapi']) {
  if (existsSync(join(root, 'backend', name))) errors.push(`后端包混入本地状态：backend/${name}`);
}

const residue = [/\/__pycache__\//, /\.py[co]$/, /(^|\/)\.webnovel\//, /(^|\/)正文\//,
  /integration_data\//, /(^|\/)accounts\//, /(^|\/)books\//, /\.dpapi(\.bak)?$/, /\.publish\.json$/,
  /scheduler\.json/, /(^|\/)\.install-lock\//, /(^|\/)\.chapter-whale-release\.json$/];
for (const name of Object.keys(manifest.files || {})) {
  if (residue.some((pattern) => pattern.test(name))) errors.push(`发行清单包含不应分发的文件：${name}`);
  if (/^runtime\/python\/Lib\/site-packages\/(manager|integration|fanqie_auto_publish|services|routers)(\/|$)/.test(name)) {
    errors.push(`运行时内置了后端源码，可能覆盖新版本：${name}`);
  }
  if (BINARY_SOURCE.test(name) && !(name.startsWith('runtime/') || name.startsWith('backend/'))) {
    errors.push(`二进制文件不在受管目录：${name}`);
  }
}

for (const required of ['backend/manager/app.py', 'backend/integration/writer_runner.py',
  'backend/fanqie_auto_publish/publication_safety.py', 'runtime/python/python.exe']) {
  if (!Object.hasOwn(manifest.files || {}, required)) errors.push(`发行清单缺少关键文件：${required}`);
}
// 代码永远来自本包 backend：清单里必须同时有五棵子树，避免某次构建把其中一棵漏掉。
for (const tree of ['manager', 'integration', 'webnovel-writer', 'fanqie_auto_publish', 'vendor']) {
  if (!Object.keys(manifest.files || {}).some((name) => name.startsWith(`backend/${tree}/`))) {
    errors.push(`发行清单缺少后端目录：backend/${tree}/`);
  }
}

const downloadPath = join(root, 'runtime-download.json');
if (!existsSync(downloadPath)) {
  // 完整包自带 runtime，不需要下载描述；轻量包必须带一份可用描述。
  if (!bundledRuntime) {
    errors.push('缺少 runtime-download.json（轻量包首次启动所需的运行时下载描述）。');
  }
} else {
  const spec = JSON.parse(readFileSync(downloadPath, 'utf8'));
  const expectedName = `dsh-chapter-whale-runtime-win32-x64-${pkg.version}.tgz`;
  if (spec.buildId !== manifest.buildId) errors.push('runtime-download.json 的 buildId 与发行清单不一致。');
  if (!/^[a-f0-9]{64}$/.test(String(spec.sha256))) errors.push('runtime-download.json 的 sha256 格式无效。');
  if (!Number.isSafeInteger(spec.bytes) || spec.bytes <= 0 || spec.bytes > 512 * 1024 * 1024) {
    errors.push('runtime-download.json 的 bytes 不在允许范围。');
  }
  if (!new RegExp(`^https://github\\.com/thus-zhou/dsh-chapter-whale/releases/download/v${pkg.version.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/${expectedName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`).test(String(spec.url))) {
    errors.push(`runtime-download.json 的 URL 与版本不符，应为 v${pkg.version}/${expectedName}。`);
  }
  if (bundledRuntime) notes.push('包内已内置 runtime，仍然校验下载描述的一致性。');
}

if (!local && pkg.private) errors.push('package.json 仍标记为 private，禁止发布。');
if (typeof pkg.license !== 'string' || !pkg.license.trim()) errors.push('package.json 缺少 license 字段。');

// 市场元数据只在本仓库快照里存在（打包暂存目录可能没有）。存在就必须与 package.json 对齐：
// 宿主按 semver 取 versions.at(-1)，多留旧版本会让「最新版」指回上一版。
const marketPath = join(root, 'market', 'index.json');
if (existsSync(marketPath)) {
  try {
    const market = JSON.parse(readFileSync(marketPath, 'utf8'));
    const plugin = Array.isArray(market.plugins) ? market.plugins[0] : null;
    const versions = Array.isArray(plugin?.versions) ? plugin.versions : [];
    if (versions.length !== 1) {
      errors.push(`market/index.json 的 plugins[0].versions 必须只保留当前版本一个对象（现有 ${versions.length} 个）。`);
    } else if (versions[0]?.version !== pkg.version) {
      errors.push(`market/index.json 的版本 ${versions[0]?.version} 与 package.json ${pkg.version} 不一致。`);
    }
  } catch (error) {
    errors.push(`market/index.json 无法解析：${error.message}`);
  }
}
const losebirdPath = join(root, 'market', 'losebird-entry.json');
if (existsSync(losebirdPath)) {
  try {
    const entry = JSON.parse(readFileSync(losebirdPath, 'utf8'));
    if (entry.version !== pkg.version || entry.latestVersion !== pkg.version) {
      errors.push(`market/losebird-entry.json 的版本（${entry.version}/${entry.latestVersion}）与 package.json ${pkg.version} 不一致。`);
    }
  } catch (error) {
    errors.push(`market/losebird-entry.json 无法解析：${error.message}`);
  }
}

const summary = {
  root, version: pkg.version, buildId: manifest.buildId, files: Object.keys(manifest.files || {}).length,
  checked, skippedRuntime, errors: errors.length, notes,
};
if (jsonAt) {
  const { writeFileSync } = await import('node:fs');
  writeFileSync(jsonAt, JSON.stringify({ ...summary, errorList: errors }, null, 2), 'utf8');
}
if (errors.length) {
  // 全部错误都要打印：只报前 20 条会让 900 多个换行符差异看起来像 20 个问题。
  console.error(errors.join('\n'));
  console.error(`\n发行清单校验失败：${errors.length} 项（已检查 ${checked} 个文件，跳过 ${skippedRuntime} 个缺席 runtime 项）。`);
  process.exit(1);
}
console.log(`发行清单校验通过：${checked} 个文件与清单一致，buildId=${manifest.buildId}`);
if (notes.length) console.log(notes.join('\n'));
