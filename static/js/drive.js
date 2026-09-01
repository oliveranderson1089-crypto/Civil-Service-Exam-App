/* 云盘
 *
 * 由 app.js 按它自己的区段边界切出（原 L7320-7411）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, aiAttachLib, api, appConfirm, appPrompt, artEm, back, clipFiles, copyText,
   DESKTOP_VER, errMsg, esc, libTouch, IN_APP, IS_DESKTOP, KB, lsDel, lsGet, lsSet, openAiOut,
   openViewerUrl, push, render, setAppClip, stack, toast, uiError */

/* ================= 云盘 ================= */
let dvFolder = '';
const FILE_ICON = { pdf: '📕', doc: '📘', docx: '📘', xls: '📗', xlsx: '📗', ppt: '📙', pptx: '📙',
  png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', webp: '🖼️', apk: '📦', exe: '📦', dmg: '📦',
  zip: '🗜️', rar: '🗜️', '7z': '🗜️', mp4: '🎬', mp3: '🎵', txt: '📄', md: '📄', html: '🌐' };
// 包成两套字形：没开主题还是原来那个彩色 emoji，开了主题换成跟色的线描（js/articons.js）
const dvIcon = e => artEm(FILE_ICON[(e || '').replace('.', '').toLowerCase()] || '📎');
function fSize(n) {
  n = n || 0;
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
  return (n / 1073741824).toFixed(1) + ' GB';   // 配额是 GB 量级，别显示成「2048.0 MB」
}
let dvQuery = '', dvSort = 'new';
let dvGrid = lsGet('dv:grid') === '1';   // 列表 / 网格，记住上次选的
const dvSel = new Set();          // 多选中的 id（每次重新列目录都清空，见 loadDrive）

let dvInTrash = false;             // 是否正停在回收站视图
function dvLeaveTrash() {          // 回收站是个独立视图，离开它得显式复位
  dvInTrash = false;
  const b = $('#dv-trash'); if (b) b.classList.remove('primary');
}
function openDrive() {
  dvFolder = ''; dvQuery = ''; $('#dv-search').value = '';
  dvLeaveTrash();                  // 不复位的话 loadDrive 会短路去 loadTrash：
  dvPush('云盘', '');                                   // 云盘打开是回收站，上传完也看不见文件
  loadDrive();
}

/* 压栈前先看看这一层是不是已经在栈里了 —— 在就退回去，不再往上堆。
   云盘的入口不止一个（侧栏、库页、面包屑），来回走几趟栈里就会攒出一串
   「云盘 › 资料 › 云盘 › 资料 › …」，顶部面包屑被撑成两三行，返回键也要按十几次。 */
function dvPush(title, folder) {
  for (let i = stack.length - 1; i >= 0; i--) {
    if (stack[i].view !== 'drive' || (stack[i].folder || '') !== folder) continue;
    stack = stack.slice(0, i + 1);
    render();
    return;
  }
  push({ view: 'drive', title, folder });
}

function dvRow(it) {
  const pick = `<input type="checkbox" class="dv-pick" data-dvpick="${it.id}">`;
  /* 一行只留一个 ⋮：原来铺 5~6 个小图标，手机上点不准，也把文件名挤得只剩半截。
     所有操作都收进菜单（右键打开的是同一个，见 dvMenu）。 */
  const more = `<button class="dv-act dv-more" data-dvmore="${it.id}" title="更多">⋮</button>`;
  if (it.is_dir) {
    // 搜索结果里的文件夹，路径要用它自己的 folder 拼，不能用当前目录
    const path = (it.folder ? it.folder + '/' : '') + it.name;
    return `<div class="dv-item dv-dir">${pick}
      <span class="dv-ic" data-dvopen="${esc(path)}">${artEm('📁')}</span>
      <div class="dv-info" data-dvopen="${esc(path)}">
        <div class="dv-name">${esc(it.name)}</div>
        <div class="dv-meta">文件夹</div></div>
      <span class="dv-acts">${more}</span></div>`;
  }
  const where = (dvQuery && it.folder) ? ' · ' + artEm('📁') + ' ' + esc(it.folder) : '';
  const name = it.viewable
    ? `<div class="dv-name dv-can" data-dvview="${it.id}" data-ext="${esc(it.ext || '')}">${esc(it.name)}</div>`
    : `<div class="dv-name">${esc(it.name)}</div>`;
  const acts = more;
  // 网格里图片直接出缩略图；onerror 时换回图标 —— 一张坏图不该在格子里留个破图标
  const face = (dvGrid && it.thumb)
    ? `<img class="dv-thumb" loading="lazy" src="/api/drive/${it.id}/thumb" alt=""
            data-dvview="${it.id}" data-ext="${esc(it.ext || '')}"
            onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'dv-ic',textContent:'🖼️'}))">`
    : `<span class="dv-ic">${dvIcon(it.ext)}</span>`;
  const meta = `<div class="dv-meta">${fSize(it.size)}${it.source === 'chat' ? ' · 聊天' : ''}${where}</div>`;
  if (dvGrid) {
    return `<div class="dv-item">${pick}${face}
      <div class="dv-info">${name}${meta}</div>
      <span class="dv-acts">${acts}</span></div>`;
  }
  return `<div class="dv-item">${pick}${face}
    <div class="dv-info">${name}${meta}</div>
    <span class="dv-acts">${acts}</span></div>`;
}

/* ---- 回收站 ----
   删除改成了软删，所以「删掉」和「真没了」是两件事。这个视图就是那两件事之间的地方。 */
function dvTrashRow(it) {
  /* 「原在 …」那串可以很长（原在 📁 四川省考/公考/…）。名字和它都放进可收缩的
     .dv-info 里，按钮才不会被顶出屏幕 —— 手机上原来点不到「恢复」就是栽在这儿。 */
  return `<div class="dv-item">
    <span class="dv-ic">${it.is_dir ? artEm('📁') : dvIcon(it.ext)}</span>
    <div class="dv-info">
      <div class="dv-name">${esc(it.name)}</div>
      <div class="dv-meta">${it.is_dir ? '文件夹' + (it.kids ? '（含 ' + it.kids + ' 项）' : '') : fSize(it.size)} · 删于 ${esc((it.deleted_at || '').slice(5, 16))}${it.folder ? ' · 原在 ' + artEm('📁') + ' ' + esc(it.folder) : ''}</div>
    </div>
    <span class="dv-acts">
      <button class="dv-act" data-dvrestore="${it.id}" title="恢复">↩︎ 恢复</button>
      <button class="dv-del" data-dvpurge="${it.id}" title="彻底删除">${artEm('🗑')}</button></span></div>`;
}

async function loadTrash() {
  $('#dv-list').innerHTML = '<p class="empty">加载中…</p>';
  dvSel.clear(); dvBatchBar();
  try {
    const d = await api('/api/drive/trash');
    $('#dv-crumb').innerHTML = `<a data-dvcd="">${artEm('☁️')} 云盘</a> / ${artEm('🗑')} 回收站`;
    // 回收站里的东西还占着配额 —— 不说清楚，用户会奇怪「删了怎么没腾出空间」
    $('#dv-used').textContent = d.held
      ? '回收站占用 ' + fSize(d.held) + '（' + d.days + ' 天后自动清空）'
      : '回收站是空的';
    $('#dv-list').innerHTML = d.items.length
      ? d.items.map(dvTrashRow).join('')
      : '<p class="empty">回收站是空的。删掉的东西会先放这儿 ' + d.days + ' 天，可以反悔。</p>';
  } catch (e) { $('#dv-list').innerHTML = uiError(e); }
}

$('#dv-trash').onclick = () => {
  dvInTrash = !dvInTrash;
  $('#dv-trash').classList.toggle('primary', dvInTrash);
  if (dvInTrash) { loadTrash(); } else { dvFolder = ''; dvQuery = ''; $('#dv-search').value = ''; loadDrive(); }
};

async function loadDrive() {
  if (dvInTrash) return loadTrash();
  $('#dv-list').innerHTML = '<p class="empty">加载中…</p>';
  // 换目录/换搜索词后，选中的可能已经不在眼前了 —— 留着会让批量操作误伤看不见的东西
  dvSel.clear(); dvBatchBar();
  try {
    const qs = new URLSearchParams({ folder: dvFolder, sort: dvSort });
    if (dvQuery) qs.set('q', dvQuery);
    const d = await api('/api/drive?' + qs.toString());
    $('#dv-used').textContent = '已用 ' + fSize(d.used) + (d.quota ? ' / ' + fSize(d.quota) : '');
    // 面包屑（搜索时改成显示搜索状态，点「云盘」退回浏览）
    if (dvQuery) {
      $('#dv-crumb').innerHTML = `<a data-dvcd="">${artEm('☁️')} 云盘</a> / 🔍 搜「${esc(dvQuery)}」`;
    } else {
      const parts = dvFolder ? dvFolder.split('/') : [];
      let acc = '';
      $('#dv-crumb').innerHTML = `<a data-dvcd="">${artEm('☁️')} 云盘</a>` + parts.map(p => {
        acc = acc ? acc + '/' + p : p; return ` / <a data-dvcd="${esc(acc)}">${esc(p)}</a>`;
      }).join('');
    }
    if (!d.items.length) {
      $('#dv-list').innerHTML = '<p class="empty">' + (dvQuery
        ? '没搜到「' + esc(dvQuery) + '」。'
        : '这个文件夹是空的。把文件或整个文件夹拖进来，也可以用右上角的上传按钮。') + '</p>';
      return;
    }
    $('#dv-list').classList.toggle('grid', dvGrid);
    $('#dv-list').innerHTML = d.items.map(dvRow).join('');
  } catch (e) { $('#dv-list').innerHTML = uiError(e); }
}

/* 进目录 = 往导航栈压一层，于是全局「返回」自然是退到**上一级目录**，
   而不是一步跳回首页。回到栈里已有的层级（点面包屑）则出栈，别把栈越堆越高。 */
function dvGo(folder) {
  // 进文件夹算打开。'' 是云盘根目录，libTouch 见空 ref 自己会跳过 ——
  // 「打开了云盘」不是一件值得记的事，那是柜子不是东西。
  // 只挂在 dvGo 上，不挂 __dvShow：按返回键退回上一级是**离开**，不是打开。
  libTouch('drivedir', folder);
  dvJump(folder);
}
// 不打点的那一半。给「先落到某层目录、要打开的其实是里面那份文件」用（dvOpenFile）——
// 走 dvGo 的话点一次文件会连带记一条文件夹，「最近打开」里就成双成对地长草。
function dvJump(folder) {
  dvQuery = ''; $('#dv-search').value = ''; dvLeaveTrash();
  dvPush(folder ? folder.split('/').pop() : '云盘', folder);
}
/* 从「库 → 最近打开」点回一份云盘文件。
   先落到它所在的那一层目录再开预览器：只开预览器的话，关掉之后人站在云盘根目录，
   而他明明是从三层深的文件夹里点进来的。 */
function dvOpenFile(id, name, folder) {
  dvJump(folder || '');
  const ext = (String(name || '').match(/\.[^.]+$/) || [''])[0].toLowerCase();
  openViewerUrl('/api/drive/' + id + '/view', name, ext,
                '/api/drive/' + id + '/download', '/api/drive/' + id + '/view?text=1',
                { kind: 'drive', id: +id });
}
$('#dv-crumb').addEventListener('click', e => {
  const a = e.target.closest('[data-dvcd]');
  if (!a) return;
  const want = a.dataset.dvcd;
  // 面包屑是往回走：把栈弹到那一层，不再往上堆
  let hops = 0;
  for (let i = stack.length - 1; i > 0; i--) {
    if (stack[i].view !== 'drive') break;
    if ((stack[i].folder || '') === want) { for (let k = 0; k < hops; k++) back(); return; }
    hops++;
  }
  dvGo(want);
});
/* 栈顶变成云盘这一层时（含被 back() 弹回来），按它记着的 folder 重新列目录。
   shell.js 的 render() 只负责显示/隐藏视图，不会替各模块重新取数据。 */
window.__dvShow = (st) => {
  const want = st.folder || '';
  if (dvFolder === want && !dvInTrash) return;    // 没变就别白跑一趟接口
  dvFolder = want;
  dvInTrash = false;
  loadDrive();
};
$('#dv-list').addEventListener('click', async e => {
  const back = e.target.closest('[data-dvrestore]');
  if (back) {
    try {
      const d = await api('/api/drive/trash/' + back.dataset.dvrestore + '/restore', { method: 'POST' });
      toast(d && d.n > 1 ? '已恢复 ' + d.n + ' 项' : '已恢复');
      loadTrash();
    }
    catch (err) { toast(errMsg(err), true); }
    return;
  }
  const purge = e.target.closest('[data-dvpurge]');
  if (purge) {
    if (!(await appConfirm('彻底删除？这一步之后就找不回来了。'))) return;
    try { await api('/api/drive/trash/' + purge.dataset.dvpurge, { method: 'DELETE' }); loadTrash(); }
    catch (err) { toast(errMsg(err), true); }
    return;
  }
  const pick = e.target.closest('[data-dvpick]');
  if (pick) {
    const id = +pick.dataset.dvpick;
    if (pick.checked) dvSel.add(id); else dvSel.delete(id);
    dvBatchBar();
    return;
  }
  const dir = e.target.closest('[data-dvopen]');
  if (dir) { dvGo(dir.dataset.dvopen); return; }
  const view = e.target.closest('[data-dvview]');
  if (view) {                      // 预览走资料库那套查看器：md/txt 阅读模式、pdf/office 走 pdf.js
    const id = view.dataset.dvview;
    libTouch('drive', id, dvFolder);   // 带上所在目录，「最近打开」里点回来才落得回这一层
    openViewerUrl('/api/drive/' + id + '/view', view.textContent, view.dataset.ext,
                  '/api/drive/' + id + '/download', '/api/drive/' + id + '/view?text=1',
                  { kind: 'drive', id: +id });
    return;
  }
  const mo = e.target.closest('[data-dvmore]');
  if (mo) {                          // ⋮ 和右键打开的是同一个菜单
    const item = mo.closest('.dv-item');
    const r = mo.getBoundingClientRect();
    dvMenu(r.right - 4, r.bottom + 4, +mo.dataset.dvmore,
           (item.querySelector('.dv-name') || {}).textContent,
           !!item.querySelector('[data-dvview]'), item.classList.contains('dv-dir'));
    return;
  }
});

// 启动时让按钮反映记住的选择，否则明明是网格、按钮还写着「▦ 网格」
if (dvGrid) { $('#dv-grid').classList.add('primary'); $('#dv-grid').textContent = '☰ 列表'; }
$('#dv-grid').onclick = () => {
  dvGrid = !dvGrid;
  lsSet('dv:grid', dvGrid ? '1' : '0');
  $('#dv-grid').classList.toggle('primary', dvGrid);
  $('#dv-grid').textContent = dvGrid ? '☰ 列表' : '▦ 网格';
  loadDrive();
};

/* ---- 转成 Markdown ----
   云盘里的 PDF / Word / 扫描件转成有层级的 Markdown，成品落到「AI 产出」，
   再由用户决定投到哪（那边的投放、下载、改名都是现成的）。分级怎么做见 mods/tomd.py。

   这份扩展名清单是后端 tomd.SUPPORT_EXT 的镜像，只用来决定「菜单里显不显示这一项」；
   能不能转由后端说了算（不支持会返回 415，错误话术也在后端）。和 OFFICE_EXT 一样，
   前后端各留一份是这套代码的老规矩，改一边记得改另一边。 */
const DV_MD_EXT = ['pdf', 'doc', 'docx', 'ppt', 'pptx', 'odt', 'odp', 'rtf', 'txt', 'md',
  'csv', 'json', 'html', 'htm', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif', 'heic', 'tif', 'tiff'];
const dvExt = n => (String(n || '').split('.').pop() || '').toLowerCase();

async function dvToMd(id, name) {
  let p;
  try { p = await api('/api/drive/' + id + '/tomd/probe'); }
  catch (e) { toast(errMsg(e), true); return; }

  /* 扫描页要逐页识别，一页几秒。超过默认上限就把账算给用户看，让他自己决定 ——
     一本 300 页的扫描书全转要十几分钟，替他做主两个方向都是错的：
     擅自全转是让他干等，擅自截断是给他一份缺了后半本、还看不出来的文件。 */
  let all = false;
  const limit = p.ocr_limit || 30;
  if (p.scan_pages > limit) {
    const mins = Math.max(1, Math.round(p.scan_pages * 3 / 60));
    const ans = await appConfirm(
      `「${name}」里有 ${p.scan_pages} 页是扫描件，要逐页识别文字，全部转大约 ${mins} 分钟。`,
      { title: '这份要识别的页数不少', okText: '全部转', altText: `只转前 ${limit} 页`, cancelText: '取消' });
    if (!ans) return;              // 取消（false / null）
    all = ans !== 'alt';
  }

  let d;
  try {
    d = await api('/api/drive/' + id + '/tomd', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ all_pages: all })
    });
  } catch (e) { toast(errMsg(e), true); return; }
  toast('在后台转，转好了通知你');
  dvMdPoll(d.task_id, name);
}

/* 轮询任务。间隔 2 秒：原生 PDF 一两秒就完了，扫描件要几分钟，
   前者不该等太久，后者也不值得每秒问一次。转换本身在后台跑，
   这里断了（切走页面、关掉应用）只是看不到结果提示，转换照常完成，通知中心里有。 */
function dvMdPoll(tid, name) {
  const t0 = Date.now();
  const tick = async () => {
    if (Date.now() - t0 > 45 * 60 * 1000) return;    // 兜底：再长就不守着了，去通知里看
    let t;
    try { t = await api('/api/drive/tomd/' + tid); }
    catch (_e) { return; }                            // 网断了就不再追问，通知里还有一份
    if (t.status === 'running') { setTimeout(tick, 2000); return; }
    if (t.status === 'error') { toast('转换失败：' + (t.message || '未知原因'), true); return; }
    if (await appConfirm(t.message || '转好了', {
      title: `「${name}」转好了`, okText: '去看看', cancelText: '待会儿' })) openAiOut();
  };
  setTimeout(tick, 1200);
}

/* ---- 分享链接 ----
   这是全站唯一「不用登录就能取到东西」的口子，所以界面上要把有效期说清楚，
   也要能随时收回（撤销后链接立刻失效）。 */
async function dvShare(id) {
  try {
    const d = await api('/api/drive/' + id + '/share', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
    const url = location.origin + d.url;
    const ok = await copyText(url);     // 桌面壳里 navigator.clipboard 是被拒的，copyText 有兜底
    await appPrompt(ok ? '链接已复制（有效期至 ' + (d.expires_at || '').slice(0, 10) + '）'
                       : '复制不了，手动选中下面这行', '', url);
  } catch (e) { toast(errMsg(e), true); }
}

$('#dv-share-list').onclick = async () => {
  let d;
  try { d = await api('/api/drive/shares'); } catch (e) { toast(errMsg(e), true); return; }
  const el = $('#mat-share-sheet');
  el.innerHTML = `<div class="ns-mask" data-sheet-close></div><div class="ns-panel">
    <div class="ns-handle"></div><div class="ns-title">我分享出去的链接</div>
    <div class="ms-list">${d.shares.length ? d.shares.map(s => `<div class="ms-frow">
      ${artEm('🔗')} ${esc(s.name)}<br><small>下载 ${s.hits} 次 · 有效期至 ${esc((s.expires_at || '不限').slice(0, 10))}</small>
      <button class="btn tiny" data-dvunshare="${s.id}">撤销</button></div>`).join('')
    : '<p class="empty">还没分享过。文件行上点 ' + artEm("🔗") + ' 就能生成链接。</p>'}</div>
    <div class="ms-acts"><button class="btn" id="dvsh-close">关闭</button></div></div>`;
  el.classList.remove('hidden');
  const close = () => el.classList.add('hidden');
  el.querySelector('.ns-mask').onclick = close;
  $('#dvsh-close').onclick = close;
  el.querySelectorAll('[data-dvunshare]').forEach(b => {
    b.onclick = async () => {
      try { await api('/api/drive/shares/' + b.dataset.dvunshare, { method: 'DELETE' }); toast('已撤销'); close(); }
      catch (err) { toast(errMsg(err), true); }
    };
  });
};

/* ---- 搜索 / 排序 ---- */
let dvSearchT = null;
$('#dv-search').addEventListener('input', e => {
  clearTimeout(dvSearchT);
  const v = e.target.value.trim();
  dvSearchT = setTimeout(() => { dvQuery = v; loadDrive(); }, 300);   // 打字防抖，别每个字母打一次接口
});
/* 排序用自己的弹层，不用原生 <select>：原生控件各系统长相不一、跟不了皮肤，
   而这套弹层和右键菜单共用一份样式（.dv-menu）。 */
const DV_SORTS = [['new', '最新在前'], ['old', '最早在前'], ['name', '按名称'],
                  ['big', '从大到小'], ['small', '从小到大']];
function dvSortLabel() {
  const hit = DV_SORTS.find(x => x[0] === dvSort);
  $('#dv-sort-label').textContent = hit ? hit[1] : DV_SORTS[0][1];
}
dvSortLabel();
$('#dv-sort').onclick = () => {
  const el = $('#dv-menu');
  el.innerHTML = DV_SORTS.map(([k, t]) =>
    `<button data-dvsort="${k}"${k === dvSort ? ' class="on"' : ''}>${t}</button>`).join('');
  el.dataset.id = ''; el.dataset.name = '';
  el.classList.remove('hidden');
  const r = $('#dv-sort').getBoundingClientRect();
  el.style.left = Math.min(r.left, window.innerWidth - (el.offsetWidth || 150) - 8) + 'px';
  el.style.top = (r.bottom + 4) + 'px';
};

/* ---- 重命名 / 移动 / 批量 ---- */
async function dvRename(id, cur) {
  const name = await appPrompt('重命名', '', cur || '');
  if (!name || !name.trim() || name.trim() === cur) return;
  try {
    await api('/api/drive/' + id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ name: name.trim() }) });
    loadDrive();
  } catch (err) { toast(errMsg(err), true); }
}

function dvBatchBar() {
  $('#dv-batch').classList.toggle('hidden', !dvSel.size);
  $('#dv-batch-n').textContent = '已选 ' + dvSel.size + ' 项';
}
/* 批量下载：多选打成一个 zip。
   只选中一个文件时不套 zip —— 直接下原文件，省得用户下回来还要解一层。 */
const dvIsDir = id => {
  const b = document.querySelector(`[data-dvmore="${id}"]`);
  return !!(b && b.closest('.dv-item') && b.closest('.dv-item').classList.contains('dv-dir'));
};
const dvNameOf = id => {
  const b = document.querySelector(`[data-dvmore="${id}"]`);
  const n = b && b.closest('.dv-item') && b.closest('.dv-item').querySelector('.dv-name');
  return n ? n.textContent : '';
};
$('#dv-bdl').onclick = async () => {
  const ids = [...dvSel];
  if (!ids.length) return;
  if (ids.length === 1 && !dvIsDir(ids[0])) {
    dvDownload('/api/drive/' + ids[0] + '/download', dvNameOf(ids[0]));
    return;
  }
  const q = ids.join(',');
  /* 先问一句「这一包多大、打不打得动」。
     点 <a download> 碰上 JSON 错误响应，浏览器是**静默不动**的 —— 超限、文件没了，
     用户看到的都是「点了没反应」。预检把这两种情况变成一句看得懂的话。 */
  let d;
  try { d = await api('/api/drive/zip?check=1&ids=' + q); }
  catch (err) { toast(errMsg(err), true); return; }
  // 打包是同步做的，几百 MB 要好几秒才开始下。不报一声体量，用户会以为按钮坏了，
  // 接着连点好几下 —— 每一下都是一次完整的打包。
  toast('正在打包 ' + d.files + ' 个文件（' + fSize(d.size) + '），好了会自动开始下载');
  dvDownload('/api/drive/zip?ids=' + q, '云盘' + ids.length + '项.zip');
};
$('#dv-bcancel').onclick = () => { dvSel.clear(); dvBatchBar(); document.querySelectorAll('.dv-pick').forEach(c => { c.checked = false; }); };
$('#dv-bdel').onclick = async () => {
  if (!dvSel.size) return;
  if (!(await appConfirm('删除选中的 ' + dvSel.size + ' 项？（文件夹会连里面一起删）'))) return;
  let fail = 0;
  for (const id of [...dvSel]) {
    // 别把原因吞掉：只报个数字的话，用户既不知道是哪一项、也不知道为什么（见 docs/README-full.md 第 1 条）
    try { await api('/api/drive/' + id, { method: 'DELETE' }); }
    catch (err) { fail++; toast(errMsg(err), true); }
  }
  toast(fail ? '删除完成，' + fail + ' 项失败' : '已删除', fail > 0);
  loadDrive();
};
$('#dv-move').onclick = async () => {
  if (!dvSel.size) return;
  const dest = await dvPickFolder();
  if (dest === null) return;
  let ok = 0, fail = 0;
  for (const id of [...dvSel]) {
    try {
      await api('/api/drive/' + id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                                      body: JSON.stringify({ folder: dest }) });
      ok++;
    } catch (err) { fail++; toast(errMsg(err), true); }
  }
  toast(fail ? '移动 ' + ok + ' 项，失败 ' + fail + ' 项' : '已移动 ' + ok + ' 项', fail > 0 && !ok);
  loadDrive();
};

/* ---- 复制 / 粘贴 ----
   桌面壳里 WebKit 自带的右键菜单只有「后退/前进/停止/重新加载」，没有复制粘贴；
   而应用内本来也没有「把文件复制到另一个目录」这回事。这里两件都补上。
   复制是瞬时的：后端沿用同一个 blob（去重那套），不搬数据、不吃配额。 */
let dvClip = [];          // 剪贴板里存的是云盘文件 id

function dvSetClip(ids) {
  dvClip = ids.slice();
  /* 同一份东西也放进应用内剪贴板：AI 助手那边认它 —— 复制完直接在助手里粘（或点
     输入框上方那条提示）就能把文件当附件带给 AI，不用先下下来再传上去。
     系统剪贴板指望不上：桌面壳的 WebKit 右键菜单只认文本和图片。 */
  setAppClip(dvClip.map(id => ({ kind: 'drive', id: +id })));
  toast(dvClip.length ? '已复制 ' + dvClip.length + ' 项：去目标文件夹点「粘贴」，或在 AI 助手里粘成附件'
                      : '没选中东西');
}

async function dvPaste() {
  if (!dvClip.length) {
    // 应用内剪贴板是空的 → 问问系统剪贴板里有没有文件（桌面壳专属）
    if (IS_DESKTOP) {
      try {
        window.webkit.messageHandlers.gk.postMessage(JSON.stringify({ a: 'pastefiles' }));
        return;
      } catch (_) { /* 桥不在就往下走 */ }
    }
    toast('剪贴板是空的。先选中文件点「复制」', true);
    return;
  }
  let ok = 0, fail = 0;
  for (const id of dvClip) {
    try {
      await api('/api/drive/' + id + '/copy', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder: dvFolder }) });
      ok++;
    } catch (err) { fail++; toast(errMsg(err), true); }
  }
  toast(fail ? '粘贴 ' + ok + ' 项，失败 ' + fail + ' 项' : '已粘贴 ' + ok + ' 项', fail > 0 && !ok);
  loadDrive();
}
$('#dv-bsend').onclick = () => driveSend([...dvSel]);
$('#dv-copy').onclick = () => { dvSetClip([...dvSel]); };
$('#dv-paste').onclick = dvPaste;

/* 右键菜单。桌面壳里必须 preventDefault 掉，否则弹出来的是 WebKit 那个
   「后退/前进/停止/重新加载」，在云盘里毫无用处。 */
function dvMenu(x, y, id, name, viewable, isDir) {
  const el = $('#dv-menu');
  const rows = [];
  if (id) {
    if (viewable) rows.push(['dvm-view', '👁 预览']);
    rows.push(['dvm-share', '🔗 分享链接'], ['dvm-copy', '📄 复制'], ['dvm-ren', '✏️ 重命名']);
    // 文件夹没有单文件下载（/download 只认 is_dir=0），给它的是整个打包成 zip
    rows.push(isDir ? ['dvm-zip', '📦 打包下载'] : ['dvm-dl', '⬇ 下载']);
    // 文件夹也给这一项：后端会先打包成 zip 再发（摊平逐个发会在对方会话里刷屏）
    rows.push(['dvm-send', isDir ? '📤 打包发送到聊天…' : '📤 发送到聊天…']);
    // 文件夹给不了：附件是一份份读的，一个目录塞进去只会把上下文冲爆
    if (!isDir) rows.push(['dvm-ai', '🤖 发给 AI 助手']);
    if (!isDir && DV_MD_EXT.includes(dvExt(name))) rows.push(['dvm-md', 'Ⓜ 转成 Markdown']);
    rows.push(['dvm-del', '🗑 删除']);
  }
  rows.push(['dvm-paste', '📋 粘贴' + (dvClip.length ? '（' + dvClip.length + ' 项）' : '')]);
  el.innerHTML = rows.map(([k, t]) => `<button data-dvm="${k}">${t}</button>`).join('');
  el.dataset.id = id || '';
  el.dataset.name = name || '';
  el.dataset.dir = isDir ? '1' : '';
  el.classList.remove('hidden');
  // 靠右/靠下时翻到另一侧，别让菜单跑到屏幕外
  const w = el.offsetWidth || 150, h = el.offsetHeight || 180;
  el.style.left = Math.min(x, window.innerWidth - w - 8) + 'px';
  el.style.top = Math.min(y, window.innerHeight - h - 8) + 'px';
}
/* 下载一律用隐藏的 <a download>，不改 location.href ——
   万一后端回了错误页，改 location 会**导航**过去，单页应用当场被冲掉。 */
function dvDownload(url, name) {
  const a = document.createElement('a');
  a.href = url; a.download = name || '';
  document.body.appendChild(a); a.click(); a.remove();
  /* 下完要有人说一声，否则「下载」这个动作从头到尾没有任何回音。
     桌面壳不在这儿说：它下完会回调 __onDownloaded，那时候连**存到哪**都说得出来（见 update.js）。
     安卓壳交给系统 DownloadManager，通知栏里有。剩下的浏览器只能报个「开始了」。 */
  if (!IS_DESKTOP) {
    toast('已开始下载' + (name ? '：' + name : '')
      + (IN_APP ? '，完成后在通知栏或手机的「下载」里找' : '，可在浏览器的下载列表里看'));
  }
}
const dvMenuHide = () => $('#dv-menu').classList.add('hidden');
$('#view-drive').addEventListener('contextmenu', e => {
  if (dvInTrash) return;                     // 回收站里只有恢复/彻底删，不给这套
  // 输入框放行：搜索框上右键该是系统那套「剪切/复制/粘贴」，我们这套菜单粘的是文件不是文字
  if (e.target.closest('input, textarea, select')) return;
  e.preventDefault();
  const item = e.target.closest('.dv-item');
  const mo = item && item.querySelector('[data-dvmore]');   // id 挂在 ⋮ 上
  dvMenu(e.clientX, e.clientY, mo ? mo.dataset.dvmore : '',
         item ? (item.querySelector('.dv-name') || {}).textContent : '',
         !!(item && item.querySelector('[data-dvview]')),
         !!(item && item.classList.contains('dv-dir')));
});
/* 点别处收起菜单。**必须放过打开菜单的那几个按钮** —— 它们的点击会冒泡到 document，
   于是菜单刚开就被这里关掉，表现是「点 ⋮ 一点反应都没有」。
   （右键不走 click，所以右键菜单一直是好的，只有 ⋮ 中招。）
   在触发器上撒 stopPropagation 也能挡，但每加一个入口就得记得撒一次；
   这里统一认「触发器」更省心。 */
const DV_MENU_TRIGGER = '#dv-menu, [data-dvmore], #dv-sort';
document.addEventListener('click', e => {
  if (!e.target.closest(DV_MENU_TRIGGER)) dvMenuHide();
});
$('#dv-menu').addEventListener('click', async e => {
  const so = e.target.closest('[data-dvsort]');
  if (so) { dvSort = so.dataset.dvsort; dvSortLabel(); dvMenuHide(); loadDrive(); return; }
  const b = e.target.closest('[data-dvm]');
  if (!b) return;
  const el = $('#dv-menu');
  const id = +el.dataset.id, name = el.dataset.name, isDir = el.dataset.dir === '1';
  dvMenuHide();
  switch (b.dataset.dvm) {
    case 'dvm-view': $(`[data-dvview="${id}"]`).click(); break;
    case 'dvm-copy': dvSetClip([id]); break;
    case 'dvm-share': dvShare(id); break;
    case 'dvm-send': driveSend([id], isDir); break;
    case 'dvm-ai': aiAttachLib([{ kind: 'drive', id, name }]); break;
    case 'dvm-md': dvToMd(id, name); break;
    case 'dvm-zip': dvDownload('/api/drive/' + id + '/zip', name + '.zip'); break;
    case 'dvm-paste': dvPaste(); break;
    case 'dvm-ren': dvRename(id, name); break;
    case 'dvm-dl': dvDownload('/api/drive/' + id + '/download', name); break;
    case 'dvm-del':
      if (await appConfirm('删除这个？（会先进回收站）')) {
        try { await api('/api/drive/' + id, { method: 'DELETE' }); loadDrive(); }
        catch (err) { toast(errMsg(err), true); }
      }
      break;
  }
});

// 选目标文件夹（复用发好友那个底部面板的样式）
async function dvPickFolder() {
  let folders = [];
  try { folders = (await api('/api/drive/folders')).folders || []; } catch (_) { /* 至少还能选根目录 */ }
  return new Promise(res => {
    const el = $('#mat-share-sheet');
    el.innerHTML = `<div class="ns-mask" data-sheet-close></div><div class="ns-panel">
      <div class="ns-handle"></div><div class="ns-title">移动到哪个文件夹</div>
      <div class="ms-list"><button class="ms-frow" data-dvto="">${artEm('☁️')} 云盘（根目录）</button>
      ${folders.map(f => `<button class="ms-frow" data-dvto="${esc(f)}">${artEm('📁')} ${esc(f)}</button>`).join('')}</div>
      <div class="ms-acts"><button class="btn" id="dvto-cancel">取消</button></div></div>`;
    el.classList.remove('hidden');
    const done = v => { el.classList.add('hidden'); res(v); };
    el.querySelector('.ns-mask').onclick = () => done(null);
    $('#dvto-cancel').onclick = () => done(null);
    el.querySelectorAll('[data-dvto]').forEach(b => { b.onclick = () => done(b.dataset.dvto); });
  });
}
/* ---- 上传 ----
   三条入口（选文件 / 选整个文件夹 / 拖进来）都汇成同一种东西喂给 dvUpload：
   [{file, folder}]，folder 是**相对当前目录**的子路径（'' = 直接放当前目录）。
   中间那些目录不用前端一层层发请求去建，后端 _ensure_folder_path 会照着这个
   相对路径把缺的补出来。 */
const DV_PARALLEL = 3;      // 同时传几个文件：再多就是把上行带宽切碎，总时间反而更长
const DV_CHUNK_PAR = 3;     // 单个文件里同时传几片（隧道 RTT 高，串行等的时间比传的时间还长）
const DV_CHUNK = 4 * 1024 * 1024;        // 分片大小，远小于 Cloudflare 隧道那 100MB 硬上限
const DV_CHUNK_MIN = 8 * 1024 * 1024;    // 超过这么大才值得切片（小文件切了反而更慢）
/* 秒传的哈希只算到这个大小为止（= 走整发上传的那档）。
   crypto.subtle 没有流式接口，算哈希必须把**整个文件**读进内存；对超过这条线的文件，
   那既是一次白读（后面分片还要再读一遍），也是一次几十 MB 的内存尖峰。
   更大的文件就不在前端问秒传了 —— 服务端 _finish_upload 仍然会按 sha256 去重，
   省的是磁盘，只是省不掉这一次上传的流量。 */
const DV_HASH_MAX = DV_CHUNK_MIN;

/* 算 sha256 给「秒传」用。拿不到就返回 null，调用方照常传 ——
   crypto.subtle 只在安全上下文（https / localhost）里有，局域网用 http 访问时是 undefined，
   那种情况下秒传直接不可用，但不能因此连传都传不了。 */
async function dvSha256(file) {
  if (!window.crypto || !crypto.subtle || file.size > DV_HASH_MAX) return null;
  try {
    const buf = await file.arrayBuffer();
    const h = await crypto.subtle.digest('SHA-256', buf);
    return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, '0')).join('');
  } catch (_) { return null; }
}

/* 分片上传：走隧道时请求体有 100MB 硬上限，单请求再放宽也没用，只能切块分多次送。
   顺带能续传 —— init 会告诉你已经收到哪些块，跳过它们接着传就行。 */
/* 续传要能跨「这次失败、下次再来」，就得把 upload_id 记在本地 —— 只存在内存里的话，
   每次重来都是全新的会话，服务端那边已经收到的块永远用不上（等于没有续传）。
   key 用「名字+大小+修改时间+目标目录」认同一个文件。 */
const dvUpKey = (file, folder) =>
  'dv:up:' + [file.name, file.size, file.lastModified, folder].join('|');

/* 网络抖一下就重试。
   隧道掉线是家常便饭（实测一天十几次，日志里是「Lost connection with the edge」），
   传 100MB 要二十多个来回，中间必然撞上一次 —— 一片没传成就让整份失败，
   等于大文件永远传不上去。分片是按序号落盘的，重传同一片幂等，所以退避重试是安全的。

   只重试**网络层**的失败（fetch 抛 TypeError）。服务端明确拒绝的（会话不存在、
   块号不合法、传的比说好的多、未登录）重试多少次都是同一个答案，直接抛出去。 */
const DV_BACKOFF = [1000, 3000, 6000];
const dvNetErr = (e) => e instanceof TypeError
  || /Failed to fetch|Load failed|NetworkError|网络中断/i.test(e && e.message || '');
async function dvRetry(fn) {
  for (let t = 0; ; t++) {
    try { return await fn(); } catch (e) {
      if (t >= DV_BACKOFF.length || !dvNetErr(e)) throw e;
      await new Promise(r => setTimeout(r, DV_BACKOFF[t]));
    }
  }
}

/* 取文件的第 [start, start+len) 段。

   普通 File 直接 slice 就有。桌面壳送来的大文件是个例外：它的**真身在壳那边的磁盘上**，
   浏览器里只有一份「名字 + 大小」的壳子（见 desktop.js 的大文件通道）—— 2GB 的文件
   base64 之后是 2.7GB 的 JS 源码，整个塞进网页 run_javascript 当场就死。
   那种文件自带一个 __part(异步)，要哪一片才现问壳要哪一片，内存里同时只有 4MB。 */
function dvPartOf(file, start, len) {
  if (typeof file.__part === 'function') return file.__part(start, start + len);
  return Promise.resolve(file.slice(start, start + len));
}

/* 分片上传通道。opts.target 决定这份文件最后落到哪：
     'drive'     → 云盘的 opts.folder 目录（默认）
     'materials' → 资料库的 opts.board 分类
   后端是同一条路（init → 每片 → done），done 按会话里记下的 target 分流。
   资料库原先是「一整个请求发完」，撞的是 64MB 全局上限、走隧道时更是 100MB 就断；
   接到这条通道上，顺带白拿断点续传。 */
async function chunkUpload(file, opts, onProg) {
  const o = opts || {};
  const target = o.target || 'drive';
  const folder = o.folder || '';
  /* 续传的 key 要把目标也算进去：同一个文件传去云盘和传去资料库是两回事，
     共用一个 upload_id 会把「已经收到的块」张冠李戴。
     云盘那支照旧只用 folder —— 换了写法就等于把大家浏览器里**正传到一半**的会话号
     全变成认不出来的孤儿，下次打开只能从头再传一遍。 */
  const key = dvUpKey(file, target === 'materials' ? 'materials:' + (o.board || '') : folder);
  let id = lsGet(key), had = new Set();
  if (id) {
    try {                                  // 会话还在就接着传
      had = new Set((await api('/api/drive/chunk/' + id)).received || []);
    } catch (_) { id = null; lsDel(key); }  // 过期/被清了 → 从头来
  }
  if (!id) {
    const init = await api('/api/drive/chunk/init', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: file.name, folder, size: file.size, mime: file.type || '',
                             target, board: o.board || '', title: o.title || '' }) });
    id = init.upload_id;
    had = new Set(init.received || []);
    lsSet(key, id);
  }
  /* 片与片之间并发。串行时每传完一片都要等一个完整的往返才开下一片，
     走隧道那条路（边缘在洛杉矶）一个来回就是大半秒 —— 100MB 的文件光「等」就等掉几十秒。
     后端每片写自己的文件、done 时才按序号合并，所以乱序到达是安全的。 */
  const n = Math.ceil(file.size / DV_CHUNK);
  const partSize = i => Math.min(file.size, (i + 1) * DV_CHUNK) - i * DV_CHUNK;
  let acked = 0, next = 0;
  for (let i = 0; i < n; i++) if (had.has(i)) acked += partSize(i);   // 续传：已在服务端的先记上
  onProg(acked);
  const sendPart = async () => {
    while (next < n) {
      const i = next++;
      if (had.has(i)) continue;
      /* 取这一片的字节。**先取好再进 dvRetry**：重试是给网络失败准备的，
         同一片重读一遍盘既慢也没意义。 */
      const part = await dvPartOf(file, i * DV_CHUNK, partSize(i));
      await dvRetry(() => api('/api/drive/chunk/' + id + '/' + i, { method: 'POST', body: part }));
      // 进度按「传成了多少字节」累加，不能再用 end：并发下片是乱序完成的，
      // 拿末尾位置当进度会让进度条跳来跳去
      acked += partSize(i); onProg(acked);
    }
  };
  await Promise.all(Array.from({ length: Math.min(DV_CHUNK_PAR, n) }, sendPart));
  const row = await dvRetry(() => api('/api/drive/chunk/' + id + '/done', { method: 'POST' }));
  lsDel(key);                              // 传成了，别把死 id 留到下次
  return row;
}

/* ---- 省流上传 ----
   家里上行就那么点（走隧道更是绕一趟洛杉矶），手机拍的证件照一张 3~4MB，
   十几张就是好几分钟。缩到长边 2000px 之后一张只剩几百 KB，**同一批快五六倍**。
   默认关：证件、证书这类材料该传原图，清晰度是它的全部意义 —— 要省流得自己按一下。 */
const DV_SLIM_PX = 2000;                  // 长边缩到这个像素：证书上的编号、印章字仍然认得出
const DV_SLIM_Q = 0.85;
const DV_SLIM_MIN = 600 * 1024;           // 比这还小的图压了也省不下什么，别白折腾
const DV_SLIM_EXT = ['.jpg', '.jpeg', '.png', '.webp'];
const dvSlimOn = () => lsGet('dv:slim') === '1';
function dvSlimLabel() {
  const b = $('#dv-slim');
  if (b) b.textContent = '🪶 省流上传：' + (dvSlimOn() ? '开' : '关');
}
dvSlimLabel();
$('#dv-slim').onclick = () => {
  lsSet('dv:slim', dvSlimOn() ? '0' : '1');
  dvSlimLabel();
  toast(dvSlimOn() ? '开了：图片会先缩到长边 2000px 再传（省流量、快很多）'
    : '关了：图片一律按原图上传');
};

// 解码排一条队，一次只解一张（为什么见 dvShrink 里那段注释）
let _dvDecodeChain = Promise.resolve();
function dvDecodeSerial(file) {
  const job = () => createImageBitmap(file);
  const p = _dvDecodeChain.then(job, job);
  _dvDecodeChain = p.then(bm => { void bm; }, () => {});   // 一张解不开不能堵住后面的
  return p;
}

/* 缩图。任何一步不成就返回原文件 —— 省流是锦上添花，不能因为它把「传得上去」搞没了。
   （HEIC 在多数浏览器里解不出来，就是靠这条兜底原样上传。） */
async function dvShrink(file) {
  const ext = (file.name.match(/\.[^.]+$/) || [''])[0].toLowerCase();
  if (!dvSlimOn() || file.size < DV_SLIM_MIN || !DV_SLIM_EXT.includes(ext)) return file;
  // 桌面壳送来的大文件在浏览器里没有真身（只有 __part 能按片取），解不了码也没必要缩
  if (typeof file.__part === 'function') return file;
  try {
    /* 解码原图这一步排队做（DV_PARALLEL 个文件是同时在传的）。
       安卓 WebView 上同时读多个 content:// URI 会互相串成同一份数据 —— 小记那边
       就是这么把三张不同的图传成同一张的（见 notes.js 的 readFileSerial）。
       缩图本来就是 CPU 活，排着队做几乎不影响总时长；网络那一段照旧并发。 */
    const bm = await dvDecodeSerial(file);
    const k = DV_SLIM_PX / Math.max(bm.width, bm.height);
    if (k >= 1) { bm.close(); return file; }        // 本来就不大，缩了只会更糊
    const cv = document.createElement('canvas');
    cv.width = Math.round(bm.width * k); cv.height = Math.round(bm.height * k);
    cv.getContext('2d').drawImage(bm, 0, 0, cv.width, cv.height);
    bm.close();
    const blob = await new Promise(r => cv.toBlob(r, 'image/jpeg', DV_SLIM_Q));
    if (!blob || blob.size >= file.size) return file;   // 没省下来就别换
    // 统一出 JPEG，名字也跟着改，免得一份 .png 里躺着 jpeg 数据
    const name = file.name.replace(/\.[^.]+$/, '') + '.jpg';
    return new File([blob], name, { type: 'image/jpeg', lastModified: file.lastModified });
  } catch (_) { return file; }
}

/* 关着省流、又一口气传一大堆图时，提一次（**只提一次**：每次都弹就成了骚扰）。
   这条提示存在的理由很实在 —— 手机走公网隧道传十几张证件照要好几分钟，
   而多数人并不知道有这么个开关。 */
const DV_SLIM_HINT = 20 * 1024 * 1024;
function dvSlimHint(items) {
  if (dvSlimOn() || lsGet('dv:slimhint') === '1') return;
  const big = items.filter(it => DV_SLIM_EXT.includes((it.file.name.match(/\.[^.]+$/) || [''])[0].toLowerCase()))
    .reduce((a, it) => a + (it.file.size || 0), 0);
  if (big < DV_SLIM_HINT) return;
  lsSet('dv:slimhint', '1');
  toast('这批图片有 ' + fSize(big) + '。工具栏「🪶 省流上传」开着能快好几倍（证件原图就别开）');
}

async function dvUploadOne(file, folder, onProg) {
  // 先问一句「这份内容你有没有」：换个目录再放一份、换台设备重传，都是常事
  const hash = await dvSha256(file);
  if (hash) {
    try {
      const d = await api('/api/drive/instant', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sha256: hash, name: file.name, folder }) });
      if (d && d.hit) { onProg(file.size); return d; }
    } catch (_) { /* 秒传没成就老老实实传 */ }
  }
  /* 整发这条路原来一次不成就算失败。走隧道时「Lost connection with the edge」一天十几次，
     几 MB 的照片正撞上就白传 —— 和分片一样给它退避重试（重来时进度从 0 起，会往回跳一格）。 */
  return file.size > DV_CHUNK_MIN
    ? dvUploadChunked(file, folder, onProg)
    : dvRetry(() => dvUploadWhole(file, folder, onProg));
}

// 云盘这一侧的老名字留着：它就是「落点 = 云盘」的 chunkUpload，调用方和测试都还认它
function dvUploadChunked(file, folder, onProg) {
  return chunkUpload(file, { target: 'drive', folder }, onProg);
}

function dvUploadWhole(file, folder, onProg) {
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
  /* 也收一串裸 File —— 桌面壳（desktop.js 的 __onDropFiles）就是那么调的。
     P0 把入参从 File[] 改成 {file,folder}[] 时漏了它，filter 把裸 File 全滤掉，
     桌面版拖拽上传于是**一声不吭地什么都不做**。这里认下两种形状，别再靠调用方记得。 */
  items = (items || []).map(it => (it instanceof File ? { file: it, folder: '' } : it))
    .filter(it => it && it.file);
  if (!items.length) return;
  /* 分母要按「实际要传的字节」算，所以放在数组里跟着走：开了省流之后，
     一张图压完可能只剩五分之一，还拿原始大小当分母的话进度条永远到不了头。 */
  const sizes = items.map(it => it.file.size || 0);
  const sent = new Array(items.length).fill(0);       // 每个文件已发字节，汇总成总进度
  let done = 0, ok = 0, fail = 0, next = 0;
  const tick = () => dvProg(sent.reduce((a, b) => a + b, 0), sizes.reduce((a, b) => a + b, 0),
                            '上传中 ' + done + '/' + items.length);
  dvSlimHint(items);
  tick();
  const worker = async () => {
    while (next < items.length) {
      const i = next++;
      const dest = [dvFolder, items[i].folder].filter(Boolean).join('/');
      try {
        const f = await dvShrink(items[i].file);      // 没开省流 / 不是图片时原样返回
        sizes[i] = f.size || 0;
        await dvUploadOne(f, dest, n => { sent[i] = n; tick(); });
        ok++;
      } catch (err) { fail++; toast(items[i].file.name + '：' + err.message, true); }
      sent[i] = sizes[i];                  // 失败的也记满，否则进度条永远差一截停在那
      done++; tick();
    }
  };
  await Promise.all(Array.from({ length: Math.min(DV_PARALLEL, items.length) }, worker));
  $('#dv-prog').classList.add('hidden');
  toast(fail ? '上传完成 ' + ok + ' 个，失败 ' + fail + ' 个' : '已上传 ' + ok + ' 个', fail > 0 && ok === 0);
  /* **要 await**：不等的话 dvUpload 在列表刷新之前就 resolve 了，
     「上传完成」这个承诺就不包含「你能看见它了」。desktop.js 那两处
     `p = dvUpload(list)` 正是拿这个 promise 当「传完了」用的。
     测试里的表现更直接：await dvUpload(...) 一返回就拆掉 DOM，
     loadDrive 的异步续体随后撞上已经销毁的 document（querySelector of undefined）。 */
  await loadDrive();
  /* 报一句战果。这里**不抛**：一批里坏了一个不该把整批算作失败（那正是上面 catch 的用意），
     但调用方得有办法知道到底成没成 —— 桌面壳的大文件通道就靠它决定回执里的 ok。 */
  return { ok, fail };
}

$('#dv-upfile').addEventListener('change', e => {
  const items = [...e.target.files].map(f => ({ file: f, folder: '' }));
  e.target.value = '';
  dvUpload(items);
});
/* 桌面壳（WebKitGTK）不认 <input webkitdirectory> —— 那是 Chromium 的能力，
   在壳里点「传文件夹」只会弹出选**文件**的框。所以桌面版改走原生的选目录对话框，
   由壳把整棵树摊平、带相对路径送回 __onPickedFiles。 */
const DV_PICKDIR_VER = 4.8;        // 壳从这个版本起才认 pickdir
function dvPickFolderNative() {
  /* 老壳收到不认识的消息是**静默丢弃**的 —— 那样点「传文件夹」就是一点反应都没有。
     所以先看版本：够新才走原生选目录，不够新就返回 false，让它退回 WebKit 自己的
     文件选择框（只能选文件，但至少看得见东西弹出来，不像坏了）。 */
  if (!(parseFloat(DESKTOP_VER || '0') >= DV_PICKDIR_VER)) return false;
  try {
    window.webkit.messageHandlers.gk.postMessage(JSON.stringify({ a: 'pickdir' }));
    return true;
  } catch (_) { return false; }
}
/* 不在云盘页时收到文件（壳里粘贴/拖放）：先把人带到云盘再传，否则传完看不见。
   要把 dvUpload 的 promise 交回去 —— 壳的背压等的就是它。 */
function dvOpenAndUpload(list) {
  openDrive();
  return new Promise(res => setTimeout(() => res(dvUpload(list)), 0));
}
$('#dv-upfolder').addEventListener('click', e => {
  // 桌面壳里拦下来走原生选目录，别让 WebKit 弹出那个只能选文件的框
  if (IS_DESKTOP && dvPickFolderNative()) e.preventDefault();
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
/* 在云盘页 Ctrl+V 粘图/粘文件 → 上传到当前文件夹（浏览器；桌面壳走 __onPasteImage / __onPickedFiles）。
   注意 #dv-search 里粘文字要放行，那是在搜文件名。 */
document.addEventListener('paste', e => {
  if (e.defaultPrevented) return;
  if ((stack[stack.length - 1] || {}).view !== 'drive') return;
  const t = e.target;
  if (t && t.closest && t.closest('#ai-panel, #qnote, .composer, input, textarea')) return;
  const fs = clipFiles(e);
  if (fs.length) { e.preventDefault(); dvUpload(fs); return; }
  if (dvClip.length) { e.preventDefault(); dvPaste(); }   // 系统剪贴板没文件 → 粘贴应用内复制的云盘文件
});
$('#dv-newfolder').onclick = async () => {
  const name = await appPrompt('新建文件夹', '', '');
  if (!name || !name.trim()) return;
  try { await api('/api/drive/folder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim(), parent: dvFolder }) }); loadDrive(); }
  catch (err) { toast(errMsg(err), true); }
};
/* 发送到聊天。ids 是云盘条目（可以是一批），isDir 只用来在提示里说清楚会打包。
   接口是按条目一个个发的，一次选好对象、循环发完，别让人对每个文件都选一遍。 */
async function driveSend(ids, isDir) {
  const list = (Array.isArray(ids) ? ids : [ids]).filter(Boolean);
  if (!list.length) return;
  const pick = await pickChatTargets(list.length > 1 ? '发送这 ' + list.length + ' 项到' : '发送到',
                                     isDir ? '文件夹会先打包成 zip 再发出去。' : '');
  if (!pick) return;
  let ok = 0, fail = 0;
  for (const id of list) {
    try {
      await api('/api/drive/' + id + '/send', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(pick) });
      ok++;
    } catch (e) { fail++; toast(errMsg(e), true); }
  }
  if (ok) toast(fail ? ('已发送 ' + ok + ' 项，失败 ' + fail + ' 项') : sentText(ok, pick));
}
const sentText = (n, pick) => '已发送' + (n > 1 ? ' ' + n + ' 项' : '') + '给 '
  + [pick.users.length ? pick.users.length + ' 位好友' : '',
     pick.groups.length ? pick.groups.length + ' 个小组' : ''].filter(Boolean).join('、');

/* 选发送对象：好友 + 我在的小组，可多选、可跨组，一次发多个目标。
   云盘、资料库、聊天里的「发送到聊天…」共用这一个 —— 它们发的本来就是同一件事。
   返回 {users:[], groups:[]}，取消返回 null。 */
async function pickChatTargets(title, hint) {
  let d;
  try { d = await api('/api/chat/targets'); }
  catch (e) { toast(errMsg(e), true); return null; }
  const friends = d.friends || [], groups = d.groups || [];
  if (!friends.length && !groups.length) {
    toast('还没有好友、也不在任何小组里。先去「聊天」加个好友或建个小组', true);
    return null;
  }
  return new Promise(res => {
    const el = $('#mat-share-sheet');
    const rows = (kind, list, icon, label, sub) => list.map(x => `
      <label class="ms-row"><input type="checkbox" data-tk="${kind}" value="${x.id}">
        <span class="ms-ic">${artEm(icon)}</span><span>${esc(label(x))}</span>
        ${sub && sub(x) ? `<span class="ms-sub">${esc(sub(x))}</span>` : ''}</label>`).join('');
    el.innerHTML = `<div class="ns-mask" data-sheet-close></div><div class="ns-panel">
      <div class="ns-handle"></div><div class="ns-title">${esc(title || '发送到')}</div>
      <p class="acct-hint" style="padding:0 16px;margin:0 0 6px">${esc(hint || '')}选中的每一个都会收到一条文件消息，好友和小组可以一起选。</p>
      <div class="ms-list">
        ${friends.length ? '<div class="ms-grp">好友</div>' + rows('u', friends, '👤', f => f.username) : ''}
        ${groups.length ? '<div class="ms-grp">我的小组</div>'
          + rows('g', groups, '👥', g => g.title, g => (g.n || 0) + ' 人') : ''}
      </div>
      <div class="ms-acts">
        <button class="btn" id="tk-cancel">取消</button>
        <button class="btn primary" id="tk-ok" disabled>发送</button>
      </div></div>`;
    el.classList.remove('hidden');
    const done = v => { el.classList.add('hidden'); res(v); };
    const picked = k => [...el.querySelectorAll(`input[data-tk="${k}"]:checked`)].map(i => +i.value);
    // 一个都没选就不该点得动「发送」——否则点下去只能弹一句报错
    const sync = () => {
      const n = picked('u').length + picked('g').length;
      $('#tk-ok').disabled = !n;
      $('#tk-ok').textContent = n ? '发送（' + n + '）' : '发送';
    };
    el.querySelectorAll('input[data-tk]').forEach(i => { i.onchange = sync; });
    el.querySelector('.ns-mask').onclick = () => done(null);
    $('#tk-cancel').onclick = () => done(null);
    $('#tk-ok').onclick = () => done({ users: picked('u'), groups: picked('g') });
  });
}
