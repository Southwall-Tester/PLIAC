/* Render server-reported work; local timers measure elapsed time only. */
(() => {
  const busyStates=new Set(['queued','running']);
  const terminalStates=new Set(['completed','failed','cancelled']);
  const stamp=value=>{const time=Date.parse(value||'');return Number.isFinite(time)?time:null;};
  const count=value=>Number.isFinite(Number(value))&&Number(value)>=0?Math.floor(Number(value)):0;
  const duration=milliseconds=>{
    const seconds=Math.max(0,Math.floor(milliseconds/1000));
    if(seconds<60)return seconds+' 秒';
    if(seconds<3600)return Math.floor(seconds/60)+' 分 '+seconds%60+' 秒';
    return Math.floor(seconds/3600)+' 小时 '+Math.floor(seconds%3600/60)+' 分';
  };
  class HandoutProgress {
    constructor(host,{compact=false,progressId=''}={}){
      this.host=host;this.job=null;this.terminalAt=null;
      host.classList.add('handout-progress');host.dataset.compact=String(compact);host.hidden=true;
      host.innerHTML='<div class="hp-heading"><p class="hp-task" role="status"></p><span class="hp-overall"></span></div><progress class="hp-bar" max="100" aria-label="讲义总体生成进度"></progress><div class="hp-metrics"><span class="hp-elapsed"></span><span class="hp-stage-elapsed"></span><span class="hp-sections"></span></div><p class="hp-response"></p><progress class="hp-activity" aria-label="当前任务正在处理" hidden></progress><ol class="hp-steps" aria-label="讲义生成步骤"></ol><details class="hp-details"><summary>查看正在处理的任务</summary><ul class="hp-tasks"></ul></details>';
      this.nodes=Object.fromEntries(['task','overall','bar','elapsed','stage-elapsed','sections','response','activity','steps','details','tasks'].map(name=>[name,host.querySelector('.hp-'+name)]));
      if(progressId)this.nodes.bar.id=progressId;
      this.nodes.details.open=!compact;
      window.addEventListener('pagehide',()=>this.stop());
    }
    stop(){clearInterval(this.timer);this.timer=null;}
    clear(){this.stop();this.job=null;this.terminalAt=null;this.host.hidden=true;}
    update(job){
      this.stop();
      if(!job){this.clear();return;}
      if(job.id!==this.job?.id)this.terminalAt=null;
      this.job=job;this.host.hidden=false;this.host.dataset.status=job.status;
      const detail=job.progress_detail||{},busy=busyStates.has(job.status),terminal=terminalStates.has(job.status);
      if(terminal&&!this.terminalAt)this.terminalAt=stamp(detail.finished_at)||stamp(job.completed_at)||stamp(job.updated_at);
      this.nodes.task.textContent=detail.current_task||job.stage||({queued:'等待开始',running:'正在准备讲义',completed:'讲义已完成',failed:'本次准备未完成',cancelled:'已取消生成'}[job.status])||'学习内容准备';
      const progress=typeof job.progress==='number'&&Number.isFinite(job.progress)?Math.max(0,Math.min(100,job.progress)):null;
      this.nodes.overall.textContent=progress===null?'':'总体进度 '+progress+'%';
      this.nodes.overall.hidden=progress===null;
      if(progress===null)this.nodes.bar.removeAttribute('value');else this.nodes.bar.value=progress;
      this.nodes.bar.hidden=!busy;
      const sections=detail.sections||{};
      this.nodes.sections.hidden=!count(sections.total);
      this.nodes.sections.textContent='讲解小节 '+count(sections.completed)+' / '+count(sections.total)+' 已完成';
      this.nodes.steps.replaceChildren();
      for(const [index,step] of (Array.isArray(detail.steps)?detail.steps:[]).entries()){
        const item=document.createElement('li');item.className='hp-step';item.dataset.state=step.status||'pending';
        if(step.status==='running')item.setAttribute('aria-current','step');
        const marker=document.createElement('span');marker.className='hp-step-marker';marker.setAttribute('aria-hidden','true');
        marker.textContent=step.status==='completed'?'✓':step.status==='failed'?'!':step.status==='cancelled'?'–':String(index+1);
        const label=document.createElement('span');label.textContent=step.label||step.id||'';
        item.append(marker,label);this.nodes.steps.append(item);
      }
      this.nodes.steps.hidden=!this.nodes.steps.childElementCount;
      const tasks=Array.isArray(detail.tasks)?detail.tasks:[];
      const active=busy?tasks.filter(task=>['running','waiting','retrying','validating'].includes(task.status)):[];
      const recent=tasks.filter(task=>task.status==='completed').slice(-2);
      this.nodes.tasks.replaceChildren();
      for(const task of [...active.slice(0,6),...recent]){
        const item=document.createElement('li');
        const parts=[(task.status==='completed'?'已完成：':'正在处理：')+(task.label||'当前任务')];
        if(count(task.received_chars))parts.push('已接收 '+count(task.received_chars).toLocaleString()+' 字符');
        const modelState={waiting:'等待模型回复',streaming:'正在接收',retrying:'模型重试中',validating:'核对内容中',completed:'模型回复已收到'}[task.model_status];
        if(task.status!=='completed'&&modelState)parts.push(modelState);
        if(task.status!=='completed'&&count(task.model_attempt)>1)parts.push('第 '+count(task.model_attempt)+' 次请求');
        item.dataset.state=task.status;item.textContent=parts.join(' · ');
        this.nodes.tasks.append(item);
      }
      this.nodes.details.hidden=!this.nodes.tasks.childElementCount;
      this.nodes.activity.hidden=!busy||!detail.request||terminalStates.has(detail.request.status);
      this.tick();
      if(busy)this.timer=setInterval(()=>this.tick(),1000);
    }
    tick(){
      if(!this.job)return;
      const job=this.job,detail=job.progress_detail||{},now=this.terminalAt||Date.now();
      const start=stamp(detail.started_at)||stamp(job.started_at)||stamp(job.created_at);
      const stageStart=stamp(detail.stage_started_at);
      const measured=busyStates.has(job.status)||this.terminalAt!==null;
      this.nodes.elapsed.hidden=start===null||!measured;
      this.nodes.elapsed.textContent=start===null||!measured?'':'已用时 '+duration(now-start);
      this.nodes['stage-elapsed'].hidden=stageStart===null||!busyStates.has(job.status);
      this.nodes['stage-elapsed'].textContent=stageStart===null?'':'当前阶段 '+duration(now-stageStart);
      const request=detail.request;
      if(!request){this.nodes.response.hidden=true;this.nodes.response.textContent='';return;}
      this.nodes.response.hidden=false;
      const parts=[],status=request.status,received=count(request.received_chars),reasoning=count(request.reasoning_chars);
      const requestStart=stamp(request.started_at),last=stamp(request.last_received_at);
      if(status==='waiting')parts.push(request.transport==='json'?'正在等待模型完整回复':'正在等待模型回复');
      else if(status==='streaming')parts.push('正在接收模型回复');
      else if(status==='validating')parts.push('正在核对生成内容');
      else if(status==='retrying')parts.push('正在重新请求模型');
      else if(status==='completed')parts.push('本轮模型回复已收到');
      else if(status==='failed')parts.push('本轮模型请求未完成');
      else if(status==='cancelled')parts.push('模型请求已取消');
      if(received)parts.push('已接收 '+received.toLocaleString()+' 字符');
      if(reasoning)parts.push('思考输出 '+reasoning.toLocaleString()+' 字符');
      if(busyStates.has(job.status)&&!terminalStates.has(status)){
        if(last!==null)parts.push('最近响应 '+duration(now-last)+'前');
        else if(requestStart!==null)parts.push('已等待 '+duration(now-requestStart));
      }
      if(busyStates.has(job.status)&&count(request.active_count)>1)parts.push(count(request.active_count)+' 个任务正在处理');
      if(count(request.total_count)>0||count(request.completed_count)>0)parts.push('已完成 '+count(request.completed_count)+' 次生成');
      if(count(request.attempt)>1)parts.push('第 '+count(request.attempt)+' 次请求');
      this.nodes.response.textContent=parts.join(' · ');
    }
  }
  window.HandoutProgress=HandoutProgress;
})();
