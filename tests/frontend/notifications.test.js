/* 消息：未读徽标 setNtfDot + 通知跳转 ntfGo。
 *
 * notifications 改动 1 次、零测试。徽标：0 条不显示、封顶到 99+；通知点进来按
 * 「板块:参数」路由到对应页面，认不出的 link 给个交代而不是静默无反应。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('setNtfDot：0 条隐藏、正数显示、超 99 显示 99+', (t) => {
  const h = boot(); t.after(() => h.close());
  const dot = h.window.document.querySelector('#notify-dot');
  h.run('setNtfDot(0)');
  assert.ok(dot.classList.contains('hidden'), '0 条还显示徽标');
  assert.strictEqual(dot.textContent, '');
  h.run('setNtfDot(5)');
  assert.ok(!dot.classList.contains('hidden'));
  assert.strictEqual(dot.textContent, '5');
  h.run('setNtfDot(150)');
  assert.strictEqual(dot.textContent, '99+', '超过 99 该封顶成 99+，不然徽标撑爆');
});

test('ntfGo：认不出的 link 给提示，不静默无反应', (t) => {
  const h = boot(); t.after(() => h.close());
  let toasted = '';
  h.run(`ME = { id: 1 };`);                     // 绕过「等 ME 到位」的重试
  h.window.toast = (m) => { toasted = m; };
  h.run(`toast = window.toast;`);
  h.run(`ntfGo('不存在的板块:x')`);
  assert.match(toasted, /没有可跳转|没有/, '认不出的通知点了没反应，用户会以为卡住了');
});

test('ntfGo：link 为空不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`ME = { id: 1 }; toast = () => {};`);
  assert.doesNotThrow(() => h.run(`ntfGo('')`));
  assert.doesNotThrow(() => h.run(`ntfGo(null)`));
});
