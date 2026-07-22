/* 书签「看到哪了」：当前位置引用 bmRef。
 *
 * bookmarks 改动 2 次、零测试。bmRef 从当前视图栈顶算出一个「书签引用」：某些视图
 * （首页/账户/搜索等）不记书签（BM_SKIP），带子标识的视图（文档/新闻/板块）用各自的
 * id 当 ref，其余用标题兜底。算错了「继续上次」会跳错地方。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

function stackTop(h, view, title, extra) {
  h.run(`stack = [${JSON.stringify(Object.assign({ view, title: title || '' }, extra))}];`);
}

test('BM_SKIP 里的视图不记书签（首页/账户/搜索等）', (t) => {
  const h = boot(); t.after(() => h.close());
  stackTop(h, 'home', '首页');
  assert.strictEqual(h.run('bmRef()'), null, 'home 不该记书签');
  stackTop(h, 'account', '账户');
  assert.strictEqual(h.run('bmRef()'), null);
});

test('普通视图用标题兜底当 ref', (t) => {
  const h = boot(); t.after(() => h.close());
  stackTop(h, 'shenlun', '申论');
  const r = h.plain('bmRef()');
  assert.strictEqual(r.kind, 'shenlun');
  assert.ok(r.ref, 'ref 空了 —— 继续上次会跳不回来');
});

test('带子标识的视图用它的 id 当 ref（板块页记住是哪个板块）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`ckBoard = '成语';`);
  stackTop(h, 'ckboard', '常考词');
  assert.strictEqual(h.plain('bmRef()').ref, '成语', 'ckboard 没用 ckBoard 当 ref');
});

test('空栈不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`stack = [];`);
  assert.strictEqual(h.run('bmRef()'), null);
});

/* 提示条本体：手机端它钉在屏幕下方、3 秒不点就自己走（电脑端不动它）。
   会漏的地方是「自己走」这一步 —— 定时器忘了清、或者点了「跳回去」之后还留着。 */
const BM_HIT = { json: { items: [{ kind: 'shenlun', ref: '申论', pos: 0.9, updated_at: '2026-07-20 18:09' }] } };
const bmTip = (h) => h.window.document.getElementById('bm-tip');
async function bmShow(h) {
  // 提示条要出得来，页面得真能滚（px < 260 就不提示）
  h.run(`document.documentElement.style.height = '9000px';`);
  Object.defineProperty(h.window.document.documentElement, 'scrollHeight', { value: 9000, configurable: true });
  Object.defineProperty(h.window.document.documentElement, 'clientHeight', { value: 800, configurable: true });
  h.window.document.documentElement.scrollTo = () => {};   // jsdom 没有 Element.scrollTo
  h.run(`stack = [{ view: 'shenlun', title: '申论' }];`);
  await h.run('bmRestore()');
}

test('手机端：3 秒没点「跳回去」，提示条自己消失', async (t) => {
  const h = boot({ mobile: true, fetch: () => BM_HIT }); t.after(() => h.close());
  await bmShow(h);
  assert.ok(!bmTip(h).classList.contains('hidden'), '书签提示压根没出来');
  await new Promise(r => setTimeout(r, 3200));
  assert.ok(bmTip(h).classList.contains('hidden'), '3 秒过了还赖着 —— 手机上它正压在正文上');
});

test('电脑端也一样 3 秒自动消失', async (t) => {
  const h = boot({ fetch: () => BM_HIT }); t.after(() => h.close());
  await bmShow(h);
  assert.ok(!bmTip(h).classList.contains('hidden'), '书签提示压根没出来');
  await new Promise(r => setTimeout(r, 3200));
  assert.ok(bmTip(h).classList.contains('hidden'), '电脑端没自动收走');
});

test('点了「跳回去」就立刻收，不等那 3 秒', async (t) => {
  const h = boot({ fetch: () => BM_HIT }); t.after(() => h.close());
  await bmShow(h);
  h.window.document.getElementById('bm-go').click();
  assert.ok(bmTip(h).classList.contains('hidden'), '点完还留着');
});

/* 提示条和划重点结果条都在屏幕下方，撞上了才让位 —— 电脑端结果条默认在顶部，
   不该因为「它在」就把书签提示整条吞掉（拖到下面那一带才算撞）。 */
test('电脑端：结果条在顶部不影响书签提示', async (t) => {
  const h = boot({ fetch: () => BM_HIT }); t.after(() => h.close());
  h.run(`$('#mk-bar').classList.remove('hidden');`);
  h.window.document.getElementById('mk-bar').getBoundingClientRect = () => ({ top: 66, bottom: 102 });
  await bmShow(h);
  assert.ok(!bmTip(h).classList.contains('hidden'), '结果条在顶部，书签提示不该被吞掉');
});

test('结果条被拖到下方时，这次不出书签提示', async (t) => {
  const h = boot({ fetch: () => BM_HIT }); t.after(() => h.close());
  h.run(`$('#mk-bar').classList.remove('hidden');`);
  const ih = h.window.innerHeight;
  h.window.document.getElementById('mk-bar').getBoundingClientRect = () => ({ top: ih - 60, bottom: ih - 20 });
  await bmShow(h);
  assert.ok(bmTip(h).classList.contains('hidden'), '两条摞在屏幕下方同一处了');
});

test('换页时上一页的书签提示先收走', async (t) => {
  const h = boot({ mobile: true, fetch: () => BM_HIT }); t.after(() => h.close());
  await bmShow(h);
  h.run(`stack = [{ view: 'home' }];`);
  await h.run('bmRestore()');
  assert.ok(bmTip(h).classList.contains('hidden'), '首页不记书签，提示条却跟着跑过来了');
});
