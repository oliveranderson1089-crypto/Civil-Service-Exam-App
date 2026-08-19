/* 在 jsdom 里把真正的 static/admin.html + js/admin-*.js 跑起来。
 *
 * 后台是独立页面（不走 index.html 那套 bundle），所以它有自己的一份 harness。
 * 和主 harness 同一个道理：加载的是真文件，少一个 id、写错一个选择器都会当场露馅——
 * 后台这几页全是「渲染 + 点一下就发请求」，正是人眼最盯不住的那类代码。
 *
 * 内联脚本（$ / esc / toast / adminConfirm 和各页的 load*）必须和分栏脚本在**同一个
 * eval** 里：那是 admin.html ↔ js/admin-*.js 的真实关系（全局脚本共用一个作用域），
 * 分两次 eval 的话第二次根本看不见第一次的东西。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../..');

/* 内联脚本启动时会去拉用户列表、AI 设置等。测试关心的不是这些，
   但缺了它们会在 render 里炸掉，所以给一份「结构对、内容空」的兜底。 */
const BASE_STUBS = {
  '/api/me': { username: 'tester' },
  '/api/admin/users': { users: [] },
  '/api/admin/ai': { base: '', model: '', model_pro: '', has_key: false },
  '/api/admin/registration': { open: true, invite_code: '' },
  '/api/admin/asr': {},
  '/api/admin/services': { services: [], oplog: [] },
};

function bootAdmin(opts = {}) {
  const html = fs.readFileSync(path.join(ROOT, 'static/admin.html'), 'utf8');
  const dom = new JSDOM(html, { url: 'http://localhost:8011/admin', runScripts: 'outside-only' });
  const w = dom.window;
  w.scrollTo = () => {};
  w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });

  const calls = [];
  w.fetch = async (url, o) => {
    const u = String(url);
    calls.push({ url: u, method: (o && o.method) || 'GET', body: o && o.body ? JSON.parse(o.body) : null });
    let r = opts.fetch ? opts.fetch(u, o) : undefined;
    if (r === undefined) {
      const hit = Object.keys(BASE_STUBS).find(k => u.split('?')[0] === k);
      r = hit ? { json: BASE_STUBS[hit] } : { json: {} };
    }
    if (r instanceof Error) throw r;
    const status = r.status || 200;
    return {
      status, ok: status >= 200 && status < 300,
      headers: { get: () => 'application/json' },
      json: async () => (r.json !== undefined ? r.json : {}),
    };
  };

  const toasts = [];
  const confirms = [];
  w.__toasts = toasts;
  w.__confirms = confirms;
  w.console = { warn: () => {}, error: () => {}, debug: () => {}, log: () => {} };

  // admin.html 里的内联脚本 + 它随后加载的分栏脚本，按真实顺序拼
  const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n;\n');
  const srcs = [...html.matchAll(/<script src="(js\/[^"]+)"><\/script>/g)].map(m => m[1]);
  if (!srcs.length) throw new Error('admin.html 里没找到 js/*.js —— 结构变了？');
  const only = opts.only ? srcs.filter(f => opts.only.includes(f)) : srcs;
  const js = inline + '\n;\n' + only
    .map(f => `//# ${f}\n` + fs.readFileSync(path.join(ROOT, 'static', f), 'utf8')).join('\n;\n');

  /* toast / adminConfirm 都是内联脚本里的函数声明，得在作用域内改绑——
     覆盖 window.toast 没用，代码调的是那个内部名字。 */
  const tail = `
    ;toast = (m, e) => window.__toasts.push({ msg: String(m), err: !!e });
    ;adminConfirm = (text, title) => {
       window.__confirms.push({ text: String(text), title: title || '' });
       return Promise.resolve(window.__confirmAnswer !== false);
     };
    ;window.__run = function (code) { return eval(code); };
  `;
  w.eval(js + tail);

  return {
    window: w, dom, calls, toasts, confirms,
    run: (code) => w.__run(code),
    /* 等页面自己那串启动请求跑完（内联脚本的 load / loadAI / loadSvc…）。
       不等的话，测试结束时 window 已经 close 了，那些还没落地的 promise 会摸到
       一个 undefined 的 document，报成一堆跟被测代码无关的 unhandledRejection。 */
    async settle(n = 8) { for (let i = 0; i < n; i++) await new Promise(r => setTimeout(r, 0)); },
    $: (sel) => w.document.querySelector(sel),
    all: (sel) => [...w.document.querySelectorAll(sel)],
    text: (sel) => (w.document.querySelector(sel) || {}).textContent || '',
    answerConfirm(v) { w.__confirmAnswer = v; },
    close() { dom.window.close(); },
  };
}

module.exports = { bootAdmin };
