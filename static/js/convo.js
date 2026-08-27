/* 对话共用件 —— AI 助手（#ai-msgs）和聊天（#cr-msgs）两块屏幕共用的底层规矩。
 *
 * 为什么合成一份：这两块界面看着不一样，可越往底下越是同一件事 —— 都是「一个会一直
 * 长高的滚动容器 + 一个输入栏」。以前各写各的，走散的恰恰是这些细节：AI 那边每 80 毫秒
 * 无条件 `scrollTop = scrollHeight`，聊天那边收到新消息也无条件跳底，结果都是同一个症状 ——
 * 你正往上翻着看，屏幕自己蹦回最新。
 *
 * 滚动契约（K8）只有一条：**只有当用户已经贴着底部时才自动跟**，否则原地不动、
 * 让「↓ N 条新消息」浮标去告诉他下面有货。判断「贴没贴底」不在内容变高之后测
 * （那时候已经不准了），而是靠 scroll 事件持续记录用户的位置：内容变高不触发 scroll，
 * 所以这个标记天然停在「用户最后一次自己滚到哪」。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 */
/* global IS_MOBILE */

'use strict';

/* 距底多少像素还算「贴着底」。留一点余量：行高、输入法、亚像素滚动都会差个几像素，
   要求严格等于底部的话，正常聊天时十有八九会被判成「用户翻上去了」。 */
const CONVO_STICK_PX = 60;

function convoAtBottom(box) {
  if (!box) return true;
  return box.scrollHeight - box.scrollTop - box.clientHeight <= CONVO_STICK_PX;
}

/* 给一个滚动容器装上滚动契约，返回一个把手。同一个容器只装一次（重复调用拿回同一个把手）。
     follow(n, force)  内容变完之后调：贴底就跟到底，没贴底就把浮标 +n
     seen()            用户回到最新 / 切了会话：清浮标、重新算贴底
     toBottom(strong)  强制滚到底（strong=true 时等图片加载完再补滚，见下）
     atBottom()        当前是否贴底
   host：浮标挂在谁身上（要是定位上下文）。不给就用容器的父节点。 */
function convoStick(box, host) {
  if (!box) return { follow() {}, seen() {}, toBottom() {}, atBottom() { return true; } };
  if (box._convoStick) return box._convoStick;

  let stuck = true, pending = 0;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'convo-jump hidden';
  btn.title = '回到最新';
  btn.innerHTML = '<span class="cj-n"></span><span class="cj-ic">↓</span>';

  const paint = () => {
    btn.classList.toggle('hidden', stuck);
    btn.querySelector('.cj-n').textContent = pending ? (pending > 99 ? '99+' : pending) + ' 条新消息' : '';
    btn.classList.toggle('has-n', !!pending);
  };
  const seen = () => { stuck = true; pending = 0; paint(); };

  /* 滚到底。滚一次不够：图片、表格、字体都是**加载完才有高度**的，那一刻内容会变长，
     刚才滚到的「底」就不再是底 —— 表现就是「进来还得自己往下滑一点」。
     所以强制滚底时，把这一屏里还没加载完的图挂上监听，各自加载完再补滚一次。 */
  const jump = () => { box.scrollTop = box.scrollHeight; };
  const toBottom = (strong) => {
    seen();
    jump();
    requestAnimationFrame(jump);
    if (!strong) return;
    /* 监听是 once 的，加载完自己就摘了；补滚前再看一眼 stuck ——
       图还在路上的时候用户已经翻上去看历史了，就不该跟他抢滚动条。 */
    [...box.querySelectorAll('img')].filter(im => !im.complete).forEach(im => {
      const on = () => { if (stuck) jump(); };
      im.addEventListener('load', on, { once: true });
      im.addEventListener('error', on, { once: true });
    });
  };

  box.addEventListener('scroll', () => {
    const at = convoAtBottom(box);
    if (at && !stuck) { seen(); return; }   // 自己滑回底部 = 都看过了
    stuck = at;
    if (!at) paint();
  }, { passive: true });

  btn.addEventListener('click', () => toBottom(false));
  (host || box.parentElement || document.body).appendChild(btn);

  const h = {
    follow(n, force) {
      if (force) { toBottom(true); return; }
      if (stuck) { jump(); requestAnimationFrame(jump); return; }
      if (n) { pending += n; paint(); }
    },
    seen, toBottom, atBottom: () => stuck, el: btn,
  };
  box._convoStick = h;
  return h;
}

/* ---- 头像（K2）：聊天、AI 会话、共享给队友三处共用一份 ----
   以前三处各画各的：聊天是 9px 圆角方块配蓝紫渐变，AI 项目是一段手写 SVG，首页卡片又是一套。
   统一成：圆角取边长的 30%，单人用姓名首字 + 按名字定色（同一个人到哪儿都是同一个颜色），
   群用深绿、AI 用品牌紫、自己用蓝青 —— 颜色本身就是身份的一部分，不该每次随机。 */
const CONVO_AV_HUES = [210, 262, 340, 22, 158, 190, 288, 46];
function convoAvHue(name) {
  let h = 0;
  const s = String(name || '?');
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 9973;
  return CONVO_AV_HUES[h % CONVO_AV_HUES.length];
}
/* kind: ''（好友）/ 'group' / 'ai' / 'me'；size: 'lg' | '' | 'sm' */
function convoAvatar(name, url, kind, size) {
  const cls = 'cv-av' + (kind ? ' cv-' + kind : '') + (size ? ' cv-' + size : '');
  if (url) return `<span class="${cls} has-img" style="background-image:url('${String(url).replace(/'/g, '%27')}')"></span>`;
  const ch = String(name || '?').trim().slice(0, 1).toUpperCase() || '?';
  const txt = kind === 'ai' ? 'AI' : (ch.replace(/[<>&"]/g, ''));
  const style = (kind || url) ? '' : ` style="--cv-h:${convoAvHue(name)}"`;
  return `<span class="${cls}"${style}>${txt}</span>`;
}

/* 手机端长按出动作面板（K5）：桌面端是悬停浮出，手机端没有悬停，只能长按。
   500ms 内手指移动超过 10px 就当成滚动，不弹面板 —— 不然在消息流里滑一下就弹。 */
function convoLongPress(box, sel, fn) {
  if (!box || !IS_MOBILE) return;
  let timer = 0, sx = 0, sy = 0, target = null;
  const clear = () => { clearTimeout(timer); timer = 0; target = null; };
  box.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 1) return clear();
    const t = e.touches[0];
    target = e.target.closest(sel);
    if (!target) return;
    sx = t.clientX; sy = t.clientY;
    timer = setTimeout(() => {
      const el = target; clear(); if (!el) return;
      /* 长按满 500ms 就弹菜单，可手指抬起时浏览器还会补一个 click。不拦掉它，
         这一下会被当成普通点击：既顺手打开了这个会话，又冒泡到 document 被
         「点别处就收菜单」的逻辑当场把刚弹出来的菜单关掉。
         只吞落在长按目标上的那一次（点菜单项的点击照常走），吞完即摘。 */
      const eat = (ev) => {
        document.removeEventListener('click', eat, true);
        if (ev.target && ev.target.closest && ev.target.closest(sel)) {
          ev.stopPropagation(); ev.preventDefault();
        }
      };
      document.addEventListener('click', eat, true);
      fn(el);
    }, 500);
  }, { passive: true });
  box.addEventListener('touchmove', (e) => {
    if (!timer) return;
    const t = e.touches[0];
    if (Math.abs(t.clientX - sx) > 10 || Math.abs(t.clientY - sy) > 10) clear();
  }, { passive: true });
  box.addEventListener('touchend', clear, { passive: true });
  box.addEventListener('touchcancel', clear, { passive: true });
}
