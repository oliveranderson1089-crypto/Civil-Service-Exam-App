/* 手写输入板 / 小题训练 / 专项练 / 成文 / 素材 / 任务 / 40 天路线 / 巩固测试
 *
 * 由 app.js 按它原有的区段边界切出（原 L4030-5672）。顺序即原顺序 —— index.html 里
 * 按同样次序引入，执行序与拆分前逐字节一致。
 *
 * 下面 /* global *​/ 是这个模块的依赖清单：它用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，这就是现成的 import 表。
 */
/* global $, _dtLastMat, api, appConfirm, back, c,
   composing, dtMaterial, emKey, esc, fmtDay, loadDaily,
   loadShared, lsGet, lsSet, ntfGo, openDtRecords, push,
   render, renderDtest, toast */

/* ============= 手写输入板（申论作答：数位板/手指 → Google 手写识别 → 填答案框） ============= */
const hwEl = {}; let hwTarget = null, hwStrokes = [], hwCur = null, hwT0 = 0, hwDrawing = false, hwTimer = null;
let hwAuto = lsGet('hwAuto') !== '0';   // 自动上屏首选字（默认开），连续写更快
let hwCommitted = null;                                 // 刚自动上屏的字，可点别的候选替换
let hwFs = lsGet('hwFs') === '1';        // 全屏透明手写：看得到后面正在填入的答案
let hwEngine = lsGet('hwEng') || 'cloud';  // 默认云端 Google(准)；'local'=端上ML Kit/本地Zinnia(快)
function hwInit() {
  ['modal', 'canvas', 'cands', 'count', 'close', 'undo', 'clear', 'space', 'nl', 'back', 'done', 'auto', 'fs', 'eng']
    .forEach(k => hwEl[k] = $('#hw-' + k));
  hwEl.engWrap = $('#hw-eng-wrap');
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
    bctx.strokeStyle = document.body.classList.contains('dark') ? '#2a3446' : '#e3e8f0';
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
    try { if (e.getCoalescedEvents) evs = e.getCoalescedEvents(); } catch (_) {}
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
    hwTarget.value = hwTarget.value.slice(0, -1);
    hwCommitted = null; hwFireInput();
  };
  hwEl.done.onclick = hwClose;
  hwEl.auto.checked = hwAuto;
  hwEl.auto.onchange = () => { hwAuto = hwEl.auto.checked; lsSet('hwAuto', hwAuto ? '1' : '0'); };
  if (hwEl.fs) hwEl.fs.onclick = () => { hwFs = !hwFs; lsSet('hwFs', hwFs ? '1' : '0'); hwApplyFs(); };
  // 默认云端 Google(准)，打勾切「更快(本地/端上)」——手机 ML Kit、电脑 Zinnia
  if (hwEl.eng) {
    hwEl.eng.checked = (hwEngine === 'local');
    hwEl.eng.onchange = () => {
      hwEngine = hwEl.eng.checked ? 'local' : 'cloud'; lsSet('hwEng', hwEngine);
      try { if (hwEngine === 'local' && window.GongkaoNative && GongkaoNative.hwPrepare) GongkaoNative.hwPrepare(); } catch (_) {}
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
  let r = null; try { r = JSON.parse(jsonStr); } catch (_) {}
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
  if (!hwStrokes.length) return;
  hwQueue.push(hwInk());
  hwCommitted = null;
  hwStrokes = []; hwCur = null; hwRedraw();
  hwPump();
}
async function hwPump() {
  if (hwBusy || !hwQueue.length) return;
  hwBusy = true;
  const job = hwQueue.shift();
  const cands = await hwCall(job);
  if (cands.length) { hwLastCands = cands; hwInsert(cands[0]); hwCommitted = cands[0]; hwSetCands(cands, cands[0]); }
  hwBusy = false;
  hwPump();     // 处理队列里下一个字
}
// 手动模式：识别后展示候选，等你点（不清画布）
async function hwRecognizeManual() {
  if (!hwStrokes.length) return;
  hwSetCands(null);
  hwLastCands = await hwCall(hwInk());
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
  try { if (hwEngine === 'local' && window.GongkaoNative && GongkaoNative.hwPrepare) GongkaoNative.hwPrepare(); } catch (_) {}  // 仅"更快"模式才预下载端上模型
  hwEl.modal.classList.remove('hidden');
  hwApplyFs();
  requestAnimationFrame(() => { hwEl._fit(); hwSetCands([]); hwFireInput(); });
}
function hwClose() {
  hwEl.modal.classList.add('hidden');
  clearTimeout(hwTimer); hwStrokes = []; hwCur = null; hwQueue = []; hwBusy = false; hwCommitted = null;
  hwTarget && hwTarget.focus();
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

/* ============= 小题训练：找点 + 写点 =============
   归纳概括 / 综合分析 / 提出对策，难点是同一个：从材料里把要点找出来。
   所以拆成两步，每步单独纠错：
     第一步「找点」—— 只勾画不写字，判**找漏 / 找错 / 找重**
     第二步「写点」—— 照着勾到的地方写，判**概括到不到位**
   勾画粒度是**句**：申论找点本来就是找句子，句子边界明确才判得准
   （自由划词的区间对不齐采分点，判定必然变成玄学）。 */
let fdPaper = null, fdPicked = new Set(), fdStep = 1, fdCheck = null, fdDrag = null;

function openFind() {
  push({ view: 'find', title: '小题训练' });
  loadFindTypes();
  loadFindList();
}
let fdDoctypes = [];
async function loadFindTypes() {
  try {
    const d = await api('/api/find/types');
    fdDoctypes = d.doctypes || [];
    $('#fd-types').innerHTML = d.types.map((t, i) => `
      <div class="fd-type${i === 0 ? ' on' : ''}" data-fdt="${t.key}">
        <div class="fd-type-h"><b>${esc(t.name)}</b><span>${t.full} 分 · ${t.word_min}~${t.word_max} 字</span></div>
        <p>${esc(t.tip)}</p>
        <div class="fd-type-n">${t.n ? '练过 ' + t.n + ' 道' : '还没练过'}</div>
      </div>`).join('');
    // 贯彻执行的文种选择条：🎲 随机 + 各文种（点选后按该文种的真题字数出题）
    $('#fd-doctypes').innerHTML = '<span class="gw-sug-t">文种：</span>'
      + '<button class="chip tiny on" data-fdd="">🎲 随机</button>'
      + fdDoctypes.map(x => `<button class="chip tiny" data-fdd="${esc(x.k)}" title="${x.min}~${x.max} 字">${esc(x.k)}</button>`).join('');
    fdSyncDoctypes();
  } catch (e) { $('#fd-types').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
function fdSyncDoctypes() {   // 只有选中「贯彻执行」时才显示文种选择条
  $('#fd-doctypes').classList.toggle('hidden', fdType() !== 'guanche');
}
$('#fd-types').addEventListener('click', e => {
  const t = e.target.closest('[data-fdt]'); if (!t) return;
  document.querySelectorAll('#fd-types .fd-type').forEach(x => x.classList.toggle('on', x === t));
  fdSyncDoctypes();
});
$('#fd-doctypes').addEventListener('click', e => {
  const b = e.target.closest('[data-fdd]'); if (!b) return;
  document.querySelectorAll('#fd-doctypes .chip').forEach(x => x.classList.toggle('on', x === b));
});
const fdType = () => (document.querySelector('#fd-types .fd-type.on') || {}).dataset?.fdt || 'guina';
const fdDoctype = () => (document.querySelector('#fd-doctypes .chip.on') || {}).dataset?.fdd || '';

async function loadFindList() {
  const box = $('#fd-list');
  try {
    const d = await api('/api/find/papers');
    box.innerHTML = d.items.length ? d.items.map(x => `
      <div class="wr-day done" data-fdp="${x.id}">
        <div class="wr-day-d">${esc(x.type_name)}</div>
        <div class="wr-day-m"><b>${esc((x.stem || '').slice(0, 40))}</b>
          <span class="wr-w">${x.full} 分</span>
          <span class="wr-tag">${esc(x.source || '')}</span>
          ${x.done ? `<span class="fd-done">练过 ${x.done} 次</span>` : ''}</div>
      </div>`).join('') : '<p class="empty">还没有题。上面点「出一道」，或上传一份真题。</p>';
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#fd-list').addEventListener('click', e => {
  const c = e.target.closest('[data-fdp]'); if (c) openFindRun(+c.dataset.fdp);
});
$('#fd-gen').onclick = async () => {
  const b = $('#fd-gen'); b.disabled = true; b.textContent = '出题中…（约 30~60 秒）';
  $('#fd-msg').textContent = 'AI 正在按题型出对应材料（每则对齐真题单则字数、掺干扰信息），字数不够会自动扩写，再标采分点…';
  try {
    const d = await api('/api/find/gen', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qtype: fdType(), topic: $('#fd-topic').value.trim(), doctype: fdDoctype() }),
    });
    $('#fd-msg').textContent = '';
    openFindRun(d.id); loadFindList(); loadFindTypes();
  } catch (e) { toast(e.message, true); $('#fd-msg').textContent = ''; }
  b.disabled = false; b.textContent = '✍️ 出一道';
};
$('#fd-up').onclick = () => $('#fd-file').click();
$('#fd-file').onchange = async () => {
  const f = $('#fd-file').files[0]; if (!f) return;
  $('#fd-msg').textContent = '正在识别真题（拆材料和小题，再逐题标采分点，可能要一两分钟）…';
  const fd = new FormData(); fd.append('file', f);
  try {
    const d = await api('/api/find/upload', { method: 'POST', body: fd });
    $('#fd-msg').textContent = '';
    toast(`识别出 ${d.made.length} 道可练的小题` + (d.skipped.length ? `（${d.skipped.join('、')} 不属于找点训练，已跳过）` : ''));
    loadFindList(); loadFindTypes();
  } catch (e) { toast(e.message, true); $('#fd-msg').textContent = ''; }
  $('#fd-file').value = '';
};

/* ---- 做题：材料按句勾画 ---- */
async function openFindRun(pid) {
  fdPaper = null; fdPicked = new Set(); fdStep = 1; fdCheck = null;
  push({ view: 'findrun', title: '找点训练' });
  $('#fr-head').innerHTML = '<p class="empty">加载中…</p>';
  $('#fr-mat').innerHTML = ''; $('#fr-foot').innerHTML = '';
  try {
    fdPaper = await api('/api/find/paper/' + pid);
    frRender();
  } catch (e) { $('#fr-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

function frRender() {
  const p = fdPaper;
  $('#fr-head').innerHTML = `
    <div class="fr-step">
      <span class="${fdStep === 1 ? 'on' : 'done'}">① 找点</span>
      <span class="${fdStep === 2 ? 'on' : (fdStep > 2 ? 'done' : '')}">② 写点</span>
      <span class="${fdStep === 3 ? 'on' : ''}">③ 批改</span>
    </div>
    <div class="fr-stem">${esc(p.stem)}</div>
    <div class="fr-meta">${esc(p.type_name)} · ${p.full} 分 · 答案 ${p.word_min}~${p.word_max} 字
      · <b>共 ${p.n_points} 个采分点</b>${p.material_words ? ` · 给定资料 ${p.material_words} 字` : ''} · ${esc(p.source || '')}</div>`;
  frMat();
  frFoot();
}

function frMat() {
  const p = fdPaper;
  let html = '', lastP = -1;
  p.sents.forEach(s => {
    if (s.p !== lastP) { if (lastP >= 0) html += '</p>'; html += '<p class="fr-para">'; lastP = s.p; }
    if (s.head) { html += `<span class="fr-s fr-h">${esc(s.t)}</span>`; return; }
    const cls = ['fr-s'];
    if (fdPicked.has(s.i)) cls.push('on');
    if (fdCheck) {                               // 判完了：把对/错/漏直接标在原文上
      if (fdCheck.okSents.has(s.i)) cls.push('ok');
      else if (fdCheck.wrongSents.has(s.i)) cls.push('bad');
      else if (fdCheck.missSents.has(s.i)) cls.push('miss');
    }
    html += `<span class="${cls.join(' ')}" data-fs="${s.i}">${esc(s.t)}</span>`;
  });
  if (lastP >= 0) html += '</p>';
  $('#fr-mat').innerHTML = html;
}

// 勾画：点一句 = 选中/取消；按住拖过多句 = 连着选（鼠标和手写笔都走 pointer 事件）
$('#fr-mat').addEventListener('pointerdown', e => {
  if (fdStep !== 1) return;
  const s = e.target.closest('[data-fs]'); if (!s) return;
  const i = +s.dataset.fs;
  fdDrag = fdPicked.has(i) ? 'off' : 'on';       // 起手是选中的 → 这一拖都是取消
  frToggle(i, fdDrag === 'on');
  e.preventDefault();
});
$('#fr-mat').addEventListener('pointerover', e => {
  if (!fdDrag || fdStep !== 1) return;
  const s = e.target.closest('[data-fs]'); if (!s) return;
  frToggle(+s.dataset.fs, fdDrag === 'on');
});
document.addEventListener('pointerup', () => { fdDrag = null; });
function frToggle(i, on) {
  if (on) fdPicked.add(i); else fdPicked.delete(i);
  const el = document.querySelector(`[data-fs="${i}"]`);
  if (el) el.classList.toggle('on', on);
  const n = $('#fr-n'); if (n) n.textContent = fdPicked.size;
}

function frFoot() {
  const p = fdPaper;
  if (fdStep === 1) {
    $('#fr-foot').innerHTML = `
      <div class="fr-tip">🖍 在材料里<b>点句子</b>勾出你认为的要点（按住拖可以连选）。
        这一步<b>只找不写</b> —— 共 ${p.n_points} 个采分点，你勾了 <b id="fr-n">${fdPicked.size}</b> 句。</div>
      <button class="btn primary" id="fr-check">看看我找得对不对</button>`;
    $('#fr-check').onclick = frDoCheck;
    return;
  }
  if (fdStep === 2) {
    const picked = fdPaper.sents.filter(s => fdPicked.has(s.i));
    const gc = p.doctype;   // 贯彻执行：提示按文种格式成文
    $('#fr-foot').innerHTML = `
      <div class="fr-tip">✍️ 照着<b>你勾到的（绿色）</b>写要点。${gc
        ? `这是<b>贯彻执行题</b>，要按<b>${esc(p.doctype)}</b>的格式成文（要点全 + 格式对 + 语言得体）。`
        : `要<b>概括</b>，不是抄原文；<b>分条写</b>。`}
        ${p.word_min}~${p.word_max} 字。</div>
      ${gc && p.doctype_fmt ? `<div class="fr-fmt-tip">📋 <b>${esc(p.doctype)}</b>格式骨架：${esc(p.doctype_fmt)}</div>` : ''}
      <div class="fr-picked">${picked.map(s => `<div>· ${esc(s.t)}</div>`).join('') || '<i>你没勾到任何要点</i>'}</div>
      <textarea id="fr-ans" placeholder="一、…\n二、…\n三、…"></textarea>
      <div class="fr-wc"><span id="fr-wc">0</span> / ${p.word_max} 字</div>
      <button class="btn primary" id="fr-grade">交给我批</button>`;
    $('#fr-ans').oninput = () => {
      $('#fr-wc').textContent = $('#fr-ans').value.replace(/\s/g, '').length;
    };
    $('#fr-grade').onclick = frDoGrade;
  }
}

async function frDoCheck() {
  if (!fdPicked.size) { toast('先在材料里勾几句', true); return; }
  const b = $('#fr-check'); b.disabled = true; b.textContent = '判定中…';
  try {
    const r = await api('/api/find/check', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paper_id: fdPaper.id, sents: [...fdPicked] }),
    });
    // 把判定结果落到句子上：找对=绿，找错=红，找漏=黄（漏的句子考生本来没勾，这里直接点出来）
    r.okSents = new Set(r.ok.flatMap(x => x.sents));
    r.wrongSents = new Set(r.wrong.map(x => x.i));
    r.missSents = new Set(r.missed.flatMap(x => x.sents));
    fdCheck = r;
    frMat();
    $('#fr-foot').innerHTML = `
      <div class="fr-res">
        <div class="fr-score">找到 <b>${r.found}</b> / ${r.total} 个采分点
          <span class="fr-acc${r.acc < 60 ? ' bad' : ''}">${r.acc}%</span></div>
        ${r.missed.length ? `<div class="fr-sec miss"><div class="fr-sec-t">❌ 找漏了 ${r.missed.length} 个</div>
          ${r.missed.map(x => `<div class="fr-item">
            <b>[${x.score} 分] ${esc(x.point)}</b>
            <div class="fr-ev" data-fsgo="${x.sents[0]}">↗ 就在这句：${esc(x.evidence.slice(0, 50))}…</div>
          </div>`).join('')}</div>` : ''}
        ${r.wrong.length ? `<div class="fr-sec bad"><div class="fr-sec-t">⚠️ 找错了 ${r.wrong.length} 处
            <i>（这些是干扰信息，不是采分点）</i></div>
          ${r.wrong.map(x => `<div class="fr-item"><div class="fr-ev" data-fsgo="${x.i}">↗ ${esc(x.t.slice(0, 50))}…</div></div>`).join('')}</div>` : ''}
        ${r.dup.length ? `<div class="fr-sec dup"><div class="fr-sec-t">🔁 找重了 ${r.dup.length} 处</div>
          ${r.dup.map(x => `<div class="fr-item"><b>${esc(x.point)}</b>
            <div class="fr-ev">这一个点你勾了 ${x.sents.length} 句 —— 材料里换了个说法而已，答案里只算一个点</div>
          </div>`).join('')}</div>` : ''}
        ${r.ok.length ? `<div class="fr-sec ok"><div class="fr-sec-t">✅ 找对了 ${r.ok.length} 个</div>
          ${r.ok.map(x => `<div class="fr-item"><b>[${x.score} 分] ${esc(x.point)}</b></div>`).join('')}</div>` : ''}
      </div>
      <div class="fr-acts">
        <button class="btn" id="fr-redo">🔄 重新找一遍</button>
        <button class="btn primary" id="fr-next">下一步：照着写点子 →</button>
      </div>`;
    $('#fr-redo').onclick = () => { fdCheck = null; fdPicked = new Set(); frMat(); frFoot(); };
    $('#fr-next').onclick = () => {
      // 漏掉的点也补进勾画（不然第二步照着写，注定还是漏）—— 但它们在原文里仍标成黄的
      fdCheck.missSents.forEach(i => fdPicked.add(i));
      fdCheck.wrongSents.forEach(i => fdPicked.delete(i));
      fdStep = 2; frRender();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    };
  } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = '看看我找得对不对'; }
}
$('#fr-foot').addEventListener('click', e => {
  const g = e.target.closest('[data-fsgo]');    // 点一下跳到原文那句
  if (!g) return;
  const el = document.querySelector(`[data-fs="${g.dataset.fsgo}"]`);
  if (el) {
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    el.classList.add('flash');
    setTimeout(() => el.classList.remove('flash'), 1400);
  }
});

async function frDoGrade() {
  const ans = $('#fr-ans').value.trim();
  if (ans.replace(/\s/g, '').length < 20) { toast('写太少了', true); return; }
  const b = $('#fr-grade'); b.disabled = true; b.textContent = '批改中…（约 20 秒）';
  try {
    const g = await api('/api/find/grade', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paper_id: fdPaper.id, answer: ans, sents: [...fdPicked] }),
    });
    fdStep = 3;
    $('#fr-head').innerHTML = `
      <div class="fr-step"><span class="done">① 找点</span><span class="done">② 写点</span><span class="on">③ 批改</span></div>`
      + frScoreHtml(g);
    $('#fr-mat').innerHTML = '';
    $('#fr-foot').innerHTML = frResultBody(g) + `
      <div class="fr-acts">
        <button class="btn primary" id="fr-again">🔄 再练这道</button>
        <button class="btn" id="fr-back">换一道</button>
      </div>`;
    $('#fr-again').onclick = () => openFindRun(fdPaper.id);
    $('#fr-back').onclick = () => { back(); loadFindList(); };
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = '交给我批'; }
}
// 批改结果的两块 HTML，做题页和「做题记录」详情共用
function frScoreHtml(g) {
  return `<div class="fr-final"><b>${g.score}</b> / ${g.full} 分${g.content_score != null && g.format
    ? `<span class="fr-brk">内容 ${g.content_score}/${g.content_full} + 格式 ${g.format.score}/${g.format.full}</span>` : ''}</div>`;
}
function frResultBody(g) {
  const M = { full: ['✅', 'ok'], part: ['⚠️', 'part'], miss: ['❌', 'miss'] };
  return `<div class="fr-res">
      <div class="fr-sec-t">逐个采分点</div>
      ${(g.items || []).map(it => {
        const m = M[it.got] || M.miss;
        return `<div class="fr-item fr-g ${m[1]}">
          <b>${m[0]} [${it.score} 分] ${esc(it.point || '')}</b>
          <div class="fr-gc">${esc(it.comment || '')}</div></div>`;
      }).join('')}
      ${g.format ? `<div class="fr-sec fr-fmt"><div class="fr-sec-t">📋 格式（${esc(g.format.doctype || '')}）${g.format.grade ? ` · ${esc(g.format.grade)}` : ''}${g.format.full ? ` · ${g.format.score}/${g.format.full} 分` : ''}</div>
        ${(g.format.ok || []).length ? `<div class="fr-item">✅ 到位：${g.format.ok.map(esc).join('、')}</div>` : ''}
        ${(g.format.miss || []).length ? `<div class="fr-item">❌ 欠缺：${g.format.miss.map(esc).join('、')}</div>` : ''}
        ${g.format.comment ? `<div class="fr-gc">${esc(g.format.comment)}</div>` : ''}</div>` : ''}
      ${(g.style || []).length ? `<div class="fr-sec bad"><div class="fr-sec-t">表述问题</div>
        ${g.style.map(s => `<div class="fr-item">· ${esc(s)}</div>`).join('')}</div>` : ''}
      ${g.advice ? `<div class="fr-adv">💡 ${esc(g.advice)}</div>` : ''}
    </div>`;
}

/* ---- 找点/写点 做题记录：每次批改都留着，可回看题干、采分点、格式分、我写的答案 ---- */
$('#fd-recs').onclick = () => openFindRecs();
async function openFindRecs() {
  push({ view: 'findrec', title: '做题记录' });
  const box = $('#frr-list');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/find/records');
    box.innerHTML = d.items.length ? d.items.map(x => `
      <div class="wr-day done" data-frrec="${x.id}">
        <div class="wr-day-d">${esc(x.type_name)}${x.doctype ? ' · ' + esc(x.doctype) : ''}</div>
        <div class="wr-day-m"><b>${esc(x.stem || '')}</b>
          <span class="dr-acc${x.score >= x.full * 0.6 ? '' : ' bad'}">${x.score}/${x.full} 分</span>
          ${x.content_score != null ? `<span class="wr-tag">内容 ${x.content_score}/${x.content_full} + 格式 ${x.format_score}/${x.format_full}</span>` : ''}
          <span class="wr-w">${esc((x.created_at || '').slice(5, 16))}</span></div>
      </div>`).join('') : '<p class="empty">还没练过题。做完一道就会留在这里。</p>';
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#frr-list').addEventListener('click', e => {
  const c = e.target.closest('[data-frrec]'); if (c) openFindRec(+c.dataset.frrec);
});
async function openFindRec(rid) {
  push({ view: 'findrecd', title: '这次的批改' });
  $('#frd-head').innerHTML = '<p class="empty">加载中…</p>'; $('#frd-body').innerHTML = '';
  try {
    const d = await api('/api/find/record/' + rid);
    const g = d.grade || {}; g.score = d.score; g.full = d.full;
    $('#frd-head').innerHTML = `<div class="fr-stem">${esc(d.stem)}</div>
      <div class="fr-meta">${esc(d.type_name)} · ${d.full} 分 · 答案 ${d.word_min}~${d.word_max} 字 · ${esc((d.created_at || '').slice(0, 16))}</div>`
      + frScoreHtml(g);
    $('#frd-body').innerHTML = frResultBody(g)
      + `<div class="fr-sec"><div class="fr-sec-t">✍️ 我写的答案</div>
         <div class="frd-ans">${esc(d.answer).replace(/\n/g, '<br>')}</div></div>`
      + `<div class="fr-acts"><button class="btn primary" id="frd-again">🔄 再练这道</button>
         <button class="btn" id="frd-back">返回记录</button></div>`;
    $('#frd-again').onclick = () => openFindRun(d.paper_id);
    $('#frd-back').onclick = () => back();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) { $('#frd-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

/* ============= 专项练（行测六大板块）=============
   资料分析 / 判断推理 / 数量关系 —— 题型固定、有套路、拼速度，**题由程序生成**，答案由构造保证。
   常识判断 / 政治理论 / 言语理解 —— 考的是知识，构造不出来，**由 AI 按考试标准出题**；
     出好的题攒进题库（drill_bank），下次直接取，不用每次等十几秒。
   三档难度**真正改变题目**（不是贴个标签）；难度系数 = 预期得分率，做完告诉你比预期高还是低。
   两种模式：背题（选完即判 + 解析）/ 测试（做完交卷、服务端判分）。题量 5/10/15/20。
   每次做完**留一条完整记录**，可以回看每一题 —— 不是做完就丢。 */
let drBoard = '', drType = '', drItems = [], drIdx = 0, drAns = [], drSec = [], drT0 = 0, drTimer = 0;
let drLimit = 60, drLevel = 'mid', drN = 10, drMode = 'study', drToken = '', drCoef = 0.6, drLevels = [];

function openDrill(board) {
  drBoard = board;
  push({ view: 'drill', title: board + ' · 专项练' });
  loadDrillTypes();
}
async function loadDrillTypes() {
  const box = $('#dr-types');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api(`/api/drill/types?board=${encodeURIComponent(drBoard)}&level=${drLevel}`);
    drLimit = d.limit; drLevels = d.levels; drCoef = d.coef;
    $('#dr-intro').innerHTML = d.ai
      ? `这一块考的是<b>知识</b>，题由 AI 按考试标准出，<b>并且必须过第二个模型的独立核验</b>
         —— 两个模型答案不一致的题<b>不会发给你做</b>（实测能筛掉约 14%，其中有真的事实错误）。
         每题限时 ${d.limit} 秒。`
      : `这一块靠<b>练</b>不靠背：题型固定、有套路、拼速度。题由<b>程序生成</b>，答案由构造保证。每题限时 ${d.limit} 秒，做完给这一类的秒杀技巧。`;
    $('#dr-levels').innerHTML = d.levels.map(l =>
      `<button class="dr-lv${l.k === drLevel ? ' on' : ''}" data-drl="${l.k}">
         <b>${esc(l.name)}</b><span>${l.coef.toFixed(2)}</span></button>`).join('');
    drCoefTip();
    // 讲义里的「解题方法」章 —— 是方法不是题型，单独摆出来（做题时的秒杀技巧就出自这里）
    $('#dr-methods').innerHTML = (d.methods || []).length
      ? `<div class="dr-mth"><div class="dr-mth-t">📐 解题方法（讲义第一章）</div>
          ${d.methods.map(m => `<div class="dr-mth-i">· ${esc(m)}</div>`).join('')}</div>` : '';
    $('#dr-missing').innerHTML = d.missing
      ? `<div class="dr-miss">⚠️ ${esc(d.missing)}</div>` : '';
    box.innerHTML = d.types.map((t, i) => {
      const done = t.n > 0;
      const weak = done && t.acc < Math.round(drCoef * 100);   // 低于这个难度的预期得分率 = 薄弱
      return `<div class="dr-card${weak ? ' weak' : ''}" data-drt="${esc(t.type)}">
        <div class="dr-card-h">
          <b><span class="dr-no">${t.ord + 1}</span>${esc(t.type)}</b>
          ${done ? `<span class="dr-acc${weak ? ' bad' : ''}">${t.acc}%</span>` : '<span class="dr-new">没练过</span>'}
        </div>
        ${t.desc ? `<p class="dr-desc">${esc(t.desc)}</p>` : ''}
        <div class="dr-meta">
          <span class="dr-eng ${t.eng}">${t.eng === 'prog' ? '程序出题' : 'AI 出题'}</span>
          ${t.eng === 'ai' && t.bank_all
            ? `<span class="dr-bank" title="AI 出的题要过第二个模型的独立核验才发给你做；答案不一致的不出">
                 ✓ ${t.bank_ok} 道已核验${t.bank_all > t.bank_ok ? `（筛掉 ${t.bank_all - t.bank_ok}）` : ''}</span>` : ''}
          ${done ? `做过 ${t.n} 题 · 平均 ${t.sec} 秒${t.sec > drLimit ? '（超时）' : ''}` : `限时 ${drLimit} 秒/题`}</div>
      </div>`;
    }).join('') + `<div class="dr-card dr-all" data-drt=""><div class="dr-card-h"><b>🎲 混合练</b></div>
      <p class="dr-desc">所有题型随机出，模拟真实考场</p><div class="dr-meta">限时 ${drLimit} 秒/题</div></div>`;
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
function drCoefTip() {
  const l = drLevels.find(x => x.k === drLevel) || {};
  // 「难度系数」在公考里就是**得分率**。必须说清它是什么，不然「0.40」看着像分数
  $('#dr-coef').innerHTML = `<b>难度系数 ${(l.coef || 0).toFixed(2)}</b>
    <span>= 这个难度下<b>预期能做对 ${Math.round((l.coef || 0) * 100)}%</b>。${esc(l.desc || '')}。
    做完会告诉你<b>比预期高还是低</b>，心里有数。</span>`;
}
$('#dr-levels').addEventListener('click', e => {
  const b = e.target.closest('[data-drl]'); if (!b) return;
  drLevel = b.dataset.drl;
  loadDrillTypes();
});
$('#dr-ns').addEventListener('click', e => {
  const b = e.target.closest('[data-drn]'); if (!b) return;
  drN = +b.dataset.drn;
  document.querySelectorAll('#dr-ns .chip').forEach(x => x.classList.toggle('active', x === b));
});
$('#dr-modes').addEventListener('click', e => {
  const b = e.target.closest('[data-drm]'); if (!b) return;
  drMode = b.dataset.drm;
  document.querySelectorAll('#dr-modes .chip').forEach(x => x.classList.toggle('active', x === b));
  drModeTip();
});
function drModeTip() {
  $('#dr-modetip').textContent = drMode === 'exam'
    ? '答案不提前下发，全部做完交卷、由服务端判分，更像考试'
    : '每题选完立刻判、马上给解析和秒杀技巧 —— 边做边学';
}
drModeTip();
$('#dr-types').addEventListener('click', e => {
  const c = e.target.closest('[data-drt]'); if (!c) return;
  drStart(c.dataset.drt);
});
$('#dr-recs').onclick = () => openDrillRecs();

async function drStart(type) {
  drType = type;
  toast('出题中…');
  try {
    const d = await api('/api/drill/quiz', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ board: drBoard, type, n: drN, level: drLevel, exam: drMode === 'exam' }),
    });
    drItems = d.items; drLimit = d.limit; drCoef = d.coef; drToken = d.token || '';
    drIdx = 0; drAns = []; drSec = [];
    push({ view: 'drillrun', title: (type || '混合') + ' · 专项练' });
    drRender();
  } catch (e) { toast(e.message, true); }
}

function drRender() {
  clearInterval(drTimer);
  if (drIdx >= drItems.length) { drResult(); return; }
  const it = drItems[drIdx];
  const isFig = !!(it.figs && it.figs.seq);
  const lvName = (drLevels.find(x => x.k === drLevel) || {}).name || '';
  $('#dr-head').innerHTML = `
    <div class="dr-prog">第 <b>${drIdx + 1}</b> / ${drItems.length} 题
      <span class="dr-tag">${esc(it.qtype || '')}</span>
      <span class="dr-tag lv">${esc(lvName)}</span></div>
    <div class="dr-clock" id="dr-clock">0 秒</div>`;
  const chosen = drAns[drIdx];
  const opts = isFig
    ? it.figs.opts.map((svg, j) => `<button class="dt-opt dt-figo${chosen === DT_L[j] ? ' chosen' : ''}"
        data-dro="${DT_L[j]}"><span class="dt-figl">${DT_L[j]}</span>${svg}</button>`).join('')
    : (it.options || []).map((o, j) => `<button class="dt-opt${chosen === DT_L[j] ? ' chosen' : ''}"
        data-dro="${DT_L[j]}">${esc(o)}</button>`).join('');
  const seq = isFig ? `<div class="dt-seq">${it.figs.seq.join('')}<span class="dt-qm">?</span></div>` : '';
  _dtLastMat = '';                                    // 每题独立渲染材料，别被上一题的缓存吃掉
  // 测试模式要能翻回去改（考场就是这样），所以给上下题按钮；背题模式选完即判，不用
  const nav = drMode === 'exam' ? `<div class="dr-nav">
      <button class="btn" id="dr-prev" ${drIdx ? '' : 'disabled'}>← 上一题</button>
      <button class="btn primary" id="dr-nextq">${drIdx + 1 >= drItems.length ? '交卷看结果' : '下一题 →'}</button>
    </div>` : '';
  $('#dr-body').innerHTML = `<div class="dt-q">${dtMaterial(it.material, drIdx)}
    <div class="dt-qt">${esc(it.q)}</div>${seq}
    <div class="dt-opts${isFig ? ' dt-figs' : ''}">${opts}</div>
    <div id="dr-exp"></div>${nav}</div>`;
  if (drMode === 'exam') {
    $('#dr-prev').onclick = () => { drStopTimer(); drIdx--; drRender(); };
    $('#dr-nextq').onclick = () => { drStopTimer(); drIdx++; drRender(); };
  }
  drT0 = Date.now();
  drTimer = setInterval(() => {
    const s = Math.round((Date.now() - drT0) / 1000 + (drSec[drIdx] || 0));
    const el = $('#dr-clock'); if (!el) { clearInterval(drTimer); return; }
    el.textContent = s + ' 秒';
    el.classList.toggle('over', s > drLimit);        // 超时只是提醒，不打断（考场上超时也得做完）
  }, 500);
}
function drStopTimer() {
  clearInterval(drTimer);
  drSec[drIdx] = (drSec[drIdx] || 0) + (Date.now() - drT0) / 1000;
}

$('#dr-body').addEventListener('click', e => {
  const b = e.target.closest('[data-dro]');
  if (b) { drPick(b.dataset.dro); return; }
  if (e.target.closest('#dr-next')) { drIdx++; drRender(); }
});

function drPick(letter) {
  const it = drItems[drIdx];
  if (drMode === 'exam') {          // 测试模式：只记选择，不判、不给解析（答案本来也没下发到前端）
    drAns[drIdx] = letter;
    document.querySelectorAll('#dr-body [data-dro]').forEach(b =>
      b.classList.toggle('chosen', b.dataset.dro === letter));
    return;
  }
  if (drAns[drIdx] !== undefined) return;             // 背题模式：答过就不能改
  drStopTimer();
  const sec = drSec[drIdx];
  drAns[drIdx] = letter;
  const ok = letter === it.answer;
  document.querySelectorAll('#dr-body [data-dro]').forEach(b => {
    b.disabled = true;
    if (b.dataset.dro === it.answer) b.classList.add('correct');
    else if (b.dataset.dro === letter) b.classList.add('wrong');
  });
  const over = sec > drLimit;
  const bold = (t) => esc(t || '').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  $('#dr-exp').innerHTML = `
    <div class="dr-verdict ${ok ? 'ok' : 'no'}">${ok ? '✅ 对了' : '❌ 错了'}
      · 用时 <b class="${over ? 'over' : ''}">${sec.toFixed(0)} 秒</b>${over ? `（限时 ${drLimit} 秒，慢了）` : ''}
      · 正确答案 <b>${esc(it.answer)}</b></div>
    <div class="dt-exp">${bold(it.explain)}</div>
    ${it.tip ? `<div class="dr-tip">⚡ <b>秒杀技巧</b>：${bold(it.tip)}</div>` : ''}
    <button class="btn primary" id="dr-next">${drIdx + 1 >= drItems.length ? '看结果' : '下一题 →'}</button>`;
}

async function drResult() {
  drStopTimer();
  $('#dr-head').innerHTML = '';
  $('#dr-body').innerHTML = '<p class="empty">判分中…</p>';
  const answers = {}, seconds = {};
  drItems.forEach((_, i) => { answers[i] = drAns[i] || ''; seconds[i] = drSec[i] || 0; });
  const body = { board: drBoard, type: drType, level: drLevel, exam: drMode === 'exam', answers, seconds };
  if (drToken) body.token = drToken;      // 测试模式：题在服务端，前端手里根本没有答案
  else body.items = drItems;
  try {
    const r = await api('/api/drill/done', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const avg = drSec.reduce((a, b) => a + b, 0) / (drSec.length || 1);
    const slow = drSec.filter(s => s > drLimit).length;
    const pct = Math.round(r.acc * 100), exp = Math.round(r.coef * 100);
    const good = r.vs >= 0;
    $('#dr-body').innerHTML = `
      <div class="dr-done">
        <div class="dr-score">${r.ok} / ${r.total}</div>
        <div class="dr-vs ${good ? 'good' : 'bad'}">
          正确率 <b>${pct}%</b> · 这个难度预期 ${exp}%
          → <b>${good ? '高出' : '低了'} ${Math.abs(Math.round(r.vs * 100))} 个点</b>
        </div>
        <div class="dr-sub">平均用时 <b class="${avg > drLimit ? 'over' : ''}">${avg.toFixed(0)} 秒</b>
          ${slow ? `· 有 ${slow} 题超时（限时 ${drLimit} 秒）` : `· 都在 ${drLimit} 秒内 👍`}</div>
        ${r.wrong_added ? `<p class="dr-wq">错的 ${r.wrong_added} 题已自动进错题本</p>` : ''}
        <div class="dr-acts">
          <button class="btn primary" id="dr-again">🔄 再来 ${drN} 题</button>
          <button class="btn" id="dr-see">📋 看每题详情</button>
          <button class="btn" id="dr-back">换个题型</button>
        </div>
      </div>`;
    $('#dr-again').onclick = () => drStart(drType);
    $('#dr-see').onclick = () => openDrillRec(r.rid);
    $('#dr-back').onclick = () => { back(); loadDrillTypes(); };
  } catch (e) { $('#dr-body').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

/* ---- 做题记录：做过的都留着，可以回看每一题（不是做完就丢） ---- */
async function openDrillRecs() {
  push({ view: 'drillrec', title: '做题记录' });
  const box = $('#drr-list');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/drill/records');
    box.innerHTML = d.items.length ? d.items.map(x => {
      const acc = Math.round(100 * x.correct / (x.total || 1));
      const good = acc >= Math.round(x.coef * 100);      // 和这个难度的预期得分率比
      return `<div class="wr-day done" data-drrec="${x.id}">
        <div class="wr-day-d">${esc(x.board)}</div>
        <div class="wr-day-m">
          <b>${esc(x.qtype || '混合')}</b>
          <span class="wr-tag">${esc(x.level_name)}</span>
          <span class="wr-tag">${x.mode === 'exam' ? '测试' : '背题'}</span>
          <span class="dr-acc${good ? '' : ' bad'}">${x.correct}/${x.total} · ${acc}%</span>
          <span class="wr-w">${Math.round(x.seconds)} 秒 · ${esc((x.created_at || '').slice(5, 16))}</span>
        </div>
      </div>`;
    }).join('') : '<p class="empty">还没做过题。</p>';
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#drr-list').addEventListener('click', e => {
  const c = e.target.closest('[data-drrec]'); if (c) openDrillRec(+c.dataset.drrec);
});
async function openDrillRec(rid) {
  push({ view: 'drillrecd', title: '这次做的题' });
  $('#drd-head').innerHTML = '<p class="empty">加载中…</p>';
  $('#drd-body').innerHTML = '';
  try {
    const d = await api('/api/drill/record/' + rid);
    const acc = Math.round(100 * d.correct / (d.total || 1));
    $('#drd-head').innerHTML = `<div class="dr-prog">${esc(d.board)} · ${esc(d.qtype || '混合')}
      <span class="dr-tag lv">${esc(d.level)}</span></div>
      <div class="dr-clock">${d.correct}/${d.total} · ${acc}%</div>`;
    _dtLastMat = '';
    $('#drd-body').innerHTML = d.items.map((it, i) => {
      const r = d.answers[i] || {};
      const isFig = !!(it.figs && it.figs.seq);
      const cls = (L) => (L === it.answer ? ' correct' : (L === r.your ? ' wrong' : ''));
      const opts = isFig
        ? it.figs.opts.map((svg, j) => `<button class="dt-opt dt-figo${cls(DT_L[j])}" disabled>
            <span class="dt-figl">${DT_L[j]}</span>${svg}</button>`).join('')
        : (it.options || []).map((o, j) => `<button class="dt-opt${cls(DT_L[j])}" disabled>${esc(o)}</button>`).join('');
      return `<div class="dt-q">${dtMaterial(it.material, i)}
        <div class="dt-qt">${r.correct ? '✅' : '❌'} ${i + 1}. ${esc(it.q)}</div>
        ${isFig ? `<div class="dt-seq">${it.figs.seq.join('')}<span class="dt-qm">?</span></div>` : ''}
        <div class="dt-opts${isFig ? ' dt-figs' : ''}">${opts}</div>
        <div class="dt-exp"><b>正确答案 ${esc(it.answer)}</b>${r.your ? ` · 你选了 ${esc(r.your)}` : ' · 没作答'}
          ${it.explain ? ' · ' + esc(it.explain) : ''}</div>
      </div>`;
    }).join('');
  } catch (e) { $('#drd-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

/* ============= 成文：把素材真正写成一篇大作文 ============= */
let wrTab = 'daily', wrCur = null, wrPoll = 0;

function openWrite(tab) {
  const app = tab === 'yingyong';           // 从「应用文 → 应用文成文」进来
  push({ view: 'write', title: app ? '应用文成文' : '议论文成文' });
  // 议论文成文放「每日成文 / 综合应用」；应用文成文放「文种大全 / 自选成文」——各两个导航栏
  const show = app ? ['yycat', 'yywrite'] : ['daily', 'compose'];
  document.querySelectorAll('#wr-tabs .tk-tab').forEach(b => b.classList.toggle('hidden', !show.includes(b.dataset.wk)));
  wrTab = show.includes(tab) ? tab : show[0];
  wrSwitch(wrTab);            // render() 只负责显隐视图，内容要自己拉
}
function wrSwitch(k) {
  wrTab = k;
  document.querySelectorAll('#wr-tabs .tk-tab').forEach(b => b.classList.toggle('active', b.dataset.wk === k));
  ['daily', 'compose', 'yycat', 'yywrite'].forEach(x => $('#wr-' + x).classList.toggle('hidden', x !== k));
  if (k === 'daily') loadWrDays();
  else if (k === 'compose') loadWrCompose();
  else if (k === 'yycat') loadYyCats();
  else if (k === 'yywrite') loadWrGw();
}
// tab 点击切换（这个 handler 连同下面几个 load 函数在做应用文那次被误删了 → 每日成文/综合应用点了没反应、空白）
$('#wr-tabs').addEventListener('click', e => {
  const b = e.target.closest('.tk-tab'); if (b) wrSwitch(b.dataset.wk);
});
async function loadWrDays() {
  const box = $('#wr-days');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/write/days');
    const undone = d.days.filter(x => !x.eid).length;
    $('#wr-backfill').classList.toggle('hidden', !undone);
    $('#wr-backfill').textContent = `⚡ 一键补齐往期（还差 ${undone} 天）`;
    if (!d.days.length) { box.innerHTML = '<p class="empty">还没有素材，每天 08:00 自动更新～</p>'; return; }
    box.innerHTML = d.days.map(x => x.eid ? `
      <div class="wr-day done" data-weid="${x.eid}">
        <div class="wr-day-d">🗓 ${fmtDay(x.date)}</div>
        <div class="wr-day-m"><b>${esc(x.title || '')}</b>
          <span class="wr-tag">${esc(x.topic || '')}</span>
          <span class="wr-w">${x.words} 字</span></div>
      </div>` : `
      <div class="wr-day">
        <div class="wr-day-d">🗓 ${fmtDay(x.date)}</div>
        <div class="wr-day-m"><span class="wr-n">素材 ${x.n} 条（衔接 ${x.nl}）</span></div>
        <button class="btn tiny primary" data-wgen="${x.date}">✍️ 写</button>
      </div>`).join('');
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

$('#wr-days').addEventListener('click', async e => {
  const g = e.target.closest('[data-wgen]');
  if (g) {
    g.disabled = true; g.textContent = '写作中…';
    try {
      const d = await api('/api/write/daily', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: g.dataset.wgen }),
      });
      openWrited(d.id);
      loadWrDays();
    } catch (err) { toast(err.message, true); g.disabled = false; g.textContent = '✍️ 写'; }
    return;
  }
  const c = e.target.closest('[data-weid]');
  if (c) openWrited(+c.dataset.weid);
});

$('#wr-backfill').onclick = async () => {
  if (!await appConfirm('把往期素材一天一篇全部补齐？每篇要调一次 AI，会在后台慢慢跑，可以先去干别的。')) return;
  try {
    const d = await api('/api/write/backfill', { method: 'POST' });
    wrWatch(d.task);
  } catch (e) { toast(e.message, true); }
};

function wrWatch(tid) {
  clearInterval(wrPoll);
  $('#wr-backfill').disabled = true;
  const msg = $('#wr-bfmsg');
  wrPoll = setInterval(async () => {
    try {
      const t = await api('/api/write/task/' + tid);
      msg.textContent = `${t.message || ''}（${t.progress}/${t.total}）`;
      if (t.status === 'done' || t.status === 'error') {
        clearInterval(wrPoll); wrPoll = 0;
        $('#wr-backfill').disabled = false;
        msg.textContent = t.message || '';
        loadWrDays();
        toast(t.status === 'done' ? '补齐完成' : t.message, t.status !== 'done');
      }
    } catch (_) { clearInterval(wrPoll); wrPoll = 0; $('#wr-backfill').disabled = false; }
  }, 3000);
}

async function loadWrCompose() {
  const box = $('#wr-cplist');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/write/list?mode=compose');
    const today = new Date().toISOString().slice(0, 10);
    $('#wr-gen-cp').textContent = d.items.some(x => x.date === today)
      ? '🔄 今天这篇重写一遍' : '✍️ 写今天这篇';
    box.innerHTML = d.items.length ? d.items.map(x => `
      <div class="wr-day done" data-weid="${x.id}">
        <div class="wr-day-d">🗓 ${fmtDay(x.date)}</div>
        <div class="wr-day-m"><b>${esc(x.title || '')}</b>
          <span class="wr-tag">${esc(x.topic || '')}</span>
          <span class="wr-w">${x.words} 字</span></div>
      </div>`).join('') : '<p class="empty">还没写过。点上面的按钮，AI 会自己选题写一篇。</p>';
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#wr-cplist').addEventListener('click', e => {
  const c = e.target.closest('[data-weid]'); if (c) openWrited(+c.dataset.weid);
});
$('#wr-gen-cp').onclick = async () => {
  const b = $('#wr-gen-cp'); b.disabled = true; b.textContent = 'AI 选题写作中…（约 20 秒）';
  try {
    const d = await api('/api/write/compose', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true }),
    });
    openWrited(d.id); loadWrCompose();
  } catch (e) { toast(e.message, true); }
  b.disabled = false;
};


/* ---- 应用文：按「类别 → 文种」铺开，每个文种给「提纲 + 范文」两样 ----
   提纲**不是文种**，是一种呈现方式（框架式、要点式），任何文种都能套。
   先看提纲（这个文种由哪几块组成）再看范文（成品长什么样），才知道文章是怎么长出来的。
   第一次一键把所有文种各铺一份；之后就是针对同一文种换话题积累。 */
let gwSpec = null, gwType = '讲话稿', gwForm = 'full', yyPoll = 0;

async function loadWrGw() {
  if (!gwSpec) {
    try { gwSpec = await api('/api/write/gwspec'); } catch (e) { toast(e.message, true); return; }
  }
  $('#yy-types').innerHTML = gwSpec.doctypes.map(d =>
    `<button class="chip${d.k === gwType ? ' active' : ''}" data-gwt="${esc(d.k)}">${esc(d.k)}</button>`).join('');
  $('#yy-scenes').innerHTML = '<span class="gw-sug-t">常用：</span>' + gwSpec.scenes.map(s =>
    `<button class="chip tiny" data-gws="${esc(s)}">${esc(s)}</button>`).join('');
  gwFmt();
  // 文种大全（yy-cats）现在是独立的一个导航栏，各自加载，这里不再连带拉它
}
function gwFmt() {
  const d = gwSpec.doctypes.find(x => x.k === gwType); if (!d) return;
  $('#yy-fmt').innerHTML = `<b>${esc(d.k)}</b>：${esc(d.d)}<br>
    <span class="gw-fmt-k">格式骨架</span>${esc(d.fmt)} · ${d.min}~${d.max} 字`;
}

async function loadYyCats() {
  const box = $('#yy-cats');
  box.innerHTML = box.innerHTML || '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/write/yylist');
    const miss = d.total * 2 - d.have_full - d.have_outline;
    const bt = $('#yy-batch');
    bt.classList.toggle('hidden', miss <= 0);
    bt.textContent = `⚡ 一键铺开所有文种（还差 ${miss} 篇）`;
    box.innerHTML = d.cats.map(c => `
      <div class="yy-cat">
        <div class="yy-cat-t">${esc(c.cat)}</div>
        ${c.doctypes.map(t => `
          <div class="yy-dt">
            <div class="yy-dt-h">
              <b>${esc(t.k)}</b><span class="yy-dt-d">${esc(t.d)}</span>
            </div>
            <div class="yy-dt-b">
              ${t.outline.length
                ? `<button class="yy-pill out" data-weid="${t.outline[0].id}">🧭 提纲</button>`
                : '<span class="yy-pill none">🧭 提纲 · 还没有</span>'}
              ${t.full.length
                ? t.full.map(f => `<button class="yy-pill" data-weid="${f.id}"
                    title="${esc(f.title || '')}">📄 ${esc(f.scene || f.title || '范文')}</button>`).join('')
                : '<span class="yy-pill none">📄 范文 · 还没有</span>'}
            </div>
          </div>`).join('')}
      </div>`).join('');
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

$('#yy-batch').onclick = async () => {
  if (!await appConfirm('给每个文种各写一份提纲和一篇范文（先提纲后范文）。要调不少次 AI，会在后台慢慢跑，可以先去干别的。')) return;
  try {
    const d = await api('/api/write/yingyong/batch', { method: 'POST' });
    yyWatch(d.task);
  } catch (e) { toast(e.message, true); }
};
function yyWatch(tid) {
  clearInterval(yyPoll);
  $('#yy-batch').disabled = true;
  const msg = $('#yy-bfmsg');
  yyPoll = setInterval(async () => {
    try {
      const t = await api('/api/write/task/' + tid);
      msg.textContent = `${t.message || ''}（${t.progress}/${t.total}）`;
      if (t.status === 'done' || t.status === 'error') {
        clearInterval(yyPoll); yyPoll = 0;
        $('#yy-batch').disabled = false;
        msg.textContent = t.message || '';
        loadYyCats();
        toast(t.status === 'done' ? '铺开完成' : t.message, t.status !== 'done');
      }
    } catch (_) { clearInterval(yyPoll); yyPoll = 0; $('#yy-batch').disabled = false; }
  }, 3000);
}

function yyPaneClick(e) {
  const t = e.target.closest('[data-gwt]');
  if (t) { gwType = t.dataset.gwt; loadWrGw(); return; }
  const f = e.target.closest('[data-yyf]');
  if (f) {
    gwForm = f.dataset.yyf;
    document.querySelectorAll('#yy-forms .chip').forEach(x => x.classList.toggle('active', x === f));
    return;
  }
  const s = e.target.closest('[data-gws]');
  if (s) { $('#yy-scene').value = s.dataset.gws; return; }
  const c = e.target.closest('[data-weid]');
  if (c) openWrited(+c.dataset.weid);
}
$('#wr-yycat').addEventListener('click', yyPaneClick);       // 文种大全：点提纲/范文打开
$('#wr-yywrite').addEventListener('click', yyPaneClick);     // 自选成文：文种/表单/生成
$('#yy-go').onclick = async () => {
  const scene = $('#yy-scene').value.trim();
  if (!scene) { toast('先说清楚就什么事发文', true); return; }
  const b = $('#yy-go'); b.disabled = true; b.textContent = '写作中…';
  try {
    const d = await api('/api/write/yingyong', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        doctype: gwType, scene, form: gwForm,
        role: $('#yy-role').value.trim(), audience: $('#yy-aud').value.trim(),
      }),
    });
    openWrited(d.id); loadYyCats();
  } catch (e) { toast(e.message, true); }
  b.disabled = false; b.textContent = '✍️ 写这一篇';
};

/* ---- 成文详情 ---- */
async function openWrited(id) {
  wrCur = null;
  push({ view: 'writed', title: '成文' });
  $('#wd-head').innerHTML = '<p class="empty">加载中…</p>';
  try {
    wrCur = await api('/api/write/' + id);
    renderWrited();
  } catch (e) { $('#wd-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
function renderWrited() {
  const d = wrCur; if (!d) return;
  const gw = d.mode === 'yingyong';           // 应用文：字数按文种走，提纲页签换成「格式批注」
  const sp = d.spec || {};
  const isOut = gw && sp.form === 'outline'; // 提纲：框架式要点式，字数本来就少，不卡字数
  const ok = isOut ? true : (gw ? d.words >= 250 : (d.words >= 1000 && d.words <= 1300));
  document.querySelector('#wd-tabs [data-wd=text]').textContent = isOut ? '🧭 提纲' : '📄 全文';
  document.querySelector('#wd-tabs [data-wd=outline]').textContent =
    isOut ? '📐 每块怎么写' : (gw ? '📐 格式批注' : '🧭 提纲');
  document.querySelector('#wd-tabs [data-wd=used]').textContent = gw ? '📎 用到的规范表述' : '📎 用到的素材';
  $('#wd-head').innerHTML = `
    <h2 class="wd-title">${esc(d.title || '')}</h2>
    <div class="wd-meta">
      <span class="wr-tag">${esc(d.topic || '')}</span>
      <span class="wd-w ${ok ? '' : 'bad'}">${d.words} 字${ok ? '' : '（字数不达标）'}</span>
      <span class="wd-src">${gw
        ? (isOut ? '🧭 提纲纲要' : '📄 范文') + ' · ' + esc(sp.scene || '')
          + (sp.role ? ' · ' + esc(sp.role) : '')
        : (d.mode === 'daily' ? '📅 ' + fmtDay(d.date) + ' 的素材' : '🧩 综合应用')}</span>
      <span class="wd-used-n">📎 ${(d.used || []).length} 条${gw ? '规范表述' : '素材'}</span>
    </div>
    ${d.note ? `<p class="wd-note">💡 ${esc(d.note)}</p>` : ''}`;
  $('#wd-text').innerHTML = isOut
    ? `<pre class="wd-outline">${esc(d.content || '')}</pre>`   // 提纲有缩进和「· 」，原样保留
    : (d.content || '').split('\n').filter(x => x.trim())
        .map(p => `<p>${esc(p.trim())}</p>`).join('');
  const groups = {};
  (d.used || []).forEach(u => { (groups[u.sec] = groups[u.sec] || []).push(u.text); });
  $('#wd-used').innerHTML = Object.keys(groups).length ? Object.entries(groups).map(([k, v]) => `
    <div class="wd-ug"><div class="wd-ug-t">${esc(k)}</div>
      ${v.map(t => `<div class="wd-ui">${esc(t)}</div>`).join('')}</div>`).join('')
    : `<p class="empty">这篇没能核对出用了哪些${gw ? '规范表述' : '素材'}。</p>`;
  if (gw) {
    // 应用文的重点全在这儿：每段是哪个部件、为什么这么写。看完才知道怎么学。
    $('#wd-outline').innerHTML = (d.outline || []).length
      ? d.outline.map(s => `<div class="gw-seg">
          <div class="gw-seg-p">${esc(s.part || '')}</div>
          <div class="gw-seg-t">${esc(s.text || '')}</div>
          <div class="gw-seg-w">💡 ${esc(s.why || '')}</div>
        </div>`).join('')
      : '<p class="empty">没有批注。</p>';
  } else {
    $('#wd-outline').innerHTML = (d.outline || []).length
      ? `<ol class="wd-ol">${d.outline.map(x => `<li>${esc(x)}</li>`).join('')}</ol>`
      : '<p class="empty">没有提纲。</p>';
  }
}
$('#wd-tabs').addEventListener('click', e => {
  const b = e.target.closest('.tk-tab'); if (!b) return;
  document.querySelectorAll('#wd-tabs .tk-tab').forEach(x => x.classList.toggle('active', x === b));
  ['text', 'used', 'outline'].forEach(k => $('#wd-' + k).classList.toggle('hidden', k !== b.dataset.wd));
});

/* ============= 议论文 · 素材积累 / 衔接表达（与微信 08:00 推送同源） ============= */
let scKind = '全部';
const SC_COLOR = { '人物事例': '#b23b2e', '具体事例': '#0f766e', '理论论据': '#7a5cc0', '衔接表达': '#c2671f' };
async function loadSucai() {
  document.querySelectorAll('#sc-kinds .chip').forEach(x => x.classList.toggle('active', x.dataset.sk === scKind));
  $('#sc-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/sucai?kind=' + encodeURIComponent(scKind));
    document.querySelectorAll('#sc-kinds .chip').forEach(x => {
      if (x.dataset.sk === '全部') return;
      const n = d.counts[x.dataset.sk]; x.textContent = x.dataset.sk + (n ? ' ' + n : '');
    });
    if (!d.items.length) { $('#sc-list').innerHTML = '<p class="empty">还没有素材，每天 08:00 自动生成～</p>'; return; }
    let lastDate = '';
    $('#sc-list').innerHTML = d.items.map(it => {
      const head = it.date !== lastDate ? `<div class="sc-day">🗓 ${fmtDay(it.date)}</div>` : '';
      lastDate = it.date;
      const col = SC_COLOR[it.kind] || '#666';
      const isLj = it.kind === '衔接表达';
      const exHtml = it.example
        ? `<div class="sc-exwrap"><div class="sc-ex"><b>例句</b> ${esc(it.example)}</div>
             <button class="sc-exbtn regen" data-scex="${it.id}" data-force="1">🔄 换个例句</button></div>`
        : (isLj ? `<button class="sc-exbtn" data-scex="${it.id}">✍️ AI 造个例句</button>` : '');
      return head + `<div class="gk-card" data-scid="${it.id}">
        <div class="gk-head"><span class="poly-badge" style="background:${col}">${esc(it.kind)}</span>
          ${it.topic ? `<span class="gk-topic">${esc(it.topic)}</span>` : ''}</div>
        <div class="sc-body">${emKey(it.content)}</div>
        ${exHtml}
      </div>`;
    }).join('');
  } catch (e) { $('#sc-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#sc-list').addEventListener('click', async e => {
  const b = e.target.closest('[data-scex]'); if (!b) return;
  const force = b.dataset.force === '1';
  const label = b.textContent;
  b.disabled = true; b.textContent = force ? '换句中…' : 'AI 造句中…';
  try {
    const d = await api('/api/sucai/' + b.dataset.scex + '/example', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force })
    });
    if (force) {                    // 原地替换例句文本，按钮留着可再换
      const ex = b.parentElement.querySelector('.sc-ex');
      if (ex) ex.innerHTML = `<b>例句</b> ${esc(d.example)}`;
      b.disabled = false; b.textContent = label;
    } else {
      b.outerHTML = `<div class="sc-exwrap"><div class="sc-ex"><b>例句</b> ${esc(d.example)}</div>
        <button class="sc-exbtn regen" data-scex="${b.dataset.scex}" data-force="1">🔄 换个例句</button></div>`;
    }
  } catch (err) { toast(err.message, true); b.disabled = false; b.textContent = label; }
});
function openSucai(kind) {
  scKind = kind || '全部';
  push({ view: 'sucai', title: scKind === '衔接表达' ? '衔接表达' : '素材积累' });
  loadSucai();
}
$('#sc-kinds').addEventListener('click', e => {
  const c = e.target.closest('[data-sk]'); if (!c) return;
  scKind = c.dataset.sk; loadSucai();
});

/* ============= 任务清单（每日任务 + 互监待办） ============= */
function openTasks() { push({ view: 'tasks', title: '任务清单' }); tkSwitch('plan'); }
function tkSwitch(t) {
  // 必须限定在本视图内：.tk-tab 这个类名被范文/批改/复习那几组页签复用，
  // 全局 querySelectorAll 会把它们的高亮一起清掉
  document.querySelectorAll('#view-tasks .tk-tab').forEach(x => x.classList.toggle('active', x.dataset.tkt === t));
  ['plan', 'daily', 'shared'].forEach(k => $('#tk-' + k).classList.toggle('hidden', k !== t));
  if (t === 'plan') loadPlan(); else if (t === 'daily') loadDaily(); else loadShared();
}
$('#view-tasks').addEventListener('click', e => {
  const tab = e.target.closest('[data-tkt]'); if (tab) tkSwitch(tab.dataset.tkt);
});

/* ================= 备考规划：AI 按真实学情排当天计划 ================= */
const PL_MOD_COLOR = {
  '复习': '#12b886', '错题': '#c0392b', '申论': '#c92a2a', '常识判断': '#e8590c',
  '言语理解': '#2b6fd6', '数量关系': '#7a5cc0', '资料分析': '#0b7285', '判断推理': '#5b6cf0',
  '政治理论': '#b7791f',
};
let plProfile = null, plEditing = false;

/* ---------- 40 天冲刺路线：今天第几天、什么阶段、今日定额、正确率目标 ---------- */
let plRoadOpen = false;
function renderRoadmap(rm, prof) {
  const box = $('#pl-road');
  if (!rm || (!rm.phase && !rm.over)) {           // 没开启（或还没到开始日）
    box.innerHTML = `<div class="plr-off">
      <div class="plr-off-t">🚀 40 天冲刺路线</div>
      <div class="plr-off-d">对标「140 分」强度，但按 <b>6 天推进 + 第 7 天复盘日</b> 排，能扛完全程。
        分三段：打牢根基(1-12) → 专项拔高(13-28) → 套题强化(29-40)；
        每天给你行测题量定额、申论安排、正确率目标，积累类任务直接用 App 里现成的内容。</div>
      <button class="btn primary" id="plr-start">开启 40 天冲刺</button>
    </div>`;
    return;
  }
  if (rm.over) {
    box.innerHTML = `<div class="plr-off">
      <div class="plr-off-t">🏁 40 天冲刺已走完（第 ${rm.day} 天）</div>
      <div class="plr-off-d">${esc(rm.data.after || '')}</div>
      <button class="btn primary" id="plr-start">再开一轮</button>
    </div>`;
    return;
  }
  const ph = rm.phase, dd = rm.data;
  const pct = Math.round(rm.day / rm.days * 100);
  const quota = Object.entries(ph.quota).map(([k, v]) =>
    `<span class="plr-q"><b>${v}</b> ${esc(k)}</span>`).join('');
  const acc = Object.entries(ph.accuracy).map(([k, v]) =>
    `<tr><td>${esc(k)}</td><td><b>${esc(v)}</b></td></tr>`).join('');
  box.innerHTML = `
    <div class="plr-top">
      <span class="plr-day">第 <b>${rm.day}</b> / ${rm.days} 天</span>
      <span class="plr-ph">${esc(ph.key)} · ${esc(ph.name)}</span>
      ${rm.review_day ? '<span class="plr-rv">★ 今天是复盘日</span>' : ''}
      <button class="plr-more" id="plr-more">${plRoadOpen ? '收起' : '看路线'}</button>
    </div>
    <div class="plr-bar"><i style="width:${pct}%"></i></div>
    <div class="plr-focus">${esc(ph.focus)}</div>
    ${rm.review_day ? `<div class="plr-tip">上午一套行测限时套题（严格 120 分钟）→ 下午全套订正 + 错因归因 → 晚上错题过筛，然后<b>休半天</b>。今天别堆新知识。</div>` : ''}
    <div class="plr-quota"><span class="plr-qt">今日行测定额</span>${quota}</div>
    <div class="plr-sl">📝 申论：${esc(ph.shenlun)}</div>
    <div class="plr-detail ${plRoadOpen ? '' : 'hidden'}">
      <div class="plr-sec">🎯 本阶段正确率目标</div>
      <table class="plr-tb">${acc}</table>
      <div class="plr-sec">📌 模块优先级</div>
      <div class="plr-p">${esc(dd.priority || '')}<div class="plr-why">${esc(dd.priority_why || '')}</div></div>
      <div class="plr-sec">🔁 本阶段每周要做到</div>
      <ul class="plr-ul">${(ph.weekly || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
      <div class="plr-sec">📚 每日固定动作（用 App 现成内容）</div>
      <ul class="plr-ul">${(dd.fixed || []).map(x =>
        `<li>${esc(x.t)}${x.link ? ` <i class="pl-go" data-plgo="${esc(x.link)}">去做 ›</i>` : ''}
          <span class="plr-note">${esc(x.note || '')}</span></li>`).join('')}</ul>
      <div class="plr-sec">⏰ 节奏</div>
      <div class="plr-p">${esc(dd.rhythm || '')}</div>
      <div class="plr-sec">🧱 纪律（原贴的 140 分强度，挑能长期执行的）</div>
      <ul class="plr-ul">${(dd.discipline || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
      <div class="plr-sec">🏁 阶段产出</div>
      <div class="plr-p">${esc(ph.output || '')}</div>
      <div class="plr-sec">➡️ 40 天之后</div>
      <div class="plr-p">${esc(dd.after || '')}</div>
      <button class="btn tiny plr-stop" id="plr-stop">结束这轮冲刺</button>
    </div>`;
  if (prof && prof.minutes < 300) {
    box.insertAdjacentHTML('beforeend',
      `<div class="plr-warn">你的「每天可学」只填了 ${prof.minutes} 分钟，这套定额是按 6~8 小时排的。
        建议去「⚙️ 备考信息」改成 <b>420</b> 分钟左右，规划助手才会把任务排够。</div>`);
  }
}
$('#pl-road').addEventListener('click', async e => {
  if (e.target.closest('#plr-more')) { plRoadOpen = !plRoadOpen; loadPlan(); return; }
  const go = e.target.closest('[data-plgo]');
  if (go) { ntfGo(go.dataset.plgo); return; }
  if (e.target.closest('#plr-start')) {
    const mins = (plProfile && plProfile.minutes) || 0;
    const ok = await appConfirm(
      '开启 40 天冲刺：从今天算第 1 天，分三段（根基 12 天 → 专项 16 天 → 套题 12 天），'
      + '每 7 天有一个复盘日。规划助手以后会按当天的定额和正确率目标排任务。'
      + (mins < 300 ? '\n\n你说全天有 6~8 小时，我顺便把「每天可学」设成 420 分钟，可以吗？' : ''),
      { title: '40 天冲刺路线', okText: '开始' });
    if (!ok) return;
    try {
      await api('/api/plan/roadmap', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mins < 300 ? { minutes: 420 } : {}),
      });
      toast('40 天冲刺已开启，去让规划助手排今天的计划');
      loadPlan();
    } catch (er) { toast(er.message, true); }
    return;
  }
  if (e.target.closest('#plr-stop')) {
    if (!await appConfirm('结束这轮 40 天冲刺？已排的计划不会删，只是规划助手不再按路线图排任务。',
      { title: '结束冲刺', okText: '结束' })) return;
    try { await api('/api/plan/roadmap', { method: 'DELETE' }); toast('已结束'); loadPlan(); }
    catch (er) { toast(er.message, true); }
  }
});

async function loadPlan() {
  try {
    const d = await api('/api/plan/today');
    plProfile = d.profile;
    const has = !!plProfile;
    if (has) renderPlan(d);
    if (plEditing) return;          // 用户正在改备考信息，别把设置页收起来
    $('#pl-setup').classList.toggle('hidden', has);
    $('#pl-main').classList.toggle('hidden', !has);
    if (!has) await fillPlanExams();
  } catch (e) { toast(e.message, true); }
}
async function fillPlanExams() {
  try {
    const d = await api('/api/plan/profile');
    $('#pl-exam').innerHTML = d.exams.map(x => `<option>${esc(x)}</option>`).join('');
    if (d.profile) {
      $('#pl-exam').value = d.profile.exam || '';
      $('#pl-date').value = d.profile.exam_date || '';
      $('#pl-min').value = d.profile.minutes || 120;
      $('#pl-weak').value = d.profile.weak || '';
      $('#pl-note').value = d.profile.note || '';
    }
  } catch (_) {}
}
function renderPlan(d) {
  const p = d.profile;
  const st = d.study || { streak: 0, total: 0 };
  $('#pl-head').innerHTML = `<div class="pl-days">${esc(p.exam || '备考规划')}</div>
    <div class="pl-meta">今天可学 ${p.minutes} 分钟${p.weak ? ' · 薄弱：' + esc(p.weak) : ''}</div>
    <div class="pl-streak">🔥 连续学习 <b>${st.streak}</b> 天 · 累计 <b>${st.total}</b> 天</div>`;
  renderRoadmap(d.roadmap, p);

  if (d.summary) {
    $('#pl-summary').innerHTML = `💡 ${esc(d.summary)}`;
    $('#pl-summary').classList.remove('hidden');
  } else $('#pl-summary').classList.add('hidden');

  $('#pl-prog').textContent = d.total
    ? `今日进度 ${d.done_n} / ${d.total} · ${d.minutes_done} / ${d.minutes_total} 分钟${d.done_n === d.total ? ' 🎉 全部完成！' : ''}`
    : '';

  $('#pl-list').innerHTML = d.items.length ? d.items.map(it => {
    const col = PL_MOD_COLOR[it.module] || '#6b7280';
    return `<div class="tk-item pl-item ${it.done ? 'done' : ''}" data-pl="${it.id}">
      <span class="tk-check">${it.done ? '✓' : ''}</span>
      <span class="tk-text">
        <span class="pl-title">${esc(it.title)}</span>
        <span class="pl-tags">
          ${it.module ? `<i class="pl-mod" style="background:${col}">${esc(it.module)}</i>` : ''}
          <i class="pl-min">${it.minutes} 分钟</i>
          ${it.link ? `<i class="pl-go" data-plgo="${esc(it.link)}">去做 ›</i>` : ''}
        </span>
        ${it.reason ? `<span class="tk-who">${esc(it.reason)}</span>` : ''}
      </span>
      <button class="tk-del" data-pldel="${it.id}">🗑</button>
    </div>`;
  }).join('') : '<p class="empty">今天还没有计划。点下面的按钮，规划助手会看着你的复习进度和错题给你排一份。</p>';
}
// 备考信息：记下打开时的原值，用来判断"有没有改过" + 撤回
let plFormBase = null;
function plReadForm() {
  return {
    exam: $('#pl-exam').value, exam_date: $('#pl-date').value,
    minutes: +$('#pl-min').value || 120,
    weak: $('#pl-weak').value.trim(), note: $('#pl-note').value.trim(),
  };
}
function plWriteForm(v) {
  if (!v) return;
  $('#pl-exam').value = v.exam || ''; $('#pl-date').value = v.exam_date || '';
  $('#pl-min').value = v.minutes || 120; $('#pl-weak').value = v.weak || ''; $('#pl-note').value = v.note || '';
  plSyncUndo();
}
function plDirty() { return plFormBase && JSON.stringify(plReadForm()) !== JSON.stringify(plFormBase); }
function plSyncUndo() { const u = $('#pl-undo'); if (u) u.hidden = !plDirty(); }
['pl-exam', 'pl-date', 'pl-min', 'pl-weak', 'pl-note'].forEach(id =>
  $('#' + id).addEventListener('input', plSyncUndo));

async function plSave() {
  try {
    await api('/api/plan/profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(plReadForm()) });
    plEditing = false; plFormBase = null;
    toast('已保存');
    return true;
  } catch (e) { toast(e.message, true); return false; }
}
$('#pl-save').onclick = async () => { if (await plSave()) loadPlan(); };
$('#pl-edit').onclick = async () => {
  plEditing = true;
  await fillPlanExams();
  plFormBase = plReadForm();      // 记下原值
  $('#pl-back').hidden = !plProfile;   // 已有档案才有"上一页"可回
  $('#pl-undo').hidden = true;
  $('#pl-setup').classList.remove('hidden');
  $('#pl-main').classList.add('hidden');
};
$('#pl-undo').onclick = () => { plWriteForm(plFormBase); toast('已撤回修改'); };
// 返回：改过就问，保存 / 不保存 / 继续编辑
async function plLeaveSetup() {
  if (!plProfile) return;   // 首次填写没有"上一页"
  if (plDirty()) {
    const r = await appConfirm('备考信息有未保存的修改，怎么处理？',
      { title: '未保存的修改', okText: '保存并返回', altText: '不保存', okVal: 'save' });
    if (r === false) return;                 // 取消 = 继续编辑
    if (r === 'save') { if (!(await plSave())) return; }
    // r === 'alt'（不保存）：直接丢弃
  }
  plEditing = false; plFormBase = null;
  loadPlan();
}
$('#pl-back').onclick = plLeaveSetup;
$('#pl-gen').onclick = async () => {
  const b = $('#pl-gen');
  b.disabled = true; b.textContent = '规划助手思考中…';
  try {
    const d = await api('/api/plan/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    plProfile = d.profile;
    renderPlan(d);
    toast('已排好 ' + d.total + ' 条');
  } catch (e) { toast(e.message, true); }
  b.disabled = false; b.textContent = '✨ 让规划助手排今天的计划';
};
$('#pl-add').onclick = async () => {
  const v = $('#pl-in').value.trim(); if (!v) return;
  try {
    await api('/api/plan/item', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: v }) });
    $('#pl-in').value = ''; loadPlan();
  } catch (e) { toast(e.message, true); }
};
$('#pl-in').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') $('#pl-add').click(); });
$('#pl-list').addEventListener('click', async e => {
  const go = e.target.closest('[data-plgo]');
  if (go) { e.stopPropagation(); ntfGo(go.dataset.plgo); return; }   // 复用消息中心那套跳转
  const del = e.target.closest('[data-pldel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('删除这条计划？'))) return;
    try { await api('/api/plan/' + del.dataset.pldel, { method: 'DELETE' }); loadPlan(); }
    catch (er) { toast(er.message, true); }
    return;
  }
  const it = e.target.closest('[data-pl]'); if (!it) return;
  try { await api('/api/plan/' + it.dataset.pl + '/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); loadPlan(); }
  catch (er) { toast(er.message, true); }
});

/* ---------------- 备考计划记录 + 进度分析 ---------------- */
$('#pl-hist').onclick = () => openPlanLog();
$('#pl-analyze').onclick = () => openPlanLog(true);
function openPlanLog(runAnalyze) {
  push({ view: 'planlog', title: '计划记录' });
  $('#plh-analysis').classList.add('hidden'); $('#plh-analysis').innerHTML = '';
  loadPlanLog();
  if (runAnalyze) setTimeout(plhAnalyze, 200);
}
function plItemsHtml(items, checkable, pid) {
  return items.map(it => {
    const col = PL_MOD_COLOR[it.module] || '#6b7280';
    return `<div class="plh-item ${it.done ? 'done' : ''}">
      <span class="plh-dot">${it.done ? '✓' : ''}</span>
      <span class="plh-itxt"><span class="plh-title">${esc(it.title)}</span>
        <span class="pl-tags">${it.module ? `<i class="pl-mod" style="background:${col}">${esc(it.module)}</i>` : ''}<i class="pl-min">${it.minutes || 0} 分钟</i></span>
      </span></div>`;
  }).join('');
}
async function loadPlanLog() {
  $('#plh-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/plan/history');
    if (!d.days.length) { $('#plh-list').innerHTML = '<p class="empty">还没有计划记录。让规划助手排几天计划，这里就会留下每天的完成情况。</p>'; return; }
    $('#plh-list').innerHTML = d.days.map(day => {
      const arch = (day.archived || []).map(a => `
        <details class="plh-arch">
          <summary>${a.summary && a.summary.indexOf('【找回】') === 0 ? '🛟 找回的上一版' : '🕓 旧版本'} · ${esc((a.created_at || '').slice(5, 16))} · ${a.total} 条 / ${a.minutes_total} 分钟
            ${day.is_today ? `<button class="plh-restore" data-restore="${a.id}">恢复为今天</button>` : ''}</summary>
          ${a.summary ? `<div class="plh-sum">💡 ${esc(a.summary.replace('【找回】', ''))}</div>` : ''}
          ${plItemsHtml(a.items || [])}
        </details>`).join('');
      return `<div class="plh-day">
        <div class="plh-dhead"><b>${esc(day.date)}</b>${day.is_today ? ' <span class="plh-today">今天</span>' : ''}
          <span class="plh-prog">${day.total ? `完成 ${day.done_n}/${day.total} · ${day.minutes_done}/${day.minutes_total} 分钟` : '当天无计划'}</span></div>
        ${day.total ? plItemsHtml(day.items) : ''}
        ${arch}
      </div>`;
    }).join('');
  } catch (e) { $('#plh-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#plh-list').addEventListener('click', async e => {
  const r = e.target.closest('[data-restore]'); if (!r) return;
  e.preventDefault();
  if (!(await appConfirm('把这一版恢复成今天的计划？当前这版会先存进历史。'))) return;
  try { await api('/api/plan/restore/' + r.dataset.restore, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); toast('已恢复'); loadPlanLog(); }
  catch (er) { toast(er.message, true); }
});
$('#plh-analyze-btn').onclick = plhAnalyze;
async function plhAnalyze() {
  const box = $('#plh-analysis'); const btn = $('#plh-analyze-btn');
  box.classList.remove('hidden');
  box.innerHTML = '<p class="empty">规划助手正在翻你的计划记录…</p>';
  btn.disabled = true;
  try {
    const d = await api('/api/plan/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const sec = (title, arr, cls) => arr && arr.length ? `<div class="plh-sec ${cls}"><h4>${title}</h4><ul>${arr.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>` : '';
    box.innerHTML = `
      <div class="plh-ov">${esc(d.overview || '')}</div>
      <div class="plh-stat">近 ${d.days} 天 · 共 ${d.total} 条 · 完成 ${d.done} 条</div>
      ${sec('✅ 坚持得不错', d.keep, 'keep')}
      ${sec('⚠️ 被冷落 / 长期没安排', d.neglected, 'neg')}
      ${sec('👉 接下来建议', d.suggestions, 'sug')}`;
  } catch (e) { box.innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
  btn.disabled = false;
}

/* ---------------- 每日巩固测试（按当天学的内容 AI 出小测） ---------------- */
$('#dt-open').onclick = () => openDtest();
function openDtest() { push({ view: 'dtest', title: '巩固测试' }); loadDtest(); }
let dtItems = [], dtChosen = {}, dtRevealed = {}, dtSubmitted = false, dtResults = null;
// 背题模式 study：做一题立刻显示答案；测试模式 test：答案不下发，交卷才服务端判分
let dtMode = lsGet('dtMode') === 'test' ? 'test' : 'study';
let dtCount = (+lsGet('dtCount') === 15) ? 15 : 10;   // 题量 10 / 15
const DT_L = ['A', 'B', 'C', 'D', 'E', 'F'];
function dtIsTest() { return dtMode === 'test'; }
function dtRevealedAt(i) { return dtIsTest() ? dtSubmitted : !!dtRevealed[i]; }
function dtModeBar() {
  return `<div class="dt-bar">
    <div class="dt-modes">
      <button class="dt-mbtn ${dtMode === 'study' ? 'on' : ''}" data-dtm="study">📖 背题模式</button>
      <button class="dt-mbtn ${dtMode === 'test' ? 'on' : ''}" data-dtm="test">📝 测试模式</button>
    </div>
    <div class="dt-mhint">${dtMode === 'study'
      ? '做一题立刻显示这题答案与解析，边做边记'
      : '答案不提前下发，全部做完交卷、由服务端判分，更像考试'}</div>
    <div class="dt-count">题量：
      <button class="dt-cbtn ${dtCount === 10 ? 'on' : ''}" data-dtc="10">10 题</button>
      <button class="dt-cbtn ${dtCount === 15 ? 'on' : ''}" data-dtc="15">15 题</button></div>
    <button class="pl-link-btn" id="dt-records">📋 测试记录</button>
  </div>`;
}
async function loadDtest() {
  $('#dt-body').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/dtest' + (dtIsTest() ? '?exam=1' : ''));
    dtItems = d.items || []; dtChosen = {}; dtRevealed = {}; dtSubmitted = false; dtResults = null;
    if (!dtItems.length) {
      $('#dt-body').innerHTML = dtModeBar() +
        `<div class="dt-empty">今天还没生成测试。选好模式和题量，AI 会按你今天学的内容出题。</div>
        <button class="btn primary" id="dt-gen">✨ 生成今日巩固测试</button>`;
      $('#dt-gen').onclick = () => dtGen(false);
      bindBar();
      return;
    }
    renderDtest();
  } catch (e) { $('#dt-body').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function bindBar() {
  const rec = $('#dt-records'); if (rec) rec.onclick = openDtRecords;
  document.querySelectorAll('[data-dtm]').forEach(b => b.onclick = async () => {
    const m = b.dataset.dtm; if (m === dtMode) return;
    dtMode = m; lsSet('dtMode', m);
    // 切换模式：同一套题、保留你的作答，只改「何时揭晓答案」，不重新出题、不清空
    if (dtSubmitted || !dtItems.length) { loadDtest(); return; }
    if (m === 'study') {
      // 背题模式要用到答案；若当前这套没带答案（从测试模式来的），重新拉同一套带答案的
      if (dtItems[0] && dtItems[0].answer === undefined) {
        try { const d = await api('/api/dtest'); if ((d.items || []).length === dtItems.length) dtItems = d.items; } catch (_) {}
      }
      dtRevealed = {}; Object.keys(dtChosen).forEach(i => dtRevealed[i] = true);  // 已答的直接揭晓
    } else {
      dtRevealed = {};   // 测试模式：收起逐题揭晓，作答保留，交卷时统一判分
    }
    renderDtest();
  });
  document.querySelectorAll('[data-dtc]').forEach(b => b.onclick = async () => {
    const n = +b.dataset.dtc; if (n === dtCount) return;
    if (dtItems.length && !dtSubmitted) {
      if (!(await appConfirm('换成 ' + n + ' 题需要重新出题，当前作答会清空。'))) return;
      dtCount = n; lsSet('dtCount', n); dtGen(true);
    } else {
      dtCount = n; lsSet('dtCount', n);
      document.querySelectorAll('[data-dtc]').forEach(x => x.classList.toggle('on', +x.dataset.dtc === dtCount));
    }
  });
}
async function dtGen(force) {
  $('#dt-body').innerHTML = `<p class="empty">AI 正在按你今天学的内容出 ${dtCount} 道题，稍等…</p>`;
  try {
    const d = await api('/api/dtest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: !!force, exam: dtIsTest(), count: dtCount }) });
    dtItems = d.items || []; dtChosen = {}; dtRevealed = {}; dtSubmitted = false; dtResults = null;
    renderDtest();
  } catch (e) {
    $('#dt-body').innerHTML = `<div class="dt-empty">${esc(e.message)}</div><button class="btn" id="dt-retry">重试</button>`;
    $('#dt-retry').onclick = () => dtGen(force);
  }
}
// 答案来源：背题模式在 item 里（已下发）；测试模式交卷后在 dtResults 里
function dtAns(i) { return dtResults ? (dtResults[i] || {}).answer : (dtItems[i].answer || '').toUpperCase(); }
function dtExp(i) { return dtResults ? (dtResults[i] || {}) : dtItems[i]; }
function dtScore() {
  if (dtResults) return dtResults.reduce((n, r) => n + (r.correct ? 1 : 0), 0);
  return dtItems.reduce((n, it, i) => n + (dtChosen[i] === (it.answer || '').toUpperCase() ? 1 : 0), 0);
}
