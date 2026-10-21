(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const params=new URLSearchParams(location.search),previewing=location.pathname==='/preview';
  let courses=[],progress=new Map(),account=null,previewData=null,loadVersion=0;
  const courseUrl=(path,id)=>path+'?'+new URLSearchParams({course_id:id});
  const studyUrl=course=>courseUrl('/learn',course.id)+(progress.get(course.id)?.current?'&view=study':'');
  const actionLabel=course=>progress.get(course.id)?.onboarded?'继续学习':'开始学习';
  $('themeButton').onclick=()=>GraphTheme.toggle();
  const loginReturn=()=>{$('accountLink').href='/login?next='+encodeURIComponent(location.pathname+location.search);};
  loginReturn();
  $('dashboard').hidden=previewing;$('preview').hidden=!previewing;
  if(!previewing)$('homeNav').setAttribute('aria-current','page');
  async function request(path){
    const response=await fetch(path,{cache:'no-store'});
    if(!response.ok){let data;try{data=await response.json();}catch{}throw Error(data?.detail||'内容暂时未能加载，请重试。');}
    return response.json();
  }
  function showError(error){$('pageError').textContent=error.message||'连接中断，请重试。';$('pageError').hidden=false;$('retryLoad').hidden=false;}
  function meter(state){return state?`<div class="course-progress"><progress max="${Math.max(1,state.total)}" value="${state.passed}" aria-label="已通过小节"></progress><span>${state.studied} 节已学 · ${state.passed} / ${state.total} 节已通过</span></div>`:'';}
  function renderCourses(){
    const query=$('courseSearch').value.trim().toLowerCase();
    const filtered=courses.filter(c=>(c.title+' '+c.description).toLowerCase().includes(query));
    $('catalogStatus').textContent=filtered.length?`${filtered.length} 门课程`:query?'没有找到相关课程，换个关键词试试。':'课程正在准备中。';
    $('courseList').innerHTML=filtered.map((c,i)=>`<article class="course-card" data-course-id="${esc(c.id)}"><div class="course-cover"><span>${esc(c.label)}</span><span class="book-number" aria-hidden="true">${String(i+1).padStart(2,'0')}</span></div><div class="course-body"><h3>${esc(c.title)}</h3><p>${esc(c.description)}</p><div class="course-counts"><span>${c.chapter_count} 章</span><span>${c.node_count} 个学习小节</span></div>${meter(progress.get(c.id))}<div class="course-actions"><a class="primary learning-course" href="${esc(studyUrl(c))}">${actionLabel(c)}</a><a class="preview-course" href="${esc(courseUrl('/preview',c.id))}">目录与预览 →</a>${account?.user?`<a class="overview-course" href="${esc(courseUrl('/learn',c.id))}&view=overview">课程全貌</a>`:''}</div></div></article>`).join('');
    const active=courses.filter(c=>progress.get(c.id)?.onboarded).sort((a,b)=>(progress.get(b.id).last_active||'').localeCompare(progress.get(a.id).last_active||''));
    const selected=active[0]||courses[0];
    $('resumePanel').hidden=!selected;if(!selected)return;
    const state=progress.get(selected.id),resuming=!!state?.onboarded;
    $('resumePanel').innerHTML=`<div><span class="eyebrow">${resuming?'接着上次学':'从一门课程开始'}</span><h2>${esc(selected.title)}</h2><p>${resuming?esc(state.current_title||'继续安排你的学习路线'):'先浏览讲解，开始学习时勾选已学过的内容。'}</p>${meter(state)}</div><div class="resume-actions"><a id="resumeLearning" class="primary" href="${esc(studyUrl(selected))}">${actionLabel(selected)} →</a><a href="${esc(courseUrl('/preview',selected.id))}">先读课程预览</a></div>`;
  }
  function selectLesson(id,focus=false){
    const n=previewData.nodes.find(n=>n.id===id);if(!n)return;
    const chapter=previewData.chapters.find(c=>c.id===n.chapter_id);
    $('lessonTitle').textContent=n.title;$('lessonChapter').textContent=chapter?.title||'';
    // HTML is produced by LearnMargin's safe Markdown renderer: raw HTML,
    // executable links and external media are disabled server-side.
    $('previewContent').innerHTML=n.paragraphs.length?n.paragraphs.map(p=>`${p.heading?'<h3>'+esc(p.heading)+'</h3>':''}${p.html}`).join(''):n.description_html;
    $('previewContent').querySelectorAll('.math').forEach(el=>window.katex?.render(el.dataset.tex,el,{displayMode:el.dataset.display==='true',throwOnError:false,trust:false}));
    document.querySelectorAll('[data-node]').forEach(b=>{b.setAttribute('aria-current',String(b.dataset.node===id));if(b.dataset.node===id)b.closest('details').open=true;});
    const url=new URL(location.href);url.searchParams.set('node_id',id);history.replaceState(null,'',url);
    loginReturn();
    if(focus)$('lessonTitle').focus({preventScroll:true});
  }
  function renderPreview(){
    const {course,chapters,nodes}=previewData;document.title=course.title+' · 课程预览';
    $('previewTitle').textContent=course.title;$('previewDescription').textContent=course.description;
    for(const id of ['previewStart','readingStart']){$(id).href=studyUrl(course);$(id).textContent=actionLabel(course);}
    $('previewChapters').innerHTML=chapters.map(c=>`<details><summary>${esc(c.title)}</summary>${nodes.filter(n=>n.chapter_id===c.id).map(n=>`<button data-node="${esc(n.id)}">${esc(n.title)}</button>`).join('')}</details>`).join('');
    const selected=nodes.find(n=>n.id===new URLSearchParams(location.search).get('node_id'))||nodes[0];
    if(selected)selectLesson(selected.id);else{$('lessonTitle').textContent='课程内容正在准备';$('previewContent').replaceChildren();}
    window.PLIACAssistant?.setContext({course_id:course.id});
  }
  $('previewChapters').onclick=e=>{const b=e.target.closest('[data-node]');if(b)selectLesson(b.dataset.node,true);};
  $('courseSearch').oninput=renderCourses;
  const readAccount=()=>fetch('/api/account/me',{cache:'no-store'}).then(async r=>{
    if(r.status===401)return null;if(!r.ok)throw Error('账号状态暂时无法读取，请刷新重试。');return r.json();
  }).catch(error=>({error}));
  async function load(){
    const version=++loadVersion;$('pageError').hidden=true;$('retryLoad').hidden=true;
    window.PLIACAccountReady=readAccount();
    try{
      const data=await request(previewing?courseUrl('/api/explore/preview',params.get('course_id')||''):'/api/explore/courses');
      if(version!==loadVersion)return;
      if(previewing){previewData=data;renderPreview();}else{courses=data.courses;renderCourses();}
      account=await window.PLIACAccountReady;
      if(version!==loadVersion)return;
      if(account?.error)throw account.error;
      if(account&&!document.querySelector('script[data-home-assistant]')){
        const script=document.createElement('script');script.src='/static/assistant-panel.js?v=2';script.dataset.homeAssistant='true';
        script.onload=()=>{if(previewData)window.PLIACAssistant?.setContext({course_id:previewData.course.id});};
        document.head.appendChild(script);
      }
      if(account?.user){
        $('accountLink').hidden=true;$('accountName').hidden=false;$('accountName').textContent=account.user.display_name;
        $('manageLink').hidden=false;$('accountLogout').hidden=false;$('welcomeNote').textContent='课程进度已与当前账号同步。';
        const data=await request('/api/home/progress');if(version!==loadVersion)return;
        progress=new Map(data.courses.map(c=>[c.course_id,c]));
        if(previewing)renderPreview();else renderCourses();
      }
    }catch(error){if(version===loadVersion)showError(error);}
  }
  $('accountLogout').onclick=async()=>{
    $('accountLogout').disabled=true;
    try{const response=await fetch('/api/account/logout',{method:'POST'});if(!response.ok)throw Error('退出未完成，请重试。');location.assign('/courses');}
    catch(error){showError(error);$('accountLogout').disabled=false;}
  };
  $('retryLoad').onclick=load;
  // Recheck session-bound progress after a browser back/forward-cache restore.
  window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
  load();
})();
