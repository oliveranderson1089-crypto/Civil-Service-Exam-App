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
   dtMaterial, esc, push, toast */

/* ============= 专项练（行测六大板块）=============
   资料分析 / 判断推理 / 数量关系 —— 题型固定、有套路、拼速度，**题由程序生成**，答案由构造保证。
   常识判断 / 政治理论 / 言语理解 —— 考的是知识，构造不出来，**由 AI 按考试标准出题**；
     出好的题攒进题库（drill_bank），下次直接取，不用每次等十几秒。
   三档难度**真正改变题目**（不是贴个标签）；难度系数 = 预期得分率，做完告诉你比预期高还是低。
   两种模式：背题（选完即判 + 解析）/ 测试（做完交卷、服务端判分）。题量 5/10/15/20。
   每次做完**留一条完整记录**，可以回看每一题 —— 不是做完就丢。 */
let drBoard = '', drType = '', drItems = [], drIdx = 0, drAns = [], drSec = [], drT0 = 0, drTimer = 0;
let drLimit = 60, drLevel = 'mid', drN = 10, drMode = 'study', drToken = '', drCoef = 0.6, drLevels = [];

function openDrill(board) {
  drBoard = board;
  push({ view: 'drill', title: board + ' · 专项练' });
  loadDrillTypes();
}
async function loadDrillTypes() {
  const box = $('#dr-types');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api(`/api/drill/types?board=${encodeURIComponent(drBoard)}&level=${drLevel}`);
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
      return `<div class="dr-card${weak ? ' weak' : ''}" data-drt="${esc(t.type)}">
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
          ${done ? `做过 ${t.n} 题 · 平均 ${t.sec} 秒${t.sec > drLimit ? '（超时）' : ''}` : `限时 ${drLimit} 秒/题`}</div>
      </div>`;
    }).join('') + `<div class="dr-card dr-all" data-drt=""><div class="dr-card-h"><b>🎲 混合练</b></div>
      <p class="dr-desc">所有题型随机出，模拟真实考场</p><div class="dr-meta">限时 ${drLimit} 秒/题</div></div>`;
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
function drCoefTip() {
  const l = drLevels.find(x => x.k === drLevel) || {};
  // 「难度系数」在公考里就是**得分率**。必须说清它是什么，不然「0.40」看着像分数
  $('#dr-coef').innerHTML = `<b>难度系数 ${(l.coef || 0).toFixed(2)}</b>
    <span>= 这个难度下<b>预期能做对 ${Math.round((l.coef || 0) * 100)}%</b>。${esc(l.desc || '')}。
    做完会告诉你<b>比预期高还是低</b>，心里有数。</span>`;
}
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
  drStart(c.dataset.drt);
});
$('#dr-recs').onclick = () => openDrillRecs();

async function drStart(type) {
  drType = type;
  toast('出题中…');
  try {
    const d = await api('/api/drill/quiz', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ board: drBoard, type, n: drN, level: drLevel, exam: drMode === 'exam' }),
    });
    drItems = d.items; drLimit = d.limit; drCoef = d.coef; drToken = d.token || '';
    drIdx = 0; drAns = []; drSec = [];
    push({ view: 'drillrun', title: (type || '混合') + ' · 专项练' });
    drRender();
  } catch (e) { toast(e.message, true); }
}

function drRender() {
  clearInterval(drTimer);
  if (drIdx >= drItems.length) { drResult(); return; }
  const it = drItems[drIdx];
  const isFig = !!(it.figs && it.figs.seq);
  const lvName = (drLevels.find(x => x.k === drLevel) || {}).name || '';
  $('#dr-head').innerHTML = `
    <div class="dr-prog">第 <b>${drIdx + 1}</b> / ${drItems.length} 题
      <span class="dr-tag">${esc(it.qtype || '')}</span>
      <span class="dr-tag lv">${esc(lvName)}</span></div>
    <div class="dr-clock" id="dr-clock">0 秒</div>`;
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
    <div class="dt-qt">${esc(it.q)}</div>${seq}
    <div class="dt-opts${isFig ? ' dt-figs' : ''}">${opts}</div>
    <div id="dr-exp"></div>${nav}</div>`;
  if (drMode === 'exam') {
    $('#dr-prev').onclick = () => { drStopTimer(); drIdx--; drRender(); };
    $('#dr-nextq').onclick = () => { drStopTimer(); drIdx++; drRender(); };
  }
  drT0 = Date.now();
  drTimer = setInterval(() => {
    const s = Math.round((Date.now() - drT0) / 1000 + (drSec[drIdx] || 0));
    const el = $('#dr-clock'); if (!el) { clearInterval(drTimer); return; }
    el.textContent = s + ' 秒';
    el.classList.toggle('over', s > drLimit);        // 超时只是提醒，不打断（考场上超时也得做完）
  }, 500);
}
function drStopTimer() {
  clearInterval(drTimer);
  drSec[drIdx] = (drSec[drIdx] || 0) + (Date.now() - drT0) / 1000;
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
  const over = sec > drLimit;
  const bold = (t) => esc(t || '').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  $('#dr-exp').innerHTML = `
    <div class="dr-verdict ${ok ? 'ok' : 'no'}">${ok ? '✅ 对了' : '❌ 错了'}
      · 用时 <b class="${over ? 'over' : ''}">${sec.toFixed(0)} 秒</b>${over ? `（限时 ${drLimit} 秒，慢了）` : ''}
      · 正确答案 <b>${esc(it.answer)}</b></div>
    <div class="dt-exp">${bold(it.explain)}</div>
    ${it.tip ? `<div class="dr-tip">⚡ <b>秒杀技巧</b>：${bold(it.tip)}</div>` : ''}
    <button class="btn primary" id="dr-next">${drIdx + 1 >= drItems.length ? '看结果' : '下一题 →'}</button>`;
}

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
    const slow = drSec.filter(s => s > drLimit).length;
    const pct = Math.round(r.acc * 100), exp = Math.round(r.coef * 100);
    const good = r.vs >= 0;
    $('#dr-body').innerHTML = `
      <div class="dr-done">
        <div class="dr-score">${r.ok} / ${r.total}</div>
        <div class="dr-vs ${good ? 'good' : 'bad'}">
          正确率 <b>${pct}%</b> · 这个难度预期 ${exp}%
          → <b>${good ? '高出' : '低了'} ${Math.abs(Math.round(r.vs * 100))} 个点</b>
        </div>
        <div class="dr-sub">平均用时 <b class="${avg > drLimit ? 'over' : ''}">${avg.toFixed(0)} 秒</b>
          ${slow ? `· 有 ${slow} 题超时（限时 ${drLimit} 秒）` : `· 都在 ${drLimit} 秒内 👍`}</div>
        ${r.wrong_added ? `<p class="dr-wq">错的 ${r.wrong_added} 题已自动进错题本</p>` : ''}
        <div class="dr-acts">
          <button class="btn primary" id="dr-again">🔄 再来 ${drN} 题</button>
          <button class="btn" id="dr-see">📋 看每题详情</button>
          <button class="btn" id="dr-back">换个题型</button>
        </div>
      </div>`;
    $('#dr-again').onclick = () => drStart(drType);
    $('#dr-see').onclick = () => openDrillRec(r.rid);
    $('#dr-back').onclick = () => { back(); loadDrillTypes(); };
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
      const cls = (L) => (L === it.answer ? ' correct' : (L === r.your ? ' wrong' : ''));
      const opts = isFig
        ? it.figs.opts.map((svg, j) => `<button class="dt-opt dt-figo${cls(DT_L[j])}" disabled>
            <span class="dt-figl">${DT_L[j]}</span>${svg}</button>`).join('')
        : (it.options || []).map((o, j) => `<button class="dt-opt${cls(DT_L[j])}" disabled>${esc(o)}</button>`).join('');
      return `<div class="dt-q">${dtMaterial(it.material, i, i ? d.items[i - 1].material : null)}
        <div class="dt-qt">${r.correct ? '✅' : '❌'} ${i + 1}. ${esc(it.q)}</div>
        ${isFig ? `<div class="dt-seq">${it.figs.seq.join('')}<span class="dt-qm">?</span></div>` : ''}
        <div class="dt-opts${isFig ? ' dt-figs' : ''}">${opts}</div>
        <div class="dt-exp"><b>正确答案 ${esc(it.answer)}</b>${r.your ? ` · 你选了 ${esc(r.your)}` : ' · 没作答'}
          ${it.explain ? ' · ' + esc(it.explain) : ''}</div>
      </div>`;
    }).join('');
  } catch (e) { $('#drd-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
