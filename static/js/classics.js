/* 古诗文速查（唐诗宋词 · 四书五经）
 *
 * 由 app.js 按它自己的区段边界切出（原 L2439-2630）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, artEm, c, errMsg, esc, libTouch, mdToHtml, push, stack, toast, uiError */

/* ================= 古诗文速查（唐诗宋词·四书五经） ================= */
const CLS_BADGE = { '唐诗': '#c0392b', '宋词': '#7b5ea7', '元曲': '#2c8c8c', '诗经': '#2f8060', '先秦': '#b08a1e', '汉魏六朝': '#8a6d3b', '明清': '#4a6785', '论语': '#1a6fb5', '孟子': '#1a6fb5', '大学': '#b08a1e', '中庸': '#b08a1e', '孙子兵法': '#9b2c22', '资治通鉴': '#5a4b8a', '增广贤文': '#2c7a5a' };
let clsState = { cat: '', q: '', star: false, page: 1, pages: 1 };
function openClassics() {
  clsState = { cat: '', q: '', star: false, page: 1, pages: 1 };
  $('#cls-input').value = '';
  push({ view: 'classics' });
  loadClsCats(); loadClassics(); loadClsDaily();
}
async function loadClsDaily() {
  try {
    const d = await api('/api/classics/daily');
    if (!d || d.error) { $('#cls-daily').classList.add('hidden'); return; }
    $('#cls-daily').innerHTML = `
      <div class="cd-daily-tag">${artEm('📖')} 每日一诗 · 申论 + 常识</div>
      <div class="cd-daily-title" data-clsopen="${d.id}">${esc(d.title)}<span class="cd-daily-meta">${esc((d.dynasty || '') + ' · ' + (d.author || ''))}</span></div>
      <div class="cd-daily-line">${esc(d.first_line || '')}</div>
      ${d.apply ? `<div class="cd-daily-apply"><b>申论运用</b> ${esc(d.apply)}</div>` : ''}
      ${d.common ? `<div class="cd-daily-apply cd-daily-common"><b>常识考点</b> ${esc(d.common)}</div>` : ''}`;
    $('#cls-daily').classList.remove('hidden');
  } catch (_) { $('#cls-daily').classList.add('hidden'); }
}
async function loadClsCats() {
  try {
    const d = await api('/api/classics/categories');
    const total = (d.categories || []).reduce((a, c) => a + c.count, 0);
    $('#cls-cats').innerHTML =
      `<button class="chip active" data-cc="">全部${total ? ' ' + total : ''}</button>` +
      `<button class="chip" data-cc="__star">★ 收藏${d.star_count ? ' ' + d.star_count : ''}</button>` +
      d.categories.map(c => `<button class="chip" data-cc="${esc(c.name)}">${esc(c.name)} ${c.count}</button>`).join('');
  } catch (e) { toast(errMsg(e), true); }
}
$('#cls-daily').addEventListener('click', e => {
  const t = e.target.closest('[data-clsopen]'); if (t) openClassicDetail(+t.dataset.clsopen);
});
$('#cls-cats').addEventListener('click', e => {
  const c = e.target.closest('[data-cc]'); if (!c) return;
  const v = c.dataset.cc;
  clsState.star = (v === '__star');
  clsState.cat = clsState.star ? '' : v;
  clsState.page = 1;
  document.querySelectorAll('#cls-cats .chip').forEach(x => x.classList.toggle('active', x.dataset.cc === v));
  loadClassics();
});
let clsTimer;
$('#cls-input').addEventListener('input', e => {
  clearTimeout(clsTimer);
  clsTimer = setTimeout(() => { clsState.q = e.target.value.trim(); clsState.page = 1; loadClassics(); }, 280);
});
async function loadClassics() {
  let url = '/api/classics?page=' + clsState.page;
  if (clsState.cat) url += '&category=' + encodeURIComponent(clsState.cat);
  if (clsState.q) url += '&q=' + encodeURIComponent(clsState.q);
  if (clsState.star) url += '&star=1';
  try {
    const d = await api(url);
    clsState.pages = d.pages;
    renderClassics(d.items, d.total);
  } catch (e) { toast(errMsg(e), true); }
}
function renderClassics(items, total) {
  const box = $('#cls-list');
  if (!items.length) {
    box.innerHTML = '';
    $('#cls-empty').classList.remove('hidden');
    $('#cls-empty').textContent = clsState.star ? '还没有收藏，点诗文右上角 ☆ 收藏'
      : (clsState.q ? '没有匹配「' + clsState.q + '」的诗文' : '暂无内容');
    $('#cls-pager').classList.add('hidden');
    return;
  }
  $('#cls-empty').classList.add('hidden');
  box.innerHTML = items.map(it => {
    const lines = (it.content || '').split('\n').map(l => `<div class="cls-line">${esc(l)}</div>`).join('');
    const meta = [it.author, it.dynasty, it.sub].filter(Boolean).join(' · ');
    return `<div class="cls-item" data-id="${it.id}">
      <div class="cls-head">
        <span class="cls-badge" style="background:${CLS_BADGE[it.category] || '#888'}">${esc(it.category)}</span>
        <span class="cls-title">${esc(it.title || '')}</span>
        <button class="cls-star ${it.starred ? 'on' : ''}" data-star="${it.id}" title="收藏">${it.starred ? '★' : '☆'}</button>
      </div>
      <div class="cls-body">${lines}</div>
      ${meta ? `<div class="cls-meta">${esc(meta)}</div>` : ''}
    </div>`;
  }).join('');
  box._items = items;
  const pager = $('#cls-pager');
  if (clsState.pages <= 1) { pager.classList.add('hidden'); }
  else {
    pager.classList.remove('hidden');
    $('#cls-info').textContent = '第 ' + clsState.page + ' / ' + clsState.pages + ' 页 · 共 ' + total + ' 条';
    $('#cls-prev').disabled = clsState.page <= 1;
    $('#cls-next').disabled = clsState.page >= clsState.pages;
  }
}
$('#cls-list').addEventListener('click', async e => {
  const s = e.target.closest('[data-star]');
  if (s) {
    const id = s.dataset.star;
    const on = !s.classList.contains('on');
    try {
      await api('/api/classics/' + id + '/star', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: on }) });
      s.classList.toggle('on', on); s.textContent = on ? '★' : '☆';
      const it = ($('#cls-list')._items || []).find(x => x.id == id); if (it) it.starred = on;
      if (clsState.star && !on) loadClassics();   // 收藏页里取消收藏即移除
    } catch (err) { toast(errMsg(err), true); }
    return;
  }
  const card = e.target.closest('.cls-item'); if (!card) return;
  openClassicDetail(+card.dataset.id);
});

/* ---- 古诗文详情：拼音 / 译文 / 赏析 / AI 讲解 ---- */
let cdData = null;
async function openClassicDetail(id) {
  libTouch('classic', id);
  push({ view: 'cdetail', title: '古诗文' });
  $('#cd-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/classics/' + id + '/detail');
    cdData = d;
    stack[stack.length - 1].title = d.title;
    $('#top-title').textContent = d.title;
    renderCDetail();
  } catch (e) { $('#cd-wrap').innerHTML = uiError(e); }
}
function renderCDetail() {
  const d = cdData;
  const meta = [d.dynasty, d.author, d.sub].filter(Boolean).join(' · ');
  const body = d.lines.map((ln, i) => {
    if (!ln.trim()) return '';
    return `<div class="cd-line"><div class="cd-py">${esc(d.pinyin[i] || '')}</div><div class="cd-han">${esc(ln)}</div></div>`;
  }).join('');
  // AI 讲解一旦生成，即替换掉开源译文/赏析；未生成时才展示开源资源
  const hasAI = !!d.ai_explain;
  let res = '';
  if (!hasAI) {
    if (d.translation) res += `<div class="cd-sec"><div class="cd-sec-t">译文</div><div class="cd-sec-b">${esc(d.translation).replace(/\n/g, '<br>')}</div></div>`;
    if (d.appreciation) res += `<div class="cd-sec"><div class="cd-sec-t">赏析</div><div class="cd-sec-b">${esc(d.appreciation).replace(/\n/g, '<br>')}</div></div>`;
  }
  const aiBox = hasAI
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">AI 讲解</div><div class="cd-sec-b">${mdToHtml(d.ai_explain)}</div>
        <button class="btn cd-ai-regen" id="cd-ai-regen">重新生成</button></div>`
    : `<button class="btn primary cd-ai-btn" id="cd-ai-btn">${artEm('🤖')} AI 讲解${(d.translation || d.appreciation) ? '（生成后替换开源译文/赏析）' : ''}</button>`;
  $('#cd-wrap').innerHTML = `
    <div class="cd-head">
      <span class="cls-badge" style="background:${CLS_BADGE[d.category] || '#888'}">${esc(d.category)}</span>
      <h2 class="cd-title">${esc(d.title)}</h2>
      <button class="cls-star ${d.starred ? 'on' : ''}" id="cd-star">${d.starred ? '★' : '☆'}</button>
    </div>
    <div class="cd-meta">${esc(meta)}</div>
    <div class="cd-body">${body}</div>
    ${res || (hasAI ? '' : '<p class="cd-tip">这篇暂无现成译文，可点下面让 AI 讲解。</p>')}
    ${aiBox}`;
}
$('#cd-wrap').addEventListener('click', async e => {
  if (e.target.closest('#cd-star')) {
    const on = !cdData.starred;
    try { await api('/api/classics/' + cdData.id + '/star', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: on }) }); cdData.starred = on; renderCDetail(); } catch (err) { toast(errMsg(err), true); }
    return;
  }
  const gen = e.target.closest('#cd-ai-btn') || e.target.closest('#cd-ai-regen');
  if (gen) {
    const regen = gen.id === 'cd-ai-regen';
    gen.disabled = true; gen.textContent = 'AI 生成中…（约十几秒）';
    try {
      const d = await api('/api/classics/' + cdData.id + '/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: regen }) });
      cdData.ai_explain = d.content; renderCDetail();
    } catch (err) { toast(errMsg(err), true); gen.disabled = false; gen.textContent = '🤖 AI 讲解'; }
  }
});

/* ---- 导出 PDF ---- */
$('#cls-export').onclick = () => {
  const scopes = [['cur', '当前筛选']];
  scopes.push(['star', '仅收藏']);
  $('#clsx-scope').innerHTML = scopes.map(s => `<option value="${s[0]}">${s[1]}</option>`).join('');
  $('#clsx-modal').classList.remove('hidden');
};
$('#clsx-cancel').onclick = () => $('#clsx-modal').classList.add('hidden');
$('#clsx-modal').addEventListener('click', e => { if (e.target.id === 'clsx-modal') $('#clsx-modal').classList.add('hidden'); });
$('#clsx-go').onclick = () => {
  const scope = $('#clsx-scope').value;
  const p = new URLSearchParams();
  p.set('py', $('#clsx-py').checked ? 1 : 0);
  p.set('tr', $('#clsx-tr').checked ? 1 : 0);
  if (scope === 'star' || clsState.star) p.set('star', 1);
  if (scope !== 'star') { if (clsState.cat) p.set('category', clsState.cat); if (clsState.q) p.set('q', clsState.q); }
  $('#clsx-modal').classList.add('hidden'); toast('正在导出 PDF…');
  window.location.href = '/api/classics/export?' + p.toString();
};
$('#cls-prev').onclick = () => { if (clsState.page > 1) { clsState.page--; loadClassics(); window.scrollTo({ top: 0 }); } };
$('#cls-next').onclick = () => { if (clsState.page < clsState.pages) { clsState.page++; loadClassics(); window.scrollTo({ top: 0 }); } };
