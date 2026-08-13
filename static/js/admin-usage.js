/* 使用观测 —— 后台第五块可观测。
   admin.html 是独立页面（不进主应用的 bundle），$ / esc / toast / adminConfirm
   都由它的内联脚本先定义好，这里直接用。

   这一屏的排版顺序是**按能不能指导今天的行动**排的，不是按数据多少：
   先是「今天该做多少题」（唯一一个当天就能执行的数字），
   再是走势（看得出断没断），最后才是逐个功能的冷热（那是做减法用的，不急在今天）。 */

const UG_STATE = { hot: '在用', cold: '冷了', dead: '停用', never: '从未用过', broken: '取数失败' };

function ugNum(n) { return (n === null || n === undefined) ? '—' : n; }

/* 覆盖率进度条。一条轨道上画两段：实心是已做的，浅色是「照当前速度还能补上的」，
   剩下的空白就是**照这个节奏到考试那天也做不完的部分**。
   把「差距」画成空白而不是画成另一根柱子，是因为它本来就该是个缺口。 */
function ugTrack(cov) {
  const done = cov.pct || 0;
  const proj = Math.max(done, cov.projected_pct || 0);
  return `
    <div class="ug-track" role="img"
         aria-label="题库覆盖 ${done}%，按当前速度到考试日可达 ${proj}%">
      <i class="ug-proj" style="width:${proj}%"></i>
      <i class="ug-done" style="width:${done}%"></i>
    </div>
    <div class="ug-tlegend">
      <span><em class="ug-s1"></em>已做 <b>${cov.done}</b> 道 · ${done}%</span>
      <span><em class="ug-s2"></em>照当前速度可达 <b>${ugNum(cov.projected)}</b> 道 · ${proj}%</span>
      <span><em class="ug-s3"></em>差 <b>${Math.max(0, cov.bank - (cov.projected || 0))}</b> 道</span>
    </div>`;
}

/* 每日做题量。没做题的那天画成一条底线而不是不画 —— 断掉的日子正是要看的东西。 */
function ugSpark(daily) {
  const max = Math.max(1, ...daily.map(d => d.n));
  const bars = daily.map(d => {
    const h = d.n ? Math.max(6, Math.round(d.n * 100 / max)) : 0;
    return `<i class="${d.n ? '' : 'zero'}" style="height:${h}%"
              title="${d.date} · ${d.n} 题"></i>`;
  }).join('');
  const first = daily[0], last = daily[daily.length - 1];
  return `
    <div class="ug-spark">${bars}</div>
    <div class="ug-sparkx"><span>${esc(first.date.slice(5))}</span><span>${esc(last.date.slice(5))}</span></div>`;
}

function ugFeatRow(f) {
  const idle = f.idle_days === null || f.idle_days === undefined ? '—'
    : (f.idle_days === 0 ? '今天' : f.idle_days + ' 天前');
  return `
    <div class="ug-row ${f.state}">
      <span class="ug-dot"></span>
      <span class="ug-name">${esc(f.name)}<i>${esc(f.what)}</i></span>
      <span class="ug-n">${f.d7}</span>
      <span class="ug-n">${f.d30}</span>
      <span class="ug-n">${f.total}</span>
      <span class="ug-last">${esc(idle)}</span>
      <span class="ug-tag">${esc(UG_STATE[f.state] || f.state)}${f.note ? ' · ' + esc(f.note) : ''}</span>
    </div>`;
}

async function loadUsage() {
  const box = $('#ug-body');
  try {
    const r = await fetch('/api/admin/usage', { cache: 'no-store' });
    const d = await r.json();
    if (!r.ok) { box.innerHTML = '<p class="ai-tip">读取失败：' + esc(d.error || '') + '</p>'; return; }
    const cov = d.coverage, s = d.states, t = d.tally;

    // 按分组归拢，组内按「冷的排前面」——要做减法，就得让该砍的先跳出来
    const order = { never: 0, dead: 1, broken: 2, cold: 3, hot: 4 };
    const groups = {};
    (d.features || []).forEach(f => { (groups[f.group] = groups[f.group] || []).push(f); });
    Object.values(groups).forEach(g => g.sort((a, b) => order[a.state] - order[b.state]));

    const groupHtml = Object.keys(groups).map(g => `
      <h3 class="st-h">${esc(g)}</h3>
      <div class="ug-table">
        <div class="ug-row head">
          <span class="ug-dot"></span><span class="ug-name">功能</span>
          <span class="ug-n">7 天</span><span class="ug-n">30 天</span><span class="ug-n">累计</span>
          <span class="ug-last">最后一次</span><span class="ug-tag"></span>
        </div>
        ${groups[g].map(ugFeatRow).join('')}
      </div>`).join('');

    const examLine = cov.days_left === null || cov.days_left === undefined
      ? '还没填考试日期（备考规划里填上，这块才算得出「今天该做多少」）'
      : `${esc(cov.exam || '考试')} ${esc(cov.exam_date)} · 还剩 <b>${cov.days_left}</b> 天`;

    box.innerHTML = `
      <div class="hl-grid">
        <div class="ql-card ${s.pace}">
          <div class="ql-top"><span class="hl-dot ${s.pace === 'bad' ? 'down' : s.pace}"></span>
            <b class="hl-name">今天该做</b></div>
          <div class="ql-num"><b>${ugNum(cov.need)}</b> 道</div>
          <div class="hl-note">${examLine}。<br>
            还有 <b>${cov.left}</b> 道没做过，摊到剩下的每一天就是这个数。
            最近 30 天日均 <b>${cov.pace}</b> 道。</div>
        </div>
        <div class="ql-card ${s.habit}">
          <div class="ql-top"><span class="hl-dot ${s.habit === 'bad' ? 'down' : s.habit}"></span>
            <b class="hl-name">最近 30 天</b></div>
          <div class="ql-num"><b>${d.active_days_30}</b> / 30 天在练</div>
          <div class="hl-note">练题的日子有这么多天。<b>不是练得多不多的问题，是断没断的问题</b>——
            隔一天补得回来，隔一周补不回来。</div>
        </div>
        <div class="ql-card ${s.build}">
          <div class="ql-top"><span class="hl-dot ${s.build === 'bad' ? 'down' : s.build}"></span>
            <b class="hl-name">建了没用的</b></div>
          <div class="ql-num"><b>${t.dead + t.never}</b> 个功能</div>
          <div class="hl-note">超过 30 天没碰过、或者从来没碰过。
            在用 ${t.hot} 个、冷了 ${t.cold} 个。<b>这些是可以停止维护的候选</b>，
            不是要你去用它们。</div>
        </div>
      </div>

      <h3 class="st-h">真题覆盖 · ${cov.done} / ${cov.bank} 道</h3>
      <div class="ai-cfg">
        ${ugTrack(cov)}
        <p class="ai-tip" style="margin:10px 0 0;">分母是<b>有答案的 ${cov.bank} 道</b>（没答案的做了也判不了对错，不该算进待办）。
          「照当前速度可达」= 已做 + 近 30 天日均 × 剩余天数，是个粗数字，
          但它把「速度」和「时间」合成了一个能对着目标看的结论。</p>
      </div>

      <h3 class="st-h">每天做了多少题 · 最近 30 天</h3>
      <div class="ai-cfg">
        ${ugSpark(d.daily)}
        <p class="ai-tip" style="margin:10px 0 0;">真题 + 专项练合计。<b>没做题的那天画成一条底线</b>，
          不是留白 —— 断掉的日子正是这张图要说的事。</p>
      </div>

      ${groupHtml}

      <p class="ai-tip" style="margin-top:14px;">数字全部来自各功能自己的业务记录（做了一道题、收了一条词），
        <b>没有埋点</b>：点开看一眼不算用，留下东西才算。所以这块一上线就带着完整的历史，
        不用等新数据慢慢攒。</p>`;
  } catch (e) {
    box.innerHTML = '<p class="ai-tip">读取失败：' + esc(e.message) + '</p>';
  }
}

$('#ug-refresh').onclick = loadUsage;
loadUsage();
