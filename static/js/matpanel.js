/* 给定资料面板（申论作答时看材料 + 手写笔勾画）
 *
 * 由 app.js 按它自己的区段边界切出（原 L10296-10429）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, IS_MOBILE, appConfirm, applyPush, avoidFab, c,
   createDock, hl, lsGet, lsSet, push, toast */

/* ================= 给定资料面板（申论作答时看材料 + 手写笔勾画） =================
   考场上就是拿笔在材料上划重点的。这里把材料做成可停靠的半屏面板（和 AI/草稿纸同一套停靠），
   上面盖一层透明画布：荧光笔划重点、笔写批注、橡皮擦掉。勾画按材料存本地，下次打开还在。 */
const MAT_COLORS = ['#f0a500', '#2fa36c', '#e05a7d', '#1a6fb5'];
let matDk = null, matInited = false;
let matKey = '', matStrokes = [], matCur = null, matDrawing = false, matSawPen = false;
let matTool = 'hl', matColor = MAT_COLORS[0], matRaf = 0;
let matCv, matCtx;

const matW = () => matCv.clientWidth || 1;
function matPt(e) {
  const r = matCv.getBoundingClientRect(), w = r.width || 1;
  return { x: (e.clientX - r.left) / w, y: (e.clientY - r.top) / w,
    p: (e.pointerType === 'pen' && e.pressure > 0) ? e.pressure : 0 };
}
function matDrawStroke(ctx, s, W) {
  const pts = s.pts;
  if (!pts || !pts.length) return;
  ctx.save();
  ctx.lineJoin = ctx.lineCap = 'round';
  if (s.tool === 'eraser') { ctx.globalCompositeOperation = 'destination-out'; ctx.strokeStyle = '#000'; ctx.lineWidth = 22; }
  else if (s.tool === 'hl') { ctx.strokeStyle = s.color; ctx.globalAlpha = .32; ctx.lineWidth = 15; ctx.lineCap = 'butt'; }
  else { ctx.strokeStyle = s.color; ctx.lineWidth = 2.4; }
  ctx.beginPath();
  ctx.moveTo(pts[0].x * W, pts[0].y * W);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x * W, pts[i].y * W);
  if (pts.length === 1) ctx.lineTo(pts[0].x * W + .1, pts[0].y * W + .1);
  ctx.stroke();
  ctx.restore();
}
function matPaint() {
  const w = matCv.clientWidth, h = matCv.clientHeight;
  matCtx.clearRect(0, 0, w, h);
  const W = matW();
  for (const s of matStrokes) matDrawStroke(matCtx, s, W);
  if (matCur) matDrawStroke(matCtx, matCur, W);
}
function matFit() {
  const inner = $('#mat-inner');
  if (!inner || !matCv) return;
  const w = inner.clientWidth, h = Math.max(inner.scrollHeight, $('#mat-scroll').clientHeight);
  if (!w) return;
  const dpr = Math.min(2, devicePixelRatio || 1);
  matCv.style.width = w + 'px'; matCv.style.height = h + 'px';
  matCv.width = Math.round(w * dpr); matCv.height = Math.round(h * dpr);
  matCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  matPaint();
}
function matSave() {
  if (!matKey) return;
  const r = (n) => Math.round(n * 1e4) / 1e4;
  // 这页勾画只存本地（考场上划重点是临时的，见面板顶部注释）。写失败必须让用户知道——
  // 原先这儿是 catch(_){}，配额满时划了一整篇材料全丢、界面还好好的。
  lsSet(matKey, JSON.stringify(matStrokes.map(s => ({
    t: s.tool, c: s.color, p: s.pts.map(q => [r(q.x), r(q.y)]),
  }))));
}
function matLoad(key) {
  matKey = key; matStrokes = [];
  try {
    const d = JSON.parse(lsGet(key) || 'null');
    if (d) matStrokes = d.map(s => ({ tool: s.t, color: s.c, pts: (s.p || []).map(q => ({ x: q[0], y: q[1] })) }));
  } catch (_) { /* 本地存的勾画读坏了就当没有，重新画即可 */ }
}
function matSyncUI() {
  document.querySelectorAll('#matpad [data-mt]').forEach(b => b.classList.toggle('on', b.dataset.mt === matTool));
  $('#mat-colors').innerHTML = MAT_COLORS.map(c =>
    `<i class="pad-c${c === matColor && matTool !== 'eraser' ? ' on' : ''}" data-mc="${c}" style="background:${c}"></i>`).join('');
}
function matInit() {
  matInited = true;
  matCv = $('#mat-cv'); matCtx = matCv.getContext('2d');
  matDk = createDock($('#matpad'), 'matDock', IS_MOBILE ? 'bottom' : 'right', matFit);

  matCv.addEventListener('pointerdown', e => {
    if (e.pointerType === 'pen') matSawPen = true;
    if (e.pointerType === 'touch' && matSawPen) return;   // 用过笔就防手掌误触
    if (e.button > 0) return;
    e.preventDefault();
    try { matCv.setPointerCapture(e.pointerId); } catch (_) { /* 捕获失败不影响画线，指针事件照样收得到 */ }
    matDrawing = true;
    matCur = { tool: matTool, color: matColor, pts: [matPt(e)] };
    matPaint();
  });
  matCv.addEventListener('pointermove', e => {
    if (!matDrawing || !matCur) return;
    e.preventDefault();
    let evs = [];
    try { if (e.getCoalescedEvents) evs = e.getCoalescedEvents(); } catch (_) { /* 有的 WebKit 返回空表，下面会退回事件本身 */ }
    if (!evs.length) evs = [e];
    for (const ev of evs) matCur.pts.push(matPt(ev));
    if (!matRaf) matRaf = requestAnimationFrame(() => { matRaf = 0; matPaint(); });
  });
  const up = () => {
    if (!matDrawing) return;
    matDrawing = false;
    if (matCur) { matStrokes.push(matCur); matCur = null; matPaint(); matSave(); }
  };
  matCv.addEventListener('pointerup', up);
  matCv.addEventListener('pointercancel', up);
  matCv.addEventListener('pointerleave', up);

  $('#matpad').addEventListener('click', e => {
    const t = e.target.closest('[data-mt]');
    if (t) { matTool = t.dataset.mt; matSyncUI(); return; }
    const c = e.target.closest('[data-mc]');
    if (c) { matColor = c.dataset.mc; if (matTool === 'eraser') matTool = 'hl'; matSyncUI(); }
  });
  $('#mat-clear').onclick = async () => {
    if (!matStrokes.length) return;
    if (!await appConfirm('清除这份材料上的全部勾画？', { title: '给定资料', okText: '清除' })) return;
    matStrokes = []; matPaint(); matSave(); toast('已清除');
  };
  $('#mat-dock').addEventListener('pointerdown', (e) => matDk.dockDrag(e));
  $('#mat-full').onclick = () => matDk.toggleFull();
  $('#mat-close').onclick = matClose;
  addEventListener('resize', () => { if (!$('#matpad').classList.contains('hidden')) matFit(); });
}
function matOpen(text, key) {
  if (!matInited) matInit();
  $('#mat-text').textContent = text || '（这份卷子没有给定资料）';
  matLoad('matmark:' + key);
  $('#matpad').classList.remove('hidden');
  matSyncUI();
  matDk.apply(false);
  requestAnimationFrame(() => { matFit(); applyPush(); avoidFab(); });
}
function matClose() {
  matSave();
  $('#matpad').classList.add('hidden');
  document.body.classList.remove('pad-full');
  applyPush(); avoidFab();
}
