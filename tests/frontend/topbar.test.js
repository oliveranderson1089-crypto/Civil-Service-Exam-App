/* 顶栏工具：着重标注 emKey + 文档标题判定 isDocHeading。
 *
 * topbar 改动 2 次、零测试。emKey 把书名号/引号/括注、以及「N个XX」这类词组自动加粗，
 * 用在标题栏等处 —— 先转义再加 <b>，不能因为要加粗就把用户文本当 HTML。
 * isDocHeading 判断一行是不是公文层级标题（第X章 / 一、/（一）/ 1.），排版时用。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('emKey：书名号/引号/括注 自动加粗', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('emKey');
  assert.match(f('学习《决定》精神'), /<b>《决定》<\/b>/);
  assert.match(f('“绿水青山”理念'), /<b>“绿水青山”<\/b>/);
  assert.match(f('落实【重点】任务'), /<b>【重点】<\/b>/);
});

test('emKey：「N个XX」词组加粗', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.match(h.run('emKey')('两个维护、四个意识'), /<b>两个维护<\/b>/);
});

test('emKey：先转义再加粗，HTML 进不了 DOM', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = h.window.document.createElement('div');
  box.innerHTML = h.run('emKey')('<img src=x onerror=alert(1)>《正常》');
  assert.strictEqual(box.querySelector('img'), null, 'emKey 把用户文本当 HTML 了');
  assert.ok(box.querySelector('b'), '书名号该加粗');   // 加粗功能仍在
});

test('emKey：换行转成 <br>', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.match(h.run('emKey')('第一行\n第二行'), /第一行<br>第二行/);
});

test('isDocHeading：认得公文层级标题，普通句子不算', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('isDocHeading');
  for (const s of ['第一章 总则', '一、指导思想', '（三）主要目标', '1. 提高认识', '2、加强领导']) {
    assert.strictEqual(f(s), true, `「${s}」该被认成标题`);
  }
  for (const s of ['这是正文段落。', '依法治国是重要方略', '他说了三点意见']) {
    assert.strictEqual(f(s), false, `「${s}」不该被当成标题`);
  }
});
