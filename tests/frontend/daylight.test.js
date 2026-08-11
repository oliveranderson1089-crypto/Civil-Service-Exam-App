/* 日光：启动屏和标签页图标随时刻连续变。
 *
 * 这一层最容易出的三种错，都不会报错、只会「看着不对」：
 *
 *   1) **跨零点断掉** —— 锚点表最后一项是 23:00、第一项是 05:00。
 *      按 b.h - a.h 算跨度会得到负数，凌晨两点直接跳回白天的配色。
 *   2) **夜里字看不见** —— 引言原来写死 color:#4a5566，压在墨蓝底上就是一团黑。
 *      所以颜色必须是**由脚本按时刻给**的，不是主题给的。
 *   3) **启动屏被主题盖掉** —— 原来有一整套 body.dark #splash。留着的话，
 *      白天开夜间模式就又变回死板的深色，日夜曲线白算。
 *
 * 另外它排在所有脚本最前面（要在第一帧就画完），所以不许依赖 core.js 的任何东西 ——
 * 最后一条测试就是钉这个：把它单独跑起来，不能炸。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { boot } = require('./harness');

const ROOT = path.resolve(__dirname, '../..');
const $ = (h, sel) => h.window.document.querySelector(sel);

test('六个锚点之间连续插值，跨零点也不断', (t) => {
  const h = boot(); t.after(() => h.close());
  const at = (x) => h.plain(`dlAt(${x})`);
  // 端点各归各位
  assert.strictEqual(at(8).name, '晨光');
  assert.strictEqual(at(23).name, '夜');
  // 凌晨两点在 23:00 → 次日 05:00 这一段里，必须还是夜色（不是跳回白天）
  const night = at(23), small = at(2), dawn = at(5);
  assert.strictEqual(at(1).name, '夜', '凌晨一点被算成了别的时段');
  assert.ok(small.stars > 0.6, '凌晨两点星子没了，跨零点那段断了');
  assert.ok(small.icon[0] !== dawn.icon[0], '凌晨两点直接等于黎明，说明这一段没在插值');
  // 相邻时刻之间不许有跳变：整点采样，任何一步的亮度差都该是渐进的
  let prev = null, maxJump = 0;
  for (let x = 0; x < 24; x += 0.25) {
    const v = at(x);
    const lum = +v.sky[0].match(/\d+/g).reduce((a, b) => +a + +b, 0);
    if (prev !== null) maxJump = Math.max(maxJump, Math.abs(lum - prev));
    prev = lum;
  }
  assert.ok(maxJump < 90, `相邻 15 分钟之间跳了 ${maxJump}，曲线断了`);
  assert.ok(night.icon[0] !== dawn.icon[0], '夜和黎明的图标底色一样，插值没起作用');
});

test('启动屏由脚本按时刻上色：白天墨字浅底，夜里浅字墨底', (t) => {
  const h = boot(); t.after(() => h.close());
  const sp = () => $(h, '#splash');
  h.run('dlPaintSplash(8)');
  const day = { bg: sp().style.background, ink: sp().style.color };
  h.run('dlPaintSplash(23)');
  const night = { bg: sp().style.background, ink: sp().style.color };
  assert.notStrictEqual(day.bg, night.bg, '早晚底色一样');
  assert.notStrictEqual(day.ink, night.ink, '早晚字色一样 —— 夜里那句引言会糊在深底上');
  // 夜里的层：星子和光点亮着，晨光的方格退掉
  assert.ok(+$(h, '#sp-stars').style.opacity > 0.9, '夜里没有星子');
  assert.ok(+$(h, '#sp-grid').style.opacity < 0.05, '夜里还留着晨光的方格');
  h.run('dlPaintSplash(8)');
  assert.ok(+$(h, '#sp-grid').style.opacity > 0.9, '早上没有方格');
  assert.ok(+$(h, '#sp-trail').style.opacity < 0.05, '大白天点着夜里那串光点');
});

test('引言和落款的颜色跟着时刻走，不是写死的', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('dlPaintSplash(23)');
  const q = $(h, '.sp-quote');
  assert.ok(q.style.color, '引言没有被上色 —— CSS 里那个写死的 #4a5566 会压在墨底上');
  const css = fs.readFileSync(path.join(ROOT, 'static/style.css'), 'utf8');
  assert.doesNotMatch(css, /body\.dark #splash/,
    '又给启动屏加了一套 body.dark —— 它会盖掉按时刻算的底色');
});

test('启动屏画不出来也不该拦住应用（DOM 缺了就安静返回）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run("document.getElementById('splash').remove()");
  assert.strictEqual(h.plain('dlPaintSplash(12)'), null, '启动屏没了还想画，会抛异常');
});

test('标签页图标：没有 canvas 就跳过，不炸（jsdom / 老壳）', (t) => {
  const h = boot(); t.after(() => h.close());
  // harness 里 getContext 返回 null，正好是"这个壳没有 canvas"的情形
  assert.strictEqual(h.plain('dlFavicon(9)'), null, '拿不到 2d 上下文时没有安静返回');
});

test('它早加载、且不能被打包器收走（收走了整个应用会停在启动屏）', () => {
  const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
  const srcs = [...html.matchAll(/<script src="(js\/[^"]+)"[^>]*><\/script>/g)].map(m => m[1]);
  assert.strictEqual(srcs[0], 'js/daylight.js',
    '日光脚本不在第一个：启动屏会先闪一下默认色再变');
  /* assets.py 把所有**光秃秃的** <script src="js/x.js"></script> 合成一个 bundle，
     并整体挪到第一个标签的位置。这一个在 DOM 中间，所以必须带属性绕开打包 ——
     否则 bundle 提前到 DOM 还没解析完时执行，$('#crumb') 是 null，应用当场停在启动屏。
     线上真出过这事故（只在打包后的线上复现，jsdom 是等 DOM 解析完才求值的），别拿掉。 */
  assert.match(html, /<script src="js\/daylight\.js"[^>]+data-early[^>]*><\/script>/,
    'daylight.js 的标签没带 data-early，会被打包器收进 bundle 并提前执行');
  const bundlable = html.search(/<script src="js\/[^"]+"><\/script>/);
  assert.ok(bundlable > html.lastIndexOf('</section>'),
    '有可打包的 <script> 插在了 DOM 中间：打包后整个应用会停在启动屏');
  const src = fs.readFileSync(path.join(ROOT, 'static/js/daylight.js'), 'utf8');
  // core.js 的招牌符号一个都不能出现（它们那时候还没定义）
  [/\bapi\(/, /\besc\(/, /\btoast\(/, /\$\(/].forEach(re =>
    assert.doesNotMatch(src, re, `daylight.js 用了 ${re} —— 它比 core.js 先跑，那时还没有这个东西`));
});

/* 方章也跟着时刻走（后加的）。它是这一屏唯一的实色块，写死一个蓝压在黄昏的暖底上
   会像贴上去的。要守的边界有两条：一是**必须变**，二是**必须还是蓝的** ——
   离开蓝色就不是这个应用的章了（用户明确要求过"公周围依旧用蓝色"）。 */
test('启动屏的方章跟着时刻变色，但始终在蓝色一族里', (t) => {
  const h = boot(); t.after(() => h.close());
  const at = (x) => h.plain(`dlAt(${x})`);
  const day = at(8).seal, night = at(23).seal, dusk = at(18).seal;
  assert.notDeepStrictEqual(day, night, '早晚方章一个色 —— 那就没跟着时刻走');
  assert.notDeepStrictEqual(day, dusk, '黄昏和早上的方章一个色');
  // 蓝色一族：三个通道里 B 必须最大，且明显大于 R
  [day, night, dusk].forEach((pair) => pair.forEach((c) => {
    const [r, g, b] = c.match(/\d+/g).map(Number);
    assert.ok(b > g && g > r, `方章 ${c} 不是蓝的了（R${r} G${g} B${b}）`);
    assert.ok(b - r > 40, `方章 ${c} 蓝得不够，快成灰的了`);
  }));
});

test('方章的背景和投影都由脚本给（投影不跟着变会像浮在半空）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('dlPaintSplash(8)');
  const lg = $(h, '.sp-logo');
  const day = { bg: lg.style.backgroundImage, sh: lg.style.boxShadow };
  h.run('dlPaintSplash(23)');
  assert.ok(day.bg && lg.style.backgroundImage, '方章没有被上色');
  assert.notStrictEqual(day.bg, lg.style.backgroundImage, '早晚方章底色一样');
  assert.notStrictEqual(day.sh, lg.style.boxShadow, '投影没跟着方章变');
});
