/* CSS 预算棘轮：写死值只准变少，不准变多。
 *
 * 背景（2026-08-13 界面评审）：style.css 里有 668 个不重复的十六进制颜色、42 种字号、
 * 28 种圆角、129 种阴影、44 个 z-index，对着 :root 里那二十来个变量。
 * 问题不是「现在坏了」——夜间配对其实写得很全——而是**一个颜色要在两处改**，
 * 而美术主题有 18 套，每加一套这个成本就乘一次。
 *
 * 一次性迁移六百多个色值的风险远大于收益，所以走另一条路：
 *   · :root 里立好尺子（--fs-* / --r-* / --sh-* / --z-* / --sp-*，见 style.css 开头）
 *   · 新代码一律取变量
 *   · 这个测试卡住存量：**只减不增**
 *
 * 它拦不住「把一个写死值换成另一个写死值」，但拦得住「又多了一个」——
 * 而后者正是过去发生的事：style.css 开头那四行注释明令禁止写死灰色，
 * 底下 #6b7280 还是出现了 27 次。光靠注释挡不住，得有人查数。
 *
 * 数字降下来之后**请顺手改小这里的预算**，棘轮才会往前走。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

/* 先把注释剥掉再数。这个文件的注释写得很长（这是好事），但里面难免出现
   #ffffff、@media、!important 这些字样 —— 数进去就是虚高，还会让人去改注释凑数。 */
const CSS = fs.readFileSync(path.join(__dirname, '../../static/style.css'), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '');

/* 上限 = 2026-08-13 全部改完之后的实测值（剥掉注释后数的）。只降不升。
   评审当天的起点是：hex 670 / 字号 43 / 圆角 26 / 阴影 129 / z-index 41 /
   断点 15 / !important 322 —— 那一版还没剥注释，口径略松。 */
const BUDGET = {
  hexUnique: 666,      // 不重复的十六进制颜色（手写板三层底改成透明后少了两个实心底色）
  fontSizes: 42,       // 不重复的 font-size:Npx
  radii: 28,           // 不重复的 border-radius:Npx
  shadows: 129,        // 不重复的 box-shadow 值
  zIndex: 44,          // 不重复的 z-index 取值
  /* 曾经是 21，其中三对是同一个值的两种写法（`@media(max-width:760px)` 和
     `@media (max-width:760px)` 各算一条）。2026-08-22 全文统一成 `@media (` 后
     剩 19 个**真**断点，棘轮跟着收到 19：以后再加新断点得先想清楚。 */
  breakpoints: 19,
  important: 311,      // !important 出现次数（这个数是总数，不是去重）
};

const uniq = (re) => new Set([...CSS.matchAll(re)].map(m => m[0].toLowerCase())).size;
const count = (re) => [...CSS.matchAll(re)].length;

const MEASURE = {
  hexUnique: () => uniq(/#[0-9a-fA-F]{3,8}\b/g),
  fontSizes: () => uniq(/font-size:[0-9.]+px/g),
  radii: () => uniq(/border-radius:[0-9.]+px/g),
  shadows: () => uniq(/box-shadow:[^;}]+/g),
  zIndex: () => uniq(/z-index:-?[0-9]+/g),
  breakpoints: () => uniq(/@media[^{]*\([^)]*\)/g),
  important: () => count(/!important/g),
};

for (const [key, max] of Object.entries(BUDGET)) {
  test(`CSS 预算：${key} 不超过 ${max}`, () => {
    const now = MEASURE[key]();
    assert.ok(now <= max,
      `${key} 从 ${max} 涨到了 ${now}。\n`
      + '  新样式请取 :root 里的 token（--fs-* / --r-* / --sh-* / --z-* / --sp-*）。\n'
      + '  确实降不下来、又必须加的话，改这里的预算并在提交信息里说明理由。');
    if (now < max) {
      // 降了要提醒收紧，否则棘轮会松掉——过一阵又能悄悄涨回来
      console.log(`  ↓ ${key} 已降到 ${now}（预算还写着 ${max}，可以收紧了）`);
    }
  });
}

/* 立好的尺子得真的在那儿。漏定义一个，用到它的规则会静默回落到浏览器默认值
   —— 那种错在夜间/主题下才看得出来，最难查。 */
test('尺度 token 都有定义', () => {
  const want = [
    '--fs-xs', '--fs-sm', '--fs-md', '--fs-lg', '--fs-xl', '--fs-2xl', '--fs-3xl',
    '--r-xs', '--r-sm', '--r-md', '--r-pill',
    '--sh-1', '--sh-2', '--sh-3',
    '--z-base', '--z-sticky', '--z-rail', '--z-fab', '--z-bar', '--z-modal',
    '--sp-1', '--sp-2', '--sp-3', '--sp-4', '--sp-5', '--sp-6',
  ];
  const missing = want.filter(v => !new RegExp('\\' + v + '\\s*:').test(CSS));
  assert.deepStrictEqual(missing, [], 'style.css 里没定义这些 token');
});

/* --muted 是全站用得最多的颜色（320 处：每条列表的说明行、每个分组标题）。
   它在白卡上必须过 AA 的 4.5:1 —— 2026-08-13 之前是 #8a93a3，只有 3.1。
   这条测试盯着它别再被调回去。 */
test('--muted 在白卡和页底上都过 AA', () => {
  const m = CSS.match(/--muted:\s*(#[0-9a-fA-F]{6})/);
  assert.ok(m, ':root 里找不到 --muted');
  const lum = (h) => {
    const p = [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255)
      .map(c => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)));
    return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2];
  };
  const ratio = (a, b) => {
    const [x, y] = [lum(a), lum(b)];
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  };
  for (const bg of ['#ffffff', '#f4f6f9']) {
    const r = ratio(m[1], bg);
    assert.ok(r >= 4.5, `--muted ${m[1]} 压在 ${bg} 上只有 ${r.toFixed(2)}:1，AA 要 4.5`);
  }
});
