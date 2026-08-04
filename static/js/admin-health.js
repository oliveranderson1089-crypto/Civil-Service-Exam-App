/* 产出健康看板 —— 后台第一屏。
   admin.html 是独立页面（不进主应用的 bundle），$ / esc / toast / adminConfirm
   都由它的内联脚本先定义好，这里直接用。 */

const HL_DOT = { ok: '正常', warn: '待观察', down: '断供', unknown: '未知' };

function hlMsg(t, ok) {
  const m = $('#hl-msg');
  m.textContent = t;
  m.className = 'ai-msg2 ' + (ok === true ? 'ok' : ok === false ? 'err' : '');
}

function hlCard(d) {
  const lag = d.lag === null || d.lag === undefined ? ''
    : (d.lag === 0 ? '今天' : d.lag + ' 天前');
  // 有问题才给按钮：正常的域不需要人动手，一屏扫过去只留该处理的
  const acts = d.state === 'ok' ? '' : `
      <div class="hl-acts">
        <button class="ubtn" data-run="${esc(d.svc)}">立即补跑</button>
        <button class="ubtn" data-jl="${esc(d.svc)}">看日志</button>
      </div>`;
  return `
    <div class="hl-card ${d.state}">
      <div class="hl-top">
        <span class="hl-dot ${d.state}"></span>
        <b class="hl-name">${esc(d.name)}</b>
        <span class="pill ${d.state === 'ok' ? 'run' : d.state === 'warn' ? 'idle' : 'fail'}">${HL_DOT[d.state] || d.state}</span>
      </div>
      <div class="hl-num">
        <span><b>${d.today_n}</b> 今日</span>
        ${d.usable === undefined || d.usable === d.total
          // 「存量」里混着发不出去的题（题库里存疑的占了 19%）就得分开写 ——
          // 一个数字同时当「有多少题」和「有多少题能做」用，迟早骗到自己
          ? `<span><b>${d.total}</b> 存量</span>`
          : `<span><b>${d.usable}</b> 可用</span><span class="hl-dim">${d.total} 库存</span>`}
        <span>最新 ${esc(d.last || '—')}${lag ? ' · ' + lag : ''}</span>
      </div>
      <div class="hl-note">${esc(d.note || '')}</div>
      ${d.hint ? `<div class="hl-hint">${esc(d.hint)}</div>` : ''}
      ${acts}
    </div>`;
}

async function loadHealth() {
  const box = $('#hl-list');
  try {
    const r = await fetch('/api/admin/health', { cache: 'no-store' });
    const d = await r.json();
    if (!r.ok) { box.innerHTML = '<p class="ai-tip">读取失败：' + esc(d.error || '') + '</p>'; return; }
    const c = d.counts || {};
    const bad = (c.down || 0) + (c.unknown || 0);
    hlMsg(bad
      ? '⚠ ' + bad + ' 个内容域断供' + (c.warn ? '、' + c.warn + ' 个待观察' : '') + '（' + d.today + '）'
      : (c.warn ? '△ ' + c.warn + ' 个待观察，其余正常（' + d.today + '）'
                : '✓ ' + (c.ok || 0) + ' 个内容域今天都有产出（' + d.today + '）'),
      bad ? false : !c.warn);
    box.innerHTML = (d.domains || []).map(hlCard).join('');
  } catch (e) {
    box.innerHTML = '<p class="ai-tip">读取失败：' + esc(e.message) + '</p>';
  }
}

$('#hl-list').onclick = async (e) => {
  const run = e.target.closest('[data-run]');
  const jl = e.target.closest('[data-jl]');
  if (run) {
    const n = run.dataset.run;
    // 定时任务是 oneshot：restart 它 = 立刻跑一次（restart 那个 .timer 只会重置计时器，
    // 任务一次都不会跑 —— 所以这里对准的是 .service）
    if (!await adminConfirm('立刻运行一次「' + n + '」？\n\n它会实际去抓取/生成内容，可能要几分钟，\n期间会消耗 AI 额度。', '补跑任务')) return;
    hlMsg('正在启动 ' + n + '…');
    try {
      const r = await fetch('/api/admin/services/restart', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ names: [n] })
      });
      const d = await r.json();
      const v = (d.results || {})[n];
      if (r.ok && v && v.ok) {
        hlMsg('✓ 已启动 ' + n + '，跑完再刷新看结果', true);
      } else {
        hlMsg('✗ ' + ((v && v.msg) || d.error || '启动失败'), false);
      }
    } catch (err) { hlMsg('✗ ' + err.message, false); }
    return;
  }
  if (jl) {
    const box = $('#hl-journal');
    box.classList.remove('hidden');
    box.textContent = '读取 ' + jl.dataset.jl + ' 的日志…';
    try {
      const d = await (await fetch('/api/admin/services/journal/' + encodeURIComponent(jl.dataset.jl))).json();
      box.textContent = d.text || d.error || '(无日志)';
      box.scrollTop = box.scrollHeight;
    } catch (err) { box.textContent = '读取失败：' + err.message; }
  }
};

$('#hl-refresh').onclick = () => { hlMsg('刷新中…'); loadHealth(); };

loadHealth();
