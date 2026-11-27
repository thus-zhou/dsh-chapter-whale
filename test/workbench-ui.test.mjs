/**
 * Static invariants for the local-Web 直写工作台.
 *
 * These tests deliberately do not boot a browser: they pin the contracts that
 * are easy to break silently — script order, IME safety, the no-innerHTML rule,
 * the draft identity fields, mobile layout, and that every mutation route used
 * by the UI is registered in index.js WRITE_ROUTES.
 */
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const root = new URL('..', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');

const html = read('backend/manager/static/index.html');
const js = read('backend/manager/static/workbench.js');
const css = read('backend/manager/static/workbench.css');
const core = read('backend/manager/static/workbench-core.js');
const indexJs = read('index.js');

const workbenchSection = (() => {
  const start = html.indexOf('id="page-workbench"');
  assert.ok(start >= 0, 'index.html must contain section#page-workbench');
  const open = html.lastIndexOf('<section', start);
  const next = html.indexOf('<section class="page" id="page-jobs"', start);
  assert.ok(open >= 0 && next > open, 'workbench section must be a sibling page section');
  return html.slice(open, next);
})();

const clientSource = read('client.js');

function between(text, begin, end) {
  const start = text.indexOf(begin);
  assert.ok(start >= 0, 'missing generated block start: ' + begin);
  const stop = text.indexOf(end, start + begin.length);
  assert.ok(stop > start, 'missing generated block end: ' + end);
  return text.slice(start + begin.length, stop);
}

function generatedAtelierCss(client) {
  const block = between(client,
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

function expectedAtelierCss() {
  const fonts = [
    ['manrope', 'Whale Geometric', '200 800'],
    ['notosanssc', 'Whale Text', '100 900'],
    ['notoserifsc', 'Whale Editorial', '400'],
  ].map(([file, family, weight]) => {
    const data = readFileSync(new URL(`assets/fonts/${file}.woff2`, root)).toString('base64');
    return `@font-face{font-family:"${family}";src:url(data:font/woff2;base64,${data}) format("woff2");font-weight:${weight};font-display:swap}`;
  });
  return fonts.join('\n') + '\n' + read('assets/atelier-base.css') + '\n' + read('assets/atelier-native.css');
}

function generatedWorkbenchCore(client) {
  return between(client,
    '        // BEGIN GENERATED WORKBENCH CORE\n',
    '        // END GENERATED WORKBENCH CORE\n');
}

function loadWorkbenchHooks() {
  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    WorkbenchCore: {},
    document: { readyState: 'loading', addEventListener: () => {} },
    window: {},
    localStorage: { getItem: () => null, setItem: () => {} },
    location: { hash: '' },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(js, sandbox, { filename: 'workbench.js' });
  assert.ok(sandbox.__workbenchTestHooks, 'workbench.js must expose its pure decisions for behaviour tests');
  return sandbox.__workbenchTestHooks;
}

test('workbench assets exist and are non-trivial', () => {
  assert.ok(existsSync(new URL('backend/manager/static/workbench.js', root)));
  assert.ok(existsSync(new URL('backend/manager/static/workbench.css', root)));
  assert.ok(js.length > 40000, 'workbench.js should contain the real implementation');
  assert.ok(css.length > 12000, 'workbench.css should contain the responsive layout');
});

test('index.html loads workbench-core before workbench, both deferred, with css', () => {
  assert.match(html, /<link rel="stylesheet" href="\/static\/workbench\.css">/);
  const coreAt = html.indexOf('src="/static/workbench-core.js"');
  const workbenchAt = html.indexOf('src="/static/workbench.js"');
  assert.ok(coreAt >= 0, 'workbench-core.js must be linked');
  assert.ok(workbenchAt > coreAt, 'workbench-core.js must load before workbench.js');
  assert.match(html.slice(coreAt, workbenchAt), /defer/);
  assert.match(html.slice(workbenchAt, workbenchAt + 120), /defer/);
});

test('nav item and page section are wired', () => {
  assert.match(html, /href="#workbench"[^>]*data-page="workbench"/);
  assert.match(workbenchSection, /<h1 id="workbench-title">/);
  assert.match(workbenchSection, /<textarea id="wb-editor"/);
  assert.match(workbenchSection, /id="wb-project"/);
  assert.match(workbenchSection, /id="wb-outline-view"/);
});

test('every element id referenced by workbench.js exists in index.html', () => {
  const start = js.indexOf('const ELEMENT_IDS = [');
  const end = js.indexOf('];', start);
  assert.ok(start >= 0 && end > start);
  const ids = [...js.slice(start, end).matchAll(/"(wb-[a-z0-9-]+)"/g)].map((match) => match[1]);
  assert.ok(ids.length > 50);
  for (const id of ids) {
    assert.ok(html.includes('id="' + id + '"'), 'index.html is missing #' + id);
  }
});

test('IME composition defers editor writes instead of force-overwriting', () => {
  const hooks = loadWorkbenchHooks();
  assert.equal(hooks.editorWriteBlocked(false, true, false), true, 'composing text must not be overwritten');
  assert.equal(hooks.editorWriteBlocked(false, false, true), true, 'adapter composition must also block writes');
  assert.equal(hooks.editorWriteBlocked(true, true, true), false, 'explicit force is the only bypass');
  assert.equal(hooks.chapterApplyDeferred(true, false), true);
  assert.equal(hooks.chapterApplyDeferred(false, true), true);
  assert.equal(hooks.chapterApplyDeferred(false, false), false);
});

test('a restored draft keeps the version it was based on (D-01)', () => {
  const hooks = loadWorkbenchHooks();
  const current = { version_id: 'v2', sha256: 'b'.repeat(64) };
  const stale = hooks.resolveDraftBaseline(
    { exists: true, baseVersionId: 'v1', baseSha: 'a'.repeat(64) },
    current,
  );
  assert.equal(stale.baseVersionId, 'v1');
  assert.equal(stale.baseSha, 'a'.repeat(64));
  const fresh = hooks.resolveDraftBaseline({ exists: false }, current);
  assert.equal(fresh.baseVersionId, 'v2');
  assert.equal(fresh.baseSha, 'b'.repeat(64));
  const unbased = hooks.resolveDraftBaseline({ exists: true, baseVersionId: null, baseSha: null }, { version_id: 'v3', content_sha256: 'c' });
  assert.equal(unbased.baseVersionId, '');
  assert.equal(unbased.baseSha, '');
  assert.equal(unbased.blocked, true, 'a draft without its own base must not fall back to v3');
});

test('Ctrl+S targets the focused editor instead of always saving a chapter (D-05)', () => {
  const hooks = loadWorkbenchHooks();
  const element = (id, tagName, extra) => ({ id, tagName: tagName || 'TEXTAREA', ...(extra || {}) });
  assert.equal(hooks.ctrlSIntentFor(element('wb-editor')), 'save-version');
  assert.equal(hooks.ctrlSIntentFor(element('wb-title', 'INPUT')), 'save-version');
  assert.equal(hooks.ctrlSIntentFor(element('wb-outline-text')), 'save-outline');
  assert.equal(hooks.ctrlSIntentFor(element('wb-lore-text')), 'save-lore');
  assert.equal(hooks.ctrlSIntentFor(element('wb-meta-master')), 'save-meta');
  assert.equal(hooks.ctrlSIntentFor(element('wb-annotation-input')), 'none');
  assert.equal(hooks.ctrlSIntentFor(element('other', 'DIV')), 'save-version');
});

test('annotation POST matches the backend create_annotation contract (D-02)', () => {
  const hooks = loadWorkbenchHooks();
  const body = hooks.annotationPayload(
    { startCp: 3, endCp: 9, text: '选中的正文' },
    '这里更紧张',
    { exists: true, baseVersionId: 'v1', baseSha: 'a'.repeat(64) },
    'v2', 'b'.repeat(64),
  );
  assert.equal(body.instruction, '这里更紧张');
  assert.equal(body.scope, 'selection');
  assert.equal(body.anchor.char_start, 3);
  assert.equal(body.anchor.char_end, 9);
  assert.equal(body.anchor.quote, '选中的正文');
  assert.equal(body.base_version_id, 'v1');
  assert.equal(body.base_content_sha256, 'a'.repeat(64));
  assert.equal(body.note, undefined, 'backend rejects unknown top-level note fields by ignoring them; the contract field is instruction');
});

test('generated ATELIER CSS is byte-identical to fonts + source stylesheets (D-08)', () => {
  assert.equal(generatedAtelierCss(clientSource), expectedAtelierCss(),
    'client.js CSS drift: run python3 -X utf8 scripts/build-client-ui.py');
  for (const name of ['assets/atelier-base.css', 'assets/atelier-native.css']) {
    assert.doesNotMatch(read(name), /\r/, name + ' must be LF-only');
  }
});

test('generated workbench core blocks match the shared kernel byte-for-byte (D-08)', () => {
  const coreText = core.endsWith('\n') ? core : core + '\n';
  assert.equal(generatedWorkbenchCore(clientSource), coreText,
    'client.js workbench core drift: run python3 -X utf8 scripts/build-client-ui.py');
  assert.equal(read('backend/manager/static/workbench-core.js'), coreText,
    'static workbench core drift: run python3 -X utf8 scripts/build-client-ui.py');
});

test('no contenteditable and no hidden mirror div for caret measurement', () => {
  assert.doesNotMatch(js, /contenteditable/i);
  assert.doesNotMatch(workbenchSection, /contenteditable/i);
  assert.doesNotMatch(js, /mirror/i);
  assert.doesNotMatch(css, /mirror/i);
  assert.match(js, /Core\.floatBarPosition\(/);
});

test('UTF-8 stream decoding is delegated to workbench-core', () => {
  assert.match(core, /decoder\.decode\(chunk,\s*\{\s*stream:\s*true\s*\}\)/);
  assert.doesNotMatch(js, /new TextDecoder/);
  assert.doesNotMatch(js, /\.decode\(/);
  assert.match(js, /new Core\.EditorAdapter\(/);
  assert.match(js, /new Core\.UndoStack\(/);
});

test('workbench.js never assigns innerHTML (all API text uses textContent)', () => {
  assert.doesNotMatch(js, /\.innerHTML\b/);
  assert.doesNotMatch(js, /\binsertAdjacentHTML\b/);
  assert.doesNotMatch(js, /\.outerHTML\b/);
  assert.match(js, /\.textContent\s*=/);
});

test('draft and version payloads carry exact optimistic-concurrency fields', () => {
  for (const field of [
    'expected_draft_id', 'expected_draft_epoch', 'expected_draft_revision',
    'submitted_draft_id', 'submitted_draft_epoch', 'submitted_draft_revision',
    'expected_version_id', 'expected_content_sha256', 'restore_title',
  ]) {
    assert.ok(js.includes(field), 'workbench.js must send ' + field);
  }
  assert.match(js, /DRAFT_DEBOUNCE_MS\s*=\s*1500/);
  assert.match(js, /"draft_conflict"/);
  assert.match(js, /"concurrent_modification"/);
  assert.ok(js.includes('保存后继续输入的内容已保留'), 'draft_preserved notice must be present');
  assert.ok(js.includes('零模型费用'), 'quick-check must show the zero model cost label');
});

test('every mutation endpoint used by the UI exists in index.js WRITE_ROUTES', () => {
  const start = indexJs.indexOf('const WRITE_ROUTES = [');
  assert.ok(start >= 0, 'index.js must define WRITE_ROUTES');
  const end = indexJs.indexOf('];', start);
  assert.ok(end > start);
  const routes = new Set(
    [...indexJs.slice(start, end).matchAll(/'([A-Z]+) ([^']+)'/g)].map((match) => match[1] + ' ' + match[2]),
  );

  const used = [
    ['POST', '/api/projects/:identity/chapters'],
    ['PUT', '/api/projects/:identity/chapters/:chapter'],
    ['DELETE', '/api/projects/:identity/chapters/:chapter'],
    ['PUT', '/api/projects/:identity/chapters/:chapter/draft'],
    ['POST', '/api/projects/:identity/chapters/:chapter/quick-check'],
    ['POST', '/api/projects/:identity/chapters/:chapter/annotations'],
    ['POST', '/api/projects/:identity/chapters/:chapter/restore'],
    ['POST', '/api/projects/:identity/chapters/:chapter/split'],
    ['POST', '/api/projects/:identity/chapters/merge-tail'],
    ['POST', '/api/projects/:identity/import-chapters'],
    ['POST', '/api/projects/:identity/trash/:entry/restore'],
    ['PUT', '/api/projects/:identity/outline/files/:filename'],
    ['PUT', '/api/projects/:identity/outline/meta'],
    ['PUT', '/api/projects/:identity/lore/files/:filename'],
  ];
  for (const [method, path] of used) {
    assert.ok(routes.has(method + ' ' + path), 'missing WRITE_ROUTES entry: ' + method + ' ' + path);
  }

  const tokens = [
    '"/chapters"', '"/chapters/"', '"/draft"', '"/quick-check"', '"/restore"',
    '"/split"', '"/chapters/merge-tail"', '"/import-chapters"', '"/trash"',
    '"/outline/files/"', '"/outline/meta"', '"/lore/files/"',
  ];
  for (const token of tokens) assert.ok(js.includes(token), 'workbench.js must call ' + token);
  assert.match(js, /"DELETE"/);
  assert.match(js, /"PUT"/);
  assert.match(js, /X-Novel-Helper/);
});

test('mobile layout collapses to drawers and a fixed bottom selection bar', () => {
  assert.match(css, /@media \(max-width: 760px\)/);
  const mobile = css.slice(css.indexOf('@media (max-width: 760px)'));
  assert.match(mobile, /\.wb-left[\s\S]*?position:\s*fixed/);
  assert.match(mobile, /\.wb-right[\s\S]*?position:\s*fixed/);
  assert.match(mobile, /\.wb-bubble\s*\{[\s\S]*?display:\s*none/);
  assert.match(css, /\.wb-selbar[\s\S]*?position:\s*fixed/);
});

test('workbench has no inline event handlers and new files are LF-only', () => {
  assert.doesNotMatch(html, /\son(?:click|input|change|submit|keydown|keyup|mouseup|pointerup)=/i);
  for (const [name, text] of [['workbench.js', js], ['workbench.css', css]]) {
    assert.doesNotMatch(text, /\r/, name + ' must be LF-only');
    assert.doesNotMatch(text, /[ \t]+$/m, name + ' must not have trailing whitespace');
  }
});

function loadSharedCore() {
  const sandbox = { console, setTimeout, clearTimeout, TextDecoder, AbortController, ReadableStream, Promise };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(core, sandbox, { filename: 'workbench-core.js' });
  return sandbox.WorkbenchCore;
}

test('SSE parser honours retry: and 503 reconnects when retryOnError is enabled (D-10)', async () => {
  const Core = loadSharedCore();
  const parser = new Core.SseParser();
  parser.feed('retry: 2500\n\n');
  assert.equal(parser.retry, 2500, 'server retry field must be parsed');

  let attempts = 0;
  const errors = [];
  const connection = Core.connectEventStream({
    url: '/stream',
    retryDelayMs: 5,
    respectRetryField: false,
    retryOnError: true,
    fetchImpl: async () => {
      attempts += 1;
      if (attempts < 3) return { ok: false, status: 503, body: null };
      return { ok: true, status: 200, body: new ReadableStream({ start(controller) { controller.close(); } }) };
    },
    onError: (error) => errors.push(error),
  });
  await new Promise((resolve) => setTimeout(resolve, 80));
  assert.ok(attempts >= 2, '503 must schedule a reconnect instead of closing forever');
  assert.ok(errors.length >= 1);
  connection.close();
  assert.equal(connection.closed, true);
});

test('761–767px stays on the desktop dock and desktop workbench layout (D-16)', () => {
  const overlapAt = css.indexOf('@media (min-width: 761px) and (max-width: 767px)');
  assert.ok(overlapAt >= 0, 'the 761–767px overlap must be handled explicitly');
  const overlap = css.slice(overlapAt);
  assert.match(overlap, /\.mobile-dock\s*\{[\s\S]*?display:\s*none/);
  assert.match(overlap, /main:not\(\.pair-shell\)\s*\{[\s\S]*?padding-bottom:\s*42px/);
  assert.match(css, /@media \(max-width: 760px\)/, 'workbench mobile breakpoint must end at 760px');
});
