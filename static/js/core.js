/* 地基：DOM 选择器 / api / toast / 转义 / 本地存储 / 图标 / 环境判断
 *
 * 由 app.js 按它自己的区段边界切出（原 L1-156）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global KB, lbInvalidate */

'use strict';
const $ = (s) => document.querySelector(s);
/* o.timeoutMs：可选的请求超时（毫秒）。**不设默认值** —— 上传、AI 生成这类接口本来就慢，
   给全局加超时会误杀。只在「用户点一下就该马上有反应」的接口上显式开（如专项练出题）：
   没有它的话，服务端一旦卡住，前端既不报错也不结束，表现就是「点了没反应」。 */
/* 安卓壳 minSdk21，系统 WebView 可能停留在很老的版本：AbortController 要 Chrome 66、
   Promise.prototype.finally 要 Chrome 63。两者都得先探再用，**探不到就退回无超时的老行为** ——
   超时只是锦上添花，为它把整个 api() 打崩（连出题按钮都点不动）得不偿失。 */
const CAN_ABORT = typeof AbortController !== 'undefined';
/* 发一个 JSON POST。**api() 的第二个参数是 fetch options，不是请求体** ——
   写成 api(url, {字段}) 会发成一个带无效选项的 GET，服务端回 405，
   前端只看到「请求失败」三个字，查半天。这个坑我踩过一次（备考方向切换、
   整卷交卷、专项练交卷、主观题批改、裁决五处全中），所以封一层。 */
const postJSON = (u, data, o) => api(u, Object.assign({
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data || {}),
}, o || {}));

const api = (u, o) => {
  const ms = o && o.timeoutMs;
  let timer = 0;
  if (ms) {
    o = Object.assign({}, o);
    delete o.timeoutMs;
    if (CAN_ABORT) {
      const ctl = new AbortController();
      timer = setTimeout(() => ctl.abort(), ms);
      o.signal = ctl.signal;
    }
  }
  const done = (v) => { if (timer) clearTimeout(timer); return v; };
  return fetch(u, o).then(async r => {
    if (r.status === 401) { location.href = '/login'; throw new Error('未登录'); }
    const ct = r.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '请求失败');
      return d;
    }
    if (!r.ok) throw new Error('请求失败');
    return r;
  }).then(done, e => {
    done();
    if (e.name === 'AbortError') throw new Error('服务端响应太慢，已中断。稍后再试一次');
    throw e;
  });
};
/* ---- 异常 → 给人看的一句话 ----
   全项目 192 处写的是 toast(e.message, true)。于是接口或渲染一出岔子，
   用户看到的是「Cannot read properties of undefined (reading 'length')」——
   英文、技术黑话，而且不告诉他此刻能做什么。（2026-08-13 实机复现两次。）

   这里按**这条 message 是不是写给人看的**分两类：
   · 我们自己抛的（api() 里那几句、后端 error 字段）本来就是中文，原样放行；
   · 运行时异常（TypeError / ReferenceError / …）是 bug 不是状况，对用户只说
     「这一步没能完成」，原文进 console.error 留给排查 —— 丢掉原文就没法查了。

   断网单独认一条：fetch 断网抛的是 TypeError: Failed to fetch，
   它归到第二类会变成「已记录」，而用户其实只要连上网就好了。 */
function errMsg(e, fallback) {
  const dflt = fallback || '没能完成，再试一次';
  if (!e) return dflt;
  const m = String(e.message || e);
  if (/failed to fetch|networkerror|load failed/i.test(m)) return '网络没连上，检查一下网络再试';
  if (e instanceof TypeError || e instanceof ReferenceError
      || e instanceof RangeError || e instanceof SyntaxError) {
    try { console.error('[ui]', e); } catch (_) { /* 没有 console 就算了 */ }
    return fallback || '这一步没能完成，刷新一下再试（详情已记到控制台）';
  }
  return m || dflt;
}
window.errMsg = errMsg;

/* 列表容器的三态。以前只有「加载中」是设计过的（tabviews.js 的 TV_SK 骨架屏），
   空和出错各写各的，多数地方干脆什么都不画 —— 于是接口一挂就是一整片空白，
   分不清「还没加载完」「本来就没有」和「坏了」。

   出错那一态**一定要带重试**：没有重试的错误提示等于让人去刷新整个应用。

   这两个函数返回的是 HTML 字符串（和全项目其余渲染一致，直接塞 innerHTML）。
   按钮的回调存在一张只增不复用的表里：复用下标的话，一个重画频繁的列表
   会让旧按钮指到别人的回调上 —— 那种错最难查。一次错误渲染一个闭包，量可以忽略。 */
const _uiActs = new Map();
let _uiSeq = 0;
function _uiAct(fn) { const k = 'a' + (++_uiSeq); _uiActs.set(k, fn); return k; }
document.addEventListener('click', e => {
  const b = e.target.closest('[data-uigo]');
  if (!b) return;
  const fn = _uiActs.get(b.dataset.uigo);
  if (fn) fn();
});
function uiEmpty(text, actText, fn) {
  return `<div class="ui-state ui-empty"><span class="ui-state-t">${esc(text)}</span>`
    + (actText && fn ? `<button class="ui-state-go" data-uigo="${_uiAct(fn)}">${esc(actText)}</button>` : '')
    + '</div>';
}
function uiError(err, fn) {
  return `<div class="ui-state ui-err"><span class="ui-state-t">${esc(errMsg(err))}</span>`
    + (fn ? `<button class="ui-state-go" data-uigo="${_uiAct(fn)}">重试</button>` : '')
    + '</div>';
}
window.uiEmpty = uiEmpty;
window.uiError = uiError;

/* 中文输入法正在组字时，回车是「确认候选词」，不是「提交」。
   所有回车处理都必须先问一句 composing(e)，否则 fcitx/搜狗打中文时会被打断，
   表现就是「只打得出英文字母、候选框弹不出来」。 */
const composing = (e) => e.isComposing || e.keyCode === 229;
const IN_APP = navigator.userAgent.includes('GongkaoApp');
/* 桌面版（原生 GTK 壳）会注入 window.__desktop / __desktopVer；普通浏览器里没有 */
const IS_DESKTOP = !!window.__desktop;
const DESKTOP_VER = String(window.__desktopVer || '');
// 手机端：安卓壳内 或 窄屏。手机端与网页端使用不同的「小记」界面
const IS_MOBILE = IN_APP || window.matchMedia('(max-width:760px)').matches;
document.body.classList.toggle('mobile-ui', IS_MOBILE);
/* 平板：装了 App 就一律算手机（IS_MOBILE 里 IN_APP 直接为真）。这对底部标签栏那套是对的，
   对「AI 面板能不能拖大/全屏」却是错的 —— 平板有的是地方，却连停靠手柄都看不到。
   所以**不动 IS_MOBILE**（它是全站开关，底部标签栏、抽屉、录音都挂在上面），
   另给一个只按尺寸算的判定，谁需要谁用。

   按**短边**而不是宽度：手机横过来宽度也能到 900，那不叫平板；平板短边普遍 600 起。
   而且它是**活的** —— IS_MOBILE 在加载时就算死了，平板一转屏、网页端一拖窗口就不准了。 */
const TABLET_MIN = 600;
const isTablet = () => Math.min(innerWidth, innerHeight) >= TABLET_MIN;
function syncTabletUi() { document.body.classList.toggle('tablet-ui', IS_MOBILE && isTablet()); }
syncTabletUi();
addEventListener('resize', syncTabletUi);
addEventListener('orientationchange', syncTabletUi);
const PAGE_SIZE = 5;

window.toast = toast;   // 桌面壳出错时要能弹提示
function toast(msg, err) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (err ? ' err' : '');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.add('hidden'), 2300);
}
const esc = (s) => (s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* ---- 本地存储：写失败必须看得见 ----
   localStorage 的坑不是理论上的：2026-07-16 批注笔迹把 5MiB 配额撑爆，setItem 抛
   QuotaExceededError，被 catch(_){} 吞掉，用户画了一整页笔迹全丢、界面上还好好的
   （画布内存里还在，刷新才发现没了）。见 ebf9da5。

   全项目的 localStorage 写入都走这两个函数：
   - 满了就告诉用户，别装作存上了
   - 同一把钥匙只吵一次，免得每笔一弹
   - 返回 false 让调用方能自己决定要不要降级 */
const _lsWarned = new Set();
function lsSet(key, val) {
  try {
    localStorage.setItem(key, val);
    _lsWarned.delete(key);
    return true;
  } catch (e) {
    const quota = e && (e.name === 'QuotaExceededError' || e.name === 'NS_ERROR_DOM_QUOTA_REACHED' || e.code === 22);
    console.warn('[存储] 写入失败 %s：%s', key, (e && e.name) || e);
    if (!_lsWarned.has(key)) {
      _lsWarned.add(key);
      toast(quota ? '本地存储已满，这次没保存上' : '本地存储写入失败，这次没保存上', true);
    }
    return false;
  }
}
function lsGet(key, dflt = null) {   // 默认给 null 而不是 undefined：与原生 getItem 等价
  try {                               // （+null 是 0、+undefined 是 NaN，差一点就不等价了）
    const v = localStorage.getItem(key);
    return v === null ? dflt : v;
  } catch (e) {                       // 隐私模式/禁用 cookie 时 localStorage 本身会抛
    console.warn('[存储] 读取失败 %s：%s', key, (e && e.name) || e);
    return dflt;
  }
}
function lsDel(key) {
  try { localStorage.removeItem(key); return true; }
  catch (e) { console.warn('[存储] 删除失败 %s：%s', key, (e && e.name) || e); return false; }
}
/* 复制文字到剪贴板。两条路都要留：
   navigator.clipboard 在桌面壳（WebKitGTK）里会被拒（报 user denied，其实是不支持），
   非 https 的局域网访问下也没有。退回 execCommand 那套老办法。
   返回是否成功 —— 提示语交给调用方，各处措辞不一样。 */
async function copyText(text) {
  if (!text) return false;
  try { await navigator.clipboard.writeText(text); return true; } catch (_) { /* 下面兜底 */ }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
  ta.remove();
  return ok;
}
function fmtSize(n) {
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(1) + ' MB';
}
function fmtTime(s) { return (s || '').slice(5, 16); }
/* ---- 「最近打开」打点 ----
   「库」首屏那张列表读的就是这些记录（后端 mods/tabhome.py + lib_visits 表）。
   在这之前它读的是各表的 updated_at/created_at，也就是「最近新增/改过」——
   云盘文件传上去时间就定死了，翻一下午也不会动一格。

   规矩是：**只在真的把一样东西打开了的地方调**。点进云盘、进资料库列表都不算，
   那只是走到了柜子跟前；不然这张表最后只会记着六个容器的名字。

   三条都是为了「打点绝不能碍着正事」——调用它的下一句往往就是渲染：
   · 不 await：多等一个来回对用户没有任何好处；
   · 吞掉所有异常：接口挂了、离线了，最坏只是这次没记上，不该为它弹红条；
   · 同一样东西 1 秒内只发一次：有的入口会连着触发两次（点一下、返回栈恢复时再画一次）。 */
const _touched = new Map();
function libTouch(kind, ref, extra) {
  if (!kind || ref == null || ref === '') return;
  const k = kind + ':' + ref, now = Date.now();
  if (now - (_touched.get(k) || 0) < 1000) return;
  _touched.set(k, now);
  api('/api/lib/touch', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, ref: String(ref), extra: extra || '' }),
  }).catch(() => {});
  // 「库」那一页缓存 20 秒，而打开一样东西恰恰会改变它那张列表。
  // 定义在 tabviews.js（同一个 bundle 里，但 core.js 先加载），所以探一下再调。
  if (typeof lbInvalidate === 'function') lbInvalidate();
}
/* 从 paste 事件里掏出文件。截图走 items（有些浏览器不进 files），复制的文件走 files ——
   两条都得看，只看一条就会出现「有的图粘得进、有的粘不进」。两者不叠加，免得同一张图收两遍。 */
function clipFiles(e) {
  const cd = e && e.clipboardData;
  if (!cd) return [];
  const fs = [...(cd.files || [])];
  if (fs.length) return fs;
  return [...(cd.items || [])].filter(i => i.kind === 'file').map(i => i.getAsFile()).filter(Boolean);
}
/* ---- 应用内剪贴板 ----
   云盘里点「复制」放进来的是**应用里的文件**（只有一个 id），系统剪贴板碰不到它：
   桌面壳的 WebKit 右键菜单只认文本和图片，navigator.clipboard 又是被拒的。
   所以自己存一份，粘到哪儿由接收方决定 —— 云盘里粘 = 复制文件，AI 助手里粘 = 当附件。
   变动时发一个 appclip 事件，界面上那些「剪贴板里有 N 项」的提示靠它自己刷新。 */
let APPCLIP = [];                 // [{kind:'drive'|'material', id, name}]
function setAppClip(items) {
  APPCLIP = (items || []).slice();
  try { document.dispatchEvent(new CustomEvent('appclip')); } catch (_) { /* 老壳没有 CustomEvent 就算了 */ }
}
function getAppClip() { return APPCLIP.slice(); }

/* 锚定小菜单：把 el 弹在 btn 附近（贴左对齐、贴下方 4px）；
   靠近视口底部/右侧时翻到上方/收边，别让菜单探出屏幕。⋮ 菜单、+号面板共用这一套。 */
function anchorMenu(el, btn) {
  el.classList.remove('hidden');
  const r = btn.getBoundingClientRect();
  const w = el.offsetWidth || 180, h = el.offsetHeight || 160;
  let top = r.bottom + 4;
  if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 4);
  el.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + 'px';
  el.style.top = top + 'px';
}
// 手机端聊天/AI 输入栏：有没有内容决定显示「麦克风+➕」还是「发送」（微信式）
function syncSendState(box) {
  const ta = box && box.querySelector('textarea');
  if (box) box.classList.toggle('has-text', !!(ta && ta.value.trim()));
}
// 输入框自增高（桌面走拖高逻辑装的 t._grow，手机走紧凑自动增高，最高 120）+ 同步发送态。
// 聊天、AI 助手的输入框共用这一套，各自套一层同名壳函数（aiGrow/crGrow）传自己的 id。
function growAndSync(taSel, boxSel) {
  const t = $(taSel); if (!t) return;
  if (t._grow) t._grow();
  else { t.style.height = 'auto'; t.style.height = Math.min(120, t.scrollHeight) + 'px'; }
  syncSendState($(boxSel));
}
// 线性 SVG 图标
const _svg = (p) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const IC = {
  feather: _svg('<path d="M20.24 12.24a6 6 0 0 0-8.49-8.49L5 10.5V19h8.5z"/><line x1="16" y1="8" x2="2" y2="22"/><line x1="17.5" y1="15" x2="9" y2="15"/>'),
  folder: _svg('<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>'),
  book: _svg('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'),
  edit: _svg('<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>'),
  del: _svg('<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'),
  clip: _svg('<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>'),
  wrong: _svg('<path d="M9 11l-2 2 2 2"/><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="14 3 14 9 20 9"/><path d="M14.5 12.5l3 3M17.5 12.5l-3 3"/>'),
  bulb: _svg('<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.8 10.6c.5.5.8 1 .8 1.9v.5h6v-.5c0-.9.3-1.4.8-1.9A6 6 0 0 0 12 3z"/>'),
  clock: _svg('<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>'),
  check: _svg('<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>'),
  quote: _svg('<path d="M6 17h3l2-4V7H5v6h3z"/><path d="M14 17h3l2-4V7h-6v6h3z"/>'),
  target: _svg('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.4"/>'),
  play: _svg('<rect x="2" y="4" width="20" height="16" rx="3"/><path d="M10 9l5 3-5 3z" fill="currentColor"/>'),
  layers: _svg('<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>'),
  compass: _svg('<circle cx="12" cy="12" r="9"/><polygon points="16.2 7.8 14.1 14.1 7.8 16.2 9.9 9.9 16.2 7.8"/>'),
  flag: _svg('<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V4s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/>'),
  star: _svg('<polygon points="12 2.5 15 9 22 9.8 16.8 14.4 18.3 21.4 12 17.8 5.7 21.4 7.2 14.4 2 9.8 9 9 12 2.5"/>'),
  /* 云盘和聊天原来用的是 ☁️ 和 💬。彩色 emoji **任何主题都改不了它的颜色**，
     混在一屏 SVG 字形里本来就是异类，主题一开更是整屏就它俩跳出来。
     （全国考情那个 📣 换成了上面的 flag。） */
  cloud: _svg('<path d="M6.8 19.4a4.6 4.6 0 0 1-.5-9.2 6.6 6.6 0 0 1 12.5-1.3 3.9 3.9 0 0 1-1 10.5z"/><path d="M12 16.6v-6M9.6 12.9 12 10.5l2.4 2.4"/>'),
  chat: _svg('<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9.6 9.6 0 0 1-2.9-.4L3 21l1.6-4.6A8 8 0 0 1 3.6 11.5a8.4 8.4 0 0 1 9-8.4 8.4 8.4 0 0 1 8.4 8.4z"/>'),
  dl: _svg('<path d="M12 3v12"/><polyline points="8 11 12 15 16 11"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>'),
};
// 板块下的功能模块（可扩展：以后给某板块加更多功能图标）
const BOARD_FEATURES = {
  /* 社区专职工作者（资中县）。它不是行测的一个板块，是**第三条备考线**——
     放进同一张表是因为「练」标签的 chip、板块页、功能分派全走这一份数据，
     单开一套等于把同一件事写两遍。没有 drill 键，所以不会混进「专项突破」那一组
     （社区的专项练是 P1 的事，等题库灌进来再加）。 */
  '社区': [
    // practice:true = 归到板块页的「练」那一组。用标记而不是按 key 名特判：
    // 分组原来只认 key==='drill'，社区没有专项练（P1 才有），
    // 不加这个标记的话「资中真题」会被归进「这个板块的积累」—— 它是练，不是积累。
    { key: 'sqreal', name: '资中真题', desc: '2023 / 2025 原卷 · 整卷模考或背题 · 100 分卷面', icon: 'target', practice: true },
    { key: 'sqlocal', name: '资中专项', desc: '公告数据直出的必得分 · 速记卡 + 程序化出题', icon: 'compass', practice: true },
    { key: 'sqdrill', name: '专项练', desc: '6531 道 · 按题型或考点刷 · 错过的排最前', icon: 'target', practice: true },
    { key: 'sqsub', name: '主观题 40 分', desc: '案例分析 + 公文写作 · 按采分点逐条批改', icon: 'pen', practice: true },
    { key: 'sqcheck', name: '入库校对', desc: '源卷是回忆版 · 三方核验对不上的题在这儿定案', icon: 'check', practice: true },
  ],
  // 这三块靠练不靠背：题型固定、有套路、拼速度 → 专项练（按题型刷 + 计时 + 秒杀技巧）
  '资料分析': [
    { key: 'drill', name: '专项练', desc: '6 类题型 · 计时 · 速算技巧 · 薄弱优先', icon: 'target' },
  ],
  '判断推理': [
    { key: 'drill', name: '专项练', desc: '图形推理 5 类规律 · 计时 · 薄弱优先', icon: 'target' },
  ],
  '数量关系': [
    { key: 'drill', name: '专项练', desc: '8 类题型 · 计时 · 秒杀技巧 · 薄弱优先', icon: 'target' },
  ],
  '常识判断': [
    { key: 'drill', name: '专项练', desc: '7 类考点 · 三档难度 · 计时 · 薄弱优先', icon: 'target' },
    { key: 'changshi', name: '常识积累', desc: '人文/科技/法律… 七大板块 每日更新', icon: 'bulb' },
  ],
  '言语理解与表达': [
    { key: 'drill', name: '专项练', desc: '逻辑填空/片段阅读/语句排序/病句 · 三档难度', icon: 'target' },
    { key: 'idiom', name: '成语词语积累', desc: '选词填空 · 拼音释义 · 导 PDF', icon: 'book' },
    { key: 'hyper', name: '上位词积累', desc: '逻辑填空概括词提示 · 每日推荐', icon: 'layers' },
  ],
  '政治理论': [
    { key: 'drill', name: '专项练', desc: '马原/毛概/中特/习思想 · 三档难度', icon: 'target' },
    { key: 'news', name: '每日时政', desc: '每天自动更新 · AI 摘要+考点', icon: 'feather' },
    { key: 'videos', name: '每日新闻视频', desc: '官方媒体 · AI 筛出最值得看的 · 国内/国际/四川', icon: 'play' },
    { key: 'policydoc', name: '时政要文库', desc: '二十大·十五五·两会报告 全文+AI解读', icon: 'book' },
    { key: 'partydict', name: '党的创新理论学习词典', desc: '两个确立·四个意识… 12371 术语速查', icon: 'book' },
    { key: 'theory', name: '理论基础', desc: '马原 · 毛概 · 中特 · 习思想 考点速记', icon: 'compass' },
  ],
  '应用文': [
    { key: 'wapp', name: '应用文成文', desc: '14 文种四大类 · 每日成文 + 提纲纲要 · 用当天素材写', icon: 'edit' },
    { key: 'gaikuo', name: '概括句积累', desc: '每日更新 · 材料表述→规范概括句', icon: 'edit' },
    { key: 'gongwen', name: '应用文上位词', desc: '公文规范上位表述 · 按场景归类 · AI 归纳', icon: 'layers' },
    { key: 'yylib', name: '应用文素材库', desc: '文种按真题频次排 · 下钻到结构部件', icon: 'clip' },
    { key: 'yyerr', name: '应用文改错', desc: '真题实证的格式错例 · 判断这样写对不对', icon: 'target' },
  ],
  '议论文': [
    { key: 'write', name: '成文', desc: '素材 → 大作文 · 每日成文 / 综合应用', icon: 'edit' },
    { key: 'fanwen', name: '人民时评·申论范文', desc: '每日抓人民日报评论版 · AI 拆结构与亮点', icon: 'feather' },
    { key: 'sucai', name: '素材积累', desc: '每日更新 · 人物/事例/理论论据', icon: 'clip' },
    { key: 'lianjie', name: '衔接表达', desc: '过渡/转折/万能句式 不口语不重复', icon: 'quote' },
    { key: 'classics', name: '古诗文·名句速查', desc: '唐诗宋词 · 四书五经 · 查询收藏', icon: 'book' },
  ],
};
// 大板块（行测/申论）下的功能模块（预留，可扩展）
const SECTION_FEATURES = {};
// 挂在大板块底部、但不属于「资料分类」的入口（所以不写进 SECTIONS.boards）
const SECTION_EXTRA = {
  shenlun: [
    { name: '小题训练', badge: '找点 + 写点', go: 'find' },
    { name: '真题批改', badge: 'AI 逐点批改', go: 'shenlun' },
  ],
  /* 社区那八个 boards 是**资料分类**（考点大类），不是功能入口；
     真正要点的两样挂在这儿，否则「按学科浏览 → 社区」只剩八个待填的分类。 */
  shequ: [
    { name: '资中真题', badge: '2023 / 2025 整卷', go: 'sqreal' },
    { name: '资中专项', badge: '地方必得分', go: 'sqlocal' },
    { name: '专项练', badge: '6531 道 · 按题型/考点', go: 'sqdrill' },
    { name: '主观题 40 分', badge: '案例 + 公文逐点批改', go: 'sqsub' },
    { name: '入库校对', badge: '存疑答案定案', go: 'sqcheck' },
  ],
};

let ME = null, SECTIONS = [], IDIOM_BOARD = '', ALL_BOARDS = [];
/* 备考方向。**只是个视图开关**：错题本、今日复习、每日测试、备考规划按它过滤，
   两条线的数据一条不删 —— 考完社区还要回头接着考公。 */
let LINE = { line: 'gongkao', lines: [], boards: [] };

async function switchLine(want) {
  if (!want || (LINE && LINE.line === want)) return;
  try {
    LINE = await postJSON('/api/me/line', { line: want });
    toast('已切到「' + ((LINE.lines.find(x => x.key === want) || {}).short || want) + '」备考');
    location.reload();       // 首页、错题、复习、计划全都要按新方向重取，整页重来最省事也最不容易漏
  } catch (e) { toast(errMsg(e), true); }
}
let stack = [];
