/* 全局快捷键（兜底层）
 *
 * 放在所有模块之后加载：更专门的处理（pad.js 的 Ctrl+Z/Y/S、AI 输入框 Enter、
 * 各弹层自己的 Esc 等）若已经 e.preventDefault()，这里用 e.defaultPrevented 让路，不重复触发。
 *
 * 原生的 Ctrl+C / Ctrl+V（复制 / 粘贴）在输入框里照常生效，这里**不拦**——拦了反而坏事。
 */
/* global $, aiSend, openSearch, toast */
(function () {
  const vis = (el) => el && !el.classList.contains('hidden') && el.offsetParent !== null;

  // 光标在能打字的地方就一个都别拦：做题页有随手记、有搜索框，
  // 在里面打「a」应该出「a」，不是选 A 选项。
  const typing = () => {
    const a = document.activeElement;
    return !!(a && (a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)));
  };
  /* 做题页专用的**无修饰键**快捷键：A–D 选选项、J/K（和 ←/→）切题、Enter 下一题。
     只在这两页生效——别的页面按 j 应该什么都不发生。
     **巩固测试（dtest）不在内**：它把整套题一次全铺在一页上，没有「当前是哪一题」这回事，
     按 A 只能永远命中第一题的 A，比没有还糟。 */
  const RUN = { realrun: '#rq-opts', drillrun: '#dr-body' };
  const NEXT = { realrun: '#rq-next', drillrun: '#dr-nextq' };
  const PREV = { drillrun: '#dr-prev' };
  /* 题号格就是现成的「跳到第 n 题」：不用再往做题模块里加接口。
     **必须限定在当前视图里找**：两个做题页各有一张答题卡，都在 DOM 里躺着。
     全局找的话，在专项练里按 J 会驱动排在前面的那张真题答题卡 ——
     题号不动、真题的表被重启、专项练正在走的表被打断，这道题的用时记成 0 秒。 */
  const step = (d) => {
    const view = document.body.dataset.view;
    const cur = document.querySelector(`#view-${view} .q-side .qs-cur`);
    if (!cur) return false;
    const t = document.querySelector(`#view-${view} .q-side [data-qs="${+cur.dataset.qs + d}"]`);
    if (!t) return false;
    t.click(); return true;
  };
  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented) return;                 // 已有更专门的处理接手了
    const mod = e.ctrlKey || e.metaKey;
    if (!mod && !e.altKey && !typing()) {
      const view = document.body.dataset.view;
      const optSel = RUN[view];
      if (optSel) {
        const k = (e.key || '');
        const L = k.toUpperCase();
        if ('ABCD'.includes(L) && L.length === 1) {
          // 选项按钮各模块类名不同（.rq-opt / .dt-opt），一律按 data-* 上的字母找
          const b = document.querySelector(
            `${optSel} [data-rqo="${L}"],${optSel} [data-dro="${L}"]`);
          if (b && !b.disabled) { e.preventDefault(); b.click(); }
          return;
        }
        if (k === 'j' || k === 'ArrowRight') { if (step(1)) e.preventDefault(); return; }
        if (k === 'k' || k === 'ArrowLeft') { if (step(-1)) e.preventDefault(); return; }
        if (k === 'Enter') {
          const n = NEXT[view] && $(NEXT[view]);
          if (n && vis(n) && !n.disabled) { e.preventDefault(); n.click(); }
          return;
        }
        if (k === 'ArrowUp') { const p2 = PREV[view] && $(PREV[view]);
          if (p2 && vis(p2) && !p2.disabled) { e.preventDefault(); p2.click(); } return; }
      }
    }
    if (!mod || e.altKey) return;
    const k = (e.key || '').toLowerCase();

    // ── Ctrl/Cmd+S：就地保存（同时拦掉浏览器「保存网页」弹窗）──
    if (k === 's') {
      e.preventDefault();
      if (vis($('#qnote'))) { $('#qn-save').click(); return; }                // 随手记
      if (vis($('#note-modal'))) { $('#note-modal-save').click(); return; }   // 笔记弹窗
      const notes = $('#view-notes');
      if (notes && !notes.classList.contains('hidden')) {                     // 小记编辑器 → 发布/保存
        const b = $('#cp-submit'); if (b && !b.disabled) { b.click(); return; }
      }
      toast('当前内容会自动保存');
      return;
    }

    // ── Ctrl/Cmd+Enter：提交当前正在写的东西 ──
    if (k === 'enter') {
      const ae = document.activeElement;
      if (ae === $('#ai-text')) { e.preventDefault(); if (typeof aiSend === 'function') aiSend(); return; }
      if (vis($('#qnote'))) { e.preventDefault(); $('#qn-save').click(); return; }
      if (vis($('#note-modal'))) { e.preventDefault(); $('#note-modal-save').click(); return; }
      if (ae && ae.closest && ae.closest('.composer')) {                      // 小记编辑器
        e.preventDefault(); const b = $('#cp-submit'); if (b && !b.disabled) b.click(); return;
      }
      const m = [...document.querySelectorAll('.modal:not(.hidden)')].pop();  // 其它弹层：点它的主按钮
      if (m) { const b = m.querySelector('.btn.primary:not([disabled])'); if (b && b.offsetParent !== null) { e.preventDefault(); b.click(); } }
      return;
    }

    // ── Ctrl/Cmd+K：打开全局搜索 ──
    if (k === 'k') {
      e.preventDefault();
      if (typeof openSearch === 'function') openSearch();
      return;
    }
  });
})();
