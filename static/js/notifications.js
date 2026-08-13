/* 消息中心
 *
 * 由 app.js 按它自己的区段边界切出（原 L8550-8642）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, appConfirm, errMsg, esc, ME, openChangkao, openChangshi, openChat,
   openChatroom, openCkBoard, openClassics, openCsBoard, openDrafts, openEssays, openFind,
   openGaikuo, openGongwen, openIdiom, openNews, openPartyDict, openPolicyDocs, openQuiz,
   openReview, openShenlun, openSucai, openTasks, openThBoard, openTheory, openWorks,
   openWrongq, push, tkSwitch, toast, uiError */

/* ================= 消息中心：有新内容就提醒，点开直达对应位置 ================= */
const NTF_ICON = {
  changshi: '💡', newlaw: '⚖️', news: '📰', xiyu: '✒️', sucai: '📎',
  gaikuo: '📝', review: '⏰', tasks: '📋', quiz: '🧩', plan: '📅', essay: '📄',
};
/* link 形如 "changshi" 或 "changshi:法律常识" */
let _ntfTries = 0;
function ntfGo(link) {
  // 原生通知点进来时 SPA 可能还没启动完，等它把 ME 拉到再跳
  if (!ME && _ntfTries < 20) { _ntfTries++; setTimeout(() => ntfGo(link), 400); return; }
  _ntfTries = 0;
  const [k, arg] = (link || '').split(':');
  const go = {
    changshi: () => { openChangshi(); if (arg) setTimeout(() => openCsBoard(arg), 260); },
    news: () => openNews(),
    xiyu: () => { openNews(); setTimeout(() => { const b = document.querySelector('#news-boards [data-nb="习语"]'); if (b) b.click(); }, 260); },
    sucai: () => openSucai('全部'),
    gaikuo: () => openGaikuo(),
    review: () => openReview(),
    tasks: () => openTasks(),
    quiz: () => openQuiz(),
    essays: () => openEssays(),
    essay: () => openEssays(),
    gongwen: () => openGongwen(),
    // 备考规划/路线图里的 link 也走这里（以前这些点了没反应）
    wrongq: () => openWrongq(),
    drafts: () => openDrafts(),
    idiom: () => openIdiom(),
    changkao: () => { openChangkao(); if (arg) setTimeout(() => openCkBoard(arg), 260); },
    shenlun: () => openShenlun(),
    find: () => openFind(),
    classics: () => openClassics(),
    theory: () => { openTheory(); if (arg) setTimeout(() => openThBoard(arg), 260); },
    works: () => openWorks(),
    partydict: () => openPartyDict(),
    policydoc: () => openPolicyDocs(),
    dtest: () => { openTasks(); setTimeout(() => tkSwitch('daily'), 60); },   // 巩固测试在「每日任务」里
    plan: () => { openTasks(); setTimeout(() => tkSwitch('plan'), 60); },
    chatroom: () => { if (arg) openChatroom(+arg, ''); else openChat(); },     // 聊天通知点进来直达会话
  }[k];
  if (go) go(); else toast('这条消息没有可跳转的位置');
}
function openNotify() { push({ view: 'notify', title: '消息' }); loadNotify(); }
$('#notify-btn').onclick = openNotify;

async function loadNotify() {
  $('#ntf-list').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/notifications');
    setNtfDot(d.unread);
    $('#ntf-list').innerHTML = d.items.length ? d.items.map(it => `
      <div class="ntf ${it.read ? '' : 'unread'}" data-ntf="${it.id}" data-link="${esc(it.link || '')}">
        <span class="ntf-ico">${NTF_ICON[it.kind] || '🔔'}</span>
        <div class="ntf-main">
          <div class="ntf-t">${esc(it.title)}</div>
          ${it.body ? `<div class="ntf-b">${esc(it.body)}</div>` : ''}
          <div class="ntf-m">${esc(it.created_at.slice(5, 16))}</div>
        </div>
        ${it.read ? '' : '<span class="ntf-new"></span>'}
      </div>`).join('') : '<p class="empty">暂时没有新消息。内容库每天早上更新后会出现在这里。</p>';
  } catch (e) { $('#ntf-list').innerHTML = uiError(e); }
}
$('#ntf-list').addEventListener('click', async e => {
  const n = e.target.closest('[data-ntf]'); if (!n) return;
  if (n.classList.contains('unread')) {
    n.classList.remove('unread');
    const nb = n.querySelector('.ntf-new'); if (nb) nb.remove();   // 老 WebView 不支持 ?.
    api('/api/notifications/' + n.dataset.ntf + '/read', { method: 'POST' })
      .then(refreshNtfDot).catch(() => {});
  }
  ntfGo(n.dataset.link);
});
$('#ntf-readall').onclick = async () => {
  try { await api('/api/notifications/read_all', { method: 'POST' }); loadNotify(); }
  catch (e) { toast(errMsg(e), true); }
};
$('#ntf-clear').onclick = async () => {
  if (!(await appConfirm('清理所有已读消息？'))) return;
  try { await api('/api/notifications', { method: 'DELETE' }); loadNotify(); }
  catch (e) { toast(errMsg(e), true); }
};

function setNtfDot(n) {
  const dot = $('#notify-dot');
  dot.textContent = n > 99 ? '99+' : (n || '');
  dot.classList.toggle('hidden', !n);
}
async function refreshNtfDot() {
  try { setNtfDot((await api('/api/notifications/unread')).unread); }
  catch (e) { console.debug('[消息] 红点刷新失败：%s', (e && e.message) || e); }        // 下次轮询会补
}
/* 启动时生成一次当天的消息并点亮角标；之后每次回首页只数未读 */
setTimeout(() => { api('/api/notifications').then(d => setNtfDot(d.unread)).catch(() => {}); }, 1200);
