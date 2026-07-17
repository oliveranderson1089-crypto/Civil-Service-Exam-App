/* 视频播放器：时间格式化 vpFmt。
 *
 * video 改动 2 次、零测试。vpFmt 把秒数格式化成进度条上的时间，是纯函数，
 * 也是播放器里唯一不依赖真实 <video>/HLS 的可测点。盯几个边界：
 * 不满 1 小时不显示小时位、负数/NaN 不崩、秒和分都补零。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('vpFmt：不满 1 小时显示 m:ss，满 1 小时显示 h:mm:ss', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('vpFmt');
  assert.strictEqual(f(0), '0:00');
  assert.strictEqual(f(9), '0:09', '秒要补零');
  assert.strictEqual(f(75), '1:15');
  assert.strictEqual(f(3599), '59:59', '差一秒到 1 小时，还是 m:ss');
  assert.strictEqual(f(3600), '1:00:00', '满 1 小时进位到 h:mm:ss，分和秒都补零');
  assert.strictEqual(f(3661), '1:01:01');
});

test('vpFmt：小数向下取整（进度条不该显示 1.9 秒）', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.strictEqual(h.run('vpFmt')(65.9), '1:05');
});

test('vpFmt：负数 / NaN / 空 都算 0，不崩', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('vpFmt');
  assert.strictEqual(f(-5), '0:00', '负数（seek 越界）该夹成 0');
  assert.strictEqual(f(NaN), '0:00', '还没拿到时长时是 NaN');
  assert.strictEqual(f(null), '0:00');
  assert.strictEqual(f(undefined), '0:00');
});
