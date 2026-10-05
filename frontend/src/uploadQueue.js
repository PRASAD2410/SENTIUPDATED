export const SOURCE_TYPES = ['FIR', 'Transaction Records', 'Call Logs', 'Other'];
export const FILE_ACCEPT = '.pdf,.docx,.csv,.tsv,.xlsx,.txt';
const MAX_FILE_SIZE = 10 * 1024 * 1024;
const FORMATS = new Set(FILE_ACCEPT.split(','));

function fileKey(file) {
  return JSON.stringify([file.name, file.size, file.lastModified, file.type]);
}

export function appendUploadFiles(existing, incoming, sourceType = 'Other') {
  const next = [...existing];
  const keys = new Set(existing.map(entry => entry.id));
  for (const file of Array.from(incoming || [])) {
    const id = fileKey(file);
    if (keys.has(id)) continue;
    keys.add(id);
    const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
    const validationError = !FORMATS.has(extension)
      ? 'Unsupported format. Choose PDF, DOCX, CSV, TSV, XLSX, or TXT.'
      : file.size > MAX_FILE_SIZE ? 'This file exceeds the 10 MB limit.'
        : file.size === 0 ? 'This file is empty.' : '';
    next.push({id, file, sourceType, status: validationError ? 'failed' : 'queued', error: validationError, validationError});
  }
  return next;
}

export function pendingUploads(entries) {
  return entries.filter(entry => !entry.validationError && ['queued', 'failed'].includes(entry.status));
}

// Process every selected file, retaining individual failures and successful results.
export async function runUploadBatch(entries, sendFile, update) {
  const pending = pendingUploads(entries);
  const outputs = [];
  for (const [index, entry] of pending.entries()) {
    const progress = {index, total: pending.length, filename: entry.file.name};
    update(entry.id, {status: 'processing', error: ''}, progress);
    try {
      const response = await sendFile(entry);
      const result = {...response, filename: entry.file.name};
      outputs.push(result);
      update(entry.id, {status: 'complete', result, error: ''}, {...progress, completed: index + 1});
    } catch (error) {
      const result = {filename: entry.file.name, error: error?.message || 'This file could not be processed.'};
      outputs.push(result);
      update(entry.id, {status: 'failed', error: result.error, result}, {...progress, completed: index + 1});
    }
  }
  return outputs;
}
