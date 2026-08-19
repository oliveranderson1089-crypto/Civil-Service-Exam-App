/* 手写输入板（数位板/手指 → 手写识别 → 填答案框）
 *
 * 由 app.js 按它自己的区段边界切出（原 L4030-4269）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, back, c, esc, lsGet,
   lsSet, push */

/* ============= 手写输入板（申论作答：数位板/手指 → Google 手写识别 → 填答案框） ============= */
const hwEl = {}; let hwTarget = null, hwStrokes = [], hwCur = null, hwT0 = 0, hwDrawing = false, hwTimer = null;
let hwAuto = lsGet('hwAuto') !== '0';   // 自动上屏首选字（默认开），连续写更快
let hwCommitted = null;                                 // 刚自动上屏的字，可点别的候选替换
let hwSess = 0;    // 会话代数：开板/关板各加一。识别是异步的，关板后回来的结果按代数作废
                   // ——不然那一下 value 赋值会打断输入法正在拼的字，拼音直接按字母上屏
let hwFs = lsGet('hwFs') === '1';        // 全屏透明手写：看得到后面正在填入的答案
let hwEngine = lsGet('hwEng') || 'cloud';  // 默认云端 Google(准)；'local'=端上ML Kit/本地Zinnia(快)
function hwInit() {
  ['modal', 'canvas', 'cands', 'count', 'close', 'undo', 'clear', 'space', 'nl', 'back', 'done', 'auto', 'fs', 'eng', 'punc', 'pan']
    .forEach(k => hwEl[k] = $('#hw-' + k));
  hwEl.engWrap = $('#hw-eng-wrap');
  hwEl.puncbar = $('#hw-puncbar');
  const cv = hwEl.canvas, ctx = cv.getContext('2d');
  // 「已写完的笔画」画在离屏层上；每帧只把离屏层贴回来 + 画正在写的这一笔。
  // 原来每次 pointermove 都要重画田字格和全部笔画，写多几笔就明显拖影——草稿本没这个问题就是因为分了层。
  const base = document.createElement('canvas');
  const bctx = base.getContext('2d');
  let hwRaf = 0;
  function fit() {
    const r = cv.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    cv.width = base.width = r.width * dpr;
    cv.height = base.height = r.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    bctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    hwRebuild();
  }
  function pos(e) {
    const r = cv.getBoundingClientRect();
    const t = e.touches ? e.touches[0] : e;
    return { x: (t.clientX - r.left), y: (t.clientY - r.top) };
  }
  const hwInk = () => document.body.classList.contains('dark') ? '#e8edf5' : '#1a2230';
  function drawStroke(c, s) {
    if (!s || s.x.length < 1) return;
    c.strokeStyle = hwInk();
    c.lineWidth = 3.2; c.lineJoin = c.lineCap = 'round'; c.setLineDash([]);
    c.beginPath(); c.moveTo(s.x[0], s.y[0]);
    for (let i = 1; i < s.x.length; i++) c.lineTo(s.x[i], s.y[i]);
    if (s.x.length === 1) c.lineTo(s.x[0] + 0.1, s.y[0] + 0.1);
    c.stroke();
  }
  function hwRebuild() {              // 重建离屏层：田字格 + 已写完的笔画（撤销/清空/切主题才需要）
    const w = cv.clientWidth, h = cv.clientHeight;
    bctx.clearRect(0, 0, w, h);
    bctx.save();
    // 田字格底改成透明之后（评审方案 02），格线是压在题目文字上的 —— 原来那两个
    // 浅色值放在白底上正好，放在字上就糊了，各加深一档才分得清哪儿是格、哪儿是字
    bctx.strokeStyle = document.body.classList.contains('dark') ? '#3d4a5f' : '#cbd4e2';
    bctx.lineWidth = 1; bctx.setLineDash([6, 6]);
    bctx.beginPath();
    bctx.moveTo(w / 2, 6); bctx.lineTo(w / 2, h - 6);
    bctx.moveTo(6, h / 2); bctx.lineTo(w - 6, h / 2);
    bctx.stroke();
    bctx.restore();
    for (const st of hwStrokes) drawStroke(bctx, st);
    hwPaint();
  }
  function hwPaint() {                // 每帧只干这两件事：贴离屏层 + 画正在写的这一笔
    const w = cv.clientWidth, h = cv.clientHeight;
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(base, 0, 0, w, h);
    if (hwCur) drawStroke(ctx, hwCur);
  }
  hwRedraw = hwRebuild;
  function start(e) {
    e.preventDefault(); hwDrawing = true;
    hwCommitted = null;                        // 又开始写了，取消"可替换刚上屏的字"
    if (!hwStrokes.length && !hwCur) hwT0 = Date.now();
    const p = pos(e); hwCur = { x: [p.x], y: [p.y], t: [Date.now() - hwT0] };
    clearTimeout(hwTimer);
  }
  function move(e) {
    if (!hwDrawing || !hwCur) return;
    e.preventDefault();
    let evs = [];                       // 高频合并采样 → 线更顺（有的 WebKit 返回空表，退回事件本身）
    try { if (e.getCoalescedEvents) evs = e.getCoalescedEvents(); } catch (_) { /* 有的 WebKit 返回空表，下面会退回事件本身 */ }
    if (!evs.length) evs = [e];
    for (const ev of evs) {
      const p = pos(ev);
      hwCur.x.push(p.x); hwCur.y.push(p.y); hwCur.t.push(Date.now() - hwT0);
    }
    if (!hwRaf) hwRaf = requestAnimationFrame(() => { hwRaf = 0; hwPaint(); });
  }
  function end(e) {
    if (!hwDrawing) return;
    e && e.preventDefault(); hwDrawing = false;
    if (hwCur) { hwStrokes.push(hwCur); drawStroke(bctx, hwCur); hwCur = null; hwPaint(); }
    clearTimeout(hwTimer);
    // 停笔就处理：自动=入队并清画布(接着写)，手动=出候选等你点。多笔画的字留足写完时间
    hwTimer = setTimeout(() => (hwAuto ? hwFlush() : hwRecognizeManual()), hwAuto ? 500 : 300);
  }
  cv.addEventListener('pointerdown', start);
  cv.addEventListener('pointermove', move);
  cv.addEventListener('pointerup', end);
  cv.addEventListener('pointerleave', end);
  hwEl._fit = fit;
  hwEl.close.onclick = hwClose;
  hwEl.clear.onclick = () => { hwStrokes = []; hwCur = null; hwRedraw(); hwSetCands([]); };
  hwEl.undo.onclick = () => { hwStrokes.pop(); hwRedraw(); if (!hwStrokes.length) hwSetCands([]); else if (!hwAuto) hwRecognizeManual(); };
  hwEl.space.onclick = () => hwInsert(' ');
  hwEl.nl.onclick = () => hwInsert('\n');
  hwEl.back.onclick = () => {
    if (!hwTarget) return;
    // 从光标处删：有选区删选区，无选区删光标前一个字（原来一律删末尾，定位到别处也删不掉那里）
    const v = hwTarget.value;
    let s = hwTarget.selectionStart, e = hwTarget.selectionEnd;
    if (s == null || e == null) s = e = v.length;   // 拿不到光标就退回删末尾
    if (s !== e) { hwTarget.value = v.slice(0, s) + v.slice(e); hwTarget.selectionStart = hwTarget.selectionEnd = s; }
    else if (s > 0) { hwTarget.value = v.slice(0, s - 1) + v.slice(s); hwTarget.selectionStart = hwTarget.selectionEnd = s - 1; }
    hwCommitted = null; hwFireInput();
  };
  hwEl.done.onclick = hwClose;
  // 标点：手写识别标点不准，给一排常用标点直接点填
  const HW_PUNCS = ['，', '。', '、', '；', '：', '？', '！', '“', '”', '‘', '’', '（', '）', '《', '》', '…', '—', '·', '【', '】'];
  if (hwEl.punc && hwEl.puncbar) {
    hwEl.puncbar.innerHTML = HW_PUNCS.map(p => `<button type="button" class="hw-punc-c" data-p="${p}">${p}</button>`).join('');
    hwEl.punc.onclick = () => { const hidden = hwEl.puncbar.classList.toggle('hidden'); hwEl.punc.classList.toggle('on', !hidden); };
    hwEl.puncbar.onclick = (ev) => { const b = ev.target.closest('[data-p]'); if (b) hwInsert(b.dataset.p); };
  }
  // ✋ 滑动：让画布“看穿”，可滚动后面正在参考的内容；再点一下恢复手写（全屏透明时最有用）
  if (hwEl.pan) hwEl.pan.onclick = () => { const on = hwEl.modal.classList.toggle('hw-pan-on'); hwEl.pan.classList.toggle('on', on); };
  hwEl.auto.checked = hwAuto;
  hwEl.auto.onchange = () => { hwAuto = hwEl.auto.checked; lsSet('hwAuto', hwAuto ? '1' : '0'); };
  if (hwEl.fs) hwEl.fs.onclick = () => { hwFs = !hwFs; lsSet('hwFs', hwFs ? '1' : '0'); hwApplyFs(); };
  // 默认云端 Google(准)，打勾切「更快(本地/端上)」——手机 ML Kit、电脑 Zinnia
  if (hwEl.eng) {
    hwEl.eng.checked = (hwEngine === 'local');
    hwEl.eng.onchange = () => {
      hwEngine = hwEl.eng.checked ? 'local' : 'cloud'; lsSet('hwEng', hwEngine);
      try { if (hwEngine === 'local' && window.GongkaoNative && GongkaoNative.hwPrepare) GongkaoNative.hwPrepare(); } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }
    };
  }
}
function hwApplyFs() {
  hwEl.modal.classList.toggle('hw-fs', hwFs);
  if (hwEl.fs) hwEl.fs.classList.toggle('on', hwFs);
  requestAnimationFrame(() => { if (hwEl._fit) hwEl._fit(); });   // 尺寸变了，重新适配画布
}
let hwRedraw = () => {};
let hwLastCands = [], hwQueue = [], hwBusy = false;
function hwInk() {
  const cv = hwEl.canvas;
  return { w: Math.round(cv.clientWidth), h: Math.round(cv.clientHeight),
           ink: hwStrokes.map(s => [s.x.map(v => Math.round(v)), s.y.map(v => Math.round(v)), s.t]) };
}
// APK 内置离线手写（ML Kit）：可用则优先，识别瞬时且离线；结果经原生回调
let __hwReq = 0; const __hwCbs = {};
window.__hwNative = function (reqId, jsonStr) {
  const cb = __hwCbs[reqId]; if (!cb) return; delete __hwCbs[reqId];
  let r = null; try { r = JSON.parse(jsonStr); } catch (_) { /* 识别服务返回的不是 JSON，下面按「没识别出来」处理 */ }
  cb(r && r.ok ? (r.candidates || []) : null);   // null = 模型未就绪/失败 → 退服务端
};
function hwNativeReady() {
  try { return !!(window.GongkaoNative && GongkaoNative.hwAvailable && GongkaoNative.hwAvailable()); }
  catch (_) { return false; }
}
function hwNativeRecognize(payload) {
  return new Promise(resolve => {
    const id = ++__hwReq; __hwCbs[id] = resolve;
    try { GongkaoNative.hwRecognize(id, JSON.stringify(payload)); }
    catch (_) { delete __hwCbs[id]; resolve(null); return; }
    setTimeout(() => { if (__hwCbs[id]) { delete __hwCbs[id]; resolve(null); } }, 5000);
  });
}
function hwApi(url, payload) {
  return api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
    .then(d => (d && d.candidates) || []).catch(() => []);
}
// 统一识别：APK 端上 ML Kit 优先；网页/桌面按开关走「本地 Zinnia(快)」或「云端 Google(准)」，本地无果自动退云端
async function hwCall(payload) {
  if (hwEngine !== 'local') return hwApi('/api/handwrite', payload);   // 默认：手机/电脑都走 Google(准)
  // 「更快(本地)」：手机端上 ML Kit，电脑本地 Zinnia，都退云端兜底
  if (hwNativeReady()) {
    const c = await hwNativeRecognize(payload);
    if (c) return c;
  }
  const local = await hwApi('/api/handwrite/local', payload);
  if (local.length) return local;
  return hwApi('/api/handwrite', payload);
}
// 自动模式：把这个字入队、立刻清空画布接着写下一个；识别在后台排队跟上、按顺序填字
function hwFlush() {
  if (!hwStrokes.length || !hwTarget) return;
  hwQueue.push(hwInk());
  hwCommitted = null;
  hwStrokes = []; hwCur = null; hwRedraw();
  hwPump();
}
async function hwPump() {
  if (hwBusy || !hwQueue.length) return;
  hwBusy = true;
  const job = hwQueue.shift();
  const sess = hwSess;                 // 这一笔属于哪次手写会话
  const cands = await hwCall(job);
  hwBusy = false;
  if (sess !== hwSess) return;         // 板已经关了（或换了输入框）：这次结果作废，绝不能再动输入框
  if (cands.length) { hwLastCands = cands; hwInsert(cands[0]); hwCommitted = cands[0]; hwSetCands(cands, cands[0]); }
  hwPump();     // 处理队列里下一个字
}
// 手动模式：识别后展示候选，等你点（不清画布）
async function hwRecognizeManual() {
  if (!hwStrokes.length) return;
  hwSetCands(null);
  const sess = hwSess;
  const cands = await hwCall(hwInk());
  if (sess !== hwSess) return;         // 同上：板关了就别再改候选区
  hwLastCands = cands;
  hwSetCands(hwLastCands);
}
function hwSetCands(list, picked) {
  if (list === null) { hwEl.cands.innerHTML = '<span class="hw-hint">识别中…</span>'; return; }
  if (!list.length) { hwEl.cands.innerHTML = '<span class="hw-hint">在田字格里写字，' + (hwAuto ? '停笔即自动上屏' : '写完点候选字填入') + '</span>'; return; }
  hwEl.cands.innerHTML = (picked ? '<span class="hw-hint hw-hint-s">已填，可点其它字更正 →</span>' : '') +
    list.map(c => `<button class="hw-cand ${c === picked ? 'filled' : ''}" data-c="${esc(c)}">${esc(c)}</button>`).join('');
}
function hwInsert(ch) {   // 只插文字，不动画布（流水线里画布可能已在写下一个字）
  if (!hwTarget) return;
  const s = hwTarget.selectionStart, e = hwTarget.selectionEnd, v = hwTarget.value;
  if (s != null && e != null) {
    hwTarget.value = v.slice(0, s) + ch + v.slice(e);
    const p = s + ch.length; hwTarget.selectionStart = hwTarget.selectionEnd = p;
  } else { hwTarget.value = v + ch; }
  hwFireInput();
}
function hwClearPad() { hwStrokes = []; hwCur = null; hwRedraw(); hwSetCands([]); }
function hwFireInput() {
  hwTarget.dispatchEvent(new Event('input', { bubbles: true }));
  hwEl.count.textContent = (hwTarget.value || '').replace(/\s/g, '').length;
}
hwEl.candsClick = null;
function openHandwrite(targetId) {
  if (!hwEl.canvas) hwInit();
  hwTarget = document.getElementById(targetId);
  if (!hwTarget) return;
  hwStrokes = []; hwCur = null; hwQueue = []; hwBusy = false; hwCommitted = null;
  hwSess++;
  hwResetTools();
  try { if (hwEngine === 'local' && window.GongkaoNative && GongkaoNative.hwPrepare) GongkaoNative.hwPrepare(); } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }  // 仅"更快"模式才预下载端上模型
  hwEl.modal.classList.remove('hidden');
  hwApplyFs();
  requestAnimationFrame(() => { hwEl._fit(); hwSetCands([]); hwFireInput(); });
}
function hwClose() {
  hwEl.modal.classList.add('hidden');
  clearTimeout(hwTimer); hwStrokes = []; hwCur = null; hwQueue = []; hwBusy = false; hwCommitted = null;
  hwSess++;
  hwResetTools();
  const t = hwTarget; hwTarget = null;   // 断开：在飞的识别回来时 hwInsert 直接空转
  if (t) requestAnimationFrame(() => t.focus());   // 等面板真的收起来再还焦点，输入法上下文才接得上
}
function hwResetTools() {   // 收起标点条、退出滑动模式，避免上次残留
  hwEl.modal && hwEl.modal.classList.remove('hw-pan-on');
  if (hwEl.pan) hwEl.pan.classList.remove('on');
  if (hwEl.puncbar) hwEl.puncbar.classList.add('hidden');
  if (hwEl.punc) hwEl.punc.classList.remove('on');
}
document.addEventListener('click', e => {
  const o = e.target.closest('[data-hw]');
  if (o) { e.preventDefault(); openHandwrite(o.dataset.hw); return; }
  const c = e.target.closest('.hw-cand');
  if (c) {
    const ch = c.dataset.c;
    if (hwCommitted && !hwStrokes.length) {
      // 刚自动上屏的字选错了：删掉它再填选中的字（更正）
      if (hwTarget) { hwTarget.value = hwTarget.value.slice(0, -1); }
      hwInsert(ch); hwCommitted = ch; hwSetCands(hwLastCands, ch);
    } else {
      hwInsert(ch); hwCommitted = null;
      if (!hwAuto) hwClearPad();   // 手动模式：填完清画布，准备写下一个
    }
  }
});
