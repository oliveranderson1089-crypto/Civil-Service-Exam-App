/* 顶栏
 *
 * 由 app.js 按它自己的区段边界切出（原 L3291-3311）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, appConfirm, esc */

/* ================= 顶栏 ================= */
$('#admin-btn').onclick = () => { location.href = '/admin'; };
async function doLogout() {
  if (!(await appConfirm('退出登录？'))) return;
  try { await fetch('/logout', { method: 'POST' }); } catch (_) {}
  location.href = '/login';
}
// 关键点加粗：书名号/引号/【】/「」/“X个XX”等高频要点；换行转 <br>
function emKey(text) {
  let t = esc(text || '');
  t = t.replace(/《[^》]{1,40}》/g, m => '<b>' + m + '</b>')
    .replace(/“[^”]{1,40}”/g, m => '<b>' + m + '</b>')
    .replace(/「[^」]{1,40}」/g, m => '<b>' + m + '</b>')
    .replace(/【[^】]{1,40}】/g, m => '<b>' + m + '</b>')
    .replace(/[一二三四五六七八九十两]+个[一-龥]{2,8}/g, m => '<b>' + m + '</b>');
  return t.replace(/\n/g, '<br>');
}
function isDocHeading(s) {
  return /^(第[一二三四五六七八九十百]+[篇章节]|[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\)|\d+[、.．])/.test(s);
}
