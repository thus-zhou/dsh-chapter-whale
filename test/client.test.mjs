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
