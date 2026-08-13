/* 前端拆包的两道闸。
 *
 * 背景：assets.py 把 71 个 js 拼成两个包 —— core 同步加载（挡首屏），
 * rest 用 defer（DOM 解析完再执行）。首屏阻塞字节从 537KB 降到 337KB 靠的就是这一刀。
 *
 * 这一刀的危险在于它**只在线上出事**：core 里只要有一句顶层代码同步用到了
 * rest 里定义的函数，加载时就 ReferenceError，应用停在启动屏。
 * 而平时的测试是把所有脚本拼一起跑的，永远绿。这个项目在打包上已经栽过一次
 * 同样形状的跟头（script 插进 DOM 中间 → 只在打包后的线上白屏），assets.py 里
 * 那道 _check_tags_at_end 就是那次留下的。这里补的是第二道。
 *
 * 两道闸：
 *   ① 只加载 core 包，启动要能走完，不许抛 ReferenceError
 *   ② 静态分析：core 里任何文件的顶层同步代码，不许引用 rest 里定义的符号
 * ① 是行为验证（真跑一遍），② 是覆盖 ① 跑不到的分支（比如只在手机上走的那条）。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { parse } = require('acorn');
const { boot, ROOT } = require('./harness');

/* CORE_FILES 的唯一真相在 assets.py。这里从那儿读出来，不在测试里抄一份——
   抄一份的话，改了 assets.py 而忘了改测试，测试会对着旧清单点头。 */
function coreFiles() {
  const py = fs.readFileSync(path.join(ROOT, 'assets.py'), 'utf8');
  const m = py.match(/^CORE_FILES = \[([\s\S]*?)^\]/m);
  assert.ok(m, 'assets.py 里找不到 CORE_FILES —— 拆包结构变了？');
  return [...m[1].matchAll(/"(js\/[^"]+\.js)"/g)].map(x => x[1]);
}

function allScripts() {
  const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
  return [...html.matchAll(/<script src="(js\/[^"]+\.js)"><\/script>/g)].map(m => m[1]);
}

test('CORE_FILES 里的文件都真实存在，且都在 index.html 里', () => {
  const all = allScripts();
  for (const f of coreFiles()) {
    assert.ok(fs.existsSync(path.join(ROOT, 'static', f)), `${f} 不存在`);
    assert.ok(all.includes(f), `${f} 在 CORE_FILES 里，但 index.html 没加载它`);
  }
});

test('闸一：只加载 core 包，启动能走完，不抛 ReferenceError', (t) => {
  const h = boot({ only: coreFiles() });
  t.after(() => h.close());
  // console.error 里出现 ReferenceError 就说明 core 引用了 rest 的东西。
  // jsdom 的 outside-only 模式下，eval 抛错会直接冒出来（boot 就炸了），
  // 走到这儿说明整段执行完了；再查一遍日志，捞异步路径上的。
  const bad = h.logs.error.filter(l => /ReferenceError|is not defined/.test(l));
  assert.deepStrictEqual(bad, [], '首屏包里有未定义的引用：' + bad.join(' | '));
});

test('闸一之二：只加载 core 时，外壳的关键 DOM 绑定都在', (t) => {
  const h = boot({ only: coreFiles() });
  t.after(() => h.close());
  // 启动屏要能被撤掉、导航要能点 —— 这几样属于首屏，缺一个就是「界面卡住」
  const joined = h.bindings.join('\n');
  for (const need of ['#tab-groups @click', '#today-body @click']) {
    assert.ok(joined.includes(need), `只加载 core 时缺少绑定：${need}`);
  }
});

/* ---------------- 闸二：静态分析 ---------------- */

const FNS = new Set(['FunctionExpression', 'ArrowFunctionExpression', 'FunctionDeclaration']);

function collectPattern(n, out) {
  if (!n) return;
  if (n.type === 'Identifier') out.add(n.name);
  else if (n.type === 'ObjectPattern') n.properties.forEach(p => collectPattern(p.value || p.argument, out));
  else if (n.type === 'ArrayPattern') n.elements.forEach(e => e && collectPattern(e, out));
  else if (n.type === 'AssignmentPattern') collectPattern(n.left, out);
  else if (n.type === 'RestElement') collectPattern(n.argument, out);
}

/* 只收「脚本执行那一刻真的会求值」的引用：一律不进嵌套函数体。
   挂在 onclick 上、写进路由表里的调用都是延后执行的，等用户点的时候
   defer 的 rest 早就到了 —— 把它们算进来的话结论会变成「什么都不能拆」。 */
function syncRefs(node, out) {
  if (!node || typeof node !== 'object') return;
  if (Array.isArray(node)) { node.forEach(n => syncRefs(n, out)); return; }
  if (FNS.has(node.type)) return;
  if (node.type === 'Identifier') { out.add(node.name); return; }
  if (node.type === 'MemberExpression') {
    syncRefs(node.object, out);
    if (node.computed) syncRefs(node.property, out);
    return;
  }
  if (node.type === 'Property') {
    if (node.computed) syncRefs(node.key, out);
    syncRefs(node.value, out);
    return;
  }
  for (const k of Object.keys(node)) {
    if (['type', 'start', 'end', 'loc'].includes(k)) continue;
    syncRefs(node[k], out);
  }
}

function analyze(files) {
  const owner = new Map();     // 符号 -> 定义它的文件
  const bodies = new Map();    // 顶层函数名 -> 函数体 AST
  const topEval = new Map();   // 文件 -> 顶层立即求值引用到的符号
  for (const f of files) {
    const src = fs.readFileSync(path.join(ROOT, 'static', f), 'utf8');
    const ast = parse(src, { ecmaVersion: 2022, sourceType: 'script' });
    const mine = new Set(), refs = new Set();
    for (const st of ast.body) {
      if (st.type === 'FunctionDeclaration' && st.id) { mine.add(st.id.name); bodies.set(st.id.name, st.body); continue; }
      if (st.type === 'ClassDeclaration' && st.id) { mine.add(st.id.name); continue; }
      if (st.type === 'VariableDeclaration') {
        st.declarations.forEach(d => {
          collectPattern(d.id, mine);
          if (d.id.type === 'Identifier' && d.init && FNS.has(d.init.type)) bodies.set(d.id.name, d.init.body);
          if (d.init) syncRefs(d.init, refs);
        });
        continue;
      }
      syncRefs(st, refs);
    }
    mine.forEach(n => { if (!owner.has(n)) owner.set(n, f); });
    topEval.set(f, refs);
  }
  return { owner, bodies, topEval };
}

test('闸二：core 的顶层同步代码不引用 rest 里定义的符号', () => {
  const all = allScripts();
  const core = coreFiles();
  const rest = all.filter(f => !core.includes(f));
  const { owner, bodies, topEval } = analyze(all);

  const problems = [];
  for (const f of core) {
    // 从顶层引用出发做传递闭包：顶层调了本文件的函数，那个函数体里的同步调用
    // 一样是加载期就要在场的（today.js 末尾的 tdLoad() 就是这么一条链）。
    const seen = new Set(), queue = [...topEval.get(f)];
    while (queue.length) {
      const n = queue.pop();
      if (seen.has(n)) continue;
      seen.add(n);
      const b = bodies.get(n);
      if (b) { const more = new Set(); syncRefs(b, more); more.forEach(m => { if (!seen.has(m)) queue.push(m); }); }
    }
    for (const n of seen) {
      const o = owner.get(n);
      if (o && rest.includes(o)) problems.push(`${f} 顶层用到了 ${n}（定义在 ${o}，属于 defer 的 rest 包）`);
    }
  }
  assert.deepStrictEqual(problems, [],
    '首屏包同步引用了延后加载的符号，线上会停在启动屏：\n  ' + problems.join('\n  '));
});

test('闸二之二：rest 不为空，且首屏包确实比整包小得多', () => {
  const all = allScripts();
  const core = coreFiles();
  const rest = all.filter(f => !core.includes(f));
  assert.ok(rest.length > 0, 'rest 空了 —— 那这刀等于没拆');
  const size = fs => fs.reduce((s, f) => s + require('fs').statSync(path.join(ROOT, 'static', f)).size, 0);
  const c = size(core), r = size(rest);
  // 拆完首屏还占八成以上的话，这刀就不值得它带来的风险了，该重新挑清单
  assert.ok(c < (c + r) * 0.8,
    `首屏包占 ${(100 * c / (c + r)).toFixed(0)}%，拆得不够，不值这个风险`);
});
