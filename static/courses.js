(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function error(id,message){$(id).textContent=message||'';$(id).hidden=!message;}
  async function api(options){
    let response;try{response=await fetch('/api/courses',options);}catch{throw new Error('连接中断，请检查本地服务。');}
    const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'课程读取失败。');return value;
  }
  async function loadCourses(){
    const {courses}=await api();
    $('courseList').innerHTML=courses.map(course=>{
      const query=new URLSearchParams({course_id:course.id}).toString();
      return `<article class="course-card" data-course-id="${esc(course.id)}"><div><h2>${esc(course.title)}</h2><div class="course-status"><span>草稿 v${esc(course.draft_version)}</span>${course.published_version?`<span>已发布 v${esc(course.published_version)}</span>`:'<span>待发布</span>'}</div></div><p class="course-counts"><span>${Number(course.chapter_count)} 章</span><span>${Number(course.node_count)} 个知识点</span><span>${Number(course.edge_count)} 条关系</span></p><div class="course-actions"><a class="learning-course" href="/learn?${query}">学习工作台</a><a class="edit-course" href="/author?${query}">编辑图谱</a>${course.published_version?`<a class="published-course" href="/knowledge?${query}">查看发布版</a>`:''}<a class="review-course" href="/review?${query}">教学复核</a></div></article>`;
    }).join('')||'<p class="muted">暂无课程</p>';
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
  loadCourses().catch(failure=>{error('courseError',failure.message);$('courseList').innerHTML='';});
})();
