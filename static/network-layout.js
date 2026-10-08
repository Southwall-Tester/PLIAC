/* Small deterministic force simulation. Positions belong to the view, not the course. */
(() => {
  class CourseNetwork {
    constructor() {
      this.points = new Map(); this.nodes = []; this.edges = [];
      this.repulsion = 6500; this.distance = 145; this.gravity = 0.012;
    }
    setData(nodes, edges) {
      this.nodes = nodes.map((n, i) => {
        if (!this.points.has(n.id)) {
          const angle = i * 2.3999632297, radius = 45 * Math.sqrt(i + 1);
          this.points.set(n.id, {id:n.id,x:Math.cos(angle)*radius,y:Math.sin(angle)*radius,vx:0,vy:0});
        }
        return this.points.get(n.id);
      });
      this.edges = edges.map(e=>[this.points.get(e.source),this.points.get(e.target)]).filter(e=>e[0]&&e[1]);
    }
    move(id, x, y) {
      const p=this.points.get(id); if(p) Object.assign(p,{x,y,vx:0,vy:0});
    }
    step(iterations=1) {
      let movement=0;
      for(let k=0;k<iterations;k++) {
        const forces=this.nodes.map(p=>({x:-p.x*this.gravity,y:-p.y*this.gravity}));
        const index=new Map(this.nodes.map((p,i)=>[p.id,i]));
        for(let i=0;i<this.nodes.length;i++)for(let j=i+1;j<this.nodes.length;j++) {
          const a=this.nodes[i],b=this.nodes[j];let dx=a.x-b.x,dy=a.y-b.y;
          if(Math.abs(dx)+Math.abs(dy)<0.01){dx=0.3;dy=0.2;}
          const distance=Math.max(12,Math.hypot(dx,dy));
          const strength=this.repulsion/(distance*distance)+(distance<60?(60-distance)*0.12:0);
          const x=dx/distance*strength,y=dy/distance*strength;
          forces[i].x+=x;forces[i].y+=y;forces[j].x-=x;forces[j].y-=y;
        }
        for(const [a,b] of this.edges) {
          const dx=b.x-a.x,dy=b.y-a.y,distance=Math.max(1,Math.hypot(dx,dy));
          const strength=(distance-this.distance)*0.018;
          const x=dx/distance*strength,y=dy/distance*strength;
          forces[index.get(a.id)].x+=x;forces[index.get(a.id)].y+=y;
          forces[index.get(b.id)].x-=x;forces[index.get(b.id)].y-=y;
        }
        movement=0;
        this.nodes.forEach((p,i)=>{
          p.vx=Math.max(-12,Math.min(12,(p.vx+forces[i].x)*0.76));
          p.vy=Math.max(-12,Math.min(12,(p.vy+forces[i].y)*0.76));
          p.x+=p.vx;p.y+=p.vy;movement+=Math.abs(p.vx)+Math.abs(p.vy);
        });
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
