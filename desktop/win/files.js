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
const crypto = require('crypto');
const { dialog, clipboard } = require('electron');

const MAX_FILE = 64 * 1024 * 1024;         // 比这大的不走这座 base64 的桥
const BATCH = 6 * 1024 * 1024;             // 一批最多这么多原始字节（base64 还会再涨 1/3）
const ACK_TIMEOUT = 300 * 1000;            // 等网页回执的上限，超了就往下走，别卡死整次上传
/* 比 MAX_FILE 还大的以前直接跳过，于是桌面版里的大文件一个都传不上去。现在改走
   「网页按需向壳要一片」的分片通道（sendBig）：字节留在本地，网页要第几片才读第几片，
   上限因此跟云盘那条分片通道对齐 —— 2GB。协议见 static/js/desktop.js 里那段注释，
   和 Linux 壳（gongkao_native.py 的 _send_big/_big_read）逐字一致。 */
const BIG_MAX = 2 * 1024 * 1024 * 1024;
const PART_MAX = 16 * 1024 * 1024;         // 网页要得再多也不给
const BIG_IDLE = 300 * 1000;               // 这么久没来要下一片就当它死了（传 2GB 本身可以很久）

module.exports = ({ log, js, toast, getWin }) => {
  let pumping = false;
  let ack = null;
  /* 大文件通道：token → 绝对路径。**只认这里登记过的 token** —— 网页永远拿不到、
     也给不了一个任意路径，读盘范围锁死在用户自己拖进来的那几个文件上。 */
  const bigs = new Map();
  let bigAck = null;
  let bigLast = 0;

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
    let batch = []; let size = 0; const skipped = []; const bigList = [];
    for (const it of items) {
      let st;
      try { st = await fs.promises.stat(it.abs); } catch (_) { skipped.push(path.basename(it.abs)); continue; }
      if (st.size > MAX_FILE) {
        // 大文件不再跳过：攒起来，等这批小的走完再一个一个走分片通道
        if (st.size <= BIG_MAX) bigList.push({ abs: it.abs, rel: it.rel, size: st.size, mtime: st.mtimeMs });
        else skipped.push(path.basename(it.abs));
        continue;
      }
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
      toast(`${skipped.length} 个文件超过 2GB 没传（${skipped[0].slice(0, 20)}…）`);
    }
    // 大的放在最后：小文件先落地，用户能立刻看见东西，而不是对着一个几百 MB 的进度条干等
    for (const b of bigList) await sendBig(b, intent);
  }

  /* ---- 大文件：网页按需向壳要一片 ---- */

  /* 推「名字 + 大小 + 一个 token」给网页，字节留在本地，等它传完（或没动静了）再返回。
     老网页没有 __onBigFile（壳更新了、页面还是缓存里的旧版），让它当场回一句 ok=0，
     别让壳在这儿干等到静默超时。 */
  function sendBig(b, intent) {
    const token = crypto.randomBytes(16).toString('hex');
    bigs.set(token, b.abs);
    bigLast = Date.now();
    const meta = { token, name: path.basename(b.abs), rel: b.rel === '.' ? '' : b.rel,
                   size: b.size, mtime: Math.round(b.mtime || 0) };
    return new Promise((resolve) => {
      let over = false;
      const fin = () => {
        if (over) return;
        over = true; bigAck = null; bigs.delete(token); clearInterval(timer); resolve();
      };
      bigAck = fin;
      /* 传 2GB 本身就要很久，不能拿一个固定的总时长当超时。看的是「还有没有在要片」：
         网页每要一片就刷新 bigLast，静默超过 BIG_IDLE 才算它死了。 */
      const timer = setInterval(() => {
        if (Date.now() - bigLast <= BIG_IDLE) return;
        toast(`「${meta.name.slice(0, 20)}」传得没动静了，跳过`);
        fin();
      }, 15 * 1000);
      js(`(window.__onBigFile ? window.__onBigFile(${JSON.stringify(meta)}, ${JSON.stringify(intent)})`
        + ` : window.webkit.messageHandlers.gk.postMessage(JSON.stringify(`
        + `{a:'bigdone', token:${JSON.stringify(token)}, ok:0, old:1})))`);
    });
  }

  /* 网页要第 [start, start+len) 段 → 读盘 → base64 送回去。
     读盘一律走 fs.promises（线程池），别用同步版把主进程钉死。 */
  async function bigPart(d) {
    const seq = Number(d.seq) || 0;
    const start = Math.max(0, Number(d.start) || 0);
    const len = Math.min(Math.max(0, Number(d.len) || 0), PART_MAX);
    const abs = bigs.get(String(d.token || ''));
    bigLast = Date.now();
    let fh = null;
    try {
      if (!abs) throw new Error('这份文件已经不在这次上传里了');
      fh = await fs.promises.open(abs, 'r');
      const buf = Buffer.alloc(len);
      const { bytesRead } = await fh.read(buf, 0, len, start);
      js(`window.__deskBigPart && window.__deskBigPart(${seq}, ${JSON.stringify(buf.subarray(0, bytesRead).toString('base64'))})`);
    } catch (e) {
      log.warn('files', '读不了这一片', String(e));
      js(`window.__deskBigFail && window.__deskBigFail(${seq}, ${JSON.stringify('读文件失败：' + String(e && e.message || e))})`);
    } finally {
      if (fh) await fh.close().catch(() => {});
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

  return {
    pickDir, pasteFiles, sendPaths,
    ackBatch: () => { if (ack) ack(); },
    bigPart,
    ackBig: (d) => {
      if (d && d.old) toast('网页版本太旧，传不了大文件（关掉应用重开一次）');
      if (bigAck) bigAck();
    },
  };
};
