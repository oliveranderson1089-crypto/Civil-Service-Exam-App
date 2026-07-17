/* 各板块基础知识点
 *
 * 由 app.js 按它自己的区段边界切出（原 L3241-3290）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, c, esc, mdToHtml, push,
   toast */

/* ================= 板块基础知识点 ================= */
let bkbBoard = '', bkbData = null;
async function openBoardKb(board) {
  bkbBoard = board;
  push({ view: 'boardkb', title: board + ' · 基础知识点' });
  $('#bkb-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try { const d = await api('/api/boardkb?board=' + encodeURIComponent(board)); bkbData = d; renderBkb(); }
  catch (e) { $('#bkb-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderBkb() {
  const d = bkbData;
  const ai = d.ai
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">📚 基础知识 · 方法技巧（AI 整理）</div>
        <div class="cd-sec-b">${mdToHtml(d.ai)}</div>
        <button class="btn cd-ai-regen" id="bkb-regen">重新生成</button></div>`
    : `<div class="bkb-gen"><p class="cd-tip" style="margin:0 0 12px">还没有整理这个板块的基础知识点，让 AI 帮你系统梳理一份。</p>
        <button class="btn primary" id="bkb-gen" style="width:100%;padding:13px;">🤖 AI 生成基础知识点</button></div>`;
  const pts = (d.points || []).map(p =>
    `<div class="bkb-point"><div class="bkb-point-c">${esc(p.content).replace(/\n/g, '<br>')}</div>
      <button class="bkb-point-del" data-bpdel="${p.id}">×</button></div>`).join('');
  $('#bkb-wrap').innerHTML = ai + `
    <div class="cd-sec"><div class="cd-sec-t">✍️ 我的补充</div>
      <div class="bkb-points">${pts || '<p class="cd-tip" style="margin:0 0 10px">还没有补充，写点自己的要点/技巧吧。</p>'}</div>
      <div class="bkb-add">
        <textarea id="bkb-input" rows="2" placeholder="添加一条自己的知识点/技巧…"></textarea>
        <button class="btn primary" id="bkb-addbtn">添加</button>
      </div>
    </div>`;
}
$('#bkb-wrap').addEventListener('click', async e => {
  const g = e.target.closest('#bkb-gen') || e.target.closest('#bkb-regen');
  if (g) {
    g.disabled = true; g.textContent = 'AI 生成中…（约二十秒）';
    try {
      const d = await api('/api/boardkb/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ board: bkbBoard, force: g.id === 'bkb-regen' }) });
      bkbData.ai = d.content; renderBkb(); toast('已生成');
    } catch (err) { toast(err.message, true); g.disabled = false; g.textContent = '🤖 AI 生成基础知识点'; }
    return;
  }
  if (e.target.closest('#bkb-addbtn')) {
    const c = $('#bkb-input').value.trim(); if (!c) return;
    try { const p = await api('/api/boardkb/point', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ board: bkbBoard, content: c }) }); bkbData.points.unshift({ id: p.id, content: c }); renderBkb(); } catch (err) { toast(err.message, true); }
    return;
  }
  const del = e.target.closest('[data-bpdel]');
  if (del) {
    try { await api('/api/boardkb/point/' + del.dataset.bpdel, { method: 'DELETE' }); bkbData.points = bkbData.points.filter(p => p.id != del.dataset.bpdel); renderBkb(); } catch (err) { toast(err.message, true); }
  }
});
