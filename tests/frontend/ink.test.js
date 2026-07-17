/* 批注：笔迹压缩 + 文本锚定位。
 *
 * 这块前后修了五轮（ebf9da5 / 565ab42 / 219e88c / c43fdd4 / d694c80），前端却一条测试都没有。
 * 后端那 24 条守的是「存进去的东西对不对」，可用户实际碰的是这里。
 *
 * 盯两件事，都是代码注释里写明踩过坑的：
 *   1. pack 的精度 —— PDF 锚的 y 是 0..1 归一化，留 1 位小数的话 0.18 会 round 成 0.2，
 *      乘回页高就是偏 42px（注释原话）。pixel 锚的 y 是像素，留 1 位就够。
 *   2. 文本锚 —— 存「那句话」而不是「那个像素」，就是为了内容重排后还能找回来。
 *      注释里实测：改个字号那一笔跑 94px、换到手机错位 180px。
 *
 * annLocate 有三级定位，下面按级覆盖。变异验证的结果值得记一笔：
 *   砍掉第 2 级（带前后文消歧）→ 红；砍掉第 3 级（只按这句话找）→ 红；
 *   砍掉第 1 级（start 还对得上就直接用）→ **不红，而这是对的**：
 *   它是性能快路径，砍了以后第 2 级会找到同一个位置，行为不变，只是每次都得全文搜一遍。
 *   只有当「前后文+锚句」整体重复时两者才会分道扬镳，那种文章罕见到不值得为它造用例。
 *   —— 记在这儿，免得以后有人看见「第 1 级没测试」以为是漏了。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

// jsdom 没有真实布局，Range.getBoundingClientRect 一律返回全 0，
// 而 annLocate 末尾会因 (b.width || b.height) 为假而返回 null —— 那样什么都测不了。
// 这个探针让它返回非零，并把 Range 当时框住的**文字**带出来：
// 于是「定位到了哪个字」变得可断言，而不只是「定位成功了没有」。
function probeRanges(h) {
  const seen = [];
  h.window.Range.prototype.getBoundingClientRect = function () {
    // 光记「框住了哪个字」不够：同一句话出现两次时两边都是「依」，分不出命中的是哪一处。
    // 连所在文本节点一起记下来，才能断言它落在了正确的那一段。
    seen.push({ text: this.toString(), node: (this.startContainer.nodeValue || '').slice(0, 24) });
    return { width: 1, height: 1, top: 0, left: 0, right: 1, bottom: 1, x: 0, y: 0 };
  };
  return seen;
}

function mkArticle(h, html) {
  const d = h.window.document;
  const root = d.createElement('div');
  root.innerHTML = html;
  d.body.appendChild(root);
  return root;
}

test('pack：PDF 锚的 y 留 4 位小数（留 1 位会偏 42px）', (t) => {
  const h = boot(); t.after(() => h.close());
  const out = h.T.Ink.pack([{
    tool: 'ink', color: '#f00', size: 2,
    a: { page: 1 },                       // page != null ⇒ PDF 锚，y 是 0..1
    pts: [{ x: 0.123456, y: 0.18, p: 0 }],
  }]);
  assert.strictEqual(out[0].p[0][1], 0.18, 'PDF 锚的 y 被压成了 ' + out[0].p[0][1] + '，乘回页高就偏了');
});

test('pack：pixel 锚的 y 留 1 位就够（它是像素）', (t) => {
  const h = boot(); t.after(() => h.close());
  const out = h.T.Ink.pack([{
    tool: 'ink', color: '#f00', size: 2, a: null,
    pts: [{ x: 0.123456, y: 123.456, p: 0 }],
  }]);
  assert.strictEqual(out[0].p[0][1], 123.5);
  assert.strictEqual(out[0].p[0][0], 0.1235, 'x 不论哪种锚都该留 4 位');
});

test('pack：连续重复的点去掉（笔迹是每个 pointermove 都采的）', (t) => {
  const h = boot(); t.after(() => h.close());
  const out = h.T.Ink.pack([{
    tool: 'ink', color: '#f00', size: 2, a: null,
    pts: [{ x: 0.1, y: 1 }, { x: 0.1, y: 1 }, { x: 0.1, y: 1 }, { x: 0.2, y: 2 }],
  }]);
  assert.strictEqual(out[0].p.length, 2, '重复点没去掉，白占配额');
});

test('pack：空笔迹整条丢掉，不留垃圾', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.strictEqual(h.T.Ink.pack([{ tool: 'ink', color: '#f00', pts: [] }]).length, 0);
});

test('pack/unpack 往返：一笔画完存下来再读回，还是那一笔', (t) => {
  const h = boot(); t.after(() => h.close());
  const one = { tool: 'hl', color: '#f0a500', size: 8, a: { quote: '依法治国', start: 12 },
                pts: [{ x: 0.1, y: 10.5, p: 0.5 }, { x: 0.25, y: 20.1, p: 0 }] };
  const back = h.T.Ink.unpack(h.T.Ink.pack([one]));
  assert.strictEqual(back.length, 1);
  assert.strictEqual(back[0].tool, 'hl');
  assert.strictEqual(back[0].color, '#f0a500');
  assert.strictEqual(back[0].size, 8);
  assert.deepEqual(back[0].a, { quote: '依法治国', start: 12 }, '锚丢了 = 这一笔不知道该贴哪');
  assert.strictEqual(back[0].pts.length, 2);
  assert.strictEqual(back[0].pts[0].p, 0.5, '压感丢了');
});

test('unpack：认得旧格式（迁移漏网的那些）', (t) => {
  const h = boot(); t.after(() => h.close());
  const old = [{ tool: 'ink', color: '#000', size: 2, pts: [{ x: 1, y: 2, p: 0 }] }];
  const back = h.T.Ink.unpack(old);
  assert.strictEqual(back.length, 1);
  assert.strictEqual(back[0].tool, 'ink', '旧格式被吃掉了 —— 老用户的批注会全没');
});

test('文本锚：位置没变时按 start 直接命中', (t) => {
  const h = boot(); t.after(() => h.close());
  const seen = probeRanges(h);
  const root = mkArticle(h, '<p>坚持依法治国，建设法治政府。</p>');
  const full = h.run('annCtx')(root).full;
  const start = full.indexOf('依法治国');
  const r = h.T.annLocate(root, { quote: '依法治国', prefix: '坚持', suffix: '，', start }, null);
  assert.ok(r, '原样没动都定位不到');
  assert.strictEqual(seen[seen.length - 1].text, '依', '定位到的不是锚句开头那个字');
});

test('文本锚：前面插了内容（start 失效）也能靠前后文找回来 —— 这就是它存在的理由', (t) => {
  const h = boot(); t.after(() => h.close());
  const seen = probeRanges(h);
  // 同一句话出现两次，且只有 prefix/suffix 能区分 —— 否则「只按 quote 找、取离老位置最近的」
  // 那级兜底也能蒙对，测出来是假阳性（第一版就栽在这儿：删掉消歧那级，测试照样绿）。
  const root = mkArticle(h,
    '<p>甲段落里坚持依法治国，建设法治政府。</p>' +
    '<p>乙段落里推进依法治国，完善法治体系。</p>');
  const full = h.run('annCtx')(root).full;
  // 锚记的是**乙段**那一处
  const anchor = { quote: '依法治国', prefix: '推进', suffix: '，完善', start: full.lastIndexOf('依法治国') };
  // 内容重排：前面插一大段，插入长度 > 两处间距 —— 这样「取离老位置最近的」会选错到甲段，
  // 只有「带前后文找」那级才能落回乙段。
  root.insertAdjacentHTML('afterbegin',
    '<p>' + '新插入的前言把后面的文字全推后了。'.repeat(6) + '</p>');
  const r = h.T.annLocate(root, anchor, null);
  assert.ok(r, '内容一变就找不着 = 退回了坐标锚的老毛病');
  const hit = seen[seen.length - 1];
  assert.strictEqual(hit.text, '依');
  assert.ok(hit.node.includes('乙段落'), `锚跑到「${hit.node}」去了 —— 前后文消歧没起作用，批注会贴到别的段落上`);
});

test('文本锚：连前后文都变了，还能靠「只按这句话找」兜住', (t) => {
  const h = boot(); t.after(() => h.close());
  const seen = probeRanges(h);
  const root = mkArticle(h, '<p>坚持依法治国，建设法治政府。</p>');
  const full = h.run('annCtx')(root).full;
  const anchor = { quote: '依法治国', prefix: '坚持', suffix: '，建设', start: full.indexOf('依法治国') };

  // 三级定位得逐级逼出来，不然测的是上一级（第一版这条就栽了：start 还有效，
  // 第一级直接命中，压根没走到兜底那级）：
  //   前面插内容      → start 失效，第一级过不去
  //   把「坚持」改掉  → prefix 没了，第二级找不到 '坚持依法治国，建设'
  //   剩 quote 还在   → 只能靠第三级「只按这句话找」
  root.innerHTML = '<p>新插入的一段前言。</p><p>全面推进依法治国，健全法治体系。</p>';

  const r = h.T.annLocate(root, anchor, null);
  assert.ok(r, '前后文一变就彻底锚不住 —— 兜底那级没了，用户的批注会直接消失');
  assert.strictEqual(seen[seen.length - 1].text, '依');
});

test('文本锚：那句话被删了就老实返回 null（调用方靠它显示「锚不住了」）', (t) => {
  const h = boot(); t.after(() => h.close());
  probeRanges(h);
  const root = mkArticle(h, '<p>这里已经没有那句话了。</p>');
  const r = h.T.annLocate(root, { quote: '依法治国', prefix: '坚持', start: 2 }, null);
  assert.strictEqual(r, null, '找不到却硬给个位置，批注就飘到别处去了');
});

test('文本锚：空锚 / 空 root 不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  probeRanges(h);
  const root = mkArticle(h, '<p>随便什么。</p>');
  assert.strictEqual(h.T.annLocate(null, { quote: 'x' }, null), null);
  assert.strictEqual(h.T.annLocate(root, null, null), null);
  assert.strictEqual(h.T.annLocate(root, { quote: '' }, null), null);
});
