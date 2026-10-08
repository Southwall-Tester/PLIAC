/* Semantic visual encoding. Group order is taken from the full source, never a filtered view. */
(() => {
  const hues=['#0072b2','#b87600','#007f73','#8051a5','#b14975','#bc5534','#537e32','#43599b','#795548','#318a9d','#a74738','#6a6c30','#915f9a','#486973'];
  const mix=(hex,amount)=>'#'+hex.slice(1).match(/../g).map(h=>Math.round(parseInt(h,16)*(1-amount)+255*amount).toString(16).padStart(2,'0')).join('');
  const family=(index,role='concept')=>index<0?'#8c9ba7':mix(hues[index%hues.length],role==='concept'?.25:role==='section'?.12:0);
  const size=(depth,kind='chapter')=>kind==='concept'?12:[42,32,26,22,19,17,15][Math.min(6,Math.max(0,depth))];
  function documentFamilies(structure,memberships){
    const byId=new Map(structure.map(n=>[n.id,n]));
    const roots=structure.filter(n=>!n.parent_id),families=[];
    // A source can have one wrapper title above the actual chapter families.
    for(const root of roots){let parent=root,children=structure.filter(n=>n.parent_id===parent.id),seen=new Set();
      while(children.length===1&&children[0].kind==='chapter'&&!seen.has(children[0].id)){
        seen.add(children[0].id);const next=structure.filter(n=>n.parent_id===children[0].id);
        if(!next.length)break;parent=children[0];children=next;
      }
      const chapters=children.filter(n=>n.kind==='chapter');
      if(chapters.length)families.push(...chapters);else families.push(root);
    }
    const index=new Map(families.map((f,i)=>[f.id,i]));
    function owner(id){let current=byId.get(id),seen=new Set();while(current&&!seen.has(current.id)){if(index.has(current.id))return current;seen.add(current.id);current=byId.get(current.parent_id);}return null;}
    function depth(id){let current=byId.get(id),d=0,seen=new Set();while(current?.parent_id&&!seen.has(current.id)){seen.add(current.id);d++;current=byId.get(current.parent_id);}return d;}
    const conceptOwners=new Map();
    // Memberships already follow source evidence order; resolve the first owner once.
    for(const m of memberships)if(!conceptOwners.has(m.node_id)){const group=owner(m.parent_id);if(group)conceptOwners.set(m.node_id,group);}
    function encoding(id){const container=byId.get(id),group=container?owner(id):conceptOwners.get(id),i=group?index.get(group.id):-1;
      return {family_id:group?.id||null,family_title:group?.title||'',depth:container?depth(id):null,kind:container?.kind||'concept',fill:container&&!container.parent_id?'#8c9ba7':family(i,container?(depth(id)>1?'section':'chapter'):'concept'),size:size(container?depth(id):0,container?'chapter':'concept')};
    }
    return {families:families.map((f,i)=>({...f,color:family(i)})),encoding};
  }
  window.GraphEncoding={family,size,documentFamilies};
})();
