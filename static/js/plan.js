/* 任务清单 / 备考规划 / 40 天冲刺路线 / 计划记录
 *
 * 由 app.js 按它自己的区段边界切出（原 L5253-5584）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, appConfirm, back, composing, esc,
   loadDaily, loadShared, ntfGo, push, toast */

/* ============= 任务清单（每日任务 + 互监待办） ============= */
function openTasks() { push({ view: 'tasks', title: '任务清单' }); tkSwitch('plan'); }
function tkSwitch(t) {
  // 必须限定在本视图内：.tk-tab 这个类名被范文/批改/复习那几组页签复用，
  // 全局 querySelectorAll 会把它们的高亮一起清掉
  document.querySelectorAll('#view-tasks .tk-tab').forEach(x => x.classList.toggle('active', x.dataset.tkt === t));
  ['plan', 'daily', 'shared'].forEach(k => $('#tk-' + k).classList.toggle('hidden', k !== t));
  if (t === 'plan') loadPlan(); else if (t === 'daily') loadDaily(); else loadShared();
}
$('#view-tasks').addEventListener('click', e => {
  const tab = e.target.closest('[data-tkt]'); if (tab) tkSwitch(tab.dataset.tkt);
});

/* ================= 备考规划：AI 按真实学情排当天计划 ================= */
const PL_MOD_COLOR = {
  '复习': '#12b886', '错题': '#c0392b', '申论': '#c92a2a', '常识判断': '#e8590c',
  '言语理解': '#2b6fd6', '数量关系': '#7a5cc0', '资料分析': '#0b7285', '判断推理': '#5b6cf0',
  '政治理论': '#b7791f',
};
let plProfile = null, plEditing = false;

/* ---------- 40 天冲刺路线：今天第几天、什么阶段、今日定额、正确率目标 ---------- */
let plRoadOpen = false;
function renderRoadmap(rm, prof) {
  const box = $('#pl-road');
  if (!rm || (!rm.phase && !rm.over)) {           // 没开启（或还没到开始日）
    box.innerHTML = `<div class="plr-off">
      <div class="plr-off-t">🚀 40 天冲刺路线</div>
      <div class="plr-off-d">对标「140 分」强度，但按 <b>6 天推进 + 第 7 天复盘日</b> 排，能扛完全程。
        分三段：打牢根基(1-12) → 专项拔高(13-28) → 套题强化(29-40)；
        每天给你行测题量定额、申论安排、正确率目标，积累类任务直接用 App 里现成的内容。</div>
      <button class="btn primary" id="plr-start">开启 40 天冲刺</button>
    </div>`;
    return;
  }
  if (rm.over) {
    box.innerHTML = `<div class="plr-off">
      <div class="plr-off-t">🏁 40 天冲刺已走完（第 ${rm.day} 天）</div>
      <div class="plr-off-d">${esc(rm.data.after || '')}</div>
      <button class="btn primary" id="plr-start">再开一轮</button>
    </div>`;
    return;
  }
  const ph = rm.phase, dd = rm.data;
  const pct = Math.round(rm.day / rm.days * 100);
  const quota = Object.entries(ph.quota).map(([k, v]) =>
    `<span class="plr-q"><b>${v}</b> ${esc(k)}</span>`).join('');
  const acc = Object.entries(ph.accuracy).map(([k, v]) =>
    `<tr><td>${esc(k)}</td><td><b>${esc(v)}</b></td></tr>`).join('');
  box.innerHTML = `
    <div class="plr-top">
      <span class="plr-day">第 <b>${rm.day}</b> / ${rm.days} 天</span>
      <span class="plr-ph">${esc(ph.key)} · ${esc(ph.name)}</span>
      ${rm.review_day ? '<span class="plr-rv">★ 今天是复盘日</span>' : ''}
      <button class="plr-more" id="plr-more">${plRoadOpen ? '收起' : '看路线'}</button>
    </div>
    <div class="plr-bar"><i style="width:${pct}%"></i></div>
    <div class="plr-focus">${esc(ph.focus)}</div>
    ${rm.review_day ? `<div class="plr-tip">上午一套行测限时套题（严格 120 分钟）→ 下午全套订正 + 错因归因 → 晚上错题过筛，然后<b>休半天</b>。今天别堆新知识。</div>` : ''}
    <div class="plr-quota"><span class="plr-qt">今日行测定额</span>${quota}</div>
    <div class="plr-sl">📝 申论：${esc(ph.shenlun)}</div>
    <div class="plr-detail ${plRoadOpen ? '' : 'hidden'}">
      <div class="plr-sec">🎯 本阶段正确率目标</div>
      <table class="plr-tb">${acc}</table>
      <div class="plr-sec">📌 模块优先级</div>
      <div class="plr-p">${esc(dd.priority || '')}<div class="plr-why">${esc(dd.priority_why || '')}</div></div>
      <div class="plr-sec">🔁 本阶段每周要做到</div>
      <ul class="plr-ul">${(ph.weekly || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
      <div class="plr-sec">📚 每日固定动作（用 App 现成内容）</div>
      <ul class="plr-ul">${(dd.fixed || []).map(x =>
        `<li>${esc(x.t)}${x.link ? ` <i class="pl-go" data-plgo="${esc(x.link)}">去做 ›</i>` : ''}
          <span class="plr-note">${esc(x.note || '')}</span></li>`).join('')}</ul>
      <div class="plr-sec">⏰ 节奏</div>
      <div class="plr-p">${esc(dd.rhythm || '')}</div>
      <div class="plr-sec">🧱 纪律（原贴的 140 分强度，挑能长期执行的）</div>
      <ul class="plr-ul">${(dd.discipline || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
      <div class="plr-sec">🏁 阶段产出</div>
      <div class="plr-p">${esc(ph.output || '')}</div>
      <div class="plr-sec">➡️ 40 天之后</div>
      <div class="plr-p">${esc(dd.after || '')}</div>
      <button class="btn tiny plr-stop" id="plr-stop">结束这轮冲刺</button>
    </div>`;
  if (prof && prof.minutes < 300) {
    box.insertAdjacentHTML('beforeend',
      `<div class="plr-warn">你的「每天可学」只填了 ${prof.minutes} 分钟，这套定额是按 6~8 小时排的。
        建议去「⚙️ 备考信息」改成 <b>420</b> 分钟左右，规划助手才会把任务排够。</div>`);
  }
}
$('#pl-road').addEventListener('click', async e => {
  if (e.target.closest('#plr-more')) { plRoadOpen = !plRoadOpen; loadPlan(); return; }
  const go = e.target.closest('[data-plgo]');
  if (go) { ntfGo(go.dataset.plgo); return; }
  if (e.target.closest('#plr-start')) {
    const mins = (plProfile && plProfile.minutes) || 0;
    const ok = await appConfirm(
      '开启 40 天冲刺：从今天算第 1 天，分三段（根基 12 天 → 专项 16 天 → 套题 12 天），'
      + '每 7 天有一个复盘日。规划助手以后会按当天的定额和正确率目标排任务。'
      + (mins < 300 ? '\n\n你说全天有 6~8 小时，我顺便把「每天可学」设成 420 分钟，可以吗？' : ''),
      { title: '40 天冲刺路线', okText: '开始' });
    if (!ok) return;
    try {
      await api('/api/plan/roadmap', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mins < 300 ? { minutes: 420 } : {}),
      });
      toast('40 天冲刺已开启，去让规划助手排今天的计划');
      loadPlan();
    } catch (er) { toast(er.message, true); }
    return;
  }
  if (e.target.closest('#plr-stop')) {
    if (!await appConfirm('结束这轮 40 天冲刺？已排的计划不会删，只是规划助手不再按路线图排任务。',
      { title: '结束冲刺', okText: '结束' })) return;
    try { await api('/api/plan/roadmap', { method: 'DELETE' }); toast('已结束'); loadPlan(); }
    catch (er) { toast(er.message, true); }
  }
});

async function loadPlan() {
  try {
    const d = await api('/api/plan/today');
    plProfile = d.profile;
    const has = !!plProfile;
    if (has) renderPlan(d);
    if (plEditing) return;          // 用户正在改备考信息，别把设置页收起来
    $('#pl-setup').classList.toggle('hidden', has);
    $('#pl-main').classList.toggle('hidden', !has);
    if (!has) await fillPlanExams();
  } catch (e) { toast(e.message, true); }
}
async function fillPlanExams() {
  try {
    const d = await api('/api/plan/profile');
    $('#pl-exam').innerHTML = d.exams.map(x => `<option>${esc(x)}</option>`).join('');
    if (d.profile) {
      $('#pl-exam').value = d.profile.exam || '';
      $('#pl-date').value = d.profile.exam_date || '';
      $('#pl-min').value = d.profile.minutes || 120;
      $('#pl-weak').value = d.profile.weak || '';
      $('#pl-note').value = d.profile.note || '';
    }
  } catch (_) { /* 取不到就让表单留空，用户自己填 */ }
}
function renderPlan(d) {
  const p = d.profile;
  const st = d.study || { streak: 0, total: 0 };
  $('#pl-head').innerHTML = `<div class="pl-days">${esc(p.exam || '备考规划')}</div>
    <div class="pl-meta">今天可学 ${p.minutes} 分钟${p.weak ? ' · 薄弱：' + esc(p.weak) : ''}</div>
    <div class="pl-streak">🔥 连续学习 <b>${st.streak}</b> 天 · 累计 <b>${st.total}</b> 天</div>`;
  renderRoadmap(d.roadmap, p);

  if (d.summary) {
    $('#pl-summary').innerHTML = `💡 ${esc(d.summary)}`;
    $('#pl-summary').classList.remove('hidden');
  } else $('#pl-summary').classList.add('hidden');

  $('#pl-prog').textContent = d.total
    ? `今日进度 ${d.done_n} / ${d.total} · ${d.minutes_done} / ${d.minutes_total} 分钟${d.done_n === d.total ? ' 🎉 全部完成！' : ''}`
    : '';

  $('#pl-list').innerHTML = d.items.length ? d.items.map(it => {
    const col = PL_MOD_COLOR[it.module] || '#6b7280';
    return `<div class="tk-item pl-item ${it.done ? 'done' : ''}" data-pl="${it.id}">
      <span class="tk-check">${it.done ? '✓' : ''}</span>
      <span class="tk-text">
        <span class="pl-title">${esc(it.title)}</span>
        <span class="pl-tags">
          ${it.module ? `<i class="pl-mod" style="background:${col}">${esc(it.module)}</i>` : ''}
          <i class="pl-min">${it.minutes} 分钟</i>
          ${it.link ? `<i class="pl-go" data-plgo="${esc(it.link)}">去做 ›</i>` : ''}
        </span>
        ${it.reason ? `<span class="tk-who">${esc(it.reason)}</span>` : ''}
      </span>
      <button class="tk-del" data-pldel="${it.id}">🗑</button>
    </div>`;
  }).join('') : '<p class="empty">今天还没有计划。点下面的按钮，规划助手会看着你的复习进度和错题给你排一份。</p>';
}
// 备考信息：记下打开时的原值，用来判断"有没有改过" + 撤回
let plFormBase = null;
function plReadForm() {
  return {
    exam: $('#pl-exam').value, exam_date: $('#pl-date').value,
    minutes: +$('#pl-min').value || 120,
    weak: $('#pl-weak').value.trim(), note: $('#pl-note').value.trim(),
  };
}
function plWriteForm(v) {
  if (!v) return;
  $('#pl-exam').value = v.exam || ''; $('#pl-date').value = v.exam_date || '';
  $('#pl-min').value = v.minutes || 120; $('#pl-weak').value = v.weak || ''; $('#pl-note').value = v.note || '';
  plSyncUndo();
}
function plDirty() { return plFormBase && JSON.stringify(plReadForm()) !== JSON.stringify(plFormBase); }
function plSyncUndo() { const u = $('#pl-undo'); if (u) u.hidden = !plDirty(); }
['pl-exam', 'pl-date', 'pl-min', 'pl-weak', 'pl-note'].forEach(id =>
  $('#' + id).addEventListener('input', plSyncUndo));

async function plSave() {
  try {
    await api('/api/plan/profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(plReadForm()) });
    plEditing = false; plFormBase = null;
    toast('已保存');
    return true;
  } catch (e) { toast(e.message, true); return false; }
}
$('#pl-save').onclick = async () => { if (await plSave()) loadPlan(); };
$('#pl-edit').onclick = async () => {
  plEditing = true;
  await fillPlanExams();
  plFormBase = plReadForm();      // 记下原值
  $('#pl-back').hidden = !plProfile;   // 已有档案才有"上一页"可回
  $('#pl-undo').hidden = true;
  $('#pl-setup').classList.remove('hidden');
  $('#pl-main').classList.add('hidden');
};
$('#pl-undo').onclick = () => { plWriteForm(plFormBase); toast('已撤回修改'); };
// 返回：改过就问，保存 / 不保存 / 继续编辑
async function plLeaveSetup() {
  if (!plProfile) return;   // 首次填写没有"上一页"
  if (plDirty()) {
    const r = await appConfirm('备考信息有未保存的修改，怎么处理？',
      { title: '未保存的修改', okText: '保存并返回', altText: '不保存', okVal: 'save' });
    if (r === false) return;                 // 取消 = 继续编辑
    if (r === 'save') { if (!(await plSave())) return; }
    // r === 'alt'（不保存）：直接丢弃
  }
  plEditing = false; plFormBase = null;
  loadPlan();
}
$('#pl-back').onclick = plLeaveSetup;
$('#pl-gen').onclick = async () => {
  const b = $('#pl-gen');
  b.disabled = true; b.textContent = '规划助手思考中…';
  try {
    const d = await api('/api/plan/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    plProfile = d.profile;
    renderPlan(d);
    toast('已排好 ' + d.total + ' 条');
  } catch (e) { toast(e.message, true); }
  b.disabled = false; b.textContent = '✨ 让规划助手排今天的计划';
};
$('#pl-add').onclick = async () => {
  const v = $('#pl-in').value.trim(); if (!v) return;
  try {
    await api('/api/plan/item', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: v }) });
    $('#pl-in').value = ''; loadPlan();
  } catch (e) { toast(e.message, true); }
};
$('#pl-in').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter') $('#pl-add').click(); });
$('#pl-list').addEventListener('click', async e => {
  const go = e.target.closest('[data-plgo]');
  if (go) { e.stopPropagation(); ntfGo(go.dataset.plgo); return; }   // 复用消息中心那套跳转
  const del = e.target.closest('[data-pldel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('删除这条计划？'))) return;
    try { await api('/api/plan/' + del.dataset.pldel, { method: 'DELETE' }); loadPlan(); }
    catch (er) { toast(er.message, true); }
    return;
  }
  const it = e.target.closest('[data-pl]'); if (!it) return;
  // 乐观更新：立刻翻勾 + 更新进度，后台再发请求；失败翻回来。不整页重渲 → 不卡顿、不回顶
  const was = it.classList.contains('done');
  plSetDone(it, !was); plRecalcProg();
  try {
    const d = await api('/api/plan/' + it.dataset.pl + '/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    if (typeof d.done === 'boolean' && d.done !== !was) { plSetDone(it, d.done); plRecalcProg(); }
  } catch (er) { plSetDone(it, was); plRecalcProg(); toast(er.message, true); }
});
function plSetDone(it, on) {
  it.classList.toggle('done', on);
  const c = it.querySelector('.tk-check'); if (c) c.textContent = on ? '✓' : '';
}
function plRecalcProg() {
  const items = [...$('#pl-list').querySelectorAll('.pl-item')];
  if (!items.length) { $('#pl-prog').textContent = ''; return; }
  const mins = x => parseInt((x.querySelector('.pl-min') || {}).textContent || '0', 10) || 0;
  const done = items.filter(x => x.classList.contains('done'));
  const mt = items.reduce((s, x) => s + mins(x), 0);
  const md = done.reduce((s, x) => s + mins(x), 0);
  $('#pl-prog').textContent = `今日进度 ${done.length} / ${items.length} · ${md} / ${mt} 分钟${done.length === items.length ? ' 🎉 全部完成！' : ''}`;
}

/* ---------------- 备考计划记录 + 进度分析 ---------------- */
$('#pl-hist').onclick = () => openPlanLog();
$('#pl-analyze').onclick = () => openPlanLog(true);
function openPlanLog(runAnalyze) {
  push({ view: 'planlog', title: '计划记录' });
  $('#plh-analysis').classList.add('hidden'); $('#plh-analysis').innerHTML = '';
  loadPlanLog();
  if (runAnalyze) setTimeout(plhAnalyze, 200);
}
function plItemsHtml(items, checkable, pid) {
  return items.map(it => {
    const col = PL_MOD_COLOR[it.module] || '#6b7280';
    return `<div class="plh-item ${it.done ? 'done' : ''}">
      <span class="plh-dot">${it.done ? '✓' : ''}</span>
      <span class="plh-itxt"><span class="plh-title">${esc(it.title)}</span>
        <span class="pl-tags">${it.module ? `<i class="pl-mod" style="background:${col}">${esc(it.module)}</i>` : ''}<i class="pl-min">${it.minutes || 0} 分钟</i></span>
      </span></div>`;
  }).join('');
}
async function loadPlanLog() {
  $('#plh-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/plan/history');
    if (!d.days.length) { $('#plh-list').innerHTML = '<p class="empty">还没有计划记录。让规划助手排几天计划，这里就会留下每天的完成情况。</p>'; return; }
    $('#plh-list').innerHTML = d.days.map(day => {
      const arch = (day.archived || []).map(a => `
        <details class="plh-arch">
          <summary>${a.summary && a.summary.indexOf('【找回】') === 0 ? '🛟 找回的上一版' : '🕓 旧版本'} · ${esc((a.created_at || '').slice(5, 16))} · ${a.total} 条 / ${a.minutes_total} 分钟
            ${day.is_today ? `<button class="plh-restore" data-restore="${a.id}">恢复为今天</button>` : ''}</summary>
          ${a.summary ? `<div class="plh-sum">💡 ${esc(a.summary.replace('【找回】', ''))}</div>` : ''}
          ${plItemsHtml(a.items || [])}
        </details>`).join('');
      return `<div class="plh-day">
        <div class="plh-dhead"><b>${esc(day.date)}</b>${day.is_today ? ' <span class="plh-today">今天</span>' : ''}
          <span class="plh-prog">${day.total ? `完成 ${day.done_n}/${day.total} · ${day.minutes_done}/${day.minutes_total} 分钟` : '当天无计划'}</span></div>
        ${day.total ? plItemsHtml(day.items) : ''}
        ${arch}
      </div>`;
    }).join('');
  } catch (e) { $('#plh-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#plh-list').addEventListener('click', async e => {
  const r = e.target.closest('[data-restore]'); if (!r) return;
  e.preventDefault();
  if (!(await appConfirm('把这一版恢复成今天的计划？当前这版会先存进历史。'))) return;
  try { await api('/api/plan/restore/' + r.dataset.restore, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); toast('已恢复'); loadPlanLog(); }
  catch (er) { toast(er.message, true); }
});
$('#plh-analyze-btn').onclick = plhAnalyze;
async function plhAnalyze() {
  const box = $('#plh-analysis'); const btn = $('#plh-analyze-btn');
  box.classList.remove('hidden');
  box.innerHTML = '<p class="empty">规划助手正在翻你的计划记录…</p>';
  btn.disabled = true;
  try {
    const d = await api('/api/plan/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const sec = (title, arr, cls) => arr && arr.length ? `<div class="plh-sec ${cls}"><h4>${title}</h4><ul>${arr.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>` : '';
    box.innerHTML = `
      <div class="plh-ov">${esc(d.overview || '')}</div>
      <div class="plh-stat">近 ${d.days} 天 · 共 ${d.total} 条 · 完成 ${d.done} 条</div>
      ${sec('✅ 坚持得不错', d.keep, 'keep')}
      ${sec('⚠️ 被冷落 / 长期没安排', d.neglected, 'neg')}
      ${sec('👉 接下来建议', d.suggestions, 'sug')}`;
  } catch (e) { box.innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
  btn.disabled = false;
}
