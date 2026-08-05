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
/* global $, BOARD_FEATURES, ME, SECTIONS, api, basicsFeats, esc, goHome,
   openBoardFeat, push, stack,
   openAccount, openAllFeats, openChangkao, openChangshi, openChat, openCkBoard, openClassics,
   openDocqa, openDrafts, openDrill, openDrive, openDtest, openEssays, openExam,
   openFanwen, openFind, openGaikuo, openGongwen, openIdiom, openKb, openMaterials,
   openNews, openNotes, openNotify, openPartyDict, openPlanLog, openPolicyDocs,
   openQuiz, openQuizSets, openRealq, openReview, openSection, openShenlun,
   openSucai, openTasks, openTheory, openVideos, openWorks, openWrite,
   openWrongq, openYyErr, openYyLib */

const TB_SVG = (p) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;

/* 这些视图不出标签栏：它们要么是沉浸式做题/阅读，要么自己屏幕底部已经住了别人
   （小记和知识库的 .notes-pill / .kb-pill 就贴在 bottom:18px，两条栏叠一起没法看）。
   用「排除法」而不是「白名单」：以后新加的视图默认带标签栏，不会因为漏登记而丢导航。 */
const TAB_OFF = new Set([
  'notes', 'notebook', 'kb', 'doc', 'viewer', 'chat', 'search',
  'realrun', 'drillrun', 'findrun', 'quizrun', 'dtest',
  'slgrade', 'slresult', 'writed', 'wqadd',
]);

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
  const practice = feats.filter(f => f.key === 'drill').map(mk);
  const rest = feats.filter(f => f.key !== 'drill' && !String(f.key).startsWith('bk') && f.key !== 'boardkb').map(mk);
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

const TAB_DEFS = [
  {
    key: 'today', name: '今日', icon: TB_SVG('<rect x="3" y="4.5" width="18" height="16" rx="2.5"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/>'),
    home: true,      // 首页 = 今日仪表盘（js/today.js）
  },
  {
    key: 'drill', name: '练', icon: TB_SVG('<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>'),
    // 板块名取前两字当 chip：「言语理解与表达」整个塞进胶囊会把一行挤成两行
    chips: () => [{ key: '', name: '全部' }].concat(
      tbBoardNames().map(b => ({ key: b, name: b.slice(0, 2) }))),
    groups: (chip) => chip ? tbBoardGroups(chip) : [
      { name: '真题实战', items: [
        { name: '历年真题', desc: '国考 / 川考原卷 · 错题自动重现', go: () => openRealq() },
        { name: '题库', desc: '四川省考卷面 · 每周自动更新', go: () => openQuiz() },
        { name: '模拟卷', desc: '整卷计时 · 卷面还原', go: () => openQuizSets() },
        { name: '申论真题批改', desc: 'AI 逐点批改', go: () => openShenlun() },
      ] },
      { name: '专项突破', items: tbDrillBoards() },
      { name: '申论小题与成文', items: [
        { name: '小题训练', desc: '找点 + 写点', go: () => openFind() },
        { name: '应用文成文', desc: '14 文种四大类 · 每日成文', go: () => openWrite('yingyong') },
        { name: '议论文成文', desc: '素材 → 大作文', go: () => openWrite('daily') },
      ] },
      { name: '巩固与错题', items: [
        { name: '巩固测试', desc: '考点来自今天学的', go: () => openDtest() },
        { name: '今日复习', desc: '遗忘曲线 · 该复习的都在这', go: () => openReview() },
        { name: '错题本', desc: '拍照 / 输入 · AI 判题型给解析', go: () => openWrongq() },
        { name: '题目解析', desc: '上传题目 · AI 出解析', go: () => openDocqa() },
      ] },
      { name: '按学科浏览', items: tbSections() },
    ],
  },
  {
    key: 'acc', name: '积累', icon: TB_SVG('<path d="M4 19.2A2.3 2.3 0 0 1 6.3 17H20"/><path d="M6.3 2.5H20v19H6.3A2.3 2.3 0 0 1 4 19.2V4.8a2.3 2.3 0 0 1 2.3-2.3z"/>'),
    chips: () => [{ key: '', name: '全部' }].concat(
      ['言语', '申论', '常识与理论', '时政', '高频'].map(n => ({ key: n, name: n === '常识与理论' ? '常识' : n }))),
    groups: (chip) => [
      { name: '言语', items: [
        Object.assign({ name: '成语词语积累', desc: '选词填空 · 拼音释义 · 导 PDF', go: () => openIdiom() }, tbAcc('idiom')),
        Object.assign({ name: '上位词积累', desc: '逻辑填空概括词提示 · 每日推荐', go: () => openCkBoard('上位词') }, tbAcc('hyper')),
      ] },
      { name: '申论', items: [
        Object.assign({ name: '素材积累', desc: '每日更新 · 人物 / 事例 / 理论论据', go: () => openSucai('全部') }, tbAcc('sucai')),
        Object.assign({ name: '衔接表达', desc: '过渡 / 转折 / 万能句式', go: () => openSucai('衔接表达') }, tbAcc('lianjie')),
        Object.assign({ name: '概括句积累', desc: '材料表述 → 规范概括句', go: () => openGaikuo() }, tbAcc('gaikuo')),
        Object.assign({ name: '应用文素材库', desc: '文种按真题频次排 · 下钻到结构部件', go: () => openYyLib() }, tbAcc('yylib')),
        { name: '应用文上位词', desc: '公文规范上位表述 · 按场景归类', go: () => openGongwen() },
        { name: '应用文改错', desc: '真题实证的格式错例', go: () => openYyErr() },
        Object.assign({ name: '人民时评 · 申论范文', desc: '每日抓评论版 · AI 拆结构与亮点', go: () => openFanwen() }, tbAcc('fanwen')),
        { name: '范文推荐', desc: '按题型挑的高分范文', go: () => openEssays() },
      ] },
      { name: '常识与理论', items: [
        Object.assign({ name: '常识积累', desc: '人文 / 科技 / 法律… 七大板块', go: () => openChangshi() }, tbAcc('changshi')),
        { name: '理论基础', desc: '马原 · 毛概 · 中特 · 习思想', go: () => openTheory() },
        { name: '经典著作', desc: '原著要点速记', go: () => openWorks() },
        { name: '古诗文 · 名句速查', desc: '唐诗宋词 · 四书五经', go: () => openClassics() },
      ] },
      { name: '时政', items: [
        Object.assign({ name: '每日时政', desc: '每天自动更新 · AI 摘要 + 考点', go: () => openNews() }, tbAcc('news')),
        Object.assign({ name: '每日新闻视频', desc: '官方媒体 · 国内 / 国际 / 四川', go: () => openVideos() }, tbAcc('videos')),
        { name: '时政要文库', desc: '二十大 · 十五五 · 两会报告全文', go: () => openPolicyDocs() },
        { name: '党的创新理论学习词典', desc: '12371 术语速查', go: () => openPartyDict() },
      ] },
      { name: '高频', items: [
        { name: '常考', desc: '高频成语 / 实词 / 上位词 / 常识 / 提法', go: () => openChangkao() },
      ] },
    ].filter(g => !chip || g.name === chip),
  },
  {
    key: 'lib', name: '库', icon: TB_SVG('<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>'),
    groups: () => [
      { name: '我记的', items: [
        { name: '小记', desc: '随手记 · 标签归类', go: () => openNotes() },
        { name: '知识库', desc: '笔记本 · 文档 · 分组整理', go: () => openKb() },
        { name: '草稿本', desc: '草稿纸留下的手写与演算', go: () => openDrafts() },
      ] },
      { name: '我存的', items: [
        { name: '资料库', desc: '图片 / 文档 / 网页 应用内查看', go: () => openMaterials() },
        { name: '云盘', desc: '存取任意文件 · 发给好友', go: () => openDrive() },
      ] },
    ],
  },
  {
    key: 'me', name: '我的', icon: TB_SVG('<circle cx="12" cy="8" r="3.6"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>'),
    groups: () => [
      { name: '学习安排', items: [
        { name: '任务清单', desc: '每日任务 · 互监待办', go: () => openTasks() },
        { name: '计划记录', desc: '进度回顾 · AI 分析', go: () => openPlanLog() },
        { name: '今日复习', desc: '遗忘曲线', go: () => openReview() },
      ] },
      { name: '资讯', items: [
        { name: '全国考情', desc: '国考 / 省考 / 事考公告 每天汇总', go: () => openExam() },
      ] },
      { name: '往来', items: [
        { name: '聊天', desc: '加好友 · 聊天 · 传文件', go: () => openChat() },
        { name: '消息', desc: '通知与提醒', go: () => openNotify() },
      ] },
      { name: '设置', items: [
        { name: '全部功能', desc: '原来的首页九宫格 · 可长按拖动排序', go: () => openAllFeats() },
        { name: '账户与外观', desc: '头像 / 壁纸 / 密码 / 同步', go: () => openAccount() },
      ].concat(ME && ME.is_admin
        ? [{ name: '管理后台', desc: '数据 / 质量 / 容量 / 健康', go: () => { location.href = '/admin'; } }]
        : []) },
    ],
  },
];

let tbItems = [];      // 当前标签页展开后的扁平条目，点击时按下标取——省得把函数名塞进 DOM
let tbCur = '';        // 当前标签
let tbChip = {};       // 每个标签各自记着选中的 chip（切走再切回来还在原处）

/* 状态数字（正确率 / 今日新增）。两条原则：
   1) **渲染不等它** —— 拿不到就只是少几个角标，目录该点还能点。导航为几个数字转圈是本末倒置。
   2) **第一次打开标签页才拉** —— 挂在启动时拉，等于给每个只用首页的人白加一个请求。 */
let tbHub = null, tbHubOnce = false;
async function tbLoadHub() {
  if (tbHubOnce) return;
  tbHubOnce = true;
  let d;
  try { d = await api('/api/hub'); } catch (_) { d = { boards: {}, acc: {} }; }
  tbHub = d;
  // 回来时这一屏可能已经不在了（切走了、或者页面整个没了）。补画只是锦上添花，失败就算了。
  try {
    const v = $('#view-tab');
    if (tbCur && v && !v.classList.contains('hidden')) tbFill(tbCur);
  } catch (_) { /* 页面已经不在，不用补画 */ }
}

function tbRow(it) {
  const i = tbItems.push(it) - 1;
  /* 标题**不能用 <b>**：夜间有条全局的 body.dark b{color:#f0c674!important}（正文着重用的金色），
     列表标题套上去会整片变金。应用里其他列表（.bc-name 等）也都是 span，这里跟着来。 */
  return `<div class="board-card tab-row" data-tbi="${i}">
    <span class="tr-text"><span class="tr-n">${esc(it.name)}</span>${it.desc ? `<span class="tr-d">${esc(it.desc)}</span>` : ''}</span>
    ${it.stat ? `<span class="tr-stat ${esc(it.statTone || '')}">${esc(it.stat)}</span>` : ''}
    <span class="bc-arrow">›</span>
  </div>`;
}

// 只重画内容，不动导航栈。切 chip、状态数字回来晚了，都走这儿
function tbFill(key) {
  const def = TAB_DEFS.find(t => t.key === key);
  if (!def || !def.groups) return;
  const chips = def.chips ? def.chips() : [];
  const cur = tbChip[key] || '';
  tbItems = [];
  const groups = def.groups(cur);
  const body = groups.map((g, i) =>
    `<div class="tab-gh" id="tg-${i}">${esc(g.name)}</div><div class="board-grid">${g.items.map(tbRow).join('')}</div>`
  ).join('');
  tbRail(key, groups);
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
  if (!def || !def.groups) return;
  tbCur = key;
  tbLoadHub();                 // 第一次进标签页才去拉状态数字，之后走缓存
  $('#tab-title').textContent = def.name;
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
  const r = e.target.closest('[data-tbi]'); if (!r) return;
  const it = tbItems[+r.dataset.tbi];
  if (it && it.go) it.go();
});

/* 手机的底部标签栏和电脑的左侧导航栏是**同一份 TAB_DEFS 的两个形态**（P3）。
   两边共用一套 data-tb 和同一个点击处理：加一个标签只改 TAB_DEFS，不用两头对。
   谁出现由 CSS 断点决定（≤760 出底栏，≥761 出左栏），JS 不判断屏幕宽度——
   否则浏览器窗口一拖动，两边就对不上了。 */
$('#tabbar').innerHTML = TAB_DEFS.map(t =>
  `<button class="tb" data-tb="${esc(t.key)}">${t.icon}<i>${esc(t.name)}</i></button>`).join('');
$('#siderail').innerHTML = TAB_DEFS.map(t =>
  `<button class="sr-t" data-tb="${esc(t.key)}">${t.icon}<i>${esc(t.name)}</i></button>`
  + `<div class="sr-subs" data-srsub="${esc(t.key)}"></div>`).join('');

/* 左栏是 fixed 的，得知道顶栏有多高才能贴在它下面。**量出来而不是写死 56px**：
   顶栏高度跟字号、安全区都有关，写死的话换个系统字体就会露出一条缝或压掉一截。 */
function tbTopbar() {
  const t = document.querySelector('.topbar');
  if (t && t.offsetHeight) document.body.style.setProperty('--topbar-h', t.offsetHeight + 'px');
}
addEventListener('resize', tbTopbar);
tbTopbar();

function tbNav(e) {
  const b = e.target.closest('[data-tb]'); if (!b) return;
  const key = b.dataset.tb;
  const def = TAB_DEFS.find(t => t.key === key);
  if (def && def.home) { goHome(); return; }
  tbRender(key);
}
$('#tabbar').addEventListener('click', tbNav);
$('#siderail').addEventListener('click', e => {
  // 左栏比底栏多一层：当前标签的分组直接列出来，点了滚过去（电脑上「积累」有五组，
  // 一屏放不下，没有这层就得一路滚着找）
  const g = e.target.closest('[data-srg]');
  if (g) {
    const t = document.getElementById('tg-' + g.dataset.srg);
    if (t) t.scrollIntoView({ block: 'start', behavior: 'smooth' });
    return;
  }
  tbNav(e);
});

// 左栏里「当前标签展开的分组」。只有开着的那个标签有子项，其余收起
function tbRail(key, groups) {
  document.querySelectorAll('#siderail [data-srsub]').forEach(box => {
    const on = box.dataset.srsub === key;
    box.innerHTML = on ? (groups || []).map((g, i) =>
      `<button class="sr-g" data-srg="${i}">${esc(g.name)}</button>`).join('') : '';
    box.classList.toggle('on', on && !!(groups || []).length);
  });
  document.querySelectorAll('#siderail .sr-t').forEach(b =>
    b.classList.toggle('on', b.dataset.tb === key));
}

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
  const t = [...stack].reverse().find(s => s.view === 'tab');
  const cur = (stack.length <= 1 && view === 'home') ? 'today' : (t ? t.tab : '');
  bar.querySelectorAll('[data-tb]').forEach(b => b.classList.toggle('on', b.dataset.tb === cur));
  const rail = $('#siderail');
  if (rail) {
    rail.classList.toggle('hidden', !on);
    rail.querySelectorAll('.sr-t').forEach(b => b.classList.toggle('on', b.dataset.tb === cur));
    // 离开标签页（比如点进了成语积累）就把分组子项收起来：那些锚点已经不指向当前内容了
    if (view !== 'tab') rail.querySelectorAll('[data-srsub]').forEach(x => {
      x.innerHTML = ''; x.classList.remove('on');
    });
  }
};
