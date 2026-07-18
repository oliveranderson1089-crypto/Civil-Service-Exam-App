/* 组队互监：名字缩略 initials/shortName + 共享待办渲染 renderSharedItem。
 *
 * team 改动 2 次、零测试。互监清单里搭档的名字要缩略显示：initials 取前 4 字当列头
 * （列宽只够放一个勾选框），shortName 去掉邮箱域名、超 6 字截断。名字来自对端用户，
 * 渲染共享待办时 text/名字都要转义（这条跨用户路径是真攻击面）。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('shortName：去掉邮箱域名，超 6 字截断加省略号', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('shortName');
  assert.strictEqual(f('alice@qq.com'), 'alice', '邮箱域名没去掉');
  assert.strictEqual(f('短名'), '短名');
  assert.strictEqual(f('一二三四五六七'), '一二三四五…', '超 6 字没截断');
  assert.strictEqual(f(''), '');
  assert.strictEqual(f(null), '', 'null 没兜底');
});

test('initials：取前 4 字当列头，去邮箱域名', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('initials');
  assert.strictEqual(f('bob@gmail.com'), 'bob');
  assert.strictEqual(f('一二三四五六'), '一二三四', '超过 4 字没截');
  assert.strictEqual(f(null), '');
});

test('renderSharedItem：待办文字里的 HTML 当文字（跨用户内容，真攻击面）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`tkMembers = []; tkMeId = 1;`);
  const html = h.run('renderSharedItem')({
    id: 1, text: '<img src=x onerror=alert(1)>做真题', created_by: 'attacker', done_ids: [], done_by_map: {},
  });
  const box = h.window.document.createElement('div'); box.innerHTML = html;
  assert.strictEqual(box.querySelector('img'), null, '搭档写的待办里的 img 活了 —— 存储型 XSS');
});
