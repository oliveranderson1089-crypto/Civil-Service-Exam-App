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
/* global $, api, esc, push, toast */

let rqOv = null, rqItems = [], rqIdx = 0, rqAns = {}, rqSec = {}, rqT0 = 0;
let rqExam = false, rqDone = false;   // rqExam=模考模式（做完才判）；rqDone=已交卷，防重复提交
const rqN = 10;

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

    <div class="rq-go">
      <button class="rq-big" data-rqgo="smart">
        <b>智能刷</b><span>${d.due ? `${d.due} 道该重刷 · 排在最前` : '没做过的优先'}</span></button>
      <button class="rq-big alt" data-rqgo="papers"><b>整卷模考</b><span>按年份/卷种，卷面原序</span></button>
    </div>

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
    box.innerHTML = `<div class="rq-sec">整卷模考 · ${d.items.length} 份卷子</div>
      <p class="rq-hint">按卷面原序出题，做完一次性判分。中途可以退出，做过的题会记进进度。</p>
      ${d.items.map(p => `
        <button class="rq-paper" data-pkey="${esc(p.pkey)}"
                data-pnm="${esc(`${p.year} ${p.exam}${p.paper ? ' · ' + p.paper : ''}`)}">
          <b>${p.year} ${esc(p.exam)}${p.paper ? ' · ' + esc(p.paper) : ''}${p.season ? ' · ' + esc(p.season) : ''}</b>
          <span>${p.c} 道可做${p.done ? ` · 已做 ${p.done}` : ''}</span>
          <i style="width:${Math.round(100 * p.done / p.c)}%"></i>
        </button>`).join('')}`;
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

$('#rq-body').addEventListener('click', e => {
  const p = e.target.closest('[data-pkey]');
  if (!p) return;
  // 整卷=**真模考**：exam:true 让服务端不下发答案，做完一次性判分（界面上就是这么承诺的）
  rqStart({ mode: 'paper', pkey: p.dataset.pkey, n: 140, exam: true }, p.dataset.pnm);
});

async function rqStart(body, title) {
  toast('取题中…');
  try {
    const d = await api('/api/real/quiz', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, timeoutMs: 20000,
      body: JSON.stringify(body),
    });
    rqItems = d.items; rqIdx = 0; rqAns = {}; rqSec = {};
    rqExam = !!d.exam; rqDone = false;
    push({ view: 'realrun', title: title + ' · 真题' });
    rqRender();
  } catch (e) { toast(e.message, true); }
}

function rqRender() {
  if (rqIdx >= rqItems.length) return rqFinish();
  const it = rqItems[rqIdx];
  rqT0 = Date.now();
  const src = (it.sources || [])[0] || {};
  const chosen = rqAns[it.id];
  const reveal = chosen && !rqExam;      // 模考模式做完才判，边做边揭就不是模考了
  $('#rq-head').innerHTML = `
    <div class="rq-prog">第 <b>${rqIdx + 1}</b> / ${rqItems.length} 题
      ${it.qtype ? `<span class="rq-tag">${esc(it.qtype)}</span>` : ''}
      <span class="rq-tag src">${src.year || ''} ${esc(src.exam || '')}${src.paper ? '·' + esc(src.paper) : ''}</span>
    </div>`;
  // 资料分析：材料排在题干**上面**（考场上也是先给材料再问）
  $('#rq-mat').innerHTML = it.material
    ? `<div class="rq-mat-t">给定资料</div><div class="rq-mat-b">${esc(it.material)}</div>` : '';
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
  $('#rq-exp').innerHTML = reveal ? explainHtml(it) : '';
  $('#rq-next').classList.toggle('hidden', !chosen);
  $('#rq-next').textContent = rqIdx + 1 >= rqItems.length ? '交卷看结果' : '下一题 →';
  $('#rq-quit').textContent = rqExam ? `交卷（已答 ${Object.keys(rqAns).length}/${rqItems.length}）` : '交卷';
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
  rqSec[it.id] = Math.round((Date.now() - rqT0) / 1000);
  rqRender();
});
$('#rq-next').onclick = () => { rqIdx++; rqRender(); };
$('#rq-quit').onclick = () => rqFinish();

async function rqFinish() {
  // 交卷按钮做完之后还在，不上锁的话再点一次就把同一批答案重复提交：
  // real_attempts 多插一批（做题数/正确率翻倍），review_state 又被推一档。
  if (rqDone) return;
  if (!Object.keys(rqAns).length) { toast('一道都没做'); return; }
  rqDone = true;
  try {
    const d = await api('/api/real/done', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers: rqAns, seconds: rqSec }),
    });
    $('#rq-head').innerHTML = '';
    $('#rq-stem').textContent = '';
    $('#rq-opts').innerHTML = '';
    $('#rq-figs').innerHTML = '';
    $('#rq-mat').innerHTML = '';   // 新增容器别漏了清理，否则上一题的图会挂在成绩上方
    $('#rq-next').classList.add('hidden');
    $('#rq-quit').classList.add('hidden');
    $('#rq-exp').innerHTML = `<div class="rq-done">
      <div class="rq-score"><b>${d.ok}</b> / ${d.total}<span>正确率 ${Math.round(d.acc * 100)}%</span></div>
      ${d.wrong_added ? `<p class="rq-hint">${d.wrong_added} 道错题已进错题本，明天会在「今日复习」里再见到。</p>`
    : '<p class="rq-hint">全对，这批题会按遗忘曲线往后排。</p>'}
      <button class="btn" id="rq-again">再来一组</button></div>
      ${rqExam ? rqReviewHtml(d.results) : ''}`;
    $('#rq-again').onclick = () => rqStart({ mode: 'smart', n: rqN }, '智能刷');
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
      return `<div class="rq-rv${r.correct ? '' : ' bad'}">
        <div class="rq-rv-h"><b>第 ${noById[r.id] || '?'} 题</b>
          <span>${r.correct ? '✓ 对' : `✗ 你选 ${esc(r.your || '未答')}，正确 ${esc(r.answer)}`}</span></div>
        ${r.material ? `<div class="rq-mat"><div class="rq-mat-t">给定资料</div><div class="rq-mat-b">${esc(r.material)}</div></div>` : ''}
        <div class="rq-rv-q">${esc((it.stem || '').slice(0, 120))}</div>
        ${(r.figs || []).map(f =>
    `<img class="rq-rv-fig" src="/api/real/fig/${encodeURIComponent(f)}" alt="题目图" loading="lazy">`).join('')}
        ${r.correct ? '' : explainHtml({ explain: r.explain })}
      </div>`;
    }).join('')}</div>`;
}

window.openRealq = openRealq;

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
