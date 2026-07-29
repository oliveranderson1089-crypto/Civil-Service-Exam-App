/* 内容质检 —— 后台「内容质检」分栏。
   全局 $ / esc 由 admin.html 的内联脚本提供（见 eslint.config.mjs 的契约）。

   这一屏**只读**：破坏性动作（--reset / --reparse / 重跑 OCR）不给按钮，
   只给该敲的命令 —— 它们动辄改几千行，要在终端里看着全量新旧对比来做。 */

const QL_TXT = { ok: '正常', warn: '留意', bad: '要处理', unknown: '查不了' };

function qlCard(c) {
  const num = c.total
    ? `<b>${c.n}</b> / ${c.total}<span class="ql-pct">${c.ratio}%</span>`
    : `<b>${c.n === null ? '—' : c.n}</b>`;
  const runway = (c.days !== undefined && c.days !== null)
    ? `<div class="ql-runway">按近 7 天的速度还能撑 <b>${c.days}</b> 天</div>` : '';
  return `<div class="ql-card ${c.state}">
      <div class="ql-top">
        <span class="hl-dot ${c.state === 'bad' ? 'down' : c.state}"></span>
        <b class="hl-name">${esc(c.name)}</b>
        <span class="pill ${c.state === 'ok' ? 'run' : c.state === 'warn' ? 'idle' : 'fail'}">${QL_TXT[c.state] || c.state}</span>
      </div>
      <div class="ql-num">${num}</div>
      ${runway}
      <div class="hl-note">${esc(c.note)}</div>
      ${c.fix ? `<div class="ql-fix"><code>${esc(c.fix)}</code>
        <button class="ubtn" data-copy="${esc(c.fix)}">复制</button></div>` : ''}
    </div>`;
}

async function loadQuality() {
  const box = $('#ql-list');
  try {
    const r = await fetch('/api/admin/quality', { cache: 'no-store' });
    const d = await r.json();
    if (!r.ok) { box.innerHTML = '<p class="ai-tip">读取失败：' + esc(d.error || '') + '</p>'; return; }
    const c = d.counts || {};
    const m = $('#ql-msg');
    const bad = (c.bad || 0) + (c.unknown || 0);
    m.textContent = bad ? `⚠ ${bad} 项要处理` + (c.warn ? `、${c.warn} 项留意` : '')
      : (c.warn ? `△ ${c.warn} 项留意，其余正常` : `✓ ${c.ok || 0} 项全部正常`);
    m.className = 'ai-msg2 ' + (bad ? 'err' : c.warn ? '' : 'ok');
    box.innerHTML = (d.checks || []).map(qlCard).join('');
  } catch (e) {
    box.innerHTML = '<p class="ai-tip">读取失败：' + esc(e.message) + '</p>';
  }
}

$('#ql-list').onclick = async (e) => {
  const b = e.target.closest('[data-copy]');
  if (!b) return;
  try {
    await navigator.clipboard.writeText(b.dataset.copy);
    toast('命令已复制，到终端里跑');
  } catch (_) {
    // 没有 clipboard 权限（http 或旧内核）时退回选中，让人自己复制
    const r = document.createRange();
    r.selectNodeContents(b.previousElementSibling);
    const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    toast('已选中，请手动复制');
  }
};
$('#ql-refresh').onclick = loadQuality;

loadQuality();
