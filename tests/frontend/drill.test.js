/* 专项刷题：难度系数说明 drCoefTip + 模式提示 drModeTip。
 *
 * drill 改动 2 次、零测试（dtMaterial 已由 dtmaterial.test 覆盖）。这里盯两个直接
 * 写进页面、会误导用户的地方：难度系数在公考里就是得分率，drCoefTip 得把「0.40」
 * 翻成「预期做对 40%」讲清楚，不然看着像分数；模式提示要跟当前模式一致。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('drCoefTip：把难度系数翻成「预期做对 N%」，四舍五入', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`drLevels = [{ k: 'mid', coef: 0.4, desc: '中等难度' }, { k: 'hard', coef: 0.256, desc: '偏难' }];
         drLevel = 'mid'; drCoefTip();`);
  const html = h.window.document.querySelector('#dr-coef').innerHTML;
  assert.match(html, /难度系数 0\.40/, '系数该显示两位小数');
  assert.match(html, /预期能做对 40%/, '0.40 该翻成 40%');
  h.run(`drLevel = 'hard'; drCoefTip();`);
  assert.match(h.window.document.querySelector('#dr-coef').innerHTML, /预期能做对 26%/, '0.256 该四舍五入成 26%');
});

test('drCoefTip：desc 转义（挡住注入），认不出的档位不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`drLevels = [{ k: 'mid', coef: 0.5, desc: '<img src=x onerror=alert(1)>' }]; drLevel = 'mid'; drCoefTip();`);
  const box = h.window.document.querySelector('#dr-coef');
  assert.strictEqual(box.querySelector('img'), null, 'desc 里的 img 活了');
  // 档位找不到时 coef 缺省 0，不该崩
  h.run(`drLevel = '不存在的档'; drCoefTip();`);
  assert.match(h.window.document.querySelector('#dr-coef').innerHTML, /难度系数 0\.00/);
});

test('drModeTip：提示文案跟当前模式走', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`drMode = 'exam'; drModeTip();`);
  assert.match(h.window.document.querySelector('#dr-modetip').textContent, /交卷|判分/, '考试模式该说交卷判分');
  h.run(`drMode = 'study'; drModeTip();`);
  assert.match(h.window.document.querySelector('#dr-modetip').textContent, /立刻判|边做边学/, '练习模式该说即时判');
});
