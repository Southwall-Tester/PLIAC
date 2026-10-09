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
      if(previous?.learner.student_id!==state.learner.student_id||!state.course.nodes.some(n=>n.id===this.selected))this.selected=state.current_lesson?.node_id||state.course.nodes[0]?.id;
      if(previous?.current_lesson?.id!==state.current_lesson?.id&&state.current_lesson)this.selected=state.current_lesson.node_id;
      $('courseOverviewText').textContent=state.course.overview||'选择章节查看知识关系，沿课程路线逐节学习。';
      $('overviewChapter').innerHTML='<option value="">全部章节</option>'+state.course.chapters.map(c=>`<option value="${esc(c.id)}">${esc(c.title)}</option>`).join('');
      if(!state.course.chapters.some(c=>c.id===this.chapter))this.chapter='';$('overviewChapter').value=this.chapter;
      $('graphLink').href=`/knowledge?course_id=${encodeURIComponent(state.course.id)}&student_id=${encodeURIComponent(state.learner.student_id)}`;
      this.select(this.selected,false);this.renderSupport();this.layout();
    }
    select(id,focus=true){
      const s=this.state,n=s?.course.nodes.find(n=>n.id===id);if(!n)return;
      this.selected=id;const status=s.learner.states[id];
      $('selectedChapter').textContent=s.course.chapters.find(c=>c.id===n.chapter_id)?.title||'';
      $('selectedTitle').textContent=n.title;$('selectedDescription').textContent=n.objectives?.[0]||n.description;
      $('selectedState').textContent=labels[status.status];$('selectedReason').textContent=this.actions.displayReason(status.reason);
      $('continueLesson').textContent=!s.workspace.onboarded?'确认学习起点':s.current_lesson?.node_id===id?'继续本节':'学习这一节';
      $('selectedEvidence').hidden=!status.evidence_ids.length;
      $('selectedEvidenceBody').innerHTML=status.evidence_ids.map(ref=>{const e=s.learner.evidence.find(e=>e.id===ref);return e?`<p>${esc(e.text)}</p><small>${esc(e.created_at)}</small>`:'';}).join('');
      const pre=s.course.edges.filter(e=>e.type==='prerequisite'&&e.target===id).map(e=>s.course.nodes.find(n=>n.id===e.source)).filter(Boolean);
      $('selectedPrerequisites').innerHTML=pre.length?'相关前置知识<br>'+pre.map(n=>`<button data-prerequisite="${esc(n.id)}">${esc(n.title)}</button>`).join(''):'';
      if(focus)this.network?.setFocus(id);
      $('relationDetail').hidden=true;
      const names=s.course.knowledge_titles||{};
      $('knowledgeRelations').innerHTML='<h3>知识关系</h3>'+s.course.edges.filter(e=>e.source===id||e.target===id).map(e=>{
        const other=s.course.nodes.find(n=>n.id===(e.source===id?e.target:e.source));
        const label=e.type==='prerequisite'?(e.target===id?'前置知识':'支撑知识'):({related:'关联',confusable:'易混淆',contains:e.source===id?'包含':'属于'}[e.type]||e.type);
        return `<button data-relation="${esc(e.id)}">${esc(label)} · ${esc(names[other.id]||other.title)}</button>`;
      }).join('');
    }
    selectRelation(id){
      const g=this.state.course,e=g.edges.find(e=>e.id===id);if(!e)return;
      const name=id=>g.knowledge_titles?.[id]||g.nodes.find(n=>n.id===id)?.title||id;
      $('relationDetail').hidden=false;
      $('relationDetail').innerHTML=`<h3>${esc(name(e.source))} ${['prerequisite','contains'].includes(e.type)?'→':'—'} ${esc(name(e.target))}</h3><p>${esc(e.reason)}</p>`+(e.source_ids||[]).map(id=>g.sources.find(s=>s.id===id)).filter(Boolean).map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>`).join('');
    }
    async drawMap(){
      const state=this.state;if(!state?.course||this.mode!=='overview')return;
      if(!this.network){this.network=new NetworkView($('courseMap'),id=>this.select(id),id=>this.selectRelation(id));this.network.force.repulsion=18000;this.network.force.distance=190;}
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
    renderSupport(){
      const s=this.state,l=s.current_lesson;
      $('discussionPanel').hidden=!l;
      $('discussionHistory').innerHTML=(l?.discussions||[]).map(turn=>`<article class="discussion-turn"><p class="student-question">${esc(turn.question)}</p><div class="support-text">${esc(turn.response)}</div><small>课程讲解 · ${esc(turn.source_heading)}</small></article>`).join('');
      const demo=s.course.id==='ml_acceptance_demo';$('contextualLab').hidden=!demo||!l;
      if(demo&&l){
        const names={sample:'检查每一列数据，确定特征与预测目标。',partition:'改变训练比例，观察样本划分与重叠情况。',roles:'在实际训练中区分训练、验证和测试的职责。',accuracy:'比较准确率与混淆矩阵，查看判断正确的样本。',leakage:'观察加入事后回执怎样改变验证分数。',complexity:'修改树深度，观察训练和验证表现。',underfit:'比较浅树与较复杂模型的表现。',overfit:'比较训练与验证之间的差距。',selection:'依据验证结果选择并封存模型。',final:'对封存后的模型完成一次最终测试。'};
        $('contextualLabText').textContent=names[l.node_id]||'用本节知识完成分类实验。';
        $('lessonLabLink').href=`/ml-lab?student_id=${encodeURIComponent(s.learner.student_id)}&node_id=${encodeURIComponent(l.node_id)}`;
        const lab=s.workspace.ml_lab,active=lab?.sessions.find(x=>x.id===lab.active_id);
        $('labReturnSummary').textContent=active?`当前实验已完成 ${active.step} / 5 步，保存了 ${active.runs.length} 次训练结果。`:'';
      }
    }
    theme(){this.mapSignature=null;if(this.mode==='overview')this.drawMap();}
  }
  window.LearningHome=LearningHome;
})();
