/* Edge geometry and deterministic static-layout contracts; no browser/server required. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const context={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/network-layout.js'),'utf8'),context);
const route=edges=>JSON.parse(JSON.stringify(context.window.CourseNetwork.routeEdges(edges)));
const edge=(id,source='a',target='b',extra={})=>({id,source,target,...extra});
const physicalOffsets=edges=>edges.map(item=>item.style.curveOffset*(item.source==='a'?1:-1));

const source=[edge('semantic','a','b',{data:{type:'prerequisite',reason:'source quote'},style:{endArrow:true,lineDash:[5,4],opacity:.35}}),
  edge('hierarchy','a','b',{data:{type:'hierarchy'},style:{endArrow:true}}),edge('reverse','b','a',{data:{type:'related'},style:{endArrow:false}})];
const before=JSON.stringify(source),routed=route(source);
assert.equal(JSON.stringify(source),before,'input edges/styles remain unchanged');
assert.deepEqual(routed.map(item=>[item.id,item.source,item.target,item.data]),source.map(item=>[item.id,item.source,item.target,item.data]));
assert.equal(routed[0].style.endArrow,true);
assert.deepEqual(routed[0].style.lineDash,[5,4]);
assert.equal(routed[0].style.opacity,.35);
assert.equal(routed[2].style.endArrow,false);
assert.deepEqual(physicalOffsets(routed),[0,-48,48]);
assert.ok(routed.every(item=>item.type==='quadratic'));

const forward=route([edge('1'),edge('2')]);
assert.deepEqual(physicalOffsets(forward),[24,-24]);
const reverse=route([edge('1'),edge('2','b','a')]);
assert.deepEqual(reverse.map(item=>item.style.curveOffset),[24,24]);
assert.deepEqual(physicalOffsets(reverse),[24,-24],'reversing edge direction reverses the curve normal');
for(let count=2;count<=12;count++){
  const group=route(Array.from({length:count},(_,i)=>edge(String(i),i%3?'a':'b',i%3?'b':'a')));
  const offsets=physicalOffsets(group);
  assert.equal(new Set(offsets).size,count,'opposite directions still occupy unique physical paths');
  assert.equal(offsets.includes(0),count%2===1,'only odd bundles have a straight center');
  assert.equal(offsets.reduce((sum,value)=>sum+value,0),0,'bundle remains centered');
}

const single=route([routed[1]])[0];
assert.equal(single.type,'line');
assert.equal(single.style.curveOffset,0,'removing parallel edges resets curvature');
assert.equal(single.style.endArrow,true);
assert.equal(route([edge('custom','a','b',{style:{curveOffset:80}})])[0].style.curveOffset,0);
assert.deepEqual(route([]),[]);

const delimiterIds=route([edge('1','a-b','c'),edge('2','a','b-c'),edge('3','a|b','c'),edge('4','a','b|c')]);
assert.ok(delimiterIds.every(item=>item.type==='line'),'endpoint IDs containing separators never collide');
assert.deepEqual(delimiterIds.map(item=>item.id),['1','2','3','4'],'output keeps input ordering');
const loops=route(Array.from({length:10},(_,i)=>edge('loop'+i,'a','a',{style:{endArrow:true}})));
assert.equal(new Set(loops.slice(0,8).map(item=>item.style.loopPlacement)).size,8);
assert.deepEqual(loops.slice(8).map(item=>[item.style.loopPlacement,item.style.loopDist]),[['top',74],['top-right',74]]);
assert.ok(loops.every(item=>item.type==='quadratic'&&item.style.endArrow));

const large=Array.from({length:12000},(_,i)=>edge(String(i),'node'+i,'node'+(i+1)));
const start=performance.now(),largeResult=route(large),elapsed=performance.now()-start;
assert.equal(largeResult.length,large.length);
assert.ok(largeResult.every(item=>item.type==='line'&&item.style.curveOffset===0));

// Two parallel springs both act on the same endpoints. Index zero is valid,
// and the known first step preserves the original force equation and damping.
const Force=context.window.CourseNetwork,force=new Force(),pair=[{id:'a'},{id:'b'}];
force.gravity=0;force.setData(pair,[edge('spring-1'),edge('spring-2'),edge('self','a','a')]);
force.move('a',0,0);force.move('b',100,0);force.step();
const close=(actual,expected)=>assert.ok(Math.abs(actual-expected)<1e-10,`${actual} != ${expected}`);
close(force.points.get('a').x,-1.7252);close(force.points.get('b').x,101.7252);
close(force.points.get('a').y,0);close(force.points.get('b').y,0);

// Filtering retains the original point objects and coordinates, while edges
// referencing a hidden endpoint cannot index into the current force buffers.
const savedA=force.points.get('a'),savedB=force.points.get('b'),savedPositions=JSON.stringify(force.positions());
force.setData([pair[0]],[edge('hidden-target')]);
assert.equal(force.nodes[0],savedA);assert.equal(force.points.get('b'),savedB);
assert.equal(force.edges.length,0);assert.equal(force.edgeIndices.length,0);
force.setData(pair,[edge('restored')]);
assert.equal(JSON.stringify(force.positions()),savedPositions,'filter/restore never triggers settling or resets coordinates');
assert.deepEqual(Array.from(force.edgeIndices),[0,1]);
assert.equal(force.forceX.length,2);assert.equal(force.forceY.length,2);
force.move('a',12,34);assert.equal(force.points.get('a'),savedA);
assert.deepEqual([savedA.x,savedA.y,savedA.vx,savedA.vy],[12,34,0,0]);
console.log(JSON.stringify({passed:true,checks:10,independent_edges:large.length,elapsed_ms:Math.round(elapsed*100)/100}));
