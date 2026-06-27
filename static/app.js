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

let ME = null, SECTIONS = [], IDIOM_BOARD = '', ALL_BOARDS = [];
let stack = [];

/* ---------------- 导航 ---------------- */
const VIEWS = ['home', 'section', 'board', 'notes', 'materials', 'idiom', 'viewer'];
const TITLES = { home: '公考助手', section: '', board: '', notes: '小记', materials: '资料库', idiom: '成语词语', viewer: '查看' };
function render() {
  const st = stack[stack.length - 1];
  VIEWS.forEach(v => $('#view-' + v).classList.toggle('hidden', v !== st.view));
  $('#top-title').textContent = st.title || TITLES[st.view] || '公考助手';
  $('#nav-back').classList.toggle('hidden', stack.length <= 1);
}
function push(state) { stack.push(state); render(); }
function back() { if (stack.length > 1) { stack.pop(); render(); } }
function goHome() { stack = [{ view: 'home' }]; render(); }
// 供安卓原生「返回/侧滑」调用：能退则退并返回 true，已在首页返回 false
window.appBack = function () {
  // 有弹窗先关弹窗
  const m = document.querySelector('.modal:not(.hidden)');
  if (m) { m.classList.add('hidden'); return true; }
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
    <div class="home-card" data-go="notes"><div class="hc-logo">📝</div><div class="hc-name">小记</div><div class="hc-desc">随手记 · 按板块归类</div></div>
    <div class="home-card" data-go="materials"><div class="hc-logo">📁</div><div class="hc-name">资料库</div><div class="hc-desc">图片/文档/网页 应用内查看</div></div>`;
  goHome();
}
$('#home-cards').addEventListener('click', e => {
  const c = e.target.closest('[data-go]'); if (!c) return;
  const g = c.dataset.go;
  if (g.startsWith('sec:')) openSection(g.slice(4));
  else if (g === 'notes') openNotes();
  else if (g === 'materials') openMaterials();
  else if (g === 'idiom') openIdiom();
});
function openSection(key) {
  const sec = SECTIONS.find(s => s.key === key); if (!sec) return;
  $('#section-title').textContent = sec.name;
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
  const b = c.dataset.board;
  if (b === IDIOM_BOARD) openIdiom();   // 言语理解与表达 → 成语词语工具
  else openBoard(b);                    // 其余板块 → 占位（建设中）
});
function openBoard(board) {
  $('#board-ph-title').textContent = board;
  push({ view: 'board', title: board });
}
$('#nav-back').onclick = back;

/* ================= 小记（仿语雀） ================= */
let curNoteBoard = '';
let curTag = '';
function buildNotesSidebar() {
  $('#notes-sidebar').innerHTML = SECTIONS.map(s => `
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
      const n = d.counts[el.dataset.cnt] || 0;
      el.textContent = n ? n : '';
    });
  } catch (_) {}
}
function openNotes(board) {
  curNoteBoard = board || curNoteBoard || ALL_BOARDS[0];
  curTag = '';
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
    `<span class="cp-tag"># ${esc(t)}<button class="cp-x" data-tgr="${i}">×</button></span>`).join('');
  const editing = !!draft.id;
  $('#cp-submit').textContent = editing ? '保存' : '发布';
  $('#cp-del').classList.toggle('hidden', !editing);
  $('#cp-cancel').classList.toggle('hidden', !editing);
  $('#cp-hint').textContent = editing ? '编辑中…' : '';
}
document.querySelector('.cp-bar').addEventListener('click', e => {
  const b = e.target.closest('[data-cp]'); if (!b) return;
  const t = b.dataset.cp;
  if (t === 'img') $('#cp-imgfile').click();
  else if (t === 'file') $('#cp-attfile').click();
  else if (t === 'todo') {
    draft.todos.push({ text: '', done: false }); renderComposer();
    const ins = document.querySelectorAll('.cp-todo-text'); if (ins.length) ins[ins.length - 1].focus();
  } else if (t === 'tag') {
    const tg = prompt('添加标签：'); if (tg && tg.trim()) { const v = tg.trim(); if (!draft.tags.includes(v)) draft.tags.push(v); renderComposer(); }
  }
});
$('#cp-imgfile').addEventListener('change', e => { [...e.target.files].forEach(f => draft.images.push({ kind: 'new', fileObj: f, url: URL.createObjectURL(f) })); e.target.value = ''; renderComposer(); });
$('#cp-attfile').addEventListener('change', e => { [...e.target.files].forEach(f => draft.files.push({ kind: 'new', fileObj: f, name: f.name })); e.target.value = ''; renderComposer(); });
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
  draft.images.filter(i => i.kind === 'new').forEach(i => fd.append('images', i.fileObj));
  draft.files.filter(i => i.kind === 'new').forEach(i => fd.append('attachments', i.fileObj));
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
    if (!d.items.length) { box.innerHTML = ''; $('#feed-empty').classList.remove('hidden'); return; }
    $('#feed-empty').classList.add('hidden');
    box.innerHTML = d.items.map(feedCard).join('');
    box._items = d.items;
  } catch (e) { toast(e.message, true); }
}
function feedCard(n) {
  const todos = n.todos.length ? `<div class="fc-todos">${n.todos.map((t, i) =>
    `<label class="fc-todo${t.done ? ' done' : ''}"><input type="checkbox" data-tg="${n.id}" data-ti="${i}" ${t.done ? 'checked' : ''}><span>${esc(t.text)}</span></label>`).join('')}</div>` : '';
  const imgs = n.images.length ? `<div class="fc-imgs">${n.images.map(u => `<img src="${u}" loading="lazy" data-img="${u}">`).join('')}</div>` : '';
  const files = n.attachments.length ? `<div class="fc-files">${n.attachments.map((a, i) =>
    `<button class="fc-file" data-file="${n.id}" data-fi="${i}" data-ext="${esc(a.ext)}" data-fview="${a.viewable ? 1 : 0}" data-fname="${esc(a.name)}">📎 ${esc(a.name)}</button>`).join('')}</div>` : '';
  const tags = n.tags.length ? `<div class="fc-tags">${n.tags.map(t => `<span class="fc-tag"># ${esc(t)}</span>`).join('')}</div>` : '';
  return `<div class="feed-card" data-id="${n.id}">
    <div class="fc-time">更新于 ${fmtTime(n.updated_at)}
      <span class="fc-acts"><button class="fc-edit" data-edit="${n.id}" title="编辑">✎</button><button class="fc-del" data-del="${n.id}" title="删除">🗑</button></span>
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
    openViewerUrl(base, fl.dataset.fname, fl.dataset.ext, base + '?dl=1'); return;
  }
  const im = e.target.closest('[data-img]');
  if (im) { openViewerUrl(im.dataset.img, '图片', '.png'); return; }
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
function openViewerUrl(fileUrl, name, ext, dlUrl) {
  ext = ext || '';
  const src = (ext === '.pdf' || OFFICE_EXT.includes(ext))
    ? '/pdfjs/web/viewer.html?file=' + encodeURIComponent(fileUrl) : fileUrl;
  $('#viewer-name').textContent = name;
  $('#viewer-frame').src = src;
  $('#viewer-dl').href = dlUrl || fileUrl;
  push({ view: 'viewer', title: name });
}
function openViewer(id, name, ext) {
  openViewerUrl('/api/materials/' + id + '/view', name, ext, '/api/materials/' + id + '/download');
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
  const file = $('#up-file').files[0];
  if (!file) { toast('请选择文件', true); return; }
  const fd = new FormData();
  fd.append('file', file);
  fd.append('board', $('#up-board').value);
  fd.append('section', '');
  fd.append('title', $('#up-title').value.trim());
  $('#up-go').disabled = true; $('#up-go').textContent = '上传中…';
  try { await api('/api/materials', { method: 'POST', body: fd }); toast('上传成功'); $('#upload-modal').classList.add('hidden'); loadMaterials(); }
  catch (e) { toast(e.message, true); }
  $('#up-go').disabled = false; $('#up-go').textContent = '上传';
};

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
    $('#settings-modal').classList.remove('hidden');
  } catch (e) { toast(e.message, true); }
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
