/* 档位控制 —— 后台「档位控制」分栏：按服务把模型档位钉成省钱的还是质量优先的。
   全局 $ / esc / toast / adminConfirm 由 admin.html 的内联脚本提供（见 eslint.config.mjs 的契约）。

   两家模型一页管：文字走 DeepSeek（fast / pro），读图走智谱（free / pro）。
   前端只认「省钱档 / 质量档」这组说法，具体档位名由后端给的 rows 决定。 */

let TR_WIN = '30d';
let TR_DATA = null;
const TR_SEL = new Set();

/* 两家的档位名与说法。cheap/rich 是位置，fast/free 是名字——批量按钮说的是位置。

   读图还有第三档 `exact`（「精准档」，见 extra）：它**不在 cheap↔rich 这条贵贱轴上**，
   而是换另一家（DeepSeek 视觉）。所以批量按钮不碰它，降档保护也不管它——
   设成精准既不是省钱也不是升级，是换一条路。没配那一家时整个按钮不出现。 */
const TR_KIND = {
  text: { cheap: 'fast', rich: 'pro', cheapName: '快速档', richName: '旗舰档', what: '文字' },
  vision: { cheap: 'free', rich: 'pro', cheapName: '免费档', richName: '旗舰档', what: '读图',
            extra: [{ v: 'exact', name: '精准档', need: 'vision_exact' }] },
};

/* 这一档现在摆不摆得出来：`need` 指向 models 里的那个模型名，空的就是没配。
   摆出一个点了设不了的按钮，比没有这个按钮更糟。 */
function trExtra(kind) {
  const k = TR_KIND[kind];
  if (!k.extra || !TR_DATA) return [];
  return k.extra.filter(e => !e.need || (TR_DATA.models || {})[e.need]);
}

/* 档位名 → 人话。exact 不在 cheap/rich 两分里，得单独查一遍，
   否则它会被当成 cheapName 显示成「免费档」——那是**说反了**。 */
function trName(kind, tier) {
  const k = TR_KIND[kind];
  if (tier === k.rich) return k.richName;
  const e = (k.extra || []).find(x => x.v === tier);
  return e ? e.name : k.cheapName;
}

function trNum(n) {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e4) return (n / 1e4).toFixed(1) + '万';
  return String(n || 0);
}

/* 一个旋钮：跟随默认 / 省钱 / 质量。key 就是要写进配置的那个键（服务名或 服务名:档位）。 */
function trSeg(kind, key, cur) {
  const k = TR_KIND[kind];
  const b = (v, txt) => `<button data-v="${v}" class="${cur === v ? 'on' : ''}">${txt}</button>`;
  return `<span class="seg mini tr-set" data-kind="${kind}" data-key="${esc(key)}">
      ${b('', '跟随默认')}${b(k.cheap, k.cheapName)}${b(k.rich, k.richName)}`
    + trExtra(kind).map(e => b(e.v, e.name)).join('') + '</span>';
}

/* 「现在实际走哪档」。跟代码默认一致时是绿的，被改过是红的——一眼看出哪些是人为动过的。 */
function trCur(kind, row) {
  const name = trName(kind, row.effective);
  const same = row.effective === row.tier;
  return `<div class="tr-cur${same ? ' same' : ''}">当前生效：<b>${name}</b>${same ? '（代码默认）' : ''}</div>`;
}

function trUse(row, max) {
  if (!row.calls) return '<span style="color:#98a1b0;">窗口内未跑</span>';
  const pct = max ? Math.max(2, Math.round(row.tokens * 100 / max)) : 2;
  const fail = row.failed ? ` · <span style="color:#c0392b;">${row.failed} 失败</span>` : '';
  return `${trNum(row.tokens)} token · ${row.calls} 次${fail}
    <div class="bar"><i class="${row.tier === 'pro' ? 'rich' : ''}" style="width:${pct}%"></i></div>`;
}

/* 一行服务。单档的旋钮就摆在行里；多档的（取材走 fast、成文走 pro）拆成子行分别设，
   免得「整体设一次」把便宜的那半也一起动了。 */
function trRow(s, max) {
  const rows = [];
  ['text', 'vision'].forEach(kind => rows.push(...s[kind].rows.map(r => ({ kind, r }))));
  if (!rows.length) return '';
  const tag = s.known ? '' : '<span class="tr-tag new">名册外</span>';
  const use = { tokens: s.tokens, calls: s.calls, failed: 0, tier: rows[0].r.tier };
  const single = rows.length === 1;
  const head = `<div class="srow${TR_SEL.has(s.key) ? ' sel' : ''}" data-svc="${esc(s.key)}">
      <input type="checkbox" class="tr-ck"${TR_SEL.has(s.key) ? ' checked' : ''}>
      <div class="sname"><b>${esc(s.name)}${tag}</b><div class="d">${esc(s.desc)}</div></div>
      <div class="use">${trUse(use, max)}</div>
      <div class="tr-ctl">${single
    ? trSeg(rows[0].kind, s.key, s[rows[0].kind].override || rows[0].r.override) + trCur(rows[0].kind, rows[0].r)
    : '<span style="font-size:12px;color:#5f6875;">下面分别设 ↓</span>'}</div>`;
  const subs = single ? '' : rows.map(({ kind, r }) => {
    const k = TR_KIND[kind];
    const def = trName(kind, r.tier);   // r.tier 是代码默认档，眼下只会是 free/pro；走 trName 是为了以后加档不漏
    return `<div class="sub">
        <div>· ${k.what}${rows.filter(x => x.kind === kind).length > 1 ? '（默认' + def + '那部分）' : ''}
          <span class="tr-tag ${r.tier === k.rich ? 'rich' : 'cheap'}">默认${def}</span>
          <span style="color:#5f6875;">${r.calls ? trNum(r.tokens) + ' token · ' + r.calls + ' 次' : '窗口内未跑'}</span></div>
        <div>${trSeg(kind, s.key + ':' + r.tier, r.override || s[kind].override)}${trCur(kind, r)}</div>
      </div>`;
  }).join('');
  return head + subs + '</div>';
}

function trRender() {
  const d = TR_DATA;
  $('#tr-models').innerHTML = `文字 · 快速 <b>${esc(d.models.fast)}</b>｜旗舰 <b>${esc(d.models.pro)}</b>`
    + (d.vision_configured
      ? `<br>读图 · 免费 <b>${esc(d.models.vision_free || '未填')}</b>｜旗舰 <b>${esc(d.models.vision_pro || '未填')}</b>`
        + (d.models.vision_exact ? `｜精准 <b>${esc(d.models.vision_exact)}</b>` : '')
      : '<br>读图 · <span style="color:#98a1b0;">未配置视觉模型</span>');

  $('#tr-global').innerHTML = `
    <div class="t"><b>全站兜底</b>
      <div class="d">一键把<b>没单独设过</b>的服务压到省钱档；单独设过的不受影响。</div></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;">
      ${trSeg('text', '*', d.global.text)}${d.vision_configured ? trSeg('vision', '*', d.global.vision) : ''}
    </div>`;

  const max = Math.max(...d.groups.flatMap(g => g.services.map(s => s.tokens)), 1);
  $('#tr-body').innerHTML = d.groups.map(g => {
    const live = g.services.filter(s => s.calls);
    const idle = g.services.filter(s => !s.calls);
    return `<div class="tr-grp"><h3>${esc(g.name)} <i></i>
        <span style="font-weight:400;">按用量排序</span></h3>
      ${live.map(s => trRow(s, max)).join('') || '<p class="ai-tip" style="margin:6px 0;">这个窗口里没有调用。</p>'}
      ${idle.length ? `<div class="tr-idle hidden">${idle.map(s => trRow(s, max)).join('')}</div>
        <div style="padding:8px 4px;"><button class="ubtn tr-more">展开窗口内没跑过的 ${idle.length} 个服务</button></div>` : ''}
    </div>`;
  }).join('');
  trSelChanged();
}

async function loadTier() {
  try {
    const r = await fetch('/api/admin/ai/tiers?win=' + encodeURIComponent(TR_WIN), { cache: 'no-store' });
    const d = await r.json();
    if (!r.ok) { $('#tr-body').innerHTML = '<p class="ai-tip">读取失败：' + esc(d.error || '') + '</p>'; return; }
    TR_DATA = d;
    trRender();
  } catch (e) {
    $('#tr-body').innerHTML = '<p class="ai-tip">读取失败：' + esc(e.message) + '</p>';
  }
}

/* 保存。降档时后端会先回 need_confirm（一条都不写），确认后带 confirmed 再来一次。
   闸在后端，这里只负责把后端给的后果原样念给人听——别在前端自己编一套判断。 */
async function trSave(sets, vision, what) {
  const post = (confirmed) => fetch('/api/admin/ai/tiers', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ set: sets || {}, vision: vision || {}, confirmed }),
  });
  let r = await post(false);
  let d = await r.json();
  if (r.ok && d.need_confirm) {
    const text = d.need_confirm.map(x => '· ' + x.why).join('\n\n');
    if (!await adminConfirm(text + '\n\n确定要降档吗？', '降档确认')) return false;
    r = await post(true);
    d = await r.json();
  }
  if (!r.ok || !d.ok) { toast(d.error || '保存失败', true); return false; }
  toast(what + '已保存，立即生效');
  await loadTier();
  return true;
}

function trSelChanged() {
  document.querySelectorAll('#tr-body .srow').forEach(
    el => el.classList.toggle('sel', TR_SEL.has(el.dataset.svc)));
  $('#tr-bulk').classList.toggle('hidden', !TR_SEL.size);
  $('#tr-cnt').textContent = '已选 ' + TR_SEL.size + ' 项';
}

$('#tr-body').onclick = async (e) => {
  const more = e.target.closest('.tr-more');
  if (more) { more.parentElement.previousElementSibling.classList.remove('hidden'); more.remove(); return; }
  const btn = e.target.closest('.tr-set button');
  if (btn) {
    const seg = btn.parentElement;
    const kind = seg.dataset.kind, key = seg.dataset.key, v = btn.dataset.v;
    const payload = { [key]: v };
    await trSave(kind === 'text' ? payload : null, kind === 'vision' ? payload : null, '档位');
    return;
  }
  const ck = e.target.closest('.tr-ck');
  if (ck) {
    const key = ck.closest('.srow').dataset.svc;
    if (ck.checked) TR_SEL.add(key); else TR_SEL.delete(key);
    trSelChanged();
  }
};

$('#tr-global').onclick = async (e) => {
  const btn = e.target.closest('.tr-set button');
  if (!btn) return;
  const seg = btn.parentElement;
  const p = { '*': btn.dataset.v };
  await trSave(seg.dataset.kind === 'text' ? p : null,
    seg.dataset.kind === 'vision' ? p : null, '全站兜底');
};

/* 批量：选中的服务，两家一起改。「省钱档」在文字那边是 fast、读图那边是 free——
   同一个意思在两家有两个名字，所以批量按位置发，不按名字发。 */
$('#tr-bulk').onclick = async (e) => {
  if (e.target.id === 'tr-none') { TR_SEL.clear(); trSelChanged(); return; }
  const b = e.target.closest('[data-bulk]');
  if (!b || !TR_SEL.size) return;
  const pos = b.dataset.bulk;
  const sets = {}, vision = {};
  TR_DATA.groups.flatMap(g => g.services).filter(s => TR_SEL.has(s.key)).forEach(s => {
    if (s.text.rows.length) sets[s.key] = pos ? TR_KIND.text[pos] : '';
    if (s.vision.rows.length) vision[s.key] = pos ? TR_KIND.vision[pos] : '';
  });
  if (await trSave(sets, vision, '这 ' + TR_SEL.size + ' 项')) TR_SEL.clear();
};

$('#tr-win').onclick = (e) => {
  const b = e.target.closest('[data-win]');
  if (!b) return;
  TR_WIN = b.dataset.win;
  document.querySelectorAll('#tr-win [data-win]').forEach(x => x.classList.toggle('on', x === b));
  loadTier();
};
$('#tr-refresh').onclick = loadTier;

loadTier();
