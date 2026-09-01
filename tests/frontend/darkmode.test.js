/* 夜间色：写错的选择器不会报错，只会静默地不生效。
 *
 * 事故（2026-08-29 用户报「小记晚间编辑这个界面背景未统一」）：手机端全屏小记
 * 编辑器的夜间规则写成了 `body.dark body.mobile-ui .composer.cp-open` ——
 * 一个 body 套着另一个 body，DOM 里不可能存在，于是那条规则从写下的那天起
 * 一次都没生效过。白天看不出来，晚上打开编辑器就是「正文框是暗的、外面一圈全白」。
 *
 * 这里钉两件事：① 全表都不许再出现「两个 body 的后代选择器」；
 * ② 夜间 + 手机端打开编辑器，背景真的是暗的（按计算样式验，不是按文本）。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const S = path.resolve(__dirname, '../../static');
const CSS = fs.readFileSync(path.join(S, 'style.css'), 'utf8');

test('没有「body.x body.y」这种永远匹配不上的选择器', () => {
  const bad = [];
  // 注释里也会出现 body（这个文件的注释就写了好几处），先剥掉再看
  const bare = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
  // 只看选择器那一段（{ 之前），逗号切开逐条看
  for (const m of bare.matchAll(/(^|\})([^{}]+)\{/g)) {
    for (const sel of m[2].split(',')) {
      const s = sel.trim();
      if (!s || s.startsWith('@')) continue;
      // body 后面隔着空格/> 又出现一个 body：DOM 里只有一个 body，这条选择器是死的
      if (/\bbody\b[^,{]*[\s>]body\b/.test(s)) bad.push(s);
    }
  }
  assert.deepStrictEqual(bad, [], '这些选择器永远匹配不上（两个 body），改成连写：body.a.b');
});

function computed(bodyClass, prep) {
  const html = fs.readFileSync(path.join(S, 'index.html'), 'utf8')
    .replace(/<script\b[^>]*><\/script>/g, '')
    .replace('<link rel="stylesheet" href="style.css">', `<style>${CSS}</style>`);
  const dom = new JSDOM(html, { pretendToBeVisual: true });
  const w = dom.window;
  w.document.body.className = bodyClass;
  const el = prep(w.document);
  const cs = w.getComputedStyle(el);
  const out = { bg: cs.backgroundColor };
  dom.window.close();
  return out;
}

test('夜间 + 手机端：全屏小记编辑器的底色是暗的', () => {
  const openComposer = (doc) => {
    const el = doc.querySelector('#view-notes .composer');
    el.classList.add('cp-open');
    return el;
  };
  const dark = computed('dark mobile-ui', openComposer);
  const light = computed('mobile-ui', openComposer);
  assert.strictEqual(light.bg, 'rgb(255, 255, 255)', '白天该是白底（这条变了说明改错了地方）');
  assert.notStrictEqual(dark.bg, 'rgb(255, 255, 255)', '晚上还是白底 —— 夜间规则又没生效');
  assert.strictEqual(dark.bg, 'rgb(26, 34, 51)', '底色要跟其它夜间卡片一致（#1a2233）');
});

test('夜间 + 手机端：编辑器顶栏也跟着暗，别只暗一半', () => {
  const head = (doc) => {
    doc.querySelector('#view-notes .composer').classList.add('cp-open');
    return doc.querySelector('#view-notes .composer .cp-mhead');
  };
  assert.strictEqual(computed('dark mobile-ui', head).bg, 'rgb(26, 34, 51)');
});
