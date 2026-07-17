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
