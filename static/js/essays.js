/* 范文推荐（仿真卷 + 全套参考答案）
 *
 * 由 app.js 按它自己的区段边界切出（原 L8643-8726）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, c, esc, openSlPaper, push,
   toast */

/* ================= 范文推荐（仿真卷 + 全套参考答案） ================= */
let esKind = 'zuowen', esTopic = '', esPapers = [], esCur = null;

async function openEssays() {
  push({ view: 'essays', title: '范文推荐' });
  try {
    const d = await api('/api/essays/topics');
    esPapers = d.papers;
    renderEsTopics();
    loadEssays();
  } catch (e) { $('#es-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderEsTopics() {
  $('#es-topics').innerHTML = `<button class="chip ${esTopic ? '' : 'active'}" data-est="">全部</button>`
    + esPapers.map(p => `<button class="chip ${esTopic === p.topic ? 'active' : ''}" data-est="${esc(p.topic)}">${esc(p.topic)}</button>`).join('');
}
$('#es-topics').addEventListener('click', e => {
  const b = e.target.closest('[data-est]'); if (!b) return;
  esTopic = b.dataset.est; renderEsTopics(); loadEssays();
});
$('#es-tabs').addEventListener('click', e => {
  const b = e.target.closest('[data-esk]'); if (!b) return;
  esKind = b.dataset.esk;
  document.querySelectorAll('#es-tabs .tk-tab').forEach(x => x.classList.toggle('active', x.dataset.esk === esKind));
  loadEssays();
});
async function loadEssays() {
  $('#es-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/essays?kind=' + esKind + (esTopic ? '&topic=' + encodeURIComponent(esTopic) : ''));
    if (!d.items.length) {
      $('#es-list').innerHTML = '<p class="empty">这个分类下还没有范文。服务器上跑 <code>gen_essays.py</code> 可以按话题继续生成。</p>';
      return;
    }
    $('#es-list').innerHTML = d.items.map(it => `
      <div class="sl-hi" data-esid="${it.id}">
        <div class="sl-hi-main">
          <div class="sl-hi-t">${esc(it.topic)} · ${esc(it.type_name)}</div>
          <div class="sl-hi-m">${esc(it.stem.slice(0, 42))}…</div>
          <div class="sl-hi-m">${it.full} 分 · 要求 ${it.word_min}-${it.word_max} 字 · 范文 ${it.answer_words} 字</div>
        </div>
        <span class="bc-arrow">›</span>
      </div>`).join('');
  } catch (e) { $('#es-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#es-list').addEventListener('click', e => {
  const c = e.target.closest('[data-esid]'); if (c) openEssay(+c.dataset.esid);
});

async function openEssay(eid) {
  try {
    const d = await api('/api/essays/' + eid);
    esCur = d;
    push({ view: 'essayd', title: d.topic + ' · ' + d.type_name });
    $('#esd-head').innerHTML = `<div class="slt-title">${esc(d.topic)} · ${esc(d.type_name)}</div>
      <div class="slt-desc">${esc(d.spec_name)} · 本题 ${d.full} 分 · 要求 ${d.word_min}-${d.word_max} 字
      · 给定资料 ${d.material_words} 字</div>`;
    $('#esd-q').innerHTML = `<div class="slt-sec">题目</div>
      <div class="slr-reftext">${esc(d.stem).replace(/\n/g, '<br>')}</div>`
      + (d.outline ? `<div class="slt-sec">写作思路</div><div class="slr-reftext">${esc(d.outline).replace(/\n/g, '<br>')}</div>` : '');
    $('#esd-m').innerHTML = `<div class="slt-sec">给定资料（${d.material_words} 字）</div>
      <div class="slr-reftext slr-mat">${esc(d.material).replace(/\n/g, '<br>')}</div>`;
    $('#esd-a').innerHTML = `<div class="slt-sec">${d.qtype === 'zuowen' ? '参考范文' : '参考答案'}</div>
      <div class="slr-wtag">${d.answer_words} 字 · 题目要求 ${d.word_min}-${d.word_max} 字</div>
      <div class="slr-reftext">${esc(d.answer).replace(/\n/g, '<br>')}</div>`;
    esdTab('q');
  } catch (e) { toast(e.message, true); }
}
function esdTab(t) {
  document.querySelectorAll('#esd-tabs .tk-tab').forEach(x => x.classList.toggle('active', x.dataset.esd === t));
  ['q', 'm', 'a'].forEach(k => $('#esd-' + k).classList.toggle('hidden', k !== t));
}
$('#esd-tabs').addEventListener('click', e => {
  const b = e.target.closest('[data-esd]'); if (b) esdTab(b.dataset.esd);
});
$('#esd-practice').onclick = async () => {
  if (!esCur) return;
  try {
    const d = await api('/api/essays/paper/' + esCur.paper_id + '/practice', { method: 'POST' });
    toast(d.existed ? '这套卷已经在你的真题卷里' : '已加入我的真题卷');
    openSlPaper(d.id);
  } catch (e) { toast(e.message, true); }
};
