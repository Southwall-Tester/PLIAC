/* Profile -> calibration questions -> a server-planned route. */
(() => {
  const $=id=>document.getElementById(id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const selfNames={confident:'我认为已经会了',unsure:'学过，还不确定',new:'还没学过'};
  class LearningJourney {
    constructor(actions){
      this.actions=actions;this.data=null;this.identity='';this.questionKey='';this.materialKey='';
      this.refreshVersion=0;this.submitting=false;this.autoAttemptKey='';this.submitError='';
      $('baselineForm').onsubmit=e=>{e.preventDefault();actions.run(()=>this.submit());};
      $('journeyRetry').onclick=()=>actions.run(()=>this.submit(true));
      $('beginRoute').onclick=()=>actions.resume();
      const progress=document.createElement('div');
      progress.id='journeyProgress';progress.className='journey-progress';progress.hidden=true;
      progress.innerHTML='<div id="journeyProgressBar" class="journey-progress-track" role="progressbar" aria-label="学习路线准备进度"><span></span></div><div class="journey-progress-meta"><span id="journeyElapsed"></span><span>完成后会自动显示学习路线</span></div>';
      $('journeyStatus').insertAdjacentElement('afterend',progress);
      const lesson=document.createElement('section');
      lesson.id='personalizedLesson';lesson.className='personalized-lesson';lesson.hidden=true;
      // The artifact's CSP permits only LearnMargin's bundled, hashed scripts.
      // Retain script execution for pagination/math and same-origin access for
      // the existing embedded-reader layout, with forms/navigation sandboxed.
      lesson.innerHTML='<iframe id="personalizedLessonFrame" title="本节 LearnMargin 讲义" sandbox="allow-scripts allow-same-origin" referrerpolicy="same-origin"></iframe>';
      $('lessonContent').before(lesson);
      lesson.before($('autoLesson'));
      const lessonProgress=document.createElement('progress');
      lessonProgress.id='autoLessonProgress';lessonProgress.max=100;lessonProgress.hidden=true;
      lessonProgress.setAttribute('aria-labelledby','autoLessonStatus');
      $('autoLessonStatus').after(lessonProgress);
    }
    render(state){
      if(!state.course)return;
      const identity=state.learner.student_id+':'+state.course.id+':'+state.course.version+':'+state.workspace.onboarded;
      if(identity!==this.identity){
        this.identity=identity;this.data=null;this.questionKey='';this.resetLesson();this.autoAttemptKey='';this.submitError='';
        this.submitting=false;this.submission=null;
        this.progressStartedAt=null;clearTimeout(this.timer);clearInterval(this.elapsedTimer);
        this.refresh().catch(this.actions.error);
      }
      if(this.data)this.paint(state);
      this.prepareLesson(state);
    }
    async refresh(){
      const state=this.actions.state(),identity=this.identity,version=++this.refreshVersion;
      const data=await this.actions.api('/api/learning/journey?student_id='+encodeURIComponent(state.learner.student_id));
      if(identity!==this.identity||version!==this.refreshVersion)return;
      this.data=data;this.paint(this.actions.state());this.prepareLesson(this.actions.state());
      this.prepareLesson(this.actions.state());
      clearTimeout(this.timer);
      if(data.stage==='planning')this.scheduleRefresh();
      else{
        if(data.learner_version!==this.actions.state().learner.version)await this.actions.reload();
        if(identity!==this.identity)return;
        const automaticKey=identity+':'+data.learner_version;
        if(data.stage==='assessment'&&Array.isArray(data.questions)&&!data.questions.length&&
           this.actions.state().workspace.onboarded&&!this.submitting&&this.autoAttemptKey!==automaticKey){
          this.autoAttemptKey=automaticKey;
          await this.submit();
        }
      }
    }
    scheduleRefresh(delay=1600){
      const identity=this.identity;
      clearTimeout(this.timer);
      this.timer=setTimeout(async()=>{
        try{await this.refresh();}
        catch(error){
          if(identity!==this.identity)return;
          this.actions.error(error);
          if(this.data?.stage==='planning')this.scheduleRefresh(4000);
        }
      },delay);
    }
    paint(state){
      const data=this.data,stage=data.stage;
      const hasQuestions=Array.isArray(data.questions)&&data.questions.length>0;
      $('baselinePanel').hidden=stage!=='assessment'||!hasQuestions||this.submitting;
      $('personalRoute').hidden=stage!=='ready';
      $('journeyRetry').hidden=this.submitting||!(stage==='failed'||this.submitError);
      const waiting=stage==='planning'||this.submitting;
      // Keep planning feedback visible while an existing lesson waits for its
      // updated route, including returns from a course Lab.
      $('readingWorkspace').before($('journeyStatus'),$('journeyProgress'),$('journeyRetry'));
      const progress=stage==='planning'?data.progress:null;
      $('journeyStatus').hidden=!waiting&&stage!=='failed'&&!this.submitError;
      const phaseLabels={preparing:'正在整理学习目标和已有基础…',model_wait:'AI 正在分析学习起点、安排路线…',validating:'正在核对学习路线与先修关系…',saving:'正在保存你的学习路线…'};
      $('journeyStatus').textContent=waiting?(progress?.label||phaseLabels[progress?.phase]||
        (this.submitting?'正在提交学习起点…':'正在安排你的学习路线…')):this.submitError||data.error||'';
      this.paintProgress(waiting,progress);
      $('journeySteps').textContent=stage==='ready'?'根据你的学习目标和起点安排':
        hasQuestions?'1 学习起点　→　2 已学内容简短核验　→　3 你的路线':'1 学习起点　→　2 安排路线　→　3 开始学习';
      if(stage==='assessment'&&hasQuestions){
        const key=state.learner.student_id+JSON.stringify(data.questions);
        if(this.questionKey!==key){
          this.questionKey=key;
          $('baselineQuestions').innerHTML=data.questions.map((q,i)=>`<section class="baseline-question"><h3>${i+1}. ${esc(q.title)}</h3><small>你的自评：${esc(selfNames[q.self_assessment]||'待核验')}</small><p>${esc(q.question)}</p><label class="sr-only" for="baseline-${i}">回答：${esc(q.title)}</label><textarea id="baseline-${i}" data-baseline="${esc(q.node_id)}" required maxlength="2000" placeholder="简单写下你的理解和判断理由。"></textarea></section>`).join('');
          for(const input of document.querySelectorAll('[data-baseline]')){
            const saved=data.answers?.find(a=>a.node_id===input.dataset.baseline);
            let draft='';try{draft=localStorage.getItem(this.draftKey(input.dataset.baseline))||'';}catch{}
            input.value=draft||saved?.text||'';
            input.oninput=()=>{try{localStorage.setItem(this.draftKey(input.dataset.baseline),input.value);}catch{}};
          }
        }
      }
      if(stage==='ready'){
        const route=data.route;
        $('routeSummary').textContent=route.summary;
        const calibrationLabels={overestimated:'发现了需要补强的环节',calibrated_confident:'本次核验支持你的自评',underestimated:'表现比自评更熟练',new:'从基础开始',needs_more_evidence:'继续用练习核验'};
        const calibration=route.calibration||[];
        $('entryCalibration').innerHTML=calibration.length?'<details class="entry-calibration"><summary>起点核验结果</summary>'+calibration.map(c=>`<p><strong>${esc(state.course.nodes.find(n=>n.id===c.node_id)?.title||c.node_id)}</strong> · ${esc(calibrationLabels[c.calibration||c.category||c.status]||c.label||'已记录本次表现')}</p><p>${esc(c.reason||'')}</p>${c.quote?`<blockquote>${esc(c.quote)}</blockquote>`:''}`).join('')+'</details>':'';
        const studied=new Set(state.workspace.lessons.map(l=>l.node_id));
        $('routeSteps').innerHTML=route.steps.map(step=>{
          const status=state.learner.states[step.node_id]?.status;
          const progress=status==='mastered'?'已核验':state.current_lesson?.node_id===step.node_id?'当前学习':studied.has(step.node_id)?'已学习 · 继续核验':'尚未学习';
          return `<li data-route-node="${esc(step.node_id)}"><h3>${esc(step.title)}</h3><small>${progress} · ${{slow:'分步练习',steady:'逐步学习',quick:'快速核验'}[step.pace]||'逐步学习'}</small><p>${esc(step.reason)}</p><p>${esc(step.focus)}</p></li>`;
        }).join('');
        $('beginRoute').textContent=state.current_lesson?'继续学习':'开始学习';
      }
      this.actions.availability?.();
    }
    paintProgress(waiting,progress){
      $('journeyProgress').hidden=!waiting;
      $('journeyProgressBar').setAttribute('aria-valuetext',$('journeyStatus').textContent);
      clearInterval(this.elapsedTimer);
      if(!waiting){this.progressStartedAt=null;return;}
      const serverStart=Date.parse(progress?.started_at||'');
      if(Number.isFinite(serverStart))this.progressStartedAt=serverStart;
      else if(!this.progressStartedAt)this.progressStartedAt=Date.now();
      const tick=()=>{
        const seconds=Math.max(0,Math.floor((Date.now()-this.progressStartedAt)/1000));
        $('journeyElapsed').textContent='已用时 '+(seconds<60?seconds+' 秒':Math.floor(seconds/60)+' 分 '+seconds%60+' 秒');
      };
      tick();this.elapsedTimer=setInterval(tick,1000);
    }
    draftKey(node){const s=this.actions.state();return `pliac.baseline.${s.learner.student_id}.${s.course.id}.${node}`;}
    async submit(retry=false){
      if(this.submitting)return;
      const s=this.actions.state(),identity=this.identity;
      if(!s.workspace.onboarded)return;
      const pendingKey=`pliac.journey.pending.${s.learner.student_id}.${s.course.id}.${s.course.version}`;
      const submission={identity};this.submission=submission;
      this.submitting=true;this.submitError='';this.progressStartedAt=null;++this.refreshVersion;clearTimeout(this.timer);
      if(this.data)this.paint(s);
      try{
        const latest=await this.actions.api('/api/learning/journey?student_id='+encodeURIComponent(s.learner.student_id));
        if(identity!==this.identity)return;
        // A refreshed page or another tab may already have started this plan.
        if(['planning','ready'].includes(latest.stage)){
          this.data=latest;
          try{localStorage.removeItem(pendingKey);}catch{}
        }else{
          const questions=latest.questions||[],expected=new Set(questions.map(q=>q.node_id));
          const answers=questions.length?(retry&&latest.stage==='failed'?latest.answers:
            [...document.querySelectorAll('[data-baseline]')].filter(i=>expected.has(i.dataset.baseline)).map(i=>({node_id:i.dataset.baseline,text:i.value.trim()}))):[];
          if(answers?.length!==questions.length||answers.some(a=>!a.text))throw Error('请简单写下每题的理解和判断理由。');
          const body={student_id:s.learner.student_id,course_version:s.course.version,expected_version:latest.learner_version,answers};
          const signature=JSON.stringify(body);
          let pending;
          try{pending=JSON.parse(localStorage.getItem(pendingKey)||'null');}catch{}
          const request_id=pending?.signature===signature?pending.request_id:crypto.randomUUID();
          try{localStorage.setItem(pendingKey,JSON.stringify({signature,request_id}));}catch{}
          const accepted=await this.actions.api('/api/learning/journey/assessment',{...body,request_id});
          try{localStorage.removeItem(pendingKey);}catch{}
          if(identity!==this.identity)return;
          this.data=accepted;
          for(const a of answers)try{localStorage.removeItem(this.draftKey(a.node_id));}catch{}
        }
      }catch(error){
        if(identity!==this.identity)return;
        // Concurrent tabs can race the version check while sharing one plan.
        if(error.status===409){
          const current=await this.actions.api('/api/learning/journey?student_id='+encodeURIComponent(s.learner.student_id));
          if(identity!==this.identity)return;
          if(['planning','ready'].includes(current.stage)){this.data=current;this.submitError='';}
          else{this.submitError=error.message;throw error;}
        }else{this.submitError=error.message;throw error;}
      }finally{
        if(this.submission===submission){
          this.submitting=false;this.submission=null;
          if(identity===this.identity&&this.data)this.paint(this.actions.state());
        }
      }
      if(identity===this.identity)await this.refresh();
    }
    ready(){return this.data?.stage==='ready';}
    resetLesson(){
      clearTimeout(this.materialTimer);clearInterval(this.frameTimer);this.frameResize?.disconnect();
      this.materialTask=null;this.materialKey='';
      const frame=$('personalizedLessonFrame');
      frame.onload=null;frame.onerror=null;frame.removeAttribute('src');delete frame.dataset.ready;
      frame.style.height='';$('personalizedLesson').hidden=true;
      $('readingWorkspace').classList.remove('has-personalized-lesson');
      $('autoLessonProgress').hidden=true;
    }
    applyLessonView(state){
      const current=state.current_lesson,task=this.materialTask;
      const matching=task&&current?.id===task.lessonId&&state.learner.student_id===task.studentId&&state.course.id===task.courseId;
      const recall=current?.study?.mode==='recall',ready=matching&&$('personalizedLessonFrame').dataset.ready==='true';
      $('readingWorkspace').classList.toggle('has-personalized-lesson',!!ready);
      $('personalizedLesson').hidden=!matching||recall||!task.jobId||!$('personalizedLessonFrame').getAttribute('src');
      $('lessonContent').hidden=!!recall||!!ready;
      if(ready&&!recall)window.PLIACAssistant?.setContext({course_id:task.courseId,node_id:task.nodeId,job_id:task.jobId,title:current.title});
    }
    lessonStatus(job,task){
      if(task!==this.materialTask)return;
      task.jobId=job.id;
      $('autoLessonLink').hidden=false;
      const busy=['queued','running'].includes(job.status),progress=Number(job.progress);
      $('autoLessonProgress').hidden=!busy;
      if(Number.isFinite(progress))$('autoLessonProgress').value=Math.max(0,Math.min(100,progress));
      else $('autoLessonProgress').removeAttribute('value');
      if(job.status==='completed'){
        $('autoLessonStatus').textContent='讲义已准备好，正在打开…';
        $('autoLessonLink').textContent='完整阅读、图谱与重新生成';
        this.openLesson(job,task);
      }else if(busy){
        $('autoLessonStatus').textContent=(job.stage||'正在准备本节讲义')+(Number.isFinite(progress)?' · '+progress+'%':'')+'；可以先读下面的课程讲解。';
        $('autoLessonLink').textContent='打开本节讲义与进度';
        this.pollLesson(task);
      }else{
        $('autoLessonStatus').textContent=(job.error||'本节讲义准备已暂停。')+' 课程讲解仍可阅读。';
        $('autoLessonLink').textContent='打开讲义并重新生成';
      }
    }
    pollLesson(task,delay=2000){
      clearTimeout(this.materialTimer);
      this.materialTimer=setTimeout(async()=>{
        if(task!==this.materialTask)return;
        const query=new URLSearchParams({student_id:task.studentId,node_id:task.nodeId,job_id:task.jobId});
        try{
          const data=await this.actions.api('/api/handouts?'+query);
          if(task!==this.materialTask)return;
          const job=data.jobs?.find(item=>item.id===task.jobId);
          if(!job)throw Error('本节讲义记录已更新，请打开完整阅读查看。');
          this.lessonStatus(job,task);
        }catch(error){
          if(task!==this.materialTask)return;
          $('autoLessonStatus').textContent='正在恢复讲义进度查询。'+error.message;
          if(!error.status||error.status>=500)this.pollLesson(task,4000);
          else $('autoLessonProgress').hidden=true;
        }
      },delay);
    }
    openLesson(job,task){
      if(task!==this.materialTask)return;
      const frame=$('personalizedLessonFrame'),container=$('personalizedLesson');
      const query=new URLSearchParams({course_id:task.courseId,student_id:task.studentId});
      const url='/api/handouts/'+encodeURIComponent(job.id)+'/artifacts/lesson.html?'+query;
      if(frame.getAttribute('src')===url){this.applyLessonView(this.actions.state());return;}
      delete frame.dataset.ready;container.dataset.loading='true';container.hidden=false;
      const failed=message=>{
        if(task!==this.materialTask)return;
        clearInterval(this.frameTimer);container.hidden=true;task.jobId='';
        $('autoLessonStatus').textContent=message+' 课程讲解仍可阅读。';
        this.applyLessonView(this.actions.state());
      };
      frame.onerror=()=>failed('讲义暂时未能打开。');
      frame.onload=()=>{
        if(task!==this.materialTask||!frame.getAttribute('src'))return;
        let count=0;clearInterval(this.frameTimer);
        this.frameTimer=setInterval(()=>{
          if(task!==this.materialTask){clearInterval(this.frameTimer);return;}
          let doc,report;
          try{doc=frame.contentDocument;report=frame.contentWindow?.learnmarginReport;}
          catch{failed('请从完整阅读打开这份讲义。');return;}
          if(++count>300){failed('讲义排版尚未完成，请从完整阅读重新打开。');return;}
          if(!doc||doc.URL==='about:blank')return;
          if(doc.contentType!=='text/html'){failed('讲义暂时未能打开，请从完整阅读重试。');return;}
          if(doc.querySelector('#flow')&&!report)return;
          if(report?.error){failed('讲义排版暂未完成，请打开完整阅读或 PDF。');return;}
          clearInterval(this.frameTimer);
          if(!doc.body?.textContent.trim()){failed('讲义内容暂未加载。');return;}
          doc.documentElement.classList.add('embedded-reader');
          // Source lookup remains available in the full reader; retain its
          // in-document reference links without leaving inactive buttons here.
          doc.querySelectorAll('.web-source-button').forEach(button=>button.remove());
          doc.addEventListener('click',event=>{
            const link=event.target.closest?.('a[href]');
            if(!link||link.getAttribute('href').startsWith('#'))return;
            event.preventDefault();
            const destination=new URL(link.href,doc.URL);
            if(['http:','https:'].includes(destination.protocol))window.open(destination.href,'_blank','noopener,noreferrer');
          });
          const resize=()=>{
            if(task!==this.materialTask||doc!==frame.contentDocument)return;
            const height=Math.max(420,Math.ceil(doc.body.getBoundingClientRect().height));
            if(frame.style.height!==height+'px')frame.style.height=height+'px';
          };
          frame.dataset.ready='true';delete container.dataset.loading;
          $('autoLessonStatus').textContent='本节讲义已准备好。';
          this.applyLessonView(this.actions.state());
          this.frameResize?.disconnect();this.frameResize=new ResizeObserver(resize);this.frameResize.observe(doc.body);
          frame.contentWindow.requestAnimationFrame(resize);
        },100);
      };
      frame.src=url;
    }
    async prepareLesson(state){
      const current=state.current_lesson;
      if(!current){if(this.materialTask)this.resetLesson();$('autoLesson').hidden=true;return;}
      this.applyLessonView(state);
      if(this.data?.stage!=='ready')return;
      const key=state.learner.student_id+':'+state.course.id+':'+state.course.version+':'+current.id+':'+this.data.assessment_id;
      if(key===this.materialKey)return;
      this.resetLesson();
      const task={key,studentId:state.learner.student_id,courseId:state.course.id,nodeId:current.node_id,lessonId:current.id};
      this.materialTask=task;this.materialKey=key;
      this.applyLessonView(state);
      $('autoLesson').hidden=false;$('autoLessonLink').hidden=false;
      $('autoLessonProgress').hidden=false;$('autoLessonProgress').removeAttribute('value');
      $('autoLessonStatus').textContent='正在准备适合本节的学习内容，课程讲解和练习可以先学。';
      const query=new URLSearchParams({course_id:state.course.id,student_id:state.learner.student_id,node_id:current.node_id,view:'read'});
      $('autoLessonLink').href='/course-reader?'+query;
      $('autoLessonLink').textContent='完整阅读与重新生成';
      $('handoutLink').href=$('autoLessonLink').href;$('handoutLink').hidden=false;
      try{
        const account=await window.PLIACAccountReady;
        if(task!==this.materialTask)return;
        const job=await this.actions.api('/api/handouts/prepare',{student_id:state.learner.student_id,scope:{node_id:current.node_id},...(account?.user?{assistant_owner:account.user.assistant_owner}:{})});
        if(task!==this.materialTask)return;
        this.lessonStatus(job,task);
      }catch(e){
        if(task!==this.materialTask)return;
        $('autoLessonProgress').hidden=true;
        $('autoLessonStatus').textContent='课程讲解和练习已就绪。'+e.message;
      }
    }
  }
  window.LearningJourney=LearningJourney;
})();
