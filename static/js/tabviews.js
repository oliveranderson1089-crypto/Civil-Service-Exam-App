/* 「库」和「我的」两个标签页的首屏（界面重构 P4）
 *
 * 这两页原来和别的标签页一样，是一列「标题 + 一句说明」的目录条。
 * 问题是它们的条目**天天点**（小记、云盘、任务清单…），说明文字看第二遍就是噪音，
 * 而一屏只摆得下五六条：库那页第一屏全被说明占满，最近改过的东西一个也看不见。
 *
 * 所以这两页换了形态，别的标签页不动：
 *   库   = 六个图标格（一屏摆得下全部容器）+ 最近打开（真正的入口，不用先想东西存在哪）
 *   我的 = 本周完成度环 + 一行一件的紧凑清单（数字和角标才是这页的内容）
 *
 * 数据各一个聚合接口（mods/tabhome.py），和首页仪表盘一个路子。
 * 20 秒内切回来不重拉：标签之间来回切很频繁，每次都打接口等于把接口打穿。
 *
 * 渲染分两拍：先出骨架（图标格/清单是写死的，不该等接口），数字和列表回来再补。
 * **接口挂了也要能点** —— 库的六个格子、我的九个入口都是纯导航，
 * 为几个数字把整页显示成「加载失败」是本末倒置。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 */
/* global $, ME, api, artIcon, esc, push, tbBadge, tbIsCur, tbItem, tbReset,
   openAccount, openAllFeats, openChat, openCkBoard, openClassicDetail, openDoc,
   openDraft, openDrafts, openDrive, openExam, openFanwen, openIdiom, openKb,
   openMaterials, openNews, openNotes, openNotify, openPlanLog, openReview,
   openTasks, openVideos */

/* 图标是描边的（方案 A）：浅色方块打底、1.7px 的线。
   也做过实色方块 + 白图形那一路（更响、小尺寸更清楚），但那套的重量和这个应用
   通篇的浅色调不搭 —— 六个彩色方块摆在一屏浅灰上，比内容还抢眼。 */
const TV_SVG = (p) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const TV_TTL = 20000;             // 20 秒内切回来用缓存

/* ================= 库 ================= */

// 六个容器。count 是接口回来后填的，key 和 mods/tabhome.py 的 counts 对齐
const LB_TILES = [
  { k: 'note', name: '小记', tone: 'amber', go: () => openNotes(),
    icon: TV_SVG('<path d="M20.2 12.2a6 6 0 0 0-8.5-8.5L5 10.5V19h8.5z"/><line x1="16" y1="8" x2="2" y2="22"/>') },
  { k: 'kb', name: '知识库', tone: 'blue', go: () => openKb(),
    icon: TV_SVG('<path d="M4 19.2A2.3 2.3 0 0 1 6.3 17H20"/><path d="M6.3 2.5H20v19H6.3A2.3 2.3 0 0 1 4 19.2V4.8a2.3 2.3 0 0 1 2.3-2.3z"/>') },
  { k: 'draft', name: '草稿本', tone: 'violet', go: () => openDrafts(),
    icon: TV_SVG('<path d="M11 4H4v16h16v-7"/><path d="M18.5 2.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4z"/>') },
  { k: 'material', name: '资料库', tone: 'teal', go: () => openMaterials(),
    icon: TV_SVG('<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>') },
  { k: 'drive', name: '云盘', tone: 'sky', go: () => openDrive(),
    icon: TV_SVG('<path d="M6.5 19a4.5 4.5 0 0 1-.4-9A6.5 6.5 0 0 1 18.4 9.6 3.7 3.7 0 0 1 17.8 19z"/>') },
  { k: 'star', name: '收藏', tone: 'gold', go: () => openStars(),
    icon: TV_SVG('<polygon points="12 3.5 14.6 9 20.5 9.8 16.2 13.9 17.3 19.8 12 17 6.7 19.8 7.8 13.9 3.5 9.8 9.4 9"/>') },
];

/* 同一批形状的线描版，只给「宣纸与印」主题用（js/daylight.js 的 DL_ART.paper）。
   实色块在纸底上是块墨疙瘩，那一稿的语言是墨线。

   两套字形**都进 DOM**，由 CSS 决定露哪一套（body.art-paper .lb-g/.lb-gl）。
   换主题时不用重渲染，也就不用让主题去牵动「库」那一页的加载状态。
   1.9px 而不是 1.7px：44px 的格子上更细的线会发虚 —— 当初把这些图标从线性
   换成实色块，就是栽在这儿。 */
const TV_LINE = (p) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const LB_LINE = {
  note: TV_LINE(`<path d="M5.2 5.4A2.2 2.2 0 0 1 7.4 3.2h6l5.4 5.4v10a2.2 2.2 0 0 1-2.2 2.2H7.4a2.2 2.2 0 0 1-2.2-2.2z"/>
    <path d="M13.4 3.4v4.4a1 1 0 0 0 1 1h4.4"/><path d="M8.4 13.4h7.2M8.4 16.6h4.6"/>`),
  kb: TV_LINE(`<path d="M6.8 3.6H18.6v16.8H6.8A2.3 2.3 0 0 1 4.5 18.1V5.9a2.3 2.3 0 0 1 2.3-2.3z"/>
    <path d="M9.2 3.6v16.8"/><path d="M11.8 8.2h4.4M11.8 11.6h3"/>`),
  draft: TV_LINE(`<path d="M4 17.5 15.1 6.4l2.6 2.6L6.6 20.1l-3.4.8z"/>
    <path d="M15.1 6.4 17.3 4.2a1.85 1.85 0 0 1 2.6 2.6l-2.2 2.2"/>`),
  material: TV_LINE(`<path d="M3.6 6.8a2 2 0 0 1 2-2h3.4l2.2 2.8h7.4a2 2 0 0 1 2 2v8.4a2 2 0 0 1-2 2H5.6a2 2 0 0 1-2-2z"/>`),
  drive: TV_LINE(`<path d="M7 19.4a4.4 4.4 0 0 1-.5-8.8 6.4 6.4 0 0 1 12.1-1.3 3.7 3.7 0 0 1-1 10.1z"/>
    <path d="M12 16.4v-5.6M9.7 13.1 12 10.8l2.3 2.3"/>`),
  star: TV_LINE(`<path d="M12 3.4 14.7 8.9l6.1.9-4.4 4.3 1 6.1L12 17.3l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>`),
};

// 「最近打开」里每条点了去哪。知识库文档和草稿能直接开到那一篇，
// 小记/资料库/云盘只能开到列表 —— 它们没有单条的独立视图，硬跳会落到一个空壳上。
const LB_OPEN = {
  note: () => openNotes(),
  kbdoc: (id) => openDoc(id),
  draft: (id) => openDraft(id),
  material: () => openMaterials(),
  drive: () => openDrive(),
};

let lbData = null, lbAt = 0;

/* 骨架：占位块和真内容**同高同位**，数据回来就地替换，页面一格不跳。
   原来这里是一块灰底「加载中…」——它比真列表矮一大截，数据一到整页往下窜一截，
   人眼看到的就是"闪一下"。骨架不是装饰，是把这一跳消掉。 */
const TV_SK = (w, cls) => `<span class="tv-sk${cls ? ' ' + cls : ''}"${w ? ` style="width:${w}"` : ''}></span>`;

function lbTiles() {
  return `<div class="lb-grid">` + LB_TILES.map(t => {
    const n = lbData && lbData.counts ? lbData.counts[t.k] : null;
    return `<button class="lb-tile" data-tbi="${tbItem(t)}">
      <span class="lb-ic lb-${t.tone}"><span class="lb-g">${window.artIcon ? artIcon(t.k, t.icon) : t.icon}</span><span class="lb-gl">${LB_LINE[t.k]}</span></span>
      <span class="lb-n">${esc(t.name)}</span>
      <span class="lb-c">${lbData ? (n == null ? '' : n + ' 条') : TV_SK('34px', 'sk-c')}</span>
    </button>`;
  }).join('') + '</div>';
}

function lbRecent() {
  // 摆三条：比一条更像"一张列表"，又不至于数据只有一条时塌一大截
  if (!lbData) {
    return `<div class="tab-gh">最近打开</div><div class="tv-rows">`
      + ['56%', '38%', '48%'].map(w =>
        `<div class="tv-row">${TV_SK('', 'sk-dot')}${TV_SK(w)}${TV_SK('', 'sk-tag')}</div>`).join('')
      + '</div>';
  }
  const its = lbData.recent || [];
  if (!its.length) {
    // 空就说空。摆几条假数据或者干脆把这一段藏掉，都会让人以为「库是空的」这件事没发生
    return `<div class="tab-gh">最近打开</div>
      <div class="tv-empty">库里还没有东西。写条小记、传个文件，这里就会记着。</div>`;
  }
  return `<div class="tab-gh">最近打开</div><div class="tv-rows">` + its.map(it => {
    const go = LB_OPEN[it.kind];
    const i = tbItem({ go: () => (go ? go(it.id) : null) });
    return `<div class="tv-row" data-tbi="${i}">
      <span class="td-dot"></span>
      <span class="tv-name">${esc(it.title)}</span>
      <span class="tv-tag">${esc(it.label)}</span>
    </div>`;
  }).join('') + '</div>';
}

function lbPaint() {
  tbReset();
  $('#tab-groups').innerHTML = lbTiles() + lbRecent();
}

async function lbView() {
  lbPaint();                       // 图标格不等接口：它是这一页的主体，而且内容是写死的
  if (lbData && Date.now() - lbAt < TV_TTL) return;
  try {
    lbData = await api('/api/lib/home');
    lbAt = Date.now();
  } catch (_) {
    lbData = { counts: {}, recent: [] };   // 数字没了照样能进各个库
  }
  // 回来晚了这一屏可能已经切走（或者页面整个没了），别画到别人身上
  try { if (window.tbIsCur && tbIsCur('lib')) lbPaint(); } catch (_) { /* 页面已经不在 */ }
}

/* ---- 收藏夹：六个模块的星标并成一张单子（mods/tabhome.py 的 /api/lib/stars） ---- */
// 每类收藏点了去哪。ck_stars 存的是板块名，其余存的是那条内容的 id
const ST_OPEN = {
  ck: (ref) => openCkBoard(ref || '收藏'),
  entry: () => openIdiom(),
  classic: (ref) => openClassicDetail(+ref),
  fanwen: () => openFanwen(),
  news: () => openNews(),
  video: () => openVideos(),
};
let stItems = [], stKind = '';

function openStars() {
  push({ view: 'stars', title: '收藏' });
  $('#st-list').innerHTML = `<div class="tv-rows">`
    + ['52%', '64%', '40%', '58%'].map(w =>
      `<div class="tv-row">${TV_SK('', 'sk-dot')}${TV_SK(w)}${TV_SK('', 'sk-tag')}</div>`).join('')
    + '</div>';
  $('#st-chips').innerHTML = '';
  loadStars();
}

async function loadStars() {
  try {
    stItems = (await api('/api/lib/stars')).items || [];
  } catch (e) {
    $('#st-list').innerHTML = `<p class="empty">${esc(e.message || '加载失败')}</p>`;
    return;
  }
  stKind = '';
  stPaint();
}

function stPaint() {
  // 筛选条只列**真有收藏的**类别：六个类别全摆出来，点进去大半是空的
  const kinds = [];
  stItems.forEach(it => { if (!kinds.some(k => k.k === it.kind)) kinds.push({ k: it.kind, name: it.label }); });
  $('#st-chips').innerHTML = kinds.length > 1
    ? [{ k: '', name: '全部' }].concat(kinds).map(c =>
      `<button class="chip${c.k === stKind ? ' active' : ''}" data-stc="${esc(c.k)}">${esc(c.name)}</button>`).join('')
    : '';
  const its = stItems.filter(it => !stKind || it.kind === stKind);
  $('#st-list').innerHTML = its.length
    ? `<div class="tv-rows">` + its.map((it, i) => `
      <div class="tv-row" data-sti="${i}">
        <span class="td-dot"></span>
        <span class="tv-text"><span class="tv-name">${esc(it.title)}</span>
          ${it.sub ? `<span class="tv-sub">${esc(it.sub)}</span>` : ''}</span>
        <span class="tv-tag">${esc(it.label)}</span>
      </div>`).join('') + '</div>'
    : '<p class="empty">还没有收藏。读到有用的点一下 ☆，都会收在这儿。</p>';
}

$('#st-chips').addEventListener('click', e => {
  const c = e.target.closest('[data-stc]'); if (!c) return;
  stKind = c.dataset.stc; stPaint();
});
$('#st-list').addEventListener('click', e => {
  const r = e.target.closest('[data-sti]'); if (!r) return;
  const it = stItems.filter(x => !stKind || x.kind === stKind)[+r.dataset.sti];
  const go = it && ST_OPEN[it.kind];
  if (go) go(it.ref);
});

/* ================= 我的 ================= */

let meData = null, meAt = 0;

function meHero() {
  if (!meData) {
    // 环和三行字的位置都占住：这张卡有 96px 高，缺了它下面九个入口会整体上移再落回来
    // sk-col：这一列平时是被文字撑开的，骨架里没有文字，不给 flex:1 就是 0 宽（百分比宽度全塌）
    return `<div class="td-hero">${TV_SK('', 'sk-ring')}
      <div class="td-hero-t sk-col">${TV_SK('60%')}${TV_SK('45%', 'sk-v')}${TV_SK('70%')}</div></div>`;
  }
  const w = meData.week;
  const ring = w && w.pct != null
    ? `<div class="td-ring" style="--p:${w.pct}"><i>${w.pct}%</i></div>`
    : `<div class="td-ring td-ring-off"><i>—</i></div>`;
  // 没排计划就说没排。这里糊一个 0% 或者拿任务清单凑个数，等于每周给自己发一张假成绩单
  const k1 = w && w.pct != null ? `本周计划完成度 ${w.done} / ${w.total} 项` : '本周还没有计划';
  const v = `${meData.questions} 题 · ${meData.minutes} 分钟`;
  const st = meData.study;
  const k2 = !st ? '' : (st.streak > 0
    ? `连续学习 <b>${st.streak}</b> 天 · 累计 ${st.total} 天`
    : '今天学一点，连续天数就从 1 开始');
  return `<div class="td-hero" data-tbi="${tbItem({ go: () => openPlanLog() })}">
    ${ring}
    <div class="td-hero-t">
      <div class="td-hero-k">${esc(k1)}</div>
      <div class="td-hero-v">${esc(v)}</div>
      <div class="td-hero-k">${k2}</div>
    </div>
  </div>`;
}

// 我的：一行一件。原来的四个分组一个不少，只是说明文字换成了右边的数字/角标
function meGroups() {
  const d = meData || {};
  const t = d.tasks || {};
  const un = d.unread || {};
  const rv = (window.tbBadge && tbBadge.review) || 0;
  return [
    { name: '学习安排', items: [
      { name: '任务清单', go: () => openTasks(),
        tag: t.total ? `${t.done}/${t.total}` : '', dot: t.total && t.done >= t.total ? 'g' : 'b' },
      { name: '计划记录', go: () => openPlanLog(), dot: 'b' },
      { name: '今日复习', go: () => openReview(), badge: rv, dot: rv ? 'r' : 'b' },
    ] },
    { name: '资讯', items: [
      { name: '全国考情', go: () => openExam(), tag: '公告汇总', dot: 'b' },
    ] },
    { name: '消息与好友', items: [
      { name: '聊天', go: () => openChat(), badge: un.chat || 0, dot: un.chat ? 'r' : 'b' },
      { name: '消息', go: () => openNotify(), badge: un.notify || 0, dot: un.notify ? 'r' : 'b' },
    ] },
    { name: '设置', items: [
      { name: '全部功能', go: () => openAllFeats(), dot: 'b' },
      { name: '账户与外观', go: () => openAccount(), dot: 'b' },
    ].concat(ME && ME.is_admin
      ? [{ name: '管理后台', go: () => { location.href = '/admin'; }, dot: 'b' }]
      : []) },
  ].map(g => `<div class="tab-gh">${esc(g.name)}</div><div class="tv-rows">` + g.items.map(it => `
    <div class="tv-row" data-tbi="${tbItem(it)}">
      <span class="td-dot td-${it.dot}"></span>
      <span class="tv-name">${esc(it.name)}</span>
      ${it.badge ? `<span class="td-badge">${it.badge > 99 ? '99+' : it.badge}</span>` : ''}
      ${it.tag ? `<span class="tv-tag">${esc(it.tag)}</span>` : ''}
    </div>`).join('') + '</div>').join('');
}

function mePaint() {
  tbReset();
  $('#tab-groups').innerHTML = meHero() + meGroups();
}

async function meView() {
  mePaint();
  if (meData && Date.now() - meAt < TV_TTL) return;
  try {
    meData = await api('/api/me/home');
    meAt = Date.now();
  } catch (_) {
    // 给一个空壳而不是 null：meHero 拿 null 会一直画骨架屏（那是「还在加载」的意思），
    // 拉不到时该画灰环 + 九个照常能点的入口，跟 lbView 的兜底一致
    meData = { week: null, tasks: {}, unread: {}, questions: 0, minutes: 0, study: null };
  }
  try { if (window.tbIsCur && tbIsCur('me')) mePaint(); } catch (_) { /* 页面已经不在 */ }
}

window.lbView = lbView;
window.meView = meView;
window.openStars = openStars;
