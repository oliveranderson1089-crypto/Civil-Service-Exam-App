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
