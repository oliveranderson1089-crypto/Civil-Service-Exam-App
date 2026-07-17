/* 找要点（贯彻执行/概括题的两步练法）：勾选集合 frToggle + 页脚 frFoot。
 *
 * find 改动 1 次、15 个函数、零测试。第一步「只找不写」——在材料里点句子勾要点，
 * frToggle 维护一个已勾集合并实时更新计数；第二步照勾到的写。文种（doctype）来自
 * 数据、拼进提示语，要转义。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('frToggle：勾/取消维护集合，计数实时更新', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`fdPicked = new Set(); $('#fr-n') && ($('#fr-n').textContent = '0');`);
  // fr-n 由 frFoot 渲染出来；先渲染第一步再勾
  h.run(`fdStep = 1; fdPaper = { n_points: 5, sents: [] }; frFoot();`);
  h.run('frToggle(3, true)');
  h.run('frToggle(7, true)');
  assert.strictEqual(h.run('fdPicked.size'), 2);
  assert.strictEqual(h.window.document.querySelector('#fr-n').textContent, '2', '计数没跟上勾选');
  h.run('frToggle(3, false)');
  assert.strictEqual(h.run('fdPicked.size'), 1, '取消勾选没从集合里删掉');
  assert.strictEqual(h.window.document.querySelector('#fr-n').textContent, '1');
});

test('frToggle：重复勾同一句不会重复计数（Set 去重）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`fdPicked = new Set(); fdStep = 1; fdPaper = { n_points: 5, sents: [] }; frFoot();`);
  h.run('frToggle(3, true); frToggle(3, true)');
  assert.strictEqual(h.run('fdPicked.size'), 1);
});

test('frFoot 第一步：显示采分点数和已勾数', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`fdPicked = new Set([1, 2]); fdStep = 1; fdPaper = { n_points: 8, sents: [] }; frFoot();`);
  const html = h.window.document.querySelector('#fr-foot').innerHTML;
  assert.match(html, /共 8 个采分点/);
  assert.match(html, /id="fr-n">2</, '已勾数没显示');
});

test('frFoot 第二步：文种（doctype）转义后拼进提示', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`fdPicked = new Set();
    fdStep = 2;
    fdPaper = { doctype: '<img src=x onerror=alert(1)>', doctype_fmt: '', word_min: 200, word_max: 400, sents: [] };
    frFoot();`);
  const box = h.window.document.querySelector('#fr-foot');
  assert.strictEqual(box.querySelector('img'), null, 'doctype 里的 img 活了');
});
