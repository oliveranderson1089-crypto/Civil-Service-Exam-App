/* 书签「看到哪了」：当前位置引用 bmRef。
 *
 * bookmarks 改动 2 次、零测试。bmRef 从当前视图栈顶算出一个「书签引用」：某些视图
 * （首页/账户/搜索等）不记书签（BM_SKIP），带子标识的视图（文档/新闻/板块）用各自的
 * id 当 ref，其余用标题兜底。算错了「继续上次」会跳错地方。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

function stackTop(h, view, title, extra) {
  h.run(`stack = [${JSON.stringify(Object.assign({ view, title: title || '' }, extra))}];`);
}

test('BM_SKIP 里的视图不记书签（首页/账户/搜索等）', (t) => {
  const h = boot(); t.after(() => h.close());
  stackTop(h, 'home', '首页');
  assert.strictEqual(h.run('bmRef()'), null, 'home 不该记书签');
  stackTop(h, 'account', '账户');
  assert.strictEqual(h.run('bmRef()'), null);
});

test('普通视图用标题兜底当 ref', (t) => {
  const h = boot(); t.after(() => h.close());
  stackTop(h, 'shenlun', '申论');
  const r = h.plain('bmRef()');
  assert.strictEqual(r.kind, 'shenlun');
  assert.ok(r.ref, 'ref 空了 —— 继续上次会跳不回来');
});

test('带子标识的视图用它的 id 当 ref（板块页记住是哪个板块）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`ckBoard = '成语';`);
  stackTop(h, 'ckboard', '常考词');
  assert.strictEqual(h.plain('bmRef()').ref, '成语', 'ckboard 没用 ckBoard 当 ref');
});

test('空栈不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`stack = [];`);
  assert.strictEqual(h.run('bmRef()'), null);
});
