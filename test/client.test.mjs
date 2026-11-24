/**
 * Behavioural check for the browser half.
 *
 * `client.js` is a UMD-ish bundle: it hands a factory to
 * `window.__ModuleLoader__.load({ id, factory })` and the host calls that factory
 * with a CommonJS `require`. Loading it here in `node:vm` with a fake DOM catches
 * the failures that a syntax check cannot: a top-level `document` access, an
 * exception thrown before the loader is called, a factory that returns nothing,
 * or an `apply()` that never registers the two slots the sidebar needs.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = readFileSync(join(root, 'client.js'), 'utf8');

/* The workbench flow card and the chapter modal tabs are plain markup, so a
   text-level guard is enough here: it catches a rename that silently drops the
   step list or one of the four tabs. */
test('工作台的创作流程与章节标签仍在', () => {
  assert.match(source, /\/projects\/\$\{project\.id\}\/workflow/);
  assert.match(source, /function usePoll/);
  assert.match(source, /document\.addEventListener\('visibilitychange'/);
  for (const id of ["'body'", "'quality'", "'revision'", "'versions'"]) {
    assert.ok(source.includes(id), `缺少标签 ${id}`);
  }
  assert.match(source, /@media \(max-width:720px\)/);
  assert.match(source, /className: 'nh-seg'/);
});

test('切书时旧请求不会更新新书，也不会阻塞新请求', async () => {
  const states = [];
  const refs = [];
  const memo = [];
  const effects = [];
  let indexes;
  const same = (a, b) => a && a.length === b.length && a.every((item, i) => Object.is(item, b[i]));
  const React = {
    useState(initial) {
      const i = indexes.state++;
      if (!(i in states)) states[i] = initial;
      return [states[i], (next) => { states[i] = next(states[i]); }];
    },
    useRef(value) {
      const i = indexes.ref++;
      return refs[i] ??= { current: value };
    },
    useMemo(make, deps) {
      const i = indexes.memo++;
      if (!same(memo[i]?.deps, deps)) memo[i] = { deps, value: make() };
      return memo[i].value;
    },
    useCallback(fn, deps) { return this.useMemo(() => fn, deps); },
    useEffect(fn, deps) {
      const i = indexes.effect++;
      if (same(effects[i]?.deps, deps)) return;
      effects[i]?.cleanup?.();
      effects[i] = { deps, cleanup: fn() };
    },
  };
  const begin = source.indexOf('        function usePoll(');
  const end = source.indexOf('        /* ========================================================= components', begin);
  const usePoll = vm.runInNewContext('(' + source.slice(begin, end).trim() + ')', {
    React, document: { addEventListener() {}, removeEventListener() {} },
  });
  const render = (id, fetcher) => {
    indexes = { state: 0, ref: 0, memo: 0, effect: 0 };
    return usePoll(fetcher, [id], 0);
  };
  let resolveOld;
  const old = new Promise((resolve) => { resolveOld = resolve; });
  render('old', () => old);
  const fetchNew = () => Promise.resolve('new outline');
  assert.equal(render('new', fetchNew).data, null);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(render('new', fetchNew).data, 'new outline');
  resolveOld('old outline');
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(render('new', fetchNew).data, 'new outline');
});

const noop = () => {};
const fakeNode = () => ({
  style: { setProperty: noop, removeProperty: noop },
  dataset: {},
  classList: { add: noop, remove: noop, toggle: noop, contains: () => false },
  setAttribute: noop,
  appendChild: noop,
  removeChild: noop,
  addEventListener: noop,
  removeEventListener: noop,
  querySelector: () => null,
  querySelectorAll: () => [],
  remove: noop,
});

function loadBundle() {
  let loaded = null;
  const sandbox = {
    window: {
      __ModuleLoader__: { load: (definition) => { loaded = definition; } },
      addEventListener: noop,
      removeEventListener: noop,
      location: { origin: 'http://127.0.0.1:62100', href: 'http://127.0.0.1:62100/' },
      setTimeout,
      clearTimeout,
      setInterval,
      clearInterval,
      matchMedia: () => ({ matches: false, addEventListener: noop, removeEventListener: noop }),
    },
    document: {
      createElement: fakeNode,
      createTextNode: () => fakeNode(),
      head: fakeNode(),
      body: fakeNode(),
      documentElement: { style: { setProperty: noop } },
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener: noop,
    },
    navigator: { language: 'zh-CN', userAgent: 'node' },
    localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
    MutationObserver: class {
      observe() {}
      disconnect() {}
    },
    requestAnimationFrame: (fn) => setTimeout(fn, 0),
    cancelAnimationFrame: noop,
    fetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ token: 'stub-token' }),
      text: async () => '',
      headers: { get: () => 'application/json' },
    }),
    AbortController,
    URL,
    URLSearchParams,
    TextDecoder,
    console,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
  };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox.window;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: 'client.js' });
  return loaded;
}

test('模块加载器拿到的 id 正确，且加载期不抛错', () => {
  const loaded = loadBundle();
  assert.ok(loaded, '没有调用 window.__ModuleLoader__.load');
  assert.equal(loaded.id, 'dsh-chapter-whale');
  assert.equal(typeof loaded.factory, 'function');
});

function atelierHelpers() {
  const chainable = new Proxy(function () {}, { get: (_target, key) => key === 'then' ? undefined : chainable, apply: () => chainable, construct: () => chainable });
  return loadBundle().factory(() => new Proxy({}, { get: () => chainable })).__internals;
}

test('A–E 轨道只采用当前章节的请求，不继承前一章的审查阶段', () => {
  const { chapterStage } = atelierHelpers();
  const stage = (chapter, role, requestChapter = chapter) => chapterStage({ cycle: { status: 'running', current_chapter: chapter, stage: 'local_generation' }, runtime: { last_request: { chapter: requestChapter, role } } });
  assert.equal(stage(3, 'A').index, 0);
  assert.equal(stage(3, 'C').index, 2);
  assert.equal(stage(3, 'D').index, 3);
  assert.equal(stage(3, 'D', 2).index, 1);
  assert.equal(chapterStage(null).index, -1);
  const success = chapterStage({ cycle: { status: 'success' } });
  assert.equal(success.index, 4);
  assert.equal(success.complete, true);
  assert.equal(success.active, false);
});

test('切换作品后只匹配所选作品的日更任务', () => {
  const { matchesProject } = atelierHelpers();
  const project = { id: 'book-b', path: 'O:\\books\\B' };
  assert.equal(matchesProject({ project: 'O:/books/B/' }, project), true);
  assert.equal(matchesProject({ project_id: 'book-b' }, project), true);
  assert.equal(matchesProject({ project: 'O:/books/A' }, project), false);
  assert.equal(matchesProject(null, project), false);
});

test('未定价费用与缺失速度不伪装成零；速度使用记录中的 Token 和耗时', () => {
  const { chapterMetrics } = atelierHelpers();
  assert.equal(chapterMetrics(null, null).cost, '—');
  assert.equal(chapterMetrics({ summary: { complete: false, cost_cny: '0' } }, null).cost, '—');
  assert.equal(chapterMetrics({ recent: [{ status: 'pending', output_tokens: 100, elapsed_ms: 1000 }] }, null).speed, '—');
  const recorded = chapterMetrics({ summary: { complete: true, cost_cny: '0.12' }, recent: [{ status: 'success', output_tokens: 120, elapsed_ms: 2000 }] }, { role: 'B', model: 'writer' });
  assert.equal(recorded.speed, '60.0 Token/s');
  assert.equal(recorded.model, 'writer');
  assert.equal(recorded.role, 'B');
  assert.notEqual(recorded.cost, '—');
});

test('factory 返回 name/inject/apply', () => {
  const loaded = loadBundle();
  const chainable = new Proxy(function () {}, {
    get: (_target, key) => (key === 'then' ? undefined : chainable),
    apply: () => chainable,
    construct: () => chainable,
  });
  const stubRequire = () => new Proxy({}, { get: () => chainable });
  const bundle = loaded.factory(stubRequire);
  assert.equal(typeof bundle.apply, 'function');
  assert.equal(bundle.name, 'dsh-chapter-whale');
  // Locale comes from the injected service, so it must be declared as a dependency.
  assert.deepEqual([...bundle.inject].sort(), ['locale', 'slots']);
});

test('apply 注册侧边栏入口与主区域面板', () => {
  const loaded = loadBundle();
  const chainable = new Proxy(function () {}, {
    get: (_target, key) => (key === 'then' ? undefined : chainable),
    apply: () => chainable,
    construct: () => chainable,
  });
  const bundle = loaded.factory(() => new Proxy({}, { get: () => chainable }));

  const calls = [];
  const ctx = {
    get: () => undefined,
    effect: (factory) => factory(),
    inject: (_deps, callback) => { if (callback) callback(ctx); },
    slots: {
      inject: (slot, callback) => { calls.push(`inject:${slot}`); if (callback) callback(); },
      register: (definition) => { calls.push(`register:${definition.id ?? definition.key}`); return () => {}; },
    },
  };
  bundle.apply(ctx);
  assert.deepEqual(calls, [
    'inject:sidebar.panellist',
    'register:novel-helper',
    'inject:main',
    'register:novel-helper',
  ]);
});

test('握手与令牌：客户端从 _session 取 token，并给每个请求带上', () => {
  assert.match(source, /\/novel-helper/);
  assert.match(source, /\/_session/);
  assert.match(source, /x-novel-helper-token/);
  assert.match(source, /credentials/);
});

test('不再吞掉加载错误（审计 item 15）', () => {
  assert.doesNotMatch(source, /failed to load/);
  assert.doesNotMatch(source, /__ModuleLoader__\.load[\s\S]{0,200}catch/);
});

test('面板 chrome 的文案走 locale，而不是硬编码在注册点', () => {
  assert.match(source, /locale\.register\(/);
  assert.match(source, /locale\.bind\(/);
  assert.match(source, /nav\.group\./);
});

test('样式表随 effect 一起回收（审计 F24）', () => {
  // A head that actually remembers its children: `appendChild` alone would make
  // the old "append once, never remove" implementation look correct.
  const children = [];
  const head = {
    appendChild: (node) => {
      // A real DOM sets `parentNode` on insert; the disposer uses it to decide
      // whether the node is still attached, so the fixture has to as well.
      node.parentNode = head;
      children.push(node);
      return node;
    },
    removeChild: (node) => {
      const at = children.indexOf(node);
      if (at >= 0) children.splice(at, 1);
      node.parentNode = null;
      return node;
    },
  };
  const styleNode = () => {
    const attributes = {};
    return {
      attributes,
      textContent: '',
      setAttribute: (name, value) => {
        attributes[name] = value;
      },
    };
  };

  let loaded = null;
  const sandbox = {
    window: {
      __ModuleLoader__: { load: (definition) => { loaded = definition; } },
      addEventListener: noop,
      removeEventListener: noop,
      location: { origin: 'http://127.0.0.1:62100', href: 'http://127.0.0.1:62100/' },
      matchMedia: () => ({ matches: false, addEventListener: noop, removeEventListener: noop }),
    },
    document: {
      createElement: (tag) => (tag === 'style' ? styleNode() : fakeNode()),
      head,
      body: fakeNode(),
      documentElement: { style: { setProperty: noop } },
      querySelector: (selector) =>
        selector.includes('data-plugin-css') && children.length ? children[0] : null,
      querySelectorAll: () => [],
      addEventListener: noop,
    },
    navigator: { language: 'zh-CN', userAgent: 'node' },
    localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
    MutationObserver: class { observe() {} disconnect() {} },
    requestAnimationFrame: (fn) => setTimeout(fn, 0),
    cancelAnimationFrame: noop,
    console,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
  };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox.window;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: 'client.js' });

  const chainable = new Proxy(function () {}, {
    get: (_target, key) => (key === 'then' ? undefined : chainable),
    apply: () => chainable,
    construct: () => chainable,
  });
  const bundle = loaded.factory(() => new Proxy({}, { get: () => chainable }));

  const disposers = [];
  const ctx = {
    get: () => undefined,
    effect: (factory) => {
      const dispose = factory();
      if (typeof dispose === 'function') disposers.push(dispose);
    },
    inject: (_deps, callback) => { if (callback) callback(ctx); },
    slots: { inject: (_slot, callback) => { if (callback) callback(); }, register: () => () => {} },
  };
  bundle.apply(ctx);

  assert.equal(children.length, 1, '样式节点应当只有一份');
  assert.equal(children[0].attributes['data-plugin-css'], 'dsh-chapter-whale/styles');

  for (const dispose of disposers) dispose();
  assert.equal(children.length, 0, 'dispose 后必须从 head 摘掉，否则热重载会留下死样式');
});

test('0.7.0 错误解析、读者反馈导航与后端路由面板全覆盖', async () => {
  const { default: assertMod } = await import('node:assert/strict');
  const fsMod = await import('node:fs');
  const pathMod = await import('node:path');
  const vmMod = await import('node:vm');
  const src = fsMod.readFileSync(new URL('../client.js', import.meta.url), 'utf8');
  let factoryFn = null;
  const ctx = {
    window: {
      __ModuleLoader__: {
        load(spec) {
          factoryFn = spec.factory;
        },
      },
    },
    document: { createElement: () => ({}) },
    Intl: globalThis.Intl,
    console,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    AbortController,
    fetch: async () => ({ ok: true, status: 200, text: async () => '{}' }),
  };
  vmMod.runInNewContext(src, ctx);
  assertMod.ok(typeof factoryFn === 'function', 'module factory registered');
  const exported = factoryFn((name) => {
    if (name === 'react') {
      return {
        Fragment: 'Fragment',
        createContext: (v) => ({ Provider: () => null, Consumer: () => null, _default: v }),
        createElement: () => null,
        useContext: (c) => (c ? c._default : undefined),
        useState: (v) => [typeof v === 'function' ? v() : v, () => {}],
        useEffect: () => {},
        useRef: (v) => ({ current: v }),
        useMemo: (fn) => fn(),
        useCallback: (fn) => fn,
      };
    }
    return {};
  });
  const internals = exported.__internals || {};
  assertMod.equal(typeof internals.apiErrorMessage, 'function', 'apiErrorMessage exposed on __internals');
  assertMod.equal(internals.apiErrorMessage({ detail: '详情错误' }, 400), '详情错误');
  assertMod.equal(internals.apiErrorMessage({ code: 'invalid_request', message: '参数非法' }, 422), '参数非法');
  assertMod.equal(internals.apiErrorMessage({ code: 'stale_buffer' }, 409), 'stale_buffer');
  assertMod.equal(internals.apiErrorMessage(null, 502), 'HTTP 502');

  assertMod.ok(Array.isArray(internals.NAV), 'NAV exposed on __internals');
  const flatNav = internals.NAV.flatMap((g) => g.items || []).map((i) => i.id);
  assertMod.ok(flatNav.includes('readers'), 'NAV includes readers');
  assertMod.ok(src.includes("'nav.readers'"), 'DICTIONARY includes nav.readers');

  for (const snippet of [
    '/schedule',
    '/precheck',
    '/entities',
    '/retrieval',
    '/evidence/impact',
    '/readers/preview',
    '/readers/observations',
    '/browser/target',
    '/publish/platforms',
    '/publish/export',
    '/notifications',
  ]) {
    assertMod.ok(src.includes(snippet), `client.js includes route ${snippet}`);
  }
});

test('v5 液态玻璃重整、DashboardPage 无异常渲染与 standalone Web API 契约', async () => {
  const { default: assertMod } = await import('node:assert/strict');
  const fsMod = await import('node:fs');
  const vmMod = await import('node:vm');
  const src = fsMod.readFileSync(new URL('../client.js', import.meta.url), 'utf8');
  let factoryFn = null;
  const storage = new Map();
  const ctx = {
    window: {
      __ModuleLoader__: { load(spec) { factoryFn = spec.factory; } },
      matchMedia: () => ({ matches: false }),
    },
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => { storage.set(k, String(v)); },
    },
    document: { createElement: () => ({}) },
    Intl: globalThis.Intl,
    console,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    AbortController,
    fetch: async () => ({ ok: true, status: 200, text: async () => '{}' }),
  };
  vmMod.runInNewContext(src, ctx);
  const exported = factoryFn((name) => {
    if (name === 'react') {
      return {
        Fragment: 'Fragment',
        createContext: (v) => ({ Provider: () => null, Consumer: () => null, _default: v }),
        createElement: (type, props, ...children) => ({ type, props: props || {}, children }),
        useContext: (c) => (c ? c._default : undefined),
        useState: (v) => [typeof v === 'function' ? v() : v, () => {}],
        useEffect: () => {},
        useRef: (v) => ({ current: v }),
        useMemo: (fn) => fn(),
        useCallback: (fn) => fn,
      };
    }
    return {};
  });
  const internals = exported.__internals || {};

  // 1. readAppearance migrates legacy palettes and clamps sliders
  storage.set('chapter-whale-appearance-v2', JSON.stringify({ palette: 'gemini', opacity: 99, blur: 1, refract: 999, backdrop: 5 }));
  const migratedGemini = internals.readAppearance();
  assertMod.equal(migratedGemini.palette, 'liquid');
  assertMod.equal(migratedGemini.opacity, 78);
  assertMod.equal(migratedGemini.blur, 4);
  assertMod.equal(migratedGemini.refract, 160);
  assertMod.equal(migratedGemini.backdrop, 35);
  storage.set('chapter-whale-appearance-v2', JSON.stringify({ palette: 'ocean' }));
  assertMod.equal(internals.readAppearance().palette, 'apple');

  // 2. HUBS covers all 6 top-dock workspaces (array returned from vm context -> convert via Array.from)
  assertMod.deepEqual(
    Array.from(internals.HUBS || [], (h) => h.id),
    ['work', 'studio', 'insights', 'publish', 'ops', 'system'],
  );

  // 3. DashboardPage renders without throwing ReferenceError (e.g. queue or icon checks)
  const tree = internals.DashboardPage({
    overview: {
      projects: [{ id: 'p1', title: '测试书', chapters: 2, target_chapters: 100 }],
      jobs: [],
      queue: { queued: 3, published: 2 },
      ai: { configured: true },
    },
    job: null,
    studio: { wordCount: '3500' },
    navigate: () => {},
    onOpenChapter: () => {},
  });
  assertMod.ok(tree && tree.props && String(tree.props.className).includes('cw-dashboard'));

  // 4. Standalone liquid-glass.js syntax & corrected API contract keys
  const webLgSrc = fsMod.readFileSync(new URL('../backend/manager/static/liquid-glass.js', import.meta.url), 'utf8');
  new vmMod.Script(webLgSrc, { filename: 'backend/manager/static/liquid-glass.js' });
  for (const snippet of ['data.findings', 'data-pc-action="ignored"', 'obs.cards', 'plan.supplied', 'visibilitychange', 'chapter-whale:overview']) {
    assertMod.ok(webLgSrc.includes(snippet), `liquid-glass.js includes ${snippet}`);
  }

  // 5. Regression guards for GET body handling, role test status check, 1-based precheck paragraph, and max_revisions bound
  assertMod.match(source, /hasBody\s*&&\s*options\s*&&\s*options\.body\s*!==\s*undefined/);
  assertMod.match(source, /result\.status\s*!==\s*'ok'/);
  assertMod.match(source, /Number\(item\.paragraph\)\s*\+\s*1/);
  const staticAppSrc = fsMod.readFileSync(new URL('../backend/manager/static/app.js', import.meta.url), 'utf8');
  assertMod.doesNotMatch(staticAppSrc, /name="max_revisions"[^>\n]*max="5"/);
  assertMod.ok(staticAppSrc.includes('chapter-whale:overview'));
});
