/**
 * Workbench page contract checks.
 *
 * The page itself is exercised through `client-ui.test.mjs`; these are the
 * pure payload builders that must match `chapter_editor.save_draft`,
 * `chapter_editor.save_version` and the restore route. A drift here is a 409
 * in the author's face, so the exact field names are asserted rather than
 * "some body was posted".
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

function loadInternals() {
  let loaded = null;
  const React = {
    Fragment: 'Fragment',
    createElement: (type, props, ...children) => ({ type, props: props || {}, children }),
    createContext: (value) => ({ Provider: () => null, Consumer: () => null, _default: value }),
    useContext: (context) => (context ? context._default : undefined),
    useState: (value) => [typeof value === 'function' ? value() : value, noop],
    useEffect: noop,
    useRef: (value) => ({ current: value }),
    useMemo: (make) => make(),
    useCallback: (fn) => fn,
  };
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
    fetch: async () => ({ ok: true, status: 200, text: async () => '{}' }),
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
  assert.ok(loaded, 'client bundle did not register with the module loader');
  const exported = loaded.factory((name) => (name === 'react' ? React : {}));
  return exported.__internals;
}

const internals = loadInternals();

test('工作台路由挂在创作室下且页面已导出', () => {
  assert.equal(typeof internals.WorkbenchPage, 'function');
  const studio = Array.from(internals.HUBS).find((hub) => hub.id === 'studio');
  assert.ok(studio, 'studio hub missing');
  assert.ok(Array.from(studio.routes).includes('workbench'), 'studio hub does not expose workbench');
  const navIds = Array.from(internals.NAV).flatMap((group) => Array.from(group.items || [])).map((item) => item.id);
  assert.ok(navIds.includes('workbench'), 'NAV missing workbench');
  assert.match(source, /routes: \['chapters', 'workbench', 'outline', 'memory', 'readers'\]/);
});

test('作品选择优先 localStorage，其次当前总览作品', () => {
  const rows = [{ id: 'p1', title: 'A' }, { id: 'p2', title: 'B' }];
  assert.equal(internals.wbPickProject(rows, 'p2').id, 'p2');
  assert.equal(internals.wbPickProject(rows, 'missing').id, 'p1');
  assert.equal(internals.wbPickProject([], 'p2'), null);
});

test('草稿初始态优先草稿内容，但保留服务端草稿身份', () => {
  const bare = internals.wbInitialDocument({
    title: '第一章', content: '正文',
    draft: { exists: false, draft_id: null, draft_epoch: 3, draft_revision: 0 },
  });
  assert.equal(bare.title, '第一章');
  assert.equal(bare.content, '正文');
  assert.deepEqual({ ...bare.identity }, { draft_id: null, draft_epoch: 3, draft_revision: 0 });
  assert.equal(bare.hasDraft, false);

  const withDraft = internals.wbInitialDocument({
    title: '第一章', content: '正文',
    draft: { exists: true, draft_id: 'drf_1', draft_epoch: 2, draft_revision: 4, title: '草稿标题', content: '草稿正文' },
  });
  assert.equal(withDraft.title, '草稿标题');
  assert.equal(withDraft.content, '草稿正文');
  assert.deepEqual({ ...withDraft.identity }, { draft_id: 'drf_1', draft_epoch: 2, draft_revision: 4 });
  assert.equal(withDraft.hasDraft, true);

  const crlf = internals.wbInitialDocument({ title: 't', content: '一\r\n二\r三', draft: { exists: false } });
  assert.equal(crlf.content, '一\n二\n三', '编辑器载入时必须规范为 LF');
});

test('草稿 PUT 携带三重身份与版本基线', () => {
  const body = internals.wbDraftPayload({
    title: '第一章', content: '改稿',
    baseVersionId: 'ver_0001_abcdef12', baseSha256: 'a'.repeat(64),
    draftIdentity: { draft_id: 'drf_1', draft_epoch: 2, draft_revision: 5 },
    sessionId: 'dsh_test', cursor: { start_cp: 2, end_cp: 2 },
  });
  assert.deepEqual(Object.keys(body).sort(), [
    'base_content_sha256', 'base_version_id', 'client_session_id', 'content',
    'cursor', 'expected_draft_epoch', 'expected_draft_id', 'expected_draft_revision', 'title',
  ]);
  assert.equal(body.expected_draft_id, 'drf_1');
  assert.equal(body.expected_draft_epoch, 2);
  assert.equal(body.expected_draft_revision, 5);
  assert.equal(body.base_version_id, 'ver_0001_abcdef12');
  assert.equal(body.base_content_sha256, 'a'.repeat(64));
  assert.equal(body.client_session_id, 'dsh_test');

  const first = internals.wbDraftPayload({ title: 't', content: 'c', draftIdentity: { draft_id: null, draft_epoch: 0, draft_revision: 0 } });
  assert.equal(first.expected_draft_id, null);
  assert.equal(first.expected_draft_epoch, 0);
  assert.equal(first.expected_draft_revision, 0);
});

test('正式版本 PUT 带 expected 版本/哈希与提交的草稿身份', () => {
  const body = internals.wbVersionPayload({
    title: '第一章', content: '定稿',
    expectedVersionId: 'ver_0001_abcdef12', expectedSha: 'a'.repeat(64),
    draftIdentity: { draft_id: 'drf_1', draft_epoch: 2, draft_revision: 5 },
    opId: 'save-test',
  });
  assert.equal(body.expected_version_id, 'ver_0001_abcdef12');
  assert.equal(body.expected_content_sha256, 'a'.repeat(64));
  assert.equal(body.submitted_draft_id, 'drf_1');
  assert.equal(body.submitted_draft_epoch, 2);
  assert.equal(body.submitted_draft_revision, 5);
  assert.equal(body.op_id, 'save-test');
  assert.equal(body.source, 'author_edit');

  const noDraft = internals.wbVersionPayload({ title: 't', content: 'c', expectedSha: 'b'.repeat(64), opId: 'op' });
  assert.equal(noDraft.submitted_draft_id, null, '没有草稿时不能伪造 draft id');
  assert.equal(noDraft.submitted_draft_epoch, null);
  assert.equal(noDraft.submitted_draft_revision, null);
});

test('三方合并直接复用共享内核，冲突不再是静默覆盖', () => {
  const base = '第一行\n第二行\n第三行\n';
  const local = '本地改\n第二行\n第三行\n';
  const remote = '第一行\n第二行\n远端改\n';
  const clean = internals.wbMergeTexts(base, local, remote);
  assert.equal(clean.clean, true);
  assert.match(clean.text, /本地改/);
  assert.match(clean.text, /远端改/);
  assert.equal(clean.conflicts.length, 0);

  const conflicted = internals.wbMergeTexts('同一句话。\n', '作者版本。\n', '服务端版本。\n');
  assert.equal(conflicted.clean, false);
  assert.ok(conflicted.conflicts.length >= 1);
  assert.match(conflicted.text, /<<<<<<< 本地/);
  assert.match(conflicted.text, />>>>>>> 服务端/);
});

test('参考页从大纲中只截取本章段落', () => {
  const outline = '# 卷一\n\n## 第1章 开端\n雨夜，主角登场。\n第二行。\n\n## 第2章 转折\n档案馆。\n';
  assert.equal(internals.wbOutlineExcerpt(outline, 1), '雨夜，主角登场。\n第二行。');
  assert.equal(internals.wbOutlineExcerpt(outline, 2), '档案馆。');
  assert.equal(internals.wbOutlineExcerpt(outline, 9), '');
  assert.equal(internals.wbOutlineExcerpt('', 1), '');
});

test('字数与段落统计按码点/非空行计算', () => {
  assert.equal(internals.wbVisibleWords('一二 三\n四'), 4);
  assert.equal(internals.wbVisibleWords(''), 0);
  assert.equal(internals.wbParagraphCount('一\n\n二\n  \n三'), 3);
  assert.equal(internals.wbParagraphCount(''), 0);
});

test('无草稿 409 会按 epoch 回退重试，不会卡死自动保存 (D-11)', async () => {
  const attempts = [];
  const put = async (body) => {
    attempts.push(body.expected_draft_epoch);
    if (body.expected_draft_epoch !== 4) {
      const error = new Error('draft_conflict');
      error.code = 'draft_conflict';
      error.data = { current_draft: { draft_id: null } };
      throw error;
    }
    assert.equal(body.expected_draft_id, null);
    assert.equal(body.expected_draft_revision, 0);
    return { draft: { draft_id: 'drf_new', draft_epoch: 4, draft_revision: 1 } };
  };
  const result = await internals.wbRetryDraftWithoutActive(
    put,
    { expected_draft_id: 'drf_old', expected_draft_epoch: 2, expected_draft_revision: 7 },
    { rememberedEpoch: 4 },
  );
  assert.deepEqual(attempts, [4], 'remembered epoch is retried first');
  assert.equal(result.draft.draft_id, 'drf_new');
});

test('存在另一份草稿时拒绝 epoch 回退，绝不覆盖 (D-11)', async () => {
  let attempts = 0;
  const put = async () => {
    attempts += 1;
    const error = new Error('draft_conflict');
    error.code = 'draft_conflict';
    error.data = { current_draft: { draft_id: 'drf_live', draft_epoch: 5 } };
    throw error;
  };
  await assert.rejects(
    () => internals.wbRetryDraftWithoutActive(put, { expected_draft_epoch: 1 }, {}),
    (error) => error.code === 'draft_conflict',
  );
  assert.equal(attempts, 1, 'a live draft must surface as a conflict immediately');
});

test('epoch 候选只包含有限的安全回退值 (D-11)', () => {
  assert.equal(internals.wbDraftEpochCandidates(2, null).join(','), '0,1,3,4');
  assert.equal(internals.wbDraftEpochCandidates(0, 3).join(','), '3,1,2');
  assert.equal(internals.wbDraftEpochCandidates('bad', null).join(','), '1,2');
  assert.equal(internals.wbDraftEpochCandidates(64, 70).length <= 5, true);
});

test('服务端返回的 draft_epoch 优先于本地猜测，且缺失键不是 0 (D-11S)', () => {
  assert.equal(internals.wbRecallDraftEpoch('p1', 1), null, 'missing localStorage key must be null, not epoch 0');
  assert.equal(internals.wbDraftEpochCandidates(0, null, 9).join(','), '9,1,2', 'server epoch must be tried first');
  assert.equal(internals.wbDraftEpochCandidates(2, 4, 2).join(','), '4,0,1,3', 'tried epoch is not retried');
  assert.equal(internals.wbDraftEpochCandidates(2, null, 'bad').join(','), '0,1,3,4');
});

test('服务端 epoch=9 时无草稿重试可以直接成功，不会锁死自动保存 (D-11S)', async () => {
  const attempts = [];
  const put = async (body) => {
    attempts.push(body.expected_draft_epoch);
    if (body.expected_draft_epoch !== 9) {
      const error = new Error('draft_conflict');
      error.code = 'draft_conflict';
      error.data = { current_draft: { draft_id: null, draft_epoch: 9 } };
      throw error;
    }
    return { draft: { draft_id: 'drf_9', draft_epoch: 9, draft_revision: 1 } };
  };
  const result = await internals.wbRetryDraftWithoutActive(
    put,
    { expected_draft_id: 'drf_old', expected_draft_epoch: 0, expected_draft_revision: 3 },
    { serverEpoch: 9 },
  );
  assert.deepEqual(attempts, [9]);
  assert.equal(result.draft.draft_id, 'drf_9');
});

test('草稿基线采纳：null base_content 阻断，空串是合法基线 (D-01R/D-01R2)', () => {
  const local = { version_id: 'v1', sha256: 'a'.repeat(64), content: 'v1 正文' };
  const same = internals.wbDraftBaseAdoption(
    { base_version_id: 'v1', base_content_sha256: 'a'.repeat(64) },
    local,
  );
  assert.equal(same.version_id, 'v1');
  assert.equal(same.content, 'v1 正文');
  assert.equal(same.blocked, false);

  const foreign = internals.wbDraftBaseAdoption(
    { base_version_id: 'v2', base_content_sha256: 'b'.repeat(64) },
    local,
  );
  assert.equal(foreign.version_id, 'v2');
  assert.equal(foreign.content, '');
  assert.equal(foreign.blocked, true, 'must not borrow another version body');

  const explicitEmpty = internals.wbDraftBaseAdoption(
    { base_version_id: 'v1', base_content_sha256: 'a'.repeat(64), base_content: '' },
    local,
  );
  assert.equal(explicitEmpty.content, '');
  assert.equal(explicitEmpty.blocked, false, 'empty base is legal');

  const missing = internals.wbDraftBaseAdoption({ base_version_id: 'v1' }, local);
  assert.equal(missing.blocked, true);
});

test('草稿合并只在同一版本基线上自动进行 (D-01R)', () => {
  const base = { version_id: 'v1', sha256: 'a'.repeat(64), content: '' };
  assert.equal(internals.wbMergeBaseCompatible(base, { base_version_id: 'v1', base_content_sha256: 'a'.repeat(64) }), true);
  assert.equal(internals.wbMergeBaseCompatible(base, { base_version_id: 'v2', base_content_sha256: 'b'.repeat(64) }), false);
  assert.equal(internals.wbMergeBaseCompatible(base, { base_version_id: 'v1' }), false);
  assert.equal(internals.wbMergeBaseCompatible(base, {}), false);
});

test('版本保存响应只写给发起保存的章节 (D-C1)', () => {
  const owner = { chapterId: 2, projectId: 'p1' };
  assert.equal(internals.wbSameChapterRef({ id: 2 }, { id: 'p1' }, owner), true);
  assert.equal(internals.wbSameChapterRef({ id: 3 }, { id: 'p1' }, owner), false, 'chapter switched');
  assert.equal(internals.wbSameChapterRef({ id: 2 }, { id: 'p2' }, owner), false, 'project switched');
  assert.equal(internals.wbSameChapterRef(null, { id: 'p1' }, owner), false);
});

test('merge-tail 检查尾章草稿后再确认 (D-09R)', () => {
  assert.equal(internals.wbMergeTailDraftMessage([
    { id: 1, draft: { exists: false } },
    { id: 2, draft: { exists: false } },
  ]), null);
  const warning = internals.wbMergeTailDraftMessage([
    { id: 1, draft: { exists: false } },
    { id: 2, draft: { exists: true } },
  ]);
  assert.match(warning, /第 2 章/);
  assert.match(warning, /未提交草稿/);
});

test('输入法兜底复位会清 composingRef 并结束 adapter 组合 (D-06)', () => {
  const ref = { current: true };
  let ended = 0;
  internals.wbResetComposition(ref, { endComposition: () => { ended += 1; } });
  assert.equal(ref.current, false);
  assert.equal(ended, 1);
  internals.wbResetComposition(ref, null);
  assert.equal(ref.current, false);
});

test('草稿飞行中继续输入会在保存成功后重排 (D-11)', () => {
  assert.equal(internals.wbDraftFollowUp(3, 3), 'clear');
  assert.equal(internals.wbDraftFollowUp(4, 3), 'reschedule');
  assert.equal(internals.wbDraftFollowUp('5', 3), 'reschedule');
});
