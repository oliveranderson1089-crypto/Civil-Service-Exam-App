/* 电脑端左侧导航栏（界面重构 P3）。
 *
 * 核心主张：底部标签栏和左侧导航栏是**同一份 TAB_DEFS 的两个形态**，不是两套导航。
 * 所以最该防的是它们悄悄长歪：加一个标签只改 TAB_DEFS，两边必须一起变、点击必须走同一条路。
 * 抄成两份的话不会报错，只会有一天电脑上少一个入口——而这种缺失谁也不会主动去查。
 *
 * 另外两条：
 *   · 谁出现只由 CSS 断点决定，JS 不判断屏幕宽度。用 IS_MOBILE 之类的启动快照来判，
 *     浏览器窗口一拖动就会两个都在或者两个都没有（IS_MOBILE 是加载时算一次的常量）。
 *   · 沉浸式页面（做题/小记）两个都要让位，理由和手机端一样：整屏专注。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { boot } = require('./harness');

const $ = (h, s) => h.window.document.querySelector(s);
const $$ = (h, s) => [...h.window.document.querySelectorAll(s)];
const CSS = fs.readFileSync(path.join(__dirname, '../../static/style.css'), 'utf8');

test('左栏和底栏是同一份 TAB_DEFS 的两个形态，分组一一对应', (t) => {
  const h = boot(); t.after(() => h.close());
  const bottom = $$(h, '#tabbar [data-tb]').map(b => b.dataset.tb);
  const rail = $$(h, '#siderail .sr-g-h').map(b => b.dataset.tb);
  assert.deepStrictEqual(rail, bottom, '两边的标签对不上——说明有一边是手写的');
  assert.deepStrictEqual($$(h, '#siderail .sr-g-h').map(b => b.textContent),
    $$(h, '#tabbar [data-tb] i').map(b => b.textContent));
});

test('左栏二级**只有一套形式**：今日用固定捷径，其余一律是那个标签页的分组标题', (t) => {
  const h = boot(); t.after(() => h.close());
  const names = $$(h, '#siderail .sr-i i').map(b => b.textContent);
  // 今日没有对应的标签页，用它自己那份捷径
  ['今日概览', '今日复习', '每日测试'].forEach(n =>
    assert.ok(names.includes(n), `「今日」少了捷径「${n}」`));
  // 其余标签：二级就是标签页里的分组，一个不多一个不少
  const groups = h.plain(`TAB_DEFS.filter(t => !t.rail)
    .flatMap(t => t.groups('').map(g => g.name))`);
  groups.forEach(n => assert.ok(names.includes(n), `左栏少了分组「${n}」`));
  // 被替换掉的那套捷径不许再出现，否则又是两套并排、概念还重复
  ['历年真题', '专项练', '错题本', '成语 · 上位词', '小记 · 知识库'].forEach(n =>
    assert.ok(!names.includes(n), `「${n}」是被分组标题替换掉的旧捷径，不该还在左栏`));
});

test('分组标题点了跳到标签页的那一段，并且先把 chip 清掉', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run('goHome()');
  // 先在「积累」里选一个 chip，让别的分组根本没渲染出来
  $(h, '#siderail .sr-g-h[data-tb="acc"]').click();
  h.run("tbChip.acc = '言语'; tbFill('acc');");
  assert.ok(!$$(h, '#tab-groups .tab-gh').some(x => x.textContent === '时政'));
  $$(h, '#siderail .sr-i').find(b => b.querySelector('i').textContent === '时政').click();
  assert.strictEqual(h.window.document.body.dataset.view, 'tab');
  assert.ok($$(h, '#tab-groups .tab-gh').some(x => x.textContent === '时政'),
    'chip 没清掉 —— 那一组压根没渲染，跳过去会扑空');
});

test('角标：复习条数和错题存量都挂得上，0 的时候不显示', (t) => {
  const h = boot(); t.after(() => h.close());
  const bd = () => $$(h, '#siderail .sr-bd').map(b => b.textContent);
  assert.deepStrictEqual(bd(), [], '一条都没有的时候不该挂角标');
  h.run('tbSetReview(12)');
  assert.ok(bd().includes('12'), '复习角标没上去');
  h.run("tbHub = { boards: { A: { wrong: 5 }, B: { wrong: 23 } }, acc: {} }; tbBadge.wrong = 28; tbRailFill();");
  assert.ok(bd().includes('28'), '错题角标该是各板块存量之和（现在挂在「巩固与错题」那一组上）');
});

test('电脑上做题时左栏保留：宽度管够，中途还能跳去查东西', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run("push({ view: 'realrun' })");
  assert.ok(!$(h, '#siderail').classList.contains('hidden'),
    '做题页把左栏也撤了——那是手机的道理（屏幕小、底下住着别的条），电脑上没必要');
  assert.ok($(h, '#tabbar').classList.contains('hidden'), '手机底栏在做题页仍该让位');
  assert.ok(h.window.document.body.classList.contains('has-rail'),
    '正文没跟着让位，会整个压在左栏下面');
});

test('左栏点击走的是同一条路：内容和高亮都跟着变', (t) => {
  const h = boot(); t.after(() => h.close());
  $(h, '#siderail .sr-g-h[data-tb="acc"]').click();
  assert.strictEqual(h.window.document.body.dataset.view, 'tab');
  assert.strictEqual(h.run('stack[stack.length-1].tab'), 'acc');
  assert.ok($(h, '#siderail .sr-g-h[data-tb="acc"]').classList.contains('on'));
  assert.ok($(h, '#tabbar [data-tb="acc"]').classList.contains('on'),
    '底栏没跟着亮——两个形态的状态该是同一份');
});

test('左栏的「今日」和底栏一样回到首页栈底', (t) => {
  const h = boot(); t.after(() => h.close());
  $(h, '#siderail .sr-g-h[data-tb="drill"]').click();
  $(h, '#siderail .sr-g-h[data-tb="today"]').click();
  assert.strictEqual(h.run('stack.length'), 1);
  assert.strictEqual(h.window.document.body.dataset.view, 'home');
});

test('分组标题常驻，不跟着「哪个标签开着」忽隐忽现', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  const names = () => $$(h, '#siderail .sr-i i').map(b => b.textContent);
  const before = names();
  $(h, '#siderail .sr-g-h[data-tb="acc"]').click();
  assert.deepStrictEqual(names(), before, '打开标签页后左栏条目变了 —— 常驻目录不该忽隐忽现');
  h.run("push({ view: 'idiom' })");
  assert.deepStrictEqual(names(), before, '进了二级页左栏又变了');
});

test('真·全屏的两页（阅读器 / 文档编辑器）左栏才撤', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  // 测试里 init() 拉不到 /api/sections 就提前返回，goHome() 从没跑过、栈是空的，
  // 那样 back() 是空操作。先把栈立起来再测。
  h.run('goHome()');
  h.run("push({ view: 'viewer' })");
  assert.ok($(h, '#siderail').classList.contains('hidden'), '阅读器全屏时左栏还占着 206px');
  h.run('back()');
  assert.ok(!$(h, '#siderail').classList.contains('hidden'));
});

test('谁出现由断点决定，两个断点必须严丝合缝不留空档', () => {
  // JS 里不能用 IS_MOBILE 判——那是加载时算一次的常量，拖动窗口不会变，
  // 结果就是拖宽之后底栏还在、左栏不出来。
  assert.ok(/@media\(min-width:761px\)\{[\s\S]{0,400}?\.tabbar\{display:none/.test(CSS),
    '≥761 没把底部标签栏收掉');
  assert.ok(/@media\(min-width:761px\)\{[\s\S]{0,600}?\.siderail\{position:fixed/.test(CSS),
    '≥761 没把左栏放出来');
  assert.ok(/\.siderail\{display:none;\}/.test(CSS), '默认（窄屏）没把左栏藏起来');
});

test('内容区给左栏让出位置，且宽屏上限个宽', () => {
  assert.ok(/body\.has-rail main\{padding-left:206px/.test(CSS),
    '正文没给左栏让位，会被压在下面');
  assert.ok(!/body\.has-tabs main\{padding-left/.test(CSS),
    '让位还挂在 has-tabs 上 —— 做题页没有底栏但有左栏，会对不上');
  assert.ok(/body\.has-rail #view-home,body\.has-rail #view-tab,body\.has-rail #view-allfeats\{[^}]*max-width/.test(CSS),
    '导航页在宽屏上没限宽，一行几百字符没法读');
});

test('顶栏的「首页」在有常驻导航时收掉：它和「今日」是同一个去处', () => {
  assert.ok(/body\.has-tabs #home-btn,body\.has-rail #home-btn\{display:none/.test(CSS),
    '左栏有「今日」、顶栏还有「首页」，两套导航并存');
  // 「账户」「后台」只在手机收（进了「我的」），电脑上留着当快捷入口
  assert.ok(!/body\.has-tabs #account-btn/.test(CSS), '电脑上把「账户」也收了，那儿并没有替代入口');
});

test('草稿纸在电脑上默认停右半屏，手机仍是下半屏', () => {
  const js = fs.readFileSync(path.join(__dirname, '../../static/js/pad.js'), 'utf8');
  assert.match(js, /createDock\(\$\('#pad'\), 'padDock', IS_MOBILE \? 'bottom' : 'right'/,
    '草稿纸在电脑上还是默认盖住下半屏——宽度够的时候该和题目并排');
});

/* ---------------- 大屏适配（≥1500） ---------------- */

test('宽屏只放宽「不是长文阅读」的页面，阅读类必须留在 760', () => {
  // 这条护的是一个判断，不是一个数字：时政/范文/素材那类是整篇读的，
  // 760px 一行 40 来个汉字正好；跟着屏幕拉到 1500 一行一百多字，
  // 眼睛来回甩，是**变难读**不是变好。全屏留白不该拿它们去填。
  const m = CSS.match(/@media\(min-width:1500px\)\{[\s\S]*?\n\}/);
  assert.ok(m, '没有 ≥1500 的大屏断点');
  const wide = m[0];
  ['#view-chat', '#view-wrongq', '#view-realrun', '#view-tab'].forEach(v =>
    assert.ok(wide.includes(v), `操作类的 ${v} 没跟着放宽`));
  ['#view-news', '#view-fanwen', '#view-sucai', '#view-changshi', '#view-policydoc'].forEach(v =>
    assert.ok(!wide.includes(v), `阅读类的 ${v} 被拉宽了 —— 一行一百多字没法读`));
});

test('正文型页面任何宽度都不放宽：整篇读的东西不能一行一百多字', () => {
  /* 这条是上一轮漏掉的：当时只照顾了「已经有 760px 上限」的阅读类，
     可成文、范文详情、批改结果这些**本来就没设上限** —— 通栏是它们的默认行为，
     屏幕一宽就一行一百多字。分类的判据是「从头读到尾」还是「扫一眼挑一个」。 */
  const READ = ['#view-writed', '#view-essayd', '#view-docqad', '#view-slresult', '#view-findrecd'];
  const rule = CSS.match(/#view-writed[^{]*\{[^}]*max-width:760px/);
  assert.ok(rule, '成文/范文详情那批正文页没设 760px 行长上限');
  READ.forEach(v => assert.ok(rule[0].includes(v) || new RegExp(v + '[^{]*\\{[^}]*max-width:760px').test(CSS),
    `${v} 是整篇读的，却没限行长`));
  const wide = CSS.match(/@media\(min-width:1500px\)\{[\s\S]*?\n\}/g) || [];
  READ.forEach(v => wide.forEach(blk => assert.ok(!blk.includes(v),
    `${v} 被放进了宽屏放宽名单 —— 正文型永远不该跟着屏幕长`)));
});

test('材料分栏只给「有给定资料」的题，没材料不能空出一根白柱子', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  const view = () => h.window.document.getElementById('view-realrun');
  h.run(`rqExam = false; rqIdx = 0; rqAns = {}; rqSec = {};
    rqItems = [{ id: 1, answer: 'A', options: ['x','y','z','w'], stem: 's', material: '一大段材料' },
               { id: 2, answer: 'B', options: ['x','y','z','w'], stem: 's' }];
    rqRender();`);
  assert.ok(view().classList.contains('rq-3col'), '有材料的题没开三栏');
  h.run('rqIdx = 1; rqRender();');
  assert.ok(!view().classList.contains('rq-3col'),
    '这道题没材料还开着三栏，左边会空出一根 420px 的白柱子');
});
