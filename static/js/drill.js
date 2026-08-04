/* 专项练（行测六大板块）
 *
 * 由 app.js 按它自己的区段边界切出（原 L4607-4887）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, DT_L, api, back, c,
   dtMaterial, esc, push, toast,
   qtStart, qtStop, wqlBtnHtml, wqlOpen, wqlRefreshBtns, wqlScan */

/* ============= 专项练（行测六大板块）=============
   资料分析 / 判断推理 / 数量关系 —— 题型固定、有套路、拼速度，**题由程序生成**，答案由构造保证。
   常识判断 / 政治理论 / 言语理解 —— 考的是知识，构造不出来，**由 AI 按考试标准出题**；
     出好的题攒进题库（drill_bank），下次直接取，不用每次等十几秒。
   三档难度**真正改变题目**（不是贴个标签）；难度系数 = 预期得分率，做完告诉你比预期高还是低。
   两种模式：背题（选完即判 + 解析）/ 测试（做完交卷、服务端判分）。题量 5/10/15/20。
   每次做完**留一条完整记录**，可以回看每一题 —— 不是做完就丢。 */
/* 计时交给 js/qtimer.js（三个刷题模块共用），这儿不再自己养一个 setInterval */
let drBoard = '', drType = '', drItems = [], drIdx = 0, drAns = [], drSec = [];
let drLimit = 60, drLevel = 'mid', drN = 10, drMode = 'study', drToken = '', drCoef = 0.6, drLevels = [];
/* 题源开关：ai=AI 出题（老行为）/ real=真题练习 / mix=真题优先、不够的 AI 补。
   真题模式**没有难度档**——真题不带难度标签，硬套是假的（原先「考场真实」那档发的
   其实就是 AI 题）。所以切到 real 时把难度行换成年份行。 */
let drSrc = 'ai', drYear = 0;

function openDrill(board) {
  drBoard = board;
  push({ view: 'drill', title: board + ' · 专项练' });
  loadDrillTypes();
}
let drTypesData = null;      // 上一次拉到的题型清单
let drTypesKey = '';         // 那一次是按 板块|难度|年份 哪一组拉的
/* 只有真题模式才带年份筛（drStart 里 `year_min: drSrc === 'real' ? drYear : 0`），
   所以「这次该按哪个年份看存量」由这一个函数说了算，前后端口径才对得上。 */
function drNeedYear() { return drSrc === 'real' ? drYear : 0; }

/* 存量数字必须和**将要发出的请求**同口径，否则就是在撒谎：
   · 不带年份拉、却按「近 3 年」出题 → 多报（语境分析显示 334、实际只有 74）
   · 带年份拉、却切到混合模式出题   → 少报（显示 74、实际按 334 取）
   两个方向都出过，所以缓存要连「按哪个年份拉的」一起记，对不上就重拉。 */
async function loadDrillTypes() {
  const y = drNeedYear();
  /* 缓存键必须**三样都带上**：板块换了、难度换了，响应内容都会变
     （每个题型的正确率/做题数是按 level 统计的）。只比年份的话，
     换板块会直接短路、把上一个板块的题型渲染出来。 */
  const key = `${drBoard}|${drLevel}|${y}`;
  if (drTypesData && drTypesKey === key) { renderDrillTypes(); return; }
  const box = $('#dr-types');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const yq = y ? `&year_min=${y}` : '';
    const d = await api(`/api/drill/types?board=${encodeURIComponent(drBoard)}&level=${drLevel}${yq}`);
    drTypesData = d; drTypesKey = key;
    renderDrillTypes();
  } catch (e) { drTypesData = null; drTypesKey = ''; box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
function renderDrillTypes() {
  const box = $('#dr-types');
  const d = drTypesData;
  if (!d) return;
  try {
    drLimit = d.limit; drLevels = d.levels; drCoef = d.coef;
    $('#dr-intro').innerHTML = d.ai
      ? `这一块考的是<b>知识</b>，题由 AI 按考试标准出，<b>并且必须过第二个模型的独立核验</b>
         —— 两个模型答案不一致的题<b>不会发给你做</b>（实测能筛掉约 14%，其中有真的事实错误）。
         每题限时 ${d.limit} 秒。`
      : `这一块靠<b>练</b>不靠背：题型固定、有套路、拼速度。题由<b>程序生成</b>，答案由构造保证。每题限时 ${d.limit} 秒，做完给这一类的秒杀技巧。`;
    $('#dr-levels').innerHTML = d.levels.map(l =>
      `<button class="dr-lv${l.k === drLevel ? ' on' : ''}" data-drl="${l.k}">
         <b>${esc(l.name)}</b><span>${l.coef.toFixed(2)}</span></button>`).join('');
    drCoefTip();
    // 讲义里的「解题方法」章 —— 是方法不是题型，单独摆出来（做题时的秒杀技巧就出自这里）
    $('#dr-methods').innerHTML = (d.methods || []).length
      ? `<div class="dr-mth"><div class="dr-mth-t">📐 解题方法（讲义第一章）</div>
          ${d.methods.map(m => `<div class="dr-mth-i">· ${esc(m)}</div>`).join('')}</div>` : '';
    $('#dr-missing').innerHTML = d.missing
      ? `<div class="dr-miss">⚠️ ${esc(d.missing)}</div>` : '';
    box.innerHTML = d.types.map((t, i) => {
      const done = t.n > 0;
      const weak = done && t.acc < Math.round(drCoef * 100);   // 低于这个难度的预期得分率 = 薄弱
      /* 真题模式下存量不够的题型**置灰**，别假装有：政治理论那四个题型真题只有
         个位数、文章阅读一道都没有。点进去只会撞一个 404，不如一眼看见。 */
      const noReal = drSrc === 'real' && !t.real_ok;
      return `<div class="dr-card${weak ? ' weak' : ''}${noReal ? ' dr-off' : ''}"
        data-drt="${noReal ? '' : esc(t.type)}"${noReal ? ' data-droff="1"' : ''}>
        <div class="dr-card-h">
          <b><span class="dr-no">${t.ord + 1}</span>${esc(t.type)}</b>
          ${done ? `<span class="dr-acc${weak ? ' bad' : ''}">${t.acc}%</span>` : '<span class="dr-new">没练过</span>'}
        </div>
        ${t.desc ? `<p class="dr-desc">${esc(t.desc)}</p>` : ''}
        <div class="dr-meta">
          <span class="dr-eng ${t.eng}">${t.eng === 'prog' ? '程序出题' : 'AI 出题'}</span>
          ${t.eng === 'ai' && t.bank_all
            ? `<span class="dr-bank" title="AI 出的题要过第二个模型的独立核验才发给你做；答案不一致的不出">
                 ✓ ${t.bank_ok} 道已核验${t.bank_all > t.bank_ok ? `（筛掉 ${t.bank_all - t.bank_ok}）` : ''}</span>` : ''}
          ${drSrc === 'ai' ? '' : `<span class="dr-real${t.real_ok ? '' : ' none'}">
             ${t.real_n ? `📄 真题 ${t.real_n} 道` : '📄 无真题'}</span>`}
          ${done ? `做过 ${t.n} 题 · 平均 ${t.sec} 秒${t.sec > drLimit ? '（超时）' : ''}` : `限时 ${drLimit} 秒/题`}</div>
      </div>`;
    }).join('') + (() => {
      /* 混合练也要跟着置灰。它原先是拼在后面的字符串常量、没参与上面的 noReal 判断，
         于是政治理论那种四个题型全灰的板块，混合练还亮着，点了必撞 404。
         能不能开**由服务端算**（real_mix_ok）：混合练是逐题型分名额的，
         「板块总量」判不了——10 个题型各 3 道，总量 30 看着够，实际每型都出不满。
         阈值也别在前端写死，改门槛要同步三处，漏一处就是「没置灰却收到 404」。 */
      const off = drSrc === 'real' && !d.real_mix_ok;
      return `<div class="dr-card dr-all${off ? ' dr-off' : ''}" data-drt=""${off ? ' data-droff="1"' : ''}>
        <div class="dr-card-h"><b>🎲 混合练</b></div>
        <p class="dr-desc">所有题型随机出，模拟真实考场</p>
        <div class="dr-meta">${drSrc === 'ai' ? '' : `<span class="dr-real${d.real_mix_ok ? '' : ' none'}">📄 真题 ${d.real_total || 0} 道 / ${d.real_types_ok || 0} 个题型够刷</span> · `}限时 ${drLimit} 秒/题</div></div>`;
    })();
  } catch (e) {
    // renderDrillTypes 现在会被题源点击直接调用，那条路上抛异常就是未捕获，
    // 表现为卡片停在旧内容、没有任何提示
    box.innerHTML = `<p class="empty">${esc(e.message)}</p>`;
  }
}
function drCoefTip() {
  const l = drLevels.find(x => x.k === drLevel) || {};
  // 「难度系数」在公考里就是**得分率**。必须说清它是什么，不然「0.40」看着像分数
  $('#dr-coef').innerHTML = `<b>难度系数 ${(l.coef || 0).toFixed(2)}</b>
    <span>= 这个难度下<b>预期能做对 ${Math.round((l.coef || 0) * 100)}%</b>。${esc(l.desc || '')}。
    做完会告诉你<b>比预期高还是低</b>，心里有数。</span>`;
}
$('#dr-srcs').addEventListener('click', e => {
  const b = e.target.closest('[data-drs]'); if (!b) return;
  drSrc = b.dataset.drs;
  document.querySelectorAll('#dr-srcs .chip').forEach(x => x.classList.toggle('active', x === b));
  drSrcTip();
  loadDrillTypes();          // 年份口径没变就只重渲染，变了才真拉（见 loadDrillTypes）
});
$('#dr-years').addEventListener('click', e => {
  const b = e.target.closest('[data-dry]'); if (!b) return;
  drYear = +b.dataset.dry;
  document.querySelectorAll('#dr-years .chip').forEach(x => x.classList.toggle('active', x === b));
  loadDrillTypes();          // 存量是按年份算的，换年份必须重拉
});
/* 置灰用的门槛由服务端给（real_min），前端不再自己写死 5 */
function drSrcTip() {
  const real = drSrc === 'real';
  /* 难度行和年份行**互斥**：真题没有难度可调，AI 题没有年份可筛 */
  $('#dr-lvrow').classList.toggle('hidden', real);
  $('#dr-coef').classList.toggle('hidden', real);
  $('#dr-yrrow').classList.toggle('hidden', !real);
  $('#dr-srctip').innerHTML = {
    ai: '题由 AI 按真题画像出（篇幅、设问措辞、干扰项都对着真题来），<b>必须过第二个模型的独立核验</b>才发给你。量大管够。',
    real: '直接做<b>历年真题</b>，答案来自原卷、最权威。<b>题量有限、做完不会再有</b>，所以按「没做过 &gt; 做错过 &gt; 做对过」的顺序给你。<br>在这儿做过的题，「历年真题」模块不会再当新题推给你 —— 两边进度是通的。',
    mix: '<b>真题优先</b>，这个题型的真题不够了（或都做过了）才用 AI 出的补。每道题上都标着来源。',
  }[drSrc];
}
drSrcTip();
$('#dr-levels').addEventListener('click', e => {
  const b = e.target.closest('[data-drl]'); if (!b) return;
  drLevel = b.dataset.drl;
  loadDrillTypes();
});
$('#dr-ns').addEventListener('click', e => {
  const b = e.target.closest('[data-drn]'); if (!b) return;
  drN = +b.dataset.drn;
  document.querySelectorAll('#dr-ns .chip').forEach(x => x.classList.toggle('active', x === b));
});
$('#dr-modes').addEventListener('click', e => {
  const b = e.target.closest('[data-drm]'); if (!b) return;
  drMode = b.dataset.drm;
  document.querySelectorAll('#dr-modes .chip').forEach(x => x.classList.toggle('active', x === b));
  drModeTip();
});
function drModeTip() {
  $('#dr-modetip').textContent = drMode === 'exam'
    ? '答案不提前下发，全部做完交卷、由服务端判分，更像考试'
    : '每题选完立刻判、马上给解析和秒杀技巧 —— 边做边学';
}
drModeTip();
$('#dr-types').addEventListener('click', e => {
  const c = e.target.closest('[data-drt]'); if (!c) return;
  if (c.dataset.droff) {         // 置灰的别静默吞掉点击，说清楚为什么
    toast('这个题型真题太少，换「AI 出题」吧');
    return;
  }
  drStart(c.dataset.drt);
});
$('#dr-recs').onclick = () => openDrillRecs();

async function drStart(type) {
  drType = type;
  toast('出题中…');
  try {
    /* 20 秒超时：服务端已改成「只从题库取，不现场调 AI」，正常是毫秒级返回。
       超过 20 秒一定是哪里不对，宁可报错也别让人对着没反应的按钮干等。 */
    const d = await api('/api/drill/quiz', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, timeoutMs: 20000,
      body: JSON.stringify({ board: drBoard, type, n: drN, level: drLevel,
        exam: drMode === 'exam', src: drSrc, year_min: drSrc === 'real' ? drYear : 0 }),
    });
    drItems = d.items; drLimit = d.limit; drCoef = d.coef; drToken = d.token || '';
    drIdx = 0; drAns = []; drSec = [];
    if (d.short) toast(`题库这一格还差 ${d.short} 道，后台正在补，先做这 ${d.items.length} 道`);
    // 没做过的题不够了，拿最久没做的顶上。得说一声：不然「怎么又是这道」只能靠自己发现，
    // 而这恰恰是该去补库的信号（后台已经排上了）。
    else if (d.again) toast(`没做过的题不够了，这组里有 ${d.again} 道是复习题，后台正在补新题`);
    push({ view: 'drillrun', title: (type || '混合') + ' · 专项练' });
    drRender();
    drScanWq();          // 按钮状态不挡首屏（见 drScanWq）
  } catch (e) { toast(e.message, true); }
}

function drRender() {
  qtStop();
  if (drIdx >= drItems.length) { drResult(); return; }
  const it = drItems[drIdx];
  /* figs **有两种形状**：figgen 出的图形题是 {seq, opts}（内联 SVG），
     真题的是文件名数组（走 /api/real/fig/<name> 取）。只判真假会把真题的图整个丢掉。 */
  const isFig = !!(it.figs && it.figs.seq);
  const realFigs = Array.isArray(it.figs) ? it.figs : [];
  const lvName = (drLevels.find(x => x.k === drLevel) || {}).name || '';
  $('#dr-head').innerHTML = `
    <div class="dr-prog">第 <b>${drIdx + 1}</b> / ${drItems.length} 题
      <span class="dr-tag">${esc(it.qtype || '')}</span>
      ${it.src === 'real' ? '<span class="dr-tag dr-tsrc">真题</span>' : ''}
      <span class="dr-tag lv">${esc(lvName)}</span></div>
    <div class="q-clock" id="dr-clock"></div>`;
  const chosen = drAns[drIdx];
  const opts = isFig
    ? it.figs.opts.map((svg, j) => `<button class="dt-opt dt-figo${chosen === DT_L[j] ? ' chosen' : ''}"
        data-dro="${DT_L[j]}"><span class="dt-figl">${DT_L[j]}</span>${svg}</button>`).join('')
    : (it.options || []).map((o, j) => `<button class="dt-opt${chosen === DT_L[j] ? ' chosen' : ''}"
        data-dro="${DT_L[j]}">${esc(o)}</button>`).join('');
  const seq = isFig ? `<div class="dt-seq">${it.figs.seq.join('')}<span class="dt-qm">?</span></div>` : '';
  // 测试模式要能翻回去改（考场就是这样），所以给上下题按钮；背题模式选完即判，不用
  const nav = drMode === 'exam' ? `<div class="dr-nav">
      <button class="btn" id="dr-prev" ${drIdx ? '' : 'disabled'}>← 上一题</button>
      <button class="btn primary" id="dr-nextq">${drIdx + 1 >= drItems.length ? '交卷看结果' : '下一题 →'}</button>
    </div>` : '';
  $('#dr-body').innerHTML = `<div class="dt-q">${dtMaterial(it.material, drIdx)}
    ${realFigs.map(f => `<img class="dt-rfig" src="/api/real/fig/${encodeURIComponent(f)}" alt="题目配图">`).join('')}
    <div class="dt-qt">${esc(it.q)}</div>${seq}
    <div class="dt-opts${isFig ? ' dt-figs' : ''}">${opts}</div>
    <div id="dr-exp"></div>${nav}</div>`;
  if (drMode === 'exam') {
    $('#dr-prev').onclick = () => { drStopTimer(); drIdx--; drRender(); };
    $('#dr-nextq').onclick = () => { drStopTimer(); drIdx++; drRender(); };
  }
  /* 倒计时按**这道题的题型**给（服务端算好在 it.sec 里），不是板块一刀切：
     混合练一组里类比推理 25 秒、分析推理 70 秒，用同一个数就没意义了。
     超时不打断，只转红记「超时 +12 秒」——考场上超时也得把题做完，
     而超了多少秒才是这道题真实的成绩。 */
  const already = drSec[drIdx] || 0;
  if (drMode !== 'exam' && drAns[drIdx] !== undefined) {
    // 背题模式下答过的题（点「上一题」翻回来）不重新起表，否则回看的时间会算进用时
    const over = already > drQLimit(it);
    $('#dr-clock').className = 'q-clock' + (over ? ' over' : '');
    $('#dr-clock').textContent = `⏱ 用时 ${Math.round(already)} 秒`;
  } else {
    qtStart('#dr-clock', drQLimit(it), { used: already });
  }
}
/* 这道题的限时：服务端按题型给的优先，老接口没带就退回板块基准 */
function drQLimit(it) { return (it && it.sec) || drLimit; }
function drStopTimer() {
  const used = qtStop();
  if (used) drSec[drIdx] = used;      // qtStart 已把之前用掉的秒数算进去了，这里直接覆盖
}

$('#dr-body').addEventListener('click', e => {
  const b = e.target.closest('[data-dro]');
  if (b) { drPick(b.dataset.dro); return; }
  if (e.target.closest('#dr-next')) { drIdx++; drRender(); }
});

function drPick(letter) {
  const it = drItems[drIdx];
  if (drMode === 'exam') {          // 测试模式：只记选择，不判、不给解析（答案本来也没下发到前端）
    drAns[drIdx] = letter;
    document.querySelectorAll('#dr-body [data-dro]').forEach(b =>
      b.classList.toggle('chosen', b.dataset.dro === letter));
    return;
  }
  if (drAns[drIdx] !== undefined) return;             // 背题模式：答过就不能改
  drStopTimer();
  const sec = drSec[drIdx];
  drAns[drIdx] = letter;
  const ok = letter === it.answer;
  document.querySelectorAll('#dr-body [data-dro]').forEach(b => {
    b.disabled = true;
    if (b.dataset.dro === it.answer) b.classList.add('correct');
    else if (b.dataset.dro === letter) b.classList.add('wrong');
  });
  const lim = drQLimit(it);
  const over = sec > lim;
  const bold = (t) => esc(t || '').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  $('#dr-exp').innerHTML = `
    <div class="dr-verdict ${ok ? 'ok' : 'no'}">${ok ? '✅ 对了' : '❌ 错了'}
      · 用时 <b class="${over ? 'over' : ''}">${sec.toFixed(0)} 秒</b>${over ? `（限时 ${lim} 秒，慢了）` : ''}
      · 正确答案 <b>${esc(it.answer)}</b></div>
    <div class="dt-exp">${bold(it.explain)}</div>
    ${it.tip ? `<div class="dr-tip">⚡ <b>秒杀技巧</b>：${bold(it.tip)}</div>` : ''}
    ${/* 做错的题服务端交卷时才自动收；这里给个当场的口子：补错因、或者把手滑点错的移出去 */''}
    ${it.wq_key ? `<div class="dr-wql">${wqlBtnHtml(it.wq_kind || 'drill', it.wq_key)}</div>` : ''}
    <button class="btn primary" id="dr-next">${drIdx + 1 >= drItems.length ? '看结果' : '下一题 →'}</button>`;
}

/* 这一组里哪些题已经在错题本（第二遍练到同一道题时，按钮该是亮的）。
   真题模式的题身份是 realq/真题 id，AI 题是 drill/题干指纹 —— 分两批问。
   **不 await**：这是次要信息，挡在首屏前面会让人多等一个来回才看到题。 */
function drScanWq() {
  return Promise.all(['realq', 'drill'].map(k => {
    const keys = drItems.filter(x => (x.wq_kind || 'drill') === k).map(x => x.wq_key);
    return keys.length ? wqlScan(k, { keys }) : null;
  })).then(() => wqlRefreshBtns('#dr-body'));
}

/* 错题本按钮（做题页 + 结果页共用）：内容从当前题里取，身份用服务端给的 wq_key。 */
$('#dr-body').addEventListener('click', e => {
  const b = e.target.closest('[data-wql]');
  if (!b) return;
  const it = drItems.find(x => x.wq_key === b.dataset.wql) || {};
  wqlOpen(b.dataset.wqlkind, b.dataset.wql, {
    board: it.module || drBoard, qtype: it.qtype || drType,
    question: (it.q || '') + '\n' + (it.options || []).join('\n'),
    answer: `正确答案 ${it.answer || ''}。${it.explain || ''}`,
    note: '来自专项练',
  }, () => wqlRefreshBtns('#dr-body'));
});

async function drResult() {
  drStopTimer();
  $('#dr-head').innerHTML = '';
  $('#dr-body').innerHTML = '<p class="empty">判分中…</p>';
  const answers = {}, seconds = {};
  drItems.forEach((_, i) => { answers[i] = drAns[i] || ''; seconds[i] = drSec[i] || 0; });
  const body = { board: drBoard, type: drType, level: drLevel, exam: drMode === 'exam', answers, seconds };
  if (drToken) body.token = drToken;      // 测试模式：题在服务端，前端手里根本没有答案
  else body.items = drItems;
  try {
    const r = await api('/api/drill/done', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const avg = drSec.reduce((a, b) => a + b, 0) / (drSec.length || 1);
    // 超时要**逐题按各自的限时**算：混合练里 25 秒的类比推理和 80 秒的排列组合
    // 拿板块基准一起比，慢的题被放过、快的题被冤枉
    const slow = drItems.filter((it, i) => (drSec[i] || 0) > drQLimit(it)).length;
    const pct = Math.round(r.acc * 100), exp = Math.round(r.coef * 100);
    const good = r.vs >= 0;
    $('#dr-body').innerHTML = `
      <div class="dr-done">
        <div class="dr-score">${r.ok} / ${r.total}</div>
        <div class="dr-vs ${good ? 'good' : 'bad'}">
          正确率 <b>${pct}%</b> · 这个难度预期 ${exp}%
          → <b>${good ? '高出' : '低了'} ${Math.abs(Math.round(r.vs * 100))} 个点</b>
        </div>
        <div class="dr-sub">平均用时 <b class="${slow ? 'over' : ''}">${avg.toFixed(0)} 秒</b>
          ${slow ? `· 有 ${slow} 题超时（限时按题型给）` : '· 都在各自限时内 👍'}</div>
        ${r.wrong_added ? `<p class="dr-wq">错的 ${r.wrong_added} 题已自动进错题本</p>` : ''}
        ${/* 逐题的错题按钮：做错的题在这儿一次过一遍，补错因比事后翻本子记得清 */''}
        <div class="dr-wqlist">${drItems.map((it, i) => {
      const res = (r.results || [])[i] || {};
      if (res.correct || !it.wq_key) return '';
      return `<div class="dr-wqrow"><span>第 ${i + 1} 题 ${esc((it.q || '').slice(0, 22))}…</span>
        ${wqlBtnHtml(it.wq_kind || 'drill', it.wq_key)}</div>`;
    }).join('')}</div>
        <div class="dr-acts">
          <button class="btn primary" id="dr-again">🔄 再来 ${drN} 题</button>
          <button class="btn" id="dr-see">📋 看每题详情</button>
          <button class="btn" id="dr-back">换个题型</button>
        </div>
      </div>`;
    $('#dr-again').onclick = () => drStart(drType);
    $('#dr-see').onclick = () => openDrillRec(r.rid);
    $('#dr-back').onclick = () => { back(); loadDrillTypes(); };
    // 交卷时服务端把做错的题收进了错题本，按钮状态得重新拉一遍（成绩已经画出来了，不用挡着）
    drScanWq();
  } catch (e) { $('#dr-body').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

/* ---- 做题记录：做过的都留着，可以回看每一题（不是做完就丢） ---- */
async function openDrillRecs() {
  push({ view: 'drillrec', title: '做题记录' });
  const box = $('#drr-list');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/drill/records');
    box.innerHTML = d.items.length ? d.items.map(x => {
      const acc = Math.round(100 * x.correct / (x.total || 1));
      const good = acc >= Math.round(x.coef * 100);      // 和这个难度的预期得分率比
      return `<div class="wr-day done" data-drrec="${x.id}">
        <div class="wr-day-d">${esc(x.board)}</div>
        <div class="wr-day-m">
          <b>${esc(x.qtype || '混合')}</b>
          <span class="wr-tag">${esc(x.level_name)}</span>
          <span class="wr-tag">${x.mode === 'exam' ? '测试' : '背题'}</span>
          <span class="dr-acc${good ? '' : ' bad'}">${x.correct}/${x.total} · ${acc}%</span>
          <span class="wr-w">${Math.round(x.seconds)} 秒 · ${esc((x.created_at || '').slice(5, 16))}</span>
        </div>
      </div>`;
    }).join('') : '<p class="empty">还没做过题。</p>';
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#drr-list').addEventListener('click', e => {
  const c = e.target.closest('[data-drrec]'); if (c) openDrillRec(+c.dataset.drrec);
});
async function openDrillRec(rid) {
  push({ view: 'drillrecd', title: '这次做的题' });
  $('#drd-head').innerHTML = '<p class="empty">加载中…</p>';
  $('#drd-body').innerHTML = '';
  try {
    const d = await api('/api/drill/record/' + rid);
    const acc = Math.round(100 * d.correct / (d.total || 1));
    $('#drd-head').innerHTML = `<div class="dr-prog">${esc(d.board)} · ${esc(d.qtype || '混合')}
      <span class="dr-tag lv">${esc(d.level)}</span></div>
      <div class="dr-clock">${d.correct}/${d.total} · ${acc}%</div>`;
    $('#drd-body').innerHTML = d.items.map((it, i) => {
      const r = d.answers[i] || {};
      const isFig = !!(it.figs && it.figs.seq);
      const rfg = Array.isArray(it.figs) ? it.figs : [];
      const cls = (L) => (L === it.answer ? ' correct' : (L === r.your ? ' wrong' : ''));
      const opts = isFig
        ? it.figs.opts.map((svg, j) => `<button class="dt-opt dt-figo${cls(DT_L[j])}" disabled>
            <span class="dt-figl">${DT_L[j]}</span>${svg}</button>`).join('')
        : (it.options || []).map((o, j) => `<button class="dt-opt${cls(DT_L[j])}" disabled>${esc(o)}</button>`).join('');
      return `<div class="dt-q">${dtMaterial(it.material, i, i ? d.items[i - 1].material : null)}
        ${rfg.map(f => `<img class="dt-rfig" src="/api/real/fig/${encodeURIComponent(f)}" alt="题目配图">`).join('')}
        <div class="dt-qt">${r.correct ? '✅' : '❌'} ${i + 1}. ${esc(it.q)}</div>
        ${isFig ? `<div class="dt-seq">${it.figs.seq.join('')}<span class="dt-qm">?</span></div>` : ''}
        <div class="dt-opts${isFig ? ' dt-figs' : ''}">${opts}</div>
        <div class="dt-exp"><b>正确答案 ${esc(it.answer)}</b>${r.your ? ` · 你选了 ${esc(r.your)}` : ' · 没作答'}
          ${it.explain ? ' · ' + esc(it.explain) : ''}</div>
      </div>`;
    }).join('');
  } catch (e) { $('#drd-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
