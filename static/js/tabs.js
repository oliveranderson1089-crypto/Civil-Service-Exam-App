/* 底部标签栏（界面重构 P0：只加导航骨架，78 个 view 的内容一行没动）
 *
 * 这里本质是一张**路由表**：每个二级入口直接调已有的 openXxx()，跟点首页卡片走的是同一条路，
 * 所以本文件不含任何业务逻辑——以后加功能只要往 TAB_DEFS 里加一行。
 *
 * 分组维度是「动作」而不是「学科」：练 / 积累 / 库 / 我的。
 * 学科维度并没有丢：「专项突破」那一组按板块展开（板块清单直接读 BOARD_FEATURES，
 * 谁配了 drill 谁就出现，不用两头维护），每个标签页末尾还留着老的 openSection 入口，
 * 原来的 首页→行测→言语→专项练 那条路径一步没动，随时能退回去。
 *
 * 「今日」标签指向首页，而首页已经是今日仪表盘了（js/today.js，P1）；
 * 原来那张九宫格挪到了「我的 › 全部功能」。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 */
/* global $, api, artIcon, basicsFeats, BOARD_FEATURES, esc, goHome, LB_OPEN, lbGet, lbView, ME, switchLine,
   meView, openAccount, openAiOut, openBoardFeat, openChangkao, openChangshi, openChat, openCkBoard,
   openClassics, openDocqa, openDrafts, openDrill, openDrive, openDtest, openEssays,
   openExam, openFanwen, openFind, openGaikuo, openGongwen, openIdiom, openKb,
   openMaterials, openNews, openNotes, openPartyDict, openPlanLog, openPolicyDocs,
   openQuiz, openQuizSets, openRealq, openReview, openSection, openShenlun, openStars,
   openSucai, openTasks, openTheory, openVideos, openWorks, openWrite, openWrongq,
   openYyErr, openYyLib, lsGet, lsSet, pgSync, push, SECTIONS, stack, tdGet, tdRepaint */

const TB_SVG = (p) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;

/* 这些视图不出标签栏：它们要么是沉浸式做题/阅读，要么自己屏幕底部已经住了别人
   （小记和知识库的 .notes-pill / .kb-pill 就贴在 bottom:18px，两条栏叠一起没法看）。
   用「排除法」而不是「白名单」：以后新加的视图默认带标签栏，不会因为漏登记而丢导航。 */
const TAB_OFF = new Set([
  'notes', 'notebook', 'kb', 'doc', 'viewer', 'chat', 'search',
  'realrun', 'drillrun', 'findrun', 'quizrun', 'dtest', 'sqrun', 'sqwrite',
  'slgrade', 'slresult', 'writed', 'wqadd',
]);

/* 左栏该撤的场合比底栏少得多：底栏撤是因为手机上屏幕就那么大、底下还住着别的悬浮条；
   电脑上左栏只占 206px，做题时留着反而能中途跳去查个成语。只有真·全屏的两页才撤。 */
const RAIL_OFF = new Set(['doc', 'viewer']);

/* 板块清单从 BOARD_FEATURES 反查：配了 drill 的板块才有「专项练」。
   写死一份的话，core.js 那边加板块这里就会漏。 */
const tbBoardNames = () => Object.keys(BOARD_FEATURES)
  .filter(b => (BOARD_FEATURES[b] || []).some(f => f.key === 'drill'));

function tbDrillBoards() {
  return tbBoardNames().map(b => {
    const f = (BOARD_FEATURES[b] || []).find(x => x.key === 'drill') || {};
    return Object.assign({ name: b, desc: f.desc || '', go: () => openDrill(b) }, tbBoardStat(b));
  });
}

/* 板块的近 30 天成绩，挂在条目右侧。**没数据就什么都不显示** ——
   一道题没练过却写个「0%」，会让人以为自己练砸了。 */
function tbBoardStat(b) {
  const s = tbHub && tbHub.boards && tbHub.boards[b];
  if (!s) return {};
  if (s.rate == null) return s.wrong ? { stat: '错题 ' + s.wrong, statTone: 'warn' } : {};
  return { stat: s.rate + '%', statTone: s.rate < 60 ? 'bad' : s.rate < 80 ? 'warn' : 'good' };
}
// 积累模块今天新增了几条。key 和后端 mods/hub.py 的 _ACC_* 对齐
function tbAcc(k) {
  const n = tbHub && tbHub.acc && tbHub.acc[k];
  return n ? { stat: '今日 +' + n, statTone: 'new' } : {};
}

/* chip 选中某个板块时，把**板块页整页内联进来** —— 这是 P2 真正压掉的那一层：
   原来是 首页→行测→言语理解→专项练（4 层），现在是 练→(chip)言语→专项练（2 层）。
   功能清单和分派都借用板块页那一套（basicsFeats + BOARD_FEATURES + openBoardFeat），
   一份数据两处渲染，不会走散。 */
function tbBoardGroups(board) {
  const feats = [{ key: 'boardkb', name: 'AI 梳理 · 我的补充', desc: '按板块通梳 + 自己记的要点' }]
    .concat(window.basicsFeats ? basicsFeats(board) : [])
    .concat(BOARD_FEATURES[board] || []);
  const mk = (f) => Object.assign(
    { name: f.name, desc: f.desc, go: () => openBoardFeat(f.key, board) },
    f.key === 'drill' ? tbBoardStat(board) : tbAcc(f.key));
  const isPractice = (f) => f.key === 'drill' || f.practice;
  const practice = feats.filter(isPractice).map(mk);
  const rest = feats.filter(f => !isPractice(f) && !String(f.key).startsWith('bk') && f.key !== 'boardkb').map(mk);
  const know = feats.filter(f => String(f.key).startsWith('bk') || f.key === 'boardkb').map(mk);
  return [
    practice.length ? { name: '练', items: practice } : null,
    know.length ? { name: '知识点', items: know } : null,
    rest.length ? { name: '这个板块的积累', items: rest } : null,
  ].filter(Boolean);
}
// 每个标签页末尾都挂一条老路径的入口，等于「全部功能」的逃生门
function tbSections() {
  return (SECTIONS || []).map(s => ({
    name: s.name, desc: s.desc || '按板块逐层进入（原来的路径）', go: () => openSection(s.key),
  }));
}

/* 左栏里每个分组下常驻的快捷条目。
   **它不是 groups 的副本**：完整清单永远在 groups（标签页）里，这里只挑每天都点的那几个
   让它一步到位——目标图上「今日复习 12」「错题本 28」就是一眼可见、一键直达的。
   badge 是个函数，因为角标要等 /api/hub、/api/review 回来才有数。 */
const RAIL_ICON = {
  overview: TB_SVG('<rect x="3" y="4" width="18" height="17" rx="2.5"/><path d="M3 9.5h18"/>'),
  clock: TB_SVG('<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>'),
  check: TB_SVG('<path d="M9 12.5l2.5 2.5L16 10"/><rect x="3.5" y="4" width="17" height="17" rx="3"/>'),
  target: TB_SVG('<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4"/>'),
  layers: TB_SVG('<polygon points="12 3 3 7.5 12 12 21 7.5 12 3"/><polyline points="3 16.5 12 21 21 16.5"/>'),
  pen: TB_SVG('<path d="M11 4H4v16h16v-7"/><path d="M18.5 2.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4z"/>'),
  cross: TB_SVG('<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>'),
  word: TB_SVG('<path d="M4 19.2A2.3 2.3 0 0 1 6.3 17H20"/><path d="M6.3 2.5H20v19H6.3A2.3 2.3 0 0 1 4 19.2V4.8a2.3 2.3 0 0 1 2.3-2.3z"/>'),
  note: TB_SVG('<path d="M20.2 12.2a6 6 0 0 0-8.5-8.5L5 10.5V19h8.5z"/><line x1="16" y1="8" x2="2" y2="22"/>'),
  folder: TB_SVG('<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>'),
  /* AI 产出：一大一小两枚星芒，和「库」那一格（js/tabviews.js 的 LB_TILES）同一枚字形 ——
     同一个功能在左栏和格子里不该长两个样。 */
  aiout: TB_SVG('<path d="M12 3.2 13.9 8l4.9 1.9-4.9 1.9L12 16.6 10.1 11.8 5.2 9.9 10.1 8z"/><path d="M18.4 15.2l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>'),
  gear: TB_SVG('<circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.06a1.7 1.7 0 0 0-1.1-1.56 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.06A1.7 1.7 0 0 0 4.6 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1.03-1.56V3a2 2 0 1 1 4 0v.06A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9v.06a1.7 1.7 0 0 0 1.56 1.03H21a2 2 0 1 1 0 4h-.06A1.7 1.7 0 0 0 19.4 15z"/>'),
};

const TAB_DEFS = [
  {
    key: 'today', name: '今日', icon: TB_SVG('<rect x="3" y="4.5" width="18" height="16" rx="2.5"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/>'),
    home: true,      // 首页 = 今日仪表盘（js/today.js）
    rail: () => [
      { name: '今日概览', icon: 'overview', go: () => goHome() },
      { name: '今日复习', icon: 'clock', go: () => openReview(), badge: () => tbBadge.review },
      { name: '每日测试', icon: 'check', go: () => openDtest() },
    ],
  },
  {
    key: 'drill', name: '练', icon: TB_SVG('<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>'),
    // 板块名取前两字当 chip：「言语理解与表达」整个塞进胶囊会把一行挤成两行
    /* 「社区」是显式加的，不走 tbBoardNames() —— 那个函数按「配了 drill」反查，
       而社区的专项练还没有（P1 才灌题库）。硬塞个 drill 键会让「专项突破」那一组
       多出一个点进去没题的入口，那比多写一行更糟。 */
    chips: () => [{ key: '', name: '全部' }].concat(
      tbBoardNames().map(b => ({ key: b, name: b.slice(0, 2) })),
      [{ key: '社区', name: '社区' }]),
    groups: (chip) => chip ? tbBoardGroups(chip) : [
      { name: '真题实战', icon: 'target', items: [
        { name: '历年真题', desc: '国考 / 川考原卷 · 错题自动重现', go: () => openRealq() },
        { name: '题库', desc: '四川省考卷面 · 每周自动更新', go: () => openQuiz() },
        { name: '模拟卷', desc: '整卷计时 · 卷面还原', go: () => openQuizSets() },
        { name: '申论真题批改', desc: 'AI 逐点批改', go: () => openShenlun() },
        // shequ.js 在 rest 包，首屏包里不写裸名（同 shell.js 里那五个）
        { name: '社区真题', desc: '2023 / 2025 原卷 · 100 分整卷',
          go: () => window.openSqReal && window.openSqReal() },
      ] },
      { name: '专项突破', icon: 'layers', items: tbDrillBoards() },
      { name: '申论小题与成文', icon: 'pen', items: [
        { name: '小题训练', desc: '找点 + 写点', go: () => openFind() },
        { name: '应用文成文', desc: '14 文种四大类 · 每日成文', go: () => openWrite('yingyong') },
        { name: '议论文成文', desc: '素材 → 大作文', go: () => openWrite('daily') },
      ] },
      { name: '巩固与错题', icon: 'cross', badge: () => tbBadge.wrong, items: [
        { name: '巩固测试', desc: '考点来自今天学的', go: () => openDtest() },
        { name: '今日复习', desc: '遗忘曲线 · 该复习的都在这', go: () => openReview() },
        { name: '错题本', desc: '拍照 / 输入 · AI 判题型给解析', go: () => openWrongq() },
        { name: '题目解析', desc: '上传题目 · AI 出解析', go: () => openDocqa() },
      ] },
      { name: '按学科浏览', icon: 'overview', items: tbSections() },
    ],
  },
  {
    key: 'acc', name: '积累', icon: TB_SVG('<path d="M4 19.2A2.3 2.3 0 0 1 6.3 17H20"/><path d="M6.3 2.5H20v19H6.3A2.3 2.3 0 0 1 4 19.2V4.8a2.3 2.3 0 0 1 2.3-2.3z"/>'),
    chips: () => [{ key: '', name: '全部' }].concat(
      ['言语', '申论', '常识与理论', '时政', '高频'].map(n => ({ key: n, name: n === '常识与理论' ? '常识' : n }))),
    groups: (chip) => [
      { name: '言语', icon: 'word', items: [
        Object.assign({ name: '成语词语积累', desc: '选词填空 · 拼音释义 · 导 PDF', go: () => openIdiom() }, tbAcc('idiom')),
        Object.assign({ name: '上位词积累', desc: '逻辑填空概括词提示 · 每日推荐', go: () => openCkBoard('上位词') }, tbAcc('hyper')),
      ] },
      { name: '申论', icon: 'note', items: [
        Object.assign({ name: '素材积累', desc: '每日更新 · 人物 / 事例 / 理论论据', go: () => openSucai('全部') }, tbAcc('sucai')),
        Object.assign({ name: '衔接表达', desc: '过渡 / 转折 / 万能句式', go: () => openSucai('衔接表达') }, tbAcc('lianjie')),
        Object.assign({ name: '概括句积累', desc: '材料表述 → 规范概括句', go: () => openGaikuo() }, tbAcc('gaikuo')),
        Object.assign({ name: '应用文素材库', desc: '文种按真题频次排 · 下钻到结构部件', go: () => openYyLib() }, tbAcc('yylib')),
        { name: '应用文上位词', desc: '公文规范上位表述 · 按场景归类', go: () => openGongwen() },
        { name: '应用文改错', desc: '真题实证的格式错例', go: () => openYyErr() },
        Object.assign({ name: '人民时评 · 申论范文', desc: '每日抓评论版 · AI 拆结构与亮点', go: () => openFanwen() }, tbAcc('fanwen')),
        { name: '范文推荐', desc: '按题型挑的高分范文', go: () => openEssays() },
      ] },
      { name: '常识与理论', icon: 'check', items: [
        Object.assign({ name: '常识积累', desc: '人文 / 科技 / 法律… 七大板块', go: () => openChangshi() }, tbAcc('changshi')),
        { name: '理论基础', desc: '马原 · 毛概 · 中特 · 习思想', go: () => openTheory() },
        { name: '经典著作', desc: '原著要点速记', go: () => openWorks() },
        { name: '古诗文 · 名句速查', desc: '唐诗宋词 · 四书五经', go: () => openClassics() },
      ] },
      { name: '时政', icon: 'layers', items: [
        Object.assign({ name: '每日时政', desc: '每天自动更新 · AI 摘要 + 考点', go: () => openNews() }, tbAcc('news')),
        Object.assign({ name: '每日新闻视频', desc: '官方媒体 · 国内 / 国际 / 四川', go: () => openVideos() }, tbAcc('videos')),
        { name: '时政要文库', desc: '二十大 · 十五五 · 两会报告全文', go: () => openPolicyDocs() },
        { name: '党的创新理论学习词典', desc: '12371 术语速查', go: () => openPartyDict() },
      ] },
      { name: '高频', icon: 'target', items: [
        { name: '常考', desc: '高频成语 / 实词 / 上位词 / 常识 / 提法', go: () => openChangkao() },
      ] },
    ].filter(g => !chip || g.name === chip),
  },
  /* 库和我的这两页不走通用目录，各有一套首屏（js/tabviews.js，P4）：
     库 = 图标格 + 最近打开，我的 = 完成度环 + 紧凑清单。
     custom 给的是**渲染函数**不是 HTML：这两页都要拉接口，得自己控制「先出骨架、数据回来再补」。
     左栏（电脑端）用下面的 rail 直达具体功能，不再用分组标题当锚点——新版没有那几个分组了。 */
  {
    key: 'lib', name: '库', sub: '小记 · 知识库 · 资料',
    icon: TB_SVG('<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>'),
    custom: () => lbView(),
    rail: () => [
      { name: '小记', icon: 'note', go: () => openNotes() },
      { name: '知识库', icon: 'word', go: () => openKb() },
      { name: '草稿本', icon: 'pen', go: () => openDrafts() },
      { name: '资料库', icon: 'folder', go: () => openMaterials() },
      { name: '云盘', icon: 'layers', go: () => openDrive() },
      { name: '收藏', icon: 'target', go: () => openStars() },
      /* 「库」那一页有七个格子，左栏原来只有六条 —— AI 产出在电脑端没有入口。
         左栏和格子是同一份清单的两个形态，顺序也跟着格子走（tabviews.js 的 LB_TILES）。 */
      { name: 'AI 产出', icon: 'aiout', go: () => openAiOut() },
    ],
  },
  {
    key: 'me', name: '我的', sub: '统计 · 计划 · 设置',
    icon: TB_SVG('<circle cx="12" cy="8" r="3.6"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>'),
    custom: () => meView(),
    rail: () => [
      { name: '任务清单', icon: 'check', go: () => openTasks() },
      { name: '计划记录', icon: 'overview', go: () => openPlanLog() },
      { name: '今日复习', icon: 'clock', go: () => openReview(), badge: () => tbBadge.review },
      { name: '全国考情', icon: 'layers', go: () => openExam() },
      { name: '聊天', icon: 'word', go: () => openChat() },
      { name: '账户与外观', icon: 'target', go: () => openAccount() },
    ].concat(ME && ME.is_admin
      /* 顶栏的「后台」按钮被 style.css 收掉了（一律走「我的」），手机端在「我的」页里有这一条，
         电脑端左栏原来漏了 —— 管理员在宽屏上就完全找不到后台入口。ME 是 init 之后才有的，
         所以 shell.js 拿到 ME 会再调一次 tbRailFill() 把这条补画出来。 */
      ? [{ name: '管理后台', icon: 'gear', go: () => { location.href = '/admin'; } }]
      : []),
  },
];

let tbItems = [];      // 当前标签页展开后的扁平条目，点击时按下标取——省得把函数名塞进 DOM
let tbCur = '';        // 当前标签
let tbChip = {};       // 每个标签各自记着选中的 chip（切走再切回来还在原处）

/* 状态数字（正确率 / 今日新增）。两条原则：
   1) **渲染不等它** —— 拿不到就只是少几个角标，目录该点还能点。导航为几个数字转圈是本末倒置。
   2) **第一次打开标签页才拉** —— 挂在启动时拉，等于给每个只用首页的人白加一个请求。 */
let tbHub = null, tbHubOnce = false;
// 左栏角标。复习那条走已有的 /api/review/today?count=1（首页也在用），
// 错题数直接从 /api/hub 的各板块存量加起来 —— 不为一个角标再开一个接口。
const tbBadge = { review: 0, wrong: 0 };
async function tbLoadHub() {
  if (tbHubOnce) return;
  tbHubOnce = true;
  let d;
  try { d = await api('/api/hub'); } catch (_) { d = { boards: {}, acc: {} }; }
  tbHub = d;
  tbBadge.wrong = Object.values(d.boards || {}).reduce((n, b) => n + (b.wrong || 0), 0);
  try { tbRailFill(); } catch (_) { /* 页面已经不在 */ }
  // 回来时这一屏可能已经不在了（切走了、或者页面整个没了）。补画只是锦上添花，失败就算了。
  try {
    const v = $('#view-tab');
    if (tbCur && v && !v.classList.contains('hidden')) tbFill(tbCur);
  } catch (_) { /* 页面已经不在，不用补画 */ }
}

/* 自定义首屏（库 / 我的）也走这套「下标 + data-tbi」的点击分派：
   函数名塞不进 DOM，两边各写一套点击处理就会走散。tabviews.js 只管拼 HTML，
   每行登记一下拿个下标；重画前先 tbReset()，否则来回切几次 tbItems 就无限长了。 */
function tbItem(it) { return tbItems.push(it) - 1; }
function tbReset() { tbItems = []; }
// 回来晚了的异步渲染要先问一句「这一屏还在不在」，别画到已经切走的标签上
function tbIsCur(key) { return tbCur === key && !$('#view-tab').classList.contains('hidden'); }
window.tbItem = tbItem;
window.tbReset = tbReset;
window.tbIsCur = tbIsCur;
// tbBadge 也得挂上去：tabviews.js 读的是 window.tbBadge，少了这一行
// 「我的」里的今日复习角标永远是 0，而左栏同一时刻显示着 12。
window.tbBadge = tbBadge;

function tbRow(it) {
  const i = tbItems.push(it) - 1;
  /* 标题**不能用 <b>**：夜间有条全局的 body.dark b{color:#f0c674!important}（正文着重用的金色），
     列表标题套上去会整片变金。应用里其他列表（.bc-name 等）也都是 span，这里跟着来。 */
  return `<div class="board-card tab-row" data-tbi="${i}" tabindex="0" role="button">
    <span class="tr-text"><span class="tr-n">${esc(it.name)}</span>${it.desc ? `<span class="tr-d">${esc(it.desc)}</span>` : ''}</span>
    ${it.stat ? `<span class="tr-stat ${esc(it.statTone || '')}">${esc(it.stat)}</span>` : ''}
    <span class="bc-arrow">›</span>
  </div>`;
}

// 只重画内容，不动导航栈。切 chip、状态数字回来晚了，都走这儿
function tbFill(key) {
  const def = TAB_DEFS.find(t => t.key === key);
  if (!def) return;
  if (def.custom) {                       // 库 / 我的：自己拉数据、自己渲染（js/tabviews.js）
    $('#tab-chips').innerHTML = '';
    $('#tab-chips').classList.add('hidden');
    def.custom();
    return;
  }
  if (!def.groups) return;
  const chips = def.chips ? def.chips() : [];
  const cur = tbChip[key] || '';
  tbItems = [];
  const groups = def.groups(cur);
  const body = groups.map((g, i) =>
    `<div class="tab-gh" id="tg-${i}">${esc(g.name)}</div><div class="board-grid">${g.items.map(tbRow).join('')}</div>`
  ).join('');
  $('#tab-chips').innerHTML = chips.length
    ? chips.map(c => `<button class="chip${c.key === cur ? ' active' : ''}" data-tbc="${esc(c.key)}">${esc(c.name)}</button>`).join('')
    : '';
  $('#tab-chips').classList.toggle('hidden', !chips.length);
  $('#tab-groups').innerHTML = body || '<p class="empty">这个分类下暂时没有内容。</p>';
  /* 选中的板块可能在横滚条的屏幕外（板块有六七个）：切走再回来时它就被切在边上，
     看着像没选中。block:'nearest' 是必须的，否则整页会跟着往下跳一截。 */
  try {
    const act = $('#tab-chips .chip.active');
    if (act && act.scrollIntoView) act.scrollIntoView({ inline: 'center', block: 'nearest' });
  } catch (_) { /* jsdom 之类没实现 scrollIntoView，位置不对不影响能不能点 */ }
}

function tbRender(key) {
  const def = TAB_DEFS.find(t => t.key === key);
  if (!def || !(def.groups || def.custom)) return;
  tbCur = key;
  tbLoadHub();                 // 第一次进标签页才去拉状态数字，之后走缓存
  // 副标题只是给这一页一句定位（「小记 · 知识库 · 资料」），没有就只出标题
  $('#tab-title').innerHTML = esc(def.name)
    + (def.sub ? `<span class="tab-sub">${esc(def.sub)}</span>` : '');
  tbFill(key);
  // 标签之间是平级切换，不该越堆越深：每次都把栈压回「首页 + 本标签页」两层，
  // 这样返回键从任何标签都是一步回首页，安卓的侧滑返回也不会退出到上一个标签。
  stack = [{ view: 'home' }];
  push({ view: 'tab', title: def.name, tab: key });
}

$('#tab-chips').addEventListener('click', e => {
  const c = e.target.closest('[data-tbc]'); if (!c || !tbCur) return;
  tbChip[tbCur] = c.dataset.tbc;
  tbFill(tbCur);
  $('#view-tab').scrollTop = 0;
});

$('#tab-groups').addEventListener('click', e => {
  // 备考方向的切换按钮（「我的」页最上面那块）
  const ln = e.target.closest('[data-line]');
  if (ln) { if (window.switchLine) switchLine(ln.dataset.line); return; }
  const r = e.target.closest('[data-tbi]'); if (!r) return;
  const it = tbItems[+r.dataset.tbi];
  if (it && it.go) it.go();
});

/* 手机的底部标签栏和电脑的左侧导航栏是**同一份 TAB_DEFS 的两个形态**（P3）。
   两边共用一套 data-tb 和同一个点击处理：加一个标签只改 TAB_DEFS，不用两头对。
   谁出现由 CSS 断点决定（≤760 出底栏，≥761 出左栏），JS 不判断屏幕宽度——
   否则浏览器窗口一拖动，两边就对不上了。 */
/* 图标现取不写死：主题带自己的一册字形（js/articons.js），换主题时 artIconsRepaint()
   会再调一次这里。取不到册子就用 TAB_DEFS 里那枚默认的。 */
function tbFillBar() {
  $('#tabbar').innerHTML = TAB_DEFS.map(t =>
    `<button class="tb" data-tb="${esc(t.key)}">${window.artIcon ? artIcon(t.key, t.icon) : t.icon}<i>${esc(t.name)}</i></button>`).join('');
  tbBarMark();
}
/* 底栏高亮：和左栏 tbRailMark 一个口径——认**栈里最近的那个标签页**，不是当前视图。
   单独拎出来是因为换主题会整段重画底栏，重画完得把亮着的那格找回来
   （原来这段内联在 __tabView 里，重画后就只能等下一次切视图才恢复）。 */
function tbBarMark() {
  const bar = $('#tabbar'); if (!bar) return;
  const t = [...stack].reverse().find(s => s.view === 'tab');
  const cur = (stack.length <= 1 && (stack[0] || {}).view === 'home') ? 'today' : (t ? t.tab : '');
  bar.querySelectorAll('[data-tb]').forEach(b => b.classList.toggle('on', b.dataset.tb === cur));
}
tbFillBar();
/* 左栏是**两级**：分组标题 = 标签页（点了看全部），组内 = 那个标签下每天都点的几个（直达）。
   只有一级的话，任何一个二级功能都要「先点标签、再在页里找」，等于把省下来的那层又加回去。 */
/* 左栏每个分组底下摆什么 —— **只有一套形式**。
   「今日」没有对应的标签页，用它自己那份固定捷径；
   其余标签一律用**那个标签页里的分组标题**（真题实战 / 专项突破 / …），点了就跳到那一段。

   所以分组名要经得起「离开上下文单看」：「我记的 / 我存的 / 往来」当段落标题还读得懂，
   一摆进左栏就认不出是什么，得叫「笔记与草稿 / 文件与云盘 / 消息与好友」。

   原来是两套并排：上面一排我挑的捷径（历年真题、专项练…），下面又铺一排分组锚点
   （真题实战、专项突破…）—— 概念还重复，一个分组能占九行。 */
function tbRailItems(t) {
  if (t.rail) return t.rail();
  return (t.groups ? t.groups('') : []).map(g => ({
    name: g.name, icon: g.icon, badge: g.badge,
    go: () => tbGoGroup(t.key, g.name),
  }));
}

/* 跳到某个标签页的某一组。
   先把 chip 清掉：选着「言语」的时候点「时政」，那一组根本没渲染出来，滚过去会扑空。 */
function tbGoGroup(key, name) {
  tbChip[key] = '';
  if (tbCur === key && !$('#view-tab').classList.contains('hidden')) tbFill(key);
  else tbRender(key);
  const h = [...document.querySelectorAll('#tab-groups .tab-gh')].find(x => x.textContent === name);
  if (h && h.scrollIntoView) { try { h.scrollIntoView({ block: 'start', behavior: 'smooth' }); } catch (_) { /* 没实现就算了 */ } }
}

/* 左栏五组**只展开一组**（界面重构 P5）。
   原来五组全铺开是 20+ 项，1440 高的窗口里 scrollHeight 1140 > clientHeight 1024，
   进来就得滚 —— 一个常驻导航栏需要滚动，等于每次都要先找一下自己在哪。
   展开的是**当前所在的那一组**，别的收起来；想去别处点一下组名就换过去。

   收起来的组仍然可点（组名 = 那个标签页），所以折叠没有藏功能，
   只是把「此刻用不到的十几行」暂时收走。 */
const SR_CHEV = '<svg class="sr-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7"/></svg>';
let tbRailOpen = '';          // 手动点开的那一组；空则跟着当前标签走

function tbRailFill() {
  $('#siderail').innerHTML = TAB_DEFS.map(t => {
    const subs = tbRailItems(t).map((it, i) => {
      const n = it.badge ? it.badge() : 0;
      return `<button class="sr-i" data-srq="${esc(t.key)}:${i}">
        ${window.artIcon ? artIcon(it.icon, RAIL_ICON[it.icon] || '') : (RAIL_ICON[it.icon] || '')}<i>${esc(it.name)}</i>
        ${n ? `<span class="sr-bd">${n > 99 ? '99+' : n}</span>` : ''}</button>`;
    }).join('');
    /* 组内条目的角标要冒到组头上：这一组收起来的时候，「今日复习还有 23 条」
       不该跟着一起消失 —— 那正是你需要它提醒你的时候。 */
    const tot = tbRailItems(t).reduce((a, it) => a + (it.badge ? it.badge() : 0), 0);
    const head = `<button class="sr-g-h" data-tb="${esc(t.key)}" aria-expanded="false">${SR_CHEV}<i>${esc(t.name)}</i>`
      + `${tot ? `<span class="sr-bd sr-bd-g">${tot > 99 ? '99+' : tot}</span>` : ''}</button>`;
    if (!subs) {
      return head.replace(' aria-expanded="false"', '').replace('class="sr-g-h"', 'class="sr-g-h sr-solo"')
        .replace(SR_CHEV, '');
    }
    return head + `<div class="sr-g" data-srg="${esc(t.key)}">${subs}</div>`;
  }).join('');
  tbRailMark();
}
/* 高亮 + 展开：分组标题跟着当前标签，条目跟着当前视图。
   两件事同一个口径（栈里最近的那个标签页），所以放在一起算，
   不然会出现「亮着的是练、展开的是积累」。 */
function tbRailMark() {
  const rail = $('#siderail'); if (!rail) return;
  const t = [...stack].reverse().find(s2 => s2.view === 'tab');
  const cur = (stack.length <= 1 && (stack[0] || {}).view === 'home') ? 'today' : (t ? t.tab : '');
  rail.querySelectorAll('[data-tb]').forEach(b => b.classList.toggle('on', b.dataset.tb === cur));
  const open = tbRailOpen || cur;
  rail.querySelectorAll('.sr-g-h[data-tb]').forEach(b =>
    b.setAttribute('aria-expanded', String(b.dataset.tb === open)));
  rail.querySelectorAll('[data-srg]').forEach(g =>
    g.classList.toggle('open', g.dataset.srg === open));
}
tbRailFill();

/* 复习条数由「今日」仪表盘那次请求顺带喂过来（同一份数据，不重复拉）。
   角标是异步到的，所以得能就地重画。 */
function tbSetReview(n) {
  if (tbBadge.review === n) return;
  tbBadge.review = n;
  try { tbRailFill(); } catch (_) { /* 页面已经不在 */ }
}
window.tbSetReview = tbSetReview;

/* 左栏是 fixed 的，得知道顶栏有多高才能贴在它下面。**量出来而不是写死 56px**：
   顶栏高度跟字号、安全区都有关，写死的话换个系统字体就会露出一条缝或压掉一截。 */
function tbTopbar() {
  const t = document.querySelector('.topbar');
  if (t && t.offsetHeight) document.body.style.setProperty('--topbar-h', t.offsetHeight + 'px');
}
addEventListener('resize', tbTopbar);
tbTopbar();

/* ================= 左栏收起（顶栏那个开关 / Ctrl+B） =================
   左栏是常驻导航，值那 206px —— 但不是每时每刻都值：读一份长文档、或者右半屏
   停着 AI 助手来回改稿的时候，正文能多 206px 比「随时能跳去查成语」要紧得多。

   所以做成**收起**而不是自适应隐藏：由人按需要拨，机器不替他猜。
   记进 localStorage —— 这是「我现在要多少地方」的姿势，不是一次性动作，
   下次进来还该是这个样子。 */
function railOff(off) {
  document.body.classList.toggle('rail-off', !!off);
  const b = $('#rail-toggle');
  if (b) {
    b.setAttribute('aria-expanded', String(!off));
    b.setAttribute('aria-label', off ? '展开左侧导航' : '收起左侧导航');
  }
  lsSet('rail:off', off ? '1' : '0');
  /* 翻页条挂在正文右下角、按正文的边界算位置：正文一变宽它就得重算，
     而这次变宽既没有 scroll 也没有 resize，不叫它就会停在原来那个位置。
     写成 window.pgSync 而不是裸 pgSync：这个函数在**首屏包的顶层**被调过一次
     （下面那行按记住的姿势摆位），而 pgSync 住在 defer 的 rest 包里 ——
     首屏包里出现它的裸名字，线上会停在启动屏（见 assets.py 的闸二）。 */
  if (window.pgSync) requestAnimationFrame(() => window.pgSync());
}
function railToggle() { railOff(!document.body.classList.contains('rail-off')); }
window.railToggle = railToggle;
railOff(lsGet('rail:off') === '1');
$('#rail-toggle').addEventListener('click', railToggle);

function tbNav(e) {
  const b = e.target.closest('[data-tb]'); if (!b) return;
  const key = b.dataset.tb;
  const def = TAB_DEFS.find(t => t.key === key);
  if (def && def.home) { goHome(); return; }
  tbRender(key);
}
$('#tabbar').addEventListener('click', tbNav);
$('#siderail').addEventListener('click', e => {
  // 快捷条目：直达那个功能
  const q = e.target.closest('[data-srq]');
  if (q) {
    const [key, i] = q.dataset.srq.split(':');
    const def = TAB_DEFS.find(t => t.key === key);
    const it = def && tbRailItems(def)[+i];
    if (it && it.go) it.go();
    return;
  }
  /* 单独点箭头 = 只展开、不跳转（想扫一眼别的组里有什么）。
     点组名本身 = 跳过去，展开跟着当前标签自动发生，所以顺手把手动状态清掉。 */
  const h = e.target.closest('.sr-g-h[data-tb]');
  if (h && e.target.closest('.sr-chev')) {
    tbRailOpen = (tbRailOpen === h.dataset.tb) ? '__none' : h.dataset.tb;
    tbRailMark();
    return;
  }
  tbRailOpen = '';
  tbNav(e);
});


/* 由 shell.js 的 render() 每次切视图时回调（跟 __padView / __bmView 一个路子）。
   高亮认的是**栈里最近的那个标签页**，不是当前视图——这样从「积累」进到成语积累里面，
   底下亮的还是「积累」，不会一进二级页就全灭。 */
window.__tabView = function (view) {
  const bar = $('#tabbar'); if (!bar) return;
  // 顶栏高度会变：返回键一出现就高 1px（它带边框）。不跟着重算，左栏顶上就露一条缝
  tbTopbar();
  const on = !TAB_OFF.has(view);
  bar.classList.toggle('hidden', !on);
  document.body.classList.toggle('has-tabs', on);
  tbBarMark();
  const rail = $('#siderail');
  if (rail) {
    /* 左栏和底栏的「该不该出现」不一样：手机上做题要整屏专注，
       电脑上宽度管够，左栏留着反而方便中途跳去查东西 —— 所以左栏只在真沉浸的几页才撤
       （阅读器全屏、文档编辑器），做题页照常保留。 */
    const railOn = !RAIL_OFF.has(view);
    rail.classList.toggle('hidden', !railOn);
    document.body.classList.toggle('has-rail', railOn);
    tbRailMark();
  }
  srRightSync(view);
  /* 翻页条要跟着重算：内容是异步来的，页面从「滚不动」变成「滚得动」的那一刻
     既没有 scroll 也没有 resize，光靠那两个事件它会一直停在收起态。 */
  if (window.pgSync) requestAnimationFrame(pgSync);
};

/* ================= 右侧「随手栏」（界面重构 P5） =================
   1920 宽下内容列右边空着 296px，1440 下空 176px —— 那块地方一直在，只是没人用。
   这里把它填成一栏常驻的「此刻还欠什么」：待办、今天进了什么新东西、最近打开过什么。

   **不加接口**：三段数据首页和库页本来就在拉（/api/today、/api/lib/home），
   这里只是把同一份再画一遍（tdGet / lbGet）。拿不到就整段不出现，
   不摆骨架屏 —— 它是配角，为它闪一下不值得。

   出现的条件比左栏严：左栏 206 是恒定成本，这一栏 250 只有在
   「左栏 + 内容列 + 它」都摆得下（≥1360）时才划算，否则会把内容列挤窄。 */
const SR_R_OFF = new Set(['doc', 'viewer', 'chat', 'notes', 'notebook', 'kb',
  'realrun', 'drillrun', 'findrun', 'quizrun', 'dtest', 'sqrun', 'sqwrite',
  'slgrade', 'slpaper', 'writed']);

function srRow(name, val, go) {
  const i = tbItem({ go });
  return `<button class="srr-row" data-tbi="${i}"><span class="srr-n">${esc(name)}</span>`
    + (val ? `<span class="srr-v">${esc(String(val))}</span>` : '') + '</button>';
}
function srRightFill() {
  /* 这个函数会在 await 之后被调到（tdLoad 拉完接口才喂它），那时页面**可能已经没了**：
     用户点了返回、壳退出、或者测试把 jsdom 的 window 关掉了。
     document 一没，$() 里的 document.querySelector 就是在 undefined 上取属性。
     所有「await 之后才碰 DOM」的地方都该先问这一句。 */
  if (typeof document === 'undefined' || !document) return;
  const box = $('#siderail-r');
  if (!box || box.classList.contains('hidden')) return;
  const d = window.tdGet ? tdGet() : null;
  const lb = window.lbGet ? lbGet() : null;
  let html = '';
  if (d) {
    const rows = [];
    const rv = tbBadge.review;
    if (rv) rows.push(srRow('今日复习', rv, () => openReview()));
    if (d.tasks && d.tasks.total) {
      rows.push(srRow('任务清单', `${d.tasks.done}/${d.tasks.total}`, () => openTasks()));
    }
    if (d.plan && d.plan.total) {
      rows.push(srRow('今日计划', `${d.plan.done}/${d.plan.total}`, () => openPlanLog()));
    }
    if (rows.length) html += '<div class="srr-h">待办</div>' + rows.join('');
    const ups = d.updates || [];
    if (ups.length) {
      html += '<div class="srr-h">今日更新</div>'
        + ups.map(u => srRow(u.name, '+' + u.n, () => { const f = SR_R_GO[u.go]; if (f) f(); })).join('');
    }
  }
  const recent = (lb && lb.recent) || [];
  if (recent.length) {
    html += '<div class="srr-h">最近打开</div>'
      + recent.slice(0, 4).map(it => srRow(it.title, '', () => {
        const f = LB_OPEN[it.kind]; if (f) f(it.id, it);
      })).join('');
  }
  box.innerHTML = html;
  box.classList.toggle('srr-empty', !html);
}
// 「今日更新」点进去是谁。key 跟 today.js 的 TD_GO 对齐
const SR_R_GO = {
  news: () => openNews(), sucai: () => openSucai('全部'), fanwen: () => openFanwen(),
  videos: () => openVideos(), gaikuo: () => openGaikuo(), changshi: () => openChangshi(),
};
/* 「最近打开」这一段**直接借 tabviews.js 的 LB_OPEN**，不再自己抄一份。
   原来这里有一张 SR_R_OPEN，注释也写着「跟 LB_OPEN 对齐」—— 实际上早就对不上了：
   它认的是 doc / kb，接口给的却是 material / kbdoc，于是宽屏随手栏里
   知识库文档和资料库那两条**点了毫无反应**（不报错，就是不动，所以一直没人发现）。
   两份表只要分开写就会再飘一次，索性只留一份。 */
/* 随手栏此刻是不是真的在屏幕上。
   有两个条件：这一页允许出（srRightSync）+ 窗口够宽（CSS 的 1360 断点）。
   首页要问这一句：待办和今日更新一旦进了随手栏，中间就不该再写一遍 ——
   两栏并排显示同样三行，看着像出了 bug。 */
const SR_R_MIN = 1360;
function srRightOn() {
  return document.body.classList.contains('has-rrail') && srRoom() >= SR_R_MIN;
}
window.srRightOn = srRightOn;

/* 首页那两段（待办 / 今日更新）住哪一边，取决于随手栏此刻在不在。
   而首页是**自己起跑的**（today.js 末尾直接 tdLoad()），它渲染的时候
   has-rrail 还没挂上 —— 于是第一屏两边都画了一份。
   所以这里每次改变随手栏的在/不在，都要回头让首页重画一次。 */
let srWasOn = null, srLastView = '';

/* 横向还剩多少地方**能摆东西**。不能用 innerWidth：AI 助手 / 草稿纸停靠成半屏之后
   窗口还是那么宽，可用的却只剩另外半屏 —— 随手栏照 innerWidth 判断，就会继续
   占着右边那 250px，而它自己被面板整个盖住：中间白空一条谁也用不上（正文以为
   右边有栏所以让位，实际那儿是面板）。
   读 --push-l/--push-r 而不是 body 的 padding：那两个是 dock.js 写死的最终值，
   不吃 padding 上的 .18s 过渡 —— 过渡途中量 padding 会量到一个中间数。 */
function srRoom() {
  const st = document.body.style;
  const n = v => parseFloat(st.getPropertyValue(v)) || 0;
  return (window.innerWidth || 0) - n('--push-l') - n('--push-r');
}

/* view 省略 = 「视图没变，只是地方变了」（面板停靠/收起、窗口缩放）。 */
function srRightSync(view) {
  const box = $('#siderail-r');
  if (!box) return;
  if (view !== undefined) srLastView = view;
  const on = !SR_R_OFF.has(srLastView) && srRoom() >= SR_R_MIN;
  box.classList.toggle('hidden', !on);
  document.body.classList.toggle('has-rrail', on);
  if (on) srRightFill();
  const now = srRightOn();
  if (now !== srWasOn) {
    srWasOn = now;
    if (window.tdRepaint) tdRepaint();
  }
}
/* 拖窗口跨过 1360 时，随手栏要出现/撤走，首页那两段也得在中间和它之间搬家。
   只在**真的跨过**断点时动，不然拖动过程中每一帧都在重排。
   （重画首页交给 srRightSync 内部那次差异判断，别在这儿再来一遍。） */
let srWasWide = srRoom() >= SR_R_MIN;
addEventListener('resize', () => {
  const now = srRoom() >= SR_R_MIN;
  if (now === srWasWide) return;
  srWasWide = now;
  srRightSync();
});
/* 面板停靠 / 收起 / 拖宽窄，可用宽度就变了 —— 由 dock.js 的 applyPush 末尾回调。 */
window.srRoomSync = function () {
  if (!srLastView) return;      // 还没进过任何视图（启动途中）：这时的 on/off 由 __tabView 说了算
  const now = srRoom() >= SR_R_MIN;
  srWasWide = now;
  srRightSync();
};
$('#siderail-r').addEventListener('click', e => {
  const r = e.target.closest('[data-tbi]'); if (!r) return;
  const it = tbItems[+r.dataset.tbi];
  if (it && it.go) it.go();
});
window.srRightFill = srRightFill;
