/* 公文高频表达：卡片渲染 gwCard。
 *
 * gongwen 改动 1 次、零测试。gwCard 把「场景 + 高频短语 + 示范」渲染成卡片。
 * 短语是一串用 顿号/逗号 分隔的词，要切成一个个 chip；场景/文种/示范都可能来自
 * AI 生成，拼进 innerHTML 前要转义。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

function card(h, it) {
  const box = h.window.document.createElement('div');
  box.innerHTML = h.run('gwCard')(it);
  return box;
}

test('短语按 顿号 / 中英文逗号 切成 chip，去掉空项', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = card(h, { id: 1, scene: '汇报', phrases: '现将有关情况报告如下、特此报告，妥否，请批示' });
  const chips = [...box.querySelectorAll('.gw-chip')].map(c => c.textContent);
  assert.deepStrictEqual(chips, ['现将有关情况报告如下', '特此报告', '妥否', '请批示']);
});

test('空短语串不炸，也不渲染出空 chip', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = card(h, { id: 1, scene: '汇报', phrases: '、，,  ,' });
  assert.strictEqual(box.querySelectorAll('.gw-chip').length, 0, '全是分隔符却渲染出了空 chip');
});

test('场景 / 示范里的 HTML 当文字，不进 DOM', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = card(h, { id: 1, scene: '<img src=x onerror=alert(1)>', phrases: 'a', example: '<script>alert(1)</script>' });
  assert.strictEqual(box.querySelector('img'), null, 'scene 里的 img 活了');
  assert.strictEqual(box.querySelector('script'), null, 'example 里的 script 活了');
});

test('AI 来源的卡片才有删除按钮，真题来源没有', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.ok(card(h, { id: 1, scene: 'x', phrases: 'a', source: 'ai' }).querySelector('.gw-del'), 'AI 卡片该有删除按钮');
  assert.strictEqual(card(h, { id: 1, scene: 'x', phrases: 'a', source: 'real' }).querySelector('.gw-del'), null, '真题卡片不该能删');
});
