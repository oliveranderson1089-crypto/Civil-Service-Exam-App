/* AI 助手
 *
 * 由 app.js 按它自己的区段边界切出（原 L2631-2915）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, CAN_ABORT, IS_MOBILE, aiBack, api, appConfirm, appPrompt,
   applyPush, avoidFab, back, c, composing, createDock,
   esc, loadClassics, loadDaily, loadEntries, loadFeed, loadPlan,
   loadWrongq, lsGet, lsSet, mdToHtml, navHomeCard, openAiChatMenu, push, stack, toast */

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
    + (aiStreamText ? `<div class="ai-msg assistant" id="ai-stream">${mdToHtml(aiStreamText)}</div>` : '')
    + (aiBusy && !aiStreamText ? '<div class="ai-msg assistant ai-typing" id="ai-typing">思考中…</div>' : '');
  const box = $('#ai-msgs');
  // 等布局重排完再滚到底 —— 同步设 scrollTop 时 mdToHtml 的高度可能还没算好，
  // 会出现「回复只露一行、其余被输入框挡住」（就是那个「只显示问题」的错觉）。
  box.scrollTop = box.scrollHeight;
  requestAnimationFrame(() => { box.scrollTop = box.scrollHeight; });
  $('#ai-send').disabled = aiBusy;
  aiTickStart();
}
/* 「思考中…」原来是一句死字：网络一抖，它就那么停在那儿，用户分不清是 AI 在想、
   还是这次请求已经悄悄死了，只能一直等。走流式之后正文一出来这行就被真回复顶掉了，
   它只负责「出字之前」那一两秒；超过 5 秒就把已等的秒数显出来，让「还在动」可见。 */
let aiTimer = 0;
function aiTickStart() {
  clearInterval(aiTimer); aiTimer = 0;
  if (!aiBusy) return;
  const t0 = Date.now();
  aiTimer = setInterval(() => {
    const el = $('#ai-typing');
    if (!el) { clearInterval(aiTimer); aiTimer = 0; return; }
    const s = Math.round((Date.now() - t0) / 1000);
    const base = aiPhase || '思考中…';
    el.textContent = s < 5 ? base : (s < 20 ? base + '（' + s + ' 秒）' : base + '（' + s + ' 秒，网络较慢）');
  }, 1000);
}
/* 流式收到的正文。逐字重画整个消息列表太贵（每片都要把全部历史过一遍 Markdown），
   所以只改那一个气泡的 innerHTML，并且最多 80 毫秒画一次。 */
let aiStreamText = '', aiPhase = '', aiPaintAt = 0, aiPaintTimer = 0;
function aiPaint() {
  clearTimeout(aiPaintTimer); aiPaintTimer = 0;
  const now = Date.now();
  if (now - aiPaintAt < 80) { aiPaintTimer = setTimeout(aiPaint, 80); return; }
  aiPaintAt = now;
  const el = $('#ai-stream');
  if (!el) { renderAI(); return; }            // 第一片到达：先让气泡本身出现
  el.innerHTML = mdToHtml(aiStreamText);
  const box = $('#ai-msgs'); box.scrollTop = box.scrollHeight;
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

// ===== AI 工具面板：把 AI 能调的工具做成可点的快捷入口，既能一键让 AI 做、也能直接打开 =====
// go=打开首页某功能（复用 navHomeCard，跟点首页图标一样跳转，含往下的二三级）；
// ask=一键发预设问题让 AI 调工具作答；input=先弹输入框收集内容，再让 AI 记进去。带 sub:'AI' 的走大模型。
// 「打开功能」组不写死：直接读首页卡片，天然镜像首页（含用户拖拽排序），日后加新功能自动出现。
const HOME_IC = { changkao: '⭐', notes: '🗒️', kb: '📚', wrongq: '📓', materials: '📁',
  quiz: '📝', tasks: '✅', drive: '☁️', chat: '💬', review: '🔁', idiom: '📖' };
function aiHomeNavItems() {
  return [...document.querySelectorAll('#home-cards .home-card[data-go]')].map(c => {
    const go = c.dataset.go;
    let ic = HOME_IC[go] || '📂';
    if (go.startsWith('sec:')) { const t = ((c.querySelector('.hc-logo') || {}).textContent || '').trim(); if (t) ic = t; }
    return { go, ic, label: ((c.querySelector('.hc-name') || {}).textContent || '').trim() };
  }).filter(x => x.label);
}
const AI_TOOL_GROUPS = [
  { name: '问我的数据', items: [
    { ic: '📊', label: '我的数据总览', sub: 'AI', ask: '帮我看看我的数据总览' },
    { ic: '🔁', label: '今天要复习什么', sub: 'AI', ask: '我今天有哪些要复习的？' },
    { ic: '🗓️', label: '今天的备考计划', sub: 'AI', ask: '我今天的备考计划是什么？' },
    { ic: '✅', label: '今天还有什么任务', sub: 'AI', ask: '我今天有哪些任务还没做？' },
    { ic: '📈', label: '我的进度和坚持天数', sub: 'AI', ask: '看看我的备考进度和连续学习天数' },
    { ic: '🎯', label: '我的刷题正确率/成绩', sub: 'AI', ask: '我的刷题正确率和最近测验成绩怎么样？' },
    { ic: '🏛️', label: '本应用有多少资源', sub: 'AI', ask: '这个应用的题库、古诗文库、常识库各有多少？' },
  ] },
  { name: '快捷记录', items: [
    { ic: '➕', label: '收录一个词', sub: 'AI', input: '输入要收录的成语/词语', ask: v => `帮我把「${v}」收录到成语词语积累` },
    { ic: '📝', label: '记一条小记', sub: 'AI', input: '要记的内容', ask: v => `帮我在小记里记一条：${v}` },
    { ic: '📅', label: '加一个每日任务', sub: 'AI', input: '每日任务内容，如「刷20道判断推理」', ask: v => `帮我加个每日任务：${v}` },
    { ic: '🔍', label: '查词释义', sub: 'AI', input: '要查释义的词', ask: v => `「${v}」是什么意思？` },
  ] },
];

let _aiToolG = [];   // 当前渲染用的分组（打开功能是动态的，点击时按这份索引，避免错位）
function renderAiTools(kw) {
  kw = (kw || '').trim().toLowerCase();
  _aiToolG = [{ name: '打开功能', items: aiHomeNavItems() }, ...AI_TOOL_GROUPS];
  let html = '';
  _aiToolG.forEach((g, gi) => {
    const rows = g.items.map((it, ii) => ({ it, ii })).filter(({ it }) => !kw || it.label.toLowerCase().includes(kw));
    if (!rows.length) return;
    html += `<div class="ai-tool-group">${g.name}</div>` + rows.map(({ it, ii }) =>
      `<button class="ai-tool-item" data-g="${gi}" data-i="${ii}"><span class="tl-ic">${it.ic}</span>` +
      `<span class="tl-tx">${esc(it.label)}</span>${it.sub ? `<span class="tl-sub">${it.sub}</span>` : ''}</button>`).join('');
  });
  $('#ai-tool-list').innerHTML = html || '<div class="ai-tool-empty">没有匹配的工具</div>';
}

function aiToolRun(it) {
  $('#ai-toolsheet').classList.add('hidden');
  if (it.go) {                       // 打开首页某功能：跟点首页图标一样跳转（含往下的二三级），先收起 AI 面板
    $('#ai-panel').classList.add('hidden');
    if (window.applyPush) applyPush();
    if (window.avoidFab) avoidFab();
    try { navHomeCard(it.go); toast('已打开「' + it.label + '」'); }
    catch (e) { console.error('[AI工具] 打开失败', it.go, e); toast('打开「' + it.label + '」没成功', true); }
    return;
  }
  if (it.input) {                    // 快捷记录：先问用户要内容，再让 AI 记
    appPrompt(it.input).then(v => { v = (v || '').trim(); if (v) aiToolSend(it.ask(v)); });
    return;
  }
  aiToolSend(it.ask);                // 快捷提问：把预设问题一键发给 AI
}

function aiToolSend(text) { $('#ai-text').value = text; aiGrow(); aiSend(); }

$('#ai-tools').onclick = () => {
  renderAiTools(''); $('#ai-tool-filter').value = '';
  $('#ai-toolsheet').classList.remove('hidden');
  if (!IS_MOBILE) setTimeout(() => $('#ai-tool-filter').focus(), 60);   // 手机端不自动聚焦，免得弹键盘遮列表
};
$('#ai-tool-filter').addEventListener('input', e => renderAiTools(e.target.value));
$('#ai-toolsheet').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]') || e.target.id === 'ai-toolsheet') { $('#ai-toolsheet').classList.add('hidden'); return; }
  const b = e.target.closest('.ai-tool-item'); if (!b) return;
  const it = (_aiToolG[+b.dataset.g] || { items: [] }).items[+b.dataset.i];
  if (it) aiToolRun(it);
});

/* 流式读一次对话。返回 {reply, title, actions}。

   为什么不用 EventSource：它只能 GET，而问题文本可以很长（截图 OCR 出来的整道题），
   塞进 query string 会被各段代理截断。所以 POST + 自己解 SSE 帧。

   安卓壳 minSdk21，老 WebView 可能没有 ReadableStream —— 那就抛 noStream，
   调用方退回非流式 /send，功能一样只是没有逐字效果。 */
const CAN_STREAM = !!(window.fetch && window.TextDecoder && typeof ReadableStream !== 'undefined');
const noStream = () => Object.assign(new Error('NO_STREAM'), { noStream: true });
async function aiSendStream(payload) {
  let ctl = null, timer = 0;
  /* 空闲超时，不是总超时：流式下每个 token 都是一次心跳，所以「45 秒一个字节都没有」
     才叫连接死了。模型写得再长也不会被误杀 —— 这正是非流式做不到的。 */
  const arm = () => { if (ctl) { clearTimeout(timer); timer = setTimeout(() => ctl.abort(), 45000); } };
  if (CAN_ABORT) { ctl = new AbortController(); arm(); }
  let r;
  try {
    r = await fetch('/api/aichat/chats/' + aiChatId + '/stream', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: payload }), signal: ctl ? ctl.signal : undefined
    });
  } catch (e) { clearTimeout(timer); throw e; }
  if (r.status === 401) { clearTimeout(timer); location.href = '/login'; throw new Error('未登录'); }
  if (!r.ok) {
    clearTimeout(timer);
    let msg = '请求失败';
    try { msg = (await r.json()).error || msg; } catch (_) { /* 不是 JSON 就用默认话术 */ }
    throw new Error(msg);
  }
  if (!r.body || !r.body.getReader) { clearTimeout(timer); throw noStream(); }
  const reader = r.body.getReader(), dec = new TextDecoder();
  let buf = '', done = null, err = '';
  for (;;) {
    const chunk = await reader.read();
    arm();
    if (chunk.done) break;
    buf += dec.decode(chunk.value, { stream: true });
    const frames = buf.split('\n\n');
    buf = frames.pop();                        // 最后一段可能只收到一半，留着跟下一片拼
    for (const f of frames) {
      let ev = 'message', data = '';
      for (const line of f.split('\n')) {
        if (line.indexOf('event:') === 0) ev = line.slice(6).trim();
        else if (line.indexOf('data:') === 0) data += line.slice(5).trim();
      }
      if (!data) continue;
      let d; try { d = JSON.parse(data); } catch (_) { continue; }
      if (ev === 'delta') { aiStreamText += d; aiPaint(); }
      else if (ev === 'reasoning') { aiPhase = '思考中…'; }
      else if (ev === 'tool') { aiPhase = '正在操作…'; }
      else if (ev === 'done') { done = d; }
      else if (ev === 'error') { err = d.error || 'AI 调用失败'; }
    }
  }
  clearTimeout(timer);
  if (err) throw new Error(err);
  if (done) return { reply: done.reply || aiStreamText, title: done.title, actions: done.actions || [] };
  // 连接在收完之前断了：已经出来的字是真的，别丢掉重来，标一句「可能不完整」就行。
  if (aiStreamText) return { reply: aiStreamText + '\n\n（连接中断，回答可能不完整）', title: '', actions: [] };
  throw noStream();                            // 一个字节都没有 → 当没流过，退回非流式
}

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
  aiBusy = true; aiStreamText = ''; aiPhase = ''; renderAI();
  try {
    let d = null;
    if (CAN_STREAM) {
      try { d = await aiSendStream(payload); }
      catch (e) { if (!e.noStream) throw e; }   // 只有「这条路走不通」才退回，真错误照报
    }
    if (!d) {
      d = await api('/api/aichat/chats/' + aiChatId + '/send', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        // 非流式没有逐字心跳，只能靠总超时兜底：服务端自己封顶 100 秒
        // （mods/agent.py AI_BUDGET），这里多给 30 秒。没有它，连接整条断掉时
        // 「思考中…」就永远转下去。
        body: JSON.stringify({ content: payload }), timeoutMs: 130000
      });
    }
    aiMsgs.push({ role: 'assistant', content: d.reply || '（空回复）' });
    if (d.title) $('#aic-title').textContent = d.title;
    aiStreamText = ''; aiBusy = false; renderAI();
    aiRunActions(d.actions);          // AI 真做了事（加收录 / 打开某功能）→ 前端跟着执行/刷新
    return;
  } catch (e) {
    const partial = aiStreamText;     // 断在半截时，已经出来的字是真的，别连它一起丢掉
    if (partial) aiMsgs.push({ role: 'assistant', content: partial });
    aiMsgs.push({ role: 'assistant', content: '⚠️ ' + (e.name === 'AbortError' ? 'AI 响应超时（网络不稳），请再发一次' : e.message) });
  }
  aiStreamText = ''; aiBusy = false; renderAI();
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
      // 原先是 try{...}catch(_){} 然后无条件 toast「已为你打开」—— 函数一抛异常，
      // 用户就收到「已为你打开」却什么也没发生。说打开了就得真打开。
      try {
        window[a.fn]();
        toast('已为你打开「' + (a.label || '') + '」');
      } catch (e) {
        console.error('[AI] 打开「%s」失败：', a.label || a.fn, e);
        toast('打开「' + (a.label || '') + '」没成功', true);
      }
    } else if (a.type === 'refresh') {
      // 用户正看着对应视图才刷新（省得白重绘）。tasks/plan 同属「任务清单」view=tasks 的两个页签。
      if (a.what === 'entries' && v === 'idiom' && typeof loadEntries === 'function') loadEntries();
      else if (a.what === 'notes' && v === 'notes' && typeof loadFeed === 'function') loadFeed();
      else if (a.what === 'wrongq' && v === 'wrongq' && typeof loadWrongq === 'function') loadWrongq();
      else if (a.what === 'tasks' && v === 'tasks' && typeof loadDaily === 'function') loadDaily();
      else if (a.what === 'plan' && v === 'tasks' && typeof loadPlan === 'function') loadPlan();
      else if (a.what === 'classics' && v === 'classics' && typeof loadClassics === 'function') loadClassics();
      // 文案由后端按实际动作给（收录/收藏/删除各不同），不再前端硬编码 —— 否则删词也会弹「已收录」
      if (a.toast) toast(a.toast);
    } else if (a.type === 'confirm') {
      aiConfirm(a);   // AI 要删东西：弹确认框，用户点确认后才真删
    }
  }
}

// AI 请求删除 → 弹美化确认框；点确认才调后端带 _confirmed 真删，结果补进对话并刷新
async function aiConfirm(a) {
  const w = a.args && a.args.word;
  const msg = w ? `删除「${w}」？此操作不可撤销。` : '确认删除这条内容？此操作不可撤销。';
  if (!(await appConfirm(msg))) return;   // 取消：什么都不做，AI 那句「确定吗」留在对话里
  try {
    const d = await api('/api/aichat/chats/' + aiChatId + '/confirm', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool: a.tool, args: a.args || {} }),
    });
    aiMsgs.push({ role: 'assistant', content: d.reply || '已删除。' });
    renderAI();
    aiRunActions(d.actions);   // 跑它带回的 refresh（刷新对应列表）
  } catch (e) { toast(e.message || '删除失败', true); }
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
    try { grip.setPointerCapture(e.pointerId); } catch (_) { /* 捕获失败不影响画线，指针事件照样收得到 */ }
    document.body.classList.add('resizing-ns'); e.preventDefault();
  });
  grip.addEventListener('pointermove', e => {
    if (!dragging) return;
    const h = Math.max(MIN, Math.min(maxH(), Math.round(sh + (sy - e.clientY))));  // 往上拖=变高
    ta.style.height = h + 'px'; lsSet(key, h);
  });
  const end = e => { if (!dragging) return; dragging = false; document.body.classList.remove('resizing-ns'); try { grip.releasePointerCapture(e.pointerId); } catch (_) { /* 捕获失败不影响画线，指针事件照样收得到 */ } };
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
