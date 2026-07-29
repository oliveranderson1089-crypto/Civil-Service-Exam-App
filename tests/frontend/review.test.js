/* 复习：卡片显示 + 「认识 → N 天后」的预告。
 *
 * 后端那 26 条测试的注释里记着三次真实教训，其中一次是「白名单手抄了第二份，
 * 加新来源时取词那边加了、提交这边忘了加，卡片点认识直接参数错误」。
 * 而前端又抄了第三份 —— RV_INTERVALS 是 mods/review.py 里 REVIEW_INTERVALS 的副本。
 *
 * 这份副本删不掉：「认识 → 2 天后」是点之前就得显示的预告，那时还没调接口、
 * 拿不到后端算的 interval。删不掉就得盯着，别让它俩走散。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { boot } = require('./harness');

const ROOT = path.resolve(__dirname, '../..');

test('间隔表跨端一致：前端的 RV_INTERVALS 必须等于后端的 REVIEW_INTERVALS', (t) => {
  const py = fs.readFileSync(path.join(ROOT, 'mods/review.py'), 'utf8');
  const js = fs.readFileSync(path.join(ROOT, 'static/js/review.js'), 'utf8');
  const mPy = py.match(/^REVIEW_INTERVALS = \[([^\]]+)\]/m);
  const mJs = js.match(/^const RV_INTERVALS = \[([^\]]+)\]/m);
  assert.ok(mPy, 'mods/review.py 里找不到 REVIEW_INTERVALS —— 改名了？');
  assert.ok(mJs, 'static/js/review.js 里找不到 RV_INTERVALS');
  const nums = (s) => s.split(',').map(x => x.trim()).filter(Boolean).map(Number);
  assert.deepStrictEqual(nums(mJs[1]), nums(mPy[1]),
    '前后端的复习间隔对不上了 —— 用户看到的「N 天后」会跟服务器实际排的不是一回事');
});

test('「认识 → N 天后」跟后端算出来的一致（逐阶对齐）', (t) => {
  const h = boot(); t.after(() => h.close());
  const IV = h.run('RV_INTERVALS');
  // 后端：stage = cur + 1; iv = REVIEW_INTERVALS[min(stage, len-1)]
  // 前端：nd = RV_INTERVALS[min(it.stage + 1, len-1)]     （it.stage 就是 cur）
  for (let cur = 0; cur < 12; cur++) {
    const back = IV[Math.min(cur + 1, IV.length - 1)];
    const front = IV[Math.min(cur + 1, IV.length - 1)];
    assert.strictEqual(front, back, `第 ${cur} 阶对不上`);
  }
  assert.strictEqual(IV[Math.min(0 + 1, IV.length - 1)], 2, '第一次点「认识」该是 2 天后');
  assert.strictEqual(IV[Math.min(99 + 1, IV.length - 1)], 60, '到顶后该停在 60 天，不能越界');
});

test('rvShow：卡片正面显示题目，答案藏着（不然点开就看见答案了）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`rvQueue = [{ kind: 'entry', stage: 0, front: '高瞻远瞩', front_sub: 'gāo zhān',
                      back: '站得高看得远' }]; rvTotal = 1; rvDoneN = 0; rvShow();`);
  const d = h.window.document;
  assert.strictEqual(d.querySelector('#rvf-title').textContent, '高瞻远瞩');
  assert.ok(d.querySelector('#rv-back').classList.contains('hidden'), '答案没藏住');
  assert.ok(!d.querySelector('#rvf-hint').classList.contains('hidden'), '「点一下看答案」的提示该在');
});

test('rvShow：「认识」按钮上写的天数按当前轮次走', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`rvQueue = [{ kind: 'entry', stage: 0, front: 'x', back: 'y' }]; rvTotal = 1; rvDoneN = 0; rvShow();`);
  assert.strictEqual(h.window.document.querySelector('#rv-know-d').textContent, '2 天后');
  h.run(`rvQueue = [{ kind: 'entry', stage: 3, front: 'x', back: 'y' }]; rvShow();`);
  assert.strictEqual(h.window.document.querySelector('#rv-know-d').textContent, '15 天后');
  h.run(`rvQueue = [{ kind: 'entry', stage: 99, front: 'x', back: 'y' }]; rvShow();`);
  assert.strictEqual(h.window.document.querySelector('#rv-know-d').textContent, '60 天后', '到顶后越界了');
});

test('rvShow：轮次显示从 1 开始数（stage 0 = 第 1 轮，别让人看见「第 0 轮」）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`rvQueue = [{ kind: 'entry', stage: 0, front: 'x', back: 'y' }]; rvTotal = 1; rvDoneN = 0; rvShow();`);
  assert.strictEqual(h.window.document.querySelector('#rv-round').textContent, '第 1 轮');
});

test('rvShow：队列空了就显示「今天背完了」，不是空白卡片', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('rvQueue = []; rvShow();');
  const d = h.window.document;
  assert.ok(d.querySelector('#rv-card-wrap').classList.contains('hidden'));
  assert.ok(!d.querySelector('#rv-done').classList.contains('hidden'), '背完了却不给个交代');
});

test('rvShow：进度条与计数对得上', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`rvQueue = [{ kind: 'entry', stage: 0, front: 'x', back: 'y' }]; rvTotal = 4; rvDoneN = 3; rvShow();`);
  const d = h.window.document;
  assert.strictEqual(d.querySelector('#rv-pos').textContent, '已复习 3 / 4');
  assert.strictEqual(d.querySelector('#rv-bar').style.width, '75%');
});

test('rvShow：rvTotal 为 0 时进度条不能算出 NaN%', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`rvQueue = [{ kind: 'entry', stage: 0, front: 'x', back: 'y' }]; rvTotal = 0; rvDoneN = 0; rvShow();`);
  assert.strictEqual(h.window.document.querySelector('#rv-bar').style.width, '0%');
});

test('分组名字只有一份（原先 RV_GROUP_NAME / RV_LNAME 一字不差地并存）', (t) => {
  const js = fs.readFileSync(path.join(ROOT, 'static/js/review.js'), 'utf8');
  assert.ok(!/RV_GROUP_NAME/.test(js), '重复的分组名映射又回来了');
  const m = js.match(/const RV_LNAME = \{([^}]+)\}/);
  assert.ok(m, 'RV_LNAME 没了？');
  for (const g of ['word', 'daily', 'gushi', 'annot', 'wrongq']) {
    assert.ok(m[1].includes(g + ':'), `分组 ${g} 没名字，界面上会显示 undefined`);
  }
});
