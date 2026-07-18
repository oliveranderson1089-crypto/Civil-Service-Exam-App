/* 桌面版：base64 转文件 b64ToFile。
 *
 * desktop 改动 1 次、零测试。桌面壳把粘贴/拖入的图片以 base64 传进来，b64ToFile 还原成
 * File。关键是**必须按后缀补 MIME**：注释里记着教训 —— 原来不补，造出的 File.type 是空，
 * 凡是靠 f.type 判「是不是图片」的地方（compressImage/qnAddImgs/addDraftImages）全把它
 * 当非图片丢掉，表现就是「拖进去没反应」。这条测试就守着那个 type。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

// 1x1 PNG 的 base64（去掉 data: 头）
const PNG1 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

test('按后缀补上正确的 MIME（否则会被当非图片丢掉）', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('b64ToFile');
  assert.strictEqual(f(PNG1, 'x.png').type, 'image/png', 'png 的 type 空了 —— 拖进去会没反应');
  assert.strictEqual(f(PNG1, 'x.jpg').type, 'image/jpeg');
  assert.strictEqual(f(PNG1, 'a.JPEG').type, 'image/jpeg', '后缀大小写没归一化');
  assert.strictEqual(f(PNG1, 'doc.pdf').type, 'application/pdf');
});

test('认不出的后缀 type 留空（但不炸、仍能造出文件）', (t) => {
  const h = boot(); t.after(() => h.close());
  const file = h.run('b64ToFile')(PNG1, 'x.zzz');
  assert.strictEqual(file.type, '');
  assert.ok(file.size > 0, '文件内容没解出来');
});

test('还原出的字节数正确（不是空文件）', (t) => {
  const h = boot(); t.after(() => h.close());
  const file = h.run('b64ToFile')(PNG1, 'x.png');
  assert.strictEqual(file.size, h.window.atob(PNG1).length, '解码出来的字节数不对');
});

test('没给文件名时兜一个默认名，不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  const file = h.run('b64ToFile')(PNG1, '');
  assert.ok(file.name && file.name.length > 0, '空文件名没兜底');
});
