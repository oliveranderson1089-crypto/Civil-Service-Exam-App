/* 小题训练：找点 + 写点
 *
 * 由 app.js 按它自己的区段边界切出（原 L4270-4606）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, appConfirm, back, c, esc, push,
   toast */

/* ============= 小题训练：找点 + 写点 =============
   归纳概括 / 综合分析 / 提出对策，难点是同一个：从材料里把要点找出来。
   所以拆成两步，每步单独纠错：
     第一步「找点」—— 只勾画不写字，判**找漏 / 找错 / 找重**
     第二步「写点」—— 照着勾到的地方写，判**概括到不到位**
   勾画粒度是**句**：申论找点本来就是找句子，句子边界明确才判得准
   （自由划词的区间对不齐采分点，判定必然变成玄学）。 */
let fdPaper = null, fdPicked = new Set(), fdStep = 1, fdCheck = null, fdDrag = null;
let fdManage = false, fdSel = new Set();   // 我的题：批量删除的管理态
// 步骤要能回退，回退就得有东西可回 —— 答案和批改结果必须挂在模块上活着：
// frFoot() 每次重渲染都会把 <textarea> 重建，答案不存在这儿，一回上一步就白写了。
// fdMaxStep = 走到过的最远一步，只有走到过的步骤才让点回去（没做过的步骤点了没意义）。
let fdAnswer = '', fdGrade = null, fdMaxStep = 1, fdTab = 'grade';

function openFind() {
  fdManage = false; fdSel.clear();
  push({ view: 'find', title: '小题训练' });
  loadFindTypes();
  loadFindRealStat();
  loadFindList();
}
let fdDoctypes = [];
async function loadFindTypes() {
  try {
    const d = await api('/api/find/types');
    fdDoctypes = d.doctypes || [];
    $('#fd-types').innerHTML = d.types.map((t, i) => `
      <div class="fd-type${i === 0 ? ' on' : ''}" data-fdt="${t.key}">
        <div class="fd-type-h"><b>${esc(t.name)}</b><span>${t.full} 分 · ${t.word_min}~${t.word_max} 字</span></div>
        <p>${esc(t.tip)}</p>
        <div class="fd-type-n">${t.n ? '练过 ' + t.n + ' 道' : '还没练过'}</div>
      </div>`).join('');
    // 贯彻执行的文种选择条：🎲 随机 + 各文种（点选后按该文种的真题字数出题）
    $('#fd-doctypes').innerHTML = '<span class="gw-sug-t">文种：</span>'
      + '<button class="chip tiny on" data-fdd="">🎲 随机</button>'
      + fdDoctypes.map(x => `<button class="chip tiny" data-fdd="${esc(x.k)}" title="${x.min}~${x.max} 字">${esc(x.k)}</button>`).join('');
    fdSyncDoctypes();
  } catch (e) { $('#fd-types').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
function fdSyncDoctypes() {   // 只有选中「贯彻执行」时才显示文种选择条
  $('#fd-doctypes').classList.toggle('hidden', fdType() !== 'guanche');
  fdSyncSrc();
}

// 真题题源的存量，进页面时取一次
let fdRealStat = null;
async function loadFindRealStat() {
  try {
    fdRealStat = await api('/api/find/realstat');
    const box = $('#fd-realopt');
    // 卷种按钮按库里实际有的卷种生成，不写死
    box.querySelectorAll('[data-fdexam]:not([data-fdexam=""])').forEach(x => x.remove());
    (fdRealStat.exams || []).forEach(x => {
      const b = document.createElement('button');
      b.className = 'chip tiny'; b.dataset.fdexam = x; b.textContent = x;
      box.appendChild(b);
    });
    // 上次选的卷种刚被上面删掉的话，选中态会整排落空 —— 回落到「不限」，
    // 别让界面停在「三排都没高亮」的样子（那正是看着像按钮失灵的场面）。
    if (!box.querySelector('[data-fdexam].on'))
      box.querySelector('[data-fdexam=""]')?.classList.add('on');
  } catch (_) { fdRealStat = null; }   // 取不到就当没有真题源，界面自动置灰
  fdSyncSrc();
}

// 题源提示：真题模式下要**明说这个筛法还剩几道**，不然点了才知道没题。
// 没有真题题源的题型（如写作类）直接把「真题练习」置灰，别让人以为在练真题、
// 实际退回了 AI 出题。
function fdSyncSrc() {
  const real = fdSrc() === 'real';
  $('#fd-realopt').classList.toggle('hidden', !real);
  const st = fdRealStat && fdRealStat.types && fdRealStat.types[fdType()];
  const btn = document.querySelector('#fd-src [data-fdsrc="real"]');
  const has = !!(st && st.total);
  if (btn) { btn.disabled = !has; btn.title = has ? '' : '这个题型还没有真题题源'; }
  if (!has && real) {                     // 切到没真题的题型时自动退回 AI，并说明
    document.querySelectorAll('#fd-src .chip').forEach(x =>
      x.classList.toggle('on', x.dataset.fdsrc === 'ai'));
    $('#fd-realopt').classList.add('hidden');
  }
  $('#fd-srcnote').textContent = !st ? ''
    : fdSrc() === 'real'
      // 这排是「筛条件」不是「出题按钮」，得明说下一步动作在哪，
      // 否则点了题源/卷种看不出发生什么，会以为按钮坏了。
      ? `可练 ${fdEra() === 'new' ? st.since2018 : st.total} 道 · 其中 ${st.with_ref} 道带官方参考答案`
        + ` · 选好年份/卷种后点「✍️ 出一道」抽一道原题`
      : `（这个题型另有 ${st.total} 道真题可练）`;
}
$('#fd-types').addEventListener('click', e => {
  const t = e.target.closest('[data-fdt]'); if (!t) return;
  document.querySelectorAll('#fd-types .fd-type').forEach(x => x.classList.toggle('on', x === t));
  fdSyncDoctypes();
});
$('#fd-doctypes').addEventListener('click', e => {
  const b = e.target.closest('[data-fdd]'); if (!b) return;
  document.querySelectorAll('#fd-doctypes .chip').forEach(x => x.classList.toggle('on', x === b));
});
$('#fd-src').addEventListener('click', e => {
  const b = e.target.closest('[data-fdsrc]'); if (!b || b.disabled) return;
  document.querySelectorAll('#fd-src .chip').forEach(x => x.classList.toggle('on', x === b));
  fdSyncSrc();
});
$('#fd-realopt').addEventListener('click', e => {
  const b = e.target.closest('[data-fdera],[data-fdexam]');
  if (!b) return;
  const attr = b.dataset.fdera !== undefined ? 'fdera' : 'fdexam';
  $('#fd-realopt').querySelectorAll(`[data-${attr}]`).forEach(x => x.classList.toggle('on', x === b));
  fdSyncSrc();
});
const fdSrc = () => (document.querySelector('#fd-src .chip.on') || {}).dataset?.fdsrc || 'ai';
const fdEra = () => (document.querySelector('#fd-realopt [data-fdera].on') || {}).dataset?.fdera || 'new';
const fdExam = () => (document.querySelector('#fd-realopt [data-fdexam].on') || {}).dataset?.fdexam || '';
const fdType = () => (document.querySelector('#fd-types .fd-type.on') || {}).dataset?.fdt || 'guina';
const fdDoctype = () => (document.querySelector('#fd-doctypes .chip.on') || {}).dataset?.fdd || '';

// 一张题目卡片。done=true 是「做过的题」区（显示最好成绩/最近时间，纯重练，无勾选/删除）；
// 否则是「我的题」区（可单删；管理态下带勾选做批量删）。
function fdPaperCard(x, opt = {}) {
  if (opt.done) {
    return `<div class="wr-day done" data-fdp="${x.id}">
      <div class="wr-day-d">${esc(x.type_name)}</div>
      <div class="wr-day-m"><b>${esc((x.stem || '').slice(0, 40))}</b>
        ${x.best != null ? `<span class="dr-acc${x.best >= x.full * 0.6 ? '' : ' bad'}">最好 ${x.best}/${x.full}</span>` : ''}
        <span class="fd-done">练过 ${x.done} 次</span>
        <span class="wr-w">${esc((x.last_done || '').slice(5, 16))}</span></div></div>`;
  }
  const chk = fdManage ? `<input type="checkbox" class="fd-chk" data-fdchk="${x.id}"${fdSel.has(x.id) ? ' checked' : ''}>` : '';
  return `<div class="wr-day done${fdManage ? ' fd-managing' : ''}" data-fdp="${x.id}">
    ${chk}
    <div class="wr-day-d">${esc(x.type_name)}</div>
    <div class="wr-day-m"><b>${esc((x.stem || '').slice(0, 40))}</b>
      <span class="wr-w">${x.full} 分</span>
      <span class="wr-tag">${esc(x.source || '')}</span>
      ${x.done ? `<span class="fd-done">练过 ${x.done} 次</span>` : ''}</div>
    <button class="btn danger tiny fd-del" data-fddel="${x.id}" title="删除这道题">🗑</button></div>`;
}

async function loadFindList() {
  const box = $('#fd-list');
  try {
    const d = await api('/api/find/papers');
    const items = d.items || [];
    // 做过的题：按最近练习时间倒排，一键重练（纳入复习规划）
    const done = items.filter(x => x.done > 0)
      .sort((a, b) => (b.last_done || '').localeCompare(a.last_done || ''));
    const dw = $('#fd-done-wrap'), dbox = $('#fd-done');
    if (done.length) {
      dbox.innerHTML = done.map(x => fdPaperCard(x, { done: true })).join('');
      dw.classList.remove('hidden');
    } else dw.classList.add('hidden');
    // 我的题：全部（新到旧）
    box.innerHTML = items.length ? items.map(x => fdPaperCard(x)).join('')
      : '<p class="empty">还没有题。上面点「出一道」，或上传一份真题。</p>';
    fdSyncBatchBar();
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#fd-done').addEventListener('click', e => {
  const c = e.target.closest('[data-fdp]'); if (c) openFindRun(+c.dataset.fdp);   // 一键重练
});
$('#fd-list').addEventListener('click', e => {
  const del = e.target.closest('[data-fddel]');
  if (del) { e.stopPropagation(); fdDelPaper(+del.dataset.fddel); return; }
  const card = e.target.closest('[data-fdp]'); if (!card) return;
  if (fdManage) {                                  // 管理态：点卡=勾选/取消
    const id = +card.dataset.fdp;
    if (fdSel.has(id)) fdSel.delete(id); else fdSel.add(id);
    const box = card.querySelector('.fd-chk'); if (box) box.checked = fdSel.has(id);
    fdSyncBatchBar();
    return;
  }
  openFindRun(+card.dataset.fdp);
});

/* ---- 题目删除：单删 + 批量删（管理态）---- */
async function fdDelPaper(id) {
  if (!(await appConfirm('删除这道题？它的做题记录也会一起删掉，且不可恢复。'))) return;
  try {
    await api('/api/find/paper/' + id, { method: 'DELETE' });
    fdSel.delete(id); toast('已删除'); loadFindList(); loadFindTypes();
  } catch (e) { toast(e.message, true); }
}
async function fdBatchDel() {
  if (!fdSel.size) { toast('先勾选要删的题', true); return; }
  if (!(await appConfirm(`删除选中的 ${fdSel.size} 道题？它们的做题记录也会一起删掉，且不可恢复。`))) return;
  try {
    const r = await api('/api/find/papers/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: [...fdSel] }),
    });
    toast(`已删除 ${r.deleted} 道`); fdSel.clear(); fdManage = false;
    loadFindList(); loadFindTypes();
  } catch (e) { toast(e.message, true); }
}
function fdSyncBatchBar() {
  const bar = $('#fd-batchbar');
  if (bar) bar.classList.toggle('hidden', !fdManage);
  const n = $('#fd-seln'); if (n) n.textContent = '已选 ' + fdSel.size;
  const mb = $('#fd-manage'); if (mb) mb.textContent = fdManage ? '✓ 完成' : '🗑 管理';
}
$('#fd-manage').onclick = () => { fdManage = !fdManage; if (!fdManage) fdSel.clear(); loadFindList(); };
$('#fd-batchdel').onclick = fdBatchDel;
$('#fd-gen').onclick = async () => {
  const b = $('#fd-gen'); b.disabled = true; b.textContent = '出题中…（约 3~5 分钟）';
  // 出题现在是「造材料 → 分块扫描 → 定向补点 → 合并定分 → 拼参考答案」好几步，
  // 比原来慢不少。慢的是出题这一次，练多少遍都不用再等（采分点和参考答案都存下来了）。
  $('#fd-msg').textContent = 'AI 正在按题型出一则材料（对齐真题单则字数、掺干扰信息），再逐块扫全材料标采分点、'
    + '补上漏掉的段落，最后拼一份参考答案 —— 出题只做这一次，之后练多少遍都不用再等…';
  try {
    const d = await api('/api/find/gen', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qtype: fdType(), topic: $('#fd-topic').value.trim(),
        doctype: fdDoctype(), src: fdSrc(), era: fdEra(), exam: fdExam() }),
    });
    $('#fd-msg').textContent = '';
    openFindRun(d.id); loadFindList(); loadFindTypes();
  } catch (e) { toast(e.message, true); $('#fd-msg').textContent = ''; }
  b.disabled = false; b.textContent = '✍️ 出一道';
};
$('#fd-up').onclick = () => $('#fd-file').click();
$('#fd-file').onchange = async () => {
  const f = $('#fd-file').files[0]; if (!f) return;
  // textContent 不解析标记，别在这儿写 **加粗**，会原样显示成星号
  $('#fd-msg').textContent = '正在识别真题：拆材料和小题，再逐题扫全材料标采分点、拼参考答案。'
    + '一份卷子有几道小题就要跑几轮，可能要五到十分钟，别关页面…';
  const fd = new FormData(); fd.append('file', f);
  try {
    const d = await api('/api/find/upload', { method: 'POST', body: fd });
    $('#fd-msg').textContent = '';
    toast(`识别出 ${d.made.length} 道可练的小题` + (d.skipped.length ? `（${d.skipped.join('、')} 不属于找点训练，已跳过）` : ''));
    loadFindList(); loadFindTypes();
  } catch (e) { toast(e.message, true); $('#fd-msg').textContent = ''; }
  $('#fd-file').value = '';
};

/* ---- 做题：材料按句勾画 ---- */
async function openFindRun(pid) {
  fdPaper = null; fdPicked = new Set(); fdStep = 1; fdCheck = null;
  fdAnswer = ''; fdGrade = null; fdMaxStep = 1; fdTab = 'grade';
  push({ view: 'findrun', title: '找点训练' });
  $('#fr-head').innerHTML = '<p class="empty">加载中…</p>';
  $('#fr-mat').innerHTML = ''; $('#fr-foot').innerHTML = '';
  try {
    fdPaper = await api('/api/find/paper/' + pid);
    fdAnswer = localStorage.getItem('fd-draft-' + pid) || '';   // 上次没写完的草稿
    frRender();
  } catch (e) { $('#fr-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

// 步骤条：走到过的步骤可以点回去。没有这个，第一步一交就永远回不去了 ——
// 而找点这事儿本来就要反复改：看完判定想再补两句、写着写着发现漏了个点，都得能退回去。
function frStepBar(cur, max) {
  const N = ['① 找点', '② 写点', '③ 批改'];
  return `<div class="fr-step">` + N.map((t, i) => {
    const k = i + 1, can = k <= max && k !== cur;
    return `<span class="${k === cur ? 'on' : (k <= max ? 'done' : '')}${can ? ' fr-back' : ''}"
      ${can ? `data-fstep="${k}"` : ''} title="${can ? '点这里回到这一步' : ''}">${t}</span>`;
  }).join('') + `</div>`;
}

function frRender() {
  const p = fdPaper;
  fdMaxStep = Math.max(fdMaxStep, fdStep);
  $('#fr-head').innerHTML = frStepBar(fdStep, fdMaxStep) + `
    <div class="fr-stem">${esc(p.stem)}</div>
    <div class="fr-meta">${esc(p.type_name)} · ${p.full} 分 · 答案 ${p.word_min}~${p.word_max} 字
      · <b>共 ${p.n_points} 个采分点</b>${p.material_words ? ` · 给定资料 ${p.material_words} 字` : ''} · ${esc(p.source || '')}</div>
    ${p.done ? `<div class="fr-hist"><i class="fr-histgo">🕐 本题练过 ${p.done} 次 · 查看记录 ›</i></div>` : ''}`
    + (fdStep === 3 ? frScoreHtml(fdGrade) + frTabBar() : '');
  frMat();
  frFoot();
}
// 做题页点「查看记录」→ 打开过滤到本题的做题记录（题目内部按时间的多次留痕）
$('#fr-head').addEventListener('click', e => {
  if (e.target.closest('.fr-histgo') && fdPaper) { openFindRecs(fdPaper.id); return; }
  const b = e.target.closest('[data-fstep]'); if (!b) return;
  frGoStep(+b.dataset.fstep);
});
// 在走到过的步骤之间**自由往返**。判定结果、答案、批改结果都挂在模块上活着，
// 所以来回切不丢东西也不重复花 AI 调用 —— 退回第二步看一眼再回第三步看批改，是常事。
// 第三步的批改已经落库，回去改完再交 = **新增**一条记录，不覆盖上一次。
function frGoStep(k) {
  if (k === fdStep || k > fdMaxStep) return;
  fdStep = k;
  frRender();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// 材料渲染抽成纯函数：做题页和「做题记录」详情都要按句渲染 + 按判定着色，
// 差别只是数据从哪来（一个是当前会话，一个是历史快照），渲染规则必须是同一套。
function frMatHtml(sents, picked, mk) {
  let html = '', lastP = -1;
  sents.forEach(s => {
    if (s.p !== lastP) { if (lastP >= 0) html += '</p>'; html += '<p class="fr-para">'; lastP = s.p; }
    if (s.head) { html += `<span class="fr-s fr-h">${esc(s.t)}</span>`; return; }
    const cls = ['fr-s'];
    if (picked.has(s.i)) cls.push('on');
    if (mk) {                                    // 判完了：把对/沾边/错/漏直接标在原文上
      if (mk.ok.has(s.i)) cls.push('ok');
      else if (mk.near && mk.near.has(s.i)) cls.push('near');
      else if (mk.bad.has(s.i)) cls.push('bad');
      else if (mk.miss.has(s.i)) cls.push('miss');
    }
    html += `<span class="${cls.join(' ')}" data-fs="${s.i}">${esc(s.t)}</span>`;
  });
  if (lastP >= 0) html += '</p>';
  return html;
}

function frMat() {
  // 第三步（批改）材料一样要留着 —— 原来这儿是清空的，结果拿到分数却看不到材料，
  // 没法对着原文看自己漏在哪；现在批改页把材料当成一个页签，还带着找对/错/漏的着色。
  const box = $('#fr-mat');
  box.classList.toggle('hidden', fdStep === 3 && fdTab !== 'mat');
  const mk = fdCheck ? { ok: fdCheck.okSents, bad: fdCheck.wrongSents, miss: fdCheck.missSents, near: fdCheck.nearSents } : null;
  box.innerHTML = (fdStep === 3
    ? `<div class="fr-sec-t">📄 给定资料${fdPaper.material_words ? `（${fdPaper.material_words} 字）` : ''}
       <i class="fr-legend">绿=找对 · 红=找错 · 黄=找漏 · 橙=沾边</i></div>` : '')
    + frMatHtml(fdPaper.sents, fdPicked, mk);
  frTapMark(null);      // 重渲染把 DOM 换掉了，待定的那一下跟着作废
}

// 批改结果的页签：真题批改那边就是这么摆的（维度评分/参考范文/原题材料/作答原文），
// 小题这边原来只有一块光秃秃的逐点批改，材料和参考答案都没有。
function frTabBar() {
  const T = [['grade', '逐点批改'], ['ref', '参考答案'], ['mat', '材料原文'], ['mine', '我的作答']];
  return `<div class="tk-tabs fr-tabs">` + T.map(([k, t]) =>
    `<button class="tk-tab${fdTab === k ? ' active' : ''}" data-frt="${k}">${t}</button>`).join('') + `</div>`;
}

// 勾画：点一句 = 选中/取消；按住拖过多句 = 连着选（鼠标和手写笔都走 pointer 事件）
//
// 手指是另一回事：材料是要滑着看的，手指落下就选 = 每滑一下都误勾一片。
// 所以触摸走「连点两下才算数」——第一下只把这句标成**待定**（虚线框，进不了 fdPicked），
// FD_TAP_MS 内再点同一句才真的勾上/取消；期间手指挪了位置、挪到别的句子上、
// 或者浏览器判成滚动（pointercancel），这一下就不算点。触摸也不做拖动连选：
// 拖 = 滑页面，两件事抢不到一起。鼠标/手写笔完全照旧。
const FD_TAP_MS = 600;
const fdCoarse = () => !!(window.matchMedia && matchMedia('(pointer: coarse)').matches);
const FD_TAP_SLOP = 10;                          // 手指抖这么多以内还算「点」，超了算滑
let fdTapI = null, fdTapTimer = null, fdDown = null;

// 待定态纯粹是给眼睛看的提示：只加/去 class，不动 fdPicked
function frTapMark(i) {
  clearTimeout(fdTapTimer);
  const box = $('#fr-mat');
  if (box) box.querySelectorAll('.fr-s.pre').forEach(el => el.classList.remove('pre'));
  fdTapI = i == null ? null : i;
  if (fdTapI == null) return;
  const el = box && box.querySelector(`[data-fs="${i}"]`);
  if (el) el.classList.add('pre');
  fdTapTimer = setTimeout(() => frTapMark(null), FD_TAP_MS);
}

$('#fr-mat').addEventListener('pointerdown', e => {
  if (fdStep !== 1) return;
  const s = e.target.closest('[data-fs]'); if (!s) return;
  const i = +s.dataset.fs;
  if (e.pointerType === 'touch') {
    // 不 preventDefault：页面照常滑：选不选等抬手时再算
    fdDown = { i, x: e.clientX, y: e.clientY };
    return;
  }
  fdDrag = fdPicked.has(i) ? 'off' : 'on';       // 起手是选中的 → 这一拖都是取消
  frToggle(i, fdDrag === 'on');
  e.preventDefault();
});
$('#fr-mat').addEventListener('pointerover', e => {
  if (!fdDrag || fdStep !== 1) return;
  const s = e.target.closest('[data-fs]'); if (!s) return;
  frToggle(+s.dataset.fs, fdDrag === 'on');
});
$('#fr-mat').addEventListener('pointerup', e => {
  const d = fdDown; fdDown = null;
  if (e.pointerType !== 'touch' || !d || fdStep !== 1) return;
  const s = e.target.closest('[data-fs]');
  if (!s || +s.dataset.fs !== d.i) return;                          // 抬手时已经在别的句子上 = 在滑
  if (Math.abs(e.clientX - d.x) > FD_TAP_SLOP
    || Math.abs(e.clientY - d.y) > FD_TAP_SLOP) return;             // 挪太多 = 在滑
  if (fdTapI === d.i) { frTapMark(null); frToggle(d.i, !fdPicked.has(d.i)); }  // 第二下：真勾/真取消
  else frTapMark(d.i);                                              // 第一下：只待定
});
document.addEventListener('pointercancel', () => { fdDown = null; });   // 滚动接管了这一指
document.addEventListener('pointerup', () => { fdDrag = null; });
function frToggle(i, on) {
  if (on) fdPicked.add(i); else fdPicked.delete(i);
  const el = document.querySelector(`[data-fs="${i}"]`);
  if (el) el.classList.toggle('on', on);
  const n = $('#fr-n'); if (n) n.textContent = fdPicked.size;
}

function frFoot() {
  const p = fdPaper;
  if (fdStep === 1) {
    // 判定过就把结果一并摆回来（回退到这一步时不该只剩个光秃秃的按钮）
    // 手机上的手势和电脑不是一套，提示语也得跟着换（fdCoarse 认的是「粗指针」= 手指）
    $('#fr-foot').innerHTML = `
      <div class="fr-tip">🖍 在材料里${fdCoarse()
        ? '<b>连点两下</b>句子勾出你认为的要点（点一下只是待定，再点一下才算勾上，滑动不会误勾）'
        : '<b>点句子</b>勾出你认为的要点（按住拖可以连选）'}。
        这一步<b>只找不写</b> —— 共 ${p.n_points} 个采分点，你勾了 <b id="fr-n">${fdPicked.size}</b> 句。</div>`
      + (fdCheck ? frCheckBody(fdCheck) : '')
      + `<div class="fr-acts">
        ${fdCheck ? '<button class="btn" id="fr-redo">🔄 全部清空重找</button>' : ''}
        <button class="btn primary" id="fr-check">${fdCheck ? '改完了，重新判定' : '看看我找得对不对'}</button>
        ${fdCheck ? '<button class="btn" id="fr-next">下一步：照着写点子 →</button>' : ''}
      </div>`;
    $('#fr-check').onclick = frDoCheck;
    if (fdCheck) {
      $('#fr-redo').onclick = () => { fdCheck = null; fdPicked = new Set(); frMat(); frFoot(); };
      $('#fr-next').onclick = frToStep2;
    }
    return;
  }
  if (fdStep === 2) {
    const picked = fdPaper.sents.filter(s => fdPicked.has(s.i));
    const gc = p.doctype;   // 贯彻执行：提示按文种格式成文
    $('#fr-foot').innerHTML = `
      <div class="fr-tip">✍️ 照着<b>你勾到的（绿色）</b>写要点。${gc
        ? `这是<b>贯彻执行题</b>，要按<b>${esc(p.doctype)}</b>的格式成文（要点全 + 格式对 + 语言得体）。`
        : `要<b>概括</b>，不是抄原文；<b>分条写</b>。`}
        ${p.word_min}~${p.word_max} 字。</div>
      ${gc && p.doctype_fmt ? `<div class="fr-fmt-tip">📋 <b>${esc(p.doctype)}</b>格式骨架：${esc(p.doctype_fmt)}</div>` : ''}
      <div class="fr-picked">${picked.map(s => `<div>· ${esc(s.t)}</div>`).join('') || '<i>你没勾到任何要点</i>'}</div>
      <textarea id="fr-ans" placeholder="一、…\n二、…\n三、…"></textarea>
      <div class="fr-wc">
        <button type="button" class="hw-open-btn" data-hw="fr-ans">✍️ 手写输入</button>
        <span><span id="fr-wc">0</span> / ${p.word_max} 字</span>
      </div>
      <div class="fr-acts">
        <button class="btn" id="fr-prev">← 回上一步改勾画</button>
        <button class="btn primary" id="fr-grade">交给我批</button>
      </div>`;
    const ta = $('#fr-ans');
    ta.value = fdAnswer;                                  // 回退/重渲染后把写过的答案接着放回去
    $('#fr-wc').textContent = fdAnswer.replace(/\s/g, '').length;
    ta.oninput = () => {
      fdAnswer = ta.value;
      $('#fr-wc').textContent = fdAnswer.replace(/\s/g, '').length;
      // 草稿存本地：批改要 20 秒，中途手滑退出/刷新不该把整篇作答赔进去
      try { localStorage.setItem('fd-draft-' + fdPaper.id, fdAnswer); } catch (_) { /* 配额满就算了 */ }
    };
    $('#fr-prev').onclick = () => frGoStep(1);
    $('#fr-grade').onclick = frDoGrade;
    return;
  }
  if (fdStep === 3) {
    $('#fr-foot').innerHTML = frStep3Pane() + `
      <div class="fr-acts">
        <button class="btn" id="fr-prev3">← 回去改答案</button>
        <button class="btn primary" id="fr-again">🔄 再练这道</button>
        <button class="btn" id="fr-back">换一道</button>
      </div>`;
    // 回去改答案再交 = **新增**一条记录，不覆盖这次的（做题记录里两次都在，能比进步）
    $('#fr-prev3').onclick = () => frGoStep(2);
    $('#fr-again').onclick = () => openFindRun(fdPaper.id);
    $('#fr-back').onclick = () => { back(); loadFindList(); };
  }
}

// 找点判定的结果块。抽出来是因为回退到第一步时要能把它原样摆回来（见 frFoot）
function frCheckBody(r) {
  return `<div class="fr-res">
      <div class="fr-score">找到 <b>${r.found}</b> / ${r.total} 个采分点
        <span class="fr-acc${r.acc < 60 ? ' bad' : ''}">${r.acc}%</span></div>
      ${r.missed.length ? `<div class="fr-sec miss"><div class="fr-sec-t">❌ 找漏了 ${r.missed.length} 个</div>
        ${r.missed.map(x => `<div class="fr-item">
          <b>${x.score ? `[${x.score} 分] ` : ""}${esc(x.point)}</b>
          <div class="fr-ev" data-fsgo="${x.sents[0]}">↗ 就在这句：${esc(x.evidence.slice(0, 50))}…</div>
        </div>`).join('')}</div>` : ''}
      ${r.wrong.length ? `<div class="fr-sec bad"><div class="fr-sec-t">⚠️ 找错了 ${r.wrong.length} 处
          <i>（这些是干扰信息，不是采分点）</i></div>
        ${r.wrong.map(x => `<div class="fr-item"><div class="fr-ev" data-fsgo="${x.i}">↗ ${esc(x.t.slice(0, 50))}…</div></div>`).join('')}</div>` : ''}
      ${(r.near || []).length ? `<div class="fr-sec near"><div class="fr-sec-t">🟡 沾边 ${r.near.length} 处
          <i>（这几句确实相关，只是没能独立成一个采分点 —— 不算找错）</i></div>
        ${r.near.map(x => `<div class="fr-item"><div class="fr-ev" data-fsgo="${x.i}">↗ ${esc(x.t.slice(0, 50))}…</div></div>`).join('')}</div>` : ''}
      ${r.dup.length ? `<div class="fr-sec dup"><div class="fr-sec-t">🔁 找重了 ${r.dup.length} 处</div>
        ${r.dup.map(x => `<div class="fr-item"><b>${esc(x.point)}</b>
          <div class="fr-ev">这一个点你勾了 ${x.sents.length} 句 —— 材料里换了个说法而已，答案里只算一个点</div>
        </div>`).join('')}</div>` : ''}
      ${r.ok.length ? `<div class="fr-sec ok"><div class="fr-sec-t">✅ 找对了 ${r.ok.length} 个</div>
        ${r.ok.map(x => `<div class="fr-item"><b>${x.score ? `[${x.score} 分] ` : ""}${esc(x.point)}</b></div>`).join('')}</div>` : ''}
    </div>`;
}
function frToStep2() {
  // 漏掉的点也补进勾画（不然第二步照着写，注定还是漏）—— 但它们在原文里仍标成黄的
  fdCheck.missSents.forEach(i => fdPicked.add(i));
  fdCheck.wrongSents.forEach(i => fdPicked.delete(i));
  fdStep = 2; frRender();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function frDoCheck() {
  if (!fdPicked.size) { toast('先在材料里勾几句', true); return; }
  const b = $('#fr-check'); const old = b.textContent;
  b.disabled = true; b.textContent = '判定中…';
  try {
    const r = await api('/api/find/check', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paper_id: fdPaper.id, sents: [...fdPicked] }),
    });
    // 把判定结果落到句子上：找对=绿，找错=红，找漏=黄（漏的句子考生本来没勾，这里直接点出来）
    r.okSents = new Set(r.ok.flatMap(x => x.sents));
    r.wrongSents = new Set(r.wrong.map(x => x.i));
    r.missSents = new Set(r.missed.flatMap(x => x.sents));
    r.nearSents = new Set((r.near || []).map(x => x.i));   // 沾边：相关但没独立成点
    fdCheck = r;
    frMat();
    frFoot();
  } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = old; }
}
$('#fr-foot').addEventListener('click', e => {
  const g = e.target.closest('[data-fsgo]');    // 点一下跳到原文那句
  if (!g) return;
  // 第三步材料是折在「材料原文」页签里的，不先切过去，滚过去也是滚到个隐藏元素上
  if (fdStep === 3 && fdTab !== 'mat') { fdTab = 'mat'; frRender(); }
  const el = $('#fr-mat').querySelector(`[data-fs="${g.dataset.fsgo}"]`);
  if (el) {
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    el.classList.add('flash');
    setTimeout(() => el.classList.remove('flash'), 1400);
  }
});

async function frDoGrade() {
  const ans = $('#fr-ans').value.trim();
  if (ans.replace(/\s/g, '').length < 20) { toast('写太少了', true); return; }
  const b = $('#fr-grade'); b.disabled = true; b.textContent = '批改中…（约 20 秒）';
  try {
    const g = await api('/api/find/grade', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        paper_id: fdPaper.id, answer: ans, sents: [...fdPicked],
        // 把这次的找点判定一起存下（记录详情里回看「我的找点过程」）
        find_result: fdCheck ? {
          found: fdCheck.found, total: fdCheck.total, acc: fdCheck.acc,
          missed: (fdCheck.missed || []).map(m => m.point),
          wrong_n: (fdCheck.wrong || []).length, dup_n: (fdCheck.dup || []).length,
        } : null,
      }),
    });
    fdAnswer = ans; fdGrade = g; fdStep = 3; fdTab = 'grade';
    try { localStorage.removeItem('fd-draft-' + fdPaper.id); } catch (_) { /* 交了就不留草稿 */ }
    frRender();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = '交给我批'; }
}

// 第三步的页签内容。材料不在这儿 —— 它单独占着 #fr-mat（切到「材料原文」时才显示）。
function frStep3Pane() {
  const g = fdGrade || {};
  if (fdTab === 'mat') return '';
  if (fdTab === 'ref') {
    return g.reference
      ? `<div class="fr-sec"><div class="fr-sec-t">📖 参考答案<i class="fr-legend">${g.ref_words || ''} 字 · 由本题采分点拼装，要点与判分标准一一对应</i></div>
         <div class="frd-ans">${esc(g.reference).replace(/\n/g, '<br>')}</div></div>`
      : `<div class="fr-sec"><div class="fr-sec-t">📖 参考答案</div>
         <p class="empty">这道题还没生成参考答案（生成是出题之外单独的一次 AI 调用，超时/失败就会空着）。</p>
         <button class="btn primary" id="fr-refgen">🔄 生成参考答案</button></div>`;
  }
  if (fdTab === 'mine') {
    const n = (fdAnswer || '').replace(/\s/g, '').length;
    return `<div class="fr-sec"><div class="fr-sec-t">✍️ 我的作答<i class="fr-legend">${n} 字 · 要求 ${fdPaper.word_min}~${fdPaper.word_max} 字</i></div>
      <div class="frd-ans">${esc(fdAnswer).replace(/\n/g, '<br>')}</div></div>`;
  }
  return frFindRecapHtml(fdCheck && {
    found: fdCheck.found, total: fdCheck.total, acc: fdCheck.acc,
    missed: (fdCheck.missed || []).map(m => m.point),
    wrong_n: (fdCheck.wrong || []).length, dup_n: (fdCheck.dup || []).length,
  }) + frResultBody(g);
}
// 页签切换 + 参考答案补生成（都挂在 #fr-head / #fr-foot 上，内容重渲染也不掉）
$('#fr-head').addEventListener('click', e => {
  const t = e.target.closest('[data-frt]'); if (!t || fdStep !== 3) return;
  fdTab = t.dataset.frt; frRender();
});
$('#fr-foot').addEventListener('click', async e => {
  const b = e.target.closest('#fr-refgen'); if (!b) return;
  b.disabled = true; b.textContent = '生成中…（约 30 秒）';
  try {
    const d = await api(`/api/find/paper/${fdPaper.id}/reference`, { method: 'POST' });
    fdGrade.reference = d.reference; fdGrade.ref_words = d.ref_words;
    frRender(); toast(`参考答案已生成（${d.ref_words} 字）`);
  } catch (err) { toast(err.message, true); b.disabled = false; b.textContent = '🔄 生成参考答案'; }
});
// 批改结果的两块 HTML，做题页和「做题记录」详情共用
function frScoreHtml(g) {
  return `<div class="fr-final"><b>${g.score}</b> / ${g.full} 分${g.content_score != null && g.format
    ? `<span class="fr-brk">内容 ${g.content_score}/${g.content_full} + 格式 ${g.format.score}/${g.format.full}</span>` : ''}</div>`;
}
function frResultBody(g) {
  const M = { full: ['✅', 'ok'], part: ['⚠️', 'part'], miss: ['❌', 'miss'] };
  return `<div class="fr-res">
      <div class="fr-sec-t">逐个采分点</div>
      ${(g.items || []).map(it => {
        const m = M[it.got] || M.miss;
        return `<div class="fr-item fr-g ${m[1]}">
          <b>${m[0]} [${it.score} 分] ${esc(it.point || '')}</b>
          <div class="fr-gc">${esc(it.comment || '')}</div></div>`;
      }).join('')}
      ${g.format ? `<div class="fr-sec fr-fmt"><div class="fr-sec-t">📋 格式（${esc(g.format.doctype || '')}）${g.format.grade ? ` · ${esc(g.format.grade)}` : ''}${g.format.full ? ` · ${g.format.score}/${g.format.full} 分` : ''}</div>
        ${(g.format.ok || []).length ? `<div class="fr-item">✅ 到位：${g.format.ok.map(esc).join('、')}</div>` : ''}
        ${(g.format.miss || []).length ? `<div class="fr-item">❌ 欠缺：${g.format.miss.map(esc).join('、')}</div>` : ''}
        ${g.format.comment ? `<div class="fr-gc">${esc(g.format.comment)}</div>` : ''}</div>` : ''}
      ${(g.style || []).length ? `<div class="fr-sec bad"><div class="fr-sec-t">表述问题</div>
        ${g.style.map(s => `<div class="fr-item">· ${esc(s)}</div>`).join('')}</div>` : ''}
      ${g.advice ? `<div class="fr-adv">💡 ${esc(g.advice)}</div>` : ''}
    </div>`;
}

/* ---- 找点/写点 记录：每次批改都留一条（含找点过程），可回看、可删。
       做题记录（全局/本题按时间）与错题记录（没满分、按时间）共用一套卡片。 ---- */
// 一条记录卡片。wrong=true 时多显示「漏 N 点」。每条带删除按钮。
function frRecCard(x, opt = {}) {
  return `<div class="wr-day done" data-frrec="${x.id}">
    <div class="wr-day-d">${esc(x.type_name)}${x.doctype ? ' · ' + esc(x.doctype) : ''}</div>
    <div class="wr-day-m"><b>${esc(x.stem || '')}</b>
      <span class="dr-acc${x.score >= x.full * 0.6 ? '' : ' bad'}">${x.score}/${x.full} 分</span>
      ${opt.wrong && x.miss_n ? `<span class="dr-acc bad">漏 ${x.miss_n} 点</span>` : ''}
      ${x.content_score != null ? `<span class="wr-tag">内容 ${x.content_score}/${x.content_full} + 格式 ${x.format_score}/${x.format_full}</span>` : ''}
      <span class="wr-w">${esc((x.created_at || '').slice(5, 16))}</span></div>
    <button class="btn danger tiny fr-recdel" data-frdel="${x.id}" title="删除这条记录">🗑</button></div>`;
}
// 删一条记录：直接把卡片从当前列表移除，不重拉/不改题目本身
async function frDelRec(rid) {
  if (!(await appConfirm('删除这条做题记录？'))) return;
  try {
    await api('/api/find/record/' + rid, { method: 'DELETE' });
    const card = document.querySelector(`[data-frrec="${rid}"]`);
    if (card) card.remove();
    toast('已删除');
  } catch (e) { toast(e.message, true); }
}
function frRecListClick(e) {
  const del = e.target.closest('[data-frdel]');
  if (del) { e.stopPropagation(); frDelRec(+del.dataset.frdel); return; }
  const c = e.target.closest('[data-frrec]'); if (c) openFindRec(+c.dataset.frrec);
}

// 做题记录：不传 paperId=全局；传了=只看这道题（题目内部按时间的多次留痕）
$('#fd-recs').onclick = () => openFindRecs();
async function openFindRecs(paperId) {
  push({ view: 'findrec', title: paperId ? '本题记录' : '做题记录' });
  const box = $('#frr-list');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/find/records' + (paperId ? '?paper_id=' + paperId : ''));
    box.innerHTML = d.items.length ? d.items.map(x => frRecCard(x)).join('')
      : '<p class="empty">还没练过题。做完一道就会留在这里。</p>';
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#frr-list').addEventListener('click', frRecListClick);

// 错题记录：没拿满分的作答，按时间倒序，方便按做题顺序复习
$('#fd-wrong').onclick = () => openFindWrong();
async function openFindWrong() {
  push({ view: 'findwrong', title: '错题记录' });
  const box = $('#fdw-list');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/find/records?wrong=1');
    box.innerHTML = d.items.length ? d.items.map(x => frRecCard(x, { wrong: true })).join('')
      : '<p class="empty">还没有错题。没拿满分的作答会按时间留在这里，方便按顺序复习。</p>';
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#fdw-list').addEventListener('click', frRecListClick);

// 「我的找点过程」回看：找到几/漏几/错几/重几（有存 find_result 的记录才显示）
function frFindRecapHtml(fr) {
  if (!fr || fr.total == null) return '';
  const acc = fr.acc != null ? fr.acc : (fr.total ? Math.round(100 * fr.found / fr.total) : 0);
  const bits = [];
  if ((fr.missed || []).length) bits.push('找漏 ' + fr.missed.length);
  if (fr.wrong_n) bits.push('找错 ' + fr.wrong_n);
  if (fr.dup_n) bits.push('找重 ' + fr.dup_n);
  return `<div class="fr-sec fr-recap"><div class="fr-sec-t">🖍 我的找点过程</div>
    <div class="fr-item">找到 <b>${fr.found}</b> / ${fr.total} 个采分点
      <span class="fr-acc${acc < 60 ? ' bad' : ''}">${acc}%</span>${bits.length ? ' · ' + bits.join(' · ') : ''}</div>
    ${(fr.missed || []).length ? `<div class="fr-item">当时漏掉：${fr.missed.map(esc).join('；')}</div>` : ''}
  </div>`;
}
/* 一条记录的完整回看：不只是「分数 + 评语」，而是把当时那一遍**重演**出来 ——
   材料上还留着当时的勾画和判定着色（绿=找对/红=找错/黄=找漏/橙=沾边），照着能看出
   「我当时为什么会漏这个点」。着色用记录里的采分点快照算，采分点后来被重标也不影响。 */
let fdRec = null, fdRecTab = 'find';
async function openFindRec(rid) {
  push({ view: 'findrecd', title: '这次的批改' });
  $('#frd-head').innerHTML = '<p class="empty">加载中…</p>';
  $('#frd-mat').innerHTML = ''; $('#frd-body').innerHTML = '';
  try {
    fdRec = await api('/api/find/record/' + rid);
    fdRecTab = 'find';
    frRecRender();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) { $('#frd-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

function frRecRender() {
  const d = fdRec, g = d.grade || {};
  g.score = d.score; g.full = d.full;
  const T = [['find', '我的找点'], ['grade', '逐点批改'], ['ref', '参考答案'],
             ['mat', '材料原文'], ['mine', '我的作答']];
  $('#frd-head').innerHTML = `<div class="fr-stem">${esc(d.stem)}</div>
    <div class="fr-meta">${esc(d.type_name)} · ${d.full} 分 · 答案 ${d.word_min}~${d.word_max} 字
      · ${esc((d.created_at || '').slice(0, 16))}${d.snap ? '' : ' · <i>采分点已重标，着色按最新标准</i>'}</div>`
    + frScoreHtml(g)
    + `<div class="tk-tabs fr-tabs">` + T.map(([k, t]) =>
      `<button class="tk-tab${fdRecTab === k ? ' active' : ''}" data-frdt="${k}">${t}</button>`).join('') + `</div>`;

  // 材料页签：整份材料 + 当时的勾画/判定着色。「我的找点」页签也把它摆出来（要对着看）
  const showMat = fdRecTab === 'mat' || fdRecTab === 'find';
  $('#frd-mat').classList.toggle('hidden', !showMat);
  $('#frd-mat').innerHTML = showMat
    ? `<div class="fr-sec-t">📄 给定资料${d.material_words ? `（${d.material_words} 字）` : ''}
       <i class="fr-legend">绿=找对 · 红=找错 · 黄=找漏 · 橙=沾边</i></div>`
      + frMatHtml(d.sents, new Set(d.marks), {
        ok: new Set(d.mark_ok), bad: new Set(d.mark_bad), miss: new Set(d.mark_miss) })
    : '';

  let body = '';
  if (fdRecTab === 'find') {
    body = frFindRecapHtml(d.find_result)
      + `<div class="fr-sec"><div class="fr-sec-t">这道题的全部采分点（${d.points.length} 个）</div>`
      + d.points.map(p => {
        const got = (p.sents || []).some(i => d.mark_ok.includes(i));
        return `<div class="fr-item fr-g ${got ? 'ok' : 'miss'}">
          <b>${got ? '✅' : '❌'} [${p.score} 分] ${esc(p.point || '')}</b>
          ${(p.sents || []).length ? `<div class="fr-ev" data-fsgo="${p.sents[0]}">↗ 原文在第 ${p.sents.join('、')} 句</div>` : ''}
        </div>`;
      }).join('') + `</div>`;
  } else if (fdRecTab === 'grade') {
    body = frResultBody(g);
  } else if (fdRecTab === 'ref') {
    body = d.reference
      ? `<div class="fr-sec"><div class="fr-sec-t">📖 参考答案<i class="fr-legend">${d.ref_words} 字 · 由本题采分点拼装</i></div>
         <div class="frd-ans">${esc(d.reference).replace(/\n/g, '<br>')}</div></div>`
      : `<div class="fr-sec"><div class="fr-sec-t">📖 参考答案</div>
         <p class="empty">这道题还没生成参考答案。</p>
         <button class="btn primary" id="frd-refgen">🔄 生成参考答案</button></div>`;
  } else if (fdRecTab === 'mine') {
    body = `<div class="fr-sec"><div class="fr-sec-t">✍️ 我写的答案<i class="fr-legend">${(d.answer || '').replace(/\s/g, '').length} 字</i></div>
      <div class="frd-ans">${esc(d.answer).replace(/\n/g, '<br>')}</div></div>`;
  }
  $('#frd-body').innerHTML = body
    + `<div class="fr-acts"><button class="btn primary" id="frd-again">🔄 再练这道</button>
       <button class="btn" id="frd-back">返回记录</button></div>`;
  $('#frd-again').onclick = () => openFindRun(d.paper_id);
  $('#frd-back').onclick = () => back();
}
$('#frd-head').addEventListener('click', e => {
  const t = e.target.closest('[data-frdt]'); if (!t) return;
  fdRecTab = t.dataset.frdt; frRecRender();
});
$('#frd-body').addEventListener('click', async e => {
  const g = e.target.closest('[data-fsgo]');       // 点采分点 → 跳到材料里那一句
  if (g) {
    const el = $('#frd-mat').querySelector(`[data-fs="${g.dataset.fsgo}"]`);
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1400);
    }
    return;
  }
  const b = e.target.closest('#frd-refgen'); if (!b) return;
  b.disabled = true; b.textContent = '生成中…（约 30 秒）';
  try {
    const d = await api(`/api/find/paper/${fdRec.paper_id}/reference`, { method: 'POST' });
    fdRec.reference = d.reference; fdRec.ref_words = d.ref_words;
    frRecRender(); toast(`参考答案已生成（${d.ref_words} 字）`);
  } catch (err) { toast(err.message, true); b.disabled = false; b.textContent = '🔄 生成参考答案'; }
});
