/* 语音：气泡渲染 + 「能不能录」的判断 + 转文字的降级路径。
 *
 * 录音本身在 jsdom 里跑不了（没有真麦克风），但**判断能不能录**、以及不能录时给的
 * 那句话，恰恰是这块最容易出错的地方：局域网 http 直连、桌面壳、老 WebView 各缺一样，
 * 提示说错了用户就不知道该去改什么。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('语音气泡：时长和播放地址都在，长的条更宽', (t) => {
  const h = boot(); t.after(() => h.close());
  const html = h.run('voiceBubbleHtml')({ id: 7, file_id: 42, dur: 8.2, text: '' });
  assert.match(html, /data-voice="7"/);
  assert.match(html, /\/api\/chat\/file\/42\?inline=1/);
  assert.match(html, /8″/);
  const wide = h.run('voiceBubbleHtml')({ id: 8, file_id: 43, dur: 30, text: '' });
  const pct = (s) => +s.match(/width:([\d.]+)%/)[1];
  assert.ok(pct(wide) > pct(html), '30 秒的条应该比 8 秒的宽');
});

test('转出来的文字挂在语音条下面，且经过转义', (t) => {
  const h = boot(); t.after(() => h.close());
  const html = h.run('voiceBubbleHtml')({ id: 9, file_id: 1, dur: 3, text: '<img src=x onerror=1>' });
  const box = h.window.document.createElement('div'); box.innerHTML = html;
  assert.ok(box.querySelector('.cr-vtext'), '转写文字要单独一行');
  assert.strictEqual(box.querySelector('img'), null, '转写文字没转义，被注入了');
});

test('时长显示：不到一分钟用「秒」，超过用 m:ss', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('voiceFmt');
  assert.strictEqual(f(0), '0″');
  assert.strictEqual(f(8.4), '8″');
  assert.strictEqual(f(75), '1:15');
  assert.strictEqual(f(600), '10:00');
});

test('没有 MediaRecorder 就是不能录，且说得出缺什么', (t) => {
  const h = boot(); t.after(() => h.close());       // jsdom 本来就没有 MediaRecorder
  assert.strictEqual(h.run('voiceSupported')(), false);
  assert.match(h.run('voiceWhyNot')(), /录音|麦克风|不支持/);
});

test('http 局域网直连：提示要说到「https / localhost」，别只说失败', (t) => {
  // 真实场景：手机浏览器直连 192.168.x.x:8011，浏览器压根不给 mediaDevices
  const h = boot({ url: 'http://192.168.1.5:8011/' }); t.after(() => h.close());
  Object.defineProperty(h.window, 'isSecureContext', { value: false, configurable: true });
  assert.match(h.run('voiceWhyNot')(), /https/, '没告诉用户该怎么办');
});

test('识别开没开只问一次服务端，答案记住不重复问', async (t) => {
  const h = boot({ fetch: (u) => (u.includes('/api/asr/status') ? { json: { enabled: true } } : {}) });
  t.after(() => h.close());
  assert.strictEqual(await h.run('voiceAsrEnabled')(), true);
  assert.strictEqual(await h.run('voiceAsrEnabled')(), true);
  const n = h.calls.filter(c => c.url.includes('/api/asr/status')).length;
  assert.strictEqual(n, 1, '状态问了 ' + n + ' 次，应该只问一次');
});

test('启动时不去问识别状态 —— 为一颗按钮先打一趟接口不值当', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.strictEqual(h.calls.filter(c => c.url.includes('/api/asr')).length, 0);
});

test('转文字失败要把原文抛出来，好让界面照原话提示', async (t) => {
  const h = boot({ fetch: () => ({ status: 503, json: { error: '语音转文字还没开启' } }) });
  t.after(() => h.close());
  await assert.rejects(() => h.run('voiceToText')(new h.window.Blob(['x']), '.webm'),
                       /语音转文字还没开启/);
});

test('权限被拒：壳里弹窗劝去设置，点确定就跳系统权限页', async (t) => {
  let opened = 0;
  const h = boot({ window: { GongkaoNative: { openAppSettings: () => { opened++; } } } });
  t.after(() => h.close());
  // jsdom 没有 getUserMedia，补一个「用户点了拒绝」的
  h.window.navigator.mediaDevices = { getUserMedia: async () => { const e = new Error('denied'); e.name = 'NotAllowedError'; throw e; } };
  h.window.MediaRecorder = function () {};
  h.window.MediaRecorder.isTypeSupported = () => true;
  // 弹窗默认停在那儿等人点，这里替成「点了确定」
  h.run('appConfirm = async () => true');
  assert.strictEqual(await h.run('voiceRecord')(), null, '被拒时不该返回录音');
  assert.strictEqual(opened, 1, '没跳到系统权限页');
});

test('普通浏览器里没有壳可跳，退回文字提示', async (t) => {
  const h = boot(); t.after(() => h.close());
  h.window.navigator.mediaDevices = { getUserMedia: async () => { const e = new Error('denied'); e.name = 'NotAllowedError'; throw e; } };
  h.window.MediaRecorder = function () {};
  h.window.MediaRecorder.isTypeSupported = () => true;
  assert.strictEqual(await h.run('voiceRecord')(), null);
  assert.match(h.toasts.map(x => x.msg).join(' '), /麦克风权限/);
});

/* 「设备打不开」这一类：外壳实测的结论决定给哪句话。三种结论三条路，
   走错一条用户就会去做完全没用的事（比如去关根本没开的录音机）。 */
function bootDeviceBusy(t, native) {
  const h = boot(native ? { window: { GongkaoNative: native } } : undefined);
  t.after(() => h.close());
  let tries = 0;
  h.window.navigator.mediaDevices = {
    getUserMedia: async () => { tries++; const e = new Error('busy'); e.name = 'NotReadableError'; throw e; },
  };
  h.window.MediaRecorder = function () {};
  h.window.MediaRecorder.isTypeSupported = () => true;
  h.tries = () => tries;
  return h;
}

test('设备打不开先自动重试一次（WebView 上换个几百毫秒就好了）', async (t) => {
  const h = bootDeviceBusy(t);
  assert.strictEqual(await h.run('voiceRecord')(), null);
  assert.strictEqual(h.tries(), 2, '应该试两次');
});

test('外壳实测「系统能录」→ 让人重开应用，别去关别的应用', async (t) => {
  const h = bootDeviceBusy(t, { openAppSettings() {}, micProbe: () => 'ok' });
  await h.run('voiceRecord')();
  const msg = h.toasts.map(x => x.msg).join(' ');
  assert.match(msg, /完全退出/);
  assert.match(msg, /NotReadableError/, '原始错误名要带上，不然下次还是只能猜');
});

test('外壳实测「真被占用」→ 才说去关别的应用', async (t) => {
  const h = bootDeviceBusy(t, { openAppSettings() {}, micProbe: () => 'busy' });
  await h.run('voiceRecord')();
  assert.match(h.toasts.map(x => x.msg).join(' '), /被别的应用占着/);
});

test('外壳实测「权限其实没给」→ 走去设置那条路，不是提示占用', async (t) => {
  let opened = 0;
  const h = bootDeviceBusy(t, { openAppSettings: () => { opened++; }, micProbe: () => 'denied' });
  h.run('appConfirm = async () => true');
  await h.run('voiceRecord')();
  assert.strictEqual(opened, 1);
  assert.doesNotMatch(h.toasts.map(x => x.msg).join(' '), /占着/);
});
