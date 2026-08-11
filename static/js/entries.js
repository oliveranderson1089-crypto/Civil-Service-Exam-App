/* 成语 / 词语积累
 *
 * 由 app.js 按它自己的区段边界切出（原 L1717-1904）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, IN_APP, PAGE_SIZE, api, appConfirm, artEm, c, composing, esc, push, toast */

/* ================= 成语 / 词语 ================= */
let state = { filter: 'all', q: '', items: [], page: 1, pages: 1 };
let preview = null;
function openIdiom() {
  state = { filter: 'all', q: '', items: [], page: 1, pages: 1 };
  $('#word-input').value = ''; $('#preview').classList.add('hidden'); $('#search').value = ''; preview = null;
  document.querySelectorAll('#filters .chip').forEach(x => x.classList.toggle('active', x.dataset.f === 'all'));
  push({ view: 'idiom' });
  loadEntries();
}
async function doLookup() {
  const word = $('#word-input').value.trim();
  if (!word) { toast('请输入成语或词语', true); return; }
  $('#add-hint').textContent = '查询中…';
  try {
    const d = await api('/api/lookup?word=' + encodeURIComponent(word));
    preview = d;
    $('#pv-word').textContent = d.word; $('#pv-py').textContent = d.pinyin; $('#pv-cat').textContent = d.category;
    $('#pv-found').textContent = d.found ? (d.source === 'ai' ? '✓ AI 已解释并收录' : '✓ 词典已收录') : '✎ 词典未收录，可 AI 解释或手动补充';
    $('#pv-exp').value = d.explanation; $('#pv-der').value = d.derivation; $('#pv-exa').value = d.example;
    $('#pv-note').value = ''; $('#pv-catsel').value = d.category;
    $('#pv-der-wrap').classList.toggle('hidden', !d.derivation && d.source !== 'idiom');
    $('#pv-exa-wrap').classList.toggle('hidden', !d.example && d.source !== 'idiom');
    // AI 生成按钮始终显示：未解释过=「AI 解释并收录」，已解释过=「AI 重新生成」，均可反复点
    $('#pv-ai').classList.remove('hidden');
    $('#pv-ai').textContent = d.found ? '🤖 AI 重新生成' : '🤖 AI 解释并收录';
    $('#preview').classList.remove('hidden'); $('#add-hint').textContent = '';
  } catch (e) { $('#add-hint').textContent = ''; toast(e.message, true); }
}
async function doAiExplain() {
  if (!preview || !preview.word) return;
  const btn = $('#pv-ai');
  const regen = !!preview.found;  // 已解释过 → 本次是「重新生成」
  btn.disabled = true; btn.textContent = regen ? '🤖 重新生成中…' : '🤖 AI 解释中…';
  try {
    const d = await api('/api/lookup/ai', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ word: preview.word, category: $('#pv-catsel').value, force: true }),
    });
    preview.explanation = d.explanation; preview.pinyin = d.pinyin;
    preview.category = d.category; preview.found = true; preview.source = 'ai';
    preview.derivation = d.derivation || ''; preview.example = d.example || '';
    $('#pv-exp').value = d.explanation; $('#pv-py').textContent = d.pinyin;
    $('#pv-cat').textContent = d.category; $('#pv-catsel').value = d.category;
    $('#pv-der').value = d.derivation || ''; $('#pv-exa').value = d.example || '';
    $('#pv-der-wrap').classList.toggle('hidden', !d.derivation);
    $('#pv-exa-wrap').classList.toggle('hidden', !d.example);
    $('#pv-found').textContent = '✓ AI 已解释并收录';
    // 不隐藏按钮：不满意可反复重新生成
    toast(regen ? '已重新生成，不满意可再次点击' : '已解释并收录进词库，以后可直接查到');
    if (regen) loadEntries();  // 已收录的同名词条已被后端同步刷新，重载列表
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = (preview && preview.found) ? '🤖 AI 重新生成' : '🤖 AI 解释并收录'; }
}
async function doSave() {
  if (!preview) return;
  try {
    await api('/api/entries', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        word: preview.word, pinyin: $('#pv-py').textContent, category: $('#pv-catsel').value,
        explanation: $('#pv-exp').value, derivation: $('#pv-der').value, example: $('#pv-exa').value, note: $('#pv-note').value,
      }),
    });
    toast('已收录：' + preview.word);
    $('#word-input').value = ''; $('#preview').classList.add('hidden'); preview = null;
    state.page = 1; loadEntries(); $('#word-input').focus();
  } catch (e) { toast(e.message, true); }
}
async function loadEntries() {
  let url = '/api/entries?page=' + state.page + '&page_size=' + PAGE_SIZE + '&';
  if (state.filter === '成语' || state.filter === '词语' || state.filter === '词组') url += 'category=' + encodeURIComponent(state.filter) + '&';
  if (state.filter === 'star') url += 'starred=1&';
  if (state.q) url += 'q=' + encodeURIComponent(state.q);
  try {
    const d = await api(url);
    state.items = d.items; state.page = d.page; state.pages = d.pages;
    renderEntries(); renderPager(d.total);
  } catch (e) { toast(e.message, true); }
}
function renderEntries() {
  const box = $('#list');
  if (!state.items.length) {
    box.innerHTML = ''; $('#empty').classList.remove('hidden');
    $('#empty').textContent = (state.q || state.filter !== 'all') ? '没有符合条件的收录。' : '还没有收录，输入一个成语试试～';
    return;
  }
  $('#empty').classList.add('hidden');
  box.innerHTML = state.items.map(it => {
    const sub = [];
    if (it.derivation) sub.push(`<div class="item-sub"><b>出处</b> ${esc(it.derivation)}</div>`);
    if (it.example) sub.push(`<div class="item-sub"><b>例句</b> ${esc(it.example)}</div>`);
    return `<div class="item" data-id="${it.id}">
      <div class="item-actions">
        <button class="iconbtn star ${it.starred ? 'on' : ''}" data-act="star">${it.starred ? '★' : '☆'}</button>
        <button class="iconbtn" data-act="edit">✎</button><button class="iconbtn" data-act="del">🗑</button>
      </div>
      <div class="item-head"><span class="item-word">${esc(it.word)}</span>
        <span class="item-py">${esc(it.pinyin)}</span><span class="item-cat">${esc(it.category)}</span></div>
      ${it.explanation ? `<div class="item-exp">${esc(it.explanation)}</div>` : ''}
      ${sub.join('')}${it.note ? `<div class="item-note">${artEm('📝')} ${esc(it.note)}</div>` : ''}
    </div>`;
  }).join('');
}
function renderPager(total) {
  const pager = $('#pager');
  if (total <= PAGE_SIZE) { pager.classList.add('hidden'); return; }
  pager.classList.remove('hidden');
  $('#pg-info').textContent = `第 ${state.page} / ${state.pages} 页 · 共 ${total} 条`;
  $('#pg-prev').disabled = state.page <= 1; $('#pg-next').disabled = state.page >= state.pages;
}
function goPage(p) { if (p < 1 || p > state.pages || p === state.page) return; state.page = p; loadEntries(); window.scrollTo({ top: 0, behavior: 'smooth' }); }
// 应用内笔记编辑弹窗（替代原生 prompt），返回 Promise<string|null>（取消为 null）
function editNote(title, value) {
  return new Promise(resolve => {
    const modal = $('#note-modal'), input = $('#note-modal-input');
    $('#note-modal-title').textContent = title;
    input.value = value || '';
    modal.classList.remove('hidden');
    setTimeout(() => { input.focus(); }, 50);
    const done = (val) => {
      modal.classList.add('hidden');
      $('#note-modal-save').onclick = $('#note-modal-cancel').onclick = modal.onclick = null;
      resolve(val);
    };
    $('#note-modal-save').onclick = () => done(input.value);
    $('#note-modal-cancel').onclick = () => done(null);
    modal.onclick = (e) => { if (e.target === modal) done(null); };  // 点遮罩取消
  });
}
$('#list').addEventListener('click', async e => {
  const btn = e.target.closest('[data-act]'); if (!btn) return;
  const id = btn.closest('.item').dataset.id;
  const it = state.items.find(x => x.id == id);
  if (btn.dataset.act === 'star') {
    try { await api('/api/entries/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: !it.starred }) }); loadEntries(); } catch (err) { toast(err.message, true); }
  } else if (btn.dataset.act === 'del') {
    if (!(await appConfirm('删除「' + it.word + '」？'))) return;
    try { await api('/api/entries/' + id, { method: 'DELETE' }); toast('已删除'); loadEntries(); } catch (err) { toast(err.message, true); }
  } else if (btn.dataset.act === 'edit') {
    const note = await editNote('「' + it.word + '」的笔记', it.note || '');
    if (note === null) return;
    try { await api('/api/entries/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }) }); toast('已保存'); loadEntries(); } catch (err) { toast(err.message, true); }
  }
});
$('#lookup-btn').onclick = doLookup;
$('#pv-ai').onclick = doAiExplain;
$('#word-input').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') doLookup(); });
$('#save-btn').onclick = doSave;
$('#filters').addEventListener('click', e => {
  const c = e.target.closest('.chip'); if (!c) return;
  document.querySelectorAll('#filters .chip').forEach(x => x.classList.remove('active'));
  c.classList.add('active'); state.filter = c.dataset.f; state.page = 1; loadEntries();
});
let searchTimer;
$('#search').addEventListener('input', e => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.q = e.target.value.trim(); state.page = 1; loadEntries(); }, 250); });
$('#pg-prev').onclick = () => goPage(state.page - 1);
$('#pg-next').onclick = () => goPage(state.page + 1);
/* 导出 PDF */
$('#export-btn').onclick = () => $('#export-modal').classList.remove('hidden');
$('#ex-cancel').onclick = () => $('#export-modal').classList.add('hidden');
$('#export-modal').addEventListener('click', e => { if (e.target.id === 'export-modal') $('#export-modal').classList.add('hidden'); });
$('#ex-mode').addEventListener('change', e => { const r = e.target.value === 'recite'; $('#ex-fields').style.opacity = r ? .4 : 1; $('#ex-fields').style.pointerEvents = r ? 'none' : 'auto'; });
$('#ex-go').onclick = async () => {
  const scope = $('#ex-scope').value, mode = $('#ex-mode').value;
  const body = { mode, derivation: $('#ex-der').checked, example: $('#ex-exa').checked, note: $('#ex-note').checked };
  if (scope === '成语' || scope === '词语' || scope === '词组') body.category = scope;
  else if (scope === 'star') body.starred = true;
  else if (state.filter === '成语' || state.filter === '词语' || state.filter === '词组') body.category = state.filter;
  else if (state.filter === 'star') body.starred = true;
  if (IN_APP) {
    const p = new URLSearchParams();
    p.set('mode', body.mode); p.set('der', body.derivation ? 1 : 0); p.set('exa', body.example ? 1 : 0); p.set('note', body.note ? 1 : 0);
    if (body.category) p.set('category', body.category); if (body.starred) p.set('starred', 1);
    $('#export-modal').classList.add('hidden'); toast('正在导出 PDF…');
    window.location.href = '/api/export?' + p.toString(); return;
  }
  try {
    const r = await fetch('/api/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.error || '导出失败'); }
    const blob = await r.blob(); const cd = r.headers.get('content-disposition') || '';
    let name = '公考积累.pdf'; const m = cd.match(/filename\*=UTF-8''([^;]+)/); if (m) name = decodeURIComponent(m[1]);
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1500);
    $('#export-modal').classList.add('hidden'); toast('PDF 已生成');
  } catch (e) { toast(e.message, true); }
};
