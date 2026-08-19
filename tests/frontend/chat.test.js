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

/* ---- 聊天里的文件：点一下先问「预览还是下载」 ----
   原来文件是个裸 <a href=... download>：安卓 WebView 同域链接就地导航，整个单页应用
   被文件顶掉、window.appBack 跟着没了，左滑只能退到后台，再进来就是重新加载回首页。
   所以这几条钉的是「文件卡不能是会导航的链接」，以及点它之后该发生什么。 */
test('文件卡不是链接：没有 href，导航不走', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = h.window.document.createElement('div');
  box.innerHTML = h.run("crFileCard(12, '讲义.pdf', 3200, true)");
  const el = box.firstElementChild;
  assert.strictEqual(el.tagName, 'BUTTON', '文件卡还是 <a>，点了会把网页导航走');
  assert.strictEqual(el.getAttribute('href'), null);
  assert.strictEqual(el.dataset.cfile, '12');
  assert.strictEqual(el.dataset.cfv, '1', '可预览的标记没带上');
});

test('信息栏的共享文件同样不带 target=_blank', (t) => {
  const h = boot(); t.after(() => h.close());
  const html = h.run("crFileRow({ id: 5, name: '真题.pdf', size: 10, view: true, who: '小李', time: '2026-08-18 10:00' })");
  assert.ok(!/target=/.test(html), 'target="_blank" 在安卓里就是就地导航，网页会被顶掉');
  assert.ok(!/href=/.test(html));
  assert.match(html, /data-cfile="5"/);
});

test('点文件：弹动作卡，预览 / 下载 / 转存三条路', (t) => {
  const h = boot(); t.after(() => h.close());
  const doc = h.window.document;
  doc.getElementById('cr-msgs').innerHTML = h.run("crFileCard(12, '讲义.pdf', 3200, true)");
  doc.querySelector('[data-cfile]').dispatchEvent(new h.window.MouseEvent('click', { bubbles: true }));
  const sheet = doc.getElementById('cr-fsheet');
  assert.ok(sheet, '点了文件没有任何拦截，等于又变回「点了就下」');
  const acts = [...sheet.querySelectorAll('[data-cf]')].map(b => b.dataset.cf);
  assert.deepStrictEqual(acts, ['view', 'dl', 'save', 'x']);
  assert.match(sheet.textContent, /讲义\.pdf/, '卡上得写清楚是哪个文件');
});

test('看不了的格式：不给一个点了没用的「预览」', (t) => {
  const h = boot(); t.after(() => h.close());
  const doc = h.window.document;
  doc.getElementById('cr-msgs').innerHTML = h.run("crFileCard(9, '素材.zip', 999, false)");
  doc.querySelector('[data-cfile]').dispatchEvent(new h.window.MouseEvent('click', { bubbles: true }));
  const sheet = doc.getElementById('cr-fsheet');
  assert.strictEqual(sheet.querySelector('[data-cf="view"]'), null, '压缩包不该给可点的预览');
  assert.ok(sheet.querySelector('.cf-b.off[disabled]'), '该有一行灰掉的说明，而不是干脆不提');
  assert.match(sheet.textContent, /下载后再打开/);
});

test('返回一次只关一层：动作卡开着时，退的是它，不是整个聊天窗', (t) => {
  const h = boot({ mobile: true }); t.after(() => h.close());
  const doc = h.window.document;
  h.run("stack = [{ view: 'home' }, { view: 'chat', title: '聊天' }, { view: 'chat', room: 7, title: '小李' }]");
  doc.getElementById('cr-msgs').innerHTML = h.run("crFileCard(12, '讲义.pdf', 3200, true)");
  doc.querySelector('[data-cfile]').dispatchEvent(new h.window.MouseEvent('click', { bubbles: true }));
  assert.ok(doc.getElementById('cr-fsheet'), '前置条件：动作卡开着');
  assert.strictEqual(h.run('appBack()'), true);
  assert.strictEqual(doc.getElementById('cr-fsheet'), null, '返回没关掉动作卡');
  assert.strictEqual(h.run('stack.length'), 3, '一次返回退了两级：聊天窗被一起弹掉了');
});

test('返回一次只关一层：看大图浮层也归返回键管', (t) => {
  const h = boot({ mobile: true }); t.after(() => h.close());
  const doc = h.window.document;
  h.run("stack = [{ view: 'home' }, { view: 'chat', room: 7 }]");
  h.run("lightbox('/api/chat/file/3?inline=1', '图.png')");
  assert.ok(doc.getElementById('lbx'), '前置条件：看图浮层开着');
  assert.strictEqual(h.run('appBack()'), true);
  assert.strictEqual(doc.getElementById('lbx'), null, '返回没关掉看图浮层，直接退出了聊天窗');
  assert.strictEqual(h.run('stack.length'), 2);
});

test('下载进度画在这条消息自己的卡片上', (t) => {
  const h = boot(); t.after(() => h.close());
  const doc = h.window.document;
  doc.getElementById('cr-msgs').innerHTML = h.run("crFileCard(12, '讲义.pdf', 3200000, true)");
  h.run("CR_DL[12] = { state: 'run', pct: 38, got: 1200000, total: 3200000 }; crDlPaint(12)");
  const card = doc.querySelector('[data-cfile="12"]');
  assert.match(card.querySelector('em').textContent, /38%/, '进度没写在卡上，人只能反复点');
  assert.strictEqual(card.querySelector('.cr-fbar i').style.width, '38%');
  assert.strictEqual(card.querySelector('.cr-fact').textContent, '取消', '下载中再点该是取消，不是又下一遍');

  h.run("window.__chatDlDone('12', '')");
  assert.match(card.querySelector('em').textContent, /已保存/, '下完了卡上要留个交代');
  assert.ok(card.querySelector('.cr-fbar').classList.contains('hidden'));

  h.run("window.__chatDlFail('12', '网络断开')");
  assert.match(card.querySelector('em').textContent, /网络断开/, '失败要说清原因');
  assert.strictEqual(card.querySelector('.cr-fact').textContent, '重试');
});

/* ---- 「以下是未读消息」那条红线 ----
   进会话时线要落在第一条没读过的消息前面，读过之后就不该再出现。曾经这里读的是
   `m.read_at_self` —— 后端从来没有这个字段，`!undefined` 恒真，于是每条对方发的
   消息都算未读：线钉死在首屏第一条上，每次点开会话都从一个月前那个位置开始看。
   钉死的是「按后端真实给的已读字段判」，不是某一次的字段名。 */
function crMsgs(list, extra) {
  return { json: Object.assign({ messages: list, me: 1, has_more: false, recalled: [] }, extra || {}) };
}
const crIn = (id, read) => ({ id, mine: false, kind: 'text', body: '第' + id + '条', time: '', read });

async function crUnreadAfter(t, list, extra, gid) {
  const h = boot({ fetch: () => crMsgs(list, extra) });
  t.after(() => h.close());
  h.run(`crFid = ${gid ? 0 : 9}; crGid = ${gid || 0}; crName = 'x'; crLastId = 0`);
  await h.run('crLoad(true)');
  const line = h.window.document.getElementById('cr-unread');
  return line ? +line.nextElementSibling.dataset.mid : 0;   // 线下面第一条是谁
}

test('未读线落在第一条没读过的消息前', async (t) => {
  const at = await crUnreadAfter(t, [crIn(1, true), crIn(2, true), crIn(3, false), crIn(4, false)]);
  assert.strictEqual(at, 3, '线该在第 3 条前面');
});

test('全都读过了就不画线：否则每次点开都从同一个老位置开始', async (t) => {
  const at = await crUnreadAfter(t, [crIn(1, true), crIn(2, true), crIn(3, true)]);
  assert.strictEqual(at, 0, '读过的消息还被当成未读，线画出来了');
});

test('群里按服务端给的 my_read 水位画线', async (t) => {
  // 群消息没有逐条已读，read 一律是 false —— 只能靠水位分开
  const list = [crIn(11, false), crIn(12, false), crIn(13, false), crIn(14, false)];
  assert.strictEqual(await crUnreadAfter(t, list, { my_read: 12 }, 5), 13, '线该在水位之后那条前面');
  assert.strictEqual(await crUnreadAfter(t, list, { my_read: 14 }, 5), 0, '水位已到最新，不该还有线');
});
