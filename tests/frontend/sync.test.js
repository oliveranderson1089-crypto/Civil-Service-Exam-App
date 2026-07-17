/* 自动同步：代码 bug 不能被当成网络抖动咽下去。
 *
 * 这组是 9edf460 那个 bug 的回归网：
 *   SYNC_REFRESH.write 调 loadWrite()，可 loadWrite 在 0134dfe 被误删了 →
 *   每 30 秒 ReferenceError → 被 checkSync 的 catch(_){} 吞掉 →
 *   而 _syncToken 在调用前就已更新，这次变更等于被消费掉 →
 *   写作页的自动同步整整一个版本没工作过，且毫无迹象。
 *
 * 「表里有没有引用不存在的函数」交给 eslint 的 no-undef（它就是这么抓到 loadWrite 的），
 * 这里只测运行时行为：派发对不对、错误分不分得清。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('write 这条派发到 wrSwitch（loadWrite 那处的定点回归）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('window.__hit = 0; wrSwitch = () => { window.__hit++; };');
  h.run('SYNC_REFRESH["write"]()');
  assert.strictEqual(h.window.__hit, 1, 'write 的刷新没接上');
});

test('SYNC_REFRESH 覆盖了所有会被刷新的视图，且都是函数', (t) => {
  const h = boot(); t.after(() => h.close());
  const views = h.run('Object.keys(SYNC_REFRESH)');
  assert.ok(views.includes('write'), 'write 不在表里了');
  assert.ok(views.length >= 15, `表里只剩 ${views.length} 项，是不是被删漏了`);
  for (const v of views) {
    assert.strictEqual(h.run(`typeof SYNC_REFRESH[${JSON.stringify(v)}]`), 'function', v + ' 不是函数');
  }
});

test('checkSync：刷新处理器里的代码 bug 要喊出来，不能被当网络抖动', async (t) => {
  const h = boot(); t.after(() => h.close());
  h.window.fetch = async (u) => ({
    status: 200, ok: true, headers: { get: () => 'application/json' },
    json: async () => (String(u).includes('/api/sync') ? { token: 'new' } : {}),
  });
  // 视图停在 write，让它的处理器抛 ReferenceError —— 正是 loadWrite 当年的样子
  h.run('_syncToken = "old"; _syncBusy = false; ME = { id: 1 };');
  h.run('stack = [{ view: "write" }];');
  h.run('wrSwitch = () => { throw new ReferenceError("loadWrite is not defined"); };');
  await h.run('checkSync()');

  assert.ok(h.logs.error.some(l => l.includes('bug')),
    '代码错误被静默了 —— 这正是 loadWrite 能藏一整个版本的原因');
});

test('checkSync：网络失败保持安静，但留 debug 痕迹', async (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('_syncToken = "old"; _syncBusy = false; ME = { id: 1 };');
  h.window.fetch = async () => { throw new Error('Failed to fetch'); };
  await h.run('checkSync()');
  assert.strictEqual(h.logs.error.length, 0, '网络抖一下不该在控制台报错');
  assert.ok(h.logs.debug.length > 0, '但也该留个痕迹');
});

test('checkSync 跑完必须放开 _syncBusy，否则同步永久卡死', async (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('_syncToken = "old"; _syncBusy = false; ME = { id: 1 };');
  h.window.fetch = async () => { throw new Error('boom'); };
  await h.run('checkSync()');
  assert.strictEqual(h.run('_syncBusy'), false,
    '_syncBusy 没放开，之后每次 checkSync 都会直接 return —— 同步再也不会跑');
});

test('正在编辑时不打扰（_syncEditing 挡住刷新）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('stack = [{ view: "doc" }];');
  assert.strictEqual(h.run('_syncEditing()'), true, '在块编辑器里还刷新，会把用户写的冲掉');
});
