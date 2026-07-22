/* 互动标记：正文取文 mkText / mkNodes。
 *
 * marks 改动 1 次、10 个函数、零测试。它是「在阅读区点句子做标记」的底层：从 DOM 里
 * 抽出可标记的正文，**跳过按钮/输入框/导航条/已标记的 mark** 这些不该被当正文的东西，
 * 段与段之间可插分隔符。抽错了，后面按字符偏移定位标记就会整段错位。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

function root(h, html) {
  const d = h.window.document.createElement('div');
  d.innerHTML = html;
  h.window.document.body.appendChild(d);
  return d;
}

test('mkText：跳过按钮/输入框，只取正文文字', (t) => {
  const h = boot(); t.after(() => h.close());
  const r = root(h, '<p>依法治国</p><button>收藏</button><p>建设法治</p><input value="x">');
  const s = h.run('mkText')(r, null, null);
  assert.match(s, /依法治国/);
  assert.match(s, /建设法治/);
  assert.doesNotMatch(s, /收藏/, '按钮文字被当成正文抽进去了 —— 标记偏移会错位');
});

test('mkText：纯空白节点不计入', (t) => {
  const h = boot(); t.after(() => h.close());
  const r = root(h, '<p>甲</p>\n\n   \n<p>乙</p>');
  assert.strictEqual(h.run('mkText')(r, null, null), '甲乙', '空白节点混进正文了');
});

test('mkText：给了分隔符则段间插入（段落边界不粘连）', (t) => {
  const h = boot(); t.after(() => h.close());
  const r = root(h, '<p>第一段</p><p>第二段</p>');
  assert.strictEqual(h.run('mkText')(r, null, '\n'), '第一段\n第二段');
});

test('mkNodes：返回每段文字节点及其字符起点（供偏移定位）', (t) => {
  const h = boot(); t.after(() => h.close());
  const r = root(h, '<p>依法治国</p><p>建设法治</p>');
  const nodes = h.run('mkNodes')(r, null, null);
  assert.strictEqual(nodes.length, 2);
  assert.strictEqual(nodes[0].start, 0);
  assert.strictEqual(nodes[1].start, 4, '第二段起点该接在第一段（4 字）之后');
});

/* ---- 颜色：正文里的 <mark> 必须和清单里那一条同色 ----
   踩过的坑：正文那层查的是时政的 NW_KIND（只有 提法/数据/政策/金句），范文的
   「分论点/素材/…」一个都查不到，全落到 NW_KIND['提法'] 的橙色上 —— 清单五颜六色、
   正文清一色橙，颜色就不再是「类型」的意思了。 */
const PROF = `mkProf = { name: '范文', kinds: [{ k: '分论点', d: '' }, { k: '素材', d: '' }],
  color: { 分论点: '#c4661f', 素材: '#1a6fb5' } }; mkProfScope = 'essayd';`;

test('划出来的重点按类型上色，不是全用同一种', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(PROF);
  const r = root(h, '<p>以创新为矛、以奋斗为盾。徐梦桃征战四届冬奥会。</p>');
  h.run('mkApply')(r, [{ quote: '以创新为矛、以奋斗为盾', kind: '分论点', why: '' },
    { quote: '徐梦桃征战四届冬奥会', kind: '素材', why: '' }]);
  const cols = [...r.querySelectorAll('mark.gk-mk')].map(m => m.style.getPropertyValue('--mk').trim());
  assert.strictEqual(cols.length, 2, '两处重点没都标上');
  assert.deepStrictEqual([...cols].sort(), ['#1a6fb5', '#c4661f'],
    `正文用的颜色不是清单里那两个类型色，实际 ${JSON.stringify(cols)}`);
});

test('mkColor：正文和清单取的是同一处颜色（profile 优先）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(PROF);
  assert.strictEqual(h.run(`mkColor('素材')`), '#1a6fb5');
  // profile 里没有的类型：退回时政那套，再退默认色，但不能是 undefined
  assert.strictEqual(h.run(`mkColor('数据')`), '#1e8449');
  assert.ok(h.run(`mkColor('没这个类型')`), '未知类型没给出颜色 —— <mark> 会变成没底色的斜体字');
});

/* ---- 结果条在不在，只认一条：它描述的那些 <mark> 还在不在眼前这一屏 ----
   这是**唯一**靠得住的判据。视图名认不出「换了一篇文章」（成文详情页永远叫 writed），
   定时器也猜不准（正文是异步渲染的）。下面几条把这三种情形都钉住。 */
const bar = (h) => h.window.document.getElementById('mk-bar');
const list = (h) => h.window.document.getElementById('mk-list');
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// 造一屏「已经划过重点」的页面：正文里有 <mark>，结果条也画好了
function markedPage(h, view) {
  h.run(`stack = [{ view: '${view}', title: 't' }];
    $('#view-${view}').classList.remove('hidden');
    $('#view-${view}').innerHTML = '<div class="cd-wrap"><p>' +
      '<mark class="nw-mk gk-mk" data-gkm="0" style="--mk:#c4661f">以创新为矛<i>分论点</i></mark></p></div>';
    mkMarks = [{ quote: '以创新为矛', kind: '分论点', why: '' }];
    mkRenderBar(1, false); mkWatch(); window.__t_st = stack[0];`);
}

test('没划过重点的页面：结果条和清单收着', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`$('#mk-bar').classList.remove('hidden'); $('#mk-list').classList.remove('hidden');
         document.body.classList.add('mk-open');`);
  h.run('window.__mkView()');
  assert.ok(bar(h).classList.contains('hidden'), '换页了结果条还飘在别的模块上面');
  assert.ok(list(h).classList.contains('hidden'), '清单没收走');
  assert.ok(!h.window.document.body.classList.contains('mk-open'), 'mk-open 没清，悬浮球一直藏着');
});

test('换页收走、返回原页接回来（profile 也换回这一页的）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(PROF);
  markedPage(h, 'essayd');
  // 逛去别的模块：视图藏起来了，mkProf 也被换成人家的
  h.run(`$('#view-essayd').classList.add('hidden');
    stack = [{ view: 'csboard', title: '常识' }];
    mkProf = { name: '常识积累', kinds: [], color: { 定义: '#b23b2e' } }; mkProfScope = 'csboard';
    window.__mkView();`);
  assert.ok(bar(h).classList.contains('hidden'), '离开时没把结果条收走');
  // 原路返回：栈顶还是原来那个对象，正文和 <mark> 都还在
  h.run(`$('#view-essayd').classList.remove('hidden');
    stack = [window.__t_st]; window.__mkView();`);
  assert.ok(!bar(h).classList.contains('hidden'), '回到原页，结果条没接回来');
  assert.match(list(h).innerHTML, /范文/, '清单用成了别的模块的 profile —— 颜色和类型名都会串');
});

test('打开同一模块的另一篇：结果条不会接到新文章头上', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(PROF);
  markedPage(h, 'writed');
  /* 成文详情页在 fetch 期间不清正文，此刻上一篇的 <mark> 还挂在 DOM 里 ——
     只按「有没有 mark」判断的话，就会把上一篇的「划出 8 处重点」接到这一篇头上。
     push 进来的是一个新的栈顶对象，认的就是这个。 */
  h.run(`stack = [{ view: 'writed', title: '成文' }]; window.__mkView();`);
  assert.ok(bar(h).classList.contains('hidden'),
    '换了一篇文章，结果条还挂着上一篇的「划出 N 处重点」（点清单里的条目会全落空）');
});

test('正文被换掉：结果条自己收（不用等下次换页）', async (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(PROF);
  markedPage(h, 'essayd');
  assert.ok(!bar(h).classList.contains('hidden'), '刚划完，结果条该在');
  h.run(`$('#view-essayd').innerHTML = '<div class="cd-wrap"><p>换成另一篇的正文了</p></div>';`);
  await sleep(300);                    // MutationObserver + 120ms 合并
  assert.ok(bar(h).classList.contains('hidden'), '正文换了，<mark> 全没了，结果条还留在屏幕上');
});

test('电脑端：拖过的位置记住，下次出现在那儿', (t) => {
  const h = boot(); t.after(() => h.close());
  h.window.localStorage.setItem('gk.mkbar.pos', JSON.stringify({ x: 300, y: 200 }));
  h.run('mkPos = null; mkShowBar();');
  assert.ok(bar(h).classList.contains('mk-moved'), '没按记住的位置摆');
  assert.strictEqual(bar(h).style.left, '300px');
  assert.strictEqual(bar(h).style.top, '200px');
});

test('窗口变小时把结果条夹回视口里（别拖到屏幕外面找不回来）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.window.localStorage.setItem('gk.mkbar.pos', JSON.stringify({ x: 99999, y: -500 }));
  h.run('mkPos = null; mkShowBar();');
  assert.strictEqual(bar(h).style.top, '8px', '负坐标没夹回来');
  assert.ok(parseInt(bar(h).style.left, 10) <= h.window.innerWidth, '跑到屏幕右边外面去了');
});

test('手机端：结果条钉在下方，不吃拖动位置', (t) => {
  const h = boot({ mobile: true }); t.after(() => h.close());
  h.window.localStorage.setItem('gk.mkbar.pos', JSON.stringify({ x: 300, y: 200 }));
  h.run('mkPos = null; mkShowBar();');
  assert.ok(!bar(h).classList.contains('mk-moved'), '手机端不该套用电脑端拖出来的位置');
  assert.strictEqual(bar(h).style.left, '', '手机端位置该由 CSS 定（屏幕下方居中）');
});
