(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const managing=location.pathname==='/manage/courses';
  $('newCourseButton').hidden=!managing;$('materialsLink').hidden=!managing;
  $('manageLink').hidden=managing;$('studentCoursesLink').hidden=!managing;
  if(managing){document.title='课程管理';document.querySelector('h1').textContent='课程管理';}
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function error(id,message){$(id).textContent=message||'';$(id).hidden=!message;}
  async function api(options){
    let response;try{response=await fetch('/api/courses',options);}catch{throw new Error('连接中断，请检查本地服务。');}
    const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'课程读取失败。');return value;
  }
  async function loadCourses(){
    const {courses}=await api();
    $('courseList').innerHTML=courses.filter(course=>managing||course.capabilities.learn).map(course=>{
      const query=new URLSearchParams({course_id:course.id}).toString(),view=course.presentation;
      const actions=[['handout','/course-reader','讲义与知识图谱']];
      if(course.capabilities.learn)actions.push(['learning','/learn','课程练习']);
      if(managing){
        if(course.capabilities.edit)actions.push(['edit','/author','编辑图谱']);
        if(course.published_version)actions.push(['published','/knowledge','查看发布版']);
        if(course.capabilities.learn)actions.push(['review','/review','教学复核']);
      }
      return `<article class="course-card" data-course-id="${esc(course.id)}"><div class="course-status"><span>${esc(view.label)}</span>${managing?`<span>v${esc(course.published_version||course.draft_version)}</span>`:''}</div><h2>${esc(course.title)}</h2><p class="muted">${esc(view.description)}</p><p class="course-counts">${view.stats.map(stat=>`<span>${Number(stat.value)} ${esc(stat.label)}</span>`).join('')}</p><div class="course-actions">${actions.map(([kind,path,label])=>`<a class="${kind}-course" href="${path}?${query}">${label}</a>`).join('')}</div></article>`;
    }).join('')||'<p class="muted">暂无可学习的课程。</p>';

  }
  $('themeButton').onclick=()=>GraphTheme.toggle();
  $('newCourseButton').onclick=()=>{error('createCourseError','');$('createCourseForm').reset();$('createCourseDialog').showModal();$('newCourseTitle').focus();};
  $('closeCreateCourse').onclick=()=>$('createCourseDialog').close();
  $('createCourseForm').onsubmit=async event=>{
    event.preventDefault();const title=$('newCourseTitle').value.trim();if(!title){error('createCourseError','请填写课程名称。');return;}
    const method=new FormData(event.target).get('createMethod');$('createCourseSubmit').disabled=true;error('createCourseError','');
    try{const value=await api({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title})});location.assign(`${method==='book'?'/documents':'/author'}?${new URLSearchParams({course_id:value.course.id,new:'1'})}`);}
    catch(failure){error('createCourseError',failure.message);$('createCourseSubmit').disabled=false;}
  };
  loadCourses().catch(failure=>{error('courseError',failure.message);document.querySelector('.course-loading')?.remove();});
})();
