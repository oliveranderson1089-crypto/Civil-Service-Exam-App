/* 草稿本（错题本里打草稿；多本 / 云端 / 多端同步）
 *
 * 由 app.js 按它自己的区段边界切出（原 L10116-10190）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, appConfirm, appPrompt, c, draft,
   esc, padCur, padDraftId, padInit, padInited, padMode,
   padOnView, padOpen, padRebuild, padSave, padSetData, padStatus,
   push, toast */

/* ---------- 草稿本：错题本里，平时打草稿用（多本 / 云端保存 / 手机电脑同步） ---------- */
function openDrafts() { push({ view: 'drafts' }); loadDrafts(); }
async function loadDrafts() {
  try {
    const d = await api('/api/drafts');
    $('#dr-empty').textContent = '还没有草稿本，点右下角 ＋ 新建一本';
    $('#dr-empty').classList.toggle('hidden', !!d.items.length);
    $('#dr-list').innerHTML = d.items.map(it => `
      <div class="dr-card" data-dr="${it.id}">
        <div class="dr-thumb"${it.thumb ? ` style="background-image:url(${it.thumb})"` : ''}></div>
        <div class="dr-body">
          <div class="dr-t">${esc(it.title || '未命名')}</div>
          <div class="dr-foot">
            <span class="dr-m">${it.pages || 1} 页 · ${(it.updated_at || '').slice(5, 16)}</span>
            <button class="dr-del" data-del="${it.id}" title="删除">✕</button>
          </div>
        </div>
      </div>`).join('');
  } catch (e) { toast(e.message, true); }
}
$('#dr-list').addEventListener('click', async e => {
  const del = e.target.closest('.dr-del');
  if (del) {
    e.stopPropagation();
    if (!await appConfirm('删除这本草稿？删了就找不回来了。', { title: '草稿本', okText: '删除' })) return;
    try { await api('/api/drafts/' + del.dataset.del, { method: 'DELETE' }); toast('已删除'); loadDrafts(); }
    catch (err) { toast(err.message, true); }
    return;
  }
  const c = e.target.closest('.dr-card');
  if (c) openDraft(+c.dataset.dr);
});
$('#dr-fab').onclick = async () => {
  const t = await appPrompt('新建草稿本', '起个名字（留空就用日期）', '');
  if (t === null) return;
  try {
    const d = await api('/api/drafts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: t }),
    });
    openDraft(d.id);
  } catch (e) { toast(e.message, true); }
};
async function openDraft(id) {
  try {
    const d = await api('/api/drafts/' + id);
    if (!padInited) padInit();
    if (padMode !== 'draft') padSave();                            // 先把随手草稿纸存好，等下还要还原
    padMode = 'draft'; padDraftId = id; padCur = null;
    padSetData(d.data);
    $('#pad-title').textContent = d.title || '未命名';
    $('#pad-doc').classList.remove('hidden');
    padStatus('已保存');
    padOpen();
  } catch (e) { toast(e.message, true); }
}
$('#pad-name').onclick = async () => {
  if (padMode !== 'draft') return;
  const t = await appPrompt('草稿本改名', '名字', $('#pad-title').textContent);
  if (t === null) return;
  try {
    await api('/api/drafts/' + padDraftId, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: t }),
    });
    $('#pad-title').textContent = t.trim() || '未命名草稿';
    toast('已改名');
  } catch (e) { toast(e.message, true); }
};
$('#wq-drafts').onclick = openDrafts;
/* 对外钩子放在最后才挂：顶层 function 声明会自动成为 window 属性，
   若直接用同名守卫(window.padRebuild)，脚本刚开始就会被误判为"已就绪"而提前调用。 */
window.__padView = padOnView;
window.__padTheme = () => { if (padInited && !$('#pad').classList.contains('hidden')) padRebuild(); };
