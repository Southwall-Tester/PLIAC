/* Apply the saved theme before styles and graph scripts render either page. */
(() => {
  const root=document.documentElement;
  function apply(dark,persist=false){
    root.classList.toggle('network-dark',dark);
    root.style.colorScheme=dark?'dark':'light';
    document.body?.classList.toggle('network-dark',dark);
    const button=document.getElementById('themeButton');
    if(button)button.textContent=dark?'浅色':'深色';
    if(persist)try{localStorage.setItem('pliac-theme',dark?'dark':'light');}catch{}
  }
  let dark=false;
  try{dark=localStorage.getItem('pliac-theme')==='dark';}catch{}
  apply(dark);
  window.GraphTheme={
    sync:()=>apply(root.classList.contains('network-dark')),
    toggle:()=>apply(!root.classList.contains('network-dark'),true)
  };
  document.addEventListener('DOMContentLoaded',()=>window.GraphTheme.sync(),{once:true});
})();
