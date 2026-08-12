/* 网页 ⇄ 壳 的桥。
 *
 * ⚠️ 这里刻意**冒充 Linux 桌面版（WebKitGTK）的那套方言**：注入同样的 window.__desktop*
 * 标志，并伪造一个 window.webkit.messageHandlers.gk.postMessage。网页端 static/js/ 里
 * 已经写好的 9 处 __desktop 判断、5 处 messageHandlers.gk 调用因此一行都不用改。
 * 壳 → 网页 的方向仍旧是主进程 executeJavaScript 调 window.__onXxx / __ttsEnd。
 *
 * 别把这里改成「Windows 专用的新桥」——那等于让前端维护第三套方言。
 */
const { contextBridge, ipcRenderer, webFrame } = require('electron');

/* 标志由主进程通过 additionalArguments 传进来（sandbox 模式下 preload 拿不到别的通道）。
   注入时机等价于 WebKit 的 InjectionTime.START：页面脚本跑之前就位。 */
const raw = (process.argv.find((a) => a.startsWith('--gk-flags=')) || '').slice(11);
let flags = {};
try { flags = JSON.parse(decodeURIComponent(raw)); } catch (_) { flags = {}; }

contextBridge.exposeInMainWorld('__desktop', true);
contextBridge.exposeInMainWorld('__desktopVer', String(flags.ver || ''));
contextBridge.exposeInMainWorld('__desktopPlat', 'win');       // 更新检查据此区分 deb / exe
// Chromium 自带 speechSynthesis（Windows 有中文 SAPI 音色），朗读**不该**走壳：
// 报 false，tts.js 就会自己回退到 speechSynthesis 那条分支。
contextBridge.exposeInMainWorld('__desktopTTS', false);
contextBridge.exposeInMainWorld('__ttsEngines', []);
contextBridge.exposeInMainWorld('__desktopShot', !!flags.shot);

contextBridge.exposeInMainWorld('webkit', {
  messageHandlers: {
    gk: { postMessage: (s) => ipcRenderer.send('gk', String(s)) },
  },
});

/* 出错兜底页 error.html 用的小 API（普通页面拿到也无害：都是本机操作，不碰数据） */
contextBridge.exposeInMainWorld('__gkShell', {
  retry: () => ipcRenderer.send('shell:retry'),
  openLogs: () => ipcRenderer.send('shell:open-logs'),
  setServer: (u) => ipcRenderer.invoke('shell:set-server', u),
  closeServer: () => ipcRenderer.send('shell:close-server'),
  copyDiag: () => ipcRenderer.invoke('shell:copy-diag'),
  diag: () => ipcRenderer.invoke('shell:diag'),
  info: () => ipcRenderer.invoke('shell:info'),
});

/* 点系统通知 → 把窗口调到前台。
 *
 * 网页端（chat.js 的 notifyChat）写的是 n.onclick = () => { window.focus(); openChatroom(...) }。
 * 渲染进程里的 window.focus() **抬不起原生窗口**，所以在这儿给 Notification 挂一个额外的
 * click 钩子，通知主进程去 show+focus；网页自己那个 onclick 照常跑（打开对应会话），两不耽误。
 *
 * 用 webFrame.executeJavaScript 是因为 contextIsolation 开着：preload 自己那个世界改
 * window.Notification 网页看不见，必须把补丁打进主世界。
 */
webFrame.executeJavaScript(`(() => {
  const N = window.Notification;
  if (!N) return;
  function GK(title, opts) {
    const n = new N(title, opts);
    n.addEventListener('click', () => {
      try { window.webkit.messageHandlers.gk.postMessage(JSON.stringify({ a: 'present' })); } catch (_) {}
    });
    return n;
  }
  GK.prototype = N.prototype;
  GK.requestPermission = (...a) => N.requestPermission(...a);
  Object.defineProperty(GK, 'permission', { get: () => N.permission });
  Object.defineProperty(GK, 'maxActions', { get: () => N.maxActions });
  window.Notification = GK;
})()`).catch(() => { /* 补丁打不进去只是「点通知不跳窗口」，不该拦住页面 */ });
