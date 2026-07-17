/* 云盘
 *
 * 由 app.js 按它自己的区段边界切出（原 L7320-7411）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, KB, api, appConfirm, appPrompt, esc,
   push, toast */

/* ================= 云盘 ================= */
let dvFolder = '';
const FILE_ICON = { pdf: '📕', doc: '📘', docx: '📘', xls: '📗', xlsx: '📗', ppt: '📙', pptx: '📙',
  png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', webp: '🖼️', apk: '📦', exe: '📦', dmg: '📦',
  zip: '🗜️', rar: '🗜️', '7z': '🗜️', mp4: '🎬', mp3: '🎵', txt: '📄', md: '📄', html: '🌐' };
const dvIcon = e => FILE_ICON[(e || '').replace('.', '').toLowerCase()] || '📎';
function fSize(n) { n = n || 0; return n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB'; }
function openDrive() { dvFolder = ''; push({ view: 'drive', title: '云盘' }); loadDrive(); }
async function loadDrive() {
  $('#dv-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/drive?folder=' + encodeURIComponent(dvFolder));
    $('#dv-used').textContent = '已用 ' + fSize(d.used);
    // 面包屑
    const parts = dvFolder ? dvFolder.split('/') : [];
    let acc = '';
    $('#dv-crumb').innerHTML = `<a data-dvcd="">☁️ 云盘</a>` + parts.map(p => {
      acc = acc ? acc + '/' + p : p; return ` / <a data-dvcd="${esc(acc)}">${esc(p)}</a>`;
    }).join('');
    if (!d.items.length) { $('#dv-list').innerHTML = '<p class="empty">这个文件夹是空的。上传文件，或新建文件夹。</p>'; return; }
    $('#dv-list').innerHTML = d.items.map(it => it.is_dir
      ? `<div class="dv-item dv-dir" data-dvopen="${esc((dvFolder ? dvFolder + '/' : '') + it.name)}">
           <span class="dv-ic">📁</span><span class="dv-name">${esc(it.name)}</span>
           <button class="dv-del" data-dvdel="${it.id}" title="删除">🗑</button></div>`
      : `<div class="dv-item">
           <span class="dv-ic">${dvIcon(it.ext)}</span>
           <span class="dv-name">${esc(it.name)}</span>
           <span class="dv-meta">${fSize(it.size)}${it.source === 'chat' ? ' · 聊天' : ''}</span>
           <button class="dv-act" data-dvsend="${it.id}" title="发给好友">📤</button>
           <a class="dv-act" href="/api/drive/${it.id}/download" title="下载">⬇</a>
           <button class="dv-del" data-dvdel="${it.id}" title="删除">🗑</button></div>`).join('');
  } catch (e) { $('#dv-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#dv-crumb').addEventListener('click', e => { const a = e.target.closest('[data-dvcd]'); if (a) { dvFolder = a.dataset.dvcd; loadDrive(); } });
$('#dv-list').addEventListener('click', async e => {
  const dir = e.target.closest('[data-dvopen]');
  if (dir && !e.target.closest('[data-dvdel]')) { dvFolder = dir.dataset.dvopen; loadDrive(); return; }
  const del = e.target.closest('[data-dvdel]');
  if (del) {
    if (!(await appConfirm('删除这个？（文件夹会连里面一起删）'))) return;
    try { await api('/api/drive/' + del.dataset.dvdel, { method: 'DELETE' }); loadDrive(); } catch (err) { toast(err.message, true); }
    return;
  }
  const send = e.target.closest('[data-dvsend]');
  if (send) driveSend(+send.dataset.dvsend);
});
$('#dv-upfile').addEventListener('change', async e => {
  const files = [...e.target.files]; e.target.value = '';
  await dvUpload(files);
});
async function dvUpload(files) {
  if (!files.length) return;
  toast('上传中…（' + files.length + '）');
  let ok = 0;
  for (const f of files) {
    const fd = new FormData(); fd.append('file', f, f.name); fd.append('folder', dvFolder);
    try { await api('/api/drive', { method: 'POST', body: fd }); ok++; } catch (err) { toast(f.name + '：' + err.message, true); }
  }
  if (ok) { toast('已上传 ' + ok + ' 个'); loadDrive(); }
}
$('#dv-newfolder').onclick = async () => {
  const name = await appPrompt('新建文件夹', '', '');
  if (!name || !name.trim()) return;
  try { await api('/api/drive/folder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim(), parent: dvFolder }) }); loadDrive(); }
  catch (err) { toast(err.message, true); }
};
async function driveSend(fid) {
  try {
    const d = await api('/api/friends');
    if (!d.friends.length) { toast('你还没有好友，先去「聊天 → 加好友」', true); return; }
    const pick = await pickFriend(d.friends, '发给谁');
    if (!pick) return;
    await api('/api/drive/' + fid + '/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to: pick }) });
    toast('已发送');
  } catch (e) { toast(e.message, true); }
}
// 选好友（复用小记那种底部面板）
function pickFriend(friends, title) {
  return new Promise(res => {
    const el = $('#mat-share-sheet');
    el.innerHTML = `<div class="ns-mask" data-sheet-close></div><div class="ns-panel">
      <div class="ns-handle"></div><div class="ns-title">${esc(title || '选择好友')}</div>
      <div class="ms-list">${friends.map(f => `<button class="ms-frow" data-fp="${f.id}">👤 ${esc(f.username)}</button>`).join('')}</div>
      <div class="ms-acts"><button class="btn" id="fp-cancel">取消</button></div></div>`;
    el.classList.remove('hidden');
    const done = v => { el.classList.add('hidden'); res(v); };
    el.querySelector('.ns-mask').onclick = () => done(null);
    $('#fp-cancel').onclick = () => done(null);
    el.querySelectorAll('[data-fp]').forEach(b => b.onclick = () => done(+b.dataset.fp));
  });
}
