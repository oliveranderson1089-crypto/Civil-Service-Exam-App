/* 应用内更新
 *
 * 由 app.js 按它自己的区段边界切出（原 L8440-8549）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, DESKTOP_VER, IN_APP, IS_DESKTOP, api, appConfirm,
   fmtSize, lsGet, lsSet, toast */

/* ================= 应用内更新 =================
   手机(APK)：下载新 APK 并唤起安装。
   电脑(桌面壳)：分两种——
     · 只改了网页 → 不用重下，提示「刷新更新」，点一下就是新版；
     · 改了桌面壳本身 → 必须重下，提示「下载更新」，下好双击装。 */
const pkgSize = (n) => n ? '安装包 ' + fmtSize(n) : '';

function updModal({ title, ver, notes, size, btn, key, onGo }) {
  $('#upd-title').textContent = title;
  $('#upd-ver').textContent = ver || '';
  $('#upd-notes').textContent = notes;
  $('#upd-size').textContent = size || '';
  $('#upd-go').textContent = btn;
  $('#upd-modal').classList.remove('hidden');
  $('#upd-later').onclick = () => {
    if (key) lsSet('skipUpdate', key);   // 这一版说过「以后再说」就别再弹
    $('#upd-modal').classList.add('hidden');
  };
  $('#upd-go').onclick = () => { $('#upd-modal').classList.add('hidden'); onGo(); };
}

let SW_AT_START = '';          // 本次启动时服务器的网页版本；之后变了 = 有前端更新（刷新即可）
let _lastUpdChk = 0;

async function checkApkUpdate(manual) {
  let cur = 0;
  try { cur = GongkaoNative.appVersion(); } catch (_) { return; }
  let d;
  try { d = await api('/api/app/version'); } catch (_) { if (manual) toast('检查更新失败', true); return; }
  if (!d.available || !d.version_code || d.version_code <= cur) {
    if (manual) toast('已是最新版本 (v' + (d.version_name || cur) + ')');
    return;
  }
  const key = 'apk' + d.version_code;
  if (!manual && lsGet('skipUpdate') === key) return;
  updModal({
    title: '发现新版本', ver: 'v' + (d.version_name || d.version_code),
    notes: d.notes || '修复问题、优化体验。', size: pkgSize(d.size),
    btn: '立即更新', key,
    onGo: () => {
      // 壳会把下载进度画到通知栏；App 还开着的时候顺带用 toast 报一下百分比
      try { GongkaoNative.updateApp(location.origin + d.url, 'v' + (d.version_name || d.version_code)); }
      catch (_) {
        try { GongkaoNative.updateApp(location.origin + d.url); }   // 老壳只认单参数
        catch (__) { toast('更新失败，请到浏览器下载', true); }
      }
    },
  });
}

/* 安卓壳下载新版 APK 的进度：0~100，-1 = 失败（壳那边已经弹了 Toast 和通知，别再叠一层）。
   通知栏那条常驻进度条才是主入口——用户多半切走了；这里只是留在 App 里时也看得见。 */
window.__updProgress = (pct) => {
  if (pct < 0) return;
  toast(pct >= 100 ? '下载完成，按提示安装' : '正在下载新版… ' + pct + '%');
};

async function checkDesktopUpdate(manual) {
  let d;
  try { d = await api('/api/desktop/version'); } catch (_) { if (manual) toast('检查更新失败', true); return; }
  const cur = parseInt(DESKTOP_VER.replace(/\./g, ''), 10) || 0;    // "3.2" → 32

  /* 两个桌面端各有各的安装包，按壳注入的平台标志挑一套。
     ⚠️ 服务端的 deb_* 字段没有改名，就是为了让已经装在机器上的老 Linux 壳继续认得。 */
  const isWin = window.__desktopPlat === 'win';
  const pkg = isWin
    ? { avail: d.win_available, code: d.win_code, name: d.win_name, notes: d.win_notes,
        size: d.win_size, url: d.win_url, tag: 'win',
        file: (d.win_url || '').split('/').pop() || 'gongkao-setup.exe' }
    : { avail: d.deb_available, code: d.deb_code, name: d.deb_name, notes: d.deb_notes,
        size: d.deb_size, url: d.deb_url, tag: 'deb', file: 'gongkao.deb' };

  // ① 桌面壳本身有新版 → 必须重新下载安装包
  if (pkg.avail && pkg.code > cur) {
    const key = pkg.tag + pkg.code;          // 跳过标记按平台分开记，别互相盖
    if (!manual && lsGet('skipUpdate') === key) return;
    updModal({
      title: '发现桌面版新版本', ver: 'v' + (pkg.name || pkg.code),
      notes: (pkg.notes || '优化体验。') + '\n这次改动涉及桌面客户端本身，需要重新下载安装包更新。',
      size: pkgSize(pkg.size), btn: '下载更新', key,
      onGo: () => {
        toast('开始下载…完成后按提示安装');
        const a = document.createElement('a');
        a.href = pkg.url; a.download = pkg.file;
        document.body.appendChild(a); a.click(); a.remove();
      },
    });
    return;
  }

  // ② 只有网页内容更新 → 不用重下，刷新就是新版
  if (SW_AT_START && d.sw && d.sw !== SW_AT_START) {
    const key = 'sw' + d.sw;
    if (!manual && lsGet('skipUpdate') === key) return;
    updModal({
      title: '有新内容更新', ver: '',
      notes: '界面/功能已更新，不需要重新下载客户端。点「刷新更新」立即用上新版。',
      size: '', btn: '刷新更新', key,
      onGo: () => location.reload(),
    });
    return;
  }
  if (d.sw && !SW_AT_START) SW_AT_START = d.sw;      // 启动时记下基准
  if (manual) toast('已是最新版本（桌面版 v' + (DESKTOP_VER || '?') + '）');
}

async function checkUpdate(manual) {
  _lastUpdChk = Date.now();
  if (IS_DESKTOP) return checkDesktopUpdate(manual);
  if (window.GongkaoNative && typeof GongkaoNative.appVersion === 'function') return checkApkUpdate(manual);
  if (manual) toast('网页版会自动更新，无需手动升级');
}
/* 网页端的「检查更新」不是查版本号，而是**把离线缓存清干净再重载**。
   sw.js 走的是网络优先，正常情况下不会卡旧版；但缓存里存过一份坏响应、
   或 Service Worker 自己卡在旧版本时，光按刷新是绕不开的，得有这么一个出口。 */
async function webReload() {
  toast('正在清理离线缓存…');
  try {
    if (window.caches && caches.keys) {
      const ks = await caches.keys();
      await Promise.all(ks.map(k => caches.delete(k)));
    }
    if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
      const rs = await navigator.serviceWorker.getRegistrations();
      // 先让它自己更新；更新这条路走不通再注销（注销只丢离线能力，重进就会重新注册）
      await Promise.all(rs.map(r => r.update().catch(() => r.unregister().catch(() => {}))));
    }
  } catch (e) {
    console.warn('[更新] 清离线缓存没成功，直接重载：', e);
  }
  location.reload();
}
$('#acct-update').onclick = () => { if (IS_DESKTOP || IN_APP) checkUpdate(true); else webReload(); };
window.checkUpdate = checkUpdate;

if (IS_DESKTOP || IN_APP) {
  setTimeout(() => checkUpdate(false), 3500);                   // 启动后静默查一次
  setInterval(() => checkUpdate(false), 30 * 60 * 1000);        // 长期开着也能收到更新提示
  document.addEventListener('visibilitychange', () => {         // 切回窗口时再看一眼（限流）
    if (!document.hidden && Date.now() - _lastUpdChk > 10 * 60 * 1000) checkUpdate(false);
  });
}
/* 桌面壳下载完成后回调（更新包下好了 → 告诉用户怎么装） */
window.__onDownloaded = (path) => {
  const p = path || '';
  const tip = { title: '更新包已下载完成', okText: '知道了' };
  if (/\.deb$/i.test(p)) {
    appConfirm(
      '已保存到：' + p + '\n\n双击它用「软件安装器」打开即可完成更新，'
      + '或在终端执行：sudo dpkg -i "' + p + '"\n装好后重新打开公考助手就是新版。', tip);
  } else if (/\.exe$/i.test(p)) {
    appConfirm(
      '已保存到：' + p + '\n\n双击它安装即可完成更新。\n'
      + '首次运行 Windows 可能拦一下（「已保护你的电脑」）——点「更多信息 → 仍要运行」，'
      + '这是没买代码签名证书的正常表现。\n装好后重新打开公考助手就是新版。', tip);
  } else if (/gongkao-win.*\.zip$/i.test(p)) {
    appConfirm(
      '已保存到：' + p + '\n\n这是便携版：解压出来，运行里面的「公考助手.exe」即可。'
      + '\n更新的话，把新解压的目录盖掉旧的就行（登录状态不在目录里，不会丢）。', tip);
  }
};
