/* 板块基础知识：renderBkb。
 *
 * basics 改动 1 次、零测试。renderBkb：AI 整理的知识点有则渲染（mdToHtml，已单独测过）、
 * 无则显示生成按钮；「我的补充」要点逐条渲染，要点内容用户手录，要转义。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('有 AI 整理则渲染，无则显示生成按钮', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`bkbData = { ai: '', points: [] }; renderBkb();`);
  assert.match(h.window.document.querySelector('#bkb-wrap').innerHTML, /生成/, '没 AI 时该显示生成按钮');
  h.run(`bkbData = { ai: '# 已整理', points: [] }; renderBkb();`);
  assert.match(h.window.document.querySelector('#bkb-wrap').innerHTML, /已整理/);
});

test('补充要点里的 HTML 当文字', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`bkbData = { ai: '', points: [{ id: 1, content: '<img src=x onerror=alert(1)>要点' }] }; renderBkb();`);
  const box = h.window.document.querySelector('#bkb-wrap');
  assert.strictEqual(box.querySelector('img'), null, '要点里的 img 活了');
  assert.match(box.textContent, /要点/);
});

test('没补充要点时显示引导文案，不是空白', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`bkbData = { ai: '', points: [] }; renderBkb();`);
  assert.match(h.window.document.querySelector('#bkb-wrap').textContent, /还没有补充|写点自己/);
});
