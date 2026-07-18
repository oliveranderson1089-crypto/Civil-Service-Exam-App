/* 常考词语：列表渲染 + 搜索过滤 renderCkList。
 *
 * changkao 改动 3 次、零测试（CK_TO_ENTRY 常量已由 crossend 钉住）。renderCkList 按搜索框
 * 里的词在标题/正文/笔记里过滤，空结果按 收藏页/普通页 分文案，条目文字要转义。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const D = (h) => h.window.document;
function setup(h, items, board, search) {
  h.run(`ckItems = ${JSON.stringify(items)}; ckBoard = ${JSON.stringify(board || '成语')}; ckStarred = new Set();`);
  h.run(`$('#ckb-search').value = ${JSON.stringify(search || '')};`);
  h.run('renderCkList()');
}

test('按搜索词在 标题/正文/笔记 里过滤', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, [
    { id: 1, title: '高瞻远瞩', content: '站得高', note: '' },
    { id: 2, title: '实事求是', content: '一切从实际出发', note: '' },
  ], '成语', '实际');
  const items = D(h).querySelectorAll('.cki-t, .cki-item, [data-ckstar]');
  assert.match(D(h).querySelector('#ckb-list').textContent, /实事求是/);
  assert.doesNotMatch(D(h).querySelector('#ckb-list').textContent, /高瞻远瞩/, '没过滤掉不匹配的');
});

test('空结果文案：收藏页 vs 普通页 不同', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, [], '收藏', '');
  assert.match(D(h).querySelector('#ckb-list').textContent, /收藏/);
  setup(h, [{ id: 1, title: 'x', content: 'y' }], '成语', '找不到的词xyz');
  assert.match(D(h).querySelector('#ckb-list').textContent, /没有匹配/);
});

test('条目标题里的 HTML 当文字', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, [{ id: 1, title: '<img src=x onerror=alert(1)>', content: 'a' }], '成语', '');
  assert.strictEqual(D(h).querySelector('#ckb-list').querySelector('img'), null, '条目标题里的 img 活了');
});
