/* 公考助手 Windows 桌面版（Electron 壳，加载网页版）。
 *
 * 和 Linux 那个 GTK 壳（../gongkao_native.py）是同一个东西的两种做法：
 * 一个真·原生窗口 + 一个 WebView 加载网页版，壳只负责系统那一半（托盘、通知、
 * 下载、剪贴板、外链）。**桥的方言也刻意保持一致**（见 preload.js），网页端不用改。
 *
 * 引擎差异带来的好消息：Windows 这边是 Chromium，Linux 壳里补 WebKit 的那一堆坑
 * （拖放拿不到文件、粘不进图、没有 speechSynthesis、clipboard.write 被拒）在这里
 * 统统不存在，网页照常走浏览器那条路即可 —— 所以这份文件比 GTK 那份短得多。
 */
const { app, BaseWindow, BrowserWindow, WebContentsView, session, shell, ipcMain,
        clipboard, nativeImage, Menu, Tray, dialog } = require('electron');
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const https = require('https');
const net = require('net');
const dns = require('dns');
const log = require('./log');
const files = require('./files')({ log, js, toast, getWin: () => win });
const shot = require('./shot')({ log, js, toast });

const SHELL_VER = '6.3';          // 壳版本。⚠️ 与 Linux 壳（DESKTOP_VER）共用同一条数字线：
                                  // 网页里 parseFloat(DESKTOP_VER) >= x 的特性闸门是跨平台比的，
                                  // 从 1.0 起步会被当成老版本，功能被悄悄关掉。
const TUNNEL = 'https://gk.gongkaopei2026.click';
const LOCAL = 'http://127.0.0.1:8011';
const TITLEBAR_H = 34;            // 和 GTK 壳的 HeaderBar 一样高，看着是一条和网页顶栏同色的细条
const IS_WIN = process.platform === 'win32';

// 用户数据目录固定成 ASCII 名：productName 是中文，不定的话会变成 %APPDATA%\公考助手，
// 让人贴日志路径、命令行进目录都别扭。
app.setPath('userData', path.join(app.getPath('appData'), 'gongkao-assistant'));
app.setAppUserModelId('com.gongkao.app');   // Windows 通知/任务栏归组要靠它

const CONFIG = path.join(app.getPath('userData'), 'config.json');

/* 局域网地址是 http 的，浏览器默认把它当「不安全上下文」：Notification、
   crypto.subtle（云盘秒传要用）、Service Worker 全部关掉 —— 换成局域网就等于
   把这些功能一起关了。这个开关告诉 Chromium「这个来源按安全的算」。
   ⚠️ 必须在 app ready **之前**声明，所以这里同步读一次配置；也因此换完地址要重启应用。 */
(function declareSecureOrigin() {
  let u = '';
  try { u = (JSON.parse(fs.readFileSync(CONFIG, 'utf8')).server || '').trim(); } catch (_) { return; }
  if (!/^http:\/\//i.test(u)) return;
  try {
    const o = new URL(u);
    if (o.hostname === 'localhost' || o.hostname === '127.0.0.1') return;   // 本机本来就算安全来源
    app.commandLine.appendSwitch('unsafely-treat-insecure-origin-as-secure', o.origin);
    app.commandLine.appendSwitch('enable-features', 'OverridePrefsForHttpAndHttpsOrigins');
  } catch (_) { /* 地址不合法就当没配 */ }
})();
// 六个时段的图标，锚点时刻与 static/js/daylight.js 的 DL_KEYS 一致。
// 网页那套是连续插值，图标是文件、只能挑最近的一张（GTK 壳同理）。
const ICON_PHASES = [[5.0, 'dawn'], [8.0, 'morning'], [13.0, 'day'],
                     [18.0, 'dusk'], [20.5, 'evening'], [23.0, 'night']];
let win = null;
let tray = null;
let appView = null;
let titleView = null;
let target = { url: TUNNEL, from: '默认' };
let quitting = false;       // 退出过程中渲染进程「正常消失」不是崩溃，见 render-process-gone
let errShown = false;       // 兜底页只显示一次：它自己加载失败会再次触发，不拦就是死循环

/* ============================ 时段图标 ============================ */
function phase(now = new Date()) {
  const h = now.getHours() + now.getMinutes() / 60;
  let name = ICON_PHASES[ICON_PHASES.length - 1][1];   // 0~5 点绕回「夜」
  for (const [start, n] of ICON_PHASES) if (h >= start) name = n;
  return name;
}

/* 打好包的时候图标在 resources/icons/，开发时直接用仓库里的 static/icons/ */
function iconFile(size = 512) {
  const dirs = [path.join(process.resourcesPath || '', 'icons'),
                path.join(__dirname, '..', '..', 'static', 'icons')];
  for (const d of dirs) {
    const p = path.join(d, `gk-${phase()}-${size}.png`);
    if (fs.existsSync(p)) return p;
  }
  return '';
}

function iconImage(px) {
  const f = iconFile(px > 64 ? 512 : 192);
  if (!f) return null;
  // 托盘要的是 16/32 的小图，直接塞 512 会糊成一团
  return nativeImage.createFromPath(f).resize({ width: px, height: px });
}

/* ============================ 服务器地址 ============================ */
function readConfig() {
  try { return JSON.parse(fs.readFileSync(CONFIG, 'utf8')); } catch (_) { return {}; }
}
function writeConfig(o) {
  try { fs.writeFileSync(CONFIG, JSON.stringify(o, null, 2)); } catch (e) { log.warn('cfg', '写配置失败', String(e)); }
}

/* 本机在跑服务就用 localhost（快得多），否则走公网隧道。
   Windows 端多半是另一台机器，这条探测基本都会落空 —— 留着是为了「服务端那台机器自己也想用」。 */
function probe(url, ms = 1500) {
  return new Promise((resolve) => {
    const lib = url.startsWith('https') ? https : http;
    const req = lib.get(url, { timeout: ms }, (res) => { res.destroy(); resolve(true); });
    req.on('timeout', () => { req.destroy(); resolve(false); });
    req.on('error', () => resolve(false));
  });
}

async function resolveUrl() {
  const arg = (process.argv.find((a) => a.startsWith('--url=')) || '');
  if (arg) return { url: arg.slice(6), from: '命令行 --url' };
  if ((process.env.GONGKAO_URL || '').trim()) return { url: process.env.GONGKAO_URL.trim(), from: '环境变量 GONGKAO_URL' };
  const cfg = readConfig();
  if (cfg.server) return { url: cfg.server, from: '设置里填的服务器地址' };
  if (await probe(LOCAL + '/')) return { url: LOCAL, from: '本机 8011 端口在跑服务' };
  return { url: TUNNEL, from: '公网隧道（默认）' };
}

const hostOf = (u) => { try { return new URL(u).hostname.toLowerCase(); } catch (_) { return ''; } };
function isExternal(url) {
  if (!/^https?:\/\//i.test(url)) return false;
  const h = hostOf(url);
  return !!h && h !== hostOf(target.url) && h !== hostOf(TUNNEL) && h !== '127.0.0.1' && h !== 'localhost';
}

/* ============================ 窗口 ============================ */
function createWindow() {
  const opts = {
    width: 1120, height: 800, minWidth: 900, minHeight: 600,
    backgroundColor: '#ffffff', title: '公考助手', show: false,
  };
  const ico = iconFile(512);
  if (ico) opts.icon = ico;
  // 标题栏和网页顶栏合成一条白色细条（GTK 那边用 HeaderBar + CSS 做的同一件事）。
  // titleBarOverlay 只有 Windows/macOS 支持；Linux 上开了就只剩一个没有按钮的空窗，
  // 所以本机调试时保持普通边框。
  if (IS_WIN) {
    opts.titleBarStyle = 'hidden';
    opts.titleBarOverlay = { color: '#ffffff', symbolColor: '#6b7785', height: TITLEBAR_H };
  }
  win = new BaseWindow(opts);

  const ses = session.fromPartition('persist:gongkao');   // 登录 cookie / localStorage 跨启动保留
  wirePermissions(ses);
  hookDownloads(ses);

  if (IS_WIN) {
    titleView = new WebContentsView();
    titleView.webContents.loadFile(path.join(__dirname, 'titlebar.html'));
    win.contentView.addChildView(titleView);
  }

  appView = new WebContentsView({
    webPreferences: {
      session: ses,
      preload: path.join(__dirname, 'preload.js'),
      sandbox: true,
      contextIsolation: true,
      spellcheck: false,
      // 播放器是「点封面 → 取播放地址 → 再 play()」，中间隔了一次网络请求，
      // 用户手势早过期了；不放开这条会被当成自动播放拦下（GTK 壳里同样处理）。
      autoplayPolicy: 'no-user-gesture-required',
      additionalArguments: ['--gk-flags=' + encodeURIComponent(JSON.stringify({
        ver: SHELL_VER,
        shot: true,         // 截图：desktopCapturer 抓屏 + 框选层，见 shot.js
      }))],
    },
  });
  win.contentView.addChildView(appView);

  layout();
  win.on('resize', layout);
  // ✕ 不真退出：藏起来留在托盘，SSE 还连着、还能收消息弹通知（和 GTK 壳一个脾气）。
  // 真退出走托盘菜单「退出」或 Ctrl+Q。
  win.on('close', (e) => {
    if (quitting || !tray) return;
    e.preventDefault();
    win.hide();
    log.info('tray', '窗口收进托盘');
    hintTray();
  });
  wireWebContents(appView.webContents);

  log.info('nav', '加载', target.url, '（来源：' + target.from + '）');
  goApp();
  win.show();
  setupTray();
  // 图标随时刻走：半小时看一次够了（相邻两个时段最近也隔 2.5 小时）
  setInterval(refreshIcons, 30 * 60 * 1000);
}

/* 主动去加载正片（首次、重试、换服务器）：复位兜底页闸门 */
function goApp() {
  errShown = false;
  appView && appView.webContents.loadURL(target.url);
}

function layout() {
  if (!win) return;
  const b = win.getContentBounds();
  const h = IS_WIN ? TITLEBAR_H : 0;
  if (titleView) titleView.setBounds({ x: 0, y: 0, width: b.width, height: h });
  if (appView) appView.setBounds({ x: 0, y: h, width: b.width, height: Math.max(0, b.height - h) });
}

/* ============================ 托盘 ============================ */
function showWindow() {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

let srvWin = null;
function openServerWindow() {
  if (srvWin) { srvWin.focus(); return; }
  srvWin = new BrowserWindow({
    width: 520, height: 470, parent: win || undefined, resizable: false,
    minimizable: false, maximizable: false, title: '服务器地址', autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), sandbox: true, contextIsolation: true },
  });
  srvWin.loadFile(path.join(__dirname, 'server.html'));
  srvWin.on('closed', () => { srvWin = null; });
}

function setupTray() {
  const img = iconImage(32);
  if (!img || img.isEmpty()) {
    // 没图标就不建托盘：托盘图标是空白的话，用户根本找不到它，
    // 关窗后应用就成了「找不回来的后台进程」。这种情况下 ✕ 老老实实退出。
    log.warn('tray', '没找到托盘图标，不建托盘（✕ 会直接退出）');
    return;
  }
  tray = new Tray(img);
  tray.setToolTip('公考助手');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开公考助手', click: showWindow },
    { type: 'separator' },
    { label: '更换服务器地址…', click: openServerWindow },
    { label: '打开日志文件夹', click: () => shell.openPath(log.logDir()) },
    { type: 'separator' },
    { label: '退出', click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on('click', () => (win && win.isVisible() && win.isFocused() ? win.hide() : showWindow()));
  lastPhase = phase();          // 起步时的图标已经是对的，别让第一次巡检白换一遍
  log.info('tray', '托盘就绪', phase());
}

/* 第一次收进托盘时说一声。不说的话，人点了 ✕ 会以为程序退了，
   下次再点图标发现「怎么开着」，或者干脆以为卡住了。 */
function hintTray() {
  const cfg = readConfig();
  if (cfg.trayHinted || !IS_WIN || !tray) return;
  cfg.trayHinted = true; writeConfig(cfg);
  try {
    tray.displayBalloon({
      icon: iconImage(64),
      title: '公考助手还在后台运行',
      content: '关掉窗口不会退出，新消息照样提醒。要真退出：右键托盘图标 →「退出」。',
    });
  } catch (e) { log.warn('tray', '气泡提示弹不出来', String(e)); }
}

let lastPhase = '';
function refreshIcons() {
  const ph = phase();
  if (ph === lastPhase) return;
  lastPhase = ph;
  const f = iconFile(512);
  try {
    if (tray) tray.setImage(iconImage(32));
    if (win && f) win.setIcon(f);
    log.info('icon', '换到时段图标', ph);
  } catch (e) { log.warn('icon', '换图标失败', String(e)); }
}

/* ============================ 网页事件 ============================ */
function wireWebContents(wc) {
  // 外链交给系统浏览器，App 只停在自己的站。
  // target="_blank" 走 setWindowOpenHandler 这一路 —— 不接管的话点了就是没反应。
  wc.setWindowOpenHandler(({ url }) => {
    if (isExternal(url)) {
      log.info('link', '外链 → 系统浏览器', url);
      shell.openExternal(url);
    } else {
      log.info('link', '站内 _blank → 当前窗口', url);
      wc.loadURL(url);      // 站内的 _blank（导出的 PDF 预览之类）别丢掉
    }
    return { action: 'deny' };
  });
  wc.on('will-navigate', (e, url) => {
    if (!isExternal(url)) return;
    e.preventDefault();
    log.info('link', '外链 → 系统浏览器', url);
    shell.openExternal(url);
  });

  let t0 = Date.now();
  wc.on('did-start-navigation', (e, url, isInPlace, isMainFrame) => {
    if (isMainFrame) { t0 = Date.now(); log.info('nav', '开始', url); }
  });
  wc.on('did-finish-load', () => {
    log.info('nav', '完成', wc.getURL(), (Date.now() - t0) + 'ms');
    // 每次加载完记一行「桥还在不在」：注入失败时页面表现是「功能莫名其妙没了」，
    // 不打这行的话排障要靠猜。
    wc.executeJavaScript(`JSON.stringify({
      标题: document.title, 桥: !!(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.gk),
      桌面标志: !!window.__desktop, 版本: window.__desktopVer || '', 平台: window.__desktopPlat || '',
      通知权限: (window.Notification && Notification.permission) || '无',
      安全上下文: !!window.isSecureContext,
      通知钩子: !!(window.Notification && window.Notification.name === 'GK') })`, true)
      .then((r) => log.info('page', '自检 ' + r))
      .catch((e) => log.warn('page', '自检失败', String(e)));
  });
  wc.on('did-fail-load', (e, code, desc, url, isMainFrame) => {
    if (!isMainFrame || code === -3) return;    // -3 = ABORTED，页面自己跳走了，不是错
    log.error('nav', '失败', code, desc, url);
    showError({ code, desc, url });
  });
  // 白屏的头号元凶，必须记下来
  wc.on('render-process-gone', (e, d) => {
    const reason = (d && d.reason) || '未知';
    // 关窗/退出时也会走这里（reason=clean-exit）。当成崩溃去弹兜底页的话，
    // 兜底页自己又起不来（进程正在拆），再触发一次 —— 实测会连着刷屏。
    if (quitting || reason === 'clean-exit') {
      log.info('crash', '渲染进程正常退出', reason);
      return;
    }
    log.error('crash', '渲染进程没了', reason, 'exitCode=' + (d && d.exitCode));
    showError({ code: 'RENDER_GONE', desc: '网页进程崩溃：' + reason, url: wc.getURL() });
  });
  wc.on('unresponsive', () => log.warn('crash', '页面无响应'));
  wc.on('responsive', () => log.info('crash', '页面恢复响应'));

  // 网页里的每条 console 都落盘：toast 上那句「xxx失败」背后的真错误在这儿。
  wc.on('console-message', (...args) => {
    const d = (args[0] && typeof args[0] === 'object' && 'message' in args[0]) ? args[0] : null;
    const level = d ? d.level : args[1];
    const msg = d ? d.message : args[2];
    const line = d ? d.lineNumber : args[3];
    const src = d ? d.sourceId : args[4];
    // Electron 自己那条 CSP 安全警告只在没打包时出现，十来行一条，会把日志冲没
    if (String(msg).includes('Electron Security Warning')) return;
    const lv = (level === 'error' || level === 3) ? 'error' : (level === 'warning' || level === 2) ? 'warn' : 'info';
    log[lv]('page', `${msg}  @${String(src || '').split('/').pop()}:${line || 0}`);
  });

  wc.on('before-input-event', (e, input) => onKey(e, input, wc));
}

function onKey(e, input, wc) {
  if (input.type !== 'keyDown') return;
  const k = (input.key || '').toLowerCase();
  const ctrl = input.control || input.meta;
  if (k === 'f5' || (ctrl && k === 'r')) {
    e.preventDefault();
    if (input.shift) wc.reloadIgnoringCache(); else wc.reload();
    return;
  }
  if (!ctrl) return;
  if (k === 'q') { e.preventDefault(); app.quit(); }
  else if (k === '=' || k === '+') { e.preventDefault(); wc.setZoomFactor(Math.min(3, wc.getZoomFactor() + 0.1)); }
  else if (k === '-') { e.preventDefault(); wc.setZoomFactor(Math.max(0.4, wc.getZoomFactor() - 0.1)); }
  else if (k === '0') { e.preventDefault(); wc.setZoomFactor(1); }
  else if (input.shift && k === 'l') { e.preventDefault(); shell.openPath(log.logDir()); }   // 一键开日志目录
  else if (input.shift && k === 'i') { e.preventDefault(); wc.toggleDevTools(); }            // 发布版也留着，排障用
}

/* ============================ 出错兜底页 ============================ */
function showError(info) {
  if (!appView || quitting || errShown) return;
  errShown = true;
  appView.webContents.loadFile(path.join(__dirname, 'error.html'), {
    query: { code: String(info.code), desc: String(info.desc || ''), url: String(info.url || target.url) },
  }).catch((e) => log.error('err', '兜底页都加载不出来', String(e)));
}

/* ============================ 下载 ============================ */
/* 网页要权限时的答复。
   ⚠️ 两个 handler 都得给：请求（异步弹窗那条）走 RequestHandler，
   而 Notification.permission 这个**同步 getter** 走的是 CheckHandler ——
   只实现前者的话，网页读到的权限永远是 default，一条通知也发不出去。 */
function wirePermissions(ses) {
  const ALLOW = new Set(['notifications', 'clipboard-read', 'clipboard-sanitized-write',
                         'fullscreen', 'media', 'pointerLock']);
  ses.setPermissionRequestHandler((wc, permission, cb) => {
    const ok = ALLOW.has(permission) && !isExternal(wc.getURL());
    log.info('perm', permission, ok ? '放行' : '拒绝');
    cb(ok);
  });
  ses.setPermissionCheckHandler((wc, permission) => ALLOW.has(permission));
}

function hookDownloads(ses) {
  ses.on('will-download', (e, item) => {
    const dir = app.getPath('downloads');
    // 这次下载是不是「为分享而下」？重定向后 getURL 会变，所以整条链都比一遍
    const key = [item.getURL(), ...(item.getURLChain() || [])].find((u) => shareJobs.has(u));
    const shareName = key ? shareJobs.get(key) : null;
    if (key) shareJobs.delete(key);
    const safe = (shareName || '').replace(/[/\\:*?"<>|]/g, '_').trim();
    let dest = path.join(dir, (shareName ? safe : '') || item.getFilename() || 'download');
    const ext = path.extname(dest); const base = dest.slice(0, dest.length - ext.length);
    for (let i = 1; fs.existsSync(dest); i++) dest = `${base}(${i})${ext}`;   // 不覆盖已存在的文件
    item.setSavePath(dest);
    log.info('dl', '开始', item.getURL(), '→', dest);
    item.once('done', (_e, state) => {
      if (state === 'completed') {
        log.info('dl', '完成', dest);
        if (shareName !== null) {
          shell.showItemInFolder(dest);       // 在资源管理器里选中，拖进微信即可
          toast('已下载并在文件夹中选中：' + path.basename(dest));
          return;                             // 分享不走「更新包下好了」那条提示
        }
        js(`window.__onDownloaded && window.__onDownloaded(${JSON.stringify(dest)})`);
      } else {
        log.error('dl', '失败', state, dest);
        toast('下载失败：' + state);
      }
    });
  });
}

/* ============================ 壳 → 网页 ============================ */
function js(code) {
  if (!appView) return;
  appView.webContents.executeJavaScript(code, true).catch((e) => log.warn('js', '注入失败', String(e)));
}
function toast(msg) {
  js(`window.toast && window.toast(${JSON.stringify(msg)}, true)`);
}

/* ============================ 网页 → 壳 ============================ */
ipcMain.on('gk', (e, raw) => {
  let d = {};
  try { d = JSON.parse(raw); } catch (_) { log.warn('gk', '解析不了的消息', String(raw).slice(0, 120)); return; }
  log.info('gk', d.a || '(无动作)');
  switch (d.a) {
    case 'open':
      if (/^https?:\/\//i.test(d.url || '')) shell.openExternal(d.url);
      else toast('这个链接打不开：' + String(d.url || '').slice(0, 50));
      break;
    case 'present':
      // 网页通知被点了（preload 给 Notification 加的钩子）→ 把窗口调到前台。
      // 渲染进程里的 window.focus() 抬不起原生窗口，只能由主进程来。
      showWindow();
      break;
    case 'copyimg':
      try {
        clipboard.writeImage(nativeImage.createFromDataURL(d.data));
        toast('图片已复制，可以粘贴了');
      } catch (err) { log.error('gk', 'copyimg 失败', String(err)); toast('复制图片失败'); }
      break;
    case 'tts': case 'tts_stop':
      // __desktopTTS 报的是 false，网页应该走 speechSynthesis，走到这儿说明判断有漏
      log.warn('gk', 'Windows 版不该收到 TTS 请求（应走 speechSynthesis）');
      break;
    case 'shot':
      shot.take();
      break;
    case 'pickdir':
      files.pickDir();
      break;
    case 'pastefiles':
      files.pasteFiles();
      break;
    case 'sharefile':
      shareFile(d.url || '', d.name || '');
      break;
    /* 用系统默认程序打开刚下好的那份文件（6.3 起，聊天卡片上的「打开」）。
       只开真实存在的文件：网页传什么过来都不越过这一关。openPath 打不开时会返回
       一句错误（不抛），那就退一步在资源管理器里选中它，人自己挑用什么打开。 */
    case 'openfile': {
      const fp = String(d.path || '');
      if (!fp || !fs.existsSync(fp) || !fs.statSync(fp).isFile()) { toast('文件不在了'); break; }
      shell.openPath(fp).then((err) => {
        if (!err) return;
        log.warn('gk', 'openfile 打不开：' + err);
        toast('没有能打开它的程序，已在文件夹里选中');
        shell.showItemInFolder(fp);
      });
      break;
    }
    case 'batchdone':
      files.ackBatch();           // 网页把这一批收完了 → 放行下一批（背压）
      break;
    default: log.warn('gk', '不认识的动作：' + d.a);
  }
});

/* 分享文件：先下下来，再在资源管理器里选中它。
   Linux 那边能弹「用哪个应用打开」（AppChooser），Windows 没有等价的系统面板 ——
   最接近的是把文件下好、在资源管理器里高亮，人直接拖进微信/邮件即可。
   下载不自己写 HTTP：走 webContents.downloadURL，它共用登录 cookie。 */
const shareJobs = new Map();      // 下载地址 → 文件名，标记「这次下载是为分享而下」

function shareFile(url, name) {
  if (!/^https?:\/\//i.test(url)) { toast('这个文件分享不了：' + url.slice(0, 50)); return; }
  shareJobs.set(url, name || '');
  log.info('share', '准备分享', name, url);
  toast('正在准备…');
  appView && appView.webContents.downloadURL(url);
}

/* 兜底页用的几个口子 */
ipcMain.on('shell:retry', () => {
  log.info('err', '手动重试 →', target.url);
  goApp();
});
ipcMain.on('shell:open-logs', () => shell.openPath(log.logDir()));
ipcMain.on('shell:close-server', () => { if (srvWin) srvWin.close(); });
ipcMain.handle('shell:set-server', (e, url) => {
  const u = String(url || '').trim().replace(/\/+$/, '');
  if (!/^https?:\/\//i.test(u)) return { ok: false, msg: '地址要以 http:// 或 https:// 开头' };
  const cfg = readConfig(); cfg.server = u;
  // 记住手输过的地址，下次在「服务器地址」页当快捷按钮用。
  // 局域网 IP 是各人各样的私事，只留在本机 config.json 里，不写死进代码。
  cfg.recent = [u, ...(cfg.recent || []).filter((x) => x !== u)].slice(0, 3);
  writeConfig(cfg);
  log.info('cfg', '服务器地址改为', u, '→ 重启应用');
  // 重启而不是直接跳转：http 的局域网地址要在启动时声明成安全来源（见 declareSecureOrigin），
  // 不重启的话通知和秒传会莫名其妙地失灵，比慢一点更难查。
  quitting = true;
  app.relaunch();
  app.exit(0);
  return { ok: true };
});
ipcMain.handle('shell:info', () => info());
ipcMain.handle('shell:diag', () => diagnose(target.url));
ipcMain.handle('shell:copy-diag', async () => {
  const d = await diagnose(target.url);
  const text = [
    '=== 公考助手 Windows 版 诊断信息 ===',
    JSON.stringify(info(), null, 2),
    '--- 连通性 ---',
    JSON.stringify(d, null, 2),
    '--- 最近日志 ---',
    log.tail(200),
  ].join('\n');
  clipboard.writeText(text);
  return true;
});

function info() {
  return {
    壳版本: SHELL_VER,
    服务器: target.url,
    最近地址: readConfig().recent || [],
    地址来源: target.from,
    Electron: process.versions.electron,
    Chromium: process.versions.chrome,
    系统: `${os.type()} ${os.release()} ${os.arch()}`,
    日志文件: log.logFile(),
    时间: new Date().toLocaleString('zh-CN'),
  };
}

/* 连不上的时候，把「到底断在哪一层」查清楚：域名解析 → TCP → HTTP。
   一律只报「加载失败」的话，人根本没法判断是自己没网、隧道挂了、还是服务没起。 */
async function diagnose(url) {
  const out = { 域名解析: '—', TCP连接: '—', HTTP响应: '—' };
  let u; try { u = new URL(url); } catch (_) { out.域名解析 = '地址本身不合法：' + url; return out; }
  const port = Number(u.port) || (u.protocol === 'https:' ? 443 : 80);
  out.域名解析 = await new Promise((res) => {
    dns.lookup(u.hostname, (err, addr) => res(err ? '失败：' + err.code : '成功 → ' + addr));
  });
  out.TCP连接 = await new Promise((res) => {
    const s = net.connect({ host: u.hostname, port, timeout: 5000 });
    s.on('connect', () => { s.destroy(); res(`成功（${u.hostname}:${port}）`); });
    s.on('timeout', () => { s.destroy(); res(`超时（${u.hostname}:${port}）`); });
    s.on('error', (err) => res('失败：' + err.code));
  });
  out.HTTP响应 = await new Promise((res) => {
    const lib = u.protocol === 'https:' ? https : http;
    const req = lib.get(url, { timeout: 8000 }, (r) => { r.destroy(); res('HTTP ' + r.statusCode); });
    req.on('timeout', () => { req.destroy(); res('超时'); });
    req.on('error', (err) => res('失败：' + err.code));
  });
  log.info('diag', JSON.stringify(out));
  return out;
}

/* ============================ 生命周期 ============================ */
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {           // 再点一次图标 → 把已开的窗调到前台
    showWindow();
  });

  app.whenReady().then(async () => {
    log.init(path.join(app.getPath('userData'), 'logs'));
    log.info('boot', '='.repeat(60));
    log.info('boot', `公考助手 Windows 版 v${SHELL_VER}`,
      `Electron ${process.versions.electron} / Chromium ${process.versions.chrome}`);
    log.info('boot', `系统 ${os.type()} ${os.release()} ${os.arch()}`);
    log.info('boot', '启动参数', JSON.stringify(process.argv.slice(1)));
    log.info('boot', '数据目录', app.getPath('userData'));
    Menu.setApplicationMenu(null);             // 不要默认菜单栏（按 Alt 会冒出来）
    target = await resolveUrl();
    log.info('boot', '服务器地址', target.url, '（来源：' + target.from + '）');
    createWindow();
  });

  app.on('before-quit', () => { quitting = true; log.info('boot', '退出中'); });
  app.on('certificate-error', (e, wc, url, error) => {
    log.error('tls', '证书有问题', error, url);   // 不放行，只记下来；兜底页会显示
  });
  app.on('window-all-closed', () => app.quit()); // 托盘（关闭不退出）是 P2 的活
  process.on('uncaughtException', (err) => {
    log.error('fatal', String(err && err.stack || err));
    try { dialog.showErrorBox('公考助手出错了', String(err && err.stack || err).slice(0, 2000)); } catch (_) { /* 弹不出框也别再抛 */ }
  });
}
