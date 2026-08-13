/* 今日仪表盘（界面重构 P1）：首页从「13 张同权重的功能卡」换成「今天该做什么」。
 *
 * 原来的九宫格没消失，挪去了「我的 › 全部功能」（#view-allfeats）——它仍是 init() 渲染的
 * 那一份 #home-cards，拖拽排序、AI 工具面板读到的东西都没变，只是换了个父节点。
 *
 * 数据两个请求：
 *   /api/today            —— 聚合接口，一次取回做题量/任务/计划/更新/上次练习（见 mods/today.py）
 *   /api/review/today     —— 复习条数照旧单独调。它除了算数还要记古诗流水，聚合接口里
 *                            照抄一遍会把那笔记重，所以宁可多一个请求。
 *
 * 这一屏最容易犯的错是**报喜不报忧**：没数据时糊一堆 0 和满环，看着像在学习。
 * 所以下面所有「空」的分支都给的是下一步动作（去设任务 / 去出测试），不是漂亮的零。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 */
/* global $, api, esc, openChangshi, openDtest, openFanwen, openGaikuo, openNews,
   openPlanLog, openRealq, openReview, openSucai, openTasks, openVideos, push, srRightFill,
   srRightOn, tbSetReview, uiError */

let tdData = null;
let tdAt = 0;            // 上次拉取时刻：回首页很频繁（每次 back 都算），别每次都打接口

// 「今日更新」那几格点进去分别是谁。key 跟后端 mods/today.py 的 _UPDATES 对齐
const TD_GO = {
  news: () => openNews(), sucai: () => openSucai('全部'), fanwen: () => openFanwen(),
  videos: () => openVideos(), gaikuo: () => openGaikuo(), changshi: () => openChangshi(),
};

function tdPct(d) {
  // 完成度的分母是「今天要做的事」= 任务清单 + 今日计划。两个都没有就没有完成度可言，
  // 这时候返回 null 让上面显示「还没安排今天」，而不是显示一个 0% 或者假的 100%。
  const done = (d.tasks.done || 0) + (d.plan.done || 0);
  const total = (d.tasks.total || 0) + (d.plan.total || 0);
  return total ? { pct: Math.round(done * 100 / total), done, total } : null;
}

function tdHero(d) {
  const p = tdPct(d);
  const q = d.done.questions || 0, m = d.done.minutes || 0;
  const ring = p
    ? `<div class="td-ring" style="--p:${p.pct}"><i>${p.pct}%</i></div>`
    : `<div class="td-ring td-ring-off"><i>—</i></div>`;
  const sub = p
    ? `今日任务 ${p.done}/${p.total} 项`
    : '今天还没安排任务';
  return `<div class="td-hero">
    ${ring}
    <div class="td-hero-t">
      <div class="td-hero-k">${esc(sub)}</div>
      <div class="td-hero-v">${q} 题 · ${m} 分钟</div>
      <div class="td-hero-k">${d.streak > 0
    ? `连续学习 <b>${d.streak}</b> 天 · 累计 ${d.study_days} 天`
    : '今天学一点，连续天数就从 1 开始'}</div>
    </div>
  </div>`;
}

function tdCta(d) {
  // 巩固测试今天没做 → 首页就催这一件事；做过了 → 换成再练一组真题。
  // 只给**一个**主行动：两个并列的大按钮等于没有主次，又回到「让用户自己挑」。
  const fresh = !d.dtest.runs;
  return fresh
    ? `<button class="td-cta" data-td="dtest">开始今天的学习
         <small>${d.dtest.has ? '巩固测试已出好' : '按今天学的出一份巩固测试'} · 约 15 分钟</small></button>`
    : `<button class="td-cta" data-td="realq">再练一组真题
         <small>今天的巩固测试已完成 ${d.dtest.score}/${d.dtest.total}</small></button>`;
}

function tdTodo(d, review) {
  const rows = [];
  if (review > 0) rows.push({ go: 'review', dot: 'r', name: '今日复习', badge: review });
  if (d.tasks.total) {
    const left = d.tasks.total - d.tasks.done;
    rows.push({ go: 'tasks', dot: left ? 'a' : 'g', name: '任务清单',
      badge: left ? left : '已完成', quiet: !left });
  }
  if (d.plan.total) {
    const left = d.plan.total - d.plan.done;
    rows.push({ go: 'plan', dot: left ? 'a' : 'g', name: '今日计划',
      badge: left ? left : '已完成', quiet: !left });
  }
  if (!rows.length) {
    return `<div class="td-h">待办</div>
      <div class="td-empty">今天没有待办。<button class="td-link" data-td="tasks">去排今天的任务</button></div>`;
  }
  return `<div class="td-h">待办</div><div class="td-rows">` + rows.map(r =>
    `<div class="td-row" data-td="${r.go}" tabindex="0" role="button">
      <span class="td-dot td-${r.dot}"></span><span class="td-name">${esc(r.name)}</span>
      <span class="td-badge${r.quiet ? ' quiet' : ''}">${esc(String(r.badge))}</span>
    </div>`).join('') + '</div>';
}

function tdUpdates(d) {
  if (!d.updates.length) {
    // 素材/时政是 cron 在后台产出的，断供过而且**是无声的**。首页与其显示「都写齐了」，
    // 不如老实说今天还没更新——这样断供第一天就看得见。
    return `<div class="td-h">今日更新</div>
      <div class="td-empty">今天还没有新内容进来。</div>`;
  }
  return `<div class="td-h">今日更新</div><div class="td-ups">` + d.updates.map(u =>
    `<div class="td-up" data-td="up:${esc(u.go)}" tabindex="0" role="button">
      <span class="td-up-n">${esc(u.name)}</span><span class="td-up-c">+${u.n} 条</span>
    </div>`).join('') + '</div>';
}

function tdLast(d) {
  if (!d.last) return '';
  const l = d.last;
  const rate = l.total ? Math.round(l.correct * 100 / l.total) : 0;
  return `<div class="td-h">上次练习</div>
    <div class="td-rows"><div class="td-row" data-td="realq" tabindex="0" role="button">
      <span class="td-dot td-b"></span>
      <span class="td-name">${esc(l.scope)}</span>
      <span class="td-badge quiet">${l.correct}/${l.total} · ${rate}%</span>
    </div></div>`;
}

function tdRender(d, review) {
  const days = d.exam && d.exam.days_left != null
    ? `<div class="td-exam">距 ${esc(d.exam.name)} 还有 <b>${d.exam.days_left}</b> 天</div>` : '';
  /* 顶栏右上角那句倒计时。放在这儿而不是单独拉一次接口：数据同一份，
     而且它在任何页面都该显示（不只「今日」页），所以挂顶栏、只在这儿刷。 */
  const td = $('#tb-days');
  if (td) {
    const on = !!(d.exam && d.exam.days_left != null);
    td.classList.toggle('hidden', !on);
    if (on) td.innerHTML = `距${esc(d.exam.name)} <b>${d.exam.days_left}</b> 天`;
  }
  /* 宽屏三栏时，待办和今日更新住在右侧随手栏里（js/tabs.js），中间就不再写一遍 ——
     两栏并排显示同样三行，看着像出了 bug。中间只留「此刻做什么」：
     完成度、主行动、上次练到哪。窄屏一切照旧。 */
  const side = window.srRightOn ? srRightOn() : false;
  $('#today-body').innerHTML =
    `<div class="td-date">${esc(d.date)} ${esc(d.weekday)}</div>${days}`
    + tdHero(d) + tdCta(d)
    + (side ? '' : tdTodo(d, review) + tdUpdates(d))
    + tdLast(d)
    + `<button class="td-all" data-td="allfeats">全部功能 ›</button>`;
}
/* 拖窗口跨过 1360 时要重画（那两段在中间和随手栏之间搬家）。
   用存下来的这一份，不重新打接口。 */
let tdReview = 0;
function tdRepaint() { if (tdData) tdRender(tdData, tdReview); }
window.tdRepaint = tdRepaint;

async function tdLoad(force) {
  if (!force && tdData && Date.now() - tdAt < 20000) return;   // 每次 back 回首页都会调，别把接口打穿
  const box = $('#today-body');
  if (!tdData) box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    // 两个请求并行。复习那条挂了也不该拖垮整屏，所以各自兜底
    const [d, rv] = await Promise.all([
      api('/api/today'),
      api('/api/review/today?count=1').catch(() => ({ count: 0 })),
    ]);
    // 左栏「今日复习」的角标用的就是这一份，不再单独拉一次
    if (window.tbSetReview) tbSetReview(rv.count || 0);
    tdReview = rv.count || 0;
    /* **先画成了，才认这份数据。** 反过来写（先 tdData = d 再画）的话，
       一份缺字段的响应会被记下来，而 tdRepaint 是在 try 外头被调的
       （切视图 / 拖窗口都会触发），下一次重画就把异常抛到 render() 里，
       整个壳当场停住。画不出来就当没拉到，走下面的出错态。 */
    tdRender(d, tdReview);
    tdData = d; tdAt = Date.now();
  } catch (e) {
    box.innerHTML = uiError(e, () => tdLoad(true));
  }
  // 右侧随手栏（宽屏）读的是同一份，拉完顺手喂一次。
  // 顺序不能反：先喂随手栏（它会挂上 has-rrail 并回调 tdRepaint），首页那两段才知道该不该画
  if (window.srRightFill) srRightFill();
}
window.tdLoad = tdLoad;
// 右侧随手栏要读今天这一份，别再拉一次接口
window.tdGet = () => tdData;

$('#today-body').addEventListener('click', e => {
  const t = e.target.closest('[data-td]'); if (!t) return;
  const g = t.dataset.td;
  if (g.startsWith('up:')) { const f = TD_GO[g.slice(3)]; if (f) f(); return; }
  if (g === 'retry') { tdLoad(true); return; }
  if (g === 'dtest') openDtest();
  else if (g === 'realq') openRealq();
  else if (g === 'review') openReview();
  else if (g === 'tasks') openTasks();
  else if (g === 'plan') openPlanLog();
  else if (g === 'allfeats') openAllFeats();
});

function openAllFeats() { push({ view: 'allfeats' }); }
window.openAllFeats = openAllFeats;

/* 自己起跑，不等 init()。
   本文件排在 index.html 的最后（排前面会打乱既有脚本的执行次序），而 init() 在 sync.js 里
   早就跑完了 —— 靠 render() 那个钩子的话，首页第一次显示时 tdLoad 还不存在，仪表盘要等
   用户来回切一次才出得来。这里直接开跑，还顺带和 init() 的请求并行，首屏更快。 */
tdLoad();
