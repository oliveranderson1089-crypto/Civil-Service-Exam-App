/* 云盘：多选下载 + 省流上传。
 *
 * 这两条都是「用户在界面上点得到、但代码里很容易悄悄坏掉」的路：
 * 下载按钮拼错一个字就下回来一个 404 页面；省流那条一旦抛异常没兜住，
 * 就变成「开了省流反而传不上去」。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

// 预检（check=1）的假回应：多选下载会先问一句「这一包多大」
const CHECK = { json: { files: 4, size: 13886406 } };
const withCheck = (extra) => ({
  fetch: (url) => (url.includes('check=1') ? CHECK : (extra ? extra(url) : {})),
});
const tick = () => new Promise(r => setTimeout(r, 0));

// 把列表渲染出来：批量下载要靠 DOM 认「这一项是不是文件夹」
function fill(h, items) {
  h.run('dvGrid = false; dvQuery = ""');
  h.window.document.getElementById('dv-list').innerHTML =
    items.map(it => h.run('dvRow')(it)).join('');
}

function catchDl(h) {
  h.window.__dl = [];
  h.run('dvDownload = (u, n) => window.__dl.push([u, n])');
  return h.window.__dl;
}

test('批量下载：多选打成一个 zip', async (t) => {
  const h = boot(withCheck()); t.after(() => h.close());
  fill(h, [{ id: 1, is_dir: false, name: 'a.jpg', ext: '.jpg', size: 9 },
           { id: 2, is_dir: true, name: '材料' }]);
  const dl = catchDl(h);
  h.run('dvSel.clear(); dvSel.add(1); dvSel.add(2)');
  h.window.document.getElementById('dv-bdl').click();
  await tick();
  assert.strictEqual(dl.length, 1);
  assert.strictEqual(dl[0][0], '/api/drive/zip?ids=1,2');
  // 打包要好几秒，得先说一声这一包多大 —— 否则用户以为按钮坏了，连点好几下
  assert.match(h.toasts.map(x => x.msg).join(' '), /正在打包 4 个文件（13\.2 MB）/);
});

test('批量下载：预检说不行（超限 / 文件没了）就当场讲清楚，不再去点那个下不动的链接', async (t) => {
  const h = boot({ fetch: () => ({ status: 413, json: { error: '选中的内容太大（3000 MB），超过打包上限 2048 MB' } }) });
  t.after(() => h.close());
  fill(h, [{ id: 1, is_dir: true, name: '大目录' }, { id: 2, is_dir: true, name: '也很大' }]);
  const dl = catchDl(h);
  h.run('dvSel.clear(); dvSel.add(1); dvSel.add(2)');
  h.window.document.getElementById('dv-bdl').click();
  await tick();
  assert.strictEqual(dl.length, 0, '下不了就别下 —— 点 <a download> 碰上 JSON 错误是静默不动的');
  const last = h.toasts[h.toasts.length - 1];
  assert.ok(last.err && /超过打包上限/.test(last.msg), '错误原因要原样端到用户面前');
});

test('批量下载：只选一个文件就下原文件，不套一层 zip', (t) => {
  const h = boot(); t.after(() => h.close());
  fill(h, [{ id: 7, is_dir: false, name: '毕业证.jpg', ext: '.jpg', size: 9 }]);
  const dl = catchDl(h);
  h.run('dvSel.clear(); dvSel.add(7)');
  h.window.document.getElementById('dv-bdl').click();
  assert.deepStrictEqual([dl[0][0], dl[0][1]], ['/api/drive/7/download', '毕业证.jpg']);
});

test('批量下载：只选一个文件夹仍然要打包（/download 只认文件）', async (t) => {
  const h = boot(withCheck()); t.after(() => h.close());
  fill(h, [{ id: 3, is_dir: true, name: '证件' }]);
  const dl = catchDl(h);
  h.run('dvSel.clear(); dvSel.add(3)');
  h.window.document.getElementById('dv-bdl').click();
  await tick();
  assert.strictEqual(dl[0][0], '/api/drive/zip?ids=3');
});

test('批量下载：一项都没选就什么都不发生', (t) => {
  const h = boot(withCheck()); t.after(() => h.close());
  const dl = catchDl(h);
  h.run('dvSel.clear()');
  h.window.document.getElementById('dv-bdl').click();
  assert.strictEqual(dl.length, 0);
});

test('省流开关：默认是关的，图片原样上传', async (t) => {
  const h = boot(); t.after(() => h.close());
  const f = new h.window.File([new Uint8Array(2 * 1024 * 1024)], '证件.jpg', { type: 'image/jpeg' });
  const out = await h.run('dvShrink')(f);
  assert.strictEqual(out, f, '默认必须原图 —— 证件照压了就白拍了');
  assert.match(h.window.document.getElementById('dv-slim').textContent, /关$/);
});

test('省流开着：图片缩小，名字跟着变成 .jpg', async (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('lsSet("dv:slim", "1")');
  h.window.createImageBitmap = async () => ({ width: 4000, height: 3000, close() {} });
  h.window.HTMLCanvasElement.prototype.getContext = () => ({ drawImage() {} });
  h.window.HTMLCanvasElement.prototype.toBlob = function (cb) {
    cb(new h.window.Blob([new Uint8Array(200 * 1024)], { type: 'image/jpeg' }));
  };
  const f = new h.window.File([new Uint8Array(3 * 1024 * 1024)], '截图.png', { type: 'image/png' });
  const out = await h.run('dvShrink')(f);
  assert.notStrictEqual(out, f);
  assert.strictEqual(out.name, '截图.jpg', '出的是 JPEG，名字不能还挂着 .png');
  assert.ok(out.size < f.size);
});

test('省流开着但压不动（解不出 HEIC 之类）：照样传原文件', async (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('lsSet("dv:slim", "1")');
  h.window.createImageBitmap = async () => { throw new Error('unsupported'); };
  const f = new h.window.File([new Uint8Array(3 * 1024 * 1024)], '照片.jpg', { type: 'image/jpeg' });
  assert.strictEqual(await h.run('dvShrink')(f), f, '省流是锦上添花，不能把「传得上去」搞没了');
});

test('省流开着：小图和非图片不碰', async (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('lsSet("dv:slim", "1")');
  h.window.createImageBitmap = async () => { throw new Error('不该被调到'); };
  const small = new h.window.File([new Uint8Array(100 * 1024)], '小.jpg', { type: 'image/jpeg' });
  const pdf = new h.window.File([new Uint8Array(3 * 1024 * 1024)], '讲义.pdf', { type: 'application/pdf' });
  assert.strictEqual(await h.run('dvShrink')(small), small);
  assert.strictEqual(await h.run('dvShrink')(pdf), pdf);
});

test('分片并发：乱序完成也要每片都送到，且进度报满', async (t) => {
  const seen = [];
  const h = boot({
    fetch: (url) => {
      const m = /\/api\/drive\/chunk\/([a-z0-9]+)\/(\d+)$/.exec(url);
      if (m) seen.push(+m[2]);
      if (url.endsWith('/init')) return { json: { upload_id: 'a'.repeat(32), received: [] } };
      return { json: { ok: true } };
    },
  });
  t.after(() => h.close());
  const size = 9 * 1024 * 1024 + 7;
  const big = new h.window.File([new Uint8Array(size)], 'big.bin');
  let last = 0;
  await h.run('dvUploadChunked')(big, '', n => { last = n; });
  assert.deepStrictEqual(seen.slice().sort((a, b) => a - b), [0, 1, 2], '三片一片都不能漏');
  assert.strictEqual(last, size, '进度分母是文件大小，最后必须正好报满');
});

/* ---- 下载得有回音 ----
   用户的原话：「点击了下载但是没有反应，也没有显示是否下载成功，下载到哪里也不知道」。
   文件其实下下来了（~/下载/云盘4项.zip），坏的是从头到尾没人说一句话。 */

test('浏览器里点下载：至少要说一声「开始了，去下载列表看」', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('dvDownload')('/api/drive/7/download', '毕业证.jpg');
  assert.match(h.toasts.map(x => x.msg).join(' '), /已开始下载：毕业证\.jpg/);
});

test('桌面壳里不抢着说：它下完会回调 __onDownloaded，那时才说得出存到哪', (t) => {
  const h = boot({ window: { __desktop: true, __desktopVer: '5.2' } });
  t.after(() => h.close());
  h.run('dvDownload')('/api/drive/7/download', '毕业证.jpg');
  assert.strictEqual(h.toasts.length, 0);
});

test('下载完成：普通文件也报平安，并且说清楚存到哪了', (t) => {
  const h = boot(); t.after(() => h.close());
  h.window.__onDownloaded('/home/me/下载/云盘4项.zip');
  const msg = h.toasts.map(x => x.msg).join(' ');
  assert.match(msg, /云盘4项\.zip/);
  assert.match(msg, /\/home\/me\/下载/, '路径必须出现 —— 「下载到哪里也不知道」就是栽在这儿');
});

test('新壳（5.2+）：下完给「打开文件夹」，点了才发 reveal', (t) => {
  const h = boot({ window: { __desktop: true, __desktopVer: '5.2' } });
  t.after(() => h.close());
  const sent = [];
  h.window.webkit = { messageHandlers: { gk: { postMessage: (s) => sent.push(JSON.parse(s)) } } };
  h.window.__onDownloaded('/home/me/下载/云盘4项.zip');
  const doc = h.window.document;
  assert.ok(!doc.getElementById('app-dialog').classList.contains('hidden'), '该弹的是应用内对话框');
  assert.strictEqual(doc.getElementById('ad-ok').textContent, '打开文件夹');
  assert.strictEqual(doc.getElementById('ad-cancel').textContent, '知道了');
  doc.getElementById('ad-ok').click();
  return new Promise(r => setTimeout(() => {
    assert.deepStrictEqual(sent, [{ a: 'reveal', path: '/home/me/下载/云盘4项.zip' }]);
    r();
  }, 0));
});

test('老壳（5.1）：不给点了没反应的按钮，退回一句话', (t) => {
  const h = boot({ window: { __desktop: true, __desktopVer: '5.1' } });
  t.after(() => h.close());
  h.window.__onDownloaded('/home/me/下载/云盘4项.zip');
  assert.ok(h.window.document.getElementById('app-dialog').classList.contains('hidden'));
  assert.match(h.toasts.map(x => x.msg).join(' '), /云盘4项\.zip/);
});

test('更新包还是走原来那套安装说明，别被「报平安」抢走', (t) => {
  const h = boot({ window: { __desktop: true, __desktopVer: '5.2' } });
  t.after(() => h.close());
  h.window.__onDownloaded('/home/me/下载/gongkao_5.2_amd64.deb');
  assert.match(h.window.document.getElementById('ad-msg').textContent, /dpkg -i/);
});
