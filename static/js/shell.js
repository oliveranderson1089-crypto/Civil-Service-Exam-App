/* 外壳：导航栈 / 初始化 / 首页 / 应用内弹窗 / 卡片拖拽排序
 *
 * 由 app.js 按它自己的区段边界切出（原 L157-538）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, ALL_BOARDS, BOARD_FEATURES, IC, IDIOM_BOARD, IS_MOBILE, LINE,
   Ink, KB, ME, SECTIONS, SECTION_EXTRA, SECTION_FEATURES,
   aiBack, api, avoidFab, basicsFeats, c, chatConnect, closeSlideshow, crCloseMenu,
   crInfoClose, crSheetClose, dqPoll,
   openBasicsCmp, openBasicsTree, tbRailFill,
   esc, loadNotebook, loadSkin, matClose, matInited, mkInject,
   newDraft, openBoardKb, openChangkao, openChangshi, openChat, openCkBoard,
   openClassics, openDrill, openDrive, openExam, openFanwen, openFind, openGaikuo,
   openGongwen, openIdiom, openKb, openMaterials, openNews, openNotes,
   openPartyDict, openPolicyDocs, openQuiz, openReview, openShenlun, openSucai,
   openTasks, openTheory, openVideos, openWorks, openWrite, openWrongq,
   padClose, qtPause, qtResume, qtTotalPause, qtTotalResume,
   qz, refreshChatBadge, refreshNtfDot, saveDoc, setViewerFull,
   stack, state, tdLoad, toast, toggleNoteSearch, openRealq, refreshRealqBadge,
   openYyErr, openYyLib */

/* ---------------- 导航 ---------------- */
const VIEWS = ['home', 'section', 'board', 'tab', 'allfeats', 'stars', 'notes', 'kb', 'notebook', 'doc', 'materials', 'idiom', 'viewer', 'search', 'classics', 'cdetail', 'wrongq', 'wqadd', 'wqdetail', 'boardkb', 'bktree', 'bknode', 'bkcmp', 'bksweep', 'account', 'partydict', 'policydoc', 'policydocd', 'news', 'newsd', 'exam', 'gaikuo', 'gongwen', 'yyerr', 'yylib', 'sucai', 'review', 'changshi', 'csboard', 'works', 'workd', 'quiz', 'quizrun', 'tasks', 'changkao', 'ckboard', 'theory', 'thboard', 'shenlun', 'slpaper', 'sltype', 'slgrade', 'slresult', 'notify', 'essays', 'essayd', 'quizsets', 'docqa', 'docqad', 'planlog', 'dtest', 'drafts', 'write', 'writed', 'realq', 'realrun', 'realrec', 'realrecd', 'sqreal', 'sqrun', 'sqres', 'sqcheck', 'sqlocal', 'sqsub', 'sqwrite', 'sqdrill', 'drill', 'drillrun', 'drillrec', 'drillrecd', 'find', 'findrun', 'findrec', 'findrecd', 'findwrong', 'videos', 'aiout', 'aishare', 'fanwen', 'fanwend', 'drive', 'chat'];
const TITLES = { home: '公考助手', section: '', board: '', tab: '', allfeats: '全部功能', stars: '收藏', notes: '小记', kb: '知识库', notebook: '', doc: '', materials: '资料库', drive: '云盘', idiom: '成语词语', viewer: '查看', search: '搜索', classics: '古诗文速查', cdetail: '', wrongq: '错题本', wqadd: '记录错题', wqdetail: '错题详情', boardkb: '基础知识点', bktree: '', bknode: '', bkcmp: '考点对照', account: '账户', partydict: '创新理论词典', policydoc: '时政要文库', policydocd: '', news: '每日时政', newsd: '', exam: '全国考情', gaikuo: '概括句积累', gongwen: '应用文上位词', yyerr: '应用文改错', yylib: '应用文素材库', sucai: '素材积累', review: '今日复习', changshi: '常识积累', csboard: '', works: '经典著作', workd: '', quiz: '题库', quizsets: '模拟卷', docqa: '题目解析', docqad: '', essays: '范文推荐', essayd: '', quizrun: '做题', tasks: '任务清单', changkao: '常考', ckboard: '', theory: '理论基础', thboard: '', shenlun: '真题批改', slpaper: '', sltype: '', slgrade: '', slresult: '批改结果', notify: '消息', planlog: '计划记录', dtest: '巩固测试', drafts: '草稿本', write: '成文', writed: '', realq: '历年真题', realrun: '', realrec: '做题记录', realrecd: '回看这一组', sqreal: '资中真题', sqrun: '', sqres: '成绩', sqcheck: '入库校对', sqlocal: '资中专项', sqsub: '主观题 40 分', sqwrite: '', sqdrill: '专项练', drill: '专项练', drillrun: '', drillrec: '做题记录', drillrecd: '', find: '小题训练', findrun: '', findrec: '做题记录', findrecd: '这次的批改', findwrong: '错题记录', videos: '每日新闻视频', aiout: 'AI 产出', aishare: '分享的对话' };
function render() {
  const st = stack[stack.length - 1];
  /* 换页先收起所有锚定小菜单（⋮ / ＋ 面板）。它们是 position:fixed 浮在最上层的，
     跟视图的显隐无关 —— 开着菜单点进另一页，菜单会一直悬在新页面上，
     而它记的还是上一页那个按钮的位置和上下文。这里统一收，各模块不用各记一遍。 */
  document.querySelectorAll('.ctxmenu:not(.hidden)').forEach(m => m.classList.add('hidden'));
  VIEWS.forEach(v => $('#view-' + v).classList.toggle('hidden', v !== st.view));
  // 聊天双栏：移动端按栈顶 state.room 决定显示会话列表还是聊天窗（back 出栈即回列表）
  // 云盘：栈顶记着当前在哪个目录，back() 弹回来时按它重列（逐级退，不是一步回首页）
  if (st.view === 'drive' && window.__dvShow) window.__dvShow(st);
  if (st.view === 'chat') {
    const p2 = $('#chat-2pane');
    if (p2 && IS_MOBILE) p2.classList.toggle('show-room', !!st.room);
  }
  // 当前是哪个视图，给 CSS 用：屏幕下方住着谁（小记的悬浮条…）只有它知道
  document.body.dataset.view = st.view;
  /* 记住「万一整页被文件顶掉，回来该落在哪个会话」（见 chat.js 的 __chatResumeMark）。
     下载/打开文件时浏览器可能把当前标签导航走，回来是重新加载，内存里的栈没了。 */
  if (window.__chatResumeMark) window.__chatResumeMark(st.view);
  $('#top-title').textContent = st.title || TITLES[st.view] || '公考助手';
  renderCrumb(st);
  $('#nav-back').classList.toggle('hidden', stack.length <= 1);
  // 文档编辑器自带顶栏，隐藏全局顶栏
  document.querySelector('.topbar').classList.toggle('hidden', st.view === 'doc');
  // 切换视图时停止朗读
  if (window.Reader && Reader.playing) Reader.stop();
  if (window.Ink && Ink.on) Ink.close();                  // 切视图退出批注模式（笔迹已按页面存好）
  // 离开阅读页必须退出全屏，否则状态栏一直藏着
  if (st.view !== 'viewer' && document.body.classList.contains('viewer-full')) setViewerFull(false);
  /* 同理：图片编辑是浮在最上面的一层，不是一个 view。用系统返回键/手势退出去时，
     没人替它收场 —— 底下换了页，编辑器还盖在屏幕上，谁也点不掉。 */
  if (st.view !== 'imgedit' && window.__ieHide) window.__ieHide();
  /* 兜底：body.pad-full 会让悬浮球 display:none。只要没有面板真的全屏开着，就把它摘掉——
     漏摘一次，悬浮球就一路消失到下次重开应用（返回键退全屏 AI 面板出过这个）。 */
  if (document.body.classList.contains('pad-full') && window.avoidFab) avoidFab();
  // 离开「题目解析」就别再轮询进度了（dqPoll 是顶层 let，不挂在 window 上）
  if (st.view !== 'docqa' && dqPoll) { clearInterval(dqPoll); dqPoll = null; }
  /* 做题页的表跟着视图**暂停/继续**，不是停掉。
     停掉的话有两笔账要还：一是人在别的页面看着看着弹「这题超过 60 秒了」，
     二是——更要命——qtStop 之后表清零，回来选答案时 qtStop() 返回 0，
     这道题的用时被静默记成 0 秒（做题记录、平均用时、超时统计一起失真）。
     暂停则把攒下的秒数留着，回到这一屏接着走。 */
  if (window.qtPause) {
    if (['realrun', 'drillrun', 'dtest'].includes(st.view)) { qtResume(); qtTotalResume(); }
    else { qtPause(); qtTotalPause(); }
  }
  if (window.__tabView) window.__tabView(st.view);        // 底部标签栏：该不该出现 + 亮哪一个
  if (window.__qpView) window.__qpView(st.view);          // 离开做题页把右栏借走的浮层还回去
  if (st.view === 'home' && window.tdLoad) tdLoad();      // 回首页刷新今日仪表盘（内部自带节流）
  if (window.__padView) window.__padView(st.view);        // 做题页才出现草稿纸按钮
  if (window.__bmView) window.__bmView();                 // 阅读页：上次看到哪了
  // 划重点的结果条/清单是 fixed 的顶层元素，换页或返回时先收走（回到原页会在 mkInject 里接回来）
  if (window.__mkView) window.__mkView();
  // 有划重点的模块，在正文顶部长出那张卡（内容是异步渲染的，等一拍再注入）
  if (window.mkInject) setTimeout(() => mkInject(), 260);
  if (st.view !== 'slgrade' && matInited && !$('#matpad').classList.contains('hidden')) matClose();
}
/* 面包屑：栈本身就是路径，直接铺出来（练 › 历年真题 › 2024 国考行测）。
   只在两层以上出现——首页上挂一个「公考助手 ›」是废话。

   宽度**照抄当前视图的**：每个视图的 max-width 各不相同（阅读类 760、做题页 1560…），
   在 CSS 里再抄一份对照表迟早对不上；直接读它算出来的值，永远和内容列对齐。 */
function renderCrumb(st) {
  const box = $('#crumb'); if (!box) return;
  // data-cb 必须是**stack 里的真实下标**：点击那边是 stack.slice(0, i+1)。
  // 过滤掉没标题的层之后再用过滤后的序号，遇到 push({view:'notebook'}) 这种空标题
  // 就会错位一格 —— 点当前这层反而退回上一层。
  const parts = stack.map((s2, i) => ({ i, t: s2.title || TITLES[s2.view] || '' })).filter(p => p.t);
  /* 手机端的聊天页不画面包屑：顶栏已经有返回键和对方的名字，会话顶栏还写了一遍
     （名字 + 人数 + 今天几人打卡），再来一行「公考助手 › 我的 › 聊天 › 某某」
     就是同一句话说三遍，白占掉一整行屏幕。别处照旧 —— 路径深的地方它是有用的。 */
  const on = parts.length > 1 && !(IS_MOBILE && st && st.view === 'chat');
  box.classList.toggle('hidden', !on);
  document.body.classList.toggle('has-crumb', on);
  if (!on) return;
  box.innerHTML = parts.map((p, n) =>
    `<span class="cb-i${n === parts.length - 1 ? ' cur' : ''}" data-cb="${p.i}">${esc(p.t)}</span>`)
    .join('<span class="cb-s">›</span>');
  const v = $('#view-' + st.view);
  if (v) {
    const cs = getComputedStyle(v);
    box.style.maxWidth = cs.maxWidth;
    box.style.paddingLeft = cs.paddingLeft;
    box.style.paddingRight = cs.paddingRight;
  }
}
// 点面包屑退回那一层（连点几次返回的替代品）
$('#crumb').addEventListener('click', e => {
  const c = e.target.closest('[data-cb]'); if (!c) return;
  const i = +c.dataset.cb;
  if (i >= stack.length - 1) return;
  stack = stack.slice(0, i + 1);
  render();
});
/* 用 <div> 当按钮的那些行（首页待办、标签页列表、库/我的的条目…）——
   它们的点击是委托在容器上的（data-td / data-tbi），所以用 div 很自然，
   代价是**键盘完全够不着**：实测首页 10 个可点元素里有 8 个 Tab 跳不到。
   模板里已经补了 tabindex="0" role="button"，这里补上另一半：
   role=button 的语义约定就是回车和空格等于点击。

   一个监听管全站，不用每个渲染函数各绑一次。
   空格要 preventDefault：不拦的话按下去先滚一屏，再跳转。 */
addEventListener('keydown', e => {
  if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
  if (e.altKey || e.ctrlKey || e.metaKey) return;
  const el = e.target;
  if (!el || el.getAttribute('role') !== 'button') return;
  // 原生按钮和链接浏览器自己会处理，别按两次
  if (el.tagName === 'BUTTON' || el.tagName === 'A') return;
  e.preventDefault();
  el.click();
});

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
  /* 看文件全屏时先退全屏，再退一级 —— 全屏下顶栏和查看器工具条都是隐藏的，
     这一步要是不做，返回键就把人从「全屏读 PDF」一下子扔回上一页（还留着沉浸式状态栏）。
     （原来这条判断长在查看器自己那个「‹ 返回」上，那个按钮已经撤了，见 index.html） */
  if (document.body.classList.contains('viewer-full')) { setViewerFull(false); return true; }
  // 0) 任意底部弹层 / 锚定小菜单（小记新建、知识库 +、块菜单、插入面板；资料库⋮、AI 会话⋮、
  //    知识库节点⋮、AI 附件来源等锚定菜单）——要放在 AI 面板分支之前，否则 AI 会话⋮菜单/
  //    附件来源开着时按返回会被 aiBack() 当成"退出会话"处理掉，而不是先关掉这个小菜单
  const sheets = [...document.querySelectorAll('.note-sheet:not(.hidden), .ctxmenu:not(.hidden)')];
  if (sheets.length) { sheets[sheets.length - 1].classList.add('hidden'); return true; }
  /* 1) 聊天自己的浮层 —— 原来一个都没列在这儿，所以在聊天窗里开着看大图/消息菜单/
     ＋号面板/会话信息时按返回，退掉的是**整个聊天窗**（一下退两级，回到会话列表）。
     顺序＝叠放顺序：后开的先关，每按一次只关一层。 */
  const fsheet = document.getElementById('cr-fsheet');       // 文件的「预览还是下载」
  if (fsheet) { fsheet.remove(); return true; }
  const lbx = document.getElementById('lbx');                // 看大图浮层
  if (lbx) { lbx.remove(); return true; }
  const cmenu = $('#cr-menu');                               // 消息长按菜单
  if (cmenu && !cmenu.classList.contains('hidden')) { crCloseMenu(); return true; }
  const csheet = $('#cr-sheet');                             // ＋号工具面板
  if (csheet && !csheet.classList.contains('hidden')) { crSheetClose(); return true; }
  const cinfo = $('#chat-info');                             // 会话信息栏（手机端是整屏盖上来的）
  if (IS_MOBILE && cinfo && !cinfo.classList.contains('hidden')) { crInfoClose(); return true; }
  // AI 面板
  const aip = $('#ai-panel');
  if (aip && !aip.classList.contains('hidden')) { return aiBack(); }
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
    LINE = d.line || LINE;
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
  // 左栏在 tabs.js 顶层就画过一次，那会儿 ME 还没回来 —— 管理员的「管理后台」那条得补画
  try { if (ME.is_admin && window.tbRailFill) tbRailFill(); } catch (_) { /* 左栏画不了不该拦住首屏 */ }
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
    <div class="home-card" data-go="exam"><div class="hc-logo hc-exam"><span class="hc-em">📣</span><span class="hc-sv">${IC.flag}</span></div><div class="hc-name">全国考情</div><div class="hc-desc">国考/省考/事考公告 · 每天自动汇总</div></div>
    <div class="home-card" data-go="realq"><div class="hc-logo hc-real">${IC.target || IC.edit}<span class="rev-badge hidden" id="realq-badge"></span></div><div class="hc-name">历年真题</div><div class="hc-desc">国考/川考原卷 · 反复刷 · 错题自动重现</div></div>
    <div class="home-card" data-go="tasks"><div class="hc-logo">${IC.check || IC.clock}</div><div class="hc-name">任务清单</div><div class="hc-desc">每日任务 · 互监待办</div></div>
    <div class="home-card" data-go="drive"><div class="hc-logo hc-drive"><span class="hc-em">☁️</span><span class="hc-sv">${IC.cloud}</span></div><div class="hc-name">云盘</div><div class="hc-desc">存取任意文件 · 发给好友</div></div>
    <div class="home-card" data-go="chat"><div class="hc-logo hc-chat"><span class="hc-em">💬</span><span class="hc-sv">${IC.chat}</span><span class="chat-badge hidden" id="chat-badge"></span></div><div class="hc-name">聊天</div><div class="hc-desc">加好友 · 聊天 · 传文件</div></div>
    <div class="home-card" data-go="review"><div class="hc-logo hc-rev">${IC.clock || IC.bulb}<span class="rev-badge hidden" id="rev-badge"></span></div><div class="hc-name">今日复习</div><div class="hc-desc" id="rev-desc">遗忘曲线 · 该复习的都在这</div></div>`;
  UI_ORDERS = ME.ui_orders || {};
  $('#home-cards').dataset.dragsort = 'home';
  $('#sl-types').dataset.dragsort = 'slt';
  $('#qz-entries').dataset.dragsort = 'qz';
  applyCardOrder($('#home-cards'));
  goHome();
  // 上一趟是在某个会话里看/下文件时被顶掉的 → 回到那个会话，而不是把人扔回首页
  try { if (window.__chatResume) window.__chatResume(); } catch (e) { console.warn('[聊天] 回到上次的会话没成功：', e); }
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
    $('#ad-cancel').textContent = o.cancelText || '取消';
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
  else if (g === 'exam') openExam();
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
    /* 社区这五个走 window.* —— 和下面 openBoardFeat 里那五个同一个理由：
       shequ.js 在 defer 的 rest 包里，首屏包不该出现指向它的裸标识符。
       成员调用不建立那层依赖，rest 还没到时也只是点了没反应，不会炸。 */
    else if (x.dataset.secgo === 'sqreal') { if (window.openSqReal) window.openSqReal(); }
    else if (x.dataset.secgo === 'sqcheck') { if (window.openSqCheck) window.openSqCheck(); }
    else if (x.dataset.secgo === 'sqlocal') { if (window.openSqLocal) window.openSqLocal(); }
    else if (x.dataset.secgo === 'sqsub') { if (window.openSqSub) window.openSqSub(); }
    else if (x.dataset.secgo === 'sqdrill') { if (window.openSqDrill) window.openSqDrill(); }
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
  // 每个板块都有「基础知识点」，有机构讲义的板块再多三张卡（哪几张由资料决定，
  // 见 basicsFeats：没导入三色的板块就不摆三色的入口），最后接板块专属功能
  const feats = [{ key: 'boardkb', name: 'AI 梳理 · 我的补充', desc: '按板块通梳 + 自己记的要点', icon: 'bulb' }]
    .concat(window.basicsFeats ? basicsFeats(board) : [])
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
/* 板块功能的分派。抽成具名函数是因为**有第二个调用方**：「练」标签页把板块页内联了
   （chips 选板块 → 直接列出这些功能，省掉一层），两边必须走同一份分派，
   否则哪天这儿加了个 key、那儿没加，表现就是「点了没反应」且不报错。 */
function openBoardFeat(k, board) {
  if (k === 'idiom') openIdiom();
  else if (k === 'classics') openClassics();
  else if (k === 'boardkb') openBoardKb(board);
  else if (k === 'bk-youlu') openBasicsTree(board, 'youlu');
  else if (k === 'bk-sanse') openBasicsTree(board, 'sanse');
  else if (k === 'bk-shequ') openBasicsTree(board, 'shequ');
  // 「社区」伪板块下的三本：key 里带着真板块名（bk-shequ@社会工作）
  else if (String(k).startsWith('bk-shequ@')) openBasicsTree(String(k).slice(9), 'shequ');
  else if (k === 'bk-cmp') openBasicsCmp(board);
  else if (k === 'partydict') openPartyDict();
  else if (k === 'policydoc') openPolicyDocs();
  else if (k === 'news') openNews();
  else if (k === 'videos') openVideos();
  else if (k === 'gaikuo') openGaikuo();
  else if (k === 'gongwen') openGongwen();
  else if (k === 'yyerr') openYyErr();
  else if (k === 'yylib') openYyLib();
  else if (k === 'drill') openDrill(board);
  else if (k === 'write') openWrite('daily');
  else if (k === 'wapp') openWrite('yingyong');
  else if (k === 'fanwen') openFanwen();
  else if (k === 'sucai') openSucai('全部');
  else if (k === 'lianjie') openSucai('衔接表达');
  else if (k === 'changshi') openChangshi();
  else if (k === 'works') openWorks();
  else if (k === 'theory') openTheory();
  else if (k === 'hyper') openCkBoard('上位词');
  /* 社区这两个走 window.* 而不是裸标识符：shequ.js 在 defer 的 rest 包里，
     而 shell.js 在首屏包，末尾那句 window.openBoardFeat = openBoardFeat 会把
     整条调用链算进「加载期就要在场」——裸名字会让首屏包同步引用一个还没到的符号，
     线上表现是**停在启动屏**。成员调用不建立这层依赖，顺带还能在没加载时不炸。 */
  else if (k === 'sqreal') { if (window.openSqReal) window.openSqReal(); }
  else if (k === 'sqcheck') { if (window.openSqCheck) window.openSqCheck(); }
  else if (k === 'sqlocal') { if (window.openSqLocal) window.openSqLocal(); }
  else if (k === 'sqsub') { if (window.openSqSub) window.openSqSub(); }
  else if (k === 'sqdrill') { if (window.openSqDrill) window.openSqDrill(); }
}
window.openBoardFeat = openBoardFeat;
$('#board-features').addEventListener('click', e => {
  const c = e.target.closest('[data-feat]'); if (!c) return;
  openBoardFeat(c.dataset.feat, curBoardFeat);
});
$('#nav-back').onclick = back;
