/* 每日时政 + 概括句积累（概括句由时政生成）
 *
 * 由 app.js 按它自己的区段边界切出（原 L3749-3982）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, artEm, c, emKey, esc, injectReadBtns, mdToHtml, push, stack, toast */

/* ============= 每日时政（爬虫 + AI 三行式；国内/四川/国际 三板块，全局共享） ============= */
let newsBoard = '党内', newsDate = '';
function fmtDay(iso) {
  const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(iso || '');
  return m ? (+m[1]) + '月' + (+m[2]) + '日' : (iso || '');
}
function renderDateStrip(el, dates, cur, attr) {
  el.innerHTML = (dates || []).map(d =>
    `<button class="chip ${d.date === cur ? 'active' : ''}" data-${attr}="${esc(d.date)}">${fmtDay(d.date)} ${d.count}</button>`).join('');
}
const XY_COLOR = { '经济': '#c2671f', '文化': '#7a5cc0', '社会': '#2b6fd6', '党建': '#b23b2e', '科教': '#0f766e', '生态': '#2e7d32', '国防': '#5a6b85', '国际': '#0277bd' };
let xyCat = '全部';
async function loadXiyu() {
  $('#news-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/xiyu?cat=' + encodeURIComponent(xyCat));
    const cats = ['全部'].concat(Object.keys(XY_COLOR));
    $('#news-dates').innerHTML = cats.map(c =>
      `<button class="chip ${c === xyCat ? 'active' : ''}" data-xc="${c}">${c}${c !== '全部' && d.counts[c] ? ' ' + d.counts[c] : ''}</button>`).join('');
    $('#news-dates').classList.remove('hidden');
    if (!d.items.length) { $('#news-list').innerHTML = '<p class="empty">还没有金句，每天清晨自动从习近平讲话数据库提炼～</p>'; return; }
    let lastDate = '';
    $('#news-list').innerHTML = d.items.map(it => {
      const head = it.date !== lastDate ? `<div class="sc-day">${artEm('🗓')} ${fmtDay(it.date)}</div>` : '';
      lastDate = it.date;
      const apply = it.apply || it.note || '';
      const bg = (it.note && it.note !== apply) ? it.note : '';
      return head + `<div class="gk-card">
        <div class="gk-head"><span class="poly-badge" style="background:${XY_COLOR[it.category] || '#666'}">${esc(it.category)}</span>
          ${it.keyword ? `<span class="xy-kw">🔑 ${esc(it.keyword)}</span>` : ''}</div>
        <div class="xy-quote">${emKey('“' + it.quote + '”')}</div>
        ${bg ? `<div class="xy-bg"><b>出处背景</b> ${esc(bg)}</div>` : ''}
        ${apply ? `<div class="xy-note"><b>申论运用</b> ${esc(apply)}</div>` : ''}
        ${it.source_url ? `<a class="poly-src" href="${esc(it.source_url)}" target="_blank" rel="noopener">讲话原文 ↗</a>` : ''}
      </div>`;
    }).join('');
  } catch (e) { $('#news-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
async function loadNews() {
  if (newsBoard === '习语') {
    document.querySelectorAll('#news-boards .chip').forEach(x => x.classList.toggle('active', x.dataset.nb === '习语'));
    loadXiyu(); return;
  }
  const starMode = newsBoard === '收藏';
  document.querySelectorAll('#news-boards .chip').forEach(x => x.classList.toggle('active', x.dataset.nb === newsBoard));
  $('#news-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api(starMode ? '/api/news?star=1'
      : '/api/news?board=' + encodeURIComponent(newsBoard) + '&date=' + encodeURIComponent(newsDate));
    if (d.counts) document.querySelectorAll('#news-boards .chip').forEach(x => {
      if (x.dataset.nb === '收藏') { x.textContent = '⭐ 收藏' + (d.star_total ? ' ' + d.star_total : ''); return; }
      const n = d.counts[x.dataset.nb]; x.textContent = x.dataset.nb + (n ? ' ' + n : '');
    });
    newsDate = d.date || '';
    renderDateStrip($('#news-dates'), d.dates, newsDate, 'nd');
    $('#news-dates').classList.toggle('hidden', starMode);
    if (!d.items.length) {
      $('#news-list').innerHTML = '<p class="empty">' + (starMode ? '还没有收藏，点新闻卡右上角的 ☆ 收藏。' : '这一天该板块没有时政，点上面换一天看看～') + '</p>';
      return;
    }
    $('#news-list').innerHTML = d.items.map(it => {
      const sum = (it.ai_summary || '').trim();
      return `<div class="poly-card news-card" data-news="${it.id}">
        <button class="news-star ${it.starred ? 'on' : ''}" data-nstar="${it.id}">${it.starred ? '★' : '☆'}</button>
        <div class="news-date">${artEm('🗓')} ${esc(it.pub_date || '')} · ${esc(it.source || '')}</div>
        <div class="poly-t" style="font-size:16px;padding-right:34px;">${esc(it.title)}</div>
        ${sum ? `<div class="news-sum" style="white-space:pre-wrap">${esc(sum)}</div>` : ''}
      </div>`;
    }).join('');
  } catch (e) { $('#news-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function openNews() { newsDate = ''; push({ view: 'news', title: '每日时政' }); loadNews(); }
$('#news-boards').addEventListener('click', e => {
  const c = e.target.closest('[data-nb]'); if (!c) return;
  newsBoard = c.dataset.nb; newsDate = ''; loadNews();
});
$('#news-dates').addEventListener('click', e => {
  const xc = e.target.closest('[data-xc]');
  if (xc) { xyCat = xc.dataset.xc; loadXiyu(); return; }
  const c = e.target.closest('[data-nd]'); if (!c) return;
  newsDate = c.dataset.nd; loadNews();
});
$('#news-list').addEventListener('click', async e => {
  const st = e.target.closest('[data-nstar]');
  if (st) {
    e.stopPropagation();
    const on = !st.classList.contains('on');
    try {
      await api('/api/news/' + st.dataset.nstar + '/star', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: on }) });
      st.classList.toggle('on', on); st.textContent = on ? '★' : '☆';
      if (newsBoard === '收藏' && !on) loadNews();
      else toast(on ? '已收藏' : '已取消收藏');
    } catch (err) { toast(err.message, true); }
    return;
  }
  const c = e.target.closest('[data-news]'); if (c) openNewsItem(+c.dataset.news);
});
/* 时政的重点标注：四类考点，颜色一一对应 */
const NW_KIND = { 提法: { c: '#c4661f', d: '新表述/新概念，常识判断爱考' },
  数据: { c: '#1e8449', d: '具体数字/时间，最容易做成选项' },
  政策: { c: '#1a6fb5', d: '文件名/举措/目标' },
  金句: { c: '#7a5cc0', d: '能直接写进申论的表述' } };
let nwCur = null;

/* 把 AI 逐字挑出的句子，原样标回原文里（它们都经服务端核对过，必然能命中） */
function nwMarkup(content, marks) {
  const esc1 = (t) => esc(t);
  if (!marks || !marks.length) return esc1(content);
  // 长句优先标，避免短句先命中把长句切碎
  const ms = [...marks].sort((a, b) => b.quote.length - a.quote.length);
  const hits = [];
  ms.forEach((m, i) => {
    let from = 0, at;
    while ((at = content.indexOf(m.quote, from)) !== -1) {
      if (!hits.some(h => at < h.end && at + m.quote.length > h.start))   // 不和已标的重叠
        hits.push({ start: at, end: at + m.quote.length, m, i: marks.indexOf(m) });
      from = at + m.quote.length;
    }
  });
  hits.sort((a, b) => a.start - b.start);
  let out = '', pos = 0;
  for (const h of hits) {
    out += esc1(content.slice(pos, h.start));
    const k = NW_KIND[h.m.kind] || NW_KIND['提法'];
    // 注意：标签必须写成一行——外面会按 \n 切段落，标签里夹了换行就会被劈开，属性会漏成正文
    const tip = esc1(h.m.kind + '：' + (h.m.why || '')).replace(/"/g, '&quot;');
    out += `<mark class="nw-mk" style="--mk:${k.c}" data-nwm="${h.i}" title="${tip}">${esc1(h.m.quote)}<i>${esc1(h.m.kind)}</i></mark>`;
    pos = h.end;
  }
  out += esc1(content.slice(pos));
  return out;
}

async function openNewsItem(id) {
  push({ view: 'newsd', title: '时政详情' });
  $('#news-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/news/' + id);
    nwCur = d;
    stack[stack.length - 1].title = d.title; $('#top-title').textContent = d.title;
    nwRender(d);
  } catch (e) { $('#news-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}

function nwRender(d) {
  const marks = d.marks || [];
  // 重点清单：先看这个就够了，没时间就别读全文
  const list = marks.length ? `
    <div class="cd-sec nw-marks"><div class="cd-sec-t">${artEm('🖍')} 重点 · 考点（${marks.length} 处，原文里已划出）</div>
      ${marks.map((m, i) => {
        const k = NW_KIND[m.kind] || NW_KIND['提法'];
        return `<div class="nw-m" data-nwgo="${i}" style="--mk:${k.c}">
          <span class="nw-k">${esc(m.kind)}</span>
          <span class="nw-q">${esc(m.quote)}</span>
          <span class="nw-w">${esc(m.why || '')}</span>
        </div>`;
      }).join('')}
      <div class="nw-legend">${Object.entries(NW_KIND).map(([k, v]) =>
        `<span style="--mk:${v.c}"><i></i>${k}：${v.d}</span>`).join('')}</div>
    </div>`
    : `<div class="cd-sec nw-marks">
        <div class="cd-sec-t">${artEm('🖍')} 重点 · 考点</div>
        <p class="empty" style="padding:6px 0 12px">还没划重点。点一下，AI 会在原文里把该记的地方标出来（约 20 秒），不用通读全文。</p>
        <button class="btn primary" id="nw-mark">${artEm('🖍')} 帮我划重点</button>
      </div>`;

  const ai = d.ai_summary
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">${artEm('🤖')} AI 摘要 · 三行式</div><div class="cd-sec-b">${mdToHtml(d.ai_summary)}</div></div>` : '';

  // 原文：把逐字挑出的重点句原样标出来（服务端核对过，必然命中）
  const marked = nwMarkup(d.content || '', marks);
  const body = marked.split('\n').filter(x => x.trim()).map(p =>
    `<p>${p}</p>`).join('');

  $('#news-wrap').innerHTML = `
    <div class="poly-head"><h2>${esc(d.title)}</h2>
      <div class="news-date">${artEm('🗓')} ${esc(d.pub_date || '')} · ${esc(d.source || '')}</div>
      <a class="poly-src" href="${esc(d.url)}" target="_blank" rel="noopener">原文来源 ↗</a></div>
    ${list}
    ${ai}
    <div class="poly-readert">全文（重点已划出）${marks.length ? `<button class="btn tiny" id="nw-remark">重划</button>` : ''}</div>
    <div class="poly-reader nw-reader">${body}</div>`;
  injectReadBtns();
}
$('#news-wrap').addEventListener('click', async e => {
  const go = e.target.closest('[data-nwgo]');            // 点重点清单 → 滚到原文里那一句
  if (go) {
    const el = $('#news-wrap').querySelector(`mark[data-nwm="${go.dataset.nwgo}"]`);
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      el.classList.add('flash');
      setTimeout(() => el.classList.remove('flash'), 1400);
    }
    return;
  }
  const b = e.target.closest('#nw-mark, #nw-remark');
  if (!b || !nwCur) return;
  b.disabled = true; b.textContent = '正在划重点…（约 20 秒）';
  try {
    const d = await api('/api/news/' + nwCur.id + '/marks' + (b.id === 'nw-remark' ? '?force=1' : ''),
      { method: 'POST' });
    nwCur.marks = d.marks;
    nwRender(nwCur);
    toast('划出 ' + d.marks.length + ' 处重点');
  } catch (err) {
    toast(err.message, true);
    b.disabled = false; b.textContent = '🖍 帮我划重点';
  }
});

/* ============= 申论 · 概括句积累（每日由时政生成，按日期查看） ============= */
let gkDate = '';
async function loadGaikuo() {
  $('#gk-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/gaikuo?date=' + encodeURIComponent(gkDate));
    gkDate = d.date || '';
    renderDateStrip($('#gk-dates'), d.dates, gkDate, 'gd');
    if (!d.items.length) { $('#gk-list').innerHTML = '<p class="empty">还没有概括句，每天早上会自动从当日时政生成～</p>'; return; }
    $('#gk-list').innerHTML = d.items.map((it, i) => `
      <div class="gk-card">
        <div class="gk-head"><span class="gk-no">${i + 1}</span><span class="gk-topic">${esc(it.topic)}</span></div>
        ${it.raw ? `<div class="gk-raw"><span class="gk-lab">材料</span>${esc(it.raw)}</div>` : ''}
        <div class="gk-sent"><span class="gk-lab gk-lab-s">概括</span><b>${esc(it.sentence)}</b></div>
        ${it.tip ? `<div class="gk-tip">${artEm('💡')} ${esc(it.tip)}</div>` : ''}
      </div>`).join('');
  } catch (e) { $('#gk-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function openGaikuo() { gkDate = ''; push({ view: 'gaikuo', title: '概括句积累' }); loadGaikuo(); }
$('#gk-dates').addEventListener('click', e => {
  const c = e.target.closest('[data-gd]'); if (!c) return;
  gkDate = c.dataset.gd; loadGaikuo();
});
