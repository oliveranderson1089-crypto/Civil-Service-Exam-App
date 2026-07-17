/* 聊天
 *
 * 由 app.js 按它自己的区段边界切出（原 L7412-7705）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, IS_MOBILE, ME, SKIN, api, appConfirm,
   back, c, composing, compressImage, dvIcon, esc,
   fSize, init, lightbox, preview, push, stack,
   state, toast */

/* ================= 聊天 ================= */
let chTab = 'convos', crFid = 0, crName = '', crLastId = 0, crPoll = 0;
let crFriendAvatar = '', crMeAvatar = '', crLastTime = '';   // 头像 + 上一条时间（做时间分隔）
function openChat() {
  push({ view: 'chat', title: '聊天' }); chSwitch('convos'); ensureNotifyPerm();
  crShowEmpty();                       // 桌面进来先在右栏显示空态；移动端只看列表
}
// 右栏空态（还没选会话）
function crShowEmpty() {
  crFid = 0; clearInterval(crPoll);
  const p2 = $('#chat-2pane'); if (p2) p2.classList.remove('show-room');
  $('#cr-peer').classList.add('hidden'); $('#cr-input').classList.add('hidden');
  $('#cr-empty').classList.remove('hidden'); $('#cr-msgs').innerHTML = '';
}
// 当前是否正开着和某人的聊天窗（桌面：选了会话；移动端：栈顶带 room）
function crInRoom() {
  const st = stack[stack.length - 1] || {};
  if (st.view !== 'chat') return false;
  return IS_MOBILE ? !!st.room : !!crFid;
}
function chSwitch(t) {
  chTab = t;
  document.querySelectorAll('#ch-tabs .ch-tab').forEach(b => b.classList.toggle('active', b.dataset.cht === t));
  ['convos', 'friends', 'add'].forEach(x => $('#ch-' + x).classList.toggle('hidden', x !== t));
  if (t === 'convos') loadConvos();
  else if (t === 'friends') loadFriends();
  else loadAddFriend();
}
$('#ch-tabs').addEventListener('click', e => { const b = e.target.closest('[data-cht]'); if (b) chSwitch(b.dataset.cht); });
// 头像：有图就贴图，没图就用名字首字（微信/QQ 那种圆头像）
function avHtml(url, name, cls) {
  const init = esc((name || '?').trim().slice(0, 1).toUpperCase() || '?');
  return url
    ? `<div class="${cls} has-img" style="background-image:url('${esc(url)}')"></div>`
    : `<div class="${cls}">${init}</div>`;
}
async function loadConvos() {
  $('#ch-convos').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/chat/conversations');
    updateChatBadge(d.unread);
    if (!d.conversations.length) { $('#ch-convos').innerHTML = '<p class="empty">还没有会话。去「好友」找人聊，或「＋ 加好友」。</p>'; return; }
    $('#ch-convos').innerHTML = d.conversations.map(c => `
      <div class="ch-convo${c.self ? ' ch-self' : ''}" data-crf="${c.id}" data-crn="${esc(c.username)}">
        ${c.self ? '<div class="ch-av ch-av-self">📁</div>' : avHtml(c.avatar, c.username, 'ch-av')}
        <div class="ch-cmid"><div class="ch-cn">${esc(c.username)}</div><div class="ch-cp">${esc(c.preview || '')}</div></div>
        <div class="ch-cright"><div class="ch-ct">${esc((c.time || '').slice(5, 16))}</div>${c.unread ? `<span class="ch-un">${c.unread}</span>` : ''}</div>
      </div>`).join('');
  } catch (e) { $('#ch-convos').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#ch-convos').addEventListener('click', e => { const c = e.target.closest('[data-crf]'); if (c) openChatroom(+c.dataset.crf, c.dataset.crn); });
async function loadFriends() {
  $('#ch-friends').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/friends');
    if (d.n_req) { $('#ch-reqbadge').textContent = d.n_req; $('#ch-reqbadge').classList.remove('hidden'); }
    else $('#ch-reqbadge').classList.add('hidden');
    if (!d.friends.length) { $('#ch-friends').innerHTML = '<p class="empty">还没有好友。点「＋ 加好友」搜用户名或 ID 添加。</p>'; return; }
    $('#ch-friends').innerHTML = d.friends.map(f => `
      <div class="ch-frow" data-crf="${f.id}" data-crn="${esc(f.username)}">
        ${avHtml(f.avatar, f.username, 'ch-av')}
        <div class="ch-cn">${esc(f.username)}</div>
        <button class="ch-chat" data-crf="${f.id}" data-crn="${esc(f.username)}">聊天</button>
        <button class="ch-fdel" data-fdel="${f.id}" title="删除好友">✕</button></div>`).join('');
  } catch (e) { $('#ch-friends').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#ch-friends').addEventListener('click', async e => {
  const del = e.target.closest('[data-fdel]');
  if (del) { if (await appConfirm('删除这个好友？')) { try { await api('/api/friends/' + del.dataset.fdel, { method: 'DELETE' }); loadFriends(); } catch (err) { toast(err.message, true); } } return; }
  const c = e.target.closest('[data-crf]'); if (c) openChatroom(+c.dataset.crf, c.dataset.crn);
});
async function loadAddFriend() {
  try {
    const d = await api('/api/friends/requests');
    $('#ch-reqs').innerHTML = d.requests.length
      ? '<div class="ch-reqt">好友请求</div>' + d.requests.map(r => `
        <div class="ch-req"><div class="ch-av">${esc(r.username.slice(0, 1).toUpperCase())}</div>
          <div class="ch-cmid"><div class="ch-cn">${esc(r.username)}</div><div class="ch-cp">${esc(r.msg || '请求加你为好友')}</div></div>
          <button class="btn tiny primary" data-req="${r.id}" data-ra="accept">接受</button>
          <button class="btn tiny" data-req="${r.id}" data-ra="reject">拒绝</button></div>`).join('')
      : '';
  } catch (_) {}
  $('#ch-results').innerHTML = '';
}
$('#ch-searchbtn').onclick = chDoSearch;
$('#ch-search').addEventListener('keydown', e => { if (e.key === 'Enter') chDoSearch(); });
async function chDoSearch() {
  const q = $('#ch-search').value.trim(); if (!q) return;
  $('#ch-results').innerHTML = '<p class="empty">搜索中…</p>';
  try {
    const d = await api('/api/friends/search?q=' + encodeURIComponent(q));
    $('#ch-results').innerHTML = d.users.length ? d.users.map(u => `
      <div class="ch-frow"><div class="ch-av">${esc(u.username.slice(0, 1).toUpperCase())}</div>
        <div class="ch-cmid"><div class="ch-cn">${esc(u.username)}</div><div class="ch-cp">ID: ${u.id}</div></div>
        ${u.state === 'friend' ? '<span class="ch-tag">已是好友</span>'
        : u.state === 'sent' ? '<span class="ch-tag">已发送</span>'
          : `<button class="btn tiny primary" data-add="${u.id}">加好友</button>`}</div>`).join('')
      : '<p class="empty">没找到这个用户。</p>';
  } catch (e) { $('#ch-results').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#ch-add').addEventListener('click', async e => {
  const add = e.target.closest('[data-add]');
  if (add) { try { const r = await api('/api/friends/request', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to: +add.dataset.add }) }); toast(r.friend ? '已成为好友' : '好友请求已发送'); chDoSearch(); } catch (err) { toast(err.message, true); } return; }
  const req = e.target.closest('[data-req]');
  if (req) { try { await api('/api/friends/requests/' + req.dataset.req, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: req.dataset.ra }) }); loadAddFriend(); } catch (err) { toast(err.message, true); } }
});
// —— 打开某人的聊天窗（右栏）——
function openChatroom(fid, name) {
  crFid = fid; crName = name; crLastId = 0;
  crFriendAvatar = ''; crMeAvatar = SKIN.avatar || ''; crLastTime = '';
  if ((stack[stack.length - 1] || {}).view !== 'chat') push({ view: 'chat', title: '聊天' });
  if (IS_MOBILE) push({ view: 'chat', room: fid, title: name });   // 移动端压栈：back 能回列表
  const p2 = $('#chat-2pane'); if (p2) p2.classList.add('show-room');
  $('#cr-peername').textContent = name || '';
  $('#cr-peer').classList.remove('hidden');
  $('#cr-input').classList.remove('hidden');
  $('#cr-empty').classList.add('hidden');
  $('#cr-msgs').innerHTML = '<p class="empty">加载中…</p>';
  crLoad(true);
  clearInterval(crPoll);
  // SSE 负责秒推；这个轮询只是兜底（万一 SSE 断了没重连上），放慢到 10 秒
  crPoll = setInterval(() => { if (crInRoom()) crLoad(false); else clearInterval(crPoll); }, 10000);
}
$('#cr-back').onclick = () => { if (IS_MOBILE) back(); else crShowEmpty(); };
let crLoading = false;
async function crLoad(first) {
  // 并发锁：轮询 / SSE 推送 / 发送后刷新可能同时进来，都读同一个 crLastId、都拉同一批消息、
  // 都往界面追加 → 同一条消息重复显示（对方以为你连发了好几条）。一次只跑一个。
  if (crLoading && !first) return;
  crLoading = true;
  try {
    const d = await api('/api/chat/' + crFid + '?after=' + crLastId);
    if (d.friend_avatar !== undefined) crFriendAvatar = d.friend_avatar || '';
    if (d.me_avatar) crMeAvatar = d.me_avatar;
    if (!crName && d.friend) {   // 从通知点进来时没带名字，拿到后补上
      crName = d.friend;
      $('#cr-peername').textContent = crName;
      const top = stack[stack.length - 1] || {};
      if (IS_MOBILE && top.room) { top.title = crName; $('#top-title').textContent = crName; }
    }
    if (first) { $('#cr-msgs').innerHTML = ''; crLastTime = ''; }
    if (!d.messages.length && first) { $('#cr-msgs').innerHTML = '<p class="empty">还没有消息，发一条打个招呼吧 👋</p>'; }
    if (d.messages.length && $('#cr-msgs').querySelector('.empty')) $('#cr-msgs').innerHTML = '';
    const box = $('#cr-msgs');
    for (const m of d.messages) {
      crLastId = Math.max(crLastId, m.id);
      if (crShouldSep(crLastTime, m.time)) box.insertAdjacentHTML('beforeend', `<div class="cr-time">${esc(crTimeLabel(m.time))}</div>`);
      crLastTime = m.time || crLastTime;
      box.insertAdjacentHTML('beforeend', crMsgHtml(m));
    }
    if (d.messages.length) { box.scrollTop = box.scrollHeight; requestAnimationFrame(() => box.scrollTop = box.scrollHeight); }
  } catch (e) { if (first) $('#cr-msgs').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
  finally { crLoading = false; }
}
function crMsgHtml(m) {
  let inner;
  if (m.kind === 'image') inner = `<img class="cr-img" src="/api/chat/file/${m.file_id}?inline=1" data-lbimg="/api/chat/file/${m.file_id}?inline=1">`;
  else if (m.kind === 'file') inner = `<a class="cr-file" href="/api/chat/file/${m.file_id}" download><span class="cr-fic">${dvIcon((m.file_name || '').split('.').pop())}</span><span class="cr-fmid"><span class="cr-fn">${esc(m.file_name || '文件')}</span><em>${fSize(m.file_size)}</em></span></a>`;
  else inner = esc(m.body).replace(/\n/g, '<br>');
  const av = avHtml(m.mine ? crMeAvatar : crFriendAvatar, m.mine ? '我' : crName, 'cr-av');
  return `<div class="cr-row ${m.mine ? 'mine' : 'theirs'}">${av}<div class="cr-bubble ${m.kind}">${inner}</div></div>`;
}
// 时间分隔：首条、或与上一条间隔超过 5 分钟就插一条居中时间（微信那样）
function crShouldSep(prev, cur) {
  if (!cur) return false;
  if (!prev) return true;
  return (new Date(cur.replace(/-/g, '/')) - new Date(prev.replace(/-/g, '/'))) > 5 * 60 * 1000;
}
function crTimeLabel(t) {
  if (!t) return '';
  const d = new Date(t.replace(/-/g, '/')), now = new Date();
  const hm = t.slice(11, 16);
  if (d.toDateString() === now.toDateString()) return hm;                 // 今天：只显示 时:分
  const yst = new Date(now); yst.setDate(now.getDate() - 1);
  if (d.toDateString() === yst.toDateString()) return '昨天 ' + hm;
  return t.slice(5, 10).replace('-', '月') + '日 ' + hm;
}
$('#cr-msgs').addEventListener('click', e => { const im = e.target.closest('[data-lbimg]'); if (im) lightbox(im.dataset.lbimg); });
$('#cr-send').onclick = crSendText;
// ⚠️ 打中文时按 Enter 是「确认候选词」，不能当发送 —— 不加 composing 守卫会导致边打字边误发、甚至连发好几条
$('#cr-text').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey && !composing(e)) { e.preventDefault(); crSendText(); }
});
let crSending = false;      // 发送锁：一次动作只发一条，堵住「连发好几条一样的」
async function crSendText() {
  if (crSending) return;
  const el = $('#cr-text'); const t = el.value.trim(); if (!t) return;
  crSending = true; el.value = ''; if (el._grow) el._grow();
  try { await api('/api/chat/' + crFid, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ body: t }) }); crLoad(false); }
  catch (e) { toast(e.message, true); el.value = t; if (el._grow) el._grow(); }   // 失败把字还回去
  crSending = false;
}
$('#cr-file').addEventListener('change', async e => {
  const files = [...e.target.files]; e.target.value = '';       // 先清空，避免选同一张再选触发不到 change
  if (!files.length) return;
  // #11：选完不要马上发，先确认（原来一选就发过去了）
  const names = files.length === 1 ? files[0].name : files.length + ' 个文件';
  if (!(await appConfirm('发送「' + names + '」给 ' + esc(crName) + '？'))) return;
  await crSendFiles(files);
});
async function crSendFiles(files) {
  if (crSending) return;
  crSending = true;
  for (const f of files) {
    // 图片先在本地压缩（缩到 ≤1600px、JPEG），传得快、对方加载也快
    let blob = f, name = f.name;
    if (/^image\//.test(f.type)) {
      try { blob = await compressImage(f); } catch (_) { blob = f; }
      if (blob !== f && !/\.jpe?g$/i.test(name)) name = name.replace(/\.[^.]+$/, '') + '.jpg';
    }
    const fd = new FormData(); fd.append('file', blob, name);
    try { await api('/api/chat/' + crFid, { method: 'POST', body: fd }); } catch (err) { toast(f.name + '：' + err.message, true); }
  }
  crSending = false;
  crLoad(false);
}
// 拖文件进聊天窗口直接发（浏览器；桌面壳走 __onDropFiles）
(function () {
  const el = $('#chat-main'); if (!el) return;
  el.addEventListener('dragover', e => { if (!crFid) return; e.preventDefault(); el.classList.add('cr-drop'); });
  el.addEventListener('dragleave', e => { if (!el.contains(e.relatedTarget)) el.classList.remove('cr-drop'); });
  el.addEventListener('drop', e => { e.preventDefault(); el.classList.remove('cr-drop'); if (!crFid) return; const fs = [...(e.dataTransfer.files || [])]; if (fs.length) crSendFiles(fs); });
})();
function updateChatBadge(n) {
  const b = $('#chat-badge'); if (!b) return;
  if (n > 0) { b.textContent = n > 99 ? '99+' : n; b.classList.remove('hidden'); } else b.classList.add('hidden');
}
// 首页/切换时刷未读角标（轮询，和现有 sync 同频）
async function refreshChatBadge() {
  try { updateChatBadge((await api('/api/chat/unread')).unread); }
  catch (e) { console.debug('[聊天] 未读角标刷新失败：%s', (e && e.message) || e); }   // 15 秒后自己会再试
}

/* 秒推：SSE 长连接。服务器一「叮」，正在聊的立刻拉新消息、其它地方更新角标。
   发消息还是普通 POST；这条连接只负责收「你有新消息」的信号。EventSource 断了会自动重连。 */
let chatES = null;
function chatConnect() {
  if (!ME || chatES) return;
  ensureNotifyPerm();                 // 早点要通知权限（桌面壳会自动放行），全应用都能收到消息提示
  try {
    chatES = new EventSource('/api/chat/stream');
    chatES.onmessage = (e) => {
      let d; try { d = JSON.parse(e.data); } catch (_) { return; }
      if (d.type === 'msg') onChatPush(d);
      else if (d.type === 'friend') onFriendPush();
    };
    // onerror 不用管：EventSource 会按服务器给的 retry(3s) 自动重连
  } catch (_) {}
}
function onChatPush(d) {
  const fromId = (d && typeof d === 'object') ? d.from : d;   // 兼容旧格式（只有 id）
  const v = (stack[stack.length - 1] || {}).view;
  const viewing = (crInRoom() && crFid === fromId && !document.hidden);
  if (viewing) { crLoad(false); if (v === 'chat') loadConvos(); return; }  // 正跟他聊且在前台 → 立刻拉
  refreshChatBadge();                                                    // 否则更新未读角标
  if (v === 'chat') loadConvos();                                        // 在聊天页（双栏）→ 刷新会话列表
  const isSelf = ME && fromId === ME.id;                                 // 文件传输助手（自己其它设备）不弹通知
  if (!isSelf && d && typeof d === 'object') notifyChat(fromId, d.name, d.preview);
}
// 通知栏推送：APK 走原生通知，浏览器/桌面走 Web Notification。点开直达该好友聊天。
function notifyChat(fromId, name, preview) {
  const title = (name || '好友') + ' 发来消息';
  const body = preview || '你有一条新消息';
  // APK：交给原生（会进系统通知栏、可后台弹出）
  try {
    if (window.GongkaoNative && typeof GongkaoNative.notify === 'function') {
      GongkaoNative.notify(title, body, 'chat:' + fromId);
      return;
    }
  } catch (_) {}
  // 浏览器/桌面壳：只要不是正开着这个人的聊天窗（onChatPush 已判过），就弹系统通知。
  // 不再要求页面隐藏——在别的功能页也该收到提示（像微信/QQ）。
  try {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    const n = new Notification(title, { body, tag: 'chat:' + fromId, icon: '/static/icon-192.png' });
    n.onclick = () => { try { window.focus(); } catch (_) {} openChatroom(fromId, name || ''); n.close(); };
  } catch (_) {}
}
// 首次进入聊天时，礼貌地请求一次通知权限（拒绝也不再烦）
function ensureNotifyPerm() {
  try {
    if (window.GongkaoNative && typeof GongkaoNative.notify === 'function') {
      if (typeof GongkaoNative.requestNotifyPerm === 'function') GongkaoNative.requestNotifyPerm();
      return;
    }
    if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission();
  } catch (_) {}
}
function onFriendPush() {
  refreshChatBadge();
  const v = (stack[stack.length - 1] || {}).view;
  if (v === 'chat') { if (chTab === 'add') loadAddFriend(); if (chTab === 'friends') loadFriends(); loadConvos(); }
}
