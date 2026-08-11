/* 组队互监：邀请搭档、共享待办、互相打勾确认
 *
 * 由 figures.js 拆出 —— 那个文件声明的职责是「资料分析的材料」，却另外装了
 * 每日测验的一半、每日任务、组队互监三摊东西。根子在拆 app.js 时照搬了它的旧区段
 * 边界，而那个边界本身就是错的（mods/dtest.py 的文件头写着同一句自白）。
 *
 * index.html 里的引入次序紧跟 figures.js，执行顺序与拆分前逐行一致。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, ME, api, appConfirm, artEm, composing, esc, toast */
let tkMembers = [], tkMeId = 0, tkItemsById = {};
/* 先看组队状态：没组队 → 组队 UI；已组队 → 队头 + 互监清单 */
async function loadShared() {
  $('#tk-team').innerHTML = '<p class="empty">加载中…</p>';
  $('#tk-board').classList.add('hidden');
  try {
    const t = await api('/api/team');
    tkMeId = t.me_id;
    if (!t.team) { renderTeamSetup(t); return; }
    renderTeamHeader(t);
    $('#tk-board').classList.remove('hidden');
    await loadSharedBoard();
  } catch (e) { $('#tk-team').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderTeamSetup(t) {
  const inc = (t.incoming || []).filter(r => r.kind === 'join').map(r => `
    <div class="tm-req"><span>📨 <b>${esc(shortName(r.from_name))}</b> 想和你组队互监</span>
      <span class="tm-acts"><button class="btn tiny primary" data-tmacc="${r.id}">接受</button>
      <button class="btn tiny" data-tmrej="${r.id}">拒绝</button></span></div>`).join('');
  const out = (t.outgoing || []).filter(r => r.kind === 'join').map(r => `
    <div class="tm-req"><span>⏳ 已向 <b>${esc(shortName(r.to_name))}</b> 发出组队申请，等对方接受</span>
      <button class="btn tiny" data-tmcancel="${r.id}">撤回</button></div>`).join('');
  $('#tk-team').innerHTML = `
    <div class="pd-intro">互监需要先和搭档组队：搜对方的账号发起邀请，对方接受即可互相监督。</div>
    <div class="tm-search"><input id="tm-q" placeholder="搜账号 / 用户名 / ID"><button class="btn primary" id="tm-search-btn">搜索</button></div>
    <div id="tm-results"></div>
    ${inc ? `<div class="tm-sec"><div class="tm-sec-t">收到的组队申请</div>${inc}</div>` : ''}
    ${out ? `<div class="tm-sec"><div class="tm-sec-t">我发出的申请</div>${out}</div>` : ''}`;
  $('#tm-search-btn').onclick = tmSearch;
  $('#tm-q').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') tmSearch(); });
}
function renderTeamHeader(t) {
  const p = t.team.partner;
  const disIn = (t.incoming || []).find(r => r.kind === 'disband');
  const disOut = (t.outgoing || []).find(r => r.kind === 'disband');
  let dis = '';
  if (disIn) dis = `<div class="tm-req tm-warn"><span>${artEm('⚠️')} <b>${esc(shortName(p ? p.name : '搭档'))}</b> 申请解散组队</span>
    <span class="tm-acts"><button class="btn tiny primary" data-tmacc="${disIn.id}">同意解散</button>
    <button class="btn tiny" data-tmrej="${disIn.id}">不同意</button></span></div>`;
  else if (disOut) dis = `<div class="tm-req"><span>⏳ 已申请解散，等对方同意</span>
    <button class="btn tiny" data-tmcancel="${disOut.id}">撤回</button></div>`;
  const st = t.study || { streak: 0, total: 0 };
  $('#tk-team').innerHTML = `
    <div class="tm-head"><span>${artEm('🤝')} 已与 <b>${esc(shortName(p ? p.name : '搭档'))}</b> 组队互监</span>
      ${disOut || disIn ? '' : '<button class="btn tiny" id="tm-disband">解散组队</button>'}</div>
    <div class="tm-streak">🔥 连续学习 <b>${st.streak}</b> 天 · 累计 <b>${st.total}</b> 天</div>
    ${dis}`;
  if ($('#tm-disband')) $('#tm-disband').onclick = tmDisband;
}
async function tmSearch() {
  const q = $('#tm-q').value.trim(); if (!q) return;
  $('#tm-results').innerHTML = '<p class="empty">搜索中…</p>';
  try {
    const d = await api('/api/team/search?q=' + encodeURIComponent(q));
    $('#tm-results').innerHTML = d.users.length ? d.users.map(u => `
      <div class="tm-res"><span>${esc(u.name)} <i class="tm-uid">ID ${u.id}</i></span>
        ${u.in_team ? '<span class="tm-busy">已组队</span>' : `<button class="btn tiny primary" data-tminvite="${u.id}">邀请组队</button>`}</div>`).join('')
      : '<p class="empty">没找到这个账号</p>';
  } catch (e) { $('#tm-results').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
async function tmDisband() {
  if (!(await appConfirm('向搭档发出解散组队申请？对方同意后才会解散。'))) return;
  try { await api('/api/team/disband', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); toast('已发出解散申请'); loadShared(); }
  catch (e) { toast(e.message, true); }
}
$('#tk-team').addEventListener('click', async e => {
  const inv = e.target.closest('[data-tminvite]');
  const acc = e.target.closest('[data-tmacc]');
  const rej = e.target.closest('[data-tmrej]');
  const can = e.target.closest('[data-tmcancel]');
  try {
    if (inv) { await api('/api/team/request', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to_uid: +inv.dataset.tminvite }) }); toast('已发出组队申请'); loadShared(); }
    else if (acc) { const r = await api('/api/team/request/' + acc.dataset.tmacc + '/accept', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); toast(r.disbanded ? '已解散组队' : '已组队 🤝'); loadShared(); }
    else if (rej) { await api('/api/team/request/' + rej.dataset.tmrej + '/reject', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); loadShared(); }
    else if (can) { await api('/api/team/request/' + can.dataset.tmcancel + '/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); loadShared(); }
  } catch (er) { toast(er.message, true); }
});
async function loadSharedBoard() {
  $('#tk-shared-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/shared_todos');
    tkMembers = d.members || [];
    tkMeId = d.me_id;
    // 表头：每位互监成员一列打勾位；自己那列标「我」，只能由搭档来勾
    $('#tk-shared-head').innerHTML = tkMembers.length
      ? `<span class="tk-hd-text">待办</span><span class="tk-hd-ms">` + tkMembers.map(m =>
        `<span class="tk-hd-m ${m.id === d.me_id ? 'me' : ''}" title="${esc(m.name)}">${m.id === d.me_id ? '我' : esc(initials(m.name))}</span>`).join('') + `</span>`
      : '';
    tkItemsById = {};
    $('#tk-shared-list').innerHTML = d.items.length
      ? d.items.map(it => { tkItemsById[it.id] = it; return renderSharedItem(it); }).join('')
      : '<p class="empty">还没有共享待办，加一条大家一起监督～</p>';
  } catch (e) { $('#tk-shared-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
// 渲染单条互监待办（打勾走乐观更新时，只重画这一条 → 不跳「加载中」、不回顶）
function renderSharedItem(it) {
  const ids = it.done_ids || [];
  const byMap = it.done_by_map || {};
  const boxes = tkMembers.map(m => {
    const on = ids.includes(m.id), mine = m.id === tkMeId;
    const tip = on ? `${m.name}（由 ${byMap[m.id] || '?'} 确认）`
      : (mine ? '自己不能勾自己，等搭档来确认' : `确认 ${m.name} 已完成`);
    return `<button class="tk-box ${on ? 'on' : ''} ${mine ? 'mine' : ''}"
      data-tsbox="${it.id}" data-tsuser="${m.id}" title="${esc(tip)}">${on ? '✓' : (mine ? '🔒' : '')}</button>`;
  }).join('');
  const who = tkMembers.filter(m => ids.includes(m.id))
    .map(m => `${shortName(m.name)}（${shortName(byMap[m.id] || '?')} 确认）`);
  const all = tkMembers.length && tkMembers.every(m => ids.includes(m.id));
  return `<div class="tk-item tk-multi ${all ? 'done' : ''}" data-ts="${it.id}">
    <span class="tk-text">${it.is_plan ? '<i class="ts-plan">' + artEm("📅") + ' 规划</i> ' : ''}${esc(it.text)}<span class="tk-who">${it.is_plan ? '来自 ' + esc(shortName(it.created_by)) + ' 的今日计划' : '发起 ' + esc(shortName(it.created_by))}${all ? ' · 🎉 双方都已确认' : (who.length ? ' · ✅ ' + esc(who.join('、')) : '')}</span></span>
    <span class="tk-boxes">${boxes}</span>
    ${it.is_plan ? '' : `<button class="tk-del" data-tsdel="${it.id}">${artEm('🗑')}</button>`}
  </div>`;
}
// 就地替换某一条（保持滚动位置：只换这一个节点，别整表重排）
function replaceSharedItem(tid) {
  const it = tkItemsById[tid];
  const old = $('#tk-shared-list').querySelector('.tk-item[data-ts="' + tid + '"]');
  if (!it || !old) return;
  const tmp = document.createElement('div');
  tmp.innerHTML = renderSharedItem(it);
  old.replaceWith(tmp.firstElementChild);
}
function shortName(n) { n = n || ''; n = n.split('@')[0]; return n.length > 6 ? n.slice(0, 5) + '…' : n; }
// 表头列宽只有一个勾选框那么宽，用 2 个字符当列名（完整名在 title 与成员面板里）
function initials(n) { n = (n || '').split('@')[0]; return n.slice(0, 4); }
$('#tk-shared-list').addEventListener('click', async e => {
  const del = e.target.closest('[data-tsdel]');
  if (del) { e.stopPropagation(); if (!(await appConfirm('删除这条共享待办？'))) return; try { await api('/api/shared_todos/' + del.dataset.tsdel, { method: 'DELETE' }); loadSharedBoard(); } catch (er) { toast(er.message, true); } return; }
  const box = e.target.closest('[data-tsbox]'); if (!box) return;
  const tid = box.dataset.tsbox, who = +box.dataset.tsuser;
  if (who === tkMeId) { toast('自己不能给自己打勾，等搭档来确认 🤝', true); return; }
  const it = tkItemsById[tid]; if (!it) return;
  const ids = it.done_ids || (it.done_ids = []);
  const snapIds = ids.slice(), snapBy = Object.assign({}, it.done_by_map);
  const myName = (ME && ME.username) || '我';
  // 乐观更新：立刻翻勾并只重画这一条，后台再发请求；失败/被拒就翻回来
  if (ids.includes(who)) it.done_ids = ids.filter(x => x !== who);
  else { it.done_ids = ids.concat(who); (it.done_by_map = it.done_by_map || {})[who] = myName; }
  replaceSharedItem(tid);
  try {
    const d = await api('/api/shared_todos/' + tid + '/toggle', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: who })
    });
    if (Array.isArray(d.done_ids)) {                 // 以服务器为准对齐这一条
      it.done_ids = d.done_ids;
      if (d.done && d.user_id === who) (it.done_by_map = it.done_by_map || {})[who] = myName;
      else if (!d.done) { it.done_by_map = it.done_by_map || {}; delete it.done_by_map[who]; }
      replaceSharedItem(tid);
    }
  } catch (er) {
    it.done_ids = snapIds; it.done_by_map = snapBy;
    replaceSharedItem(tid);
    toast(er.message, true);
  }
});
$('#tk-shared-add').onclick = async () => {
  const v = $('#tk-shared-in').value.trim(); if (!v) return;
  try { await api('/api/shared_todos', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: v }) }); $('#tk-shared-in').value = ''; loadSharedBoard(); } catch (e) { toast(e.message, true); }
};
$('#tk-shared-in').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') $('#tk-shared-add').click(); });
