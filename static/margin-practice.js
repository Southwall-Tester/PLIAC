/* Generated exercises keep raw attempts in the course's shared learner store. */
(() => {
  const $=id=>document.getElementById(id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  class HandoutPractice {
    constructor(courseId,fail){
      this.courseId=courseId;this.fail=fail;this.job=null;this.state=null;this.busy=false;this.revision=0;this.sections=[];
      this.storageKey='pliac.student.'+courseId;
      let student=new URLSearchParams(location.search).get('student_id');
      try{student ||= localStorage.getItem(this.storageKey);}catch{}
      $('practiceStudent').value=student||'learner-'+crypto.randomUUID().slice(0,8);
      this.accountReady=(window.PLIACAccountReady ||= fetch('/api/account/me').then(async response=>{
        if(response.status===401){location.assign('/login?next='+encodeURIComponent(location.pathname+location.search));return null;}
        return response.ok?response.json():{testing:true};
      })).then(account=>{
        if(account?.user){this.account=account.user;$('practiceStudent').value=account.user.student_id;
          $('practiceStudent').readOnly=true;$('practiceStudent').closest('label').hidden=true;$('loadPractice').hidden=true;}
        return account;
      });
      $('loadPractice').onclick=()=>this.load(this.job).catch(fail);
      $('practiceStatus').insertAdjacentHTML('afterend','<button id="practiceRetry" type="button" hidden>重新准备题目选项</button>');
      $('practiceRetry').onclick=()=>this.load(this.job).catch(fail);
      $('practiceQuestions').onclick=e=>{const b=e.target.closest('[data-action]');if(b)this.act(b.dataset.action,b.dataset.question).catch(fail);};
    }
    reset(){this.revision++;this.job=null;this.state=null;$('practiceQuestions').replaceChildren();$('practiceProgress').textContent='';$('practiceRetry').hidden=true;}
    async request(body){
      if(!await this.accountReady)throw new Error('请先登录。');
      const student=$('practiceStudent').value.trim();
      if(!/^[A-Za-z0-9_-]{1,80}$/.test(student))throw new Error('学习编号只能包含字母、数字、下划线或短横线。');
      const response=await fetch(`/api/handouts/${this.job}/practice?${new URLSearchParams({course_id:this.courseId,student_id:student})}`,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
      const data=await response.json();if(!response.ok)throw new Error(data.detail||'练习读取失败。');
      try{localStorage.setItem(this.storageKey,student);}catch{}
      return data;
    }
    async load(job){
      if(!job){$('practiceStatus').textContent='生成本范围的学习单元后，即可在这里作答。';return;}
      const revision=++this.revision;this.job=job;
      this.state=null;$('practiceQuestions').replaceChildren();$('practiceProgress').textContent='';
      $('practiceStatus').textContent='正在准备本单元题目选项…';$('practiceRetry').hidden=true;
      try{
        const state=await this.request();if(revision!==this.revision)return;
        this.state=state;this.render();$('practiceStatus').textContent='';
      }catch(error){
        if(revision===this.revision){$('practiceStatus').textContent='题目选项准备未完成，可以重试。';$('practiceRetry').hidden=false;}
        throw error;
      }
    }
    render(){
      const data=this.state;
      $('practiceProgress').textContent=`已作答 ${data.answered} / ${data.total} 题`;
      $('practiceQuestions').innerHTML=data.questions.map((q,i)=>{
        const responses=data.responses.filter(r=>r.question_id===q.id);
        const action=(kind,label)=>`<button type="button" data-action="${kind}" data-question="${esc(q.id)}">${label}</button>`;
        const options=(q.options||[]).map(o=>`<label><input type="radio" name="practice-${esc(q.id)}" value="${esc(o.id)}" ${data.choice_drafts?.[q.id]===o.id?'checked':''}><span><strong>${esc(o.id)}.</strong> ${esc(o.text)}</span></label>`).join('');
        return `<article class="practice-card" data-practice="${esc(q.id)}"><p class="practice-section">${esc(q.section_title)}</p><h3>练习 ${i+1}</h3><p class="practice-prompt">${esc(q.prompt)}</p><fieldset class="practice-options"><legend>选择你的答案</legend>${options}</fieldset><details class="practice-supplement"><summary>补充说明（可选）</summary><textarea maxlength="4000" rows="3" aria-label="练习 ${i+1} 的补充说明" placeholder="选好答案即可提交，也可以补充你的思路。">${esc(data.drafts[q.id]||'')}</textarea></details><div class="practice-actions">${action('answer','提交作答')}${action('draft','保存草稿')}${action('hint','查看提示')}${action('solution','核对参考答案')}</div>${q.hint!==null?`<p class="practice-hint">提示：${esc(q.hint)}</p>`:''}${q.answer!==null?`<div class="practice-solution"><h4>参考答案</h4><p>${esc(q.answer)}</p></div>`:''}<div class="practice-history">${responses.map(r=>`<details><summary>已保存作答 · ${r.exposure===2?'看过参考答案':r.exposure===1?'使用过提示':'未打开本题提示'}</summary><p>${esc(r.text)}</p></details>`).join('')}</div><button type="button" data-section="section-${this.sections.indexOf(q.section_id)+1}">返回相关讲解</button></article>`;
      }).join('')||'<p>这份旧讲义尚未包含习题，可以生成一份完整学习单元。</p>';
    }
    async act(operation,question){
      if(this.busy||!this.state)return;
      if($('practiceStudent').value.trim()!==this.state.student_id)throw new Error('切换学习编号后，请先读取对应记录。');
      const drafts=new Map([...$('practiceQuestions').querySelectorAll('[data-practice]')].map(card=>[card.dataset.practice,card.querySelector('textarea').value]));
      const choices=new Map([...$('practiceQuestions').querySelectorAll('[data-practice]')].map(card=>[card.dataset.practice,card.querySelector('input[type=radio]:checked')?.value||'']));
      const text=drafts.get(question)||'';
      const choice_id=choices.get(question)||'',item=this.state.questions.find(q=>q.id===question);
      if(operation==='answer'&&!choice_id)throw new Error('请选择一个答案，补充说明可以留空。');
      this.busy=true;$('practiceQuestions').querySelectorAll('button').forEach(b=>b.disabled=true);
      const signature=JSON.stringify([this.job,operation,question,text,choice_id,item.option_set_id]);
      if(this.receipt?.signature!==signature)this.receipt={signature,id:crypto.randomUUID()};
      const revision=this.revision;
      try{
        const result=await this.request({student_id:this.state.student_id,expected_version:this.state.version,
          request_id:this.receipt.id,operation,question_id:question,text,choice_id,option_set_id:item.option_set_id});
        if(revision!==this.revision)return;
        this.state=result;this.receipt=null;this.render();
        for(const card of $('practiceQuestions').querySelectorAll('[data-practice]'))if(operation!=='answer'||card.dataset.practice!==question){
          card.querySelector('textarea').value=drafts.get(card.dataset.practice)||'';
          for(const input of card.querySelectorAll('input[type=radio]'))input.checked=input.value===choices.get(card.dataset.practice);
        }
        $('practiceStatus').textContent=operation==='answer'?'作答已保存。':operation==='draft'?'草稿已保存。':'已记录本题的提示使用情况。';
      }catch(error){
        // Refresh the revision while preserving unsaved text after a tab conflict.
        if(revision===this.revision){const state=await this.request().catch(()=>this.state);if(revision===this.revision)this.state=state;}throw error;
      }finally{this.busy=false;$('practiceQuestions').querySelectorAll('button').forEach(b=>b.disabled=false);}
    }
  }
  window.HandoutPractice=HandoutPractice;
})();
