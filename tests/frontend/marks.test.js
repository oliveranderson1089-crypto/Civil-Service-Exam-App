/* 互动标记：正文取文 mkText / mkNodes。
 *
 * marks 改动 1 次、10 个函数、零测试。它是「在阅读区点句子做标记」的底层：从 DOM 里
 * 抽出可标记的正文，**跳过按钮/输入框/导航条/已标记的 mark** 这些不该被当正文的东西，
 * 段与段之间可插分隔符。抽错了，后面按字符偏移定位标记就会整段错位。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

function root(h, html) {
  const d = h.window.document.createElement('div');
  d.innerHTML = html;
  h.window.document.body.appendChild(d);
  return d;
}

test('mkText：跳过按钮/输入框，只取正文文字', (t) => {
  const h = boot(); t.after(() => h.close());
  const r = root(h, '<p>依法治国</p><button>收藏</button><p>建设法治</p><input value="x">');
  const s = h.run('mkText')(r, null, null);
  assert.match(s, /依法治国/);
  assert.match(s, /建设法治/);
  assert.doesNotMatch(s, /收藏/, '按钮文字被当成正文抽进去了 —— 标记偏移会错位');
});

test('mkText：纯空白节点不计入', (t) => {
  const h = boot(); t.after(() => h.close());
  const r = root(h, '<p>甲</p>\n\n   \n<p>乙</p>');
  assert.strictEqual(h.run('mkText')(r, null, null), '甲乙', '空白节点混进正文了');
});

test('mkText：给了分隔符则段间插入（段落边界不粘连）', (t) => {
  const h = boot(); t.after(() => h.close());
  const r = root(h, '<p>第一段</p><p>第二段</p>');
  assert.strictEqual(h.run('mkText')(r, null, '\n'), '第一段\n第二段');
});

test('mkNodes：返回每段文字节点及其字符起点（供偏移定位）', (t) => {
  const h = boot(); t.after(() => h.close());
  const r = root(h, '<p>依法治国</p><p>建设法治</p>');
  const nodes = h.run('mkNodes')(r, null, null);
  assert.strictEqual(nodes.length, 2);
  assert.strictEqual(nodes[0].start, 0);
  assert.strictEqual(nodes[1].start, 4, '第二段起点该接在第一段（4 字）之后');
});
