/* 社区卷的作答态：多选、判断、答题卡。
 *
 * 这三样是这条备考线唯一**新写的交互**，其余都是复用现成的。盯三件事：
 *   ① 多选题能多勾、且揭晓时要标出「漏选」—— 对/错两态说不清少选，
 *      而少选正是「多选、少选、错选均不得分」这条规则下最常见的丢分方式；
 *   ② 模考模式一个答案字符都不能出现在 DOM 里（后端也不发，这是第二道闸）；
 *   ③ 答题卡按题型分段，主观题格子标分值、不冒充成一道没答的客观题。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

/* 一份小卷子：单选 / 多选 / 判断 / 案例各一道。字段名跟后端 _pub() 出去的一致。 */
const ITEMS = `[
  { id: 1, seq: 1, part: 'single', part_seq: 1, part_name: '单项选择题', qtype: '社区知识',
    stem: '居民委员会法定任期', score: 1, options: ['5 年','3 年','4 年','2 年'], answer: 'A' },
  { id: 2, seq: 2, part: 'multi', part_seq: 1, part_name: '多项选择题', qtype: '社区知识',
    stem: '基层网格化管理三大职责', score: 1,
    options: ['信息采集','隐患排查','便民服务','行政执法'], answer: 'ABC' },
  { id: 3, seq: 3, part: 'judge', part_seq: 1, part_name: '判断题', qtype: '公文写作',
    stem: '报告可以夹带请求批准事项。', score: 1, options: [], answer: 'F' },
  { id: 4, seq: 4, part: 'case', part_seq: 1, part_name: '案例分析题', qtype: '社会工作',
    stem: '老旧小区加装电梯矛盾…', score: 12, options: [], answer: '参考答案正文' }
]`;
const PARTS = `[
  { part: 'single', name: '单项选择题', n: 1, score: 1, rule: '四选一，选对得分。' },
  { part: 'multi', name: '多项选择题', n: 1, score: 1, rule: '多选、少选、错选均不得分' },
  { part: 'judge', name: '判断题', n: 1, score: 1, rule: '判对得分' },
  { part: 'case', name: '案例分析题', n: 1, score: 12, rule: '' }
]`;

function setup(h, mode) {
  h.run(`sqRules = { multi: '多选、少选、错选均不得分 —— 与本地真题判分口径一致。' };
    sqRun = { pid: 1, mode: '${mode}', items: ${ITEMS}, parts: ${PARTS}, idx: 0,
              answers: {}, locked: {}, held: 2, objFull: 3, t0: Date.now(), left: 7200, timer: null };
    sqRender();`);
}
const body = (h) => h.window.document.querySelector('#sq-run-body');

test('单选是圆标、多选是方标 —— 形状即规则', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 'study');
  assert.strictEqual(body(h).querySelectorAll('.sq-opt.multi').length, 0, '单选题不该有多选样式');
  h.run(`sqRun.idx = 1; sqRender();`);
  assert.strictEqual(body(h).querySelectorAll('.sq-opt.multi').length, 4, '多选题四个选项都该带 multi');
});

test('多选题能勾多个，再点一下取消', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 'study');
  h.run(`sqRun.idx = 1; sqRender(); sqPick('A'); sqPick('C');`);
  assert.strictEqual(h.run(`sqRun.answers[2]`), 'AC');
  // 还没「确定提交」，所以停在选中态、答案不揭晓
  assert.strictEqual(body(h).querySelectorAll('.sq-opt.chosen').length, 2);
  assert.doesNotMatch(body(h).textContent, /答对了|答错了/, '还没提交就揭晓了');
  h.run(`sqPick('A');`);
  assert.strictEqual(h.run(`sqRun.answers[2]`), 'C', '再点一下没取消');
});

test('多选题答案按字母序存，跟后端判分口径对得上', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 'study');
  h.run(`sqRun.idx = 1; sqRender(); sqPick('C'); sqPick('A'); sqPick('B');`);
  assert.strictEqual(h.run(`sqRun.answers[2]`), 'ABC', '顺序乱了，后端字符串比对会判错');
});

test('背题模式下少选要标出「漏选」，不是笼统一个错', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 'study');
  h.run(`sqRun.idx = 1; sqRender(); sqPick('A'); sqPick('B');
    sqRun.locked[2] = true; sqRender();`);
  const html = body(h).innerHTML;
  assert.match(html, /sq-opt[^"]*miss/, '漏掉的 C 没有标成 miss');
  assert.strictEqual(body(h).querySelectorAll('.sq-opt.right').length, 2, 'A B 该是答对的两个');
  assert.match(body(h).textContent, /答错了/, '少选就是错，不能显示答对');
});

test('多选全对才显示答对', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 'study');
  h.run(`sqRun.idx = 1; sqRender(); sqPick('A'); sqPick('B'); sqPick('C');
    sqRun.locked[2] = true; sqRender();`);
  assert.match(body(h).textContent, /答对了/);
  assert.strictEqual(body(h).querySelectorAll('.sq-opt.miss').length, 0);
});

test('判断题是两个键，不是四选一', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 'study');
  h.run(`sqRun.idx = 2; sqRender();`);
  assert.strictEqual(body(h).querySelectorAll('.sq-tf-b').length, 2);
  assert.strictEqual(body(h).querySelectorAll('.sq-opt').length, 0, '判断题不该出现选项列表');
  h.run(`sqPick('F');`);
  assert.strictEqual(h.run(`sqRun.answers[3]`), 'F');
  assert.match(body(h).textContent, /答对了/);
});

test('模考模式：DOM 里不出现答案，也不当场揭晓', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 'exam');
  h.run(`sqRun.idx = 2; sqRender(); sqPick('T');`);
  const txt = body(h).textContent;
  assert.doesNotMatch(txt, /答对了|答错了/, '模考模式当场揭晓了对错');
  assert.doesNotMatch(txt, /正确答案/, '模考模式把答案显示出来了');
});

test('主观题给输入框，并说明不当场判分', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 'study');
  h.run(`sqRun.idx = 3; sqRender();`);
  assert.ok(body(h).querySelector('#sq-sub'), '案例题没有作答框');
  assert.match(body(h).textContent, /不当场判分|参考答案/);
});

test('翻页前先把主观题写的东西收起来', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 'study');
  h.run(`sqRun.idx = 3; sqRender();`);
  h.window.document.querySelector('#sq-sub').value = '我写的处置方案';
  h.run(`sqGo(-1);`);
  assert.strictEqual(h.run(`sqRun.answers[4]`), '我写的处置方案', '一翻页就白写了');
});

test('答题卡按题型分段，主观题格子标分值', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 'study');
  h.run(`$('#sq-sheet').innerHTML = sqSheetHtml();`);
  const sheet = h.window.document.querySelector('#sq-sheet');
  assert.strictEqual(sheet.querySelectorAll('.sq-sheet-lab').length, 4, '四个题型该有四段');
  assert.strictEqual(sheet.querySelectorAll('.sq-sq.wide').length, 1, '案例题该是宽格');
  assert.match(sheet.querySelector('.sq-sq.wide').innerHTML, /12 分/, '宽格没标分值');
});

test('答题卡如实报出被扣着的题，不假装卷子是满的', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 'study');
  h.run(`$('#sq-sheet').innerHTML = sqSheetHtml();`);
  assert.match(h.window.document.querySelector('#sq-sheet').textContent, /2 道客观题答案待裁决/);
});

test('题干里的 HTML 当文字，不当标签', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, 'study');
  h.run(`sqRun.items[0].stem = '<img src=x onerror=alert(1)>居民委员会'; sqRun.idx = 0; sqRender();`);
  assert.strictEqual(body(h).querySelector('img'), null, '题干里的 img 活了');
  assert.match(body(h).textContent, /居民委员会/);
});
