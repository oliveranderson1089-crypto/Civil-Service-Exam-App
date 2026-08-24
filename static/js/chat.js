/* 聊天
 *
 * 由 app.js 按它自己的区段边界切出（原 L7412-7705）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, anchorMenu, api, appConfirm, appPrompt, artEm, back, c, canOpenFile, canReveal,
   clipFiles, composing,
   chunkUpload, compressImage, convoAvatar, convoLongPress, convoStick, deskOpenFile, dvIcon,
   DV_CHUNK_MIN, errMsg, esc, fSize,
   growAndSync, init, IS_DESKTOP, IS_MOBILE, lightbox, lsDel, lsGet, lsSet, mdToHtml, ME, openAI,
   revealPath,
   openViewerUrl, preview, push, SKIN, stack, state, toast, uiError, voiceAsrEnabled, voiceBubbleHtml,
   voiceInsert, voiceLive, voiceRecord, voiceSupported, voiceToggle, voiceToText, voiceWhyNot */

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
  crRenderAnnounce(''); crInfoClose(); $('#cr-checkin').classList.add('hidden');
}
// 当前是否正开着和某人的聊天窗（桌面：选了会话；移动端：栈顶带 room）
function crInRoom() {
  const st = stack[stack.length - 1] || {};
  if (st.view !== 'chat') return false;
  return IS_MOBILE ? !!st.room : (!!crFid || !!crGid);
}
/* 「消息 / 好友 / 加好友」三个平级标签收成一行标题 + ＋ 菜单：
   加好友是一年点几次的操作，凭什么常年占掉顶部三分之一（CD7）。
   chSwitch 保留（其它模块和测试都在调它），只是不再有标签栏这个外壳。 */
function chSwitch(t) {
  chTab = t;
  ['convos', 'friends', 'add'].forEach(x => $('#ch-' + x).classList.toggle('hidden', x !== t));
  $('#ch-searchbar').classList.toggle('hidden', t !== 'convos');
  const ttl = $('.ch-htitle');
  if (ttl) ttl.textContent = t === 'convos' ? '消息' : (t === 'friends' ? '好友' : '加好友');
  if (t === 'convos') loadConvos();
  else if (t === 'friends') loadFriends();
  else loadAddFriend();
}
$('#ch-add-btn').onclick = (e) => {
  const box = $('#ch-addmenu');
  box.innerHTML = `<div class="acm-list">
    <button data-cha="group">${artEm('👥')} 新建学习小组</button>
    <button data-cha="add">${artEm('＋')} 加好友</button>
    <button data-cha="friends">${artEm('📇')} 好友列表</button>
    <button data-cha="convos">${artEm('💬')} 回到消息</button></div>`;
  anchorMenu(box, e.currentTarget);
};
$('#ch-addmenu').addEventListener('click', e => {
  const b = e.target.closest('[data-cha]'); if (!b) return;
  $('#ch-addmenu').classList.add('hidden');
  if (b.dataset.cha === 'group') crNewGroup(); else chSwitch(b.dataset.cha);
});
$('#ch-searchbtn2').onclick = () => { $('#ch-msgsearch').focus(); };
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
    if (!d.conversations.length) { $('#ch-convos').innerHTML = '<p class="empty">还没有会话。点右上角 ' + artEm('＋') + ' 加好友或建个学习小组。</p>'; return; }
    $('#ch-convos').innerHTML = d.conversations.map(c => {
      const key = (c.group ? 'g' : 'u') + c.id;
      const draft = (lsGet('crDraft:' + (c.group ? 'g' + c.id : String(c.id))) || '').trim();
      const av = c.self ? convoAvatar('我', '', 'me') : convoAvatar(c.username, c.avatar, c.group ? 'group' : '');
      return `<div class="ch-convo${c.self ? ' ch-self' : ''}${c.pinned ? ' ch-pinned' : ''}"
        ${c.group ? `data-crg="${c.id}"` : `data-crf="${c.id}"`} data-crn="${esc(c.username)}"
        data-ckey="${key}" data-cpin="${c.pinned ? 1 : 0}" data-cmute="${c.muted ? 1 : 0}">
        ${av}
        <div class="ch-cmid">
          <div class="ch-cn"><span class="ch-cname">${esc(c.username)}</span>${c.group ? `<span class="ch-nmem">${c.n_mem}</span>` : ''}
            ${c.pinned ? '<span class="ch-flag">置顶</span>' : ''}${c.muted ? '<span class="ch-flag ch-mute">🔕</span>' : ''}</div>
          <div class="ch-cp">${c.at ? '<span class="ch-at">[有人@我]</span> ' : ''}${draft ? '<span class="ch-draft">[草稿]</span> ' : ''}${c.last_mine ? `<span class="ch-tick">${c.last_read ? artEm('✓') + artEm('✓') : artEm('✓')}</span> ` : ''}${esc(draft || c.preview || '')}</div></div>
        <div class="ch-cright"><div class="ch-ct">${esc((c.time || '').slice(5, 16))}</div>${c.unread ? `<span class="ch-un${c.muted ? ' ch-un-mute' : ''}">${c.unread}</span>` : ''}</div>
      </div>`;
    }).join('');
  } catch (e) { $('#ch-convos').innerHTML = uiError(e); }
}
$('#ch-convos').addEventListener('click', e => {
  const g = e.target.closest('[data-crg]');
  if (g) { openGroup(+g.dataset.crg, g.dataset.crn); return; }
  const c = e.target.closest('[data-crf]'); if (c) openChatroom(+c.dataset.crf, c.dataset.crn);
});
/* 置顶 / 免打扰：桌面右键，手机长按。开关落在服务端（chat_prefs），换设备也还在。 */
async function chRowMenu(row) {
  if (!row || row.classList.contains('ch-self')) return;
  const kind = row.dataset.crg ? 'g' : 'u';
  const id = +(row.dataset.crg || row.dataset.crf);
  const pinned = row.dataset.cpin === '1', muted = row.dataset.cmute === '1';
  const box = $('#ch-addmenu');
  box.innerHTML = `<div class="acm-list">
    <button data-chp="pin">${pinned ? '取消置顶' : artEm('📌') + ' 置顶'}</button>
    <button data-chp="mute">${muted ? '恢复提醒' : '🔕 消息免打扰'}</button></div>`;
  box._ctx = { kind, id, pinned, muted };
  anchorMenu(box, row);
}
$('#ch-addmenu').addEventListener('click', async e => {
  const b = e.target.closest('[data-chp]'); if (!b) return;
  const ctx = $('#ch-addmenu')._ctx; if (!ctx) return;
  $('#ch-addmenu').classList.add('hidden');
  const body = b.dataset.chp === 'pin' ? { pinned: !ctx.pinned } : { muted: !ctx.muted };
  try {
    await api('/api/chat/prefs', { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ kind: ctx.kind, id: ctx.id }, body)) });
    loadConvos();
  } catch (err) { toast(errMsg(err), true); }
});
$('#ch-convos').addEventListener('contextmenu', e => {
  const row = e.target.closest('.ch-convo'); if (!row) return;
  e.preventDefault(); chRowMenu(row);
});
convoLongPress($('#ch-convos'), '.ch-convo', chRowMenu);
/* 好友列表缓存。跨网络用（Cloudflare 隧道）时一次往返要 1~3 秒，本机同一个接口是 2.5 毫秒——
   差的全是路上。所以凡是「点一下才去拉好友」的地方，先用上次的结果把界面填出来，
   新数据回来再覆盖：慢的是网络，改不了；能改的是**别让人对着一个没反应的界面等**。 */
let chFriendsCache = null;
async function chGetFriends() {
  const d = await api('/api/friends', { timeoutMs: 15000 });
  chFriendsCache = d.friends || [];
  return chFriendsCache;
}
async function loadFriends() {
  $('#ch-friends').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/friends');
    chFriendsCache = d.friends || [];
    if (d.n_req) { $('#ch-reqbadge').textContent = d.n_req; $('#ch-reqbadge').classList.remove('hidden'); }
    else $('#ch-reqbadge').classList.add('hidden');
    if (!d.friends.length) { $('#ch-friends').innerHTML = '<p class="empty">还没有好友。点「' + artEm('＋') + ' 加好友」搜用户名或 ID 添加。</p>'; return; }
    $('#ch-friends').innerHTML = d.friends.map(f => `
      <div class="ch-frow" data-crf="${f.id}" data-crn="${esc(f.username)}">
        ${avHtml(f.avatar, f.username, 'ch-av')}
        <div class="ch-cn">${esc(f.username)}</div>
        <button class="ch-chat" data-crf="${f.id}" data-crn="${esc(f.username)}">聊天</button>
        <button class="ch-fdel" data-fdel="${f.id}" title="删除好友">${artEm('✕')}</button></div>`).join('');
  } catch (e) { $('#ch-friends').innerHTML = uiError(e); }
}
$('#ch-friends').addEventListener('click', async e => {
  const del = e.target.closest('[data-fdel]');
  if (del) { if (await appConfirm('删除这个好友？')) { try { await api('/api/friends/' + del.dataset.fdel, { method: 'DELETE' }); loadFriends(); } catch (err) { toast(errMsg(err), true); } } return; }
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
  } catch (e) { $('#ch-results').innerHTML = uiError(e); }
}
$('#ch-add').addEventListener('click', async e => {
  const add = e.target.closest('[data-add]');
  if (add) { try { const r = await api('/api/friends/request', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to: +add.dataset.add }) }); toast(r.friend ? '已成为好友' : '好友请求已发送'); chDoSearch(); } catch (err) { toast(errMsg(err), true); } return; }
  const req = e.target.closest('[data-req]');
  if (req) { try { await api('/api/friends/requests/' + req.dataset.req, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: req.dataset.ra }) }); loadAddFriend(); } catch (err) { toast(errMsg(err), true); } }
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
  crPaintPeer();
  $('#cr-peer').classList.remove('hidden');
  $('#cr-input').classList.remove('hidden');
  $('#cr-empty').classList.add('hidden');
  $('#cr-text').placeholder = '发消息…（@助手 让 AI 在群里答）';
  $('#cr-msgs').innerHTML = '<p class="empty">加载中…</p>';
  crLoad(true); crLoadCheckin();
  clearInterval(crPoll);
  crPoll = setInterval(() => { if (crInRoom()) crLoad(false); else clearInterval(crPoll); }, 10000);
}
/* 会话顶栏：头像 + 名字 + 一行副标题（群里是「N 人 · 今天几人打过卡」）。
   旧版手机端把整条 .cr-peer 隐藏了，名字改由全局顶栏显示 —— 人数、公告、搜索、
   信息入口跟着一起没了（CD1/CD2）。现在两端都留着。 */
function crPaintPeer(sub) {
  $('#cr-peerav').innerHTML = crGid ? convoAvatar(crName, '', 'group', 'sm')
    : convoAvatar(crName, crFriendAvatar, crFid === (ME && ME.id) ? 'me' : '', 'sm');
  $('#cr-peername').textContent = crName || '';
  const s = sub || (crGid ? (crMembers.length ? crMembers.length + ' 人' : '') : '');
  $('#cr-peersub').textContent = s;
  $('#cr-peersub').classList.toggle('hidden', !s);
}
/* 勾好友的那个框（新建小组 / 拉人进组共用）。

   **先开框，再拉数据**：以前是 `await /api/friends` 拿到列表才开框，隧道上就是
   「点了确定，一两秒什么都不动」——用户只会以为没点上，接着再点一次。
   有缓存就先把上次的名单填出来（秒开），新名单回来再覆盖；拉不到就在框里给「重试」，
   而不是弹一句 toast 然后框也不出现。 */
function crPickFriends(opt) {
  const box = $('#cr-picker');
  box.classList.remove('hidden');
  const draw = (rows, state) => {
    const list = rows === null
      ? (state === 'err'
        ? '<p class="cp-wait cp-err">读不到好友列表 <button type="button" id="cp-retry">重试</button></p>'
        : '<p class="cp-wait"><i class="cr-spin"></i> 正在读好友列表…</p>')
      : (rows.length
        ? rows.map(f => `<label class="cp-item cp-check"><input type="checkbox" value="${f.id}"> <span class="t">${esc(f.username)}</span></label>`).join('')
        : `<p class="cp-wait">${esc(opt.empty || '没有可选的好友')}</p>`);
    box.innerHTML = `<div class="cp-box"><div class="cp-head">${esc(opt.title)}<button data-cpx>${artEm('✕')}</button></div>
      <div class="cp-list">${list}</div>
      <div class="mem-add"><button id="cp-ok"${rows && rows.length ? '' : ' disabled'}>${esc(opt.okText)}</button></div></div>`;
    const ok = $('#cp-ok');
    if (ok) ok.onclick = () => {
      const ids = [...box.querySelectorAll('input:checked')].map(x => +x.value);
      box.classList.add('hidden');
      opt.onOk(ids);
    };
    const rt = $('#cp-retry');
    if (rt) rt.onclick = () => { draw(null); pull(); };
  };
  const filter = (fr) => (opt.filter ? fr.filter(opt.filter) : fr);
  /* 晚到的响应先确认窗口还在、框还开着：慢网络下（隧道 1~3 秒）用户完全可能
     等不及就关了框、甚至退出了页面，那时候再去摸 DOM 只会抛一条无源的错。 */
  const live = () => typeof document !== 'undefined' && !!(document && document.querySelector)
    && !box.classList.contains('hidden');
  const pull = () => chGetFriends()
    .then(fr => { if (live()) draw(filter(fr)); })
    .catch(() => { if (live()) draw(null, 'err'); });
  draw(chFriendsCache ? filter(chFriendsCache) : null);   // 立刻出框：有缓存就直接是名单
  pull();                                                 // 同时去拉最新的，回来覆盖
}
// 新建小组：从好友里勾人
async function crNewGroup() {
  const name = await appPrompt('新建学习小组', '小组名，如：省考冲刺小组');
  if (!name || !name.trim()) return;
  const nm = name.trim();
  crPickFriends({
    title: '拉谁进「' + nm + '」', okText: '创建小组', empty: '还没有好友，先去加一个',
    onOk: async (ids) => {
      toast('正在创建…');
      try {
        const d = await api('/api/chat/groups', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: nm, members: ids })
        });
        await loadConvos();
        openGroup(d.id, d.name);
      } catch (e) { toast(errMsg(e), true); }
    }
  });
}

// —— 打开某人的聊天窗（右栏）——
function openChatroom(fid, name) {
  crSaveDraft();                       // 先把上一个会话没发完的话存住（**必须在改 crGid 之前**：
  crGid = 0;                           //  草稿的 key 是按当前会话算的，先清了就存到别人头上了）
  crFid = fid; crName = name; crLastId = 0;
  crFriendAvatar = ''; crMeAvatar = SKIN.avatar || ''; crLastTime = '';
  crHasMore = false; crFirstId = 0; crReadUpto = 0;
  crClearReply(); crLoadDraft(crKey()); crRenderAnnounce(''); $('#cr-checkin').classList.add('hidden');
  if ((stack[stack.length - 1] || {}).view !== 'chat') push({ view: 'chat', title: '聊天' });
  if (IS_MOBILE) push({ view: 'chat', room: fid, title: name });   // 移动端压栈：back 能回列表
  const p2 = $('#chat-2pane'); if (p2) p2.classList.add('show-room');
  crPaintPeer();
  $('#cr-peer').classList.remove('hidden');
  $('#cr-input').classList.remove('hidden');
  $('#cr-empty').classList.add('hidden');
  $('#cr-text').placeholder = '发消息…（可拖文件进来）';
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
      crPaintPeer();
      const top = stack[stack.length - 1] || {};
      if (IS_MOBILE && top.room) { top.title = crName; $('#top-title').textContent = crName; }
    }
    if (crGid) {                    // 群：名字、公告、成员都随消息一起回来
      crMembers = d.members || crMembers;
      if (d.name) { crName = d.name; }
      crPaintPeer();
      crRenderAnnounce(d.announce);
    }
    const box = $('#cr-msgs');
    if (first) {
      box.innerHTML = '<div id="cr-more" class="cr-more"></div>';
      crLastTime = ''; crHasMore = !!d.has_more; crFirstId = 0; crReadUpto = 0;
      crStick().seen();
    }
    let fresh = 0;                 // 这一轮真正画上去的条数（去重后），给浮标上的数字用
    if (!d.messages.length && first) {
      // 群里顺带说一句 @助手 —— 不然没人知道 AI 能在群里答（功能藏着等于没有）
      box.insertAdjacentHTML('beforeend', '<p class="empty">还没有消息，发一条打个招呼吧 👋'
        + (crGid ? '<br><span class="cr-tiphint">打「@助手 …」可以让 AI 在群里当场回答，全组都看得见</span>' : '')
        + '</p>');
    }
    /* 未读分割线：首屏时按「我上次读到哪」插一条红线，滚动停在它那儿而不是最底（CD5）。
       水位：群看服务端给的 my_read（我读到哪条），一对一看每条上的 read（= 我读没读过它）。
       后端两处都是**先**把这一屏拼好、**再**把已读写库，所以首屏拿到的是进来之前的状态。
       曾经这里读的是 m.read_at_self —— 后端从来没有这个字段，取到的永远是 undefined，
       于是每条对方发的消息都算「未读」：红线钉死在首屏第一条上，每次进来都从一个月前开始。 */
    let unreadAt = 0;
    if (first) {
      const un = d.messages.filter(m => !m.mine && !m.recalled
        && (crGid ? (d.my_read !== undefined && m.id > d.my_read) : !m.read));
      if (un.length >= 2) unreadAt = un[0].id;
    }
    if (d.messages.length) { const e = box.querySelector('.empty'); if (e) e.remove(); }
    for (const m of d.messages) {
      // 乐观气泡已经把自己发的那条画出来了（发送成功时就地转实），增量拉取会再带回同一条 ——
      // 认 id 去重，否则自己发的消息会显示两遍。
      if (box.querySelector('[data-mid="' + m.id + '"]')) { crLastId = Math.max(crLastId, m.id); continue; }
      if (!m.mine) fresh++;        // 自己发的那条是乐观气泡转实，不算「新消息」
      crLastId = Math.max(crLastId, m.id);
      if (!crFirstId) crFirstId = m.id;
      if (unreadAt && m.id === unreadAt) box.insertAdjacentHTML('beforeend', '<div class="cr-unread" id="cr-unread">以下是未读消息</div>');
      if (crShouldSep(crLastTime, m.time)) box.insertAdjacentHTML('beforeend', `<div class="cr-time">${esc(crTimeLabel(m.time))}</div>`);
      crLastTime = m.time || crLastTime;
      box.insertAdjacentHTML('beforeend', crMsgHtml(m));
    }
    crApplyRead(d.read_upto);
    crApplyRecalled(d.recalled);
    // 正在下的文件：这一批重绘会把卡片刷回静态样子，把进度补画回去
    Object.keys(CR_DL).forEach(id => crDlPaint(+id));
    if (first) crRenderMore();
    if (d.messages.length) crStickBottom(box, first, fresh);
    crPaintAtJump();
    // 有未读线就停在线上（先滚到底再回到线，位置才准 —— 图片撑开高度是后来的事）
    const uel = first && $('#cr-unread');
    if (uel) setTimeout(() => uel.scrollIntoView({ block: 'center' }), 60);
  } catch (e) { if (first) $('#cr-msgs').innerHTML = uiError(e); }
  finally { crLoading = false; }
}
/* 滚动：走共用的滚动契约（js/convo.js）。
   原先这里是「来了新消息就跳底」，跟 AI 那边是同一个毛病 —— 你正翻着上周的记录，
   对方发一条，屏幕自己蹦到最新。现在只有贴着底时才跟，否则右下角出「↓ N 条新消息」。
   进房（strong）仍然强制到底，并且等这一屏的图各自加载完再补滚（图片是加载完才有高度的）。 */
function crStick() { return convoStick($('#cr-msgs'), $('#chat-main')); }
/* box 照旧从外面传进来（测试拿假容器测的就是这一条契约），不写死 #cr-msgs */
function crStickBottom(box, strong, n) {
  const st = convoStick(box || $('#cr-msgs'), $('#chat-main'));
  if (strong) st.toBottom(true);
  else st.follow(n || 1);
}
/* ---- 今天的打卡（CM2）----
   谁打了、我打没打、公告都在这一张条里。只有小组才有；一对一不出现。 */
let crCheckin = { total: 0, done: 0, me: false, list: [] };
async function crLoadCheckin() {
  const bar = $('#cr-checkin');
  if (!crGid) { crCheckin = { total: 0, done: 0, me: false, list: [] }; bar.classList.add('hidden'); return; }
  try {
    const d = await api('/api/chat/g/' + crGid + '/checkin');
    crCheckin = { total: d.total, done: (d.done || []).filter(x => x.done).length, me: d.me, list: d.done || [] };
    crPaintCheckin();
    crPaintPeer(crCheckin.total + ' 人' + (crCheckin.done ? ' · 今天 ' + crCheckin.done + ' 人打过卡' : ''));
  } catch (_) { bar.classList.add('hidden'); }   // 打卡拉不到不该挡住聊天本身
}
function crPaintCheckin() {
  const bar = $('#cr-checkin');
  if (!crGid || !crCheckin.total) { bar.classList.add('hidden'); return; }
  bar.classList.remove('hidden');
  bar.innerHTML = `<div class="cc-top"><b>今天的打卡</b><span>${crCheckin.done} / ${crCheckin.total} 已打</span></div>
    <div class="cc-row">
      ${crCheckin.list.map(m => m.done
    ? convoAvatar(m.username, m.avatar, '', 'sm')
    : `<span class="cv-av cv-sm cc-undone" title="${esc(m.username)} 还没打卡">?</span>`).join('')}
      <button type="button" id="cc-do" class="cc-btn${crCheckin.me ? ' done' : ''}">${crCheckin.me ? '✅ 今天已打卡' : '✅ 打卡'}</button>
    </div>`;
}
$('#cr-checkin').addEventListener('click', async e => {
  if (!e.target.closest('#cc-do') || crCheckin.me) return;
  try {
    const d = await api('/api/chat/g/' + crGid + '/checkin', { method: 'POST' });
    crCheckin = { total: d.total, done: (d.done || []).filter(x => x.done).length, me: d.me, list: d.done || [] };
    crPaintCheckin(); toast('打卡成功，继续保持');
  } catch (err) { toast(errMsg(err), true); }
});
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
  } catch (e) { toast(errMsg(e), true); crRenderMore(); }
  crLoadingMore = false;
}
$('#cr-msgs').addEventListener('click', e => {
  if (!$('#cr-sheet').classList.contains('hidden')) crSheetClose();   // 点消息区＝收起面板
  if (e.target.closest('#cr-morebtn')) { crLoadMore(); return; }
  if (crSel) {                       // 多选态：点一条就是勾/取消，不触发打开卡片那些
    const row = e.target.closest('.cr-row[data-mid]');
    if (row) {
      e.preventDefault(); e.stopPropagation();
      const id = +row.dataset.mid;
      if (crSel.has(id)) crSel.delete(id); else crSel.add(id);
      crSelPaint();
    }
  }
}, true);
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
  } else if (m.kind === 'ai') {
    /* AI 在群里答的那条（后端 kind='ai'、from_uid=0）。走完整 Markdown 渲染 ——
       它的答案本来就带列表和加粗，用聊天那套「只认三样」的轻量渲染会糊成一坨。 */
    inner = `<div class="cr-ai">${mdToHtml(m.body || '')}</div>`;
  } else if (m.kind === 'voice') inner = voiceBubbleHtml(m);
  else if (m.kind === 'image') inner = `<img class="cr-img" src="/api/chat/file/${m.file_id}?thumb=1" data-lbimg="/api/chat/file/${m.file_id}?inline=1">`;
  else if (m.kind === 'file') inner = crFileCard(m.file_id, m.file_name, m.file_size, m.file_view);
  else inner = crText(m.body);
  if (m.quote) {
    inner = `<div class="cr-quote" data-jump="${m.quote.id}"><b>${esc(m.quote.who)}</b>：${esc(m.quote.text)}</div>` + inner;
  }
  const isAi = m.kind === 'ai';
  const av = isAi ? convoAvatar('AI', '', 'ai', 'sm')
    : convoAvatar(m.mine ? '我' : (crGid ? (m.who || '?') : crName),
      m.mine ? crMeAvatar : crFriendAvatar, m.mine ? 'me' : '', 'sm');
  // 群里必须看得出是谁说的（一对一就没必要，两个人还署名很啰嗦）
  const who = isAi ? '<div class="cr-who cr-whoai">AI 助手</div>'
    : ((crGid && !m.mine && m.who) ? `<div class="cr-who">${esc(m.who)}</div>` : '');
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
$('#cr-msgs').addEventListener('click', e => {
  const im = e.target.closest('[data-lbimg]'); if (im) { lightbox(im.dataset.lbimg); return; }
  const fb = e.target.closest('[data-cfile]');
  if (fb) { e.preventDefault(); crFileTap(fb, !!e.target.closest('.cr-fact')); }
});

/* ================= 聊天里的文件：预览 / 下载 / 转存 =================
   原来这里只有一个 <a download>：点下去只有一种结果（下载），
   没有「要预览还是要下载」的问询，也没有任何进度反馈 —— 安卓交给系统下载器，
   进度只在通知栏，应用里一点动静没有，于是人就反复点、反复下同一份。
   现在点击一律被拦下来，由下面这套接管；应用内预览直接复用资料库/云盘那个查看器
   （openViewerUrl 自己会往导航栈压一层，所以返回一次就是回到聊天窗，不多退一级）。 */
const CR_IMG_EXT = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'heic', 'avif', 'svg'];
const CR_DL = {};        // file_id → { state:'run'|'done'|'fail', pct, got, total, … }

/* 「这份文件已经在本机了」得单独记一份、并且要活过这次会话。
   CR_DL 记的是**这一趟**的进度，crDlLater 一分钟后就把它清掉（卡片要变回原样）——
   于是下完一分钟，右边那个「打开」就再也回不来，想打开只能重下一遍；
   网页端和桌面端更早一步：它们那条下载路根本没记路径，「打开」从来没出现过。 */
const CR_HAVE_KEY = 'chatDlHave';
const CR_HAVE_MAX = 80;      // localStorage 只有 5 MiB，这张表不设上限就是慢性泄漏
function crHaveAll() {
  try { return JSON.parse(lsGet(CR_HAVE_KEY) || '{}') || {}; } catch (_) { return {}; }
}
// path 是本机路径（安卓是 content:// Uri，桌面是绝对路径）；浏览器给不出路径，只标 web
function crHave(id) {
  const r = crHaveAll()[id];
  return r && (r.path || r.web) ? r : null;
}
function crHaveSet(id, path, where) {
  const all = crHaveAll();
  all[id] = { path: path || '', web: path ? 0 : 1, where: where || '', at: Date.now() };
  Object.keys(all).sort((a, b) => (all[b].at || 0) - (all[a].at || 0))
    .slice(CR_HAVE_MAX).forEach(k => delete all[k]);
  lsSet(CR_HAVE_KEY, JSON.stringify(all));
}

/* 卡片一画出来就要认账：本机已经有这一份的话，右边直接带上「打开」。
   （crDlPaint 只在下载过程中被调，翻页/重进会话重画的卡片不经过它） */
function crFileAct(id) {
  return crHave(id) ? '<span class="cr-fact">打开</span>' : '<span class="cr-fact hidden"></span>';
}
function crFileCard(id, name, size, viewable) {
  return `<button type="button" class="cr-file${crHave(id) ? ' dl-have' : ''}" data-cfile="${id}"
    data-cfn="${esc(name || '')}" data-cfsz="${size || 0}" data-cfv="${viewable ? 1 : 0}"
    data-cfem="${esc(fSize(size))}">
    <span class="cr-fic">${dvIcon((name || '').split('.').pop())}</span>
    <span class="cr-fmid"><span class="cr-fn">${esc(name || '文件')}</span>
      <em>${fSize(size)}</em><span class="cr-fbar hidden"><i></i></span></span>
    ${crFileAct(id)}</button>`;
}
function crFileOf(el) {
  return { id: +el.dataset.cfile, name: el.dataset.cfn || '文件', size: +el.dataset.cfsz || 0,
    view: el.dataset.cfv === '1', meta: el.dataset.cfmeta || '' };
}
/* 点这张卡：下载中→取消，失败→重试，刚下完→打开，其余→弹动作卡。
   hitAct＝点的是右边那枚小按钮（「打开」/「取消」/「重试」）而不是卡片本身：
   以前下过、这次只是路过的文件，点卡身还是该弹动作卡（预览/下载/转存都在那儿），
   只有点「打开」才是「就要本机那一份」。 */
function crFileTap(el, hitAct) {
  const f = crFileOf(el);
  const j = CR_DL[f.id];
  if (j && j.state === 'run') { crDlCancel(f.id); return; }
  if (j && j.state === 'fail') { crDownload(f); return; }
  if (j && j.state === 'done' && (j.path || j.web)) { crOpenLocal(f, j.path); return; }
  const have = crHave(f.id);
  if (have && hitAct) { crOpenLocal(f, have.path); return; }
  crFileSheet(f, have);
}
/* ---- 动作卡（不用系统原生弹窗，样式跟应用走） ---- */
function crFsClose() {
  const b = document.getElementById('cr-fsheet');
  if (b) { b.remove(); document.removeEventListener('keydown', crFsKey); }
}
function crFsKey(e) { if (e.key === 'Escape') crFsClose(); }
function crFileSheet(f, have) {
  crFsClose();
  const ext = (f.name || '').split('.').pop().toLowerCase();
  const box = document.createElement('div');
  box.id = 'cr-fsheet'; box.className = 'cr-fsheet';
  box.innerHTML = `<div class="cf-mask"></div>
    <div class="cf-card" role="dialog" aria-label="${esc(f.name)}">
      <div class="cf-f"><span class="cf-ic">${dvIcon(ext)}</span>
        <span class="cf-t"><b>${esc(f.name)}</b>
          <em>${fSize(f.size)}${f.meta ? ' · ' + esc(f.meta) : ''}</em></span></div>
      ${f.view
    ? `<button type="button" class="cf-b pri" data-cf="view"><span class="cf-k">${artEm('👁')}</span>在应用内预览</button>`
    : `<button type="button" class="cf-b off" disabled><span class="cf-k">${artEm('👁')}</span>${ext ? '.' + esc(ext) + ' ' : ''}这种格式看不了，下载后再打开</button>`}
      ${have ? `<button type="button" class="cf-b" data-cf="open"><span class="cf-k">${artEm('↘')}</span>${have.path ? '打开本机的这一份' : '在新标签打开'}<span class="cf-s">${esc(have.where || '之前下载过')}</span></button>` : ''}
      <button type="button" class="cf-b" data-cf="dl"><span class="cf-k">${artEm('⤓')}</span>${have ? '再下一次' : '下载到本机'}<span class="cf-s">下载文件夹</span></button>
      <button type="button" class="cf-b" data-cf="save"><span class="cf-k">${artEm('↗')}</span>转存到我的云盘</button>
      <button type="button" class="cf-b cancel" data-cf="x">取消</button>
    </div>`;
  document.body.appendChild(box);
  box.addEventListener('click', e => {
    if (e.target.closest('.cf-mask')) { crFsClose(); return; }
    const b = e.target.closest('[data-cf]'); if (!b) return;
    const a = b.dataset.cf;
    crFsClose();
    if (a === 'view') crPreview(f);
    else if (a === 'open') crOpenLocal(f, have ? have.path : '');
    else if (a === 'dl') crDownload(f);
    else if (a === 'save') crSaveToDrive(f);
  });
  document.addEventListener('keydown', crFsKey);
  const first = box.querySelector('.cf-b:not([disabled])');
  if (first) first.focus();
}
/* ---- 预览：图片走看图浮层，其余走查看器（pdf.js / 阅读模式 / 批注） ---- */
function crPreview(f) {
  const ext = (f.name || '').split('.').pop().toLowerCase();
  const url = '/api/chat/file/' + f.id;
  if (CR_IMG_EXT.includes(ext)) { lightbox(url + '?inline=1', f.name); return; }
  openViewerUrl(url + '?view=1', f.name || '文件', '.' + ext, url, url + '?text=1');
}
/* ---- 转存到自己的云盘（内容按 sha256 共用，不重复占盘） ---- */
async function crSaveToDrive(f) {
  try {
    const d = await api('/api/chat/file/' + f.id + '/save', { method: 'POST' });
    toast(d.existed ? ('云盘里已经有了：' + (d.folder || '根目录'))
      : ('已转存到云盘「' + (d.folder || '聊天文件') + '」'));
  } catch (err) { toast(errMsg(err), true); }
}
/* ---- 下载：进度画在这条消息自己的卡片上 ---- */
function crDlPaint(id) {
  const j = CR_DL[id];
  document.querySelectorAll('[data-cfile="' + id + '"]').forEach(el => {
    const em = el.querySelector('em');
    const bar = el.querySelector('.cr-fbar');
    const act = el.querySelector('.cr-fact');
    el.classList.remove('dl-run', 'dl-done', 'dl-fail');
    if (!j) {                                   // 这一趟没在下：回到静态样子
      if (em) em.textContent = el.dataset.cfem || '';
      if (bar) bar.classList.add('hidden');
      /* 但「本机已经有这一份」是**上一趟**留下的事实，卡片得一直认账：
         右边留一枚「打开」，点它直接开那份文件，不用再下一遍。 */
      const have = crHave(+el.dataset.cfile);
      el.classList.toggle('dl-have', !!have);
      if (act) {
        act.textContent = have ? '打开' : '';
        act.classList.toggle('hidden', !have);
      }
      return;
    }
    el.classList.remove('dl-have');
    el.classList.add('dl-' + j.state);
    if (em) {
      if (j.state === 'run') {
        em.textContent = j.total
          ? fSize(j.got) + ' / ' + fSize(j.total) + ' · ' + Math.max(0, j.pct) + '%'
          : '下载中… ' + fSize(j.got);
      } else if (j.state === 'done') em.textContent = '✓ ' + (j.where || '已保存');
      else em.textContent = j.msg || '下载失败';
    }
    if (bar) {
      bar.classList.toggle('hidden', j.state !== 'run');
      const i = bar.querySelector('i');
      // 拿不到总大小（没有 Content-Length）就画一条来回跑的条，别假装有百分比
      if (i) { i.style.width = j.pct >= 0 ? j.pct + '%' : '100%'; }
      bar.classList.toggle('indet', j.state === 'run' && j.pct < 0);
    }
    if (act) {
      const t = j.state === 'run' ? '取消'
        : (j.state === 'fail' ? '重试' : ((j.path || j.web) ? '打开' : ''));
      act.textContent = t;
      act.classList.toggle('hidden', !t);
    }
  });
}
function crDlCancel(id) {
  const j = CR_DL[id]; if (!j) return;
  if (j.abort) { j.abort(); return; }            // 走 fetch 的：abort 之后在 catch 里收尾
  if (j.native && window.GongkaoNative && GongkaoNative.cancelDownload) {
    try { GongkaoNative.cancelDownload(String(id)); } catch (_) { /* 老壳没这个方法 */ }
  }
  delete CR_DL[id]; crDlPaint(id); toast('已取消下载');
}
function crDlLater(id) {                          // 完成/失败的状态留一分钟，然后恢复原样
  setTimeout(() => {
    const j = CR_DL[id];
    if (j && j.state !== 'run') { delete CR_DL[id]; crDlPaint(id); }
  }, 60000);
}
function crBlobSave(blob, name) {
  const u = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = u; a.download = name || '';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(u), 60000);   // 壳里的下载器可能还在读，别急着撤
}
async function crDownload(f) {
  const id = f.id;
  if (CR_DL[id] && CR_DL[id].state === 'run') { toast('这个文件正在下载'); return; }
  const url = '/api/chat/file/' + id;
  /* 安卓：交给原生下载（和更新包同一套流式下载），进度回调到下面的 __chatDl*。
     没有这个桥的旧版 APK 会掉进下面 fetch 那条路 —— blob 存不下来，
     所以旧版继续走 <a download>（系统下载器接管，通知栏里有进度）。 */
  if (window.GongkaoNative && typeof GongkaoNative.downloadFile === 'function') {
    CR_DL[id] = { state: 'run', pct: -1, got: 0, total: f.size || 0, name: f.name, native: true };
    crDlPaint(id);
    try { GongkaoNative.downloadFile(location.origin + url, f.name || '', String(id)); }
    catch (err) {
      CR_DL[id] = { state: 'fail', msg: '下载没能开始：' + errMsg(err) };
      crDlPaint(id); crDlLater(id);
    }
    return;
  }
  if (window.GongkaoNative && !window.__desktop) {   // 旧版安卓壳：没有桥，退回系统下载器
    crBlobSaveFallback(url, f.name);
    return;
  }
  /* 桌面壳（Linux WebKit / Windows Electron）：交给壳自己的下载器。
     它下完会回调 __onDownloaded，带着**落盘的绝对路径** —— 那正是「打开」缺的东西；
     走下面 fetch+blob 那条路只拿得到一个 blob，路径无从谈起（这就是桌面端一直没有
     「打开」的原因）。代价是没有百分比，壳不回报进度，所以这里画的是来回跑的条。 */
  if (IS_DESKTOP) {
    CR_DL[id] = { state: 'run', pct: -1, got: 0, total: f.size || 0, name: f.name, desk: true };
    crDlPaint(id);
    crDeskWait = { id: id, name: f.name || '', at: Date.now() };
    crLinkSave(url, f.name);
    // 壳要是没回音（下载被取消、动作被丢弃），别让这张卡一直转下去
    clearTimeout(crDeskTimer);
    crDeskTimer = setTimeout(() => {
      if (CR_DL[id] && CR_DL[id].state === 'run' && CR_DL[id].desk) {
        CR_DL[id] = { state: 'fail', msg: '没等到下载结果，点这里重试' };
        crDlPaint(id);
      }
    }, 180000);
    return;
  }
  const ctl = ('AbortController' in window) ? new AbortController() : null;
  CR_DL[id] = { state: 'run', pct: 0, got: 0, total: f.size || 0, name: f.name,
    abort: ctl ? () => ctl.abort() : null };
  crDlPaint(id);
  try {
    const r = await fetch(url, { credentials: 'same-origin', signal: ctl ? ctl.signal : undefined });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const total = +(r.headers.get('Content-Length') || 0) || f.size || 0;
    const rd = r.body && r.body.getReader ? r.body.getReader() : null;
    let blob;
    if (!rd) {                                   // 没有流式 API 的老 WebView：至少别崩，只是没百分比
      CR_DL[id].pct = -1; crDlPaint(id);
      blob = await r.blob();
    } else {
      const parts = []; let got = 0, last = 0;
      for (;;) {
        const st = await rd.read();
        if (st.done) break;
        parts.push(st.value); got += st.value.length;
        const now = Date.now();
        if (now - last >= 120) {                 // 刷太密只是白烧 CPU，看不出区别
          last = now;
          Object.assign(CR_DL[id], { got, total,
            pct: total ? Math.min(99, Math.floor(got * 100 / total)) : -1 });
          crDlPaint(id);
        }
      }
      blob = new Blob(parts, { type: r.headers.get('Content-Type') || 'application/octet-stream' });
    }
    crBlobSave(blob, f.name);
    CR_DL[id] = { state: 'done', where: '已保存到「下载」', web: 1 };
    crHaveSet(id, '', '已下载过');
    crDlPaint(id); crDlLater(id);
  } catch (err) {
    if (err && err.name === 'AbortError') { delete CR_DL[id]; crDlPaint(id); toast('已取消下载'); return; }
    CR_DL[id] = { state: 'fail', msg: '下载中断：' + errMsg(err) };
    crDlPaint(id); crDlLater(id);
  }
}
/* 隐藏的 <a download>：把这次下载交给壳/浏览器自己的下载器。
   ⚠️ 不许改 location.href —— 那是**导航**，单页应用当场被文件顶掉，
   再回来就是重新加载（人看到的是「返回怎么回首页了」）。 */
function crLinkSave(url, name) {
  const a = document.createElement('a');
  a.href = url; a.download = name || '';
  document.body.appendChild(a); a.click(); a.remove();
}
// 旧安卓壳兜底：系统下载器接管，进度只在通知栏
function crBlobSaveFallback(url, name) {
  crLinkSave(url, name);
  toast('已交给系统下载器，进度看通知栏');
}
let crDeskWait = null, crDeskTimer = 0;
/* 桌面壳下完只会喊一声 __onDownloaded(路径)，并不知道是谁点的下载（那个回调本来是
   给更新包和云盘用的）。这里认领：刚才确实是聊天卡片发起的、文件名也对得上，
   就归到那张卡上，由卡片显示「打开」，不再叠一个「下载完成」的框。 */
const crStem = (n) => String(n || '').replace(/\.[^.]*$/, '').replace(/\(\d+\)$/, '');
window.__chatDlAdopt = function (path) {
  const w = crDeskWait;
  if (!w || Date.now() - w.at > 10 * 60 * 1000) return false;
  const base = String(path || '').split(/[\\/]/).pop() || '';
  if (w.name && base && crStem(base) !== crStem(w.name)) return false;   // 不是这一份，交还给原来那条路
  crDeskWait = null; clearTimeout(crDeskTimer);
  CR_DL[w.id] = { state: 'done', where: '已保存到本机', path: path || '' };
  crHaveSet(w.id, path || '', '已保存到本机');
  crDlPaint(w.id); crDlLater(w.id);
  toast('已下载：' + base + '　点卡片右边的「打开」就能打开它');
  return true;
};
/* 打开本机那一份。三种壳三条路，都走不通时至少把人送到文件本身，别只留一句安慰话。
   ⚠️ 浏览器碰不到本机文件系统（下载去哪了它自己都不告诉网页），所以网页端的「打开」
   开的是**服务器上的那一份**，而且一定要新标签：在当前标签打开就等于把应用顶掉。 */
function crOpenLocal(f, path) {
  if (path && window.GongkaoNative && GongkaoNative.openDownload) {
    try { GongkaoNative.openDownload(path); return; } catch (_) { /* 老壳没这个方法 */ }
  }
  if (path && canOpenFile()) { deskOpenFile(path); return; }
  if (path && canReveal()) { revealPath(path); return; }      // 老一点的桌面壳：至少在文件管理器里选中它
  if (f && f.id) {
    window.open('/api/chat/file/' + f.id + '?inline=1', '_blank', 'noopener');
    toast('已在新标签打开；本机下载的那一份在「下载」文件夹里');
    return;
  }
  toast('文件在「下载」文件夹里');
}
/* 安卓原生下载的回调（三个都由壳在下载线程里调） */
window.__chatDl = function (tag, pct, got, total) {
  const id = +tag; const j = CR_DL[id]; if (!j) return;
  Object.assign(j, { state: 'run', pct: +pct, got: +got || 0, total: +total || j.total });
  crDlPaint(id);
};
window.__chatDlDone = function (tag, path) {
  const id = +tag;
  CR_DL[id] = { state: 'done', where: '已保存到「下载」', path: path || '' };
  if (path) crHaveSet(id, path, '已保存到「下载」');    // 一分钟后进度状态会清掉，这条得留着
  crDlPaint(id); crDlLater(id);
};
// 安卓 9 及以下没有 MediaStore.Downloads，壳把活儿交给了系统下载器
window.__chatDlSys = function (tag) {
  const id = +tag;
  CR_DL[id] = { state: 'done', where: '已交给系统下载器，进度看通知栏' };
  crDlPaint(id); crDlLater(id);
};
window.__chatDlFail = function (tag, msg) {
  const id = +tag;
  CR_DL[id] = { state: 'fail', msg: '下载失败：' + (msg || '未知原因') };
  crDlPaint(id); crDlLater(id);
};

/* ================= 「回来时还站在原地」 =================
   「下载完文件按返回，怎么回首页了？」——不是返回键的毛病：浏览器/壳把当前标签导航到了
   文件本身（下载后自动打开、或就地打开），整个单页应用被顶掉；再回来是**重新加载**，
   而导航栈只活在内存里，从头开始自然就是首页。
   整条栈没法复活（每一层的内容都是当时渲染出来的），但最要紧的那一层可以：人是在某个
   会话里看文件的，就把这个会话记进 sessionStorage（只活在这个标签页里），
   重新加载后若还新鲜（10 分钟内）就自动回到它。 */
const CR_RESUME_KEY = 'chatResume';
const CR_RESUME_TTL = 10 * 60 * 1000;
function crResumeClear() { try { sessionStorage.removeItem(CR_RESUME_KEY); } catch (_) { /* 隐私模式下 sessionStorage 本身会抛 */ } }
/* shell.js 的 render() 每次切视图调一次。
   看文件那一层（viewer）**不动记录** —— 那正是最容易被顶掉的地方，记录要留给它。 */
window.__chatResumeMark = function (view) {
  if (view === 'viewer') return;
  if (view === 'chat' && (crFid || crGid)) {
    try {
      sessionStorage.setItem(CR_RESUME_KEY,
                             JSON.stringify({ f: crFid, g: crGid, n: crName, at: Date.now() }));
    } catch (_) { /* 存不下就是没有这层兜底，不影响别的 */ }
    return;
  }
  crResumeClear();                    // 自己走回列表/首页的，就别再把人拽回会话里
};
// init() 画完首页后调一次
window.__chatResume = function () {
  let r = null;
  try { r = JSON.parse(sessionStorage.getItem(CR_RESUME_KEY) || 'null'); } catch (_) { r = null; }
  crResumeClear();
  if (!r || Date.now() - (r.at || 0) > CR_RESUME_TTL) return false;
  openChat();
  if (r.g) openGroup(r.g, r.n || '');
  else if (r.f) openChatroom(r.f, r.n || '');
  else return false;
  return true;
};

/* ---- 语音条：点一下放，再点停；进度画在气泡自己身上 ---- */
function crVoiceState(key, st, ratio) {
  const el = $('#cr-msgs').querySelector('.cr-voice[data-voice="' + key + '"]');
  if (!el) return;                                   // 翻页翻走了/被撤回了，忽略
  el.classList.toggle('playing', st === 'play' || st === 'progress');
  const bar = el.querySelector('.cr-vbar i');
  if (bar) bar.style.width = (st === 'stop' ? 0 : Math.round((ratio || 0) * 100)) + '%';
}
$('#cr-msgs').addEventListener('click', e => {
  const v = e.target.closest('.cr-voice'); if (!v) return;
  voiceToggle(v.dataset.voice, v.dataset.vurl, crVoiceState);
});
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
  const isVoice = !!row.querySelector('.cr-bubble.voice');
  const items = [];
  items.push('<button data-cm="quote">↩︎ 引用</button>');
  // 转过的不再给这一项：文字已经贴在气泡下面了，再点也是同一份
  if (isVoice && !row.querySelector('.cr-vtext')) items.push('<button data-cm="voicetext">📝 转文字</button>');
  if (isText) items.push('<button data-cm="copy">📋 复制</button>');
  items.push('<button data-cm="forward">➡ 转发</button>');
  if (isText && crGid) items.push('<button data-cm="askgroup">🤖 群里问助手</button>');
  if (isText) items.push('<button data-cm="askai">🤖 私下问 AI</button>');
  if (isText) items.push('<button data-cm="wrongq">📓 存进错题本</button>');
  items.push('<button data-cm="multi">☑ 多选</button>');
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
  } else if (b.dataset.cm === 'voicetext') {
    const bx = row.querySelector('.cr-voice');
    if (bx) bx.classList.add('busy');
    try {
      const d = await api('/api/chat/msg/' + mid + '/voicetext', { method: 'POST' });
      if (bx) bx.insertAdjacentHTML('afterend', '<div class="cr-vtext">' + esc(d.text || '') + '</div>');
    } catch (err) { toast(errMsg(err), true); }
    if (bx) bx.classList.remove('busy');
  } else if (b.dataset.cm === 'recall') {
    try {
      const d = await api('/api/chat/msg/' + mid, { method: 'DELETE' });
      row.outerHTML = crMsgHtml({ id: mid, mine: true, recalled: true, body: d.body || '' });
      loadConvos();
    } catch (err) { toast(errMsg(err), true); }
  } else if (b.dataset.cm === 'wrongq') {
    // 别人发来的题一键收进自己的错题本（复用错题本的新增接口）
    try {
      await api('/api/wrongq', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, board: '', qtype: '' })
      });
      toast('已存进错题本');
    } catch (err) { toast(errMsg(err), true); }
  } else if (b.dataset.cm === 'askgroup') {
    // 在群里问：把原文带上，AI 的答案会作为一条消息发回群里，所有人都看得见（F10）
    crMentionBot('关于这条：「' + text.slice(0, 120) + '」');
  } else if (b.dataset.cm === 'askai') {
    // 私下问：跳到助手面板，答案只有自己看得到
    openAI('帮我讲讲这条：\n\n' + text);
  } else if (b.dataset.cm === 'forward') {
    crForward([mid]);
  } else if (b.dataset.cm === 'multi') {
    crSelStart(mid);
  }
});

/* ---- 转发 / 多选转发（F8）----
   多选时消息行左侧长出一个勾选框，底部一条操作栏；转发是「挑一个会话再发过去」。 */
let crSel = null;   // null=没在多选；Set=选中的 mid
function crSelStart(mid) {
  crSel = new Set(mid ? [mid] : []);
  $('#cr-msgs').classList.add('sel-on');
  crSelPaint();
}
function crSelEnd() {
  crSel = null;
  $('#cr-msgs').classList.remove('sel-on');
  $('#cr-msgs').querySelectorAll('.cr-row.picked').forEach(r => r.classList.remove('picked'));
  $('#cr-selbar').classList.add('hidden');
}
function crSelPaint() {
  if (!crSel) return;
  $('#cr-msgs').querySelectorAll('.cr-row[data-mid]').forEach(r =>
    r.classList.toggle('picked', crSel.has(+r.dataset.mid)));
  const bar = $('#cr-selbar');
  bar.classList.remove('hidden');
  bar.innerHTML = `<span>已选 ${crSel.size} 条</span>
    <button type="button" data-sel="forward" ${crSel.size ? '' : 'disabled'}>➡ 转发</button>
    <button type="button" data-sel="copy" ${crSel.size ? '' : 'disabled'}>📋 复制</button>
    <button type="button" data-sel="cancel">取消</button>`;
}
$('#cr-selbar').addEventListener('click', async e => {
  const b = e.target.closest('[data-sel]'); if (!b || !crSel) return;
  const ids = [...crSel];
  if (b.dataset.sel === 'cancel') { crSelEnd(); return; }
  if (b.dataset.sel === 'copy') {
    const txt = ids.map(id => {
      const r = $('#cr-msgs').querySelector('[data-mid="' + id + '"] .cr-bubble');
      return r ? r.innerText.trim() : '';
    }).filter(Boolean).join('\n');
    try { await navigator.clipboard.writeText(txt); toast('已复制 ' + ids.length + ' 条'); }
    catch (_) { toast('这个浏览器不让复制', true); }
    crSelEnd(); return;
  }
  crForward(ids); crSelEnd();
});
/* 转发：先挑会话，再把这几条的正文按原顺序发过去。
   合并成一条发，而不是一条条刷屏 —— 十几条聊天记录逐条推过去，对面收到的是一片轰炸。 */
async function crForward(ids) {
  // 同样是先开框再拉：会话列表也要走一次网络（隧道上 1~3 秒）
  const box = $('#cr-picker');
  box.classList.remove('hidden');
  box._fwd = ids;
  const head = `<div class="cp-head">转发到<button data-cpx>${artEm('✕')}</button></div>`;
  box.innerHTML = `<div class="cp-box">${head}<div class="cp-list"><p class="cp-wait"><i class="cr-spin"></i> 正在读会话列表…</p></div></div>`;
  try {
    const convos = (await api('/api/chat/conversations', { timeoutMs: 15000 })).conversations || [];
    if (box.classList.contains('hidden')) return;          // 等的时候用户已经关了
    box.querySelector('.cp-list').innerHTML = convos.map(c =>
      `<button class="cp-item" data-fwd="${c.group ? 'g' : 'u'}:${c.id}">
        <span class="t">${esc(c.username)}</span></button>`).join('');
  } catch (e) {
    const list = box.querySelector('.cp-list');
    if (list) list.innerHTML = '<p class="cp-wait cp-err">' + esc(e.message) + '</p>';
  }
}
$('#cr-picker').addEventListener('click', async e => {
  const b = e.target.closest('[data-fwd]'); if (!b) return;
  const ids = $('#cr-picker')._fwd || [];
  $('#cr-picker').classList.add('hidden');
  const txt = ids.map(id => {
    const r = $('#cr-msgs').querySelector('[data-mid="' + id + '"] .cr-bubble');
    return r ? r.innerText.trim() : '';
  }).filter(Boolean).join('\n');
  if (!txt) { toast('这几条没有可转发的正文', true); return; }
  const [kind, pid] = b.dataset.fwd.split(':');
  const url = kind === 'g' ? '/api/chat/g/' + pid : '/api/chat/' + pid;
  try {
    await api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body: '[转发的聊天记录]\n' + txt }) });
    toast('已转发');
  } catch (err) { toast(errMsg(err), true); }
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

/* ---- 会话信息栏（C1 的第三栏）----
   成员、公告、共享文件、图片、置顶/免打扰 —— 旧版这些全塞在标题栏的 ⋮ 菜单里（CD2）。
   桌面端它是常驻的一栏（窄屏自动收起，点 ⓘ 展开），手机端是盖满一屏的信息页。 */
function crInfoOpen() {
  $('#chat-info').classList.remove('hidden');
  $('#chat-2pane').classList.add('info-on');
  crOpenInfo();
}
function crInfoClose() {
  $('#chat-info').classList.add('hidden');
  $('#chat-2pane').classList.remove('info-on');
}
function crInfoToggle() {
  if ($('#chat-info').classList.contains('hidden')) crInfoOpen(); else crInfoClose();
}
function crInfoHead(title) {
  return `<div class="ci-head"><b>${esc(title)}</b><button type="button" id="ci-x" title="收起">✕</button></div>`;
}
/* 信息栏的「共享文件」和气泡里的文件卡走**同一条路**：点一下先问预览还是下载。
   原来这里是 <a target="_blank">，安卓 WebView 不开新窗口，同域链接就地导航 ——
   整个单页应用被文件本身顶掉，window.appBack 跟着没了，左滑只能退到后台，
   再进来就是重新加载 → 回首页。所以这里连 href 都不该有。 */
function crFileRow(f) {
  const meta = (f.who || '') + ' · ' + (f.time || '').slice(5, 16);
  return `<button type="button" class="ci-file" data-cfile="${f.id}"
    data-cfn="${esc(f.name || '')}" data-cfsz="${f.size || 0}" data-cfv="${f.view ? 1 : 0}"
    data-cfem="${esc(meta)}" data-cfmeta="${esc(meta)}">
    <span class="fi">${artEm('📄')}</span><span class="ci-fm"><b>${esc(f.name)}</b>
    <em>${esc(meta)}</em><span class="cr-fbar hidden"><i></i></span></span>
    ${crFileAct(f.id)}</button>`;
}
function crImgGrid(imgs) {
  if (!imgs || !imgs.length) return '<p class="ci-empty">还没有图片。</p>';
  // 格子里铺缩略图、点开才拿原图：一屏二十几张原图是几十 MB 的白等
  return '<div class="ci-imgs">' + imgs.map(i =>
    `<img src="${i.thumb || i.url}" data-lb="${i.url}" alt="">`).join('') + '</div>';
}
async function crOpenInfo() {
  if (!crGid && !crFid) return;
  const box = $('#chat-info');
  box.innerHTML = crInfoHead('会话信息') + '<p class="ci-empty">加载中…</p>';
  try {
    if (crGid) {
      const g = await api('/api/chat/groups/' + crGid);
      crMembers = g.members || [];
      crPaintPeer(crMembers.length + ' 人' + (crCheckin.done ? ' · 今天 ' + crCheckin.done + ' 人打过卡' : ''));
      box.innerHTML = crInfoHead(g.name) + `
        <div class="ci-grp"><div class="ci-lbl">成员 · ${g.members.length}</div>
          <div class="ci-mems">${g.members.map(m => `<div class="ci-mem" data-gm="${m.id}">
            ${convoAvatar(m.username, m.avatar, '', 'sm')}<span>${esc(m.username)}</span>
            ${m.owner ? '<i>群主</i>' : ''}
            ${(g.is_owner && !m.owner) ? `<button class="ci-kick" data-gkick="${m.id}" title="移出小组">✕</button>` : ''}
          </div>`).join('')}
          <button class="ci-mem ci-add" id="cr-ginvite">${convoAvatar('＋', '', '', 'sm')}<span>邀请</span></button></div></div>
        <div class="ci-grp"><div class="ci-lbl">公告</div>
          <p class="ci-ann">${esc(g.announce || '还没有群公告')}</p>
          ${g.is_owner ? '<div class="ci-edit"><button data-gedit="announce">改公告</button><button data-gedit="name">改组名</button></div>' : ''}</div>
        <div class="ci-grp"><div class="ci-lbl">共享文件 · ${g.files.length}</div>
          ${g.files.length ? g.files.map(crFileRow).join('') : '<p class="ci-empty">还没传过文件。</p>'}</div>
        <div class="ci-grp"><div class="ci-lbl">图片</div>${crImgGrid(g.images)}</div>
        ${crPrefRows(g.prefs)}
        <div class="ci-grp"><button class="ci-danger" id="cr-gleave">${g.is_owner ? '解散小组' : '退出小组'}</button></div>`;
      return;
    }
    const d = await api('/api/chat/info?id=' + crFid);
    box.innerHTML = crInfoHead(crName || '会话') + `
      <div class="ci-grp"><div class="ci-lbl">共享文件 · ${d.files.length}</div>
        ${d.files.length ? d.files.map(crFileRow).join('') : '<p class="ci-empty">还没有互发过文件。</p>'}</div>
      <div class="ci-grp"><div class="ci-lbl">图片</div>${crImgGrid(d.images)}</div>
      ${crPrefRows(d.prefs)}`;
  } catch (e) { box.innerHTML = crInfoHead('会话信息') + '<p class="ci-empty">' + esc(e.message) + '</p>'; }
}
function crPrefRows(p) {
  p = p || {};
  return `<div class="ci-grp">
    <label class="ci-sw"><span>置顶会话</span><input type="checkbox" data-pref="pinned"${p.pinned ? ' checked' : ''}><i></i></label>
    <label class="ci-sw"><span>消息免打扰</span><input type="checkbox" data-pref="muted"${p.muted ? ' checked' : ''}><i></i></label>
  </div>`;
}
$('#chat-info').addEventListener('change', async e => {
  const c = e.target.closest('[data-pref]'); if (!c) return;
  try {
    await api('/api/chat/prefs', { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: crGid ? 'g' : 'u', id: crGid || crFid, [c.dataset.pref]: c.checked }) });
    loadConvos();
  } catch (err) { toast(errMsg(err), true); c.checked = !c.checked; }
});
$('#chat-info').addEventListener('click', async e => {
  if (e.target.closest('#ci-x')) { crInfoClose(); return; }
  const img = e.target.closest('[data-lb]');
  if (img) { lightbox(img.dataset.lb); return; }
  const cf = e.target.closest('[data-cfile]');
  if (cf) { e.preventDefault(); crFileTap(cf, !!e.target.closest('.cr-fact')); return; }   // 和气泡里的文件同一条路
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
      crLoad(true); loadConvos(); crOpenInfo();
    } catch (err) { toast(errMsg(err), true); }
    return;
  }
  const kick = e.target.closest('[data-gkick]');
  if (kick) {
    if (!(await appConfirm('把这个成员移出小组？'))) return;
    try { await api('/api/chat/groups/' + crGid + '/members/' + kick.dataset.gkick, { method: 'DELETE' }); crOpenInfo(); }
    catch (err) { toast(errMsg(err), true); }
    return;
  }
  if (e.target.closest('#cr-gleave')) { crLeaveGroup(); return; }
  if (e.target.closest('#cr-ginvite')) { crInviteMembers(); return; }
});
/* 退组 / 拉人：信息栏那两颗按钮的实现（成员选择还是复用 #cr-picker 那个弹层） */
async function crLeaveGroup() {
  if (!(await appConfirm('确定要退出这个小组吗？'))) return;
  try {
    await api('/api/chat/groups/' + crGid + '/members/' + (ME ? ME.id : 0), { method: 'DELETE' });
    crInfoClose(); crShowEmpty(); if (IS_MOBILE) back();
    loadConvos();
  } catch (err) { toast(errMsg(err), true); }
}
function crInviteMembers() {
  const inside = new Set(crMembers.map(m => m.id));
  crPickFriends({
    title: '拉谁进来', okText: '加入小组', empty: '好友都已经在组里了',
    filter: (f) => !inside.has(f.id),
    onOk: async (ids) => {
      if (!ids.length) return;
      toast('正在拉人…');
      try {
        await api('/api/chat/groups/' + crGid + '/members', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ members: ids })
        });
        toast('已拉进来'); crLoad(true); crOpenInfo();
      } catch (err) { toast(errMsg(err), true); }
    }
  });
}
$('#cr-info').onclick = crInfoToggle;
/* 窄屏它是盖在聊天区上的浮层，Esc / 点旁边的聊天区都当关闭 —— 只留一个 ✕ 太窄了 */
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !$('#chat-info').classList.contains('hidden')) crInfoClose();
});
$('#cr-msgs').addEventListener('pointerdown', () => {
  const box = $('#chat-info');
  if (!box.classList.contains('hidden') && getComputedStyle(box).position !== 'static') crInfoClose();
});
$('#cr-searchbtn').onclick = () => { $('#ch-msgsearch').focus(); $('#ch-msgsearch').select(); };
/* 「@ 我」跳转（F9）：群里被点名那条往往已经被后面的消息顶上去了。
   按钮只在这一屏真有 @我 时才出现 —— 没有就不显示，不摆一颗按不动的（AD10 的教训）。 */
function crPaintAtJump() {
  const btn = $('#cr-atjump'); if (!btn) return;
  const hits = $('#cr-msgs').querySelectorAll('.cr-atme');
  btn.classList.toggle('hidden', !hits.length);
  btn._last = hits.length ? hits[hits.length - 1] : null;
}
$('#cr-atjump').onclick = () => {
  const el = $('#cr-atjump')._last; if (!el) return;
  const row = el.closest('.cr-row');
  (row || el).scrollIntoView({ block: 'center', behavior: 'smooth' });
  if (row) { row.classList.add('cr-hl'); setTimeout(() => row.classList.remove('cr-hl'), 1500); }
};

/* 手机端 ➕：页内的一块面板（和 AI 那边同一套），不跟输入法抢地方。 */
const CR_SHEET_ITEMS = [
  { ic: '🖼', name: '相册', go: () => { const f = $('#cr-file'); f.accept = 'image/*'; f.click(); } },
  { ic: '📄', name: '文件', go: () => { const f = $('#cr-file'); f.accept = ''; f.click(); } },
  { ic: '📓', name: '错题', go: () => crPickCard('wrongq') },
  { ic: '📖', name: '古诗文', go: () => crPickCard('classic') },
  { ic: '📁', name: '素材', go: () => crPickCard('sucai') },
  { ic: '🗒️', name: '小记', go: () => crPickCard('note') },
  { ic: '🤖', name: () => (crGid ? '群里问助手' : '问 AI'), go: () => crAskAi() },
  { ic: 'ⓘ', name: '会话信息', go: () => crInfoOpen() },
];
function crSheetOpen() {
  $('#cr-sheet-grid').innerHTML = CR_SHEET_ITEMS.map((it, i) =>
    `<button class="ai-g4" data-csh="${i}"><em>${artEm(it.ic)}</em>${esc(typeof it.name === 'function' ? it.name() : it.name)}</button>`).join('');
  $('#cr-sheet').classList.remove('hidden');
  $('#cr-plus').classList.add('on');      // ＋ 转 45° 变成 ✕：同一颗按钮既开又关
  crStick().follow(0);
}
function crSheetClose() {
  $('#cr-sheet').classList.add('hidden');
  $('#cr-plus').classList.remove('on');
}
$('#cr-plus').onclick = () => { if ($('#cr-sheet').classList.contains('hidden')) crSheetOpen(); else crSheetClose(); };
$('#cr-sheet').addEventListener('click', e => {
  const b = e.target.closest('[data-csh]'); if (!b) return;
  crSheetClose();
  const it = CR_SHEET_ITEMS[+b.dataset.csh]; if (it) it.go();
});
$('#cr-text').addEventListener('focus', crSheetClose);
/* 🤖：群里就是「在群里问助手」—— 往输入框插一个 @助手，答案发回群里，所有人都看得见；
   一对一没有「群里」可言，还是打开助手面板私下问。 */
function crAskAi() {
  if (crGid) { crMentionBot(); return; }
  const t = ($('#cr-text').value || '').trim();
  openAI(t ? t : '');            // 输入框里打了一半的问题直接带过去
}
function crMentionBot(prefix) {
  const ta = $('#cr-text');
  const cur = ta.value || '';
  if (!/^@助手\s/.test(cur)) ta.value = '@助手 ' + (prefix ? prefix + '\n' : '') + cur;
  else if (prefix) ta.value = '@助手 ' + prefix + '\n' + cur.replace(/^@助手\s*/, '');
  ta.focus();
  try { ta.selectionStart = ta.selectionEnd = ta.value.length; } catch (_) { /* 老 WebView 不给设光标 */ }
  crGrow();
}
$('#cr-askai').onclick = crAskAi;
/* 两颗麦克风，分工不同（都在输入区，别混）：
     #cr-mic2  输入行那颗（微信里语音键的位置）→ **发一条语音消息**
     #cr-voice 工具行那颗                      → 说话转文字填进输入框
   转文字优先用浏览器自带识别；没有（桌面壳 WebKit、安卓 WebView、Firefox）就退到
   服务端识别，两条都没有才把这颗藏起来 —— 摆一颗按不动的最差。
   发语音条不依赖识别引擎，只要这个环境能录音就一直在。 */
function crVoiceAvail() {
  const live = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  // 转文字这颗：有自带识别就一定能用；没有的话只要这个环境能录音就先留着，
  // 点下去才去问服务端开没开（开着直接录，没开给一句能照做的提示）
  const b = $('#cr-voice'); if (b) b.classList.toggle('no-speech', !(live || voiceSupported()));
  ['#cr-mic2', '#cr-vsend'].forEach(sel => {
    const m = $(sel); if (m) m.classList.toggle('no-speech', !voiceSupported());
  });
}
crVoiceAvail();
let crRec = null, crRecOn = false;
/* 录一段传服务端识别（没有浏览器自带识别时走这条），文字填进输入框、不自动发。
   转写要好几秒：这中间用户可能接着打字，也可能切去另一个会话 ——
   所以结果回来先认会话，再插到光标处，不能拿开录时的快照覆盖整个输入框
   （覆盖会吞掉刚打的字，还会打断输入法正在拼的字）。 */
async function crVoiceByServer() {
  const rec = await voiceRecord({ tip: '正在录音，说完点「完成」转成文字' });
  if (!rec) return;
  const el = $('#cr-text'), fid = crFid, gid = crGid;
  const b = $('#cr-voice'); if (b) b.classList.add('rec');   // 转写中：按钮上有动静，别再点一次
  try {
    const txt = await voiceToText(rec.blob, rec.ext);
    if (fid !== crFid || gid !== crGid) { toast('会话已经切走了，这段话没填进去', true); return; }
    if (!txt) { toast('没识别出内容'); return; }
    voiceInsert(el, txt);
  } catch (e) {
    toast(errMsg(e), true);
  } finally {
    if (b) b.classList.remove('rec');
    crGrow();
  }
}
async function crVoiceToggle() {
  const R = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!R) {
    if (voiceSupported() && await voiceAsrEnabled()) { crVoiceByServer(); return; }
    toast(voiceSupported() ? '语音转文字还没开启（管理员可在后台 → 语音识别 里配置）'
      : (voiceWhyNot() || '这个浏览器不支持语音输入'), true);
    return;
  }
  if (crRecOn) { try { crRec.stop(); } catch (_) { /* 已经停了 */ } return; }
  crRec = new R();
  crRec.lang = 'zh-CN'; crRec.interimResults = true; crRec.continuous = true;
  const live = voiceLive($('#cr-text'));   // 只改「自己写进去的那一段」，别重写整个框
  crRec.onresult = (ev) => {
    let txt = '';
    for (let i = 0; i < ev.results.length; i++) txt += ev.results[i][0].transcript;
    live.set(txt);
    crGrow();
  };
  crRec.onend = () => { crRecOn = false; crVoicePaint(); };
  crRec.onerror = (ev) => { crRecOn = false; crVoicePaint(); if (ev.error !== 'aborted') toast('没听清（' + ev.error + '）', true); };
  try { crRec.start(); crRecOn = true; crVoicePaint(); toast('在听了，说完再点一下'); }
  catch (_) { toast('麦克风没打开', true); }
}
function crVoicePaint() {
  const b = $('#cr-voice'); if (b) b.classList.toggle('rec', crRecOn);
}
$('#cr-voice').onclick = crVoiceToggle;
/* 发语音有两个入口：输入行那颗麦克风（手机端）和工具行的 🎙（电脑端 ——
   .input-mic 在桌面是 display:none，工具都在工具行） */
function crVoiceSend() {
  if (!crFid && !crGid) { toast('先选一个会话'); return; }
  voiceRecord({ tip: '正在录音，说完点「完成」发出去' }).then(rec => { if (rec) crSendVoice(rec); });
}
$('#cr-mic2').onclick = crVoiceSend;
$('#cr-mic2').title = '发语音（按一下开始，说完点完成）';
const crVs = $('#cr-vsend'); if (crVs) crVs.onclick = crVoiceSend;

/* ---- 内容卡片：把应用里的一条发给好友（这是这个聊天区别于微信的地方）----
   各功能的列表接口字段不一样，所以每种给一个「怎么拉、怎么取标题」的适配；
   点开时复用已有的 openXxx，跟自己在应用里点进去是同一条路。 */
// 每个接口的分页参数名都不一样（entries 是 page_size 且默认才 5 条，classics 固定 10 条一页），
// 所以这里逐个写清楚，别想当然套一个 limit。
const CARD_META = {
  /* AI 对话的分享。跟下面几种不一样：那几种是「应用里的一条」，点开直达我这边的数据；
     这一种是**对方复制给我的一份快照**，点开是只读地看 + 可以接着往下问。
     它没有 api/pick —— 分享是从 AI 面板那头发起的，不从聊天的 ＋ 里挑。
     withId：这类卡片的打开函数**要**卡片 id；其余几种的 open 函数签名各不相同
     （openNotes(board)、openSucai(kind)），无脑把 id 传过去会把它们弄坏。 */
  aishare: { ic: '💬', name: 'AI 对话', open: 'openAiShare', withId: true },
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
  } catch (e) { box.querySelector('.cp-list').innerHTML = uiError(e); }
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
  crStick().toBottom(false);
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
  } catch (err) { toast(errMsg(err), true); if (row) row.remove(); }
});
// 点卡片 → 跳到应用里那一条（跟自己点进去是同一条路）
$('#cr-msgs').addEventListener('click', e => {
  const c = e.target.closest('[data-card]'); if (!c) return;
  const meta = CARD_META[c.dataset.card]; if (!meta) return;
  const fn = window[meta.open];
  if (typeof fn !== 'function') { toast('打不开这个内容', true); return; }
  // 只有声明了 withId 的才收 id：openNotes(board) / openSucai(kind) 收的是别的东西
  try { fn(meta.withId ? (+c.dataset.cid || 0) : undefined); }
  catch (err) { console.error('[聊天卡片] 打开失败', err); toast('打开失败', true); }
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
    } catch (e) { $('#ch-searchres').innerHTML = uiError(e); }
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
  crStick().toBottom(false);
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
    if (!row) { toast(errMsg(e), true); return; }
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
    try {
      if (blob.size > DV_CHUNK_MIN) await crSendBig(blob, name);
      else {
        const fd = new FormData(); fd.append('file', blob, name);
        await api(crUrl(), { method: 'POST', body: fd });
      }
    } catch (err) { toast(f.name + '：' + errMsg(err), true); }
  }
  crSending = false;
  crLoad(false);
}
/* 大文件绕道云盘再发。

   聊天这条路是「一整个请求发完」：200MB 封顶，走隧道时 100MB 就断，中途掉线还得从头来。
   所以超过分片门槛的就先分片传进自己云盘的「聊天文件」，再让服务端把那一份发进当前
   会话 —— 上限跟云盘一样，断了能续传，自己云盘里也留着一份（群消息本来就引用发送方
   那一份，不额外占盘）。 */
async function crSendBig(blob, name) {
  const file = blob instanceof File ? blob : new File([blob], name, { type: blob.type || '' });
  let shown = -1;
  const row = await chunkUpload(file, { target: 'drive', folder: '聊天文件' }, n => {
    const pct = Math.floor(n / (file.size || 1) * 10) * 10;    // 每 10% 报一次，别刷屏
    if (pct > shown) { shown = pct; toast('正在发送 ' + name + '… ' + pct + '%'); }
  });
  await api('/api/drive/' + row.id + '/send', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(crGid ? { groups: [crGid] } : { users: [crFid] }) });
}

/* ---- 发语音 ----
   走的还是文件那条通道（multipart），只是多带 voice=1 和时长：后端据此把这条
   存成 kind='voice'，音频本身照样进云盘「聊天文件」，想转发想下载都还在。 */
async function crSendVoice(rec) {
  if (crSending) return;
  crSending = true;
  const fd = new FormData();
  fd.append('file', rec.blob, 'voice' + (rec.ext || '.webm'));
  fd.append('voice', '1');
  fd.append('dur', String(rec.dur || 0));
  if (crReplyTo) fd.append('reply_to', String(crReplyTo));
  try { await api(crUrl(), { method: 'POST', body: fd }); crClearReply(); }
  catch (err) { toast(errMsg(err), true); }
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
