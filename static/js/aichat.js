/* AI 助手
 *
 * 由 app.js 按它自己的区段边界切出（原 L2631-2915）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, CAN_ABORT, IS_MOBILE, aiBack, anchorMenu, api, appConfirm, appPrompt, applyPush, artEm, avoidFab, back, c, composing, createDock, esc, growAndSync, loadClassics, loadDaily, loadEntries, loadFeed, loadPlan, loadWrongq, lsGet, lsSet, mdToHtml, navHomeCard, openAiChatMenu, push, stack, toast */

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
let aiHomeQ = '';
async function loadAiHome() {
  try {
    const d = await api('/api/aichat/home' + (aiHomeQ ? '?q=' + encodeURIComponent(aiHomeQ) : ''));
    $('#aih-sec').textContent = aiHomeQ ? ('搜索结果（' + d.chats.length + '）') : '最近对话';
    $('#aih-pcount').textContent = d.projects.length || '';
    $('#aih-recents').innerHTML = d.chats.length ? d.chats.map(c => `
      <div class="aih-item" data-aichat="${c.id}">
        <div class="aih-it">${c.starred ? artEm('⭐') + ' ' : ''}${esc(c.title || '（新对话）')}</div>
        <div class="aih-im">${c.pname ? AI_FOLDER + ' ' + esc(c.pname) + ' · ' : ''}${esc((c.updated_at || '').slice(5, 16))}</div>
        <button class="aih-del" data-aimenu="${c.id}" data-atitle="${esc(c.title || '')}" data-aproj="${c.project_id || ''}" data-astar="${c.starred ? 1 : 0}">⋮</button>
      </div>`).join('') : '<p class="empty" style="padding:20px 0">还没有对话，点上面「' + artEm("＋") + ' 新对话」开始。</p>';
    $('#ai-panel')._projects = d.projects;
    $('#ai-panel')._chats = d.chats;
  } catch (e) { toast(e.message, true); }
}
/* 主动开场：打开助手先给一句基于今天复习/错题的判断 + 几个可点的起手式。
   空白输入框是最大的使用门槛。这一条不调模型（数字本来就在库里），所以立刻就出来。 */
let aiOpener = null;
async function aiLoadOpener() {
  try { aiOpener = await api('/api/aichat/opener'); }
  catch (_) { aiOpener = null; }               // 拿不到就退回原来那句固定问候
  if (!aiMsgs.length) renderAI();
}
async function aiNewChat(projectId) {
  // 懒创建：先进界面，第一次发送消息时才真正建会话（不产生空记录）
  aiChatId = null; aiProjectId = projectId || null; aiMsgs = [];
  aiTraceOpen = {}; aiLoadOpener();
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
    aiTier = d.tier || 'fast'; aiTraceOpen = {}; renderAiTier();
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
      <button class="aih-del" data-aipdel="${p.id}">${artEm('✕')}</button>
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
      <div class="aih-it">${c.starred ? artEm('⭐') + ' ' : ''}${esc(c.title || '（新对话）')}</div>
      <div class="aih-im">${esc((c.updated_at || '').slice(5, 16))}</div>
      <button class="aih-del" data-aimenu="${c.id}" data-atitle="${esc(c.title || '')}" data-aproj="${c.project_id || ''}" data-astar="${c.starred ? 1 : 0}">⋮</button>
    </div>`).join('')
    + (p.instructions ? `<p class="cd-tip" style="margin-top:12px">${artEm('📋')} 项目指令：${esc(p.instructions)}</p>` : '');
  aiShow('project');
}
$('#aipd-new').onclick = () => { if (aiCurProject) aiNewChat(aiCurProject.id); };
/* 一轮工具调用的卡片：收起时一行「查了你的错题本，3 步」，点开看每一步调了什么、拿到什么。
   这是「AI 到底动了我什么」从黑盒变账本的那一步 —— 轨迹已经落库，刷新后还在。 */
function aiTraceHtml(m, i) {
  const t = m.trace || [];
  if (!t.length) return '';
  const names = [...new Set(t.map(s => s.label || s.name))];
  const head = names.slice(0, 2).join('、') + (names.length > 2 ? ' 等' : '') + '，' + t.length + ' 步';
  const open = aiTraceOpen[i];
  return `<div class="ai-trace${open ? ' open' : ''}" data-trace="${i}">
    <div class="ai-th"><span class="ic">🔧</span><span>${esc(head)}</span><span class="ar">${open ? '收起 ▴' : '展开 ▾'}</span></div>
    ${open ? '<div class="ai-tb">' + t.map((s, n) => `
      <div class="ai-step${s.result && /失败|错误|未找到|没找到/.test(s.result) ? ' bad' : ''}">
        <span class="n">${n + 1}</span>
        <span class="c"><span class="k">${esc(s.name || '')}</span>${s.args && Object.keys(s.args).length
    ? '（' + esc(Object.entries(s.args).filter(([k]) => k !== '_confirmed')
      .map(([k, v]) => k + '=' + String(v).slice(0, 30)).join('，')) + '）' : ''}
          <span class="r">${esc((s.result || '').slice(0, 200))}</span></span>
      </div>`).join('') + '</div>' : ''}
  </div>`;
}
let aiTraceOpen = {};
function renderAI() {
  $('#ai-msgs').innerHTML = (aiMsgs.length ? '' : (aiOpener && aiOpener.greet
    ? `<div class="ai-open"><div class="t">${esc(aiOpener.greet)}</div>
        <div class="a-chips">${(aiOpener.chips || []).map(c => `<button class="a-chip" data-chip="${esc(c)}">${esc(c)}</button>`).join('')}</div></div>`
    : '<div class="ai-msg assistant">我是你的公考 AI 助手 👋 讲知识点、出题、翻译古文、分析错题、聊备考都行。我还能看到你的收录/错题/复习数据。</div>'))
    + aiMsgs.map((m, i) => {
      if (m.kind === 'tool') return aiTraceHtml(m, i);
      const acts = (m.role === 'assistant' && m.kind !== 'error' && !aiBusy)
        ? `<div class="ai-acts" data-mi="${i}"><span data-act="copy">${artEm('📋')} 复制</span>` +
          (i === aiMsgs.length - 1 ? '<span data-act="retry">↻ 重答</span>' : '') +
          '<span data-act="branch">⑂ 分支</span></div>' : '';
      const uacts = (m.role === 'user' && !aiBusy)
        ? `<div class="ai-acts uacts" data-mi="${i}"><span data-act="edit">✎ 改问题</span></div>` : '';
      const cont = (m.truncated && i === aiMsgs.length - 1 && !aiBusy)
        ? '<div class="ai-contwrap"><button class="ai-contbtn" id="ai-continue">▸ 继续（上一轮没做完）</button></div>' : '';
      return `<div class="ai-msg ${m.role}${m.kind === 'error' ? ' ai-err' : ''}">` +
        (m.role === 'assistant' ? mdToHtml(m.content) : esc(m.content)) + '</div>' + acts + uacts + cont;
    }).join('')
    + (aiStreamText ? `<div class="ai-msg assistant" id="ai-stream">${mdToHtml(aiStreamText)}</div>` : '')
    + (aiBusy && !aiStreamText ? '<div class="ai-msg assistant ai-typing" id="ai-typing">思考中…</div>' : '')
    + (aiBusy ? '<div class="ai-stopwrap"><button class="ai-stopbtn" id="ai-stop">■ 停止生成</button></div>' : '');
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
/* 已经写完的那些段落渲染一次就冻结，之后每次重绘只解析**最后一个没写完的段落**。
   原先每 80 毫秒把已收到的全文重跑一遍 Markdown 再整段替换 innerHTML：前几百字很流畅，
   写到两千字时每次重绘都在解析两千字，越写越卡。
   切点只取 \n\n（段落边界），且必须在代码块之外 —— 从 ``` 中间切开会把代码块拆坏。 */
let aiDoneHtml = '', aiDoneLen = 0;
function aiPaintReset() { aiDoneHtml = ''; aiDoneLen = 0; }
function aiPaint() {
  clearTimeout(aiPaintTimer); aiPaintTimer = 0;
  const now = Date.now();
  if (now - aiPaintAt < 80) { aiPaintTimer = setTimeout(aiPaint, 80); return; }
  aiPaintAt = now;
  const el = $('#ai-stream');
  if (!el) { renderAI(); return; }            // 第一片到达：先让气泡本身出现
  const s = aiStreamText;
  const cut = s.lastIndexOf('\n\n');
  // 代码围栏必须成对，否则这一刀正落在代码块里
  if (cut > aiDoneLen && (s.slice(0, cut).split('```').length - 1) % 2 === 0) {
    aiDoneHtml += mdToHtml(s.slice(aiDoneLen, cut));
    aiDoneLen = cut;
  }
  el.innerHTML = aiDoneHtml + mdToHtml(s.slice(aiDoneLen));
  const box = $('#ai-msgs'); box.scrollTop = box.scrollHeight;
}
let aiAtts = [];  // [{name, text}]
function renderAiAtts() {
  $('#ai-atts').innerHTML = aiAtts.map((a, i) =>
    `<span class="ai-att">${artEm('📎')} ${esc(a.name)} <button data-aiattdel="${i}">×</button></span>`).join('');
}
$('#ai-atts').addEventListener('click', e => {
  const b = e.target.closest('[data-aiattdel]'); if (!b) return;
  aiAtts.splice(+b.dataset.aiattdel, 1); renderAiAtts();
});
$('#ai-attach').onclick = () => anchorMenu($('#ai-attsheet'), $('#ai-attach'));
$('#ai-attsheet').addEventListener('click', e => {
  const b = e.target.closest('[data-aiatt]'); if (!b) return;
  $('#ai-attsheet').classList.add('hidden');
  if (IS_MOBILE) $('#ai-input .input-tools').classList.add('hidden');   // 手机端：选完附件来源，➕ 弹出的工具面板也一起收起
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
    // image 是留下来的原图文件名：带着它，这一轮就走视觉模型（模型真看得见图形和图表），
    // 抽出来的文字继续当兜底一起发过去。
    aiAtts.push({ name: d.name || file.name, text: d.text || '', image: d.image || '' });
    renderAiAtts();
    toast(d.image ? '已附加，发送时 AI 会直接看这张图' : '已附加，发送时 AI 会读取其内容');
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
      `<button class="ai-tool-item" data-g="${gi}" data-i="${ii}"><span class="tl-ic">${artEm(it.ic)}</span>` +
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
  if (IS_MOBILE) $('#ai-input .input-tools').classList.add('hidden');   // 手机端：➕ 弹出的工具面板让位给工具大面板
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
/* 停止生成用的把手：aiSendStream 建好 AbortController 就存这儿，
   #ai-stop 按下时 abort 它（声明放在使用它的函数**之前**，免得将来有人在顶层提前调用踩 TDZ）。 */
let aiCtl = null, aiStopped = false;
const CAN_STREAM = !!(window.fetch && window.TextDecoder && typeof ReadableStream !== 'undefined');
const noStream = () => Object.assign(new Error('NO_STREAM'), { noStream: true });
async function aiSendStream(content, atts) {
  let ctl = null, timer = 0;
  /* 空闲超时，不是总超时：流式下每个 token 都是一次心跳，所以「45 秒一个字节都没有」
     才叫连接死了。模型写得再长也不会被误杀 —— 这正是非流式做不到的。 */
  const arm = () => { if (ctl) { clearTimeout(timer); timer = setTimeout(() => ctl.abort(), 45000); } };
  if (CAN_ABORT) { ctl = new AbortController(); arm(); aiCtl = ctl; }   // 同一个 ctl 也给「停止生成」用
  let r;
  try {
    r = await fetch('/api/aichat/chats/' + aiChatId + '/stream', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: content, attachments: atts || [] }), signal: ctl ? ctl.signal : undefined
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
      // 后端把工具名连人话标签一起推过来了。以前这里一律显示「正在操作…」——
      // 查错题和删小记长得一模一样，用户不知道它在动谁的数据。
      else if (ev === 'tool') { aiPhase = '正在' + ((d && d.label) || '操作') + '…'; }
      else if (ev === 'done') { done = d; }
      else if (ev === 'error') { err = d.error || 'AI 调用失败'; }
    }
  }
  clearTimeout(timer);
  if (err) throw new Error(err);
  // 把服务端 done 里的东西**整包带走**，别一个个挑：漏掉 user_mid/msg_id 会让
  // 「改问题 / 分支」在流式路径（也就是所有现代浏览器）上永远报「还没同步好」，
  // 漏掉 truncated 则「继续」按钮永远不出现 —— 服务端明明都发了。
  if (done) return Object.assign({}, done, { reply: done.reply || aiStreamText,
    actions: done.actions || [], trace: done.trace || [] });
  // 连接在收完之前断了：已经出来的字是真的，别丢掉重来，标一句「可能不完整」就行。
  if (aiStreamText) return { reply: aiStreamText + '\n\n（连接中断，回答可能不完整）', title: '', actions: [] };
  throw noStream();                            // 一个字节都没有 → 当没流过，退回非流式
}

async function aiSend() {
  const t = $('#ai-text').value.trim();
  if ((!t && !aiAtts.length) || aiBusy) return;
  /* 附件全文**不再拼进问题正文**。以前 payload（含整篇 PDF）既发出去又落库，而屏幕上
     显示的是精简的 shown —— 刷新会话后自己那句话就变成了几千字的正文，标题也从它截前
     24 字。现在两者分开：content 是人看的那句，附件走 attachments 单独传、单独存。 */
  const atts = aiAtts.slice();
  const shown = (t ? t : '') + (atts.length ? (t ? '\n' : '') + '📎 ' + atts.map(a => a.name).join('、') : '');
  if (atts.length) { aiAtts = []; renderAiAtts(); }
  if (!aiChatId) {
    try {
      const d = await api('/api/aichat/chats', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: aiProjectId || null, tier: aiTier }) });
      aiChatId = d.id;
    } catch (e) { toast(e.message, true); return; }
  }
  aiMsgs.push({ role: 'user', content: shown });
  $('#ai-text').value = ''; aiGrow();
  aiBusy = true; aiStreamText = ''; aiPhase = ''; aiPaintReset(); renderAI();
  try {
    let d = null;
    if (CAN_STREAM) {
      try { d = await aiSendStream(shown, atts); }
      catch (e) { if (!e.noStream) throw e; }   // 只有「这条路走不通」才退回，真错误照报
    }
    if (!d) {
      d = await api('/api/aichat/chats/' + aiChatId + '/send', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        // 非流式没有逐字心跳，只能靠总超时兜底：服务端自己封顶 100 秒
        // （mods/agent.py AI_BUDGET），这里多给 30 秒。没有它，连接整条断掉时
        // 「思考中…」就永远转下去。
        body: JSON.stringify({ content: shown, attachments: atts }), timeoutMs: 130000
      });
    }
    // 工具轨迹排在回答**前面**（跟服务端落库的顺序一致：先查，再答）
    // 把服务端刚落库的行号补给本地这两条。没有它，「改问题 / 分支」拿到的 m.id 是
    // undefined → 服务端按「最后一轮」处理，改第一个问题会把后面几轮一起删掉还不吭声。
    for (let k = aiMsgs.length - 1; k >= 0; k--) {
      if (aiMsgs[k].role === 'user') { aiMsgs[k].id = d.user_mid || aiMsgs[k].id; break; }
    }
    if (d.trace && d.trace.length) aiMsgs.push({ role: 'assistant', kind: 'tool', trace: d.trace });
    // truncated：轮数/预算用完它还在调工具 —— 活没干完，给个「继续」而不是让用户对着半截总结
    aiMsgs.push({ role: 'assistant', id: d.msg_id, content: d.reply || '（空回复）', truncated: !!d.truncated });
    if (d.title) $('#aic-title').textContent = d.title;
    aiStreamText = ''; aiBusy = false; aiCtl = null; renderAI();
    aiRunActions(d.actions);          // AI 真做了事（加收录 / 打开某功能）→ 前端跟着执行/刷新
    aiAutoTitle();                    // 首轮结束后再让模型起个名字（回答已经显示完，起名慢一点无所谓）
    return;
  } catch (e) {
    const partial = aiStreamText;     // 断在半截时，已经出来的字是真的，别连它一起丢掉
    if (partial) aiMsgs.push({ role: 'assistant', content: partial + (aiStopped ? '\n\n（已停止）' : '') });
    // 用户自己按的「停止生成」不是错误，别报「响应超时，请再发一次」
    if (!aiStopped) {
      aiMsgs.push({ role: 'assistant', content: '⚠️ ' + (e.name === 'AbortError' ? 'AI 响应超时（网络不稳），请再发一次' : e.message) });
    } else if (!partial) {
      aiMsgs.push({ role: 'assistant', content: '（已停止）' });
    }
  }
  aiStreamText = ''; aiBusy = false; aiStopped = false; aiCtl = null; renderAI();
}
/* 停止生成：复用流式那条 AbortController。以前它只服务于「45 秒一个字节都没有」的
   空闲超时，界面上没有出口 —— 发现问错了只能眼睁睁看它写完两千字。
   已经吐出来的部分留着（服务端那边 finally 分支也会把半截落库）。 */
function aiStop() {
  if (!aiCtl) return;
  aiStopped = true;
  try { aiCtl.abort(); } catch (_) { /* 已经结束了就不用停 */ }
  aiCtl = null;
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
  /* 后端在 confirm 动作里带了 summary（那条数据的原文摘要）和 label（这是什么操作）。
     以前这里只认 args.word —— 删词能显示词，删错题和删小记一律「确认删除这条内容？」，
     用户不知道是哪一条，只能盲点确定。删除不可逆，这是最不该省的一步。 */
  const w = a.args && a.args.word;
  const msg = a.summary
    ? `确认${a.label || '删除'}？此操作不可撤销。\n\n${a.summary}`
    : (w ? `删除「${w}」？此操作不可撤销。` : '确认删除这条内容？此操作不可撤销。');
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
function aiGrow() { growAndSync('#ai-text', '#ai-input'); }
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
/* 消息区里的东西每次 renderAI 都重建 —— 一律委托绑定，别绑在具体按钮上 */
$('#ai-msgs').addEventListener('click', async e => {
  if (e.target.closest('#ai-stop')) { aiStop(); return; }
  if (e.target.closest('#ai-continue')) {      // 接着上一轮往下做（服务端的 4 轮/100 秒上限重新计）
    $('#ai-text').value = '继续，把上面没做完的做完'; aiGrow(); aiSend(); return;
  }
  const chip = e.target.closest('[data-chip]');
  if (chip) { $('#ai-text').value = chip.dataset.chip; aiGrow(); aiSend(); return; }
  const tr = e.target.closest('[data-trace]');
  if (tr) { const i = +tr.dataset.trace; aiTraceOpen[i] = !aiTraceOpen[i]; renderAI(); return; }
  const a = e.target.closest('[data-act]'); if (!a) return;
  const i = +a.closest('[data-mi]').dataset.mi, m = aiMsgs[i]; if (!m) return;
  const act = a.dataset.act;
  if (act === 'copy') {
    try { await navigator.clipboard.writeText(m.content || ''); toast('已复制'); }
    catch (_) { toast('这个浏览器不让复制，长按选中吧', true); }
  } else if (act === 'retry') {
    aiRetry('');
  } else if (act === 'edit') {
    // 没有 id 就别发：服务端会把 msg_id=0 当成「退最后一轮」，改前面的问题反而删掉后面的
    if (!m.id) { toast('这条还没同步好，稍等一下再改', true); return; }
    const v = await appPrompt('改一下问题再发', '', m.content || '');
    if (v && v.trim()) aiRetry(v.trim(), m.id);
  } else if (act === 'branch') {
    if (!m.id) { toast('这条还没同步好，稍等一下再分支', true); return; }
    try {
      const d = await api('/api/aichat/chats/' + aiChatId + '/branch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ msg_id: m.id })
      });
      toast('已新开一条分支对话');
      await loadAiHome(); aiOpenChat(d.id);
    } catch (err) { toast(err.message, true); }
  }
});
/* 重答 / 改问：先让服务端把历史退回到那一轮之前，再用（新的或原来的）问题正常重发。
   生成只有一条路（/stream），这里不复制一份对话逻辑。 */
async function aiRetry(newContent, msgId) {
  if (aiBusy) return;
  try {
    const d = await api('/api/aichat/chats/' + aiChatId + '/retry', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: newContent || '', msg_id: msgId || 0 })
    });
    // 本地历史也退回去：退到最后一条 user 之前
    let cut = -1;
    for (let i = aiMsgs.length - 1; i >= 0; i--) {
      if (aiMsgs[i].role === 'user' && (!msgId || aiMsgs[i].id === msgId)) { cut = i; break; }
    }
    if (cut >= 0) aiMsgs = aiMsgs.slice(0, cut);
    aiAtts = (d.attachments || []).slice();
    renderAiAtts();
    $('#ai-text').value = d.content || '';
    renderAI();
    aiSend();
  } catch (e) { toast(e.message, true); }
}
/* ---- 长期记忆：AI 记住的关于我的事，可查可删 ----
   记忆最怕悄悄记错还一直用，所以来源和「被用过几次」都摆出来。 */
async function openAiMemories() {
  const box = $('#ai-memsheet');
  box.classList.remove('hidden');
  box.innerHTML = `<div class="cp-box"><div class="cp-head">AI 记住的关于我的事<button data-memx>✕</button></div>
    <div class="cp-list"><p class="empty">加载中…</p></div>
    <div class="mem-add"><input id="mem-new" placeholder="想让它长期记住什么？"><button id="mem-addbtn">添加</button></div></div>`;
  try {
    const d = await api('/api/aichat/memories');
    box.querySelector('.cp-list').innerHTML =
      '<p class="mem-tip">这些会在每次对话开头带给 AI。删掉的立刻失效。</p>' +
      (d.memories.length ? d.memories.map(m => `
        <div class="ai-mem"><div class="c"><div class="t">${esc(m.text)}</div>
          <div class="s">${esc(m.source || '')}${m.hits ? ' · 已用 ' + m.hits + ' 次' : ''}</div></div>
          <button class="x" data-memdel="${m.id}">✕</button></div>`).join('')
        : '<p class="empty">还没有记住任何事。</p>');
  } catch (e) { box.querySelector('.cp-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#ai-memsheet').addEventListener('click', async e => {
  if (e.target.closest('[data-memx]') || e.target.id === 'ai-memsheet') { $('#ai-memsheet').classList.add('hidden'); return; }
  const del = e.target.closest('[data-memdel]');
  if (del) {
    try { await api('/api/aichat/memories/' + del.dataset.memdel, { method: 'DELETE' }); openAiMemories(); }
    catch (err) { toast(err.message, true); }
    return;
  }
  if (e.target.closest('#mem-addbtn')) {
    const v = ($('#mem-new').value || '').trim(); if (!v) return;
    try {
      await api('/api/aichat/memories', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: v })
      });
      openAiMemories();
    } catch (err) { toast(err.message, true); }
  }
});
$('#aih-mem').onclick = openAiMemories;

/* 首轮结束后让模型给会话起个名（原先是把用户第一句话切前 24 字）。
   只在第一轮做，失败就保持原样 —— 名字不好看是小事，不值得打断用户。 */
async function aiAutoTitle() {
  if (!aiChatId || aiMsgs.filter(m => m.role === 'user').length !== 1) return;
  try {
    const d = await api('/api/aichat/chats/' + aiChatId + '/title', { method: 'POST' });
    if (d.title) $('#aic-title').textContent = d.title;
  } catch (_) { /* 起名失败不影响对话本身 */ }
}
/* 档位：快 / 深度。深度走推理模型（aiclient 的 pro 档），慢但想得清楚。 */
let aiTier = 'fast';
function renderAiTier() {
  const el = $('#ai-tier'); if (!el) return;
  el.querySelectorAll('[data-tier]').forEach(b => b.classList.toggle('on', b.dataset.tier === aiTier));
}
$('#ai-tier').addEventListener('click', async e => {
  const b = e.target.closest('[data-tier]'); if (!b || aiBusy) return;
  aiTier = b.dataset.tier; renderAiTier();
  if (!aiChatId) return;          // 还没建会话，等发送时一起带过去
  try {
    await api('/api/aichat/chats/' + aiChatId, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tier: aiTier })
    });
  } catch (err) { toast(err.message, true); }
});
// 手机端微信式输入栏：➕ 弹出工具小面板（🧰工具/📎附件/✍️手写/📷截图），桌面端这颗按钮本来就不显示
$('#ai-plus').onclick = () => anchorMenu($('#ai-input').querySelector('.input-tools'), $('#ai-plus'));
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

let aiHomeTimer = 0;
$('#aih-search').addEventListener('input', e => {
  aiHomeQ = e.target.value.trim();
  clearTimeout(aiHomeTimer);
  aiHomeTimer = setTimeout(loadAiHome, 220);      // 打字防抖
});
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
    openAiChatMenu(menu, +menu.dataset.aimenu, menu.dataset.atitle, menu.dataset.aproj, menu.dataset.astar === '1');
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
