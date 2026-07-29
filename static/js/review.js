/* 今日复习（艾宾浩斯遗忘曲线）
 *
 * 由 app.js 按它自己的区段边界切出（原 L6721-6895）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, back, emKey, esc, push,
   refreshReviewBadge, toast */

/* ============= 今日复习（艾宾浩斯遗忘曲线） ============= */
const RV_KIND = { entry: '成语词语', wrongq: '错题', classic: '古诗文', gushi: '古诗' };
const RV_COLOR = { entry: '#2b6fd6', wrongq: '#b23b2e', classic: '#0f766e', gushi: '#8a5a2b' };
// 跟 mods/review.py 的 REVIEW_INTERVALS 是同一张表。这儿必须留一份副本：
// 「认识 → N 天后」是点之前就要显示的预告，那时还没调接口、拿不到后端算的 interval。
// 两份手抄迟早走散（后端注释里记着同样的教训：白名单抄了第二份，结果加新来源时漏改一处），
// 所以 tests/frontend/review.test.js 有一条专门盯着它俩一致。
const RV_INTERVALS = [1, 2, 4, 7, 15, 30, 60];
let rvQueue = [], rvTotal = 0, rvDoneN = 0;
/* 词语句子 / 每日积累 / 批注 / 错题 各背各的，不混成一副牌 */
let rvAll = [], rvGroup = 'word', rvDoneToday = {};
/* 每日复习量：一天能背多少因人而异。堆太多就不想背了 —— 超出上限的**不会丢**，
   只是今天不出现（到期时间不变，明天照样在）。0 = 不限。 */
const RV_LNAME = { word: '词语句子', daily: '每日积累', gushi: '古诗', annot: '批注', wrongq: '错题' };
let rvLim = null, rvPool = null;
function rvLimRender() {
  if (!rvLim) return;
  $('#rv-lim-rows').innerHTML = Object.keys(RV_LNAME).map(k => `
    <div class="rv-lim-row">
      <label>${RV_LNAME[k]}</label>
      <input type="number" min="0" max="500" data-rvl="${k}" value="${rvLim[k]}">
      <span class="rv-lim-pool">到期 ${(rvPool || {})[k] || 0} 条${rvLim[k] ? '' : ' · 不限'}</span>
    </div>`).join('');
  $('#rv-limsum').textContent = Object.keys(RV_LNAME)
    .map(k => `${RV_LNAME[k]} ${rvLim[k] || '不限'}`).join(' · ');
}
$('#rv-limtog').onclick = async () => {
  const box = $('#rv-lim');
  const show = box.classList.contains('hidden');
  box.classList.toggle('hidden', !show);
  if (show && !rvLim) {
    try {
      const d = await api('/api/review/limits');
      rvLim = d.limits; rvPool = d.due; rvLimRender();
    } catch (e) { toast(e.message, true); }
  }
};
$('#rv-limsave').onclick = async () => {
  const body = {};
  document.querySelectorAll('[data-rvl]').forEach(i => { body[i.dataset.rvl] = Math.max(0, +i.value || 0); });
  const b = $('#rv-limsave'); b.disabled = true;
  try {
    const d = await api('/api/review/limits', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    rvLim = d.limits; rvLimRender();
    $('#rv-lim').classList.add('hidden');
    toast('已保存，今天按新的量出');
    loadReview();
  } catch (e) { toast(e.message, true); }
  b.disabled = false;
};

async function loadReview() {
  ['rv-empty', 'rv-card-wrap', 'rv-done'].forEach(id => $('#' + id).classList.add('hidden'));
  try {
    const d = await api('/api/review/today');
    rvAll = d.items || [];
    rvLim = d.limits || rvLim; rvPool = d.pool || rvPool;
    rvDoneToday = d.done_today || {};
    if (rvLim) rvLimRender();
    const g = d.groups || {};
    document.querySelectorAll('[data-rvg]').forEach(b => {
      const n = g[b.dataset.rvg] || 0;
      b.querySelector('.rv-n').textContent = n ? ' ' + n : '';
      b.classList.toggle('rv-empty-tab', !n);
    });
    if (!rvAll.length) { $('#rv-empty').classList.remove('hidden'); refreshReviewBadge(); return; }
    // 默认停在第一个有内容的板块
    if (!(g[rvGroup] > 0)) rvGroup = ['word', 'daily', 'gushi', 'wrongq'].find(k => g[k] > 0) || 'word';
    rvSelect(rvGroup);
  } catch (e) { toast(e.message, true); }
}
function rvSelect(group) {
  rvGroup = group;
  document.querySelectorAll('[data-rvg]').forEach(b => b.classList.toggle('active', b.dataset.rvg === group));
  rvQueue = rvAll.filter(it => it.group === group);
  rvTotal = rvQueue.length; rvDoneN = 0;
  $('#rv-done').classList.add('hidden');
  if (!rvTotal) {
    $('#rv-card-wrap').classList.add('hidden');
    // 这个板块今天做过（额度用满）→ 明说「已完成 N 条」，别让人以为是空的/出错
    const done = rvDoneToday[group] || 0;
    const lim = (rvLim || {})[group] || 0;
    $('#rv-empty').innerHTML = done > 0
      ? `<p class="empty">✅ 「${RV_LNAME[group] || ''}」今日已完成 <b>${done}</b> 条${lim ? '（每日量 ' + lim + '）' : ''}，明天见～<br><span style="font-size:13px;color:var(--muted)">想多背可到「每日复习量」调高上限。</span></p>`
      : '<p class="empty">🎉 这个板块今天没有要复习的内容。收录的成语/古诗文、每日素材、古诗、错题会按遗忘曲线（1/2/4/7/15/30/60 天）分别出现。</p>';
    $('#rv-empty').classList.remove('hidden');
    return;
  }
  $('#rv-empty').classList.add('hidden');
  $('#rv-card-wrap').classList.remove('hidden');
  rvShow();
}
$('#rv-tabs').addEventListener('click', e => {
  const b = e.target.closest('[data-rvg]'); if (b) rvSelect(b.dataset.rvg);
});
function openReview() { push({ view: 'review', title: '今日复习' }); loadReview(); }
function rvShow() {
  if (!rvQueue.length) {
    $('#rv-card-wrap').classList.add('hidden');
    $('#rv-done').classList.remove('hidden');
    refreshReviewBadge();
    return;
  }
  const it = rvQueue[0];
  $('#rv-bar').style.width = (rvTotal ? (rvDoneN / rvTotal * 100) : 0) + '%';
  $('#rv-pos').textContent = `已复习 ${rvDoneN} / ${rvTotal}`;
  $('#rv-round').textContent = `第 ${it.stage + 1} 轮`;
  $('#rvf-kind').textContent = RV_KIND[it.kind] || it.kind;
  $('#rvf-kind').style.background = RV_COLOR[it.kind] || '#666';
  $('#rvf-title').textContent = it.front || it.title;
  $('#rvf-sub').textContent = it.front_sub || '';
  $('#rvb-body').innerHTML = emKey(it.back || '');
  $('#rv-back').classList.add('hidden');
  // 古诗要回忆的是「名句 + 考点」，不是「内容要点」——提示语说清楚该想什么
  $('#rvf-hint').textContent = it.kind === 'gushi'
    ? '先默出名句，再想常识考点和申论用法 · 点击卡片对答案'
    : '请回忆内容要点 · 点击卡片显示答案';
  $('#rvf-hint').classList.remove('hidden');
  $('#rv-btns').classList.add('hidden');
  const nd = RV_INTERVALS[Math.min(it.stage + 1, RV_INTERVALS.length - 1)];
  $('#rv-know-d').textContent = nd + ' 天后';
}
$('#rv-flash').addEventListener('click', e => {
  if (e.target.closest('.read-item-btn')) return;   // 朗读按钮不翻卡
  const back = $('#rv-back');
  const opening = back.classList.contains('hidden');
  back.classList.toggle('hidden', !opening);
  $('#rvf-hint').classList.toggle('hidden', opening);
  $('#rv-btns').classList.toggle('hidden', !opening);
  if (opening) rvEnsureExample();                   // 翻到背面：没例句就现去要一个
});

/* 例句懒加载：194 个词在真语料里找到了真句子（人民日报等），剩下的翻到时才让 AI 仿写 ——
   一次性给 990 个词都生成太浪费，你真背到哪个才给哪个。 */
async function rvEnsureExample() {
  const it = rvQueue[0];
  if (!it || it.kind !== 'changkao') return;                 // 只有常考的成语/实词有例句
  if ((it.back || '').includes('✍️ 例句')) return;           // 已经有了
  if (it._exLoading) return;
  it._exLoading = true;
  const box = $('#rvb-body');
  const tip = document.createElement('div');
  tip.className = 'rv-ex-load';
  tip.textContent = '正在找例句…';
  box.appendChild(tip);
  try {
    const d = await api('/api/changkao/' + it.id + '/example');
    const ai = (d.src || '').startsWith('AI');
    it.back = (it.back || '') + '\n\n✍️ 例句：' + d.example + (d.src ? '\n　　—— ' + d.src : '');
    tip.className = 'rv-ex';
    tip.innerHTML = `<div class="rv-ex-t">✍️ ${esc(d.example)}</div>
      <div class="ck-ex-src ${ai ? 'ai' : 'real'}">${ai ? '✎' : '📰'} ${esc(d.src || '')}</div>`;
  } catch (_) { tip.remove(); }
  it._exLoading = false;
}
async function rvAnswer(result) {
  const it = rvQueue.shift(); if (!it) return;
  try {
    await api('/api/review/done', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: it.kind, id: it.id, result }) });
  } catch (e) { toast(e.message, true); rvQueue.unshift(it); return; }
  if (result === 'forget') { it.stage = 0; rvQueue.push(it); }   // 忘记：今日重现（排到队尾）
  else {
    rvDoneN++;
    const i = rvAll.indexOf(it);
    if (i >= 0) rvAll.splice(i, 1);            // 从总表里去掉，各板块的角标才会跟着减
    rvUpdateCounts();
  }
  rvShow();
}
function rvUpdateCounts() {
  document.querySelectorAll('[data-rvg]').forEach(b => {
    const n = rvAll.filter(x => x.group === b.dataset.rvg).length;
    b.querySelector('.rv-n').textContent = n ? ' ' + n : '';
    b.classList.toggle('rv-empty-tab', !n);
  });
}
$('#rv-know').onclick = () => rvAnswer('know');
$('#rv-fuzzy').onclick = () => rvAnswer('fuzzy');
$('#rv-forget').onclick = () => rvAnswer('forget');
