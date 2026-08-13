/* 通用「划重点」（悬浮球 → 🖍）
 *
 * 由 app.js 按它自己的区段边界切出（原 L10816-11034）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, artEm, c, errMsg, esc, IS_MOBILE, lsGet, lsSet, NW_KIND, push, stack,
   toast */

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
  const col = mkColor(hit.kind);
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
    mk.style.setProperty('--mk', col);
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
  mkBarState = null;
  mkUnwatch();
  $('#mk-bar').classList.add('hidden');
  mkHideList();
  if (window.mkInject) setTimeout(() => mkInject(), 60);   // 清完了，把「帮我划重点」的卡片长回来
}
/* 划重点：**按模块**做，不是一个全局按钮套所有页面。
   每个模块划的东西根本不是一回事 —— 常识划「定义/数字/易混」（选项就改那一个字），
   错题划「陷阱/正解」，范文划「分论点/论证/表达」。类型清单和「这个模块该看什么」
   都由服务端 MK_PROFILES 给（GET /api/marks/profile），前端不另写一份。
   入口是各模块页顶部自动长出来的一张卡片（和时政那张一样），不在悬浮球里。 */
const MK_COLORS = ['#c4661f', '#1e8449', '#1a6fb5', '#7a5cc0', '#b23b2e'];
let mkProf = null, mkProfScope = '';

/* 正文里的 <mark>、清单、图例，颜色必须出自同一处。
   以前正文那一层查的是时政的 NW_KIND（只有 提法/数据/政策/金句 四类），范文的
   「分论点/素材/论证/衔接」一个都查不到、全落到 NW_KIND['提法'] 的橙色上——
   于是清单里五颜六色、正文里清一色橙。要先查本模块 profile 的颜色。 */
function mkColor(kind) {
  return (mkProf && mkProf.color && mkProf.color[kind])
    || (NW_KIND[kind] && NW_KIND[kind].c) || MK_COLORS[0];
}

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
  if (!root) return;
  if (root.querySelector('mark.gk-mk')) return;                        // 已经划过了（结果条归 mkSyncBar 管）
  if (mkText(root).replace(/\s+/g, ' ').trim().length < 120) return;   // 正文太短不值当
  let p;
  try { p = await mkGetProf(st.view); } catch (_) { return; }
  const card = document.createElement('div');
  card.id = 'mk-card'; card.className = 'mk-card';
  // focus 里用 **xx** 标了要强调的词（后端写的），转成粗体，别把星号露出来
  const bold = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  card.innerHTML = `<div class="mk-card-t">${artEm('🖍')} 重点 · 考点</div>
    <p class="mk-card-p">${p.focus ? bold(p.focus) + '<br>' : ''}
      点一下，AI 按<b>「${esc(p.name)}」的考法</b>在本页标出：
      ${p.kinds.map(k => `<span class="mk-ck" style="--mk:${p.color[k.k]}">${esc(k.k)}</span>`).join('')}</p>
    <button class="btn primary" id="mk-go">${artEm('🖍')} 帮我划重点</button>`;
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
    mkWatch();          // 这一屏的正文一旦被换掉，结果条自己收（见 mkSyncBar）
    toast('划出 ' + n + ' 处重点' + (d.cached ? '（缓存）' : ''));
  } catch (e) {
    toast(errMsg(e), true);
    if (btn) { btn.disabled = false; btn.textContent = '🖍 帮我划重点'; }
  }
}
function mkRenderBar(n, cached) {
  const p = mkProf || { name: '', kinds: [], color: {} };
  /* profile 也一起记着：中途逛过别的模块，mkProf 已经被换成人家的了，
     回来重建这张清单不能拿错颜色和类型名。
     st 记的是**当时的导航栈顶对象**：视图名认不出「换了一篇文章」（两篇成文都是
     writed），但 push 进来的是一个新对象、back 回去的还是原来那个 —— 对象身份
     恰好就是「还是不是这一屏」。 */
  mkBarState = { n, cached, prof: mkProf, scope: mkProfScope, st: stack[stack.length - 1] };
  $('#mk-bar').innerHTML = `🖍 划出 <b>${n}</b> 处重点${cached ? ' <i>· 缓存</i>' : ''}
    <button class="btn tiny" id="mk-toggle">看清单</button>
    <button class="mk-x" id="mk-clear" title="清除">${artEm('✕')}</button>`;
  $('#mk-list').innerHTML = `<div class="mk-lt">${artEm('🖍')} ${esc(p.name)} · 重点考点（${mkMarks.length} 处）</div>
    ${mkMarks.map((m, i) => `<div class="nw-m" data-mkgo="${i}" style="--mk:${mkColor(m.kind)}">
        <span class="nw-k">${esc(m.kind)}</span>
        <span class="nw-q">${esc(m.quote)}</span>
        <span class="nw-w">${esc(m.why || '')}</span></div>`).join('')}
    <div class="nw-legend">${p.kinds.map(k =>
      `<span style="--mk:${mkColor(k.k)}"><i></i>${esc(k.k)}：${esc(k.d)}</span>`).join('')}</div>`;
  mkShowBar();
}
/* ---- 结果条摆哪儿：手机端钉在屏幕下方，电脑端可以拖、拖到哪下次还在哪 ---- */
const MK_POS_KEY = 'gk.mkbar.pos';
let mkBarState = null;      // 结果条现在显示的内容（换页收起后原样接回来）
let mkPos = null;           // 电脑端拖到的位置 {x,y}（左上角 px）

function mkLoadPos() {
  if (mkPos) return mkPos;
  try { mkPos = JSON.parse(lsGet(MK_POS_KEY, 'null')); } catch (_) { mkPos = null; }
  return mkPos;
}
// 贴回记住的位置，并夹回视口内 —— 上次拖到右下角、这次窗口小了，不能让它跑到屏幕外面去
function mkApplyPos() {
  const bar = $('#mk-bar');
  const p = IS_MOBILE ? null : mkLoadPos();
  if (!p) { bar.classList.remove('mk-moved'); bar.style.left = bar.style.top = ''; return; }
  bar.classList.add('mk-moved');
  bar.style.left = Math.min(Math.max(8, p.x), Math.max(8, innerWidth - bar.offsetWidth - 8)) + 'px';
  bar.style.top = Math.min(Math.max(8, p.y), Math.max(8, innerHeight - bar.offsetHeight - 8)) + 'px';
}
// 清单跟着结果条走：下面放不下就翻到上面去
function mkPlaceList() {
  const list = $('#mk-list'), bar = $('#mk-bar');
  const reset = () => { list.classList.remove('mk-moved'); list.style.left = list.style.top = ''; };
  if (IS_MOBILE) {
    /* 手机端：结果条钉在屏幕下方，清单贴着它往上展开。条子多高**实测**——
       写死一个 bottom 常数的话，条子一换行（窄屏 + 长模块名）就被清单压住，
       「看清单」按钮点都点不到。 */
    reset();
    list.style.bottom = Math.round(innerHeight - bar.getBoundingClientRect().top + 10) + 'px';
    return;
  }
  list.style.bottom = '';
  if (!bar.classList.contains('mk-moved')) { reset(); return; }
  list.classList.add('mk-moved');
  const b = bar.getBoundingClientRect(), lw = list.offsetWidth, lh = list.offsetHeight;
  list.style.left = Math.min(Math.max(8, b.left + b.width / 2 - lw / 2),
    Math.max(8, innerWidth - lw - 8)) + 'px';
  list.style.top = (b.bottom + 8 + lh <= innerHeight - 8 ? b.bottom + 8
    : Math.max(8, b.top - lh - 8)) + 'px';
}
function mkShowBar() { $('#mk-bar').classList.remove('hidden'); mkApplyPos(); }
function mkHideList() {
  $('#mk-list').classList.add('hidden');
  document.body.classList.remove('mk-open');
  const t = $('#mk-toggle'); if (t) t.textContent = '看清单';
}

/* ---- 结果条什么时候在：只有一条规矩 ----
   **它描述的那些 <mark> 还在眼前这一屏上**，它才在。别的判断都靠不住：
   结果条和清单是 position:fixed 的顶层元素，页面切走了自己不会消失；而「切走了没有」
   既不能靠视图名认（同一个 writed 下有无数篇成文），也不能靠定时器猜（正文是异步渲染的，
   在成文里 fetch 期间旧正文还挂着，等 260ms 再看就会把上一篇的结果条接到这一篇头上）。
   所以：位置变化（render）和内容变化（MutationObserver）都来这儿复核一遍。 */
function mkOnPage() {
  if (!mkBarState) return false;
  if (stack[stack.length - 1] !== mkBarState.st) return false;   // 换了一屏（新 push 的是另一个对象）
  const root = mkPageRoot();                                     // 视图藏起来时它返回 null
  return !!(root && root.querySelector('mark.gk-mk'));
}
function mkSyncBar() {
  if (mkOnPage()) {
    if (!$('#mk-bar').classList.contains('hidden')) return;      // 已经在了，别重画（清单可能正开着）
    mkProf = mkBarState.prof; mkProfScope = mkBarState.scope;    // 换回这一页的 profile
    mkRenderBar(mkBarState.n, mkBarState.cached);
    return;
  }
  $('#mk-bar').classList.add('hidden');
  mkHideList();
}
window.__mkView = mkSyncBar;      // shell.js 的 render() 每次换页都叫一声

/* 正文被换掉（同一屏里重画、或者打开了另一篇）时，那些 <mark> 就没了 —— 结果条得跟着收。
   DOM 变化是唯一可靠的信号，靠延时猜时机迟早猜错。整份卷子/长文的 childList 变动不算频繁，
   再加 120ms 合并，代价可以忽略。 */
let mkObs = null, mkSyncT = 0;
function mkWatch() {
  if (mkObs) { mkObs.disconnect(); mkObs = null; }
  const root = mkPageRoot();
  const box = root && root.closest('.view');
  if (!box || !window.MutationObserver) return;
  mkObs = new MutationObserver(() => {
    clearTimeout(mkSyncT);
    mkSyncT = setTimeout(mkSyncBar, 120);
  });
  mkObs.observe(box, { childList: true, subtree: true });
}
function mkUnwatch() {
  if (mkObs) { mkObs.disconnect(); mkObs = null; }
  clearTimeout(mkSyncT);
}

// 电脑端：按住结果条空白处拖（按在按钮上不算拖），松手记住位置
$('#mk-bar').addEventListener('pointerdown', e => {
  if (IS_MOBILE || e.target.closest('button')) return;
  const bar = $('#mk-bar'), r = bar.getBoundingClientRect();
  const dx = e.clientX - r.left, dy = e.clientY - r.top;
  let moved = false;
  const move = (ev) => {
    // 挪够 4px 才算拖：手一抖就跑位的话，点「看清单」都点不准
    if (!moved && Math.abs(ev.clientX - e.clientX) + Math.abs(ev.clientY - e.clientY) < 4) return;
    moved = true;
    bar.classList.add('mk-moved', 'dragging');
    mkPos = { x: ev.clientX - dx, y: ev.clientY - dy };
    mkApplyPos();
    if (!$('#mk-list').classList.contains('hidden')) mkPlaceList();
  };
  const up = () => {
    bar.removeEventListener('pointermove', move);
    bar.removeEventListener('pointerup', up);
    bar.removeEventListener('pointercancel', up);
    bar.classList.remove('dragging');
    if (moved) lsSet(MK_POS_KEY, JSON.stringify(mkPos));
  };
  try { bar.setPointerCapture(e.pointerId); } catch (_) { /* 捕获不到就按普通 move 走 */ }
  bar.addEventListener('pointermove', move);
  bar.addEventListener('pointerup', up);
  bar.addEventListener('pointercancel', up);
});
addEventListener('resize', () => {
  if ($('#mk-bar').classList.contains('hidden')) return;
  mkApplyPos();
  if (!$('#mk-list').classList.contains('hidden')) mkPlaceList();
});

document.addEventListener('click', e => {
  if (e.target.closest('#mk-clear')) { mkClear(); return; }
  if (e.target.closest('#mk-toggle')) {
    const on = $('#mk-list').classList.toggle('hidden');
    $('#mk-toggle').textContent = on ? '看清单' : '收起清单';
    document.body.classList.toggle('mk-open', !on);   // 清单铺开时把悬浮球收起来，别互相挡
    if (!on) mkPlaceList();
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
