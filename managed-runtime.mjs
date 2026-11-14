import { cp, mkdir, readFile, writeFile, stat, lstat, rm, mkdtemp } from 'node:fs/promises';
import { existsSync, createWriteStream } from 'node:fs';
import { createHash } from 'node:crypto';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { dirname, join } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';

export const PACKAGE_ROOT = dirname(fileURLToPath(import.meta.url));
export function managedRoot() {
  return join(process.env.LOCALAPPDATA || join(homedir(), 'AppData', 'Local'), 'ChapterWhale', 'workspace');
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

export function runtimeAvailable() {
  return (existsSync(join(PACKAGE_ROOT, 'runtime', 'python', 'python.exe'))
    || existsSync(join(PACKAGE_ROOT, 'runtime-download.json')))
    && existsSync(join(PACKAGE_ROOT, 'backend', 'manager', 'app.py'));
}

export async function downloadRuntime(workspace, manifest) {
  const spec = JSON.parse(await readFile(join(PACKAGE_ROOT, 'runtime-download.json'), 'utf8'));
  if (!/^https:\/\/github\.com\/thus-zhou\/dsh-chapter-whale\/releases\/download\/[^/]+\/[^/]+\.tgz$/.test(spec.url)
      || !/^[a-f0-9]{64}$/.test(spec.sha256) || spec.buildId !== manifest.buildId
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
  const execute = promisify(execFile);
  const options = { windowsHide: true, maxBuffer: 8 * 1024 * 1024 };
  const { stdout } = await execute('tar.exe', ['-tvzf', archive], options);
  validateTarListing(stdout);
  await execute('tar.exe', ['-xzf', archive, '-C', staging], options);
  const payload = join(staging, 'package');
  const actual = JSON.parse(await readFile(join(payload, 'runtime-manifest.json'), 'utf8'));
  if (actual.buildId !== manifest.buildId || !existsSync(join(payload, 'runtime', 'python', 'python.exe'))) throw new Error('发行包版本不匹配。');
  return payload;
}

let preparing;
export async function prepareManaged(config) {
  if (!config.managed) return;
  if (preparing) return preparing;
  preparing = (async () => {
    if (process.platform !== 'win32' || process.arch !== 'x64') throw new Error('码章鲸当前支持 Windows 10/11 64 位。');
    if (!runtimeAvailable()) throw new Error('安装包缺少运行环境，请重新安装完整的码章鲸发行包。');
    const manifest = JSON.parse(await readFile(join(PACKAGE_ROOT, 'runtime-manifest.json'), 'utf8'));
    await mkdir(config.rootDir, { recursive: true });
    if ((await lstat(config.rootDir)).isSymbolicLink()) throw new Error('工作目录不能是符号链接。');
    const marker = join(config.rootDir, '.chapter-whale-release.json');
    let installed;
    try { installed = JSON.parse(await readFile(marker, 'utf8')); } catch {}
    if (installed?.buildId === manifest.buildId && existsSync(config.python) && existsSync(config.entry)) {
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
      const payload = existsSync(join(PACKAGE_ROOT, 'runtime', 'python', 'python.exe'))
        ? PACKAGE_ROOT : await downloadRuntime(config.rootDir, manifest);
      // Only code/runtime trees are replaced. Books, accounts and ledgers are never copied from a developer machine.
      for (const name of ['manager', 'integration', 'webnovel-writer', 'fanqie_auto_publish', 'vendor']) {
        const destination = join(config.rootDir, name);
        if (existsSync(destination) && (await lstat(destination)).isSymbolicLink()) throw new Error('运行目录不能是符号链接。');
        await cp(join(payload, 'backend', name), destination, { recursive: true, force: true, dereference: false });
      }
      await cp(join(payload, 'runtime', 'python'), join(config.rootDir, '.venv', 'Scripts'), { recursive: true });
      // Absolute workspace path avoids embeddable Python's parent-path handling;
      // omitting import site prevents loading user-global site-packages.
      await writeFile(join(config.rootDir, '.venv', 'Scripts', 'python313._pth'),
        `python313.zip\n.\nLib/site-packages\n${config.rootDir}\n`);
      await cp(join(payload, 'runtime', 'browsers'), join(config.rootDir, 'playwright-browsers'), { recursive: true });
      await mkdir(join(config.rootDir, 'integration_data'), { recursive: true });
      const verification = await verifyInstalled(
        config.rootDir, manifest, ['manager', 'integration', 'webnovel-writer', 'fanqie_auto_publish', 'vendor']);
      if (verification.missing.length || verification.mismatched.length) {
        throw new Error(`安装后校验失败（${verification.mismatched.length} 个文件不一致，${verification.missing.length} 个缺失），未写入发行标记。`);
      }
      await writeFile(marker, JSON.stringify({
        buildId: manifest.buildId, installedAt: new Date().toISOString(), verifiedFiles: verification.checked,
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
  return { ...env, CHAPTER_WHALE_MANAGED: '1', NOVEL_HELPER_ROOT: config.rootDir,
    NOVEL_HELPER_AI_CONFIG: join(config.rootDir, 'integration_data', 'ai_config.json'),
    NOVEL_HELPER_WEBNOVEL_HOME: join(config.rootDir, 'integration_data', 'webnovel'),
    PLAYWRIGHT_BROWSERS_PATH: join(config.rootDir, 'playwright-browsers') };
}
