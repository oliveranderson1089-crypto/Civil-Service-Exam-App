/* 刷题运行页：renderQuiz。
 *
 * quiz 改动 3 次、零测试（dtMaterial 那半已由 dtmaterial.test 覆盖）。renderQuiz 要认三种
 * 材料：图形推理的图（JSON figs）/ 资料分析的表格（JSON）/ 老的纯文字，靠 material 是否
 * 以 { 开头来分。JSON 坏了不能整页崩，得当纯文字兜住。空题不显示空白页。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

function run(h, qs, idx, set) {
  h.run(`qz = { set: ${JSON.stringify(set || { kind: '行测' })}, qs: ${JSON.stringify(qs)}, idx: ${idx || 0} };`);
  h.run('renderQuiz()');
  return h.window.document.querySelector('#qzr-wrap');
}

test('没题目时显示占位，不是空白页', (t) => {
  const h = boot(); t.after(() => h.close());
  const wrap = run(h, [], 0);
  assert.match(wrap.textContent, /没有题目/);
});

test('纯文字材料照常渲染', (t) => {
  const h = boot(); t.after(() => h.close());
  const wrap = run(h, [{ question: '下列哪项正确', options: ['甲', '乙'], material: '给定资料：某地推进…', module: '常识' }], 0);
  assert.match(wrap.textContent, /下列哪项正确/);
});

test('material 是坏 JSON 时不整页崩（当纯文字兜住）', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.doesNotThrow(() => run(h, [{ question: '题干', options: ['甲', '乙'], material: '{ 这不是合法JSON', module: '常识' }], 0),
    'material JSON 解析失败就把整页炸了');
});

test('题干里的 HTML 当文字', (t) => {
  const h = boot(); t.after(() => h.close());
  const wrap = run(h, [{ question: '<img src=x onerror=alert(1)>选哪个', options: ['甲', '乙'], module: '常识' }], 0);
  assert.strictEqual(wrap.querySelector('img'), null, '题干里的 img 活了');
});
