/* 选文件夹 / 粘贴文件：把本地文件摊平、分批送进网页。
 *
 * 协议和 Linux 壳（gongkao_native.py 的 _walk/_pump/_push）**完全一致**：
 * 每批是 [{name, rel, data(base64)}]，交给 window.__onPickedFiles(batch, intent)，
 * 网页收完回一句 {a:'batchdone'} 才发下一批。intent：'drive' 是点了「传文件夹」、
 * 'paste' 是粘贴、'' 是拖放（Windows 上拖放走网页自己那条路，不经这里）。
 *
 * 两件事必须做对，否则真实目录（实测「公考」= 497 个文件 / 816MB）会把壳搞死：
 * ① 读盘全用 fs.promises（走线程池），别用同步版把主进程钉死；
 * ② 要有背压 —— 一口气把上百批塞进网页，浏览器那边会同时开一百多个上传，
 *    base64 字符串全堆在内存里。
 */
const fs = require('fs');
const path = require('path');
const { dialog, clipboard } = require('electron');

const MAX_FILE = 64 * 1024 * 1024;         // 比这大的不走这座 base64 的桥
const BATCH = 6 * 1024 * 1024;             // 一批最多这么多原始字节（base64 还会再涨 1/3）
const ACK_TIMEOUT = 300 * 1000;            // 等网页回执的上限，超了就往下走，别卡死整次上传

module.exports = ({ log, js, toast, getWin }) => {
  let pumping = false;
  let ack = null;

  const relOf = (dir, base) => {
    const r = path.relative(base, dir).split(path.sep).join('/');
    return r === '' ? '.' : r;
  };

  async function walk(p, out, base) {
    if (base === undefined) base = path.dirname(p.replace(/[\\/]+$/, ''));
    const st = await fs.promises.stat(p).catch(() => null);
    if (!st) return;
    if (st.isFile()) { out.push({ abs: p, rel: relOf(path.dirname(p), base) }); return; }
    if (!st.isDirectory()) return;
    let ents = [];
    try { ents = await fs.promises.readdir(p, { withFileTypes: true }); } catch (e) {
      log.warn('files', '读不了目录', p, String(e)); return;
    }
    ents = ents.filter((e) => !e.name.startsWith('.')).sort((a, b) => a.name.localeCompare(b.name));
    for (const e of ents) {
      const child = path.join(p, e.name);
      if (e.isDirectory()) await walk(child, out, base);
      else if (e.isFile()) out.push({ abs: child, rel: relOf(p, base) });
    }
  }

  /* 等网页说「这批收完了」。超时返回 false —— 卡住一批不该让后面的永远发不出去。 */
  function waitAck() {
    return new Promise((resolve) => {
      let done = false;
      const fin = (ok) => { if (!done) { done = true; ack = null; resolve(ok); } };
      ack = () => fin(true);
      setTimeout(() => fin(false), ACK_TIMEOUT);
    });
  }

  async function push(batch, intent) {
    js(`window.__onPickedFiles && window.__onPickedFiles(${JSON.stringify(batch)}, ${JSON.stringify(intent)})`);
    if (!(await waitAck())) toast('有一批等太久，继续传后面的');
  }

  async function pump(items, intent) {
    let batch = []; let size = 0; const skipped = [];
    for (const it of items) {
      let st;
      try { st = await fs.promises.stat(it.abs); } catch (_) { skipped.push(path.basename(it.abs)); continue; }
      if (st.size > MAX_FILE) { skipped.push(path.basename(it.abs)); continue; }
      let buf;
      try { buf = await fs.promises.readFile(it.abs); } catch (_) { skipped.push(path.basename(it.abs)); continue; }
      batch.push({
        name: path.basename(it.abs),
        rel: it.rel === '.' ? '' : it.rel,
        data: buf.toString('base64'),
      });
      size += st.size;
      if (size >= BATCH) { await push(batch, intent); batch = []; size = 0; }
    }
    if (batch.length) await push(batch, intent);
    if (skipped.length) {
      // 单个太大的走网页那个「⬆ 上传」按钮更靠谱：那条是分片传的，不经这座桥
      toast(`${skipped.length} 个文件太大没传（${skipped[0].slice(0, 20)}…），用「⬆ 上传」单独传`);
    }
  }

  async function sendPaths(paths, label, intent) {
    if (pumping) { toast('上一批还在传，等它传完再来'); return; }   // 两个 pump 会互相抢回执
    pumping = true;
    if (label) toast(label);
    try {
      const out = [];
      for (const p of paths) await walk(p, out);
      log.info('files', `摊平 ${paths.length} 个路径 → ${out.length} 个文件`, 'intent=' + (intent || '(拖放)'));
      if (!out.length) { toast('这里面没有可上传的文件'); return; }
      await pump(out, intent);
    } catch (e) {
      log.error('files', '传文件出错', String(e && e.stack || e));
      toast('读取文件出错：' + String(e).slice(0, 50));
    } finally {
      pumping = false;
    }
  }

  async function pickDir() {
    const win = getWin();
    const r = await dialog.showOpenDialog(win, {
      title: '选择要上传的文件夹',
      properties: ['openDirectory'],
      buttonLabel: '上传这个文件夹',
    });
    if (r.canceled || !r.filePaths.length) { log.info('files', '选文件夹：取消'); return; }
    const dir = r.filePaths[0];
    await sendPaths([dir], `正在读取「${path.basename(dir)}」…`, 'drive');
  }

  /* 系统剪贴板里复制的**文件**（在资源管理器里 Ctrl+C 的那种）。
     ⚠️ Windows 把多文件放在 CF_HDROP 里，Electron 没把这个格式暴露出来，
     只能读 FileNameW —— 那是个只装得下**一个**路径的老格式。所以多选复制时
     这里只拿得到第一个；多文件请用拖放（Chromium 的 drop 事件是全的）。 */
  function clipboardPaths() {
    const out = [];
    try {
      const s = clipboard.read('FileNameW');
      if (s) out.push(s.replace(/\0/g, ''));
    } catch (_) { /* 这个格式不在剪贴板里，往下试 */ }
    if (!out.length) {
      try {
        const b = clipboard.readBuffer('FileNameW');
        if (b && b.length) out.push(b.toString('ucs2').replace(/\0/g, ''));
      } catch (_) { /* 同上 */ }
    }
    if (!out.length) {
      // Linux/X11 上是 uri-list（本机调试时走这条）
      try {
        const uris = clipboard.read('text/uri-list') || '';
        for (const line of uris.split(/\r?\n/)) {
          if (line.startsWith('file://')) out.push(decodeURIComponent(line.slice(7)));
        }
      } catch (_) { /* 没有就算了 */ }
    }
    return out.filter((p) => p && fs.existsSync(p));
  }

  async function pasteFiles() {
    const paths = clipboardPaths();
    if (paths.length) {
      log.info('files', '剪贴板里有文件', paths.length + ' 个');
      // intent='paste'：网页按「粘贴」的规矩分发（跟着当前页面走，不被侧栏 AI 抢）
      await sendPaths(paths, '正在粘贴…', 'paste');
      return;
    }
    const img = clipboard.readImage();
    if (img && !img.isEmpty()) {
      log.info('files', '剪贴板里是图片');
      js(`window.__onPasteImage && window.__onPasteImage(${JSON.stringify(img.toDataURL())})`);
      return;
    }
    log.info('files', '剪贴板里没有文件也没有图片');
    toast('剪贴板里没有文件或图片');
  }

  return { pickDir, pasteFiles, sendPaths, ackBatch: () => { if (ack) ack(); } };
};
