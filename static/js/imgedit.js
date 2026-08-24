/* 图片编辑：转、裁、打码
 *
 * 挂在**查看器**上，所以七个看图的入口（云盘、资料库、知识库、小记附件、聊天收到的图、
 * 云盘搜索结果、题目详情）一次全有 —— 它们打开图片走的是同一个 openViewerUrl。
 *
 * 两条不肯让步的地方：
 *   1. 马赛克是**就地把像素平均掉**，不是盖一层色块。盖色块的做法一旦被撤销、或者
 *      存成带透明的格式，遮住的证件号就露回来了 —— 这种东西不能赌。
 *   2. 默认另存副本，原图一个字节不动。覆盖要单独点、还要再确认一次。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 */
/* global $, api, appConfirm, back, dvJump, errMsg, push, stack, toast, viewerImg */

/* ================= 图片编辑 ================= */
/* 与后端 mods/social.py 的 EDIT_EXT 同名同内容（tests/frontend/crossend.test.js 盯着这一对）：
   前端拿它决定给不给「编辑」按钮，后端拿它决定收不收这次写回。两边走散 =
   按钮点得下去、存的时候被拒。HEIC/TIFF 不在里面：浏览器根本画不出来。 */
const EDIT_EXT = ['.png', '.jpg', '.jpeg', '.webp', '.bmp'];
const IE_MAX_PX = 4096;        // 进画布前的长边上限：手机原图上亿像素，直接画会卡死
const IE_MAX_UNDO = 15;        // 每一步都是一整张画布，手机上留太多会把内存吃光
const IE_JPEG_Q = 0.92;

let ieCv = null, ieCtx = null;      // 主画布
let ieOrigin = null;                // 最初那张，「重来」回到它
let ieUndo = [];
let ieTool = '', ieColor = '#e53935', ieBrush = 34;
let ieDrag = null;
let ieSrc = null;                   // {kind:'drive', id} | null（别处来的图只能另存到云盘）
let ieName = '图片.jpg', ieExt = '.jpg';

const ieEditable = (ext) => EDIT_EXT.includes((ext || '').toLowerCase());
const ieSay = (t) => { $('#ie-status').textContent = t; };

/* 离屏画布一律从这里出，连上下文一起给。
   `willReadFrequently` 不是「为了读得快」才加的，是**必须**加：
   桌面壳走的是 WebKit(2GTK)，把一张带 willReadFrequently 的画布 drawImage 到一张
   **没带**的画布上，画进去的是空的 —— 两边后端不是一套（一个软件光栅、一个走加速），
   取不到像素，而且不报错、不抛异常，画布就那么整张透明了。
   主画布 ieCtx 带着这个参数（马赛克要就地读像素），于是所有拿主画布当源的操作 ——
   旋转、翻转、裁剪、撤销快照 —— 都得在这一边。漏掉任何一处，那一步之后就是一片空白。 */
function ieNewCv(w, h) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  return { cv: c, g: c.getContext('2d', { willReadFrequently: true }) };
}

function ieSnap(src) {
  const { cv, g } = ieNewCv(src.width, src.height);
  g.drawImage(src, 0, 0);
  return cv;
}
function iePushUndo() {
  ieUndo.push(ieSnap(ieCv));
  if (ieUndo.length > IE_MAX_UNDO) ieUndo.shift();
  $('#ie-undo').disabled = false;
}
// 把一张离屏画布放回主画布。尺寸跟着变 —— 旋转和裁剪都会改画布大小
function iePaste(src) {
  ieCv.width = src.width; ieCv.height = src.height;
  ieCtx.drawImage(src, 0, 0);
  $('#ie-dims').textContent = ieCv.width + ' × ' + ieCv.height;
}

/* ---- 打开 ---- */
function openImgEdit(url, name, ext, src) {
  ieName = name || '图片'; ieExt = (ext || '.jpg').toLowerCase(); ieSrc = src || null;
  ieUndo = []; ieDrag = null; ieTool = '';
  $('#ie-undo').disabled = true;
  $('#imgedit').classList.remove('hidden');
  document.body.classList.add('ie-open');
  ieCv = $('#ie-cv'); ieCtx = ieCv.getContext('2d', { willReadFrequently: true });
  ieSetTool('');
  ieSay('加载中…');
  /* push 一层：手机上的返回手势、桌面壳的返回键，都该是「退出编辑」而不是退出整个查看器。
     关掉编辑器时若这一层还在栈顶，由 ieClose 负责弹掉。 */
  push({ view: 'imgedit', title: '编辑 ' + ieName });
  const im = new Image();
  im.onload = () => {
    let w = im.naturalWidth, h = im.naturalHeight;
    const k = IE_MAX_PX / Math.max(w, h);
    const shrank = k < 1;
    if (shrank) { w = Math.round(w * k); h = Math.round(h * k); }
    const { cv: c, g } = ieNewCv(w, h);
    g.drawImage(im, 0, 0, w, h);
    ieOrigin = c;
    iePaste(c);
    ieSay(shrank ? '图太大，已缩到 ' + w + '×' + h + ' 再编辑' : '选一个工具开始');
  };
  im.onerror = () => ieSay('这张图没打开，换一张试试');
  im.src = url;
}

function ieClose() {
  ieHide();
  // 只弹自己压的那一层；用户已经退到别处时别顺手把人家的栈也弹了
  if (stack.length && stack[stack.length - 1].view === 'imgedit') back();
}

/* 只收浮层、不碰导航栈。
   给 shell.js 的 render 用：系统返回键/返回手势把栈弹走时，底下已经换页了，
   这一层要是不收，编辑器就永远盖在屏幕上、还谁都点不掉。 */
function ieHide() {
  $('#imgedit').classList.add('hidden');
  document.body.classList.remove('ie-open');
  ieUndo = []; ieOrigin = null; ieDrag = null;
  $('#ie-undo').disabled = true;
}
// shell.js 在首屏包里，够不着这个延后包的函数名，只能过 window
window.__ieHide = ieHide;

/* ---- 变形 ---- */
function ieRotate(dir) {
  iePushUndo();
  const { cv: c, g } = ieNewCv(ieCv.height, ieCv.width);
  g.translate(c.width / 2, c.height / 2);
  g.rotate(dir * Math.PI / 2);
  g.drawImage(ieCv, -ieCv.width / 2, -ieCv.height / 2);
  iePaste(c);
  ieSay(dir > 0 ? '右转 90°' : '左转 90°');
}
function ieFlip() {
  iePushUndo();
  const { cv: c, g } = ieNewCv(ieCv.width, ieCv.height);
  g.translate(c.width, 0); g.scale(-1, 1); g.drawImage(ieCv, 0, 0);
  iePaste(c);
  ieSay('左右翻转');
}

/* ---- 坐标：屏幕上的点 → 画布像素 ----
   画布是按 CSS 缩放显示的（max-width/max-height），两套尺寸不换算的话，
   手指点在户号上、马赛克打在旁边。 */
function ieAt(e) {
  const r = ieCv.getBoundingClientRect();
  return { x: (e.clientX - r.left) * (ieCv.width / r.width),
           y: (e.clientY - r.top) * (ieCv.height / r.height) };
}

/* ---- 马赛克：就地把像素平均掉 ---- */
function ieMosaicAt(x, y) {
  const s = Math.max(8, ieBrush);
  const x0 = Math.max(0, Math.round(x - s / 2)), y0 = Math.max(0, Math.round(y - s / 2));
  const w = Math.min(ieCv.width - x0, s), h = Math.min(ieCv.height - y0, s);
  if (w <= 0 || h <= 0) return;
  const img = ieCtx.getImageData(x0, y0, w, h), d = img.data;
  const block = Math.max(4, Math.round(s / 4));
  for (let by = 0; by < h; by += block) {
    for (let bx = 0; bx < w; bx += block) {
      const bw = Math.min(block, w - bx), bh = Math.min(block, h - by);
      let r = 0, g = 0, b = 0, n = 0;
      for (let yy = 0; yy < bh; yy++) {
        for (let xx = 0; xx < bw; xx++) {
          const i = ((by + yy) * w + bx + xx) * 4;
          r += d[i]; g += d[i + 1]; b += d[i + 2]; n++;
        }
      }
      r /= n; g /= n; b /= n;
      for (let yy = 0; yy < bh; yy++) {
        for (let xx = 0; xx < bw; xx++) {
          const i = ((by + yy) * w + bx + xx) * 4;
          d[i] = r; d[i + 1] = g; d[i + 2] = b;
        }
      }
    }
  }
  ieCtx.putImageData(img, x0, y0);
}

function ieStroke(a, b) {
  ieCtx.strokeStyle = ieColor;
  ieCtx.lineWidth = Math.max(3, ieBrush / 3);
  ieCtx.lineCap = 'round'; ieCtx.lineJoin = 'round';
  ieCtx.beginPath(); ieCtx.moveTo(a.x, a.y); ieCtx.lineTo(b.x, b.y); ieCtx.stroke();
}

/* ---- 裁剪框 ---- */
function ieDrawCrop() {
  const box = $('#ie-crop');
  if (!ieDrag || ieDrag.mode !== 'crop') { box.classList.add('hidden'); return; }
  const r = ieCv.getBoundingClientRect(), sr = $('#ie-stage').getBoundingClientRect();
  const k = r.width / ieCv.width;
  box.classList.remove('hidden');
  box.style.left = Math.min(ieDrag.x0, ieDrag.x1) * k + (r.left - sr.left) + 'px';
  box.style.top = Math.min(ieDrag.y0, ieDrag.y1) * k + (r.top - sr.top) + 'px';
  box.style.width = Math.abs(ieDrag.x1 - ieDrag.x0) * k + 'px';
  box.style.height = Math.abs(ieDrag.y1 - ieDrag.y0) * k + 'px';
  $('#ie-cropact').classList.remove('hidden');
  ieSay('框了 ' + Math.round(Math.abs(ieDrag.x1 - ieDrag.x0)) + ' × '
        + Math.round(Math.abs(ieDrag.y1 - ieDrag.y0)) + '，点「裁掉框外」');
}
function ieClearCrop() {
  ieDrag = null;
  $('#ie-crop').classList.add('hidden');
  $('#ie-cropact').classList.add('hidden');
}
function ieDoCrop() {
  if (!ieDrag || ieDrag.mode !== 'crop') { ieSay('先在图上拖一个框'); return; }
  const x = Math.round(Math.min(ieDrag.x0, ieDrag.x1)), y = Math.round(Math.min(ieDrag.y0, ieDrag.y1));
  const w = Math.round(Math.abs(ieDrag.x1 - ieDrag.x0)), h = Math.round(Math.abs(ieDrag.y1 - ieDrag.y0));
  if (w < 8 || h < 8) { ieSay('框太小了，重新拖一个'); return; }
  iePushUndo();
  const { cv: c, g } = ieNewCv(w, h);
  g.drawImage(ieCv, x, y, w, h, 0, 0, w, h);
  iePaste(c);
  ieClearCrop();
  ieSay('裁好了');
}

/* ---- 工具切换 ---- */
function ieSetTool(t) {
  ieTool = (ieTool === t) ? '' : t;
  ieClearCrop();
  document.querySelectorAll('#ie-bar [data-ietool]').forEach(b =>
    b.classList.toggle('primary', b.dataset.ietool === ieTool));
  $('#ie-cv').className = ieTool === 'crop' ? 'ie-crosshair' : (ieTool ? 'ie-cell' : '');
  $('#ie-colors').classList.toggle('hidden', ieTool !== 'paint');
  $('#ie-sizewrap').classList.toggle('hidden', ieTool === 'crop' || !ieTool);
  ieSay(ieTool === 'crop' ? '在图上拖一个框，框里是要留下的部分'
    : ieTool === 'mosaic' ? '在要遮住的地方拖动，像素会被就地打散'
      : ieTool === 'paint' ? '按住拖动就是一笔' : '选一个工具开始');
}

/* ---- 保存 ---- */
function ieBlob() {
  // 输出格式跟着原图走：JPEG 存 JPEG，其余一律 PNG（保住透明底，也不给 bmp 那种大家伙）
  const jpg = ieExt === '.jpg' || ieExt === '.jpeg';
  return new Promise(res => ieCv.toBlob(res, jpg ? 'image/jpeg' : 'image/png',
                                        jpg ? IE_JPEG_Q : undefined));
}
function ieOutName() {
  const jpg = ieExt === '.jpg' || ieExt === '.jpeg';
  const base = ieName.replace(/\.[^.]+$/, '');
  return base + '-编辑' + (jpg ? ieExt : '.png');
}

async function ieSave() {
  const blob = await ieBlob();
  if (!blob) { toast('这张图存不出来，换个格式试试', true); return; }
  const canOverwrite = !!(ieSrc && ieSrc.kind === 'drive');
  /* 默认另存 —— 证件材料改坏了没处找回。覆盖是那个**要多点一下**的选项，
     而且只对云盘里自己的图给：别人在聊天里发来的、共享进来的，都不该被就地改掉。 */
  const ans = await appConfirm(
    canOverwrite
      ? '存成新文件（' + ieOutName() + '），还是直接覆盖原图？'
      : '这张图会存到云盘的「图片编辑」文件夹，原图不动。',
    { title: '保存编辑结果', okText: '另存为副本',
      altText: canOverwrite ? '覆盖原图' : '', cancelText: '再改改' });
  if (!ans) return;
  try {
    if (ans === 'alt') {
      if (!(await appConfirm('覆盖之后原来那张就找不回来了（回收站里也没有，因为动的是文件内容）。确定？',
                             { title: '覆盖原图', okText: '确定覆盖', cancelText: '算了' }))) return;
      await ieUpload('/api/drive/' + ieSrc.id + '/replace', blob);
      toast('已覆盖原图');
      ieClose();
      ieRefreshViewer();
      return;
    }
    const row = canOverwrite
      ? await ieUpload('/api/drive/' + ieSrc.id + '/saveas?name=' + encodeURIComponent(ieOutName()), blob)
      : await ieUploadCopy(blob);
    ieClose();
    const where = '云盘/' + (row.folder ? row.folder + '/' : '') + row.name;
    /* 存完把落点摆在明面上，并且给一条过去的路。
       **不自动跳** —— 人正看着这张图呢，存个副本就被弹到另一个目录是把人赶走。 */
    if (await appConfirm('已存到 ' + where,
                         { title: '保存好了', okText: '去看看', cancelText: '知道了' })) {
      dvJump(row.folder || '');
    }
  } catch (e) {
    toast(errMsg(e), true);
  }
}

/* 覆盖之后查看器里挂的还是浏览器缓存里那张老图（URL 一个字没变，它不会去重取）。
   加个时间戳把它逼着重新拉一次，否则用户会以为「覆盖没生效」。 */
function ieRefreshViewer() {
  const im = $('#viewer-img img');
  if (!im || !viewerImg) return;
  const url = viewerImg.url + (viewerImg.url.includes('?') ? '&' : '?') + 't=' + Date.now();
  viewerImg.url = url;
  im.src = url;
}

function ieUpload(url, blob) {
  return api(url, { method: 'POST', headers: { 'Content-Type': blob.type }, body: blob });
}
// 别处来的图（聊天、知识库、小记、资料库）：云盘是这个应用的文件总仓库，统一落到这儿
const IE_COPY_DIR = '图片编辑';
function ieUploadCopy(blob) {
  const fd = new FormData();
  fd.append('file', new File([blob], ieOutName(), { type: blob.type }));
  fd.append('folder', IE_COPY_DIR);
  return api('/api/drive', { method: 'POST', body: fd });
}

/* ---- 事件 ---- */
/* 「编辑」按钮归本文件管：它和这个按钮在同一个延后包里，绑上的那一刻功能一定是齐的。
   viewerImg 由 materials.js 在打开图片时填（顶层 let 跨 <script> 可见）。 */
$('#viewer-edit').onclick = () => {
  if (viewerImg) openImgEdit(viewerImg.url, viewerImg.name, viewerImg.ext, viewerImg.src);
};

$('#ie-bar').addEventListener('click', async (e) => {
  const t = e.target.closest('[data-ietool]');
  if (t) { ieSetTool(t.dataset.ietool); return; }
  const d = e.target.closest('[data-ie]');
  if (!d) return;
  switch (d.dataset.ie) {
    case 'rotl': ieRotate(-1); break;
    case 'rotr': ieRotate(1); break;
    case 'flip': ieFlip(); break;
    case 'undo': {
      const prev = ieUndo.pop();
      if (prev) { iePaste(prev); ieClearCrop(); ieSay('退回一步'); }
      $('#ie-undo').disabled = !ieUndo.length;
      break;
    }
    case 'reset':
      if (ieOrigin) { iePushUndo(); iePaste(ieOrigin); ieClearCrop(); ieSay('回到最初那张'); }
      break;
    case 'cancel':
      if (!ieUndo.length || await appConfirm('改的这些不保存了？', { title: '退出编辑', okText: '不保存', cancelText: '继续改' })) ieClose();
      break;
    case 'save': ieSave(); break;
  }
});

$('#ie-cropact').addEventListener('click', (e) => {
  const d = e.target.closest('[data-ie]');
  if (!d) return;
  if (d.dataset.ie === 'docrop') ieDoCrop();
  if (d.dataset.ie === 'uncrop') { ieClearCrop(); ieSay('重新拖一个框'); }
});

$('#ie-size').addEventListener('input', e => { ieBrush = +e.target.value; });
$('#ie-colors').addEventListener('click', e => {
  const b = e.target.closest('[data-iecolor]');
  if (!b) return;
  ieColor = b.dataset.iecolor;
  document.querySelectorAll('[data-iecolor]').forEach(x =>
    x.setAttribute('aria-pressed', String(x === b)));
});

(function ieBindStage() {
  const cv = $('#ie-cv');
  if (!cv) return;
  cv.addEventListener('pointerdown', (e) => {
    if (!ieTool) { ieSay('先选一个工具：裁剪 / 马赛克 / 涂抹'); return; }
    cv.setPointerCapture(e.pointerId);
    const p = ieAt(e);
    if (ieTool === 'crop') {
      ieDrag = { mode: 'crop', x0: p.x, y0: p.y, x1: p.x, y1: p.y };
      ieDrawCrop();
      return;
    }
    iePushUndo();                       // 一笔算一步，松手前的连续移动不再压栈
    ieDrag = { mode: ieTool, last: p };
    if (ieTool === 'mosaic') ieMosaicAt(p.x, p.y); else ieStroke(p, p);
  });
  cv.addEventListener('pointermove', (e) => {
    if (!ieDrag) return;
    e.preventDefault();
    const p = ieAt(e);
    if (ieDrag.mode === 'crop') { ieDrag.x1 = p.x; ieDrag.y1 = p.y; ieDrawCrop(); return; }
    if (ieDrag.mode === 'mosaic') {
      // 沿途补点：拖快了才不会留下一串断续的格子
      const dist = Math.hypot(p.x - ieDrag.last.x, p.y - ieDrag.last.y);
      const n = Math.max(1, Math.round(dist / Math.max(4, ieBrush / 3)));
      for (let i = 1; i <= n; i++) {
        ieMosaicAt(ieDrag.last.x + (p.x - ieDrag.last.x) * i / n,
                   ieDrag.last.y + (p.y - ieDrag.last.y) * i / n);
      }
    } else {
      ieStroke(ieDrag.last, p);
    }
    ieDrag.last = p;
  });
  const end = () => { if (ieDrag && ieDrag.mode !== 'crop') ieDrag = null; };
  cv.addEventListener('pointerup', end);
  cv.addEventListener('pointercancel', end);
})();
