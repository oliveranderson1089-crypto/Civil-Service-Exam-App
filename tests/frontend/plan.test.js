/* 备考规划：表单读写往返 plReadForm/plWriteForm + 脏检测。
 *
 * plan 改动 3 次、零测试。规划表单在「后端存的档案 ↔ 页面输入框」之间来回搬，
 * 读写口径必须对称，否则一进一出就把用户填的改了、或者「有没有改过」判错导致
 * 撤销按钮乱闪。「每天可学分钟数」有个兜底：填空/填 0 都回落到 120（真题按 6~8 小时
 * 排，0 分钟排不出计划）。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const V = { exam: '省考', exam_date: '2026-09-01', minutes: 300, weak: '资料分析', note: '晚上背' };

// #pl-exam 是空 <select>，选项平时由 fillPlanExams() 异步填。测试里手动塞一个，
// 否则 .value='省考' 会因为没有对应 option 而落空 —— 那是 select 的固有行为，不是 bug。
function seedExam(h) {
  h.run(`$('#pl-exam').innerHTML = '<option>省考</option><option>国考</option>';`);
}

test('写进表单再读回来，一字不差（往返对称）', (t) => {
  const h = boot(); t.after(() => h.close());
  seedExam(h);
  h.run(`plWriteForm(${JSON.stringify(V)})`);
  assert.deepStrictEqual(h.plain('plReadForm()'), V, '写进去和读出来对不上 —— 保存会把用户填的改掉');
});

test('minutes 兜底：填空 / 填 0 都回落 120', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`plWriteForm(${JSON.stringify(Object.assign({}, V, { minutes: 0 }))})`);
  assert.strictEqual(h.window.document.querySelector('#pl-min').value, '120', 'minutes=0 没回落到 120');
  h.run(`$('#pl-min').value = '';`);
  assert.strictEqual(h.run('plReadForm().minutes'), 120, '清空后读出来该是 120，不是 NaN/0');
});

test('weak / note 读时去空白（前后空格不该算内容）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`plWriteForm(${JSON.stringify(V)}); $('#pl-weak').value = '  资料  ';`);
  assert.strictEqual(h.run('plReadForm().weak'), '资料');
});

test('plDirty：写入即基线时不算脏，改一个字段才算脏', (t) => {
  const h = boot(); t.after(() => h.close());
  seedExam(h);
  h.run(`plFormBase = ${JSON.stringify(V)}; plWriteForm(${JSON.stringify(V)});`);
  assert.strictEqual(h.run('plDirty()'), false, '刚写入和基线一致，不该判脏（撤销按钮会乱闪）');
  h.run(`$('#pl-note').value = '改了';`);
  assert.strictEqual(h.run('plDirty()'), true, '改了字段却没判脏');
});
