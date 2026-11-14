/**
 * dsh-chapter-whale — Host half.
 *
 * Three jobs:
 *   1. Expose the 小说助手 manager (127.0.0.1:8765) on this origin so the native
 *      panel can call it without CORS.
 *   2. Start the manager silently when it is not running, then wait for readiness.
 *   3. Give the Agent a `novel_helper` tool over the same HTTP surface.
 *
 * Security model (see DETAIL.md §Security):
 *   gate 1  Host header must be a loopback authority — blocks DNS rebinding.
 *   gate 2  Origin / Sec-Fetch-Site must be same-origin — blocks cross-site writes.
 *   gate 3  Every plugin endpoint except `_session` needs a per-process bearer
 *           token. The token is handed out same-origin only, so a cross-site page
 *           can neither read it (no CORS) nor send it (custom header = preflight).
 *   gate 4  Only whitelisted method+path pairs may mutate the manager.
 *
 * The plugin itself writes nothing into the 小说助手 project; it only reads files
 * to report state and spawns the manager the user configured.
 */
import Schema from '@deepseek-ai/schemastery';
import { randomBytes, timingSafeEqual } from 'node:crypto';
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  readSync,
  readdirSync,
  statSync,
} from 'node:fs';
import { spawn } from 'node:child_process';
import { join, resolve } from 'node:path';
import { managedRoot, runtimeAvailable, prepareManaged, managedEnvironment } from './managed-runtime.mjs';

const PLUGIN_ID = 'dsh-chapter-whale';
const ROUTE = '/novel-helper';
const SERVICE_PATH = `${ROUTE}/_service`;
const SESSION_PATH = `${ROUTE}/_session`;
const STOP_PATH = `${ROUTE}/_stop`;
const TOKEN_HEADER = 'x-novel-helper-token';
const API_VERSION = 1;

const STOP_WAIT_MS = 12_000;

const DEFAULT_PORT = 18765;
const PROBE_TIMEOUT_MS = 1800;
const DEFAULT_START_TIMEOUT_MS = 75_000;
const DEFAULT_UPSTREAM_TIMEOUT_MS = 180_000;
const DEFAULT_MAX_BODY_BYTES = 64 * 1024 * 1024;

export const name = PLUGIN_ID;
export const inject = ['tools'];

/** Runtime configuration. Every field is optional; defaults live in resolveConfig. */
export const Config = Schema.object({
  rootDir: Schema.string().description(
    '高级选项：连接已有小说助手目录。普通用户留空，自动使用内置环境。',
  ),
  python: Schema.string().description(
    '高级选项：覆盖解释器。普通用户留空，使用内置 Python。',
  ),
  port: Schema.natural().min(1).max(65535).default(DEFAULT_PORT).description(
    'manager 监听端口（仅 127.0.0.1）。',
  ),
  autoStart: Schema.boolean().default(true).description('服务未运行时是否自动拉起 manager。'),
  allowLanStart: Schema.boolean().default(false).description(
    '拉起 manager 时是否传 --lan（仅在本机已配置设备配对时开启）。',
  ),
  startTimeoutMs: Schema.natural().min(1_000).max(600_000).default(DEFAULT_START_TIMEOUT_MS),
  stopOnDispose: Schema.boolean().default(false).description(
    '插件卸载/宿主退出时，是否停止本插件拉起的 manager（默认关闭：正在跑的长任务不应被 HMR 打断）。',
  ),
  upstreamTimeoutMs: Schema.natural().min(1_000).max(600_000).default(DEFAULT_UPSTREAM_TIMEOUT_MS),
  maxBodyBytes: Schema.natural().min(1_024).default(DEFAULT_MAX_BODY_BYTES),
});

/* ------------------------------------------------------------------ config */

/** Candidate interpreter paths, most specific first. Cross-platform on purpose. */
function pythonCandidates(rootDir, platform = process.platform) {
  const local = platform === 'win32'
    ? [join(rootDir, '.venv', 'Scripts', 'python.exe'), join(rootDir, 'venv', 'Scripts', 'python.exe')]
    : [join(rootDir, '.venv', 'bin', 'python3'), join(rootDir, '.venv', 'bin', 'python')];
  return local;
}

function defaultPython(rootDir, platform = process.platform) {
  for (const candidate of pythonCandidates(rootDir, platform)) {
    try {
      if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
    } catch {
      /* ignore unreadable candidate */
    }
  }
  return platform === 'win32' ? 'python' : 'python3';
}

/**
 * Normalize and validate the plugin configuration.
 * @param config - raw Cordis row config.
 * @returns resolved runtime configuration.
 * @throws {Error} for out-of-range numbers or a configured rootDir that is not a directory.
 */
export function resolveConfig(config = {}) {
  const rawPort = config.port ?? DEFAULT_PORT;
  const port = Number(rawPort);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${PLUGIN_ID}: port 必须是 1-65535 的整数，收到 ${String(rawPort)}`);
  }

  const rawRoot = typeof config.rootDir === 'string' ? config.rootDir.trim() : '';
  const rootDir = rawRoot ? resolve(rawRoot) : managedRoot();
  if (rawRoot) {
    let stat;
    try {
      stat = statSync(rootDir);
    } catch {
      throw new Error(`${PLUGIN_ID}: rootDir 不存在：${rootDir}`);
    }
    if (!stat.isDirectory()) throw new Error(`${PLUGIN_ID}: rootDir 不是目录：${rootDir}`);
  }

  const python = String(config.python || '').trim() || (rawRoot ? defaultPython(rootDir) : join(rootDir, '.venv', 'Scripts', 'python.exe'));
  const entry = join(rootDir, 'manager', 'app.py');

  return {
    port,
    managed: !rawRoot,
    rootDir,
    python,
    entry,
    configuredRoot: Boolean(rawRoot),
    entryExists: existsSync(entry),
    autoStart: config.autoStart !== false,
    allowLanStart: config.allowLanStart === true,
    startTimeoutMs: Number(config.startTimeoutMs) || DEFAULT_START_TIMEOUT_MS,
    stopOnDispose: config.stopOnDispose === true,
    upstreamTimeoutMs: Number(config.upstreamTimeoutMs) || DEFAULT_UPSTREAM_TIMEOUT_MS,
    maxBodyBytes: Number(config.maxBodyBytes) || DEFAULT_MAX_BODY_BYTES,
  };
}

function baseUrl(config) {
  return `http://127.0.0.1:${config.port}`;
}

/* --------------------------------------------------------- access control */

const LOOPBACK_AUTHORITIES = new Set(['127.0.0.1', 'localhost', '[::1]']);

/**
 * Read the hostname out of a Host header without trusting its port.
 * @param authority - raw `host` header value.
 * @returns lower-cased hostname, or undefined when the header is unusable.
 */
export function hostnameOf(authority) {
  if (typeof authority !== 'string') return undefined;
  const raw = authority.trim().toLowerCase();
  if (!raw) return undefined;
  if (raw.startsWith('[')) {
    const end = raw.indexOf(']');
    return end === -1 ? raw : raw.slice(0, end + 1);
  }
  const colon = raw.lastIndexOf(':');
  const hostname = colon === -1 ? raw : raw.slice(0, colon);
  return hostname || undefined;
}

/**
 * Gate 1: the request must address this machine by a loopback name.
 * Blocks DNS rebinding, where an attacker domain resolves to 127.0.0.1.
 */
export function isLoopbackAuthority(authority) {
  const hostname = hostnameOf(authority);
  return hostname !== undefined && LOOPBACK_AUTHORITIES.has(hostname);
}

/**
 * Gate 2: browser-originated requests must be same-origin with the Host header.
 * Non-browser clients (no Origin, no Sec-Fetch-Site) pass; they are local
 * processes that could reach the manager port directly anyway.
 * @returns undefined when allowed, otherwise a machine-readable reason.
 */
export function originProblem(headers, authority) {
  const site = headers['sec-fetch-site'];
  if (typeof site === 'string' && site !== 'same-origin' && site !== 'none') {
    return 'cross-site-request';
  }
  const origin = headers.origin;
  if (origin === undefined) return undefined;
  if (origin === 'null') return 'opaque-origin';
  let parsed;
  try {
    parsed = new URL(String(origin));
  } catch {
    return 'malformed-origin';
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return 'unsupported-origin-scheme';
  const expected = String(authority || '').trim().toLowerCase();
  if (!expected || parsed.host.toLowerCase() !== expected) return 'cross-origin-request';
  return undefined;
}

/**
 * Gate 4: the mutation surface. Every entry below mirrors a manager route that
 * the panel legitimately calls; `:name` matches exactly one decoded segment.
 * Anything absent from this table is refused before a socket to the manager opens.
 */
const WRITE_ROUTES = [
  'POST /api/projects',
  'POST /api/projects/create',
  'POST /api/projects/:identity/creative/chat',
  'POST /api/projects/:identity/creative/expand',
  'PUT /api/projects/:identity/creative',
  'POST /api/projects/:identity/memory/items',
  'PUT /api/projects/:identity/memory/items/:item',
  'POST /api/projects/:identity/memory/items/:item/archive',
  'PUT /api/projects/:identity/memory/items/:item/correct',
  'POST /api/projects/:identity/memory/candidates/:chapter/commit',
  'POST /api/projects/:identity/characters',
  'PUT /api/projects/:identity/characters/:person/correct',
  'POST /api/projects/:identity/characters/candidates/:chapter/commit',
  'POST /api/projects/:identity/memory/rebuild',
  'POST /api/projects/:identity/samples',
  'POST /api/projects/:identity/samples/:sample/learn',
  'POST /api/projects/:identity/samples/:sample/delete',
  'PUT /api/projects/:identity/style-profile',
  'POST /api/projects/:identity/style-profile/rebuild',
  'POST /api/projects/:identity/plan',
  'POST /api/projects/:identity/batches/:batch/resume',
  'POST /api/projects/:identity/chapters/:chapter/polish',
  'POST /api/projects/:identity/chapters/:chapter/review',
  'POST /api/projects/:identity/chapters/:chapter/revision',
  'POST /api/projects/:identity/chapters/:chapter/revision/accept',
  'POST /api/projects/:identity/chapters/:chapter/revision/reject',
  'POST /api/projects/:identity/chapters/:chapter/restore',
  'PUT /api/projects/:identity/outline',
  'POST /api/projects/:identity/generate',
  'POST /api/projects/:identity/stage',
  'POST /api/accounts/login',
  'POST /api/accounts/:name/confirm-login',
  'POST /api/publish',
  'POST /api/jobs',
  'PUT /api/jobs/:identity',
  'POST /api/jobs/:identity/run',
  'POST /api/jobs/:identity/recover',
  'POST /api/jobs/:identity/approve',
  'POST /api/operations/:identity/cancel',
  'PUT /api/ai',
  'PUT /api/ai/roles',
  'POST /api/ai/models',
  'POST /api/ai/test',
  'POST /api/ai/roles/:role/test',
  'POST /api/ai/roles/test',
  'GET /api/ai/providers',
  'POST /api/ai/providers',
  'PUT /api/ai/providers/:identity',
  'DELETE /api/ai/providers/:identity',
  'POST /api/ai/providers/:identity/models',
  'POST /api/ai/providers/:identity/test',
  'POST /api/ai/providers/:identity/reprice',
  'PUT /api/ai/bindings',
  'POST /api/ai/providers/migrate',
  'POST /api/ai/providers/dsh/import',
  'GET /api/ai/free-channels',
  'POST /api/ai/free-channels/scan',
  'POST /api/ai/free-channels/import',
  'GET /api/ai/role-checks',
  'PUT /api/settings',
  'PUT /api/costs/pricing',
  'GET /api/free-model/status',
  'POST /api/free-model/start',
  'GET /api/free-model/summary',
  'POST /api/free-model/refresh',
  'POST /api/free-model/rpc',
  'PUT /api/free-model/pool',
  'POST /api/access/code',
  'POST /api/access/pair',
  'POST /api/access/logout',
  'DELETE /api/access/devices/:identity',
].map((spec) => {
  const [method, pattern] = spec.split(' ');
  return { method, segments: pattern.split('/').filter(Boolean) };
});

function routeMatches(route, method, segments) {
  if (route.method !== method) return false;
  if (route.segments.length !== segments.length) return false;
  for (let index = 0; index < segments.length; index += 1) {
    const expected = route.segments[index];
    if (!expected.startsWith(':') && expected !== segments[index]) return false;
  }
  return true;
}

/**
 * @returns whether `method path` is a whitelisted mutation of the manager.
 */
export function allowsMutation(method, segments) {
  return WRITE_ROUTES.some((route) => routeMatches(route, method, segments));
}

/** Reads are side-effect free in this manager; writes are never implicitly allowed. */
export function allowsRead(segments) {
  return segments.length >= 2 && segments[0] === 'api' && segments[1] !== '_service';
}

const SAFE_METHODS = new Set(['GET', 'HEAD']);

/* ------------------------------------------------------------------ policy */

/**
 * Turn a raw request target into the decoded segment list the policy matches on.
 * Rejects anything whose decoded form could address a different upstream path.
 * @returns segments, or a rejection reason.
 */
export function parseTarget(rawTarget) {
  const raw = String(rawTarget || '/');
  if (!raw.startsWith(`${ROUTE}/`) && raw !== ROUTE) return { error: 'outside-route' };
  const queryAt = raw.indexOf('?');
  const pathname = queryAt === -1 ? raw : raw.slice(0, queryAt);
  const search = queryAt === -1 ? '' : raw.slice(queryAt);
  const suffix = pathname.slice(ROUTE.length) || '/';

  let decoded;
  try {
    decoded = decodeURIComponent(suffix);
  } catch {
    return { error: 'invalid-encoding' };
  }
  // Second check on the decoded form (audit item 14): separators and dot
  // segments that only appear after decoding are refused too.
  if (decoded.includes('\\')) return { error: 'backslash' };
  if (decoded.includes('\0')) return { error: 'nul-byte' };
  if (!decoded.startsWith('/')) return { error: 'bad-prefix' };
  const segments = decoded.split('/').slice(1);
  if (segments.some((part) => part === '' || part === '.' || part === '..')) {
    return { error: 'dot-segment' };
  }
  if (segments.some((part) => part.includes('%') || part.includes('?'))) {
    return { error: 'encoded-separator' };
  }
  return { segments, search, suffix };
}

/* ------------------------------------------------------------------ helpers */

const delay = (ms) => new Promise((done) => setTimeout(done, ms));

function logDir(config) {
  return join(config.rootDir, 'integration_data', 'manager-logs');
}

/** Last N characters of a log file, for honest failure reporting. */
function tailFile(path, limit = 4000) {
  try {
    const size = statSync(path).size;
    const start = Math.max(0, size - limit);
    const fd = openSync(path, 'r');
    try {
      const buffer = Buffer.alloc(Math.min(limit, size));
      readSync(fd, buffer, 0, buffer.length, start);
      return buffer.toString('utf8');
    } finally {
      closeSync(fd);
    }
  } catch {
    return '';
  }
}

function lastSpawnedLog(config) {
  try {
    const dir = logDir(config);
    if (!existsSync(dir)) return { out: '', err: '' };
    const files = readdirSync(dir)
      .filter((entry) => entry.endsWith('.plugin.err.log'))
      .sort();
    if (!files.length) return { out: '', err: '' };
    const newest = files[files.length - 1];
    return {
      name: newest,
      err: tailFile(join(dir, newest)),
      out: tailFile(join(dir, newest.replace('.plugin.err.log', '.plugin.out.log'))),
    };
  } catch {
    return { out: '', err: '' };
  }
}

function configHint(config) {
  if (config.managed) return runtimeAvailable() ? undefined : '安装包不完整，请安装包含运行环境的码章鲸发行包。';
  if (!config.configuredRoot && !config.entryExists) {
    return '未找到 manager/app.py：请在插件配置里填写 rootDir（小说助手 项目根目录）。';
  }
  if (!config.entryExists) {
    return `未找到启动入口 ${config.entry}：请确认 rootDir 指向小说助手项目根目录。`;
  }
  return undefined;
}

/* ------------------------------------------------------------- service probe */

async function probe(config, signal) {
  // Always ask the port first: a manager started outside DSH is perfectly valid,
  // and a missing rootDir only means *we* cannot start one ourselves.
  const hint = configHint(config);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  const forwardAbort = () => controller.abort();
  signal?.addEventListener('abort', forwardAbort, { once: true });
  try {
    const response = await fetch(`${baseUrl(config)}/api/health`, {
      signal: controller.signal,
      headers: { accept: 'application/json' },
    });
    if (!response.ok) {
      return { running: false, httpStatus: response.status, error: hint, unconfigured: Boolean(hint), hint };
    }
    const body = await response.json();
    return { running: body?.service === 'novel-helper-manager', health: body, hint };
  } catch (error) {
    return {
      running: false,
      error: hint || String(error?.message || error),
      unconfigured: Boolean(hint),
      hint,
    };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', forwardAbort);
  }
}

let startingPromise = null;
/** The manager process *this* Host process spawned, if any. */
let spawnedChild = null;

/** True only for the pid we started; a manager someone else launched is left alone. */
function ownsPid(pid) {
  return Number.isInteger(pid) && spawnedChild?.pid === pid && spawnedChild.exitCode === null;
}

/** Report a rejected spawn/telemetry promise instead of letting it become an unhandled rejection. */
function swallow(promise, onError) {
  if (!promise || typeof promise.then !== 'function') return;
  promise.catch(onError);
}

async function ensureStarted(config, signal) {
  const current = await probe(config, signal);
  if (current.running) return { started: false, ...current };
  if (!config.autoStart) return { started: false, ...current, autoStart: false };
  if (startingPromise) return startingPromise;

  startingPromise = (async () => {
    await prepareManaged(config);
    const hint = configHint(config);
    if (hint) return { started: false, error: hint, ...current };
    const dir = logDir(config);
    try {
      mkdirSync(dir, { recursive: true });
    } catch (error) {
      return { started: false, error: `无法创建日志目录：${String(error?.message || error)}`, ...current };
    }
    const stamp = new Date()
      .toISOString()
      .replace(/[-:]/g, '')
      .replace(/\..+/, '')
      .replace('T', '-');
    const outPath = join(dir, `${stamp}.plugin.out.log`);
    const errPath = join(dir, `${stamp}.plugin.err.log`);

    const args = ['-X', 'utf8', '-u', config.entry, '--port', String(config.port)];
    if (config.allowLanStart) args.push('--lan');

    let child;
    let fdOut = 0;
    let fdErr = 0;
    let spawnError = null;
    try {
      fdOut = openSync(outPath, 'a');
      fdErr = openSync(errPath, 'a');
      child = spawn(config.python, args, {
        cwd: config.rootDir,
        detached: true,
        windowsHide: true,
        stdio: ['ignore', fdOut, fdErr],
        env: managedEnvironment(config),
      });
      // A missing interpreter emits 'error' asynchronously; without a listener the
      // whole Host process would see an unhandled 'error' event (audit F23).
      child.on('error', (error) => {
        spawnError = error;
      });
      child.once('exit', () => {
        if (spawnedChild === child) spawnedChild = null;
      });
      spawnedChild = child;
      child.unref();
    } catch (error) {
      return { started: false, error: `无法启动服务：${String(error?.message || error)}`, ...current };
    } finally {
      for (const fd of [fdOut, fdErr]) {
        try {
          if (fd) closeSync(fd);
        } catch {
          /* already closed */
        }
      }
    }
    // Track the process' lifetime without letting a rejection escape.
    swallow(child.exitCode === null ? new Promise((done) => child.once('exit', done)) : Promise.resolve(), () => {});

    const deadline = Date.now() + config.startTimeoutMs;
    while (Date.now() < deadline) {
      if (signal?.aborted) return { started: false, aborted: true, pid: child.pid };
      await delay(600);
      if (spawnError) {
        const logs = lastSpawnedLog(config);
        return {
          started: false,
          error: `无法启动服务：${String(spawnError.message || spawnError)}`,
          logFile: logs.name || null,
          logTail: (logs.err || logs.out || '').slice(-3000),
        };
      }
      const state = await probe(config, signal);
      if (state.running) return { started: true, pid: child.pid, ...state };
      if (child.exitCode !== null) break;
    }
    if (signal?.aborted) return { started: false, aborted: true, pid: child.pid };
    const logs = lastSpawnedLog(config);
    const died = child.exitCode !== null;
    return {
      started: false,
      pid: child.pid,
      exitCode: child.exitCode,
      error: died
        ? `服务进程已退出（exit ${child.exitCode}）`
        : `服务在 ${Math.round(config.startTimeoutMs / 1000)} 秒内未就绪`,
      logFile: logs.name || null,
      logTail: (logs.err || logs.out || '').slice(-3000),
    };
  })();

  try {
    return await startingPromise;
  } catch (error) {
    return { started: false, error: `启动失败：${String(error?.message || error)}`, ...current };
  } finally {
    startingPromise = null;
  }
}

/**
 * Stop the manager — but only the one this Host process started.
 *
 * A detached child survives the Host exiting (that is the point of `detached`),
 * so without an explicit stop the Python process outlives DSH forever. Killing
 * whatever answers on the port would be worse than leaking it: the manager may
 * be the user's own long-running publish worker. So ownership is decided by pid
 * identity against the child we spawned, never by "something is listening".
 */
async function stopService(config, signal) {
  const state = await probe(config, signal);
  if (!state.running) return { stopped: false, running: false, detail: '服务未在运行' };
  const pid = state.health?.pid;
  if (!Number.isInteger(pid)) {
    return { stopped: false, running: true, code: 'no-pid', detail: '健康检查没有返回 pid，无法判断归属' };
  }
  if (!ownsPid(pid)) {
    return {
      stopped: false,
      running: true,
      code: 'foreign-process',
      pid,
      detail: `pid ${pid} 不是本插件启动的进程；请用它自己的方式停止（插件不会去杀一个不属于自己的服务）`,
    };
  }
  try {
    spawnedChild.kill('SIGTERM');
  } catch (error) {
    return { stopped: false, running: true, pid, error: String(error?.message || error) };
  }
  const deadline = Date.now() + STOP_WAIT_MS;
  while (Date.now() < deadline) {
    await delay(350);
    const after = await probe(config, signal).catch(() => ({ running: true }));
    if (!after.running) return { stopped: true, running: false, pid };
    if (signal?.aborted) return { stopped: false, running: true, pid, aborted: true };
  }
  return {
    stopped: false,
    running: true,
    pid,
    error: `已发送 SIGTERM，但 ${Math.round(STOP_WAIT_MS / 1000)} 秒内仍未退出`,
  };
}

/* -------------------------------------------------------------------- proxy */

function readBody(request, limit) {
  return new Promise((done, fail) => {
    const chunks = [];
    let size = 0;
    request.on('data', (chunk) => {
      size += chunk.length;
      if (size > limit) {
        fail(new Error(`请求体超过 ${Math.round(limit / 1024 / 1024)}MB`));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on('end', () => done(Buffer.concat(chunks)));
    request.on('error', fail);
  });
}

function sendJson(response, status, value, extraHeaders) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
    'cross-origin-resource-policy': 'same-origin',
    vary: 'origin',
    ...extraHeaders,
  });
  response.end(body);
}

async function forward(request, response, config, context, targetPath, search) {
  const method = (request.method || 'GET').toUpperCase();
  const headers = { accept: 'application/json, text/plain, */*' };
  const contentType = request.headers['content-type'];
  if (contentType) headers['content-type'] = contentType;
  // The manager refuses writes without its own marker. The marker is not a
  // credential: gate 4 already decided this exact method+path may mutate, and
  // gate 3 authenticated the caller. Only mutations carry it upstream.
  if (!SAFE_METHODS.has(method)) headers['x-novel-helper'] = '1';

  let body;
  if (!SAFE_METHODS.has(method)) body = await readBody(request, config.maxBodyBytes);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.upstreamTimeoutMs);
  const abortAll = () => controller.abort();
  request.once('close', abortAll);
  try {
    const upstream = await fetch(`${baseUrl(config)}${targetPath}${search}`, {
      method,
      headers,
      body,
      signal: controller.signal,
      redirect: 'manual',
    });
    const buffer = Buffer.from(await upstream.arrayBuffer());
    response.writeHead(upstream.status, {
      'content-type': upstream.headers.get('content-type') || 'application/json; charset=utf-8',
      'content-length': buffer.length,
      'cache-control': 'no-store',
      'x-content-type-options': 'nosniff',
      'cross-origin-resource-policy': 'same-origin',
      vary: 'origin',
    });
    response.end(method === 'HEAD' ? undefined : buffer);
  } catch (error) {
    const aborted = error?.name === 'AbortError';
    sendJson(response, aborted ? 504 : 502, {
      detail: aborted
        ? `请求超时（${Math.round(config.upstreamTimeoutMs / 1000)} 秒）；服务可能正在执行长任务`
        : `无法连接小说助手服务：${String(error?.message || error)}`,
      service_down: true,
    });
  } finally {
    clearTimeout(timer);
    request.off?.('close', abortAll);
  }
}

/* ------------------------------------------------------------------- routes */

function tokenMatches(actual, expected) {
  if (typeof actual !== 'string' || actual.length !== expected.length) return false;
  return timingSafeEqual(Buffer.from(actual), Buffer.from(expected));
}

/**
 * Build the single route handler. Exported so the test harness can drive it with
 * a fake request/response pair, without a running Web host.
 */
export function createHandler(config, token) {
  return async function handle(request, response) {
    const method = (request.method || 'GET').toUpperCase();
    const authority = request.headers.host;

    if (method === 'OPTIONS') {
      // No CORS is ever granted: a preflight fails, so a cross-origin page can
      // never attach the token header.
      sendJson(response, 403, { detail: '不允许跨站请求' });
      return;
    }
    if (!isLoopbackAuthority(authority)) {
      sendJson(response, 403, { detail: '只接受本机回环地址访问' });
      return;
    }
    const problem = originProblem(request.headers, authority);
    if (problem) {
      sendJson(response, 403, { detail: '拒绝跨站请求', reason: problem });
      return;
    }

    const parsed = parseTarget(request.url);
    if (parsed.error) {
      sendJson(response, parsed.error === 'outside-route' ? 404 : 400, { detail: `路径不被接受：${parsed.error}` });
      return;
    }
    const { segments, search, suffix } = parsed;
    const isSession = segments.length === 1 && segments[0] === '_session';
    if (isSession) {
      if (method !== 'GET' && method !== 'HEAD') {
        sendJson(response, 405, { detail: '只支持 GET' });
        return;
      }
      sendJson(response, 200, {
        plugin: PLUGIN_ID,
        apiVersion: API_VERSION,
        route: ROUTE,
        token,
      });
      return;
    }

    if (!tokenMatches(request.headers[TOKEN_HEADER], token)) {
      sendJson(response, 401, { detail: '缺少或错误的插件令牌', code: 'plugin-token-required' });
      return;
    }

    const isService = (segments.length === 1 && segments[0] === '_service')
      || (segments.length === 2 && segments[0] === 'api' && segments[1] === '_service');
    if (isService) {
      if (method === 'POST') {
        const result = await ensureStarted(config);
        sendJson(response, 200, { ok: Boolean(result.running), ...redactService(result) });
        return;
      }
      if (method !== 'GET' && method !== 'HEAD') {
        sendJson(response, 405, { detail: '只支持 GET 与 POST' });
        return;
      }
      const state = await probe(config);
      const logs = lastSpawnedLog(config);
      sendJson(response, 200, {
        ok: Boolean(state.running),
        running: Boolean(state.running),
        httpStatus: state.httpStatus ?? null,
        service: state.health
          ? {
            service: state.health.service,
            release_id: state.health.release_id,
            pid: state.health.pid,
            started_at: state.health.started_at,
          }
          : null,
        error: state.unconfigured ? null : state.error || null,
        hint: configHint(config) || null,
        autoStart: config.autoStart,
        port: config.port,
        logFile: logs.name || null,
        logTail: (logs.err || '').slice(-1500) || null,
      });
      return;
    }

    const isStop = segments.length === 1 && segments[0] === '_stop';
    if (isStop) {
      if (method !== 'POST') {
        sendJson(response, 405, { detail: '只支持 POST' });
        return;
      }
      const result = await stopService(config);
      sendJson(response, result.stopped ? 200 : result.code === 'foreign-process' ? 409 : 200, {
        ok: Boolean(result.stopped),
        ...result,
      });
      return;
    }

    if (!suffix.startsWith('/api/')) {
      sendJson(response, 404, { detail: '请从侧边栏「小说助手」面板访问' });
      return;
    }

    if (SAFE_METHODS.has(method)) {
      if (!allowsRead(segments)) {
        sendJson(response, 404, { detail: `未代理的路径：${suffix}` });
        return;
      }
    } else if (!allowsMutation(method, segments)) {
      sendJson(response, 403, {
        detail: `${method} ${suffix} 不在允许的写操作白名单内`,
        code: 'mutation-not-allowed',
      });
      return;
    }

    await forward(request, response, config, { method, segments }, suffix, search);
  };
}

/** Strip machine paths from the HTTP face of the service endpoint. */
function redactService(result) {
  const { rootDir, python, entry, ...rest } = result;
  return rest;
}

function installRoutes(ctx, config, token) {
  ctx.inject(['webServer'], (scoped) => {
    const server = scoped.webServer ?? scoped.get?.('webServer');
    if (!server || typeof server.register !== 'function') return;
    const disposers = [];
    disposers.push(
      server.register({ kind: 'prefix', path: ROUTE, handler: createHandler(config, token) }),
    );
    ctx.effect(
      () => () => {
        for (const dispose of disposers) {
          try {
            dispose();
          } catch {
            /* already gone */
          }
        }
      },
      'novel-helper: routes',
    );
  });
}

/* --------------------------------------------------------------------- tool */

function textRender(_args, value) {
  return [{ type: 'text', text: JSON.stringify(value, null, 1) }];
}

/** Read one upstream JSON document, honouring both the timeout and the caller's signal. */
async function requestUpstream(config, method, path, body, signal) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.upstreamTimeoutMs);
  const forwardAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', forwardAbort, { once: true });
  }
  try {
    const headers = { accept: 'application/json' };
    let payload;
    if (method !== 'GET' && method !== 'HEAD') {
      headers['content-type'] = 'application/json';
      headers['x-novel-helper'] = '1';
      payload = JSON.stringify(body ?? {});
    }
    const response = await fetch(`${baseUrl(config)}${path}`, {
      method,
      headers,
      body: payload,
      signal: controller.signal,
    });
    const text = await response.text();
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
    return { response, parsed };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', forwardAbort);
  }
}

function assertToolPath(path, method) {
  if (!path.startsWith('/api/')) throw new Error('path 必须以 /api/ 开头');
  // Decode before judging, exactly like the HTTP bridge: `%2e%2e%2f` must not
  // travel one segment deeper through the tool than it does through the panel.
  let decoded = path;
  try {
    decoded = decodeURIComponent(path);
  } catch {
    throw new Error('path 不是合法的 URL 编码');
  }
  if (decoded.includes('\\') || decoded.includes('\0')) {
    throw new Error('path 不允许包含反斜杠或空字节');
  }
  const segments = decoded.split('?')[0].split('/').filter(Boolean);
  if (segments.some((part) => part === '.' || part === '..' || part === '')) {
    throw new Error('path 不允许包含上级目录引用或空段');
  }
  if (method === 'GET') {
    if (!allowsRead(segments)) throw new Error(`不支持的读取路径：${path}`);
  } else if (!allowsMutation(method, segments)) {
    throw new Error(
      `${method} ${path} 不在写操作白名单内。可先调用 action=status 查看状态，或改用面板完成该操作。`,
    );
  }
  return segments;
}

function makeTool(ctx, config) {
  return {
    name: 'novel_helper',
    description:
      '读取或操作本机「小说助手」应用（127.0.0.1:8765，经插件白名单代理）。'
      + 'action=status 查看服务与总览；action=get 读取只读 API 路径；'
      + 'action=post 提交写操作，必须同时传 confirm=true。'
      + '写操作会真实影响写作/发布流程。',
    parameters: {
      type: 'object',
      properties: {
        action: { type: 'string', enum: ['status', 'get', 'post'] },
        path: {
          type: 'string',
          description: 'API 路径，例如 /api/overview 或 /api/projects/<id>/chapters',
        },
        body: { type: 'object', description: 'action=post 时的 JSON 请求体' },
        confirm: {
          type: 'boolean',
          description: 'action=post 时必须为 true：表示已确认这次写操作。',
        },
      },
      required: ['action'],
      additionalProperties: false,
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: textRender,
    },
    async execute(args, exec) {
      const action = args?.action;
      const signal = exec?.signal;
      if (action === 'status') {
        const state = await probe(config, signal);
        const result = {
          running: Boolean(state.running),
          port: config.port,
          rootDir: config.rootDir,
          python: config.python,
          entry: config.entry,
          health: state.health || null,
          error: state.error || null,
          hint: state.unconfigured ? configHint(config) : undefined,
        };
        if (state.running) {
          try {
            const { parsed } = await requestUpstream(config, 'GET', '/api/overview', undefined, signal);
            const overview = parsed;
            result.overview = {
              projects: overview.projects,
              accounts: overview.accounts,
              queue: overview.queue,
              diagnostics: overview.diagnostics,
              jobs: (overview.jobs || []).map((job) => ({
                id: job.id,
                name: job.name,
                enabled: job.enabled,
                last_status: job.last_status,
                last_message: job.last_message,
                cycle_status: job.cycle?.status ?? null,
                cycle_stage: job.cycle?.stage ?? null,
                current_chapter: job.cycle?.current_chapter ?? null,
              })),
            };
          } catch (error) {
            result.overviewError = String(error?.message || error);
          }
        }
        return result;
      }

      const path = String(args?.path || '');
      const method = action === 'post' ? 'POST' : 'GET';
      assertToolPath(path, method);

      if (method !== 'GET') {
        if (args?.confirm !== true) {
          throw new Error(`写操作需要确认：请传 confirm=true 后再执行 ${path}`);
        }
        const approval = await requestApproval(ctx, exec, path);
        if (!approval.allowed) throw new Error(`写操作未获批准：${approval.reason || approval.outcome}`);
      }

      const { response, parsed } = await requestUpstream(config, method, path, args?.body, signal);
      if (!response.ok) {
        const detail = parsed && typeof parsed === 'object' && parsed.detail
          ? parsed.detail
          : typeof parsed === 'string'
            ? parsed.slice(0, 800)
            : '请求失败';
        throw new Error(`${response.status} ${detail}`);
      }
      return { ok: true, status: response.status, data: parsed };
    },
  };
}

/**
 * Ask the Host approval service when one is attached. A host without the service
 * (or outside a turn) still needs the explicit `confirm` flag from the caller.
 */
async function requestApproval(ctx, exec, path) {
  const approval = ctx.get?.('approval');
  if (!approval || typeof approval.request !== 'function') return { allowed: false, outcome: 'no-service', reason: '请在码章鲸面板确认并执行此操作' };
  try {
    const outcome = await approval.request({
      agent: exec?.agent,
      toolName: 'novel_helper',
      callId: exec?.callId,
      reason: `novel_helper 写操作：${path}`,
      signal: exec?.signal,
    });
    return { allowed: outcome === 'allowed-once', outcome, reason: outcome };
  } catch (error) {
    return { allowed: false, outcome: 'unavailable', reason: '确认服务暂不可用，请在码章鲸面板操作' };
  }
}

/* -------------------------------------------------------------------- apply */

export function apply(ctx, config = {}) {
  const resolved = resolveConfig(config);
  const token = randomBytes(24).toString('base64url');
  installRoutes(ctx, resolved, token);
  ctx.effect(() => {
    const dispose = ctx.tools.register(makeTool(ctx, resolved));
    return typeof dispose === 'function' ? dispose : () => {};
  }, 'novel-helper: tool');
  if (resolved.stopOnDispose) {
    // Opt-in: a plugin reload during a publish run must not SIGTERM the worker.
    ctx.effect(
      () => () => {
        if (spawnedChild && spawnedChild.exitCode === null) spawnedChild.kill('SIGTERM');
      },
      'novel-helper: stop on dispose',
    );
  }
}

export default { name, inject, Config, apply, resolveConfig };

/** Stable surface for the package's own test harness. */
export const __internals = {
  PLUGIN_ID,
  ROUTE,
  SERVICE_PATH,
  SESSION_PATH,
  TOKEN_HEADER,
  WRITE_ROUTES,
  allowsMutation,
  allowsRead,
  assertToolPath,
  makeTool,
  parseTarget,
  originProblem,
  isLoopbackAuthority,
  hostnameOf,
  redactService,
};
