/* 项目设置：指令得随时改得动。
 *
 * 原先指令只在「新建项目」那一刻用一个单行输入框问过一次，之后前端没有任何入口，
 * 后端也没有改的接口。而空项目更惨：点进去直接开新对话，连项目页都看不到。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const PROJ = { id: 3, name: '申论批改', instructions: '按采分点打分', cnt: 0 };
function bootAi(t, chats) {
  const h = boot({
    fetch: (url) => {
      const u = String(url);
      if (u.indexOf('/api/aichat/home') === 0) return { json: { chats: chats || [], projects: [PROJ] } };
      if (/\/files$/.test(u)) return { json: { files: [{ id: 1, name: '评分标准', size: 320 }] } };
      return { json: { ok: true } };
    },
  });
  t.after(() => h.close());
  return h;
}
const $$ = (h, s) => h.window.document.querySelector(s);
const click = (h, el) => el.dispatchEvent(new h.window.MouseEvent('click', { bubbles: true }));

test('空项目也进得去项目页（否则永远够不到设置）', async (t) => {
  const h = bootAi(t, []);
  h.run("$('#ai-panel').classList.remove('hidden');");
  await h.run('loadAiHome()');
  h.run('openAiProject(3)');
  assert.ok($$(h, '#aipd-set'), '项目页上该有「项目设置」入口');
  assert.ok(h.run("document.querySelector('#aih-recents').innerHTML").includes('还没有对话'));
});

test('设置弹层把现有的名字和指令填进去', async (t) => {
  const h = bootAi(t, []);
  h.run("$('#ai-panel').classList.remove('hidden');");
  await h.run('loadAiHome()');
  await h.run('openAiProjSet(3)');
  assert.ok(!$$(h, '#ai-projsheet').classList.contains('hidden'));
  assert.strictEqual($$(h, '#ps-name').value, '申论批改');
  assert.strictEqual($$(h, '#ps-ins').value, '按采分点打分', '指令得能看见才谈得上改');
  assert.ok($$(h, '#ps-files').innerHTML.includes('评分标准'), '挂着的参考资料也该列出来');
});

test('保存发出 PUT，且指令清空也要发出去', async (t) => {
  const h = bootAi(t, []);
  h.run("$('#ai-panel').classList.remove('hidden');");
  await h.run('loadAiHome()');
  await h.run('openAiProjSet(3)');
  $$(h, '#ps-ins').value = '';                    // 清空 = 这个项目不再加前缀
  click(h, $$(h, '#ps-save'));
  await new Promise(r => setTimeout(r, 40));

  const put = h.calls.filter(c => c.method === 'PUT');
  assert.strictEqual(put.length, 1);
  assert.strictEqual(put[0].url, '/api/aichat/projects/3');
  const body = JSON.parse(put[0].body);
  assert.strictEqual(body.name, '申论批改');
  assert.strictEqual(body.instructions, '', '空指令被过滤掉的话，用户就清不掉它了');
});

test('名字空着不发请求', async (t) => {
  const h = bootAi(t, []);
  h.run("$('#ai-panel').classList.remove('hidden');");
  await h.run('loadAiHome()');
  await h.run('openAiProjSet(3)');
  $$(h, '#ps-name').value = '   ';
  click(h, $$(h, '#ps-save'));
  await new Promise(r => setTimeout(r, 40));
  assert.strictEqual(h.calls.filter(c => c.method === 'PUT').length, 0);
  assert.ok(h.toasts.some(x => x.err), '得告诉用户为什么没保存');
});

/* 挂资料是**项目级**的：从这个入口传的文件，项目下每个对话都读得到。
   老入口只能手打/粘贴文本，用户于是退回去用输入框的回形针 —— 那个只属于那一次对话，
   正是他抱怨的那件事。 */
test('传文件走项目资料接口，不是对话附件接口', async (t) => {
  const h = bootAi(t, []);
  h.run("$('#ai-panel').classList.remove('hidden');");
  await h.run('loadAiHome()');
  await h.run('openAiProjSet(3)');
  const f = new h.window.File(['讲义正文'], '社区讲义.pdf', { type: 'application/pdf' });
  await h.run('aiProjUpload(3, args[0])', f);

  const post = h.calls.filter(c => c.method === 'POST');
  assert.strictEqual(post.length, 1);
  assert.strictEqual(post[0].url, '/api/aichat/projects/3/files/upload',
    '传到 /api/ai/extract 就又变成「只有这一个对话能用」了');
  assert.ok(post[0].body instanceof h.window.FormData);
});

test('传完刷新列表，用户当场看得见挂上了什么', async (t) => {
  const h = bootAi(t, []);
  h.run("$('#ai-panel').classList.remove('hidden');");
  await h.run('loadAiHome()');
  await h.run('openAiProjSet(3)');
  h.calls.length = 0;
  const f = new h.window.File(['x'], 'a.txt', { type: 'text/plain' });
  await h.run('aiProjUpload(3, args[0])', f);
  assert.ok(h.calls.some(c => c.url === '/api/aichat/projects/3/files' && c.method === 'GET'),
    '传完不重拉列表，界面上还是「还没挂资料」');
});

test('粘贴文本那条路还在（评分标准这类东西没必要做成文件）', async (t) => {
  const h = bootAi(t, []);
  h.run("$('#ai-panel').classList.remove('hidden');");
  await h.run('loadAiHome()');
  await h.run('openAiProjSet(3)');
  assert.ok($$(h, '#ps-addtext'), '只留传文件，等于逼用户把两行字存成文件');
  assert.ok($$(h, '#ps-upfile'), '没有 file input，「传文件」按钮点了没反应');
});

test('设置弹层里写明资料是项目内共享的', async (t) => {
  const h = bootAi(t, []);
  h.run("$('#ai-panel').classList.remove('hidden');");
  await h.run('loadAiHome()');
  await h.run('openAiProjSet(3)');
  const html = $$(h, '#ai-projsheet').innerHTML;
  assert.ok(/每一个对话|每个对话/.test(html), '不说清楚，用户就会以为又传进了某一次对话');
});
