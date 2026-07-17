/* 草稿本 / 外观 / 侧边翻页 / 给定资料面板 / AI 截图 / 书签 / 桌面拖放 / 划重点
 *
 * 由 app.js 按它原有的区段边界切出（原 L10116-11034）。顺序即原顺序 —— index.html 里
 * 按同样次序引入，执行序与拆分前逐字节一致。
 *
 * 下面 /* global *​/ 是这个模块的依赖清单：它用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，这就是现成的 import 表。
 */
/* global $, DOC, IS_MOBILE, NW_KIND, TITLES, addDraftFiles,
   addDraftImages, aiHandleAttach, api, appConfirm, appPrompt, applyPush,
   avoidFab, back, bindImgDrop, bindImgPaste, c, ckBoard,
   compressImage, crFid, crSendFiles, createDock, csBoard, deskMsg,
   draft, dvUpload, esc, hl, loadMaterials, lsGet,
   lsSet, matBoard, nwCur, openAI, padCur, padDraftId,
   padInit, padInited, padMode, padOnView, padOpen, padRebuild,
   padSave, padSetData, padStatus, push, qnAddFiles, qnAddImgs,
   qnOpen, slUploadPaper, stack, toast, uploadDropped */

/* ---------- 草稿本：错题本里，平时打草稿用（多本 / 云端保存 / 手机电脑同步） ---------- */
function openDrafts() { push({ view: 'drafts' }); loadDrafts(); }
async function loadDrafts() {
  try {
    const d = await api('/api/drafts');
    $('#dr-empty').textContent = '还没有草稿本，点右下角 ＋ 新建一本';
    $('#dr-empty').classList.toggle('hidden', !!d.items.length);
    $('#dr-list').innerHTML = d.items.map(it => `
      <div class="dr-card" data-dr="${it.id}">
        <div class="dr-thumb"${it.thumb ? ` style="background-image:url(${it.thumb})"` : ''}></div>
        <div class="dr-body">
          <div class="dr-t">${esc(it.title || '未命名')}</div>
          <div class="dr-foot">
            <span class="dr-m">${it.pages || 1} 页 · ${(it.updated_at || '').slice(5, 16)}</span>
            <button class="dr-del" data-del="${it.id}" title="删除">✕</button>
          </div>
        </div>
      </div>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#dr-list').addEventListener('click', async e => {
  const del = e.target.closest('.dr-del');
  if (del) {
    e.stopPropagation();
    if (!await appConfirm('删除这本草稿？删了就找不回来了。', { title: '草稿本', okText: '删除' })) return;
    try { await api('/api/drafts/' + del.dataset.del, { method: 'DELETE' }); toast('已删除'); loadDrafts(); }
    catch (err) { toast(err.message, true); }
    return;
  }
  const c = e.target.closest('.dr-card');
  if (c) openDraft(+c.dataset.dr);
});
$('#dr-fab').onclick = async () => {
  const t = await appPrompt('新建草稿本', '起个名字（留空就用日期）', '');
  if (t === null) return;
  try {
    const d = await api('/api/drafts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: t }),
    });
    openDraft(d.id);
  } catch (e) { toast(e.message, true); }
};
async function openDraft(id) {
  try {
    const d = await api('/api/drafts/' + id);
    if (!padInited) padInit();
    if (padMode !== 'draft') padSave();                            // 先把随手草稿纸存好，等下还要还原
    padMode = 'draft'; padDraftId = id; padCur = null;
    padSetData(d.data);
    $('#pad-title').textContent = d.title || '未命名';
    $('#pad-doc').classList.remove('hidden');
    padStatus('已保存');
    padOpen();
  } catch (e) { toast(e.message, true); }
}
$('#pad-name').onclick = async () => {
  if (padMode !== 'draft') return;
  const t = await appPrompt('草稿本改名', '名字', $('#pad-title').textContent);
  if (t === null) return;
  try {
    await api('/api/drafts/' + padDraftId, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: t }),
    });
    $('#pad-title').textContent = t.trim() || '未命名草稿';
    toast('已改名');
  } catch (e) { toast(e.message, true); }
};
$('#wq-drafts').onclick = openDrafts;
/* 对外钩子放在最后才挂：顶层 function 声明会自动成为 window 属性，
   若直接用同名守卫(window.padRebuild)，脚本刚开始就会被误判为"已就绪"而提前调用。 */
window.__padView = padOnView;
window.__padTheme = () => { if (padInited && !$('#pad').classList.contains('hidden')) padRebuild(); };

/* ================= 外观：头像 / 壁纸 =================
   壁纸铺在 body 上（fixed，不跟着滚），上面盖一层可调浓度的蒙版保证正文看得清。
   登录页在没登录时读不到接口，所以把壁纸 URL 缓存进 localStorage，login.html 自己取。 */
let SKIN = { avatar: '', wall_app: '', wall_login: '' };
const skinDim = () => Math.min(90, Math.max(0, parseInt(lsGet('skinDim') || '55', 10)));

function applySkin() {
  // 头像出现在两处：左上角的 logo 和账户页顶部的大圆。
  // （原来只更新了 logo，账户页那个是 HTML 里写死的「公」，换了头像也不变。）
  [$('#brand-logo'), $('#acct-avatar')].forEach(el => {
    if (!el) return;
    if (SKIN.avatar) {
      el.style.backgroundImage = 'url("' + SKIN.avatar + '")';
      el.classList.add('has-img');
      el.textContent = '';
    } else {
      el.style.backgroundImage = '';
      el.classList.remove('has-img');
      el.textContent = '公';
    }
  });
  // 应用内壁纸
  const b = document.body;
  b.classList.toggle('has-wall', !!SKIN.wall_app);
  b.style.setProperty('--wall', SKIN.wall_app ? 'url("' + SKIN.wall_app + '")' : 'none');
  b.style.setProperty('--wall-dim', (skinDim() / 100).toFixed(2));
  // 登录页要用的，缓存到本地（它没登录，拿不到接口）
  lsSet('wallLogin', SKIN.wall_login || '');
  lsSet('skinDim', String(skinDim()));
}
async function loadSkin() {
  try {
    SKIN = await api('/api/skin');
    applySkin();
  } catch (_) {}
}
function renderSkinPrev() {
  [['avatar', '公'], ['wall_app', '无'], ['wall_login', '无']].forEach(([k, empty]) => {
    const el = $('#sk-' + k);
    if (!el) return;
    if (SKIN[k]) { el.style.backgroundImage = 'url("' + SKIN[k] + '")'; el.innerHTML = ''; }
    else { el.style.backgroundImage = ''; el.innerHTML = '<span>' + empty + '</span>'; }
  });
  $('#skin-dim').value = skinDim();
  $('#skin-dimv').textContent = skinDim() + '%';
  $('#skin-dim-row').classList.toggle('hidden', !SKIN.wall_app && !SKIN.wall_login);
}
document.addEventListener('change', async e => {
  const inp = e.target.closest('input[data-skin]');
  if (!inp || !inp.files || !inp.files[0]) return;
  const kind = inp.dataset.skin, f = inp.files[0];
  inp.value = '';
  if (f.size > 12 * 1024 * 1024) { toast('图片太大了（超过 12MB）', true); return; }
  toast('上传中…');
  try {
    const fd = new FormData(); fd.append('file', f);
    const d = await api('/api/skin/' + kind, { method: 'POST', body: fd });
    SKIN[kind] = d.url + '?t=' + Date.now();      // 加时间戳，绕过缓存立刻看到新图
    applySkin(); renderSkinPrev();
    toast(kind === 'avatar' ? '头像已更换' : '壁纸已更换');
  } catch (err) { toast(err.message, true); }
});
$('#view-account').addEventListener('click', async e => {
  const del = e.target.closest('[data-skindel]');
  if (!del) return;
  const kind = del.dataset.skindel;
  if (!SKIN[kind]) return;
  if (!await appConfirm(kind === 'avatar' ? '恢复成默认头像？' : '清除这张壁纸？', { title: '外观定制' })) return;
  try {
    await api('/api/skin/' + kind, { method: 'DELETE' });
    SKIN[kind] = ''; applySkin(); renderSkinPrev();
    toast('已恢复默认');
  } catch (err) { toast(err.message, true); }
});
$('#skin-dim').addEventListener('input', e => {
  lsSet('skinDim', e.target.value);
  $('#skin-dimv').textContent = e.target.value + '%';
  applySkin();
});

/* ================= 侧边翻页条（电脑端）=================
   手写笔没有滚轮、没有中键，光靠拖滚动条很别扭。这里给一排大按钮：
   上下翻一屏、直接回顶（回顶时如果不在首页，顺便把「返回」按钮亮出来）、到底部。 */
function pgScroll(dy) {
  const el = document.scrollingElement || document.documentElement;
  el.scrollBy({ top: dy, behavior: 'smooth' });
}
function pgInit() {
  // 触屏手机不需要；桌面版和电脑网页才显示
  document.body.classList.toggle('has-pen', !IS_MOBILE);
  $('#pg-up').onclick = () => pgScroll(-(innerHeight * 0.85));
  $('#pg-dn').onclick = () => pgScroll(innerHeight * 0.85);
  $('#pg-end').onclick = () => {
    const el = document.scrollingElement || document.documentElement;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  };
  $('#pg-top').onclick = () => {
    const el = document.scrollingElement || document.documentElement;
    el.scrollTo({ top: 0, behavior: 'smooth' });
  };
  // 长按/右键「回到顶部」= 直接返回上一页，省得回顶再去点返回
  $('#pg-top').oncontextmenu = (e) => { e.preventDefault(); back(); };
}
pgInit();

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
  } catch (_) {}
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
    try { matCv.setPointerCapture(e.pointerId); } catch (_) {}
    matDrawing = true;
    matCur = { tool: matTool, color: matColor, pts: [matPt(e)] };
    matPaint();
  });
  matCv.addEventListener('pointermove', e => {
    if (!matDrawing || !matCur) return;
    e.preventDefault();
    let evs = [];
    try { if (e.getCoalescedEvents) evs = e.getCoalescedEvents(); } catch (_) {}
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

/* ================= AI：截图 / 粘贴图片 / 手写输入 =================
   识图必须走智谱 GLM-4.6V —— 实测 DeepSeek 的 API 直接拒收图片
   （HTTP 400: unknown variant `image_url`），它根本没有视觉能力。
   所以：图 → 智谱读成文字 → 文字再交给 DeepSeek（便宜）。/api/ai/extract 已经是这个流程。 */

/* ---- #14 Ctrl+V 粘贴截图 / 拖图片进来，直接变成 AI 附件 ---- */
$('#ai-panel').addEventListener('paste', e => {
  const items = [...((e.clipboardData && e.clipboardData.items) || [])];
  const img = items.find(i => (i.type || '').startsWith('image/'));
  if (!img) return;                       // 粘文字就照常，不拦
  e.preventDefault();
  const f = img.getAsFile();
  if (f) { toast('正在读取截图…'); aiHandleAttach(f); }
});
$('#ai-panel').addEventListener('dragover', e => e.preventDefault());
$('#ai-panel').addEventListener('drop', e => {
  const f = [...(e.dataTransfer ? e.dataTransfer.files : [])][0];
  if (f && (f.type || '').startsWith('image/')) { e.preventDefault(); aiHandleAttach(f); }
});

/* ---- #13 截图：壳抓图（GNOME 区域选择，鼠标/笔都能拖）→ 回到网页再用笔自由圈 ---- */
let shotImg = null, shotPts = [], shotRect = null, shotDraw = false, shotPen = false;
let shotCv, shotCtx, shotDest = 'ai';        // 截完去哪：ai=直接问AI；menu=让用户选（AI/小记/资料库）

function shotAsk(dest) {
  if (!window.__desktopShot) { toast('截图功能只在电脑桌面版里有', true); return; }
  shotDest = dest || 'ai';
  toast('拖选要截的区域…');
  deskMsg({ a: 'shot' });
}
window.__onShot = (dataUrl) => {          // 壳把截好的图交回来
  const im = new Image();
  im.onload = () => { shotImg = im; shotOpen(); };
  im.src = dataUrl;
};
function shotOpen() {
  shotPts = []; shotRect = null;
  $('#shot').classList.remove('hidden');
  shotCv = $('#shot-cv'); shotCtx = shotCv.getContext('2d');
  const maxW = Math.min(innerWidth - 40, 1400), maxH = innerHeight - 120;
  const k = Math.min(maxW / shotImg.width, maxH / shotImg.height, 1);
  shotCv.width = Math.round(shotImg.width * k);
  shotCv.height = Math.round(shotImg.height * k);
  shotPaint();
}
function shotPaint() {
  shotCtx.clearRect(0, 0, shotCv.width, shotCv.height);
  shotCtx.drawImage(shotImg, 0, 0, shotCv.width, shotCv.height);
  if (!shotPts.length && !shotRect) return;
  shotCtx.save();
  shotCtx.fillStyle = 'rgba(10,20,35,.5)';      // 圈外压暗，圈中的地方亮着
  shotCtx.fillRect(0, 0, shotCv.width, shotCv.height);
  shotCtx.globalCompositeOperation = 'destination-out';
  shotCtx.beginPath();
  if (shotRect) shotCtx.rect(shotRect.x, shotRect.y, shotRect.w, shotRect.h);
  else {
    shotCtx.moveTo(shotPts[0].x, shotPts[0].y);
    for (const p of shotPts) shotCtx.lineTo(p.x, p.y);
    shotCtx.closePath();
  }
  shotCtx.fill();
  shotCtx.restore();
  shotCtx.strokeStyle = '#2c8fd6'; shotCtx.lineWidth = 2; shotCtx.setLineDash([6, 4]);
  shotCtx.stroke();
  shotCtx.setLineDash([]);
}
function shotPt(e) {
  const r = shotCv.getBoundingClientRect();
  return { x: (e.clientX - r.left) * shotCv.width / r.width,
    y: (e.clientY - r.top) * shotCv.height / r.height };
}
function shotBind() {
  const cv = $('#shot-cv');
  cv.addEventListener('pointerdown', e => {
    e.preventDefault();
    shotDraw = true;
    shotPen = e.pointerType === 'pen';        // 笔 → 自由圈；鼠标/触摸 → 拖矩形
    const p = shotPt(e);
    shotPts = [p];
    shotRect = shotPen ? null : { x: p.x, y: p.y, w: 0, h: 0, x0: p.x, y0: p.y };
    try { cv.setPointerCapture(e.pointerId); } catch (_) {}
  });
  cv.addEventListener('pointermove', e => {
    if (!shotDraw) return;
    const p = shotPt(e);
    if (shotPen) shotPts.push(p);
    else {
      const r = shotRect;
      r.x = Math.min(r.x0, p.x); r.y = Math.min(r.y0, p.y);
      r.w = Math.abs(p.x - r.x0); r.h = Math.abs(p.y - r.y0);
    }
    shotPaint();
  });
  const up = () => { shotDraw = false; shotPaint(); };
  cv.addEventListener('pointerup', up);
  cv.addEventListener('pointercancel', up);

  $('#shot-cancel').onclick = () => { $('#shot').classList.add('hidden'); shotImg = null; };
  $('#shot-redo').onclick = () => { shotPts = []; shotRect = null; shotPaint(); };
  $('#shot-all').onclick = () => { shotPts = []; shotRect = null; shotSend(true); };
  $('#shot-ok').onclick = () => shotSend(false);
  $('#ai-shot').onclick = () => shotAsk('ai');       // AI 面板里的截图：直接问 AI
}
function shotSend(whole) {
  if (!shotImg) return;
  const k = shotImg.width / shotCv.width;      // 画布是缩放显示的，裁剪要还原到原图分辨率
  let box;
  if (whole || (!shotRect && shotPts.length < 3)) {
    box = { x: 0, y: 0, w: shotImg.width, h: shotImg.height };
  } else if (shotRect) {
    box = { x: shotRect.x * k, y: shotRect.y * k, w: shotRect.w * k, h: shotRect.h * k };
  } else {
    const xs = shotPts.map(p => p.x), ys = shotPts.map(p => p.y);
    box = { x: Math.min(...xs) * k, y: Math.min(...ys) * k,
      w: (Math.max(...xs) - Math.min(...xs)) * k, h: (Math.max(...ys) - Math.min(...ys)) * k };
  }
  if (box.w < 8 || box.h < 8) { toast('圈选的区域太小了', true); return; }
  const c = document.createElement('canvas');
  c.width = Math.round(box.w); c.height = Math.round(box.h);
  const x = c.getContext('2d');
  if (!whole && shotPts.length >= 3) {         // 自由圈：只保留圈内的部分
    x.save();
    x.beginPath();
    x.moveTo(shotPts[0].x * k - box.x, shotPts[0].y * k - box.y);
    for (const p of shotPts) x.lineTo(p.x * k - box.x, p.y * k - box.y);
    x.closePath(); x.clip();
    x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height);
  }
  x.drawImage(shotImg, box.x, box.y, box.w, box.h, 0, 0, c.width, c.height);
  if (!whole && shotPts.length >= 3) x.restore();
  c.toBlob(b => {
    if (!b) return;
    $('#shot').classList.add('hidden');
    shotImg = null;
    const file = new File([b], '截图' + Date.now() + '.png', { type: 'image/png' });
    if (shotDest === 'menu') shotChoose(file);      // 工具球来的：让用户选去哪
    else { openAI(); aiHandleAttach(file); }        // AI 面板来的：直接问 AI
  }, 'image/png');
}
// 截好后选去处：问 AI / 存到小记 / 存到资料库
function shotChoose(file) {
  const el = $('#shot-dest');
  const url = URL.createObjectURL(file);
  el.innerHTML = `<div class="ns-mask" data-sheet-close></div>
    <div class="ns-panel">
      <div class="ns-handle"></div>
      <div class="ns-title">📷 截图好了，怎么用它？</div>
      <img src="${url}" style="max-width:100%;max-height:38vh;display:block;margin:0 auto 12px;border-radius:8px;">
      <div class="acm-list">
        <button data-sd="ai">🤖 问 AI（讲解 / 出处 / 怎么做）</button>
        <button data-sd="note">📒 存到小记</button>
        <button data-sd="mat">📚 存到资料库</button>
      </div>
    </div>`;
  el.classList.remove('hidden');
  const close = () => { el.classList.add('hidden'); URL.revokeObjectURL(url); };
  el.querySelector('.ns-mask').onclick = close;
  el.querySelectorAll('[data-sd]').forEach(btn => {
    btn.onclick = () => {
      const d = btn.dataset.sd; close();
      if (d === 'ai') { openAI(); aiHandleAttach(file); }
      else if (d === 'note') {
        if ($('#qnote').classList.contains('hidden')) qnOpen();
        qnAddImgs([file]); toast('已加到小记，写两句就能记下');
      } else if (d === 'mat') { uploadShot(file); }
    };
  });
}
async function uploadShot(file) {
  toast('上传到资料库…');
  const fd = new FormData();
  fd.append('file', file, file.name); fd.append('board', ''); fd.append('section', ''); fd.append('title', '');
  try {
    await api('/api/materials', { method: 'POST', body: fd });
    toast('已存到资料库（未分类）');
    if ((stack[stack.length - 1] || {}).view === 'materials') loadMaterials();
  } catch (e) { toast(e.message, true); }
}
shotBind();

/* ================= 书签：看到哪了 =================
   长文（经典著作 / 要文库 / 范文 / 知识库文档）看到一半退出来，回头根本找不到位置。
   这里在阅读类页面自动记住滚动位置，回来时顶部给一条「上次看到这里 · 点我跳回」。 */
/* 书签：任何会滚动的页面都记「看到哪了」——长文如此，长列表（如 894 条成语）更需要。
   ref 用「视图 + 这一页的子标识」拼出来（板块名 / 文章 id / 分类…），换个板块就是另一条书签。 */
const BM_SKIP = new Set(['home', 'account', 'search', 'slgrade', 'quizrun', 'dtest', 'notify']);
let bmCur = null, bmT = null;

function bmRef() {
  const st = stack[stack.length - 1];
  if (!st || BM_SKIP.has(st.view)) return null;
  // 顶层 let 不会挂到 window 上，直接引用（都在同一个脚本作用域里）
  // 顶层 let 不会挂到 window 上，直接引用（同一脚本作用域）；标题足够区分的就用标题
  const sub = {
    doc: () => DOC && DOC.id,
    newsd: () => nwCur && nwCur.id,
    ckboard: () => ckBoard,
    csboard: () => csBoard,
    materials: () => matBoard || '全部',
  }[st.view];
  let id = '';
  try { id = sub ? (sub() || '') : (st.title || ''); } catch (_) { id = st.title || ''; }
  return { kind: st.view, ref: String(id || st.view), title: st.title || TITLES[st.view] || '' };
}
function bmScrollTop() { return (document.scrollingElement || document.documentElement).scrollTop; }
function bmSave() {                      // 滚动停下来 1.5s 就记一次（不打扰、不刷接口）
  const r = bmRef();
  if (!r) return;
  const el = document.scrollingElement || document.documentElement;
  const pos = el.scrollHeight > el.clientHeight ? bmScrollTop() / (el.scrollHeight - el.clientHeight) : 0;
  // 按「滚了多少像素」判断，不能按百分比：894 条成语那页有 15 万像素高，
  // 滚了 3000px 也才 2%，用百分比阈值会直接把书签丢掉。
  if (bmScrollTop() < 260) return;
  api('/api/bookmarks', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: r.kind, ref: r.ref, title: r.title, pos }),
  }).catch(() => {});
}
addEventListener('scroll', () => {
  if (!bmRef()) return;
  clearTimeout(bmT);
  bmT = setTimeout(bmSave, 1500);
}, { passive: true });

async function bmRestore() {             // 进阅读页时问一句：上次看到哪了
  const r = bmRef();
  if (!r) { $('#bm-tip').classList.add('hidden'); return; }
  try {
    const d = await api('/api/bookmarks');
    const b = (d.items || []).find(x => x.kind === r.kind && x.ref === r.ref);
    const el = document.scrollingElement || document.documentElement;
    const px = b ? b.pos * (el.scrollHeight - el.clientHeight) : 0;
    if (!b || px < 260) { $('#bm-tip').classList.add('hidden'); return; }
    bmCur = b;
    $('#bm-tip').innerHTML = `🔖 上次看到 <b>${Math.round(b.pos * 100)}%</b> 处 · <i>${(b.updated_at || '').slice(5, 16)}</i>
      <button class="btn tiny" id="bm-go">跳回去</button>
      <button class="bm-x" id="bm-hide">✕</button>`;
    $('#bm-tip').classList.remove('hidden');
  } catch (_) {}
}
document.addEventListener('click', e => {
  if (e.target.closest('#bm-go')) {
    const el = document.scrollingElement || document.documentElement;
    el.scrollTo({ top: bmCur.pos * (el.scrollHeight - el.clientHeight), behavior: 'smooth' });
    $('#bm-tip').classList.add('hidden');
  } else if (e.target.closest('#bm-hide')) $('#bm-tip').classList.add('hidden');
});
window.__bmView = () => setTimeout(bmRestore, 700);   // 内容渲染完再问

/* 选队友共享：复用底部弹层，勾选=共享，取消勾选=收回 */
function matPickMembers(members) {
  return new Promise(res => {
    const el = $('#mat-share-sheet');
    // ★ 必须裹 .ns-mask（深色遮罩）+ .ns-panel（白底面板）—— 少了它们，内容就直接浮在
    //   一张 position:fixed;inset:0 的**透明**层上，电脑端看着就是「完全透明的窗口」。
    el.innerHTML = `<div class="ns-mask" data-sheet-close></div>
      <div class="ns-panel">
        <div class="ns-handle"></div>
        <div class="ns-title">👥 共享给队友</div>
        <p class="acct-hint" style="padding:0 16px;margin:0 0 6px">勾上就共享给他（他能在资料库看到并下载，但不能改不能删）；取消勾选就收回。</p>
        <div class="ms-list">${members.map(m => `
          <label class="ms-row"><input type="checkbox" value="${m.id}" ${m.shared ? 'checked' : ''}>
            <span>${esc(m.username)}</span></label>`).join('')}</div>
        <div class="ms-acts">
          <button class="btn" id="ms-cancel">取消</button>
          <button class="btn primary" id="ms-ok">确定</button>
        </div>
      </div>`;
    el.classList.remove('hidden');
    const done = (v) => { el.classList.add('hidden'); res(v); };
    $('#ms-ok').onclick = () => done([...el.querySelectorAll('input:checked')].map(i => +i.value));
    $('#ms-cancel').onclick = () => done(null);
    el.querySelector('.ns-mask').onclick = () => done(null);
  });
}

/* ================= 桌面版：拖放 / 粘贴图片（由壳送进来） =================
   WebKitGTK 的 drop 事件里 dataTransfer.files 是**空的**（dragover 有效、drop 拿不到文件），
   往输入框里 Ctrl+V 粘图也粘不进去（WebKit 只认文字）。
   所以这两件事都由原生壳从 GTK 层拿到，再把内容送回网页。 */
const MIME = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif',
  webp: 'image/webp', bmp: 'image/bmp', heic: 'image/heic',
  pdf: 'application/pdf', txt: 'text/plain',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  ppt: 'application/vnd.ms-powerpoint',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
};
function b64ToFile(b64, name) {
  const bin = atob(b64);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  // ⚠️ 必须按后缀补上 MIME。原来 new File([buf], name) 造出来的文件 **type 是空的** ——
  //    凡是靠 f.type 判「这是不是图片」的地方（compressImage、qnAddImgs、addDraftImages）
  //    全都会把它当成非图片丢掉，表现就是「拖进去没反应」。
  const ext = (name || '').split('.').pop().toLowerCase();
  const type = MIME[ext] || '';
  return new File([buf], name || ('文件_' + Date.now()), type ? { type } : undefined);
}
/* 桌面壳里 target="_blank" 是**死的**：WebKit 把新窗口请求直接吞掉（在 decide-policy 里
   处理 NEW_WINDOW_ACTION 也没用，实测真机上就是不走）。所以桌面版**不指望 WebKit 的行为** ——
   全局拦住 _blank 外链，直接让壳去调系统浏览器。手机/浏览器不受影响，照常开新标签页。 */
document.addEventListener('click', e => {
  if (!window.__desktop) return;
  const a = e.target.closest('a[target="_blank"]');
  if (!a) return;
  const href = a.getAttribute('href') || '';
  if (!/^https?:\/\//i.test(href)) return;          // 站内相对链接不管
  try {
    const h = new URL(href, location.href).hostname;
    if (h === location.hostname) return;             // 自己站的，也不管
  } catch (_) { return; }
  e.preventDefault();
  deskMsg({ a: 'open', url: href });
  toast('已在系统浏览器打开');
}, true);

/* 桌面壳（WebKitGTK）里 drop 事件拿不到文件（dataTransfer.files 是空的），
   图片由壳在 GTK 层截下来、转成 base64 再回调这里。所以**壳里的拖放/粘贴走的是这条路**，
   不是网页里那些 bindImgDrop/bindImgPaste —— 那两个只在浏览器里生效。
   ⚠️ 随手记和小记编辑器一直没接进这个路由，所以在桌面版里拖图片进随手记会掉进兜底提示。 */
function dropTarget() {                 // 当前该把文件丢给谁
  const st = stack[stack.length - 1];
  // 随手记开着 → 它就是焦点，优先级**高于** AI 面板（人正在那儿写字）
  if ($('#qnote') && !$('#qnote').classList.contains('hidden')) return 'qnote';
  if ($('#ai-panel') && !$('#ai-panel').classList.contains('hidden')) return 'ai';
  if (!st) return '';
  if (st.view === 'notes') return 'notes';          // 小记页 → 进编辑器的图片区
  if (st.view === 'materials') return 'materials';
  if (st.view === 'shenlun') return 'shenlun';
  if (st.view === 'chat' && crFid) return 'chatroom';  // 正开着聊天窗 → 拖文件直接发
  if (st.view === 'drive') return 'drive';          // 云盘 → 拖文件上传到当前文件夹
  return '';
}
window.__onDragOver = () => {
  const t = dropTarget();
  if (t === 'materials') $('#view-materials').classList.add('drag-on');
  else if (t === 'shenlun') $('#view-shenlun').classList.add('drag-on');
  else if (t === 'qnote') $('#qnote').classList.add('drop-on');
  else if (t === 'notes') { const c = document.querySelector('.composer'); if (c) c.classList.add('drop-on'); }
  else if (t === 'chatroom') $('#chat-main').classList.add('cr-drop');
};
window.__onDragLeave = () => {
  $('#view-materials').classList.remove('drag-on');
  $('#view-shenlun').classList.remove('drag-on');
  const q = $('#qnote'); if (q) q.classList.remove('drop-on');
  const c = document.querySelector('.composer'); if (c) c.classList.remove('drop-on');
  const cm = $('#chat-main'); if (cm) cm.classList.remove('cr-drop');
};
const isImg = (f) => /^image\//.test(f.type || '') || /\.(jpe?g|png|gif|webp|bmp|heic)$/i.test(f.name || '');
window.__onDropFiles = (items) => {
  window.__onDragLeave();
  const files = (items || []).map(x => b64ToFile(x.data, x.name));
  if (!files.length) return;
  const t = dropTarget();
  if (t === 'qnote' || t === 'notes') {            // 小记：图片当图片，别的当附件
    const imgs = files.filter(isImg);
    const atts = files.filter(f => !isImg(f));
    if (t === 'qnote') { if (imgs.length) qnAddImgs(imgs); if (atts.length) qnAddFiles(atts); }
    else { if (imgs.length) addDraftImages(imgs); if (atts.length) addDraftFiles(atts); }
    const bits = [];
    if (imgs.length) bits.push(`${imgs.length} 张图`);
    if (atts.length) bits.push(`${atts.length} 个附件`);
    toast('已加 ' + bits.join(' + '));
    return;
  }
  if (t === 'ai') files.forEach(f => aiHandleAttach(f));         // AI 开着 → 当附件
  else if (t === 'shenlun') slUploadPaper(files[0]);             // 真题页 → 上传真题卷
  else if (t === 'materials') uploadDropped(files);              // 资料库 → 传进当前分类
  else if (t === 'chatroom') crSendFiles(files);                 // 聊天窗口 → 直接发给对方
  else if (t === 'drive') dvUpload(files);                       // 云盘 → 上传到当前文件夹
  else toast('把文件拖到「资料库」「真题批改」「小记」「聊天」「云盘」，或先打开 AI / 随手记', true);
};
window.__onPasteImage = (dataUrl) => {   // Ctrl+V / 右键「粘贴图片」（壳里的粘贴也走这条路）
  fetch(dataUrl).then(r => r.blob()).then(b => {
    const f = new File([b], '粘贴的图片.png', { type: 'image/png' });
    const t = dropTarget();                       // 和拖放共用一套路由，行为一致
    if (t === 'qnote') { qnAddImgs([f]); toast('已粘贴图片'); }
    else if (t === 'notes') { addDraftImages([f]); toast('已粘贴图片'); }
    else if (t === 'ai') { toast('正在读取图片…'); aiHandleAttach(f); }
    else if (t === 'materials') uploadDropped([f]);
    else { openAI(); toast('正在读取图片…'); aiHandleAttach(f); }   // 其它地方：开 AI 并附上
  }).catch(() => toast('粘贴失败', true));
};

/* ================= 通用「划重点」（悬浮球 → 🖍） =================
   任何模块的正文都能划：不重渲染页面，而是直接在**已经渲染好的 DOM 里**找到那些句子、就地包一层 <mark>。
   所以时政、常识、理论、范文、讲义、错题解析…统统适用，不用每个模块单独写一遍。
   要害：AI 挑的句子必须逐字来自原文（服务端已核对），否则在 DOM 里根本找不到。 */
// 「不是正文」的东西：按钮、工具栏、脚本…… 取正文时一律跳过
const MK_SKIP_BASE = 'button, input, textarea, select, nav, .topbar, .tk-tab, .chip, .btn, ' +
  '.pgbar, .fab, .bm-tip, .mk-bar, .mk-card, script, style, .cd-sec-t, .slt-sec';
// 划重点自己还要跳过 <mark>：已经标过的别再标一遍
const MK_SKIP = MK_SKIP_BASE + ', mark';
// 但**文本锚不能跳过 <mark>**：划重点会把重点句包进 <mark>，跳过的话锚句就从全文里消失、
// 那一页的手写批注全变孤儿不画 —— 而用户圈的重点，恰恰就是 AI 划重点也会标的句子。
const ANN_SKIP = MK_SKIP_BASE;
let mkMarks = [];

function mkPageRoot() {                 // 当前页面的「正文」在哪
  const st = stack[stack.length - 1];
  if (!st) return null;
  const view = $('#view-' + st.view);
  if (!view || view.classList.contains('hidden')) return null;
  // 优先取常见的正文容器；找不到就整页（跳过按钮/工具栏）
  const pick = view.querySelector('.poly-reader, .cd-wrap, #cd-wrap, .doc-blocks, .aih-scroll');
  return pick || view;
}
// 段落/标题这些「块」：块与块之间的文字本来就不连着读
const MK_BLOCK = 'p, li, h1, h2, h3, h4, h5, h6, blockquote, td, th, pre, section, article, div';
const mkBlockOf = (n) => (n.parentElement ? n.parentElement.closest(MK_BLOCK) : null);
// skip 不传＝划重点用的名单（跳过 <mark>）；文本锚要传 ANN_SKIP（看得见 <mark> 里的字）。
// sep 不传＝所有文本节点直接首尾相接（划重点的老行为：它只拿去 indexOf，不在乎读不读得通）；
//   文本锚要传 '\n' —— 不然标题和正文会粘成一串（"…学习问答今天问了什么…"），锚句跨块、
//   拿去做复习卡就是一坨读不通的东西，也没法按句子去重。
// **mkText 和 mkNodes 必须传同一份 skip 和 sep**，否则算出来的偏移对不上。
function mkText(root, skip, sep) {
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (!n.nodeValue.trim() || n.parentElement.closest(skip || MK_SKIP))
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  let s = '', prev = null;
  while (w.nextNode()) {
    const n = w.currentNode;
    if (sep) { const b = mkBlockOf(n); if (prev && b !== prev) s += sep; prev = b; }
    s += n.nodeValue;
  }
  return s;
}
function mkNodes(root, skip, sep) {
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (!n.nodeValue.trim() || n.parentElement.closest(skip || MK_SKIP))
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  const out = []; let pos = 0, prev = null;
  while (w.nextNode()) {
    const n = w.currentNode;
    if (sep) { const b = mkBlockOf(n); if (prev && b !== prev) pos += sep.length; prev = b; }
    out.push({ n, start: pos });
    pos += n.nodeValue.length;
  }
  return out;
}
function mkWrapOne(root, hit) {
  // 每次重新取一遍节点表：上一处标注会改变 DOM，偏移必须重算
  const nodes = mkNodes(root);
  const k = NW_KIND[hit.kind] || NW_KIND['提法'];
  for (let i = nodes.length - 1; i >= 0; i--) {
    const { n, start } = nodes[i];
    const end = start + n.nodeValue.length;
    if (end <= hit.start || start >= hit.end) continue;
    const s = Math.max(0, hit.start - start), e = Math.min(n.nodeValue.length, hit.end - start);
    if (e <= s) continue;
    const r = document.createRange();
    r.setStart(n, s); r.setEnd(n, e);
    const mk = document.createElement('mark');
    mk.className = 'nw-mk gk-mk';
    mk.style.setProperty('--mk', k.c);
    mk.dataset.gkm = hit.i;
    mk.title = hit.kind + '：' + (hit.why || '');
    try { r.surroundContents(mk); } catch (_) { r.detach && r.detach(); continue; }
    const tag = document.createElement('i');   // 右上角的小类型标签
    tag.textContent = hit.kind;
    mk.appendChild(tag);
    break;                                     // 一个片段包一次就够（跨节点的下一轮再来）
  }
}
function mkApply(root, marks) {
  const full = mkText(root);
  const hits = [];
  marks.map((m, i) => ({ m, i })).sort((a, b) => b.m.quote.length - a.m.quote.length)   // 长句先标
    .forEach(({ m, i }) => {
      let from = 0, at;
      while ((at = full.indexOf(m.quote, from)) !== -1) {
        const end = at + m.quote.length;
        if (!hits.some(h => at < h.end && end > h.start)) hits.push({ start: at, end, i, kind: m.kind, why: m.why });
        from = end;
      }
    });
  hits.sort((a, b) => b.start - a.start);      // 从后往前改，前面的偏移才不会失效
  hits.forEach(h => mkWrapOne(root, h));
  return hits.length;
}
function mkClear() {
  document.querySelectorAll('mark.gk-mk').forEach(m => {
    const i = m.querySelector('i'); if (i) i.remove();
    const p = m.parentNode;
    while (m.firstChild) p.insertBefore(m.firstChild, m);
    p.removeChild(m);
    p.normalize();
  });
  mkMarks = [];
  $('#mk-bar').classList.add('hidden');
  $('#mk-list').classList.add('hidden');
  document.body.classList.remove('mk-open');
  if (window.mkInject) setTimeout(() => mkInject(), 60);   // 清完了，把「帮我划重点」的卡片长回来
}
/* 划重点：**按模块**做，不是一个全局按钮套所有页面。
   每个模块划的东西根本不是一回事 —— 常识划「定义/数字/易混」（选项就改那一个字），
   错题划「陷阱/正解」，范文划「分论点/论证/表达」。类型清单和「这个模块该看什么」
   都由服务端 MK_PROFILES 给（GET /api/marks/profile），前端不另写一份。
   入口是各模块页顶部自动长出来的一张卡片（和时政那张一样），不在悬浮球里。 */
const MK_COLORS = ['#c4661f', '#1e8449', '#1a6fb5', '#7a5cc0', '#b23b2e'];
let mkProf = null, mkProfScope = '';

// 哪些页面配划重点：服务端有 profile 的都算（问一次缓存住）
async function mkGetProf(scope) {
  if (mkProfScope === scope && mkProf) return mkProf;
  const d = await api('/api/marks/profile?scope=' + encodeURIComponent(scope));
  d.color = {};
  d.kinds.forEach((k, i) => { d.color[k.k] = MK_COLORS[i % MK_COLORS.length]; });
  mkProf = d; mkProfScope = scope;
  return d;
}
const MK_VIEWS = ['csboard', 'thboard', 'workd', 'partydict', 'policydocd', 'essayd', 'writed',
  'wqdetail', 'slresult', 'sltype', 'boardkb', 'docqad', 'cdetail', 'ckboard', 'viewer', 'fanwend'];

// 进到有划重点的模块，就在正文顶部长出这张卡（时政那张是模块自己写的，不走这里）
async function mkInject() {
  const st = stack[stack.length - 1];
  const old = document.getElementById('mk-card');
  if (old) old.remove();
  if (!st || !MK_VIEWS.includes(st.view)) return;
  const root = mkPageRoot();
  if (!root || mkText(root).replace(/\s+/g, ' ').trim().length < 120) return;   // 正文太短不值当
  if (root.querySelector('mark.gk-mk')) return;                                  // 已经划过了
  let p;
  try { p = await mkGetProf(st.view); } catch (_) { return; }
  const card = document.createElement('div');
  card.id = 'mk-card'; card.className = 'mk-card';
  // focus 里用 **xx** 标了要强调的词（后端写的），转成粗体，别把星号露出来
  const bold = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  card.innerHTML = `<div class="mk-card-t">🖍 重点 · 考点</div>
    <p class="mk-card-p">${p.focus ? bold(p.focus) + '<br>' : ''}
      点一下，AI 按<b>「${esc(p.name)}」的考法</b>在本页标出：
      ${p.kinds.map(k => `<span class="mk-ck" style="--mk:${p.color[k.k]}">${esc(k.k)}</span>`).join('')}</p>
    <button class="btn primary" id="mk-go">🖍 帮我划重点</button>`;
  root.insertBefore(card, root.firstChild);
}
document.addEventListener('click', e => {
  if (e.target.closest('#mk-go')) markPage();
});

async function markPage(force) {
  if (document.querySelector('mark.gk-mk') && !force) { mkClear(); toast('已清除重点'); return; }
  if (document.querySelector('.nw-mk:not(.gk-mk)')) { toast('这页已经划过重点了'); return; }
  const root = mkPageRoot();
  const text = root ? mkText(root).replace(/\s+/g, ' ').trim() : '';
  if (!root || text.length < 60) { toast('这页没有可划的正文', true); return; }
  const scope = stack[stack.length - 1].view;
  const btn = $('#mk-go');
  if (btn) { btn.disabled = true; btn.textContent = '划重点中…（约 20 秒）'; }
  try {
    await mkGetProf(scope);
    const d = await api('/api/marks', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: mkText(root), scope }),
    });
    mkClear();
    mkMarks = d.marks || [];
    const n = mkApply(root, mkMarks);
    if (!n) { toast('这页的正文和 AI 挑的句子对不上，换个页面试试', true); return; }
    const c = document.getElementById('mk-card'); if (c) c.remove();
    mkRenderBar(n, !!d.cached);
    toast('划出 ' + n + ' 处重点' + (d.cached ? '（缓存）' : ''));
  } catch (e) {
    toast(e.message, true);
    if (btn) { btn.disabled = false; btn.textContent = '🖍 帮我划重点'; }
  }
}
function mkRenderBar(n, cached) {
  const p = mkProf || { name: '', kinds: [], color: {} };
  const col = (k) => p.color[k] || (NW_KIND[k] && NW_KIND[k].c) || MK_COLORS[0];
  $('#mk-bar').innerHTML = `🖍 划出 <b>${n}</b> 处重点${cached ? ' <i>· 缓存</i>' : ''}
    <button class="btn tiny" id="mk-toggle">看清单</button>
    <button class="mk-x" id="mk-clear" title="清除">✕</button>`;
  $('#mk-bar').classList.remove('hidden');
  $('#mk-list').innerHTML = `<div class="mk-lt">🖍 ${esc(p.name)} · 重点考点（${mkMarks.length} 处）</div>
    ${mkMarks.map((m, i) => `<div class="nw-m" data-mkgo="${i}" style="--mk:${col(m.kind)}">
        <span class="nw-k">${esc(m.kind)}</span>
        <span class="nw-q">${esc(m.quote)}</span>
        <span class="nw-w">${esc(m.why || '')}</span></div>`).join('')}
    <div class="nw-legend">${p.kinds.map(k =>
      `<span style="--mk:${col(k.k)}"><i></i>${esc(k.k)}：${esc(k.d)}</span>`).join('')}</div>`;
}
document.addEventListener('click', e => {
  if (e.target.closest('#mk-clear')) { mkClear(); return; }
  if (e.target.closest('#mk-toggle')) {
    const on = $('#mk-list').classList.toggle('hidden');
    $('#mk-toggle').textContent = on ? '看清单' : '收起清单';
    document.body.classList.toggle('mk-open', !on);   // 清单铺开时把悬浮球收起来，别互相挡
    return;
  }
  const go = e.target.closest('[data-mkgo]');
  if (go) {
    const el = document.querySelector(`mark.gk-mk[data-gkm="${go.dataset.mkgo}"]`);
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      el.classList.add('flash');
      setTimeout(() => el.classList.remove('flash'), 1400);
    }
  }
});
