/* 多端自动同步：数据变了自动刷新当前视图
 *
 * 由 app.js 按它自己的区段边界切出（原 L8054-8387）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, AI_FOLDER, aiCurProject, ALL_BOARDS, anchorMenu, api, appConfirm, appPrompt,
   artEm, chSwitch, chTab, crInRoom, crLoad, DESKTOP_VER, errMsg, esc, fabClamp, init,
   inkHere, loadAiHome, loadCsBoard, loadDrive, loadEntries, loadFanwen, loadFeed,
   loadFeedTags, loadGaikuo, loadGongwen, loadMaterials, loadNews, loadNotebooks,
   loadPartyDict, loadPlanLog, loadReview, loadShared, loadSucai, loadVideos, loadWrongq,
   lsGet, lsSet, matBoard, matCustomBoards, matPickMembers, ME, openAI, openAiProject,
   padToggle, push, qnOpen, refreshChatBadge, shotAsk, stack, toast, wrSwitch, wrTab */

/* ============= 多端自动同步：数据变了自动刷新当前视图，无需手动更新 ============= */
let _syncToken = null, _syncBusy = false;
const SYNC_REFRESH = {
  notes: () => { loadFeed(); loadFeedTags(); },
  materials: () => loadMaterials(),
  idiom: () => loadEntries(),
  kb: () => loadNotebooks(),
  wrongq: () => loadWrongq(),
  news: () => loadNews(),
  videos: () => loadVideos(),
  fanwen: () => loadFanwen(),
  drive: () => loadDrive(),
  chat: () => { chSwitch(chTab); if (crInRoom()) crLoad(false); },
  gaikuo: () => loadGaikuo(),
  gongwen: () => loadGongwen($('#gw-q').value.trim()),
  planlog: () => loadPlanLog(),
  partydict: () => loadPartyDict(),
  sucai: () => loadSucai(),
  write: () => wrSwitch(wrTab),        // 原先调 loadWrite()，可它在 0134dfe 那次被误删了（只剩这处引用）
  review: () => { if ($('#rv-card-wrap').classList.contains('hidden')) loadReview(); },  // 复习进行中不打断会话
  tasks: () => { const a = document.querySelector('#view-tasks .tk-tab.active'); if (a && a.dataset.tkt === 'shared') loadShared(); },
  csboard: () => loadCsBoard(),
};
function _syncEditing() {
  // 正在编辑/弹窗打开时不打扰（块编辑器、小记编辑器有内容、任何弹层）
  const v = stack.length ? stack[stack.length - 1].view : '';
  if (v === 'doc' || v === 'wqadd') return true;
  const cp = $('#cp-content'); if (cp && cp.value.trim()) return true;
  if (document.querySelector('.modal:not(.hidden)') || document.querySelector('.note-sheet:not(.hidden)')
      || document.querySelector('.ctxmenu:not(.hidden)')) return true;
  return false;
}
async function checkSync() {
  if (_syncBusy || document.hidden || !ME) return;
  _syncBusy = true;
  try {
    const d = await api('/api/sync');
    if (_syncToken === null) { _syncToken = d.token; return; }
    if (d.token !== _syncToken) {
      _syncToken = d.token;
      if (!_syncEditing()) {
        const v = stack.length ? stack[stack.length - 1].view : '';
        if (SYNC_REFRESH[v]) SYNC_REFRESH[v]();
      }
    }
  } catch (e) {
    // 网络抖一下很正常，下次轮询自然补上 —— 那种静默就好。
    // 但这里同时也会吞掉 SYNC_REFRESH[v]() 里的**代码错误**：loadWrite 那个
    // ReferenceError 就是被这一行藏了整整一个版本（见 9edf460），期间写作页的
    // 自动同步一直是坏的、毫无迹象。所以两者要分开对待。
    if (e instanceof ReferenceError || e instanceof TypeError) {
      console.error('[同步] 刷新处理器有 bug（不是网络问题）：', e);
    } else {
      console.debug('[同步] 本次跳过：%s', (e && e.message) || e);
    }
  } finally { _syncBusy = false; }
}
setInterval(checkSync, 30000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) checkSync(); });
window.addEventListener('focus', checkSync);
// 聊天未读角标：每 15 秒问一次（比同步频些，聊天要及时点）
setInterval(() => { if (ME && !document.hidden) refreshChatBadge(); }, 15000);

/* 锚定小菜单（⋮ 菜单 / + 面板）：点菜单和触发按钮之外的任何地方就关闭。
   一次性把几个 ctxmenu 一起收，别处点了别处的 ⋮ 也顺手把上一个关掉。
   .input-tools（手机端由 ➕ 弹出的工具面板）没有唯一 id，按 class 一起处理。 */
const CTX_MENU_IDS = ['mat-menu', 'ai-chatmenu', 'node-menu', 'ai-attsheet'];
const CTX_MENU_TRIGGERS = '.mat-more, [data-aimenu], [data-nodedots], #ai-attach, ' +
  '#ai-plus, #cr-plus, .input-tools, ' + CTX_MENU_IDS.map(id => '#' + id).join(', ');
document.addEventListener('click', e => {
  if (e.target.closest(CTX_MENU_TRIGGERS)) return;
  CTX_MENU_IDS.forEach(id => $('#' + id).classList.add('hidden'));
  // .input-tools 桌面端是常驻工具行，只有手机端（➕ 弹出）才需要点别处收起
  if (document.body.classList.contains('mobile-ui')) {
    document.querySelectorAll('.input-tools').forEach(el => el.classList.add('hidden'));
  }
});

// 外部链接一律新开/交给系统浏览器，避免在应用内跳走后无法返回
document.addEventListener('click', e => {
  const a = e.target.closest('a[href]'); if (!a) return;
  const href = a.getAttribute('href') || '';
  if (/^https?:\/\//i.test(href) && href.indexOf(location.host) < 0) {
    e.preventDefault();
    try { if (window.GongkaoNative && window.GongkaoNative.openUrl) { window.GongkaoNative.openUrl(href); return; } } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }
    window.open(href, '_blank', 'noopener');
  }
});

init();
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});

/* 资料库：分类下拉选「新建分类」时弹输入 */
$('#up-board').addEventListener('change', async e => {
  if (e.target.value !== '__new__') return;
  const name = await appPrompt('新建分类', '分类名，如：晨读');
  const v = (name || '').trim().slice(0, 20);
  if (v) {
    if (!matCustomBoards.includes(v) && !ALL_BOARDS.includes(v)) matCustomBoards.push(v);
    const opt = document.createElement('option');
    opt.textContent = v; opt.value = v;
    e.target.insertBefore(opt, e.target.querySelector('option[value="__new__"]'));
    e.target.value = v;
  } else e.target.value = '';
});

/* 资料库：拖拽 / 粘贴 直接上传（网页端；APP 端用系统分享接收） */
async function uploadDropped(files) {
  if (!files.length) return;
  toast('上传中…（' + files.length + ' 个）');
  let ok = 0;
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file, file.name || ('粘贴_' + Date.now() + '.png'));
    fd.append('board', matBoard);
    fd.append('section', '');
    fd.append('title', '');
    try { await api('/api/materials', { method: 'POST', body: fd }); ok++; }
    catch (e) { toast((file.name || '文件') + '：' + e.message, true); }
  }
  if (ok) { toast('已上传 ' + ok + ' 个'); loadMaterials(); }
}
(function () {
  const mv = $('#view-materials'); if (!mv) return;
  ['dragover', 'dragenter'].forEach(ev => mv.addEventListener(ev, e => {
    e.preventDefault(); mv.classList.add('drag-on');
  }));
  mv.addEventListener('dragleave', e => { if (e.target === mv) mv.classList.remove('drag-on'); });
  mv.addEventListener('drop', e => {
    e.preventDefault(); mv.classList.remove('drag-on');
    const fs = [...(e.dataTransfer ? e.dataTransfer.files : [])];
    if (fs.length) uploadDropped(fs);
    // 桌面版本该由壳接管（GTK 层）。要是这里还被触发且没文件，说明壳没接管成功 → 说清楚，别静默
    else if (window.__desktop) toast('桌面壳没接管拖放（请关掉应用重开一次）', true);
    else toast('没拿到文件，换「+ 上传资料」按钮试试', true);
  });
  document.addEventListener('paste', e => {
    const st = stack[stack.length - 1];
    if (!st || st.view !== 'materials') return;
    const fs = [...((e.clipboardData && e.clipboardData.files) || [])];
    if (fs.length) { e.preventDefault(); uploadDropped(fs); }
  });
})();

/* AI 会话卡 ⋮ 菜单：置顶/重命名/移动项目/移出项目/删除 */
let aiMenuCtx = null, aiMenuBtn = null;
function openAiChatMenu(btn, id, title, projId, starred) {
  aiMenuCtx = { id, title, projId: projId ? +projId : null, starred };
  aiMenuBtn = btn;
  const ps = $('#ai-panel')._projects || [];
  $('#acm-list').innerHTML = `
    <button data-acm="star">${starred ? '☆ 取消置顶' : '⭐ 置顶'}</button>
    <button data-acm="rename">${artEm('✏️')} 重命名</button>
    ${ps.length ? `<button data-acm="move">${AI_FOLDER} 移动到项目 ›</button>` : ''}
    ${aiMenuCtx.projId ? '<button data-acm="unproj">' + artEm("📤") + ' 移出项目</button>' : ''}
    <button data-acm="del" class="acm-danger">${artEm('🗑')} 删除对话</button>`;
  anchorMenu($('#ai-chatmenu'), btn);
}
$('#ai-chatmenu').addEventListener('click', async e => {
  const mv = e.target.closest('[data-acmproj]');
  if (mv && aiMenuCtx) {
    $('#ai-chatmenu').classList.add('hidden');
    try {
      await api('/api/aichat/chats/' + aiMenuCtx.id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: +mv.dataset.acmproj }) });
      toast('已移动'); await loadAiHome();
      if (aiCurProject) openAiProject(aiCurProject.id);   // 正只看某个项目时，刷完再回到那份筛选
    } catch (err) { toast(errMsg(err), true); }
    return;
  }
  const b = e.target.closest('[data-acm]');
  if (!b || !aiMenuCtx) return;
  const act = b.dataset.acm;
  if (act === 'move') {
    const ps = $('#ai-panel')._projects || [];
    $('#acm-list').innerHTML = '<div class="acm-tip">移动到哪个项目：</div>'
      + ps.map(p => `<button data-acmproj="${p.id}">${AI_FOLDER} ${esc(p.name)}</button>`).join('');
    if (aiMenuBtn) anchorMenu($('#ai-chatmenu'), aiMenuBtn);   // 项目列表比原菜单长，重新贴位防止探出屏幕
    return;
  }
  $('#ai-chatmenu').classList.add('hidden');
  try {
    if (act === 'star') {
      await api('/api/aichat/chats/' + aiMenuCtx.id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: !aiMenuCtx.starred }) });
    } else if (act === 'rename') {
      const t = await appPrompt('重命名对话', '', aiMenuCtx.title);
      if (!t || !t.trim()) return;
      await api('/api/aichat/chats/' + aiMenuCtx.id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: t.trim() }) });
    } else if (act === 'unproj') {
      await api('/api/aichat/chats/' + aiMenuCtx.id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: null }) });
    } else if (act === 'del') {
      if (!(await appConfirm('删除这个对话？'))) return;
      await api('/api/aichat/chats/' + aiMenuCtx.id, { method: 'DELETE' });
    }
    await loadAiHome();
    if (aiCurProject) openAiProject(aiCurProject.id);
  } catch (err) { toast(errMsg(err), true); }
});

/* 悬浮工具球：点一下在四周扇出「AI / 草稿纸」；按住可拖到任意位置（位置记忆） */
(function () {
  const fab = $('#fab'), main = $('#fab-btn');
  if (!fab || !main) return;
  try {
    const p = JSON.parse(lsGet('aifab') || 'null');
    if (p) { fab.style.left = p.x + 'px'; fab.style.top = p.y + 'px'; fab.style.right = 'auto'; fab.style.bottom = 'auto'; }
  } catch (_) { /* 存的悬浮球位置读坏了就用默认位置 */ }
  requestAnimationFrame(fabClamp);          // 上次记的位置可能落在这个窗口外面，先夹回来

  function dirs() {                       // 扇出方向：别扇到屏幕外
    const r = fab.getBoundingClientRect();
    fab.classList.toggle('dir-l', r.left > innerWidth / 2);
    fab.classList.toggle('dir-r', r.left <= innerWidth / 2);
    fab.classList.toggle('dir-up', r.top > innerHeight * .22);
    fab.classList.toggle('dir-dn', r.top <= innerHeight * .22);
  }
  window.fabClose = () => fab.classList.remove('open');
  // 竖排菜单：按「实际可见的按钮数」把胶囊一条条往上/下码（截图在手机端隐藏，个数会变）。
  // 只算纵向偏移，横向贴哪一侧由 CSS 的 dir-l/dir-r 决定；加工具只是多码一条，不会挤。
  function layoutFab() {
    const acts = [...fab.querySelectorAll('.fab-act')].filter(b => !b.hidden);
    const step = 50;                              // 每条胶囊 42px 高 + 8px 间距
    acts.forEach((b, i) => {
      b.style.setProperty('--fy', ((i + 1) * step) + 'px');
    });
  }
  function toggle() { dirs(); layoutFab(); fab.classList.toggle('open'); }

  let sx = 0, sy = 0, ox = 0, oy = 0, moved = false, dragging = false;
  main.addEventListener('pointerdown', e => {
    dragging = true; moved = false;
    sx = e.clientX; sy = e.clientY;
    const r = fab.getBoundingClientRect(); ox = r.left; oy = r.top;
    main.setPointerCapture(e.pointerId);
  });
  main.addEventListener('pointermove', e => {
    if (!dragging) return;
    const dx = e.clientX - sx, dy = e.clientY - sy;
    if (Math.abs(dx) + Math.abs(dy) > 6) { moved = true; fab.classList.remove('open'); }
    if (!moved) return;
    const x = Math.min(Math.max(4, ox + dx), innerWidth - fab.offsetWidth - 4);
    const y = Math.min(Math.max(4, oy + dy), innerHeight - fab.offsetHeight - 4);
    fab.style.left = x + 'px'; fab.style.top = y + 'px';
    fab.style.right = 'auto'; fab.style.bottom = 'auto';
  });
  main.addEventListener('pointerup', e => {
    dragging = false;
    if (moved) {
      const r = fab.getBoundingClientRect();
      lsSet('aifab', JSON.stringify({ x: r.left, y: r.top }));
      dirs(); e.preventDefault(); e.stopPropagation();
    } else toggle();
  });
  main.addEventListener('click', e => { if (moved) { e.preventDefault(); e.stopPropagation(); moved = false; } }, true);

  $('#fab-ai').onclick = () => { fabClose(); openAI(); };
  $('#fab-note').onclick = () => { fabClose(); qnOpen(); };   // 📒 随手记（浮层，不跳走）
  $('#fab-pad').onclick = () => { fabClose(); padToggle(); };
  // 📷 截图只有电脑桌面版有（壳负责抓屏）；手机截图交给系统，不放这
  if (window.__desktopShot) $('#fab-shot').hidden = false;
  $('#fab-shot').onclick = () => { fabClose(); shotAsk('menu'); };
  // ✏️ 批注：给当前页面盖一层手写批注
  $('#fab-ink').onclick = () => { fabClose(); inkHere(); };
  document.addEventListener('pointerdown', e => {          // 点别处收起扇出
    if (fab.classList.contains('open') && !e.target.closest('#fab')) fabClose();
  }, true);
})();

/* 资料库条目 ⋮ 菜单：分享 / 重命名 / 复制 / 下载 / 删除 */
const MAT_SHARE_VER = 5.0;      // 桌面壳从这个版本起才认 sharefile（会弹应用列表；老壳只会静默丢弃）
/* 安卓壳分享大文件时，得先整份下到本地才能交给系统分享面板。几十秒里只有一句
   「正在准备分享…」，看不出是在跑还是卡死了 —— 所以让壳把百分比喂回来。
   老壳不会调这个函数，那边的行为不变。 */
window.__shareProgress = pct => {
  if (pct < 0) return;                                   // 失败：壳自己会弹 Toast，别再叠一层
  toast(pct >= 100 ? '准备好了，选个应用发送吧' : '正在准备分享… ' + pct + '%');
};
let matMenuCtx = null;
function openMatMenu(btn, id, name, ext) {
  matMenuCtx = { id, name, ext };
  $('#ai-chatmenu').classList.add('hidden');
  anchorMenu($('#mat-menu'), btn);
}
$('#mat-menu').addEventListener('click', async e => {
  const teamBtn = e.target.closest('[data-mm="team"]');
  if (teamBtn) {                                  // 共享给指定队友（可多选，取消勾选=收回）
    $('#mat-menu').classList.add('hidden');
    const mid = matMenuCtx.id;
    try {
      const d = await api('/api/materials/' + mid + '/share');
      if (!d.members.length) { toast('你还没有队友（去「任务清单 → 互监待办」组队）', true); return; }
      const pick = await matPickMembers(d.members);
      if (pick === null) return;
      const r = await api('/api/materials/' + mid + '/share', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to: pick }),
      });
      toast(r.n ? ('已共享给 ' + r.n + ' 位队友') : '已取消共享');
      loadMaterials();
    } catch (err) { toast(errMsg(err), true); }
    return;
  }
  const b = e.target.closest('[data-mm]');
  if (!b || !matMenuCtx) return;
  const { id, name } = matMenuCtx;
  $('#mat-menu').classList.add('hidden');
  const act = b.dataset.mm;
  if (act === 'share') {
    const url = '/api/materials/' + id + '/download';
    try {
      if (window.GongkaoNative && typeof GongkaoNative.shareFile === 'function') {
        GongkaoNative.shareFile(location.origin + url, name);   // 进度条由安卓壳自己弹
        return;
      }
    } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }
    // 桌面壳（WebKitGTK 没有系统分享面板）：交给壳去下载 + 弹「用哪个应用打开」的应用列表。
    // 老壳不认这条消息且**静默丢弃**，所以先卡版本，不够新就退回下面的下载兜底。
    if (window.__desktop && parseFloat(DESKTOP_VER || '0') >= MAT_SHARE_VER) {
      try {
        window.webkit.messageHandlers.gk.postMessage(
          JSON.stringify({ a: 'sharefile', url: location.origin + url, name }));
        return;
      } catch (_) { /* 桥不在，往下走兜底 */ }
    }
    // 浏览器支持「分享文件本身」的（部分桌面 Chrome / 手机浏览器）→ 直接弹系统分享，分享文件
    if (navigator.share && navigator.canShare) {
      try {
        const resp = await fetch(url);
        if (resp.ok) {
          const blob = await resp.blob();
          const file = new File([blob], name, { type: blob.type || 'application/octet-stream' });
          if (navigator.canShare({ files: [file] })) { await navigator.share({ files: [file], title: name }); return; }
        }
      } catch (e) { if (e && e.name === 'AbortError') return; }
    }
    // 都不支持（老桌面壳 / 老浏览器）：把文件下下来 —— 到「下载」文件夹后就能手动发给别人。
    // （要在应用内分享给同学，用菜单里的「👥 共享给队友」。）
    const a = document.createElement('a'); a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    toast('已下载「' + name + '」，可从「下载」文件夹发给他人（应用内分享用「👥 共享给队友」）');
  } else if (act === 'rename') {
    const v = await appPrompt('重命名文档', '', name);
    if (v && v.trim() && v !== name) {
      try { await api('/api/materials/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: v.trim() }) }); toast('已重命名'); loadMaterials(); }
      catch (err) { toast(errMsg(err), true); }
    }
  } else if (act === 'dup') {
    try { await api('/api/materials/' + id + '/duplicate', { method: 'POST' }); toast('已复制一份'); loadMaterials(); }
    catch (err) { toast(errMsg(err), true); }
  } else if (act === 'dl') {
    const a = document.createElement('a'); a.href = '/api/materials/' + id + '/download'; a.download = '';
    document.body.appendChild(a); a.click(); a.remove();
  } else if (act === 'del') {
    if (!(await appConfirm('删除「' + name + '」？'))) return;
    try { await api('/api/materials/' + id, { method: 'DELETE' }); toast('已删除'); loadMaterials(); }
    catch (err) { toast(errMsg(err), true); }
  }
});
