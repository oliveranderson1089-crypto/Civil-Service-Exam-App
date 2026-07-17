/* 弹窗居中：防止「僵尸 CSS」再次咬人。
 *
 * 这是本会话唯一一个「查出来的真 bug」却差点没测试的地方，补上。事故经过：
 *   535d7fb  #note-modal 装的是 .note-editor（底部抽屉式），于是写了
 *            #note-modal{align-items:flex-end}
 *   f57ddd5  小记重做为语雀式，#note-modal 从 HTML 里消失 —— 但那两条 CSS 留在原地
 *   6242fe5  五天后，词条功能新建了一个同名 #note-modal（笔记弹窗）
 * → 僵尸规则复活，咬在一个毫不相干的功能上。.modal 是 place-items:center，而
 *   #note-modal 是 id 选择器、特异性压过 class，于是词条笔记弹窗手机上贴底、
 *   桌面上又被 @media 拉回居中 —— 全项目独此一份，从 6-27 潜伏到 7-17 无人察觉。
 *   因为 CSS 不报错，只是静默变丑。
 *
 * 为什么测「所有弹窗一致」而不是「#note-modal 居中」：
 *   成因不是「#note-modal 这个 id 特殊」，而是「功能无关的通用 id 被别的功能重新
 *   认领，静默继承前任样式」。特判 #note-modal 只堵住这一个名字；测一致性，则任何
 *   弹窗被任何 id 规则夺走居中都会红。style.css 里有 142 条 id 选择器、其中 23 条
 *   设置布局/定位属性，撞车面不小。
 *
 * jsdom 的两个脾气（都实测过，别改）：
 *   1. 它**认** id 特异性 —— 把僵尸规则加回去，alignItems 真会变成 'flex-end'（这条
 *      测试就是靠这个才有效；变异验证过：加回规则 → 红）。
 *   2. 它**不展开** place-items 简写 —— 所以 .modal 的居中读出来是
 *      placeItems==='center' 而 alignItems===''，两个都得断言。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const S = path.resolve(__dirname, '../../static');

// 只验 CSS 层叠，不跑那 54 个脚本 —— 脚本剥掉，jsdom 建得快得多。
function boot(extraCss = '') {
  const css = fs.readFileSync(path.join(S, 'style.css'), 'utf8') + extraCss;
  const html = fs.readFileSync(path.join(S, 'index.html'), 'utf8')
    .replace(/<script\b[^>]*><\/script>/g, '')
    .replace('<link rel="stylesheet" href="style.css">', `<style>${css}</style>`);
  const dom = new JSDOM(html, { pretendToBeVisual: true });
  const w = dom.window;
  const modals = [...w.document.querySelectorAll('.modal')].map(el => {
    const cs = w.getComputedStyle(el);
    return { id: el.id || '(无 id)', alignItems: cs.alignItems, placeItems: cs.placeItems };
  });
  return { modals, close: () => dom.window.close() };
}

test('所有弹窗都居中，没有哪个被 id 规则单独改掉', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.ok(h.modals.length >= 5, `只找到 ${h.modals.length} 个 .modal —— 选择器失效了？`);
  for (const m of h.modals) {
    assert.strictEqual(m.placeItems, 'center',
      `${m.id} 的居中被覆盖成了 place-items:${m.placeItems}`);
    assert.strictEqual(m.alignItems, '',
      `${m.id} 被一条更高特异性的规则设成了 align-items:${m.alignItems} —— ` +
      '这正是 #note-modal 当年贴底的原因。若确实想让某个弹窗不居中，' +
      '请给它一个功能限定的 class（别用 id），并在这里写明例外。');
  }
});

test('#note-modal 不再继承旧小记编辑器的贴底样式（回归钉子）', (t) => {
  const h = boot(); t.after(() => h.close());
  const m = h.modals.find(x => x.id === 'note-modal');
  assert.ok(m, '#note-modal 没了？它是词条的笔记弹窗（editNote），别连带删掉');
  assert.strictEqual(m.alignItems, '', '贴底的僵尸规则回来了');
  assert.strictEqual(m.placeItems, 'center');
});

test('这套断言真能抓到僵尸规则（变异自检 —— 别让测试变成摆设）', (t) => {
  // 上面两条测试若因 jsdom 换版本而不再认 id 特异性，会变成永远绿的摆设。
  // 这条把僵尸规则原样加回去：抓不到就说明那两条已经失效了。
  const h = boot('\n#note-modal{align-items:flex-end;}'); t.after(() => h.close());
  const m = h.modals.find(x => x.id === 'note-modal');
  assert.strictEqual(m.alignItems, 'flex-end',
    'jsdom 不再认 id 选择器的特异性了 —— 上面两条测试已经形同虚设，得换验证手段');
  assert.ok(h.modals.some(x => x.alignItems === ''), '对照组：别的弹窗不该受影响');
});
