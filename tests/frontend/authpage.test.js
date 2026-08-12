/* 登录 / 注册 / 找回密码 三页的天光底。
 *
 * 这一层出错的样子都是「不报错、只是看着不对」，而这三页平时没人跑测试：
 *
 *   1) **脚本排在 #dl-sky 前面** —— dlPaintAuth 找不到底，第一帧退回 CSS 那张
 *      静态晨光底；白天看不出来，夜里就是米白底压着一屏深色表单。
 *   2) **夜里字看不见** —— 卡片是半透明的，颜色由脚本按时刻给。要是卡片翻成了
 *      墨色而字色没跟着翻（或反过来），就是深字压深底。
 *   3) **哪一页漏改** —— 三页各自一份 HTML，改了登录页忘了注册页，风格当场分叉。
 *
 * 跑：node --test tests/frontend/authpage.test.js
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../..');
const PAGES = ['login.html', 'register.html', 'forgot.html'];
const read = (f) => fs.readFileSync(path.join(ROOT, 'static', f), 'utf8');

/* 把一页真的跑起来：HTML 是真文件，脚本按页面里的真实顺序 eval。
   （jsdom 不下载外链脚本，所以这里照着标签顺序自己喂。） */
function boot(page, hour) {
  const html = read(page);
  const dom = new JSDOM(html, { url: 'http://localhost:8011/' + page.replace('.html', ''),
                                runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  w.HTMLCanvasElement.prototype.getContext = () => null;   // jsdom 的原生实现只会抛「未实现」，噪音大
  const srcs = [...html.matchAll(/<script src="(js\/[^"]+)"><\/script>/g)].map(m => m[1]);
  assert.deepStrictEqual(srcs, ['js/daylight.js', 'js/auth.js'], `${page} 引的脚本不对`);
  w.eval(srcs.map(f => read(f)).join('\n;\n'));
  if (hour != null) w.eval(`dlPaintAuth(${hour})`);
  return { w, d: w.document, close: () => w.close() };
}

// 相对亮度（WCAG），用来核对字和卡片的对比度
function lum(c) {
  const [r, g, b] = (c.match(/-?\d+(\.\d+)?/g) || []).map(Number);
  return [r, g, b].map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); })
    .reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
}
const ratio = (a, b) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);
const hex2rgb = (h) => `rgb(${parseInt(h.slice(1, 3), 16)},${parseInt(h.slice(3, 5), 16)},${parseInt(h.slice(5, 7), 16)})`;

test('三页都接了天光底，且脚本排在底后面（早一步就找不到 #dl-sky）', () => {
  PAGES.forEach((p) => {
    const html = read(p);
    assert.match(html, /<link rel="stylesheet" href="auth.css">/, `${p} 没引 auth.css`);
    assert.match(html, /<div id="dl-sky"/, `${p} 没有天光底`);
    assert.ok(html.indexOf('<div id="dl-sky"') < html.indexOf('<script src="js/daylight.js">'),
      `${p} 的 daylight.js 排在 #dl-sky 前面：它一执行就找 #dl-sky，找不到就退回静态兜底底`);
    // 各页自己那段 <style> 已经并进 auth.css：留着就是第二套色，改一处漏一处
    assert.doesNotMatch(html, /<style>/, `${p} 里还留着内联 <style>，会和 auth.css 冲突`);
    assert.doesNotMatch(html, /linear-gradient\(135deg,#1a6fb5/, `${p} 还在用原来那块死蓝底`);
  });
});

test('底和卡片都按时刻画：早上是宣纸浅底深字，夜里翻成墨色玻璃浅字', (t) => {
  const day = boot('login.html', 8); t.after(() => day.close());
  const night = boot('login.html', 23); t.after(() => night.close());
  const val = (h, k) => h.d.body.style.getPropertyValue(k);
  const sky = (h) => h.d.getElementById('dl-sky').style.backgroundImage;

  assert.ok(sky(day) && sky(night), '天光底没被画出来');
  assert.notStrictEqual(sky(day), sky(night), '早晚是同一张底 —— 那就没跟着时刻走');
  // 早上：深字压浅卡；夜里：浅字压深卡。两边都得读得清
  const dayInk = hex2rgb(val(day, '--dl-ink')), dayCard = val(day, '--dl-card-solid');
  const nightInk = hex2rgb(val(night, '--dl-ink')), nightCard = val(night, '--dl-card-solid');
  assert.ok(lum(dayInk) < lum(dayCard), '早上不是深字压浅卡');
  assert.ok(lum(nightInk) > lum(nightCard), '夜里卡片翻黑了字没跟着翻 —— 深字压深底');
  assert.ok(ratio(dayInk, dayCard) >= 4.5, `早上字和卡片只有 ${ratio(dayInk, dayCard).toFixed(1)}:1`);
  assert.ok(ratio(nightInk, nightCard) >= 4.5, `夜里字和卡片只有 ${ratio(nightInk, nightCard).toFixed(1)}:1`);
});

test('星子和晨晕各归各的时刻（夜里有星、早上有晕）', (t) => {
  const day = boot('login.html', 8); t.after(() => day.close());
  const night = boot('login.html', 23); t.after(() => night.close());
  const op = (h, id) => +h.d.getElementById(id).style.opacity;
  assert.ok(op(night, 'dl-stars') > 0.9, '夜里没有星子');
  assert.strictEqual(op(day, 'dl-stars'), 0, '早上冒出星子了');
  assert.ok(op(day, 'dl-bloom') > 0.9, '早上没有晨晕');
  assert.ok(op(night, 'dl-hill') > 0, '夜里没有山脊');
});

test('状态栏颜色跟着天光走（不改就是米白底顶一条深蓝条）', (t) => {
  const h = boot('login.html', 8); t.after(() => h.close());
  const meta = () => h.d.querySelector('meta[name="theme-color"]').getAttribute('content');
  const morning = meta();
  assert.notStrictEqual(morning, '#1a6fb5', 'theme-color 还是原来那块死蓝');
  h.w.eval('dlPaintAuth(23)');
  assert.notStrictEqual(meta(), morning, '状态栏颜色早晚一个样');
});

test('用户自己传的壁纸优先于天光底', (t) => {
  const html = read('login.html');
  const dom = new JSDOM(html, { url: 'http://localhost:8011/login', runScripts: 'outside-only' });
  const w = dom.window; t.after(() => w.close());
  w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  w.HTMLCanvasElement.prototype.getContext = () => null;   // jsdom 的原生实现只会抛「未实现」，噪音大
  w.localStorage.setItem('wallLogin', 'https://example.com/a.jpg');
  w.eval(read('js/daylight.js') + '\n;\n' + read('js/auth.js'));
  assert.ok(w.document.body.classList.contains('has-wall'), '缓存里有壁纸却没挂 has-wall');
  assert.match(w.document.body.style.getPropertyValue('--wall'), /example\.com/);
  // 盖住天光底这件事在 auth.css 里，一并钉住
  assert.match(read('auth.css'), /body\.has-wall #dl-sky\s*{\s*display:\s*none/,
    'auth.css 里没有「有壁纸就盖掉天光底」那条');
});

test('注册/找回两页跟登录页共用同一套卡片类名（漏改就风格分叉）', (t) => {
  ['register.html', 'forgot.html'].forEach((p) => {
    const h = boot(p, 23); t.after(() => h.close());
    assert.ok(h.d.querySelector('.auth-box'), `${p} 没有卡片`);
    assert.ok(h.d.querySelector('.auth-logo'), `${p} 没有方章`);
    assert.ok(h.d.body.style.getPropertyValue('--dl-card'), `${p} 的卡片颜色没被脚本画上`);
  });
});
