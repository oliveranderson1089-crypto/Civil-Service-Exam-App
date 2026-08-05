/* 答题卡（界面重构 P4）：做题页右栏那一格。
 *
 * 补的是一个真缺口，不只是排版：真题做题页原来**只有「下一题」** —— 整卷 130 道，
 * 想回头改第 47 题就只能交卷重来。答题卡先解决「跳得回去」，顺带解决「还剩几道没答」。
 *
 * 电脑上它常驻右栏（宽度本来就空着）；手机上默认收起，点标题展开——竖屏上
 * 一格一格的方阵很占地方，而手机做题多半是一路往下做，用不着频繁跳。
 *
 * 真题（realq）和专项练（drill）共用这一份：两边都是「一次一道 + 一个题目数组」，
 * 各写一套迟早在「已答/未答怎么算」上分家。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 */
/* global $, esc */

/* host   —— 容器选择器（#rq-side / #dr-side）
   o.title —— 标题（如「资料分析 · 20 题」），不给就写「答题卡」
   o.stat  —— 标题下那行统计（如「已答 12 · 用时 14:22 · 均 71 秒/题」）
   o.n    —— 共几题
   o.cur  —— 当前第几题（0 起）
   o.state(i) —— 这题什么状态：'right' | 'wrong' | 'done'（已答未判） | ''（没答）
   o.onJump(i) —— 点了某一格 */
function qsRender(host, o) {
  const box = $(host);
  if (!box || !o || !o.n) { if (box) box.innerHTML = ''; return; }
  let done = 0;
  const cells = [];
  for (let i = 0; i < o.n; i++) {
    const st = (o.state ? o.state(i) : '') || '';
    if (st) done++;
    cells.push(`<button class="qs-c${st ? ' qs-' + st : ''}${i === o.cur ? ' qs-cur' : ''}"
      data-qs="${i}" title="第 ${i + 1} 题">${i + 1}</button>`);
  }
  box.innerHTML = `
    <button class="qs-h" data-qs-toggle>
      <span>${esc(o.title || '答题卡')}</span>
      <span class="qs-n">${done}/${o.n}</span>
      <span class="qs-caret">▾</span>
    </button>
    ${o.stat ? `<div class="qs-stat">${esc(o.stat)}</div>` : ''}
    <div class="qs-grid">${cells.join('')}</div>`;
  box.classList.remove('hidden');
  // 每次重画都把处理器重新挂上：内容是整段换的，旧的随节点一起没了
  box.querySelector('[data-qs-toggle]').onclick = () => box.classList.toggle('qs-open');
  box.querySelector('.qs-grid').onclick = (e) => {
    const c = e.target.closest('[data-qs]');
    if (c && o.onJump) o.onJump(+c.dataset.qs);
  };
}
/* 撤掉答题卡。**必须清空 innerHTML，光加 hidden 不算数**：格子还在 DOM 里，
   键盘的 J/K 照样能查到它、点得动它，于是出现「交卷之后按 j 又跳回题目」
   「背题模式按 j 用的是上一局测试模式留下的旧卡」这种鬼打墙。 */
function qsClear(host) {
  const box = $(host);
  if (!box) return;
  box.innerHTML = '';
  box.classList.add('hidden');
  box.classList.remove('qs-open');
}
window.qsRender = qsRender;
window.qsClear = qsClear;
