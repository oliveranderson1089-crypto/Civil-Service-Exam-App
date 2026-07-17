/* 草稿纸（做题时演算用；只写不识别）
 *
 * 由 app.js 按它自己的区段边界切出（原 L8872-9160）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, ME, api, appConfirm, c, createDock,
   draft, hl, lsGet, lsSet, padClose, padDk,
   push, toast */

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
