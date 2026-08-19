/* AI 面板的返回：一层一层往上退，不能一步退出整个面板。
 *
 * 原先只认「抽屉」和「工具面板」两层，剩下一律直接藏掉面板 —— 在对话里按返回，
 * 人就被扔回底下那个页面（今日/练习/随便什么），跟「上一级」毫无关系。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const HOME = {
  chats: [{ id: 7, title: '对话甲', updated_at: '2026-08-18 10:00', project_id: 3, starred: 0, pname: '申论批改' }],
  projects: [{ id: 3, name: '申论批改', instructions: '', cnt: 1 }],
};

function bootAi(t) {
  const h = boot({
    fetch: (url) => {
      if (String(url).indexOf('/api/aichat/home') === 0) return { json: HOME };
      if (/\/api\/aichat\/chats\/\d+$/.test(String(url))) {
        return { json: { id: 7, title: '对话甲', project_id: 3, tier: 'fast',
                         msgs: [{ id: 1, role: 'user', content: '你好', kind: 'text' }] } };
      }
      return { json: { ok: true } };
    },
  });
  t.after(() => h.close());
  return h;
}
const hidden = (h, sel) => h.window.document.querySelector(sel).classList.contains('hidden');
const sideOn = (h) => h.window.document.querySelector('#ai-panel').classList.contains('side-on');

test('在对话里按返回 → 回到会话列表，面板不能关', async (t) => {
  const h = bootAi(t);
  h.run("$('#ai-panel').classList.remove('hidden'); $('#ai-panel').dataset.shell = 'dock';");
  await h.run('loadAiHome()');
  await h.run('aiOpenChat(7)');
  assert.ok(h.run('aiMsgs.length') > 0, '前置条件：会话里得有内容');

  assert.strictEqual(h.run('aiBack()'), true);
  assert.ok(sideOn(h), '该退到会话列表这一级');
  assert.ok(!hidden(h, '#ai-panel'), '不该一步就把整个面板关掉（这正是原来的毛病）');
});

test('会话列表里按返回 → 才关面板（不来回打转）', async (t) => {
  const h = bootAi(t);
  h.run("$('#ai-panel').classList.remove('hidden'); $('#ai-panel').dataset.shell = 'dock';");
  await h.run('loadAiHome()');
  await h.run('aiOpenChat(7)');
  h.run('aiBack()');                       // → 列表
  h.run('aiCurProject = null;');
  assert.strictEqual(h.run('aiBack()'), true);
  assert.ok(hidden(h, '#ai-panel'), '列表的上一级就是关掉面板');
});

test('正只看某个项目时，先退回「全部对话」', async (t) => {
  const h = bootAi(t);
  h.run("$('#ai-panel').classList.remove('hidden'); $('#ai-panel').dataset.shell = 'dock';");
  await h.run('loadAiHome()');
  h.run('aiSideOpen(); openAiProject(3);');
  assert.ok(h.run('!!aiCurProject'), '前置条件：正看着某个项目');

  assert.strictEqual(h.run('aiBack()'), true);
  assert.ok(!h.run('!!aiCurProject'), '该退回全部对话');
  assert.ok(sideOn(h), '还留在列表这一级');
  assert.ok(!hidden(h, '#ai-panel'));
});

test('工具面板开着时先收它', async (t) => {
  const h = bootAi(t);
  h.run("$('#ai-panel').classList.remove('hidden'); $('#ai-sheet').classList.remove('hidden');");
  assert.strictEqual(h.run('aiBack()'), true);
  assert.ok(hidden(h, '#ai-sheet'));
  assert.ok(!hidden(h, '#ai-panel'), '收工具面板不该顺手关掉整个面板');
});

test('工作台壳（列表常驻）没有「退回列表」这一级，直接关', async (t) => {
  const h = bootAi(t);
  h.run("$('#ai-panel').classList.remove('hidden'); $('#ai-panel').dataset.shell = 'desk';");
  await h.run('loadAiHome()');
  await h.run('aiOpenChat(7)');
  assert.strictEqual(h.run('aiBack()'), true);
  assert.ok(hidden(h, '#ai-panel'), '工作台里列表本来就看得见，没有上一级可退');
});

test('面板本来就没开时，返回不归它管', (t) => {
  const h = bootAi(t);
  assert.strictEqual(h.run('aiBack()'), false, '得让 appBack 继续往下找该退的东西');
});
