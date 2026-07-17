/* 每日任务：自己给自己派的当日清单（任务清单页的一个 tab）
 *
 * 由 figures.js 拆出 —— 那个文件声明的职责是「资料分析的材料」，却另外装了
 * 每日测验的一半、每日任务、组队互监三摊东西。根子在拆 app.js 时照搬了它的旧区段
 * 边界，而那个边界本身就是错的（mods/dtest.py 的文件头写着同一句自白）。
 *
 * index.html 里的引入次序紧跟 figures.js，执行顺序与拆分前逐行一致。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, appConfirm, composing, esc, toast */
async function loadDaily() {
  $('#tk-daily-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/daily_tasks');
    $('#tk-daily-prog').textContent = d.total ? `今日进度 ${d.done_n} / ${d.total}${d.done_n === d.total ? ' 🎉 全部完成！' : ''}` : '';
    $('#tk-daily-list').innerHTML = d.items.length ? d.items.map(it => `
      <div class="tk-item ${it.done ? 'done' : ''}" data-td="${it.id}">
        <span class="tk-check">${it.done ? '✓' : ''}</span>
        <span class="tk-text">${esc(it.text)}</span>
        <button class="tk-del" data-tddel="${it.id}">🗑</button>
      </div>`).join('') : '<p class="empty">还没有每日任务，下面加一条吧～</p>';
  } catch (e) { $('#tk-daily-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function tdSetDone(it, on) {
  it.classList.toggle('done', on);
  const c = it.querySelector('.tk-check'); if (c) c.textContent = on ? '✓' : '';
}
function tdRecalcProg() {
  const items = [...$('#tk-daily-list').querySelectorAll('.tk-item')];
  const done = items.filter(x => x.classList.contains('done')).length;
  $('#tk-daily-prog').textContent = items.length
    ? `今日进度 ${done} / ${items.length}${done === items.length ? ' 🎉 全部完成！' : ''}` : '';
}
$('#tk-daily-list').addEventListener('click', async e => {
  const del = e.target.closest('[data-tddel]');
  if (del) { e.stopPropagation(); if (!(await appConfirm('删除这个每日任务？'))) return; try { await api('/api/daily_tasks/templates/' + del.dataset.tddel, { method: 'DELETE' }); loadDaily(); } catch (er) { toast(er.message, true); } return; }
  const it = e.target.closest('[data-td]'); if (!it) return;
  // 乐观更新：立刻翻勾 + 更新进度，后台再发请求；失败翻回来。不整表重渲 → 不卡顿、不回顶
  const was = it.classList.contains('done');
  tdSetDone(it, !was); tdRecalcProg();
  try {
    const d = await api('/api/daily_tasks/' + it.dataset.td + '/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    if (typeof d.done === 'boolean' && d.done !== !was) { tdSetDone(it, d.done); tdRecalcProg(); }
  } catch (er) { tdSetDone(it, was); tdRecalcProg(); toast(er.message, true); }
});
$('#tk-daily-add').onclick = async () => {
  const v = $('#tk-daily-in').value.trim(); if (!v) return;
  try { await api('/api/daily_tasks/templates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: v }) }); $('#tk-daily-in').value = ''; loadDaily(); } catch (e) { toast(e.message, true); }
};
$('#tk-daily-in').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') $('#tk-daily-add').click(); });
