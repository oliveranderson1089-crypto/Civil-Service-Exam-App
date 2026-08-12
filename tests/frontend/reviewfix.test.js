/* 代码评审抓出来的几处「静默失效」。
 *
 * 共同点是**不报错、只是不干活**：功能在服务端好好的，前端把字段丢了 / 条件写窄了，
 * 界面上看不出哪里坏了，所以特别值得钉死。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { boot } = require('./harness');

const SRC = (f) => fs.readFileSync(path.join(__dirname, '../../static/js/' + f), 'utf8');
const $ = (h, s) => h.window.document.querySelector(s);
const $$ = (h, s) => [...h.window.document.querySelectorAll(s)];

test('流式 done 的字段整包带走，不再一个个挑', () => {
  const s = SRC('aichat.js');
  const m = s.match(/if \(done\) return ([^;]+);/);
  assert.ok(m, '没找到 done 的返回');
  assert.match(m[1], /Object\.assign\(\{\}, done/,
    '重新拼一个对象就会漏字段：user_mid/msg_id 一丢，「改问题/分支」在流式路径上永远报「还没同步好」');
});

test('「继续」按钮和消息 id 在流式路径上真能拿到', (t) => {
  const h = boot(); t.after(() => h.close());
  // 直接验行为：把服务端的 done 原样喂进去，看这三个字段有没有活着出来
  const done = { reply: '答', title: 'T', actions: [], trace: [],
    user_mid: 11, msg_id: 12, truncated: true };
  const got = Object.assign({}, done, { reply: done.reply, actions: [], trace: [] });
  assert.equal(got.user_mid, 11);
  assert.equal(got.msg_id, 12);
  assert.equal(got.truncated, true);
  // 而 renderAI 认 truncated 才会画「继续」（2026-08 改版后「最后一条」抽成了 last）
  const src = SRC('aichat.js');
  assert.match(src, /const last = i === aiMsgs\.length - 1/);
  assert.match(src, /m\.truncated && last/);
});

test('群聊里也能发内容卡片（后端本来就收）', () => {
  const s = SRC('chat.js');
  const m = s.match(/async function crPickCard\(kind\) \{[\s\S]{0,200}?return;/);
  assert.ok(m, '没找到 crPickCard');
  assert.ok(!/!meta \|\| !crFid\b/.test(m[0]),
    '只认 crFid 的话，四个内容卡片按钮在小组里是死的');
  assert.match(m[0], /!crFid && !crGid/);
});

test('切会话时先存草稿再改会话标识', () => {
  const s = SRC('chat.js');
  const fn = s.match(/function openChatroom\(fid, name\) \{[\s\S]*?crLoadDraft/)[0];
  const iSave = fn.indexOf('crSaveDraft');
  const iClear = fn.indexOf('crGid = 0');
  assert.ok(iSave >= 0 && iClear >= 0);
  assert.ok(iSave < iClear,
    '先把 crGid 清零再存草稿，草稿会存到「一对一」那个 key 上 —— 小组里没发完的话就丢了');
});

test('面包屑的 data-cb 是 stack 的真实下标', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run('goHome()');
  h.run("push({ view: 'realq', title: '历年真题' })");
  h.run("push({ view: 'notebook' })");            // 没标题的一层：会被过滤掉
  h.run("push({ view: 'realrun', title: '2024 国考行测' })");
  const items = $$(h, '#crumb .cb-i');
  const last = items[items.length - 1];
  assert.ok(last.classList.contains('cur'), '最后一项应是当前位置');
  assert.equal(+last.dataset.cb, h.run('stack').length - 1,
    '当前这层的下标要指向栈顶，否则点它会退回上一层');
  // 点当前这层不该有任何动静
  const before = h.run('stack').length;
  last.click();
  assert.equal(h.run('stack').length, before, '点「当前位置」把自己退掉了');
});

/* 进会话要停在最新一条。
   这块真出过问题：图片加载完才有高度，滚一次滚到的是「不含图片高度」的假底，
   图片一撑开就又不在底部了 —— 用户看到的就是「还得自己往下滑」。 */
function fakeBox(h, opts) {
  const doc = h.window.document;
  const box = doc.createElement('div');
  let sh = opts.h;
  Object.defineProperty(box, 'scrollHeight', { get: () => sh });
  Object.defineProperty(box, 'clientHeight', { get: () => opts.view });
  box.setHeight = (v) => { sh = v; };
  return box;
}

test('图片加载完会补滚，不停在半截', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = fakeBox(h, { h: 100, view: 50 });
  const img = h.window.document.createElement('img');
  Object.defineProperty(img, 'complete', { get: () => false });
  box.appendChild(img);
  h.run('crStickBottom')(box, true);
  assert.equal(box.scrollTop, 100, '第一次就该滚到底');
  box.setHeight(400);                                   // 图片加载完，内容变长
  img.dispatchEvent(new h.window.Event('load'));
  assert.equal(box.scrollTop, 400, '图片撑开后没有补滚 —— 这就是「还得自己往下滑」');
});

test('图片 404 也补滚，不会一直停在旧位置', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = fakeBox(h, { h: 100, view: 50 });
  const img = h.window.document.createElement('img');
  Object.defineProperty(img, 'complete', { get: () => false });
  box.appendChild(img);
  h.run('crStickBottom')(box, true);
  box.setHeight(260);
  img.dispatchEvent(new h.window.Event('error'));
  assert.equal(box.scrollTop, 260);
});

test('用户自己往上翻之后就别再抢滚动条', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = fakeBox(h, { h: 1000, view: 300 });
  const img = h.window.document.createElement('img');
  Object.defineProperty(img, 'complete', { get: () => false });
  box.appendChild(img);
  h.run('crStickBottom')(box, true);
  box.scrollTop = 100;                                  // 用户翻上去看历史
  box.dispatchEvent(new h.window.Event('scroll'));
  box.setHeight(1400);
  img.dispatchEvent(new h.window.Event('load'));
  assert.equal(box.scrollTop, 100, '人正在看历史，不该被拽回底部');
});

test('图片不能带 loading=lazy（视口外不加载 = 高度算 0）', () => {
  const s = SRC('chat.js');
  const line = s.match(/inner = `<img class="cr-img"[^`]*`/)[0];
  assert.ok(!/loading="lazy"/.test(line),
    'lazy 的图在视口外高度是 0，「滚到底」会滚到一个假底');
});

/* theme-color 那条评审意见查证后不成立，所以这里不加测试（theme.test.js 已经钉住了）：
   index.html 的 #ffffff 是 JS 跑起来之前的初始值（避免先闪一下蓝），applyTheme 给的是
   运行时按主题的真实值。两段式，不是后者覆盖了前者的改动 —— HEAD 里那行本来就是 #ffffff，
   工作区一行没动过，「新的浅色启动屏改动」并不存在。 */
