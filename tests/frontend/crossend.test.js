/* 跨端手抄的常量：前端一份、后端一份，别让它俩走散。
 *
 * 这类副本删不掉 —— 前端得在调接口**之前**就把选项画出来（比如错题本的板块下拉、
 * 复习卡片上「认识 → 2 天后」的预告），那时候还拿不到后端算的值。删不掉就得盯着。
 *
 * 而且它真咬过人。mods/review.py 的注释里记着：「白名单手抄了第二份，加新来源时
 * 取词那边加了、提交这边忘了加，卡片点认识直接参数错误」。
 *
 * 为什么是自动发现而不是逐个点名：
 *   逐个点名只能钉住我今天翻出来的这 3 个（WQ_BOARDS / OFFICE_EXT / CK_TO_ENTRY）。
 *   明天谁再手抄第 4 份，照样没人盯 —— 而「手抄」这个动作本身才是病根。所以这里扫
 *   两边的源码、按名字配对，新增的副本自动进网。
 *   （review.js 的 RV_INTERVALS ↔ mods/review.py 的 REVIEW_INTERVALS 名字不同，
 *    配不上对，已由 review.test.js 单独钉住。这也说明自动发现有个边界：改了名的
 *    手抄它抓不到，那种只能手写。）
 *
 * 比的是「内容集合」不是「字面量」：两边类型本就不同（JS 数组 ↔ Python set/dict），
 * 顺序也不该强求 —— 后端只拿它当白名单校验，顺序不影响。要抓的是「一边加了新成员、
 * 另一边没加」。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../..');

// 字面量里所有带引号的字符串 + 裸数字 —— 当作这份常量的「内容」
function members(src) {
  const out = new Set();
  for (const m of src.matchAll(/'([^']*)'|"([^"]*)"/g)) out.add(m[1] !== undefined ? m[1] : m[2]);
  for (const m of src.matchAll(/(?<!['"\w.])(\d+(?:\.\d+)?)(?!['"\w])/g)) out.add(m[1]);
  return out;
}

function collectFE() {
  const out = {};
  const dir = path.join(ROOT, 'static/js');
  for (const f of fs.readdirSync(dir).filter(x => x.endsWith('.js'))) {
    const t = fs.readFileSync(path.join(dir, f), 'utf8');
    for (const m of t.matchAll(/^const ([A-Z][A-Z0-9_]{2,})\s*=\s*([[{][\s\S]*?);\s*$/gm)) {
      out[m[1]] = { file: 'static/js/' + f, body: m[2] };
    }
  }
  return out;
}

function collectBE() {
  const out = {};
  for (const d of ['mods', '.']) {
    const dir = path.join(ROOT, d);
    for (const f of fs.readdirSync(dir).filter(x => x.endsWith('.py'))) {
      const t = fs.readFileSync(path.join(dir, f), 'utf8');
      // Python 的字面量可能跨行，一直读到括号配平
      for (const m of t.matchAll(/^([A-Z][A-Z0-9_]{2,})\s*=\s*([[{(])/gm)) {
        const start = m.index + m[0].length - 1;
        const open = m[2], close = { '[': ']', '{': '}', '(': ')' }[open];
        let depth = 0, end = start;
        for (let i = start; i < t.length; i++) {
          if (t[i] === open) depth++;
          else if (t[i] === close && --depth === 0) { end = i + 1; break; }
        }
        if (!out[m[1]]) out[m[1]] = { file: `${d}/${f}`.replace('./', ''), body: t.slice(start, end) };
      }
    }
  }
  return out;
}

test('前后端同名的常量表，内容必须一致（一边加了新成员、另一边忘了 = 用户点了就报错）', () => {
  const fe = collectFE(), be = collectBE();
  const shared = Object.keys(fe).filter(k => be[k]).sort();
  assert.ok(shared.length >= 3,
    `只配对上 ${shared.length} 份跨端常量（${shared}）—— 抓取正则失效了？` +
    '本该至少有 WQ_BOARDS / OFFICE_EXT / CK_TO_ENTRY 三份');

  for (const k of shared) {
    const a = members(fe[k].body), b = members(be[k].body);
    const onlyFE = [...a].filter(x => !b.has(x));
    const onlyBE = [...b].filter(x => !a.has(x));
    assert.deepStrictEqual(
      { 只在前端有: onlyFE, 只在后端有: onlyBE },
      { 只在前端有: [], 只在后端有: [] },
      `${k} 前后端走散了：${fe[k].file} vs ${be[k].file}`);
  }
});

test('这套配对真能抓到走散（变异自检 —— 别让测试变成摆设）', () => {
  // 上面那条全靠两边的正则都抓得到东西。哪天谁把 const 换成 let、或后端改用
  // dataclass，配对数会悄悄掉到 0，测试就永远绿了。这条把「走散」造出来验一遍。
  const fe = collectFE(), be = collectBE();
  assert.ok(fe.WQ_BOARDS && be.WQ_BOARDS, 'WQ_BOARDS 没配上对 —— 抓取逻辑已失效');
  // 往前端那份里塞一个后端没有的板块，必须被发现
  const mutated = members(fe.WQ_BOARDS.body.replace(']', ", '行政执法']"));
  const drift = [...mutated].filter(x => !members(be.WQ_BOARDS.body).has(x));
  assert.deepStrictEqual(drift, ['行政执法'],
    '前端偷偷加了个板块却没被发现 —— members() 或配对逻辑坏了');
});
