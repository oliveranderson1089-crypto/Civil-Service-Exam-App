/* AI 会话 ⋮ →「移动到项目 ›」这条路。
 *
 * 曾经的表现是「点了毫无反应」：move 分支用 innerHTML 重画了 #acm-list，被点的按钮
 * 因此脱离文档；事件冒到 document 上的关菜单钩子时，那边用 e.target.closest() 判断
 * 「点在不在菜单里」，而脱离文档的节点 closest 永远返回 null —— 于是刚画好的项目列表
 * 当场被当成「点在菜单外」收掉。二级菜单闪一下就没了，看起来就是没反应。
 *
 * 所以这里测的不是「PUT 发没发出去」，而是**点完之后菜单还在不在**。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const HOME = {
  chats: [{ id: 7, title: '对话甲', updated_at: '2026-08-18 10:00', project_id: null, starred: 0, pname: null }],
  projects: [{ id: 3, name: '申论批改', instructions: '按采分点批改', cnt: 0 }],
};

function bootAi(t) {
  const h = boot({
    fetch: (url) => (String(url).indexOf('/api/aichat/home') === 0 ? { json: HOME } : { json: { ok: true } }),
  });
  t.after(() => h.close());
  return h;
}
const click = (h, el) => el.dispatchEvent(new h.window.MouseEvent('click', { bubbles: true }));

test('点「移动到项目 ›」之后，二级菜单要还在屏幕上', async (t) => {
  const h = bootAi(t);
  await h.run('loadAiHome()');
  const doc = h.window.document;

  click(h, doc.querySelector('[data-aimenu]'));
  const menu = doc.querySelector('#ai-chatmenu');
  assert.ok(!menu.classList.contains('hidden'), '⋮ 菜单没弹出来');

  const mv = doc.querySelector('[data-acm="move"]');
  assert.ok(mv, '有项目时应该出现「移动到项目」');
  click(h, mv);

  assert.ok(!menu.classList.contains('hidden'),
    '二级菜单被自己收掉了 —— 用户看到的就是「点击没有反应」');
  assert.ok(doc.querySelector('[data-acmproj="3"]'), '项目列表没画出来');
});

test('在二级菜单里选中项目，真的发出移动请求', async (t) => {
  const h = bootAi(t);
  await h.run('loadAiHome()');
  const doc = h.window.document;

  click(h, doc.querySelector('[data-aimenu]'));
  click(h, doc.querySelector('[data-acm="move"]'));
  click(h, doc.querySelector('[data-acmproj="3"]'));
  await new Promise(r => setTimeout(r, 30));

  const put = h.calls.filter(c => c.method === 'PUT');
  assert.strictEqual(put.length, 1, '应当只发一次移动请求');
  assert.strictEqual(put[0].url, '/api/aichat/chats/7');
  assert.deepStrictEqual(JSON.parse(put[0].body), { project_id: 3 });
  assert.ok(h.toasts.some(x => x.msg === '已移动'), '移动完要给个回执');
  assert.ok(doc.querySelector('#ai-chatmenu').classList.contains('hidden'), '选完项目菜单该收起来');
});

test('点菜单外面，菜单照旧要关掉（别把关菜单一起修没了）', async (t) => {
  const h = bootAi(t);
  await h.run('loadAiHome()');
  const doc = h.window.document;

  click(h, doc.querySelector('[data-aimenu]'));
  assert.ok(!doc.querySelector('#ai-chatmenu').classList.contains('hidden'));
  click(h, doc.body);
  assert.ok(doc.querySelector('#ai-chatmenu').classList.contains('hidden'),
    '点空白处应该关掉菜单');
});
