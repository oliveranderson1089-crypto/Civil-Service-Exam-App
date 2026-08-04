/* 自选成文的「我写过的」列表。
 *
 * 这一页原来只有一张空表单：写完当场看一眼、一返回就再也找不着那篇（其实一直在库里）。
 * 列表是唯一的找回入口，断了不报错、只是空一块，所以盯两件事：
 *   ① 标题/场景来自 AI，拼进 innerHTML 前必须转义；
 *   ② 删除按钮在卡片内部，点它只能删、不能顺带把这篇打开（closest 判定顺序问题）。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const ITEM = {
  id: 7, date: '2026-08-04 22:55:53', words: 352,
  title: '花湖区工会工作经验交流材料',
  doctype: '经验交流材料', scene: '工会工作', form: 'full',
};

function bootWith(items) {
  return boot({
    fetch: (url) => url.includes('/api/write/yingyong/mine') ? { json: { items } } : {},
  });
}

test('写过的都列出来：文种、场景、字数、写的时间都在', async (t) => {
  const h = bootWith([ITEM]);
  t.after(() => h.close());
  await h.run('loadYyMine')();
  const card = h.window.document.querySelector('#yy-mine [data-weid="7"]');
  assert.ok(card, '写过的那篇没出现在列表里 —— 返回后就找不回来了');
  const txt = card.textContent;
  for (const s of ['花湖区工会工作经验交流材料', '经验交流材料', '工会工作', '352 字']) {
    assert.ok(txt.includes(s), `卡片上少了「${s}」：${txt}`);
  }
  // 同一天能写好几篇，只显示日期分不出是哪篇，时分必须在
  assert.ok(txt.includes('22:55'), '没显示写的时间：' + txt);
  assert.ok(txt.includes('范文'), '没标出是范文还是提纲：' + txt);
});

test('一篇都没有时给的是「会留在这儿」，不是空白', async (t) => {
  const h = bootWith([]);
  t.after(() => h.close());
  await h.run('loadYyMine')();
  assert.ok(h.window.document.querySelector('#yy-mine .empty'), '空列表什么都没说');
});

test('标题 / 场景里的 HTML 当文字，不进 DOM', async (t) => {
  const h = bootWith([Object.assign({}, ITEM, {
    title: '<img src=x onerror=alert(1)>', scene: '<script>alert(1)</script>',
  })]);
  t.after(() => h.close());
  await h.run('loadYyMine')();
  const box = h.window.document.querySelector('#yy-mine');
  assert.strictEqual(box.querySelector('img'), null, '标题里的 img 活了');
  assert.strictEqual(box.querySelector('script'), null, '场景里的 script 活了');
});

test('点删除按钮只弹确认，不会顺手把这篇打开', async (t) => {
  const h = bootWith([ITEM]);
  t.after(() => h.close());
  await h.run('loadYyMine')();
  const w = h.window;
  const before = h.calls.length;
  w.document.querySelector('#yy-mine [data-yydel="7"]')
    .dispatchEvent(new w.Event('click', { bubbles: true }));
  await new Promise(r => setTimeout(r, 0));
  assert.ok(w.document.querySelector('#view-writed').classList.contains('hidden'),
    '点「删掉」把这篇打开了 —— 删除按钮要抢在 data-weid 前面判');
  assert.ok(!h.calls.slice(before).some(c => /\/api\/write\/7/.test(c.url)),
    '还没确认就已经打接口了');
});
