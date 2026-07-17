/* 知识库文档：块的规整 normalizeBlocks + 渲染 blockHtml + stripHtml。
 *
 * kb 改动 2 次、34 个函数、零测试。文档是块的数组，来回在「后端存的 JSON ↔ 前端块对象」
 * 之间转。normalizeBlocks 是入口消毒：补全缺字段、认得旧格式、非数组不炸。blockHtml
 * 按块类型渲染，元数据（文件名/状态标签）必须转义。
 *
 * 一条边界写进注释：blk-edit 里的 b.text 和表格单元格是 contenteditable 富文本、
 * 存的就是 HTML，**故意不转义**（用户要加粗/列表）。kb 文档是本人私有、不共享，所以
 * 这是 self-XSS，可接受。真要哪天做了文档分享，这里得改。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('normalizeBlocks：补全缺失字段（id/type/text/data 都得有）', (t) => {
  const h = boot(); t.after(() => h.close());
  const out = h.run('normalizeBlocks')([{ text: '只有正文' }]);
  assert.strictEqual(out.length, 1);
  assert.ok(out[0].id, '没补 id —— 后面按 id 找块会全乱');
  assert.strictEqual(out[0].type, 'text', 'type 缺省该是 text');
  // 跨 realm 的 {} 原型不同，deepStrictEqual 会误判 —— 只断言「是空对象」
  assert.strictEqual(Object.keys(out[0].data).length, 0, 'data 缺省该是空对象');
});

test('normalizeBlocks：非数组 / null 返回空数组，不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  const n = h.run('normalizeBlocks');
  assert.strictEqual(n(null).length, 0);
  assert.strictEqual(n(undefined).length, 0);
  assert.strictEqual(n('不是数组').length, 0);
});

test('normalizeBlocks：已有 id 的块保留原 id（不能重新生成，会断掉引用）', (t) => {
  const h = boot(); t.after(() => h.close());
  const out = h.run('normalizeBlocks')([{ id: 'keep-me', type: 'h1', text: '标题', data: { indent: 2 } }]);
  assert.strictEqual(out[0].id, 'keep-me');
  assert.strictEqual(out[0].data.indent, 2, 'data 被清掉了');
});

test('stripHtml：扒掉标签只留文字，用来判断块是不是空的', (t) => {
  const h = boot(); t.after(() => h.close());
  const s = h.run('stripHtml');
  assert.strictEqual(s('<b>你好</b> 世界'), '你好 世界');
  assert.strictEqual(s('<br><div></div>'), '', '只有标签没文字该算空');
  assert.strictEqual(s(''), '');
  assert.strictEqual(s(null), '');
});

test('blockHtml：文件名转义（元数据来自上传，可能带引号/尖括号）', (t) => {
  const h = boot(); t.after(() => h.close());
  const html = h.run('blockHtml')({ id: 'b1', type: 'file', data: { ext: '.pdf', name: '<img src=x>"坏名', size: 100 } });
  const box = h.window.document.createElement('div'); box.innerHTML = html;
  assert.strictEqual(box.querySelector('img'), null, '文件名里的 img 活了');
  assert.match(box.querySelector('.bf-name').textContent, /<img src=x/);
});

test('blockHtml：divider / todo 各按类型渲染', (t) => {
  const h = boot(); t.after(() => h.close());
  const div = h.run('blockHtml')({ id: 'b1', type: 'divider', data: {} });
  assert.match(div, /<hr>/);
  const todo = h.run('blockHtml')({ id: 'b2', type: 'todo', text: '买菜', data: { done: true } });
  const box = h.window.document.createElement('div'); box.innerHTML = todo;
  assert.ok(box.querySelector('.blk.todo.done'), '已完成的待办没加 done 类');
});
