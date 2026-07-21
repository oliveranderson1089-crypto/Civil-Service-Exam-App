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
function fSize(n) {
  n = n || 0;
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
  return (n / 1073741824).toFixed(1) + ' GB';   // 配额是 GB 量级，别显示成「2048.0 MB」
}
function openDrive() { dvFolder = ''; push({ view: 'drive', title: '云盘' }); loadDrive(); }
async function loadDrive() {
  $('#dv-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/drive?folder=' + encodeURIComponent(dvFolder));
    $('#dv-used').textContent = '已用 ' + fSize(d.used) + (d.quota ? ' / ' + fSize(d.quota) : '');
    // 面包屑
    const parts = dvFolder ? dvFolder.split('/') : [];
    let acc = '';
    $('#dv-crumb').innerHTML = `<a data-dvcd="">☁️ 云盘</a>` + parts.map(p => {
      acc = acc ? acc + '/' + p : p; return ` / <a data-dvcd="${esc(acc)}">${esc(p)}</a>`;
    }).join('');
    if (!d.items.length) { $('#dv-list').innerHTML = '<p class="empty">这个文件夹是空的。把文件或整个文件夹拖进来，也可以用右上角的上传按钮。</p>'; return; }
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
/* ---- 上传 ----
   三条入口（选文件 / 选整个文件夹 / 拖进来）都汇成同一种东西喂给 dvUpload：
   [{file, folder}]，folder 是**相对当前目录**的子路径（'' = 直接放当前目录）。
   中间那些目录不用前端一层层发请求去建，后端 _ensure_folder_path 会照着这个
   相对路径把缺的补出来。 */
const DV_PARALLEL = 3;      // 并发数：再多就是把上行带宽切碎，总时间反而更长

function dvUploadOne(file, folder, onProg) {
  // 用 XHR 而不是 api()：只有 XHR 能报上传进度，fetch 的请求体没有 progress 事件
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append('file', file, file.name);
    fd.append('folder', folder);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/drive');
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProg(e.loaded); };
    xhr.onload = () => {
      if (xhr.status === 401) { location.href = '/login'; reject(new Error('未登录')); return; }
      let d = {};
      try { d = JSON.parse(xhr.responseText); } catch (_) { /* 413 之类返回的是 HTML 错误页 */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(d);
      else reject(new Error(d.error || (xhr.status === 413 ? '文件太大，服务器拒收' : '上传失败')));
    };
    xhr.onerror = () => reject(new Error('网络中断'));
    xhr.send(fd);
  });
}

function dvProg(cur, total, label) {
  $('#dv-prog').classList.remove('hidden');
  const pct = total ? Math.min(100, Math.round(cur / total * 100)) : 0;
  $('#dv-prog-bar').style.width = pct + '%';
  $('#dv-prog-txt').textContent = label + ' · ' + pct + '%';
}

async function dvUpload(items) {
  items = (items || []).filter(it => it && it.file);
  if (!items.length) return;
  const total = items.reduce((s, it) => s + (it.file.size || 0), 0);
  const sent = new Array(items.length).fill(0);       // 每个文件已发字节，汇总成总进度
  let done = 0, ok = 0, fail = 0, next = 0;
  const tick = () => dvProg(sent.reduce((a, b) => a + b, 0), total, '上传中 ' + done + '/' + items.length);
  tick();
  const worker = async () => {
    while (next < items.length) {
      const i = next++;
      const dest = [dvFolder, items[i].folder].filter(Boolean).join('/');
      try { await dvUploadOne(items[i].file, dest, n => { sent[i] = n; tick(); }); ok++; }
      catch (err) { fail++; toast(items[i].file.name + '：' + err.message, true); }
      sent[i] = items[i].file.size || 0;   // 失败的也记满，否则进度条永远差一截停在那
      done++; tick();
    }
  };
  await Promise.all(Array.from({ length: Math.min(DV_PARALLEL, items.length) }, worker));
  $('#dv-prog').classList.add('hidden');
  toast(fail ? '上传完成 ' + ok + ' 个，失败 ' + fail + ' 个' : '已上传 ' + ok + ' 个', fail > 0 && ok === 0);
  loadDrive();
}

$('#dv-upfile').addEventListener('change', e => {
  const items = [...e.target.files].map(f => ({ file: f, folder: '' }));
  e.target.value = '';
  dvUpload(items);
});
$('#dv-upfolder').addEventListener('change', e => {
  // webkitRelativePath 形如 '照片/2024/a.jpg'，砍掉文件名剩下的就是要建的子目录
  const items = [...e.target.files].map(f => {
    const rel = f.webkitRelativePath || '';
    return { file: f, folder: rel.includes('/') ? rel.slice(0, rel.lastIndexOf('/')) : '' };
  });
  e.target.value = '';
  dvUpload(items);
});

/* 拖拽上传。必须走 dataTransfer.items 拿 FileSystemEntry：只读 dataTransfer.files
   的话，拖进来的文件夹会变成一个 0 字节的怪文件，用户以为传上去了其实是空的。 */
function dvWalkEntry(entry, parent, out) {
  return new Promise(resolve => {
    if (entry.isFile) {
      entry.file(f => { out.push({ file: f, folder: parent }); resolve(); }, () => resolve());
      return;
    }
    if (!entry.isDirectory) { resolve(); return; }
    const dir = parent ? parent + '/' + entry.name : entry.name;
    const reader = entry.createReader();
    const kids = [];
    const readBatch = () => reader.readEntries(batch => {
      // readEntries 一次最多给 100 条，要一直读到它返回空数组才算读完这个目录
      if (batch.length) { kids.push(...batch); readBatch(); return; }
      Promise.all(kids.map(k => dvWalkEntry(k, dir, out))).then(resolve);
    }, () => resolve());
    readBatch();
  });
}
const dvView = $('#view-drive');
dvView.addEventListener('dragover', e => { e.preventDefault(); dvView.classList.add('dv-drag'); });
dvView.addEventListener('dragleave', e => {
  // 只有真正离开整个视图才收起提示，划过子元素不算
  if (!e.relatedTarget || !dvView.contains(e.relatedTarget)) dvView.classList.remove('dv-drag');
});
dvView.addEventListener('drop', async e => {
  e.preventDefault();
  dvView.classList.remove('dv-drag');
  const dt = e.dataTransfer;
  // entry 得在回调里同步取完：await 之后 dataTransfer 就被浏览器回收了
  const entries = [...(dt.items || [])].map(it => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null)).filter(Boolean);
  const out = [];
  if (entries.length) await Promise.all(entries.map(en => dvWalkEntry(en, '', out)));
  else for (const f of [...(dt.files || [])]) out.push({ file: f, folder: '' });
  dvUpload(out);
});
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
