/* 应用文改错（错例小测）
 *
 * 题型是判断题，不是四选一：库里只有 4 类检查项，四选一做几道就把选项背下来了，
 * 变成考「记住了几类」而不是考「认不认得出」。判断题每次面对一句具体的话，
 * 要真的看出它哪里不合规范。
 *
 * 一半给错句、一半给改正（后端按位置定，不用随机数）——只给错句的话，
 * 做几道就摸出规律「反正都选错」，等于没考。
 *
 * 零 AI 调用：题目全部来自 yy_items 里的成对错例（错句 + 改正 + 扣分理由），
 * 那批数据是从 71 篇自产范文里用格式检查器捞出来的，判据都有真题实证。
 */
/* global $, api, artEm, errMsg, esc, push, toast */

let yeItems = [], yeIdx = 0, yeAnswered = [], yeDone = 0;

function yeRender() {
  const box = $('#ye-body');
  if (!yeItems.length) {
    box.innerHTML = '<p class="empty">还没有错例。生成几篇应用文之后，格式检查器会自动攒出来。</p>';
    $('#ye-bar').classList.add('hidden');
    return;
  }
  if (yeIdx >= yeItems.length) { yeSummary(); return; }
  const it = yeItems[yeIdx];
  const picked = yeAnswered[yeIdx];
  $('#ye-prog').textContent = `第 ${yeIdx + 1} / ${yeItems.length} 题`;
  $('#ye-score').textContent = yeDone ? `已答 ${yeDone} · 对 ${yeAnswered.filter(x => x && x.ok).length}` : '';
  box.innerHTML = `
    <div class="ye-card">
      <div class="ye-meta">${esc(it.where || '应用文')} · <b>${esc(it.check)}</b></div>
      <div class="ye-q">下面这样写，对不对？</div>
      <div class="ye-text">${esc(it.text)}</div>
      ${picked ? '' : `<div class="ye-btns">
        <button class="btn ye-pick" data-ye="right">${artEm('✓')} 对</button>
        <button class="btn ye-pick" data-ye="wrong">✗ 错</button>
      </div>`}
      ${picked ? `
      <div class="ye-fb ${picked.ok ? 'ok' : 'no'}">
        ${picked.ok ? '✅ 答对了' : '❌ 答错了'}　正确答案：<b>${it.answer === 'right' ? '对' : '错'}</b>
      </div>
      <div class="ye-pair">
        <div class="ye-bad">✗ ${esc(it.bad)}</div>
        <div class="ye-good">${artEm('✓')} ${esc(it.good)}</div>
      </div>
      ${it.why ? `<div class="ye-why">${artEm('💡')} ${esc(it.why)}</div>` : ''}
      <div class="ye-btns">
        <button class="btn primary" id="ye-next">${yeIdx + 1 >= yeItems.length ? '看成绩' : '下一题'}</button>
      </div>` : ''}
    </div>`;
}

function yeSummary() {
  const ok = yeAnswered.filter(x => x && x.ok).length;
  const wrong = yeItems.filter((_, i) => yeAnswered[i] && !yeAnswered[i].ok);
  $('#ye-prog').textContent = '做完了';
  $('#ye-score').textContent = '';
  $('#ye-body').innerHTML = `
    <div class="ye-card">
      <div class="ye-sum">${ok} / ${yeItems.length} 题答对</div>
      ${wrong.length ? `<div class="ye-q">这几条再看一眼：</div>` + wrong.map(it => `
        <div class="ye-pair">
          <div class="ye-meta">${esc(it.where || '')} · ${esc(it.check)}</div>
          <div class="ye-bad">✗ ${esc(it.bad)}</div>
          <div class="ye-good">${artEm('✓')} ${esc(it.good)}</div>
          ${it.why ? `<div class="ye-why">${artEm('💡')} ${esc(it.why)}</div>` : ''}
        </div>`).join('')
        : '<div class="ye-fb ok">' + artEm("✅") + ' 全对，格式这块没问题</div>'}
      <div class="ye-btns"><button class="btn primary" id="ye-again">再来一组</button></div>
    </div>`;
}

async function loadYyErr() {
  $('#ye-body').innerHTML = '<p class="empty">出题中…</p>';
  try {
    const d = await api('/api/gongwen/errquiz?n=10');
    yeItems = d.items || []; yeIdx = 0; yeAnswered = []; yeDone = 0;
    $('#ye-bar').classList.toggle('hidden', !yeItems.length);
    yeRender();
  } catch (e) { toast(errMsg(e), true); $('#ye-body').innerHTML = '<p class="empty">出题失败</p>'; }
}

function openYyErr() {
  push({ view: 'yyerr', title: '应用文改错' });
  loadYyErr();
}

$('#view-yyerr').addEventListener('click', e => {
  const pick = e.target.closest('[data-ye]');
  if (pick) {
    const it = yeItems[yeIdx];
    yeAnswered[yeIdx] = { pick: pick.dataset.ye, ok: pick.dataset.ye === it.answer };
    yeDone += 1;
    yeRender();
    return;
  }
  if (e.target.closest('#ye-next')) { yeIdx += 1; yeRender(); return; }
  if (e.target.closest('#ye-again')) { loadYyErr(); }
});
