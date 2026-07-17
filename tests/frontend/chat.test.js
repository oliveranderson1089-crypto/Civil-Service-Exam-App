/* 聊天：头像渲染 avHtml。
 *
 * chat 改动 2 次、零测试，大半是异步 DOM 胶水。avHtml 是其中的纯逻辑：有头像图就
 * 用背景图、没有就取名字首字母。名字和图片 URL 都来自对端用户 —— 拼进 style / 首字母
 * 都得转义（URL 里塞引号能闭合 style 属性）。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('无头像：取名字首字母、大写', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.match(h.run('avHtml')(null, 'alice', 'av'), />A</, '首字母没大写');
  assert.match(h.run('avHtml')('', '  bob', 'av'), />B</, '前导空格没去掉');
});

test('空名字兜底成「?」，不显示空白圈', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.match(h.run('avHtml')(null, '', 'av'), />\?</);
  assert.match(h.run('avHtml')(null, null, 'av'), />\?</);
});

test('有头像 URL：URL 里的双引号转义，闭合不了 style 属性', (t) => {
  const h = boot(); t.after(() => h.close());
  // style 是双引号属性，要破它得用 " —— 用 ' 破不了（上一版就栽在这，测了个假的）
  const html = h.run('avHtml')('x"><img src=y onerror=alert(1)>', '张三', 'av');
  const box = h.window.document.createElement('div'); box.innerHTML = html;
  assert.strictEqual(box.querySelector('img'), null, 'URL 里的双引号闭合了 style，注入出了 img');
});
