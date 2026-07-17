/* 本地存储：写失败必须看得见。
 *
 * 这组盯的是 ebf9da5 那个病：localStorage 配额被撑满 → setItem 抛
 * QuotaExceededError → 被 catch(_){} 吞掉 → 用户画了一整页笔迹全丢，界面上还好好的。
 * 那次只修了 Ink._stash，matSave 漏了（同样的病、另一处），见 a7b8071。
 *
 * 跑的是真的 static/app.js，不是抠出来的副本。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('存储正常时：写进去、读得回、返回 true', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.strictEqual(h.T.lsSet('k', 'v'), true);
  assert.strictEqual(h.T.lsGet('k'), 'v');
});

test('配额满时：返回 false，而不是抛异常打断调用方', (t) => {
  const h = boot(); t.after(() => h.close());
  h.fillStorage();
  assert.strictEqual(h.T.lsSet('ink:p1', 'x'), false);   // 不抛
});

test('配额满时：必须告诉用户，不能装作存上了', (t) => {
  const h = boot(); t.after(() => h.close());
  h.fillStorage();
  h.T.lsSet('ink:p1', 'x');
  assert.strictEqual(h.toasts.length, 1, '一声不吭 = ebf9da5 那个 bug 回来了');
  assert.match(h.toasts[0].msg, /存储已满|没保存/);
  assert.strictEqual(h.toasts[0].err, true, '应该是错误样式的提示');
});

test('同一把钥匙连写多次只吵一次（笔迹是每笔都存的，弹 20 次没法用）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.fillStorage();
  for (let i = 0; i < 20; i++) h.T.lsSet('ink:p1', 'stroke' + i);
  assert.strictEqual(h.toasts.length, 1, `弹了 ${h.toasts.length} 次`);
});

test('换一把钥匙会重新提醒（是另一份数据在丢）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.fillStorage();
  h.T.lsSet('ink:p1', 'x');
  h.T.lsSet('matmark:m1', 'y');
  assert.strictEqual(h.toasts.length, 2);
});

test('写成功之后再失败，会重新提醒（不能因为提醒过就永远闭嘴）', (t) => {
  const h = boot(); t.after(() => h.close());
  let free = h.fillStorage();
  h.T.lsSet('k', '1');
  assert.strictEqual(h.toasts.length, 1);
  free();                                  // 腾出空间了
  h.T.lsSet('k', '2');
  h.fillStorage();                         // 又满了
  h.T.lsSet('k', '3');
  assert.strictEqual(h.toasts.length, 2, '第二次失败应该再说一次');
});

test('写失败也留 console 痕迹，方便排查', (t) => {
  const h = boot(); t.after(() => h.close());
  h.fillStorage();
  h.T.lsSet('k', 'v');
  assert.ok(h.logs.warn.some(l => l.includes('存储')), '没留日志');
});

test('lsGet 默认返回 null，与原生 getItem 等价', (t) => {
  const h = boot(); t.after(() => h.close());
  // 差一点就不等价：+undefined 是 NaN、+null 是 0，而 dtCount 那处正是用 +x 判断
  assert.strictEqual(h.T.lsGet('从来没存过'), null);
  assert.strictEqual(h.T.lsGet('从来没存过', '兜底'), '兜底');
});

test('localStorage 整个不可用时（隐私模式），lsGet 降级而不是崩', (t) => {
  const h = boot(); t.after(() => h.close());
  h.breakStorage();
  assert.strictEqual(h.T.lsGet('k', '兜底'), '兜底');   // app.js 里好几处 getItem 在模块加载时就跑，一抛整个应用就废
});

test('matSave：配额满时用户得知道自己划的重点没存上（ebf9da5 的漏网之鱼）', (t) => {
  const h = boot(); t.after(() => h.close());
  const w = h.window;
  h.run('matKey = "matmark:test"; matStrokes = [{ tool:"hl", color:"#f0a500", pts:[{x:0.1,y:0.2}] }];');
  h.fillStorage();
  h.run('matSave()');
  assert.strictEqual(h.toasts.length, 1, 'matSave 又在偷偷吞了');
  assert.match(h.toasts[0].msg, /存储已满|没保存/);
});

test('matSave 正常时真的把笔迹存进去了', (t) => {
  const h = boot(); t.after(() => h.close());
  const w = h.window;
  h.run('matKey = "matmark:t2"; matStrokes = [{ tool:"hl", color:"#f0a500", pts:[{x:0.5,y:0.25}] }];');
  h.run('matSave()');
  const raw = w.localStorage.getItem('matmark:t2');
  assert.ok(raw, '没存进去');
  const d = JSON.parse(raw);
  assert.strictEqual(d.length, 1);
  assert.strictEqual(d[0].t, 'hl');
  assert.deepStrictEqual(d[0].p, [[0.5, 0.25]]);
});
