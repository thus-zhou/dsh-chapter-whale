/* Workbench core — shared by the DSH plugin (client.js) and the local Web UI.
 *
 * Plain browser-compatible ES2018: no imports, no exports, no DOM access.
 * All text offsets are Unicode code points on LF-normalised text unless the
 * function name explicitly says utf16. The build script injects this exact
 * source into client.js and copies it to backend/manager/static/.
 */
const WorkbenchCore = (() => {
  'use strict';

  const UNDO_LIMIT = 20;

  function _string(value) {
    return value === null || value === undefined ? '' : String(value);
  }

  function _integer(value, fallback) {
    const number = Number(value);
    if (!Number.isFinite(number)) return fallback;
    return Math.trunc(number);
  }

  function _clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, value));
  }

  function _cpLength(text) {
    return Array.from(_string(text)).length;
  }

  function normalizeLf(text) {
    return _string(text).replace(/\r\n?/g, '\n');
  }

  function toCodepoints(text) {
    return Array.from(_string(text));
  }

  function utf16ToCodepoint(text, utf16Index) {
    const source = _string(text);
    let index = _integer(utf16Index, 0);
    index = _clamp(index, 0, source.length);
    let codepoints = 0;
    for (let i = 0; i < index; i += 1) {
      const code = source.charCodeAt(i);
      if (code >= 0xd800 && code <= 0xdbff && i + 1 < index) {
        const low = source.charCodeAt(i + 1);
        if (low >= 0xdc00 && low <= 0xdfff) i += 1;
      }
      codepoints += 1;
    }
    return codepoints;
  }

  function codepointToUtf16(text, cpIndex) {
    const source = _string(text);
    const total = _cpLength(source);
    const target = _clamp(_integer(cpIndex, 0), 0, total);
    let codepoints = 0;
    let index = 0;
    while (index < source.length && codepoints < target) {
      const code = source.charCodeAt(index);
      if (code >= 0xd800 && code <= 0xdbff && index + 1 < source.length) {
        const low = source.charCodeAt(index + 1);
        index += low >= 0xdc00 && low <= 0xdfff ? 2 : 1;
      } else {
        index += 1;
      }
      codepoints += 1;
    }
    return index;
  }

  function sliceCodepoints(text, start, end) {
    const source = _string(text);
    const total = _cpLength(source);
    const from = _clamp(_integer(start, 0), 0, total);
    const to = _clamp(_integer(end, from), 0, total);
    return source.slice(codepointToUtf16(source, from), codepointToUtf16(source, to));
  }

  function clampRange(text, start, end) {
    const total = _cpLength(_string(text));
    let from = _clamp(_integer(start, 0), 0, total);
    let to = _clamp(_integer(end, from), 0, total);
    if (to < from) {
      const swap = from;
      from = to;
      to = swap;
    }
    return { start: from, end: to };
  }

  class UndoStack {
    constructor(capacity) {
      const requested = _integer(capacity, UNDO_LIMIT);
      this.capacity = requested > 0 ? requested : UNDO_LIMIT;
      this._undo = [];
      this._redo = [];
    }

    get canUndo() {
      return this._undo.length > 0;
    }

    get canRedo() {
      return this._redo.length > 0;
    }

    get size() {
      return this._undo.length;
    }

    push(entry) {
      if (!entry || typeof entry !== 'object') return null;
      const item = {
        label: entry.label === null || entry.label === undefined ? '' : String(entry.label),
        before: entry.before,
        after: entry.after,
        meta: entry.meta,
      };
      this._undo.push(item);
      if (this._undo.length > this.capacity) this._undo.splice(0, this._undo.length - this.capacity);
      this._redo.length = 0;
      return item;
    }

    undo() {
      if (!this._undo.length) return null;
      const item = this._undo.pop();
      this._redo.push(item);
      return item;
    }

    redo() {
      if (!this._redo.length) return null;
      const item = this._redo.pop();
      this._undo.push(item);
      return item;
    }

    get peek() {
      return this._undo.length ? this._undo[this._undo.length - 1] : null;
    }

    clear() {
      this._undo.length = 0;
      this._redo.length = 0;
    }
  }

  class DraftQueue {
    constructor() {
      this._queue = [];
      this._active = null;
      this._editSeq = 0;
      this._submittedEditSeq = 0;
      this._idleWaiters = [];
    }

    get pending() {
      return this._queue.length + (this._active ? 1 : 0);
    }

    get idle() {
      return !this._active && this._queue.length === 0;
    }

    get editSeq() {
      return this._editSeq;
    }

    get submittedEditSeq() {
      return this._submittedEditSeq;
    }

    noteEdit() {
      this._editSeq += 1;
      return this._editSeq;
    }

    enqueue(fn) {
      return new Promise((resolve, reject) => {
        this._queue.push({ fn: fn, resolve: resolve, reject: reject });
        this._pump();
      });
    }

    submit(fn) {
      const submittedEditSeq = this._editSeq;
      this._submittedEditSeq = submittedEditSeq;
      return this.enqueue(fn).then((value) => {
        const editSeq = this._editSeq;
        const stale = editSeq > submittedEditSeq;
        if (value && typeof value === 'object' && !Array.isArray(value)) {
          const result = Object.assign({}, value);
          result.stale = stale;
          Object.defineProperty(result, 'value', { value: value, enumerable: false });
          Object.defineProperty(result, 'submittedEditSeq', { value: submittedEditSeq, enumerable: false });
          Object.defineProperty(result, 'editSeq', { value: editSeq, enumerable: false });
          return result;
        }
        return { value: value, submittedEditSeq: submittedEditSeq, editSeq: editSeq, stale: stale };
      });
    }

    whenIdle() {
      if (this.idle) return Promise.resolve();
      return new Promise((resolve) => this._idleWaiters.push(resolve));
    }

    _pump() {
      if (this._active) return;
      if (!this._queue.length) {
        this._settleIdle();
        return;
      }
      const task = this._queue.shift();
      this._active = task;
      Promise.resolve()
        .then(() => task.fn())
        .then(
          (value) => task.resolve(value),
          (error) => task.reject(error),
        )
        .then(() => {
          this._active = null;
          if (this._queue.length) this._pump();
          else this._settleIdle();
        });
    }

    _settleIdle() {
      const waiters = this._idleWaiters.splice(0, this._idleWaiters.length);
      for (let i = 0; i < waiters.length; i += 1) waiters[i]();
    }
  }

  class EditorAdapter {
    constructor(options, title) {
      const settings = typeof options === 'string' ? { text: options, title: title } : (options || {});
      this.text = normalizeLf(settings.text || '');
      this.title = settings.title === null || settings.title === undefined ? '' : String(settings.title);
      this.editSeq = 0;
      this.composing = false;
      this._selection = { startCp: 0, endCp: 0 };
      this._revision = null;
    }

    setValue(text, force) {
      if (this.composing && !force) return false;
      this.text = normalizeLf(text);
      const total = _cpLength(this.text);
      this._selection = {
        startCp: _clamp(this._selection.startCp, 0, total),
        endCp: _clamp(this._selection.endCp, 0, total),
      };
      return true;
    }

    beginComposition() {
      this.composing = true;
    }

    endComposition() {
      this.composing = false;
    }

    replaceRange(startCp, endCp, replacement) {
      const total = _cpLength(this.text);
      const range = clampRange(this.text, startCp, endCp);
      const from = _clamp(range.start, 0, total);
      const to = _clamp(range.end, 0, total);
      const beforeText = this.text;
      const removed = sliceCodepoints(this.text, from, to);
      const inserted = normalizeLf(replacement);
      this.text = sliceCodepoints(this.text, 0, from) + inserted + sliceCodepoints(this.text, to, total);
      const caret = from + _cpLength(inserted);
      this._selection = { startCp: caret, endCp: caret };
      this.editSeq += 1;
      return {
        before: beforeText,
        after: this.text,
        removed: removed,
        inserted: inserted,
        range: { startCp: from, endCp: to },
      };
    }

    selection() {
      return { startCp: this._selection.startCp, endCp: this._selection.endCp };
    }

    setSelection(startCp, endCp) {
      const range = clampRange(this.text, startCp, endCp);
      this._selection = { startCp: range.start, endCp: range.end };
      return this.selection();
    }

    markRevision(draftId, epoch, revision) {
      this._revision = {
        draftId: draftId === null || draftId === undefined ? null : String(draftId),
        epoch: epoch === null || epoch === undefined ? null : String(epoch),
        revision: _integer(revision, 0),
      };
      return {
        draftId: this._revision.draftId,
        epoch: this._revision.epoch,
        revision: this._revision.revision,
      };
    }

    canApplyRemote(draftId, epoch, revision) {
      if (!this._revision) return false;
      const remoteDraft = draftId === null || draftId === undefined ? null : String(draftId);
      const remoteEpoch = epoch === null || epoch === undefined ? null : String(epoch);
      if (remoteDraft !== this._revision.draftId) return false;
      if (remoteEpoch !== this._revision.epoch) return false;
      return _integer(revision, 0) > this._revision.revision;
    }
  }

  function _rectValue(rect, key, fallback) {
    const value = Number(rect ? rect[key] : NaN);
    return Number.isFinite(value) ? value : fallback;
  }

  function floatBarPosition(options) {
    const settings = options || {};
    const selectionRect = settings.selectionRect;
    const editorRect = settings.editorRect;
    if (!selectionRect || !editorRect) return null;
    const margin = Number.isFinite(Number(settings.margin)) ? Number(settings.margin) : 8;
    const barWidth = Math.max(0, Number(settings.barWidth) || 0);
    const barHeight = Math.max(0, Number(settings.barHeight) || 0);

    const editorLeft = _rectValue(editorRect, 'left', _rectValue(editorRect, 'x', 0));
    const editorTop = _rectValue(editorRect, 'top', _rectValue(editorRect, 'y', 0));
    const editorRight = _rectValue(editorRect, 'right', editorLeft + _rectValue(editorRect, 'width', 0));
    const editorBottom = _rectValue(editorRect, 'bottom', editorTop + _rectValue(editorRect, 'height', 0));
    const viewport = settings.viewport || null;
    const viewportTop = viewport ? _rectValue(viewport, 'top', 0) : null;
    const viewportBottom = viewport ? _rectValue(viewport, 'bottom', 0) : null;
    const clipTop = viewportTop === null ? editorTop : Math.max(editorTop, viewportTop);
    const clipBottom = viewportBottom === null ? editorBottom : Math.min(editorBottom, viewportBottom);

    const selectionLeft = _rectValue(selectionRect, 'left', _rectValue(selectionRect, 'x', editorLeft));
    const selectionTop = _rectValue(selectionRect, 'top', _rectValue(selectionRect, 'y', editorTop));
    const selectionRight = _rectValue(selectionRect, 'right', selectionLeft + _rectValue(selectionRect, 'width', 0));
    const selectionBottom = _rectValue(selectionRect, 'bottom', selectionTop + _rectValue(selectionRect, 'height', 0));

    const minimumLeft = editorLeft + margin;
    const maximumLeft = editorRight - margin - barWidth;
    let left = selectionLeft + (selectionRight - selectionLeft) / 2 - barWidth / 2;
    left = maximumLeft >= minimumLeft ? _clamp(left, minimumLeft, maximumLeft) : minimumLeft;

    const minimumTop = clipTop + margin;
    const maximumTop = clipBottom - margin - barHeight;
    const above = selectionTop - margin - barHeight;
    const below = selectionBottom + margin;
    let placement = above >= minimumTop ? 'above' : 'below';
    let top = placement === 'above' ? above : below;
    top = maximumTop >= minimumTop ? _clamp(top, minimumTop, maximumTop) : minimumTop;

    return { left: left, top: top, placement: placement };
  }

  class SseParser {
    constructor() {
      this.decoder = new TextDecoder('utf-8');
      this._buffer = '';
      this._data = null;
      this._event = '';
      this._lastEventId = null;
      this._retry = null;
    }

    get lastEventId() {
      return this._lastEventId;
    }

    get retry() {
      return this._retry;
    }

    feed(chunk) {
      const out = [];
      const text = typeof chunk === 'string' ? chunk : this.decoder.decode(chunk, { stream: true });
      this._ingest(text, out, false);
      return out;
    }

    flush() {
      const out = [];
      const text = this.decoder.decode();
      this._ingest(text, out, true);
      return out;
    }

    _ingest(text, out, final) {
      this._buffer += text;
      while (true) {
        const match = /(?:\r\n|\n|\r)/.exec(this._buffer);
        if (!match) break;
        const index = match.index;
        if (!final && this._buffer.charAt(index) === '\r' && index === this._buffer.length - 1) break;
        let skip = 1;
        if (this._buffer.charAt(index) === '\r' && this._buffer.charAt(index + 1) === '\n') skip = 2;
        const line = this._buffer.slice(0, index);
        this._buffer = this._buffer.slice(index + skip);
        this._handleLine(line, out);
      }
      if (final && this._buffer.length) {
        const line = this._buffer;
        this._buffer = '';
        this._handleLine(line, out);
      }
      if (final) this._dispatch(out);
    }

    _handleLine(line, out) {
      if (line === '') {
        this._dispatch(out);
        return;
      }
      if (line.charAt(0) === ':') return;
      let field = line;
      let value = '';
      const colon = line.indexOf(':');
      if (colon >= 0) {
        field = line.slice(0, colon);
        value = line.slice(colon + 1);
        if (value.charAt(0) === ' ') value = value.slice(1);
      }
      if (field === 'data') {
        this._data = (this._data === null ? '' : this._data) + value + '\n';
      } else if (field === 'event') {
        this._event = value;
      } else if (field === 'id') {
        if (value.indexOf('\u0000') < 0) this._lastEventId = value;
      } else if (field === 'retry') {
        const delay = Number(value);
        if (Number.isFinite(delay) && delay >= 0) this._retry = delay;
      }
    }

    _dispatch(out) {
      if (this._data !== null) {
        const data = this._data.slice(0, -1);
        out.push({ id: this._lastEventId, event: this._event || 'message', data: data });
      }
      this._data = null;
      this._event = '';
    }
  }

  function _sequenceNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  class OrderedEventBuffer {
    constructor() {
      this._events = [];
      this._snapshot = null;
      this._ids = new Set();
      this._seqs = new Set();
    }

    push(event) {
      if (!event || typeof event !== 'object') return false;
      const seq = _sequenceNumber(event.seq);
      if (this._snapshot !== null && seq !== null && seq <= this._snapshot) return false;
      const idValue = event.event_id !== null && event.event_id !== undefined
        ? event.event_id
        : event.id;
      const idKey = idValue === null || idValue === undefined ? null : 'id:' + String(idValue);
      // A resync marker is a control frame, not a duplicate data frame: it must
      // reach the consumer even when it reuses the last delivered seq
      // (B-14R-2).  Data frames keep both dedupe checks.
      if (event.kind !== 'resync_required') {
        if (idKey !== null && this._ids.has(idKey)) return false;
        if (seq !== null && this._seqs.has(seq)) return false;
      }
      if (idKey !== null) this._ids.add(idKey);
      if (seq !== null) this._seqs.add(seq);
      this._events.push({ event: event, seq: seq, order: this._events.length });
      return true;
    }

    markSnapshot(seq) {
      const number = _sequenceNumber(seq);
      this._snapshot = number;
      if (number === null) return 0;
      let dropped = 0;
      const kept = [];
      for (let i = 0; i < this._events.length; i += 1) {
        const row = this._events[i];
        if (row.seq !== null && row.seq <= number) dropped += 1;
        else kept.push(row);
      }
      this._events = kept;
      return dropped;
    }

    drain() {
      const rows = this._events.slice(0);
      rows.sort((left, right) => {
        if (left.seq === null && right.seq === null) return left.order - right.order;
        if (left.seq === null) return 1;
        if (right.seq === null) return -1;
        return left.seq - right.seq || left.order - right.order;
      });
      this._events = [];
      return rows.map((row) => row.event);
    }
  }

  function _commonPrefixLength(a, b) {
    const limit = Math.min(a.length, b.length);
    let index = 0;
    while (index < limit && a[index] === b[index]) index += 1;
    return index;
  }

  function _myersOperations(a, b) {
    const n = a.length;
    const m = b.length;
    const maximum = n + m;
    const limit = Math.min(maximum, 1200);
    const frontier = new Map();
    frontier.set(1, 0);
    const trace = [];
    let found = -1;
    for (let d = 0; d <= limit; d += 1) {
      trace.push(new Map(frontier));
      for (let k = -d; k <= d; k += 2) {
        const down = frontier.get(k + 1);
        const right = frontier.get(k - 1);
        let x;
        if (k === -d || (k !== d && (right === undefined ? -Infinity : right) < (down === undefined ? -Infinity : down))) {
          x = down === undefined ? 0 : down;
        } else {
          x = (right === undefined ? 0 : right) + 1;
        }
        let y = x - k;
        while (x < n && y < m && a[x] === b[y]) {
          x += 1;
          y += 1;
        }
        frontier.set(k, x);
        if (x >= n && y >= m) {
          found = d;
          break;
        }
      }
      if (found >= 0) break;
    }
    if (found < 0) return null;

    const operations = [];
    let x = n;
    let y = m;
    for (let d = found; d > 0; d -= 1) {
      const previous = trace[d];
      const k = x - y;
      const left = previous.get(k - 1);
      const right = previous.get(k + 1);
      let previousK;
      if (k === -d || (k !== d && (left === undefined ? -Infinity : left) < (right === undefined ? -Infinity : right))) {
        previousK = k + 1;
      } else {
        previousK = k - 1;
      }
      const previousX = previous.get(previousK);
      const startX = previousX === undefined ? 0 : previousX;
      const startY = startX - previousK;
      while (x > startX && y > startY) {
        operations.push({ type: 'equal', text: a[x - 1] });
        x -= 1;
        y -= 1;
      }
      if (x === startX) {
        operations.push({ type: 'insert', text: b[y - 1] });
        y -= 1;
      } else {
        operations.push({ type: 'delete', text: a[x - 1] });
        x -= 1;
      }
    }
    while (x > 0 && y > 0) {
      operations.push({ type: 'equal', text: a[x - 1] });
      x -= 1;
      y -= 1;
    }
    while (x > 0) {
      operations.push({ type: 'delete', text: a[x - 1] });
      x -= 1;
    }
    while (y > 0) {
      operations.push({ type: 'insert', text: b[y - 1] });
      y -= 1;
    }
    operations.reverse();
    return operations;
  }

  function _diffChanges(baseText, targetText) {
    const base = Array.from(baseText);
    const target = Array.from(targetText);
    const prefix = _commonPrefixLength(base, target);
    let suffix = 0;
    while (
      suffix < base.length - prefix
      && suffix < target.length - prefix
      && base[base.length - 1 - suffix] === target[target.length - 1 - suffix]
    ) {
      suffix += 1;
    }
    const baseMiddle = base.slice(prefix, base.length - suffix);
    const targetMiddle = target.slice(prefix, target.length - suffix);
    if (!baseMiddle.length && !targetMiddle.length) return [];
    if (!baseMiddle.length || !targetMiddle.length) {
      return [{
        baseStart: prefix,
        baseEnd: prefix + baseMiddle.length,
        text: targetMiddle.join(''),
      }];
    }
    const operations = _myersOperations(baseMiddle, targetMiddle);
    if (!operations) {
      return [{
        baseStart: prefix,
        baseEnd: prefix + baseMiddle.length,
        text: targetMiddle.join(''),
      }];
    }
    const changes = [];
    let basePosition = prefix;
    let pending = null;
    for (let i = 0; i < operations.length; i += 1) {
      const operation = operations[i];
      if (operation.type === 'equal') {
        if (pending) {
          changes.push(pending);
          pending = null;
        }
        basePosition += 1;
      } else if (operation.type === 'delete') {
        if (!pending) pending = { baseStart: basePosition, baseEnd: basePosition, text: '' };
        basePosition += 1;
        pending.baseEnd = basePosition;
      } else {
        if (!pending) pending = { baseStart: basePosition, baseEnd: basePosition, text: '' };
        pending.text += operation.text;
      }
    }
    if (pending) changes.push(pending);
    return changes;
  }

  function _rangesOverlap(firstStart, firstEnd, secondStart, secondEnd) {
    if (firstStart === firstEnd && secondStart === secondEnd) return firstStart === secondStart;
    if (firstStart === firstEnd) return firstStart > secondStart && firstStart < secondEnd;
    if (secondStart === secondEnd) return secondStart > firstStart && secondStart < firstEnd;
    return firstStart < secondEnd && secondStart < firstEnd;
  }

  function _rangeOf(value) {
    if (Array.isArray(value)) {
      const start = _integer(value[0], 0);
      const end = _integer(value[1], start);
      return end < start ? { start: end, end: start } : { start: start, end: end };
    }
    const object = value || {};
    let start = object.start;
    if (start === undefined || start === null) start = object.startCp;
    if (start === undefined || start === null) start = object.char_start;
    let end = object.end;
    if (end === undefined || end === null) end = object.endCp;
    if (end === undefined || end === null) end = object.char_end;
    const from = _integer(start, 0);
    const to = _integer(end, from);
    return to < from ? { start: to, end: from } : { start: from, end: to };
  }

  function overlapRanges(first, second) {
    const a = _rangeOf(first);
    const b = _rangeOf(second);
    return _rangesOverlap(a.start, a.end, b.start, b.end);
  }

  function _applyGroup(base, changes, start, end) {
    let text = '';
    let position = start;
    const sorted = changes.slice(0).sort((left, right) => left.baseStart - right.baseStart || left.baseEnd - right.baseEnd);
    for (let i = 0; i < sorted.length; i += 1) {
      const change = sorted[i];
      const from = _clamp(change.baseStart, start, end);
      const to = _clamp(change.baseEnd, start, end);
      if (from > position) text += base.slice(position, from).join('');
      text += change.text;
      if (to > position) position = to;
    }
    if (position < end) text += base.slice(position, end).join('');
    return text;
  }

  function threeWayTextMerge(baseValue, serverValue, localValue) {
    const baseText = normalizeLf(baseValue);
    const serverText = normalizeLf(serverValue);
    const localText = normalizeLf(localValue);
    if (serverText === localText) return { text: serverText, conflicts: [], clean: true };
    if (baseText === serverText) return { text: localText, conflicts: [], clean: true };
    if (baseText === localText) return { text: serverText, conflicts: [], clean: true };

    const base = Array.from(baseText);
    const serverChanges = _diffChanges(baseText, serverText);
    const localChanges = _diffChanges(baseText, localText);
    const all = [];
    for (let i = 0; i < serverChanges.length; i += 1) {
      const change = serverChanges[i];
      all.push({ side: 'server', baseStart: change.baseStart, baseEnd: change.baseEnd, text: change.text });
    }
    for (let i = 0; i < localChanges.length; i += 1) {
      const change = localChanges[i];
      all.push({ side: 'local', baseStart: change.baseStart, baseEnd: change.baseEnd, text: change.text });
    }
    all.sort((left, right) => (
      left.baseStart - right.baseStart
      || left.baseEnd - right.baseEnd
      || (left.side === right.side ? 0 : left.side === 'server' ? -1 : 1)
    ));

    const used = new Array(all.length).fill(false);
    let cursor = 0;
    const groups = [];

    while (true) {
      while (cursor < all.length && used[cursor]) cursor += 1;
      if (cursor >= all.length) break;
      const first = all[cursor];
      const group = [first];
      used[cursor] = true;
      let groupStart = first.baseStart;
      let groupEnd = first.baseEnd;
      let expanded = true;
      while (expanded) {
        expanded = false;
        for (let index = 0; index < all.length; index += 1) {
          if (used[index]) continue;
          const candidate = all[index];
          if (candidate.baseEnd < groupStart || candidate.baseStart > groupEnd) continue;
          let crosses = false;
          for (let memberIndex = 0; memberIndex < group.length; memberIndex += 1) {
            const member = group[memberIndex];
            if (member.side !== candidate.side && _rangesOverlap(
              member.baseStart, member.baseEnd, candidate.baseStart, candidate.baseEnd,
            )) {
              crosses = true;
              break;
            }
          }
          if (!crosses) continue;
          used[index] = true;
          group.push(candidate);
          groupStart = Math.min(groupStart, candidate.baseStart);
          groupEnd = Math.max(groupEnd, candidate.baseEnd);
          expanded = true;
        }
      }
      groups.push({ start: groupStart, end: groupEnd, changes: group });
    }

    function evaluate(group) {
      const serverChanges = group.changes.filter((change) => change.side === 'server');
      const localChanges = group.changes.filter((change) => change.side === 'local');
      group.serverSide = _applyGroup(base, serverChanges, group.start, group.end);
      group.localSide = _applyGroup(base, localChanges, group.start, group.end);
      group.baseSide = base.slice(group.start, group.end).join('');
      group.conflict = group.serverSide !== group.localSide
        && group.serverSide !== group.baseSide
        && group.localSide !== group.baseSide;
      let insertConflict = group.changes.length > 0;
      let insertPosition = -1;
      for (let i = 0; i < group.changes.length; i += 1) {
        const change = group.changes[i];
        if (change.baseStart !== change.baseEnd) {
          insertConflict = false;
          break;
        }
        if (insertPosition < 0) insertPosition = change.baseStart;
        else if (insertPosition !== change.baseStart) {
          insertConflict = false;
          break;
        }
      }
      group.insertConflict = insertConflict;
    }

    for (let i = 0; i < groups.length; i += 1) evaluate(groups[i]);

    /* Character-level diffs can split one replaced phrase into adjacent
       fragments. Keep a single conflict block per touched run instead of
       scattering markup through the sentence. */
    const mergedGroups = [];
    for (let i = 0; i < groups.length; i += 1) {
      const group = groups[i];
      const previous = mergedGroups.length ? mergedGroups[mergedGroups.length - 1] : null;
      if (previous && previous.conflict && group.conflict && group.start >= previous.end) {
        const gap = base.slice(previous.end, group.start).join('');
        if (group.start - previous.end <= 24 && gap.indexOf('\n') < 0) {
          previous.end = group.end;
          previous.changes = previous.changes.concat(group.changes);
          evaluate(previous);
          continue;
        }
      }
      mergedGroups.push(group);
    }

    /* Conflict markers follow whole lines, like a normal three-way merge, so
       the local block contains the author's complete sentence instead of a
       fragment glued to marker text. Clean edits on the same line are folded
       into the conflict region for both sides. */
    const regions = [];
    for (let i = 0; i < mergedGroups.length; i += 1) {
      const group = mergedGroups[i];
      if (!group.conflict) continue;
      let start = group.start;
      while (start > 0 && base[start - 1] !== '\n') start -= 1;
      let end = group.end;
      while (end < base.length && base[end] !== '\n') end += 1;
      if (end < base.length && base[end] === '\n') end += 1;
      regions.push({ start: start, end: end, changes: group.changes.slice(0), conflict: true });
    }
    regions.sort((left, right) => left.start - right.start || left.end - right.end);
    const mergedRegions = [];
    for (let i = 0; i < regions.length; i += 1) {
      const region = regions[i];
      const previous = mergedRegions.length ? mergedRegions[mergedRegions.length - 1] : null;
      if (previous && region.start <= previous.end) {
        previous.end = Math.max(previous.end, region.end);
        previous.changes = previous.changes.concat(region.changes);
      } else {
        mergedRegions.push(region);
      }
    }

    const renderGroups = [];
    for (let i = 0; i < mergedGroups.length; i += 1) {
      const group = mergedGroups[i];
      if (group.conflict) continue;
      let absorbed = false;
      for (let r = 0; r < mergedRegions.length; r += 1) {
        const region = mergedRegions[r];
        if (group.start >= region.start && group.end <= region.end) {
          region.changes = region.changes.concat(group.changes);
          absorbed = true;
          break;
        }
      }
      if (!absorbed) renderGroups.push(group);
    }
    for (let r = 0; r < mergedRegions.length; r += 1) {
      evaluate(mergedRegions[r]);
      renderGroups.push(mergedRegions[r]);
    }
    renderGroups.sort((left, right) => left.start - right.start || left.end - right.end);

    let text = '';
    let textLength = 0;
    let basePosition = 0;
    const conflicts = [];

    function append(piece) {
      text += piece;
      textLength += _cpLength(piece);
    }

    for (let i = 0; i < renderGroups.length; i += 1) {
      const group = renderGroups[i];
      if (group.end < basePosition) continue;
      if (group.start > basePosition) append(base.slice(basePosition, group.start).join(''));

      if (group.serverSide === group.localSide) {
        append(group.serverSide);
      } else if (group.serverSide === group.baseSide) {
        append(group.localSide);
      } else if (group.localSide === group.baseSide) {
        append(group.serverSide);
      } else {
        const conflictStart = textLength;
        append('<<<<<<< 本地\n');
        append(group.localSide);
        if (!group.localSide.endsWith('\n')) append('\n');
        append('=======\n');
        append(group.serverSide);
        if (!group.serverSide.endsWith('\n')) append('\n');
        append('>>>>>>> 服务端\n');
        conflicts.push({
          start: conflictStart,
          end: textLength,
          baseStart: group.start,
          baseEnd: group.end,
          type: group.insertConflict ? 'insert_conflict' : 'content_conflict',
          local: group.localSide,
          server: group.serverSide,
        });
      }
      basePosition = Math.max(basePosition, group.end);
    }
    if (basePosition < base.length) append(base.slice(basePosition).join(''));

    return { text: text, conflicts: conflicts, clean: conflicts.length === 0 };
  }

  function _isBlankLine(codepoints, start, end) {
    for (let i = start; i < end; i += 1) {
      if (!/\s/.test(codepoints[i])) return false;
    }
    return true;
  }

  function paragraphIndexOf(text, cpOffset) {
    const codepoints = Array.from(normalizeLf(text));
    const total = codepoints.length;
    const offset = _clamp(_integer(cpOffset, 0), 0, total);
    let paragraph = -1;
    let lineStart = 0;
    for (let index = 0; index <= total; index += 1) {
      if (index !== total && codepoints[index] !== '\n') continue;
      const blank = _isBlankLine(codepoints, lineStart, index);
      if (!blank) paragraph += 1;
      if (offset >= lineStart && offset <= index) return paragraph < 0 ? 0 : paragraph;
      lineStart = index + 1;
    }
    return paragraph < 0 ? 0 : paragraph;
  }

  function annotationAnchors(text, annotations) {
    const source = normalizeLf(text);
    const rows = Array.isArray(annotations) ? annotations : [];
    const result = [];
    for (let i = 0; i < rows.length; i += 1) {
      const row = rows[i] || {};
      const anchor = row.anchor && typeof row.anchor === 'object' ? row.anchor : row;
      let start = anchor.startCp;
      if (start === undefined || start === null) start = anchor.char_start;
      if (start === undefined || start === null) start = anchor.start;
      let end = anchor.endCp;
      if (end === undefined || end === null) end = anchor.char_end;
      if (end === undefined || end === null) end = anchor.end;
      const range = clampRange(source, start === undefined || start === null ? 0 : start, end === undefined || end === null ? start : end);
      result.push({
        id: row.id === undefined || row.id === null ? anchor.id : row.id,
        startCp: range.start,
        endCp: range.end,
        paragraph: paragraphIndexOf(source, range.start),
      });
    }
    result.sort((left, right) => left.startCp - right.startCp || left.endCp - right.endCp);
    return result;
  }

  function markSuperseded(hunks, chosen) {
    const list = Array.isArray(hunks) ? hunks : [];
    const picks = (Array.isArray(chosen) ? chosen : []).map((item) => ({
      id: item && item.id,
      range: _rangeOf(item),
    }));
    const chosenIds = new Set(picks.map((item) => item.id));
    for (let index = 0; index < list.length; index += 1) {
      const hunk = list[index];
      if (chosenIds.has(hunk.id)) continue;
      const range = _rangeOf(hunk);
      let overlaps = false;
      for (let pickIndex = 0; pickIndex < picks.length; pickIndex += 1) {
        if (_rangesOverlap(range.start, range.end, picks[pickIndex].range.start, picks[pickIndex].range.end)) {
          overlaps = true;
          break;
        }
      }
      hunk.status = overlaps ? 'superseded' : 'pending';
    }
    return list;
  }

  function _hasHeader(headers, name) {
    const wanted = String(name).toLowerCase();
    const keys = Object.keys(headers);
    for (let i = 0; i < keys.length; i += 1) {
      if (keys[i].toLowerCase() === wanted) return true;
    }
    return false;
  }

  function connectEventStream(options) {
    const settings = options || {};
    const fetchImpl = settings.fetchImpl || (typeof fetch === 'function' ? fetch : null);
    if (!fetchImpl) throw new Error('connectEventStream requires fetchImpl or global fetch');
    const onEvent = typeof settings.onEvent === 'function' ? settings.onEvent : function () {};
    const onError = typeof settings.onError === 'function' ? settings.onError : function () {};
    const baseDelay = Math.max(0, _integer(settings.retryDelayMs, 1000));
    const maximumDelay = Math.max(baseDelay, _integer(settings.maxRetryDelayMs, 15000));
    const retryOnError = settings.retryOnError === true;
    const respectRetryField = settings.respectRetryField !== false;
    const externalSignal = settings.signal || null;
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    let closed = externalSignal ? Boolean(externalSignal.aborted) : false;
    let timer = null;
    let reader = null;
    let retryDelay = baseDelay;
    let serverRetry = null;
    let lastEventId = settings.lastEventId === undefined || settings.lastEventId === null ? null : String(settings.lastEventId);

    function report(error) {
      try {
        onError(error);
      } catch (ignored) {
        /* consumer error handlers must not kill the stream loop */
      }
    }

    function emit(event) {
      if (event && event.id !== null && event.id !== undefined) lastEventId = event.id;
      try {
        onEvent(event);
      } catch (ignored) {
        /* consumer error handlers must not kill the stream loop */
      }
    }

    function schedule() {
      if (closed) return;
      const wait = serverRetry === null ? retryDelay : serverRetry;
      retryDelay = Math.min(retryDelay * 2, maximumDelay);
      timer = setTimeout(run, wait);
    }

    async function run() {
      timer = null;
      if (closed) return;
      const parser = new SseParser();
      const headers = Object.assign({}, settings.headers || {});
      if (lastEventId !== null && !_hasHeader(headers, 'Last-Event-ID')) headers['Last-Event-ID'] = lastEventId;
      if (!_hasHeader(headers, 'Accept')) headers.Accept = 'text/event-stream';
      let response;
      try {
        response = await fetchImpl(settings.url, {
          method: 'GET',
          headers: headers,
          signal: controller ? controller.signal : undefined,
          cache: 'no-store',
        });
      } catch (error) {
        if (closed) return;
        report(error);
        schedule();
        return;
      }
      if (closed) return;
      const status = response ? Number(response.status) : 0;
      const ok = Boolean(response) && (
        response.ok === true
        || (response.ok === undefined && status >= 200 && status < 300)
      );
      if (!ok) {
        const error = new Error('Event stream request failed with status ' + status);
        error.status = status;
        report(error);
        /* 401/403 cannot be repaired by retrying; 429/5xx and gateway
           timeouts are transient and must reconnect instead of dying. */
        if (retryOnError && status !== 401 && status !== 403 && status !== 410) {
          schedule();
          return;
        }
        close();
        return;
      }
      retryDelay = baseDelay;
      try {
        if (!response.body || typeof response.body.getReader !== 'function') {
          throw new Error('Event stream response has no readable body');
        }
        reader = response.body.getReader();
        while (!closed) {
          const step = await reader.read();
          if (step.done) break;
          const events = parser.feed(step.value);
          for (let i = 0; i < events.length; i += 1) emit(events[i]);
          if (parser.lastEventId !== null) lastEventId = parser.lastEventId;
          if (respectRetryField && parser.retry !== null) {
            serverRetry = Math.min(Math.max(0, parser.retry), maximumDelay);
          }
        }
        if (!closed) {
          const tail = parser.flush();
          for (let i = 0; i < tail.length; i += 1) emit(tail[i]);
          if (parser.lastEventId !== null) lastEventId = parser.lastEventId;
          if (respectRetryField && parser.retry !== null) {
            serverRetry = Math.min(Math.max(0, parser.retry), maximumDelay);
          }
        }
      } catch (error) {
        if (!closed) report(error);
      } finally {
        reader = null;
      }
      if (!closed) schedule();
    }

    function close() {
      if (closed) return;
      closed = true;
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      if (externalSignal && typeof externalSignal.removeEventListener === 'function') {
        externalSignal.removeEventListener('abort', close);
      }
      if (controller) controller.abort();
      if (reader) {
        try {
          reader.cancel();
        } catch (ignored) {
          /* a reader already closed by the transport is fine */
        }
      }
    }

    if (externalSignal && typeof externalSignal.addEventListener === 'function' && !closed) {
      externalSignal.addEventListener('abort', close);
    }
    if (!closed) Promise.resolve().then(run);

    return {
      close: close,
      get closed() {
        return closed;
      },
      get lastEventId() {
        return lastEventId;
      },
    };
  }

  return {
    UNDO_LIMIT: UNDO_LIMIT,
    normalizeLf: normalizeLf,
    toCodepoints: toCodepoints,
    utf16ToCodepoint: utf16ToCodepoint,
    codepointToUtf16: codepointToUtf16,
    sliceCodepoints: sliceCodepoints,
    clampRange: clampRange,
    UndoStack: UndoStack,
    DraftQueue: DraftQueue,
    EditorAdapter: EditorAdapter,
    floatBarPosition: floatBarPosition,
    SseParser: SseParser,
    OrderedEventBuffer: OrderedEventBuffer,
    threeWayTextMerge: threeWayTextMerge,
    paragraphIndexOf: paragraphIndexOf,
    annotationAnchors: annotationAnchors,
    overlapRanges: overlapRanges,
    markSuperseded: markSuperseded,
    connectEventStream: connectEventStream,
  };
})();
if (typeof globalThis !== 'undefined') globalThis.WorkbenchCore = WorkbenchCore;
