/* 资料分析的材料：表格 / 柱状图 / 折线图 / 饼图（内联 SVG）
 *
 * drill.js / quiz.js / dtest.js 三家共用 dtMaterial —— 这是它独立成模块的理由。
 * （原先这里还堆着每日测验的一半、每日任务、组队互监，已分别拆去
 *   dtest.js / tasks.js / team.js。）
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global esc */

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
/* 把两题共用的一份材料折叠成一行提示，不重复渲染整张表/图。
   prev = 上一题的材料对象（列表渲染时传 arr[i-1].material，单题渲染不传）。
   —— 原先这里靠一个模块级全局 _dtLastMat 记「上一份」，逼着 dtest/drill/quiz 三家
   在开新一轮前各自记得清空它；谁忘了清，新一轮第一题就折叠成指向空气的「↑ 根据上面
   这份材料作答」（drill.js 的注释「别被上一题的缓存吃掉」就是踩过之后补的）。改成
   把「上一份」显式传进来后，去重只看相邻两题、不留跨渲染的状态，也就没得可忘。 */
function dtMaterial(m, i, prev) {
  if (!m) return '';
  if (prev && JSON.stringify(prev) === JSON.stringify(m))
    return '<div class="dt-same">↑ 根据上面这份材料作答</div>';  // 两题共用一份材料，不重复渲染
  /* 真题的材料是**一段纯文本**（片段阅读的文段、资料分析的文字资料），
     不是 figgen 那种 {type:'table', headers, rows} 结构体。不特判的话会掉进下面
     的图表分支：m.labels 是 undefined，渲染出一张空图 + 一个空的「看数据表」。 */
  if (typeof m === 'string') {
    const t = m.trim();
    return t ? `<div class="dt-mat dt-mtxt">${esc(t).replace(/\n+/g, '<br>')}</div>` : '';
  }
  const head = `<div class="dt-mt">${esc(m.title || '根据下列资料，回答问题')}${m.unit ? `<span>单位：${esc(m.unit)}</span>` : ''}</div>`;
  if (m.type === 'table') return `<div class="dt-mat">${head}${dtTable(m)}</div>`;
  // 图表另附「看数据表」，方便核对数字（也是无障碍要求：不能只靠图形）
  const tb = { headers: ['项目', ...(m.labels || [])],
    rows: (m.series || []).map(s => [s.name, ...s.data.map(v => dtNum(v))]) };
  return `<div class="dt-mat">${head}${dtChart(m)}${dtLegend(m.series || [])}
    <button class="ch-tbtn" data-chtb="${i}">📋 看数据表</button>
    <div class="ch-tbwrap hidden" id="chtb-${i}">${dtTable(tb)}</div></div>`;
}
