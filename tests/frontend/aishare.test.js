/* 别人分享给我的 AI 对话：只读地看 + 接着问。 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const SHARE = {
  id: 5, title: '资料分析提速', from: '同桌', mine: false, created_at: '2026-08-18 10:00',
  msgs: [{ role: 'user', content: '资料分析总超时' },
         { role: 'assistant', content: '先练**截位直除**' }],
};

function bootAs(t) {
  const h = boot({
    fetch: (url) => {
      const u = String(url);
      if (/\/adopt$/.test(u)) return { json: { id: 42, n: 2 } };
      if (/^\/api\/aishare\/\d+$/.test(u)) return { json: SHARE };
      return { json: {} };
    },
  });
  t.after(() => h.close());
  return h;
}
const $ = (h, s) => h.window.document.querySelector(s);

test('只读地看：正文出来了，助手那边走 Markdown', async (t) => {
  const h = bootAs(t);
  await h.run('openAiShare(5)');
  assert.match($(h, '.as-m').textContent, /来自 同桌/);
  assert.match($(h, '.as-msgs').innerHTML, /<strong>截位直除<\/strong>/);
  assert.ok($(h, '#as-adopt'), '得有「接着问」的入口，不然分享就只是给人看个截图');
});

test('这一页没有输入框（是一份记录，不是能打字的窗口）', async (t) => {
  const h = bootAs(t);
  await h.run('openAiShare(5)');
  assert.strictEqual($(h, '#view-aishare').querySelectorAll('textarea').length, 0);
});

test('接着问 = 在自己名下复制一条，然后打开它', async (t) => {
  const h = bootAs(t);
  h.run('window.__opened = 0; openAI = async () => {}; aiOpenChat = async (id) => { window.__opened = id; };');
  await h.run('openAiShare(5)');
  await h.run("asAdopt(5)");
  await new Promise(r => setTimeout(r, 40));
  assert.ok(h.calls.some(c => c.method === 'POST' && c.url === '/api/aishare/5/adopt'));
  assert.strictEqual(h.window.__opened, 42, '复制完该直接把新对话打开');
});

test('卡片没带编号时说清楚，别静默什么都不做', (t) => {
  const h = bootAs(t);
  h.run('openAiShare(0)');
  assert.ok(h.toasts.some(x => x.err));
});
