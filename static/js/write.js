/* 成文 + 素材积累 / 衔接表达（成文要用素材）
 *
 * 由 app.js 按它自己的区段边界切出（原 L4888-5252）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, appConfirm, c, emKey, esc,
   fmtDay, push, render, toast */

/* ============= 成文：把素材真正写成一篇大作文 ============= */
let wrTab = 'daily', wrCur = null, wrPoll = 0;

function openWrite(tab) {
  const app = tab === 'yingyong';           // 从「应用文 → 应用文成文」进来
  push({ view: 'write', title: app ? '应用文成文' : '议论文成文' });
  // 议论文成文放「每日成文 / 综合应用」；应用文成文放「文种大全 / 自选成文」——各两个导航栏
  const show = app ? ['yycat', 'yywrite'] : ['daily', 'compose'];
  document.querySelectorAll('#wr-tabs .tk-tab').forEach(b => b.classList.toggle('hidden', !show.includes(b.dataset.wk)));
  wrTab = show.includes(tab) ? tab : show[0];
  wrSwitch(wrTab);            // render() 只负责显隐视图，内容要自己拉
}
function wrSwitch(k) {
  wrTab = k;
  document.querySelectorAll('#wr-tabs .tk-tab').forEach(b => b.classList.toggle('active', b.dataset.wk === k));
  ['daily', 'compose', 'yycat', 'yywrite'].forEach(x => $('#wr-' + x).classList.toggle('hidden', x !== k));
  if (k === 'daily') loadWrDays();
  else if (k === 'compose') loadWrCompose();
  else if (k === 'yycat') loadYyCats();
  else if (k === 'yywrite') loadWrGw();
}
// tab 点击切换（这个 handler 连同下面几个 load 函数在做应用文那次被误删了 → 每日成文/综合应用点了没反应、空白）
$('#wr-tabs').addEventListener('click', e => {
  const b = e.target.closest('.tk-tab'); if (b) wrSwitch(b.dataset.wk);
});
async function loadWrDays() {
  const box = $('#wr-days');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/write/days');
    const undone = d.days.filter(x => !x.eid).length;
    $('#wr-backfill').classList.toggle('hidden', !undone);
    $('#wr-backfill').textContent = `⚡ 一键补齐往期（还差 ${undone} 天）`;
    if (!d.days.length) { box.innerHTML = '<p class="empty">还没有素材，每天 08:00 自动更新～</p>'; return; }
    box.innerHTML = d.days.map(x => x.eid ? `
      <div class="wr-day done" data-weid="${x.eid}">
        <div class="wr-day-d">🗓 ${fmtDay(x.date)}</div>
        <div class="wr-day-m"><b>${esc(x.title || '')}</b>
          <span class="wr-tag">${esc(x.topic || '')}</span>
          <span class="wr-w">${x.words} 字</span></div>
      </div>` : `
      <div class="wr-day">
        <div class="wr-day-d">🗓 ${fmtDay(x.date)}</div>
        <div class="wr-day-m"><span class="wr-n">素材 ${x.n} 条（衔接 ${x.nl}）</span></div>
        <button class="btn tiny primary" data-wgen="${x.date}">✍️ 写</button>
      </div>`).join('');
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

$('#wr-days').addEventListener('click', async e => {
  const g = e.target.closest('[data-wgen]');
  if (g) {
    g.disabled = true; g.textContent = '写作中…';
    try {
      const d = await api('/api/write/daily', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: g.dataset.wgen }),
      });
      openWrited(d.id);
      loadWrDays();
    } catch (err) { toast(err.message, true); g.disabled = false; g.textContent = '✍️ 写'; }
    return;
  }
  const c = e.target.closest('[data-weid]');
  if (c) openWrited(+c.dataset.weid);
});

$('#wr-backfill').onclick = async () => {
  if (!await appConfirm('把往期素材一天一篇全部补齐？每篇要调一次 AI，会在后台慢慢跑，可以先去干别的。')) return;
  try {
    const d = await api('/api/write/backfill', { method: 'POST' });
    wrWatch(d.task);
  } catch (e) { toast(e.message, true); }
};

function wrWatch(tid) {
  clearInterval(wrPoll);
  $('#wr-backfill').disabled = true;
  const msg = $('#wr-bfmsg');
  wrPoll = setInterval(async () => {
    try {
      const t = await api('/api/write/task/' + tid);
      msg.textContent = `${t.message || ''}（${t.progress}/${t.total}）`;
      if (t.status === 'done' || t.status === 'error') {
        clearInterval(wrPoll); wrPoll = 0;
        $('#wr-backfill').disabled = false;
        msg.textContent = t.message || '';
        loadWrDays();
        toast(t.status === 'done' ? '补齐完成' : t.message, t.status !== 'done');
      }
    } catch (_) { clearInterval(wrPoll); wrPoll = 0; $('#wr-backfill').disabled = false; }
  }, 3000);
}

async function loadWrCompose() {
  const box = $('#wr-cplist');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/write/list?mode=compose');
    const today = new Date().toISOString().slice(0, 10);
    $('#wr-gen-cp').textContent = d.items.some(x => x.date === today)
      ? '🔄 今天这篇重写一遍' : '✍️ 写今天这篇';
    box.innerHTML = d.items.length ? d.items.map(x => `
      <div class="wr-day done" data-weid="${x.id}">
        <div class="wr-day-d">🗓 ${fmtDay(x.date)}</div>
        <div class="wr-day-m"><b>${esc(x.title || '')}</b>
          <span class="wr-tag">${esc(x.topic || '')}</span>
          <span class="wr-w">${x.words} 字</span></div>
      </div>`).join('') : '<p class="empty">还没写过。点上面的按钮，AI 会自己选题写一篇。</p>';
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#wr-cplist').addEventListener('click', e => {
  const c = e.target.closest('[data-weid]'); if (c) openWrited(+c.dataset.weid);
});
$('#wr-gen-cp').onclick = async () => {
  const b = $('#wr-gen-cp'); b.disabled = true; b.textContent = 'AI 选题写作中…（约 20 秒）';
  try {
    const d = await api('/api/write/compose', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true }),
    });
    openWrited(d.id); loadWrCompose();
  } catch (e) { toast(e.message, true); }
  b.disabled = false;
};


/* ---- 应用文：按「类别 → 文种」铺开，每个文种给「提纲 + 范文」两样 ----
   提纲**不是文种**，是一种呈现方式（框架式、要点式），任何文种都能套。
   先看提纲（这个文种由哪几块组成）再看范文（成品长什么样），才知道文章是怎么长出来的。
   第一次一键把所有文种各铺一份；之后就是针对同一文种换话题积累。 */
let gwSpec = null, gwType = '讲话稿', gwForm = 'full', yyPoll = 0;

async function loadWrGw() {
  if (!gwSpec) {
    try { gwSpec = await api('/api/write/gwspec'); } catch (e) { toast(e.message, true); return; }
  }
  $('#yy-types').innerHTML = gwSpec.doctypes.map(d =>
    `<button class="chip${d.k === gwType ? ' active' : ''}" data-gwt="${esc(d.k)}">${esc(d.k)}</button>`).join('');
  $('#yy-scenes').innerHTML = '<span class="gw-sug-t">常用：</span>' + gwSpec.scenes.map(s =>
    `<button class="chip tiny" data-gws="${esc(s)}">${esc(s)}</button>`).join('');
  gwFmt();
  // 文种大全（yy-cats）现在是独立的一个导航栏，各自加载，这里不再连带拉它
}
function gwFmt() {
  const d = gwSpec.doctypes.find(x => x.k === gwType); if (!d) return;
  $('#yy-fmt').innerHTML = `<b>${esc(d.k)}</b>：${esc(d.d)}<br>
    <span class="gw-fmt-k">格式骨架</span>${esc(d.fmt)} · ${d.min}~${d.max} 字`;
}

async function loadYyCats() {
  const box = $('#yy-cats');
  box.innerHTML = box.innerHTML || '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/write/yylist');
    const miss = d.total * 2 - d.have_full - d.have_outline;
    const bt = $('#yy-batch');
    bt.classList.toggle('hidden', miss <= 0);
    bt.textContent = `⚡ 一键铺开所有文种（还差 ${miss} 篇）`;
    box.innerHTML = d.cats.map(c => `
      <div class="yy-cat">
        <div class="yy-cat-t">${esc(c.cat)}</div>
        ${c.doctypes.map(t => `
          <div class="yy-dt">
            <div class="yy-dt-h">
              <b>${esc(t.k)}</b><span class="yy-dt-d">${esc(t.d)}</span>
            </div>
            <div class="yy-dt-b">
              ${t.outline.length
                ? `<button class="yy-pill out" data-weid="${t.outline[0].id}">🧭 提纲</button>`
                : '<span class="yy-pill none">🧭 提纲 · 还没有</span>'}
              ${t.full.length
                ? t.full.map(f => `<button class="yy-pill" data-weid="${f.id}"
                    title="${esc(f.title || '')}">📄 ${esc(f.scene || f.title || '范文')}</button>`).join('')
                : '<span class="yy-pill none">📄 范文 · 还没有</span>'}
            </div>
          </div>`).join('')}
      </div>`).join('');
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

$('#yy-batch').onclick = async () => {
  if (!await appConfirm('给每个文种各写一份提纲和一篇范文（先提纲后范文）。要调不少次 AI，会在后台慢慢跑，可以先去干别的。')) return;
  try {
    const d = await api('/api/write/yingyong/batch', { method: 'POST' });
    yyWatch(d.task);
  } catch (e) { toast(e.message, true); }
};
function yyWatch(tid) {
  clearInterval(yyPoll);
  $('#yy-batch').disabled = true;
  const msg = $('#yy-bfmsg');
  yyPoll = setInterval(async () => {
    try {
      const t = await api('/api/write/task/' + tid);
      msg.textContent = `${t.message || ''}（${t.progress}/${t.total}）`;
      if (t.status === 'done' || t.status === 'error') {
        clearInterval(yyPoll); yyPoll = 0;
        $('#yy-batch').disabled = false;
        msg.textContent = t.message || '';
        loadYyCats();
        toast(t.status === 'done' ? '铺开完成' : t.message, t.status !== 'done');
      }
    } catch (_) { clearInterval(yyPoll); yyPoll = 0; $('#yy-batch').disabled = false; }
  }, 3000);
}

function yyPaneClick(e) {
  const t = e.target.closest('[data-gwt]');
  if (t) { gwType = t.dataset.gwt; loadWrGw(); return; }
  const f = e.target.closest('[data-yyf]');
  if (f) {
    gwForm = f.dataset.yyf;
    document.querySelectorAll('#yy-forms .chip').forEach(x => x.classList.toggle('active', x === f));
    return;
  }
  const s = e.target.closest('[data-gws]');
  if (s) { $('#yy-scene').value = s.dataset.gws; return; }
  const c = e.target.closest('[data-weid]');
  if (c) openWrited(+c.dataset.weid);
}
$('#wr-yycat').addEventListener('click', yyPaneClick);       // 文种大全：点提纲/范文打开
$('#wr-yywrite').addEventListener('click', yyPaneClick);     // 自选成文：文种/表单/生成
$('#yy-go').onclick = async () => {
  const scene = $('#yy-scene').value.trim();
  if (!scene) { toast('先说清楚就什么事发文', true); return; }
  const b = $('#yy-go'); b.disabled = true; b.textContent = '写作中…';
  try {
    const d = await api('/api/write/yingyong', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        doctype: gwType, scene, form: gwForm,
        role: $('#yy-role').value.trim(), audience: $('#yy-aud').value.trim(),
      }),
    });
    openWrited(d.id); loadYyCats();
  } catch (e) { toast(e.message, true); }
  b.disabled = false; b.textContent = '✍️ 写这一篇';
};

/* ---- 成文详情 ---- */
async function openWrited(id) {
  wrCur = null;
  push({ view: 'writed', title: '成文' });
  $('#wd-head').innerHTML = '<p class="empty">加载中…</p>';
  try {
    wrCur = await api('/api/write/' + id);
    renderWrited();
  } catch (e) { $('#wd-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
function renderWrited() {
  const d = wrCur; if (!d) return;
  const gw = d.mode === 'yingyong';           // 应用文：字数按文种走，提纲页签换成「格式批注」
  const sp = d.spec || {};
  const isOut = gw && sp.form === 'outline'; // 提纲：框架式要点式，字数本来就少，不卡字数
  const ok = isOut ? true : (gw ? d.words >= 250 : (d.words >= 1000 && d.words <= 1300));
  document.querySelector('#wd-tabs [data-wd=text]').textContent = isOut ? '🧭 提纲' : '📄 全文';
  document.querySelector('#wd-tabs [data-wd=outline]').textContent =
    isOut ? '📐 每块怎么写' : (gw ? '📐 格式批注' : '🧭 提纲');
  document.querySelector('#wd-tabs [data-wd=used]').textContent = gw ? '📎 用到的规范表述' : '📎 用到的素材';
  $('#wd-head').innerHTML = `
    <h2 class="wd-title">${esc(d.title || '')}</h2>
    <div class="wd-meta">
      <span class="wr-tag">${esc(d.topic || '')}</span>
      <span class="wd-w ${ok ? '' : 'bad'}">${d.words} 字${ok ? '' : '（字数不达标）'}</span>
      <span class="wd-src">${gw
        ? (isOut ? '🧭 提纲纲要' : '📄 范文') + ' · ' + esc(sp.scene || '')
          + (sp.role ? ' · ' + esc(sp.role) : '')
        : (d.mode === 'daily' ? '📅 ' + fmtDay(d.date) + ' 的素材' : '🧩 综合应用')}</span>
      <span class="wd-used-n">📎 ${(d.used || []).length} 条${gw ? '规范表述' : '素材'}</span>
    </div>
    ${d.note ? `<p class="wd-note">💡 ${esc(d.note)}</p>` : ''}`;
  $('#wd-text').innerHTML = isOut
    ? `<pre class="wd-outline">${esc(d.content || '')}</pre>`   // 提纲有缩进和「· 」，原样保留
    : (d.content || '').split('\n').filter(x => x.trim())
        .map(p => `<p>${esc(p.trim())}</p>`).join('');
  const groups = {};
  (d.used || []).forEach(u => { (groups[u.sec] = groups[u.sec] || []).push(u.text); });
  $('#wd-used').innerHTML = Object.keys(groups).length ? Object.entries(groups).map(([k, v]) => `
    <div class="wd-ug"><div class="wd-ug-t">${esc(k)}</div>
      ${v.map(t => `<div class="wd-ui">${esc(t)}</div>`).join('')}</div>`).join('')
    : `<p class="empty">这篇没能核对出用了哪些${gw ? '规范表述' : '素材'}。</p>`;
  if (gw) {
    // 应用文的重点全在这儿：每段是哪个部件、为什么这么写。看完才知道怎么学。
    $('#wd-outline').innerHTML = (d.outline || []).length
      ? d.outline.map(s => `<div class="gw-seg">
          <div class="gw-seg-p">${esc(s.part || '')}</div>
          <div class="gw-seg-t">${esc(s.text || '')}</div>
          <div class="gw-seg-w">💡 ${esc(s.why || '')}</div>
        </div>`).join('')
      : '<p class="empty">没有批注。</p>';
  } else {
    $('#wd-outline').innerHTML = (d.outline || []).length
      ? `<ol class="wd-ol">${d.outline.map(x => `<li>${esc(x)}</li>`).join('')}</ol>`
      : '<p class="empty">没有提纲。</p>';
  }
}
$('#wd-tabs').addEventListener('click', e => {
  const b = e.target.closest('.tk-tab'); if (!b) return;
  document.querySelectorAll('#wd-tabs .tk-tab').forEach(x => x.classList.toggle('active', x === b));
  ['text', 'used', 'outline'].forEach(k => $('#wd-' + k).classList.toggle('hidden', k !== b.dataset.wd));
});

/* ============= 议论文 · 素材积累 / 衔接表达（与微信 08:00 推送同源） ============= */
let scKind = '全部';
const SC_COLOR = { '人物事例': '#b23b2e', '具体事例': '#0f766e', '理论论据': '#7a5cc0', '衔接表达': '#c2671f' };
async function loadSucai() {
  document.querySelectorAll('#sc-kinds .chip').forEach(x => x.classList.toggle('active', x.dataset.sk === scKind));
  $('#sc-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/sucai?kind=' + encodeURIComponent(scKind));
    document.querySelectorAll('#sc-kinds .chip').forEach(x => {
      if (x.dataset.sk === '全部') return;
      const n = d.counts[x.dataset.sk]; x.textContent = x.dataset.sk + (n ? ' ' + n : '');
    });
    if (!d.items.length) { $('#sc-list').innerHTML = '<p class="empty">还没有素材，每天 08:00 自动生成～</p>'; return; }
    let lastDate = '';
    $('#sc-list').innerHTML = d.items.map(it => {
      const head = it.date !== lastDate ? `<div class="sc-day">🗓 ${fmtDay(it.date)}</div>` : '';
      lastDate = it.date;
      const col = SC_COLOR[it.kind] || '#666';
      const isLj = it.kind === '衔接表达';
      const exHtml = it.example
        ? `<div class="sc-exwrap"><div class="sc-ex"><b>例句</b> ${esc(it.example)}</div>
             <button class="sc-exbtn regen" data-scex="${it.id}" data-force="1">🔄 换个例句</button></div>`
        : (isLj ? `<button class="sc-exbtn" data-scex="${it.id}">✍️ AI 造个例句</button>` : '');
      return head + `<div class="gk-card" data-scid="${it.id}">
        <div class="gk-head"><span class="poly-badge" style="background:${col}">${esc(it.kind)}</span>
          ${it.topic ? `<span class="gk-topic">${esc(it.topic)}</span>` : ''}</div>
        <div class="sc-body">${emKey(it.content)}</div>
        ${exHtml}
      </div>`;
    }).join('');
  } catch (e) { $('#sc-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#sc-list').addEventListener('click', async e => {
  const b = e.target.closest('[data-scex]'); if (!b) return;
  const force = b.dataset.force === '1';
  const label = b.textContent;
  b.disabled = true; b.textContent = force ? '换句中…' : 'AI 造句中…';
  try {
    const d = await api('/api/sucai/' + b.dataset.scex + '/example', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force })
    });
    if (force) {                    // 原地替换例句文本，按钮留着可再换
      const ex = b.parentElement.querySelector('.sc-ex');
      if (ex) ex.innerHTML = `<b>例句</b> ${esc(d.example)}`;
      b.disabled = false; b.textContent = label;
    } else {
      b.outerHTML = `<div class="sc-exwrap"><div class="sc-ex"><b>例句</b> ${esc(d.example)}</div>
        <button class="sc-exbtn regen" data-scex="${b.dataset.scex}" data-force="1">🔄 换个例句</button></div>`;
    }
  } catch (err) { toast(err.message, true); b.disabled = false; b.textContent = label; }
});
function openSucai(kind) {
  scKind = kind || '全部';
  push({ view: 'sucai', title: scKind === '衔接表达' ? '衔接表达' : '素材积累' });
  loadSucai();
}
$('#sc-kinds').addEventListener('click', e => {
  const c = e.target.closest('[data-sk]'); if (!c) return;
  scKind = c.dataset.sk; loadSucai();
});
