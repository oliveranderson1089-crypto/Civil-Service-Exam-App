/* 朗读引擎/音色的选择回退 ttsEng / ttsVoice。
 *
 * partydict 改动 3 次、零测试。桌面版有多个 TTS 引擎，可用哪些由外壳在运行时报进
 * window.__ttsEngines。ttsEng 的回退链要对：存过且现在可用 → 用存的；存过但现在
 * 不可用（换了机器/删了引擎）→ 退到第一个可用的；一个都不可用 → 兜到 piper。选错了
 * 用户点朗读就没声或报错。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

function setup(h, available, saved) {
  h.run(`window.__ttsEngines = ${JSON.stringify(available)};`);
  h.run(saved == null ? `lsDel('ttsEngine')` : `lsSet('ttsEngine', ${JSON.stringify(saved)})`);
}

test('存过且当前可用 → 用存的', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, ['piper', 'edge'], 'edge');
  assert.strictEqual(h.run('ttsEng()'), 'edge');
});

test('存过但当前不可用（换了机器）→ 退到第一个可用的', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, ['piper'], 'edge');   // 存了 edge，但这台机器只有 piper
  assert.strictEqual(h.run('ttsEng()'), 'piper', '存的引擎没了却还硬用，点朗读会报错');
});

test('一个都不可用 → 兜底 piper（别返回 undefined）', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, [], null);
  assert.strictEqual(h.run('ttsEng()'), 'piper');
});

test('没存过 → 用第一个可用的', (t) => {
  const h = boot(); t.after(() => h.close());
  setup(h, ['edge'], null);
  assert.strictEqual(h.run('ttsEng()'), 'edge');
});

test('ttsVoice：没存过给默认音色（第一个），不是 undefined', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`lsDel('ttsVoice')`);
  assert.strictEqual(h.run('ttsVoice()'), h.run('TTS_VOICES[0].id'));
  h.run(`lsSet('ttsVoice', 'zh-CN-YunxiNeural')`);
  assert.strictEqual(h.run('ttsVoice()'), 'zh-CN-YunxiNeural');
});
