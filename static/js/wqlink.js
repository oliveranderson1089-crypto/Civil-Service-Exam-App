/* 刷题界面 ↔ 错题本 的双向联动。
 *
 * 全站四个刷题入口（专项练 / 历年真题 / 每日巩固测试 / 题库模拟卷）共用这一份：
 * 每道题旁边一个「错题本」按钮，亮着 = 这题已经在本子里。点开就能改题干、答案、
 * 笔记、板块题型，也能直接移出 —— 不用先跑去错题本翻一遍找到它。
 *
 * 认「同一道题」靠 (kind, key)，服务端定：真题用真题 id，其余用题干指纹。
 * **指纹一律由服务端算**（/api/wrongq/lookup 会把算好的 key 回给前端），
 * 前端自己算的话两边差一个标点就对不上，表现是收过的题显示成没收过、
 * 再点一次又收出第二条。
 */
/* global $, WQ_BOARDS, api, appConfirm, esc, toast */

/* 板块清单用错题本那一份（js/wrongq.js 的 WQ_BOARDS）——这儿再抄一遍的话，
   加一个板块就得改两处，漏改的表现是：同一条错题，从刷题端打开选不到那个板块、
   从错题本进去却能选。wrongq.js 在本文件之后加载，但只在 wqlOpen 里用到，
   那时早就定义好了。 */

/* 当前这一组题的错题状态：key → {id, starred, note}；没收录的键不存在。
   按 kind 分开存，两个模块同时开着也不会串。 */
const wqlState = {};

function _wqlBox(kind) { return (wqlState[kind] = wqlState[kind] || {}); }

/** 这道题在错题本里吗（渲染按钮时问）。 */
function wqlHas(kind, key) { return !!_wqlBox(kind)[key]; }

/** 按钮 HTML。放在题目/解析区，`data-wql` 带上 key，点击由各模块转交 wqlOpen。 */
function wqlBtnHtml(kind, key, label) {
  const on = wqlHas(kind, key);
  return `<button class="wql-btn${on ? ' on' : ''}" data-wql="${esc(String(key))}"
    data-wqlkind="${esc(kind)}" title="${wqlBtnTitle(on)}">
    ${wqlBtnText(on)}${label ? ' ' + esc(label) : ''}</button>`;
}
function wqlBtnText(on) { return on ? '📕 已收' : '📓 收错题'; }
function wqlBtnTitle(on) { return on ? '已在错题本，点开可改可删' : '收进错题本'; }

/** 收了/删了之后刷新按钮外观。root 传作用范围（选择器或元素），不传就是全页。

    四个刷题模块都要这一下，所以只此一份：原先各写各的，已经不一致了——
    有的更新 title、有的不更新，同一个按钮在不同页面悬停提示不一样。
    只刷按钮**不整页重画**：结果页重画会走进已上锁的交卷流程，一整屏成绩会停在旧状态。 */
function wqlRefreshBtns(root) {
  const box = !root ? document : (typeof root === 'string' ? $(root) : root);
  if (!box) return;
  box.querySelectorAll('[data-wql]').forEach(b => {
    const on = wqlHas(b.dataset.wqlkind, b.dataset.wql);
    b.classList.toggle('on', on);
    b.textContent = wqlBtnText(on);
    b.title = wqlBtnTitle(on);
  });
}

/** 服务端刚自动收了一道错题（做错时那条链路），把状态记到本地。
    这样不用为了刷新一个按钮再打一次 lookup、再整屏重画。 */
function wqlMark(kind, key, info) {
  if (!key) return;
  _wqlBox(kind)[key] = Object.assign({ id: 0, starred: false, note: '' }, info || {});
}

/** 刷新一批题的收录状态。keys 传真题 id；没有 id 的模块传 questions（题干原文）。
    返回服务端算好的 key 数组，和入参同序 —— 各模块拿它去渲染按钮。 */
async function wqlScan(kind, { keys, questions }) {
  try {
    const d = await api('/api/wrongq/lookup', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, keys, questions }),
    });
    wqlState[kind] = d.items || {};
    return d.keys || keys || [];
  } catch (_) {
    // 查不到就当都没收录：按钮还能点，点了会真的收。比整屏报错强。
    wqlState[kind] = {};
    return keys || [];
  }
}

/** 收进错题本（已经在里面就只补空字段，不会重复收）。payload 见 /api/wrongq/sync。 */
async function wqlAdd(kind, key, payload) {
  const d = await api('/api/wrongq/sync', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.assign({ kind, key }, payload)),
  });
  _wqlBox(kind)[d.item.src_key] = { id: d.id, starred: d.item.starred, note: d.item.note };
  return d;
}

/** 从错题本移出这道题。 */
async function wqlRemove(kind, key) {
  await api(`/api/wrongq/src/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`,
    { method: 'DELETE' });
  delete _wqlBox(kind)[key];
}

/* ---------------- 就地编辑面板（底部弹层） ---------------- */
/* 用自建弹层而不是 appPrompt：错题要改的是**一组**字段（题干/答案/笔记/板块/题型），
   一行输入框的对话框套不下。原生 prompt 更不行（见「禁用原生弹窗」的约定）。 */
let _wqlSheet = null, _wqlCtx = null;

function _wqlEnsure() {
  if (_wqlSheet) return _wqlSheet;
  _wqlSheet = document.createElement('div');
  _wqlSheet.id = 'wql-sheet';
  _wqlSheet.className = 'wql-sheet hidden';
  document.body.appendChild(_wqlSheet);
  _wqlSheet.addEventListener('click', async e => {
    if (e.target === _wqlSheet || e.target.closest('[data-wqlact="close"]')) return wqlClose();
    const act = e.target.closest('[data-wqlact]');
    if (!act) return;
    const a = act.dataset.wqlact;
    if (a === 'star') {
      act.classList.toggle('on');
      act.textContent = act.classList.contains('on') ? '★ 已收藏' : '☆ 收藏';
      return;
    }
    if (a === 'save') return _wqlSave();
    if (a === 'del') {
      if (!(await appConfirm('把这道题从错题本删除？笔记也会一起没。'))) return;
      try {
        await wqlRemove(_wqlCtx.kind, _wqlCtx.key);
        toast('已移出错题本');
        const cb = _wqlCtx.onChange; wqlClose(); if (cb) cb();
      } catch (err) { toast(err.message, true); }
    }
  });
  return _wqlSheet;
}

async function _wqlSave() {
  const c = _wqlCtx; if (!c) return;
  const body = {
    question: $('#wql-q').value.trim(),
    answer: $('#wql-a').value.trim(),
    note: $('#wql-note').value,
    board: $('#wql-board').value,
    qtype: $('#wql-type').value.trim(),
    starred: $('#wql-star').classList.contains('on'),
  };
  if (!body.question) { toast('题目不能为空', true); return; }
  try {
    let id = (_wqlBox(c.kind)[c.key] || {}).id;
    if (!id) {                       // 还没收录：先收进去，再把这次改的内容写上
      const d = await wqlAdd(c.kind, c.key, body);
      id = d.id;
    }
    // 用 PUT 覆盖式更新：sync 只补空字段（第二遍做错时不能洗掉人工写的笔记），
    // 而这里是**用户明确在改**，改什么就该存什么。
    await api('/api/wrongq/' + id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const box = _wqlBox(c.kind);
    box[c.key] = { id, starred: body.starred, note: body.note };
    toast('已保存到错题本');
    const cb = c.onChange; wqlClose(); if (cb) cb();
  } catch (e) { toast(e.message, true); }
}

function wqlClose() {
  if (_wqlSheet) _wqlSheet.classList.add('hidden');
  _wqlCtx = null;
}

/** 打开面板。payload 是这道题的现成内容（题干/答案/板块/题型），
    已收录的话以**错题本里的版本**为准 —— 那是用户改过的。 */
async function wqlOpen(kind, key, payload, onChange) {
  const sheet = _wqlEnsure();
  _wqlCtx = { kind, key, onChange };
  const cur = _wqlBox(kind)[key];
  let w = Object.assign({ question: '', answer: '', board: '', qtype: '', note: '', starred: false },
    payload || {});
  if (cur) {
    try { w = Object.assign(w, await api('/api/wrongq/' + cur.id)); } catch (_) { /* 用现成的 */ }
  }
  sheet.innerHTML = `<div class="wql-panel">
    <div class="wql-head">
      <b>${cur ? '错题本 · 这道题' : '收进错题本'}</b>
      ${w.src_name ? `<span class="wql-src">来自${esc(w.src_name)}</span>` : ''}
      <button class="wql-x" data-wqlact="close">✕</button>
    </div>
    <label class="wql-l">题目</label>
    <textarea id="wql-q" class="wql-ta" rows="5">${esc(w.question || '')}</textarea>
    <label class="wql-l">答案 / 解析</label>
    <textarea id="wql-a" class="wql-ta" rows="3">${esc(w.answer || '')}</textarea>
    <label class="wql-l">我的笔记（错因、易错点）</label>
    <textarea id="wql-note" class="wql-ta" rows="3" placeholder="为什么错？下次注意什么？">${esc(w.note || '')}</textarea>
    <div class="wql-row">
      <select id="wql-board" class="wql-in">
        <option value="">（未分类）</option>
        ${WQ_BOARDS.map(b => `<option${b === w.board ? ' selected' : ''}>${b}</option>`).join('')}
      </select>
      <input id="wql-type" class="wql-in" placeholder="题型" value="${esc(w.qtype || '')}">
      <button class="wql-star${w.starred ? ' on' : ''}" id="wql-star" data-wqlact="star">
        ${w.starred ? '★ 已收藏' : '☆ 收藏'}</button>
    </div>
    <div class="wql-acts">
      ${cur ? '<button class="btn ghost wql-del" data-wqlact="del">移出错题本</button>' : ''}
      <button class="btn" data-wqlact="save">${cur ? '保存修改' : '收进错题本'}</button>
    </div>
  </div>`;
  sheet.classList.remove('hidden');
}

window.wqlScan = wqlScan;
window.wqlHas = wqlHas;
window.wqlBtnHtml = wqlBtnHtml;
window.wqlRefreshBtns = wqlRefreshBtns;
window.wqlMark = wqlMark;
window.wqlOpen = wqlOpen;
window.wqlAdd = wqlAdd;
window.wqlRemove = wqlRemove;
window.wqlClose = wqlClose;
