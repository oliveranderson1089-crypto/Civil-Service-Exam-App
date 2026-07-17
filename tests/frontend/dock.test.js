/* 停靠面板：拖分隔线改大小。
 *
 * 这个模块是「零业务测试」里改动最多的（3 次）—— 拿它验一个假设：
 * 前面挑测试目标时用的是「git log 改动次数 = 风险」，改得勤的（小记 14 次、
 * 申论 13 次、批注 5 轮返工）都补了测试，剩下 39 个改动 1~3 次的模块一条没有。
 * 那假设成不成立？翻开第一个就抓到了 bug，所以：不成立。
 *
 * 抓到的 bug（经典 falsy-zero）：
 *   size() 里 `st.sizes[d] || defSize(d)` 拿 0 当「没拖过 / 双击复位了」的哨兵，
 *   而拖动时算的是 `innerHeight - ev.clientY` —— 一路拖到屏幕边缘，这个值正好是 0。
 *   于是：面板缩到最小值(190px)，再往下拖一点 → 「啪」地弹回半屏(353px)。
 *   松手时 up() 还会把这个尺寸存进 localStorage，下次打开就是错的。
 *   夹到 Math.max(1, raw) 之后，边缘处收敛到 min，不再撞哨兵。
 *
 * 为什么走真实指针事件而不是直接设 st.sizes：
 *   bug 在 mv 里（raw → st.sizes 那一步）。直接设 st.sizes=0 测到的是 size()，
 *   而 size() 把 0 当默认值是**有意的** —— 双击复位就靠这个。两者必须分开测，
 *   否则「修好」的办法会变成拆掉双击复位。
 *
 * jsdom 的脾气（实测）：PointerEvent 有，setPointerCapture 没有 —— 后者被
 * dock.js 里的 try/catch 兜住了，正好证明那个 catch 不是摆设。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

function mkDock(h, defDock) {
  const w = h.window;
  const el = w.document.createElement('div');
  w.document.body.appendChild(el);
  const dk = h.run('createDock')(el, '__test_' + defDock + Math.random(), defDock);
  const grip = el.querySelector('.dk-grip');
  const ev = (t, o) => new w.PointerEvent(t, Object.assign({ bubbles: true, pointerId: 1 }, o));
  // 真实路径：按住分隔线 → 拖 → 松手
  const drag = (to) => {
    grip.dispatchEvent(ev('pointerdown', { clientX: 100, clientY: 100 }));
    grip.dispatchEvent(ev('pointermove', to));
    grip.dispatchEvent(ev('pointerup', to));
  };
  const px = () => el.style.getPropertyValue(w.innerWidth && (defDock === 'left' || defDock === 'right')
    ? '--dk-w' : '--dk-h');
  return { el, dk, grip, drag, px, ev };
}

test('下半屏：分隔线一路拖到屏幕最底边 → 收到最小值，不许弹回半屏', (t) => {
  const h = boot(); t.after(() => h.close());
  const d = mkDock(h, 'bottom');
  const half = Math.round(h.window.innerHeight * 0.46);   // 353：弹回半屏就是这个数
  d.drag({ clientY: h.window.innerHeight });              // innerHeight - clientY === 0
  assert.strictEqual(d.px(), '190px',
    `拖到最底边得到 ${d.px()}，期望 190px（最小值）；若等于 ${half}px 说明 0 又被当成` +
    '「用默认值」了 —— 用户拖到最小再拖一点，面板会猛地弹回一半');
  assert.strictEqual(d.dk.st.sizes.bottom, 190, '松手存进 localStorage 的尺寸也得是夹取后的值');
});

test('右半屏：拖到最右边同理（横向那条路是另一套坐标）', (t) => {
  const h = boot(); t.after(() => h.close());
  const d = mkDock(h, 'right');
  d.drag({ clientX: h.window.innerWidth });               // innerWidth - clientX === 0
  assert.strictEqual(d.px(), '280px', '横向的最小值是 280');
});

test('拖出屏幕外（负数）也收敛到最小值，不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  const d = mkDock(h, 'bottom');
  d.drag({ clientY: h.window.innerHeight + 500 });
  assert.strictEqual(d.px(), '190px');
});

test('正常范围内的拖动照常工作：拖到哪儿就是多大', (t) => {
  const h = boot(); t.after(() => h.close());
  const d = mkDock(h, 'bottom');
  d.drag({ clientY: h.window.innerHeight - 300 });
  assert.strictEqual(d.px(), '300px', '正常范围内的拖动被改坏了');
});

test('双击复位仍然回到一半 —— 0 哨兵是有意的，别为了修上面那个 bug 把它拆了', (t) => {
  const h = boot(); t.after(() => h.close());
  const d = mkDock(h, 'bottom');
  const half = Math.round(h.window.innerHeight * 0.46);
  d.drag({ clientY: h.window.innerHeight - 300 });
  assert.strictEqual(d.px(), '300px');
  d.grip.dispatchEvent(new h.window.MouseEvent('dblclick', { bubbles: true }));
  assert.strictEqual(d.px(), half + 'px', '双击复位没回到一半 —— size() 的 0 哨兵被误伤了');
});
