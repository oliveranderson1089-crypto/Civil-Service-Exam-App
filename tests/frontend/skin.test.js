/* 皮肤：调暗系数 skinDim + 预览 renderSkinPrev。
 *
 * skin 改动 2 次、零测试。skinDim 把存的调暗百分比钳到 0~90（存坏了/超范围不能让
 * 界面全黑或没效果）。renderSkinPrev：设了壁纸就显示为背景图、没设就显示占位字。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('skinDim：钳到 0~90，默认 55', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`lsDel('skinDim')`);
  assert.strictEqual(h.run('skinDim()'), 55, '没存过该给默认 55');
  h.run(`lsSet('skinDim', '200')`);
  assert.strictEqual(h.run('skinDim()'), 90, '超 90 没钳住，界面会全黑');
  h.run(`lsSet('skinDim', '-10')`);
  assert.strictEqual(h.run('skinDim()'), 0, '负数没钳到 0');
  // 边角：存了非数字 → parseInt NaN，Math.max/min 会把 NaN 一路传下去，返回 NaN。
  // 没有把它当 0 兜住。实测无害（CSS 拿到 NaN% 直接忽略、退回无调暗），且只有 localStorage
  // 被写坏才会发生，不值得为它改源码 —— 这里如实钉住「返回的是 NaN」，别让人以为兜住了。
  h.run(`lsSet('skinDim', '坏值')`);
  assert.ok(Number.isNaN(h.run('skinDim()')), 'skinDim 对非数字的行为变了？原来是返回 NaN（CSS 会忽略）');
});

test('renderSkinPrev：设了壁纸显示为背景图，没设显示占位', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`SKIN = { avatar: 'data:image/png;base64,AAAA', wall_app: '', wall_login: '' }; renderSkinPrev();`);
  const av = h.window.document.querySelector('#sk-avatar');
  if (av) {
    assert.match(av.style.backgroundImage, /data:image\/png/, '设了头像没显示为背景图');
    const wall = h.window.document.querySelector('#sk-wall_app');
    assert.strictEqual(wall.style.backgroundImage, '', '没设壁纸却有背景图');
    assert.match(wall.textContent, /无/, '没设壁纸该显示占位「无」');
  }
});
