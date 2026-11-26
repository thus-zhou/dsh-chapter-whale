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

test('IME composition is guarded and .value is not overwritten mid-composition', () => {
  assert.match(js, /"compositionstart"/);
  assert.match(js, /"compositionend"/);
  assert.match(js, /state\.composing\s*=\s*true/);
  assert.match(js, /state\.composing\s*=\s*false/);
  assert.match(js, /state\.composing[^\n]*return false/);
  assert.match(js, /state\.adapter\.beginComposition\(\)/);
  assert.match(js, /state\.adapter\.endComposition\(\)/);
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
  assert.match(css, /@media \(max-width: 767px\)/);
  const mobile = css.slice(css.indexOf('@media (max-width: 767px)'));
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
