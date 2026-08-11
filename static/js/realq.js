/* 历年真题：智能刷 / 按题型刷 / 整卷模考
 *
 * 和「专项练」的区别在于**题是死的**——就那么几千道。所以这一屏的重点不是「再出一批」，
 * 而是让人看清「我刷到哪了、哪些该再刷一遍」，以及做完之后**解析要好读**。
 *
 * 解析的版式是这个模块的核心：后端给的是结构化四段（关键/步骤/错项/举一反三），
 * 不是一坨文本。所以这里按固定版式排 —— 关键点最先看到，步骤一行一步（计算题
 * 一眼能对着算），错项逐条列。原卷解析仍然保留，折叠起来给想看原文的人。
 *
 */
/* global $, api, appConfirm, artEm, back, esc, push, qsClear, qsRender, qtFmt, qtStart, qtStop, qtTotalStart, qtTotalStop, toast, wqlBtnHtml, wqlOpen, wqlRefreshBtns, wqlScan */

let rqOv = null, rqItems = [], rqIdx = 0, rqAns = {}, rqSec = {};
let rqRates = {};   // 考点 → 近 30 天正确率（跟出题一起回来，见 mods/realq.py 的 _qtype_rates）
let rqExam = false, rqDone = false;   // rqExam=模考模式（做完才判）；rqDone=已交卷，防重复提交
let rqMode = 'smart', rqScope = '';   // 这一组是怎么来的 —— 交卷时写进做题记录
/* 交卷后服务端回的逐题结果，按题号索引。模考模式下答案和解析只在这里有
   （出题时被剥掉了），逐题回顾和「收错题」都要从这儿取。 */
let rqRes = {};
let rqRecItems = [];                  // 做题记录回看页当前这一组的快照
/* 题量：和专项练一个交互（那边是 5/10/15/20）。真题这边多给 30/50 两档 ——
   真题是限量资源，「今天就把这个题型刷透」是常见打法，10 道一组要点五次。
   选择记在本地：每次进来都要重选一遍的话，这个开关等于没加。 */
let rqN = +localStorage.getItem('rq_n') || 10;
const RQ_NS = [5, 10, 20, 30, 50];
/* 整卷的两种打法（和巩固测试、专项练一个词汇表）：
   exam=测试模式，答案不下发、交卷才判分，顶上挂总倒计时 —— 就是原来的「整卷模考」；
   study=背题模式，选完即揭晓答案和解析。一整套 130 道的卷子第一遍往往是拿来「过一遍原卷」的，
   逼着人做完两小时才看见答案，这一遍的收获全压在交卷后那一屏里，题早忘了。
   记在本地：一个人的打法是稳定的，每次进来重选一遍等于没加。 */
let rqPaperMode = localStorage.getItem('rq_paper_mode') === 'study' ? 'study' : 'exam';

async function openRealq() {
  push({ view: 'realq', title: '历年真题' });
  const box = $('#rq-body');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    rqOv = await api('/api/real/overview');
    renderRealqHome();
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

function renderRealqHome() {
  const d = rqOv;
  const acc = d.attempts ? Math.round(100 * d.correct / d.attempts) : null;
  const pct = d.total ? Math.round(100 * d.done / d.total) : 0;
  const byMod = {};
  (d.types || []).forEach(t => { (byMod[t.module] = byMod[t.module] || []).push(t); });

  $('#rq-body').innerHTML = `
    <div class="rq-hero">
      <div class="rq-stat"><b>${d.total}</b><span>可做真题</span></div>
      <div class="rq-stat"><b>${d.done}</b><span>已刷过</span></div>
      <div class="rq-stat"><b>${acc === null ? '—' : acc + '%'}</b><span>正确率</span></div>
      <div class="rq-stat${d.due ? ' due' : ''}"><b>${d.due}</b><span>该重刷</span></div>
    </div>
    <div class="rq-bar"><i style="width:${pct}%"></i></div>
    <p class="rq-hint">国考 2000-2023、四川 2007-2025 原卷。答案存疑的题不会发出来。</p>

    <div class="rq-cfg">
      <label>题量</label>
      <div class="chip-row" id="rq-ns">${RQ_NS.map(n =>
    `<button class="chip${n === rqN ? ' active' : ''}" data-rqn="${n}">${n} 题</button>`).join('')}</div>
    </div>
    <p class="rq-hint sub">每题按<b>题型</b>倒计时（类比推理 25 秒、分析推理 70 秒…），
      到点不打断，只记下超了多少 —— 超时多少才是这道题真实的成绩。</p>

    <div class="rq-go">
      <button class="rq-big" data-rqgo="smart">
        <b>智能刷</b><span>${d.due ? `${d.due} 道该重刷 · 排在最前` : '没做过的优先'}</span></button>
      <button class="rq-big alt" data-rqgo="papers"><b>整卷真题</b><span>按年份/卷种 · 背题或模考</span></button>
    </div>
    <button class="btn tiny" id="rq-recs">${artEm('📋')} 做题记录</button>

    <div class="rq-sec">按题型刷</div>
    ${Object.keys(byMod).map(m => `
      <div class="rq-mod">
        <div class="rq-mod-h">${esc(m || '未归类')}</div>
        <div class="rq-types">${byMod[m].map(t => `
          <button class="rq-t" data-rqm="${esc(m)}" data-rqt="${esc(t.qtype)}">
            ${esc(t.qtype)}<i>${t.c}</i></button>`).join('')}</div>
      </div>`).join('')}`;
}

$('#rq-body').addEventListener('click', async e => {
  const n = e.target.closest('[data-rqn]');
  if (n) {
    rqN = +n.dataset.rqn;
    localStorage.setItem('rq_n', rqN);
    document.querySelectorAll('#rq-ns .chip').forEach(x => x.classList.toggle('active', x === n));
    return;
  }
  if (e.target.closest('#rq-recs')) return openRealRecords();
  const go = e.target.closest('[data-rqgo]');
  if (go) {
    if (go.dataset.rqgo === 'papers') return openRealPapers();
    return rqStart({ mode: 'smart', n: rqN }, '智能刷');
  }
  const t = e.target.closest('[data-rqt]');
  if (t) return rqStart({ mode: 'type', module: t.dataset.rqm, qtype: t.dataset.rqt, n: rqN },
    t.dataset.rqt);
});

async function openRealPapers() {
  const box = $('#rq-body');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/real/papers');
    box.innerHTML = `<div class="rq-sec">整卷 · ${d.items.length} 份卷子</div>
      <div class="dt-bar">
        <div class="dt-modes" id="rq-pmodes">
          <button class="dt-mbtn${rqPaperMode === 'study' ? ' on' : ''}" data-rqpm="study">${artEm('📖')} 背题模式</button>
          <button class="dt-mbtn${rqPaperMode === 'exam' ? ' on' : ''}" data-rqpm="exam">${artEm('📝')} 测试模式</button>
        </div>
        <div class="dt-mhint" id="rq-pmhint">${rqPmHint()}</div>
      </div>
      <p class="rq-hint">按卷面原序出题。中途可以退出，做过的题会记进进度。</p>
      ${d.items.map(p => `
        <button class="rq-paper" data-pkey="${esc(p.pkey)}"
                data-pnm="${esc(`${p.year} ${p.exam}${p.paper ? ' · ' + p.paper : ''}`)}">
          <b>${p.year} ${esc(p.exam)}${p.paper ? ' · ' + esc(p.paper) : ''}${p.season ? ' · ' + esc(p.season) : ''}</b>
          <span>${p.c} 道可做${p.done ? ` · 已做 ${p.done}` : ''}</span>
          <i style="width:${Math.round(100 * p.done / p.c)}%"></i>
        </button>`).join('')}`;
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

function rqPmHint() {
  return rqPaperMode === 'study'
    ? '做一题立刻显示这题答案与解析，边做边记；不挂总倒计时'
    : '答案不提前下发，整卷做完交卷、由服务端判分，顶上走总倒计时，更像考场';
}

$('#rq-body').addEventListener('click', e => {
  const m = e.target.closest('[data-rqpm]');
  if (m) {
    rqPaperMode = m.dataset.rqpm;
    localStorage.setItem('rq_paper_mode', rqPaperMode);
    /* 只改按钮和这行说明，**不重拉卷子列表**：接口要现算每份卷的已做进度，
       为了换个开关重跑一遍，切两下就是两次白等。 */
    document.querySelectorAll('#rq-pmodes .dt-mbtn').forEach(b =>
      b.classList.toggle('on', b === m));
    $('#rq-pmhint').textContent = rqPmHint();
    return;
  }
  const p = e.target.closest('[data-pkey]');
  if (!p) return;
  // 测试模式=**真模考**：exam:true 让服务端不下发答案，做完一次性判分。
  // 背题模式走 exam:false，和「按题型刷」同一条路——选完即揭晓（见 rqRender 的 reveal）。
  const isExam = rqPaperMode === 'exam';
  /* 标题带上模式：做题记录里同一份卷子可能既背过又考过，只写年份分不出哪次是哪次
     （scope 服务端截 60 字，这个后缀进得去）。 */
  rqStart({ mode: 'paper', pkey: p.dataset.pkey, n: 140, exam: isExam },
    p.dataset.pnm + (isExam ? '' : ' · 背题'));
});

async function rqStart(body, title) {
  toast('取题中…');
  try {
    const d = await api('/api/real/quiz', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, timeoutMs: 20000,
      body: JSON.stringify(body),
    });
    rqItems = d.items; rqIdx = 0; rqAns = {}; rqSec = {}; rqRes = {};
    rqRates = d.rates || {};
    rqExam = !!d.exam; rqDone = false;
    rqMode = body.mode; rqScope = title;
    push({ view: 'realrun', title: title + ' · 真题' });
    /* 错题按钮的状态**不挡首屏**：先把题画出来，扫描回来再刷按钮。
       await 在这儿的话，弱网下点「智能刷」要等两个来回才看见第一道题，
       而「这题收没收过」是次要信息。 */
    rqScanWq();
    // 整卷模考：顶上再挂一个大钟（总时长 = 各题建议用时之和，服务端算好的）。
    // 按题型刷/智能刷不挂 —— 那是练手，没有「整场时间」这回事。
    /* 这儿**不传 tag**（和巩固测试相反）：点一次「整卷模考」就是开一场新的，
       同一份卷子再考一遍也该从满时间开始。中途去别的页面看一眼不受影响 ——
       那条路走的是 shell.js 的 qtTotalPause/Resume，钟接着走，不重开。 */
    if (rqExam && d.total_sec) qtTotalStart('#rq-total', d.total_sec);
    else {
      // 上一次模考留下的大钟要**收干净**：qtTotalStop 只停表不动 DOM，
      // 不隐藏的话按题型刷时顶上还挂着一个不走字的「剩余 01:12:30」。
      qtTotalStop();
      $('#rq-total').textContent = '';
      $('#rq-total').className = 'q-total hidden';
    }
    rqRender();
  } catch (e) { toast(e.message, true); }
}

/* 右栏的「本题相关」：这个考点你最近练得怎么样。
   只说有据可查的话 —— 没数据就直说「还没练过」，不糊一个 0%（那等于说你练砸了）；
   「已加入复习队列」只在**这一题真的做错并揭晓**之后才写，模考模式答案还没揭晓，
   写了就是替服务端许诺一件还没发生的事。 */
function rqRelated(it, justWrong) {
  const box = $('#rq-rel'); if (!box) return;
  const qt = (it.qtype || '').trim();
  if (!qt) { box.classList.add('hidden'); box.innerHTML = ''; return; }
  const r = rqRates[qt];
  const tone = !r ? '' : r.rate < 60 ? ' bad' : r.rate < 80 ? ' warn' : ' good';
  box.classList.remove('hidden');
  box.innerHTML = `<div class="qr-h">本题相关</div>
    <div class="qr-b">考点「${esc(qt)}」·
      ${r ? `你近 30 天此考点正确率 <b class="qr-rate${tone}">${r.rate}%</b>（做过 ${r.n} 题）`
    : '近 30 天还没练过这个考点'}
      ${justWrong ? '，<b>已加入复习队列</b>' : ''}</div>`;
}

function rqRender() {
  if (rqIdx >= rqItems.length) return rqFinish();
  const it = rqItems[rqIdx];
  const src = (it.sources || [])[0] || {};
  const chosen = rqAns[it.id];
  const reveal = chosen && !rqExam;      // 模考模式做完才判，边做边揭就不是模考了
  $('#rq-head').innerHTML = `
    <div class="rq-prog">第 <b>${rqIdx + 1}</b> / ${rqItems.length} 题
      ${it.qtype ? `<span class="rq-tag">${esc(it.qtype)}</span>` : ''}
      <span class="rq-tag src">${src.year || ''} ${esc(src.exam || '')}${src.paper ? '·' + esc(src.paper) : ''}</span>
      <span class="q-clock" id="rq-clock"></span>
    </div>`;
  /* 已经答过的题（翻回来看）不重新计时：那样会把「回看」的时间算进这道题的用时，
     平均用时立刻失真。只有没答过的题才起表。 */
  if (chosen === undefined) qtStart('#rq-clock', it.sec || 60);
  else {
    qtStop();
    const used = rqSec[it.id] || 0;
    const over = used > (it.sec || 60);
    $('#rq-clock').className = 'q-clock' + (over ? ' over' : '');
    $('#rq-clock').textContent = `⏱ 用时 ${Math.round(used)} 秒${over ? `（限时 ${it.sec} 秒）` : ''}`;
  }
  // 资料分析：材料排在题干**上面**（考场上也是先给材料再问）
  $('#rq-mat').innerHTML = it.material
    ? `<div class="rq-mat-t">给定资料</div><div class="rq-mat-b">${esc(it.material)}</div>` : '';
  /* 宽屏（≥1500）上材料单独占一栏、和题干并排；没材料的题要退回两栏，
     否则左边空出一根白柱子。逐题判：同一组里有的题带材料有的不带。 */
  $('#view-realrun').classList.toggle('rq-3col', !!it.material);
  $('#rq-stem').textContent = it.stem;
  // 图形推理的题，图就是题本身 —— 题干只是一句「选择最合适的一个填入问号处」
  $('#rq-figs').innerHTML = (it.figs || []).map(f =>
    `<img src="/api/real/fig/${encodeURIComponent(f)}" alt="题目图" loading="lazy">`).join('');
  $('#rq-opts').innerHTML = it.options.map((o, j) => {
    const L = 'ABCD'[j];
    let cls = '';
    if (reveal) cls = L === it.answer ? ' right' : (L === chosen ? ' wrong' : '');
    return `<button class="rq-opt${cls}${chosen === L ? ' chosen' : ''}" data-rqo="${L}"
              ${reveal ? 'disabled' : ''}><span class="rq-l">${L}</span>${esc(o)}</button>`;
  }).join('');
  /* 错题本按钮跟着解析一起出：做错的题服务端已经自动收了，这里让人当场
     补一句错因、或者把不该收的（比如手滑点错）移出去 —— 不用等到复习时再翻本子。
     模考模式下答案还没揭晓，收错题无从谈起，交卷后的逐题回顾里才给。 */
  $('#rq-exp').innerHTML = reveal
    ? explainHtml(it) + `<div class="rq-wql">${wqlBtnHtml('realq', String(it.id))}</div>`
    : '';
  $('#rq-next').classList.toggle('hidden', !chosen);
  $('#rq-next').textContent = rqIdx + 1 >= rqItems.length ? '交卷看结果' : '下一题 →';
  /* 整卷（130 道）一次做不完是常态，背题模式也要能看见「已答几道」再决定是不是先交 ——
     所以进度按 paper 判，不按 rqExam：背题模式下 rqExam 是 false，只看它就只剩一个光秃秃的「交卷」。 */
  $('#rq-quit').textContent = (rqExam || rqMode === 'paper')
    ? `交卷（已答 ${Object.keys(rqAns).length}/${rqItems.length}）` : '交卷';
  /* 答题卡（P4）。原来这一页**只有「下一题」**，整卷 130 道想回头改第 47 题只能交卷重来。
     模考模式下答案没揭晓，只报「答过没答过」，不能透出对错——那就等于提前判卷。 */
  /* 标题和统计跟着这一组走。用时只算**答过的题**：没答的题没有秒数，
     算进去会把「均 71 秒/题」拉成一个假的低值。 */
  const secs = Object.values(rqSec);
  const used = secs.reduce((a, b) => a + b, 0);
  const mm = (n) => Math.floor(n / 60) + ':' + String(Math.round(n % 60)).padStart(2, '0');
  rqRelated(it, reveal && chosen !== it.answer);
  qsRender('#rq-side', {
    // 不在这儿 esc：qsRender 渲染 title 时自己会 esc，转两次的话卷名里的 & 会显示成 &amp;
    title: `${rqScope || it.qtype || '真题'} · ${rqItems.length} 题`,
    stat: secs.length
      ? `已答 ${Object.keys(rqAns).length} · 用时 ${mm(used)} · 均 ${Math.round(used / secs.length)} 秒/题`
      : `已答 ${Object.keys(rqAns).length} / ${rqItems.length}`,
    n: rqItems.length, cur: rqIdx,
    state: (i) => {
      const q = rqItems[i], a = rqAns[q.id];
      if (a === undefined) return '';
      return rqExam ? 'done' : (a === q.answer ? 'right' : 'wrong');
    },
    onJump: (i) => { if (i !== rqIdx) { rqIdx = i; rqRender(); } },
  });
}

/* 解析版式：**关键点排最前**，步骤一行一步，错项逐条。
   原卷解析折叠 —— 它内容权威但排版是 PDF 拉下来的一整片，默认展开会把结构化那几段淹掉。 */
function explainHtml(it) {
  const e = it.explain || {};
  const steps = e.steps || [], wrong = e.wrong || {};
  return `<div class="rq-ex">
    ${e.keypoint ? `<div class="rq-key"><span>关键</span>${esc(e.keypoint)}</div>` : ''}
    ${steps.length ? `<div class="rq-block"><h4>怎么做</h4><ol>${
      steps.map(s => `<li>${esc(s)}</li>`).join('')}</ol></div>` : ''}
    ${Object.keys(wrong).length ? `<div class="rq-block"><h4>错在哪</h4>${
      Object.keys(wrong).sort().map(k =>
        `<div class="rq-w"><i>${esc(k)}</i>${esc(wrong[k])}</div>`).join('')}</div>` : ''}
    ${e.tip ? `<div class="rq-tip">举一反三　${esc(e.tip)}</div>` : ''}
    ${e.official ? `<details class="rq-off"><summary>原卷解析</summary><pre>${
      esc(e.official)}</pre></details>` : ''}
  </div>`;
}

$('#rq-opts').addEventListener('click', e => {
  const b = e.target.closest('[data-rqo]');
  if (!b) return;
  const it = rqItems[rqIdx];
  rqAns[it.id] = b.dataset.rqo;
  /* ⚠️ 表停过之后 qtStop() 返回 0，**拿到 0 一律别写**：模考模式下选项不锁，
     改答案是常规操作 —— 第二次点选时表早停了，无条件覆盖会把这道题的用时
     从 45 秒抹成 0，交卷记录和超时统计跟着一起错。 */
  const used = qtStop();
  if (used) rqSec[it.id] = Math.round(used);
  rqRender();
});
$('#rq-next').onclick = () => { rqIdx++; rqRender(); };
$('#rq-quit').onclick = () => rqFinish();

/* 这一组题的错题收录状态。不 await —— 调用方先渲染，扫回来再刷按钮。 */
function rqScanWq(ids) {
  return wqlScan('realq', { keys: (ids || rqItems.map(x => x.id)).map(String) })
    .then(() => wqlRefreshBtns('#rq-exp'));
}

/* 错题本按钮：做题页和交卷后的逐题回顾共用一套（都挂在 #rq-exp 下）。 */
$('#rq-exp').addEventListener('click', e => {
  const b = e.target.closest('[data-wql]');
  if (!b) return;
  const qid = b.dataset.wql;
  const it = rqItems.find(x => String(x.id) === qid) || {};
  /* 模考模式下 rqItems 里**没有答案和解析**（服务端按模考规则剥掉了），
     交卷后的答案在 rqRes 里 —— 不合过来的话，在逐题回顾里手动收一道题，
     存进错题本的会是「正确答案 。」，解析也是空的。 */
  const res = rqRes[qid] || {};
  const ex = it.explain || res.explain || {};
  const ans = it.answer || res.answer || '';
  wqlOpen('realq', qid, {
    board: it.module || '行测', qtype: it.qtype || '',
    question: '【真题】' + (it.stem || '') + '\n' + (it.options || []).join('\n'),
    answer: `正确答案 ${ans}。${ex.keypoint || (ex.official || '').slice(0, 200)}`,
    note: '来自真题练习',
  }, () => wqlRefreshBtns('#rq-exp'));
});

async function rqFinish() {
  // 交卷按钮做完之后还在，不上锁的话再点一次就把同一批答案重复提交：
  // real_attempts 多插一批（做题数/正确率翻倍），review_state 又被推一档。
  if (rqDone) return;
  if (!Object.keys(rqAns).length) { toast('一道都没做'); return; }
  rqDone = true;
  qtStop(); qtTotalStop();
  try {
    const d = await api('/api/real/done', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      // mode/scope 是给**做题记录**用的：没有它们，记录列表上一排全是「智能刷」，
      // 认不出哪次是 2023 国考、哪次是定义判断专练。
      body: JSON.stringify({ answers: rqAns, seconds: rqSec, mode: rqMode, scope: rqScope,
        exam: rqExam }),
    });
    $('#rq-head').innerHTML = '';
    $('#rq-stem').textContent = '';
    $('#rq-opts').innerHTML = '';
    $('#rq-figs').innerHTML = '';
    $('#rq-mat').innerHTML = '';   // 新增容器别漏了清理，否则上一题的图会挂在成绩上方
    qsClear('#rq-side');           // 答题卡同理：留在成绩页上还能点，点一下就把题目盖回成绩上
    $('#rq-next').classList.add('hidden');
    $('#rq-quit').classList.add('hidden');
    // 逐题结果留一份：模考的答案和解析只有这里有，逐题回顾和「收错题」都要用
    (d.results || []).forEach(r => { rqRes[String(r.id)] = r; });
    // 超时统计：限时是按题型给的，所以「慢了几道」比「总共花了多久」有用得多
    const timed = rqItems.filter(x => rqSec[x.id] !== undefined);
    const slow = timed.filter(x => rqSec[x.id] > (x.sec || 60)).length;
    const used = timed.reduce((s, x) => s + (rqSec[x.id] || 0), 0);
    $('#rq-exp').innerHTML = `<div class="rq-done">
      <div class="rq-score"><b>${d.ok}</b> / ${d.total}<span>正确率 ${Math.round(d.acc * 100)}%</span></div>
      ${timed.length ? `<div class="rq-sub">共用时 ${qtFmt(used)}
        · ${slow ? `<b class="over">${slow} 道超时</b>` : '全部在限时内 👍'}</div>` : ''}
      ${d.wrong_added ? `<p class="rq-hint">${d.wrong_added} 道错题已进错题本，明天会在「今日复习」里再见到。</p>`
    : '<p class="rq-hint">全对，这批题会按遗忘曲线往后排。</p>'}
      <div class="rq-done-acts">
        <button class="btn" id="rq-again">再来一组</button>
        <button class="btn ghost" id="rq-torec">${artEm('📋')} 做题记录</button>
      </div></div>
      ${rqExam ? rqReviewHtml(d.results) : ''}`;
    $('#rq-again').onclick = () => rqStart({ mode: 'smart', n: rqN }, '智能刷');
    $('#rq-torec').onclick = () => openRealRecords();
    // 服务端刚把做错的题收进了错题本，状态要重新拉一遍，否则逐题回顾里那些按钮
    // 会全显示成「未收」，点一下才发现早就在里面了。成绩已经画出来了，这步不用挡着。
    rqScanWq();
  } catch (e) { rqDone = false; toast(e.message, true); }
}

/* 模考交卷后的逐题回顾：模考过程中一直没给答案，全部答案和解析都在这儿一次性给。 */
function rqReviewHtml(results) {
  const byId = {}, noById = {};
  // 题号要用**卷面上的位置**，不能用结果数组下标：results 只含作答过的题，
  // 130 道的模考里只答了第 40/55/77 三道，按下标就显示成「第1/2/3题」，回原卷根本找不到
  rqItems.forEach((it, k) => { byId[it.id] = it; noById[it.id] = k + 1; });
  return `<div class="rq-review"><div class="rq-sec">逐题回顾</div>${
    (results || []).map((r) => {
      const it = byId[r.id] || {};
      const sec = rqSec[r.id], over = sec !== undefined && sec > (it.sec || 60);
      return `<div class="rq-rv${r.correct ? '' : ' bad'}">
        <div class="rq-rv-h"><b>第 ${noById[r.id] || '?'} 题</b>
          <span>${r.correct ? '✓ 对' : `✗ 你选 ${esc(r.your || '未答')}，正确 ${esc(r.answer)}`}</span>
          ${sec === undefined ? '' : `<span class="rq-rv-sec${over ? ' over' : ''}">${Math.round(sec)}s
            ${over ? `/ 限 ${it.sec}s` : ''}</span>`}
          ${wqlBtnHtml('realq', String(r.id))}</div>
        ${r.material ? `<div class="rq-mat"><div class="rq-mat-t">给定资料</div><div class="rq-mat-b">${esc(r.material)}</div></div>` : ''}
        <div class="rq-rv-q">${esc((it.stem || '').slice(0, 120))}</div>
        ${(r.figs || []).map(f =>
    `<img class="rq-rv-fig" src="/api/real/fig/${encodeURIComponent(f)}" alt="题目图" loading="lazy">`).join('')}
        ${r.correct ? '' : explainHtml({ explain: r.explain })}
      </div>`;
    }).join('')}</div>`;
}

/* ================= 做题记录 =================
   real_attempts 是逐题流水，回答不了「上周那套 2023 国考我做得怎么样」。
   这里按**组**回看：哪十道题、哪几道超时、当时选的什么、解析是什么。
   和专项练的「做题记录」是一个形状 —— 两个模块的记录看着一样，不用重新学。 */
function openRealRecords() {
  push({ view: 'realrec', title: '真题 · 做题记录' });
  return loadRealRecords();
}

/* 只重画列表、**不压栈**：删完记录后要刷新列表，再 push 一次的话栈里会多一层
   realrec，返回键看着像失灵（按一下还在记录页，得按两下才退出去）。 */
async function loadRealRecords() {
  const box = $('#rqr-list');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/real/records');
    if (!d.items.length) {
      box.innerHTML = '<p class="empty">还没有记录。做完一组真题（或交一次卷）就会留档，可以逐题回看。</p>';
      return;
    }
    box.innerHTML = d.items.map(r => {
      const acc = r.total ? Math.round(100 * r.correct / r.total) : 0;
      return `<div class="drr-row" data-rqrec="${r.id}">
        <div class="drr-main">
          <b>${esc(r.scope || r.mode_name)}</b>
          <span class="drr-tag">${esc(r.mode_name)}${r.exam ? ' · 模考' : ''}</span>
        </div>
        <div class="drr-meta">${esc((r.created_at || '').slice(5, 16))}
          · ${r.correct}/${r.total} 题
          · <b class="${acc >= 60 ? 'ok' : 'bad'}">${acc}%</b>
          · 用时 ${qtFmt(r.seconds || 0)}</div>
        <span class="drr-go">回看 ›</span></div>`;
    }).join('');
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

$('#rqr-list').addEventListener('click', e => {
  const row = e.target.closest('[data-rqrec]');
  if (row) openRealRecord(+row.dataset.rqrec);
});

async function openRealRecord(rid) {
  push({ view: 'realrecd', title: '回看这一组' });
  const box = $('#rqd-body');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/real/record/' + rid);
    rqRecItems = d.items || [];
    const acc = d.total ? Math.round(100 * d.correct / d.total) : 0;
    const slow = d.items.filter(x => x.seconds > (x.sec || 60)).length;
    $('#rqd-head').innerHTML = `<div class="dr-res">
      <div class="dr-score"><b>${d.correct}</b> / ${d.total}<span>${acc}%</span></div>
      <div class="dr-sub">${esc(d.scope || '')} · ${esc((d.created_at || '').slice(0, 16))}
        · 用时 ${qtFmt(d.seconds || 0)}${slow ? ` · <b class="over">${slow} 道超时</b>` : ''}</div>
      <button class="btn ghost tiny" id="rqd-del">删除这条记录</button></div>`;
    $('#rqd-del').onclick = async () => {
      // 只删回看记录，作答流水不动 —— 说清楚，否则会被当成「把这次练习一笔勾销」
      if (!(await appConfirm('删除这条回看记录？做题进度和正确率统计不受影响。'))) return;
      try { await api('/api/real/record/' + rid, { method: 'DELETE' }); toast('已删除'); back(); loadRealRecords(); }
      catch (err) { toast(err.message, true); }
    };
    box.innerHTML = d.items.map((it, i) => {
      const over = it.seconds > (it.sec || 60);
      return `<div class="rq-rv${it.correct ? '' : ' bad'}">
        <div class="rq-rv-h"><b>第 ${i + 1} 题</b>
          ${it.qtype ? `<span class="rq-tag">${esc(it.qtype)}</span>` : ''}
          <span>${it.correct ? '✓ 对' : `✗ 你选 ${esc(it.your || '未答')}，正确 ${esc(it.answer)}`}</span>
          <span class="rq-rv-sec${over ? ' over' : ''}">${Math.round(it.seconds)}s${over ? ` / 限 ${it.sec}s` : ''}</span>
          ${wqlBtnHtml('realq', String(it.id))}</div>
        ${it.material ? `<div class="rq-mat"><div class="rq-mat-t">给定资料</div><div class="rq-mat-b">${esc(it.material)}</div></div>` : ''}
        <div class="rq-rv-q">${esc(it.stem || '')}</div>
        ${(it.figs || []).map(f =>
        `<img class="rq-rv-fig" src="/api/real/fig/${encodeURIComponent(f)}" alt="题目图" loading="lazy">`).join('')}
        <div class="rq-rv-opts">${(it.options || []).map((o, j) => {
        const L = 'ABCD'[j];
        return `<div class="rq-rv-o${L === it.answer ? ' right' : (L === it.your ? ' wrong' : '')}">
            <span class="rq-l">${L}</span>${esc(o)}</div>`;
      }).join('')}</div>
        ${it.correct ? '' : explainHtml({ explain: it.explain })}</div>`;
    }).join('');
    // 这一组题的错题收录状态：回看时也能收/改/删，和做题当下是同一套按钮。
    // 不 await —— 记录内容先出来，按钮状态随后补上。
    wqlScan('realq', { keys: rqRecItems.map(x => String(x.id)) })
      .then(() => wqlRefreshBtns('#rqd-body'));
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

/* 回看页的错题按钮：内容从这条记录的**快照数据**里取，不从 DOM 里抠。
   抠 DOM 的话拿到的只有题干（选项和答案都在数据里、页面上却是分开渲染的），
   收进去就是一条没有选项、没有答案的错题；元素缺失时还会存成「【真题】undefined」。 */
$('#rqd-body').addEventListener('click', e => {
  const b = e.target.closest('[data-wql]');
  if (!b) return;
  const qid = b.dataset.wql;
  const it = rqRecItems.find(x => String(x.id) === qid) || {};
  const ex = it.explain || {};
  wqlOpen('realq', qid, {
    board: it.module || '行测', qtype: it.qtype || '',
    question: '【真题】' + (it.stem || '') + '\n' + (it.options || []).join('\n'),
    answer: `正确答案 ${it.answer || ''}。${ex.keypoint || (ex.official || '').slice(0, 200)}`,
    note: '来自真题练习',
  }, () => wqlRefreshBtns('#rqd-body'));
});

/** 从错题本的「重做原题」跳进来：直接按这道题的**题型**起一组真题。
    题型不带模块筛 —— 错题本里存的板块可能是「行测」这种兜底值，带上反而筛空。
    这道题本身会被「错过且到期」的排序顶到最前（见 mods/realq.py 的 _pick）。 */
function rqPractice(qtype) {
  const t = (qtype || '').trim();
  return t ? rqStart({ mode: 'type', qtype: t, n: rqN }, t)
    : rqStart({ mode: 'smart', n: rqN }, '智能刷');
}

window.openRealq = openRealq;
window.openRealRecords = openRealRecords;
window.rqPractice = rqPractice;

/* 首页卡片上的红点：/api/real/overview 早就返回了 due（该重刷的道数），
   之前放了个 #realq-badge 元素却没人填 —— 最该提醒的数字一直不显示。
   仿 refreshReviewBadge 的写法，静默失败（没登录/接口挂了不该弹错）。 */
async function refreshRealqBadge() {
  const el = $('#realq-badge');
  if (!el) return;
  try {
    const d = await api('/api/real/overview');
    el.textContent = d.due > 99 ? '99+' : d.due;
    el.classList.toggle('hidden', !d.due);
  } catch (e) { /* 静默 */ }
}
window.refreshRealqBadge = refreshRealqBadge;
