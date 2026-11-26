/**
 * Shared editor-kernel tests.
 *
 * The module is a plain browser script, so it is evaluated in a Node `vm`
 * sandbox exactly as the build injects it into client.js. These tests pin the
 * contracts the DSH panel and the local Web UI both rely on: UTF-8 SSE
 * framing across split chunks, code-point offsets, IME-safe values, serial
 * draft saves, three-way merges and hunk supersession.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const root = new URL('..', import.meta.url);
const sharedSource = readFileSync(new URL('scripts/shared/workbench-core.js', root), 'utf8');

function loadCore() {
  const sandbox = {
    TextDecoder,
    TextEncoder,
    AbortController,
    setTimeout,
    clearTimeout,
    console,
  };
  vm.createContext(sandbox);
  vm.runInContext(sharedSource, sandbox, { filename: 'workbench-core.js' });
  return sandbox.WorkbenchCore;
}

const WorkbenchCore = loadCore();
const encoder = new TextEncoder();

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* Values built inside the vm context have that realm's prototypes, which
   deepStrictEqual treats as different from host literals. Normalise them. */
const plain = (value) => JSON.parse(JSON.stringify(value));

async function waitFor(predicate, timeoutMs = 1000) {
  const started = Date.now();
  while (!predicate()) {
    if (Date.now() - started > timeoutMs) throw new Error('waitFor timed out');
    await delay(5);
  }
}

test('normalizeLf / code-point offsets survive emoji and CRLF', () => {
  const normalized = WorkbenchCore.normalizeLf('第一行\r\n😀 中间\r结尾');
  assert.equal(normalized, '第一行\n😀 中间\n结尾');
  assert.deepEqual(plain(WorkbenchCore.toCodepoints(normalized)), Array.from(normalized));
  assert.equal(WorkbenchCore.toCodepoints(normalized).length, 11);
  assert.equal(normalized.length, 12, 'emoji takes two UTF-16 code units');

  assert.equal(WorkbenchCore.utf16ToCodepoint('😀a中', 2), 1);
  assert.equal(WorkbenchCore.utf16ToCodepoint('😀a中', 3), 2);
  assert.equal(WorkbenchCore.codepointToUtf16('😀a中', 1), 2);
  assert.equal(WorkbenchCore.codepointToUtf16('😀a中', 3), 4);
  assert.equal(WorkbenchCore.sliceCodepoints('😀a中', 1, 3), 'a中');
  assert.equal(WorkbenchCore.sliceCodepoints('😀a中', 0, 1), '😀');
  assert.deepEqual(plain(WorkbenchCore.clampRange('😀a中', -9, 99)), { start: 0, end: 3 });
  assert.deepEqual(plain(WorkbenchCore.clampRange('abc', 2, 1)), { start: 1, end: 2 });
  assert.deepEqual(plain(WorkbenchCore.clampRange('abc', 1.9, 99.7)), { start: 1, end: 3 });
});

test('UndoStack keeps the newest 20 steps and redo is cleared by a new push', () => {
  const stack = new WorkbenchCore.UndoStack();
  for (let index = 0; index < 25; index += 1) {
    stack.push({ label: String(index), before: 'before-' + index, after: 'after-' + index });
  }
  assert.equal(stack.size, 20);
  assert.equal(stack.peek.label, '24');
  assert.equal(stack.undo().label, '24');
  assert.equal(stack.peek.label, '23');

  let undone = 1;
  while (stack.undo()) undone += 1;
  assert.equal(undone, 20);
  assert.equal(stack.canUndo, false);
  assert.equal(stack.canRedo, true);
  assert.equal(stack.undo(), null);

  assert.equal(stack.redo().label, '5');
  assert.equal(stack.canRedo, true);
  let redone = 1;
  while (stack.redo()) redone += 1;
  assert.equal(redone, 20);
  assert.equal(stack.canRedo, false);

  stack.undo();
  stack.push({ label: 'new', before: 'x', after: 'y' });
  assert.equal(stack.canRedo, false);
  stack.clear();
  assert.equal(stack.canUndo, false);
  assert.equal(stack.canRedo, false);
});

test('EditorAdapter never overwrites during IME composition unless forced', () => {
  const editor = new WorkbenchCore.EditorAdapter({ text: '第一行\r\n第二行', title: '第一章' });
  assert.equal(editor.text, '第一行\n第二行');
  assert.equal(editor.title, '第一章');

  editor.beginComposition();
  assert.equal(editor.setValue('异步补丁'), false);
  assert.equal(editor.text, '第一行\n第二行');
  editor.endComposition();
  assert.equal(editor.setValue('异步补丁'), true);
  assert.equal(editor.text, '异步补丁');

  editor.setValue('甲乙丙丁');
  editor.setSelection(1, 3);
  const replacement = editor.replaceRange(1, 3, '😀');
  assert.equal(replacement.before, '甲乙丙丁');
  assert.equal(replacement.after, '甲😀丁');
  assert.equal(replacement.removed, '乙丙');
  assert.equal(replacement.inserted, '😀');
  assert.deepEqual(plain(replacement.range), { startCp: 1, endCp: 3 });
  assert.equal(editor.text, '甲😀丁');
  assert.equal(editor.editSeq, 1);
  assert.deepEqual(plain(editor.selection()), { startCp: 2, endCp: 2 });

  editor.markRevision('drf_1', 3, 5);
  assert.equal(editor.canApplyRemote('drf_1', 3, 6), true);
  assert.equal(editor.canApplyRemote('drf_1', 3, 5), false);
  assert.equal(editor.canApplyRemote('drf_1', 3, 4), false);
  assert.equal(editor.canApplyRemote('drf_2', 3, 6), false);
  assert.equal(editor.canApplyRemote('drf_1', 4, 6), false);
});

test('DraftQueue serializes saves, tracks edits and marks stale results', async () => {
  const queue = new WorkbenchCore.DraftQueue();
  const order = [];
  let releaseFirst;
  const gate = new Promise((resolve) => { releaseFirst = resolve; });
  const first = queue.submit(async () => {
    order.push('first-start');
    await gate;
    order.push('first-end');
    return 'A';
  });
  const second = queue.submit(async () => {
    order.push('second-start');
    await delay(5);
    order.push('second-end');
    return 'B';
  });
  assert.equal(queue.pending, 2);
  queue.noteEdit();
  assert.equal(queue.editSeq, 1);
  releaseFirst();

  const [firstResult, secondResult] = await Promise.all([first, second]);
  assert.deepEqual(order, ['first-start', 'first-end', 'second-start', 'second-end']);
  assert.equal(firstResult.value, 'A');
  assert.equal(firstResult.submittedEditSeq, 0);
  assert.equal(firstResult.stale, true);
  assert.equal(secondResult.stale, true);
  await queue.whenIdle();
  assert.equal(queue.idle, true);
  assert.equal(queue.pending, 0);

  const clean = new WorkbenchCore.DraftQueue();
  const cleanResult = await clean.submit(async () => 'ok');
  assert.equal(cleanResult.stale, false);
  assert.equal(cleanResult.editSeq, 0);
  const objectResult = await clean.submit(async () => ({ revision: 3, draft_id: 'drf_x' }));
  assert.equal(objectResult.revision, 3);
  assert.equal(objectResult.draft_id, 'drf_x');
  assert.equal(objectResult.stale, false);
  assert.equal(objectResult.value.revision, 3);
  assert.equal(clean.submittedEditSeq, 0);
  await assert.rejects(clean.enqueue(async () => { throw new Error('network'); }), /network/);
  const afterFailure = await clean.submit(async () => 'still-running');
  assert.equal(afterFailure.value, 'still-running');
});

test('floatBarPosition clamps fully inside the editor viewport', () => {
  const position = WorkbenchCore.floatBarPosition({
    selectionRect: { left: 1000, top: 5, right: 1100, bottom: 25 },
    editorRect: { left: 100, top: 50, right: 600, bottom: 400 },
    barWidth: 240,
    barHeight: 40,
    margin: 8,
  });
  assert.notEqual(position, null);
  assert.ok(position.left >= 108, 'left respects margin');
  assert.ok(position.left + 240 <= 592, 'right edge stays inside');
  assert.ok(position.top >= 58, 'top respects margin');
  assert.ok(position.top + 40 <= 392, 'bottom edge stays inside');
  assert.equal(position.placement, 'below');

  const above = WorkbenchCore.floatBarPosition({
    selectionRect: { left: 300, top: 200, width: 10, height: 18 },
    editorRect: { left: 100, top: 50, width: 500, height: 350 },
    barWidth: 200,
    barHeight: 36,
  });
  assert.equal(above.placement, 'above');
  assert.ok(above.top + 36 <= 392);
  assert.equal(WorkbenchCore.floatBarPosition({ editorRect: { left: 0, top: 0, right: 1, bottom: 1 } }), null);
});

test('SseParser decodes UTF-8 split across chunks and parses multi-line frames', () => {
  const payload = 'id: 42\nevent: draft\ndata: 中文分片\ndata: 第二行\n\n';
  const bytes = encoder.encode(payload);
  const parser = new WorkbenchCore.SseParser();
  let events = [];
  for (let index = 0; index < bytes.length; index += 2) {
    events = events.concat(parser.feed(bytes.slice(index, index + 2)));
  }
  assert.deepEqual(plain(events), [{ id: '42', event: 'draft', data: '中文分片\n第二行' }]);
  assert.deepEqual(plain(parser.flush()), []);

  const bytewise = new WorkbenchCore.SseParser();
  const chinese = encoder.encode('data: 你好，世界\n\n');
  let byteEvents = [];
  for (let index = 0; index < chinese.length; index += 1) {
    byteEvents = byteEvents.concat(bytewise.feed(chinese.slice(index, index + 1)));
  }
  assert.deepEqual(plain(byteEvents), [{ id: null, event: 'message', data: '你好，世界' }]);
});

test('SseParser handles multiple events, comments, CRLF and idempotent flush', () => {
  const parser = new WorkbenchCore.SseParser();
  const events = parser.feed(encoder.encode(
    ': ping\nid: 7\nevent: update\ndata: 第一行\ndata: 第二行\n\n'
    + 'id: 8\ndata: 第二事件\n\n'
    + ': heart-beat\n\n',
  ));
  assert.deepEqual(plain(events), [
    { id: '7', event: 'update', data: '第一行\n第二行' },
    { id: '8', event: 'message', data: '第二事件' },
  ]);
  assert.deepEqual(plain(parser.flush()), []);

  const crlf = new WorkbenchCore.SseParser();
  assert.deepEqual(plain(crlf.feed(encoder.encode('id: 9\r\ndata: 第一行\r\ndata: 第二行\r\n\r\n'))), [
    { id: '9', event: 'message', data: '第一行\n第二行' },
  ]);

  const tail = new WorkbenchCore.SseParser();
  assert.deepEqual(plain(tail.feed(encoder.encode('data: 尾部'))), []);
  assert.deepEqual(plain(tail.flush()), [{ id: null, event: 'message', data: '尾部' }]);
  assert.deepEqual(plain(tail.flush()), []);
});

test('OrderedEventBuffer drops snapshot-covered frames and dedupes ids and seqs', () => {
  const buffer = new WorkbenchCore.OrderedEventBuffer();
  assert.equal(buffer.push({ seq: 5, event_id: 'e5' }), true);
  assert.equal(buffer.push({ seq: 3, event_id: 'e3' }), true);
  assert.equal(buffer.push({ seq: 4, event_id: 'e3' }), false, 'same event id');
  assert.equal(buffer.push({ seq: 5, event_id: 'e5-again' }), false, 'same seq');
  assert.equal(buffer.push({ seq: 4, event_id: 'e4' }), true);
  assert.equal(buffer.markSnapshot(3), 1);
  assert.equal(buffer.push({ seq: 2, event_id: 'e2' }), false, 'seq <= snapshot');
  assert.deepEqual(plain(buffer.drain().map((event) => event.seq)), [4, 5]);
  assert.deepEqual(plain(buffer.drain()), []);

  const unordered = new WorkbenchCore.OrderedEventBuffer();
  unordered.push({ seq: 2, event_id: 'b' });
  unordered.push({ seq: 1, event_id: 'a' });
  unordered.push({ seq: 3, event_id: 'c' });
  assert.deepEqual(plain(unordered.drain().map((event) => event.event_id)), ['a', 'b', 'c']);
});

test('threeWayTextMerge applies non-overlapping edits from both sides', () => {
  const base = '第一行\n第二行\n第三行\n';
  const merged = WorkbenchCore.threeWayTextMerge(
    base,
    '第一行改\n第二行\n第三行\n',
    '第一行\n第二行\n第三行改\n',
  );
  assert.equal(merged.text, '第一行改\n第二行\n第三行改\n');
  assert.equal(merged.clean, true);
  assert.deepEqual(plain(merged.conflicts), []);

  const sameLine = WorkbenchCore.threeWayTextMerge('abc def ghi', 'ABC def ghi', 'abc def GHI');
  assert.equal(sameLine.text, 'ABC def GHI');
  assert.equal(sameLine.clean, true);

  const insertions = WorkbenchCore.threeWayTextMerge('甲乙丙', '甲X乙丙', '甲乙Y丙');
  assert.equal(insertions.text, '甲X乙Y丙');
  assert.equal(insertions.clean, true);
});

test('threeWayTextMerge keeps both sides on a conflict and dedupes identical edits', () => {
  const conflict = WorkbenchCore.threeWayTextMerge(
    '这是原来的句子。',
    '这是服务端的句子。',
    '这是本地的句子。',
  );
  assert.equal(conflict.clean, false);
  assert.equal(conflict.conflicts.length, 1);
  assert.ok(conflict.text.includes('<<<<<<< 本地'));
  assert.ok(conflict.text.includes('======='));
  assert.ok(conflict.text.includes('>>>>>>> 服务端'));
  assert.ok(conflict.text.includes('这是本地的句子。'));
  assert.ok(conflict.text.includes('这是服务端的句子。'));
  assert.ok(conflict.text.indexOf('这是本地的句子。') < conflict.text.indexOf('这是服务端的句子。'));
  const range = conflict.conflicts[0];
  assert.equal(range.baseStart, 0);
  assert.equal(range.baseEnd, 8);
  assert.equal(range.local, '这是本地的句子。');
  assert.equal(range.server, '这是服务端的句子。');
  assert.ok(range.start >= 0 && range.end <= Array.from(conflict.text).length);

  const identical = WorkbenchCore.threeWayTextMerge('甲\n乙\n', '甲\n丙\n', '甲\n丙\n');
  assert.equal(identical.text, '甲\n丙\n');
  assert.equal(identical.clean, true);
  assert.equal((identical.text.match(/丙/g) || []).length, 1);

  const insertConflict = WorkbenchCore.threeWayTextMerge('甲乙', '甲X乙', '甲Y乙');
  assert.equal(insertConflict.clean, false);
  assert.equal(insertConflict.conflicts.length, 1);
  assert.equal(insertConflict.conflicts[0].type, 'insert_conflict');
  assert.ok(insertConflict.text.includes('X'));
  assert.ok(insertConflict.text.includes('Y'));
});

test('paragraph indexes and annotation anchors clamp for navigation', () => {
  const text = '第一段第一行\n第一段第二行\n\n第二段\n\n第三段';
  assert.equal(WorkbenchCore.paragraphIndexOf(text, 0), 0);
  assert.equal(WorkbenchCore.paragraphIndexOf(text, text.indexOf('第二段')), 2);
  assert.equal(WorkbenchCore.paragraphIndexOf(text, text.indexOf('第三段')), 3);
  assert.equal(WorkbenchCore.paragraphIndexOf(text, 9999), 3);

  const second = text.indexOf('第二段');
  const anchors = WorkbenchCore.annotationAnchors(text, [
    { id: 'ann_b', anchor: { char_start: second, char_end: second + 3 } },
    { id: 'ann_a', startCp: 0, endCp: 2 },
    { id: 'ann_c', startCp: 9999, endCp: 10005 },
  ]);
  assert.deepEqual(plain(anchors.map((anchor) => anchor.id)), ['ann_a', 'ann_b', 'ann_c']);
  assert.deepEqual(plain(anchors[1]), { id: 'ann_b', startCp: second, endCp: second + 3, paragraph: 2 });
  assert.equal(anchors[2].startCp, Array.from(text).length);
  assert.equal(anchors[2].endCp, Array.from(text).length);
  assert.equal(anchors[2].paragraph, 3);
});

test('markSuperseded only supersedes hunks overlapping the chosen range', () => {
  assert.equal(WorkbenchCore.overlapRanges({ start: 1, end: 5 }, { start: 4, end: 8 }), true);
  assert.equal(WorkbenchCore.overlapRanges({ start: 1, end: 5 }, { start: 5, end: 8 }), false);
  assert.equal(WorkbenchCore.overlapRanges([0, 2], [1, 3]), true);

  const hunks = [
    { id: 'a1', start: 0, end: 5, status: 'pending' },
    { id: 'a2', start: 10, end: 15, status: 'pending' },
    { id: 'b1', start: 3, end: 8, status: 'pending' },
    { id: 'b2', start: 20, end: 25, status: 'pending' },
  ];
  const marked = WorkbenchCore.markSuperseded(hunks, [{ id: 'a1', start: 0, end: 5 }]);
  assert.equal(marked.find((hunk) => hunk.id === 'b1').status, 'superseded');
  assert.equal(marked.find((hunk) => hunk.id === 'a2').status, 'pending');
  assert.equal(marked.find((hunk) => hunk.id === 'b2').status, 'pending');
  assert.equal(marked.find((hunk) => hunk.id === 'a1').status, 'pending');
  assert.equal(hunks.find((hunk) => hunk.id === 'b1').status, 'superseded');
});

test('connectEventStream sends Last-Event-ID, streams frames and stops on non-200', async () => {
  let request = null;
  let streamController = null;
  const body = new ReadableStream({
    start(controller) {
      streamController = controller;
      controller.enqueue(encoder.encode('id: 11\ndata: 第一段\n\n'));
    },
  });
  const received = [];
  const failures = [];
  const connection = WorkbenchCore.connectEventStream({
    url: '/api/projects/book/room/stream',
    headers: { 'x-novel-helper-token': 'token' },
    lastEventId: '10',
    fetchImpl: async (url, init) => {
      request = { url, init };
      return { ok: true, status: 200, body };
    },
    onEvent: (event) => received.push(event),
    onError: (error) => failures.push(error),
    retryDelayMs: 20,
  });
  await waitFor(() => received.length === 1);
  assert.equal(request.url, '/api/projects/book/room/stream');
  assert.equal(request.init.headers['x-novel-helper-token'], 'token');
  assert.equal(request.init.headers['Last-Event-ID'], '10');
  assert.deepEqual(plain(received[0]), { id: '11', event: 'message', data: '第一段' });
  assert.equal(failures.length, 0);
  connection.close();
  assert.equal(connection.closed, true);
  if (streamController) {
    try { streamController.close(); } catch (ignored) { /* already cancelled */ }
  }

  let attempts = 0;
  const errors = [];
  const rejected = WorkbenchCore.connectEventStream({
    url: '/stream',
    fetchImpl: async () => {
      attempts += 1;
      return { ok: false, status: 503, body: null };
    },
    onError: (error) => errors.push(error),
    retryDelayMs: 10,
  });
  await waitFor(() => errors.length === 1);
  assert.equal(attempts, 1);
  assert.equal(errors[0].status, 503);
  assert.equal(rejected.closed, true);
});

test('generated workbench copies stay byte-identical', () => {
  const staticCopy = readFileSync(new URL('backend/manager/static/workbench-core.js', root));
  assert.deepEqual(staticCopy, readFileSync(new URL('scripts/shared/workbench-core.js', root)));
  const client = readFileSync(new URL('client.js', root), 'utf8');
  assert.ok(client.includes('// BEGIN GENERATED WORKBENCH CORE'));
  assert.ok(client.includes(sharedSource));
});
