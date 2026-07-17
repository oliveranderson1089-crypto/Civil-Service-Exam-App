/* 错题本
 *
 * 由 app.js 按它自己的区段边界切出（原 L3089-3240）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, appConfirm, back, c, esc,
   push, toast */

/* ================= 错题本 ================= */
const WQ_BOARDS = ['常识判断', '资料分析', '判断推理', '数量关系', '政治理论', '言语理解与表达', '申论'];
let wqState = { board: '', q: '', star: false, page: 1, pages: 1 };
function openWrongq() {
  wqState = { board: '', q: '', star: false, page: 1, pages: 1 };
  $('#wq-input').value = '';
  push({ view: 'wrongq' });
  loadWqBoards(); loadWrongq();
}
async function loadWqBoards() {
  try {
    const d = await api('/api/wrongq/boards');
    $('#wq-cats').innerHTML =
      `<button class="chip active" data-wc="">全部${d.total ? ' ' + d.total : ''}</button>` +
      `<button class="chip" data-wc="__star">★ 收藏${d.star ? ' ' + d.star : ''}</button>` +
      d.boards.map(b => `<button class="chip" data-wc="${esc(b.name)}">${esc(b.name)} ${b.count}</button>`).join('');
  } catch (_) { /* 分类拉不到就先空着，下次进来会重试 */ }
}
$('#wq-cats').addEventListener('click', e => {
  const c = e.target.closest('[data-wc]'); if (!c) return;
  const v = c.dataset.wc; wqState.star = (v === '__star'); wqState.board = wqState.star ? '' : v; wqState.page = 1;
  document.querySelectorAll('#wq-cats .chip').forEach(x => x.classList.toggle('active', x.dataset.wc === v));
  loadWrongq();
});
let wqTimer;
$('#wq-input').addEventListener('input', e => { clearTimeout(wqTimer); wqTimer = setTimeout(() => { wqState.q = e.target.value.trim(); wqState.page = 1; loadWrongq(); }, 280); });
async function loadWrongq() {
  let url = '/api/wrongq?page=' + wqState.page;
  if (wqState.board) url += '&board=' + encodeURIComponent(wqState.board);
  if (wqState.q) url += '&q=' + encodeURIComponent(wqState.q);
  if (wqState.star) url += '&star=1';
  try { const d = await api(url); wqState.pages = d.pages; renderWq(d.items, d.total); } catch (e) { toast(e.message, true); }
}
function renderWq(items, total) {
  const box = $('#wq-list');
  if (!items.length) {
    box.innerHTML = ''; $('#wq-empty').classList.remove('hidden');
    $('#wq-empty').textContent = wqState.star ? '还没有收藏的错题' : (wqState.q ? '没有匹配的错题' : '还没有错题，点右下角 ＋ 记录第一道');
    $('#wq-pager').classList.add('hidden'); return;
  }
  $('#wq-empty').classList.add('hidden');
  box.innerHTML = items.map(w => `
    <div class="wq-item" data-id="${w.id}">
      <div class="wq-head">
        ${w.qtype ? `<span class="wq-type">${esc(w.qtype)}</span>` : ''}
        ${w.board ? `<span class="wq-board">${esc(w.board)}</span>` : ''}
        <button class="cls-star ${w.starred ? 'on' : ''}" data-wqstar="${w.id}">${w.starred ? '★' : '☆'}</button>
      </div>
      <div class="wq-q">${esc((w.question || '（图片题）').slice(0, 80))}</div>
    </div>`).join('');
  box._items = items;
  const p = $('#wq-pager');
  if (wqState.pages <= 1) p.classList.add('hidden');
  else { p.classList.remove('hidden'); $('#wq-info').textContent = '第 ' + wqState.page + ' / ' + wqState.pages + ' 页 · 共 ' + total + ' 道'; $('#wq-prev').disabled = wqState.page <= 1; $('#wq-next').disabled = wqState.page >= wqState.pages; }
}
$('#wq-list').addEventListener('click', async e => {
  const s = e.target.closest('[data-wqstar]');
  if (s) {
    const id = s.dataset.wqstar; const on = !s.classList.contains('on');
    try { await api('/api/wrongq/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: on }) }); s.classList.toggle('on', on); s.textContent = on ? '★' : '☆'; if (wqState.star && !on) loadWrongq(); } catch (err) { toast(err.message, true); }
    return;
  }
  const card = e.target.closest('.wq-item'); if (card) openWqDetail(+card.dataset.id);
});
$('#wq-prev').onclick = () => { if (wqState.page > 1) { wqState.page--; loadWrongq(); window.scrollTo({ top: 0 }); } };
$('#wq-next').onclick = () => { if (wqState.page < wqState.pages) { wqState.page++; loadWrongq(); window.scrollTo({ top: 0 }); } };
$('#wq-fab').onclick = openWqAdd;

/* 新增错题 */
let wqImgFile = null;
function openWqAdd() {
  wqImgFile = null;
  $('#wqa-q').value = ''; $('#wqa-a').value = ''; $('#wqa-imgprev').innerHTML = '';
  $('#wqa-board').innerHTML = '<option value="">（自动判断）</option>' + WQ_BOARDS.map(b => `<option>${b}</option>`).join('');
  $('#wqa-go').disabled = false; $('#wqa-go').textContent = '🤖 AI 分析并收录';
  push({ view: 'wqadd' });
}
async function wqOcrFill(file) {
  wqImgFile = file;
  $('#wqa-imgprev').innerHTML = `<img src="${URL.createObjectURL(file)}"><span>已附题目图片</span>`;
  toast('识别中…');
  const fd = new FormData(); fd.append('file', file);
  try {
    const d = await api('/api/ocr', { method: 'POST', body: fd });
    if (d.text) { const cur = $('#wqa-q').value.trim(); $('#wqa-q').value = cur ? cur + '\n' + d.text : d.text; toast('已识别，可修正'); }
    else toast('没识别到文字，可手动输入', true);
  } catch (e) { toast(e.message, true); }
}
$('#wqa-cam').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; if (f) wqOcrFill(f); });
$('#wqa-img').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; if (f) wqOcrFill(f); });
$('#wqa-go').onclick = async () => {
  const q = $('#wqa-q').value.trim();
  if (!q && !wqImgFile) { toast('请输入题目或拍照', true); return; }
  const fd = new FormData();
  fd.append('question', q); fd.append('answer', $('#wqa-a').value.trim()); fd.append('board', $('#wqa-board').value);
  if (wqImgFile) fd.append('image', wqImgFile);
  $('#wqa-go').disabled = true; $('#wqa-go').textContent = 'AI 分析中…（约十几秒）';
  try { const w = await api('/api/wrongq', { method: 'POST', body: fd }); toast('已收录'); back(); openWqDetail(w.id); }
  catch (e) { toast(e.message, true); $('#wqa-go').disabled = false; $('#wqa-go').textContent = '🤖 AI 分析并收录'; }
};

/* 错题详情 */
let wqData = null;
async function openWqDetail(id) {
  push({ view: 'wqdetail' });
  $('#wqd-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try { wqData = await api('/api/wrongq/' + id); renderWqDetail(); } catch (e) { $('#wqd-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function wqSec(t, v) { return v ? `<div class="cd-sec"><div class="cd-sec-t">${t}</div><div class="cd-sec-b">${esc(v).replace(/\n/g, '<br>')}</div></div>` : ''; }
function renderWqDetail() {
  const w = wqData;
  $('#wqd-wrap').innerHTML = `
    <div class="wqd-head">
      ${w.qtype ? `<span class="wq-type">${esc(w.qtype)}</span>` : ''}
      ${w.board ? `<span class="wq-board">${esc(w.board)}</span>` : ''}
      <button class="cls-star ${w.starred ? 'on' : ''}" id="wqd-star">${w.starred ? '★' : '☆'}</button>
    </div>
    <div class="cd-sec"><div class="cd-sec-t">题目</div><div class="cd-sec-b wqd-q">${esc(w.question).replace(/\n/g, '<br>') || '（见图）'}</div>
      ${w.image ? `<img class="wqd-img" src="${w.image}">` : ''}</div>
    ${w.answer ? wqSec('我的答案 / 解析', w.answer) : ''}
    ${wqSec('知识点', w.points)}
    ${wqSec('公式 / 方法', w.method)}
    ${wqSec('解题技巧', w.skill)}
    ${wqSec('解题步骤', w.steps)}
    <div class="cd-sec"><div class="cd-sec-t">我的笔记</div>
      <textarea id="wqd-note" class="wqd-note" placeholder="记录易错点、复盘…">${esc(w.note)}</textarea>
      <button class="btn" id="wqd-savenote" style="margin-top:8px;">保存笔记</button></div>
    <div class="wqd-acts">
      <button class="btn" id="wqd-reanalyze">🤖 重新分析</button>
      <button class="btn" id="wqd-del" style="color:#e0524d;border-color:#f0c9c6;">删除</button>
    </div>`;
}
$('#wqd-wrap').addEventListener('click', async e => {
  if (e.target.closest('#wqd-star')) {
    const on = !wqData.starred;
    try { await api('/api/wrongq/' + wqData.id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: on }) }); wqData.starred = on; renderWqDetail(); } catch (err) { toast(err.message, true); } return;
  }
  if (e.target.closest('#wqd-savenote')) {
    const note = $('#wqd-note').value;
    try { await api('/api/wrongq/' + wqData.id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }) }); wqData.note = note; toast('已保存'); } catch (err) { toast(err.message, true); } return;
  }
  const rb = e.target.closest('#wqd-reanalyze');
  if (rb) {
    rb.disabled = true; rb.textContent = '分析中…';
    try { wqData = await api('/api/wrongq/' + wqData.id + '/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); renderWqDetail(); toast('已更新'); } catch (err) { toast(err.message, true); rb.disabled = false; rb.textContent = '🤖 重新分析'; } return;
  }
  if (e.target.closest('#wqd-del')) {
    if (!(await appConfirm('删除这道错题？'))) return;
    try { await api('/api/wrongq/' + wqData.id, { method: 'DELETE' }); toast('已删除'); back(); loadWrongq(); loadWqBoards(); } catch (err) { toast(err.message, true); } return;
  }
});
