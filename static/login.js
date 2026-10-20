(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let mode = 'login';
  const requested = new URL(location.href).searchParams.get('next') || '/courses';
  function safePath(value) {
    try {
      const target = new URL(value, location.origin);
      return value.startsWith('/') && !value.startsWith('//') && target.origin === location.origin &&
        target.pathname !== '/login' ? target.pathname + target.search + target.hash : '/courses';
    } catch { return '/courses'; }
  }
  const next = safePath(requested);
  function select(value) {
    mode = value;
    const register = mode === 'register';
    $('loginTab').setAttribute('aria-selected', String(!register));
    $('registerTab').setAttribute('aria-selected', String(register));
    $('displayNameRow').hidden = !register;
    $('password').autocomplete = register ? 'new-password' : 'current-password';
    $('formTitle').textContent = register ? '创建你的学习空间' : '登录学习空间';
    $('formDescription').textContent = '学习进度、对话与画像按账号保存。';
    $('submitAccount').textContent = register ? '创建账号并开始' : '登录并继续';
    $('accountError').textContent = '';
  }
  $('loginTab').onclick = () => select('login');
  $('registerTab').onclick = () => select('register');
  $('accountForm').onsubmit = async event => {
    event.preventDefault();
    $('submitAccount').disabled = true;
    $('accountError').textContent = '';
    try {
      const body = {username:$('username').value.trim(), password:$('password').value, next};
      if (mode === 'register' && $('displayName').value.trim()) body.display_name = $('displayName').value.trim();
      const response = await fetch(`/api/account/${mode}`, {method:'POST', credentials:'same-origin',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || '暂时无法登录，请重试。');
      location.assign(safePath(result.next || next));
    } catch (error) {
      $('accountError').textContent = error.message || '连接暂时中断，请重试。';
    } finally { $('submitAccount').disabled = false; }
  };
  fetch('/api/account/me', {credentials:'same-origin'}).then(response => response.ok ? response.json() : null)
    .then(data => { if (data?.authenticated) location.replace(next); }).catch(() => {});
})();
