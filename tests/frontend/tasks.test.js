/* 每日任务：进度统计 tdRecalcProg。
 *
 * tasks 改动 2 次、零测试。打勾用乐观更新（先翻勾再发请求），翻完 tdRecalcProg 从当前
 * 列表 DOM 里数「已完成 / 总数」刷新进度条 —— 全勾完还要给个 🎉。数错了进度就跟实际
 * 对不上。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

function seed(h, states) {
  // states 如 ['done','','done'] —— 往每日任务列表塞几条，标记完成态
  const html = states.map((s, i) => `<div class="tk-item ${s}" data-td="${i}"></div>`).join('');
  h.run(`$('#tk-daily-list').innerHTML = ${JSON.stringify(html)};`);
}

test('数出「已完成 / 总数」', (t) => {
  const h = boot(); t.after(() => h.close());
  seed(h, ['done', '', 'done', '']);
  h.run('tdRecalcProg()');
  assert.match(h.window.document.querySelector('#tk-daily-prog').textContent, /今日进度 2 \/ 4/);
});

test('全部完成时给 🎉', (t) => {
  const h = boot(); t.after(() => h.close());
  seed(h, ['done', 'done']);
  h.run('tdRecalcProg()');
  assert.match(h.window.document.querySelector('#tk-daily-prog').textContent, /2 \/ 2.*🎉/);
});

test('没到全完不给 🎉（差一个也不行）', (t) => {
  const h = boot(); t.after(() => h.close());
  seed(h, ['done', 'done', '']);
  const txt = h.window.document.querySelector('#tk-daily-prog');
  h.run('tdRecalcProg()');
  assert.doesNotMatch(txt.textContent, /🎉/, '还差一个就提前庆祝了');
});

test('一条任务都没有时进度条清空（不显示 0/0）', (t) => {
  const h = boot(); t.after(() => h.close());
  seed(h, []);
  h.run('tdRecalcProg()');
  assert.strictEqual(h.window.document.querySelector('#tk-daily-prog').textContent, '');
});
