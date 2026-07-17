/* 常识积累（7 板块 · 考情 + 高频考点）
 *
 * 由 app.js 按它自己的区段边界切出（原 L7064-7126）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, c, emKey, esc, push */

/* ============= 常识积累（7板块 · 考情 + 高频考点） ============= */
const CS_COLOR = { '人文常识': '#b23b2e', '科技常识': '#2b6fd6', '法律常识': '#8c2f24', '地理常识': '#0f766e', '经济常识': '#c2671f', '公文常识': '#7a5cc0', '管理常识': '#5a6b85' };
let csBoard = '', csTopic = '';
async function openChangshi() {
  push({ view: 'changshi', title: '常识积累' });
  $('#cs-tiers').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/changshi/boards');
    $('#cs-tiers').innerHTML = d.tiers.map(t => `
      <div class="cs-tier-name">${esc(t.name)}</div>
      <div class="home-cards cs-cards" data-dragsort="csb:${esc(t.name)}">${t.boards.map(b => `
        <div class="home-card" data-csb="${esc(b.name)}">
          <div class="hc-logo" style="background:${CS_COLOR[b.name] || '#666'}">${esc(b.name[0])}</div>
          <div class="hc-name">${esc(b.name)}</div>
          <div class="hc-desc">${b.topics} 个专题 · ${b.count} 条考点</div>
        </div>`).join('')}</div>`).join('');
  } catch (e) { $('#cs-tiers').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#cs-tiers').addEventListener('click', e => {
  const c = e.target.closest('[data-csb]'); if (c) openCsBoard(c.dataset.csb);
});
function openCsBoard(board) {
  csBoard = board; csTopic = '';
  push({ view: 'csboard', title: board });
  loadCsBoard();
}
async function loadCsBoard() {
  $('#cs-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/changshi/board?board=' + encodeURIComponent(csBoard) + '&topic=' + encodeURIComponent(csTopic));
    csTopic = d.topic;
    $('#top-title').textContent = csBoard;
    $('#cs-ov-body').innerHTML = emKey(d.overview);
    $('#cs-topics').innerHTML = d.topics.map(t =>
      `<button class="chip ${t.name === csTopic ? 'active' : ''}" data-cst="${esc(t.name)}">${esc(t.name)}${t.count ? ' ' + t.count : ''}</button>`).join('');
    const tm = d.topics.find(t => t.name === csTopic) || {};
    $('#cs-kaoqing').innerHTML = `
      <div class="cs-kq">
        ${tm.tezheng ? `<div class="cs-kq-row"><b>题型特征</b>${emKey(tm.tezheng)}</div>` : ''}
        ${tm.silu ? `<div class="cs-kq-row"><b>破题思路</b>${emKey(tm.silu)}</div>` : ''}
        ${tm.map ? `<div class="cs-kq-row cs-kq-map"><b>要点导图</b>${emKey(tm.map)}</div>` : ''}
      </div>`;
    if (!d.items.length) {
      $('#cs-list').innerHTML = '<p class="empty">' + (d.daily ? '考点生成中，每天还会自动新增～' : '考点生成中，稍后再来看看～') + '</p>';
      return;
    }
    $('#cs-list').innerHTML = d.items.map(it => `
      <div class="gk-card">
        <div class="gk-head"><span class="poly-badge" style="background:${CS_COLOR[csBoard] || '#666'}">${esc(it.title)}</span>
          <span class="cs-date">${esc(it.date || '')}${it.source === '新法跟踪' ? ' · 新法跟踪' : ''}</span></div>
        <div class="sc-body">${emKey(it.content)}</div>
      </div>`).join('');
  } catch (e) { $('#cs-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#cs-topics').addEventListener('click', e => {
  const c = e.target.closest('[data-cst]'); if (!c) return;
  csTopic = c.dataset.cst; loadCsBoard();
});
$('#cs-ov-toggle').onclick = () => {
  const b = $('#cs-ov-body'); b.classList.toggle('hidden');
  $('#cs-ov-toggle').querySelector('.cs-ov-arrow').textContent = b.classList.contains('hidden') ? '▾' : '▴';
};
