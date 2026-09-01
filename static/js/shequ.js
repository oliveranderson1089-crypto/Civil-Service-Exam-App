/* 社区专职工作者（资中县）：整卷背题 / 模考 + 入库校对裁决台
 *
 * 这卷子和行测卷不是一个形状，所以没有复用 realq.js 的做题页：
 *   · 五种题型（单选/多选/判断/案例/公文），**按 part 分派渲染**，不按题型名猜；
 *   · 多选题是「多选、少选、错选均不得分」，所以要有「确定提交」这一步 ——
 *     点一下就判的交互会让人手滑丢分，而这门考试丢的是整整 1 分；
 *   · 40 分主观题没有标准答案可判，交卷后给参考答案并排对照。
 *
 * **判分一律在后端**（mods/sqscore.py）。前端连「对不对」都不自己算：
 * 算两遍迟早算得不一样，而且不会报错。
 */
/* global $, api, appConfirm, artEm, errMsg, esc, postJSON, push, back, stack, toast */

let sqPapers = [], sqRules = {};
let sqRun = null;        // { pid, mode, items, parts, idx, answers:{qid:值}, t0, left, timer, held }

const SQ_L = ['A', 'B', 'C', 'D'];

/* ---------------------------------------------------------------- 卷子列表 */
async function openSqReal() {
  push({ view: 'sqreal', title: '资中真题' });
  $('#sq-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/shequ/overview');
    sqPapers = d.papers || []; sqRules = d.rules || {};
    sqRenderList(d);
  } catch (e) { $('#sq-list').innerHTML = `<p class="empty">${esc(errMsg(e))}</p>`; }
}

/* 顶上那条：还剩几天、报名什么时候、笔试考什么范围。
   「笔试不考行测」是从公告的考试内容里读出来的，不是我们的判断 —— 原文照抄，
   让人自己看：社工初级 + 党建 + 社区 + 基层治理 + 法律 + 时政，没有行测。 */
function sqExamBar(x) {
  if (!x) return '';
  const near = x.days >= 0 && x.days <= 30;
  return `<div class="card sq-exam${near ? ' near' : ''}">
      <div class="sq-exam-d">${x.days > 0 ? `距笔试还有 <b>${x.days}</b> 天`
        : x.days === 0 ? '<b>今天就是笔试</b>' : '笔试已过'}</div>
      <div class="sq-exam-m">${esc(x.exam_date)} 笔试${x.sign_up
        ? '　·　报名 ' + esc(x.sign_up) : ''}${x.total ? '　·　选聘 ' + x.total + ' 名' : ''}</div>
      ${x.scope ? `<div class="sq-exam-s">公告写明的笔试内容：${esc(x.scope)}</div>` : ''}
    </div>`;
}

/* 一张卷子的卡片。真题和模拟卷**共用这一份** —— 两处各写一份的下场是
   改了按钮文案只改到一半。差别只在副标题那一行：模拟卷要如实写出缺口。 */
function sqPaperCard(p, mock) {
  const gap = mock && p.n_bad
    ? `<span class="sq-warn">原卷 ${p.servable + p.n_bad} 题，OCR 认不出的 ${p.n_bad} 道已剔除</span>`
    : '';
  return `
    <div class="card sq-paper">
      <div class="sq-p-t">${esc(p.name.replace(/\.pdf$/i, ''))}</div>
      <div class="sq-p-m">${p.year ? p.year + ' 年 · ' : ''}${esc(p.kind)} ·
        客观 <b>${p.servable}</b>/${p.n_obj} 题可练${p.n_sub ? ` + 主观 ${p.n_sub} 题` : ''}
        ${p.n_doubt ? `<span class="sq-warn">${p.n_doubt} 道待裁决</span>` : ''}
        ${gap}
        ${p.mine ? `<span class="sq-mine">做过 ${p.mine} 次</span>` : ''}</div>
      <div class="sq-p-b">
        <button class="btn primary" data-sq-open="${p.id}" data-sq-mode="exam">模考（总倒计时）</button>
        <button class="btn" data-sq-open="${p.id}" data-sq-mode="study">背题（做一题揭晓一题）</button>
      </div>
    </div>`;
}

function sqRenderList(d) {
  if (!sqPapers.length) {
    $('#sq-list').innerHTML = '<p class="empty">还没有卷子。先跑 ingest_shequ.py 把真题解析进库。</p>';
    return;
  }
  const types = (d.types || []).map(t => `<span class="sq-chip">${esc(t.qtype)} ${t.c}</span>`).join('');
  const mocks = d.mocks || [];
  $('#sq-list').innerHTML = sqExamBar(d.exam) + sqPapers.map(p => sqPaperCard(p, false)).join('')
    /* 模拟卷单开一组，**标题里就写明「不是真题」**：真题一共只有两套，
       混在一起摆会让人以为资中考过七八回。 */
    + (mocks.length ? `<div class="card sq-mock-h">
        <div class="sq-sec-t">模拟卷 · 不是真题（${mocks.length} 套）</div>
        <div class="sq-note">${esc(d.mock_note || '')}</div></div>`
      + mocks.map(p => sqPaperCard(p, true)).join('') : '')
    + (types ? `<div class="card"><div class="sq-sec-t">能练的考点分布</div>
        <div class="sq-chips">${types}</div>
        <div class="sq-note">只统计过了校对闸门的题 —— 库存满不等于有题做。</div></div>` : '')
    + (d.doubt ? `<div class="card sq-doubt-entry">
        <div class="sq-sec-t">${artEm('⚠')} ${d.doubt} 道题的答案还没定</div>
        <div class="sq-note">源卷是回忆版，答案本身可能是错的。这些题留在库里但不发给你做，
          裁决完才会进卷子。</div>
        <button class="btn primary" id="sq-go-check">去裁决</button></div>` : '')
    + `<div class="card"><div class="sq-sec-t">我的记录</div><div id="sq-recs" class="sq-recs">
        <p class="empty">加载中…</p></div></div>`;
  sqLoadRecs();
}

async function sqLoadRecs() {
  try {
    const d = await api('/api/shequ/records');
    const box = $('#sq-recs');
    if (!box) return;
    if (!(d.items || []).length) { box.innerHTML = '<p class="empty">还没做过</p>'; return; }
    box.innerHTML = d.items.map(r => `
      <div class="sq-rec" data-sq-rec="${r.id}">
        <span class="sq-rec-m">${esc(r.mode_name)}</span>
        <span class="sq-rec-n">${esc((r.paper_name || '').replace(/\.pdf$/i, ''))}</span>
        <span class="sq-rec-s">${r.obj_score} / ${r.obj_full}</span>
        <span class="sq-rec-d">${esc((r.created_at || '').slice(5, 16))}</span>
      </div>`).join('');
  } catch (e) { /* 记录拉不到不该挡住做题 */ }
}

/* ---------------------------------------------------------------- 做题 */
async function sqOpenPaper(pid, mode) {
  try {
    const d = await api(`/api/shequ/paper/${pid}?mode=${mode}`);
    if (!(d.items || []).length) { toast('这份卷子还没有能做的题', true); return; }
    sqRun = { pid, mode, items: d.items, parts: d.parts || [], idx: 0, answers: {}, locked: {},
              held: d.held || 0, objFull: d.obj_full, t0: Date.now(),
              left: mode === 'exam' ? d.seconds : 0, timer: null, paper: d.paper };
    push({ view: 'sqrun', title: mode === 'exam' ? '模考' : '背题' });
    if (mode === 'exam') sqTick();
    sqRender();
  } catch (e) { toast(errMsg(e), true); }
}

function sqTick() {
  clearInterval(sqRun.timer);
  sqRun.timer = setInterval(() => {
    if (!sqRun) return;
    sqRun.left -= 1;
    const el = $('#sq-clock');
    if (el) el.textContent = sqFmt(sqRun.left);
    if (sqRun.left <= 0) { clearInterval(sqRun.timer); sqSubmit(true); }
  }, 1000);
}
const sqFmt = (s) => {
  s = Math.max(0, s | 0);
  const h = (s / 3600) | 0, m = ((s % 3600) / 60) | 0;
  return (h ? String(h).padStart(2, '0') + ':' : '') + String(m).padStart(2, '0')
    + ':' + String(s % 60).padStart(2, '0');
};

function sqRender() {
  const r = sqRun; if (!r) return;
  const it = r.items[r.idx];
  const done = Object.keys(r.answers).filter(k => String(r.answers[k]).trim()).length;
  $('#sq-run-bar').innerHTML = `
    <span class="sq-run-p">第 ${r.idx + 1} / ${r.items.length} 题 · ${esc(it.part_name)}</span>
    ${r.mode === 'exam' ? `<span id="sq-clock" class="sq-clock">${sqFmt(r.left)}</span>` : ''}
    <span class="sq-run-d">已答 ${done}</span>
    <button class="btn tiny" id="sq-sheet-btn">答题卡</button>`;
  $('#sq-run-body').innerHTML = sqQuestionHtml(it);
  $('#sq-sheet').classList.add('hidden');
}

function sqQuestionHtml(it) {
  const r = sqRun;
  const mine = r.answers[it.id];
  /* 什么时候揭晓：单选和判断点一下就揭晓；**多选要等「确定提交」**。
     不区分的话，勾第一个选项的瞬间答案就亮出来了，那颗按钮等于摆设，
     而且是在人还在挑的时候泄底 —— 这道题的规则是少选一个就 0 分，
     正需要「想清楚再交」这一步。 */
  const shown = r.mode !== 'exam' && it.answer != null && (it.part === 'multi'
    ? !!(r.locked && r.locked[it.id])
    : (mine != null && mine !== ''));
  let body = '';
  if (it.part === 'judge') {
    body = `<div class="sq-tf">
        <button class="sq-tf-b t${mine === 'T' ? ' picked' : ''}" data-sq-tf="T">√<small>正确</small></button>
        <button class="sq-tf-b f${mine === 'F' ? ' picked' : ''}" data-sq-tf="F">×<small>错误</small></button>
      </div>
      <div class="sq-kbd"><i>J</i> 判对　<i>K</i> 判错　<i>Enter</i> 下一题</div>`;
  } else if (it.part === 'case' || it.part === 'gongwen') {
    body = `<textarea id="sq-sub" class="sq-sub" rows="10"
        placeholder="在这里作答（${it.score} 分）">${esc(mine || '')}</textarea>
      <div class="sq-note">主观题交卷后给参考答案对照，不当场判分。</div>`;
  } else {
    const multi = it.part === 'multi';
    const picked = new Set(String(mine || '').split(''));
    body = `<div class="sq-opts">` + (it.options || []).map((o, i) => {
      const L = SQ_L[i];
      let cls = picked.has(L) ? ' chosen' : '';
      if (shown) {
        const right = String(it.answer).includes(L);
        if (right && picked.has(L)) cls = ' right';
        else if (right) cls = ' miss';
        else if (picked.has(L)) cls = ' wrong';
        else cls = '';
      }
      return `<button class="sq-opt${multi ? ' multi' : ''}${cls}" data-sq-opt="${L}">
          <span class="sq-l">${L}</span><span>${esc(o)}</span></button>`;
    }).join('') + `</div>`
      + (multi ? `<div class="sq-rule">${mine ? '已选 ' + String(mine).split('').join(' ') + '　·　' : ''}
          <b>${esc(sqRules.multi || '')}</b></div>` : '');
    if (multi && !shown) body += `<button class="btn primary sq-wide" id="sq-multi-ok">确定提交</button>`;
  }
  let after = '';
  if (shown) {
    const ok = sqLocalHint(it, mine);
    after = `<div class="sq-fb ${ok}">${ok === 'ok' ? artEm('✅') + ' 答对了' : artEm('❌') + ' 答错了'}
        　正确答案：<b>${esc(sqAnsText(it))}</b></div>`
      + (it.explain ? `<div class="sq-ex">${esc(it.explain)}</div>` : '');
  }
  return `<div class="card sq-q">
      <div class="sq-q-h"><span class="sq-qt ${it.part}">${esc(it.part_name)}</span>
        <span class="sq-qk">${esc(it.qtype)}</span><span class="sq-qs">${it.score} 分</span></div>
      <div class="sq-stem">${esc(it.stem)}</div>
      ${body}${after}
      <div class="sq-nav">
        <button class="btn" id="sq-prev"${sqRun.idx ? '' : ' disabled'}>上一题</button>
        <button class="btn" id="sq-next">${sqRun.idx + 1 >= sqRun.items.length ? '到末尾' : '下一题'}</button>
        <button class="btn primary" id="sq-submit">交卷</button>
      </div>
    </div>`;
}

/* 背题模式下的即时反馈。**只是提示，不是判分** —— 真正的分数由后端交卷时算，
   这儿算错了也不会写进任何记录。多选按「全对才算对」，和后端同一条规矩。 */
function sqLocalHint(it, mine) {
  const a = String(it.answer || '').split('').sort().join('');
  const c = String(mine || '').split('').sort().join('');
  return a && c && a === c ? 'ok' : 'no';
}
const sqAnsText = (it) => it.part === 'judge'
  ? (it.answer === 'T' ? '√ 正确' : '× 错误') : String(it.answer || '').split('').join(' ');

function sqPick(letter) {
  const r = sqRun, it = r.items[r.idx];
  if (it.part === 'multi') {
    const s = new Set(String(r.answers[it.id] || '').split(''));
    s.has(letter) ? s.delete(letter) : s.add(letter);
    r.answers[it.id] = [...s].sort().join('');
    if (r.locked) delete r.locked[it.id];   // 又改了就撤回揭晓，别看着答案改
    sqRender();
    return;
  }
  r.answers[it.id] = letter;
  sqRender();
  if (r.mode === 'exam') setTimeout(() => sqGo(1), 180);   // 模考不揭晓，直接走下一题
}

function sqGo(step) {
  const r = sqRun;
  sqStash();
  const n = r.idx + step;
  if (n < 0 || n >= r.items.length) return;
  r.idx = n; sqRender();
}

/* 主观题的输入要在切题前收起来，否则一翻页就白写了 */
function sqStash() {
  const el = $('#sq-sub');
  if (el && sqRun) sqRun.answers[sqRun.items[sqRun.idx].id] = el.value;
}

function sqSheetHtml() {
  const r = sqRun;
  let h = '';
  for (const p of r.parts) {
    const rows = r.items.filter(i => i.part === p.part);
    const done = rows.filter(i => String(r.answers[i.id] || '').trim()).length;
    const wide = (p.part === 'case' || p.part === 'gongwen');
    h += `<div class="sq-sheet-lab"><span>${esc(p.name)} ${p.n} 题 · ${p.score} 分</span>
        <span>已答 ${done}</span></div>
      <div class="sq-sheet">` + rows.map(i => {
      const at = r.items.indexOf(i);
      const cls = (String(r.answers[i.id] || '').trim() ? ' done' : '')
        + (at === r.idx ? ' cur' : '') + (wide ? ' wide' : '');
      return `<button class="sq-sq${cls}" data-sq-jump="${at}">${wide
        ? esc(p.name.slice(0, 2)) + '<br>' + i.score + ' 分' : i.part_seq}</button>`;
    }).join('') + `</div>`;
  }
  if (r.held) h += `<div class="sq-note sq-warn-box">另有 ${r.held} 道客观题答案待裁决，
      本卷暂不发出 —— 卷面因此不满分，这是实话，不是漏题。</div>`;
  return h;
}

async function sqSubmit(auto) {
  const r = sqRun; if (!r) return;
  sqStash();
  if (!r.pid) {                       // 专项练：没有卷子，走 drill/done
    try {
      const d = await postJSON('/api/shequ/drill/done', { answers: r.answers });
      toast(`${d.n} 道里对了 ${d.ok} 道`);
      back();
    } catch (e) { toast(errMsg(e), true); }
    return;
  }
  const done = Object.keys(r.answers).filter(k => String(r.answers[k]).trim()).length;
  if (!auto && done < r.items.length) {
    const go = await appConfirm(`还有 ${r.items.length - done} 题没作答，确定交卷？`);
    if (!go) return;
  }
  clearInterval(r.timer);
  try {
    const d = await postJSON('/api/shequ/submit', {
      paper_id: r.pid, mode: r.mode, seconds: ((Date.now() - r.t0) / 1000) | 0,
      answers: r.answers,
    });
    push({ view: 'sqres', title: '成绩' });
    sqResult(d);
  } catch (e) { toast(errMsg(e), true); }
}

function sqResult(d) {
  const r = sqRun;
  const byId = {}; (r.items || []).forEach(i => { byId[i.id] = i; });
  const wrong = (d.detail || []).filter(x => x.correct === 0);
  const subs = (d.detail || []).filter(x => x.correct === -1);
  $('#sq-res').innerHTML = `
    <div class="card">
      <div class="sq-score"><b>${d.obj_score}</b><small> / ${d.obj_full} 分（客观题）</small></div>
      <div class="sq-note">主观题 ${d.n_sub} 道未判分 —— 40 分那部分要按采分点批改，
        现在先和参考答案对照着看。${r.held ? `另有 ${r.held} 道题答案待裁决，没进这张卷子。` : ''}</div>
    </div>
    ${wrong.length ? `<div class="card"><div class="sq-sec-t">错了 ${wrong.length} 道</div>`
      + wrong.map(x => {
        const it = byId[x.qid] || {};
        const miss = x.miss ? `<span class="sq-miss">漏选 ${x.miss.split('').join(' ')}</span>` : '';
        const extra = x.extra ? `<span class="sq-extra">多选 ${x.extra.split('').join(' ')}</span>` : '';
        return `<div class="sq-wrong">
            <div class="sq-w-h">第 ${it.seq || x.seq} 题 · ${esc(it.part_name || '')} ${miss}${extra}</div>
            <div class="sq-w-q">${esc(it.stem || '')}</div>
            <div class="sq-w-a">你选 <b>${esc(String(x.chosen || '—').split('').join(' '))}</b>
              　正确 <b>${esc(sqAnsText(it))}</b></div>
            ${it.explain ? `<div class="sq-ex">${esc(it.explain)}</div>` : ''}
          </div>`;
      }).join('') + `</div>` : '<div class="card sq-allright">' + artEm('✅') + ' 客观题全对</div>'}
    ${subs.length ? `<div class="card"><div class="sq-sec-t">主观题对照</div>`
      + subs.map(x => {
        const it = byId[x.qid] || {};
        return `<div class="sq-sub-cmp">
            <div class="sq-w-h">${esc(it.part_name || '')} · ${it.score} 分</div>
            <div class="sq-w-q">${esc(it.stem || '')}</div>
            <div class="sq-cmp2">
              <div><div class="sq-cmp-t">你写的</div><div class="sq-cmp-b">${esc(x.chosen || '（没写）')}</div></div>
              <div><div class="sq-cmp-t">参考答案</div><div class="sq-cmp-b">${esc(it.answer || '')}</div></div>
            </div></div>`;
      }).join('') + `</div>` : ''}
    <div class="card"><button class="btn primary sq-wide" id="sq-back-list">回卷子列表</button></div>`;
}

/* ---------------------------------------------------------------- 资中专项
   两套原卷里 8 道本地题**全部出自招聘公告参数**，没有一道考县情地理或 GDP。
   所以速记卡按「真题考过 / 未经真题验证」分档摆，不装作同等重要 ——
   只剩三周多，得先背确定考的那些。 */
async function openSqLocal() {
  push({ view: 'sqlocal', title: '资中专项' });
  $('#sq-local').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/shequ/facts');
    sqRenderFacts(d);
  } catch (e) { $('#sq-local').innerHTML = `<p class="empty">${esc(errMsg(e))}</p>`; }
}

function sqRenderFacts(d) {
  if (!(d.groups || []).length) {
    $('#sq-local').innerHTML = '<p class="empty">还没有数据。先跑 build_zizhong.py。</p>';
    return;
  }
  $('#sq-local').innerHTML = sqExamBar(d.exam) + (d.quiz_n ? `<div class="card sq-quiz-entry">
      <div class="sq-sec-t">${artEm('🎯')} 这些数字，练 ${d.quiz_n} 道</div>
      <div class="sq-note">题目由公告数据直接生成，<b>答案由数据保证</b>，
        干扰项取自同一组真实数字 —— 记混了才会选错，这正是本地题的考法。</div>
      <button class="btn primary sq-wide" data-sq-quiz="${d.quiz_paper}">开始练</button>
    </div>` : '')
    + d.groups.map(g => `
      <div class="card">
        <div class="sq-sec-t">${esc(g.grp)}
          ${g.proven ? `<span class="sq-badge proven">${g.proven} 条真题考过</span>`
            : '<span class="sq-badge plain">未经真题验证</span>'}</div>
        <div class="sq-facts-list">${g.items.map(f => `
          <div class="sq-f${f.proven ? ' proven' : ''}">
            <div class="sq-f-k">${esc(f.k)}${f.proven ? '<i title="真题考过">●</i>' : ''}</div>
            <div class="sq-f-v">${esc(f.v)}${f.unit ? ' ' + esc(f.unit) : ''}</div>
            ${f.note ? `<div class="sq-f-n">${esc(f.note)}</div>` : ''}
            <div class="sq-f-s">据 ${esc(f.src)}${f.year ? '（' + f.year + '）' : ''}</div>
          </div>`).join('')}</div>
      </div>`).join('')
    + `<div class="card"><div class="sq-note">
        ${artEm('📍')} <b>本地数据是会过期的。</b>招聘公告每年换，县情 PDF 里还有 2018 年的数字。
        所以每条都标了来源和年份 —— 明年换公告时整份替换，别只改数字。</div></div>`;
}

/* 回看某一次：作答从记录里取，题面/答案/解析后端现查库（记录表不存题面）。
   复用成绩页那一屏 —— 同一份东西不画两遍。 */
async function sqOpenRecord(rid) {
  try {
    const d = await api(`/api/shequ/record/${rid}`);
    const items = d.items || [];
    // sqResult 读的是 sqRun.items + detail 两份，这儿把它们从回看数据里拼回去
    sqRun = { items, held: 0 };
    const detail = items.map(it => ({ qid: it.id, seq: it.seq, chosen: it.chosen,
                                      correct: it.correct, miss: it.miss, extra: it.extra }));
    const r = d.record || {};
    push({ view: 'sqres', title: '回看' });
    sqResult({ obj_score: r.obj_score, obj_full: r.obj_full, detail,
               n_sub: detail.filter(x => x.correct === -1).length });
  } catch (e) { toast(errMsg(e), true); }
}

/* ---------------------------------------------------------------- 专项练
   多选和判断合起来 20 分，在此之前只能在整卷里碰到、没法针对性刷。
   题只从**题库**出，不掺真题：真题是标尺，掺进来之后想拿它估分就估不准了。 */
let sqDrill = null;

async function openSqDrill() {
  push({ view: 'sqdrill', title: '专项练' });
  $('#sq-drill').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/shequ/drill/meta');
    $('#sq-drill').innerHTML = `
      <div class="card"><div class="sq-sec-t">按题型练　<span class="muted">共 ${d.total} 道</span></div>
        ${d.parts.map(p => `<div class="sq-drill-row" data-sq-dr="part:${p.part}">
            <span class="sq-rec-n"><b>${esc(p.name)}</b>
              <span class="sq-f-s">${esc(p.rule)}</span></span>
            <span class="sq-rec-s">${p.c}</span>
            <span class="sq-rec-d">${p.done ? '做过 ' + p.done : ''}</span>
          </div>`).join('')}
      </div>
      <div class="card"><div class="sq-sec-t">按考点练</div>
        ${d.types.map(t => `<div class="sq-drill-row" data-sq-dr="qtype:${esc(t.qtype)}">
            <span class="sq-rec-n"><b>${esc(t.qtype)}</b>
              <span class="sq-f-s ${t.sure ? '' : 'warn'}">${esc(t.sure
                || '⚠ 公告未点名、两套真题也没考过 —— 时间紧就先放放')}</span></span>
            <span class="sq-rec-s">${t.c}</span>
            <span class="sq-rec-d">${t.done ? '做过 ' + t.done : ''}</span>
          </div>`).join('')}
      </div>
      <div class="card"><div class="sq-note">出题顺序是<b>错过的 › 没做过的 › 做对过的</b> ——
        全随机的话，刷三遍等于把第一遍重刷三次，最该练的题反而遇不上。</div></div>`;
  } catch (e) { $('#sq-drill').innerHTML = `<p class="empty">${esc(errMsg(e))}</p>`; }
}

async function sqDrillStart(kind, val) {
  try {
    const q = kind === 'part' ? 'part=' + encodeURIComponent(val)
      : 'qtype=' + encodeURIComponent(val);
    const d = await api('/api/shequ/drill?n=10&' + q);
    if (!(d.items || []).length) { toast('这一类还没有可练的题', true); return; }
    // 复用整卷那套作答态：多选方标、判断两键、少选高亮，一份组件两处用
    sqRules = d.rules || {};
    sqDrill = { items: d.items };
    sqRun = { pid: 0, mode: 'study', items: d.items, parts: [], idx: 0,
              answers: {}, locked: {}, held: 0, t0: Date.now(), left: 0, timer: null };
    push({ view: 'sqrun', title: '专项练' });
    sqRender();
  } catch (e) { toast(errMsg(e), true); }
}

/* ---------------------------------------------------------------- 主观题 40 分
   案例分析 25 + 公文 15。两处刻意的设计：
     · **骨架常驻在作答框上方**。这门考试主观题占四成，而四道真题的参考答案只有
       两种骨架 —— 骨架比辞藻值钱，练几次就该成肌肉记忆。
     · 判定分三档，**「沾边」单独一档**（◐）：只写「上门劝导」没写「联合城管消防
       整治」就是沾边，这是最常见的丢分方式，跟「整块没写」混为一谈就学不到东西。 */
let sqSub = [], sqCur = null;

/* 一道主观题的卡片。**「N 年真题」那句话不能写死** —— 外省题库里的题没有年份，
   照原样渲染会显示成「0 年真题」，看着像资中 0 年考过。有年份才写年份，
   没有就写它出自哪本册子。 */
function sqSubCard(it) {
  const from = it.year ? `${it.year} 年资中真题` : esc((it.src || '外省题库').replace(/\.pdf$/i, ''));
  return `
      <div class="card sq-subq" data-sq-sub="${it.id}">
        <div class="sq-q-h"><span class="sq-qt ${it.part}">${esc(it.part_name)}</span>
          <span class="sq-qk">${from}</span>
          <span class="sq-qs">${it.score} 分</span></div>
        <div class="sq-w-q">${esc(it.stem.slice(0, 110))}${it.stem.length > 110 ? '…' : ''}</div>
        <div class="sq-p-m">${it.skeleton ? esc(it.skeleton.name) + '　·　' : ''}
          ${it.n_points ? it.n_points + ' 个采分点'
    : (it.part === 'gongwen' ? '按结构部件给分' : '拆不出采分点，只能对照参考答案')}
          ${it.mine ? `　·　写过 ${it.mine} 次` : ''}</div>
      </div>`;
}

async function openSqSub() {
  push({ view: 'sqsub', title: '主观题 40 分' });
  $('#sq-sub-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/shequ/subjective');
    sqSub = d.items || [];
    /* 分档摆：资中真题 → 外省同型 → 简答论述。**分组和说明都是后端下发的**，
       JS 里不另判一遍「这题算不算资中考的」—— 两边各判一次迟早说的不是一回事。 */
    $('#sq-sub-list').innerHTML = (d.groups || []).map(g => {
      const got = sqSub.filter(x => x.group === g.key);
      if (!got.length) return '';
      return `<div class="card sq-grp-h">
          <div class="sq-sec-t">${esc(g.name)}（${got.length} 道）</div>
          <div class="sq-note">${esc(g.note)}</div></div>`
        + got.map(sqSubCard).join('');
    }).join('')
      + `<div class="card"><div class="sq-sec-t">我的批改记录</div>
          <div id="sq-glist" class="sq-recs"><p class="empty">加载中…</p></div></div>`;
    sqLoadGrades();
  } catch (e) { $('#sq-sub-list').innerHTML = `<p class="empty">${esc(errMsg(e))}</p>`; }
}

async function sqLoadGrades() {
  try {
    const d = await api('/api/shequ/grades');
    const box = $('#sq-glist'); if (!box) return;
    box.innerHTML = (d.items || []).length ? d.items.map(r => `
      <div class="sq-rec"><span class="sq-rec-m">${esc(r.part_name.slice(0, 2))}</span>
        <span class="sq-rec-n">${esc((r.stem || '').slice(0, 26))}</span>
        <span class="sq-rec-s">${r.score} / ${r.full}</span>
        <span class="sq-rec-d">${esc((r.created_at || '').slice(5, 16))}</span></div>`).join('')
      : '<p class="empty">还没写过</p>';
  } catch (e) { /* 记录拉不到不该挡住写题 */ }
}

function sqOpenSub(id) {
  const it = sqSub.find(x => x.id === id); if (!it) return;
  sqCur = it;
  push({ view: 'sqwrite', title: it.part_name });
  const sk = it.skeleton;
  $('#sq-write').innerHTML = `
    <div class="card">
      <div class="sq-q-h"><span class="sq-qt ${it.part}">${esc(it.part_name)}</span>
        <span class="sq-qk">${it.year ? it.year + ' 年资中真题'
    : esc((it.src || '外省题库').replace(/\.pdf$/i, ''))}</span>
        <span class="sq-qs">${it.score} 分</span></div>
      <div class="sq-stem">${esc(it.stem)}</div>
    </div>
    ${sk ? `<div class="card sq-skel">
      <div class="sq-sec-t">${artEm('🦴')} 骨架：${esc(sk.name)}</div>
      <ol class="sq-skel-l">${sk.steps.map(x => `<li>${esc(x)}</li>`).join('')}</ol>
      <div class="sq-note">${esc(sk.hint)}</div></div>` : ''}
    <div class="card">
      <div class="sq-sec-t">你的答案</div>
      <textarea id="sq-ans" class="sq-sub" rows="14"
        placeholder="按骨架一条一条写。写完点批改，会逐个采分点告诉你答到没答到。"></textarea>
      <div class="sq-note" id="sq-wc">0 字</div>
      <button class="btn primary sq-wide" id="sq-do-grade">逐点批改</button>
    </div>
    <div id="sq-gres"></div>`;
}

async function sqDoGrade() {
  const el = $('#sq-ans'); if (!el || !sqCur) return;
  const btn = $('#sq-do-grade');
  btn.disabled = true; btn.textContent = '批改中…（约十几秒）';
  try {
    const d = await postJSON('/api/shequ/grade', { qid: sqCur.id, answer: el.value });
    sqRenderGrade(d);
  } catch (e) { toast(errMsg(e), true); }
  btn.disabled = false; btn.textContent = '逐点批改';
}

function sqRenderGrade(d) {
  if (!d.gradable) {
    $('#sq-gres').innerHTML = `<div class="card"><div class="sq-note">${esc(d.note || '')}</div>
      <div class="sq-cmp-t">参考答案</div><div class="sq-cmp-b">${esc(d.reference || '')}</div></div>`;
    return;
  }
  const MK = { hit: '✓', partial: '◐', miss: '✗' };
  $('#sq-gres').innerHTML = `
    <div class="card">
      <div class="scoreline"><span class="big">${d.score}<small> / ${d.full} 分</small></span>
        <span class="muted">${d.points.filter(p => p.verdict === 'hit').length} 点答全 ·
          ${d.points.filter(p => p.verdict === 'partial').length} 点沾边 ·
          ${d.points.filter(p => p.verdict === 'miss').length} 点没写</span></div>
      ${d.points.map(p => `
        <div class="pt ${p.verdict === 'hit' ? 'hit' : p.verdict === 'partial' ? 'half' : 'miss'}">
          <span class="mk">${MK[p.verdict]}</span>
          <span><b>${esc(p.name)}</b>：${esc(p.why || '')}
            ${p.yours ? `<span class="sq-f-s">你写的：${esc(p.yours)}</span>` : ''}
            ${p.verdict !== 'hit' ? `<span class="sq-f-s">标准要点：${esc(p.detail || '')}</span>` : ''}
          </span>
          <span class="sc">${p.got} / ${p.max}</span>
        </div>`).join('')}
      ${d.advice ? `<div class="sq-rule">${artEm('💡')} ${esc(d.advice)}</div>` : ''}
    </div>
    ${(d.repeat || []).length ? `<div class="card sq-doubt-entry">
      <div class="sq-sec-t">${artEm('⚠')} 这几点你反复漏</div>
      ${d.repeat.map(r => `<div class="sq-w-a">「${esc(r.name)}」—— 近 20 次里漏了 ${r.n} 回</div>`).join('')}
      <div class="sq-note">一次没答上是手滑，两次以上是没记住 —— 骨架里就缺这一环。</div></div>` : ''}
    ${(d.issues || []).length ? `<div class="card">
      <div class="sq-sec-t">格式检查（纯代码判定，判据有真题实证）</div>
      ${d.issues.map(e => `<div class="chk bad"><span class="m">✗</span>
        <span>${esc(e.bad)}<span class="sq-f-s">应为：${esc(e.good)}</span></span></div>`).join('')}
    </div>` : ''}
    <div class="card"><div class="sq-cmp-t">参考答案</div>
      <div class="sq-cmp-b">${esc(d.reference || '')}</div></div>`;
}

/* ---------------------------------------------------------------- 裁决台 */
async function openSqCheck() {
  push({ view: 'sqcheck', title: '入库校对' });
  $('#sq-check').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/shequ/doubts');
    sqRenderCheck(d);
  } catch (e) { $('#sq-check').innerHTML = `<p class="empty">${esc(errMsg(e))}</p>`; }
}

function sqRenderCheck(d) {
  const health = (d.health || []).map(h => `
    <div class="card">
      <div class="sq-sec-t">${esc((h.name || '').replace(/\.pdf$/i, ''))}</div>
      <div class="sq-facts">
        <div class="sq-fact"><div class="v">${h.obj || 0}</div><div class="k">客观题总数</div></div>
        <div class="sq-fact"><div class="v ok">${h.ok || 0}</div><div class="k">过闸，可练</div></div>
        <div class="sq-fact"><div class="v warn">${h.doubt || 0}</div><div class="k">存疑待裁决</div></div>
        <div class="sq-fact"><div class="v bad">${h.bad || 0}</div><div class="k">不入库</div></div>
        ${h.todo ? `<div class="sq-fact"><div class="v">${h.todo}</div><div class="k">还没校对</div></div>` : ''}
      </div>
    </div>`).join('');
  const items = (d.items || []).map(it => {
    const note = it.note || {};
    const parties = (note.parties || []).map(p => `
      <div class="sq-party"><span class="who">${esc(p.who)}</span>
        <span class="ans">${esc(p.answer || '—')}</span>
        <span class="why">${esc(p.note || '')}</span></div>`).join('');
    const opts = (it.options || []).map((o, i) =>
      `<div class="sq-opt ro"><span class="sq-l">${SQ_L[i]}</span><span>${esc(o)}</span></div>`).join('');
    /* 本地事实题单独说一句：招录人数、年龄上限这类只写在当地公告里的数字，
       模型没有依据、给出的答案还互相矛盾。这时**源卷比模型可信**，
       不提醒的话很容易顺手点「采信建议」，把对的答案改坏。 */
    const localTip = note.local ? `<div class="sq-local-tip">${artEm('📍')}
        这是<b>本地事实题</b> —— 招录人数、年龄上限、合同期限这类只写在资中当地公告里的数字，
        模型答不了、也查不到，它们的答案是猜的。除非你手上有公告原文，否则<b>维持源卷</b>。</div>` : '';
    return `<div class="card sq-doubt${note.local ? ' local' : ''}" data-sq-q="${it.id}">
        <div class="sq-q-h"><span class="sq-qt ${it.part}">${esc(it.part_name)}</span>
          <span class="sq-qk">${esc(it.paper_name || '').replace(/\.pdf$/i, '')} 第 ${it.seq} 题</span>
          <span class="sq-badge warn">${it.verify === 'bad' ? '题干有问题'
            : note.local ? '本地事实题' : '答案存疑'}</span></div>
        ${localTip}
        <div class="sq-stem">${esc(it.stem)}</div>
        ${opts ? `<div class="sq-opts">${opts}</div>` : ''}
        <div class="sq-verdict">
          <div class="sq-party src"><span class="who">源卷标注</span>
            <span class="ans">${esc(sqAnsText(it))}</span><span class="why">${esc(note.why || '')}</span></div>
          ${parties}
        </div>
        <div class="sq-acts">
          ${note.suggest && note.suggest !== it.answer
            ? `<button class="btn primary" data-sq-act="accept">采信 ${esc(note.suggest)}，改正入库</button>` : ''}
          <button class="btn${note.local ? ' primary' : ''}" data-sq-act="keep">源卷是对的，过闸</button>
          <button class="btn" data-sq-act="hold">保留存疑</button>
          <button class="btn" data-sq-act="drop">这题不能用</button>
        </div>
      </div>`;
  }).join('');
  $('#sq-check').innerHTML = health
    + (items || '<div class="card sq-allright">' + artEm('✅') + ' 没有待裁决的题</div>');
}

/* ---------------------------------------------------------------- 事件 */
$('#view-sqdrill').addEventListener('click', (e) => {
  const r = e.target.closest('[data-sq-dr]');
  if (!r) return;
  const [kind, val] = r.dataset.sqDr.split(':');
  sqDrillStart(kind, val);
});

$('#view-sqsub').addEventListener('click', (e) => {
  const c = e.target.closest('[data-sq-sub]');
  if (c) sqOpenSub(+c.dataset.sqSub);
});

$('#view-sqwrite').addEventListener('click', (e) => {
  if (e.target.closest('#sq-do-grade')) sqDoGrade();
});
$('#view-sqwrite').addEventListener('input', (e) => {
  if (e.target.id === 'sq-ans') $('#sq-wc').textContent = e.target.value.trim().length + ' 字';
});

$('#view-sqlocal').addEventListener('click', (e) => {
  const q = e.target.closest('[data-sq-quiz]');
  if (q) sqOpenPaper(+q.dataset.sqQuiz, 'study');   // 专项一律背题：目的是记住，不是模考
});

$('#view-sqreal').addEventListener('click', async (e) => {
  const op = e.target.closest('[data-sq-open]');
  if (op) { sqOpenPaper(+op.dataset.sqOpen, op.dataset.sqMode); return; }
  if (e.target.closest('#sq-go-check')) { openSqCheck(); return; }
  const rec = e.target.closest('[data-sq-rec]');
  if (rec) { sqOpenRecord(+rec.dataset.sqRec); }
});

$('#view-sqrun').addEventListener('click', (e) => {
  if (!sqRun) return;
  const o = e.target.closest('[data-sq-opt]');
  if (o) { sqPick(o.dataset.sqOpt); return; }
  const tf = e.target.closest('[data-sq-tf]');
  if (tf) { sqPick(tf.dataset.sqTf); return; }
  const jp = e.target.closest('[data-sq-jump]');
  if (jp) { sqStash(); sqRun.idx = +jp.dataset.sqJump; sqRender(); return; }
  if (e.target.closest('#sq-multi-ok')) {
    // 多选题的「确定提交」：背题模式下这一下才揭晓；模考模式只是确认并翻页
    if (sqRun.mode === 'exam') { sqGo(1); return; }
    (sqRun.locked = sqRun.locked || {})[sqRun.items[sqRun.idx].id] = true;
    sqRender();
    return;
  }
  if (e.target.closest('#sq-prev')) { sqGo(-1); return; }
  if (e.target.closest('#sq-next')) { sqGo(1); return; }
  if (e.target.closest('#sq-submit')) { sqSubmit(false); return; }
  if (e.target.closest('#sq-sheet-btn')) {
    const s = $('#sq-sheet');
    s.innerHTML = sqSheetHtml();
    s.classList.toggle('hidden');
  }
});

$('#view-sqres').addEventListener('click', (e) => {
  if (!e.target.closest('#sq-back-list')) return;
  /* 交卷是「列表 → 做题 → 成绩」，要退两层；回看是「列表 → 成绩」，退一层。
     按栈里有没有做题页判，不靠记一个标志位 —— 标志位迟早和真实栈走散。 */
  back();
  if (stack.length && stack[stack.length - 1].view === 'sqrun') back();
});

$('#view-sqcheck').addEventListener('click', async (e) => {
  const b = e.target.closest('[data-sq-act]');
  if (!b) return;
  const card = b.closest('[data-sq-q]');
  const qid = +card.dataset.sqQ, act = b.dataset.sqAct;
  if (act === 'drop' && !await appConfirm('判定这题没法用？它将永不发出。')) return;
  try {
    await postJSON(`/api/shequ/doubt/${qid}`, { act });
    toast(act === 'accept' ? '已改正并入库' : act === 'keep' ? '已过闸' :
      act === 'drop' ? '已标为不能用' : '保留存疑');
    openSqCheck();
  } catch (err) { toast(errMsg(err), true); }
});

/* 判断题的键盘操作。只在做题页、且当前是判断题时接管，别抢了别处的输入 */
document.addEventListener('keydown', (e) => {
  if (document.body.dataset.view !== 'sqrun' || !sqRun) return;
  if (/^(INPUT|TEXTAREA)$/.test((e.target.tagName || '').toUpperCase())) return;
  const it = sqRun.items[sqRun.idx];
  const k = e.key.toUpperCase();
  if (it.part === 'judge' && (k === 'J' || k === 'K')) { sqPick(k === 'J' ? 'T' : 'F'); e.preventDefault(); }
  else if ((it.part === 'single' || it.part === 'multi') && SQ_L.includes(k)) { sqPick(k); e.preventDefault(); }
  else if (e.key === 'Enter') { sqGo(1); e.preventDefault(); }
});

window.openSqReal = openSqReal;
window.openSqCheck = openSqCheck;
window.openSqLocal = openSqLocal;
window.openSqSub = openSqSub;
window.openSqDrill = openSqDrill;
