/* 做题页右栏的标签切换：答题卡 / AI 助手 / 草稿纸 / 笔记（对齐目标效果图）。
 *
 * AI 助手、草稿纸、随手记本来都是**浮层**（fixed，靠悬浮球唤出）。这里不重写它们 ——
 * 那三块各自有几百行逻辑（拖拽、停靠、笔迹、会话），重写一遍等于把跑通的代码扔掉。
 * 做的是**把那个元素搬进右栏**，套一个 .dk-inline 让它从 fixed 变成流内的一张卡；
 * 切走或离开做题页再搬回 body，恢复原样。
 *
 * 搬家要还三笔账，漏一笔就出怪事：
 *   · dock.js 的 applyPush() 会按面板的宽高去推正文 —— 内联之后它本来就在正文里，
 *     再推一次就是白让出去半屏；
 *   · avoidFab() 会为了躲面板挪悬浮球 —— 内联的面板压根不挡球；
 *   · 随手记是 makeFloat 拖出来的，位置写在 style 上（left/top/width），
 *     不清掉的话搬进右栏还赖在原来那个坐标上。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 */
/* global $, esc, openAI, padOpen, qnOpen */

/* el   —— 要搬进来的浮层（没有就是答题卡那一档，用右栏里现成的卡片）
   init —— 让它自己做初始化（拉数据、建画布…），搬家不替它干这些 */
const QP_TABS = [
  { k: 'sheet', name: '答题卡' },
  { k: 'ai', name: 'AI 助手', el: '#ai-panel', init: () => openAI() },
  { k: 'pad', name: '草稿纸', el: '#pad', init: () => padOpen() },
  { k: 'note', name: '笔记', el: '#qnote', init: () => qnOpen() },
];
let qpCur = 'sheet';

// 把搬进来的浮层送回 body，并把 .dk-inline 留下的痕迹擦干净
function qpRelease() {
  QP_TABS.forEach(t => {
    if (!t.el) return;
    const el = $(t.el);
    if (!el || !el.classList.contains('dk-inline')) return;
    el.classList.remove('dk-inline');
    el.classList.add('hidden');
    // makeFloat 把位置写在 style 上，不清掉搬回去还赖在右栏那个坐标
    ['left', 'top', 'right', 'bottom', 'width', 'height'].forEach(k => el.style.removeProperty(k));
    document.body.appendChild(el);
  });
  const host = $('#rq-host');
  if (host) { host.innerHTML = ''; host.classList.add('hidden'); }
}
window.qpRelease = qpRelease;

function qpShow(k) {
  const t = QP_TABS.find(x => x.k === k) || QP_TABS[0];
  qpRelease();
  qpCur = t.k;
  const sheet = t.k === 'sheet';
  ['#rq-side', '#rq-rel'].forEach(s => {
    const e = $(s);
    // 答题卡那一档才露出来；它们各自还有「有没有内容」的开关，这里只管档位
    if (e) e.classList.toggle('qp-off', !sheet);
  });
  if (!sheet && t.el) {
    const el = $(t.el);
    if (el) {
      if (t.init) { try { t.init(); } catch (_) { /* 面板自己初始化失败不该拖垮切档 */ } }
      el.classList.remove('hidden');
      el.classList.add('dk-inline');
      $('#rq-host').appendChild(el);
      $('#rq-host').classList.remove('hidden');
    }
  }
  qpRenderTabs();
}

function qpRenderTabs() {
  const box = $('#rq-tabs'); if (!box) return;
  box.innerHTML = QP_TABS.map(t =>
    `<button data-qp="${esc(t.k)}" class="${t.k === qpCur ? 'on' : ''}">${esc(t.name)}</button>`).join('');
}
qpRenderTabs();

$('#rq-tabs').addEventListener('click', e => {
  const b = e.target.closest('[data-qp]'); if (!b) return;
  qpShow(b.dataset.qp);
});

/* 离开做题页就把浮层还回去：不还的话它们跟着隐藏的 #view-realrun 一起消失，
   下次点悬浮球会「点了没反应」—— 元素还在右栏里躺着，而右栏是隐藏的。 */
window.__qpView = function (view) {
  if (view !== 'realrun' && qpCur !== 'sheet') qpShow('sheet');
};
