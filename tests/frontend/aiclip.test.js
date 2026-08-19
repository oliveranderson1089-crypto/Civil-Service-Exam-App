/* 云盘里「复制」的文件，粘到 AI 助手里当附件。
 *
 * 实机反馈：在云盘右键「复制」，到 AI 助手输入框里右键粘贴 / Ctrl+V —— 什么都没有。
 * 原因是两套剪贴板：云盘的「复制」只是把文件 id 记在前端（桌面壳的 WebKit 右键菜单
 * 只认文本和图片，系统剪贴板里根本没这份文件），而 AI 那边只认系统剪贴板里的图片。
 *
 * 这里钉住接缝：复制要进应用内剪贴板；在 AI 里粘贴要把它读成附件（发 id，不重传文件）；
 * 剪贴板里同时有文字时不许抢 —— 粘文字是人当下的意图。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const EXTRACT = { name: '讲义.txt', text: '社区工作者考试要点', total: 9 };
const bootAi = () => boot({ fetch: (url) => (url.startsWith('/api/ai/extract') ? { json: EXTRACT } : {}) });
const tick = () => new Promise(r => setTimeout(r, 0));

function paste(h, text) {
  const ta = h.window.document.querySelector('#ai-text');
  const ev = new h.window.Event('paste', { bubbles: true, cancelable: true });
  ev.clipboardData = { files: [], items: [], getData: () => (text || '') };
  ta.dispatchEvent(ev);
  return ev;
}

const extractCalls = (h) => h.calls.filter(c => c.url === '/api/ai/extract');

test('云盘点「复制」= 同时进应用内剪贴板（系统剪贴板装不下应用里的文件）', (t) => {
  const h = bootAi(); t.after(() => h.close());
  h.run('dvSetClip([7, 9])');
  assert.deepStrictEqual(h.plain('getAppClip()'),
    [{ kind: 'drive', id: 7 }, { kind: 'drive', id: 9 }]);
});

test('在 AI 输入框里粘贴 → 按 id 挂成附件，不把文件下下来再传回去', async (t) => {
  const h = bootAi(); t.after(() => h.close());
  h.run('dvSetClip([7])');
  const ev = paste(h);
  await tick(); await tick();
  const c = extractCalls(h);
  assert.strictEqual(c.length, 1, '粘贴没有去读附件');
  assert.deepStrictEqual(JSON.parse(c[0].body), { drive_id: 7 });
  assert.ok(ev.defaultPrevented, '得拦下来，否则粘的是空文字');
  assert.deepStrictEqual(h.plain('aiAtts.map(a => a.name)'), ['讲义.txt']);
});

test('剪贴板里同时有文字：照常粘文字，只提示一句，不替人做主', async (t) => {
  const h = bootAi(); t.after(() => h.close());
  h.run('dvSetClip([7])');
  const ev = paste(h, '我抄来的一段题干');
  await tick();
  assert.strictEqual(extractCalls(h).length, 0, '抢了文字：人要粘的是那段字');
  assert.ok(!ev.defaultPrevented);
  assert.match(h.toasts.map(x => x.msg).join('|'), /还有 1 个文件/);
});

test('应用内剪贴板是空的就完全不管，粘文字照旧', async (t) => {
  const h = bootAi(); t.after(() => h.close());
  const ev = paste(h, '普通文字');
  await tick();
  assert.strictEqual(extractCalls(h).length, 0);
  assert.ok(!ev.defaultPrevented);
});

test('输入框上方给一条看得见的提示：右键菜单里的「粘贴」够不着应用内剪贴板', async (t) => {
  const h = bootAi(); t.after(() => h.close());
  const chip = h.window.document.querySelector('#ai-clipchip');
  assert.ok(chip.classList.contains('hidden'), '没复制东西时不该占地方');
  h.run('dvSetClip([7])');
  assert.ok(!chip.classList.contains('hidden'), '复制完提示条要自己冒出来');
  assert.match(chip.textContent, /1 个文件/);
  chip.querySelector('#ai-clipadd').click();
  await tick(); await tick();
  assert.deepStrictEqual(JSON.parse(extractCalls(h)[0].body), { drive_id: 7 });
  assert.ok(chip.classList.contains('hidden'), '附完了提示条该收起来');
});

test('资料库那份也能挂：走 material_id，同一个接口', async (t) => {
  const h = bootAi(); t.after(() => h.close());
  await h.run("aiAttachLib([{ kind: 'material', id: 3, name: '标准.txt' }], { keepPanel: true })");
  assert.deepStrictEqual(JSON.parse(extractCalls(h)[0].body), { material_id: 3 });
});

test('接口回 error 时不塞空附件进去（不然发送时 AI 收到一份没内容的文件）', async (t) => {
  const h = boot({ fetch: () => ({ json: { error: '文件夹不能整个当附件，进去挑里面的文件' } }) });
  t.after(() => h.close());
  await h.run("aiAttachLib([{ kind: 'drive', id: 5, name: '备考资料' }], { keepPanel: true })");
  assert.deepStrictEqual(h.plain('aiAtts'), []);
  assert.match(h.toasts.map(x => x.msg).join('|'), /文件夹/);
});
