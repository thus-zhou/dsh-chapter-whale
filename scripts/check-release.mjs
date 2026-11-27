// 发行前一致性校验：分发字节 == 清单哈希 == 干净检出可复现。
// 用法：
//   node scripts/check-release.mjs [--local] [--root <dir>] [--json <file>]
// --local   允许包内没有内置 runtime（薄源码检出）；此时只跳过缺席的 runtime/ 项，
//           backend/ 的每一项都必须存在且哈希一致，绝不静默跳过。
//           非 --local 面向完整发行包：缺 runtime/ 或 runtime/python/python.exe 直接失败。
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

// runtime-manifest.json 的 buildId 由 Python 的
// `sha256(json.dumps(files, sort_keys=True))` 生成。这里必须逐字节复刻该格式：
// 键按 Unicode 码点排序、分隔符为 ", " / ": "、ensure_ascii 会把非 ASCII 转成
// \uXXXX（非 BMP 用代理对）。用 JSON.stringify 会得到不同字节，复算就没有意义。
function pythonJsonString(value) {
  let out = '"';
  for (const ch of String(value)) {
    const code = ch.codePointAt(0);
    if (ch === '"') out += '\\"';
    else if (ch === '\\') out += '\\\\';
    else if (ch === '\b') out += '\\b';
    else if (ch === '\f') out += '\\f';
    else if (ch === '\n') out += '\\n';
    else if (ch === '\r') out += '\\r';
    else if (ch === '\t') out += '\\t';
    else if (code < 0x20) out += `\\u${code.toString(16).padStart(4, '0')}`;
    else if (code < 0x7f) out += ch;
    else if (code <= 0xffff) out += `\\u${code.toString(16).padStart(4, '0')}`;
    else {
      const pair = code - 0x10000;
      out += `\\u${(0xd800 + (pair >> 10)).toString(16).padStart(4, '0')}`;
      out += `\\u${(0xdc00 + (pair & 0x3ff)).toString(16).padStart(4, '0')}`;
    }
  }
  return `${out}"`;
}

/** Python sorts strings by code point; Array#sort compares UTF-16 code units. */
function compareCodePoints(a, b) {
  const left = Array.from(a);
  const right = Array.from(b);
  const shared = Math.min(left.length, right.length);
  for (let index = 0; index < shared; index += 1) {
    const delta = left[index].codePointAt(0) - right[index].codePointAt(0);
    if (delta !== 0) return delta;
  }
  return left.length - right.length;
}

function manifestBuildId(files) {
  const keys = Object.keys(files || {}).sort(compareCodePoints);
  const body = keys.map((name) => `${pythonJsonString(name)}: ${pythonJsonString(files[name])}`).join(', ');
  return createHash('sha256').update(`{${body}}`, 'utf8').digest('hex');
}

const bundledRuntime = existsSync(join(root, 'runtime', 'python', 'python.exe'));
let skippedRuntime = 0;
let checked = 0;
// P2-21：静默跳过 runtime 只允许发生在 --local。完整包缺 python.exe 时，
// 2253 个 runtime 项不是“缺席”，而是发行包损坏。只报一条总错误，避免刷屏。
if (!bundledRuntime && !local) {
  errors.push(existsSync(join(root, 'runtime'))
    ? '完整发行包缺少 runtime/python/python.exe（--local 才允许跳过 runtime 项）。'
    : '完整发行包缺少 runtime/ 目录（--local 才允许跳过 runtime 项）。');
}
for (const [name, hash] of Object.entries(manifest.files || {})) {
  if (name.startsWith('runtime/') && !bundledRuntime) {
    if (local) skippedRuntime += 1;
    continue;
  }
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

// P3-3：buildId 与 packageVersion 必须能从清单本身复算，不能只信手工字段。
const recomputedBuildId = manifestBuildId(manifest.files);
if (manifest.buildId !== recomputedBuildId) {
  errors.push(`runtime-manifest.json 的 buildId 与文件清单复算值不一致（清单 ${String(manifest.buildId)}，复算 ${recomputedBuildId}）。`);
}
if (String(manifest.packageVersion ?? '') !== String(pkg.version)) {
  errors.push(`runtime-manifest.json 的 packageVersion（${String(manifest.packageVersion ?? '缺失')}）与 package.json ${pkg.version} 不一致。`);
}

for (const name of ['accounts', 'books', 'integration_data', 'playwright-browsers', '.env', '.dpapi']) {
  if (existsSync(join(root, 'backend', name))) errors.push(`后端包混入本地状态：backend/${name}`);
}

const residue = [/\/__pycache__\//, /\.py[co]$/, /(^|\/)\.webnovel\//, /(^|\/)正文\//,
  /integration_data\//, /(^|\/)accounts\//, /(^|\/)books\//, /\.dpapi(\.bak)?$/, /\.publish\.json$/,
  /scheduler\.json/, /(^|\/)\.install-lock\//, /(^|\/)\.chapter-whale-release\.json$/,
  /(^|\/)test_[^/]*\.py$/];
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
  const runtimeVersion = String(manifest.version || pkg.version);
  const expectedName = `dsh-chapter-whale-runtime-win32-x64-${runtimeVersion}.tgz`;
  if (spec.buildId !== manifest.buildId) errors.push('runtime-download.json 的 buildId 与发行清单不一致。');
  if (spec.runtimeAssetBuildId !== undefined && !/^[a-f0-9]{64}$/.test(spec.runtimeAssetBuildId)) {
    errors.push('runtime-download.json 的 runtimeAssetBuildId 格式无效。');
  }
  if (!/^[a-f0-9]{64}$/.test(String(spec.sha256))) errors.push('runtime-download.json 的 sha256 格式无效。');
  if (!Number.isSafeInteger(spec.bytes) || spec.bytes <= 0 || spec.bytes > 512 * 1024 * 1024) {
    errors.push('runtime-download.json 的 bytes 不在允许范围。');
  }
  if (!new RegExp(`^https://github\\.com/thus-zhou/dsh-chapter-whale/releases/download/v${runtimeVersion.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/${expectedName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`).test(String(spec.url))) {
    errors.push(`runtime-download.json 的 URL 与版本不符，应为 v${runtimeVersion}/${expectedName}。`);
  }
  if (bundledRuntime) notes.push('包内已内置 runtime，仍然校验下载描述的一致性。');
}

const macReqPath = join(root, 'deploy', 'macos', 'requirements-macos.txt');
if (Array.isArray(pkg?.dsh?.bundle?.platforms) && pkg.dsh.bundle.platforms.includes('darwin')) {
  if (!existsSync(macReqPath) || !statSync(macReqPath).isFile()) {
    errors.push('缺少 macOS 运行环境依赖清单：deploy/macos/requirements-macos.txt');
  } else {
    const macReqRaw = readFileSync(macReqPath);
    if (macReqRaw.includes(0x0d) && macReqRaw.includes(0x0a) && macReqRaw.toString('utf8').includes('\r\n')) {
      errors.push('文本文件含 CRLF，分发字节必须是 LF：deploy/macos/requirements-macos.txt');
    }
  }
}

if (!local && pkg.private) errors.push('package.json 仍标记为 private，禁止发布。');
if (typeof pkg.license !== 'string' || !pkg.license.trim()) errors.push('package.json 缺少 license 字段。');

// 市场元数据只在本仓库快照里存在（打包暂存目录可能没有）。
// P2-23：市场条目只能在对应 GitHub/npm 资产真实存在后指向新版本。发布前允许
// market 落后于 package.json（当前 0.7.4 已发布、0.7.5 尚在验收），但绝不允许
// 指向比 package.json 更新的版本，否则宿主会去下载 404 的资产。
function versionTuple(value) {
  const match = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/.exec(String(value ?? '').trim());
  if (!match) return null;
  return { core: [Number(match[1]), Number(match[2]), Number(match[3])], pre: match[4] || null };
}
function compareVersions(left, right) {
  const a = versionTuple(left);
  const b = versionTuple(right);
  if (!a || !b) return null;
  for (let index = 0; index < 3; index += 1) {
    if (a.core[index] !== b.core[index]) return a.core[index] - b.core[index];
  }
  if (a.pre === b.pre) return 0;
  if (!a.pre) return 1;
  if (!b.pre) return -1;
  return a.pre.localeCompare(b.pre);
}
function marketVersionProblem(label, version) {
  if (version === pkg.version) return null;
  const order = compareVersions(version, pkg.version);
  if (order === null) return `${label} 的版本 ${String(version)} 不是有效 semver。`;
  if (order < 0) {
    notes.push(`${label} 仍指向 ${version}（低于 package.json ${pkg.version}）；发布 v${pkg.version} 前允许滞后，Release/npm 完成后必须同步。`);
    return null;
  }
  return `${label} 的版本 ${String(version)} 高于 package.json ${pkg.version}；资产尚不存在时会把用户引向 404。`;
}

const marketPath = join(root, 'market', 'index.json');
if (existsSync(marketPath)) {
  try {
    const market = JSON.parse(readFileSync(marketPath, 'utf8'));
    const plugin = Array.isArray(market.plugins) ? market.plugins[0] : null;
    const versions = Array.isArray(plugin?.versions) ? plugin.versions : [];
    if (versions.length !== 1) {
      errors.push(`market/index.json 的 plugins[0].versions 必须只保留当前版本一个对象（现有 ${versions.length} 个）。`);
    } else {
      const problem = marketVersionProblem('market/index.json', versions[0]?.version);
      if (problem) errors.push(problem);
    }
  } catch (error) {
    errors.push(`market/index.json 无法解析：${error.message}`);
  }
}
const losebirdPath = join(root, 'market', 'losebird-entry.json');
if (existsSync(losebirdPath)) {
  try {
    const entry = JSON.parse(readFileSync(losebirdPath, 'utf8'));
    for (const [field, value] of [['version', entry.version], ['latestVersion', entry.latestVersion]]) {
      const problem = marketVersionProblem(`market/losebird-entry.json 的 ${field}`, value);
      if (problem) errors.push(problem);
    }
  } catch (error) {
    errors.push(`market/losebird-entry.json 无法解析：${error.message}`);
  }
}
const catalogPath = join(root, 'market', 'catalog-entry.yml');
if (existsSync(catalogPath)) {
  const catalog = readFileSync(catalogPath, 'utf8');
  const tarball = /releases\/download\/v([^/\s]+)\//.exec(catalog);
  if (tarball) {
    const problem = marketVersionProblem('market/catalog-entry.yml 的 tarball', tarball[1]);
    if (problem) errors.push(problem);
  }
}

// D-08：client.js 里内嵌的 ATELIER CSS 与 workbench 内核必须能从源文件逐字节
// 复算。assets/*.css 或 scripts/shared/workbench-core.js 改动后忘了重新构建时，
// 测试与发布校验都必须失败，而不是静默发出旧面板。
function readTextFile(path) {
  return readFileSync(path, 'utf8');
}
function blockBetween(text, begin, end) {
  const start = text.indexOf(begin);
  if (start < 0) throw new Error('缺少生成块起点：' + begin.trim());
  const stop = text.indexOf(end, start + begin.length);
  if (stop < 0) throw new Error('缺少生成块终点：' + end.trim());
  return text.slice(start + begin.length, stop);
}
function embeddedAtelierCss(client) {
  const block = blockBetween(client,
    '        // BEGIN GENERATED ATELIER CSS\n',
    '        // END GENERATED ATELIER CSS\n');
  const chunks = [];
  for (const line of block.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const literal = trimmed.endsWith(',') ? trimmed.slice(0, -1) : trimmed;
    if (!/^".*"$/.test(literal)) continue;
    chunks.push(JSON.parse(literal));
  }
  return chunks.join('');
}
function expectedAtelierCssFromSources() {
  const fonts = [
    ['manrope', 'Whale Geometric', '200 800'],
    ['notosanssc', 'Whale Text', '100 900'],
    ['notoserifsc', 'Whale Editorial', '400'],
  ].map(([file, family, weight]) => {
    const path = join(root, 'assets', 'fonts', file + '.woff2');
    if (!existsSync(path)) throw new Error('缺少字体源文件：' + path);
    const data = readFileSync(path).toString('base64');
    return `@font-face{font-family:"${family}";src:url(data:font/woff2;base64,${data}) format("woff2");font-weight:${weight};font-display:swap}`;
  });
  const base = readTextFile(join(root, 'assets', 'atelier-base.css'));
  const native = readTextFile(join(root, 'assets', 'atelier-native.css'));
  return fonts.join('\n') + '\n' + base + '\n' + native;
}
function embeddedWorkbenchCore(client) {
  return blockBetween(client,
    '        // BEGIN GENERATED WORKBENCH CORE\n',
    '        // END GENERATED WORKBENCH CORE\n');
}
try {
  const clientPath = join(root, 'client.js');
  const uiSources = [
    join(root, 'assets', 'atelier-base.css'),
    join(root, 'assets', 'atelier-native.css'),
    join(root, 'assets', 'fonts', 'manrope.woff2'),
    join(root, 'assets', 'fonts', 'notosanssc.woff2'),
    join(root, 'assets', 'fonts', 'notoserifsc.woff2'),
  ];
  if (!existsSync(clientPath)) {
    notes.push('未包含 client.js，跳过生成产物一致性校验。');
  } else if (!uiSources.every((path) => existsSync(path))) {
    errors.push('发行包缺少生成用前端源文件（assets/*.css 或字体），无法校验 client.js 内嵌样式。');
  } else {
    const clientText = readTextFile(clientPath);
    if (embeddedAtelierCss(clientText) !== expectedAtelierCssFromSources()) {
      errors.push('client.js 内嵌 ATELIER CSS 与 assets/atelier-base.css + atelier-native.css + 字体不一致：请运行 python3 -X utf8 scripts/build-client-ui.py。');
    }
    const staticCorePath = join(root, 'backend', 'manager', 'static', 'workbench-core.js');
    const sharedCorePath = join(root, 'scripts', 'shared', 'workbench-core.js');
    const corePath = existsSync(sharedCorePath) ? sharedCorePath : (existsSync(staticCorePath) ? staticCorePath : null);
    if (!corePath) {
      errors.push('缺少 workbench-core 源文件，无法校验内嵌内核。');
    } else {
      const source = readTextFile(corePath);
      const normalized = source.endsWith('\n') ? source : source + '\n';
      if (embeddedWorkbenchCore(clientText) !== normalized) {
        errors.push('client.js 内嵌 WORKBENCH CORE 与 scripts/shared/workbench-core.js 不一致：请运行 python3 -X utf8 scripts/build-client-ui.py。');
      }
      if (existsSync(staticCorePath) && readTextFile(staticCorePath) !== normalized) {
        errors.push('backend/manager/static/workbench-core.js 与 scripts/shared/workbench-core.js 不一致：请运行 python3 -X utf8 scripts/build-client-ui.py。');
      }
    }
  }
} catch (error) {
  errors.push('前端产物一致性校验失败：' + error.message);
}

const summary = {
  root, version: pkg.version, packageVersion: manifest.packageVersion,
  buildId: manifest.buildId, recomputedBuildId, files: Object.keys(manifest.files || {}).length,
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
