/* 小记：标签解析 + 卡片渲染的转义。
 *
 * 小记是改动第二勤的前端功能（14 次），却一条测试都没有。
 *
 * 转义这块查下来是干净的，但值得钉住 —— 因为同一个项目里 mdToHtml 就栽了：
 * 它自己写了个 E()，只转义 &<>、漏了 "，于是链接 URL 里塞引号就能注入事件处理器。
 * feedCard 用的是 core.js 的 esc()，那个转义 " —— 一字之差。
 * 这组测试就是防着有人哪天「顺手」把 esc 换成别的、或者新加字段忘了包 esc。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const XSS = '<img src=x onerror=alert(1)>"><script>alert(2)</script>';

function render(h, note) {
  const box = h.window.document.createElement('div');
  box.innerHTML = h.run('feedCard')(Object.assign({
    id: 1, content: '', images: [], attachments: [], tags: [], todos: [],
    updated_at: '2026-07-17 10:00:00',
  }, note));
  return box;
}

test('小记正文里的 HTML 一律当文字，进不了 DOM', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = render(h, { content: XSS });
  assert.strictEqual(box.querySelector('script'), null, '正文里的 script 活了');
  assert.strictEqual(box.querySelector('img'), null, '正文里的 img 活了');
  assert.match(box.querySelector('.fc-text').textContent, /<img src=x/, '该原样显示成文字');
});

test('标签 / 待办 / 文件名里的 HTML 也进不了 DOM', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = render(h, {
    tags: [XSS],
    todos: [{ text: XSS, done: false }],
    attachments: [{ ext: '.pdf', name: XSS, viewable: 1 }],
  });
  assert.strictEqual(box.querySelector('script'), null);
  assert.strictEqual(box.querySelector('img'), null);
  const evil = [...box.querySelectorAll('*')].filter(e => [...e.attributes].some(a => /^on/i.test(a.name)));
  assert.deepStrictEqual(evil.map(e => e.tagName), [], '注入出了事件处理器');
});

test('引号也得转义（mdToHtml 就是漏了这个才被打穿的）', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = render(h, { attachments: [{ ext: '.pdf', name: 'a" onmouseover="alert(1)', viewable: 1 }] });
  const btn = box.querySelector('.fc-file');
  assert.ok(btn, '文件按钮没渲染出来');
  assert.strictEqual(btn.getAttribute('onmouseover'), null, '文件名里的引号闭合了属性，注入成功');
});

test('图片 URL 是后端构造的固定格式，不是用户能填的', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = render(h, { images: ['/api/notes/1/img/0'] });
  const img = box.querySelector('.fc-imgs img');
  assert.strictEqual(img.getAttribute('src'), '/api/notes/1/img/0');
  // 这条是给将来的人看的：万一哪天 images 改成用户可填，这里就得包 esc
  assert.match(img.getAttribute('src'), /^\/api\/notes\/\d+\/img\/\d+$/,
    'images 的来源变了？那 feedCard 里的 ${u} 得包 esc —— 它现在是裸拼的');
});

test('空小记不炸（没正文、没图、没标签）', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = render(h, {});
  assert.ok(box.querySelector('.feed-card'), '空小记渲染不出卡片');
  assert.strictEqual(box.querySelector('.fc-text'), null, '没正文就不该有正文块');
});

test('标签解析：空格 / 英文逗号 / 中文逗号 / 顿号 都算分隔', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('draft = { tags: [] }');
  h.run("addTagsFrom('申论 行测,常识，判断、资料')");
  assert.deepStrictEqual(h.plain('draft.tags'), ['申论', '行测', '常识', '判断', '资料']);
});

test('标签解析：重复的不再加，且返回 false（调用方靠它决定要不要重渲染）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run("draft = { tags: ['申论'] }");
  assert.strictEqual(h.run("addTagsFrom('申论')"), false, '重复标签还报 added=true，会白刷一次');
  assert.deepStrictEqual(h.plain('draft.tags'), ['申论']);
  assert.strictEqual(h.run("addTagsFrom('申论 行测')"), true, '有新标签就该返回 true');
  assert.deepStrictEqual(h.plain('draft.tags'), ['申论', '行测']);
});

test('标签解析：空输入 / 全是分隔符 → 不加空标签', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('draft = { tags: [] }');
  for (const s of ["''", "'   '", "',,，、'", 'null', 'undefined']) {
    assert.strictEqual(h.run(`addTagsFrom(${s})`), false, `${s} 加出了标签`);
  }
  assert.deepStrictEqual(h.plain('draft.tags'), [], '混进了空标签，界面上会显示一个「# 」');
});


/* 标签栏收纳（39 个标签堆成半屏那次改的）。三条死规矩：
   外面只占一行 / 选中的一定在外面 / 顺序完全听服务端的。 */
function tagBox(h, items, cur) {
  h.run(`feedTagsAll = ${JSON.stringify(items)}; curTag = ${JSON.stringify(cur || '')};
         feedTagsOpen = false; renderFeedTags();`);
  return h.window.document.getElementById('feed-tags');
}
const MANY = Array.from({ length: 39 }, (_, i) => ({ tag: 't' + i, n: i < 5 ? 3 : 1 }));

test('标签多了：外面只留「全部 + 常用几个 + 更多」', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = tagBox(h, MANY);
  const chips = [...box.querySelectorAll('.tagchip')];
  assert.strictEqual(chips.length, 8, '外面应当是 全部 + 6 个常用 + 更多，一行放得下');
  assert.match(chips[chips.length - 1].textContent, /更多 33/, '剩下的要说清楚还有几个');
  assert.strictEqual(box.querySelector('.tagpanel'), null, '面板默认不展开');
});

test('正在筛的那个标签，就算排不进常用也留在外面', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = tagBox(h, MANY, 't38');                    // 最冷门的那个
  const out = [...box.querySelectorAll('.tagchip')].map(c => c.dataset.tag);
  assert.ok(out.includes('t38'), '选中的标签被收进面板了 —— 界面上就看不出自己在按什么筛');
  assert.strictEqual(box.querySelectorAll('.tagchip').length, 8, '挤进来不该多占一行');
  assert.strictEqual(box.querySelector('.tagchip.active').dataset.tag, 't38');
});

test('展开「更多」能搜，搜不到就直说', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`feedTagsAll = ${JSON.stringify(MANY)}; curTag = ''; feedTagsOpen = true; renderFeedTags('t3');`);
  const box = h.window.document.getElementById('feed-tags');
  const inPanel = [...box.querySelectorAll('.tagpanel-list .tagchip')].map(c => c.dataset.tag);
  assert.deepStrictEqual(inPanel, ['t3', 't30', 't31', 't32', 't33', 't34', 't35', 't36', 't37', 't38']);
  h.run("renderFeedTags('没有这个标签');");
  assert.ok(h.window.document.querySelector('.tagpanel-none'), '搜空了要给一句话，别只剩一个空框');
});

test('顺序完全按服务端给的来，前端不再自己排', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = tagBox(h, [{ tag: '乙', n: 1 }, { tag: '甲', n: 9 }, { tag: '丙', n: 5 }]);
  const out = [...box.querySelectorAll('.tagchip')].map(c => c.dataset.tag);
  assert.deepStrictEqual(out, ['', '乙', '甲', '丙'], '前端一旦自己排，就会和服务端的口径打架');
});


/* 导出弹窗。盯两件事：
   ① 范围默认是**屏幕上这些** —— 人点导出想的是眼前这一屏，不是整个库；
   ② 这个格式装不下的东西要置灰（md 带不了图、只有 zip 有附件原件），
      藏起来会让人以为「导出把图弄丢了」。 */
function openExport(h, { items = 2, board = '', tag = '', q = '', ids = null } = {}) {
  h.run(`document.getElementById('feed')._items = ${JSON.stringify(Array.from({ length: items }, (_, i) => ({ id: i + 1 })))};
         curNoteBoard = ${JSON.stringify(board)}; curTag = ${JSON.stringify(tag)}; noteSearchQ = ${JSON.stringify(q)};
         openNoteExport(${JSON.stringify(ids)});`);
  return h.window.document;
}

test('导出：范围默认跟着当前筛选走，条数说清楚', (t) => {
  const h = boot(); t.after(() => h.close());
  let d = openExport(h, { items: 7 });
  assert.ok(!d.getElementById('nx-modal').classList.contains('hidden'), '弹窗没打开');
  let opts = [...d.getElementById('nx-scope').options];
  assert.deepStrictEqual(opts.map(o => o.value), ['cur', 'all']);
  assert.match(opts[0].textContent, /7 条/);
  assert.match(opts[0].textContent, /当前列表/, '没筛选时别说「当前筛选的」');

  d = openExport(h, { items: 3, tag: '行测' });
  assert.match(d.getElementById('nx-scope').options[0].textContent, /当前筛选的 3 条/);
});

test('导出：从卡片点进来时，范围多一条「这 N 条」并排在最前', (t) => {
  const h = boot(); t.after(() => h.close());
  const d = openExport(h, { items: 9, ids: [5] });
  const opts = [...d.getElementById('nx-scope').options];
  assert.deepStrictEqual(opts.map(o => o.value), ['sel', 'cur', 'all']);
  assert.match(opts[0].textContent, /这 1 条/);
});

test('导出：装不下的选项置灰而不是藏起来', (t) => {
  const h = boot(); t.after(() => h.close());
  const d = openExport(h);
  const off = id => d.getElementById(id).classList.contains('nx-off');
  const pick = fmt => h.run(`nxFmt = '${fmt}'; nxRenderFmts();`);

  pick('md');
  assert.ok(off('nx-imgs-l') && off('nx-atts-l'), 'md 带不走图片和附件');
  pick('html');
  assert.ok(!off('nx-imgs-l') && off('nx-atts-l'), 'html 内嵌图片，但没有附件原件');
  pick('zip');
  assert.ok(!off('nx-imgs-l') && !off('nx-atts-l'), 'zip 是唯一什么都带得走的');
  // 置灰的是 label，不是 display:none —— 选项还看得见，只是点不动
  assert.ok(d.getElementById('nx-atts'), '别把选项从 DOM 里删掉');
});

test('导出：选中的格式要有说明，六种用途差得远', (t) => {
  const h = boot(); t.after(() => h.close());
  const d = openExport(h);
  const tip = () => d.getElementById('nx-tip').textContent;
  assert.strictEqual(d.querySelectorAll('.nx-fmt').length, 6);
  h.run("nxFmt = 'pdf'; nxRenderFmts();");
  const pdfTip = tip();
  h.run("nxFmt = 'json'; nxRenderFmts();");
  assert.ok(pdfTip && tip() && pdfTip !== tip(), '换了格式说明也得换');
  assert.strictEqual(d.querySelector('.nx-fmt.on').dataset.fmt, 'json', '选中态要跟上');
});

test('导出：卡片上有单条导出按钮，且带小记 id', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = render(h, { content: '随便写点' });
  const btn = box.querySelector('[data-exp]');
  assert.ok(btn, '卡片上没有导出按钮');
  assert.strictEqual(btn.dataset.exp, '1');
});

/* ---- 一次选多张图：读文件必须排队 ----
   真事：手机上选了几张不同的图，发出去有三份字节完全相同（连编辑器里的缩略图
   都是同一张）。原因是几张图的 arrayBuffer / createImageBitmap 是**同时**发起的，
   安卓 WebView 读多个 content:// URI 会互相串成同一份数据。
   下面用「谁跟别人同时读，谁就读到别人的数据」的假文件把那个环境模拟出来：
   只要哪天有人把 readFileSerial 那道闸去掉，这条就红。 */
function strayFile(h, tag, live) {
  const w = h.window;
  return {
    name: tag + '.png', type: 'image/png',
    async arrayBuffer() {
      live.n++;
      const crossed = live.n > 1;          // 有人跟我同时在读 → 读到的是别人那份
      await new Promise(r => w.setTimeout(r, 5));
      live.n--;
      return new w.TextEncoder().encode(crossed ? 'STRAY' : tag).buffer;
    },
  };
}

test('一次选多张图：读文件是排队的，不会串成同一张', async (t) => {
  const h = boot(); t.after(() => h.close());
  const live = { n: 0 };
  const files = ['aaa', 'bbb', 'ccc'].map(tag => strayFile(h, tag, live));
  await h.T.addDraftImages(files);
  const imgs = h.T.draft.images;
  assert.strictEqual(imgs.length, 3, '三张都该进草稿');
  await Promise.all(imgs.map(i => i.ready));
  const got = [];
  for (const im of imgs) got.push(await im.fileObj.text());
  assert.deepStrictEqual(got, ['aaa', 'bbb', 'ccc'], '几张图串成了同一份数据');
});

test('图片还没读出来时，缩略图不放空 img（免得一排裂图）', async (t) => {
  const h = boot(); t.after(() => h.close());
  const live = { n: 0 };
  h.T.addDraftImages([strayFile(h, 'aaa', live)]);
  const box = h.window.document.querySelector('#cp-imgs .cp-thumb');
  assert.ok(box, '位子要先占上');
  assert.strictEqual(box.querySelector('img'), null, '还没读出来就不该有 img');
  assert.ok(box.classList.contains('busy'), '该显示成「处理中」');
  await Promise.all(h.T.draft.images.map(i => i.ready));
  assert.ok(box.querySelector('img'), '读完了缩略图要补上');
});

/* ---- 点「完成」之后 ----
   手机上存一条带图的小记，慢的全在上传那几秒（服务端只要 0.0 秒）。
   所以编辑器是**先关**、上传在后台跑。代价是「万一没传成功」这条路必须是真的可靠：
   内容得原样回到编辑器，不能只弹一句红字然后人财两空。 */
function fillComposer(h, text) {
  h.window.document.querySelector('#cp-content').value = text;
  h.run(`draft.content = ${JSON.stringify(text)}`);
}

test('点完成：编辑器立刻放开，不等上传', (t) => {
  const h = boot({ fetch: () => ({ json: { id: 7 } }) }); t.after(() => h.close());
  fillComposer(h, '记一条');
  h.window.document.querySelector('#cp-submit').click();
  assert.strictEqual(h.window.document.querySelector('#cp-content').value, '',
    '还在等服务端回话就说明界面被上传挡住了');
});

test('保存失败：这条要原样回到编辑器，不能凭空没了', async (t) => {
  const h = boot({ fetch: () => new Error('隧道又断了') }); t.after(() => h.close());
  fillComposer(h, '不能丢的一条');
  h.window.document.querySelector('#cp-submit').click();
  for (let i = 0; i < 50 && !h.toasts.some(x => x.err); i++) {
    await new Promise(r => h.window.setTimeout(r, 10));
  }
  assert.strictEqual(h.window.document.querySelector('#cp-content').value, '不能丢的一条',
    '传失败了，正文没还回来');
  assert.ok(h.toasts.some(x => x.err), '失败了得说一声');
});
