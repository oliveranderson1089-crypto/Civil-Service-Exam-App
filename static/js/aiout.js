/* AI 产出：助手生成的东西先落这儿，再由你决定投到哪。
 *
 * 为什么不让 AI 直接往资料库/云盘写：生成和投放是两件事。生成随时可能不满意
 * （重来一遍就行），投放是**会被别人看到**的动作。混在一起的话，AI 每写一版就往
 * 资料库堆一份，你还得回头去删。
 *
 * 这一页刻意做得薄：它是中转站不是仓库。没归档的产出 30 天自己清掉（服务端做），
 * 界面上就把「还剩几天」明说出来，省得有人把它当第二个云盘用。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 */
/* global $, api, appConfirm, appPrompt, artEm, esc, libTouch, errMsg, lsGet, lsSet,
   matPickMembers, mdToHtml, pickChatTargets, push, toast, uiError */

let aoItems = [], aoRetain = 30;

function openAiOut() { push({ view: 'aiout' }); loadAiOut(); }

async function loadAiOut() {
  const box = $('#ao-list');
  box.innerHTML = '<p class="ais-empty">加载中…</p>';
  try {
    const d = await api('/api/aiout');
    aoItems = d.items || [];
    aoRetain = d.retain_days || 30;
  } catch (e) { box.innerHTML = uiError(e); return; }
  aoPaint();
}

const AO_KIND = { md: '📄 文档', txt: '📄 文本', pdf: '📕 PDF' };
const AO_SOON = 7;      // 剩这么些天以内转琥珀：到这一档，再不管它是真的会没

/* 这一条还剩几天被自动清掉。
   保留期以前只写在页顶那句总说明里，可那句话保不住任何一条具体的产出 ——
   要判断的从来是「这一条今天要不要处理」。
   手工解析而不是 Date.parse：'YYYY-MM-DD HH:MM:SS' 这种没时区的写法，
   老 WebView（安卓 minSdk21）当 UTC、新引擎当本地时，差 8 小时就能差出一天。 */
function aoLeft(it) {
  const m = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(it.created_at || '');
  if (!m) return null;                   // 时间读不出来就不显示，别瞎猜一个天数
  const born = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  return Math.max(0, aoRetain - Math.floor((Date.now() - born) / 86400000));
}

/* 某一段开着还是收着。存的是「你上次自己拨到哪边」；从没拨过的时候：
   待处理默认摊开（每天要动的就是它），已归档默认收起 ——
   除非待处理是空的，那时候两段都收着的话，整页只剩两行标题。 */
function aoSecOpen(which, hasFresh) {
  const v = lsGet('ao:open:' + which);
  if (v === '1') return true;
  if (v === '0') return false;
  return which === 'fresh' ? true : !hasFresh;
}

function aoCard(it, i) {
  const left = it.kept ? null : aoLeft(it);   // 归档过的不会被清，没有「还剩几天」这回事
  return `
    <div class="ao-card" data-ao="${it.id}">
      <div class="ao-h">
        <span class="ao-k">${AO_KIND[it.kind] || '📄'}</span>
        <span class="ao-t">${esc(it.title)}</span>
        ${it.kept ? '<span class="ao-keep">已归档</span>' : ''}
      </div>
      <div class="ao-m">${it.size} 字 · ${esc((it.created_at || '').slice(5, 16))}${
        left === null ? ''
          : ` · <span class="ao-left${left <= AO_SOON ? ' soon' : ''}">剩 ${left} 天</span>`}${
        it.sent ? ' · 已投到 ' + esc(it.sent) : ''}</div>
      <div class="ao-acts">
        <button data-aoact="view" data-i="${i}">看全文</button>
        <button data-aoact="send" data-i="${i}">${artEm('📤')} 投放</button>
        <button data-aoact="share" data-i="${i}">${artEm('👥')} 分享</button>
        <button data-aoact="dl" data-i="${i}">下载</button>
        <button data-aoact="keep" data-i="${i}">${it.kept ? '取消归档' : '归档'}</button>
        <button data-aoact="rename" data-i="${i}">改名</button>
        <button data-aoact="del" data-i="${i}" class="ao-danger">删除</button>
      </div>
    </div>`;
}

function aoPaint() {
  const box = $('#ao-list');
  $('#ao-intro').textContent =
    'AI 生成的汇总、文档、题目先存在这里 · 没归档的 ' + aoRetain + ' 天后自动清掉';
  box.classList.remove('grouped');
  if (!aoItems.length) {
    box.innerHTML = '<p class="ais-empty">还没有产出。<br>在 AI 助手里点「汇总」，'
      + '或让它「写一份…存成文件」，东西就会出现在这里。</p>';
    return;
  }
  /* 分组时**下标要留着**：动作按钮认的是 aoItems 里的位置（data-i），
     分完组重新编号的话，点「删除」删掉的会是另一份东西。 */
  const fresh = [], kept = [];
  aoItems.forEach((it, i) => (it.kept ? kept : fresh).push(aoCard(it, i)));
  const days = aoItems.filter(it => !it.kept).map(aoLeft).filter(d => d !== null);
  const openF = aoSecOpen('fresh', fresh.length), openK = aoSecOpen('kept', fresh.length);
  /* 两段的标题栏是同一个东西，只有名字和条数不同 —— 写两遍迟早只改一边 */
  const sec = (which, label, n, on) => `
    <button class="ao-sec${on ? '' : ' closed'}" data-aosec="${which}" aria-expanded="${on}"
      aria-controls="ao-${which}"><span class="caret" aria-hidden="true">▾</span>${label}<span class="n">${n}</span></button>`;
  box.classList.add('grouped');
  box.innerHTML = `
    <div class="ao-sum">${fresh.length
      ? `<b>${fresh.length} 份</b>待处理`
        + (days.length ? ` · 最早一份 <b>${Math.min(...days)} 天</b>后清掉` : '')
        + ` · 已归档 ${kept.length} 份`
      : `待处理都清完了 · 已归档 <b>${kept.length} 份</b>`}</div>
    ${sec('fresh', '待处理', fresh.length, openF)}
    <div class="ao-grp" id="ao-fresh"${openF ? '' : ' hidden'}>${fresh.join('')
      || '<p class="ais-empty">都处理完了。<br>新的产出会自己出现在这里。</p>'}</div>
    ${sec('kept', '已归档', kept.length, openK)}
    <div class="ao-grp" id="ao-kept"${openK ? '' : ' hidden'}>${kept.join('')
      || '<p class="ais-empty">还没归档过东西。<br>点某份产出的「归档」，它就不会被 '
         + aoRetain + ' 天清理带走。</p>'}</div>`;
}

/* 正文字号。产出里现在会出现整本书转来的长文档（云盘「转成 Markdown」），
   一屏几十行的东西没法用固定字号读 —— 和阅读模式一样给 A− / A+，
   范围也取同一档（13~28px）。标题在 CSS 里全是 em，调正文它们跟着缩放。 */
let aoFont = +lsGet('ao:font') || 16;

function aoApplyFont() {
  const b = $('#ao-rb');
  if (b) b.style.fontSize = aoFont + 'px';
  lsSet('ao:font', aoFont);
}

async function aoView(it) {
  libTouch('aiout', it.id);
  const box = $('#ao-list');
  box.classList.remove('grouped');
  try {
    const d = await api('/api/aiout/' + it.id);
    box.innerHTML = `<div class="ao-read">
      <button class="ais-back" id="ao-back">‹ 回到产出列表</button>
      <div class="ao-rhead">
        <h2 class="ao-rt">${esc(d.title)}</h2>
        <span class="reader-tools">
          <button id="ao-fmin" title="字小一点">A−</button>
          <button id="ao-fplus" title="字大一点">A+</button>
        </span>
      </div>
      <div class="ao-rb" id="ao-rb">${mdToHtml(d.body || '')}</div>
    </div>`;
    aoApplyFont();
    $('#ao-fmin').onclick = () => { aoFont = Math.max(13, aoFont - 1); aoApplyFont(); };
    $('#ao-fplus').onclick = () => { aoFont = Math.min(28, aoFont + 1); aoApplyFont(); };
  } catch (e) { toast(errMsg(e), true); }
}

/* 投放：一个动作一个目的地。**默认不含聊天** —— 往聊天里发东西是给别人看的，
   那条路走 AI 助手里的确认流程，不做成这里一个随手可点的按钮。 */
const AO_DESTS = [['material', '资料库'], ['drive', '云盘'], ['note', '小记']];

async function aoSend(it) {
  const names = AO_DESTS.map(d => d[1]).join(' / ');
  const pick = await appPrompt('投到哪里？（' + names + '）', '填一个：' + names, '资料库');
  if (!pick) return;
  const hit = AO_DESTS.find(d => d[1] === pick.trim());
  if (!hit) { toast('只能投到：' + names, true); return; }
  try {
    const d = await api('/api/aiout/' + it.id + '/send', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dest: hit[0] })
    });
    toast('已投到' + d.where + '，并顺手归档');
    loadAiOut();
  } catch (e) { toast(errMsg(e), true); }
}

/* 分享：两条路，先问清是哪一条 —— 它们的后果差得远。
   「发到聊天」是发一条消息过去，对方在聊天里收到一个文件；
   「共享给队友」是把这份产出投进**我自己的**资料库，再让队友在他的资料库里长期看到。
   这一页 30 天就清，所以后一条必须先落成资料 —— 不能让人共享一个随时会消失的东西。 */
function aoPickShare(it) {
  return new Promise(res => {
    const el = $('#mat-share-sheet');
    // 和云盘/资料库同一个底部弹层：必须裹 .ns-mask + .ns-panel，少一个就是块透明浮层
    el.innerHTML = `<div class="ns-mask" data-sheet-close></div><div class="ns-panel">
      <div class="ns-handle"></div><div class="ns-title">分享《${esc(it.title)}》</div>
      <div class="ms-list">
        <button class="ms-frow" data-aoshare="chat">${artEm('💬')} 发到聊天
          <span class="ms-sub">好友 / 小组，对方收到一个文件</span></button>
        <button class="ms-frow" data-aoshare="team">${artEm('👥')} 共享给队友
          <span class="ms-sub">先投进我的资料库，队友在自己那边长期看得到</span></button>
      </div>
      <div class="ms-acts"><button class="btn" id="aosh-cancel">取消</button></div></div>`;
    el.classList.remove('hidden');
    const done = v => { el.classList.add('hidden'); res(v); };
    el.querySelector('.ns-mask').onclick = () => done(null);
    $('#aosh-cancel').onclick = () => done(null);
    el.querySelectorAll('[data-aoshare]').forEach(b => { b.onclick = () => done(b.dataset.aoshare); });
  });
}

async function aoShare(it) {
  const how = await aoPickShare(it);
  if (!how) return;
  try {
    if (how === 'chat') {
      // 选人的面板和云盘、资料库共用一个：发的本来就是同一件事
      const pick = await pickChatTargets('发送到');
      if (!pick) return;
      const r = await api('/api/aiout/' + it.id + '/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pick)
      });
      toast('已发送给 ' + [r.users ? r.users + ' 位好友' : '',
        r.groups ? r.groups + ' 个小组' : ''].filter(Boolean).join('、') + '，并顺手归档');
    } else {
      const d = await api('/api/aiout/' + it.id + '/team');
      if (!d.members.length) { toast('你还没有队友（去「任务清单 → 互监待办」组队）', true); return; }
      /* 借资料库那个勾选面板，但话得换一套：那边是「整份覆盖、取消勾选就收回」，
         这边每点一次都是新投一份副本进资料库，收不回来 —— 说错了就是骗人。 */
      const pick = await matPickMembers(d.members,
        '勾上的队友会在自己的资料库里得到这份产出的副本（能看能下载，不能改不能删）。'
        + '这份产出也会同时投进你自己的资料库。');
      if (pick === null) return;
      if (!pick.length) { toast('一个队友都没选', true); return; }
      const r = await api('/api/aiout/' + it.id + '/team', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to: pick })
      });
      toast('已投进资料库，并共享给 ' + r.n + ' 位队友');
    }
    loadAiOut();
  } catch (e) { toast(errMsg(e), true); }
}

$('#view-aiout').addEventListener('click', async e => {
  if (e.target.closest('#ao-back')) { aoPaint(); return; }
  const sec = e.target.closest('[data-aosec]');
  if (sec) {     // 开合记下来，下次进这一页还是你拨的那样
    lsSet('ao:open:' + sec.dataset.aosec, sec.classList.contains('closed') ? '1' : '0');
    aoPaint();
    return;
  }
  const b = e.target.closest('[data-aoact]'); if (!b) return;
  const it = aoItems[+b.dataset.i]; if (!it) return;
  const act = b.dataset.aoact;
  if (act === 'view') { aoView(it); return; }
  if (act === 'send') { aoSend(it); return; }
  if (act === 'share') { aoShare(it); return; }
  if (act === 'dl') { location.href = '/api/aiout/' + it.id + '/download'; return; }
  try {
    if (act === 'keep') {
      await api('/api/aiout/' + it.id, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kept: !it.kept })
      });
      toast(it.kept ? '已取消归档，' + aoRetain + ' 天后会自动清掉' : '已归档，不会被自动清理');
    } else if (act === 'rename') {
      const t = await appPrompt('改个名字', '', it.title);
      if (!t || !t.trim()) return;
      await api('/api/aiout/' + it.id, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: t.trim() })
      });
    } else if (act === 'del') {
      if (!(await appConfirm('删掉这份产出？'))) return;
      await api('/api/aiout/' + it.id, { method: 'DELETE' });
    }
    loadAiOut();
  } catch (err) { toast(errMsg(err), true); }
});
