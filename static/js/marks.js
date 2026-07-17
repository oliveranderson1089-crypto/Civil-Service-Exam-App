/* 通用「划重点」（悬浮球 → 🖍）
 *
 * 由 app.js 按它自己的区段边界切出（原 L10816-11034）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, NW_KIND, api, c, esc, push,
   stack, toast */

/* ================= 通用「划重点」（悬浮球 → 🖍） =================
   任何模块的正文都能划：不重渲染页面，而是直接在**已经渲染好的 DOM 里**找到那些句子、就地包一层 <mark>。
   所以时政、常识、理论、范文、讲义、错题解析…统统适用，不用每个模块单独写一遍。
   要害：AI 挑的句子必须逐字来自原文（服务端已核对），否则在 DOM 里根本找不到。 */
// 「不是正文」的东西：按钮、工具栏、脚本…… 取正文时一律跳过
const MK_SKIP_BASE = 'button, input, textarea, select, nav, .topbar, .tk-tab, .chip, .btn, ' +
  '.pgbar, .fab, .bm-tip, .mk-bar, .mk-card, script, style, .cd-sec-t, .slt-sec';
// 划重点自己还要跳过 <mark>：已经标过的别再标一遍
const MK_SKIP = MK_SKIP_BASE + ', mark';
// 但**文本锚不能跳过 <mark>**：划重点会把重点句包进 <mark>，跳过的话锚句就从全文里消失、
// 那一页的手写批注全变孤儿不画 —— 而用户圈的重点，恰恰就是 AI 划重点也会标的句子。
const ANN_SKIP = MK_SKIP_BASE;
let mkMarks = [];

function mkPageRoot() {                 // 当前页面的「正文」在哪
  const st = stack[stack.length - 1];
  if (!st) return null;
  const view = $('#view-' + st.view);
  if (!view || view.classList.contains('hidden')) return null;
  // 优先取常见的正文容器；找不到就整页（跳过按钮/工具栏）
  const pick = view.querySelector('.poly-reader, .cd-wrap, #cd-wrap, .doc-blocks, .aih-scroll');
  return pick || view;
}
// 段落/标题这些「块」：块与块之间的文字本来就不连着读
const MK_BLOCK = 'p, li, h1, h2, h3, h4, h5, h6, blockquote, td, th, pre, section, article, div';
const mkBlockOf = (n) => (n.parentElement ? n.parentElement.closest(MK_BLOCK) : null);
// skip 不传＝划重点用的名单（跳过 <mark>）；文本锚要传 ANN_SKIP（看得见 <mark> 里的字）。
// sep 不传＝所有文本节点直接首尾相接（划重点的老行为：它只拿去 indexOf，不在乎读不读得通）；
//   文本锚要传 '\n' —— 不然标题和正文会粘成一串（"…学习问答今天问了什么…"），锚句跨块、
//   拿去做复习卡就是一坨读不通的东西，也没法按句子去重。
// **mkText 和 mkNodes 必须传同一份 skip 和 sep**，否则算出来的偏移对不上。
function mkText(root, skip, sep) {
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (!n.nodeValue.trim() || n.parentElement.closest(skip || MK_SKIP))
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  let s = '', prev = null;
  while (w.nextNode()) {
    const n = w.currentNode;
    if (sep) { const b = mkBlockOf(n); if (prev && b !== prev) s += sep; prev = b; }
    s += n.nodeValue;
  }
  return s;
}
function mkNodes(root, skip, sep) {
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (!n.nodeValue.trim() || n.parentElement.closest(skip || MK_SKIP))
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  const out = []; let pos = 0, prev = null;
  while (w.nextNode()) {
    const n = w.currentNode;
    if (sep) { const b = mkBlockOf(n); if (prev && b !== prev) pos += sep.length; prev = b; }
    out.push({ n, start: pos });
    pos += n.nodeValue.length;
  }
  return out;
}
function mkWrapOne(root, hit) {
  // 每次重新取一遍节点表：上一处标注会改变 DOM，偏移必须重算
  const nodes = mkNodes(root);
  const k = NW_KIND[hit.kind] || NW_KIND['提法'];
  for (let i = nodes.length - 1; i >= 0; i--) {
    const { n, start } = nodes[i];
    const end = start + n.nodeValue.length;
    if (end <= hit.start || start >= hit.end) continue;
    const s = Math.max(0, hit.start - start), e = Math.min(n.nodeValue.length, hit.end - start);
    if (e <= s) continue;
    const r = document.createRange();
    r.setStart(n, s); r.setEnd(n, e);
    const mk = document.createElement('mark');
    mk.className = 'nw-mk gk-mk';
    mk.style.setProperty('--mk', k.c);
    mk.dataset.gkm = hit.i;
    mk.title = hit.kind + '：' + (hit.why || '');
    try { r.surroundContents(mk); } catch (_) { r.detach && r.detach(); continue; }
    const tag = document.createElement('i');   // 右上角的小类型标签
    tag.textContent = hit.kind;
    mk.appendChild(tag);
    break;                                     // 一个片段包一次就够（跨节点的下一轮再来）
  }
}
function mkApply(root, marks) {
  const full = mkText(root);
  const hits = [];
  marks.map((m, i) => ({ m, i })).sort((a, b) => b.m.quote.length - a.m.quote.length)   // 长句先标
    .forEach(({ m, i }) => {
      let from = 0, at;
      while ((at = full.indexOf(m.quote, from)) !== -1) {
        const end = at + m.quote.length;
        if (!hits.some(h => at < h.end && end > h.start)) hits.push({ start: at, end, i, kind: m.kind, why: m.why });
        from = end;
      }
    });
  hits.sort((a, b) => b.start - a.start);      // 从后往前改，前面的偏移才不会失效
  hits.forEach(h => mkWrapOne(root, h));
  return hits.length;
}
function mkClear() {
  document.querySelectorAll('mark.gk-mk').forEach(m => {
    const i = m.querySelector('i'); if (i) i.remove();
    const p = m.parentNode;
    while (m.firstChild) p.insertBefore(m.firstChild, m);
    p.removeChild(m);
    p.normalize();
  });
  mkMarks = [];
  $('#mk-bar').classList.add('hidden');
  $('#mk-list').classList.add('hidden');
  document.body.classList.remove('mk-open');
  if (window.mkInject) setTimeout(() => mkInject(), 60);   // 清完了，把「帮我划重点」的卡片长回来
}
/* 划重点：**按模块**做，不是一个全局按钮套所有页面。
   每个模块划的东西根本不是一回事 —— 常识划「定义/数字/易混」（选项就改那一个字），
   错题划「陷阱/正解」，范文划「分论点/论证/表达」。类型清单和「这个模块该看什么」
   都由服务端 MK_PROFILES 给（GET /api/marks/profile），前端不另写一份。
   入口是各模块页顶部自动长出来的一张卡片（和时政那张一样），不在悬浮球里。 */
const MK_COLORS = ['#c4661f', '#1e8449', '#1a6fb5', '#7a5cc0', '#b23b2e'];
let mkProf = null, mkProfScope = '';

// 哪些页面配划重点：服务端有 profile 的都算（问一次缓存住）
async function mkGetProf(scope) {
  if (mkProfScope === scope && mkProf) return mkProf;
  const d = await api('/api/marks/profile?scope=' + encodeURIComponent(scope));
  d.color = {};
  d.kinds.forEach((k, i) => { d.color[k.k] = MK_COLORS[i % MK_COLORS.length]; });
  mkProf = d; mkProfScope = scope;
  return d;
}
const MK_VIEWS = ['csboard', 'thboard', 'workd', 'partydict', 'policydocd', 'essayd', 'writed',
  'wqdetail', 'slresult', 'sltype', 'boardkb', 'docqad', 'cdetail', 'ckboard', 'viewer', 'fanwend'];

// 进到有划重点的模块，就在正文顶部长出这张卡（时政那张是模块自己写的，不走这里）
async function mkInject() {
  const st = stack[stack.length - 1];
  const old = document.getElementById('mk-card');
  if (old) old.remove();
  if (!st || !MK_VIEWS.includes(st.view)) return;
  const root = mkPageRoot();
  if (!root || mkText(root).replace(/\s+/g, ' ').trim().length < 120) return;   // 正文太短不值当
  if (root.querySelector('mark.gk-mk')) return;                                  // 已经划过了
  let p;
  try { p = await mkGetProf(st.view); } catch (_) { return; }
  const card = document.createElement('div');
  card.id = 'mk-card'; card.className = 'mk-card';
  // focus 里用 **xx** 标了要强调的词（后端写的），转成粗体，别把星号露出来
  const bold = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  card.innerHTML = `<div class="mk-card-t">🖍 重点 · 考点</div>
    <p class="mk-card-p">${p.focus ? bold(p.focus) + '<br>' : ''}
      点一下，AI 按<b>「${esc(p.name)}」的考法</b>在本页标出：
      ${p.kinds.map(k => `<span class="mk-ck" style="--mk:${p.color[k.k]}">${esc(k.k)}</span>`).join('')}</p>
    <button class="btn primary" id="mk-go">🖍 帮我划重点</button>`;
  root.insertBefore(card, root.firstChild);
}
document.addEventListener('click', e => {
  if (e.target.closest('#mk-go')) markPage();
});

async function markPage(force) {
  if (document.querySelector('mark.gk-mk') && !force) { mkClear(); toast('已清除重点'); return; }
  if (document.querySelector('.nw-mk:not(.gk-mk)')) { toast('这页已经划过重点了'); return; }
  const root = mkPageRoot();
  const text = root ? mkText(root).replace(/\s+/g, ' ').trim() : '';
  if (!root || text.length < 60) { toast('这页没有可划的正文', true); return; }
  const scope = stack[stack.length - 1].view;
  const btn = $('#mk-go');
  if (btn) { btn.disabled = true; btn.textContent = '划重点中…（约 20 秒）'; }
  try {
    await mkGetProf(scope);
    const d = await api('/api/marks', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: mkText(root), scope }),
    });
    mkClear();
    mkMarks = d.marks || [];
    const n = mkApply(root, mkMarks);
    if (!n) { toast('这页的正文和 AI 挑的句子对不上，换个页面试试', true); return; }
    const c = document.getElementById('mk-card'); if (c) c.remove();
    mkRenderBar(n, !!d.cached);
    toast('划出 ' + n + ' 处重点' + (d.cached ? '（缓存）' : ''));
  } catch (e) {
    toast(e.message, true);
    if (btn) { btn.disabled = false; btn.textContent = '🖍 帮我划重点'; }
  }
}
function mkRenderBar(n, cached) {
  const p = mkProf || { name: '', kinds: [], color: {} };
  const col = (k) => p.color[k] || (NW_KIND[k] && NW_KIND[k].c) || MK_COLORS[0];
  $('#mk-bar').innerHTML = `🖍 划出 <b>${n}</b> 处重点${cached ? ' <i>· 缓存</i>' : ''}
    <button class="btn tiny" id="mk-toggle">看清单</button>
    <button class="mk-x" id="mk-clear" title="清除">✕</button>`;
  $('#mk-bar').classList.remove('hidden');
  $('#mk-list').innerHTML = `<div class="mk-lt">🖍 ${esc(p.name)} · 重点考点（${mkMarks.length} 处）</div>
    ${mkMarks.map((m, i) => `<div class="nw-m" data-mkgo="${i}" style="--mk:${col(m.kind)}">
        <span class="nw-k">${esc(m.kind)}</span>
        <span class="nw-q">${esc(m.quote)}</span>
        <span class="nw-w">${esc(m.why || '')}</span></div>`).join('')}
    <div class="nw-legend">${p.kinds.map(k =>
      `<span style="--mk:${col(k.k)}"><i></i>${esc(k.k)}：${esc(k.d)}</span>`).join('')}</div>`;
}
document.addEventListener('click', e => {
  if (e.target.closest('#mk-clear')) { mkClear(); return; }
  if (e.target.closest('#mk-toggle')) {
    const on = $('#mk-list').classList.toggle('hidden');
    $('#mk-toggle').textContent = on ? '看清单' : '收起清单';
    document.body.classList.toggle('mk-open', !on);   // 清单铺开时把悬浮球收起来，别互相挡
    return;
  }
  const go = e.target.closest('[data-mkgo]');
  if (go) {
    const el = document.querySelector(`mark.gk-mk[data-gkm="${go.dataset.mkgo}"]`);
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      el.classList.add('flash');
      setTimeout(() => el.classList.remove('flash'), 1400);
    }
  }
});
