/* AI：截图 / 粘贴图片 / 手写输入
 *
 * 由 app.js 按它自己的区段边界切出（原 L10430-10609）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, aiAttachLib, aiHandleAttach, api, artEm, c, clipFiles, deskMsg, errMsg, getAppClip,
   loadMaterials, openAI, push, qnAddImgs, qnOpen, stack, toast */

/* ================= AI：截图 / 粘贴图片 / 手写输入 =================
   识图必须走智谱 GLM-4.6V —— 实测 DeepSeek 的 API 直接拒收图片
   （HTTP 400: unknown variant `image_url`），它根本没有视觉能力。
   所以：图 → 智谱读成文字 → 文字再交给 DeepSeek（便宜）。/api/ai/extract 已经是这个流程。 */

/* ---- #14 Ctrl+V 粘贴截图/文件、拖文件进来，直接变成 AI 附件 ---- */
async function aiAttachFiles(files) {
  // 一个个来，不并发：extract 那头要 OCR，同时开几路只会互相拖慢，提示也会打架
  for (const f of files.slice(0, 5)) {
    toast((f.type || '').startsWith('image/') ? '正在读取截图…' : '正在读取附件…');
    await aiHandleAttach(f);
  }
}
$('#ai-panel').addEventListener('paste', e => {
  const fs = clipFiles(e);                // 截图进 items、复制的文件进 files，两条都得看
  if (fs.length) { e.preventDefault(); aiAttachFiles(fs); return; }
  /* 系统剪贴板里没有文件，再看应用内剪贴板 —— 刚在云盘里点过「复制」的话，
     文件只存在于应用自己这份剪贴板里（桌面壳的 WebKit 只认文本和图片，
     云盘的「复制」也只是记下 id，压根没往系统剪贴板里放东西）。 */
  const clip = getAppClip();
  if (!clip.length) return;               // 粘文字就照常，不拦
  const txt = (e.clipboardData && e.clipboardData.getData('text')) || '';
  if (txt.trim()) {
    // 两份剪贴板都有货：粘文字是人当下的意图，别替他做主，只把另一条路指出来
    toast('剪贴板里还有 ' + clip.length + ' 个文件，点输入框上方的「附给 AI」可以一起带上');
    return;
  }
  e.preventDefault();
  aiAttachLib(clip, { keepPanel: true });
});
$('#ai-panel').addEventListener('dragover', e => e.preventDefault());
$('#ai-panel').addEventListener('drop', e => {
  const fs = [...(e.dataTransfer ? e.dataTransfer.files : [])];
  if (fs.length) { e.preventDefault(); aiAttachFiles(fs); }
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
    try { cv.setPointerCapture(e.pointerId); } catch (_) { /* 捕获失败不影响画线，指针事件照样收得到 */ }
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
      <div class="ns-title">${artEm('📷')} 截图好了，怎么用它？</div>
      <img src="${url}" style="max-width:100%;max-height:38vh;display:block;margin:0 auto 12px;border-radius:8px;">
      <div class="acm-list">
        <button data-sd="ai">${artEm('🤖')} 问 AI（讲解 / 出处 / 怎么做）</button>
        <button data-sd="note">${artEm('📒')} 存到小记</button>
        <button data-sd="mat">${artEm('📚')} 存到资料库</button>
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
  } catch (e) { toast(errMsg(e), true); }
}
shotBind();
