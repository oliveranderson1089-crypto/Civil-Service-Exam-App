/* 题库（四川省考卷面 · 练习模式）
 *
 * 由 app.js 按它自己的区段边界切出（原 L6896-7009）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, DT_L, api, c, dtMaterial,
   emKey, esc, push, toast */

/* ============= 题库（四川省考卷面 · 练习模式） ============= */
let qz = { set: null, qs: [], idx: 0 };
$('#qz-list').addEventListener('click', async e => {
  const c = e.target.closest('[data-qset]'); if (!c) return;
  try {
    const d = await api('/api/quiz/sets/' + c.dataset.qset);
    qz = { set: d, qs: d.questions, idx: 0 };
    // 跳到第一道未作答的题
    const firstUndone = d.questions.findIndex(q => !q.my_choice);
    if (firstUndone > 0) qz.idx = firstUndone;
    push({ view: 'quizrun', title: d.name });
    renderQuiz();
  } catch (err) { toast(err.message, true); }
});
function renderQuiz() {
  const q = qz.qs[qz.idx];
  if (!q) { $('#qzr-wrap').innerHTML = '<p class="empty">没有题目</p>'; return; }
  const total = qz.qs.length;
  const doneN = qz.qs.filter(x => x.my_choice).length;
  const isSL = qz.set.kind === '申论';
  const answered = !!q.my_choice;
  // 材料可能是三种：图形推理的图（JSON figs）/ 资料分析的表格·图表（JSON）/ 老的纯文字材料
  let mat = null;
  try { mat = q.material && q.material.trim().startsWith('{') ? JSON.parse(q.material) : null; } catch (_) { mat = null; }
  const isFig = !!(mat && mat.type === 'figs');
  let optHtml = '';
  if (isFig) {
    optHtml = '<div class="qz-opts qz-figs">' + (mat.opts || []).map((svg, j) => {
      const letter = DT_L[j];
      let cls = '';
      if (answered) {
        if (letter === q.answer) cls = ' right';
        else if (letter === q.my_choice) cls = ' wrong';
        else cls = ' dim';
      }
      return `<button class="qz-opt qz-figopt${cls}" data-opt="${letter}" ${answered ? 'disabled' : ''}>
        <span class="dt-figl">${letter}</span>${svg}</button>`;
    }).join('') + '</div>';
  } else if (!isSL) {
    optHtml = '<div class="qz-opts">' + q.options.map(o => {
      const letter = (o || '').trim().slice(0, 1).toUpperCase();
      let cls = '';
      if (answered) {
        if (letter === q.answer) cls = ' right';
        else if (letter === q.my_choice) cls = ' wrong';
        else cls = ' dim';
      }
      return `<button class="qz-opt${cls}" data-opt="${letter}" ${answered ? 'disabled' : ''}>${esc(o)}</button>`;
    }).join('') + '</div>';
  }
  const expl = (answered && !isSL)
    ? `<div class="cd-sec qz-expl"><div class="cd-sec-t">${q.my_choice === q.answer ? '✅ 回答正确' : '❌ 回答错误 · 正确答案 ' + esc(q.answer)}</div>
        <div class="cd-sec-b">${emKey(q.explanation || '')}</div></div>` : '';
  const slAns = isSL ? `
    <button class="btn primary" id="qz-showans" style="width:100%;padding:12px;margin-top:12px;">查看参考答案</button>
    <div class="cd-sec qz-expl hidden" id="qz-ansbox"><div class="cd-sec-t">📄 参考答案</div>
      <div class="cd-sec-b">${emKey(q.explanation || '')}</div></div>` : '';
  $('#qzr-wrap').innerHTML = `
    <div class="rv-progress"><div class="rv-bar" style="width:${doneN / total * 100}%"></div></div>
    <div class="rv-meta-row"><span>第 ${qz.idx + 1} / ${total} 题 · ${esc(q.module)}${q.qtype && q.qtype !== q.module ? '·' + esc(q.qtype) : ''}</span>
      <span>已做 ${doneN} · 对 ${qz.qs.filter(x => x.my_choice && x.my_choice === x.answer).length}</span></div>
    ${(mat && !isFig) ? dtMaterial(mat, 'qz' + qz.idx)          /* 资料分析：真表格 / 图表 */
      : (q.material && !mat) ? `<div class="qz-mat"><div class="qz-mat-t">📋 ${isSL ? '给定资料' : '材料'}（上下滚动）</div><div class="qz-mat-b">${emKey(q.material)}</div></div>`
        : ''}
    <div class="gk-card"><div class="qz-q">${qz.idx + 1}. ${emKey(q.question)}</div>
      ${isFig ? `<div class="dt-seq">${(mat.seq || []).join('')}<span class="dt-qm">?</span></div>` : ''}
      ${optHtml}${slAns}</div>
    ${expl}
    <div class="qz-nav">
      <button class="btn" id="qz-prev" ${qz.idx === 0 ? 'disabled' : ''}>‹ 上一题</button>
      <button class="btn primary" id="qz-next" ${qz.idx >= total - 1 ? 'disabled' : ''}>下一题 ›</button>
    </div>`;
  window.scrollTo(0, 0);
}
$('#qzr-wrap').addEventListener('click', async e => {
  const chtb = e.target.closest('[data-chtb]');        // 资料分析图表下的「看数据表」
  if (chtb) {
    const box = $('#chtb-' + chtb.dataset.chtb);
    const hidden = box.classList.toggle('hidden');
    chtb.textContent = hidden ? '📋 看数据表' : '📊 收起数据表';
    return;
  }
  if (e.target.closest('#qz-prev')) { if (qz.idx > 0) { qz.idx--; renderQuiz(); } return; }
  if (e.target.closest('#qz-next')) { if (qz.idx < qz.qs.length - 1) { qz.idx++; renderQuiz(); } return; }
  if (e.target.closest('#qz-showans')) {
    $('#qz-ansbox').classList.remove('hidden');
    e.target.closest('#qz-showans').classList.add('hidden');
    return;
  }
  const opt = e.target.closest('.qz-opt');
  if (opt && !opt.disabled) {
    const q = qz.qs[qz.idx];
    try {
      const d = await api('/api/quiz/answer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ qid: q.id, choice: opt.dataset.opt }) });
      q.my_choice = opt.dataset.opt; q.answer = d.answer; q.explanation = d.explanation;
      renderQuiz();
      // 答错自动收进错题本。走 /api/wrongq/sync（不是人工录入那个口子）：
      // 带上来源身份 quiz/题目 id，同一道题重复做错只留一条，错题本那边改了、
      // 删了，回到这儿看到的也是改后的状态。
      if (!d.correct) {
        try {
          await api('/api/wrongq/sync', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              kind: 'quiz', key: String(q.id),
              board: q.module === '申论' ? '申论' : q.module,
              question: q.question + '\n' + (q.options || []).join('\n'),
              answer: d.answer, qtype: q.qtype || q.module,
              note: '来自题库：' + qz.set.name,
            }),
          });
          toast('已答错，这题自动收进错题本');
        } catch (e) {
          // 这是「自动」收错题：成功时会 toast，失败却一声不响的话，用户会以为收进去了
          // —— 等到复习错题本时才发现这题根本不在里面。
          console.warn('[题库] 自动收错题失败：%s', (e && e.message) || e);
          toast('这题没能自动收进错题本，可到错题本手动加', true);
        }
      }
    } catch (err) { toast(err.message, true); }
  }
});
