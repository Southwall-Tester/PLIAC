/* Content-boundary pauses and learner-authored practice; no timed gates. */
class StudyPanel {
  constructor(actions) {
    this.actions = actions;
    this.cardDrafts = new Map();
    this.$ = id => document.getElementById(id);
    this.esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    this.fields = {trigger:'什么时候用',reason:'为什么这样做',steps:'关键步骤',boundary:'容易误判的地方',reflection:'我的卡点与修正'};
    this.$('lessonContent').insertAdjacentHTML('beforebegin', '<div id="recallTools" class="study-tools"><button id="recallToggle" type="button">收起讲义，试着回想</button><span id="recallState" role="status"></span></div><p id="reviewHistory" class="muted" hidden></p>');
    this.$('lessonContent').insertAdjacentHTML('afterend', '<aside id="restPrompt" class="rest-prompt" hidden><p id="restText"></p><label>回来从哪里继续<input id="resumeNote" maxlength="1000" placeholder="可以记下当前卡点"></label><div class="form-actions"><button id="takeBreak" type="button">暂存，休息一下</button><button id="skipBreak" type="button">继续学习</button></div></aside><details id="chunkEditor" class="chunk-editor"><summary>整理我的解题卡</summary><form id="chunkForm">'+Object.entries(this.fields).map(([k,v])=>`<label>${v}<textarea data-card-field="${k}" rows="2" maxlength="600"></textarea></label>`).join('')+'<button type="submit">保存解题卡</button><span id="cardStatus" role="status"></span></form></details>');
    this.$('answerText').insertAdjacentHTML('beforebegin', '<label class="confidence-label">这次回答的把握<select id="answerConfidence"><option value="">请选择</option><option value="sure">确定</option><option value="unsure">不太确定</option><option value="guess">猜的</option></select></label>');
    document.body.insertAdjacentHTML('beforeend', '<dialog id="mixedDialog"><button id="closeMixed" type="button">返回课程</button><section id="mixedPanel" class="panel" hidden><h2>混合辨析</h2><p id="mixedQuestion"></p><form id="mixedForm"><div id="mixedChoices"></div><label>判断依据<textarea id="mixedReason" rows="3" maxlength="1200" required></textarea></label><label>这次回答的把握<select id="mixedConfidence" required><option value="">请选择</option><option value="sure">确定</option><option value="unsure">不太确定</option><option value="guess">猜的</option></select></label><button type="submit">提交辨析</button></form><details id="mixedFeedback"><summary>查看已完成的辨析</summary><div id="mixedHistory"></div></details></section></dialog>');
    this.$('handbook').insertAdjacentHTML('afterend', '<div id="chunkLibrary"></div>');
    this.$('recallToggle').onclick = () => actions.run(async()=>{await actions.save();await actions.mutate('study',{lesson_id:this.state.current_lesson.id,action:this.state.current_lesson.study?.mode==='recall'?'read':'recall'});});
    this.$('takeBreak').onclick = () => actions.run(async()=>{await actions.save();const point=this.pausePoint;await actions.mutate('study',{lesson_id:this.state.current_lesson.id,action:'break',note:this.$('resumeNote').value});if(point)await actions.mutate('rest',{point_id:point.id,choice:'rest'});});
    this.$('skipBreak').onclick = () => actions.run(async()=>{await actions.save();const point=this.pausePoint;if(point)await actions.mutate('rest',{point_id:point.id,choice:'continue'});await actions.mutate('study',{lesson_id:this.state.current_lesson.id,action:'continue'});});
    document.querySelector('.tutor-column').prepend(this.$('restPrompt'));
    this.reachedBoundaries=new Set();
    document.querySelector('.navigation-footer').insertAdjacentHTML('beforeend','<button id="openMixed" type="button" hidden>综合练习</button>');
    this.$('openMixed').onclick=()=>actions.run(async()=>{await actions.save();this.$('mixedDialog').showModal();});
    this.$('closeMixed').onclick=()=>this.$('mixedDialog').close();
    this.$('chunkForm').oninput = () => {if(this.key)this.cardDrafts.set(this.key,this.cardValues());this.$('cardStatus').textContent='待保存';};
    this.$('chunkForm').onsubmit = e => {e.preventDefault();actions.run(async()=>{await this.saveCard();actions.refresh();});};
    this.$('mixedForm').oninput = () => this.saveMixedDraft();
    this.$('mixedForm').onsubmit = e => {e.preventDefault();const choice=this.$('mixedForm').querySelector('input:checked');if(!choice)return;actions.run(async()=>{await actions.save();const key=this.mixedKey;await actions.mutate('mixed',{task_id:this.state.study_activities.mixed_task.id,choice:Number(choice.value),reason:this.$('mixedReason').value,confidence:this.$('mixedConfidence').value});try{sessionStorage.removeItem(key);}catch{}this.$('mixedFeedback').open=true;});};
  }
  cardValues(){return Object.fromEntries([...this.$('chunkForm').querySelectorAll('[data-card-field]')].map(e=>[e.dataset.cardField,e.value]));}
  async saveCard(){
    if(!this.key||!this.cardDrafts.has(this.key))return;
    const key=this.key,values=this.cardDrafts.get(key),node=this.state.current_lesson.node_id;
    await this.actions.mutate('card',{node_id:node,fields:values},{renderPage:false});
    this.cardDrafts.delete(key);this.$('cardStatus').textContent='已保存';
  }
  saveMixedDraft(){if(!this.mixedKey)return;try{sessionStorage.setItem(this.mixedKey,JSON.stringify({choice:this.$('mixedForm').querySelector('input:checked')?.value,reason:this.$('mixedReason').value,confidence:this.$('mixedConfidence').value}));}catch{}}
  render(state){
    this.state=state;const l=state.current_lesson,a=state.study_activities||{},esc=this.esc;
    this.$('recallTools').hidden=!l;
    this.$('chunkEditor').hidden=!l;
    if(l){
      const study=l.study||{},recall=study.mode==='recall';
      const prior=state.learner.states[l.node_id];
      this.$('reviewHistory').hidden=!prior?.last_mastered_at;
      this.$('reviewHistory').textContent=prior?.last_mastered_at?`上次独立通过：${new Date(prior.last_mastered_at).toLocaleDateString()}${prior.due?' · 本次进行到期复测':''}`:'';
      this.$('lessonContent').hidden=recall;
      this.$('discussionPanel').hidden=recall;
      if(recall)this.$('contextualLab').hidden=true;
      this.$('chunkEditor').hidden=recall;
      this.$('recallToggle').textContent=recall?'重新打开讲义':'收起讲义，试着回想';
      this.$('recallState').textContent=study.material_reopened?'已记录回看材料':recall?'讲义已收起，先写下自己的理解':'可以对照讲义学习';
      this.$('answerConfidence').value=state.workspace.drafts[l.id]?.confidence||'';
      this.observer?.disconnect();
      this.pausePoint=state.rhythm?.current||null;
      const point=this.pausePoint,boundaryKey=point?.id;
      const reached=!!l.responses.length||this.reachedBoundaries.has(boundaryKey);
      this.$('restPrompt').hidden=!(study.paused||(point&&reached));
      this.$('restText').textContent=study.paused?'已暂存。回来后从下面记下的位置继续。':point?`这一组内容可以告一段落。可以休息约 ${point.break_minutes} 分钟，回来后${point.resume}也可以继续学习。`:'';
      this.$('resumeNote').value=study.resume_note||'';
      this.$('takeBreak').hidden=!!study.paused;
      this.$('skipBreak').textContent=study.paused?'回来继续':'继续学习';
      if(point&&!reached&&point.after.boundary!=='practice'&&!recall){
        const button=[...this.$('lessonContent').querySelectorAll('[data-paragraph]')].find(e=>e.dataset.paragraph===point.after.boundary);
        if(button){this.observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){this.reachedBoundaries.add(boundaryKey);this.$('restPrompt').hidden=false;this.observer.disconnect();}},{threshold:1});this.observer.observe(button);}
      }
      this.key=`${state.course.id}:${state.learner.student_id}:${l.node_id}`;
      const values=this.cardDrafts.get(this.key)||a.cards?.[l.node_id]?.fields||{};
      this.$('chunkForm').querySelectorAll('[data-card-field]').forEach(e=>e.value=values[e.dataset.cardField]||'');
      this.$('cardStatus').textContent=this.cardDrafts.has(this.key)?'待保存':a.cards?.[l.node_id]?'已保存':'';
      const last=l.responses.at(-1),certainty=last?.context?.confidence;
      if(certainty&&this.$('responses').lastElementChild){
        const labels={sure:'确定',unsure:'不太确定',guess:'猜的'};
        const text=`作答前：${labels[certainty]} · ${last.context.study?.mode==='recall'?'收起讲义作答':'对照材料作答'}${last.context.study?.material_reopened?' · 曾回看材料':''}`;
        const p=document.createElement('p');p.className='muted';p.textContent=text;this.$('responses').lastElementChild.prepend(p);
      }
    }
    const t=a.mixed_task;
    this.$('mixedPanel').hidden=false;
    this.$('openMixed').hidden=!t&&!(a.mixed_completed>0);
    this.$('mixedForm').hidden=!t;
    this.$('mixedQuestion').textContent=t?.question||'本组题目已完成，可以回顾判断依据。';
    const newKey=t?`pliac.mixed.${state.course.id}.${state.learner.student_id}.${t.id}`:null;
    if(this.mixedKey!==newKey){
      this.mixedKey=newKey;let draft={};try{draft=JSON.parse(sessionStorage.getItem(newKey)||'{}');}catch{}
      this.$('mixedChoices').innerHTML=(t?.options||[]).map((o,i)=>`<label class="answer-choice"><input type="radio" name="mixedChoice" value="${i}" required ${String(i)===draft.choice?'checked':''}>${esc(o)}</label>`).join('');
      this.$('mixedReason').value=draft.reason||'';this.$('mixedConfidence').value=draft.confidence||'';
    }
    this.$('mixedHistory').innerHTML=(a.mixed_history||[]).map(x=>`<article><p>${esc(x.question)}</p><strong>${x.correct?'选择正确':'再辨析一次'}</strong><p>${esc(x.explanation)}</p><p>我的依据：${esc(x.reason)}</p></article>`).join('');
    this.$('chunkLibrary').innerHTML=Object.entries(a.cards||{}).map(([id,c])=>`<article class="handbook-entry"><h3>${esc(c.title)} · 我的解题卡</h3><p>先回想使用条件和关键步骤，再展开核对。</p><details><summary>核对我的记录</summary>${Object.entries(c.fields).filter(([,v])=>v).map(([k,v])=>`<h4>${this.fields[k]}</h4><p>${esc(v)}</p>`).join('')}<small>保存于 ${esc(c.saved_at)} · ${esc(c.evidence_id)}</small></details></article>`).join('');
    for(const id of ['recallToggle','takeBreak','skipBreak'])this.$(id).disabled=!!state.course_changed;
  }
  exportCards(){return Object.values(this.state.study_activities?.cards||{}).map(c=>`${c.title} · 我的解题卡\n${Object.entries(c.fields).map(([k,v])=>`${this.fields[k]}：${v}`).join('\n')}\n证据：${c.evidence_id}\n`).join('\n');}
}
