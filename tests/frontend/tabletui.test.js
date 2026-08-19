/* 平板不该被当成手机。
 *
 * IS_MOBILE 的定义是「装了 App 或 窄屏」，平板上装的 APK 直接命中前半句，于是 CSS 里
 * 那条 body.mobile-ui 的规则把 AI 面板的停靠手柄和全屏按钮一起藏了 —— 平板明明有的是
 * 地方，对话框却拖不动也全不了屏。
 *
 * 修法是不动 IS_MOBILE（全站开关），另加一个只按短边算、且会跟着转屏更新的判定。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { boot } = require('./harness');

const CSS = fs.readFileSync(path.join(__dirname, '../../static/style.css'), 'utf8');

function setSize(h, w, ht) {
  Object.defineProperty(h.window, 'innerWidth', { value: w, configurable: true });
  Object.defineProperty(h.window, 'innerHeight', { value: ht, configurable: true });
  h.window.dispatchEvent(new h.window.Event('resize'));
}
const cls = (h) => [...h.window.document.body.classList];

test('平板尺寸下挂上 tablet-ui，手机尺寸下没有', (t) => {
  const h = boot({ mobile: true }); t.after(() => h.close());
  assert.ok(cls(h).includes('mobile-ui'), '前置条件：这是「手机端」那一套');

  setSize(h, 1280, 800);                     // 平板横屏
  assert.ok(cls(h).includes('tablet-ui'), '平板该拿回停靠和全屏');

  setSize(h, 412, 915);                      // 手机竖屏
  assert.ok(!cls(h).includes('tablet-ui'), '手机不该有');
});

test('按短边判定：手机横过来不算平板', (t) => {
  const h = boot({ mobile: true }); t.after(() => h.close());
  setSize(h, 915, 412);                      // 手机横屏：宽度够大，短边只有 412
  assert.ok(!cls(h).includes('tablet-ui'), '光看宽度的话，横过来的手机会被误判成平板');
});

test('转屏后会重新判定（不是加载时算死的）', (t) => {
  const h = boot({ mobile: true }); t.after(() => h.close());
  setSize(h, 800, 1280);                     // 平板竖屏
  assert.ok(cls(h).includes('tablet-ui'));
  Object.defineProperty(h.window, 'innerWidth', { value: 500, configurable: true });
  Object.defineProperty(h.window, 'innerHeight', { value: 900, configurable: true });
  h.window.dispatchEvent(new h.window.Event('orientationchange'));
  assert.ok(!cls(h).includes('tablet-ui'), '转屏事件也要认，安卓壳发的是这个');
});

test('电脑端不该被挂上 tablet-ui（它本来就有停靠和全屏）', (t) => {
  const h = boot({ mobile: false }); t.after(() => h.close());
  setSize(h, 1440, 900);
  assert.ok(!cls(h).includes('mobile-ui'));
  assert.ok(!cls(h).includes('tablet-ui'), 'tablet-ui 只用来给手机那套开小灶');
});

test('CSS 那条隐藏规则把平板排除在外', () => {
  const rule = CSS.split('\n').filter(l => l.includes('.ai-panel .ai-full')).join('\n');
  assert.ok(rule, '找不到隐藏停靠/全屏的那条规则，选择器改名了？');
  assert.ok(rule.includes(':not(.tablet-ui)'),
    '平板仍然会被这条规则连坐 —— 手柄和全屏按钮还是看不到');
});
