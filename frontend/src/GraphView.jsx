import React,{useEffect,useMemo,useRef,useState} from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import {Search,LayoutGrid,RotateCcw,Maximize,Plus,Minus,Network,X,FileText} from 'lucide-react';
import {COLORS,API,Empty} from './shared';
import {graphNode,graphStyles,graphPositions,visibleGraph} from './graphData';
import './GraphView.css';

// Keep the first view readable instead of fitting hundreds of isolated nodes.
// FIT VIEW explicitly includes every displayed entity.
function fitReadable(cy){
  if(!cy||cy.destroyed()||!cy.nodes().length)return;
  cy.resize();
  const connected=cy.nodes().filter(n=>n.degree()>0);
  cy.fit(connected.length?connected.union(cy.edges()):cy.nodes().slice(0,15),55);
  const level=connected.length?Math.min(1.1,cy.zoom()):Math.max(.7,Math.min(1.1,cy.zoom()));
  cy.zoom({level,renderedPosition:{x:cy.width()/2,y:cy.height()/2}});
}

export default function GraphView({data,current,theme,loading=false,error=''}){
  const [showAll,setShowAll]=useState(false),[search,setSearch]=useState('');
  const [type,setType]=useState('All Entities'),[grid,setGrid]=useState(true);
  const [selected,setSelected]=useState(null),[tab,setTab]=useState('Overview'),[zoom,setZoom]=useState(1);
  const [aspect,setAspect]=useState(1.8);
  const cyRef=useRef(null),canvasRef=useRef(null),nodesRef=useRef(data.network.nodes);
  nodesRef.current=data.network.nodes;
  const hasConnections=data.network.edges.length>0,connectedOnly=hasConnections&&!showAll;

  useEffect(()=>{setSelected(null);setSearch('');setType('All Entities');setShowAll(false);},[current.id]);
  useEffect(()=>{
    const observer=new ResizeObserver(()=>{
      const canvas=canvasRef.current;
      if(canvas?.clientWidth&&canvas?.clientHeight)setAspect(canvas.clientWidth/canvas.clientHeight);
      const cy=cyRef.current;
      if(cy&&!cy.destroyed())fitReadable(cy);
    });
    if(canvasRef.current)observer.observe(canvasRef.current);
    return()=>observer.disconnect();
  },[]);

  const {nodes,edges,connections,hiddenCount}=useMemo(()=>
    visibleGraph(data.network,{connectedOnly,search,type}),[data.network,connectedOnly,search,type]);
  const elements=useMemo(()=>{
    const context=document.createElement('canvas').getContext('2d');
    if(context)context.font='500 13px Arial';
    const measure=context?text=>context.measureText(text).width:undefined;
    return [
      ...nodes.map(n=>({data:{...graphNode(n,measure),color:COLORS[n.type]||COLORS.Event}})),
      ...connections.map(e=>({data:{...e,id:'edge-'+e.id}})),
    ];
  },[nodes,connections]);
  const layout=useMemo(()=>({name:'preset',animate:false,fit:false,
    positions:graphPositions(elements.slice(0,nodes.length).map(e=>e.data),connections,aspect),
  }),[elements,aspect]);
  const stylesheet=useMemo(()=>graphStyles(theme),[theme]);

  const initialize=cy=>{
    if(cyRef.current===cy)return;
    cyRef.current=cy;
    cy.on('tap','node',e=>{
      setSelected(nodesRef.current.find(n=>n.id===e.target.id()));
      setTab('Overview');
    });
    cy.on('zoom',()=>setZoom(cy.zoom()));
    cy.on('layoutstop',()=>fitReadable(cy));
    fitReadable(cy);
    setZoom(cy.zoom());
  };
  const fit=()=>{
    const cy=cyRef.current;
    if(cy&&!cy.destroyed()){cy.resize();cy.fit(cy.elements(),75);}
  };
  const changeZoom=factor=>{
    const cy=cyRef.current;
    if(cy&&!cy.destroyed())cy.zoom({level:cy.zoom()*factor,renderedPosition:{x:cy.width()/2,y:cy.height()/2}});
  };
  const reset=()=>{
    setSearch('');setType('All Entities');setSelected(null);setShowAll(false);
    const cy=cyRef.current;
    if(cy&&!cy.destroyed())cy.layout(layout).run();
  };
  const links=selected?data.network.edges.filter(e=>e.source===selected.id||e.target===selected.id):[];
  const sources=data.documents.filter(d=>links.some(e=>e.documentId===d.documentId)||selected?.reportIds?.includes(d.reportId));
  const noEdgesMessage=hasConnections?
    'No connections match these filters. Clear the search or change the entity filter.':
    'No relationships were returned for this case. Reanalyze the source files in Input to update extraction.';
  const renderSummary=loading?'Loading case graph…':error?'Case graph unavailable. '+error:
    `${nodes.length} entities · ${connections.length} connections / ${edges.length} source statements`;

  return <div className="graph-page">
    <div className="graph-toolbar">
      <span className="eyebrow">{current.id} / ALL SOURCES</span>
      <div className="graph-search"><Search size={15}/>
        <input aria-label="Search graph entities" placeholder="Search entities…" value={search} onChange={e=>setSearch(e.target.value)}/>
        {search&&nodes.length>0&&<div className="graph-search-results panel">{nodes.slice(0,5).map(n=>
          <button key={n.id} onClick={()=>{setSelected(n);setTab('Overview');setSearch('');}}>{n.label}<small>{n.type}</small></button>
        )}</div>}
      </div>
      <select aria-label="Filter entity type" value={type} onChange={e=>setType(e.target.value)}>
        <option>All Entities</option>{[...new Set(data.network.nodes.map(n=>n.type))].map(t=><option key={t}>{t}</option>)}
      </select>
      <button className={connectedOnly?'pressed':''} disabled={!hasConnections||loading||!!error} onClick={()=>setShowAll(!showAll)} aria-pressed={connectedOnly}
        title={connectedOnly?'Show all entities, including those without relationships':'Focus on entities with relationships'}>
        {connectedOnly?'CONNECTED ONLY':'ALL ENTITIES'}
      </button>
      <button className={'icon-button '+(grid?'pressed':'')} aria-label="Toggle graph grid" onClick={()=>setGrid(!grid)}><LayoutGrid size={17}/></button>
      <button className="icon-button" aria-label="Reset graph" onClick={reset}><RotateCcw size={17}/></button>
      <button onClick={fit}><Maximize size={14}/> FIT VIEW</button>
    </div>
    <div className="graph-body">
      <div ref={canvasRef} className={'graph-canvas '+(grid?'grid-background':'')}>
        <div className="graph-caption mono" role="status" aria-live="polite">
          <span>{renderSummary}</span>
          {!loading&&!error&&connectedOnly&&hiddenCount>0&&!search&&type==='All Entities'&&
            <p className="graph-view-note">{hiddenCount} entities without connections are available in All Entities.</p>}
          {!loading&&!error&&nodes.length>0&&edges.length===0&&<p className="isolated-note">{noEdgesMessage}</p>}
        </div>
        {!loading&&!error&&nodes.length?<CytoscapeComponent elements={elements} cy={initialize}
          style={{width:'100%',height:'100%'}} layout={layout} minZoom={.08} maxZoom={3}
          wheelSensitivity={.18} stylesheet={stylesheet}/>:<Empty icon={Network}
          title={loading?'Loading graph':error?'Case data unavailable':data.network.nodes.length?'No matching entities':'No graph yet'}
          description={loading?'Fetching the selected case and its relationships.':error?'The graph could not be loaded. Retry the connection above.':data.network.nodes.length?'Adjust your search, entity filter, or Connected Only view.':'Upload source records to map entities and their evidenced relationships.'}/>}
        <div className="zoom-controls">
          <button aria-label="Zoom in" onClick={()=>changeZoom(1.2)}><Plus size={17}/></button>
          <span className="mono">{Math.round(zoom*100)}%</span>
          <button aria-label="Zoom out" onClick={()=>changeZoom(1/1.2)}><Minus size={17}/></button>
        </div>
      </div>
      {selected&&!loading&&!error&&<aside className="entity-profile">
        <div className="between"><p className="eyebrow">ENTITY PROFILE</p><button className="icon-button" onClick={()=>setSelected(null)} aria-label="Close entity profile"><X size={16}/></button></div>
        <div className="entity-identity"><div style={{color:COLORS[selected.type]}}><Network size={30}/></div><h2>{selected.label}</h2><p className="micro">{selected.type?.toUpperCase()} / {selected.id.slice(0,16)}</p></div>
        <div className="profile-tabs">{['Overview','Connections','Activity','Documents'].map(t=><button className={tab===t?'active':''} key={t} onClick={()=>setTab(t)}>{t}</button>)}</div>
        {tab==='Overview'&&<>
          <p className="eyebrow">IDENTITY SUMMARY</p>
          <div className="profile-fact"><span>Entity type</span><strong>{selected.type}</strong></div>
          <div className="profile-fact"><span>Connected entities</span><strong>{new Set(links.map(e=>e.source===selected.id?e.target:e.source)).size}</strong></div>
          <div className="profile-fact"><span>Extracted relationships</span><strong>{links.length}</strong></div>
          <div className="insight-box"><p className="eyebrow">ANALYTICAL INSIGHT</p><p>This entity appears in the selected case's extracted records. Inspect connections and their source evidence before drawing conclusions.</p></div>
          <p className="muted small">Same-name mentions are grouped for display; identity is unverified. Source statements require human review.</p>
        </>}
        {(tab==='Connections'||tab==='Activity')&&<>{links.length?links.map(e=>
          <div className="connection-item" key={e.id}>
            <p className="eyebrow">{String(e.type).replaceAll('_',' ')}</p>
            <strong>{data.network.nodes.find(n=>n.id===(e.source===selected.id?e.target:e.source))?.label}</strong>
            <p className="small">{e.evidenceText}</p><small className="muted">{e.origin||'Extracted'} · Review pending</small>
          </div>
        ):<Empty title="No relationships extracted" description="This entity has no evidenced connections yet."/>}</>}
        {tab==='Documents'&&<>{sources.length?sources.map(d=>
          <a className="document-link" key={d.documentId} href={`${API}/api/cases/${encodeURIComponent(current.id)}/documents/${encodeURIComponent(d.documentId)}/download`}><FileText size={16}/>{d.filename}</a>
        ):<Empty title="No linked original files" description="Pasted notes may have no downloadable source file."/>}</>}
      </aside>}
    </div>
    <div className="graph-legend">{['Person','Organization','Phone','Account','Vehicle','Location'].map(t=><span key={t}><i style={{background:COLORS[t]}}/>{t.toUpperCase()}</span>)}<small>SCROLL TO ZOOM · DRAG TO PAN</small></div>
  </div>;
}
