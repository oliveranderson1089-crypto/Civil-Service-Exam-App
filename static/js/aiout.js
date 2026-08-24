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
   mdToHtml, push, toast, uiError */

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

function aoPaint() {
  const box = $('#ao-list');
  $('#ao-intro').textContent =
    'AI 生成的汇总、文档、题目先存在这里 · 没归档的 ' + aoRetain + ' 天后自动清掉';
  if (!aoItems.length) {
    box.innerHTML = '<p class="ais-empty">还没有产出。<br>在 AI 助手里点「汇总」，'
      + '或让它「写一份…存成文件」，东西就会出现在这里。</p>';
    return;
  }
  box.innerHTML = aoItems.map((it, i) => `
    <div class="ao-card" data-ao="${it.id}">
      <div class="ao-h">
        <span class="ao-k">${AO_KIND[it.kind] || '📄'}</span>
        <span class="ao-t">${esc(it.title)}</span>
        ${it.kept ? '<span class="ao-keep">已归档</span>' : ''}
      </div>
      <div class="ao-m">${it.size} 字 · ${esc((it.created_at || '').slice(5, 16))}${
        it.sent ? ' · 已投到 ' + esc(it.sent) : ''}</div>
      <div class="ao-acts">
        <button data-aoact="view" data-i="${i}">看全文</button>
        <button data-aoact="send" data-i="${i}">${artEm('📤')} 投放</button>
        <button data-aoact="dl" data-i="${i}">下载</button>
        <button data-aoact="keep" data-i="${i}">${it.kept ? '取消归档' : '归档'}</button>
        <button data-aoact="rename" data-i="${i}">改名</button>
        <button data-aoact="del" data-i="${i}" class="ao-danger">删除</button>
      </div>
    </div>`).join('');
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

$('#view-aiout').addEventListener('click', async e => {
  if (e.target.closest('#ao-back')) { aoPaint(); return; }
  const b = e.target.closest('[data-aoact]'); if (!b) return;
  const it = aoItems[+b.dataset.i]; if (!it) return;
  const act = b.dataset.aoact;
  if (act === 'view') { aoView(it); return; }
  if (act === 'send') { aoSend(it); return; }
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
