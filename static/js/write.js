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
   fmtDay, inkRekey, push, render, toast */

/* ============= 成文：把素材真正写成一篇大作文 ============= */
let wrTab = 'daily', wrCur = null, wrPoll = 0, wrApp = false;

function openWrite(tab) {
  const app = tab === 'yingyong';           // 从「应用文 → 应用文成文」进来
  wrApp = app;                              // 每日成文/综合应用两个面板据此调应用文还是议论文接口（需求一）
  push({ view: 'write', title: app ? '应用文成文' : '议论文成文' });
  // 议论文成文：每日成文 / 综合应用；应用文成文：这两样 + 文种大全 / 自选成文
  const show = app ? ['daily', 'compose', 'yycat', 'yywrite'] : ['daily', 'compose'];
  document.querySelectorAll('#wr-tabs .tk-tab').forEach(b => b.classList.toggle('hidden', !show.includes(b.dataset.wk)));
  // 传进来的 tab 是 'yingyong'（不在列表里）→ 落到第一个「每日成文」
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
  if (wrApp) return loadYyDays();          // 应用文：走「每日一道应用文题」
  const box = $('#wr-days');
  if ($('#wr-daily-intro')) $('#wr-daily-intro').innerHTML = '按<b>素材更新的日期</b>成文：当天的人物事例 / 理论论据 / 衔接表达全用上，政治理论和常考提法按当天话题现捞。素材背了不会用等于没背。';
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

// 应用文·每日成文：AI 每天出一道应用文题（自动挑文种 + 贴热点情景），写范文 + 逐段批注
async function loadYyDays() {
  const box = $('#wr-days');
  if ($('#wr-daily-intro')) $('#wr-daily-intro').innerHTML = '每天 AI 出<b>一道应用文题</b>（自动挑一个文种 + 贴近时政的情景），写出范文并逐段批注格式。往期没写的可一键补齐。';
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/write/yingyong/days');
    const undone = d.days.filter(x => !x.eid).length;
    $('#wr-backfill').classList.toggle('hidden', !undone);
    $('#wr-backfill').textContent = `⚡ 一键补齐往期（还差 ${undone} 天）`;
    const band = x => `${YY_POS_LABEL[x.pos] || ''} · ${x.wmin}~${x.wmax}字`;
    box.innerHTML = d.days.map(x => x.eid ? `
      <div class="wr-day done" data-weid="${x.eid}">
        <div class="wr-day-d">🗓 ${fmtDay(x.date)}</div>
        <div class="wr-day-m"><b>${esc(x.title || '')}</b>
          <span class="wr-tag">${esc(x.topic || x.doctype || '')}</span>
          <span class="wr-tag">${esc(band(x))}</span>
          <span class="wr-w">${x.words} 字</span></div>
      </div>` : `
      <div class="wr-day">
        <div class="wr-day-d">🗓 ${fmtDay(x.date)}</div>
        <div class="wr-day-m"><span class="wr-n">今日文种：${esc(x.doctype)} · ${esc(band(x))}${x.scene ? ' · ' + esc(x.scene) : ''}</span></div>
        <button class="btn tiny primary" data-wgen="${x.date}">✍️ 写</button>
      </div>`).join('');
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

$('#wr-days').addEventListener('click', async e => {
  const g = e.target.closest('[data-wgen]');
  if (g) {
    g.disabled = true; g.textContent = '写作中…';
    try {
      const d = await api(wrApp ? '/api/write/yingyong/daily' : '/api/write/daily', {
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
  const msg = wrApp
    ? '把最近 14 天没写的每日应用文补齐？每篇要调一次 AI，会在后台慢慢跑，可以先去干别的。'
    : '把往期素材一天一篇全部补齐？每篇要调一次 AI，会在后台慢慢跑，可以先去干别的。';
  if (!await appConfirm(msg)) return;
  try {
    const d = await api(wrApp ? '/api/write/yingyong/backfill' : '/api/write/backfill', { method: 'POST' });
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
  const app = wrApp;
  if ($('#wr-compose-intro')) $('#wr-compose-intro').innerHTML = app
    ? '模拟<b>综合应用能力</b>大题：AI 出一段给定材料 + 作答要求，再写出参考范文（带格式批注）。每天一道。'
    : '不限日期，<b>AI 自己选题</b>——跨全部素材库挑真正用得上的，每天一篇范文。选题要是省考真考的方向，不选空泛口号。';
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/write/list?mode=' + (app ? 'yingyong-compose' : 'compose'));
    const today = new Date().toISOString().slice(0, 10);
    const has = d.items.some(x => x.date === today);
    $('#wr-gen-cp').textContent = app
      ? (has ? '🔄 今天这道重出一遍' : '✍️ 出今天这道题')
      : (has ? '🔄 今天这篇重写一遍' : '✍️ 写今天这篇');
    box.innerHTML = d.items.length ? d.items.map(x => `
      <div class="wr-day done" data-weid="${x.id}">
        <div class="wr-day-d">🗓 ${fmtDay(x.date)}</div>
        <div class="wr-day-m"><b>${esc(x.title || '')}</b>
          <span class="wr-tag">${esc(x.topic || '')}</span>
          <span class="wr-w">${x.words} 字</span></div>
      </div>`).join('')
      : (app ? '<p class="empty">还没出过。点上面的按钮，AI 出一道综合应用大题并写范文。</p>'
             : '<p class="empty">还没写过。点上面的按钮，AI 会自己选题写一篇。</p>');
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#wr-cplist').addEventListener('click', e => {
  const c = e.target.closest('[data-weid]'); if (c) openWrited(+c.dataset.weid);
});
$('#wr-gen-cp').onclick = async () => {
  const b = $('#wr-gen-cp'); b.disabled = true;
  b.textContent = wrApp ? 'AI 出题写作中…（约 30 秒）' : 'AI 选题写作中…（约 20 秒）';
  try {
    const d = await api(wrApp ? '/api/write/yingyong/compose' : '/api/write/compose', {
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
let gwSpec = null, gwType = '讲话稿', gwForm = 'full', gwPos = 'medium', yyPoll = 0;
const YY_POS_LABEL = { small: '小题位', medium: '中题位', large: '大题位' };   // 题位：越靠后字数越大

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
  const pz = e.target.closest('[data-yyp]');
  if (pz) {
    gwPos = pz.dataset.yyp;
    document.querySelectorAll('#yy-pos .chip').forEach(x => x.classList.toggle('active', x === pz));
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
        doctype: gwType, scene, form: gwForm, pos: gwPos,
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
// 应用文范文排版：首行标题不重复（头部已显示）、称谓顶格、落款机关+日期右对齐，其余正常段落
function fmtGwBody(content, title) {
  const lines = (content || '').split('\n').map(x => x.trim()).filter(Boolean);
  if (!lines.length) return '';
  const isDate = s => /^\d{4}\s*年.*日$/.test(s) || /^\d{4}[-./]\d{1,2}[-./]\d{1,2}$/.test(s);
  const isOrg = s => s.length <= 24 && /(会|局|厅|部|办|组|队|处|科|站|所|院|校|司|署|团|社|委|政府|公司|集团|支部|中心|大队|小组|街道|社区|指挥部)$/.test(s);
  const noEndPunct = s => s.length <= 24 && !/[。！？；，、：,.!?;:]$/.test(s);
  // 从尾部认出落款块（署名机关 + 日期），最多 3 行：
  // 最后一行是日期时，它上方不带句末标点的短行就当署名（更稳，机关名千奇百怪）；
  // 没有日期时才要求像机关名结尾，免得把「谢谢大家」这类结语也右对齐了。
  const lastIsDate = lines.length > 0 && isDate(lines[lines.length - 1]);
  let signFrom = lines.length;
  for (let i = lines.length - 1; i >= 0 && lines.length - i <= 3; i--) {
    const s = lines[i];
    if (isDate(s) || (noEndPunct(s) && (lastIsDate || isOrg(s)))) signFrom = i; else break;
  }
  const tnorm = (title || '').replace(/\s/g, '');
  return lines.map((ln, i) => {
    if (i === 0 && tnorm && ln.replace(/\s/g, '') === tnorm) return '';              // 首行=标题：头部已单独显示，正文不重复
    if (i >= signFrom) return `<p class="wd-gw-sign">${esc(ln)}</p>`;                 // 落款 / 日期右对齐
    if (i <= 2 && /[：:]$/.test(ln)) return `<p class="wd-gw-call">${esc(ln)}</p>`;   // 称谓顶格、不缩进
    return `<p>${esc(ln)}</p>`;
  }).join('');
}
function renderWrited() {
  const d = wrCur; if (!d) return;
  const gw = /^yingyong/.test(d.mode || '');  // 应用文（含每日成文/综合应用）：字数按文种走，提纲页签换成「格式批注」
  const sp = d.spec || {};
  const isComp = sp.kind === 'compose';      // 综合应用能力大题：有给定材料 + 作答要求
  const isOut = gw && sp.form === 'outline'; // 提纲：框架式要点式，字数本来就少，不卡字数
  const wlo = sp.wmin || 150, whi = sp.wmax || 500;   // 应用文按「题位」定的字数区间（上限 ≤500）
  const ok = isOut ? true : (gw ? (d.words >= wlo && d.words <= whi) : (d.words >= 1000 && d.words <= 1300));
  document.querySelector('#wd-tabs [data-wd=text]').textContent = isOut ? '🧭 提纲' : '📄 全文';
  document.querySelector('#wd-tabs [data-wd=outline]').textContent =
    isOut ? '📐 每块怎么写' : (gw ? '📐 格式批注' : '🧭 提纲');
  document.querySelector('#wd-tabs [data-wd=used]').textContent = gw ? '📎 用到的规范表述' : '📎 用到的素材';
  const posLbl = gw ? (isComp ? '大题位' : (sp.pos ? YY_POS_LABEL[sp.pos] || '' : '')) : '';
  const src = gw
    ? (isComp ? '🧩 综合应用能力' + (sp.doctype ? ' · ' + esc(sp.doctype) : '')
      : (isOut ? '🧭 提纲纲要' : '📄 范文') + ' · ' + esc(sp.scene || '') + (sp.role ? ' · ' + esc(sp.role) : ''))
      + (posLbl ? ' · ' + posLbl : '')
    : (d.mode === 'daily' ? '📅 ' + fmtDay(d.date) + ' 的素材' : '🧩 综合应用');
  const wtxt = gw && !isOut
    ? `${d.words} 字 / 目标 ${wlo}~${whi}${ok ? '' : (d.words > whi ? '（超了）' : '（不足）')}`
    : `${d.words} 字${ok ? '' : '（字数不达标）'}`;
  $('#wd-head').innerHTML = `
    <h2 class="wd-title">${esc(d.title || '')}</h2>
    <div class="wd-meta">
      <span class="wr-tag">${esc(d.topic || '')}</span>
      <span class="wd-w ${ok ? '' : 'bad'}">${wtxt}</span>
      <span class="wd-src">${src}</span>
      <span class="wd-used-n">📎 ${(d.used || []).length} 条${gw ? '规范表述' : '素材'}</span>
    </div>
    ${d.note ? `<p class="wd-note">💡 ${esc(d.note)}</p>` : ''}`;
  const paras = (s) => (s || '').split('\n').filter(x => x.trim()).map(p => `<p>${esc(p.trim())}</p>`).join('');
  const stripLbl = (s) => (s || '').replace(/^\s*【[^】]{1,8}】\s*\n?/, '');   // 去掉开头重复的「【给定材料】」标签
  // 综合应用能力：题干（给定材料 + 作答要求）在前，参考范文在后
  const timu = isComp ? `<div class="wd-timu">
      <div class="wd-timu-t">📎 给定材料</div><div class="wd-timu-b">${paras(stripLbl(sp.material))}</div>
      <div class="wd-timu-t">✍️ 作答要求</div><div class="wd-timu-b">${paras(stripLbl(sp.task))}</div>
      <div class="wd-timu-t">📄 参考范文</div>
    </div>` : '';
  // 应用文范文按公文格式排（落款/日期右对齐、称谓顶格）；议论文用普通段落
  const body = gw ? fmtGwBody(d.content, d.title) : paras(d.content);
  $('#wd-text').innerHTML = isOut
    ? `<pre class="wd-outline">${esc(d.content || '')}</pre>`   // 提纲有缩进和「· 」，原样保留
    : timu + body;
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
  if (typeof inkRekey === 'function') inkRekey();   // 批注层开着就换成这个 tab 的笔迹，别串到别的 tab（需求四）
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
