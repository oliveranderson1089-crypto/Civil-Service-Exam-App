/* 申论 / 常考 / 理论基础 / 今日复习 / 题库 / 经典著作 / 常识 / 要文库 / 人民时评
 *
 * 由 app.js 按它原有的区段边界切出（原 L6040-7319）。顺序即原顺序 —— index.html 里
 * 按同样次序引入，执行序与拆分前逐字节一致。
 *
 * 下面 /* global *​/ 是这个模块的依赖清单：它用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，这就是现成的 import 表。
 */
/* global $, DT_L, IC, IS_MOBILE, _dtLastMat, api,
   appConfirm, appPrompt, back, c, dtMaterial, emKey,
   esc, fmtDay, injectReadBtns, isDocHeading, matOpen, mdToHtml,
   openClassicDetail, openEssays, push, refreshReviewBadge, stack, state,
   toast */

/* ================= 申论：真题卷 + 题型讲义 + AI 逐点批改 ================= */
let slType = null, slQuestion = null, slPaper = null;

async function openShenlun() {
  push({ view: 'shenlun', title: '真题批改' });
  $('#sl-types').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/shenlun/types');
    $('#sl-types').innerHTML = d.types.map(t => `
      <div class="home-card" data-slt="${esc(t.key)}">
        <div class="hc-logo" style="background:${t.color}">${IC[t.icon] || IC.edit}</div>
        <div class="hc-name">${esc(t.name)}</div>
        <div class="hc-desc">${t.full} 分 · ${t.word_min}-${t.word_max} 字</div>
      </div>`).join('');
    loadSlPapers();
    loadSlHistory();
  } catch (e) { $('#sl-types').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#sl-types').addEventListener('click', e => {
  const c = e.target.closest('[data-slt]'); if (c) openSlType(c.dataset.slt);
});

/* ---- 真题卷：上传 → 自动拆题 ---- */
$('#sl-essays').onclick = () => openEssays();
$('#sl-upload').onclick = () => $('#sl-file').click();
async function slUploadPaper(file) {
  if (!file) return;
  toast('正在识别题目…（扫描件需 OCR，可能要 1 分钟）');
  const fd = new FormData();
  fd.append('file', file);
  try {
    const d = await api('/api/shenlun/paper/upload', { method: 'POST', body: fd });
    toast('识别出 ' + d.questions.length + ' 道题');
    loadSlPapers();
    openSlPaper(d.id);
  } catch (err) { toast(err.message, true); }
}
$('#sl-file').addEventListener('change', e => {
  const f = e.target.files[0]; e.target.value = '';
  slUploadPaper(f);
});
/* 真题卷：整个页面都能拖进来（PDF / Word / 图片都行），不用非得点按钮 */
(function () {
  const v = $('#view-shenlun');
  if (!v) return;
  const on = (e) => { e.preventDefault(); v.classList.add('drag-on'); };
  const off = (e) => { if (e.target === v || !v.contains(e.relatedTarget)) v.classList.remove('drag-on'); };
  v.addEventListener('dragover', on);
  v.addEventListener('dragenter', on);
  v.addEventListener('dragleave', off);
  v.addEventListener('drop', e => {
    e.preventDefault(); v.classList.remove('drag-on');
    const f = [...(e.dataTransfer ? e.dataTransfer.files : [])][0];
    if (f) slUploadPaper(f);
    else if (!window.__desktop) toast('没拿到文件，换「📄 上传真题」按钮试试', true);
  });
})();

async function loadSlPapers() {
  try {
    const d = await api('/api/shenlun/papers');
    $('#sl-papers').innerHTML = d.items.length ? d.items.map(p => `
      <div class="sl-hi" data-slp="${p.id}">
        <div class="sl-hi-main">
          <div class="sl-hi-t">📄 ${esc(p.title)}</div>
          <div class="sl-hi-m">${p.total} 道题 · 已做 ${p.done} 道 · ${esc(p.created_at.slice(5, 16))}</div>
        </div>
        <div class="sl-hi-s ${p.done >= p.total ? 'good' : 'ok'}">${p.done}<span>/${p.total}</span></div>
        <button class="sl-hi-del" data-slpdel="${p.id}">🗑</button>
      </div>`).join('') : '<p class="empty">还没有真题卷。点右上角「上传真题」，PDF/Word/图片都行，会自动拆出各道题。</p>';
  } catch (_) {}
}
$('#sl-papers').addEventListener('click', async e => {
  const del = e.target.closest('[data-slpdel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('删除这份真题卷？批改记录会保留。'))) return;
    try { await api('/api/shenlun/paper/' + del.dataset.slpdel, { method: 'DELETE' }); loadSlPapers(); }
    catch (er) { toast(er.message, true); }
    return;
  }
  const p = e.target.closest('[data-slp]');
  if (p) openSlPaper(+p.dataset.slp);
});

async function openSlPaper(pid) {
  try {
    const p = await api('/api/shenlun/paper/' + pid);
    slPaper = p;
    push({ view: 'slpaper', title: p.title });
    const done = p.questions.filter(q => q.done).length;
    $('#slp-head').innerHTML = `<div class="slt-title">${esc(p.title)}</div>
      <div class="slt-desc">${p.questions.length} 道题 · 已做 ${done} 道</div>`;
    $('#slp-mat-text').textContent = p.material || '（未识别到给定资料）';
    $('#slp-qs').innerHTML = p.questions.map(q => {
      const d = q.done;
      const pct = d && q.full ? d.score / q.full : 0;
      return `<div class="slq" data-slq="${q.id}">
        <div class="slq-head">
          <span class="slq-no">${q.seq}</span>
          <span class="slq-type">${esc(q.type_name)}</span>
          <span class="slq-meta">${q.full} 分 · ${q.word_min}-${q.word_max} 字</span>
          ${d ? `<span class="slq-score ${pct >= 0.8 ? 'good' : pct >= 0.6 ? 'ok' : 'bad'}">${d.score}/${d.full}</span>`
          : '<span class="slq-todo">未作答</span>'}
        </div>
        <div class="slq-stem">${esc(q.stem)}</div>
        ${d ? `<button class="slq-view" data-slview="${d.grade_id}">看批改</button>` : ''}
      </div>`;
    }).join('');
  } catch (e) { toast(e.message, true); }
}
$('#slp-qs').addEventListener('click', e => {
  const v = e.target.closest('[data-slview]');
  if (v) { e.stopPropagation(); openSlRecord(+v.dataset.slview); return; }
  const q = e.target.closest('[data-slq]');
  if (!q) return;
  const item = slPaper.questions.find(x => x.id === +q.dataset.slq);
  if (item) openSlGradeQ(item);
});

/* ---- 批改记录 ---- */
async function loadSlHistory() {
  try {
    const d = await api('/api/shenlun/history');
    $('#sl-hist-n').textContent = d.items.length ? d.items.length + ' 次' : '';
    $('#sl-hist').innerHTML = d.items.length ? d.items.map(it => {
      const pct = it.full ? it.score / it.full : 0;
      const lv = pct >= 0.8 ? '优秀' : pct >= 0.6 ? '达标' : '待提升';
      const from = it.paper_title ? `${esc(it.paper_title)} 第${it.seq}题` : esc(it.type_name);
      const w = it.words ? ` · ${it.words} 字` : '';
      return `<div class="sl-hi" data-slr="${it.id}">
        <div class="sl-hi-main">
          <div class="sl-hi-t">${from} · ${esc(it.question)}</div>
          <div class="sl-hi-m">${esc(it.created_at.slice(5, 16))} · ${lv}${w}</div>
        </div>
        <div class="sl-hi-s ${pct >= 0.8 ? 'good' : pct >= 0.6 ? 'ok' : 'bad'}">${it.score}<span>/${it.full}</span></div>
        <button class="sl-hi-del" data-sldel="${it.id}">🗑</button>
      </div>`;
    }).join('') : '<p class="empty">还没有批改记录，挑一道题练一练吧～</p>';
  } catch (_) {}
}
$('#sl-hist').addEventListener('click', async e => {
  const del = e.target.closest('[data-sldel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('删除这条批改记录？'))) return;
    try { await api('/api/shenlun/record/' + del.dataset.sldel, { method: 'DELETE' }); loadSlHistory(); }
    catch (er) { toast(er.message, true); }
    return;
  }
  const it = e.target.closest('[data-slr]');
  if (it) openSlRecord(+it.dataset.slr);
});

/* ---- 题型讲义 ---- */
async function openSlType(key) {
  try {
    const t = await api('/api/shenlun/type/' + key);
    slType = t; slQuestion = null;
    push({ view: 'sltype', title: t.name });
    $('#slt-head').innerHTML = `<div class="slt-title" style="border-left-color:${t.color}">${esc(t.name)}</div>
      <div class="slt-desc">${esc(t.desc)} · 满分 ${t.full} 分 · 参考字数 ${t.word_min}-${t.word_max} 字</div>`;
    $('#slt-goals').innerHTML = `<div class="slt-sec">学习目标</div><ul>`
      + t.goals.map(g => `<li>${esc(g)}</li>`).join('') + `</ul>`;
    $('#slt-map').innerHTML = `<div class="slt-sec">本章知识导图</div>` + t.map.map(g => `
      <div class="slm-group">
        <div class="slm-gname" style="background:${t.color}">${esc(g.group)}</div>
        ${g.rows.map(r => `<div class="slm-row">
          <div class="slm-name">${esc(r.name)}</div>
          <div class="slm-cells">${Object.keys(r).filter(k => k !== 'name').map(k =>
            `<div class="slm-cell"><b>${esc(k)}</b>${esc(r[k])}</div>`).join('')}</div>
        </div>`).join('')}
      </div>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#slt-go').onclick = () => { if (slType) openSlGrade(slType); };

/* ---- 作答页：自由练 / 真题某一小题 ---- */
function slSetupAnswer(full, wmin, wmax) {
  $('#slg-full').value = full;
  $('#slg-a').dataset.wmin = wmin; $('#slg-a').dataset.wmax = wmax;
  $('#slg-req').textContent = `（要求 ${wmin}-${wmax} 字）`;
  $('#slg-a').value = '';
  slCountWords();
}
function slWords(t) { return (t || '').replace(/\s+/g, '').length; }
function slCountWords() {
  const a = $('#slg-a');
  const n = slWords(a.value);
  const lo = +a.dataset.wmin, hi = +a.dataset.wmax;
  const el = $('#slg-count');
  let state = 'ok', tip = '字数达标';
  if (!n) { state = 'idle'; tip = ''; }
  else if (n < lo) { state = 'low'; tip = `还差 ${lo - n} 字`; }
  else if (n > hi) { state = 'high'; tip = `超出 ${n - hi} 字`; }
  el.className = 'slg-count ' + state;
  el.textContent = n ? `${n} / ${lo}-${hi} 字　${tip}` : `要求 ${lo}-${hi} 字`;
}
$('#slg-a').addEventListener('input', slCountWords);

function openSlGrade(t) {          // 自由练：自己贴题干和材料
  $('#slg-mat').classList.add('hidden');
  slType = t; slQuestion = null;
  push({ view: 'slgrade', title: t.name + ' · 批改' });
  $('#slg-type').innerHTML = `<span class="slg-badge" style="background:${t.color}">${esc(t.name)}</span>`;
  $('#slg-manual').classList.remove('hidden');
  $('#slg-fixed').classList.add('hidden');
  $('#slg-fullwrap').classList.remove('hidden');
  $('#slg-q').value = ''; $('#slg-m').value = '';
  slSetupAnswer(t.full, t.word_min, t.word_max);
}
function openSlGradeQ(q) {         // 真题：题干/材料/满分/字数都锁定，只写答案
  slQuestion = q; slType = null;
  push({ view: 'slgrade', title: `第${q.seq}题 · ${q.type_name}` });
  $('#slg-type').innerHTML = `<span class="slg-badge" style="background:#2b6fd6">第 ${q.seq} 题 · ${esc(q.type_name)}</span>`;
  $('#slg-manual').classList.add('hidden');
  $('#slg-fullwrap').classList.add('hidden');
  $('#slg-fixed').classList.remove('hidden');
  $('#slg-fixed').innerHTML = `<div class="slf-stem">${esc(q.stem)}</div>
    <div class="slf-meta">${q.full} 分 · 要求 ${q.word_min}-${q.word_max} 字</div>`;
  slSetupAnswer(q.full, q.word_min, q.word_max);
  // 作答时要看得到给定资料（考场上就是拿笔在材料上划重点）
  const mat = (slPaper && slPaper.material) || '';
  $('#slg-mat').classList.toggle('hidden', !mat);
  $('#slg-mat').onclick = () => matOpen(mat, 'p' + (slPaper ? slPaper.id : 0));
  if (mat && !IS_MOBILE) matOpen(mat, 'p' + slPaper.id);      // 电脑端直接半屏摆出来
}
$('#slg-go').onclick = async () => {
  const answer = $('#slg-a').value.trim();
  if (answer.length < 10) return toast('请填写你的答案', true);
  const lo = +$('#slg-a').dataset.wmin, hi = +$('#slg-a').dataset.wmax, n = slWords(answer);
  if (n < lo * 0.5) { if (!(await appConfirm(`只写了 ${n} 字，远低于要求的 ${lo} 字，仍要批改吗？`))) return; }

  let body;
  if (slQuestion) body = { question_id: slQuestion.id, answer };
  else {
    const question = $('#slg-q').value.trim(), material = $('#slg-m').value.trim();
    if (!question) return toast('请填写题干', true);
    body = { type: slType.key, question, material, answer, full: +$('#slg-full').value, word_min: lo, word_max: hi };
  }
  const btn = $('#slg-go');
  btn.disabled = true; btn.textContent = '阅卷中…（30~60 秒）';
  try {
    const d = await api('/api/shenlun/grade', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    renderSlResult(d);
    loadSlHistory();
    if (d.next) showSlNext(d);
  } catch (e) { toast(e.message, true); }
  btn.disabled = false; btn.textContent = '开始批改';
};

/* ---- 做完一题 → 提示继续下一题 ---- */
function showSlNext(d) {
  $('#sln-title').textContent = `第 ${d.seq} 题 已批改：${d.score} / ${d.full} 分`;
  $('#sln-body').textContent = `下一题是「第 ${d.next.seq} 题 · ${d.next.type_name}」（${d.next.full} 分），现在继续吗？`;
  $('#sl-next').classList.remove('hidden');
  $('#sln-stay').onclick = () => $('#sl-next').classList.add('hidden');
  $('#sln-go').onclick = async () => {
    $('#sl-next').classList.add('hidden');
    try {
      const p = await api('/api/shenlun/paper/' + d.paper_id);
      slPaper = p;
      const q = p.questions.find(x => x.id === d.next.id);
      if (q) openSlGradeQ(q);
    } catch (e) { toast(e.message, true); }
  };
}

async function openSlRecord(rid) {
  try {
    const d = await api('/api/shenlun/record/' + rid);
    renderSlResult(d.result);
  } catch (e) { toast(e.message, true); }
}

function renderSlResult(r) {
  push({ view: 'slresult', title: '批改结果' });
  const pct = r.full ? r.score / r.full : 0;
  const grade = pct >= 0.8 ? 'good' : pct >= 0.6 ? 'ok' : 'bad';
  const lv = r.level || (pct >= 0.8 ? '优秀' : pct >= 0.6 ? '达标' : '待提升');
  const hasReq = !!(r.word_min && r.word_max);          // 老记录没存字数要求，别一律标红
  const wOk = !hasReq || (r.words >= r.word_min && r.words <= r.word_max);
  $('#slr-score').innerHTML = `
    <div class="slr-num"><b>${r.score}</b><span>/${r.full}</span></div>
    <div class="slr-pct ${grade}">${Math.round(pct * 100)}%</div>
    <div class="slr-stat">
      <span class="slr-dot good"></span>命中 ${r.hit_n || 0}
      <span class="slr-dot ok"></span>部分 ${r.part_n || 0}
      <span class="slr-dot bad"></span>未中 ${r.miss_n || 0}
      ${r.words ? `<span class="slr-w ${wOk ? '' : 'warn'}">${r.words} 字${hasReq ? ` / 要求 ${r.word_min}-${r.word_max}` : ''}</span>` : ''}
    </div>
    <div class="slr-lv ${grade}">${esc(lv)}</div>`;

  $('#slr-points').innerHTML = (r.points || []).map((p, i) => {
    const state = (p.misses && p.misses.length && !p.yours) ? 'bad'
      : ((p.partial && p.partial.length) || (p.misses && p.misses.length)) ? 'ok' : 'good';
    return `<div class="slp ${state}">
      <div class="slp-head"><span class="slp-no">${i + 1}</span>
        <span class="slp-name">${esc(p.name || '')}</span>
        <span class="slp-score">${p.got}<i>/${p.max}</i></span></div>
      ${p.yours ? `<div class="slp-yours"><b>你的：</b>${esc(p.yours)}</div>`
      : `<div class="slp-yours slp-none">这一点没有作答</div>`}
      ${(p.hits || []).map(h => `<div class="slp-li hit">✓ ${esc(h)}</div>`).join('')}
      ${(p.partial || []).map(h => `<div class="slp-li part">— ${esc(h)}</div>`).join('')}
      ${(p.misses || []).map(h => `<div class="slp-li miss">✕ ${esc(h)}</div>`).join('')}
      ${p.material ? `<div class="slp-mat"><b>对照材料：</b>${esc(p.material)}</div>` : ''}
    </div>`;
  }).join('') + ((r.advice || []).length ? `<div class="slr-advice"><div class="slt-sec">改进建议</div><ul>`
    + r.advice.map(a => `<li>${esc(a)}</li>`).join('') + `</ul></div>` : '');

  const rw = r.ref_words || slWords(r.reference);
  const refOk = !hasReq || (rw >= r.word_min && rw <= r.word_max);
  // 范文是批改之外的一次独立 AI 调用，超时就会是空的 → 给个单独重生成的按钮，不用重跑整份批改
  $('#slr-ref').innerHTML = r.reference
    ? `<div class="slt-sec">参考范文（${esc(r.type_name || '')}）</div>
       <div class="slr-wtag ${refOk ? '' : 'warn'}">${rw} 字${hasReq ? ` · 题目要求 ${r.word_min}-${r.word_max} 字` : ''}</div>
       <div class="slr-reftext">${esc(r.reference).replace(/\n/g, '<br>')}</div>`
    : `<div class="slt-sec">参考范文（${esc(r.type_name || '')}）</div>
       <p class="empty">这次没生成出范文（生成范文是批改之外单独的一次 AI 调用，超时/失败就会空着）。<br>
       点下面的按钮单独重生成，不用重跑整份批改。</p>
       ${r.id ? `<button class="btn primary" id="slr-regen" data-rid="${r.id}">🔄 重新生成参考范文</button>` : ''}`;

  $('#slr-orig').innerHTML = `<div class="slt-sec">题干</div>
    <div class="slr-reftext">${esc(r.question || '').replace(/\n/g, '<br>')}</div>
    <div class="slt-sec">给定资料</div>
    <div class="slr-reftext slr-mat">${esc(r.material || '（本次批改没有提供给定资料）').replace(/\n/g, '<br>')}</div>`;

  $('#slr-mine').innerHTML = `<div class="slt-sec">作答原文</div>
    <div class="slr-wtag ${wOk ? '' : 'warn'}">${r.words || slWords(r.answer)} 字${hasReq ? ` · 要求 ${r.word_min}-${r.word_max} 字` : ''}</div>
    <div class="slr-reftext">${esc(r.answer || '').replace(/\n/g, '<br>')}</div>`;
  slrTab('points');
  window.scrollTo(0, 0);
}
function slrTab(t) {
  document.querySelectorAll('.slr-tabs .tk-tab').forEach(x => x.classList.toggle('active', x.dataset.slrt === t));
  ['points', 'ref', 'orig', 'mine'].forEach(k => $('#slr-' + k).classList.toggle('hidden', k !== t));
}
document.querySelector('.slr-tabs').addEventListener('click', e => {
  const b = e.target.closest('[data-slrt]'); if (b) slrTab(b.dataset.slrt);
});
$('#slr-ref').addEventListener('click', async e => {
  const b = e.target.closest('#slr-regen'); if (!b) return;
  b.disabled = true; b.textContent = '生成中…（约 30 秒）';
  try {
    const d = await api('/api/shenlun/record/' + b.dataset.rid + '/reference', { method: 'POST' });
    await openSlRecord(b.dataset.rid);
    toast('范文已生成（' + d.ref_words + ' 字）');
  } catch (err) {
    toast(err.message, true);
    b.disabled = false; b.textContent = '🔄 重新生成参考范文';
  }
});

/* ================= 常考（高频考点合集） + 上位词 ================= */
async function openChangkao() {
  push({ view: 'changkao', title: '常考' });
  loadCkBoards();
  loadHyperDaily();
}
async function loadCkBoards() {
  $('#ck-boards').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/changkao/boards');
    let nStar = 0;
    try { nStar = (await api('/api/changkao/stars')).total; } catch (_) {}
    $('#ck-boards').innerHTML = '<div class="home-cards cs-cards" data-dragsort="ckb">' + d.boards.map(b => `
      <div class="home-card ck-card" data-ckb="${esc(b.key)}">
        <div class="hc-logo hc-ck">${IC[b.icon] || IC.bulb}</div>
        <div class="hc-name">${esc(b.name)}</div>
        <div class="hc-desc">${b.count} 条 · ${esc(b.desc)}</div>
      </div>`).join('') + `
      <div class="home-card ck-card ck-star-card" data-ckb="收藏">
        <div class="hc-logo hc-star">★</div>
        <div class="hc-name">我的收藏</div>
        <div class="hc-desc">${nStar} 条 · 六个模块收藏的都在这</div>
      </div>` + '</div>';
  } catch (e) { $('#ck-boards').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#ck-boards').addEventListener('click', e => {
  const c = e.target.closest('[data-ckb]'); if (c) openCkBoard(c.dataset.ckb);
});
async function loadHyperDaily() {
  try {
    const d = await api('/api/hyper/daily');
    if (!d.items || !d.items.length) { $('#ck-daily').classList.add('hidden'); return; }
    $('#ck-daily').innerHTML = `<div class="ckd-tag">🎯 今日推荐 · 上位词</div>` +
      d.items.map(it => `<div class="ckd-item" data-ckd="${it.id}">
        <div class="ckd-h">${esc(it.hyper)}</div>
        <div class="ckd-s">${esc(it.subs || '')}</div>
        ${it.note ? `<div class="ckd-n">${esc(it.note)}</div>` : ''}
      </div>`).join('');
    $('#ck-daily').classList.remove('hidden');
  } catch (_) { $('#ck-daily').classList.add('hidden'); }
}
$('#ck-daily').addEventListener('click', () => openCkBoard('上位词'));

let ckBoard = '', ckItems = [], ckKind = 'text';
async function openCkBoard(key) {
  ckBoard = key;
  await loadCkStarred();                        // 六个模块都要标★
  push({ view: 'ckboard', title: key === '上位词' ? '上位词积累' : (key === '收藏' ? '我的收藏' : '常考 · ' + key) });
  $('#ckb-search').value = '';
  $('#ckb-ai').classList.toggle('hidden', key !== '上位词');
  $('#ckb-head').innerHTML = '';
  $('#ckb-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    if (key === '收藏') {
      const d = await api('/api/changkao/stars');
      ckItems = d.boards.flatMap(b => b.items.map(x =>
        ({ id: x.item_id, title: x.title, content: x.content, note: x.note, _b: b.board })));
      ckKind = 'star';
      $('#ckb-head').innerHTML = `<span class="ckb-n">${d.total} 条</span>` +
        '<span class="ckb-tip">再点一次 ★ 取消收藏</span>';
      renderCkList();
      return;
    }
    const d = await api('/api/changkao/items?board=' + encodeURIComponent(key));
    ckItems = d.items; ckKind = d.kind;
    $('#ckb-head').innerHTML = `<span class="ckb-n">${d.items.length} 条</span>` +
      (key === '上位词' ? '<span class="ckb-tip">逻辑填空里题干出现上位词，答案必须与它同类</span>' : '');
    renderCkList();
  } catch (e) { $('#ckb-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
// 收藏是**六个模块通用**的（key = "板块:id"）。成语/实词额外同步进「成语词语积累」——
// 收藏就是为了拿去背，散在两处等于没收。
let ckStarred = new Set();
async function loadCkStarred() {
  try {
    const d = await api('/api/changkao/stars?ids=1');
    ckStarred = new Set(d.ids || []);
  } catch (_) {}
}
function renderCkList() {
  const q = $('#ckb-search').value.trim();
  const list = q ? ckItems.filter(it =>
    (it.title || '').includes(q) || (it.content || '').includes(q) || (it.note || '').includes(q)) : ckItems;
  if (!list.length) {
    $('#ckb-list').innerHTML = ckBoard === '收藏'
      ? '<p class="empty">还没收藏。进任一模块，点卡片上的 ☆ 就收进来了。</p>'
      : '<p class="empty">没有匹配的内容</p>';
    return;
  }
  $('#ckb-list').innerHTML = list.map(it => {
    const b = it._b || ckBoard;                       // 收藏页里每条来自不同板块
    const key = b + ':' + it.id;
    const on = ckStarred.has(key);
    const freq = it.freq && b === '成语' ? `<span class="cki-freq">考频 ${it.freq}</span>` : '';
    const note = (it.note || '').replace(/^考频 \d+ 次(\s·\s)?/, '');   // 考频已单独成徽章
    const tip = CK_TO_ENTRY[b] ? '收藏 → 同时收进「成语词语积累」' : '收藏';
    return `<div class="gk-card ck-item" data-cki="${it.id}" data-ckbd="${esc(b)}">
      <div class="cki-t">${esc(it.title)}${freq}
        ${ckBoard === '收藏' ? `<span class="cki-from">${esc(b)}</span>` : ''}
        <button class="cki-star${on ? ' on' : ''}" data-ckstar="${esc(b)}:${it.id}"
          title="${tip}">${on ? '★' : '☆'}</button>
        ${ckKind === 'hyper' ? `<button class="cki-del" data-ckdel="${it.id}">🗑</button>` : ''}</div>
      ${it.meaning ? `<div class="cki-mean"><b>释义</b>${esc(it.meaning)}</div>` : ''}
      ${it.content ? `<div class="cki-c">${b === '实词' && it.meaning ? '<span class="cki-c-lab">搭配</span>' : ''}${esc(it.content)}</div>` : ''}
      ${note ? `<div class="cki-n">${(ckKind === 'classic' || b === '古诗文') ? esc(note) : '💡 ' + esc(note)}</div>` : ''}
      ${(b === '上位词') ? '<div class="cki-more">点开看每个下位词的典故 / 出处 / 怎么考 ›</div>'
        : (b === '成语' || b === '实词') ? '<div class="cki-more">点开看典故 / 出处 / 怎么考 ›</div>' : ''}
    </div>`;
  }).join('');
}
// 这两类收藏时会同步进「言语理解 → 成语词语积累」的对应分类（服务端 CK_TO_ENTRY 也有一份）
const CK_TO_ENTRY = { '成语': '成语', '实词': '词语' };
$('#ckb-search').addEventListener('input', renderCkList);
$('#ckb-list').addEventListener('click', async e => {
  const star = e.target.closest('[data-ckstar]');
  if (star) {                                   // 收藏 / 取消收藏（六个模块通用）
    e.stopPropagation();
    const [b, id] = star.dataset.ckstar.split(':');
    star.disabled = true;
    try {
      const r = await api('/api/changkao/star', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ board: b, id: +id }),
      });
      if (r.starred) {
        ckStarred.add(b + ':' + id);
        star.textContent = '★'; star.classList.add('on');
        toast(r.to_entry ? `已收藏，并收进「成语词语积累 · ${r.category}」，明天开始进复习`
          : (CK_TO_ENTRY[b] ? '已收藏（「成语词语积累」里本来就有）' : '已收藏'));
      } else {
        ckStarred.delete(b + ':' + id);
        star.textContent = '☆'; star.classList.remove('on');
        toast('已取消收藏');
        if (ckBoard === '收藏') { openCkBoard('收藏'); return; }   // 收藏页里取消了就移走
      }
    } catch (err) { toast(err.message, true); }
    star.disabled = false;
    return;
  }
  const del = e.target.closest('[data-ckdel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('从上位词库中删除这一组？'))) return;
    try { await api('/api/hyper/' + del.dataset.ckdel, { method: 'DELETE' }); openCkBoard('上位词'); }
    catch (er) { toast(er.message, true); }
    return;
  }
  const it = e.target.closest('[data-cki]');
  if (!it) return;
  const b = it.dataset.ckbd || ckBoard;
  if (b === '古诗文') openClassicDetail(+it.dataset.cki);
  else if (b === '上位词') openHyper(+it.dataset.cki);              // 上位词：点开看典故/来源
  else if (b === '成语' || b === '实词') openCkStory(+it.dataset.cki);   // 成语/实词：点开看典故
});

/* 成语/实词的典故：出处原文 + 故事 + 本义怎么引申成今义 + 公考怎么考。
   看懂来历自然就记住了，不用死背释义。AI 讲一次就缓存，之后秒开。 */
async function openCkStory(cid) {
  push({ view: 'cdetail', title: '典故' });
  $('#cd-wrap').innerHTML = '<p class="empty">正在讲典故…（第一次约 20 秒，之后秒开）</p>';
  try {
    const d = await api('/api/changkao/' + cid + '/story');
    const s = d.story || {};
    $('#cd-wrap').innerHTML = `
      <div class="cd-head"><div class="cd-title">${esc(d.title)}</div>
        <div class="cd-meta">常考 · ${esc(d.board || '')}${d.freq ? ` · 考频 ${d.freq} 次` : ''}</div></div>
      ${d.content ? `<div class="cd-sec"><div class="cd-sec-t">释义</div><div class="cd-sec-b">${esc(d.content)}</div></div>` : ''}
      ${s.origin ? `<div class="cd-sec"><div class="cd-sec-t">📜 出处</div><div class="cd-sec-b ck-origin">${esc(s.origin)}</div></div>` : ''}
      ${s.story ? `<div class="cd-sec"><div class="cd-sec-t">📖 典故</div><div class="cd-sec-b ck-story">${esc(s.story)}</div></div>` : ''}
      ${s.evolve ? `<div class="cd-sec"><div class="cd-sec-t">🔗 本义 → 今义</div><div class="cd-sec-b">${esc(s.evolve)}</div></div>` : ''}
      ${s.usage ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">🎯 公考怎么考</div><div class="cd-sec-b">${esc(s.usage)}</div></div>` : ''}
      <div class="cd-sec" id="ck-ex"><div class="cd-sec-t">✍️ 例句</div>
        <div class="cd-sec-b"><button class="btn tiny" id="ck-ex-go" data-cid="${cid}">找一句真实例句</button>
        <span class="ck-ex-hint">先在人民日报等真语料里找；找不到才 AI 仿写（会标明）</span></div></div>
      <div class="cd-sec" id="ck-cf"><div class="cd-sec-t">⚖️ 易混辨析</div>
        <div class="cd-sec-b"><button class="btn tiny" id="ck-cf-go" data-cid="${cid}">辨析相似词</button>
        <span class="ck-ex-hint">逻辑填空考的就是「这几个近义词该用哪个」</span></div></div>`;
    window.scrollTo(0, 0);
    injectReadBtns();
    ckLoadExample(cid);          // 已经有例句就直接显示，不用点
    ckLoadConfuse(cid, true);
  } catch (e) {
    $('#cd-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>';
  }
}

/* ---- 例句：真语料优先（人民日报等），找不到才 AI 仿写并标明 ---- */
async function ckLoadExample(cid, force) {
  const box = $('#ck-ex'); if (!box) return;
  const btn = $('#ck-ex-go');
  if (!force && btn) { btn.disabled = true; btn.textContent = '查找中…'; }
  try {
    const d = await api(`/api/changkao/${cid}/example${force ? '?force=1' : ''}`);
    const ai = (d.src || '').startsWith('AI');
    box.querySelector('.cd-sec-b').innerHTML = `
      <div class="ck-ex">${esc(d.example)}</div>
      <div class="ck-ex-src ${ai ? 'ai' : 'real'}">${ai ? '✎' : '📰'} ${esc(d.src || '')}</div>`;
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = '找一句真实例句'; }
  }
}
document.addEventListener('click', e => {
  const b = e.target.closest('#ck-ex-go');
  if (b) { b.disabled = true; b.textContent = '查找中…'; ckLoadExample(+b.dataset.cid, true); }
});

/* ---- 易混辨析：给出 2~3 个最容易混的词，逐条说清「用哪个」 ---- */
async function ckLoadConfuse(cid, quiet) {
  const box = $('#ck-cf'); if (!box) return;
  try {
    const d = await api(`/api/changkao/${cid}/confuse${quiet ? '' : '?force=1'}`);
    if (quiet && !d.cached) return;         // 静默模式只显示已经生成过的，不主动烧 AI
    ckRenderConfuse(box, d);
  } catch (_) {}
}
function ckRenderConfuse(box, d) {
  const q = d.quiz;
  box.querySelector('.cd-sec-b').innerHTML = `
    ${d.key ? `<div class="ck-cf-key">🔑 ${esc(d.key)}</div>` : ''}
    ${(d.items || []).map(x => `
      <div class="ck-cf-i">
        <div class="ck-cf-w">${esc(d.word)} <i>vs</i>
          ${x.in_lib ? `<b class="ck-cf-go" data-ckcf="${x.id}">${esc(x.word)}</b>`
                     : `<b>${esc(x.word)}</b><span class="ck-cf-out">库外</span>`}</div>
        <div class="ck-cf-r"><span>词义侧重</span>${esc(x.focus || '')}</div>
        <div class="ck-cf-r"><span>感情色彩</span>${esc(x.color || '')}</div>
        <div class="ck-cf-r"><span>搭配对象</span>${esc(x.collocation || '')}</div>
        ${x.wrong ? `<div class="ck-cf-bad">✗ ${esc(x.wrong)}</div>` : ''}
      </div>`).join('')}
    ${q ? `<div class="ck-cf-quiz" data-ans="${esc(q.answer)}">
        <div class="ck-cf-q">📝 ${esc(q.stem)}</div>
        <div class="ck-cf-opts">${q.options.map((o, i) =>
          `<button class="dt-opt" data-ckq="${DT_L[i]}">${esc(o)}</button>`).join('')}</div>
        <div class="ck-cf-why hidden">${esc(q.why || '')}</div>
      </div>` : ''}`;
}
document.addEventListener('click', e => {
  const b = e.target.closest('#ck-cf-go');
  if (b) { b.disabled = true; b.textContent = '辨析中…（约 20 秒）'; ckLoadConfuse(+b.dataset.cid); return; }
  const g = e.target.closest('[data-ckcf]');
  if (g) { openCkStory(+g.dataset.ckcf); return; }        // 点对比词 → 直接看它的详情
  const o = e.target.closest('[data-ckq]');
  if (o) {                                                 // 填空自测：选完立刻判
    const box = o.closest('.ck-cf-quiz');
    const ans = box.dataset.ans;
    box.querySelectorAll('[data-ckq]').forEach(x => {
      x.disabled = true;
      if (x.dataset.ckq === ans) x.classList.add('correct');
      else if (x === o) x.classList.add('wrong');
    });
    box.querySelector('.ck-cf-why').classList.remove('hidden');
  }
});

/* 上位词详解：每个下位词的出处、典故、公考考点（AI 讲一次就缓存，之后秒开） */
async function openHyper(hid) {
  push({ view: 'cdetail', title: '上位词详解' });
  $('#cd-wrap').innerHTML = '<p class="empty">正在讲典故…（第一次要 30 秒左右，之后秒开）</p>';
  try {
    const d = await api('/api/hyper/' + hid);
    $('#cd-wrap').innerHTML = `
      <div class="cd-head"><div class="cd-title">${esc(d.hyper)}</div>
        <div class="cd-meta">上位词 · 逻辑填空里的概括词</div></div>
      <div class="cd-sec"><div class="cd-sec-t">下位词</div>
        <div class="cd-sec-b">${esc(d.subs || '')}</div></div>
      ${d.note ? `<div class="cd-sec"><div class="cd-sec-t">💡 提示</div><div class="cd-sec-b">${esc(d.note)}</div></div>` : ''}
      ${(d.story || []).map(x => `
        <div class="cd-sec hy-sec">
          <div class="cd-sec-t">${esc(x.name)}</div>
          ${x.origin ? `<div class="hy-row"><b>出处</b>${esc(x.origin)}</div>` : ''}
          ${x.story ? `<div class="hy-row hy-story"><b>典故</b>${esc(x.story)}</div>` : ''}
          ${x.point ? `<div class="hy-row hy-point"><b>怎么考</b>${esc(x.point)}</div>` : ''}
        </div>`).join('')}`;
    window.scrollTo(0, 0);
    injectReadBtns();
  } catch (e) {
    $('#cd-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>';
  }
}
$('#ckb-ai').onclick = async () => {
  const w = await appPrompt('AI 补充上位词', '输入一个词（如「戏曲」或「京剧」），AI 会归纳它的上位词与同类下位词');
  if (!w || !w.trim()) return;
  toast('AI 分析中…');
  try {
    const d = await api('/api/hyper/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ word: w.trim() }) });
    toast(d.cached ? '已在库中：' + d.hyper : '已收录：' + d.hyper);
    openCkBoard('上位词');
  } catch (e) { toast(e.message, true); }
};

/* ================= 理论基础（马原/毛概/中特/习思想） ================= */
async function openTheory() {
  push({ view: 'theory', title: '理论基础' });
  $('#th-boards').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/theory/boards');
    $('#th-boards').innerHTML = '<div class="home-cards cs-cards" data-dragsort="thb">' + d.boards.map(b => `
      <div class="home-card ck-card" data-thb="${esc(b.name)}">
        <div class="hc-logo hc-th">${IC[b.icon] || IC.book}</div>
        <div class="hc-name">${esc(b.short)}</div>
        <div class="hc-desc">${b.count} 条 · ${esc(b.desc)}</div>
      </div>`).join('') + '</div>';
  } catch (e) { $('#th-boards').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#th-boards').addEventListener('click', e => {
  const c = e.target.closest('[data-thb]'); if (c) openThBoard(c.dataset.thb);
});
async function openThBoard(name) {
  push({ view: 'thboard', title: name.length > 10 ? name.slice(0, 9) + '…' : name });
  $('#thb-head').innerHTML = ''; $('#thb-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/theory/items?board=' + encodeURIComponent(name));
    $('#thb-head').innerHTML = `<div class="thb-title">${esc(name)}</div>
      <div class="thb-desc">${esc(d.desc || '')}</div><span class="ckb-n">${d.count} 个考点</span>`;
    if (!d.topics.length) { $('#thb-list').innerHTML = '<p class="empty">内容生成中，稍后再来～</p>'; return; }
    $('#thb-list').innerHTML = d.topics.map(t => `
      <div class="th-topic"><div class="th-tname">${esc(t.name)}</div>
        ${t.items.map(it => `<div class="gk-card th-item">
          <div class="cki-t">${esc(it.title)}</div>
          <div class="cki-c">${emKey(it.content || '')}</div>
        </div>`).join('')}
      </div>`).join('');
  } catch (e) { $('#thb-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}


/* ============= 今日复习（艾宾浩斯遗忘曲线） ============= */
const RV_KIND = { entry: '成语词语', wrongq: '错题', classic: '古诗文' };
const RV_COLOR = { entry: '#2b6fd6', wrongq: '#b23b2e', classic: '#0f766e' };
const RV_INTERVALS = [1, 2, 4, 7, 15, 30, 60];
let rvQueue = [], rvTotal = 0, rvDoneN = 0;
/* 词语句子 / 每日积累 / 批注 / 错题 各背各的，不混成一副牌 */
let rvAll = [], rvGroup = 'word', rvDoneToday = {};
const RV_GROUP_NAME = { word: '词语句子', daily: '每日积累', annot: '批注', wrongq: '错题' };
/* 每日复习量：一天能背多少因人而异。堆太多就不想背了 —— 超出上限的**不会丢**，
   只是今天不出现（到期时间不变，明天照样在）。0 = 不限。 */
const RV_LNAME = { word: '词语句子', daily: '每日积累', annot: '批注', wrongq: '错题' };
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
    if (!(g[rvGroup] > 0)) rvGroup = ['word', 'daily', 'wrongq'].find(k => g[k] > 0) || 'word';
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
      ? `<p class="empty">✅ 「${RV_GROUP_NAME[group] || ''}」今日已完成 <b>${done}</b> 条${lim ? '（每日量 ' + lim + '）' : ''}，明天见～<br><span style="font-size:13px;color:var(--muted)">想多背可到「每日复习量」调高上限。</span></p>`
      : '<p class="empty">🎉 这个板块今天没有要复习的内容。收录的成语/古诗文、每日素材、错题会按遗忘曲线（1/2/4/7/15/30/60 天）分别出现。</p>';
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
    ${(mat && !isFig) ? (_dtLastMat = '', dtMaterial(mat, 'qz' + qz.idx))          /* 资料分析：真表格 / 图表 */
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
      // 答错自动收进错题本
      if (!d.correct) {
        try {
          const fd = new FormData();
          fd.append('board', q.module === '申论' ? '申论' : q.module);
          fd.append('question', q.question + '\n' + (q.options || []).join('\n'));
          fd.append('answer', d.answer);
          fd.append('qtype', q.qtype || q.module);
          fd.append('points', ''); fd.append('note', '来自题库：' + qz.set.name);
          fd.append('analyze', '0');
          await api('/api/wrongq', { method: 'POST', body: fd });
          toast('已答错，这题自动收进错题本');
        } catch (_) { }
      }
    } catch (err) { toast(err.message, true); }
  }
});

/* ============= 经典著作（毛泽东选集） ============= */
let wkData = null;
async function openWorks() {
  push({ view: 'works', title: '经典著作' });
  $('#wk-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/works');
    $('#wk-list').innerHTML = d.items.map(it => `
      <div class="poly-card" data-work="${it.id}">
        <div class="poly-t" style="font-size:15.5px">${it.ord + 1}. ${esc(it.title)}</div>
        <div class="poly-meta">${esc(it.book)} · 约 ${(it.chars / 1000).toFixed(1)} 千字${it.has_ai ? ' · <span class="poly-ai-on">✓ 已有AI导读</span>' : ''}</div>
      </div>`).join('');
  } catch (e) { $('#wk-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#wk-list').addEventListener('click', e => {
  const c = e.target.closest('[data-work]'); if (c) openWorkDetail(+c.dataset.work);
});
async function openWorkDetail(id) {
  push({ view: 'workd', title: '精读' });
  $('#wk-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/works/' + id); wkData = d;
    stack[stack.length - 1].title = d.title; $('#top-title').textContent = d.title;
    renderWork();
  } catch (e) { $('#wk-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderWork() {
  const d = wkData;
  const ai = d.interpretation
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">🤖 AI 导读</div><div class="cd-sec-b">${mdToHtml(d.interpretation)}</div>
        <button class="btn cd-ai-regen" id="wk-regen">重新生成</button></div>`
    : `<div class="poly-genbox"><p class="cd-tip" style="margin:0 0 10px">让 AI 梳理这篇文章的写作背景、核心观点、名句与公考运用。</p>
        <button class="btn primary" id="wk-gen" style="width:100%;padding:12px;">🤖 生成 AI 导读</button></div>`;
  const body = (d.content || '').split('\n').filter(x => x.trim()).map(p => {
    const s2 = p.trim();
    return isDocHeading(s2) ? `<p class="poly-h">${emKey(s2)}</p>` : `<p>${emKey(s2)}</p>`;
  }).join('');
  $('#wk-wrap').innerHTML = `
    <div class="poly-head"><h2>${esc(d.title)}</h2>
      <div class="news-date">📕 ${esc(d.book)}</div></div>
    ${ai}
    <div class="poly-readert">全文</div>
    <div class="poly-reader">${body}</div>`;
}
$('#wk-wrap').addEventListener('click', async e => {
  const g = e.target.closest('#wk-gen') || e.target.closest('#wk-regen');
  if (!g) return;
  g.disabled = true; g.textContent = 'AI 导读生成中…（约二三十秒）';
  try {
    const d = await api('/api/works/' + wkData.id + '/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: g.id === 'wk-regen' }) });
    wkData.interpretation = d.content; renderWork(); toast('已生成');
  } catch (err) { toast(err.message, true); g.disabled = false; g.textContent = '🤖 生成 AI 导读'; }
});

/* ============= 常识积累（7板块 · 考情 + 高频考点） ============= */
const CS_COLOR = { '人文常识': '#b23b2e', '科技常识': '#2b6fd6', '法律常识': '#8c2f24', '地理常识': '#0f766e', '经济常识': '#c2671f', '公文常识': '#7a5cc0', '管理常识': '#5a6b85' };
let csBoard = '', csTopic = '';
async function openChangshi() {
  push({ view: 'changshi', title: '常识积累' });
  $('#cs-tiers').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/changshi/boards');
    $('#cs-tiers').innerHTML = d.tiers.map(t => `
      <div class="cs-tier-name">${esc(t.name)}</div>
      <div class="home-cards cs-cards" data-dragsort="csb:${esc(t.name)}">${t.boards.map(b => `
        <div class="home-card" data-csb="${esc(b.name)}">
          <div class="hc-logo" style="background:${CS_COLOR[b.name] || '#666'}">${esc(b.name[0])}</div>
          <div class="hc-name">${esc(b.name)}</div>
          <div class="hc-desc">${b.topics} 个专题 · ${b.count} 条考点</div>
        </div>`).join('')}</div>`).join('');
  } catch (e) { $('#cs-tiers').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#cs-tiers').addEventListener('click', e => {
  const c = e.target.closest('[data-csb]'); if (c) openCsBoard(c.dataset.csb);
});
function openCsBoard(board) {
  csBoard = board; csTopic = '';
  push({ view: 'csboard', title: board });
  loadCsBoard();
}
async function loadCsBoard() {
  $('#cs-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/changshi/board?board=' + encodeURIComponent(csBoard) + '&topic=' + encodeURIComponent(csTopic));
    csTopic = d.topic;
    $('#top-title').textContent = csBoard;
    $('#cs-ov-body').innerHTML = emKey(d.overview);
    $('#cs-topics').innerHTML = d.topics.map(t =>
      `<button class="chip ${t.name === csTopic ? 'active' : ''}" data-cst="${esc(t.name)}">${esc(t.name)}${t.count ? ' ' + t.count : ''}</button>`).join('');
    const tm = d.topics.find(t => t.name === csTopic) || {};
    $('#cs-kaoqing').innerHTML = `
      <div class="cs-kq">
        ${tm.tezheng ? `<div class="cs-kq-row"><b>题型特征</b>${emKey(tm.tezheng)}</div>` : ''}
        ${tm.silu ? `<div class="cs-kq-row"><b>破题思路</b>${emKey(tm.silu)}</div>` : ''}
        ${tm.map ? `<div class="cs-kq-row cs-kq-map"><b>要点导图</b>${emKey(tm.map)}</div>` : ''}
      </div>`;
    if (!d.items.length) {
      $('#cs-list').innerHTML = '<p class="empty">' + (d.daily ? '考点生成中，每天还会自动新增～' : '考点生成中，稍后再来看看～') + '</p>';
      return;
    }
    $('#cs-list').innerHTML = d.items.map(it => `
      <div class="gk-card">
        <div class="gk-head"><span class="poly-badge" style="background:${CS_COLOR[csBoard] || '#666'}">${esc(it.title)}</span>
          <span class="cs-date">${esc(it.date || '')}${it.source === '新法跟踪' ? ' · 新法跟踪' : ''}</span></div>
        <div class="sc-body">${emKey(it.content)}</div>
      </div>`).join('');
  } catch (e) { $('#cs-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#cs-topics').addEventListener('click', e => {
  const c = e.target.closest('[data-cst]'); if (!c) return;
  csTopic = c.dataset.cst; loadCsBoard();
});
$('#cs-ov-toggle').onclick = () => {
  const b = $('#cs-ov-body'); b.classList.toggle('hidden');
  $('#cs-ov-toggle').querySelector('.cs-ov-arrow').textContent = b.classList.contains('hidden') ? '▾' : '▴';
};

/* ================= 时政要文库（重要文件全文 + AI 政策解读） ================= */
let polyData = null;
const POLY_COLOR = { '重要讲话': '#c81e1e', '党代会报告': '#b23b2e', '中央全会文件': '#8c2f24', '政府工作报告': '#2b6fd6', '中央一号文件': '#0f766e', '地方政府工作报告': '#7a5cc0', '五年规划': '#c2671f' };
async function openPolicyDocs() {
  push({ view: 'policydoc', title: '时政要文库' });
  $('#poly-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/policydocs');
    $('#poly-list').innerHTML = d.items.map(it => {
      const col = POLY_COLOR[it.category] || '#666';
      return `<div class="poly-card" data-poly="${it.id}">
        <span class="poly-badge" style="background:${col}">${esc(it.category)}</span>
        <div class="poly-t">${esc(it.title)}</div>
        <div class="poly-meta">全文约 ${(it.chars / 1000).toFixed(1)} 千字${it.has_ai ? ' · <span class="poly-ai-on">✓ 已有 AI 解读</span>' : ''}</div>
      </div>`;
    }).join('');
  } catch (e) { $('#poly-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#poly-list').addEventListener('click', e => {
  const c = e.target.closest('[data-poly]'); if (c) openPolicyDoc(+c.dataset.poly);
});
async function openPolicyDoc(id) {
  push({ view: 'policydocd', title: '要文精读' });
  $('#poly-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/policydocs/' + id); polyData = d;
    stack[stack.length - 1].title = d.title; $('#top-title').textContent = d.title;
    renderPolicyDoc();
  } catch (e) { $('#poly-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderPolicyDoc() {
  const d = polyData;
  const ai = d.interpretation
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">🤖 AI 政策解读</div><div class="cd-sec-b">${mdToHtml(d.interpretation)}</div>
        <button class="btn cd-ai-regen" id="poly-regen">重新生成</button></div>`
    : `<div class="poly-genbox"><p class="cd-tip" style="margin:0 0 10px">让 AI 提炼这份文件的核心要点、公考高频考点、可引用金句与答题运用。</p>
        <button class="btn primary" id="poly-gen" style="width:100%;padding:12px;">🤖 生成 AI 政策解读</button></div>`;
  const body = (d.content || '').split('\n').filter(x => x.trim()).map(p => {
    const s = p.trim();
    return isDocHeading(s) ? `<p class="poly-h">${emKey(s)}</p>` : `<p>${emKey(s)}</p>`;
  }).join('');
  $('#poly-wrap').innerHTML = `
    <div class="poly-head"><h2>${esc(d.title)}</h2>
      <a class="poly-src" href="${esc(d.source_url)}" target="_blank" rel="noopener">原文来源 ↗</a></div>
    ${ai}
    <div class="poly-readert">全文</div>
    <div class="poly-reader">${body}</div>`;
}
$('#poly-wrap').addEventListener('click', async e => {
  const g = e.target.closest('#poly-gen') || e.target.closest('#poly-regen');
  if (!g) return;
  g.disabled = true; g.textContent = 'AI 解读生成中…（约二三十秒）';
  try {
    const d = await api('/api/policydocs/' + polyData.id + '/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: g.id === 'poly-regen' }) });
    polyData.interpretation = d.content; renderPolicyDoc(); toast('已生成');
  } catch (err) { toast(err.message, true); g.disabled = false; g.textContent = '🤖 生成 AI 政策解读'; }
});

/* ================= 人民时评·申论范文（每日抓人民日报评论版） ================= */
let fwBoard = '', fwData = null;
async function openFanwen() {
  push({ view: 'fanwen', title: '人民时评·申论范文' });
  loadFanwen();
}
async function loadFanwen() {
  $('#fw-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/fanwen' + (fwBoard === 'star' ? '?star=1' : ''));
    document.querySelectorAll('#fw-tabs .chip').forEach(c => {
      c.classList.toggle('active', c.dataset.fwb === fwBoard);
      if (c.dataset.fwb === 'star') c.textContent = '⭐ 收藏' + (d.n_star ? ' ' + d.n_star : '');
    });
    if (!d.items.length) {
      $('#fw-list').innerHTML = fwBoard === 'star'
        ? '<p class="empty">还没收藏。读到好范文点 ☆ 收起来，反复临摹。</p>'
        : '<p class="empty">还没有范文。每天早上会自动抓当天的人民时评。</p>';
      return;
    }
    $('#fw-list').innerHTML = d.items.map(it => `
      <div class="fw-card" data-fw="${it.id}">
        <div class="fw-c-top">
          <span class="fw-col">人民时评</span>
          <span class="fw-date">${esc(fmtDay(it.pub_date))}</span>
          <button class="fw-star${it.starred ? ' on' : ''}" data-fwstar="${it.id}"
            title="收藏">${it.starred ? '★' : '☆'}</button>
        </div>
        <div class="fw-t">${esc(it.title)}</div>
        ${it.pullquote ? `<div class="fw-pull">${esc(it.pullquote)}</div>` : ''}
        <div class="fw-meta">${it.author ? esc(it.author) + ' · ' : ''}约 ${(it.chars / 1000).toFixed(1)} 千字${it.has_ai ? ' · <span class="poly-ai-on">✓ 已有 AI 拆解</span>' : ''}</div>
      </div>`).join('');
  } catch (e) { $('#fw-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#fw-tabs').addEventListener('click', e => {
  const c = e.target.closest('[data-fwb]'); if (!c) return;
  fwBoard = c.dataset.fwb; loadFanwen();
});
$('#fw-refresh').onclick = async () => {
  const b = $('#fw-refresh'); b.disabled = true; $('#fw-msg').textContent = '正在抓取今天的人民时评…';
  try {
    const d = await api('/api/fanwen/refresh', { method: 'POST' });
    $('#fw-msg').textContent = d.added > 0 ? `新增 ${d.added} 篇` : '今天暂无更新（周末可能无评论版）';
    if (d.added > 0) { fwBoard = ''; loadFanwen(); }
  } catch (e) { $('#fw-msg').textContent = ''; toast(e.message, true); }
  b.disabled = false;
  setTimeout(() => { $('#fw-msg').textContent = ''; }, 5000);
};
$('#fw-list').addEventListener('click', async e => {
  const s = e.target.closest('[data-fwstar]');
  if (s) {
    e.stopPropagation(); s.disabled = true;
    try {
      const r = await api('/api/fanwen/' + s.dataset.fwstar + '/star', { method: 'POST' });
      s.textContent = r.starred ? '★' : '☆'; s.classList.toggle('on', r.starred);
      toast(r.starred ? '已收藏' : '已取消收藏');
      if (fwBoard === 'star') loadFanwen();
    } catch (err) { toast(err.message, true); }
    s.disabled = false; return;
  }
  const c = e.target.closest('[data-fw]'); if (c) openFanwenItem(+c.dataset.fw);
});
async function openFanwenItem(id) {
  push({ view: 'fanwend', title: '范文精读' });
  $('#fw-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    fwData = await api('/api/fanwen/' + id);
    stack[stack.length - 1].title = fwData.title;
    $('#top-title').textContent = fwData.title;
    renderFanwen();
  } catch (e) { $('#fw-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
let fwReadMode = 'plain';        // plain=纯读；annotated=对照精读（AI 批注跟在每段后）
function renderFanwen() {
  const d = fwData;
  const ai = d.analysis
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">🤖 AI 范文拆解</div><div class="cd-sec-b">${mdToHtml(d.analysis)}</div>
        <button class="btn cd-ai-regen" id="fw-regen">重新生成</button></div>`
    : `<div class="poly-genbox"><p class="cd-tip" style="margin:0 0 10px">让 AI 拆开讲：中心论点、结构脉络、亮点、可仿写的过渡句金句，以及能用在哪些主题。</p>
        <button class="btn primary" id="fw-gen" style="width:100%;padding:12px;">🤖 生成 AI 范文拆解</button></div>`;
  const paras = (d.content || '').split('\n').filter(x => x.trim());
  const ann = d.annotations || {};
  const annotated = fwReadMode === 'annotated';
  // 对照精读：每段后面紧跟这段的 AI 批注 —— 解读和正文对得上，不用两头翻
  const body = paras.map((p, i) => {
    let html = `<p>${emKey(p.trim())}</p>`;
    if (annotated && ann[i]) html += `<div class="fw-anno">💡 ${emKey(ann[i])}</div>`;
    return html;
  }).join('');
  const toolbar = `<div class="fw-readbar">
    <button class="fw-rtab${!annotated ? ' on' : ''}" data-fwmode="plain">纯读</button>
    <button class="fw-rtab${annotated ? ' on' : ''}" data-fwmode="annotated">对照精读</button>
    <span class="fw-rhint">对照精读：AI 逐段批注就跟在每段后面</span>
  </div>`;
  $('#fw-wrap').innerHTML = `
    <div class="poly-head"><h2>${esc(d.title)}</h2>
      <div class="fw-byline">人民时评${d.author ? ' · ' + esc(d.author) : ''}${d.pub_date ? ' · ' + esc(fmtDay(d.pub_date)) : ''}
        <a class="poly-src" href="${esc(d.source_url)}" target="_blank" rel="noopener">原文 ↗</a></div></div>
    ${d.pullquote ? `<div class="fw-pull-big">${emKey(d.pullquote)}</div>` : ''}
    ${ai}
    <div class="poly-readert">范文全文</div>
    ${toolbar}
    <div class="poly-reader${annotated ? ' fw-annotated' : ''}">${body}</div>`;
}
$('#fw-wrap').addEventListener('click', async e => {
  const mt = e.target.closest('[data-fwmode]');
  if (mt) {
    const mode = mt.dataset.fwmode;
    if (mode === 'annotated' && !(fwData.annotations && Object.keys(fwData.annotations).length)) {
      mt.disabled = true; mt.textContent = '生成批注中…';
      try {
        const d = await api('/api/fanwen/' + fwData.id + '/annotate', { method: 'POST' });
        fwData.annotations = d.notes || {};
      } catch (err) { toast(err.message, true); mt.disabled = false; mt.textContent = '对照精读'; return; }
    }
    fwReadMode = mode; renderFanwen(); return;
  }
  const g = e.target.closest('#fw-gen') || e.target.closest('#fw-regen');
  if (!g) return;
  g.disabled = true; g.textContent = 'AI 拆解生成中…（约二三十秒）';
  try {
    const d = await api('/api/fanwen/' + fwData.id + '/ai', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: g.id === 'fw-regen' })
    });
    fwData.analysis = d.content; renderFanwen(); toast('已生成');
  } catch (err) { toast(err.message, true); g.disabled = false; g.textContent = '🤖 生成 AI 范文拆解'; }
});

// #8：AI 解读/拆解都很长，挡着正文。点它的标题可折叠收起（政策解读 / 范文拆解通用）
document.addEventListener('click', e => {
  const t = e.target.closest('.cd-ai > .cd-sec-t');
  if (t) t.parentElement.classList.toggle('cd-collapsed');
});
