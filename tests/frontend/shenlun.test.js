/* 申论作答：字数统计。
 *
 * 申论/小题是改动第三勤的前端功能（13 次），零测试。翻它的 git log，
 * 改动几乎全绕着字数打转：「字数按文种真题规格」「材料字数对齐真题（每题约2000字）」
 * 「每则对齐真题单则字数」…… 因为考场上超字数是真扣分的，这个数字必须准。
 *
 * slWords 的口径：去掉所有空白再数。中文按字数、标点也算 —— 跟阅卷一致。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

function setup(h, wmin, wmax) {
  h.run(`slSetupAnswer(20, ${wmin}, ${wmax})`);
}
function type(h, text) {
  h.run(`$('#slg-a').value = ${JSON.stringify(text)}; slCountWords();`);
  const el = h.window.document.querySelector('#slg-count');
  return { cls: el.className, text: el.textContent };
}

test('slWords：空白一律不算（换行、空格、全角空格、Tab）', (t) => {
  const h = boot(); t.after(() => h.close());
  const w = h.run('slWords');
  assert.strictEqual(w('依法治国'), 4);
  assert.strictEqual(w('依法 治国'), 4, '半角空格算进去了');
  assert.strictEqual(w('依法\n治国'), 4, '换行算进去了 —— 分段作答的人会被误判超字');
  assert.strictEqual(w('依法\t治国'), 4);
  assert.strictEqual(w('  依法治国  '), 4, '首尾空格算进去了');
});

test('slWords：标点算字数（跟阅卷口径一致）', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.strictEqual(h.run('slWords')('依法治国，建设法治政府。'), 12);
});

test('slWords：空 / null / undefined 都算 0，不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  const w = h.run('slWords');
  assert.strictEqual(w(''), 0);
  assert.strictEqual(w(null), 0);
  assert.strictEqual(w(undefined), 0);
});

test('还没写字时只显示要求，不显示「还差 N 字」', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 100, 200);
  const r = type(h, '');
  assert.match(r.cls, /idle/);
  assert.strictEqual(r.text, '要求 100-200 字', '一个字没写就催「还差 100 字」很烦');
});

test('字数不够：显示还差多少', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 100, 200);
  const r = type(h, '字'.repeat(60));
  assert.match(r.cls, /low/);
  assert.match(r.text, /60 \/ 100-200 字/);
  assert.match(r.text, /还差 40 字/);
});

test('字数达标：明确告诉他达标了', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 100, 200);
  const r = type(h, '字'.repeat(150));
  assert.match(r.cls, /ok/);
  assert.match(r.text, /字数达标/);
});

test('超字数：显示超出多少（考场上这是要扣分的）', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 100, 200);
  const r = type(h, '字'.repeat(230));
  assert.match(r.cls, /high/);
  assert.match(r.text, /超出 30 字/);
});

test('边界：正好卡在下限 / 上限都算达标，差一个字就不算', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 100, 200);
  assert.match(type(h, '字'.repeat(100)).cls, /ok/, '正好 100 该算达标');
  assert.match(type(h, '字'.repeat(200)).cls, /ok/, '正好 200 该算达标');
  assert.match(type(h, '字'.repeat(99)).cls, /low/, '99 该提示还差 1 字');
  assert.match(type(h, '字'.repeat(201)).cls, /high/, '201 该提示超出 1 字');
});

test('换新题时字数框跟着重置（不然留着上一题的数）', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 100, 200);
  type(h, '字'.repeat(150));
  setup(h, 300, 500);                       // 换成另一道题
  const el = h.window.document.querySelector('#slg-count');
  assert.strictEqual(h.window.document.querySelector('#slg-a').value, '', '上一题的答案没清掉');
  assert.strictEqual(el.textContent, '要求 300-500 字', '还显示着上一题的字数要求');
  assert.strictEqual(h.window.document.querySelector('#slg-req').textContent, '（要求 300-500 字）');
});
