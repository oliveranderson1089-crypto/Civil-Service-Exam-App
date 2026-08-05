/* 标签页的板块筛选与状态角标（界面重构 P2）。
 *
 * P2 的全部意义是**压掉一层**：原来进「专项练」要走 首页→行测→言语理解→专项练 四层，
 * 现在是 练→(chip)言语→专项练 两层。所以第一组测试盯的是「板块页真的被内联进来了」——
 * 而且内联的那份清单和分派必须是板块页那一份，不是另抄的：抄一份的话，
 * core.js 那边加个功能，这边不会报错，只会点了没反应。
 *
 * 第二组盯「状态数字不能说反话」：
 *   · 没练过的板块不许显示 0%（会把该练的和没练的调个个儿）；
 *   · 状态接口挂了，目录本身照样能点 —— 导航为几个数字转圈是本末倒置。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const HUB = {
  date: '2026-08-05', window_days: 30,
  boards: {
    '言语理解与表达': { q: 120, correct: 85, rate: 71, wrong: 4 },
    '数量关系': { q: 40, correct: 20, rate: 50, wrong: 6 },
    '资料分析': { q: 60, correct: 51, rate: 85, wrong: 0 },
    '常识判断': { q: 0, correct: 0, rate: null, wrong: 3 },
  },
  acc: { idiom: 8, sucai: 4, news: 6 },
};

function bootHub(hub) {
  return boot({
    fetch: (url) => url.startsWith('/api/hub')
      ? (hub instanceof Error ? hub : { json: hub === undefined ? HUB : hub })
      : { json: {} },
  });
}
const $ = (h, s) => h.window.document.querySelector(s);
const $$ = (h, s) => [...h.window.document.querySelectorAll(s)];
const names = (h) => $$(h, '#tab-groups .tr-n').map(b => b.textContent);
// tbRender 是同步的，但状态数字要等 /api/hub 回来才补画
const settle = () => new Promise(r => setTimeout(r, 0));

async function openTab(h, key) {
  $(h, `#tabbar [data-tb="${key}"]`).click();
  await settle();
  return h;
}
const chip = (h, key) => $(h, `#tab-chips [data-tbc="${key}"]`).click();

test('「练」顶上出板块筛选条，板块名取前两字', async (t) => {
  const h = bootHub(); t.after(() => h.close());
  await openTab(h, 'drill');
  const cs = $$(h, '#tab-chips [data-tbc]').map(c => c.textContent);
  assert.strictEqual(cs[0], '全部');
  assert.ok(cs.includes('言语'), '「言语理解与表达」没缩成「言语」，整个塞进胶囊会挤成两行');
  assert.ok(cs.includes('资料') && cs.includes('数量'));
});

test('选中板块 = 把板块页整页内联进来，这就是省掉的那一层', async (t) => {
  const h = bootHub(); t.after(() => h.close());
  await openTab(h, 'drill');
  chip(h, '言语理解与表达');
  const n = names(h);
  // 板块页上有什么，这里就该有什么：专项练 + 基础知识点 + 该板块的积累
  assert.ok(n.includes('专项练'), '内联后连专项练都没有，那这一层白压了');
  assert.ok(n.includes('AI 梳理 · 我的补充'), '基础知识点入口没跟过来');
  assert.ok(n.includes('成语词语积累'), '板块专属的积累入口没跟过来');
  // 只剩这个板块的东西，别的板块不该混进来
  assert.ok(!n.includes('图形推理'), '切了板块还在显示别的板块的内容');
});

test('内联用的是板块页那份分派，不是另抄一份', async (t) => {
  const h = bootHub(); t.after(() => h.close());
  await openTab(h, 'drill');
  chip(h, '言语理解与表达');
  // 换掉共用的分派函数：内联那份要是自己抄了一套 if-else，这儿就观察不到
  h.run("openBoardFeat = (k, b) => { window.__hit = k + '@' + b; }");
  $$(h, '#tab-groups .tab-row').find(r => r.querySelector('.tr-n').textContent === '专项练').click();
  assert.strictEqual(h.window.__hit, 'drill@言语理解与表达',
    '没走 openBoardFeat —— 两份分派迟早走散，而且走散了不会报错');
});

test('切回「全部」回到总览，chip 的选择各标签各记各的', async (t) => {
  const h = bootHub(); t.after(() => h.close());
  await openTab(h, 'drill');
  chip(h, '数量关系');
  assert.ok(!names(h).includes('历年真题'), '选了板块还在显示总览的真题实战');

  await openTab(h, 'acc');
  assert.ok($(h, '#tab-chips [data-tbc=""]').classList.contains('active'),
    '「积累」跟着「练」一起被选中了板块，两个标签的 chip 该各记各的');

  await openTab(h, 'drill');
  assert.ok($(h, '#tab-chips [data-tbc="数量关系"]').classList.contains('active'),
    '切走再回来，刚才选的板块没了');
  chip(h, '');
  assert.ok(names(h).includes('历年真题'));
});

test('正确率按高低分档显示，低的要显眼', async (t) => {
  const h = bootHub(); t.after(() => h.close());
  await openTab(h, 'drill');
  const stat = (name) => {
    const r = $$(h, '#tab-groups .tab-row').find(x => x.querySelector('.tr-n').textContent === name);
    return r && r.querySelector('.tr-stat');
  };
  assert.strictEqual(stat('数量关系').textContent, '50%');
  assert.ok(stat('数量关系').classList.contains('bad'), '50% 该标成要补的');
  assert.ok(stat('言语理解与表达').classList.contains('warn'), '71% 该是中间档');
  assert.ok(stat('资料分析').classList.contains('good'), '85% 该是稳的');
});

test('没练过的板块不显示 0%，显示的是错题存量', async (t) => {
  const h = bootHub(); t.after(() => h.close());
  await openTab(h, 'drill');
  const r = $$(h, '#tab-groups .tab-row').find(x => x.querySelector('.tr-n').textContent === '常识判断');
  const s = r.querySelector('.tr-stat');
  assert.ok(!/0%/.test(s.textContent), '一道没练却报 0%，把该练的和没练的调了个个儿');
  assert.match(s.textContent, /错题 3/);
});

test('「积累」按大类筛选，条目带今日新增', async (t) => {
  const h = bootHub(); t.after(() => h.close());
  await openTab(h, 'acc');
  const idiom = $$(h, '#tab-groups .tab-row').find(x => x.querySelector('.tr-n').textContent === '成语词语积累');
  assert.match(idiom.querySelector('.tr-stat').textContent, /今日 \+8/);

  chip(h, '时政');
  const n = names(h);
  assert.ok(n.includes('每日时政'), '选了时政却没有每日时政');
  assert.ok(!n.includes('成语词语积累'), '筛选没生效，别的大类还在');
});

test('没有新增的模块不挂角标，不显示「今日 +0」', async (t) => {
  const h = bootHub({ boards: {}, acc: {} }); t.after(() => h.close());
  await openTab(h, 'acc');
  assert.strictEqual($(h, '#tab-groups .tr-stat'), null, '没新增也挂了角标');
  assert.ok(names(h).length > 5, '角标没了连条目也不见了');
});

test('状态接口挂了，目录照样能点', async (t) => {
  const h = bootHub(new Error('后端 502')); t.after(() => h.close());
  await openTab(h, 'drill');
  // 导航为了几个数字转圈是本末倒置：数字没了就没了，路还得能走
  assert.ok(names(h).includes('历年真题'), '状态挂了把整个目录也拖没了');
  assert.strictEqual($(h, '#tab-groups .tr-stat'), null);
  h.run("openRealq = () => { window.__hit = 'realq'; }");
  $$(h, '#tab-groups .tab-row').find(r => r.querySelector('.tr-n').textContent === '历年真题').click();
  assert.strictEqual(h.window.__hit, 'realq');
});

test('状态数字只拉一次，来回切标签不反复打接口', async (t) => {
  const h = bootHub(); t.after(() => h.close());
  await openTab(h, 'drill');
  await openTab(h, 'acc');
  await openTab(h, 'drill');
  const n = h.calls.filter(c => c.url.startsWith('/api/hub')).length;
  assert.strictEqual(n, 1, `切一次标签打一次 /api/hub（共 ${n} 次）`);
});

test('只用首页的人不该为这两个标签页多发一个请求', (t) => {
  const h = bootHub(); t.after(() => h.close());
  assert.strictEqual(h.calls.filter(c => c.url.startsWith('/api/hub')).length, 0,
    '启动就拉了 /api/hub —— 没打开过标签页的人白付一个请求');
});
