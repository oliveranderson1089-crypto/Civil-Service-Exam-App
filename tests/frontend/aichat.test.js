/* AI 工具动作：说「已为你打开」之前，得真的打开了。
 *
 * 原先是 try { window[a.fn](); } catch (_) {} 然后**无条件** toast「已为你打开」——
 * 函数一抛异常就被吞掉，用户收到「已为你打开成语积累」，页面纹丝不动。
 * 跟后端 _save_cfg 一个模式：界面说成了，其实没有。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('打开成功才说「已为你打开」', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('window.__opened = 0; window.openIdiom = () => { window.__opened++; };');
  h.run('stack = [{ view: "home" }];');
  h.run('aiRunActions([{ type: "navigate", fn: "openIdiom", label: "成语积累" }])');
  assert.strictEqual(h.window.__opened, 1, '压根没调用目标函数');
  // 不用 deepStrictEqual：toast 对象是在 jsdom 那个 realm 里造的，原型跟 node 的不是同一个，
  // strict 版会因「结构相同但原型不是同一引用」而失败。比字段即可。
  assert.strictEqual(h.toasts.length, 1);
  assert.strictEqual(h.toasts[0].msg, '已为你打开「成语积累」');
  assert.strictEqual(h.toasts[0].err, false);
});

test('打开失败要说没成功，不能还报「已为你打开」', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('window.openIdiom = () => { throw new Error("界面炸了"); };');
  h.run('stack = [{ view: "home" }];');
  h.run('aiRunActions([{ type: "navigate", fn: "openIdiom", label: "成语积累" }])');
  assert.strictEqual(h.toasts.length, 1);
  assert.match(h.toasts[0].msg, /没成功/, `用户被告知「${h.toasts[0].msg}」，可页面根本没打开`);
  assert.strictEqual(h.toasts[0].err, true, '该是错误样式');
  assert.ok(h.logs.error.length > 0, '得留 console 痕迹，不然没法查是哪个函数炸的');
});

test('AI 给了不存在的函数名时安静跳过（typeof 那道检查还在）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('stack = [{ view: "home" }];');
  h.run('aiRunActions([{ type: "navigate", fn: "根本没这个函数", label: "X" }])');
  assert.strictEqual(h.toasts.length, 0, 'AI 瞎给函数名时不该骗用户说打开了');
});

test('空动作列表不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('stack = [{ view: "home" }];');
  h.run('aiRunActions([])');
  h.run('aiRunActions(null)');
  assert.strictEqual(h.toasts.length, 0);
});
