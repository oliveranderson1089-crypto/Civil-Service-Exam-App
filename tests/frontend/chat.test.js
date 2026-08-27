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

/* ---- 下完之后那枚「打开」----
   进度记录（CR_DL）一分钟后就会被清掉，卡片要变回原样；但「本机已经有这一份」是
   跨会话的事实。原来两者一起清，于是下完一分钟「打开」就再也找不到，只能重下一遍；
   网页端和桌面端更早一步 —— 它们那条下载路根本没记路径，「打开」从来没出现过。 */
test('下完一分钟后进度状态清掉了，「打开」还得在', (t) => {
  const h = boot(); t.after(() => h.close());
  const doc = h.window.document;
  doc.getElementById('cr-msgs').innerHTML = h.run("crFileCard(12, '讲义.pdf', 3200000, true)");
  h.run("window.__chatDlDone('12', 'content://downloads/77')");
  h.run('delete CR_DL[12]; crDlPaint(12)');            // = crDlLater 一分钟后干的事
  const card = doc.querySelector('[data-cfile="12"]');
  assert.strictEqual(card.querySelector('.cr-fact').textContent, '打开',
                     '进度一清「打开」就没了 —— 想打开只能重下一遍');
  assert.match(card.querySelector('em').textContent, /3\.\d MB|3 MB|MB/, '文案该回到文件大小');
});

test('重进会话新画的卡片也认账：本机有那一份就带上「打开」', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run("window.__chatDlDone('12', 'content://downloads/77')");
  const html = h.run("crFileCard(12, '讲义.pdf', 3200000, true)");   // 重画一张全新的卡
  const box = h.window.document.createElement('div'); box.innerHTML = html;
  assert.strictEqual(box.querySelector('.cr-fact').textContent, '打开',
                     'crDlPaint 只在下载途中被调，重画的卡片得自己认这笔账');
});

test('点卡身还是弹动作卡，只有点「打开」才直接开', (t) => {
  const h = boot(); t.after(() => h.close());
  const doc = h.window.document;
  h.run("window.__chatDlDone('12', 'content://downloads/77')");
  h.run('delete CR_DL[12]');
  doc.getElementById('cr-msgs').innerHTML = h.run("crFileCard(12, '讲义.pdf', 3200000, true)");
  const card = doc.querySelector('[data-cfile="12"]');
  card.dispatchEvent(new h.window.MouseEvent('click', { bubbles: true }));
  assert.ok(doc.getElementById('cr-fsheet'), '点卡身该弹动作卡（预览/下载/转存都在那儿）');
  assert.match(doc.getElementById('cr-fsheet').innerHTML, /打开本机的这一份|在新标签打开/,
               '动作卡里也该给一条「打开本机那份」');
  h.run("document.getElementById('cr-fsheet').remove()");

  let opened = '';
  h.run("window.open = (u) => { window.__opened = u; return null; }");
  card.querySelector('.cr-fact').dispatchEvent(new h.window.MouseEvent('click', { bubbles: true }));
  opened = h.window.__opened || '';
  assert.strictEqual(doc.getElementById('cr-fsheet'), null, '点「打开」不该再弹一次动作卡');
  assert.match(opened, /\/api\/chat\/file\/12\?inline=1/,
               '浏览器里碰不到本机文件，「打开」该在新标签开服务器上那一份');
});

/* 桌面壳下完只喊一声 __onDownloaded(路径)，并不知道是谁点的下载 —— 那个回调本来是
   给更新包和云盘用的。聊天要认领它，否则桌面端永远拿不到路径，也就永远没有「打开」。 */
test('桌面壳：聊天发起的下载由卡片认领，不再叠一个「下载完成」弹框', (t) => {
  const h = boot({ window: { __desktop: true, __desktopVer: '6.3' } }); t.after(() => h.close());
  const doc = h.window.document;
  doc.getElementById('cr-msgs').innerHTML = h.run("crFileCard(12, '讲义.pdf', 3200000, true)");
  h.run("crDeskWait = { id: 12, name: '讲义.pdf', at: Date.now() }");
  assert.strictEqual(h.run("window.__chatDlAdopt('/home/me/下载/讲义.pdf')"), true);
  assert.strictEqual(doc.querySelector('[data-cfile="12"] .cr-fact').textContent, '打开');
  // 不是这一份就交还给原来那条路（更新包、云盘打包下载还得靠它）
  h.run("crDeskWait = { id: 12, name: '讲义.pdf', at: Date.now() }");
  assert.strictEqual(h.run("window.__chatDlAdopt('/home/me/下载/gongkao_6.3_amd64.deb')"), false);
});

/* ---- 「回来时还站在原地」----
   下完文件按返回怎么回首页了：浏览器/壳把当前标签导航到文件本身，单页应用被顶掉，
   回来是重新加载，而导航栈只活在内存里。这层兜底把「人在哪个会话」记进 sessionStorage。 */
test('看文件那一层不动记录，自己走回列表才清掉', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run("crFid = 7; crGid = 0; crName = '小李'; window.__chatResumeMark('chat')");
  assert.ok(h.window.sessionStorage.getItem('chatResume'), '在会话里就该记一笔');
  h.run("window.__chatResumeMark('viewer')");
  assert.ok(h.window.sessionStorage.getItem('chatResume'),
            '看文件时把记录清了 —— 正好丢在最容易被顶掉的地方');
  h.run("window.__chatResumeMark('home')");
  assert.strictEqual(h.window.sessionStorage.getItem('chatResume'), null,
                     '自己走回首页的，就别再把人拽回会话里');
});

test('重新加载后回到刚才那个会话；隔太久的记录不认', async (t) => {
  const h = boot({ fetch: () => ({ json: { messages: [], me: 1, has_more: false, recalled: [] } }) });
  t.after(() => h.close());
  h.window.sessionStorage.setItem('chatResume',
    JSON.stringify({ f: 7, g: 0, n: '小李', at: Date.now() }));
  h.run("stack = [{ view: 'home' }]");
  assert.strictEqual(h.run('window.__chatResume()'), true);
  assert.strictEqual(h.run('crFid'), 7, '没回到那个会话');
  assert.strictEqual(h.run("stack[stack.length - 1].view"), 'chat');
  assert.strictEqual(h.window.sessionStorage.getItem('chatResume'), null, '用过就该清掉，只兜这一次');
  // 收尾：openChatroom 起了一趟拉消息和一个轮询，不等它们落地就关窗口会炸在测试之外
  await new Promise(r => setImmediate(r));
  h.run('clearInterval(crPoll); crPoll = 0');

  h.window.sessionStorage.setItem('chatResume',
    JSON.stringify({ f: 9, g: 0, n: '老王', at: Date.now() - 20 * 60 * 1000 }));
  assert.strictEqual(h.run('window.__chatResume()'), false, '二十分钟前的记录还往回拽人');
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

/* ---- 会话列表右上角的 ＋ 菜单：怎么关 ----
   它原来只管弹出来：点别处不关（全局那份「点别处收菜单」的清单里没有它）、
   再点一次 ＋ 只是原地重画一遍、切到别的页它还悬在新页面上（.ctxmenu 是 fixed 的，
   跟视图显隐无关）。三条路各钉一条测试。 */
function chAddMenu(t) {
  const h = boot({ fetch: () => ({ json: { conversations: [], unread: 0 } }) });
  t.after(() => h.close());
  const doc = h.window.document;
  const box = doc.getElementById('ch-addmenu');
  doc.getElementById('ch-add-btn').click();
  assert.ok(!box.classList.contains('hidden'), '点 ＋ 菜单没弹出来');
  return { h, doc, box };
}

test('＋ 菜单：点页面别处就收起', (t) => {
  const { doc, box } = chAddMenu(t);
  doc.getElementById('ch-convos').click();
  assert.ok(box.classList.contains('hidden'), '点菜单外面菜单还在');
});

test('＋ 菜单：再点一次 ＋ 是收起，不是重画', (t) => {
  const { doc, box } = chAddMenu(t);
  doc.getElementById('ch-add-btn').click();
  assert.ok(box.classList.contains('hidden'), '连点两下 ＋ 菜单关不掉');
});

test('＋ 菜单：换一页就收起，不许悬在新页面上', (t) => {
  const { h, box } = chAddMenu(t);
  h.run('push')({ view: 'home' });
  assert.ok(box.classList.contains('hidden'), '切了视图菜单还浮在上面');
});

test('会话行的右键菜单，点别处也收得掉', (t) => {
  const h = boot({ fetch: () => ({ json: { conversations: [], unread: 0 } }) });
  t.after(() => h.close());
  const doc = h.window.document;
  const box = doc.getElementById('ch-addmenu');
  doc.getElementById('ch-convos').innerHTML =
    '<div class="ch-convo" data-crf="7" data-crn="小李" data-cpin="0" data-cmute="0"></div>';
  h.run('chRowMenu')(doc.querySelector('.ch-convo'));
  assert.ok(!box.classList.contains('hidden'), '右键菜单没出来');
  doc.body.click();
  assert.ok(box.classList.contains('hidden'), '右键菜单点别处收不掉');
});
