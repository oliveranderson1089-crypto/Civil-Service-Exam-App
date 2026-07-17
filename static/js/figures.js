/* 资料分析的材料：表格 / 柱状图 / 折线图 / 饼图（内联 SVG）
 *
 * 由 app.js 按它自己的区段边界切出（原 L5673-6039）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, DT_L, PL_MOD_COLOR, api, appConfirm, back,
   bindBar, c, composing, dtAns, dtChosen, dtExp,
   dtGen, dtIsTest, dtItems, dtModeBar, dtResults, dtRevealed,
   dtRevealedAt, dtScore, dtSubmitted, esc, loadDtest, toast */

/* ---------- 资料分析的材料：表格 / 柱状图 / 折线图 / 饼图（内联 SVG，无外部库） ----------
   颜色用 CSS 变量（--c1..--c4），日/夜间自动切换，不用重新渲染。配色经色盲分离度与对比度校验。 */
function dtNum(v) { return (Math.round(v * 100) / 100).toLocaleString('zh-CN'); }
function dtLegend(series) {
  if (series.length < 2) return '';                 // 单系列不需要图例（标题已经说明它是什么）
  return `<div class="ch-lg">${series.map((s, i) =>
    `<span><i style="background:var(--c${i + 1})"></i>${esc(s.name)}</span>`).join('')}</div>`;
}
function dtChart(m) {
  const W = 560, H = 250, PL = 52, PR = 14, PT = 14, PB = 34;   // 画布与内边距
  const iw = W - PL - PR, ih = H - PT - PB;
  const labels = m.labels || [], series = m.series || [];
  if (m.type === 'pie') {
    const data = (series[0] || {}).data || [];
    const tot = data.reduce((a, b) => a + b, 0) || 1;
    let a0 = -Math.PI / 2, arcs = '';
    data.forEach((v, i) => {
      const a1 = a0 + v / tot * Math.PI * 2, big = (a1 - a0) > Math.PI ? 1 : 0;
      const R = 92, cx = 150, cy = 125;
      const x0 = cx + R * Math.cos(a0), y0 = cy + R * Math.sin(a0);
      const x1 = cx + R * Math.cos(a1), y1 = cy + R * Math.sin(a1);
      // 2px 表面间隙：扇区之间留一条底色描边，不靠颜色硬碰硬
      arcs += `<path d="M${cx},${cy} L${x0.toFixed(1)},${y0.toFixed(1)} A${R},${R} 0 ${big} 1 ${x1.toFixed(1)},${y1.toFixed(1)} Z"
        fill="var(--c${(i % 4) + 1})" stroke="var(--card)" stroke-width="2"><title>${esc(labels[i] || '')} ${dtNum(v)}${esc(m.unit || '')}</title></path>`;
      const am = (a0 + a1) / 2, lx = cx + (R + 26) * Math.cos(am), ly = cy + (R + 26) * Math.sin(am);
      arcs += `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" class="ch-dl" text-anchor="${Math.cos(am) < -0.1 ? 'end' : (Math.cos(am) > 0.1 ? 'start' : 'middle')}">${esc(labels[i] || '')} ${dtNum(v)}${esc(m.unit || '')}</text>`;
      a0 = a1;
    });
    return `<svg viewBox="0 0 ${W} ${H}" class="ch" role="img">${arcs}</svg>`;
  }
  const all = series.flatMap(s => s.data);
  const max = Math.max(...all, 0), min = Math.min(...all, 0);
  const top = max > 0 ? max * 1.12 : 1, bot = min < 0 ? min * 1.12 : 0;
  // band 刻度（每个类别占一格、点画在格子中心）：柱组不会压住 Y 轴刻度，也不会被右边裁掉
  const band = iw / Math.max(labels.length, 1);
  const X = (i) => PL + band * (i + 0.5);
  const Y = (v) => PT + ih - (v - bot) / (top - bot || 1) * ih;
  let g = '';
  for (let k = 0; k <= 4; k++) {                     // 网格线：弱化，不抢笔迹
    const y = PT + ih * k / 4, v = top - (top - bot) * k / 4;
    g += `<line x1="${PL}" y1="${y.toFixed(1)}" x2="${W - PR}" y2="${y.toFixed(1)}" class="ch-gr"/>
      <text x="${PL - 8}" y="${(y + 4).toFixed(1)}" class="ch-ax" text-anchor="end">${dtNum(v)}</text>`;
  }
  g += labels.map((L, i) => `<text x="${X(i).toFixed(1)}" y="${H - 12}" class="ch-ax" text-anchor="middle">${esc(L)}</text>`).join('');
  let marks = '';
  if (m.type === 'bar') {
    const bw = Math.min(28, band * 0.72 / Math.max(series.length, 1));   // 一格里放得下这组柱子
    labels.forEach((L, i) => series.forEach((s, j) => {
      const v = s.data[i], x = X(i) - (series.length * bw) / 2 + j * bw, y = Y(Math.max(v, 0)), h = Math.abs(Y(v) - Y(0));
      // 数据端 4px 圆角、锚在基线；相邻柱之间留 2px 底色间隙
      marks += `<rect x="${(x + 1).toFixed(1)}" y="${y.toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${Math.max(h, 1).toFixed(1)}"
        rx="4" fill="var(--c${(j % 4) + 1})"><title>${esc(L)} · ${esc(s.name)} ${dtNum(v)}${esc(m.unit || '')}</title></rect>`;
      if (series.length * labels.length <= 8)        // 点数少才直接标数值，多了就只留悬停
        marks += `<text x="${(x + bw / 2).toFixed(1)}" y="${(y - 6).toFixed(1)}" class="ch-dl" text-anchor="middle">${dtNum(v)}</text>`;
    }));
  } else {
    series.forEach((s, j) => {
      const pts = s.data.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
      marks += `<polyline points="${pts}" fill="none" stroke="var(--c${(j % 4) + 1})" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
      marks += s.data.map((v, i) => `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="4.5"
        fill="var(--c${(j % 4) + 1})" stroke="var(--card)" stroke-width="2"><title>${esc(labels[i])} · ${esc(s.name)} ${dtNum(v)}${esc(m.unit || '')}</title></circle>`).join('');
    });
  }
  return `<svg viewBox="0 0 ${W} ${H}" class="ch" role="img">${g}${marks}</svg>`;
}
function dtTable(m) {
  return `<table class="ch-tb"><thead><tr>${(m.headers || []).map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
    <tbody>${(m.rows || []).map(r => `<tr>${r.map((c, i) => `<td${i ? ' class="num"' : ''}>${esc(String(c))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}
let _dtLastMat = '';
function dtMaterial(m, i) {
  if (!m) { _dtLastMat = ''; return ''; }
  const key = JSON.stringify(m);
  if (key === _dtLastMat) return '<div class="dt-same">↑ 根据上面这份材料作答</div>';  // 两题共用一份材料，不重复渲染
  _dtLastMat = key;
  const head = `<div class="dt-mt">${esc(m.title || '根据下列资料，回答问题')}${m.unit ? `<span>单位：${esc(m.unit)}</span>` : ''}</div>`;
  if (m.type === 'table') return `<div class="dt-mat">${head}${dtTable(m)}</div>`;
  // 图表另附「看数据表」，方便核对数字（也是无障碍要求：不能只靠图形）
  const tb = { headers: ['项目', ...(m.labels || [])],
    rows: (m.series || []).map(s => [s.name, ...s.data.map(v => dtNum(v))]) };
  return `<div class="dt-mat">${head}${dtChart(m)}${dtLegend(m.series || [])}
    <button class="ch-tbtn" data-chtb="${i}">📋 看数据表</button>
    <div class="ch-tbwrap hidden" id="chtb-${i}">${dtTable(tb)}</div></div>`;
}

function renderDtest() {
  _dtLastMat = '';
  const qs = dtItems.map((it, i) => {
    const revealed = dtRevealedAt(i);
    const isFig = !!(it.figs && it.figs.opts);
    const opts = isFig
      ? it.figs.opts.map((svg, j) => {
        const L = DT_L[j], chosen = dtChosen[i] === L, isAns = (dtAns(i) || '').toUpperCase() === L;
        let cls = 'dt-opt dt-figopt';
        if (revealed) { if (isAns) cls += ' correct'; else if (chosen) cls += ' wrong'; }
        else if (chosen) cls += ' chosen';
        return `<button class="${cls}" data-dtq="${i}" data-dtl="${L}" ${revealed ? 'disabled' : ''}>
          <span class="dt-figl">${L}</span>${svg}</button>`;
      }).join('')
      : (it.options || []).map((o, j) => {
        const L = DT_L[j], chosen = dtChosen[i] === L, isAns = (dtAns(i) || '').toUpperCase() === L;
        let cls = 'dt-opt';
        if (revealed) { if (isAns) cls += ' correct'; else if (chosen) cls += ' wrong'; }
        else if (chosen) cls += ' chosen';
        return `<button class="${cls}" data-dtq="${i}" data-dtl="${L}" ${revealed ? 'disabled' : ''}>${esc(o)}</button>`;
      }).join('');
    const e = dtExp(i);
    const exp = revealed ? `<div class="dt-exp"><b>正确答案 ${esc(dtAns(i))}</b>${e.explain ? ' · ' + esc(e.explain) : ''}${e.source ? ` <span class="dt-src">${esc(e.source)}</span>` : ''}</div>` : '';
    const mod = it.module ? `<span class="dt-mod" style="background:${PL_MOD_COLOR[it.module] || '#6b7280'}">${esc(it.module)}</span>` : '';
    const mat = dtMaterial(it.material, i);
    const seq = isFig ? `<div class="dt-seq">${it.figs.seq.join('')}<span class="dt-qm">?</span></div>` : '';
    return `<div class="dt-q">${mat}<div class="dt-qt">${mod}${i + 1}. ${esc(it.q)}</div>${seq}
      <div class="dt-opts${isFig ? ' dt-figs' : ''}">${opts}</div>${exp}</div>`;
  }).join('');
  let foot;
  if (dtSubmitted) {
    foot = `<div class="dt-score">得分 ${dtScore()} / ${dtItems.length}</div>
       <button class="btn" id="dt-again">🔄 换一套新题</button>`;
  } else if (dtIsTest()) {
    foot = `<button class="btn primary" id="dt-submit">交卷看结果</button>`;
  } else {
    const done = dtItems.filter((_, i) => dtRevealed[i]).length;
    foot = `<div class="dt-prog2">已做 ${done} / ${dtItems.length}</div>` +
      (done === dtItems.length ? `<button class="btn primary" id="dt-finish">看结果并记录</button>` : '');
  }
  $('#dt-body').innerHTML = (dtSubmitted ? '' : dtModeBar()) + `<div class="dt-list">${qs}</div><div class="dt-foot">${foot}</div>`;
  if (dtSubmitted) $('#dt-again').onclick = async () => { if (await appConfirm('重新出一套？当前作答会清空。')) dtGen(true); };
  else { const s = $('#dt-submit'); if (s) s.onclick = dtSubmit; const f = $('#dt-finish'); if (f) f.onclick = dtFinish; bindBar(); }
}
async function dtRecord() {
  // 把本次作答交给服务端判分并留档
  try {
    const ans = {}; dtItems.forEach((_, i) => ans[i] = dtChosen[i] || '');
    return await api('/api/dtest/grade', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answers: ans }) });
  } catch (e) { toast(e.message, true); return null; }
}
async function dtSubmit() {   // 测试模式交卷
  const un = dtItems.findIndex((_, i) => !dtChosen[i]);
  if (un >= 0) { toast('第 ' + (un + 1) + ' 题还没选', true); return; }
  const btn = $('#dt-submit'); if (btn) { btn.disabled = true; btn.textContent = '判分中…'; }
  const d = await dtRecord();
  if (!d) { if (btn) { btn.disabled = false; btn.textContent = '交卷看结果'; } return; }
  dtResults = d.results || [];
  dtSubmitted = true; renderDtest();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
async function dtFinish() {   // 背题模式做完，记录成绩
  await dtRecord();
  dtSubmitted = true; renderDtest();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
$('#dt-body').addEventListener('click', e => {
  const tb = e.target.closest('[data-chtb]');          // 图表下方的「看数据表」
  if (tb) {
    const box = $('#chtb-' + tb.dataset.chtb);
    const hidden = box.classList.toggle('hidden');
    tb.textContent = hidden ? '📋 看数据表' : '📊 收起数据表';
    return;
  }
  const o = e.target.closest('[data-dtq]'); if (!o) return;
  const i = +o.dataset.dtq;
  if (dtRevealedAt(i)) return;              // 已揭晓的题不能再改
  dtChosen[i] = o.dataset.dtl;
  if (!dtIsTest()) {
    dtRevealed[i] = true;                   // 背题模式：选完立刻揭晓这题
    if ((dtAns(i) || '').toUpperCase() !== dtChosen[i]) {   // 选错了 → 自动进错题本
      api('/api/dtest/wrong', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ idx: i, choice: dtChosen[i] }),
      }).then(d => { if (d.added) toast('这题错了，已收进错题本'); }).catch(() => {});
    }
  }
  renderDtest();
});
/* 测试记录：列表 + 回看某次作答 */
async function openDtRecords() {
  $('#dt-body').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/dtest/records');
    const list = d.items.length ? d.items.map(r => `
      <div class="dtr-row" data-dtrec="${r.id}">
        <span class="dtr-when">${esc((r.created_at || r.date || '').slice(5, 16))}</span>
        <span class="dtr-score ${r.score >= r.total * 0.6 ? 'ok' : 'bad'}">${r.score} / ${r.total}</span>
        <span class="dtr-go">回看 ›</span></div>`).join('')
      : '<p class="empty">还没有测试记录。做一次巩固测试，交卷后就会留档。</p>';
    $('#dt-body').innerHTML = `<div class="dtr-top"><button class="pl-link-btn" id="dt-back">‹ 返回测试</button><b>测试记录</b></div>${list}`;
    $('#dt-back').onclick = loadDtest;
  } catch (e) { $('#dt-body').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
async function openDtRecord(rid) {
  $('#dt-body').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/dtest/record/' + rid);
    const qs = (d.detail || []).map((it, i) => {
      const opts = (it.options || []).map((o, j) => {
        const L = DT_L[j], isAns = (it.answer || '').toUpperCase() === L, mine = (it.your || '').toUpperCase() === L;
        let cls = 'dt-opt'; if (isAns) cls += ' correct'; else if (mine) cls += ' wrong';
        return `<button class="${cls}" disabled>${esc(o)}</button>`;
      }).join('');
      return `<div class="dt-q"><div class="dt-qt">${i + 1}. ${esc(it.q)}</div><div class="dt-opts">${opts}</div>
        <div class="dt-exp"><b>正确答案 ${esc(it.answer)}</b>${it.your ? ' · 你选了 ' + esc(it.your) : ''}${it.explain ? ' · ' + esc(it.explain) : ''}${it.source ? ` <span class="dt-src">${esc(it.source)}</span>` : ''}</div></div>`;
    }).join('');
    $('#dt-body').innerHTML = `<div class="dtr-top"><button class="pl-link-btn" id="dt-back2">‹ 返回记录</button>
      <b>${esc((d.created_at || '').slice(5, 16))} · 得分 ${d.score}/${d.total}</b></div><div class="dt-list">${qs}</div>`;
    $('#dt-back2').onclick = openDtRecords;
  } catch (e) { $('#dt-body').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#dt-body').addEventListener('click', e => {
  const r = e.target.closest('[data-dtrec]'); if (r) openDtRecord(+r.dataset.dtrec);
});

async function loadDaily() {
  $('#tk-daily-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/daily_tasks');
    $('#tk-daily-prog').textContent = d.total ? `今日进度 ${d.done_n} / ${d.total}${d.done_n === d.total ? ' 🎉 全部完成！' : ''}` : '';
    $('#tk-daily-list').innerHTML = d.items.length ? d.items.map(it => `
      <div class="tk-item ${it.done ? 'done' : ''}" data-td="${it.id}">
        <span class="tk-check">${it.done ? '✓' : ''}</span>
        <span class="tk-text">${esc(it.text)}</span>
        <button class="tk-del" data-tddel="${it.id}">🗑</button>
      </div>`).join('') : '<p class="empty">还没有每日任务，下面加一条吧～</p>';
  } catch (e) { $('#tk-daily-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#tk-daily-list').addEventListener('click', async e => {
  const del = e.target.closest('[data-tddel]');
  if (del) { e.stopPropagation(); if (!(await appConfirm('删除这个每日任务？'))) return; try { await api('/api/daily_tasks/templates/' + del.dataset.tddel, { method: 'DELETE' }); loadDaily(); } catch (er) { toast(er.message, true); } return; }
  const it = e.target.closest('[data-td]'); if (!it) return;
  try { await api('/api/daily_tasks/' + it.dataset.td + '/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); loadDaily(); } catch (er) { toast(er.message, true); }
});
$('#tk-daily-add').onclick = async () => {
  const v = $('#tk-daily-in').value.trim(); if (!v) return;
  try { await api('/api/daily_tasks/templates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: v }) }); $('#tk-daily-in').value = ''; loadDaily(); } catch (e) { toast(e.message, true); }
};
$('#tk-daily-in').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') $('#tk-daily-add').click(); });

let tkMembers = [], tkMeId = 0;
/* 先看组队状态：没组队 → 组队 UI；已组队 → 队头 + 互监清单 */
async function loadShared() {
  $('#tk-team').innerHTML = '<p class="empty">加载中…</p>';
  $('#tk-board').classList.add('hidden');
  try {
    const t = await api('/api/team');
    tkMeId = t.me_id;
    if (!t.team) { renderTeamSetup(t); return; }
    renderTeamHeader(t);
    $('#tk-board').classList.remove('hidden');
    await loadSharedBoard();
  } catch (e) { $('#tk-team').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function renderTeamSetup(t) {
  const inc = (t.incoming || []).filter(r => r.kind === 'join').map(r => `
    <div class="tm-req"><span>📨 <b>${esc(shortName(r.from_name))}</b> 想和你组队互监</span>
      <span class="tm-acts"><button class="btn tiny primary" data-tmacc="${r.id}">接受</button>
      <button class="btn tiny" data-tmrej="${r.id}">拒绝</button></span></div>`).join('');
  const out = (t.outgoing || []).filter(r => r.kind === 'join').map(r => `
    <div class="tm-req"><span>⏳ 已向 <b>${esc(shortName(r.to_name))}</b> 发出组队申请，等对方接受</span>
      <button class="btn tiny" data-tmcancel="${r.id}">撤回</button></div>`).join('');
  $('#tk-team').innerHTML = `
    <div class="pd-intro">互监需要先和搭档组队：搜对方的账号发起邀请，对方接受即可互相监督。</div>
    <div class="tm-search"><input id="tm-q" placeholder="搜账号 / 用户名 / ID"><button class="btn primary" id="tm-search-btn">搜索</button></div>
    <div id="tm-results"></div>
    ${inc ? `<div class="tm-sec"><div class="tm-sec-t">收到的组队申请</div>${inc}</div>` : ''}
    ${out ? `<div class="tm-sec"><div class="tm-sec-t">我发出的申请</div>${out}</div>` : ''}`;
  $('#tm-search-btn').onclick = tmSearch;
  $('#tm-q').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') tmSearch(); });
}
function renderTeamHeader(t) {
  const p = t.team.partner;
  const disIn = (t.incoming || []).find(r => r.kind === 'disband');
  const disOut = (t.outgoing || []).find(r => r.kind === 'disband');
  let dis = '';
  if (disIn) dis = `<div class="tm-req tm-warn"><span>⚠️ <b>${esc(shortName(p ? p.name : '搭档'))}</b> 申请解散组队</span>
    <span class="tm-acts"><button class="btn tiny primary" data-tmacc="${disIn.id}">同意解散</button>
    <button class="btn tiny" data-tmrej="${disIn.id}">不同意</button></span></div>`;
  else if (disOut) dis = `<div class="tm-req"><span>⏳ 已申请解散，等对方同意</span>
    <button class="btn tiny" data-tmcancel="${disOut.id}">撤回</button></div>`;
  const st = t.study || { streak: 0, total: 0 };
  $('#tk-team').innerHTML = `
    <div class="tm-head"><span>🤝 已与 <b>${esc(shortName(p ? p.name : '搭档'))}</b> 组队互监</span>
      ${disOut || disIn ? '' : '<button class="btn tiny" id="tm-disband">解散组队</button>'}</div>
    <div class="tm-streak">🔥 连续学习 <b>${st.streak}</b> 天 · 累计 <b>${st.total}</b> 天</div>
    ${dis}`;
  if ($('#tm-disband')) $('#tm-disband').onclick = tmDisband;
}
async function tmSearch() {
  const q = $('#tm-q').value.trim(); if (!q) return;
  $('#tm-results').innerHTML = '<p class="empty">搜索中…</p>';
  try {
    const d = await api('/api/team/search?q=' + encodeURIComponent(q));
    $('#tm-results').innerHTML = d.users.length ? d.users.map(u => `
      <div class="tm-res"><span>${esc(u.name)} <i class="tm-uid">ID ${u.id}</i></span>
        ${u.in_team ? '<span class="tm-busy">已组队</span>' : `<button class="btn tiny primary" data-tminvite="${u.id}">邀请组队</button>`}</div>`).join('')
      : '<p class="empty">没找到这个账号</p>';
  } catch (e) { $('#tm-results').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
async function tmDisband() {
  if (!(await appConfirm('向搭档发出解散组队申请？对方同意后才会解散。'))) return;
  try { await api('/api/team/disband', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); toast('已发出解散申请'); loadShared(); }
  catch (e) { toast(e.message, true); }
}
$('#tk-team').addEventListener('click', async e => {
  const inv = e.target.closest('[data-tminvite]');
  const acc = e.target.closest('[data-tmacc]');
  const rej = e.target.closest('[data-tmrej]');
  const can = e.target.closest('[data-tmcancel]');
  try {
    if (inv) { await api('/api/team/request', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to_uid: +inv.dataset.tminvite }) }); toast('已发出组队申请'); loadShared(); }
    else if (acc) { const r = await api('/api/team/request/' + acc.dataset.tmacc + '/accept', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); toast(r.disbanded ? '已解散组队' : '已组队 🤝'); loadShared(); }
    else if (rej) { await api('/api/team/request/' + rej.dataset.tmrej + '/reject', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); loadShared(); }
    else if (can) { await api('/api/team/request/' + can.dataset.tmcancel + '/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); loadShared(); }
  } catch (er) { toast(er.message, true); }
});
async function loadSharedBoard() {
  $('#tk-shared-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/shared_todos');
    tkMembers = d.members || [];
    tkMeId = d.me_id;
    // 表头：每位互监成员一列打勾位；自己那列标「我」，只能由搭档来勾
    $('#tk-shared-head').innerHTML = tkMembers.length
      ? `<span class="tk-hd-text">待办</span><span class="tk-hd-ms">` + tkMembers.map(m =>
        `<span class="tk-hd-m ${m.id === d.me_id ? 'me' : ''}" title="${esc(m.name)}">${m.id === d.me_id ? '我' : esc(initials(m.name))}</span>`).join('') + `</span>`
      : '';
    $('#tk-shared-list').innerHTML = d.items.length ? d.items.map(it => {
      const ids = it.done_ids || [];
      const byMap = it.done_by_map || {};
      const boxes = tkMembers.map(m => {
        const on = ids.includes(m.id), mine = m.id === d.me_id;
        const tip = on ? `${m.name}（由 ${byMap[m.id] || '?'} 确认）`
          : (mine ? '自己不能勾自己，等搭档来确认' : `确认 ${m.name} 已完成`);
        return `<button class="tk-box ${on ? 'on' : ''} ${mine ? 'mine' : ''}"
          data-tsbox="${it.id}" data-tsuser="${m.id}" title="${esc(tip)}">${on ? '✓' : (mine ? '🔒' : '')}</button>`;
      }).join('');
      const who = tkMembers.filter(m => ids.includes(m.id))
        .map(m => `${shortName(m.name)}（${shortName(byMap[m.id] || '?')} 确认）`);
      const all = tkMembers.length && tkMembers.every(m => ids.includes(m.id));
      return `<div class="tk-item tk-multi ${all ? 'done' : ''}" data-ts="${it.id}">
        <span class="tk-text">${it.is_plan ? '<i class="ts-plan">📅 规划</i> ' : ''}${esc(it.text)}<span class="tk-who">${it.is_plan ? '来自 ' + esc(shortName(it.created_by)) + ' 的今日计划' : '发起 ' + esc(shortName(it.created_by))}${all ? ' · 🎉 双方都已确认' : (who.length ? ' · ✅ ' + esc(who.join('、')) : '')}</span></span>
        <span class="tk-boxes">${boxes}</span>
        ${it.is_plan ? '' : `<button class="tk-del" data-tsdel="${it.id}">🗑</button>`}
      </div>`;
    }).join('') : '<p class="empty">还没有共享待办，加一条大家一起监督～</p>';
  } catch (e) { $('#tk-shared-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
function shortName(n) { n = n || ''; n = n.split('@')[0]; return n.length > 6 ? n.slice(0, 5) + '…' : n; }
// 表头列宽只有一个勾选框那么宽，用 2 个字符当列名（完整名在 title 与成员面板里）
function initials(n) { n = (n || '').split('@')[0]; return n.slice(0, 4); }
$('#tk-shared-list').addEventListener('click', async e => {
  const del = e.target.closest('[data-tsdel]');
  if (del) { e.stopPropagation(); if (!(await appConfirm('删除这条共享待办？'))) return; try { await api('/api/shared_todos/' + del.dataset.tsdel, { method: 'DELETE' }); loadSharedBoard(); } catch (er) { toast(er.message, true); } return; }
  const box = e.target.closest('[data-tsbox]'); if (!box) return;
  if (+box.dataset.tsuser === tkMeId) { toast('自己不能给自己打勾，等搭档来确认 🤝', true); return; }
  try {
    await api('/api/shared_todos/' + box.dataset.tsbox + '/toggle', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: +box.dataset.tsuser })
    });
    loadSharedBoard();
  } catch (er) { toast(er.message, true); }
});
$('#tk-shared-add').onclick = async () => {
  const v = $('#tk-shared-in').value.trim(); if (!v) return;
  try { await api('/api/shared_todos', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: v }) }); $('#tk-shared-in').value = ''; loadSharedBoard(); } catch (e) { toast(e.message, true); }
};
$('#tk-shared-in').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') $('#tk-shared-add').click(); });
