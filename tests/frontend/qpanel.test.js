/* 做题页右栏的标签切换：答题卡 / AI 助手 / 草稿纸 / 笔记（对齐目标效果图）。
 *
 * 这一层不重写那三个浮层，只是**把元素搬进右栏**。搬家要还三笔账，
 * 漏一笔都不会报错、只会出怪事，所以每一笔都单独钉一条：
 *   · 搬进去要脱离 fixed（.dk-inline），搬回来要恢复原样、清掉拖拽留下的坐标；
 *   · dock.js 的 applyPush 不能再按它的宽度推正文 —— 它已经在正文里了；
 *   · 离开做题页必须还回去，否则元素跟着隐藏的视图一起消失，
 *     下次点悬浮球就是「点了没反应」。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const $ = (h, s) => h.window.document.querySelector(s);
const $$ = (h, s) => [...h.window.document.querySelectorAll(s)];

test('四个标签按目标图的次序出现，默认停在答题卡', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.deepStrictEqual($$(h, '#rq-tabs [data-qp]').map(b => b.textContent),
    ['答题卡', 'AI 助手', '草稿纸', '笔记']);
  assert.strictEqual($(h, '#rq-tabs .on').textContent, '答题卡');
});

test('切到「笔记」= 把随手记搬进右栏，不是另做一个', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  const qn = () => $(h, '#qnote');
  assert.strictEqual(qn().parentElement.tagName, 'BODY', '前提变了：随手记本来挂在 body 上');
  h.run("qpShow('note')");
  assert.strictEqual(qn().closest('#rq-host') !== null, true, '没搬进右栏');
  assert.ok(qn().classList.contains('dk-inline'), '没脱离 fixed，会浮在页面上而不是待在栏里');
  assert.ok(!qn().classList.contains('hidden'));
});

test('切回答题卡：浮层要还给 body，并恢复原样', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run("qpShow('note')");
  // 模拟它被拖过：makeFloat 会把坐标写在 style 上
  h.run("$('#qnote').style.left = '120px'; $('#qnote').style.width = '390px';");
  h.run("qpShow('sheet')");
  const qn = $(h, '#qnote');
  assert.strictEqual(qn.parentElement.tagName, 'BODY', '没还回 body');
  assert.ok(!qn.classList.contains('dk-inline'));
  assert.ok(qn.classList.contains('hidden'));
  assert.strictEqual(qn.style.left, '', '拖拽留下的坐标没清，搬回去还赖在右栏那个位置');
  assert.strictEqual(qn.style.width, '');
});

test('答题卡那一档才显示答题卡和「本题相关」', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run("qpShow('note')");
  assert.ok($(h, '#rq-side').classList.contains('qp-off'));
  assert.ok($(h, '#rq-rel').classList.contains('qp-off'));
  h.run("qpShow('sheet')");
  assert.ok(!$(h, '#rq-side').classList.contains('qp-off'));
});

test('内联的面板不再推正文：它已经在正文里了', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run("qpShow('pad')");            // 草稿纸搬进右栏
  h.run('applyPush()');
  assert.strictEqual(h.window.document.body.style.getPropertyValue('--push-r'), '0px',
    'applyPush 把内联面板也算进去了 —— 正文会白让出去半屏');
  assert.strictEqual(h.window.document.body.style.getPropertyValue('--push-b'), '0px');
});

test('离开做题页就把浮层还回去，不然下次点悬浮球「没反应」', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run("qpShow('ai')");
  assert.ok($(h, '#ai-panel').closest('#rq-host'), '前提没成立：AI 面板没搬进右栏');
  h.run("push({ view: 'notes' })");   // 走了
  assert.strictEqual($(h, '#ai-panel').parentElement.tagName, 'BODY',
    '元素还留在右栏里，而右栏跟着隐藏的做题页一起没了 —— 悬浮球点了会像没反应');
  assert.strictEqual($(h, '#rq-tabs .on').textContent, '答题卡', '档位没归位');
});

test('切到 AI / 草稿纸 / 笔记时右栏要加宽：292px 装不下聊天和画布', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  const view = () => h.window.document.getElementById('view-realrun');
  h.run("qpShow('pad')");
  assert.ok(view().classList.contains('qp-wide'),
    '切到草稿纸没加宽 —— 画布只剩巴掌大，没法算数');
  h.run("qpShow('sheet')");
  assert.ok(!view().classList.contains('qp-wide'), '回到答题卡还占着加宽的位置');
});

test('画布类面板进栏后要重新量尺寸，否则笔迹落点对不上', () => {
  const js = require('fs').readFileSync(
    require('path').join(__dirname, '../../static/js/qpanel.js'), 'utf8');
  assert.match(js, /k: 'pad',[^}]*fit: \(\) => padFit\(\)/,
    '草稿纸没挂 fit —— 画布是按容器像素画的，容器变了不重算，手落在哪儿和线画在哪儿就错开');
  assert.match(js, /requestAnimationFrame\(\(\) => \{[^}]*t\.fit\(\)/,
    '没等一帧就量：元素刚插进 DOM，宽高还是 0');
});

test('内联面板要给死高度：height:auto 会让画布塌成一条', () => {
  const css = require('fs').readFileSync(
    require('path').join(__dirname, '../../static/style.css'), 'utf8');
  const m = css.match(/@media ?\(min-width:761px\)\{[^@]*?#view-realrun\.qp-wide[\s\S]*?\n\}/);
  assert.ok(m, '没有加宽规则');
  assert.match(m[0], /\.dk-inline\{height:calc\(/, '内联面板没给确定高度');
});
