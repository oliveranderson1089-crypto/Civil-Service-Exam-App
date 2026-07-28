/* 全国考情：列表渲染 + 筛选 + 关注地区。
 *
 * 这一页的内容**全部来自外站**（标题、来源名、链接都是爬回来的），经 innerHTML 渲染，
 * 和每日时政是同一类攻击面 —— 转义必须严，链接必须挡住 javascript: 这类协议。
 *
 * 另外两条是产品语义，不是样式：
 *   · 「只看四川」不等于「不看国考」，全国性公告要一直带着；
 *   · 时效标只说「几天前发的」，不替用户判断「还能不能报名」——报名截止藏在原文里，
 *     我们没抓，替他下结论会让人错过报名。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const BASE = {
  kinds: ['国考', '省考', '事考'], regions: ['全国', '四川', '广东'],
  counts: { 省考: 2 }, by_region: { 四川: 2 }, follow: ['四川'],
  updated_at: '2026-07-28 07:20:11', total: 2,
};

function bootExam(items, extra) {
  const h = boot({
    fetch: (url) => url.startsWith('/api/exam/notices')
      ? { json: Object.assign({}, BASE, { items }, extra || {}) } : { json: {} },
  });
  return h;
}

const ONE = {
  kind: '省考', region: '四川', title: '四川省2026年度考试录用公务员公告',
  url: 'https://sc.huatu.com/2026/0728/1.html', source: '华图·四川',
  pub_date: '2026-07-28', headcount: '85', brief: '省级机关招录',
};

test('公告标题来自外站：HTML 当文字，进不了 DOM', async (t) => {
  const h = bootExam([Object.assign({}, ONE, {
    title: '<img src=x onerror=alert(1)>某某公告',
    source: '<b>来源</b>', brief: '<i>x</i>',
  })]);
  t.after(() => h.close());
  await h.run('loadExam()');
  const box = h.window.document.getElementById('ex-list');
  assert.strictEqual(box.querySelector('img'), null, '标题里的 img 活了');
  assert.strictEqual(box.querySelector('b'), null, '来源里的 b 活了');
  assert.match(box.textContent, /<img src=x/);
});

test('公告链接是外站地址：javascript: 这类协议不能变成可点的链接', async (t) => {
  const h = bootExam([Object.assign({}, ONE, { url: 'javascript:alert(1)' })]);
  t.after(() => h.close());
  await h.run('loadExam()');
  const a = h.window.document.querySelector('#ex-list .ex-title');
  assert.ok(a, '没渲染出标题链接');
  assert.ok(!/^javascript:/i.test(a.getAttribute('href') || ''),
    'javascript: 链接直接进了 href：' + a.getAttribute('href'));
});

test('时效标只说「几天前发的」，不说「还能不能报名」', (t) => {
  const h = boot(); t.after(() => h.close());
  /* 必须按**本地**日期造，不能用 toISOString（那是 UTC）：东八区凌晨 0~8 点跑测试时，
     UTC 还停在昨天，「今天」会被算成「昨天」，测试半夜自己变红。 */
  const day = (n) => {
    const d = new Date(Date.now() - n * 86400000);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  };
  assert.strictEqual(h.run(`exAge('${day(0)}')`).txt, '今天');
  assert.strictEqual(h.run(`exAge('${day(3)}')`).txt, '3 天前');
  assert.strictEqual(h.run("exAge('').txt"), '日期不明');
  for (const n of [0, 3, 40]) {
    assert.ok(!/报名|截止|可报|已结束/.test(h.run(`exAge('${day(n)}')`).txt),
      '时效标替用户下了报名结论');
  }
});

test('默认按「我关注的」筛，请求带 region=follow', async (t) => {
  const h = bootExam([ONE]); t.after(() => h.close());
  await h.run('loadExam()');
  const req = h.calls.filter(c => c.url.startsWith('/api/exam/notices')).pop();
  assert.match(req.url, /region=follow/);
});

test('关注地区面板：只保存被选中的省，且允许清空', async (t) => {
  const h = bootExam([ONE]); t.after(() => h.close());
  await h.run('loadExam()');
  h.window.document.getElementById('ex-follow').onclick();
  const box = h.window.document.getElementById('ex-pickbox');
  // 默认选中的是「四川」（follow 里给的）；取消它 = 清空关注
  box.querySelector('[data-exp="四川"]').classList.remove('active');
  await h.window.document.getElementById('ex-picksave').onclick();
  const put = h.calls.filter(c => c.method === 'PUT').pop();
  assert.ok(put, '没发出保存请求');
  assert.deepStrictEqual(JSON.parse(put.body).regions, [],
    '清空关注没被如实发上去，那「我不想只看四川」这个操作就永远无效');
});

test('库是空的时候，说清楚该干什么，而不是只给一句「暂无数据」', async (t) => {
  const h = bootExam([], { total: 0, updated_at: '' });
  t.after(() => h.close());
  await h.run('loadExam()');
  const txt = h.window.document.getElementById('ex-list').textContent;
  assert.match(txt, /立即抓取/, '空态没告诉用户下一步点哪里：' + txt);
});
