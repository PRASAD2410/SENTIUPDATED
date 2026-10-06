import os
from datetime import datetime
from uuid import uuid4
from urllib.parse import quote
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2]/'.env')
import networkx as nx
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.responses import Response
from .extraction import extract, get_extraction_version, RelationshipExtractionError
from .neo_store import NeoStore
from .file_reader import parse_upload, UnsupportedFormatError, ALLOWED
from .llm import get_llm_provider
from .mongo_store import MongoStore, CaseBusyError
from .nlp import nlp_status
from .demo_data import DEMO_REPORTS

app=FastAPI(title='SentinelGraph API',version='0.2.0')
app.add_middleware(CORSMiddleware,allow_origins=[os.getenv('FRONTEND_ORIGIN','http://localhost:5173')],allow_methods=['*'],allow_headers=['*'])
# Session findings cache; durable data stored in MongoDB and Neo4j
nodes={}; edges=[]; reports=[]; neo=NeoStore(); mongo=MongoStore()
class Ingest(BaseModel):
 text:str=Field(min_length=15)
 title:str='Investigator submitted report'
 date:str|None=None
 case_id:str=Field(default='default',min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
class Question(BaseModel):
 question:str=Field(min_length=2,max_length=1000)
 case_id:str='default'
class NewCase(BaseModel):
 title:str=Field(min_length=1,max_length=150)
 classification:str='Restricted'
 summary:str=Field(default='',max_length=2000)
class ConfirmCaseAction(BaseModel):
 confirm_case_id:str=Field(min_length=1,max_length=100)
def graph():
 g=nx.Graph(); g.add_nodes_from(nodes); g.add_edges_from((e['source'],e['target']) for e in edges); return g
def analytics():
 g=graph()
 if not g:return []
 degree=nx.degree_centrality(g); between=nx.betweenness_centrality(g); pagerank=nx.pagerank(g)
 return sorted([{'id':i,'label':nodes[i]['label'],'type':nodes[i]['type'],'degree':round(degree.get(i,0),3),'betweenness':round(between.get(i,0),3),'pagerank':round(pagerank.get(i,0),3)} for i in g.nodes],key=lambda x:(x['pagerank'],x['degree']),reverse=True)
def evidence(a,b): return sorted({e['reportId'] for e in edges if {e['source'],e['target']}=={a,b}})
def leads():
 g=graph(); out=[]; bridges=nx.betweenness_centrality(g)
 for node in g.nodes:
  links=list(g.neighbors(node)); kinds={nodes[n]['type'] for n in links}; names=', '.join(nodes[n]['label'] for n in links[:4]); sources=sorted({rid for n in links for rid in evidence(node,n)})
  if len(links)>=3: out.append({'severity':'high','title':f"Cross-domain linkage: {nodes[node]['label']}",'entity':nodes[node]['label'],'reason':f"Reported alongside {len(links)} linked entities ({names}) across {len(kinds)} categories. Sources: {', '.join(sources) or 'review pending'}.",'rule':'Entity links across three or more records/categories','sources':sources})
  if bridges.get(node,0)>=.12: out.append({'severity':'medium','title':f"Potential network bridge: {nodes[node]['label']}",'entity':nodes[node]['label'],'reason':'Connects otherwise separate parts of the reported network. Review underlying source context before any action.','rule':'High betweenness centrality','sources':sources})
 for a,b in g.edges:
  common=list(nx.common_neighbors(g,a,b))
  if common:
   shared=nodes[common[0]]['label']; sources=sorted(set(evidence(a,common[0])+evidence(b,common[0])))
   out.append({'severity':'medium','title':f"Shared reported association: {nodes[a]['label']} and {nodes[b]['label']}",'entity':f"{nodes[a]['label']} ↔ {nodes[b]['label']}",'reason':f"Both are linked to {shared}. Validate whether this is a meaningful connection or incidental overlap. Sources: {', '.join(sources)}.",'rule':'Common-neighbor pattern','sources':sources})
 return out[:12]
def process(text,title,source,date=None,parsed_document=None,case_id='default',document_id=None):
 report_id=f'USR-{uuid4().hex}'
 result=extract(text,parsed_document,scope=f'case:{case_id}'); date=date or datetime.now().date().isoformat(); report={'id':report_id,'caseId':case_id,'date':date,'title':title,'text':text,'source':source}
 if document_id: report['documentId']=document_id
 storage=mongo.save_extraction(case_id,report,result)
 if parsed_document is not None: report['parsedDocument']=parsed_document
 reports.append(report)
 for e in result['entities']: nodes.setdefault(e['id'],{'id':e['id'],'label':e['label'],'type':e['type'],'risk':30})
 for r in result['relationships']:
  if r['source'] in nodes and r['target'] in nodes: edges.append({**r,'label':r['type'],'reportId':report_id})
 neo.add_extraction(result['entities'],result['relationships'],report_id)
 return {'reportId':report_id,'caseId':case_id,**result,'storage':storage,'message':'Findings are investigative leads for human review; they do not establish criminality.'}
@app.on_event('startup')
def startup():
 mongo.connect()
 neo.seed(nodes,edges)
@app.on_event('shutdown')
def shutdown(): mongo.close()
@app.get('/health')
def health(): return {'status':'ok','mode':'neo4j+memory' if neo.available else 'demo-memory','geminiEnabled':get_llm_provider().available,'nlp':nlp_status(),'mongo':mongo.status()}
@app.get('/api/cases/{case_id}/entities')
def stored_entities(case_id:str):
 try: return {'caseId':case_id,'entities':mongo.entities_for_case(case_id),'limit':1000}
 except Exception: raise HTTPException(503,'MongoDB entities are unavailable. Check database configuration.')
@app.get('/api/cases')
def list_cases():
 try: return {'cases':mongo.list_cases()}
 except Exception: raise HTTPException(503,'Case storage is unavailable. Check MongoDB.')
@app.post('/api/cases')
def create_case(payload:NewCase):
 if not payload.title.strip(): raise HTTPException(422,'A case title is required.')
 try: return mongo.create_case(payload.title.strip(),payload.classification,payload.summary)
 except Exception: raise HTTPException(503,'The case could not be saved. Check MongoDB.')
def manage_case_data(case_id,payload,delete_case):
 if payload.confirm_case_id!=case_id:
  raise HTTPException(422,'The confirmation must match the selected case ID.')
 try: result=mongo.clear_case(case_id,delete_case)
 except ValueError: raise HTTPException(404,'Case not found.')
 except CaseBusyError as exc: raise HTTPException(409,str(exc))
 except Exception: raise HTTPException(503,'Case cleanup could not finish. Some data may remain; check MongoDB and retry.')
 removed_reports=set(result.pop('_reportIds')); removed_entities=result.pop('_entityIds')
 reports[:]=[r for r in reports if r.get('caseId','default')!=case_id]
 edges[:]=[r for r in edges if r.get('reportId') not in removed_reports]
 for entity_id in removed_entities:
  if not mongo.db.entities.find_one({'id':entity_id}): nodes.pop(entity_id,None)
 return {**result,'message':'Case deleted.' if delete_case else 'Case data cleared; case details retained.'}
@app.delete('/api/cases/{case_id}/data')
def clear_case_data(case_id:str,payload:ConfirmCaseAction):
 return manage_case_data(case_id,payload,False)
@app.delete('/api/cases/{case_id}')
def delete_case(case_id:str,payload:ConfirmCaseAction):
 return manage_case_data(case_id,payload,True)
class EdgeReview(BaseModel):
 review_status:str=Field(pattern=r'^(accepted|rejected|pending)$')

@app.get('/api/cases/{case_id}/workspace')
def case_workspace(case_id:str, min_confidence:float=0.0, layer:str|None=None, time_start:str|None=None, time_end:str|None=None):
 try:
  entities=mongo.entities_for_case(case_id); relationships=mongo.relationships_for_case(case_id); documents=mongo.documents_for_case(case_id)
 except Exception: raise HTTPException(503,'Case records are unavailable. Check MongoDB.')
 
 if min_confidence > 0:
  relationships=[r for r in relationships if float(r.get('confidence') or 1.0) >= min_confidence]
 if layer:
  relationships=[r for r in relationships if r.get('method') == layer or r.get('type') == layer]
 if time_start:
  relationships=[r for r in relationships if not r.get('timestamp') or str(r['timestamp']) >= time_start]
 if time_end:
  relationships=[r for r in relationships if not r.get('timestamp') or str(r['timestamp']) <= time_end]

 # Collapse historical report-scoped spellings for display, retaining aliases
 # and all source references. This is name grouping, not verified identity.
 groups={}; aliases={}
 for item in entities:
  key=(item['type'],item.get('normalizedValue') or ' '.join(item['label'].casefold().split()))
  if key not in groups:
   groups[key]={**item,'aliasIds':[],'reportIds':[]}
  group=groups[key]; aliases[item['id']]=group['id']
  group['aliasIds'].append(item['id'])
  group['reportIds']=sorted(set(group['reportIds']+item.get('reportIds',[])))
  if item['type']=='Person': group['identityStatus']='unverified-name-group'
 entities=list(groups.values())
 relationships=[{**r,'originalSource':r['source'],'originalTarget':r['target'],
                 'source':aliases.get(r['source'],r['source']),'target':aliases.get(r['target'],r['target'])}
                for r in relationships]
 g=nx.Graph(); g.add_nodes_from((e['id'],e) for e in entities)
 valid=[r for r in relationships if r['source'] in g and r['target'] in g]
 g.add_edges_from((r['source'],r['target']) for r in valid)
 degree=nx.degree_centrality(g) if g else {}; between=nx.betweenness_centrality(g) if g else {}
 rankings=sorted([{'id':e['id'],'label':e['label'],'type':e['type'],'degree':degree.get(e['id'],0),'betweenness':between.get(e['id'],0),'connections':g.degree(e['id'])} for e in entities],key=lambda e:e['connections'],reverse=True)
 case_leads=[]
 for e in rankings:
  if e['connections']<3: continue
  supporting=[r for r in valid if e['id'] in (r['source'],r['target'])]
  sources=sorted({r.get('reportId') or r.get('documentId') or 'Record' for r in supporting})
  conf=min(0.98, round(0.70 + (e['connections'] * 0.04) + (len(sources) * 0.03), 2))
  sev='high' if e['connections']>=5 or len(sources)>=2 else 'medium'
  case_leads.append({'severity':sev,'confidenceScore':conf,'title':f"Reported connections: {e['label']}",'entity':e['label'],'entityId':e['id'],'reason':f"Linked to {e['connections']} distinct entities across {len(sources)} source record(s). Review the context and alternative explanations.",'rule':'Multi-source hub / entity connectivity threshold','sources':sources,'evidence':supporting})
 return {'network':{'nodes':entities,'edges':valid},'documents':documents,'analytics':rankings,'leads':case_leads,
         'overview':{'nodes':len(entities),'edges':len(valid),'reports':len(documents),'leads':len(case_leads)},'truncated':any(len(items)>=1000 for items in (entities,relationships,documents))}

@app.post('/api/cases/{case_id}/edges/{edge_id}/review')
def review_edge(case_id:str, edge_id:str, payload:EdgeReview):
 if mongo.db is None: raise HTTPException(503, 'MongoDB is unavailable.')
 res = mongo.db.relationships.update_one({'_id': edge_id, 'caseId': case_id}, {'$set': {'reviewStatus': payload.review_status, 'updatedAt': datetime.now()}})
 if res.matched_count == 0:
  raise HTTPException(404, 'Edge not found.')
 return {'edgeId': edge_id, 'caseId': case_id, 'reviewStatus': payload.review_status}
@app.get('/api/cases/{case_id}/documents')
def stored_documents(case_id:str):
 try: return {'caseId':case_id,'documents':mongo.documents_for_case(case_id),'limit':1000}
 except Exception: raise HTTPException(503,'MongoDB documents are unavailable.')
@app.get('/api/cases/{case_id}/relationships')
def stored_relationships(case_id:str):
 try: return {'caseId':case_id,'relationships':mongo.relationships_for_case(case_id),'limit':1000}
 except Exception: raise HTTPException(503,'MongoDB relationships are unavailable.')
@app.get('/api/cases/{case_id}/documents/{document_id}/download')
def download_document(case_id:str,document_id:str):
 try: original=mongo.original_document(case_id,document_id)
 except Exception: raise HTTPException(503,'The stored file could not be retrieved.')
 if original is None: raise HTTPException(404,'Document not found in this case.')
 record,content=original
 return Response(content,media_type='application/octet-stream',headers={
  'Content-Disposition': "attachment; filename*=UTF-8''"+quote(record['filename'],safe=''),
  'X-Content-Type-Options': 'nosniff'})
@app.get('/api/cases/{case_id}/documents/{document_id}')
def get_document_details(case_id:str,document_id:str):
 if mongo.db is None: raise HTTPException(503,'MongoDB is unavailable.')
 doc=mongo.db.documents.find_one({'_id':document_id,'caseId':case_id},{'_id':0})
 if not doc: raise HTTPException(404,'Document not found.')
 report=mongo.db.reports.find_one({'_id':doc.get('reportId'),'caseId':case_id},{'_id':0}) if doc.get('reportId') else None
 extraction=mongo.extraction_for_report(case_id,doc['reportId']) if doc.get('reportId') else {'entities':[],'relationships':[],'mentions':[]}
 return {'document':doc,'report':report,'entities':extraction.get('entities',[]),'relationships':extraction.get('relationships',[]),'mentions':extraction.get('mentions',[])}
@app.post('/api/cases/{case_id}/documents/{document_id}/reanalyze')
def reanalyze_document_relationships(case_id:str,document_id:str):
 try: original=mongo.original_document(case_id,document_id)
 except Exception: raise HTTPException(503,'The original document is unavailable. Check MongoDB.')
 if original is None: raise HTTPException(404,'Document not found in this case.')
 record,content=original
 try:
  parsed=parse_upload(record['filename'],content)
  return mongo.reanalyze_relationships(case_id,document_id,parsed)
 except RelationshipExtractionError as e: raise HTTPException(502,str(e))
 except ValueError as e: raise HTTPException(422,str(e))
 except Exception: raise HTTPException(503,'Relationship reanalysis could not be saved. Check the rules and MongoDB.')
@app.get('/api/overview')
def overview(): return {'nodes':len(nodes),'edges':len(edges),'reports':len(reports),'leads':len(leads()),'topEntities':analytics()[:5],'geminiEnabled':get_llm_provider().available}
@app.get('/api/network')
def network(): return {'nodes':list(nodes.values()),'edges':edges}
@app.get('/api/timeline')
def timeline(): return sorted(reports,key=lambda x:x['date'])
@app.get('/api/analytics')
def get_analytics(): return analytics()
@app.get('/api/leads')
def get_leads(): return leads()
@app.delete('/api/workspace')
def clear_workspace():
 # The local MVP is intentionally session-based; clearing starts a fresh case.
 nodes.clear(); edges.clear(); reports.clear()
 return {'message':'Workspace cleared. Start a new case by uploading a source record.'}
@app.post('/api/demo/seed')
def seed_demo(case_id:str='default'):
 seeded=[process(r['text'],r['title'],r['source'],r['date'],case_id=case_id) for r in DEMO_REPORTS]
 return {'status':'ok','caseId':case_id,'seededReports':len(seeded),'message':f'Successfully seeded {len(seeded)} demo reports into case {case_id}.'}
@app.post('/api/ingest')
def ingest(payload:Ingest): return process(payload.text,payload.title,'Investigator submitted',payload.date,case_id=payload.case_id)
@app.post('/api/upload')
async def upload(file:UploadFile=File(...),case_id:str=Form('default'),source_type:str=Form('Other'),investigation_type:str=Form('Criminal Network Analysis')):
 import re
 if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',case_id): raise HTTPException(422,'Case ID must contain 1-100 letters, digits, underscores or hyphens.')
 content=await file.read()
 max_size=int(os.getenv('MAX_UPLOAD_SIZE_MB','1024'))*1024*1024
 if len(content)>max_size: raise HTTPException(413,f'Maximum file size is {max_size//(1024*1024)} MB.')
 filename=(file.filename or 'upload.txt').replace('\\','/').rsplit('/',1)[-1]
 if Path(filename).suffix.lower() not in ALLOWED: raise HTTPException(415,'Supported formats: PDF, DOCX, TXT, CSV, TSV, XLSX.')
 try: document=mongo.save_document(case_id,filename,content,file.content_type)
 except RuntimeError as e: raise HTTPException(503,str(e))
 document_id=document['documentId']
 if document.get('duplicate'):
  if document.get('processingStatus')!='completed' or not document.get('reportId'):
   raise HTTPException(409,{'message':'This file is already stored but its extraction is pending or failed. No duplicate file was created.','documentId':document_id})
  refreshed=False
  warnings=document.get('warnings',[])
  if document.get('extractionVersion')!=get_extraction_version():
   try:
    parsed=parse_upload(document['filename'],content)
    update=mongo.reanalyze_relationships(case_id,document_id,parsed)
    refreshed=True; warnings=update.get('warnings',[])
   except RelationshipExtractionError as exc:
    raise HTTPException(502,str(exc))
   except Exception:
    raise HTTPException(503,'This file is already saved, but updating its relationships failed. No duplicate file was created; check MongoDB and retry.')
  result=mongo.extraction_for_report(case_id,document['reportId'])
  report_state=mongo.db.reports.find_one({'_id':document['reportId'],'caseId':case_id}) or {}
  result['relationshipStatus']=report_state.get('relationshipStatus')
  return {'reportId':document['reportId'],'caseId':case_id,'documentId':document_id,
          **result,'duplicate':True,'fileStorage':{'saved':True,'reused':True,'documentId':document_id},
          'storage':{'saved':True,'reused':True},'warnings':warnings,'reanalyzed':refreshed,
          'message':('Existing file reanalyzed with the current relationship extractor; the original file and report were reused.' if refreshed else 'This file already exists in this case. Reused the stored file and findings; no new records were created.')}
 try:
  mongo.document_status(case_id,document_id,'processing',sourceType=source_type[:100],investigationType=investigation_type[:100])
  parsed=parse_upload(filename,content)
  if len(parsed['text'].strip())<15:
   raise HTTPException(422,{'message':'Insufficient usable text was found. The original file is saved.','warnings':parsed['warnings'],'documentId':document_id})
  response=process(parsed['text'],f'Uploaded: {filename}','Uploaded file',parsed_document=parsed,case_id=case_id,document_id=document_id)
  completed=response['storage']['saved']
  mongo.document_status(case_id,document_id,'completed' if completed else 'storage_failed',reportId=response['reportId'],extractionVersion=get_extraction_version() if response.get('relationshipStatus',{}).get('complete',True) else 'incomplete',relationshipStatus=response.get('relationshipStatus'),warnings=parsed['warnings']+response['warnings'])
  return {**response,'documentId':document_id,'fileStorage':{'saved':True,'documentId':document_id},'parsedDocument':parsed}
 except Exception as exc:
  try: mongo.document_status(case_id,document_id,'failed')
  except Exception: pass
  if isinstance(exc,HTTPException): raise
  raise HTTPException(422,{'message':'The original file is saved, but processing failed. Check the format and MongoDB connection.','documentId':document_id})
def _build_local_assistant_response(question: str, workspace: dict, docs: list) -> str:
    q = question.lower().strip()
    analytics = workspace.get('analytics', [])
    nodes = workspace.get('network', {}).get('nodes', [])
    edges = workspace.get('network', {}).get('edges', [])
    leads = workspace.get('leads', [])
    overview = workspace.get('overview', {})
    node_map = {n['id']: n for n in nodes}

    # 1. Summarize this case
    if any(k in q for k in ('summarize', 'summary', 'overview', 'about this case', 'case context')):
        top_nodes = analytics[:5]
        top_str = ", ".join([f"**{n['label']}** ({n['type']}, {n['connections']} links)" for n in top_nodes]) if top_nodes else "None extracted yet"
        doc_titles = [d.get('title') or d.get('filename') or d.get('_id') for d in docs[:5]]
        docs_str = ", ".join(doc_titles) if doc_titles else f"{overview.get('reports', 0)} source documents"
        persons_count = len([n for n in nodes if n.get('type') == 'Person'])
        orgs_count = len([n for n in nodes if n.get('type') in ('Organization', 'Company')])
        ids_count = len([n for n in nodes if n.get('type') in ('Phone', 'AccountNumber', 'Vehicle', 'Location', 'Domain', 'Email')])

        return (
            f"### Case Summary\n"
            f"**Overview:** {overview.get('nodes', 0)} extracted entities, {overview.get('edges', 0)} relationships, {overview.get('reports', 0)} source records.\n\n"
            f"**Uploaded Records:** {docs_str}\n\n"
            f"**Top Connected Key Entities:** {top_str}\n\n"
            f"**Breakdown:** {persons_count} Person(s), {orgs_count} Organization(s), and {ids_count} Identifier(s) (Phones/Accounts/Vehicles/Locations).\n\n"
            f"**Analytical Leads:** {len(leads)} investigation signal(s) flagged for review."
        )

    # 2. Which entities have the most connections?
    if any(k in q for k in ('most connections', 'most connected', 'highest degree', 'top connected', 'connected entities', 'connections')):
        top_nodes = analytics[:8]
        if not top_nodes:
            return "No connected entities found in this case yet."
        lines = ["### Top Connected Entities in Case Network\n"]
        for idx, n in enumerate(top_nodes, 1):
            neighbors = []
            for e in edges:
                if e.get('source') == n['id'] and e.get('target') in node_map:
                    neighbors.append(node_map[e['target']]['label'])
                elif e.get('target') == n['id'] and e.get('source') in node_map:
                    neighbors.append(node_map[e['source']]['label'])
            unique_neighbors = list(dict.fromkeys(neighbors))[:4]
            neighbor_str = ", ".join(unique_neighbors)
            lines.append(f"{idx}. **{n['label']}** (`{n['type']}`) — **{n['connections']} connections**")
            if neighbor_str:
                lines.append(f"   *Connected to:* {neighbor_str}")
        return "\n".join(lines)

    # 3. Show relationship evidence
    if any(k in q for k in ('evidence', 'relationship evidence', 'supporting evidence', 'proof', 'quotes')):
        evidence_edges = [e for e in edges if e.get('evidenceText') or e.get('reason')]
        if not evidence_edges:
            evidence_edges = edges[:6]
        if not evidence_edges:
            return "No supporting relationship evidence currently recorded in this case."
        lines = ["### Key Extracted Relationship Evidence\n"]
        for e in evidence_edges[:8]:
            src_name = node_map.get(e.get('source'), {}).get('label', e.get('source', 'Unknown'))
            tgt_name = node_map.get(e.get('target'), {}).get('label', e.get('target', 'Unknown'))
            rel_type = e.get('type', 'ASSOCIATED_WITH')
            quote = e.get('evidenceText') or e.get('reason') or 'Extracted association'
            doc_id = e.get('reportId') or e.get('documentId') or 'Source Record'
            origin = (e.get('origin') or 'reported').upper()
            lines.append(f"• **{src_name}** `[{rel_type}]` **{tgt_name}**")
            lines.append(f"  > *\"{quote}\"* — **{origin}** (Ref: `{doc_id}`)\n")
        return "\n".join(lines)

    # 4. Search for specific terms in entities
    matched_nodes = [n for n in nodes if any(term in n['label'].lower() or term in n['type'].lower() for term in q.split() if len(term) > 2)]
    if matched_nodes:
        lines = [f"### Entities Matching Query in Case Network\n"]
        for n in matched_nodes[:6]:
            lines.append(f"• **{n['label']}** (`{n['type']}`)")
            n_edges = [e for e in edges if e.get('source') == n['id'] or e.get('target') == n['id']]
            if n_edges:
                lines.append(f"  * {len(n_edges)} relationship(s):")
                for e in n_edges[:3]:
                    other_id = e['target'] if e['source'] == n['id'] else e['source']
                    other_name = node_map.get(other_id, {}).get('label', other_id)
                    lines.append(f"    - `{e.get('type', 'LINKED')}` ➜ **{other_name}**")
        return "\n".join(lines)

    # 5. Default case status answer
    top_entities = ", ".join([n['label'] for n in analytics[:5]]) if analytics else "None"
    return (
        f"Based on **{overview.get('reports', 0)} uploaded records** in case `{workspace.get('overview', {}).get('caseId', 'default')}`:\n\n"
        f"• **Extracted Entities:** {overview.get('nodes', 0)}\n"
        f"• **Extracted Relationships:** {overview.get('edges', 0)}\n"
        f"• **Top Key Hubs:** {top_entities}\n\n"
        f"You can ask *'Summarize this case'*, *'Which entities have the most connections?'*, or *'Show relationship evidence'* for detailed investigative insights."
    )

@app.post('/api/assistant')
def assistant(payload:Question):
 provider=get_llm_provider(); question=payload.question.lower()
 try: workspace=case_workspace(payload.case_id)
 except HTTPException: raise HTTPException(503,'The selected case is unavailable.')
 persons=[n['label'] for n in workspace['network']['nodes'] if n['type']=='Person']
 
 # Load reports from MongoDB or in-memory array
 case_reports = []
 if mongo.db is not None:
     try: case_reports = list(mongo.db.reports.find({'caseId': payload.case_id}, {'_id': 0}))
     except Exception: pass
 if not case_reports:
     case_reports = [r for r in reports if r.get('caseId','default') == payload.case_id]

 if any(term in question for term in ('culprit','criminal','guilty','guilt')):
  named=', '.join(persons) if persons else 'no people were confidently extracted'
  answer=f"I cannot identify ‘culprits’ or determine guilt from these records. The people explicitly named in the current uploaded sources are: {named}. Their presence in a report or graph is a reported association that requires independent verification and any legal outcome must come from the court record."
  return {'answer':answer,'disclaimer':'This response summarizes reported data and potential leads only. It is not proof of criminality.'}

 answer = None
 if provider.available:
  context={'entities':workspace['analytics'][:20],'leads':workspace['leads'][:12],'relationships':workspace['network']['edges'][:100],'reports':[{'id':r.get('id', r.get('_id')),'title':r.get('title',''),'date':r.get('date',''),'source':r.get('source',''),'full_text':(r.get('text') or '')[:250000]} for r in case_reports[-3:]]}
  res = provider.generate(f'''You are SentinelGraph's document-grounded case assistant. Use the FULL TEXT of the uploaded records in the case context to answer the user's question directly and completely. Answer questions about all named people, identifiers, phone numbers, vehicles, locations, dates, FIR/case details, stated events, and stated court outcomes when they appear in the record. Cite the relevant report ID. Do not rely only on the graph summary.

Never invent a fact. If a phone number or requested fact is not in the uploaded record, say it is not stated. Do not call anyone a criminal or guilty: use “named in the record”, “reported”, and “requires verification”.\nCASE CONTEXT:{context}\nQUESTION:{payload.question}''')
  if res and not res.startswith('Gemini is temporarily unavailable'):
      answer = res

 if not answer:
  answer = _build_local_assistant_response(payload.question, workspace, case_reports or workspace.get('documents', []))

 return {'answer':answer,'disclaimer':'This response summarizes reported data and potential leads only. It is not proof of criminality.'}

@app.get('/api/intelligence-db')
def intelligence_db(collection: str = 'ref_accounts', limit: int = 500):
    """Query any reference DB collection imported via mongoimport and return graph-ready nodes/edges."""
    if mongo.db is None:
        raise HTTPException(503, 'MongoDB is unavailable.')
    allowed = {'ref_accounts', 'ref_kyc', 'ref_companies', 'ref_directors', 'ref_vehicles', 'ref_vehicle_events', 'ref_cyber_events', 'ref_locations'}
    if collection not in allowed:
        raise HTTPException(400, f'Unknown collection. Allowed: {sorted(allowed)}')
    docs = list(mongo.db[collection].find({}, {'_id': 0}).limit(limit))
    return {'collection': collection, 'count': len(docs), 'records': docs}

@app.get('/api/intelligence-db/graph')
def intelligence_db_graph(limit: int = 800):
    """Build a cross-collection knowledge graph from all reference collections."""
    if mongo.db is None:
        raise HTTPException(503, 'MongoDB is unavailable.')
    nodes = {}
    edges = []
    edge_id = 0

    def add_node(nid, label, ntype, meta=None):
        if nid and nid not in nodes:
            nodes[nid] = {'id': nid, 'label': label, 'type': ntype, 'meta': meta or {}}

    def add_edge(src, tgt, rel, meta=None):
        nonlocal edge_id
        if src and tgt and src != tgt:
            edges.append({'id': f'e{edge_id}', 'source': src, 'target': tgt, 'relation': rel, 'label': rel, 'meta': meta or {}})
            edge_id += 1

    # KYC — persons
    for r in mongo.db.get_collection('ref_kyc').find({}, {'_id': 0}).limit(limit):
        pid = r.get('person_id') or r.get('id')
        name = r.get('name') or r.get('full_name') or pid
        if pid:
            add_node(pid, name, 'Person', {'aadhaar': r.get('aadhaar'), 'pan': r.get('pan'), 'address': r.get('address')})

    # Accounts — link person → account
    for r in mongo.db.get_collection('ref_accounts').find({}, {'_id': 0}).limit(limit):
        aid = r.get('account_id') or r.get('id')
        pid = r.get('owner_id') or r.get('person_id')
        bank = r.get('bank', '')
        acc_num = r.get('account_number', '')
        label = f"{bank} ···{acc_num[-4:]}" if acc_num else aid
        if aid:
            add_node(aid, label, 'Account', {'bank': bank, 'type': r.get('account_type'), 'upi': r.get('upi_id')})
        if pid and aid:
            add_edge(pid, aid, 'OWNS_ACCOUNT')

    # Companies
    for r in mongo.db.get_collection('ref_companies').find({}, {'_id': 0}).limit(limit):
        cid = r.get('company_id') or r.get('id')
        cname = r.get('company_name') or r.get('name') or cid
        if cid:
            add_node(cid, cname, 'Organization', {'cin': r.get('cin'), 'status': r.get('status'), 'industry': r.get('industry')})

    # Directors — link person → company
    for r in mongo.db.get_collection('ref_directors').find({}, {'_id': 0}).limit(limit):
        pid = r.get('person_id')
        cid = r.get('company_id')
        role = r.get('role') or 'DIRECTOR_OF'
        if pid and cid:
            add_edge(pid, cid, role)

    # Vehicles
    for r in mongo.db.get_collection('ref_vehicles').find({}, {'_id': 0}).limit(limit):
        vid = r.get('vehicle_id') or r.get('id')
        plate = r.get('registration_number') or r.get('plate') or vid
        pid = r.get('owner_id') or r.get('person_id')
        if vid:
            add_node(vid, plate, 'Vehicle', {'make': r.get('make'), 'model': r.get('model'), 'color': r.get('color')})
        if pid and vid:
            add_edge(pid, vid, 'OWNS_VEHICLE')

    # Locations — referenced by accounts
    for r in mongo.db.get_collection('ref_locations').find({}, {'_id': 0}).limit(limit):
        lid = r.get('location_id') or r.get('id')
        lname = r.get('name') or r.get('address') or lid
        if lid:
            add_node(lid, lname, 'Location', {'lat': r.get('latitude'), 'lon': r.get('longitude'), 'type': r.get('location_type')})

    total_nodes = len(nodes)
    total_edges = len(edges)
    return {
        'nodes': list(nodes.values()),
        'edges': edges,
        'stats': {
            'nodes': total_nodes,
            'edges': total_edges,
            'persons': sum(1 for n in nodes.values() if n['type'] == 'Person'),
            'accounts': sum(1 for n in nodes.values() if n['type'] == 'Account'),
            'organizations': sum(1 for n in nodes.values() if n['type'] == 'Organization'),
            'vehicles': sum(1 for n in nodes.values() if n['type'] == 'Vehicle'),
            'locations': sum(1 for n in nodes.values() if n['type'] == 'Location'),
        }
    }
