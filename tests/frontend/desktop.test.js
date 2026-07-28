/* 桌面版：base64 转文件 b64ToFile。
 *
 * desktop 改动 1 次、零测试。桌面壳把粘贴/拖入的图片以 base64 传进来，b64ToFile 还原成
 * File。关键是**必须按后缀补 MIME**：注释里记着教训 —— 原来不补，造出的 File.type 是空，
 * 凡是靠 f.type 判「是不是图片」的地方（compressImage/qnAddImgs/addDraftImages）全把它
 * 当非图片丢掉，表现就是「拖进去没反应」。这条测试就守着那个 type。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

// 1x1 PNG 的 base64（去掉 data: 头）
const PNG1 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

test('按后缀补上正确的 MIME（否则会被当非图片丢掉）', (t) => {
  const h = boot(); t.after(() => h.close());
  const f = h.run('b64ToFile');
  assert.strictEqual(f(PNG1, 'x.png').type, 'image/png', 'png 的 type 空了 —— 拖进去会没反应');
  assert.strictEqual(f(PNG1, 'x.jpg').type, 'image/jpeg');
  assert.strictEqual(f(PNG1, 'a.JPEG').type, 'image/jpeg', '后缀大小写没归一化');
  assert.strictEqual(f(PNG1, 'doc.pdf').type, 'application/pdf');
});

test('认不出的后缀 type 留空（但不炸、仍能造出文件）', (t) => {
  const h = boot(); t.after(() => h.close());
  const file = h.run('b64ToFile')(PNG1, 'x.zzz');
  assert.strictEqual(file.type, '');
  assert.ok(file.size > 0, '文件内容没解出来');
});

test('还原出的字节数正确（不是空文件）', (t) => {
  const h = boot(); t.after(() => h.close());
  const file = h.run('b64ToFile')(PNG1, 'x.png');
  assert.strictEqual(file.size, h.window.atob(PNG1).length, '解码出来的字节数不对');
});

test('没给文件名时兜一个默认名，不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  const file = h.run('b64ToFile')(PNG1, '');
  assert.ok(file.name && file.name.length > 0, '空文件名没兜底');
});

/* ---- 粘贴到底进哪儿（云盘/聊天页被侧栏 AI 抢走粘贴，是用户报的 bug） ----
   规矩：有焦点听焦点；没焦点时「粘贴」跟着当前页走，「拖放」还是面板优先。 */
function at(h, view, opts = {}) {          // 把应用摆到某一页 + 决定 AI 面板开不开
  h.run(`stack.length = 0; stack.push({ view: ${JSON.stringify(view)} });`);
  if (opts.crFid !== undefined) h.run('crFid = ' + opts.crFid);
  const ai = h.window.document.querySelector('#ai-panel');
  ai.classList.toggle('hidden', !opts.ai);
}

test('云盘页粘贴：AI 面板开着也该进云盘（原来被 AI 抢走）', (t) => {
  const h = boot(); t.after(() => h.close());
  at(h, 'drive', { ai: true });
  assert.strictEqual(h.run('dropTarget')('paste'), 'drive',
    '在云盘页粘贴又被侧栏 AI 截走了');
});

test('聊天页粘贴：开着聊天窗就发给对方，不进 AI', (t) => {
  const h = boot(); t.after(() => h.close());
  at(h, 'chat', { ai: true, crFid: 7 });
  assert.strictEqual(h.run('dropTarget')('paste'), 'chatroom');
});

test('聊天页没选会话时，粘贴仍归 AI（没有别的去处）', (t) => {
  const h = boot(); t.after(() => h.close());
  at(h, 'chat', { ai: true, crFid: 0 });
  assert.strictEqual(h.run('dropTarget')('paste'), 'ai');
});

test('焦点在 AI 输入框：哪怕人停在云盘页，粘贴也归 AI', (t) => {
  const h = boot(); t.after(() => h.close());
  at(h, 'drive', { ai: true });
  h.window.document.querySelector('#ai-text').focus();
  assert.strictEqual(h.run('dropTarget')('paste'), 'ai');
});

test('焦点在聊天输入框：粘贴发给对方', (t) => {
  const h = boot(); t.after(() => h.close());
  at(h, 'chat', { ai: true, crFid: 7 });
  h.window.document.querySelector('#cr-text').focus();
  assert.strictEqual(h.run('dropTarget')('paste'), 'chatroom');
});

test('拖放不变：面板开着仍优先给 AI（拖是冲着看得见的面板拖的）', (t) => {
  const h = boot(); t.after(() => h.close());
  at(h, 'drive', { ai: true });
  assert.strictEqual(h.run('dropTarget')(), 'ai', '拖放的老行为被改掉了');
  at(h, 'drive', { ai: false });
  assert.strictEqual(h.run('dropTarget')(), 'drive');
});

test('__onPasteImage：聊天页粘的图直接发出去，不会自己弹开 AI', async (t) => {
  const h = boot(); t.after(() => h.close());
  at(h, 'chat', { ai: true, crFid: 7 });
  h.window.fetch = async () => ({ blob: async () => new h.window.Blob(['x'], { type: 'image/png' }) });
  const sent = [];
  h.run('crSendFiles = (fs) => { window.__sent = fs.map(f => f.name); }');
  h.run('openAI = () => { window.__aiOpened = true; }');
  h.window.__onPasteImage('data:image/png;base64,x');
  await new Promise(r => setTimeout(r, 10));
  sent.push(...(h.window.__sent || []));
  assert.deepStrictEqual(sent, ['粘贴的图片.png'], '聊天页粘的图没发出去');
  assert.ok(!h.window.__aiOpened, 'AI 助手又被自动弹开了');
});
