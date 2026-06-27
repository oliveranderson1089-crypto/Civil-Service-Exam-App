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
const VIEWS = ['home', 'notes', 'materials', 'idiom', 'viewer'];
const TITLES = { home: '公考助手', notes: '小记', materials: '资料库', idiom: '成语词语', viewer: '查看' };
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
  goHome();
}
$('#home-cards').addEventListener('click', e => {
  const c = e.target.closest('[data-go]'); if (!c) return;
  const g = c.dataset.go;
  if (g === 'notes') openNotes();
  else if (g === 'materials') openMaterials();
  else if (g === 'idiom') openIdiom();
});
$('#nav-back').onclick = back;

/* ================= 小记 ================= */
let curNoteBoard = '';
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
function openNotes() {
  if (!curNoteBoard) curNoteBoard = ALL_BOARDS[0];
  buildNotesSidebar();
  push({ view: 'notes' });
  loadNotes(); refreshNoteCounts();
}
$('#notes-sidebar').addEventListener('click', e => {
  const it = e.target.closest('[data-board]'); if (!it) return;
  curNoteBoard = it.dataset.board;
  document.querySelectorAll('.ns-item').forEach(x => x.classList.toggle('active', x.dataset.board === curNoteBoard));
  loadNotes();
});
async function loadNotes() {
  try {
    const d = await api('/api/notes?board=' + encodeURIComponent(curNoteBoard));
    const box = $('#notes-list');
    if (!d.items.length) { box.innerHTML = ''; $('#notes-empty').classList.remove('hidden'); return; }
    $('#notes-empty').classList.add('hidden');
    box.innerHTML = d.items.map(n => `
      <div class="note-card" data-id="${n.id}">
        ${n.content ? `<div class="nc-text">${esc(n.content)}</div>` : ''}
        ${n.images.length ? `<div class="nc-imgs">${n.images.map(u => `<img src="${u}" loading="lazy">`).join('')}</div>` : ''}
        <div class="nc-time">${fmtTime(n.updated_at)}</div>
      </div>`).join('');
    box._items = d.items;
  } catch (e) { toast(e.message, true); }
}
$('#notes-list').addEventListener('click', e => {
  const card = e.target.closest('.note-card'); if (!card) return;
  const it = ($('#notes-list')._items || []).find(x => x.id == card.dataset.id);
  if (it) openEditor(it);
});
$('#note-fab').onclick = () => openEditor(null);

/* 小记编辑器 */
let editing = null;      // 正在编辑的 note（null=新建）
let editorImgs = [];     // [{kind:'existing',file,url} | {kind:'new',fileObj,url}]
function openEditor(note) {
  editing = note;
  editorImgs = [];
  $('#ne-board').innerHTML = ALL_BOARDS.map(b => `<option ${b === (note ? note.board : curNoteBoard) ? 'selected' : ''}>${esc(b)}</option>`).join('');
  $('#ne-content').value = note ? note.content : '';
  $('#ne-del').classList.toggle('hidden', !note);
  if (note) note.img_files.forEach((f, i) => editorImgs.push({ kind: 'existing', file: f, url: note.images[i] }));
  renderEditorImgs();
  $('#note-modal').classList.remove('hidden');
  setTimeout(() => $('#ne-content').focus(), 50);
}
function renderEditorImgs() {
  $('#ne-imgs').innerHTML = editorImgs.map((im, i) =>
    `<div class="ne-thumb"><img src="${im.url}"><button data-rm="${i}">×</button></div>`).join('');
}
$('#ne-imgs').addEventListener('click', e => {
  const b = e.target.closest('[data-rm]'); if (!b) return;
  editorImgs.splice(+b.dataset.rm, 1); renderEditorImgs();
});
$('#ne-file').addEventListener('change', e => {
  [...e.target.files].forEach(f => editorImgs.push({ kind: 'new', fileObj: f, url: URL.createObjectURL(f) }));
  e.target.value = ''; renderEditorImgs();
});
$('#ne-cancel').onclick = () => $('#note-modal').classList.add('hidden');
$('#note-modal').addEventListener('click', e => { if (e.target.id === 'note-modal') $('#note-modal').classList.add('hidden'); });
$('#ne-save').onclick = async () => {
  const content = $('#ne-content').value.trim();
  if (!content && !editorImgs.length) { toast('写点什么吧', true); return; }
  const fd = new FormData();
  fd.append('board', $('#ne-board').value);
  fd.append('content', content);
  editorImgs.filter(i => i.kind === 'new').forEach(i => fd.append('images', i.fileObj));
  try {
    if (editing) {
      fd.append('keep', JSON.stringify(editorImgs.filter(i => i.kind === 'existing').map(i => i.file)));
      await api('/api/notes/' + editing.id, { method: 'PUT', body: fd });
    } else {
      await api('/api/notes', { method: 'POST', body: fd });
    }
    $('#note-modal').classList.add('hidden');
    toast('已保存');
    curNoteBoard = $('#ne-board').value;
    document.querySelectorAll('.ns-item').forEach(x => x.classList.toggle('active', x.dataset.board === curNoteBoard));
    loadNotes(); refreshNoteCounts();
  } catch (e) { toast(e.message, true); }
};
$('#ne-del').onclick = async () => {
  if (!editing || !confirm('删除这条小记？')) return;
  try { await api('/api/notes/' + editing.id, { method: 'DELETE' }); $('#note-modal').classList.add('hidden'); toast('已删除'); loadNotes(); refreshNoteCounts(); }
  catch (e) { toast(e.message, true); }
};

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
function openViewer(id, name, ext) {
  ext = ext || '';
  const fileUrl = '/api/materials/' + id + '/view';
  const src = (ext === '.pdf' || OFFICE_EXT.includes(ext))
    ? '/pdfjs/web/viewer.html?file=' + encodeURIComponent(fileUrl) : fileUrl;
  $('#viewer-name').textContent = name;
  $('#viewer-frame').src = src;
  $('#viewer-dl').href = '/api/materials/' + id + '/download';
  push({ view: 'viewer', title: name });
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
