import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { validateTarListing, verifyInstalled, AUTO_UPDATE_ENABLED, updateAvailable } from '../managed-runtime.mjs';

test('accepts a normal package listing', () => {
  const listing = [
    'drwxr-xr-x  0 0 0        0 Nov 14 12:00 package/',
    '-rw-r--r--  0 0 0     1024 Nov 14 12:00 package/runtime-manifest.json',
    '-rw-r--r--  0 0 0     2048 Nov 14 12:00 package/backend/manager/app.py',
  ].join('\n');
  assert.equal(validateTarListing(listing), 3);
  assert.equal(validateTarListing('package/a.txt\npackage/b/c.txt'), 2);
});

test('rejects traversal, absolute paths and backslashes', () => {
  assert.throws(() => validateTarListing('package/../evil.txt'), /路径异常/);
  assert.throws(() => validateTarListing('/etc/passwd'), /路径异常/);
  assert.throws(() => validateTarListing('package\\backend\\app.py'), /路径异常/);
  assert.throws(() => validateTarListing('other/package/app.py'), /路径异常/);
});

test('rejects links and special files in the archive', () => {
  assert.throws(
    () => validateTarListing('lrwxrwxrwx  0 0 0 0 Nov 14 12:00 package/python -> /usr/bin/python'),
    /链接或特殊文件/);
  assert.throws(
    () => validateTarListing('hrw-r--r--  0 0 0 0 Nov 14 12:00 package/hard'),
    /链接或特殊文件/);
  assert.throws(() => validateTarListing(''), /目录为空/);
});

test('auto update stays disabled without a signature', () => {
  assert.equal(AUTO_UPDATE_ENABLED, false);
  const state = updateAvailable();
  assert.equal(state.enabled, false);
  assert.match(state.reason, /签名/);
  assert.match(state.reason, /手动/);
});

test('installed files are compared against the manifest', async () => {
  const root = await mkdtemp(join(tmpdir(), 'chw-install-'));
  try {
    await mkdir(join(root, 'manager'), { recursive: true });
    const body = 'print("ok")\n';
    await writeFile(join(root, 'manager', 'app.py'), body);
    const manifest = { files: { 'backend/manager/app.py': createHash('sha256').update(body).digest('hex') } };
    const good = await verifyInstalled(root, manifest, ['manager']);
    assert.equal(good.checked, 1);
    assert.deepEqual(good.mismatched, []);
    assert.deepEqual(good.missing, []);

    await writeFile(join(root, 'manager', 'app.py'), 'print("old")\n');
    const stale = await verifyInstalled(root, manifest, ['manager']);
    assert.deepEqual(stale.mismatched, ['backend/manager/app.py']);

    await rm(join(root, 'manager', 'app.py'));
    const gone = await verifyInstalled(root, manifest, ['manager']);
    assert.deepEqual(gone.missing, ['backend/manager/app.py']);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
