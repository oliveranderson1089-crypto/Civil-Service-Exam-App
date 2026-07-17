/* 诗文积累：列表渲染 renderClassics。
 *
 * classics 改动 1 次、零测试。诗文正文按行渲染、每行都要转义（虽然是内置语料，
 * 但渲染管线该干净）；分类角标按类别取色、认不出的类别有兜底色；空态按 收藏/搜索
 * 分文案。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const D = (h) => h.window.document;
function render(h, items, total, state) {
  h.run(`clsState = ${JSON.stringify(Object.assign({ q: '', star: false, page: 1, pages: 1 }, state))};`);
  h.run('renderClassics')(items, total);
}

test('正文逐行渲染，每行转义', (t) => {
  const h = boot(); t.after(() => h.close());
  render(h, [{ id: 1, title: '测试', category: '唐诗', content: '第一行\n<img src=x>第二行' }], 1, { pages: 1 });
  const box = D(h).querySelector('#cls-list');
  assert.strictEqual(box.querySelectorAll('.cls-line').length, 2, '两行没各成一个 .cls-line');
  assert.strictEqual(box.querySelector('img'), null, '正文里的 img 活了');
});

test('分类角标取色，认不出的类别用兜底色', (t) => {
  const h = boot(); t.after(() => h.close());
  render(h, [{ id: 1, title: 'x', category: '唐诗', content: 'a' },
             { id: 2, title: 'y', category: '不存在的类', content: 'b' }], 2, { pages: 1 });
  const badges = D(h).querySelectorAll('.cls-badge');
  assert.match(badges[0].getAttribute('style'), /#c0392b/, '唐诗该用它的专属色');
  assert.match(badges[1].getAttribute('style'), /#888/, '认不出的类别该用兜底色，不是 undefined');
});

test('标题 / 分类里的 HTML 当文字', (t) => {
  const h = boot(); t.after(() => h.close());
  render(h, [{ id: 1, title: '<script>alert(1)</script>', category: '<b>x</b>', content: 'a' }], 1, { pages: 1 });
  const box = D(h).querySelector('#cls-list');
  assert.strictEqual(box.querySelector('script'), null);
  assert.strictEqual(box.querySelector('b'), null);
});

test('空态：收藏 / 搜索 分文案', (t) => {
  const h = boot(); t.after(() => h.close());
  render(h, [], 0, { star: true });
  assert.match(D(h).querySelector('#cls-empty').textContent, /收藏/);
  render(h, [], 0, { q: '李白' });
  assert.match(D(h).querySelector('#cls-empty').textContent, /李白/, '搜索空结果该带上搜索词');
});
