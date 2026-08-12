/* 面包屑（对齐目标效果图）。
 *
 * 栈本身就是路径，所以这一层唯一会出错的地方是「路径和栈说的不是一回事」：
 * 少一层、多一层、或者点了跳到别处。另外两条是产品判断：
 * 首页上挂一个「公考助手 ›」是废话（只在两层以上出现），
 * 以及宽度必须跟着当前视图走——各视图 max-width 各不相同，
 * 在 CSS 里另抄一份对照表迟早对不上。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const $ = (h, s) => h.window.document.querySelector(s);
const $$ = (h, s) => [...h.window.document.querySelectorAll(s)];
const parts = (h) => $$(h, '#crumb .cb-i').map(x => x.textContent);

test('首页不出面包屑：挂一个「公考助手 ›」是废话', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('goHome()');
  assert.ok($(h, '#crumb').classList.contains('hidden'));
  assert.ok(!h.window.document.body.classList.contains('has-crumb'));
});

test('路径就是栈：进几层显示几层，最后一层是当前位置', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run('goHome()');
  $(h, '#siderail .sr-g-h[data-tb="drill"]').click();
  h.run("push({ view: 'realq', title: '历年真题' })");
  h.run("push({ view: 'realrun', title: '2024 国考行测' })");
  assert.deepStrictEqual(parts(h), ['公考助手', '练', '历年真题', '2024 国考行测']);
  assert.ok($$(h, '#crumb .cb-i.cur').length === 1);
  assert.strictEqual($(h, '#crumb .cb-i.cur').textContent, '2024 国考行测');
});

test('点中间那层就退回那层，不是退一步也不是回首页', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run('goHome()');
  $(h, '#siderail .sr-g-h[data-tb="drill"]').click();
  h.run("push({ view: 'realq', title: '历年真题' })");
  h.run("push({ view: 'realrun', title: '2024 国考行测' })");
  $$(h, '#crumb .cb-i')[1].click();          // 点「练」
  assert.deepStrictEqual(h.plain('stack.map(s => s.view)'), ['home', 'tab']);
  assert.strictEqual(h.window.document.body.dataset.view, 'tab');
});

test('点当前这层不动：它就是你现在待的地方', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run('goHome()');
  h.run("push({ view: 'realq', title: '历年真题' })");
  const before = h.plain('stack.map(s => s.view)');
  $(h, '#crumb .cb-i.cur').click();
  assert.deepStrictEqual(h.plain('stack.map(s => s.view)'), before);
});

test('标题里的 HTML 当文字，不进 DOM', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run('goHome()');
  h.run("push({ view: 'realq', title: '<img src=x onerror=alert(1)>卷' })");
  assert.strictEqual($(h, '#crumb').querySelector('img'), null);
  assert.match($(h, '#crumb').textContent, /<img src=x/);
});

test('宽度照抄当前视图，不在 CSS 里另抄一份对照表', () => {
  const js = require('fs').readFileSync(
    require('path').join(__dirname, '../../static/js/shell.js'), 'utf8');
  assert.match(js, /getComputedStyle\(v\)/,
    '面包屑没读当前视图算出来的宽度 —— 各视图 max-width 各不相同，另抄一份迟早对不上');
  const css = require('fs').readFileSync(
    require('path').join(__dirname, '../../static/style.css'), 'utf8');
  assert.match(css, /body\.has-crumb \.view\{padding-top/,
    '面包屑出现时视图没收掉上边距，会和面包屑挤成两行空白');
});

test('手机端聊天页不画面包屑：顶栏和会话顶栏已经把名字写过两遍了', (t) => {
  const h = boot({ mobile: true }); t.after(() => h.close());
  h.run("stack.length=0; stack.push({view:'me',title:'我的'},{view:'chat',title:'聊天'}," +
    "{view:'chat',room:9,title:'某某'}); renderCrumb(stack[stack.length-1])");
  assert.ok($(h, '#crumb').classList.contains('hidden'),
    '手机端聊天页还在画面包屑 —— 同一句话说三遍，白占一整行');
  // 别处照旧：路径深的地方它是有用的
  h.run("stack.length=0; stack.push({view:'me',title:'我的'},{view:'kb',title:'知识库'}); " +
    "renderCrumb(stack[stack.length-1])");
  assert.ok(!$(h, '#crumb').classList.contains('hidden'), '把别处的面包屑也一起关掉了');
});
