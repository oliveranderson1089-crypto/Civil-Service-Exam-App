'use strict';
const $ = (s) => document.querySelector(s);
const api = (u, o) => fetch(u, o).then(async r => {
  if (r.status === 401) { location.href = '/login'; throw new Error('未登录'); }
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('application/json')) {
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || '请求失败');
    return d;
  }
  if (!r.ok) throw new Error('请求失败');
  return r;
});

const PAGE_SIZE = 5;
const IN_APP = navigator.userAgent.includes('GongkaoApp');  // 安卓 APP 内打开
let state = { filter: 'all', q: '', items: [], page: 1, pages: 1 };
let preview = null;

function toast(msg, err) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (err ? ' err' : '');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.add('hidden'), 2200);
}

function esc(s) {
  return (s || '').replace(/[&<>"]/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/* ---------------- 查询预览 ---------------- */
async function doLookup() {
  const word = $('#word-input').value.trim();
  if (!word) { toast('请输入成语或词语', true); return; }
  $('#add-hint').textContent = '查询中…';
  try {
    const d = await api('/api/lookup?word=' + encodeURIComponent(word));
    preview = d;
    $('#pv-word').textContent = d.word;
    $('#pv-py').textContent = d.pinyin;
    $('#pv-cat').textContent = d.category;
    $('#pv-found').textContent = d.found ? '✓ 词典已收录' : '✎ 词典未收录，可手动补充';
    $('#pv-exp').value = d.explanation;
    $('#pv-der').value = d.derivation;
    $('#pv-exa').value = d.example;
    $('#pv-note').value = '';
    $('#pv-catsel').value = d.category;
    $('#pv-der-wrap').classList.toggle('hidden', !d.derivation && d.source !== 'idiom');
    $('#pv-exa-wrap').classList.toggle('hidden', !d.example && d.source !== 'idiom');
    $('#preview').classList.remove('hidden');
    $('#add-hint').textContent = '';
  } catch (e) {
    $('#add-hint').textContent = '';
    toast(e.message, true);
  }
}

async function doSave() {
  if (!preview) return;
  const body = {
    word: preview.word,
    pinyin: $('#pv-py').textContent,
    category: $('#pv-catsel').value,
    explanation: $('#pv-exp').value,
    derivation: $('#pv-der').value,
    example: $('#pv-exa').value,
    note: $('#pv-note').value,
  };
  try {
    await api('/api/entries', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    toast('已收录：' + preview.word);
    $('#word-input').value = '';
    $('#preview').classList.add('hidden');
    preview = null;
    state.page = 1;
    load();
    $('#word-input').focus();
  } catch (e) { toast(e.message, true); }
}

/* ---------------- 列表 ---------------- */
async function load() {
  let url = '/api/entries?page=' + state.page + '&page_size=' + PAGE_SIZE + '&';
  if (state.filter === '成语' || state.filter === '词语')
    url += 'category=' + encodeURIComponent(state.filter) + '&';
  if (state.filter === 'star') url += 'starred=1&';
  if (state.q) url += 'q=' + encodeURIComponent(state.q);
  try {
    const d = await api(url);
    state.items = d.items;
    state.page = d.page;
    state.pages = d.pages;
    $('#st-total').textContent = d.stats.total;
    $('#st-idiom').textContent = d.stats.idiom;
    $('#st-ci').textContent = d.stats.ci;
    $('#st-star').textContent = d.stats.starred;
    render();
    renderPager(d.total);
  } catch (e) { toast(e.message, true); }
}

function renderPager(total) {
  const pager = $('#pager');
  if (total <= PAGE_SIZE) { pager.classList.add('hidden'); return; }
  pager.classList.remove('hidden');
  $('#pg-info').textContent = `第 ${state.page} / ${state.pages} 页 · 共 ${total} 条`;
  $('#pg-prev').disabled = state.page <= 1;
  $('#pg-next').disabled = state.page >= state.pages;
}

function goPage(p) {
  if (p < 1 || p > state.pages || p === state.page) return;
  state.page = p;
  load();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function render() {
  const box = $('#list');
  if (!state.items.length) {
    box.innerHTML = '';
    $('#empty').classList.remove('hidden');
    $('#empty').textContent = (state.q || state.filter !== 'all')
      ? '没有符合条件的收录。' : '还没有收录内容，先在上面输入一个成语试试～';
    return;
  }
  $('#empty').classList.add('hidden');
  box.innerHTML = state.items.map(it => {
    const sub = [];
    if (it.derivation) sub.push(`<div class="item-sub"><b>出处</b> ${esc(it.derivation)}</div>`);
    if (it.example) sub.push(`<div class="item-sub"><b>例句</b> ${esc(it.example)}</div>`);
    return `<div class="item" data-id="${it.id}">
      <div class="item-actions">
        <button class="iconbtn star ${it.starred ? 'on' : ''}" data-act="star" title="收藏">${it.starred ? '★' : '☆'}</button>
        <button class="iconbtn" data-act="edit" title="编辑笔记">✎</button>
        <button class="iconbtn" data-act="del" title="删除">🗑</button>
      </div>
      <div class="item-head">
        <span class="item-word">${esc(it.word)}</span>
        <span class="item-py">${esc(it.pinyin)}</span>
        <span class="item-cat">${esc(it.category)}</span>
      </div>
      ${it.explanation ? `<div class="item-exp">${esc(it.explanation)}</div>` : ''}
      ${sub.join('')}
      ${it.note ? `<div class="item-note">📝 ${esc(it.note)}</div>` : ''}
    </div>`;
  }).join('');
}

async function onListClick(e) {
  const btn = e.target.closest('[data-act]');
  if (!btn) return;
  const id = btn.closest('.item').dataset.id;
  const it = state.items.find(x => x.id == id);
  if (btn.dataset.act === 'star') {
    try {
      await api('/api/entries/' + id, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ starred: !it.starred }),
      });
      load();
    } catch (err) { toast(err.message, true); }
  } else if (btn.dataset.act === 'del') {
    if (!confirm('删除「' + it.word + '」？')) return;
    try { await api('/api/entries/' + id, { method: 'DELETE' }); toast('已删除'); load(); }
    catch (err) { toast(err.message, true); }
  } else if (btn.dataset.act === 'edit') {
    const note = prompt('笔记（辨析 / 易混词 / 真题出处）：', it.note || '');
    if (note === null) return;
    try {
      await api('/api/entries/' + id, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note }),
      });
      load();
    } catch (err) { toast(err.message, true); }
  }
}

/* ---------------- 导出 ---------------- */
function openExport() { $('#export-modal').classList.remove('hidden'); }
function closeExport() { $('#export-modal').classList.add('hidden'); }

async function doExport() {
  const scope = $('#ex-scope').value;
  const mode = $('#ex-mode').value;
  const body = {
    mode,
    derivation: $('#ex-der').checked,
    example: $('#ex-exa').checked,
    note: $('#ex-note').checked,
  };
  if (scope === '成语' || scope === '词语') body.category = scope;
  else if (scope === 'star') body.starred = true;
  // scope==='all' 时跟随当前筛选
  else if (state.filter === '成语' || state.filter === '词语') body.category = state.filter;
  else if (state.filter === 'star') body.starred = true;

  // 安卓 APP 内：用 GET 链接触发系统下载器（WebView 无法处理 blob 下载）
  if (IN_APP) {
    const p = new URLSearchParams();
    p.set('mode', body.mode);
    p.set('der', body.derivation ? 1 : 0);
    p.set('exa', body.example ? 1 : 0);
    p.set('note', body.note ? 1 : 0);
    if (body.category) p.set('category', body.category);
    if (body.starred) p.set('starred', 1);
    closeExport();
    toast('正在导出 PDF…');
    window.location.href = '/api/export?' + p.toString();
    return;
  }

  try {
    const r = await fetch('/api/export', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(d.error || '导出失败');
    }
    const blob = await r.blob();
    const cd = r.headers.get('content-disposition') || '';
    let name = '公考积累.pdf';
    const m = cd.match(/filename\*=UTF-8''([^;]+)/);
    if (m) name = decodeURIComponent(m[1]);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1500);
    closeExport();
    toast('PDF 已生成');
  } catch (e) { toast(e.message, true); }
}

/* ---------------- 事件绑定 ---------------- */
$('#lookup-btn').onclick = doLookup;
$('#word-input').addEventListener('keydown', e => { if (e.key === 'Enter') doLookup(); });
$('#save-btn').onclick = doSave;
$('#list').addEventListener('click', onListClick);
$('#filters').addEventListener('click', e => {
  const c = e.target.closest('.chip'); if (!c) return;
  document.querySelectorAll('.chip').forEach(x => x.classList.remove('active'));
  c.classList.add('active');
  state.filter = c.dataset.f;
  state.page = 1;
  load();
});
let searchTimer;
$('#search').addEventListener('input', e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.q = e.target.value.trim(); state.page = 1; load(); }, 250);
});
$('#pg-prev').onclick = () => goPage(state.page - 1);
$('#pg-next').onclick = () => goPage(state.page + 1);
$('#logout-btn').onclick = async () => {
  if (!confirm('退出登录？')) return;
  try { await fetch('/logout', { method: 'POST' }); } catch (_) {}
  location.href = '/login';
};
$('#export-btn').onclick = openExport;
$('#ex-cancel').onclick = closeExport;
$('#ex-go').onclick = doExport;
$('#export-modal').addEventListener('click', e => {
  if (e.target.id === 'export-modal') closeExport();
});
// 默写版时禁用字段勾选
$('#ex-mode').addEventListener('change', e => {
  const recite = e.target.value === 'recite';
  $('#ex-fields').style.opacity = recite ? .4 : 1;
  $('#ex-fields').style.pointerEvents = recite ? 'none' : 'auto';
});

load();
$('#word-input').focus();

/* PWA */
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}
