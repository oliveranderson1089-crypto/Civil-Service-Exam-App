/* 常考（高频考点合集）+ 上位词
 *
 * 由 app.js 按它自己的区段边界切出（原 L6395-6684）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, appConfirm, appPrompt, artEm, c, DT_L, errMsg, esc, IC, injectReadBtns,
   openClassicDetail, push, toast, uiError */

/* ================= 常考（高频考点合集） + 上位词 ================= */
async function openChangkao() {
  push({ view: 'changkao', title: '常考' });
  loadCkBoards();
  loadHyperDaily();
}
async function loadCkBoards() {
  $('#ck-boards').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/changkao/boards');
    let nStar = 0;
    try { nStar = (await api('/api/changkao/stars')).total; }
    catch (e) { console.debug('[常考] 收藏数取不到，按 0 显示：%s', (e && e.message) || e); }
    $('#ck-boards').innerHTML = '<div class="home-cards cs-cards" data-dragsort="ckb">' + d.boards.map(b => `
      <div class="home-card ck-card" data-ckb="${esc(b.key)}">
        <div class="hc-logo hc-ck">${IC[b.icon] || IC.bulb}</div>
        <div class="hc-name">${esc(b.name)}</div>
        <div class="hc-desc">${b.count} 条 · ${esc(b.desc)}</div>
      </div>`).join('') + `
      <div class="home-card ck-card ck-star-card" data-ckb="收藏">
        <div class="hc-logo hc-star">★</div>
        <div class="hc-name">我的收藏</div>
        <div class="hc-desc">${nStar} 条 · 各模块收藏的都在这</div>
      </div>` + '</div>';
  } catch (e) { $('#ck-boards').innerHTML = uiError(e); }
}
$('#ck-boards').addEventListener('click', e => {
  const c = e.target.closest('[data-ckb]'); if (c) openCkBoard(c.dataset.ckb);
});
async function loadHyperDaily() {
  try {
    const d = await api('/api/hyper/daily');
    if (!d.items || !d.items.length) { $('#ck-daily').classList.add('hidden'); return; }
    $('#ck-daily').innerHTML = `<div class="ckd-tag">${artEm('🎯')} 今日推荐 · 上位词</div>` +
      d.items.map(it => `<div class="ckd-item" data-ckd="${it.id}">
        <div class="ckd-h">${esc(it.hyper)}</div>
        <div class="ckd-s">${esc(it.subs || '')}</div>
        ${it.note ? `<div class="ckd-n">${esc(it.note)}</div>` : ''}
      </div>`).join('');
    $('#ck-daily').classList.remove('hidden');
  } catch (_) { $('#ck-daily').classList.add('hidden'); }
}
$('#ck-daily').addEventListener('click', () => openCkBoard('上位词'));

let ckBoard = '', ckItems = [], ckKind = 'text';
async function openCkBoard(key) {
  ckBoard = key;
  await loadCkStarred();                        // 各模块都要标★
  push({ view: 'ckboard', title: key === '上位词' ? '上位词积累' : (key === '收藏' ? '我的收藏' : '常考 · ' + key) });
  $('#ckb-search').value = '';
  $('#ckb-ai').classList.toggle('hidden', key !== '上位词');
  $('#ckb-head').innerHTML = '';
  $('#ckb-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    if (key === '收藏') {
      const d = await api('/api/changkao/stars');
      ckItems = d.boards.flatMap(b => b.items.map(x =>
        ({ id: x.item_id, title: x.title, content: x.content, note: x.note, _b: b.board })));
      ckKind = 'star';
      $('#ckb-head').innerHTML = `<span class="ckb-n">${d.total} 条</span>` +
        '<span class="ckb-tip">再点一次 ★ 取消收藏</span>';
      renderCkList();
      return;
    }
    const d = await api('/api/changkao/items?board=' + encodeURIComponent(key));
    ckItems = d.items; ckKind = d.kind;
    const days = key === '古诗积累' ? new Set(d.items.map(x => x.day)).size : 0;
    $('#ckb-head').innerHTML = `<span class="ckb-n">${d.items.length} 条</span>` +
      (key === '上位词' ? '<span class="ckb-tip">逻辑填空里题干出现上位词，答案必须与它同类</span>' : '') +
      (key === '古诗积累'
        ? `<span class="ckb-n">${days} 天</span>` +
          '<span class="ckb-tip">「今日复习 · 古诗」每天新出的诗自动收进来</span>' : '');
    renderCkList();
  } catch (e) { $('#ckb-list').innerHTML = uiError(e); }
}
// 收藏是**各模块通用**的（key = "板块:id"）。成语/实词额外同步进「成语词语积累」——
// 收藏就是为了拿去背，散在两处等于没收。
let ckStarred = new Set();
async function loadCkStarred() {
  try {
    const d = await api('/api/changkao/stars?ids=1');
    ckStarred = new Set(d.ids || []);
  } catch (_) { /* 取不到就按默认显示，下次进来会重拉 */ }
}
function renderCkList() {
  const q = $('#ckb-search').value.trim();
  const list = q ? ckItems.filter(it =>
    (it.title || '').includes(q) || (it.content || '').includes(q) || (it.note || '').includes(q)) : ckItems;
  if (!list.length) {
    $('#ckb-list').innerHTML = ckBoard === '收藏'
      ? '<p class="empty">还没收藏。进任一模块，点卡片上的 ☆ 就收进来了。</p>'
      : (ckBoard === '古诗积累' && !q)
        ? '<p class="empty">还是空的。去「今日复习 · 古诗」背一轮，当天新出的诗会自动收进这里。</p>'
        : '<p class="empty">没有匹配的内容</p>';
    return;
  }
  let ckDay = '';                                   // 古诗积累：一天一段，段首插日期条
  $('#ckb-list').innerHTML = list.map(it => {
    const b = it._b || ckBoard;                       // 收藏页里每条来自不同板块
    const key = b + ':' + it.id;
    const on = ckStarred.has(key);
    const freq = it.freq && b === '成语' ? `<span class="cki-freq">考频 ${it.freq}</span>` : '';
    const note = (it.note || '').replace(/^考频 \d+ 次(\s·\s)?/, '');   // 考频已单独成徽章
    const tip = CK_TO_ENTRY[b] ? '收藏 → 同时收进「成语词语积累」' : '收藏';
    let head = '';
    if (b === '古诗积累' && it.day !== ckDay) {
      ckDay = it.day;
      head = `<div class="cki-day">${esc(ckDayLabel(it.day))}</div>`;
    }
    return head + `<div class="gk-card ck-item" data-cki="${it.id}"
      data-ckbd="${esc(b)}"${it.cid ? ` data-ckcid="${it.cid}"` : ''}>
      <div class="cki-t">${esc(it.title)}${freq}
        ${ckBoard === '收藏' ? `<span class="cki-from">${esc(b)}</span>` : ''}
        <button class="cki-star${on ? ' on' : ''}" data-ckstar="${esc(b)}:${it.id}"
          title="${tip}">${on ? '★' : '☆'}</button>
        ${ckKind === 'hyper' ? `<button class="cki-del" data-ckdel="${it.id}">${artEm('🗑')}</button>` : ''}</div>
      ${it.meaning ? `<div class="cki-mean"><b>释义</b>${esc(it.meaning)}</div>` : ''}
      ${it.content ? `<div class="cki-c">${b === '实词' && it.meaning ? '<span class="cki-c-lab">搭配</span>' : ''}${esc(it.content)}</div>` : ''}
      ${note ? `<div class="cki-n">${(ckKind === 'classic' || b === '古诗文' || b === '古诗积累') ? esc(note) : '💡 ' + esc(note)}</div>` : ''}
      ${it.common ? `<div class="cki-gs"><b>常识考点</b>${esc(it.common)}</div>` : ''}
      ${it.apply ? `<div class="cki-gs"><b>申论怎么用</b>${esc(it.apply)}</div>` : ''}
      ${(b === '上位词') ? '<div class="cki-more">点开看每个下位词的典故 / 出处 / 怎么考 ›</div>'
        : (b === '成语' || b === '实词') ? '<div class="cki-more">点开看典故 / 出处 / 怎么考 ›</div>'
          : (b === '古诗积累') ? '<div class="cki-more">点开看全诗 / 译文 / 赏析 ›</div>' : ''}
    </div>`;
  }).join('');
}
// 这两类收藏时会同步进「言语理解 → 成语词语积累」的对应分类（服务端 CK_TO_ENTRY 也有一份）
const CK_TO_ENTRY = { '成语': '成语', '实词': '词语' };
// 古诗积累的日期条：近几天说人话，远的给日期（YYYY-MM-DD 直接拼 T00:00:00，别交给 new Date(str) 猜时区）
function ckDayLabel(day) {
  if (!day) return '日期不明';
  const d = Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(day + 'T00:00:00').getTime()) / 86400000);
  const md = day.slice(5).replace('-', ' 月 ') + ' 日';
  if (d === 0) return '今天 · ' + md;
  if (d === 1) return '昨天 · ' + md;
  if (d > 1 && d <= 6) return d + ' 天前 · ' + md;
  return day;
}
$('#ckb-search').addEventListener('input', renderCkList);
$('#ckb-list').addEventListener('click', async e => {
  const star = e.target.closest('[data-ckstar]');
  if (star) {                                   // 收藏 / 取消收藏（各模块通用）
    e.stopPropagation();
    const [b, id] = star.dataset.ckstar.split(':');
    star.disabled = true;
    try {
      const r = await api('/api/changkao/star', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ board: b, id: +id }),
      });
      if (r.starred) {
        ckStarred.add(b + ':' + id);
        star.textContent = '★'; star.classList.add('on');
        toast(r.to_entry ? `已收藏，并收进「成语词语积累 · ${r.category}」，明天开始进复习`
          : (CK_TO_ENTRY[b] ? '已收藏（「成语词语积累」里本来就有）' : '已收藏'));
      } else {
        ckStarred.delete(b + ':' + id);
        star.textContent = '☆'; star.classList.remove('on');
        toast('已取消收藏');
        if (ckBoard === '收藏') { openCkBoard('收藏'); return; }   // 收藏页里取消了就移走
      }
    } catch (err) { toast(errMsg(err), true); }
    star.disabled = false;
    return;
  }
  const del = e.target.closest('[data-ckdel]');
  if (del) {
    e.stopPropagation();
    if (!(await appConfirm('从上位词库中删除这一组？'))) return;
    try { await api('/api/hyper/' + del.dataset.ckdel, { method: 'DELETE' }); openCkBoard('上位词'); }
    catch (er) { toast(errMsg(er), true); }
    return;
  }
  const it = e.target.closest('[data-cki]');
  if (!it) return;
  const b = it.dataset.ckbd || ckBoard;
  // 古诗积累里 data-cki 是**卡的 id**（要和复习/收藏对得上），点开要用诗的 id，走 data-ckcid
  if (b === '古诗积累') { if (it.dataset.ckcid) openClassicDetail(+it.dataset.ckcid); }
  else if (b === '古诗文') openClassicDetail(+it.dataset.cki);
  else if (b === '上位词') openHyper(+it.dataset.cki);              // 上位词：点开看典故/来源
  else if (b === '成语' || b === '实词') openCkStory(+it.dataset.cki);   // 成语/实词：点开看典故
});

/* 成语/实词的典故：出处原文 + 故事 + 本义怎么引申成今义 + 公考怎么考。
   看懂来历自然就记住了，不用死背释义。AI 讲一次就缓存，之后秒开。 */
async function openCkStory(cid) {
  push({ view: 'cdetail', title: '典故' });
  $('#cd-wrap').innerHTML = '<p class="empty">正在讲典故…（第一次约 20 秒，之后秒开）</p>';
  try {
    const d = await api('/api/changkao/' + cid + '/story');
    const s = d.story || {};
    $('#cd-wrap').innerHTML = `
      <div class="cd-head"><div class="cd-title">${esc(d.title)}</div>
        <div class="cd-meta">常考 · ${esc(d.board || '')}${d.freq ? ` · 考频 ${d.freq} 次` : ''}</div></div>
      ${d.content ? `<div class="cd-sec"><div class="cd-sec-t">释义</div><div class="cd-sec-b">${esc(d.content)}</div></div>` : ''}
      ${s.origin ? `<div class="cd-sec"><div class="cd-sec-t">📜 出处</div><div class="cd-sec-b ck-origin">${esc(s.origin)}</div></div>` : ''}
      ${s.story ? `<div class="cd-sec"><div class="cd-sec-t">${artEm('📖')} 典故</div><div class="cd-sec-b ck-story">${esc(s.story)}</div></div>` : ''}
      ${s.evolve ? `<div class="cd-sec"><div class="cd-sec-t">${artEm('🔗')} 本义 → 今义</div><div class="cd-sec-b">${esc(s.evolve)}</div></div>` : ''}
      ${s.usage ? `<div class="cd-sec cd-ai"><div class="cd-sec-t">${artEm('🎯')} 公考怎么考</div><div class="cd-sec-b">${esc(s.usage)}</div></div>` : ''}
      <div class="cd-sec" id="ck-ex"><div class="cd-sec-t">${artEm('✍️')} 例句</div>
        <div class="cd-sec-b"><button class="btn tiny" id="ck-ex-go" data-cid="${cid}">找一句真实例句</button>
        <span class="ck-ex-hint">先在人民日报等真语料里找；找不到才 AI 仿写（会标明）</span></div></div>
      <div class="cd-sec" id="ck-cf"><div class="cd-sec-t">⚖️ 易混辨析</div>
        <div class="cd-sec-b"><button class="btn tiny" id="ck-cf-go" data-cid="${cid}">辨析相似词</button>
        <span class="ck-ex-hint">逻辑填空考的就是「这几个近义词该用哪个」</span></div></div>`;
    window.scrollTo(0, 0);
    injectReadBtns();
    ckLoadExample(cid);          // 已经有例句就直接显示，不用点
    ckLoadConfuse(cid, true);
  } catch (e) {
    $('#cd-wrap').innerHTML = uiError(e);
  }
}

/* ---- 例句：真语料优先（人民日报等），找不到才 AI 仿写并标明 ---- */
async function ckLoadExample(cid, force) {
  const box = $('#ck-ex'); if (!box) return;
  const btn = $('#ck-ex-go');
  if (!force && btn) { btn.disabled = true; btn.textContent = '查找中…'; }
  try {
    const d = await api(`/api/changkao/${cid}/example${force ? '?force=1' : ''}`);
    const ai = (d.src || '').startsWith('AI');
    box.querySelector('.cd-sec-b').innerHTML = `
      <div class="ck-ex">${esc(d.example)}</div>
      <div class="ck-ex-src ${ai ? 'ai' : 'real'}">${ai ? '✎' : '📰'} ${esc(d.src || '')}</div>`;
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = '找一句真实例句'; }
  }
}
document.addEventListener('click', e => {
  const b = e.target.closest('#ck-ex-go');
  if (b) { b.disabled = true; b.textContent = '查找中…'; ckLoadExample(+b.dataset.cid, true); }
});

/* ---- 易混辨析：给出 2~3 个最容易混的词，逐条说清「用哪个」 ---- */
async function ckLoadConfuse(cid, quiet) {
  const box = $('#ck-cf'); if (!box) return;
  try {
    const d = await api(`/api/changkao/${cid}/confuse${quiet ? '' : '?force=1'}`);
    if (quiet && !d.cached) return;         // 静默模式只显示已经生成过的，不主动烧 AI
    ckRenderConfuse(box, d);
  } catch (_) { /* 取不到就按默认显示，下次进来会重拉 */ }
}
function ckRenderConfuse(box, d) {
  const q = d.quiz;
  box.querySelector('.cd-sec-b').innerHTML = `
    ${d.key ? `<div class="ck-cf-key">🔑 ${esc(d.key)}</div>` : ''}
    ${(d.items || []).map(x => `
      <div class="ck-cf-i">
        <div class="ck-cf-w">${esc(d.word)} <i>vs</i>
          ${x.in_lib ? `<b class="ck-cf-go" data-ckcf="${x.id}">${esc(x.word)}</b>`
                     : `<b>${esc(x.word)}</b><span class="ck-cf-out">库外</span>`}</div>
        <div class="ck-cf-r"><span>词义侧重</span>${esc(x.focus || '')}</div>
        <div class="ck-cf-r"><span>感情色彩</span>${esc(x.color || '')}</div>
        <div class="ck-cf-r"><span>搭配对象</span>${esc(x.collocation || '')}</div>
        ${x.wrong ? `<div class="ck-cf-bad">✗ ${esc(x.wrong)}</div>` : ''}
      </div>`).join('')}
    ${q ? `<div class="ck-cf-quiz" data-ans="${esc(q.answer)}">
        <div class="ck-cf-q">${artEm('📝')} ${esc(q.stem)}</div>
        <div class="ck-cf-opts">${q.options.map((o, i) =>
          `<button class="dt-opt" data-ckq="${DT_L[i]}">${esc(o)}</button>`).join('')}</div>
        <div class="ck-cf-why hidden">${esc(q.why || '')}</div>
      </div>` : ''}`;
}
document.addEventListener('click', e => {
  const b = e.target.closest('#ck-cf-go');
  if (b) { b.disabled = true; b.textContent = '辨析中…（约 20 秒）'; ckLoadConfuse(+b.dataset.cid); return; }
  const g = e.target.closest('[data-ckcf]');
  if (g) { openCkStory(+g.dataset.ckcf); return; }        // 点对比词 → 直接看它的详情
  const o = e.target.closest('[data-ckq]');
  if (o) {                                                 // 填空自测：选完立刻判
    const box = o.closest('.ck-cf-quiz');
    const ans = box.dataset.ans;
    box.querySelectorAll('[data-ckq]').forEach(x => {
      x.disabled = true;
      if (x.dataset.ckq === ans) x.classList.add('correct');
      else if (x === o) x.classList.add('wrong');
    });
    box.querySelector('.ck-cf-why').classList.remove('hidden');
  }
});

/* 上位词详解：每个下位词的出处、典故、公考考点（AI 讲一次就缓存，之后秒开） */
async function openHyper(hid) {
  push({ view: 'cdetail', title: '上位词详解' });
  $('#cd-wrap').innerHTML = '<p class="empty">正在讲典故…（第一次要 30 秒左右，之后秒开）</p>';
  try {
    const d = await api('/api/hyper/' + hid);
    $('#cd-wrap').innerHTML = `
      <div class="cd-head"><div class="cd-title">${esc(d.hyper)}</div>
        <div class="cd-meta">上位词 · 逻辑填空里的概括词</div></div>
      <div class="cd-sec"><div class="cd-sec-t">下位词</div>
        <div class="cd-sec-b">${esc(d.subs || '')}</div></div>
      ${d.note ? `<div class="cd-sec"><div class="cd-sec-t">${artEm('💡')} 提示</div><div class="cd-sec-b">${esc(d.note)}</div></div>` : ''}
      ${(d.story || []).map(x => `
        <div class="cd-sec hy-sec">
          <div class="cd-sec-t">${esc(x.name)}</div>
          ${x.origin ? `<div class="hy-row"><b>出处</b>${esc(x.origin)}</div>` : ''}
          ${x.story ? `<div class="hy-row hy-story"><b>典故</b>${esc(x.story)}</div>` : ''}
          ${x.point ? `<div class="hy-row hy-point"><b>怎么考</b>${esc(x.point)}</div>` : ''}
        </div>`).join('')}`;
    window.scrollTo(0, 0);
    injectReadBtns();
  } catch (e) {
    $('#cd-wrap').innerHTML = uiError(e);
  }
}
$('#ckb-ai').onclick = async () => {
  const w = await appPrompt('AI 补充上位词', '输入一个词（如「戏曲」或「京剧」），AI 会归纳它的上位词与同类下位词');
  if (!w || !w.trim()) return;
  toast('AI 分析中…');
  try {
    const d = await api('/api/hyper/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ word: w.trim() }) });
    toast(d.cached ? '已在库中：' + d.hyper : '已收录：' + d.hyper);
    openCkBoard('上位词');
  } catch (e) { toast(errMsg(e), true); }
};
