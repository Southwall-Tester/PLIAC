/* Student course overview and reading shell. All states come from the learner API. */
(() => {
  const $=id=>document.getElementById(id);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels={unknown:'尚未学习',uncertain:'待核验',needs_review:'待补学',mastered:'当前已掌握'};
  const colors={unknown:'#a8b0b8',uncertain:'#d7b16b',needs_review:'#d28d8e',mastered:'#79b59b'};
  class LearningHome {
    constructor(actions){
      this.actions=actions;this.mode=new URLSearchParams(location.search).get('view')==='study'?'study':'overview';this.selected=null;this.state=null;this.chapter='';this.renderVersion=0;
      document.body.classList.add('student-home');
      $('onboardSlot').appendChild($('onboarding'));
      $('overviewTab').onclick=()=>actions.changeView('overview');
      $('studyTab').onclick=()=>actions.changeView('study');
      $('continueLesson').onclick=()=>{if(!this.state.workspace.onboarded){this.show('overview');$('onboarding').hidden=false;$('onboarding').scrollIntoView({behavior:'smooth',block:'start'});$('goals').focus();}else actions.study(this.selected);};
      $('overviewChapter').onchange=()=>{this.chapter=$('overviewChapter').value;this.drawMap();};
      $('mapColorMode').onchange=()=>this.drawMap();
      $('fitCourseMap').onclick=()=>this.network?.fit();
      $('selectedPrerequisites').onclick=e=>{const b=e.target.closest('[data-prerequisite]');if(b)this.select(b.dataset.prerequisite);};
      $('knowledgeRelations').onclick=e=>{const b=e.target.closest('[data-relation]');if(b)this.selectRelation(b.dataset.relation);};
      $('selectedPrerequisites').addEventListener('click',e=>{const b=e.target.closest('[data-lesson]');if(b)this.selectConcept(this.concept,b.dataset.lesson,false);});
      for(const [button,panel] of [['reportsLink','reportsPanel'],['handbookLink','handbookPanel']])$(button).onclick=()=>{this.show('study');$(panel).scrollIntoView({behavior:'smooth',block:'start'});};
    }
    show(mode){
      this.mode=mode;
      const url=new URL(location.href);url.searchParams.set('view',mode);history.replaceState(null,'',url);
      this.layout();
    }
    layout(){
      if(!this.state?.course)return;
      $('courseOverview').hidden=this.mode!=='overview';$('readingWorkspace').hidden=this.mode!=='study';
      $('reportsPanel').hidden=this.mode!=='study';$('handbookPanel').hidden=this.mode!=='study';
      $('overviewTab').setAttribute('aria-pressed',String(this.mode==='overview'));$('studyTab').setAttribute('aria-pressed',String(this.mode==='study'));
      // One next-lesson control moves with the current view.
      (this.mode==='overview'?$('overviewAdvance'):$('studyAdvance')).appendChild($('nextLesson'));
      $('nextLesson').hidden=this.mode==='overview'&&(!this.state.workspace.onboarded||!!this.state.current_lesson);
      $('continueLesson').hidden=this.mode==='overview'&&this.state.workspace.onboarded&&!this.state.current_lesson;
      if(this.mode==='overview')this.drawMap();
    }
    render(state){
      const previous=this.state;
      this.state=state;
      if(!state.course)return;
      if(!state.workspace.onboarded)this.mode='overview';
      const color=$('mapColorMode').value;
      $('mapColorMode').innerHTML=state.concept_map?'<option value="family">知识分组</option><option value="active">当前小节</option>':'<option value="family">知识分组</option><option value="mastery">掌握状态</option>';
      $('mapColorMode').value=[...$('mapColorMode').options].some(o=>o.value===color)?color:'family';
      if(previous?.learner.student_id!==state.learner.student_id||!state.course.nodes.some(n=>n.id===this.selected))this.selected=state.current_lesson?.node_id||state.course.nodes[0]?.id;
      if(previous?.current_lesson?.id!==state.current_lesson?.id&&state.current_lesson)this.selected=state.current_lesson.node_id;
      $('courseOverviewText').textContent=state.course.overview||'选择章节查看知识关系，沿课程路线逐节学习。';
      $('overviewChapter').innerHTML='<option value="">全部章节</option>'+state.course.chapters.map(c=>`<option value="${esc(c.id)}">${esc(c.title)}</option>`).join('');
      if(!state.course.chapters.some(c=>c.id===this.chapter))this.chapter='';$('overviewChapter').value=this.chapter;
      $('graphLink').href=`/knowledge?course_id=${encodeURIComponent(state.course.id)}&student_id=${encodeURIComponent(state.learner.student_id)}`;
      this.select(this.selected,false);this.renderSupport();this.renderActivities();this.layout();
    }
    renderActivities(){
      const s=this.state;if(!s?.course)return;
      const configured=s.course.activities;
      const labs=(Array.isArray(configured)?configured:[]).filter(lab=>typeof lab.href==='string'&&lab.href.startsWith('/')&&!lab.href.startsWith('//'));
      $('courseLabs').hidden=!labs.length;
      $('courseLabList').innerHTML=labs.map(lab=>{
        const url=new URL(lab.href,location.origin);
        if(url.origin!==location.origin)return '';
        url.searchParams.set('course_id',s.course.id);url.searchParams.set('student_id',s.learner.student_id);
        return `<article><h3>${esc(lab.title)}</h3><p>${esc(lab.description)}</p><a href="${esc(url.pathname+url.search)}">进入实验</a></article>`;
      }).join('');
      $('courseLabs').dataset.ready='true';
    }
    select(id,focus=true){
      const s=this.state,n=s?.course.nodes.find(n=>n.id===id);if(!n)return;
      if(s.concept_map){
        const entry=s.concept_map.entry_concepts?.[id];
        const current=s.concept_map.nodes.find(n=>n.id===this.concept&&n.lesson_ids.includes(id));
        const concept=(focus&&entry?s.concept_map.nodes.find(n=>n.id===entry):current)||s.concept_map.nodes.find(n=>n.id===entry)||s.concept_map.nodes.find(n=>n.lesson_ids.includes(id));
        if(concept){this.selectConcept(concept.id,id,focus);return;}
      }
      this.selected=id;const status=s.learner.states[id];
      $('selectedChapter').textContent=s.course.chapters.find(c=>c.id===n.chapter_id)?.title||'';
      $('selectedTitle').textContent=n.title;$('selectedDescription').textContent=n.objectives?.[0]||n.description;
      $('selectedState').textContent=labels[status.status];$('selectedReason').textContent=this.actions.displayReason(status.reason);
      $('continueLesson').textContent=!s.workspace.onboarded?'确认学习起点':s.current_lesson?.node_id===id?'继续本节':'学习这一节';
      $('selectedEvidence').hidden=!status.evidence_ids.length;
      $('selectedEvidenceBody').innerHTML=status.evidence_ids.map(ref=>{const e=s.learner.evidence.find(e=>e.id===ref);return e?`<p>${esc(e.text)}</p><small>${esc(e.created_at)}</small>`:'';}).join('');
      const pre=s.course.edges.filter(e=>e.type==='prerequisite'&&e.target===id).map(e=>s.course.nodes.find(n=>n.id===e.source)).filter(Boolean);
      $('selectedPrerequisites').innerHTML=pre.length?'相关前置知识<br>'+pre.map(n=>`<button data-prerequisite="${esc(n.id)}">${esc(n.title)}</button>`).join(''):'';
      $('relationDetail').hidden=true;
      const names=s.course.knowledge_titles||{};
      $('knowledgeRelations').innerHTML='<h3>知识关系</h3>'+s.course.edges.filter(e=>e.source===id||e.target===id).map(e=>{
        const other=s.course.nodes.find(n=>n.id===(e.source===id?e.target:e.source));
        const label=e.type==='prerequisite'?(e.target===id?'前置知识':'支撑知识'):({related:'关联',confusable:'易混淆',contains:e.source===id?'包含':'属于'}[e.type]||e.type);
        return `<button data-relation="${esc(e.id)}">${esc(label)} · ${esc(names[other.id]||other.title)}</button>`;
      }).join('');
    }
    selectConcept(id,lessonId,focus=true){
      const s=this.state,g=s.concept_map,n=g?.nodes.find(n=>n.id===id);if(!n)return;
      this.concept=id;
      const linked=n.lesson_ids.map(id=>s.course.nodes.find(l=>l.id===id)).filter(Boolean);
      const lesson=linked.find(l=>l.id===lessonId)||linked.find(l=>l.id===this.selected)||linked[0];
      this.selected=lesson.id;
      $('selectedChapter').textContent=g.groups.find(x=>x.id===n.group_id)?.title||'';
      $('selectedTitle').textContent=n.title;$('selectedDescription').textContent=n.description;
      $('selectedState').textContent='相关小节：'+lesson.title;
      $('selectedReason').textContent='小节学习状态：'+labels[s.learner.states[lesson.id].status];
      $('continueLesson').textContent=!s.workspace.onboarded?'确认学习起点':s.current_lesson?.node_id===lesson.id?'继续相关讲义':'阅读相关讲义';
      const status=s.learner.states[lesson.id];
      $('selectedEvidence').hidden=!status.evidence_ids.length;
      $('selectedEvidence').querySelector('summary').textContent='查看相关小节的学习依据';
      $('selectedEvidenceBody').innerHTML=status.evidence_ids.map(id=>s.learner.evidence.find(e=>e.id===id)).filter(Boolean).map(e=>`<p>${esc(e.text)}</p>`).join('');
      $('selectedPrerequisites').innerHTML=linked.length>1?'<p>选择相关讲义</p>'+linked.map(l=>`<button data-lesson="${esc(l.id)}" aria-pressed="${l.id===lesson.id}">${esc(l.title)}</button>`).join(''):'';
      $('knowledgeRelations').innerHTML='<h3>知识关系</h3>'+g.edges.filter(e=>e.source===id||e.target===id).map(e=>{
        const from=g.nodes.find(n=>n.id===e.source),to=g.nodes.find(n=>n.id===e.target);
        return `<button data-relation="${esc(e.id)}" title="${esc(e.reason)}">${esc(from.title)} · ${esc(e.predicate)} · ${esc(to.title)}</button>`;
      }).join('')+'<div class="concept-sources">'+n.source_ids.map(id=>g.sources.find(s=>s.id===id)).filter(Boolean).map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>`).join('')+'</div>';
      $('relationDetail').hidden=true;
    }
    selectRelation(id){
      if(this.state.concept_map){
        const g=this.state.concept_map,e=g.edges.find(e=>e.id===id);if(!e)return;
        const name=id=>g.nodes.find(n=>n.id===id).title;
        $('relationDetail').hidden=false;
        $('relationDetail').innerHTML=`<h3>${esc(name(e.source))} · ${esc(e.predicate)} · ${esc(name(e.target))}</h3><p>${esc(e.reason)}</p>`+e.source_ids.map(id=>g.sources.find(s=>s.id===id)).filter(Boolean).map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>`).join('');
        return;
      }
      const g=this.state.course,e=g.edges.find(e=>e.id===id);if(!e)return;
      const name=id=>g.knowledge_titles?.[id]||g.nodes.find(n=>n.id===id)?.title||id;
      $('relationDetail').hidden=false;
      $('relationDetail').innerHTML=`<h3>${esc(name(e.source))} ${['prerequisite','contains'].includes(e.type)?'→':'—'} ${esc(name(e.target))}</h3><p>${esc(e.reason)}</p>`+(e.source_ids||[]).map(id=>g.sources.find(s=>s.id===id)).filter(Boolean).map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>`).join('');
    }
    async drawMap(){
      const state=this.state;if(!state?.course||this.mode!=='overview')return;
      if(!this.network){this.network=new NetworkView($('courseMap'),id=>this.state.concept_map?this.selectConcept(id):this.select(id),id=>this.selectRelation(id));this.network.force.repulsion=18000;this.network.force.distance=190;}
      if(state.concept_map){await this.drawConceptMap();return;}
      const nodes=state.course.nodes.filter(n=>!this.chapter||n.chapter_id===this.chapter),ids=new Set(nodes.map(n=>n.id));
      const mastery=$('mapColorMode').value==='mastery';
      const relationNames={prerequisite:'前置',related:'关联',confusable:'易混淆',contains:'包含'};
      const data={nodes:nodes.map(n=>({id:n.id,data:{title:state.course.knowledge_titles?.[n.id]||n.title,kind:'concept',family_id:n.chapter_id},style:{size:18,fill:mastery?colors[state.learner.states[n.id]?.status||'unknown']:GraphEncoding.family(state.course.chapters.findIndex(c=>c.id===n.chapter_id))}})),edges:state.course.edges.filter(e=>ids.has(e.source)&&ids.has(e.target)).map(e=>({id:e.id,source:e.source,target:e.target,data:{label:relationNames[e.type]||e.type,type:e.type,reason:e.reason},style:{endArrow:e.type==='prerequisite'||e.type==='contains',lineDash:['confusable','related'].includes(e.type)?[4,3]:undefined,opacity:.42}}))};
      $('mapLegend').innerHTML=(mastery?Object.entries(labels).map(([id,title])=>({title,color:colors[id]})):state.course.chapters.filter(c=>!this.chapter||c.id===this.chapter).map(c=>({title:c.title,color:GraphEncoding.family(state.course.chapters.indexOf(c))}))).map(x=>`<span><i style="background:${x.color}"></i>${esc(x.title)}</span>`).join('');
      const signature=JSON.stringify(data);
      if(this.mapSignature===signature)return;
      const revision=++this.renderVersion;
      this.mapSignature=signature;
      const topology=JSON.stringify([data.nodes.map(n=>n.id),data.edges.map(e=>e.id)]),changed=topology!==this.mapTopology;this.mapTopology=topology;
      try{await this.network.setData(data,changed);if(revision!==this.renderVersion)return;$('courseMap').dataset.ready='true';}
      catch(e){$('courseMap').dataset.ready='error';this.actions.error('知识地图加载失败，可从课程目录继续学习。');console.error(e);}
    }
    async drawConceptMap(){
      const s=this.state,g=s.concept_map;
      const lessonIds=new Set(s.course.nodes.filter(n=>!this.chapter||n.chapter_id===this.chapter).map(n=>n.id));
      const nodes=g.nodes.filter(n=>n.lesson_ids.some(id=>lessonIds.has(id))),ids=new Set(nodes.map(n=>n.id));
      const active=$('mapColorMode').value==='active',lesson=s.current_lesson?.node_id;
      const fill=n=>active&&!n.lesson_ids.includes(lesson)?'#c4c8cc':GraphEncoding.family(g.groups.findIndex(x=>x.id===n.group_id));
      const data={nodes:nodes.map(n=>({id:n.id,data:{title:n.title,kind:'concept',family_id:n.group_id,lesson_ids:n.lesson_ids},style:{size:22,labelFontSize:16,fill:fill(n)}})),edges:g.edges.filter(e=>ids.has(e.source)&&ids.has(e.target)).map(e=>({id:e.id,source:e.source,target:e.target,data:{label:e.predicate,reason:e.reason,type:'concept_relation'},style:{endArrow:e.directed,lineDash:e.directed?undefined:[4,3],opacity:.42}}))};
      $('mapLegend').innerHTML=g.groups.map((x,i)=>`<span><i style="background:${GraphEncoding.family(i)}"></i>${esc(x.title)}</span>`).join('')+(active?'<span><i style="background:#c4c8cc"></i>其他小节</span>':'');
      document.querySelector('.map-relations-legend').textContent='连线标注概念关系；点击知识点查看定义与相关讲义。';
      const signature=JSON.stringify(data);if(this.mapSignature===signature)return;
      this.mapSignature=signature;const revision=++this.renderVersion;
      const topology=JSON.stringify([data.nodes.map(n=>n.id),data.edges.map(e=>e.id)]),changed=topology!==this.mapTopology;this.mapTopology=topology;
      try{await this.network.setData(data,changed);if(revision!==this.renderVersion)return;$('courseMap').dataset.ready='true';}
      catch(e){$('courseMap').dataset.ready='error';this.actions.error(e.message);}
    }
    renderSupport(){
      const s=this.state,l=s.current_lesson;
      $('discussionPanel').hidden=!l;
      $('discussionHistory').innerHTML=(l?.discussions||[]).map(turn=>`<article class="discussion-turn"><p class="student-question">${esc(turn.question)}</p><div class="support-text">${esc(turn.response)}</div><small>课程讲解 · ${esc(turn.source_heading)}</small></article>`).join('');
      const activity=(s.course.activities||[]).find(a=>a.node_prompts?.[l?.node_id]);
      $('contextualLab').hidden=!activity||!l;
      if(activity&&l){
        $('contextualLabText').textContent=activity.node_prompts[l.node_id];
        const url=new URL(activity.href,location.origin);
        if(url.origin!==location.origin)return;
        url.searchParams.set('course_id',s.course.id);url.searchParams.set('student_id',s.learner.student_id);url.searchParams.set('node_id',l.node_id);
        $('lessonLabLink').href=url.pathname+url.search;
        const lab=s.workspace.ml_lab,active=lab?.sessions.find(x=>x.id===lab.active_id);
        $('labReturnSummary').textContent=active?`当前实验已完成 ${active.step} 步，保存了 ${active.runs.length} 次训练结果。`:'';
      }
    }
    theme(){this.mapSignature=null;if(this.mode==='overview')this.drawMap();}
  }
  window.LearningHome=LearningHome;
})();
