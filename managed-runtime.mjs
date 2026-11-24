import { cp, mkdir, readFile, writeFile, stat, lstat, rm, mkdtemp } from 'node:fs/promises';
import { existsSync, createWriteStream, mkdirSync, readFileSync, realpathSync, renameSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { execFile, execFileSync } from 'node:child_process';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { promisify } from 'node:util';
import { t as listTar, x as extractTar } from 'tar';
import { basename, dirname, join, posix, resolve, sep } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';

const execFileAsync = promisify(execFile);

export const PACKAGE_ROOT = dirname(fileURLToPath(import.meta.url));
export function managedRoot(platform = process.platform) {
  if (platform === 'win32') {
    return join(process.env.LOCALAPPDATA || join(homedir(), 'AppData', 'Local'), 'ChapterWhale', 'workspace');
  }
  if (platform === 'darwin') {
    return posix.join(process.env.HOME || homedir(), 'Library', 'Application Support', 'ChapterWhale', 'workspace');
  }
  return posix.join(process.env.XDG_DATA_HOME || posix.join(process.env.HOME || homedir(), '.local', 'share'), 'ChapterWhale', 'workspace');
}

export function managedPythonPath(rootDir, platform = process.platform) {
  return platform === 'win32'
    ? join(rootDir, '.venv', 'Scripts', 'python.exe')
    : posix.join(rootDir, '.venv', 'bin', 'python3');
}

export function macPythonCandidates(homeDir = process.env.HOME || homedir()) {
  const candidates = [];
  if (process.env.CHAPTER_WHALE_MAC_PYTHON) candidates.push(process.env.CHAPTER_WHALE_MAC_PYTHON.trim());
  for (const dir of ['/opt/homebrew/bin', '/usr/local/bin']) {
    candidates.push(
      `${dir}/python3.13`,
      `${dir}/python3.12`,
      `${dir}/python3.11`,
      `${dir}/python3`,
    );
  }
  for (const minor of ['3.13', '3.12', '3.11']) {
    candidates.push(`/Library/Frameworks/Python.framework/Versions/${minor}/bin/python3`);
  }
  candidates.push(posix.join(homeDir, '.pyenv', 'shims', 'python3'));
  candidates.push('python3');
  return [...new Set(candidates.filter(Boolean))];
}

export function findMacPython(candidates = macPythonCandidates()) {
  const probe = 'import sys, venv; assert sys.version_info >= (3, 11); print(sys.executable)';
  for (const candidate of candidates) {
    if (candidate.startsWith('/') && !existsSync(candidate)) continue;
    try {
      const resolved = execFileSync(candidate, ['-c', probe], {
        timeout: 5000,
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      }).trim();
      if (resolved) return resolved;
    } catch {
      /* continue searching Python 3.11+ candidates */
    }
  }
  throw new Error('未检测到 macOS 所需的 Python 3.11+ 环境。请先执行 brew install python@3.13 或从 https://www.python.org/downloads/macos/ 安装 Python 3.11+ 后重启 DSH（或在插件配置中填写 python 路径）。');
}

// 没有签名清单与可信公钥，自动跟随新版本的能力保持关闭。
// 哈希只证明“下载内容与清单一致”，不等于来源认证；新版本由用户手动下载安装。
export const AUTO_UPDATE_ENABLED = false;
export function updateAvailable() {
  return { enabled: false, reason: '未配置发布方签名与公钥，自动更新已关闭；请手动下载新的发行包覆盖安装。' };
}

export function validateTarListing(text) {
  const lines = text.split(/\r?\n/).filter((line) => line.trim() !== '');
  if (!lines.length) throw new Error('发行包目录为空，未解包。');
  for (const line of lines) {
    const verbose = /^[dlhbcps-][rwxStTs-]{9}/.test(line);
    let member = line;
    if (verbose) {
      if (!/^[-d]/.test(line) || line.includes(' -> ')) throw new Error('发行包包含链接或特殊文件，未解包。');
      const at = line.indexOf('package/');
      if (at < 0) throw new Error('发行包路径异常，未解包。');
      member = line.slice(at);
    }
    if (!member.startsWith('package/') || member.split(/[\\/]/).includes('..') || member.includes('\\')) {
      throw new Error('发行包路径异常，未解包。');
    }
  }
  return lines.length;
}

export function validateArchiveEntry(path, type) {
  if (!['File', 'Directory'].includes(type)) throw new Error('发行包包含链接或特殊文件，未解包。');
  if ((path !== 'package' && !path.startsWith('package/')) || path.includes('\\')
      || path.includes(':') || path.includes('\0') || path.split('/').includes('..')) {
    throw new Error('发行包路径异常，未解包。');
  }
}

export async function extractPackage(archive, destination) {
  let entries = 0;
  const invalid = [];
  await listTar({ file: archive, strict: true, onReadEntry(entry) {
    entries += 1;
    try { validateArchiveEntry(entry.path, entry.type); } catch (error) { invalid.push(error); }
  } });
  if (invalid.length) throw invalid[0];
  if (!entries) throw new Error('发行包目录为空，未解包。');
  // node-tar reads UTF-8 paths directly, including on Windows systems whose
  // bundled bsdtar cannot convert Chinese filenames to the ANSI code page.
  await extractTar({ file: archive, cwd: destination, strict: true, preservePaths: false });
  return { entries };
}

export async function verifyInstalled(rootDir, manifest, names) {
  const { readFile: read } = await import('node:fs/promises');
  const result = { checked: 0, missing: [], mismatched: [] };
  for (const [name, hash] of Object.entries(manifest.files || {})) {
    if (!names.some((prefix) => name.startsWith(`backend/${prefix}/`))) continue;
    const path = join(rootDir, name.slice('backend/'.length));
    try {
      const actual = createHash('sha256').update(await read(path)).digest('hex');
      result.checked += 1;
      if (actual !== hash) result.mismatched.push(name);
    } catch {
      result.missing.push(name);
    }
  }
  return result;
}

export function runtimeAvailable(platform = process.platform) {
  if (!existsSync(join(PACKAGE_ROOT, 'backend', 'manager', 'app.py'))) return false;
  if (platform === 'darwin') {
    return existsSync(join(PACKAGE_ROOT, 'deploy', 'macos', 'requirements-macos.txt'));
  }
  return existsSync(join(PACKAGE_ROOT, 'runtime', 'python', 'python.exe'))
    || existsSync(join(PACKAGE_ROOT, 'runtime-download.json'));
}

export async function downloadRuntime(workspace, manifest) {
  const spec = JSON.parse(await readFile(join(PACKAGE_ROOT, 'runtime-download.json'), 'utf8'));
  if (!/^https:\/\/github\.com\/thus-zhou\/dsh-chapter-whale\/releases\/download\/[^/]+\/[^/]+\.tgz$/.test(spec.url)
      || !/^[a-f0-9]{64}$/.test(spec.sha256) || spec.buildId !== manifest.buildId
      || (spec.runtimeAssetBuildId !== undefined && !/^[a-f0-9]{64}$/.test(spec.runtimeAssetBuildId))
      || !Number.isSafeInteger(spec.bytes) || spec.bytes < 1 || spec.bytes > 512 * 1024 * 1024) {
    throw new Error('发行下载信息无效，请重新安装码章鲸。');
  }
  const cache = join(dirname(workspace), 'release-cache');
  await mkdir(cache, { recursive: true });
  const staging = await mkdtemp(join(cache, 'download-'));
  const archive = join(staging, 'runtime.tgz');
  const response = await fetch(spec.url, { signal: AbortSignal.timeout(15 * 60 * 1000) });
  if (!response.ok || !response.body) throw new Error('运行环境下载失败，请检查网络后重试。');
  const hash = createHash('sha256');
  let bytes = 0;
  await pipeline(Readable.fromWeb(response.body), new Transform({ transform(chunk, encoding, done) {
    bytes += chunk.length;
    if (bytes > spec.bytes) return done(new Error('下载文件超过发行清单大小'));
    hash.update(chunk); done(null, chunk);
  } }), createWriteStream(archive, { flags: 'wx' }));
  if (bytes !== spec.bytes || hash.digest('hex') !== spec.sha256) throw new Error('运行环境校验失败，未执行下载的文件。请重试安装。');
  await extractPackage(archive, staging);
  const payload = join(staging, 'package');
  const actual = JSON.parse(await readFile(join(payload, 'runtime-manifest.json'), 'utf8'));
  if (actual.buildId !== (spec.runtimeAssetBuildId ?? manifest.buildId)
      || !existsSync(join(payload, 'runtime', 'python', 'python.exe'))) {
    throw new Error('发行包版本不匹配。');
  }
  if (spec.runtimeAssetBuildId) {
    // Older archives may be reused only for the exact same runtime files.
    // prepareManaged always copies the current backend from PACKAGE_ROOT.
    const entries = (info) => Object.entries(info.files || {}).filter(([name]) => name.startsWith('runtime/'));
    const expected = entries(manifest);
    if (!expected.length || expected.length !== entries(actual).length
        || expected.some(([name, hash]) => actual.files?.[name] !== hash)) {
      throw new Error('旧运行环境包与当前运行环境文件清单不一致。');
    }
  }
  return payload;
}

// 代码与运行环境是两条独立来源，任何情况下都不得混用：
//   codeSource  —— 恒为本轻量包自己的 backend（用户刚安装/升级的那份代码）。
//   runtimeSource —— 内置 runtime，或按发行清单下载并逐一校验过的 runtime 包。
// 下载包即使夹带 backend 目录也不会被复制或执行，否则一次降级下载就能悄悄把
// 新版本代码换成旧后端。
const CODE_TREES = ['manager', 'integration', 'webnovel-writer', 'fanqie_auto_publish', 'vendor'];
// 作者数据与登录态：升级清理永远不碰。
const AUTHOR_DATA_TREES = ['accounts', 'books', 'integration_data', 'playwright-browsers', '.venv'];
const PROTECTED_NAMES = new Set(['.env', '.chapter-whale-release.json', 'scheduler.json', '.publish.json',
  '.dpapi', 'cookies.json', 'storage_state.json']);

export function codeSource() {
  if (!existsSync(join(PACKAGE_ROOT, 'backend', 'manager', 'app.py'))) {
    throw new Error('安装包缺少后端源码（backend/manager/app.py），请重新安装完整的码章鲸发行包。');
  }
  return PACKAGE_ROOT;
}

export async function resolveRuntimeSource(workspace, manifest) {
  const bundled = join(PACKAGE_ROOT, 'runtime');
  if (existsSync(join(bundled, 'python', 'python.exe')) && existsSync(join(bundled, 'browsers'))) {
    return { root: PACKAGE_ROOT, kind: 'bundled', buildId: manifest.buildId };
  }
  if (!existsSync(join(PACKAGE_ROOT, 'runtime-download.json'))) {
    throw new Error('安装包缺少运行环境（runtime/python 与 runtime/browsers），请重新安装完整的码章鲸发行包。');
  }
  const payload = await downloadRuntime(workspace, manifest);
  if (!existsSync(join(payload, 'runtime', 'browsers'))) {
    throw new Error('下载的运行环境缺少浏览器目录，未安装。');
  }
  const actual = JSON.parse(await readFile(join(payload, 'runtime-manifest.json'), 'utf8'));
  return { root: payload, kind: 'downloaded', buildId: actual.buildId };
}

function withinRoot(rootDir, target) {
  return resolve(target).startsWith(resolve(rootDir) + sep);
}

// 上一发行清单管理、本版不再分发的代码文件需要清理；只允许清理 backend 受管子树
// 内的规范化路径，作者数据、凭据、账本、登录文件一律跳过。
export function staleCodeFiles(rootDir, previousFiles, nextFiles) {
  const next = new Set(nextFiles || []);
  const stale = [];
  for (const name of previousFiles || []) {
    if (typeof name !== 'string' || next.has(name) || !name.startsWith('backend/')) continue;
    const segments = name.slice('backend/'.length).split('/');
    if (!segments.length || !CODE_TREES.includes(segments[0])) continue;
    if (segments.some((segment) => segment === '' || segment === '.' || segment === '..'
      || segment.includes('\\') || segment.includes(':') || segment.includes('\0'))) continue;
    if (segments.some((segment) => AUTHOR_DATA_TREES.includes(segment))) continue;
    if (PROTECTED_NAMES.has(segments[segments.length - 1])) continue;
    const target = join(rootDir, ...segments);
    if (!withinRoot(rootDir, target)) continue;
    stale.push(target);
  }
  return stale;
}

export async function removeStaleCode(rootDir, previousFiles, nextFiles) {
  const removed = [];
  for (const target of staleCodeFiles(rootDir, previousFiles, nextFiles)) {
    try {
      await rm(target, { force: true });
      removed.push(target);
    } catch {}
  }
  return removed;
}

async function prepareDarwinManaged(config, manifest, codeRoot, codeFiles) {
  if (process.arch !== 'arm64' && process.arch !== 'x64') {
    throw new Error('码章鲸当前支持 Apple Silicon (arm64) 与 Intel (x86_64) macOS。');
  }
  const reqPath = join(PACKAGE_ROOT, 'deploy', 'macos', 'requirements-macos.txt');
  const reqSha = createHash('sha256').update(await readFile(reqPath)).digest('hex');
  await mkdir(config.rootDir, { recursive: true });
  if ((await lstat(config.rootDir)).isSymbolicLink()) throw new Error('工作目录不能是符号链接。');
  const marker = join(config.rootDir, '.chapter-whale-release.json');
  let installed;
  try { installed = JSON.parse(await readFile(marker, 'utf8')); } catch {}
  const venvPy = managedPythonPath(config.rootDir, 'darwin');
  const sameCandidate = installed?.buildId === manifest.buildId
    && installed?.runtimeKind === 'macos-venv'
    && installed?.requirementsSha256 === reqSha
    && existsSync(config.python)
    && existsSync(config.entry);
  if (sameCandidate) {
    const spot = await verifyInstalled(config.rootDir, manifest, ['manager', 'integration']);
    if (spot.missing.length || spot.mismatched.length) {
      config.entryExists = false;
      throw new Error('已安装的后端与发行清单不一致，请重新安装完整发行包。');
    }
    config.entryExists = true;
    return;
  }
  const lock = join(config.rootDir, '.install-lock');
  try { await mkdir(lock); } catch { throw new Error('另一个码章鲸实例正在准备环境，请稍后重试。'); }
  try {
    for (const name of CODE_TREES) {
      const source = join(codeRoot, 'backend', name);
      if (!existsSync(source)) throw new Error(`安装包缺少后端目录 ${name}，请重新安装完整的码章鲸发行包。`);
      const destination = join(config.rootDir, name);
      if (existsSync(destination) && (await lstat(destination)).isSymbolicLink()) throw new Error('运行目录不能是符号链接。');
      await cp(source, destination, { recursive: true, force: true, dereference: false });
    }
    await removeStaleCode(config.rootDir, installed?.codeFiles || installed?.files, codeFiles);
    const venvDir = join(config.rootDir, '.venv');
    let depsReady = false;
    if (existsSync(venvPy) && installed?.requirementsSha256 === reqSha) {
      if (process.env.CHAPTER_WHALE_SKIP_MAC_PIP === '1') {
        depsReady = true;
      } else {
        try {
          await execFileAsync(venvPy, ['-c', 'import fastapi, uvicorn, pydantic, httpx, aiohttp, filelock, tzdata, multipart, aiofiles, PIL, requests, playwright'], { timeout: 10_000 });
          depsReady = true;
        } catch {
          depsReady = false;
        }
      }
    }
    if (!depsReady) {
      if (!existsSync(venvPy)) {
        const basePython = findMacPython();
        await execFileAsync(basePython, ['-m', 'venv', venvDir], { timeout: 120_000 });
      }
      if (process.env.CHAPTER_WHALE_SKIP_MAC_PIP !== '1') {
        await execFileAsync(venvPy, ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-r', reqPath], {
          timeout: 10 * 60 * 1000,
          env: { ...process.env, PIP_DISABLE_PIP_VERSION_CHECK: '1', PIP_REQUIRE_VIRTUALENV: '0' },
        });
      }
    }
    await mkdir(join(config.rootDir, 'integration_data'), { recursive: true, mode: 0o700 });
    const verification = await verifyInstalled(config.rootDir, manifest, CODE_TREES);
    if (verification.missing.length || verification.mismatched.length) {
      throw new Error(`安装后校验失败（${verification.mismatched.length} 个文件不一致，${verification.missing.length} 个缺失），未写入发行标记。`);
    }
    await writeFile(marker, JSON.stringify({
      buildId: manifest.buildId, codeBuildId: manifest.buildId, runtimeBuildId: manifest.buildId,
      runtimeKind: 'macos-venv', arch: process.arch, requirementsSha256: reqSha,
      installedAt: new Date().toISOString(),
      verifiedFiles: verification.checked, codeFiles,
    }));
    config.entryExists = (await stat(config.entry)).isFile();
  } finally {
    await rm(lock, { recursive: false }).catch(async () => {
      const { rmdir } = await import('node:fs/promises');
      await rmdir(lock);
    });
  }
}

let preparing;
export async function prepareManaged(config) {
  if (!config.managed) return;
  if (preparing) return preparing;
  preparing = (async () => {
    if (process.platform === 'darwin') {
      if (!runtimeAvailable('darwin')) throw new Error('安装包缺少 macOS 运行环境依赖清单或后端源码，请重新安装码章鲸发行包。');
      const manifest = JSON.parse(await readFile(join(PACKAGE_ROOT, 'runtime-manifest.json'), 'utf8'));
      const codeRoot = codeSource();
      const codeFiles = Object.keys(manifest.files || {}).filter((name) => name.startsWith('backend/'));
      return await prepareDarwinManaged(config, manifest, codeRoot, codeFiles);
    }
    if (process.platform !== 'win32' || process.arch !== 'x64') {
      throw new Error('码章鲸当前支持 Windows 10/11 64 位与 macOS（Apple Silicon / Intel）。');
    }
    if (!runtimeAvailable('win32')) throw new Error('安装包缺少运行环境，请重新安装完整的码章鲸发行包。');
    const manifest = JSON.parse(await readFile(join(PACKAGE_ROOT, 'runtime-manifest.json'), 'utf8'));
    const codeRoot = codeSource();
    const codeFiles = Object.keys(manifest.files || {}).filter((name) => name.startsWith('backend/'));
    await mkdir(config.rootDir, { recursive: true });
    if ((await lstat(config.rootDir)).isSymbolicLink()) throw new Error('工作目录不能是符号链接。');
    const marker = join(config.rootDir, '.chapter-whale-release.json');
    let installed;
    try { installed = JSON.parse(await readFile(marker, 'utf8')); } catch {}
    const bundled = existsSync(join(PACKAGE_ROOT, 'runtime', 'python', 'python.exe'))
      && existsSync(join(PACKAGE_ROOT, 'runtime', 'browsers'));
    const runtimeSpec = bundled ? null : JSON.parse(await readFile(join(PACKAGE_ROOT, 'runtime-download.json'), 'utf8'));
    const sameCandidate = installed?.buildId === manifest.buildId
      && (installed?.runtimeBuildId ?? installed?.buildId) === (runtimeSpec?.runtimeAssetBuildId ?? manifest.buildId);
    if (sameCandidate && existsSync(config.python) && existsSync(config.entry)) {
      const spot = await verifyInstalled(config.rootDir, manifest, ['manager', 'integration']);
      if (spot.missing.length || spot.mismatched.length) {
        config.entryExists = false;
        throw new Error('已安装的后端与发行清单不一致，请重新安装完整发行包。');
      }
      config.entryExists = true;
      return;
    }
    const lock = join(config.rootDir, '.install-lock');
    try { await mkdir(lock); } catch { throw new Error('另一个码章鲸实例正在准备环境，请稍后重试。'); }
    try {
      const runtime = await resolveRuntimeSource(config.rootDir, manifest);
      // Only code/runtime trees are replaced. Books, accounts and ledgers are never copied from a developer machine.
      for (const name of CODE_TREES) {
        const source = join(codeRoot, 'backend', name);
        if (!existsSync(source)) throw new Error(`安装包缺少后端目录 ${name}，请重新安装完整的码章鲸发行包。`);
        const destination = join(config.rootDir, name);
        if (existsSync(destination) && (await lstat(destination)).isSymbolicLink()) throw new Error('运行目录不能是符号链接。');
        await cp(source, destination, { recursive: true, force: true, dereference: false });
      }
      await removeStaleCode(config.rootDir, installed?.codeFiles || installed?.files, codeFiles);
      await cp(join(runtime.root, 'runtime', 'python'), join(config.rootDir, '.venv', 'Scripts'), { recursive: true });
      // Absolute workspace path avoids embeddable Python's parent-path handling;
      // omitting import site prevents loading user-global site-packages.
      await writeFile(join(config.rootDir, '.venv', 'Scripts', 'python313._pth'),
        `python313.zip\n.\nLib/site-packages\n${config.rootDir}\n`);
      await cp(join(runtime.root, 'runtime', 'browsers'), join(config.rootDir, 'playwright-browsers'), { recursive: true });
      await mkdir(join(config.rootDir, 'integration_data'), { recursive: true });
      const verification = await verifyInstalled(config.rootDir, manifest, CODE_TREES);
      if (verification.missing.length || verification.mismatched.length) {
        throw new Error(`安装后校验失败（${verification.mismatched.length} 个文件不一致，${verification.missing.length} 个缺失），未写入发行标记。`);
      }
      await writeFile(marker, JSON.stringify({
        buildId: manifest.buildId, codeBuildId: manifest.buildId, runtimeBuildId: runtime.buildId,
        runtimeKind: runtime.kind, installedAt: new Date().toISOString(),
        verifiedFiles: verification.checked, codeFiles,
      }));
      config.entryExists = (await stat(config.entry)).isFile();
    } finally {
      await rm(lock, { recursive: false }).catch(async () => {
        // fs.rm intentionally refuses nonempty lock directories.
        const { rmdir } = await import('node:fs/promises');
        await rmdir(lock);
      });
    }
  })();
  try { return await preparing; } finally { preparing = null; }
}

export function managedEnvironment(config) {
  const env = { ...process.env, PYTHONUTF8: '1', PYTHONUNBUFFERED: '1' };
  if (!config.managed) return env;
  for (const name of Object.keys(env)) {
    if (name.startsWith('NOVEL_HELPER_') || ['AI_API_KEY', 'AI_MODEL', 'AI_BASE_URL', 'PYTHONPATH', 'PYTHONHOME'].includes(name)) delete env[name];
  }
  const managedEnv = {
    ...env,
    CHAPTER_WHALE_MANAGED: '1',
    CHAPTER_WHALE_SERVICE_MODE: 'dsh_managed',
    NOVEL_HELPER_ROOT: config.rootDir,
    NOVEL_HELPER_AI_CONFIG: join(config.rootDir, 'integration_data', 'ai_config.json'),
    NOVEL_HELPER_WEBNOVEL_HOME: join(config.rootDir, 'integration_data', 'webnovel'),
  };
  if (process.platform === 'win32' || existsSync(join(config.rootDir, 'playwright-browsers'))) {
    managedEnv.PLAYWRIGHT_BROWSERS_PATH = join(config.rootDir, 'playwright-browsers');
  }
  if (process.platform !== 'win32') {
    managedEnv.PYTHONPATH = config.rootDir;
    const pathParts = String(managedEnv.PATH || '').split(':').filter(Boolean);
    for (const extra of ['/opt/homebrew/bin', '/usr/local/bin']) {
      if (!pathParts.includes(extra)) pathParts.unshift(extra);
    }
    managedEnv.PATH = pathParts.join(':');
  }
  return managedEnv;
}

/* ------------------------------------------------- 工作区级运行描述（P05） */

export const RUN_DESCRIPTION = join('integration_data', 'run-description.json');
export const SERVICE_NAME = 'novel-helper-manager';

/** 将存在段或最近已存在父目录解析为真实长路径，兼容 Windows 8.3 短路径与符号链接。 */
function canonicalPath(value) {
  let target = resolve(String(value));
  const tail = [];
  while (true) {
    try {
      const real = realpathSync.native(target).replace(/^\\\\\?\\(?=[A-Za-z]:\\)/, '');
      return tail.length ? join(real, ...tail.reverse()) : real;
    } catch {
      const parent = dirname(target);
      if (!parent || parent === target) {
        return resolve(String(value));
      }
      tail.push(basename(target));
      target = parent;
    }
  }
}

export function normalizePath(value) {
  const canonical = canonicalPath(value);
  return process.platform === 'win32' ? canonical.toLowerCase() : canonical;
}

export function runDescriptionPath(rootDir) {
  return join(rootDir, RUN_DESCRIPTION);
}

export function readRunDescription(rootDir) {
  try {
    const value = JSON.parse(readFileSync(runDescriptionPath(rootDir), 'utf8'));
    return value && value.schema_version === 1 ? value : {};
  } catch {
    return {};
  }
}

/** 原子替换运行描述：先写临时文件再 rename，避免守护进程读到半个 JSON。 */
export function writeRunDescription(config, health = {}, options = {}) {
  const rootDir = config.rootDir;
  if (!rootDir) throw new Error('没有工作区，无法写入运行描述');
  const current = readRunDescription(rootDir);
  const payload = {
    ...current,
    schema_version: 1,
    mode: options.mode || 'dsh_managed',
    owner: options.owner || 'plugin',
    port: Number(config.port) || null,
    root: canonicalPath(rootDir),
    python: String(config.python || options.python || ''),
    entry: String(config.entry || options.entry || ''),
    pid: Number.isInteger(health.pid) ? health.pid : null,
    startup_id: health.startup_id || null,
    release_id: health.release_id || null,
    service: health.service || SERVICE_NAME,
    started_at: health.started_at || null,
    updated_at: new Date().toISOString(),
  };
  const target = runDescriptionPath(rootDir);
  mkdirSync(dirname(target), { recursive: true });
  const temporary = `${target}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  renameSync(temporary, target);
  return payload;
}

/**
 * 判断端口上的健康响应是否属于本工作区。
 * 返回 {ok, kind, message}，kind 与 Python 侧 run_description.compare 保持一致。
 */
export function compareRunDescription(description, health, rootDir, port) {
  if (health?.service && health.service !== SERVICE_NAME) {
    return { ok: false, kind: 'foreign', message: `端口 ${port} 上运行的不是码章鲸管理服务（${health.service}）` };
  }
  if (health?.root && normalizePath(health.root) !== normalizePath(rootDir)) {
    return { ok: false, kind: 'foreign', message: `端口 ${port} 上的管理服务属于其他工作区（${health.root}）` };
  }
  if (!description || !description.port) return { ok: true, kind: 'none', message: '' };
  if (Number(description.port) !== Number(port)) {
    return { ok: false, kind: 'conflict', message: `运行描述记录端口 ${description.port}，本次使用 ${port}` };
  }
  if (description.root && normalizePath(description.root) !== normalizePath(rootDir)) {
    return { ok: false, kind: 'conflict', message: '运行描述属于其他工作区' };
  }
  if (description.startup_id && health?.startup_id && description.startup_id !== health.startup_id) {
    return { ok: false, kind: 'stale', message: '运行描述记录的启动实例已经退出' };
  }
  return { ok: true, kind: 'none', message: '' };
}
