export const RELATION_LABELS={
  CALLED:'called',CONTACTED:'contacted',MET:'met',ASSOCIATED_WITH:'connected to',
  CHILD_OF:'child of',SIBLING_OF:'sibling of',SPOUSE_OF:'spouse of',
  POSTED_AT:'posted at',WORKS_FOR:'works for',MEMBER_OF:'member of',
  RESIDES_IN:'lives in',LOCATED_IN:'located in',USES:'uses',OWNS:'owns',
  REGISTERED_TO:'registered to',TRANSFERRED_TO:'transferred to',
  COMMUNICATED_WITH:'communicated with',MESSAGED:'messaged',
  PRESENT_AT:'present at',VISITED:'visited',PAID:'paid',
  RECEIVED_FROM:'received from',OPERATES:'operates',
  ACCUSED_IN:'accused in',INVOLVED_IN:'involved in',
};

// Preserve every character while giving long names enough room inside a node.
// Explicit line breaks keep the canvas label and the computed node size in sync.
export function graphNode(node,measureText=text=>text.length*7.4){
  const label=String(node.label??node.id),words=label.trim().split(/\s+/),lines=[];
  let line='';
  for(const word of words){
    const parts=word.match(/.{1,28}/gu)||[''];
    for(const part of parts){
      if(line&&line.length+part.length+1>28){lines.push(line);line='';}
      line+=(line?' ':'')+part;
      if(parts.length>1){lines.push(line);line='';}
    }
  }
  if(line||!lines.length)lines.push(line);
  const labelWidth=Math.max(104,...lines.map(measureText))+2;
  return {...node,displayLabel:lines.join('\n'),labelWidth,
    nodeWidth:labelWidth+32,nodeHeight:Math.max(58,lines.length*20+28)};
}

export function graphStyles(theme){
  const dark=theme==='dark',ink=dark?'#e3eaf4':'#243449',line=dark?'#85accf':'#507798';
  return [
    {selector:'node',style:{shape:'roundrectangle','background-color':dark?'#13233a':'#ffffff',
      'border-color':'data(color)','border-width':2.5,width:'data(nodeWidth)',height:'data(nodeHeight)',
      label:'data(displayLabel)','font-size':13,'font-weight':500,'font-family':'Arial',color:ink,
      'text-valign':'center','text-halign':'center','text-wrap':'wrap','text-max-width':'data(labelWidth)',
      'line-height':1.45,'overlay-opacity':0}},
    {selector:'edge',style:{width:2.4,'line-color':line,'target-arrow-color':line,
      'target-arrow-shape':'triangle','arrow-scale':1.2,'curve-style':'bezier',
      'control-point-step-size':65,label:'data(shortLabel)','font-size':12,'font-weight':500,
      'font-family':'Arial','text-rotation':'autorotate','text-margin-y':-12,color:ink,
      'text-background-color':dark?'#13233a':'#ffffff','text-background-opacity':1,
      'text-background-padding':5,'text-background-shape':'roundrectangle',
      'text-border-color':dark?'#31465e':'#d4e0eb','text-border-width':1,'text-border-opacity':1,
      'min-zoomed-font-size':0,'overlay-padding':10,'overlay-opacity':0}},
    {selector:'node:selected',style:{'border-width':4,'overlay-opacity':.12,'overlay-color':'#2453d4'}},
    {selector:'edge:selected',style:{width:3.5,'line-color':dark?'#8dbaff':'#2453d4',
      'target-arrow-color':dark?'#8dbaff':'#2453d4'}},
  ];
}

// A wide, measured ring keeps connected records in one balanced viewport.
// Every pair is spaced using its real label box, so long names cannot collide.
// Unconnected records occupy a separate grid below the network.
export function graphPositions(nodes,edges,aspect=1.8){
  const connectedIds=new Set(edges.flatMap(e=>[e.source,e.target]));
  const connected=nodes.filter(n=>connectedIds.has(n.id));
  const isolates=nodes.filter(n=>!connectedIds.has(n.id));
  const positions={},ratio=Math.max(1,Math.min(2.5,aspect));
  const width=n=>n.nodeWidth||136,height=n=>n.nodeHeight||58;
  const maxWidth=Math.max(136,...nodes.map(width)),maxHeight=Math.max(58,...nodes.map(height));
  let gridTop=40;
  if(connected.length){
    const points=connected.map((n,i)=>({...n,x:Math.cos(-Math.PI/2+i*2*Math.PI/connected.length)*ratio,
      y:Math.sin(-Math.PI/2+i*2*Math.PI/connected.length)}));
    let scale=connected.length>1?90:0;
    for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++){
      const a=points[i],b=points[j],dx=Math.abs(a.x-b.x),dy=Math.abs(a.y-b.y);
      const horizontal=dx>1e-9?((width(a)+width(b))/2+36)/dx:Infinity;
      const vertical=dy>1e-9?((height(a)+height(b))/2+28)/dy:Infinity;
      scale=Math.max(scale,Math.min(horizontal,vertical));
    }
    for(const n of points)positions[n.id]={x:n.x*scale+ratio*scale+maxWidth/2+40,
      y:n.y*scale+scale+maxHeight/2+40};
    gridTop=2*scale+maxHeight+170;
  }
  const columns=Math.min(5,Math.ceil(Math.sqrt(Math.max(isolates.length,1))));
  isolates.forEach((n,i)=>{positions[n.id]={x:40+maxWidth/2+(i%columns)*(maxWidth+60),
    y:gridTop+maxHeight/2+Math.floor(i/columns)*(maxHeight+55)};});
  return positions;
}

// Start with evidenced connections when present. Isolates remain available in
// All entities, without forcing hundreds of unrelated nodes into the first fit.
export function visibleGraph(network,{connectedOnly=false,search='',type='All Entities'}={}){
  const connected=new Set(network.edges.flatMap(e=>[e.source,e.target]));
  const nodes=network.nodes.filter(n=>(!connectedOnly||connected.has(n.id))&&
    (type==='All Entities'||n.type===type)&&String(n.label??n.id).toLowerCase().includes(search.toLowerCase()));
  const ids=new Set(nodes.map(n=>n.id));
  const edges=network.edges.filter(e=>ids.has(e.source)&&ids.has(e.target));
  return {nodes,edges,connections:graphEdges(edges),hiddenCount:network.nodes.length-nodes.length};
}

// One visual edge per directed relationship, retaining every source statement.
export function graphEdges(edges){
  const groups=new Map();
  for(const edge of edges){
    const type=String(edge.type||'RELATED_TO').trim().toUpperCase();
    const key=JSON.stringify([edge.source,edge.target,type]);
    if(!groups.has(key))groups.set(key,{...edge,type,id:key,evidence:[]});
    groups.get(key).evidence.push(edge);
  }
  return [...groups.values()].map(edge=>({...edge,occurrenceCount:edge.evidence.length,
    shortLabel:(RELATION_LABELS[edge.type]||edge.type.toLowerCase().replaceAll('_',' '))+
      (edge.evidence.length>1?` ×${edge.evidence.length}`:'')}));
}
