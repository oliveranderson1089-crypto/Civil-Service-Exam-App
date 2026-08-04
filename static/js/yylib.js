/* 应用文素材库（按「文种 → 部件」两级下钻）
 *
 * 这个页面最要紧的一点：**文种按真题频次排，并把「考过几次」显示出来**。
 * 原来「文种大全」是按录入顺序排的，练得最多的倡议书在真题里一次没考过。
 * 排序换成频次之后，「该练什么」这件事才有依据。
 *
 * 空格子也要看得见：库里哪个文种、哪一块还没素材，正是这个页面该回答的问题。
 * 所以有素材的和没素材的都列，不做「没有就不显示」——那样看上去永远是齐的。
 */
/* global $, api, esc, push, toast */

let ylCats = [], ylKind = '';

function ylBadge(g) {
  if (g.freq > 0) return `<span class="yl-freq">真题考过 ${g.freq} 次</span>`;
  if (g.freq_all > 0) return `<span class="yl-freq old">2018 后未考 · 更早 ${g.freq_all} 次</span>`;
  return '<span class="yl-freq zero">近五年未考</span>';
}

function ylRenderCats() {
  const box = $('#yl-body');
  const kinds = ylKindCounts;
  $('#yl-kinds').innerHTML = ['', ...Object.keys(kinds)].map(k =>
    `<button class="chip${k === ylKind ? ' active' : ''}" data-ylk="${esc(k)}">${
      k ? esc(k) + ' ' + kinds[k] : '全部 ' + Object.values(kinds).reduce((a, b) => a + b, 0)
    }</button>`).join('');
  box.innerHTML = ylCats.map(g => {
    const cells = g.parts.map(p => `
      <button class="yl-cell${p.n ? '' : ' empty'}${p.req ? ' req' : ''}${p.extra ? ' extra' : ''}"
        data-yldt="${esc(g.k)}" data-ylpart="${esc(p.part)}" ${p.n ? '' : 'disabled'}
        title="${p.req ? '必需部件' : '可选部件'}${p.extra ? '（库里有、但不在这个文种的部件清单里）' : ''}">
        ${esc(p.part)}${p.req ? '<b>*</b>' : ''}<span class="yl-n">${p.n}</span>
      </button>`).join('');
    return `<div class="yl-dt${g.n ? '' : ' hollow'}">
      <div class="yl-dt-h">
        <b>${esc(g.k)}</b>${ylBadge(g)}
        ${g.parts_src === 'real' ? '<span class="yl-evi">真题实证</span>' : ''}
        <span class="yl-cnt">${g.n} 条</span>
      </div>
      <div class="yl-dt-d">${esc(g.d)}</div>
      <div class="yl-cells">${cells}</div>
    </div>`;
  }).join('');
}

let ylKindCounts = {};

function ylItemCard(it) {
  // 得体和错例都是成对的，但语义相反：错例是「✗ 错的 / ✓ 对的」，
  // 得体是「✓ 该这么写 / ✗ 不能这么写」。后端已经摊成 good/bad 两个字段。
  if (it.kind === '得体') {
    return `<div class="yl-item">
      <div class="yl-item-h">${esc(it.part || '')} · ${esc(it.kind)}
        ${it.src === 'real' ? '<span class="yl-evi">真题实证</span>'
                            : '<span class="yl-freq zero">人工种子</span>'}</div>
      <div class="yl-text"><b>${esc(it.title || '')}</b></div>
      <div class="ye-good">✓ ${esc(it.good || '')}</div>
      ${it.bad ? `<div class="ye-bad">✗ ${esc(it.bad)}</div>` : ''}
      ${it.note ? `<div class="ye-why">💡 ${esc(it.note)}</div>` : ''}
    </div>`;
  }
  if (it.kind === '错例') {
    return `<div class="yl-item">
      <div class="yl-item-h">${esc(it.part || '')} · ${esc(it.kind)}
        ${it.freq > 1 ? `<span class="yl-freq">犯过 ${it.freq} 次</span>` : ''}</div>
      <div class="ye-bad">✗ ${esc(it.bad || '')}</div>
      <div class="ye-good">✓ ${esc(it.good || '')}</div>
      ${it.note ? `<div class="ye-why">💡 ${esc(it.note)}</div>` : ''}
      ${it.src_ref ? `<div class="yl-src">来源 ${esc(it.src_ref)}</div>` : ''}
    </div>`;
  }
  return `<div class="yl-item">
    <div class="yl-item-h">${esc(it.part || '')} · ${esc(it.kind)}</div>
    <div class="yl-text">${esc(it.text || '')}</div>
    ${it.note ? `<div class="ye-why">💡 ${esc(it.note)}</div>` : ''}
    ${it.example ? `<div class="ye-good">示范：${esc(it.example)}</div>` : ''}
    ${it.src_ref ? `<div class="yl-src">来源 ${esc(it.src_ref)}</div>` : ''}
  </div>`;
}

async function ylOpenCell(dt, part) {
  $('#yl-body').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const q = `?doctype=${encodeURIComponent(dt)}${part ? '&part=' + encodeURIComponent(part) : ''}${ylKind ? '&kind=' + encodeURIComponent(ylKind) : ''}`;
    const d = await api('/api/gongwen/yylib' + q);
    $('#yl-body').innerHTML = `
      <div class="yl-crumb"><button class="btn" id="yl-back">← 返回目录</button>
        <b>${esc(dt)}</b>${part ? ' · ' + esc(part) : ''}　${d.items.length} 条</div>
      ${d.items.length ? d.items.map(ylItemCard).join('')
        : '<p class="empty">这一格还没有素材。</p>'}`;
  } catch (e) { toast(e.message, true); }
}

async function loadYyLib() {
  $('#yl-body').innerHTML = '<p class="empty">加载中…</p>';
  try {
    const d = await api('/api/gongwen/yylib' + (ylKind ? '?kind=' + encodeURIComponent(ylKind) : ''));
    ylCats = d.cats || []; ylKindCounts = d.kinds || {};
    $('#yl-total').textContent = d.total ? `共 ${d.total} 条素材` : '库里还没有素材';
    ylRenderCats();
  } catch (e) { toast(e.message, true); $('#yl-body').innerHTML = '<p class="empty">加载失败</p>'; }
}

function openYyLib(dt) {
  push({ view: 'yylib', title: '应用文素材库' });
  if (dt) { ylKind = ''; ylOpenCell(dt, ''); } else { loadYyLib(); }
}

$('#view-yylib').addEventListener('click', e => {
  const k = e.target.closest('[data-ylk]');
  if (k) { ylKind = k.dataset.ylk; loadYyLib(); return; }
  const cell = e.target.closest('[data-yldt]');
  if (cell) { ylOpenCell(cell.dataset.yldt, cell.dataset.ylpart); return; }
  if (e.target.closest('#yl-back')) loadYyLib();
});
