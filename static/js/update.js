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
      try { GongkaoNative.updateApp(location.origin + d.url); }
      catch (_) { toast('更新失败，请到浏览器下载', true); }
    },
  });
}

async function checkDesktopUpdate(manual) {
  let d;
  try { d = await api('/api/desktop/version'); } catch (_) { if (manual) toast('检查更新失败', true); return; }
  const cur = parseInt(DESKTOP_VER.replace(/\./g, ''), 10) || 0;    // "3.2" → 32

  // ① 桌面壳本身有新版 → 必须重新下载安装包
  if (d.deb_available && d.deb_code > cur) {
    const key = 'deb' + d.deb_code;
    if (!manual && lsGet('skipUpdate') === key) return;
    updModal({
      title: '发现桌面版新版本', ver: 'v' + (d.deb_name || d.deb_code),
      notes: (d.deb_notes || '优化体验。') + '\n这次改动涉及桌面客户端本身，需要重新下载安装包更新。',
      size: pkgSize(d.deb_size), btn: '下载更新', key,
      onGo: () => {
        toast('开始下载…完成后按提示安装');
        const a = document.createElement('a');
        a.href = d.deb_url; a.download = 'gongkao.deb';
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
$('#acct-update').onclick = () => checkUpdate(true);
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
  if (!/\.deb$/i.test(path || '')) return;
  appConfirm(
    '已保存到：' + path + '\n\n双击它用「软件安装器」打开即可完成更新，'
    + '或在终端执行：sudo dpkg -i "' + path + '"\n装好后重新打开公考助手就是新版。',
    { title: '更新包已下载完成', okText: '知道了' });
};
