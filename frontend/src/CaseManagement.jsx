import React,{useState} from 'react';
import {Trash2,RotateCcw,AlertTriangle} from 'lucide-react';
import {api,Modal} from './shared';

export default function CaseManagement({current,data,close,finished}){
  const [action,setAction]=useState(''),[confirmation,setConfirmation]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const isDelete=action==='delete';
  async function submit(e){
    e.preventDefault();
    if(confirmation!==current.title||busy)return;
    setBusy(true);setError('');
    try{
      const path=`/api/cases/${encodeURIComponent(current.id)}`+(isDelete?'':'/data');
      await api(path,{method:'DELETE',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({confirm_case_id:current.id})});
      finished({deleted:isDelete,caseId:current.id});
    }catch(e){setError(e.message);setBusy(false);}
  }
  return <Modal title={action?(isDelete?'Delete Case':'Clear Case Data'):'Manage Case'} close={()=>{if(!busy)close();}}>
    <p className="eyebrow">SELECTED CASE / {current.id}</p>
    <h3>{current.title}</h3>
    {!action?<>
      <p className="muted small case-management-summary">{data.documents.length} uploaded files · {data.overview.nodes} entity groups · {data.overview.edges} relationship statements</p>
      <button className="case-action-option" onClick={()=>setAction('clear')}><RotateCcw size={18}/><span><strong>Clear Case Data</strong><small>Keep the case title and details. Remove uploads and extracted findings.</small></span></button>
      <button className="case-action-option danger" onClick={()=>setAction('delete')}><Trash2 size={18}/><span><strong>Delete Case</strong><small>Remove the case, uploaded files, and all extracted findings.</small></span></button>
    </>:<form onSubmit={submit}>
      <div className="destructive-notice"><AlertTriangle size={18}/><p>This permanently removes this case's original files, entities, mentions, relationships, and reports. {isDelete?'The case title and details will also be deleted.':'The case title and details will remain.'} This cannot be undone.</p></div>
      <label className="field-label" htmlFor="confirm-case-title">TYPE THE CASE TITLE TO CONFIRM</label>
      <p className="small confirmation-title">{current.title}</p>
      <input id="confirm-case-title" value={confirmation} onChange={e=>setConfirmation(e.target.value)} autoComplete="off" disabled={busy}/>
      {error&&<p className="error" role="alert">{error}</p>}
      <div className="modal-actions"><button type="button" disabled={busy} onClick={()=>{setAction('');setConfirmation('');setError('');}}>BACK</button><button type="submit" className="danger-button" disabled={busy||confirmation!==current.title}>{busy?'REMOVING…':isDelete?'DELETE CASE':'CLEAR CASE DATA'}</button></div>
    </form>}
  </Modal>;
}
