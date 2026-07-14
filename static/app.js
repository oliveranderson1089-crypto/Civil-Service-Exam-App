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
/* 中文输入法正在组字时，回车是「确认候选词」，不是「提交」。
   所有回车处理都必须先问一句 composing(e)，否则 fcitx/搜狗打中文时会被打断，
   表现就是「只打得出英文字母、候选框弹不出来」。 */
const composing = (e) => e.isComposing || e.keyCode === 229;
const IN_APP = navigator.userAgent.includes('GongkaoApp');
/* 桌面版（原生 GTK 壳）会注入 window.__desktop / __desktopVer；普通浏览器里没有 */
const IS_DESKTOP = !!window.__desktop;
const DESKTOP_VER = String(window.__desktopVer || '');
// 手机端：安卓壳内 或 窄屏。手机端与网页端使用不同的「小记」界面
const IS_MOBILE = IN_APP || window.matchMedia('(max-width:760px)').matches;
document.body.classList.toggle('mobile-ui', IS_MOBILE);
const PAGE_SIZE = 5;

window.toast = toast;   // 桌面壳出错时要能弹提示
function toast(msg, err) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (err ? ' err' : '');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.add('hidden'), 2300);
}
const esc = (s) => (s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
function fmtSize(n) {
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(1) + ' MB';
}
function fmtTime(s) { return (s || '').slice(5, 16); }
// 线性 SVG 图标
const _svg = (p) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const IC = {
  feather: _svg('<path d="M20.24 12.24a6 6 0 0 0-8.49-8.49L5 10.5V19h8.5z"/><line x1="16" y1="8" x2="2" y2="22"/><line x1="17.5" y1="15" x2="9" y2="15"/>'),
  folder: _svg('<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>'),
  book: _svg('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'),
  edit: _svg('<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>'),
  del: _svg('<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'),
  clip: _svg('<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>'),
  wrong: _svg('<path d="M9 11l-2 2 2 2"/><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="14 3 14 9 20 9"/><path d="M14.5 12.5l3 3M17.5 12.5l-3 3"/>'),
  bulb: _svg('<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.8 10.6c.5.5.8 1 .8 1.9v.5h6v-.5c0-.9.3-1.4.8-1.9A6 6 0 0 0 12 3z"/>'),
  clock: _svg('<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>'),
  check: _svg('<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>'),
  quote: _svg('<path d="M6 17h3l2-4V7H5v6h3z"/><path d="M14 17h3l2-4V7h-6v6h3z"/>'),
  target: _svg('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.4"/>'),
  play: _svg('<rect x="2" y="4" width="20" height="16" rx="3"/><path d="M10 9l5 3-5 3z" fill="currentColor"/>'),
  layers: _svg('<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>'),
  compass: _svg('<circle cx="12" cy="12" r="9"/><polygon points="16.2 7.8 14.1 14.1 7.8 16.2 9.9 9.9 16.2 7.8"/>'),
  flag: _svg('<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V4s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/>'),
  star: _svg('<polygon points="12 2.5 15 9 22 9.8 16.8 14.4 18.3 21.4 12 17.8 5.7 21.4 7.2 14.4 2 9.8 9 9 12 2.5"/>'),
};
// 板块下的功能模块（可扩展：以后给某板块加更多功能图标）
const BOARD_FEATURES = {
  // 这三块靠练不靠背：题型固定、有套路、拼速度 → 专项练（按题型刷 + 计时 + 秒杀技巧）
  '资料分析': [
    { key: 'drill', name: '专项练', desc: '6 类题型 · 计时 · 速算技巧 · 薄弱优先', icon: 'target' },
  ],
  '判断推理': [
    { key: 'drill', name: '专项练', desc: '图形推理 5 类规律 · 计时 · 薄弱优先', icon: 'target' },
  ],
  '数量关系': [
    { key: 'drill', name: '专项练', desc: '8 类题型 · 计时 · 秒杀技巧 · 薄弱优先', icon: 'target' },
  ],
  '常识判断': [
    { key: 'drill', name: '专项练', desc: '7 类考点 · 三档难度 · 计时 · 薄弱优先', icon: 'target' },
    { key: 'changshi', name: '常识积累', desc: '人文/科技/法律… 七大板块 每日更新', icon: 'bulb' },
  ],
  '言语理解与表达': [
    { key: 'drill', name: '专项练', desc: '逻辑填空/片段阅读/语句排序/病句 · 三档难度', icon: 'target' },
    { key: 'idiom', name: '成语词语积累', desc: '选词填空 · 拼音释义 · 导 PDF', icon: 'book' },
    { key: 'hyper', name: '上位词积累', desc: '逻辑填空概括词提示 · 每日推荐', icon: 'layers' },
  ],
  '政治理论': [
    { key: 'drill', name: '专项练', desc: '马原/毛概/中特/习思想 · 三档难度', icon: 'target' },
    { key: 'news', name: '每日时政', desc: '每天自动更新 · AI 摘要+考点', icon: 'feather' },
    { key: 'videos', name: '每日新闻视频', desc: '官方媒体 · AI 筛出最值得看的 · 国内/国际/四川', icon: 'play' },
    { key: 'policydoc', name: '时政要文库', desc: '二十大·十五五·两会报告 全文+AI解读', icon: 'book' },
    { key: 'partydict', name: '党的创新理论学习词典', desc: '两个确立·四个意识… 12371 术语速查', icon: 'book' },
    { key: 'theory', name: '理论基础', desc: '马原 · 毛概 · 中特 · 习思想 考点速记', icon: 'compass' },
  ],
  '应用文': [
    { key: 'wapp', name: '应用文成文', desc: '导航位已留 · 生成逻辑待定', icon: 'edit' },
    { key: 'gaikuo', name: '概括句积累', desc: '每日更新 · 材料表述→规范概括句', icon: 'edit' },
    { key: 'gongwen', name: '应用文上位词', desc: '公文规范上位表述 · 按场景归类 · AI 归纳', icon: 'layers' },
  ],
  '议论文': [
    { key: 'write', name: '成文', desc: '素材 → 大作文 · 每日成文 / 综合应用', icon: 'edit' },
    { key: 'sucai', name: '素材积累', desc: '每日更新 · 人物/事例/理论论据', icon: 'clip' },
    { key: 'lianjie', name: '衔接表达', desc: '过渡/转折/万能句式 不口语不重复', icon: 'quote' },
    { key: 'classics', name: '古诗文·名句速查', desc: '唐诗宋词 · 四书五经 · 查询收藏', icon: 'book' },
  ],
};
// 大板块（行测/申论）下的功能模块（预留，可扩展）
const SECTION_FEATURES = {};
// 挂在大板块底部、但不属于「资料分类」的入口（所以不写进 SECTIONS.boards）
const SECTION_EXTRA = {
  shenlun: [
    { name: '小题训练', badge: '找点 + 写点', go: 'find' },
    { name: '真题批改', badge: 'AI 逐点批改', go: 'shenlun' },
  ],
};

let ME = null, SECTIONS = [], IDIOM_BOARD = '', ALL_BOARDS = [];
let stack = [];

/* ---------------- 导航 ---------------- */
const VIEWS = ['home', 'section', 'board', 'notes', 'kb', 'notebook', 'doc', 'materials', 'idiom', 'viewer', 'search', 'classics', 'cdetail', 'wrongq', 'wqadd', 'wqdetail', 'boardkb', 'account', 'partydict', 'policydoc', 'policydocd', 'news', 'newsd', 'gaikuo', 'gongwen', 'sucai', 'review', 'changshi', 'csboard', 'works', 'workd', 'quiz', 'quizrun', 'tasks', 'changkao', 'ckboard', 'theory', 'thboard', 'shenlun', 'slpaper', 'sltype', 'slgrade', 'slresult', 'notify', 'essays', 'essayd', 'quizsets', 'docqa', 'docqad', 'planlog', 'dtest', 'drafts', 'write', 'writed', 'drill', 'drillrun', 'drillrec', 'drillrecd', 'find', 'findrun', 'videos'];
const TITLES = { home: '公考助手', section: '', board: '', notes: '小记', kb: '知识库', notebook: '', doc: '', materials: '资料库', idiom: '成语词语', viewer: '查看', search: '搜索', classics: '古诗文速查', cdetail: '', wrongq: '错题本', wqadd: '记录错题', wqdetail: '错题详情', boardkb: '基础知识点', account: '账户', partydict: '创新理论词典', policydoc: '时政要文库', policydocd: '', news: '每日时政', newsd: '', gaikuo: '概括句积累', gongwen: '应用文上位词', sucai: '素材积累', review: '今日复习', changshi: '常识积累', csboard: '', works: '经典著作', workd: '', quiz: '题库', quizsets: '模拟卷', docqa: '题目解析', docqad: '', essays: '范文推荐', essayd: '', quizrun: '做题', tasks: '任务清单', changkao: '常考', ckboard: '', theory: '理论基础', thboard: '', shenlun: '真题批改', slpaper: '', sltype: '', slgrade: '', slresult: '批改结果', notify: '消息', planlog: '计划记录', dtest: '巩固测试', drafts: '草稿本', write: '成文', writed: '', drill: '专项练', drillrun: '', drillrec: '做题记录', drillrecd: '', find: '小题训练', findrun: '', videos: '每日新闻视频' };
function render() {
  const st = stack[stack.length - 1];
  VIEWS.forEach(v => $('#view-' + v).classList.toggle('hidden', v !== st.view));
  $('#top-title').textContent = st.title || TITLES[st.view] || '公考助手';
  $('#nav-back').classList.toggle('hidden', stack.length <= 1);
  // 文档编辑器自带顶栏，隐藏全局顶栏
  document.querySelector('.topbar').classList.toggle('hidden', st.view === 'doc');
  // 切换视图时停止朗读
  if (window.Reader && Reader.playing) Reader.stop();
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
  } catch (e) { return; }
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
    <div class="home-card" data-go="tasks"><div class="hc-logo">${IC.check || IC.clock}</div><div class="hc-name">任务清单</div><div class="hc-desc">每日任务 · 互监待办</div></div>\n    <div class="home-card" data-go="review"><div class="hc-logo hc-rev">${IC.clock || IC.bulb}<span class="rev-badge hidden" id="rev-badge"></span></div><div class="hc-name">今日复习</div><div class="hc-desc" id="rev-desc">遗忘曲线 · 该复习的都在这</div></div>`;
  UI_ORDERS = ME.ui_orders || {};
  $('#home-cards').dataset.dragsort = 'home';
  $('#sl-types').dataset.dragsort = 'slt';
  $('#qz-entries').dataset.dragsort = 'qz';
  applyCardOrder($('#home-cards'));
  goHome();
  refreshReviewBadge();
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
    const d = await api('/api/review/today');
    const b = $('#rev-badge');
    if (d.count > 0) { b.textContent = d.count > 99 ? '99+' : d.count; b.classList.remove('hidden'); }
    else b.classList.add('hidden');
    $('#rev-desc').textContent = d.count > 0 ? `今天有 ${d.count} 条要复习` : '今日复习完成，棒！';
  } catch (_) {}
}
$('#home-cards').addEventListener('click', e => {
  if (hcDragSuppress) return;   // 刚拖拽完的抬手不算点击
  const c = e.target.closest('[data-go]'); if (!c) return;
  const g = c.dataset.go;
  if (g.startsWith('sec:')) openSection(g.slice(4));
  else if (g === 'notes') openNotes();
  else if (g === 'kb') openKb();
  else if (g === 'wrongq') openWrongq();
  else if (g === 'materials') openMaterials();
  else if (g === 'idiom') openIdiom();
  else if (g === 'review') openReview();
  else if (g === 'tasks') openTasks();
  else if (g === 'quiz') openQuiz();
  else if (g === 'changkao') openChangkao();
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
  } catch (_) {}
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
  else if (c.dataset.feat === 'sucai') openSucai('全部');
  else if (c.dataset.feat === 'lianjie') openSucai('衔接表达');
  else if (c.dataset.feat === 'changshi') openChangshi();
  else if (c.dataset.feat === 'works') openWorks();
  else if (c.dataset.feat === 'theory') openTheory();
  else if (c.dataset.feat === 'hyper') openCkBoard('上位词');
});
$('#nav-back').onclick = back;

/* ================= 小记（仿语雀） ================= */
let curNoteBoard = '';
let curTag = '';
let noteSearchQ = '';
// 板块的下拉选项（编辑器、feed 筛选、快速记 三处共用）
function boardOptions(sel, withAll) {
  return (withAll ? `<option value="">全部板块</option>` : `<option value="">不分板块</option>`)
    + SECTIONS.map(s => `<optgroup label="${esc(s.name)}">`
      + s.boards.map(b => `<option value="${esc(b)}"${b === sel ? ' selected' : ''}>${esc(b)}</option>`).join('')
      + '</optgroup>').join('');
}
// 电脑端原来有一整栏板块目录（占掉最左边一大条）。板块只是个归类，不值得占一栏 ——
// 改成「写的时候在编辑器里选，看的时候在顶部下拉筛」，功能一样，屏幕省下来给正文。
function buildNotesSidebar() {
  const fb = $('#feed-board');
  if (fb) fb.innerHTML = boardOptions(curNoteBoard, true);
  const cb = $('#cp-board');
  if (cb) cb.innerHTML = boardOptions(draft.board != null ? draft.board : curNoteBoard, false);
}
async function refreshNoteCounts() {
  try {
    const d = await api('/api/notes/counts');
    document.querySelectorAll('[data-cnt]').forEach(el => {
      const n = el.dataset.cnt === '' ? (d.total || 0) : (d.counts[el.dataset.cnt] || 0);
      el.textContent = n ? n : '';
    });
  } catch (_) {}
}
function openNotes(board) {
  curTag = '';
  if (IS_MOBILE) {
    // 手机端：统一信息流（不分板块，用标签区分）
    curNoteBoard = '';
    noteSearchQ = '';
    $('#notes-msearch').classList.add('hidden');
    $('#notes-msearch-input').value = '';
    push({ view: 'notes' });
    newDraft(); loadFeed(); loadFeedTags();
    return;
  }
  curNoteBoard = board != null ? board : (curNoteBoard || '');
  buildNotesSidebar();
  push({ view: 'notes' });
  newDraft(); loadFeed(); loadFeedTags(); refreshNoteCounts();
}
$('#feed-board').addEventListener('change', () => {     // 顶部下拉：按板块筛选
  curNoteBoard = $('#feed-board').value; curTag = '';
  loadFeed(); loadFeedTags();
});
$('#cp-board').addEventListener('change', () => {       // 编辑器：这条归到哪个板块
  draft.board = $('#cp-board').value;
});

/* ---- 编辑器（草稿） ---- */
let draft = { id: null, content: '', images: [], files: [], todos: [], tags: [] };
function newDraft() {
  draft = { id: null, content: '', images: [], files: [], todos: [], tags: [],
            board: curNoteBoard };   // 新写的默认归到当前筛选的板块
  $('#cp-content').value = ''; renderComposer();
  closeComposerM();
}
// 手机端：把内嵌编辑器变成全屏弹出 / 收起
function openComposerM() {
  if (!IS_MOBILE) return;
  document.querySelector('.composer').classList.add('cp-open');
  document.body.classList.add('cp-open-lock');
  setTimeout(() => $('#cp-content').focus(), 60);
}
function closeComposerM() {
  document.querySelector('.composer').classList.remove('cp-open');
  document.body.classList.remove('cp-open-lock');
}
function loadDraft(n) {
  draft = {
    id: n.id, content: n.content, board: n.board || '',
    images: n.img_files.map((f, i) => ({ kind: 'old', file: f, url: n.images[i] })),
    files: n.att_files.map((a, i) => ({ kind: 'old', file: a.file, name: a.name, ext: a.ext, url: n.attachments[i].url })),
    todos: n.todos.map(t => ({ text: t.text, done: !!t.done })),
    tags: [...n.tags],
  };
  $('#cp-content').value = n.content;
  renderComposer();
  if (IS_MOBILE) { openComposerM(); return; }
  $('#view-notes').scrollIntoView({ behavior: 'smooth', block: 'start' });
  $('#cp-content').focus();
}
function renderComposer() {
  const cb = $('#cp-board');
  if (cb) cb.value = (draft.board != null ? draft.board : curNoteBoard) || '';
  $('#cp-todos').innerHTML = draft.todos.map((t, i) =>
    `<div class="cp-todo"><input type="checkbox" data-tdo="${i}" ${t.done ? 'checked' : ''}>
     <input class="cp-todo-text" data-tdt="${i}" value="${esc(t.text)}" placeholder="待办事项…">
     <button class="cp-x" data-tdr="${i}">×</button></div>`).join('');
  $('#cp-imgs').innerHTML = draft.images.map((im, i) =>
    `<div class="cp-thumb${im.busy ? ' busy' : ''}" data-imb="${i}">
       <img src="${im.url}" data-imbig="${i}" title="点开看大图，确认没传错">
       <button class="cp-x" data-imr="${i}">×</button>
     </div>`).join('');
  $('#cp-files').innerHTML = draft.files.map((f, i) =>
    `<div class="cp-file">📎 <span>${esc(f.name)}</span><button class="cp-x" data-flr="${i}">×</button></div>`).join('');
  $('#cp-tags').innerHTML = draft.tags.map((t, i) =>
    `<span class="cp-tag"># ${esc(t)}<button class="cp-x" data-tgr="${i}">×</button></span>`).join('') +
    `<button type="button" class="cp-tag-add" data-tagadd>＋ 标签</button>`;
  const editing = !!draft.id;
  $('#cp-submit').textContent = editing ? '保存' : '发布';
  $('#cp-del').classList.toggle('hidden', !editing);
  $('#cp-cancel').classList.toggle('hidden', !editing);
  $('#cp-hint').textContent = editing ? '编辑中…' : '';
  // 手机端全屏编辑器顶栏
  $('#cp-mtitle').textContent = editing ? '编辑小记' : '写小记';
  $('#cp-mdel').classList.toggle('hidden', !editing);
}
document.querySelector('.cp-bar').addEventListener('click', e => {
  const b = e.target.closest('[data-cp]'); if (!b) return;
  const t = b.dataset.cp;
  if (t === 'img') $('#cp-imgfile').click();
  else if (t === 'cam') $('#cp-camfile').click();
  else if (t === 'file') $('#cp-attfile').click();
  else if (t === 'todo') {
    draft.todos.push({ text: '', done: false }); renderComposer();
    const ins = document.querySelectorAll('.cp-todo-text'); if (ins.length) ins[ins.length - 1].focus();
  } else if (t === 'tag') {
    showTagInput();
  }
});
/* 行内标签输入（替代原生 prompt，仿语雀） */
function showTagInput() {
  const inp = $('#cp-taginput');
  inp.classList.remove('hidden'); inp.value = '';
  setTimeout(() => inp.focus(), 30);
}
function addTagsFrom(raw) {
  let added = false;
  (raw || '').split(/[\s,，、]+/).filter(Boolean).forEach(v => {
    if (!draft.tags.includes(v)) { draft.tags.push(v); added = true; }
  });
  return added;
}
$('#cp-taginput').addEventListener('keydown', e => {
  if (!composing(e) && e.key === 'Enter') {
    e.preventDefault();
    if (addTagsFrom(e.target.value)) renderComposer();
    e.target.value = '';
    setTimeout(() => { const i = $('#cp-taginput'); i.classList.remove('hidden'); i.focus(); }, 10);
  } else if (e.key === 'Escape') { e.target.value = ''; e.target.classList.add('hidden'); }
});
$('#cp-taginput').addEventListener('blur', e => {
  if (addTagsFrom(e.target.value)) renderComposer();
  e.target.value = ''; e.target.classList.add('hidden');
});
$('#cp-tags').addEventListener('click', e => {
  if (e.target.closest('[data-tagadd]')) { showTagInput(); }
});
// 立刻把所选文件读进内存（趁 content:// URI 权限还有效），避免发布时 URI 失效导致传 0 字节
async function _materialize(f, fallbackType) {
  try {
    const buf = await f.arrayBuffer();
    return new Blob([buf], { type: f.type || fallbackType || 'application/octet-stream' });
  } catch (_) { return f; }   // 兜底用原 File
}
/* 轻量看图浮层：就地放大，不跳走、不丢正在写的草稿（openViewerUrl 会 push 一个新视图，
   写到一半跑去看图再回来，体验很别扭）。Esc / 点背景 / 点图都能关。 */
/* 看图浮层：就地放大，不跳走（openViewerUrl 会 push 一个新视图，写到一半跑去看图再回来很别扭）。
   ★ 草稿里的图和已发布的图**走同一条路**——原来已发布的图走 openViewerUrl（全屏阅读器），
     草稿里的走这个浮层，所以「上传前小、上传后巨大」。统一到这里。
   ★ 手机端支持**双指捏合缩放**；电脑端滚轮缩放、拖动平移。
   ★ 「复制图片」是真把**图片本身**写进剪贴板（不是图片地址）—— 原来复制出来是一串 URL。 */
function lightbox(url, name) {
  if (!url) return;
  const old = document.getElementById('lbx'); if (old) old.remove();
  const box = document.createElement('div');
  box.id = 'lbx'; box.className = 'lbx';
  box.innerHTML = `
    <div class="lbx-bar">
      <button class="lbx-b" data-lbx="copy" title="复制图片本身（不是地址）">⧉ 复制图片</button>
      <a class="lbx-b" href="${url}" download="${esc(name || 'image.png')}" title="下载">⤓ 下载</a>
      <button class="lbx-b" data-lbx="reset" title="还原大小">⤢ 还原</button>
      <button class="lbx-b lbx-x" data-lbx="close" title="关闭（Esc）">×</button>
    </div>
    <div class="lbx-stage"><img id="lbx-img" src="${url}" alt=""></div>
    <div class="lbx-hint">双指捏合 / 滚轮缩放 · 拖动平移 · 点背景关闭</div>`;
  document.body.appendChild(box);

  const img = box.querySelector('#lbx-img');
  const stage = box.querySelector('.lbx-stage');
  let scale = 1, tx = 0, ty = 0;
  const apply = () => { img.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`; };
  const reset = () => { scale = 1; tx = ty = 0; apply(); };

  // ⚠️ 这个键盘处理函数原来叫 esc，把全局的 esc()（HTML 转义）**遮蔽**了 ——
  //    上面 innerHTML 里用到 esc(name) 就直接 ReferenceError。改名 onEsc。
  const close = () => { box.remove(); document.removeEventListener('keydown', onEsc); };
  const onEsc = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onEsc);

  box.addEventListener('click', e => {
    if (e.target === box || e.target === stage) { close(); return; }   // 点背景才关，点图不关
    const b = e.target.closest('[data-lbx]'); if (!b) return;
    const a = b.dataset.lbx;
    if (a === 'close') close();
    else if (a === 'reset') reset();
    else if (a === 'copy') copyImage(url, b);
  });

  // 滚轮缩放（电脑端）
  stage.addEventListener('wheel', e => {
    e.preventDefault();
    scale = Math.min(6, Math.max(0.4, scale * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
    apply();
  }, { passive: false });

  // 双指捏合（手机端）+ 单指/鼠标拖动平移
  const pts = new Map();
  let d0 = 0, s0 = 1, px = 0, py = 0;
  stage.addEventListener('pointerdown', e => {
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    stage.setPointerCapture(e.pointerId);
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      d0 = Math.hypot(a.x - b.x, a.y - b.y); s0 = scale;
    } else { px = e.clientX - tx; py = e.clientY - ty; }
  });
  stage.addEventListener('pointermove', e => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size >= 2) {
      const [a, b] = [...pts.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (d0 > 0) { scale = Math.min(6, Math.max(0.4, s0 * d / d0)); apply(); }
    } else if (scale !== 1) {              // 没放大时不平移，免得挡住「点背景关闭」
      tx = e.clientX - px; ty = e.clientY - py; apply();
    }
  });
  const up = e => { pts.delete(e.pointerId); if (pts.size < 2) d0 = 0; };
  stage.addEventListener('pointerup', up);
  stage.addEventListener('pointercancel', up);
  // 双击/双击图片 = 放大/还原
  img.addEventListener('dblclick', () => { scale = scale > 1 ? 1 : 2.2; tx = ty = 0; apply(); });
}

/* 复制图片：把**图片本身**写进剪贴板（原来复制出来只是一串 URL，粘贴到别处就是个地址）。
   剪贴板只认 image/png，所以 jpg/webp 要先用 canvas 转一道。 */
async function copyImage(url, btn) {
  const label = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '复制中…'; }
  try {
    if (!navigator.clipboard || !window.ClipboardItem) throw new Error('这个浏览器不支持复制图片');
    const blob = await (await fetch(url)).blob();
    let png = blob;
    if (blob.type !== 'image/png') {          // 剪贴板只吃 png
      const bmp = await createImageBitmap(blob);
      const cv = document.createElement('canvas');
      cv.width = bmp.width; cv.height = bmp.height;
      cv.getContext('2d').drawImage(bmp, 0, 0);
      bmp.close();
      png = await new Promise(r => cv.toBlob(r, 'image/png'));
    }
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': png })]);
    toast('图片已复制，可以直接粘贴了');
  } catch (e) {
    toast('复制图片失败：' + e.message, true);
  }
  if (btn) { btn.disabled = false; btn.textContent = label; }
}

/* 图片压缩：手机拍的图动辄 4~8MB，原样上传 → 点「发布」那一下就卡住了。
   在**选图时**就压到 1600px / JPEG 0.82，发布时传的是几百 KB，一下就完。
   但压缩不能挡住添加：先把缩略图（原图 objectURL）立刻放上去，压缩丢到后台，
   压完再换掉 fileObj。发布时若还没压完，submit 会等一下（一般早压完了）。 */
async function compressImage(file, maxSide = 1600, quality = 0.82) {
  if (!/^image\//.test(file.type) || /gif|svg/i.test(file.type)) return file;   // 动图/矢量图不动
  let bmp;
  try { bmp = await createImageBitmap(file); } catch (_) { return file; }
  const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
  if (scale === 1 && file.size < 700 * 1024) { bmp.close(); return file; }       // 本来就小，别白折腾
  const w = Math.round(bmp.width * scale), h = Math.round(bmp.height * scale);
  let blob = null;
  try {
    let cv;
    if (typeof OffscreenCanvas !== 'undefined') cv = new OffscreenCanvas(w, h);
    else { cv = document.createElement('canvas'); cv.width = w; cv.height = h; }
    const ctx = cv.getContext('2d');
    ctx.drawImage(bmp, 0, 0, w, h);
    blob = cv.convertToBlob
      ? await cv.convertToBlob({ type: 'image/jpeg', quality })
      : await new Promise(r => cv.toBlob(r, 'image/jpeg', quality));
  } catch (_) { blob = null; }
  bmp.close();
  return (blob && blob.size < file.size) ? blob : file;   // 压完反而更大就用原图
}

async function addDraftImages(files) {
  const list = [...files];
  for (const f of list) {
    const im = {
      kind: 'new', fileObj: f, name: f.name || ('img_' + Date.now() + '.jpg'),
      url: URL.createObjectURL(f), busy: true,
    };
    draft.images.push(im);
    im.ready = compressImage(f).then(b => {          // 后台压，不挡添加
      im.fileObj = b; im.busy = false;
      const el = document.querySelector(`[data-imb="${draft.images.indexOf(im)}"]`);
      if (el) el.classList.remove('busy');
    }).catch(() => { im.busy = false; });
  }
  renderComposer();
}
$('#cp-imgfile').addEventListener('change', async e => { const fs = [...e.target.files]; e.target.value = ''; await addDraftImages(fs); });
bindImgDrop(document.querySelector('.composer'), addDraftImages);      // 拖图片进编辑器
bindImgPaste($('#cp-content'), addDraftImages);                        // Ctrl+V 粘图片
$('#cp-camfile').addEventListener('change', async e => { const fs = [...e.target.files]; e.target.value = ''; await addDraftImages(fs); });
$('#cp-attfile').addEventListener('change', async e => {
  const list = [...e.target.files]; e.target.value = '';
  for (const f of list) {
    const blob = await _materialize(f);
    draft.files.push({ kind: 'new', fileObj: blob, name: f.name || 'file' });
  }
  renderComposer();
});
$('#cp-todos').addEventListener('click', e => { const r = e.target.closest('[data-tdr]'); if (r) { draft.todos.splice(+r.dataset.tdr, 1); renderComposer(); } });
$('#cp-todos').addEventListener('change', e => { const c = e.target.closest('[data-tdo]'); if (c) draft.todos[+c.dataset.tdo].done = c.checked; });
$('#cp-todos').addEventListener('input', e => { const t = e.target.closest('[data-tdt]'); if (t) draft.todos[+t.dataset.tdt].text = t.value; });
$('#cp-imgs').addEventListener('click', e => {
  const r = e.target.closest('[data-imr]');
  if (r) { draft.images.splice(+r.dataset.imr, 1); renderComposer(); return; }
  const b = e.target.closest('[data-imbig]');            // 发布前就能点开看大图，确认没传错
  if (b) lightbox(draft.images[+b.dataset.imbig].url);
});
$('#cp-files').addEventListener('click', e => { const r = e.target.closest('[data-flr]'); if (r) { draft.files.splice(+r.dataset.flr, 1); renderComposer(); } });
$('#cp-tags').addEventListener('click', e => { const r = e.target.closest('[data-tgr]'); if (r) { draft.tags.splice(+r.dataset.tgr, 1); renderComposer(); } });
$('#cp-cancel').onclick = () => newDraft();
$('#cp-del').onclick = async () => {
  if (!draft.id || !(await appConfirm('删除这条小记？'))) return;
  try { await api('/api/notes/' + draft.id, { method: 'DELETE' }); toast('已删除'); newDraft(); loadFeed(); loadFeedTags(); refreshNoteCounts(); }
  catch (e) { toast(e.message, true); }
};
$('#cp-submit').onclick = async () => {
  const content = $('#cp-content').value.trim();
  draft.todos = draft.todos.filter(t => (t.text || '').trim() !== '');
  if (!content && !draft.images.length && !draft.files.length && !draft.todos.length) { toast('写点什么吧', true); return; }
  $('#cp-submit').disabled = true;
  // 压缩一般在选图时就跑完了；万一刚选完就点发布，这里等一下（避免传上去的是原图）
  const pending = draft.images.filter(i => i.ready).map(i => i.ready);
  if (pending.length) await Promise.all(pending);
  const fd = new FormData();
  fd.append('board', draft.board != null ? draft.board : curNoteBoard);
  fd.append('content', content);
  fd.append('todos', JSON.stringify(draft.todos));
  fd.append('tags', JSON.stringify(draft.tags));
  draft.images.filter(i => i.kind === 'new').forEach(i => fd.append('images', i.fileObj, i.name || 'image.jpg'));
  draft.files.filter(i => i.kind === 'new').forEach(i => fd.append('attachments', i.fileObj, i.name || 'file'));
  try {
    if (draft.id) {
      fd.append('keep_imgs', JSON.stringify(draft.images.filter(i => i.kind === 'old').map(i => i.file)));
      fd.append('keep_atts', JSON.stringify(draft.files.filter(i => i.kind === 'old').map(i => i.file)));
      await api('/api/notes/' + draft.id, { method: 'PUT', body: fd });
    } else {
      await api('/api/notes', { method: 'POST', body: fd });
    }
    toast('已保存'); newDraft(); loadFeed(); loadFeedTags(); refreshNoteCounts();
  } catch (e) { toast(e.message, true); }
  $('#cp-submit').disabled = false;
};

/* ---- 手机端：底部悬浮条 / 新建面板 / 全屏编辑器 ---- */
// 全屏编辑器顶栏：取消 / 删除 / 完成
$('#cp-mclose').onclick = () => newDraft();
$('#cp-msave').onclick = () => $('#cp-submit').click();
$('#cp-mdel').onclick = () => $('#cp-del').click();
// 底部悬浮条
$('#notes-pill').addEventListener('click', e => {
  const b = e.target.closest('[data-pill]'); if (!b) return;
  const p = b.dataset.pill;
  if (p === 'add') $('#note-sheet').classList.remove('hidden');
  else if (p === 'search') toggleNoteSearch();
  else if (p === 'ai') openAI();
});
// 新建小记面板
$('#note-sheet').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]')) { $('#note-sheet').classList.add('hidden'); return; }
  const b = e.target.closest('[data-new]'); if (!b) return;
  $('#note-sheet').classList.add('hidden');
  const m = b.dataset.new;
  if (m === 'ocr') { $('#ocr-file').click(); return; }
  newNoteM(m);
});
$('#ocr-file').addEventListener('change', async e => {
  const f = e.target.files[0]; e.target.value = ''; if (!f) return;
  toast('正在识别文字…');
  const fd = new FormData(); fd.append('file', f);
  try {
    const d = await api('/api/ocr', { method: 'POST', body: fd });
    newDraft();
    $('#cp-content').value = d.text || '';
    draft.content = d.text || '';
    openComposerM();
    toast(d.text ? '识别完成，可编辑后发布' : '没识别到文字，可手动输入', !d.text);
  } catch (err) { toast(err.message, true); }
});
function newNoteM(mode) {
  newDraft();
  openComposerM();
  if (mode === 'img') $('#cp-imgfile').click();
  else if (mode === 'cam') $('#cp-camfile').click();
  else if (mode === 'file') $('#cp-attfile').click();
  else if (mode === 'todo') { draft.todos.push({ text: '', done: false }); renderComposer(); }
}
// 手机端搜索
function toggleNoteSearch() {
  const box = $('#notes-msearch');
  box.classList.toggle('hidden');
  if (box.classList.contains('hidden')) {
    if (noteSearchQ) { noteSearchQ = ''; $('#notes-msearch-input').value = ''; loadFeed(); }
  } else {
    setTimeout(() => $('#notes-msearch-input').focus(), 50);
  }
}
let noteSearchTimer;
$('#notes-msearch-input').addEventListener('input', e => {
  clearTimeout(noteSearchTimer);
  noteSearchTimer = setTimeout(() => { noteSearchQ = e.target.value.trim(); loadFeed(); }, 200);
});

/* ---- 动态流 ---- */
async function loadFeedTags() {
  try {
    const d = await api('/api/notes/tags?board=' + encodeURIComponent(curNoteBoard));
    $('#feed-tags').innerHTML = d.tags.length
      ? `<button class="tagchip${curTag === '' ? ' active' : ''}" data-tag="">全部</button>` +
        d.tags.map(t => `<button class="tagchip${curTag === t ? ' active' : ''}" data-tag="${esc(t)}"># ${esc(t)}</button>`).join('')
      : '';
  } catch (_) {}
}
$('#feed-tags').addEventListener('click', e => {
  const c = e.target.closest('[data-tag]'); if (!c) return;
  curTag = c.dataset.tag;
  document.querySelectorAll('#feed-tags .tagchip').forEach(x => x.classList.toggle('active', x.dataset.tag === curTag));
  loadFeed();
});
async function loadFeed() {
  try {
    let url = '/api/notes?board=' + encodeURIComponent(curNoteBoard);
    if (curTag) url += '&tag=' + encodeURIComponent(curTag);
    const d = await api(url);
    const box = $('#feed');
    let items = d.items;
    if (noteSearchQ) {
      const q = noteSearchQ;
      items = items.filter(n => (n.content || '').includes(q)
        || (n.tags || []).some(t => t.includes(q))
        || (n.todos || []).some(t => (t.text || '').includes(q)));
    }
    if (!items.length) {
      box.innerHTML = ''; box._items = [];
      $('#feed-empty').classList.remove('hidden');
      $('#feed-empty').textContent = noteSearchQ ? '没有匹配「' + noteSearchQ + '」的小记'
        : (IS_MOBILE ? '还没有小记，点下面的 ＋ 写一条吧～' : '还没有小记，在左侧写一条吧～');
      return;
    }
    $('#feed-empty').classList.add('hidden');
    box.innerHTML = items.map(feedCard).join('');
    box._items = items;
  } catch (e) { toast(e.message, true); }
}
function feedCard(n) {
  const todos = n.todos.length ? `<div class="fc-todos">${n.todos.map((t, i) =>
    `<label class="fc-todo${t.done ? ' done' : ''}"><input type="checkbox" data-tg="${n.id}" data-ti="${i}" ${t.done ? 'checked' : ''}><span>${esc(t.text)}</span></label>`).join('')}</div>` : '';
  const imgs = n.images.length ? `<div class="fc-imgs">${n.images.map(u => `<img src="${u}" loading="lazy" data-img="${u}">`).join('')}</div>` : '';
  const files = n.attachments.length ? `<div class="fc-files">${n.attachments.map((a, i) =>
    `<button class="fc-file" data-file="${n.id}" data-fi="${i}" data-ext="${esc(a.ext)}" data-fview="${a.viewable ? 1 : 0}" data-fname="${esc(a.name)}">${IC.clip}${esc(a.name)}</button>`).join('')}</div>` : '';
  const tags = n.tags.length ? `<div class="fc-tags">${n.tags.map(t => `<span class="fc-tag"># ${esc(t)}</span>`).join('')}</div>` : '';
  return `<div class="feed-card" data-id="${n.id}">
    <div class="fc-time">更新于 ${fmtTime(n.updated_at)}
      <span class="fc-acts"><button class="fc-edit" data-edit="${n.id}" title="编辑">${IC.edit}</button><button class="fc-del" data-del="${n.id}" title="删除">${IC.del}</button></span>
    </div>
    ${n.content ? `<div class="fc-text">${esc(n.content)}</div>` : ''}
    ${todos}${imgs}${files}${tags}
  </div>`;
}
$('#feed').addEventListener('click', async e => {
  const box = $('#feed');
  const tg = e.target.closest('[data-tg]');
  if (tg) {
    try {
      await api('/api/notes/' + tg.dataset.tg + '/todo', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ idx: +tg.dataset.ti, done: tg.checked }) });
      tg.closest('.fc-todo').classList.toggle('done', tg.checked);
      const it = (box._items || []).find(x => x.id == tg.dataset.tg); if (it) it.todos[+tg.dataset.ti].done = tg.checked;
    } catch (err) { tg.checked = !tg.checked; toast(err.message, true); }
    return;
  }
  const ed = e.target.closest('[data-edit]');
  if (ed) { const it = (box._items || []).find(x => x.id == ed.dataset.edit); if (it) loadDraft(it); return; }
  const dl = e.target.closest('[data-del]');
  if (dl) {
    if (!(await appConfirm('删除这条小记？'))) return;
    try { await api('/api/notes/' + dl.dataset.del, { method: 'DELETE' }); toast('已删除'); if (draft.id == dl.dataset.del) newDraft(); loadFeed(); loadFeedTags(); refreshNoteCounts(); }
    catch (err) { toast(err.message, true); } return;
  }
  const fl = e.target.closest('[data-file]');
  if (fl) {
    const base = '/api/notes/' + fl.dataset.file + '/file/' + fl.dataset.fi;
    if (fl.dataset.fview !== '1') { const a = document.createElement('a'); a.href = base + '?dl=1'; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); return; }
    const fe = (fl.dataset.ext || '').toLowerCase();
    const ftu = (fe === '.pdf' || OFFICE_EXT.includes(fe)) ? base + '/text' : null;
    openViewerUrl(base, fl.dataset.fname, fl.dataset.ext, base + '?dl=1', ftu); return;
  }
  const im = e.target.closest('[data-img]');
  if (im) { lightbox(im.dataset.img, '图片.png'); return; }   // 和草稿里的图走同一条路，大小一致
});
/* 双击小记卡片即可编辑（除点到按钮/图片/附件/勾选） */
$('#feed').addEventListener('dblclick', e => {
  if (e.target.closest('button,a,input,[data-img],[data-file]')) return;
  const card = e.target.closest('.feed-card'); if (!card) return;
  const it = ($('#feed')._items || []).find(x => x.id == card.dataset.id);
  if (it) loadDraft(it);
});

/* ---- 图片：拖进来 / 粘贴进来（小记编辑器 和 随手记浮层 都支持）----
   原来只能点按钮选文件。资料库早就支持拖拽了，AI 早就支持 Ctrl+V 了 —— 小记没道理不支持。 */
function bindImgDrop(el, add) {
  el.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('drop-on'); });
  el.addEventListener('dragleave', e => {
    if (!el.contains(e.relatedTarget)) el.classList.remove('drop-on');
  });
  el.addEventListener('drop', e => {
    e.preventDefault(); el.classList.remove('drop-on');
    const fs = [...(e.dataTransfer.files || [])].filter(f => /^image\//.test(f.type));
    if (fs.length) add(fs);
    else if (e.dataTransfer.files && e.dataTransfer.files.length) toast('只能拖图片进来', true);
  });
}
function bindImgPaste(el, add) {
  el.addEventListener('paste', e => {
    const items = [...((e.clipboardData || {}).items || [])];
    const fs = items.filter(i => i.type && i.type.startsWith('image/'))
      .map(i => i.getAsFile()).filter(Boolean);
    if (!fs.length) return;                 // 粘的是文字 → 放行，让它正常粘进去
    e.preventDefault();
    add(fs);
  });
}
// 桌面壳（WebKit）里 dataTransfer.files 是空的，图片由壳转成 dataURL 回调过来
window.__onNotePasteImage = null;

/* ---- 通用浮窗：标题栏拖动移位、右下角拖动改大小、位置和尺寸都记住 ----
   （createDock 那套是给「半屏停靠面板」用的；随手记是个小窗，要的是自由摆放，两回事。） */
function makeFloat(el, key, handle) {
  const K = 'flt-' + key;
  const clamp = () => {                       // 换了屏幕/缩了窗口，别把浮窗甩到看不见的地方
    const r = el.getBoundingClientRect();
    const x = Math.min(Math.max(8, r.left), Math.max(8, innerWidth - r.width - 8));
    const y = Math.min(Math.max(8, r.top), Math.max(8, innerHeight - r.height - 8));
    el.style.left = x + 'px'; el.style.top = y + 'px';
    el.style.right = 'auto'; el.style.bottom = 'auto';
  };
  const save = () => {
    const r = el.getBoundingClientRect();
    try { localStorage.setItem(K, JSON.stringify({ x: r.left, y: r.top, w: r.width, h: r.height })); }
    catch (_) {}
  };
  el.restore = () => {                        // 打开时调：恢复上次的位置和大小
    let v = null;
    try { v = JSON.parse(localStorage.getItem(K) || 'null'); } catch (_) {}
    if (!v) return;                           // 没拖过 → 用 CSS 里的默认位置和大小
    el.style.width = Math.max(280, v.w) + 'px';
    el.style.height = Math.max(220, v.h) + 'px';
    el.style.left = v.x + 'px'; el.style.top = v.y + 'px';
    el.style.right = 'auto'; el.style.bottom = 'auto';
    clamp();
  };

  // 拖标题栏 = 移动
  let dx = 0, dy = 0, moving = false;
  (handle || el).addEventListener('pointerdown', e => {
    if (e.target.closest('button, select, input, textarea, a')) return;   // 别抢控件的事件
    const r = el.getBoundingClientRect();
    dx = e.clientX - r.left; dy = e.clientY - r.top;
    moving = true;
    el.style.right = 'auto'; el.style.bottom = 'auto';
    (handle || el).setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  (handle || el).addEventListener('pointermove', e => {
    if (!moving) return;
    el.style.left = (e.clientX - dx) + 'px';
    el.style.top = (e.clientY - dy) + 'px';
  });
  (handle || el).addEventListener('pointerup', e => {
    if (!moving) return;
    moving = false;
    try { (handle || el).releasePointerCapture(e.pointerId); } catch (_) {}
    clamp(); save();
  });

  // 右下角小三角 = 改大小
  const grip = document.createElement('div');
  grip.className = 'flt-grip';
  el.appendChild(grip);
  let rw = 0, rh = 0, rx = 0, ry = 0, sizing = false;
  grip.addEventListener('pointerdown', e => {
    const r = el.getBoundingClientRect();
    rw = r.width; rh = r.height; rx = e.clientX; ry = e.clientY;
    sizing = true;
    grip.setPointerCapture(e.pointerId);
    e.preventDefault(); e.stopPropagation();
  });
  grip.addEventListener('pointermove', e => {
    if (!sizing) return;
    el.style.width = Math.max(300, Math.min(innerWidth - 24, rw + e.clientX - rx)) + 'px';
    el.style.height = Math.max(240, Math.min(innerHeight - 24, rh + e.clientY - ry)) + 'px';
  });
  grip.addEventListener('pointerup', e => {
    if (!sizing) return;
    sizing = false;
    try { grip.releasePointerCapture(e.pointerId); } catch (_) {}
    clamp(); save();
  });
  addEventListener('resize', clamp);
  return el;
}

/* ---- 随手记（悬浮球里的小记）----
   小记本来只有「进那个模块」一条路。但真正要记的时候，人都在看别的东西
   （做题、看时政、读范文）—— 跳走一趟回来，思路就断了。
   所以做成**浮在当前页面上**的一小块：写完点「记下」，页面纹丝不动。
   原来的小记模块**照样保留**（要整理、要翻历史还是得进去）。 */
let qnImgs = [];
let qnFloat = null;
function qnOpen() {
  const box = $('#qnote');
  if (!box.classList.contains('hidden')) { qnClose(); return; }
  if (!qnFloat) qnFloat = makeFloat(box, 'qnote', $('#qnote .qn-head'));   // 可拖、可缩放
  box.restore();
  $('#qn-board').innerHTML = boardOptions(curNoteBoard, false);
  $('#qn-text').value = ''; $('#qn-tags').value = '';
  qnImgs = []; $('#qn-imgs').innerHTML = '';
  box.classList.remove('hidden');
  setTimeout(() => $('#qn-text').focus(), 30);
  if (window.fabClose) fabClose();
}
function qnClose() { $('#qnote').classList.add('hidden'); }
$('#qn-close').onclick = qnClose;
$('#qn-more').onclick = () => { qnClose(); openNotes(); };
async function qnAddImgs(files) {
  for (const f of [...files]) {
    if (!/^image\//.test(f.type)) continue;
    const im = { url: URL.createObjectURL(f), fileObj: f, name: f.name || 'img.jpg' };
    qnImgs.push(im);
    im.ready = compressImage(f).then(b => { im.fileObj = b; });   // 和小记一样：选图就压
  }
  qnRenderImgs();
}
$('#qn-file').addEventListener('change', async e => {
  const fs = [...e.target.files]; e.target.value = '';
  await qnAddImgs(fs);
});
bindImgDrop($('#qnote'), qnAddImgs);          // 拖图片进随手记
bindImgPaste($('#qn-text'), qnAddImgs);       // Ctrl+V 粘图片
function qnRenderImgs() {
  $('#qn-imgs').innerHTML = qnImgs.map((im, i) =>
    `<div class="cp-thumb"><img src="${im.url}" data-qnbig="${i}"><button class="cp-x" data-qnr="${i}">×</button></div>`).join('');
}
$('#qn-imgs').addEventListener('click', e => {
  const r = e.target.closest('[data-qnr]');
  if (r) { qnImgs.splice(+r.dataset.qnr, 1); qnRenderImgs(); return; }
  const b = e.target.closest('[data-qnbig]');
  if (b) lightbox(qnImgs[+b.dataset.qnbig].url);
});
$('#qn-save').onclick = async () => {
  const text = $('#qn-text').value.trim();
  if (!text && !qnImgs.length) { toast('写点什么吧', true); return; }
  const b = $('#qn-save'); b.disabled = true; b.textContent = '记下…';
  try {
    await Promise.all(qnImgs.filter(i => i.ready).map(i => i.ready));
    const fd = new FormData();
    fd.append('board', $('#qn-board').value);
    fd.append('content', text);
    fd.append('todos', '[]');
    fd.append('tags', JSON.stringify(
      $('#qn-tags').value.split(/[,，\s]+/).map(x => x.trim()).filter(Boolean)));
    qnImgs.forEach(i => fd.append('images', i.fileObj, i.name));
    await api('/api/notes', { method: 'POST', body: fd });
    qnClose();
    toast('已记下');
    if ((stack[stack.length - 1] || {}).view === 'notes') { loadFeed(); refreshNoteCounts(); }
  } catch (e) { toast(e.message, true); }
  b.disabled = false; b.textContent = '记下';
};

/* ================= 资料库 ================= */
const EXT_ICON = {
  pdf: '📕', doc: '📘', docx: '📘', xls: '📗', xlsx: '📗', ppt: '📙', pptx: '📙',
  png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', webp: '🖼️', svg: '🖼️', bmp: '🖼️',
  html: '🌐', htm: '🌐', txt: '📄', md: '📄', csv: '📊', zip: '🗜️',
};
const iconFor = (ext) => EXT_ICON[(ext || '').replace('.', '')] || '📎';
const OFFICE_EXT = ['.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp', '.rtf'];
let matBoard = '', matCustomBoards = [];
async function renderMatFilter() {
  try {
    const d = await api('/api/materials/boards');
    (d.boards || []).forEach(b => { if (b && !ALL_BOARDS.includes(b) && !matCustomBoards.includes(b)) matCustomBoards.push(b); });
  } catch (_) {}
  const all = ALL_BOARDS.concat(matCustomBoards);
  $('#mat-filter').innerHTML = `<button class="chip ${matBoard === '' ? 'active' : ''}" data-mb="">全部</button>` +
    all.map(b => `<button class="chip ${b === matBoard ? 'active' : ''}" data-mb="${esc(b)}">${esc(b)}</button>`).join('') +
    `<button class="chip chip-newcat" id="mat-newcat">＋ 分类</button>`;
}
async function saveMatBoards() {
  try {
    await api('/api/materials/boards', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ boards: matCustomBoards }),
    });
  } catch (_) {}
}
/* 长按/右键自定义分类 → 删掉它（里面的资料会回到「全部」，不会丢） */
$('#mat-filter').addEventListener('contextmenu', async e => {
  const c = e.target.closest('[data-mb]');
  if (!c || !c.dataset.mb || !matCustomBoards.includes(c.dataset.mb)) return;
  e.preventDefault();
  const b = c.dataset.mb;
  if (!await appConfirm('删除分类「' + b + '」？里面的资料不会删，只是回到「全部」。',
    { title: '资料分类', okText: '删除分类' })) return;
  matCustomBoards = matCustomBoards.filter(x => x !== b);
  await saveMatBoards();
  if (matBoard === b) matBoard = '';
  renderMatFilter(); loadMaterials();
  toast('分类已删除');
});

function openMaterials() {
  matBoard = '';
  renderMatFilter();
  push({ view: 'materials' });
  loadMaterials();
}
$('#mat-filter').addEventListener('click', async e => {
  if (e.target.closest('#mat-newcat')) {
    const name = await appPrompt('新建分类', '分类名，如：晨读');
    const v = (name || '').trim().slice(0, 20);
    if (!v) return;
    if (!matCustomBoards.includes(v) && !ALL_BOARDS.includes(v)) matCustomBoards.push(v);
    await saveMatBoards();            // 存到服务器：不然新建了但还没传东西的分类，重启就没了
    matBoard = v;                     // 选中新分类：之后上传/拍照默认归入它
    renderMatFilter(); loadMaterials();
    toast('分类「' + v + '」已保存，现在上传的资料会归入它');
    return;
  }
  const c = e.target.closest('[data-mb]'); if (!c) return;
  matBoard = c.dataset.mb;
  document.querySelectorAll('#mat-filter .chip').forEach(x => x.classList.toggle('active', x.dataset.mb === matBoard));
  loadMaterials();
});
async function loadMaterials() {
  try {
    const d = await api('/api/materials' + (matBoard ? '?board=' + encodeURIComponent(matBoard) : ''));
    let newCat = false;
    (d.items || []).forEach(m => { const b = m.board; if (b && !ALL_BOARDS.includes(b) && !matCustomBoards.includes(b)) { matCustomBoards.push(b); newCat = true; } });
    if (newCat) renderMatFilter();
    const box = $('#mat-list');
    if (!d.items.length) { box.innerHTML = ''; $('#mat-empty').classList.remove('hidden'); return; }
    $('#mat-empty').classList.add('hidden');
    box.innerHTML = d.items.map(m => `
      <div class="mat-item" data-id="${m.id}" data-view="${m.viewable ? 1 : 0}" data-ext="${esc(m.ext || '')}">
        <span class="mat-icon">${iconFor(m.ext)}</span>
        <div class="mat-info">
          <div class="mat-name">${esc(m.title || m.orig_name)}</div>
          <div class="mat-meta">${esc((m.ext || '').replace('.', '').toUpperCase())} · ${fmtSize(m.size)}${m.board ? ' · ' + esc(m.board) : ''}${m.shared ? ` · <span class="mat-shared">👥 ${esc(m.shared_from)} 共享</span>` : ''}</div>
        </div>
        <div class="mat-actions">
          <button class="iconbtn mat-more" data-act="menu" title="更多操作">⋮</button>
        </div>
      </div>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#mat-list').addEventListener('click', async e => {
  const item = e.target.closest('.mat-item'); if (!item) return;
  const id = item.dataset.id;
  const act = e.target.closest('[data-act]');
  if (act && act.dataset.act === 'menu') {
    e.stopPropagation();
    openMatMenu(id, item.querySelector('.mat-name').textContent, item.dataset.ext);
    return;
  }
  if (act) {
    e.stopPropagation();
    if (act.dataset.act === 'dl') {
      const a = document.createElement('a'); a.href = '/api/materials/' + id + '/download'; a.download = '';
      document.body.appendChild(a); a.click(); a.remove();
    } else if (act.dataset.act === 'rename') {
      const cur = item.querySelector('.mat-name').textContent;
      const v = await kbPrompt('重命名文档', cur);
      if (v && v !== cur) {
        try { await api('/api/materials/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: v }) }); toast('已重命名'); loadMaterials(); }
        catch (err) { toast(err.message, true); }
      }
    } else if (act.dataset.act === 'dup') {
      try { await api('/api/materials/' + id + '/duplicate', { method: 'POST' }); toast('已复制一份'); loadMaterials(); }
      catch (err) { toast(err.message, true); }
    } else if (act.dataset.act === 'del') {
      if (!(await appConfirm('删除这个资料？'))) return;
      try { await api('/api/materials/' + id, { method: 'DELETE' }); toast('已删除'); loadMaterials(); }
      catch (err) { toast(err.message, true); }
    }
    return;
  }
  if (item.dataset.view !== '1') { toast('该格式不支持预览，请下载查看', true); return; }
  openViewer(id, item.querySelector('.mat-name').textContent, item.dataset.ext);
});
const READER_EXT = ['.md', '.markdown', '.txt'];
let viewerTextUrl = null;
function openViewerUrl(fileUrl, name, ext, dlUrl, textUrl) {
  ext = (ext || '').toLowerCase();
  setViewerFull(false);
  $('#viewer-name').textContent = name;
  $('#viewer-dl').href = dlUrl || fileUrl;
  viewerTextUrl = textUrl || null;
  push({ view: 'viewer', title: name });
  if (READER_EXT.includes(ext)) { $('#viewer-mode').classList.add('hidden'); openReader(fileUrl, ext); return; }
  // 原版预览（pdf.js / iframe）
  $('#viewer-reader').classList.add('hidden');
  $('#reader-tools').classList.add('hidden');
  $('#viewer-frame').classList.remove('hidden');
  $('#viewer-frame').src = (ext === '.pdf' || OFFICE_EXT.includes(ext))
    ? '/pdfjs/web/viewer.html?file=' + encodeURIComponent(fileUrl) : fileUrl;
  // pdf/office 且有文本接口 → 提供「阅读模式」切换
  const canRead = (ext === '.pdf' || OFFICE_EXT.includes(ext)) && viewerTextUrl;
  $('#viewer-mode').classList.toggle('hidden', !canRead);
  $('#viewer-mode').textContent = '阅读模式';
  probeSlides(fileUrl);
}

/* ================= 幻灯片播放（逐页出图） =================
   整份 PDF 十几 MB，家里上行只有一百多 KB/s，打开要一分多钟；
   单页 JPEG 只有 100KB 上下，所以按需逐页拉图，翻到哪拉到哪。 */
let ssMid = 0, ssTotal = 0, ssPage = 1;
function probeSlides(fileUrl) {
  $('#viewer-play').classList.add('hidden');
  const m = /\/api\/materials\/(\d+)\/view/.exec(fileUrl || '');
  if (!m) { ssMid = 0; return; }
  const mid = +m[1];
  api('/api/materials/' + mid + '/pages').then(d => {
    if (!d.slides || !d.pages) return;
    ssMid = mid; ssTotal = d.pages;
    $('#viewer-play').textContent = d.ppt ? '▶ 播放' : '▶ 逐页看';
    $('#viewer-play').classList.remove('hidden');
  }).catch(() => {});
}
function ssUrl(n) { return '/api/materials/' + ssMid + '/page/' + n; }
function ssPrefetch(n) { if (n >= 1 && n <= ssTotal) new Image().src = ssUrl(n); }
function ssShow(n) {
  if (!ssMid || n < 1 || n > ssTotal) return;
  ssPage = n;
  $('#ss-page').textContent = n + ' / ' + ssTotal;
  $('#ss-load').classList.remove('hidden');
  const img = $('#ss-img');
  img.onload = () => { $('#ss-load').classList.add('hidden'); ssPrefetch(n + 1); ssPrefetch(n - 1); };
  img.onerror = () => { $('#ss-load').textContent = '这一页加载失败'; };
  img.src = ssUrl(n);
}
function openSlideshow() {
  if (!ssMid || !ssTotal) return;
  $('#slideshow').classList.remove('hidden');
  document.body.classList.add('ss-open');
  try { if (window.GongkaoNative && GongkaoNative.fullscreen) GongkaoNative.fullscreen(true); } catch (_) {}
  ssShow(1);
}
function closeSlideshow() {
  $('#slideshow').classList.add('hidden');
  document.body.classList.remove('ss-open');
  $('#ss-img').src = '';
  try { if (window.GongkaoNative && GongkaoNative.fullscreen) GongkaoNative.fullscreen(false); } catch (_) {}
}
$('#viewer-play').onclick = openSlideshow;
$('#ss-close').onclick = closeSlideshow;
$('#ss-prev').onclick = () => ssShow(ssPage - 1);
$('#ss-next').onclick = () => ssShow(ssPage + 1);
$('#ss-hl').onclick = () => ssShow(ssPage - 1);
$('#ss-hr').onclick = () => ssShow(ssPage + 1);
document.addEventListener('keydown', e => {
  if ($('#slideshow').classList.contains('hidden')) return;
  if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') ssShow(ssPage + 1);
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') ssShow(ssPage - 1);
  else if (e.key === 'Escape') closeSlideshow();
});
(function ssSwipe() {
  let x0 = 0, y0 = 0;
  const el = $('#slideshow');
  el.addEventListener('touchstart', e => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
  el.addEventListener('touchend', e => {
    const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
    if (Math.abs(dx) > 55 && Math.abs(dx) > Math.abs(dy)) ssShow(ssPage + (dx < 0 ? 1 : -1));
    else if (dy > 90 && Math.abs(dy) > Math.abs(dx)) closeSlideshow();   // 下滑退出
  }, { passive: true });
})();
let _viewerFull = false;
function setViewerFull(on) {
  _viewerFull = on;
  document.body.classList.toggle('viewer-full', on);
  $('#viewer-full').textContent = on ? '⛶ 退出全屏' : '⛶ 全屏';
  // 让原生壳一起隐藏状态栏/导航栏（沉浸式），否则「全屏」只全屏了网页那一半
  try {
    if (window.GongkaoNative && typeof GongkaoNative.fullscreen === 'function') GongkaoNative.fullscreen(on);
  } catch (_) {}
}
$('#viewer-full').onclick = () => setViewerFull(!_viewerFull);
$('#viewer-exit').onclick = () => setViewerFull(false);
$('#viewer-mode').onclick = async () => {
  const reading = !$('#viewer-reader').classList.contains('hidden');
  if (reading) {
    $('#viewer-reader').classList.add('hidden');
    $('#reader-tools').classList.add('hidden');
    $('#viewer-frame').classList.remove('hidden');
    $('#viewer-mode').textContent = '阅读模式';
    return;
  }
  $('#viewer-frame').classList.add('hidden');
  $('#viewer-reader').classList.remove('hidden');
  $('#reader-tools').classList.remove('hidden');
  $('#viewer-mode').textContent = '原版';
  $('#viewer-reader').innerHTML = '<p class="reader-tip">提取文字中…</p>';
  applyReaderStyle();
  try {
    const d = await api(viewerTextUrl);
    const txt = (d && typeof d.text === 'string') ? d.text : '';
    $('#viewer-reader').innerHTML = txt.trim()
      ? '<pre class="reader-pre">' + esc(txt) + '</pre>'
      : '<p class="reader-tip">没提取到文字（可能是扫描/图片型 PDF，可用小记的 OCR 识图）</p>';
    $('#viewer-reader').scrollTop = 0;
  } catch (e) { $('#viewer-reader').innerHTML = '<p class="reader-tip">提取失败：' + esc(e.message) + '</p>'; }
};
/* ---- 阅读模式（md 渲染 / txt） ---- */
let readerFont = 17, readerSepia = false, readerSerif = false;
function applyReaderStyle() {
  const r = $('#viewer-reader');
  r.style.fontSize = readerFont + 'px';
  r.classList.toggle('sepia', readerSepia);
  r.classList.toggle('serif', readerSerif);
}
async function openReader(fileUrl, ext) {
  $('#viewer-frame').classList.add('hidden'); $('#viewer-frame').src = 'about:blank';
  $('#viewer-reader').classList.remove('hidden');
  $('#reader-tools').classList.remove('hidden');
  $('#viewer-reader').innerHTML = '<p class="reader-tip">加载中…</p>';
  applyReaderStyle();
  try {
    const r = await fetch(fileUrl);
    const txt = await r.text();
    $('#viewer-reader').innerHTML = (ext === '.txt')
      ? '<pre class="reader-pre">' + esc(txt) + '</pre>' : mdToHtml(txt);
    $('#viewer-reader').scrollTop = 0;
  } catch (e) { $('#viewer-reader').innerHTML = '<p class="reader-tip">加载失败，请下载查看</p>'; }
}
$('#rd-fontplus').onclick = () => { readerFont = Math.min(28, readerFont + 1); applyReaderStyle(); };
$('#rd-fontminus').onclick = () => { readerFont = Math.max(13, readerFont - 1); applyReaderStyle(); };
$('#rd-theme').onclick = () => { readerSepia = !readerSepia; applyReaderStyle(); };
$('#rd-serif').onclick = () => { readerSerif = !readerSerif; $('#rd-serif').textContent = readerSerif ? '黑体' : '宋体'; applyReaderStyle(); };
$('#rd-copy').onclick = async () => {
  const text = $('#viewer-reader').innerText || '';
  if (!text) { toast('没有可复制的内容', true); return; }
  try { await navigator.clipboard.writeText(text); toast('已复制全文'); return; } catch (_) { }
  const ta = document.createElement('textarea'); ta.value = text;
  ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); toast('已复制全文'); } catch (e) { toast('复制失败，请长按选择', true); }
  ta.remove();
};

/* 轻量 Markdown → HTML（标题/加粗/斜体/代码/引用/列表/分割线/链接/表格） */
function mdToHtml(src) {
  const E = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const inline = s => {
    s = E(s);
    s = s.replace(/`([^`]+)`/g, (m, c) => '<code>' + c + '</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/__([^_]+)__/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return s;
  };
  const lines = src.replace(/\r\n/g, '\n').split('\n');
  let html = '', inCode = false, codeBuf = [], listType = null, para = [], i = 0;
  const flushPara = () => { if (para.length) { html += '<p>' + inline(para.join(' ')) + '</p>'; para = []; } };
  const closeList = () => { if (listType) { html += '</' + listType + '>'; listType = null; } };
  for (i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = line.match(/^```(.*)$/);
    if (fence) {
      if (inCode) { html += '<pre class="md-code"><code>' + E(codeBuf.join('\n')) + '</code></pre>'; inCode = false; codeBuf = []; }
      else { flushPara(); closeList(); inCode = true; }
      continue;
    }
    if (inCode) { codeBuf.push(line); continue; }
    // 表格：| a | b | 后跟 |---|---|
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      flushPara(); closeList();
      const cells = r => r.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(c => c.trim());
      html += '<table class="md-table"><thead><tr>' + cells(line).map(c => '<th>' + inline(c) + '</th>').join('') + '</tr></thead><tbody>';
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        html += '<tr>' + cells(lines[i]).map(c => '<td>' + inline(c) + '</td>').join('') + '</tr>'; i++;
      }
      i--; html += '</tbody></table>';
      continue;
    }
    if (/^\s*$/.test(line)) { flushPara(); closeList(); continue; }
    let m;
    if (m = line.match(/^(#{1,6})\s+(.*)$/)) { flushPara(); closeList(); const lv = m[1].length; html += '<h' + lv + '>' + inline(m[2]) + '</h' + lv + '>'; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flushPara(); closeList(); html += '<hr>'; continue; }
    if (m = line.match(/^\s*>\s?(.*)$/)) { flushPara(); closeList(); html += '<blockquote>' + inline(m[1]) + '</blockquote>'; continue; }
    if (m = line.match(/^\s*[-*+]\s+(.*)$/)) { flushPara(); if (listType !== 'ul') { closeList(); html += '<ul>'; listType = 'ul'; } html += '<li>' + inline(m[1]) + '</li>'; continue; }
    if (m = line.match(/^\s*\d+[.)]\s+(.*)$/)) { flushPara(); if (listType !== 'ol') { closeList(); html += '<ol>'; listType = 'ol'; } html += '<li>' + inline(m[1]) + '</li>'; continue; }
    para.push(line.trim());
  }
  flushPara(); closeList();
  if (inCode) html += '<pre class="md-code"><code>' + E(codeBuf.join('\n')) + '</code></pre>';
  return html;
}
function openViewer(id, name, ext) {
  const e = (ext || '').toLowerCase();
  const textUrl = (e === '.pdf' || OFFICE_EXT.includes(e)) ? '/api/materials/' + id + '/text' : null;
  openViewerUrl('/api/materials/' + id + '/view', name, ext, '/api/materials/' + id + '/download', textUrl);
}
/* 上传资料 */
$('#upload-btn').onclick = () => {
  $('#up-board').innerHTML = `<option value="">未分类</option>`
    + ALL_BOARDS.concat(matCustomBoards).map(b => `<option ${b === matBoard ? 'selected' : ''}>${esc(b)}</option>`).join('')
    + `<option value="__new__">＋ 新建分类…</option>`;
  $('#up-title').value = ''; $('#up-file').value = '';
  $('#upload-modal').classList.remove('hidden');
};
$('#up-cancel').onclick = () => $('#upload-modal').classList.add('hidden');
$('#upload-modal').addEventListener('click', e => { if (e.target.id === 'upload-modal') $('#upload-modal').classList.add('hidden'); });
/* 带进度 + 断网重试的上传：服务器在家里，上行只有一百多 KB/s，
   fetch 没有进度事件、一断就整个失败，所以这里用 XHR。 */
function uploadXhr(fd, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/materials');
    xhr.timeout = 15 * 60 * 1000;              // 大文件慢，给足时间
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve(JSON.parse(xhr.responseText || '{}'));
      let msg = '上传失败（' + xhr.status + '）';
      try { msg = JSON.parse(xhr.responseText).error || msg; } catch (_) {}
      reject(new Error(msg));
    };
    xhr.onerror = () => reject(new Error('网络中断'));
    xhr.ontimeout = () => reject(new Error('上传超时'));
    xhr.send(fd);
  });
}
function upProg(show, pct, txt) {
  $('#up-prog').classList.toggle('hidden', !show);
  if (!show) return;
  $('#up-prog').querySelector('i').style.width = Math.round(pct * 100) + '%';
  $('#up-prog').querySelector('.up-txt').textContent = txt;
}
$('#up-go').onclick = async () => {
  const files = [...$('#up-file').files];
  if (!files.length) { toast('请选择文件', true); return; }
  const board = $('#up-board').value, title = $('#up-title').value.trim();
  $('#up-go').disabled = true; $('#up-go').textContent = '上传中…';
  $('#up-cancel').disabled = true;
  let ok = 0;
  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    const label = files.length > 1 ? `(${i + 1}/${files.length}) ${file.name}` : file.name;
    let done = false;
    for (let attempt = 1; attempt <= 3 && !done; attempt++) {   // 网络抖动自动重试
      const fd = new FormData();
      fd.append('file', file);
      fd.append('board', board);
      fd.append('section', '');
      fd.append('title', files.length === 1 ? title : '');       // 多个文件各用文件名
      try {
        await uploadXhr(fd, p => upProg(true, p,
          `${label} ${Math.round(p * 100)}%${attempt > 1 ? ' · 第' + attempt + '次尝试' : ''}`));
        ok++; done = true;
      } catch (e) {
        if (attempt === 3) { toast(file.name + '：' + e.message, true); }
        else { upProg(true, 0, label + ' 重试中…'); await new Promise(r => setTimeout(r, 1500)); }
      }
    }
  }
  upProg(false);
  $('#up-go').disabled = false; $('#up-go').textContent = '上传';
  $('#up-cancel').disabled = false;
  if (ok) { toast('上传成功 ' + ok + ' 个'); $('#upload-modal').classList.add('hidden'); loadMaterials(); }
};
/* 资料库拍照直接上传 */
$('#mat-camfile').addEventListener('change', async e => {
  const file = e.target.files[0]; e.target.value = '';
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  fd.append('board', matBoard);
  fd.append('section', '');
  fd.append('title', '拍照 ' + new Date().toLocaleString('zh-CN', { hour12: false }).slice(5, 16));
  toast('上传中…');
  try { await api('/api/materials', { method: 'POST', body: fd }); toast('已上传'); loadMaterials(); }
  catch (err) { toast(err.message, true); }
});

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
      ${sub.join('')}${it.note ? `<div class="item-note">📝 ${esc(it.note)}</div>` : ''}
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

/* ================= 知识库（笔记本 + 文档块编辑器） ================= */
const ICON_CHEVRON = _svg('<polyline points="9 18 15 12 9 6"/>');
const ICON_FOLDER = _svg('<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>');
const ICON_DOCF = _svg('<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="14 3 14 9 20 9"/>');
const ICON_DOTS = _svg('<circle cx="12" cy="5" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="12" cy="19" r="1.4"/>');
const ICON_PLUS = _svg('<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>');
const ICON_TEXT = _svg('<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/>');
const ICON_LIST = _svg('<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/>');
const ICON_CHECKBOX = _svg('<path d="M9 11l2.5 2.5L16 8"/><rect x="3" y="3" width="18" height="18" rx="2.5"/>');
const ICON_QUOTE2 = _svg('<path d="M4 6h5v7H4z"/><path d="M15 6h5v7h-5z"/>');
const ICON_BULB = _svg('<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.7 10.7c.5.5.7 1 .7 1.8h6c0-.8.2-1.3.7-1.8A6 6 0 0 0 12 3z"/>');
const ICON_CODE = _svg('<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>');
const ICON_CHK = _svg('<polyline points="20 6 9 17 4 12"/>');
const KB_COVERS = [
  'linear-gradient(160deg,#3f73b3,#2b5894)', 'linear-gradient(160deg,#d3892f,#a9651b)',
  'linear-gradient(160deg,#c0473a,#982c22)', 'linear-gradient(160deg,#2f8060,#21614a)',
  'linear-gradient(160deg,#7a5ea8,#5b4589)', 'linear-gradient(160deg,#2c8c8c,#1f6e6e)',
  'linear-gradient(160deg,#b08a1e,#876900)', 'linear-gradient(160deg,#46566a,#2f3b48)',
];
const kbCoverInner = () => '<span class="kbc-band"></span><span class="kbc-ribbon"></span>';
const KB = { notebooks: [], nb: null, tree: [], openGroups: {} };
let DOC = null;

/* ---- 知识库列表 ---- */
async function openKb() { push({ view: 'kb' }); await loadNotebooks(); }
async function loadNotebooks() {
  try {
    const d = await api('/api/kb/notebooks');
    KB.notebooks = d.items;
    const box = $('#kb-list');
    if (!d.items.length) { box.innerHTML = ''; $('#kb-empty').classList.remove('hidden'); return; }
    $('#kb-empty').classList.add('hidden');
    box.innerHTML = d.items.map(nb => `
      <div class="kb-card" data-nb="${nb.id}">
        <div class="kb-cover" style="background:${KB_COVERS[(nb.cover || 0) % 8]}">${kbCoverInner()}</div>
        <div class="kb-card-name">${esc(nb.name)}</div>
        <div class="kb-card-sub">${nb.doc_count} 篇文档</div>
      </div>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#kb-list').addEventListener('click', e => {
  const c = e.target.closest('[data-nb]'); if (!c) return;
  openNotebook(+c.dataset.nb);
});

/* ---- 新建 / 编辑 知识库 ---- */
let nbEditId = null, nbCover = 0;
$('#kb-fab').onclick = () => openNbModal(null);
function openNbModal(nb) {
  nbEditId = nb ? nb.id : null;
  nbCover = nb ? (nb.cover || 0) : 0;
  $('#nb-modal-title').textContent = nb ? '知识库设置' : '新建知识库';
  $('#nb-in-name').value = nb ? nb.name : '';
  $('#nb-in-intro').value = nb ? nb.intro : '';
  $('#nb-cover-pick').innerHTML = KB_COVERS.map((g, i) =>
    `<div class="nb-cover-opt${i === nbCover ? ' sel' : ''}" data-cv="${i}" style="background:${g}"></div>`).join('');
  $('#nb-save').textContent = nb ? '保存' : '新建';
  $('#nb-del').classList.toggle('hidden', !nb);
  $('#nb-modal').classList.remove('hidden');
  if (!nb) setTimeout(() => $('#nb-in-name').focus(), 60);
}
$('#nb-cover-pick').addEventListener('click', e => {
  const c = e.target.closest('[data-cv]'); if (!c) return;
  nbCover = +c.dataset.cv;
  document.querySelectorAll('#nb-cover-pick .nb-cover-opt').forEach(x => x.classList.toggle('sel', +x.dataset.cv === nbCover));
});
$('#nb-cancel').onclick = () => $('#nb-modal').classList.add('hidden');
$('#nb-modal').addEventListener('click', e => { if (e.target.id === 'nb-modal') $('#nb-modal').classList.add('hidden'); });
$('#nb-save').onclick = async () => {
  const name = $('#nb-in-name').value.trim();
  if (!name) { toast('请填写知识库名称', true); return; }
  const intro = $('#nb-in-intro').value.trim();
  try {
    if (nbEditId) {
      await api('/api/kb/notebooks/' + nbEditId, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, intro, cover: nbCover }) });
      toast('已保存'); $('#nb-modal').classList.add('hidden');
      if (KB.nb && KB.nb.id === nbEditId) await loadNotebook(nbEditId);
      loadNotebooks();
    } else {
      const nb = await api('/api/kb/notebooks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, intro, cover: nbCover }) });
      toast('已创建'); $('#nb-modal').classList.add('hidden');
      openNotebook(nb.id);
    }
  } catch (e) { toast(e.message, true); }
};
$('#nb-del').onclick = async () => {
  if (!nbEditId) return;
  if (!(await appConfirm('删除整个知识库「' + $('#nb-in-name').value + '」？里面所有文档和分组都会删除，不可恢复！'))) return;
  try {
    await api('/api/kb/notebooks/' + nbEditId, { method: 'DELETE' });
    toast('已删除'); $('#nb-modal').classList.add('hidden');
    if (stack[stack.length - 1].view === 'notebook') back();
    loadNotebooks();
  } catch (e) { toast(e.message, true); }
};

/* ---- 知识库详情（目录树） ---- */
async function openNotebook(id) { push({ view: 'notebook' }); await loadNotebook(id); }
async function loadNotebook(id) {
  try {
    const d = await api('/api/kb/notebooks/' + id);
    KB.nb = d.notebook; KB.tree = d.tree;
    renderNotebook();
  } catch (e) { toast(e.message, true); }
}
function renderNotebook() {
  const nb = KB.nb;
  $('#nb-cover').style.background = KB_COVERS[(nb.cover || 0) % 8];
  $('#nb-cover').innerHTML = kbCoverInner();
  $('#nb-name').textContent = nb.name;
  $('#nb-sub').textContent = (nb.intro ? nb.intro + ' · ' : '') + nb.doc_count + ' 篇文档';
  const top = stack[stack.length - 1];
  if (top && top.view === 'notebook') { top.title = nb.name; $('#top-title').textContent = nb.name; }
  renderTree();
}
function findNode(id) {
  let found = null;
  (function walk(ns) { ns.forEach(n => { if (n.id === id) found = n; if (n.children) walk(n.children); }); })(KB.tree);
  return found;
}
function renderTree() {
  const box = $('#nb-tree');
  if (!KB.tree.length) { box.innerHTML = ''; $('#nb-empty').classList.remove('hidden'); return; }
  $('#nb-empty').classList.add('hidden');
  let html = '';
  (function walk(nodes, depth) {
    nodes.forEach(n => {
      const isGroup = n.type === 'group';
      const open = !!KB.openGroups[n.id];
      html += `<div class="nb-node" data-node="${n.id}" data-type="${n.type}" style="padding-left:${6 + depth * 20}px">
        <span class="nb-twirl${isGroup ? (open ? ' open' : '') : ' leaf'}">${ICON_CHEVRON}</span>
        <span class="nb-nicon ${n.type}">${isGroup ? ICON_FOLDER : ICON_DOCF}</span>
        <span class="nb-ntitle">${esc(n.title || (isGroup ? '未命名分组' : '无标题文档'))}</span>
        <button class="nb-ndots" data-nodedots="${n.id}">${ICON_DOTS}</button>
      </div>`;
      if (isGroup && open && n.children.length) walk(n.children, depth + 1);
    });
  })(KB.tree, 0);
  box.innerHTML = html;
}
$('#nb-tree').addEventListener('click', e => {
  const dots = e.target.closest('[data-nodedots]');
  if (dots) { e.stopPropagation(); openNodeMenu(+dots.dataset.nodedots); return; }
  const row = e.target.closest('[data-node]'); if (!row) return;
  const id = +row.dataset.node;
  if (row.dataset.type === 'group') { KB.openGroups[id] = !KB.openGroups[id]; renderTree(); }
  else openDoc(id);
});

/* 底部悬浮条（知识库详情） */
$('#nb-pill').addEventListener('click', e => {
  const b = e.target.closest('[data-nbpill]'); if (!b) return;
  const p = b.dataset.nbpill;
  if (p === 'add') openKbSheet(null);
  else if (p === 'search') openSearch();
  else if (p === 'ai') openAI();
});

/* + 面板：新建 空白文档 / 知识库 / 分组 */
let kbSheetParent = null;
function openKbSheet(parentId) {
  kbSheetParent = parentId || null;
  $('#kb-sheet-title').textContent = parentId ? '在分组内新建' : '新建文档、知识库';
  $('#kb-sheet').classList.remove('hidden');
}
$('#kb-sheet').addEventListener('click', async e => {
  if (e.target.closest('[data-sheet-close]')) { $('#kb-sheet').classList.add('hidden'); return; }
  const b = e.target.closest('[data-kbnew]'); if (!b) return;
  $('#kb-sheet').classList.add('hidden');
  const t = b.dataset.kbnew;
  if (t === 'notebook') { openNbModal(null); return; }
  try {
    const node = await api('/api/kb/nodes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notebook_id: KB.nb.id, parent_id: kbSheetParent, type: t })
    });
    if (kbSheetParent) KB.openGroups[kbSheetParent] = true;
    await loadNotebook(KB.nb.id);
    if (t === 'doc') openDoc(node.id);
  } catch (e) { toast(e.message, true); }
});

/* 节点菜单：重命名 / 新建子项 / 删除 */
let nodeMenuId = null;
function openNodeMenu(id) {
  const n = findNode(id); if (!n) return;
  nodeMenuId = id;
  $('#node-menu-title').textContent = n.title || (n.type === 'group' ? '未命名分组' : '无标题文档');
  let html = `<button data-nm="rename"><span class="ci">${IC.edit}</span>重命名</button>`;
  if (n.type === 'group') html += `<button data-nm="add"><span class="ci">${ICON_PLUS}</span>在此分组内新建</button>`;
  if (n.type === 'doc') html += `<button data-nm="open"><span class="ci">${ICON_DOCF}</span>打开文档</button>`;
  html += `<button data-nm="del" style="color:#e0524d"><span class="ci">${IC.del}</span>删除</button>`;
  $('#node-menu-list').innerHTML = html;
  $('#node-menu').classList.remove('hidden');
}
$('#node-menu').addEventListener('click', async e => {
  if (e.target.closest('[data-sheet-close]')) { $('#node-menu').classList.add('hidden'); return; }
  const b = e.target.closest('[data-nm]'); if (!b) return;
  const act = b.dataset.nm, id = nodeMenuId, n = findNode(id);
  $('#node-menu').classList.add('hidden');
  if (!n) return;
  if (act === 'rename') {
    const v = await kbPrompt('重命名', n.title);
    if (v) { try { await api('/api/kb/nodes/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: v }) }); loadNotebook(KB.nb.id); } catch (e) { toast(e.message, true); } }
  } else if (act === 'add') { KB.openGroups[id] = true; openKbSheet(id); }
  else if (act === 'open') { openDoc(id); }
  else if (act === 'del') {
    if (!(await appConfirm('删除「' + (n.title || '该项') + '」' + (n.type === 'group' ? '及其下所有内容' : '') + '？不可恢复'))) return;
    try { await api('/api/kb/nodes/' + id, { method: 'DELETE' }); toast('已删除'); loadNotebook(KB.nb.id); } catch (e) { toast(e.message, true); }
  }
});

/* 输入框（替代 prompt，兼容 WebView） */
let _kbpResolve = null;
function kbPrompt(title, value) {
  return new Promise(res => {
    _kbpResolve = res;
    $('#kbp-title').textContent = title;
    $('#kbp-input').value = value || '';
    $('#kb-prompt').classList.remove('hidden');
    setTimeout(() => { $('#kbp-input').focus(); $('#kbp-input').select(); }, 50);
  });
}
function kbpClose(v) { $('#kb-prompt').classList.add('hidden'); if (_kbpResolve) { _kbpResolve(v); _kbpResolve = null; } }
$('#kbp-cancel').onclick = () => kbpClose(null);
$('#kbp-ok').onclick = () => kbpClose($('#kbp-input').value.trim());
$('#kb-prompt').addEventListener('click', e => { if (e.target.id === 'kb-prompt') kbpClose(null); });
$('#kbp-input').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') kbpClose($('#kbp-input').value.trim()); });
$('#nb-edit').onclick = () => { if (KB.nb) openNbModal(KB.nb); };

/* ============ 文档块编辑器 ============ */
const STATUS_OPTS = [
  { v: 'todo', label: '未开始', c: '#8a93a3', bg: '#eef0f3' },
  { v: 'doing', label: '进行中', c: '#1a6fb5', bg: '#e7f0fb' },
  { v: 'done', label: '已完成', c: '#1f9d57', bg: '#e4f6ec' },
  { v: 'hold', label: '搁置', c: '#d98324', bg: '#fdf0e1' },
];
const CONVERT_TYPES = [
  { t: 'text', label: '文本', icon: ICON_TEXT }, { t: 'h1', label: '标题 1', icon: 'H1' },
  { t: 'h2', label: '标题 2', icon: 'H2' }, { t: 'h3', label: '标题 3', icon: 'H3' },
  { t: 'list', label: '列表', icon: ICON_LIST }, { t: 'todo', label: '待办', icon: ICON_CHECKBOX },
  { t: 'quote', label: '引用', icon: ICON_QUOTE2 }, { t: 'callout', label: '高亮块', icon: ICON_BULB },
  { t: 'code', label: '代码块', icon: ICON_CODE },
];
const bid = () => 'b' + Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-3);
const newBlock = (type, data) => ({ id: bid(), type: type || 'text', text: '', data: data || {} });
function stripHtml(h) { const d = document.createElement('div'); d.innerHTML = h || ''; return (d.textContent || '').trim(); }
function normalizeBlocks(arr) {
  return (Array.isArray(arr) ? arr : []).map(b => ({ id: b.id || bid(), type: b.type || 'text', text: b.text || '', data: b.data || {} }));
}
function curB() { return DOC && DOC.blocks.find(x => x.id === DOC.curBlock); }

async function openDoc(id) {
  try {
    const d = await api('/api/kb/nodes/' + id);
    let blocks = normalizeBlocks(d.content);
    if (!blocks.length) blocks = [newBlock('text')];
    DOC = { id, blocks, curBlock: blocks[0].id, history: [], hist_i: -1 };
    push({ view: 'doc', title: d.title || '无标题文档' });
    $('#doc-title').textContent = (d.title && d.title !== '无标题文档') ? d.title : '';
    renderDoc();
    pushHistory();
    setTimeout(() => focusBlock(blocks[0].id), 70);
  } catch (e) { toast(e.message, true); }
}
function renderDoc() {
  $('#doc-blocks').innerHTML = DOC.blocks.map(blockHtml).join('');
}
function blockHtml(b) {
  const ind = b.data && b.data.indent ? ` style="margin-left:${b.data.indent * 22}px"` : '';
  const ce = 'contenteditable="true"';
  if (b.type === 'divider') return `<div class="blk divider" data-b="${b.id}" data-t="divider"${ind}><hr></div>`;
  if (b.type === 'image') return `<div class="blk image" data-b="${b.id}" data-t="image"${ind}>${b.data.url ? `<img src="${b.data.url}">` : ''}</div>`;
  if (b.type === 'file') {
    const d = b.data || {};
    return `<div class="blk file" data-b="${b.id}" data-t="file"${ind}>
      <div class="blk-file-card" data-fopen="${b.id}"><span class="bf-ic">${iconFor(d.ext)}</span>
      <span class="bf-name">${esc(d.name || '附件')}</span><span class="bf-meta">${d.size ? fmtSize(d.size) : ''}</span></div></div>`;
  }
  if (b.type === 'status') {
    const st = STATUS_OPTS.find(s => s.v === (b.data.value || 'todo')) || STATUS_OPTS[0];
    return `<div class="blk status" data-b="${b.id}" data-t="status"${ind}>
      <span class="blk-status-pill" data-status="${b.id}" style="color:${st.c};background:${st.bg}">${esc(st.label)}</span>
      <div class="blk-edit"></div></div>`;
  }
  if (b.type === 'table') {
    const rows = (b.data.rows && b.data.rows.length) ? b.data.rows : [['', ''], ['', '']];
    let t = `<div class="blk table" data-b="${b.id}" data-t="table"${ind}><table><tbody>`;
    rows.forEach((r, ri) => { t += '<tr>' + r.map((c, ci) => `<td contenteditable="true" data-tr="${ri}" data-tc="${ci}">${c || ''}</td>`).join('') + '</tr>'; });
    t += `</tbody></table><div class="tbl-tools"><button data-tbl="row" data-tid="${b.id}">＋行</button><button data-tbl="col" data-tid="${b.id}">＋列</button></div></div>`;
    return t;
  }
  if (b.type === 'todo') {
    return `<div class="blk todo${b.data.done ? ' done' : ''}" data-b="${b.id}" data-t="todo"${ind}>
      <span class="blk-chk${b.data.done ? ' on' : ''}" data-chk="${b.id}">${b.data.done ? ICON_CHK : ''}</span>
      <div class="blk-edit" ${ce} data-ph="待办事项">${b.text || ''}</div></div>`;
  }
  const cls = { text: 'text', h1: 'h1', h2: 'h2', h3: 'h3', quote: 'quote', callout: 'callout', code: 'code', list: 'list' }[b.type] || 'text';
  const ph = b.type === 'code' ? '输入代码…' : b.type === 'quote' ? '引用…' : b.type === 'callout' ? '高亮内容…'
    : b.type === 'list' ? '列表项…' : (/^h[123]$/.test(b.type) ? '标题' : '输入文本，或点下方 ＋ 插入');
  return `<div class="blk ${cls}" data-b="${b.id}" data-t="${b.type}"${ind}>
    <div class="blk-edit" ${ce} data-ph="${ph}">${b.text || ''}</div></div>`;
}

/* 输入同步 */
$('#doc-blocks').addEventListener('input', e => {
  if (!DOC) return;
  const td = e.target.closest('td[data-tr]');
  if (td) { const b = DOC.blocks.find(x => x.id === td.closest('[data-b]').dataset.b); if (b) { b.data.rows[+td.dataset.tr][+td.dataset.tc] = td.innerHTML; markDirty(); } return; }
  const edit = e.target.closest('.blk-edit'); if (!edit) return;
  const b = DOC.blocks.find(x => x.id === edit.closest('[data-b]').dataset.b);
  if (b) { b.text = edit.innerHTML; markDirty(); }
});
$('#doc-blocks').addEventListener('focusin', e => {
  const blk = e.target.closest('[data-b]'); if (blk && DOC) DOC.curBlock = blk.dataset.b;
});
$('#doc-blocks').addEventListener('click', e => {
  if (!DOC) return;
  const chk = e.target.closest('[data-chk]');
  if (chk) { const b = DOC.blocks.find(x => x.id === chk.dataset.chk); if (b) { b.data.done = !b.data.done; renderDoc(); markDirty(); } return; }
  const stp = e.target.closest('[data-status]');
  if (stp) { DOC.curBlock = stp.dataset.status; const b = DOC.blocks.find(x => x.id === stp.dataset.status); if (b) { const i = STATUS_OPTS.findIndex(s => s.v === (b.data.value || 'todo')); b.data.value = STATUS_OPTS[(i + 1) % STATUS_OPTS.length].v; renderDoc(); markDirty(); } return; }
  const tb = e.target.closest('[data-tbl]');
  if (tb) { const b = DOC.blocks.find(x => x.id === tb.dataset.tid); if (b) { if (tb.dataset.tbl === 'row') b.data.rows.push(b.data.rows[0].map(() => '')); else b.data.rows.forEach(r => r.push('')); renderDoc(); markDirty(); } return; }
  const fo = e.target.closest('[data-fopen]');
  if (fo) { const b = DOC.blocks.find(x => x.id === fo.dataset.fopen); if (b) openDocFile(b); return; }
  const blk = e.target.closest('[data-b]'); if (blk) DOC.curBlock = blk.dataset.b;
});
/* 回车分块 / 退格合并 */
$('#doc-blocks').addEventListener('keydown', e => {
  if (!DOC) return;
  const edit = e.target.closest('.blk-edit'); if (!edit) return;
  const blk = edit.closest('[data-b]'); const id = blk.dataset.b; const t = blk.dataset.t;
  const b = DOC.blocks.find(x => x.id === id); const idx = DOC.blocks.indexOf(b);
  if (!composing(e) && e.key === 'Enter' && !e.shiftKey && t !== 'code') {
    e.preventDefault();
    if ((b.type === 'list' || b.type === 'todo') && stripHtml(b.text) === '') { b.type = 'text'; b.data = {}; renderDoc(); focusBlock(id); markDirty(); return; }
    const nt = (b.type === 'list' || b.type === 'todo') ? b.type : 'text';
    const nb = newBlock(nt); DOC.blocks.splice(idx + 1, 0, nb); DOC.curBlock = nb.id;
    renderDoc(); focusBlock(nb.id); markDirty();
  } else if (e.key === 'Backspace' && stripHtml(edit.innerHTML) === '' && DOC.blocks.length > 1) {
    e.preventDefault();
    DOC.blocks.splice(idx, 1);
    const prev = DOC.blocks[Math.max(0, idx - 1)];
    DOC.curBlock = prev.id; renderDoc(); if (prev) focusBlock(prev.id); markDirty();
  }
});

/* 标题 */
$('#doc-title').addEventListener('input', () => {
  if (!DOC) return; const t = $('#doc-title').textContent;
  stack[stack.length - 1].title = t || '无标题文档'; markDirty();
});
$('#doc-title').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') { e.preventDefault(); if (DOC && DOC.blocks[0]) focusBlock(DOC.blocks[0].id); } });

/* 光标定位 */
function focusBlock(id) {
  const el = document.querySelector(`[data-b="${id}"] .blk-edit[contenteditable]`);
  if (el) { el.focus(); const r = document.createRange(); r.selectNodeContents(el); r.collapse(false); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
}

/* 保存 / 历史 */
let docSaveTimer, docHistTimer;
function markDirty() {
  clearTimeout(docSaveTimer); docSaveTimer = setTimeout(saveDoc, 900);
  clearTimeout(docHistTimer); docHistTimer = setTimeout(pushHistory, 700);
}
async function saveDoc() {
  if (!DOC) return;
  const title = $('#doc-title').textContent.trim() || '无标题文档';
  try { await api('/api/kb/nodes/' + DOC.id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, content: DOC.blocks }) }); } catch (e) { }
}
function pushHistory() {
  if (!DOC) return;
  const snap = JSON.stringify({ title: $('#doc-title').textContent, blocks: DOC.blocks });
  if (DOC.history[DOC.hist_i] === snap) return;
  DOC.history = DOC.history.slice(0, DOC.hist_i + 1);
  DOC.history.push(snap);
  if (DOC.history.length > 60) DOC.history.shift();
  DOC.hist_i = DOC.history.length - 1;
  updateUndo();
}
function applyHistory() {
  const s = JSON.parse(DOC.history[DOC.hist_i]);
  DOC.blocks = normalizeBlocks(s.blocks); $('#doc-title').textContent = s.title;
  if (DOC.blocks[0]) DOC.curBlock = DOC.blocks[0].id;
  renderDoc(); updateUndo();
  clearTimeout(docSaveTimer); docSaveTimer = setTimeout(saveDoc, 500);
}
function updateUndo() {
  $('#doc-undo').disabled = !DOC || DOC.hist_i <= 0;
  $('#doc-redo').disabled = !DOC || DOC.hist_i >= DOC.history.length - 1;
}
$('#doc-undo').onclick = () => { if (DOC && DOC.hist_i > 0) { DOC.hist_i--; applyHistory(); } };
$('#doc-redo').onclick = () => { if (DOC && DOC.hist_i < DOC.history.length - 1) { DOC.hist_i++; applyHistory(); } };
$('#doc-outline').onclick = () => {
  const hs = DOC ? DOC.blocks.filter(b => /^h[123]$/.test(b.type)) : [];
  toast(hs.length ? ('共 ' + hs.length + ' 个标题') : '还没有标题，用「Aa」把某行设为标题');
};
$('#doc-done').onclick = async () => { await saveDoc(); back(); if (KB.nb) loadNotebook(KB.nb.id); };

/* 底部工具条 */
$('#doc-toolbar').addEventListener('click', e => {
  const b = e.target.closest('[data-tb]'); if (!b || !DOC) return;
  const t = b.dataset.tb;
  if (t === 'insert') $('#blk-insert').classList.remove('hidden');
  else if (t === 'style') openStyleSheet();
  else if (t === 'bold') { document.execCommand('bold'); const cb = curB(); const el = document.querySelector(`[data-b="${DOC.curBlock}"] .blk-edit`); if (cb && el) { cb.text = el.innerHTML; markDirty(); } }
  else if (t === 'list') toggleBlockType('list');
  else if (t === 'todo') toggleBlockType('todo');
  else if (t === 'more') openBlkMenu();
  else if (t === 'kbd') { if (document.activeElement) document.activeElement.blur(); }
});
function toggleBlockType(type) {
  const b = curB(); if (!b) return;
  b.type = (b.type === type) ? 'text' : type;
  if (b.type === 'todo') b.data.done = b.data.done || false;
  renderDoc(); focusBlock(b.id); markDirty();
}

/* 块菜单（图四） */
function hiliteCur(on) {
  document.querySelectorAll('.blk.sel').forEach(x => x.classList.remove('sel'));
  if (on && DOC) { const el = document.querySelector(`[data-b="${DOC.curBlock}"]`); if (el) el.classList.add('sel'); }
}
function openBlkMenu() {
  if (!DOC.curBlock && DOC.blocks.length) DOC.curBlock = DOC.blocks[DOC.blocks.length - 1].id;
  hiliteCur(true);
  $('#blk-menu').classList.remove('hidden');
}
$('#blk-menu').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]')) { $('#blk-menu').classList.add('hidden'); hiliteCur(false); return; }
  const b = e.target.closest('[data-blkact]'); if (!b) return;
  $('#blk-menu').classList.add('hidden'); hiliteCur(false);
  blkAction(b.dataset.blkact);
});
function blkAction(act) {
  const b = curB(); if (!b) return; const idx = DOC.blocks.indexOf(b);
  if (act === 'convert') { openConvert(); return; }
  if (act === 'addbelow') { $('#blk-insert').classList.remove('hidden'); return; }
  if (act === 'copy') { const c = JSON.parse(JSON.stringify(b)); c.id = bid(); DOC.blocks.splice(idx + 1, 0, c); renderDoc(); markDirty(); toast('已复制到下方'); }
  else if (act === 'cut') { if (DOC.blocks.length > 1) DOC.blocks.splice(idx, 1); else DOC.blocks[0] = newBlock('text'); DOC.curBlock = DOC.blocks[Math.max(0, idx - 1)].id; renderDoc(); markDirty(); toast('已剪切'); }
  else if (act === 'indent') { b.data.indent = Math.min(4, (b.data.indent || 0) + 1); renderDoc(); markDirty(); }
  else if (act === 'outdent') { b.data.indent = Math.max(0, (b.data.indent || 0) - 1); renderDoc(); markDirty(); }
  else if (act === 'del') { if (DOC.blocks.length > 1) DOC.blocks.splice(idx, 1); else DOC.blocks[0] = newBlock('text'); DOC.curBlock = DOC.blocks[Math.max(0, idx - 1)].id; renderDoc(); markDirty(); }
}

/* 转换 / 文字样式 */
function openConvert() {
  $('#blk-conv-list').innerHTML = CONVERT_TYPES.map(c => {
    const ic = (typeof c.icon === 'string' && c.icon.length <= 2) ? `<b>${c.icon}</b>` : c.icon;
    return `<button data-conv="${c.t}"><span class="ci">${ic}</span>${c.label}</button>`;
  }).join('');
  $('#blk-convert').classList.remove('hidden');
}
$('#blk-convert').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]')) { $('#blk-convert').classList.add('hidden'); return; }
  const b = e.target.closest('[data-conv]'); if (!b) return;
  $('#blk-convert').classList.add('hidden');
  const blk = curB(); if (!blk) return;
  blk.type = b.dataset.conv; if (blk.type === 'todo') blk.data.done = blk.data.done || false;
  renderDoc(); focusBlock(blk.id); markDirty();
});
function openStyleSheet() {
  const opts = [['text', '正文'], ['h1', '标题 1'], ['h2', '标题 2'], ['h3', '标题 3']];
  $('#blk-style-list').innerHTML = opts.map(o => `<button data-style="${o[0]}">${o[1]}</button>`).join('');
  $('#blk-style').classList.remove('hidden');
}
$('#blk-style').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]')) { $('#blk-style').classList.add('hidden'); return; }
  const b = e.target.closest('[data-style]'); if (!b) return;
  $('#blk-style').classList.add('hidden');
  const blk = curB(); if (!blk) return;
  blk.type = b.dataset.style; renderDoc(); focusBlock(blk.id); markDirty();
});

/* 插入面板（图五） */
$('#blk-insert').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]')) { $('#blk-insert').classList.add('hidden'); return; }
  const b = e.target.closest('[data-ins]'); if (!b) return;
  $('#blk-insert').classList.add('hidden');
  doInsert(b.dataset.ins);
});
function insertAfterCur(blk) {
  let idx = DOC.blocks.findIndex(x => x.id === DOC.curBlock);
  if (idx < 0) idx = DOC.blocks.length - 1;
  DOC.blocks.splice(idx + 1, 0, blk); DOC.curBlock = blk.id;
  renderDoc();
  if (!['divider', 'image', 'file', 'status'].includes(blk.type)) focusBlock(blk.id);
  markDirty();
}
function doInsert(kind) {
  if (kind === 'image') { $('#doc-imgfile').click(); return; }
  if (kind === 'camera') { $('#doc-camfile').click(); return; }
  if (kind === 'file') { $('#doc-attfile').click(); return; }
  let blk;
  if (kind === 'table') blk = newBlock('table', { rows: [['', ''], ['', '']] });
  else if (kind === 'status') blk = newBlock('status', { value: 'todo' });
  else blk = newBlock(kind);   // text/callout/quote/divider/code
  insertAfterCur(blk);
}
async function uploadDocAsset(file, preferImage) {
  const fd = new FormData(); fd.append('file', file);
  toast('上传中…');
  const d = await api('/api/kb/upload', { method: 'POST', body: fd });
  const blk = (preferImage && d.is_image)
    ? newBlock('image', { stored: d.stored, url: d.url, name: d.name })
    : newBlock('file', { stored: d.stored, name: d.name, ext: d.ext, size: d.size, url: d.url, viewable: d.viewable });
  insertAfterCur(blk); toast('已插入');
}
$('#doc-imgfile').addEventListener('change', async e => { const f = e.target.files[0]; e.target.value = ''; if (f) try { await uploadDocAsset(f, true); } catch (err) { toast(err.message, true); } });
$('#doc-camfile').addEventListener('change', async e => { const f = e.target.files[0]; e.target.value = ''; if (f) try { await uploadDocAsset(f, true); } catch (err) { toast(err.message, true); } });
$('#doc-attfile').addEventListener('change', async e => { const f = e.target.files[0]; e.target.value = ''; if (f) try { await uploadDocAsset(f, false); } catch (err) { toast(err.message, true); } });
function openDocFile(b) {
  const d = b.data || {};
  if (!d.viewable) { const a = document.createElement('a'); a.href = d.url + '?dl=1'; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); return; }
  const e = (d.ext || '').toLowerCase();
  const tu = (e === '.pdf' || OFFICE_EXT.includes(e)) ? d.url + '?text=1' : null;
  openViewerUrl(d.url, d.name, d.ext, d.url + '?dl=1', tu);
}

/* ================= 古诗文速查（唐诗宋词·四书五经） ================= */
const CLS_BADGE = { '唐诗': '#c0392b', '宋词': '#7b5ea7', '元曲': '#2c8c8c', '诗经': '#2f8060', '先秦': '#b08a1e', '汉魏六朝': '#8a6d3b', '明清': '#4a6785', '论语': '#1a6fb5', '孟子': '#1a6fb5', '大学': '#b08a1e', '中庸': '#b08a1e', '孙子兵法': '#9b2c22', '资治通鉴': '#5a4b8a', '增广贤文': '#2c7a5a' };
let clsState = { cat: '', q: '', star: false, page: 1, pages: 1 };
function openClassics() {
  clsState = { cat: '', q: '', star: false, page: 1, pages: 1 };
  $('#cls-input').value = '';
  push({ view: 'classics' });
  loadClsCats(); loadClassics(); loadClsDaily();
}
async function loadClsDaily() {
  try {
    const d = await api('/api/classics/daily');
    if (!d || d.error) { $('#cls-daily').classList.add('hidden'); return; }
    $('#cls-daily').innerHTML = `
      <div class="cd-daily-tag">📖 每日一诗 · 申论 + 常识</div>
      <div class="cd-daily-title" data-clsopen="${d.id}">${esc(d.title)}<span class="cd-daily-meta">${esc((d.dynasty || '') + ' · ' + (d.author || ''))}</span></div>
      <div class="cd-daily-line">${esc(d.first_line || '')}</div>
      ${d.apply ? `<div class="cd-daily-apply"><b>申论运用</b> ${esc(d.apply)}</div>` : ''}
      ${d.common ? `<div class="cd-daily-apply cd-daily-common"><b>常识考点</b> ${esc(d.common)}</div>` : ''}`;
    $('#cls-daily').classList.remove('hidden');
  } catch (_) { $('#cls-daily').classList.add('hidden'); }
}
async function loadClsCats() {
  try {
    const d = await api('/api/classics/categories');
    const total = (d.categories || []).reduce((a, c) => a + c.count, 0);
    $('#cls-cats').innerHTML =
      `<button class="chip active" data-cc="">全部${total ? ' ' + total : ''}</button>` +
      `<button class="chip" data-cc="__star">★ 收藏${d.star_count ? ' ' + d.star_count : ''}</button>` +
      d.categories.map(c => `<button class="chip" data-cc="${esc(c.name)}">${esc(c.name)} ${c.count}</button>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#cls-daily').addEventListener('click', e => {
  const t = e.target.closest('[data-clsopen]'); if (t) openClassicDetail(+t.dataset.clsopen);
});
$('#cls-cats').addEventListener('click', e => {
  const c = e.target.closest('[data-cc]'); if (!c) return;
  const v = c.dataset.cc;
  clsState.star = (v === '__star');
  clsState.cat = clsState.star ? '' : v;
  clsState.page = 1;
  document.querySelectorAll('#cls-cats .chip').forEach(x => x.classList.toggle('active', x.dataset.cc === v));
  loadClassics();
});
let clsTimer;
$('#cls-input').addEventListener('input', e => {
  clearTimeout(clsTimer);
  clsTimer = setTimeout(() => { clsState.q = e.target.value.trim(); clsState.page = 1; loadClassics(); }, 280);
});
async function loadClassics() {
  let url = '/api/classics?page=' + clsState.page;
  if (clsState.cat) url += '&category=' + encodeURIComponent(clsState.cat);
  if (clsState.q) url += '&q=' + encodeURIComponent(clsState.q);
  if (clsState.star) url += '&star=1';
  try {
    const d = await api(url);
    clsState.pages = d.pages;
    renderClassics(d.items, d.total);
  } catch (e) { toast(e.message, true); }
}
function renderClassics(items, total) {
  const box = $('#cls-list');
  if (!items.length) {
    box.innerHTML = '';
    $('#cls-empty').classList.remove('hidden');
    $('#cls-empty').textContent = clsState.star ? '还没有收藏，点诗文右上角 ☆ 收藏'
      : (clsState.q ? '没有匹配「' + clsState.q + '」的诗文' : '暂无内容');
    $('#cls-pager').classList.add('hidden');
    return;
  }
  $('#cls-empty').classList.add('hidden');
  box.innerHTML = items.map(it => {
    const lines = (it.content || '').split('\n').map(l => `<div class="cls-line">${esc(l)}</div>`).join('');
    const meta = [it.author, it.dynasty, it.sub].filter(Boolean).join(' · ');
    return `<div class="cls-item" data-id="${it.id}">
      <div class="cls-head">
        <span class="cls-badge" style="background:${CLS_BADGE[it.category] || '#888'}">${esc(it.category)}</span>
        <span class="cls-title">${esc(it.title || '')}</span>
        <button class="cls-star ${it.starred ? 'on' : ''}" data-star="${it.id}" title="收藏">${it.starred ? '★' : '☆'}</button>
      </div>
      <div class="cls-body">${lines}</div>
      ${meta ? `<div class="cls-meta">${esc(meta)}</div>` : ''}
    </div>`;
  }).join('');
  box._items = items;
  const pager = $('#cls-pager');
  if (clsState.pages <= 1) { pager.classList.add('hidden'); }
  else {
    pager.classList.remove('hidden');
    $('#cls-info').textContent = '第 ' + clsState.page + ' / ' + clsState.pages + ' 页 · 共 ' + total + ' 条';
    $('#cls-prev').disabled = clsState.page <= 1;
    $('#cls-next').disabled = clsState.page >= clsState.pages;
  }
}
$('#cls-list').addEventListener('click', async e => {
  const s = e.target.closest('[data-star]');
  if (s) {
    const id = s.dataset.star;
    const on = !s.classList.contains('on');
    try {
      await api('/api/classics/' + id + '/star', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: on }) });
      s.classList.toggle('on', on); s.textContent = on ? '★' : '☆';
      const it = ($('#cls-list')._items || []).find(x => x.id == id); if (it) it.starred = on;
      if (clsState.star && !on) loadClassics();   // 收藏页里取消收藏即移除
    } catch (err) { toast(err.message, true); }
    return;
  }
  const card = e.target.closest('.cls-item'); if (!card) return;
  openClassicDetail(+card.dataset.id);
});

/* ---- 古诗文详情：拼音 / 译文 / 赏析 / AI 讲解 ---- */
let cdData = null;
async function openClassicDetail(id) {
  push({ view: 'cdetail', title: '古诗文' });
  $('#cd-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/classics/' + id + '/detail');
    cdData = d;
    stack[stack.length - 1].title = d.title;
    $('#top-title').textContent = d.title;
    renderCDetail();
  } catch (e) { $('#cd-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderCDetail() {
  const d = cdData;
  const meta = [d.dynasty, d.author, d.sub].filter(Boolean).join(' · ');
  const body = d.lines.map((ln, i) => {
    if (!ln.trim()) return '';
    return `<div class="cd-line"><div class="cd-py">${esc(d.pinyin[i] || '')}</div><div class="cd-han">${esc(ln)}</div></div>`;
  }).join('');
  // AI 讲解一旦生成，即替换掉开源译文/赏析；未生成时才展示开源资源
  const hasAI = !!d.ai_explain;
  let res = '';
  if (!hasAI) {
    if (d.translation) res += `<div class="cd-sec"><div class="cd-sec-t">译文</div><div class="cd-sec-b">${esc(d.translation).replace(/\n/g, '<br>')}</div></div>`;
    if (d.appreciation) res += `<div class="cd-sec"><div class="cd-sec-t">赏析</div><div class="cd-sec-b">${esc(d.appreciation).replace(/\n/g, '<br>')}</div></div>`;
  }
  const aiBox = hasAI
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">AI 讲解</div><div class="cd-sec-b">${mdToHtml(d.ai_explain)}</div>
        <button class="btn cd-ai-regen" id="cd-ai-regen">重新生成</button></div>`
    : `<button class="btn primary cd-ai-btn" id="cd-ai-btn">🤖 AI 讲解${(d.translation || d.appreciation) ? '（生成后替换开源译文/赏析）' : ''}</button>`;
  $('#cd-wrap').innerHTML = `
    <div class="cd-head">
      <span class="cls-badge" style="background:${CLS_BADGE[d.category] || '#888'}">${esc(d.category)}</span>
      <h2 class="cd-title">${esc(d.title)}</h2>
      <button class="cls-star ${d.starred ? 'on' : ''}" id="cd-star">${d.starred ? '★' : '☆'}</button>
    </div>
    <div class="cd-meta">${esc(meta)}</div>
    <div class="cd-body">${body}</div>
    ${res || (hasAI ? '' : '<p class="cd-tip">这篇暂无现成译文，可点下面让 AI 讲解。</p>')}
    ${aiBox}`;
}
$('#cd-wrap').addEventListener('click', async e => {
  if (e.target.closest('#cd-star')) {
    const on = !cdData.starred;
    try { await api('/api/classics/' + cdData.id + '/star', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: on }) }); cdData.starred = on; renderCDetail(); } catch (err) { toast(err.message, true); }
    return;
  }
  const gen = e.target.closest('#cd-ai-btn') || e.target.closest('#cd-ai-regen');
  if (gen) {
    const regen = gen.id === 'cd-ai-regen';
    gen.disabled = true; gen.textContent = 'AI 生成中…（约十几秒）';
    try {
      const d = await api('/api/classics/' + cdData.id + '/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: regen }) });
      cdData.ai_explain = d.content; renderCDetail();
    } catch (err) { toast(err.message, true); gen.disabled = false; gen.textContent = '🤖 AI 讲解'; }
  }
});

/* ---- 导出 PDF ---- */
$('#cls-export').onclick = () => {
  const scopes = [['cur', '当前筛选']];
  scopes.push(['star', '仅收藏']);
  $('#clsx-scope').innerHTML = scopes.map(s => `<option value="${s[0]}">${s[1]}</option>`).join('');
  $('#clsx-modal').classList.remove('hidden');
};
$('#clsx-cancel').onclick = () => $('#clsx-modal').classList.add('hidden');
$('#clsx-modal').addEventListener('click', e => { if (e.target.id === 'clsx-modal') $('#clsx-modal').classList.add('hidden'); });
$('#clsx-go').onclick = () => {
  const scope = $('#clsx-scope').value;
  const p = new URLSearchParams();
  p.set('py', $('#clsx-py').checked ? 1 : 0);
  p.set('tr', $('#clsx-tr').checked ? 1 : 0);
  if (scope === 'star' || clsState.star) p.set('star', 1);
  if (scope !== 'star') { if (clsState.cat) p.set('category', clsState.cat); if (clsState.q) p.set('q', clsState.q); }
  $('#clsx-modal').classList.add('hidden'); toast('正在导出 PDF…');
  window.location.href = '/api/classics/export?' + p.toString();
};
$('#cls-prev').onclick = () => { if (clsState.page > 1) { clsState.page--; loadClassics(); window.scrollTo({ top: 0 }); } };
$('#cls-next').onclick = () => { if (clsState.page < clsState.pages) { clsState.page++; loadClassics(); window.scrollTo({ top: 0 }); } };

/* ================= AI 助手 ================= */
/* ---- 全局 AI 会话中心（仿 Claude：新对话 / 项目 / 最近） ---- */
let aiMsgs = [], aiBusy = false, aiChatId = null, aiProjectId = null;
const AI_FOLDER = '<svg class="ai-folder" viewBox="0 0 48 48"><rect x="2" y="2" width="44" height="44" rx="13" fill="#5b6cf0"/><path fill="#7d8cf8" opacity=".5" d="M2 15C2 7.8 7.8 2 15 2h18c7.2 0 13 5.8 13 13v2H2z"/><rect x="11" y="11" width="11.5" height="11.5" rx="3.5" fill="#fff"/><rect x="25.5" y="11" width="11.5" height="11.5" rx="3.5" fill="#fff" opacity=".82"/><rect x="11" y="25.5" width="11.5" height="11.5" rx="3.5" fill="#fff" opacity=".82"/><circle cx="31.2" cy="31.2" r="5.8" fill="#ffd66b"/></svg>';
function aiShow(v) {
  ['aiv-home', 'aiv-projects', 'aiv-project', 'aiv-chat'].forEach(id => $('#' + id).classList.add('hidden'));
  $('#aiv-' + v).classList.remove('hidden');
}
/* AI 面板也用通用停靠：默认半屏（电脑右半屏 / 手机下半屏），不再一点就整屏盖住 */
let aiDk = null;
function aiInitDock() {
  if (aiDk) return;
  $('#ai-shot').classList.toggle('hidden', !window.__desktopShot);   // 截图只有桌面版有
  aiDk = createDock($('#ai-panel'), 'aiDock', IS_MOBILE ? 'bottom' : 'right', null);
  document.querySelectorAll('#ai-panel .ai-dock').forEach(b =>
    b.addEventListener('pointerdown', (e) => aiDk.dockDrag(e)));
  document.querySelectorAll('#ai-panel .ai-full').forEach(b =>
    b.onclick = () => aiDk.toggleFull());
}
async function openAI(preset) {
  aiInitDock();
  $('#ai-panel').classList.remove('hidden');
  aiDk.apply(false);
  if (preset) { await aiNewChat(); $('#ai-text').value = preset; aiGrow(); return; }
  aiShow('home'); loadAiHome();
}
async function loadAiHome() {
  try {
    const d = await api('/api/aichat/home');
    $('#aih-pcount').textContent = d.projects.length || '';
    $('#aih-recents').innerHTML = d.chats.length ? d.chats.map(c => `
      <div class="aih-item" data-aichat="${c.id}">
        <div class="aih-it">${c.starred ? '⭐ ' : ''}${esc(c.title || '（新对话）')}</div>
        <div class="aih-im">${c.pname ? AI_FOLDER + ' ' + esc(c.pname) + ' · ' : ''}${esc((c.updated_at || '').slice(5, 16))}</div>
        <button class="aih-del" data-aimenu="${c.id}" data-atitle="${esc(c.title || '')}" data-aproj="${c.project_id || ''}" data-astar="${c.starred ? 1 : 0}">⋮</button>
      </div>`).join('') : '<p class="empty" style="padding:20px 0">还没有对话，点上面「＋ 新对话」开始。</p>';
    $('#ai-panel')._projects = d.projects;
    $('#ai-panel')._chats = d.chats;
  } catch (e) { toast(e.message, true); }
}
async function aiNewChat(projectId) {
  // 懒创建：先进界面，第一次发送消息时才真正建会话（不产生空记录）
  aiChatId = null; aiProjectId = projectId || null; aiMsgs = [];
  const ps = $('#ai-panel')._projects || [];
  const p = ps.find(x => x.id === aiProjectId);
  $('#aic-title').textContent = p ? ('📁 ' + p.name + ' · 新对话') : '新对话';
  aiShow('chat'); renderAI();
  setTimeout(() => $('#ai-text').focus(), 60);
}
async function aiOpenChat(id) {
  try {
    const d = await api('/api/aichat/chats/' + id);
    aiChatId = d.id; aiMsgs = d.msgs; aiProjectId = d.project_id;
    $('#aic-title').textContent = d.title || '对话';
    aiShow('chat'); renderAI();
  } catch (e) { toast(e.message, true); }
}
function renderAiProjects() {
  const ps = $('#ai-panel')._projects || [];
  $('#aip-list').innerHTML = (ps.length ? ps.map(p => `
    <div class="aih-item" data-aiproj="${p.id}">
      <div class="aih-it">${AI_FOLDER} ${esc(p.name)}</div>
      <div class="aih-im">${p.cnt} 个对话${p.instructions ? ' · 有自定义指令' : ''}</div>
      <button class="aih-del" data-aipdel="${p.id}">✕</button>
    </div>`).join('') : '<p class="empty" style="padding:20px 0">还没有项目。项目=一组对话+自定义指令（比如"申论批改"）。</p>')
    + '<p class="cd-tip" style="margin-top:14px">点项目名在该项目下开新对话，AI 会遵循项目指令。</p>';
}
let aiCurProject = null;
function openAiProject(pid) {
  const ps = $('#ai-panel')._projects || [];
  const p = ps.find(x => x.id === pid); if (!p) return;
  const chats = ($('#ai-panel')._chats || []).filter(c => c.project_id === pid);
  if (!chats.length) { aiNewChat(pid); return; }   // 空项目：直接开新对话
  aiCurProject = p;
  $('#aipd-title').textContent = p.name;
  $('#aipd-chats').innerHTML = chats.map(c => `
    <div class="aih-item" data-aichat="${c.id}">
      <div class="aih-it">${c.starred ? '⭐ ' : ''}${esc(c.title || '（新对话）')}</div>
      <div class="aih-im">${esc((c.updated_at || '').slice(5, 16))}</div>
      <button class="aih-del" data-aimenu="${c.id}" data-atitle="${esc(c.title || '')}" data-aproj="${c.project_id || ''}" data-astar="${c.starred ? 1 : 0}">⋮</button>
    </div>`).join('')
    + (p.instructions ? `<p class="cd-tip" style="margin-top:12px">📋 项目指令：${esc(p.instructions)}</p>` : '');
  aiShow('project');
}
$('#aipd-new').onclick = () => { if (aiCurProject) aiNewChat(aiCurProject.id); };
function renderAI() {
  $('#ai-msgs').innerHTML = (aiMsgs.length ? '' : '<div class="ai-msg assistant">我是你的公考 AI 助手 👋 讲知识点、出题、翻译古文、分析错题、聊备考都行。我还能看到你的收录/错题/复习数据。</div>')
    + aiMsgs.map(m =>
      `<div class="ai-msg ${m.role}">${m.role === 'assistant' ? mdToHtml(m.content) : esc(m.content)}</div>`).join('')
    + (aiBusy ? '<div class="ai-msg assistant ai-typing">思考中…</div>' : '');
  const box = $('#ai-msgs'); box.scrollTop = box.scrollHeight;
  $('#ai-send').disabled = aiBusy;
}
let aiAtts = [];  // [{name, text}]
function renderAiAtts() {
  $('#ai-atts').innerHTML = aiAtts.map((a, i) =>
    `<span class="ai-att">📎 ${esc(a.name)} <button data-aiattdel="${i}">×</button></span>`).join('');
}
$('#ai-atts').addEventListener('click', e => {
  const b = e.target.closest('[data-aiattdel]'); if (!b) return;
  aiAtts.splice(+b.dataset.aiattdel, 1); renderAiAtts();
});
$('#ai-attach').onclick = () => $('#ai-attsheet').classList.remove('hidden');
$('#ai-attsheet').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]') || e.target.id === 'ai-attsheet') { $('#ai-attsheet').classList.add('hidden'); return; }
  const b = e.target.closest('[data-aiatt]'); if (!b) return;
  $('#ai-attsheet').classList.add('hidden');
  if (b.dataset.aiatt === 'photo') $('#ai-camfile').click();
  else if (b.dataset.aiatt === 'image') { $('#ai-attfile').accept = 'image/*'; $('#ai-attfile').click(); }
  else { $('#ai-attfile').accept = '.pdf,.doc,.docx,.txt,.md,.ppt,.pptx,.xls,.xlsx'; $('#ai-attfile').click(); }
});
async function aiHandleAttach(file) {
  if (!file) return;
  toast('正在读取附件…');
  const fd = new FormData(); fd.append('file', file);
  try {
    const d = await api('/api/ai/extract', { method: 'POST', body: fd });
    if (d.error) { toast(d.error, true); return; }
    aiAtts.push({ name: d.name || file.name, text: d.text }); renderAiAtts();
    toast('已附加，发送时 AI 会读取其内容');
  } catch (e) { toast(e.message, true); }
}
$('#ai-attfile').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; aiHandleAttach(f); });
$('#ai-camfile').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; aiHandleAttach(f); });

async function aiSend() {
  const t = $('#ai-text').value.trim();
  if ((!t && !aiAtts.length) || aiBusy) return;
  let payload = t, shown = t;
  if (aiAtts.length) {
    payload = aiAtts.map(a => '【附件：' + a.name + '】\n' + a.text).join('\n\n') + '\n\n' + (t || '请阅读以上附件内容并帮我分析/讲解。');
    shown = (t ? t + '\n' : '') + '📎 ' + aiAtts.map(a => a.name).join('、');
    aiAtts = []; renderAiAtts();
  }
  if (!aiChatId) {
    try {
      const d = await api('/api/aichat/chats', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: aiProjectId || null }) });
      aiChatId = d.id;
    } catch (e) { toast(e.message, true); return; }
  }
  aiMsgs.push({ role: 'user', content: shown });
  $('#ai-text').value = ''; aiGrow();
  aiBusy = true; renderAI();
  try {
    const d = await api('/api/aichat/chats/' + aiChatId + '/send', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: payload })
    });
    aiMsgs.push({ role: 'assistant', content: d.reply || '（空回复）' });
    if (d.title) $('#aic-title').textContent = d.title;
  } catch (e) {
    aiMsgs.push({ role: 'assistant', content: '⚠️ ' + e.message });
  }
  aiBusy = false; renderAI();
}
function aiGrow() { const t = $('#ai-text'); t.style.height = 'auto'; t.style.height = Math.min(120, t.scrollHeight) + 'px'; }
$('#ai-send').onclick = aiSend;
/* AI 入口在悬浮工具球里（#fab-ai），见文件末尾的悬浮球逻辑 */
// AI 面板：从上方下滑关闭/返回上一层（替代点右上角✕）
(function () {
  const panel = $('#ai-panel'); if (!panel) return;
  let sy = 0, sx = 0, tracking = false;
  panel.addEventListener('touchstart', e => {
    if (e.touches.length !== 1) { tracking = false; return; }
    const y = e.touches[0].clientY;
    // 仅在顶部 140px 区域内（头部/新对话附近）起手，避免和列表滚动冲突
    tracking = y < 160;
    sy = y; sx = e.touches[0].clientX;
  }, { passive: true });
  panel.addEventListener('touchend', e => {
    if (!tracking) return; tracking = false;
    const t = e.changedTouches[0];
    const dy = t.clientY - sy, dx = Math.abs(t.clientX - sx);
    if (dy > 70 && dy > dx) {   // 明显下滑
      const cur = ['home', 'projects', 'project', 'chat'].find(v => !$('#aiv-' + v).classList.contains('hidden'));
      if (cur === 'home' || !cur) { $('#ai-panel').classList.add('hidden'); applyPush(); avoidFab(); }
      else if (cur === 'project') { renderAiProjects(); aiShow('projects'); }
      else { aiShow('home'); loadAiHome(); }
    }
  }, { passive: true });
})();

$('#aih-new').onclick = () => aiNewChat();
$('#aih-projects').onclick = () => { renderAiProjects(); aiShow('projects'); };
$('#aip-new').onclick = async () => {
  const name = await appPrompt('新建项目', '项目名，如：申论批改');
  if (!name || !name.trim()) return;
  const ins = await appPrompt('项目自定义指令（可留空）', '例：你是申论阅卷老师，对我提交的答案按采分点批改打分');
  try {
    await api('/api/aichat/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim(), instructions: (ins || '').trim() }) });
    await loadAiHome(); renderAiProjects();
  } catch (e) { toast(e.message, true); }
};
$('#ai-panel').addEventListener('click', async e => {
  const back = e.target.closest('[data-aiback]');
  if (back) {
    if (back.dataset.aiback === 'close') { $('#ai-panel').classList.add('hidden'); applyPush(); avoidFab(); }
    else aiBack();
    return;
  }
  const menu = e.target.closest('[data-aimenu]');
  if (menu) {
    e.stopPropagation();
    openAiChatMenu(+menu.dataset.aimenu, menu.dataset.atitle, menu.dataset.aproj, menu.dataset.astar === '1');
    return;
  }
  const pdel = e.target.closest('[data-aipdel]');
  if (pdel) {
    e.stopPropagation();
    if (!(await appConfirm('删除这个项目？（对话会保留，只是不再归组）'))) return;
    try { await api('/api/aichat/projects/' + pdel.dataset.aipdel, { method: 'DELETE' }); await loadAiHome(); renderAiProjects(); } catch (err) { toast(err.message, true); }
    return;
  }
  const chat = e.target.closest('[data-aichat]');
  if (chat) { aiOpenChat(+chat.dataset.aichat); return; }
  const proj = e.target.closest('[data-aiproj]');
  if (proj) { openAiProject(+proj.dataset.aiproj); return; }
});
$('#ai-close').onclick = () => { $('#ai-panel').classList.add('hidden'); applyPush(); avoidFab(); };
$('#ai-text').addEventListener('input', aiGrow);
$('#ai-text').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); aiSend(); } });

/* ================= 全文搜索 ================= */
let searchData = { q: '', filter: 'all', results: [] };
function openSearch() {
  searchData = { q: '', filter: 'all', results: [] };
  $('#search-input').value = '';
  $('#search-results').innerHTML = '';
  $('#search-empty').classList.add('hidden');
  document.querySelectorAll('#search-filter .chip').forEach(x => x.classList.toggle('active', x.dataset.sf === 'all'));
  push({ view: 'search' });
  setTimeout(() => $('#search-input').focus(), 80);
}
$('#home-search').onclick = openSearch;
let searchTimer2;
$('#search-input').addEventListener('input', e => {
  clearTimeout(searchTimer2);
  const q = e.target.value.trim();
  searchTimer2 = setTimeout(() => runSearch(q), 250);
});
$('#search-filter').addEventListener('click', e => {
  const c = e.target.closest('[data-sf]'); if (!c) return;
  searchData.filter = c.dataset.sf;
  document.querySelectorAll('#search-filter .chip').forEach(x => x.classList.toggle('active', x.dataset.sf === searchData.filter));
  renderSearch();
});
async function runSearch(q) {
  searchData.q = q;
  if (!q) { searchData.results = []; renderSearch(); return; }
  try {
    const d = await api('/api/search?q=' + encodeURIComponent(q));
    // 功能入口匹配（名称/关键词），置顶
    const fhits = FEATURES.filter(f => f.name.includes(q) || f.kw.includes(q))
      .map(f => ({ type: 'feature', title: f.name, snippet: f.desc, _open: f.open }));
    searchData.results = fhits.concat(d.results);
    renderSearch();
  } catch (e) { toast(e.message, true); }
}
function hl(text, q) {
  const t = esc(text || '');
  if (!q) return t;
  try { return t.replace(new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'), '<mark>$1</mark>'); }
  catch (_) { return t; }
}
const SR_TYPE = { note: '小记', material: '资料', doc: '知识库', wrongq: '错题', boardkb: '基础知识', news: '时政', policydoc: '要文', partydict: '理论词典', classic: '古诗文', changshi: '常识', sucai: '素材', gaikuo: '概括句', entry: '成语词语', feature: '功能',
  draft: '草稿本', essay: '范文', gongwen: '应用文', changkao: '常考', theory: '理论', xiyu: '习语', work: '经典著作' };
// 功能入口索引：搜索时匹配名称/关键词，结果置顶直达
const FEATURES = [
  { name: '备考规划', desc: '任务清单 · AI 按你的学情排当天计划', kw: '规划助手备考计划学习计划每日计划安排时间距考试', open: () => { openTasks(); setTimeout(() => tkSwitch('plan'), 60); } },
  { name: '范文推荐', desc: '申论 · 热门话题仿真卷 + 全套参考答案', kw: '范文推荐大作文议论文应用文参考答案话题基层治理科技创新乡村振兴', open: () => openEssays() },
  { name: '题目解析', desc: '题库 · 上传讲义让 AI 解出没答案的例题', kw: '题目解析讲义识题答案解析上传pdfword副本', open: () => openDocqa() },
  { name: '真题批改', desc: '申论 · 四大题型讲义 + AI 逐点批改', kw: '申论真题批改归纳概括综合分析提出对策贯彻执行大作文阅卷采分点范文', open: () => openShenlun() },
  { name: '常考', desc: '高频成语/实词/上位词/古诗文/常识/提法', kw: '常考高频考点成语实词上位词提法', open: () => openChangkao() },
  { name: '上位词积累', desc: '常考 · 逻辑填空概括词提示', kw: '上位词概括词下位词逻辑填空', open: () => openCkBoard('上位词') },
  { name: '理论基础', desc: '政治理论 · 马原/毛概/中特/习思想', kw: '理论马原马克思毛概毛泽东思想邓小平三个代表科学发展观习近平新时代中特公基', open: () => openTheory() },
  { name: '每日时政', desc: '政治理论 · 每天自动更新 AI 三行式', kw: '时政新闻党内国内四川国际', open: () => openNews() },
  { name: '时政要文库', desc: '政治理论 · 重要文件全文+AI解读', kw: '要文二十大报告十五五规划政府工作报告一号文件讲话', open: () => openPolicyDocs() },
  { name: '党的创新理论学习词典', desc: '政治理论 · 12371 术语速查+背诵', kw: '词典理论两个确立四个意识党章党史', open: () => openPartyDict() },
  { name: '常识积累', desc: '常识判断 · 七大板块考情+考点', kw: '常识人文科技法律地理经济公文管理', open: () => openChangshi() },
  { name: '成语词语积累', desc: '言语理解 · 查询收录+AI解释', kw: '成语词语词组选词填空', open: () => openIdiom() },
  { name: '古诗文·名句速查', desc: '议论文 · 唐诗宋词四书五经', kw: '古诗文诗词名句唐诗宋词论语', open: () => openClassics() },
  { name: '素材积累', desc: '议论文 · 人物/事例/理论论据 每日更新', kw: '素材人物事例理论论据写作', open: () => openSucai('全部') },
  { name: '衔接表达', desc: '议论文 · 过渡/转折/万能句式', kw: '衔接过渡转折句式', open: () => openSucai('衔接表达') },
  { name: '概括句积累', desc: '应用文 · 材料表述→规范概括句', kw: '概括句申论', open: () => openGaikuo() },
  { name: '应用文上位词', desc: '应用文 · 公文规范上位表述，按场景归类', kw: '应用文上位词公文规范表述通知意见倡议书规范用语提法', open: () => openGongwen() },
  { name: '错题本', desc: '拍照/输入 · AI 判题型给解析', kw: '错题刷题', open: () => openWrongq() },
  { name: '草稿本', desc: '错题本 · 平时打草稿/演算，手写不识别，自动保存', kw: '草稿本草稿纸打草稿演算竖式手写画板白板涂鸦计算', open: () => openDrafts() },
  { name: '巩固测试', desc: '任务清单 · 每日任务里，按当天计划出题，背题/测试两种模式', kw: '巩固测试测验做题背题模式服务端判分每日测试', open: () => { openTasks(); setTimeout(() => tkSwitch('daily'), 60); } },
  { name: '计划记录', desc: '任务清单 · 历史计划回看 + 进度分析', kw: '计划记录历史回看进度分析冷落模块', open: () => openPlanLog() },
  { name: '经典著作', desc: '毛泽东选集 · 全文精读 + AI 导读', kw: '经典著作毛选毛泽东选集精读朗读', open: () => openWorks() },
  { name: '今日复习', desc: '遗忘曲线 · 该复习的都在这', kw: '复习遗忘曲线艾宾浩斯背诵', open: () => openReview() },
  { name: '小记', desc: '随手记 · 标签归类', kw: '笔记记录', open: () => openNotes() },
  { name: '知识库', desc: '笔记本 · 文档 · 分组整理', kw: '文档笔记本', open: () => openKb() },
  { name: '资料库', desc: '图片/文档/网页 应用内查看', kw: '资料文件上传', open: () => openMaterials() },
  { name: '基础知识点', desc: '各板块 基础知识+方法技巧', kw: '基础知识方法技巧', open: () => { const b = ALL_BOARDS[0] ? null : null; openSection(SECTIONS[0] && SECTIONS[0].key); toast('进入任意板块即可看「基础知识点」'); } },
  { name: '账户', desc: '个人信息 · 改密码/邮箱/密保', kw: '账号设置密码退出登录', open: () => openAccount() },
];
function renderSearch() {
  const box = $('#search-results');
  // 筛选条只留「这次搜到东西」的类别，免得十几个 chip 排满一屏
  document.querySelectorAll('#search-filter .chip').forEach(c => {
    const t = c.dataset.sf;
    c.classList.toggle('hidden', !!searchData.q && t !== 'all'
      && !searchData.results.some(r => r.type === t));
  });
  if (!searchData.q) { box.innerHTML = ''; $('#search-empty').classList.add('hidden'); return; }
  let items = searchData.results;
  if (searchData.filter !== 'all') items = items.filter(r => r.type === searchData.filter);
  if (!items.length) {
    box.innerHTML = '';
    $('#search-empty').classList.remove('hidden');
    $('#search-empty').textContent = '没有匹配「' + searchData.q + '」的内容';
    return;
  }
  $('#search-empty').classList.add('hidden');
  box.innerHTML = items.map((r, i) => {
    const meta = r.type === 'doc' ? ('知识库：' + esc(r.notebook || ''))
      : r.type === 'material' ? ((r.ext || '').replace('.', '').toUpperCase() + (r.board ? ' · ' + esc(r.board) : ''))
        : r.type === 'note' ? (r.tags && r.tags.length ? r.tags.map(t => '#' + esc(t)).join(' ') : (r.board ? esc(r.board) : ''))
          : (r.board ? esc(r.board) : '');
    return `<div class="sr-item" data-sri="${i}">
      <div class="sr-head"><span class="sr-type ${r.type}">${SR_TYPE[r.type]}</span>
        <span class="sr-title">${hl(r.title, searchData.q)}</span></div>
      ${r.snippet ? `<div class="sr-snip">${hl(r.snippet, searchData.q)}</div>` : ''}
      ${meta ? `<div class="sr-meta">${meta}</div>` : ''}
    </div>`;
  }).join('');
  box._items = items;
}
$('#search-results').addEventListener('click', async e => {
  const it = e.target.closest('[data-sri]'); if (!it) return;
  const r = ($('#search-results')._items || [])[+it.dataset.sri]; if (!r) return;
  if (r.type === 'feature') {
    if (r._open) r._open();
  } else if (r.type === 'material') {
    if (r.viewable) openViewer(r.id, r.title, r.ext);
    else { const a = document.createElement('a'); a.href = '/api/materials/' + r.id + '/download'; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); }
  } else if (r.type === 'doc') {
    await openNotebook(r.notebook_id);
    openDoc(r.id);
  } else if (r.type === 'note') {
    try {
      const note = await api('/api/notes/' + r.id);
      openNotes();
      setTimeout(() => loadDraft(note), 120);
    } catch (e) { toast(e.message, true); }
  } else if (r.type === 'wrongq') {
    openWqDetail(r.id);
  } else if (r.type === 'boardkb') {
    openBoardKb(r.board);
  } else if (r.type === 'news') {
    openNewsItem(r.id);
  } else if (r.type === 'policydoc') {
    openPolicyDoc(r.id);
  } else if (r.type === 'classic') {
    openClassicDetail(r.id);
  } else if (r.type === 'partydict') {
    await openPartyDict();
    $('#pd-q').value = r.title; loadPartyDict();
  } else if (r.type === 'changshi') {
    csBoard = r.cs_board; csTopic = r.cs_topic;
    push({ view: 'csboard', title: csBoard });
    loadCsBoard();
  } else if (r.type === 'sucai') {
    openSucai(r.kind || '全部');
  } else if (r.type === 'gaikuo') {
    openGaikuo();
  } else if (r.type === 'entry') {
    openIdiom();
    state.q = r.title; $('#search').value = r.title; loadEntries();
  } else if (r.type === 'draft') {
    openDrafts();
    setTimeout(() => openDraft(r.id), 80);
  } else if (r.type === 'essay') {
    openEssay(r.id);
  } else if (r.type === 'gongwen') {
    openGongwen();
    setTimeout(() => { $('#gw-q').value = r.term || r.title; $('#gw-q').dispatchEvent(new Event('input')); }, 120);
  } else if (r.type === 'changkao') {
    openCkBoard(r.ck_board || '上位词');
  } else if (r.type === 'theory') {
    openThBoard(r.th_board || '');
  } else if (r.type === 'xiyu') {
    openNews();
    setTimeout(() => { const b = document.querySelector('#news-boards [data-nb="习语"]'); if (b) b.click(); }, 260);
  } else if (r.type === 'work') {
    openWorkDetail(r.id);
  }
});

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
  } catch (_) { }
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

/* ================= 板块基础知识点 ================= */
let bkbBoard = '', bkbData = null;
async function openBoardKb(board) {
  bkbBoard = board;
  push({ view: 'boardkb', title: board + ' · 基础知识点' });
  $('#bkb-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try { const d = await api('/api/boardkb?board=' + encodeURIComponent(board)); bkbData = d; renderBkb(); }
  catch (e) { $('#bkb-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderBkb() {
  const d = bkbData;
  const ai = d.ai
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">📚 基础知识 · 方法技巧（AI 整理）</div>
        <div class="cd-sec-b">${mdToHtml(d.ai)}</div>
        <button class="btn cd-ai-regen" id="bkb-regen">重新生成</button></div>`
    : `<div class="bkb-gen"><p class="cd-tip" style="margin:0 0 12px">还没有整理这个板块的基础知识点，让 AI 帮你系统梳理一份。</p>
        <button class="btn primary" id="bkb-gen" style="width:100%;padding:13px;">🤖 AI 生成基础知识点</button></div>`;
  const pts = (d.points || []).map(p =>
    `<div class="bkb-point"><div class="bkb-point-c">${esc(p.content).replace(/\n/g, '<br>')}</div>
      <button class="bkb-point-del" data-bpdel="${p.id}">×</button></div>`).join('');
  $('#bkb-wrap').innerHTML = ai + `
    <div class="cd-sec"><div class="cd-sec-t">✍️ 我的补充</div>
      <div class="bkb-points">${pts || '<p class="cd-tip" style="margin:0 0 10px">还没有补充，写点自己的要点/技巧吧。</p>'}</div>
      <div class="bkb-add">
        <textarea id="bkb-input" rows="2" placeholder="添加一条自己的知识点/技巧…"></textarea>
        <button class="btn primary" id="bkb-addbtn">添加</button>
      </div>
    </div>`;
}
$('#bkb-wrap').addEventListener('click', async e => {
  const g = e.target.closest('#bkb-gen') || e.target.closest('#bkb-regen');
  if (g) {
    g.disabled = true; g.textContent = 'AI 生成中…（约二十秒）';
    try {
      const d = await api('/api/boardkb/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ board: bkbBoard, force: g.id === 'bkb-regen' }) });
      bkbData.ai = d.content; renderBkb(); toast('已生成');
    } catch (err) { toast(err.message, true); g.disabled = false; g.textContent = '🤖 AI 生成基础知识点'; }
    return;
  }
  if (e.target.closest('#bkb-addbtn')) {
    const c = $('#bkb-input').value.trim(); if (!c) return;
    try { const p = await api('/api/boardkb/point', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ board: bkbBoard, content: c }) }); bkbData.points.unshift({ id: p.id, content: c }); renderBkb(); } catch (err) { toast(err.message, true); }
    return;
  }
  const del = e.target.closest('[data-bpdel]');
  if (del) {
    try { await api('/api/boardkb/point/' + del.dataset.bpdel, { method: 'DELETE' }); bkbData.points = bkbData.points.filter(p => p.id != del.dataset.bpdel); renderBkb(); } catch (err) { toast(err.message, true); }
  }
});

/* ================= 顶栏 ================= */
$('#admin-btn').onclick = () => { location.href = '/admin'; };
async function doLogout() {
  if (!(await appConfirm('退出登录？'))) return;
  try { await fetch('/logout', { method: 'POST' }); } catch (_) {}
  location.href = '/login';
}
// 关键点加粗：书名号/引号/【】/「」/“X个XX”等高频要点；换行转 <br>
function emKey(text) {
  let t = esc(text || '');
  t = t.replace(/《[^》]{1,40}》/g, m => '<b>' + m + '</b>')
    .replace(/“[^”]{1,40}”/g, m => '<b>' + m + '</b>')
    .replace(/「[^」]{1,40}」/g, m => '<b>' + m + '</b>')
    .replace(/【[^】]{1,40}】/g, m => '<b>' + m + '</b>')
    .replace(/[一二三四五六七八九十两]+个[一-龥]{2,8}/g, m => '<b>' + m + '</b>');
  return t.replace(/\n/g, '<br>');
}
function isDocHeading(s) {
  return /^(第[一二三四五六七八九十百]+[篇章节]|[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\)|\d+[、.．])/.test(s);
}

/* ============= 每日新闻视频（抓 → AI 按公考价值筛 → 只留最值得看的）=============
   信源全是**白名单里的官方媒体**：央视网（新闻联播/焦点访谈/东方时空/今日关注/环球视线，
   走 api.cntv.cn 的开放 JSON 接口）+ 川观新闻（四川日报社）。
   为什么不接受「任意博主」：**没法自动确认一个账号是不是真的**，那等于把把关的活儿丢给用户。
   核心价值不是「有视频看」，而是**帮你把不值得看的滤掉** —— 每条都说清「为什么值得看」。 */
let vdBoard = '', vdPoll = 0;

function openVideos() {
  push({ view: 'videos', title: '每日新闻视频' });
  loadVideos();
}
async function loadVideos() {
  const box = $('#vd-list');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const q = vdBoard === 'star' ? '?star=1' : (vdBoard ? '?board=' + encodeURIComponent(vdBoard) : '');
    const d = await api('/api/videos' + q);
    $('#vd-last').textContent = d.last ? `· 最近更新 ${fmtDay(d.last)}` : '';
    document.querySelectorAll('#vd-tabs .chip').forEach(c => {
      const k = c.dataset.vdb;
      c.classList.toggle('active', k === vdBoard);
      if (k && k !== 'star') {
        const n = (d.counts || {})[k] || 0;
        c.textContent = c.textContent.replace(/\s\d+$/, '') + (n ? ' ' + n : '');
      } else if (k === 'star') {
        c.textContent = '⭐ 收藏' + (d.n_star ? ' ' + d.n_star : '');
      }
    });
    if (!d.items.length) {
      box.innerHTML = vdBoard === 'star'
        ? '<p class="empty">还没收藏。看到有用的点 ☆ 收起来，做申论素材。</p>'
        : '<p class="empty">还没有视频。点上面「手动刷新」抓一批，或等每天 07:20 自动更新。</p>';
      return;
    }
    box.innerHTML = d.items.map(v => {
      const long = /^(0?[3-9]|[1-9]\d):/.test(v.duration || '');   // 超过 3 分钟的标一下
      return `<div class="vd-card">
        <a class="vd-cover" href="${esc(v.url)}" target="_blank" rel="noopener"
           style="${v.cover ? `background-image:url('${esc(v.cover)}')` : ''}">
          <span class="vd-play">▶</span>
          ${v.duration ? `<span class="vd-dur">${esc(v.duration)}</span>` : ''}
        </a>
        <div class="vd-body">
          <div class="vd-top">
            <span class="vd-board vd-${esc(v.board)}">${esc(v.board)}</span>
            <span class="vd-col">${esc(v.column_name || '')}</span>
            <span class="vd-score" title="AI 打的「值得看」分">★ ${v.score}</span>
            <button class="vd-star${v.starred ? ' on' : ''}" data-vdstar="${v.id}"
              title="收藏（可当申论素材）">${v.starred ? '★' : '☆'}</button>
          </div>
          <a class="vd-title" href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.title)}</a>
          ${v.why ? `<div class="vd-why"><b>为什么值得看</b>${esc(v.why)}</div>` : ''}
          ${(v.tags || []).length ? `<div class="vd-tags">${v.tags.map(t =>
            `<span>${esc(t)}</span>`).join('')}</div>` : ''}
          <div class="vd-foot">
            <span class="vd-src-n">📺 ${esc(v.source || '')}</span>
            <span>${esc((v.pub_date || '').slice(0, 16))}</span>
            ${v.brief ? `<button class="vd-more" data-vdbrief="${v.id}">内容提要 ▾</button>` : ''}
          </div>
          ${v.brief ? `<div class="vd-brief hidden" id="vdb-${v.id}">${esc(v.brief)}</div>` : ''}
        </div>
      </div>`;
    }).join('');
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#vd-tabs').addEventListener('click', e => {
  const c = e.target.closest('[data-vdb]'); if (!c) return;
  vdBoard = c.dataset.vdb;
  loadVideos();
});
$('#vd-list').addEventListener('click', async e => {
  const b = e.target.closest('[data-vdbrief]');
  if (b) {
    const box = $('#vdb-' + b.dataset.vdbrief);
    const open = box.classList.toggle('hidden');
    b.textContent = open ? '内容提要 ▾' : '收起 ▴';
    return;
  }
  const s = e.target.closest('[data-vdstar]');
  if (s) {
    e.preventDefault();
    s.disabled = true;
    try {
      const r = await api('/api/videos/' + s.dataset.vdstar + '/star', { method: 'POST' });
      s.textContent = r.starred ? '★' : '☆';
      s.classList.toggle('on', r.starred);
      toast(r.starred ? '已收藏（可当申论素材）' : '已取消收藏');
      if (vdBoard === 'star') loadVideos();
    } catch (err) { toast(err.message, true); }
    s.disabled = false;
  }
});
$('#vd-refresh').onclick = async () => {
  const b = $('#vd-refresh'); b.disabled = true;
  $('#vd-msg').textContent = '正在抓取（要开无头浏览器渲染川观新闻，约 1 分钟）…';
  try {
    const d = await api('/api/videos/refresh', { method: 'POST' });
    clearInterval(vdPoll);
    vdPoll = setInterval(async () => {
      try {
        const t = await api('/api/write/task/' + d.task);      // 后台任务表是共用的
        $('#vd-msg').textContent = t.message || '';
        if (t.status === 'done' || t.status === 'error') {
          clearInterval(vdPoll); vdPoll = 0;
          b.disabled = false;
          loadVideos();
          toast(t.status === 'done' ? '刷新完成' : t.message, t.status !== 'done');
        }
      } catch (_) { clearInterval(vdPoll); vdPoll = 0; b.disabled = false; }
    }, 3000);
  } catch (e) { toast(e.message, true); b.disabled = false; $('#vd-msg').textContent = ''; }
};

/* ============= 每日时政（爬虫 + AI 三行式；国内/四川/国际 三板块，全局共享） ============= */
let newsBoard = '党内', newsDate = '';
function fmtDay(iso) {
  const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(iso || '');
  return m ? (+m[1]) + '月' + (+m[2]) + '日' : (iso || '');
}
function renderDateStrip(el, dates, cur, attr) {
  el.innerHTML = (dates || []).map(d =>
    `<button class="chip ${d.date === cur ? 'active' : ''}" data-${attr}="${esc(d.date)}">${fmtDay(d.date)} ${d.count}</button>`).join('');
}
const XY_COLOR = { '经济': '#c2671f', '文化': '#7a5cc0', '社会': '#2b6fd6', '党建': '#b23b2e', '科教': '#0f766e', '生态': '#2e7d32', '国防': '#5a6b85', '国际': '#0277bd' };
let xyCat = '全部';
async function loadXiyu() {
  $('#news-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/xiyu?cat=' + encodeURIComponent(xyCat));
    const cats = ['全部'].concat(Object.keys(XY_COLOR));
    $('#news-dates').innerHTML = cats.map(c =>
      `<button class="chip ${c === xyCat ? 'active' : ''}" data-xc="${c}">${c}${c !== '全部' && d.counts[c] ? ' ' + d.counts[c] : ''}</button>`).join('');
    $('#news-dates').classList.remove('hidden');
    if (!d.items.length) { $('#news-list').innerHTML = '<p class="empty">还没有金句，每天清晨自动从习近平讲话数据库提炼～</p>'; return; }
    let lastDate = '';
    $('#news-list').innerHTML = d.items.map(it => {
      const head = it.date !== lastDate ? `<div class="sc-day">🗓 ${fmtDay(it.date)}</div>` : '';
      lastDate = it.date;
      const apply = it.apply || it.note || '';
      const bg = (it.note && it.note !== apply) ? it.note : '';
      return head + `<div class="gk-card">
        <div class="gk-head"><span class="poly-badge" style="background:${XY_COLOR[it.category] || '#666'}">${esc(it.category)}</span>
          ${it.keyword ? `<span class="xy-kw">🔑 ${esc(it.keyword)}</span>` : ''}</div>
        <div class="xy-quote">${emKey('“' + it.quote + '”')}</div>
        ${bg ? `<div class="xy-bg"><b>出处背景</b> ${esc(bg)}</div>` : ''}
        ${apply ? `<div class="xy-note"><b>申论运用</b> ${esc(apply)}</div>` : ''}
        ${it.source_url ? `<a class="poly-src" href="${esc(it.source_url)}" target="_blank" rel="noopener">讲话原文 ↗</a>` : ''}
      </div>`;
    }).join('');
  } catch (e) { $('#news-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
async function loadNews() {
  if (newsBoard === '习语') {
    document.querySelectorAll('#news-boards .chip').forEach(x => x.classList.toggle('active', x.dataset.nb === '习语'));
    loadXiyu(); return;
  }
  const starMode = newsBoard === '收藏';
  document.querySelectorAll('#news-boards .chip').forEach(x => x.classList.toggle('active', x.dataset.nb === newsBoard));
  $('#news-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api(starMode ? '/api/news?star=1'
      : '/api/news?board=' + encodeURIComponent(newsBoard) + '&date=' + encodeURIComponent(newsDate));
    if (d.counts) document.querySelectorAll('#news-boards .chip').forEach(x => {
      if (x.dataset.nb === '收藏') { x.textContent = '⭐ 收藏' + (d.star_total ? ' ' + d.star_total : ''); return; }
      const n = d.counts[x.dataset.nb]; x.textContent = x.dataset.nb + (n ? ' ' + n : '');
    });
    newsDate = d.date || '';
    renderDateStrip($('#news-dates'), d.dates, newsDate, 'nd');
    $('#news-dates').classList.toggle('hidden', starMode);
    if (!d.items.length) {
      $('#news-list').innerHTML = '<p class="empty">' + (starMode ? '还没有收藏，点新闻卡右上角的 ☆ 收藏。' : '这一天该板块没有时政，点上面换一天看看～') + '</p>';
      return;
    }
    $('#news-list').innerHTML = d.items.map(it => {
      const sum = (it.ai_summary || '').trim();
      return `<div class="poly-card news-card" data-news="${it.id}">
        <button class="news-star ${it.starred ? 'on' : ''}" data-nstar="${it.id}">${it.starred ? '★' : '☆'}</button>
        <div class="news-date">🗓 ${esc(it.pub_date || '')} · ${esc(it.source || '')}</div>
        <div class="poly-t" style="font-size:16px;padding-right:34px;">${esc(it.title)}</div>
        ${sum ? `<div class="news-sum" style="white-space:pre-wrap">${esc(sum)}</div>` : ''}
      </div>`;
    }).join('');
  } catch (e) { $('#news-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function openNews() { newsDate = ''; push({ view: 'news', title: '每日时政' }); loadNews(); }
$('#news-boards').addEventListener('click', e => {
  const c = e.target.closest('[data-nb]'); if (!c) return;
  newsBoard = c.dataset.nb; newsDate = ''; loadNews();
});
$('#news-dates').addEventListener('click', e => {
  const xc = e.target.closest('[data-xc]');
  if (xc) { xyCat = xc.dataset.xc; loadXiyu(); return; }
  const c = e.target.closest('[data-nd]'); if (!c) return;
  newsDate = c.dataset.nd; loadNews();
});
$('#news-list').addEventListener('click', async e => {
  const st = e.target.closest('[data-nstar]');
  if (st) {
    e.stopPropagation();
    const on = !st.classList.contains('on');
    try {
      await api('/api/news/' + st.dataset.nstar + '/star', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ starred: on }) });
      st.classList.toggle('on', on); st.textContent = on ? '★' : '☆';
      if (newsBoard === '收藏' && !on) loadNews();
      else toast(on ? '已收藏' : '已取消收藏');
    } catch (err) { toast(err.message, true); }
    return;
  }
  const c = e.target.closest('[data-news]'); if (c) openNewsItem(+c.dataset.news);
});
/* 时政的重点标注：四类考点，颜色一一对应 */
const NW_KIND = { 提法: { c: '#c4661f', d: '新表述/新概念，常识判断爱考' },
  数据: { c: '#1e8449', d: '具体数字/时间，最容易做成选项' },
  政策: { c: '#1a6fb5', d: '文件名/举措/目标' },
  金句: { c: '#7a5cc0', d: '能直接写进申论的表述' } };
let nwCur = null;

/* 把 AI 逐字挑出的句子，原样标回原文里（它们都经服务端核对过，必然能命中） */
function nwMarkup(content, marks) {
  const esc1 = (t) => esc(t);
  if (!marks || !marks.length) return esc1(content);
  // 长句优先标，避免短句先命中把长句切碎
  const ms = [...marks].sort((a, b) => b.quote.length - a.quote.length);
  const hits = [];
  ms.forEach((m, i) => {
    let from = 0, at;
    while ((at = content.indexOf(m.quote, from)) !== -1) {
      if (!hits.some(h => at < h.end && at + m.quote.length > h.start))   // 不和已标的重叠
        hits.push({ start: at, end: at + m.quote.length, m, i: marks.indexOf(m) });
      from = at + m.quote.length;
    }
  });
  hits.sort((a, b) => a.start - b.start);
  let out = '', pos = 0;
  for (const h of hits) {
    out += esc1(content.slice(pos, h.start));
    const k = NW_KIND[h.m.kind] || NW_KIND['提法'];
    // 注意：标签必须写成一行——外面会按 \n 切段落，标签里夹了换行就会被劈开，属性会漏成正文
    const tip = esc1(h.m.kind + '：' + (h.m.why || '')).replace(/"/g, '&quot;');
    out += `<mark class="nw-mk" style="--mk:${k.c}" data-nwm="${h.i}" title="${tip}">${esc1(h.m.quote)}<i>${esc1(h.m.kind)}</i></mark>`;
    pos = h.end;
  }
  out += esc1(content.slice(pos));
  return out;
}

async function openNewsItem(id) {
  push({ view: 'newsd', title: '时政详情' });
  $('#news-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/news/' + id);
    nwCur = d;
    stack[stack.length - 1].title = d.title; $('#top-title').textContent = d.title;
    nwRender(d);
  } catch (e) { $('#news-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}

function nwRender(d) {
  const marks = d.marks || [];
  // 重点清单：先看这个就够了，没时间就别读全文
  const list = marks.length ? `
    <div class="cd-sec nw-marks"><div class="cd-sec-t">🖍 重点 · 考点（${marks.length} 处，原文里已划出）</div>
      ${marks.map((m, i) => {
        const k = NW_KIND[m.kind] || NW_KIND['提法'];
        return `<div class="nw-m" data-nwgo="${i}" style="--mk:${k.c}">
          <span class="nw-k">${esc(m.kind)}</span>
          <span class="nw-q">${esc(m.quote)}</span>
          <span class="nw-w">${esc(m.why || '')}</span>
        </div>`;
      }).join('')}
      <div class="nw-legend">${Object.entries(NW_KIND).map(([k, v]) =>
        `<span style="--mk:${v.c}"><i></i>${k}：${v.d}</span>`).join('')}</div>
    </div>`
    : `<div class="cd-sec nw-marks">
        <div class="cd-sec-t">🖍 重点 · 考点</div>
        <p class="empty" style="padding:6px 0 12px">还没划重点。点一下，AI 会在原文里把该记的地方标出来（约 20 秒），不用通读全文。</p>
        <button class="btn primary" id="nw-mark">🖍 帮我划重点</button>
      </div>`;

  const ai = d.ai_summary
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">🤖 AI 摘要 · 三行式</div><div class="cd-sec-b">${mdToHtml(d.ai_summary)}</div></div>` : '';

  // 原文：把逐字挑出的重点句原样标出来（服务端核对过，必然命中）
  const marked = nwMarkup(d.content || '', marks);
  const body = marked.split('\n').filter(x => x.trim()).map(p =>
    `<p>${p}</p>`).join('');

  $('#news-wrap').innerHTML = `
    <div class="poly-head"><h2>${esc(d.title)}</h2>
      <div class="news-date">🗓 ${esc(d.pub_date || '')} · ${esc(d.source || '')}</div>
      <a class="poly-src" href="${esc(d.url)}" target="_blank" rel="noopener">原文来源 ↗</a></div>
    ${list}
    ${ai}
    <div class="poly-readert">全文（重点已划出）${marks.length ? `<button class="btn tiny" id="nw-remark">重划</button>` : ''}</div>
    <div class="poly-reader nw-reader">${body}</div>`;
  injectReadBtns();
}
$('#news-wrap').addEventListener('click', async e => {
  const go = e.target.closest('[data-nwgo]');            // 点重点清单 → 滚到原文里那一句
  if (go) {
    const el = $('#news-wrap').querySelector(`mark[data-nwm="${go.dataset.nwgo}"]`);
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      el.classList.add('flash');
      setTimeout(() => el.classList.remove('flash'), 1400);
    }
    return;
  }
  const b = e.target.closest('#nw-mark, #nw-remark');
  if (!b || !nwCur) return;
  b.disabled = true; b.textContent = '正在划重点…（约 20 秒）';
  try {
    const d = await api('/api/news/' + nwCur.id + '/marks' + (b.id === 'nw-remark' ? '?force=1' : ''),
      { method: 'POST' });
    nwCur.marks = d.marks;
    nwRender(nwCur);
    toast('划出 ' + d.marks.length + ' 处重点');
  } catch (err) {
    toast(err.message, true);
    b.disabled = false; b.textContent = '🖍 帮我划重点';
  }
});

/* ============= 申论 · 概括句积累（每日由时政生成，按日期查看） ============= */
let gkDate = '';
async function loadGaikuo() {
  $('#gk-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/gaikuo?date=' + encodeURIComponent(gkDate));
    gkDate = d.date || '';
    renderDateStrip($('#gk-dates'), d.dates, gkDate, 'gd');
    if (!d.items.length) { $('#gk-list').innerHTML = '<p class="empty">还没有概括句，每天早上会自动从当日时政生成～</p>'; return; }
    $('#gk-list').innerHTML = d.items.map((it, i) => `
      <div class="gk-card">
        <div class="gk-head"><span class="gk-no">${i + 1}</span><span class="gk-topic">${esc(it.topic)}</span></div>
        ${it.raw ? `<div class="gk-raw"><span class="gk-lab">材料</span>${esc(it.raw)}</div>` : ''}
        <div class="gk-sent"><span class="gk-lab gk-lab-s">概括</span><b>${esc(it.sentence)}</b></div>
        ${it.tip ? `<div class="gk-tip">💡 ${esc(it.tip)}</div>` : ''}
      </div>`).join('');
  } catch (e) { $('#gk-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function openGaikuo() { gkDate = ''; push({ view: 'gaikuo', title: '概括句积累' }); loadGaikuo(); }
$('#gk-dates').addEventListener('click', e => {
  const c = e.target.closest('[data-gd]'); if (!c) return;
  gkDate = c.dataset.gd; loadGaikuo();
});

/* ============= 应用文 · 应用文上位词（公文规范上位表述，按场景归类） ============= */
function gwCard(it) {
  const chips = (it.phrases || '').split(/[、,，]/).map(s => s.trim()).filter(Boolean)
    .map(p => `<span class="gw-chip">${esc(p)}</span>`).join('');
  return `<div class="gw-card">
    <div class="gw-top"><span class="gw-scene">${esc(it.scene)}</span>
      ${it.doctype ? `<span class="gw-doc">${esc(it.doctype)}</span>` : ''}
      ${it.source === 'ai' ? `<button class="gw-del" data-gwdel="${it.id}" title="删除">✕</button>` : ''}</div>
    <div class="gw-chips">${chips}</div>
    ${it.note ? `<div class="gw-note">💡 ${esc(it.note)}</div>` : ''}
    ${it.example ? `<div class="gw-eg"><span class="gw-lab">示范</span>${esc(it.example)}</div>` : ''}
  </div>`;
}
async function loadGongwen(q) {
  $('#gw-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/gongwen' + (q ? '?q=' + encodeURIComponent(q) : ''));
    if (!d.items.length) { $('#gw-list').innerHTML = '<p class="empty">没有匹配的场景，换个词试试～</p>'; return; }
    $('#gw-list').innerHTML = d.items.map(gwCard).join('');
  } catch (e) { $('#gw-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function openGongwen() { push({ view: 'gongwen', title: '应用文上位词' }); $('#gw-in').value = ''; $('#gw-q').value = ''; loadGongwen(); }
let gwTimer = null;
$('#gw-q').addEventListener('input', e => {
  clearTimeout(gwTimer);
  gwTimer = setTimeout(() => loadGongwen(e.target.value.trim()), 250);
});
$('#gw-ask').onclick = async () => {
  const text = $('#gw-in').value.trim();
  if (!text) { toast('先输入一句口语或一个场景', true); return; }
  $('#gw-ask').disabled = true; $('#gw-ask').textContent = '归纳中…';
  try {
    await api('/api/gongwen/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ input: text }) });
    $('#gw-in').value = ''; $('#gw-q').value = '';
    toast('已归纳并收录到最前面');
    await loadGongwen();
    $('#gw-list').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) { toast(e.message, true); }
  $('#gw-ask').disabled = false; $('#gw-ask').textContent = 'AI 归纳';
};
$('#gw-list').addEventListener('click', async e => {
  const d = e.target.closest('[data-gwdel]'); if (!d) return;
  if (!(await appConfirm('删除这条 AI 归纳的场景？'))) return;
  try { await api('/api/gongwen/' + d.dataset.gwdel, { method: 'DELETE' }); loadGongwen($('#gw-q').value.trim()); }
  catch (err) { toast(err.message, true); }
});

/* ============= 手写输入板（申论作答：数位板/手指 → Google 手写识别 → 填答案框） ============= */
const hwEl = {}; let hwTarget = null, hwStrokes = [], hwCur = null, hwT0 = 0, hwDrawing = false, hwTimer = null;
let hwAuto = localStorage.getItem('hwAuto') !== '0';   // 自动上屏首选字（默认开），连续写更快
let hwCommitted = null;                                 // 刚自动上屏的字，可点别的候选替换
let hwFs = localStorage.getItem('hwFs') === '1';        // 全屏透明手写：看得到后面正在填入的答案
let hwEngine = localStorage.getItem('hwEng') || 'cloud';  // 默认云端 Google(准)；'local'=端上ML Kit/本地Zinnia(快)
function hwInit() {
  ['modal', 'canvas', 'cands', 'count', 'close', 'undo', 'clear', 'space', 'nl', 'back', 'done', 'auto', 'fs', 'eng']
    .forEach(k => hwEl[k] = $('#hw-' + k));
  hwEl.engWrap = $('#hw-eng-wrap');
  const cv = hwEl.canvas, ctx = cv.getContext('2d');
  // 「已写完的笔画」画在离屏层上；每帧只把离屏层贴回来 + 画正在写的这一笔。
  // 原来每次 pointermove 都要重画田字格和全部笔画，写多几笔就明显拖影——草稿本没这个问题就是因为分了层。
  const base = document.createElement('canvas');
  const bctx = base.getContext('2d');
  let hwRaf = 0;
  function fit() {
    const r = cv.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    cv.width = base.width = r.width * dpr;
    cv.height = base.height = r.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    bctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    hwRebuild();
  }
  function pos(e) {
    const r = cv.getBoundingClientRect();
    const t = e.touches ? e.touches[0] : e;
    return { x: (t.clientX - r.left), y: (t.clientY - r.top) };
  }
  const hwInk = () => document.body.classList.contains('dark') ? '#e8edf5' : '#1a2230';
  function drawStroke(c, s) {
    if (!s || s.x.length < 1) return;
    c.strokeStyle = hwInk();
    c.lineWidth = 3.2; c.lineJoin = c.lineCap = 'round'; c.setLineDash([]);
    c.beginPath(); c.moveTo(s.x[0], s.y[0]);
    for (let i = 1; i < s.x.length; i++) c.lineTo(s.x[i], s.y[i]);
    if (s.x.length === 1) c.lineTo(s.x[0] + 0.1, s.y[0] + 0.1);
    c.stroke();
  }
  function hwRebuild() {              // 重建离屏层：田字格 + 已写完的笔画（撤销/清空/切主题才需要）
    const w = cv.clientWidth, h = cv.clientHeight;
    bctx.clearRect(0, 0, w, h);
    bctx.save();
    bctx.strokeStyle = document.body.classList.contains('dark') ? '#2a3446' : '#e3e8f0';
    bctx.lineWidth = 1; bctx.setLineDash([6, 6]);
    bctx.beginPath();
    bctx.moveTo(w / 2, 6); bctx.lineTo(w / 2, h - 6);
    bctx.moveTo(6, h / 2); bctx.lineTo(w - 6, h / 2);
    bctx.stroke();
    bctx.restore();
    for (const st of hwStrokes) drawStroke(bctx, st);
    hwPaint();
  }
  function hwPaint() {                // 每帧只干这两件事：贴离屏层 + 画正在写的这一笔
    const w = cv.clientWidth, h = cv.clientHeight;
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(base, 0, 0, w, h);
    if (hwCur) drawStroke(ctx, hwCur);
  }
  hwRedraw = hwRebuild;
  function start(e) {
    e.preventDefault(); hwDrawing = true;
    hwCommitted = null;                        // 又开始写了，取消"可替换刚上屏的字"
    if (!hwStrokes.length && !hwCur) hwT0 = Date.now();
    const p = pos(e); hwCur = { x: [p.x], y: [p.y], t: [Date.now() - hwT0] };
    clearTimeout(hwTimer);
  }
  function move(e) {
    if (!hwDrawing || !hwCur) return;
    e.preventDefault();
    let evs = [];                       // 高频合并采样 → 线更顺（有的 WebKit 返回空表，退回事件本身）
    try { if (e.getCoalescedEvents) evs = e.getCoalescedEvents(); } catch (_) {}
    if (!evs.length) evs = [e];
    for (const ev of evs) {
      const p = pos(ev);
      hwCur.x.push(p.x); hwCur.y.push(p.y); hwCur.t.push(Date.now() - hwT0);
    }
    if (!hwRaf) hwRaf = requestAnimationFrame(() => { hwRaf = 0; hwPaint(); });
  }
  function end(e) {
    if (!hwDrawing) return;
    e && e.preventDefault(); hwDrawing = false;
    if (hwCur) { hwStrokes.push(hwCur); drawStroke(bctx, hwCur); hwCur = null; hwPaint(); }
    clearTimeout(hwTimer);
    // 停笔就处理：自动=入队并清画布(接着写)，手动=出候选等你点。多笔画的字留足写完时间
    hwTimer = setTimeout(() => (hwAuto ? hwFlush() : hwRecognizeManual()), hwAuto ? 500 : 300);
  }
  cv.addEventListener('pointerdown', start);
  cv.addEventListener('pointermove', move);
  cv.addEventListener('pointerup', end);
  cv.addEventListener('pointerleave', end);
  hwEl._fit = fit;
  hwEl.close.onclick = hwClose;
  hwEl.clear.onclick = () => { hwStrokes = []; hwCur = null; hwRedraw(); hwSetCands([]); };
  hwEl.undo.onclick = () => { hwStrokes.pop(); hwRedraw(); if (!hwStrokes.length) hwSetCands([]); else if (!hwAuto) hwRecognizeManual(); };
  hwEl.space.onclick = () => hwInsert(' ');
  hwEl.nl.onclick = () => hwInsert('\n');
  hwEl.back.onclick = () => {
    if (!hwTarget) return;
    hwTarget.value = hwTarget.value.slice(0, -1);
    hwCommitted = null; hwFireInput();
  };
  hwEl.done.onclick = hwClose;
  hwEl.auto.checked = hwAuto;
  hwEl.auto.onchange = () => { hwAuto = hwEl.auto.checked; localStorage.setItem('hwAuto', hwAuto ? '1' : '0'); };
  if (hwEl.fs) hwEl.fs.onclick = () => { hwFs = !hwFs; localStorage.setItem('hwFs', hwFs ? '1' : '0'); hwApplyFs(); };
  // 默认云端 Google(准)，打勾切「更快(本地/端上)」——手机 ML Kit、电脑 Zinnia
  if (hwEl.eng) {
    hwEl.eng.checked = (hwEngine === 'local');
    hwEl.eng.onchange = () => {
      hwEngine = hwEl.eng.checked ? 'local' : 'cloud'; localStorage.setItem('hwEng', hwEngine);
      try { if (hwEngine === 'local' && window.GongkaoNative && GongkaoNative.hwPrepare) GongkaoNative.hwPrepare(); } catch (_) {}
    };
  }
}
function hwApplyFs() {
  hwEl.modal.classList.toggle('hw-fs', hwFs);
  if (hwEl.fs) hwEl.fs.classList.toggle('on', hwFs);
  requestAnimationFrame(() => { if (hwEl._fit) hwEl._fit(); });   // 尺寸变了，重新适配画布
}
let hwRedraw = () => {};
let hwLastCands = [], hwQueue = [], hwBusy = false;
function hwInk() {
  const cv = hwEl.canvas;
  return { w: Math.round(cv.clientWidth), h: Math.round(cv.clientHeight),
           ink: hwStrokes.map(s => [s.x.map(v => Math.round(v)), s.y.map(v => Math.round(v)), s.t]) };
}
// APK 内置离线手写（ML Kit）：可用则优先，识别瞬时且离线；结果经原生回调
let __hwReq = 0; const __hwCbs = {};
window.__hwNative = function (reqId, jsonStr) {
  const cb = __hwCbs[reqId]; if (!cb) return; delete __hwCbs[reqId];
  let r = null; try { r = JSON.parse(jsonStr); } catch (_) {}
  cb(r && r.ok ? (r.candidates || []) : null);   // null = 模型未就绪/失败 → 退服务端
};
function hwNativeReady() {
  try { return !!(window.GongkaoNative && GongkaoNative.hwAvailable && GongkaoNative.hwAvailable()); }
  catch (_) { return false; }
}
function hwNativeRecognize(payload) {
  return new Promise(resolve => {
    const id = ++__hwReq; __hwCbs[id] = resolve;
    try { GongkaoNative.hwRecognize(id, JSON.stringify(payload)); }
    catch (_) { delete __hwCbs[id]; resolve(null); return; }
    setTimeout(() => { if (__hwCbs[id]) { delete __hwCbs[id]; resolve(null); } }, 5000);
  });
}
function hwApi(url, payload) {
  return api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
    .then(d => (d && d.candidates) || []).catch(() => []);
}
// 统一识别：APK 端上 ML Kit 优先；网页/桌面按开关走「本地 Zinnia(快)」或「云端 Google(准)」，本地无果自动退云端
async function hwCall(payload) {
  if (hwEngine !== 'local') return hwApi('/api/handwrite', payload);   // 默认：手机/电脑都走 Google(准)
  // 「更快(本地)」：手机端上 ML Kit，电脑本地 Zinnia，都退云端兜底
  if (hwNativeReady()) {
    const c = await hwNativeRecognize(payload);
    if (c) return c;
  }
  const local = await hwApi('/api/handwrite/local', payload);
  if (local.length) return local;
  return hwApi('/api/handwrite', payload);
}
// 自动模式：把这个字入队、立刻清空画布接着写下一个；识别在后台排队跟上、按顺序填字
function hwFlush() {
  if (!hwStrokes.length) return;
  hwQueue.push(hwInk());
  hwCommitted = null;
  hwStrokes = []; hwCur = null; hwRedraw();
  hwPump();
}
async function hwPump() {
  if (hwBusy || !hwQueue.length) return;
  hwBusy = true;
  const job = hwQueue.shift();
  const cands = await hwCall(job);
  if (cands.length) { hwLastCands = cands; hwInsert(cands[0]); hwCommitted = cands[0]; hwSetCands(cands, cands[0]); }
  hwBusy = false;
  hwPump();     // 处理队列里下一个字
}
// 手动模式：识别后展示候选，等你点（不清画布）
async function hwRecognizeManual() {
  if (!hwStrokes.length) return;
  hwSetCands(null);
  hwLastCands = await hwCall(hwInk());
  hwSetCands(hwLastCands);
}
function hwSetCands(list, picked) {
  if (list === null) { hwEl.cands.innerHTML = '<span class="hw-hint">识别中…</span>'; return; }
  if (!list.length) { hwEl.cands.innerHTML = '<span class="hw-hint">在田字格里写字，' + (hwAuto ? '停笔即自动上屏' : '写完点候选字填入') + '</span>'; return; }
  hwEl.cands.innerHTML = (picked ? '<span class="hw-hint hw-hint-s">已填，可点其它字更正 →</span>' : '') +
    list.map(c => `<button class="hw-cand ${c === picked ? 'filled' : ''}" data-c="${esc(c)}">${esc(c)}</button>`).join('');
}
function hwInsert(ch) {   // 只插文字，不动画布（流水线里画布可能已在写下一个字）
  if (!hwTarget) return;
  const s = hwTarget.selectionStart, e = hwTarget.selectionEnd, v = hwTarget.value;
  if (s != null && e != null) {
    hwTarget.value = v.slice(0, s) + ch + v.slice(e);
    const p = s + ch.length; hwTarget.selectionStart = hwTarget.selectionEnd = p;
  } else { hwTarget.value = v + ch; }
  hwFireInput();
}
function hwClearPad() { hwStrokes = []; hwCur = null; hwRedraw(); hwSetCands([]); }
function hwFireInput() {
  hwTarget.dispatchEvent(new Event('input', { bubbles: true }));
  hwEl.count.textContent = (hwTarget.value || '').replace(/\s/g, '').length;
}
hwEl.candsClick = null;
function openHandwrite(targetId) {
  if (!hwEl.canvas) hwInit();
  hwTarget = document.getElementById(targetId);
  if (!hwTarget) return;
  hwStrokes = []; hwCur = null; hwQueue = []; hwBusy = false; hwCommitted = null;
  try { if (hwEngine === 'local' && window.GongkaoNative && GongkaoNative.hwPrepare) GongkaoNative.hwPrepare(); } catch (_) {}  // 仅"更快"模式才预下载端上模型
  hwEl.modal.classList.remove('hidden');
  hwApplyFs();
  requestAnimationFrame(() => { hwEl._fit(); hwSetCands([]); hwFireInput(); });
}
function hwClose() {
  hwEl.modal.classList.add('hidden');
  clearTimeout(hwTimer); hwStrokes = []; hwCur = null; hwQueue = []; hwBusy = false; hwCommitted = null;
  hwTarget && hwTarget.focus();
}
document.addEventListener('click', e => {
  const o = e.target.closest('[data-hw]');
  if (o) { e.preventDefault(); openHandwrite(o.dataset.hw); return; }
  const c = e.target.closest('.hw-cand');
  if (c) {
    const ch = c.dataset.c;
    if (hwCommitted && !hwStrokes.length) {
      // 刚自动上屏的字选错了：删掉它再填选中的字（更正）
      if (hwTarget) { hwTarget.value = hwTarget.value.slice(0, -1); }
      hwInsert(ch); hwCommitted = ch; hwSetCands(hwLastCands, ch);
    } else {
      hwInsert(ch); hwCommitted = null;
      if (!hwAuto) hwClearPad();   // 手动模式：填完清画布，准备写下一个
    }
  }
});

/* ============= 小题训练：找点 + 写点 =============
   归纳概括 / 综合分析 / 提出对策，难点是同一个：从材料里把要点找出来。
   所以拆成两步，每步单独纠错：
     第一步「找点」—— 只勾画不写字，判**找漏 / 找错 / 找重**
     第二步「写点」—— 照着勾到的地方写，判**概括到不到位**
   勾画粒度是**句**：申论找点本来就是找句子，句子边界明确才判得准
   （自由划词的区间对不齐采分点，判定必然变成玄学）。 */
let fdPaper = null, fdPicked = new Set(), fdStep = 1, fdCheck = null, fdDrag = null;

function openFind() {
  push({ view: 'find', title: '小题训练' });
  loadFindTypes();
  loadFindList();
}
async function loadFindTypes() {
  try {
    const d = await api('/api/find/types');
    $('#fd-types').innerHTML = d.types.map((t, i) => `
      <div class="fd-type${i === 0 ? ' on' : ''}" data-fdt="${t.key}">
        <div class="fd-type-h"><b>${esc(t.name)}</b><span>${t.full} 分 · ${t.word_min}~${t.word_max} 字</span></div>
        <p>${esc(t.tip)}</p>
        <div class="fd-type-n">${t.n ? '练过 ' + t.n + ' 道' : '还没练过'}</div>
      </div>`).join('');
  } catch (e) { $('#fd-types').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#fd-types').addEventListener('click', e => {
  const t = e.target.closest('[data-fdt]'); if (!t) return;
  document.querySelectorAll('#fd-types .fd-type').forEach(x => x.classList.toggle('on', x === t));
});
const fdType = () => (document.querySelector('#fd-types .fd-type.on') || {}).dataset?.fdt || 'guina';

async function loadFindList() {
  const box = $('#fd-list');
  try {
    const d = await api('/api/find/papers');
    box.innerHTML = d.items.length ? d.items.map(x => `
      <div class="wr-day done" data-fdp="${x.id}">
        <div class="wr-day-d">${esc(x.type_name)}</div>
        <div class="wr-day-m"><b>${esc((x.stem || '').slice(0, 40))}</b>
          <span class="wr-w">${x.full} 分</span>
          <span class="wr-tag">${esc(x.source || '')}</span>
          ${x.done ? `<span class="fd-done">练过 ${x.done} 次</span>` : ''}</div>
      </div>`).join('') : '<p class="empty">还没有题。上面点「出一道」，或上传一份真题。</p>';
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#fd-list').addEventListener('click', e => {
  const c = e.target.closest('[data-fdp]'); if (c) openFindRun(+c.dataset.fdp);
});
$('#fd-gen').onclick = async () => {
  const b = $('#fd-gen'); b.disabled = true; b.textContent = '出题中…（约 20 秒）';
  $('#fd-msg').textContent = 'AI 正在造材料（会故意掺入干扰信息）并标采分点…';
  try {
    const d = await api('/api/find/gen', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qtype: fdType(), topic: $('#fd-topic').value.trim() }),
    });
    $('#fd-msg').textContent = '';
    openFindRun(d.id); loadFindList(); loadFindTypes();
  } catch (e) { toast(e.message, true); $('#fd-msg').textContent = ''; }
  b.disabled = false; b.textContent = '✍️ 出一道';
};
$('#fd-up').onclick = () => $('#fd-file').click();
$('#fd-file').onchange = async () => {
  const f = $('#fd-file').files[0]; if (!f) return;
  $('#fd-msg').textContent = '正在识别真题（拆材料和小题，再逐题标采分点，可能要一两分钟）…';
  const fd = new FormData(); fd.append('file', f);
  try {
    const d = await api('/api/find/upload', { method: 'POST', body: fd });
    $('#fd-msg').textContent = '';
    toast(`识别出 ${d.made.length} 道可练的小题` + (d.skipped.length ? `（${d.skipped.join('、')} 不属于找点训练，已跳过）` : ''));
    loadFindList(); loadFindTypes();
  } catch (e) { toast(e.message, true); $('#fd-msg').textContent = ''; }
  $('#fd-file').value = '';
};

/* ---- 做题：材料按句勾画 ---- */
async function openFindRun(pid) {
  fdPaper = null; fdPicked = new Set(); fdStep = 1; fdCheck = null;
  push({ view: 'findrun', title: '找点训练' });
  $('#fr-head').innerHTML = '<p class="empty">加载中…</p>';
  $('#fr-mat').innerHTML = ''; $('#fr-foot').innerHTML = '';
  try {
    fdPaper = await api('/api/find/paper/' + pid);
    frRender();
  } catch (e) { $('#fr-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

function frRender() {
  const p = fdPaper;
  $('#fr-head').innerHTML = `
    <div class="fr-step">
      <span class="${fdStep === 1 ? 'on' : 'done'}">① 找点</span>
      <span class="${fdStep === 2 ? 'on' : (fdStep > 2 ? 'done' : '')}">② 写点</span>
      <span class="${fdStep === 3 ? 'on' : ''}">③ 批改</span>
    </div>
    <div class="fr-stem">${esc(p.stem)}</div>
    <div class="fr-meta">${esc(p.type_name)} · ${p.full} 分 · ${p.word_min}~${p.word_max} 字
      · <b>共 ${p.n_points} 个采分点</b> · ${esc(p.source || '')}</div>`;
  frMat();
  frFoot();
}

function frMat() {
  const p = fdPaper;
  let html = '', lastP = -1;
  p.sents.forEach(s => {
    if (s.p !== lastP) { if (lastP >= 0) html += '</p>'; html += '<p class="fr-para">'; lastP = s.p; }
    if (s.head) { html += `<span class="fr-s fr-h">${esc(s.t)}</span>`; return; }
    const cls = ['fr-s'];
    if (fdPicked.has(s.i)) cls.push('on');
    if (fdCheck) {                               // 判完了：把对/错/漏直接标在原文上
      if (fdCheck.okSents.has(s.i)) cls.push('ok');
      else if (fdCheck.wrongSents.has(s.i)) cls.push('bad');
      else if (fdCheck.missSents.has(s.i)) cls.push('miss');
    }
    html += `<span class="${cls.join(' ')}" data-fs="${s.i}">${esc(s.t)}</span>`;
  });
  if (lastP >= 0) html += '</p>';
  $('#fr-mat').innerHTML = html;
}

// 勾画：点一句 = 选中/取消；按住拖过多句 = 连着选（鼠标和手写笔都走 pointer 事件）
$('#fr-mat').addEventListener('pointerdown', e => {
  if (fdStep !== 1) return;
  const s = e.target.closest('[data-fs]'); if (!s) return;
  const i = +s.dataset.fs;
  fdDrag = fdPicked.has(i) ? 'off' : 'on';       // 起手是选中的 → 这一拖都是取消
  frToggle(i, fdDrag === 'on');
  e.preventDefault();
});
$('#fr-mat').addEventListener('pointerover', e => {
  if (!fdDrag || fdStep !== 1) return;
  const s = e.target.closest('[data-fs]'); if (!s) return;
  frToggle(+s.dataset.fs, fdDrag === 'on');
});
document.addEventListener('pointerup', () => { fdDrag = null; });
function frToggle(i, on) {
  if (on) fdPicked.add(i); else fdPicked.delete(i);
  const el = document.querySelector(`[data-fs="${i}"]`);
  if (el) el.classList.toggle('on', on);
  const n = $('#fr-n'); if (n) n.textContent = fdPicked.size;
}

function frFoot() {
  const p = fdPaper;
  if (fdStep === 1) {
    $('#fr-foot').innerHTML = `
      <div class="fr-tip">🖍 在材料里<b>点句子</b>勾出你认为的要点（按住拖可以连选）。
        这一步<b>只找不写</b> —— 共 ${p.n_points} 个采分点，你勾了 <b id="fr-n">${fdPicked.size}</b> 句。</div>
      <button class="btn primary" id="fr-check">看看我找得对不对</button>`;
    $('#fr-check').onclick = frDoCheck;
    return;
  }
  if (fdStep === 2) {
    const picked = fdPaper.sents.filter(s => fdPicked.has(s.i));
    $('#fr-foot').innerHTML = `
      <div class="fr-tip">✍️ 照着<b>你勾到的（绿色）</b>写要点。要<b>概括</b>，不是抄原文；<b>分条写</b>。
        ${p.word_min}~${p.word_max} 字。</div>
      <div class="fr-picked">${picked.map(s => `<div>· ${esc(s.t)}</div>`).join('') || '<i>你没勾到任何要点</i>'}</div>
      <textarea id="fr-ans" placeholder="一、…\n二、…\n三、…"></textarea>
      <div class="fr-wc"><span id="fr-wc">0</span> / ${p.word_max} 字</div>
      <button class="btn primary" id="fr-grade">交给我批</button>`;
    $('#fr-ans').oninput = () => {
      $('#fr-wc').textContent = $('#fr-ans').value.replace(/\s/g, '').length;
    };
    $('#fr-grade').onclick = frDoGrade;
  }
}

async function frDoCheck() {
  if (!fdPicked.size) { toast('先在材料里勾几句', true); return; }
  const b = $('#fr-check'); b.disabled = true; b.textContent = '判定中…';
  try {
    const r = await api('/api/find/check', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paper_id: fdPaper.id, sents: [...fdPicked] }),
    });
    // 把判定结果落到句子上：找对=绿，找错=红，找漏=黄（漏的句子考生本来没勾，这里直接点出来）
    r.okSents = new Set(r.ok.flatMap(x => x.sents));
    r.wrongSents = new Set(r.wrong.map(x => x.i));
    r.missSents = new Set(r.missed.flatMap(x => x.sents));
    fdCheck = r;
    frMat();
    $('#fr-foot').innerHTML = `
      <div class="fr-res">
        <div class="fr-score">找到 <b>${r.found}</b> / ${r.total} 个采分点
          <span class="fr-acc${r.acc < 60 ? ' bad' : ''}">${r.acc}%</span></div>
        ${r.missed.length ? `<div class="fr-sec miss"><div class="fr-sec-t">❌ 找漏了 ${r.missed.length} 个</div>
          ${r.missed.map(x => `<div class="fr-item">
            <b>[${x.score} 分] ${esc(x.point)}</b>
            <div class="fr-ev" data-fsgo="${x.sents[0]}">↗ 就在这句：${esc(x.evidence.slice(0, 50))}…</div>
          </div>`).join('')}</div>` : ''}
        ${r.wrong.length ? `<div class="fr-sec bad"><div class="fr-sec-t">⚠️ 找错了 ${r.wrong.length} 处
            <i>（这些是干扰信息，不是采分点）</i></div>
          ${r.wrong.map(x => `<div class="fr-item"><div class="fr-ev" data-fsgo="${x.i}">↗ ${esc(x.t.slice(0, 50))}…</div></div>`).join('')}</div>` : ''}
        ${r.dup.length ? `<div class="fr-sec dup"><div class="fr-sec-t">🔁 找重了 ${r.dup.length} 处</div>
          ${r.dup.map(x => `<div class="fr-item"><b>${esc(x.point)}</b>
            <div class="fr-ev">这一个点你勾了 ${x.sents.length} 句 —— 材料里换了个说法而已，答案里只算一个点</div>
          </div>`).join('')}</div>` : ''}
        ${r.ok.length ? `<div class="fr-sec ok"><div class="fr-sec-t">✅ 找对了 ${r.ok.length} 个</div>
          ${r.ok.map(x => `<div class="fr-item"><b>[${x.score} 分] ${esc(x.point)}</b></div>`).join('')}</div>` : ''}
      </div>
      <div class="fr-acts">
        <button class="btn" id="fr-redo">🔄 重新找一遍</button>
        <button class="btn primary" id="fr-next">下一步：照着写点子 →</button>
      </div>`;
    $('#fr-redo').onclick = () => { fdCheck = null; fdPicked = new Set(); frMat(); frFoot(); };
    $('#fr-next').onclick = () => {
      // 漏掉的点也补进勾画（不然第二步照着写，注定还是漏）—— 但它们在原文里仍标成黄的
      fdCheck.missSents.forEach(i => fdPicked.add(i));
      fdCheck.wrongSents.forEach(i => fdPicked.delete(i));
      fdStep = 2; frRender();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    };
  } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = '看看我找得对不对'; }
}
$('#fr-foot').addEventListener('click', e => {
  const g = e.target.closest('[data-fsgo]');    // 点一下跳到原文那句
  if (!g) return;
  const el = document.querySelector(`[data-fs="${g.dataset.fsgo}"]`);
  if (el) {
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    el.classList.add('flash');
    setTimeout(() => el.classList.remove('flash'), 1400);
  }
});

async function frDoGrade() {
  const ans = $('#fr-ans').value.trim();
  if (ans.replace(/\s/g, '').length < 20) { toast('写太少了', true); return; }
  const b = $('#fr-grade'); b.disabled = true; b.textContent = '批改中…（约 20 秒）';
  try {
    const g = await api('/api/find/grade', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paper_id: fdPaper.id, answer: ans, sents: [...fdPicked] }),
    });
    fdStep = 3;
    const M = { full: ['✅', 'ok'], part: ['⚠️', 'part'], miss: ['❌', 'miss'] };
    $('#fr-head').innerHTML = `
      <div class="fr-step"><span class="done">① 找点</span><span class="done">② 写点</span><span class="on">③ 批改</span></div>
      <div class="fr-final"><b>${g.score}</b> / ${g.full} 分</div>`;
    $('#fr-mat').innerHTML = '';
    $('#fr-foot').innerHTML = `
      <div class="fr-res">
        <div class="fr-sec-t">逐个采分点</div>
        ${(g.items || []).map(it => {
          const m = M[it.got] || M.miss;
          return `<div class="fr-item fr-g ${m[1]}">
            <b>${m[0]} [${it.score} 分] ${esc(it.point || '')}</b>
            <div class="fr-gc">${esc(it.comment || '')}</div></div>`;
        }).join('')}
        ${(g.style || []).length ? `<div class="fr-sec bad"><div class="fr-sec-t">表述问题</div>
          ${g.style.map(s => `<div class="fr-item">· ${esc(s)}</div>`).join('')}</div>` : ''}
        ${g.advice ? `<div class="fr-adv">💡 ${esc(g.advice)}</div>` : ''}
      </div>
      <div class="fr-acts">
        <button class="btn primary" id="fr-again">🔄 再练这道</button>
        <button class="btn" id="fr-back">换一道</button>
      </div>`;
    $('#fr-again').onclick = () => openFindRun(fdPaper.id);
    $('#fr-back').onclick = () => { back(); loadFindList(); };
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = '交给我批'; }
}

/* ============= 专项练（行测六大板块）=============
   资料分析 / 判断推理 / 数量关系 —— 题型固定、有套路、拼速度，**题由程序生成**，答案由构造保证。
   常识判断 / 政治理论 / 言语理解 —— 考的是知识，构造不出来，**由 AI 按考试标准出题**；
     出好的题攒进题库（drill_bank），下次直接取，不用每次等十几秒。
   三档难度**真正改变题目**（不是贴个标签）；难度系数 = 预期得分率，做完告诉你比预期高还是低。
   两种模式：背题（选完即判 + 解析）/ 测试（做完交卷、服务端判分）。题量 5/10/15/20。
   每次做完**留一条完整记录**，可以回看每一题 —— 不是做完就丢。 */
let drBoard = '', drType = '', drItems = [], drIdx = 0, drAns = [], drSec = [], drT0 = 0, drTimer = 0;
let drLimit = 60, drLevel = 'mid', drN = 10, drMode = 'study', drToken = '', drCoef = 0.6, drLevels = [];

function openDrill(board) {
  drBoard = board;
  push({ view: 'drill', title: board + ' · 专项练' });
  loadDrillTypes();
}
async function loadDrillTypes() {
  const box = $('#dr-types');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api(`/api/drill/types?board=${encodeURIComponent(drBoard)}&level=${drLevel}`);
    drLimit = d.limit; drLevels = d.levels; drCoef = d.coef;
    $('#dr-intro').innerHTML = d.ai
      ? `这一块考的是<b>知识</b>，题由 AI 按考试标准出，<b>并且必须过第二个模型的独立核验</b>
         —— 两个模型答案不一致的题<b>不会发给你做</b>（实测能筛掉约 14%，其中有真的事实错误）。
         每题限时 ${d.limit} 秒。`
      : `这一块靠<b>练</b>不靠背：题型固定、有套路、拼速度。题由<b>程序生成</b>，答案由构造保证。每题限时 ${d.limit} 秒，做完给这一类的秒杀技巧。`;
    $('#dr-levels').innerHTML = d.levels.map(l =>
      `<button class="dr-lv${l.k === drLevel ? ' on' : ''}" data-drl="${l.k}">
         <b>${esc(l.name)}</b><span>${l.coef.toFixed(2)}</span></button>`).join('');
    drCoefTip();
    // 讲义里的「解题方法」章 —— 是方法不是题型，单独摆出来（做题时的秒杀技巧就出自这里）
    $('#dr-methods').innerHTML = (d.methods || []).length
      ? `<div class="dr-mth"><div class="dr-mth-t">📐 解题方法（讲义第一章）</div>
          ${d.methods.map(m => `<div class="dr-mth-i">· ${esc(m)}</div>`).join('')}</div>` : '';
    $('#dr-missing').innerHTML = d.missing
      ? `<div class="dr-miss">⚠️ ${esc(d.missing)}</div>` : '';
    box.innerHTML = d.types.map((t, i) => {
      const done = t.n > 0;
      const weak = done && t.acc < Math.round(drCoef * 100);   // 低于这个难度的预期得分率 = 薄弱
      return `<div class="dr-card${weak ? ' weak' : ''}" data-drt="${esc(t.type)}">
        <div class="dr-card-h">
          <b><span class="dr-no">${t.ord + 1}</span>${esc(t.type)}</b>
          ${done ? `<span class="dr-acc${weak ? ' bad' : ''}">${t.acc}%</span>` : '<span class="dr-new">没练过</span>'}
        </div>
        ${t.desc ? `<p class="dr-desc">${esc(t.desc)}</p>` : ''}
        <div class="dr-meta">
          <span class="dr-eng ${t.eng}">${t.eng === 'prog' ? '程序出题' : 'AI 出题'}</span>
          ${t.eng === 'ai' && t.bank_all
            ? `<span class="dr-bank" title="AI 出的题要过第二个模型的独立核验才发给你做；答案不一致的不出">
                 ✓ ${t.bank_ok} 道已核验${t.bank_all > t.bank_ok ? `（筛掉 ${t.bank_all - t.bank_ok}）` : ''}</span>` : ''}
          ${done ? `做过 ${t.n} 题 · 平均 ${t.sec} 秒${t.sec > drLimit ? '（超时）' : ''}` : `限时 ${drLimit} 秒/题`}</div>
      </div>`;
    }).join('') + `<div class="dr-card dr-all" data-drt=""><div class="dr-card-h"><b>🎲 混合练</b></div>
      <p class="dr-desc">所有题型随机出，模拟真实考场</p><div class="dr-meta">限时 ${drLimit} 秒/题</div></div>`;
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
function drCoefTip() {
  const l = drLevels.find(x => x.k === drLevel) || {};
  // 「难度系数」在公考里就是**得分率**。必须说清它是什么，不然「0.40」看着像分数
  $('#dr-coef').innerHTML = `<b>难度系数 ${(l.coef || 0).toFixed(2)}</b>
    <span>= 这个难度下<b>预期能做对 ${Math.round((l.coef || 0) * 100)}%</b>。${esc(l.desc || '')}。
    做完会告诉你<b>比预期高还是低</b>，心里有数。</span>`;
}
$('#dr-levels').addEventListener('click', e => {
  const b = e.target.closest('[data-drl]'); if (!b) return;
  drLevel = b.dataset.drl;
  loadDrillTypes();
});
$('#dr-ns').addEventListener('click', e => {
  const b = e.target.closest('[data-drn]'); if (!b) return;
  drN = +b.dataset.drn;
  document.querySelectorAll('#dr-ns .chip').forEach(x => x.classList.toggle('active', x === b));
});
$('#dr-modes').addEventListener('click', e => {
  const b = e.target.closest('[data-drm]'); if (!b) return;
  drMode = b.dataset.drm;
  document.querySelectorAll('#dr-modes .chip').forEach(x => x.classList.toggle('active', x === b));
  drModeTip();
});
function drModeTip() {
  $('#dr-modetip').textContent = drMode === 'exam'
    ? '答案不提前下发，全部做完交卷、由服务端判分，更像考试'
    : '每题选完立刻判、马上给解析和秒杀技巧 —— 边做边学';
}
drModeTip();
$('#dr-types').addEventListener('click', e => {
  const c = e.target.closest('[data-drt]'); if (!c) return;
  drStart(c.dataset.drt);
});
$('#dr-recs').onclick = () => openDrillRecs();

async function drStart(type) {
  drType = type;
  toast('出题中…');
  try {
    const d = await api('/api/drill/quiz', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ board: drBoard, type, n: drN, level: drLevel, exam: drMode === 'exam' }),
    });
    drItems = d.items; drLimit = d.limit; drCoef = d.coef; drToken = d.token || '';
    drIdx = 0; drAns = []; drSec = [];
    push({ view: 'drillrun', title: (type || '混合') + ' · 专项练' });
    drRender();
  } catch (e) { toast(e.message, true); }
}

function drRender() {
  clearInterval(drTimer);
  if (drIdx >= drItems.length) { drResult(); return; }
  const it = drItems[drIdx];
  const isFig = !!(it.figs && it.figs.seq);
  const lvName = (drLevels.find(x => x.k === drLevel) || {}).name || '';
  $('#dr-head').innerHTML = `
    <div class="dr-prog">第 <b>${drIdx + 1}</b> / ${drItems.length} 题
      <span class="dr-tag">${esc(it.qtype || '')}</span>
      <span class="dr-tag lv">${esc(lvName)}</span></div>
    <div class="dr-clock" id="dr-clock">0 秒</div>`;
  const chosen = drAns[drIdx];
  const opts = isFig
    ? it.figs.opts.map((svg, j) => `<button class="dt-opt dt-figo${chosen === DT_L[j] ? ' chosen' : ''}"
        data-dro="${DT_L[j]}"><span class="dt-figl">${DT_L[j]}</span>${svg}</button>`).join('')
    : (it.options || []).map((o, j) => `<button class="dt-opt${chosen === DT_L[j] ? ' chosen' : ''}"
        data-dro="${DT_L[j]}">${esc(o)}</button>`).join('');
  const seq = isFig ? `<div class="dt-seq">${it.figs.seq.join('')}<span class="dt-qm">?</span></div>` : '';
  _dtLastMat = '';                                    // 每题独立渲染材料，别被上一题的缓存吃掉
  // 测试模式要能翻回去改（考场就是这样），所以给上下题按钮；背题模式选完即判，不用
  const nav = drMode === 'exam' ? `<div class="dr-nav">
      <button class="btn" id="dr-prev" ${drIdx ? '' : 'disabled'}>← 上一题</button>
      <button class="btn primary" id="dr-nextq">${drIdx + 1 >= drItems.length ? '交卷看结果' : '下一题 →'}</button>
    </div>` : '';
  $('#dr-body').innerHTML = `<div class="dt-q">${dtMaterial(it.material, drIdx)}
    <div class="dt-qt">${esc(it.q)}</div>${seq}
    <div class="dt-opts${isFig ? ' dt-figs' : ''}">${opts}</div>
    <div id="dr-exp"></div>${nav}</div>`;
  if (drMode === 'exam') {
    $('#dr-prev').onclick = () => { drStopTimer(); drIdx--; drRender(); };
    $('#dr-nextq').onclick = () => { drStopTimer(); drIdx++; drRender(); };
  }
  drT0 = Date.now();
  drTimer = setInterval(() => {
    const s = Math.round((Date.now() - drT0) / 1000 + (drSec[drIdx] || 0));
    const el = $('#dr-clock'); if (!el) { clearInterval(drTimer); return; }
    el.textContent = s + ' 秒';
    el.classList.toggle('over', s > drLimit);        // 超时只是提醒，不打断（考场上超时也得做完）
  }, 500);
}
function drStopTimer() {
  clearInterval(drTimer);
  drSec[drIdx] = (drSec[drIdx] || 0) + (Date.now() - drT0) / 1000;
}

$('#dr-body').addEventListener('click', e => {
  const b = e.target.closest('[data-dro]');
  if (b) { drPick(b.dataset.dro); return; }
  if (e.target.closest('#dr-next')) { drIdx++; drRender(); }
});

function drPick(letter) {
  const it = drItems[drIdx];
  if (drMode === 'exam') {          // 测试模式：只记选择，不判、不给解析（答案本来也没下发到前端）
    drAns[drIdx] = letter;
    document.querySelectorAll('#dr-body [data-dro]').forEach(b =>
      b.classList.toggle('chosen', b.dataset.dro === letter));
    return;
  }
  if (drAns[drIdx] !== undefined) return;             // 背题模式：答过就不能改
  drStopTimer();
  const sec = drSec[drIdx];
  drAns[drIdx] = letter;
  const ok = letter === it.answer;
  document.querySelectorAll('#dr-body [data-dro]').forEach(b => {
    b.disabled = true;
    if (b.dataset.dro === it.answer) b.classList.add('correct');
    else if (b.dataset.dro === letter) b.classList.add('wrong');
  });
  const over = sec > drLimit;
  const bold = (t) => esc(t || '').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  $('#dr-exp').innerHTML = `
    <div class="dr-verdict ${ok ? 'ok' : 'no'}">${ok ? '✅ 对了' : '❌ 错了'}
      · 用时 <b class="${over ? 'over' : ''}">${sec.toFixed(0)} 秒</b>${over ? `（限时 ${drLimit} 秒，慢了）` : ''}
      · 正确答案 <b>${esc(it.answer)}</b></div>
    <div class="dt-exp">${bold(it.explain)}</div>
    ${it.tip ? `<div class="dr-tip">⚡ <b>秒杀技巧</b>：${bold(it.tip)}</div>` : ''}
    <button class="btn primary" id="dr-next">${drIdx + 1 >= drItems.length ? '看结果' : '下一题 →'}</button>`;
}

async function drResult() {
  drStopTimer();
  $('#dr-head').innerHTML = '';
  $('#dr-body').innerHTML = '<p class="empty">判分中…</p>';
  const answers = {}, seconds = {};
  drItems.forEach((_, i) => { answers[i] = drAns[i] || ''; seconds[i] = drSec[i] || 0; });
  const body = { board: drBoard, type: drType, level: drLevel, exam: drMode === 'exam', answers, seconds };
  if (drToken) body.token = drToken;      // 测试模式：题在服务端，前端手里根本没有答案
  else body.items = drItems;
  try {
    const r = await api('/api/drill/done', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const avg = drSec.reduce((a, b) => a + b, 0) / (drSec.length || 1);
    const slow = drSec.filter(s => s > drLimit).length;
    const pct = Math.round(r.acc * 100), exp = Math.round(r.coef * 100);
    const good = r.vs >= 0;
    $('#dr-body').innerHTML = `
      <div class="dr-done">
        <div class="dr-score">${r.ok} / ${r.total}</div>
        <div class="dr-vs ${good ? 'good' : 'bad'}">
          正确率 <b>${pct}%</b> · 这个难度预期 ${exp}%
          → <b>${good ? '高出' : '低了'} ${Math.abs(Math.round(r.vs * 100))} 个点</b>
        </div>
        <div class="dr-sub">平均用时 <b class="${avg > drLimit ? 'over' : ''}">${avg.toFixed(0)} 秒</b>
          ${slow ? `· 有 ${slow} 题超时（限时 ${drLimit} 秒）` : `· 都在 ${drLimit} 秒内 👍`}</div>
        ${r.wrong_added ? `<p class="dr-wq">错的 ${r.wrong_added} 题已自动进错题本</p>` : ''}
        <div class="dr-acts">
          <button class="btn primary" id="dr-again">🔄 再来 ${drN} 题</button>
          <button class="btn" id="dr-see">📋 看每题详情</button>
          <button class="btn" id="dr-back">换个题型</button>
        </div>
      </div>`;
    $('#dr-again').onclick = () => drStart(drType);
    $('#dr-see').onclick = () => openDrillRec(r.rid);
    $('#dr-back').onclick = () => { back(); loadDrillTypes(); };
  } catch (e) { $('#dr-body').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

/* ---- 做题记录：做过的都留着，可以回看每一题（不是做完就丢） ---- */
async function openDrillRecs() {
  push({ view: 'drillrec', title: '做题记录' });
  const box = $('#drr-list');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/drill/records');
    box.innerHTML = d.items.length ? d.items.map(x => {
      const acc = Math.round(100 * x.correct / (x.total || 1));
      const good = acc >= Math.round(x.coef * 100);      // 和这个难度的预期得分率比
      return `<div class="wr-day done" data-drrec="${x.id}">
        <div class="wr-day-d">${esc(x.board)}</div>
        <div class="wr-day-m">
          <b>${esc(x.qtype || '混合')}</b>
          <span class="wr-tag">${esc(x.level_name)}</span>
          <span class="wr-tag">${x.mode === 'exam' ? '测试' : '背题'}</span>
          <span class="dr-acc${good ? '' : ' bad'}">${x.correct}/${x.total} · ${acc}%</span>
          <span class="wr-w">${Math.round(x.seconds)} 秒 · ${esc((x.created_at || '').slice(5, 16))}</span>
        </div>
      </div>`;
    }).join('') : '<p class="empty">还没做过题。</p>';
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#drr-list').addEventListener('click', e => {
  const c = e.target.closest('[data-drrec]'); if (c) openDrillRec(+c.dataset.drrec);
});
async function openDrillRec(rid) {
  push({ view: 'drillrecd', title: '这次做的题' });
  $('#drd-head').innerHTML = '<p class="empty">加载中…</p>';
  $('#drd-body').innerHTML = '';
  try {
    const d = await api('/api/drill/record/' + rid);
    const acc = Math.round(100 * d.correct / (d.total || 1));
    $('#drd-head').innerHTML = `<div class="dr-prog">${esc(d.board)} · ${esc(d.qtype || '混合')}
      <span class="dr-tag lv">${esc(d.level)}</span></div>
      <div class="dr-clock">${d.correct}/${d.total} · ${acc}%</div>`;
    _dtLastMat = '';
    $('#drd-body').innerHTML = d.items.map((it, i) => {
      const r = d.answers[i] || {};
      const isFig = !!(it.figs && it.figs.seq);
      const cls = (L) => (L === it.answer ? ' correct' : (L === r.your ? ' wrong' : ''));
      const opts = isFig
        ? it.figs.opts.map((svg, j) => `<button class="dt-opt dt-figo${cls(DT_L[j])}" disabled>
            <span class="dt-figl">${DT_L[j]}</span>${svg}</button>`).join('')
        : (it.options || []).map((o, j) => `<button class="dt-opt${cls(DT_L[j])}" disabled>${esc(o)}</button>`).join('');
      return `<div class="dt-q">${dtMaterial(it.material, i)}
        <div class="dt-qt">${r.correct ? '✅' : '❌'} ${i + 1}. ${esc(it.q)}</div>
        ${isFig ? `<div class="dt-seq">${it.figs.seq.join('')}<span class="dt-qm">?</span></div>` : ''}
        <div class="dt-opts${isFig ? ' dt-figs' : ''}">${opts}</div>
        <div class="dt-exp"><b>正确答案 ${esc(it.answer)}</b>${r.your ? ` · 你选了 ${esc(r.your)}` : ' · 没作答'}
          ${it.explain ? ' · ' + esc(it.explain) : ''}</div>
      </div>`;
    }).join('');
  } catch (e) { $('#drd-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

/* ============= 成文：把素材真正写成一篇大作文 ============= */
let wrTab = 'daily', wrCur = null, wrPoll = 0;

function openWrite(tab) {
  wrTab = tab || 'daily';
  push({ view: 'write', title: '成文' });
  wrSwitch(wrTab);            // render() 只负责显隐视图，内容要自己拉
}
function wrSwitch(k) {
  wrTab = k;
  document.querySelectorAll('#wr-tabs .tk-tab').forEach(b => b.classList.toggle('active', b.dataset.wk === k));
  ['daily', 'compose', 'yingyong'].forEach(x => $('#wr-' + x).classList.toggle('hidden', x !== k));
  if (k === 'daily') loadWrDays();
  else if (k === 'compose') loadWrCompose();
  else if (k === 'yingyong') loadWrGw();
}

/* ---- 应用文：按「类别 → 文种」铺开，每个文种给「提纲 + 范文」两样 ----
   提纲**不是文种**，是一种呈现方式（框架式、要点式），任何文种都能套。
   先看提纲（这个文种由哪几块组成）再看范文（成品长什么样），才知道文章是怎么长出来的。
   第一次一键把所有文种各铺一份；之后就是针对同一文种换话题积累。 */
let gwSpec = null, gwType = '讲话稿', gwForm = 'full', yyPoll = 0;

async function loadWrGw() {
  if (!gwSpec) {
    try { gwSpec = await api('/api/write/gwspec'); } catch (e) { toast(e.message, true); return; }
  }
  $('#yy-types').innerHTML = gwSpec.doctypes.map(d =>
    `<button class="chip${d.k === gwType ? ' active' : ''}" data-gwt="${esc(d.k)}">${esc(d.k)}</button>`).join('');
  $('#yy-scenes').innerHTML = '<span class="gw-sug-t">常用：</span>' + gwSpec.scenes.map(s =>
    `<button class="chip tiny" data-gws="${esc(s)}">${esc(s)}</button>`).join('');
  gwFmt();
  loadYyCats();
}
function gwFmt() {
  const d = gwSpec.doctypes.find(x => x.k === gwType); if (!d) return;
  $('#yy-fmt').innerHTML = `<b>${esc(d.k)}</b>：${esc(d.d)}<br>
    <span class="gw-fmt-k">格式骨架</span>${esc(d.fmt)} · ${d.min}~${d.max} 字`;
}

async function loadYyCats() {
  const box = $('#yy-cats');
  box.innerHTML = box.innerHTML || '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/write/yylist');
    const miss = d.total * 2 - d.have_full - d.have_outline;
    const bt = $('#yy-batch');
    bt.classList.toggle('hidden', miss <= 0);
    bt.textContent = `⚡ 一键铺开所有文种（还差 ${miss} 篇）`;
    box.innerHTML = d.cats.map(c => `
      <div class="yy-cat">
        <div class="yy-cat-t">${esc(c.cat)}</div>
        ${c.doctypes.map(t => `
          <div class="yy-dt">
            <div class="yy-dt-h">
              <b>${esc(t.k)}</b><span class="yy-dt-d">${esc(t.d)}</span>
            </div>
            <div class="yy-dt-b">
              ${t.outline.length
                ? `<button class="yy-pill out" data-weid="${t.outline[0].id}">🧭 提纲</button>`
                : '<span class="yy-pill none">🧭 提纲 · 还没有</span>'}
              ${t.full.length
                ? t.full.map(f => `<button class="yy-pill" data-weid="${f.id}"
                    title="${esc(f.title || '')}">📄 ${esc(f.scene || f.title || '范文')}</button>`).join('')
                : '<span class="yy-pill none">📄 范文 · 还没有</span>'}
            </div>
          </div>`).join('')}
      </div>`).join('');
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

$('#yy-batch').onclick = async () => {
  if (!await appConfirm('给每个文种各写一份提纲和一篇范文（先提纲后范文）。要调不少次 AI，会在后台慢慢跑，可以先去干别的。')) return;
  try {
    const d = await api('/api/write/yingyong/batch', { method: 'POST' });
    yyWatch(d.task);
  } catch (e) { toast(e.message, true); }
};
function yyWatch(tid) {
  clearInterval(yyPoll);
  $('#yy-batch').disabled = true;
  const msg = $('#yy-bfmsg');
  yyPoll = setInterval(async () => {
    try {
      const t = await api('/api/write/task/' + tid);
      msg.textContent = `${t.message || ''}（${t.progress}/${t.total}）`;
      if (t.status === 'done' || t.status === 'error') {
        clearInterval(yyPoll); yyPoll = 0;
        $('#yy-batch').disabled = false;
        msg.textContent = t.message || '';
        loadYyCats();
        toast(t.status === 'done' ? '铺开完成' : t.message, t.status !== 'done');
      }
    } catch (_) { clearInterval(yyPoll); yyPoll = 0; $('#yy-batch').disabled = false; }
  }, 3000);
}

$('#wr-yingyong').addEventListener('click', e => {
  const t = e.target.closest('[data-gwt]');
  if (t) { gwType = t.dataset.gwt; loadWrGw(); return; }
  const f = e.target.closest('[data-yyf]');
  if (f) {
    gwForm = f.dataset.yyf;
    document.querySelectorAll('#yy-forms .chip').forEach(x => x.classList.toggle('active', x === f));
    return;
  }
  const s = e.target.closest('[data-gws]');
  if (s) { $('#yy-scene').value = s.dataset.gws; return; }
  const c = e.target.closest('[data-weid]');
  if (c) openWrited(+c.dataset.weid);
});
$('#yy-go').onclick = async () => {
  const scene = $('#yy-scene').value.trim();
  if (!scene) { toast('先说清楚就什么事发文', true); return; }
  const b = $('#yy-go'); b.disabled = true; b.textContent = '写作中…';
  try {
    const d = await api('/api/write/yingyong', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        doctype: gwType, scene, form: gwForm,
        role: $('#yy-role').value.trim(), audience: $('#yy-aud').value.trim(),
      }),
    });
    openWrited(d.id); loadYyCats();
  } catch (e) { toast(e.message, true); }
  b.disabled = false; b.textContent = '✍️ 写这一篇';
};

/* ---- 成文详情 ---- */
async function openWrited(id) {
  wrCur = null;
  push({ view: 'writed', title: '成文' });
  $('#wd-head').innerHTML = '<p class="empty">加载中…</p>';
  try {
    wrCur = await api('/api/write/' + id);
    renderWrited();
  } catch (e) { $('#wd-head').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
function renderWrited() {
  const d = wrCur; if (!d) return;
  const gw = d.mode === 'yingyong';           // 应用文：字数按文种走，提纲页签换成「格式批注」
  const sp = d.spec || {};
  const isOut = gw && sp.form === 'outline'; // 提纲：框架式要点式，字数本来就少，不卡字数
  const ok = isOut ? true : (gw ? d.words >= 250 : (d.words >= 1000 && d.words <= 1300));
  document.querySelector('#wd-tabs [data-wd=text]').textContent = isOut ? '🧭 提纲' : '📄 全文';
  document.querySelector('#wd-tabs [data-wd=outline]').textContent =
    isOut ? '📐 每块怎么写' : (gw ? '📐 格式批注' : '🧭 提纲');
  document.querySelector('#wd-tabs [data-wd=used]').textContent = gw ? '📎 用到的规范表述' : '📎 用到的素材';
  $('#wd-head').innerHTML = `
    <h2 class="wd-title">${esc(d.title || '')}</h2>
    <div class="wd-meta">
      <span class="wr-tag">${esc(d.topic || '')}</span>
      <span class="wd-w ${ok ? '' : 'bad'}">${d.words} 字${ok ? '' : '（字数不达标）'}</span>
      <span class="wd-src">${gw
        ? (isOut ? '🧭 提纲纲要' : '📄 范文') + ' · ' + esc(sp.scene || '')
          + (sp.role ? ' · ' + esc(sp.role) : '')
        : (d.mode === 'daily' ? '📅 ' + fmtDay(d.date) + ' 的素材' : '🧩 综合应用')}</span>
      <span class="wd-used-n">📎 ${(d.used || []).length} 条${gw ? '规范表述' : '素材'}</span>
    </div>
    ${d.note ? `<p class="wd-note">💡 ${esc(d.note)}</p>` : ''}`;
  $('#wd-text').innerHTML = isOut
    ? `<pre class="wd-outline">${esc(d.content || '')}</pre>`   // 提纲有缩进和「· 」，原样保留
    : (d.content || '').split('\n').filter(x => x.trim())
        .map(p => `<p>${esc(p.trim())}</p>`).join('');
  const groups = {};
  (d.used || []).forEach(u => { (groups[u.sec] = groups[u.sec] || []).push(u.text); });
  $('#wd-used').innerHTML = Object.keys(groups).length ? Object.entries(groups).map(([k, v]) => `
    <div class="wd-ug"><div class="wd-ug-t">${esc(k)}</div>
      ${v.map(t => `<div class="wd-ui">${esc(t)}</div>`).join('')}</div>`).join('')
    : `<p class="empty">这篇没能核对出用了哪些${gw ? '规范表述' : '素材'}。</p>`;
  if (gw) {
    // 应用文的重点全在这儿：每段是哪个部件、为什么这么写。看完才知道怎么学。
    $('#wd-outline').innerHTML = (d.outline || []).length
      ? d.outline.map(s => `<div class="gw-seg">
          <div class="gw-seg-p">${esc(s.part || '')}</div>
          <div class="gw-seg-t">${esc(s.text || '')}</div>
          <div class="gw-seg-w">💡 ${esc(s.why || '')}</div>
        </div>`).join('')
      : '<p class="empty">没有批注。</p>';
  } else {
    $('#wd-outline').innerHTML = (d.outline || []).length
      ? `<ol class="wd-ol">${d.outline.map(x => `<li>${esc(x)}</li>`).join('')}</ol>`
      : '<p class="empty">没有提纲。</p>';
  }
}
$('#wd-tabs').addEventListener('click', e => {
  const b = e.target.closest('.tk-tab'); if (!b) return;
  document.querySelectorAll('#wd-tabs .tk-tab').forEach(x => x.classList.toggle('active', x === b));
  ['text', 'used', 'outline'].forEach(k => $('#wd-' + k).classList.toggle('hidden', k !== b.dataset.wd));
});

/* ============= 议论文 · 素材积累 / 衔接表达（与微信 08:00 推送同源） ============= */
let scKind = '全部';
const SC_COLOR = { '人物事例': '#b23b2e', '具体事例': '#0f766e', '理论论据': '#7a5cc0', '衔接表达': '#c2671f' };
async function loadSucai() {
  document.querySelectorAll('#sc-kinds .chip').forEach(x => x.classList.toggle('active', x.dataset.sk === scKind));
  $('#sc-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/sucai?kind=' + encodeURIComponent(scKind));
    document.querySelectorAll('#sc-kinds .chip').forEach(x => {
      if (x.dataset.sk === '全部') return;
      const n = d.counts[x.dataset.sk]; x.textContent = x.dataset.sk + (n ? ' ' + n : '');
    });
    if (!d.items.length) { $('#sc-list').innerHTML = '<p class="empty">还没有素材，每天 08:00 自动生成～</p>'; return; }
    let lastDate = '';
    $('#sc-list').innerHTML = d.items.map(it => {
      const head = it.date !== lastDate ? `<div class="sc-day">🗓 ${fmtDay(it.date)}</div>` : '';
      lastDate = it.date;
      const col = SC_COLOR[it.kind] || '#666';
      const isLj = it.kind === '衔接表达';
      const exHtml = it.example
        ? `<div class="sc-exwrap"><div class="sc-ex"><b>例句</b> ${esc(it.example)}</div>
             <button class="sc-exbtn regen" data-scex="${it.id}" data-force="1">🔄 换个例句</button></div>`
        : (isLj ? `<button class="sc-exbtn" data-scex="${it.id}">✍️ AI 造个例句</button>` : '');
      return head + `<div class="gk-card" data-scid="${it.id}">
        <div class="gk-head"><span class="poly-badge" style="background:${col}">${esc(it.kind)}</span>
          ${it.topic ? `<span class="gk-topic">${esc(it.topic)}</span>` : ''}</div>
        <div class="sc-body">${emKey(it.content)}</div>
        ${exHtml}
      </div>`;
    }).join('');
  } catch (e) { $('#sc-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#sc-list').addEventListener('click', async e => {
  const b = e.target.closest('[data-scex]'); if (!b) return;
  const force = b.dataset.force === '1';
  const label = b.textContent;
  b.disabled = true; b.textContent = force ? '换句中…' : 'AI 造句中…';
  try {
    const d = await api('/api/sucai/' + b.dataset.scex + '/example', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force })
    });
    if (force) {                    // 原地替换例句文本，按钮留着可再换
      const ex = b.parentElement.querySelector('.sc-ex');
      if (ex) ex.innerHTML = `<b>例句</b> ${esc(d.example)}`;
      b.disabled = false; b.textContent = label;
    } else {
      b.outerHTML = `<div class="sc-exwrap"><div class="sc-ex"><b>例句</b> ${esc(d.example)}</div>
        <button class="sc-exbtn regen" data-scex="${b.dataset.scex}" data-force="1">🔄 换个例句</button></div>`;
    }
  } catch (err) { toast(err.message, true); b.disabled = false; b.textContent = label; }
});
function openSucai(kind) {
  scKind = kind || '全部';
  push({ view: 'sucai', title: scKind === '衔接表达' ? '衔接表达' : '素材积累' });
  loadSucai();
}
$('#sc-kinds').addEventListener('click', e => {
  const c = e.target.closest('[data-sk]'); if (!c) return;
  scKind = c.dataset.sk; loadSucai();
});

/* ============= 任务清单（每日任务 + 互监待办） ============= */
function openTasks() { push({ view: 'tasks', title: '任务清单' }); tkSwitch('plan'); }
function tkSwitch(t) {
  // 必须限定在本视图内：.tk-tab 这个类名被范文/批改/复习那几组页签复用，
  // 全局 querySelectorAll 会把它们的高亮一起清掉
  document.querySelectorAll('#view-tasks .tk-tab').forEach(x => x.classList.toggle('active', x.dataset.tkt === t));
  ['plan', 'daily', 'shared'].forEach(k => $('#tk-' + k).classList.toggle('hidden', k !== t));
  if (t === 'plan') loadPlan(); else if (t === 'daily') loadDaily(); else loadShared();
}
$('#view-tasks').addEventListener('click', e => {
  const tab = e.target.closest('[data-tkt]'); if (tab) tkSwitch(tab.dataset.tkt);
});

/* ================= 备考规划：AI 按真实学情排当天计划 ================= */
const PL_MOD_COLOR = {
  '复习': '#12b886', '错题': '#c0392b', '申论': '#c92a2a', '常识判断': '#e8590c',
  '言语理解': '#2b6fd6', '数量关系': '#7a5cc0', '资料分析': '#0b7285', '判断推理': '#5b6cf0',
  '政治理论': '#b7791f',
};
let plProfile = null, plEditing = false;

/* ---------- 40 天冲刺路线：今天第几天、什么阶段、今日定额、正确率目标 ---------- */
let plRoadOpen = false;
function renderRoadmap(rm, prof) {
  const box = $('#pl-road');
  if (!rm || (!rm.phase && !rm.over)) {           // 没开启（或还没到开始日）
    box.innerHTML = `<div class="plr-off">
      <div class="plr-off-t">🚀 40 天冲刺路线</div>
      <div class="plr-off-d">对标「140 分」强度，但按 <b>6 天推进 + 第 7 天复盘日</b> 排，能扛完全程。
        分三段：打牢根基(1-12) → 专项拔高(13-28) → 套题强化(29-40)；
        每天给你行测题量定额、申论安排、正确率目标，积累类任务直接用 App 里现成的内容。</div>
      <button class="btn primary" id="plr-start">开启 40 天冲刺</button>
    </div>`;
    return;
  }
  if (rm.over) {
    box.innerHTML = `<div class="plr-off">
      <div class="plr-off-t">🏁 40 天冲刺已走完（第 ${rm.day} 天）</div>
      <div class="plr-off-d">${esc(rm.data.after || '')}</div>
      <button class="btn primary" id="plr-start">再开一轮</button>
    </div>`;
    return;
  }
  const ph = rm.phase, dd = rm.data;
  const pct = Math.round(rm.day / rm.days * 100);
  const quota = Object.entries(ph.quota).map(([k, v]) =>
    `<span class="plr-q"><b>${v}</b> ${esc(k)}</span>`).join('');
  const acc = Object.entries(ph.accuracy).map(([k, v]) =>
    `<tr><td>${esc(k)}</td><td><b>${esc(v)}</b></td></tr>`).join('');
  box.innerHTML = `
    <div class="plr-top">
      <span class="plr-day">第 <b>${rm.day}</b> / ${rm.days} 天</span>
      <span class="plr-ph">${esc(ph.key)} · ${esc(ph.name)}</span>
      ${rm.review_day ? '<span class="plr-rv">★ 今天是复盘日</span>' : ''}
      <button class="plr-more" id="plr-more">${plRoadOpen ? '收起' : '看路线'}</button>
    </div>
    <div class="plr-bar"><i style="width:${pct}%"></i></div>
    <div class="plr-focus">${esc(ph.focus)}</div>
    ${rm.review_day ? `<div class="plr-tip">上午一套行测限时套题（严格 120 分钟）→ 下午全套订正 + 错因归因 → 晚上错题过筛，然后<b>休半天</b>。今天别堆新知识。</div>` : ''}
    <div class="plr-quota"><span class="plr-qt">今日行测定额</span>${quota}</div>
    <div class="plr-sl">📝 申论：${esc(ph.shenlun)}</div>
    <div class="plr-detail ${plRoadOpen ? '' : 'hidden'}">
      <div class="plr-sec">🎯 本阶段正确率目标</div>
      <table class="plr-tb">${acc}</table>
      <div class="plr-sec">📌 模块优先级</div>
      <div class="plr-p">${esc(dd.priority || '')}<div class="plr-why">${esc(dd.priority_why || '')}</div></div>
      <div class="plr-sec">🔁 本阶段每周要做到</div>
      <ul class="plr-ul">${(ph.weekly || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
      <div class="plr-sec">📚 每日固定动作（用 App 现成内容）</div>
      <ul class="plr-ul">${(dd.fixed || []).map(x =>
        `<li>${esc(x.t)}${x.link ? ` <i class="pl-go" data-plgo="${esc(x.link)}">去做 ›</i>` : ''}
          <span class="plr-note">${esc(x.note || '')}</span></li>`).join('')}</ul>
      <div class="plr-sec">⏰ 节奏</div>
      <div class="plr-p">${esc(dd.rhythm || '')}</div>
      <div class="plr-sec">🧱 纪律（原贴的 140 分强度，挑能长期执行的）</div>
      <ul class="plr-ul">${(dd.discipline || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
      <div class="plr-sec">🏁 阶段产出</div>
      <div class="plr-p">${esc(ph.output || '')}</div>
      <div class="plr-sec">➡️ 40 天之后</div>
      <div class="plr-p">${esc(dd.after || '')}</div>
      <button class="btn tiny plr-stop" id="plr-stop">结束这轮冲刺</button>
    </div>`;
  if (prof && prof.minutes < 300) {
    box.insertAdjacentHTML('beforeend',
      `<div class="plr-warn">你的「每天可学」只填了 ${prof.minutes} 分钟，这套定额是按 6~8 小时排的。
        建议去「⚙️ 备考信息」改成 <b>420</b> 分钟左右，规划助手才会把任务排够。</div>`);
  }
}
$('#pl-road').addEventListener('click', async e => {
  if (e.target.closest('#plr-more')) { plRoadOpen = !plRoadOpen; loadPlan(); return; }
  const go = e.target.closest('[data-plgo]');
  if (go) { ntfGo(go.dataset.plgo); return; }
  if (e.target.closest('#plr-start')) {
    const mins = (plProfile && plProfile.minutes) || 0;
    const ok = await appConfirm(
      '开启 40 天冲刺：从今天算第 1 天，分三段（根基 12 天 → 专项 16 天 → 套题 12 天），'
      + '每 7 天有一个复盘日。规划助手以后会按当天的定额和正确率目标排任务。'
      + (mins < 300 ? '\n\n你说全天有 6~8 小时，我顺便把「每天可学」设成 420 分钟，可以吗？' : ''),
      { title: '40 天冲刺路线', okText: '开始' });
    if (!ok) return;
    try {
      await api('/api/plan/roadmap', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mins < 300 ? { minutes: 420 } : {}),
      });
      toast('40 天冲刺已开启，去让规划助手排今天的计划');
      loadPlan();
    } catch (er) { toast(er.message, true); }
    return;
  }
  if (e.target.closest('#plr-stop')) {
    if (!await appConfirm('结束这轮 40 天冲刺？已排的计划不会删，只是规划助手不再按路线图排任务。',
      { title: '结束冲刺', okText: '结束' })) return;
    try { await api('/api/plan/roadmap', { method: 'DELETE' }); toast('已结束'); loadPlan(); }
    catch (er) { toast(er.message, true); }
  }
});

async function loadPlan() {
  try {
    const d = await api('/api/plan/today');
    plProfile = d.profile;
    const has = !!plProfile;
    if (has) renderPlan(d);
    if (plEditing) return;          // 用户正在改备考信息，别把设置页收起来
    $('#pl-setup').classList.toggle('hidden', has);
    $('#pl-main').classList.toggle('hidden', !has);
    if (!has) await fillPlanExams();
  } catch (e) { toast(e.message, true); }
}
async function fillPlanExams() {
  try {
    const d = await api('/api/plan/profile');
    $('#pl-exam').innerHTML = d.exams.map(x => `<option>${esc(x)}</option>`).join('');
    if (d.profile) {
      $('#pl-exam').value = d.profile.exam || '';
      $('#pl-date').value = d.profile.exam_date || '';
      $('#pl-min').value = d.profile.minutes || 120;
      $('#pl-weak').value = d.profile.weak || '';
      $('#pl-note').value = d.profile.note || '';
    }
  } catch (_) {}
}
function renderPlan(d) {
  const p = d.profile;
  const st = d.study || { streak: 0, total: 0 };
  $('#pl-head').innerHTML = `<div class="pl-days">${esc(p.exam || '备考规划')}</div>
    <div class="pl-meta">今天可学 ${p.minutes} 分钟${p.weak ? ' · 薄弱：' + esc(p.weak) : ''}</div>
    <div class="pl-streak">🔥 连续学习 <b>${st.streak}</b> 天 · 累计 <b>${st.total}</b> 天</div>`;
  renderRoadmap(d.roadmap, p);

  if (d.summary) {
    $('#pl-summary').innerHTML = `💡 ${esc(d.summary)}`;
    $('#pl-summary').classList.remove('hidden');
  } else $('#pl-summary').classList.add('hidden');

  $('#pl-prog').textContent = d.total
    ? `今日进度 ${d.done_n} / ${d.total} · ${d.minutes_done} / ${d.minutes_total} 分钟${d.done_n === d.total ? ' 🎉 全部完成！' : ''}`
    : '';

  $('#pl-list').innerHTML = d.items.length ? d.items.map(it => {
    const col = PL_MOD_COLOR[it.module] || '#6b7280';
    return `<div class="tk-item pl-item ${it.done ? 'done' : ''}" data-pl="${it.id}">
      <span class="tk-check">${it.done ? '✓' : ''}</span>
      <span class="tk-text">
        <span class="pl-title">${esc(it.title)}</span>
        <span class="pl-tags">
          ${it.module ? `<i class="pl-mod" style="background:${col}">${esc(it.module)}</i>` : ''}
          <i class="pl-min">${it.minutes} 分钟</i>
          ${it.link ? `<i class="pl-go" data-plgo="${esc(it.link)}">去做 ›</i>` : ''}
        </span>
        ${it.reason ? `<span class="tk-who">${esc(it.reason)}</span>` : ''}
      </span>
      <button class="tk-del" data-pldel="${it.id}">🗑</button>
    </div>`;
  }).join('') : '<p class="empty">今天还没有计划。点下面的按钮，规划助手会看着你的复习进度和错题给你排一份。</p>';
}
// 备考信息：记下打开时的原值，用来判断"有没有改过" + 撤回
let plFormBase = null;
function plReadForm() {
  return {
    exam: $('#pl-exam').value, exam_date: $('#pl-date').value,
    minutes: +$('#pl-min').value || 120,
    weak: $('#pl-weak').value.trim(), note: $('#pl-note').value.trim(),
  };
}
function plWriteForm(v) {
  if (!v) return;
  $('#pl-exam').value = v.exam || ''; $('#pl-date').value = v.exam_date || '';
  $('#pl-min').value = v.minutes || 120; $('#pl-weak').value = v.weak || ''; $('#pl-note').value = v.note || '';
  plSyncUndo();
}
function plDirty() { return plFormBase && JSON.stringify(plReadForm()) !== JSON.stringify(plFormBase); }
function plSyncUndo() { const u = $('#pl-undo'); if (u) u.hidden = !plDirty(); }
['pl-exam', 'pl-date', 'pl-min', 'pl-weak', 'pl-note'].forEach(id =>
  $('#' + id).addEventListener('input', plSyncUndo));

async function plSave() {
  try {
    const d = await api('/api/plan/profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(plReadForm()) });
    plEditing = false; plFormBase = null;
    toast('已保存');
    return true;
  } catch (e) { toast(e.message, true); return false; }
}
$('#pl-save').onclick = async () => { if (await plSave()) loadPlan(); };
$('#pl-edit').onclick = async () => {
  plEditing = true;
  await fillPlanExams();
  plFormBase = plReadForm();      // 记下原值
  $('#pl-back').hidden = !plProfile;   // 已有档案才有"上一页"可回
  $('#pl-undo').hidden = true;
  $('#pl-setup').classList.remove('hidden');
  $('#pl-main').classList.add('hidden');
};
$('#pl-undo').onclick = () => { plWriteForm(plFormBase); toast('已撤回修改'); };
// 返回：改过就问，保存 / 不保存 / 继续编辑
async function plLeaveSetup() {
  if (!plProfile) return;   // 首次填写没有"上一页"
  if (plDirty()) {
    const r = await appConfirm('备考信息有未保存的修改，怎么处理？',
      { title: '未保存的修改', okText: '保存并返回', altText: '不保存', okVal: 'save' });
    if (r === false) return;                 // 取消 = 继续编辑
    if (r === 'save') { if (!(await plSave())) return; }
    // r === 'alt'（不保存）：直接丢弃
  }
  plEditing = false; plFormBase = null;
  loadPlan();
}
$('#pl-back').onclick = plLeaveSetup;
$('#pl-gen').onclick = async () => {
  const b = $('#pl-gen');
  b.disabled = true; b.textContent = '规划助手思考中…';
  try {
    const d = await api('/api/plan/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    plProfile = d.profile;
    renderPlan(d);
    toast('已排好 ' + d.total + ' 条');
  } catch (e) { toast(e.message, true); }
  b.disabled = false; b.textContent = '✨ 让规划助手排今天的计划';
};
$('#pl-add').onclick = async () => {
  const v = $('#pl-in').value.trim(); if (!v) return;
  try {
    await api('/api/plan/item', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: v }) });
    $('#pl-in').value = ''; loadPlan();
  } catch (e) { toast(e.message, true); }
};
$('#pl-in').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') $('#pl-add').click(); });
$('#pl-list').addEventListener('click', async e => {
  const go = e.target.closest('[data-plgo]');
  if (go) { e.stopPropagation(); ntfGo(go.dataset.plgo); return; }   // 复用消息中心那套跳转
  const del = e.target.closest('[data-pldel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('删除这条计划？'))) return;
    try { await api('/api/plan/' + del.dataset.pldel, { method: 'DELETE' }); loadPlan(); }
    catch (er) { toast(er.message, true); }
    return;
  }
  const it = e.target.closest('[data-pl]'); if (!it) return;
  try { await api('/api/plan/' + it.dataset.pl + '/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); loadPlan(); }
  catch (er) { toast(er.message, true); }
});

/* ---------------- 备考计划记录 + 进度分析 ---------------- */
$('#pl-hist').onclick = () => openPlanLog();
$('#pl-analyze').onclick = () => openPlanLog(true);
function openPlanLog(runAnalyze) {
  push({ view: 'planlog', title: '计划记录' });
  $('#plh-analysis').classList.add('hidden'); $('#plh-analysis').innerHTML = '';
  loadPlanLog();
  if (runAnalyze) setTimeout(plhAnalyze, 200);
}
function plItemsHtml(items, checkable, pid) {
  return items.map(it => {
    const col = PL_MOD_COLOR[it.module] || '#6b7280';
    return `<div class="plh-item ${it.done ? 'done' : ''}">
      <span class="plh-dot">${it.done ? '✓' : ''}</span>
      <span class="plh-itxt"><span class="plh-title">${esc(it.title)}</span>
        <span class="pl-tags">${it.module ? `<i class="pl-mod" style="background:${col}">${esc(it.module)}</i>` : ''}<i class="pl-min">${it.minutes || 0} 分钟</i></span>
      </span></div>`;
  }).join('');
}
async function loadPlanLog() {
  $('#plh-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/plan/history');
    if (!d.days.length) { $('#plh-list').innerHTML = '<p class="empty">还没有计划记录。让规划助手排几天计划，这里就会留下每天的完成情况。</p>'; return; }
    $('#plh-list').innerHTML = d.days.map(day => {
      const arch = (day.archived || []).map(a => `
        <details class="plh-arch">
          <summary>${a.summary && a.summary.indexOf('【找回】') === 0 ? '🛟 找回的上一版' : '🕓 旧版本'} · ${esc((a.created_at || '').slice(5, 16))} · ${a.total} 条 / ${a.minutes_total} 分钟
            ${day.is_today ? `<button class="plh-restore" data-restore="${a.id}">恢复为今天</button>` : ''}</summary>
          ${a.summary ? `<div class="plh-sum">💡 ${esc(a.summary.replace('【找回】', ''))}</div>` : ''}
          ${plItemsHtml(a.items || [])}
        </details>`).join('');
      return `<div class="plh-day">
        <div class="plh-dhead"><b>${esc(day.date)}</b>${day.is_today ? ' <span class="plh-today">今天</span>' : ''}
          <span class="plh-prog">${day.total ? `完成 ${day.done_n}/${day.total} · ${day.minutes_done}/${day.minutes_total} 分钟` : '当天无计划'}</span></div>
        ${day.total ? plItemsHtml(day.items) : ''}
        ${arch}
      </div>`;
    }).join('');
  } catch (e) { $('#plh-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#plh-list').addEventListener('click', async e => {
  const r = e.target.closest('[data-restore]'); if (!r) return;
  e.preventDefault();
  if (!(await appConfirm('把这一版恢复成今天的计划？当前这版会先存进历史。'))) return;
  try { await api('/api/plan/restore/' + r.dataset.restore, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); toast('已恢复'); loadPlanLog(); }
  catch (er) { toast(er.message, true); }
});
$('#plh-analyze-btn').onclick = plhAnalyze;
async function plhAnalyze() {
  const box = $('#plh-analysis'); const btn = $('#plh-analyze-btn');
  box.classList.remove('hidden');
  box.innerHTML = '<p class="empty">规划助手正在翻你的计划记录…</p>';
  btn.disabled = true;
  try {
    const d = await api('/api/plan/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const sec = (title, arr, cls) => arr && arr.length ? `<div class="plh-sec ${cls}"><h4>${title}</h4><ul>${arr.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>` : '';
    box.innerHTML = `
      <div class="plh-ov">${esc(d.overview || '')}</div>
      <div class="plh-stat">近 ${d.days} 天 · 共 ${d.total} 条 · 完成 ${d.done} 条</div>
      ${sec('✅ 坚持得不错', d.keep, 'keep')}
      ${sec('⚠️ 被冷落 / 长期没安排', d.neglected, 'neg')}
      ${sec('👉 接下来建议', d.suggestions, 'sug')}`;
  } catch (e) { box.innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
  btn.disabled = false;
}

/* ---------------- 每日巩固测试（按当天学的内容 AI 出小测） ---------------- */
$('#dt-open').onclick = () => openDtest();
function openDtest() { push({ view: 'dtest', title: '巩固测试' }); loadDtest(); }
let dtItems = [], dtChosen = {}, dtRevealed = {}, dtSubmitted = false, dtResults = null;
// 背题模式 study：做一题立刻显示答案；测试模式 test：答案不下发，交卷才服务端判分
let dtMode = localStorage.getItem('dtMode') === 'test' ? 'test' : 'study';
let dtCount = (+localStorage.getItem('dtCount') === 15) ? 15 : 10;   // 题量 10 / 15
const DT_L = ['A', 'B', 'C', 'D', 'E', 'F'];
function dtIsTest() { return dtMode === 'test'; }
function dtRevealedAt(i) { return dtIsTest() ? dtSubmitted : !!dtRevealed[i]; }
function dtModeBar() {
  return `<div class="dt-bar">
    <div class="dt-modes">
      <button class="dt-mbtn ${dtMode === 'study' ? 'on' : ''}" data-dtm="study">📖 背题模式</button>
      <button class="dt-mbtn ${dtMode === 'test' ? 'on' : ''}" data-dtm="test">📝 测试模式</button>
    </div>
    <div class="dt-mhint">${dtMode === 'study'
      ? '做一题立刻显示这题答案与解析，边做边记'
      : '答案不提前下发，全部做完交卷、由服务端判分，更像考试'}</div>
    <div class="dt-count">题量：
      <button class="dt-cbtn ${dtCount === 10 ? 'on' : ''}" data-dtc="10">10 题</button>
      <button class="dt-cbtn ${dtCount === 15 ? 'on' : ''}" data-dtc="15">15 题</button></div>
    <button class="pl-link-btn" id="dt-records">📋 测试记录</button>
  </div>`;
}
async function loadDtest() {
  $('#dt-body').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/dtest' + (dtIsTest() ? '?exam=1' : ''));
    dtItems = d.items || []; dtChosen = {}; dtRevealed = {}; dtSubmitted = false; dtResults = null;
    if (!dtItems.length) {
      $('#dt-body').innerHTML = dtModeBar() +
        `<div class="dt-empty">今天还没生成测试。选好模式和题量，AI 会按你今天学的内容出题。</div>
        <button class="btn primary" id="dt-gen">✨ 生成今日巩固测试</button>`;
      $('#dt-gen').onclick = () => dtGen(false);
      bindBar();
      return;
    }
    renderDtest();
  } catch (e) { $('#dt-body').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function bindBar() {
  const rec = $('#dt-records'); if (rec) rec.onclick = openDtRecords;
  document.querySelectorAll('[data-dtm]').forEach(b => b.onclick = async () => {
    const m = b.dataset.dtm; if (m === dtMode) return;
    dtMode = m; localStorage.setItem('dtMode', m);
    // 切换模式：同一套题、保留你的作答，只改「何时揭晓答案」，不重新出题、不清空
    if (dtSubmitted || !dtItems.length) { loadDtest(); return; }
    if (m === 'study') {
      // 背题模式要用到答案；若当前这套没带答案（从测试模式来的），重新拉同一套带答案的
      if (dtItems[0] && dtItems[0].answer === undefined) {
        try { const d = await api('/api/dtest'); if ((d.items || []).length === dtItems.length) dtItems = d.items; } catch (_) {}
      }
      dtRevealed = {}; Object.keys(dtChosen).forEach(i => dtRevealed[i] = true);  // 已答的直接揭晓
    } else {
      dtRevealed = {};   // 测试模式：收起逐题揭晓，作答保留，交卷时统一判分
    }
    renderDtest();
  });
  document.querySelectorAll('[data-dtc]').forEach(b => b.onclick = async () => {
    const n = +b.dataset.dtc; if (n === dtCount) return;
    if (dtItems.length && !dtSubmitted) {
      if (!(await appConfirm('换成 ' + n + ' 题需要重新出题，当前作答会清空。'))) return;
      dtCount = n; localStorage.setItem('dtCount', n); dtGen(true);
    } else {
      dtCount = n; localStorage.setItem('dtCount', n);
      document.querySelectorAll('[data-dtc]').forEach(x => x.classList.toggle('on', +x.dataset.dtc === dtCount));
    }
  });
}
async function dtGen(force) {
  $('#dt-body').innerHTML = `<p class="empty">AI 正在按你今天学的内容出 ${dtCount} 道题，稍等…</p>`;
  try {
    const d = await api('/api/dtest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: !!force, exam: dtIsTest(), count: dtCount }) });
    dtItems = d.items || []; dtChosen = {}; dtRevealed = {}; dtSubmitted = false; dtResults = null;
    renderDtest();
  } catch (e) {
    $('#dt-body').innerHTML = `<div class="dt-empty">${esc(e.message)}</div><button class="btn" id="dt-retry">重试</button>`;
    $('#dt-retry').onclick = () => dtGen(force);
  }
}
// 答案来源：背题模式在 item 里（已下发）；测试模式交卷后在 dtResults 里
function dtAns(i) { return dtResults ? (dtResults[i] || {}).answer : (dtItems[i].answer || '').toUpperCase(); }
function dtExp(i) { return dtResults ? (dtResults[i] || {}) : dtItems[i]; }
function dtScore() {
  if (dtResults) return dtResults.reduce((n, r) => n + (r.correct ? 1 : 0), 0);
  return dtItems.reduce((n, it, i) => n + (dtChosen[i] === (it.answer || '').toUpperCase() ? 1 : 0), 0);
}
/* ---------- 资料分析的材料：表格 / 柱状图 / 折线图 / 饼图（内联 SVG，无外部库） ----------
   颜色用 CSS 变量（--c1..--c4），日/夜间自动切换，不用重新渲染。配色经色盲分离度与对比度校验。 */
function dtNum(v) { return (Math.round(v * 100) / 100).toLocaleString('zh-CN'); }
function dtLegend(series) {
  if (series.length < 2) return '';                 // 单系列不需要图例（标题已经说明它是什么）
  return `<div class="ch-lg">${series.map((s, i) =>
    `<span><i style="background:var(--c${i + 1})"></i>${esc(s.name)}</span>`).join('')}</div>`;
}
function dtChart(m) {
  const W = 560, H = 250, PL = 52, PR = 14, PT = 14, PB = 34;   // 画布与内边距
  const iw = W - PL - PR, ih = H - PT - PB;
  const labels = m.labels || [], series = m.series || [];
  if (m.type === 'pie') {
    const data = (series[0] || {}).data || [];
    const tot = data.reduce((a, b) => a + b, 0) || 1;
    let a0 = -Math.PI / 2, arcs = '';
    data.forEach((v, i) => {
      const a1 = a0 + v / tot * Math.PI * 2, big = (a1 - a0) > Math.PI ? 1 : 0;
      const R = 92, cx = 150, cy = 125;
      const x0 = cx + R * Math.cos(a0), y0 = cy + R * Math.sin(a0);
      const x1 = cx + R * Math.cos(a1), y1 = cy + R * Math.sin(a1);
      // 2px 表面间隙：扇区之间留一条底色描边，不靠颜色硬碰硬
      arcs += `<path d="M${cx},${cy} L${x0.toFixed(1)},${y0.toFixed(1)} A${R},${R} 0 ${big} 1 ${x1.toFixed(1)},${y1.toFixed(1)} Z"
        fill="var(--c${(i % 4) + 1})" stroke="var(--card)" stroke-width="2"><title>${esc(labels[i] || '')} ${dtNum(v)}${esc(m.unit || '')}</title></path>`;
      const am = (a0 + a1) / 2, lx = cx + (R + 26) * Math.cos(am), ly = cy + (R + 26) * Math.sin(am);
      arcs += `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" class="ch-dl" text-anchor="${Math.cos(am) < -0.1 ? 'end' : (Math.cos(am) > 0.1 ? 'start' : 'middle')}">${esc(labels[i] || '')} ${dtNum(v)}${esc(m.unit || '')}</text>`;
      a0 = a1;
    });
    return `<svg viewBox="0 0 ${W} ${H}" class="ch" role="img">${arcs}</svg>`;
  }
  const all = series.flatMap(s => s.data);
  const max = Math.max(...all, 0), min = Math.min(...all, 0);
  const top = max > 0 ? max * 1.12 : 1, bot = min < 0 ? min * 1.12 : 0;
  // band 刻度（每个类别占一格、点画在格子中心）：柱组不会压住 Y 轴刻度，也不会被右边裁掉
  const band = iw / Math.max(labels.length, 1);
  const X = (i) => PL + band * (i + 0.5);
  const Y = (v) => PT + ih - (v - bot) / (top - bot || 1) * ih;
  let g = '';
  for (let k = 0; k <= 4; k++) {                     // 网格线：弱化，不抢笔迹
    const y = PT + ih * k / 4, v = top - (top - bot) * k / 4;
    g += `<line x1="${PL}" y1="${y.toFixed(1)}" x2="${W - PR}" y2="${y.toFixed(1)}" class="ch-gr"/>
      <text x="${PL - 8}" y="${(y + 4).toFixed(1)}" class="ch-ax" text-anchor="end">${dtNum(v)}</text>`;
  }
  g += labels.map((L, i) => `<text x="${X(i).toFixed(1)}" y="${H - 12}" class="ch-ax" text-anchor="middle">${esc(L)}</text>`).join('');
  let marks = '';
  if (m.type === 'bar') {
    const bw = Math.min(28, band * 0.72 / Math.max(series.length, 1));   // 一格里放得下这组柱子
    labels.forEach((L, i) => series.forEach((s, j) => {
      const v = s.data[i], x = X(i) - (series.length * bw) / 2 + j * bw, y = Y(Math.max(v, 0)), h = Math.abs(Y(v) - Y(0));
      // 数据端 4px 圆角、锚在基线；相邻柱之间留 2px 底色间隙
      marks += `<rect x="${(x + 1).toFixed(1)}" y="${y.toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${Math.max(h, 1).toFixed(1)}"
        rx="4" fill="var(--c${(j % 4) + 1})"><title>${esc(L)} · ${esc(s.name)} ${dtNum(v)}${esc(m.unit || '')}</title></rect>`;
      if (series.length * labels.length <= 8)        // 点数少才直接标数值，多了就只留悬停
        marks += `<text x="${(x + bw / 2).toFixed(1)}" y="${(y - 6).toFixed(1)}" class="ch-dl" text-anchor="middle">${dtNum(v)}</text>`;
    }));
  } else {
    series.forEach((s, j) => {
      const pts = s.data.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
      marks += `<polyline points="${pts}" fill="none" stroke="var(--c${(j % 4) + 1})" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
      marks += s.data.map((v, i) => `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="4.5"
        fill="var(--c${(j % 4) + 1})" stroke="var(--card)" stroke-width="2"><title>${esc(labels[i])} · ${esc(s.name)} ${dtNum(v)}${esc(m.unit || '')}</title></circle>`).join('');
    });
  }
  return `<svg viewBox="0 0 ${W} ${H}" class="ch" role="img">${g}${marks}</svg>`;
}
function dtTable(m) {
  return `<table class="ch-tb"><thead><tr>${(m.headers || []).map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
    <tbody>${(m.rows || []).map(r => `<tr>${r.map((c, i) => `<td${i ? ' class="num"' : ''}>${esc(String(c))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}
let _dtLastMat = '';
function dtMaterial(m, i) {
  if (!m) { _dtLastMat = ''; return ''; }
  const key = JSON.stringify(m);
  if (key === _dtLastMat) return '<div class="dt-same">↑ 根据上面这份材料作答</div>';  // 两题共用一份材料，不重复渲染
  _dtLastMat = key;
  const head = `<div class="dt-mt">${esc(m.title || '根据下列资料，回答问题')}${m.unit ? `<span>单位：${esc(m.unit)}</span>` : ''}</div>`;
  if (m.type === 'table') return `<div class="dt-mat">${head}${dtTable(m)}</div>`;
  // 图表另附「看数据表」，方便核对数字（也是无障碍要求：不能只靠图形）
  const tb = { headers: ['项目', ...(m.labels || [])],
    rows: (m.series || []).map(s => [s.name, ...s.data.map(v => dtNum(v))]) };
  return `<div class="dt-mat">${head}${dtChart(m)}${dtLegend(m.series || [])}
    <button class="ch-tbtn" data-chtb="${i}">📋 看数据表</button>
    <div class="ch-tbwrap hidden" id="chtb-${i}">${dtTable(tb)}</div></div>`;
}

function renderDtest() {
  _dtLastMat = '';
  const qs = dtItems.map((it, i) => {
    const revealed = dtRevealedAt(i);
    const isFig = !!(it.figs && it.figs.opts);
    const opts = isFig
      ? it.figs.opts.map((svg, j) => {
        const L = DT_L[j], chosen = dtChosen[i] === L, isAns = (dtAns(i) || '').toUpperCase() === L;
        let cls = 'dt-opt dt-figopt';
        if (revealed) { if (isAns) cls += ' correct'; else if (chosen) cls += ' wrong'; }
        else if (chosen) cls += ' chosen';
        return `<button class="${cls}" data-dtq="${i}" data-dtl="${L}" ${revealed ? 'disabled' : ''}>
          <span class="dt-figl">${L}</span>${svg}</button>`;
      }).join('')
      : (it.options || []).map((o, j) => {
        const L = DT_L[j], chosen = dtChosen[i] === L, isAns = (dtAns(i) || '').toUpperCase() === L;
        let cls = 'dt-opt';
        if (revealed) { if (isAns) cls += ' correct'; else if (chosen) cls += ' wrong'; }
        else if (chosen) cls += ' chosen';
        return `<button class="${cls}" data-dtq="${i}" data-dtl="${L}" ${revealed ? 'disabled' : ''}>${esc(o)}</button>`;
      }).join('');
    const e = dtExp(i);
    const exp = revealed ? `<div class="dt-exp"><b>正确答案 ${esc(dtAns(i))}</b>${e.explain ? ' · ' + esc(e.explain) : ''}${e.source ? ` <span class="dt-src">${esc(e.source)}</span>` : ''}</div>` : '';
    const mod = it.module ? `<span class="dt-mod" style="background:${PL_MOD_COLOR[it.module] || '#6b7280'}">${esc(it.module)}</span>` : '';
    const mat = dtMaterial(it.material, i);
    const seq = isFig ? `<div class="dt-seq">${it.figs.seq.join('')}<span class="dt-qm">?</span></div>` : '';
    return `<div class="dt-q">${mat}<div class="dt-qt">${mod}${i + 1}. ${esc(it.q)}</div>${seq}
      <div class="dt-opts${isFig ? ' dt-figs' : ''}">${opts}</div>${exp}</div>`;
  }).join('');
  let foot;
  if (dtSubmitted) {
    foot = `<div class="dt-score">得分 ${dtScore()} / ${dtItems.length}</div>
       <button class="btn" id="dt-again">🔄 换一套新题</button>`;
  } else if (dtIsTest()) {
    foot = `<button class="btn primary" id="dt-submit">交卷看结果</button>`;
  } else {
    const done = dtItems.filter((_, i) => dtRevealed[i]).length;
    foot = `<div class="dt-prog2">已做 ${done} / ${dtItems.length}</div>` +
      (done === dtItems.length ? `<button class="btn primary" id="dt-finish">看结果并记录</button>` : '');
  }
  $('#dt-body').innerHTML = (dtSubmitted ? '' : dtModeBar()) + `<div class="dt-list">${qs}</div><div class="dt-foot">${foot}</div>`;
  if (dtSubmitted) $('#dt-again').onclick = async () => { if (await appConfirm('重新出一套？当前作答会清空。')) dtGen(true); };
  else { const s = $('#dt-submit'); if (s) s.onclick = dtSubmit; const f = $('#dt-finish'); if (f) f.onclick = dtFinish; bindBar(); }
}
async function dtRecord() {
  // 把本次作答交给服务端判分并留档
  try {
    const ans = {}; dtItems.forEach((_, i) => ans[i] = dtChosen[i] || '');
    return await api('/api/dtest/grade', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answers: ans }) });
  } catch (e) { toast(e.message, true); return null; }
}
async function dtSubmit() {   // 测试模式交卷
  const un = dtItems.findIndex((_, i) => !dtChosen[i]);
  if (un >= 0) { toast('第 ' + (un + 1) + ' 题还没选', true); return; }
  const btn = $('#dt-submit'); if (btn) { btn.disabled = true; btn.textContent = '判分中…'; }
  const d = await dtRecord();
  if (!d) { if (btn) { btn.disabled = false; btn.textContent = '交卷看结果'; } return; }
  dtResults = d.results || [];
  dtSubmitted = true; renderDtest();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
async function dtFinish() {   // 背题模式做完，记录成绩
  await dtRecord();
  dtSubmitted = true; renderDtest();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
$('#dt-body').addEventListener('click', e => {
  const tb = e.target.closest('[data-chtb]');          // 图表下方的「看数据表」
  if (tb) {
    const box = $('#chtb-' + tb.dataset.chtb);
    const hidden = box.classList.toggle('hidden');
    tb.textContent = hidden ? '📋 看数据表' : '📊 收起数据表';
    return;
  }
  const o = e.target.closest('[data-dtq]'); if (!o) return;
  const i = +o.dataset.dtq;
  if (dtRevealedAt(i)) return;              // 已揭晓的题不能再改
  dtChosen[i] = o.dataset.dtl;
  if (!dtIsTest()) {
    dtRevealed[i] = true;                   // 背题模式：选完立刻揭晓这题
    if ((dtAns(i) || '').toUpperCase() !== dtChosen[i]) {   // 选错了 → 自动进错题本
      api('/api/dtest/wrong', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ idx: i, choice: dtChosen[i] }),
      }).then(d => { if (d.added) toast('这题错了，已收进错题本'); }).catch(() => {});
    }
  }
  renderDtest();
});
/* 测试记录：列表 + 回看某次作答 */
async function openDtRecords() {
  $('#dt-body').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/dtest/records');
    const list = d.items.length ? d.items.map(r => `
      <div class="dtr-row" data-dtrec="${r.id}">
        <span class="dtr-when">${esc((r.created_at || r.date || '').slice(5, 16))}</span>
        <span class="dtr-score ${r.score >= r.total * 0.6 ? 'ok' : 'bad'}">${r.score} / ${r.total}</span>
        <span class="dtr-go">回看 ›</span></div>`).join('')
      : '<p class="empty">还没有测试记录。做一次巩固测试，交卷后就会留档。</p>';
    $('#dt-body').innerHTML = `<div class="dtr-top"><button class="pl-link-btn" id="dt-back">‹ 返回测试</button><b>测试记录</b></div>${list}`;
    $('#dt-back').onclick = loadDtest;
  } catch (e) { $('#dt-body').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
async function openDtRecord(rid) {
  $('#dt-body').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/dtest/record/' + rid);
    const qs = (d.detail || []).map((it, i) => {
      const opts = (it.options || []).map((o, j) => {
        const L = DT_L[j], isAns = (it.answer || '').toUpperCase() === L, mine = (it.your || '').toUpperCase() === L;
        let cls = 'dt-opt'; if (isAns) cls += ' correct'; else if (mine) cls += ' wrong';
        return `<button class="${cls}" disabled>${esc(o)}</button>`;
      }).join('');
      return `<div class="dt-q"><div class="dt-qt">${i + 1}. ${esc(it.q)}</div><div class="dt-opts">${opts}</div>
        <div class="dt-exp"><b>正确答案 ${esc(it.answer)}</b>${it.your ? ' · 你选了 ' + esc(it.your) : ''}${it.explain ? ' · ' + esc(it.explain) : ''}${it.source ? ` <span class="dt-src">${esc(it.source)}</span>` : ''}</div></div>`;
    }).join('');
    $('#dt-body').innerHTML = `<div class="dtr-top"><button class="pl-link-btn" id="dt-back2">‹ 返回记录</button>
      <b>${esc((d.created_at || '').slice(5, 16))} · 得分 ${d.score}/${d.total}</b></div><div class="dt-list">${qs}</div>`;
    $('#dt-back2').onclick = openDtRecords;
  } catch (e) { $('#dt-body').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#dt-body').addEventListener('click', e => {
  const r = e.target.closest('[data-dtrec]'); if (r) openDtRecord(+r.dataset.dtrec);
});

async function loadDaily() {
  $('#tk-daily-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/daily_tasks');
    $('#tk-daily-prog').textContent = d.total ? `今日进度 ${d.done_n} / ${d.total}${d.done_n === d.total ? ' 🎉 全部完成！' : ''}` : '';
    $('#tk-daily-list').innerHTML = d.items.length ? d.items.map(it => `
      <div class="tk-item ${it.done ? 'done' : ''}" data-td="${it.id}">
        <span class="tk-check">${it.done ? '✓' : ''}</span>
        <span class="tk-text">${esc(it.text)}</span>
        <button class="tk-del" data-tddel="${it.id}">🗑</button>
      </div>`).join('') : '<p class="empty">还没有每日任务，下面加一条吧～</p>';
  } catch (e) { $('#tk-daily-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#tk-daily-list').addEventListener('click', async e => {
  const del = e.target.closest('[data-tddel]');
  if (del) { e.stopPropagation(); if (!(await appConfirm('删除这个每日任务？'))) return; try { await api('/api/daily_tasks/templates/' + del.dataset.tddel, { method: 'DELETE' }); loadDaily(); } catch (er) { toast(er.message, true); } return; }
  const it = e.target.closest('[data-td]'); if (!it) return;
  try { await api('/api/daily_tasks/' + it.dataset.td + '/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); loadDaily(); } catch (er) { toast(er.message, true); }
});
$('#tk-daily-add').onclick = async () => {
  const v = $('#tk-daily-in').value.trim(); if (!v) return;
  try { await api('/api/daily_tasks/templates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: v }) }); $('#tk-daily-in').value = ''; loadDaily(); } catch (e) { toast(e.message, true); }
};
$('#tk-daily-in').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') $('#tk-daily-add').click(); });

let tkMembers = [], tkMeId = 0, tkTeam = null;
/* 先看组队状态：没组队 → 组队 UI；已组队 → 队头 + 互监清单 */
async function loadShared() {
  $('#tk-team').innerHTML = '<p class="empty">加载中…</p>';
  $('#tk-board').classList.add('hidden');
  try {
    const t = await api('/api/team');
    tkMeId = t.me_id; tkTeam = t.team;
    if (!t.team) { renderTeamSetup(t); return; }
    renderTeamHeader(t);
    $('#tk-board').classList.remove('hidden');
    await loadSharedBoard();
  } catch (e) { $('#tk-team').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderTeamSetup(t) {
  const inc = (t.incoming || []).filter(r => r.kind === 'join').map(r => `
    <div class="tm-req"><span>📨 <b>${esc(shortName(r.from_name))}</b> 想和你组队互监</span>
      <span class="tm-acts"><button class="btn tiny primary" data-tmacc="${r.id}">接受</button>
      <button class="btn tiny" data-tmrej="${r.id}">拒绝</button></span></div>`).join('');
  const out = (t.outgoing || []).filter(r => r.kind === 'join').map(r => `
    <div class="tm-req"><span>⏳ 已向 <b>${esc(shortName(r.to_name))}</b> 发出组队申请，等对方接受</span>
      <button class="btn tiny" data-tmcancel="${r.id}">撤回</button></div>`).join('');
  $('#tk-team').innerHTML = `
    <div class="pd-intro">互监需要先和搭档组队：搜对方的账号发起邀请，对方接受即可互相监督。</div>
    <div class="tm-search"><input id="tm-q" placeholder="搜账号 / 用户名 / ID"><button class="btn primary" id="tm-search-btn">搜索</button></div>
    <div id="tm-results"></div>
    ${inc ? `<div class="tm-sec"><div class="tm-sec-t">收到的组队申请</div>${inc}</div>` : ''}
    ${out ? `<div class="tm-sec"><div class="tm-sec-t">我发出的申请</div>${out}</div>` : ''}`;
  $('#tm-search-btn').onclick = tmSearch;
  $('#tm-q').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') tmSearch(); });
}
function renderTeamHeader(t) {
  const p = t.team.partner;
  const disIn = (t.incoming || []).find(r => r.kind === 'disband');
  const disOut = (t.outgoing || []).find(r => r.kind === 'disband');
  let dis = '';
  if (disIn) dis = `<div class="tm-req tm-warn"><span>⚠️ <b>${esc(shortName(p ? p.name : '搭档'))}</b> 申请解散组队</span>
    <span class="tm-acts"><button class="btn tiny primary" data-tmacc="${disIn.id}">同意解散</button>
    <button class="btn tiny" data-tmrej="${disIn.id}">不同意</button></span></div>`;
  else if (disOut) dis = `<div class="tm-req"><span>⏳ 已申请解散，等对方同意</span>
    <button class="btn tiny" data-tmcancel="${disOut.id}">撤回</button></div>`;
  const st = t.study || { streak: 0, total: 0 };
  $('#tk-team').innerHTML = `
    <div class="tm-head"><span>🤝 已与 <b>${esc(shortName(p ? p.name : '搭档'))}</b> 组队互监</span>
      ${disOut || disIn ? '' : '<button class="btn tiny" id="tm-disband">解散组队</button>'}</div>
    <div class="tm-streak">🔥 连续学习 <b>${st.streak}</b> 天 · 累计 <b>${st.total}</b> 天</div>
    ${dis}`;
  if ($('#tm-disband')) $('#tm-disband').onclick = tmDisband;
}
async function tmSearch() {
  const q = $('#tm-q').value.trim(); if (!q) return;
  $('#tm-results').innerHTML = '<p class="empty">搜索中…</p>';
  try {
    const d = await api('/api/team/search?q=' + encodeURIComponent(q));
    $('#tm-results').innerHTML = d.users.length ? d.users.map(u => `
      <div class="tm-res"><span>${esc(u.name)} <i class="tm-uid">ID ${u.id}</i></span>
        ${u.in_team ? '<span class="tm-busy">已组队</span>' : `<button class="btn tiny primary" data-tminvite="${u.id}">邀请组队</button>`}</div>`).join('')
      : '<p class="empty">没找到这个账号</p>';
  } catch (e) { $('#tm-results').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
async function tmDisband() {
  if (!(await appConfirm('向搭档发出解散组队申请？对方同意后才会解散。'))) return;
  try { await api('/api/team/disband', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); toast('已发出解散申请'); loadShared(); }
  catch (e) { toast(e.message, true); }
}
$('#tk-team').addEventListener('click', async e => {
  const inv = e.target.closest('[data-tminvite]');
  const acc = e.target.closest('[data-tmacc]');
  const rej = e.target.closest('[data-tmrej]');
  const can = e.target.closest('[data-tmcancel]');
  try {
    if (inv) { await api('/api/team/request', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to_uid: +inv.dataset.tminvite }) }); toast('已发出组队申请'); loadShared(); }
    else if (acc) { const r = await api('/api/team/request/' + acc.dataset.tmacc + '/accept', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); toast(r.disbanded ? '已解散组队' : '已组队 🤝'); loadShared(); }
    else if (rej) { await api('/api/team/request/' + rej.dataset.tmrej + '/reject', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); loadShared(); }
    else if (can) { await api('/api/team/request/' + can.dataset.tmcancel + '/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); loadShared(); }
  } catch (er) { toast(er.message, true); }
});
async function loadSharedBoard() {
  $('#tk-shared-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/shared_todos');
    tkMembers = d.members || [];
    tkMeId = d.me_id;
    // 表头：每位互监成员一列打勾位；自己那列标「我」，只能由搭档来勾
    $('#tk-shared-head').innerHTML = tkMembers.length
      ? `<span class="tk-hd-text">待办</span><span class="tk-hd-ms">` + tkMembers.map(m =>
        `<span class="tk-hd-m ${m.id === d.me_id ? 'me' : ''}" title="${esc(m.name)}">${m.id === d.me_id ? '我' : esc(initials(m.name))}</span>`).join('') + `</span>`
      : '';
    $('#tk-shared-list').innerHTML = d.items.length ? d.items.map(it => {
      const ids = it.done_ids || [];
      const byMap = it.done_by_map || {};
      const boxes = tkMembers.map(m => {
        const on = ids.includes(m.id), mine = m.id === d.me_id;
        const tip = on ? `${m.name}（由 ${byMap[m.id] || '?'} 确认）`
          : (mine ? '自己不能勾自己，等搭档来确认' : `确认 ${m.name} 已完成`);
        return `<button class="tk-box ${on ? 'on' : ''} ${mine ? 'mine' : ''}"
          data-tsbox="${it.id}" data-tsuser="${m.id}" title="${esc(tip)}">${on ? '✓' : (mine ? '🔒' : '')}</button>`;
      }).join('');
      const who = tkMembers.filter(m => ids.includes(m.id))
        .map(m => `${shortName(m.name)}（${shortName(byMap[m.id] || '?')} 确认）`);
      const all = tkMembers.length && tkMembers.every(m => ids.includes(m.id));
      return `<div class="tk-item tk-multi ${all ? 'done' : ''}" data-ts="${it.id}">
        <span class="tk-text">${it.is_plan ? '<i class="ts-plan">📅 规划</i> ' : ''}${esc(it.text)}<span class="tk-who">${it.is_plan ? '来自 ' + esc(shortName(it.created_by)) + ' 的今日计划' : '发起 ' + esc(shortName(it.created_by))}${all ? ' · 🎉 双方都已确认' : (who.length ? ' · ✅ ' + esc(who.join('、')) : '')}</span></span>
        <span class="tk-boxes">${boxes}</span>
        ${it.is_plan ? '' : `<button class="tk-del" data-tsdel="${it.id}">🗑</button>`}
      </div>`;
    }).join('') : '<p class="empty">还没有共享待办，加一条大家一起监督～</p>';
  } catch (e) { $('#tk-shared-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function shortName(n) { n = n || ''; n = n.split('@')[0]; return n.length > 6 ? n.slice(0, 5) + '…' : n; }
// 表头列宽只有一个勾选框那么宽，用 2 个字符当列名（完整名在 title 与成员面板里）
function initials(n) { n = (n || '').split('@')[0]; return n.slice(0, 4); }
$('#tk-shared-list').addEventListener('click', async e => {
  const del = e.target.closest('[data-tsdel]');
  if (del) { e.stopPropagation(); if (!(await appConfirm('删除这条共享待办？'))) return; try { await api('/api/shared_todos/' + del.dataset.tsdel, { method: 'DELETE' }); loadSharedBoard(); } catch (er) { toast(er.message, true); } return; }
  const box = e.target.closest('[data-tsbox]'); if (!box) return;
  if (+box.dataset.tsuser === tkMeId) { toast('自己不能给自己打勾，等搭档来确认 🤝', true); return; }
  try {
    await api('/api/shared_todos/' + box.dataset.tsbox + '/toggle', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: +box.dataset.tsuser })
    });
    loadSharedBoard();
  } catch (er) { toast(er.message, true); }
});
$('#tk-shared-add').onclick = async () => {
  const v = $('#tk-shared-in').value.trim(); if (!v) return;
  try { await api('/api/shared_todos', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: v }) }); $('#tk-shared-in').value = ''; loadSharedBoard(); } catch (e) { toast(e.message, true); }
};
$('#tk-shared-in').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') $('#tk-shared-add').click(); });

/* ================= 申论：真题卷 + 题型讲义 + AI 逐点批改 ================= */
let slType = null, slQuestion = null, slPaper = null, slResult = null;

async function openShenlun() {
  push({ view: 'shenlun', title: '真题批改' });
  $('#sl-types').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/shenlun/types');
    $('#sl-types').innerHTML = d.types.map(t => `
      <div class="home-card" data-slt="${esc(t.key)}">
        <div class="hc-logo" style="background:${t.color}">${IC[t.icon] || IC.edit}</div>
        <div class="hc-name">${esc(t.name)}</div>
        <div class="hc-desc">${t.full} 分 · ${t.word_min}-${t.word_max} 字</div>
      </div>`).join('');
    loadSlPapers();
    loadSlHistory();
  } catch (e) { $('#sl-types').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#sl-types').addEventListener('click', e => {
  const c = e.target.closest('[data-slt]'); if (c) openSlType(c.dataset.slt);
});

/* ---- 真题卷：上传 → 自动拆题 ---- */
$('#sl-essays').onclick = () => openEssays();
$('#sl-upload').onclick = () => $('#sl-file').click();
async function slUploadPaper(file) {
  if (!file) return;
  toast('正在识别题目…（扫描件需 OCR，可能要 1 分钟）');
  const fd = new FormData();
  fd.append('file', file);
  try {
    const d = await api('/api/shenlun/paper/upload', { method: 'POST', body: fd });
    toast('识别出 ' + d.questions.length + ' 道题');
    loadSlPapers();
    openSlPaper(d.id);
  } catch (err) { toast(err.message, true); }
}
$('#sl-file').addEventListener('change', e => {
  const f = e.target.files[0]; e.target.value = '';
  slUploadPaper(f);
});
/* 真题卷：整个页面都能拖进来（PDF / Word / 图片都行），不用非得点按钮 */
(function () {
  const v = $('#view-shenlun');
  if (!v) return;
  const on = (e) => { e.preventDefault(); v.classList.add('drag-on'); };
  const off = (e) => { if (e.target === v || !v.contains(e.relatedTarget)) v.classList.remove('drag-on'); };
  v.addEventListener('dragover', on);
  v.addEventListener('dragenter', on);
  v.addEventListener('dragleave', off);
  v.addEventListener('drop', e => {
    e.preventDefault(); v.classList.remove('drag-on');
    const f = [...(e.dataTransfer ? e.dataTransfer.files : [])][0];
    if (f) slUploadPaper(f);
    else if (!window.__desktop) toast('没拿到文件，换「📄 上传真题」按钮试试', true);
  });
})();

async function loadSlPapers() {
  try {
    const d = await api('/api/shenlun/papers');
    $('#sl-papers').innerHTML = d.items.length ? d.items.map(p => `
      <div class="sl-hi" data-slp="${p.id}">
        <div class="sl-hi-main">
          <div class="sl-hi-t">📄 ${esc(p.title)}</div>
          <div class="sl-hi-m">${p.total} 道题 · 已做 ${p.done} 道 · ${esc(p.created_at.slice(5, 16))}</div>
        </div>
        <div class="sl-hi-s ${p.done >= p.total ? 'good' : 'ok'}">${p.done}<span>/${p.total}</span></div>
        <button class="sl-hi-del" data-slpdel="${p.id}">🗑</button>
      </div>`).join('') : '<p class="empty">还没有真题卷。点右上角「上传真题」，PDF/Word/图片都行，会自动拆出各道题。</p>';
  } catch (_) {}
}
$('#sl-papers').addEventListener('click', async e => {
  const del = e.target.closest('[data-slpdel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('删除这份真题卷？批改记录会保留。'))) return;
    try { await api('/api/shenlun/paper/' + del.dataset.slpdel, { method: 'DELETE' }); loadSlPapers(); }
    catch (er) { toast(er.message, true); }
    return;
  }
  const p = e.target.closest('[data-slp]');
  if (p) openSlPaper(+p.dataset.slp);
});

async function openSlPaper(pid) {
  try {
    const p = await api('/api/shenlun/paper/' + pid);
    slPaper = p;
    push({ view: 'slpaper', title: p.title });
    const done = p.questions.filter(q => q.done).length;
    $('#slp-head').innerHTML = `<div class="slt-title">${esc(p.title)}</div>
      <div class="slt-desc">${p.questions.length} 道题 · 已做 ${done} 道</div>`;
    $('#slp-mat-text').textContent = p.material || '（未识别到给定资料）';
    $('#slp-qs').innerHTML = p.questions.map(q => {
      const d = q.done;
      const pct = d && q.full ? d.score / q.full : 0;
      return `<div class="slq" data-slq="${q.id}">
        <div class="slq-head">
          <span class="slq-no">${q.seq}</span>
          <span class="slq-type">${esc(q.type_name)}</span>
          <span class="slq-meta">${q.full} 分 · ${q.word_min}-${q.word_max} 字</span>
          ${d ? `<span class="slq-score ${pct >= 0.8 ? 'good' : pct >= 0.6 ? 'ok' : 'bad'}">${d.score}/${d.full}</span>`
          : '<span class="slq-todo">未作答</span>'}
        </div>
        <div class="slq-stem">${esc(q.stem)}</div>
        ${d ? `<button class="slq-view" data-slview="${d.grade_id}">看批改</button>` : ''}
      </div>`;
    }).join('');
  } catch (e) { toast(e.message, true); }
}
$('#slp-qs').addEventListener('click', e => {
  const v = e.target.closest('[data-slview]');
  if (v) { e.stopPropagation(); openSlRecord(+v.dataset.slview); return; }
  const q = e.target.closest('[data-slq]');
  if (!q) return;
  const item = slPaper.questions.find(x => x.id === +q.dataset.slq);
  if (item) openSlGradeQ(item);
});

/* ---- 批改记录 ---- */
async function loadSlHistory() {
  try {
    const d = await api('/api/shenlun/history');
    $('#sl-hist-n').textContent = d.items.length ? d.items.length + ' 次' : '';
    $('#sl-hist').innerHTML = d.items.length ? d.items.map(it => {
      const pct = it.full ? it.score / it.full : 0;
      const lv = pct >= 0.8 ? '优秀' : pct >= 0.6 ? '达标' : '待提升';
      const from = it.paper_title ? `${esc(it.paper_title)} 第${it.seq}题` : esc(it.type_name);
      const w = it.words ? ` · ${it.words} 字` : '';
      return `<div class="sl-hi" data-slr="${it.id}">
        <div class="sl-hi-main">
          <div class="sl-hi-t">${from} · ${esc(it.question)}</div>
          <div class="sl-hi-m">${esc(it.created_at.slice(5, 16))} · ${lv}${w}</div>
        </div>
        <div class="sl-hi-s ${pct >= 0.8 ? 'good' : pct >= 0.6 ? 'ok' : 'bad'}">${it.score}<span>/${it.full}</span></div>
        <button class="sl-hi-del" data-sldel="${it.id}">🗑</button>
      </div>`;
    }).join('') : '<p class="empty">还没有批改记录，挑一道题练一练吧～</p>';
  } catch (_) {}
}
$('#sl-hist').addEventListener('click', async e => {
  const del = e.target.closest('[data-sldel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('删除这条批改记录？'))) return;
    try { await api('/api/shenlun/record/' + del.dataset.sldel, { method: 'DELETE' }); loadSlHistory(); }
    catch (er) { toast(er.message, true); }
    return;
  }
  const it = e.target.closest('[data-slr]');
  if (it) openSlRecord(+it.dataset.slr);
});

/* ---- 题型讲义 ---- */
async function openSlType(key) {
  try {
    const t = await api('/api/shenlun/type/' + key);
    slType = t; slQuestion = null;
    push({ view: 'sltype', title: t.name });
    $('#slt-head').innerHTML = `<div class="slt-title" style="border-left-color:${t.color}">${esc(t.name)}</div>
      <div class="slt-desc">${esc(t.desc)} · 满分 ${t.full} 分 · 参考字数 ${t.word_min}-${t.word_max} 字</div>`;
    $('#slt-goals').innerHTML = `<div class="slt-sec">学习目标</div><ul>`
      + t.goals.map(g => `<li>${esc(g)}</li>`).join('') + `</ul>`;
    $('#slt-map').innerHTML = `<div class="slt-sec">本章知识导图</div>` + t.map.map(g => `
      <div class="slm-group">
        <div class="slm-gname" style="background:${t.color}">${esc(g.group)}</div>
        ${g.rows.map(r => `<div class="slm-row">
          <div class="slm-name">${esc(r.name)}</div>
          <div class="slm-cells">${Object.keys(r).filter(k => k !== 'name').map(k =>
            `<div class="slm-cell"><b>${esc(k)}</b>${esc(r[k])}</div>`).join('')}</div>
        </div>`).join('')}
      </div>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#slt-go').onclick = () => { if (slType) openSlGrade(slType); };

/* ---- 作答页：自由练 / 真题某一小题 ---- */
function slSetupAnswer(full, wmin, wmax) {
  $('#slg-full').value = full;
  $('#slg-a').dataset.wmin = wmin; $('#slg-a').dataset.wmax = wmax;
  $('#slg-req').textContent = `（要求 ${wmin}-${wmax} 字）`;
  $('#slg-a').value = '';
  slCountWords();
}
function slWords(t) { return (t || '').replace(/\s+/g, '').length; }
function slCountWords() {
  const a = $('#slg-a');
  const n = slWords(a.value);
  const lo = +a.dataset.wmin, hi = +a.dataset.wmax;
  const el = $('#slg-count');
  let state = 'ok', tip = '字数达标';
  if (!n) { state = 'idle'; tip = ''; }
  else if (n < lo) { state = 'low'; tip = `还差 ${lo - n} 字`; }
  else if (n > hi) { state = 'high'; tip = `超出 ${n - hi} 字`; }
  el.className = 'slg-count ' + state;
  el.textContent = n ? `${n} / ${lo}-${hi} 字　${tip}` : `要求 ${lo}-${hi} 字`;
}
$('#slg-a').addEventListener('input', slCountWords);

function openSlGrade(t) {          // 自由练：自己贴题干和材料
  $('#slg-mat').classList.add('hidden');
  slType = t; slQuestion = null;
  push({ view: 'slgrade', title: t.name + ' · 批改' });
  $('#slg-type').innerHTML = `<span class="slg-badge" style="background:${t.color}">${esc(t.name)}</span>`;
  $('#slg-manual').classList.remove('hidden');
  $('#slg-fixed').classList.add('hidden');
  $('#slg-fullwrap').classList.remove('hidden');
  $('#slg-q').value = ''; $('#slg-m').value = '';
  slSetupAnswer(t.full, t.word_min, t.word_max);
}
function openSlGradeQ(q) {         // 真题：题干/材料/满分/字数都锁定，只写答案
  slQuestion = q; slType = null;
  push({ view: 'slgrade', title: `第${q.seq}题 · ${q.type_name}` });
  $('#slg-type').innerHTML = `<span class="slg-badge" style="background:#2b6fd6">第 ${q.seq} 题 · ${esc(q.type_name)}</span>`;
  $('#slg-manual').classList.add('hidden');
  $('#slg-fullwrap').classList.add('hidden');
  $('#slg-fixed').classList.remove('hidden');
  $('#slg-fixed').innerHTML = `<div class="slf-stem">${esc(q.stem)}</div>
    <div class="slf-meta">${q.full} 分 · 要求 ${q.word_min}-${q.word_max} 字</div>`;
  slSetupAnswer(q.full, q.word_min, q.word_max);
  // 作答时要看得到给定资料（考场上就是拿笔在材料上划重点）
  const mat = (slPaper && slPaper.material) || '';
  $('#slg-mat').classList.toggle('hidden', !mat);
  $('#slg-mat').onclick = () => matOpen(mat, 'p' + (slPaper ? slPaper.id : 0));
  if (mat && !IS_MOBILE) matOpen(mat, 'p' + slPaper.id);      // 电脑端直接半屏摆出来
}
$('#slg-go').onclick = async () => {
  const answer = $('#slg-a').value.trim();
  if (answer.length < 10) return toast('请填写你的答案', true);
  const lo = +$('#slg-a').dataset.wmin, hi = +$('#slg-a').dataset.wmax, n = slWords(answer);
  if (n < lo * 0.5) { if (!(await appConfirm(`只写了 ${n} 字，远低于要求的 ${lo} 字，仍要批改吗？`))) return; }

  let body;
  if (slQuestion) body = { question_id: slQuestion.id, answer };
  else {
    const question = $('#slg-q').value.trim(), material = $('#slg-m').value.trim();
    if (!question) return toast('请填写题干', true);
    body = { type: slType.key, question, material, answer, full: +$('#slg-full').value, word_min: lo, word_max: hi };
  }
  const btn = $('#slg-go');
  btn.disabled = true; btn.textContent = '阅卷中…（30~60 秒）';
  try {
    const d = await api('/api/shenlun/grade', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    slResult = d;
    renderSlResult(d);
    loadSlHistory();
    if (d.next) showSlNext(d);
  } catch (e) { toast(e.message, true); }
  btn.disabled = false; btn.textContent = '开始批改';
};

/* ---- 做完一题 → 提示继续下一题 ---- */
function showSlNext(d) {
  $('#sln-title').textContent = `第 ${d.seq} 题 已批改：${d.score} / ${d.full} 分`;
  $('#sln-body').textContent = `下一题是「第 ${d.next.seq} 题 · ${d.next.type_name}」（${d.next.full} 分），现在继续吗？`;
  $('#sl-next').classList.remove('hidden');
  $('#sln-stay').onclick = () => $('#sl-next').classList.add('hidden');
  $('#sln-go').onclick = async () => {
    $('#sl-next').classList.add('hidden');
    try {
      const p = await api('/api/shenlun/paper/' + d.paper_id);
      slPaper = p;
      const q = p.questions.find(x => x.id === d.next.id);
      if (q) openSlGradeQ(q);
    } catch (e) { toast(e.message, true); }
  };
}

async function openSlRecord(rid) {
  try {
    const d = await api('/api/shenlun/record/' + rid);
    renderSlResult(d.result);
  } catch (e) { toast(e.message, true); }
}

function renderSlResult(r) {
  push({ view: 'slresult', title: '批改结果' });
  const pct = r.full ? r.score / r.full : 0;
  const grade = pct >= 0.8 ? 'good' : pct >= 0.6 ? 'ok' : 'bad';
  const lv = r.level || (pct >= 0.8 ? '优秀' : pct >= 0.6 ? '达标' : '待提升');
  const hasReq = !!(r.word_min && r.word_max);          // 老记录没存字数要求，别一律标红
  const wOk = !hasReq || (r.words >= r.word_min && r.words <= r.word_max);
  $('#slr-score').innerHTML = `
    <div class="slr-num"><b>${r.score}</b><span>/${r.full}</span></div>
    <div class="slr-pct ${grade}">${Math.round(pct * 100)}%</div>
    <div class="slr-stat">
      <span class="slr-dot good"></span>命中 ${r.hit_n || 0}
      <span class="slr-dot ok"></span>部分 ${r.part_n || 0}
      <span class="slr-dot bad"></span>未中 ${r.miss_n || 0}
      ${r.words ? `<span class="slr-w ${wOk ? '' : 'warn'}">${r.words} 字${hasReq ? ` / 要求 ${r.word_min}-${r.word_max}` : ''}</span>` : ''}
    </div>
    <div class="slr-lv ${grade}">${esc(lv)}</div>`;

  $('#slr-points').innerHTML = (r.points || []).map((p, i) => {
    const state = (p.misses && p.misses.length && !p.yours) ? 'bad'
      : ((p.partial && p.partial.length) || (p.misses && p.misses.length)) ? 'ok' : 'good';
    return `<div class="slp ${state}">
      <div class="slp-head"><span class="slp-no">${i + 1}</span>
        <span class="slp-name">${esc(p.name || '')}</span>
        <span class="slp-score">${p.got}<i>/${p.max}</i></span></div>
      ${p.yours ? `<div class="slp-yours"><b>你的：</b>${esc(p.yours)}</div>`
      : `<div class="slp-yours slp-none">这一点没有作答</div>`}
      ${(p.hits || []).map(h => `<div class="slp-li hit">✓ ${esc(h)}</div>`).join('')}
      ${(p.partial || []).map(h => `<div class="slp-li part">— ${esc(h)}</div>`).join('')}
      ${(p.misses || []).map(h => `<div class="slp-li miss">✕ ${esc(h)}</div>`).join('')}
      ${p.material ? `<div class="slp-mat"><b>对照材料：</b>${esc(p.material)}</div>` : ''}
    </div>`;
  }).join('') + ((r.advice || []).length ? `<div class="slr-advice"><div class="slt-sec">改进建议</div><ul>`
    + r.advice.map(a => `<li>${esc(a)}</li>`).join('') + `</ul></div>` : '');

  const rw = r.ref_words || slWords(r.reference);
  const refOk = !hasReq || (rw >= r.word_min && rw <= r.word_max);
  // 范文是批改之外的一次独立 AI 调用，超时就会是空的 → 给个单独重生成的按钮，不用重跑整份批改
  $('#slr-ref').innerHTML = r.reference
    ? `<div class="slt-sec">参考范文（${esc(r.type_name || '')}）</div>
       <div class="slr-wtag ${refOk ? '' : 'warn'}">${rw} 字${hasReq ? ` · 题目要求 ${r.word_min}-${r.word_max} 字` : ''}</div>
       <div class="slr-reftext">${esc(r.reference).replace(/\n/g, '<br>')}</div>`
    : `<div class="slt-sec">参考范文（${esc(r.type_name || '')}）</div>
       <p class="empty">这次没生成出范文（生成范文是批改之外单独的一次 AI 调用，超时/失败就会空着）。<br>
       点下面的按钮单独重生成，不用重跑整份批改。</p>
       ${r.id ? `<button class="btn primary" id="slr-regen" data-rid="${r.id}">🔄 重新生成参考范文</button>` : ''}`;

  $('#slr-orig').innerHTML = `<div class="slt-sec">题干</div>
    <div class="slr-reftext">${esc(r.question || '').replace(/\n/g, '<br>')}</div>
    <div class="slt-sec">给定资料</div>
    <div class="slr-reftext slr-mat">${esc(r.material || '（本次批改没有提供给定资料）').replace(/\n/g, '<br>')}</div>`;

  $('#slr-mine').innerHTML = `<div class="slt-sec">作答原文</div>
    <div class="slr-wtag ${wOk ? '' : 'warn'}">${r.words || slWords(r.answer)} 字${hasReq ? ` · 要求 ${r.word_min}-${r.word_max} 字` : ''}</div>
    <div class="slr-reftext">${esc(r.answer || '').replace(/\n/g, '<br>')}</div>`;
  slrTab('points');
  window.scrollTo(0, 0);
}
function slrTab(t) {
  document.querySelectorAll('.slr-tabs .tk-tab').forEach(x => x.classList.toggle('active', x.dataset.slrt === t));
  ['points', 'ref', 'orig', 'mine'].forEach(k => $('#slr-' + k).classList.toggle('hidden', k !== t));
}
document.querySelector('.slr-tabs').addEventListener('click', e => {
  const b = e.target.closest('[data-slrt]'); if (b) slrTab(b.dataset.slrt);
});
$('#slr-ref').addEventListener('click', async e => {
  const b = e.target.closest('#slr-regen'); if (!b) return;
  b.disabled = true; b.textContent = '生成中…（约 30 秒）';
  try {
    const d = await api('/api/shenlun/record/' + b.dataset.rid + '/reference', { method: 'POST' });
    await openSlRecord(b.dataset.rid);
    toast('范文已生成（' + d.ref_words + ' 字）');
  } catch (err) {
    toast(err.message, true);
    b.disabled = false; b.textContent = '🔄 重新生成参考范文';
  }
});

/* ================= 常考（高频考点合集） + 上位词 ================= */
async function openChangkao() {
  push({ view: 'changkao', title: '常考' });
  loadCkBoards();
  loadHyperDaily();
}
async function loadCkBoards() {
  $('#ck-boards').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/changkao/boards');
    let nStar = 0;
    try { nStar = (await api('/api/changkao/stars')).total; } catch (_) {}
    $('#ck-boards').innerHTML = '<div class="home-cards cs-cards" data-dragsort="ckb">' + d.boards.map(b => `
      <div class="home-card ck-card" data-ckb="${esc(b.key)}">
        <div class="hc-logo hc-ck">${IC[b.icon] || IC.bulb}</div>
        <div class="hc-name">${esc(b.name)}</div>
        <div class="hc-desc">${b.count} 条 · ${esc(b.desc)}</div>
      </div>`).join('') + `
      <div class="home-card ck-card ck-star-card" data-ckb="收藏">
        <div class="hc-logo hc-star">★</div>
        <div class="hc-name">我的收藏</div>
        <div class="hc-desc">${nStar} 条 · 六个模块收藏的都在这</div>
      </div>` + '</div>';
  } catch (e) { $('#ck-boards').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#ck-boards').addEventListener('click', e => {
  const c = e.target.closest('[data-ckb]'); if (c) openCkBoard(c.dataset.ckb);
});
async function loadHyperDaily() {
  try {
    const d = await api('/api/hyper/daily');
    if (!d.items || !d.items.length) { $('#ck-daily').classList.add('hidden'); return; }
    $('#ck-daily').innerHTML = `<div class="ckd-tag">🎯 今日推荐 · 上位词</div>` +
      d.items.map(it => `<div class="ckd-item" data-ckd="${it.id}">
        <div class="ckd-h">${esc(it.hyper)}</div>
        <div class="ckd-s">${esc(it.subs || '')}</div>
        ${it.note ? `<div class="ckd-n">${esc(it.note)}</div>` : ''}
      </div>`).join('');
    $('#ck-daily').classList.remove('hidden');
  } catch (_) { $('#ck-daily').classList.add('hidden'); }
}
$('#ck-daily').addEventListener('click', () => openCkBoard('上位词'));

let ckBoard = '', ckItems = [], ckKind = 'text';
async function openCkBoard(key) {
  ckBoard = key;
  await loadCkStarred();                        // 六个模块都要标★
  push({ view: 'ckboard', title: key === '上位词' ? '上位词积累' : (key === '收藏' ? '我的收藏' : '常考 · ' + key) });
  $('#ckb-search').value = '';
  $('#ckb-ai').classList.toggle('hidden', key !== '上位词');
  $('#ckb-head').innerHTML = '';
  $('#ckb-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    if (key === '收藏') {
      const d = await api('/api/changkao/stars');
      ckItems = d.boards.flatMap(b => b.items.map(x =>
        ({ id: x.item_id, title: x.title, content: x.content, note: x.note, _b: b.board })));
      ckKind = 'star';
      $('#ckb-head').innerHTML = `<span class="ckb-n">${d.total} 条</span>` +
        '<span class="ckb-tip">再点一次 ★ 取消收藏</span>';
      renderCkList();
      return;
    }
    const d = await api('/api/changkao/items?board=' + encodeURIComponent(key));
    ckItems = d.items; ckKind = d.kind;
    $('#ckb-head').innerHTML = `<span class="ckb-n">${d.items.length} 条</span>` +
      (key === '上位词' ? '<span class="ckb-tip">逻辑填空里题干出现上位词，答案必须与它同类</span>' : '');
    renderCkList();
  } catch (e) { $('#ckb-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
// 收藏是**六个模块通用**的（key = "板块:id"）。成语/实词额外同步进「成语词语积累」——
// 收藏就是为了拿去背，散在两处等于没收。
let ckStarred = new Set();
async function loadCkStarred() {
  try {
    const d = await api('/api/changkao/stars?ids=1');
    ckStarred = new Set(d.ids || []);
  } catch (_) {}
}
function renderCkList() {
  const q = $('#ckb-search').value.trim();
  const list = q ? ckItems.filter(it =>
    (it.title || '').includes(q) || (it.content || '').includes(q) || (it.note || '').includes(q)) : ckItems;
  if (!list.length) {
    $('#ckb-list').innerHTML = ckBoard === '收藏'
      ? '<p class="empty">还没收藏。进任一模块，点卡片上的 ☆ 就收进来了。</p>'
      : '<p class="empty">没有匹配的内容</p>';
    return;
  }
  $('#ckb-list').innerHTML = list.map(it => {
    const b = it._b || ckBoard;                       // 收藏页里每条来自不同板块
    const key = b + ':' + it.id;
    const on = ckStarred.has(key);
    const freq = it.freq && b === '成语' ? `<span class="cki-freq">考频 ${it.freq}</span>` : '';
    const note = (it.note || '').replace(/^考频 \d+ 次(\s·\s)?/, '');   // 考频已单独成徽章
    const tip = CK_TO_ENTRY[b] ? '收藏 → 同时收进「成语词语积累」' : '收藏';
    return `<div class="gk-card ck-item" data-cki="${it.id}" data-ckbd="${esc(b)}">
      <div class="cki-t">${esc(it.title)}${freq}
        ${ckBoard === '收藏' ? `<span class="cki-from">${esc(b)}</span>` : ''}
        <button class="cki-star${on ? ' on' : ''}" data-ckstar="${esc(b)}:${it.id}"
          title="${tip}">${on ? '★' : '☆'}</button>
        ${ckKind === 'hyper' ? `<button class="cki-del" data-ckdel="${it.id}">🗑</button>` : ''}</div>
      ${it.content ? `<div class="cki-c">${esc(it.content)}</div>` : ''}
      ${note ? `<div class="cki-n">${(ckKind === 'classic' || b === '古诗文') ? esc(note) : '💡 ' + esc(note)}</div>` : ''}
      ${(b === '上位词') ? '<div class="cki-more">点开看每个下位词的典故 / 出处 / 怎么考 ›</div>'
        : (b === '成语' || b === '实词') ? '<div class="cki-more">点开看典故 / 出处 / 怎么考 ›</div>' : ''}
    </div>`;
  }).join('');
}
// 这两类收藏时会同步进「言语理解 → 成语词语积累」的对应分类（服务端 CK_TO_ENTRY 也有一份）
const CK_TO_ENTRY = { '成语': '成语', '实词': '词语' };
$('#ckb-search').addEventListener('input', renderCkList);
$('#ckb-list').addEventListener('click', async e => {
  const star = e.target.closest('[data-ckstar]');
  if (star) {                                   // 收藏 / 取消收藏（六个模块通用）
    e.stopPropagation();
    const [b, id] = star.dataset.ckstar.split(':');
    star.disabled = true;
    try {
      const r = await api('/api/changkao/star', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ board: b, id: +id }),
      });
      if (r.starred) {
        ckStarred.add(b + ':' + id);
        star.textContent = '★'; star.classList.add('on');
        toast(r.to_entry ? `已收藏，并收进「成语词语积累 · ${r.category}」，明天开始进复习`
          : (CK_TO_ENTRY[b] ? '已收藏（「成语词语积累」里本来就有）' : '已收藏'));
      } else {
        ckStarred.delete(b + ':' + id);
        star.textContent = '☆'; star.classList.remove('on');
        toast('已取消收藏');
        if (ckBoard === '收藏') { openCkBoard('收藏'); return; }   // 收藏页里取消了就移走
      }
    } catch (err) { toast(err.message, true); }
    star.disabled = false;
    return;
  }
  const del = e.target.closest('[data-ckdel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('从上位词库中删除这一组？'))) return;
    try { await api('/api/hyper/' + del.dataset.ckdel, { method: 'DELETE' }); openCkBoard('上位词'); }
    catch (er) { toast(er.message, true); }
    return;
  }
  const it = e.target.closest('[data-cki]');
  if (!it) return;
  const b = it.dataset.ckbd || ckBoard;
  if (b === '古诗文') openClassicDetail(+it.dataset.cki);
  else if (b === '上位词') openHyper(+it.dataset.cki);              // 上位词：点开看典故/来源
  else if (b === '成语' || b === '实词') openCkStory(+it.dataset.cki);   // 成语/实词：点开看典故
});

/* 成语/实词的典故：出处原文 + 故事 + 本义怎么引申成今义 + 公考怎么考。
   看懂来历自然就记住了，不用死背释义。AI 讲一次就缓存，之后秒开。 */
async function openCkStory(cid) {
  push({ view: 'cdetail', title: '典故' });
  $('#cd-wrap').innerHTML = '<p class="empty">正在讲典故…（第一次约 20 秒，之后秒开）</p>';
  try {
    const d = await api('/api/changkao/' + cid + '/story');
    const s = d.story || {};
    $('#cd-wrap').innerHTML = `
      <div class="cd-head"><div class="cd-title">${esc(d.title)}</div>
        <div class="cd-meta">常考 · ${esc(d.board || '')}${d.freq ? ` · 考频 ${d.freq} 次` : ''}</div></div>
      ${d.content ? `<div class="cd-sec"><div class="cd-sec-t">释义</div><div class="cd-sec-b">${esc(d.content)}</div></div>` : ''}
      ${s.origin ? `<div class="cd-sec"><div class="cd-sec-t">📜 出处</div><div class="cd-sec-b ck-origin">${esc(s.origin)}</div></div>` : ''}
      ${s.story ? `<div class="cd-sec"><div class="cd-sec-t">📖 典故</div><div class="cd-sec-b ck-story">${esc(s.story)}</div></div>` : ''}
      ${s.evolve ? `<div class="cd-sec"><div class="cd-sec-t">🔗 本义 → 今义</div><div class="cd-sec-b">${esc(s.evolve)}</div></div>` : ''}
      ${s.usage ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">🎯 公考怎么考</div><div class="cd-sec-b">${esc(s.usage)}</div></div>` : ''}
      <div class="cd-sec" id="ck-ex"><div class="cd-sec-t">✍️ 例句</div>
        <div class="cd-sec-b"><button class="btn tiny" id="ck-ex-go" data-cid="${cid}">找一句真实例句</button>
        <span class="ck-ex-hint">先在人民日报等真语料里找；找不到才 AI 仿写（会标明）</span></div></div>
      <div class="cd-sec" id="ck-cf"><div class="cd-sec-t">⚖️ 易混辨析</div>
        <div class="cd-sec-b"><button class="btn tiny" id="ck-cf-go" data-cid="${cid}">辨析相似词</button>
        <span class="ck-ex-hint">逻辑填空考的就是「这几个近义词该用哪个」</span></div></div>`;
    window.scrollTo(0, 0);
    injectReadBtns();
    ckLoadExample(cid);          // 已经有例句就直接显示，不用点
    ckLoadConfuse(cid, true);
  } catch (e) {
    $('#cd-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>';
  }
}

/* ---- 例句：真语料优先（人民日报等），找不到才 AI 仿写并标明 ---- */
async function ckLoadExample(cid, force) {
  const box = $('#ck-ex'); if (!box) return;
  const btn = $('#ck-ex-go');
  if (!force && btn) { btn.disabled = true; btn.textContent = '查找中…'; }
  try {
    const d = await api(`/api/changkao/${cid}/example${force ? '?force=1' : ''}`);
    const ai = (d.src || '').startsWith('AI');
    box.querySelector('.cd-sec-b').innerHTML = `
      <div class="ck-ex">${esc(d.example)}</div>
      <div class="ck-ex-src ${ai ? 'ai' : 'real'}">${ai ? '✎' : '📰'} ${esc(d.src || '')}</div>`;
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = '找一句真实例句'; }
  }
}
document.addEventListener('click', e => {
  const b = e.target.closest('#ck-ex-go');
  if (b) { b.disabled = true; b.textContent = '查找中…'; ckLoadExample(+b.dataset.cid, true); }
});

/* ---- 易混辨析：给出 2~3 个最容易混的词，逐条说清「用哪个」 ---- */
async function ckLoadConfuse(cid, quiet) {
  const box = $('#ck-cf'); if (!box) return;
  try {
    const d = await api(`/api/changkao/${cid}/confuse${quiet ? '' : '?force=1'}`);
    if (quiet && !d.cached) return;         // 静默模式只显示已经生成过的，不主动烧 AI
    ckRenderConfuse(box, d);
  } catch (_) {}
}
function ckRenderConfuse(box, d) {
  const q = d.quiz;
  box.querySelector('.cd-sec-b').innerHTML = `
    ${d.key ? `<div class="ck-cf-key">🔑 ${esc(d.key)}</div>` : ''}
    ${(d.items || []).map(x => `
      <div class="ck-cf-i">
        <div class="ck-cf-w">${esc(d.word)} <i>vs</i>
          ${x.in_lib ? `<b class="ck-cf-go" data-ckcf="${x.id}">${esc(x.word)}</b>`
                     : `<b>${esc(x.word)}</b><span class="ck-cf-out">库外</span>`}</div>
        <div class="ck-cf-r"><span>词义侧重</span>${esc(x.focus || '')}</div>
        <div class="ck-cf-r"><span>感情色彩</span>${esc(x.color || '')}</div>
        <div class="ck-cf-r"><span>搭配对象</span>${esc(x.collocation || '')}</div>
        ${x.wrong ? `<div class="ck-cf-bad">✗ ${esc(x.wrong)}</div>` : ''}
      </div>`).join('')}
    ${q ? `<div class="ck-cf-quiz" data-ans="${esc(q.answer)}">
        <div class="ck-cf-q">📝 ${esc(q.stem)}</div>
        <div class="ck-cf-opts">${q.options.map((o, i) =>
          `<button class="dt-opt" data-ckq="${DT_L[i]}">${esc(o)}</button>`).join('')}</div>
        <div class="ck-cf-why hidden">${esc(q.why || '')}</div>
      </div>` : ''}`;
}
document.addEventListener('click', e => {
  const b = e.target.closest('#ck-cf-go');
  if (b) { b.disabled = true; b.textContent = '辨析中…（约 20 秒）'; ckLoadConfuse(+b.dataset.cid); return; }
  const g = e.target.closest('[data-ckcf]');
  if (g) { openCkStory(+g.dataset.ckcf); return; }        // 点对比词 → 直接看它的详情
  const o = e.target.closest('[data-ckq]');
  if (o) {                                                 // 填空自测：选完立刻判
    const box = o.closest('.ck-cf-quiz');
    const ans = box.dataset.ans;
    box.querySelectorAll('[data-ckq]').forEach(x => {
      x.disabled = true;
      if (x.dataset.ckq === ans) x.classList.add('correct');
      else if (x === o) x.classList.add('wrong');
    });
    box.querySelector('.ck-cf-why').classList.remove('hidden');
  }
});

/* 上位词详解：每个下位词的出处、典故、公考考点（AI 讲一次就缓存，之后秒开） */
async function openHyper(hid) {
  push({ view: 'cdetail', title: '上位词详解' });
  $('#cd-wrap').innerHTML = '<p class="empty">正在讲典故…（第一次要 30 秒左右，之后秒开）</p>';
  try {
    const d = await api('/api/hyper/' + hid);
    $('#cd-wrap').innerHTML = `
      <div class="cd-head"><div class="cd-title">${esc(d.hyper)}</div>
        <div class="cd-meta">上位词 · 逻辑填空里的概括词</div></div>
      <div class="cd-sec"><div class="cd-sec-t">下位词</div>
        <div class="cd-sec-b">${esc(d.subs || '')}</div></div>
      ${d.note ? `<div class="cd-sec"><div class="cd-sec-t">💡 提示</div><div class="cd-sec-b">${esc(d.note)}</div></div>` : ''}
      ${(d.story || []).map(x => `
        <div class="cd-sec hy-sec">
          <div class="cd-sec-t">${esc(x.name)}</div>
          ${x.origin ? `<div class="hy-row"><b>出处</b>${esc(x.origin)}</div>` : ''}
          ${x.story ? `<div class="hy-row hy-story"><b>典故</b>${esc(x.story)}</div>` : ''}
          ${x.point ? `<div class="hy-row hy-point"><b>怎么考</b>${esc(x.point)}</div>` : ''}
        </div>`).join('')}`;
    window.scrollTo(0, 0);
    injectReadBtns();
  } catch (e) {
    $('#cd-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>';
  }
}
$('#ckb-ai').onclick = async () => {
  const w = await appPrompt('AI 补充上位词', '输入一个词（如「戏曲」或「京剧」），AI 会归纳它的上位词与同类下位词');
  if (!w || !w.trim()) return;
  toast('AI 分析中…');
  try {
    const d = await api('/api/hyper/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ word: w.trim() }) });
    toast(d.cached ? '已在库中：' + d.hyper : '已收录：' + d.hyper);
    openCkBoard('上位词');
  } catch (e) { toast(e.message, true); }
};

/* ================= 理论基础（马原/毛概/中特/习思想） ================= */
async function openTheory() {
  push({ view: 'theory', title: '理论基础' });
  $('#th-boards').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/theory/boards');
    $('#th-boards').innerHTML = '<div class="home-cards cs-cards" data-dragsort="thb">' + d.boards.map(b => `
      <div class="home-card ck-card" data-thb="${esc(b.name)}">
        <div class="hc-logo hc-th">${IC[b.icon] || IC.book}</div>
        <div class="hc-name">${esc(b.short)}</div>
        <div class="hc-desc">${b.count} 条 · ${esc(b.desc)}</div>
      </div>`).join('') + '</div>';
  } catch (e) { $('#th-boards').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#th-boards').addEventListener('click', e => {
  const c = e.target.closest('[data-thb]'); if (c) openThBoard(c.dataset.thb);
});
async function openThBoard(name) {
  push({ view: 'thboard', title: name.length > 10 ? name.slice(0, 9) + '…' : name });
  $('#thb-head').innerHTML = ''; $('#thb-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/theory/items?board=' + encodeURIComponent(name));
    $('#thb-head').innerHTML = `<div class="thb-title">${esc(name)}</div>
      <div class="thb-desc">${esc(d.desc || '')}</div><span class="ckb-n">${d.count} 个考点</span>`;
    if (!d.topics.length) { $('#thb-list').innerHTML = '<p class="empty">内容生成中，稍后再来～</p>'; return; }
    $('#thb-list').innerHTML = d.topics.map(t => `
      <div class="th-topic"><div class="th-tname">${esc(t.name)}</div>
        ${t.items.map(it => `<div class="gk-card th-item">
          <div class="cki-t">${esc(it.title)}</div>
          <div class="cki-c">${emKey(it.content || '')}</div>
        </div>`).join('')}
      </div>`).join('');
  } catch (e) { $('#thb-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}


/* ============= 今日复习（艾宾浩斯遗忘曲线） ============= */
const RV_KIND = { entry: '成语词语', wrongq: '错题', classic: '古诗文' };
const RV_COLOR = { entry: '#2b6fd6', wrongq: '#b23b2e', classic: '#0f766e' };
const RV_INTERVALS = [1, 2, 4, 7, 15, 30, 60];
let rvQueue = [], rvTotal = 0, rvDoneN = 0;
/* 词语句子 / 每日积累 / 错题 各背各的，不混成一副牌 */
let rvAll = [], rvGroup = 'word';
const RV_GROUP_NAME = { word: '词语句子', daily: '每日积累', wrongq: '错题' };
/* 每日复习量：一天能背多少因人而异。堆太多就不想背了 —— 超出上限的**不会丢**，
   只是今天不出现（到期时间不变，明天照样在）。0 = 不限。 */
const RV_LNAME = { word: '词语句子', daily: '每日积累', wrongq: '错题' };
let rvLim = null, rvPool = null;
function rvLimRender() {
  if (!rvLim) return;
  $('#rv-lim-rows').innerHTML = Object.keys(RV_LNAME).map(k => `
    <div class="rv-lim-row">
      <label>${RV_LNAME[k]}</label>
      <input type="number" min="0" max="500" data-rvl="${k}" value="${rvLim[k]}">
      <span class="rv-lim-pool">到期 ${(rvPool || {})[k] || 0} 条${rvLim[k] ? '' : ' · 不限'}</span>
    </div>`).join('');
  $('#rv-limsum').textContent = Object.keys(RV_LNAME)
    .map(k => `${RV_LNAME[k]} ${rvLim[k] || '不限'}`).join(' · ');
}
$('#rv-limtog').onclick = async () => {
  const box = $('#rv-lim');
  const show = box.classList.contains('hidden');
  box.classList.toggle('hidden', !show);
  if (show && !rvLim) {
    try {
      const d = await api('/api/review/limits');
      rvLim = d.limits; rvPool = d.due; rvLimRender();
    } catch (e) { toast(e.message, true); }
  }
};
$('#rv-limsave').onclick = async () => {
  const body = {};
  document.querySelectorAll('[data-rvl]').forEach(i => { body[i.dataset.rvl] = Math.max(0, +i.value || 0); });
  const b = $('#rv-limsave'); b.disabled = true;
  try {
    const d = await api('/api/review/limits', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    rvLim = d.limits; rvLimRender();
    $('#rv-lim').classList.add('hidden');
    toast('已保存，今天按新的量出');
    loadReview();
  } catch (e) { toast(e.message, true); }
  b.disabled = false;
};

async function loadReview() {
  ['rv-empty', 'rv-card-wrap', 'rv-done'].forEach(id => $('#' + id).classList.add('hidden'));
  try {
    const d = await api('/api/review/today');
    rvAll = d.items || [];
    rvLim = d.limits || rvLim; rvPool = d.pool || rvPool;
    if (rvLim) rvLimRender();
    const g = d.groups || {};
    document.querySelectorAll('[data-rvg]').forEach(b => {
      const n = g[b.dataset.rvg] || 0;
      b.querySelector('.rv-n').textContent = n ? ' ' + n : '';
      b.classList.toggle('rv-empty-tab', !n);
    });
    if (!rvAll.length) { $('#rv-empty').classList.remove('hidden'); refreshReviewBadge(); return; }
    // 默认停在第一个有内容的板块
    if (!(g[rvGroup] > 0)) rvGroup = ['word', 'daily', 'wrongq'].find(k => g[k] > 0) || 'word';
    rvSelect(rvGroup);
  } catch (e) { toast(e.message, true); }
}
function rvSelect(group) {
  rvGroup = group;
  document.querySelectorAll('[data-rvg]').forEach(b => b.classList.toggle('active', b.dataset.rvg === group));
  rvQueue = rvAll.filter(it => it.group === group);
  rvTotal = rvQueue.length; rvDoneN = 0;
  $('#rv-done').classList.add('hidden');
  if (!rvTotal) {
    $('#rv-card-wrap').classList.add('hidden');
    $('#rv-empty').classList.remove('hidden');
    return;
  }
  $('#rv-empty').classList.add('hidden');
  $('#rv-card-wrap').classList.remove('hidden');
  rvShow();
}
$('#rv-tabs').addEventListener('click', e => {
  const b = e.target.closest('[data-rvg]'); if (b) rvSelect(b.dataset.rvg);
});
function openReview() { push({ view: 'review', title: '今日复习' }); loadReview(); }
function rvShow() {
  if (!rvQueue.length) {
    $('#rv-card-wrap').classList.add('hidden');
    $('#rv-done').classList.remove('hidden');
    refreshReviewBadge();
    return;
  }
  const it = rvQueue[0];
  $('#rv-bar').style.width = (rvTotal ? (rvDoneN / rvTotal * 100) : 0) + '%';
  $('#rv-pos').textContent = `已复习 ${rvDoneN} / ${rvTotal}`;
  $('#rv-round').textContent = `第 ${it.stage + 1} 轮`;
  $('#rvf-kind').textContent = RV_KIND[it.kind] || it.kind;
  $('#rvf-kind').style.background = RV_COLOR[it.kind] || '#666';
  $('#rvf-title').textContent = it.front || it.title;
  $('#rvf-sub').textContent = it.front_sub || '';
  $('#rvb-body').innerHTML = emKey(it.back || '');
  $('#rv-back').classList.add('hidden');
  $('#rvf-hint').classList.remove('hidden');
  $('#rv-btns').classList.add('hidden');
  const nd = RV_INTERVALS[Math.min(it.stage + 1, RV_INTERVALS.length - 1)];
  $('#rv-know-d').textContent = nd + ' 天后';
}
$('#rv-flash').addEventListener('click', e => {
  if (e.target.closest('.read-item-btn')) return;   // 朗读按钮不翻卡
  const back = $('#rv-back');
  const opening = back.classList.contains('hidden');
  back.classList.toggle('hidden', !opening);
  $('#rvf-hint').classList.toggle('hidden', opening);
  $('#rv-btns').classList.toggle('hidden', !opening);
  if (opening) rvEnsureExample();                   // 翻到背面：没例句就现去要一个
});

/* 例句懒加载：194 个词在真语料里找到了真句子（人民日报等），剩下的翻到时才让 AI 仿写 ——
   一次性给 990 个词都生成太浪费，你真背到哪个才给哪个。 */
async function rvEnsureExample() {
  const it = rvQueue[0];
  if (!it || it.kind !== 'changkao') return;                 // 只有常考的成语/实词有例句
  if ((it.back || '').includes('✍️ 例句')) return;           // 已经有了
  if (it._exLoading) return;
  it._exLoading = true;
  const box = $('#rvb-body');
  const tip = document.createElement('div');
  tip.className = 'rv-ex-load';
  tip.textContent = '正在找例句…';
  box.appendChild(tip);
  try {
    const d = await api('/api/changkao/' + it.id + '/example');
    const ai = (d.src || '').startsWith('AI');
    it.back = (it.back || '') + '\n\n✍️ 例句：' + d.example + (d.src ? '\n　　—— ' + d.src : '');
    tip.className = 'rv-ex';
    tip.innerHTML = `<div class="rv-ex-t">✍️ ${esc(d.example)}</div>
      <div class="ck-ex-src ${ai ? 'ai' : 'real'}">${ai ? '✎' : '📰'} ${esc(d.src || '')}</div>`;
  } catch (_) { tip.remove(); }
  it._exLoading = false;
}
async function rvAnswer(result) {
  const it = rvQueue.shift(); if (!it) return;
  try {
    await api('/api/review/done', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: it.kind, id: it.id, result }) });
  } catch (e) { toast(e.message, true); rvQueue.unshift(it); return; }
  if (result === 'forget') { it.stage = 0; rvQueue.push(it); }   // 忘记：今日重现（排到队尾）
  else {
    rvDoneN++;
    const i = rvAll.indexOf(it);
    if (i >= 0) rvAll.splice(i, 1);            // 从总表里去掉，各板块的角标才会跟着减
    rvUpdateCounts();
  }
  rvShow();
}
function rvUpdateCounts() {
  document.querySelectorAll('[data-rvg]').forEach(b => {
    const n = rvAll.filter(x => x.group === b.dataset.rvg).length;
    b.querySelector('.rv-n').textContent = n ? ' ' + n : '';
    b.classList.toggle('rv-empty-tab', !n);
  });
}
$('#rv-know').onclick = () => rvAnswer('know');
$('#rv-fuzzy').onclick = () => rvAnswer('fuzzy');
$('#rv-forget').onclick = () => rvAnswer('forget');

/* ============= 题库（四川省考卷面 · 练习模式） ============= */
let qz = { set: null, qs: [], idx: 0 };
$('#qz-list').addEventListener('click', async e => {
  const c = e.target.closest('[data-qset]'); if (!c) return;
  try {
    const d = await api('/api/quiz/sets/' + c.dataset.qset);
    qz = { set: d, qs: d.questions, idx: 0 };
    // 跳到第一道未作答的题
    const firstUndone = d.questions.findIndex(q => !q.my_choice);
    if (firstUndone > 0) qz.idx = firstUndone;
    push({ view: 'quizrun', title: d.name });
    renderQuiz();
  } catch (err) { toast(err.message, true); }
});
function renderQuiz() {
  const q = qz.qs[qz.idx];
  if (!q) { $('#qzr-wrap').innerHTML = '<p class="empty">没有题目</p>'; return; }
  const total = qz.qs.length;
  const doneN = qz.qs.filter(x => x.my_choice).length;
  const isSL = qz.set.kind === '申论';
  const answered = !!q.my_choice;
  // 材料可能是三种：图形推理的图（JSON figs）/ 资料分析的表格·图表（JSON）/ 老的纯文字材料
  let mat = null;
  try { mat = q.material && q.material.trim().startsWith('{') ? JSON.parse(q.material) : null; } catch (_) { mat = null; }
  const isFig = !!(mat && mat.type === 'figs');
  let optHtml = '';
  if (isFig) {
    optHtml = '<div class="qz-opts qz-figs">' + (mat.opts || []).map((svg, j) => {
      const letter = DT_L[j];
      let cls = '';
      if (answered) {
        if (letter === q.answer) cls = ' right';
        else if (letter === q.my_choice) cls = ' wrong';
        else cls = ' dim';
      }
      return `<button class="qz-opt qz-figopt${cls}" data-opt="${letter}" ${answered ? 'disabled' : ''}>
        <span class="dt-figl">${letter}</span>${svg}</button>`;
    }).join('') + '</div>';
  } else if (!isSL) {
    optHtml = '<div class="qz-opts">' + q.options.map(o => {
      const letter = (o || '').trim().slice(0, 1).toUpperCase();
      let cls = '';
      if (answered) {
        if (letter === q.answer) cls = ' right';
        else if (letter === q.my_choice) cls = ' wrong';
        else cls = ' dim';
      }
      return `<button class="qz-opt${cls}" data-opt="${letter}" ${answered ? 'disabled' : ''}>${esc(o)}</button>`;
    }).join('') + '</div>';
  }
  const expl = (answered && !isSL)
    ? `<div class="cd-sec qz-expl"><div class="cd-sec-t">${q.my_choice === q.answer ? '✅ 回答正确' : '❌ 回答错误 · 正确答案 ' + esc(q.answer)}</div>
        <div class="cd-sec-b">${emKey(q.explanation || '')}</div></div>` : '';
  const slAns = isSL ? `
    <button class="btn primary" id="qz-showans" style="width:100%;padding:12px;margin-top:12px;">查看参考答案</button>
    <div class="cd-sec qz-expl hidden" id="qz-ansbox"><div class="cd-sec-t">📄 参考答案</div>
      <div class="cd-sec-b">${emKey(q.explanation || '')}</div></div>` : '';
  $('#qzr-wrap').innerHTML = `
    <div class="rv-progress"><div class="rv-bar" style="width:${doneN / total * 100}%"></div></div>
    <div class="rv-meta-row"><span>第 ${qz.idx + 1} / ${total} 题 · ${esc(q.module)}${q.qtype && q.qtype !== q.module ? '·' + esc(q.qtype) : ''}</span>
      <span>已做 ${doneN} · 对 ${qz.qs.filter(x => x.my_choice && x.my_choice === x.answer).length}</span></div>
    ${(mat && !isFig) ? (_dtLastMat = '', dtMaterial(mat, 'qz' + qz.idx))          /* 资料分析：真表格 / 图表 */
      : (q.material && !mat) ? `<div class="qz-mat"><div class="qz-mat-t">📋 ${isSL ? '给定资料' : '材料'}（上下滚动）</div><div class="qz-mat-b">${emKey(q.material)}</div></div>`
        : ''}
    <div class="gk-card"><div class="qz-q">${qz.idx + 1}. ${emKey(q.question)}</div>
      ${isFig ? `<div class="dt-seq">${(mat.seq || []).join('')}<span class="dt-qm">?</span></div>` : ''}
      ${optHtml}${slAns}</div>
    ${expl}
    <div class="qz-nav">
      <button class="btn" id="qz-prev" ${qz.idx === 0 ? 'disabled' : ''}>‹ 上一题</button>
      <button class="btn primary" id="qz-next" ${qz.idx >= total - 1 ? 'disabled' : ''}>下一题 ›</button>
    </div>`;
  window.scrollTo(0, 0);
}
$('#qzr-wrap').addEventListener('click', async e => {
  const chtb = e.target.closest('[data-chtb]');        // 资料分析图表下的「看数据表」
  if (chtb) {
    const box = $('#chtb-' + chtb.dataset.chtb);
    const hidden = box.classList.toggle('hidden');
    chtb.textContent = hidden ? '📋 看数据表' : '📊 收起数据表';
    return;
  }
  if (e.target.closest('#qz-prev')) { if (qz.idx > 0) { qz.idx--; renderQuiz(); } return; }
  if (e.target.closest('#qz-next')) { if (qz.idx < qz.qs.length - 1) { qz.idx++; renderQuiz(); } return; }
  if (e.target.closest('#qz-showans')) {
    $('#qz-ansbox').classList.remove('hidden');
    e.target.closest('#qz-showans').classList.add('hidden');
    return;
  }
  const opt = e.target.closest('.qz-opt');
  if (opt && !opt.disabled) {
    const q = qz.qs[qz.idx];
    try {
      const d = await api('/api/quiz/answer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ qid: q.id, choice: opt.dataset.opt }) });
      q.my_choice = opt.dataset.opt; q.answer = d.answer; q.explanation = d.explanation;
      renderQuiz();
      // 答错自动收进错题本
      if (!d.correct) {
        try {
          const fd = new FormData();
          fd.append('board', q.module === '申论' ? '申论' : q.module);
          fd.append('question', q.question + '\n' + (q.options || []).join('\n'));
          fd.append('answer', d.answer);
          fd.append('qtype', q.qtype || q.module);
          fd.append('points', ''); fd.append('note', '来自题库：' + qz.set.name);
          fd.append('analyze', '0');
          await api('/api/wrongq', { method: 'POST', body: fd });
          toast('已答错，这题自动收进错题本');
        } catch (_) { }
      }
    } catch (err) { toast(err.message, true); }
  }
});

/* ============= 经典著作（毛泽东选集） ============= */
let wkData = null;
async function openWorks() {
  push({ view: 'works', title: '经典著作' });
  $('#wk-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/works');
    $('#wk-list').innerHTML = d.items.map(it => `
      <div class="poly-card" data-work="${it.id}">
        <div class="poly-t" style="font-size:15.5px">${it.ord + 1}. ${esc(it.title)}</div>
        <div class="poly-meta">${esc(it.book)} · 约 ${(it.chars / 1000).toFixed(1)} 千字${it.has_ai ? ' · <span class="poly-ai-on">✓ 已有AI导读</span>' : ''}</div>
      </div>`).join('');
  } catch (e) { $('#wk-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#wk-list').addEventListener('click', e => {
  const c = e.target.closest('[data-work]'); if (c) openWorkDetail(+c.dataset.work);
});
async function openWorkDetail(id) {
  push({ view: 'workd', title: '精读' });
  $('#wk-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/works/' + id); wkData = d;
    stack[stack.length - 1].title = d.title; $('#top-title').textContent = d.title;
    renderWork();
  } catch (e) { $('#wk-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderWork() {
  const d = wkData;
  const ai = d.interpretation
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">🤖 AI 导读</div><div class="cd-sec-b">${mdToHtml(d.interpretation)}</div>
        <button class="btn cd-ai-regen" id="wk-regen">重新生成</button></div>`
    : `<div class="poly-genbox"><p class="cd-tip" style="margin:0 0 10px">让 AI 梳理这篇文章的写作背景、核心观点、名句与公考运用。</p>
        <button class="btn primary" id="wk-gen" style="width:100%;padding:12px;">🤖 生成 AI 导读</button></div>`;
  const body = (d.content || '').split('\n').filter(x => x.trim()).map(p => {
    const s2 = p.trim();
    return isDocHeading(s2) ? `<p class="poly-h">${emKey(s2)}</p>` : `<p>${emKey(s2)}</p>`;
  }).join('');
  $('#wk-wrap').innerHTML = `
    <div class="poly-head"><h2>${esc(d.title)}</h2>
      <div class="news-date">📕 ${esc(d.book)}</div></div>
    ${ai}
    <div class="poly-readert">全文</div>
    <div class="poly-reader">${body}</div>`;
}
$('#wk-wrap').addEventListener('click', async e => {
  const g = e.target.closest('#wk-gen') || e.target.closest('#wk-regen');
  if (!g) return;
  g.disabled = true; g.textContent = 'AI 导读生成中…（约二三十秒）';
  try {
    const d = await api('/api/works/' + wkData.id + '/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: g.id === 'wk-regen' }) });
    wkData.interpretation = d.content; renderWork(); toast('已生成');
  } catch (err) { toast(err.message, true); g.disabled = false; g.textContent = '🤖 生成 AI 导读'; }
});

/* ============= 常识积累（7板块 · 考情 + 高频考点） ============= */
const CS_COLOR = { '人文常识': '#b23b2e', '科技常识': '#2b6fd6', '法律常识': '#8c2f24', '地理常识': '#0f766e', '经济常识': '#c2671f', '公文常识': '#7a5cc0', '管理常识': '#5a6b85' };
let csBoard = '', csTopic = '';
async function openChangshi() {
  push({ view: 'changshi', title: '常识积累' });
  $('#cs-tiers').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/changshi/boards');
    $('#cs-tiers').innerHTML = d.tiers.map(t => `
      <div class="cs-tier-name">${esc(t.name)}</div>
      <div class="home-cards cs-cards" data-dragsort="csb:${esc(t.name)}">${t.boards.map(b => `
        <div class="home-card" data-csb="${esc(b.name)}">
          <div class="hc-logo" style="background:${CS_COLOR[b.name] || '#666'}">${esc(b.name[0])}</div>
          <div class="hc-name">${esc(b.name)}</div>
          <div class="hc-desc">${b.topics} 个专题 · ${b.count} 条考点</div>
        </div>`).join('')}</div>`).join('');
  } catch (e) { $('#cs-tiers').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#cs-tiers').addEventListener('click', e => {
  const c = e.target.closest('[data-csb]'); if (c) openCsBoard(c.dataset.csb);
});
function openCsBoard(board) {
  csBoard = board; csTopic = '';
  push({ view: 'csboard', title: board });
  loadCsBoard();
}
async function loadCsBoard() {
  $('#cs-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/changshi/board?board=' + encodeURIComponent(csBoard) + '&topic=' + encodeURIComponent(csTopic));
    csTopic = d.topic;
    $('#top-title').textContent = csBoard;
    $('#cs-ov-body').innerHTML = emKey(d.overview);
    $('#cs-topics').innerHTML = d.topics.map(t =>
      `<button class="chip ${t.name === csTopic ? 'active' : ''}" data-cst="${esc(t.name)}">${esc(t.name)}${t.count ? ' ' + t.count : ''}</button>`).join('');
    const tm = d.topics.find(t => t.name === csTopic) || {};
    $('#cs-kaoqing').innerHTML = `
      <div class="cs-kq">
        ${tm.tezheng ? `<div class="cs-kq-row"><b>题型特征</b>${emKey(tm.tezheng)}</div>` : ''}
        ${tm.silu ? `<div class="cs-kq-row"><b>破题思路</b>${emKey(tm.silu)}</div>` : ''}
        ${tm.map ? `<div class="cs-kq-row cs-kq-map"><b>要点导图</b>${emKey(tm.map)}</div>` : ''}
      </div>`;
    if (!d.items.length) {
      $('#cs-list').innerHTML = '<p class="empty">' + (d.daily ? '考点生成中，每天还会自动新增～' : '考点生成中，稍后再来看看～') + '</p>';
      return;
    }
    $('#cs-list').innerHTML = d.items.map(it => `
      <div class="gk-card">
        <div class="gk-head"><span class="poly-badge" style="background:${CS_COLOR[csBoard] || '#666'}">${esc(it.title)}</span>
          <span class="cs-date">${esc(it.date || '')}${it.source === '新法跟踪' ? ' · 新法跟踪' : ''}</span></div>
        <div class="sc-body">${emKey(it.content)}</div>
      </div>`).join('');
  } catch (e) { $('#cs-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#cs-topics').addEventListener('click', e => {
  const c = e.target.closest('[data-cst]'); if (!c) return;
  csTopic = c.dataset.cst; loadCsBoard();
});
$('#cs-ov-toggle').onclick = () => {
  const b = $('#cs-ov-body'); b.classList.toggle('hidden');
  $('#cs-ov-toggle').querySelector('.cs-ov-arrow').textContent = b.classList.contains('hidden') ? '▾' : '▴';
};

/* ================= 时政要文库（重要文件全文 + AI 政策解读） ================= */
let polyData = null;
const POLY_COLOR = { '重要讲话': '#c81e1e', '党代会报告': '#b23b2e', '中央全会文件': '#8c2f24', '政府工作报告': '#2b6fd6', '中央一号文件': '#0f766e', '地方政府工作报告': '#7a5cc0', '五年规划': '#c2671f' };
async function openPolicyDocs() {
  push({ view: 'policydoc', title: '时政要文库' });
  $('#poly-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/policydocs');
    $('#poly-list').innerHTML = d.items.map(it => {
      const col = POLY_COLOR[it.category] || '#666';
      return `<div class="poly-card" data-poly="${it.id}">
        <span class="poly-badge" style="background:${col}">${esc(it.category)}</span>
        <div class="poly-t">${esc(it.title)}</div>
        <div class="poly-meta">全文约 ${(it.chars / 1000).toFixed(1)} 千字${it.has_ai ? ' · <span class="poly-ai-on">✓ 已有 AI 解读</span>' : ''}</div>
      </div>`;
    }).join('');
  } catch (e) { $('#poly-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#poly-list').addEventListener('click', e => {
  const c = e.target.closest('[data-poly]'); if (c) openPolicyDoc(+c.dataset.poly);
});
async function openPolicyDoc(id) {
  push({ view: 'policydocd', title: '要文精读' });
  $('#poly-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/policydocs/' + id); polyData = d;
    stack[stack.length - 1].title = d.title; $('#top-title').textContent = d.title;
    renderPolicyDoc();
  } catch (e) { $('#poly-wrap').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderPolicyDoc() {
  const d = polyData;
  const ai = d.interpretation
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">🤖 AI 政策解读</div><div class="cd-sec-b">${mdToHtml(d.interpretation)}</div>
        <button class="btn cd-ai-regen" id="poly-regen">重新生成</button></div>`
    : `<div class="poly-genbox"><p class="cd-tip" style="margin:0 0 10px">让 AI 提炼这份文件的核心要点、公考高频考点、可引用金句与答题运用。</p>
        <button class="btn primary" id="poly-gen" style="width:100%;padding:12px;">🤖 生成 AI 政策解读</button></div>`;
  const body = (d.content || '').split('\n').filter(x => x.trim()).map(p => {
    const s = p.trim();
    return isDocHeading(s) ? `<p class="poly-h">${emKey(s)}</p>` : `<p>${emKey(s)}</p>`;
  }).join('');
  $('#poly-wrap').innerHTML = `
    <div class="poly-head"><h2>${esc(d.title)}</h2>
      <a class="poly-src" href="${esc(d.source_url)}" target="_blank" rel="noopener">原文来源 ↗</a></div>
    ${ai}
    <div class="poly-readert">全文</div>
    <div class="poly-reader">${body}</div>`;
}
$('#poly-wrap').addEventListener('click', async e => {
  const g = e.target.closest('#poly-gen') || e.target.closest('#poly-regen');
  if (!g) return;
  g.disabled = true; g.textContent = 'AI 解读生成中…（约二三十秒）';
  try {
    const d = await api('/api/policydocs/' + polyData.id + '/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: g.id === 'poly-regen' }) });
    polyData.interpretation = d.content; renderPolicyDoc(); toast('已生成');
  } catch (err) { toast(err.message, true); g.disabled = false; g.textContent = '🤖 生成 AI 政策解读'; }
});

/* ================= 党的创新理论学习词典（12371.cn） ================= */
let pdCat = '全部', pdTimer = null;
async function openPartyDict() {
  push({ view: 'partydict', title: '创新理论词典' });
  $('#pd-q').value = ''; pdCat = '全部';
  try {
    const d = await api('/api/partydict/cats');
    const chips = [`<button class="pd-chip on" data-cat="全部">全部 ${d.total}</button>`]
      .concat(d.cats.map(c => `<button class="pd-chip" data-cat="${esc(c.cat)}">${esc(c.cat)} ${c.count}</button>`));
    $('#pd-cats').innerHTML = chips.join('');
  } catch (e) {}
  loadPartyDict();
}
async function loadPartyDict() {
  const q = $('#pd-q').value.trim();
  $('#pd-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/partydict?cat=' + encodeURIComponent(pdCat) + '&q=' + encodeURIComponent(q));
    if (!d.items.length) { $('#pd-list').innerHTML = '<p class="empty">没有匹配的词条，换个关键词试试。</p>'; return; }
    $('#pd-list').innerHTML = d.items.map(it =>
      `<div class="pd-item"><div class="pd-term">${esc(it.term)}<span class="pd-tag">${esc(it.cat)}</span></div>
        <div class="pd-body">${emKey(it.content)}</div></div>`).join('');
  } catch (e) { $('#pd-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#pd-cats').addEventListener('click', e => {
  const b = e.target.closest('.pd-chip'); if (!b) return;
  pdCat = b.dataset.cat;
  $('#pd-cats').querySelectorAll('.pd-chip').forEach(x => x.classList.toggle('on', x === b));
  loadPartyDict();
});
$('#pd-q').addEventListener('input', () => { clearTimeout(pdTimer); pdTimer = setTimeout(loadPartyDict, 250); });
// 背诵模式：隐藏释义、点卡片显示/收起
let pdRecite = false;
$('#pd-recite').onclick = () => {
  pdRecite = !pdRecite;
  $('#pd-list').classList.toggle('reciting', pdRecite);
  $('#pd-recite').classList.toggle('on', pdRecite);
  $('#pd-recite').textContent = pdRecite ? '✓ 背诵中' : '🎯 背诵模式';
  $('#pd-recite-hint').classList.toggle('hidden', !pdRecite);
  $('#pd-list').querySelectorAll('.pd-item.revealed').forEach(x => x.classList.remove('revealed'));
};
$('#pd-list').addEventListener('click', e => {
  if (!pdRecite) return;
  const it = e.target.closest('.pd-item'); if (it) it.classList.toggle('revealed');
});

/* 桌面版（GTK/WebKit）没有 speechSynthesis，朗读要借壳调系统 TTS */
const deskTTS = () => !!(window.__desktopTTS && window.webkit && window.webkit.messageHandlers
  && window.webkit.messageHandlers.gk);
function deskMsg(o) {
  try { window.webkit.messageHandlers.gk.postMessage(JSON.stringify(o)); } catch (_) {}
}
// 引擎：piper=离线神经语音（默认，不联网、起声快）／edge=微软在线（音质最好，要联网）
// ⚠️ 曾经有第三档「系统默认」= speech-dispatcher，已删除：它的 PulseAudio 输出模块会段错误
//    （内核日志实锤 spd_pulse.so segfault），是 Ubuntu 自带组件的 bug，点一下就把朗读弄挂。
const TTS_ENGS = [
  { id: 'piper', name: 'Piper 离线', desc: '本机合成，不联网，起声快' },
  { id: 'edge', name: '微软在线', desc: '音质最自然，需要联网' },
];
const TTS_VOICES = [
  { id: 'zh-CN-XiaoxiaoNeural', name: '晓晓（女）' },
  { id: 'zh-CN-YunxiNeural', name: '云希（男）' },
  { id: 'zh-CN-XiaoyiNeural', name: '晓伊（女·活泼）' },
  { id: 'zh-CN-YunjianNeural', name: '云健（男·浑厚）' },
];
const ttsHas = (id) => (window.__ttsEngines || []).includes(id);
const ttsEng = () => {
  const v = localStorage.getItem('ttsEngine');
  if (v && ttsHas(v)) return v;
  return (TTS_ENGS.find(e => ttsHas(e.id)) || {}).id || 'piper';
};
const ttsVoice = () => localStorage.getItem('ttsVoice') || TTS_VOICES[0].id;
const deskSay = (text, rate, id) =>
  deskMsg({ a: 'tts', text, rate, id, engine: ttsEng(), voice: ttsVoice() });
const deskStop = () => { if (deskTTS()) deskMsg({ a: 'tts_stop' }); };
// 壳读完一段会回调这里（比按字数估时长准，段间衔接才不断不叠）
window.__ttsEnd = (id) => { const f = window.Reader && Reader._deskCb; if (f && id === Reader._deskId) f(); };

/* 账户页「朗读音色」：只有桌面版有得选（手机走安卓 TTS，网页走浏览器自带） */
function ttsSetup() {
  const sec = $('#acct-tts'); if (!sec) return;
  const engs = TTS_ENGS.filter(e => ttsHas(e.id));
  sec.classList.toggle('hidden', !deskTTS() || engs.length < 2);
  if (!deskTTS()) return;
  const cur = ttsEng();
  $('#tts-eng-row').innerHTML = engs.map(e =>
    `<button class="theme-opt tts-opt${e.id === cur ? ' on' : ''}" data-tts="${e.id}" title="${e.desc}">${e.name}</button>`).join('');
  const vs = $('#tts-voice');
  vs.classList.toggle('hidden', cur !== 'edge');       // 音色只有微软在线那档能挑
  vs.innerHTML = TTS_VOICES.map(v =>
    `<option value="${v.id}"${v.id === ttsVoice() ? ' selected' : ''}>${v.name}</option>`).join('');
}
document.addEventListener('click', e => {
  const b = e.target.closest('.tts-opt');
  if (b) { localStorage.setItem('ttsEngine', b.dataset.tts); ttsSetup(); return; }
  if (e.target.closest('#tts-try')) {
    Reader.stop();
    deskSay('金无足赤，人无完人。这是朗读试听。', 1.0, '');
  }
});
document.addEventListener('change', e => {
  if (e.target.id === 'tts-voice') { localStorage.setItem('ttsVoice', e.target.value); }
});

/* ================= 逐条朗读（安卓 TTS 桥 / 浏览器 speechSynthesis） ================= */
// 会自动注入 🔊 按钮的内容条目选择器（新渲染的列表/卡片自动获得朗读按钮）
const READ_ITEM_SEL = '.gk-card, .pd-item, .poly-card, .cd-sec, .cd-body, .item, .poly-reader, #viewer-reader, .cs-ov-body, .cs-kq, .ai-msg.assistant, .sc-body-solo, .rv-flash';
const READ_RATES = [1.0, 1.2, 1.5, 0.8];
window.Reader = {
  playing: false, segs: [], idx: 0, gen: 0, rateIdx: 0, card: null,
  native() { return !!(window.GongkaoNative && window.GongkaoNative.ttsSpeak); },
  rate() { return READ_RATES[this.rateIdx]; },
  split(text) {
    // 按句切分（细粒度：切语速时从当前句继续，不用重头）；超长句再按逗号拆
    const t = (text || '').replace(/\s+/g, ' ').trim();
    const sents = t.split(/(?<=[。！？；.!?;\n])/);
    const segs = [];
    for (let s of sents) {
      s = s.trim(); if (!s) continue;
      if (s.length <= 120) { segs.push(s); continue; }
      let cur = '';
      for (const p of s.split(/(?<=[，,、])/)) {
        if ((cur + p).length > 120) { if (cur.trim()) segs.push(cur.trim()); cur = p; }
        else cur += p;
      }
      if (cur.trim()) segs.push(cur.trim());
    }
    return segs;
  },
  textOf(card) {
    const c = card.cloneNode(true);
    c.querySelectorAll('button, .read-item-btn, .item-actions, .news-star, .iconbtn, .rv-stage').forEach(x => x.remove());
    return c.innerText || '';
  },
  readCard(card) {
    if (this.card === card && this.playing) { this.stop(); return; }  // 再点同一条 = 停止
    this.stop();
    const segs = this.split(this.textOf(card));
    if (!segs.length) { toast('这一条没有可朗读的文字', true); return; }
    this.card = card; card.classList.add('reading-src');
    this.segs = segs; this.idx = 0; this.playing = true;
    this.ui(); this.next();
  },
  next() {
    if (!this.playing) return;
    if (this.idx >= this.segs.length) { this.stop(); return; }
    const myGen = ++this.gen; const seg = this.segs[this.idx];
    if (this.native()) {
      this._waitId = 'r' + myGen;
      try { window.GongkaoNative.ttsSpeak(this._waitId, seg, this.rate()); }
      catch (_) { this.stop(); }
    } else if (deskTTS()) {
      // 电脑桌面版：WebKit 根本没有 speechSynthesis，借壳去调系统 TTS（Piper/微软/espeak）。
      // 壳读完这段会回调 __ttsEnd，接着读下一段；超时只是兜底（万一壳挂了不至于卡死）。
      const adv = () => {
        if (!this.playing || myGen !== this.gen) return;
        clearTimeout(this._deskT); this._deskCb = null;
        this.idx++; this.next();
      };
      this._deskId = 'r' + myGen; this._deskCb = adv;
      deskSay(seg, this.rate(), this._deskId);
      this._deskT = setTimeout(adv, Math.max(4000, seg.length * 600 / this.rate()));
    } else if (window.speechSynthesis) {
      const u = new SpeechSynthesisUtterance(seg);
      u.lang = 'zh-CN'; u.rate = this.rate();
      u.onend = () => { if (this.playing && myGen === this.gen) { this.idx++; this.next(); } };
      u.onerror = () => { if (this.playing && myGen === this.gen) { this.idx++; this.next(); } };
      speechSynthesis.speak(u);
    } else { toast('当前环境不支持语音朗读', true); this.stop(); }
  },
  reRate() {
    // 调语速：取消当前发声，但 idx 不动 → 从当前这句接着读，不从头
    if (!this.playing) return;
    this.gen++;
    try { if (this.native()) window.GongkaoNative.ttsCancel(); } catch (_) {}
    try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch (_) {}
    deskStop(); clearTimeout(this._deskT); this._deskCb = null;
    setTimeout(() => this.next(), 60);
  },
  stop() {
    this.playing = false; this.gen++; this.segs = []; this.idx = 0;
    if (this.card) { this.card.classList.remove('reading-src'); this.card = null; }
    try { if (this.native()) window.GongkaoNative.ttsCancel(); } catch (_) {}
    try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch (_) {}
    deskStop(); clearTimeout(this._deskT); this._deskCb = null;
    this.ui();
  },
  ui() {
    $('#read-ctrl').classList.toggle('hidden', !this.playing);
    $('#read-rate').textContent = this.rate().toFixed(1) + '×';
  },
};
// 安卓 TTS 段落结束回调
window.__ttsEvent = function (id, ev) {
  if (ev === 'end' && Reader.playing && id === Reader._waitId) { Reader.idx++; Reader.next(); }
};
$('#read-stop').onclick = () => Reader.stop();
$('#read-rate').onclick = () => {
  Reader.rateIdx = (Reader.rateIdx + 1) % READ_RATES.length;
  $('#read-rate').textContent = Reader.rate().toFixed(1) + '×';
  Reader.reRate();
};
// 自动给内容条目注入 🔊 朗读按钮（MutationObserver 覆盖所有现在/将来渲染的列表）
const READ_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>';
const SHARE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.6" y1="10.5" x2="15.4" y2="6.5"/><line x1="8.6" y1="13.5" x2="15.4" y2="17.5"/></svg>';
async function shareCard(card) {
  const text = (Reader.textOf(card) || '').trim();
  if (!text) { toast('这一条没有可分享的文字', true); return; }
  const payload = text + '\n\n—— 来自「公考助手」';
  try {
    if (window.GongkaoNative && typeof GongkaoNative.share === 'function') { GongkaoNative.share(payload); return; }
  } catch (_) {}
  if (navigator.share) {
    try { await navigator.share({ text: payload }); return; } catch (e) { if (e && e.name === 'AbortError') return; }
  }
  // 剪贴板兜底（旧 APK / 无分享面板环境）
  let copied = false;
  try { await navigator.clipboard.writeText(payload); copied = true; } catch (_) {}
  if (!copied) {
    try {
      const ta = document.createElement('textarea');
      ta.value = payload; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      copied = document.execCommand('copy'); ta.remove();
    } catch (_) {}
  }
  toast(copied ? '已复制内容，去微信等应用粘贴即可（更新 APK 后可直接弹分享面板）' : '分享失败', !copied);
}
/* ---- 朗读：两条路，覆盖所有带文字的地方（不放进悬浮球）----
   ① 卡片/整篇上的 🔊 —— READ_ITEM_SEL 里已经包含 .poly-reader / #viewer-reader / .cd-body
      这些整篇容器，所以「读整篇」本来就有，不用再做一个「朗读本页」
   ② 选中一段文字 —— 冒出「🔊 朗读选中」，只读选中的那段 */
// 选中文字 → 冒出朗读气泡（手写笔/鼠标划选都行）
let _selBub = null;
function selBubHide() { if (_selBub) { _selBub.remove(); _selBub = null; } }
document.addEventListener('selectionchange', () => {
  clearTimeout(window._selT);
  window._selT = setTimeout(() => {
    const sel = window.getSelection();
    const txt = sel && String(sel).trim();
    if (!txt || txt.length < 6 || sel.isCollapsed) { selBubHide(); return; }
    // 输入框里的选中不算（那是在编辑，不是在读）
    const a = sel.anchorNode;
    if (a && a.parentElement && a.parentElement.closest('input, textarea, [contenteditable]')) return;
    let r;
    try { r = sel.getRangeAt(0).getBoundingClientRect(); } catch (_) { return; }
    if (!r || (!r.width && !r.height)) return;
    if (!_selBub) {
      _selBub = document.createElement('button');
      _selBub.className = 'sel-read';
      _selBub.innerHTML = '🔊 朗读选中';
      _selBub.onmousedown = e => e.preventDefault();     // 别把选区点没了
      _selBub.onclick = () => {
        const t = String(window.getSelection()).trim();
        selBubHide();
        if (!t) return;
        Reader.stop();
        Reader.segs = Reader.split(t); Reader.idx = 0; Reader.playing = true;
        Reader.card = null; Reader.ui(); Reader.next();
      };
      document.body.appendChild(_selBub);
    }
    const top = r.top - 42 < 6 ? r.bottom + 8 : r.top - 42;
    _selBub.style.left = Math.max(8, Math.min(window.innerWidth - 110, r.left + r.width / 2 - 52)) + 'px';
    _selBub.style.top = top + 'px';
  }, 220);
});
document.addEventListener('scroll', selBubHide, true);

function injectReadBtns() {
  document.querySelectorAll(READ_ITEM_SEL).forEach(card => {
    if (card.classList.contains('ai-typing')) return;  // 「思考中…」气泡不加按钮
    if (card.querySelector(':scope > .read-item-btn')) return;
    if (!(card.innerText || '').trim()) return;
    const b = document.createElement('button');
    b.className = 'read-item-btn'; b.title = '朗读这一条'; b.innerHTML = READ_ICON;
    b.onclick = e => { e.stopPropagation(); e.preventDefault(); Reader.readCard(card); };
    card.appendChild(b);
    const sb = document.createElement('button');
    sb.className = 'read-item-btn share-item-btn'; sb.title = '分享这一条'; sb.innerHTML = SHARE_ICON;
    sb.onclick = e => { e.stopPropagation(); e.preventDefault(); shareCard(card); };
    card.appendChild(sb);
  });
}
let _readInjTimer = null;
new MutationObserver(() => {
  clearTimeout(_readInjTimer);
  _readInjTimer = setTimeout(injectReadBtns, 120);
}).observe(document.body, { childList: true, subtree: true });
injectReadBtns();

/* ================= 账户 / 个人信息页 ================= */
async function openAccount() {
  push({ view: 'account', title: '账户' });
  try {
    const d = await api('/api/account');
    const qs = (await api('/api/sec_questions')).questions;
    $('#acct-name').textContent = d.username || (ME && ME.username) || '';
    $('#acct-email').textContent = d.email ? ('📧 ' + d.email) : '未绑定邮箱';
    $('#acct-role').textContent = (ME && ME.is_admin) ? '管理员' : '普通用户';
    $('#acct-email-in').value = d.email || '';
    $('#acct-secq').innerHTML = qs.map(q => `<option ${q === d.sec_question ? 'selected' : ''}>${esc(q)}</option>`).join('');
    $('#acct-oldpw').value = ''; $('#acct-newpw').value = ''; $('#acct-seca').value = '';
    $('#acct-app').classList.toggle('hidden', !(IN_APP || IS_DESKTOP));
    $('#acct-app-t').textContent = IS_DESKTOP ? '💻 桌面版' : '📱 App';
    document.querySelectorAll('#acct-app .apk-only')            // 通知/切服务器只有安卓壳有
      .forEach(b => b.classList.toggle('hidden', !IN_APP));
    $('#acct-app-hint').classList.toggle('hidden', !IS_DESKTOP);
    $('#acct-dver').textContent = 'v' + (DESKTOP_VER || '?');
    renderSkinPrev();
    ttsSetup();
    refreshNotifyBtn();
  } catch (e) { toast(e.message, true); }
}
$('#brand-logo').onclick = openAccount;
$('#account-btn').onclick = openAccount;
$('#home-btn').onclick = goHome;

$('#acct-email-save').onclick = async () => {
  try {
    await api('/api/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: $('#acct-email-in').value.trim() }) });
    const em = $('#acct-email-in').value.trim();
    $('#acct-email').textContent = em ? ('📧 ' + em) : '未绑定邮箱';
    toast('邮箱已保存');
  } catch (e) { toast(e.message, true); }
};
$('#acct-pw-save').onclick = async () => {
  const np = $('#acct-newpw').value;
  if (!np) { toast('请输入新密码', true); return; }
  try {
    await api('/api/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ new_password: np, old_password: $('#acct-oldpw').value }) });
    $('#acct-oldpw').value = ''; $('#acct-newpw').value = ''; toast('密码已修改');
  } catch (e) { toast(e.message, true); }
};
$('#acct-sec-save').onclick = async () => {
  if (!$('#acct-seca').value.trim()) { toast('请输入密保答案', true); return; }
  try {
    await api('/api/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sec_question: $('#acct-secq').value, sec_answer: $('#acct-seca').value }) });
    $('#acct-seca').value = ''; toast('密保已保存');
  } catch (e) { toast(e.message, true); }
};
$('#acct-refresh').onclick = () => {
  if (window.GongkaoNative && window.GongkaoNative.reload) { try { window.GongkaoNative.reload(); return; } catch (_) {} }
  location.reload();
};
$('#acct-server').onclick = () => { try { window.GongkaoNative && window.GongkaoNative.changeServer(); } catch (_) {} };
$('#acct-logout').onclick = doLogout;

/* ============= 多端自动同步：数据变了自动刷新当前视图，无需手动更新 ============= */
let _syncToken = null, _syncBusy = false;
const SYNC_REFRESH = {
  notes: () => { loadFeed(); loadFeedTags(); },
  materials: () => loadMaterials(),
  idiom: () => loadEntries(),
  kb: () => loadNotebooks(),
  wrongq: () => loadWrongq(),
  news: () => loadNews(),
  gaikuo: () => loadGaikuo(),
  gongwen: () => loadGongwen($('#gw-q').value.trim()),
  planlog: () => loadPlanLog(),
  partydict: () => loadPartyDict(),
  sucai: () => loadSucai(),
  write: () => loadWrite(),
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
  } catch (_) {} finally { _syncBusy = false; }
}
setInterval(checkSync, 30000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) checkSync(); });
window.addEventListener('focus', checkSync);

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
    const p = JSON.parse(localStorage.getItem('aifab') || 'null');
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
  function toggle() { dirs(); fab.classList.toggle('open'); }

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
      try { localStorage.setItem('aifab', JSON.stringify({ x: r.left, y: r.top })); } catch (_) {}
      dirs(); e.preventDefault(); e.stopPropagation();
    } else toggle();
  });
  main.addEventListener('click', e => { if (moved) { e.preventDefault(); e.stopPropagation(); moved = false; } }, true);

  $('#fab-ai').onclick = () => { fabClose(); openAI(); };
  $('#fab-note').onclick = () => { fabClose(); qnOpen(); };   // 📒 随手记（浮层，不跳走）
  $('#fab-pad').onclick = () => { fabClose(); padToggle(); };
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
    const url = location.origin + '/api/materials/' + id + '/download';
    try {
      if (window.GongkaoNative && typeof GongkaoNative.shareFile === 'function') {
        toast('正在准备分享…');
        GongkaoNative.shareFile(url, name);
        return;
      }
    } catch (_) {}
    // 兜底：分享/复制文件名+说明
    const card = document.createElement('div');
    card.innerText = '「' + name + '」（来自公考助手资料库）';
    shareCard(card);
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
  const mode = localStorage.getItem('theme') || 'auto';
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
  localStorage.setItem('theme', b.dataset.theme);
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
    if (key) localStorage.setItem('skipUpdate', key);   // 这一版说过「以后再说」就别再弹
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
  if (!manual && localStorage.getItem('skipUpdate') === key) return;
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
    if (!manual && localStorage.getItem('skipUpdate') === key) return;
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
    if (!manual && localStorage.getItem('skipUpdate') === key) return;
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
  try { setNtfDot((await api('/api/notifications/unread')).unread); } catch (_) {}
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

/* ================= 草稿纸（做题时演算用；只写不识别） =================
   笔/荧光笔/橡皮 · 数位板压感 · 撤销重做 · 多页 · 方格/横线纸 · 存为图片 ·
   自动保存到本地（切题、刷新、关掉再开都还在）。 */
/* 草稿纸随时可调用（悬浮球里点开），停靠位可拖：下/右/左/上/全屏 */
const PAD_DOCKS = ['bottom', 'right', 'left', 'top', 'full'];
const PAD_INK = '#1a2230';                              // 默认墨色（夜间自动转浅）
const PAD_COLORS = [PAD_INK, '#1a6fb5', '#c0392b', '#1e8449', '#f0a500'];
const PAD_BGICON = ['▢', '⊞', '☰'];                     // 空白 / 方格 / 横线
let padPages = [{ st: [], rd: [] }], padPg = 0;
let padTool = 'pen', padColor = PAD_INK, padSize = 3, padBg = 1;
let padCur = null, padDrawing = false, padSawPen = false, padSaveT = null, padInited = false;
let padCv, padCtx, padBase, padBaseCtx, padRaf = 0;
let padMode = 'scratch', padDraftId = null;     // scratch=做题时的随手草稿纸(存本地)；draft=草稿本(存服务器)

const padDark = () => document.body.classList.contains('dark');
const padW = () => padCv.clientWidth || 1;
const padCol = (c, dark) => (c === PAD_INK && dark) ? '#e8edf5' : c;

function padPt(e) {
  const r = padCv.getBoundingClientRect(), w = r.width || 1;
  return {
    x: (e.clientX - r.left) / w, y: (e.clientY - r.top) / w,      // 按宽度归一化：换屏/全屏不变形
    p: (e.pointerType === 'pen' && e.pressure > 0) ? e.pressure : 0,
  };
}

function padPaper(ctx, w, h, dark) {
  ctx.save();
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = dark ? '#0f141e' : '#fff';
  ctx.fillRect(0, 0, w, h);
  if (padBg) {                                                    // 0=空白 1=方格 2=横线
    ctx.strokeStyle = dark ? 'rgba(160,180,210,.13)' : 'rgba(30,70,130,.10)';
    ctx.lineWidth = 1;
    const g = 26;
    ctx.beginPath();
    for (let y = g; y < h; y += g) { ctx.moveTo(0, y + .5); ctx.lineTo(w, y + .5); }
    if (padBg === 1) for (let x = g; x < w; x += g) { ctx.moveTo(x + .5, 0); ctx.lineTo(x + .5, h); }
    ctx.stroke();
  }
  ctx.restore();
}

function padDraw(ctx, s, W, dark) {
  const pts = s.pts;
  if (!pts || !pts.length) return;
  ctx.save();
  ctx.lineJoin = ctx.lineCap = 'round';
  const base = s.size * W;                                        // 归一化粗细 → 当前屏幕像素
  let wid = base;
  if (s.tool === 'eraser') {
    ctx.globalCompositeOperation = 'destination-out';             // 只擦笔迹，不擦纸上的格子
    ctx.strokeStyle = '#000'; wid = base * 5;
  } else {
    ctx.strokeStyle = padCol(s.color, dark);
    if (s.tool === 'hl') { ctx.globalAlpha = .3; wid = base * 3.2; }
  }
  if (pts.length === 1) {                                         // 点一下 = 一个点
    ctx.beginPath(); ctx.arc(pts[0].x * W, pts[0].y * W, Math.max(.6, wid / 2), 0, 6.2832);
    ctx.fillStyle = ctx.strokeStyle; ctx.fill(); ctx.restore(); return;
  }
  const varW = s.tool === 'pen' && pts.some(p => p.p > 0);        // 数位板：有压感就逐段变粗细
  if (!varW) {
    ctx.lineWidth = wid;
    ctx.beginPath(); ctx.moveTo(pts[0].x * W, pts[0].y * W);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x * W, pts[i].y * W);
    ctx.stroke();
  } else {
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i];
      ctx.lineWidth = wid * (.35 + 1.1 * (((a.p || .5) + (b.p || .5)) / 2));
      ctx.beginPath(); ctx.moveTo(a.x * W, a.y * W); ctx.lineTo(b.x * W, b.y * W); ctx.stroke();
    }
  }
  ctx.restore();
}

function padPaint() {                                             // 纸 + 已完成图层 + 正在画的这笔
  const w = padCv.clientWidth, h = padCv.clientHeight;
  padPaper(padCtx, w, h, padDark());
  padCtx.drawImage(padBase, 0, 0, w, h);
  if (padCur) padDraw(padCtx, padCur, padW(), padDark());
}
function padRebuild() {                                           // 重建"已完成"图层（撤销/翻页/换主题/改尺寸后）
  padBaseCtx.save();
  padBaseCtx.setTransform(1, 0, 0, 1, 0, 0);
  padBaseCtx.clearRect(0, 0, padBase.width, padBase.height);
  padBaseCtx.restore();
  const dark = padDark(), W = padW();
  for (const s of padPages[padPg].st) padDraw(padBaseCtx, s, W, dark);
  padPaint(); padSyncUI();
}
function padFit() {
  const w = padCv.clientWidth, h = padCv.clientHeight;
  $('#pad').classList.toggle('narrow', $('#pad').clientWidth < 470);   // 纸窄了工具栏就用紧凑排版
  if (!w || !h) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  padCv.width = padBase.width = Math.round(w * dpr);
  padCv.height = padBase.height = Math.round(h * dpr);
  padCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  padBaseCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  padRebuild();
}

function padDown(e) {
  if (e.pointerType === 'pen') padSawPen = true;
  if (e.pointerType === 'touch' && padSawPen) return;             // 用过笔之后忽略触摸 = 防手掌误触
  if (e.button > 0) return;
  e.preventDefault();
  try { padCv.setPointerCapture(e.pointerId); } catch (_) {}
  padDrawing = true;
  padCur = { tool: padTool, color: padColor, size: padSize / padW(), pts: [padPt(e)] };
  padPaint();
}
function padMove(e) {
  if (!padDrawing || !padCur) return;
  e.preventDefault();
  // 高频合并采样能让线更顺；但有的实现（含部分 WebKit）会返回空表，那就退回事件本身，
  // 否则一笔只剩落笔那个点，画出来是个小点。
  let evs = [];
  try { if (e.getCoalescedEvents) evs = e.getCoalescedEvents(); } catch (_) {}
  if (!evs.length) evs = [e];
  for (const ev of evs) padCur.pts.push(padPt(ev));
  if (!padRaf) padRaf = requestAnimationFrame(() => { padRaf = 0; padPaint(); });
}
function padUp() {
  if (!padDrawing) return;
  padDrawing = false;
  if (!padCur) return;
  const pg = padPages[padPg];
  pg.st.push(padCur); pg.rd = [];                                 // 新落笔 → 清空重做栈
  padDraw(padBaseCtx, padCur, padW(), padDark());
  padCur = null;
  padPaint(); padSyncUI(); padSaveSoon();
}

function padUndo() { const p = padPages[padPg]; if (!p.st.length) return; p.rd.push(p.st.pop()); padRebuild(); padSaveSoon(); }
function padRedo() { const p = padPages[padPg]; if (!p.rd.length) return; p.st.push(p.rd.pop()); padRebuild(); padSaveSoon(); }
function padGo(i) { padPg = Math.max(0, Math.min(padPages.length - 1, i)); padCur = null; padRebuild(); padSaveSoon(); }

function padSyncUI() {
  const pg = padPages[padPg];
  $('#pad-pg').textContent = (padPg + 1) + ' / ' + padPages.length;
  $('#pad-undo').disabled = !pg.st.length;
  $('#pad-redo').disabled = !pg.rd.length;
  $('#pad-prev').disabled = padPg === 0;
  $('#pad-next').disabled = padPg >= padPages.length - 1;
  $('#pad-bg').textContent = PAD_BGICON[padBg];
  $('#pad-size').value = padSize;
  document.querySelectorAll('#pad .pad-t[data-tool]').forEach(b => b.classList.toggle('on', b.dataset.tool === padTool));
  $('#pad-colors').innerHTML = PAD_COLORS.map(c =>
    `<i class="pad-c${c === padColor && padTool !== 'eraser' ? ' on' : ''}" data-c="${c}" style="background:${padCol(c, padDark())}"></i>`).join('');
}

/* 笔迹存储格式：本地「随手草稿纸」和云端「草稿本」共用（坐标已按画布宽度归一化） */
function padData() {
  const r = (n) => Math.round(n * 1e4) / 1e4;
  return {
    bg: padBg,
    pages: padPages.map(p => ({
      st: p.st.map(s => ({ t: s.tool, c: s.color, w: r(s.size), p: s.pts.map(q => [r(q.x), r(q.y), Math.round((q.p || 0) * 100) / 100]) })),
    })),
  };
}
function padSetData(d) {
  const ps = (d && d.pages && d.pages.length) ? d.pages : [{ st: [] }];
  padPages = ps.map(p => ({
    st: (p.st || []).map(s => ({ tool: s.t, color: s.c, size: s.w, pts: (s.p || []).map(q => ({ x: q[0], y: q[1], p: q[2] })) })),
    rd: [],
  }));
  padBg = (d && d.bg != null) ? (d.bg | 0) : 1;
  padPg = Math.min((d && (d.pg | 0)) || 0, padPages.length - 1);
}
/* 第一页的缩略图（白底黑字），给草稿本列表当封面 */
function padThumb() {
  const w = padCv.clientWidth || 1, h = padCv.clientHeight || 1, W = 320, k = W / w;
  const c = document.createElement('canvas');
  c.width = W; c.height = Math.max(1, Math.round(h * k));
  const x = c.getContext('2d');
  x.setTransform(k, 0, 0, k, 0, 0);
  padPaper(x, w, h, false);
  for (const s of padPages[0].st) padDraw(x, s, w, false);
  return c.toDataURL('image/jpeg', .72);
}

/* 随手草稿纸：存本地（切题/刷新/关掉再开都还在，按用户分开存） */
const padKey = () => 'pad:' + ((ME && (ME.id || ME.username)) || 'x');
function padSaveSoon() {
  clearTimeout(padSaveT);
  if (padMode === 'draft') padStatus('未保存…');
  padSaveT = setTimeout(() => (padMode === 'draft' ? padDraftSave() : padSave()), padMode === 'draft' ? 1200 : 700);
}
function padSave() {
  try { localStorage.setItem(padKey(), JSON.stringify(Object.assign(padData(), { pg: padPg }))); }
  catch (_) {}                                                    // 存不下就算了，别影响做题
}
function padLoad() {
  try {
    const d = JSON.parse(localStorage.getItem(padKey()) || 'null');
    if (d && d.pages && d.pages.length) padSetData(d);
  } catch (_) {}
}

/* 草稿本：存服务器（多本、手机电脑同步） */
function padStatus(t) { $('#pad-st').textContent = t || ''; }
async function padDraftSave() {
  if (!padDraftId) return;
  const id = padDraftId;                       // 存的过程中可能已经关掉了，用当时的 id
  padStatus('保存中…');
  try {
    await api('/api/drafts/' + id, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: padData(), pages: padPages.length, thumb: padThumb() }),
    });
    if (padDraftId === id) padStatus('已保存');
  } catch (_) {
    if (padDraftId === id) padStatus('没存上·稍后重试');
  }
}

function padInit() {
  padInited = true;
  padCv = $('#pad-cv'); padCtx = padCv.getContext('2d');
  padBase = document.createElement('canvas'); padBaseCtx = padBase.getContext('2d');
  padDk = createDock($('#pad'), 'padDock', 'bottom', padFit);
  padLoad();

  padCv.addEventListener('pointerdown', padDown);
  padCv.addEventListener('pointermove', padMove);
  padCv.addEventListener('pointerup', padUp);
  padCv.addEventListener('pointercancel', padUp);
  padCv.addEventListener('pointerleave', padUp);

  $('#pad').addEventListener('click', e => {
    const t = e.target.closest('.pad-t[data-tool]');
    if (t) { padTool = t.dataset.tool; padSyncUI(); return; }
    const c = e.target.closest('.pad-c');
    if (c) { padColor = c.dataset.c; if (padTool === 'eraser') padTool = 'pen'; padSyncUI(); }
  });
  $('#pad-size').oninput = (e) => { padSize = +e.target.value; };
  $('#pad-undo').onclick = padUndo;
  $('#pad-redo').onclick = padRedo;
  $('#pad-prev').onclick = () => padGo(padPg - 1);
  $('#pad-next').onclick = () => padGo(padPg + 1);
  $('#pad-add').onclick = () => {
    if (padPages.length >= 20) { toast('最多 20 页', true); return; }
    padPages.splice(padPg + 1, 0, { st: [], rd: [] });
    padGo(padPg + 1); toast('已新增一页');
  };
  $('#pad-bg').onclick = () => { padBg = (padBg + 1) % 3; padPaint(); padSyncUI(); padSaveSoon(); };
  $('#pad-clear').onclick = async () => {
    const many = padPages.length > 1;
    const r = await appConfirm('清空这一页的草稿？' + (many ? '（也可以直接删掉这一页）' : ''),
      { title: '草稿纸', okText: '清空本页', altText: many ? '删除本页' : '', altDanger: true });
    if (r === 'alt') { padPages.splice(padPg, 1); padGo(Math.min(padPg, padPages.length - 1)); toast('已删除本页'); }
    else if (r === true) { padPages[padPg] = { st: [], rd: [] }; padRebuild(); padSaveSoon(); toast('本页已清空'); }
  };
  $('#pad-png').onclick = () => {                                 // 导出白底黑字，方便打印/贴到错题本
    const w = padCv.clientWidth, h = padCv.clientHeight, k = 2;
    const c = document.createElement('canvas');
    c.width = w * k; c.height = h * k;
    const x = c.getContext('2d');
    x.setTransform(k, 0, 0, k, 0, 0);
    padPaper(x, w, h, false);
    for (const s of padPages[padPg].st) padDraw(x, s, w, false);
    const a = document.createElement('a');
    a.download = '草稿-第' + (padPg + 1) + '页.png';
    a.href = c.toDataURL('image/png');
    document.body.appendChild(a); a.click(); a.remove();
    toast('已保存为图片');
  };
  $('#pad-mode').onclick = () => padDk.toggleFull();               // 全屏 ⇄ 还原
  $('#pad-close').onclick = padClose;
  $('#pad-dock').addEventListener('pointerdown', (e) => padDk.dockDrag(e));

  let rzT = null;
  addEventListener('resize', () => {
    if ($('#pad').classList.contains('hidden')) return;
    clearTimeout(rzT); rzT = setTimeout(padFit, 120);
  });
  document.addEventListener('keydown', e => {
    if ($('#pad').classList.contains('hidden')) return;
    const k = (e.key || '').toLowerCase();
    if (e.ctrlKey && k === 'z') { e.preventDefault(); e.shiftKey ? padRedo() : padUndo(); }
    else if (e.ctrlKey && k === 'y') { e.preventDefault(); padRedo(); }
    else if (e.ctrlKey && k === 's') { e.preventDefault(); if (padMode === 'draft') { clearTimeout(padSaveT); padDraftSave(); } }
    else if (e.key === 'Escape') padClose();
  });
}

/* ================= 通用停靠（草稿纸 / AI 面板共用） =================
   半屏只是默认值：交界处的分隔线可以直接拖，比例按「每个停靠位」分别记住；
   ✥ 手柄按住拖到屏幕任一边 → 松手吸附成那半边（拖到正中 = 全屏）。 */
const DOCK_NAME = { bottom: '下半屏', top: '上半屏', right: '右半屏', left: '左半屏', full: '全屏' };
const dockVert = (d) => d === 'left' || d === 'right';

function createDock(el, key, defDock, onChange) {
  const st = { dock: defDock, prev: defDock, sizes: { bottom: 0, top: 0, left: 0, right: 0 } };
  const defSize = (d) => dockVert(d) ? Math.round(innerWidth * .5) : Math.round(innerHeight * .46);
  const size = (d) => {                       // 记住的大小；没拖过就是一半。换屏也不会越界
    const v = st.sizes[d] || defSize(d);
    const max = dockVert(d) ? innerWidth * .95 : innerHeight * .95;
    const min = dockVert(d) ? 280 : 190;
    return Math.round(Math.min(max, Math.max(min, v)));
  };
  const save = () => { try { localStorage.setItem(key, JSON.stringify({ d: st.dock, sizes: st.sizes })); } catch (_) {} };
  (function load() {
    try {
      const d = JSON.parse(localStorage.getItem(key) || 'null');
      if (!d) return;
      if (DOCK_NAME[d.d]) { st.dock = d.d; st.prev = d.d === 'full' ? defDock : d.d; }
      if (d.sizes) Object.assign(st.sizes, d.sizes);
      else { if (d.h) { st.sizes.bottom = d.h; st.sizes.top = d.h; }    // 兼容旧格式
             if (d.w) { st.sizes.left = d.w; st.sizes.right = d.w; } }
    } catch (_) {}
  })();

  function apply(doSave) {
    Object.keys(DOCK_NAME).forEach(d => el.classList.toggle('dk-' + d, d === st.dock));
    if (st.dock !== 'full') {
      if (dockVert(st.dock)) el.style.setProperty('--dk-w', size(st.dock) + 'px');
      else el.style.setProperty('--dk-h', size(st.dock) + 'px');
    }
    if (doSave) save();
    requestAnimationFrame(() => { if (onChange) onChange(); applyPush(); avoidFab(); });
  }
  function set(d, quiet) {
    if (!DOCK_NAME[d]) return;
    if (d !== 'full') st.prev = d;
    st.dock = d; apply(true);
    if (!quiet) toast(d === 'full' ? '全屏' : '已停靠：' + DOCK_NAME[d]);
  }
  function toggleFull() { set(st.dock === 'full' ? (st.prev || defDock) : 'full', true); }

  const box = (z) => z === 'full' ? { left: 0, top: 0, width: innerWidth, height: innerHeight }
    : z === 'left' ? { left: 0, top: 0, width: size('left'), height: innerHeight }
      : z === 'right' ? { left: innerWidth - size('right'), top: 0, width: size('right'), height: innerHeight }
        : z === 'top' ? { left: 0, top: 0, width: innerWidth, height: size('top') }
          : { left: 0, top: innerHeight - size('bottom'), width: innerWidth, height: size('bottom') };
  const zoneAt = (x, y) => x < innerWidth * .18 ? 'left' : x > innerWidth * .82 ? 'right'
    : y < innerHeight * .15 ? 'top' : y > innerHeight * .85 ? 'bottom' : 'full';

  function dockDrag(e) {                      // 按住 ✥ 拖 → 松手吸附
    e.preventDefault();
    el.classList.add('dragging');
    let zone = st.dock;
    const show = (z) => {
      const s = $('#dock-snap'), b = box(z);
      s.style.left = b.left + 'px'; s.style.top = b.top + 'px';
      s.style.width = b.width + 'px'; s.style.height = b.height + 'px';
      s.classList.remove('hidden');
    };
    const mv = (ev) => { zone = zoneAt(ev.clientX, ev.clientY); show(zone); };
    const up = () => {
      removeEventListener('pointermove', mv); removeEventListener('pointerup', up);
      el.classList.remove('dragging');
      $('#dock-snap').classList.add('hidden');
      if (zone !== st.dock) set(zone);        // 大小沿用该停靠位上次拖成的比例
    };
    show(zone);
    addEventListener('pointermove', mv); addEventListener('pointerup', up);
  }

  const grip = document.createElement('div');   // 交界处那条分隔线
  grip.className = 'dk-grip';
  grip.title = '拖动改大小 · 双击复位成一半';
  el.appendChild(grip);
  grip.addEventListener('pointerdown', (e) => {
    if (st.dock === 'full') return;
    e.preventDefault();
    document.body.classList.add(dockVert(st.dock) ? 'dk-rz-x' : 'dk-rz-y');
    grip.classList.add('on');
    const mv = (ev) => {
      st.sizes[st.dock] = st.dock === 'bottom' ? innerHeight - ev.clientY
        : st.dock === 'top' ? ev.clientY
          : st.dock === 'right' ? innerWidth - ev.clientX
            : ev.clientX;
      apply(false);
    };
    const up = () => {
      removeEventListener('pointermove', mv); removeEventListener('pointerup', up);
      document.body.classList.remove('dk-rz-x', 'dk-rz-y');
      grip.classList.remove('on');
      st.sizes[st.dock] = size(st.dock);
      apply(true);
    };
    addEventListener('pointermove', mv); addEventListener('pointerup', up);
  });
  grip.addEventListener('dblclick', () => {
    if (st.dock === 'full') return;
    st.sizes[st.dock] = 0; apply(true); toast('已复位成一半');
  });

  addEventListener('resize', () => { if (!el.classList.contains('hidden')) apply(false); });
  return { st, apply, set, toggleFull, dockDrag, isFull: () => st.dock === 'full' };
}

/* 记住的位置要按「当前窗口」夹回来：换台设备 / 桌面版窗口更小时，
   否则球会停在窗口外面，看起来就是「悬浮球不见了」。 */
function fabClamp() {
  const fab = $('#fab');
  if (!fab || !innerWidth || !innerHeight) return;      // 还没完成布局就先别动
  if (!fab.style.left && !fab.style.top) return;        // 没拖过 → 用 CSS 默认角落，不用管
  const r = fab.getBoundingClientRect();
  const w = r.width || 50, h = r.height || 50;
  const x = Math.min(Math.max(4, r.left), innerWidth - w - 4);
  const y = Math.min(Math.max(4, r.top), innerHeight - h - 4);
  if (Math.abs(x - r.left) < .5 && Math.abs(y - r.top) < .5) return;
  fab.style.left = x + 'px'; fab.style.top = y + 'px';
  fab.style.right = 'auto'; fab.style.bottom = 'auto';
  try { localStorage.setItem('aifab', JSON.stringify({ x, y })); } catch (_) {}
}
addEventListener('resize', fabClamp);
addEventListener('load', () => requestAnimationFrame(fabClamp));

/* 停靠面板占屏后，把页面内容挤到剩下的可见区（卡片会自动重排，不再被盖住） */
function applyPush() {
  const p = { left: 0, right: 0, top: 0, bottom: 0 };
  [$('#pad'), $('#ai-panel'), $('#matpad')].forEach(el => {
    if (!el || el.classList.contains('hidden') || el.classList.contains('dk-full')) return;
    const d = Object.keys(DOCK_NAME).find(k => el.classList.contains('dk-' + k));
    if (!d || d === 'full') return;
    const r = el.getBoundingClientRect();
    p[d] = Math.max(p[d], Math.round(dockVert(d) ? r.width : r.height));
  });
  const s = document.body.style;
  s.setProperty('--push-l', p.left + 'px');
  s.setProperty('--push-r', p.right + 'px');
  s.setProperty('--push-t', p.top + 'px');
  s.setProperty('--push-b', p.bottom + 'px');
}

/* 悬浮球别被面板压住：挡住就挪到面板外；面板全屏时藏起来 */
function avoidFab() {
  const fab = $('#fab');
  if (!fab || !innerWidth) return;
  const open = [$('#pad'), $('#ai-panel'), $('#matpad')].filter(p => p && !p.classList.contains('hidden'));
  document.body.classList.toggle('pad-full', open.some(p => p.classList.contains('dk-full')));
  if (!open.length || document.body.classList.contains('pad-full')) return;
  for (const p of open) {
    const r = p.getBoundingClientRect(), f = fab.getBoundingClientRect();
    if (!(f.left < r.right && f.right > r.left && f.top < r.bottom && f.bottom > r.top)) continue;
    const d = Object.keys(DOCK_NAME).find(k => p.classList.contains('dk-' + k));
    let x = f.left, y = f.top;
    if (d === 'right') x = r.left - f.width - 12;
    else if (d === 'left') x = r.right + 12;
    else if (d === 'bottom') y = r.top - f.height - 12;
    else if (d === 'top') y = r.bottom + 12;
    x = Math.min(Math.max(4, x), innerWidth - f.width - 4);
    y = Math.min(Math.max(4, y), innerHeight - f.height - 4);
    fab.style.left = x + 'px'; fab.style.top = y + 'px';
    fab.style.right = 'auto'; fab.style.bottom = 'auto';
    try { localStorage.setItem('aifab', JSON.stringify({ x, y })); } catch (_) {}
  }
}

/* 草稿纸的停靠实例（手机默认下半屏，电脑默认下半屏；想要别的自己拖） */
let padDk = null;
function padDock_() { return padDk ? padDk.st.dock : 'bottom'; }

function padOpen() {
  if (!padInited) padInit();
  $('#pad').classList.remove('hidden');
  document.body.classList.add('pad-open');
  padDk.apply(false);
}
function padClose() {
  const wasDraft = padMode === 'draft';
  clearTimeout(padSaveT);
  if (wasDraft) padDraftSave(); else padSave();
  $('#pad').classList.add('hidden');
  document.body.classList.remove('pad-open', 'pad-full');
  applyPush(); avoidFab();
  if (wasDraft) {                                                 // 退出草稿本 → 回列表，恢复随手草稿纸
    padMode = 'scratch'; padDraftId = null;
    $('#pad-doc').classList.add('hidden');
    padLoad();
    loadDrafts();
  }
}
function padToggle() { $('#pad').classList.contains('hidden') ? padOpen() : padClose(); }
function padOnView() {
  /* 草稿纸现在是全局悬浮的：换页面不再收起——正好可以一边看成语词语、一边在旁边练着写。 */
}

/* ---------- 草稿本：错题本里，平时打草稿用（多本 / 云端保存 / 手机电脑同步） ---------- */
function openDrafts() { push({ view: 'drafts' }); loadDrafts(); }
async function loadDrafts() {
  try {
    const d = await api('/api/drafts');
    $('#dr-empty').textContent = '还没有草稿本，点右下角 ＋ 新建一本';
    $('#dr-empty').classList.toggle('hidden', !!d.items.length);
    $('#dr-list').innerHTML = d.items.map(it => `
      <div class="dr-card" data-dr="${it.id}">
        <div class="dr-thumb"${it.thumb ? ` style="background-image:url(${it.thumb})"` : ''}></div>
        <div class="dr-body">
          <div class="dr-t">${esc(it.title || '未命名')}</div>
          <div class="dr-foot">
            <span class="dr-m">${it.pages || 1} 页 · ${(it.updated_at || '').slice(5, 16)}</span>
            <button class="dr-del" data-del="${it.id}" title="删除">✕</button>
          </div>
        </div>
      </div>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#dr-list').addEventListener('click', async e => {
  const del = e.target.closest('.dr-del');
  if (del) {
    e.stopPropagation();
    if (!await appConfirm('删除这本草稿？删了就找不回来了。', { title: '草稿本', okText: '删除' })) return;
    try { await api('/api/drafts/' + del.dataset.del, { method: 'DELETE' }); toast('已删除'); loadDrafts(); }
    catch (err) { toast(err.message, true); }
    return;
  }
  const c = e.target.closest('.dr-card');
  if (c) openDraft(+c.dataset.dr);
});
$('#dr-fab').onclick = async () => {
  const t = await appPrompt('新建草稿本', '起个名字（留空就用日期）', '');
  if (t === null) return;
  try {
    const d = await api('/api/drafts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: t }),
    });
    openDraft(d.id);
  } catch (e) { toast(e.message, true); }
};
async function openDraft(id) {
  try {
    const d = await api('/api/drafts/' + id);
    if (!padInited) padInit();
    if (padMode !== 'draft') padSave();                            // 先把随手草稿纸存好，等下还要还原
    padMode = 'draft'; padDraftId = id; padCur = null;
    padSetData(d.data);
    $('#pad-title').textContent = d.title || '未命名';
    $('#pad-doc').classList.remove('hidden');
    padStatus('已保存');
    padOpen();
  } catch (e) { toast(e.message, true); }
}
$('#pad-name').onclick = async () => {
  if (padMode !== 'draft') return;
  const t = await appPrompt('草稿本改名', '名字', $('#pad-title').textContent);
  if (t === null) return;
  try {
    await api('/api/drafts/' + padDraftId, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: t }),
    });
    $('#pad-title').textContent = t.trim() || '未命名草稿';
    toast('已改名');
  } catch (e) { toast(e.message, true); }
};
$('#wq-drafts').onclick = openDrafts;
/* 对外钩子放在最后才挂：顶层 function 声明会自动成为 window 属性，
   若直接用同名守卫(window.padRebuild)，脚本刚开始就会被误判为"已就绪"而提前调用。 */
window.__padView = padOnView;
window.__padTheme = () => { if (padInited && !$('#pad').classList.contains('hidden')) padRebuild(); };

/* ================= 外观：头像 / 壁纸 =================
   壁纸铺在 body 上（fixed，不跟着滚），上面盖一层可调浓度的蒙版保证正文看得清。
   登录页在没登录时读不到接口，所以把壁纸 URL 缓存进 localStorage，login.html 自己取。 */
let SKIN = { avatar: '', wall_app: '', wall_login: '' };
const skinDim = () => Math.min(90, Math.max(0, parseInt(localStorage.getItem('skinDim') || '55', 10)));

function applySkin() {
  // 头像出现在两处：左上角的 logo 和账户页顶部的大圆。
  // （原来只更新了 logo，账户页那个是 HTML 里写死的「公」，换了头像也不变。）
  [$('#brand-logo'), $('#acct-avatar')].forEach(el => {
    if (!el) return;
    if (SKIN.avatar) {
      el.style.backgroundImage = 'url("' + SKIN.avatar + '")';
      el.classList.add('has-img');
      el.textContent = '';
    } else {
      el.style.backgroundImage = '';
      el.classList.remove('has-img');
      el.textContent = '公';
    }
  });
  // 应用内壁纸
  const b = document.body;
  b.classList.toggle('has-wall', !!SKIN.wall_app);
  b.style.setProperty('--wall', SKIN.wall_app ? 'url("' + SKIN.wall_app + '")' : 'none');
  b.style.setProperty('--wall-dim', (skinDim() / 100).toFixed(2));
  // 登录页要用的，缓存到本地（它没登录，拿不到接口）
  try {
    localStorage.setItem('wallLogin', SKIN.wall_login || '');
    localStorage.setItem('skinDim', String(skinDim()));
  } catch (_) {}
}
async function loadSkin() {
  try {
    SKIN = await api('/api/skin');
    applySkin();
  } catch (_) {}
}
function renderSkinPrev() {
  [['avatar', '公'], ['wall_app', '无'], ['wall_login', '无']].forEach(([k, empty]) => {
    const el = $('#sk-' + k);
    if (!el) return;
    if (SKIN[k]) { el.style.backgroundImage = 'url("' + SKIN[k] + '")'; el.innerHTML = ''; }
    else { el.style.backgroundImage = ''; el.innerHTML = '<span>' + empty + '</span>'; }
  });
  $('#skin-dim').value = skinDim();
  $('#skin-dimv').textContent = skinDim() + '%';
  $('#skin-dim-row').classList.toggle('hidden', !SKIN.wall_app && !SKIN.wall_login);
}
document.addEventListener('change', async e => {
  const inp = e.target.closest('input[data-skin]');
  if (!inp || !inp.files || !inp.files[0]) return;
  const kind = inp.dataset.skin, f = inp.files[0];
  inp.value = '';
  if (f.size > 12 * 1024 * 1024) { toast('图片太大了（超过 12MB）', true); return; }
  toast('上传中…');
  try {
    const fd = new FormData(); fd.append('file', f);
    const d = await api('/api/skin/' + kind, { method: 'POST', body: fd });
    SKIN[kind] = d.url + '?t=' + Date.now();      // 加时间戳，绕过缓存立刻看到新图
    applySkin(); renderSkinPrev();
    toast(kind === 'avatar' ? '头像已更换' : '壁纸已更换');
  } catch (err) { toast(err.message, true); }
});
$('#view-account').addEventListener('click', async e => {
  const del = e.target.closest('[data-skindel]');
  if (!del) return;
  const kind = del.dataset.skindel;
  if (!SKIN[kind]) return;
  if (!await appConfirm(kind === 'avatar' ? '恢复成默认头像？' : '清除这张壁纸？', { title: '外观定制' })) return;
  try {
    await api('/api/skin/' + kind, { method: 'DELETE' });
    SKIN[kind] = ''; applySkin(); renderSkinPrev();
    toast('已恢复默认');
  } catch (err) { toast(err.message, true); }
});
$('#skin-dim').addEventListener('input', e => {
  localStorage.setItem('skinDim', e.target.value);
  $('#skin-dimv').textContent = e.target.value + '%';
  applySkin();
});

/* ================= 侧边翻页条（电脑端）=================
   手写笔没有滚轮、没有中键，光靠拖滚动条很别扭。这里给一排大按钮：
   上下翻一屏、直接回顶（回顶时如果不在首页，顺便把「返回」按钮亮出来）、到底部。 */
function pgScroll(dy) {
  const el = document.scrollingElement || document.documentElement;
  el.scrollBy({ top: dy, behavior: 'smooth' });
}
function pgInit() {
  // 触屏手机不需要；桌面版和电脑网页才显示
  document.body.classList.toggle('has-pen', !IS_MOBILE);
  $('#pg-up').onclick = () => pgScroll(-(innerHeight * 0.85));
  $('#pg-dn').onclick = () => pgScroll(innerHeight * 0.85);
  $('#pg-end').onclick = () => {
    const el = document.scrollingElement || document.documentElement;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  };
  $('#pg-top').onclick = () => {
    const el = document.scrollingElement || document.documentElement;
    el.scrollTo({ top: 0, behavior: 'smooth' });
  };
  // 长按/右键「回到顶部」= 直接返回上一页，省得回顶再去点返回
  $('#pg-top').oncontextmenu = (e) => { e.preventDefault(); back(); };
}
pgInit();

/* ================= 给定资料面板（申论作答时看材料 + 手写笔勾画） =================
   考场上就是拿笔在材料上划重点的。这里把材料做成可停靠的半屏面板（和 AI/草稿纸同一套停靠），
   上面盖一层透明画布：荧光笔划重点、笔写批注、橡皮擦掉。勾画按材料存本地，下次打开还在。 */
const MAT_COLORS = ['#f0a500', '#2fa36c', '#e05a7d', '#1a6fb5'];
let matDk = null, matInited = false;
let matKey = '', matStrokes = [], matCur = null, matDrawing = false, matSawPen = false;
let matTool = 'hl', matColor = MAT_COLORS[0], matRaf = 0;
let matCv, matCtx;

const matW = () => matCv.clientWidth || 1;
function matPt(e) {
  const r = matCv.getBoundingClientRect(), w = r.width || 1;
  return { x: (e.clientX - r.left) / w, y: (e.clientY - r.top) / w,
    p: (e.pointerType === 'pen' && e.pressure > 0) ? e.pressure : 0 };
}
function matDrawStroke(ctx, s, W) {
  const pts = s.pts;
  if (!pts || !pts.length) return;
  ctx.save();
  ctx.lineJoin = ctx.lineCap = 'round';
  if (s.tool === 'eraser') { ctx.globalCompositeOperation = 'destination-out'; ctx.strokeStyle = '#000'; ctx.lineWidth = 22; }
  else if (s.tool === 'hl') { ctx.strokeStyle = s.color; ctx.globalAlpha = .32; ctx.lineWidth = 15; ctx.lineCap = 'butt'; }
  else { ctx.strokeStyle = s.color; ctx.lineWidth = 2.4; }
  ctx.beginPath();
  ctx.moveTo(pts[0].x * W, pts[0].y * W);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x * W, pts[i].y * W);
  if (pts.length === 1) ctx.lineTo(pts[0].x * W + .1, pts[0].y * W + .1);
  ctx.stroke();
  ctx.restore();
}
function matPaint() {
  const w = matCv.clientWidth, h = matCv.clientHeight;
  matCtx.clearRect(0, 0, w, h);
  const W = matW();
  for (const s of matStrokes) matDrawStroke(matCtx, s, W);
  if (matCur) matDrawStroke(matCtx, matCur, W);
}
function matFit() {
  const inner = $('#mat-inner');
  if (!inner || !matCv) return;
  const w = inner.clientWidth, h = Math.max(inner.scrollHeight, $('#mat-scroll').clientHeight);
  if (!w) return;
  const dpr = Math.min(2, devicePixelRatio || 1);
  matCv.style.width = w + 'px'; matCv.style.height = h + 'px';
  matCv.width = Math.round(w * dpr); matCv.height = Math.round(h * dpr);
  matCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  matPaint();
}
function matSave() {
  if (!matKey) return;
  const r = (n) => Math.round(n * 1e4) / 1e4;
  try {
    localStorage.setItem(matKey, JSON.stringify(matStrokes.map(s => ({
      t: s.tool, c: s.color, p: s.pts.map(q => [r(q.x), r(q.y)]),
    }))));
  } catch (_) {}
}
function matLoad(key) {
  matKey = key; matStrokes = [];
  try {
    const d = JSON.parse(localStorage.getItem(key) || 'null');
    if (d) matStrokes = d.map(s => ({ tool: s.t, color: s.c, pts: (s.p || []).map(q => ({ x: q[0], y: q[1] })) }));
  } catch (_) {}
}
function matSyncUI() {
  document.querySelectorAll('#matpad [data-mt]').forEach(b => b.classList.toggle('on', b.dataset.mt === matTool));
  $('#mat-colors').innerHTML = MAT_COLORS.map(c =>
    `<i class="pad-c${c === matColor && matTool !== 'eraser' ? ' on' : ''}" data-mc="${c}" style="background:${c}"></i>`).join('');
}
function matInit() {
  matInited = true;
  matCv = $('#mat-cv'); matCtx = matCv.getContext('2d');
  matDk = createDock($('#matpad'), 'matDock', IS_MOBILE ? 'bottom' : 'right', matFit);

  matCv.addEventListener('pointerdown', e => {
    if (e.pointerType === 'pen') matSawPen = true;
    if (e.pointerType === 'touch' && matSawPen) return;   // 用过笔就防手掌误触
    if (e.button > 0) return;
    e.preventDefault();
    try { matCv.setPointerCapture(e.pointerId); } catch (_) {}
    matDrawing = true;
    matCur = { tool: matTool, color: matColor, pts: [matPt(e)] };
    matPaint();
  });
  matCv.addEventListener('pointermove', e => {
    if (!matDrawing || !matCur) return;
    e.preventDefault();
    let evs = [];
    try { if (e.getCoalescedEvents) evs = e.getCoalescedEvents(); } catch (_) {}
    if (!evs.length) evs = [e];
    for (const ev of evs) matCur.pts.push(matPt(ev));
    if (!matRaf) matRaf = requestAnimationFrame(() => { matRaf = 0; matPaint(); });
  });
  const up = () => {
    if (!matDrawing) return;
    matDrawing = false;
    if (matCur) { matStrokes.push(matCur); matCur = null; matPaint(); matSave(); }
  };
  matCv.addEventListener('pointerup', up);
  matCv.addEventListener('pointercancel', up);
  matCv.addEventListener('pointerleave', up);

  $('#matpad').addEventListener('click', e => {
    const t = e.target.closest('[data-mt]');
    if (t) { matTool = t.dataset.mt; matSyncUI(); return; }
    const c = e.target.closest('[data-mc]');
    if (c) { matColor = c.dataset.mc; if (matTool === 'eraser') matTool = 'hl'; matSyncUI(); }
  });
  $('#mat-clear').onclick = async () => {
    if (!matStrokes.length) return;
    if (!await appConfirm('清除这份材料上的全部勾画？', { title: '给定资料', okText: '清除' })) return;
    matStrokes = []; matPaint(); matSave(); toast('已清除');
  };
  $('#mat-dock').addEventListener('pointerdown', (e) => matDk.dockDrag(e));
  $('#mat-full').onclick = () => matDk.toggleFull();
  $('#mat-close').onclick = matClose;
  addEventListener('resize', () => { if (!$('#matpad').classList.contains('hidden')) matFit(); });
}
function matOpen(text, key) {
  if (!matInited) matInit();
  $('#mat-text').textContent = text || '（这份卷子没有给定资料）';
  matLoad('matmark:' + key);
  $('#matpad').classList.remove('hidden');
  matSyncUI();
  matDk.apply(false);
  requestAnimationFrame(() => { matFit(); applyPush(); avoidFab(); });
}
function matClose() {
  matSave();
  $('#matpad').classList.add('hidden');
  document.body.classList.remove('pad-full');
  applyPush(); avoidFab();
}

/* ================= AI：截图 / 粘贴图片 / 手写输入 =================
   识图必须走智谱 GLM-4.6V —— 实测 DeepSeek 的 API 直接拒收图片
   （HTTP 400: unknown variant `image_url`），它根本没有视觉能力。
   所以：图 → 智谱读成文字 → 文字再交给 DeepSeek（便宜）。/api/ai/extract 已经是这个流程。 */

/* ---- #14 Ctrl+V 粘贴截图 / 拖图片进来，直接变成 AI 附件 ---- */
$('#ai-panel').addEventListener('paste', e => {
  const items = [...((e.clipboardData && e.clipboardData.items) || [])];
  const img = items.find(i => (i.type || '').startsWith('image/'));
  if (!img) return;                       // 粘文字就照常，不拦
  e.preventDefault();
  const f = img.getAsFile();
  if (f) { toast('正在读取截图…'); aiHandleAttach(f); }
});
$('#ai-panel').addEventListener('dragover', e => e.preventDefault());
$('#ai-panel').addEventListener('drop', e => {
  const f = [...(e.dataTransfer ? e.dataTransfer.files : [])][0];
  if (f && (f.type || '').startsWith('image/')) { e.preventDefault(); aiHandleAttach(f); }
});

/* ---- #13 截图：壳抓图（GNOME 区域选择，鼠标/笔都能拖）→ 回到网页再用笔自由圈 ---- */
let shotImg = null, shotPts = [], shotRect = null, shotDraw = false, shotPen = false;
let shotCv, shotCtx;

function shotAsk() {
  if (!window.__desktopShot) { toast('截图功能只在电脑桌面版里有', true); return; }
  toast('拖选要截的区域…');
  deskMsg({ a: 'shot' });
}
window.__onShot = (dataUrl) => {          // 壳把截好的图交回来
  const im = new Image();
  im.onload = () => { shotImg = im; shotOpen(); };
  im.src = dataUrl;
};
function shotOpen() {
  shotPts = []; shotRect = null;
  $('#shot').classList.remove('hidden');
  shotCv = $('#shot-cv'); shotCtx = shotCv.getContext('2d');
  const maxW = Math.min(innerWidth - 40, 1400), maxH = innerHeight - 120;
  const k = Math.min(maxW / shotImg.width, maxH / shotImg.height, 1);
  shotCv.width = Math.round(shotImg.width * k);
  shotCv.height = Math.round(shotImg.height * k);
  shotPaint();
}
function shotPaint() {
  shotCtx.clearRect(0, 0, shotCv.width, shotCv.height);
  shotCtx.drawImage(shotImg, 0, 0, shotCv.width, shotCv.height);
  if (!shotPts.length && !shotRect) return;
  shotCtx.save();
  shotCtx.fillStyle = 'rgba(10,20,35,.5)';      // 圈外压暗，圈中的地方亮着
  shotCtx.fillRect(0, 0, shotCv.width, shotCv.height);
  shotCtx.globalCompositeOperation = 'destination-out';
  shotCtx.beginPath();
  if (shotRect) shotCtx.rect(shotRect.x, shotRect.y, shotRect.w, shotRect.h);
  else {
    shotCtx.moveTo(shotPts[0].x, shotPts[0].y);
    for (const p of shotPts) shotCtx.lineTo(p.x, p.y);
    shotCtx.closePath();
  }
  shotCtx.fill();
  shotCtx.restore();
  shotCtx.strokeStyle = '#2c8fd6'; shotCtx.lineWidth = 2; shotCtx.setLineDash([6, 4]);
  shotCtx.stroke();
  shotCtx.setLineDash([]);
}
function shotPt(e) {
  const r = shotCv.getBoundingClientRect();
  return { x: (e.clientX - r.left) * shotCv.width / r.width,
    y: (e.clientY - r.top) * shotCv.height / r.height };
}
function shotBind() {
  const cv = $('#shot-cv');
  cv.addEventListener('pointerdown', e => {
    e.preventDefault();
    shotDraw = true;
    shotPen = e.pointerType === 'pen';        // 笔 → 自由圈；鼠标/触摸 → 拖矩形
    const p = shotPt(e);
    shotPts = [p];
    shotRect = shotPen ? null : { x: p.x, y: p.y, w: 0, h: 0, x0: p.x, y0: p.y };
    try { cv.setPointerCapture(e.pointerId); } catch (_) {}
  });
  cv.addEventListener('pointermove', e => {
    if (!shotDraw) return;
    const p = shotPt(e);
    if (shotPen) shotPts.push(p);
    else {
      const r = shotRect;
      r.x = Math.min(r.x0, p.x); r.y = Math.min(r.y0, p.y);
      r.w = Math.abs(p.x - r.x0); r.h = Math.abs(p.y - r.y0);
    }
    shotPaint();
  });
  const up = () => { shotDraw = false; shotPaint(); };
  cv.addEventListener('pointerup', up);
  cv.addEventListener('pointercancel', up);

  $('#shot-cancel').onclick = () => { $('#shot').classList.add('hidden'); shotImg = null; };
  $('#shot-redo').onclick = () => { shotPts = []; shotRect = null; shotPaint(); };
  $('#shot-all').onclick = () => { shotPts = []; shotRect = null; shotSend(true); };
  $('#shot-ok').onclick = () => shotSend(false);
  $('#ai-shot').onclick = shotAsk;
}
function shotSend(whole) {
  if (!shotImg) return;
  const k = shotImg.width / shotCv.width;      // 画布是缩放显示的，裁剪要还原到原图分辨率
  let box;
  if (whole || (!shotRect && shotPts.length < 3)) {
    box = { x: 0, y: 0, w: shotImg.width, h: shotImg.height };
  } else if (shotRect) {
    box = { x: shotRect.x * k, y: shotRect.y * k, w: shotRect.w * k, h: shotRect.h * k };
  } else {
    const xs = shotPts.map(p => p.x), ys = shotPts.map(p => p.y);
    box = { x: Math.min(...xs) * k, y: Math.min(...ys) * k,
      w: (Math.max(...xs) - Math.min(...xs)) * k, h: (Math.max(...ys) - Math.min(...ys)) * k };
  }
  if (box.w < 8 || box.h < 8) { toast('圈选的区域太小了', true); return; }
  const c = document.createElement('canvas');
  c.width = Math.round(box.w); c.height = Math.round(box.h);
  const x = c.getContext('2d');
  if (!whole && shotPts.length >= 3) {         // 自由圈：只保留圈内的部分
    x.save();
    x.beginPath();
    x.moveTo(shotPts[0].x * k - box.x, shotPts[0].y * k - box.y);
    for (const p of shotPts) x.lineTo(p.x * k - box.x, p.y * k - box.y);
    x.closePath(); x.clip();
    x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height);
  }
  x.drawImage(shotImg, box.x, box.y, box.w, box.h, 0, 0, c.width, c.height);
  if (!whole && shotPts.length >= 3) x.restore();
  c.toBlob(b => {
    if (!b) return;
    $('#shot').classList.add('hidden');
    shotImg = null;
    openAI();
    aiHandleAttach(new File([b], '截图.png', { type: 'image/png' }));
  }, 'image/png');
}
shotBind();

/* ================= 书签：看到哪了 =================
   长文（经典著作 / 要文库 / 范文 / 知识库文档）看到一半退出来，回头根本找不到位置。
   这里在阅读类页面自动记住滚动位置，回来时顶部给一条「上次看到这里 · 点我跳回」。 */
/* 书签：任何会滚动的页面都记「看到哪了」——长文如此，长列表（如 894 条成语）更需要。
   ref 用「视图 + 这一页的子标识」拼出来（板块名 / 文章 id / 分类…），换个板块就是另一条书签。 */
const BM_SKIP = new Set(['home', 'account', 'search', 'slgrade', 'quizrun', 'dtest', 'notify']);
let bmCur = null, bmT = null;

function bmRef() {
  const st = stack[stack.length - 1];
  if (!st || BM_SKIP.has(st.view)) return null;
  // 顶层 let 不会挂到 window 上，直接引用（都在同一个脚本作用域里）
  // 顶层 let 不会挂到 window 上，直接引用（同一脚本作用域）；标题足够区分的就用标题
  const sub = {
    doc: () => DOC && DOC.id,
    newsd: () => nwCur && nwCur.id,
    ckboard: () => ckBoard,
    csboard: () => csBoard,
    materials: () => matBoard || '全部',
  }[st.view];
  let id = '';
  try { id = sub ? (sub() || '') : (st.title || ''); } catch (_) { id = st.title || ''; }
  return { kind: st.view, ref: String(id || st.view), title: st.title || TITLES[st.view] || '' };
}
function bmScrollTop() { return (document.scrollingElement || document.documentElement).scrollTop; }
function bmSave() {                      // 滚动停下来 1.5s 就记一次（不打扰、不刷接口）
  const r = bmRef();
  if (!r) return;
  const el = document.scrollingElement || document.documentElement;
  const pos = el.scrollHeight > el.clientHeight ? bmScrollTop() / (el.scrollHeight - el.clientHeight) : 0;
  // 按「滚了多少像素」判断，不能按百分比：894 条成语那页有 15 万像素高，
  // 滚了 3000px 也才 2%，用百分比阈值会直接把书签丢掉。
  if (bmScrollTop() < 260) return;
  api('/api/bookmarks', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: r.kind, ref: r.ref, title: r.title, pos }),
  }).catch(() => {});
}
addEventListener('scroll', () => {
  if (!bmRef()) return;
  clearTimeout(bmT);
  bmT = setTimeout(bmSave, 1500);
}, { passive: true });

async function bmRestore() {             // 进阅读页时问一句：上次看到哪了
  const r = bmRef();
  if (!r) { $('#bm-tip').classList.add('hidden'); return; }
  try {
    const d = await api('/api/bookmarks');
    const b = (d.items || []).find(x => x.kind === r.kind && x.ref === r.ref);
    const el = document.scrollingElement || document.documentElement;
    const px = b ? b.pos * (el.scrollHeight - el.clientHeight) : 0;
    if (!b || px < 260) { $('#bm-tip').classList.add('hidden'); return; }
    bmCur = b;
    $('#bm-tip').innerHTML = `🔖 上次看到 <b>${Math.round(b.pos * 100)}%</b> 处 · <i>${(b.updated_at || '').slice(5, 16)}</i>
      <button class="btn tiny" id="bm-go">跳回去</button>
      <button class="bm-x" id="bm-hide">✕</button>`;
    $('#bm-tip').classList.remove('hidden');
  } catch (_) {}
}
document.addEventListener('click', e => {
  if (e.target.closest('#bm-go')) {
    const el = document.scrollingElement || document.documentElement;
    el.scrollTo({ top: bmCur.pos * (el.scrollHeight - el.clientHeight), behavior: 'smooth' });
    $('#bm-tip').classList.add('hidden');
  } else if (e.target.closest('#bm-hide')) $('#bm-tip').classList.add('hidden');
});
window.__bmView = () => setTimeout(bmRestore, 700);   // 内容渲染完再问

/* 选队友共享：复用底部弹层，勾选=共享，取消勾选=收回 */
function matPickMembers(members) {
  return new Promise(res => {
    const el = $('#mat-share-sheet');
    el.innerHTML = `<div class="ns-title">👥 共享给队友</div>
      <p class="acct-hint" style="padding:0 16px">勾上就共享给他（他能在资料库看到并下载，但不能改不能删）；取消勾选就收回。</p>
      <div class="ms-list">${members.map(m => `
        <label class="ms-row"><input type="checkbox" value="${m.id}" ${m.shared ? 'checked' : ''}>
          <span>${esc(m.username)}</span></label>`).join('')}</div>
      <div class="ms-acts">
        <button class="btn" id="ms-cancel">取消</button>
        <button class="btn primary" id="ms-ok">确定</button>
      </div>`;
    el.classList.remove('hidden');
    const done = (v) => { el.classList.add('hidden'); res(v); };
    $('#ms-ok').onclick = () => done([...el.querySelectorAll('input:checked')].map(i => +i.value));
    $('#ms-cancel').onclick = () => done(null);
    el.onclick = (e) => { if (e.target === el) done(null); };
  });
}

/* ================= 桌面版：拖放 / 粘贴图片（由壳送进来） =================
   WebKitGTK 的 drop 事件里 dataTransfer.files 是**空的**（dragover 有效、drop 拿不到文件），
   往输入框里 Ctrl+V 粘图也粘不进去（WebKit 只认文字）。
   所以这两件事都由原生壳从 GTK 层拿到，再把内容送回网页。 */
function b64ToFile(b64, name) {
  const bin = atob(b64);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return new File([buf], name || ('文件_' + Date.now()));
}
function dropTarget() {                 // 当前该把文件丢给谁
  const st = stack[stack.length - 1];
  if ($('#ai-panel') && !$('#ai-panel').classList.contains('hidden')) return 'ai';
  if (!st) return '';
  if (st.view === 'materials') return 'materials';
  if (st.view === 'shenlun') return 'shenlun';
  return '';
}
window.__onDragOver = () => {
  const t = dropTarget();
  if (t === 'materials') $('#view-materials').classList.add('drag-on');
  else if (t === 'shenlun') $('#view-shenlun').classList.add('drag-on');
};
window.__onDragLeave = () => {
  $('#view-materials') && $('#view-materials').classList.remove('drag-on');
  $('#view-shenlun') && $('#view-shenlun').classList.remove('drag-on');
};
window.__onDropFiles = (items) => {
  window.__onDragLeave();
  const files = (items || []).map(x => b64ToFile(x.data, x.name));
  if (!files.length) return;
  const t = dropTarget();
  if (t === 'ai') files.forEach(f => aiHandleAttach(f));         // AI 开着 → 当附件
  else if (t === 'shenlun') slUploadPaper(files[0]);             // 真题页 → 上传真题卷
  else if (t === 'materials') uploadDropped(files);              // 资料库 → 传进当前分类
  else toast('把文件拖到「资料库」「真题批改」，或先打开 AI 面板', true);
};
window.__onPasteImage = (dataUrl) => {   // Ctrl+V / 右键「粘贴图片」
  fetch(dataUrl).then(r => r.blob()).then(b => {
    const f = new File([b], '粘贴的图片.png', { type: 'image/png' });
    const st = stack[stack.length - 1];
    if ($('#ai-panel') && !$('#ai-panel').classList.contains('hidden')) {
      toast('正在读取图片…'); aiHandleAttach(f);
    } else if (st && st.view === 'materials') {
      uploadDropped([f]);
    } else {
      openAI(); toast('正在读取图片…'); aiHandleAttach(f);       // 其它地方：直接开 AI 并附上
    }
  }).catch(() => toast('粘贴失败', true));
};

/* ================= 通用「划重点」（悬浮球 → 🖍） =================
   任何模块的正文都能划：不重渲染页面，而是直接在**已经渲染好的 DOM 里**找到那些句子、就地包一层 <mark>。
   所以时政、常识、理论、范文、讲义、错题解析…统统适用，不用每个模块单独写一遍。
   要害：AI 挑的句子必须逐字来自原文（服务端已核对），否则在 DOM 里根本找不到。 */
const MK_SKIP = 'button, input, textarea, select, nav, .topbar, .tk-tab, .chip, .btn, ' +
  '.pgbar, .fab, .bm-tip, .mk-bar, .mk-card, mark, script, style, .cd-sec-t, .slt-sec';
let mkMarks = [], mkRoot = null;

function mkPageRoot() {                 // 当前页面的「正文」在哪
  const st = stack[stack.length - 1];
  if (!st) return null;
  const view = $('#view-' + st.view);
  if (!view || view.classList.contains('hidden')) return null;
  // 优先取常见的正文容器；找不到就整页（跳过按钮/工具栏）
  const pick = view.querySelector('.poly-reader, .cd-wrap, #cd-wrap, .doc-blocks, .aih-scroll');
  return pick || view;
}
function mkText(root) {
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (!n.nodeValue.trim() || n.parentElement.closest(MK_SKIP))
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  let s = '';
  while (w.nextNode()) s += w.currentNode.nodeValue;
  return s;
}
function mkNodes(root) {
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (!n.nodeValue.trim() || n.parentElement.closest(MK_SKIP))
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  const out = []; let pos = 0;
  while (w.nextNode()) { out.push({ n: w.currentNode, start: pos }); pos += w.currentNode.nodeValue.length; }
  return out;
}
function mkWrapOne(root, hit) {
  // 每次重新取一遍节点表：上一处标注会改变 DOM，偏移必须重算
  const nodes = mkNodes(root);
  const k = NW_KIND[hit.kind] || NW_KIND['提法'];
  for (let i = nodes.length - 1; i >= 0; i--) {
    const { n, start } = nodes[i];
    const end = start + n.nodeValue.length;
    if (end <= hit.start || start >= hit.end) continue;
    const s = Math.max(0, hit.start - start), e = Math.min(n.nodeValue.length, hit.end - start);
    if (e <= s) continue;
    const r = document.createRange();
    r.setStart(n, s); r.setEnd(n, e);
    const mk = document.createElement('mark');
    mk.className = 'nw-mk gk-mk';
    mk.style.setProperty('--mk', k.c);
    mk.dataset.gkm = hit.i;
    mk.title = hit.kind + '：' + (hit.why || '');
    try { r.surroundContents(mk); } catch (_) { r.detach && r.detach(); continue; }
    const tag = document.createElement('i');   // 右上角的小类型标签
    tag.textContent = hit.kind;
    mk.appendChild(tag);
    break;                                     // 一个片段包一次就够（跨节点的下一轮再来）
  }
}
function mkApply(root, marks) {
  const full = mkText(root);
  const hits = [];
  marks.map((m, i) => ({ m, i })).sort((a, b) => b.m.quote.length - a.m.quote.length)   // 长句先标
    .forEach(({ m, i }) => {
      let from = 0, at;
      while ((at = full.indexOf(m.quote, from)) !== -1) {
        const end = at + m.quote.length;
        if (!hits.some(h => at < h.end && end > h.start)) hits.push({ start: at, end, i, kind: m.kind, why: m.why });
        from = end;
      }
    });
  hits.sort((a, b) => b.start - a.start);      // 从后往前改，前面的偏移才不会失效
  hits.forEach(h => mkWrapOne(root, h));
  return hits.length;
}
function mkClear() {
  document.querySelectorAll('mark.gk-mk').forEach(m => {
    const i = m.querySelector('i'); if (i) i.remove();
    const p = m.parentNode;
    while (m.firstChild) p.insertBefore(m.firstChild, m);
    p.removeChild(m);
    p.normalize();
  });
  mkMarks = []; mkRoot = null;
  $('#mk-bar').classList.add('hidden');
  $('#mk-list').classList.add('hidden');
  document.body.classList.remove('mk-open');
  if (window.mkInject) setTimeout(() => mkInject(), 60);   // 清完了，把「帮我划重点」的卡片长回来
}
/* 划重点：**按模块**做，不是一个全局按钮套所有页面。
   每个模块划的东西根本不是一回事 —— 常识划「定义/数字/易混」（选项就改那一个字），
   错题划「陷阱/正解」，范文划「分论点/论证/表达」。类型清单和「这个模块该看什么」
   都由服务端 MK_PROFILES 给（GET /api/marks/profile），前端不另写一份。
   入口是各模块页顶部自动长出来的一张卡片（和时政那张一样），不在悬浮球里。 */
const MK_COLORS = ['#c4661f', '#1e8449', '#1a6fb5', '#7a5cc0', '#b23b2e'];
let mkProf = null, mkProfScope = '';

// 哪些页面配划重点：服务端有 profile 的都算（问一次缓存住）
async function mkGetProf(scope) {
  if (mkProfScope === scope && mkProf) return mkProf;
  const d = await api('/api/marks/profile?scope=' + encodeURIComponent(scope));
  d.color = {};
  d.kinds.forEach((k, i) => { d.color[k.k] = MK_COLORS[i % MK_COLORS.length]; });
  mkProf = d; mkProfScope = scope;
  return d;
}
const MK_VIEWS = ['csboard', 'thboard', 'workd', 'partydict', 'policydocd', 'essayd', 'writed',
  'wqdetail', 'slresult', 'sltype', 'boardkb', 'docqad', 'cdetail', 'ckboard', 'viewer'];

// 进到有划重点的模块，就在正文顶部长出这张卡（时政那张是模块自己写的，不走这里）
async function mkInject() {
  const st = stack[stack.length - 1];
  const old = document.getElementById('mk-card');
  if (old) old.remove();
  if (!st || !MK_VIEWS.includes(st.view)) return;
  const root = mkPageRoot();
  if (!root || mkText(root).replace(/\s+/g, ' ').trim().length < 120) return;   // 正文太短不值当
  if (root.querySelector('mark.gk-mk')) return;                                  // 已经划过了
  let p;
  try { p = await mkGetProf(st.view); } catch (_) { return; }
  const card = document.createElement('div');
  card.id = 'mk-card'; card.className = 'mk-card';
  // focus 里用 **xx** 标了要强调的词（后端写的），转成粗体，别把星号露出来
  const bold = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  card.innerHTML = `<div class="mk-card-t">🖍 重点 · 考点</div>
    <p class="mk-card-p">${p.focus ? bold(p.focus) + '<br>' : ''}
      点一下，AI 按<b>「${esc(p.name)}」的考法</b>在本页标出：
      ${p.kinds.map(k => `<span class="mk-ck" style="--mk:${p.color[k.k]}">${esc(k.k)}</span>`).join('')}</p>
    <button class="btn primary" id="mk-go">🖍 帮我划重点</button>`;
  root.insertBefore(card, root.firstChild);
}
document.addEventListener('click', e => {
  if (e.target.closest('#mk-go')) markPage();
});

async function markPage(force) {
  if (document.querySelector('mark.gk-mk') && !force) { mkClear(); toast('已清除重点'); return; }
  if (document.querySelector('.nw-mk:not(.gk-mk)')) { toast('这页已经划过重点了'); return; }
  const root = mkPageRoot();
  const text = root ? mkText(root).replace(/\s+/g, ' ').trim() : '';
  if (!root || text.length < 60) { toast('这页没有可划的正文', true); return; }
  const scope = stack[stack.length - 1].view;
  const btn = $('#mk-go');
  if (btn) { btn.disabled = true; btn.textContent = '划重点中…（约 20 秒）'; }
  try {
    await mkGetProf(scope);
    const d = await api('/api/marks', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: mkText(root), scope }),
    });
    mkClear();
    mkRoot = root; mkMarks = d.marks || [];
    const n = mkApply(root, mkMarks);
    if (!n) { toast('这页的正文和 AI 挑的句子对不上，换个页面试试', true); return; }
    const c = document.getElementById('mk-card'); if (c) c.remove();
    mkRenderBar(n, !!d.cached);
    toast('划出 ' + n + ' 处重点' + (d.cached ? '（缓存）' : ''));
  } catch (e) {
    toast(e.message, true);
    if (btn) { btn.disabled = false; btn.textContent = '🖍 帮我划重点'; }
  }
}
function mkRenderBar(n, cached) {
  const p = mkProf || { name: '', kinds: [], color: {} };
  const col = (k) => p.color[k] || (NW_KIND[k] && NW_KIND[k].c) || MK_COLORS[0];
  $('#mk-bar').innerHTML = `🖍 划出 <b>${n}</b> 处重点${cached ? ' <i>· 缓存</i>' : ''}
    <button class="btn tiny" id="mk-toggle">看清单</button>
    <button class="mk-x" id="mk-clear" title="清除">✕</button>`;
  $('#mk-bar').classList.remove('hidden');
  $('#mk-list').innerHTML = `<div class="mk-lt">🖍 ${esc(p.name)} · 重点考点（${mkMarks.length} 处）</div>
    ${mkMarks.map((m, i) => `<div class="nw-m" data-mkgo="${i}" style="--mk:${col(m.kind)}">
        <span class="nw-k">${esc(m.kind)}</span>
        <span class="nw-q">${esc(m.quote)}</span>
        <span class="nw-w">${esc(m.why || '')}</span></div>`).join('')}
    <div class="nw-legend">${p.kinds.map(k =>
      `<span style="--mk:${col(k.k)}"><i></i>${esc(k.k)}：${esc(k.d)}</span>`).join('')}</div>`;
}
document.addEventListener('click', e => {
  if (e.target.closest('#mk-clear')) { mkClear(); return; }
  if (e.target.closest('#mk-toggle')) {
    const on = $('#mk-list').classList.toggle('hidden');
    $('#mk-toggle').textContent = on ? '看清单' : '收起清单';
    document.body.classList.toggle('mk-open', !on);   // 清单铺开时把悬浮球收起来，别互相挡
    return;
  }
  const go = e.target.closest('[data-mkgo]');
  if (go) {
    const el = document.querySelector(`mark.gk-mk[data-gkm="${go.dataset.mkgo}"]`);
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      el.classList.add('flash');
      setTimeout(() => el.classList.remove('flash'), 1400);
    }
  }
});
