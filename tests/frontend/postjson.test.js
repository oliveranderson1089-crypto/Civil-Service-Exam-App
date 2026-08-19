/* postJSON：api() 的第二个参数是 **fetch options，不是请求体**。
 *
 * 写成 api(url, { 字段 }) 会发出一个带无效选项的 GET，服务端回 405，
 * 前端只看到「请求失败」三个字 —— 后端日志里连这次调用都不算异常。
 * 这个坑一次踩中五处（备考方向切换、整卷交卷、专项练交卷、主观题批改、裁决），
 * 所以既封了 postJSON，也把「写 POST 的地方不许直接把数据当 options 传」钉在这儿。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { boot, ROOT } = require('./harness');

test('postJSON 发的是带 JSON 体的 POST', (t) => {
  const calls = [];
  const h = boot({ fetch: (url, o) => { calls.push({ url, o }); return { json: { ok: 1 } }; } });
  t.after(() => h.close());
  h.run(`postJSON('/api/x', { a: 1 });`);
  // boot() 自己会打几个启动接口，按 url 挑出我们这条，别用下标
  const c = calls.find(x => x.url === '/api/x');
  assert.ok(c, '请求没发出去');
  assert.strictEqual(c.o.method, 'POST');
  assert.match(c.o.headers['Content-Type'], /application\/json/);
  assert.strictEqual(c.o.body, '{"a":1}');
});

test('postJSON 允许调用方补 options（超时之类）', (t) => {
  const calls = [];
  const h = boot({ fetch: (url, o) => { calls.push({ url, o }); return { json: {} }; } });
  t.after(() => h.close());
  h.run(`postJSON('/api/x2', {}, { timeoutMs: 5000 });`);
  const c = calls.find(x => x.url === '/api/x2');
  assert.ok(c && c.o.method === 'POST', '补 options 之后 method 被覆盖了');
});

test('没有人再把数据直接当 fetch options 传', () => {
  // 判据：api('…', { … }) 里若既没有 method 也没有 body/signal/headers，就是踩了这个坑
  const bad = [];
  for (const f of fs.readdirSync(path.join(ROOT, 'static/js'))) {
    if (!f.endsWith('.js')) continue;
    const src = fs.readFileSync(path.join(ROOT, 'static/js', f), 'utf8');
    const re = /\bapi\(\s*(?:'[^']*'|`[^`]*`)\s*,\s*\{([^{}]*)\}/g;
    let m;
    while ((m = re.exec(src))) {
      const opt = m[1];
      if (!/\b(method|body|signal|headers|timeoutMs)\b/.test(opt)) {
        bad.push(`${f}: api(…, {${opt.trim().slice(0, 46)}…})`);
      }
    }
  }
  assert.deepStrictEqual(bad, [], '这些调用把数据当成了 fetch options，应该用 postJSON：\n  ' + bad.join('\n  '));
});
