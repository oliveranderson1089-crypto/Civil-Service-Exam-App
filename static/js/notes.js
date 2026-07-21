/* 小记（仿语雀）
 *
 * 由 app.js 按它自己的区段边界切出（原 L539-1277）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, IC, IS_MOBILE, KB, OFFICE_EXT, SECTIONS,
   api, appConfirm, c, composing, createDock, deskMsg,
   esc, fmtTime, iconFor, lsGet, lsSet, openAI,
   openViewerUrl, push, stack, toast */

/* ================= 小记（仿语雀） ================= */
let curNoteBoard = '';
let curTag = '';
let noteSearchQ = '';
// 板块的下拉选项（编辑器、feed 筛选、快速记 三处共用）
function boardOptions(sel, withAll) {
  return (withAll ? `<option value="">全部板块</option>` : `<option value="">不分板块</option>`)
    + SECTIONS.map(s => `<optgroup label="${esc(s.name)}">`
      + s.boards.map(b => `<option value="${esc(b)}"${b === sel ? ' selected' : ''}>${esc(b)}</option>`).join('')
      + '</optgroup>').join('');
}
// 电脑端原来有一整栏板块目录（占掉最左边一大条）。板块只是个归类，不值得占一栏 ——
// 改成「写的时候在编辑器里选，看的时候在顶部下拉筛」，功能一样，屏幕省下来给正文。
function buildNotesSidebar() {
  const fb = $('#feed-board');
  if (fb) fb.innerHTML = boardOptions(curNoteBoard, true);
  const cb = $('#cp-board');
  if (cb) cb.innerHTML = boardOptions(draft.board != null ? draft.board : curNoteBoard, false);
}
async function refreshNoteCounts() {
  try {
    const d = await api('/api/notes/counts');
    document.querySelectorAll('[data-cnt]').forEach(el => {
      const n = el.dataset.cnt === '' ? (d.total || 0) : (d.counts[el.dataset.cnt] || 0);
      el.textContent = n ? n : '';
    });
  } catch (_) { /* 拉不到就先空着，下次进来或轮询会补上 */ }
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
    restoreDraftOrNew(); loadFeed(); loadFeedTags();
    return;
  }
  curNoteBoard = board != null ? board : (curNoteBoard || '');
  buildNotesSidebar();
  push({ view: 'notes' });
  restoreDraftOrNew(); loadFeed(); loadFeedTags(); refreshNoteCounts();
}
// 编辑器里任何输入/勾选/换板块 → 防抖存本地草稿；关页面/切走前立刻兜底存一次
document.querySelector('.composer').addEventListener('input', saveDraftLocal);
document.querySelector('.composer').addEventListener('change', saveDraftLocal);
addEventListener('pagehide', flushDraftLocal);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flushDraftLocal(); });
$('#feed-board').addEventListener('change', () => {     // 顶部下拉：按板块筛选
  curNoteBoard = $('#feed-board').value; curTag = '';
  loadFeed(); loadFeedTags();
});
$('#cp-board').addEventListener('change', () => {       // 编辑器：这条归到哪个板块
  draft.board = $('#cp-board').value;
});

/* ---- 编辑器（草稿） ---- */
let draft = { id: null, content: '', images: [], files: [], todos: [], tags: [] };
function newDraft(clearLocal) {
  draft = { id: null, content: '', images: [], files: [], todos: [], tags: [],
            board: curNoteBoard };   // 新写的默认归到当前筛选的板块
  $('#cp-content').value = ''; renderComposer();
  closeComposerM();
  if (clearLocal) clearDraftLocal();   // 只有发布/取消/删除才清；单纯进页面不清（否则刚要恢复就被抹掉）
}

/* ---- 自动保存草稿到本地：没点发布也不丢（关应用/切功能都在）----
   只存文字类字段（正文/待办/标签/板块/所编辑的笔记id）。图片/附件是内存里的 blob，
   没法塞进 localStorage，就不进自动草稿——真要连图带附件保住，还得点发布。 */
const NOTE_DRAFT_KEY = 'noteDraft';
let _draftSaveT = null;
function _draftMeaningful(content) {
  return (content || '').trim() ||
         draft.todos.some(t => (t.text || '').trim()) ||
         draft.tags.length > 0;
}
function flushDraftLocal() {            // 立刻存（关页面/切走时用，绕过防抖）
  try {
    const content = $('#cp-content').value;
    if (!_draftMeaningful(content)) { clearDraftLocal(); return; }
    lsSet(NOTE_DRAFT_KEY, JSON.stringify({
      id: draft.id, content, board: draft.board,
      todos: draft.todos, tags: draft.tags, ts: Date.now(),
    }));
  } catch (_) { /* 存不下（配额满等）就算了，别打断编辑 */ }
}
function saveDraftLocal() {             // 编辑时防抖存，别每个按键都写盘
  clearTimeout(_draftSaveT);
  _draftSaveT = setTimeout(flushDraftLocal, 500);
}
function clearDraftLocal() { clearTimeout(_draftSaveT); try { lsSet(NOTE_DRAFT_KEY, ''); } catch (_) { /* 清不掉不影响，下次覆盖 */ } }
// 进小记时：有未保存草稿就恢复，否则开新草稿
async function restoreDraftOrNew() {
  let s = null;
  try { s = JSON.parse(lsGet(NOTE_DRAFT_KEY) || 'null'); } catch (_) { /* 读坏就当没有 */ }
  const meaningful = s && ((s.content || '').trim() ||
    (s.todos || []).some(t => (t.text || '').trim()) || (s.tags || []).length);
  if (!meaningful) { newDraft(); return; }
  if (s.id) {                       // 恢复的是「对已有笔记的未保存修改」：先拉原笔记（要它的图/附件），再盖上改动
    try {
      const n = await api('/api/notes/' + s.id);
      loadDraft(n);
      draft.content = s.content || ''; $('#cp-content').value = draft.content;
      if (s.todos) draft.todos = s.todos;
      if (s.tags) draft.tags = s.tags;
      if (s.board != null) draft.board = s.board;
      renderComposer();
      $('#cp-hint').textContent = '已恢复未保存的修改';
      return;
    } catch (_) { /* 原笔记没了（被删）→ 下面按新草稿把文字保住，别丢 */ }
  }
  draft = { id: null, content: s.content || '', images: [], files: [],
            todos: s.todos || [], tags: s.tags || [],
            board: s.board != null ? s.board : curNoteBoard };
  $('#cp-content').value = draft.content;
  renderComposer();
  $('#cp-hint').textContent = '已恢复未发布的草稿';
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
    id: n.id, content: n.content, board: n.board || '',
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
  const cb = $('#cp-board');
  if (cb) cb.value = (draft.board != null ? draft.board : curNoteBoard) || '';
  $('#cp-todos').innerHTML = draft.todos.map((t, i) =>
    `<div class="cp-todo"><input type="checkbox" data-tdo="${i}" ${t.done ? 'checked' : ''}>
     <input class="cp-todo-text" data-tdt="${i}" value="${esc(t.text)}" placeholder="待办事项…">
     <button class="cp-x" data-tdr="${i}">×</button></div>`).join('');
  $('#cp-imgs').innerHTML = draft.images.map((im, i) =>
    `<div class="cp-thumb${im.busy ? ' busy' : ''}" data-imb="${i}">
       <img src="${im.url}" data-imbig="${i}" title="点开看大图，确认没传错">
       <button class="cp-x" data-imr="${i}">×</button>
     </div>`).join('');
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
  if (!composing(e) && e.key === 'Enter') {
    e.preventDefault();
    if (addTagsFrom(e.target.value)) { renderComposer(); saveDraftLocal(); }
    e.target.value = '';
    setTimeout(() => { const i = $('#cp-taginput'); i.classList.remove('hidden'); i.focus(); }, 10);
  } else if (e.key === 'Escape') { e.target.value = ''; e.target.classList.add('hidden'); }
});
$('#cp-taginput').addEventListener('blur', e => {
  if (addTagsFrom(e.target.value)) { renderComposer(); saveDraftLocal(); }
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
/* 轻量看图浮层：就地放大，不跳走、不丢正在写的草稿（openViewerUrl 会 push 一个新视图，
   写到一半跑去看图再回来，体验很别扭）。Esc / 点背景 / 点图都能关。 */
/* 看图浮层：就地放大，不跳走（openViewerUrl 会 push 一个新视图，写到一半跑去看图再回来很别扭）。
   ★ 草稿里的图和已发布的图**走同一条路**——原来已发布的图走 openViewerUrl（全屏阅读器），
     草稿里的走这个浮层，所以「上传前小、上传后巨大」。统一到这里。
   ★ 手机端支持**双指捏合缩放**；电脑端滚轮缩放、拖动平移。
   ★ 「复制图片」是真把**图片本身**写进剪贴板（不是图片地址）—— 原来复制出来是一串 URL。 */
function lightbox(url, name) {
  if (!url) return;
  const old = document.getElementById('lbx'); if (old) old.remove();
  const box = document.createElement('div');
  box.id = 'lbx'; box.className = 'lbx';
  box.innerHTML = `
    <div class="lbx-bar">
      <button class="lbx-b" data-lbx="copy" title="复制图片本身（不是地址）">⧉ 复制图片</button>
      <a class="lbx-b" href="${url}" download="${esc(name || 'image.png')}" title="下载">⤓ 下载</a>
      <button class="lbx-b" data-lbx="reset" title="还原大小">⤢ 还原</button>
      <button class="lbx-b lbx-x" data-lbx="close" title="关闭（Esc）">×</button>
    </div>
    <div class="lbx-stage"><img id="lbx-img" src="${url}" alt=""></div>
    <div class="lbx-hint">双指捏合 / 滚轮缩放 · 拖动平移 · 点背景关闭</div>`;
  document.body.appendChild(box);

  const img = box.querySelector('#lbx-img');
  const stage = box.querySelector('.lbx-stage');
  let scale = 1, tx = 0, ty = 0;
  const apply = () => { img.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`; };
  const reset = () => { scale = 1; tx = ty = 0; apply(); };

  // ⚠️ 这个键盘处理函数原来叫 esc，把全局的 esc()（HTML 转义）**遮蔽**了 ——
  //    上面 innerHTML 里用到 esc(name) 就直接 ReferenceError。改名 onEsc。
  const close = () => { box.remove(); document.removeEventListener('keydown', onEsc); };
  const onEsc = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onEsc);

  box.addEventListener('click', e => {
    if (e.target === box || e.target === stage) { close(); return; }   // 点背景才关，点图不关
    const b = e.target.closest('[data-lbx]'); if (!b) return;
    const a = b.dataset.lbx;
    if (a === 'close') close();
    else if (a === 'reset') reset();
    else if (a === 'copy') copyImage(url, b);
  });

  // 滚轮缩放（电脑端）
  stage.addEventListener('wheel', e => {
    e.preventDefault();
    scale = Math.min(6, Math.max(0.4, scale * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
    apply();
  }, { passive: false });

  // 双指捏合（手机端）+ 单指/鼠标拖动平移
  const pts = new Map();
  let d0 = 0, s0 = 1, px = 0, py = 0;
  stage.addEventListener('pointerdown', e => {
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    stage.setPointerCapture(e.pointerId);
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      d0 = Math.hypot(a.x - b.x, a.y - b.y); s0 = scale;
    } else { px = e.clientX - tx; py = e.clientY - ty; }
  });
  stage.addEventListener('pointermove', e => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size >= 2) {
      const [a, b] = [...pts.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (d0 > 0) { scale = Math.min(6, Math.max(0.4, s0 * d / d0)); apply(); }
    } else if (scale !== 1) {              // 没放大时不平移，免得挡住「点背景关闭」
      tx = e.clientX - px; ty = e.clientY - py; apply();
    }
  });
  const up = e => { pts.delete(e.pointerId); if (pts.size < 2) d0 = 0; };
  stage.addEventListener('pointerup', up);
  stage.addEventListener('pointercancel', up);
  // 双击/双击图片 = 放大/还原
  img.addEventListener('dblclick', () => { scale = scale > 1 ? 1 : 2.2; tx = ty = 0; apply(); });
}

/* 复制图片：把**图片本身**写进剪贴板（原来复制出来只是一串 URL，粘贴到别处就是个地址）。
   剪贴板只认 image/png，所以 jpg/webp 要先用 canvas 转一道。 */
async function copyImage(url, btn) {
  const label = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '复制中…'; }
  try {
    const blob = await (await fetch(url)).blob();
    let png = blob;
    if (blob.type !== 'image/png') {          // 剪贴板只吃 png
      const bmp = await createImageBitmap(blob);
      const cv = document.createElement('canvas');
      cv.width = bmp.width; cv.height = bmp.height;
      cv.getContext('2d').drawImage(bmp, 0, 0);
      bmp.close();
      png = await new Promise(r => cv.toBlob(r, 'image/png'));
    }
    // 桌面版：WebKitGTK 的 navigator.clipboard.write 会被拒（报 user denied，其实是不支持），
    // 所以走消息桥让壳用 GTK 剪贴板真复制。浏览器/手机走标准 Clipboard API。
    if (window.__desktop) {
      const b64 = await new Promise(res => {
        const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(png);
      });
      deskMsg({ a: 'copyimg', data: b64 });
      // 壳复制成功会自己 toast；这里不重复提示
    } else {
      if (!navigator.clipboard || !window.ClipboardItem) throw new Error('这个浏览器不支持复制图片');
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': png })]);
      toast('图片已复制，可以直接粘贴了');
    }
  } catch (e) {
    toast('复制图片失败：' + e.message, true);
  }
  if (btn) { btn.disabled = false; btn.textContent = label; }
}

/* 图片压缩：手机拍的图动辄 4~8MB，原样上传 → 点「发布」那一下就卡住了。
   在**选图时**就压到 1600px / JPEG 0.82，发布时传的是几百 KB，一下就完。
   但压缩不能挡住添加：先把缩略图（原图 objectURL）立刻放上去，压缩丢到后台，
   压完再换掉 fileObj。发布时若还没压完，submit 会等一下（一般早压完了）。 */
async function compressImage(file, maxSide = 1600, quality = 0.82) {
  if (!/^image\//.test(file.type) || /gif|svg/i.test(file.type)) return file;   // 动图/矢量图不动
  let bmp;
  try { bmp = await createImageBitmap(file); } catch (_) { return file; }
  const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
  if (scale === 1 && file.size < 700 * 1024) { bmp.close(); return file; }       // 本来就小，别白折腾
  const w = Math.round(bmp.width * scale), h = Math.round(bmp.height * scale);
  let blob = null;
  try {
    let cv;
    if (typeof OffscreenCanvas !== 'undefined') cv = new OffscreenCanvas(w, h);
    else { cv = document.createElement('canvas'); cv.width = w; cv.height = h; }
    const ctx = cv.getContext('2d');
    ctx.drawImage(bmp, 0, 0, w, h);
    blob = cv.convertToBlob
      ? await cv.convertToBlob({ type: 'image/jpeg', quality })
      : await new Promise(r => cv.toBlob(r, 'image/jpeg', quality));
  } catch (_) { blob = null; }
  bmp.close();
  return (blob && blob.size < file.size) ? blob : file;   // 压完反而更大就用原图
}

async function addDraftImages(files) {
  const list = [...files];
  for (const f of list) {
    const im = {
      kind: 'new', fileObj: f, name: f.name || ('img_' + Date.now() + '.jpg'),
      url: URL.createObjectURL(f), busy: true,
    };
    draft.images.push(im);
    im.ready = compressImage(f).then(b => {          // 后台压，不挡添加
      im.fileObj = b; im.busy = false;
      const el = document.querySelector(`[data-imb="${draft.images.indexOf(im)}"]`);
      if (el) el.classList.remove('busy');
    }).catch(() => { im.busy = false; });
  }
  renderComposer();
}
$('#cp-imgfile').addEventListener('change', async e => { const fs = [...e.target.files]; e.target.value = ''; await addDraftImages(fs); });
bindImgDrop(document.querySelector('.composer'), addDraftImages);      // 拖图片进编辑器
bindImgPaste($('#cp-content'), addDraftImages);                        // Ctrl+V 粘图片
$('#cp-camfile').addEventListener('change', async e => { const fs = [...e.target.files]; e.target.value = ''; await addDraftImages(fs); });
async function addDraftFiles(files) {          // 图片以外的附件进小记编辑器
  for (const f of [...files]) {
    const blob = await _materialize(f);
    draft.files.push({ kind: 'new', fileObj: blob, name: f.name || 'file' });
  }
  renderComposer();
}
$('#cp-attfile').addEventListener('change', async e => {
  const list = [...e.target.files]; e.target.value = '';
  await addDraftFiles(list);
});
$('#cp-todos').addEventListener('click', e => { const r = e.target.closest('[data-tdr]'); if (r) { draft.todos.splice(+r.dataset.tdr, 1); renderComposer(); saveDraftLocal(); } });
$('#cp-todos').addEventListener('change', e => { const c = e.target.closest('[data-tdo]'); if (c) draft.todos[+c.dataset.tdo].done = c.checked; });
$('#cp-todos').addEventListener('input', e => { const t = e.target.closest('[data-tdt]'); if (t) draft.todos[+t.dataset.tdt].text = t.value; });
$('#cp-imgs').addEventListener('click', e => {
  const r = e.target.closest('[data-imr]');
  if (r) { draft.images.splice(+r.dataset.imr, 1); renderComposer(); return; }
  const b = e.target.closest('[data-imbig]');            // 发布前就能点开看大图，确认没传错
  if (b) lightbox(draft.images[+b.dataset.imbig].url);
});
$('#cp-files').addEventListener('click', e => { const r = e.target.closest('[data-flr]'); if (r) { draft.files.splice(+r.dataset.flr, 1); renderComposer(); } });
$('#cp-tags').addEventListener('click', e => { const r = e.target.closest('[data-tgr]'); if (r) { draft.tags.splice(+r.dataset.tgr, 1); renderComposer(); saveDraftLocal(); } });
$('#cp-cancel').onclick = () => newDraft(true);
$('#cp-del').onclick = async () => {
  if (!draft.id || !(await appConfirm('删除这条小记？'))) return;
  try { await api('/api/notes/' + draft.id, { method: 'DELETE' }); toast('已删除'); newDraft(true); loadFeed(); loadFeedTags(); refreshNoteCounts(); }
  catch (e) { toast(e.message, true); }
};
$('#cp-submit').onclick = async () => {
  const content = $('#cp-content').value.trim();
  draft.todos = draft.todos.filter(t => (t.text || '').trim() !== '');
  if (!content && !draft.images.length && !draft.files.length && !draft.todos.length) { toast('写点什么吧', true); return; }
  $('#cp-submit').disabled = true;
  // 压缩一般在选图时就跑完了；万一刚选完就点发布，这里等一下（避免传上去的是原图）
  const pending = draft.images.filter(i => i.ready).map(i => i.ready);
  if (pending.length) await Promise.all(pending);
  const fd = new FormData();
  fd.append('board', draft.board != null ? draft.board : curNoteBoard);
  fd.append('content', content);
  fd.append('todos', JSON.stringify(draft.todos));
  fd.append('tags', JSON.stringify(draft.tags));
  draft.images.filter(i => i.kind === 'new').forEach(i => fd.append('images', i.fileObj, i.name || 'image.jpg'));
  draft.files.filter(i => i.kind === 'new').forEach(i => fd.append('attachments', i.fileObj, i.name || 'file'));
  try {
    if (draft.id) {
      fd.append('keep_imgs', JSON.stringify(draft.images.filter(i => i.kind === 'old').map(i => i.file)));
      fd.append('keep_atts', JSON.stringify(draft.files.filter(i => i.kind === 'old').map(i => i.file)));
      await api('/api/notes/' + draft.id, { method: 'PUT', body: fd });
    } else {
      await api('/api/notes', { method: 'POST', body: fd });
    }
    toast('已保存'); newDraft(true); loadFeed(); loadFeedTags(); refreshNoteCounts();
  } catch (e) { toast(e.message, true); }
  $('#cp-submit').disabled = false;
};

/* ---- 手机端：底部悬浮条 / 新建面板 / 全屏编辑器 ---- */
// 全屏编辑器顶栏：取消 / 删除 / 完成
$('#cp-mclose').onclick = () => newDraft(true);
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
  } catch (_) { /* 拉不到就先空着，下次进来或轮询会补上 */ }
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
    if (!(await appConfirm('删除这条小记？'))) return;
    try { await api('/api/notes/' + dl.dataset.del, { method: 'DELETE' }); toast('已删除'); if (draft.id == dl.dataset.del) newDraft(true); loadFeed(); loadFeedTags(); refreshNoteCounts(); }
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
  if (im) { lightbox(im.dataset.img, '图片.png'); return; }   // 和草稿里的图走同一条路，大小一致
});
/* 双击小记卡片即可编辑（除点到按钮/图片/附件/勾选） */
$('#feed').addEventListener('dblclick', e => {
  if (e.target.closest('button,a,input,[data-img],[data-file]')) return;
  const card = e.target.closest('.feed-card'); if (!card) return;
  const it = ($('#feed')._items || []).find(x => x.id == card.dataset.id);
  if (it) loadDraft(it);
});

/* ---- 图片：拖进来 / 粘贴进来（小记编辑器 和 随手记浮层 都支持）----
   原来只能点按钮选文件。资料库早就支持拖拽了，AI 早就支持 Ctrl+V 了 —— 小记没道理不支持。 */
function bindImgDrop(el, add) {
  el.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('drop-on'); });
  el.addEventListener('dragleave', e => {
    if (!el.contains(e.relatedTarget)) el.classList.remove('drop-on');
  });
  el.addEventListener('drop', e => {
    e.preventDefault(); el.classList.remove('drop-on');
    const fs = [...(e.dataTransfer.files || [])].filter(f => /^image\//.test(f.type));
    if (fs.length) add(fs);
    else if (e.dataTransfer.files && e.dataTransfer.files.length) toast('只能拖图片进来', true);
  });
}
function bindImgPaste(el, add) {
  el.addEventListener('paste', e => {
    const items = [...((e.clipboardData || {}).items || [])];
    const fs = items.filter(i => i.type && i.type.startsWith('image/'))
      .map(i => i.getAsFile()).filter(Boolean);
    if (!fs.length) return;                 // 粘的是文字 → 放行，让它正常粘进去
    e.preventDefault();
    add(fs);
  });
}
// 桌面壳（WebKit）里 dataTransfer.files 是空的，图片由壳转成 dataURL 回调过来
window.__onNotePasteImage = null;

/* ---- 通用浮窗：标题栏拖动移位、右下角拖动改大小、位置和尺寸都记住 ----
   （createDock 那套是给「半屏停靠面板」用的；随手记是个小窗，要的是自由摆放，两回事。） */
function makeFloat(el, key, handle) {
  const K = 'flt-' + key;
  const clamp = () => {                       // 换了屏幕/缩了窗口，别把浮窗甩到看不见的地方
    const r = el.getBoundingClientRect();
    const x = Math.min(Math.max(8, r.left), Math.max(8, innerWidth - r.width - 8));
    const y = Math.min(Math.max(8, r.top), Math.max(8, innerHeight - r.height - 8));
    el.style.left = x + 'px'; el.style.top = y + 'px';
    el.style.right = 'auto'; el.style.bottom = 'auto';
  };
  const save = () => {
    const r = el.getBoundingClientRect();
    lsSet(K, JSON.stringify({ x: r.left, y: r.top, w: r.width, h: r.height }));
  };
  el.restore = () => {                        // 打开时调：恢复上次的位置和大小
    let v = null;
    try { v = JSON.parse(lsGet(K) || 'null'); } catch (_) { /* 拉不到就先空着，下次进来或轮询会补上 */ }
    if (!v) return;                           // 没拖过 → 用 CSS 里的默认位置和大小
    el.style.width = Math.max(280, v.w) + 'px';
    el.style.height = Math.max(220, v.h) + 'px';
    el.style.left = v.x + 'px'; el.style.top = v.y + 'px';
    el.style.right = 'auto'; el.style.bottom = 'auto';
    clamp();
  };

  // 拖标题栏 = 移动
  let dx = 0, dy = 0, moving = false;
  (handle || el).addEventListener('pointerdown', e => {
    if (e.target.closest('button, select, input, textarea, a')) return;   // 别抢控件的事件
    const r = el.getBoundingClientRect();
    dx = e.clientX - r.left; dy = e.clientY - r.top;
    moving = true;
    el.style.right = 'auto'; el.style.bottom = 'auto';
    (handle || el).setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  (handle || el).addEventListener('pointermove', e => {
    if (!moving) return;
    el.style.left = (e.clientX - dx) + 'px';
    el.style.top = (e.clientY - dy) + 'px';
  });
  (handle || el).addEventListener('pointerup', e => {
    if (!moving) return;
    moving = false;
    try { (handle || el).releasePointerCapture(e.pointerId); } catch (_) { /* 捕获失败不影响画线，指针事件照样收得到 */ }
    clamp(); save();
  });

  // 右下角小三角 = 改大小
  const grip = document.createElement('div');
  grip.className = 'flt-grip';
  el.appendChild(grip);
  let rw = 0, rh = 0, rx = 0, ry = 0, sizing = false;
  grip.addEventListener('pointerdown', e => {
    const r = el.getBoundingClientRect();
    rw = r.width; rh = r.height; rx = e.clientX; ry = e.clientY;
    sizing = true;
    grip.setPointerCapture(e.pointerId);
    e.preventDefault(); e.stopPropagation();
  });
  grip.addEventListener('pointermove', e => {
    if (!sizing) return;
    el.style.width = Math.max(300, Math.min(innerWidth - 24, rw + e.clientX - rx)) + 'px';
    el.style.height = Math.max(240, Math.min(innerHeight - 24, rh + e.clientY - ry)) + 'px';
  });
  grip.addEventListener('pointerup', e => {
    if (!sizing) return;
    sizing = false;
    try { grip.releasePointerCapture(e.pointerId); } catch (_) { /* 捕获失败不影响画线，指针事件照样收得到 */ }
    clamp(); save();
  });
  addEventListener('resize', clamp);
  return el;
}

/* ---- 随手记（悬浮球里的小记）----
   小记本来只有「进那个模块」一条路。但真正要记的时候，人都在看别的东西
   （做题、看时政、读范文）—— 跳走一趟回来，思路就断了。
   所以做成**浮在当前页面上**的一小块：写完点「记下」，页面纹丝不动。
   原来的小记模块**照样保留**（要整理、要翻历史还是得进去）。 */
let qnImgs = [];
let qnFiles = [];        // 随手记的附件（图片以外的文件：PDF/Word/表格…）
let qnFloat = null;
function qnOpen() {
  const box = $('#qnote');
  if (!box.classList.contains('hidden')) { qnClose(); return; }
  if (!qnFloat) qnFloat = makeFloat(box, 'qnote', $('#qnote .qn-head'));   // 可拖、可缩放
  box.restore();
  $('#qn-board').innerHTML = boardOptions(curNoteBoard, false);
  $('#qn-text').value = ''; $('#qn-tags').value = '';
  qnImgs = []; $('#qn-imgs').innerHTML = '';
  qnFiles = []; $('#qn-files').innerHTML = '';
  box.classList.remove('hidden');
  setTimeout(() => $('#qn-text').focus(), 30);
  if (window.fabClose) fabClose();
}
function qnClose() { $('#qnote').classList.add('hidden'); }
$('#qn-close').onclick = qnClose;
$('#qn-more').onclick = () => { qnClose(); openNotes(); };
async function qnAddImgs(files) {
  for (const f of [...files]) {
    if (!/^image\//.test(f.type)) continue;
    const im = { url: URL.createObjectURL(f), fileObj: f, name: f.name || 'img.jpg' };
    qnImgs.push(im);
    im.ready = compressImage(f).then(b => { im.fileObj = b; });   // 和小记一样：选图就压
  }
  qnRenderImgs();
}
$('#qn-file').addEventListener('change', async e => {
  const fs = [...e.target.files]; e.target.value = '';
  await qnAddImgs(fs);
});
// 附件：图片以外的任何格式（PDF / Word / 表格 / 压缩包…）。图片仍走上面的图片区。
async function qnAddFiles(files) {
  for (const f of [...files]) {
    const blob = await _materialize(f);
    qnFiles.push({ fileObj: blob, name: f.name || 'file', size: f.size || 0 });
  }
  qnRenderFiles();
}
$('#qn-attfile').addEventListener('change', async e => {
  const fs = [...e.target.files]; e.target.value = '';
  await qnAddFiles(fs);
});
// 拖进随手记：图片当图片、别的当附件（不再把非图片一律挡掉）。
// 浏览器走这里；桌面壳的拖放走 GTK 层的 __onDropFiles（也已按同样规则路由）。
(function bindQnDrop() {
  const el = $('#qnote');
  el.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('drop-on'); });
  el.addEventListener('dragleave', e => { if (!el.contains(e.relatedTarget)) el.classList.remove('drop-on'); });
  el.addEventListener('drop', e => {
    e.preventDefault(); el.classList.remove('drop-on');
    const all = [...(e.dataTransfer.files || [])];
    const imgs = all.filter(f => /^image\//.test(f.type));
    const atts = all.filter(f => !/^image\//.test(f.type));
    if (imgs.length) qnAddImgs(imgs);
    if (atts.length) qnAddFiles(atts);
  });
})();
bindImgPaste($('#qn-text'), qnAddImgs);       // Ctrl+V 粘图片
function qnRenderImgs() {
  $('#qn-imgs').innerHTML = qnImgs.map((im, i) =>
    `<div class="cp-thumb"><img src="${im.url}" data-qnbig="${i}"><button class="cp-x" data-qnr="${i}">×</button></div>`).join('');
}
function qnRenderFiles() {
  $('#qn-files').innerHTML = qnFiles.map((f, i) =>
    `<div class="cp-file">${iconFor((f.name.split('.').pop() || ''))} <span>${esc(f.name)}</span>` +
    `<button class="cp-x" data-qnfr="${i}">×</button></div>`).join('');
}
$('#qn-imgs').addEventListener('click', e => {
  const r = e.target.closest('[data-qnr]');
  if (r) { qnImgs.splice(+r.dataset.qnr, 1); qnRenderImgs(); return; }
  const b = e.target.closest('[data-qnbig]');
  if (b) lightbox(qnImgs[+b.dataset.qnbig].url);
});
$('#qn-files').addEventListener('click', e => {
  const r = e.target.closest('[data-qnfr]');
  if (r) { qnFiles.splice(+r.dataset.qnfr, 1); qnRenderFiles(); }
});
$('#qn-save').onclick = async () => {
  const text = $('#qn-text').value.trim();
  if (!text && !qnImgs.length && !qnFiles.length) { toast('写点什么吧', true); return; }
  const b = $('#qn-save'); b.disabled = true; b.textContent = '记下…';
  try {
    await Promise.all(qnImgs.filter(i => i.ready).map(i => i.ready));
    const fd = new FormData();
    fd.append('board', $('#qn-board').value);
    fd.append('content', text);
    fd.append('todos', '[]');
    fd.append('tags', JSON.stringify(
      $('#qn-tags').value.split(/[,，\s]+/).map(x => x.trim()).filter(Boolean)));
    qnImgs.forEach(i => fd.append('images', i.fileObj, i.name));
    qnFiles.forEach(f => fd.append('attachments', f.fileObj, f.name));   // 字段名和小记编辑器一致
    await api('/api/notes', { method: 'POST', body: fd });
    qnClose();
    toast('已记下');
    if ((stack[stack.length - 1] || {}).view === 'notes') { loadFeed(); refreshNoteCounts(); }
  } catch (e) { toast(e.message, true); }
  b.disabled = false; b.textContent = '记下';
};
