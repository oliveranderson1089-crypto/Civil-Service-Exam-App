/* 外壳：导航栈 / 初始化 / 首页 / 应用内弹窗 / 卡片拖拽排序
 *
 * 由 app.js 按它自己的区段边界切出（原 L157-538）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, ALL_BOARDS, BOARD_FEATURES, IC, IDIOM_BOARD, IS_MOBILE,
   Ink, KB, ME, SECTIONS, SECTION_EXTRA, SECTION_FEATURES,
   aiBack, api, c, chatConnect, closeSlideshow, dqPoll,
   esc, loadNotebook, loadSkin, matClose, matInited, mkInject,
   newDraft, openBoardKb, openChangkao, openChangshi, openChat, openCkBoard,
   openClassics, openDrill, openDrive, openFanwen, openFind, openGaikuo,
   openGongwen, openIdiom, openKb, openMaterials, openNews, openNotes,
   openPartyDict, openPolicyDocs, openQuiz, openReview, openShenlun, openSucai,
   openTasks, openTheory, openVideos, openWorks, openWrite, openWrongq,
   padClose, qz, refreshChatBadge, refreshNtfDot, saveDoc, setViewerFull,
   stack, state, toast, toggleNoteSearch, openRealq, refreshRealqBadge */

/* ---------------- 导航 ---------------- */
const VIEWS = ['home', 'section', 'board', 'notes', 'kb', 'notebook', 'doc', 'materials', 'idiom', 'viewer', 'search', 'classics', 'cdetail', 'wrongq', 'wqadd', 'wqdetail', 'boardkb', 'account', 'partydict', 'policydoc', 'policydocd', 'news', 'newsd', 'gaikuo', 'gongwen', 'sucai', 'review', 'changshi', 'csboard', 'works', 'workd', 'quiz', 'quizrun', 'tasks', 'changkao', 'ckboard', 'theory', 'thboard', 'shenlun', 'slpaper', 'sltype', 'slgrade', 'slresult', 'notify', 'essays', 'essayd', 'quizsets', 'docqa', 'docqad', 'planlog', 'dtest', 'drafts', 'write', 'writed', 'realq', 'realrun', 'drill', 'drillrun', 'drillrec', 'drillrecd', 'find', 'findrun', 'findrec', 'findrecd', 'findwrong', 'videos', 'fanwen', 'fanwend', 'drive', 'chat'];
const TITLES = { home: '公考助手', section: '', board: '', notes: '小记', kb: '知识库', notebook: '', doc: '', materials: '资料库', idiom: '成语词语', viewer: '查看', search: '搜索', classics: '古诗文速查', cdetail: '', wrongq: '错题本', wqadd: '记录错题', wqdetail: '错题详情', boardkb: '基础知识点', account: '账户', partydict: '创新理论词典', policydoc: '时政要文库', policydocd: '', news: '每日时政', newsd: '', gaikuo: '概括句积累', gongwen: '应用文上位词', sucai: '素材积累', review: '今日复习', changshi: '常识积累', csboard: '', works: '经典著作', workd: '', quiz: '题库', quizsets: '模拟卷', docqa: '题目解析', docqad: '', essays: '范文推荐', essayd: '', quizrun: '做题', tasks: '任务清单', changkao: '常考', ckboard: '', theory: '理论基础', thboard: '', shenlun: '真题批改', slpaper: '', sltype: '', slgrade: '', slresult: '批改结果', notify: '消息', planlog: '计划记录', dtest: '巩固测试', drafts: '草稿本', write: '成文', writed: '', realq: '历年真题', realrun: '', drill: '专项练', drillrun: '', drillrec: '做题记录', drillrecd: '', find: '小题训练', findrun: '', findrec: '做题记录', findrecd: '这次的批改', findwrong: '错题记录', videos: '每日新闻视频' };
function render() {
  const st = stack[stack.length - 1];
  VIEWS.forEach(v => $('#view-' + v).classList.toggle('hidden', v !== st.view));
  // 聊天双栏：移动端按栈顶 state.room 决定显示会话列表还是聊天窗（back 出栈即回列表）
  // 云盘：栈顶记着当前在哪个目录，back() 弹回来时按它重列（逐级退，不是一步回首页）
  if (st.view === 'drive' && window.__dvShow) window.__dvShow(st);
  if (st.view === 'chat') {
    const p2 = $('#chat-2pane');
    if (p2 && IS_MOBILE) p2.classList.toggle('show-room', !!st.room);
  }
  $('#top-title').textContent = st.title || TITLES[st.view] || '公考助手';
  $('#nav-back').classList.toggle('hidden', stack.length <= 1);
  // 文档编辑器自带顶栏，隐藏全局顶栏
  document.querySelector('.topbar').classList.toggle('hidden', st.view === 'doc');
  // 切换视图时停止朗读
  if (window.Reader && Reader.playing) Reader.stop();
  if (window.Ink && Ink.on) Ink.close();                  // 切视图退出批注模式（笔迹已按页面存好）
  // 离开阅读页必须退出全屏，否则状态栏一直藏着
  if (st.view !== 'viewer' && document.body.classList.contains('viewer-full')) setViewerFull(false);
  // 离开「题目解析」就别再轮询进度了（dqPoll 是顶层 let，不挂在 window 上）
  if (st.view !== 'docqa' && dqPoll) { clearInterval(dqPoll); dqPoll = null; }
  if (window.__padView) window.__padView(st.view);        // 做题页才出现草稿纸按钮
  if (window.__bmView) window.__bmView();                 // 阅读页：上次看到哪了
  // 有划重点的模块，在正文顶部长出那张卡（内容是异步渲染的，等一拍再注入）
  if (window.mkInject) setTimeout(() => mkInject(), 260);
  if (st.view !== 'slgrade' && matInited && !$('#matpad').classList.contains('hidden')) matClose();
}
function push(state) { stack.push(state); render(); }
function back() { if (stack.length > 1) { stack.pop(); render(); } }
function goHome() { stack = [{ view: 'home' }]; render(); if (window.refreshNtfDot) refreshNtfDot(); }
// 供安卓原生「返回/侧滑」调用：能退则退并返回 true，已在首页返回 false
window.appBack = function () {
  // 草稿纸开着就先收起（内容已自动保存）
  const padEl = $('#pad');
  if (padEl && !padEl.classList.contains('hidden')) { padClose(); return true; }
  // 幻灯片播放优先退出
  if (!$('#slideshow').classList.contains('hidden')) { closeSlideshow(); return true; }
  // AI 面板
  const aip = $('#ai-panel');
  if (aip && !aip.classList.contains('hidden')) { return aiBack(); }
  // 0) 任意底部弹层（小记新建 / 知识库 + / 块菜单 / 插入面板）
  const sheets = [...document.querySelectorAll('.note-sheet:not(.hidden)')];
  if (sheets.length) { sheets[sheets.length - 1].classList.add('hidden'); return true; }
  // 2) 全屏小记编辑器
  const cp = document.querySelector('.composer.cp-open');
  if (cp) { newDraft(); return true; }
  // 3) 普通弹窗
  const m = document.querySelector('.modal:not(.hidden)');
  if (m) { m.classList.add('hidden'); return true; }
  // 4) 手机端搜索框展开时先收起
  const ms = $('#notes-msearch');
  if (IS_MOBILE && ms && !ms.classList.contains('hidden')) { toggleNoteSearch(); return true; }
  // 5) 文档编辑器：保存后退出
  const top = stack[stack.length - 1];
  if (top && top.view === 'doc') { saveDoc(); back(); if (KB.nb) loadNotebook(KB.nb.id); return true; }
  if (stack.length > 1) { back(); return true; }
  return false;
};

/* ---------------- 初始化 / 首页 ---------------- */
async function init() {
  try {
    ME = await api('/api/me');
    const d = await api('/api/sections');
    SECTIONS = d.sections; IDIOM_BOARD = d.idiom_board;
    ALL_BOARDS = SECTIONS.flatMap(s => s.boards);
  } catch (e) {
    // 拉不到基础数据（掉线 / 后端异常）：别把用户丢在空白首页，给个能重试的提示。
    // 未登录时 api() 已跳去 /login，不会走到这里。
    // 直接撤掉启动页（不排动画计时器）、重试用一个跳回 / 的链接（不加事件绑定），保持零副作用。
    try {
      const sp = document.getElementById('splash'); if (sp) sp.remove();
      const hc = $('#home-cards');
      if (hc) {
        hc.innerHTML = '<div style="text-align:center;padding:44px 20px;color:#8a94a6">'
          + '<p style="margin-bottom:14px;font-size:15px">😥 加载失败，请检查网络后重试</p>'
          + '<a href="/" class="btn primary" style="display:inline-block">重新加载</a></div>';
      }
    } catch (_) { /* init 是异步的，其失败续体可能在页面/测试环境已拆掉后才跑，此时 DOM 不在了，忽略即可 */ }
    return;
  }
  loadSkin();                      // 头像 / 壁纸（不 await，别拖慢首屏）
  $('#admin-btn').classList.toggle('hidden', !ME.is_admin);
  $('#home-cards').innerHTML =
    SECTIONS.map(s => `
      <div class="home-card" data-go="sec:${esc(s.key)}">
        <div class="hc-logo hc-sec">${esc(s.icon)}</div>
        <div class="hc-name">${esc(s.name)}</div>
        <div class="hc-desc">${esc(s.desc)}</div>
      </div>`).join('') + `
    <div class="home-card" data-go="changkao"><div class="hc-logo hc-ck">${IC.target || IC.bulb}</div><div class="hc-name">常考</div><div class="hc-desc">高频成语/实词/上位词/常识/提法</div></div>
    <div class="home-card" data-go="notes"><div class="hc-logo">${IC.feather}</div><div class="hc-name">小记</div><div class="hc-desc">随手记 · 标签归类</div></div>
    <div class="home-card" data-go="kb"><div class="hc-logo">${IC.book}</div><div class="hc-name">知识库</div><div class="hc-desc">笔记本 · 文档 · 分组整理</div></div>
    <div class="home-card" data-go="wrongq"><div class="hc-logo">${IC.wrong}</div><div class="hc-name">错题本</div><div class="hc-desc">拍照/输入 · AI 判题型给解析</div></div>
    <div class="home-card" data-go="materials"><div class="hc-logo">${IC.folder}</div><div class="hc-name">资料库</div><div class="hc-desc">图片/文档/网页 应用内查看</div></div>
    <div class="home-card" data-go="quiz"><div class="hc-logo">${IC.edit}</div><div class="hc-name">题库</div><div class="hc-desc">四川省考卷面 · 每周自动更新</div></div>
    <div class="home-card" data-go="realq"><div class="hc-logo hc-real">${IC.target || IC.edit}<span class="rev-badge hidden" id="realq-badge"></span></div><div class="hc-name">历年真题</div><div class="hc-desc">国考/川考原卷 · 反复刷 · 错题自动重现</div></div>
    <div class="home-card" data-go="tasks"><div class="hc-logo">${IC.check || IC.clock}</div><div class="hc-name">任务清单</div><div class="hc-desc">每日任务 · 互监待办</div></div>
    <div class="home-card" data-go="drive"><div class="hc-logo hc-drive">☁️</div><div class="hc-name">云盘</div><div class="hc-desc">存取任意文件 · 发给好友</div></div>
    <div class="home-card" data-go="chat"><div class="hc-logo hc-chat">💬<span class="chat-badge hidden" id="chat-badge"></span></div><div class="hc-name">聊天</div><div class="hc-desc">加好友 · 聊天 · 传文件</div></div>
    <div class="home-card" data-go="review"><div class="hc-logo hc-rev">${IC.clock || IC.bulb}<span class="rev-badge hidden" id="rev-badge"></span></div><div class="hc-name">今日复习</div><div class="hc-desc" id="rev-desc">遗忘曲线 · 该复习的都在这</div></div>`;
  UI_ORDERS = ME.ui_orders || {};
  $('#home-cards').dataset.dragsort = 'home';
  $('#sl-types').dataset.dragsort = 'slt';
  $('#qz-entries').dataset.dragsort = 'qz';
  applyCardOrder($('#home-cards'));
  goHome();
  refreshReviewBadge();
  refreshRealqBadge();
  refreshChatBadge();
  chatConnect();               // 开秒推长连接
  hideSplash();
}
function hideSplash() {
  const sp = document.getElementById('splash'); if (!sp) return;
  // 名言至少展示 1.2 秒，再淡出进入首页
  const shown = Date.now() - (window.__t0 || Date.now());
  setTimeout(() => { sp.classList.add('fade'); setTimeout(() => sp.remove(), 550); },
    Math.max(0, 2000 - shown));
}
window.__t0 = Date.now();
setTimeout(hideSplash, 6000);  // 兜底：万一接口异常也不挡界面

/* ---------------- 应用内确认/输入弹窗（替代原生 confirm/prompt） ---------------- */
let _adResolve = null;
function _dialog(o) {
  return new Promise(res => {
    _adResolve = res;
    $('#ad-title').textContent = o.title || '确认';
    $('#ad-msg').textContent = o.msg || '';
    $('#ad-msg').classList.toggle('hidden', !o.msg);
    const inp = $('#ad-input');
    inp.classList.toggle('hidden', !o.input);
    if (o.input) { inp.value = o.val || ''; inp.placeholder = o.placeholder || ''; }
    $('#ad-ok').textContent = o.okText || '确定';
    $('#ad-ok').classList.toggle('danger', !!o.danger);
    const alt = $('#ad-alt');
    if (o.altText) { alt.hidden = false; alt.textContent = o.altText; alt.classList.toggle('danger', !!o.altDanger); }
    else alt.hidden = true;
    $('#ad-okval') && ($('#ad-okval').value = '');
    _adOkVal = o.okVal;
    $('#app-dialog').classList.remove('hidden');
    if (o.input) setTimeout(() => inp.focus(), 80);
  });
}
let _adOkVal;
function _adDone(v) {
  $('#app-dialog').classList.add('hidden');
  const r = _adResolve; _adResolve = null;
  if (r) r(v);
}
$('#ad-ok').onclick = () => _adDone($('#ad-input').classList.contains('hidden') ? (_adOkVal !== undefined ? _adOkVal : true) : $('#ad-input').value);
$('#ad-alt').onclick = () => _adDone('alt');
$('#ad-cancel').onclick = () => _adDone($('#ad-input').classList.contains('hidden') ? false : null);
$('#app-dialog').addEventListener('click', e => { if (e.target.id === 'app-dialog') $('#ad-cancel').click(); });
function appConfirm(msg, opts) {
  return _dialog(Object.assign({ title: '确认操作', msg, danger: /删除|退出|清空/.test(msg) }, opts || {}));
}
function appPrompt(title, placeholder, val) {
  return _dialog({ title, input: true, placeholder, val });
}
async function refreshReviewBadge() {
  try {
    const d = await api('/api/review/today?count=1');   // 角标只要 count，别拉回整份复习列表
    const b = $('#rev-badge');
    if (d.count > 0) { b.textContent = d.count > 99 ? '99+' : d.count; b.classList.remove('hidden'); }
    else b.classList.add('hidden');
    $('#rev-desc').textContent = d.count > 0 ? `今天有 ${d.count} 条要复习` : '今日复习完成，棒！';
  } catch (_) { /* 角标拉不到就不显示，下次进来会重试 */ }
}
// 首页某张卡片的跳转（按 data-go）。抽成独立函数：首页点击、AI 工具面板都复用它，
// 这样「打开功能」跟点首页图标行为完全一致，日后加新卡片两边一起生效。
function navHomeCard(g) {
  if (g.startsWith('sec:')) openSection(g.slice(4));
  else if (g === 'notes') openNotes();
  else if (g === 'kb') openKb();
  else if (g === 'wrongq') openWrongq();
  else if (g === 'materials') openMaterials();
  else if (g === 'idiom') openIdiom();
  else if (g === 'review') openReview();
  else if (g === 'tasks') openTasks();
  else if (g === 'quiz') openQuiz();
  else if (g === 'realq') openRealq();
  else if (g === 'changkao') openChangkao();
  else if (g === 'drive') openDrive();
  else if (g === 'chat') openChat();
}
$('#home-cards').addEventListener('click', e => {
  if (hcDragSuppress) return;   // 刚拖拽完的抬手不算点击
  const c = e.target.closest('[data-go]'); if (!c) return;
  navHomeCard(c.dataset.go);
});

/* ---------------- 卡片拖拽排序（通用）：电脑按住拖动，手机长按 0.4 秒再拖 ----------------
   容器带 data-dragsort="唯一键" 即可拖动其中的 .home-card；顺序按键独立存入账号(ui_orders)。 */
let hcDragSuppress = false;
let UI_ORDERS = {};
const CARD_KEY_ATTRS = ['go', 'secfeat', 'feat', 'slt', 'ckb', 'thb', 'csb', 'qzgo'];
function cardKey(c) {
  for (const k of CARD_KEY_ATTRS) if (c.dataset[k] !== undefined) return c.dataset[k];
  const n = c.querySelector('.hc-name');
  return n ? n.textContent.trim() : '';
}
function applyCardOrder(grid) {
  const key = grid && grid.dataset ? grid.dataset.dragsort : '';
  const order = key && UI_ORDERS[key];
  if (!Array.isArray(order) || !order.length) return;
  const cards = [...grid.querySelectorAll(':scope > .home-card')];
  const want = order.map(k => cards.find(c => cardKey(c) === k)).filter(Boolean)
    .concat(cards.filter(c => !order.includes(cardKey(c))));   // 之后新增的卡片排最后
  if (want.every((c, i) => c === cards[i])) return;            // 顺序已一致：避免观察器循环
  want.forEach(c => grid.appendChild(c));
}
async function saveCardOrder(grid) {
  const key = grid.dataset.dragsort; if (!key) return;
  const order = [...grid.querySelectorAll(':scope > .home-card')].map(cardKey);
  UI_ORDERS[key] = order;
  try {
    await api('/api/ui_order', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key, order }) });
  } catch (e) {
    // 拖完就走的动作：存不上的话下次进来顺序还是旧的，不说一声用户会以为是 bug
    console.warn('[首页] 卡片顺序保存失败：%s', (e && e.message) || e);
    toast('顺序没保存上：' + ((e && e.message) || '网络异常'), true);
  }
}
(function initCardDrag() {
  let grid = null, card = null, ghost = null, timer = null, sx = 0, sy = 0, dragging = false, isTouch = false;
  function startDrag(x, y) {
    dragging = true; hcDragSuppress = true;
    if (navigator.vibrate) navigator.vibrate(30);
    const r = card.getBoundingClientRect();
    ghost = card.cloneNode(true);
    ghost.classList.add('hc-ghost');
    ghost.style.width = r.width + 'px';
    document.body.appendChild(ghost);
    card.classList.add('hc-hole');
    moveGhost(x, y);
  }
  function moveGhost(x, y) {
    ghost.style.left = x + 'px'; ghost.style.top = y + 'px';
    const el = document.elementFromPoint(x, y);
    let over = el && el.closest ? el.closest('.home-card') : null;
    if (over && over.parentElement !== grid) over = null;   // 只在同一网格内换位
    let after = null;
    if (!over) {   // 网格空白处（如宽屏行尾）：行优先找最近的卡片落位
      const g = grid.getBoundingClientRect();
      if (x < g.left - 40 || x > g.right + 40 || y < g.top - 40 || y > g.bottom + 40) return;
      let bd = Infinity, bb = null;
      grid.querySelectorAll(':scope > .home-card').forEach(c => {
        if (c === card) return;
        const b = c.getBoundingClientRect();
        const dy = Math.max(b.top - y, y - b.bottom, 0);
        const dx = Math.max(b.left - x, x - b.right, 0);
        const d = dy * 10000 + dx;   // 行距离权重远大于列：先匹配所在行
        if (d < bd) { bd = d; over = c; bb = b; }
      });
      if (over) after = x > bb.left + bb.width / 2;   // 指针在目标卡右侧→插到它后面
    }
    if (!over || over === card) return;
    const cards = [...grid.querySelectorAll(':scope > .home-card')];
    if (after === null) after = cards.indexOf(card) < cards.indexOf(over);
    grid.insertBefore(card, after ? over.nextSibling : over);
  }
  function endDrag(save) {
    clearTimeout(timer); timer = null;
    if (!card && !dragging) return;
    if (ghost) { ghost.remove(); ghost = null; }
    if (card) card.classList.remove('hc-hole');
    if (dragging && save !== false && grid) saveCardOrder(grid);
    card = null; grid = null;
    if (dragging) { dragging = false; setTimeout(() => { hcDragSuppress = false; }, 60); }
  }
  document.addEventListener('pointerdown', e => {
    const c = e.target.closest('.home-card'); if (!c || dragging) return;
    const g = c.parentElement;
    if (!g || !g.dataset || !g.dataset.dragsort) return;
    grid = g; card = c; sx = e.clientX; sy = e.clientY; isTouch = e.pointerType !== 'mouse';
    if (isTouch) timer = setTimeout(() => startDrag(sx, sy), 400);   // 手机：长按进入拖动
  });
  document.addEventListener('pointermove', e => {
    if (!card) return;
    if (dragging) { moveGhost(e.clientX, e.clientY); return; }
    const moved = Math.abs(e.clientX - sx) + Math.abs(e.clientY - sy);
    if (isTouch) { if (moved > 10) endDrag(false); }       // 手指先动了 = 想滚动页面，取消长按
    else if (moved > 6) startDrag(e.clientX, e.clientY);   // 电脑：鼠标按住微移即拖
  });
  document.addEventListener('pointerup', () => endDrag());
  // 触摸的取消/滚动判断全靠 touch 事件（惯性滚动中长按会触发 pointercancel，不能据此取消）
  document.addEventListener('pointercancel', () => { if (!isTouch) endDrag(false); });
  document.addEventListener('touchmove', e => {
    const t = e.touches[0];
    if (!dragging) {
      // 长按等待中：手指移动超阈值 = 想滚动页面，取消长按
      if (card && t && Math.abs(t.clientX - sx) + Math.abs(t.clientY - sy) > 10) endDrag(false);
      return;
    }
    e.preventDefault();   // 拖动期间禁止页面滚动（必须非 passive）
    if (t) moveGhost(t.clientX, t.clientY);
  }, { passive: false });
  document.addEventListener('touchend', () => { if (dragging && isTouch) endDrag(); }, { passive: true });
  document.addEventListener('touchcancel', () => { if (dragging && isTouch) endDrag(false); }, { passive: true });
  document.addEventListener('contextmenu', e => { if (dragging || timer) e.preventDefault(); });   // 长按不弹系统菜单
  document.addEventListener('click', e => { if (hcDragSuppress) { e.stopPropagation(); e.preventDefault(); } }, true);   // 拖完的抬手不算点击
  // 任何卡片网格重新渲染后，自动应用该网格已保存的顺序
  new MutationObserver(muts => {
    if (dragging) return;
    const seen = new Set();
    const hit = g => { if (!seen.has(g)) { seen.add(g); applyCardOrder(g); } };
    muts.forEach(m => {
      const t = m.target;
      if (t.nodeType === 1 && t.dataset && t.dataset.dragsort) hit(t);
      m.addedNodes.forEach(n => {
        if (n.nodeType !== 1) return;
        if (n.dataset && n.dataset.dragsort) hit(n);
        if (n.querySelectorAll) n.querySelectorAll('[data-dragsort]').forEach(hit);
      });
    });
  }).observe(document.body, { childList: true, subtree: true });
})();
function openSection(key) {
  const sec = SECTIONS.find(s => s.key === key); if (!sec) return;
  $('#section-title').textContent = sec.name;
  const feats = SECTION_FEATURES[sec.name] || [];
  $('#section-feats').innerHTML = feats.map(f =>
    `<div class="home-card" data-secfeat="${esc(f.key)}">
      <div class="hc-logo">${IC[f.icon] || ''}</div>
      <div class="hc-name">${esc(f.name)}</div>
      <div class="hc-desc">${esc(f.desc)}</div>
    </div>`).join('');
  $('#section-feats').dataset.dragsort = 'secfeat:' + key;
  applyCardOrder($('#section-feats'));
  $('#board-grid').innerHTML = sec.boards.map(b => `
    <div class="board-card" data-board="${esc(b)}">
      <span class="bc-name">${esc(b)}</span>
      ${b === IDIOM_BOARD ? '<span class="bc-badge">成语词语</span>' : ''}
      <span class="bc-arrow">›</span>
    </div>`).join('')
    + (SECTION_EXTRA[sec.key] || []).map(x => `
    <div class="board-card" data-secgo="${esc(x.go)}">
      <span class="bc-name">${esc(x.name)}</span>
      <span class="bc-badge">${esc(x.badge)}</span>
      <span class="bc-arrow">›</span>
    </div>`).join('');
  push({ view: 'section', title: sec.name });
}
$('#board-grid').addEventListener('click', e => {
  const x = e.target.closest('[data-secgo]');
  if (x) {
    if (x.dataset.secgo === 'shenlun') openShenlun();
    else if (x.dataset.secgo === 'find') openFind();
    return;
  }
  const c = e.target.closest('[data-board]'); if (!c) return;
  openBoard(c.dataset.board);
});
$('#section-feats').addEventListener('click', e => {
  const c = e.target.closest('[data-secfeat]'); if (!c) return;
  if (c.dataset.secfeat === 'classics') openClassics();
});
let curBoardFeat = '';
function openBoard(board) {
  curBoardFeat = board;
  // 每个板块都有「基础知识点」，再加上板块专属功能
  const feats = [{ key: 'boardkb', name: '基础知识点', desc: '基础知识 · 方法技巧', icon: 'bulb' }]
    .concat(BOARD_FEATURES[board] || []);
  $('#board-title').textContent = board;
  $('#board-features').innerHTML = feats.map(f =>
    `<div class="home-card" data-feat="${esc(f.key)}">
      <div class="hc-logo">${IC[f.icon] || ''}</div>
      <div class="hc-name">${esc(f.name)}</div>
      <div class="hc-desc">${esc(f.desc)}</div>
    </div>`).join('');
  $('#board-features').dataset.dragsort = 'feat:' + board;
  applyCardOrder($('#board-features'));
  $('#board-features').classList.remove('hidden');
  $('#board-ph').classList.add('hidden');
  push({ view: 'board', title: board });
}
$('#board-features').addEventListener('click', e => {
  const c = e.target.closest('[data-feat]'); if (!c) return;
  if (c.dataset.feat === 'idiom') openIdiom();
  else if (c.dataset.feat === 'classics') openClassics();
  else if (c.dataset.feat === 'boardkb') openBoardKb(curBoardFeat);
  else if (c.dataset.feat === 'partydict') openPartyDict();
  else if (c.dataset.feat === 'policydoc') openPolicyDocs();
  else if (c.dataset.feat === 'news') openNews();
  else if (c.dataset.feat === 'videos') openVideos();
  else if (c.dataset.feat === 'gaikuo') openGaikuo();
  else if (c.dataset.feat === 'gongwen') openGongwen();
  else if (c.dataset.feat === 'drill') openDrill(curBoardFeat);
  else if (c.dataset.feat === 'write') openWrite('daily');
  else if (c.dataset.feat === 'wapp') openWrite('yingyong');
  else if (c.dataset.feat === 'fanwen') openFanwen();
  else if (c.dataset.feat === 'sucai') openSucai('全部');
  else if (c.dataset.feat === 'lianjie') openSucai('衔接表达');
  else if (c.dataset.feat === 'changshi') openChangshi();
  else if (c.dataset.feat === 'works') openWorks();
  else if (c.dataset.feat === 'theory') openTheory();
  else if (c.dataset.feat === 'hyper') openCkBoard('上位词');
});
$('#nav-back').onclick = back;
