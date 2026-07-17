/* 在 jsdom 里把真正的 static/app.js 跑起来，供测试调用它的内部函数。
 *
 * 为什么不测抠出来的片段：那样测的是副本，改了原件测试照样绿。这里加载的是
 * 真文件，index.html 也是真的 —— 少一个 DOM 元素、写错一个 id 都会当场露馅。
 *
 * app.js 是全局脚本（<script src="app.js">，非 module），它的 const/function 都在
 * eval 作用域里，外面拿不到。所以在同一个 eval 末尾把要测的符号挂到 window.__T。
 * 这是唯一的侵入，且只发生在测试里——生产的 app.js 一个字节没动。
 *
 * 跑：node --test tests/frontend/
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../..');

// 想在测试里访问的内部符号。加测试要用新符号时，往这儿加名字。
const EXPORTS = [
  'lsSet', 'lsGet', 'lsDel', '_lsWarned',
  'SYNC_REFRESH', 'saveDoc', 'matSave', 'matLoad', 'matStrokes', 'matKey',
  'wrSwitch', 'api', 'esc', 'fmtSize', 'fmtTime', 'composing',
  'checkSync', '_syncEditing',
];

function boot(opts = {}) {
  const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
  const js = fs.readFileSync(path.join(ROOT, 'static/app.js'), 'utf8');
  const dom = new JSDOM(html, {
    url: 'http://localhost:8011/',
    runScripts: 'outside-only',
    pretendToBeVisual: true,
  });
  const w = dom.window;

  // jsdom 没有的浏览器能力，补最小实现
  w.matchMedia = () => ({ matches: !!opts.mobile, addEventListener() {}, removeEventListener() {},
                          addListener() {}, removeListener() {} });
  w.scrollTo = () => {};
  if (!w.HTMLCanvasElement.prototype.getContext) w.HTMLCanvasElement.prototype.getContext = () => null;

  // 记录所有发出去的请求 + 可编程的响应
  const calls = [];
  w.fetch = async (url, o) => {
    calls.push({ url: String(url), method: (o && o.method) || 'GET', body: o && o.body });
    const r = opts.fetch ? opts.fetch(String(url), o) : {};
    if (r instanceof Error) throw r;
    const status = r.status || 200;
    return {
      status, ok: status >= 200 && status < 300,
      headers: { get: () => 'application/json' },
      json: async () => (r.json !== undefined ? r.json : {}),
    };
  };

  // toast 是给用户看的提示，console 是后台失败留的痕 —— 两者测试都要能断言。
  const toasts = [];
  const logs = { warn: [], error: [], debug: [] };
  w.__toasts = toasts;
  w.console = {
    warn: (...a) => logs.warn.push(a.join(' ')),
    error: (...a) => logs.error.push(a.join(' ')),
    debug: (...a) => logs.debug.push(a.join(' ')),
    log: () => {},
  };

  // 必须跟 app.js 在**同一个 eval** 里：它的 const/function 都在那个作用域内，
  // 分两次 eval 的话第二次根本看不见第一次的东西。
  // toast 同理 —— 代码里调的是内部的 function toast，覆盖 window.toast 没用，
  // 得在作用域内改绑（函数声明可重新赋值）。
  const tail = `
    ;toast = (m, e) => window.__toasts.push({ msg: String(m), err: !!e });
    ;window.__T = { ${EXPORTS.map(n => `get ${n}() { return typeof ${n} !== 'undefined' ? ${n} : undefined; }`).join(', ')} };
    /* 在 app.js 自己的作用域里跑代码：测试要能读写它的内部状态（matKey / matStrokes 之类）。
       必须是这里的直接 eval —— window.eval 是另一个作用域，看不见这些变量。 */
    ;window.__run = function (code) { return eval(code); };
  `;
  w.eval(js + tail);

  return {
    window: w, dom, calls, toasts, logs,
    T: w.__T,
    run: (code) => w.__run(code),      // 在 app.js 自己的作用域里执行

    /* 把 localStorage 变成「满的」。
       只能改 Storage.prototype —— jsdom 的 Storage 实例上覆盖不了 setItem
       （拿 Proxy 拦了写），测试不必关心这个细节，收在这儿。 */
    fillStorage() {
      const orig = w.Storage.prototype.setItem;
      w.Storage.prototype.setItem = function () {
        const e = new Error('quota exceeded');
        e.name = 'QuotaExceededError';
        throw e;
      };
      return () => { w.Storage.prototype.setItem = orig; };   // 调它就腾出空间
    },
    breakStorage() {                    // 隐私模式：localStorage 整个不可用
      const orig = w.Storage.prototype.getItem;
      w.Storage.prototype.getItem = function () { throw new Error('SecurityError'); };
      return () => { w.Storage.prototype.getItem = orig; };
    },

    // app.js 里 setInterval 会吊住事件循环，测完要关
    close() { try { dom.window.close(); } catch (_) { /* 已关 */ } },
  };
}

module.exports = { boot, ROOT };
