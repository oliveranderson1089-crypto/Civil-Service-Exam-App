/* AI 助手里选图上传 —— 手机端的「选完图没动静」。
 *
 * 实机反馈：安卓 APK 里在 AI 助手点「相册」，选完图回到应用，什么都没发生。
 * 量出来的账：手机原图 5~10MB，安卓壳默认连的是 Cloudflare 隧道（边缘在洛杉矶），
 * 实测 8.4MB 光上传就 22 秒，服务端识别再要 20~30 秒 —— 而这条路当时
 *   ① 传的是原图（聊天、小记、云盘早就先压再传，只有它没压）；
 *   ② 请求没有超时（api() 默认不超时），隧道一断这个 fetch 就永远挂着；
 *   ③ 整个过程只有开头一句 toast，附件那一栏一直是空的。
 * 三样凑起来，用户看到的就是「没动静」，只会反复再选一次。
 *
 * 下面三条钉住的就是这三样。测试用不着真跑压缩（jsdom 里没有 canvas，
 * compressImage 会自己退回原图）—— 要钉的是「这条路有没有走压缩、有没有超时、
 * 等待时屏幕上有没有东西」。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const EXTRACT = { name: '题目.jpg', text: '下列句子中', image: 'abc123.jpg', total: 5 };
const bootAi = () => boot({ fetch: (url) => (url.startsWith('/api/ai/extract') ? { json: EXTRACT } : {}) });
const tick = () => new Promise(r => setTimeout(r, 0));
const photo = (mb) => `new File([new Uint8Array(${Math.round(mb * 1024 * 1024)})], '照片.jpg', { type: 'image/jpeg' })`;

test('选的图先在本地压过再传，不把手机原图整个丢上隧道', async (t) => {
  const h = bootAi(); t.after(() => h.close());
  // 压缩本身有 notes.js 那边的测试管；这里只看「有没有把图交给它」和交的档位
  h.run(`compressImage = async (f, side, q) => { window.__cz = { side: side, q: q, from: f.size };
           return new Blob([new Uint8Array(200 * 1024)], { type: 'image/jpeg' }); };`);
  h.run(`aiHandleAttach(${photo(8)})`);
  for (let i = 0; i < 6; i++) await tick();

  const cz = h.plain('window.__cz');
  assert.ok(cz, '根本没压：原图直接上传了');
  assert.strictEqual(cz.from, 8 * 1024 * 1024);
  assert.ok(cz.side <= 2400 && cz.side >= 1600, '缩到 ' + cz.side + 'px：太大省不出传输，太小 OCR 认不清');

  const c = h.calls.find(x => x.url === '/api/ai/extract');
  assert.ok(c, '没发上传请求');
  assert.strictEqual(c.body.get('file').size, 200 * 1024, '传上去的还是原图那份');
});

test('上传请求带超时 —— 没有它，隧道一断就永远转，连报错都等不到', async (t) => {
  const h = bootAi(); t.after(() => h.close());
  // 看的是 api() 真把超时兑现成了 fetch 的 signal（光传个 timeoutMs 字段不算数）
  const seen = [];
  h.window.fetch = (u, o) => { seen.push({ url: String(u), abortable: !!(o && o.signal) }); return new Promise(() => {}); };
  h.run(`aiHandleAttach(${photo(1)})`);
  for (let i = 0; i < 6; i++) await tick();

  const c = seen.find(x => x.url === '/api/ai/extract');
  assert.ok(c, '没发上传请求');
  assert.ok(c.abortable, '上传没设超时：隧道断了这个请求会一直挂着');
});

test('选完图立刻占住位子：等的这几十秒里，屏幕上得看得见东西', async (t) => {
  const h = bootAi(); t.after(() => h.close());
  h.window.fetch = () => new Promise(() => {});      // 传得很慢/卡住的那一路
  h.run(`aiHandleAttach(${photo(1)})`);
  for (let i = 0; i < 6; i++) await tick();

  const busy = h.window.document.querySelector('#ai-atts .ai-att.busy');
  assert.ok(busy, '附件那栏还是空的 —— 这就是「选完图没动静」');
  assert.match(busy.textContent, /读取中/);
  assert.ok(h.window.document.querySelector('#ai-atts').classList.contains('on'), '那一栏没显示出来');
});

test('还在读取的那份不许跟着发出去（发出去 AI 收到的是个空壳）', async (t) => {
  const h = bootAi(); t.after(() => h.close());
  h.window.fetch = () => new Promise(() => {});
  h.run(`aiHandleAttach(${photo(1)})`);
  for (let i = 0; i < 6; i++) await tick();

  const before = h.calls.length;
  h.run(`$('#ai-text').value = '看看这道题'`);
  h.run('aiSend()');
  for (let i = 0; i < 4; i++) await tick();

  assert.strictEqual(h.calls.length, before, '把没读完的附件发出去了');
  assert.match(h.toasts.map(x => x.msg).join('|'), /还在读取/, '拦下了却不说一声，用户只会以为发送键坏了');
});
