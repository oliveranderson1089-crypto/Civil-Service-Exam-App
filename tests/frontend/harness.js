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
  'checkSync', '_syncEditing', 'aiRunActions',
  'Ink', 'annCtx', 'annLocate', 'annPosOf', 'annRangeOf',
  'rvShow', 'rvSelect', 'RV_INTERVALS', 'RV_LNAME', 'rvQueue',
  'mdToHtml', 'mdSafeHref',
  'feedCard', 'addTagsFrom', 'draft', 'boardOptions',
  'slWords', 'slCountWords', 'slSetupAnswer',
  'loadYyMine',
];

function boot(opts = {}) {
  const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
  /* 按 index.html 里 <script> 的真实顺序拼起来 —— 顺序是行为的一部分，
     写死一份清单迟早跟 index.html 走散，所以直接从它里面读。
     正则要允许标签带属性：早加载的那个（data-early）也得算进来，
     漏掉它就是在测一个没有启动屏配色的应用。 */
  let srcs = [...html.matchAll(/<script src="(js\/[^"]+)"[^>]*><\/script>/g)].map(m => m[1]);
  if (!srcs.length) throw new Error('index.html 里没找到 js/*.js —— 拆分结构变了？');
  /* opts.only：只加载一部分脚本。给「只有首屏包时应用能不能起来」那条测试用——
     线上 core 是同步的、rest 是 defer 的，中间那一段时间里页面就是这个样子。
     不给这个选项的话，那种「core 顶层用了 rest 里的函数」的错永远测不出来，
     只会在手机上白屏一次。 */
  if (opts.only) srcs = srcs.filter(f => opts.only.includes(f));
  const js = srcs.map(f => `//# ${f}\n` + fs.readFileSync(path.join(ROOT, 'static', f), 'utf8')).join('\n;\n');
  const dom = new JSDOM(html, {
    // 默认 localhost；opts.url 可换成局域网 http 直连那种「不安全上下文」，
    // 有些能力（录音）只在安全上下文下才有，测提示语要用得上
    url: opts.url || 'http://localhost:8011/',
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

  /* ---- 记录 app.js 装了哪些事件（必须在 eval 之前挂钩子） ----
     拆模块唯一该保证的事就是「行为一个字节都没变」。而 app.js 有 377 条顶层执行语句，
     几乎全是绑事件 —— 它们是不是都还在、绑的顺序对不对，人眼盯不住。
     这里把 addEventListener 和 .onX= 两种形式都拦下来，拆分前后各拍一张快照对比。 */
  const bindings = [];
  const describe = (t) => {
    if (!t) return '?';
    if (t === w) return 'window';
    if (t === w.document) return 'document';
    if (t.id) return '#' + t.id;
    if (t.nodeName) return t.nodeName.toLowerCase() + (t.className ? '.' + String(t.className).split(/\s+/)[0] : '');
    return String(t);
  };
  const origAdd = w.EventTarget.prototype.addEventListener;
  w.EventTarget.prototype.addEventListener = function (type, fn, o) {
    bindings.push(describe(this) + ' @' + type);
    return origAdd.call(this, type, fn, o);
  };
  // .onclick = fn 这种不走 addEventListener，得单独拦 setter
  for (const prop of ['onclick', 'onchange', 'oninput', 'onsubmit', 'onkeydown', 'onload', 'onerror', 'onpointerdown']) {
    for (const proto of [w.HTMLElement.prototype, w.Element.prototype]) {
      const d = Object.getOwnPropertyDescriptor(proto, prop);
      if (!d || !d.set) continue;
      Object.defineProperty(proto, prop, {
        configurable: true, enumerable: d.enumerable, get: d.get,
        set(fn) { bindings.push(describe(this) + ' .' + prop); return d.set.call(this, fn); },
      });
      break;
    }
  }

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

  /* 壳注入的全局（window.__desktop / __desktopPlat 之类）。
     真实的桌面壳是在页面脚本之前注入的，所以这里也必须在 eval 之前赋值 ——
     放到后面的话，IS_DESKTOP 这种「加载时就定好」的常量已经算完了，测的就不是那回事。 */
  if (opts.window) Object.assign(w, opts.window);

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
    window: w, dom, calls, toasts, logs, bindings,
    T: w.__T,
    run: (code) => w.__run(code),      // 在 app.js 自己的作用域里执行

    /* 把 jsdom 那边的值搬回本 realm。
       jsdom 里造的数组/对象，原型是它自己那套 Object/Array —— assert.deepStrictEqual
       会以「结构相同但原型不是同一引用」失败，报出来的两边看着一模一样，很费解。
       断言结构时一律先过这个（踩过两次了：aichat 的 toast、notes 的 draft.tags）。 */
    plain: (code) => JSON.parse(JSON.stringify(w.__run(code))),

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
