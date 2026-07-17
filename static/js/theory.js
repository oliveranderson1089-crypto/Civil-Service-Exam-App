/* 理论基础（马原 / 毛概 / 中特 / 习思想）
 *
 * 由 app.js 按它自己的区段边界切出（原 L6685-6720）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, IC, api, c, emKey, esc,
   push */

/* ================= 理论基础（马原/毛概/中特/习思想） ================= */
async function openTheory() {
  push({ view: 'theory', title: '理论基础' });
  $('#th-boards').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/theory/boards');
    $('#th-boards').innerHTML = '<div class="home-cards cs-cards" data-dragsort="thb">' + d.boards.map(b => `
      <div class="home-card ck-card" data-thb="${esc(b.name)}">
        <div class="hc-logo hc-th">${IC[b.icon] || IC.book}</div>
        <div class="hc-name">${esc(b.short)}</div>
        <div class="hc-desc">${b.count} 条 · ${esc(b.desc)}</div>
      </div>`).join('') + '</div>';
  } catch (e) { $('#th-boards').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#th-boards').addEventListener('click', e => {
  const c = e.target.closest('[data-thb]'); if (c) openThBoard(c.dataset.thb);
});
async function openThBoard(name) {
  push({ view: 'thboard', title: name.length > 10 ? name.slice(0, 9) + '…' : name });
  $('#thb-head').innerHTML = ''; $('#thb-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/theory/items?board=' + encodeURIComponent(name));
    $('#thb-head').innerHTML = `<div class="thb-title">${esc(name)}</div>
      <div class="thb-desc">${esc(d.desc || '')}</div><span class="ckb-n">${d.count} 个考点</span>`;
    if (!d.topics.length) { $('#thb-list').innerHTML = '<p class="empty">内容生成中，稍后再来～</p>'; return; }
    $('#thb-list').innerHTML = d.topics.map(t => `
      <div class="th-topic"><div class="th-tname">${esc(t.name)}</div>
        ${t.items.map(it => `<div class="gk-card th-item">
          <div class="cki-t">${esc(it.title)}</div>
          <div class="cki-c">${emKey(it.content || '')}</div>
        </div>`).join('')}
      </div>`).join('');
  } catch (e) { $('#thb-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
