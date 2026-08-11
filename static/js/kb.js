/* 知识库 + 文档块编辑器（编辑器是知识库的一部分）
 *
 * 由 app.js 按它自己的区段边界切出（原 L1905-2438）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, IC, OFFICE_EXT, _svg, anchorMenu, api, appConfirm, artEm, back, c, composing, esc, fmtSize, iconFor, openAI, openSearch, openViewerUrl, push, stack, toast */

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
/* 封面色**不在这里**。八个色号是 style.css 里的 .kbc0…kbc7，主题开着时由
   js/daylight.js 的 dlKbCovers 顶掉那批变量。这里只负责挂对第几号 ——
   以前是在这行内写死八条渐变，主题因此一次也没管到知识库（行内样式谁也压不过，
   而那条扫样式表的守门测试又只认 CSS 里的颜色）。 */
const KB_COVER_N = 8;
const kbCoverCls = (nb) => 'kbc' + (((nb && nb.cover) || 0) % KB_COVER_N);
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
        <div class="kb-cover ${kbCoverCls(nb)}">${kbCoverInner()}</div>
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
  $('#nb-cover-pick').innerHTML = Array.from({ length: KB_COVER_N }, (_, i) =>
    `<div class="nb-cover-opt kbc${i}${i === nbCover ? ' sel' : ''}" data-cv="${i}"></div>`).join('');
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
  if (!(await appConfirm('删除整个知识库「' + $('#nb-in-name').value + '」？里面所有文档和分组都会删除，不可恢复！'))) return;
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
  $('#nb-cover').className = 'nb-cover ' + kbCoverCls(nb);
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
  if (dots) { e.stopPropagation(); openNodeMenu(dots, +dots.dataset.nodedots); return; }
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
function openNodeMenu(btn, id) {
  const n = findNode(id); if (!n) return;
  nodeMenuId = id;
  let html = `<button data-nm="rename"><span class="ci">${IC.edit}</span>重命名</button>`;
  if (n.type === 'group') html += `<button data-nm="add"><span class="ci">${ICON_PLUS}</span>在此分组内新建</button>`;
  if (n.type === 'doc') html += `<button data-nm="open"><span class="ci">${ICON_DOCF}</span>打开文档</button>`;
  html += `<button data-nm="del" style="color:#e0524d"><span class="ci">${IC.del}</span>删除</button>`;
  $('#node-menu-list').innerHTML = html;
  anchorMenu($('#node-menu'), btn);
}
$('#node-menu').addEventListener('click', async e => {
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
    if (!(await appConfirm('删除「' + (n.title || '该项') + '」' + (n.type === 'group' ? '及其下所有内容' : '') + '？不可恢复'))) return;
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
$('#kbp-input').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') kbpClose($('#kbp-input').value.trim()); });
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
    t += `</tbody></table><div class="tbl-tools"><button data-tbl="row" data-tid="${b.id}">${artEm('＋')}行</button><button data-tbl="col" data-tid="${b.id}">${artEm('＋')}列</button></div></div>`;
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
  if (!composing(e) && e.key === 'Enter' && !e.shiftKey && t !== 'code') {
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
$('#doc-title').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') { e.preventDefault(); if (DOC && DOC.blocks[0]) focusBlock(DOC.blocks[0].id); } });

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
let _docSaveFailed = false;
async function saveDoc() {
  if (!DOC) return;
  const title = $('#doc-title').textContent.trim() || '无标题文档';
  try {
    await api('/api/kb/nodes/' + DOC.id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, content: DOC.blocks }) });
    if (_docSaveFailed) { _docSaveFailed = false; toast('已重新保存'); }   // 网回来了，让人安心
  } catch (e) {
    // 这是**自动**保存（改完 900ms 触发），原先是空 catch：网一断，用户接着往下写，
    // 全程以为存着，其实一个字都没上去。项目里手动保存都会 toast(err.message, true)，
    // 自动保存更该说 —— 只是不能每 900ms 弹一次，所以只在「由成功转为失败」时说一次。
    console.warn('[文档] 自动保存失败：%s', (e && e.message) || e);
    if (!_docSaveFailed) {
      _docSaveFailed = true;
      toast('保存失败：' + ((e && e.message) || '网络异常') + '（内容还在，请检查网络）', true);
    }
  }
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
