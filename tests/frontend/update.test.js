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

/* ---- 桌面版更新检查：两个电脑端各拿各的包 ----
   Linux 壳读 deb_*、Windows 壳读 win_*，服务端两套字段并存（老 Linux 壳只认 deb_*，
   改名会让所有已装的客户端再也收不到更新提示）。挑错一边的后果很实在：
   Windows 用户会被提示去下一个装不上的 .deb。 */
const VER_API = {
  sw: 'gongkao-v221',
  deb_available: true, deb_code: 52, deb_name: '5.2', deb_notes: 'Linux 那版的说明',
  deb_size: 1119988, deb_url: '/download/gongkao.deb',
  win_available: true, win_code: 60, win_name: '6.0', win_notes: 'Windows 那版的说明',
  win_size: 90000000, win_url: '/download/gongkao-setup.exe',
};
const bootShell = (plat) => boot({
  window: { __desktop: true, __desktopVer: '5.1', __desktopPlat: plat },
  fetch: (url) => (url.includes('/api/desktop/version') ? { json: VER_API } : {}),
});

test('Windows 壳拿 win_* 那一套（不是 deb）', async (t) => {
  const h = bootShell('win'); t.after(() => h.close());
  h.run(`lsDel('skipUpdate')`);
  await h.run(`checkDesktopUpdate(true)`);
  assert.strictEqual(D(h).querySelector('#upd-ver').textContent, 'v6.0', 'Windows 壳没拿 win_* 的版本号');
  assert.ok(D(h).querySelector('#upd-notes').textContent.includes('Windows 那版的说明'),
    '更新说明串到 Linux 那套去了');
});

test('Linux 壳照旧拿 deb_*（没有 __desktopPlat 也要认）', async (t) => {
  const h = bootShell(undefined); t.after(() => h.close());
  h.run(`lsDel('skipUpdate')`);
  await h.run(`checkDesktopUpdate(true)`);
  assert.strictEqual(D(h).querySelector('#upd-ver').textContent, 'v5.2', '老 Linux 壳的更新提示被改坏了');
});

test('「以后再说」的跳过标记按平台分开记', async (t) => {
  const h = bootShell('win'); t.after(() => h.close());
  h.run(`lsDel('skipUpdate')`);
  await h.run(`checkDesktopUpdate(true)`);
  D(h).querySelector('#upd-later').click();
  assert.strictEqual(h.run(`lsGet('skipUpdate')`), 'win60',
    '跳过标记没带平台，Windows 上说过「以后再说」会把 Linux 的更新也压掉');
});
