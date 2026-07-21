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

  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented) return;                 // 已有更专门的处理接手了
    const mod = e.ctrlKey || e.metaKey;
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
