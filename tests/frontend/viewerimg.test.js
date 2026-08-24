/* 查看器：图片走自己的那套，不再丢给 iframe。
 *
 * 起因：iframe 里 WebKit 按**原始像素**铺开图片（Chrome 会自动缩，WebKitGTK 不会），
 * 手机拍的 4000px 证书打开就是糊在屏幕上的一角；而页面 meta 写着 user-scalable=no，
 * 手机上连捏合缩小都借不到。所以这里钉死：图片进图片层、整张放得进窗口、能缩放。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const $ = (h, id) => h.window.document.getElementById(id);
const hidden = (h, id) => $(h, id).classList.contains('hidden');

test('图片走图片层，iframe 不参与（也不能在后台白下一遍）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('openViewerUrl')('/api/drive/9/view', '毕业证.jpg', '.jpg', '/api/drive/9/download');
  assert.ok(!hidden(h, 'viewer-img'), '图片层要露出来');
  assert.ok(hidden(h, 'viewer-frame'), 'iframe 要收起来');
  assert.ok(!$(h, 'viewer-frame').getAttribute('src'), 'iframe 还挂着地址就是在后台又下一遍');
  assert.strictEqual($(h, 'viewer-img').querySelector('img').getAttribute('src'), '/api/drive/9/view');
  assert.ok(!hidden(h, 'viewer-fit'), '缩放按钮跟着图片一起出现');
});

test('换成 PDF 时图片层要收干净，不能垫在底下', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('openViewerUrl')('/api/drive/9/view', '证.png', '.png', null);
  h.run('openViewerUrl')('/api/drive/10/view', '讲义.pdf', '.pdf', null);
  assert.ok(hidden(h, 'viewer-img'));
  assert.ok(hidden(h, 'viewer-fit'));
  assert.ok(!$(h, 'viewer-img').querySelector('img').getAttribute('src'), '上一张图要卸掉');
  assert.ok(!hidden(h, 'viewer-frame'));
});

test('图片没有「阅读模式」「批注」这些跟它无关的按钮', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('openViewerUrl')('/x.jpg', 'x.jpg', '.jpg', null, '/x?text=1');
  assert.ok(hidden(h, 'viewer-mode'));
  assert.ok(hidden(h, 'viewer-ink'));
});

test('打开时是「整张放进窗口」：不缩不移，样式交给 CSS 的 contain', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('openViewerUrl')('/x.jpg', 'x.jpg', '.jpg', null);
  assert.strictEqual(h.run('vimgS'), 1);
  assert.match($(h, 'viewer-img').querySelector('img').style.transform, /scale\(1\)/);
  assert.match($(h, 'viewer-fit').textContent, /原始大小/);
});

test('缩放有上限，缩回去会归位（不留个偏出屏幕的死角）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('openViewerUrl')('/x.jpg', 'x.jpg', '.jpg', null);
  h.run('vimgZoom(3, 10, 10)');
  assert.strictEqual(h.run('vimgS'), 3);
  assert.match($(h, 'viewer-fit').textContent, /整张/, '放大后按钮该给「回到整张」这条路');
  h.run('vimgZoom(999)');
  assert.strictEqual(h.run('vimgS'), 8, '再怎么点也不该无限放大');
  h.run('vimgZoom(0.2)');
  assert.strictEqual(h.run('vimgS'), 1, '缩不到比整张更小');
  assert.deepStrictEqual([h.run('vimgX'), h.run('vimgY')], [0, 0], '回到整张时平移要清零');
});

test('缩放锚在指哪儿：放大后那个点还在原地', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('openViewerUrl')('/x.jpg', 'x.jpg', '.jpg', null);
  // jsdom 里元素尺寸都是 0，容器中心就是 (0,0)：锚点 (100,0) 相对中心偏 +100，
  // 放大 2 倍后它应当被推到 -100，才能让指头底下那一点不动
  h.run('vimgZoom(2, 100, 0)');
  assert.strictEqual(Math.round(h.run('vimgX')), -100);
});

/* ---- 查看器的返回只留一个 ----
   顶栏（#nav-back）和查看器工具条上原来各有一个「‹ 返回」，上下两行说同一句话。
   撤掉工具条那个之后，全屏时的退路必须还在：那时顶栏和工具条**都是隐藏的**，
   只剩右下角的 #viewer-exit 和返回键 —— 所以 appBack 得先退全屏，再谈退栈。 */
test('查看器里只剩顶栏那一个返回', (t) => {
  const h = boot(); t.after(() => h.close());
  const bar = h.window.document.querySelector('.viewer-bar');
  assert.strictEqual(bar.querySelector('#viewer-back'), null, '工具条上还留着第二个返回');
  assert.ok($(h, 'nav-back'), '顶栏那个返回不能跟着一起没了');
  assert.ok($(h, 'viewer-exit'), '全屏时唯一的按钮退路');
});

test('全屏看文件时，返回键先退全屏而不是退出这一页', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run("stack = [{ view: 'home' }, { view: 'viewer', title: '讲义.pdf' }]");
  h.run('setViewerFull(true)');
  assert.strictEqual(h.run('appBack()'), true);
  assert.ok(!h.window.document.body.classList.contains('viewer-full'), '没退全屏');
  assert.strictEqual(h.run('stack.length'), 2, '一下退了两件事：全屏退了，页也退了');
});

/* ---- 夹在中间的 PDF 要跟着应用一起暗下来 ----
   pdf.js 只认系统的 prefers-color-scheme，而我们的明暗是 body.dark（还可能来自
   「跟随天光」，跟系统深浅无关）。各判各的结果就是：夜里应用全黑，中间那份 PDF 雪白。 */
test('夜间：给 pdf.js 挂上 is-dark，白天挂 is-light', (t) => {
  const h = boot(); t.after(() => h.close());
  const doc = h.window.document;
  const inner = $(h, 'viewer-frame').contentDocument;
  if (!inner) { t.skip('jsdom 没给 iframe 造文档'); return; }
  doc.body.classList.add('dark');
  h.run('applyViewerTheme()');
  assert.ok(inner.documentElement.classList.contains('is-dark'), 'PDF 那一片还是白的');
  doc.body.classList.remove('dark');
  h.run('applyViewerTheme()');
  assert.ok(inner.documentElement.classList.contains('is-light'), '白天要压住系统的深色偏好');
  assert.ok(!inner.documentElement.classList.contains('is-dark'));
});
