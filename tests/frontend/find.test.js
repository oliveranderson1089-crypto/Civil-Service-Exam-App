/* 找要点（贯彻执行/概括题的两步练法）：勾选集合 frToggle + 页脚 frFoot。
 *
 * find 改动 1 次、15 个函数、零测试。第一步「只找不写」——在材料里点句子勾要点，
 * frToggle 维护一个已勾集合并实时更新计数；第二步照勾到的写。文种（doctype）来自
 * 数据、拼进提示语，要转义。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('frToggle：勾/取消维护集合，计数实时更新', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`fdPicked = new Set(); $('#fr-n') && ($('#fr-n').textContent = '0');`);
  // fr-n 由 frFoot 渲染出来；先渲染第一步再勾
  h.run(`fdStep = 1; fdPaper = { n_points: 5, sents: [] }; frFoot();`);
  h.run('frToggle(3, true)');
  h.run('frToggle(7, true)');
  assert.strictEqual(h.run('fdPicked.size'), 2);
  assert.strictEqual(h.window.document.querySelector('#fr-n').textContent, '2', '计数没跟上勾选');
  h.run('frToggle(3, false)');
  assert.strictEqual(h.run('fdPicked.size'), 1, '取消勾选没从集合里删掉');
  assert.strictEqual(h.window.document.querySelector('#fr-n').textContent, '1');
});

test('frToggle：重复勾同一句不会重复计数（Set 去重）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`fdPicked = new Set(); fdStep = 1; fdPaper = { n_points: 5, sents: [] }; frFoot();`);
  h.run('frToggle(3, true); frToggle(3, true)');
  assert.strictEqual(h.run('fdPicked.size'), 1);
});

test('frFoot 第一步：显示采分点数和已勾数', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`fdPicked = new Set([1, 2]); fdStep = 1; fdPaper = { n_points: 8, sents: [] }; frFoot();`);
  const html = h.window.document.querySelector('#fr-foot').innerHTML;
  assert.match(html, /共 8 个采分点/);
  assert.match(html, /id="fr-n">2</, '已勾数没显示');
});

test('frFoot 第二步：文种（doctype）转义后拼进提示', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`fdPicked = new Set();
    fdStep = 2;
    fdPaper = { doctype: '<img src=x onerror=alert(1)>', doctype_fmt: '', word_min: 200, word_max: 400, sents: [] };
    frFoot();`);
  const box = h.window.document.querySelector('#fr-foot');
  assert.strictEqual(box.querySelector('img'), null, 'doctype 里的 img 活了');
});

/* ---- 第一步勾画的手势：手指连点两下才算数，鼠标照旧一下就选 ----
   手机上材料是滑着看的，手指一落就选 = 滑一下误勾一片。 */
function findRun(h, sents) {
  h.run(`fdStep = 1; fdMaxStep = 1; fdCheck = null; fdPicked = new Set();
    fdPaper = { id: 1, n_points: 3, sents: ${JSON.stringify(sents)} };
    frMat(); frFoot();`);
  return (i) => h.window.document.querySelector(`#fr-mat [data-fs="${i}"]`);
}
const SENTS = [{ i: 0, p: 0, t: '第一句。' }, { i: 1, p: 0, t: '第二句。' }];
// pointerdown → pointerup 打一整下；dx/dy = 抬手时手指挪了多远
function tap(h, el, o = {}) {
  const w = h.window;
  const mk = (type, x, y) => new w.PointerEvent(type, {
    bubbles: true, cancelable: true, pointerId: 1, pointerType: o.type || 'touch', clientX: x, clientY: y });
  el.dispatchEvent(mk('pointerdown', 50, 50));
  (o.upOn || el).dispatchEvent(mk('pointerup', 50 + (o.dx || 0), 50 + (o.dy || 0)));
}

test('找点·触摸：点一下只待定，第二下才真勾上', (t) => {
  const h = boot({ mobile: true }); t.after(() => h.close());
  const el = findRun(h, SENTS);
  tap(h, el(0));
  assert.strictEqual(h.run('fdPicked.has(0)'), false, '第一下就勾上了 = 滑动照样误触');
  assert.ok(el(0).classList.contains('pre'), '第一下没给「待定」的视觉反馈');
  tap(h, el(0));
  assert.strictEqual(h.run('fdPicked.has(0)'), true, '第二下没勾上');
  assert.ok(el(0).classList.contains('on') && !el(0).classList.contains('pre'));
  // 勾上的再连点两下 = 取消
  tap(h, el(0)); tap(h, el(0));
  assert.strictEqual(h.run('fdPicked.has(0)'), false, '连点两下没能取消');
});

test('找点·触摸：两下点在不同句子上不算数', (t) => {
  const h = boot({ mobile: true }); t.after(() => h.close());
  const el = findRun(h, SENTS);
  tap(h, el(0)); tap(h, el(1));
  assert.strictEqual(h.run('fdPicked.size'), 0, '第二下点的是别的句子，不该勾上任何一句');
  assert.ok(el(1).classList.contains('pre'), '待定标记应该跟到最后点的那句上');
});

test('找点·触摸：手指挪动超过阈值当滑动，不算点', (t) => {
  const h = boot({ mobile: true }); t.after(() => h.close());
  const el = findRun(h, SENTS);
  tap(h, el(0), { dy: 40 });                     // 滑
  assert.strictEqual(h.run('fdTapI'), null, '滑一下也记成了「点过一次」');
  tap(h, el(0), { dy: 40 }); tap(h, el(0), { dy: 40 });
  assert.strictEqual(h.run('fdPicked.size'), 0, '滑动被判成了勾选');
  // 落在这句、抬手在另一句（手指划过去了）同样不算
  tap(h, el(0), { upOn: el(1) }); tap(h, el(0), { upOn: el(1) });
  assert.strictEqual(h.run('fdPicked.size'), 0);
});

test('找点·鼠标：一下就选，手势没被触摸那套改坏', (t) => {
  const h = boot(); t.after(() => h.close());
  const el = findRun(h, SENTS);
  tap(h, el(0), { type: 'mouse' });
  assert.strictEqual(h.run('fdPicked.has(0)'), true, '鼠标点一下没选中');
  tap(h, el(0), { type: 'mouse' });
  assert.strictEqual(h.run('fdPicked.has(0)'), false, '鼠标再点一下没取消');
});

test('frFoot 第一步：手机提示说的是连点两下', (t) => {
  const h = boot({ mobile: true }); t.after(() => h.close());
  h.run(`fdPicked = new Set(); fdStep = 1; fdPaper = { n_points: 8, sents: [] }; frFoot();`);
  assert.match(h.window.document.querySelector('#fr-foot').innerHTML, /连点两下/);
});

test('找点·触摸：隔太久的第二下重新算第一下', async (t) => {
  const h = boot({ mobile: true }); t.after(() => h.close());
  const el = findRun(h, SENTS);
  tap(h, el(0));
  await new Promise(r => setTimeout(r, h.run('FD_TAP_MS') + 120));
  assert.strictEqual(h.run('fdTapI'), null, '待定态过了窗口没自己消掉');
  assert.ok(!el(0).classList.contains('pre'));
  tap(h, el(0));
  assert.strictEqual(h.run('fdPicked.size'), 0, '隔了半天的两下被当成连点');
});
