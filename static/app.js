'use strict';
const $ = (s) => document.querySelector(s);
const api = (u, o) => fetch(u, o).then(async r => {
  if (r.status === 401) { location.href = '/login'; throw new Error('未登录'); }
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('application/json')) {
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || '请求失败');
    return d;
  }
  if (!r.ok) throw new Error('请求失败');
  return r;
});
const IN_APP = navigator.userAgent.includes('GongkaoApp');
// 手机端：安卓壳内 或 窄屏。手机端与网页端使用不同的「小记」界面
const IS_MOBILE = IN_APP || window.matchMedia('(max-width:760px)').matches;
document.body.classList.toggle('mobile-ui', IS_MOBILE);
const PAGE_SIZE = 5;

function toast(msg, err) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (err ? ' err' : '');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.add('hidden'), 2300);
}
const esc = (s) => (s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
function fmtSize(n) {
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(1) + ' MB';
}
function fmtTime(s) { return (s || '').slice(5, 16); }
// 线性 SVG 图标
const _svg = (p) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const IC = {
  feather: _svg('<path d="M20.24 12.24a6 6 0 0 0-8.49-8.49L5 10.5V19h8.5z"/><line x1="16" y1="8" x2="2" y2="22"/><line x1="17.5" y1="15" x2="9" y2="15"/>'),
  folder: _svg('<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>'),
  book: _svg('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'),
  edit: _svg('<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>'),
  del: _svg('<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'),
  clip: _svg('<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>'),
  wrong: _svg('<path d="M9 11l-2 2 2 2"/><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="14 3 14 9 20 9"/><path d="M14.5 12.5l3 3M17.5 12.5l-3 3"/>'),
  bulb: _svg('<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.8 10.6c.5.5.8 1 .8 1.9v.5h6v-.5c0-.9.3-1.4.8-1.9A6 6 0 0 0 12 3z"/>'),
  clock: _svg('<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>'),
  quote: _svg('<path d="M6 17h3l2-4V7H5v6h3z"/><path d="M14 17h3l2-4V7h-6v6h3z"/>'),
};
// 板块下的功能模块（可扩展：以后给某板块加更多功能图标）
const BOARD_FEATURES = {
  '言语理解与表达': [
    { key: 'idiom', name: '成语词语积累', desc: '选词填空 · 拼音释义 · 导 PDF', icon: 'book' },
  ],
  '政治理论': [
    { key: 'news', name: '每日时政', desc: '每天自动更新 · AI 摘要+考点', icon: 'feather' },
    { key: 'policydoc', name: '时政要文库', desc: '二十大·十五五·两会报告 全文+AI解读', icon: 'book' },
    { key: 'partydict', name: '党的创新理论学习词典', desc: '两个确立·四个意识… 12371 术语速查', icon: 'book' },
  ],
  '应用文': [
    { key: 'gaikuo', name: '概括句积累', desc: '每日更新 · 材料表述→规范概括句', icon: 'edit' },
  ],
  '议论文': [
    { key: 'sucai', name: '素材积累', desc: '每日更新 · 人物/事例/理论论据', icon: 'clip' },
    { key: 'lianjie', name: '衔接表达', desc: '过渡/转折/万能句式 不口语不重复', icon: 'quote' },
    { key: 'classics', name: '古诗文·名句速查', desc: '唐诗宋词 · 四书五经 · 查询收藏', icon: 'book' },
  ],
};
// 大板块（行测/申论）下的功能模块（预留，可扩展）
const SECTION_FEATURES = {};

let ME = null, SECTIONS = [], IDIOM_BOARD = '', ALL_BOARDS = [];
let stack = [];

/* ---------------- 导航 ---------------- */
const VIEWS = ['home', 'section', 'board', 'notes', 'kb', 'notebook', 'doc', 'materials', 'idiom', 'viewer', 'search', 'classics', 'cdetail', 'wrongq', 'wqadd', 'wqdetail', 'boardkb', 'account', 'partydict', 'policydoc', 'policydocd', 'news', 'newsd', 'gaikuo', 'sucai', 'review'];
const TITLES = { home: '公考助手', section: '', board: '', notes: '小记', kb: '知识库', notebook: '', doc: '', materials: '资料库', idiom: '成语词语', viewer: '查看', search: '搜索', classics: '古诗文速查', cdetail: '', wrongq: '错题本', wqadd: '记录错题', wqdetail: '错题详情', boardkb: '基础知识点', account: '账户', partydict: '创新理论词典', policydoc: '时政要文库', policydocd: '', news: '每日时政', newsd: '', gaikuo: '概括句积累', sucai: '素材积累', review: '今日复习' };
function render() {
  const st = stack[stack.length - 1];
  VIEWS.forEach(v => $('#view-' + v).classList.toggle('hidden', v !== st.view));
  $('#top-title').textContent = st.title || TITLES[st.view] || '公考助手';
  $('#nav-back').classList.toggle('hidden', stack.length <= 1);
  // 文档编辑器自带顶栏，隐藏全局顶栏
  document.querySelector('.topbar').classList.toggle('hidden', st.view === 'doc');
}
function push(state) { stack.push(state); render(); }
function back() { if (stack.length > 1) { stack.pop(); render(); } }
function goHome() { stack = [{ view: 'home' }]; render(); }
// 供安卓原生「返回/侧滑」调用：能退则退并返回 true，已在首页返回 false
window.appBack = function () {
  // AI 面板
  const aip = $('#ai-panel');
  if (aip && !aip.classList.contains('hidden')) { aip.classList.add('hidden'); return true; }
  // 0) 任意底部弹层（小记新建 / 知识库 + / 块菜单 / 插入面板）
  const sheets = [...document.querySelectorAll('.note-sheet:not(.hidden)')];
  if (sheets.length) { sheets[sheets.length - 1].classList.add('hidden'); return true; }
  // 2) 全屏小记编辑器
  const cp = document.querySelector('.composer.cp-open');
  if (cp) { newDraft(); return true; }
  // 3) 普通弹窗
  const m = document.querySelector('.modal:not(.hidden)');
  if (m) { m.classList.add('hidden'); return true; }
  // 4) 手机端搜索框展开时先收起
  const ms = $('#notes-msearch');
  if (IS_MOBILE && ms && !ms.classList.contains('hidden')) { toggleNoteSearch(); return true; }
  // 5) 文档编辑器：保存后退出
  const top = stack[stack.length - 1];
  if (top && top.view === 'doc') { saveDoc(); back(); if (KB.nb) loadNotebook(KB.nb.id); return true; }
  if (stack.length > 1) { back(); return true; }
  return false;
};

/* ---------------- 初始化 / 首页 ---------------- */
async function init() {
  try {
    ME = await api('/api/me');
    const d = await api('/api/sections');
    SECTIONS = d.sections; IDIOM_BOARD = d.idiom_board;
    ALL_BOARDS = SECTIONS.flatMap(s => s.boards);
  } catch (e) { return; }
  $('#admin-btn').classList.toggle('hidden', !ME.is_admin);
  $('#home-cards').innerHTML =
    SECTIONS.map(s => `
      <div class="home-card" data-go="sec:${esc(s.key)}">
        <div class="hc-logo hc-sec">${esc(s.icon)}</div>
        <div class="hc-name">${esc(s.name)}</div>
        <div class="hc-desc">${esc(s.desc)}</div>
      </div>`).join('') + `
    <div class="home-card" data-go="notes"><div class="hc-logo">${IC.feather}</div><div class="hc-name">小记</div><div class="hc-desc">随手记 · 标签归类</div></div>
    <div class="home-card" data-go="kb"><div class="hc-logo">${IC.book}</div><div class="hc-name">知识库</div><div class="hc-desc">笔记本 · 文档 · 分组整理</div></div>
    <div class="home-card" data-go="wrongq"><div class="hc-logo">${IC.wrong}</div><div class="hc-name">错题本</div><div class="hc-desc">拍照/输入 · AI 判题型给解析</div></div>
    <div class="home-card" data-go="materials"><div class="hc-logo">${IC.folder}</div><div class="hc-name">资料库</div><div class="hc-desc">图片/文档/网页 应用内查看</div></div>
    <div class="home-card" data-go="review"><div class="hc-logo hc-rev">${IC.clock || IC.bulb}<span class="rev-badge hidden" id="rev-badge"></span></div><div class="hc-name">今日复习</div><div class="hc-desc" id="rev-desc">遗忘曲线 · 该复习的都在这</div></div>`;
  goHome();
  refreshReviewBadge();
}
async function refreshReviewBadge() {
  try {
    const d = await api('/api/review/today');
    const b = $('#rev-badge');
    if (d.count > 0) { b.textContent = d.count > 99 ? '99+' : d.count; b.classList.remove('hidden'); }
    else b.classList.add('hidden');
    $('#rev-desc').textContent = d.count > 0 ? `今天有 ${d.count} 条要复习` : '今日复习完成，棒！';
  } catch (_) {}
}
$('#home-cards').addEventListener('click', e => {
  const c = e.target.closest('[data-go]'); if (!c) return;
  const g = c.dataset.go;
  if (g.startsWith('sec:')) openSection(g.slice(4));
  else if (g === 'notes') openNotes();
  else if (g === 'kb') openKb();
  else if (g === 'wrongq') openWrongq();
  else if (g === 'materials') openMaterials();
  else if (g === 'idiom') openIdiom();
  else if (g === 'review') openReview();
});
function openSection(key) {
  const sec = SECTIONS.find(s => s.key === key); if (!sec) return;
  $('#section-title').textContent = sec.name;
  const feats = SECTION_FEATURES[sec.name] || [];
  $('#section-feats').innerHTML = feats.map(f =>
    `<div class="home-card" data-secfeat="${esc(f.key)}">
      <div class="hc-logo">${IC[f.icon] || ''}</div>
      <div class="hc-name">${esc(f.name)}</div>
      <div class="hc-desc">${esc(f.desc)}</div>
    </div>`).join('');
  $('#board-grid').innerHTML = sec.boards.map(b => `
    <div class="board-card" data-board="${esc(b)}">
      <span class="bc-name">${esc(b)}</span>
      ${b === IDIOM_BOARD ? '<span class="bc-badge">成语词语</span>' : ''}
      <span class="bc-arrow">›</span>
    </div>`).join('');
  push({ view: 'section', title: sec.name });
}
$('#board-grid').addEventListener('click', e => {
  const c = e.target.closest('[data-board]'); if (!c) return;
  openBoard(c.dataset.board);
});
$('#section-feats').addEventListener('click', e => {
  const c = e.target.closest('[data-secfeat]'); if (!c) return;
  if (c.dataset.secfeat === 'classics') openClassics();
});
let curBoardFeat = '';
function openBoard(board) {
  curBoardFeat = board;
  // 每个板块都有「基础知识点」，再加上板块专属功能
  const feats = [{ key: 'boardkb', name: '基础知识点', desc: '基础知识 · 方法技巧', icon: 'bulb' }]
    .concat(BOARD_FEATURES[board] || []);
  $('#board-title').textContent = board;
  $('#board-features').innerHTML = feats.map(f =>
    `<div class="home-card" data-feat="${esc(f.key)}">
      <div class="hc-logo">${IC[f.icon] || ''}</div>
      <div class="hc-name">${esc(f.name)}</div>
      <div class="hc-desc">${esc(f.desc)}</div>
    </div>`).join('');
  $('#board-features').classList.remove('hidden');
  $('#board-ph').classList.add('hidden');
  push({ view: 'board', title: board });
}
$('#board-features').addEventListener('click', e => {
  const c = e.target.closest('[data-feat]'); if (!c) return;
  if (c.dataset.feat === 'idiom') openIdiom();
  else if (c.dataset.feat === 'classics') openClassics();
  else if (c.dataset.feat === 'boardkb') openBoardKb(curBoardFeat);
  else if (c.dataset.feat === 'partydict') openPartyDict();
  else if (c.dataset.feat === 'policydoc') openPolicyDocs();
  else if (c.dataset.feat === 'news') openNews();
  else if (c.dataset.feat === 'gaikuo') openGaikuo();
  else if (c.dataset.feat === 'sucai') openSucai('全部');
  else if (c.dataset.feat === 'lianjie') openSucai('衔接表达');
});
$('#nav-back').onclick = back;

/* ================= 小记（仿语雀） ================= */
let curNoteBoard = '';
let curTag = '';
let noteSearchQ = '';
function buildNotesSidebar() {
  $('#notes-sidebar').innerHTML =
    `<div class="ns-item${curNoteBoard === '' ? ' active' : ''}" data-board="">
        <span class="ns-name">全部</span>
        <span class="ns-count" data-cnt=""></span>
      </div>` +
    SECTIONS.map(s => `
    <div class="ns-group">${esc(s.name)}</div>
    ${s.boards.map(b => `
      <div class="ns-item${b === curNoteBoard ? ' active' : ''}" data-board="${esc(b)}">
        <span class="ns-name">${esc(b)}</span>
        <span class="ns-count" data-cnt="${esc(b)}"></span>
      </div>`).join('')}
  `).join('');
}
async function refreshNoteCounts() {
  try {
    const d = await api('/api/notes/counts');
    document.querySelectorAll('[data-cnt]').forEach(el => {
      const n = el.dataset.cnt === '' ? (d.total || 0) : (d.counts[el.dataset.cnt] || 0);
      el.textContent = n ? n : '';
    });
  } catch (_) {}
}
function openNotes(board) {
  curTag = '';
  if (IS_MOBILE) {
    // 手机端：统一信息流（不分板块，用标签区分）
    curNoteBoard = '';
    noteSearchQ = '';
    $('#notes-msearch').classList.add('hidden');
    $('#notes-msearch-input').value = '';
    push({ view: 'notes' });
    newDraft(); loadFeed(); loadFeedTags();
    return;
  }
  curNoteBoard = board != null ? board : (curNoteBoard || '');
  buildNotesSidebar();
  push({ view: 'notes' });
  newDraft(); loadFeed(); loadFeedTags(); refreshNoteCounts();
}
$('#notes-sidebar').addEventListener('click', e => {
  const it = e.target.closest('[data-board]'); if (!it) return;
  curNoteBoard = it.dataset.board; curTag = '';
  document.querySelectorAll('.ns-item').forEach(x => x.classList.toggle('active', x.dataset.board === curNoteBoard));
  newDraft(); loadFeed(); loadFeedTags();
});

/* ---- 编辑器（草稿） ---- */
let draft = { id: null, content: '', images: [], files: [], todos: [], tags: [] };
function newDraft() {
  draft = { id: null, content: '', images: [], files: [], todos: [], tags: [] };
  $('#cp-content').value = ''; renderComposer();
  closeComposerM();
}
// 手机端：把内嵌编辑器变成全屏弹出 / 收起
function openComposerM() {
  if (!IS_MOBILE) return;
  document.querySelector('.composer').classList.add('cp-open');
  document.body.classList.add('cp-open-lock');
  setTimeout(() => $('#cp-content').focus(), 60);
}
function closeComposerM() {
  document.querySelector('.composer').classList.remove('cp-open');
  document.body.classList.remove('cp-open-lock');
}
function loadDraft(n) {
  draft = {
    id: n.id, content: n.content,
    images: n.img_files.map((f, i) => ({ kind: 'old', file: f, url: n.images[i] })),
    files: n.att_files.map((a, i) => ({ kind: 'old', file: a.file, name: a.name, ext: a.ext, url: n.attachments[i].url })),
    todos: n.todos.map(t => ({ text: t.text, done: !!t.done })),
    tags: [...n.tags],
  };
  $('#cp-content').value = n.content;
  renderComposer();
  if (IS_MOBILE) { openComposerM(); return; }
  $('#view-notes').scrollIntoView({ behavior: 'smooth', block: 'start' });
  $('#cp-content').focus();
}
function renderComposer() {
  $('#cp-board').textContent = '# ' + curNoteBoard;
  $('#cp-todos').innerHTML = draft.todos.map((t, i) =>
    `<div class="cp-todo"><input type="checkbox" data-tdo="${i}" ${t.done ? 'checked' : ''}>
     <input class="cp-todo-text" data-tdt="${i}" value="${esc(t.text)}" placeholder="待办事项…">
     <button class="cp-x" data-tdr="${i}">×</button></div>`).join('');
  $('#cp-imgs').innerHTML = draft.images.map((im, i) =>
    `<div class="cp-thumb"><img src="${im.url}"><button class="cp-x" data-imr="${i}">×</button></div>`).join('');
  $('#cp-files').innerHTML = draft.files.map((f, i) =>
    `<div class="cp-file">📎 <span>${esc(f.name)}</span><button class="cp-x" data-flr="${i}">×</button></div>`).join('');
  $('#cp-tags').innerHTML = draft.tags.map((t, i) =>
    `<span class="cp-tag"># ${esc(t)}<button class="cp-x" data-tgr="${i}">×</button></span>`).join('') +
    `<button type="button" class="cp-tag-add" data-tagadd>＋ 标签</button>`;
  const editing = !!draft.id;
  $('#cp-submit').textContent = editing ? '保存' : '发布';
  $('#cp-del').classList.toggle('hidden', !editing);
  $('#cp-cancel').classList.toggle('hidden', !editing);
  $('#cp-hint').textContent = editing ? '编辑中…' : '';
  // 手机端全屏编辑器顶栏
  $('#cp-mtitle').textContent = editing ? '编辑小记' : '写小记';
  $('#cp-mdel').classList.toggle('hidden', !editing);
}
document.querySelector('.cp-bar').addEventListener('click', e => {
  const b = e.target.closest('[data-cp]'); if (!b) return;
  const t = b.dataset.cp;
  if (t === 'img') $('#cp-imgfile').click();
  else if (t === 'cam') $('#cp-camfile').click();
  else if (t === 'file') $('#cp-attfile').click();
  else if (t === 'todo') {
    draft.todos.push({ text: '', done: false }); renderComposer();
    const ins = document.querySelectorAll('.cp-todo-text'); if (ins.length) ins[ins.length - 1].focus();
  } else if (t === 'tag') {
    showTagInput();
  }
});
/* 行内标签输入（替代原生 prompt，仿语雀） */
function showTagInput() {
  const inp = $('#cp-taginput');
  inp.classList.remove('hidden'); inp.value = '';
  setTimeout(() => inp.focus(), 30);
}
function addTagsFrom(raw) {
  let added = false;
  (raw || '').split(/[\s,，、]+/).filter(Boolean).forEach(v => {
    if (!draft.tags.includes(v)) { draft.tags.push(v); added = true; }
  });
  return added;
}
$('#cp-taginput').addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    e.preventDefault();
    if (addTagsFrom(e.target.value)) renderComposer();
    e.target.value = '';
    setTimeout(() => { const i = $('#cp-taginput'); i.classList.remove('hidden'); i.focus(); }, 10);
  } else if (e.key === 'Escape') { e.target.value = ''; e.target.classList.add('hidden'); }
});
$('#cp-taginput').addEventListener('blur', e => {
  if (addTagsFrom(e.target.value)) renderComposer();
  e.target.value = ''; e.target.classList.add('hidden');
});
$('#cp-tags').addEventListener('click', e => {
  if (e.target.closest('[data-tagadd]')) { showTagInput(); }
});
// 立刻把所选文件读进内存（趁 content:// URI 权限还有效），避免发布时 URI 失效导致传 0 字节
async function _materialize(f, fallbackType) {
  try {
    const buf = await f.arrayBuffer();
    return new Blob([buf], { type: f.type || fallbackType || 'application/octet-stream' });
  } catch (_) { return f; }   // 兜底用原 File
}
async function addDraftImages(files) {
  const list = [...files];
  for (const f of list) {
    const blob = await _materialize(f, 'image/jpeg');
    draft.images.push({ kind: 'new', fileObj: blob, name: f.name || ('img_' + Date.now() + '.jpg'), url: URL.createObjectURL(blob) });
  }
  renderComposer();
}
$('#cp-imgfile').addEventListener('change', async e => { const fs = [...e.target.files]; e.target.value = ''; await addDraftImages(fs); });
$('#cp-camfile').addEventListener('change', async e => { const fs = [...e.target.files]; e.target.value = ''; await addDraftImages(fs); });
$('#cp-attfile').addEventListener('change', async e => {
  const list = [...e.target.files]; e.target.value = '';
  for (const f of list) {
    const blob = await _materialize(f);
    draft.files.push({ kind: 'new', fileObj: blob, name: f.name || 'file' });
  }
  renderComposer();
});
$('#cp-todos').addEventListener('click', e => { const r = e.target.closest('[data-tdr]'); if (r) { draft.todos.splice(+r.dataset.tdr, 1); renderComposer(); } });
$('#cp-todos').addEventListener('change', e => { const c = e.target.closest('[data-tdo]'); if (c) draft.todos[+c.dataset.tdo].done = c.checked; });
$('#cp-todos').addEventListener('input', e => { const t = e.target.closest('[data-tdt]'); if (t) draft.todos[+t.dataset.tdt].text = t.value; });
$('#cp-imgs').addEventListener('click', e => { const r = e.target.closest('[data-imr]'); if (r) { draft.images.splice(+r.dataset.imr, 1); renderComposer(); } });
$('#cp-files').addEventListener('click', e => { const r = e.target.closest('[data-flr]'); if (r) { draft.files.splice(+r.dataset.flr, 1); renderComposer(); } });
$('#cp-tags').addEventListener('click', e => { const r = e.target.closest('[data-tgr]'); if (r) { draft.tags.splice(+r.dataset.tgr, 1); renderComposer(); } });
$('#cp-cancel').onclick = () => newDraft();
$('#cp-del').onclick = async () => {
  if (!draft.id || !confirm('删除这条小记？')) return;
  try { await api('/api/notes/' + draft.id, { method: 'DELETE' }); toast('已删除'); newDraft(); loadFeed(); loadFeedTags(); refreshNoteCounts(); }
  catch (e) { toast(e.message, true); }
};
$('#cp-submit').onclick = async () => {
  const content = $('#cp-content').value.trim();
  draft.todos = draft.todos.filter(t => (t.text || '').trim() !== '');
  if (!content && !draft.images.length && !draft.files.length && !draft.todos.length) { toast('写点什么吧', true); return; }
  const fd = new FormData();
  fd.append('board', curNoteBoard);
  fd.append('content', content);
  fd.append('todos', JSON.stringify(draft.todos));
  fd.append('tags', JSON.stringify(draft.tags));
  draft.images.filter(i => i.kind === 'new').forEach(i => fd.append('images', i.fileObj, i.name || 'image.jpg'));
  draft.files.filter(i => i.kind === 'new').forEach(i => fd.append('attachments', i.fileObj, i.name || 'file'));
  $('#cp-submit').disabled = true;
  try {
    if (draft.id) {
      fd.append('keep_imgs', JSON.stringify(draft.images.filter(i => i.kind === 'old').map(i => i.file)));
      fd.append('keep_atts', JSON.stringify(draft.files.filter(i => i.kind === 'old').map(i => i.file)));
      await api('/api/notes/' + draft.id, { method: 'PUT', body: fd });
    } else {
      await api('/api/notes', { method: 'POST', body: fd });
    }
    toast('已保存'); newDraft(); loadFeed(); loadFeedTags(); refreshNoteCounts();
  } catch (e) { toast(e.message, true); }
  $('#cp-submit').disabled = false;
};

/* ---- 手机端：底部悬浮条 / 新建面板 / 全屏编辑器 ---- */
// 全屏编辑器顶栏：取消 / 删除 / 完成
$('#cp-mclose').onclick = () => newDraft();
$('#cp-msave').onclick = () => $('#cp-submit').click();
$('#cp-mdel').onclick = () => $('#cp-del').click();
// 底部悬浮条
$('#notes-pill').addEventListener('click', e => {
  const b = e.target.closest('[data-pill]'); if (!b) return;
  const p = b.dataset.pill;
  if (p === 'add') $('#note-sheet').classList.remove('hidden');
  else if (p === 'search') toggleNoteSearch();
  else if (p === 'ai') openAI();
});
// 新建小记面板
$('#note-sheet').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]')) { $('#note-sheet').classList.add('hidden'); return; }
  const b = e.target.closest('[data-new]'); if (!b) return;
  $('#note-sheet').classList.add('hidden');
  const m = b.dataset.new;
  if (m === 'ocr') { $('#ocr-file').click(); return; }
  newNoteM(m);
});
$('#ocr-file').addEventListener('change', async e => {
  const f = e.target.files[0]; e.target.value = ''; if (!f) return;
  toast('正在识别文字…');
  const fd = new FormData(); fd.append('file', f);
  try {
    const d = await api('/api/ocr', { method: 'POST', body: fd });
    newDraft();
    $('#cp-content').value = d.text || '';
    draft.content = d.text || '';
    openComposerM();
    toast(d.text ? '识别完成，可编辑后发布' : '没识别到文字，可手动输入', !d.text);
  } catch (err) { toast(err.message, true); }
});
function newNoteM(mode) {
  newDraft();
  openComposerM();
  if (mode === 'img') $('#cp-imgfile').click();
  else if (mode === 'cam') $('#cp-camfile').click();
  else if (mode === 'file') $('#cp-attfile').click();
  else if (mode === 'todo') { draft.todos.push({ text: '', done: false }); renderComposer(); }
}
// 手机端搜索
function toggleNoteSearch() {
  const box = $('#notes-msearch');
  box.classList.toggle('hidden');
  if (box.classList.contains('hidden')) {
    if (noteSearchQ) { noteSearchQ = ''; $('#notes-msearch-input').value = ''; loadFeed(); }
  } else {
    setTimeout(() => $('#notes-msearch-input').focus(), 50);
  }
}
let noteSearchTimer;
$('#notes-msearch-input').addEventListener('input', e => {
  clearTimeout(noteSearchTimer);
  noteSearchTimer = setTimeout(() => { noteSearchQ = e.target.value.trim(); loadFeed(); }, 200);
});

/* ---- 动态流 ---- */
async function loadFeedTags() {
  try {
    const d = await api('/api/notes/tags?board=' + encodeURIComponent(curNoteBoard));
    $('#feed-tags').innerHTML = d.tags.length
      ? `<button class="tagchip${curTag === '' ? ' active' : ''}" data-tag="">全部</button>` +
        d.tags.map(t => `<button class="tagchip${curTag === t ? ' active' : ''}" data-tag="${esc(t)}"># ${esc(t)}</button>`).join('')
      : '';
  } catch (_) {}
}
$('#feed-tags').addEventListener('click', e => {
  const c = e.target.closest('[data-tag]'); if (!c) return;
  curTag = c.dataset.tag;
  document.querySelectorAll('#feed-tags .tagchip').forEach(x => x.classList.toggle('active', x.dataset.tag === curTag));
  loadFeed();
});
async function loadFeed() {
  try {
    let url = '/api/notes?board=' + encodeURIComponent(curNoteBoard);
    if (curTag) url += '&tag=' + encodeURIComponent(curTag);
    const d = await api(url);
    const box = $('#feed');
    let items = d.items;
    if (noteSearchQ) {
      const q = noteSearchQ;
      items = items.filter(n => (n.content || '').includes(q)
        || (n.tags || []).some(t => t.includes(q))
        || (n.todos || []).some(t => (t.text || '').includes(q)));
    }
    if (!items.length) {
      box.innerHTML = ''; box._items = [];
      $('#feed-empty').classList.remove('hidden');
      $('#feed-empty').textContent = noteSearchQ ? '没有匹配「' + noteSearchQ + '」的小记'
        : (IS_MOBILE ? '还没有小记，点下面的 ＋ 写一条吧～' : '还没有小记，在左侧写一条吧～');
      return;
    }
    $('#feed-empty').classList.add('hidden');
    box.innerHTML = items.map(feedCard).join('');
    box._items = items;
  } catch (e) { toast(e.message, true); }
}
function feedCard(n) {
  const todos = n.todos.length ? `<div class="fc-todos">${n.todos.map((t, i) =>
    `<label class="fc-todo${t.done ? ' done' : ''}"><input type="checkbox" data-tg="${n.id}" data-ti="${i}" ${t.done ? 'checked' : ''}><span>${esc(t.text)}</span></label>`).join('')}</div>` : '';
  const imgs = n.images.length ? `<div class="fc-imgs">${n.images.map(u => `<img src="${u}" loading="lazy" data-img="${u}">`).join('')}</div>` : '';
  const files = n.attachments.length ? `<div class="fc-files">${n.attachments.map((a, i) =>
    `<button class="fc-file" data-file="${n.id}" data-fi="${i}" data-ext="${esc(a.ext)}" data-fview="${a.viewable ? 1 : 0}" data-fname="${esc(a.name)}">${IC.clip}${esc(a.name)}</button>`).join('')}</div>` : '';
  const tags = n.tags.length ? `<div class="fc-tags">${n.tags.map(t => `<span class="fc-tag"># ${esc(t)}</span>`).join('')}</div>` : '';
  return `<div class="feed-card" data-id="${n.id}">
    <div class="fc-time">更新于 ${fmtTime(n.updated_at)}
      <span class="fc-acts"><button class="fc-edit" data-edit="${n.id}" title="编辑">${IC.edit}</button><button class="fc-del" data-del="${n.id}" title="删除">${IC.del}</button></span>
    </div>
    ${n.content ? `<div class="fc-text">${esc(n.content)}</div>` : ''}
    ${todos}${imgs}${files}${tags}
  </div>`;
}
$('#feed').addEventListener('click', async e => {
  const box = $('#feed');
  const tg = e.target.closest('[data-tg]');
  if (tg) {
    try {
      await api('/api/notes/' + tg.dataset.tg + '/todo', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ idx: +tg.dataset.ti, done: tg.checked }) });
      tg.closest('.fc-todo').classList.toggle('done', tg.checked);
      const it = (box._items || []).find(x => x.id == tg.dataset.tg); if (it) it.todos[+tg.dataset.ti].done = tg.checked;
    } catch (err) { tg.checked = !tg.checked; toast(err.message, true); }
    return;
  }
  const ed = e.target.closest('[data-edit]');
  if (ed) { const it = (box._items || []).find(x => x.id == ed.dataset.edit); if (it) loadDraft(it); return; }
  const dl = e.target.closest('[data-del]');
  if (dl) {
    if (!confirm('删除这条小记？')) return;
    try { await api('/api/notes/' + dl.dataset.del, { method: 'DELETE' }); toast('已删除'); if (draft.id == dl.dataset.del) newDraft(); loadFeed(); loadFeedTags(); refreshNoteCounts(); }
    catch (err) { toast(err.message, true); } return;
  }
  const fl = e.target.closest('[data-file]');
  if (fl) {
    const base = '/api/notes/' + fl.dataset.file + '/file/' + fl.dataset.fi;
    if (fl.dataset.fview !== '1') { const a = document.createElement('a'); a.href = base + '?dl=1'; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); return; }
    const fe = (fl.dataset.ext || '').toLowerCase();
    const ftu = (fe === '.pdf' || OFFICE_EXT.includes(fe)) ? base + '/text' : null;
    openViewerUrl(base, fl.dataset.fname, fl.dataset.ext, base + '?dl=1', ftu); return;
  }
  const im = e.target.closest('[data-img]');
  if (im) { openViewerUrl(im.dataset.img, '图片', '.png'); return; }
});
/* 双击小记卡片即可编辑（除点到按钮/图片/附件/勾选） */
$('#feed').addEventListener('dblclick', e => {
  if (e.target.closest('button,a,input,[data-img],[data-file]')) return;
  const card = e.target.closest('.feed-card'); if (!card) return;
  const it = ($('#feed')._items || []).find(x => x.id == card.dataset.id);
  if (it) loadDraft(it);
});

/* ================= 资料库 ================= */
const EXT_ICON = {
  pdf: '📕', doc: '📘', docx: '📘', xls: '📗', xlsx: '📗', ppt: '📙', pptx: '📙',
  png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', webp: '🖼️', svg: '🖼️', bmp: '🖼️',
  html: '🌐', htm: '🌐', txt: '📄', md: '📄', csv: '📊', zip: '🗜️',
};
const iconFor = (ext) => EXT_ICON[(ext || '').replace('.', '')] || '📎';
const OFFICE_EXT = ['.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp', '.rtf'];
let matBoard = '';
function openMaterials() {
  matBoard = '';
  $('#mat-filter').innerHTML = `<button class="chip active" data-mb="">全部</button>` +
    ALL_BOARDS.map(b => `<button class="chip" data-mb="${esc(b)}">${esc(b)}</button>`).join('');
  push({ view: 'materials' });
  loadMaterials();
}
$('#mat-filter').addEventListener('click', e => {
  const c = e.target.closest('[data-mb]'); if (!c) return;
  matBoard = c.dataset.mb;
  document.querySelectorAll('#mat-filter .chip').forEach(x => x.classList.toggle('active', x.dataset.mb === matBoard));
  loadMaterials();
});
async function loadMaterials() {
  try {
    const d = await api('/api/materials' + (matBoard ? '?board=' + encodeURIComponent(matBoard) : ''));
    const box = $('#mat-list');
    if (!d.items.length) { box.innerHTML = ''; $('#mat-empty').classList.remove('hidden'); return; }
    $('#mat-empty').classList.add('hidden');
    box.innerHTML = d.items.map(m => `
      <div class="mat-item" data-id="${m.id}" data-view="${m.viewable ? 1 : 0}" data-ext="${esc(m.ext || '')}">
        <span class="mat-icon">${iconFor(m.ext)}</span>
        <div class="mat-info">
          <div class="mat-name">${esc(m.title || m.orig_name)}</div>
          <div class="mat-meta">${esc((m.ext || '').replace('.', '').toUpperCase())} · ${fmtSize(m.size)}${m.board ? ' · ' + esc(m.board) : ''}</div>
        </div>
        <div class="mat-actions">
          <button class="iconbtn" data-act="rename" title="重命名">✎</button>
          <button class="iconbtn" data-act="dup" title="复制一份">⧉</button>
          <button class="iconbtn" data-act="dl" title="下载">⬇</button>
          <button class="iconbtn" data-act="del" title="删除">🗑</button>
        </div>
      </div>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#mat-list').addEventListener('click', async e => {
  const item = e.target.closest('.mat-item'); if (!item) return;
  const id = item.dataset.id;
  const act = e.target.closest('[data-act]');
  if (act) {
    e.stopPropagation();
    if (act.dataset.act === 'dl') {
      const a = document.createElement('a'); a.href = '/api/materials/' + id + '/download'; a.download = '';
      document.body.appendChild(a); a.click(); a.remove();
    } else if (act.dataset.act === 'rename') {
      const cur = item.querySelector('.mat-name').textContent;
      const v = await kbPrompt('重命名文档', cur);
      if (v && v !== cur) {
        try { await api('/api/materials/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: v }) }); toast('已重命名'); loadMaterials(); }
        catch (err) { toast(err.message, true); }
      }
    } else if (act.dataset.act === 'dup') {
      try { await api('/api/materials/' + id + '/duplicate', { method: 'POST' }); toast('已复制一份'); loadMaterials(); }
      catch (err) { toast(err.message, true); }
    } else if (act.dataset.act === 'del') {
      if (!confirm('删除这个资料？')) return;
      try { await api('/api/materials/' + id, { method: 'DELETE' }); toast('已删除'); loadMaterials(); }
      catch (err) { toast(err.message, true); }
    }
    return;
  }
  if (item.dataset.view !== '1') { toast('该格式不支持预览，请下载查看', true); return; }
  openViewer(id, item.querySelector('.mat-name').textContent, item.dataset.ext);
});
const READER_EXT = ['.md', '.markdown', '.txt'];
let viewerTextUrl = null;
function openViewerUrl(fileUrl, name, ext, dlUrl, textUrl) {
  ext = (ext || '').toLowerCase();
  $('#viewer-name').textContent = name;
  $('#viewer-dl').href = dlUrl || fileUrl;
  viewerTextUrl = textUrl || null;
  push({ view: 'viewer', title: name });
  if (READER_EXT.includes(ext)) { $('#viewer-mode').classList.add('hidden'); openReader(fileUrl, ext); return; }
  // 原版预览（pdf.js / iframe）
  $('#viewer-reader').classList.add('hidden');
  $('#reader-tools').classList.add('hidden');
  $('#viewer-frame').classList.remove('hidden');
  $('#viewer-frame').src = (ext === '.pdf' || OFFICE_EXT.includes(ext))
    ? '/pdfjs/web/viewer.html?file=' + encodeURIComponent(fileUrl) : fileUrl;
  // pdf/office 且有文本接口 → 提供「阅读模式」切换
  const canRead = (ext === '.pdf' || OFFICE_EXT.includes(ext)) && viewerTextUrl;
  $('#viewer-mode').classList.toggle('hidden', !canRead);
  $('#viewer-mode').textContent = '阅读模式';
}
$('#viewer-mode').onclick = async () => {
  const reading = !$('#viewer-reader').classList.contains('hidden');
  if (reading) {
    $('#viewer-reader').classList.add('hidden');
    $('#reader-tools').classList.add('hidden');
    $('#viewer-frame').classList.remove('hidden');
    $('#viewer-mode').textContent = '阅读模式';
    return;
  }
  $('#viewer-frame').classList.add('hidden');
  $('#viewer-reader').classList.remove('hidden');
  $('#reader-tools').classList.remove('hidden');
  $('#viewer-mode').textContent = '原版';
  $('#viewer-reader').innerHTML = '<p class="reader-tip">提取文字中…</p>';
  applyReaderStyle();
  try {
    const d = await api(viewerTextUrl);
    const txt = (d && typeof d.text === 'string') ? d.text : '';
    $('#viewer-reader').innerHTML = txt.trim()
      ? '<pre class="reader-pre">' + esc(txt) + '</pre>'
      : '<p class="reader-tip">没提取到文字（可能是扫描/图片型 PDF，可用小记的 OCR 识图）</p>';
    $('#viewer-reader').scrollTop = 0;
  } catch (e) { $('#viewer-reader').innerHTML = '<p class="reader-tip">提取失败：' + esc(e.message) + '</p>'; }
};
/* ---- 阅读模式（md 渲染 / txt） ---- */
let readerFont = 17, readerSepia = false, readerSerif = false;
function applyReaderStyle() {
  const r = $('#viewer-reader');
  r.style.fontSize = readerFont + 'px';
  r.classList.toggle('sepia', readerSepia);
  r.classList.toggle('serif', readerSerif);
}
async function openReader(fileUrl, ext) {
  $('#viewer-frame').classList.add('hidden'); $('#viewer-frame').src = 'about:blank';
  $('#viewer-reader').classList.remove('hidden');
  $('#reader-tools').classList.remove('hidden');
  $('#viewer-reader').innerHTML = '<p class="reader-tip">加载中…</p>';
  applyReaderStyle();
  try {
    const r = await fetch(fileUrl);
    const txt = await r.text();
    $('#viewer-reader').innerHTML = (ext === '.txt')
      ? '<pre class="reader-pre">' + esc(txt) + '</pre>' : mdToHtml(txt);
    $('#viewer-reader').scrollTop = 0;
  } catch (e) { $('#viewer-reader').innerHTML = '<p class="reader-tip">加载失败，请下载查看</p>'; }
}
$('#rd-fontplus').onclick = () => { readerFont = Math.min(28, readerFont + 1); applyReaderStyle(); };
$('#rd-fontminus').onclick = () => { readerFont = Math.max(13, readerFont - 1); applyReaderStyle(); };
$('#rd-theme').onclick = () => { readerSepia = !readerSepia; applyReaderStyle(); };
$('#rd-serif').onclick = () => { readerSerif = !readerSerif; $('#rd-serif').textContent = readerSerif ? '黑体' : '宋体'; applyReaderStyle(); };
$('#rd-copy').onclick = async () => {
  const text = $('#viewer-reader').innerText || '';
  if (!text) { toast('没有可复制的内容', true); return; }
  try { await navigator.clipboard.writeText(text); toast('已复制全文'); return; } catch (_) { }
  const ta = document.createElement('textarea'); ta.value = text;
  ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); toast('已复制全文'); } catch (e) { toast('复制失败，请长按选择', true); }
  ta.remove();
};

/* 轻量 Markdown → HTML（标题/加粗/斜体/代码/引用/列表/分割线/链接/表格） */
function mdToHtml(src) {
  const E = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const inline = s => {
    s = E(s);
    s = s.replace(/`([^`]+)`/g, (m, c) => '<code>' + c + '</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/__([^_]+)__/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return s;
  };
  const lines = src.replace(/\r\n/g, '\n').split('\n');
  let html = '', inCode = false, codeBuf = [], listType = null, para = [], i = 0;
  const flushPara = () => { if (para.length) { html += '<p>' + inline(para.join(' ')) + '</p>'; para = []; } };
  const closeList = () => { if (listType) { html += '</' + listType + '>'; listType = null; } };
  for (i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = line.match(/^```(.*)$/);
    if (fence) {
      if (inCode) { html += '<pre class="md-code"><code>' + E(codeBuf.join('\n')) + '</code></pre>'; inCode = false; codeBuf = []; }
      else { flushPara(); closeList(); inCode = true; }
      continue;
    }
    if (inCode) { codeBuf.push(line); continue; }
    // 表格：| a | b | 后跟 |---|---|
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      flushPara(); closeList();
      const cells = r => r.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(c => c.trim());
      html += '<table class="md-table"><thead><tr>' + cells(line).map(c => '<th>' + inline(c) + '</th>').join('') + '</tr></thead><tbody>';
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        html += '<tr>' + cells(lines[i]).map(c => '<td>' + inline(c) + '</td>').join('') + '</tr>'; i++;
      }
      i--; html += '</tbody></table>';
      continue;
    }
    if (/^\s*$/.test(line)) { flushPara(); closeList(); continue; }
    let m;
    if (m = line.match(/^(#{1,6})\s+(.*)$/)) { flushPara(); closeList(); const lv = m[1].length; html += '<h' + lv + '>' + inline(m[2]) + '</h' + lv + '>'; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flushPara(); closeList(); html += '<hr>'; continue; }
    if (m = line.match(/^\s*>\s?(.*)$/)) { flushPara(); closeList(); html += '<blockquote>' + inline(m[1]) + '</blockquote>'; continue; }
    if (m = line.match(/^\s*[-*+]\s+(.*)$/)) { flushPara(); if (listType !== 'ul') { closeList(); html += '<ul>'; listType = 'ul'; } html += '<li>' + inline(m[1]) + '</li>'; continue; }
    if (m = line.match(/^\s*\d+[.)]\s+(.*)$/)) { flushPara(); if (listType !== 'ol') { closeList(); html += '<ol>'; listType = 'ol'; } html += '<li>' + inline(m[1]) + '</li>'; continue; }
    para.push(line.trim());
  }
  flushPara(); closeList();
  if (inCode) html += '<pre class="md-code"><code>' + E(codeBuf.join('\n')) + '</code></pre>';
  return html;
}
function openViewer(id, name, ext) {
  const e = (ext || '').toLowerCase();
  const textUrl = (e === '.pdf' || OFFICE_EXT.includes(e)) ? '/api/materials/' + id + '/text' : null;
  openViewerUrl('/api/materials/' + id + '/view', name, ext, '/api/materials/' + id + '/download', textUrl);
}
/* 上传资料 */
$('#upload-btn').onclick = () => {
  $('#up-board').innerHTML = `<option value="">未分类</option>` + ALL_BOARDS.map(b => `<option ${b === matBoard ? 'selected' : ''}>${esc(b)}</option>`).join('');
  $('#up-title').value = ''; $('#up-file').value = '';
  $('#upload-modal').classList.remove('hidden');
};
$('#up-cancel').onclick = () => $('#upload-modal').classList.add('hidden');
$('#upload-modal').addEventListener('click', e => { if (e.target.id === 'upload-modal') $('#upload-modal').classList.add('hidden'); });
$('#up-go').onclick = async () => {
  const files = [...$('#up-file').files];
  if (!files.length) { toast('请选择文件', true); return; }
  const board = $('#up-board').value, title = $('#up-title').value.trim();
  $('#up-go').disabled = true; $('#up-go').textContent = '上传中…';
  let ok = 0;
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('board', board);
    fd.append('section', '');
    fd.append('title', files.length === 1 ? title : '');  // 多个文件各用文件名
    try { await api('/api/materials', { method: 'POST', body: fd }); ok++; }
    catch (e) { toast(file.name + '：' + e.message, true); }
  }
  $('#up-go').disabled = false; $('#up-go').textContent = '上传';
  if (ok) { toast('上传成功 ' + ok + ' 个'); $('#upload-modal').classList.add('hidden'); loadMaterials(); }
};
/* 资料库拍照直接上传 */
$('#mat-camfile').addEventListener('change', async e => {
  const file = e.target.files[0]; e.target.value = '';
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  fd.append('board', matBoard);
  fd.append('section', '');
  fd.append('title', '拍照 ' + new Date().toLocaleString('zh-CN', { hour12: false }).slice(5, 16));
  toast('上传中…');
  try { await api('/api/materials', { method: 'POST', body: fd }); toast('已上传'); loadMaterials(); }
  catch (err) { toast(err.message, true); }
});

/* ================= 成语 / 词语 ================= */
let state = { filter: 'all', q: '', items: [], page: 1, pages: 1 };
let preview = null;
function openIdiom() {
  state = { filter: 'all', q: '', items: [], page: 1, pages: 1 };
  $('#word-input').value = ''; $('#preview').classList.add('hidden'); $('#search').value = ''; preview = null;
  document.querySelectorAll('#filters .chip').forEach(x => x.classList.toggle('active', x.dataset.f === 'all'));
  push({ view: 'idiom' });
  loadEntries();
}
async function doLookup() {
  const word = $('#word-input').value.trim();
  if (!word) { toast('请输入成语或词语', true); return; }
  $('#add-hint').textContent = '查询中…';
  try {
    const d = await api('/api/lookup?word=' + encodeURIComponent(word));
    preview = d;
    $('#pv-word').textContent = d.word; $('#pv-py').textContent = d.pinyin; $('#pv-cat').textContent = d.category;
    $('#pv-found').textContent = d.found ? (d.source === 'ai' ? '✓ AI 已解释并收录' : '✓ 词典已收录') : '✎ 词典未收录，可 AI 解释或手动补充';
    $('#pv-exp').value = d.explanation; $('#pv-der').value = d.derivation; $('#pv-exa').value = d.example;
    $('#pv-note').value = ''; $('#pv-catsel').value = d.category;
    $('#pv-der-wrap').classList.toggle('hidden', !d.derivation && d.source !== 'idiom');
    $('#pv-exa-wrap').classList.toggle('hidden', !d.example && d.source !== 'idiom');
    // AI 生成按钮始终显示：未解释过=「AI 解释并收录」，已解释过=「AI 重新生成」，均可反复点
    $('#pv-ai').classList.remove('hidden');
    $('#pv-ai').textContent = d.found ? '🤖 AI 重新生成' : '🤖 AI 解释并收录';
    $('#preview').classList.remove('hidden'); $('#add-hint').textContent = '';
  } catch (e) { $('#add-hint').textContent = ''; toast(e.message, true); }
}
async function doAiExplain() {
  if (!preview || !preview.word) return;
  const btn = $('#pv-ai');
  const regen = !!preview.found;  // 已解释过 → 本次是「重新生成」
  btn.disabled = true; btn.textContent = regen ? '🤖 重新生成中…' : '🤖 AI 解释中…';
  try {
    const d = await api('/api/lookup/ai', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ word: preview.word, category: $('#pv-catsel').value, force: true }),
    });
    preview.explanation = d.explanation; preview.pinyin = d.pinyin;
    preview.category = d.category; preview.found = true; preview.source = 'ai';
    preview.derivation = d.derivation || ''; preview.example = d.example || '';
    $('#pv-exp').value = d.explanation; $('#pv-py').textContent = d.pinyin;
    $('#pv-cat').textContent = d.category; $('#pv-catsel').value = d.category;
    $('#pv-der').value = d.derivation || ''; $('#pv-exa').value = d.example || '';
    $('#pv-der-wrap').classList.toggle('hidden', !d.derivation);
    $('#pv-exa-wrap').classList.toggle('hidden', !d.example);
    $('#pv-found').textContent = '✓ AI 已解释并收录';
    // 不隐藏按钮：不满意可反复重新生成
    toast(regen ? '已重新生成，不满意可再次点击' : '已解释并收录进词库，以后可直接查到');
    if (regen) loadEntries();  // 已收录的同名词条已被后端同步刷新，重载列表
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = (preview && preview.found) ? '🤖 AI 重新生成' : '🤖 AI 解释并收录'; }
}
async function doSave() {
  if (!preview) return;
  try {
    await api('/api/entries', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        word: preview.word, pinyin: $('#pv-py').textContent, category: $('#pv-catsel').value,
        explanation: $('#pv-exp').value, derivation: $('#pv-der').value, example: $('#pv-exa').value, note: $('#pv-note').value,
      }),
    });
    toast('已收录：' + preview.word);
    $('#word-input').value = ''; $('#preview').classList.add('hidden'); preview = null;
    state.page = 1; loadEntries(); $('#word-input').focus();
  } catch (e) { toast(e.message, true); }
}
async function loadEntries() {
  let url = '/api/entries?page=' + state.page + '&page_size=' + PAGE_SIZE + '&';
  if (state.filter === '成语' || state.filter === '词语' || state.filter === '词组') url += 'category=' + encodeURIComponent(state.filter) + '&';
  if (state.filter === 'star') url += 'starred=1&';
  if (state.q) url += 'q=' + encodeURIComponent(state.q);
  try {
    const d = await api(url);
    state.items = d.items; state.page = d.page; state.pages = d.pages;
    renderEntries(); renderPager(d.total);
  } catch (e) { toast(e.message, true); }
}
function renderEntries() {
  const box = $('#list');
  if (!state.items.length) {
    box.innerHTML = ''; $('#empty').classList.remove('hidden');
    $('#empty').textContent = (state.q || state.filter !== 'all') ? '没有符合条件的收录。' : '还没有收录，输入一个成语试试～';
    return;
  }
  $('#empty').classList.add('hidden');
  box.innerHTML = state.items.map(it => {
    const sub = [];
    if (it.derivation) sub.push(`<div class="item-sub"><b>出处</b> ${esc(it.derivation)}</div>`);
    if (it.example) sub.push(`<div class="item-sub"><b>例句</b> ${esc(it.example)}</div>`);
    return `<div class="item" data-id="${it.id}">
      <div class="item-actions">
        <button class="iconbtn star ${it.starred ? 'on' : ''}" data-act="star">${it.starred ? '★' : '☆'}</button>
        <button class="iconbtn" data-act="edit">✎</button><button class="iconbtn" data-act="del">🗑</button>
      </div>
      <div class="item-head"><span class="item-word">${esc(it.word)}</span>
        <span class="item-py">${esc(it.pinyin)}</span><span class="item-cat">${esc(it.category)}</span></div>
      ${it.explanation ? `<div class="item-exp">${esc(it.explanation)}</div>` : ''}
      ${sub.join('')}${it.note ? `<div class="item-note">📝 ${esc(it.note)}</div>` : ''}
    </div>`;
  }).join('');
}
function renderPager(total) {
  const pager = $('#pager');
  if (total <= PAGE_SIZE) { pager.classList.add('hidden'); return; }
  pager.classList.remove('hidden');
  $('#pg-info').textContent = `第 ${state.page} / ${state.pages} 页 · 共 ${total} 条`;
  $('#pg-prev').disabled = state.page <= 1; $('#pg-next').disabled = state.page >= state.pages;
}
function goPage(p) { if (p < 1 || p > state.pages || p === state.page) return; state.page = p; loadEntries(); window.scrollTo({ top: 0, behavior: 'smooth' }); }
// 应用内笔记编辑弹窗（替代原生 prompt），返回 Promise<string|null>（取消为 null）
function editNote(title, value) {
  return new Promise(resolve => {
    const modal = $('#note-modal'), input = $('#note-modal-input');
    $('#note-modal-title').textContent = title;
    input.value = value || '';
    modal.classList.remove('hidden');
    setTimeout(() => { input.focus(); }, 50);
    const done = (val) => {
      modal.classList.add('hidden');
      $('#note-modal-save').onclick = $('#note-modal-cancel').onclick = modal.onclick = null;
      resolve(val);
    };
    $('#note-modal-save').onclick = () => done(input.value);
    $('#note-modal-cancel').onclick = () => done(null);
    modal.onclick = (e) => { if (e.target === modal) done(null); };  // 点遮罩取消
  });
}
$('#list').addEventListener('click', async e => {
  const btn = e.target.closest('[data-act]'); if (!btn) return;
  const id = btn.closest('.item').dataset.id;
  const it = state.items.find(x => x.id == id);
  if (btn.dataset.act === 'star') {
    try { await api('/api/entries/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: !it.starred }) }); loadEntries(); } catch (err) { toast(err.message, true); }
  } else if (btn.dataset.act === 'del') {
    if (!confirm('删除「' + it.word + '」？')) return;
    try { await api('/api/entries/' + id, { method: 'DELETE' }); toast('已删除'); loadEntries(); } catch (err) { toast(err.message, true); }
  } else if (btn.dataset.act === 'edit') {
    const note = await editNote('「' + it.word + '」的笔记', it.note || '');
    if (note === null) return;
    try { await api('/api/entries/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }) }); toast('已保存'); loadEntries(); } catch (err) { toast(err.message, true); }
  }
});
$('#lookup-btn').onclick = doLookup;
$('#pv-ai').onclick = doAiExplain;
$('#word-input').addEventListener('keydown', e => { if (e.key === 'Enter') doLookup(); });
$('#save-btn').onclick = doSave;
$('#filters').addEventListener('click', e => {
  const c = e.target.closest('.chip'); if (!c) return;
  document.querySelectorAll('#filters .chip').forEach(x => x.classList.remove('active'));
  c.classList.add('active'); state.filter = c.dataset.f; state.page = 1; loadEntries();
});
let searchTimer;
$('#search').addEventListener('input', e => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.q = e.target.value.trim(); state.page = 1; loadEntries(); }, 250); });
$('#pg-prev').onclick = () => goPage(state.page - 1);
$('#pg-next').onclick = () => goPage(state.page + 1);
/* 导出 PDF */
$('#export-btn').onclick = () => $('#export-modal').classList.remove('hidden');
$('#ex-cancel').onclick = () => $('#export-modal').classList.add('hidden');
$('#export-modal').addEventListener('click', e => { if (e.target.id === 'export-modal') $('#export-modal').classList.add('hidden'); });
$('#ex-mode').addEventListener('change', e => { const r = e.target.value === 'recite'; $('#ex-fields').style.opacity = r ? .4 : 1; $('#ex-fields').style.pointerEvents = r ? 'none' : 'auto'; });
$('#ex-go').onclick = async () => {
  const scope = $('#ex-scope').value, mode = $('#ex-mode').value;
  const body = { mode, derivation: $('#ex-der').checked, example: $('#ex-exa').checked, note: $('#ex-note').checked };
  if (scope === '成语' || scope === '词语') body.category = scope;
  else if (scope === 'star') body.starred = true;
  else if (state.filter === '成语' || state.filter === '词语') body.category = state.filter;
  else if (state.filter === 'star') body.starred = true;
  if (IN_APP) {
    const p = new URLSearchParams();
    p.set('mode', body.mode); p.set('der', body.derivation ? 1 : 0); p.set('exa', body.example ? 1 : 0); p.set('note', body.note ? 1 : 0);
    if (body.category) p.set('category', body.category); if (body.starred) p.set('starred', 1);
    $('#export-modal').classList.add('hidden'); toast('正在导出 PDF…');
    window.location.href = '/api/export?' + p.toString(); return;
  }
  try {
    const r = await fetch('/api/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.error || '导出失败'); }
    const blob = await r.blob(); const cd = r.headers.get('content-disposition') || '';
    let name = '公考积累.pdf'; const m = cd.match(/filename\*=UTF-8''([^;]+)/); if (m) name = decodeURIComponent(m[1]);
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1500);
    $('#export-modal').classList.add('hidden'); toast('PDF 已生成');
  } catch (e) { toast(e.message, true); }
};

/* ================= 知识库（笔记本 + 文档块编辑器） ================= */
const ICON_CHEVRON = _svg('<polyline points="9 18 15 12 9 6"/>');
const ICON_FOLDER = _svg('<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>');
const ICON_DOCF = _svg('<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="14 3 14 9 20 9"/>');
const ICON_DOTS = _svg('<circle cx="12" cy="5" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="12" cy="19" r="1.4"/>');
const ICON_PLUS = _svg('<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>');
const ICON_TEXT = _svg('<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/>');
const ICON_LIST = _svg('<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/>');
const ICON_CHECKBOX = _svg('<path d="M9 11l2.5 2.5L16 8"/><rect x="3" y="3" width="18" height="18" rx="2.5"/>');
const ICON_QUOTE2 = _svg('<path d="M4 6h5v7H4z"/><path d="M15 6h5v7h-5z"/>');
const ICON_BULB = _svg('<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.7 10.7c.5.5.7 1 .7 1.8h6c0-.8.2-1.3.7-1.8A6 6 0 0 0 12 3z"/>');
const ICON_CODE = _svg('<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>');
const ICON_CHK = _svg('<polyline points="20 6 9 17 4 12"/>');
const KB_COVERS = [
  'linear-gradient(160deg,#3f73b3,#2b5894)', 'linear-gradient(160deg,#d3892f,#a9651b)',
  'linear-gradient(160deg,#c0473a,#982c22)', 'linear-gradient(160deg,#2f8060,#21614a)',
  'linear-gradient(160deg,#7a5ea8,#5b4589)', 'linear-gradient(160deg,#2c8c8c,#1f6e6e)',
  'linear-gradient(160deg,#b08a1e,#876900)', 'linear-gradient(160deg,#46566a,#2f3b48)',
];
const kbCoverInner = () => '<span class="kbc-band"></span><span class="kbc-ribbon"></span>';
const KB = { notebooks: [], nb: null, tree: [], openGroups: {} };
let DOC = null;

/* ---- 知识库列表 ---- */
async function openKb() { push({ view: 'kb' }); await loadNotebooks(); }
async function loadNotebooks() {
  try {
    const d = await api('/api/kb/notebooks');
    KB.notebooks = d.items;
    const box = $('#kb-list');
    if (!d.items.length) { box.innerHTML = ''; $('#kb-empty').classList.remove('hidden'); return; }
    $('#kb-empty').classList.add('hidden');
    box.innerHTML = d.items.map(nb => `
      <div class="kb-card" data-nb="${nb.id}">
        <div class="kb-cover" style="background:${KB_COVERS[(nb.cover || 0) % 8]}">${kbCoverInner()}</div>
        <div class="kb-card-name">${esc(nb.name)}</div>
        <div class="kb-card-sub">${nb.doc_count} 篇文档</div>
      </div>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#kb-list').addEventListener('click', e => {
  const c = e.target.closest('[data-nb]'); if (!c) return;
  openNotebook(+c.dataset.nb);
});

/* ---- 新建 / 编辑 知识库 ---- */
let nbEditId = null, nbCover = 0;
$('#kb-fab').onclick = () => openNbModal(null);
function openNbModal(nb) {
  nbEditId = nb ? nb.id : null;
  nbCover = nb ? (nb.cover || 0) : 0;
  $('#nb-modal-title').textContent = nb ? '知识库设置' : '新建知识库';
  $('#nb-in-name').value = nb ? nb.name : '';
  $('#nb-in-intro').value = nb ? nb.intro : '';
  $('#nb-cover-pick').innerHTML = KB_COVERS.map((g, i) =>
    `<div class="nb-cover-opt${i === nbCover ? ' sel' : ''}" data-cv="${i}" style="background:${g}"></div>`).join('');
  $('#nb-save').textContent = nb ? '保存' : '新建';
  $('#nb-del').classList.toggle('hidden', !nb);
  $('#nb-modal').classList.remove('hidden');
  if (!nb) setTimeout(() => $('#nb-in-name').focus(), 60);
}
$('#nb-cover-pick').addEventListener('click', e => {
  const c = e.target.closest('[data-cv]'); if (!c) return;
  nbCover = +c.dataset.cv;
  document.querySelectorAll('#nb-cover-pick .nb-cover-opt').forEach(x => x.classList.toggle('sel', +x.dataset.cv === nbCover));
});
$('#nb-cancel').onclick = () => $('#nb-modal').classList.add('hidden');
$('#nb-modal').addEventListener('click', e => { if (e.target.id === 'nb-modal') $('#nb-modal').classList.add('hidden'); });
$('#nb-save').onclick = async () => {
  const name = $('#nb-in-name').value.trim();
  if (!name) { toast('请填写知识库名称', true); return; }
  const intro = $('#nb-in-intro').value.trim();
  try {
    if (nbEditId) {
      await api('/api/kb/notebooks/' + nbEditId, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, intro, cover: nbCover }) });
      toast('已保存'); $('#nb-modal').classList.add('hidden');
      if (KB.nb && KB.nb.id === nbEditId) await loadNotebook(nbEditId);
      loadNotebooks();
    } else {
      const nb = await api('/api/kb/notebooks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, intro, cover: nbCover }) });
      toast('已创建'); $('#nb-modal').classList.add('hidden');
      openNotebook(nb.id);
    }
  } catch (e) { toast(e.message, true); }
};
$('#nb-del').onclick = async () => {
  if (!nbEditId) return;
  if (!confirm('删除整个知识库「' + $('#nb-in-name').value + '」？里面所有文档和分组都会删除，不可恢复！')) return;
  try {
    await api('/api/kb/notebooks/' + nbEditId, { method: 'DELETE' });
    toast('已删除'); $('#nb-modal').classList.add('hidden');
    if (stack[stack.length - 1].view === 'notebook') back();
    loadNotebooks();
  } catch (e) { toast(e.message, true); }
};

/* ---- 知识库详情（目录树） ---- */
async function openNotebook(id) { push({ view: 'notebook' }); await loadNotebook(id); }
async function loadNotebook(id) {
  try {
    const d = await api('/api/kb/notebooks/' + id);
    KB.nb = d.notebook; KB.tree = d.tree;
    renderNotebook();
  } catch (e) { toast(e.message, true); }
}
function renderNotebook() {
  const nb = KB.nb;
  $('#nb-cover').style.background = KB_COVERS[(nb.cover || 0) % 8];
  $('#nb-cover').innerHTML = kbCoverInner();
  $('#nb-name').textContent = nb.name;
  $('#nb-sub').textContent = (nb.intro ? nb.intro + ' · ' : '') + nb.doc_count + ' 篇文档';
  const top = stack[stack.length - 1];
  if (top && top.view === 'notebook') { top.title = nb.name; $('#top-title').textContent = nb.name; }
  renderTree();
}
function findNode(id) {
  let found = null;
  (function walk(ns) { ns.forEach(n => { if (n.id === id) found = n; if (n.children) walk(n.children); }); })(KB.tree);
  return found;
}
function renderTree() {
  const box = $('#nb-tree');
  if (!KB.tree.length) { box.innerHTML = ''; $('#nb-empty').classList.remove('hidden'); return; }
  $('#nb-empty').classList.add('hidden');
  let html = '';
  (function walk(nodes, depth) {
    nodes.forEach(n => {
      const isGroup = n.type === 'group';
      const open = !!KB.openGroups[n.id];
      html += `<div class="nb-node" data-node="${n.id}" data-type="${n.type}" style="padding-left:${6 + depth * 20}px">
        <span class="nb-twirl${isGroup ? (open ? ' open' : '') : ' leaf'}">${ICON_CHEVRON}</span>
        <span class="nb-nicon ${n.type}">${isGroup ? ICON_FOLDER : ICON_DOCF}</span>
        <span class="nb-ntitle">${esc(n.title || (isGroup ? '未命名分组' : '无标题文档'))}</span>
        <button class="nb-ndots" data-nodedots="${n.id}">${ICON_DOTS}</button>
      </div>`;
      if (isGroup && open && n.children.length) walk(n.children, depth + 1);
    });
  })(KB.tree, 0);
  box.innerHTML = html;
}
$('#nb-tree').addEventListener('click', e => {
  const dots = e.target.closest('[data-nodedots]');
  if (dots) { e.stopPropagation(); openNodeMenu(+dots.dataset.nodedots); return; }
  const row = e.target.closest('[data-node]'); if (!row) return;
  const id = +row.dataset.node;
  if (row.dataset.type === 'group') { KB.openGroups[id] = !KB.openGroups[id]; renderTree(); }
  else openDoc(id);
});

/* 底部悬浮条（知识库详情） */
$('#nb-pill').addEventListener('click', e => {
  const b = e.target.closest('[data-nbpill]'); if (!b) return;
  const p = b.dataset.nbpill;
  if (p === 'add') openKbSheet(null);
  else if (p === 'search') openSearch();
  else if (p === 'ai') openAI();
});

/* + 面板：新建 空白文档 / 知识库 / 分组 */
let kbSheetParent = null;
function openKbSheet(parentId) {
  kbSheetParent = parentId || null;
  $('#kb-sheet-title').textContent = parentId ? '在分组内新建' : '新建文档、知识库';
  $('#kb-sheet').classList.remove('hidden');
}
$('#kb-sheet').addEventListener('click', async e => {
  if (e.target.closest('[data-sheet-close]')) { $('#kb-sheet').classList.add('hidden'); return; }
  const b = e.target.closest('[data-kbnew]'); if (!b) return;
  $('#kb-sheet').classList.add('hidden');
  const t = b.dataset.kbnew;
  if (t === 'notebook') { openNbModal(null); return; }
  try {
    const node = await api('/api/kb/nodes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notebook_id: KB.nb.id, parent_id: kbSheetParent, type: t })
    });
    if (kbSheetParent) KB.openGroups[kbSheetParent] = true;
    await loadNotebook(KB.nb.id);
    if (t === 'doc') openDoc(node.id);
  } catch (e) { toast(e.message, true); }
});

/* 节点菜单：重命名 / 新建子项 / 删除 */
let nodeMenuId = null;
function openNodeMenu(id) {
  const n = findNode(id); if (!n) return;
  nodeMenuId = id;
  $('#node-menu-title').textContent = n.title || (n.type === 'group' ? '未命名分组' : '无标题文档');
  let html = `<button data-nm="rename"><span class="ci">${IC.edit}</span>重命名</button>`;
  if (n.type === 'group') html += `<button data-nm="add"><span class="ci">${ICON_PLUS}</span>在此分组内新建</button>`;
  if (n.type === 'doc') html += `<button data-nm="open"><span class="ci">${ICON_DOCF}</span>打开文档</button>`;
  html += `<button data-nm="del" style="color:#e0524d"><span class="ci">${IC.del}</span>删除</button>`;
  $('#node-menu-list').innerHTML = html;
  $('#node-menu').classList.remove('hidden');
}
$('#node-menu').addEventListener('click', async e => {
  if (e.target.closest('[data-sheet-close]')) { $('#node-menu').classList.add('hidden'); return; }
  const b = e.target.closest('[data-nm]'); if (!b) return;
  const act = b.dataset.nm, id = nodeMenuId, n = findNode(id);
  $('#node-menu').classList.add('hidden');
  if (!n) return;
  if (act === 'rename') {
    const v = await kbPrompt('重命名', n.title);
    if (v) { try { await api('/api/kb/nodes/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: v }) }); loadNotebook(KB.nb.id); } catch (e) { toast(e.message, true); } }
  } else if (act === 'add') { KB.openGroups[id] = true; openKbSheet(id); }
  else if (act === 'open') { openDoc(id); }
  else if (act === 'del') {
    if (!confirm('删除「' + (n.title || '该项') + '」' + (n.type === 'group' ? '及其下所有内容' : '') + '？不可恢复')) return;
    try { await api('/api/kb/nodes/' + id, { method: 'DELETE' }); toast('已删除'); loadNotebook(KB.nb.id); } catch (e) { toast(e.message, true); }
  }
});

/* 输入框（替代 prompt，兼容 WebView） */
let _kbpResolve = null;
function kbPrompt(title, value) {
  return new Promise(res => {
    _kbpResolve = res;
    $('#kbp-title').textContent = title;
    $('#kbp-input').value = value || '';
    $('#kb-prompt').classList.remove('hidden');
    setTimeout(() => { $('#kbp-input').focus(); $('#kbp-input').select(); }, 50);
  });
}
function kbpClose(v) { $('#kb-prompt').classList.add('hidden'); if (_kbpResolve) { _kbpResolve(v); _kbpResolve = null; } }
$('#kbp-cancel').onclick = () => kbpClose(null);
$('#kbp-ok').onclick = () => kbpClose($('#kbp-input').value.trim());
$('#kb-prompt').addEventListener('click', e => { if (e.target.id === 'kb-prompt') kbpClose(null); });
$('#kbp-input').addEventListener('keydown', e => { if (e.key === 'Enter') kbpClose($('#kbp-input').value.trim()); });
$('#nb-edit').onclick = () => { if (KB.nb) openNbModal(KB.nb); };

/* ============ 文档块编辑器 ============ */
const STATUS_OPTS = [
  { v: 'todo', label: '未开始', c: '#8a93a3', bg: '#eef0f3' },
  { v: 'doing', label: '进行中', c: '#1a6fb5', bg: '#e7f0fb' },
  { v: 'done', label: '已完成', c: '#1f9d57', bg: '#e4f6ec' },
  { v: 'hold', label: '搁置', c: '#d98324', bg: '#fdf0e1' },
];
const CONVERT_TYPES = [
  { t: 'text', label: '文本', icon: ICON_TEXT }, { t: 'h1', label: '标题 1', icon: 'H1' },
  { t: 'h2', label: '标题 2', icon: 'H2' }, { t: 'h3', label: '标题 3', icon: 'H3' },
  { t: 'list', label: '列表', icon: ICON_LIST }, { t: 'todo', label: '待办', icon: ICON_CHECKBOX },
  { t: 'quote', label: '引用', icon: ICON_QUOTE2 }, { t: 'callout', label: '高亮块', icon: ICON_BULB },
  { t: 'code', label: '代码块', icon: ICON_CODE },
];
const bid = () => 'b' + Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-3);
const newBlock = (type, data) => ({ id: bid(), type: type || 'text', text: '', data: data || {} });
function stripHtml(h) { const d = document.createElement('div'); d.innerHTML = h || ''; return (d.textContent || '').trim(); }
function normalizeBlocks(arr) {
  return (Array.isArray(arr) ? arr : []).map(b => ({ id: b.id || bid(), type: b.type || 'text', text: b.text || '', data: b.data || {} }));
}
function curB() { return DOC && DOC.blocks.find(x => x.id === DOC.curBlock); }

async function openDoc(id) {
  try {
    const d = await api('/api/kb/nodes/' + id);
    let blocks = normalizeBlocks(d.content);
    if (!blocks.length) blocks = [newBlock('text')];
    DOC = { id, blocks, curBlock: blocks[0].id, history: [], hist_i: -1 };
    push({ view: 'doc', title: d.title || '无标题文档' });
    $('#doc-title').textContent = (d.title && d.title !== '无标题文档') ? d.title : '';
    renderDoc();
    pushHistory();
    setTimeout(() => focusBlock(blocks[0].id), 70);
  } catch (e) { toast(e.message, true); }
}
function renderDoc() {
  $('#doc-blocks').innerHTML = DOC.blocks.map(blockHtml).join('');
}
function blockHtml(b) {
  const ind = b.data && b.data.indent ? ` style="margin-left:${b.data.indent * 22}px"` : '';
  const ce = 'contenteditable="true"';
  if (b.type === 'divider') return `<div class="blk divider" data-b="${b.id}" data-t="divider"${ind}><hr></div>`;
  if (b.type === 'image') return `<div class="blk image" data-b="${b.id}" data-t="image"${ind}>${b.data.url ? `<img src="${b.data.url}">` : ''}</div>`;
  if (b.type === 'file') {
    const d = b.data || {};
    return `<div class="blk file" data-b="${b.id}" data-t="file"${ind}>
      <div class="blk-file-card" data-fopen="${b.id}"><span class="bf-ic">${iconFor(d.ext)}</span>
      <span class="bf-name">${esc(d.name || '附件')}</span><span class="bf-meta">${d.size ? fmtSize(d.size) : ''}</span></div></div>`;
  }
  if (b.type === 'status') {
    const st = STATUS_OPTS.find(s => s.v === (b.data.value || 'todo')) || STATUS_OPTS[0];
    return `<div class="blk status" data-b="${b.id}" data-t="status"${ind}>
      <span class="blk-status-pill" data-status="${b.id}" style="color:${st.c};background:${st.bg}">${esc(st.label)}</span>
      <div class="blk-edit"></div></div>`;
  }
  if (b.type === 'table') {
    const rows = (b.data.rows && b.data.rows.length) ? b.data.rows : [['', ''], ['', '']];
    let t = `<div class="blk table" data-b="${b.id}" data-t="table"${ind}><table><tbody>`;
    rows.forEach((r, ri) => { t += '<tr>' + r.map((c, ci) => `<td contenteditable="true" data-tr="${ri}" data-tc="${ci}">${c || ''}</td>`).join('') + '</tr>'; });
    t += `</tbody></table><div class="tbl-tools"><button data-tbl="row" data-tid="${b.id}">＋行</button><button data-tbl="col" data-tid="${b.id}">＋列</button></div></div>`;
    return t;
  }
  if (b.type === 'todo') {
    return `<div class="blk todo${b.data.done ? ' done' : ''}" data-b="${b.id}" data-t="todo"${ind}>
      <span class="blk-chk${b.data.done ? ' on' : ''}" data-chk="${b.id}">${b.data.done ? ICON_CHK : ''}</span>
      <div class="blk-edit" ${ce} data-ph="待办事项">${b.text || ''}</div></div>`;
  }
  const cls = { text: 'text', h1: 'h1', h2: 'h2', h3: 'h3', quote: 'quote', callout: 'callout', code: 'code', list: 'list' }[b.type] || 'text';
  const ph = b.type === 'code' ? '输入代码…' : b.type === 'quote' ? '引用…' : b.type === 'callout' ? '高亮内容…'
    : b.type === 'list' ? '列表项…' : (/^h[123]$/.test(b.type) ? '标题' : '输入文本，或点下方 ＋ 插入');
  return `<div class="blk ${cls}" data-b="${b.id}" data-t="${b.type}"${ind}>
    <div class="blk-edit" ${ce} data-ph="${ph}">${b.text || ''}</div></div>`;
}

/* 输入同步 */
$('#doc-blocks').addEventListener('input', e => {
  if (!DOC) return;
  const td = e.target.closest('td[data-tr]');
  if (td) { const b = DOC.blocks.find(x => x.id === td.closest('[data-b]').dataset.b); if (b) { b.data.rows[+td.dataset.tr][+td.dataset.tc] = td.innerHTML; markDirty(); } return; }
  const edit = e.target.closest('.blk-edit'); if (!edit) return;
  const b = DOC.blocks.find(x => x.id === edit.closest('[data-b]').dataset.b);
  if (b) { b.text = edit.innerHTML; markDirty(); }
});
$('#doc-blocks').addEventListener('focusin', e => {
  const blk = e.target.closest('[data-b]'); if (blk && DOC) DOC.curBlock = blk.dataset.b;
});
$('#doc-blocks').addEventListener('click', e => {
  if (!DOC) return;
  const chk = e.target.closest('[data-chk]');
  if (chk) { const b = DOC.blocks.find(x => x.id === chk.dataset.chk); if (b) { b.data.done = !b.data.done; renderDoc(); markDirty(); } return; }
  const stp = e.target.closest('[data-status]');
  if (stp) { DOC.curBlock = stp.dataset.status; const b = DOC.blocks.find(x => x.id === stp.dataset.status); if (b) { const i = STATUS_OPTS.findIndex(s => s.v === (b.data.value || 'todo')); b.data.value = STATUS_OPTS[(i + 1) % STATUS_OPTS.length].v; renderDoc(); markDirty(); } return; }
  const tb = e.target.closest('[data-tbl]');
  if (tb) { const b = DOC.blocks.find(x => x.id === tb.dataset.tid); if (b) { if (tb.dataset.tbl === 'row') b.data.rows.push(b.data.rows[0].map(() => '')); else b.data.rows.forEach(r => r.push('')); renderDoc(); markDirty(); } return; }
  const fo = e.target.closest('[data-fopen]');
  if (fo) { const b = DOC.blocks.find(x => x.id === fo.dataset.fopen); if (b) openDocFile(b); return; }
  const blk = e.target.closest('[data-b]'); if (blk) DOC.curBlock = blk.dataset.b;
});
/* 回车分块 / 退格合并 */
$('#doc-blocks').addEventListener('keydown', e => {
  if (!DOC) return;
  const edit = e.target.closest('.blk-edit'); if (!edit) return;
  const blk = edit.closest('[data-b]'); const id = blk.dataset.b; const t = blk.dataset.t;
  const b = DOC.blocks.find(x => x.id === id); const idx = DOC.blocks.indexOf(b);
  if (e.key === 'Enter' && !e.shiftKey && t !== 'code') {
    e.preventDefault();
    if ((b.type === 'list' || b.type === 'todo') && stripHtml(b.text) === '') { b.type = 'text'; b.data = {}; renderDoc(); focusBlock(id); markDirty(); return; }
    const nt = (b.type === 'list' || b.type === 'todo') ? b.type : 'text';
    const nb = newBlock(nt); DOC.blocks.splice(idx + 1, 0, nb); DOC.curBlock = nb.id;
    renderDoc(); focusBlock(nb.id); markDirty();
  } else if (e.key === 'Backspace' && stripHtml(edit.innerHTML) === '' && DOC.blocks.length > 1) {
    e.preventDefault();
    DOC.blocks.splice(idx, 1);
    const prev = DOC.blocks[Math.max(0, idx - 1)];
    DOC.curBlock = prev.id; renderDoc(); if (prev) focusBlock(prev.id); markDirty();
  }
});

/* 标题 */
$('#doc-title').addEventListener('input', () => {
  if (!DOC) return; const t = $('#doc-title').textContent;
  stack[stack.length - 1].title = t || '无标题文档'; markDirty();
});
$('#doc-title').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); if (DOC && DOC.blocks[0]) focusBlock(DOC.blocks[0].id); } });

/* 光标定位 */
function focusBlock(id) {
  const el = document.querySelector(`[data-b="${id}"] .blk-edit[contenteditable]`);
  if (el) { el.focus(); const r = document.createRange(); r.selectNodeContents(el); r.collapse(false); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
}

/* 保存 / 历史 */
let docSaveTimer, docHistTimer;
function markDirty() {
  clearTimeout(docSaveTimer); docSaveTimer = setTimeout(saveDoc, 900);
  clearTimeout(docHistTimer); docHistTimer = setTimeout(pushHistory, 700);
}
async function saveDoc() {
  if (!DOC) return;
  const title = $('#doc-title').textContent.trim() || '无标题文档';
  try { await api('/api/kb/nodes/' + DOC.id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, content: DOC.blocks }) }); } catch (e) { }
}
function pushHistory() {
  if (!DOC) return;
  const snap = JSON.stringify({ title: $('#doc-title').textContent, blocks: DOC.blocks });
  if (DOC.history[DOC.hist_i] === snap) return;
  DOC.history = DOC.history.slice(0, DOC.hist_i + 1);
  DOC.history.push(snap);
  if (DOC.history.length > 60) DOC.history.shift();
  DOC.hist_i = DOC.history.length - 1;
  updateUndo();
}
function applyHistory() {
  const s = JSON.parse(DOC.history[DOC.hist_i]);
  DOC.blocks = normalizeBlocks(s.blocks); $('#doc-title').textContent = s.title;
  if (DOC.blocks[0]) DOC.curBlock = DOC.blocks[0].id;
  renderDoc(); updateUndo();
  clearTimeout(docSaveTimer); docSaveTimer = setTimeout(saveDoc, 500);
}
function updateUndo() {
  $('#doc-undo').disabled = !DOC || DOC.hist_i <= 0;
  $('#doc-redo').disabled = !DOC || DOC.hist_i >= DOC.history.length - 1;
}
$('#doc-undo').onclick = () => { if (DOC && DOC.hist_i > 0) { DOC.hist_i--; applyHistory(); } };
$('#doc-redo').onclick = () => { if (DOC && DOC.hist_i < DOC.history.length - 1) { DOC.hist_i++; applyHistory(); } };
$('#doc-outline').onclick = () => {
  const hs = DOC ? DOC.blocks.filter(b => /^h[123]$/.test(b.type)) : [];
  toast(hs.length ? ('共 ' + hs.length + ' 个标题') : '还没有标题，用「Aa」把某行设为标题');
};
$('#doc-done').onclick = async () => { await saveDoc(); back(); if (KB.nb) loadNotebook(KB.nb.id); };

/* 底部工具条 */
$('#doc-toolbar').addEventListener('click', e => {
  const b = e.target.closest('[data-tb]'); if (!b || !DOC) return;
  const t = b.dataset.tb;
  if (t === 'insert') $('#blk-insert').classList.remove('hidden');
  else if (t === 'style') openStyleSheet();
  else if (t === 'bold') { document.execCommand('bold'); const cb = curB(); const el = document.querySelector(`[data-b="${DOC.curBlock}"] .blk-edit`); if (cb && el) { cb.text = el.innerHTML; markDirty(); } }
  else if (t === 'list') toggleBlockType('list');
  else if (t === 'todo') toggleBlockType('todo');
  else if (t === 'more') openBlkMenu();
  else if (t === 'kbd') { if (document.activeElement) document.activeElement.blur(); }
});
function toggleBlockType(type) {
  const b = curB(); if (!b) return;
  b.type = (b.type === type) ? 'text' : type;
  if (b.type === 'todo') b.data.done = b.data.done || false;
  renderDoc(); focusBlock(b.id); markDirty();
}

/* 块菜单（图四） */
function hiliteCur(on) {
  document.querySelectorAll('.blk.sel').forEach(x => x.classList.remove('sel'));
  if (on && DOC) { const el = document.querySelector(`[data-b="${DOC.curBlock}"]`); if (el) el.classList.add('sel'); }
}
function openBlkMenu() {
  if (!DOC.curBlock && DOC.blocks.length) DOC.curBlock = DOC.blocks[DOC.blocks.length - 1].id;
  hiliteCur(true);
  $('#blk-menu').classList.remove('hidden');
}
$('#blk-menu').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]')) { $('#blk-menu').classList.add('hidden'); hiliteCur(false); return; }
  const b = e.target.closest('[data-blkact]'); if (!b) return;
  $('#blk-menu').classList.add('hidden'); hiliteCur(false);
  blkAction(b.dataset.blkact);
});
function blkAction(act) {
  const b = curB(); if (!b) return; const idx = DOC.blocks.indexOf(b);
  if (act === 'convert') { openConvert(); return; }
  if (act === 'addbelow') { $('#blk-insert').classList.remove('hidden'); return; }
  if (act === 'copy') { const c = JSON.parse(JSON.stringify(b)); c.id = bid(); DOC.blocks.splice(idx + 1, 0, c); renderDoc(); markDirty(); toast('已复制到下方'); }
  else if (act === 'cut') { if (DOC.blocks.length > 1) DOC.blocks.splice(idx, 1); else DOC.blocks[0] = newBlock('text'); DOC.curBlock = DOC.blocks[Math.max(0, idx - 1)].id; renderDoc(); markDirty(); toast('已剪切'); }
  else if (act === 'indent') { b.data.indent = Math.min(4, (b.data.indent || 0) + 1); renderDoc(); markDirty(); }
  else if (act === 'outdent') { b.data.indent = Math.max(0, (b.data.indent || 0) - 1); renderDoc(); markDirty(); }
  else if (act === 'del') { if (DOC.blocks.length > 1) DOC.blocks.splice(idx, 1); else DOC.blocks[0] = newBlock('text'); DOC.curBlock = DOC.blocks[Math.max(0, idx - 1)].id; renderDoc(); markDirty(); }
}

/* 转换 / 文字样式 */
function openConvert() {
  $('#blk-conv-list').innerHTML = CONVERT_TYPES.map(c => {
    const ic = (typeof c.icon === 'string' && c.icon.length <= 2) ? `<b>${c.icon}</b>` : c.icon;
    return `<button data-conv="${c.t}"><span class="ci">${ic}</span>${c.label}</button>`;
  }).join('');
  $('#blk-convert').classList.remove('hidden');
}
$('#blk-convert').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]')) { $('#blk-convert').classList.add('hidden'); return; }
  const b = e.target.closest('[data-conv]'); if (!b) return;
  $('#blk-convert').classList.add('hidden');
  const blk = curB(); if (!blk) return;
  blk.type = b.dataset.conv; if (blk.type === 'todo') blk.data.done = blk.data.done || false;
  renderDoc(); focusBlock(blk.id); markDirty();
});
function openStyleSheet() {
  const opts = [['text', '正文'], ['h1', '标题 1'], ['h2', '标题 2'], ['h3', '标题 3']];
  $('#blk-style-list').innerHTML = opts.map(o => `<button data-style="${o[0]}">${o[1]}</button>`).join('');
  $('#blk-style').classList.remove('hidden');
}
$('#blk-style').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]')) { $('#blk-style').classList.add('hidden'); return; }
  const b = e.target.closest('[data-style]'); if (!b) return;
  $('#blk-style').classList.add('hidden');
  const blk = curB(); if (!blk) return;
  blk.type = b.dataset.style; renderDoc(); focusBlock(blk.id); markDirty();
});

/* 插入面板（图五） */
$('#blk-insert').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]')) { $('#blk-insert').classList.add('hidden'); return; }
  const b = e.target.closest('[data-ins]'); if (!b) return;
  $('#blk-insert').classList.add('hidden');
  doInsert(b.dataset.ins);
});
function insertAfterCur(blk) {
  let idx = DOC.blocks.findIndex(x => x.id === DOC.curBlock);
  if (idx < 0) idx = DOC.blocks.length - 1;
  DOC.blocks.splice(idx + 1, 0, blk); DOC.curBlock = blk.id;
  renderDoc();
  if (!['divider', 'image', 'file', 'status'].includes(blk.type)) focusBlock(blk.id);
  markDirty();
}
function doInsert(kind) {
  if (kind === 'image') { $('#doc-imgfile').click(); return; }
  if (kind === 'camera') { $('#doc-camfile').click(); return; }
  if (kind === 'file') { $('#doc-attfile').click(); return; }
  let blk;
  if (kind === 'table') blk = newBlock('table', { rows: [['', ''], ['', '']] });
  else if (kind === 'status') blk = newBlock('status', { value: 'todo' });
  else blk = newBlock(kind);   // text/callout/quote/divider/code
  insertAfterCur(blk);
}
async function uploadDocAsset(file, preferImage) {
  const fd = new FormData(); fd.append('file', file);
  toast('上传中…');
  const d = await api('/api/kb/upload', { method: 'POST', body: fd });
  const blk = (preferImage && d.is_image)
    ? newBlock('image', { stored: d.stored, url: d.url, name: d.name })
    : newBlock('file', { stored: d.stored, name: d.name, ext: d.ext, size: d.size, url: d.url, viewable: d.viewable });
  insertAfterCur(blk); toast('已插入');
}
$('#doc-imgfile').addEventListener('change', async e => { const f = e.target.files[0]; e.target.value = ''; if (f) try { await uploadDocAsset(f, true); } catch (err) { toast(err.message, true); } });
$('#doc-camfile').addEventListener('change', async e => { const f = e.target.files[0]; e.target.value = ''; if (f) try { await uploadDocAsset(f, true); } catch (err) { toast(err.message, true); } });
$('#doc-attfile').addEventListener('change', async e => { const f = e.target.files[0]; e.target.value = ''; if (f) try { await uploadDocAsset(f, false); } catch (err) { toast(err.message, true); } });
function openDocFile(b) {
  const d = b.data || {};
  if (!d.viewable) { const a = document.createElement('a'); a.href = d.url + '?dl=1'; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); return; }
  const e = (d.ext || '').toLowerCase();
  const tu = (e === '.pdf' || OFFICE_EXT.includes(e)) ? d.url + '?text=1' : null;
  openViewerUrl(d.url, d.name, d.ext, d.url + '?dl=1', tu);
}

/* ================= 古诗文速查（唐诗宋词·四书五经） ================= */
const CLS_BADGE = { '唐诗': '#c0392b', '宋词': '#7b5ea7', '元曲': '#2c8c8c', '诗经': '#2f8060', '先秦': '#b08a1e', '汉魏六朝': '#8a6d3b', '明清': '#4a6785', '论语': '#1a6fb5', '孟子': '#1a6fb5', '大学': '#b08a1e', '中庸': '#b08a1e', '孙子兵法': '#9b2c22', '资治通鉴': '#5a4b8a', '增广贤文': '#2c7a5a' };
let clsState = { cat: '', q: '', star: false, page: 1, pages: 1 };
function openClassics() {
  clsState = { cat: '', q: '', star: false, page: 1, pages: 1 };
  $('#cls-input').value = '';
  push({ view: 'classics' });
  loadClsCats(); loadClassics();
}
async function loadClsCats() {
  try {
    const d = await api('/api/classics/categories');
    $('#cls-cats').innerHTML =
      `<button class="chip active" data-cc="">全部</button>` +
      `<button class="chip" data-cc="__star">★ 收藏${d.star_count ? ' ' + d.star_count : ''}</button>` +
      d.categories.map(c => `<button class="chip" data-cc="${esc(c.name)}">${esc(c.name)} ${c.count}</button>`).join('');
  } catch (e) { toast(e.message, true); }
}
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
let aiMsgs = [], aiBusy = false;
async function openAI(preset) {
  $('#ai-panel').classList.remove('hidden');
  if (!aiMsgs.length) {
    let greet = '我是你的公考 AI 助手 👋 让我讲知识点、出题、翻译古文、分析错题都行。';
    try {
      const s = await api('/api/ai/status');
      if (!s.configured) {
        greet = ME && ME.is_admin
          ? '⚠️ AI 还没配置。请到「后台 → AI 设置」填写 DeepSeek 的 API Key（在 platform.deepseek.com 申请）。'
          : '⚠️ AI 还没配置，请让管理员在后台填写 API Key。';
      }
    } catch (_) { }
    aiMsgs.push({ role: 'assistant', content: greet });
    renderAI();
  }
  if (preset) { $('#ai-text').value = preset; aiGrow(); }
  setTimeout(() => $('#ai-text').focus(), 60);
}
function renderAI() {
  $('#ai-msgs').innerHTML = aiMsgs.map(m =>
    `<div class="ai-msg ${m.role}">${m.role === 'assistant' ? mdToHtml(m.content) : esc(m.content)}</div>`).join('')
    + (aiBusy ? '<div class="ai-msg assistant ai-typing">思考中…</div>' : '');
  const box = $('#ai-msgs'); box.scrollTop = box.scrollHeight;
  $('#ai-send').disabled = aiBusy;
}
async function aiSend() {
  const t = $('#ai-text').value.trim();
  if (!t || aiBusy) return;
  aiMsgs.push({ role: 'user', content: t });
  $('#ai-text').value = ''; aiGrow();
  aiBusy = true; renderAI();
  try {
    const d = await api('/api/ai/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: aiMsgs.slice(-12) })
    });
    aiMsgs.push({ role: 'assistant', content: d.reply || '（空回复）' });
  } catch (e) {
    aiMsgs.push({ role: 'assistant', content: '⚠️ ' + e.message });
  }
  aiBusy = false; renderAI();
}
function aiGrow() { const t = $('#ai-text'); t.style.height = 'auto'; t.style.height = Math.min(120, t.scrollHeight) + 'px'; }
$('#ai-send').onclick = aiSend;
$('#ai-close').onclick = () => $('#ai-panel').classList.add('hidden');
$('#ai-clear').onclick = () => { aiMsgs = []; renderAI(); openAI(); };
$('#ai-text').addEventListener('input', aiGrow);
$('#ai-text').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); aiSend(); } });

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
    searchData.results = d.results;
    renderSearch();
  } catch (e) { toast(e.message, true); }
}
function hl(text, q) {
  const t = esc(text || '');
  if (!q) return t;
  try { return t.replace(new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'), '<mark>$1</mark>'); }
  catch (_) { return t; }
}
const SR_TYPE = { note: '小记', material: '资料', doc: '知识库', wrongq: '错题', boardkb: '基础知识' };
function renderSearch() {
  const box = $('#search-results');
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
        : (r.type === 'wrongq' || r.type === 'boardkb') ? (r.board ? esc(r.board) : '')
          : (r.tags && r.tags.length ? r.tags.map(t => '#' + esc(t)).join(' ') : (r.board ? esc(r.board) : ''));
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
  if (r.type === 'material') {
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
    if (!confirm('删除这道错题？')) return;
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
  if (!confirm('退出登录？')) return;
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

/* ============= 每日时政（爬虫 + AI 三行式；国内/四川/国际 三板块，全局共享） ============= */
let newsBoard = '党内', newsDate = '';
function fmtDay(iso) {
  const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(iso || '');
  return m ? (+m[1]) + '月' + (+m[2]) + '日' : (iso || '');
}
function renderDateStrip(el, dates, cur, attr) {
  el.innerHTML = (dates || []).map(d =>
    `<button class="chip ${d.date === cur ? 'active' : ''}" data-${attr}="${esc(d.date)}">${fmtDay(d.date)} ${d.count}</button>`).join('');
}
async function loadNews() {
  const starMode = newsBoard === '收藏';
  document.querySelectorAll('#news-boards .chip').forEach(x => x.classList.toggle('active', x.dataset.nb === newsBoard));
  $('#news-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api(starMode ? '/api/news?star=1'
      : '/api/news?board=' + encodeURIComponent(newsBoard) + '&date=' + encodeURIComponent(newsDate));
    if (d.counts) document.querySelectorAll('#news-boards .chip').forEach(x => {
      if (x.dataset.nb === '收藏') { x.textContent = '⭐ 收藏' + (d.star_total ? ' ' + d.star_total : ''); return; }
      const n = d.counts[x.dataset.nb]; x.textContent = x.dataset.nb + (n ? ' ' + n : '');
    });
    newsDate = d.date || '';
    renderDateStrip($('#news-dates'), d.dates, newsDate, 'nd');
    $('#news-dates').classList.toggle('hidden', starMode);
    if (!d.items.length) {
      $('#news-list').innerHTML = '<p class="empty">' + (starMode ? '还没有收藏，点新闻卡右上角的 ☆ 收藏。' : '这一天该板块没有时政，点上面换一天看看～') + '</p>';
      return;
    }
    $('#news-list').innerHTML = d.items.map(it => {
      const sum = (it.ai_summary || '').trim();
      return `<div class="poly-card news-card" data-news="${it.id}">
        <button class="news-star ${it.starred ? 'on' : ''}" data-nstar="${it.id}">${it.starred ? '★' : '☆'}</button>
        <div class="news-date">🗓 ${esc(it.pub_date || '')} · ${esc(it.source || '')}</div>
        <div class="poly-t" style="font-size:16px;padding-right:34px;">${esc(it.title)}</div>
        ${sum ? `<div class="news-sum" style="white-space:pre-wrap">${esc(sum)}</div>` : ''}
      </div>`;
    }).join('');
  } catch (e) { $('#news-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function openNews() { newsDate = ''; push({ view: 'news', title: '每日时政' }); loadNews(); }
$('#news-boards').addEventListener('click', e => {
  const c = e.target.closest('[data-nb]'); if (!c) return;
  newsBoard = c.dataset.nb; newsDate = ''; loadNews();
});
$('#news-dates').addEventListener('click', e => {
  const c = e.target.closest('[data-nd]'); if (!c) return;
  newsDate = c.dataset.nd; loadNews();
});
$('#news-list').addEventListener('click', async e => {
  const st = e.target.closest('[data-nstar]');
  if (st) {
    e.stopPropagation();
    const on = !st.classList.contains('on');
    try {
      await api('/api/news/' + st.dataset.nstar + '/star', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: on }) });
      st.classList.toggle('on', on); st.textContent = on ? '★' : '☆';
      if (newsBoard === '收藏' && !on) loadNews();
      else toast(on ? '已收藏' : '已取消收藏');
    } catch (err) { toast(err.message, true); }
    return;
  }
  const c = e.target.closest('[data-news]'); if (c) openNewsItem(+c.dataset.news);
});
async function openNewsItem(id) {
  push({ view: 'newsd', title: '时政详情' });
  $('#news-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/news/' + id);
    stack[stack.length - 1].title = d.title; $('#top-title').textContent = d.title;
    const body = (d.content || '').split('\n').filter(x => x.trim()).map(p => {
      const s = p.trim();
      return isDocHeading(s) ? `<p class="poly-h">${emKey(s)}</p>` : `<p>${emKey(s)}</p>`;
    }).join('');
    const ai = d.ai_summary
      ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">🤖 AI 摘要 · 考点</div><div class="cd-sec-b">${mdToHtml(d.ai_summary)}</div></div>` : '';
    $('#news-wrap').innerHTML = `
      <div class="poly-head"><h2>${esc(d.title)}</h2>
        <div class="news-date">🗓 ${esc(d.pub_date || '')} · ${esc(d.source || '')}</div>
        <a class="poly-src" href="${esc(d.url)}" target="_blank" rel="noopener">原文来源 ↗</a></div>
      ${ai}
      <div class="poly-readert">全文</div>
      <div class="poly-reader">${body}</div>`;
  } catch (e) { $('#news-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}

/* ============= 申论 · 概括句积累（每日由时政生成，按日期查看） ============= */
let gkDate = '';
async function loadGaikuo() {
  $('#gk-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/gaikuo?date=' + encodeURIComponent(gkDate));
    gkDate = d.date || '';
    renderDateStrip($('#gk-dates'), d.dates, gkDate, 'gd');
    if (!d.items.length) { $('#gk-list').innerHTML = '<p class="empty">还没有概括句，每天早上会自动从当日时政生成～</p>'; return; }
    $('#gk-list').innerHTML = d.items.map((it, i) => `
      <div class="gk-card">
        <div class="gk-head"><span class="gk-no">${i + 1}</span><span class="gk-topic">${esc(it.topic)}</span></div>
        ${it.raw ? `<div class="gk-raw"><span class="gk-lab">材料</span>${esc(it.raw)}</div>` : ''}
        <div class="gk-sent"><span class="gk-lab gk-lab-s">概括</span><b>${esc(it.sentence)}</b></div>
        ${it.tip ? `<div class="gk-tip">💡 ${esc(it.tip)}</div>` : ''}
      </div>`).join('');
  } catch (e) { $('#gk-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function openGaikuo() { gkDate = ''; push({ view: 'gaikuo', title: '概括句积累' }); loadGaikuo(); }
$('#gk-dates').addEventListener('click', e => {
  const c = e.target.closest('[data-gd]'); if (!c) return;
  gkDate = c.dataset.gd; loadGaikuo();
});

/* ============= 议论文 · 素材积累 / 衔接表达（与微信 08:00 推送同源） ============= */
let scKind = '全部';
const SC_COLOR = { '人物事例': '#b23b2e', '具体事例': '#0f766e', '理论论据': '#7a5cc0', '衔接表达': '#c2671f' };
async function loadSucai() {
  document.querySelectorAll('#sc-kinds .chip').forEach(x => x.classList.toggle('active', x.dataset.sk === scKind));
  $('#sc-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/sucai?kind=' + encodeURIComponent(scKind));
    document.querySelectorAll('#sc-kinds .chip').forEach(x => {
      if (x.dataset.sk === '全部') return;
      const n = d.counts[x.dataset.sk]; x.textContent = x.dataset.sk + (n ? ' ' + n : '');
    });
    if (!d.items.length) { $('#sc-list').innerHTML = '<p class="empty">还没有素材，每天 08:00 自动生成～</p>'; return; }
    let lastDate = '';
    $('#sc-list').innerHTML = d.items.map(it => {
      const head = it.date !== lastDate ? `<div class="sc-day">🗓 ${fmtDay(it.date)}</div>` : '';
      lastDate = it.date;
      const col = SC_COLOR[it.kind] || '#666';
      return head + `<div class="gk-card">
        <div class="gk-head"><span class="poly-badge" style="background:${col}">${esc(it.kind)}</span>
          ${it.topic ? `<span class="gk-topic">${esc(it.topic)}</span>` : ''}</div>
        <div class="sc-body">${emKey(it.content)}</div>
      </div>`;
    }).join('');
  } catch (e) { $('#sc-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function openSucai(kind) {
  scKind = kind || '全部';
  push({ view: 'sucai', title: scKind === '衔接表达' ? '衔接表达' : '素材积累' });
  loadSucai();
}
$('#sc-kinds').addEventListener('click', e => {
  const c = e.target.closest('[data-sk]'); if (!c) return;
  scKind = c.dataset.sk; loadSucai();
});

/* ============= 今日复习（艾宾浩斯遗忘曲线） ============= */
const RV_KIND = { entry: '成语词语', wrongq: '错题', classic: '古诗文' };
const RV_COLOR = { entry: '#2b6fd6', wrongq: '#b23b2e', classic: '#0f766e' };
async function loadReview() {
  $('#rv-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/review/today');
    if (!d.items.length) {
      $('#rv-summary').classList.add('hidden');
      $('#rv-list').innerHTML = '<p class="empty">🎉 今天没有要复习的内容。收录的成语/错题/收藏古诗文会按遗忘曲线自动出现在这里。</p>';
      refreshReviewBadge();
      return;
    }
    $('#rv-summary').classList.remove('hidden');
    $('#rv-summary').textContent = `今天要复习 ${d.count} 条 · 复习完点「✓ 记住了」进入下一轮`;
    $('#rv-list').innerHTML = d.items.map(it => `
      <div class="gk-card rv-item" data-rvk="${it.kind}" data-rvid="${it.id}">
        <div class="gk-head">
          <span class="poly-badge" style="background:${RV_COLOR[it.kind] || '#666'}">${RV_KIND[it.kind] || it.kind}</span>
          <span class="gk-topic">${esc(it.title)}</span>
          <span class="rv-stage">第 ${it.stage + 1} 轮</span>
        </div>
        ${it.sub ? `<div class="rv-sub">${esc(it.sub)}</div>` : ''}
        ${it.body ? `<div class="sc-body rv-body">${esc(it.body)}…</div>` : ''}
        <button class="btn rv-done" data-rvdone="1">✓ 记住了</button>
      </div>`).join('');
  } catch (e) { $('#rv-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function openReview() { push({ view: 'review', title: '今日复习' }); loadReview(); }
$('#rv-list').addEventListener('click', async e => {
  const btn = e.target.closest('[data-rvdone]'); if (!btn) return;
  const card = btn.closest('.rv-item'); if (!card) return;
  btn.disabled = true;
  try {
    const d = await api('/api/review/done', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: card.dataset.rvk, id: +card.dataset.rvid }) });
    card.style.opacity = '.35'; btn.textContent = `✓ ${d.interval} 天后再见`;
    refreshReviewBadge();
  } catch (err) { toast(err.message, true); btn.disabled = false; }
});

/* ================= 时政要文库（重要文件全文 + AI 政策解读） ================= */
let polyData = null;
const POLY_COLOR = { '重要讲话': '#c81e1e', '党代会报告': '#b23b2e', '中央全会文件': '#8c2f24', '政府工作报告': '#2b6fd6', '中央一号文件': '#0f766e', '地方政府工作报告': '#7a5cc0', '五年规划': '#c2671f' };
async function openPolicyDocs() {
  push({ view: 'policydoc', title: '时政要文库' });
  $('#poly-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/policydocs');
    $('#poly-list').innerHTML = d.items.map(it => {
      const col = POLY_COLOR[it.category] || '#666';
      return `<div class="poly-card" data-poly="${it.id}">
        <span class="poly-badge" style="background:${col}">${esc(it.category)}</span>
        <div class="poly-t">${esc(it.title)}</div>
        <div class="poly-meta">全文约 ${(it.chars / 1000).toFixed(1)} 千字${it.has_ai ? ' · <span class="poly-ai-on">✓ 已有 AI 解读</span>' : ''}</div>
      </div>`;
    }).join('');
  } catch (e) { $('#poly-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#poly-list').addEventListener('click', e => {
  const c = e.target.closest('[data-poly]'); if (c) openPolicyDoc(+c.dataset.poly);
});
async function openPolicyDoc(id) {
  push({ view: 'policydocd', title: '要文精读' });
  $('#poly-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/policydocs/' + id); polyData = d;
    stack[stack.length - 1].title = d.title; $('#top-title').textContent = d.title;
    renderPolicyDoc();
  } catch (e) { $('#poly-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderPolicyDoc() {
  const d = polyData;
  const ai = d.interpretation
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">🤖 AI 政策解读</div><div class="cd-sec-b">${mdToHtml(d.interpretation)}</div>
        <button class="btn cd-ai-regen" id="poly-regen">重新生成</button></div>`
    : `<div class="poly-genbox"><p class="cd-tip" style="margin:0 0 10px">让 AI 提炼这份文件的核心要点、公考高频考点、可引用金句与答题运用。</p>
        <button class="btn primary" id="poly-gen" style="width:100%;padding:12px;">🤖 生成 AI 政策解读</button></div>`;
  const body = (d.content || '').split('\n').filter(x => x.trim()).map(p => {
    const s = p.trim();
    return isDocHeading(s) ? `<p class="poly-h">${emKey(s)}</p>` : `<p>${emKey(s)}</p>`;
  }).join('');
  $('#poly-wrap').innerHTML = `
    <div class="poly-head"><h2>${esc(d.title)}</h2>
      <a class="poly-src" href="${esc(d.source_url)}" target="_blank" rel="noopener">原文来源 ↗</a></div>
    ${ai}
    <div class="poly-readert">全文</div>
    <div class="poly-reader">${body}</div>`;
}
$('#poly-wrap').addEventListener('click', async e => {
  const g = e.target.closest('#poly-gen') || e.target.closest('#poly-regen');
  if (!g) return;
  g.disabled = true; g.textContent = 'AI 解读生成中…（约二三十秒）';
  try {
    const d = await api('/api/policydocs/' + polyData.id + '/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: g.id === 'poly-regen' }) });
    polyData.interpretation = d.content; renderPolicyDoc(); toast('已生成');
  } catch (err) { toast(err.message, true); g.disabled = false; g.textContent = '🤖 生成 AI 政策解读'; }
});

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
    $('#acct-app').classList.toggle('hidden', !IN_APP);
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

/* ============= 多端自动同步：数据变了自动刷新当前视图，无需手动更新 ============= */
let _syncToken = null, _syncBusy = false;
const SYNC_REFRESH = {
  notes: () => { loadFeed(); loadFeedTags(); },
  materials: () => loadMaterials(),
  idiom: () => loadEntries(),
  kb: () => loadNotebooks(),
  wrongq: () => loadWrongq(),
  news: () => loadNews(),
  gaikuo: () => loadGaikuo(),
  partydict: () => loadPartyDict(),
  sucai: () => loadSucai(),
  review: () => loadReview(),
};
function _syncEditing() {
  // 正在编辑/弹窗打开时不打扰（块编辑器、小记编辑器有内容、任何弹层）
  const v = stack.length ? stack[stack.length - 1].view : '';
  if (v === 'doc' || v === 'wqadd') return true;
  const cp = $('#cp-content'); if (cp && cp.value.trim()) return true;
  if (document.querySelector('.modal:not(.hidden)') || document.querySelector('.note-sheet:not(.hidden)')) return true;
  return false;
}
async function checkSync() {
  if (_syncBusy || document.hidden || !ME) return;
  _syncBusy = true;
  try {
    const d = await api('/api/sync');
    if (_syncToken === null) { _syncToken = d.token; return; }
    if (d.token !== _syncToken) {
      _syncToken = d.token;
      if (!_syncEditing()) {
        const v = stack.length ? stack[stack.length - 1].view : '';
        if (SYNC_REFRESH[v]) SYNC_REFRESH[v]();
      }
    }
  } catch (_) {} finally { _syncBusy = false; }
}
setInterval(checkSync, 30000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) checkSync(); });
window.addEventListener('focus', checkSync);

// 外部链接一律新开/交给系统浏览器，避免在应用内跳走后无法返回
document.addEventListener('click', e => {
  const a = e.target.closest('a[href]'); if (!a) return;
  const href = a.getAttribute('href') || '';
  if (/^https?:\/\//i.test(href) && href.indexOf(location.host) < 0) {
    e.preventDefault();
    try { if (window.GongkaoNative && window.GongkaoNative.openUrl) { window.GongkaoNative.openUrl(href); return; } } catch (_) {}
    window.open(href, '_blank', 'noopener');
  }
});

init();
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
