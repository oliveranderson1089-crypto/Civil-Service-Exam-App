/* 通用停靠（草稿纸 / AI 面板共用）
 *
 * 由 app.js 按它自己的区段边界切出（原 L9914-10115）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, doSave, draft, loadDrafts, lsGet, lsSet,
   padDraftId, padDraftSave, padInit, padInited, padLoad, padMode,
   padSave, padSaveT, push, toast */

/* ================= 通用停靠（草稿纸 / AI 面板共用） =================
   半屏只是默认值：交界处的分隔线可以直接拖，比例按「每个停靠位」分别记住；
   ✥ 手柄按住拖到屏幕任一边 → 松手吸附成那半边（拖到正中 = 全屏）。 */
const DOCK_NAME = { bottom: '下半屏', top: '上半屏', right: '右半屏', left: '左半屏', full: '全屏' };
const dockVert = (d) => d === 'left' || d === 'right';

function createDock(el, key, defDock, onChange) {
  const st = { dock: defDock, prev: defDock, sizes: { bottom: 0, top: 0, left: 0, right: 0 } };
  const defSize = (d) => dockVert(d) ? Math.round(innerWidth * .5) : Math.round(innerHeight * .46);
  const size = (d) => {                       // 记住的大小；没拖过就是一半。换屏也不会越界
    const v = st.sizes[d] || defSize(d);
    const max = dockVert(d) ? innerWidth * .95 : innerHeight * .95;
    const min = dockVert(d) ? 280 : 190;
    return Math.round(Math.min(max, Math.max(min, v)));
  };
  const save = () => { lsSet(key, JSON.stringify({ d: st.dock, sizes: st.sizes })); };
  (function load() {
    try {
      const d = JSON.parse(lsGet(key) || 'null');
      if (!d) return;
      if (DOCK_NAME[d.d]) { st.dock = d.d; st.prev = d.d === 'full' ? defDock : d.d; }
      if (d.sizes) Object.assign(st.sizes, d.sizes);
      else { if (d.h) { st.sizes.bottom = d.h; st.sizes.top = d.h; }    // 兼容旧格式
             if (d.w) { st.sizes.left = d.w; st.sizes.right = d.w; } }
    } catch (_) { /* 存的位置读坏了就用默认停靠，不值得为它打扰用户 */ }
  })();

  function apply(doSave) {
    Object.keys(DOCK_NAME).forEach(d => el.classList.toggle('dk-' + d, d === st.dock));
    if (st.dock !== 'full') {
      if (dockVert(st.dock)) el.style.setProperty('--dk-w', size(st.dock) + 'px');
      else el.style.setProperty('--dk-h', size(st.dock) + 'px');
    }
    if (doSave) save();
    requestAnimationFrame(() => { if (onChange) onChange(); applyPush(); avoidFab(); });
  }
  function set(d, quiet) {
    if (!DOCK_NAME[d]) return;
    if (d !== 'full') st.prev = d;
    st.dock = d; apply(true);
    if (!quiet) toast(d === 'full' ? '全屏' : '已停靠：' + DOCK_NAME[d]);
  }
  function toggleFull() { set(st.dock === 'full' ? (st.prev || defDock) : 'full', true); }

  const box = (z) => z === 'full' ? { left: 0, top: 0, width: innerWidth, height: innerHeight }
    : z === 'left' ? { left: 0, top: 0, width: size('left'), height: innerHeight }
      : z === 'right' ? { left: innerWidth - size('right'), top: 0, width: size('right'), height: innerHeight }
        : z === 'top' ? { left: 0, top: 0, width: innerWidth, height: size('top') }
          : { left: 0, top: innerHeight - size('bottom'), width: innerWidth, height: size('bottom') };
  const zoneAt = (x, y) => x < innerWidth * .18 ? 'left' : x > innerWidth * .82 ? 'right'
    : y < innerHeight * .15 ? 'top' : y > innerHeight * .85 ? 'bottom' : 'full';

  function dockDrag(e) {                      // 按住 ✥ 拖 → 松手吸附
    e.preventDefault();
    el.classList.add('dragging');
    let zone = st.dock;
    const show = (z) => {
      const s = $('#dock-snap'), b = box(z);
      s.style.left = b.left + 'px'; s.style.top = b.top + 'px';
      s.style.width = b.width + 'px'; s.style.height = b.height + 'px';
      s.classList.remove('hidden');
    };
    const mv = (ev) => { zone = zoneAt(ev.clientX, ev.clientY); show(zone); };
    const up = () => {
      removeEventListener('pointermove', mv); removeEventListener('pointerup', up);
      el.classList.remove('dragging');
      $('#dock-snap').classList.add('hidden');
      if (zone !== st.dock) set(zone);        // 大小沿用该停靠位上次拖成的比例
    };
    show(zone);
    addEventListener('pointermove', mv); addEventListener('pointerup', up);
  }

  const grip = document.createElement('div');   // 交界处那条分隔线
  grip.className = 'dk-grip';
  grip.title = '拖动改大小 · 双击复位成一半';
  el.appendChild(grip);
  grip.addEventListener('pointerdown', (e) => {
    if (st.dock === 'full') return;
    e.preventDefault();
    // ★ 关键：把指针锁在 grip 上。不然拖动时指针一旦划过 PDF 的 iframe，pointerup 会被 iframe 吞掉，
    //   父窗口收不到「松手」→ 表现就是「松开鼠标还在调大小，一动就变」。
    try { grip.setPointerCapture(e.pointerId); } catch (_) { /* 捕获失败不影响画线，指针事件照样收得到 */ }
    document.body.classList.add(dockVert(st.dock) ? 'dk-rz-x' : 'dk-rz-y');
    grip.classList.add('on');
    const mv = (ev) => {
      const raw = st.dock === 'bottom' ? innerHeight - ev.clientY
        : st.dock === 'top' ? ev.clientY
          : st.dock === 'right' ? innerWidth - ev.clientX
            : ev.clientX;
      // 0 是「没拖过 / 双击复位了」的哨兵（见 size()），拖动不能撞上它：
      // 一路拖到屏幕边缘时 raw 正好是 0，会被 size() 当成「用默认值」→ 面板从
      // 最小值猛地弹回半屏，松手还把这个尺寸存了下来。夹到 1，让 size() 去收敛到 min。
      st.sizes[st.dock] = Math.max(1, raw);
      apply(false);
    };
    const up = () => {
      grip.removeEventListener('pointermove', mv);
      grip.removeEventListener('pointerup', up);
      grip.removeEventListener('pointercancel', up);
      try { grip.releasePointerCapture(e.pointerId); } catch (_) { /* 捕获失败不影响画线，指针事件照样收得到 */ }
      document.body.classList.remove('dk-rz-x', 'dk-rz-y');
      grip.classList.remove('on');
      st.sizes[st.dock] = size(st.dock);
      apply(true);
    };
    grip.addEventListener('pointermove', mv);
    grip.addEventListener('pointerup', up);
    grip.addEventListener('pointercancel', up);
  });
  grip.addEventListener('dblclick', () => {
    if (st.dock === 'full') return;
    st.sizes[st.dock] = 0; apply(true); toast('已复位成一半');
  });

  addEventListener('resize', () => { if (!el.classList.contains('hidden')) apply(false); });
  return { st, apply, set, toggleFull, dockDrag, isFull: () => st.dock === 'full' };
}

/* 记住的位置要按「当前窗口」夹回来：换台设备 / 桌面版窗口更小时，
   否则球会停在窗口外面，看起来就是「悬浮球不见了」。 */
function fabClamp() {
  const fab = $('#fab');
  if (!fab || !innerWidth || !innerHeight) return;      // 还没完成布局就先别动
  if (!fab.style.left && !fab.style.top) return;        // 没拖过 → 用 CSS 默认角落，不用管
  const r = fab.getBoundingClientRect();
  const w = r.width || 50, h = r.height || 50;
  const x = Math.min(Math.max(4, r.left), innerWidth - w - 4);
  const y = Math.min(Math.max(4, r.top), innerHeight - h - 4);
  if (Math.abs(x - r.left) < .5 && Math.abs(y - r.top) < .5) return;
  fab.style.left = x + 'px'; fab.style.top = y + 'px';
  fab.style.right = 'auto'; fab.style.bottom = 'auto';
  lsSet('aifab', JSON.stringify({ x, y }));
}
addEventListener('resize', fabClamp);
addEventListener('load', () => requestAnimationFrame(fabClamp));

/* 停靠面板占屏后，把页面内容挤到剩下的可见区（卡片会自动重排，不再被盖住） */
function applyPush() {
  const p = { left: 0, right: 0, top: 0, bottom: 0 };
  [$('#pad'), $('#ai-panel'), $('#matpad')].forEach(el => {
    /* dk-inline = 这个面板被搬进做题页右栏了（见 js/qpanel.js）。
       它已经在正文流里，再按它的宽度推一次正文，就是白让出去半屏。 */
    if (!el || el.classList.contains('hidden') || el.classList.contains('dk-full')
      || el.classList.contains('dk-inline')) return;
    const d = Object.keys(DOCK_NAME).find(k => el.classList.contains('dk-' + k));
    if (!d || d === 'full') return;
    const r = el.getBoundingClientRect();
    p[d] = Math.max(p[d], Math.round(dockVert(d) ? r.width : r.height));
  });
  const s = document.body.style;
  s.setProperty('--push-l', p.left + 'px');
  s.setProperty('--push-r', p.right + 'px');
  s.setProperty('--push-t', p.top + 'px');
  s.setProperty('--push-b', p.bottom + 'px');
}

/* 悬浮球别被面板压住：挡住就挪到面板外；面板全屏时藏起来 */
function avoidFab() {
  const fab = $('#fab');
  if (!fab || !innerWidth) return;
  const open = [$('#pad'), $('#ai-panel'), $('#matpad')]
    .filter(p => p && !p.classList.contains('hidden') && !p.classList.contains('dk-inline'));
  document.body.classList.toggle('pad-full', open.some(p => p.classList.contains('dk-full')));
  if (!open.length || document.body.classList.contains('pad-full')) return;
  for (const p of open) {
    const r = p.getBoundingClientRect(), f = fab.getBoundingClientRect();
    if (!(f.left < r.right && f.right > r.left && f.top < r.bottom && f.bottom > r.top)) continue;
    const d = Object.keys(DOCK_NAME).find(k => p.classList.contains('dk-' + k));
    let x = f.left, y = f.top;
    if (d === 'right') x = r.left - f.width - 12;
    else if (d === 'left') x = r.right + 12;
    else if (d === 'bottom') y = r.top - f.height - 12;
    else if (d === 'top') y = r.bottom + 12;
    x = Math.min(Math.max(4, x), innerWidth - f.width - 4);
    y = Math.min(Math.max(4, y), innerHeight - f.height - 4);
    fab.style.left = x + 'px'; fab.style.top = y + 'px';
    fab.style.right = 'auto'; fab.style.bottom = 'auto';
    lsSet('aifab', JSON.stringify({ x, y }));
  }
}

/* 草稿纸的停靠实例（手机默认下半屏，电脑默认下半屏；想要别的自己拖） */
let padDk = null;

function padOpen() {
  if (!padInited) padInit();
  $('#pad').classList.remove('hidden');
  document.body.classList.add('pad-open');
  padDk.apply(false);
}
function padClose() {
  const wasDraft = padMode === 'draft';
  clearTimeout(padSaveT);
  if (wasDraft) padDraftSave(); else padSave();
  $('#pad').classList.add('hidden');
  document.body.classList.remove('pad-open', 'pad-full');
  applyPush(); avoidFab();
  if (wasDraft) {                                                 // 退出草稿本 → 回列表，恢复随手草稿纸
    padMode = 'scratch'; padDraftId = null;
    $('#pad-doc').classList.add('hidden');
    padLoad();
    loadDrafts();
  }
}
function padToggle() { $('#pad').classList.contains('hidden') ? padOpen() : padClose(); }
function padOnView() {
  /* 草稿纸现在是全局悬浮的：换页面不再收起——正好可以一边看成语词语、一边在旁边练着写。 */
}
