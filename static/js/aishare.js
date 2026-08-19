/* 别人分享给我的 AI 对话：只读地看，然后「接着问」。
 *
 * 「接着问」是把这份**快照**复制成我自己的一条会话 —— 从这里开始两边各走各的，
 * 我往下问什么不会回流给分享的人，他后面又聊了什么我也看不到。
 *
 * 有一件事值得说清楚（免得被当成省钱功能）：省下的是「对方重新摸索一遍」的功夫，
 * 不是上下文费用 —— 接着问的时候，这段历史照样每轮进上下文。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 */
/* global $, aiOpenChat, api, back, esc, errMsg, mdToHtml, openAI, push, toast, uiError */

let asCur = null;

async function openAiShare(sid) {
  if (!sid) { toast('这张卡片没带上分享编号', true); return; }
  push({ view: 'aishare' });
  const box = $('#as-wrap');
  box.innerHTML = '<p class="ais-empty">加载中…</p>';
  try {
    asCur = await api('/api/aishare/' + sid);
  } catch (e) { box.innerHTML = uiError(e); return; }
  box.innerHTML = `
    <div class="as-head">
      <div class="as-t">${esc(asCur.title || 'AI 对话')}</div>
      <div class="as-m">${asCur.mine ? '你分享出去的' : '来自 ' + esc(asCur.from || '好友')}
        · ${asCur.msgs.length} 条 · ${esc((asCur.created_at || '').slice(0, 16))}</div>
    </div>
    <div class="as-msgs">${asCur.msgs.map(m => m.role === 'user'
      ? `<div class="as-u"><div class="as-bub">${esc(m.content)}</div></div>`
      : `<div class="as-a">${mdToHtml(m.content || '')}</div>`).join('')}</div>
    <div class="as-foot">
      <button class="btn primary" id="as-adopt">接着问下去</button>
      <p class="acct-hint">会在你自己的助手里复制成一条新对话。此后你问什么，
        分享给你的人看不到。</p>
    </div>`;
  $('#as-adopt').onclick = () => asAdopt(sid);
}

async function asAdopt(sid) {
  const btn = $('#as-adopt');
  btn.disabled = true;
  try {
    const d = await api('/api/aishare/' + sid + '/adopt', { method: 'POST' });
    back();                       // 先退出只读页，别让 AI 面板盖在它上面
    await openAI();
    await aiOpenChat(d.id);
    toast('已复制成你自己的对话，接着问吧');
  } catch (e) { toast(errMsg(e), true); btn.disabled = false; }
}
