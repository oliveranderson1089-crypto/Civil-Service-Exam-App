/* 每日巩固测试
 *
 * 由 app.js 按它自己的区段边界切出（原 L5585-5672）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, appConfirm, esc, lsGet, lsSet,
   openDtRecords, push, renderDtest */

/* ---------------- 每日巩固测试（按当天学的内容 AI 出小测） ---------------- */
$('#dt-open').onclick = () => openDtest();
function openDtest() { push({ view: 'dtest', title: '巩固测试' }); loadDtest(); }
let dtItems = [], dtChosen = {}, dtRevealed = {}, dtSubmitted = false, dtResults = null;
// 背题模式 study：做一题立刻显示答案；测试模式 test：答案不下发，交卷才服务端判分
let dtMode = lsGet('dtMode') === 'test' ? 'test' : 'study';
let dtCount = (+lsGet('dtCount') === 15) ? 15 : 10;   // 题量 10 / 15
const DT_L = ['A', 'B', 'C', 'D', 'E', 'F'];
function dtIsTest() { return dtMode === 'test'; }
function dtRevealedAt(i) { return dtIsTest() ? dtSubmitted : !!dtRevealed[i]; }
function dtModeBar() {
  return `<div class="dt-bar">
    <div class="dt-modes">
      <button class="dt-mbtn ${dtMode === 'study' ? 'on' : ''}" data-dtm="study">📖 背题模式</button>
      <button class="dt-mbtn ${dtMode === 'test' ? 'on' : ''}" data-dtm="test">📝 测试模式</button>
    </div>
    <div class="dt-mhint">${dtMode === 'study'
      ? '做一题立刻显示这题答案与解析，边做边记'
      : '答案不提前下发，全部做完交卷、由服务端判分，更像考试'}</div>
    <div class="dt-count">题量：
      <button class="dt-cbtn ${dtCount === 10 ? 'on' : ''}" data-dtc="10">10 题</button>
      <button class="dt-cbtn ${dtCount === 15 ? 'on' : ''}" data-dtc="15">15 题</button></div>
    <button class="pl-link-btn" id="dt-records">📋 测试记录</button>
  </div>`;
}
async function loadDtest() {
  $('#dt-body').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/dtest' + (dtIsTest() ? '?exam=1' : ''));
    dtItems = d.items || []; dtChosen = {}; dtRevealed = {}; dtSubmitted = false; dtResults = null;
    if (!dtItems.length) {
      $('#dt-body').innerHTML = dtModeBar() +
        `<div class="dt-empty">今天还没生成测试。选好模式和题量，AI 会按你今天学的内容出题。</div>
        <button class="btn primary" id="dt-gen">✨ 生成今日巩固测试</button>`;
      $('#dt-gen').onclick = () => dtGen(false);
      bindBar();
      return;
    }
    renderDtest();
  } catch (e) { $('#dt-body').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function bindBar() {
  const rec = $('#dt-records'); if (rec) rec.onclick = openDtRecords;
  document.querySelectorAll('[data-dtm]').forEach(b => b.onclick = async () => {
    const m = b.dataset.dtm; if (m === dtMode) return;
    dtMode = m; lsSet('dtMode', m);
    // 切换模式：同一套题、保留你的作答，只改「何时揭晓答案」，不重新出题、不清空
    if (dtSubmitted || !dtItems.length) { loadDtest(); return; }
    if (m === 'study') {
      // 背题模式要用到答案；若当前这套没带答案（从测试模式来的），重新拉同一套带答案的
      if (dtItems[0] && dtItems[0].answer === undefined) {
        try { const d = await api('/api/dtest'); if ((d.items || []).length === dtItems.length) dtItems = d.items; } catch (_) {}
      }
      dtRevealed = {}; Object.keys(dtChosen).forEach(i => dtRevealed[i] = true);  // 已答的直接揭晓
    } else {
      dtRevealed = {};   // 测试模式：收起逐题揭晓，作答保留，交卷时统一判分
    }
    renderDtest();
  });
  document.querySelectorAll('[data-dtc]').forEach(b => b.onclick = async () => {
    const n = +b.dataset.dtc; if (n === dtCount) return;
    if (dtItems.length && !dtSubmitted) {
      if (!(await appConfirm('换成 ' + n + ' 题需要重新出题，当前作答会清空。'))) return;
      dtCount = n; lsSet('dtCount', n); dtGen(true);
    } else {
      dtCount = n; lsSet('dtCount', n);
      document.querySelectorAll('[data-dtc]').forEach(x => x.classList.toggle('on', +x.dataset.dtc === dtCount));
    }
  });
}
async function dtGen(force) {
  $('#dt-body').innerHTML = `<p class="empty">AI 正在按你今天学的内容出 ${dtCount} 道题，稍等…</p>`;
  try {
    const d = await api('/api/dtest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: !!force, exam: dtIsTest(), count: dtCount }) });
    dtItems = d.items || []; dtChosen = {}; dtRevealed = {}; dtSubmitted = false; dtResults = null;
    renderDtest();
  } catch (e) {
    $('#dt-body').innerHTML = `<div class="dt-empty">${esc(e.message)}</div><button class="btn" id="dt-retry">重试</button>`;
    $('#dt-retry').onclick = () => dtGen(force);
  }
}
// 答案来源：背题模式在 item 里（已下发）；测试模式交卷后在 dtResults 里
function dtAns(i) { return dtResults ? (dtResults[i] || {}).answer : (dtItems[i].answer || '').toUpperCase(); }
function dtExp(i) { return dtResults ? (dtResults[i] || {}) : dtItems[i]; }
function dtScore() {
  if (dtResults) return dtResults.reduce((n, r) => n + (r.correct ? 1 : 0), 0);
  return dtItems.reduce((n, it, i) => n + (dtChosen[i] === (it.answer || '').toUpperCase() ? 1 : 0), 0);
}
