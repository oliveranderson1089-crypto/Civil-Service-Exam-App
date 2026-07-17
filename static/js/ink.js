/* 草稿纸 / 文本锚 / 通用手写批注层 / 通用停靠
 *
 * 由 app.js 按它原有的区段边界切出（原 L8872-10115）。顺序即原顺序 —— index.html 里
 * 按同样次序引入，执行序与拆分前逐字节一致。
 *
 * 下面 /* global *​/ 是这个模块的依赖清单：它用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，这就是现成的 import 表。
 */
/* global $, ANN_SKIP, ME, api, appConfirm, back,
   c, doSave, draft, esc, hidePdfjsPen, hl,
   loadDrafts, lsDel, lsGet, lsSet, mkNodes, mkPageRoot,
   mkText, mkWrapOne, probeSlides, push, render, stack,
   toast */

/* ================= 草稿纸（做题时演算用；只写不识别） =================
   笔/荧光笔/橡皮 · 数位板压感 · 撤销重做 · 多页 · 方格/横线纸 · 存为图片 ·
   自动保存到本地（切题、刷新、关掉再开都还在）。 */
/* 草稿纸随时可调用（悬浮球里点开），停靠位可拖：下/右/左/上/全屏 */
const PAD_INK = '#1a2230';                              // 默认墨色（夜间自动转浅）
const PAD_COLORS = [PAD_INK, '#1a6fb5', '#c0392b', '#1e8449', '#f0a500'];
const PAD_BGICON = ['▢', '⊞', '☰'];                     // 空白 / 方格 / 横线
let padPages = [{ st: [], rd: [] }], padPg = 0;
let padTool = 'pen', padColor = PAD_INK, padSize = 3, padBg = 1;
let padCur = null, padDrawing = false, padSawPen = false, padSaveT = null, padInited = false;
let padCv, padCtx, padBase, padBaseCtx, padRaf = 0;
let padMode = 'scratch', padDraftId = null;     // scratch=做题时的随手草稿纸(存本地)；draft=草稿本(存服务器)

const padDark = () => document.body.classList.contains('dark');
const padW = () => padCv.clientWidth || 1;
const padCol = (c, dark) => (c === PAD_INK && dark) ? '#e8edf5' : c;

function padPt(e) {
  const r = padCv.getBoundingClientRect(), w = r.width || 1;
  return {
    x: (e.clientX - r.left) / w, y: (e.clientY - r.top) / w,      // 按宽度归一化：换屏/全屏不变形
    p: (e.pointerType === 'pen' && e.pressure > 0) ? e.pressure : 0,
  };
}

function padPaper(ctx, w, h, dark) {
  ctx.save();
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = dark ? '#0f141e' : '#fff';
  ctx.fillRect(0, 0, w, h);
  if (padBg) {                                                    // 0=空白 1=方格 2=横线
    ctx.strokeStyle = dark ? 'rgba(160,180,210,.13)' : 'rgba(30,70,130,.10)';
    ctx.lineWidth = 1;
    const g = 26;
    ctx.beginPath();
    for (let y = g; y < h; y += g) { ctx.moveTo(0, y + .5); ctx.lineTo(w, y + .5); }
    if (padBg === 1) for (let x = g; x < w; x += g) { ctx.moveTo(x + .5, 0); ctx.lineTo(x + .5, h); }
    ctx.stroke();
  }
  ctx.restore();
}

function padDraw(ctx, s, W, dark) {
  const pts = s.pts;
  if (!pts || !pts.length) return;
  ctx.save();
  ctx.lineJoin = ctx.lineCap = 'round';
  const base = s.size * W;                                        // 归一化粗细 → 当前屏幕像素
  let wid = base;
  if (s.tool === 'eraser') {
    ctx.globalCompositeOperation = 'destination-out';             // 只擦笔迹，不擦纸上的格子
    ctx.strokeStyle = '#000'; wid = base * 5;
  } else {
    ctx.strokeStyle = padCol(s.color, dark);
    if (s.tool === 'hl') { ctx.globalAlpha = .3; wid = base * 3.2; }
  }
  if (pts.length === 1) {                                         // 点一下 = 一个点
    ctx.beginPath(); ctx.arc(pts[0].x * W, pts[0].y * W, Math.max(.6, wid / 2), 0, 6.2832);
    ctx.fillStyle = ctx.strokeStyle; ctx.fill(); ctx.restore(); return;
  }
  const varW = s.tool === 'pen' && pts.some(p => p.p > 0);        // 数位板：有压感就逐段变粗细
  if (!varW) {
    ctx.lineWidth = wid;
    ctx.beginPath(); ctx.moveTo(pts[0].x * W, pts[0].y * W);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x * W, pts[i].y * W);
    ctx.stroke();
  } else {
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i];
      ctx.lineWidth = wid * (.35 + 1.1 * (((a.p || .5) + (b.p || .5)) / 2));
      ctx.beginPath(); ctx.moveTo(a.x * W, a.y * W); ctx.lineTo(b.x * W, b.y * W); ctx.stroke();
    }
  }
  ctx.restore();
}

function padPaint() {                                             // 纸 + 已完成图层 + 正在画的这笔
  const w = padCv.clientWidth, h = padCv.clientHeight;
  padPaper(padCtx, w, h, padDark());
  padCtx.drawImage(padBase, 0, 0, w, h);
  if (padCur) padDraw(padCtx, padCur, padW(), padDark());
}
function padRebuild() {                                           // 重建"已完成"图层（撤销/翻页/换主题/改尺寸后）
  padBaseCtx.save();
  padBaseCtx.setTransform(1, 0, 0, 1, 0, 0);
  padBaseCtx.clearRect(0, 0, padBase.width, padBase.height);
  padBaseCtx.restore();
  const dark = padDark(), W = padW();
  for (const s of padPages[padPg].st) padDraw(padBaseCtx, s, W, dark);
  padPaint(); padSyncUI();
}
function padFit() {
  const w = padCv.clientWidth, h = padCv.clientHeight;
  $('#pad').classList.toggle('narrow', $('#pad').clientWidth < 470);   // 纸窄了工具栏就用紧凑排版
  if (!w || !h) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  padCv.width = padBase.width = Math.round(w * dpr);
  padCv.height = padBase.height = Math.round(h * dpr);
  padCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  padBaseCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  padRebuild();
}

function padDown(e) {
  if (e.pointerType === 'pen') padSawPen = true;
  if (e.pointerType === 'touch' && padSawPen) return;             // 用过笔之后忽略触摸 = 防手掌误触
  if (e.button > 0) return;
  e.preventDefault();
  try { padCv.setPointerCapture(e.pointerId); } catch (_) {}
  padDrawing = true;
  padCur = { tool: padTool, color: padColor, size: padSize / padW(), pts: [padPt(e)] };
  padPaint();
}
function padMove(e) {
  if (!padDrawing || !padCur) return;
  e.preventDefault();
  // 高频合并采样能让线更顺；但有的实现（含部分 WebKit）会返回空表，那就退回事件本身，
  // 否则一笔只剩落笔那个点，画出来是个小点。
  let evs = [];
  try { if (e.getCoalescedEvents) evs = e.getCoalescedEvents(); } catch (_) {}
  if (!evs.length) evs = [e];
  for (const ev of evs) padCur.pts.push(padPt(ev));
  if (!padRaf) padRaf = requestAnimationFrame(() => { padRaf = 0; padPaint(); });
}
function padUp() {
  if (!padDrawing) return;
  padDrawing = false;
  if (!padCur) return;
  const pg = padPages[padPg];
  pg.st.push(padCur); pg.rd = [];                                 // 新落笔 → 清空重做栈
  padDraw(padBaseCtx, padCur, padW(), padDark());
  padCur = null;
  padPaint(); padSyncUI(); padSaveSoon();
}

function padUndo() { const p = padPages[padPg]; if (!p.st.length) return; p.rd.push(p.st.pop()); padRebuild(); padSaveSoon(); }
function padRedo() { const p = padPages[padPg]; if (!p.rd.length) return; p.st.push(p.rd.pop()); padRebuild(); padSaveSoon(); }
function padGo(i) { padPg = Math.max(0, Math.min(padPages.length - 1, i)); padCur = null; padRebuild(); padSaveSoon(); }

function padSyncUI() {
  const pg = padPages[padPg];
  $('#pad-pg').textContent = (padPg + 1) + ' / ' + padPages.length;
  $('#pad-undo').disabled = !pg.st.length;
  $('#pad-redo').disabled = !pg.rd.length;
  $('#pad-prev').disabled = padPg === 0;
  $('#pad-next').disabled = padPg >= padPages.length - 1;
  $('#pad-bg').textContent = PAD_BGICON[padBg];
  $('#pad-size').value = padSize;
  document.querySelectorAll('#pad .pad-t[data-tool]').forEach(b => b.classList.toggle('on', b.dataset.tool === padTool));
  $('#pad-colors').innerHTML = PAD_COLORS.map(c =>
    `<i class="pad-c${c === padColor && padTool !== 'eraser' ? ' on' : ''}" data-c="${c}" style="background:${padCol(c, padDark())}"></i>`).join('');
}

/* 笔迹存储格式：本地「随手草稿纸」和云端「草稿本」共用（坐标已按画布宽度归一化） */
function padData() {
  const r = (n) => Math.round(n * 1e4) / 1e4;
  return {
    bg: padBg,
    pages: padPages.map(p => ({
      st: p.st.map(s => ({ t: s.tool, c: s.color, w: r(s.size), p: s.pts.map(q => [r(q.x), r(q.y), Math.round((q.p || 0) * 100) / 100]) })),
    })),
  };
}
function padSetData(d) {
  const ps = (d && d.pages && d.pages.length) ? d.pages : [{ st: [] }];
  padPages = ps.map(p => ({
    st: (p.st || []).map(s => ({ tool: s.t, color: s.c, size: s.w, pts: (s.p || []).map(q => ({ x: q[0], y: q[1], p: q[2] })) })),
    rd: [],
  }));
  padBg = (d && d.bg != null) ? (d.bg | 0) : 1;
  padPg = Math.min((d && (d.pg | 0)) || 0, padPages.length - 1);
}
/* 第一页的缩略图（白底黑字），给草稿本列表当封面 */
function padThumb() {
  const w = padCv.clientWidth || 1, h = padCv.clientHeight || 1, W = 320, k = W / w;
  const c = document.createElement('canvas');
  c.width = W; c.height = Math.max(1, Math.round(h * k));
  const x = c.getContext('2d');
  x.setTransform(k, 0, 0, k, 0, 0);
  padPaper(x, w, h, false);
  for (const s of padPages[0].st) padDraw(x, s, w, false);
  return c.toDataURL('image/jpeg', .72);
}

/* 随手草稿纸：存本地（切题/刷新/关掉再开都还在，按用户分开存） */
const padKey = () => 'pad:' + ((ME && (ME.id || ME.username)) || 'x');
function padSaveSoon() {
  clearTimeout(padSaveT);
  if (padMode === 'draft') padStatus('未保存…');
  padSaveT = setTimeout(() => (padMode === 'draft' ? padDraftSave() : padSave()), padMode === 'draft' ? 1200 : 700);
}
function padSave() {
  // 存不下不会中断做题（lsSet 不抛，只提示一次），但草稿丢了用户得知道
  lsSet(padKey(), JSON.stringify(Object.assign(padData(), { pg: padPg })));
}
function padLoad() {
  try {
    const d = JSON.parse(lsGet(padKey()) || 'null');
    if (d && d.pages && d.pages.length) padSetData(d);
  } catch (_) {}
}

/* 草稿本：存服务器（多本、手机电脑同步） */
function padStatus(t) { $('#pad-st').textContent = t || ''; }
async function padDraftSave() {
  if (!padDraftId) return;
  const id = padDraftId;                       // 存的过程中可能已经关掉了，用当时的 id
  padStatus('保存中…');
  try {
    await api('/api/drafts/' + id, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: padData(), pages: padPages.length, thumb: padThumb() }),
    });
    if (padDraftId === id) padStatus('已保存');
  } catch (_) {
    if (padDraftId === id) padStatus('没存上·稍后重试');
  }
}

function padInit() {
  padInited = true;
  padCv = $('#pad-cv'); padCtx = padCv.getContext('2d');
  padBase = document.createElement('canvas'); padBaseCtx = padBase.getContext('2d');
  padDk = createDock($('#pad'), 'padDock', 'bottom', padFit);
  padLoad();

  padCv.addEventListener('pointerdown', padDown);
  padCv.addEventListener('pointermove', padMove);
  padCv.addEventListener('pointerup', padUp);
  padCv.addEventListener('pointercancel', padUp);
  padCv.addEventListener('pointerleave', padUp);

  $('#pad').addEventListener('click', e => {
    const t = e.target.closest('.pad-t[data-tool]');
    if (t) { padTool = t.dataset.tool; padSyncUI(); return; }
    const c = e.target.closest('.pad-c');
    if (c) { padColor = c.dataset.c; if (padTool === 'eraser') padTool = 'pen'; padSyncUI(); }
  });
  $('#pad-size').oninput = (e) => { padSize = +e.target.value; };
  $('#pad-undo').onclick = padUndo;
  $('#pad-redo').onclick = padRedo;
  $('#pad-prev').onclick = () => padGo(padPg - 1);
  $('#pad-next').onclick = () => padGo(padPg + 1);
  $('#pad-add').onclick = () => {
    if (padPages.length >= 20) { toast('最多 20 页', true); return; }
    padPages.splice(padPg + 1, 0, { st: [], rd: [] });
    padGo(padPg + 1); toast('已新增一页');
  };
  $('#pad-bg').onclick = () => { padBg = (padBg + 1) % 3; padPaint(); padSyncUI(); padSaveSoon(); };
  $('#pad-clear').onclick = async () => {
    const many = padPages.length > 1;
    const r = await appConfirm('清空这一页的草稿？' + (many ? '（也可以直接删掉这一页）' : ''),
      { title: '草稿纸', okText: '清空本页', altText: many ? '删除本页' : '', altDanger: true });
    if (r === 'alt') { padPages.splice(padPg, 1); padGo(Math.min(padPg, padPages.length - 1)); toast('已删除本页'); }
    else if (r === true) { padPages[padPg] = { st: [], rd: [] }; padRebuild(); padSaveSoon(); toast('本页已清空'); }
  };
  $('#pad-png').onclick = () => {                                 // 导出白底黑字，方便打印/贴到错题本
    const w = padCv.clientWidth, h = padCv.clientHeight, k = 2;
    const c = document.createElement('canvas');
    c.width = w * k; c.height = h * k;
    const x = c.getContext('2d');
    x.setTransform(k, 0, 0, k, 0, 0);
    padPaper(x, w, h, false);
    for (const s of padPages[padPg].st) padDraw(x, s, w, false);
    const a = document.createElement('a');
    a.download = '草稿-第' + (padPg + 1) + '页.png';
    a.href = c.toDataURL('image/png');
    document.body.appendChild(a); a.click(); a.remove();
    toast('已保存为图片');
  };
  $('#pad-mode').onclick = () => padDk.toggleFull();               // 全屏 ⇄ 还原
  $('#pad-close').onclick = padClose;
  $('#pad-dock').addEventListener('pointerdown', (e) => padDk.dockDrag(e));

  let rzT = null;
  addEventListener('resize', () => {
    if ($('#pad').classList.contains('hidden')) return;
    clearTimeout(rzT); rzT = setTimeout(padFit, 120);
  });
  document.addEventListener('keydown', e => {
    if ($('#pad').classList.contains('hidden')) return;
    const k = (e.key || '').toLowerCase();
    if (e.ctrlKey && k === 'z') { e.preventDefault(); e.shiftKey ? padRedo() : padUndo(); }
    else if (e.ctrlKey && k === 'y') { e.preventDefault(); padRedo(); }
    else if (e.ctrlKey && k === 's') { e.preventDefault(); if (padMode === 'draft') { clearTimeout(padSaveT); padDraftSave(); } }
    else if (e.key === 'Escape') padClose();
  });
}

/* ================= 文本锚：把标注钉在「那句话」上，而不是「那个像素」上 =================
   坐标锚定的批注，内容一重排就和它标的东西脱节：实测在阅读模式画一道线、点一下工具栏的
   「A+」（16px→20px），那一条就跑了 94px、笔迹纹丝不动＝错位 173px（约 2.3 行）；
   同一份批注拿到手机上（1600px→390px）错位 180px。所以「批注存服务器同步到手机」这件事，
   在坐标模型下是没有意义的 —— 同步过去全落在别的段落上。
   这里改成按文本定位：存下「那句话」+ 前后文，重排后按文本把位置找回来。
   和 AI 划重点同一个路子（mkWrapOne 就是按文本偏移 + Range 定位的），
   也就是 W3C Web Annotation 的 TextQuoteSelector。 */
const ANN_CTX = 24;          // 前后各取多少字消歧（同一句话在一页里可能出现多次）
const ANN_QLEN = 16;         // 锚句取多长：够唯一又不至于内容一改就整段对不上

// (文本节点, 节点内偏移) → 全文偏移；mkNodes 给的就是「节点 → 起始偏移」表
function annPosOf(nodes, node, off) {
  for (const { n, start } of nodes) if (n === node) return start + off;
  return -1;
}
// 全文偏移 → Range（拿它的 getBoundingClientRect 得到「这句话现在在屏幕哪」）
function annRangeOf(nodes, pos, len) {
  let r = null;
  for (const { n, start } of nodes) {
    const end = start + n.nodeValue.length;
    if (!r && pos >= start && pos < end) { r = document.createRange(); r.setStart(n, pos - start); }
    if (r && pos + len > start && pos + len <= end) { r.setEnd(n, pos + len - start); return r; }
  }
  return null;
}
// 整篇正文只遍历一次，给 relayout 那种「一次定位很多笔」的场景复用（每笔各算一遍＝2N 次全文遍历）。
// 块之间插 '\n'：锚句才不会横跨标题和正文（见 mkText 的注释）。
function annCtx(root) {
  return root ? { full: mkText(root, ANN_SKIP, '\n'), nodes: mkNodes(root, ANN_SKIP, '\n') } : null;
}
// 屏幕点 → { a: 锚, rect: 锚句现在的位置 }。画在空白处/图片上锚不住 → null，调用方退回 pixel 锚。
// doc：这个点属于哪个文档 —— PDF 在同源 iframe 里，得用它自己的 document 做命中测试（x/y 也要是
// 那个文档的视口坐标）。mkNodes/mkText/Range 跨 document 直接可用（实测过），所以只有这里要区分。
function annAnchorAt(root, x, y, doc) {
  if (!root) return null;
  doc = doc || document;
  let rg = null;
  // caretRangeFromPoint 走的是命中测试：批注画布正盖在文字上，不让开的话命中的是画布（拿到 BODY），
  // 一个锚都生成不出来。临时 pointer-events:none 让它「看穿」画布，取完立刻恢复。
  // （PDF 那条路的 doc 在 iframe 里，画布在父文档、本来就不挡它，让开也无妨。）
  const cv = $('#ink-cv'), pe = cv ? cv.style.pointerEvents : null;
  if (cv) cv.style.pointerEvents = 'none';
  try {
    if (doc.caretRangeFromPoint) rg = doc.caretRangeFromPoint(x, y);
    else if (doc.caretPositionFromPoint) {
      const p = doc.caretPositionFromPoint(x, y);
      if (p) { rg = doc.createRange(); rg.setStart(p.offsetNode, p.offset); }
    }
  } catch (_) {}
  if (cv) cv.style.pointerEvents = pe;
  if (!rg || !rg.startContainer || rg.startContainer.nodeType !== 3) return null;
  if (!root.contains(rg.startContainer)) return null;
  const ctx = annCtx(root);
  let pos = annPosOf(ctx.nodes, rg.startContainer, rg.startOffset);
  if (pos < 0) return null;
  // caretRangeFromPoint 在空白处会给「最近的」文本，可能离得很远 —— 验一下真压着字。
  // 在段落右边空白划一道时 caret 会吸到行尾，pos 正好落在块分隔符上 —— 那个位置不属于任何文本
  // 节点（annRangeOf 两头都不沾），得退一格拿这一块最后那个字来验。
  let probe = annRangeOf(ctx.nodes, pos, 1);
  if (!probe && pos > 0) probe = annRangeOf(ctx.nodes, pos - 1, 1);
  if (!probe) return null;
  const b = probe.getBoundingClientRect();
  if (y < b.top - 40 || y > b.bottom + 40) return null;        // 竖直差一行以上＝没压住文本
  const full = ctx.full;
  const enough = (s) => s.replace(/\s/g, '').length >= 4;      // 太短的锚不稳
  let quote = full.slice(pos, pos + ANN_QLEN);
  const nl = quote.indexOf('\n');
  if (nl >= 0) quote = quote.slice(0, nl);                     // 锚句别跨块（块之间是 '\n'）
  // 落在这一块的末尾（比如在段落右边的空白上划一道，caret 吸到行尾）→ 往后没字了，
  // 往前取这一块的尾巴当锚，别让这一笔白白掉回 pixel。
  if (!enough(quote)) {
    const bs = full.lastIndexOf('\n', pos - 1) + 1;            // 这一块从哪开始
    const from = Math.max(bs, pos - ANN_QLEN);
    const back = full.slice(from, pos);
    if (enough(back)) { quote = back; pos = from; }
  }
  if (!enough(quote)) return null;                             // 这一块本来就没几个字 → 退回 pixel
  // rect 一并带出去：位置这儿已经算出来了，调用方不必再 annLocate 从头搜一遍。
  // 注意要取**锚句起点**的矩形：pos 可能刚往前挪过，而 annLocate 以后重定位时给的正是起点的矩形，
  // 这儿给错的话，第一次 relayout 笔迹就会跳一下。
  const rr = annRangeOf(ctx.nodes, pos, 1);
  return {
    a: {
      quote,
      prefix: full.slice(Math.max(0, pos - ANN_CTX), pos),
      suffix: full.slice(pos + quote.length, pos + quote.length + ANN_CTX),
      start: pos,
    },
    rect: rr ? rr.getBoundingClientRect() : b,
  };
}
// 锚 → 这句话现在的屏幕矩形。找不到＝内容改了（孤儿标注），返回 null。
// ctx 传了就复用它（定位多笔时别每笔都重新遍历整篇正文）
function annLocate(root, a, ctx) {
  if (!root || !a || !a.quote) return null;
  ctx = ctx || annCtx(root);
  const full = ctx.full, q = a.quote;
  let pos = -1;
  if (a.start >= 0 && full.substr(a.start, q.length) === q) pos = a.start;   // 老位置还对得上（最常见）
  if (pos < 0) {                                                             // 带前后文找，消歧
    const i = full.indexOf((a.prefix || '') + q + (a.suffix || ''));
    if (i >= 0) pos = i + (a.prefix || '').length;
  }
  if (pos < 0) {                                                             // 只按这句话找，多处取离老位置最近的
    const hits = []; let i = full.indexOf(q);
    while (i >= 0 && hits.length < 50) { hits.push(i); i = full.indexOf(q, i + 1); }
    if (hits.length) pos = hits.reduce((b, c) => (Math.abs(c - a.start) < Math.abs(b - a.start) ? c : b));
  }
  if (pos < 0) return null;
  const rg = annRangeOf(ctx.nodes, pos, 1);
  if (!rg) return null;
  const b = rg.getBoundingClientRect();
  return (b.width || b.height) ? b : null;
}

/* ================= 通用手写批注层（Ink）=================
   一块透明画布盖在**任意内容**上，随处拿笔勾画/做笔记。解决三件事：
     · 笔尖对齐：坐标是「指针相对画布」直接算的，笔尖落哪画哪（pdf.js 自带的笔尖是歪的）。
     · 橡皮 + 全屏清除：橡皮划过即擦（destination-out）；清屏一键抹掉整页笔迹。
     · 笔迹保留：按「页面/文档」存到本地，关了再打开还在（PDF 按资料 id、其它按视图名）。
   PDF 是同源 iframe：读它内部 #viewerContainer 的滚动，笔迹跟着页面一起滚、贴在原位。
   笔引擎（压感、合并采样顺滑、笔/荧光笔）和草稿纸同源。 */
const Ink = {
  on: false, tool: 'pen', color: '#e23b2e', size: 3, eraserSize: 18,   // 笔和橡皮各调各的粗细
  strokes: [], cur: null, key: '', drawing: false, sawPen: false, raf: 0,
  scroller: null, _onScroll: null, cv: null, ctx: null, frame: null, root: null,
  COLORS: ['#e23b2e', '#1a6fb5', '#f0a500', '#1e8449', '#111'],
  curSize() { return this.tool === 'eraser' ? this.eraserSize : this.size; },

  rect() { return this.cv.getBoundingClientRect(); },
  scrollY() {
    try { return this.scroller ? (this.scroller.scrollTop || 0) : 0; } catch (_) { return 0; }
  },
  /* ---------- PDF 锚：把一笔钉到「第几页的页内某处」---------- */
  pdfDoc() { try { return this.frame && this.frame.contentDocument; } catch (_) { return null; } },
  /* 一帧的几何快照：画布矩形、iframe 矩形、滚动量、各页矩形。一帧内共用（别每笔都量），
     但**每帧必须重新取**：拿上一帧的页矩形去算这一帧的落笔点，滚动中就会把偏掉的坐标永久存进去。
     页矩形是懒查的，用到哪页查哪页。 */
  newFrame() {
    let fr = null;
    try { fr = this.frame ? this.frame.getBoundingClientRect() : null; } catch (_) {}
    this._geo = { cr: this.rect(), fr, sy: this.scrollY(), pages: {} };
    return this._geo;
  },
  // 第 n 页此刻在画布坐标系里的矩形。缩放/滚动都体现在它身上 —— 所以笔迹自动跟着缩放和滚动。
  pageRect(n) {
    const g = this._geo;
    if (!g || !g.fr) return null;
    if (g.pages[n] !== undefined) return g.pages[n];
    let r = null;
    const doc = this.pdfDoc();
    if (doc) {
      const el = doc.querySelector('.page[data-page-number="' + n + '"]');
      if (el) {
        const b = el.getBoundingClientRect();          // iframe 视口坐标
        if (b.width && b.height) {
          r = { left: b.left + g.fr.left - g.cr.left, top: b.top + g.fr.top - g.cr.top,
                width: b.width, height: b.height };
        }
      }
    }
    g.pages[n] = r;
    return r;
  },
  // pdf.js 把页渲染出来了没。PDF 要加载一分多钟，加载期间「一页都找不到」是正常的，
  // 不能当成「批注找不到页」去报警。
  pdfReady() {
    if (!this.frame) return true;
    try {
      const doc = this.pdfDoc();
      return !!(doc && doc.querySelector('.page[data-page-number]'));
    } catch (_) { return false; }
  },
  // 屏幕点 → PDF 锚 {page, pw, quote?}。pw＝落笔时的页宽，用来算笔粗该跟着缩放放大多少倍。
  pdfAnchorAt(clientX, clientY) {
    const doc = this.pdfDoc(), g = this._geo;
    if (!doc || !g || !g.fr) return null;
    try {
      const ix = clientX - g.fr.left, iy = clientY - g.fr.top;    // 换算成 iframe 自己的视口坐标
      const el = doc.elementFromPoint(ix, iy);
      const page = el && el.closest && el.closest('.page[data-page-number]');
      if (!page) return null;
      const b = page.getBoundingClientRect();
      if (!b.width || !b.height) return null;
      const a = { page: +page.dataset.pageNumber, pw: Math.round(b.width) };
      // 顺带记下这一笔压着的是哪句话（pdf.js 的 textLayer 里有文本）。**定位仍然只靠 page + 页内
      // 归一化坐标**，quote 纯属附加信息 —— 但没有它，PDF 批注就只是一坨没内容的像素：搜不到、
      // 也进不了复习。而用户画得最多的恰恰是 PDF。
      const hit = annAnchorAt(page, ix, iy, doc);
      if (hit) { a.quote = hit.a.quote; a.prefix = hit.a.prefix; a.suffix = hit.a.suffix; }
      return a;
    } catch (_) { return null; }
  },
  /* ---------- 三种锚共用一个仿射变换 ----------
     存储点 → 画布点：X = x*kx + ox，Y = y*ky + oy；笔粗 ×= ks。pt() 就是它的逆。
       pixel：x 按画布宽归一化、y 是内容绝对像素        → kx=W, ox=0,        ky=1, oy=-sy
       text ：同上，但 y 相对「那句话」                  → kx=W, ox=0,        ky=1, oy=ref-sy
       pdf  ：x/y 都归一化到页内，跟着缩放走             → kx/ox/ky/oy = 页矩形，ks=页宽/落笔时页宽
     返回 null＝这一笔现在画不出来（文本锚孤儿、或那一页找不到）。用 newFrame() 的几何快照。 */
  tfOf(s) {
    const g = this._geo || this.newFrame();
    const a = s.a;
    if (a && a.page != null) {
      const pr = this.pageRect(a.page);
      if (!pr) return null;
      return { kx: pr.width, ox: pr.left, ky: pr.height, oy: pr.top, ks: pr.width / (a.pw || pr.width) };
    }
    if (s._ref === null) return null;
    return { kx: g.cr.width, ox: 0, ky: 1, oy: (s._ref || 0) - g.sy, ks: 1 };
  },
  // 屏幕点 → 存储坐标（tfOf 的逆变换）
  pt(e, tf) {
    const r = (this._geo || this.newFrame()).cr;
    return {
      x: ((e.clientX - r.left) - tf.ox) / (tf.kx || 1),
      y: ((e.clientY - r.top) - tf.oy) / (tf.ky || 1),
      p: (e.pointerType === 'pen' && e.pressure > 0) ? e.pressure : 0,
    };
  },
  fit() {
    const r = this.rect();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    this.cv.width = Math.round(r.width * dpr);
    this.cv.height = Math.round(r.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.relayout();                     // 宽度变了＝内容重排了，锚要重新定位
    this.paint();
  },
  drawStroke(ctx, s, tf) {
    const pts = s.pts; if (!pts || !pts.length || !tf) return;   // tf=null：孤儿 / 那一页还没渲染
    ctx.save(); ctx.lineJoin = ctx.lineCap = 'round';
    let wid = s.size * (tf.ks || 1);               // s.size 已是该工具自己的粗细（橡皮/笔各存各的）
    if (s.tool === 'eraser') { ctx.globalCompositeOperation = 'destination-out'; ctx.strokeStyle = '#000'; }
    else { ctx.strokeStyle = s.color; if (s.tool === 'hl') { ctx.globalAlpha = .3; wid *= 3.2; } }
    const X = p => p.x * tf.kx + tf.ox, Y = p => p.y * tf.ky + tf.oy;   // 存储坐标 → 画布坐标
    if (pts.length === 1) {
      ctx.beginPath(); ctx.arc(X(pts[0]), Y(pts[0]), Math.max(.6, wid / 2), 0, 6.2832);
      ctx.fillStyle = ctx.strokeStyle; ctx.fill(); ctx.restore(); return;
    }
    const varW = s.tool === 'pen' && pts.some(p => p.p > 0);
    if (!varW) {
      ctx.lineWidth = wid; ctx.beginPath(); ctx.moveTo(X(pts[0]), Y(pts[0]));
      for (let i = 1; i < pts.length; i++) ctx.lineTo(X(pts[i]), Y(pts[i]));
      ctx.stroke();
    } else {
      for (let i = 1; i < pts.length; i++) {
        const a = pts[i - 1], b = pts[i];
        ctx.lineWidth = wid * (.35 + 1.1 * (((a.p || .5) + (b.p || .5)) / 2));
        ctx.beginPath(); ctx.moveTo(X(a), Y(a)); ctx.lineTo(X(b), Y(b)); ctx.stroke();
      }
    }
    ctx.restore();
  },
  paint() {
    if (!this.ctx) return;
    const g = this.newFrame();
    this.ctx.clearRect(0, 0, g.cr.width, g.cr.height);
    // 画不出来的笔在这里一起数：文本锚找不到那句话、PDF 锚找不到那一页。数据都还在，只是不画 ——
    // 但必须出声。静默消失就是当初那个空 catch 的病，换成 return null 也还是同一种病。
    let missText = 0, missPage = 0;
    const ready = this.pdfReady();
    for (const s of this.strokes) {
      const tf = this.tfOf(s);
      if (!tf) { if (s.a && s.a.page != null) { if (ready) missPage++; } else missText++; }
      this.drawStroke(this.ctx, s, tf);
    }
    if (this.cur) this.drawStroke(this.ctx, this.cur, this.tfOf(this.cur));
    this.tellMissing(missText, missPage);
  },
  // 同一批「显示不出来」只说一次，别每帧刷屏。工具栏上留个角标，点开能处理（光弹个 toast
  // 等于只告诉你「丢了」却不给辙 —— 那和不吭声只差半步）。
  tellMissing(t, p) {
    const n = t + p, k = t + ':' + p;
    const btn = $('#ink-orph');
    if (btn) {
      btn.classList.toggle('hidden', !n);
      if (n) btn.textContent = '⚠ ' + n + ' 条贴不上';
    }
    if (n && k !== this._toldMissing) {
      const why = [];
      if (t) why.push(t + ' 条找不到原文（原文改过）');
      if (p) why.push(p + ' 条找不到对应的页（换过文件？）');
      toast('有批注暂时显示不出来：' + why.join('；') + '，点工具栏 ⚠ 处理', true);
    }
    this._toldMissing = k;
  },
  // 现在贴不上的那些笔（连同它们在 strokes 里的下标，删除/重挂要用）
  missing() {
    const out = [];
    this.newFrame();
    this.strokes.forEach((s, i) => { if (!this.tfOf(s)) out.push({ i, s }); });
    return out;
  },
  /* 重新挂锚：让用户在页面上点一个新位置，把这一笔挪过去。
     笔迹本身（那些点）是相对锚存的，所以换锚＝换参照物，形状不变、整体挪到新位置。 */
  pickAnchor(idx) {
    const s = this.strokes[idx];
    if (!s) return;
    this._reanchor = idx;
    const q = (s.a && s.a.quote) ? s.a.quote : '这一笔';
    const t = $('#ink-pick-t'), bar = $('#ink-pick');
    if (t) t.textContent = '点一下「' + q.slice(0, 14) + '」现在该贴在哪';
    if (bar) bar.classList.remove('hidden');
    if (this.tool === 'scroll') { this.tool = 'pen'; this.syncUI(); }   // 浏览模式点不到画布
  },
  cancelPick() {
    this._reanchor = null;
    const bar = $('#ink-pick'); if (bar) bar.classList.add('hidden');
  },
  // 用户在新位置点了一下 → 换锚。返回 true 表示这一下已经被「重挂」吃掉，不该再画
  takePick(e) {
    if (this._reanchor == null) return false;
    const idx = this._reanchor, s = this.strokes[idx];
    this.cancelPick();
    if (!s) return true;
    const g = this.newFrame();
    let a = this.pdfAnchorAt(e.clientX, e.clientY), ref = 0;
    if (a) { s.a = a; s._ref = 0; }
    else {
      const hit = annAnchorAt(this.root, e.clientX, e.clientY);
      if (!hit) { toast('这儿没有文字，挂不上 —— 换个有字的地方点', true); return true; }
      s.a = hit.a;
      ref = hit.rect.top - g.cr.top + g.sy;
      s._ref = ref;
    }
    this.relayout(); this.paint(); this.save();
    toast('挂好了');
    return true;
  },
  dropStroke(idx) {
    if (!this.strokes[idx]) return;
    this.strokes.splice(idx, 1);
    this._cleared = null;
    this.relayout(); this.paint(); this.save();
  },
  down(e) {
    if (this.tool === 'scroll') return;                     // ✋ 浏览模式：不画，交给下面滚动
    if (e.pointerType === 'pen') this.sawPen = true;
    if (e.pointerType === 'touch' && this.sawPen) return;   // 用过笔就忽略手指 = 防手掌误触
    if (e.button > 0) return;
    e.preventDefault();
    if (this.takePick(e)) return;                           // 正在给某一笔挑新位置：这一下是「挂哪」，不是画
    try { this.cv.setPointerCapture(e.pointerId); } catch (_) {}
    this.drawing = true;
    // 落笔时就定好这一笔钉在哪：PDF 钉到「第几页的页内某处」；文本钉到「那句话」；
    // 都钉不住（大片空白/图片上）→ a=null 退回 pixel 锚（＝老行为，画在哪个屏幕位置就留在哪）
    const g = this.newFrame();
    let a = this.pdfAnchorAt(e.clientX, e.clientY), ref = 0;
    if (!a) {
      const hit = annAnchorAt(this.root, e.clientX, e.clientY);
      if (hit) { a = hit.a; ref = hit.rect.top - g.cr.top + g.sy; }
    }
    this.cur = { tool: this.tool, color: this.color, size: this.curSize(), a, _ref: ref };
    const tf = this.tfOf(this.cur);
    if (!tf) {                          // 这一笔现在没法定位（页找不到）：捕获也得还回去，
      this.drawing = false; this.cur = null;      // 不然这一下拖动既不画、下面的 PDF 也收不到事件＝不滚
      try { this.cv.releasePointerCapture(e.pointerId); } catch (_) {}
      return;
    }
    this.cur.pts = [this.pt(e, tf)];
    this.paint();
  },
  move(e) {
    if (!this.drawing || !this.cur) return;
    e.preventDefault();
    let evs = [];
    try { if (e.getCoalescedEvents) evs = e.getCoalescedEvents(); } catch (_) {}
    if (!evs.length) evs = [e];
    // 每次 move 重取一帧几何：页矩形和滚动量都可能已经变了（惯性滚动/自动滚页），
    // 拿旧的算会把偏掉的坐标永久存进去。同一批合并采样点共用这一份就够了。
    this.newFrame();
    const tf = this.tfOf(this.cur);
    if (!tf) return;
    for (const ev of evs) this.cur.pts.push(this.pt(ev, tf));
    if (!this.raf) this.raf = requestAnimationFrame(() => { this.raf = 0; this.paint(); });
  },
  up() {
    if (!this.drawing) return;
    this.drawing = false;
    if (this.cur && this.cur.pts.length) { this.strokes.push(this.cur); this._cleared = null; }
    this.cur = null; this.paint(); this.save();
  },
  undo() {
    if (!this.strokes.length && this._cleared) { this.strokes = this._cleared; this._cleared = null; }  // 撤销「清屏」→ 全部找回
    else if (this.strokes.length) this.strokes.pop();
    else return;
    this.paint(); this.save();
  },
  clear() {
    // 画布空着、也没有数据在路上 → 没什么可清。但 load 还没回来时画布**看着**是空的，
    // 这时点清屏也是明确指令（「这页的批注我不要了」），得记下来，否则数据一回来又冒出来。
    if (!this.strokes.length && !this._loading) return;
    if (this.strokes.length) this._cleared = this.strokes.slice();
    this.strokes = [];
    this._wiped = true;
    this.paint(); this.save();
  },
  // 存盘格式（和草稿纸 padData 一个路子）：点存成 [x,y] / [x,y,压感] 的数组、坐标取整、
  // 连续重复的点直接扔（笔停在原地时合并采样仍在不停入队）。全精度对象存法一份 PDF 批注能到
  // 6MB，5MiB 配额一满 setItem 就永远抛 QuotaExceededError —— 新批注再也存不进去。
  pack(strokes) {
    const r4 = (n) => Math.round(n * 1e4) / 1e4, r1 = (n) => Math.round(n * 10) / 10;
    return strokes.map(s => {
      // y 的精度得看这一笔用的哪种锚：pixel/text 的 y 是像素，留 0.1 足够；
      // **PDF 锚的 y 是 0..1 归一化**，留 0.1 的话 0.18 会被round成 0.2 —— 乘回页高就是偏 42px。
      const ry = (s.a && s.a.page != null) ? r4 : r1;
      const pts = []; let lx = null, ly = null;
      for (const q of (s.pts || [])) {
        const x = r4(q.x), y = ry(q.y);
        if (x === lx && y === ly) continue;
        const p = Math.round((q.p || 0) * 100) / 100;
        pts.push(p ? [x, y, p] : [x, y]);
        lx = x; ly = y;
      }
      const o = { t: s.tool, c: s.color, w: s.size, p: pts };
      if (s.a) o.a = s.a;                          // 文本锚：这一笔贴在「哪句话」上
      return o;
    }).filter(s => s.p.length);
  },
  // 读得懂两种格式：新的 {t,c,w,p:[[x,y]]}，和旧的 {tool,color,size,pts:[{x,y,p}]}（迁移漏网的）
  unpack(data) {
    return (data || []).map(s => (s.pts ? s : {
      tool: s.t, color: s.c, size: s.w, a: s.a || null,
      pts: (s.p || []).map(q => ({ x: q[0], y: q[1], p: q[2] || 0 })),
    })).filter(s => s.pts && s.pts.length);
  },
  // 每笔的参考原点（内容坐标系的 y）：文本锚＝那句话现在在哪；pixel 锚＝0（＝老的视口坐标行为）。
  // 存的是「内容坐标」而不是「屏幕坐标」，所以滚动只要减 scrollTop，不必重新定位（annLocate 不便宜）。
  relayout() {
    const g = this.newFrame();
    this.orphans = 0;
    const all = this.cur ? this.strokes.concat([this.cur]) : this.strokes;
    // 整篇正文只遍历一次给所有笔共用：以前每笔各算一遍，100 笔就是 200 遍全文，拖窗口直接卡死
    const isText = (s) => s.a && s.a.page == null;
    const ctx = (this.root && all.some(isText)) ? annCtx(this.root) : null;
    for (const s of all) {
      // pixel 锚不用定位；PDF 锚每帧靠页矩形算（见 tfOf），也不走这里
      if (!isText(s)) { s._ref = 0; continue; }
      const b = annLocate(this.root, s.a, ctx);
      if (b) s._ref = b.top - g.cr.top + g.sy;
      else { s._ref = null; this.orphans++; }     // 内容改了，这句话没了＝孤儿，不画（数据留着）
    }
    // 「显示不出来」的提示统一在 paint() 里报（那儿连 PDF 找不到页的也一起数）
  },
  /* 存服务器（批注是长期资产，不该躺在一个浏览器的 5MiB 配额里；换设备/重装也不丢）。
     localStorage 降级成**离线暂存**：传上去就删掉本地那份 —— 正常情况下它几乎不占空间，
     配额问题从根上没了；离线时笔迹先压在本地，下次进这一页再补传。 */
  save() {
    if (!this.key) return;
    this._memKey = this.key;              // 内存里这份笔迹是哪一页的 —— load() 靠它兜底
    this._stash();                        // 先落本地：关窗口/断网都不丢
    clearTimeout(this._saveT);            // 防抖：别每抬一次笔就打一次接口
    // key 必须**现在**捕获：写成 () => this.flush(this.key) 的话，700ms 后 this.key 可能已经翻到
    // 别的页了 —— 那次 flush 就发到别的 target 上，这一页的笔迹反倒从没传上去。
    const k = this.key;
    this._saveT = setTimeout(() => this.flush(k), 700);
  },
  _stash() {
    try {
      if (this.strokes.length) localStorage.setItem('ink:' + this.key, JSON.stringify(this.pack(this.strokes)));
      else lsDel('ink:' + this.key);
      this._warned = false;
    } catch (_) {
      // 存不下就得说话：以前这里是空 catch，笔迹默默丢了，用户完全看不出发生过什么
      if (!this._warned) { this._warned = true; toast('本地存储满了，这一页批注没存上', true); }
    }
  },
  async flush(key) {
    if (!key) return;
    // load 还没回来时手里只有半份（甚至空的）strokes，这时候整页 replace 会把服务器上这一页的
    // 旧批注删光。等它回来再传 —— 重试用自己的定时器，别占 _saveT：那是「当前页防抖」的位子，
    // 一开新页画一笔就会 clearTimeout 把这次补传取消掉。replace 是幂等的，重试多跑一次也无妨。
    if (this._loading === key) { setTimeout(() => this.flush(key), 400); return; }
    const items = this.pack(this.key === key ? this.strokes : this.unpack(this._stashed(key)))
      .map(s => ({ kind: s.t === 'hl' ? 'hl' : 'ink',
                   anchor_type: !s.a ? 'pixel' : (s.a.page != null ? 'pdf' : 'text'),
                   anchor: s.a || {}, data: { t: s.t, c: s.c, w: s.w, p: s.p } }));
    try {
      await api('/api/annots/replace', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: key, items }),
      });
      try { lsDel('ink:' + key); } catch (_) {}   // 传上去了，本地那份就不留了
    } catch (_) {}                        // 离线/失败：本地暂存还在，下次进这一页再补
  },
  _stashed(key) {
    try { return JSON.parse(lsGet('ink:' + key) || 'null') || []; } catch (_) { return []; }
  },
  async load() {
    const key = this.key;
    if (this._memKey !== key) { this._cleared = null; this.strokes = []; }  // 换了一页：清屏的后悔药也别跨页
    this._memKey = key;
    this._wiped = false;                                  // 等接口这会儿用户点没点「清屏」
    const n0 = this.strokes.length;                       // 内存里原有的（同一页重开时非 0）
    const stash = this._stashed(key);                     // 离线时压在本地、还没传上去的
    let server = null;
    this._loading = key;                                  // 这期间别让 flush 拿半份数据去覆盖服务器
    try {
      const d = await api('/api/annots?target=' + encodeURIComponent(key));
      server = (d.items || []).map(it => Object.assign({}, it.data,
        { a: (it.anchor_type === 'text' || it.anchor_type === 'pdf') ? it.anchor : null }));
    } catch (_) {}                                        // 断网：下面退回本地那份
    if (this._loading === key) this._loading = null;
    if (this.key !== key) return;                         // 等接口的工夫用户已经翻页了，别把笔迹画串页
    // 等接口这会儿用户可能已经落笔了 —— 那几笔必须留住，接在取回来的后面，别被覆盖掉
    const mine = this.strokes.slice(this._wiped ? 0 : n0);
    let base;
    if (this._wiped) base = [];       // 用户在等接口的工夫点了「清屏」：那是明确指令，别把旧的又搬回来
    else if (stash.length) { base = this.unpack(stash); this.flush(key); }   // 本地暂存＝还没传上去的，最新
    else if (server && server.length) base = this.unpack(server);
    else if (n0) { base = this.strokes.slice(0, n0); this.flush(key); }
    // ↑ 内存里有、服务器和本地都没有 ＝ 还没传上去（防抖没到点、或本地配额满存不下），
    //   这份是唯一的一份，保住并补传。注意 server=[] 是 truthy，别把「还没传」当成「服务器说这页是空的」。
    else base = [];
    this.strokes = base.concat(mine);
    if (this.on) { this.relayout(); this.paint(); }
  },
  syncUI() {
    document.querySelectorAll('#ink .ink-t[data-inkt]').forEach(b => b.classList.toggle('on', b.dataset.inkt === this.tool));
    $('#ink-colors').innerHTML = this.COLORS.map(c =>
      `<i class="ink-c${c === this.color && this.tool !== 'eraser' ? ' on' : ''}" data-ic="${c}" style="background:${c}"></i>`).join('');
    // 滑杆调的是「当前工具」的粗细：橡皮范围大一些（能一擦一大片），笔细一些
    const sl = $('#ink-size');
    if (this.tool === 'eraser') { sl.min = 6; sl.max = 60; } else { sl.min = 1; sl.max = 14; }
    sl.value = this.curSize();
    // ✋ 浏览模式：画布让开，事件透传到下面 → 能滚动 PDF/页面（工具栏还在，随时切回笔）
    if (this.cv) this.cv.style.pointerEvents = this.tool === 'scroll' ? 'none' : 'auto';
  },
  // scroller: 要跟随滚动的元素（PDF 是 iframe 内部的 #viewerContainer；其它视图是主滚动容器/null）
  // target:   画布要盖住的元素（PDF 是 iframe；不传就盖住顶栏以下的整个内容区）→ 笔尖对齐靠这个
  open(key, scroller, target, root) {
    this.unhook();                       // 已经开着又点一次入口（工具球/查看器条各有一个）：先摘干净
    this.key = key || (('view:' + ((stack[stack.length - 1] || {}).view || 'home')));
    this.scroller = scroller || null;
    this.root = root || null;            // 文本锚挂在这个容器的文字上；不传＝只能 pixel 锚
    // 盖的是 PDF 的 iframe → 这一层能用 PDF 锚（钉到页内，跟着缩放/翻页走）
    this.frame = (target && target.tagName === 'IFRAME') ? target : null;
    this._geo = null; this._toldMissing = null;    // 换了一页：几何快照和「说过的提示」都重来
    this.cv = $('#ink-cv'); this.ctx = this.cv.getContext('2d');
    $('#ink').classList.remove('hidden');
    // 把画布精确定位到目标区域（不传目标就是顶栏以下整个屏幕）—— 画布(0,0) 要正好对齐内容(0,0)
    const r = target ? target.getBoundingClientRect() : null;
    const top = r ? r.top : (($('.topbar') || {}).getBoundingClientRect ? $('.topbar').getBoundingClientRect().bottom : 0);
    this.cv.style.left = (r ? r.left : 0) + 'px';
    this.cv.style.top = top + 'px';
    this.cv.style.width = (r ? r.width : window.innerWidth) + 'px';
    this.cv.style.height = (r ? r.height : (window.innerHeight - top)) + 'px';
    this.on = true; this.sawPen = false;
    this.load();
    this.fit();
    this.syncUI();
    if (!this._bound) { this.bind(); this._bound = true; }
    // 跟随滚动重绘。整页滚动（html/body）的 scroll 事件在 window 上触发，不在元素上 → 监听 window
    this._onScroll = () => this.paint();
    this._scrollHost = (this.scroller === document.scrollingElement
      || this.scroller === document.documentElement || this.scroller === document.body)
      ? window : this.scroller;
    if (this._scrollHost) {
      try { this._scrollHost.addEventListener('scroll', this._onScroll, { passive: true }); } catch (_) {}
    }
    // PDF 缩放（pdf.js 的 +/−）不发 scroll，页矩形却变了 —— 盯住它内部的 #viewer，尺寸一变就重画。
    // 「整份 PDF 十几 MB…打开要一分多钟」（见 probeSlides 那段注释），所以点开资料立刻点批注是常事，
    // 那会儿 iframe 还是 about:blank、#viewer 根本不存在 —— 挂不上就等 frame 加载完再挂，
    // 否则这一次批注期间缩放永远不重画。（frame.onload 已被 hidePdfjsPen 占用，只能 addEventListener。）
    if (this.frame && window.ResizeObserver && !this.hookZoom()) {
      this._onFrameLoad = () => this.hookZoom();
      try { this.frame.addEventListener('load', this._onFrameLoad); } catch (_) {}
    }
    window.addEventListener('resize', this._onResize = () => this.fit());
  },
  close() {
    this.on = false;
    // 笔还没抬就被关掉（切视图会走 render() → Ink.close()）：这一笔也得算数，别默默丢
    if (this.cur && this.cur.pts && this.cur.pts.length) { this.strokes.push(this.cur); this._cleared = null; this.save(); }
    // 关之前把还压着的那次防抖传完：定时器留到关掉之后才到点，那时 key 可能已经指向别的页了
    if (this._saveT) { clearTimeout(this._saveT); this._saveT = 0; this.flush(this.key); }
    this.cancelPick();                                   // 别把「正在挑位置」的状态留给下次
    const osh = $('#ink-orph-sheet'); if (osh) osh.classList.add('hidden');
    $('#ink').classList.add('hidden');
    if (this.cv) this.cv.style.pointerEvents = 'auto';   // 别把「浏览模式」的透传状态留给下次
    this.unhook();
    this.scroller = null; this.frame = null; this.cur = null; this.drawing = false;
  },
  // 盯住 pdf.js 的 #viewer：缩放会改它的尺寸。挂上了返回 true；PDF 还没加载出来就返回 false，
  // 由 open() 挂个 frame load 监听等它回来再挂一次。
  hookZoom() {
    if (this._ro) return true;
    try {
      const doc = this.pdfDoc();
      const v = doc && doc.getElementById('viewer');
      if (!v) return false;
      this._ro = new ResizeObserver(() => this.paint());
      this._ro.observe(v);
      this.paint();                      // 页这会儿可能刚渲染出来，补画一次
      return true;
    } catch (_) { return false; }
  },
  // 摘监听：open() 里重新挂之前也要先摘，否则反复开关会越挂越多
  unhook() {
    if (this._scrollHost && this._onScroll) { try { this._scrollHost.removeEventListener('scroll', this._onScroll); } catch (_) {} }
    if (this._onResize) window.removeEventListener('resize', this._onResize);
    if (this._ro) { try { this._ro.disconnect(); } catch (_) {} this._ro = null; }
    if (this._onFrameLoad && this.frame) { try { this.frame.removeEventListener('load', this._onFrameLoad); } catch (_) {} }
    this._scrollHost = null; this._onScroll = null; this._onResize = null; this._onFrameLoad = null;
  },
  bind() {
    const cv = this.cv;
    cv.addEventListener('pointerdown', e => this.down(e));
    cv.addEventListener('pointermove', e => this.move(e));
    cv.addEventListener('pointerup', () => this.up());
    cv.addEventListener('pointercancel', () => this.up());
    cv.style.touchAction = 'none';
    $('#ink').addEventListener('click', e => {
      const t = e.target.closest('[data-inkt]');
      if (t) { this.tool = t.dataset.inkt; this.syncUI(); return; }
      const c = e.target.closest('[data-ic]');
      if (c) { this.color = c.dataset.ic; if (this.tool === 'eraser') this.tool = 'pen'; this.syncUI(); return; }
    });
    $('#ink-size').addEventListener('input', e => { if (this.tool === 'eraser') this.eraserSize = +e.target.value; else this.size = +e.target.value; });
    $('#ink-undo').onclick = () => this.undo();
    $('#ink-clear').onclick = () => this.clear();
    $('#ink-done').onclick = () => this.close();
    const ob = $('#ink-orph'); if (ob) ob.onclick = () => inkOrphOpen();
    const px = $('#ink-pick-x'); if (px) px.onclick = () => this.cancelPick();
  },
};
// 从工具球「✏️ 批注」进：给当前视图盖一层。PDF 查看器另有专门入口（跟随内部滚动）。
function inkHere() {
  const st = stack[stack.length - 1] || {};
  // PDF/Office 预览：**PDF 锚** —— 笔迹钉到「第几页的页内某处」，页内坐标归一化，
  // 所以缩放（pdf.js 的 +/-）、滚动、换设备、换窗口宽度都跟着那一页走，笔粗也按页宽同比缩放。
  // （老的存法是「iframe 内部滚动的绝对像素」，一缩放就全错位。）
  const vf = $('#viewer-frame');
  if (st.view === 'viewer' && vf && !vf.classList.contains('hidden')) {
    let sc = null;
    try { sc = vf.contentDocument && vf.contentDocument.getElementById('viewerContainer'); } catch (_) {}
    // 按文件 URL 里的 file= 参数存，同一份资料每次打开都取回上次的笔迹
    let fk = vf.src;
    try { fk = decodeURIComponent(new URL(vf.src, location.href).searchParams.get('file') || vf.src); } catch (_) {}
    Ink.open('mat:' + fk.slice(-80), sc, vf, null);
    return;
  }
  // 阅读模式（.md/.txt/PDF 转出来的文本）：**文本锚**。笔迹钉在「那句话」上 —— 改字号、换字体、
  // 换设备宽度、内容重排，笔迹都跟着那句话走（坐标锚定下点一次 A+ 就错位 2.3 行）。
  // root=#viewer-reader 是文字所在的容器，它自己带滚动（.reader{overflow-y:auto}），
  // 锚存的是内容坐标，滚动只是减 scrollTop，笔迹自然跟着内容滚。
  const rd = $('#viewer-reader');
  if (st.view === 'viewer' && rd && !rd.classList.contains('hidden')) {
    Ink.open('view:viewer' + (st.id ? ':' + st.id : ''), rd, null, rd);
    return;
  }
  // 其它视图：暂时仍是 pixel 锚（按视口坐标，画在哪个屏幕位置就留在哪）。
  // 文本锚推广到这些视图是第二期的事 —— 它们的正文容器（mkPageRoot）和滚动容器五花八门，
  // 得一个个核对，先让阅读模式这条路跑稳。
  Ink.open('view:' + (st.view || 'home') + (st.id ? ':' + st.id : ''), null, null, null);
}

/* 「贴不上」的批注面板：笔迹还在，只是原文改过 / 换了文件，不知道该贴哪了。
   给三条路：重新指个位置、删掉、或者先留着（关掉就是留着，数据一直在）。 */
function inkOrphOpen() {
  const sh = $('#ink-orph-sheet');
  if (!sh) return;
  const miss = Ink.missing();
  if (!miss.length) { toast('现在没有贴不上的批注'); return; }
  $('#orph-tip').textContent = '这些笔迹还在，但原文改过之后找不到落点了，所以暂时没画出来。'
    + '可以重新指个位置，或者删掉；就这么关掉也行，数据不会丢。';
  $('#orph-list').innerHTML = miss.map(({ i, s }) => {
    const a = s.a || {};
    const what = a.page != null
      ? ('第 ' + a.page + ' 页' + (a.quote ? '：' + esc(a.quote) : '') )
      : (a.quote ? esc(a.quote) : '（没记下原文）');
    return `<div class="orph-item">
      <div class="orph-q">${a.quote || a.page != null ? '原来贴在 <b>' + what + '</b>' : what}</div>
      <div class="orph-acts">
        <button class="pri" data-orph-pick="${i}">重新指个位置</button>
        <button class="del" data-orph-del="${i}">删掉</button>
      </div></div>`;
  }).join('');
  sh.classList.remove('hidden');
}
const inkOrphClose = () => { const sh = $('#ink-orph-sheet'); if (sh) sh.classList.add('hidden'); };
// 这段是顶层代码：元素要是不在（比如 SW 给了旧的 index.html 配新的 app.js），
// 直接 $(...).onclick 会抛，**整个 app.js 就加载不下去了** —— 崩的可不止批注。
if ($('#ink-orph-sheet')) {
  $('#orph-close').onclick = inkOrphClose;
  $('#ink-orph-sheet').addEventListener('click', async (e) => {
    if (e.target === e.currentTarget) { inkOrphClose(); return; }
    const p = e.target.closest('[data-orph-pick]');
    if (p) { inkOrphClose(); Ink.pickAnchor(+p.dataset.orphPick); return; }
    const d = e.target.closest('[data-orph-del]');
    if (d) {
      if (!await appConfirm('删掉这一笔批注？删了就找不回来了。', { title: '批注', okText: '删掉', danger: true })) return;
      Ink.dropStroke(+d.dataset.orphDel);
      toast('已删掉');
      if (Ink.missing().length) inkOrphOpen(); else inkOrphClose();
    }
  });
}

/* 一次性把旧批注重写成紧凑格式：笔迹一笔不动，体积降到约 1/3.7。
   旧的全精度存法（每点一个 {"x":0.8153038726993865,...} 对象、连重复点都留着）把 5MiB 配额占满后，
   setItem 会一直抛 QuotaExceededError，新批注根本存不进去 —— 「批注保留不住」就是这么来的。 */
function inkMigrate() {
  try {
    if (lsGet('inkFmt') === '2') return;
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.indexOf('ink:') === 0) keys.push(k);      // 先收齐再改，边遍历边写会乱序
    }
    for (const k of keys) {
      const old = lsGet(k);
      let d = null;
      try { d = JSON.parse(old || 'null'); } catch (_) { continue; }
      if (!d || !d.length || !d[0].pts) continue;          // 空的、或已经是新格式
      const packed = JSON.stringify(Ink.pack(Ink.unpack(d)));
      if (packed.length >= old.length) continue;
      try {
        localStorage.setItem(k, packed);                   // 覆盖写：新值更小，配额上放得下
      } catch (_) {
        try { localStorage.removeItem(k); localStorage.setItem(k, packed); }   // 满得连覆盖都被拒
        catch (_) { try { localStorage.setItem(k, old); } catch (_) {} }       // 还不行就原样放回
      }
    }
    lsSet('inkFmt', '2');
  } catch (e) {
    // 迁移是尽力而为（里面每一步都有自己的降级），但整体失败不该无声无息：
    // 没迁成的话下次进来还会再试一遍，是幂等的。
    console.warn('[批注] 旧格式迁移未完成：%s', (e && e.message) || e);
  }
}
inkMigrate();

/* 把本地存着的旧批注传到服务器，传上去就把本地那份删掉。
   跑完 localStorage 里的 ink: 基本清空 —— 5MiB 配额那个坎从根上没了（老批注是 pixel 锚，
   行为和以前一样；以后重新画的才带文本锚）。失败就留着，下次进应用再传。 */
async function inkUpload() {
  let keys = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.indexOf('ink:') === 0) keys.push(k);
    }
  } catch (_) { return; }
  for (const k of keys) {
    const target = k.slice(4);
    if (!target) continue;
    await Ink.flush(target);             // flush 读本地暂存、传上去、成功即删本地
  }
}
setTimeout(inkUpload, 3000);             // 别和启动那波请求抢，晚一点再传

/* ================= 通用停靠（草稿纸 / AI 面板共用） =================
   半屏只是默认值：交界处的分隔线可以直接拖，比例按「每个停靠位」分别记住；
   ✥ 手柄按住拖到屏幕任一边 → 松手吸附成那半边（拖到正中 = 全屏）。 */
const DOCK_NAME = { bottom: '下半屏', top: '上半屏', right: '右半屏', left: '左半屏', full: '全屏' };
const dockVert = (d) => d === 'left' || d === 'right';

function createDock(el, key, defDock, onChange) {
  const st = { dock: defDock, prev: defDock, sizes: { bottom: 0, top: 0, left: 0, right: 0 } };
  const defSize = (d) => dockVert(d) ? Math.round(innerWidth * .5) : Math.round(innerHeight * .46);
  const size = (d) => {                       // 记住的大小；没拖过就是一半。换屏也不会越界
    const v = st.sizes[d] || defSize(d);
    const max = dockVert(d) ? innerWidth * .95 : innerHeight * .95;
    const min = dockVert(d) ? 280 : 190;
    return Math.round(Math.min(max, Math.max(min, v)));
  };
  const save = () => { try { lsSet(key, JSON.stringify({ d: st.dock, sizes: st.sizes })); } catch (_) {} };
  (function load() {
    try {
      const d = JSON.parse(lsGet(key) || 'null');
      if (!d) return;
      if (DOCK_NAME[d.d]) { st.dock = d.d; st.prev = d.d === 'full' ? defDock : d.d; }
      if (d.sizes) Object.assign(st.sizes, d.sizes);
      else { if (d.h) { st.sizes.bottom = d.h; st.sizes.top = d.h; }    // 兼容旧格式
             if (d.w) { st.sizes.left = d.w; st.sizes.right = d.w; } }
    } catch (_) {}
  })();

  function apply(doSave) {
    Object.keys(DOCK_NAME).forEach(d => el.classList.toggle('dk-' + d, d === st.dock));
    if (st.dock !== 'full') {
      if (dockVert(st.dock)) el.style.setProperty('--dk-w', size(st.dock) + 'px');
      else el.style.setProperty('--dk-h', size(st.dock) + 'px');
    }
    if (doSave) save();
    requestAnimationFrame(() => { if (onChange) onChange(); applyPush(); avoidFab(); });
  }
  function set(d, quiet) {
    if (!DOCK_NAME[d]) return;
    if (d !== 'full') st.prev = d;
    st.dock = d; apply(true);
    if (!quiet) toast(d === 'full' ? '全屏' : '已停靠：' + DOCK_NAME[d]);
  }
  function toggleFull() { set(st.dock === 'full' ? (st.prev || defDock) : 'full', true); }

  const box = (z) => z === 'full' ? { left: 0, top: 0, width: innerWidth, height: innerHeight }
    : z === 'left' ? { left: 0, top: 0, width: size('left'), height: innerHeight }
      : z === 'right' ? { left: innerWidth - size('right'), top: 0, width: size('right'), height: innerHeight }
        : z === 'top' ? { left: 0, top: 0, width: innerWidth, height: size('top') }
          : { left: 0, top: innerHeight - size('bottom'), width: innerWidth, height: size('bottom') };
  const zoneAt = (x, y) => x < innerWidth * .18 ? 'left' : x > innerWidth * .82 ? 'right'
    : y < innerHeight * .15 ? 'top' : y > innerHeight * .85 ? 'bottom' : 'full';

  function dockDrag(e) {                      // 按住 ✥ 拖 → 松手吸附
    e.preventDefault();
    el.classList.add('dragging');
    let zone = st.dock;
    const show = (z) => {
      const s = $('#dock-snap'), b = box(z);
      s.style.left = b.left + 'px'; s.style.top = b.top + 'px';
      s.style.width = b.width + 'px'; s.style.height = b.height + 'px';
      s.classList.remove('hidden');
    };
    const mv = (ev) => { zone = zoneAt(ev.clientX, ev.clientY); show(zone); };
    const up = () => {
      removeEventListener('pointermove', mv); removeEventListener('pointerup', up);
      el.classList.remove('dragging');
      $('#dock-snap').classList.add('hidden');
      if (zone !== st.dock) set(zone);        // 大小沿用该停靠位上次拖成的比例
    };
    show(zone);
    addEventListener('pointermove', mv); addEventListener('pointerup', up);
  }

  const grip = document.createElement('div');   // 交界处那条分隔线
  grip.className = 'dk-grip';
  grip.title = '拖动改大小 · 双击复位成一半';
  el.appendChild(grip);
  grip.addEventListener('pointerdown', (e) => {
    if (st.dock === 'full') return;
    e.preventDefault();
    // ★ 关键：把指针锁在 grip 上。不然拖动时指针一旦划过 PDF 的 iframe，pointerup 会被 iframe 吞掉，
    //   父窗口收不到「松手」→ 表现就是「松开鼠标还在调大小，一动就变」。
    try { grip.setPointerCapture(e.pointerId); } catch (_) {}
    document.body.classList.add(dockVert(st.dock) ? 'dk-rz-x' : 'dk-rz-y');
    grip.classList.add('on');
    const mv = (ev) => {
      st.sizes[st.dock] = st.dock === 'bottom' ? innerHeight - ev.clientY
        : st.dock === 'top' ? ev.clientY
          : st.dock === 'right' ? innerWidth - ev.clientX
            : ev.clientX;
      apply(false);
    };
    const up = () => {
      grip.removeEventListener('pointermove', mv);
      grip.removeEventListener('pointerup', up);
      grip.removeEventListener('pointercancel', up);
      try { grip.releasePointerCapture(e.pointerId); } catch (_) {}
      document.body.classList.remove('dk-rz-x', 'dk-rz-y');
      grip.classList.remove('on');
      st.sizes[st.dock] = size(st.dock);
      apply(true);
    };
    grip.addEventListener('pointermove', mv);
    grip.addEventListener('pointerup', up);
    grip.addEventListener('pointercancel', up);
  });
  grip.addEventListener('dblclick', () => {
    if (st.dock === 'full') return;
    st.sizes[st.dock] = 0; apply(true); toast('已复位成一半');
  });

  addEventListener('resize', () => { if (!el.classList.contains('hidden')) apply(false); });
  return { st, apply, set, toggleFull, dockDrag, isFull: () => st.dock === 'full' };
}

/* 记住的位置要按「当前窗口」夹回来：换台设备 / 桌面版窗口更小时，
   否则球会停在窗口外面，看起来就是「悬浮球不见了」。 */
function fabClamp() {
  const fab = $('#fab');
  if (!fab || !innerWidth || !innerHeight) return;      // 还没完成布局就先别动
  if (!fab.style.left && !fab.style.top) return;        // 没拖过 → 用 CSS 默认角落，不用管
  const r = fab.getBoundingClientRect();
  const w = r.width || 50, h = r.height || 50;
  const x = Math.min(Math.max(4, r.left), innerWidth - w - 4);
  const y = Math.min(Math.max(4, r.top), innerHeight - h - 4);
  if (Math.abs(x - r.left) < .5 && Math.abs(y - r.top) < .5) return;
  fab.style.left = x + 'px'; fab.style.top = y + 'px';
  fab.style.right = 'auto'; fab.style.bottom = 'auto';
  try { lsSet('aifab', JSON.stringify({ x, y })); } catch (_) {}
}
addEventListener('resize', fabClamp);
addEventListener('load', () => requestAnimationFrame(fabClamp));

/* 停靠面板占屏后，把页面内容挤到剩下的可见区（卡片会自动重排，不再被盖住） */
function applyPush() {
  const p = { left: 0, right: 0, top: 0, bottom: 0 };
  [$('#pad'), $('#ai-panel'), $('#matpad')].forEach(el => {
    if (!el || el.classList.contains('hidden') || el.classList.contains('dk-full')) return;
    const d = Object.keys(DOCK_NAME).find(k => el.classList.contains('dk-' + k));
    if (!d || d === 'full') return;
    const r = el.getBoundingClientRect();
    p[d] = Math.max(p[d], Math.round(dockVert(d) ? r.width : r.height));
  });
  const s = document.body.style;
  s.setProperty('--push-l', p.left + 'px');
  s.setProperty('--push-r', p.right + 'px');
  s.setProperty('--push-t', p.top + 'px');
  s.setProperty('--push-b', p.bottom + 'px');
}

/* 悬浮球别被面板压住：挡住就挪到面板外；面板全屏时藏起来 */
function avoidFab() {
  const fab = $('#fab');
  if (!fab || !innerWidth) return;
  const open = [$('#pad'), $('#ai-panel'), $('#matpad')].filter(p => p && !p.classList.contains('hidden'));
  document.body.classList.toggle('pad-full', open.some(p => p.classList.contains('dk-full')));
  if (!open.length || document.body.classList.contains('pad-full')) return;
  for (const p of open) {
    const r = p.getBoundingClientRect(), f = fab.getBoundingClientRect();
    if (!(f.left < r.right && f.right > r.left && f.top < r.bottom && f.bottom > r.top)) continue;
    const d = Object.keys(DOCK_NAME).find(k => p.classList.contains('dk-' + k));
    let x = f.left, y = f.top;
    if (d === 'right') x = r.left - f.width - 12;
    else if (d === 'left') x = r.right + 12;
    else if (d === 'bottom') y = r.top - f.height - 12;
    else if (d === 'top') y = r.bottom + 12;
    x = Math.min(Math.max(4, x), innerWidth - f.width - 4);
    y = Math.min(Math.max(4, y), innerHeight - f.height - 4);
    fab.style.left = x + 'px'; fab.style.top = y + 'px';
    fab.style.right = 'auto'; fab.style.bottom = 'auto';
    try { lsSet('aifab', JSON.stringify({ x, y })); } catch (_) {}
  }
}

/* 草稿纸的停靠实例（手机默认下半屏，电脑默认下半屏；想要别的自己拖） */
let padDk = null;

function padOpen() {
  if (!padInited) padInit();
  $('#pad').classList.remove('hidden');
  document.body.classList.add('pad-open');
  padDk.apply(false);
}
function padClose() {
  const wasDraft = padMode === 'draft';
  clearTimeout(padSaveT);
  if (wasDraft) padDraftSave(); else padSave();
  $('#pad').classList.add('hidden');
  document.body.classList.remove('pad-open', 'pad-full');
  applyPush(); avoidFab();
  if (wasDraft) {                                                 // 退出草稿本 → 回列表，恢复随手草稿纸
    padMode = 'scratch'; padDraftId = null;
    $('#pad-doc').classList.add('hidden');
    padLoad();
    loadDrafts();
  }
}
function padToggle() { $('#pad').classList.contains('hidden') ? padOpen() : padClose(); }
function padOnView() {
  /* 草稿纸现在是全局悬浮的：换页面不再收起——正好可以一边看成语词语、一边在旁边练着写。 */
}
