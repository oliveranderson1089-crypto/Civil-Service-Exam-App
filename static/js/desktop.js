/* 桌面版：拖放 / 粘贴图片（由壳送进来）
 *
 * 由 app.js 按它自己的区段边界切出（原 L10706-10815）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, addDraftFiles, addDraftImages, aiHandleAttach, bindImgDrop, bindImgPaste,
   c, compressImage, crFid, crSendFiles, deskMsg, dvUpload,
   openAI, push, qnAddFiles, qnAddImgs, slUploadPaper, stack,
   toast, uploadDropped */

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
