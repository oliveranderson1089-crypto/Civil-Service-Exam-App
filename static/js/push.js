/* 手机通知栏推送（APK 内由原生定时拉取）
 *
 * 由 app.js 按它自己的区段边界切出（原 L8844-8871）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, toast */

/* ================= 手机通知栏推送（APK 内由原生定时拉取并弹通知） ================= */
function nativeNotify() {
  return window.GongkaoNative && typeof GongkaoNative.notifyEnabled === 'function' ? GongkaoNative : null;
}
function refreshNotifyBtn() {
  const n = nativeNotify();
  const b = $('#acct-notify');
  if (!b) return;
  if (!n) { b.textContent = '手机通知（需安装 App）'; return; }
  try { b.textContent = '手机通知：' + (n.notifyEnabled() ? '已开启 ✓' : '已关闭'); } catch (_) { /* 壳没提供这个接口就不显示状态，普通浏览器里本来就没有 */ }
}
$('#acct-notify').onclick = () => {
  const n = nativeNotify();
  if (!n) return toast('网页版看不到系统通知，请安装安卓 App', true);
  try {
    const on = !n.notifyEnabled();
    n.setNotify(on);
    refreshNotifyBtn();
    toast(on ? '已开启：新消息会推到手机通知栏' : '已关闭手机通知');
  } catch (e) { toast('设置失败', true); }
};
$('#acct-notifytest').onclick = () => {
  const n = nativeNotify();
  if (!n) return toast('网页版看不到系统通知，请安装安卓 App', true);
  try { n.notifyTest(); toast('已发送，下拉通知栏看看'); }
  catch (e) { toast('发送失败', true); }
};
