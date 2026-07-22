/* dtMaterial：资料分析材料的渲染 + 「两题共用一份材料」的折叠。
 *
 * dtest / drill / quiz 三家共用这一个渲染器。它原先靠一个模块级全局 _dtLastMat 记
 * 「上一份材料」，逼着三家在开新一轮前各自记得清空它 —— 谁忘了清，新一轮第一题就把
 * 材料折叠成指向空气的「↑ 根据上面这份材料作答」（drill.js 的注释「别被上一题的缓存
 * 吃掉」就是踩过之后补的）。已改成把「上一份」显式当参数传进来：去重只看相邻两题、
 * 不留跨渲染的状态，也就没得可忘。这组测试钉住那个不变量。
 *
 * 折叠语义（与改造前逐一比对过，等价）：折叠 iff 传入的 prev 与当前材料 JSON 相等。
 * 单题渲染不传 prev → 永远真渲染；列表渲染传 arr[i-1].material。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const A = { type: 'table', title: '甲表', headers: ['项目', '2023'], rows: [['GDP', '100']] };
const B = { type: 'bar', title: '乙图', labels: ['一季度'], series: [{ name: '增速', data: [7.2] }] };
const folded = (s) => s.includes('dt-same');

test('首题（prev 为空）永远真渲染，绝不折叠 —— 这就是 bug 的修复点', (t) => {
  const h = boot(); t.after(() => h.close());
  const dtMaterial = h.run('dtMaterial');
  assert.ok(!folded(dtMaterial(A, 0, null)), '第一题就折叠成「↑ 根据上面这份材料作答」，上面根本没有材料');
  assert.ok(!folded(dtMaterial(A, 0)), '不传 prev（单题渲染）也不该折叠');
  assert.match(dtMaterial(A, 0, null), /甲表/, '首题该把材料标题渲染出来');
});

test('相邻两题共用同一份材料 → 折叠，不重复渲染整张表', (t) => {
  const h = boot(); t.after(() => h.close());
  const dtMaterial = h.run('dtMaterial');
  const out = dtMaterial(A, 1, A);
  assert.ok(folded(out), '同材料没折叠，会把整张表重复画一遍');
  assert.doesNotMatch(out, /<table/, '折叠了却还渲染了表格');
});

test('相邻两题材料不同 → 真渲染，不误折叠', (t) => {
  const h = boot(); t.after(() => h.close());
  const dtMaterial = h.run('dtMaterial');
  assert.ok(!folded(dtMaterial(B, 1, A)), '不同材料被误折叠 —— 用户看不到第二份材料');
  assert.match(dtMaterial(B, 1, A), /乙图/);
});

test('无状态：两次独立的首题渲染互不影响（旧全局版这里会把第二次误折叠）', (t) => {
  const h = boot(); t.after(() => h.close());
  const dtMaterial = h.run('dtMaterial');
  dtMaterial(A, 0, null);                       // 第一轮渲染 A，旧版会把 A 存进全局
  const second = dtMaterial(A, 0, null);        // 另起一轮，仍是首题
  assert.ok(!folded(second), '第二轮的首题继承了上一轮的残留 —— 正是无状态改造要根除的');
});

test('无材料返回空串，不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  const dtMaterial = h.run('dtMaterial');
  assert.strictEqual(dtMaterial(null, 0, A), '');
  assert.strictEqual(dtMaterial(undefined, 0, null), '');
});

test('折叠只认「相邻」：A、B、A 三题，第三题的 A 不该因为第一题也是 A 就折叠', (t) => {
  const h = boot(); t.after(() => h.close());
  const dtMaterial = h.run('dtMaterial');
  // 模拟列表渲染：prev 传的是「紧邻的上一题」的材料
  const items = [A, B, A];
  const outs = items.map((m, i) => dtMaterial(m, i, i ? items[i - 1] : null));
  assert.ok(!folded(outs[0]), '第一题 A');
  assert.ok(!folded(outs[1]), '第二题 B（与 A 不同）');
  assert.ok(!folded(outs[2]), '第三题 A：紧邻的上一题是 B，不该折叠 —— 折叠语义只看相邻');
});

/* ---- 真题的材料是**纯文本**，不是 figgen 那种结构体（P3 题源开关引入） ---- */

test('字符串材料要渲染成文字，不能掉进图表分支', (t) => {
  const h = boot(); t.after(() => h.close());
  const dtMaterial = h.run('dtMaterial');
  const out = dtMaterial('2023 年甲市地区生产总值 1000 亿元，同比增长 5.2%。', 0, null);
  assert.match(out, /1000 亿元/, '文字材料没渲染出来');
  assert.ok(!out.includes('<svg'), '掉进图表分支了，会画出一张空图');
  assert.ok(!out.includes('看数据表'), '空的「看数据表」按钮不该出现');
});

test('文字材料要保住自然段，别压成一坨', (t) => {
  const h = boot(); t.after(() => h.close());
  const dtMaterial = h.run('dtMaterial');
  const out = dtMaterial('一、工业情况。\n产值增长。\n\n二、农业情况。', 0, null);
  assert.equal((out.match(/<p>/g) || []).length, 2, '空行分段没生效');
  assert.match(out, /<br>/, '段内的单换行该是软换行');
});

test('文字材料也要转义，别把材料里的尖括号当标签', (t) => {
  const h = boot(); t.after(() => h.close());
  const dtMaterial = h.run('dtMaterial');
  const out = dtMaterial('增速 <script>alert(1)</script> 如上', 0, null);
  assert.ok(!out.includes('<script>'), 'XSS：材料里的标签被原样输出了');
});

test('空白字符串材料当没有材料', (t) => {
  const h = boot(); t.after(() => h.close());
  const dtMaterial = h.run('dtMaterial');
  assert.equal(dtMaterial('   \n  ', 0, null), '');
});

test('相邻两题共用同一段文字材料也要折叠', (t) => {
  const h = boot(); t.after(() => h.close());
  const dtMaterial = h.run('dtMaterial');
  const s = '同一份文字资料';
  assert.ok(folded(dtMaterial(s, 1, s)), '文字材料没走折叠，长材料会重复渲染两遍');
});
