/* 更新提示弹窗 updModal。
 *
 * update 改动 1 次、零测试。updModal 把新版本信息填进弹窗，两个按钮：「立即更新」调
 * onGo，「以后再说」把这一版记进 skipUpdate（同一版别再反复弹）。三端（安卓/桌面/网页）
 * 共用这一个弹窗，逻辑错了要么该更新的不提示、要么烦人地反复弹。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const D = (h) => h.window.document;

test('填入版本信息、显示弹窗', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`updModal({ title: '发现新版本', ver: 'v2.1', notes: '修了几个bug', size: '12MB', btn: '立即更新', key: 'apk21', onGo: () => {} })`);
  assert.strictEqual(D(h).querySelector('#upd-title').textContent, '发现新版本');
  assert.strictEqual(D(h).querySelector('#upd-ver').textContent, 'v2.1');
  assert.ok(!D(h).querySelector('#upd-modal').classList.contains('hidden'), '弹窗没显示出来');
});

test('「立即更新」调 onGo 并关弹窗', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`window.__went = false; updModal({ title: 't', notes: 'n', btn: '更新', onGo: () => { window.__went = true; } })`);
  D(h).querySelector('#upd-go').click();
  assert.strictEqual(h.window.__went, true, '点「立即更新」没调 onGo');
  assert.ok(D(h).querySelector('#upd-modal').classList.contains('hidden'), '点了更新弹窗没关');
});

test('「以后再说」把这一版记进 skipUpdate（别再反复弹）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`lsDel('skipUpdate'); updModal({ title: 't', notes: 'n', btn: '更新', key: 'apk99', onGo: () => {} })`);
  D(h).querySelector('#upd-later').click();
  assert.strictEqual(h.run(`lsGet('skipUpdate')`), 'apk99', '「以后再说」没记住版本，下次还弹');
  assert.ok(D(h).querySelector('#upd-modal').classList.contains('hidden'));
});

test('没给 key 时「以后再说」不写 skipUpdate（比如网页版强提示）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`lsDel('skipUpdate'); updModal({ title: 't', notes: 'n', btn: '刷新', onGo: () => {} })`);
  D(h).querySelector('#upd-later').click();
  assert.strictEqual(h.run(`lsGet('skipUpdate')`), null, '没 key 却写了 skipUpdate');
});
