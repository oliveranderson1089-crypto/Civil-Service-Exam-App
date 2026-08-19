/* AI 产出这一页：看、投放、归档。
 *
 * 它是**中转站不是第二个云盘** —— 界面上得把「还剩多久自动清掉」明说出来，
 * 否则总有人把它当仓库用，然后有一天发现东西没了。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const ITEMS = [
  { id: 7, kind: 'md', title: '资料分析速算', size: 320, kept: false, sent: '', created_at: '2026-08-18 10:00' },
  { id: 8, kind: 'pdf', title: '申论模板', size: 900, kept: true, sent: '资料库', created_at: '2026-08-17 09:00' },
];

function bootAo(t, over) {
  const h = boot({
    fetch: (url) => {
      const u = String(url).split('?')[0];
      if (u === '/api/aiout') return { json: over || { items: ITEMS, retain_days: 30 } };
      if (/^\/api\/aiout\/\d+$/.test(u)) return { json: { id: 7, title: '资料分析速算', body: '# 速算\n\n**截位直除**' } };
      return { json: { ok: true, where: '资料库' } };
    },
  });
  t.after(() => h.close());
  return h;
}
const $ = (h, s) => h.window.document.querySelector(s);
const $$ = (h, s) => [...h.window.document.querySelectorAll(s)];
const click = (h, el) => el.dispatchEvent(new h.window.MouseEvent('click', { bubbles: true }));

test('列表把保留期限说出来，并标出已归档的', async (t) => {
  const h = bootAo(t);
  await h.run('loadAiOut()');
  assert.match($(h, '#ao-intro').textContent, /30 天后自动清掉/,
    '不说清会被自动清掉，用户会把它当仓库用');
  assert.deepStrictEqual($$(h, '.ao-t').map(x => x.textContent), ['资料分析速算', '申论模板']);
  assert.strictEqual($$(h, '.ao-keep').length, 1);
  assert.match($$(h, '.ao-m')[1].textContent, /已投到 资料库/, '投过哪儿要看得见，不然会重复投');
});

test('空的时候告诉你东西从哪来', async (t) => {
  const h = bootAo(t, { items: [], retain_days: 30 });
  await h.run('loadAiOut()');
  assert.match($(h, '#ao-list').textContent, /还没有产出/);
  assert.match($(h, '#ao-list').textContent, /汇总/, '空状态要说清东西是怎么进来的');
});

test('看全文走 Markdown 渲染，能退回列表', async (t) => {
  const h = bootAo(t);
  await h.run('loadAiOut()');
  click(h, $$(h, '[data-aoact="view"]')[0]);
  await new Promise(r => setTimeout(r, 30));
  assert.match($(h, '.ao-rb').innerHTML, /<strong>截位直除<\/strong>/, '正文该按 Markdown 渲染');
  click(h, $(h, '#ao-back'));
  assert.ok($$(h, '.ao-card').length === 2, '退不回列表');
});

test('归档发出的是 kept 翻转', async (t) => {
  const h = bootAo(t);
  await h.run('loadAiOut()');
  click(h, $$(h, '[data-aoact="keep"]')[0]);
  await new Promise(r => setTimeout(r, 30));
  const put = h.calls.find(c => c.method === 'PUT');
  assert.strictEqual(put.url, '/api/aiout/7');
  assert.deepStrictEqual(JSON.parse(put.body), { kept: true });
});

test('标题走转义（是 AI 写的，也可能被用户改成任何东西）', async (t) => {
  const h = bootAo(t, { items: [{ id: 1, kind: 'md', title: '<img src=x onerror=alert(1)>',
    size: 3, kept: false, sent: '', created_at: '2026-08-18 10:00' }], retain_days: 30 });
  await h.run('loadAiOut()');
  assert.ok(!$(h, '#ao-list').querySelector('img'), '标题没转义，塞得进标签');
  assert.match($(h, '.ao-t').textContent, /onerror/);
});
