/* 经典著作（毛泽东选集）
 *
 * 由 app.js 按它自己的区段边界切出（原 L7010-7063）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, c, emKey, esc, isDocHeading,
   mdToHtml, push, stack, toast */

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
