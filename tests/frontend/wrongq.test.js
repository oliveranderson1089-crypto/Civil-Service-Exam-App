/* 错题本：分页边界 + 空态 + 转义。
 *
 * wrongq 改动 2 次、零测试。它的翻页按钮在边界上要正确禁用（第一页禁「上一页」、
 * 末页禁「下一页」），单页时整个翻页条藏起来；空结果按 收藏/搜索/全新 给不同文案。
 * 题面来自用户手录，进 innerHTML 前必须转义。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const D = (h) => h.window.document;

function render(h, items, total, state) {
  h.run(`wqState = ${JSON.stringify(Object.assign({ board: '', q: '', star: false, page: 1, pages: 1 }, state))};`);
  h.run('renderWq')(items, total);
}

test('翻页边界：第一页禁「上一页」，末页禁「下一页」', (t) => {
  const h = boot(); t.after(() => h.close());
  const items = [{ id: 1, question: 'x' }];
  render(h, items, 30, { page: 1, pages: 3 });
  assert.strictEqual(D(h).querySelector('#wq-prev').disabled, true, '第一页还能点「上一页」');
  assert.strictEqual(D(h).querySelector('#wq-next').disabled, false);
  render(h, items, 30, { page: 3, pages: 3 });
  assert.strictEqual(D(h).querySelector('#wq-next').disabled, true, '末页还能点「下一页」');
  assert.strictEqual(D(h).querySelector('#wq-prev').disabled, false);
});

test('只有一页时整个翻页条藏起来', (t) => {
  const h = boot(); t.after(() => h.close());
  render(h, [{ id: 1, question: 'x' }], 1, { page: 1, pages: 1 });
  assert.ok(D(h).querySelector('#wq-pager').classList.contains('hidden'));
});

test('空结果的文案按场景分：收藏 / 搜索 / 全新', (t) => {
  const h = boot(); t.after(() => h.close());
  render(h, [], 0, { star: true });
  assert.match(D(h).querySelector('#wq-empty').textContent, /收藏/);
  render(h, [], 0, { q: '行测' });
  assert.match(D(h).querySelector('#wq-empty').textContent, /没有匹配/);
  render(h, [], 0, {});
  assert.match(D(h).querySelector('#wq-empty').textContent, /还没有错题/);
});

test('题面里的 HTML 当文字，不进 DOM', (t) => {
  const h = boot(); t.after(() => h.close());
  render(h, [{ id: 1, question: '<img src=x onerror=alert(1)>选项 A' }], 1, { pages: 1 });
  const box = D(h).querySelector('#wq-list');
  assert.strictEqual(box.querySelector('img'), null, '题面里的 img 活了');
  assert.match(box.querySelector('.wq-q').textContent, /<img src=x/, '该原样显示成文字');
});

test('没题面的图片题显示占位，不显示 undefined', (t) => {
  const h = boot(); t.after(() => h.close());
  render(h, [{ id: 1, question: '' }], 1, { pages: 1 });
  assert.match(D(h).querySelector('#wq-q, .wq-q').textContent, /图片题/);
});
