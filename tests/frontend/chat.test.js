/* 聊天：头像渲染 avHtml。
 *
 * chat 改动 2 次、零测试，大半是异步 DOM 胶水。avHtml 是其中的纯逻辑：有头像图就
 * 用背景图、没有就取名字首字母。名字和图片 URL 都来自对端用户 —— 拼进 style / 首字母
 * 都得转义（URL 里塞引号能闭合 style 属性）。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('无头像：取名字首字母、大写', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.match(h.run('avHtml')(null, 'alice', 'av'), />A</, '首字母没大写');
  assert.match(h.run('avHtml')('', '  bob', 'av'), />B</, '前导空格没去掉');
});

test('空名字兜底成「?」，不显示空白圈', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.match(h.run('avHtml')(null, '', 'av'), />\?</);
  assert.match(h.run('avHtml')(null, null, 'av'), />\?</);
});

test('有头像 URL：URL 里的双引号转义，闭合不了 style 属性', (t) => {
  const h = boot(); t.after(() => h.close());
  // style 是双引号属性，要破它得用 " —— 用 ' 破不了（上一版就栽在这，测了个假的）
  const html = h.run('avHtml')('x"><img src=y onerror=alert(1)>', '张三', 'av');
  const box = h.window.document.createElement('div'); box.innerHTML = html;
  assert.strictEqual(box.querySelector('img'), null, 'URL 里的双引号闭合了 style，注入出了 img');
});

/* 手机端 #chat-main 在没进会话时是 display:none。任何 position:fixed 的浮层挂在它下面，
   都会跟着一起看不见 —— 表现是「新建小组点了确定像没反应，点开某个会话它才冒出来」。
   这条钉的是位置，不是某一次的 bug。 */
test('聊天的浮层挂在 body 下，不能住进手机端会隐藏的 #chat-main', (t) => {
  const h = boot({ mobile: true }); t.after(() => h.close());
  for (const id of ['cr-picker', 'cr-menu', 'emoji-pan']) {
    const el = h.window.document.getElementById(id);
    assert.ok(el, '#' + id + ' 不见了');
    assert.ok(!el.closest('#chat-main'),
      '#' + id + ' 挂在 #chat-main 里 —— 手机端在会话列表页它会连同容器一起看不见');
  }
});

test('新建小组：确定之后立刻出选人框（不用先点开某个会话）', async (t) => {
  const h = boot({ mobile: true, fetch: () => ({ json: { friends: [{ id: 7, username: '小李' }] } }) });
  t.after(() => h.close());
  const doc = h.window.document;
  // appPrompt 是弹窗，测试里直接给答案；别真去点那两颗按钮
  h.run("appPrompt = async () => '空耳'");
  await h.run('crNewGroup')();
  const box = doc.getElementById('cr-picker');
  assert.ok(!box.classList.contains('hidden'), '确定之后选人框没出来');
  assert.ok(!box.closest('#chat-main'), '框虽然开了，但藏在会话列表页看不见的容器里');
  assert.match(box.innerHTML, /空耳/, '框里没带上刚起的组名');
});
