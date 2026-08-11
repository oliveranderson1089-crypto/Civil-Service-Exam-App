/* 时政要文库（重要文件全文 + AI 政策解读）
 *
 * 由 app.js 按它自己的区段边界切出（原 L7127-7184）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, artEm, c, emKey, esc, isDocHeading, mdToHtml, push, stack, toast */

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
        <div class="poly-meta">全文约 ${(it.chars / 1000).toFixed(1)} 千字${it.has_ai ? ' · <span class="poly-ai-on">' + artEm("✓") + ' 已有 AI 解读</span>' : ''}</div>
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
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">${artEm('🤖')} AI 政策解读</div><div class="cd-sec-b">${mdToHtml(d.interpretation)}</div>
        <button class="btn cd-ai-regen" id="poly-regen">重新生成</button></div>`
    : `<div class="poly-genbox"><p class="cd-tip" style="margin:0 0 10px">让 AI 提炼这份文件的核心要点、公考高频考点、可引用金句与答题运用。</p>
        <button class="btn primary" id="poly-gen" style="width:100%;padding:12px;">${artEm('🤖')} 生成 AI 政策解读</button></div>`;
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
