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

test('左栏和底栏是同一份 TAB_DEFS 的两个形态，条目一一对应', (t) => {
  const h = boot(); t.after(() => h.close());
  const bottom = $$(h, '#tabbar [data-tb]').map(b => b.dataset.tb);
  const rail = $$(h, '#siderail .sr-t').map(b => b.dataset.tb);
  assert.deepStrictEqual(rail, bottom, '两边的标签对不上——说明有一边是手写的');
  assert.deepStrictEqual($$(h, '#siderail .sr-t i').map(b => b.textContent),
    $$(h, '#tabbar [data-tb] i').map(b => b.textContent));
});

test('左栏点击走的是同一条路：内容和高亮都跟着变', (t) => {
  const h = boot(); t.after(() => h.close());
  $(h, '#siderail [data-tb="acc"]').click();
  assert.strictEqual(h.window.document.body.dataset.view, 'tab');
  assert.strictEqual(h.run('stack[stack.length-1].tab'), 'acc');
  assert.ok($(h, '#siderail [data-tb="acc"]').classList.contains('on'));
  assert.ok($(h, '#tabbar [data-tb="acc"]').classList.contains('on'),
    '底栏没跟着亮——两个形态的状态该是同一份');
});

test('左栏的「今日」和底栏一样回到首页栈底', (t) => {
  const h = boot(); t.after(() => h.close());
  $(h, '#siderail [data-tb="drill"]').click();
  $(h, '#siderail [data-tb="today"]').click();
  assert.strictEqual(h.run('stack.length'), 1);
  assert.strictEqual(h.window.document.body.dataset.view, 'home');
});

test('左栏多出一层：当前标签的分组列出来，且只有当前那个展开', (t) => {
  const h = boot(); t.after(() => h.close());
  $(h, '#siderail [data-tb="acc"]').click();
  const subs = $$(h, '#siderail [data-srsub="acc"] .sr-g').map(b => b.textContent);
  assert.ok(subs.includes('言语') && subs.includes('时政'), '分组没列出来：' + subs.join('/'));
  assert.deepStrictEqual($$(h, '#siderail [data-srsub="drill"] .sr-g'), [],
    '没打开的标签也把分组展开了，左栏会长得没边');

  // 分组锚点要真能对上正文里的标题
  subs.forEach((_, i) => assert.ok($(h, '#tg-' + i), '正文里没有 #tg-' + i + '，点了跳不过去'));
});

test('切到别的标签，上一个标签的分组要收起来', (t) => {
  const h = boot(); t.after(() => h.close());
  $(h, '#siderail [data-tb="acc"]').click();
  $(h, '#siderail [data-tb="lib"]').click();
  assert.deepStrictEqual($$(h, '#siderail [data-srsub="acc"] .sr-g'), []);
  assert.ok($$(h, '#siderail [data-srsub="lib"] .sr-g').length > 0);
});

test('离开标签页后分组锚点要撤掉：它们已经不指向当前内容了', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  $(h, '#siderail [data-tb="acc"]').click();
  assert.ok($$(h, '#siderail .sr-g').length > 0);
  h.run("push({ view: 'idiom' })");
  assert.deepStrictEqual($$(h, '#siderail .sr-g'), [],
    '进了成语积累，左栏还挂着「积累」页的分组锚点，点了会跳到不存在的地方');
});

test('沉浸式页面左栏一起让位', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  $(h, '#siderail [data-tb="drill"]').click();
  assert.ok(!$(h, '#siderail').classList.contains('hidden'));
  h.run("push({ view: 'realrun' })");
  assert.ok($(h, '#siderail').classList.contains('hidden'), '做题页左栏还占着 206px');
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
  assert.ok(/body\.has-tabs main\{padding-left:206px/.test(CSS),
    '正文没给左栏让位，会被压在下面');
  assert.ok(/body\.has-tabs #view-home,body\.has-tabs #view-tab,body\.has-tabs #view-allfeats\{[^}]*max-width/.test(CSS),
    '导航页在宽屏上没限宽，一行几百字符没法读');
});

test('顶栏的「首页」在有常驻导航时收掉：它和「今日」是同一个去处', () => {
  assert.ok(/body\.has-tabs #home-btn\{display:none/.test(CSS),
    '左栏有「今日」、顶栏还有「首页」，两套导航并存');
  // 「账户」「后台」只在手机收（进了「我的」），电脑上留着当快捷入口
  assert.ok(!/body\.has-tabs #account-btn/.test(CSS), '电脑上把「账户」也收了，那儿并没有替代入口');
});

test('草稿纸在电脑上默认停右半屏，手机仍是下半屏', () => {
  const js = fs.readFileSync(path.join(__dirname, '../../static/js/pad.js'), 'utf8');
  assert.match(js, /createDock\(\$\('#pad'\), 'padDock', IS_MOBILE \? 'bottom' : 'right'/,
    '草稿纸在电脑上还是默认盖住下半屏——宽度够的时候该和题目并排');
});
