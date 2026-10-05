import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import cytoscape from 'cytoscape';
// Import the pure ES module without changing the app's package/module settings.
const source=await readFile(new URL('./graphData.js',import.meta.url),'utf8');
const {graphEdges,graphNode,graphStyles,graphPositions,visibleGraph}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('Repeated statements share a short edge label and retain all evidence',()=>{
  const edges=graphEdges([
    {id:'1',source:'a',target:'b',type:'CALLED',reportId:'r1'},
    {id:'2',source:'a',target:'b',type:'CALLED',reportId:'r2'},
    {id:'3',source:'a',target:'b',type:'MET',reportId:'r3'},
    {id:'4',source:'b',target:'a',type:'CALLED',reportId:'r4'},
  ]);
  assert.equal(edges.length,3);
  assert.equal(edges[0].shortLabel,'called ×2');
  assert.deepEqual(edges[0].evidence.map(e=>e.reportId),['r1','r2']);
  assert.equal(edges[1].shortLabel,'met');
  assert.equal(edges[2].shortLabel,'called');
});
test('Connected view retains every call but excludes unrelated isolated entities',()=>{
  const network={nodes:[{id:'a',label:'9000010001',type:'Phone'},{id:'b',label:'9000010002',type:'Phone'},
    ...Array.from({length:239},(_,i)=>({id:'isolated-'+i,label:'Other '+i,type:'Person'}))],
    edges:[{source:'a',target:'b',type:'CALLED'},{source:'a',target:'b',type:'CALLED'}]};
  const focused=visibleGraph(network,{connectedOnly:true});
  assert.equal(focused.nodes.length,2);
  assert.equal(focused.edges.length,2);
  assert.equal(focused.connections[0].shortLabel,'called ×2');
  assert.equal(focused.hiddenCount,239);
  assert.equal(visibleGraph(network).nodes.length,241);
  assert.equal(visibleGraph(network,{search:'9000010001'}).edges.length,0);
});
test('Node dimensions fit measured full labels, including wrapped long names',()=>{
  const label='THE SUPREME COURT OF INDIA INVESTIGATION DEPARTMENT';
  const node=graphNode({id:'court',label},text=>text.length*12);
  assert.equal(node.label,label);
  assert.equal(node.displayLabel.split('\n').join(' '),label);
  assert.ok(node.nodeWidth>=Math.max(...node.displayLabel.split('\n').map(s=>s.length*12))+32);
  assert.ok(node.nodeHeight>=node.displayLabel.split('\n').length*20+28);
  const token='ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890';
  assert.equal(graphNode({id:'long',label:token}).displayLabel.replaceAll('\n',''),token);
});
test('Canvas styles render full labels inside nodes and prominent labelled arrows in both themes',()=>{
  for(const theme of ['light','dark']){
    const nodes=['9000010001','9000010002'].map((label,i)=>({data:{...graphNode({id:'n'+i,label,type:'Phone'}),color:'#138468'}}));
    const edges=graphEdges([{source:'n0',target:'n1',type:'CALLED'}]).map(e=>({data:{...e,id:'edge-'+e.id}}));
    const cy=cytoscape({headless:true,styleEnabled:true,elements:[...nodes,...edges],style:graphStyles(theme)});
    assert.equal(cy.nodes()[0].style('label'),'9000010001');
    assert.equal(cy.nodes()[0].style('text-valign'),'center');
    assert.ok(cy.nodes()[0].width()>=136);
    assert.ok(cy.nodes()[0].height()>=58);
    assert.equal(cy.edges()[0].style('label'),'called');
    assert.equal(cy.edges()[0].style('target-arrow-shape'),'triangle');
    assert.ok(parseFloat(cy.edges()[0].style('width'))>=2);
    assert.equal(parseFloat(cy.edges()[0].style('min-zoomed-font-size')),0);
    cy.destroy();
  }
});
test('Twelve connected call-log nodes occupy a compact landscape layout without overlapping',()=>{
  const nodes=Array.from({length:12},(_,i)=>graphNode({id:'phone-'+i,label:'900001'+String(i).padStart(4,'0'),type:'Phone'}));
  const edges=Array.from({length:30},(_,i)=>({source:nodes[i%12].id,target:nodes[(i%12+1+Math.floor(i/12))%12].id,type:'CALLED'}));
  const positions=graphPositions(nodes,edges,1.8);
  assert.equal(Object.keys(positions).length,12);
  for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
    const a=nodes[i],b=nodes[j],pa=positions[a.id],pb=positions[b.id];
    const separated=Math.abs(pa.x-pb.x)>=(a.nodeWidth+b.nodeWidth)/2+20||
      Math.abs(pa.y-pb.y)>=(a.nodeHeight+b.nodeHeight)/2+20;
    assert.ok(separated,`${a.id} and ${b.id} overlap`);
  }
  const xs=nodes.map(n=>positions[n.id].x),ys=nodes.map(n=>positions[n.id].y);
  const width=Math.max(...xs)-Math.min(...xs)+Math.max(...nodes.map(n=>n.nodeWidth));
  const height=Math.max(...ys)-Math.min(...ys)+Math.max(...nodes.map(n=>n.nodeHeight));
  assert.ok(width/height>1.5&&width/height<2.5);
  assert.ok(height<600);
  const isolated=graphNode({id:'unlinked',label:'Unlinked record'});
  assert.ok(graphPositions([...nodes,isolated],edges,1.8).unlinked.y>Math.max(...ys)+80);
});
