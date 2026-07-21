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

function openFind() {
  fdManage = false; fdSel.clear();
  push({ view: 'find', title: '小题训练' });
  loadFindTypes();
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
  const b = $('#fd-gen'); b.disabled = true; b.textContent = '出题中…（约 1~2 分钟）';
  $('#fd-msg').textContent = 'AI 正在按题型出一则材料（对齐真题单则字数 1400~2500 字、掺干扰信息），字数不够会自动扩写，再标采分点…';
  try {
    const d = await api('/api/find/gen', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qtype: fdType(), topic: $('#fd-topic').value.trim(), doctype: fdDoctype() }),
    });
    $('#fd-msg').textContent = '';
    openFindRun(d.id); loadFindList(); loadFindTypes();
  } catch (e) { toast(e.message, true); $('#fd-msg').textContent = ''; }
  b.disabled = false; b.textContent = '✍️ 出一道';
};
$('#fd-up').onclick = () => $('#fd-file').click();
$('#fd-file').onchange = async () => {
  const f = $('#fd-file').files[0]; if (!f) return;
  $('#fd-msg').textContent = '正在识别真题（拆材料和小题，再逐题标采分点，可能要一两分钟）…';
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
  push({ view: 'findrun', title: '找点训练' });
  $('#fr-head').innerHTML = '<p class="empty">加载中…</p>';
  $('#fr-mat').innerHTML = ''; $('#fr-foot').innerHTML = '';
  try {
    fdPaper = await api('/api/find/paper/' + pid);
    frRender();
  } catch (e) { $('#fr-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

function frRender() {
  const p = fdPaper;
  $('#fr-head').innerHTML = `
    <div class="fr-step">
      <span class="${fdStep === 1 ? 'on' : 'done'}">① 找点</span>
      <span class="${fdStep === 2 ? 'on' : (fdStep > 2 ? 'done' : '')}">② 写点</span>
      <span class="${fdStep === 3 ? 'on' : ''}">③ 批改</span>
    </div>
    <div class="fr-stem">${esc(p.stem)}</div>
    <div class="fr-meta">${esc(p.type_name)} · ${p.full} 分 · 答案 ${p.word_min}~${p.word_max} 字
      · <b>共 ${p.n_points} 个采分点</b>${p.material_words ? ` · 给定资料 ${p.material_words} 字` : ''} · ${esc(p.source || '')}</div>
    ${p.done ? `<div class="fr-hist"><i class="fr-histgo">🕐 本题练过 ${p.done} 次 · 查看记录 ›</i></div>` : ''}`;
  frMat();
  frFoot();
}
// 做题页点「查看记录」→ 打开过滤到本题的做题记录（题目内部按时间的多次留痕）
$('#fr-head').addEventListener('click', e => {
  if (e.target.closest('.fr-histgo') && fdPaper) openFindRecs(fdPaper.id);
});

function frMat() {
  const p = fdPaper;
  let html = '', lastP = -1;
  p.sents.forEach(s => {
    if (s.p !== lastP) { if (lastP >= 0) html += '</p>'; html += '<p class="fr-para">'; lastP = s.p; }
    if (s.head) { html += `<span class="fr-s fr-h">${esc(s.t)}</span>`; return; }
    const cls = ['fr-s'];
    if (fdPicked.has(s.i)) cls.push('on');
    if (fdCheck) {                               // 判完了：把对/错/漏直接标在原文上
      if (fdCheck.okSents.has(s.i)) cls.push('ok');
      else if (fdCheck.wrongSents.has(s.i)) cls.push('bad');
      else if (fdCheck.missSents.has(s.i)) cls.push('miss');
    }
    html += `<span class="${cls.join(' ')}" data-fs="${s.i}">${esc(s.t)}</span>`;
  });
  if (lastP >= 0) html += '</p>';
  $('#fr-mat').innerHTML = html;
}

// 勾画：点一句 = 选中/取消；按住拖过多句 = 连着选（鼠标和手写笔都走 pointer 事件）
$('#fr-mat').addEventListener('pointerdown', e => {
  if (fdStep !== 1) return;
  const s = e.target.closest('[data-fs]'); if (!s) return;
  const i = +s.dataset.fs;
  fdDrag = fdPicked.has(i) ? 'off' : 'on';       // 起手是选中的 → 这一拖都是取消
  frToggle(i, fdDrag === 'on');
  e.preventDefault();
});
$('#fr-mat').addEventListener('pointerover', e => {
  if (!fdDrag || fdStep !== 1) return;
  const s = e.target.closest('[data-fs]'); if (!s) return;
  frToggle(+s.dataset.fs, fdDrag === 'on');
});
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
    $('#fr-foot').innerHTML = `
      <div class="fr-tip">🖍 在材料里<b>点句子</b>勾出你认为的要点（按住拖可以连选）。
        这一步<b>只找不写</b> —— 共 ${p.n_points} 个采分点，你勾了 <b id="fr-n">${fdPicked.size}</b> 句。</div>
      <button class="btn primary" id="fr-check">看看我找得对不对</button>`;
    $('#fr-check').onclick = frDoCheck;
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
      <div class="fr-wc"><span id="fr-wc">0</span> / ${p.word_max} 字</div>
      <button class="btn primary" id="fr-grade">交给我批</button>`;
    $('#fr-ans').oninput = () => {
      $('#fr-wc').textContent = $('#fr-ans').value.replace(/\s/g, '').length;
    };
    $('#fr-grade').onclick = frDoGrade;
  }
}

async function frDoCheck() {
  if (!fdPicked.size) { toast('先在材料里勾几句', true); return; }
  const b = $('#fr-check'); b.disabled = true; b.textContent = '判定中…';
  try {
    const r = await api('/api/find/check', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paper_id: fdPaper.id, sents: [...fdPicked] }),
    });
    // 把判定结果落到句子上：找对=绿，找错=红，找漏=黄（漏的句子考生本来没勾，这里直接点出来）
    r.okSents = new Set(r.ok.flatMap(x => x.sents));
    r.wrongSents = new Set(r.wrong.map(x => x.i));
    r.missSents = new Set(r.missed.flatMap(x => x.sents));
    fdCheck = r;
    frMat();
    $('#fr-foot').innerHTML = `
      <div class="fr-res">
        <div class="fr-score">找到 <b>${r.found}</b> / ${r.total} 个采分点
          <span class="fr-acc${r.acc < 60 ? ' bad' : ''}">${r.acc}%</span></div>
        ${r.missed.length ? `<div class="fr-sec miss"><div class="fr-sec-t">❌ 找漏了 ${r.missed.length} 个</div>
          ${r.missed.map(x => `<div class="fr-item">
            <b>[${x.score} 分] ${esc(x.point)}</b>
            <div class="fr-ev" data-fsgo="${x.sents[0]}">↗ 就在这句：${esc(x.evidence.slice(0, 50))}…</div>
          </div>`).join('')}</div>` : ''}
        ${r.wrong.length ? `<div class="fr-sec bad"><div class="fr-sec-t">⚠️ 找错了 ${r.wrong.length} 处
            <i>（这些是干扰信息，不是采分点）</i></div>
          ${r.wrong.map(x => `<div class="fr-item"><div class="fr-ev" data-fsgo="${x.i}">↗ ${esc(x.t.slice(0, 50))}…</div></div>`).join('')}</div>` : ''}
        ${r.dup.length ? `<div class="fr-sec dup"><div class="fr-sec-t">🔁 找重了 ${r.dup.length} 处</div>
          ${r.dup.map(x => `<div class="fr-item"><b>${esc(x.point)}</b>
            <div class="fr-ev">这一个点你勾了 ${x.sents.length} 句 —— 材料里换了个说法而已，答案里只算一个点</div>
          </div>`).join('')}</div>` : ''}
        ${r.ok.length ? `<div class="fr-sec ok"><div class="fr-sec-t">✅ 找对了 ${r.ok.length} 个</div>
          ${r.ok.map(x => `<div class="fr-item"><b>[${x.score} 分] ${esc(x.point)}</b></div>`).join('')}</div>` : ''}
      </div>
      <div class="fr-acts">
        <button class="btn" id="fr-redo">🔄 重新找一遍</button>
        <button class="btn primary" id="fr-next">下一步：照着写点子 →</button>
      </div>`;
    $('#fr-redo').onclick = () => { fdCheck = null; fdPicked = new Set(); frMat(); frFoot(); };
    $('#fr-next').onclick = () => {
      // 漏掉的点也补进勾画（不然第二步照着写，注定还是漏）—— 但它们在原文里仍标成黄的
      fdCheck.missSents.forEach(i => fdPicked.add(i));
      fdCheck.wrongSents.forEach(i => fdPicked.delete(i));
      fdStep = 2; frRender();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    };
  } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = '看看我找得对不对'; }
}
$('#fr-foot').addEventListener('click', e => {
  const g = e.target.closest('[data-fsgo]');    // 点一下跳到原文那句
  if (!g) return;
  const el = document.querySelector(`[data-fs="${g.dataset.fsgo}"]`);
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
    fdStep = 3;
    $('#fr-head').innerHTML = `
      <div class="fr-step"><span class="done">① 找点</span><span class="done">② 写点</span><span class="on">③ 批改</span></div>`
      + frScoreHtml(g);
    $('#fr-mat').innerHTML = '';
    $('#fr-foot').innerHTML = frResultBody(g) + `
      <div class="fr-acts">
        <button class="btn primary" id="fr-again">🔄 再练这道</button>
        <button class="btn" id="fr-back">换一道</button>
      </div>`;
    $('#fr-again').onclick = () => openFindRun(fdPaper.id);
    $('#fr-back').onclick = () => { back(); loadFindList(); };
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = '交给我批'; }
}
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
async function openFindRec(rid) {
  push({ view: 'findrecd', title: '这次的批改' });
  $('#frd-head').innerHTML = '<p class="empty">加载中…</p>'; $('#frd-body').innerHTML = '';
  try {
    const d = await api('/api/find/record/' + rid);
    const g = d.grade || {}; g.score = d.score; g.full = d.full;
    $('#frd-head').innerHTML = `<div class="fr-stem">${esc(d.stem)}</div>
      <div class="fr-meta">${esc(d.type_name)} · ${d.full} 分 · 答案 ${d.word_min}~${d.word_max} 字 · ${esc((d.created_at || '').slice(0, 16))}</div>`
      + frScoreHtml(g);
    $('#frd-body').innerHTML = frFindRecapHtml(d.find_result) + frResultBody(g)
      + `<div class="fr-sec"><div class="fr-sec-t">✍️ 我写的答案</div>
         <div class="frd-ans">${esc(d.answer).replace(/\n/g, '<br>')}</div></div>`
      + `<div class="fr-acts"><button class="btn primary" id="frd-again">🔄 再练这道</button>
         <button class="btn" id="frd-back">返回记录</button></div>`;
    $('#frd-again').onclick = () => openFindRun(d.paper_id);
    $('#frd-back').onclick = () => back();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) { $('#frd-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
