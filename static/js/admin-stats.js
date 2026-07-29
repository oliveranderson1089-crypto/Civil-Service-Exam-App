/* AI 用量与故障报表 —— 后台「AI 用量」分栏。
   全局 $ / esc / adminConfirm 由 admin.html 的内联脚本提供（见 eslint.config.mjs 的契约）。 */

let ST_WIN = 'today';

function stNum(n) {
  // token 动辄几十万，原样铺出来读不出量级
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e4) return (n / 1e4).toFixed(1) + '万';
  return String(n || 0);
}

function stTile(label, val, sub, tone) {
  return `<div class="st-tile${tone ? ' ' + tone : ''}">
      <div class="st-v">${esc(String(val))}</div>
      <div class="st-l">${esc(label)}</div>
      ${sub ? `<div class="st-s">${esc(sub)}</div>` : ''}
    </div>`;
}

/* 排名条：宽度按最大值归一，一眼看出谁是大头 */
function stBars(rows, max) {
  if (!rows.length) return '<p class="ai-tip" style="margin:0;">这个窗口里没有记录。</p>';
  return rows.map(r => {
    const pct = max ? Math.max(2, Math.round(r.tokens * 100 / max)) : 2;
    const fail = r.failed ? `<span class="st-fail">${r.failed} 失败</span>` : '';
    return `<div class="st-bar">
        <div class="st-bar-top"><b>${esc(r.key)}</b>${fail}
          <span class="st-bar-n">${stNum(r.tokens)} token · ${r.calls} 次</span></div>
        <div class="st-bar-track"><i style="width:${pct}%"></i></div>
      </div>`;
  }).join('');
}

function stDaily(rows) {
  if (!rows.length) return '';
  const max = Math.max(...rows.map(r => r.tokens), 1);
  return `<div class="st-spark">` + rows.map(r => {
    const h = Math.max(3, Math.round(r.tokens * 46 / max));
    return `<div class="st-col" title="${esc(r.day)}：${stNum(r.tokens)} token / ${r.calls} 次${r.failed ? '（' + r.failed + ' 失败）' : ''}">
        <i style="height:${h}px" class="${r.failed ? 'bad' : ''}"></i>
        <span>${esc(r.day.slice(5))}</span>
      </div>`;
  }).join('') + `</div>`;
}

async function loadStats() {
  const box = $('#st-body');
  try {
    const r = await fetch('/api/admin/ai/stats?win=' + encodeURIComponent(ST_WIN), { cache: 'no-store' });
    const d = await r.json();
    if (!r.ok) { box.innerHTML = '<p class="ai-tip">读取失败：' + esc(d.error || '') + '</p>'; return; }
    const t = d.totals;
    const maxCaller = Math.max(...(d.by_caller.map(x => x.tokens)), 1);

    box.innerHTML = `
      <div class="st-tiles">
        ${stTile('调用次数', t.calls, t.failed ? t.failed + ' 次失败' : '全部成功')}
        ${stTile('token 总量', stNum(t.tokens), '进 ' + stNum(t.prompt_tokens) + ' / 出 ' + stNum(t.completion_tokens))}
        ${stTile('推理 token', stNum(t.reasoning_tokens), '推理模型单独计')}
        ${stTile('失败率', t.fail_rate + '%', '平均 ' + t.avg_ms + 'ms', t.fail_rate > 10 ? 'bad' : '')}
      </div>
      ${d.daily.length ? `<h3 class="st-h">近 14 天</h3>${stDaily(d.daily)}` : ''}
      <h3 class="st-h">谁在烧（按 token）</h3>
      ${stBars(d.by_caller, maxCaller)}
      <h3 class="st-h">按档位</h3>
      ${stBars(d.by_tier, Math.max(...(d.by_tier.map(x => x.tokens)), 1))}
      ${d.errors.length ? `<h3 class="st-h">失败分类</h3>
        <div class="st-errs">${d.errors.map(e =>
          `<span class="st-chip">${esc(e.kind)} <b>${e.n}</b></span>`).join('')}</div>` : ''}
      ${d.recent_failures.length ? `<h3 class="st-h">最近的失败</h3>
        <div class="st-recent">${d.recent_failures.map(f =>
          `<div><span class="st-t">${esc((f.ts || '').slice(5, 16))}</span>
             ${esc(f.caller || '?')} · ${esc(f.tier || '')} · <b>${esc(f.err_kind || '')}</b></div>`).join('')}</div>` : ''}
      <p class="ai-tip" style="margin-top:16px;">口径：<b>一次重试算一次调用</b>——重试是实打实又发了一次请求、又烧了一次 token。
        失败行的 token 多半是 0（请求就没成功），所以 token 总量看的是成功的那些。记录保留 90 天。</p>`;
  } catch (e) {
    box.innerHTML = '<p class="ai-tip">读取失败：' + esc(e.message) + '</p>';
  }
}

$('#st-win').onclick = (e) => {
  const b = e.target.closest('[data-win]');
  if (!b) return;
  ST_WIN = b.dataset.win;
  document.querySelectorAll('#st-win [data-win]').forEach(x => x.classList.toggle('on', x === b));
  loadStats();
};
$('#st-refresh').onclick = loadStats;

loadStats();
