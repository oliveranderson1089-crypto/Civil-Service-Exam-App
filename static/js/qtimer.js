/* 做题倒计时：每题一个小钟，整卷模考再加一个大钟。
 *
 * 三个刷题入口（专项练 / 历年真题 / 每日巩固测试）共用这一份，限时秒数由服务端
 * 按**题型**给（mods/timing.py），前端不猜、也不写死板块默认值 —— 各写一份的话，
 * 同一道「比较大小」在两个入口的倒计时会不一样，练出来的速度感是假的。
 *
 * 归零之后**不打断**：钟转红、开始记「超时 +12 秒」，题照做、答案照选。
 * 真实考场也没人到点拔你的笔；而超时了多少秒才是这道题真正的成绩，
 * 强行跳题只会把这个数字抹掉（做题记录里那一栏就永远是「限时」）。
 *
 * 计时一律按**时间戳差**算，不用累加 setInterval 的次数：手机锁屏、切后台时
 * 定时器会被节流，累加法算出来的用时比真实短一大截，「平均用时」整个失真。
 *
 * ⚠️ 停表分两种，别混用（混了就是静默把用时记成 0）：
 *   qtPause() —— 离开页面时用。**攒着的秒数留着**，回来 qtResume() 接着走。
 *   qtStop()  —— 这道题真的做完了才用。清空状态并返回总用时。
 * 对已经停掉的表再调 qtStop() 返回 0，所以调用方拿到 0 一律别往用时里写
 * （realq/drill 都加了 `if (used)` 的护栏）。
 */
/* global $, toast */

/* _qtT0 = 本段计时的起点（暂停时为 0）；_qtUsed = 之前已攒下的秒数。
   两个加起来才是这道题的真实用时 —— 只有一个变量的话，一次暂停就丢一段。 */
let _qtTimer = 0, _qtT0 = 0, _qtUsed = 0, _qtLimit = 0, _qtEl = null;
let _qtWarned = false, _qtOnOver = null;
let _qtTotalTimer = 0, _qtTotalT0 = 0, _qtTotalUsed = 0, _qtTotalLimit = 0;
let _qtTotalEl = null, _qtTotalWarned = false, _qtTotalTag = '';

/** 秒 → 「1:05:03」/「05:03」。超过一小时才带小时位，平时别占位置。 */
function qtFmt(s) {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  const mm = String(m).padStart(2, '0'), xx = String(x).padStart(2, '0');
  return h ? `${h}:${mm}:${xx}` : `${mm}:${xx}`;
}

/** 这道题到现在花了多少秒（暂停期间不涨）。 */
function qtElapsed() { return _qtUsed + (_qtT0 ? (Date.now() - _qtT0) / 1000 : 0); }

function _qtPaint() {
  if (!_qtEl) return;
  const left = _qtLimit - qtElapsed();
  if (left >= 0) {
    _qtEl.textContent = `⏱ ${qtFmt(left)}`;
    // 最后 1/4 且不超过 15 秒时转黄：早早变色会让人整题都处在警报状态，反而不敏感
    _qtEl.className = 'q-clock' + (left <= Math.min(15, _qtLimit / 4) ? ' warn' : '');
    return;
  }
  _qtEl.textContent = `⏱ 超时 +${qtFmt(-left)}`;
  _qtEl.className = 'q-clock over';
  if (!_qtWarned) {
    _qtWarned = true;
    toast(`这题超过 ${_qtLimit} 秒了，接着做`);
    // 手机上钟在屏幕上方，眼睛在题上 —— 震一下才是真的提醒（不支持的浏览器自动忽略）
    if (navigator.vibrate) { try { navigator.vibrate(120); } catch (_) { /* 忽略 */ } }
    if (_qtOnOver) _qtOnOver();
  }
}

/** 开始给这道题计时。el 可传元素或选择器；sec 是服务端给的题型限时。
    opts.used = 这道题**之前已经花掉**的秒数（测试模式能翻回上一题，
    那部分时间得接着算，从零重来的话超时的题一翻页就「不超时」了）。 */
function qtStart(el, sec, opts) {
  qtStop();
  _qtUsed = Math.max(0, (opts || {}).used || 0);
  _qtEl = typeof el === 'string' ? $(el) : el;
  _qtLimit = Math.max(5, +sec || 60);
  _qtT0 = Date.now();
  _qtWarned = _qtUsed > _qtLimit;   // 之前就已经超时了，别再弹一次「超时了」
  _qtOnOver = (opts || {}).onOver || null;
  _qtPaint();
  _qtTimer = setInterval(_qtPaint, 250);   // 250ms：切页面时残留的那一格也就少显示 1/4 秒
  return _qtLimit;
}

/** 停表，返回这道题实际用了多少秒（小数，统计要用）。没在计时就返回 0。 */
function qtStop() {
  const used = qtElapsed();
  clearInterval(_qtTimer);
  _qtTimer = 0; _qtT0 = 0; _qtUsed = 0; _qtEl = null; _qtOnOver = null;
  return used;
}

/** 暂停（离开页面）。攒着的秒数**留着**，qtResume() 回来接着走。 */
function qtPause() {
  if (!_qtT0) return;
  _qtUsed = qtElapsed();
  clearInterval(_qtTimer);
  _qtTimer = 0; _qtT0 = 0;
}

/** 回到页面继续走。元素已经被重画掉（不在文档里）就不恢复，交给模块重新起表。 */
function qtResume() {
  if (_qtT0 || !_qtEl || !_qtEl.isConnected) return;
  _qtT0 = Date.now();
  _qtPaint();
  _qtTimer = setInterval(_qtPaint, 250);
}

/** 这道题的限时是多少（结果页判「超时没超时」用同一个数）。 */
function qtLimit() { return _qtLimit; }

function _qtTotalElapsed() {
  return _qtTotalUsed + (_qtTotalT0 ? (Date.now() - _qtTotalT0) / 1000 : 0);
}

function _qtTotalPaint() {
  if (!_qtTotalEl) return;
  const left = _qtTotalLimit - _qtTotalElapsed();
  if (left >= 0) {
    _qtTotalEl.textContent = `剩余 ${qtFmt(left)}`;
    _qtTotalEl.className = 'q-total' + (left <= 300 ? ' warn' : '');   // 最后 5 分钟
    return;
  }
  _qtTotalEl.textContent = `超时 +${qtFmt(-left)}`;
  _qtTotalEl.className = 'q-total over';
  if (!_qtTotalWarned) {
    _qtTotalWarned = true;
    toast('整卷时间到了，剩下的题可以继续做完');
    if (navigator.vibrate) { try { navigator.vibrate([120, 80, 120]); } catch (_) { /* 忽略 */ } }
  }
}

/** 整卷模考 / 整份小测的大钟。sec = 各题建议用时之和（服务端算，见 real_quiz 的 total_sec）。
    tag 用来认「还是不是同一份卷子」：同一份就别重开，否则离开页面再回来时间会被刷新，
    这个钟就成了摆设（想续时只要退出去再进来）。 */
function qtTotalStart(el, sec, tag) {
  if (tag && tag === _qtTotalTag && _qtTotalEl) { qtTotalResume(); return; }
  qtTotalStop();
  _qtTotalEl = typeof el === 'string' ? $(el) : el;
  _qtTotalLimit = Math.max(60, +sec || 0);
  _qtTotalUsed = 0;
  _qtTotalT0 = Date.now();
  _qtTotalWarned = false;
  _qtTotalTag = tag || '';
  _qtTotalPaint();
  _qtTotalTimer = setInterval(_qtTotalPaint, 500);
}

/** 收大钟，返回整卷用了多少秒。 */
function qtTotalStop() {
  const used = _qtTotalElapsed();
  clearInterval(_qtTotalTimer);
  _qtTotalTimer = 0; _qtTotalT0 = 0; _qtTotalUsed = 0; _qtTotalEl = null; _qtTotalTag = '';
  return used;
}

function qtTotalPause() {
  if (!_qtTotalT0) return;
  _qtTotalUsed = _qtTotalElapsed();
  clearInterval(_qtTotalTimer);
  _qtTotalTimer = 0; _qtTotalT0 = 0;
}

function qtTotalResume() {
  if (_qtTotalT0 || !_qtTotalEl || !_qtTotalEl.isConnected) return;
  _qtTotalT0 = Date.now();
  _qtTotalPaint();
  _qtTotalTimer = setInterval(_qtTotalPaint, 500);
}

/** 大钟还在走吗（含暂停：暂停也算「这份卷子的钟还在」）。 */
function qtTotalOn() { return !!(_qtTotalT0 || _qtTotalEl); }

window.qtFmt = qtFmt;
window.qtStart = qtStart;
window.qtStop = qtStop;
window.qtPause = qtPause;
window.qtResume = qtResume;
window.qtElapsed = qtElapsed;
window.qtLimit = qtLimit;
window.qtTotalStart = qtTotalStart;
window.qtTotalStop = qtTotalStop;
window.qtTotalPause = qtTotalPause;
window.qtTotalResume = qtTotalResume;
window.qtTotalOn = qtTotalOn;
