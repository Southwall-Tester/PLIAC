/* Small deterministic force simulation. Positions belong to the view, not the course. */
(() => {
  class CourseNetwork {
    // G6 5.1.1 bundle geometry, computed once per topology instead of beforeDraw.
    // https://github.com/antvis/G6/blob/5.1.1/packages/g6/src/transforms/process-parallel-edges.ts
    static routeEdges(edges, distance=24) {
      const routes=edges.map(edge=>({...edge,style:{...edge.style}})),groups=new Map();
      const loops=['top','top-right','right','right-bottom','bottom','bottom-left','left','left-top'];
      for(const edge of routes){
        const ordered=String(edge.source)<=String(edge.target);
        const a=ordered?edge.source:edge.target,b=ordered?edge.target:edge.source;
        if(!groups.has(a))groups.set(a,new Map());
        const targets=groups.get(a);
        if(!targets.has(b))targets.set(b,[]);
        targets.get(b).push(edge);
      }
      for(const targets of groups.values())for(const group of targets.values()){
        const count=group.length,source=group[0].source;
        for(let index=0;index<count;index++){
          const edge=group[index];
          if(edge.source===edge.target){
            edge.type='quadratic';
            edge.style.loopPlacement=loops[index%loops.length];
            edge.style.loopDist=50+Math.floor(index/loops.length)*distance;
          }else if(count===1){
            edge.type='line';edge.style.curveOffset=0;
          }else{
            const direction=edge.source===source?1:-1,side=index%2===0?1:-1;
            edge.type='quadratic';
            edge.style.curveOffset=direction*side*(count%2===1?Math.ceil(index/2)*distance*2:Math.floor(index/2)*distance*2+distance);
          }
        }
      }
      return routes;
    }
    constructor() {
      this.points = new Map(); this.nodes = []; this.edges = [];
      this.edgeIndices=new Uint32Array(0);this.forceX=new Float64Array(0);this.forceY=new Float64Array(0);
      this.repulsion = 6500; this.distance = 145; this.gravity = 0.012;
    }
    setData(nodes, edges) {
      this.anchorId=nodes.find(n=>n.data?.layout_anchor)?.id||null;
      this.nodes = nodes.map((n, i) => {
        if (!this.points.has(n.id)) {
          const angle = i * 2.3999632297, radius = 45 * Math.sqrt(i + 1);
          this.points.set(n.id, {id:n.id,x:Math.cos(angle)*radius,y:Math.sin(angle)*radius,vx:0,vy:0});
        }
        return this.points.get(n.id);
      });
      const index=new Map(this.nodes.map((p,i)=>[p.id,i])),pairs=[];
      this.edges=[];
      for(const edge of edges){const a=index.get(edge.source),b=index.get(edge.target);if(a===undefined||b===undefined)continue;this.edges.push([this.nodes[a],this.nodes[b]]);pairs.push(a,b);}
      this.edgeIndices=new Uint32Array(pairs);
      if(this.forceX.length!==this.nodes.length){this.forceX=new Float64Array(this.nodes.length);this.forceY=new Float64Array(this.nodes.length);}
    }
    move(id, x, y) {
      const p=this.points.get(id); if(p) Object.assign(p,{x,y,vx:0,vy:0});
    }
    step(iterations=1) {
      let movement=0;
      const nodes=this.nodes,count=nodes.length,fx=this.forceX,fy=this.forceY,edges=this.edgeIndices;
      const gravity=this.gravity,repulsion=this.repulsion,rest=this.distance,hypot=Math.hypot,abs=Math.abs,max=Math.max;
      for(let k=0;k<iterations;k++) {
        for(let i=0;i<count;i++){fx[i]=-nodes[i].x*gravity;fy[i]=-nodes[i].y*gravity;}
        for(let i=0;i<count;i++)for(let j=i+1;j<count;j++) {
          const a=nodes[i],b=nodes[j];let dx=a.x-b.x,dy=a.y-b.y;
          if(abs(dx)+abs(dy)<0.01){dx=0.3;dy=0.2;}
          const distance=max(12,hypot(dx,dy));
          const strength=repulsion/(distance*distance)+(distance<60?(60-distance)*0.12:0);
          const x=dx/distance*strength,y=dy/distance*strength;
          fx[i]+=x;fy[i]+=y;fx[j]-=x;fy[j]-=y;
        }
        for(let k=0;k<edges.length;k+=2) {
          const i=edges[k],j=edges[k+1],a=nodes[i],b=nodes[j];
          const dx=b.x-a.x,dy=b.y-a.y,distance=max(1,hypot(dx,dy));
          const strength=(distance-rest)*0.018;
          const x=dx/distance*strength,y=dy/distance*strength;
          fx[i]+=x;fy[i]+=y;fx[j]-=x;fy[j]-=y;
        }
        movement=0;
        for(let i=0;i<count;i++){
          if(nodes[i].id===this.anchorId){Object.assign(nodes[i],{x:0,y:0,vx:0,vy:0});continue;}
          const p=nodes[i],vx=(p.vx+fx[i])*0.76,vy=(p.vy+fy[i])*0.76;
          p.vx=vx>12?12:vx< -12?-12:vx;p.vy=vy>12?12:vy< -12?-12:vy;
          p.x+=p.vx;p.y+=p.vy;movement+=abs(p.vx)+abs(p.vy);
        }
      }
      return movement;
    }
    async stepAsync(iterations=1, sliceMs=8) {
      let remaining=iterations,movement=0;
      // Keep the exact deterministic iteration order while allowing input and paint
      // between short batches. Positions are rendered only after the whole layout.
      while(remaining>0){
        const deadline=performance.now()+sliceMs;
        do{movement=this.step(1);remaining--;}while(remaining>0&&performance.now()<deadline);
        if(remaining>0)await new Promise(resolve=>setTimeout(resolve,0));
      }
      return movement;
    }
    positions(){return this.nodes.map(p=>({id:p.id,style:{x:p.x,y:p.y}}));}
  }
  window.CourseNetwork=CourseNetwork;
})();
