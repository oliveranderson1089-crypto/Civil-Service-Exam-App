/* AI 助手
 *
 * 由 app.js 按它自己的区段边界切出（原 L2631-2915）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, IS_MOBILE, aiBack, api, appConfirm, appPrompt,
   applyPush, avoidFab, back, c, composing, createDock,
   esc, loadEntries, loadFeed, loadWrongq, lsGet, lsSet,
   mdToHtml, openAiChatMenu, push, stack, toast */

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
