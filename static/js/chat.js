/* 聊天
 *
 * 由 app.js 按它自己的区段边界切出（原 L7412-7705）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, IS_MOBILE, ME, SKIN, anchorMenu, api, appConfirm, appPrompt, artEm,
   back, c, clipFiles, composing, compressImage, dvIcon, esc,
   fSize, growAndSync, init, lightbox, lsDel, lsGet, lsSet, preview, push, stack,
   state, toast */

/* ================= 聊天 ================= */
let chTab = 'convos', crFid = 0, crGid = 0, crName = '', crLastId = 0, crPoll = 0;
let crMembers = [];   // 群成员（@ 高亮和信息栏用）
let crFriendAvatar = '', crMeAvatar = '', crLastTime = '';   // 头像 + 上一条时间（做时间分隔）
function openChat() {
  push({ view: 'chat', title: '聊天' }); chSwitch('convos'); ensureNotifyPerm();
  crShowEmpty();                       // 桌面进来先在右栏显示空态；移动端只看列表
}
// 右栏空态（还没选会话）
function crShowEmpty() {
  crFid = 0; crGid = 0; clearInterval(crPoll);
  const p2 = $('#chat-2pane'); if (p2) p2.classList.remove('show-room');
  $('#cr-peer').classList.add('hidden'); $('#cr-input').classList.add('hidden');
  $('#cr-empty').classList.remove('hidden'); $('#cr-msgs').innerHTML = '';
  crRenderAnnounce('');
}
// 当前是否正开着和某人的聊天窗（桌面：选了会话；移动端：栈顶带 room）
function crInRoom() {
  const st = stack[stack.length - 1] || {};
  if (st.view !== 'chat') return false;
  return IS_MOBILE ? !!st.room : (!!crFid || !!crGid);
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
    if (!d.conversations.length) { $('#ch-convos').innerHTML = '<p class="empty">还没有会话。去「好友」找人聊，或「' + artEm('＋') + ' 加好友」。</p>'; return; }
    $('#ch-convos').innerHTML = d.conversations.map(c => `
      <div class="ch-convo${c.self ? ' ch-self' : ''}" ${c.group ? `data-crg="${c.id}"` : `data-crf="${c.id}"`} data-crn="${esc(c.username)}">
        ${c.self ? '<div class="ch-av ch-av-self">' + artEm('📁') + '</div>'
    : c.group ? `<div class="ch-av ch-av-g">${esc((c.username || '组').slice(0, 1))}</div>`
      : avHtml(c.avatar, c.username, 'ch-av')}
        <div class="ch-cmid">
          <div class="ch-cn">${esc(c.username)}${c.group ? `<span class="ch-nmem">${c.n_mem}</span>` : ''}</div>
          <div class="ch-cp">${c.at ? '<span class="ch-at">[有人@我]</span> ' : ''}${c.last_mine ? `<span class="ch-tick">${c.last_read ? artEm('✓') + artEm('✓') : artEm('✓')}</span> ` : ''}${esc(c.preview || '')}</div></div>
        <div class="ch-cright"><div class="ch-ct">${esc((c.time || '').slice(5, 16))}</div>${c.unread ? `<span class="ch-un">${c.unread}</span>` : ''}</div>
      </div>`).join('');
  } catch (e) { $('#ch-convos').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#ch-convos').addEventListener('click', e => {
  const g = e.target.closest('[data-crg]');
  if (g) { openGroup(+g.dataset.crg, g.dataset.crn); return; }
  const c = e.target.closest('[data-crf]'); if (c) openChatroom(+c.dataset.crf, c.dataset.crn);
});
async function loadFriends() {
  $('#ch-friends').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/friends');
    if (d.n_req) { $('#ch-reqbadge').textContent = d.n_req; $('#ch-reqbadge').classList.remove('hidden'); }
    else $('#ch-reqbadge').classList.add('hidden');
    if (!d.friends.length) { $('#ch-friends').innerHTML = '<p class="empty">还没有好友。点「' + artEm('＋') + ' 加好友」搜用户名或 ID 添加。</p>'; return; }
    $('#ch-friends').innerHTML = d.friends.map(f => `
      <div class="ch-frow" data-crf="${f.id}" data-crn="${esc(f.username)}">
        ${avHtml(f.avatar, f.username, 'ch-av')}
        <div class="ch-cn">${esc(f.username)}</div>
        <button class="ch-chat" data-crf="${f.id}" data-crn="${esc(f.username)}">聊天</button>
        <button class="ch-fdel" data-fdel="${f.id}" title="删除好友">${artEm('✕')}</button></div>`).join('');
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
  } catch (_) { /* 拉不到就先空着，15 秒后的轮询会补上 */ }
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

/* ---- 小组（群聊）----
   群和一对一共用同一个聊天窗，只是取/发走 /api/chat/g/<id>：crGid 非 0 就是在群里。
   这样气泡、引用、撤回、卡片、草稿那一整套都不用写第二份。 */
function crUrl(sub) {
  const base = crGid ? '/api/chat/g/' + crGid : '/api/chat/' + crFid;
  return base + (sub || '');
}
function openGroup(gid, name) {
  crSaveDraft();                       // 先把上一个会话没发完的话存住（必须在改会话标识之前）
  crGid = gid; crFid = 0; crName = name || '小组'; crLastId = 0;
  crMeAvatar = SKIN.avatar || ''; crFriendAvatar = ''; crLastTime = '';
  crHasMore = false; crFirstId = 0; crReadUpto = 0; crMembers = [];
  crClearReply(); crLoadDraft(crKey());
  if ((stack[stack.length - 1] || {}).view !== 'chat') push({ view: 'chat', title: '聊天' });
  if (IS_MOBILE) push({ view: 'chat', room: 'g' + gid, title: crName });
  const p2 = $('#chat-2pane'); if (p2) p2.classList.add('show-room');
  $('#cr-peername').textContent = crName;
  $('#cr-peer').classList.remove('hidden');
  $('#cr-input').classList.remove('hidden');
  $('#cr-empty').classList.add('hidden');
  $('#cr-msgs').innerHTML = '<p class="empty">加载中…</p>';
  crLoad(true);
  clearInterval(crPoll);
  crPoll = setInterval(() => { if (crInRoom()) crLoad(false); else clearInterval(crPoll); }, 10000);
}
// 新建小组：从好友里勾人
async function crNewGroup() {
  const name = await appPrompt('新建学习小组', '小组名，如：省考冲刺小组');
  if (!name || !name.trim()) return;
  let fr = [];
  try { fr = (await api('/api/friends')).friends || []; } catch (e) { toast(e.message, true); return; }
  if (!fr.length) { toast('先加几个好友再建组', true); return; }
  const box = $('#cr-picker');
  box.classList.remove('hidden');
  box.innerHTML = `<div class="cp-box"><div class="cp-head">拉谁进「${esc(name.trim())}」<button data-cpx>${artEm('✕')}</button></div>
    <div class="cp-list">${fr.map(f => `<label class="cp-item cp-check"><input type="checkbox" value="${f.id}"> <span class="t">${esc(f.username)}</span></label>`).join('')}</div>
    <div class="mem-add"><button id="cp-gok">创建小组</button></div></div>`;
  $('#cp-gok').onclick = async () => {
    const ids = [...box.querySelectorAll('input:checked')].map(x => +x.value);
    box.classList.add('hidden');
    try {
      const d = await api('/api/chat/groups', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), members: ids })
      });
      await loadConvos();
      openGroup(d.id, d.name);
    } catch (e) { toast(e.message, true); }
  };
}
$('#ch-newgroup').onclick = crNewGroup;

// —— 打开某人的聊天窗（右栏）——
function openChatroom(fid, name) {
  crSaveDraft();                       // 先把上一个会话没发完的话存住（**必须在改 crGid 之前**：
  crGid = 0;                           //  草稿的 key 是按当前会话算的，先清了就存到别人头上了）
  crFid = fid; crName = name; crLastId = 0;
  crFriendAvatar = ''; crMeAvatar = SKIN.avatar || ''; crLastTime = '';
  crHasMore = false; crFirstId = 0; crReadUpto = 0;
  crClearReply(); crLoadDraft(crKey()); crRenderAnnounce('');
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
let crLoading = false, crLoadingMore = false, crHasMore = false, crFirstId = 0, crReadUpto = 0;
async function crLoad(first) {
  // 并发锁：轮询 / SSE 推送 / 发送后刷新可能同时进来，都读同一个 crLastId、都拉同一批消息、
  // 都往界面追加 → 同一条消息重复显示（对方以为你连发了好几条）。一次只跑一个。
  if (crLoading && !first) return;
  crLoading = true;
  try {
    // 首屏**不带 after**：后端给最近 50 条。原先带 after=0，后端那句是 `id>0 ORDER BY id LIMIT 200`，
    // 也就是从最老的一条开始截 —— 聊过几百条的会话进来看到的是几个月前的对话。
    const d = await api(crUrl(first ? '' : '?after=' + crLastId));
    if (d.friend_avatar !== undefined) crFriendAvatar = d.friend_avatar || '';
    if (d.me_avatar) crMeAvatar = d.me_avatar;
    if (!crGid && !crName && d.friend) {   // 从通知点进来时没带名字，拿到后补上
      crName = d.friend;
      $('#cr-peername').textContent = crName;
      const top = stack[stack.length - 1] || {};
      if (IS_MOBILE && top.room) { top.title = crName; $('#top-title').textContent = crName; }
    }
    if (crGid) {                    // 群：名字、公告、成员都随消息一起回来
      crMembers = d.members || crMembers;
      if (d.name) { crName = d.name; $('#cr-peername').textContent = d.name; }
      crRenderAnnounce(d.announce);
    }
    const box = $('#cr-msgs');
    if (first) {
      box.innerHTML = '<div id="cr-more" class="cr-more"></div>';
      crLastTime = ''; crHasMore = !!d.has_more; crFirstId = 0; crReadUpto = 0;
    }
    if (!d.messages.length && first) box.insertAdjacentHTML('beforeend', '<p class="empty">还没有消息，发一条打个招呼吧 👋</p>');
    if (d.messages.length) { const e = box.querySelector('.empty'); if (e) e.remove(); }
    for (const m of d.messages) {
      // 乐观气泡已经把自己发的那条画出来了（发送成功时就地转实），增量拉取会再带回同一条 ——
      // 认 id 去重，否则自己发的消息会显示两遍。
      if (box.querySelector('[data-mid="' + m.id + '"]')) { crLastId = Math.max(crLastId, m.id); continue; }
      crLastId = Math.max(crLastId, m.id);
      if (!crFirstId) crFirstId = m.id;
      if (crShouldSep(crLastTime, m.time)) box.insertAdjacentHTML('beforeend', `<div class="cr-time">${esc(crTimeLabel(m.time))}</div>`);
      crLastTime = m.time || crLastTime;
      box.insertAdjacentHTML('beforeend', crMsgHtml(m));
    }
    crApplyRead(d.read_upto);
    crApplyRecalled(d.recalled);
    if (first) crRenderMore();
    if (d.messages.length) crStickBottom(box, first);
  } catch (e) { if (first) $('#cr-msgs').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
  finally { crLoading = false; }
}
/* 滚到底。
   滚一次不够：图片（哪怕是缩略图）、表格、字体都是**加载完才有高度**的，
   那一刻内容会变长，刚才滚到的「底」就不再是底了 —— 表现就是「进来还得自己往下滑」。
   所以：先滚一次，再等这一屏里还没加载完的图各自 load 之后补滚；
   用户只要自己往上翻了（离底超过一屏的三分之一），立刻停手，别跟人抢滚动条。 */
let crStickTimer = 0;
function crStickBottom(box, strong) {
  const jump = () => { box.scrollTop = box.scrollHeight; };
  jump();
  requestAnimationFrame(jump);
  if (!strong) return;                 // 增量拉新只补一下；下面那套只在进房时用
  clearTimeout(crStickTimer);
  let stop = false;
  const onScroll = () => {
    if (box.scrollHeight - box.scrollTop - box.clientHeight > box.clientHeight / 3) stop = true;
  };
  box.addEventListener('scroll', onScroll, { passive: true });
  const armed = [...box.querySelectorAll('img')].filter(im => !im.complete);
  armed.forEach(im => {
    const on = () => { if (!stop) jump(); };
    im.addEventListener('load', on, { once: true });
    im.addEventListener('error', on, { once: true });
  });
  // 兜底：图片可能一直不 load（断网/404），2 秒后收手，别一直挂着监听
  crStickTimer = setTimeout(() => box.removeEventListener('scroll', onScroll), 2000);
}
// 群公告：置顶一条，进组先看到规则
function crRenderAnnounce(text) {
  const el = $('#cr-announce'); if (!el) return;
  el.classList.toggle('hidden', !(crGid && text));
  if (crGid && text) el.innerHTML = artEm('📌') + ' ' + esc(text);
}
// 顶部那条「加载更早的消息」。首屏只给最近 50 条，更早的按需往上翻。
function crRenderMore() {
  const el = $('#cr-more'); if (!el) return;
  el.innerHTML = crHasMore
    ? '<button class="cr-morebtn" id="cr-morebtn">↑ 加载更早的消息</button>'
    : (crFirstId ? '<span class="cr-moreend">没有更早的消息了</span>' : '');
}
async function crLoadMore() {
  if (crLoadingMore || !crHasMore || !crFirstId) return;
  crLoadingMore = true;
  const el = $('#cr-more'); if (el) el.innerHTML = '<span class="cr-moreend">加载中…</span>';
  const box = $('#cr-msgs'), h0 = box.scrollHeight, t0 = box.scrollTop;
  try {
    const d = await api(crUrl('?before=' + crFirstId));
    crHasMore = !!d.has_more;
    let html = '', prevT = '';
    for (const m of d.messages) {
      if (crShouldSep(prevT, m.time)) html += `<div class="cr-time">${esc(crTimeLabel(m.time))}</div>`;
      prevT = m.time || prevT;
      html += crMsgHtml(m);
    }
    if (d.messages.length) {
      crFirstId = d.messages[0].id;
      $('#cr-more').insertAdjacentHTML('afterend', html);
      // 插在上面会把内容整体顶下去；补回高度差，视觉上停在原处（不然一翻页就跳走）
      box.scrollTop = t0 + (box.scrollHeight - h0);
    }
    crRenderMore();
  } catch (e) { toast(e.message, true); crRenderMore(); }
  crLoadingMore = false;
}
$('#cr-msgs').addEventListener('click', e => { if (e.target.closest('#cr-morebtn')) crLoadMore(); });
// 滚到顶自动接着加载（和按钮并存：手指甩上去的人不用再找按钮）
$('#cr-msgs').addEventListener('scroll', () => { if ($('#cr-msgs').scrollTop < 40) crLoadMore(); }, { passive: true });

/* 正文渲染：转义之后再把链接挑出来做成可点的。
   先 esc 再匹配，所以匹配的是转义后的文本 —— & 会变成 &amp;，正则里把 &amp; 当作 & 收进
   链接（否则带 query 的网址会在第一个 & 处断掉）。 */
function crText(s) {
  let safe = esc(s || '');
  /* 轻量 Markdown，只认这三样：**加粗**、`行内代码`、行首「- 」项目符号。
     不上完整的 mdToHtml —— 聊天里随手打的 # 和数字点会被当成标题和有序列表，
     那是把别人的话改了样子，比不渲染更糟。 */
  safe = safe.replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|\n)- (?=\S)/g, '$1· ');   // 此刻换行还是 \n（下面才转 <br>）
  // 群里 @ 到的名字高亮；@我 自己那条更醒目一点
  if (crGid) {
    const mine = (ME && ME.username) || '';
    safe = safe.replace(/@([^\s@:：,，。!！?？]{1,20})/g, (all, n) =>
      (n === mine || /^(所有人|全体成员|all)$/i.test(n))
        ? `<span class="cr-atme">${all}</span>`
        : (crMembers.some(x => x.username === n) ? `<span class="cr-at">${all}</span>` : all));
  }
  return safe.replace(/((?:https?:\/\/|www\.)[\w\-.~:/?#[\]@!$'()*+,;=%]+(?:&amp;[\w\-.~:/?#[\]@!$'()*+,;=%]*)*)/g,
    u => {
      let tail = '';
      while (/[.,;:)\]}]$/.test(u)) { tail = u.slice(-1) + tail; u = u.slice(0, -1); }   // 句末标点不算链接的一部分
      const href = /^www\./.test(u) ? 'https://' + u : u;
      return `<a class="cr-link" href="${href}" target="_blank" rel="noopener noreferrer">${u}</a>${tail}`;
    }).replace(/\n/g, '<br>');
}
function crMsgHtml(m) {
  let inner;
  if (m.recalled || m.kind === 'recalled') {
    return `<div class="cr-sys" data-mid="${m.id}">${m.mine ? '你' : esc(crName || '对方')}撤回了一条消息` +
      // 原文走 encodeURIComponent 塞属性：esc 只挡 <>&，正文里一个双引号就能把属性截断
      (m.mine && m.body ? ' <span class="cr-reedit" data-reedit="' + encodeURIComponent(m.body) + '">重新编辑</span>' : '') + '</div>';
  }
  if (m.kind === 'card' && m.card) {
    const meta = CARD_META[m.card.kind] || { ic: '📄', name: '内容' };
    inner = `<div class="cr-card" data-card="${esc(m.card.kind)}" data-cid="${m.card.id || 0}">
      <div class="k">${meta.ic} 来自${esc(meta.name)}</div>
      <div class="t">${esc(m.card.title || '')}</div>
      ${m.card.sub ? `<div class="f">${esc(m.card.sub)} · 点开直接看</div>` : '<div class="f">点开直接看</div>'}
    </div>`;
  // **不加 loading="lazy"**：视口外的图不加载 → 高度算 0 → 「进来滚到底」滚到的是
  // 一个不含图片高度的假底，图片随后加载又把内容撑长，就成了「还得自己往下滑」。
  // 首屏只有 50 条、拿的又是缩略图，本来也不需要 lazy。
  } else if (m.kind === 'image') inner = `<img class="cr-img" src="/api/chat/file/${m.file_id}?thumb=1" data-lbimg="/api/chat/file/${m.file_id}?inline=1">`;
  else if (m.kind === 'file') inner = `<a class="cr-file" href="/api/chat/file/${m.file_id}" download><span class="cr-fic">${dvIcon((m.file_name || '').split('.').pop())}</span><span class="cr-fmid"><span class="cr-fn">${esc(m.file_name || '文件')}</span><em>${fSize(m.file_size)}</em></span></a>`;
  else inner = crText(m.body);
  if (m.quote) {
    inner = `<div class="cr-quote" data-jump="${m.quote.id}"><b>${esc(m.quote.who)}</b>：${esc(m.quote.text)}</div>` + inner;
  }
  const av = avHtml(m.mine ? crMeAvatar : crFriendAvatar,
    m.mine ? '我' : (crGid ? (m.who || '?') : crName), 'cr-av');
  // 群里必须看得出是谁说的（一对一就没必要，两个人还署名很啰嗦）
  const who = (crGid && !m.mine && m.who) ? `<div class="cr-who">${esc(m.who)}</div>` : '';
  // 自己的消息带一行状态：发送中 → 已送达 → 已读（对方那侧一读，crApplyRead 就地翻牌）
  const meta = m.mine
    ? `<div class="cr-meta">${m.pending ? '<i class="cr-spin"></i> 发送中' : (m.read ? '✓✓ 已读' : '✓ 已送达')}</div>` : '';
  const attr = m.tmp ? ` data-tmp="${m.tmp}"` : (m.id ? ` data-mid="${m.id}"` : '');
  return `<div class="cr-row ${m.mine ? 'mine' : 'theirs'}"${attr}>${av}<div class="cr-bcol">${who}` +
    `<div class="cr-bubble ${m.kind}${m.pending ? ' sending' : ''}">${inner}</div>${meta}</div></div>`;
}
/* 撤回是**就地改状态**，增量拉取（after=最大 id）带不回来 —— 后端单给一份「最近撤回的 id」，
   这里把已经画在屏幕上的那条换成一行灰字。 */
function crApplyRecalled(ids) {
  if (!ids || !ids.length) return;
  for (const id of ids) {
    const row = $('#cr-msgs').querySelector('.cr-row[data-mid="' + id + '"]');
    if (!row) continue;
    const mine = row.classList.contains('mine');
    row.outerHTML = crMsgHtml({ id: id, mine: mine, recalled: true });
  }
}
// 对方读到哪了：把水位以下自己发的气泡统一翻成「已读」。
// 增量拉取只带回**新**消息，已经画出来的老气泡不会再随消息回来，所以单给一个水位。
function crApplyRead(upto) {
  upto = +upto || 0;
  if (upto <= crReadUpto) return;
  crReadUpto = upto;
  $('#cr-msgs').querySelectorAll('.cr-row.mine[data-mid]').forEach(r => {
    if (+r.dataset.mid > upto) return;
    const mt = r.querySelector('.cr-meta');
    if (mt && mt.textContent.indexOf('已读') < 0 && mt.textContent.indexOf('失败') < 0) mt.textContent = '✓✓ 已读';
  });
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
let crSending = false;      // 发送锁：文件那条路一次只跑一批
const CHAT_MAX = 4000;      // 和后端 social.py CHAT_MAX 一致
let crTmpSeq = 0;
$('#cr-send').onclick = crSendText;
// 手机端 ➕：弹出工具行（附件 + 四种内容卡片）；桌面端那一行本来就常驻
$('#cr-plus').onclick = () => anchorMenu($('#cr-input').querySelector('.input-tools'), $('#cr-plus'));
$('#cr-input').addEventListener('click', e => {
  const b = e.target.closest('[data-crcard]'); if (!b) return;
  if (IS_MOBILE) $('#cr-input .input-tools').classList.add('hidden');
  crPickCard(b.dataset.crcard);
});
function crGrow() { growAndSync('#cr-text', '#cr-input'); }
let crDraftTimer = 0;
$('#cr-text').addEventListener('input', () => {
  crGrow(); crCount();
  clearTimeout(crDraftTimer); crDraftTimer = setTimeout(crSaveDraft, 400);   // 别每敲一个字写一次 localStorage
});
// 关页面/切后台也存一次，否则最后 400 毫秒里打的字会丢
window.addEventListener('pagehide', crSaveDraft);
document.addEventListener('visibilitychange', () => { if (document.hidden) crSaveDraft(); });
// ⚠️ 打中文时按 Enter 是「确认候选词」，不能当发送 —— 不加 composing 守卫会导致边打字边误发、甚至连发好几条
$('#cr-text').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey && !composing(e)) { e.preventDefault(); crSendText(); }
});
// 点失败的那条 → 原样重发（不用重新打字）；撤回后「重新编辑」把原文塞回输入框
$('#cr-msgs').addEventListener('click', e => {
  const re = e.target.closest('[data-reedit]');
  if (re) {
    $('#cr-text').value = decodeURIComponent(re.dataset.reedit);
    crGrow(); crCount(); $('#cr-text').focus();
    return;
  }
  const q = e.target.closest('[data-jump]');
  if (q) { crJumpTo(+q.dataset.jump); return; }
  const f = e.target.closest('.cr-fail'); if (!f) return;
  const row = f.closest('.cr-row'); if (row && row.dataset.text) crSendOne(row.dataset.text, row);
});
// 跳到被引用的那条：在当前已加载的范围里找得到就高亮一下，找不到就说明它在更早的历史里
function crJumpTo(id) {
  const row = $('#cr-msgs').querySelector('[data-mid="' + id + '"]');
  if (!row) { toast('那条消息在更早的记录里，先往上加载'); return; }
  row.scrollIntoView({ block: 'center', behavior: 'smooth' });
  row.classList.add('cr-hl');
  setTimeout(() => row.classList.remove('cr-hl'), 1400);
}

/* ---- 消息操作菜单（长按 / 右键）---- */
let crMenuMid = 0;
function crOpenMenu(row, x, y) {
  const mid = +row.dataset.mid; if (!mid) return;
  crMenuMid = mid;
  const mine = row.classList.contains('mine');
  const isText = !!row.querySelector('.cr-bubble.text');
  const items = [];
  items.push('<button data-cm="quote">↩︎ 引用</button>');
  if (isText) items.push('<button data-cm="copy">📋 复制</button>');
  if (isText) items.push('<button data-cm="wrongq">📓 存进错题本</button>');
  if (mine) items.push('<button data-cm="recall" class="danger">↺ 撤回</button>');
  const el = $('#cr-menu');
  el.innerHTML = items.join('');
  el.classList.remove('hidden');
  // 贴着手指弹，但别越出屏幕
  const w = el.offsetWidth || 150, h = el.offsetHeight || 40;
  el.style.left = Math.max(8, Math.min(x, window.innerWidth - w - 8)) + 'px';
  el.style.top = Math.max(8, Math.min(y, window.innerHeight - h - 8)) + 'px';
}
function crCloseMenu() { $('#cr-menu').classList.add('hidden'); crMenuMid = 0; }
document.addEventListener('click', e => { if (!e.target.closest('#cr-menu')) crCloseMenu(); });
$('#cr-msgs').addEventListener('contextmenu', e => {
  const row = e.target.closest('.cr-row[data-mid]'); if (!row) return;
  e.preventDefault(); crOpenMenu(row, e.clientX, e.clientY);
});
// 手机端：长按 480ms 弹菜单；手指一动就取消（不然滚动列表也会弹）
(function () {
  let t = 0, sx = 0, sy = 0;
  const box = $('#cr-msgs'); if (!box) return;
  box.addEventListener('touchstart', e => {
    const row = e.target.closest('.cr-row[data-mid]'); if (!row || e.touches.length !== 1) return;
    const p = e.touches[0]; sx = p.clientX; sy = p.clientY;
    clearTimeout(t);
    t = setTimeout(() => crOpenMenu(row, sx, sy), 480);
  }, { passive: true });
  const cancel = e => {
    if (e.touches && e.touches[0]) {
      const p = e.touches[0];
      if (Math.abs(p.clientX - sx) < 8 && Math.abs(p.clientY - sy) < 8) return;   // 没动就不算取消
    }
    clearTimeout(t);
  };
  box.addEventListener('touchmove', cancel, { passive: true });
  box.addEventListener('touchend', () => clearTimeout(t), { passive: true });
  box.addEventListener('touchcancel', () => clearTimeout(t), { passive: true });
})();
$('#cr-menu').addEventListener('click', async e => {
  const b = e.target.closest('[data-cm]'); if (!b) return;
  const mid = crMenuMid, row = $('#cr-msgs').querySelector('[data-mid="' + mid + '"]');
  crCloseMenu();
  if (!row) return;
  const bub = row.querySelector('.cr-bubble');
  const text = bub ? bub.innerText.trim() : '';
  if (b.dataset.cm === 'copy') {
    try { await navigator.clipboard.writeText(text); toast('已复制'); }
    catch (_) { toast('这个浏览器不让复制，长按选中吧', true); }
  } else if (b.dataset.cm === 'quote') {
    crSetReply(mid, row.classList.contains('mine') ? '我' : crName, text);
  } else if (b.dataset.cm === 'recall') {
    try {
      const d = await api('/api/chat/msg/' + mid, { method: 'DELETE' });
      row.outerHTML = crMsgHtml({ id: mid, mine: true, recalled: true, body: d.body || '' });
      loadConvos();
    } catch (err) { toast(err.message, true); }
  } else if (b.dataset.cm === 'wrongq') {
    // 别人发来的题一键收进自己的错题本（复用错题本的新增接口）
    try {
      await api('/api/wrongq', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, board: '', qtype: '' })
      });
      toast('已存进错题本');
    } catch (err) { toast(err.message, true); }
  }
});

/* ---- 引用回复 ---- */
// 乐观气泡也要带引用条：从屏幕上那条原消息取摘要，别等服务端回来才显示
function crQuotePreview(mid) {
  const row = $('#cr-msgs').querySelector('[data-mid="' + mid + '"]');
  if (!row) return null;
  const b = row.querySelector('.cr-bubble');
  return { id: mid, who: row.classList.contains('mine') ? '我' : (crName || '对方'),
    text: (b ? b.innerText.trim() : '').slice(0, 60) };
}
let crReplyTo = 0;
function crSetReply(mid, who, text) {
  crReplyTo = mid;
  const bar = $('#cr-replybar');
  bar.innerHTML = `↩︎ 回复 <b>${esc(who || '')}</b>：${esc((text || '').slice(0, 40))}<span class="x" data-replycancel>${artEm('✕')}</span>`;
  bar.classList.remove('hidden');
  $('#cr-text').focus();
}
function crClearReply() { crReplyTo = 0; $('#cr-replybar').classList.add('hidden'); }
$('#cr-replybar').addEventListener('click', e => { if (e.target.closest('[data-replycancel]')) crClearReply(); });

/* ---- 会话信息：群显示成员/公告/退出，一对一显示共享过的文件 ---- */
async function crOpenInfo() {
  if (!crGid && !crFid) return;
  const box = $('#cr-picker');
  box.classList.remove('hidden');
  box.innerHTML = `<div class="cp-box"><div class="cp-head">会话信息<button data-cpx>${artEm('✕')}</button></div>
    <div class="cp-list"><p class="empty">加载中…</p></div></div>`;
  const list = box.querySelector('.cp-list');
  if (!crGid) {     // 一对一：把互相发过的文件聚到一处（文件传输助手用久了最需要这个）
    try {
      const d = await api('/api/chat/search?q=.&with=' + crFid);
      const files = (d.results || []).filter(r => r.file);
      list.innerHTML = `<p class="mem-tip">和 ${esc(crName)} 的会话</p>` + (files.length
        ? files.map(f => `<div class="ai-mem"><div class="c"><div class="t">${artEm('📄')} ${esc(f.text)}</div>
            <div class="s">${esc((f.time || '').slice(0, 16))}</div></div></div>`).join('')
        : '<p class="empty">还没有互发过文件。</p>');
    } catch (e) { list.innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
    return;
  }
  try {
    const g = await api('/api/chat/groups/' + crGid);
    crMembers = g.members || [];
    list.innerHTML = `
      <p class="mem-tip">${esc(g.name)} · ${g.members.length} 人</p>
      <div class="ai-mem"><div class="c"><div class="t">${artEm('📌')} ${esc(g.announce || '还没有群公告')}</div>
        ${g.is_owner ? '<div class="s"><span class="cr-reedit" data-gedit="announce">改公告</span> · <span class="cr-reedit" data-gedit="name">改组名</span></div>' : ''}
      </div></div>
      ${g.members.map(m => `<div class="ai-mem"><div class="c"><div class="t">${esc(m.username)}${m.owner ? ' <span class="ch-tag">群主</span>' : ''}</div></div>
        ${(g.is_owner && !m.owner) ? `<button class="x" data-gkick="${m.id}">${artEm('✕')}</button>` : ''}</div>`).join('')}
      <div class="mem-add"><button id="cr-ginvite">＋ 拉好友进来</button>
        <button id="cr-gleave" class="danger">${g.is_owner ? '解散小组' : '退出小组'}</button></div>`;
  } catch (e) { list.innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#cr-picker').addEventListener('click', async e => {
  const ed = e.target.closest('[data-gedit]');
  if (ed) {
    const isName = ed.dataset.gedit === 'name';
    const v = await appPrompt(isName ? '改组名' : '改群公告', isName ? '小组名' : '一句话说清规矩');
    if (v === null) return;
    try {
      await api('/api/chat/groups/' + crGid, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(isName ? { name: v } : { announce: v })
      });
      $('#cr-picker').classList.add('hidden');
      crLoad(true); loadConvos();
    } catch (err) { toast(err.message, true); }
    return;
  }
  const kick = e.target.closest('[data-gkick]');
  if (kick) {
    if (!(await appConfirm('把这个成员移出小组？'))) return;
    try { await api('/api/chat/groups/' + crGid + '/members/' + kick.dataset.gkick, { method: 'DELETE' }); crOpenInfo(); }
    catch (err) { toast(err.message, true); }
    return;
  }
  if (e.target.closest('#cr-gleave')) {
    if (!(await appConfirm('确定要退出这个小组吗？'))) return;
    try {
      await api('/api/chat/groups/' + crGid + '/members/' + (ME ? ME.id : 0), { method: 'DELETE' });
      $('#cr-picker').classList.add('hidden');
      crShowEmpty(); if (IS_MOBILE) back();
      loadConvos();
    } catch (err) { toast(err.message, true); }
    return;
  }
  if (e.target.closest('#cr-ginvite')) {
    let fr = [];
    try { fr = (await api('/api/friends')).friends || []; } catch (err) { toast(err.message, true); return; }
    const inside = new Set(crMembers.map(m => m.id));
    const out = fr.filter(f => !inside.has(f.id));
    if (!out.length) { toast('好友都已经在组里了'); return; }
    const box = $('#cr-picker');
    box.innerHTML = `<div class="cp-box"><div class="cp-head">拉谁进来<button data-cpx>${artEm('✕')}</button></div>
      <div class="cp-list">${out.map(f => `<label class="cp-item cp-check"><input type="checkbox" value="${f.id}"> <span class="t">${esc(f.username)}</span></label>`).join('')}</div>
      <div class="mem-add"><button id="cp-iok">加入小组</button></div></div>`;
    $('#cp-iok').onclick = async () => {
      const ids = [...box.querySelectorAll('input:checked')].map(x => +x.value);
      box.classList.add('hidden');
      try {
        await api('/api/chat/groups/' + crGid + '/members', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ members: ids })
        });
        toast('已拉进来'); crLoad(true);
      } catch (err) { toast(err.message, true); }
    };
  }
});
$('#cr-info').onclick = crOpenInfo;

/* ---- 内容卡片：把应用里的一条发给好友（这是这个聊天区别于微信的地方）----
   各功能的列表接口字段不一样，所以每种给一个「怎么拉、怎么取标题」的适配；
   点开时复用已有的 openXxx，跟自己在应用里点进去是同一条路。 */
// 每个接口的分页参数名都不一样（entries 是 page_size 且默认才 5 条，classics 固定 10 条一页），
// 所以这里逐个写清楚，别想当然套一个 limit。
const CARD_META = {
  wrongq: { ic: '📓', name: '错题本', api: '/api/wrongq?page_size=30',
    pick: d => (d.items || []).map(x => ({ id: x.id, title: x.question || '', sub: [x.board, x.qtype].filter(Boolean).join(' · ') })),
    open: 'openWrongq' },
  classic: { ic: '📖', name: '古诗文', api: '/api/classics',
    pick: d => (d.items || []).map(x => ({ id: x.id, title: x.title || x.content || '', sub: [x.dynasty, x.author].filter(Boolean).join(' · ') })),
    open: 'openClassics' },
  sucai: { ic: '📁', name: '素材', api: '/api/sucai',
    pick: d => (d.items || []).map(x => ({ id: x.id, title: x.title || x.content || '', sub: x.kind || '' })),
    open: 'openSucai' },
  note: { ic: '🗒️', name: '小记', api: '/api/notes',
    pick: d => (d.items || []).map(x => ({ id: x.id, title: x.content || '', sub: (x.created_at || '').slice(0, 10) })),
    open: 'openNotes' },
  entry: { ic: '📖', name: '收录的词', api: '/api/entries?page_size=30',
    pick: d => (d.items || []).map(x => ({ id: x.id, title: x.word || '', sub: x.explanation || '' })),
    open: 'openIdiom' },
};
async function crPickCard(kind) {
  // 群里也能发（group_send 本来就收 card）—— 认 crFid || crGid，别把小组挡在外面
  const meta = CARD_META[kind]; if (!meta || (!crFid && !crGid)) return;
  const box = $('#cr-picker');
  box.classList.remove('hidden');
  box.innerHTML = `<div class="cp-box"><div class="cp-head">选一条${esc(meta.name)}发给 ${esc(crName || '对方')}<button data-cpx>${artEm('✕')}</button></div>
    <div class="cp-list"><p class="empty">加载中…</p></div></div>`;
  try {
    const d = await api(meta.api);
    const items = meta.pick(d).filter(x => x.title).slice(0, 30);
    box.querySelector('.cp-list').innerHTML = items.length ? items.map(x =>
      `<button class="cp-item" data-cpick="${encodeURIComponent(JSON.stringify({ kind: kind, id: x.id, title: x.title.slice(0, 120), sub: (x.sub || '').slice(0, 60) }))}">
        <span class="t">${esc(x.title.slice(0, 60))}</span>${x.sub ? `<span class="s">${esc(x.sub.slice(0, 40))}</span>` : ''}
      </button>`).join('') : `<p class="empty">${esc(meta.name)}里还没有内容。</p>`;
  } catch (e) { box.querySelector('.cp-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#cr-picker').addEventListener('click', async e => {
  if (e.target.closest('[data-cpx]') || e.target.id === 'cr-picker') { $('#cr-picker').classList.add('hidden'); return; }
  const b = e.target.closest('[data-cpick]'); if (!b) return;
  $('#cr-picker').classList.add('hidden');
  const card = JSON.parse(decodeURIComponent(b.dataset.cpick));
  const box = $('#cr-msgs');
  const tid = 'tmp' + (++crTmpSeq);
  const e0 = box.querySelector('.empty'); if (e0) e0.remove();
  box.insertAdjacentHTML('beforeend', crMsgHtml({ mine: true, kind: 'card', card: card, tmp: tid, pending: true }));
  box.scrollTop = box.scrollHeight;
  const row = box.querySelector('[data-tmp="' + tid + '"]');
  try {
    const d = await api(crUrl(), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ card: card })
    });
    if (row) {
      row.removeAttribute('data-tmp');
      if (d.id) { row.dataset.mid = d.id; crLastId = Math.max(crLastId, d.id); }
      const bb = row.querySelector('.cr-bubble'); if (bb) bb.classList.remove('sending');
      const mt = row.querySelector('.cr-meta'); if (mt) mt.textContent = '✓ 已送达';
    }
    loadConvos();
  } catch (err) { toast(err.message, true); if (row) row.remove(); }
});
// 点卡片 → 跳到应用里那一条（跟自己点进去是同一条路）
$('#cr-msgs').addEventListener('click', e => {
  const c = e.target.closest('[data-card]'); if (!c) return;
  const meta = CARD_META[c.dataset.card]; if (!meta) return;
  const fn = window[meta.open];
  if (typeof fn !== 'function') { toast('打不开这个内容', true); return; }
  try { fn(); } catch (err) { console.error('[聊天卡片] 打开失败', err); toast('打开失败', true); }
});

/* ---- 表情面板：聊天和 AI 助手共用一个 ----
   原来那两颗 🙂 是 disabled 的占位。emoji 直接当字符插进 textarea 即可，
   不需要图片资源，系统字体自己会画。 */
const EMOJIS = ('😀😄😅😂🙂😉😊🥰😍😘🤗🤔🤨😐😴😪😥😭😤😡🥺😳🤯😱🥳😎🤓🧐🤝👍👎👌✌️🙏💪👏🎉✨🔥💯' +
  '❤️💔⭐🌟💡📌📎📖📚📝✏️🖊️📓📔🗒️📅⏰⌛✅❌⚠️❓❗🔍🎯🏆🥇📈📉🍀🌸🌈☀️🌙⛅🍚☕🍜🚀').match(/./gu) || [];
let emojiTarget = null;
function openEmojiPanel(btn, textareaSel) {
  const pan = $('#emoji-pan');
  emojiTarget = textareaSel;
  if (!pan.dataset.built) {
    pan.innerHTML = EMOJIS.map(e => `<button type="button" data-emo="${e}">${e}</button>`).join('');
    pan.dataset.built = '1';
  }
  pan.classList.remove('hidden');
  const r = btn.getBoundingClientRect(), w = pan.offsetWidth || 300, h = pan.offsetHeight || 230;
  pan.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + 'px';
  pan.style.top = Math.max(8, r.top - h - 8) + 'px';      // 弹在按钮上方，别被键盘顶掉
}
$('#emoji-pan').addEventListener('click', e => {
  const b = e.target.closest('[data-emo]'); if (!b || !emojiTarget) return;
  const ta = $(emojiTarget);
  const s = ta.selectionStart != null ? ta.selectionStart : ta.value.length;
  ta.value = ta.value.slice(0, s) + b.dataset.emo + ta.value.slice(ta.selectionEnd != null ? ta.selectionEnd : s);
  ta.focus();
  try { ta.selectionStart = ta.selectionEnd = s + b.dataset.emo.length; } catch (_) { /* 老 WebView 不给设光标就算了 */ }
  ta.dispatchEvent(new Event('input'));      // 触发自动增高 / 字数 / 草稿
});
document.addEventListener('click', e => {
  if (!e.target.closest('#emoji-pan') && !e.target.closest('.input-emoji')) $('#emoji-pan').classList.add('hidden');
});
document.querySelectorAll('#cr-input .input-emoji').forEach(b => {
  b.disabled = false; b.title = '表情';
  b.onclick = () => openEmojiPanel(b, '#cr-text');
});
document.querySelectorAll('.ai-input .input-emoji').forEach(b => {
  b.disabled = false; b.title = '表情';
  b.onclick = () => openEmojiPanel(b, '#ai-text');
});

/* ---- 搜聊天记录（消息 + 文件名，会话内和全局同一个框）---- */
let chSearchTimer = 0;
function chDoMsgSearch() {
  const q = $('#ch-msgsearch').value.trim();
  $('#ch-msgsearch-x').classList.toggle('hidden', !q);
  clearTimeout(chSearchTimer);
  if (!q) { $('#ch-searchres').classList.add('hidden'); $('#ch-convos').classList.remove('hidden'); return; }
  chSearchTimer = setTimeout(async () => {
    try {
      const d = await api('/api/chat/search?q=' + encodeURIComponent(q));
      $('#ch-convos').classList.add('hidden');
      const box = $('#ch-searchres');
      box.classList.remove('hidden');
      box.innerHTML = d.results.length ? d.results.map(r => `
        <div class="ch-sres" ${r.group ? `data-crg="${r.peer}"` : `data-crf="${r.peer}"`} data-crn="${esc(r.peer_name)}" data-jumpmid="${r.id}">
          <div class="ch-sh"><span>${esc(r.peer_name)}</span><span>${esc((r.time || '').slice(5, 16))}</span></div>
          <div class="ch-sb">${r.file ? '📄 ' : ''}${chMark(r.text, q)}</div>
        </div>`).join('') : '<p class="empty">没找到「' + esc(q) + '」。</p>';
    } catch (e) { $('#ch-searchres').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
  }, 220);      // 打字防抖：别每敲一个字就查一次
}
// 命中处加高亮。先转义再插标签，关键词本身也要转义后再找位置
function chMark(text, q) {
  const s = esc(text || ''), k = esc(q);
  const i = s.toLowerCase().indexOf(k.toLowerCase());
  if (i < 0) return s.slice(0, 80);
  const from = Math.max(0, i - 20);
  return (from ? '…' : '') + s.slice(from, i) + '<mark>' + s.slice(i, i + k.length) + '</mark>' + s.slice(i + k.length, i + k.length + 50);
}
$('#ch-msgsearch').addEventListener('input', chDoMsgSearch);
$('#ch-msgsearch-x').onclick = () => { $('#ch-msgsearch').value = ''; chDoMsgSearch(); };
$('#ch-searchres').addEventListener('click', e => {
  const it = e.target.closest('[data-crf],[data-crg]'); if (!it) return;
  if (it.dataset.crg) openGroup(+it.dataset.crg, it.dataset.crn);
  else openChatroom(+it.dataset.crf, it.dataset.crn);
  // 结果多半在更早的历史里：连着往上翻几页去够它，够不到就提示
  const want = +it.dataset.jumpmid;
  let tries = 0;
  const seek = () => {
    if ($('#cr-msgs').querySelector('[data-mid="' + want + '"]')) { crJumpTo(want); return; }
    if (++tries > 8 || !crHasMore) { toast('这条消息比较早，已加载到能找到的位置'); return; }
    crLoadMore().then(() => setTimeout(seek, 60));
  };
  setTimeout(seek, 400);
});

/* ---- 草稿：打了一半切走，回来还在（按会话分开存）---- */
function crDraftKey(k) { return 'crDraft:' + k; }
// 当前会话的标识：群是 g<id>，一对一是好友 id
function crKey() { return crGid ? ('g' + crGid) : String(crFid || ''); }
function crSaveDraft() {
  if (!crFid && !crGid) return;
  const v = $('#cr-text').value;
  if (v.trim()) lsSet(crDraftKey(crKey()), v); else lsDel(crDraftKey(crKey()));
}
function crLoadDraft(k) {
  const v = lsGet(crDraftKey(k)) || '';
  $('#cr-text').value = v; crGrow(); crCount();
}
// 字数：接近上限才出现，超了变橙。后端到 CHAT_MAX 会直接报错，不再悄悄切一半。
function crCount() {
  const el = $('#cr-count'); if (!el) return;
  const n = $('#cr-text').value.length;
  el.classList.toggle('hidden', n < CHAT_MAX * 0.8);
  el.classList.toggle('warn', n > CHAT_MAX);
  el.textContent = n + ' / ' + CHAT_MAX;
}
function crSendText() {
  const el = $('#cr-text'); const t = el.value.trim(); if (!t) return;
  if (t.length > CHAT_MAX) { toast('消息太长了（' + t.length + ' / ' + CHAT_MAX + ' 字），分两条发吧', true); return; }
  const rt = crReplyTo;
  el.value = ''; crGrow(); crCount(); lsDel(crDraftKey(crKey())); crClearReply();
  crSendOne(t, null, rt);
}
/* 乐观发送：按下就把气泡画出来，再去请求。
   原先是等 POST 回来、再等一次 crLoad 拉取，消息才落到屏幕上 —— 网络稍慢就是一两秒空白，
   用户以为没发出去又按一次。失败也不再把字塞回输入框，而是让那条消息留在原地标红，点一下重发。 */
async function crSendOne(t, retryRow, replyTo) {
  const box = $('#cr-msgs');
  const tid = 'tmp' + (++crTmpSeq);
  if (retryRow) { replyTo = replyTo || +retryRow.dataset.replyto || 0; retryRow.remove(); }
  const e0 = box.querySelector('.empty'); if (e0) e0.remove();
  const q = replyTo ? crQuotePreview(replyTo) : null;
  box.insertAdjacentHTML('beforeend', crMsgHtml({ mine: true, kind: 'text', body: t, tmp: tid, pending: true, quote: q }));
  box.scrollTop = box.scrollHeight;
  const row = box.querySelector('[data-tmp="' + tid + '"]');
  if (row && replyTo) row.dataset.replyto = replyTo;
  try {
    const d = await api(crUrl(), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body: t, reply_to: replyTo || 0 })
    });
    if (row) {
      row.removeAttribute('data-tmp');
      if (d.id) { row.dataset.mid = d.id; crLastId = Math.max(crLastId, d.id); }  // 认了 id，随后的增量拉取才不会再画一遍
      if (!crFirstId) crFirstId = d.id || 0;
      const b = row.querySelector('.cr-bubble'); if (b) b.classList.remove('sending');
      const mt = row.querySelector('.cr-meta'); if (mt) mt.textContent = '✓ 已送达';
    }
    loadConvos();      // 会话列表的摘要跟着更新（在双栏里看得见）
  } catch (e) {
    if (!row) { toast(e.message, true); return; }
    row.dataset.text = t;
    const b = row.querySelector('.cr-bubble'); if (b) { b.classList.remove('sending'); b.classList.add('failed'); }
    const mt = row.querySelector('.cr-meta');
    if (mt) mt.innerHTML = '<span class="cr-fail">✕ ' + esc(e.message || '发送失败') + ' · 点击重发</span>';
  }
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
    try { await api(crUrl(), { method: 'POST', body: fd }); } catch (err) { toast(f.name + '：' + err.message, true); }
  }
  crSending = false;
  crLoad(false);
}
// 拖文件进聊天窗口直接发（浏览器；桌面壳走 __onDropFiles）
(function () {
  const el = $('#chat-main'); if (!el) return;
  el.addEventListener('dragover', e => { if (!crFid && !crGid) return; e.preventDefault(); el.classList.add('cr-drop'); });
  el.addEventListener('dragleave', e => { if (!el.contains(e.relatedTarget)) el.classList.remove('cr-drop'); });
  el.addEventListener('drop', e => { e.preventDefault(); el.classList.remove('cr-drop'); if (!crFid && !crGid) return; const fs = [...(e.dataTransfer.files || [])]; if (fs.length) crSendFiles(fs); });
  /* 在聊天页 Ctrl+V 粘图/粘文件 → 发给正在聊的人（浏览器；桌面壳走 __onPasteImage）。
     以前这里什么都没接，粘贴会被侧栏的 AI 助手收走 —— 人明明在聊天窗里。 */
  document.addEventListener('paste', e => {
    if (e.defaultPrevented || (!crFid && !crGid)) return;
    if ((stack[stack.length - 1] || {}).view !== 'chat') return;
    if (e.target && e.target.closest && e.target.closest('#ai-panel, #qnote, .composer')) return;  // 焦点在别人的输入框里
    const fs = clipFiles(e);
    if (!fs.length) return;                  // 粘文字照常进输入框，不拦
    e.preventDefault();
    toast('正在发送…');
    crSendFiles(fs);
  });
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
  } catch (_) { /* 拉不到就先空着，15 秒后的轮询会补上 */ }
}
function onChatPush(d) {
  const fromId = (d && typeof d === 'object') ? d.from : d;   // 兼容旧格式（只有 id）
  const gid = (d && typeof d === 'object') ? (d.group || 0) : 0;
  const v = (stack[stack.length - 1] || {}).view;
  const viewing = crInRoom() && !document.hidden
    && (gid ? crGid === gid : (!crGid && crFid === fromId));
  if (viewing) { crLoad(false); if (v === 'chat') loadConvos(); return; }  // 正跟他聊且在前台 → 立刻拉
  refreshChatBadge();                                                    // 否则更新未读角标
  if (v === 'chat') loadConvos();                                        // 在聊天页（双栏）→ 刷新会话列表
  const isSelf = ME && fromId === ME.id && !gid;                         // 文件传输助手（自己其它设备）不弹通知
  if (!isSelf && d && typeof d === 'object' && !d.silent) notifyChat(fromId, d.name, d.preview, gid);
}
// 通知栏推送：APK 走原生通知，浏览器/桌面走 Web Notification。点开直达该会话。
function notifyChat(fromId, name, preview, gid) {
  const title = gid ? ('小组「' + (name || '') + '」有新消息') : ((name || '好友') + ' 发来消息');
  const body = preview || '你有一条新消息';
  const tag = gid ? ('chatgroup:' + gid) : ('chat:' + fromId);
  // APK：交给原生（会进系统通知栏、可后台弹出）
  try {
    if (window.GongkaoNative && typeof GongkaoNative.notify === 'function') {
      GongkaoNative.notify(title, body, tag);
      return;
    }
  } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }
  // 浏览器/桌面壳：只要不是正开着这个会话（onChatPush 已判过），就弹系统通知。
  // 不再要求页面隐藏——在别的功能页也该收到提示（像微信/QQ）。
  try {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    const n = new Notification(title, { body, tag: tag, icon: '/static/icon-192.png' });
    n.onclick = () => {
      try { window.focus(); } catch (_) { /* 浏览器不支持这个能力就算了，不是错 */ }
      if (gid) openGroup(gid, name || ''); else openChatroom(fromId, name || '');
      n.close();
    };
  } catch (_) { /* 浏览器不支持这个能力就算了，不是错 */ }
}
// 首次进入聊天时，礼貌地请求一次通知权限（拒绝也不再烦）
function ensureNotifyPerm() {
  try {
    if (window.GongkaoNative && typeof GongkaoNative.notify === 'function') {
      if (typeof GongkaoNative.requestNotifyPerm === 'function') GongkaoNative.requestNotifyPerm();
      return;
    }
    if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission();
  } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }
}
function onFriendPush() {
  refreshChatBadge();
  const v = (stack[stack.length - 1] || {}).view;
  if (v === 'chat') { if (chTab === 'add') loadAddFriend(); if (chTab === 'friends') loadFriends(); loadConvos(); }
}
