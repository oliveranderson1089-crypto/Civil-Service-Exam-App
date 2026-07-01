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
};
// 板块下的功能模块（可扩展：以后给某板块加更多功能图标）
const BOARD_FEATURES = {
  '言语理解与表达': [
    { key: 'idiom', name: '成语词语积累', desc: '选词填空 · 拼音释义 · 导 PDF', icon: 'book' },
  ],
  '议论文': [
    { key: 'classics', name: '古诗文·名句速查', desc: '唐诗宋词 · 四书五经 · 查询收藏', icon: 'book' },
  ],
};
// 大板块（行测/申论）下的功能模块（预留，可扩展）
const SECTION_FEATURES = {};

let ME = null, SECTIONS = [], IDIOM_BOARD = '', ALL_BOARDS = [];
let stack = [];

/* ---------------- 导航 ---------------- */
const VIEWS = ['home', 'section', 'board', 'notes', 'kb', 'notebook', 'doc', 'materials', 'idiom', 'viewer', 'search', 'classics', 'cdetail'];
const TITLES = { home: '公考助手', section: '', board: '', notes: '小记', kb: '知识库', notebook: '', doc: '', materials: '资料库', idiom: '成语词语', viewer: '查看', search: '搜索', classics: '古诗文速查', cdetail: '' };
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
  $('#me-name').textContent = ME.username;
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
    <div class="home-card" data-go="materials"><div class="hc-logo">${IC.folder}</div><div class="hc-name">资料库</div><div class="hc-desc">图片/文档/网页 应用内查看</div></div>`;
  goHome();
}
$('#home-cards').addEventListener('click', e => {
  const c = e.target.closest('[data-go]'); if (!c) return;
  const g = c.dataset.go;
  if (g.startsWith('sec:')) openSection(g.slice(4));
  else if (g === 'notes') openNotes();
  else if (g === 'kb') openKb();
  else if (g === 'materials') openMaterials();
  else if (g === 'idiom') openIdiom();
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
function openBoard(board) {
  const feats = BOARD_FEATURES[board] || [];
  $('#board-title').textContent = board;
  if (feats.length) {
    $('#board-features').innerHTML = feats.map(f =>
      `<div class="home-card" data-feat="${esc(f.key)}">
        <div class="hc-logo">${IC[f.icon] || ''}</div>
        <div class="hc-name">${esc(f.name)}</div>
        <div class="hc-desc">${esc(f.desc)}</div>
      </div>`).join('');
    $('#board-features').classList.remove('hidden');
    $('#board-ph').classList.add('hidden');
  } else {
    $('#board-features').classList.add('hidden');
    $('#board-ph').classList.remove('hidden');
    $('#board-ph-title').textContent = board;
  }
  push({ view: 'board', title: board });
}
$('#board-features').addEventListener('click', e => {
  const c = e.target.closest('[data-feat]'); if (!c) return;
  if (c.dataset.feat === 'idiom') openIdiom();
  else if (c.dataset.feat === 'classics') openClassics();
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
    $('#pv-found').textContent = d.found ? '✓ 词典已收录' : '✎ 词典未收录，可手动补充';
    $('#pv-exp').value = d.explanation; $('#pv-der').value = d.derivation; $('#pv-exa').value = d.example;
    $('#pv-note').value = ''; $('#pv-catsel').value = d.category;
    $('#pv-der-wrap').classList.toggle('hidden', !d.derivation && d.source !== 'idiom');
    $('#pv-exa-wrap').classList.toggle('hidden', !d.example && d.source !== 'idiom');
    $('#preview').classList.remove('hidden'); $('#add-hint').textContent = '';
  } catch (e) { $('#add-hint').textContent = ''; toast(e.message, true); }
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
  if (state.filter === '成语' || state.filter === '词语') url += 'category=' + encodeURIComponent(state.filter) + '&';
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
    const note = prompt('笔记：', it.note || ''); if (note === null) return;
    try { await api('/api/entries/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }) }); loadEntries(); } catch (err) { toast(err.message, true); }
  }
});
$('#lookup-btn').onclick = doLookup;
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
  let res = '';
  if (d.translation) res += `<div class="cd-sec"><div class="cd-sec-t">译文</div><div class="cd-sec-b">${esc(d.translation).replace(/\n/g, '<br>')}</div></div>`;
  if (d.appreciation) res += `<div class="cd-sec"><div class="cd-sec-t">赏析</div><div class="cd-sec-b">${esc(d.appreciation).replace(/\n/g, '<br>')}</div></div>`;
  const aiBox = d.ai_explain
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">AI 讲解</div><div class="cd-sec-b">${mdToHtml(d.ai_explain)}</div>
        <button class="btn cd-ai-regen" id="cd-ai-regen">重新生成</button></div>`
    : `<button class="btn primary cd-ai-btn" id="cd-ai-btn">🤖 AI 讲解${d.translation ? '（不满意资源时用）' : ''}</button>`;
  $('#cd-wrap').innerHTML = `
    <div class="cd-head">
      <span class="cls-badge" style="background:${CLS_BADGE[d.category] || '#888'}">${esc(d.category)}</span>
      <h2 class="cd-title">${esc(d.title)}</h2>
      <button class="cls-star ${d.starred ? 'on' : ''}" id="cd-star">${d.starred ? '★' : '☆'}</button>
    </div>
    <div class="cd-meta">${esc(meta)}</div>
    <div class="cd-body">${body}</div>
    ${res || (d.ai_explain ? '' : '<p class="cd-tip">这篇暂无现成译文，可点下面让 AI 讲解。</p>')}
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
const SR_TYPE = { note: '小记', material: '资料', doc: '知识库' };
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
  }
});

/* ================= 顶栏 ================= */
$('#admin-btn').onclick = () => { location.href = '/admin'; };
$('#logout-btn').onclick = async () => {
  if (!confirm('退出登录？')) return;
  try { await fetch('/logout', { method: 'POST' }); } catch (_) {}
  location.href = '/login';
};
$('#settings-btn').onclick = async () => {
  try {
    const d = await api('/api/account');
    const qs = (await api('/api/sec_questions')).questions;
    $('#set-secq').innerHTML = qs.map(q => `<option ${q === d.sec_question ? 'selected' : ''}>${esc(q)}</option>`).join('');
    $('#set-oldpw').value = ''; $('#set-newpw').value = ''; $('#set-seca').value = '';
    $('#set-app').classList.toggle('hidden', !IN_APP);
    $('#settings-modal').classList.remove('hidden');
  } catch (e) { toast(e.message, true); }
};
$('#set-refresh').onclick = () => {
  if (window.GongkaoNative && window.GongkaoNative.reload) { try { window.GongkaoNative.reload(); return; } catch (_) {} }
  location.reload();
};
$('#set-server').onclick = () => {
  $('#settings-modal').classList.add('hidden');
  try { window.GongkaoNative && window.GongkaoNative.changeServer(); } catch (_) {}
};
$('#set-cancel').onclick = () => $('#settings-modal').classList.add('hidden');
$('#settings-modal').addEventListener('click', e => { if (e.target.id === 'settings-modal') $('#settings-modal').classList.add('hidden'); });
$('#set-save').onclick = async () => {
  const body = {};
  if ($('#set-newpw').value) { body.new_password = $('#set-newpw').value; body.old_password = $('#set-oldpw').value; }
  if ($('#set-seca').value) { body.sec_question = $('#set-secq').value; body.sec_answer = $('#set-seca').value; }
  if (!body.new_password && !body.sec_answer) { $('#settings-modal').classList.add('hidden'); return; }
  try { await api('/api/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); toast('已保存'); $('#settings-modal').classList.add('hidden'); }
  catch (e) { toast(e.message, true); }
};

init();
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
