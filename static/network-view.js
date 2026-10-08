/* Shared circular graph renderer for course and document graphs. */
(() => {
  class NetworkView {
    static bindTheme(redraw) {
      const button=document.getElementById('themeButton');
      button.onclick=async()=>{document.body.classList.toggle('network-dark');button.textContent=document.body.classList.contains('network-dark')?'浅色':'深色';await redraw?.();};
    }
    constructor(element, select, edgeSelect, contextMenu) {
      this.element=element;this.select=select;this.edgeSelect=edgeSelect;
      this.force=new CourseNetwork();this.labels=true;this.busy=false;this.dragging=false;
      this.focus=null;this.focusDirty=false;this.visualNodes=new Map();this.visualEdges=new Map();
      this.graph=new G6.Graph({container:element,width:element.clientWidth,height:element.clientHeight,
        animation:false,padding:65,zoomRange:[.08,6],
        node:{type:'circle',style:{labelText:d=>d.data.title,labelPlacement:'bottom',labelOffsetY:5,labelFontSize:11,labelFontFamily:'Microsoft YaHei, sans-serif'}},
        edge:{type:'line',style:{lineWidth:1,endArrowSize:5,labelFontSize:8,labelAutoRotate:true,labelBackground:true,labelBackgroundFill:'#ffffff',labelBackgroundOpacity:.78}},
        behaviors:['drag-canvas','zoom-canvas',{type:'drag-element',animation:false,dropEffect:'none'}]});
      this.graph.on('node:click',e=>select?.(e.target.id));
      this.graph.on('edge:click',e=>edgeSelect?.(e.target.id));
      // G6 node events include the text label. Hit-test the circular key shape only.
      element.addEventListener('pointermove',event=>this.pointerMove(event));
      element.addEventListener('pointerleave',()=>{if(!this.dragging)this.setFocus(null);});
      element.addEventListener('contextmenu',event=>{const id=this.hitTest(event);if(id&&contextMenu){event.preventDefault();contextMenu(id,{x:event.clientX,y:event.clientY});}});
      this.graph.on('node:dragstart',()=>{this.dragging=true;});
      this.graph.on('node:dragend',e=>{const p=this.graph.getElementPosition(e.target.id);this.force.move(e.target.id,p[0],p[1]);this.dragging=false;});
      new ResizeObserver(()=>{if(element.clientWidth&&element.clientHeight)this.graph.setSize(element.clientWidth,element.clientHeight);}).observe(element);
      this.tick=async()=>{
        const now=performance.now();
        if(!this.busy&&!this.dragging&&!document.hidden&&this.force.nodes.length&&(this.focusDirty||this.transition)){
          this.busy=true;
          try{
            if(this.focusDirty)this.startFocusTransition(now);
            this.drawFocusTransition(now);
            await this.graph.draw();
          }catch(error){console.error(error);}finally{this.busy=false;}
        }
        this.frame=requestAnimationFrame(this.tick);
      };
      this.frame=requestAnimationFrame(this.tick);
    }
    async setData(data, reset=false) {
      while(this.busy)await new Promise(r=>setTimeout(r,10));this.busy=true;
      try{
        if(!data.nodes.length)this.force.points.clear();
        const firstLayout=this.force.points.size===0&&data.nodes.length>0;
        this.data=data;this.force.setData(data.nodes,data.edges);
        if(firstLayout)this.force.step(320);
        const positions=new Map(this.force.positions().map(p=>[p.id,p.style]));
        const dark=document.body.classList.contains('network-dark');
        const nodes=data.nodes.map(n=>({...n,style:{fill:GraphEncoding.rootFill,stroke:GraphEncoding.outline(n.style?.fill||GraphEncoding.rootFill),lineWidth:1,opacity:1,labelOpacity:1,shadowBlur:0,size:12,...n.style,...positions.get(n.id),labelFill:dark?'#e8edf6':'#303b4c',labelText:this.labels?n.data.title:''}}));
        const fills=new Map(nodes.map(n=>[n.id,n.style.fill]));
        // Relations follow the source node's family; line style still encodes relation type.
        const edges=data.edges.map(e=>({...e,style:{stroke:fills.get(e.source)||GraphEncoding.rootFill,opacity:.35,...e.style,labelText:this.labels?(e.data?.label||''):'',labelFill:dark?'#c9d0df':'#5c6778',labelBackgroundFill:dark?'#111820':'#fcfbf9'}}));
        this.baseNodes=new Map(nodes.map(n=>[n.id,{...n.style}]));this.baseEdges=new Map(edges.map(e=>[e.id,{...e.style}]));
        // Preserve an in-flight highlight when node selection redraws the same topology.
        if(!reset){for(const n of nodes)if(this.visualNodes.has(n.id))Object.assign(n.style,this.visualNodes.get(n.id));for(const e of edges)if(this.visualEdges.has(e.id))Object.assign(e.style,this.visualEdges.get(e.id));}
        else{this.visualNodes.clear();this.visualEdges.clear();this.transition=null;}
        if(this.focus&&!this.baseNodes.has(this.focus))this.focus=null;
        if(reset){this.graph.setData({nodes,edges});await this.graph.render();if(firstLayout)await this.fit();}
        else{this.graph.updateNodeData(nodes);this.graph.updateEdgeData(edges);await this.graph.draw();}
        this.focusDirty=true;
      }finally{this.busy=false;}
    }
    async redraw(){if(this.data)await this.setData(this.data);}
    async fit(){await this.graph.fitView();if(this.graph.getZoom()>1.15)await this.graph.zoomTo(1.15);}
    setFocus(id){if(this.focus===id)return;this.focus=id;this.focusDirty=true;}
    pointerMove(event){
      if(!this.data||this.dragging||event.pointerType==='touch')return;
      this.setFocus(this.hitTest(event));
    }
    hitTest(event){
      if(!this.data)return null;
      const rect=this.element.getBoundingClientRect(),p=this.graph.getCanvasByViewport([event.clientX-rect.left,event.clientY-rect.top]);
      let hit=null,closest=Infinity;
      for(const n of this.graph.getNodeData()){
        const base=this.baseNodes?.get(n.id);if(!base)continue;
        // Use the resting radius so the visual enlargement cannot make labels hoverable.
        const radius=Number(base.size)/2,dx=p[0]-n.style.x,dy=p[1]-n.style.y,distance=dx*dx+dy*dy;
        if(distance<=radius*radius&&distance<closest){hit=n.id;closest=distance;}
      }
      return hit;
    }
    startFocusTransition(now){
      this.focusDirty=false;const id=this.focus,near=new Set(id?[id]:[]);
      for(const e of this.data.edges)if(e.source===id||e.target===id){near.add(e.source);near.add(e.target);}
      const nodes=this.data.nodes.map(n=>{
        const base=this.baseNodes.get(n.id),active=n.id===id,dim=!!id&&!near.has(n.id);
        const to={opacity:dim?.12:base.opacity,labelOpacity:dim?.12:1,size:base.size*(active?1.16:1),lineWidth:active?3:base.lineWidth,shadowBlur:active?16:0};
        const from=this.visualNodes.get(n.id)||{opacity:base.opacity,labelOpacity:1,size:base.size,lineWidth:base.lineWidth,shadowBlur:0};
        return {id:n.id,from:{...from},to,shadowColor:base.fill};
      });
      const edges=this.data.edges.map(e=>{const base=this.baseEdges.get(e.id),connected=e.source===id||e.target===id;return {id:e.id,from:{...(this.visualEdges.get(e.id)||{opacity:base.opacity})},to:{opacity:id?(connected?.95:.05):base.opacity}};});
      this.transition={started:now,duration:matchMedia('(prefers-reduced-motion: reduce)').matches?0:220,nodes,edges};
    }
    drawFocusTransition(now){
      const transition=this.transition;if(!transition)return;
      const progress=transition.duration?Math.min(1,(now-transition.started)/transition.duration):1;
      const eased=progress*progress*(3-2*progress);
      const interpolate=item=>{const style={};for(const key of Object.keys(item.to))style[key]=progress===1?item.to[key]:item.from[key]+(item.to[key]-item.from[key])*eased;return style;};
      this.graph.updateNodeData(transition.nodes.map(item=>{const style=interpolate(item);this.visualNodes.set(item.id,style);return {id:item.id,style:{...style,shadowColor:item.shadowColor}};}));
      this.graph.updateEdgeData(transition.edges.map(item=>{const style=interpolate(item);this.visualEdges.set(item.id,style);return {id:item.id,style};}));
      if(progress===1)this.transition=null;
    }
    bindControls() {
      const $=id=>document.getElementById(id);
      const arrange=async()=>{this.force.step(600);await this.redraw();await this.fit();};
      $('stabilizeButton').onclick=arrange;
      $('applyLayout').onclick=async()=>{$('physicsDialog').close();await arrange();};
      $('labelsButton').onclick=async()=>{this.labels=!this.labels;$('labelsButton').textContent=this.labels?'隐藏标签':'显示标签';await this.redraw();};
      NetworkView.bindTheme(()=>this.redraw());
      $('physicsSettings').onclick=()=>$('physicsDialog').showModal();
      $('repulsion').oninput=e=>{this.force.repulsion=+e.target.value;};
      $('distance').oninput=e=>{this.force.distance=+e.target.value;};
      $('repulsion').value=this.force.repulsion;$('distance').value=this.force.distance;
      $('fitButton').onclick=()=>this.fit();
      $('zoomIn').onclick=()=>this.graph.zoomTo(Math.min(6,this.graph.getZoom()*1.2));
      $('zoomOut').onclick=()=>this.graph.zoomTo(Math.max(.08,this.graph.getZoom()/1.2));
    }
  }
  window.NetworkView=NetworkView;
  window.showGraphMenu=(title,items,point)=>{
    document.getElementById('graphContextMenu')?.remove();
    const menu=document.createElement('div');menu.id='graphContextMenu';menu.className='graph-context-menu';menu.setAttribute('role','menu');
    const heading=document.createElement('strong');heading.textContent=title;menu.appendChild(heading);
    for(const item of items){const button=document.createElement('button');button.type='button';button.textContent=item.label;button.setAttribute('role','menuitem');button.onclick=()=>{menu.remove();item.action();};menu.appendChild(button);}
    document.body.appendChild(menu);menu.style.left=Math.max(8,Math.min(point.x,innerWidth-menu.offsetWidth-8))+'px';menu.style.top=Math.max(8,Math.min(point.y,innerHeight-menu.offsetHeight-8))+'px';
  };
  document.addEventListener('pointerdown',e=>{const menu=document.getElementById('graphContextMenu');if(menu&&!menu.contains(e.target))menu.remove();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('graphContextMenu')?.remove();});
})();
