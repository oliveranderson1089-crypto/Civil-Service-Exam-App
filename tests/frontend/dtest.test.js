/* 每日巩固测试：判分 + 「何时揭晓答案」。
 *
 * dtest 有两种模式，判分口径不同：
 *   背题模式(study)：答案随题下发，前端自己比对 dtChosen 与 item.answer
 *   测试模式(test) ：答案不下发，交卷后服务端判分，结果在 dtResults 里
 * dtScore 要在两条路上都对；揭晓时机 dtRevealedAt 也按模式分岔。改动第 4 勤、零测试。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('dtScore·背题模式：比对 dtChosen 与答案，大小写不敏感', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`dtResults = null; dtMode = 'study';
    dtItems = [{ answer: 'A' }, { answer: 'b' }, { answer: 'C' }, { answer: 'D' }];
    dtChosen = { 0: 'A', 1: 'B', 2: 'x' };`);   // 第1题小写答案 vs 大写作答、第3题错、第4题没答
  assert.strictEqual(h.run('dtScore()'), 2, '答案 b / 作答 B 该算对（大小写不敏感），没答的不算分');
});

test('dtScore·测试模式：直接数 dtResults 里 correct 的条数', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`dtMode = 'test';
    dtResults = [{ correct: true }, { correct: false }, { correct: true }];
    dtItems = [{}, {}, {}]; dtChosen = {};`);
  assert.strictEqual(h.run('dtScore()'), 2);
});

test('dtScore·一题没答完也不炸，算 0', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`dtResults = null; dtMode = 'study'; dtItems = [{ answer: 'A' }, { answer: 'B' }]; dtChosen = {};`);
  assert.strictEqual(h.run('dtScore()'), 0);
});

test('dtRevealedAt·测试模式：交卷前全藏，交卷后全亮', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`dtMode = 'test'; dtSubmitted = false; dtRevealed = { 0: true };`);
  assert.strictEqual(h.run('dtRevealedAt(0)'), false, '测试模式没交卷就不该揭晓，哪怕 dtRevealed 里标了');
  h.run(`dtSubmitted = true;`);
  assert.strictEqual(h.run('dtRevealedAt(3)'), true, '交卷后每题都该揭晓');
});

test('dtRevealedAt·背题模式：逐题揭晓，只看这题答没答', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`dtMode = 'study'; dtSubmitted = false; dtRevealed = { 1: true };`);
  assert.strictEqual(h.run('dtRevealedAt(1)'), true, '背题模式答过的题该揭晓');
  assert.strictEqual(h.run('dtRevealedAt(0)'), false, '没答的题不该揭晓');
});
