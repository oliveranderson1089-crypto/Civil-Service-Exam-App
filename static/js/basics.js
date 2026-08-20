/* 各板块基础知识点
 *
 * 由 app.js 按它自己的区段边界切出（原 L3241-3290）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, artEm, c, errMsg, esc, mdToHtml, push, rqStart, stack, toast, uiError */

/* ================= 机构讲义：优路精讲 / 三色速记 / 考点对照 =================
 *
 * 资料由 ingest_basics.py 解析入库，这里只读。三套界面共用两个渲染函数：
 * bkMd（正文，负责把 {{r|…}} 变成三色高亮）和 bkBlocks（按 kind 分样式）。
 */
let bkAvail = null;                    // board → {youlu:n, sanse:n, compare:n}
let bkMeta = {};
let bkTree = null, bkCmpBoard = '', bkNodePr = null, bkCmpPr = null;

(async function loadBkAvail() {
  try { const d = await api('/api/basics/entries'); bkAvail = d.boards || {}; bkMeta = d.meta || {}; }
  catch (_e) { bkAvail = {}; }         // 拉不到就当没有讲义，板块页照常显示其余卡片
})();

/* 板块页要摆哪几张讲义卡 —— 只摆真有资料的那几张 */
/* 社区那条线的考点树挂在**三个真板块**下（社会工作 / 社区知识 / 法律法规），
   而「社区」本身是给「练」标签的 chip 用的伪板块。不在这儿把三本摊出来的话，
   从 练→社区 进去够不着考点树，得绕 按学科浏览→社区→社会工作 三层 ——
   那正是当初压层级要消灭的路径。 */
const SQ_BK_BOARDS = ['社会工作', '社区知识', '法律法规'];

function basicsFeats(board) {
  if (board === '社区') {
    return SQ_BK_BOARDS.map(b => {
      const n = ((bkAvail || {})[b] || {}).shequ;
      return n ? { key: 'bk-shequ@' + b, name: b + ' · 考点清单',
                   desc: n + ' 个考点 · 公告点名的范围', icon: 'compass' } : null;
    }).filter(Boolean);
  }
  const a = (bkAvail || {})[board];
  if (!a) return [];
  const out = [];
  // 来源清单从后端下发的 meta 里取，别在这儿写死一份 —— 加第三套资料（社区速记）
  // 时写死的那份会漏，表现是「库里有考点、板块页上没入口」，而且不报错。
  Object.keys(bkMeta || {}).forEach(s => {
    if (a[s]) out.push({
      key: 'bk-' + s, name: (bkMeta[s] || {}).name || s,
      desc: ((bkMeta[s] || {}).desc || '') + ' · ' + a[s] + ' 个考点',
      icon: (bkMeta[s] || {}).icon || 'book',
    });
  });
  if (a.compare && a.youlu && a.sanse) out.push({
    key: 'bk-cmp', name: '考点对照', icon: 'layers',
    desc: '同一考点 · 详解与速记并排 · ' + a.compare + ' 个考点',
  });
  return out;
}

/* 三色的三色：{{r|…}} → <mark>。mdToHtml 会转义 HTML，标记本身穿得过去，
   所以在它之后再替换是安全的（内容里的 {{ }} 入库时已经剔掉）。 */
function bkMd(md) {
  return mdToHtml(md || '', { breaks: true })
    .replace(/\{\{([rbg])\|([\s\S]*?)\}\}/g, (m, tag, txt) => '<mark class="bk-' + tag + '">' + txt + '</mark>');
}

const BK_KIND = {
  concept: { t: '', cls: '' },
  example: { t: '例题', cls: 'bk-ex' },
  answer: { t: '解析', cls: 'bk-ans' },
  /* 扫描件笔记里的表格（家庭类型、人生八阶段这些对照表）。mdToHtml 本来就认
     markdown 表格，这里只是给它一个标签和自己的边距。 */
  table: { t: '对照表', cls: 'bk-table' },
};

/* 正文块。带 sid 时每块挂一个「看原书这一页」——图形推理的图、数量/资料的分式
   竖式，纯文本救不回来，点开原页是唯一靠谱的兜底。 */
function bkBlocks(blocks, sid) {
  return (blocks || []).map(b => {
    const k = BK_KIND[b.kind] || BK_KIND.concept;
    const to = b.page_to || b.page;
    const pg = (sid && b.page)
      ? `<button class="bk-pagebtn" data-bkpage="${sid}:${b.page}:${to}">${artEm('🖼')} 原书 ${to > b.page ? `P${b.page}-P${to}` : 'P' + b.page}</button>` : '';
    return `<div class="bk-block ${k.cls}">${k.t ? `<span class="bk-tag">${k.t}</span>` : ''}
      <div class="bk-body">${bkMd(b.md)}</div>${pg}</div>`;
  }).join('') || '<p class="empty">这一节没有正文</p>';
}

/* 学完就练：这个考点对应真题里的哪几个题型，一起出（考点↔题型是一对多） */
function bkPractice(p) {
  if (!p || !p.count) return '';
  return `<div class="bk-practice">
      <div class="bk-practice-t">学完了？拿真题练一练</div>
      <div class="bk-practice-d">${esc(p.name)} · ${p.count} 道可做（${p.qtypes.map(esc).join(' / ')}）</div>
      <div class="bk-practice-btns">
        ${[5, 10, 20].filter(n => n <= p.count).map(n =>
    `<button class="btn primary" data-bkq="${n}">练 ${n} 题</button>`).join('')}
      </div></div>`;
}

function bkStartPractice(p, n) {
  if (!window.rqStart) { toast('真题模块还没就绪'); return; }
  rqStart({ mode: 'type', module: p.module, qtypes: p.qtypes, n: n }, p.name);
}

/* 点开原书页：就地展开一张图，再点收起（不跳页，读到哪看到哪） */
function bkTogglePage(btn) {
  const [sid, from, to] = btn.dataset.bkpage.split(':').map(Number);
  let next = btn.nextElementSibling;
  if (next && next.classList.contains('bk-pageimg')) {          // 再点收起（整段一起收）
    while (next && next.classList.contains('bk-pageimg')) {
      const gone = next; next = next.nextElementSibling; gone.remove();
    }
    return;
  }
  // 块跨几页就贴几页：图形推理的一道题，题干和图常常分在相邻两页上
  let anchor = btn;
  for (let p = to; p >= from; p--) {                            // 倒着插，顺序才是正的
    const img = document.createElement('img');
    img.className = 'bk-pageimg';
    img.loading = 'lazy';
    img.src = '/api/basics/page?source_id=' + sid + '&page=' + p;
    img.alt = '原书第 ' + p + ' 页';
    anchor.insertAdjacentElement('afterend', img);
  }
}

/* ---------------- 目录树 ---------------- */
async function openBasicsTree(board, source) {
  push({ view: 'bktree', title: board + ' · ' + ((bkMeta[source] || {}).name || '') });
  $('#bktree-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    bkTree = await api('/api/basics/tree?board=' + encodeURIComponent(board) + '&source=' + source);
    renderBkTree();
  } catch (e) { $('#bktree-wrap').innerHTML = uiError(e); }
}

/* 树有几层是**资料决定的**，不是写死的：
   优路/三色一板块一册，树是「章 → 考点」两层；
   社区那条线一个板块摞着十几册，树是「书 → 章/节 → 考点」三层。
   早先这儿写死了两层，社区线 2590 个考点全长在第三层 —— 界面上一个都看不到，
   点开章节只有一片空白。所以按「有没有孩子」决定摆成组还是摆成叶子，别数层号。 */
function renderBkTree() {
  const d = bkTree, tops = d.nodes.filter(n => !n.parent_id);
  const kids = id => d.nodes.filter(n => n.parent_id === id);
  const leaf = n => `<div class="bk-leaf" data-bknode="${n.id}">
      <span class="bk-leaf-t">${esc(n.title)}</span>
      <span class="bk-leaf-n">${n.blocks || 0} 段</span></div>`;
  // 中间层：自己有正文就也能点开读（章前面常有一段引子），下面再列它的考点
  const branch = n => {
    const sub = kids(n.id);
    if (!sub.length) return leaf(n);
    return `<div class="bk-sub">
      <div class="bk-sub-h" data-bkfold="${n.id}">
        <span class="bk-sub-t">${esc(n.title)}</span>
        <button class="bk-sweep-btn" data-bksweep="${n.id}"
          title="把这一节的考点摊开成清单">速览</button>
        <span class="bk-leaf-n">${sub.length}</span>
      </div>
      <div class="bk-group-b" id="bkg-${n.id}">${sub.map(leaf).join('')}</div>
    </div>`;
  };
  const groups = tops.map(t => {
    const sub = kids(t.id);
    const deep = sub.some(n => kids(n.id).length);
    return `<div class="bk-group">
      <div class="bk-group-h" data-bkfold="${t.id}">
        <span class="bk-group-t">${esc(t.title)}</span>
        ${sub.length ? `<button class="bk-sweep-btn" data-bksweep="${t.id}"
          title="把整本/整章的考点摊开成清单">速览</button>` : ''}
        <span class="bk-leaf-n">${sub.length || (t.blocks || 0)}</span>
      </div>
      <div class="bk-group-b" id="bkg-${t.id}">
        ${sub.length ? sub.map(deep ? branch : leaf).join('') : leaf(t)}
      </div></div>`;
  }).join('');
  $('#bktree-wrap').innerHTML = `
    <div class="bk-head"><div class="bk-head-t">${esc((d.meta || {}).name || '')}</div>
      <div class="bk-head-d">${esc(d.title || '')}</div></div>${groups}`;
}

$('#bktree-wrap').addEventListener('click', e => {
  const sw = e.target.closest('[data-bksweep]');
  if (sw) { openBasicsSweep(+sw.dataset.bksweep); return; }
  const f = e.target.closest('[data-bkfold]');
  if (f) { $('#bkg-' + f.dataset.bkfold).classList.toggle('fold'); f.classList.toggle('fold'); return; }
  const n = e.target.closest('[data-bknode]');
  if (n) openBasicsNode(+n.dataset.bknode);
});

/* ---------------- 考点正文 ---------------- */
async function openBasicsNode(id) {
  push({ view: 'bknode', title: '加载中…' });
  $('#bknode-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/basics/node/' + id);
    $('#top-title').textContent = d.title;
    const crumb = (d.path || []).map(p => esc(p.title)).join(' › ');
    const nav = `<div class="bk-nav">
      ${d.prev ? `<button class="btn" data-bknode="${d.prev.id}">‹ ${esc(d.prev.title)}</button>` : '<span></span>'}
      ${d.next ? `<button class="btn" data-bknode="${d.next.id}">${esc(d.next.title)} ›</button>` : '<span></span>'}
    </div>`;
    $('#bknode-wrap').innerHTML = `
      <div class="bk-head"><div class="bk-head-d">${crumb}${d.page ? ' · 原书 P' + d.page : ''}</div>
        <div class="bk-head-t">${esc(d.title)}</div></div>
      ${bkBlocks(d.blocks, d.source_id)}${bkPractice(d.practice)}${nav}`;
    bkNodePr = d.practice;
  } catch (e) { $('#bknode-wrap').innerHTML = uiError(e); }
}

$('#bknode-wrap').addEventListener('click', e => {
  const p = e.target.closest('[data-bkpage]');
  if (p) { bkTogglePage(p); return; }
  const q = e.target.closest('[data-bkq]');
  if (q) { bkStartPractice(bkNodePr, +q.dataset.bkq); return; }
  const n = e.target.closest('[data-bknode]');
  if (n) { stack.pop(); openBasicsNode(+n.dataset.bknode); }   // 前后翻不叠栈
});

/* ---------------- 整章速览 ----------------
   这批速记资料印出来本来就是「考点名｜要点串」一行一条的（见 12.社会工作综合能力
   重点笔记），考前扫的就是这个节奏。逐个点开读是精读的用法，两种都要有。 */
function bkSweepItem(it) {
  // 正文只有一段、而且短，就贴着标题排成两列；多段或带表格的老老实实竖着放，
  // 挤进右栏会把表格压成一条缝。
  const solo = (it.blocks || []).length === 1 && it.blocks[0].kind === 'concept'
    && (it.blocks[0].md || '').length <= 160 && !(it.kids || []).length;
  const body = solo
    ? `<div class="bk-sw-b">${bkMd(it.blocks[0].md)}</div>`
    : `<div class="bk-sw-b bk-sw-wide">${(it.blocks || []).map(b =>
      b.kind === 'table' ? bkMd(b.md) : `<p>${bkMd(b.md)}</p>`).join('')}
       ${(it.kids || []).map(k => `<div class="bk-sw-sub">
          <span class="bk-sw-subt">${esc(k.title)}</span>
          ${(k.blocks || []).map(b => bkMd(b.md)).join('')}</div>`).join('')}</div>`;
  return `<div class="bk-sw-item${solo ? '' : ' bk-sw-stack'}" data-bknode="${it.id}">
      <div class="bk-sw-n">${esc(it.title)}</div>${body}</div>`;
}

async function openBasicsSweep(nid) {
  push({ view: 'bksweep', title: '加载中…' });
  $('#bksweep-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/basics/sweep?nid=' + nid);
    $('#top-title').textContent = d.title;
    const empty = !d.items.length && !(d.blocks || []).length;
    $('#bksweep-wrap').innerHTML = `
      <div class="bk-head"><div class="bk-head-d">${esc(d.book || '')} · 速览</div>
        <div class="bk-head-t">${esc(d.title)}</div></div>
      ${(d.blocks || []).length ? `<div class="bk-sw-intro">${
      (d.blocks || []).map(b => bkMd(b.md)).join('')}</div>` : ''}
      ${empty ? '<p class="empty">这一章还没有正文</p>'
    : `<div class="bk-sw">${d.items.map(bkSweepItem).join('')}</div>`}
      <p class="bk-sw-tip">点任意一条可以进到它的精读页（带原书页码和练习）。</p>`;
  } catch (e) { $('#bksweep-wrap').innerHTML = uiError(e); }
}

$('#bksweep-wrap').addEventListener('click', e => {
  const n = e.target.closest('[data-bknode]');
  if (n) openBasicsNode(+n.dataset.bknode);
});

/* ---------------- 考点对照 ---------------- */
async function openBasicsCmp(board, repush) {
  bkCmpBoard = board;
  // repush=false 是「从考点详情退回列表」——详情本来就没入栈（同一个 view 内换内容），
  // 再 push 一层的话顶栏返回键第一下只是弹掉这层重复帧，界面纹丝不动
  if (repush !== false) push({ view: 'bkcmp', title: board + ' · 考点对照' });
  $('#bkcmp-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/basics/compare?board=' + encodeURIComponent(board));
    $('#bkcmp-wrap').innerHTML = `<div class="bk-head">
        <div class="bk-head-t">考点对照</div>
        <div class="bk-head-d">同一考点下，先看优路详解、再看三色速记</div></div>` +
      (d.topics || []).map(t => `<div class="bk-leaf" data-bktopic="${t.id}">
          <span class="bk-leaf-t">${esc(t.name)}</span>
          <span class="bk-leaf-n">${t.youlu ? '优路 ' + t.youlu : ''}${t.youlu && t.sanse ? ' · ' : ''}${t.sanse ? '三色 ' + t.sanse : ''}</span>
        </div>`).join('') || '<p class="empty">这个板块还没有对齐的考点</p>';
  } catch (e) { $('#bkcmp-wrap').innerHTML = uiError(e); }
}

async function openBasicsTopic(tid) {
  $('#bkcmp-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/basics/compare?board=' + encodeURIComponent(bkCmpBoard) + '&topic_id=' + tid);
    const side = (list, cls, label) => `<div class="bk-side ${cls}">
        <div class="bk-side-h">${label}</div>
        ${list.length ? list.map(n => `<div class="bk-side-n">
            <div class="bk-side-t">${esc(n.title)}${n.page ? ' <span class="bk-leaf-n">P' + n.page + '</span>' : ''}</div>
            ${bkBlocks(n.blocks, n.source_id)}</div>`).join('')
    : '<p class="empty">这套资料没讲这个考点</p>'}</div>`;
    $('#bkcmp-wrap').innerHTML = `
      <div class="bk-head"><div class="bk-head-d"><button class="btn" id="bkcmp-back">‹ 考点列表</button></div>
        <div class="bk-head-t">${esc(d.topic.name)}</div></div>
      <div class="bk-cmp">${side(d.youlu || [], 'bk-y', artEm('📘') + ' 优路 · 系统精讲')}
        ${side(d.sanse || [], 'bk-s', artEm('⚡') + ' 三色笔记 · 速记')}</div>${bkPractice(d.practice)}`;
    bkCmpPr = d.practice;
  } catch (e) { $('#bkcmp-wrap').innerHTML = uiError(e); }
}

$('#bkcmp-wrap').addEventListener('click', e => {
  const p = e.target.closest('[data-bkpage]');
  if (p) { bkTogglePage(p); return; }
  const q = e.target.closest('[data-bkq]');
  if (q) { bkStartPractice(bkCmpPr, +q.dataset.bkq); return; }
  const t = e.target.closest('[data-bktopic]');
  if (t) { openBasicsTopic(+t.dataset.bktopic); return; }
  if (e.target.closest('#bkcmp-back')) openBasicsCmp(bkCmpBoard, false);
});

/* ================= 板块基础知识点：AI 梳理 + 我的补充 ================= */
let bkbBoard = '', bkbData = null;
async function openBoardKb(board) {
  bkbBoard = board;
  push({ view: 'boardkb', title: board + ' · 基础知识点' });
  $('#bkb-wrap').innerHTML = '<p class="empty">加载中…</p>';
  try { const d = await api('/api/boardkb?board=' + encodeURIComponent(board)); bkbData = d; renderBkb(); }
  catch (e) { $('#bkb-wrap').innerHTML = uiError(e); }
}
function renderBkb() {
  const d = bkbData;
  const ai = d.ai
    ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">${artEm('📚')} 基础知识 · 方法技巧（AI 整理）</div>
        <div class="cd-sec-b">${mdToHtml(d.ai)}</div>
        <button class="btn cd-ai-regen" id="bkb-regen">重新生成</button></div>`
    : `<div class="bkb-gen"><p class="cd-tip" style="margin:0 0 12px">还没有整理这个板块的基础知识点，让 AI 帮你系统梳理一份。</p>
        <button class="btn primary" id="bkb-gen" style="width:100%;padding:13px;">${artEm('🤖')} AI 生成基础知识点</button></div>`;
  const pts = (d.points || []).map(p =>
    `<div class="bkb-point"><div class="bkb-point-c">${esc(p.content).replace(/\n/g, '<br>')}</div>
      <button class="bkb-point-del" data-bpdel="${p.id}">×</button></div>`).join('');
  $('#bkb-wrap').innerHTML = ai + `
    <div class="cd-sec"><div class="cd-sec-t">${artEm('✍️')} 我的补充</div>
      <div class="bkb-points">${pts || '<p class="cd-tip" style="margin:0 0 10px">还没有补充，写点自己的要点/技巧吧。</p>'}</div>
      <div class="bkb-add">
        <textarea id="bkb-input" rows="2" placeholder="添加一条自己的知识点/技巧…"></textarea>
        <button class="btn primary" id="bkb-addbtn">添加</button>
      </div>
    </div>`;
}
$('#bkb-wrap').addEventListener('click', async e => {
  const g = e.target.closest('#bkb-gen') || e.target.closest('#bkb-regen');
  if (g) {
    g.disabled = true; g.textContent = 'AI 生成中…（约二十秒）';
    try {
      const d = await api('/api/boardkb/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ board: bkbBoard, force: g.id === 'bkb-regen' }) });
      bkbData.ai = d.content; renderBkb(); toast('已生成');
    } catch (err) { toast(errMsg(err), true); g.disabled = false; g.textContent = '🤖 AI 生成基础知识点'; }
    return;
  }
  if (e.target.closest('#bkb-addbtn')) {
    const c = $('#bkb-input').value.trim(); if (!c) return;
    try { const p = await api('/api/boardkb/point', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ board: bkbBoard, content: c }) }); bkbData.points.unshift({ id: p.id, content: c }); renderBkb(); } catch (err) { toast(errMsg(err), true); }
    return;
  }
  const del = e.target.closest('[data-bpdel]');
  if (del) {
    try { await api('/api/boardkb/point/' + del.dataset.bpdel, { method: 'DELETE' }); bkbData.points = bkbData.points.filter(p => p.id != del.dataset.bpdel); renderBkb(); } catch (err) { toast(errMsg(err), true); }
  }
});
