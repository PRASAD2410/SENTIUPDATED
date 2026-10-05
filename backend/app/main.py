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

app=FastAPI(title='SentinelGraph API',version='0.2.0')
app.add_middleware(CORSMiddleware,allow_origins=[os.getenv('FRONTEND_ORIGIN','http://localhost:5173')],allow_methods=['*'],allow_headers=['*'])
# Start every local session with an empty case. Findings are created only from
# the reports and documents the investigator submits in that session.
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
@app.get('/api/cases/{case_id}/workspace')
def case_workspace(case_id:str):
 try:
  entities=mongo.entities_for_case(case_id); relationships=mongo.relationships_for_case(case_id); documents=mongo.documents_for_case(case_id)
 except Exception: raise HTTPException(503,'Case records are unavailable. Check MongoDB.')
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
  case_leads.append({'severity':'medium','title':f"Reported connections: {e['label']}",'entity':e['label'],'entityId':e['id'],'reason':f"Linked to {e['connections']} distinct entities by extracted source statements. Review the context and alternative explanations.",'rule':'Three or more distinct connections','sources':sorted({r['reportId'] for r in supporting}),'evidence':supporting})
 return {'network':{'nodes':entities,'edges':valid},'documents':documents,'analytics':rankings,'leads':case_leads,
         'overview':{'nodes':len(entities),'edges':len(valid),'reports':len(documents),'leads':len(case_leads)},'truncated':any(len(items)>=1000 for items in (entities,relationships,documents))}
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
@app.post('/api/ingest')
def ingest(payload:Ingest): return process(payload.text,payload.title,'Investigator submitted',payload.date,case_id=payload.case_id)
@app.post('/api/upload')
async def upload(file:UploadFile=File(...),case_id:str=Form('default'),source_type:str=Form('Other'),investigation_type:str=Form('Criminal Network Analysis')):
 import re
 if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',case_id): raise HTTPException(422,'Case ID must contain 1-100 letters, digits, underscores or hyphens.')
 content=await file.read()
 if len(content)>10*1024*1024: raise HTTPException(413,'Maximum file size is 10 MB.')
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
@app.post('/api/assistant')
def assistant(payload:Question):
 provider=get_llm_provider(); question=payload.question.lower()
 try: workspace=case_workspace(payload.case_id)
 except HTTPException: raise HTTPException(503,'The selected case is unavailable.')
 persons=[n['label'] for n in workspace['network']['nodes'] if n['type']=='Person']
 case_reports=[r for r in reports if r.get('caseId','default')==payload.case_id]
 context={'entities':workspace['analytics'][:20],'leads':workspace['leads'][:12],'relationships':workspace['network']['edges'][:100],'reports':[{'id':r['id'],'title':r['title'],'date':r['date'],'source':r['source'],'full_text':r['text'][:250000]} for r in case_reports[-3:]]}
 if any(term in question for term in ('culprit','criminal','guilty','guilt')):
  named=', '.join(persons) if persons else 'no people were confidently extracted'
  answer=f"I cannot identify ‘culprits’ or determine guilt from these records. The people explicitly named in the current uploaded sources are: {named}. Their presence in a report or graph is a reported association that requires independent verification and any legal outcome must come from the court record."
  return {'answer':answer,'disclaimer':'This response summarizes reported data and potential leads only. It is not proof of criminality.'}
 if provider.available:
  answer=provider.generate(f'''You are SentinelGraph's document-grounded case assistant. Use the FULL TEXT of the uploaded records in the case context to answer the user's question directly and completely. Answer questions about all named people, identifiers, phone numbers, vehicles, locations, dates, FIR/case details, stated events, and stated court outcomes when they appear in the record. Cite the relevant report ID. Do not rely only on the graph summary.

Never invent a fact. If a phone number or requested fact is not in the uploaded record, say it is not stated. Do not call anyone a criminal or guilty: use “named in the record”, “reported”, and “requires verification”.\nCASE CONTEXT:{context}\nQUESTION:{payload.question}''') or 'Gemini is temporarily unavailable. Please try again.'
 else: answer=f"The selected case contains {workspace['overview']['nodes']} entities, {workspace['overview']['edges']} relationships and {workspace['overview']['reports']} source files. The case assistant is not configured."
 return {'answer':answer,'disclaimer':'This response summarizes reported data and potential leads only. It is not proof of criminality.'}
