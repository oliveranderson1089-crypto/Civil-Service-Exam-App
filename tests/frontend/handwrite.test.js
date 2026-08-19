/* 手写输入板：晚到的识别结果不许再碰输入框；夜间全屏模式必须真透明。
 *
 * 两个都是实际咬过人的 bug：
 *   1. 识别是异步的（云端 Google 要几百毫秒到几秒）。写完最后一个字点「完成」，
 *      那次请求还在飞；结果回来时直接 hwTarget.value = ... —— 正在打的拼音
 *      composition 被这一下打断，WebKit 把预编辑串按**原始字母**提交。
 *      现象是「输入法明明切到中文了，打出来还是 dfsdf sdfss」。
 *      hwClose 清了队列，但已经出队、正在网络上的那一次拦不住 → 加会话代数。
 *   2. body.dark 的底色带 !important（普通面板需要），特异性压过
 *      .hw-fs 的 transparent（不带），全屏透明模式在夜间就成了一块不透光的板。
 *      白天没事，纯粹因为浅色那条没写 !important —— 这种「只在一种主题下坏」的
 *      层叠事故，只有把两种主题都算一遍才抓得住。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');
const { boot } = require('./harness');

const S = path.resolve(__dirname, '../../static');

// jsdom 没有 canvas 后端，但这块的逻辑（排队/作废/填字）跟画不画得出来无关，
// 给个记账用的假 2d 上下文即可。
function stubCanvas(w) {
  const noop = () => {};
  w.HTMLCanvasElement.prototype.getContext = () => ({
    setTransform: noop, clearRect: noop, save: noop, restore: noop, beginPath: noop,
    moveTo: noop, lineTo: noop, stroke: noop, drawImage: noop, setLineDash: noop,
    strokeStyle: '', lineWidth: 0, lineJoin: '', lineCap: '',
  });
}
const ONE_STROKE = 'hwStrokes = [{ x: [10, 20], y: [10, 20], t: [0, 12] }]';
const settle = () => new Promise(r => setTimeout(r, 30));

test('识别结果正常填进目标输入框', async (t) => {
  const h = boot({ fetch: (u) => (u.includes('/api/handwrite') ? { json: { candidates: ['好', '女'] } } : {}) });
  t.after(() => h.close());
  stubCanvas(h.window);
  h.run('openHandwrite("ai-text")');
  h.run(ONE_STROKE); h.run('hwFlush()');
  await settle();
  assert.strictEqual(h.window.document.getElementById('ai-text').value, '好');
});

test('关板后回来的识别结果作废：绝不能再动输入框（会打断输入法正在拼的字）', async (t) => {
  const h = boot({ fetch: (u) => (u.includes('/api/handwrite') ? { json: { candidates: ['好'] } } : {}) });
  t.after(() => h.close());
  stubCanvas(h.window);
  const ta = h.window.document.getElementById('ai-text');
  h.run('openHandwrite("ai-text")');
  h.run(ONE_STROKE);
  h.run('hwFlush()');       // 发出识别请求（还在 await 里）
  h.run('hwClose()');       // 用户点「完成」，转头去键盘打拼音
  ta.value = 'nihao';       // 输入法此刻正在这里拼字
  await settle();
  assert.strictEqual(ta.value, 'nihao',
    '晚到的识别结果又往输入框里塞字了 —— 正在拼的字会被这一下打断，拼音按字母上屏');
  assert.strictEqual(h.run('hwTarget'), null, '关板后 hwTarget 应断开，晚到的插入才无处可写');
});

test('换到另一个输入框，上一个框的识别结果不会串过来', async (t) => {
  const h = boot({ fetch: (u) => (u.includes('/api/handwrite') ? { json: { candidates: ['好'] } } : {}) });
  t.after(() => h.close());
  stubCanvas(h.window);
  h.run('openHandwrite("ai-text")');
  h.run(ONE_STROKE); h.run('hwFlush()');
  h.run('openHandwrite("qn-text")');     // 没关板直接换目标（随手记）
  await settle();
  assert.strictEqual(h.window.document.getElementById('ai-text').value, '');
  assert.strictEqual(h.window.document.getElementById('qn-text').value, '',
    '上一个框写的字串到新框里了');
});

/* ---- 看得见后面：两种模式 × 两种主题，四种组合都得透 ----
 * 评审方案 02「透窗」：遮罩撤掉、田字格全透，面板底留 72% 毛玻璃托住控件。
 * 四种组合都要断言，是因为这块坏过的方式恰恰是「只坏一种」——
 * body.dark 的底色带 !important，白天好好的、夜里就成了一块不透光的板。
 */
function cssBoot() {
  const css = fs.readFileSync(path.join(S, 'style.css'), 'utf8');
  const html = fs.readFileSync(path.join(S, 'index.html'), 'utf8')
    .replace(/<script\b[^>]*><\/script>/g, '')
    .replace('<link rel="stylesheet" href="style.css">', `<style>${css}</style>`);
  const dom = new JSDOM(html, { pretendToBeVisual: true });
  const w = dom.window;
  const modal = w.document.getElementById('hw-modal');
  modal.classList.remove('hidden');
  const bg = (sel) => w.getComputedStyle(modal.querySelector(sel)).backgroundColor;
  return {
    read: (dark, fs2) => {
      w.document.body.classList.toggle('dark', dark);
      modal.classList.toggle('hw-fs', fs2);
      return { 遮罩: w.getComputedStyle(modal).backgroundColor, 面板底: bg('.hw-sheet'), 田字格底: bg('.hw-canvas-wrap') };
    },
    close: () => dom.window.close(),
  };
}
const SEE_THROUGH = new Set(['transparent', 'rgba(0, 0, 0, 0)', '']);
// 面板底不是全透（要托住按钮和候选字），但也不许是实心 —— 读出它的 alpha 来判
const alphaOf = (v) => {
  if (SEE_THROUGH.has(v)) return 0;
  const m = /^rgba\([^)]*,\s*([\d.]+)\)$/.exec(v);
  return m ? +m[1] : 1;
};
const SHEET_MAX_A = 0.8;   // 评审定的是 .72；留一点余量，但实心（1）必须红

for (const dark of [false, true]) {
  for (const fs2 of [false, true]) {
    const 主题 = dark ? '夜间' : '白天', 模式 = fs2 ? '全屏' : '小屏';
    test(`${模式}手写板 · ${主题}：底板不许挡住后面的题目`, (t) => {
      const h = cssBoot(); t.after(() => h.close());
      const got = h.read(dark, fs2);
      const why = `（这块坏过一次：body.dark 的底色带 !important，把 transparent 压掉了）`;
      for (const k of ['遮罩', '田字格底']) {
        assert.ok(SEE_THROUGH.has(got[k]),
          `${模式} ${主题} 的${k}是 ${got[k]} —— 写字时正对着底下的原文，这层必须全透 ${why}`);
      }
      const a = alphaOf(got.面板底);
      if (fs2) {
        assert.strictEqual(a, 0, `全屏模式的面板底是 ${got.面板底}，该整块透出去 ${why}`);
      } else {
        assert.ok(a > 0 && a <= SHEET_MAX_A,
          `小屏面板底是 ${got.面板底}（alpha ${a}）—— 要么实心挡住了后面，` +
          '要么全透了托不住按钮和候选字；评审定的是 72% 毛玻璃');
      }
    });
  }
}

test('全屏模式不许带毛玻璃：那块 sheet 铺满整屏，糊的就是整个屏幕', () => {
  const css = fs.readFileSync(path.join(S, 'style.css'), 'utf8');
  const rule = /\.hw-modal\.hw-fs \.hw-sheet\{[^}]*\}/.exec(css);
  assert.ok(rule, '找不到 .hw-modal.hw-fs .hw-sheet 规则');
  assert.match(rule[0], /-webkit-backdrop-filter:\s*none/, '得把 .hw-sheet 继承来的毛玻璃关掉（前缀版）');
  assert.match(rule[0], /[^-]backdrop-filter:\s*none/, '标准写法也要关');
});

test('小屏面板要配毛玻璃：只降透明度不模糊，后面的字会从按钮缝里钻出来', () => {
  const css = fs.readFileSync(path.join(S, 'style.css'), 'utf8');
  const rule = /\.hw-sheet\{[^}]*\}/.exec(css);
  assert.ok(rule, '找不到 .hw-sheet 规则');
  assert.match(rule[0], /-webkit-backdrop-filter:\s*blur/, 'WebKit 壳要前缀版，缺了就是没模糊');
  assert.match(rule[0], /[^-]backdrop-filter:\s*blur/, '标准写法也要留着');
});
