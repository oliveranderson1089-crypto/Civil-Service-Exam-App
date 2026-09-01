/* 桌面壳里的大文件：__onBigFile → 云盘分片通道。
 *
 * 治的是这个毛病：在桌面版里拖一个大文件进来，**一声不吭什么都没发生**（壳把超过
 * 64MB 的直接跳过了，因为整份 base64 推给网页会把 run_javascript 撑死）。
 * 现在改成「壳只推名字和大小，网页要哪一片才回头问壳要哪一片」，上限从 64MB
 * 变成分片通道自己的 2GB。
 *
 * 这里守的是三条命门：
 *   ① 真的走分片通道（init → 每片 → done），而不是整份塞进一个请求；
 *   ② 每片的字节是**问壳要来的**，浏览器里从没出现过整份文件；
 *   ③ 不管成没成，都要回一句 bigdone —— 壳靠它放行下一个，不回就是卡死在那。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const CHUNK = 4 * 1024 * 1024;              // = drive.js 的 DV_CHUNK
const SIZE = 8 * 1024 * 1024 + 1;           // 刚过分片门槛（8MB）→ 3 片：4MB / 4MB / 1B

/* 起一个「装了壳」的应用，并把壳那一侧演出来：
   收到 {a:'bigpart'} 就按 seq 把那一段字节回填给网页。 */
function bootShell(opts = {}) {
  const msgs = [];
  const h = boot({
    window: { __desktop: true, __desktopVer: '6.4' },
    fetch: opts.fetch || ((url) => {
      if (url.includes('/api/drive/chunk/init')) return { status: 201, json: { upload_id: 'u1', received: [] } };
      if (/\/api\/drive\/chunk\/u1\/done$/.test(url)) return { status: 201, json: { id: 9, name: '大讲义.mp4' } };
      if (/\/api\/drive\/chunk\/u1\/\d+$/.test(url)) return { status: 200, json: { ok: true } };
      return { json: { items: [], used: 0, quota: 1e12, max_file: 1e9 } };
    }),
  });
  const w = h.window;
  w.webkit = {
    messageHandlers: {
      gk: {
        postMessage: (raw) => {
          const d = JSON.parse(raw);
          msgs.push(d);
          if (d.a !== 'bigpart') return;
          if (opts.shellFails) { setTimeout(() => w.__deskBigFail(d.seq, '读文件失败：没这个文件'), 0); return; }
          // 壳读盘是异步的 —— 用 setTimeout 保证网页那边真的在「等」，而不是同步拿到
          setTimeout(() => w.__deskBigPart(d.seq, w.btoa('x'.repeat(d.len))), 0);
        },
      },
    },
  };
  return { h, w, msgs, calls: h.calls };
}

const META = { token: 't1', name: '大讲义.mp4', rel: '', size: SIZE, mtime: 1700000000000 };

test('大文件走分片通道：init → 每片 → done，一次都没整份发出去', async (t) => {
  const { h, w, msgs, calls } = bootShell(); t.after(() => h.close());
  await w.__onBigFile(META, 'drive');

  const posts = calls.filter(c => c.method === 'POST').map(c => c.url);
  assert.ok(posts.some(u => u.includes('/api/drive/chunk/init')), '没开分片会话');
  assert.ok(posts.some(u => /\/api\/drive\/chunk\/u1\/done$/.test(u)), '没收尾（done）');
  assert.ok(!posts.some(u => /\/api\/drive$/.test(u)),
    '走了「一整个请求发完」那条路 —— 大文件正是它传不动');

  const parts = calls.filter(c => /\/api\/drive\/chunk\/u1\/\d+$/.test(c.url));
  assert.strictEqual(parts.length, Math.ceil(SIZE / CHUNK), '片数不对');
  const bytes = parts.reduce((a, c) => a + (c.body && c.body.size || 0), 0);
  assert.strictEqual(bytes, SIZE, '发出去的总字节和文件大小对不上');
});

test('每片都是现问壳要的（浏览器里从没有过整份文件）', async (t) => {
  const { h, w, msgs } = bootShell(); t.after(() => h.close());
  await w.__onBigFile(META, 'drive');

  const asks = msgs.filter(m => m.a === 'bigpart');
  assert.strictEqual(asks.length, Math.ceil(SIZE / CHUNK), '要片的次数和片数对不上');
  assert.ok(asks.every(m => m.token === 't1'), 'token 没带上 —— 壳认不出要读哪个文件');
  assert.ok(asks.every(m => m.len <= CHUNK), '一次要了不止一片，内存尖峰又回来了');
  // 覆盖到整份：起点排序后应当是 0, 4M, 8M
  assert.deepStrictEqual(asks.map(m => m.start).sort((a, b) => a - b), [0, CHUNK, 2 * CHUNK]);
  assert.strictEqual(asks.reduce((a, m) => a + m.len, 0), SIZE, '各片加起来不等于整份');
});

test('传完回一句 bigdone（壳靠它放行下一个文件）', async (t) => {
  const { h, w, msgs } = bootShell(); t.after(() => h.close());
  await w.__onBigFile(META, 'drive');
  const fin = msgs.filter(m => m.a === 'bigdone');
  assert.strictEqual(fin.length, 1, '没回执 —— 壳会在那儿干等到静默超时');
  assert.strictEqual(fin[0].ok, 1);
  assert.strictEqual(fin[0].token, 't1');
});

test('壳读盘失败：不吞掉，照样回执 + 告诉用户', async (t) => {
  const { h, w, msgs } = bootShell({ shellFails: true }); t.after(() => h.close());
  await w.__onBigFile(META, 'drive');
  const fin = msgs.filter(m => m.a === 'bigdone');
  assert.strictEqual(fin.length, 1, '失败时也必须回执，否则后面的文件全卡住');
  assert.strictEqual(fin[0].ok, 0);
  assert.ok(h.toasts.some(t2 => /失败|没这个文件/.test(t2.msg)), '没跟用户说一声');
});

test('服务端拒了（比如超配额）：回执 ok=0，不当成功', async (t) => {
  const { h, w, msgs } = bootShell({
    fetch: (url) => (url.includes('/api/drive/chunk/init')
      ? { status: 400, json: { error: '云盘空间不足（配额 20480 MB）' } }
      : { json: { items: [] } }),
  });
  t.after(() => h.close());
  await w.__onBigFile(META, 'drive');
  const fin = msgs.filter(m => m.a === 'bigdone');
  assert.strictEqual(fin.length, 1);
  assert.strictEqual(fin[0].ok, 0);
  assert.ok(h.toasts.some(t2 => /空间不足/.test(t2.msg)), '服务端说的理由要透给用户');
});

test('元数据不全（没 token / 大小为 0）立刻回执，不去开会话', async (t) => {
  const { h, w, msgs, calls } = bootShell(); t.after(() => h.close());
  await w.__onBigFile({ name: 'x.bin', size: SIZE }, 'drive');       // 没 token
  await w.__onBigFile({ token: 't2', name: 'x.bin', size: 0 }, 'drive');
  assert.strictEqual(msgs.filter(m => m.a === 'bigdone').length, 2, '每次都得有回执');
  assert.ok(!calls.some(c => c.url.includes('/api/drive/chunk/init')),
    '拿不出内容的东西不该在服务端开一个空会话');
});

test('续传的 key 认得出同一份文件：mtime 进得去（换个名字才是另一份）', (t) => {
  const { h, w } = bootShell(); t.after(() => h.close());
  const f = h.run('deskBigFile')(META);
  assert.strictEqual(f.size, SIZE);
  assert.strictEqual(f.lastModified, META.mtime, 'lastModified 丢了 —— 下次重传认不出上次传到哪');
  assert.strictEqual(typeof f.__part, 'function', '没有 __part，chunkUpload 就读不到字节');
  void w;
});

test('dvPartOf：普通 File 走 slice，壳大文件走 __part', async (t) => {
  const { h, w } = bootShell(); t.after(() => h.close());
  const dvPartOf = h.run('dvPartOf');
  const real = new w.File([new w.Uint8Array(100)], 'a.bin');
  const part = await dvPartOf(real, 10, 30);
  assert.strictEqual(part.size, 30, '普通文件的 slice 被改坏了');

  let asked = null;
  const fake = { name: 'b.bin', size: 100, __part: (s, e) => { asked = [s, e]; return Promise.resolve('片'); } };
  assert.strictEqual(await dvPartOf(fake, 10, 30), '片');
  assert.deepStrictEqual(asked, [10, 40], '__part 收的是 [start, end)，别传成长度');
});
