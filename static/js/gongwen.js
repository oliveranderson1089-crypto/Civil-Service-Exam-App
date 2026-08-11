/* 应用文上位词（公文规范表述）
 *
 * 由 app.js 按它自己的区段边界切出（原 L3983-4029）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, appConfirm, artEm, esc, push, toast */

/* ============= 应用文 · 应用文上位词（公文规范上位表述，按场景归类） ============= */
function gwCard(it) {
  const chips = (it.phrases || '').split(/[、,，]/).map(s => s.trim()).filter(Boolean)
    .map(p => `<span class="gw-chip">${esc(p)}</span>`).join('');
  return `<div class="gw-card">
    <div class="gw-top"><span class="gw-scene">${esc(it.scene)}</span>
      ${it.doctype ? `<span class="gw-doc">${esc(it.doctype)}</span>` : ''}
      ${it.source === 'ai' ? `<button class="gw-del" data-gwdel="${it.id}" title="删除">${artEm('✕')}</button>` : ''}</div>
    <div class="gw-chips">${chips}</div>
    ${it.note ? `<div class="gw-note">${artEm('💡')} ${esc(it.note)}</div>` : ''}
    ${it.example ? `<div class="gw-eg"><span class="gw-lab">示范</span>${esc(it.example)}</div>` : ''}
  </div>`;
}
async function loadGongwen(q) {
  $('#gw-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/gongwen' + (q ? '?q=' + encodeURIComponent(q) : ''));
    if (!d.items.length) { $('#gw-list').innerHTML = '<p class="empty">没有匹配的场景，换个词试试～</p>'; return; }
    $('#gw-list').innerHTML = d.items.map(gwCard).join('');
  } catch (e) { $('#gw-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function openGongwen() { push({ view: 'gongwen', title: '应用文上位词' }); $('#gw-in').value = ''; $('#gw-q').value = ''; loadGongwen(); }
let gwTimer = null;
$('#gw-q').addEventListener('input', e => {
  clearTimeout(gwTimer);
  gwTimer = setTimeout(() => loadGongwen(e.target.value.trim()), 250);
});
$('#gw-ask').onclick = async () => {
  const text = $('#gw-in').value.trim();
  if (!text) { toast('先输入一句口语或一个场景', true); return; }
  $('#gw-ask').disabled = true; $('#gw-ask').textContent = '归纳中…';
  try {
    await api('/api/gongwen/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ input: text }) });
    $('#gw-in').value = ''; $('#gw-q').value = '';
    toast('已归纳并收录到最前面');
    await loadGongwen();
    $('#gw-list').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) { toast(e.message, true); }
  $('#gw-ask').disabled = false; $('#gw-ask').textContent = 'AI 归纳';
};
$('#gw-list').addEventListener('click', async e => {
  const d = e.target.closest('[data-gwdel]'); if (!d) return;
  if (!(await appConfirm('删除这条 AI 归纳的场景？'))) return;
  try { await api('/api/gongwen/' + d.dataset.gwdel, { method: 'DELETE' }); loadGongwen($('#gw-q').value.trim()); }
  catch (err) { toast(err.message, true); }
});
