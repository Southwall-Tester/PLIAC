/* Shared circular graph renderer for course and document graphs. */
(() => {
  class NetworkView {
    static bindTheme(redraw) {
      const button=document.getElementById('themeButton');
      GraphTheme.sync();
      button.onclick=async()=>{GraphTheme.toggle();await redraw?.();};
    }
    constructor(element, select, edgeSelect, contextMenu) {
      this.element=element;this.select=select;this.edgeSelect=edgeSelect;
      this.force=new CourseNetwork();this.labels=true;this.busy=false;this.dragging=false;
      this.operations=Promise.resolve();
      this.focus=null;this.focusDirty=false;this.frame=null;this.visualNodes=new Map();this.visualEdges=new Map();
      const Graph=window.PIXI&&window.CoursePixiGraph?CoursePixiGraph:G6.Graph;
      this.graph=new Graph({container:element,width:element.clientWidth,height:element.clientHeight,
        animation:false,padding:65,zoomRange:[.08,6],
        node:{type:'circle',style:{labelText:d=>d.data.title,labelPlacement:'bottom',labelOffsetY:5,labelFontSize:11,labelFontFamily:'Microsoft YaHei, sans-serif'}},
        edge:{style:{lineWidth:1,endArrowSize:5,labelFontSize:8,labelAutoRotate:true}},
        transforms:typeof CourseNetwork.routeEdges==='function'?[]:[{type:'process-parallel-edges',mode:'bundle',distance:24}],
        behaviors:['drag-canvas',{type:'zoom-canvas',sensitivity:.2,animation:{duration:120}},{type:'drag-element',animation:false,dropEffect:'none'},
          {type:'optimize-viewport-transform',enable:()=>this.data?.edges.length>800,debounce:120,
            shapes:(type,shape)=>!['label','text','background'].includes(shape.className)}]});
      this.graph.on('node:click',e=>select?.(e.target.id));
      this.graph.on('edge:click',e=>edgeSelect?.(e.target.id));
      // G6 node events include the text label. Hit-test the circular key shape only.
      element.addEventListener('pointermove',event=>this.pointerMove(event));
      element.addEventListener('pointerleave',()=>{if(!this.dragging)this.setFocus(null);});
      element.addEventListener('contextmenu',event=>{const id=this.hitTest(event);if(id&&contextMenu){event.preventDefault();contextMenu(id,{x:event.clientX,y:event.clientY});}});
      this.graph.on('node:dragstart',()=>{this.dragging=true;});
      this.graph.on('node:dragend',e=>{const p=this.graph.getElementPosition(e.target.id);this.force.move(e.target.id,p[0],p[1]);const hit=this.hitNodes?.find(n=>n.id===e.target.id);if(hit){hit.x=p[0];hit.y=p[1];}this.dragging=false;this.wake();});
      this.graph.on('afterdraw',()=>{if(!this.busy)this.restoreFocusStyles();});
      new ResizeObserver(()=>{if(element.clientWidth&&element.clientHeight)this.graph.setSize(element.clientWidth,element.clientHeight);}).observe(element);
      this.tick=async()=>{
        this.frame=null;
        const now=performance.now();
        if(!this.busy&&!this.dragging&&!document.hidden&&this.force.nodes.length&&(this.focusDirty||this.transition)){
          this.busy=true;
          try{
            if(this.focusDirty)this.startFocusTransition(now);
            if(this.transition)this.drawFocusTransition(now);
          }catch(error){console.error(error);}finally{this.busy=false;}
        }
        this.wake();
      };
      document.addEventListener('visibilitychange',()=>{if(!document.hidden)this.wake();});
    }
    wake(){
      if(this.frame===null&&!this.busy&&!this.dragging&&!document.hidden&&this.force.nodes.length&&(this.focusDirty||this.transition))this.frame=requestAnimationFrame(this.tick);
    }
    enqueue(work){
      const result=this.operations.then(work);
      this.operations=result.catch(()=>{});
      return result;
    }
    clearLayout(){
      return this.enqueue(async()=>{
        while(this.busy)await new Promise(resolve=>setTimeout(resolve,10));
        this.force.points.clear();
      });
    }
    async layout(iterations){
      if(typeof this.force.stepAsync==='function')return this.force.stepAsync(iterations);
      // A previously cached layout script still supports synchronous single steps.
      // Yield between short batches while the browser refreshes shared assets.
      let remaining=iterations;
      while(remaining>0){
        const deadline=performance.now()+8;
        do{this.force.step(1);remaining--;}while(remaining>0&&performance.now()<deadline);
        if(remaining>0)await new Promise(resolve=>setTimeout(resolve,0));
      }
    }
    setData(data, reset=false, layoutIterations=0) {
      return this.enqueue(()=>this.drawData(data,reset,layoutIterations));
    }
    async drawData(data, reset=false, layoutIterations=0) {
      while(this.busy)await new Promise(r=>setTimeout(r,10));this.busy=true;
      try{
        const firstLayout=this.force.points.size===0&&data.nodes.length>0;
        this.data=data;this.force.setData(data.nodes,data.edges);
        if(firstLayout||layoutIterations)await this.layout(firstLayout?320:layoutIterations);
        const positions=new Map(this.force.positions().map(p=>[p.id,p.style]));
        const dark=document.body.classList.contains('network-dark');
        const nodes=data.nodes.map(n=>({...n,style:{fill:GraphEncoding.rootFill,stroke:GraphEncoding.outline(n.style?.fill||GraphEncoding.rootFill),lineWidth:1,opacity:1,labelOpacity:1,shadowBlur:0,size:12,...n.style,...positions.get(n.id),labelFill:dark?'#e8edf6':'#303b4c',labelText:this.labels?n.data.title:''}}));
        for(const node of nodes){node.style.hitRadius=Number(node.style.size)/2;node.style.baseLineWidth=node.style.lineWidth;}
        const fills=new Map(nodes.map(n=>[n.id,n.style.fill]));
        // Relations follow the source node's family; line style still encodes relation type.
        // G6's graph-level styles override data styles, so theme-dependent labels live here.
        if(this.routedSource!==data.edges){this.routedSource=data.edges;this.routedEdges=CourseNetwork.routeEdges?CourseNetwork.routeEdges(data.edges):data.edges;}
        const edges=this.routedEdges.map(e=>({...e,style:{stroke:fills.get(e.source)||GraphEncoding.rootFill,opacity:.35,...e.style,labelText:this.labels?(e.data?.label||''):'',labelFill:dark?'#a6b2c2':'#5c6778',labelBackground:!dark,labelBackgroundFill:'#fcfbf9',labelBackgroundOpacity:.78}}));
        this.baseNodes=new Map(nodes.map(n=>[n.id,{...n.style}]));this.baseEdges=new Map(edges.map(e=>[e.id,{...e.style}]));
        // Preserve an in-flight highlight when node selection redraws the same topology.
        if(!reset){for(const n of nodes)if(this.visualNodes.has(n.id))Object.assign(n.style,this.visualNodes.get(n.id));for(const e of edges)if(this.visualEdges.has(e.id))Object.assign(e.style,this.visualEdges.get(e.id));}
        else{this.visualNodes.clear();this.visualEdges.clear();this.transition=null;}
        if(this.focus&&!this.baseNodes.has(this.focus))this.focus=null;
        if(reset){this.graph.setData({nodes,edges});await this.graph.render();if(firstLayout)await this.fit();}
        else{this.graph.updateNodeData(nodes);this.graph.updateEdgeData(edges);await this.graph.draw();}
        this.hitNodes=nodes.map(n=>({id:n.id,x:n.style.x,y:n.style.y,radius:Number(this.baseNodes.get(n.id).size)/2}));
        this.guardCanvasFrames();
        this.cacheFocusShapes();
        this.focusDirty=true;
      }finally{this.busy=false;this.wake();}
    }
    // Resolve current data when this operation runs, after earlier filter updates.
    redraw(){return this.enqueue(()=>this.data?this.drawData(this.data):undefined);}
    async fit(){
      await this.graph.fitView();
      const anchor=this.data?.nodes.find(n=>n.data?.layout_anchor);
      if(anchor){
        const center=this.graph.getElementPosition(anchor.id);
        let width=1,height=1;
        for(const n of this.data.nodes){const p=this.graph.getElementPosition(n.id);width=Math.max(width,Math.abs(p[0]-center[0])+70);height=Math.max(height,Math.abs(p[1]-center[1])+45);}
        await this.graph.zoomTo(Math.max(.08,Math.min(1.15,(this.element.clientWidth/2-30)/width,(this.element.clientHeight/2-30)/height)));
        const at=this.graph.getViewportByCanvas(center);
        await this.graph.translateBy([this.element.clientWidth/2-at[0],this.element.clientHeight/2-at[1]]);
      }else if(this.graph.getZoom()>1.15)await this.graph.zoomTo(1.15);
    }
    setFocus(id){if(this.focus===id)return;this.focus=id;this.focusDirty=true;this.wake();}
    pointerMove(event){
      if(!this.data||this.dragging||event.pointerType==='touch')return;
      this.setFocus(this.hitTest(event));
    }
    hitTest(event){
      if(!this.data)return null;
      const rect=this.element.getBoundingClientRect(),p=this.graph.getCanvasByViewport([event.clientX-rect.left,event.clientY-rect.top]);
      let hit=null,closest=Infinity;
      for(const n of this.hitNodes||[]){
        // Use the resting radius so the visual enlargement cannot make labels hoverable.
        const radius=n.radius,dx=p[0]-n.x,dy=p[1]-n.y,distance=dx*dx+dy*dy;
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
      const changed=item=>Object.keys(item.to).some(key=>item.from[key]!==item.to[key]);
      const changedNodes=nodes.filter(changed),changedEdges=edges.filter(changed);
      this.transition=changedNodes.length||changedEdges.length?{focus:id,near,started:now,duration:matchMedia('(prefers-reduced-motion: reduce)').matches?0:220,nodes:changedNodes,edges:changedEdges}:null;
      if(this.transition)this.graph.beginFocusTransition?.(this.transition);
    }
    drawFocusTransition(now){
      const transition=this.transition;if(!transition)return;
      const progress=transition.duration?Math.min(1,(now-transition.started)/transition.duration):1;
      const eased=progress*progress*(3-2*progress);
      const interpolate=item=>{const style={};for(const key of Object.keys(item.to))style[key]=progress===1?item.to[key]:item.from[key]+(item.to[key]-item.from[key])*eased;return style;};
      this.graph.beginFocusFrame?.(eased);
      for(const item of transition.nodes){const style=interpolate(item);this.visualNodes.set(item.id,style);this.paintFocusNode(item.id,style,item.shadowColor);}
      for(const item of transition.edges){const style=interpolate(item);this.visualEdges.set(item.id,style);this.paintFocusEdge(item.id,style);}
      this.graph.endFocusFrame?.();
      if(progress===1)this.transition=null;
    }
    guardCanvasFrames(){
      // G6 5.1.1's G canvas scans the entire scene before its dirty check.
      // Keep native camera/animation scheduling, but skip clean display frames.
      // Scope the adapter to these canvas instances; do not patch the vendor.
      for(const layer of Object.values(this.graph.getCanvas?.().getLayers?.()||{})){
        if(layer.__networkDirtyGuard)continue;
        const reasons=layer.context?.renderingContext?.renderReasons,render=layer.render;
        if(!(reasons instanceof Set)||typeof render!=='function')continue;
        layer.render=function(...args){if(reasons.size)return render.apply(this,args);};
        layer.__networkDirtyGuard=true;
      }
    }
    cacheFocusShapes(){
      if(this.graph.paintFocusNode){this.restoreFocusStyles();return;}
      // G6 5.1.1 display objects expose attr/getShape. Hover is transient paint,
      // not a graph-data change: leave topology, parallel paths and layout alone.
      const capture=id=>{const element=this.graph.context.element.getElement(id),label=element?.getShape('label');return {element,key:element?.getShape('key'),label,text:label?.getShape('text'),background:label?.getShape('background')};};
      this.nodeShapes=new Map(this.data.nodes.map(n=>[n.id,capture(n.id)]));
      this.edgeShapes=new Map(this.data.edges.map(e=>[e.id,capture(e.id)]));
      this.restoreFocusStyles();
    }
    paintFocusNode(id,style,color=this.baseNodes.get(id)?.fill){
      if(this.graph.paintFocusNode){this.graph.paintFocusNode(id,style,color);return;}
      const shapes=this.nodeShapes?.get(id);if(!shapes?.key||shapes.key.destroyed)return;
      shapes.element.attr({...style,shadowColor:color});
      shapes.key.attr({opacity:style.opacity,r:style.size/2,lineWidth:style.lineWidth,shadowBlur:style.shadowBlur,shadowColor:color});
      shapes.label?.attr('opacity',style.labelOpacity);shapes.text?.attr('opacity',style.labelOpacity);
      shapes.background?.attr('opacity',style.labelOpacity*(this.baseNodes.get(id)?.labelBackgroundOpacity??.75));
    }
    paintFocusEdge(id,style){
      if(this.graph.paintFocusEdge){this.graph.paintFocusEdge(id,style);return;}
      const shapes=this.edgeShapes?.get(id);if(!shapes?.key||shapes.key.destroyed)return;
      shapes.element.attr('opacity',style.opacity);shapes.key.attr('opacity',style.opacity);
      const opacity=Math.min(1,style.opacity/(this.baseEdges.get(id)?.opacity||1));
      shapes.label?.attr('opacity',opacity*(this.baseEdges.get(id)?.opacity??1));shapes.text?.attr('opacity',opacity*(this.baseEdges.get(id)?.opacity??1));
      shapes.background?.attr('opacity',opacity*(this.baseEdges.get(id)?.labelBackgroundOpacity??.78));
    }
    restoreFocusStyles(){
      for(const [id,style] of this.visualNodes)this.paintFocusNode(id,style);
      for(const [id,style] of this.visualEdges)this.paintFocusEdge(id,style);
    }
    bindControls() {
      const $=id=>document.getElementById(id);
      const arrange=async()=>{if(this.arranging)return;this.arranging=true;try{await this.enqueue(async()=>{if(!this.data?.nodes.length)return;await this.drawData(this.data,false,600);await this.fit();});}finally{this.arranging=false;}};
      $('stabilizeButton').onclick=arrange;
      $('applyLayout').onclick=async()=>{$('physicsDialog').close();await arrange();};
      $('labelsButton').onclick=async()=>{this.labels=!this.labels;$('labelsButton').textContent=this.labels?'隐藏标签':'显示标签';await this.redraw();};
      NetworkView.bindTheme(()=>this.redraw());
      $('physicsSettings').onclick=()=>$('physicsDialog').showModal();
      $('repulsion').oninput=e=>{this.force.repulsion=+e.target.value;};
      $('distance').oninput=e=>{this.force.distance=+e.target.value;};
      $('repulsion').value=this.force.repulsion;$('distance').value=this.force.distance;
      $('fitButton').onclick=()=>this.fit();
      $('zoomIn').onclick=()=>this.graph.zoomTo(Math.min(6,this.graph.getZoom()*1.1),{duration:120});
      $('zoomOut').onclick=()=>this.graph.zoomTo(Math.max(.08,this.graph.getZoom()/1.1),{duration:120});
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
