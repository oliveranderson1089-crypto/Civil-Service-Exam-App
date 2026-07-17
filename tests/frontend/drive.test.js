/* 云盘：文件大小格式化 fSize。
 *
 * drive 改动 1 次、零测试。fSize 把字节数格式化成 B/KB/MB，是纯函数。盯边界：
 * 1024 的进位点、小数位、0/空不炸。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('fSize：按 1024 分档 B / KB / MB', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('fSize');
  assert.strictEqual(f(0), '0 B');
  assert.strictEqual(f(512), '512 B');
  assert.strictEqual(f(1023), '1023 B', '差一字节到 1KB，还是 B');
  assert.strictEqual(f(1024), '1.0 KB', '正好 1024 该进位到 KB');
  assert.strictEqual(f(1536), '1.5 KB');
  assert.strictEqual(f(1047552), '1023.0 KB', '差一点到 1MB（1048576）还是 KB —— 进位阈值必须是 1024²，不是 10⁶');
  assert.strictEqual(f(1048576), '1.0 MB', '正好 1MB');
  assert.strictEqual(f(5 * 1048576), '5.0 MB');
});

test('fSize：KB / MB 留一位小数（截断，不四舍五入到整数）', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('fSize');
  assert.match(f(1234567), /^1\.2 MB$/);
  assert.match(f(2600), /^2\.5 KB$/);
});

test('fSize：null / undefined 当 0，不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('fSize');
  assert.strictEqual(f(null), '0 B');
  assert.strictEqual(f(undefined), '0 B');
});
