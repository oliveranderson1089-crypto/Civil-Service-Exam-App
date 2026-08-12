/* 主题（日间/夜间/跟随系统）+ AI 面板分层返回
 *
 * 由 app.js 按它自己的区段边界切出（原 L8388-8439）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, DL_ART, aiSheetClose, aiSideClose, applyPush, avoidFab, dlArtApply, dlArtAt, dlArtClock,
   dlArtDark, dlArtHue, dlArtKey, dlArtMode, dlIsDesk, esc, loadAiHome, lsGet, lsSet,
   toast */

/* ================= 主题：日间 / 夜间 / 跟随系统 ================= */
const _themeMedia = window.matchMedia ? matchMedia('(prefers-color-scheme: dark)') : null;
/* Android WebView 里 prefers-color-scheme 恒为 light（除非 app 显式开启），
   所以「跟随系统」在 APK 中失灵。原生壳会把系统夜间状态写进 window.__sysDark，优先采信它。 */
function sysIsDark() {
  if (typeof window.__sysDark === 'boolean') return window.__sysDark;
  try {
    if (window.GongkaoNative && typeof GongkaoNative.sysDark === 'function') return !!GongkaoNative.sysDark();
  } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }
  return !!(_themeMedia && _themeMedia.matches);
}
function applyTheme() {
  const mode = lsGet('theme') || 'auto';
  /* 主题风格开着、且「跟随天光」也开着时，日夜由**当前时刻**说了算 ——
     那正是这套主题的卖点，日间/夜间按钮这会儿让位（界面上有一行字说明）。
     没开主题时 dlArtDark() 返回 null，一切照旧。 */
  const byClock = window.dlArtDark ? dlArtDark() : null;
  const dark = byClock !== null ? byClock
    : (mode === 'dark' || (mode === 'auto' && sysIsDark()));
  document.body.classList.toggle('dark', dark);
  document.querySelectorAll('.theme-opt[data-theme]').forEach(b => b.classList.toggle('on', b.dataset.theme === mode));
  const taken = $('#theme-taken');
  if (taken) {
    taken.classList.toggle('hidden', byClock === null);
    // 日夜被接管的**理由**有两种，说错一种人就会一直去点那三个按钮
    const m = window.dlArtMode ? dlArtMode() : '';
    if (byClock !== null) {
      taken.textContent = (m && DL_ART[m].fixed)
        ? `「${DL_ART[m].name}」只有夜色这一档，这三个按钮暂时不起作用。`
        : '「跟随天光」开着，日夜由当前时刻决定，这三个按钮暂时不起作用。';
    }
  }
  // 和 index.html 里那行 <meta ... content="#ffffff"> 是**两段式**，不是打架：
  // 那个白是 JS 跑起来之前的初始值（避免先闪一下蓝），这里是运行时按主题给的真实值，
  // 配合日间蓝顶栏 / 夜间深底。改这里记得连 theme.test.js 那条断言一起看。
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
document.addEventListener('visibilitychange', () => {
  if (document.hidden) return;
  // 回到前台时可能已经跨过了黄昏，主题得先重算，applyTheme 才问得到对的日夜
  if (window.dlArtApply && dlArtMode()) { try { dlArtApply(); } catch (_) { /* 主题是可选项 */ } }
  applyTheme();
});
applyTheme();

/* ================= 主题风格（美术方向）的选择界面 =================
   全部稿子住在 js/daylight.js 的 DL_ART（色表 + 插值 + 上色都在那儿，
   因为它得在第一帧就位）。这里只管**设置页里怎么选**。

   **一次只列出这一端的那几套**：手机端是竖构图大色块，电脑端是横构图细边框，
   互相搬过去都不成立，所以两端各列各的、各记各的（键名见 dlArtKey）。
   列出对面那几套的代价不是"多几个格子"，而是选了之后没有 CSS 接住它。
   套数别写死在文案里：加一套主题只该改 DL_ART 一处（这句原先写着"四套"，
   加到九套之后还在那儿说四套）。

   预览格不写死颜色，现从 DL_ART 白昼那一档取：光靠名字选不出来，
   而「宣纸与印」「墨山」这几个名字谁也不知道长什么样。 */
function artRenderPicker() {
  const grid = $('#art-grid');
  if (!grid || !window.DL_ART) return;
  const cur = dlArtMode();
  const desk = window.dlIsDesk ? dlIsDesk() : true;
  const keys = Object.keys(DL_ART).filter(k => !!DL_ART[k].desk === desk);
  const hint = $('#art-scope-hint');
  if (hint) {
    hint.textContent = '给整个界面换一套美术方向：模块面、图标和壁纸一起变。不选就是现在的样子。'
      + (desk ? `这 ${keys.length} 套是电脑端专用的，手机上另有一套清单。`
        : `这 ${keys.length} 套是手机端的，电脑上另有一套清单。`);
  }
  const cell = (key, name, sw) =>
    `<button class="art-opt${key === cur ? ' on' : ''}" data-art="${key}" aria-pressed="${key === cur}">
      <span class="art-sw" style="${sw.bg}">${sw.dots}</span>
      <span class="art-nm">${esc(name)}</span>
    </button>`;
  // 默认那一格：就画现在这套图标的三个颜色，让"不开主题"也是一个看得见的选项
  let html = cell('', '默认', {
    bg: 'background:linear-gradient(178deg,#f6f7f9,#eef1f5)',
    dots: '<i style="background:#e0930c"></i><i style="background:#1a6fb5"></i><i style="background:#1f7a6a"></i>',
  });
  keys.forEach(key => {
    const T = DL_ART[key];
    const v = dlArtAt(key, 13);                 // 一律用白昼那一档做预览，四格之间才可比
    let bg, dots;
    if (key === 'celadon') {
      // 釉底 + 釉青印、纸卡、墨：这三点就是"有色壁纸、无色正文"那句话的缩影
      bg = `background:linear-gradient(178deg,${v.wall[0]},${v.wall[2]})`;
      dots = [`background:linear-gradient(150deg,${v.seal[0]},${v.seal[1]})`,
        `background:${v.card};box-shadow:inset 0 0 0 1px ${v.line}`,
        `background:${v.text}`].map(s => `<i style="${s}"></i>`).join('');
    } else if (key === 'dossier') {
      // 牛皮底 + 墨绿封条、朱印、纸页。朱那一点是这一稿的记号
      bg = `background:linear-gradient(178deg,${v.wall[0]},${v.wall[2]})`;
      dots = [`background:${v.band}`, `background:${v.seal}`,
        `background:${v.card};box-shadow:inset 0 0 0 1px ${v.line}`]
        .map(s => `<i style="${s}"></i>`).join('');
    } else if (key === 'night') {
      // 近黑底 + 青蓝、卡片、灯晕。灯那一点只在启动屏出现，预览里留着是为了认出这一稿
      bg = `background:linear-gradient(178deg,${v.wall[0]},${v.wall[2]})`;
      dots = [`background:${v.blue}`, `background:${v.card};box-shadow:inset 0 0 0 1px ${v.line}`,
        `background:${v.lamp}`].map(s => `<i style="${s}"></i>`).join('');
    } else if (key === 'studio') {
      // 白底 + 品牌蓝、线、墨。三个方块之间几乎没有颜色 —— 那正是这一稿要说的
      bg = `background:linear-gradient(178deg,${v.wall[0]},${v.wall[2]})`;
      dots = [`background:${v.blue}`, `background:${v.rule}`, `background:${v.text}`]
        .map(s => `<i style="${s}"></i>`).join('');
    } else if (T.art2) {
      /* 第二代十套：底色 + 图标底 + 强调 + 插画的第二支色。
         最后那一点是这一格的记号 —— 十套之间底色相近的有好几对（两套纸、两套暖黄），
         真正一眼分得开的是朱 / 紫 / 桃 / 金 / 番茄那一点。 */
      bg = `background:linear-gradient(178deg,${v.wall[0]},${v.wall[2]})`;
      dots = [`background:linear-gradient(155deg,${v.tile[0]},${v.tile[1]});box-shadow:inset 0 0 0 1px ${v.line}`,
        `background:${v.blue}`, `background:${v.il2}`]
        .map(s => `<i style="${s}"></i>`).join('');
    } else if (key === 'paper') {
      bg = `background:linear-gradient(178deg,${v.wall[0]},${v.wall[2]})`;
      // 三张纸都是米白的，光看方块认不出这是哪一稿；那枚朱印才是它的记号
      dots = [0, 1, 2].map(i => `<i style="background:linear-gradient(155deg,${v.tile[0]},${v.tile[1]});box-shadow:inset 0 0 0 1px rgba(128,128,128,.28)${i === 2 ? `,inset -4px -4px 0 -2.4px ${v.seal}` : ''}"></i>`).join('');
    } else if (key === 'glass') {
      bg = `background:linear-gradient(178deg,${v.sky[0]},${v.sky[2]})`;
      dots = [0, 1, 2].map(() => `<i style="background:rgba(255,255,255,${v.ga.toFixed(2)});box-shadow:inset 0 0 0 1px rgba(255,255,255,${v.gb.toFixed(2)})"></i>`).join('');
    } else if (key === 'ink') {
      bg = `background:linear-gradient(178deg,${v.bg},${v.card})`;
      dots = [0, 1, 2].map(() => `<i style="background:${v.blk}"></i>`).join('');
    } else {
      bg = `background:linear-gradient(178deg,${v.wall[0]},${v.wall[2]})`;
      /* 挑 缃 / 藕荷 / 赭。原来挑的是 缃/靛/竹青 —— 那正好是现在这套橙蓝绿的近亲，
         预览格和「默认」那一格看着一模一样，等于没给人可选的信息。 */
      dots = [0, 2, 5].map(i => `<i style="background:${dlArtHue(v, i)}"></i>`).join('');
    }
    html += cell(key, T.name, { bg, dots });
  });
  grid.innerHTML = html;
  artRenderClock();
}
function artRenderClock() {
  const row = $('#art-clock-row');
  if (!row) return;
  const on = dlArtMode();
  /* 没选主题时这一行没有意义；只有一档的主题（夜航）也一样 ——
     它本来就是夜色，"跟随天光"对它是个空开关，摆在那儿只会让人以为自己没设对。 */
  const fixed = !!(on && DL_ART[on].fixed);
  row.classList.toggle('hidden', !on || fixed);
  const clk = dlArtClock();
  document.querySelectorAll('[data-artclk]').forEach(b =>
    b.classList.toggle('on', (b.dataset.artclk === '1') === clk));
  const hint = $('#art-clock-hint');
  if (hint) {
    hint.textContent = clk
      ? '界面跟着一天的时刻连续变色，日夜也自动切换 —— 和启动图标是同一条曲线。'
      : '主题固定成一套配色，日夜仍由上面的「外观」决定。';
  }
}
document.addEventListener('click', e => {
  const a = e.target.closest('[data-art]');
  if (a) {
    lsSet(window.dlArtKey ? dlArtKey() : 'artTheme', a.dataset.art);   // 电脑/手机各记各的
    dlArtApply(); applyTheme(); artRenderPicker();
    toast(a.dataset.art ? (DL_ART[a.dataset.art].name + ' 已应用') : '已回到默认外观');
    return;
  }
  const c = e.target.closest('[data-artclk]');
  if (c) {
    lsSet('artClock', c.dataset.artclk);
    dlArtApply(); applyTheme(); artRenderClock();
    toast(c.dataset.artclk === '1' ? '跟随天光' : '已固定');
  }
});
artRenderPicker();

/* ================= AI 面板的返回键 =================
   改版后 AI 只剩两层：会话抽屉开着 → 先收抽屉；否则关面板。
   （旧版有首页/项目/项目详情/会话四层，返回要一层层退 —— 那四个视图已经并成一栏了。） */
function aiBack() {
  if ($('#ai-panel').classList.contains('hidden')) return false;
  if ($('#ai-panel').classList.contains('side-on')) { aiSideClose(); return true; }
  if (!$('#ai-sheet').classList.contains('hidden')) { aiSheetClose(); return true; }
  $('#ai-panel').classList.add('hidden');
  /* 关面板必须顺手收 body 上的 pad-full / --push-*：全屏停靠时它给 body 挂了 pad-full，
     而那条类会把悬浮球 display:none。这条**返回键**路径原先只藏面板不收类，
     于是用返回退出全屏 AI 之后，悬浮球就一直不见了，只能重开应用。 */
  if (window.applyPush) applyPush();
  if (window.avoidFab) avoidFab();
  return true;
}
