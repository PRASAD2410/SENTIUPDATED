import React, {useEffect, useRef, useState} from 'react';
import {ArrowRight, Upload, FileText, CheckCircle2, Loader2, X, Download, Plus, RefreshCw} from 'lucide-react';
import {API, api, readSetting, Intro, Empty, Modal} from './shared';
import {SOURCE_TYPES, FILE_ACCEPT, appendUploadFiles, pendingUploads, runUploadBatch} from './uploadQueue';
import './sourceUpload.css';

const STATUS_LABELS = {queued: 'Ready', processing: 'Uploading and analyzing…', complete: 'Completed', failed: 'Needs attention'};

export default function InputView({data, current, refresh}) {
  const [draft, setDraft] = useState(() => readSetting('sg-draft-' + current.id, ''));
  const [types, setTypes] = useState(['Criminal Network Analysis', 'Money Laundering', 'Cyber Fraud']);
  const [selected, setSelected] = useState('Criminal Network Analysis');
  const [adding, setAdding] = useState(false);
  const [menu, setMenu] = useState(false);
  const [source, setSource] = useState('Other');
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [reanalysisMessage, setReanalysisMessage] = useState('');
  const picker = useRef(null);
  const pickerSource = useRef(source);
  const pendingCount = pendingUploads(files).length;
  const completedCount = files.filter(file => file.status === 'complete').length;

  useEffect(() => {
    try { localStorage.setItem('sg-draft-' + current.id, draft); } catch {}
  }, [draft, current.id]);

  function addFiles(incoming, sourceType = source) {
    if (busy) return;
    setFiles(existing => appendUploadFiles(existing, incoming, sourceType));
    setMenu(false);
  }

  function chooseFiles(sourceType = source) {
    setSource(sourceType);
    pickerSource.current = sourceType;
    setMenu(false);
    picker.current?.click();
  }

  async function reanalyze(document) {
    setBusy(true);
    setProgress(null);
    setError('');
    setReanalysisMessage('');
    try {
      const response = await api(`/api/cases/${current.id}/documents/${document.documentId}/reanalyze`, {method: 'POST'});
      setReanalysisMessage(`${response.relationshipCount} relationships saved for ${document.filename}. No additional upload was created.`);
      refresh();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  async function upload() {
    if (busy || !pendingCount) return;
    setBusy(true);
    setError('');
    setProgress({index: 0, total: pendingCount, completed: 0});
    try {
      const outputs = await runUploadBatch(files, async entry => {
        const form = new FormData();
        form.append('file', entry.file);
        form.append('case_id', current.id);
        form.append('source_type', entry.sourceType);
        form.append('investigation_type', selected);
        return api('/api/upload', {method: 'POST', body: form});
      }, (id, changes, nextProgress) => {
        setFiles(existing => existing.map(entry => entry.id === id ? {...entry, ...changes} : entry));
        setProgress(nextProgress);
      });
      setResult(outputs);
      refresh();
    } finally {
      setBusy(false);
    }
  }

  async function submitText() {
    setBusy(true);
    setProgress(null);
    setError('');
    try {
      setResult([await api('/api/ingest', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: draft, title: 'Investigator note', case_id: current.id}),
      })]);
      setDraft('');
      refresh();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  return <div className="page-content">
    <Intro eyebrow="SOURCE INGESTION" title="Add investigation records and source material."
      description="Upload several source files together. Each file and its findings belong to the selected case."
      badge={'WORKSPACE / ' + current.id}/>
    <p className="eyebrow type-label">INVESTIGATION TYPE</p>
    <div className="type-grid">
      {types.map(type => <button disabled={busy} className={'type-card ' + (selected === type ? 'selected' : '')}
        key={type} onClick={() => setSelected(type)}>
        <i className={'dot ' + (selected === type ? 'blue' : 'gray')}/>
        <span><strong>{type.toUpperCase()}</strong><small>{selected === type ? 'SELECTED' : 'SELECT'}</small></span>
      </button>)}
      <button disabled={busy} className="dashed-button" onClick={() => {setMenu(false); setAdding(true);}}>+<br/>ADD TYPE</button>
    </div>

    <section className="panel intake-panel">
      <div className="between">
        <div><p className="eyebrow">RAW INVESTIGATION CONTENT</p><h3>Record Intake</h3></div>
        <span className="eyebrow">DRAFT SAVED ON DEVICE</span>
      </div>
      <textarea aria-label="Investigation content"
        placeholder="Paste or type investigation content, reports, names, phone numbers, transactions, notes or other relevant information…"
        value={draft} onChange={event => setDraft(event.target.value)}/>
      <div className="between intake-actions">
        <span className="micro">{draft.length} CHARACTERS</span>
        <div className="action-group">
          {draft.trim() && <button disabled={busy || draft.trim().length < 15} onClick={submitText}>EXTRACT TEXT <ArrowRight size={14}/></button>}
          <div className="upload-menu-anchor">
            <button className="primary" disabled={busy} onClick={() => setMenu(!menu)} aria-expanded={menu}>
              <Upload size={14}/> ADD SOURCE FILES
            </button>
            {menu && <div className="upload-menu panel"><p className="micro">SOURCE TYPE</p>
              {SOURCE_TYPES.map(type => <button key={type} onClick={() => chooseFiles(type)}>{type}<span className="micro">SELECT FILES →</span></button>)}
            </div>}
          </div>
        </div>
      </div>

      <input className="visually-hidden" ref={picker} type="file" multiple accept={FILE_ACCEPT}
        aria-label="Select multiple source files" disabled={busy}
        onChange={event => {addFiles(event.target.files, pickerSource.current); event.target.value = '';}}/>
      <div className={'source-drop-zone ' + (dragging ? 'dragging' : '')}
        onDragOver={event => {event.preventDefault(); if (!busy) setDragging(true);}}
        onDragLeave={event => {if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false);}}
        onDrop={event => {event.preventDefault(); setDragging(false); addFiles(event.dataTransfer.files);}}>
        <Upload size={22}/>
        <strong>Drop multiple files here</strong>
        <p className="small muted">Use Ctrl or Shift to select several files, or add more without replacing your selection.</p>
        <div className="source-picker-actions">
          <label className="small muted">Source type
            <select aria-label="Default source type for added files" disabled={busy} value={source}
              onChange={event => {setSource(event.target.value); pickerSource.current = event.target.value;}}>
              {SOURCE_TYPES.map(type => <option key={type}>{type}</option>)}
            </select>
          </label>
          <button disabled={busy} onClick={() => chooseFiles()}><Plus size={14}/> CHOOSE FILES</button>
        </div>
      </div>

      {files.length > 0 && <div className="selected-files source-upload-queue">
        <div className="between source-queue-heading">
          <p className="eyebrow">{files.length} SOURCE FILE{files.length === 1 ? '' : 'S'} / {pendingCount} READY TO PROCESS</p>
          {completedCount > 0 && <button disabled={busy} onClick={() => setFiles(existing => existing.filter(entry => entry.status !== 'complete'))}>HIDE COMPLETED</button>}
        </div>
        {files.map(entry => <div className={'source-queue-row ' + entry.status} key={entry.id}>
          <FileText size={18}/>
          <div className="source-queue-file">
            <strong>{entry.file.name}</strong><small>{(entry.file.size / 1024).toFixed(1)} KB</small>
            <span className={'source-queue-status ' + (entry.status === 'complete' ? 'green' : entry.status === 'failed' ? 'red' : 'muted')}>
              {entry.status === 'processing' && <Loader2 className="spin" size={12}/>}
              {entry.status === 'complete' && <CheckCircle2 size={12}/>}
              {STATUS_LABELS[entry.status]}
              {entry.status === 'complete' && ` · ${entry.result?.entities?.length || 0} entities · ${entry.result?.relationships?.length || 0} relationships`}
            </span>
            {entry.error && <p className="source-file-error" role="alert">{entry.error}</p>}
          </div>
          <select aria-label={'Source type for ' + entry.file.name} value={entry.sourceType}
            disabled={busy || entry.status === 'complete'}
            onChange={event => setFiles(existing => existing.map(file => file.id === entry.id ? {...file, sourceType: event.target.value} : file))}>
            {SOURCE_TYPES.map(type => <option key={type}>{type}</option>)}
          </select>
          <button disabled={busy} className="icon-button" aria-label={'Remove ' + entry.file.name + ' from selection'}
            onClick={() => setFiles(existing => existing.filter(file => file.id !== entry.id))}><X size={14}/></button>
        </div>)}
        <div className="source-batch-actions">
          <button className="primary" disabled={busy || !pendingCount} onClick={upload}>
            {busy && progress ? <Loader2 className="spin" size={14}/> : <ArrowRight size={14}/>}
            {busy && progress ? `PROCESSING ${Math.min(progress.index + 1, progress.total)} OF ${progress.total}` : `UPLOAD & EXTRACT ${pendingCount} FILE${pendingCount === 1 ? '' : 'S'}`}
          </button>
          {!busy && files.some(entry => entry.status === 'failed') && <p className="small muted">Failed files stay in the list so you can retry or remove them.</p>}
        </div>
        {progress && <div className="source-batch-progress" role="status" aria-live="polite">
          <progress max={progress.total} value={progress.completed ?? progress.index}/>
          <span>{progress.completed ?? progress.index} of {progress.total} files processed{busy && progress.filename ? ' · ' + progress.filename : ''}</span>
        </div>}
      </div>}
      <p className="muted micro format-hint">PDF · DOCX · CSV · TSV · XLSX · TXT / UP TO 10 MB PER FILE</p>
    </section>

    {error && <p className="error" role="alert">{error}</p>}
    {reanalysisMessage && <p className="small green" role="status">{reanalysisMessage}</p>}
    {result && <section className="panel extraction-result"><p className="eyebrow">EXTRACTION RESULTS</p>
      {result.map((response, index) => <div key={index}>
        {response.filename && <p className="small source-result-filename"><strong>{response.filename}</strong></p>}
        {response.error ? <p className="error">{response.error}</p> : <>
          <h3><CheckCircle2 size={17}/> {response.entities?.length || 0} entities · {response.relationships?.length || 0} relationships</h3>
          <p className="small">{response.reanalyzed ? 'Relationships updated. Original file and report reused. ' : response.duplicate && 'Already stored — reused the original and existing entities. No duplicate records created. '}
            {response.fileStorage?.saved ? 'Original file saved. ' : ''}
            {response.relationshipStatus?.complete === false ? 'Entities saved; relationship extraction needs retry. Use Reanalyze below.' : response.storage?.saved ? 'Extracted findings saved.' : response.storage?.warning}</p>
          {[...new Set([...(response.warnings || []), ...(response.parsedDocument?.warnings || [])])].map((warning, warningIndex) => <p className="muted small" key={warningIndex}>{warning}</p>)}
          <details><summary>Inspect entities and relationship evidence</summary>
            {(response.entities || []).map(entity => <p className="small" key={entity.id}>{entity.type} / {entity.label}</p>)}
            {(response.relationships || []).map(relationship => <p className="small" key={relationship.id}>{relationship.type} / {relationship.evidenceText}</p>)}
          </details>
          {response.parsedDocument && <details><summary>Inspect extracted text</summary><pre>{response.parsedDocument.text}</pre></details>}
        </>}
      </div>)}
    </section>}

    <div className="section-heading"><p className="eyebrow">ATTACHED EVIDENCE</p><h3>Source Records <span className="blue">{data.documents.length}</span></h3></div>
    {data.documents.length ? <div className="panel source-table">
      {data.documents.map(document => <div className="source-row" key={document.documentId}>
        <FileText size={22}/><span><strong>{document.filename}</strong><small>{document.documentId} · {(document.sizeBytes / 1024).toFixed(1)} KB</small>
          {document.entityCount != null && <small>{document.entityCount} entities · {document.relationshipCount ?? 0} relationships saved</small>}</span>
        <span className={'status-badge ' + (document.processingStatus === 'completed' && document.relationshipStatus?.complete !== false ? 'green' : 'amber')}>{document.relationshipStatus?.complete === false ? 'Relationships pending' : document.processingStatus}</span>
        <button disabled={busy || !document.reportId} className="icon-button" title="Reanalyze relationships using current rules"
          aria-label={'Reanalyze relationships in ' + document.filename} onClick={() => reanalyze(document)}><RefreshCw size={16}/></button>
        <a className="icon-button" href={`${API}/api/cases/${current.id}/documents/${document.documentId}/download`} aria-label={'Download ' + document.filename}><Download size={16}/></a>
      </div>)}
    </div> : <div className="dashed-empty"><Empty title="No source records attached" description="Upload FIRs, transaction records, call logs, or other case material."/></div>}
    {adding && <Modal title="Add Investigation Type" close={() => setAdding(false)}>
      {['Human Trafficking', 'Organized Crime', 'Financial Crime', 'Drug Network'].filter(type => !types.includes(type)).map(type =>
        <button className="modal-option" key={type} onClick={() => {setTypes(existing => [...existing, type]); setSelected(type); setAdding(false);}}>{type}<Plus size={15}/></button>)}
    </Modal>}
  </div>;
}
