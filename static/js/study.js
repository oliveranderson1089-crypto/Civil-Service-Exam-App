/* 古诗文速查 / AI 助手 / 全文搜索 / 错题本 / 板块基础知识点 / 顶栏
 *
 * 由 app.js 按它原有的区段边界切出（原 L2439-3311）。顺序即原顺序 —— index.html 里
 * 按同样次序引入，执行序与拆分前逐字节一致。
 *
 * 下面 /* global *​/ 是这个模块的依赖清单：它用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，这就是现成的 import 表。
 */
/* global $, IS_MOBILE, SECTIONS, aiBack, api, appConfirm,
   appPrompt, applyPush, avoidFab, back, c, composing,
   createDock, csBoard, csTopic, draft, esc, loadCsBoard,
   loadDraft, loadEntries, loadFeed, loadPartyDict, lsGet, lsSet,
   mdToHtml, openAccount, openAiChatMenu, openChangkao, openChangshi, openCkBoard,
   openDoc, openDocqa, openDraft, openDrafts, openEssay, openEssays,
   openGaikuo, openGongwen, openIdiom, openKb, openMaterials, openNews,
   openNewsItem, openNotebook, openNotes, openPartyDict, openPlanLog, openPolicyDoc,
   openPolicyDocs, openReview, openSection, openShenlun, openSucai, openTasks,
   openThBoard, openTheory, openViewer, openWorkDetail, openWorks, push,
   stack, state, tkSwitch, toast */

/* ================= 古诗文速查（唐诗宋词·四书五经） ================= */
const CLS_BADGE = { '唐诗': '#c0392b', '宋词': '#7b5ea7', '元曲': '#2c8c8c', '诗经': '#2f8060', '先秦': '#b08a1e', '汉魏六朝': '#8a6d3b', '明清': '#4a6785', '论语': '#1a6fb5', '孟子': '#1a6fb5', '大学': '#b08a1e', '中庸': '#b08a1e', '孙子兵法': '#9b2c22', '资治通鉴': '#5a4b8a', '增广贤文': '#2c7a5a' };
let clsState = { cat: '', q: '', star: false, page: 1, pages: 1 };
function openClassics() {
  clsState = { cat: '', q: '', star: false, page: 1, pages: 1 };
  $('#cls-input').value = '';
  push({ view: 'classics' });
  loadClsCats(); loadClassics(); loadClsDaily();
}
async function loadClsDaily() {
  try {
    const d = await api('/api/classics/daily');
    if (!d || d.error) { $('#cls-daily').classList.add('hidden'); return; }
    $('#cls-daily').innerHTML = `
      <div class="cd-daily-tag">📖 每日一诗 · 申论 + 常识</div>
      <div class="cd-daily-title" data-clsopen="${d.id}">${esc(d.title)}<span class="cd-daily-meta">${esc((d.dynasty || '') + ' · ' + (d.author || ''))}</span></div>
      <div class="cd-daily-line">${esc(d.first_line || '')}</div>
      ${d.apply ? `<div class="cd-daily-apply"><b>申论运用</b> ${esc(d.apply)}</div>` : ''}
      ${d.common ? `<div class="cd-daily-apply cd-daily-common"><b>常识考点</b> ${esc(d.common)}</div>` : ''}`;
    $('#cls-daily').classList.remove('hidden');
  } catch (_) { $('#cls-daily').classList.add('hidden'); }
}
async function loadClsCats() {
  try {
    const d = await api('/api/classics/categories');
    const total = (d.categories || []).reduce((a, c) => a + c.count, 0);
    $('#cls-cats').innerHTML =
      `<button class="chip active" data-cc="">全部${total ? ' ' + total : ''}</button>` +
      `<button class="chip" data-cc="__star">★ 收藏${d.star_count ? ' ' + d.star_count : ''}</button>` +
      d.categories.map(c => `<button class="chip" data-cc="${esc(c.name)}">${esc(c.name)} ${c.count}</button>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#cls-daily').addEventListener('click', e => {
  const t = e.target.closest('[data-clsopen]'); if (t) openClassicDetail(+t.dataset.clsopen);
});
$('#cls-cats').addEventListener('click', e => {
  const c = e.target.closest('[data-cc]'); if (!c) return;
  const v = c.dataset.cc;
  clsState.star = (v === '__star');
  clsState.cat = clsState.star ? '' : v;
  clsState.page = 1;
  document.querySelectorAll('#cls-cats .chip').forEach(x => x.classList.toggle('active', x.dataset.cc === v));
  loadClassics();
});
let clsTimer;
$('#cls-input').addEventListener('input', e => {
  clearTimeout(clsTimer);
  clsTimer = setTimeout(() => { clsState.q = e.target.value.trim(); clsState.page = 1; loadClassics(); }, 280);
});
async function loadClassics() {
  let url = '/api/classics?page=' + clsState.page;
  if (clsState.cat) url += '&category=' + encodeURIComponent(clsState.cat);
  if (clsState.q) url += '&q=' + encodeURIComponent(clsState.q);
  if (clsState.star) url += '&star=1';
  try {
    const d = await api(url);
    clsState.pages = d.pages;
    renderClassics(d.items, d.total);
  } catch (e) { toast(e.message, true); }
}
function renderClassics(items, total) {
  const box = $('#cls-list');
  if (!items.length) {
    box.innerHTML = '';
    $('#cls-empty').classList.remove('hidden');
    $('#cls-empty').textContent = clsState.star ? '还没有收藏，点诗文右上角 ☆ 收藏'
      : (clsState.q ? '没有匹配「' + clsState.q + '」的诗文' : '暂无内容');
    $('#cls-pager').classList.add('hidden');
    return;
  }
  $('#cls-empty').classList.add('hidden');
  box.innerHTML = items.map(it => {
    const lines = (it.content || '').split('\n').map(l => `<div class="cls-line">${esc(l)}</div>`).join('');
    const meta = [it.author, it.dynasty, it.sub].filter(Boolean).join(' · ');
    return `<div class="cls-item" data-id="${it.id}">
      <div class="cls-head">
        <span class="cls-badge" style="background:${CLS_BADGE[it.category] || '#888'}">${esc(it.category)}</span>
        <span class="cls-title">${esc(it.title || '')}</span>
        <button class="cls-star ${it.starred ? 'on' : ''}" data-star="${it.id}" title="收藏">${it.starred ? '★' : '☆'}</button>
      </div>
      <div class="cls-body">${lines}</div>
      ${meta ? `<div class="cls-meta">${esc(meta)}</div>` : ''}
    </div>`;
  }).join('');
  box._items = items;
  const pager = $('#cls-pager');
  if (clsState.pages <= 1) { pager.classList.add('hidden'); }
  else {
    pager.classList.remove('hidden');
    $('#cls-info').textContent = '第 ' + clsState.page + ' / ' + clsState.pages + ' 页 · 共 ' + total + ' 条';
    $('#cls-prev').disabled = clsState.page <= 1;
    $('#cls-next').disabled = clsState.page >= clsState.pages;
  }
}
$('#cls-list').addEventListener('click', async e => {
  const s = e.target.closest('[data-star]');
  if (s) {
    const id = s.dataset.star;
    const on = !s.classList.contains('on');
    try {
      await api('/api/classics/' + id + '/star', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: on }) });
      s.classList.toggle('on', on); s.textContent = on ? '★' : '☆';
      const it = ($('#cls-list')._items || []).find(x => x.id == id); if (it) it.starred = on;
      if (clsState.star && !on) loadClassics();   // 收藏页里取消收藏即移除
    } catch (err) { toast(err.message, true); }
    return;
  }
  const card = e.target.closest('.cls-item'); if (!card) return;
  openClassicDetail(+card.dataset.id);
});

/* ---- 古诗文详情：拼音 / 译文 / 赏析 / AI 讲解 ---- */
let cdData = null;
async function openClassicDetail(id) {
  push({ view: 'cdetail', title: '古诗文' });
  $('#cd-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/classics/' + id + '/detail');
    cdData = d;
    stack[stack.length - 1].title = d.title;
    $('#top-title').textContent = d.title;
    renderCDetail();
  } catch (e) { $('#cd-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderCDetail() {
  const d = cdData;
  const meta = [d.dynasty, d.author, d.sub].filter(Boolean).join(' · ');
  const body = d.lines.map((ln, i) => {
    if (!ln.trim()) return '';
    return `<div class="cd-line"><div class="cd-py">${esc(d.pinyin[i] || '')}</div><div class="cd-han">${esc(ln)}</div></div>`;
  }).join('');
  // AI 讲解一旦生成，即替换掉开源译文/赏析；未生成时才展示开源资源
  const hasAI = !!d.ai_explain;
  let res = '';
  if (!hasAI) {
    if (d.translation) res += `<div class="cd-sec"><div class="cd-sec-t">译文</div><div class="cd-sec-b">${esc(d.translation).replace(/\n/g, '<br>')}</div></div>`;
    if (d.appreciation) res += `<div class="cd-sec"><div class="cd-sec-t">赏析</div><div class="cd-sec-b">${esc(d.appreciation).replace(/\n/g, '<br>')}</div></div>`;
  }
  const aiBox = hasAI
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">AI 讲解</div><div class="cd-sec-b">${mdToHtml(d.ai_explain)}</div>
        <button class="btn cd-ai-regen" id="cd-ai-regen">重新生成</button></div>`
    : `<button class="btn primary cd-ai-btn" id="cd-ai-btn">🤖 AI 讲解${(d.translation || d.appreciation) ? '（生成后替换开源译文/赏析）' : ''}</button>`;
  $('#cd-wrap').innerHTML = `
    <div class="cd-head">
      <span class="cls-badge" style="background:${CLS_BADGE[d.category] || '#888'}">${esc(d.category)}</span>
      <h2 class="cd-title">${esc(d.title)}</h2>
      <button class="cls-star ${d.starred ? 'on' : ''}" id="cd-star">${d.starred ? '★' : '☆'}</button>
    </div>
    <div class="cd-meta">${esc(meta)}</div>
    <div class="cd-body">${body}</div>
    ${res || (hasAI ? '' : '<p class="cd-tip">这篇暂无现成译文，可点下面让 AI 讲解。</p>')}
    ${aiBox}`;
}
$('#cd-wrap').addEventListener('click', async e => {
  if (e.target.closest('#cd-star')) {
    const on = !cdData.starred;
    try { await api('/api/classics/' + cdData.id + '/star', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: on }) }); cdData.starred = on; renderCDetail(); } catch (err) { toast(err.message, true); }
    return;
  }
  const gen = e.target.closest('#cd-ai-btn') || e.target.closest('#cd-ai-regen');
  if (gen) {
    const regen = gen.id === 'cd-ai-regen';
    gen.disabled = true; gen.textContent = 'AI 生成中…（约十几秒）';
    try {
      const d = await api('/api/classics/' + cdData.id + '/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: regen }) });
      cdData.ai_explain = d.content; renderCDetail();
    } catch (err) { toast(err.message, true); gen.disabled = false; gen.textContent = '🤖 AI 讲解'; }
  }
});

/* ---- 导出 PDF ---- */
$('#cls-export').onclick = () => {
  const scopes = [['cur', '当前筛选']];
  scopes.push(['star', '仅收藏']);
  $('#clsx-scope').innerHTML = scopes.map(s => `<option value="${s[0]}">${s[1]}</option>`).join('');
  $('#clsx-modal').classList.remove('hidden');
};
$('#clsx-cancel').onclick = () => $('#clsx-modal').classList.add('hidden');
$('#clsx-modal').addEventListener('click', e => { if (e.target.id === 'clsx-modal') $('#clsx-modal').classList.add('hidden'); });
$('#clsx-go').onclick = () => {
  const scope = $('#clsx-scope').value;
  const p = new URLSearchParams();
  p.set('py', $('#clsx-py').checked ? 1 : 0);
  p.set('tr', $('#clsx-tr').checked ? 1 : 0);
  if (scope === 'star' || clsState.star) p.set('star', 1);
  if (scope !== 'star') { if (clsState.cat) p.set('category', clsState.cat); if (clsState.q) p.set('q', clsState.q); }
  $('#clsx-modal').classList.add('hidden'); toast('正在导出 PDF…');
  window.location.href = '/api/classics/export?' + p.toString();
};
$('#cls-prev').onclick = () => { if (clsState.page > 1) { clsState.page--; loadClassics(); window.scrollTo({ top: 0 }); } };
$('#cls-next').onclick = () => { if (clsState.page < clsState.pages) { clsState.page++; loadClassics(); window.scrollTo({ top: 0 }); } };

/* ================= AI 助手 ================= */
/* ---- 全局 AI 会话中心（仿 Claude：新对话 / 项目 / 最近） ---- */
let aiMsgs = [], aiBusy = false, aiChatId = null, aiProjectId = null;
const AI_FOLDER = '<svg class="ai-folder" viewBox="0 0 48 48"><rect x="2" y="2" width="44" height="44" rx="13" fill="#5b6cf0"/><path fill="#7d8cf8" opacity=".5" d="M2 15C2 7.8 7.8 2 15 2h18c7.2 0 13 5.8 13 13v2H2z"/><rect x="11" y="11" width="11.5" height="11.5" rx="3.5" fill="#fff"/><rect x="25.5" y="11" width="11.5" height="11.5" rx="3.5" fill="#fff" opacity=".82"/><rect x="11" y="25.5" width="11.5" height="11.5" rx="3.5" fill="#fff" opacity=".82"/><circle cx="31.2" cy="31.2" r="5.8" fill="#ffd66b"/></svg>';
function aiShow(v) {
  ['aiv-home', 'aiv-projects', 'aiv-project', 'aiv-chat'].forEach(id => $('#' + id).classList.add('hidden'));
  $('#aiv-' + v).classList.remove('hidden');
}
/* AI 面板也用通用停靠：默认半屏（电脑右半屏 / 手机下半屏），不再一点就整屏盖住 */
let aiDk = null;
function aiInitDock() {
  if (aiDk) return;
  $('#ai-shot').classList.toggle('hidden', !window.__desktopShot);   // 截图只有桌面版有
  aiDk = createDock($('#ai-panel'), 'aiDock', IS_MOBILE ? 'bottom' : 'right', null);
  document.querySelectorAll('#ai-panel .ai-dock').forEach(b =>
    b.addEventListener('pointerdown', (e) => aiDk.dockDrag(e)));
  document.querySelectorAll('#ai-panel .ai-full').forEach(b =>
    b.onclick = () => aiDk.toggleFull());
}
async function openAI(preset) {
  aiInitDock();
  $('#ai-panel').classList.remove('hidden');
  aiDk.apply(false);
  if (preset) { await aiNewChat(); $('#ai-text').value = preset; aiGrow(); return; }
  aiShow('home'); loadAiHome();
}
async function loadAiHome() {
  try {
    const d = await api('/api/aichat/home');
    $('#aih-pcount').textContent = d.projects.length || '';
    $('#aih-recents').innerHTML = d.chats.length ? d.chats.map(c => `
      <div class="aih-item" data-aichat="${c.id}">
        <div class="aih-it">${c.starred ? '⭐ ' : ''}${esc(c.title || '（新对话）')}</div>
        <div class="aih-im">${c.pname ? AI_FOLDER + ' ' + esc(c.pname) + ' · ' : ''}${esc((c.updated_at || '').slice(5, 16))}</div>
        <button class="aih-del" data-aimenu="${c.id}" data-atitle="${esc(c.title || '')}" data-aproj="${c.project_id || ''}" data-astar="${c.starred ? 1 : 0}">⋮</button>
      </div>`).join('') : '<p class="empty" style="padding:20px 0">还没有对话，点上面「＋ 新对话」开始。</p>';
    $('#ai-panel')._projects = d.projects;
    $('#ai-panel')._chats = d.chats;
  } catch (e) { toast(e.message, true); }
}
async function aiNewChat(projectId) {
  // 懒创建：先进界面，第一次发送消息时才真正建会话（不产生空记录）
  aiChatId = null; aiProjectId = projectId || null; aiMsgs = [];
  const ps = $('#ai-panel')._projects || [];
  const p = ps.find(x => x.id === aiProjectId);
  $('#aic-title').textContent = p ? ('📁 ' + p.name + ' · 新对话') : '新对话';
  aiShow('chat'); renderAI();
  setTimeout(() => $('#ai-text').focus(), 60);
}
async function aiOpenChat(id) {
  try {
    const d = await api('/api/aichat/chats/' + id);
    aiChatId = d.id; aiMsgs = d.msgs; aiProjectId = d.project_id;
    $('#aic-title').textContent = d.title || '对话';
    aiShow('chat'); renderAI();
  } catch (e) { toast(e.message, true); }
}
function renderAiProjects() {
  const ps = $('#ai-panel')._projects || [];
  $('#aip-list').innerHTML = (ps.length ? ps.map(p => `
    <div class="aih-item" data-aiproj="${p.id}">
      <div class="aih-it">${AI_FOLDER} ${esc(p.name)}</div>
      <div class="aih-im">${p.cnt} 个对话${p.instructions ? ' · 有自定义指令' : ''}</div>
      <button class="aih-del" data-aipdel="${p.id}">✕</button>
    </div>`).join('') : '<p class="empty" style="padding:20px 0">还没有项目。项目=一组对话+自定义指令（比如"申论批改"）。</p>')
    + '<p class="cd-tip" style="margin-top:14px">点项目名在该项目下开新对话，AI 会遵循项目指令。</p>';
}
let aiCurProject = null;
function openAiProject(pid) {
  const ps = $('#ai-panel')._projects || [];
  const p = ps.find(x => x.id === pid); if (!p) return;
  const chats = ($('#ai-panel')._chats || []).filter(c => c.project_id === pid);
  if (!chats.length) { aiNewChat(pid); return; }   // 空项目：直接开新对话
  aiCurProject = p;
  $('#aipd-title').textContent = p.name;
  $('#aipd-chats').innerHTML = chats.map(c => `
    <div class="aih-item" data-aichat="${c.id}">
      <div class="aih-it">${c.starred ? '⭐ ' : ''}${esc(c.title || '（新对话）')}</div>
      <div class="aih-im">${esc((c.updated_at || '').slice(5, 16))}</div>
      <button class="aih-del" data-aimenu="${c.id}" data-atitle="${esc(c.title || '')}" data-aproj="${c.project_id || ''}" data-astar="${c.starred ? 1 : 0}">⋮</button>
    </div>`).join('')
    + (p.instructions ? `<p class="cd-tip" style="margin-top:12px">📋 项目指令：${esc(p.instructions)}</p>` : '');
  aiShow('project');
}
$('#aipd-new').onclick = () => { if (aiCurProject) aiNewChat(aiCurProject.id); };
function renderAI() {
  $('#ai-msgs').innerHTML = (aiMsgs.length ? '' : '<div class="ai-msg assistant">我是你的公考 AI 助手 👋 讲知识点、出题、翻译古文、分析错题、聊备考都行。我还能看到你的收录/错题/复习数据。</div>')
    + aiMsgs.map(m =>
      `<div class="ai-msg ${m.role}">${m.role === 'assistant' ? mdToHtml(m.content) : esc(m.content)}</div>`).join('')
    + (aiBusy ? '<div class="ai-msg assistant ai-typing">思考中…</div>' : '');
  const box = $('#ai-msgs');
  // 等布局重排完再滚到底 —— 同步设 scrollTop 时 mdToHtml 的高度可能还没算好，
  // 会出现「回复只露一行、其余被输入框挡住」（就是那个「只显示问题」的错觉）。
  box.scrollTop = box.scrollHeight;
  requestAnimationFrame(() => { box.scrollTop = box.scrollHeight; });
  $('#ai-send').disabled = aiBusy;
}
let aiAtts = [];  // [{name, text}]
function renderAiAtts() {
  $('#ai-atts').innerHTML = aiAtts.map((a, i) =>
    `<span class="ai-att">📎 ${esc(a.name)} <button data-aiattdel="${i}">×</button></span>`).join('');
}
$('#ai-atts').addEventListener('click', e => {
  const b = e.target.closest('[data-aiattdel]'); if (!b) return;
  aiAtts.splice(+b.dataset.aiattdel, 1); renderAiAtts();
});
$('#ai-attach').onclick = () => $('#ai-attsheet').classList.remove('hidden');
$('#ai-attsheet').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]') || e.target.id === 'ai-attsheet') { $('#ai-attsheet').classList.add('hidden'); return; }
  const b = e.target.closest('[data-aiatt]'); if (!b) return;
  $('#ai-attsheet').classList.add('hidden');
  if (b.dataset.aiatt === 'photo') $('#ai-camfile').click();
  else if (b.dataset.aiatt === 'image') { $('#ai-attfile').accept = 'image/*'; $('#ai-attfile').click(); }
  else { $('#ai-attfile').accept = '.pdf,.doc,.docx,.txt,.md,.ppt,.pptx,.xls,.xlsx'; $('#ai-attfile').click(); }
});
async function aiHandleAttach(file) {
  if (!file) return;
  toast('正在读取附件…');
  const fd = new FormData(); fd.append('file', file);
  try {
    const d = await api('/api/ai/extract', { method: 'POST', body: fd });
    if (d.error) { toast(d.error, true); return; }
    aiAtts.push({ name: d.name || file.name, text: d.text }); renderAiAtts();
    toast('已附加，发送时 AI 会读取其内容');
  } catch (e) { toast(e.message, true); }
}
$('#ai-attfile').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; aiHandleAttach(f); });
$('#ai-camfile').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; aiHandleAttach(f); });

async function aiSend() {
  const t = $('#ai-text').value.trim();
  if ((!t && !aiAtts.length) || aiBusy) return;
  let payload = t, shown = t;
  if (aiAtts.length) {
    payload = aiAtts.map(a => '【附件：' + a.name + '】\n' + a.text).join('\n\n') + '\n\n' + (t || '请阅读以上附件内容并帮我分析/讲解。');
    shown = (t ? t + '\n' : '') + '📎 ' + aiAtts.map(a => a.name).join('、');
    aiAtts = []; renderAiAtts();
  }
  if (!aiChatId) {
    try {
      const d = await api('/api/aichat/chats', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: aiProjectId || null }) });
      aiChatId = d.id;
    } catch (e) { toast(e.message, true); return; }
  }
  aiMsgs.push({ role: 'user', content: shown });
  $('#ai-text').value = ''; aiGrow();
  aiBusy = true; renderAI();
  try {
    const d = await api('/api/aichat/chats/' + aiChatId + '/send', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: payload })
    });
    aiMsgs.push({ role: 'assistant', content: d.reply || '（空回复）' });
    if (d.title) $('#aic-title').textContent = d.title;
    aiBusy = false; renderAI();
    aiRunActions(d.actions);          // AI 真做了事（加收录 / 打开某功能）→ 前端跟着执行/刷新
    return;
  } catch (e) {
    aiMsgs.push({ role: 'assistant', content: '⚠️ ' + e.message });
  }
  aiBusy = false; renderAI();
}
// 执行 AI 工具产生的动作：收录类刷新对应列表，导航类打开功能页
function aiRunActions(actions) {
  if (!actions || !actions.length) return;
  // 收录了新词：如果正看着「成语词语积累」，刷新一下让新词立刻出现
  const v = (stack[stack.length - 1] || {}).view;
  if (v === 'idiom' && typeof loadEntries === 'function') loadEntries();
  for (const a of actions) {
    if (a.type === 'navigate' && a.fn && typeof window[a.fn] === 'function') {
      // 打开功能页前先收起 AI 面板（不然盖在上面看不到）
      $('#ai-panel').classList.add('hidden'); if (window.applyPush) applyPush(); if (window.avoidFab) avoidFab();
      try { window[a.fn](); } catch (_) {}
      toast('已为你打开「' + (a.label || '') + '」');
    } else if (a.type === 'refresh' && a.what === 'notes') {
      if (v === 'notes' && typeof loadFeed === 'function') loadFeed();   // 正看着小记就刷新
    } else if (a.type === 'refresh' && a.what === 'entries') {
      if (v === 'idiom' && typeof loadEntries === 'function') loadEntries();
      toast('已收录到「成语词语积累」');
    } else if (a.type === 'refresh' && a.what === 'wrongq') {
      if (v === 'wrongq' && typeof loadWrongq === 'function') loadWrongq();
      toast('已加入错题本 📓');
    }
  }
}
// 手机端不用拖高（_grow 未装），走回原来的自动增高（最高 120）；桌面端交给拖高逻辑
function aiGrow() { const t = $('#ai-text'); if (!t) return; if (t._grow) { t._grow(); return; } t.style.height = 'auto'; t.style.height = Math.min(120, t.scrollHeight) + 'px'; }
// 输入框可拖高（**仅桌面**）：顶边加一条把手，拖动改高度。最小约 3 行、最高半屏，记住上次高度。
// 内容多时自动增高（不低于拖拽设定的高度、不超过半屏）。聊天和 AI 助手共用。
function makeInputResizable(bar, ta, key) {
  if (!bar || !ta || bar.querySelector('.input-grip')) return;
  const MIN = 74;
  const maxH = () => Math.round(window.innerHeight * 0.5);   // 最高半屏
  const base = () => Math.max(MIN, Math.min(maxH(), parseInt(lsGet(key) || '', 10) || MIN));
  ta._grow = () => { ta.style.height = 'auto'; ta.style.height = Math.max(base(), Math.min(maxH(), ta.scrollHeight)) + 'px'; };
  ta.addEventListener('input', ta._grow);
  const grip = document.createElement('div');
  grip.className = 'input-grip'; grip.title = '拖动上边可调高输入框（最高半屏）';
  bar.appendChild(grip);
  let sy = 0, sh = 0, dragging = false;
  grip.addEventListener('pointerdown', e => {
    dragging = true; sy = e.clientY; sh = ta.getBoundingClientRect().height;
    try { grip.setPointerCapture(e.pointerId); } catch (_) {}
    document.body.classList.add('resizing-ns'); e.preventDefault();
  });
  grip.addEventListener('pointermove', e => {
    if (!dragging) return;
    const h = Math.max(MIN, Math.min(maxH(), Math.round(sh + (sy - e.clientY))));  // 往上拖=变高
    ta.style.height = h + 'px'; lsSet(key, h);
  });
  const end = e => { if (!dragging) return; dragging = false; document.body.classList.remove('resizing-ns'); try { grip.releasePointerCapture(e.pointerId); } catch (_) {} };
  grip.addEventListener('pointerup', end); grip.addEventListener('pointercancel', end);
  ta._grow();                          // 初始高度 = 上次拖到的高度（或最小）
}
// 只在**桌面**装拖高把手（手机端保持原来的紧凑自动增高，见 #4 反馈）
if (!IS_MOBILE) {
  makeInputResizable(document.querySelector('.ai-input'), $('#ai-text'), 'aiInputH');
  makeInputResizable($('#cr-input'), $('#cr-text'), 'crInputH');
}
$('#ai-send').onclick = aiSend;
/* AI 入口在悬浮工具球里（#fab-ai），见文件末尾的悬浮球逻辑 */
// AI 面板：从上方下滑关闭/返回上一层（替代点右上角✕）
(function () {
  const panel = $('#ai-panel'); if (!panel) return;
  let sy = 0, sx = 0, tracking = false;
  panel.addEventListener('touchstart', e => {
    if (e.touches.length !== 1) { tracking = false; return; }
    const y = e.touches[0].clientY;
    // 仅在顶部 140px 区域内（头部/新对话附近）起手，避免和列表滚动冲突
    tracking = y < 160;
    sy = y; sx = e.touches[0].clientX;
  }, { passive: true });
  panel.addEventListener('touchend', e => {
    if (!tracking) return; tracking = false;
    const t = e.changedTouches[0];
    const dy = t.clientY - sy, dx = Math.abs(t.clientX - sx);
    if (dy > 70 && dy > dx) {   // 明显下滑
      const cur = ['home', 'projects', 'project', 'chat'].find(v => !$('#aiv-' + v).classList.contains('hidden'));
      if (cur === 'home' || !cur) { $('#ai-panel').classList.add('hidden'); applyPush(); avoidFab(); }
      else if (cur === 'project') { renderAiProjects(); aiShow('projects'); }
      else { aiShow('home'); loadAiHome(); }
    }
  }, { passive: true });
})();

$('#aih-new').onclick = () => aiNewChat();
$('#aih-projects').onclick = () => { renderAiProjects(); aiShow('projects'); };
$('#aip-new').onclick = async () => {
  const name = await appPrompt('新建项目', '项目名，如：申论批改');
  if (!name || !name.trim()) return;
  const ins = await appPrompt('项目自定义指令（可留空）', '例：你是申论阅卷老师，对我提交的答案按采分点批改打分');
  try {
    await api('/api/aichat/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim(), instructions: (ins || '').trim() }) });
    await loadAiHome(); renderAiProjects();
  } catch (e) { toast(e.message, true); }
};
$('#ai-panel').addEventListener('click', async e => {
  const back = e.target.closest('[data-aiback]');
  if (back) {
    if (back.dataset.aiback === 'close') { $('#ai-panel').classList.add('hidden'); applyPush(); avoidFab(); }
    else aiBack();
    return;
  }
  const menu = e.target.closest('[data-aimenu]');
  if (menu) {
    e.stopPropagation();
    openAiChatMenu(+menu.dataset.aimenu, menu.dataset.atitle, menu.dataset.aproj, menu.dataset.astar === '1');
    return;
  }
  const pdel = e.target.closest('[data-aipdel]');
  if (pdel) {
    e.stopPropagation();
    if (!(await appConfirm('删除这个项目？（对话会保留，只是不再归组）'))) return;
    try { await api('/api/aichat/projects/' + pdel.dataset.aipdel, { method: 'DELETE' }); await loadAiHome(); renderAiProjects(); } catch (err) { toast(err.message, true); }
    return;
  }
  const chat = e.target.closest('[data-aichat]');
  if (chat) { aiOpenChat(+chat.dataset.aichat); return; }
  const proj = e.target.closest('[data-aiproj]');
  if (proj) { openAiProject(+proj.dataset.aiproj); return; }
});
$('#ai-close').onclick = () => { $('#ai-panel').classList.add('hidden'); applyPush(); avoidFab(); };
$('#ai-text').addEventListener('input', aiGrow);
$('#ai-text').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); aiSend(); } });

/* ================= 全文搜索 ================= */
let searchData = { q: '', filter: 'all', results: [] };
function openSearch() {
  searchData = { q: '', filter: 'all', results: [] };
  $('#search-input').value = '';
  $('#search-results').innerHTML = '';
  $('#search-empty').classList.add('hidden');
  document.querySelectorAll('#search-filter .chip').forEach(x => x.classList.toggle('active', x.dataset.sf === 'all'));
  push({ view: 'search' });
  setTimeout(() => $('#search-input').focus(), 80);
}
$('#home-search').onclick = openSearch;
let searchTimer2;
$('#search-input').addEventListener('input', e => {
  clearTimeout(searchTimer2);
  const q = e.target.value.trim();
  searchTimer2 = setTimeout(() => runSearch(q), 250);
});
$('#search-filter').addEventListener('click', e => {
  const c = e.target.closest('[data-sf]'); if (!c) return;
  searchData.filter = c.dataset.sf;
  document.querySelectorAll('#search-filter .chip').forEach(x => x.classList.toggle('active', x.dataset.sf === searchData.filter));
  renderSearch();
});
async function runSearch(q) {
  searchData.q = q;
  if (!q) { searchData.results = []; renderSearch(); return; }
  try {
    const d = await api('/api/search?q=' + encodeURIComponent(q));
    // 功能入口匹配（名称/关键词），置顶
    const fhits = FEATURES.filter(f => f.name.includes(q) || f.kw.includes(q))
      .map(f => ({ type: 'feature', title: f.name, snippet: f.desc, _open: f.open }));
    searchData.results = fhits.concat(d.results);
    renderSearch();
  } catch (e) { toast(e.message, true); }
}
function hl(text, q) {
  const t = esc(text || '');
  if (!q) return t;
  try { return t.replace(new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'), '<mark>$1</mark>'); }
  catch (_) { return t; }
}
const SR_TYPE = { note: '小记', material: '资料', doc: '知识库', wrongq: '错题', boardkb: '基础知识', news: '时政', policydoc: '要文', partydict: '理论词典', classic: '古诗文', changshi: '常识', sucai: '素材', gaikuo: '概括句', entry: '成语词语', feature: '功能',
  draft: '草稿本', essay: '范文', gongwen: '应用文', changkao: '常考', theory: '理论', xiyu: '习语', work: '经典著作',
  annot: '批注' };
// 功能入口索引：搜索时匹配名称/关键词，结果置顶直达
const FEATURES = [
  { name: '备考规划', desc: '任务清单 · AI 按你的学情排当天计划', kw: '规划助手备考计划学习计划每日计划安排时间距考试', open: () => { openTasks(); setTimeout(() => tkSwitch('plan'), 60); } },
  { name: '范文推荐', desc: '申论 · 热门话题仿真卷 + 全套参考答案', kw: '范文推荐大作文议论文应用文参考答案话题基层治理科技创新乡村振兴', open: () => openEssays() },
  { name: '题目解析', desc: '题库 · 上传讲义让 AI 解出没答案的例题', kw: '题目解析讲义识题答案解析上传pdfword副本', open: () => openDocqa() },
  { name: '真题批改', desc: '申论 · 四大题型讲义 + AI 逐点批改', kw: '申论真题批改归纳概括综合分析提出对策贯彻执行大作文阅卷采分点范文', open: () => openShenlun() },
  { name: '常考', desc: '高频成语/实词/上位词/古诗文/常识/提法', kw: '常考高频考点成语实词上位词提法', open: () => openChangkao() },
  { name: '上位词积累', desc: '常考 · 逻辑填空概括词提示', kw: '上位词概括词下位词逻辑填空', open: () => openCkBoard('上位词') },
  { name: '理论基础', desc: '政治理论 · 马原/毛概/中特/习思想', kw: '理论马原马克思毛概毛泽东思想邓小平三个代表科学发展观习近平新时代中特公基', open: () => openTheory() },
  { name: '每日时政', desc: '政治理论 · 每天自动更新 AI 三行式', kw: '时政新闻党内国内四川国际', open: () => openNews() },
  { name: '时政要文库', desc: '政治理论 · 重要文件全文+AI解读', kw: '要文二十大报告十五五规划政府工作报告一号文件讲话', open: () => openPolicyDocs() },
  { name: '党的创新理论学习词典', desc: '政治理论 · 12371 术语速查+背诵', kw: '词典理论两个确立四个意识党章党史', open: () => openPartyDict() },
  { name: '常识积累', desc: '常识判断 · 七大板块考情+考点', kw: '常识人文科技法律地理经济公文管理', open: () => openChangshi() },
  { name: '成语词语积累', desc: '言语理解 · 查询收录+AI解释', kw: '成语词语词组选词填空', open: () => openIdiom() },
  { name: '古诗文·名句速查', desc: '议论文 · 唐诗宋词四书五经', kw: '古诗文诗词名句唐诗宋词论语', open: () => openClassics() },
  { name: '素材积累', desc: '议论文 · 人物/事例/理论论据 每日更新', kw: '素材人物事例理论论据写作', open: () => openSucai('全部') },
  { name: '衔接表达', desc: '议论文 · 过渡/转折/万能句式', kw: '衔接过渡转折句式', open: () => openSucai('衔接表达') },
  { name: '概括句积累', desc: '应用文 · 材料表述→规范概括句', kw: '概括句申论', open: () => openGaikuo() },
  { name: '应用文上位词', desc: '应用文 · 公文规范上位表述，按场景归类', kw: '应用文上位词公文规范表述通知意见倡议书规范用语提法', open: () => openGongwen() },
  { name: '错题本', desc: '拍照/输入 · AI 判题型给解析', kw: '错题刷题', open: () => openWrongq() },
  { name: '草稿本', desc: '错题本 · 平时打草稿/演算，手写不识别，自动保存', kw: '草稿本草稿纸打草稿演算竖式手写画板白板涂鸦计算', open: () => openDrafts() },
  { name: '巩固测试', desc: '任务清单 · 每日任务里，按当天计划出题，背题/测试两种模式', kw: '巩固测试测验做题背题模式服务端判分每日测试', open: () => { openTasks(); setTimeout(() => tkSwitch('daily'), 60); } },
  { name: '计划记录', desc: '任务清单 · 历史计划回看 + 进度分析', kw: '计划记录历史回看进度分析冷落模块', open: () => openPlanLog() },
  { name: '经典著作', desc: '毛泽东选集 · 全文精读 + AI 导读', kw: '经典著作毛选毛泽东选集精读朗读', open: () => openWorks() },
  { name: '今日复习', desc: '遗忘曲线 · 该复习的都在这', kw: '复习遗忘曲线艾宾浩斯背诵', open: () => openReview() },
  { name: '小记', desc: '随手记 · 标签归类', kw: '笔记记录', open: () => openNotes() },
  { name: '知识库', desc: '笔记本 · 文档 · 分组整理', kw: '文档笔记本', open: () => openKb() },
  { name: '资料库', desc: '图片/文档/网页 应用内查看', kw: '资料文件上传', open: () => openMaterials() },
  { name: '基础知识点', desc: '各板块 基础知识+方法技巧', kw: '基础知识方法技巧', open: () => { openSection(SECTIONS[0] && SECTIONS[0].key); toast('进入任意板块即可看「基础知识点」'); } },
  { name: '账户', desc: '个人信息 · 改密码/邮箱/密保', kw: '账号设置密码退出登录', open: () => openAccount() },
];
function renderSearch() {
  const box = $('#search-results');
  // 筛选条只留「这次搜到东西」的类别，免得十几个 chip 排满一屏
  document.querySelectorAll('#search-filter .chip').forEach(c => {
    const t = c.dataset.sf;
    c.classList.toggle('hidden', !!searchData.q && t !== 'all'
      && !searchData.results.some(r => r.type === t));
  });
  if (!searchData.q) { box.innerHTML = ''; $('#search-empty').classList.add('hidden'); return; }
  let items = searchData.results;
  if (searchData.filter !== 'all') items = items.filter(r => r.type === searchData.filter);
  if (!items.length) {
    box.innerHTML = '';
    $('#search-empty').classList.remove('hidden');
    $('#search-empty').textContent = '没有匹配「' + searchData.q + '」的内容';
    return;
  }
  $('#search-empty').classList.add('hidden');
  box.innerHTML = items.map((r, i) => {
    const meta = r.type === 'doc' ? ('知识库：' + esc(r.notebook || ''))
      : r.type === 'material' ? ((r.ext || '').replace('.', '').toUpperCase() + (r.board ? ' · ' + esc(r.board) : ''))
        : r.type === 'note' ? (r.tags && r.tags.length ? r.tags.map(t => '#' + esc(t)).join(' ') : (r.board ? esc(r.board) : ''))
          : (r.board ? esc(r.board) : '');
    return `<div class="sr-item" data-sri="${i}">
      <div class="sr-head"><span class="sr-type ${r.type}">${SR_TYPE[r.type]}</span>
        <span class="sr-title">${hl(r.title, searchData.q)}</span></div>
      ${r.snippet ? `<div class="sr-snip">${hl(r.snippet, searchData.q)}</div>` : ''}
      ${meta ? `<div class="sr-meta">${meta}</div>` : ''}
    </div>`;
  }).join('');
  box._items = items;
}
$('#search-results').addEventListener('click', async e => {
  const it = e.target.closest('[data-sri]'); if (!it) return;
  const r = ($('#search-results')._items || [])[+it.dataset.sri]; if (!r) return;
  if (r.type === 'feature') {
    if (r._open) r._open();
  } else if (r.type === 'material') {
    if (r.viewable) openViewer(r.id, r.title, r.ext);
    else { const a = document.createElement('a'); a.href = '/api/materials/' + r.id + '/download'; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); }
  } else if (r.type === 'doc') {
    await openNotebook(r.notebook_id);
    openDoc(r.id);
  } else if (r.type === 'note') {
    try {
      const note = await api('/api/notes/' + r.id);
      openNotes();
      setTimeout(() => loadDraft(note), 120);
    } catch (e) { toast(e.message, true); }
  } else if (r.type === 'wrongq') {
    openWqDetail(r.id);
  } else if (r.type === 'boardkb') {
    openBoardKb(r.board);
  } else if (r.type === 'news') {
    openNewsItem(r.id);
  } else if (r.type === 'policydoc') {
    openPolicyDoc(r.id);
  } else if (r.type === 'classic') {
    openClassicDetail(r.id);
  } else if (r.type === 'partydict') {
    await openPartyDict();
    $('#pd-q').value = r.title; loadPartyDict();
  } else if (r.type === 'changshi') {
    csBoard = r.cs_board; csTopic = r.cs_topic;
    push({ view: 'csboard', title: csBoard });
    loadCsBoard();
  } else if (r.type === 'sucai') {
    openSucai(r.kind || '全部');
  } else if (r.type === 'gaikuo') {
    openGaikuo();
  } else if (r.type === 'entry') {
    openIdiom();
    state.q = r.title; $('#search').value = r.title; loadEntries();
  } else if (r.type === 'draft') {
    openDrafts();
    setTimeout(() => openDraft(r.id), 80);
  } else if (r.type === 'essay') {
    openEssay(r.id);
  } else if (r.type === 'gongwen') {
    openGongwen();
    setTimeout(() => { $('#gw-q').value = r.term || r.title; $('#gw-q').dispatchEvent(new Event('input')); }, 120);
  } else if (r.type === 'changkao') {
    openCkBoard(r.ck_board || '上位词');
  } else if (r.type === 'theory') {
    openThBoard(r.th_board || '');
  } else if (r.type === 'xiyu') {
    openNews();
    setTimeout(() => { const b = document.querySelector('#news-boards [data-nb="习语"]'); if (b) b.click(); }, 260);
  } else if (r.type === 'work') {
    openWorkDetail(r.id);
  } else if (r.type === 'annot') {
    // 批注：打开它所在的那份资料，笔迹会自己按锚贴回原处（PDF 按页、阅读模式按那句话）
    if (r.mat) openViewer(r.mat.id, r.mat.name, r.mat.ext);
    else toast('这条批注不在资料库里', true);
  }
});

/* ================= 错题本 ================= */
const WQ_BOARDS = ['常识判断', '资料分析', '判断推理', '数量关系', '政治理论', '言语理解与表达', '申论'];
let wqState = { board: '', q: '', star: false, page: 1, pages: 1 };
function openWrongq() {
  wqState = { board: '', q: '', star: false, page: 1, pages: 1 };
  $('#wq-input').value = '';
  push({ view: 'wrongq' });
  loadWqBoards(); loadWrongq();
}
async function loadWqBoards() {
  try {
    const d = await api('/api/wrongq/boards');
    $('#wq-cats').innerHTML =
      `<button class="chip active" data-wc="">全部${d.total ? ' ' + d.total : ''}</button>` +
      `<button class="chip" data-wc="__star">★ 收藏${d.star ? ' ' + d.star : ''}</button>` +
      d.boards.map(b => `<button class="chip" data-wc="${esc(b.name)}">${esc(b.name)} ${b.count}</button>`).join('');
  } catch (_) { }
}
$('#wq-cats').addEventListener('click', e => {
  const c = e.target.closest('[data-wc]'); if (!c) return;
  const v = c.dataset.wc; wqState.star = (v === '__star'); wqState.board = wqState.star ? '' : v; wqState.page = 1;
  document.querySelectorAll('#wq-cats .chip').forEach(x => x.classList.toggle('active', x.dataset.wc === v));
  loadWrongq();
});
let wqTimer;
$('#wq-input').addEventListener('input', e => { clearTimeout(wqTimer); wqTimer = setTimeout(() => { wqState.q = e.target.value.trim(); wqState.page = 1; loadWrongq(); }, 280); });
async function loadWrongq() {
  let url = '/api/wrongq?page=' + wqState.page;
  if (wqState.board) url += '&board=' + encodeURIComponent(wqState.board);
  if (wqState.q) url += '&q=' + encodeURIComponent(wqState.q);
  if (wqState.star) url += '&star=1';
  try { const d = await api(url); wqState.pages = d.pages; renderWq(d.items, d.total); } catch (e) { toast(e.message, true); }
}
function renderWq(items, total) {
  const box = $('#wq-list');
  if (!items.length) {
    box.innerHTML = ''; $('#wq-empty').classList.remove('hidden');
    $('#wq-empty').textContent = wqState.star ? '还没有收藏的错题' : (wqState.q ? '没有匹配的错题' : '还没有错题，点右下角 ＋ 记录第一道');
    $('#wq-pager').classList.add('hidden'); return;
  }
  $('#wq-empty').classList.add('hidden');
  box.innerHTML = items.map(w => `
    <div class="wq-item" data-id="${w.id}">
      <div class="wq-head">
        ${w.qtype ? `<span class="wq-type">${esc(w.qtype)}</span>` : ''}
        ${w.board ? `<span class="wq-board">${esc(w.board)}</span>` : ''}
        <button class="cls-star ${w.starred ? 'on' : ''}" data-wqstar="${w.id}">${w.starred ? '★' : '☆'}</button>
      </div>
      <div class="wq-q">${esc((w.question || '（图片题）').slice(0, 80))}</div>
    </div>`).join('');
  box._items = items;
  const p = $('#wq-pager');
  if (wqState.pages <= 1) p.classList.add('hidden');
  else { p.classList.remove('hidden'); $('#wq-info').textContent = '第 ' + wqState.page + ' / ' + wqState.pages + ' 页 · 共 ' + total + ' 道'; $('#wq-prev').disabled = wqState.page <= 1; $('#wq-next').disabled = wqState.page >= wqState.pages; }
}
$('#wq-list').addEventListener('click', async e => {
  const s = e.target.closest('[data-wqstar]');
  if (s) {
    const id = s.dataset.wqstar; const on = !s.classList.contains('on');
    try { await api('/api/wrongq/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: on }) }); s.classList.toggle('on', on); s.textContent = on ? '★' : '☆'; if (wqState.star && !on) loadWrongq(); } catch (err) { toast(err.message, true); }
    return;
  }
  const card = e.target.closest('.wq-item'); if (card) openWqDetail(+card.dataset.id);
});
$('#wq-prev').onclick = () => { if (wqState.page > 1) { wqState.page--; loadWrongq(); window.scrollTo({ top: 0 }); } };
$('#wq-next').onclick = () => { if (wqState.page < wqState.pages) { wqState.page++; loadWrongq(); window.scrollTo({ top: 0 }); } };
$('#wq-fab').onclick = openWqAdd;

/* 新增错题 */
let wqImgFile = null;
function openWqAdd() {
  wqImgFile = null;
  $('#wqa-q').value = ''; $('#wqa-a').value = ''; $('#wqa-imgprev').innerHTML = '';
  $('#wqa-board').innerHTML = '<option value="">（自动判断）</option>' + WQ_BOARDS.map(b => `<option>${b}</option>`).join('');
  $('#wqa-go').disabled = false; $('#wqa-go').textContent = '🤖 AI 分析并收录';
  push({ view: 'wqadd' });
}
async function wqOcrFill(file) {
  wqImgFile = file;
  $('#wqa-imgprev').innerHTML = `<img src="${URL.createObjectURL(file)}"><span>已附题目图片</span>`;
  toast('识别中…');
  const fd = new FormData(); fd.append('file', file);
  try {
    const d = await api('/api/ocr', { method: 'POST', body: fd });
    if (d.text) { const cur = $('#wqa-q').value.trim(); $('#wqa-q').value = cur ? cur + '\n' + d.text : d.text; toast('已识别，可修正'); }
    else toast('没识别到文字，可手动输入', true);
  } catch (e) { toast(e.message, true); }
}
$('#wqa-cam').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; if (f) wqOcrFill(f); });
$('#wqa-img').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; if (f) wqOcrFill(f); });
$('#wqa-go').onclick = async () => {
  const q = $('#wqa-q').value.trim();
  if (!q && !wqImgFile) { toast('请输入题目或拍照', true); return; }
  const fd = new FormData();
  fd.append('question', q); fd.append('answer', $('#wqa-a').value.trim()); fd.append('board', $('#wqa-board').value);
  if (wqImgFile) fd.append('image', wqImgFile);
  $('#wqa-go').disabled = true; $('#wqa-go').textContent = 'AI 分析中…（约十几秒）';
  try { const w = await api('/api/wrongq', { method: 'POST', body: fd }); toast('已收录'); back(); openWqDetail(w.id); }
  catch (e) { toast(e.message, true); $('#wqa-go').disabled = false; $('#wqa-go').textContent = '🤖 AI 分析并收录'; }
};

/* 错题详情 */
let wqData = null;
async function openWqDetail(id) {
  push({ view: 'wqdetail' });
  $('#wqd-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try { wqData = await api('/api/wrongq/' + id); renderWqDetail(); } catch (e) { $('#wqd-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function wqSec(t, v) { return v ? `<div class="cd-sec"><div class="cd-sec-t">${t}</div><div class="cd-sec-b">${esc(v).replace(/\n/g, '<br>')}</div></div>` : ''; }
function renderWqDetail() {
  const w = wqData;
  $('#wqd-wrap').innerHTML = `
    <div class="wqd-head">
      ${w.qtype ? `<span class="wq-type">${esc(w.qtype)}</span>` : ''}
      ${w.board ? `<span class="wq-board">${esc(w.board)}</span>` : ''}
      <button class="cls-star ${w.starred ? 'on' : ''}" id="wqd-star">${w.starred ? '★' : '☆'}</button>
    </div>
    <div class="cd-sec"><div class="cd-sec-t">题目</div><div class="cd-sec-b wqd-q">${esc(w.question).replace(/\n/g, '<br>') || '（见图）'}</div>
      ${w.image ? `<img class="wqd-img" src="${w.image}">` : ''}</div>
    ${w.answer ? wqSec('我的答案 / 解析', w.answer) : ''}
    ${wqSec('知识点', w.points)}
    ${wqSec('公式 / 方法', w.method)}
    ${wqSec('解题技巧', w.skill)}
    ${wqSec('解题步骤', w.steps)}
    <div class="cd-sec"><div class="cd-sec-t">我的笔记</div>
      <textarea id="wqd-note" class="wqd-note" placeholder="记录易错点、复盘…">${esc(w.note)}</textarea>
      <button class="btn" id="wqd-savenote" style="margin-top:8px;">保存笔记</button></div>
    <div class="wqd-acts">
      <button class="btn" id="wqd-reanalyze">🤖 重新分析</button>
      <button class="btn" id="wqd-del" style="color:#e0524d;border-color:#f0c9c6;">删除</button>
    </div>`;
}
$('#wqd-wrap').addEventListener('click', async e => {
  if (e.target.closest('#wqd-star')) {
    const on = !wqData.starred;
    try { await api('/api/wrongq/' + wqData.id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: on }) }); wqData.starred = on; renderWqDetail(); } catch (err) { toast(err.message, true); } return;
  }
  if (e.target.closest('#wqd-savenote')) {
    const note = $('#wqd-note').value;
    try { await api('/api/wrongq/' + wqData.id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }) }); wqData.note = note; toast('已保存'); } catch (err) { toast(err.message, true); } return;
  }
  const rb = e.target.closest('#wqd-reanalyze');
  if (rb) {
    rb.disabled = true; rb.textContent = '分析中…';
    try { wqData = await api('/api/wrongq/' + wqData.id + '/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); renderWqDetail(); toast('已更新'); } catch (err) { toast(err.message, true); rb.disabled = false; rb.textContent = '🤖 重新分析'; } return;
  }
  if (e.target.closest('#wqd-del')) {
    if (!(await appConfirm('删除这道错题？'))) return;
    try { await api('/api/wrongq/' + wqData.id, { method: 'DELETE' }); toast('已删除'); back(); loadWrongq(); loadWqBoards(); } catch (err) { toast(err.message, true); } return;
  }
});

/* ================= 板块基础知识点 ================= */
let bkbBoard = '', bkbData = null;
async function openBoardKb(board) {
  bkbBoard = board;
  push({ view: 'boardkb', title: board + ' · 基础知识点' });
  $('#bkb-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try { const d = await api('/api/boardkb?board=' + encodeURIComponent(board)); bkbData = d; renderBkb(); }
  catch (e) { $('#bkb-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderBkb() {
  const d = bkbData;
  const ai = d.ai
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">📚 基础知识 · 方法技巧（AI 整理）</div>
        <div class="cd-sec-b">${mdToHtml(d.ai)}</div>
        <button class="btn cd-ai-regen" id="bkb-regen">重新生成</button></div>`
    : `<div class="bkb-gen"><p class="cd-tip" style="margin:0 0 12px">还没有整理这个板块的基础知识点，让 AI 帮你系统梳理一份。</p>
        <button class="btn primary" id="bkb-gen" style="width:100%;padding:13px;">🤖 AI 生成基础知识点</button></div>`;
  const pts = (d.points || []).map(p =>
    `<div class="bkb-point"><div class="bkb-point-c">${esc(p.content).replace(/\n/g, '<br>')}</div>
      <button class="bkb-point-del" data-bpdel="${p.id}">×</button></div>`).join('');
  $('#bkb-wrap').innerHTML = ai + `
    <div class="cd-sec"><div class="cd-sec-t">✍️ 我的补充</div>
      <div class="bkb-points">${pts || '<p class="cd-tip" style="margin:0 0 10px">还没有补充，写点自己的要点/技巧吧。</p>'}</div>
      <div class="bkb-add">
        <textarea id="bkb-input" rows="2" placeholder="添加一条自己的知识点/技巧…"></textarea>
        <button class="btn primary" id="bkb-addbtn">添加</button>
      </div>
    </div>`;
}
$('#bkb-wrap').addEventListener('click', async e => {
  const g = e.target.closest('#bkb-gen') || e.target.closest('#bkb-regen');
  if (g) {
    g.disabled = true; g.textContent = 'AI 生成中…（约二十秒）';
    try {
      const d = await api('/api/boardkb/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ board: bkbBoard, force: g.id === 'bkb-regen' }) });
      bkbData.ai = d.content; renderBkb(); toast('已生成');
    } catch (err) { toast(err.message, true); g.disabled = false; g.textContent = '🤖 AI 生成基础知识点'; }
    return;
  }
  if (e.target.closest('#bkb-addbtn')) {
    const c = $('#bkb-input').value.trim(); if (!c) return;
    try { const p = await api('/api/boardkb/point', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ board: bkbBoard, content: c }) }); bkbData.points.unshift({ id: p.id, content: c }); renderBkb(); } catch (err) { toast(err.message, true); }
    return;
  }
  const del = e.target.closest('[data-bpdel]');
  if (del) {
    try { await api('/api/boardkb/point/' + del.dataset.bpdel, { method: 'DELETE' }); bkbData.points = bkbData.points.filter(p => p.id != del.dataset.bpdel); renderBkb(); } catch (err) { toast(err.message, true); }
  }
});

/* ================= 顶栏 ================= */
$('#admin-btn').onclick = () => { location.href = '/admin'; };
async function doLogout() {
  if (!(await appConfirm('退出登录？'))) return;
  try { await fetch('/logout', { method: 'POST' }); } catch (_) {}
  location.href = '/login';
}
// 关键点加粗：书名号/引号/【】/「」/“X个XX”等高频要点；换行转 <br>
function emKey(text) {
  let t = esc(text || '');
  t = t.replace(/《[^》]{1,40}》/g, m => '<b>' + m + '</b>')
    .replace(/“[^”]{1,40}”/g, m => '<b>' + m + '</b>')
    .replace(/「[^」]{1,40}」/g, m => '<b>' + m + '</b>')
    .replace(/【[^】]{1,40}】/g, m => '<b>' + m + '</b>')
    .replace(/[一二三四五六七八九十两]+个[一-龥]{2,8}/g, m => '<b>' + m + '</b>');
  return t.replace(/\n/g, '<br>');
}
function isDocHeading(s) {
  return /^(第[一二三四五六七八九十百]+[篇章节]|[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\)|\d+[、.．])/.test(s);
}
