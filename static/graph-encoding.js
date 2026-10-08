/* Semantic visual encoding. Group order is taken from the full source, never a filtered view. */
(() => {
  // Clear chapter colors with moderated saturation; connections stay visually secondary.
  const hues=['#6bcaa4','#e99bb6','#af97da','#e9ca76','#7bc9d2','#a8cf80','#eaa597','#9fabe0','#d597c6','#72c3b2','#e7b780','#c5d184','#c59cdb','#86c1d9'];
  // Common ancestors spanning multiple families have no categorical color.
  // A family's parent and descendants share one fill; depth changes size only.
  const rootFill='#c4c8cc';
  const family=index=>index<0?rootFill:hues[index%hues.length];
  const outline=hex=>'#'+hex.slice(1).match(/../g).map(h=>Math.round(parseInt(h,16)*.78).toString(16).padStart(2,'0')).join('');
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
    const descendants=new Map();
    for(const group of families){let current=group,seen=new Set();while(current&&!seen.has(current.id)){seen.add(current.id);if(!descendants.has(current.id))descendants.set(current.id,new Set());descendants.get(current.id).add(group.id);current=byId.get(current.parent_id);}}
    function owner(id){
      let current=byId.get(id),seen=new Set();
      while(current&&!seen.has(current.id)){if(index.has(current.id))return current;seen.add(current.id);current=byId.get(current.parent_id);}
      // A wrapper above one family belongs to that family. A shared wrapper
      // above several families stays neutral instead of borrowing one color.
      const below=descendants.get(id);return below?.size===1?byId.get([...below][0]):null;
    }
    function depth(id){let current=byId.get(id),d=0,seen=new Set();while(current?.parent_id&&!seen.has(current.id)){seen.add(current.id);d++;current=byId.get(current.parent_id);}return d;}
    const conceptOwners=new Map();
    // Memberships already follow source evidence order; resolve the first owner once.
    for(const m of memberships)if(!conceptOwners.has(m.node_id)){const group=owner(m.parent_id);if(group)conceptOwners.set(m.node_id,group);}
    function encoding(id){const container=byId.get(id),group=container?owner(id):conceptOwners.get(id),i=group?index.get(group.id):-1;
      return {family_id:group?.id||null,family_title:group?.title||'',depth:container?depth(id):null,kind:container?.kind||'concept',fill:family(i),size:size(container?depth(id):0,container?'chapter':'concept')};
    }
    return {families:families.map((f,i)=>({...f,color:family(i)})),encoding};
  }
  function collapseTextSections(hierarchy){
    const nodes=hierarchy?.nodes||[],byId=new Map(nodes.map(n=>[n.id,n]));
    const removed=new Set(nodes.filter(n=>n.kind==='page').map(n=>n.id));
    const parent=id=>{const seen=new Set();while(removed.has(id)&&!seen.has(id)){seen.add(id);id=byId.get(id)?.parent_id;}return id;};
    const seen=new Set(),memberships=[];
    for(const member of hierarchy?.memberships||[]){const source=parent(member.source),key=JSON.stringify([source,member.target]);if(source&&!seen.has(key)){seen.add(key);memberships.push({...member,source});}}
    return {...hierarchy,nodes:nodes.filter(n=>!removed.has(n.id)).map(n=>({...n,parent_id:parent(n.parent_id)})),memberships};
  }
  window.GraphEncoding={family,size,documentFamilies,rootFill,outline,collapseTextSections};
})();
