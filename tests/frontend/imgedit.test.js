/* 图片编辑：转、裁、打码。
 *
 * jsdom 没有真 canvas，所以这里给它一个**会记账的假 2d context**：
 * 画了什么记下来，getImageData 给回真实数组。这样马赛克那条能验到「像素真被抹掉」，
 * 而不是只验「调用了某个方法」—— 打码是这功能里唯一不能出错的地方。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

/* 一块可控的像素：横向渐变（每一列都不一样）。
   别用「左半黑右半白」—— 分界正好落在块边界上时，平均完还是纯黑纯白，
   那条断言就成了摆设，代码把 putImageData 原样写回也能过。 */
const GRAD = (x) => (x * 6) % 256;
function checkerData(w, h) {
  const d = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      d[i] = d[i + 1] = d[i + 2] = GRAD(x); d[i + 3] = 255;
    }
  }
  return d;
}

function fakeCanvas(h, opts = {}) {
  const w = h.window;
  const put = [];                        // putImageData 收到的每一笔
  const ops = [];                        // 画了什么
  const ctxOpts = [];                    // 每次 getContext 拿到的第二个参数
  w.HTMLCanvasElement.prototype.getContext = function (kind, o) {
    ctxOpts.push(o);
    return {
      drawImage: (...a) => ops.push(['drawImage', a.length]),
      translate: () => ops.push(['translate']),
      rotate: (r) => ops.push(['rotate', r]),
      scale: (x) => ops.push(['scale', x]),
      beginPath: () => {}, moveTo: () => {}, lineTo: () => {},
      stroke: () => ops.push(['stroke']),
      getImageData: (x, y, ww, hh) => ({ width: ww, height: hh, data: checkerData(ww, hh) }),
      putImageData: (img, x, y) => put.push({ img, x, y }),
      set strokeStyle(v) { ops.push(['strokeStyle', v]); },
      set lineWidth(v) { ops.push(['lineWidth', v]); },
      set lineCap(v) {}, set lineJoin(v) {},
    };
  };
  w.HTMLCanvasElement.prototype.toBlob = function (cb, type, q) {
    ops.push(['toBlob', type, q]);
    cb(new w.Blob([new Uint8Array(1234)], { type: type || 'image/png' }));
  };
  // 画布在屏幕上的位置/尺寸：坐标换算要用（展示 300px 宽、画布 600px 宽 = 2 倍）
  const rect = opts.rect || { left: 100, top: 50, width: 300, height: 200 };
  w.HTMLCanvasElement.prototype.getBoundingClientRect = () => ({
    ...rect, right: rect.left + rect.width, bottom: rect.top + rect.height,
  });
  w.HTMLElement.prototype.setPointerCapture = () => {};
  return { put, ops, ctxOpts };
}

// 把一张图「打开」到编辑器里（绕过真的 Image 加载）
function openWith(h, w, hh, name = '证件.jpg', ext = '.jpg', src = { kind: 'drive', id: 7 }) {
  h.run('openImgEdit')('/api/drive/7/view', name, ext, src);
  const cv = h.window.document.getElementById('ie-cv');
  cv.width = w; cv.height = hh;
  h.run(`ieCv = document.getElementById('ie-cv'); ieCtx = ieCv.getContext('2d');
         ieOrigin = ieCv;`);
  return cv;
}

test('能编辑的格式：改得动的才给按钮，HEIC/TIFF 不给', (t) => {
  const h = boot(); t.after(() => h.close());
  const can = h.run('ieEditable');
  assert.ok(can('.jpg') && can('.JPEG') && can('.png') && can('.webp') && can('.bmp'));
  assert.ok(!can('.heic'), 'HEIC 浏览器画不出来，给了按钮就是点了没反应');
  assert.ok(!can('.tif') && !can('.pdf') && !can(''));
});

test('查看器：图片出现「编辑」，PDF 和 HEIC 不出现', (t) => {
  const h = boot(); t.after(() => h.close());
  const btn = h.window.document.getElementById('viewer-edit');
  h.run('openViewerUrl')('/api/drive/7/view', '证件.jpg', '.jpg', null, null, { kind: 'drive', id: 7 });
  assert.ok(!btn.classList.contains('hidden'));
  h.run('openViewerUrl')('/api/drive/8/view', '讲义.pdf', '.pdf', null);
  assert.ok(btn.classList.contains('hidden'));
  h.run('openViewerUrl')('/api/drive/9/view', '手机拍的.heic', '.heic', null);
  assert.ok(btn.classList.contains('hidden'));
});

test('打开编辑器：浮层露出来，并且压一层栈（返回=退出编辑，不是退出查看器）', (t) => {
  const h = boot(); t.after(() => h.close());
  fakeCanvas(h);
  const before = h.run('stack.length');
  openWith(h, 600, 400);
  assert.ok(!h.window.document.getElementById('imgedit').classList.contains('hidden'));
  assert.ok(h.window.document.body.classList.contains('ie-open'));
  assert.strictEqual(h.run('stack.length'), before + 1);
  assert.strictEqual(h.run('stack[stack.length-1].view'), 'imgedit');
});

test('坐标换算：图是缩着显示的，点在哪就得落在哪', (t) => {
  const h = boot(); t.after(() => h.close());
  fakeCanvas(h);                       // 显示 300×200，画布 600×400 → 2 倍
  openWith(h, 600, 400);
  const p = h.run('ieAt')({ clientX: 100 + 30, clientY: 50 + 20 });
  assert.deepStrictEqual([p.x, p.y], [60, 40], '不换算的话，手指点在户号上、码打在旁边');
});

test('马赛克：像素被就地平均掉，不是盖一层色块', (t) => {
  const h = boot(); t.after(() => h.close());
  const rec = fakeCanvas(h);
  openWith(h, 600, 400);
  h.run('ieBrush = 40');
  h.run('ieMosaicAt')(300, 200);
  assert.strictEqual(rec.put.length, 1, '必须写回像素 —— 只画个方块盖住不算打码');
  const { data, width } = rec.put[0].img;
  const block = 10;                       // brush 40 / 4
  const vals = [];
  for (const [bx, by] of [[0, 0], [10, 0], [20, 20], [30, 10]]) {
    // 块内处处相同 = 细节真的没了
    const first = data[((by * width) + bx) * 4];
    for (let yy = 0; yy < block; yy++) {
      for (let xx = 0; xx < block; xx++) {
        const i = (((by + yy) * width) + bx + xx) * 4;
        assert.strictEqual(data[i], first, `块内像素没被抹平（${bx},${by}）`);
      }
    }
    // 而且等于这一块原来的平均值 —— 不是随便涂了个颜色
    let sum = 0;
    for (let xx = 0; xx < block; xx++) sum += GRAD(bx + xx);
    assert.strictEqual(first, Math.round(sum / block), '不是这一块的平均色');
    vals.push(first);
  }
  assert.ok(new Set(vals).size > 1, '每块都一个色 = 盖了层色块，不是打码');
});

test('旋转 90°：画布长宽对调', (t) => {
  const h = boot(); t.after(() => h.close());
  fakeCanvas(h);
  openWith(h, 600, 400);
  h.run('ieRotate')(1);
  const cv = h.window.document.getElementById('ie-cv');
  assert.deepStrictEqual([cv.width, cv.height], [400, 600]);
  assert.match(h.window.document.getElementById('ie-dims').textContent, /400 × 600/);
});

test('裁剪：框太小不动手，正常框裁出对应像素', (t) => {
  const h = boot(); t.after(() => h.close());
  fakeCanvas(h);
  openWith(h, 600, 400);
  h.run('ieDrag = { mode:"crop", x0:10, y0:10, x1:14, y1:14 }');
  h.run('ieDoCrop')();
  assert.deepStrictEqual([h.run('ieCv.width'), h.run('ieCv.height')], [600, 400], '4px 的框该被拒绝');
  assert.match(h.window.document.getElementById('ie-status').textContent, /框太小/);
  h.run('ieDrag = { mode:"crop", x0:100, y0:50, x1:340, y1:210 }');
  h.run('ieDoCrop')();
  assert.deepStrictEqual([h.run('ieCv.width'), h.run('ieCv.height')], [240, 160]);
});

test('撤销：一步一步退，最多留 15 步', (t) => {
  const h = boot(); t.after(() => h.close());
  fakeCanvas(h);
  openWith(h, 600, 400);
  const undoBtn = h.window.document.getElementById('ie-undo');
  assert.ok(undoBtn.disabled, '什么都没做时没得撤销');
  for (let i = 0; i < 20; i++) h.run('iePushUndo')();
  assert.strictEqual(h.run('ieUndo.length'), 15, '每步都是一整张画布，留太多会把手机内存吃光');
  assert.ok(!undoBtn.disabled);
});

test('保存（云盘的图）：默认另存副本，走 saveas', async (t) => {
  const seen = [];
  const h = boot({ fetch: (url, o) => {
    if (o && o.method === 'POST') seen.push([url, o.method]);
    return { json: { folder: '填表材料', name: '证件-编辑.jpg' } };
  } });
  t.after(() => h.close());
  fakeCanvas(h);
  openWith(h, 600, 400);
  const p = h.run('ieSave')();
  await new Promise(r => setTimeout(r, 0));
  const doc = h.window.document;
  assert.strictEqual(doc.getElementById('ad-ok').textContent, '另存为副本');
  assert.strictEqual(doc.getElementById('ad-alt').textContent, '覆盖原图');
  doc.getElementById('ad-ok').click();
  await new Promise(r => setTimeout(r, 0));
  assert.ok(seen.some(([u, m]) => m === 'POST' && u.includes('/api/drive/7/saveas')
                                  && u.includes(encodeURIComponent('证件-编辑.jpg'))), JSON.stringify(seen));
  // 存完要说清楚落在哪，并给一条过去的路 —— 但**不自动跳**，人还看着这张图呢
  assert.match(doc.getElementById('ad-msg').textContent, /已存到 云盘\/填表材料\/证件-编辑\.jpg/);
  assert.strictEqual(doc.getElementById('ad-ok').textContent, '去看看');
  doc.getElementById('ad-cancel').click();
  await p;
});

test('保存（云盘的图）：选覆盖要再确认一次，确认后才 replace', async (t) => {
  const seen = [];
  const h = boot({ fetch: (url, o) => {
    if (o && o.method === 'POST') seen.push([url, o.method]);   // 只记写回，别把启动时那堆 GET 也算上
    return { json: {} };
  } });
  t.after(() => h.close());
  fakeCanvas(h);
  openWith(h, 600, 400);
  const p = h.run('ieSave')();
  await new Promise(r => setTimeout(r, 0));
  const doc = h.window.document;
  doc.getElementById('ad-alt').click();                 // 覆盖原图
  await new Promise(r => setTimeout(r, 0));
  assert.match(doc.getElementById('ad-msg').textContent, /找不回来/, '覆盖必须再问一次');
  assert.ok(!seen.length, '还没确认就不许动原图');
  doc.getElementById('ad-ok').click();
  await p;
  assert.ok(seen.some(([u, m]) => m === 'POST' && u === '/api/drive/7/replace'), JSON.stringify(seen));
  assert.match(h.toasts.map(x => x.msg).join(' '), /已覆盖原图/);
});

test('保存（云盘的图）：覆盖那一步反悔，原图就不该被碰', async (t) => {
  const seen = [];
  const h = boot({ fetch: (url, o) => {
    if (o && o.method === 'POST') seen.push(url);
    return { json: {} };
  } });
  t.after(() => h.close());
  fakeCanvas(h);
  openWith(h, 600, 400);
  const p = h.run('ieSave')();
  await new Promise(r => setTimeout(r, 0));
  h.window.document.getElementById('ad-alt').click();
  await new Promise(r => setTimeout(r, 0));
  h.window.document.getElementById('ad-cancel').click();  // 算了
  await p;
  assert.deepStrictEqual(seen, []);
});

test('保存（别处来的图）：没有「覆盖」这条路，存到云盘的「图片编辑」', async (t) => {
  const seen = [];
  const h = boot({ fetch: (url, o) => {
    if (o && o.method === 'POST') seen.push([url, o.body]);
    return { json: { folder: '图片编辑', name: '群里的图-编辑.png' } };
  } });
  t.after(() => h.close());
  fakeCanvas(h);
  openWith(h, 600, 400, '群里的图.png', '.png', null);   // 聊天里收到的图
  const p = h.run('ieSave')();
  await new Promise(r => setTimeout(r, 0));
  const doc = h.window.document;
  assert.ok(doc.getElementById('ad-alt').hidden, '别人发来的图不该给「覆盖原图」');
  doc.getElementById('ad-ok').click();
  await new Promise(r => setTimeout(r, 0));
  doc.getElementById('ad-cancel').click();          // 「知道了」，不跳过去
  await p;
  const [url, body] = seen[0];
  assert.strictEqual(url, '/api/drive');
  assert.strictEqual(body.get('folder'), '图片编辑');
  assert.strictEqual(body.get('file').name, '群里的图-编辑.png');
});

test('输出格式跟着原图走：JPEG 存 JPEG，PNG 存 PNG', async (t) => {
  const h = boot(); t.after(() => h.close());
  const rec = fakeCanvas(h);
  openWith(h, 600, 400, 'a.jpg', '.jpg');
  await h.run('ieBlob')();
  assert.deepStrictEqual(rec.ops.filter(o => o[0] === 'toBlob').pop(), ['toBlob', 'image/jpeg', 0.92]);
  assert.strictEqual(h.run('ieOutName')(), 'a-编辑.jpg');
  openWith(h, 600, 400, '截图.png', '.png');
  await h.run('ieBlob')();
  assert.deepStrictEqual(rec.ops.filter(o => o[0] === 'toBlob').pop(), ['toBlob', 'image/png', undefined]);
  assert.strictEqual(h.run('ieOutName')(), '截图-编辑.png', 'PNG 要保住透明底，不能偷偷转成 JPEG');
});

test('退出编辑：改过东西要问一句，浮层收起', async (t) => {
  const h = boot(); t.after(() => h.close());
  fakeCanvas(h);
  openWith(h, 600, 400);
  h.run('iePushUndo')();                                  // 假装改过了
  h.window.document.querySelector('[data-ie="cancel"]').click();
  await new Promise(r => setTimeout(r, 0));
  const doc = h.window.document;
  assert.match(doc.getElementById('ad-msg').textContent, /不保存/);
  doc.getElementById('ad-ok').click();
  await new Promise(r => setTimeout(r, 0));
  assert.ok(doc.getElementById('imgedit').classList.contains('hidden'));
  assert.ok(!doc.body.classList.contains('ie-open'));
});

test('覆盖之后要把查看器里那张图逼着重取一次', async (t) => {
  const h = boot({ fetch: (url, o) => ({ json: {} }) }); t.after(() => h.close());
  fakeCanvas(h);
  h.run('openViewerUrl')('/api/drive/7/view', '证件.jpg', '.jpg', null, null, { kind: 'drive', id: 7 });
  openWith(h, 600, 400);
  const p = h.run('ieSave')();
  await new Promise(r => setTimeout(r, 0));
  h.window.document.getElementById('ad-alt').click();
  await new Promise(r => setTimeout(r, 0));
  h.window.document.getElementById('ad-ok').click();
  await p;
  const src = h.window.document.querySelector('#viewer-img img').getAttribute('src');
  assert.match(src, /\/api\/drive\/7\/view\?t=\d+/,
               'URL 一个字没变的话浏览器直接给缓存，用户会以为覆盖没生效');
});

test('用系统返回键退出去：底下换了页，浮层必须自己收掉', (t) => {
  const h = boot(); t.after(() => h.close());
  fakeCanvas(h);
  // 底下先垫一层「正在看这张图」：back() 只在栈里不止一层时才退
  h.run('push')({ view: 'viewer', title: '证件.jpg' });
  openWith(h, 600, 400);
  assert.ok(!h.window.document.getElementById('imgedit').classList.contains('hidden'));
  h.run('back')();                                  // = 系统返回键 / 返回手势
  assert.ok(h.window.document.getElementById('imgedit').classList.contains('hidden'),
            '不收的话编辑器会一直盖在屏幕上，谁也点不掉');
  assert.ok(!h.window.document.body.classList.contains('ie-open'));
});


/* 这条盯的是一个**看不见**的坑：WebKit（桌面壳）上，带 willReadFrequently 的画布
   drawImage 到不带的画布上，画进去是空的，不报错。主画布为了马赛克必须带这个参数，
   于是每一张拿主画布当源的离屏画布也必须带 —— 漏一个，那一步之后整张图就是透明的。
   jsdom 画不出真像素，验不了「图还在」，那就退一步验「后端是同一套」。 */
test('离屏画布必须和主画布同一套后端（漏了就整张变透明）', (t) => {
  const h = boot(); t.after(() => h.close());
  const fc = fakeCanvas(h);
  const cv = openWith(h, 600, 400);
  const each = (label) => {
    fc.ctxOpts.length = 0;
    return () => assert.ok(
      fc.ctxOpts.length > 0 && fc.ctxOpts.every(o => o && o.willReadFrequently === true),
      label + ' 建的画布少了 willReadFrequently：' + JSON.stringify(fc.ctxOpts));
  };
  let check = each('旋转'); h.run('ieRotate')(1); check();
  check = each('翻转'); h.run('ieFlip')(); check();
  check = each('撤销快照'); h.run('ieSnap')(cv); check();
  check = each('裁剪');
  h.run('ieDrag = { mode: "crop", x0: 10, y0: 10, x1: 200, y1: 150 };');
  h.run('ieDoCrop')();
  check();
});
