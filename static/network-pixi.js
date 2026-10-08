/* PLIAC graph renderer. Independent PixiJS implementation; coordinates stay in graph space. */
(() => {
  'use strict';
  const number=(value,fallback=0)=>Number.isFinite(Number(value))?Number(value):fallback;
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  const circleRadius=64;
  const copy=item=>({...item,data:{...item.data},style:{...item.style}});
  const point=(a,c,b,t)=>{const s=1-t;return [s*s*a[0]+2*s*t*c[0]+t*t*b[0],s*s*a[1]+2*s*t*c[1]+t*t*b[1]];};

  // These adapters inspect and update the actual Pixi display objects. They keep
  // the small display-object inspection surface used by the surrounding UI.
  class Shape {
    constructor(graph,record,part){this.graph=graph;this.record=record;this.part=part;this.className=part;}
    get object(){const r=this.record;return this.part==='element'?r.container:this.part==='key'?r.key:this.part==='label'?r.label:this.part==='text'?r.text:r.background;}
    get destroyed(){return !this.object||this.object.destroyed;}
    get attributes(){
      const r=this.record,s=r.style;
      if(this.part==='element')return {...s};
      if(this.part==='key')return r.kind==='node'?{...s,r:r.radius,opacity:r.key.alpha*(r.opacityGroups?.body?.alpha??1)}:{...s,d:r.path,opacity:r.container.alpha*r.key.alpha*(r.opacityGroups?.body?.alpha??1)};
      if(this.part==='text')return {text:r.text?.text,fill:s.labelFill,opacity:r.text?.alpha};
      if(this.part==='background')return {fill:s.labelBackgroundFill,opacity:r.background?.alpha};
      return {text:r.text?.text,opacity:r.label?.alpha*(r.opacityGroups?.label?.alpha??1)};
    }
    getShape(part){
      if(part==='label'&&!this.record.style.labelText)return undefined;
      if(part==='background'&&!this.record.style.labelBackground)return undefined;
      return this.record.shapes[part];
    }
    attr(name,value){
      const style=typeof name==='string'?{[name]:value}:name;
      if(this.part==='element'||this.part==='key'){
        const patch={...style};if('r'in patch)patch.size=2*patch.r;
        this.record.kind==='node'?this.graph.paintFocusNode(this.record.id,patch):this.graph.paintFocusEdge(this.record.id,patch);
      }else if(this.object&&'opacity'in style){this.object.alpha=style.opacity;this.graph.requestRender();}
      return this;
    }
  }

  class CoursePixiGraph {
    constructor(options={}){
      this.options=options;this.element=options.container;this.width=options.width||this.element.clientWidth||1;this.height=options.height||this.element.clientHeight||1;
      this.listeners=new Map();this.nodes=new Map();this.edges=new Map();this.nodeViews=new Map();this.edgeViews=new Map();this.adjacent=new Map();
      this.zoom=1;this.offset=[0,0];this.frame=null;this.viewportDirty=true;this.destroyed=false;this.isPixi=true;
      this.context={element:{getElement:id=>(this.nodeViews.get(id)||this.edgeViews.get(id))?.shapes.element}};
      this.ready=this.initialize();this.bindPointer();
      this.onVisibility=()=>{if(!document.hidden)this.requestRender();};document.addEventListener('visibilitychange',this.onVisibility);
    }
    async initialize(){
      this.app=new PIXI.Application();
      await this.app.init({width:this.width,height:this.height,preference:'webgl',autoStart:false,sharedTicker:false,antialias:true,
        resolution:Math.min(window.devicePixelRatio||1,2),autoDensity:true,backgroundAlpha:0});
      this.app.stop();
      // Picking uses the DOM handlers below; detach this instance's Pixi event
      // ticker without stopping a global ticker that another app might use.
      this.app.renderer.events?.setTargetElement(null);
      this.circleContext=new PIXI.GraphicsContext().circle(0,0,circleRadius).fill(0xffffff);
      this.glowContext=new PIXI.GraphicsContext();for(let i=5;i>=1;i--)this.glowContext.circle(0,0,circleRadius*(1+i*.12)).fill({color:0xffffff,alpha:.035});
      this.sharedContexts=new Set([this.circleContext,this.glowContext]);this.outlineContexts=new Map();
      this.world=new PIXI.Container({isRenderGroup:true});this.world.eventMode='none';
      this.edgeLayer=new PIXI.Container({isRenderGroup:true});this.nodeLayer=new PIXI.Container({isRenderGroup:true});this.edgeLabels=new PIXI.Container({isRenderGroup:true});this.nodeLabels=new PIXI.Container({isRenderGroup:true});
      this.world.addChild(this.edgeLayer,this.nodeLayer,this.edgeLabels,this.nodeLabels);this.app.stage.addChild(this.world);
      this.app.canvas.style.display='block';this.app.canvas.style.touchAction='none';this.element.appendChild(this.app.canvas);
      this.applyViewport();
    }
    on(type,callback){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(callback);return this;}
    off(type,callback){this.listeners.get(type)?.delete(callback);return this;}
    emit(type,event={}){for(const callback of this.listeners.get(type)||[])callback(event);return this;}
    getOptions(){return this.options;}
    setData(data){this.nodes=new Map((data.nodes||[]).map(n=>[n.id,copy(n)]));this.edges=new Map((data.edges||[]).map(e=>[e.id,copy(e)]));return this;}
    updateNodeData(nodes){this.update(this.nodes,nodes);return this;}
    updateEdgeData(edges){this.update(this.edges,edges);return this;}
    update(map,items){for(const item of items){const previous=map.get(item.id)||{};map.set(item.id,{...previous,...item,data:{...previous.data,...item.data},style:{...previous.style,...item.style}});}}
    getNodeData(id){return id===undefined?[...this.nodes.values()]:Array.isArray(id)?id.map(key=>this.nodes.get(key)):this.nodes.get(id);}
    getEdgeData(id){return id===undefined?[...this.edges.values()]:Array.isArray(id)?id.map(key=>this.edges.get(key)):this.edges.get(id);}
    getElementPosition(id){const s=this.nodeViews.get(id)?.style||this.nodes.get(id)?.style;return [number(s?.x),number(s?.y),0];}
    getElementRenderStyle(id){return {...(this.nodeViews.get(id)||this.edgeViews.get(id))?.style};}
    getZoom(){return this.zoom;}
    getCanvasByViewport(p){return [(p[0]-this.offset[0])/this.zoom,(p[1]-this.offset[1])/this.zoom];}
    getViewportByCanvas(p){return [p[0]*this.zoom+this.offset[0],p[1]*this.zoom+this.offset[1]];}
    async render(){return this.draw();}
    async draw(){
      await this.ready;if(this.destroyed)return;
      this.clearFocusGroups();
      this.prune(this.nodeViews,this.nodes);this.prune(this.edgeViews,this.edges);
      for(const node of this.nodes.values())this.syncNode(node);
      this.adjacent=new Map();
      for(const edge of this.edges.values()){
        for(const id of new Set([edge.source,edge.target])){if(!this.adjacent.has(id))this.adjacent.set(id,new Set());this.adjacent.get(id).add(edge.id);}
        this.syncEdge(edge);
      }
      this.viewportDirty=true;this.emit('afterdraw');this.requestRender();
    }
    destroyView(record){
      const shapes=[record.key,record.outline,record.glow,record.background,record.arrow,record.startArrow].filter(Boolean);
      const contexts=new Set(shapes.map(g=>g.context));
      if(record.hoverOutline)contexts.add(record.hoverOutline);
      // Pixi Graphics.destroy({context:false}) leaves context listeners behind.
      // Shared geometry must not retain removed/filtered display objects.
      for(const shape of shapes){shape.context.off('update',shape.onViewUpdate,shape);shape.context.off('unload',shape.unload,shape);}
      record.container.destroy({children:true,context:false});record.label.destroy({children:true,context:false});
      for(const context of contexts)if(!this.sharedContexts.has(context)&&!context.destroyed)context.destroy();
    }
    prune(views,models){for(const [id,record] of views)if(!models.has(id)){this.destroyView(record);views.delete(id);}}
    createView(id,kind){
      const record={id,kind,style:{},container:new PIXI.Container(),key:kind==='node'?new PIXI.Graphics(this.circleContext):new PIXI.Graphics(),label:new PIXI.Container(),background:new PIXI.Graphics(),shapes:{}};
      record.container.eventMode='none';record.label.eventMode='none';record.label.addChild(record.background);
      for(const part of ['element','key','label','text','background'])record.shapes[part]=new Shape(this,record,part);
      if(kind==='node'){
        record.outline=new PIXI.Graphics(this.circleContext);record.glow=new PIXI.Graphics(this.glowContext);record.container.addChild(record.glow,record.outline,record.key);this.nodeLayer.addChild(record.container);this.nodeLabels.addChild(record.label);
      }else{
        record.arrow=new PIXI.Graphics();record.startArrow=new PIXI.Graphics();record.container.addChild(record.key,record.arrow,record.startArrow);this.edgeLayer.addChild(record.container);this.edgeLabels.addChild(record.label);
      }
      // Long dashed paths exceed Pixi's auto-batch vertex threshold. Explicit
      // batching keeps them in shared GPU buffers instead of one draw per edge.
      for(const shape of [record.key,record.background,record.outline,record.glow,record.arrow,record.startArrow])if(shape)shape.context.batchMode='batch';
      return record;
    }
    syncNode(node){
      let r=this.nodeViews.get(node.id);if(!r){r=this.createView(node.id,'node');this.nodeViews.set(node.id,r);}
      r.style={fill:'#c4c8cc',stroke:'#81878d',lineWidth:1,opacity:1,labelOpacity:1,size:12,labelFontSize:11,labelFontFamily:'Microsoft YaHei, sans-serif',...node.style};
      r.baseRadius=number(node.style?.hitRadius,number(node.style?.size,12)/2);
      r.key.tint=r.style.fill;r.outline.tint=r.style.stroke;r.glow.tint=r.style.shadowColor||r.style.fill;
      r.baseOutlineSignature=JSON.stringify([r.baseRadius,number(r.style.baseLineWidth,1),r.style.lineDash||[]]);
      if(!this.outlineContexts.has(r.baseOutlineSignature)){
        const context=new PIXI.GraphicsContext();context.batchMode='batch';this.buildOutline(context,r.baseRadius,number(r.style.baseLineWidth,1),r.style.lineDash);
        this.outlineContexts.set(r.baseOutlineSignature,context);this.sharedContexts.add(context);
      }
      r.container.position.set(number(r.style.x),number(r.style.y));this.paintNode(r);this.syncLabel(r);
    }
    buildOutline(context,radius,width,pattern){
      context.clear();
      if(pattern?.length){let angle=0,index=0;while(angle<Math.PI*2){const end=Math.min(Math.PI*2,angle+Math.max(.1,number(pattern[index%pattern.length],4))/Math.max(.1,radius));
          if(index%2===0)context.moveTo(Math.cos(angle)*circleRadius,Math.sin(angle)*circleRadius).arc(0,0,circleRadius,angle,end);angle=end;index++;}}
      else context.circle(0,0,circleRadius);
      context.stroke({color:0xffffff,width:Math.max(.01,width)*circleRadius/Math.max(.1,radius)});
    }
    paintNode(r){
      const s=r.style,radius=number(s.size,12)/2,width=number(s.lineWidth,1);r.radius=radius;
      const signature=JSON.stringify([radius,width,s.lineDash||[]]);
      if(signature!==r.outlineSignature){r.outlineSignature=signature;
        if(signature===r.baseOutlineSignature)r.outline.context=this.outlineContexts.get(signature);
        else{if(!r.hoverOutline){r.hoverOutline=new PIXI.GraphicsContext();r.hoverOutline.batchMode='batch';}this.buildOutline(r.hoverOutline,radius,width,s.lineDash);r.outline.context=r.hoverOutline;}}
      r.key.scale.set(Math.max(.1,radius-width/2)/circleRadius);r.outline.scale.set(radius/circleRadius);
      const opacity=number(s.opacity,1),body=r.opacityGroups?.body;if(body){body.alpha=opacity;r.key.alpha=r.outline.alpha=1;}else r.key.alpha=r.outline.alpha=opacity;
      r.glow.tint=s.shadowColor||s.fill;r.glow.scale.set((radius+number(s.shadowBlur)/3)/circleRadius);r.glow.alpha=number(s.shadowBlur)>0?(body?1:opacity):0;
      r.label.position.set(number(s.x),number(s.y)+radius+number(s.labelOffsetY,5)+number(s.labelFontSize,11)/2);
      this.paintLabelOpacity(r,number(s.labelOpacity,1));
    }
    syncLabel(r){
      const s=r.style,text=String(s.labelText||''),fontSize=number(s.labelFontSize,r.kind==='node'?11:8);
      if(!r.text&&text){r.text=new PIXI.Text({text,resolution:2,style:{fontFamily:s.labelFontFamily||'Microsoft YaHei, sans-serif',fontSize,fill:s.labelFill||'#303b4c',fontWeight:s.labelFontWeight||400}});r.text.anchor.set(.5);r.label.addChild(r.text);}
      if(r.text){if(r.text.text!==text)r.text.text=text;
        const signature=JSON.stringify([fontSize,s.labelFill,s.labelFontFamily,s.labelFontWeight]);
        if(r.labelSignature!==signature){r.labelSignature=signature;r.text.style={fontSize,fontFamily:s.labelFontFamily||'Microsoft YaHei, sans-serif',fill:s.labelFill||'#303b4c',fontWeight:s.labelFontWeight||400};}
      }
      const bgSignature=JSON.stringify([text,r.labelSignature,s.labelBackground,s.labelBackgroundFill,s.labelBackgroundOpacity]);
      if(bgSignature!==r.backgroundSignature){r.backgroundSignature=bgSignature;r.background.clear();
        if(text&&s.labelBackground&&r.text){const w=r.text.width+4,h=r.text.height+2;r.background.roundRect(-w/2,-h/2,w,h,2).fill(s.labelBackgroundFill||'#fcfbf9');}}
      r.background.visible=!!s.labelBackground;r.background.alpha=number(s.labelBackgroundOpacity,.78);r.hasLabel=!!text;
      r.label.visible=!!text&&(r.kind==='node'||!!r.bounds);this.paintLabelOpacity(r,r.kind==='node'?number(s.labelOpacity,1):number(s.opacity,.35)*number(s.labelOpacity,1));
    }
    syncEdge(edge){
      let r=this.edgeViews.get(edge.id);if(!r){r=this.createView(edge.id,'edge');this.edgeViews.set(edge.id,r);}
      r.source=edge.source;r.target=edge.target;r.style={opacity:.35,lineWidth:1,stroke:'#a2a9af',labelFontSize:8,...edge.style};
      this.edgeGeometry(r);this.syncLabel(r);this.paintEdge(r);
    }
    edgeGeometry(r){
      const source=this.nodeViews.get(r.source),target=this.nodeViews.get(r.target);if(!source||!target){r.container.visible=false;r.label.visible=false;r.bounds=null;r.points=[];r.path=[];r.geometrySignature='';return;}
      const a=[number(source.style.x),number(source.style.y)],b=[number(target.style.x),number(target.style.y)],s=r.style;
      const signature=JSON.stringify([a,b,source.baseRadius,target.baseRadius,s.curveOffset,s.loopPlacement,s.loopDist,s.stroke,s.lineWidth,s.lineDash,s.endArrow,s.startArrow]);
      if(signature===r.geometrySignature)return;r.geometrySignature=signature;r.container.visible=true;
      const dx=b[0]-a[0],dy=b[1]-a[1],length=Math.max(.01,Math.hypot(dx,dy)),offset=number(s.curveOffset);
      let c=[(a[0]+b[0])/2-dy/length*offset,(a[1]+b[1])/2+dx/length*offset],start,end;
      if(r.source===r.target){const placements=['top','top-right','right','right-bottom','bottom','bottom-left','left','left-top'],angle=(placements.indexOf(s.loopPlacement)+6)*Math.PI/4;
        c=[a[0]+Math.cos(angle)*number(s.loopDist,50)*2,a[1]+Math.sin(angle)*number(s.loopDist,50)*2];
        start=[a[0]+Math.cos(angle-.65)*source.baseRadius,a[1]+Math.sin(angle-.65)*source.baseRadius];end=[b[0]+Math.cos(angle+.65)*target.baseRadius,b[1]+Math.sin(angle+.65)*target.baseRadius];
      }else{
        const from=Math.max(.01,Math.hypot(c[0]-a[0],c[1]-a[1])),to=Math.max(.01,Math.hypot(c[0]-b[0],c[1]-b[1]));
        start=[a[0]+(c[0]-a[0])/from*source.baseRadius,a[1]+(c[1]-a[1])/from*source.baseRadius];end=[b[0]+(c[0]-b[0])/to*target.baseRadius,b[1]+(c[1]-b[1])/to*target.baseRadius];
      }
      const curved=!!offset||r.source===r.target;r.path=curved?[['M',...start],['Q',...c,...end]]:[['M',...start],['L',...end]];
      r.points=curved?Array.from({length:25},(_,i)=>point(start,c,end,i/24)):[start,end];
      r.bounds=[Math.min(start[0],c[0],end[0]),Math.min(start[1],c[1],end[1]),Math.max(start[0],c[0],end[0]),Math.max(start[1],c[1],end[1])];
      r.key.clear();
      if(s.lineDash?.length)this.dashed(r.key,r.points,s.lineDash);
      else{r.key.moveTo(...start);curved?r.key.quadraticCurveTo(...c,...end):r.key.lineTo(...end);}
      r.key.stroke({color:s.stroke,width:number(s.lineWidth,1)});
      const endAngle=Math.atan2(end[1]-c[1],end[0]-c[0]),startAngle=Math.atan2(start[1]-c[1],start[0]-c[0]);
      this.arrow(r.arrow,!!s.endArrow,end,endAngle,s);this.arrow(r.startArrow,!!s.startArrow,start,startAngle,s);
      r.anchors={start,end,from:[(start[0]-a[0])/(source.baseRadius||1),(start[1]-a[1])/(source.baseRadius||1)],to:[(end[0]-b[0])/(target.baseRadius||1),(end[1]-b[1])/(target.baseRadius||1)]};this.positionArrows(r);
      const center=curved?point(start,c,end,.5):[(start[0]+end[0])/2,(start[1]+end[1])/2];r.label.position.set(...center);
      let angle=Math.atan2(end[1]-start[1],end[0]-start[0]);if(angle>Math.PI/2)angle-=Math.PI;if(angle< -Math.PI/2)angle+=Math.PI;r.label.rotation=s.labelAutoRotate===false?0:angle;
    }
    dashed(graphics,points,pattern){
      const dash=pattern.map(x=>Math.max(.1,number(x,4)));let index=0,remaining=dash[0];
      graphics.moveTo(...points[0]);
      for(let i=1;i<points.length;i++){let [x,y]=points[i-1];const target=points[i],dx=target[0]-x,dy=target[1]-y,length=Math.hypot(dx,dy);let walked=0;
        while(walked<length-.0001){const step=Math.min(remaining,length-walked);walked+=step;x=points[i-1][0]+dx*walked/length;y=points[i-1][1]+dy*walked/length;
          index%2?graphics.moveTo(x,y):graphics.lineTo(x,y);remaining-=step;if(remaining<.0001){index=(index+1)%dash.length;remaining=dash[index];}}
      }
    }
    arrow(graphics,visible,position,angle,style){
      graphics.clear();graphics.visible=visible;if(!visible)return;
      const size=number(style.endArrowSize,number(this.options.edge?.style?.endArrowSize,5));
      graphics.moveTo(0,0).lineTo(-size*1.6,-size*.65).lineTo(-size*1.2,0).lineTo(-size*1.6,size*.65).closePath().fill(style.stroke);
      graphics.position.set(...position);graphics.rotation=angle;
    }
    paintLabelOpacity(r,opacity){const group=r.opacityGroups?.label;if(group){group.alpha=opacity;r.label.alpha=1;}else r.label.alpha=opacity;}
    paintEdge(r){const opacity=number(r.style.opacity,.35),group=r.opacityGroups?.body;if(group){group.alpha=opacity;r.container.alpha=1;}else r.container.alpha=opacity;this.paintLabelOpacity(r,opacity*number(r.style.labelOpacity,1));}
    clearFocusGroups(){
      if(!this.focusGroups)return;
      // Detach each sibling list once; addChild would otherwise remove every
      // record from its old parent with a separate array search and splice.
      for(const group of this.focusGroups)group.removeChildren();
      for(const r of this.nodeViews.values()){this.nodeLayer.addChild(r.container);this.nodeLabels.addChild(r.label);r.opacityGroups=null;this.paintNode(r);}
      for(const r of this.edgeViews.values()){this.edgeLayer.addChild(r.container);this.edgeLabels.addChild(r.label);r.opacityGroups=null;this.paintEdge(r);}
      for(const group of this.focusGroups)group.destroy();this.focusGroups=null;
    }
    beginFocusTransition(transition){
      if(!this.world||this.destroyed)return;
      this.focus=transition.focus;this.focusNear=transition.near||new Set();this.viewportDirty=true;
      // Reuse the groups that already contain most of each desired bucket.
      // Unchanged memberships keep their GPU batches and display-tree parents.
      const previous=this.focusGroups,groups=new Map(),nodeItems=new Map((transition?.nodes||[]).map(item=>[item.id,item])),edgeItems=new Map((transition?.edges||[]).map(item=>[item.id,item]));
      const collect=(layer,role,part,record,from,to)=>{
        const key=role+':'+from+':'+to;let bucket=groups.get(key);
        if(!bucket){bucket={layer,part,from,to,members:[],overlap:new Map()};groups.set(key,bucket);}
        bucket.members.push(record);
        const parent=(part==='body'?record.container:record.label).parent;
        if(previous?.has(parent)&&parent.parent===layer)bucket.overlap.set(parent,(bucket.overlap.get(parent)||0)+1);
      };
      for(const r of this.nodeViews.values()){
        const item=nodeItems.get(r.id),from=number(r.style.opacity,1),to=number(item?.to.opacity,from),labelFrom=number(r.style.labelOpacity,1),labelTo=number(item?.to.labelOpacity,labelFrom);
        collect(this.nodeLayer,'node','body',r,from,to);collect(this.nodeLabels,'node-label','label',r,labelFrom,labelTo);
      }
      for(const r of this.edgeViews.values()){
        const item=edgeItems.get(r.id),from=number(r.style.opacity,.35),to=number(item?.to.opacity,from),label=number(r.style.labelOpacity,1);
        collect(this.edgeLayer,'edge','body',r,from,to);collect(this.edgeLabels,'edge-label','label',r,from*label,to*label);
      }
      const candidates=[];for(const bucket of groups.values())for(const [group,count] of bucket.overlap)candidates.push({bucket,group,count});
      candidates.sort((a,b)=>b.count-a.count);const reused=new Set();
      for(const {bucket,group} of candidates)if(!bucket.group&&!reused.has(group)){bucket.group=group;reused.add(group);}
      if(previous){for(const group of previous)if(!reused.has(group))group.removeChildren();}
      else for(const layer of [this.nodeLayer,this.nodeLabels,this.edgeLayer,this.edgeLabels])layer.removeChildren();
      const next=new Set();
      for(const bucket of groups.values()){
        let group=bucket.group;
        if(!group){group=new PIXI.Container({isRenderGroup:true});group.eventMode='none';bucket.layer.addChild(group);}
        group.alpha=bucket.from;group.focusFrom=bucket.from;group.focusTo=bucket.to;next.add(group);
        for(const r of bucket.members){const object=bucket.part==='body'?r.container:r.label;if(object.parent!==group)group.addChild(object);(r.opacityGroups||(r.opacityGroups={}))[bucket.part]=group;}
      }
      for(const r of this.nodeViews.values())this.paintNode(r);
      for(const r of this.edgeViews.values())this.paintEdge(r);
      if(previous)for(const group of previous)if(!next.has(group))group.destroy();
      this.focusGroups=next;this.requestRender();
    }
    positionArrows(r){
      if(!r.anchors)return;const source=this.nodeViews.get(r.source),target=this.nodeViews.get(r.target);if(!source||!target)return;
      const a=r.anchors,from=source.radius-source.baseRadius,to=target.radius-target.baseRadius;
      r.startArrow.position.set(a.start[0]+a.from[0]*from,a.start[1]+a.from[1]*from);r.arrow.position.set(a.end[0]+a.to[0]*to,a.end[1]+a.to[1]*to);
    }
    beginFocusFrame(eased){
      this.paintingFocusFrame=true;
      for(const group of this.focusGroups||[])group.alpha=group.focusFrom+(group.focusTo-group.focusFrom)*eased;
    }
    endFocusFrame(){this.paintingFocusFrame=false;this.requestRender();}
    paintFocusNode(id,style,color){
      const r=this.nodeViews.get(id);if(!r)return;const oldRadius=r.radius;
      const geometryChanged=style.size!==r.style.size||style.lineWidth!==r.style.lineWidth||style.shadowBlur!==r.style.shadowBlur;
      Object.assign(r.style,style);if(color)r.style.shadowColor=color;
      if(geometryChanged||!this.paintingFocusFrame||!r.opacityGroups)this.paintNode(r);
      if(oldRadius!==r.radius)for(const edgeId of this.adjacent.get(id)||[]){const edge=this.edgeViews.get(edgeId);if(edge)this.positionArrows(edge);}
      if(!this.paintingFocusFrame)this.requestRender();
    }
    paintFocusEdge(id,style){const r=this.edgeViews.get(id);if(!r)return;Object.assign(r.style,style);if(!this.paintingFocusFrame||!r.opacityGroups)this.paintEdge(r);if(!this.paintingFocusFrame)this.requestRender();}
    requestRender(){if(!this.app?.renderer||this.frame!==null||this.destroyed||document.hidden)return;
      this.frame=requestAnimationFrame(()=>{this.frame=null;if(this.destroyed)return;if(this.viewportDirty)this.cull();this.app.render();});}
    cull(){
      this.viewportDirty=false;const a=this.getCanvasByViewport([-160,-80]),b=this.getCanvasByViewport([this.width+160,this.height+80]);
      const inside=(x,y,r=0)=>x+r>=a[0]&&x-r<=b[0]&&y+r>=a[1]&&y-r<=b[1];
      for(const r of this.nodeViews.values()){r.container.visible=inside(number(r.style.x),number(r.style.y),r.radius);r.label.visible=r.hasLabel&&inside(r.label.x,r.label.y,40/this.zoom);}
      for(const r of this.edgeViews.values()){const bounds=r.bounds;r.container.visible=!!bounds&&bounds[2]>=a[0]&&bounds[0]<=b[0]&&bounds[3]>=a[1]&&bounds[1]<=b[1];r.label.visible=!!bounds&&r.hasLabel&&inside(r.label.x,r.label.y,40/this.zoom);}
      if(this.nodeViews.size>180||this.edgeViews.size>700)this.cullLabels();
    }
    cullLabels(){
      // Text is useful at readable screen sizes. Budget overlapping overview
      // labels independently of graph data, with focus and neighbours first.
      const occupied=[],priority=r=>r.id===this.focus?0:this.focusNear?.has(r.id)?1:2;
      const fits=r=>{
        const [x,y]=this.getViewportByCanvas([r.label.x,r.label.y]);
        if(x<0||y<0||x>this.width||y>this.height)return false;
        const width=(r.text?.width||0)*this.zoom+6,height=(r.text?.height||0)*this.zoom+4;
        const box=[x-width/2,y-height/2,x+width/2,y+height/2];
        if(r.id!==this.focus&&occupied.some(b=>box[0]<b[2]&&box[2]>b[0]&&box[1]<b[3]&&box[3]>b[1]))return false;
        occupied.push(box);return true;
      };
      const nodes=[...this.nodeViews.values()].filter(r=>r.label.visible).sort((a,b)=>priority(a)-priority(b)||b.baseRadius-a.baseRadius);
      let count=0;for(const r of nodes){r.label.visible=count<150&&fits(r);if(r.label.visible)count++;}
      count=0;
      for(const r of this.edgeViews.values())if(r.label.visible){
        const connected=this.focus&&(r.source===this.focus||r.target===this.focus);
        r.label.visible=count<60&&(connected||this.zoom>=1.1)&&fits(r);if(r.label.visible)count++;
      }
    }
    applyViewport(){if(!this.world)return;this.world.position.set(...this.offset);this.world.scale.set(this.zoom);this.viewportDirty=true;this.requestRender();}
    async fitView(){
      await this.ready;if(!this.nodes.size)return;
      let left=Infinity,top=Infinity,right=-Infinity,bottom=-Infinity;
      for(const node of this.nodes.values()){const s=node.style||{},r=number(s.size,12)/2,x=number(s.x),y=number(s.y);left=Math.min(left,x-r-20);right=Math.max(right,x+r+20);top=Math.min(top,y-r);bottom=Math.max(bottom,y+r+28);}
      const padding=number(this.options.padding,65),range=this.options.zoomRange||[.08,6];this.cancelZoom();
      this.zoom=clamp(Math.min((this.width-padding*2)/Math.max(1,right-left),(this.height-padding*2)/Math.max(1,bottom-top)),range[0],range[1]);
      this.offset=[this.width/2-(left+right)/2*this.zoom,this.height/2-(top+bottom)/2*this.zoom];this.applyViewport();
    }
    cancelZoom(){if(this.zoomFrame!==undefined){cancelAnimationFrame(this.zoomFrame);this.zoomFrame=undefined;}this.finishZoom?.();this.finishZoom=null;this.zoomTarget=null;}
    async zoomTo(value,animation,origin){
      await this.ready;this.cancelZoom();const range=this.options.zoomRange||[.08,6],target=clamp(value,range[0],range[1]),anchor=origin||[this.width/2,this.height/2],world=this.getCanvasByViewport(anchor),start=this.zoom;
      const apply=zoom=>{this.zoom=zoom;this.offset=[anchor[0]-world[0]*zoom,anchor[1]-world[1]*zoom];this.applyViewport();};
      const duration=number(animation?.duration);this.zoomTarget=target;this.emit('beforetransform');
      if(!duration||matchMedia('(prefers-reduced-motion: reduce)').matches){apply(target);this.zoomTarget=null;this.emit('aftertransform');return;}
      await new Promise(resolve=>{this.finishZoom=resolve;const began=performance.now();const frame=now=>{const p=Math.min(1,(now-began)/duration);apply(start+(target-start)*p*p*(3-2*p));if(p<1)this.zoomFrame=requestAnimationFrame(frame);else{this.zoomFrame=undefined;this.finishZoom=null;this.zoomTarget=null;this.emit('aftertransform');resolve();}};this.zoomFrame=requestAnimationFrame(frame);});
    }
    async translateBy(delta){await this.ready;this.cancelZoom();this.offset=[this.offset[0]+delta[0],this.offset[1]+delta[1]];this.applyViewport();}
    setSize(width,height){this.width=Math.max(1,width);this.height=Math.max(1,height);this.ready.then(()=>{if(!this.destroyed){this.app.renderer.resize(this.width,this.height);this.applyViewport();}});}
    pointer(event){const rect=this.element.getBoundingClientRect();return [event.clientX-rect.left,event.clientY-rect.top];}
    hitNode(viewport){const [x,y]=this.getCanvasByViewport(viewport);let best=null,distance=Infinity;
      for(const r of this.nodeViews.values()){const d=(x-number(r.style.x))**2+(y-number(r.style.y))**2;if(d<=r.baseRadius*r.baseRadius&&d<distance){best=r.id;distance=d;}}return best;}
    hitEdge(viewport){const p=this.getCanvasByViewport(viewport),tolerance=5/this.zoom;let best=null,distance=tolerance*tolerance;
      for(const r of this.edgeViews.values()){const b=r.bounds;if(!b||p[0]<b[0]-tolerance||p[0]>b[2]+tolerance||p[1]<b[1]-tolerance||p[1]>b[3]+tolerance)continue;
        for(let i=1;i<r.points.length;i++){const a=r.points[i-1],b=r.points[i],dx=b[0]-a[0],dy=b[1]-a[1],t=clamp(((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy||1),0,1),d=(p[0]-a[0]-dx*t)**2+(p[1]-a[1]-dy*t)**2;if(d<distance){distance=d;best=r.id;}}}return best;}
    bindPointer(){
      const element=this.element;this.pointerHandlers={
        pointerdown:event=>{if(event.button!==0)return;const at=this.pointer(event),id=this.hitNode(at);this.cancelZoom();this.drag={pointer:event.pointerId,id,start:at,last:at,moved:false};element.setPointerCapture?.(event.pointerId);},
        pointermove:event=>{const at=this.pointer(event),drag=this.drag;
          if(!drag){const hit=this.hitNode(at);if(hit!==this.pointerNode){if(this.pointerNode)this.emit('node:pointerleave',{target:{id:this.pointerNode}});this.pointerNode=hit;}return;}
          if(event.pointerId!==drag.pointer)return;if(!drag.moved&&Math.hypot(at[0]-drag.start[0],at[1]-drag.start[1])<3)return;
          if(!drag.moved){drag.moved=true;if(drag.id)this.emit('node:dragstart',{target:{id:drag.id}});}
          const dx=at[0]-drag.last[0],dy=at[1]-drag.last[1];drag.last=at;
          if(drag.id){const model=this.nodes.get(drag.id),r=this.nodeViews.get(drag.id);if(!model||!r)return;
            model.style.x=number(model.style.x)+dx/this.zoom;model.style.y=number(model.style.y)+dy/this.zoom;r.style.x=model.style.x;r.style.y=model.style.y;
            r.container.position.set(model.style.x,model.style.y);this.paintNode(r);for(const id of this.adjacent.get(drag.id)||[])this.edgeGeometry(this.edgeViews.get(id));
            this.emit('node:drag',{target:{id:drag.id}});this.viewportDirty=true;this.requestRender();
          }else{this.offset=[this.offset[0]+dx,this.offset[1]+dy];this.applyViewport();}
        },
        pointerup:event=>this.endPointer(event),pointercancel:event=>this.endPointer(event,true),
        pointerleave:()=>{if(!this.drag&&this.pointerNode){this.emit('node:pointerleave',{target:{id:this.pointerNode}});this.pointerNode=null;}},
        wheel:event=>{event.preventDefault();const factor=1-clamp(event.deltaY,-50,50)*.002;this.zoomTo((this.zoomTarget??this.zoom)*factor,{duration:120},this.pointer(event));}
      };
      for(const [type,handler] of Object.entries(this.pointerHandlers))element.addEventListener(type,handler,type==='wheel'?{passive:false}:undefined);
    }
    endPointer(event,cancelled=false){
      const drag=this.drag;if(!drag||drag.pointer!==event.pointerId)return;this.drag=null;
      if(this.element.hasPointerCapture?.(event.pointerId))this.element.releasePointerCapture(event.pointerId);
      if(drag.moved&&drag.id)this.emit('node:dragend',{target:{id:drag.id}});
      else if(!cancelled&&!drag.moved){const at=this.pointer(event),id=this.hitNode(at);if(id&&id===drag.id)this.emit('node:click',{target:{id}});else if(!drag.id){const edge=this.hitEdge(at);if(edge)this.emit('edge:click',{target:{id:edge}});}}
    }
    destroy(){this.destroyed=true;this.cancelZoom();if(this.frame!==null)cancelAnimationFrame(this.frame);document.removeEventListener('visibilitychange',this.onVisibility);
      for(const [type,handler] of Object.entries(this.pointerHandlers))this.element.removeEventListener(type,handler);this.ready.then(()=>{for(const record of [...this.nodeViews.values(),...this.edgeViews.values()])this.destroyView(record);this.app.destroy(true,{children:true,context:false});for(const context of this.sharedContexts)context.destroy();});}
  }
  window.CoursePixiGraph=CoursePixiGraph;
})();
