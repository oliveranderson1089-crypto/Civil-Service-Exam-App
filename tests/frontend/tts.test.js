/* 朗读器语速 Reader.rate + 循环。
 *
 * tts 改动 2 次、零测试，大半是 DOM/朗读桥胶水。可测的纯逻辑是语速：一个固定档位表
 * READ_RATES，Reader.rate() 取当前档，点一下按 (rateIdx+1)%len 循环回到头。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('Reader.rate() 取当前档位对应的倍速', (t) => {
  const h = boot(); t.after(() => h.close());
  const rates = h.plain('READ_RATES');
  for (let i = 0; i < rates.length; i++) {
    h.run(`Reader.rateIdx = ${i}`);
    assert.strictEqual(h.run('Reader.rate()'), rates[i], `第 ${i} 档倍速对不上`);
  }
});

test('语速循环：点「语速」按钮逐档切，最后一档再点绕回第一档', (t) => {
  const h = boot(); t.after(() => h.close());
  const len = h.run('READ_RATES.length');
  const btn = h.window.document.querySelector('#read-rate');
  assert.ok(btn, '#read-rate 按钮没了？循环没法测');
  h.run(`Reader.rateIdx = ${len - 1}`);
  btn.click();   // 真的走源码那步 (rateIdx+1)%len，不是在测试里重写公式
  assert.strictEqual(h.run('Reader.rateIdx'), 0, '最后一档再点没绕回第一档 —— 取模丢了会越界成 undefined×');
  assert.match(btn.textContent, /×/, '按钮该显示当前倍速');
  btn.click();
  assert.strictEqual(h.run('Reader.rateIdx'), 1, '再点该到第二档');
});

test('READ_RATES 第一档是 1.0（正常语速起步）', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.strictEqual(h.run('READ_RATES[0]'), 1.0, '默认起步不是正常语速会吓人一跳');
});
