/* 日光：启动屏和标签页图标跟着一天的时刻连续变（美术稿 v2）
 *
 * 不是「早上一张、晚上一张」两态切换 —— 那样下午三点该长什么样是没定义的。
 * 这里定六个锚点（黎明/晨光/白昼/黄昏/暮色/夜），任意时刻在相邻两个之间插值，
 * **跨零点也连续**（23:00 和次日 05:00 首尾相接）。
 *
 * 同一份色表还喂着另外两处，改这里要一起改：
 *   · gen_appicon.py 的 PHASES —— 桌面/安卓的图标 PNG（六个时段各导一张）
 *   · desktop/gongkao_native.py 的 _phase() —— 桌面版启动时挑哪张图标
 *
 * 本文件**排在 index.html 所有脚本的最前面**，紧跟在 #splash 那段 DOM 后面：
 * 启动屏必须在第一帧就是对的颜色，晚一拍就是肉眼可见的闪一下。
 * 所以它不许依赖 core.js 的任何东西（$ / api / esc 都还不存在），只用原生 DOM。
 */

/* 六个锚点。sky 是天光的三段渐变；grid/bloom/stars/hill/trail 是五层各自的透明度；
   icon 是桌面图标的底色；rim 是底色暗下去之后要补的一圈内描边 —— 没有它，
   墨底图标压在黑壁纸上就没有边了（19px 时整块糊掉）。 */
const DL_KEYS = [
  { h: 5.0, name: '黎明', sky: ['#16223a', '#33405e', '#8a6a70'], ink: '#e8ecf4', sub: 'rgba(232,236,244,.6)',
    dot: '#8fb8e0', grid: 0, bloom: 0.55, stars: 0.55, hill: 0.5, trail: 0.35,
    seal: ['#4d86c8', '#22548c'],
    icon: ['#2a3346', '#1a2438'], grain: 0.3, rim: 1 },
  { h: 8.0, name: '晨光', sky: ['#fff4e0', '#fdf3e6', '#e8f0f8'], ink: '#20303f', sub: '#7c848f',
    dot: '#1a6fb5', grid: 1, bloom: 1, stars: 0, hill: 0, trail: 0,
    seal: ['#35a3e2', '#1a6fb5'],
    icon: ['#fdfaf3', '#f0e8d8'], grain: 0.55, rim: 0 },
  { h: 13.0, name: '白昼', sky: ['#f8fbff', '#eef4fb', '#e2ecf7'], ink: '#22323f', sub: '#7b838e',
    dot: '#1a6fb5', grid: 0.72, bloom: 0.32, stars: 0, hill: 0, trail: 0,
    seal: ['#2b8fd6', '#1668ad'],
    icon: ['#fffdf7', '#f3ece0'], grain: 0.42, rim: 0 },
  { h: 18.0, name: '黄昏', sky: ['#ffd9a8', '#f3b487', '#b98fa8'], ink: '#3a2c2c', sub: 'rgba(58,44,44,.62)',
    dot: '#a8582f', grid: 0.32, bloom: 0.9, stars: 0, hill: 0.35, trail: 0,
    seal: ['#3f9ccb', '#1d6390'],
    icon: ['#f6d9b4', '#c98f6e'], grain: 0.5, rim: 0.15 },
  { h: 20.5, name: '暮色', sky: ['#3b4a6b', '#27364f', '#1b2b47'], ink: '#e6ecf6', sub: 'rgba(230,236,246,.6)',
    dot: '#9ec4e8', grid: 0.1, bloom: 0.3, stars: 0.45, hill: 0.75, trail: 0.5,
    seal: ['#3f8ac9', '#1b5388'],
    icon: ['#4a4a5e', '#2a3348'], grain: 0.4, rim: 0.7 },
  { h: 23.0, name: '夜', sky: ['#0e1d33', '#14304f', '#0c1c30'], ink: '#e9f0f8', sub: 'rgba(225,236,248,.6)',
    dot: '#7fb6e8', grid: 0, bloom: 0, stars: 1, hill: 0.5, trail: 1,
    seal: ['#3d8fd4', '#17548f'],
    icon: ['#1c2a44', '#121c2e'], grain: 0.32, rim: 1 },
];

/* 三位写法（#fff）要先展开成六位。不展开的话 slice(5,7) 拿到的是空串，
   parseInt('') 是 NaN，拼出来的 rgb(255,255,NaN) 是非法值 —— 浏览器把**整条声明**
   静默丢掉，表现就是那一层什么都没有、还不报错。
   （色表里目前全是六位写法，但谁哪天顺手写个 #fff 就会踩上。） */
function dlHex(h) {
  const s = h.length < 7 ? '#' + h.slice(1).split('').map(c => c + c).join('') : h;
  return [parseInt(s.slice(1, 3), 16), parseInt(s.slice(3, 5), 16), parseInt(s.slice(5, 7), 16)];
}
function dlMix(a, b, t) {
  const x = dlHex(a), y = dlHex(b);
  return 'rgb(' + x.map((v, i) => Math.round(v + (y[i] - v) * t)).join(',') + ')';
}
const dlNum = (a, b, t) => a + (b - a) * t;
// 给插值出来的 rgb(...) 加透明度。**不能**在后面接十六进制（rgb(...)47 是非法的，
// 整条声明会被丢掉 —— 表现就是投影不见了，还不报错）
const dlRgba = (c, a) => c.replace('rgb(', 'rgba(').replace(')', ',' + a + ')');

/* 取任意时刻的一整套值。跨零点是这里唯一的坑：23:00 之后要接回 05:00，
   所以最后一个锚点的下一个是第一个，跨度按 +24 算，别写成 b.h - a.h（会是负的）。 */
function dlAt(h) {
  h = ((h % 24) + 24) % 24;
  let i = DL_KEYS.length - 1;
  for (let k = 0; k < DL_KEYS.length; k++) if (h >= DL_KEYS[k].h) i = k;
  const a = DL_KEYS[i], b = DL_KEYS[(i + 1) % DL_KEYS.length];
  const span = ((b.h - a.h) + 24) % 24 || 24;
  const t = Math.min(1, Math.max(0, (((h - a.h) + 24) % 24) / span));
  return {
    name: (t < 0.66 ? a : b).name,
    sky: [0, 1, 2].map(k => dlMix(a.sky[k], b.sky[k], t)),
    ink: t < 0.5 ? a.ink : b.ink,
    sub: t < 0.5 ? a.sub : b.sub,
    dot: dlMix(a.dot, b.dot, t),
    grid: dlNum(a.grid, b.grid, t), bloom: dlNum(a.bloom, b.bloom, t),
    stars: dlNum(a.stars, b.stars, t), hill: dlNum(a.hill, b.hill, t),
    trail: dlNum(a.trail, b.trail, t), grain: dlNum(a.grain, b.grain, t),
    rim: dlNum(a.rim, b.rim, t),
    icon: [dlMix(a.icon[0], b.icon[0], t), dlMix(a.icon[1], b.icon[1], t)],
    seal: [dlMix(a.seal[0], b.seal[0], t), dlMix(a.seal[1], b.seal[1], t)],
  };
}
function dlNow() { const d = new Date(); return d.getHours() + d.getMinutes() / 60; }

// 星子和那串光点的位置写死在这儿（不是随机的）：随机的话每次启动位置都在跳，
// 而启动屏是每天见几十次的东西，位置一变就显得"闪"。
const DL_STARS = `radial-gradient(1.1px 1.1px at 22% 12%,#fff,transparent),
  radial-gradient(1px 1px at 68% 8%,rgba(255,255,255,.8),transparent),
  radial-gradient(1.5px 1.5px at 42% 19%,rgba(255,255,255,.85),transparent),
  radial-gradient(1px 1px at 84% 23%,rgba(255,255,255,.7),transparent),
  radial-gradient(1.2px 1.2px at 12% 31%,rgba(255,255,255,.55),transparent),
  radial-gradient(1px 1px at 58% 27%,rgba(255,255,255,.5),transparent)`;
const DL_TRAIL = `radial-gradient(3.4px 3.4px at 32% 92%,rgba(130,185,240,.5),transparent),
  radial-gradient(3.6px 3.6px at 38% 76%,rgba(140,192,244,.6),transparent),
  radial-gradient(3.8px 3.8px at 43% 60%,rgba(155,203,248,.7),transparent),
  radial-gradient(4px 4px at 47% 44%,rgba(175,214,250,.8),transparent),
  radial-gradient(4.4px 4.4px at 49% 28%,rgba(240,206,130,.85),transparent),
  radial-gradient(5px 5px at 50% 12%,rgba(240,180,60,.95),transparent)`;

/* 纸感噪点：画一小块 64×64 平铺，**不能用整屏的 SVG feTurbulence** ——
   手机上 390px 宽没事，桌面窗口 1690×1200 就是两百多万像素的分形噪声，
   WebKitGTK 在软件渲染下直接卡住（画面停在最后一帧，看着就是"进不去主页"）。
   一块 4096 像素的噪点画一次、平铺开，代价可以忽略。 */
let dlGrainUrl = null;
function dlGrain() {
  if (dlGrainUrl !== null) return dlGrainUrl;       // 只画一次，之后复用
  dlGrainUrl = '';
  try {
    const N = 64, c = document.createElement('canvas');
    c.width = c.height = N;
    const g = c.getContext && c.getContext('2d');
    if (!g) return dlGrainUrl;
    const im = g.createImageData(N, N);
    for (let i = 0; i < im.data.length; i += 4) {
      const v = 110 + Math.random() * 70;
      im.data[i] = im.data[i + 1] = im.data[i + 2] = v;
      im.data[i + 3] = 255;
    }
    g.putImageData(im, 0, 0);
    dlGrainUrl = 'url(' + c.toDataURL('image/png') + ')';
  } catch (_) { dlGrainUrl = ''; }                  // 没有 canvas 就没纸感，不影响别的
  return dlGrainUrl;
}

function dlPaintSplash(h) {
  const sp = document.getElementById('splash');
  if (!sp) return null;                       // 已经淡出撤掉了，或者这一页没有启动屏
  const v = dlAt(h == null ? dlNow() : h);
  /* 逐属性赋值，**不要用 cssText**：整条里只要有一处解析不了（比如带换行的
     background 简写），有的实现会把这一条**整个**丢掉 —— 表现就是那一层的
     浓淡不跟着时刻走，还不报错。位置和尺寸都在 CSS 里，这里只给"画什么"和"多浓"。 */
  const set = (id, op, bg) => {
    const e = document.getElementById(id);
    if (!e) return;
    e.style.opacity = op;
    if (bg) e.style.backgroundImage = bg;
  };
  sp.style.backgroundImage = `linear-gradient(180deg,${v.sky[0]} 0%,${v.sky[1]} 52%,${v.sky[2]} 100%)`;
  sp.style.color = v.ink;
  set('sp-grid', v.grid,
    'repeating-linear-gradient(0deg,rgba(26,111,181,.055) 0 1px,transparent 1px 26px),'
    + 'repeating-linear-gradient(90deg,rgba(26,111,181,.055) 0 1px,transparent 1px 26px)');
  set('sp-bloom', v.bloom,
    'radial-gradient(85% 30% at 50% 2%,rgba(252,190,96,.5),transparent 64%),'
    + 'radial-gradient(52% 16% at 50% 3%,rgba(255,232,180,.7),transparent 70%)');
  set('sp-stars', v.stars, DL_STARS);
  set('sp-hill', v.hill);
  set('sp-trail', v.trail, DL_TRAIL);      // 只占下半屏，位置在 CSS 里（爬到中间会压住引言）
  set('sp-grain', v.grain * 0.5, dlGrain() || undefined);
  const lg = sp.querySelector('.sp-logo');
  if (lg) {
    lg.style.backgroundImage = `linear-gradient(150deg,${v.seal[0]},${v.seal[1]} 70%)`;
    // 投影用方章自己的深色：写死一个蓝影子，夜里会像浮在半空
    lg.style.boxShadow = `0 10px 30px ${dlRgba(v.seal[1], 0.32)},inset 0 1px 0 rgba(255,255,255,.35)`;
  }
  const q = sp.querySelector('.sp-quote'); if (q) q.style.color = v.ink;
  const au = sp.querySelector('.sp-author'); if (au) au.style.color = v.sub;
  sp.querySelectorAll('.sp-loading span').forEach(s => { s.style.background = v.dot; });
  /* 选了主题就把这张启动屏重画一遍。**必须在同一次调用里做完**：
     分两步（先默认、下一帧再主题）就是肉眼可见地闪一下默认色再变。
     它复用上面那六层 DOM，不新增元素 —— 启动屏是每天见几十次的东西，
     多一层就多一次合成。 */
  try { if (dlArtMode()) dlArtSplash(sp); } catch (_) { /* 主题画不出来就留着上面这张默认的 */ }
  return v;
}

/* 登录 / 注册 / 找回密码三页的天光底。**和启动屏是同一张色表、同一批层** ——
   启动屏淡出后落到登录页，不该换一块天；反过来，登录成功跳进应用时也接得上。
   这三页各有各的表单，共用的只有底和卡片那几个颜色，所以这里只做两件事：
     · 把 #dl-sky 那五层画出来（层的位置和尺寸在 auth.css 里，这里只给"画什么、多浓"）；
     · 把卡片要用的颜色写成 body 上的 --dl-* 变量，交给 auth.css 去用。
   卡片颜色不再进锚点表：那张表还被 gen_appicon.py 和 desktop/gongkao_native.py 镜像着，
   为一页表单往里加六个键，三处都得跟着改。这里改从 v.ink 的明暗推——夜里字是近白的，
   就翻成墨色玻璃；白天就是半透明宣纸，并且带一点当时天光的冷暖（死白会像贴上去的）。 */
function dlPaintAuth(h) {
  const sky = document.getElementById('dl-sky');
  if (!sky) return null;                      // 这一页没有天光底（比如后台页）
  const v = dlAt(h == null ? dlNow() : h);
  const set = (id, op, bg) => {
    const e = document.getElementById(id);
    if (!e) return;
    e.style.opacity = op;
    if (bg) e.style.backgroundImage = bg;
  };
  sky.style.backgroundImage = `linear-gradient(180deg,${v.sky[0]} 0%,${v.sky[1]} 52%,${v.sky[2]} 100%)`;
  set('dl-grid', v.grid,
    'repeating-linear-gradient(0deg,rgba(26,111,181,.055) 0 1px,transparent 1px 26px),'
    + 'repeating-linear-gradient(90deg,rgba(26,111,181,.055) 0 1px,transparent 1px 26px)');
  set('dl-bloom', v.bloom,
    'radial-gradient(85% 30% at 50% 2%,rgba(252,190,96,.5),transparent 64%),'
    + 'radial-gradient(52% 16% at 50% 3%,rgba(255,232,180,.7),transparent 70%)');
  set('dl-stars', v.stars, DL_STARS);
  set('dl-hill', v.hill);
  set('dl-grain', v.grain * 0.5, dlGrain() || undefined);

  /* 夜里（v.ink 是近白的）翻成墨色玻璃，白天是宣纸。判据用字色而不是时刻：
     锚点表哪天调了，这里自己会跟上。 */
  const dark = dlLum(v.ink) > 0.5;
  const tint = dlRGB(v.sky[0]).map(c => Math.round(c + (255 - c) * 0.86));   // 白里掺一点当时的天光
  const b = document.body;
  const S = (k, val) => b.style.setProperty(k, val);
  S('--dl-ink', v.ink);
  S('--dl-sub', v.sub);
  S('--dl-seal1', v.seal[0]);
  S('--dl-seal2', v.seal[1]);
  S('--dl-sealsh', dlRgba(v.seal[1], 0.3));
  S('--dl-card', dark ? 'rgba(13,27,46,.62)' : `rgba(${tint.join(',')},.82)`);
  /* 不支持 backdrop-filter 的壳（旧 WebView）拿不到模糊，半透明卡压在稿纸格上会花。
     给它一个不透明的同色兜底，auth.css 用 @supports 挑。 */
  S('--dl-card-solid', dark ? 'rgb(16,32,52)' : `rgb(${tint.join(',')})`);
  S('--dl-line', dark ? 'rgba(150,190,235,.22)' : 'rgba(26,111,181,.14)');
  S('--dl-fld', dark ? 'rgba(255,255,255,.07)' : 'rgba(255,255,255,.72)');
  S('--dl-fline', dark ? 'rgba(150,190,235,.26)' : 'rgba(26,111,181,.18)');
  S('--dl-ring', dlRgba(v.seal[0], 0.22));
  S('--dl-shadow', dark ? '0 18px 46px rgba(0,10,25,.5)' : '0 14px 40px rgba(10,25,45,.16)');
  /* 状态栏跟着天光走。安卓壳里这一条最显眼：不改的话，米白的晨光底顶着一条深蓝状态栏。 */
  const m = document.querySelector('meta[name="theme-color"]');
  if (m) m.setAttribute('content', v.sky[0]);
  return v;
}

/* 四套主题各自的启动屏。层的位置和尺寸仍在 CSS 里，这里只给"画什么、多浓"。
   共用的两件事：底色渐变 + 文字色，都取当前时刻那一档。 */
function dlArtSplash(sp) {
  const mode = dlArtMode();
  const v = dlArtAt(mode, dlArtHour());
  if (!v) return;
  const lay = (id, op, bg) => {
    const e = document.getElementById(id);
    if (!e) return;
    e.style.opacity = op;
    e.style.backgroundImage = bg || 'none';
  };
  const wall = v.wall || v.sky || [v.bg, v.bg, v.card];
  sp.style.backgroundImage = `linear-gradient(180deg,${wall[0]} 0%,${wall[1]} 52%,${wall[2]} 100%)`;
  sp.style.color = v.text;
  // 先把各层全清零，各主题只点亮自己要的那几层（漏清就会留着上一套的痕迹）
  ['sp-grid', 'sp-bloom', 'sp-stars', 'sp-hill', 'sp-trail', 'sp-grain', 'sp-art'].forEach(id => lay(id, 0, null));
  /* 横构图的开关。**在这里翻**而不是等 dlArtApply：那一步在本函数之后才跑，
     晚一拍就是启动屏先居中画一帧、再跳到靠左 —— 每天见几十次的那一下。 */
  const desk = !!DL_ART[mode].desk;
  if (document.body) document.body.classList.toggle('art-desk', desk);
  const art = document.getElementById('sp-art');
  if (art && !desk) art.innerHTML = '';           // 换回手机那几套时，把上一套的美术层撤干净

  const hill = document.querySelectorAll('#sp-hill svg path');
  const logo = sp.querySelector('.sp-logo');
  const dot = v.text;

  if (DL_ART[mode].art2) {
    /* 第二代：材质铺满，卡通占一侧。手机竖构图把画放在下半屏（文字在上），
       电脑横构图放右半 —— 和进入界面后壁纸的摆位一致，启动到进入不跳。
       浓度比壁纸上提一档：这一屏就三行字，画不出来这一下就白开了。 */
    const T = DL_ART[mode];
    const grid = document.getElementById('sp-grid');
    if (grid) { grid.style.opacity = '1'; dlLayers(grid, dlPatLayers(T.pat, v, T.patS || 1)); }
    if (art) {
      art.innerHTML = '';
      art.style.opacity = '1';
      const sc = dlSceneUrl(T.scene, {
        il1: v.il1, il2: v.il2, ila: Math.min(0.8, (v.ila || 0.22) * 2.6),
      });
      dlLayers(art, [desk
        ? { img: sc, size: '46vmin auto', pos: 'right 6vmin center', rep: 'no-repeat' }
        : { img: sc, size: '80vmin auto', pos: 'center bottom 4vmin', rep: 'no-repeat' }]);
    }
    if (logo) {
      logo.style.backgroundImage = `linear-gradient(150deg,${v.tile[0]},${v.tile[1]})`;
      logo.style.color = v.text;
      logo.style.boxShadow = `0 10px 30px ${dlAlpha(v.text, 0.16)}`;
    }
  } else if (mode === 'paper') {
    // 纸 + 界格 + 一抹远山；方章用朱 —— 这一稿的名字就是「宣纸与印」
    lay('sp-grid', 1, `repeating-linear-gradient(0deg,${dlAlpha(v.ink, v.grid)} 0 1px,transparent 1px 26px),`
      + `repeating-linear-gradient(90deg,${dlAlpha(v.ink, v.grid)} 0 1px,transparent 1px 26px)`);
    lay('sp-grain', v.grain * 0.5, dlGrain() || null);
    lay('sp-hill', 0.12, null);
    if (hill.length) {
      hill[0].setAttribute('fill', v.ink); hill[0].setAttribute('opacity', '.5');
      hill[1].setAttribute('stroke', v.seal); hill[1].setAttribute('opacity', '.5');
      hill[2].setAttribute('fill', v.ink);
    }
    if (logo) {
      logo.style.backgroundImage = `linear-gradient(150deg,${v.seal},${v.seal})`;
      logo.style.color = v.tile[0];
      logo.style.boxShadow = `0 10px 30px ${dlAlpha(v.seal, 0.28)},inset 0 1px 0 rgba(255,255,255,.28)`;
    }
  } else if (mode === 'glass') {
    /* 天光本来就是默认那张的底子，所以琉璃的记号只能落在**日/月**和**玻璃方章**上：
       日轮按钟点在天上走位（和壁纸同一条弧），方章是一块透光的琉璃而不是实心印。 */
    const h = dlArtHour(), day = (h >= 5 && h < 19);
    const q2 = day ? (h - 5) / 14 : (((h - 19) + 24) % 24) / 10;
    // 压在上缘那一带：再低就撞上方章和引言了（.sp-body 是垂直居中的）
    const x = (9 + 82 * q2).toFixed(1), y = (27 - 14 * Math.sin(Math.PI * q2)).toFixed(1);
    lay('sp-bloom', 1, `radial-gradient(circle at ${x}% ${y}%,${dlAlpha(v.orb, day ? 1 : 0.86)} 0 3.2vmin,transparent 4.6vmin),`
      + `radial-gradient(circle at ${x}% ${y}%,${dlAlpha(v.orb, 0.22)} 0,transparent 20vmin)`);
    lay('sp-stars', v.dark > 0.5 ? 0.8 : 0, DL_STARS);
    if (logo) {
      // 统一用 backgroundImage 写（别混 background 简写：它会把上一套的图一起清掉，
      // 换主题不重载时留下半套状态）
      const g = v.dark > 0.5 ? 'rgba(255,255,255,.14)' : 'rgba(255,255,255,.55)';
      logo.style.backgroundImage = `linear-gradient(${g},${g})`;
      logo.style.color = v.text;
      logo.style.boxShadow = `inset 0 0 0 1.5px rgba(255,255,255,${(v.gb * 1.2).toFixed(2)}),0 10px 30px rgba(10,20,40,.18)`;
    }
  } else if (mode === 'ink') {
    // 整屏单色，全靠两重山的浓淡撑层次；夜里月亮从右上升起来
    lay('sp-hill', 1, null);
    if (hill.length) {
      hill[0].setAttribute('fill', v.mid); hill[0].setAttribute('opacity', String(0.75));
      hill[1].setAttribute('stroke', 'none'); hill[1].setAttribute('opacity', '0');
      hill[2].setAttribute('fill', v.near);
    }
    if (v.moon > 0.05) {
      lay('sp-bloom', 1, `radial-gradient(circle at 76% 20%,rgba(244,244,238,${(0.9 * v.moon).toFixed(2)}) 0 3vmin,transparent 3.6vmin),`
        + `radial-gradient(circle at 76% 20%,rgba(240,242,236,${(0.16 * v.moon).toFixed(2)}) 0,transparent 18vmin)`);
    }
    if (logo) {
      logo.style.backgroundImage = `linear-gradient(150deg,${v.blk},${v.blk})`;
      logo.style.color = v.glyph;
      logo.style.boxShadow = `0 10px 30px rgba(10,12,16,.30),inset 0 0 0 1.5px rgba(238,236,228,${v.rim.toFixed(2)})`;
    }
  } else if (mode === 'hue') {
    // 细织纹 + 两团低彩度色场；方章取靛
    lay('sp-grid', v.weave * 0.5,
      'repeating-linear-gradient(45deg,rgba(255,255,255,.06) 0 1px,transparent 1px 5px),'
      + 'repeating-linear-gradient(-45deg,rgba(0,0,0,.05) 0 1px,transparent 1px 5px)');
    lay('sp-bloom', 0.22, `radial-gradient(70% 34% at 14% 8%,${dlArtHue(v, 1)},transparent 66%),`
      + `radial-gradient(64% 32% at 88% 78%,${dlArtHue(v, 3)},transparent 68%)`);
    if (logo) {
      const c = dlArtHue(v, 1);
      logo.style.backgroundImage = `linear-gradient(150deg,${dlMixR(c, '#ffffff', 0.24)},${c} 70%)`;
      logo.style.color = '#fff';
      logo.style.boxShadow = `0 10px 30px ${dlAlpha(c, 0.30)},inset 0 1px 0 rgba(255,255,255,.32)`;
    }
  } else if (DL_ART[mode].desk) {
    dlArtSplashDesk(mode, v, lay, logo, art);
  }
  const q = sp.querySelector('.sp-quote'); if (q) q.style.color = v.text;
  const au = sp.querySelector('.sp-author'); if (au) au.style.color = v.muted;
  sp.querySelectorAll('.sp-loading span').forEach(s => { s.style.background = dlAlpha(dot, 0.6); });
}

/* 开片。和星子、光点一样**位置写死**：随机的话每次开应用裂纹都在跳，
   而这是每天见几十次的第一眼。只画右半屏 —— 正文区一根线都不落，
   不然引言会被裂纹从中间穿过去。 */
const DL_CRACK = 'M6 0 L18 26 L11 47 L24 72 L19 100 M18 26 L41 33 L58 20 L74 27 L96 14'
  + ' M41 33 L47 58 L63 71 L58 100 M24 72 L47 58 M63 71 L84 63 L100 74'
  + ' M74 27 L84 63 M52 0 L58 20 M96 14 L100 30';

/* 电脑端四套的启动屏。横构图（正文靠左、右半留给美术）由 CSS 的 body.art-desk 管，
   这里只画美术那一半。多出来的那层是 #sp-art：手机那四套用不到它，
   HTML 里它是空的，也就不多一次合成。 */
function dlArtSplashDesk(mode, v, lay, logo, art) {
  const px = (n) => n.toFixed(2) + 'vmin';
  if (mode === 'celadon') {
    // 一整面釉 + 开片 + 右边那枚圆印。圆印是这一稿唯一的实物感
    if (art) {
      /* 一份图案镜像铺成 4×3。整张只画一遍的话，1440 宽的屏上一个"开片"能有 400px ——
         那不是开片，是几块拼图。逐块翻转而不是平移：接缝两边的线是连着的，看不出是十二块。 */
      const w = 25, hh = 100 / 3;
      let tiles = '';
      for (let gx = 0; gx < 4; gx++) {
        for (let gy = 0; gy < 3; gy++) {
          const fx = gx % 2, fy = gy % 2;
          tiles += `<g transform="translate(${(gx + fx) * w},${(gy + fy) * hh})`
            + ` scale(${(fx ? -w : w) / 100},${(fy ? -hh : hh) / 100})"><path d="${DL_CRACK}"/></g>`;
        }
      }
      art.innerHTML =
        `<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"
           style="position:absolute;right:0;top:0;width:58%;height:100%"
           fill="none" stroke="${dlAlpha(v.crack, v.crackA)}" stroke-width=".45">${tiles}</svg>`
        + `<i style="position:absolute;right:11%;top:50%;transform:translateY(-50%);
             width:${px(20)};height:${px(20)};border-radius:50%;display:grid;place-items:center;
             font-style:normal;font-size:${px(5)};font-weight:700;letter-spacing:0;
             font-family:'Songti SC','Noto Serif CJK SC','SimSun',serif;color:${v.glyph};
             background:radial-gradient(circle at 38% 32%,${dlAlpha(v.crack, 0.4)},transparent 62%),
               linear-gradient(150deg,${v.seal[0]},${v.seal[1]});
             box-shadow:inset 0 0 0 ${px(0.35)} ${dlAlpha(v.crack, 0.4)},0 ${px(1.6)} ${px(4)} rgba(20,40,34,.24)">考</i>`;
    }
    lay('sp-art', 1, null);
    lay('sp-grain', v.grain * 0.4, dlGrain() || null);
    if (logo) {
      logo.style.backgroundImage = `linear-gradient(150deg,${v.seal[0]},${v.seal[1]} 70%)`;
      logo.style.color = v.glyph;
      logo.style.boxShadow = `0 10px 28px ${dlAlpha(v.seal[1], 0.34)},inset 0 1px 0 ${dlAlpha(v.crack, 0.3)}`;
    }
  } else if (mode === 'dossier') {
    // 一页摊开的卷宗：稿纸格 + 装订线 + 档案栏 + 骑缝朱印
    const ln = dlAlpha(v.rule, v.grid);
    lay('sp-grid', 1, `repeating-linear-gradient(0deg,${ln} 0 1px,transparent 1px 26px),`
      + `repeating-linear-gradient(90deg,${ln} 0 1px,transparent 1px 26px)`);
    lay('sp-grain', v.grain * 0.5, dlGrain() || null);
    if (art) {
      const hole = (top) => `<i style="position:absolute;left:${px(1.6)};top:${top};
        width:${px(1.4)};height:${px(1.4)};border-radius:50%;background:${dlAlpha(v.rule, 0.3)}"></i>`;
      art.innerHTML =
        `<div style="position:absolute;left:0;top:0;bottom:0;width:${px(4.6)};
           background:linear-gradient(90deg,${dlAlpha(v.rule, v.grid * 1.5)},transparent);
           border-right:1px solid ${dlAlpha(v.seal, 0.42)}">${hole('22%')}${hole('50%')}${hole('78%')}</div>`
        + `<div style="position:absolute;left:8%;right:6%;top:${px(5.6)};height:1px;
             background:${dlAlpha(v.seal, 0.4)}">
             <span style="position:absolute;right:0;top:${px(-2.9)};font-size:${px(1.35)};
               letter-spacing:.28em;color:${dlAlpha(v.text, 0.6)}">公考助手 · 学习卷宗</span></div>`
        /* 印落右下角那一侧、压着骑缝 —— 和「宣纸与印」的朱印一个规矩：
           朱只做记号，不往交互色里挤 */
        + `<i style="position:absolute;right:9%;top:50%;
             transform:translateY(-50%) rotate(-4deg);width:${px(13)};height:${px(13)};
             border-radius:${px(1.2)};box-shadow:inset 0 0 0 ${px(0.5)} ${v.seal};color:${v.seal};
             opacity:.82;display:grid;place-items:center;text-align:center;line-height:1.15;
             font-style:normal;font-size:${px(3.4)};font-weight:700;letter-spacing:.1em;
             font-family:'Songti SC','Noto Serif CJK SC','SimSun',serif">公考<br>助手</i>`;
    }
    lay('sp-art', 1, null);
    if (logo) {
      // 封条那块墨绿。上面的字一律用纸色写死：这块底全天都是深绿，跟着 card 走反而会在夜里消失
      logo.style.backgroundImage = `linear-gradient(150deg,${dlMixR(v.band, '#ffffff', 0.12)},${v.band} 70%)`;
      logo.style.color = '#f4efe2';
      logo.style.boxShadow = `0 10px 26px ${dlAlpha(v.band, 0.42)},inset 0 1px 0 rgba(255,255,255,.14)`;
    }
  } else if (mode === 'night') {
    // 台灯的暖晕在右上，星子铺满，底部一线地平 —— 全屏就这三件事
    lay('sp-stars', v.stars, DL_STARS);
    lay('sp-bloom', 1, `radial-gradient(circle at 84% 12%,${dlAlpha(v.lamp, v.lampA)} 0,transparent 46vmin)`);
    if (art) {
      art.innerHTML =
        `<div style="position:absolute;left:0;right:0;bottom:16%;height:1px;
           background:linear-gradient(90deg,transparent,${dlAlpha(v.hz, 0.5)} 45%,transparent)"></div>`
        /* 辉光要**朝着地平线聚**（上端透明），不能反过来：
           反过来那一层的上边缘就是一条横贯全屏的硬线，比地平线本身还显眼。 */
        + `<div style="position:absolute;left:0;right:0;bottom:16%;height:${px(16)};
             background:linear-gradient(180deg,transparent,${dlAlpha(v.hz, 0.08)})"></div>`;
    }
    lay('sp-art', 1, null);
    if (logo) {
      logo.style.backgroundImage = `linear-gradient(150deg,${v.tile[0]},${v.tile[1]} 70%)`;
      logo.style.color = v.glyph;
      logo.style.boxShadow = `0 0 ${px(3)} ${dlAlpha(v.blue, 0.3)},inset 0 0 0 1px ${dlAlpha(v.blue, 0.4)}`;
    }
  } else if (mode === 'studio') {
    /* 一条横线、一个方块、一行小字。那条线就是界面里顶栏底边的位置 ——
       启动到进入是接着的，不会跳一下（.sp-body 也因此贴着线下方排，见 CSS）。 */
    if (art) {
      const bar = (h, x) => `<i style="width:${px(0.5)};height:${px(h)};border-radius:99px;
        background:${dlAlpha(v.rule, 0.9)};margin-left:${x ? px(0.8) : 0}"></i>`;
      art.innerHTML =
        `<div style="position:absolute;left:0;right:0;top:50%;height:1px;background:${v.rule}"></div>`
        + `<div style="position:absolute;left:8%;top:calc(50% - ${px(1.6)});
             width:${px(0.22)};height:${px(3.2)};background:${v.blue}"></div>`
        + `<div style="position:absolute;right:8%;top:calc(50% - ${px(4.4)});font-size:${px(1.3)};
             letter-spacing:.24em;color:${v.muted};font-variant-numeric:tabular-nums">正在载入</div>`
        + `<div style="position:absolute;right:8%;top:calc(50% + ${px(3)});display:flex;
             align-items:flex-end">${bar(1.2)}${bar(2.4, 1)}${bar(1.8, 1)}${bar(3.4, 1)}${bar(2, 1)}${bar(1.2, 1)}</div>`;
    }
    lay('sp-art', 1, null);
    if (logo) {
      // 方章就是一块墨（用正文色），字挖成底色。日夜自动对调，不用另写一套
      logo.style.backgroundImage = `linear-gradient(150deg,${v.text},${v.text})`;
      logo.style.color = v.card;
      logo.style.boxShadow = 'none';
    }
  }
}

/* 标签页图标：按当前时刻现画一张塞进 <link rel=icon>。
   桌面/安卓的图标是打包死的文件（gen_appicon.py 导的），只有这里能真的跟着时间走。 */
function dlFavicon(h) {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext && c.getContext('2d');
  if (!g) return null;                        // jsdom / 老壳没有 canvas，没图标而已，不影响用
  const v = dlAt(h == null ? dlNow() : h);
  const S = 64, r = S * 0.23;
  const box = (x, y, w, hh, rad, fill) => {
    g.beginPath();
    if (g.roundRect) g.roundRect(x, y, w, hh, rad);
    else g.rect(x, y, w, hh);
    g.fillStyle = fill; g.fill();
  };
  const lin = (y0, y1, c0, c1) => { const t = g.createLinearGradient(0, y0, S, y1); t.addColorStop(0, c0); t.addColorStop(1, c1); return t; };
  box(0, 0, S, S, r, lin(0, S, v.icon[0], v.icon[1]));
  if (v.rim > 0.05) {                          // 底色暗到一定程度才补描边，浅底上加了反而脏
    g.strokeStyle = `rgba(255,255,255,${0.22 * v.rim})`;
    g.lineWidth = 1.5;
    g.beginPath();
    if (g.roundRect) g.roundRect(0.75, 0.75, S - 1.5, S - 1.5, r); else g.rect(0.75, 0.75, S - 1.5, S - 1.5);
    g.stroke();
  }
  const s = S * 0.6, o = (S - s) / 2;
  box(o, o, s, s, s * 0.17, lin(o, o + s, v.seal[0], v.seal[1]));
  g.fillStyle = '#fff';
  g.font = '800 ' + Math.round(S * 0.30) + 'px "PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif';
  g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText('公', S / 2, S / 2 + S * 0.015);
  let link = document.querySelector('link[rel="icon"]');
  if (!link) { link = document.createElement('link'); link.rel = 'icon'; document.head.appendChild(link); }
  link.type = 'image/png';
  link.href = c.toDataURL('image/png');
  return v;
}

/* ================================================================
   主题风格（美术方向）

   十八套美术稿，手机端九套 / 电脑端九套（两端互不出现，见 dlIsDesk）。
   前八套逐个锚点手写，后十套走下面 dlArt2() 那张紧凑表。
   默认**一套都不开**，界面就是原来的样子 —— 这是可选项，不是改版。

   和上面那套启动屏日光共用同一副骨架：同样六个锚点小时，同样的插值和跨零点接法，
   换的只是每个锚点上填什么色、什么材质。所以「主题」不是另一套机制。

   为什么住在这个文件里：主题得在**第一帧**就是对的颜色。晚一拍就是白底闪一下
   再变成夜色，每天见几十次，比不做还难受。这个文件是全页第一个脚本。

   颜色写在 **body 的 inline style** 上，不是 documentElement：
   style.css 里 body.dark{--bg:…} 是挂在 body 上的，写到 html 上会被它盖掉。
   inline 优先级最高，两边不用互相让。
   ================================================================ */

// 六个模块的传统色底色（节气色专用）。**色相全天锁死**——认色识别模块的前提是
// 色相不动，随时间变的只有掺进去多少 tint。顺序对齐 tabviews.js 的 LB_TILES：
// 小记 缃 / 知识库 靛 / 草稿本 藕荷 / 资料库 竹青 / 云盘 天缥 / 收藏 赭
const DL_HUES = ['#dfa42a', '#2b5b8c', '#7b6aa6', '#2c7a68', '#4d97c9', '#b35a33'];

const DL_ART_HRS = [5.0, 8.0, 13.0, 18.0, 20.5, 23.0];

/* 六个锚点填同一份值 = 这套主题不跟时刻变。夜航（desk + fixed）用它：
   一天里怎么插值都是同一个结果，机制不用为它开特例。 */
const dlSame = (k) => [k, k, k, k, k, k];

/* 手机端和电脑端各有各的主题，两边**互不出现**（用户的要求）。
   分界线就是 style.css 里左侧导航栏那条断点 —— 一个数，两处引用，别再各写各的。 */
const DL_DESK_W = 761;
function dlIsDesk() { return (window.innerWidth || 1024) >= DL_DESK_W; }
/* 选择也分两处记。为什么不共用一个键：共用的话，在电脑上选了「卷宗」再把窗口拖窄，
   要么窄屏顶着一套没有 CSS 的主题（inline 变量还在，样式却在 media 里失效了），
   要么就得把人家的选择清掉。分开记，两端各自记得自己那套，来回拖也不丢。 */
function dlArtKey() { return dlIsDesk() ? 'artThemeDesk' : 'artTheme'; }

/* ---------------- 第二代主题的写法 ----------------
   前八套是逐个锚点写字面量的：六行 × 十二个字段，一套六十行。到第九套时这么写
   就是七百行几乎一样的十六进制，改一个字段要在六处对齐（漏一处就是某个钟点配色不对）。

   这里换一张紧凑表：一天里**真正在变的只有底色**，而"读字的那一面"（卡片 / 字 /
   描边 / 强调 / 图标底）在同一端内是同一组值 —— 本来 DL_ART_SNAP 就是让它们到点硬翻，
   翻的就是 day ↔ night 这两组。所以一套主题只要报：
     day / night   两组读字面的值
     bg / bg2      六个锚点各自的底色
     il1/il2/ila   插画的两支色和浓度（白天一组、夜里一组，跟着 day/night 走）
   dlArt2() 把它摊成 DL_ART 要的六个锚点，字段名和第一代完全一样，
   插值、硬翻、壁纸那套机制一行都不用动。

   壁纸的三段渐变由底色现算（比底色亮 4% → 底色 → 暗一档），不再逐套手写：
   八套里那二十四组 wall 值本来也都是照这个关系配的。 */
const DL_ART2_DARK = [1, 0, 0, 0, 1, 1];
function dlArt2(o) {
  const keys = DL_ART2_DARK.map((dk, i) => {
    const s = dk ? o.night : o.day;
    const bg = o.bg[i], bg2 = o.bg2[i];
    return Object.assign({}, s, {
      dark: dk, bg, bg2,
      // 夜里底下压得更暗：深色底上如果三段一样亮，那面墙就是一块死板
      wall: [dlMixR(bg, '#ffffff', dk ? 0.05 : 0.04), bg, dlMixR(bg, '#000000', dk ? 0.34 : 0.06)],
      ink: s.text, glyph: s.card,
    });
  });
  return {
    name: o.name, hint: o.hint, icons: o.icons, scene: o.scene, pat: o.pat,
    patS: o.patS || 1, kb: o.kb, art2: 1, desk: o.desk, keys,
  };
}

/* 每套主题六个锚点。共有字段：
     dark  这一刻是不是暗环境（决定要不要给 body 加 .dark；插值后过 0.5 才算）
     bg/bg2/card/line/text/muted/blue  直接顶掉 style.css 的同名变量
     fill  实心按钮的底色 —— 必须**全天都压得住白字**，不能跟着 blue 一起变浅
   其余字段各主题自用，含义写在各自那一段。 */
const DL_ART = {
  /* 宣纸与印：纸、墨、一点朱。
     tile 是模块图标那张纸的两段底色，ink 是墨线，seal 是右下角那枚朱印
     （落在右下是国画的规矩，也是为了躲开右上角——那是角标的位置，
     六个红点排一屏会被整片读成"六处未读"）。
     朱**只做装饰**，不当交互色：交互色仍是墨蓝，免得和"危险/删除"的红撞车。 */
  paper: {
    name: '宣纸与印', hint: '纸、墨、一点朱', icons: 'paper', scene: 'paper', ila: 0.26,
    keys: [
      { dark: 1, bg: '#1b2130', bg2: '#232833', card: '#262c38', line: '#333a48', text: '#ded8c9', muted: '#9aa0ad', blue: '#6fa8dc', fill: '#1c5a8a',
        wall: ['#1b2130', '#2a2f3f', '#453f4a'], tile: ['#2a3040', '#1e2431'], ink: '#ded8c9', seal: '#c4614e', grain: 0.18, rim: 0.20, grid: 0.05 },
      { dark: 0, bg: '#f3ebdc', bg2: '#ece4d4', card: '#fffdf7', line: '#e0d8c8', text: '#20262e', muted: '#7c8490', blue: '#1c5a8a', fill: '#1c5a8a',
        wall: ['#f7f1e4', '#f3ebdc', '#e9e2d3'], tile: ['#fdfaf3', '#f2ece0'], ink: '#20262e', seal: '#b8402f', grain: 0.50, rim: 0.26, grid: 0.055 },
      { dark: 0, bg: '#f6f2e9', bg2: '#efeade', card: '#fffefa', line: '#e3ddd0', text: '#1c222a', muted: '#7b838e', blue: '#1c5a8a', fill: '#1c5a8a',
        wall: ['#fbf8f1', '#f6f2e9', '#ece7dd'], tile: ['#fffdf7', '#f5efe4'], ink: '#1c222a', seal: '#b8402f', grain: 0.42, rim: 0.24, grid: 0.05 },
      { dark: 0, bg: '#f0cfaf', bg2: '#e8c6a6', card: '#fbecd8', line: '#ddc0a4', text: '#38291f', muted: '#8a7160', blue: '#1d5f8f', fill: '#1d5f8f',
        wall: ['#f8e0c2', '#efcaa6', '#d5ab9d'], tile: ['#f8e6cd', '#e6c9a8'], ink: '#38291f', seal: '#a3372a', grain: 0.46, rim: 0.24, grid: 0.045 },
      { dark: 1, bg: '#2e3446', bg2: '#363d50', card: '#3d434f', line: '#454c5c', text: '#e6e0d2', muted: '#a3a8b3', blue: '#6fa8dc', fill: '#1c5a8a',
        wall: ['#3f4457', '#2e3446', '#252c3d'], tile: ['#3a3f4d', '#2b3040'], ink: '#e6e0d2', seal: '#c4614e', grain: 0.30, rim: 0.22, grid: 0.045 },
      { dark: 1, bg: '#101620', bg2: '#171e2a', card: '#1d2430', line: '#2a3140', text: '#e8e2d3', muted: '#98a0ae', blue: '#7fb6e8', fill: '#1c5a8a',
        wall: ['#141a26', '#101620', '#0b1017'], tile: ['#1a202c', '#131923'], ink: '#e8e2d3', seal: '#cf6a55', grain: 0.22, rim: 0.24, grid: 0.04 },
    ],
  },
  /* 天光琉璃：壁纸就是天（sky 直接抄上面 DL_KEYS 的三段渐变，一处改两处跟），
     模块面是磨砂玻璃，本身没颜色，颜色全是背后透上来的天色。
     ga = 玻璃底的白色浓度，gb = 那圈亮边的浓度，glow = 模块背后那盏灯透出多少。
     orb 是天上那颗日/月的颜色，位置按钟点算（见 dlArtWall）。 */
  glass: {
    name: '天光琉璃', hint: '界面浮在天上', icons: 'glass', scene: 'glass', ila: 0.2,
    keys: [
      { dark: 1, bg: '#2b3550', bg2: '#33405e', line: '#4a5570', text: '#e8ecf4', muted: '#a8b0c0', blue: '#8fb8e0', fill: '#1a6fb5',
        sky: ['#16223a', '#33405e', '#8a6a70'], gc: '#1b2437', ga: 0.58, gb: 0.26, glow: 0.55, orb: '#f0d8b8' },
      { dark: 0, bg: '#fdf3e6', bg2: '#f2ece2', line: '#e2ddd2', text: '#20303f', muted: '#7c848f', blue: '#1a6fb5', fill: '#1a6fb5',
        sky: ['#fff4e0', '#fdf3e6', '#e8f0f8'], gc: '#ffffff', ga: 0.66, gb: 0.55, glow: 0.30, orb: '#ffd98a' },
      { dark: 0, bg: '#eef4fb', bg2: '#e6edf6', line: '#d8e2ee', text: '#22323f', muted: '#7b838e', blue: '#1a6fb5', fill: '#1a6fb5',
        sky: ['#f8fbff', '#eef4fb', '#e2ecf7'], gc: '#ffffff', ga: 0.72, gb: 0.62, glow: 0.20, orb: '#fff0c0' },
      { dark: 0, bg: '#f3b487', bg2: '#e7ab84', line: '#d7a289', text: '#3a2c2c', muted: '#7d6664', blue: '#1d6390', fill: '#1d6390',
        sky: ['#ffd9a8', '#f3b487', '#b98fa8'], gc: '#fffaf2', ga: 0.62, gb: 0.50, glow: 0.55, orb: '#ffb066' },
      { dark: 1, bg: '#27364f', bg2: '#2e3d58', line: '#3f4d68', text: '#e6ecf6', muted: '#9fa9bd', blue: '#9ec4e8', fill: '#1a6fb5',
        sky: ['#3b4a6b', '#27364f', '#1b2b47'], gc: '#212b40', ga: 0.60, gb: 0.30, glow: 0.35, orb: '#dfe6f2' },
      { dark: 1, bg: '#14304f', bg2: '#12283f', line: '#25405e', text: '#e9f0f8', muted: '#93a2b8', blue: '#7fb6e8', fill: '#1a6fb5',
        sky: ['#0e1d33', '#14304f', '#0c1c30'], gc: '#0d1626', ga: 0.64, gb: 0.24, glow: 0.22, orb: '#eef3fb' },
    ],
  },
  /* 墨山：整屏没有第二个颜色。壁纸是五重山，时间不改色相，改的是
     **看得见几重山、墨有多浓**（m 是五重各自的浓度）。
     blk/glyph 是模块图标那块墨和挖白的字形，rim 是夜里把墨块从暗底上抠出来的月白发丝线
     —— 就是 DL_KEYS 里 rim 那一招。
     （试过白天阳刻、夜里阴刻那种反相：插值中途墨块和字形一起走到中灰，
     19:00 前后一小时图标整块看不见，放弃了。） */
  ink: {
    name: '墨山', hint: '拓片式，全屏单色', icons: 'ink',
    keys: [
      { dark: 1, bg: '#232830', bg2: '#2a2f38', card: '#2a2f38', line: '#3a404b', text: '#e2e0d8', muted: '#9a9d9f', blue: '#c3cad3', fill: '#3a414d',
        far: '#39404c', mid: '#2b313c', near: '#1c2129', blk: '#1a1e26', glyph: '#dfddd4', rim: 0.50, moon: 0.55, m: [0.40, 0.55, 0.75, 0.90, 1] },
      { dark: 0, bg: '#f4f1e9', bg2: '#ebe8df', card: '#fbf9f3', line: '#e2ded2', text: '#23272e', muted: '#7a7d80', blue: '#3d4650', fill: '#3d4650',
        far: '#cfd2ce', mid: '#e2e0d8', near: '#f0ede5', blk: '#23272e', glyph: '#f9f7f1', rim: 0, moon: 0, m: [0.30, 0.16, 0.06, 0, 0] },
      { dark: 0, bg: '#f8f6ef', bg2: '#efede5', card: '#fdfcf7', line: '#e5e2d8', text: '#1e222a', muted: '#787c80', blue: '#3d4650', fill: '#3d4650',
        far: '#d8dad5', mid: '#e9e7de', near: '#f4f2ea', blk: '#1e222a', glyph: '#f8f6ef', rim: 0, moon: 0, m: [0.24, 0.10, 0.03, 0, 0] },
      { dark: 0, bg: '#eae4d8', bg2: '#e2dbcd', card: '#f0ebe0', line: '#d5cdbe', text: '#2b2a28', muted: '#7e7a72', blue: '#44403a', fill: '#44403a',
        far: '#b9b6ae', mid: '#cfcbc0', near: '#e0dbcf', blk: '#2b2a28', glyph: '#f2ece0', rim: 0.12, moon: 0.10, m: [0.46, 0.34, 0.20, 0.08, 0] },
      { dark: 1, bg: '#2b3038', bg2: '#31363f', card: '#31363f', line: '#414751', text: '#e0ded6', muted: '#9b9ea2', blue: '#c3cad3', fill: '#414751',
        far: '#454b56', mid: '#343943', near: '#232830', blk: '#1b1f27', glyph: '#dedcd3', rim: 0.62, moon: 0.70, m: [0.50, 0.66, 0.82, 0.94, 1] },
      { dark: 1, bg: '#14181f', bg2: '#1a1f27', card: '#1a1f27', line: '#2a2f38', text: '#e6e4dc', muted: '#8f9398', blue: '#c8ced6', fill: '#333a44',
        far: '#2b313b', mid: '#1f242c', near: '#12161c', blk: '#1d2028', glyph: '#e6e4dc', rim: 0.78, moon: 1, m: [0.55, 0.72, 0.88, 1, 1] },
    ],
  },
  /* 节气色：改动最小的一稿。保留现在这套实色圆角块 + 白字形（44px 上是验证过的），
     只把配色换成传统色。时间不改色相，六个色一起掺同一份 tint：
     黎明掺灰蓝、正午不掺、黄昏掺夕照、入夜掺墨。weave 是壁纸上那层细织纹。 */
  hue: {
    name: '节气色', hint: '六色识别，低彩度压住', icons: 'hue', scene: 'hue', ila: 0.22,
    keys: [
      { dark: 1, bg: '#1d2431', bg2: '#242b39', card: '#242b39', line: '#323a4a', text: '#e4e7ee', muted: '#9aa2b0', blue: '#7fb0e8', fill: '#2b5b8c',
        wall: ['#232a38', '#1d2431', '#161c27'], tint: '#3d4658', amt: 0.46, weave: 0.5 },
      { dark: 0, bg: '#f4f0e8', bg2: '#ece8de', card: '#fffdf8', line: '#e4dfd4', text: '#20262e', muted: '#7c848f', blue: '#2b5b8c', fill: '#2b5b8c',
        wall: ['#f7f2e8', '#f2eee4', '#eae8de'], tint: '#fff3e0', amt: 0.10, weave: 0.9 },
      { dark: 0, bg: '#f5f5f0', bg2: '#ecece6', card: '#fffffc', line: '#e3e3dc', text: '#1c222a', muted: '#7b838e', blue: '#2b5b8c', fill: '#2b5b8c',
        wall: ['#f9f8f4', '#f3f3ee', '#eaebe6'], tint: '#ffffff', amt: 0, weave: 0.8 },
      { dark: 0, bg: '#f0dcc4', bg2: '#e8d3b8', card: '#faead9', line: '#ddc7ad', text: '#3a2c26', muted: '#8a7160', blue: '#2b5b8c', fill: '#2b5b8c',
        wall: ['#f6e2cb', '#eed3b4', '#dcc0ab'], tint: '#e8934a', amt: 0.18, weave: 0.7 },
      { dark: 1, bg: '#272e3d', bg2: '#2f374a', card: '#333b4b', line: '#414a5d', text: '#e6eaf2', muted: '#a0a8b6', blue: '#7fb0e8', fill: '#2b5b8c',
        wall: ['#333b4c', '#272e3d', '#1f2532'], tint: '#2b3346', amt: 0.34, weave: 0.55 },
      { dark: 1, bg: '#11161f', bg2: '#171d27', card: '#1a212c', line: '#28303c', text: '#e8ecf4', muted: '#98a0ae', blue: '#7fb0e8', fill: '#2b5b8c',
        wall: ['#161c28', '#11161f', '#0c1119'], tint: '#131a26', amt: 0.50, weave: 0.4 },
    ],
  },

  /* ================= 以下四套只在电脑端出现（desk: 1） =================
     上面四套是照手机屏做的：竖构图、大色块、居中排版。同一套稿子搬到 27 寸上，
     大色块变成一整面墙，居中的启动屏在 16:10 里两边空得发慌。
     这四套是重画的：横构图启动屏（正文靠左、右半留给美术），质感靠**边框和密度**
     而不是靠一块大色。两端各记各的选择（见 dlArtKey），互相看不见对方。 */

  /* 青瓷：一整面釉色，靠开片纹和一枚圆印撑住。彩度压到最低 ——
     冷青绿在长时间注视下比蓝更不容易累眼，这一稿是给"一天八小时"准备的。
     釉色**只在壁纸和启动屏上**：读字的那一面仍然是米白纸，有色底铺满正文会把字压灰。
     crack/crackA 是开片纹的颜色和浓度，seal 是那枚圆印的两段釉。 */
  celadon: {
    name: '青瓷', hint: '一整面釉色，最耐看', desk: 1, icons: 'celadon', scene: 'celadon', ila: 0.24,
    keys: [
      { dark: 1, bg: '#1b2523', bg2: '#212c29', card: '#26312e', line: '#33403c', text: '#dbe7e1', muted: '#8fa39b', blue: '#7fb3a5', fill: '#35635a',
        wall: ['#16201e', '#1e2b28', '#2f4740'], crack: '#bee1d2', crackA: 0.26,
        seal: ['#3c6a5e', '#24443b'], tile: ['#3c6a5e', '#24443b'], glyph: '#dfeee7', rim: 0.26, grain: 0.22 },
      { dark: 0, bg: '#eef3ef', bg2: '#e6ece8', card: '#fdfefc', line: '#e0e9e3', text: '#1f2a25', muted: '#77867e', blue: '#3a6a5f', fill: '#35635a',
        wall: ['#f2f7f3', '#dfeae4', '#b9d2c9'], crack: '#ffffff', crackA: 0.50,
        seal: ['#5c8d81', '#33604f'], tile: ['#5c8d81', '#33604f'], glyph: '#f1f6f2', rim: 0.16, grain: 0.40 },
      { dark: 0, bg: '#eef2ef', bg2: '#e6ebe8', card: '#fbfcfa', line: '#e2e9e4', text: '#1e2723', muted: '#78877f', blue: '#3f7166', fill: '#3f7166',
        wall: ['#e7efea', '#cfe0da', '#9fbdb4'], crack: '#ffffff', crackA: 0.55,
        seal: ['#5c8d81', '#33604f'], tile: ['#5c8d81', '#33604f'], glyph: '#f1f6f2', rim: 0.15, grain: 0.38 },
      { dark: 0, bg: '#f0ece0', bg2: '#e8e4d8', card: '#fbf7ec', line: '#e6e2d2', text: '#2a2c22', muted: '#7f8172', blue: '#3e6a5c', fill: '#3f7166',
        wall: ['#f0e9d8', '#d9dfcc', '#a9bcae'], crack: '#fff8e8', crackA: 0.45,
        seal: ['#5a8676', '#2f5a4b'], tile: ['#5a8676', '#2f5a4b'], glyph: '#f4f2e6', rim: 0.16, grain: 0.42 },
      { dark: 1, bg: '#202b28', bg2: '#26312e', card: '#2b3733', line: '#38443f', text: '#dde8e2', muted: '#93a49c', blue: '#82b6a7', fill: '#35635a',
        wall: ['#2b3a35', '#22302c', '#1a2523'], crack: '#bee1d2', crackA: 0.22,
        seal: ['#3f7166', '#254a40'], tile: ['#3f7166', '#254a40'], glyph: '#e4f0ea', rim: 0.28, grain: 0.30 },
      { dark: 1, bg: '#131b19', bg2: '#18211f', card: '#1c2624', line: '#29332f', text: '#dfeae4', muted: '#8b9c94', blue: '#86bbac', fill: '#35635a',
        wall: ['#101816', '#141d1b', '#1d2b27'], crack: '#bee1d2', crackA: 0.18,
        seal: ['#38665b', '#1e3f36'], tile: ['#38665b', '#1e3f36'], glyph: '#dfeee7', rim: 0.30, grain: 0.20 },
    ],
  },

  /* 卷宗：整个电脑端就是一份摊开的卷宗 —— 左边装订线、满屏稿纸格、深墨绿的封条、
     一枚骑缝朱印。四套里辨识度最高的，也是最"公考"的：它长得像答题卡和公文。
     朱**只做记号**（书脊、装订线、印），交互色留给墨绿 —— 和「宣纸与印」同一条规矩，
     免得和"危险/删除"的红撞车。
     band 是顶栏那条封条（必须有个深色压住整面牛皮，不然满屏发黄发飘），
     rule 是稿纸格的线色（**故意不进 SNAP**：它是气氛，硬翻会在正午前后闪一下）。 */
  dossier: {
    name: '卷宗', hint: '像卷宗和答题卡', desk: 1, icons: 'dossier', scene: 'dossier', ila: 0.22,
    keys: [
      { dark: 1, bg: '#1d1c17', bg2: '#23211b', card: '#282520', line: '#37332a', text: '#e6ddc8', muted: '#a09781', blue: '#8fbf9f', fill: '#2f4636',
        wall: ['#1a1914', '#211f19', '#2b2820'], rule: '#dcc496', grid: 0.09, band: '#232f26',
        seal: '#c4614e', tile: ['#2b2822', '#211f19'], ink: '#e6ddc8', glyph: '#e6ddc8', rim: 0.26, grain: 0.20 },
      { dark: 0, bg: '#efe5d2', bg2: '#e7dcc7', card: '#fdf8ec', line: '#e0d3b6', text: '#2b2620', muted: '#877c66', blue: '#2f4636', fill: '#2f4636',
        wall: ['#f4ecdb', '#ece0c9', '#dfd0b0'], rule: '#78603a', grid: 0.13, band: '#2f4636',
        seal: '#b8402f', tile: ['#fdf8ec', '#eee2ca'], ink: '#2f4636', glyph: '#2f4636', rim: 0.22, grain: 0.45 },
      { dark: 0, bg: '#ece3d2', bg2: '#e4dac6', card: '#fbf6ea', line: '#ddd0b4', text: '#2a2620', muted: '#867c68', blue: '#2f4636', fill: '#2f4636',
        wall: ['#f2ebda', '#e9e0cb', '#dccdae'], rule: '#78603a', grid: 0.13, band: '#2f4636',
        seal: '#b8402f', tile: ['#fbf6ea', '#ece0c8'], ink: '#2f4636', glyph: '#2f4636', rim: 0.22, grain: 0.42 },
      { dark: 0, bg: '#efdcc0', bg2: '#e7d3b4', card: '#fbeeda', line: '#ddc7a6', text: '#33291c', muted: '#8a7a60', blue: '#2f4636', fill: '#2f4636',
        wall: ['#f5e2c6', '#ecd4b2', '#d9bb9c'], rule: '#7d5a33', grid: 0.12, band: '#2c4433',
        seal: '#a3372a', tile: ['#fbeeda', '#ecdcc0'], ink: '#2f4636', glyph: '#2f4636', rim: 0.22, grain: 0.44 },
      { dark: 1, bg: '#241f18', bg2: '#2a251c', card: '#2f2a21', line: '#3d372c', text: '#e4dbc6', muted: '#9d9480', blue: '#96c0a4', fill: '#2f4636',
        wall: ['#2b2519', '#231e16', '#1c1811'], rule: '#d9c193', grid: 0.08, band: '#26332a',
        seal: '#c4614e', tile: ['#332e24', '#28241c'], ink: '#e4dbc6', glyph: '#e4dbc6', rim: 0.26, grain: 0.28 },
      { dark: 1, bg: '#191712', bg2: '#1e1c16', card: '#23201a', line: '#2f2b22', text: '#e6ddc8', muted: '#968d79', blue: '#9cc6aa', fill: '#2f4636',
        wall: ['#151410', '#1a1813', '#221f18'], rule: '#d6bd8e', grid: 0.07, band: '#212c24',
        seal: '#cf6a55', tile: ['#272419', '#1d1b15'], ink: '#e6ddc8', glyph: '#e6ddc8', rim: 0.28, grain: 0.18 },
    ],
  },

  /* 夜航：给夜里的大屏做的，**只有一档**（fixed）。整屏近黑，右上一盏台灯的暖晕，
     底部一线地平和几颗星。这是唯一不跟天光的一套：它本来就是夜色，白天开着也成立
     —— 就像 IDE 的深色主题不会到中午自己变白。
     底色是 #0c111a 不是纯黑：纯黑配浅字在 OLED 以外的屏上会拖影，也压不出卡片的层次。
     交互色用青蓝而不是品牌蓝 —— #1a6fb5 在近黑底上只有 3:1；而实心按钮的底（fill）
     仍要压得住白字，所以另取一支更深的。
     暖色**只在启动屏那盏灯上**，界面里一个暖点都不留：那个位置留给"错题"的红。 */
  night: {
    name: '夜航', hint: '夜里的大屏，只有一档', desk: 1, fixed: 1, icons: 'night', scene: 'night', ila: 0.3,
    keys: dlSame({
      dark: 1, bg: '#0c111a', bg2: '#121a26', card: '#141b26', line: '#1f2a38',
      text: '#dfe6f2', muted: '#8894a6', blue: '#58b6d8', fill: '#1d5e7a',
      /* 天由上而下**变亮**（近地那点余光），地最暗 —— 顺序反过来的话，
         底下比天还亮，那条地平线就只是一道台阶，不是地平线。 */
      wall: ['#0a0f18', '#101c2c', '#070b11'], lamp: '#e7a44b', lampA: 0.30, stars: 0.8,
      hz: '#58b6d8', tile: ['#1b2735', '#131b26'], glyph: '#8fd4ec', rim: 0.34, grain: 0.14,
    }),
  },

  /* 白台：走另一个方向 —— 一点装饰都不要。纯白、细线、小圆角、更密的行距，
     全屏只有一处品牌蓝。启动屏几乎是空的：一条横线、一个方块、一行小字。
     那条基线**就是界面里顶栏底边的位置**，启动到进入是接着的，不会跳一下。
     rule 是那条线的颜色（同样不进 SNAP，让它随天光滑过去）。 */
  studio: {
    name: '白台', hint: '没有装饰的工作台', desk: 1, icons: 'studio', scene: 'studio', ila: 0.16,
    keys: [
      { dark: 1, bg: '#101418', bg2: '#151a20', card: '#171d24', line: '#262e38', text: '#e8ecf1', muted: '#8b96a3', blue: '#6cb0e8', fill: '#1a6fb5',
        wall: ['#0e1216', '#101418', '#141a20'], rule: '#2a323c',
        tile: ['#1b222b', '#151b22'], ink: '#6cb0e8', glyph: '#6cb0e8', rim: 0.30, grain: 0 },
      { dark: 0, bg: '#fffdfa', bg2: '#f7f4ee', card: '#ffffff', line: '#ece7de', text: '#11161d', muted: '#7d8791', blue: '#1a6fb5', fill: '#1a6fb5',
        wall: ['#fffefb', '#fffdfa', '#f6f1e9'], rule: '#e6ded2',
        tile: ['#ffffff', '#f7f4ee'], ink: '#1a6fb5', glyph: '#1a6fb5', rim: 0.20, grain: 0 },
      { dark: 0, bg: '#ffffff', bg2: '#f4f6f8', card: '#ffffff', line: '#e4e8ee', text: '#10151c', muted: '#79838f', blue: '#1a6fb5', fill: '#1a6fb5',
        wall: ['#ffffff', '#fbfcfd', '#f2f5f8'], rule: '#dfe4ea',
        tile: ['#ffffff', '#f4f6f8'], ink: '#1a6fb5', glyph: '#1a6fb5', rim: 0.20, grain: 0 },
      { dark: 0, bg: '#fffaf4', bg2: '#f8f1e9', card: '#fffdfa', line: '#ece2d6', text: '#191410', muted: '#857b70', blue: '#1a6fb5', fill: '#1a6fb5',
        wall: ['#fffcf7', '#fdf6ee', '#f2e6d8'], rule: '#e6dcd0',
        tile: ['#fffdfa', '#f8f1e9'], ink: '#1a6fb5', glyph: '#1a6fb5', rim: 0.20, grain: 0 },
      { dark: 1, bg: '#12161c', bg2: '#171c23', card: '#191f27', line: '#28303a', text: '#e6ebf1', muted: '#8a95a2', blue: '#6cb0e8', fill: '#1a6fb5',
        wall: ['#141920', '#12161c', '#0f1318'], rule: '#2c343e',
        tile: ['#1d242d', '#171d25'], ink: '#6cb0e8', glyph: '#6cb0e8', rim: 0.30, grain: 0 },
      { dark: 1, bg: '#0e1217', bg2: '#12171d', card: '#151a21', line: '#232b34', text: '#e8ecf1', muted: '#838d9a', blue: '#6cb0e8', fill: '#1a6fb5',
        wall: ['#0c1015', '#0e1217', '#11161c'], rule: '#28303a',
        tile: ['#191f27', '#13181f'], ink: '#6cb0e8', glyph: '#6cb0e8', rim: 0.32, grain: 0 },
    ],
  },

  /* ================= 第二代：五种画风 × 两端 =================
     和上面八套的区别不在配色，在**图标和插画**：每种画风自带一册字形
     （js/articons.js）和一幅卡通场景（下面的 DL_SCENE），所以「御前手账」的云盘
     是个葫芦、「炸物猫铺」的云盘是口冒汽的锅，不是同一批线条图换个颜色。

     手机和电脑各五套，同一画风两端共用图标册（icons 字段指的是同一本），
     换的是构图：手机把插画压在右下角，电脑摊成右侧大图 + 左下角饰。 */

  /* 御前手账：纸胶带、虚线剪边、墨葫芦。朱只做记号，交互色是墨竹青
     —— 和「宣纸与印」同一条规矩，免得和"危险/删除"的红撞车。 */
  meow: dlArt2({
    name: '御前手账', hint: '纸胶带与墨葫芦', icons: 'meow', scene: 'meow', pat: 'tape',
    day: { card: '#fffdf6', line: '#e0d7c2', text: '#2b2823', muted: '#8b8271', blue: '#4a5c50',
      fill: '#3e4d43', tile: ['#e4e7d4', '#d6dcc2'], seal: '#b8402f',
      il1: '#6b6a62', il2: '#b8402f', ila: 0.22, patA: 0.16, rim: 0.2 },
    night: { card: '#262820', line: '#34362c', text: '#e3dcc9', muted: '#98917e', blue: '#9db9a4',
      fill: '#3e4d43', tile: ['#30332a', '#262920'], seal: '#cf6a55',
      il1: '#b9b6a4', il2: '#cf6a55', ila: 0.18, patA: 0.1, rim: 0.24 },
    bg: ['#232520', '#f2ead9', '#f7f2e6', '#eeddc2', '#2c2e28', '#171814'],
    bg2: ['#2c2e28', '#e6e9d6', '#e9ecd9', '#e4d6bc', '#343730', '#1f211b'],
    kb: ['#8a6a3c', '#4a5c50', '#b8402f', '#7d6a4a', '#5a6b52', '#3a4049', '#9a7a4a', '#6e5a4b'],
  }),

  /* 女巫茶会：陈年纸上的铜版画。直角、粗黑框、不填底的图标，
     紫只在交互上——彩度全压在一处。入夜整张纸翻成深紫夜。 */
  witch: dlArt2({
    name: '女巫茶会', hint: '古董纸与铜版画', icons: 'witch', scene: 'witch', pat: 'stars',
    day: { card: '#f7efdb', line: '#cbb695', text: '#231b13', muted: '#7a6850', blue: '#5b4680',
      fill: '#4a3768', tile: ['#efe3c6', '#e3d4b0'],
      il1: '#2e2418', il2: '#6b5296', ila: 0.18, patA: 0.5, rim: 0.16 },
    night: { card: '#221b33', line: '#372c4e', text: '#ede2cd', muted: '#9b8ead', blue: '#c0a8e8',
      fill: '#4a3768', tile: ['#2a2240', '#1e1830'],
      il1: '#c9bda6', il2: '#a98fd8', ila: 0.2, patA: 0.8, rim: 0.22 },
    bg: ['#1b1622', '#ece0c8', '#f0e6d2', '#e6d0b0', '#241d2e', '#14101c'],
    bg2: ['#231c30', '#e3d6b9', '#e7dcc4', '#dcc4a2', '#2c2438', '#1b1626'],
    kb: ['#5b4680', '#7a4a3a', '#8a6a3c', '#3f5a6b', '#6b3a52', '#2e2418', '#4a6b5a', '#8a5a6b'],
  }),

  /* 像素蜜桃：圆角收成 0，边框靠四道位移阴影拼（那才是像素框，圆角画不出来）。
     白天蜜桃粉、入夜滑到荔枝冰——参考图本来就是同系列的暖冷两版，各占一头。 */
  pixel: dlArt2({
    name: '像素蜜桃', hint: '8-bit 甜点，日夜换味', icons: 'pixel', scene: 'pixel', pat: 'dots',
    day: { card: '#fffafb', line: '#f4c3cd', text: '#4e2530', muted: '#a3798a', blue: '#c02f52',
      fill: '#c02f52', tile: ['#ffe2e8', '#ffd0da'],
      il1: '#e88ca0', il2: '#f6c6a0', ila: 0.4, patA: 0.06, rim: 0 },
    night: { card: '#221c34', line: '#3a3054', text: '#e9e2f4', muted: '#9d92b8', blue: '#8fd0ea',
      fill: '#2f6f8f', tile: ['#2a2340', '#211b32'],
      il1: '#4d76a0', il2: '#7fa8c8', ila: 0.45, patA: 0.08, rim: 0 },
    bg: ['#211a2e', '#ffe7ec', '#fff1f3', '#ffd9dd', '#241d38', '#191428'],
    bg2: ['#2a2238', '#ffdde3', '#ffe6ea', '#ffcdd3', '#2c2442', '#211a30'],
    kb: ['#c02f52', '#e88ca0', '#f0a860', '#8fd0ea', '#7a5fb0', '#4e2530', '#d06a80', '#5f8fb0'],
  }),

  /* 炸物猫铺：2.2px 全黑描边 + 不带模糊的位移阴影，就是贴纸从纸上翘起来那一下。
     描边色走 line 变量，夜里整套翻成米白描边，不用为夜间另写一套。 */
  tempura: dlArt2({
    name: '炸物猫铺', hint: '厚描边贴纸，奶黄樱粉', icons: 'tempura', scene: 'tempura', pat: 'wave',
    day: { card: '#fffdf6', line: '#2a2420', text: '#2a2420', muted: '#8a7a63', blue: '#a8500e',
      fill: '#a8500e', tile: ['#ffd98f', '#f0be6a'],
      il1: '#3a3128', il2: '#f0b445', ila: 0.28, patA: 0.1, rim: 0 },
    night: { card: '#241f18', line: '#f3e2c0', text: '#f6ecd8', muted: '#a2937b', blue: '#f0a94b',
      fill: '#a8500e', tile: ['#5a3d16', '#432d10'],
      il1: '#c9b696', il2: '#e0973a', ila: 0.3, patA: 0.1, rim: 0 },
    bg: ['#221d18', '#fff3dc', '#fff8e8', '#ffe2b8', '#2a231b', '#191411'],
    bg2: ['#2a231b', '#ffe9c2', '#ffefd0', '#ffd8a4', '#332b21', '#211b15'],
    kb: ['#a8500e', '#f0b445', '#2f5d7a', '#c25a6a', '#7a9a4a', '#2a2420', '#d08a3a', '#6b4a2a'],
  }),

  /* 家庭菜园：格纹桌布 + 缎带。红绿分工死——绿是交互和完成，红是数字和强调，
     番茄红从不做按钮底（会被读成危险），也从不单独承载信息（对色弱友好）。 */
  garden: dlArt2({
    name: '家庭菜园', hint: '水彩格纹，番茄与嫩绿', icons: 'garden', scene: 'garden', pat: 'gingham',
    day: { card: '#fffefa', line: '#dae3c6', text: '#252d1e', muted: '#7c8a6b', blue: '#4a6c2e',
      fill: '#44622b', tile: ['#e6eed6', '#d6e0c0'], seal: '#d8483f',
      il1: '#6f8a52', il2: '#d8483f', ila: 0.28, patA: 0.13, rim: 0.16 },
    night: { card: '#1e2620', line: '#2f3a2b', text: '#e4ecda', muted: '#93a186', blue: '#a6cc7e',
      fill: '#44622b', tile: ['#283224', '#1f2a1c'], seal: '#c2564a',
      il1: '#7f9a62', il2: '#c2564a', ila: 0.32, patA: 0.1, rim: 0.2 },
    bg: ['#1c221b', '#f3f6e8', '#f8faf0', '#f6e6cf', '#232a20', '#141a14'],
    bg2: ['#232b20', '#eaf0dc', '#eff4e2', '#eedcc2', '#2b3327', '#1c231b'],
    kb: ['#d8483f', '#4a6c2e', '#c9a227', '#7fa650', '#a1512c', '#3f5a3a', '#c2564a', '#6b8a4a'],
  }),

  /* ---- 以下五套只在电脑端出现（desk: 1）：横构图、靠边框和密度，不靠大色块 ---- */

  // 御前案头：胶带竖起来当装订边，稿纸行线铺满正文（手机上行高挤，铺不了）
  meowdesk: dlArt2({
    name: '御前案头', hint: '装订边与稿纸行线', icons: 'meow', scene: 'meow', pat: 'tape',
    desk: 1, patS: 1.3,
    day: { card: '#fffdf7', line: '#e0d8c3', text: '#262421', muted: '#857c6c', blue: '#46564a',
      fill: '#3b4a40', tile: ['#e2e6d2', '#d4dac0'], seal: '#b8402f',
      il1: '#6b6a62', il2: '#b8402f', ila: 0.22, patA: 0.13, rim: 0.2 },
    night: { card: '#21231d', line: '#323328', text: '#e2dbc8', muted: '#96907d', blue: '#9cb8a3',
      fill: '#3b4a40', tile: ['#2c2f26', '#23261e'], seal: '#cf6a55',
      il1: '#b9b6a4', il2: '#cf6a55', ila: 0.18, patA: 0.09, rim: 0.24 },
    bg: ['#212320', '#f0e9d8', '#f5f1e6', '#ecdcc2', '#2a2c26', '#161713'],
    bg2: ['#282a24', '#e6e9d6', '#e9ecd9', '#e2d5bb', '#31342c', '#1e201a'],
    kb: ['#8a6a3c', '#46564a', '#b8402f', '#7d6a4a', '#5a6b52', '#3a4049', '#9a7a4a', '#6e5a4b'],
  }),

  // 女巫账房：整扇窗是一版报纸 —— 参考图那张排版本身就是宽的，密排比等分更像它
  witchdesk: dlArt2({
    name: '女巫账房', hint: '一整版铜版画', icons: 'witch', scene: 'witch', pat: 'stars',
    desk: 1, patS: 1.4,
    day: { card: '#f7f0dd', line: '#c8b18d', text: '#201810', muted: '#786649', blue: '#56417a',
      fill: '#453462', tile: ['#eee2c4', '#e0d0ac'],
      il1: '#2e2418', il2: '#6b5296', ila: 0.18, patA: 0.45, rim: 0.16 },
    night: { card: '#211a31', line: '#3a2f52', text: '#ece1cb', muted: '#998ba9', blue: '#bda4e6',
      fill: '#453462', tile: ['#291f3e', '#1d172e'],
      il1: '#c9bda6', il2: '#a98fd8', ila: 0.2, patA: 0.75, rim: 0.22 },
    bg: ['#191322', '#e7dbc0', '#eadfc7', '#e0c8a6', '#221b31', '#120e1c'],
    bg2: ['#221a2f', '#e0d2b2', '#e3d6ba', '#d6bc98', '#2a2140', '#1a1428'],
    kb: ['#56417a', '#7a4a3a', '#8a6a3c', '#3f5a6b', '#6b3a52', '#2e2418', '#4a6b5a', '#8a5a6b'],
  }),

  // 像素工位：粉压掉一档（铺满 27 寸会腻），粉只留在描边、标题栏那条杠和选中项上
  pixeldesk: dlArt2({
    name: '像素工位', hint: '8-bit 窗口与扫描线', icons: 'pixel', scene: 'pixel', pat: 'dots',
    desk: 1, patS: 1,
    day: { card: '#fffcfd', line: '#e9c9d2', text: '#3f2530', muted: '#96788a', blue: '#b32b4c',
      fill: '#b32b4c', tile: ['#f9dde3', '#f2ccd6'],
      il1: '#e6a0b0', il2: '#f2c39e', ila: 0.38, patA: 0.05, rim: 0 },
    night: { card: '#201a32', line: '#382e52', text: '#e8e1f3', muted: '#9a8fb6', blue: '#7fc7e6',
      fill: '#2c6a89', tile: ['#28213c', '#1d1830'],
      il1: '#4a7296', il2: '#7ba4c4', ila: 0.42, patA: 0.07, rim: 0 },
    bg: ['#1e1830', '#f8e9ec', '#f6edef', '#f7dbe0', '#231c36', '#171327'],
    bg2: ['#261e3a', '#f7dce2', '#f2e2e6', '#f3cfd6', '#2b2340', '#1e1832'],
    kb: ['#b32b4c', '#e6a0b0', '#e09a5a', '#7fc7e6', '#7059a0', '#3f2530', '#c46076', '#5586a6'],
  }),

  /* 猫铺暖帘：顶栏是一整幅靛蓝暖帘。靛是电脑端才加的一支色——宽屏需要一块深色
     压住整面奶黄，不然大面积暖色发飘（和「卷宗」用封条压牛皮是同一个道理）。 */
  tempuradesk: dlArt2({
    name: '猫铺暖帘', hint: '顶栏是一幅暖帘', icons: 'tempura', scene: 'tempura', pat: 'wave',
    desk: 1, patS: 1.15,
    day: { card: '#fffdf7', line: '#2a2420', text: '#2a2420', muted: '#877860', blue: '#9c4a0c',
      fill: '#9c4a0c', tile: ['#ffd98f', '#efbc66'], band: '#2f5d7a',
      il1: '#3a3128', il2: '#e8a63c', ila: 0.28, patA: 0.09, rim: 0 },
    night: { card: '#231e17', line: '#f0dfbd', text: '#f5ebd7', muted: '#a09178', blue: '#eea748',
      fill: '#9c4a0c', tile: ['#573b15', '#402b0f'], band: '#24485e',
      il1: '#c9b696', il2: '#e0973a', ila: 0.3, patA: 0.09, rim: 0 },
    bg: ['#201b16', '#fdf1d9', '#fdf4e1', '#fbdfb4', '#28211a', '#181410'],
    bg2: ['#282119', '#ffe9c4', '#ffedd0', '#f7d6a2', '#312820', '#201a14'],
    kb: ['#9c4a0c', '#e8a63c', '#2f5d7a', '#c25a6a', '#7a9a4a', '#2a2420', '#d08a3a', '#6b4a2a'],
  }),

  // 苗圃工作台：格子放大到 15px —— 格纹的观感取决于视距，手机那个数搬上大屏会像摩尔纹
  gardendesk: dlArt2({
    name: '苗圃工作台', hint: '桌布格纹与营养圆标', icons: 'garden', scene: 'garden', pat: 'gingham',
    desk: 1, patS: 1.15,
    day: { card: '#fffefb', line: '#dce4c8', text: '#232a1d', muted: '#79876a', blue: '#47692c',
      fill: '#41602a', tile: ['#e5edd4', '#d5dfbe'], seal: '#d4453c',
      il1: '#6f8a52', il2: '#d4453c', ila: 0.28, patA: 0.11, rim: 0.16 },
    night: { card: '#1d251f', line: '#2e392a', text: '#e3ebd9', muted: '#91a085', blue: '#a4cb7c',
      fill: '#41602a', tile: ['#273123', '#1e291b'], seal: '#c2564a',
      il1: '#7f9a62', il2: '#c2564a', ila: 0.32, patA: 0.09, rim: 0.2 },
    bg: ['#1a201a', '#f2f6e9', '#f6f9ef', '#f5e6d0', '#212820', '#131914'],
    bg2: ['#212a1f', '#e9efdb', '#edf2e0', '#ecdcc0', '#2a3226', '#1b221a'],
    kb: ['#d4453c', '#47692c', '#c9a227', '#7fa650', '#a1512c', '#3f5a3a', '#c2564a', '#6b8a4a'],
  }),
};

/* 颜色解析要同时吃 '#rrggbb' 和 'rgb(r,g,b)'：插值出来的是后者，
   而节气色还要拿插值结果再去和固定的十六进制底色掺一次。 */
function dlRGB(c) {
  if (c.charAt(0) === '#') return dlHex(c);
  const m = c.match(/-?\d+(\.\d+)?/g) || [0, 0, 0];
  return [+m[0], +m[1], +m[2]];
}
function dlMixR(a, b, t) {
  const x = dlRGB(a), y = dlRGB(b);
  return 'rgb(' + x.map((v, i) => Math.round(v + (y[i] - v) * t)).join(',') + ')';
}
/* 加透明度。**主题里一律用这个，不要用上面的 dlRgba** —— 那个只会把 'rgb(' 换成 'rgba('，
   喂给它一个 '#rrggbb' 它什么都不做、也不报错，透明度就这么静默地丢了。
   而 DL_ART_SNAP 里那些字段（ink / card / tile …）恰恰是硬翻的，留着十六进制。
   踩过一次：界格和远山本该是 5%/10% 的淡痕，结果满屏骨白横条加一团大光斑。 */
const dlAlpha = (c, a) => 'rgba(' + dlRGB(c).join(',') + ',' + a + ')';

/* 这些字段**不插值，到点直接翻**（和 dlAt 里 ink/sub 用 t<0.5 硬切是同一个道理）。

   为什么必须这样：晨昏两段是「暗环境 → 亮环境」。底色由深走浅、字色由浅走深，
   两条线在中间交叉 —— 那一段卡片是中灰、字也是中灰，正文直接看不见。
   6:00 那一版就是这么糊的（渲出来才发现，四套主题全中）。

   分界线画在「读字的那一面」和「远处的气氛」之间：
     · 卡片底、字色、描边、强调色、玻璃浓度 —— 决定能不能读，一起翻，永远配套
     · 壁纸、天光、山色、掺色 —— 只是气氛，继续连续地滑，一天里看不出台阶
   所以远处仍然是渐变的，近处永远是清楚的。 */
const DL_ART_SNAP = ['card', 'line', 'text', 'muted', 'blue', 'fill',
  'tile', 'ink', 'blk', 'glyph', 'ga', 'gb', 'gc'];

/* 任意时刻取一套主题值。逐字段按类型插：数组照元素来，字符串当颜色掺，数字线性。
   跨零点和 dlAt 是同一个坑、同一个解法（最后一个锚点的下一个是第一个，跨度 +24）。 */
function dlArtAt(mode, h) {
  const T = DL_ART[mode];
  if (!T) return null;
  h = ((h % 24) + 24) % 24;
  let i = DL_ART_HRS.length - 1;
  for (let k = 0; k < DL_ART_HRS.length; k++) if (h >= DL_ART_HRS[k]) i = k;
  const j = (i + 1) % DL_ART_HRS.length;
  const span = ((DL_ART_HRS[j] - DL_ART_HRS[i]) + 24) % 24 || 24;
  const t = Math.min(1, Math.max(0, (((h - DL_ART_HRS[i]) + 24) % 24) / span));
  const a = T.keys[i], b = T.keys[j], out = {};
  for (const k in a) {
    const va = a[k], vb = b[k];
    if (DL_ART_SNAP.indexOf(k) >= 0) { out[k] = t < 0.5 ? va : vb; continue; }
    if (Array.isArray(va)) out[k] = va.map((v, n) => typeof v === 'string' ? dlMixR(v, vb[n], t) : dlNum(v, vb[n], t));
    else if (typeof va === 'string') out[k] = dlMixR(va, vb, t);
    else out[k] = dlNum(va, vb, t);
  }
  return out;
}

/* 当前该用哪套主题 / 要不要跟着时刻走。
   **只用原生 localStorage**：core.js 的 lsGet 这会儿还不存在（本文件是第一个脚本）。 */
function dlLs(k, d) {
  try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (_) { return d; }
}
/* 当前该用哪套。除了"这个名字存在"，还要问"它属于这一端吗"：
   同步/导入把另一端的选择带过来时，宁可退回默认，也不要让一套没有 CSS 的主题挂上去。 */
function dlArtMode() {
  const m = dlLs(dlArtKey(), ''), T = DL_ART[m];
  return (T && !!T.desk === dlIsDesk()) ? m : '';
}

/* ================= 默认外观也跟着天光走（M4）=================
   这套按时刻取色的东西一直只服务启动屏和登录页；越过登录之后，除非你主动去
   「外观」里挑一套美术主题，界面就是一张没有立场的白纸。工具造好了，没接到主路上。

   这里把它接上，但**幅度压到几乎看不见**：饱和度 2–4%，只动页面底色和卡片底，
   字色、品牌蓝、语义色一律不碰。效果是「这个应用记得现在几点」，
   而不是「界面在变色」—— 后者会干扰读题。

   三条边界：
   · 开了美术主题 → 什么都不做。那时颜色归主题管，两套插值打架就成了泥。
   · 夜间 → 什么都不做。夜色本身就是「夜」这一档，再压一层暖调只会发脏。
   · 用户关掉（外观 › 跟随天光）→ 清干净，回到写死的 #f4f6f9。

   底色和卡片底的每一档都验过对比度：--muted 压上去最低 5.04:1、正文 15.66:1，
   都在 AA 之上（验算见 tests/frontend/cssbudget.test.js 那条 --muted 断言的同一套算法）。 */
const DL_TINT = [
  { h: 5, bg: '#f1f4f9', card: '#ffffff' },   // 拂晓：偏冷青
  { h: 8, bg: '#f3f5f8', card: '#ffffff' },   // 晨
  { h: 13, bg: '#f4f6f9', card: '#ffffff' },  // 昼：就是原来那个值，正午不偏
  { h: 17, bg: '#f7f5f1', card: '#fffefc' },  // 午后：一丝暖
  { h: 19, bg: '#f8f3ec', card: '#fffdf9' },  // 昏：全天最暖的一档
  { h: 21, bg: '#f4f2f3', card: '#fffeff' },  // 暮：暖退回中性
  { h: 23, bg: '#f0f2f7', card: '#ffffff' },  // 夜：转冷
];
function dlTintAt(h) {
  h = ((h % 24) + 24) % 24;
  let i = DL_TINT.length - 1;
  for (let k = 0; k < DL_TINT.length; k++) if (h >= DL_TINT[k].h) i = k;
  const a = DL_TINT[i], b = DL_TINT[(i + 1) % DL_TINT.length];
  const span = ((b.h - a.h) + 24) % 24 || 24;
  const t = Math.min(1, Math.max(0, (((h - a.h) + 24) % 24) / span));
  return { bg: dlMix(a.bg, b.bg, t), card: dlMix(a.card, b.card, t) };
}
function dlTintOn() { return dlLs('dayTint', '1') !== '0'; }
/* 写在 **:root** 上，不是 body 上 —— 这一层要和美术主题分开：
     · 美术主题写 body 的 inline 变量（dlArtApply），
     · 天光底写 :root 的 inline 变量。
   body 比 :root 离用到变量的元素更近，所以主题一开就自然盖过天光，
   两边不用互相判断、也不用抢着清对方的痕迹。夜间同理：body.dark 那条 CSS 规则
   本来就重定义了 --bg / --card，压在 :root 的 inline 值之上。
   （早先写在 body 上，结果和「换回默认要把痕迹清干净」那条测试打架 —— 那条测试
   守的是真出过的 bug：主题关不掉。分层之后两件事各归各的。） */
function dlTintApply() {
  const r = document.documentElement;
  if (!r || !document.body) return;
  const off = !dlTintOn() || dlArtMode() || document.body.classList.contains('dark');
  if (off) {
    r.style.removeProperty('--bg');
    r.style.removeProperty('--card');
    document.body.classList.remove('day-tint');
    return;
  }
  const v = dlTintAt(dlNow());
  r.style.setProperty('--bg', v.bg);
  r.style.setProperty('--card', v.card);
  document.body.classList.add('day-tint');
}
window.dlTintApply = dlTintApply;
window.dlTintOn = dlTintOn;

/* 图标风格：'line'（默认，描边 SVG）/ 'emoji'（平台彩色字形）。
   和主题**分开记**：这两套字形本来就都在 DOM 里（.em-sw），以前露哪一套却绑在
   「有没有开美术主题」上，等于想要一套统一的单色图标就得连配色一起换。
   放在 daylight.js 而不是 theme.js：theme.js 是后面才加载的，晚一拍就是
   满屏 emoji 闪一下再变成线条。 */
function dlIconsApply() {
  if (!document.body) return;
  document.body.classList.toggle('icons-emoji', dlLs('icons', 'line') === 'emoji');
}
window.dlIconsApply = dlIconsApply;
function dlArtClock() { return dlLs('artClock', '1') !== '0'; }

/* 主题该按哪个时刻取色：
   跟着天光走 → 此刻；关掉了 → 由「日间/夜间/跟随系统」挑一头，白昼 13:00 或夜 23:00。
   关掉之后主题就是一套静态配色，这是给「喜欢这个调子但不想让界面自己变」的人留的。 */
function dlArtHour() {
  if (dlArtClock()) return dlNow();
  const mode = dlLs('theme', 'auto');
  const dark = mode === 'dark' || (mode === 'auto' && (
    typeof window.__sysDark === 'boolean' ? window.__sysDark
      : !!(window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches)));
  return dark ? 23 : 13;
}

/* 主题开着时，日/夜由天光说了算，theme.js 的 applyTheme 会来问这一句。
   没开主题、或没开跟随时刻时返回 null = 「我不管，你按原来的来」。 */
function dlArtDark() {
  const mode = dlArtMode();
  if (!mode) return null;
  /* 只有一档的主题（夜航）**不交还决定权**，哪怕"跟随天光"是关着的：
     它的变量把界面刷成了夜色，body.dark 要是没跟上，那一批写死深色的规则
     （顶栏、左栏、代码块…）就会留在浅色态 —— 半亮半暗的一屏。 */
  if (!DL_ART[mode].fixed && !dlArtClock()) return null;
  const v = dlArtAt(mode, dlNow());
  return !!(v && v.dark > 0.5);
}

/* ---------------- 第二代主题的卡通场景 ----------------
   五幅画，每种画风一幅：葫芦上的官帽猫 / 茶杯里的小女巫 / 像素蜜桃 / 端炸物的三花猫 / 番茄篮。

   **不进 DOM**：#art-wall 是一张常驻的 fixed 底图，多一层 DOM 元素就多一个常驻合成层。
   写成 SVG data URI 当背景图，位置和大小交给 background-position/size，
   浏览器按需栅格化，滚动时一帧不掉。

   两支色：a 是主线（跟当前时刻的字色走），b 是强调（朱 / 紫 / 桃 / 金 / 番茄）。
   浓度不写在颜色里，写在 <svg opacity> 上 —— 颜色要参与插值，浓度不要。 */
const DL_SCENE_VB = {
  meow: '0 0 120 130', witch: '0 0 130 120', pixel: '0 0 130 120',
  tempura: '0 0 130 120', garden: '0 0 130 120',
  paper: '0 0 130 100', glass: '0 0 130 100', hue: '0 0 130 100', celadon: '0 0 130 100',
  dossier: '0 0 130 100', night: '0 0 130 100', studio: '0 0 130 100',
};
const DL_SCENE = {
  // 挂在葫芦上的官帽猫 + 兰草 + 铜钱串 + 雀足印
  meow: (a, b) => `<g stroke='${a}'>`
    + `<path d='M74 2v10'/>`
    + `<path d='M74 12c-5.6 0-8.8 5-6.2 9.4 1.8 3 1.4 5-1.4 7.6-4.8 4.4-7.2 8.4-7.2 13.6 0 4.6 2.6 8 5.8 10.8-6.8 5-11.2 12.2-11.2 21C53.8 87 62.6 96.4 74 96.4S94.2 87 94.2 74.4c0-8.8-4.4-16-11.2-21 3.2-2.8 5.8-6.2 5.8-10.8 0-5.2-2.4-9.2-7.2-13.6-2.8-2.6-3.2-4.6-1.4-7.6C82.8 17 79.6 12 74 12z'/>`
    + `<path d='M20 60l2.4-11 8.4 5.4'/><path d='M53 60l-2.4-11-8.4 5.4'/>`
    + `<ellipse cx='36.5' cy='68' rx='17' ry='14.6'/>`
    + `<path d='M29.5 65.6h.01M43.5 65.6h.01'/><path d='M32.6 72.4c2.6 2 5.2 2 7.8 0'/>`
    + `<path d='M17 66.4H8M17 70.4H8M56 66.4h9M56 70.4h9'/>`
    + `<path d='M24 48.6h25v5.4H24z'/><path d='M20.6 48.6h32'/>`
    + `<path d='M4 106c6-3 9.6-9 10.8-18M12 108c3.6-5.4 4.8-12.6 3.6-21'/>`
    + `<path d='M100 104l3 3.6 3-3.6M100 112l3 3.6 3-3.6M92 108l3 3.6 3-3.6'/></g>`
    + `<g stroke='${b}'><circle cx='103' cy='46' r='6'/><path d='M100.6 43.6h4.8v4.8h-4.8z'/>`
    + `<circle cx='103' cy='60' r='6'/><path d='M100.6 57.6h4.8v4.8h-4.8z'/>`
    + `<path d='M103 40v-6'/><path d='M74 96.4v10l-5 8h10z'/></g>`,
  // 茶杯里的小女巫 + 黑猫 + 星
  witch: (a, b) => `<g stroke='${a}'>`
    + `<path d='M22 56h62l-4.6 30.4A13 13 0 0 1 66.6 97H39.4a13 13 0 0 1-12.8-10.6z'/>`
    + `<path d='M84 62h5.4a11.6 11.6 0 0 1 0 23.2h-3.4'/><path d='M14 104h78'/>`
    + `<path d='M53 24L42.6 52h20.8z'/><path d='M35 52h36'/><circle cx='53' cy='60' r='6.6'/>`
    + `<path d='M45 78c0-4.6 3.6-8 8-8s8 3.4 8 8'/>`
    + `<path d='M100 74c0-6 3-9 3-9l-1.6-7.4 5 4.2h6.2l5-4.2L116 65s3 3 3 9v6a9.6 9.6 0 0 1-19 0z'/>`
    + `<path d='M119 84c5 1.6 8-2.4 5.6-6.4'/><path d='M105.6 68.4h.01M113.4 68.4h.01'/></g>`
    + `<g stroke='${b}'><path d='M100 20l1.6 4 4 1.6-4 1.6-1.6 4-1.6-4-4-1.6 4-1.6z'/>`
    + `<path d='M22 16l1.2 3 3 1.2-3 1.2-1.2 3-1.2-3-3-1.2 3-1.2z'/>`
    + `<path d='M78 30l1.2 3 3 1.2-3 1.2-1.2 3-1.2-3-3-1.2 3-1.2z'/>`
    + `<path d='M14 76l1.2 3 3 1.2-3 1.2L14 84.4l-1.2-3-3-1.2 3-1.2z'/>`
    + `<path d='M53 66.6c2.6 1.2 5 1.2 7 0'/></g>`,
  // 像素蜜桃 + 冰棒 + 汽水瓶 + 四角闪。纯色块，一条描边都不要
  pixel: (a, b) => `<g fill='${a}' stroke='none'>`
    + `<path d='M62 26h8v8h-8z'/><path d='M70 18h10v8H70z'/>`
    + `<path d='M46 42h34v8H46zM38 50h50v8H38zM30 58h66v26H30zM38 84h50v8H38zM46 92h34v8H46z'/>`
    + `<path d='M6 92h6v6H6zM12 86h6v6h-6zM18 92h6v6h-6zM12 98h6v6h-6z'/>`
    + `<path d='M104 92h6v6h-6zM110 86h6v6h-6zM116 92h6v6h-6zM110 98h6v6h-6z'/></g>`
    + `<g fill='${b}' stroke='none'><path d='M8 20h20v34H8z'/><path d='M14 54h8v22h-8z'/>`
    + `<path d='M104 16h14v8h-14zM100 24h22v8h-22zM104 32h14v46h-14z'/></g>`,
  // 端着天妇罗的三花猫 + 炸虾 + 柠檬 + 青海波
  tempura: (a, b) => `<g stroke='${a}'>`
    + `<path d='M26 44l2.6-14.6 10.4 7.6h8L57.4 29.4 60 44v6.6a17 17 0 0 1-34 0z'/>`
    + `<path d='M37 46.6h.01M49 46.6h.01'/><path d='M40 53.4c1.8 1.6 4.2 1.6 6 0'/>`
    + `<path d='M22 47h-9M22 51h-9M64 47h9M64 51h9'/>`
    + `<path d='M16 84h98a12 12 0 0 1-12 10H28a12 12 0 0 1-12-10z'/><path d='M8 84h114'/>`
    + `<path d='M2 110c0-8 6-14 14-14s14 6 14 14M30 110c0-8 6-14 14-14s14 6 14 14'/></g>`
    + `<g stroke='${b}'><path d='M74 60c-10 0-18 7-18 15 0 5 4 9 9 9h4'/>`
    + `<path d='M74 60c6 0 10 3 10 7s-4 7-10 7'/><path d='M86 58l8-6M90 64l10-2'/>`
    + `<circle cx='112' cy='62' r='11'/>`
    + `<path d='M112 51v22M101 62h22M104.2 54.2l15.6 15.6M119.8 54.2l-15.6 15.6'/></g>`,
  // 一篮刚摘的番茄 + 藤叶 + 打蛋器
  garden: (a, b) => `<g stroke='${a}'>`
    + `<path d='M22 64h72l-7.4 38H29.4z'/><path d='M40 64a17 17 0 0 1 36 0'/>`
    + `<path d='M24.6 76h66.8M27 88h62'/>`
    + `<path d='M6 40c14 0 20 8 20 18M6 40c0 8 5 13 13 14'/>`
    + `<path d='M112 30c-12 2-17 9-16 18M112 30c1 8-3 13-10 15'/>`
    + `<path d='M100 62v34'/><path d='M96 62c-3-6-1-11 4-13 5 2 7 7 4 13z'/>`
    + `<path d='M100 70c4-3 9-2 11 2'/></g>`
    + `<g stroke='${b}'><circle cx='44' cy='46' r='13'/><path d='M44 33v-5'/>`
    + `<path d='M37 34.6c2.6-3.4 5.2-3.4 7-.8 1.8-2.6 4.4-2.6 7 .8'/>`
    + `<circle cx='72' cy='52' r='9'/><path d='M72 43v-4'/>`
    + `<path d='M67 44c2-2.4 3.6-2.4 5-.6 1.4-1.8 3-1.8 5 .6'/>`
    + `<circle cx='88' cy='36' r='6'/><path d='M88 30v-3'/></g>`,

  /* ---- 现有那七套的画。墨山不在这儿：它的五重山本来就是 canvas 画的，
     背景图会被那张 canvas 整个盖住，所以那一笔孤舟直接画进 dlArtInk。 ---- */
  // paper：远山 · 一枝墨梅 · 印泥盒与一枚圆印（朱只在印上）
  paper: (a, b) => `<g fill='none' stroke='${a}' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'> <path d='M4 62c10-9 17-4 25-12 9-9 17 3 26-5 8-7 15 5 24-2 6-5 12 0 17-3'/> <path d='M4 74c12-7 20-2 30-8 10-6 18 4 28-2 9-5 16 3 24-1 5-3 9 0 10-1'/> <path d='M22 96c6-16 10-28 9-44'/><path d='M31 60c-4 6-9 8-14 7 2-6 7-9 14-7z'/> <path d='M31 48c-5 5-10 6-15 4 3-6 9-7 15-4z'/><path d='M31 70c5 4 7 9 6 14-5-2-8-7-6-14z'/> <circle cx='27' cy='41' r='3'/><circle cx='38' cy='55' r='2.4'/><circle cx='24' cy='68' r='2.4'/> <path d='M96 96h22v-4H96z'/><path d='M99 92V78h16v14'/><path d='M99 84h16'/> </g><g fill='none' stroke='${b}' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'> <rect x='72' y='66' width='17' height='24' rx='1.4'/><path d='M76 71h9M76 76h9M76 81h6'/> <circle cx='107' cy='60' r='7'/><path d='M104 57h6v6h-6z'/> </g>`,
  // glass：日轮 · 两重层云 · 远处的波
  glass: (a, b) => `<g fill='none' stroke='${a}' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'> <circle cx='94' cy='30' r='15'/><path d='M94 6v6M94 48v6M118 30h-6M76 30h-6M111 13l-4.2 4.2M77 47l4.2-4.2M111 47l-4.2-4.2M77 13l4.2 4.2'/> <path d='M18 72a11 11 0 0 1-1.2-22 16 16 0 0 1 30.4-4 9.4 9.4 0 0 1-1.6 26z'/> <path d='M62 88a8 8 0 0 1-.8-16 11.6 11.6 0 0 1 22-2.8 6.8 6.8 0 0 1-1.2 18.8z'/> <path d='M96 62c3-3 6-3 9 0 3-3 6-3 9 0'/><path d='M100 72c3-3 6-3 9 0 3-3 6-3 9 0'/> </g>`,
  // hue：二十四节气盘 · 一株苗 · 一朵花
  hue: (a, b) => `<g fill='none' stroke='${a}' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'> <circle cx='66' cy='48' r='34'/><circle cx='66' cy='48' r='26'/> <path d='M66 14v6M66 76v6M32 48h6M94 48h6M42 24l4.2 4.2M85.8 67.8l4.2 4.2M90 24l-4.2 4.2M46.2 67.8L42 72'/> <path d='M66 48l0-18M66 48l13 8'/> <path d='M14 94V70'/><path d='M14 70c-3.4 0-5.6-2.2-5.6-5.6S10.6 58.8 14 58.8s5.6 2.2 5.6 5.6S17.4 70 14 70z'/> <path d='M14 78c-4 0-6.6-2-6.6-5M14 78c4 0 6.6-2 6.6-5M14 86c-4.6 0-7.4-2.2-7.4-5.4M14 86c4.6 0 7.4-2.2 7.4-5.4'/> <circle cx='114' cy='76' r='4'/> <path d='M114 72c0-4.4 2-6.8 6-6.8 0 4.4-2 6.8-6 6.8zM118 76c4.4 0 6.8 2 6.8 6-4.4 0-6.8-2-6.8-6zM114 80c0 4.4-2 6.8-6 6.8 0-4.4 2-6.8 6-6.8zM110 76c-4.4 0-6.8-2-6.8-6 4.4 0 6.8 2 6.8 6z'/> </g>`,
  // celadon：一只梅瓶 · 开片 · 一枝
  celadon: (a, b) => `<g fill='none' stroke='${a}' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'> <path d='M52 10h14v8c0 8 14 12 14 28 0 16-9 26-21 26S38 62 38 46c0-16 14-20 14-28z'/> <path d='M40 44h38'/><path d='M42 60c8 5 26 5 34 0'/> <path d='M46 26c-6 6-8 12-8 18M74 30c4 5 6 10 6 16'/> <path d='M96 90c8-14 12-26 10-40'/><path d='M104 56c-4 5-9 6-14 4 3-6 8-7 14-4z'/> <path d='M106 68c5 3 7 8 5 13-5-2-7-7-5-13z'/><circle cx='102' cy='46' r='3'/> <path d='M14 88c6-4 8-10 6-16'/><path d='M8 74c4 2 7 6 6 10'/> </g>`,
  // dossier：档案盒 · 立柜 · 骑缝朱印 · 回形针
  dossier: (a, b) => `<g fill='none' stroke='${a}' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'> <rect x='12' y='42' width='60' height='46' rx='3'/><path d='M12 56h60'/><path d='M34 42V32h16v10'/> <path d='M24 68h14M24 76h20'/> <path d='M84 30h34v58H84z'/><path d='M84 44h34M84 58h34M84 72h34'/> <path d='M96 22l10 8-10 8z'/> <path d='M60 14c-6 0-9 4-9 8s3 7 7 7 6-3 6-6-2-5-5-5-4 2-4 4'/> </g><g fill='none' stroke='${b}' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'> <circle cx='72' cy='60' r='11'/><path d='M67 55h10v10H67z'/><path d='M72 55v10M67 60h10'/> </g>`,
  // night：灯塔 · 一艘船 · 星 · 夜里的浪（灯光也是青蓝，暖色一个不留）
  night: (a, b) => `<g fill='none' stroke='${a}' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'> <path d='M92 88V52h16v36z'/><path d='M90 52h20'/><path d='M94 52l4-14h4l4 14'/><path d='M96 38h8'/><path d='M97 30h6v8h-6z'/> <path d='M97 34h-14M103 34h14M98 29l-10-7M102 29l10-7'/> <path d='M20 82h34l-4 7H24z'/><path d='M37 82V56'/><path d='M37 58l14 10-14 5z'/><path d='M37 58L26 68l11 4z'/> <path d='M2 92c6-3 10 3 16 0s10 3 16 0 10 3 16 0 10 3 16 0 10 3 16 0 10 3 16 0 10 3 16 0'/> <path d='M18 20l1.4 3.6 3.6 1.4-3.6 1.4L18 30l-1.4-3.6L13 25l3.6-1.4z'/> <path d='M62 14l1 2.6 2.6 1-2.6 1-1 2.6-1-2.6-2.6-1 2.6-1z'/> <circle cx='44' cy='34' r='1.6'/><circle cx='76' cy='42' r='1.4'/><circle cx='10' cy='52' r='1.4'/> </g>`,
  // studio：一条基线 · 一个方块 · 一支笔 —— 那条线就是顶栏底边的位置
  studio: (a, b) => `<g fill='none' stroke='${a}' stroke-width='1.6' stroke-linecap='square'> <path d='M6 62h118'/><rect x='26' y='34' width='26' height='26'/> <path d='M76 60L96 40'/><path d='M76 60v-7h7'/> <circle cx='112' cy='28' r='7'/> </g>`,
};
function dlSceneUrl(name, v) {
  const f = DL_SCENE[name];
  if (!f) return '';
  const s = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='${DL_SCENE_VB[name]}' fill='none'`
    + ` stroke-width='2' stroke-linecap='round' stroke-linejoin='round'`
    + ` opacity='${(v.ila || 0.22).toFixed(3)}'>${f(v.il1, v.il2)}</svg>`;
  return `url("data:image/svg+xml,${encodeURIComponent(s)}")`;
}

/* 材质层。五种画风各一种，返回 {img,size,pos,rep} —— 因为青海波和格纹要自己的
   tile 尺寸，光给 background-image 是不够的，四条 longhand 得按同一个次序对齐。 */
function dlPatLayers(pat, v, s) {
  const A = v.patA || 0.12, ink = v.ink || v.text;
  const tile = (img, size) => ({ img, size, pos: '0 0', rep: 'repeat' });
  if (pat === 'tape') {
    // 稿纸行线：整幅纸的呼吸，胶带那条斜纹交给 CSS（它只压在顶栏和底栏上）
    return [tile(`repeating-linear-gradient(0deg,${dlAlpha(ink, A * 0.5)} 0 1px,transparent 1px ${(21 * s).toFixed(0)}px)`, 'auto')];
  }
  if (pat === 'stars') {
    const c = dlAlpha(v.il2, A * 0.5), d = dlAlpha(ink, A * 0.4);
    return [
      { img: `radial-gradient(1.4px 1.4px at 24% 22%,${d},transparent)`, size: `${(120 * s).toFixed(0)}px ${(140 * s).toFixed(0)}px`, pos: '0 0', rep: 'repeat' },
      { img: `radial-gradient(1.6px 1.6px at 72% 58%,${c},transparent)`, size: `${(170 * s).toFixed(0)}px ${(190 * s).toFixed(0)}px`, pos: '0 0', rep: 'repeat' },
    ];
  }
  if (pat === 'dots') {
    const c = dlAlpha(v.blue, A);
    const p = (8 * s).toFixed(0);
    return [tile(`repeating-linear-gradient(0deg,${c} 0 2px,transparent 2px ${p}px),`
      + `repeating-linear-gradient(90deg,${c} 0 2px,transparent 2px ${p}px)`, 'auto')];
  }
  if (pat === 'wave') {
    // 青海波：一格一道弧，靠 background-size 铺开
    const c = dlAlpha(v.il2, A * 1.4);
    return [tile(`repeating-radial-gradient(circle at 50% 100%,transparent 0 9px,${c} 9px 10.5px,transparent 10.5px 20px)`,
      `${(34 * s).toFixed(0)}px ${(22 * s).toFixed(0)}px`)];
  }
  // gingham：格纹桌布。密度按视距给（手机 13px、电脑 15px，patS 说了算）
  const g = dlAlpha(v.il1, A);
  const w = Math.round(13 * s), w2 = w * 2;
  return [tile(`repeating-linear-gradient(90deg,${g} 0 ${w}px,transparent ${w}px ${w2}px),`
    + `repeating-linear-gradient(0deg,${g} 0 ${w}px,transparent ${w}px ${w2}px)`, 'auto')];
}

/* 把一摞层刷到某个元素上。四条 longhand 必须**同序等长**，
   少一个浏览器就会循环取用，青海波那格会跑到渐变身上去。 */
function dlLayers(el, arr) {
  el.style.backgroundImage = arr.map(x => x.img).join(',');
  el.style.backgroundSize = arr.map(x => x.size || 'auto').join(',');
  el.style.backgroundPosition = arr.map(x => x.pos || '0 0').join(',');
  el.style.backgroundRepeat = arr.map(x => x.rep || 'no-repeat').join(',');
}

/* 第二代主题的壁纸：底色渐变 + 一层材质 + 一幅卡通。
   十套共用这一条通道 —— 加第十一套只是多一张色表和一幅画，不用再来一个 else if。 */
function dlArtWall2(el, mode, v) {
  const T = DL_ART[mode];
  // 材质层自带 size（青海波和格纹要自己的 tile 尺寸），所以整个对象传下去
  const arr = dlPatLayers(T.pat, v, T.patS || 1);
  arr.push({ img: `linear-gradient(178deg,${v.wall[0]} 0%,${v.wall[1]} 54%,${v.wall[2]} 100%)`,
    size: 'cover', pos: '0 0', rep: 'no-repeat' });
  dlArtWallOut(el, mode, v, arr);     // 插画那一层由共用出口压上去，两代走同一段
  el.style.setProperty('--art-grain', '0');
}

/* 壁纸。paper/glass/hue 用多层 background-image 拼（够用且便宜）；
   ink 那五重山是曲线，拼不出来，单独用一张 canvas。 */
function dlArtWall(mode, v) {
  const el = document.getElementById('art-wall');
  if (!el) return;
  const cv = el.querySelector('canvas');
  if (mode !== 'ink' && cv) el.removeChild(cv);
  el.style.backgroundImage = '';
  el.style.background = '';   // 简写清掉的是全部 longhand，第二代那几条 size/position 也跟着走
  /* 各套先把自己那摞层**摆进 L**，最后统一交给 dlArtWallOut 铺 ——
     插画要压在最上面，而每一层的 size/position 必须同序等长，
     所以不能再像原来那样各自 join 完就写进 backgroundImage 了。 */
  let L = null;

  if (DL_ART[mode] && DL_ART[mode].art2) { dlArtWall2(el, mode, v); return; }

  if (mode === 'paper') {
    const grid = `repeating-linear-gradient(0deg,${dlAlpha(v.ink, v.grid)} 0 1px,transparent 1px 26px),`
      + `repeating-linear-gradient(90deg,${dlAlpha(v.ink, v.grid)} 0 1px,transparent 1px 26px)`;
    const hill = `radial-gradient(120% 30% at 22% 100%,${dlAlpha(v.ink, 0.10)} 0%,transparent 62%),`
      + `radial-gradient(90% 24% at 76% 104%,${dlAlpha(v.ink, 0.08)} 0%,transparent 66%)`;
    L = [grid, hill,
      `linear-gradient(178deg,${v.wall[0]} 0%,${v.wall[1]} 54%,${v.wall[2]} 100%)`];
    el.style.setProperty('--art-grain', String(v.grain * 0.6));
  } else if (mode === 'glass') {
    /* 日轮 5:00 东升 → 12:00 中天 → 19:00 西沉，之后换月，走同一条弧。
       连续算位置而不是分两态：下午三点太阳该在哪，得是有定义的。 */
    const h = dlArtHour(), day = (h >= 5 && h < 19);
    const q = day ? (h - 5) / 14 : (((h - 19) + 24) % 24) / 10;
    const x = (9 + 82 * q).toFixed(1), y = (76 - 60 * Math.sin(Math.PI * q)).toFixed(1);
    /* 月亮比太阳小一圈，也暗一档：满亮度的小白盘隔着毛玻璃会变成一个"亮点"，
       看着像脏了一块而不像天体。边要羽化，晕要铺得开，日月才立得住。 */
    const r = day ? 3.4 : 1.9;
    const disc = dlAlpha(v.orb, day ? 1 : 0.86);
    L = [
      `radial-gradient(circle at ${x}% ${y}%,${disc} 0 ${(r * 0.78).toFixed(2)}vmin,transparent ${(r * 1.25).toFixed(2)}vmin)`,
      `radial-gradient(circle at ${x}% ${y}%,${dlAlpha(v.orb, 0.26)} 0,transparent ${(r * 3).toFixed(1)}vmin)`,
      `radial-gradient(circle at ${x}% ${y}%,${dlAlpha(v.orb, 0.12)} 0,transparent ${(r * 7).toFixed(1)}vmin)`,
      `radial-gradient(130% 38% at 50% 104%,${v.sky[2]},transparent 70%)`,
      `linear-gradient(180deg,${v.sky[0]} 0%,${v.sky[1]} 52%,${v.sky[2]} 100%)`,
    ];
    el.style.setProperty('--art-grain', '0');
  } else if (mode === 'hue') {
    L = [
      `radial-gradient(78% 40% at 16% 6%,${dlAlpha(dlMixR(DL_HUES[1], v.tint, v.amt), 0.20)},transparent 66%)`,
      `radial-gradient(70% 38% at 88% 76%,${dlAlpha(dlMixR(DL_HUES[3], v.tint, v.amt), 0.20)},transparent 68%)`,
      `linear-gradient(178deg,${v.wall[0]} 0%,${v.wall[1]} 56%,${v.wall[2]} 100%)`,
    ];
    el.style.setProperty('--art-grain', String(v.weave * 0.16));
  } else if (mode === 'ink') {
    el.style.setProperty('--art-grain', '0');
    dlArtInk(el, v);
  } else if (mode === 'celadon') {
    /* 釉 + 极淡的开片。裂纹在壁纸上只留一层意思（两组斜线，3% 上下）——
       启动屏那张才是真画的开片，壁纸整天在正文底下，画细了只会变噪点。 */
    const cz = dlAlpha(v.crack, v.crackA * 0.06);
    L = [
      `repeating-linear-gradient(63deg,${cz} 0 1px,transparent 1px 148px)`,
      `repeating-linear-gradient(-27deg,${cz} 0 1px,transparent 1px 196px)`,
      `radial-gradient(88% 42% at 78% 8%,${dlAlpha(v.crack, v.crackA * 0.10)},transparent 68%)`,
      `linear-gradient(178deg,${v.wall[0]} 0%,${v.wall[1]} 54%,${v.wall[2]} 100%)`,
    ];
    el.style.setProperty('--art-grain', String(v.grain * 0.4));
  } else if (mode === 'dossier') {
    /* 稿纸格 + 左边那条装订带。格子 26px 和「宣纸与印」对齐 —— 同一个应用里
       两套纸不该是两种格距。装订带压在最左边 46px，正好落在左侧导航栏底下。 */
    const ln = dlAlpha(v.rule, v.grid);
    L = [
      `repeating-linear-gradient(0deg,${ln} 0 1px,transparent 1px 26px)`,
      `repeating-linear-gradient(90deg,${ln} 0 1px,transparent 1px 26px)`,
      `linear-gradient(90deg,${dlAlpha(v.rule, v.grid * 1.6)} 0 46px,transparent 46px)`,
      `linear-gradient(178deg,${v.wall[0]} 0%,${v.wall[1]} 54%,${v.wall[2]} 100%)`,
    ];
    el.style.setProperty('--art-grain', String(v.grain * 0.55));
  } else if (mode === 'night') {
    // 近黑 + 右上那盏灯的余光 + 几颗星。界面里的暖色仅此一处，且已经压到 6%
    L = [
      `radial-gradient(56% 46% at 88% 4%,${dlAlpha(v.lamp, v.lampA * 0.20)},transparent 70%)`,
      `radial-gradient(1.2px 1.2px at 18% 22%,rgba(255,255,255,.28),transparent)`,
      `radial-gradient(1.1px 1.1px at 72% 16%,rgba(255,255,255,.22),transparent)`,
      `radial-gradient(1px 1px at 88% 38%,rgba(190,225,245,.22),transparent)`,
      `linear-gradient(178deg,${v.wall[0]} 0%,${v.wall[1]} 54%,${v.wall[2]} 100%)`,
    ];
    el.style.setProperty('--art-grain', '0');
  } else if (mode === 'studio') {
    // 白台的壁纸就该几乎看不见：一层极缓的渐变，别的什么都没有（grain 也是 0）
    L = [`linear-gradient(178deg,${v.wall[0]} 0%,${v.wall[1]} 54%,${v.wall[2]} 100%)`];
    el.style.setProperty('--art-grain', '0');
  }
  if (L) dlArtWallOut(el, mode, v, L);
}

/* 把一套主题的壁纸层摆上去，顺手把那幅卡通压在最上面。
   十八套走同一个出口：加主题只要在 DL_ART 里报个 scene，画自己会跟上。 */
function dlArtWallOut(el, mode, v, layers) {
  const T = DL_ART[mode] || {};
  const arr = [];
  if (T.scene) {
    const c = dlSceneColors(mode, v);
    const sc = dlSceneUrl(T.scene, c);
    /* 手机压右下角（那儿是拇指区，正文本来就不落字），
       电脑摊到右侧、左下角再放一份小的当角饰 —— 宽屏两处空白，只填一处会偏。 */
    if (sc && T.desk) {
      arr.push({ img: sc, size: '32vmin auto', pos: 'right 3vmin bottom 6vmin', rep: 'no-repeat' });
      /* 角饰**要躲开左侧导航栏**：壁纸是整屏的，而左栏那 206px 是一块不透明的卡片色，
         摆在 left 0 附近等于画了一份谁也看不见的画（第一版就是这么丢的）。 */
      arr.push({ img: sc, size: '18vmin auto', pos: 'left 244px bottom 3vmin', rep: 'no-repeat' });
    } else if (sc) {
      arr.push({ img: sc, size: '54vmin auto', pos: 'right -6vmin bottom 8vmin', rep: 'no-repeat' });
    }
  }
  /* 前八套给的是字符串：它们原来靠**默认值**铺（repeat + auto，见 style.css 里
     #art-wall 那条注释）—— 界格和织纹要自己内部的循环，写死 cover 会把循环一起拉伸，
     所以这里照原样给回去。第二代给的是带 size 的对象（青海波、格纹要自己的 tile），原样收下。 */
  layers.forEach(x => arr.push(typeof x === 'string'
    ? { img: x, size: 'auto', pos: '0 0', rep: 'repeat' } : x));
  dlLayers(el, arr);
}

/* 一幅画用哪两支色。**不逐锚点写**：八套里这两支色本来就跟着已有字段走
   （墨 / 朱、天青 / 日轮、釉 / 印…），逐锚点手写就是 48 处要对齐的十六进制。 */
function dlSceneColors(mode, v) {
  // 第二代自带两支色（写在 day/night 那两组里），直接用
  if (v.il1) return { il1: v.il1, il2: v.il2, ila: v.ila };
  const pick = (c) => (Array.isArray(c) ? c[1] : c);
  let a = v.ink || v.blk || v.text, b = pick(v.seal) || v.blue;
  if (mode === 'hue') { a = dlArtHue(v, 2); b = dlArtHue(v, 5); }   // 藕荷 + 赭
  else if (mode === 'glass') { a = v.blue; b = v.orb; }
  else if (mode === 'night') { a = v.glyph; b = v.blue; }           // 灯塔的光也是青蓝，暖色一个不留
  else if (mode === 'studio') { a = v.rule; b = v.blue; }           // 那条基线是什么色，画就是什么色
  return { il1: a, il2: b, ila: (DL_ART[mode] || {}).ila || 0.22 };
}


/* 五重山。形状写死不随机 —— 随机的话每次开应用山头都在跳，
   而这是每天见几十次的底图，位置一变就显得"闪"。 */
const DL_RANGES = [
  { base: 0.50, amp: 0.085, ph: 0.4, col: 'far' },
  { base: 0.58, amp: 0.070, ph: 2.1, col: 'far' },
  { base: 0.67, amp: 0.095, ph: 1.2, col: 'mid' },
  { base: 0.77, amp: 0.075, ph: 3.4, col: 'mid' },
  { base: 0.88, amp: 0.060, ph: 0.9, col: 'near' },
];
function dlArtInk(el, v) {
  let cv = el.querySelector('canvas');
  if (!cv) {
    cv = document.createElement('canvas');
    cv.setAttribute('aria-hidden', 'true');
    cv.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;';
    el.appendChild(cv);
  }
  const w = el.clientWidth || window.innerWidth, h = el.clientHeight || window.innerHeight;
  if (!w || !h) return;
  /* 按 CSS 像素画，不乘 devicePixelRatio：这是一张全屏的纯色块底图，没有细节要还原，
     而 2 倍分辨率在 1690×1200 的桌面窗口上就是四百万像素——省下来的那点锐度不值。 */
  const g = cv.getContext && cv.getContext('2d');
  if (!g) return;
  cv.width = w; cv.height = h;
  const sky = g.createLinearGradient(0, 0, 0, h);
  sky.addColorStop(0, v.bg); sky.addColorStop(1, v.card);
  g.fillStyle = sky; g.fillRect(0, 0, w, h);
  if (v.moon > 0.02) {
    const mx = w * 0.76, my = h * 0.13, r = Math.min(w, h) * 0.045;
    const halo = g.createRadialGradient(mx, my, r * 0.6, mx, my, r * 4.2);
    halo.addColorStop(0, 'rgba(240,242,236,' + (0.18 * v.moon).toFixed(3) + ')');
    halo.addColorStop(1, 'rgba(240,242,236,0)');
    g.fillStyle = halo; g.beginPath(); g.arc(mx, my, r * 4.2, 0, 7); g.fill();
    g.fillStyle = 'rgba(244,244,238,' + (0.9 * v.moon).toFixed(3) + ')';
    g.beginPath(); g.arc(mx, my, r, 0, 7); g.fill();
  }
  /* 孤舟。墨山这一稿的画就是**它自己那张 canvas**：五重山和月本来就在这儿画，
     只差一笔舟 —— 所以不像别的七套那样另铺一层 SVG（那一层会被这张不透明的 canvas
     整个盖住）。**画在五重山之后**：山是从各自的山脊一路填到底的，先画舟就被埋了。 */
  const boat = () => {
    /* 颜色跟着明暗翻，和这一稿其余地方同一条规矩：白天是墨、夜里是月白。
       只用一支色写死的话，总有一头是"舟和它坐着的那重山同色" —— 等于没画。
       高度也是算过的：0.73 那条线白天还是空纸、夜里已经进了山影，两头都露得出来。 */
    const dk = v.dark > 0.5;
    g.globalAlpha = dk ? 0.5 : 0.3;
    g.strokeStyle = dk ? v.glyph : v.blk; g.lineWidth = Math.max(1, w / 900);
    g.lineCap = 'round'; g.lineJoin = 'round';
    const bx = w * 0.3, by = h * 0.73, s = Math.min(w, h) * 0.05;
    g.beginPath();                                   // 船身：一条浅弧
    g.moveTo(bx - s, by); g.quadraticCurveTo(bx, by + s * 0.42, bx + s, by);
    g.stroke();
    g.beginPath();                                   // 桅与半帆
    g.moveTo(bx + s * 0.1, by - 0.1 * s); g.lineTo(bx + s * 0.1, by - s * 1.5);
    g.moveTo(bx + s * 0.1, by - s * 1.35); g.lineTo(bx - s * 0.75, by - s * 0.2);
    g.stroke();
  };

  DL_RANGES.forEach((rg, i) => {
    const a = v.m[i];
    if (a < 0.02) return;
    g.globalAlpha = a;
    g.fillStyle = v[rg.col];
    g.beginPath(); g.moveTo(0, h);
    for (let x = 0; x <= w; x += 4) {
      const t = x / w;
      g.lineTo(x, h * (rg.base
        - Math.sin(t * Math.PI * 1.7 + rg.ph) * rg.amp
        - Math.sin(t * Math.PI * 5.3 + rg.ph * 2) * rg.amp * 0.26));
    }
    g.lineTo(w, h); g.closePath(); g.fill();
  });
  boat();
  g.globalAlpha = 1;
}

// 节气色第 i 个模块此刻的颜色。设置页的预览格也要用它，所以单独拎出来 export
function dlArtHue(v, i) { return dlMixR(DL_HUES[i], v.tint, v.amt); }

const DL_ART_VARS = ['bg', 'bg2', 'card', 'line', 'text', 'muted', 'blue'];

/* ---------------- 知识库那一排书封 ----------------
   书封和「库」那六格不是一回事：六格是固定的，书封是**用户自己挑的**（八选一），
   八本必须一眼分得开 —— 所以不能像功能图标那样全拍平成一块材质。
   办法是「同材异色」：材质跟主题走，八本在这套主题**自己的色盘**里各取一位。
     · 有彩的三套（节气色 / 青瓷 / 卷宗）变色相
     · 单色的几套变浓淡：墨山是焦浓重淡清一梯墨，夜航是八档冷光，
       白台干脆只在书脊那一条留色（那一稿的立意就是"一点装饰都不要"）

   这里只报变量（--kb-c0..7 封面、--kb-s0..7 书脊，外加题签/缎带/描边），
   CSS 那边八条 .kbc0..7 消费它们，兜底值就是原来那八条渐变 ——
   **没开主题时外观分毫不变**。八套 × 八本 = 六十四条规则不用写。 */
const DL_KB_PIG = {
  // 八种国画颜料：赭石 花青 藤黄 胭脂 石绿 墨 群青 紫檀
  paper: ['#a8663c', '#3a5a7a', '#c9a227', '#9e3d4a', '#4f7a63', '#3a4049', '#4a5a90', '#6e4f6b'],
  glass: ['#5b8fc0', '#6fa89a', '#c8a06a', '#8f9fc8', '#a88fb8', '#6f9fb8', '#98b0a0', '#c08f8f'],
  /* 一窑出来的八种釉，秘色 → 月白。色相只在青绿里微移，深浅靠**釉的厚薄**拉开：
     八个色相硬塞进青瓷里反而不像青瓷，而只要这一梯拉得开就认得出自己那本。 */
  celadon: ['#4a7d6e', '#5f8f7a', '#6b9a8e', '#7fa89b', '#8ab59f', '#9dc0b6', '#b3cdbd', '#c8dad0'],
  // 档案盒的色标：墨绿 朱 赭 藏青 牛皮 深棕 豆沙 灰绿
  dossier: ['#2f4636', '#8a3324', '#7d5a33', '#2d3c55', '#b0925e', '#4a3a2a', '#6a4a45', '#4f5a53'],
  /* 夜航一个暖点都不留，八本全是冷光。色相之间还要再叠一梯亮度：
     只靠色相的话，压到这么暗的水位上八本会一起糊成同一块深灰。 */
  night: ['#2f7f9f', '#4060c0', '#9060c8', '#2fa080', '#70b8d0', '#5850a0', '#40b0a8', '#a8c8e0'],
  studio: ['#1a6fb5', '#c9563c', '#3f8f6a', '#7a5fb0', '#c99a2a', '#2f6f8f', '#b0456a', '#5a6b7a'],
};

function dlKbCovers(mode, v) {
  const dark = v.dark > 0.5, face = [], spine = [];
  const R = { rim: '', shadow: '', radius: '', ribbon: '', bandLine: '' };
  const grad = (a, b) => 'linear-gradient(160deg,' + a + ',' + b + ')';

  if (DL_ART[mode] && DL_ART[mode].art2) {
    /* 第二代：八本在这套主题自己那排颜料里各取一位（kb 字段），
       再往当前时刻的图标底色里掺一点，白天夜里都落在同一面墙上。 */
    R.band = v.tile[0]; R.bandInk = v.ink; R.ribbon = v.seal || v.il2;
    R.rim = 'inset 0 0 0 1px ' + dlAlpha(v.ink, dark ? 0.24 : 0.14);
    (DL_ART[mode].kb || DL_KB_PIG.paper).forEach(p => {
      const c = dlMixR(p, v.tile[0], dark ? 0.28 : 0.12);
      face.push(grad(dlMixR(c, '#ffffff', 0.12), dlMixR(c, '#000000', 0.18)));
      spine.push(dlMixR(c, '#000000', 0.34));
    });
  } else if (mode === 'paper') {
    // 染过的纸；题签也是纸，右上那面旗换成朱印
    R.band = v.tile[0]; R.bandInk = v.ink; R.ribbon = v.seal;
    DL_KB_PIG.paper.forEach(p => {
      const c = dlMixR(p, v.tile[0], dark ? 0.24 : 0.10);
      face.push(grad(dlMixR(c, '#ffffff', 0.12), dlMixR(c, v.ink, 0.20)));
      spine.push(dlMixR(c, '#000000', 0.32));
    });
  } else if (mode === 'glass') {
    /* 八块淡淡染过的玻璃，颜色有一半还是背后的天透上来的。
       **不加 backdrop-filter**：一屏八本就是八个模糊层，安卓 WebView 会掉帧
       —— 和 .lb-ic 那条注释是同一个理由。 */
    R.band = 'rgba(255,255,255,' + (v.gb * 0.75).toFixed(3) + ')'; R.bandInk = v.text;
    R.ribbon = v.orb;
    R.rim = 'inset 0 0 0 1px rgba(255,255,255,' + v.gb.toFixed(3) + ')';
    DL_KB_PIG.glass.forEach(p => {
      const c = dlMixR(p, v.gc, dark ? 0.42 : 0.32);
      face.push(grad(dlAlpha(c, (v.ga * 0.92).toFixed(3)), dlAlpha(dlMixR(c, v.gc, 0.3), (v.ga * 0.7).toFixed(3))));
      spine.push('rgba(255,255,255,' + (v.gb * 1.1).toFixed(3) + ')');
    });
  } else if (mode === 'ink') {
    /* 焦浓重淡清一梯墨 —— 不是八个色相，这一稿整屏没有第二个颜色。
       浓淡必须朝 glyph（挖白那一头）走，**不能朝 card 走**：
       夜里 card 和 blk 几乎同色，一梯八档会全糊在一起。 */
    R.band = v.glyph; R.bandInk = v.blk; R.ribbon = v.glyph;
    R.rim = 'inset 0 0 0 1px ' + (v.rim
      ? 'rgba(238,236,228,' + v.rim.toFixed(3) + ')' : dlAlpha(v.blk, 0.18));
    [0, 0.09, 0.18, 0.27, 0.36, 0.45, 0.54, 0.63].forEach(t => {
      const c = dlMixR(v.blk, v.glyph, t);
      face.push(grad(dlMixR(c, v.glyph, 0.08), c));
      spine.push(dlMixR(v.blk, '#000000', 0.3));
    });
  } else if (mode === 'hue') {
    // 六个传统色 + 胭脂 + 松。色相全天锁死（和「库」六格同一条规矩），只掺此刻的 tint
    R.band = 'rgba(255,255,255,.9)'; R.bandInk = '#333';
    R.ribbon = dlArtHue(v, 0);
    DL_HUES.concat(['#a33c46', '#5f7a4a']).forEach(p => {
      const c = dlMixR(p, v.tint, v.amt);
      face.push('linear-gradient(150deg,' + dlMixR(c, '#ffffff', 0.26) + ',' + c + ')');
      spine.push(dlMixR(c, '#000000', 0.30));
    });
  } else if (mode === 'celadon') {
    /* 题签往釉里掺一丝、再描一道极淡的边：纯白压在釉上会读成"贴了张便利贴"，
       掺一点之后才像釉上的一块留白（卷宗那张牛皮题签不用掺 —— 那本来就是贴上去的纸）。 */
    R.band = dlMixR(v.card, v.tile[0], 0.07); R.bandInk = v.text;
    R.bandLine = dlAlpha(v.tile[1], 0.14); R.ribbon = v.seal[1];
    R.rim = 'inset 0 0 0 1px rgba(255,255,255,' + (v.rim * 1.3).toFixed(3) + ')';
    DL_KB_PIG.celadon.forEach(p => {
      const c = dlMixR(p, v.tile[1], dark ? 0.30 : 0.10);
      face.push('linear-gradient(150deg,' + dlMixR(c, '#ffffff', 0.14) + ',' + dlMixR(c, v.tile[1], 0.26) + ')');
      spine.push(dlMixR(c, v.tile[1], 0.55));
    });
  } else if (mode === 'dossier') {
    // 牛皮题签贴在封面上，投影是硬的 —— 和卷宗的卡片同一手法（像叠着的纸，不是悬浮的玻璃）
    R.band = v.tile[0]; R.bandInk = v.ink; R.ribbon = v.seal;
    R.radius = '4px'; R.shadow = '2px 3px 0 rgba(120,100,66,.20)';
    DL_KB_PIG.dossier.forEach(p => {
      const c = dlMixR(p, dark ? v.tile[0] : '#000000', dark ? 0.30 : 0.06);
      face.push(grad(dlMixR(c, '#ffffff', 0.10), dlMixR(c, '#000000', 0.18)));
      spine.push(dlMixR(c, '#000000', 0.34));
    });
  } else if (mode === 'night') {
    R.band = dlAlpha(v.glyph, 0.14); R.bandInk = v.glyph; R.ribbon = v.blue;
    R.rim = 'inset 0 0 0 1px rgba(140,200,230,' + v.rim.toFixed(3) + ')';
    DL_KB_PIG.night.forEach((p, i) => {
      // 0.46 是压到底了：再亮一档，八本书就成了这一屏最响的东西，和"近黑"的立意打架
      const c = dlMixR(dlMixR(p, v.tile[0], 0.46), v.glyph, i * 0.045);
      face.push(grad(dlMixR(c, v.glyph, 0.10), dlMixR(c, v.tile[1], 0.45)));
      spine.push(dlMixR(p, v.tile[1], 0.25));
    });
  } else {
    /* 白台：一点装饰都不要。八本同一张白封，唯一的色是书脊那 6px；
       题签退成一圈细边框，右上那面旗直接不要（CSS 里按 art-studio 藏掉）。 */
    R.band = 'transparent'; R.bandInk = v.muted; R.bandLine = v.line;
    R.ribbon = 'transparent';
    R.radius = '5px'; R.shadow = 'none';
    R.rim = 'inset 0 0 0 1px ' + v.line;
    DL_KB_PIG.studio.forEach(p => {
      face.push(grad(v.card, v.bg2));
      spine.push(p);
    });
  }
  R.face = face; R.spine = spine;
  return R;
}

/* ---------------- 字一定要看得清：给字色兜一条对比度下限 ----------------

   18 套主题 × 24 个时刻 = 432 屏，靠眼睛挨个看是看不完的，实测也确实漏了一大片：
   黄昏那一段（18–20 时）**每一套主题**的次要字压在页面底色上只有 1.3~1.6:1 —— 基本等于隐形。

   为什么偏偏是黄昏：卡片底和字色是「到点硬翻」的（见 DL_ART_SNAP，为的是别在中途撞成
   中灰配中灰），而壁纸、天光这些**气氛色是连续滑的**。于是字已经翻成白天的墨色了，
   身下那片底还在从夜色滑向日色，正好路过和墨色差不多的那一档 —— 两条线在黄昏交叉。
   卡片上的字当时挡了一手（卡片自己也翻了），直接落在底色上的字（分组小标题、空状态、
   卡片外的说明）就这么没了。

   解法不改美术稿，只在**下发前**给字色兜底：算一下它压在卡片和底色上分别是多少，
   哪边差就往哪边推（暗底推白、亮底推黑），推到够为止。够了就一个像素都不动 ——
   绝大多数时刻本来就够，这条兜底只在交叉那两三个小时里起作用。 */
const DL_MIN_TEXT = 4.5;      // 正文：WCAG AA
/* 次要字原来是 3.4：「够读，又不至于把层次推平」。这个判断的前提是它只承载
   非关键信息，但实际上 --muted 扛的是每条列表的说明行、每个分组标题、
   首页那三行小字 —— 12.5px 的正文，AA 对它的要求就是 4.5，不是大字的 3。
   默认外观那一支已经提到 5.21（style.css 的 --muted），主题这边不跟上，
   就变成「开了主题反而更看不清」。
   层次靠字号和字重拉，不该靠让字看不清来拉。 */
const DL_MIN_MUTED = 4.5;

function dlLum(c) {
  return dlRGB(c).map(v => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  }).reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
}
function dlRatio(a, b) {
  const l1 = dlLum(a), l2 = dlLum(b);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}
/* 把 ink 推到「压在 surfaces 里每一面上都不低于 min」。推的方向由**最差的那一面**定：
   它比字亮就把字推黑，比字暗就把字推白。一步 6%，一路推到纯黑/纯白为止。

   两处必须留神：
   · 判据看的是**最差的那一面**（worst 取最小值），不是当前这一面 —— 卡片和底色一深一浅时，
     只盯着一面推，会把另一面推垮，来回拉锯。
   · 有些时刻是**推不到**的：晨昏那一档天光琉璃的底色正好是中灰，纯白压上去也只有 4.33:1。
     这时候就把这一路上最好的那个交出去，别硬把字翻成反色 —— 那会和这一刻其余按日/夜
     写死的颜色打架，比差 0.2 个对比度更难看。 */
function dlInkFix(ink, surfaces, min) {
  const worst = c => surfaces.reduce((m, s) => Math.min(m, dlRatio(c, s)), Infinity);
  if (worst(ink) >= min) return ink;
  const far = surfaces.reduce((m, s) => dlRatio(ink, s) < dlRatio(ink, m) ? s : m, surfaces[0]);
  const pole = dlLum(far) > dlLum(ink) ? '#000000' : '#ffffff';
  let best = ink;
  for (let t = 0.06; t < 1.06; t += 0.06) {
    const c = dlMixR(ink, pole, Math.min(1, t));
    if (worst(c) > worst(best)) best = c;
    if (worst(best) >= min) break;
  }
  return best;
}
/* 半透明的面（天光琉璃的玻璃卡）算不出真实底色 —— 它背后是壁纸。
   这种就别拿它当参照，否则算出来的是个 NaN，一路把字色推成纯黑。 */
function dlSolid(c) { return typeof c === 'string' && !/rgba|hsla/.test(c) && !isNaN(dlLum(c)); }

function dlGuardInk(v) {
  const faces = [v.card, v.bg, v.bg2].filter(dlSolid);
  if (!faces.length) return v;
  return Object.assign({}, v, {
    text: dlInkFix(v.text, faces, DL_MIN_TEXT),
    muted: dlInkFix(v.muted, faces, DL_MIN_MUTED),
  });
}

/* 把当前主题刷到界面上。没选主题就把痕迹清干净（**必须清**：不清的话
   关掉主题后 body 上还挂着上一套的 inline 变量，看着像"关不掉"）。 */
function dlArtApply() {
  const b = document.body;
  if (!b) return null;
  const mode = dlArtMode();
  Object.keys(DL_ART).forEach(k => b.classList.toggle('art-' + k, k === mode));
  b.classList.toggle('art-on', !!mode);
  b.classList.toggle('art-desk', !!(mode && DL_ART[mode].desk));
  if (!mode) {
    DL_ART_VARS.concat(['blue-d', 'blue-fill']).forEach(k => b.style.removeProperty('--' + k));
    ['ink', 'seal', 'grain', 'grain-img', 'icgrain', 'rim', 'tile1', 'tile2',
      'glass', 'glass-line', 'glow', 'blk', 'glyph', 'tint', 'amt', 'band', 'rule',
      'fab', 'fab-ink', 'fab-rim', 'tail']
      .forEach(k => b.style.removeProperty('--art-' + k));
    for (let i = 0; i < 6; i++) { b.style.removeProperty('--art-t' + i); b.style.removeProperty('--art-t' + i + 'a'); }
    /* 书封那两排也得清。漏了就是"关不掉"里最难查的一种：整屏都变回默认了，
       只有知识库那一页还留着上一套的封面色。 */
    for (let i = 0; i < 8; i++) { b.style.removeProperty('--kb-c' + i); b.style.removeProperty('--kb-s' + i); }
    ['band', 'band-ink', 'band-line', 'ribbon', 'rim', 'shadow', 'radius']
      .forEach(k => b.style.removeProperty('--kb-' + k));
    const el = document.getElementById('art-wall');
    if (el) { el.style.background = ''; el.style.backgroundImage = ''; const c = el.querySelector('canvas'); if (c) el.removeChild(c); }
    return null;
  }
  const v = dlGuardInk(dlArtAt(mode, dlArtHour()));
  DL_ART_VARS.forEach(k => { if (v[k]) b.style.setProperty('--' + k, v[k]); });
  b.style.setProperty('--blue-fill', v.fill);
  b.style.setProperty('--blue-d', v.fill);
  b.style.setProperty('--art-grain-img', dlGrain() || 'none');

  /* 悬浮球和它那几个胶囊：和模块图标**同一种材质**（纸 / 玻璃 / 墨 / 传统色 / 釉…）。
     每套主题在自己那一段里报三样，CSS 那边就只需要一条规则 ——
     不然就是八套 × 两个元素 = 十六条各写各的，加第九套主题时必漏。 */
  const fab = (bg, ink, rim) => {
    b.style.setProperty('--art-fab', bg);
    b.style.setProperty('--art-fab-ink', ink);
    b.style.setProperty('--art-fab-rim', rim || 'transparent');
  };
  const tileBg = () => `linear-gradient(150deg,${v.tile[0]},${v.tile[1]})`;

  if (DL_ART[mode].art2) {
    /* 第二代十套共用这一段。各套的性格不在这里分叉，在 CSS 的 body.art-xxx 里 ——
       这里只把色表摊成变量，CSS 那边决定它是葫芦弧、缺角像素框还是厚描边贴纸。 */
    b.style.setProperty('--art-tile1', v.tile[0]);
    b.style.setProperty('--art-tile2', v.tile[1]);
    b.style.setProperty('--art-ink', v.ink);
    b.style.setProperty('--art-glyph', v.glyph);
    b.style.setProperty('--art-rim', String(v.rim || 0));
    b.style.setProperty('--art-il1', v.il1);
    b.style.setProperty('--art-il2', v.il2);
    // 这两个有的套用不上，给个不改变外观的空值，免得 CSS 那边还要各写各的兜底
    b.style.setProperty('--art-seal', v.seal || v.il2);
    b.style.setProperty('--art-band', v.band || v.fill);
    fab(tileBg(), v.ink, dlAlpha(v.ink, 0.22));
  } else if (mode === 'paper') {
    b.style.setProperty('--art-tile1', v.tile[0]);
    b.style.setProperty('--art-tile2', v.tile[1]);
    b.style.setProperty('--art-ink', v.ink);
    b.style.setProperty('--art-seal', v.seal);
    b.style.setProperty('--art-rim', String(v.rim));
    // 44px 的格子上纸纹要减半：壁纸那个浓度铺到指甲盖大小，只会把墨线一起洗淡
    b.style.setProperty('--art-icgrain', (v.grain * 0.45).toFixed(3));
    fab(tileBg(), v.ink, dlAlpha(v.ink, 0.22));
  } else if (mode === 'glass') {
    /* 玻璃必须**真的磨砂**（浓度 .58 以上），不能是一层 9% 的白。
       透明度一低，卡片的颜色就完全由背后那片渐变的天决定 —— 而晨昏那一段天正好是中灰，
       字压上去就没了。夜里换深色玻璃、白天换白玻璃，两者在同一刻硬翻。 */
    // gc 是硬翻的，所以还是 '#rrggbb'；dlRgba 只吃 rgb(...)，先转一道
    const glass = 'rgba(' + dlRGB(v.gc).join(',') + ',' + v.ga.toFixed(3) + ')';
    b.style.setProperty('--card', glass);
    b.style.setProperty('--line', 'rgba(255,255,255,' + v.gb.toFixed(3) + ')');
    b.style.setProperty('--art-glass', glass);
    b.style.setProperty('--art-glass-line', 'rgba(255,255,255,' + v.gb.toFixed(3) + ')');
    b.style.setProperty('--art-glow', v.glow.toFixed(3));
    fab(glass, v.text, 'rgba(255,255,255,' + (v.gb * 1.2).toFixed(3) + ')');
  } else if (mode === 'ink') {
    b.style.setProperty('--art-blk', v.blk);
    b.style.setProperty('--art-glyph', v.glyph);
    b.style.setProperty('--art-rim', String(v.rim));
    fab(v.blk, v.glyph, 'rgba(238,236,228,' + v.rim.toFixed(3) + ')');
  } else if (mode === 'hue') {
    /* 功能图标（.hc-logo）有十几个，硬塞进六个传统色反而认不出谁是谁，
       所以它们不逐个换色，改成盖一层当前时刻的 tint —— 和这六格走的是同一条掺色曲线。 */
    b.style.setProperty('--art-tint', v.tint);
    /* 封顶 0.34：夜里 amt 是 0.5，十几个功能图标一起掺半份墨会整片沉下去，
       和这一稿"图标是那一屏唯一的重音、夜里不压暗"的规矩打架。
       封顶之后，功能图标比「库」那六格略退一档 —— 那正好是想要的层级。 */
    b.style.setProperty('--art-amt', Math.min(0.34, v.amt).toFixed(3));
    DL_HUES.forEach((base, i) => {
      const c = dlArtHue(v, i);
      b.style.setProperty('--art-t' + i, c);
      b.style.setProperty('--art-t' + i + 'a', dlMixR(c, '#ffffff', 0.26));   // 渐变的亮那头
    });
    // 球取靛（和「库」里的知识库同一色），胶囊各取一色 —— 六色识别在这一稿是主角
    const indigo = dlArtHue(v, 1);
    fab(`linear-gradient(150deg,${dlMixR(indigo, '#ffffff', 0.22)},${indigo})`, '#ffffff', null);
  } else if (DL_ART[mode].desk) {
    /* 电脑端四套共用一套字段名（tile/glyph/ink/seal/rim/grain），CSS 里各写各的形状。
       复用手机那几套的变量名不是偷懒：清变量的清单只有一份，多一个名字就多一处
       "关不掉"的机会。逐个 if 是因为四套各用其中几样，没有的那些不该留在 body 上。 */
    if (v.tile) { b.style.setProperty('--art-tile1', v.tile[0]); b.style.setProperty('--art-tile2', v.tile[1]); }
    if (v.glyph) b.style.setProperty('--art-glyph', v.glyph);
    if (v.ink) b.style.setProperty('--art-ink', v.ink);
    if (v.seal) b.style.setProperty('--art-seal', v.seal);
    if (v.band) b.style.setProperty('--art-band', v.band);
    if (v.rule) b.style.setProperty('--art-rule', v.rule);
    b.style.setProperty('--art-rim', String(v.rim));
    b.style.setProperty('--art-icgrain', (v.grain * 0.45).toFixed(3));
    // 电脑端四套都有 tile；字形色各家叫法不同（釉青/夜航用 glyph，卷宗/白台用 ink）
    if (v.tile) fab(tileBg(), v.glyph || v.ink || v.text, dlAlpha(v.glyph || v.ink || v.text, 0.20));
    else fab(v.fill, '#ffffff', null);
  }

  /* 知识库那一排书封。八套主题一视同仁，所以放在 if 链**外面**：
     漏掉哪一套，那一套的书就退回最初那八条通用彩，和整屏格格不入
     —— 这一轮返工要修的就是这个。 */
  try {
    const kb = dlKbCovers(mode, v);
    kb.face.forEach((c, i) => b.style.setProperty('--kb-c' + i, c));
    kb.spine.forEach((c, i) => b.style.setProperty('--kb-s' + i, c));
    b.style.setProperty('--kb-band', kb.band);
    b.style.setProperty('--kb-band-ink', kb.bandInk);
    b.style.setProperty('--kb-band-line', kb.bandLine || 'transparent');
    b.style.setProperty('--kb-ribbon', kb.ribbon);
    // 这三样有的主题不用，给个不改变外观的空值，免得 CSS 那边还要各写各的兜底
    b.style.setProperty('--kb-rim', kb.rim || '0 0 rgba(0,0,0,0)');
    b.style.setProperty('--kb-shadow', kb.shadow || '0 6px 18px rgba(20,30,50,.2)');
    b.style.setProperty('--kb-radius', kb.radius || '6px 11px 11px 6px');
  } catch (_) { /* 算不出来就退回 CSS 里那八条兜底渐变，不该拦住整套主题 */ }

  /* 长尾兜底。样式表里还有十几处只在某一页出现一次的写死彩色（各种页头、进度条、
     头像底、骨架屏…）。逐条给它们配主题色是做得完的，但**下次谁新加一条又会漏**
     —— 这一轮就是这么漏的。所以给它们统一套一个滤镜：颜色不再是原来的彩度，
     至少不会有一块荧光跳出来。
     值按主题分三档：单色那两稿几乎抽干净，暖调的偏一点棕，其余压掉一半彩度。
     （tests/frontend/arttheme.test.js 里有一条扫样式表的测试钉着"新加的彩色
     必须落进主题段"，不然这层兜底也会慢慢失守。） */
  b.style.setProperty('--art-tail',
    (mode === 'ink' || mode === 'celadon') ? 'saturate(.14)'
      : (mode === 'paper' || mode === 'dossier') ? 'saturate(.42) sepia(.16)'
        /* 第二代里像素那两套**不压彩度**：它整套的立意就是糖果色，
           压完就成了一屏脏粉。其余四种画风按各自的调子压。 */
        : (DL_ART[mode].scene === 'pixel') ? 'saturate(1)'
          : (DL_ART[mode].scene === 'meow') ? 'saturate(.42) sepia(.16)'
            : (DL_ART[mode].scene === 'witch') ? 'saturate(.5)'
              : (DL_ART[mode].scene === 'tempura' || DL_ART[mode].scene === 'garden') ? 'saturate(.72)'
                : mode === 'hue' ? 'saturate(.7)' : 'saturate(.5)');

  try { dlArtWall(mode, v); } catch (_) { /* 壁纸画不出来就是一块纯色底，不该拦住用 */ }
  /* 图标册跟着换（js/articons.js）。它比本文件晚加载，第一帧时还不存在 ——
     不用管：那会儿底栏和左栏都还没渲染，tabs.js 自己就会取到对的那一册。 */
  try { if (window.artIconsRepaint) window.artIconsRepaint(); } catch (_) { /* 图标换不了不该拦住配色 */ }
  return v;
}

/* 自己起跑。启动屏那一下必须同步画完（脚本就贴在 #splash 后面），
   图标画完一次之后每 10 分钟对一次表 —— 这应用一开就是几小时，跨过黄昏得跟上。 */
/* 登录/注册/找回三页没有启动屏，只有天光底（#dl-sky）。它们也**不套美术主题**：
   主题是账号里的东西，登录前还不知道是谁；这一屏只该有一件事——把天光接上。 */
const DL_AUTH = !!document.getElementById('dl-sky');
try { if (DL_AUTH) dlPaintAuth(); else dlPaintSplash(); } catch (_) { /* 画不出来就是 CSS 里那张静态兜底底图，不该拦住启动 */ }
/* 主题也要在第一帧就位。这里顺手把 .dark 也定了：等 theme.js 加载完再翻，
   中间那几十毫秒就是白底闪一下——主题开着的时候尤其刺眼。 */
try {
  if (!DL_AUTH) {
    dlIconsApply();          // 必须和主题同一帧：晚一拍就是图标闪一下
    dlArtApply();
    const d = dlArtDark();
    if (d !== null) document.body.classList.toggle('dark', d);
    // 天光底要排在最后：它得先知道「是不是夜间」「有没有开主题」才决定要不要上色
    dlTintApply();
  }
} catch (_) { /* 主题是可选项，画不出来就退回默认外观 */ }
try {
  dlFavicon();
  setInterval(() => {
    try { dlFavicon(); } catch (_) { /* 标签页图标而已 */ }
    // 跨过黄昏时主题也得跟上，顺带把 .dark 对一次表
    // 登录页开着不动过了黄昏，底也得跟上（这三页没有主题那一路）
    try { if (DL_AUTH) dlPaintAuth(); } catch (_) { /* 底没重画就还是上一档的天，不影响登录 */ }
    try {
      if (!DL_AUTH && dlArtMode()) {
        dlArtApply();
        const dk = dlArtDark();
        if (dk !== null && window.applyTheme) window.applyTheme();
        else if (dk !== null) document.body.classList.toggle('dark', dk);
      }
      // 没开主题的默认外观也要跟上：不跟的话跨过黄昏底色停在上一档
      if (!DL_AUTH) dlTintApply();
    } catch (_) { /* 同上 */ }
  }, 600000);
} catch (_) { /* 没有 canvas 就算了 */ }
/* 窗口尺寸变了要管两件事：
     · 跨过 761 就是换了一端（手机四套 ↔ 电脑四套，见 dlArtKey），整套得重刷 ——
       不刷的话上一端的 inline 变量还挂在 body 上，而它的 CSS 已经不生效了，
       表现就是"配色对不上任何一套"；
     · 墨山那张山水是按窗口尺寸画的，窗口一变就得重画（别的主题是渐变，自己会跟）。 */
let dlRz, dlWasDesk = dlIsDesk();
addEventListener('resize', () => {
  if (DL_AUTH) return;                    // 登录三页不套主题，没有要重刷的东西
  clearTimeout(dlRz);
  dlRz = setTimeout(() => {
    try {
      const now = dlIsDesk();
      if (now !== dlWasDesk) {
        dlWasDesk = now;
        dlArtApply();
        if (window.applyTheme) window.applyTheme();
        if (window.artRenderPicker) window.artRenderPicker();   // 设置页开着的话，格子也得换一批
      } else if (dlArtMode() === 'ink') {
        dlArtApply();
      }
    } catch (_) { /* 重画失败就留着旧的那张 */ }
  }, 160);
});

window.dlAt = dlAt;
window.dlPaintSplash = dlPaintSplash;
window.dlPaintAuth = dlPaintAuth;   // 登录/注册/找回三页用（js/auth.js 里定时重画）
window.dlFavicon = dlFavicon;
window.DL_ART = DL_ART;
window.dlArtAt = dlArtAt;
window.dlArtApply = dlArtApply;
window.dlArtDark = dlArtDark;
window.dlArtMode = dlArtMode;
window.dlArtClock = dlArtClock;
window.dlArtHue = dlArtHue;
window.dlIsDesk = dlIsDesk;
window.dlArtKey = dlArtKey;
window.dlGuardInk = dlGuardInk;   // 测试要拿它核对每套主题每个时刻的对比度
