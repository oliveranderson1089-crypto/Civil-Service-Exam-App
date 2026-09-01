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

/* ---- 两段：待处理 / 已归档 ----
   这一页是中转站：每天真正要动的是「还没决定去处」的那批，归档过的只是留着备查。
   下面几条盯的就是这个分界别糊掉。 */

// 相对今天造时间戳：写死日期的话，测试过几天自己就红了
function ago(days) {
  const d = new Date(Date.now() - days * 86400000);
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
const mk = (id, over) => ({ id, kind: 'md', title: '产出' + id, size: 100, kept: false,
                            sent: '', created_at: ago(1), ...over });

test('分成待处理 / 已归档两段，各自报条数', async (t) => {
  const h = bootAo(t, { items: [mk(1), mk(2), mk(3, { kept: true })], retain_days: 30 });
  await h.run('loadAiOut()');
  const secs = $$(h, '.ao-sec');
  assert.strictEqual(secs.length, 2);
  assert.match(secs[0].textContent, /待处理2/, '待处理那段要写着 2 份');
  assert.match(secs[1].textContent, /已归档1/);
  const grps = $$(h, '.ao-grp');
  assert.deepStrictEqual([...grps[0].querySelectorAll('.ao-t')].map(x => x.textContent), ['产出1', '产出2']);
  assert.deepStrictEqual([...grps[1].querySelectorAll('.ao-t')].map(x => x.textContent), ['产出3'],
    '归档过的不该还混在待处理里');
});

test('动作按钮认的还是原来那一份（分组不能把下标打乱）', async (t) => {
  const h = bootAo(t, { items: [mk(1), mk(2, { kept: true }), mk(3)], retain_days: 30 });
  await h.run('loadAiOut()');
  // 第 3 份排在待处理段的第二张卡上；点它的删除，删的必须是 id=3
  const card = $$(h, '.ao-grp')[0].querySelectorAll('.ao-card')[1];
  assert.strictEqual(card.dataset.ao, '3');
  await h.run('appConfirm = () => Promise.resolve(true)');
  click(h, card.querySelector('[data-aoact="del"]'));
  await new Promise(r => setTimeout(r, 30));
  const del = h.calls.find(c => c.method === 'DELETE');
  assert.strictEqual(del.url, '/api/aiout/3', '分完组下标错位，删的就是别人');
});

test('已归档默认收起，点一下展开，下次进来还是展开的', async (t) => {
  const h = bootAo(t, { items: [mk(1), mk(2, { kept: true })], retain_days: 30 });
  await h.run('loadAiOut()');
  assert.ok($(h, '#ao-kept').hasAttribute('hidden'), '有待处理的时候，已归档该收着');
  click(h, $(h, '[data-aosec="kept"]'));
  assert.ok(!$(h, '#ao-kept').hasAttribute('hidden'));
  assert.strictEqual($(h, '[data-aosec="kept"]').getAttribute('aria-expanded'), 'true');
  await h.run('loadAiOut()');
  assert.ok(!$(h, '#ao-kept').hasAttribute('hidden'), '拨过的开合状态没记住');
});

test('待处理那段也能折叠（顶着一个点不动的 ▾ 就是在骗人）', async (t) => {
  const h = bootAo(t, { items: [mk(1), mk(2), mk(3, { kept: true })], retain_days: 30 });
  await h.run('loadAiOut()');
  const head = $(h, '[data-aosec="fresh"]');
  assert.strictEqual(head.tagName, 'BUTTON', '标题行得是个按钮，不然点不着也没有键盘焦点');
  assert.ok(!$(h, '#ao-fresh').hasAttribute('hidden'), '默认摊开：每天要动的就是它');
  click(h, head);
  assert.ok($(h, '#ao-fresh').hasAttribute('hidden'));
  assert.strictEqual($(h, '[data-aosec="fresh"]').getAttribute('aria-expanded'), 'false');
  await h.run('loadAiOut()');
  assert.ok($(h, '#ao-fresh').hasAttribute('hidden'), '收起状态没记住');
});

test('两段各记各的开合，互不牵连', async (t) => {
  const h = bootAo(t, { items: [mk(1), mk(2, { kept: true })], retain_days: 30 });
  await h.run('loadAiOut()');
  click(h, $(h, '[data-aosec="kept"]'));                    // 先把已归档拨开
  click(h, $(h, '[data-aosec="fresh"]'));                   // 再把待处理收起
  assert.ok($(h, '#ao-fresh').hasAttribute('hidden'));
  assert.ok(!$(h, '#ao-kept').hasAttribute('hidden'), '拨一段不该顺手改动另一段');
  await h.run('loadAiOut()');
  assert.ok($(h, '#ao-fresh').hasAttribute('hidden'), '重进之后两段该各自还原');
  assert.ok(!$(h, '#ao-kept').hasAttribute('hidden'));
});

test('待处理清空了，已归档那段自己摊开', async (t) => {
  const h = bootAo(t, { items: [mk(1, { kept: true })], retain_days: 30 });
  await h.run('loadAiOut()');
  assert.ok(!$(h, '#ao-kept').hasAttribute('hidden'), '否则整页只剩两行标题');
});

test('每条写着还剩几天，进 7 天以内转琥珀', async (t) => {
  const h = bootAo(t, { items: [mk(1, { created_at: ago(0) }), mk(2, { created_at: ago(23) }),
                                mk(3, { created_at: ago(40) })], retain_days: 30 });
  await h.run('loadAiOut()');
  const lefts = $$(h, '.ao-left');
  assert.deepStrictEqual(lefts.map(x => x.textContent), ['剩 30 天', '剩 7 天', '剩 0 天']);
  assert.ok(!lefts[0].classList.contains('soon'));
  assert.ok(lefts[1].classList.contains('soon'), '第 23 天正好踩线，该报警了');
  assert.ok(lefts[2].classList.contains('soon'));
});

test('归档过的不写剩余天数（它本来就不会被清）', async (t) => {
  const h = bootAo(t, { items: [mk(1, { kept: true })], retain_days: 30 });
  await h.run('loadAiOut()');
  assert.strictEqual($$(h, '.ao-left').length, 0);
});

test('顶上一句摘要：几份待处理、最早一份哪天没', async (t) => {
  const h = bootAo(t, { items: [mk(1, { created_at: ago(2) }), mk(2, { created_at: ago(26) }),
                                mk(3, { kept: true })], retain_days: 30 });
  await h.run('loadAiOut()');
  const sum = $(h, '.ao-sum').textContent;
  assert.match(sum, /2 份待处理/);
  assert.match(sum, /最早一份 4 天后清掉/, '要报最紧的那一份，不是最新的');
  assert.match(sum, /已归档 1 份/);
});

test('两类各说各的空话', async (t) => {
  const h1 = bootAo(t, { items: [mk(1, { kept: true })], retain_days: 30 });
  await h1.run('loadAiOut()');
  assert.match($$(h1, '.ao-grp')[0].textContent, /都处理完了/, '有归档、没待处理 ≠ 一份产出都没有');
  const h2 = bootAo(t, { items: [mk(1)], retain_days: 30 });
  await h2.run('loadAiOut()');
  click(h2, $(h2, '[data-aosec="kept"]'));
  assert.match($(h2, '#ao-kept').textContent, /还没归档过东西/);
  assert.match($(h2, '#ao-kept').textContent, /30 天/, '空态要顺带说清归档是干嘛的');
});

test('时间读不出来就不编一个天数出来', async (t) => {
  const h = bootAo(t, { items: [mk(1, { created_at: '' })], retain_days: 30 });
  await h.run('loadAiOut()');
  assert.strictEqual($$(h, '.ao-left').length, 0);
  assert.strictEqual($$(h, '.ao-card').length, 1, '算不出天数不该连卡片一起没了');
});

/* ---- 分享 ----
   两条路后果不一样：「发到聊天」是发一条消息过去，「共享给队友」是把副本落进资料库。
   选人的面板是跟云盘、资料库共用的，所以这里连着面板一起点，别只测发出去的那个请求。 */
const tick = () => new Promise(r => setTimeout(r, 30));

function bootShare(t, over = {}) {
  const h = boot({
    fetch: (url) => {
      const u = String(url).split('?')[0];
      if (u === '/api/aiout') return { json: { items: [mk(1)], retain_days: 30 } };
      if (u === '/api/chat/targets') {
        return { json: over.targets || { friends: [{ id: 9, username: '小王' }],
                                         groups: [{ id: 5, title: '上岸小队', n: 3 }] } };
      }
      if (u === '/api/aiout/1/team') return { json: over.team || { members: [{ id: 7, username: '阿珍' }] } };
      if (u === '/api/aiout/1/chat') return { json: { ok: true, n: 2, users: 1, groups: 1 } };
      return { json: { ok: true, n: 1 } };
    },
  });
  t.after(() => h.close());
  return h;
}
const shareBtn = h => $$(h, '[data-aoact="share"]')[0];

test('分享 → 发到聊天：好友和小组能一起选，发到 /chat', async (t) => {
  const h = bootShare(t);
  await h.run('loadAiOut()');
  click(h, shareBtn(h));
  await tick();
  assert.ok($(h, '[data-aoshare="chat"]'), '得先问清是发聊天还是共享给队友');
  click(h, $(h, '[data-aoshare="chat"]'));
  await tick();
  const boxes = $$(h, '#mat-share-sheet input[data-tk]');
  assert.strictEqual(boxes.length, 2, '好友和小组都该列出来');
  boxes.forEach(b => { b.checked = true; b.dispatchEvent(new h.window.Event('change')); });
  click(h, $(h, '#tk-ok'));
  await tick();
  const post = h.calls.find(c => c.url === '/api/aiout/1/chat');
  assert.ok(post, '没发出去');
  assert.deepStrictEqual(JSON.parse(post.body), { users: [9], groups: [5] });
});

test('分享 → 共享给队友：勾了人才发，请求带的是队友 id', async (t) => {
  const h = bootShare(t);
  await h.run('loadAiOut()');
  click(h, shareBtn(h));
  await tick();
  click(h, $(h, '[data-aoshare="team"]'));
  await tick();
  const box = $(h, '#mat-share-sheet input[type="checkbox"]');
  assert.ok(box, '队友该列出来');
  box.checked = true;
  click(h, $(h, '#ms-ok'));
  await tick();
  const post = h.calls.find(c => c.url === '/api/aiout/1/team' && c.method === 'POST');
  assert.ok(post, '没共享出去');
  assert.deepStrictEqual(JSON.parse(post.body), { to: [7] });
});

test('共享给队友：借了资料库的面板，但话得换成「投一份副本」', async (t) => {
  const h = bootShare(t);
  await h.run('loadAiOut()');
  click(h, shareBtn(h));
  await tick();
  click(h, $(h, '[data-aoshare="team"]'));
  await tick();
  const hint = $(h, '#mat-share-sheet .acct-hint').textContent;
  assert.match(hint, /副本/, '这边收不回，不能照抄资料库那句「取消勾选就收回」');
  assert.doesNotMatch(hint, /取消勾选就收回/);
});

test('没队友时说清去哪儿组队，而不是弹一个空面板', async (t) => {
  const h = bootShare(t, { team: { members: [] } });
  await h.run('loadAiOut()');
  click(h, shareBtn(h));
  await tick();
  click(h, $(h, '[data-aoshare="team"]'));
  await tick();
  assert.strictEqual($$(h, '#mat-share-sheet input[type="checkbox"]').length, 0);
  assert.ok(!h.calls.find(c => c.url === '/api/aiout/1/team' && c.method === 'POST'));
});
