/* 资料库 + 幻灯片播放（它是资料的查看器）
 *
 * 由 app.js 按它自己的区段边界切出（原 L1278-1716）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, ALL_BOARDS, Ink, KB, api, appConfirm,
   appPrompt, c, esc, fmtSize, hl, inkHere,
   kbPrompt, openMatMenu, push, toast */

/* ================= 资料库 ================= */
const EXT_ICON = {
  pdf: '📕', doc: '📘', docx: '📘', xls: '📗', xlsx: '📗', ppt: '📙', pptx: '📙',
  png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', webp: '🖼️', svg: '🖼️', bmp: '🖼️',
  html: '🌐', htm: '🌐', txt: '📄', md: '📄', csv: '📊', zip: '🗜️',
};
const iconFor = (ext) => EXT_ICON[(ext || '').replace('.', '')] || '📎';
const OFFICE_EXT = ['.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp', '.rtf'];
let matBoard = '', matCustomBoards = [];
async function renderMatFilter() {
  try {
    const d = await api('/api/materials/boards');
    (d.boards || []).forEach(b => { if (b && !ALL_BOARDS.includes(b) && !matCustomBoards.includes(b)) matCustomBoards.push(b); });
  } catch (_) {}
  const all = ALL_BOARDS.concat(matCustomBoards);
  $('#mat-filter').innerHTML = `<button class="chip ${matBoard === '' ? 'active' : ''}" data-mb="">全部</button>` +
    all.map(b => `<button class="chip ${b === matBoard ? 'active' : ''}" data-mb="${esc(b)}">${esc(b)}</button>`).join('') +
    `<button class="chip chip-newcat" id="mat-newcat">＋ 分类</button>`;
}
async function saveMatBoards() {
  try {
    await api('/api/materials/boards', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ boards: matCustomBoards }),
    });
  } catch (e) {
    // 分类是用户手建/手删的，存不上就得说 —— 否则刷新一下白建了
    console.warn('[资料库] 自定义分类保存失败：%s', (e && e.message) || e);
    toast('分类没保存上：' + ((e && e.message) || '网络异常'), true);
  }
}
/* 长按/右键自定义分类 → 删掉它（里面的资料会回到「全部」，不会丢） */
$('#mat-filter').addEventListener('contextmenu', async e => {
  const c = e.target.closest('[data-mb]');
  if (!c || !c.dataset.mb || !matCustomBoards.includes(c.dataset.mb)) return;
  e.preventDefault();
  const b = c.dataset.mb;
  if (!await appConfirm('删除分类「' + b + '」？里面的资料不会删，只是回到「全部」。',
    { title: '资料分类', okText: '删除分类' })) return;
  matCustomBoards = matCustomBoards.filter(x => x !== b);
  await saveMatBoards();
  if (matBoard === b) matBoard = '';
  renderMatFilter(); loadMaterials();
  toast('分类已删除');
});

function openMaterials() {
  matBoard = '';
  renderMatFilter();
  push({ view: 'materials' });
  loadMaterials();
}
$('#mat-filter').addEventListener('click', async e => {
  if (e.target.closest('#mat-newcat')) {
    const name = await appPrompt('新建分类', '分类名，如：晨读');
    const v = (name || '').trim().slice(0, 20);
    if (!v) return;
    if (!matCustomBoards.includes(v) && !ALL_BOARDS.includes(v)) matCustomBoards.push(v);
    await saveMatBoards();            // 存到服务器：不然新建了但还没传东西的分类，重启就没了
    matBoard = v;                     // 选中新分类：之后上传/拍照默认归入它
    renderMatFilter(); loadMaterials();
    toast('分类「' + v + '」已保存，现在上传的资料会归入它');
    return;
  }
  const c = e.target.closest('[data-mb]'); if (!c) return;
  matBoard = c.dataset.mb;
  document.querySelectorAll('#mat-filter .chip').forEach(x => x.classList.toggle('active', x.dataset.mb === matBoard));
  loadMaterials();
});
async function loadMaterials() {
  try {
    const d = await api('/api/materials' + (matBoard ? '?board=' + encodeURIComponent(matBoard) : ''));
    let newCat = false;
    (d.items || []).forEach(m => { const b = m.board; if (b && !ALL_BOARDS.includes(b) && !matCustomBoards.includes(b)) { matCustomBoards.push(b); newCat = true; } });
    if (newCat) renderMatFilter();
    const box = $('#mat-list');
    if (!d.items.length) { box.innerHTML = ''; $('#mat-empty').classList.remove('hidden'); return; }
    $('#mat-empty').classList.add('hidden');
    box.innerHTML = d.items.map(m => `
      <div class="mat-item" data-id="${m.id}" data-view="${m.viewable ? 1 : 0}" data-ext="${esc(m.ext || '')}">
        <span class="mat-icon">${iconFor(m.ext)}</span>
        <div class="mat-info">
          <div class="mat-name">${esc(m.title || m.orig_name)}</div>
          <div class="mat-meta">${esc((m.ext || '').replace('.', '').toUpperCase())} · ${fmtSize(m.size)}${m.board ? ' · ' + esc(m.board) : ''}${m.shared ? ` · <span class="mat-shared">👥 ${esc(m.shared_from)} 共享</span>` : ''}</div>
        </div>
        <div class="mat-actions">
          <button class="iconbtn mat-more" data-act="menu" title="更多操作">⋮</button>
        </div>
      </div>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#mat-list').addEventListener('click', async e => {
  const item = e.target.closest('.mat-item'); if (!item) return;
  const id = item.dataset.id;
  const act = e.target.closest('[data-act]');
  if (act && act.dataset.act === 'menu') {
    e.stopPropagation();
    openMatMenu(id, item.querySelector('.mat-name').textContent, item.dataset.ext);
    return;
  }
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
      if (!(await appConfirm('删除这个资料？'))) return;
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
  setViewerFull(false);
  $('#viewer-name').textContent = name;
  $('#viewer-dl').href = dlUrl || fileUrl;
  viewerTextUrl = textUrl || null;
  // id 带上文件本身：批注按「这一份文档」存。不带的话每份 .md/.txt 都共用 view:viewer 这一个
  // key，07-15 上画的圈打开 07-14 也会浮出来。
  push({ view: 'viewer', title: name, id: (fileUrl || '').slice(-80) });
  if (READER_EXT.includes(ext)) { $('#viewer-mode').classList.add('hidden'); openReader(fileUrl, ext); return; }
  // 原版预览（pdf.js / iframe）
  $('#viewer-reader').classList.add('hidden');
  $('#reader-tools').classList.add('hidden');
  $('#viewer-frame').classList.remove('hidden');
  const isPdf = (ext === '.pdf' || OFFICE_EXT.includes(ext));
  $('#viewer-frame').src = isPdf
    ? '/pdfjs/web/viewer.html?file=' + encodeURIComponent(fileUrl) : fileUrl;
  $('#viewer-ink').classList.toggle('hidden', !isPdf);   // 批注只对 PDF/Office 预览给（跟随内部滚动）
  if (isPdf) $('#viewer-frame').onload = hidePdfjsPen;   // 藏掉 pdf.js 自带那支「歪笔」，只留我们的批注
  // pdf/office 且有文本接口 → 提供「阅读模式」切换
  const canRead = (ext === '.pdf' || OFFICE_EXT.includes(ext)) && viewerTextUrl;
  $('#viewer-mode').classList.toggle('hidden', !canRead);
  $('#viewer-mode').textContent = '阅读模式';
  probeSlides(fileUrl);
}
// pdf.js 自带的手写/文本编辑器那支笔笔尖是歪的（改它的压缩代码风险大）。同源，直接往 iframe 注 CSS
// 把它工具栏里的编辑按钮藏掉，只用我们对齐准确、能存能擦的「✏️ 批注」。
function hidePdfjsPen() {
  const f = $('#viewer-frame');
  try {
    const doc = f.contentDocument; if (!doc) return;
    if (doc.getElementById('gk-hidepen')) return;
    const st = doc.createElement('style'); st.id = 'gk-hidepen';
    st.textContent = '#editorModeButtons,#editorInk,#editorFreeText,#editorStamp,'
      + '#editorHighlight,#editorInkButton,#editorModeSeparator{display:none!important}';
    doc.head.appendChild(st);
  } catch (_) {}
}

/* ================= 幻灯片播放（逐页出图） =================
   整份 PDF 十几 MB，家里上行只有一百多 KB/s，打开要一分多钟；
   单页 JPEG 只有 100KB 上下，所以按需逐页拉图，翻到哪拉到哪。 */
let ssMid = 0, ssTotal = 0, ssPage = 1;
function probeSlides(fileUrl) {
  $('#viewer-play').classList.add('hidden');
  const m = /\/api\/materials\/(\d+)\/view/.exec(fileUrl || '');
  if (!m) { ssMid = 0; return; }
  const mid = +m[1];
  api('/api/materials/' + mid + '/pages').then(d => {
    if (!d.slides || !d.pages) return;
    ssMid = mid; ssTotal = d.pages;
    $('#viewer-play').textContent = d.ppt ? '▶ 播放' : '▶ 逐页看';
    $('#viewer-play').classList.remove('hidden');
  }).catch(() => {});
}
function ssUrl(n) { return '/api/materials/' + ssMid + '/page/' + n; }
function ssPrefetch(n) { if (n >= 1 && n <= ssTotal) new Image().src = ssUrl(n); }
function ssShow(n) {
  if (!ssMid || n < 1 || n > ssTotal) return;
  ssPage = n;
  $('#ss-page').textContent = n + ' / ' + ssTotal;
  $('#ss-load').classList.remove('hidden');
  const img = $('#ss-img');
  img.onload = () => { $('#ss-load').classList.add('hidden'); ssPrefetch(n + 1); ssPrefetch(n - 1); };
  img.onerror = () => { $('#ss-load').textContent = '这一页加载失败'; };
  img.src = ssUrl(n);
}
function openSlideshow() {
  if (!ssMid || !ssTotal) return;
  $('#slideshow').classList.remove('hidden');
  document.body.classList.add('ss-open');
  try { if (window.GongkaoNative && GongkaoNative.fullscreen) GongkaoNative.fullscreen(true); } catch (_) {}
  ssShow(1);
}
function closeSlideshow() {
  $('#slideshow').classList.add('hidden');
  document.body.classList.remove('ss-open');
  $('#ss-img').src = '';
  try { if (window.GongkaoNative && GongkaoNative.fullscreen) GongkaoNative.fullscreen(false); } catch (_) {}
}
$('#viewer-play').onclick = openSlideshow;
$('#ss-close').onclick = closeSlideshow;
$('#ss-prev').onclick = () => ssShow(ssPage - 1);
$('#ss-next').onclick = () => ssShow(ssPage + 1);
$('#ss-hl').onclick = () => ssShow(ssPage - 1);
$('#ss-hr').onclick = () => ssShow(ssPage + 1);
document.addEventListener('keydown', e => {
  if ($('#slideshow').classList.contains('hidden')) return;
  if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') ssShow(ssPage + 1);
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') ssShow(ssPage - 1);
  else if (e.key === 'Escape') closeSlideshow();
});
(function ssSwipe() {
  let x0 = 0, y0 = 0;
  const el = $('#slideshow');
  el.addEventListener('touchstart', e => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
  el.addEventListener('touchend', e => {
    const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
    if (Math.abs(dx) > 55 && Math.abs(dx) > Math.abs(dy)) ssShow(ssPage + (dx < 0 ? 1 : -1));
    else if (dy > 90 && Math.abs(dy) > Math.abs(dx)) closeSlideshow();   // 下滑退出
  }, { passive: true });
})();
let _viewerFull = false;
function setViewerFull(on) {
  _viewerFull = on;
  document.body.classList.toggle('viewer-full', on);
  $('#viewer-full').textContent = on ? '⛶ 退出全屏' : '⛶ 全屏';
  // 让原生壳一起隐藏状态栏/导航栏（沉浸式），否则「全屏」只全屏了网页那一半
  try {
    if (window.GongkaoNative && typeof GongkaoNative.fullscreen === 'function') GongkaoNative.fullscreen(on);
  } catch (_) {}
}
$('#viewer-full').onclick = () => setViewerFull(!_viewerFull);
$('#viewer-exit').onclick = () => setViewerFull(false);
$('#viewer-ink').onclick = () => inkHere();
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
  // 字号/字体一变正文就重排，批注的锚要重新定位，否则笔迹还停在旧位置（这正是原来的病）
  if (window.Ink && Ink.on) { Ink.relayout(); Ink.paint(); }
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
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) { flushPara(); closeList(); const lv = m[1].length; html += '<h' + lv + '>' + inline(m[2]) + '</h' + lv + '>'; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flushPara(); closeList(); html += '<hr>'; continue; }
    if ((m = line.match(/^\s*>\s?(.*)$/))) { flushPara(); closeList(); html += '<blockquote>' + inline(m[1]) + '</blockquote>'; continue; }
    if ((m = line.match(/^\s*[-*+]\s+(.*)$/))) { flushPara(); if (listType !== 'ul') { closeList(); html += '<ul>'; listType = 'ul'; } html += '<li>' + inline(m[1]) + '</li>'; continue; }
    if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) { flushPara(); if (listType !== 'ol') { closeList(); html += '<ol>'; listType = 'ol'; } html += '<li>' + inline(m[1]) + '</li>'; continue; }
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
  $('#up-board').innerHTML = `<option value="">未分类</option>`
    + ALL_BOARDS.concat(matCustomBoards).map(b => `<option ${b === matBoard ? 'selected' : ''}>${esc(b)}</option>`).join('')
    + `<option value="__new__">＋ 新建分类…</option>`;
  $('#up-title').value = ''; $('#up-file').value = '';
  $('#upload-modal').classList.remove('hidden');
};
$('#up-cancel').onclick = () => $('#upload-modal').classList.add('hidden');
$('#upload-modal').addEventListener('click', e => { if (e.target.id === 'upload-modal') $('#upload-modal').classList.add('hidden'); });
/* 带进度 + 断网重试的上传：服务器在家里，上行只有一百多 KB/s，
   fetch 没有进度事件、一断就整个失败，所以这里用 XHR。 */
function uploadXhr(fd, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/materials');
    xhr.timeout = 15 * 60 * 1000;              // 大文件慢，给足时间
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve(JSON.parse(xhr.responseText || '{}'));
      let msg = '上传失败（' + xhr.status + '）';
      try { msg = JSON.parse(xhr.responseText).error || msg; } catch (_) {}
      reject(new Error(msg));
    };
    xhr.onerror = () => reject(new Error('网络中断'));
    xhr.ontimeout = () => reject(new Error('上传超时'));
    xhr.send(fd);
  });
}
function upProg(show, pct, txt) {
  $('#up-prog').classList.toggle('hidden', !show);
  if (!show) return;
  $('#up-prog').querySelector('i').style.width = Math.round(pct * 100) + '%';
  $('#up-prog').querySelector('.up-txt').textContent = txt;
}
$('#up-go').onclick = async () => {
  const files = [...$('#up-file').files];
  if (!files.length) { toast('请选择文件', true); return; }
  const board = $('#up-board').value, title = $('#up-title').value.trim();
  $('#up-go').disabled = true; $('#up-go').textContent = '上传中…';
  $('#up-cancel').disabled = true;
  let ok = 0;
  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    const label = files.length > 1 ? `(${i + 1}/${files.length}) ${file.name}` : file.name;
    let done = false;
    for (let attempt = 1; attempt <= 3 && !done; attempt++) {   // 网络抖动自动重试
      const fd = new FormData();
      fd.append('file', file);
      fd.append('board', board);
      fd.append('section', '');
      fd.append('title', files.length === 1 ? title : '');       // 多个文件各用文件名
      try {
        await uploadXhr(fd, p => upProg(true, p,
          `${label} ${Math.round(p * 100)}%${attempt > 1 ? ' · 第' + attempt + '次尝试' : ''}`));
        ok++; done = true;
      } catch (e) {
        if (attempt === 3) { toast(file.name + '：' + e.message, true); }
        else { upProg(true, 0, label + ' 重试中…'); await new Promise(r => setTimeout(r, 1500)); }
      }
    }
  }
  upProg(false);
  $('#up-go').disabled = false; $('#up-go').textContent = '上传';
  $('#up-cancel').disabled = false;
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
