/* 书签：看到哪了
 *
 * 由 app.js 按它自己的区段边界切出（原 L10610-10705）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, DOC, IS_MOBILE, TITLES, api, artEm, ckBoard, csBoard, esc, matBoard, nwCur, stack */

/* ================= 书签：看到哪了 =================
   长文（经典著作 / 要文库 / 范文 / 知识库文档）看到一半退出来，回头根本找不到位置。
   这里在阅读类页面自动记住滚动位置，回来时顶部给一条「上次看到这里 · 点我跳回」。 */
/* 书签：任何会滚动的页面都记「看到哪了」——长文如此，长列表（如 894 条成语）更需要。
   ref 用「视图 + 这一页的子标识」拼出来（板块名 / 文章 id / 分类…），换个板块就是另一条书签。 */
const BM_SKIP = new Set(['home', 'account', 'search', 'slgrade', 'quizrun', 'dtest', 'notify']);
let bmCur = null, bmT = null, bmHideT = null;
// 这条提示只有「要不要跳回去」一个用处，问完就该走：3 秒不点就自己消失（两端一致）
const BM_AUTOHIDE = 3000;
function bmHide() { clearTimeout(bmHideT); bmHideT = null; $('#bm-tip').classList.add('hidden'); }

function bmRef() {
  const st = stack[stack.length - 1];
  if (!st || BM_SKIP.has(st.view)) return null;
  // 顶层 let 不会挂到 window 上，直接引用（都在同一个脚本作用域里）
  // 顶层 let 不会挂到 window 上，直接引用（同一脚本作用域）；标题足够区分的就用标题
  const sub = {
    doc: () => DOC && DOC.id,
    newsd: () => nwCur && nwCur.id,
    ckboard: () => ckBoard,
    csboard: () => csBoard,
    materials: () => matBoard || '全部',
  }[st.view];
  let id = '';
  try { id = sub ? (sub() || '') : (st.title || ''); } catch (_) { id = st.title || ''; }
  return { kind: st.view, ref: String(id || st.view), title: st.title || TITLES[st.view] || '' };
}
function bmScrollTop() { return (document.scrollingElement || document.documentElement).scrollTop; }
function bmSave() {                      // 滚动停下来 1.5s 就记一次（不打扰、不刷接口）
  const r = bmRef();
  if (!r) return;
  const el = document.scrollingElement || document.documentElement;
  const pos = el.scrollHeight > el.clientHeight ? bmScrollTop() / (el.scrollHeight - el.clientHeight) : 0;
  // 按「滚了多少像素」判断，不能按百分比：894 条成语那页有 15 万像素高，
  // 滚了 3000px 也才 2%，用百分比阈值会直接把书签丢掉。
  if (bmScrollTop() < 260) return;
  api('/api/bookmarks', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: r.kind, ref: r.ref, title: r.title, pos }),
  }).catch(() => {});
}
addEventListener('scroll', () => {
  if (!bmRef()) return;
  clearTimeout(bmT);
  bmT = setTimeout(bmSave, 1500);
}, { passive: true });

async function bmRestore() {             // 进阅读页时问一句：上次看到哪了
  bmHide();                              // 换页先收起来：上一页的提示不能跟着跑到这一页
  const r = bmRef();
  if (!r) return;
  try {
    const d = await api('/api/bookmarks');
    const b = (d.items || []).find(x => x.kind === r.kind && x.ref === r.ref);
    const el = document.scrollingElement || document.documentElement;
    const px = b ? b.pos * (el.scrollHeight - el.clientHeight) : 0;
    if (!b || px < 260) return;
    /* 和划重点结果条抢位置时让它：重点条是用户自己点出来的、还要用，这条 3 秒就走。
       但只在真会挡住的时候让 —— 手机端两者都钉在屏幕下方，必撞；电脑端这条在下方、
       结果条默认在顶部，只有被拖到下面那一带才撞，凭「结果条在」就吞掉提示没道理。 */
    const mkBar = $('#mk-bar');
    if (!mkBar.classList.contains('hidden')
        && (IS_MOBILE || mkBar.getBoundingClientRect().bottom > innerHeight - 120)) return;
    bmCur = b;
    $('#bm-tip').innerHTML = `🔖 上次看到 <b>${Math.round(b.pos * 100)}%</b> 处 · <i>${(b.updated_at || '').slice(5, 16)}</i>
      <button class="btn tiny" id="bm-go">跳回去</button>
      <button class="bm-x" id="bm-hide">${artEm('✕')}</button>`;
    $('#bm-tip').classList.remove('hidden');
    bmHideT = setTimeout(bmHide, BM_AUTOHIDE);
  } catch (_) { /* 取不到书签就不显示「跳回去」，不影响正常阅读 */ }
}
document.addEventListener('click', e => {
  if (e.target.closest('#bm-go')) {
    const el = document.scrollingElement || document.documentElement;
    el.scrollTo({ top: bmCur.pos * (el.scrollHeight - el.clientHeight), behavior: 'smooth' });
    bmHide();
  } else if (e.target.closest('#bm-hide')) bmHide();
});
window.__bmView = () => setTimeout(bmRestore, 700);   // 内容渲染完再问

/* 选队友共享：复用底部弹层，勾选=共享，取消勾选=收回 */
function matPickMembers(members) {
  return new Promise(res => {
    const el = $('#mat-share-sheet');
    // ★ 必须裹 .ns-mask（深色遮罩）+ .ns-panel（白底面板）—— 少了它们，内容就直接浮在
    //   一张 position:fixed;inset:0 的**透明**层上，电脑端看着就是「完全透明的窗口」。
    el.innerHTML = `<div class="ns-mask" data-sheet-close></div>
      <div class="ns-panel">
        <div class="ns-handle"></div>
        <div class="ns-title">${artEm('👥')} 共享给队友</div>
        <p class="acct-hint" style="padding:0 16px;margin:0 0 6px">勾上就共享给他（他能在资料库看到并下载，但不能改不能删）；取消勾选就收回。</p>
        <div class="ms-list">${members.map(m => `
          <label class="ms-row"><input type="checkbox" value="${m.id}" ${m.shared ? 'checked' : ''}>
            <span>${esc(m.username)}</span></label>`).join('')}</div>
        <div class="ms-acts">
          <button class="btn" id="ms-cancel">取消</button>
          <button class="btn primary" id="ms-ok">确定</button>
        </div>
      </div>`;
    el.classList.remove('hidden');
    const done = (v) => { el.classList.add('hidden'); res(v); };
    $('#ms-ok').onclick = () => done([...el.querySelectorAll('input:checked')].map(i => +i.value));
    $('#ms-cancel').onclick = () => done(null);
    el.querySelector('.ns-mask').onclick = () => done(null);
  });
}
