/* 申论：真题卷 + 题型讲义 + AI 逐点批改
 *
 * 由 app.js 按它自己的区段边界切出（原 L6040-6394）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, appConfirm, artEm, c, errMsg, esc, frCheckBody, frMatHtml, IC, IS_MOBILE,
   matOpen, openEssays, push, state, toast, uiError */
/* frMatHtml / frCheckBody 来自 find.js（它在 index.html 里先加载）：
   真题批改的「练习模式」和小题训练的找点是同一件事 —— 同一套采分点、同一套判定、
   同一套按句渲染。渲染规则必须共用一份，两边各写一套迟早会判得不一样。 */

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
  } catch (e) { $('#sl-types').innerHTML = uiError(e); }
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
  } catch (err) { toast(errMsg(err), true); }
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
          <div class="sl-hi-t">${artEm('📄')} ${esc(p.title)}</div>
          <div class="sl-hi-m">${p.total} 道题 · 已做 ${p.done} 道 · ${esc(p.created_at.slice(5, 16))}</div>
        </div>
        <div class="sl-hi-s ${p.done >= p.total ? 'good' : 'ok'}">${p.done}<span>/${p.total}</span></div>
        <button class="sl-hi-del" data-slpdel="${p.id}">${artEm('🗑')}</button>
      </div>`).join('') : '<p class="empty">还没有真题卷。点右上角「上传真题」，PDF/Word/图片都行，会自动拆出各道题。</p>';
  } catch (_) { /* 列表拉不到就显示空态，下次进来会重试 */ }
}
$('#sl-papers').addEventListener('click', async e => {
  const del = e.target.closest('[data-slpdel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('删除这份真题卷？批改记录会保留。'))) return;
    try { await api('/api/shenlun/paper/' + del.dataset.slpdel, { method: 'DELETE' }); loadSlPapers(); }
    catch (er) { toast(errMsg(er), true); }
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
  } catch (e) { toast(errMsg(e), true); }
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
        <button class="sl-hi-del" data-sldel="${it.id}">${artEm('🗑')}</button>
      </div>`;
    }).join('') : '<p class="empty">还没有批改记录，挑一道题练一练吧～</p>';
  } catch (_) { /* 列表拉不到就显示空态，下次进来会重试 */ }
}
$('#sl-hist').addEventListener('click', async e => {
  const del = e.target.closest('[data-sldel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('删除这条批改记录？'))) return;
    try { await api('/api/shenlun/record/' + del.dataset.sldel, { method: 'DELETE' }); loadSlHistory(); }
    catch (er) { toast(errMsg(er), true); }
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
  } catch (e) { toast(errMsg(e), true); }
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
  // 自由练没有预标采分点（题干材料是临时贴的），无从判定找点 —— 不给模式选择
  $('#slg-mode').classList.add('hidden');
  $('#slg-find').classList.add('hidden');
  $('#slg-picked').classList.add('hidden');
  $('#slg-body').classList.remove('hidden');
  slMode = 'exam';
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
  slFind = null; slPicked = new Set();   // 换了题，练习模式的找点进度不能带到新题上
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
  // 真题小题才有模式可选（自由练没有预标采分点，无从判定找点）
  $('#slg-mode').classList.remove('hidden');
  slSetMode('exam', { silent: true });
  if (mat && !IS_MOBILE) matOpen(mat, 'p' + slPaper.id);      // 电脑端直接半屏摆出来
}

/* ---- 两种做题模式 ----
   模考模式 = 现有流程：直接写、直接批，还原考场情境。
   练习模式 = 先在给定资料上勾要点、判**找漏/找错/找重**，再照着写 —— 平时练用。
   判定复用真题预标的那套采分点（P2 已存进 shenlun_questions.points），
   和小题训练是**同一套采分点、同一套判法**，两个模块练出来的标准才是一个。 */
let slMode = 'exam', slFind = null, slPicked = new Set(), slDrag = null;

function slSetMode(m, opt = {}) {
  slMode = m;
  document.querySelectorAll('#slg-mode [data-slgm]').forEach(
    b => b.classList.toggle('on', b.dataset.slgm === m));
  const drill = m === 'drill';
  $('#slg-find').classList.toggle('hidden', !drill);
  $('#slg-body').classList.toggle('hidden', drill);   // 找点没判完前先不给写
  // 切回模考就得把练习模式的痕迹收干净，否则「你勾到的句子」会挂在模考页面上
  if (!drill) $('#slg-picked').classList.add('hidden');
  // 同一道题来回切模式不能把已经勾的点/判定结果冲掉，只有这道题还没读过找点数据才去拉
  if (drill && !slFind) slLoadFind();
  else if (drill) slRenderFind();
}
$('#slg-mode').addEventListener('click', e => {
  const b = e.target.closest('[data-slgm]'); if (!b) return;
  if (b.dataset.slgm === slMode) return;
  slSetMode(b.dataset.slgm);
});

async function slLoadFind() {
  if (!slQuestion) return;
  slFind = null; slPicked = new Set();
  $('#slg-find').innerHTML = `<p class="empty">正在准备这道题的要点…<br>
    <i>第一次进练习模式要先标一遍采分点（约 2~3 分钟），之后再进就秒开。</i></p>`;
  try {
    slFind = await api(`/api/shenlun/question/${slQuestion.id}/find`);
    slFind.check = null;
    slRenderFind();
  } catch (e) {
    $('#slg-find').innerHTML = `<p class="empty">${esc(e.message)}</p>
      <button class="btn" id="slg-back-exam">← 用模考模式作答</button>`;
    $('#slg-back-exam').onclick = () => slSetMode('exam');
  }
}

function slRenderFind() {
  const f = slFind, c = f.check;
  const mk = c ? { ok: c.okSents, bad: c.wrongSents, miss: c.missSents, near: c.nearSents } : null;
  const what = f.is_essay ? '立意 / 分论点 / 论据' : '要点';
  $('#slg-find').innerHTML = `
    <div class="fr-tip">${artEm('🖍')} 在材料里<b>点句子</b>勾出你认为的${esc(what)}（按住拖可以连选）。
      ${f.is_essay
        ? '大作文没有采分点，这一步找的是<b>动笔前的备料</b>：题目那句话的出处、可当分论点的侧面、能直接引的案例数据。'
        : '这一步<b>只找不写</b>。'}
      共 <b>${f.n_points}</b> 个${esc(what)}，你勾了 <b id="slg-n">${slPicked.size}</b> 句。
      ${(f.refs || []).length ? `<i>（本题只看给定资料 ${f.refs.join('、')}）</i>` : ''}</div>
    <div id="slg-mat-sents" class="fr-mat">${frMatHtml(f.sents, slPicked, mk)}</div>
    ${c ? frCheckBody(c) : ''}
    <div class="fr-acts">
      ${c ? '<button class="btn" id="slg-redo">' + artEm("🔄") + ' 重新找一遍</button>' : ''}
      <button class="btn primary" id="slg-check">${c ? '改完了，重新判定' : '看看我找得对不对'}</button>
      ${c ? '<button class="btn" id="slg-towrite">下一步：照着写 →</button>' : ''}
    </div>`;
  $('#slg-check').onclick = slDoCheck;
  if (c) {
    $('#slg-redo').onclick = () => { slFind.check = null; slPicked = new Set(); slRenderFind(); };
    $('#slg-towrite').onclick = () => {
      // 漏掉的点补进勾画，不然照着写注定还是漏（和小题训练一个处理）
      c.missSents.forEach(i => slPicked.add(i));
      c.wrongSents.forEach(i => slPicked.delete(i));
      $('#slg-find').classList.add('hidden');
      $('#slg-body').classList.remove('hidden');
      const picked = slFind.sents.filter(s => slPicked.has(s.i));
      $('#slg-picked').innerHTML = `<div class="fr-sec-t">${artEm('🖍')} 你勾到的（照着这些写）</div>`
        + `<div class="fr-picked">${picked.map(s => `<div>· ${esc(s.t)}</div>`).join('')
          || '<i>你没勾到任何要点</i>'}</div>`;
      $('#slg-picked').classList.remove('hidden');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    };
  }
}

// 勾画：点一句=选中/取消，按住拖过多句=连选（和小题训练同一套手势）
$('#slg-find').addEventListener('pointerdown', e => {
  const s = e.target.closest('[data-fs]'); if (!s) return;
  const i = +s.dataset.fs;
  slDrag = slPicked.has(i) ? 'off' : 'on';
  slToggle(i, slDrag === 'on');
  e.preventDefault();
});
$('#slg-find').addEventListener('pointerover', e => {
  if (!slDrag) return;
  const s = e.target.closest('[data-fs]'); if (!s) return;
  slToggle(+s.dataset.fs, slDrag === 'on');
});
document.addEventListener('pointerup', () => { slDrag = null; });
function slToggle(i, on) {
  if (on) slPicked.add(i); else slPicked.delete(i);
  const el = $('#slg-find').querySelector(`[data-fs="${i}"]`);
  if (el) el.classList.toggle('on', on);
  const n = $('#slg-n'); if (n) n.textContent = slPicked.size;
}
// 点「就在这句」跳到原文
$('#slg-find').addEventListener('click', e => {
  const g = e.target.closest('[data-fsgo]'); if (!g) return;
  const el = $('#slg-find').querySelector(`[data-fs="${g.dataset.fsgo}"]`);
  if (el) {
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1400);
  }
});

async function slDoCheck() {
  if (!slPicked.size) { toast('先在材料里勾几句', true); return; }
  const b = $('#slg-check'); const old = b.textContent;
  b.disabled = true; b.textContent = '判定中…';
  try {
    const r = await api(`/api/shenlun/question/${slQuestion.id}/check`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sents: [...slPicked] }),
    });
    r.okSents = new Set(r.ok.flatMap(x => x.sents));
    r.wrongSents = new Set(r.wrong.map(x => x.i));
    r.missSents = new Set(r.missed.flatMap(x => x.sents));
    r.nearSents = new Set((r.near || []).map(x => x.i));
    slFind.check = r;
    slRenderFind();
  } catch (e) { toast(errMsg(e), true); b.disabled = false; b.textContent = old; }
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
  } catch (e) { toast(errMsg(e), true); }
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
    } catch (e) { toast(errMsg(e), true); }
  };
}

async function openSlRecord(rid) {
  try {
    const d = await api('/api/shenlun/record/' + rid);
    renderSlResult(d.result);
  } catch (e) { toast(errMsg(e), true); }
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
      ${(p.hits || []).map(h => `<div class="slp-li hit">${artEm('✓')} ${esc(h)}</div>`).join('')}
      ${(p.partial || []).map(h => `<div class="slp-li part">— ${esc(h)}</div>`).join('')}
      ${(p.misses || []).map(h => `<div class="slp-li miss">${artEm('✕')} ${esc(h)}</div>`).join('')}
      ${p.material ? `<div class="slp-mat"><b>对照材料${
        // 句号只有「按预标采分点评分」时才有 —— 现场提炼那条老路给不出原文位置。
        // 句号是相对「给定资料N」那一则的，所以得把是哪一则一并标出来，否则对不上整份材料。
        (p.sents || []).length
          ? `（${(r.std_refs || []).length ? '给定资料' + r.std_refs.join('、') + ' ' : ''}第 ${p.sents.join('、')} 句）`
          : ''}：</b>${esc(p.material)}</div>` : ''}
    </div>`;
  }).join('')
    // 采分点是预先标好的：同一份答案再批一次分数不会飘，值得让用户看见
    + (r.std_points ? `<div class="slr-wtag">${artEm('📌')} 本题按<b>预标采分点</b>评分：标尺固定、结果可复现，"对照材料"是逐字锚定到原句的</div>` : '')
    + ((r.advice || []).length ? `<div class="slr-advice"><div class="slt-sec">改进建议</div><ul>`
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
       ${r.id ? `<button class="btn primary" id="slr-regen" data-rid="${r.id}">${artEm('🔄')} 重新生成参考范文</button>` : ''}`;

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
// 选择器必须锁在 #view-slresult 内：范文详情页的 #esd-tabs 也顶着 .slr-tabs（为了蹭样式），
// 且在 DOM 里排在前面。用裸的 .slr-tabs 会选到它——事件绑错元素，本页四个页签一点没反应。
function slrTab(t) {
  document.querySelectorAll('#view-slresult .slr-tabs .tk-tab')
    .forEach(x => x.classList.toggle('active', x.dataset.slrt === t));
  ['points', 'ref', 'orig', 'mine'].forEach(k => $('#slr-' + k).classList.toggle('hidden', k !== t));
}
document.querySelector('#view-slresult .slr-tabs').addEventListener('click', e => {
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
    toast(errMsg(err), true);
    b.disabled = false; b.textContent = '🔄 重新生成参考范文';
  }
});
