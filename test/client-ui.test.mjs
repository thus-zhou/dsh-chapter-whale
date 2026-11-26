/**
 * Recursive component tests for the browser half.
 *
 * The legacy smoke test only walked the top-level element, so a `ReferenceError`
 * inside `Bars` (and the crashed CostsPage/ReadersPage tabs) still passed. The
 * renderer below actually invokes function components, keeps hook slots across
 * passes, and runs effects — enough to execute every page end to end without a
 * browser. Data comes from a fetch stub that records request bodies, so the
 * pricing/job contracts are checked as payloads rather than string matches.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const root = new URL('..', import.meta.url);
const source = readFileSync(new URL('client.js', root), 'utf8');
const appSource = readFileSync(new URL('backend/manager/static/app.js', root), 'utf8');

const noop = () => {};
const depsEqual = (a, b) =>
  Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));

function createReactRuntime() {
  let current = null;
  const stack = [];
  let dirty = false;
  const React = {
    Fragment: Symbol('Fragment'),
    createContext(value) {
      return {
        _default: value,
        Provider: (props) => props.children,
        Consumer: (props) => (typeof props.children === 'function' ? props.children(value) : null),
      };
    },
    createElement(type, props, ...children) {
      const merged = { ...(props || {}) };
      if (children.length) merged.children = children.length === 1 ? children[0] : children;
      return { type, props: merged };
    },
    useContext(context) {
      return context ? context._default : undefined;
    },
    useState(initial) {
      const index = current.index++;
      if (!(index in current.hooks)) {
        current.hooks[index] = { value: typeof initial === 'function' ? initial() : initial };
      }
      const slot = current.hooks[index];
      return [
        slot.value,
        (next) => {
          slot.value = typeof next === 'function' ? next(slot.value) : next;
          dirty = true;
        },
      ];
    },
    useRef(initial) {
      const index = current.index++;
      if (!(index in current.hooks)) current.hooks[index] = { current: initial };
      return current.hooks[index];
    },
    useMemo(make, deps) {
      const index = current.index++;
      const slot = current.hooks[index];
      if (!slot || !depsEqual(slot.deps, deps)) current.hooks[index] = { deps, value: make() };
      return current.hooks[index].value;
    },
    useCallback(fn, deps) {
      return React.useMemo(() => fn, deps);
    },
    useEffect(fn, deps) {
      const index = current.index++;
      const slot = current.hooks[index];
      if (slot && depsEqual(slot.deps, deps)) return;
      current.hooks[index] = { deps };
      const cleanup = fn();
      if (typeof cleanup === 'function') current.hooks[index].cleanup = cleanup;
    },
  };
  return {
    React,
    push(instance) {
      stack.push(current);
      current = instance;
    },
    pop() {
      current = stack.pop();
    },
    consumeDirty() {
      const value = dirty;
      dirty = false;
      return value;
    },
  };
}

function normalizeChildren(props) {
  const children = props && props.children;
  if (children === undefined || children === null) return [];
  return Array.isArray(children) ? children : [children];
}

function createRenderer(runtime) {
  const instances = new Map();

  const renderNode = (node, path) => {
    if (node === null || node === undefined || node === false || node === true) return null;
    if (typeof node !== 'object') return { kind: 'text', text: String(node) };
    const { type, props = {} } = node;
    if (typeof type === 'function') {
      let instance = instances.get(path);
      if (!instance || instance.type !== type) {
        instance = { type, hooks: [], index: 0 };
        instances.set(path, instance);
      }
      instance.index = 0;
      runtime.push(instance);
      let output;
      try {
        output = type(props);
      } finally {
        runtime.pop();
      }
      return renderNode(output, `${path}/c`);
    }
    const children = normalizeChildren(props);
    if (type === runtime.React.Fragment) {
      return { kind: 'fragment', type, props, children: children.map((child, index) => renderNode(child, `${path}/f${index}`)) };
    }
    return { kind: 'element', type, props, children: children.map((child, index) => renderNode(child, `${path}/${index}`)) };
  };

  return {
    render(element) {
      return renderNode(element, 'root');
    },
  };
}

function walk(node, visit) {
  if (!node) return;
  visit(node);
  for (const child of node.children || []) walk(child, visit);
}

function textOf(node) {
  if (!node) return '';
  if (node.kind === 'text') return node.text;
  return (node.children || []).map(textOf).join('');
}

function findAll(tree, predicate) {
  const matches = [];
  walk(tree, (node) => {
    if (predicate(node)) matches.push(node);
  });
  return matches;
}

function findByText(tree, text) {
  return findAll(tree, (node) => node.kind === 'element' && node.type === 'button' && textOf(node) === text)[0] || null;
}

function jsonResponse(data) {
  const text = JSON.stringify(data);
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => text,
    json: async () => data,
  };
}

function fakeNode() {
  return {
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
    focus: noop,
    getClientRects: () => [],
  };
}

function loadClient(routes = {}) {
  let loaded = null;
  const calls = [];
  const fetch = async (url, init = {}) => {
    let path = String(url).replace(/^.*\/novel-helper/, '') || '/';
    if (path.startsWith('/api')) path = path.slice(4);
    const method = String(init.method || 'GET').toUpperCase();
    calls.push({ path, method, body: init.body ? JSON.parse(init.body) : undefined });
    if (path === '/_session') return jsonResponse({ token: 'test-token' });
    let data = typeof routes === 'function' ? routes(path, method, init) : routes[path];
    if (data === undefined) data = {};
    if (data instanceof Error) throw data;
    return jsonResponse(data);
  };
  const sandbox = {
    window: {
      __ModuleLoader__: { load: (definition) => { loaded = definition; } },
      addEventListener: noop,
      removeEventListener: noop,
      location: { origin: 'http://127.0.0.1:8765', href: 'http://127.0.0.1:8765/' },
      matchMedia: () => ({ matches: false, addEventListener: noop, removeEventListener: noop }),
      dispatchEvent: noop,
    },
    document: {
      hidden: false,
      activeElement: null,
      createElement: fakeNode,
      createTextNode: () => fakeNode(),
      head: fakeNode(),
      body: fakeNode(),
      documentElement: { style: { setProperty: noop }, dataset: {} },
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener: noop,
      removeEventListener: noop,
    },
    navigator: { language: 'zh-CN', userAgent: 'node' },
    localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
    MutationObserver: class {
      observe() {}
      disconnect() {}
    },
    requestAnimationFrame: (fn) => setTimeout(fn, 0),
    cancelAnimationFrame: noop,
    fetch,
    AbortController,
    URL,
    URLSearchParams,
    TextDecoder,
    Intl,
    console,
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    clearInterval: noop,
  };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox.window;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: 'client.js' });
  assert.ok(loaded, '客户端没有注册模块');
  const runtime = createReactRuntime();
  const exported = loaded.factory((name) => (name === 'react' ? runtime.React : {}));
  return { internals: exported.__internals, runtime, renderer: createRenderer(runtime), calls };
}

async function renderPasses(harness, element, passes = 4) {
  let tree = null;
  for (let pass = 0; pass < passes; pass += 1) {
    tree = harness.renderer.render(element);
    await new Promise((resolve) => setImmediate(resolve));
    if (!harness.runtime.consumeDirty()) break;
  }
  return tree;
}

const overview = (extra = {}) => ({  projects: [{ id: 'p1', title: '星海归途', chapters: 3, target_chapters: 100 }],
  jobs: [],
  queue: { queued: 0, published: 0, books: [] },
  accounts: [],
  ai: { configured: true },
  operations: [],
  ...extra,
});

test('CostsPage 默认 cost tab 真实递归渲染（P1-21）', async () => {
  const harness = loadClient({
    '/costs': {
      summary: { cost_cny: '2.50', calls: 4, input_tokens: 1000, output_tokens: 500, cached_tokens: 100, reasoning_tokens: 0, complete: true, unpriced: 0, unknown_usage: 0 },
      daily: [{ key: '2026-11-01', cost_cny: '1.20' }, { key: '2026-11-02', cost_cny: '0.80' }],
      models: [{ key: 'gpt-x', calls: 2, input_tokens: 100, output_tokens: 50, cost_cny: '1.2' }],
      stages: [{ key: 'writing', cost_cny: '1.2' }],
    },
  });
  const tree = await renderPasses(harness, harness.runtime.React.createElement(harness.internals.CostsPage, {}));
  assert.ok(tree, 'CostsPage 没有返回组件树');
  const activeTab = findByText(tree, '用量与成本');
  assert.ok(activeTab, '缺少“用量与成本”标签');
  assert.equal(activeTab.props['data-active'], 'true', '默认 tab 必须是 cost');
  const bars = findAll(tree, (node) => node.kind === 'element' && node.props.className === 'nh-bar');
  assert.equal(bars.length, 2, '按天成本条形图应渲染两个数据点');
});

test('ReadersPage 有数据时真实渲染，Bars 不再抛 ReferenceError（P1-21）', async () => {
  const harness = loadClient((path) => {
    if (path === '/projects/p1/readers/dictionary') return { metrics: [{ metric: 'chapter_completion_rate', label: '读完率' }], batches: [] };
    if (path.startsWith('/projects/p1/readers/series')) {
      return {
        points: [
          { key: 'k1', chapter_id: 1, value: 42, unit: '%', denominator: 100, denominator_known: true, window: ['2026-11-01', '2026-11-02'], stage: 'ok', batch: 'b1' },
          { key: 'k2', chapter_id: 2, value: 55, unit: '%', denominator: 100, denominator_known: true, window: ['2026-11-02', '2026-11-03'], stage: 'ok', batch: 'b1' },
        ],
        limitations: ['样本仍小'],
      };
    }
    if (path.startsWith('/projects/p1/readers/comments')) return { clusters: [], trace: [] };
    if (path.startsWith('/projects/p1/readers/observations')) return { cards: [], active: [] };
    return {};
  });
  const element = harness.runtime.React.createElement(harness.internals.ReadersPage, { overview: overview() });
  let tree = await renderPasses(harness, element);
  assert.ok(tree, 'ReadersPage 没有返回组件树');
  const trendTab = findByText(tree, '趋势与局限');
  assert.ok(trendTab, '缺少趋势与局限标签');
  trendTab.props.onClick();
  tree = await renderPasses(harness, element, 2);
  const bars = findAll(tree, (node) => node.kind === 'element' && node.props.className === 'nh-bar');
  assert.equal(bars.length, 2, '读者趋势条形图应渲染两个读数点');
  assert.match(textOf(tree), /55/);
});

test('未完成批次使用 id，不再请求 batches/undefined（P1-14）', async () => {
  const harness = loadClient((path) => {
    if (path === '/projects/p1/chapters') return { chapters: [] };
    if (path === '/projects/p1/workflow') return { pending_batches: [{ id: 'abc123def456' }] };
    return {};
  });
  const tree = await renderPasses(harness, harness.runtime.React.createElement(harness.internals.ChaptersPage, {
    overview: overview(),
    allOperations: [],
    studio: { wordCount: '3500' },
    refreshOverview: noop,
  }));
  const button = findByText(tree, '继续原批次');
  assert.ok(button, '没有渲染继续原批次按钮');
  await button.props.onClick();
  const posted = harness.calls.find((call) => call.method === 'POST' && call.path.includes('/batches/'));
  assert.ok(posted, '没有发出批次请求');
  assert.equal(posted.path, '/projects/p1/batches/abc123def456/resume');
  assert.ok(!posted.path.includes('undefined'), `路径不应包含 undefined：${posted.path}`);
  assert.doesNotMatch(source, /batch_id\s*\)/);
});

test('定价 payload 符合 CostRateInput，且同模型多 base_url 独立编辑（P1-15/P2-7）', async () => {
  const harness = loadClient();
  const { buildPricingPayload, pricingRateKey } = harness.internals;
  const data = {
    revision: 4,
    usd_to_cny: null,
    rates: [
      { base_url: 'https://a.example/v1', model: 'gpt-x', currency: 'USD', input: '1', output: '2', cached: '0.5' },
      { base_url: 'https://b.example/v1', model: 'gpt-x', currency: 'USD', input: '3', output: '4', cached: null },
    ],
  };
  const keyA = pricingRateKey(data.rates[0]);
  const keyB = pricingRateKey(data.rates[1]);
  assert.notEqual(keyA, keyB, '同模型不同 base_url 不能共用编辑 key');
  const payload = buildPricingPayload(data, { [keyA]: { input: '9' }, [keyB]: { output: '8' } });
  assert.equal(payload.rates.length, 2);
  assert.equal(payload.rates[0].input_per_million, 9);
  assert.equal(payload.rates[1].input_per_million, 3);
  assert.equal(payload.rates[1].output_per_million, 8);
  assert.equal(payload.rates[1].base_url, 'https://b.example/v1');
  assert.equal(payload.rates[0].currency, 'USD');
  assert.deepEqual(Object.keys(payload.rates[0]).sort(), [
    'base_url', 'cached_per_million', 'currency', 'input_per_million', 'model', 'output_per_million',
  ]);
  assert.equal('usd_to_cny' in payload, false, 'usd_to_cny 为 null 时不能写默认 7.2');
  assert.equal(payload.reprice_unpriced, true);

  const withFx = buildPricingPayload({ ...data, usd_to_cny: 7.11 }, {});
  assert.equal(withFx.usd_to_cny, 7.11);
  assert.equal(withFx.rates[1].cached_per_million, undefined);
});

test('PricingPage 保存时按 CostRateInput 提交且不写默认汇率（P1-15/P2-7）', async () => {
  const rates = [
    { base_url: 'https://a.example/v1', model: 'gpt-x', currency: 'USD', input: '1', output: '2', cached: '0.5' },
    { base_url: 'https://b.example/v1', model: 'gpt-x', currency: 'USD', input: '3', output: '4', cached: null },
  ];
  const harness = loadClient({
    '/costs/pricing': { revision: 2, usd_to_cny: null, rates, models: [] },
  });
  const element = harness.runtime.React.createElement(harness.internals.PricingPage, { embedded: true });
  let tree = await renderPasses(harness, element);
  const rows = findAll(tree, (node) => node.kind === 'element' && node.type === 'tr');
  assert.equal(rows.length, 3, '表头 + 两行同模型不同 base_url 的定价');
  const numberInputs = findAll(tree, (node) => node.kind === 'element' && node.type === 'input' && node.props.type === 'number');
  assert.equal(numberInputs.length, 6);
  numberInputs[0].props.onChange({ target: { value: '9' } });
  tree = await renderPasses(harness, element, 2);
  const save = findByText(tree, '保存定价并重算');
  assert.ok(save, '编辑后应出现保存按钮');
  await save.props.onClick();
  const put = harness.calls.find((call) => call.method === 'PUT' && call.path === '/costs/pricing');
  assert.ok(put, '没有提交定价 PUT');
  assert.equal(put.body.rates.length, 2);
  assert.equal(put.body.rates[0].input_per_million, 9);
  assert.equal(put.body.rates[1].input_per_million, 3, '第二条同模型不同 base_url 的编辑不能串到第一条');
  assert.equal('usd_to_cny' in put.body, false);
  assert.equal(put.body.rates[0].input, undefined);
  assert.equal(put.body.rates[0].model, 'gpt-x');
});

test('JobsPage 空态表单可选账号，发布模式必填账号（P1-17/P1-25）', async () => {
  const harness = loadClient();
  const element = harness.runtime.React.createElement(harness.internals.JobsPage, {
    overview: overview({ accounts: [{ name: 'main', logged_in: true }] }),
    allOperations: [],
    studio: { wordCount: '3500' },
    refreshOverview: noop,
  });
  let tree = await renderPasses(harness, element);
  const modeSelect = findAll(tree, (node) => node.kind === 'element' && node.type === 'select')
    .find((node) => textOf(node).includes('立即发布到番茄'));
  assert.ok(modeSelect, '空态表单缺少投递方式下拉');
  const accountSelect = findAll(tree, (node) => node.kind === 'element' && node.type === 'select')
    .find((node) => textOf(node).includes('main'));
  assert.ok(accountSelect, '空态表单缺少账号选择');

  const createButton = findByText(tree, '创建日更任务');
  await createButton.props.onClick();
  let post = harness.calls.filter((call) => call.method === 'POST' && call.path === '/jobs').at(-1);
  assert.equal(post.body.publication_mode, 'draft_only');
  assert.equal(post.body.account, '');
  assert.equal(post.body.name, '《星海归途》· 日更');

  modeSelect.props.onChange({ target: { value: 'publish_now' } });
  tree = await renderPasses(harness, element, 2);
  const refreshedAccount = findAll(tree, (node) => node.kind === 'element' && node.type === 'select')
    .find((node) => textOf(node).includes('main'));
  refreshedAccount.props.onChange({ target: { value: 'main' } });
  tree = await renderPasses(harness, element, 2);
  await findByText(tree, '创建日更任务').props.onClick();
  post = harness.calls.filter((call) => call.method === 'POST' && call.path === '/jobs').at(-1);
  assert.equal(post.body.publication_mode, 'publish_now');
  assert.equal(post.body.account, 'main');
});

test('PublishPage 只显示当前作品的发布任务（login 例外）（P2-2）', async () => {
  const harness = loadClient();
  const tree = await renderPasses(harness, harness.runtime.React.createElement(harness.internals.PublishPage, {
    overview: overview({
      accounts: [{ name: 'main', logged_in: true }],
      operations: [
        { id: 'op-a', kind: 'publish', status: 'running', project_id: 'p1' },
        { id: 'op-b', kind: 'publish', status: 'running', project_id: 'p2' },
        { id: 'op-login', kind: 'login', status: 'awaiting_login' },
      ],
    }),
    refreshOverview: noop,
  }));
  const bars = findAll(tree, (node) => node.kind === 'element' && node.props.className === 'cw-progress-wrap');
  assert.equal(bars.length, 2, '应只保留当前书 publish 与全局 login 两条进度');
});

test('Dashboard 全局操作单独分组，不算当前书（P2-3）', async () => {
  const harness = loadClient({
    '/costs': { summary: {}, daily: [], models: [], stages: [], recent: [] },
    '/projects/p1/chapters': { chapters: [] },
    '/projects/p1/workflow': { steps: [] },
  });
  const tree = await renderPasses(harness, harness.runtime.React.createElement(harness.internals.DashboardPage, {
    overview: overview(),
    allOperations: [{ id: 'global-1', kind: 'generate', status: 'running' }],
    job: null,
    studio: { wordCount: '3500' },
    navigate: noop,
    onOpenChapter: noop,
  }));
  assert.match(textOf(tree), /全局任务/);
  const ribbons = findAll(tree, (node) => node.kind === 'element' && node.props.className === 'cw-gemini-box');
  assert.equal(ribbons.length, 0, '全局任务不应占据当前书的工作流进度条');
});

test('免费渠道兜底 id 与后端一致，登录链接/二维码过滤协议（P1-18/P2-5/P2-6）', () => {
  const harness = loadClient();
  const { FREE_CHANNEL_FALLBACKS, safeHttpUrl, safeQrSrc, loginPollReady, OP_ACTIVE_STATUSES } = harness.internals;
  assert.deepEqual(
    Array.from(FREE_CHANNEL_FALLBACKS, (channel) => channel.id),
    ['codearts', 'buddy', 'workbuddy', 'lobsterai', 'qoder', 'qodercn', 'trae', 'cline', 'loomy', 'raccoon', 'minimax', 'zcode', 'gemini'],
  );
  assert.equal(safeHttpUrl('javascript:alert(1)'), '');
  assert.equal(safeHttpUrl('data:text/html,x'), '');
  assert.equal(safeHttpUrl('https://example.com/login'), 'https://example.com/login');
  assert.equal(safeQrSrc('javascript:alert(1)'), '');
  assert.equal(safeQrSrc('data:image/png;base64,AAAA'), 'data:image/png;base64,AAAA');
  assert.equal(safeQrSrc(''), '');
  assert.equal(loginPollReady({ provider: 'x', accountId: 'pending' }), false);
  assert.equal(loginPollReady({ provider: 'x', accountId: '' }), false);
  assert.equal(loginPollReady({ provider: 'x', accountId: 'x-1' }), true);
  assert.ok(OP_ACTIVE_STATUSES.includes('awaiting_login'));
});

/* ---------------------------------------------------------- Web 控制台 */

function webConsoleHarness() {
  const elements = new Map();
  const form = {
    elements: {},
    querySelector: () => null,
    reportValidity: () => true,
  };
  for (const name of ['name', 'project', 'book', 'publication_mode', 'account', 'daily_times_text', 'chapters_per_run', 'word_count', 'timezone', 'max_revisions', 'approval_mode']) {
    form.elements[name] = { value: '', checked: false, onchange: null };
  }
  form.elements.enabled = { value: '', checked: false, onchange: null };

  const element = (id) => {
    if (!elements.has(id)) {
      elements.set(id, {
        id,
        style: { setProperty: noop },
        dataset: {},
        classList: { add: noop, remove: noop, toggle: noop, contains: () => false },
        textContent: '',
        innerHTML: '',
        value: '',
        checked: false,
        hidden: false,
        disabled: false,
        open: false,
        addEventListener: noop,
        removeEventListener: noop,
        setAttribute: noop,
        appendChild: noop,
        firstElementChild: null,
        querySelector: () => (id === 'action-dialog' ? form : null),
        querySelectorAll: () => [],
        closest: (selector) => (selector === '.file-drop' ? element('sample-file') : null),
        showModal() { this.open = true; },
        close() { this.open = false; },
        remove: noop,
        prepend: noop,
        focus: noop,
      });
    }
    return elements.get(id);
  };
  const document = {
    getElementById: element,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => element(`created-${Math.random()}`),
    documentElement: { dataset: {} },
    addEventListener: noop,
    removeEventListener: noop,
    body: { classList: { add: noop, remove: noop, toggle: noop, contains: () => false } },
  };
  const sandbox = {
    document,
    window: { addEventListener: noop, removeEventListener: noop, dispatchEvent: noop, NovelCosts: null, NovelProviders: null, NovelMemory: null },
    localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
    Intl,
    console,
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    clearInterval: noop,
    fetch: async () => jsonResponse({ projects: [{ id: 'p1', path: 'O:/A', title: '星海归途', chapters: 0 }], jobs: [], operations: [], accounts: [], queue: { books: [] }, diagnostics: { checks: [] }, ai: {}, settings: {} }),
    AbortController,
    CustomEvent: class {
      constructor(type, init) { this.type = type; this.detail = init && init.detail; }
    },
    confirm: () => false,
    location: { hash: '', assign: noop },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(appSource, sandbox, { filename: 'app.js' });
  return { sandbox, element, form };
}

function formData(entries) {
  return {
    get(key) { return entries[key]; },
    [Symbol.iterator]() { return Object.entries(entries)[Symbol.iterator](); },
  };
}

test('Web 控制台 jobDialog 支持 publication_mode，draft_only 不要登录账号（P1-24）', async () => {
  const { sandbox, form } = webConsoleHarness();
  vm.runInContext(`
    state.projects = [{ id: 'p1', path: 'O:/A', title: '星海归途' }];
    state.accounts = [];
    globalThis.__dialog = null;
    openDialog = (title, content, onSubmit) => { globalThis.__dialog = { title, content, onSubmit }; };
    closeDialog = () => {};
    toast = () => {};
    refresh = async () => {};
    api = async (path, method, payload) => { globalThis.__api = { path, method, payload }; return {}; };
  `, sandbox);
  vm.runInContext('jobDialog()', sandbox);
  const dialog = sandbox.__dialog;
  assert.ok(dialog, '没有登录账号时仍应打开只存稿任务对话框');
  assert.match(dialog.content, /name="publication_mode"/);
  assert.match(dialog.content, /value="platform_scheduled"/);

  await dialog.onSubmit(formData({
    name: '《星海归途》· 日更', project: 'O:/A', book: '星海归途',
    publication_mode: 'draft_only', account: '', daily_times_text: '09:00',
    chapters_per_run: '2', word_count: '3500', timezone: 'Asia/Shanghai',
    max_revisions: '1', approval_mode: 'unattended',
  }), form);
  assert.equal(sandbox.__api.path, '/api/jobs');
  assert.equal(sandbox.__api.method, 'POST');
  assert.equal(sandbox.__api.payload.publication_mode, 'draft_only');
  assert.equal(sandbox.__api.payload.account, '');

  const publishDialog = sandbox.__dialog;
  await assert.rejects(
    publishDialog.onSubmit(formData({
      name: 'n', project: 'O:/A', book: 'b', publication_mode: 'publish_now', account: '',
      daily_times_text: '09:00', chapters_per_run: '1', word_count: '3500',
      timezone: 'Asia/Shanghai', max_revisions: '1', approval_mode: 'unattended',
    }), form),
    /必须选择已登录账号/,
  );

  vm.runInContext("state.accounts = [{ name: 'main', logged_in: true }];", sandbox);
  const jobDialogFn = vm.runInContext('jobDialog', sandbox);
  jobDialogFn({ id: 'j1', name: 'n', project: 'O:/A', book: 'b', account: 'main', publication_mode: 'platform_scheduled', daily_time: '09:00', timezone: 'Asia/Shanghai', chapters_per_run: 1, word_count: 3500, max_revisions: 1, enabled: true });
  const editDialog = sandbox.__dialog;
  assert.equal(editDialog.title, '编辑日更');
  await editDialog.onSubmit(formData({
    name: 'n', project: 'O:/A', book: 'b', publication_mode: 'platform_scheduled', account: 'main',
    daily_times_text: '09:00', chapters_per_run: '1', word_count: '3500',
    timezone: 'Asia/Shanghai', max_revisions: '1', approval_mode: 'unattended',
  }), form);
  assert.equal(sandbox.__api.path, '/api/jobs/j1');
  assert.equal(sandbox.__api.method, 'PUT');
  assert.equal(sandbox.__api.payload.publication_mode, 'platform_scheduled');
  assert.equal(sandbox.__api.payload.account, 'main');
});

test('默认任务名统一为《书名》· 日更（P2-11）', () => {
  assert.match(source, /`《\$\{project\.title\}》· 日更`/);
  assert.match(appSource, /`《\$\{firstBook\}》· 日更`/);
  assert.match(appSource, /`《\$\{p\.title\}》· 日更`/);
});
