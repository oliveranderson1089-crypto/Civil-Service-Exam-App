/* 多端自动同步 / 主题 / 应用内更新 / 消息中心 / 范文推荐 / 题库解析 / 通知
 *
 * 由 app.js 按它原有的区段边界切出（原 L8054-8871）。顺序即原顺序 —— index.html 里
 * 按同样次序引入，执行序与拆分前逐字节一致。
 *
 * 下面 /* global *​/ 是这个模块的依赖清单：它用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，这就是现成的 import 表。
 */
/* global $, AI_FOLDER, ALL_BOARDS, DESKTOP_VER, IC, IN_APP,
   IS_DESKTOP, ME, aiCurProject, aiProjectId, aiShow, api,
   appConfirm, appPrompt, c, chSwitch, chTab, crInRoom,
   crLoad, esc, fabClamp, fmtSize, init, inkHere,
   loadAiHome, loadCsBoard, loadDrive, loadEntries, loadFanwen, loadFeed,
   loadFeedTags, loadGaikuo, loadGongwen, loadMaterials, loadNews, loadNotebooks,
   loadPartyDict, loadPlanLog, loadReview, loadShared, loadSucai, loadVideos,
   loadWrongq, lsGet, lsSet, matBoard, matCustomBoards, matPickMembers,
   openAI, openAiProject, openChangkao, openChangshi, openChat, openChatroom,
   openCkBoard, openClassics, openCsBoard, openDrafts, openGaikuo, openGongwen,
   openIdiom, openNews, openPartyDict, openPolicyDocs, openReview, openShenlun,
   openSlPaper, openSucai, openTasks, openThBoard, openTheory, openViewerUrl,
   openWorks, openWrongq, padToggle, push, qnOpen, qz,
   refreshChatBadge, render, renderAiProjects, shotAsk, stack, tkSwitch,
   toast, wrSwitch, wrTab */

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
  if (document.querySelector('.modal:not(.hidden)') || document.querySelector('.note-sheet:not(.hidden)')) return true;
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

// 外部链接一律新开/交给系统浏览器，避免在应用内跳走后无法返回
document.addEventListener('click', e => {
  const a = e.target.closest('a[href]'); if (!a) return;
  const href = a.getAttribute('href') || '';
  if (/^https?:\/\//i.test(href) && href.indexOf(location.host) < 0) {
    e.preventDefault();
    try { if (window.GongkaoNative && window.GongkaoNative.openUrl) { window.GongkaoNative.openUrl(href); return; } } catch (_) {}
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
let aiMenuCtx = null;
function openAiChatMenu(id, title, projId, starred) {
  aiMenuCtx = { id, title, projId: projId ? +projId : null, starred };
  const ps = $('#ai-panel')._projects || [];
  $('#acm-list').innerHTML = `
    <button data-acm="star">${starred ? '☆ 取消置顶' : '⭐ 置顶'}</button>
    <button data-acm="rename">✏️ 重命名</button>
    ${ps.length ? `<button data-acm="move">${AI_FOLDER} 移动到项目 ›</button>` : ''}
    ${aiMenuCtx.projId ? '<button data-acm="unproj">📤 移出项目</button>' : ''}
    <button data-acm="del" class="acm-danger">🗑 删除对话</button>`;
  $('#ai-chatmenu').classList.remove('hidden');
}
$('#ai-chatmenu').addEventListener('click', async e => {
  if (e.target.closest('[data-sheet-close]') || e.target.id === 'ai-chatmenu') {
    $('#ai-chatmenu').classList.add('hidden'); return;
  }
  const mv = e.target.closest('[data-acmproj]');
  if (mv && aiMenuCtx) {
    $('#ai-chatmenu').classList.add('hidden');
    try {
      await api('/api/aichat/chats/' + aiMenuCtx.id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: +mv.dataset.acmproj }) });
      toast('已移动'); await loadAiHome();
      if (!$('#aiv-project').classList.contains('hidden') && aiCurProject) openAiProject(aiCurProject.id);
    } catch (err) { toast(err.message, true); }
    return;
  }
  const b = e.target.closest('[data-acm]');
  if (!b || !aiMenuCtx) return;
  const act = b.dataset.acm;
  if (act === 'move') {
    const ps = $('#ai-panel')._projects || [];
    $('#acm-list').innerHTML = '<div class="acm-tip">移动到哪个项目：</div>'
      + ps.map(p => `<button data-acmproj="${p.id}">${AI_FOLDER} ${esc(p.name)}</button>`).join('');
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
    if (!$('#aiv-project').classList.contains('hidden') && aiCurProject) openAiProject(aiCurProject.id);
  } catch (err) { toast(err.message, true); }
});

/* 悬浮工具球：点一下在四周扇出「AI / 草稿纸」；按住可拖到任意位置（位置记忆） */
(function () {
  const fab = $('#fab'), main = $('#fab-btn');
  if (!fab || !main) return;
  try {
    const p = JSON.parse(lsGet('aifab') || 'null');
    if (p) { fab.style.left = p.x + 'px'; fab.style.top = p.y + 'px'; fab.style.right = 'auto'; fab.style.bottom = 'auto'; }
  } catch (_) {}
  requestAnimationFrame(fabClamp);          // 上次记的位置可能落在这个窗口外面，先夹回来

  function dirs() {                       // 扇出方向：别扇到屏幕外
    const r = fab.getBoundingClientRect();
    fab.classList.toggle('dir-l', r.left > innerWidth / 2);
    fab.classList.toggle('dir-r', r.left <= innerWidth / 2);
    fab.classList.toggle('dir-up', r.top > innerHeight * .22);
    fab.classList.toggle('dir-dn', r.top <= innerHeight * .22);
  }
  window.fabClose = () => fab.classList.remove('open');
  // 按「实际可见的按钮数」把它们均匀铺在四分之一圆弧上（截图在手机端隐藏，个数会变；
  // 固定 CSS 弧位就会留空/重叠）。半径随个数增大，保证不叠。
  function layoutFab() {
    const acts = [...fab.querySelectorAll('.fab-act')].filter(b => !b.hidden);
    const n = acts.length;
    const R = 70 + Math.max(0, n - 3) * 16;       // 3个→70，每多一个半径+16，避免挤在一起
    acts.forEach((b, i) => {
      const a = n === 1 ? Math.PI / 4 : (Math.PI / 2) * (i / (n - 1));   // 0..90° 均分
      b.style.setProperty('--fx', Math.round(Math.cos(a) * R) + 'px');
      b.style.setProperty('--fy', Math.round(Math.sin(a) * R) + 'px');
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
      try { lsSet('aifab', JSON.stringify({ x: r.left, y: r.top })); } catch (_) {}
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
let matMenuCtx = null;
function openMatMenu(id, name, ext) {
  matMenuCtx = { id, name, ext };
  $('#mm-title').textContent = name;
  $('#ai-chatmenu').classList.add('hidden');
  $('#mat-menu').classList.remove('hidden');
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
    } catch (err) { toast(err.message, true); }
    return;
  }
  if (e.target.closest('[data-sheet-close]') || e.target.id === 'mat-menu') {
    $('#mat-menu').classList.add('hidden'); return;
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
        toast('正在准备分享…');
        GongkaoNative.shareFile(location.origin + url, name);
        return;
      }
    } catch (_) {}
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
    // 电脑桌面版（WebKitGTK 没有系统分享面板）：把文件下下来 —— 到「下载」文件夹后就能手动发给别人，
    // 比原来复制个文件名文本有用。（要在应用内分享给同学，用菜单里的「👥 共享给队友」。）
    const a = document.createElement('a'); a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    toast('已下载「' + name + '」，可从「下载」文件夹发给他人（应用内分享用「👥 共享给队友」）');
  } else if (act === 'rename') {
    const v = await appPrompt('重命名文档', '', name);
    if (v && v.trim() && v !== name) {
      try { await api('/api/materials/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: v.trim() }) }); toast('已重命名'); loadMaterials(); }
      catch (err) { toast(err.message, true); }
    }
  } else if (act === 'dup') {
    try { await api('/api/materials/' + id + '/duplicate', { method: 'POST' }); toast('已复制一份'); loadMaterials(); }
    catch (err) { toast(err.message, true); }
  } else if (act === 'dl') {
    const a = document.createElement('a'); a.href = '/api/materials/' + id + '/download'; a.download = '';
    document.body.appendChild(a); a.click(); a.remove();
  } else if (act === 'del') {
    if (!(await appConfirm('删除「' + name + '」？'))) return;
    try { await api('/api/materials/' + id, { method: 'DELETE' }); toast('已删除'); loadMaterials(); }
    catch (err) { toast(err.message, true); }
  }
});

/* ================= 主题：日间 / 夜间 / 跟随系统 ================= */
const _themeMedia = window.matchMedia ? matchMedia('(prefers-color-scheme: dark)') : null;
/* Android WebView 里 prefers-color-scheme 恒为 light（除非 app 显式开启），
   所以「跟随系统」在 APK 中失灵。原生壳会把系统夜间状态写进 window.__sysDark，优先采信它。 */
function sysIsDark() {
  if (typeof window.__sysDark === 'boolean') return window.__sysDark;
  try {
    if (window.GongkaoNative && typeof GongkaoNative.sysDark === 'function') return !!GongkaoNative.sysDark();
  } catch (_) {}
  return !!(_themeMedia && _themeMedia.matches);
}
function applyTheme() {
  const mode = lsGet('theme') || 'auto';
  const dark = mode === 'dark' || (mode === 'auto' && sysIsDark());
  document.body.classList.toggle('dark', dark);
  document.querySelectorAll('.theme-opt').forEach(b => b.classList.toggle('on', b.dataset.theme === mode));
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = dark ? '#0f141e' : '#1a6fb5';
  if (window.__padTheme) window.__padTheme();      // 草稿纸墨色跟着日/夜间翻转（钩子在脚本末尾才挂，早期调用自动跳过）
}
// 原生壳在系统深色模式切换时调用
window.__onSysTheme = function (dark) { window.__sysDark = !!dark; applyTheme(); };
document.addEventListener('click', e => {
  const b = e.target.closest('.theme-opt'); if (!b || !b.dataset.theme) return;
  lsSet('theme', b.dataset.theme);
  applyTheme();
  toast(b.textContent.trim() + ' 已应用');
});
if (_themeMedia) {
  try { _themeMedia.addEventListener('change', applyTheme); }
  catch (_) { _themeMedia.addListener(applyTheme); }  // 旧 WebView
}
// 回到前台时系统可能已切到夜间（跟随系统模式下重新判定一次）
document.addEventListener('visibilitychange', () => { if (!document.hidden) applyTheme(); });
applyTheme();

/* ================= AI 面板分层返回（返回上一级而非直接关闭） ================= */
function aiBack() {
  if ($('#ai-panel').classList.contains('hidden')) return false;
  if (!$('#aiv-chat').classList.contains('hidden')) {
    // 会话 → 所属项目详情（若有）或首页
    if (aiProjectId && ($('#ai-panel')._projects || []).some(p => p.id === aiProjectId)) {
      loadAiHome().then(() => openAiProject(aiProjectId));
    } else { aiShow('home'); loadAiHome(); }
    return true;
  }
  if (!$('#aiv-project').classList.contains('hidden')) { renderAiProjects(); aiShow('projects'); return true; }
  if (!$('#aiv-projects').classList.contains('hidden')) { aiShow('home'); loadAiHome(); return true; }
  $('#ai-panel').classList.add('hidden');
  return true;
}

/* ================= 应用内更新 =================
   手机(APK)：下载新 APK 并唤起安装。
   电脑(桌面壳)：分两种——
     · 只改了网页 → 不用重下，提示「刷新更新」，点一下就是新版；
     · 改了桌面壳本身 → 必须重下，提示「下载更新」，下好双击装。 */
const pkgSize = (n) => n ? '安装包 ' + fmtSize(n) : '';

function updModal({ title, ver, notes, size, btn, key, onGo }) {
  $('#upd-title').textContent = title;
  $('#upd-ver').textContent = ver || '';
  $('#upd-notes').textContent = notes;
  $('#upd-size').textContent = size || '';
  $('#upd-go').textContent = btn;
  $('#upd-modal').classList.remove('hidden');
  $('#upd-later').onclick = () => {
    if (key) lsSet('skipUpdate', key);   // 这一版说过「以后再说」就别再弹
    $('#upd-modal').classList.add('hidden');
  };
  $('#upd-go').onclick = () => { $('#upd-modal').classList.add('hidden'); onGo(); };
}

let SW_AT_START = '';          // 本次启动时服务器的网页版本；之后变了 = 有前端更新（刷新即可）
let _lastUpdChk = 0;

async function checkApkUpdate(manual) {
  let cur = 0;
  try { cur = GongkaoNative.appVersion(); } catch (_) { return; }
  let d;
  try { d = await api('/api/app/version'); } catch (_) { if (manual) toast('检查更新失败', true); return; }
  if (!d.available || !d.version_code || d.version_code <= cur) {
    if (manual) toast('已是最新版本 (v' + (d.version_name || cur) + ')');
    return;
  }
  const key = 'apk' + d.version_code;
  if (!manual && lsGet('skipUpdate') === key) return;
  updModal({
    title: '发现新版本', ver: 'v' + (d.version_name || d.version_code),
    notes: d.notes || '修复问题、优化体验。', size: pkgSize(d.size),
    btn: '立即更新', key,
    onGo: () => {
      try { GongkaoNative.updateApp(location.origin + d.url); }
      catch (_) { toast('更新失败，请到浏览器下载', true); }
    },
  });
}

async function checkDesktopUpdate(manual) {
  let d;
  try { d = await api('/api/desktop/version'); } catch (_) { if (manual) toast('检查更新失败', true); return; }
  const cur = parseInt(DESKTOP_VER.replace(/\./g, ''), 10) || 0;    // "3.2" → 32

  // ① 桌面壳本身有新版 → 必须重新下载安装包
  if (d.deb_available && d.deb_code > cur) {
    const key = 'deb' + d.deb_code;
    if (!manual && lsGet('skipUpdate') === key) return;
    updModal({
      title: '发现桌面版新版本', ver: 'v' + (d.deb_name || d.deb_code),
      notes: (d.deb_notes || '优化体验。') + '\n这次改动涉及桌面客户端本身，需要重新下载安装包更新。',
      size: pkgSize(d.deb_size), btn: '下载更新', key,
      onGo: () => {
        toast('开始下载…完成后按提示安装');
        const a = document.createElement('a');
        a.href = d.deb_url; a.download = 'gongkao.deb';
        document.body.appendChild(a); a.click(); a.remove();
      },
    });
    return;
  }

  // ② 只有网页内容更新 → 不用重下，刷新就是新版
  if (SW_AT_START && d.sw && d.sw !== SW_AT_START) {
    const key = 'sw' + d.sw;
    if (!manual && lsGet('skipUpdate') === key) return;
    updModal({
      title: '有新内容更新', ver: '',
      notes: '界面/功能已更新，不需要重新下载客户端。点「刷新更新」立即用上新版。',
      size: '', btn: '刷新更新', key,
      onGo: () => location.reload(),
    });
    return;
  }
  if (d.sw && !SW_AT_START) SW_AT_START = d.sw;      // 启动时记下基准
  if (manual) toast('已是最新版本（桌面版 v' + (DESKTOP_VER || '?') + '）');
}

async function checkUpdate(manual) {
  _lastUpdChk = Date.now();
  if (IS_DESKTOP) return checkDesktopUpdate(manual);
  if (window.GongkaoNative && typeof GongkaoNative.appVersion === 'function') return checkApkUpdate(manual);
  if (manual) toast('网页版会自动更新，无需手动升级');
}
$('#acct-update').onclick = () => checkUpdate(true);
window.checkUpdate = checkUpdate;

if (IS_DESKTOP || IN_APP) {
  setTimeout(() => checkUpdate(false), 3500);                   // 启动后静默查一次
  setInterval(() => checkUpdate(false), 30 * 60 * 1000);        // 长期开着也能收到更新提示
  document.addEventListener('visibilitychange', () => {         // 切回窗口时再看一眼（限流）
    if (!document.hidden && Date.now() - _lastUpdChk > 10 * 60 * 1000) checkUpdate(false);
  });
}
/* 桌面壳下载完成后回调（更新包下好了 → 告诉用户怎么装） */
window.__onDownloaded = (path) => {
  if (!/\.deb$/i.test(path || '')) return;
  appConfirm(
    '已保存到：' + path + '\n\n双击它用「软件安装器」打开即可完成更新，'
    + '或在终端执行：sudo dpkg -i "' + path + '"\n装好后重新打开公考助手就是新版。',
    { title: '更新包已下载完成', okText: '知道了' });
};

/* ================= 消息中心：有新内容就提醒，点开直达对应位置 ================= */
const NTF_ICON = {
  changshi: '💡', newlaw: '⚖️', news: '📰', xiyu: '✒️', sucai: '📎',
  gaikuo: '📝', review: '⏰', tasks: '📋', quiz: '🧩', plan: '📅', essay: '📄',
};
/* link 形如 "changshi" 或 "changshi:法律常识" */
let _ntfTries = 0;
function ntfGo(link) {
  // 原生通知点进来时 SPA 可能还没启动完，等它把 ME 拉到再跳
  if (!ME && _ntfTries < 20) { _ntfTries++; setTimeout(() => ntfGo(link), 400); return; }
  _ntfTries = 0;
  const [k, arg] = (link || '').split(':');
  const go = {
    changshi: () => { openChangshi(); if (arg) setTimeout(() => openCsBoard(arg), 260); },
    news: () => openNews(),
    xiyu: () => { openNews(); setTimeout(() => { const b = document.querySelector('#news-boards [data-nb="习语"]'); if (b) b.click(); }, 260); },
    sucai: () => openSucai('全部'),
    gaikuo: () => openGaikuo(),
    review: () => openReview(),
    tasks: () => openTasks(),
    quiz: () => openQuiz(),
    essays: () => openEssays(),
    essay: () => openEssays(),
    gongwen: () => openGongwen(),
    // 备考规划/路线图里的 link 也走这里（以前这些点了没反应）
    wrongq: () => openWrongq(),
    drafts: () => openDrafts(),
    idiom: () => openIdiom(),
    changkao: () => { openChangkao(); if (arg) setTimeout(() => openCkBoard(arg), 260); },
    shenlun: () => openShenlun(),
    classics: () => openClassics(),
    theory: () => { openTheory(); if (arg) setTimeout(() => openThBoard(arg), 260); },
    works: () => openWorks(),
    partydict: () => openPartyDict(),
    policydoc: () => openPolicyDocs(),
    dtest: () => { openTasks(); setTimeout(() => tkSwitch('daily'), 60); },   // 巩固测试在「每日任务」里
    plan: () => { openTasks(); setTimeout(() => tkSwitch('plan'), 60); },
    chatroom: () => { if (arg) openChatroom(+arg, ''); else openChat(); },     // 聊天通知点进来直达会话
  }[k];
  if (go) go(); else toast('这条消息没有可跳转的位置');
}
function openNotify() { push({ view: 'notify', title: '消息' }); loadNotify(); }
$('#notify-btn').onclick = openNotify;

async function loadNotify() {
  $('#ntf-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/notifications');
    setNtfDot(d.unread);
    $('#ntf-list').innerHTML = d.items.length ? d.items.map(it => `
      <div class="ntf ${it.read ? '' : 'unread'}" data-ntf="${it.id}" data-link="${esc(it.link || '')}">
        <span class="ntf-ico">${NTF_ICON[it.kind] || '🔔'}</span>
        <div class="ntf-main">
          <div class="ntf-t">${esc(it.title)}</div>
          ${it.body ? `<div class="ntf-b">${esc(it.body)}</div>` : ''}
          <div class="ntf-m">${esc(it.created_at.slice(5, 16))}</div>
        </div>
        ${it.read ? '' : '<span class="ntf-new"></span>'}
      </div>`).join('') : '<p class="empty">暂时没有新消息。内容库每天早上更新后会出现在这里。</p>';
  } catch (e) { $('#ntf-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#ntf-list').addEventListener('click', async e => {
  const n = e.target.closest('[data-ntf]'); if (!n) return;
  if (n.classList.contains('unread')) {
    n.classList.remove('unread');
    const nb = n.querySelector('.ntf-new'); if (nb) nb.remove();   // 老 WebView 不支持 ?.
    api('/api/notifications/' + n.dataset.ntf + '/read', { method: 'POST' })
      .then(refreshNtfDot).catch(() => {});
  }
  ntfGo(n.dataset.link);
});
$('#ntf-readall').onclick = async () => {
  try { await api('/api/notifications/read_all', { method: 'POST' }); loadNotify(); }
  catch (e) { toast(e.message, true); }
};
$('#ntf-clear').onclick = async () => {
  if (!(await appConfirm('清理所有已读消息？'))) return;
  try { await api('/api/notifications', { method: 'DELETE' }); loadNotify(); }
  catch (e) { toast(e.message, true); }
};

function setNtfDot(n) {
  const dot = $('#notify-dot');
  dot.textContent = n > 99 ? '99+' : (n || '');
  dot.classList.toggle('hidden', !n);
}
async function refreshNtfDot() {
  try { setNtfDot((await api('/api/notifications/unread')).unread); }
  catch (e) { console.debug('[消息] 红点刷新失败：%s', (e && e.message) || e); }        // 下次轮询会补
}
/* 启动时生成一次当天的消息并点亮角标；之后每次回首页只数未读 */
setTimeout(() => { api('/api/notifications').then(d => setNtfDot(d.unread)).catch(() => {}); }, 1200);

/* ================= 范文推荐（仿真卷 + 全套参考答案） ================= */
let esKind = 'zuowen', esTopic = '', esPapers = [], esCur = null;

async function openEssays() {
  push({ view: 'essays', title: '范文推荐' });
  try {
    const d = await api('/api/essays/topics');
    esPapers = d.papers;
    renderEsTopics();
    loadEssays();
  } catch (e) { $('#es-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderEsTopics() {
  $('#es-topics').innerHTML = `<button class="chip ${esTopic ? '' : 'active'}" data-est="">全部</button>`
    + esPapers.map(p => `<button class="chip ${esTopic === p.topic ? 'active' : ''}" data-est="${esc(p.topic)}">${esc(p.topic)}</button>`).join('');
}
$('#es-topics').addEventListener('click', e => {
  const b = e.target.closest('[data-est]'); if (!b) return;
  esTopic = b.dataset.est; renderEsTopics(); loadEssays();
});
$('#es-tabs').addEventListener('click', e => {
  const b = e.target.closest('[data-esk]'); if (!b) return;
  esKind = b.dataset.esk;
  document.querySelectorAll('#es-tabs .tk-tab').forEach(x => x.classList.toggle('active', x.dataset.esk === esKind));
  loadEssays();
});
async function loadEssays() {
  $('#es-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/essays?kind=' + esKind + (esTopic ? '&topic=' + encodeURIComponent(esTopic) : ''));
    if (!d.items.length) {
      $('#es-list').innerHTML = '<p class="empty">这个分类下还没有范文。服务器上跑 <code>gen_essays.py</code> 可以按话题继续生成。</p>';
      return;
    }
    $('#es-list').innerHTML = d.items.map(it => `
      <div class="sl-hi" data-esid="${it.id}">
        <div class="sl-hi-main">
          <div class="sl-hi-t">${esc(it.topic)} · ${esc(it.type_name)}</div>
          <div class="sl-hi-m">${esc(it.stem.slice(0, 42))}…</div>
          <div class="sl-hi-m">${it.full} 分 · 要求 ${it.word_min}-${it.word_max} 字 · 范文 ${it.answer_words} 字</div>
        </div>
        <span class="bc-arrow">›</span>
      </div>`).join('');
  } catch (e) { $('#es-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#es-list').addEventListener('click', e => {
  const c = e.target.closest('[data-esid]'); if (c) openEssay(+c.dataset.esid);
});

async function openEssay(eid) {
  try {
    const d = await api('/api/essays/' + eid);
    esCur = d;
    push({ view: 'essayd', title: d.topic + ' · ' + d.type_name });
    $('#esd-head').innerHTML = `<div class="slt-title">${esc(d.topic)} · ${esc(d.type_name)}</div>
      <div class="slt-desc">${esc(d.spec_name)} · 本题 ${d.full} 分 · 要求 ${d.word_min}-${d.word_max} 字
      · 给定资料 ${d.material_words} 字</div>`;
    $('#esd-q').innerHTML = `<div class="slt-sec">题目</div>
      <div class="slr-reftext">${esc(d.stem).replace(/\n/g, '<br>')}</div>`
      + (d.outline ? `<div class="slt-sec">写作思路</div><div class="slr-reftext">${esc(d.outline).replace(/\n/g, '<br>')}</div>` : '');
    $('#esd-m').innerHTML = `<div class="slt-sec">给定资料（${d.material_words} 字）</div>
      <div class="slr-reftext slr-mat">${esc(d.material).replace(/\n/g, '<br>')}</div>`;
    $('#esd-a').innerHTML = `<div class="slt-sec">${d.qtype === 'zuowen' ? '参考范文' : '参考答案'}</div>
      <div class="slr-wtag">${d.answer_words} 字 · 题目要求 ${d.word_min}-${d.word_max} 字</div>
      <div class="slr-reftext">${esc(d.answer).replace(/\n/g, '<br>')}</div>`;
    esdTab('q');
  } catch (e) { toast(e.message, true); }
}
function esdTab(t) {
  document.querySelectorAll('#esd-tabs .tk-tab').forEach(x => x.classList.toggle('active', x.dataset.esd === t));
  ['q', 'm', 'a'].forEach(k => $('#esd-' + k).classList.toggle('hidden', k !== t));
}
$('#esd-tabs').addEventListener('click', e => {
  const b = e.target.closest('[data-esd]'); if (b) esdTab(b.dataset.esd);
});
$('#esd-practice').onclick = async () => {
  if (!esCur) return;
  try {
    const d = await api('/api/essays/paper/' + esCur.paper_id + '/practice', { method: 'POST' });
    toast(d.existed ? '这套卷已经在你的真题卷里' : '已加入我的真题卷');
    openSlPaper(d.id);
  } catch (e) { toast(e.message, true); }
};

/* ================= 题库：模拟卷 / 题目解析 ================= */
function openQuiz() {
  push({ view: 'quiz', title: '题库' });
  $('#qz-entries').innerHTML = `
    <div class="home-card" data-qzgo="sets">
      <div class="hc-logo" style="background:linear-gradient(135deg,#2b6fd6,#4bb0f0)">${IC.edit}</div>
      <div class="hc-name">模拟卷</div><div class="hc-desc">四川省考卷面 · 每周自动更新</div></div>
    <div class="home-card" data-qzgo="docqa">
      <div class="hc-logo" style="background:linear-gradient(135deg,#0b7285,#1098ad)">${IC.bulb}</div>
      <div class="hc-name">题目解析</div><div class="hc-desc">上传讲义 · AI 解出没答案的例题</div></div>`;
}
$('#qz-entries').addEventListener('click', e => {
  const c = e.target.closest('[data-qzgo]'); if (!c) return;
  if (c.dataset.qzgo === 'sets') openQuizSets(); else openDocqa();
});

async function openQuizSets() {
  push({ view: 'quizsets', title: '模拟卷' });
  $('#qz-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/quiz/sets');
    if (!d.items.length) { $('#qz-list').innerHTML = '<p class="empty">还没有套卷，每周二/五清晨自动生成～</p>'; return; }
    $('#qz-list').innerHTML = d.items.map(it => {
      const pct = it.done ? Math.round(it.right_n / it.done * 100) : 0;
      return `<div class="poly-card" data-qset="${it.id}">
        <span class="poly-badge" style="background:${it.kind === '申论' ? '#7a5cc0' : '#2b6fd6'}">${esc(it.kind)}</span>
        <div class="poly-t" style="font-size:16px">${esc(it.name)}</div>
        <div class="poly-meta">${it.total} 题 · 已做 ${it.done}${it.done ? ` · 正确率 ${pct}%` : ''}</div>
      </div>`;
    }).join('');
  } catch (e) { $('#qz-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}

/* ---- 题目解析：上传讲义 → 后台识题 → 生成含答案解析副本 ---- */
var dqPoll = null;   // var：render() 在它上面，用 let 会踩暂时性死区
function openDocqa() { push({ view: 'docqa', title: '题目解析' }); loadDocqa(); }
$('#dq-upload').onclick = () => $('#dq-file').click();
$('#dq-file').addEventListener('change', async e => {
  const files = [...e.target.files]; e.target.value = '';
  if (!files.length) return;
  toast(files.length > 1 ? `已上传 ${files.length} 份，正在后台排队识题…` : '已上传，正在后台识题…');
  let ok = 0, fail = 0;
  for (const file of files) {           // 逐个上传；后端会排队，一次只解一份，不挤爆接口
    const fd = new FormData();
    fd.append('file', file);
    fd.append('board', matBoard || '');
    try { await api('/api/docqa/upload', { method: 'POST', body: fd }); ok++; }
    catch (err) { fail++; }
  }
  if (fail) toast(`${ok} 份已排队，${fail} 份上传失败`, true);
  loadDocqa();
});

async function loadDocqa() {
  try {
    const d = await api('/api/docqa/tasks');
    const running = d.items.some(t => t.status === 'running');
    $('#dq-list').innerHTML = d.items.length ? d.items.map(t => {
      const pct = t.total ? Math.round(t.progress / t.total * 100) : 0;
      const cls = t.status === 'done' ? 'good' : t.status === 'error' ? 'bad' : 'ok';
      return `<div class="sl-hi" data-dqt="${t.id}">
        <div class="sl-hi-main">
          <div class="sl-hi-t">${esc(t.title)}</div>
          <div class="sl-hi-m">${esc(t.created_at.slice(5, 16))} · ${esc(t.message || '')}</div>
          ${t.status === 'running' ? `<div class="dq-bar"><i style="width:${pct}%"></i></div>` : ''}
        </div>
        <div class="sl-hi-s ${cls}" style="font-size:13px">${t.status === 'done' ? '完成' : t.status === 'error' ? '失败' : pct + '%'}</div>
        <button class="sl-hi-del" data-dqdel="${t.id}">🗑</button>
      </div>`;
    }).join('') : '<p class="empty">还没有解析任务。上传一份讲义，AI 会把里面没答案的例题解出来。</p>';
    clearInterval(dqPoll);
    if (running) dqPoll = setInterval(loadDocqa, 4000);     // 有任务在跑就轮询进度
  } catch (e) { $('#dq-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#dq-list').addEventListener('click', async e => {
  const del = e.target.closest('[data-dqdel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('删除这条解析记录？（资料库里的文件不会删）'))) return;
    try { await api('/api/docqa/task/' + del.dataset.dqdel, { method: 'DELETE' }); loadDocqa(); }
    catch (er) { toast(er.message, true); }
    return;
  }
  const t = e.target.closest('[data-dqt]');
  if (t) openDocqaTask(+t.dataset.dqt);
});

async function openDocqaTask(tid) {
  try {
    const t = await api('/api/docqa/task/' + tid);
    if (t.status === 'running') return toast('还在解析中，' + (t.message || ''));
    if (t.status === 'error') return toast('解析失败：' + t.message, true);
    push({ view: 'docqad', title: t.title });
    $('#dqd-head').innerHTML = `<div class="slt-title">${esc(t.title)}</div>
      <div class="slt-desc">识别 ${t.questions.length} 道题 · ${esc(t.created_at.slice(0, 16))}</div>`;
    const src = t.extra.src_mid, out = t.extra.out_mid;
    $('#dqd-files').innerHTML = `
      <button class="dqd-f" data-dqopen="${src}|原件">📄 打开原件</button>
      <button class="dqd-f primary" data-dqopen="${out}|含答案解析">✅ 打开含答案解析副本</button>`;
    $('#dqd-qs').innerHTML = t.questions.map((q, i) => `
      <div class="slp good">
        <div class="slp-head"><span class="slp-no">${i + 1}</span>
          <span class="slp-name">${esc(q.qtype || '题目')}</span>
          <span class="slp-score" style="font-size:12px">第 ${q.page} 页</span></div>
        <div class="slp-yours">${esc(q.stem)}</div>
        ${q.options.map(o => `<div class="dq-opt">${esc(o)}</div>`).join('')}
        <div class="slp-li hit">【答案】${esc(q.answer)}</div>
        <div class="slp-mat"><b>解析：</b>${esc(q.explain)}</div>
      </div>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#dqd-files').addEventListener('click', e => {
  const b = e.target.closest('[data-dqopen]'); if (!b) return;
  const [mid, name] = b.dataset.dqopen.split('|');
  openViewerUrl('/api/materials/' + mid + '/view', name, '.pdf', '/api/materials/' + mid + '/download');
});

/* ================= 手机通知栏推送（APK 内由原生定时拉取并弹通知） ================= */
function nativeNotify() {
  return window.GongkaoNative && typeof GongkaoNative.notifyEnabled === 'function' ? GongkaoNative : null;
}
function refreshNotifyBtn() {
  const n = nativeNotify();
  const b = $('#acct-notify');
  if (!b) return;
  if (!n) { b.textContent = '手机通知（需安装 App）'; return; }
  try { b.textContent = '手机通知：' + (n.notifyEnabled() ? '已开启 ✓' : '已关闭'); } catch (_) {}
}
$('#acct-notify').onclick = () => {
  const n = nativeNotify();
  if (!n) return toast('网页版看不到系统通知，请安装安卓 App', true);
  try {
    const on = !n.notifyEnabled();
    n.setNotify(on);
    refreshNotifyBtn();
    toast(on ? '已开启：新消息会推到手机通知栏' : '已关闭手机通知');
  } catch (e) { toast('设置失败', true); }
};
$('#acct-notifytest').onclick = () => {
  const n = nativeNotify();
  if (!n) return toast('网页版看不到系统通知，请安装安卓 App', true);
  try { n.notifyTest(); toast('已发送，下拉通知栏看看'); }
  catch (e) { toast('发送失败', true); }
};
