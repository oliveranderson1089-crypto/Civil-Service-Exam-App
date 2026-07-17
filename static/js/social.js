/* 云盘 / 聊天 / 党建词典 / 逐条朗读 / 账户
 *
 * 由 app.js 按它原有的区段边界切出（原 L7320-8053）。顺序即原顺序 —— index.html 里
 * 按同样次序引入，执行序与拆分前逐字节一致。
 *
 * 下面 /* global *​/ 是这个模块的依赖清单：它用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，这就是现成的 import 表。
 */
/* global $, DESKTOP_VER, IN_APP, IS_DESKTOP, IS_MOBILE, KB,
   ME, SKIN, api, appConfirm, appPrompt, back,
   c, composing, compressImage, doLogout, emKey, esc,
   goHome, init, lightbox, lsGet, lsSet, preview,
   push, refreshNotifyBtn, renderSkinPrev, stack, state, toast */

/* ================= 云盘 ================= */
let dvFolder = '';
const FILE_ICON = { pdf: '📕', doc: '📘', docx: '📘', xls: '📗', xlsx: '📗', ppt: '📙', pptx: '📙',
  png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', webp: '🖼️', apk: '📦', exe: '📦', dmg: '📦',
  zip: '🗜️', rar: '🗜️', '7z': '🗜️', mp4: '🎬', mp3: '🎵', txt: '📄', md: '📄', html: '🌐' };
const dvIcon = e => FILE_ICON[(e || '').replace('.', '').toLowerCase()] || '📎';
function fSize(n) { n = n || 0; return n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB'; }
function openDrive() { dvFolder = ''; push({ view: 'drive', title: '云盘' }); loadDrive(); }
async function loadDrive() {
  $('#dv-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/drive?folder=' + encodeURIComponent(dvFolder));
    $('#dv-used').textContent = '已用 ' + fSize(d.used);
    // 面包屑
    const parts = dvFolder ? dvFolder.split('/') : [];
    let acc = '';
    $('#dv-crumb').innerHTML = `<a data-dvcd="">☁️ 云盘</a>` + parts.map(p => {
      acc = acc ? acc + '/' + p : p; return ` / <a data-dvcd="${esc(acc)}">${esc(p)}</a>`;
    }).join('');
    if (!d.items.length) { $('#dv-list').innerHTML = '<p class="empty">这个文件夹是空的。上传文件，或新建文件夹。</p>'; return; }
    $('#dv-list').innerHTML = d.items.map(it => it.is_dir
      ? `<div class="dv-item dv-dir" data-dvopen="${esc((dvFolder ? dvFolder + '/' : '') + it.name)}">
           <span class="dv-ic">📁</span><span class="dv-name">${esc(it.name)}</span>
           <button class="dv-del" data-dvdel="${it.id}" title="删除">🗑</button></div>`
      : `<div class="dv-item">
           <span class="dv-ic">${dvIcon(it.ext)}</span>
           <span class="dv-name">${esc(it.name)}</span>
           <span class="dv-meta">${fSize(it.size)}${it.source === 'chat' ? ' · 聊天' : ''}</span>
           <button class="dv-act" data-dvsend="${it.id}" title="发给好友">📤</button>
           <a class="dv-act" href="/api/drive/${it.id}/download" title="下载">⬇</a>
           <button class="dv-del" data-dvdel="${it.id}" title="删除">🗑</button></div>`).join('');
  } catch (e) { $('#dv-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#dv-crumb').addEventListener('click', e => { const a = e.target.closest('[data-dvcd]'); if (a) { dvFolder = a.dataset.dvcd; loadDrive(); } });
$('#dv-list').addEventListener('click', async e => {
  const dir = e.target.closest('[data-dvopen]');
  if (dir && !e.target.closest('[data-dvdel]')) { dvFolder = dir.dataset.dvopen; loadDrive(); return; }
  const del = e.target.closest('[data-dvdel]');
  if (del) {
    if (!(await appConfirm('删除这个？（文件夹会连里面一起删）'))) return;
    try { await api('/api/drive/' + del.dataset.dvdel, { method: 'DELETE' }); loadDrive(); } catch (err) { toast(err.message, true); }
    return;
  }
  const send = e.target.closest('[data-dvsend]');
  if (send) driveSend(+send.dataset.dvsend);
});
$('#dv-upfile').addEventListener('change', async e => {
  const files = [...e.target.files]; e.target.value = '';
  await dvUpload(files);
});
async function dvUpload(files) {
  if (!files.length) return;
  toast('上传中…（' + files.length + '）');
  let ok = 0;
  for (const f of files) {
    const fd = new FormData(); fd.append('file', f, f.name); fd.append('folder', dvFolder);
    try { await api('/api/drive', { method: 'POST', body: fd }); ok++; } catch (err) { toast(f.name + '：' + err.message, true); }
  }
  if (ok) { toast('已上传 ' + ok + ' 个'); loadDrive(); }
}
$('#dv-newfolder').onclick = async () => {
  const name = await appPrompt('新建文件夹', '', '');
  if (!name || !name.trim()) return;
  try { await api('/api/drive/folder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim(), parent: dvFolder }) }); loadDrive(); }
  catch (err) { toast(err.message, true); }
};
async function driveSend(fid) {
  try {
    const d = await api('/api/friends');
    if (!d.friends.length) { toast('你还没有好友，先去「聊天 → 加好友」', true); return; }
    const pick = await pickFriend(d.friends, '发给谁');
    if (!pick) return;
    await api('/api/drive/' + fid + '/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to: pick }) });
    toast('已发送');
  } catch (e) { toast(e.message, true); }
}
// 选好友（复用小记那种底部面板）
function pickFriend(friends, title) {
  return new Promise(res => {
    const el = $('#mat-share-sheet');
    el.innerHTML = `<div class="ns-mask" data-sheet-close></div><div class="ns-panel">
      <div class="ns-handle"></div><div class="ns-title">${esc(title || '选择好友')}</div>
      <div class="ms-list">${friends.map(f => `<button class="ms-frow" data-fp="${f.id}">👤 ${esc(f.username)}</button>`).join('')}</div>
      <div class="ms-acts"><button class="btn" id="fp-cancel">取消</button></div></div>`;
    el.classList.remove('hidden');
    const done = v => { el.classList.add('hidden'); res(v); };
    el.querySelector('.ns-mask').onclick = () => done(null);
    $('#fp-cancel').onclick = () => done(null);
    el.querySelectorAll('[data-fp]').forEach(b => b.onclick = () => done(+b.dataset.fp));
  });
}

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

/* ================= 党的创新理论学习词典（12371.cn） ================= */
let pdCat = '全部', pdTimer = null;
async function openPartyDict() {
  push({ view: 'partydict', title: '创新理论词典' });
  $('#pd-q').value = ''; pdCat = '全部';
  try {
    const d = await api('/api/partydict/cats');
    const chips = [`<button class="pd-chip on" data-cat="全部">全部 ${d.total}</button>`]
      .concat(d.cats.map(c => `<button class="pd-chip" data-cat="${esc(c.cat)}">${esc(c.cat)} ${c.count}</button>`));
    $('#pd-cats').innerHTML = chips.join('');
  } catch (e) {}
  loadPartyDict();
}
async function loadPartyDict() {
  const q = $('#pd-q').value.trim();
  $('#pd-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/partydict?cat=' + encodeURIComponent(pdCat) + '&q=' + encodeURIComponent(q));
    if (!d.items.length) { $('#pd-list').innerHTML = '<p class="empty">没有匹配的词条，换个关键词试试。</p>'; return; }
    $('#pd-list').innerHTML = d.items.map(it =>
      `<div class="pd-item"><div class="pd-term">${esc(it.term)}<span class="pd-tag">${esc(it.cat)}</span></div>
        <div class="pd-body">${emKey(it.content)}</div></div>`).join('');
  } catch (e) { $('#pd-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#pd-cats').addEventListener('click', e => {
  const b = e.target.closest('.pd-chip'); if (!b) return;
  pdCat = b.dataset.cat;
  $('#pd-cats').querySelectorAll('.pd-chip').forEach(x => x.classList.toggle('on', x === b));
  loadPartyDict();
});
$('#pd-q').addEventListener('input', () => { clearTimeout(pdTimer); pdTimer = setTimeout(loadPartyDict, 250); });
// 背诵模式：隐藏释义、点卡片显示/收起
let pdRecite = false;
$('#pd-recite').onclick = () => {
  pdRecite = !pdRecite;
  $('#pd-list').classList.toggle('reciting', pdRecite);
  $('#pd-recite').classList.toggle('on', pdRecite);
  $('#pd-recite').textContent = pdRecite ? '✓ 背诵中' : '🎯 背诵模式';
  $('#pd-recite-hint').classList.toggle('hidden', !pdRecite);
  $('#pd-list').querySelectorAll('.pd-item.revealed').forEach(x => x.classList.remove('revealed'));
};
$('#pd-list').addEventListener('click', e => {
  if (!pdRecite) return;
  const it = e.target.closest('.pd-item'); if (it) it.classList.toggle('revealed');
});

/* 桌面版（GTK/WebKit）没有 speechSynthesis，朗读要借壳调系统 TTS */
const deskTTS = () => !!(window.__desktopTTS && window.webkit && window.webkit.messageHandlers
  && window.webkit.messageHandlers.gk);
function deskMsg(o) {
  try { window.webkit.messageHandlers.gk.postMessage(JSON.stringify(o)); } catch (_) {}
}
// 引擎：piper=离线神经语音（默认，不联网、起声快）／edge=微软在线（音质最好，要联网）
// ⚠️ 曾经有第三档「系统默认」= speech-dispatcher，已删除：它的 PulseAudio 输出模块会段错误
//    （内核日志实锤 spd_pulse.so segfault），是 Ubuntu 自带组件的 bug，点一下就把朗读弄挂。
const TTS_ENGS = [
  { id: 'piper', name: 'Piper 离线', desc: '本机合成，不联网，起声快' },
  { id: 'edge', name: '微软在线', desc: '音质最自然，需要联网' },
];
const TTS_VOICES = [
  { id: 'zh-CN-XiaoxiaoNeural', name: '晓晓（女）' },
  { id: 'zh-CN-YunxiNeural', name: '云希（男）' },
  { id: 'zh-CN-XiaoyiNeural', name: '晓伊（女·活泼）' },
  { id: 'zh-CN-YunjianNeural', name: '云健（男·浑厚）' },
];
const ttsHas = (id) => (window.__ttsEngines || []).includes(id);
const ttsEng = () => {
  const v = lsGet('ttsEngine');
  if (v && ttsHas(v)) return v;
  return (TTS_ENGS.find(e => ttsHas(e.id)) || {}).id || 'piper';
};
const ttsVoice = () => lsGet('ttsVoice') || TTS_VOICES[0].id;
const deskSay = (text, rate, id) =>
  deskMsg({ a: 'tts', text, rate, id, engine: ttsEng(), voice: ttsVoice() });
const deskStop = () => { if (deskTTS()) deskMsg({ a: 'tts_stop' }); };
// 壳读完一段会回调这里（比按字数估时长准，段间衔接才不断不叠）
window.__ttsEnd = (id) => { const f = window.Reader && Reader._deskCb; if (f && id === Reader._deskId) f(); };

/* 账户页「朗读音色」：只有桌面版有得选（手机走安卓 TTS，网页走浏览器自带） */
function ttsSetup() {
  const sec = $('#acct-tts'); if (!sec) return;
  const engs = TTS_ENGS.filter(e => ttsHas(e.id));
  sec.classList.toggle('hidden', !deskTTS() || engs.length < 2);
  if (!deskTTS()) return;
  const cur = ttsEng();
  $('#tts-eng-row').innerHTML = engs.map(e =>
    `<button class="theme-opt tts-opt${e.id === cur ? ' on' : ''}" data-tts="${e.id}" title="${e.desc}">${e.name}</button>`).join('');
  const vs = $('#tts-voice');
  vs.classList.toggle('hidden', cur !== 'edge');       // 音色只有微软在线那档能挑
  vs.innerHTML = TTS_VOICES.map(v =>
    `<option value="${v.id}"${v.id === ttsVoice() ? ' selected' : ''}>${v.name}</option>`).join('');
}
document.addEventListener('click', e => {
  const b = e.target.closest('.tts-opt');
  if (b) { lsSet('ttsEngine', b.dataset.tts); ttsSetup(); return; }
  if (e.target.closest('#tts-try')) {
    Reader.stop();
    deskSay('金无足赤，人无完人。这是朗读试听。', 1.0, '');
  }
});
document.addEventListener('change', e => {
  if (e.target.id === 'tts-voice') { lsSet('ttsVoice', e.target.value); }
});

/* ================= 逐条朗读（安卓 TTS 桥 / 浏览器 speechSynthesis） ================= */
// 会自动注入 🔊 按钮的内容条目选择器（新渲染的列表/卡片自动获得朗读按钮）
const READ_ITEM_SEL = '.gk-card, .pd-item, .poly-card, .cd-sec, .cd-body, .item, .poly-reader, #viewer-reader, .cs-ov-body, .cs-kq, .ai-msg.assistant, .sc-body-solo, .rv-flash';
const READ_RATES = [1.0, 1.2, 1.5, 0.8];
window.Reader = {
  playing: false, segs: [], idx: 0, gen: 0, rateIdx: 0, card: null,
  native() { return !!(window.GongkaoNative && window.GongkaoNative.ttsSpeak); },
  rate() { return READ_RATES[this.rateIdx]; },
  split(text) {
    // 按句切分（细粒度：切语速时从当前句继续，不用重头）；超长句再按逗号拆
    const t = (text || '').replace(/\s+/g, ' ').trim();
    const sents = t.split(/(?<=[。！？；.!?;\n])/);
    const segs = [];
    for (let s of sents) {
      s = s.trim(); if (!s) continue;
      if (s.length <= 120) { segs.push(s); continue; }
      let cur = '';
      for (const p of s.split(/(?<=[，,、])/)) {
        if ((cur + p).length > 120) { if (cur.trim()) segs.push(cur.trim()); cur = p; }
        else cur += p;
      }
      if (cur.trim()) segs.push(cur.trim());
    }
    return segs;
  },
  textOf(card) {
    const c = card.cloneNode(true);
    c.querySelectorAll('button, .read-item-btn, .item-actions, .news-star, .iconbtn, .rv-stage').forEach(x => x.remove());
    return c.innerText || '';
  },
  readCard(card) {
    if (this.card === card && this.playing) { this.stop(); return; }  // 再点同一条 = 停止
    this.stop();
    const segs = this.split(this.textOf(card));
    if (!segs.length) { toast('这一条没有可朗读的文字', true); return; }
    this.card = card; card.classList.add('reading-src');
    this.segs = segs; this.idx = 0; this.playing = true;
    this.ui(); this.next();
  },
  next() {
    if (!this.playing) return;
    if (this.idx >= this.segs.length) { this.stop(); return; }
    const myGen = ++this.gen; const seg = this.segs[this.idx];
    if (this.native()) {
      this._waitId = 'r' + myGen;
      try { window.GongkaoNative.ttsSpeak(this._waitId, seg, this.rate()); }
      catch (_) { this.stop(); }
    } else if (deskTTS()) {
      // 电脑桌面版：WebKit 根本没有 speechSynthesis，借壳去调系统 TTS（Piper/微软/espeak）。
      // 壳读完这段会回调 __ttsEnd，接着读下一段；超时只是兜底（万一壳挂了不至于卡死）。
      const adv = () => {
        if (!this.playing || myGen !== this.gen) return;
        clearTimeout(this._deskT); this._deskCb = null;
        this.idx++; this.next();
      };
      this._deskId = 'r' + myGen; this._deskCb = adv;
      deskSay(seg, this.rate(), this._deskId);
      this._deskT = setTimeout(adv, Math.max(4000, seg.length * 600 / this.rate()));
    } else if (window.speechSynthesis) {
      const u = new SpeechSynthesisUtterance(seg);
      u.lang = 'zh-CN'; u.rate = this.rate();
      u.onend = () => { if (this.playing && myGen === this.gen) { this.idx++; this.next(); } };
      u.onerror = () => { if (this.playing && myGen === this.gen) { this.idx++; this.next(); } };
      speechSynthesis.speak(u);
    } else { toast('当前环境不支持语音朗读', true); this.stop(); }
  },
  reRate() {
    // 调语速：取消当前发声，但 idx 不动 → 从当前这句接着读，不从头
    if (!this.playing) return;
    this.gen++;
    try { if (this.native()) window.GongkaoNative.ttsCancel(); } catch (_) {}
    try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch (_) {}
    deskStop(); clearTimeout(this._deskT); this._deskCb = null;
    setTimeout(() => this.next(), 60);
  },
  stop() {
    this.playing = false; this.gen++; this.segs = []; this.idx = 0;
    if (this.card) { this.card.classList.remove('reading-src'); this.card = null; }
    try { if (this.native()) window.GongkaoNative.ttsCancel(); } catch (_) {}
    try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch (_) {}
    deskStop(); clearTimeout(this._deskT); this._deskCb = null;
    this.ui();
  },
  ui() {
    $('#read-ctrl').classList.toggle('hidden', !this.playing);
    $('#read-rate').textContent = this.rate().toFixed(1) + '×';
  },
};
// 安卓 TTS 段落结束回调
window.__ttsEvent = function (id, ev) {
  if (ev === 'end' && Reader.playing && id === Reader._waitId) { Reader.idx++; Reader.next(); }
};
$('#read-stop').onclick = () => Reader.stop();
$('#read-rate').onclick = () => {
  Reader.rateIdx = (Reader.rateIdx + 1) % READ_RATES.length;
  $('#read-rate').textContent = Reader.rate().toFixed(1) + '×';
  Reader.reRate();
};
// 自动给内容条目注入 🔊 朗读按钮（MutationObserver 覆盖所有现在/将来渲染的列表）
const READ_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>';
const SHARE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.6" y1="10.5" x2="15.4" y2="6.5"/><line x1="8.6" y1="13.5" x2="15.4" y2="17.5"/></svg>';
async function shareCard(card) {
  const text = (Reader.textOf(card) || '').trim();
  if (!text) { toast('这一条没有可分享的文字', true); return; }
  const payload = text + '\n\n—— 来自「公考助手」';
  try {
    if (window.GongkaoNative && typeof GongkaoNative.share === 'function') { GongkaoNative.share(payload); return; }
  } catch (_) {}
  if (navigator.share) {
    try { await navigator.share({ text: payload }); return; } catch (e) { if (e && e.name === 'AbortError') return; }
  }
  // 剪贴板兜底（旧 APK / 无分享面板环境）
  let copied = false;
  try { await navigator.clipboard.writeText(payload); copied = true; } catch (_) {}
  if (!copied) {
    try {
      const ta = document.createElement('textarea');
      ta.value = payload; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      copied = document.execCommand('copy'); ta.remove();
    } catch (_) {}
  }
  toast(copied ? '已复制内容，去微信等应用粘贴即可（更新 APK 后可直接弹分享面板）' : '分享失败', !copied);
}
/* ---- 朗读：两条路，覆盖所有带文字的地方（不放进悬浮球）----
   ① 卡片/整篇上的 🔊 —— READ_ITEM_SEL 里已经包含 .poly-reader / #viewer-reader / .cd-body
      这些整篇容器，所以「读整篇」本来就有，不用再做一个「朗读本页」
   ② 选中一段文字 —— 冒出「🔊 朗读选中」，只读选中的那段 */
// 选中文字 → 冒出朗读气泡（手写笔/鼠标划选都行）
let _selBub = null;
function selBubHide() { if (_selBub) { _selBub.remove(); _selBub = null; } }
document.addEventListener('selectionchange', () => {
  clearTimeout(window._selT);
  window._selT = setTimeout(() => {
    const sel = window.getSelection();
    const txt = sel && String(sel).trim();
    if (!txt || txt.length < 6 || sel.isCollapsed) { selBubHide(); return; }
    // 输入框里的选中不算（那是在编辑，不是在读）
    const a = sel.anchorNode;
    if (a && a.parentElement && a.parentElement.closest('input, textarea, [contenteditable]')) return;
    let r;
    try { r = sel.getRangeAt(0).getBoundingClientRect(); } catch (_) { return; }
    if (!r || (!r.width && !r.height)) return;
    if (!_selBub) {
      _selBub = document.createElement('button');
      _selBub.className = 'sel-read';
      _selBub.innerHTML = '🔊 朗读选中';
      _selBub.onmousedown = e => e.preventDefault();     // 别把选区点没了
      _selBub.onclick = () => {
        const t = String(window.getSelection()).trim();
        selBubHide();
        if (!t) return;
        Reader.stop();
        Reader.segs = Reader.split(t); Reader.idx = 0; Reader.playing = true;
        Reader.card = null; Reader.ui(); Reader.next();
      };
      document.body.appendChild(_selBub);
    }
    const top = r.top - 42 < 6 ? r.bottom + 8 : r.top - 42;
    _selBub.style.left = Math.max(8, Math.min(window.innerWidth - 110, r.left + r.width / 2 - 52)) + 'px';
    _selBub.style.top = top + 'px';
  }, 220);
});
document.addEventListener('scroll', selBubHide, true);

function injectReadBtns() {
  document.querySelectorAll(READ_ITEM_SEL).forEach(card => {
    if (card.classList.contains('ai-typing')) return;  // 「思考中…」气泡不加按钮
    if (card.querySelector(':scope > .read-item-btn')) return;
    if (!(card.innerText || '').trim()) return;
    const b = document.createElement('button');
    b.className = 'read-item-btn'; b.title = '朗读这一条'; b.innerHTML = READ_ICON;
    b.onclick = e => { e.stopPropagation(); e.preventDefault(); Reader.readCard(card); };
    card.appendChild(b);
    const sb = document.createElement('button');
    sb.className = 'read-item-btn share-item-btn'; sb.title = '分享这一条'; sb.innerHTML = SHARE_ICON;
    sb.onclick = e => { e.stopPropagation(); e.preventDefault(); shareCard(card); };
    card.appendChild(sb);
  });
}
let _readInjTimer = null;
new MutationObserver(() => {
  clearTimeout(_readInjTimer);
  _readInjTimer = setTimeout(injectReadBtns, 120);
}).observe(document.body, { childList: true, subtree: true });
injectReadBtns();

/* ================= 账户 / 个人信息页 ================= */
async function openAccount() {
  push({ view: 'account', title: '账户' });
  try {
    const d = await api('/api/account');
    const qs = (await api('/api/sec_questions')).questions;
    $('#acct-name').textContent = d.username || (ME && ME.username) || '';
    $('#acct-email').textContent = d.email ? ('📧 ' + d.email) : '未绑定邮箱';
    $('#acct-role').textContent = (ME && ME.is_admin) ? '管理员' : '普通用户';
    $('#acct-email-in').value = d.email || '';
    $('#acct-secq').innerHTML = qs.map(q => `<option ${q === d.sec_question ? 'selected' : ''}>${esc(q)}</option>`).join('');
    $('#acct-oldpw').value = ''; $('#acct-newpw').value = ''; $('#acct-seca').value = '';
    $('#acct-app').classList.toggle('hidden', !(IN_APP || IS_DESKTOP));
    $('#acct-app-t').textContent = IS_DESKTOP ? '💻 桌面版' : '📱 App';
    document.querySelectorAll('#acct-app .apk-only')            // 通知/切服务器只有安卓壳有
      .forEach(b => b.classList.toggle('hidden', !IN_APP));
    $('#acct-app-hint').classList.toggle('hidden', !IS_DESKTOP);
    $('#acct-dver').textContent = 'v' + (DESKTOP_VER || '?');
    renderSkinPrev();
    ttsSetup();
    refreshNotifyBtn();
  } catch (e) { toast(e.message, true); }
}
$('#brand-logo').onclick = openAccount;
$('#account-btn').onclick = openAccount;
$('#home-btn').onclick = goHome;

$('#acct-email-save').onclick = async () => {
  try {
    await api('/api/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: $('#acct-email-in').value.trim() }) });
    const em = $('#acct-email-in').value.trim();
    $('#acct-email').textContent = em ? ('📧 ' + em) : '未绑定邮箱';
    toast('邮箱已保存');
  } catch (e) { toast(e.message, true); }
};
$('#acct-pw-save').onclick = async () => {
  const np = $('#acct-newpw').value;
  if (!np) { toast('请输入新密码', true); return; }
  try {
    await api('/api/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ new_password: np, old_password: $('#acct-oldpw').value }) });
    $('#acct-oldpw').value = ''; $('#acct-newpw').value = ''; toast('密码已修改');
  } catch (e) { toast(e.message, true); }
};
$('#acct-sec-save').onclick = async () => {
  if (!$('#acct-seca').value.trim()) { toast('请输入密保答案', true); return; }
  try {
    await api('/api/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sec_question: $('#acct-secq').value, sec_answer: $('#acct-seca').value }) });
    $('#acct-seca').value = ''; toast('密保已保存');
  } catch (e) { toast(e.message, true); }
};
$('#acct-refresh').onclick = () => {
  if (window.GongkaoNative && window.GongkaoNative.reload) { try { window.GongkaoNative.reload(); return; } catch (_) {} }
  location.reload();
};
$('#acct-server').onclick = () => { try { window.GongkaoNative && window.GongkaoNative.changeServer(); } catch (_) {} };
$('#acct-logout').onclick = doLogout;
