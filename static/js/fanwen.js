/* 人民时评 · 申论范文
 *
 * 由 app.js 按它自己的区段边界切出（原 L7185-7319）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, c, emKey, esc, fmtDay,
   mdToHtml, push, stack, toast */

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
    $('#fw-msg').textContent = d.msg || (d.added > 0 ? `新增 ${d.added} 篇` : '今天暂无更新');
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
