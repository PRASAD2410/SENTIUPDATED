import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('./uploadQueue.js', import.meta.url), 'utf8');
const {appendUploadFiles, pendingUploads, runUploadBatch} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const file = (name, size = 100) => ({name, size, lastModified: 123, type: 'text/plain'});

test('Later file selections append and preserve each source type without duplicate selections', () => {
  const first = appendUploadFiles([], [file('fir.pdf'), file('notes.txt')], 'FIR');
  const combined = appendUploadFiles(first, [file('calls.csv'), file('fir.pdf')], 'Call Logs');
  assert.equal(combined.length, 3);
  assert.deepEqual(combined.map(entry => entry.sourceType), ['FIR', 'FIR', 'Call Logs']);
  assert.equal(pendingUploads(combined).length, 3);
});

test('Unsupported and oversized files remain visible with individual errors', () => {
  const queue = appendUploadFiles([], [file('valid.CSV'), file('bad.exe'), file('large.pdf', 10 * 1024 * 1024 + 1), file('empty.txt', 0)]);
  assert.equal(queue.length, 4);
  assert.deepEqual(queue.map(entry => entry.status), ['queued', 'failed', 'failed', 'failed']);
  assert.equal(pendingUploads(queue).length, 1);
  assert.match(queue[1].error, /Unsupported/);
  assert.match(queue[2].error, /10 MB/);
  assert.match(queue[3].error, /empty/);
});

test('The whole batch continues after an error; retry sends only failed files', async () => {
  let queue = appendUploadFiles([], [file('fir.pdf'), file('calls.csv'), file('transactions.xlsx')], 'Other');
  const sent = [];
  const updates = [];
  const update = (id, changes, progress) => {
    queue = queue.map(entry => entry.id === id ? {...entry, ...changes} : entry);
    updates.push(progress);
  };
  const outputs = await runUploadBatch(queue, async entry => {
    sent.push(entry.file.name);
    if (entry.file.name === 'calls.csv') throw new Error('Backend unreachable');
    return {entities: [{id: entry.file.name}], relationships: []};
  }, update);
  assert.deepEqual(sent, ['fir.pdf', 'calls.csv', 'transactions.xlsx']);
  assert.equal(outputs.length, 3);
  assert.equal(queue.length, 3);
  assert.deepEqual(queue.map(entry => entry.status), ['complete', 'failed', 'complete']);
  assert.equal(queue[1].error, 'Backend unreachable');
  assert.equal(updates.at(-1).completed, 3);
  const retried = [];
  await runUploadBatch(queue, async entry => {
    retried.push(entry.file.name);
    return {entities: [], relationships: [{id: 'call'}]};
  }, update);
  assert.deepEqual(retried, ['calls.csv']);
  assert.deepEqual(queue.map(entry => entry.status), ['complete', 'complete', 'complete']);
  assert.equal(pendingUploads(queue).length, 0);
});
