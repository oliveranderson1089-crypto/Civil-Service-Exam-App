/* 联网 / 精准识图这两个开关：按下之后**要一直开着**，并且看得出来它开着。
 *
 * 第一版做的是「一问一关」（发完自动复位），理由是联网一轮更慢更贵、忘了关难受。
 * 实际用下来反了：真实场景是**连着追问同一件事**（先问纪录片、再问同天上映的电影），
 * 每轮都得重新点才是最烦人的地方。用户定了「开着就一直开，直到手动关」。
 *
 * 代价随之变成「忘了关」，所以状态必须摆在看得见的地方 —— 尤其手机端：那边整行
 * 工具栏是收起的（style.css: `body.mobile-ui .ai-input .input-tools{display:none}`），
 * ➕ 面板一关就没有第二处能看出它还开着，于是 placeholder 也得跟着变。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('点一下开、再点一下关', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.strictEqual(h.run('aiWeb'), false);
  h.run('aiWebToggle()');
  assert.strictEqual(h.run('aiWeb'), true);
  h.run('aiWebToggle()');
  assert.strictEqual(h.run('aiWeb'), false);
});

test('发送之后开关不复位（这是本次改动的要点）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('aiWebToggle(); aiExactToggle();');
  // 只跑到「取快照」那一步就够：再往下会真去 fetch。这里要验的正是快照取完之后
  // 全局值没有被复位。
  h.run('window.__snap = { web: aiWeb, exact: aiExact };');
  // 逐个比，别用 deepStrictEqual：数组是在 jsdom 那个 realm 里造的，
  // 原型跟 node 的不是同一引用（同 aichat.test.js 开头那条注释）。
  assert.strictEqual(h.run('__snap.web'), true);
  assert.strictEqual(h.run('__snap.exact'), true);
  assert.strictEqual(h.run('aiWeb'), true, '发完就自己关掉，等于每轮都要重点一次');
  assert.strictEqual(h.run('aiExact'), true);
});

test('开着的时候 placeholder 要说出来', (t) => {
  const h = boot(); t.after(() => h.close());
  const ph0 = h.run('$("#ai-text").placeholder');
  h.run('aiWebToggle()');
  const ph1 = h.run('$("#ai-text").placeholder');
  assert.ok(ph1.includes('联网'), '手机端 ➕ 面板一关，这就是唯一看得见的状态了');
  assert.notStrictEqual(ph1, ph0);
  h.run('aiWebToggle()');
  assert.strictEqual(h.run('$("#ai-text").placeholder'), ph0, '关掉要还原成原来那句');
});

test('两个都开就都写进去', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('aiWebToggle(); aiExactToggle();');
  const ph = h.run('$("#ai-text").placeholder');
  assert.ok(ph.includes('联网') && ph.includes('精准'), ph);
});

test('placeholder 原文取自 DOM，不在 js 里抄一份', (t) => {
  const h = boot(); t.after(() => h.close());
  const ph0 = h.run('$("#ai-text").placeholder');
  assert.strictEqual(h.run('AI_PH'), ph0,
    '抄一份的下场是改了 index.html 之后，开关一开一关就把文案换成了旧的');
});

test('桌面端图标跟着高亮', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.strictEqual(h.run('$("#ai-web").classList.contains("on")'), false);
  h.run('aiWebToggle()');
  assert.strictEqual(h.run('$("#ai-web").classList.contains("on")'), true);
});

test('手机端 ➕ 面板里那两格也在，并且开着时高亮', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('aiExactOk = true;');          // 假装后台说这一档配好了
  h.run('aiSheetOpen()');
  const html0 = h.run('$("#ai-sheet-grid").innerHTML');
  assert.ok(html0.includes('联网'), '手机端整行工具栏是收起的，这里是唯一入口');
  assert.ok(html0.includes('精准识图'));
  h.run('aiWebToggle(); aiSheetOpen();');
  const grid = h.run(`(() => {
    const b = [...$("#ai-sheet-grid").querySelectorAll("[data-sh]")]
      .find(x => x.textContent.includes("联网"));
    return b ? b.className : "";
  })()`);
  assert.ok(grid.includes('on'), '面板里看不出开没开，等于手机上没有这个状态');
});

test('没配精准档就不摆那一格', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('aiExactOk = false;');
  h.run('aiSheetOpen()');
  assert.ok(!h.run('$("#ai-sheet-grid").innerHTML').includes('精准识图'),
    '摆一个点了设不了的格子，比没有它更糟');
});

test('隐藏一格不能让后面的格子点错', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('aiExactOk = false;');
  h.run('aiSheetOpen()');
  const ok = h.run(`(() => [...$("#ai-sheet-grid").querySelectorAll("[data-sh]")]
    .every(b => {
      const it = AI_SHEET_ITEMS[+b.dataset.sh];
      return it && b.textContent.includes(it.name);
    }))()`);
  assert.ok(ok, '先 filter 再 map 会让下标错位 —— 点「联网」结果跑去了「导出」');
});
