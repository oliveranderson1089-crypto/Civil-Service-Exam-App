/* 每日时政：nwMarkup 高亮 + fmtDay。
 *
 * nwMarkup 把「提法/数据/…」的标记套到新闻正文上高亮。正文来自爬虫（12371.cn /
 * 人民网），是**外部内容经 innerHTML 渲染** —— 和 mdToHtml 同一类攻击面，转义必须严。
 * 逻辑也不只是套标签：长句优先标（免得短句先命中把长句切碎）、已标区间不重叠。
 * news 改动 2 次、零测试。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

function domOf(h, html) {
  const box = h.window.document.createElement('div');
  box.innerHTML = html;
  return box;
}

test('没有标记时：正文整段转义，HTML 进不了 DOM', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = domOf(h, h.run('nwMarkup')('<img src=x onerror=alert(1)>正文', []));
  assert.strictEqual(box.querySelector('img'), null, '外部正文里的 img 活了');
  assert.match(box.textContent, /<img src=x/);
});

test('有标记时：命中处高亮，正文其余部分仍转义', (t) => {
  const h = boot(); t.after(() => h.close());
  const out = h.run('nwMarkup')('坚持依法治国<script>x</script>', [{ quote: '依法治国', kind: '提法', why: '常考' }]);
  const box = domOf(h, out);
  assert.ok(box.querySelector('mark.nw-mk'), '标记没渲染成 mark');
  assert.match(box.querySelector('mark').textContent, /依法治国/);
  assert.strictEqual(box.querySelector('script'), null, '正文里的 script 活了');
});

test('标记的 quote / kind / why 也转义（都可能来自外部）', (t) => {
  const h = boot(); t.after(() => h.close());
  const out = h.run('nwMarkup')('这里有恶意串xyz在文中', [{ quote: '恶意串xyz', kind: '<b>k</b>', why: 'a"onmouseover="alert(1)' }]);
  const box = domOf(h, out);
  const bad = [...box.querySelectorAll('*')].filter(e => [...e.attributes].some(a => /^on/i.test(a.name)));
  assert.deepStrictEqual(bad.map(e => e.tagName), [], 'why 里的引号闭合了 title 属性，注入出事件处理器');
  assert.strictEqual(box.querySelector('b'), null, 'kind 里的 <b> 活了');
});

test('长句优先标：短句不把长句切碎', (t) => {
  const h = boot(); t.after(() => h.close());
  // 「法治」是「法治政府」的子串。若短句先标，长句就再也整段命中不了
  const out = h.run('nwMarkup')('建设法治政府', [{ quote: '法治', kind: '提法' }, { quote: '法治政府', kind: '提法' }]);
  const box = domOf(h, out);
  const marks = [...box.querySelectorAll('mark')].map(m => m.textContent.replace(/提法$/, ''));
  assert.ok(marks.includes('法治政府'), `长句「法治政府」没被整段标出，实际标了 ${JSON.stringify(marks)}`);
});

test('同一处不重复标：区间重叠只留一个', (t) => {
  const h = boot(); t.after(() => h.close());
  const out = h.run('nwMarkup')('依法治国', [{ quote: '依法治国', kind: '提法' }, { quote: '依法', kind: '数据' }]);
  const box = domOf(h, out);
  assert.strictEqual(box.querySelectorAll('mark').length, 1, '重叠的标记没去重，套了两层 mark');
});

test('fmtDay：ISO 日期 → 「N月N日」，去掉前导零；非法输入原样返回', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('fmtDay');
  assert.strictEqual(f('2026-07-08'), '7月8日', '月/日的前导零该去掉');
  assert.strictEqual(f('2026-11-20'), '11月20日');
  assert.strictEqual(f(''), '');
  assert.strictEqual(f('今天'), '今天', '认不出的格式原样返回，不该变 undefined');
});
