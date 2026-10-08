/* Apply the saved theme before styles and graph scripts render either page. */
(() => {
  const root=document.documentElement;
  function apply(dark,persist=false){
    root.classList.toggle('network-dark',dark);
    root.style.colorScheme=dark?'dark':'light';
    document.body?.classList.toggle('network-dark',dark);
    const button=document.getElementById('themeButton');
    if(button){
      const toolbar=button.closest('header');
      if(toolbar){toolbar.classList.add('theme-toolbar');if(button.parentElement!==toolbar)toolbar.appendChild(button);}
      const label=dark?'切换到浅色模式':'切换到深色模式';
      button.setAttribute('aria-label',label);
      button.title=label;
      button.innerHTML=`<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${dark?'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/>':'<path d="M20.9 13.1A9 9 0 0 1 10.9 3.1 9 9 0 1 0 20.9 13.1Z"/>'}</svg>`;
    }
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
