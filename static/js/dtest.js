/* 每日巩固测试：出题 / 作答 / 交卷判分 / 成绩记录
 *
 * 拆 app.js 时这个功能被切成了两半 —— 出题入口留在这儿，渲染和交卷却掉进了
 * figures.js，两边互相够着（那边用这边 13 个符号，这边反过来用那边的 renderDtest /
 * openDtRecords，成了环）。根子是照搬了 app.js 的旧区段边界，而那个边界本身就是错的。
 * 现已并回，环解开了。（mods/dtest.py 的文件头记着后端一模一样的病。）
 *
 * index.html 里的引入次序不能调换：415 个事件绑定依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, PL_MOD_COLOR, api, appConfirm, dtMaterial,
   esc, lsGet, lsSet, push, toast,
   qtFmt, qtTotalStart, qtTotalStop, wqlBtnHtml, wqlMark, wqlOpen,
   wqlRefreshBtns, wqlScan */

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

/* 巩固测试是**一屏列全部题**，不像专项练一题一屏 —— 所以计时器给的是「整份」的：
   总时长 = 各题按题型的限时之和（服务端在 it.sec 里给，见 mods/timing.py），
   每道题旁边再标一句「建议 30 秒」。一份小测里常识 30 秒、数量 70 秒混着出，
   拿一个板块基准套所有题的话，那个钟没人会看。
   到点不打断：转红记超时，题接着做。 */
function dtTotalSec() { return dtItems.reduce((s, it) => s + (it.sec || 40), 0); }
/* 这份卷子的身份。qtTotalStart 拿它判「还是不是同一份」：是就接着走，不是才重开。
   没有它的话，离开页面再回来（或每次 loadDtest）钟都从满格重来 ——
   退出去再进来就能无限续时，这个限时等于没有。 */
function dtClockTag() { return 'dt' + dtItems.length + ':' + (dtItems[0] || {}).wq_key; }
function dtClockStart() {
  if (!dtItems.length || dtSubmitted) return;
  qtTotalStart('#dt-total', dtTotalSec(), dtClockTag());
}
function dtClockStop() {
  qtTotalStop();
  const el = $('#dt-total');
  if (el) { el.textContent = ''; el.className = 'q-total hidden'; }
}
/* 这一份里哪些题已经在错题本（背题模式选错时服务端会自动收，按钮状态要跟得上）。
   **不 await**：题先画出来，按钮状态随后补 —— 挡在前面只是让人多等一个来回。 */
function dtScanWq() {
  const keys = dtItems.map(x => x.wq_key).filter(Boolean);
  if (!keys.length) return Promise.resolve();
  return wqlScan('dtest', { keys }).then(() => wqlRefreshBtns('#dt-body'));
}
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
    /* 这儿**不无条件停表**：loadDtest 每次进页面都会跑，停了就等于每次进来都重新计时。
       换没换卷子由 dtClockTag() 认（见 dtClockStart），同一份就接着走。 */
    if (!dtItems.length) {
      dtClockStop();                   // 没题了（还没生成），钟没有意义
      $('#dt-body').innerHTML = dtModeBar() +
        `<div class="dt-empty">今天还没生成测试。选好模式和题量，AI 会按你今天学的内容出题。</div>
        <button class="btn primary" id="dt-gen">✨ 生成今日巩固测试</button>`;
      $('#dt-gen').onclick = () => dtGen(false);
      bindBar();
      return;
    }
    renderDtest();
    dtScanWq();
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
        try { const d = await api('/api/dtest'); if ((d.items || []).length === dtItems.length) dtItems = d.items; } catch (e) { console.debug('[巩固测试] 取题失败，保留当前题目：%s', (e && e.message) || e); }
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
    dtClockStop();                     // 新的一套：卷子换了，钟必须从头起
    renderDtest();
    dtScanWq();
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

/* ---------- 以下由 figures.js 并回：出题/交卷/成绩记录 ----------
   原先它们被切在 figures.js 里，而这边留着 openDtest/loadDtest/dtGen —— 同一个功能
   切成两半、互相够着（那边用这边 13 个符号，这边反过来用那边的 renderDtest/
   openDtRecords，成了环）。并回来环就没了。 */
function renderDtest() {
  const qs = dtItems.map((it, i) => {
    const revealed = dtRevealedAt(i);
    const isFig = !!(it.figs && it.figs.opts);
    const opts = isFig
      ? it.figs.opts.map((svg, j) => {
        const L = DT_L[j], chosen = dtChosen[i] === L, isAns = (dtAns(i) || '').toUpperCase() === L;
        let cls = 'dt-opt dt-figopt';
        if (revealed) { if (isAns) cls += ' correct'; else if (chosen) cls += ' wrong'; }
        else if (chosen) cls += ' chosen';
        return `<button class="${cls}" data-dtq="${i}" data-dtl="${L}" ${revealed ? 'disabled' : ''}>
          <span class="dt-figl">${L}</span>${svg}</button>`;
      }).join('')
      : (it.options || []).map((o, j) => {
        const L = DT_L[j], chosen = dtChosen[i] === L, isAns = (dtAns(i) || '').toUpperCase() === L;
        let cls = 'dt-opt';
        if (revealed) { if (isAns) cls += ' correct'; else if (chosen) cls += ' wrong'; }
        else if (chosen) cls += ' chosen';
        return `<button class="${cls}" data-dtq="${i}" data-dtl="${L}" ${revealed ? 'disabled' : ''}>${esc(o)}</button>`;
      }).join('');
    const e = dtExp(i);
    const wrong = revealed && (dtAns(i) || '').toUpperCase() !== dtChosen[i];
    const exp = revealed ? `<div class="dt-exp"><b>正确答案 ${esc(dtAns(i))}</b>${e.explain ? ' · ' + esc(e.explain) : ''}${e.source ? ` <span class="dt-src">${esc(e.source)}</span>` : ''}
      ${/* 做错的题服务端已自动收进错题本，这儿让人当场补一句错因、或把手滑点错的移出去 */''}
      ${wrong && it.wq_key ? `<div class="dr-wql">${wqlBtnHtml(it.wq_kind || 'dtest', it.wq_key)}</div>` : ''}</div>` : '';
    const mod = it.module ? `<span class="dt-mod" style="background:${PL_MOD_COLOR[it.module] || '#6b7280'}">${esc(it.module)}</span>` : '';
    const mat = dtMaterial(it.material, i, i ? dtItems[i - 1].material : null);
    const seq = isFig ? `<div class="dt-seq">${it.figs.seq.join('')}<span class="dt-qm">?</span></div>` : '';
    // 每题标出这个**题型**该花多久 —— 顶上的总倒计时就是这些数加起来的，
    // 看到「这题建议 30 秒」才知道该不该在这儿耗着
    const secTag = it.sec ? `<span class="dt-sec">建议 ${it.sec} 秒</span>` : '';
    return `<div class="dt-q">${mat}<div class="dt-qt">${mod}${i + 1}. ${esc(it.q)}${secTag}</div>${seq}
      <div class="dt-opts${isFig ? ' dt-figs' : ''}">${opts}</div>${exp}</div>`;
  }).join('');
  let foot;
  if (dtSubmitted) {
    foot = `<div class="dt-score">得分 ${dtScore()} / ${dtItems.length}
       <span class="dt-score-sub">全套建议用时 ${qtFmt(dtTotalSec())}</span></div>
       <button class="btn" id="dt-again">🔄 换一套新题</button>`;
  } else if (dtIsTest()) {
    foot = `<button class="btn primary" id="dt-submit">交卷看结果</button>`;
  } else {
    const done = dtItems.filter((_, i) => dtRevealed[i]).length;
    foot = `<div class="dt-prog2">已做 ${done} / ${dtItems.length}</div>` +
      (done === dtItems.length ? `<button class="btn primary" id="dt-finish">看结果并记录</button>` : '');
  }
  $('#dt-body').innerHTML = (dtSubmitted ? '' : dtModeBar()) + `<div class="dt-list">${qs}</div><div class="dt-foot">${foot}</div>`;
  if (dtSubmitted) {
    dtClockStop();                    // 交完卷钟就该收，别在成绩页上继续跳
    $('#dt-again').onclick = async () => { if (await appConfirm('重新出一套？当前作答会清空。')) dtGen(true); };
  } else {
    const s = $('#dt-submit'); if (s) s.onclick = dtSubmit;
    const f = $('#dt-finish'); if (f) f.onclick = dtFinish;
    bindBar();
    dtClockStart();                   // 已经在走的话是空操作（见 dtClockStart）
  }
}

/* 错题本按钮：巩固测试是一屏列全部题，按钮散在各题的解析里，统一在这儿接。 */
$('#dt-body').addEventListener('click', e => {
  const b = e.target.closest('[data-wql]');
  if (!b) return;
  const i = dtItems.findIndex(x => x.wq_key === b.dataset.wql);
  const it = dtItems[i] || {};
  wqlOpen(b.dataset.wqlkind, b.dataset.wql, {
    board: it.module || '', qtype: it.qtype || it.source || '',
    question: (it.q || '') + '\n' + (it.options || []).join('\n'),
    answer: `正确答案 ${dtAns(i) || ''}。${(dtExp(i) || {}).explain || ''}`,
    note: '来自巩固测试',
  }, () => wqlRefreshBtns('#dt-body'));
});
async function dtRecord() {
  // 把本次作答交给服务端判分并留档
  try {
    const ans = {}; dtItems.forEach((_, i) => ans[i] = dtChosen[i] || '');
    return await api('/api/dtest/grade', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answers: ans }) });
  } catch (e) { toast(e.message, true); return null; }
}
async function dtSubmit() {   // 测试模式交卷
  const un = dtItems.findIndex((_, i) => !dtChosen[i]);
  if (un >= 0) { toast('第 ' + (un + 1) + ' 题还没选', true); return; }
  const btn = $('#dt-submit'); if (btn) { btn.disabled = true; btn.textContent = '判分中…'; }
  const d = await dtRecord();
  if (!d) { if (btn) { btn.disabled = false; btn.textContent = '交卷看结果'; } return; }
  dtResults = d.results || [];
  dtSubmitted = true; renderDtest();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
async function dtFinish() {   // 背题模式做完，记录成绩
  await dtRecord();
  dtSubmitted = true; renderDtest();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
$('#dt-body').addEventListener('click', e => {
  const tb = e.target.closest('[data-chtb]');          // 图表下方的「看数据表」
  if (tb) {
    const box = $('#chtb-' + tb.dataset.chtb);
    const hidden = box.classList.toggle('hidden');
    tb.textContent = hidden ? '📋 看数据表' : '📊 收起数据表';
    return;
  }
  const o = e.target.closest('[data-dtq]'); if (!o) return;
  const i = +o.dataset.dtq;
  if (dtRevealedAt(i)) return;              // 已揭晓的题不能再改
  dtChosen[i] = o.dataset.dtl;
  if (!dtIsTest()) {
    dtRevealed[i] = true;                   // 背题模式：选完立刻揭晓这题
    if ((dtAns(i) || '').toUpperCase() !== dtChosen[i]) {   // 选错了 → 自动进错题本
      /* 做错了**自动**进错题本 —— 这条链路是这个模块的核心，别动。
         服务端收完，本地状态跟着记一笔、就地把那一个按钮点亮就行：
         再打一次 lookup + 整屏重画（十几道题连图形 SVG 一起重建）纯属浪费，
         重画那一下还会把正在点下一题的手指弹开。 */
      api('/api/dtest/wrong', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ idx: i, choice: dtChosen[i] }),
      }).then(d => {
        if (d.added) toast('这题错了，已收进错题本');
        // d.ok=false 表示服务端压根没收（今天没这份卷子/题号对不上），那就别把按钮点亮
        const key = d.ok ? (dtItems[i] || {}).wq_key : '';
        if (key) { wqlMark('dtest', key); wqlRefreshBtns('#dt-body'); }
      }).catch(() => {});
    }
  }
  renderDtest();
});
/* 测试记录：列表 + 回看某次作答 */
async function openDtRecords() {
  $('#dt-body').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/dtest/records');
    const list = d.items.length ? d.items.map(r => `
      <div class="dtr-row" data-dtrec="${r.id}">
        <span class="dtr-when">${esc((r.created_at || r.date || '').slice(5, 16))}</span>
        <span class="dtr-score ${r.score >= r.total * 0.6 ? 'ok' : 'bad'}">${r.score} / ${r.total}</span>
        <span class="dtr-go">回看 ›</span></div>`).join('')
      : '<p class="empty">还没有测试记录。做一次巩固测试，交卷后就会留档。</p>';
    $('#dt-body').innerHTML = `<div class="dtr-top"><button class="pl-link-btn" id="dt-back">‹ 返回测试</button><b>测试记录</b></div>${list}`;
    $('#dt-back').onclick = loadDtest;
  } catch (e) { $('#dt-body').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
async function openDtRecord(rid) {
  $('#dt-body').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/dtest/record/' + rid);
    const qs = (d.detail || []).map((it, i) => {
      const opts = (it.options || []).map((o, j) => {
        const L = DT_L[j], isAns = (it.answer || '').toUpperCase() === L, mine = (it.your || '').toUpperCase() === L;
        let cls = 'dt-opt'; if (isAns) cls += ' correct'; else if (mine) cls += ' wrong';
        return `<button class="${cls}" disabled>${esc(o)}</button>`;
      }).join('');
      return `<div class="dt-q"><div class="dt-qt">${i + 1}. ${esc(it.q)}</div><div class="dt-opts">${opts}</div>
        <div class="dt-exp"><b>正确答案 ${esc(it.answer)}</b>${it.your ? ' · 你选了 ' + esc(it.your) : ''}${it.explain ? ' · ' + esc(it.explain) : ''}${it.source ? ` <span class="dt-src">${esc(it.source)}</span>` : ''}</div></div>`;
    }).join('');
    $('#dt-body').innerHTML = `<div class="dtr-top"><button class="pl-link-btn" id="dt-back2">‹ 返回记录</button>
      <b>${esc((d.created_at || '').slice(5, 16))} · 得分 ${d.score}/${d.total}</b></div><div class="dt-list">${qs}</div>`;
    $('#dt-back2').onclick = openDtRecords;
  } catch (e) { $('#dt-body').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#dt-body').addEventListener('click', e => {
  const r = e.target.closest('[data-dtrec]'); if (r) openDtRecord(+r.dataset.dtrec);
});
