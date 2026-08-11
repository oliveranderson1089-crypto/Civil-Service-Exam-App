/* 题库：模拟卷 / 题目解析
 *
 * 由 app.js 按它自己的区段边界切出（原 L8727-8843）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, IC, api, appConfirm, artEm, c, esc, matBoard, openViewerUrl, push, qz, render, toast */

/* ================= 题库：模拟卷 / 题目解析 ================= */
function openQuiz() {
  push({ view: 'quiz', title: '题库' });
  $('#qz-entries').innerHTML = `
    <div class="home-card" data-qzgo="sets">
      <div class="hc-logo" style="background:linear-gradient(135deg,#2b6fd6,#4bb0f0)">${IC.edit}</div>
      <div class="hc-name">模拟卷</div><div class="hc-desc">四川省考卷面 · 每周自动更新</div></div>
    <div class="home-card" data-qzgo="docqa">
      <div class="hc-logo" style="background:linear-gradient(135deg,#0b7285,#1098ad)">${IC.bulb}</div>
      <div class="hc-name">题目解析</div><div class="hc-desc">上传讲义 · AI 解出没答案的例题</div></div>`;
}
$('#qz-entries').addEventListener('click', e => {
  const c = e.target.closest('[data-qzgo]'); if (!c) return;
  if (c.dataset.qzgo === 'sets') openQuizSets(); else openDocqa();
});

async function openQuizSets() {
  push({ view: 'quizsets', title: '模拟卷' });
  $('#qz-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/quiz/sets');
    if (!d.items.length) { $('#qz-list').innerHTML = '<p class="empty">还没有套卷，每周二/五清晨自动生成～</p>'; return; }
    $('#qz-list').innerHTML = d.items.map(it => {
      const pct = it.done ? Math.round(it.right_n / it.done * 100) : 0;
      return `<div class="poly-card" data-qset="${it.id}">
        <span class="poly-badge" style="background:${it.kind === '申论' ? '#7a5cc0' : '#2b6fd6'}">${esc(it.kind)}</span>
        <div class="poly-t" style="font-size:16px">${esc(it.name)}</div>
        <div class="poly-meta">${it.total} 题 · 已做 ${it.done}${it.done ? ` · 正确率 ${pct}%` : ''}</div>
      </div>`;
    }).join('');
  } catch (e) { $('#qz-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}

/* ---- 题目解析：上传讲义 → 后台识题 → 生成含答案解析副本 ---- */
var dqPoll = null;   // var：render() 在它上面，用 let 会踩暂时性死区
function openDocqa() { push({ view: 'docqa', title: '题目解析' }); loadDocqa(); }
$('#dq-upload').onclick = () => $('#dq-file').click();
$('#dq-file').addEventListener('change', async e => {
  const files = [...e.target.files]; e.target.value = '';
  if (!files.length) return;
  toast(files.length > 1 ? `已上传 ${files.length} 份，正在后台排队识题…` : '已上传，正在后台识题…');
  let ok = 0, fail = 0;
  for (const file of files) {           // 逐个上传；后端会排队，一次只解一份，不挤爆接口
    const fd = new FormData();
    fd.append('file', file);
    fd.append('board', matBoard || '');
    try { await api('/api/docqa/upload', { method: 'POST', body: fd }); ok++; }
    catch (err) { fail++; }
  }
  if (fail) toast(`${ok} 份已排队，${fail} 份上传失败`, true);
  loadDocqa();
});

async function loadDocqa() {
  try {
    const d = await api('/api/docqa/tasks');
    const running = d.items.some(t => t.status === 'running');
    $('#dq-list').innerHTML = d.items.length ? d.items.map(t => {
      const pct = t.total ? Math.round(t.progress / t.total * 100) : 0;
      const cls = t.status === 'done' ? 'good' : t.status === 'error' ? 'bad' : 'ok';
      return `<div class="sl-hi" data-dqt="${t.id}">
        <div class="sl-hi-main">
          <div class="sl-hi-t">${esc(t.title)}</div>
          <div class="sl-hi-m">${esc(t.created_at.slice(5, 16))} · ${esc(t.message || '')}</div>
          ${t.status === 'running' ? `<div class="dq-bar"><i style="width:${pct}%"></i></div>` : ''}
        </div>
        <div class="sl-hi-s ${cls}" style="font-size:13px">${t.status === 'done' ? '完成' : t.status === 'error' ? '失败' : pct + '%'}</div>
        <button class="sl-hi-del" data-dqdel="${t.id}">${artEm('🗑')}</button>
      </div>`;
    }).join('') : '<p class="empty">还没有解析任务。上传一份讲义，AI 会把里面没答案的例题解出来。</p>';
    clearInterval(dqPoll);
    if (running) dqPoll = setInterval(loadDocqa, 4000);     // 有任务在跑就轮询进度
  } catch (e) { $('#dq-list').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; }
}
$('#dq-list').addEventListener('click', async e => {
  const del = e.target.closest('[data-dqdel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('删除这条解析记录？（资料库里的文件不会删）'))) return;
    try { await api('/api/docqa/task/' + del.dataset.dqdel, { method: 'DELETE' }); loadDocqa(); }
    catch (er) { toast(er.message, true); }
    return;
  }
  const t = e.target.closest('[data-dqt]');
  if (t) openDocqaTask(+t.dataset.dqt);
});

async function openDocqaTask(tid) {
  try {
    const t = await api('/api/docqa/task/' + tid);
    if (t.status === 'running') return toast('还在解析中，' + (t.message || ''));
    if (t.status === 'error') return toast('解析失败：' + t.message, true);
    push({ view: 'docqad', title: t.title });
    $('#dqd-head').innerHTML = `<div class="slt-title">${esc(t.title)}</div>
      <div class="slt-desc">识别 ${t.questions.length} 道题 · ${esc(t.created_at.slice(0, 16))}</div>`;
    const src = t.extra.src_mid, out = t.extra.out_mid;
    $('#dqd-files').innerHTML = `
      <button class="dqd-f" data-dqopen="${src}|原件">${artEm('📄')} 打开原件</button>
      <button class="dqd-f primary" data-dqopen="${out}|含答案解析">${artEm('✅')} 打开含答案解析副本</button>`;
    $('#dqd-qs').innerHTML = t.questions.map((q, i) => `
      <div class="slp good">
        <div class="slp-head"><span class="slp-no">${i + 1}</span>
          <span class="slp-name">${esc(q.qtype || '题目')}</span>
          <span class="slp-score" style="font-size:12px">第 ${q.page} 页</span></div>
        <div class="slp-yours">${esc(q.stem)}</div>
        ${q.options.map(o => `<div class="dq-opt">${esc(o)}</div>`).join('')}
        <div class="slp-li hit">【答案】${esc(q.answer)}</div>
        <div class="slp-mat"><b>解析：</b>${esc(q.explain)}</div>
      </div>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#dqd-files').addEventListener('click', e => {
  const b = e.target.closest('[data-dqopen]'); if (!b) return;
  const [mid, name] = b.dataset.dqopen.split('|');
  openViewerUrl('/api/materials/' + mid + '/view', name, '.pdf', '/api/materials/' + mid + '/download');
});
