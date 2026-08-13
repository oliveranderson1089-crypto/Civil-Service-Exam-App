/* 侧边翻页条（电脑端）
 *
 * 由 app.js 按它自己的区段边界切出（原 L10271-10295）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, IS_MOBILE, back */

/* ================= 侧边翻页条（电脑端）=================
   手写笔没有滚轮、没有中键，光靠拖滚动条很别扭。这里给一排大按钮：
   上下翻一屏、直接回顶（回顶时如果不在首页，顺便把「返回」按钮亮出来）、到底部。 */
function pgScroll(dy) {
  const el = document.scrollingElement || document.documentElement;
  el.scrollBy({ top: dy, behavior: 'smooth' });
}
function pgInit() {
  // 触屏手机不需要；桌面版和电脑网页才显示
  document.body.classList.toggle('has-pen', !IS_MOBILE);
  $('#pg-up').onclick = () => pgScroll(-(innerHeight * 0.85));
  $('#pg-dn').onclick = () => pgScroll(innerHeight * 0.85);
  $('#pg-end').onclick = () => {
    const el = document.scrollingElement || document.documentElement;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  };
  $('#pg-top').onclick = () => {
    const el = document.scrollingElement || document.documentElement;
    el.scrollTo({ top: 0, behavior: 'smooth' });
  };
  // 长按/右键「回到顶部」= 直接返回上一页，省得回顶再去点返回
  $('#pg-top').oncontextmenu = (e) => { e.preventDefault(); back(); };
  pgSync();
}

/* 页面根本滚不动的时候把这一条收起来。
   它是给手写笔用的（笔没有滚轮），所以**不能**做成「滚动时才淡入」——
   那样第一下就没得点。但「这一页只有半屏内容、右边却常驻四个翻页箭头」
   同样说不过去：四个按钮全是死的，还占着右边一条道。
   判据就是一句：滚不动就收起来。 */
function pgSync() {
  const bar = $('#pgbar'); if (!bar) return;
  const el = document.scrollingElement || document.documentElement;
  const can = el.scrollHeight > el.clientHeight + 40;
  bar.classList.toggle('pg-idle', !can);
  document.body.classList.toggle('has-pgbar', can && !IS_MOBILE);
}
window.pgSync = pgSync;
/* 内容是异步来的，高度会变好几次；滚动和改窗口也都要重算。
   rAF 合并一下，别一秒算几百遍。 */
let pgRaf = 0;
const pgQueue = () => {
  if (pgRaf) return;
  pgRaf = requestAnimationFrame(() => { pgRaf = 0; pgSync(); });
};
addEventListener('scroll', pgQueue, { passive: true });
addEventListener('resize', pgQueue);
pgInit();
