/* 内容详情页三兄弟：works / fanwen / policydocs 的 render*。
 *
 * 这仨改动各 1 次、零测试，结构几乎同构：标题 esc、正文按段过 emKey（已单独测过）、
 * AI 解读有则渲染 mdToHtml（已单独测过）、无则显示「生成」按钮。这里合并守两件事：
 *   1. 标题 / 来源链接 esc（policydocs、fanwen 的 source_url 进了 href，是注入面）
 *   2. AI 有/无 的分支（有解读显示内容、没有显示生成按钮）
 * 三个共用同一套 poly-* 结构，一个文件覆盖，不各写一份近乎重复的。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

// [模块状态变量, 渲染函数, wrap 的 id, AI 字段, 有没有 source_url]
const PAGES = [
  { state: 'wkData', fn: 'renderWork', wrap: '#wk-wrap', ai: 'interpretation', src: false },
  { state: 'fwData', fn: 'renderFanwen', wrap: '#fw-wrap', ai: 'analysis', src: true },
  { state: 'polyData', fn: 'renderPolicyDoc', wrap: '#poly-wrap', ai: 'interpretation', src: true },
];

for (const p of PAGES) {
  test(`${p.fn}：标题里的 HTML 当文字`, (t) => {
    const h = boot(); t.after(() => h.close());
    h.run(`${p.state} = { title: '<img src=x onerror=alert(1)>标题', content: '正文一段', book: '出处', source_url: '/x' };`);
    h.run(`${p.fn}()`);
    const box = h.window.document.querySelector(p.wrap);
    assert.strictEqual(box.querySelector('img'), null, `${p.fn} 标题里的 img 活了`);
  });

  test(`${p.fn}：有 AI 解读则渲染内容，无则显示生成按钮`, (t) => {
    const h = boot(); t.after(() => h.close());
    h.run(`${p.state} = { title: 't', content: 'c', book: 'b', source_url: '/x', ${p.ai}: '' };`);
    h.run(`${p.fn}()`);
    assert.match(h.window.document.querySelector(p.wrap).innerHTML, /生成/, '没 AI 时该显示生成按钮');
    h.run(`${p.state} = { title: 't', content: 'c', book: 'b', source_url: '/x', ${p.ai}: '# 已有解读' };`);
    h.run(`${p.fn}()`);
    assert.match(h.window.document.querySelector(p.wrap).innerHTML, /已有解读/, '有 AI 解读却没渲染出来');
  });

  if (p.src) {
    test(`${p.fn}：来源链接 URL 转义（进了 href，是注入面）`, (t) => {
      const h = boot(); t.after(() => h.close());
      h.run(`${p.state} = { title: 't', content: 'c', book: 'b', source_url: 'x"><img src=y onerror=alert(1)>' };`);
      h.run(`${p.fn}()`);
      assert.strictEqual(h.window.document.querySelector(p.wrap).querySelector('img'), null,
        'source_url 里的双引号闭合了 href，注入出 img');
    });
  }
}
