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

test('fSize：GB 档 —— 配额是 GB 量级，别显示成「2048.0 MB」', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('fSize');
  assert.strictEqual(f(1073741823), '1024.0 MB', '差一字节到 1GB，还是 MB');
  assert.strictEqual(f(1073741824), '1.0 GB');
  assert.strictEqual(f(2 * 1073741824), '2.0 GB');
});

/* 拖拽上传的目录展开。这是本次改动里最容易悄悄错的一块：
   readEntries 一次最多给 100 条、要一直读到空数组才算完，漏了就只传前 100 个；
   路径要按层往下拼，拼错了文件会散落到别的目录去。两种错都不报错、只是传丢。 */
const fakeFile = (name) => ({
  isFile: true, isDirectory: false, name,
  file: (cb) => cb({ name, size: 1 }),
});
// batches: 二维数组，模拟 readEntries 分批返回，最后自动补一个空批表示读完
const fakeDir = (name, batches) => ({
  isFile: false, isDirectory: true, name,
  createReader: () => {
    let i = 0;
    return { readEntries: (cb) => cb(i < batches.length ? batches[i++] : []) };
  },
});

test('dvWalkEntry：目录树摊平成 {file, folder}，路径按层拼', async (t) => {
  const h = boot(); t.after(() => h.close());
  const walk = h.run('dvWalkEntry');
  // 照片/ ├ a.jpg  └ 2024/ └ b.jpg
  const tree = fakeDir('照片', [[fakeFile('a.jpg'), fakeDir('2024', [[fakeFile('b.jpg')]])]]);
  const out = [];
  await walk(tree, '', out);
  assert.deepStrictEqual(out.map(x => x.folder + '/' + x.file.name).sort(),
    ['照片/2024/b.jpg', '照片/a.jpg']);
});

test('dvWalkEntry：顶层散文件落在当前目录（folder 为空）', async (t) => {
  const h = boot(); t.after(() => h.close());
  const out = [];
  await h.run('dvWalkEntry')(fakeFile('单个.txt'), '', out);
  assert.deepStrictEqual(out.map(x => [x.folder, x.file.name]), [['', '单个.txt']]);
});

test('dvWalkEntry：目录分批返回要读全 —— 只读第一批就会传丢', async (t) => {
  const h = boot(); t.after(() => h.close());
  const b1 = Array.from({ length: 100 }, (_, i) => fakeFile('a' + i));
  const b2 = Array.from({ length: 37 }, (_, i) => fakeFile('b' + i));
  const out = [];
  await h.run('dvWalkEntry')(fakeDir('多', [b1, b2]), '', out);
  assert.strictEqual(out.length, 137, '分批没读全，后面那批文件传丢了');
  assert.ok(out.every(x => x.folder === '多'));
});

test('dvUpload：当前目录 + 相对子路径 = 目标目录（拼错文件就散到别处去了）', async (t) => {
  const h = boot(); t.after(() => h.close());
  const sent = [];
  h.window.XMLHttpRequest = function () {
    this.upload = {};
    this.open = () => {};
    this.send = (fd) => {
      sent.push(fd.get('folder'));
      this.status = 201; this.responseText = '{}';
      setTimeout(() => this.onload(), 0);
    };
  };
  h.run('dvFolder = "工作"');          // 用户当前正站在「工作」目录里
  const mk = (n) => new h.window.File(['x'], n);
  await h.run('dvUpload')([
    { file: mk('a.txt'), folder: '' },              // 散文件 → 就放当前目录
    { file: mk('b.jpg'), folder: '照片/2024' },      // 来自文件夹 → 拼到当前目录下面
  ]);
  assert.deepStrictEqual(sent.sort(), ['工作', '工作/照片/2024']);
});

test('dvUpload：根目录下上传，目标就是相对路径本身（不带前导斜杠）', async (t) => {
  const h = boot(); t.after(() => h.close());
  const sent = [];
  h.window.XMLHttpRequest = function () {
    this.upload = {};
    this.open = () => {};
    this.send = (fd) => {
      sent.push(fd.get('folder'));
      this.status = 201; this.responseText = '{}';
      setTimeout(() => this.onload(), 0);
    };
  };
  h.run('dvFolder = ""');
  await h.run('dvUpload')([{ file: new h.window.File(['x'], 'b.jpg'), folder: '照片/2024' }]);
  assert.deepStrictEqual(sent, ['照片/2024'], '根目录下不该拼出 "/照片/2024"');
});

/* 列表行渲染。搜索是全盘的，结果里的东西不在当前目录 —— 路径若还按当前目录拼，
   点进去就是个不存在的地方（空文件夹），而且不报错。 */
test('dvRow：搜索结果里的文件夹，路径按它自己的 folder 拼，不是当前目录', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('dvFolder = "我正站着的目录"; dvQuery = "找"');
  const html = h.run('dvRow')({ id: 7, is_dir: true, name: '孙', folder: '甲/乙' });
  assert.match(html, /data-dvopen="甲\/乙\/孙"/);
  assert.ok(!html.includes('我正站着的目录'), '用当前目录拼路径了，点进去会是空的');
});

test('dvRow：搜索时把文件所在目录显示出来', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('dvQuery = "找"');
  const html = h.run('dvRow')({ id: 1, is_dir: false, name: 'a.txt', ext: '.txt', size: 1, folder: '深/处' });
  assert.match(html, /深\/处/, '搜出来不说在哪个目录，等于搜了也找不着');
});

test('dvRow：只有能预览的文件才挂预览钩子', (t) => {
  const h = boot(); t.after(() => h.close());
  const yes = h.run('dvRow')({ id: 1, is_dir: false, name: 'a.png', ext: '.png', size: 1, viewable: true });
  const no = h.run('dvRow')({ id: 2, is_dir: false, name: 'b.apk', ext: '.apk', size: 1, viewable: false });
  assert.match(yes, /data-dvview="1"/);
  assert.ok(!/data-dvview/.test(no), '不能预览的也挂了钩子，点下去只会拿到 415');
});

test('dvRow：文件名里的 HTML 当文字，不进 DOM', (t) => {
  const h = boot(); t.after(() => h.close());
  const html = h.run('dvRow')({ id: 1, is_dir: false, name: '<img onerror=x>.txt', ext: '.txt', size: 1 });
  assert.ok(!html.includes('<img'), '文件名没转义，上传个带标签的名字就能注入');
});

/* 秒传与分片。两条都容易「看着传成功了、其实内容不对」，所以盯的是发出去的请求序列。 */
// window.crypto 在 jsdom 里是只读 getter，只能 defineProperty 覆盖
function setCrypto(h, value) {
  Object.defineProperty(h.window, 'crypto', { configurable: true, value });
}
function stubFetch(h, calls, resp) {
  h.window.fetch = async (url, o) => {
    const u = String(url);
    calls.push(u);
    return { status: 201, ok: true, headers: { get: () => 'application/json' },
             json: async () => (resp(u, o) || {}) };
  };
}

test('dvUploadOne：秒传命中后就不再传内容了', async (t) => {
  const h = boot(); t.after(() => h.close());
  setCrypto(h, { subtle: { digest: async () => new ArrayBuffer(32) } });
  const calls = [];
  stubFetch(h, calls, u => (u.includes('/instant') ? { hit: true, id: 9 } : {}));
  await h.run('dvUploadOne')(new h.window.File(['abc'], 'a.txt'), '', () => {});
  assert.ok(calls.some(u => u.includes('/api/drive/instant')), '压根没问秒传');
  assert.ok(!calls.some(u => u.includes('/chunk/')), '秒传命中了还走了分片');
});

test('dvUploadOne：秒传没命中就照常传', async (t) => {
  const h = boot(); t.after(() => h.close());
  setCrypto(h, { subtle: { digest: async () => new ArrayBuffer(32) } });
  const calls = [];
  stubFetch(h, calls, () => ({ hit: false }));
  let sent = 0;
  h.window.XMLHttpRequest = function () {
    this.upload = {}; this.open = () => {};
    this.send = () => { sent++; this.status = 201; this.responseText = '{}';
                        setTimeout(() => this.onload(), 0); };
  };
  await h.run('dvUploadOne')(new h.window.File(['abc'], 'a.txt'), '', () => {});
  assert.strictEqual(sent, 1, '秒传没命中，就得老老实实把内容传上去');
});

test('dvSha256：拿不到 crypto.subtle 时返回 null（http 访问下要能退回正常上传）', async (t) => {
  const h = boot(); t.after(() => h.close());
  setCrypto(h, undefined);             // 局域网 http 访问时就是这样
  const got = await h.run('dvSha256')(new h.window.File(['abc'], 'a.txt'));
  assert.strictEqual(got, null, '这里不返回 null 的话，非 https 下会连传都传不了');
});

test('dvUploadChunked：按 4MB 切块，跑完再 done', async (t) => {
  const h = boot(); t.after(() => h.close());
  const calls = [];
  stubFetch(h, calls, u => (u.includes('/chunk/init')
    ? { upload_id: 'a'.repeat(32), received: [] } : {}));
  const big = new h.window.File([new Uint8Array(9 * 1024 * 1024)], 'big.bin');
  await h.run('dvUploadChunked')(big, '照片', () => {});
  const puts = calls.filter(u => /\/chunk\/a+\/\d+$/.test(u));
  assert.strictEqual(puts.length, 3, '9MB 该切成 3 块（4+4+1），实际 ' + puts.length);
  assert.ok(calls[calls.length - 1].endsWith('/done'), '最后没调 done，文件不会入库');
});

test('dvUploadChunked：续传时跳过已经收到的块', async (t) => {
  const h = boot(); t.after(() => h.close());
  const calls = [];
  stubFetch(h, calls, u => (u.includes('/chunk/init')
    ? { upload_id: 'b'.repeat(32), received: [0] } : {}));
  const big = new h.window.File([new Uint8Array(9 * 1024 * 1024)], 'big.bin');
  await h.run('dvUploadChunked')(big, '', () => {});
  const puts = calls.filter(u => /\/chunk\/b+\/\d+$/.test(u));
  assert.deepStrictEqual(puts.map(u => u.split('/').pop()), ['1', '2'],
    '第 0 块服务端已经有了，不该再传一遍');
});

test('dvUploadChunked：进度报到文件总大小，不会停在半截', async (t) => {
  const h = boot(); t.after(() => h.close());
  stubFetch(h, [], u => (u.includes('/chunk/init')
    ? { upload_id: 'c'.repeat(32), received: [] } : {}));
  const size = 9 * 1024 * 1024;
  const big = new h.window.File([new Uint8Array(size)], 'big.bin');
  let last = 0;
  await h.run('dvUploadChunked')(big, '', n => { last = n; });
  assert.strictEqual(last, size, '最后一块只有 1MB，进度不能按整块算超或算少');
});

/* 桌面壳（WebKitGTK）的 drop 事件里 dataTransfer.files 是空的，所以拖放由 GTK 层接管，
   最后走 desktop.js 的 __onDropFiles → dvUpload(files)，传的是**一串裸 File**。
   P0 改 dvUpload 入参时漏了这个调用方，桌面版拖拽上传于是静默失效。 */
test('dvUpload：也收一串裸 File（桌面壳就是这么调的）', async (t) => {
  const h = boot(); t.after(() => h.close());
  const sent = [];
  h.window.XMLHttpRequest = function () {
    this.upload = {}; this.open = () => {};
    this.send = (fd) => {
      sent.push(fd.get('file').name);
      this.status = 201; this.responseText = '{}';
      setTimeout(() => this.onload(), 0);
    };
  };
  h.run('dvFolder = "当前目录"');
  await h.run('dvUpload')([new h.window.File(['x'], 'a.pdf'), new h.window.File(['y'], 'b.pdf')]);
  assert.deepStrictEqual(sent.sort(), ['a.pdf', 'b.pdf'],
    '裸 File 被滤掉了 —— 桌面版拖进来的文件会一声不吭地消失');
});

test('dvUpload：单个文件失败不拖垮其余的，并如实报失败数', async (t) => {
  const h = boot(); t.after(() => h.close());
  h.window.XMLHttpRequest = function () {
    this.upload = {};
    this.open = () => {};
    this.send = (fd) => {
      const bad = fd.get('file').name === 'bad.bin';
      this.status = bad ? 400 : 201;
      this.responseText = bad ? '{"error":"云盘空间不足"}' : '{}';
      setTimeout(() => this.onload(), 0);
    };
  };
  const mk = (n) => new h.window.File(['x'], n);
  await h.run('dvUpload')([
    { file: mk('ok1.txt'), folder: '' },
    { file: mk('bad.bin'), folder: '' },
    { file: mk('ok2.txt'), folder: '' },
  ]);
  const msgs = h.toasts.map(x => x.msg);
  assert.ok(msgs.some(m => m.includes('bad.bin') && m.includes('云盘空间不足')),
    '失败的那个要点名报出来，否则用户不知道是哪个没传上：' + JSON.stringify(msgs));
  assert.ok(msgs.some(m => m.includes('2 个') && m.includes('失败 1 个')),
    '汇总要如实：成功 2 个、失败 1 个。实际：' + JSON.stringify(msgs));
});

/* ---- 代码审查查出来的前端坑 ---- */

test('dvMenu：文件夹不给「下载」（/download 只认文件，给了就是点出个 404）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('dvMenu')(10, 10, 7, '某文件夹', false, true);      // isDir = true
  const keys = [...h.window.document.querySelectorAll('#dv-menu [data-dvm]')]
    .map(b => b.dataset.dvm);
  assert.ok(!keys.includes('dvm-dl'), '文件夹给了下载项，点下去会把单页应用冲到 404 页');
  assert.ok(keys.includes('dvm-del') && keys.includes('dvm-copy'));
});

test('dvMenu：文件才给「下载」', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('dvMenu')(10, 10, 8, 'a.pdf', true, false);
  const keys = [...h.window.document.querySelectorAll('#dv-menu [data-dvm]')]
    .map(b => b.dataset.dvm);
  assert.ok(keys.includes('dvm-dl') && keys.includes('dvm-view'));
});

test('openDrive：从回收站回到云盘要退出回收站视图', async (t) => {
  const h = boot(); t.after(() => h.close());
  const calls = [];
  stubFetch(h, calls, () => ({ items: [], used: 0, quota: 100 }));
  h.run('dvInTrash = true');
  h.run('openDrive()');
  assert.strictEqual(h.run('dvInTrash'), false,
    '不复位的话 loadDrive 会短路去 loadTrash —— 云盘打开是回收站，上传完也看不见文件');
  // openDrive 里的 loadDrive 是异步的：不等它落地就 close()，它会在关掉的 jsdom 上继续跑
  await new Promise(r => setTimeout(r, 0));
  await new Promise(r => setTimeout(r, 0));
  assert.ok(calls.some(u => u.includes('/api/drive?')), '走的是列目录，不是回收站');
  assert.ok(!calls.some(u => u.includes('/api/drive/trash')));
});

test('右键菜单放过输入框：搜索框上仍是系统那套文字菜单', (t) => {
  const h = boot(); t.after(() => h.close());
  const w = h.window;
  const fire = (el) => {
    const e = new w.MouseEvent('contextmenu', { bubbles: true, cancelable: true });
    el.dispatchEvent(e);
    return e.defaultPrevented;
  };
  assert.strictEqual(fire(w.document.querySelector('#dv-search')), false,
    '搜索框的右键被吞了，用户粘不了文字');
  assert.strictEqual(fire(w.document.querySelector('#dv-list')), true,
    '列表区的右键应该给我们自己的菜单');
});

test('dvUploadChunked：记住 upload_id，重来时先问服务端收到哪些块', async (t) => {
  const h = boot(); t.after(() => h.close());
  const calls = [];
  // 第一次：init 给会话号，传到一半「断了」
  h.window.fetch = async (url) => {
    const u = String(url); calls.push(u);
    let body = {};
    if (u.includes('/chunk/init')) body = { upload_id: 'd'.repeat(32), received: [] };
    if (/\/chunk\/d+$/.test(u)) body = { received: [0, 1] };     // 续传时服务端说收到 0、1
    return { status: 201, ok: true, headers: { get: () => 'application/json' }, json: async () => body };
  };
  const big = new h.window.File([new Uint8Array(9 * 1024 * 1024)], 'big.bin');
  await h.run('dvUploadChunked')(big, '', () => {});
  const key = h.run('dvUpKey')(big, '');
  assert.strictEqual(h.window.localStorage.getItem(key), null, '传完了该把会话号清掉');

  // 第二次：手动塞回一个会话号，应该先问进度、只补没传的那块
  h.window.localStorage.setItem(key, 'd'.repeat(32));
  calls.length = 0;
  await h.run('dvUploadChunked')(big, '', () => {});
  assert.ok(!calls.some(u => u.includes('/chunk/init')), '有会话号还去重开了新会话，等于没有续传');
  const puts = calls.filter(u => /\/chunk\/d+\/\d+$/.test(u)).map(u => u.split('/').pop());
  assert.deepStrictEqual(puts, ['2'], '第 0、1 块服务端已经有了，只该补第 2 块');
});

/* ---- 网格视图 / 分享链接 ---- */

test('dvRow：网格模式下图片出缩略图，非图片仍是图标', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('dvGrid = true');
  const img = h.run('dvRow')({ id: 3, is_dir: false, name: 'a.png', ext: '.png', size: 1,
                               viewable: true, thumb: true });
  const zip = h.run('dvRow')({ id: 4, is_dir: false, name: 'b.zip', ext: '.zip', size: 1,
                               viewable: false, thumb: false });
  assert.match(img, /src="\/api\/drive\/3\/thumb"/);
  assert.match(img, /loading="lazy"/, '不懒加载的话，一屏几十张图会一次性全下');
  assert.ok(!/dv-thumb/.test(zip), '压缩包不该去请求缩略图（后端只会回 404）');
});

test('dvRow：列表模式下不请求缩略图', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('dvGrid = false');
  const img = h.run('dvRow')({ id: 3, is_dir: false, name: 'a.png', ext: '.png', size: 1,
                               viewable: true, thumb: true });
  assert.ok(!/dv-thumb/.test(img), '列表模式白下一堆缩略图');
});

test('dvShare：拿到链接后复制的是完整地址（发给别人要能直接打开）', async (t) => {
  const h = boot(); t.after(() => h.close());
  const copied = [];
  h.window.navigator.clipboard = { writeText: async (v) => { copied.push(v); } };
  stubFetch(h, [], () => ({ url: '/s/tok123', expires_at: '2026-08-01 12:00:00' }));
  h.run("appPrompt = async () => null");        // 别真弹框
  await h.run('dvShare')(5);
  assert.strictEqual(copied.length, 1);
  assert.ok(copied[0].startsWith('http'), '复制的是相对路径，别人打不开：' + copied[0]);
  assert.ok(copied[0].endsWith('/s/tok123'));
});

/* ---- 一行一个 ⋮ / 排序弹层 / 返回逐级 ---- */

test('dvRow：一行只留一个 ⋮，操作都收进菜单', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('dvGrid = false');
  const html = h.run('dvRow')({ id: 5, is_dir: false, name: 'a.pdf', ext: '.pdf', size: 1,
                                viewable: true, thumb: false });
  assert.match(html, /data-dvmore="5"/);
  const btns = (html.match(/<button|<a /g) || []).length;
  assert.ok(btns <= 2, '一行还铺着 ' + btns + ' 个按钮，手机上点不准也挤没文件名');
});

test('dvMenu：文件夹给「打包下载」，文件给「下载」', (t) => {
  const h = boot(); t.after(() => h.close());
  const keys = (isDir) => {
    h.run('dvMenu')(10, 10, 9, 'x', false, isDir);
    return [...h.window.document.querySelectorAll('#dv-menu [data-dvm]')].map(b => b.dataset.dvm);
  };
  const dir = keys(true), file = keys(false);
  assert.ok(dir.includes('dvm-zip') && !dir.includes('dvm-dl'), '文件夹给了单文件下载');
  assert.ok(file.includes('dvm-dl') && !file.includes('dvm-zip'));
  assert.ok(dir.includes('dvm-share'), '文件夹现在也能分享');
  assert.ok(!dir.includes('dvm-send'), '文件夹发不了给好友（走的是单文件接口）');
});

test('排序：点按钮出自定义弹层，选中后回写标签', (t) => {
  const h = boot(); t.after(() => h.close());
  const w = h.window;
  assert.strictEqual(w.document.querySelector('select#dv-sort'), null, '还留着原生 select');
  w.document.querySelector('#dv-sort').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
  const opts = [...w.document.querySelectorAll('#dv-menu [data-dvsort]')].map(b => b.dataset.dvsort);
  assert.deepStrictEqual(opts, ['new', 'old', 'name', 'big', 'small']);
  h.run('dvSort = "big"; dvSortLabel()');
  assert.strictEqual(w.document.querySelector('#dv-sort-label').textContent, '从大到小');
});

const settle = () => new Promise(r => setTimeout(r, 0)).then(() => new Promise(r => setTimeout(r, 0)));

test('dvGo：进目录压一层栈，返回退到上一级而不是首页', async (t) => {
  const h = boot(); t.after(() => h.close());
  stubFetch(h, [], () => ({ items: [], used: 0, quota: 100 }));
  h.run('stack = [{view:"home"}]');
  h.run('openDrive()');
  h.run('dvGo("国考")');
  h.run('dvGo("国考/真题")');
  assert.strictEqual(h.run('stack.length'), 4, '进目录没压栈，返回会一步跳回首页');
  h.run('back()');
  assert.strictEqual(h.run('stack[stack.length-1].folder'), '国考', '返回该退到上一级目录');
  h.run('back()');
  assert.strictEqual(h.run('stack[stack.length-1].folder'), '');
  h.run('back()');
  assert.strictEqual(h.run('stack[stack.length-1].view'), 'home', '再返回才回首页');
  await settle();          // loadDrive 是异步的，等它落地再让 t.after 关掉 jsdom
});

test('__dvShow：栈弹回来时按栈里记的目录重列', async (t) => {
  const h = boot(); t.after(() => h.close());
  stubFetch(h, [], () => ({ items: [], used: 0, quota: 100 }));
  h.run('dvFolder = "别处"; dvInTrash = true');
  h.run('window.__dvShow({view:"drive", folder:"国考/真题"})');
  assert.strictEqual(h.run('dvFolder'), '国考/真题');
  assert.strictEqual(h.run('dvInTrash'), false, '从回收站按返回回来，该回到普通列表');
  await settle();
});
