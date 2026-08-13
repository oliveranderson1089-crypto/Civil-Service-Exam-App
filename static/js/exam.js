/* 全国考情：各地招考公告汇总（爬虫每天抓 + AI 归类，这里只管筛和看）
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, artEm, errMsg, esc, fmtDay, mdSafeHref, push, toast, uiError */

/* ============= 全国考情 ============= */
// 'follow' = 只看关注的省（默认）。它不是一个真的地区，是「我关注的那几个 + 全国性的」。
let exKind = '', exRegion = 'follow', exQ = '', exPoll = 0, exFollow = [], exRegions = [];
// 类型胶囊按公考人的关注顺序排，不按字典序：国考/省考/事考是主线，其余是支线
const EX_KINDS = ['国考', '省考', '事考', '选调', '教师', '医疗', '警法', '其他'];
const EX_KIND_COLOR = {
  '国考': '#b23b2e', '省考': '#2b6fd6', '事考': '#0f766e', '选调': '#7a5cc0',
  '教师': '#c2671f', '医疗': '#2e7d32', '警法': '#5a6b85', '其他': '#777',
};

function openExam() {
  push({ view: 'exam', title: '全国考情' });
  loadExam();
}

/* 公告有没有过时，只能按发布日估——报名截止日藏在原文里，我们不抄（抄错了会让人错过报名）。
   所以这里只说「几天前发的」，把判断留给用户，别替他下「还能不能报」的结论。 */
function exAge(pub) {
  if (!pub) return { txt: '日期不明', cls: 'old' };
  const d = Math.floor((Date.now() - new Date(pub + 'T00:00:00').getTime()) / 86400000);
  if (d <= 0) return { txt: '今天', cls: 'new' };
  if (d === 1) return { txt: '昨天', cls: 'new' };
  if (d <= 7) return { txt: d + ' 天前', cls: 'new' };
  if (d <= 30) return { txt: d + ' 天前', cls: '' };
  return { txt: d + ' 天前', cls: 'old' };
}

async function loadExam() {
  const box = $('#ex-list');
  box.innerHTML = '<p class="empty">加载中…</p>';
  const qs = new URLSearchParams();
  if (exKind) qs.set('kind', exKind);
  if (exRegion) qs.set('region', exRegion);
  if (exQ) qs.set('q', exQ);
  let d;
  try {
    d = await api('/api/exam/notices?' + qs.toString());
  } catch (e) { box.innerHTML = uiError(e); return; }
  exFollow = d.follow || [];
  exRegions = d.regions || [];

  $('#ex-kinds').innerHTML = `<span class="chip ${exKind ? '' : 'active'}" data-exk="">全部类型</span>`
    + EX_KINDS.map(k => `<span class="chip ${exKind === k ? 'active' : ''}" data-exk="${k}"
        >${k}${d.counts[k] ? ' ' + d.counts[k] : ''}</span>`).join('');

  const followTxt = exFollow.length ? exFollow.join('/') : '未设置';
  $('#ex-regions').innerHTML =
    `<span class="chip ${exRegion === 'follow' ? 'active' : ''}" data-exr="follow">${artEm('📍')} 我关注的（${esc(followTxt)}）</span>`
    + `<span class="chip ${exRegion === '' ? 'active' : ''}" data-exr="">不限地区</span>`
    + exRegions.map(r => `<span class="chip ${exRegion === r ? 'active' : ''}" data-exr="${esc(r)}"
        >${esc(r)}${d.by_region[r] ? ' ' + d.by_region[r] : ''}</span>`).join('');

  $('#ex-meta').textContent = d.updated_at
    ? `共收录 ${d.total} 条 · 最近一次抓取 ${d.updated_at.slice(0, 16)}`
    : '还没抓过。点右上「立即抓取」跑第一轮（30 多个源，要几分钟）。';

  if (!d.items.length) {
    box.innerHTML = `<p class="empty">${d.total ? '这个筛选下没有公告，换个类型或地区看看。'
      : '库里还是空的，先点「🔄 立即抓取」。'}</p>`;
    return;
  }
  box.innerHTML = d.items.map(it => {
    const age = exAge(it.pub_date);
    return `<div class="ex-card">
      <div class="ex-head">
        <span class="poly-badge" style="background:${EX_KIND_COLOR[it.kind] || '#777'}">${esc(it.kind)}</span>
        <span class="ex-region">${esc(it.region)}</span>
        ${it.headcount ? `<span class="ex-num">招 ${esc(it.headcount)} 人</span>` : ''}
        <span class="ex-age ${age.cls}">${age.txt}</span>
      </div>
      <!-- href 必须过 mdSafeHref：这个地址是从外站列表页扒下来的，esc() 只挡 HTML，
           挡不住 javascript: 这种协议——它会变成一条点了就执行脚本的链接。 -->
      <a class="ex-title" href="${mdSafeHref(it.url)}" target="_blank" rel="noopener">${esc(it.title)}</a>
      <div class="ex-foot">
        ${it.brief ? `<span class="ex-brief">${esc(it.brief)}</span>` : ''}
        <span class="ex-src">${esc(it.source)}${it.pub_date ? ' · ' + fmtDay(it.pub_date) : ''}</span>
      </div>
    </div>`;
  }).join('');
}

$('#ex-kinds').addEventListener('click', e => {
  const c = e.target.closest('[data-exk]'); if (!c) return;
  exKind = c.dataset.exk; loadExam();
});
$('#ex-regions').addEventListener('click', e => {
  const c = e.target.closest('[data-exr]'); if (!c) return;
  exRegion = c.dataset.exr; loadExam();
});
// 搜索防抖：一个字一个请求会把列表刷成闪烁的
let exQt = 0;
$('#ex-q').addEventListener('input', e => {
  clearTimeout(exQt);
  const v = e.target.value.trim();
  exQt = setTimeout(() => { exQ = v; loadExam(); }, 300);
});

/* 关注地区：多选。用一个就地展开的胶囊面板，不用弹窗——31 个省塞进弹窗要滚，
   而选省份这件事常常是「点开看一眼、改一两个」。 */
$('#ex-follow').onclick = () => {
  const box = $('#ex-list');
  const on = new Set(exFollow);
  box.innerHTML = `<div class="ex-pick">
    <div class="ex-pick-t">选择要关注的地区（可多选）—— 列表默认只显示这些地区 + 全国性公告</div>
    <div class="ex-chips" id="ex-pickbox">${exRegions.filter(r => r !== '全国').map(r =>
    `<span class="chip ${on.has(r) ? 'active' : ''}" data-exp="${esc(r)}">${esc(r)}</span>`).join('')}</div>
    <div class="ex-pick-b"><button class="btn tiny primary" id="ex-picksave">保存</button>
      <button class="btn tiny" id="ex-pickcancel">取消</button></div>
  </div>`;
  $('#ex-pickbox').onclick = e => {
    const c = e.target.closest('[data-exp]'); if (c) c.classList.toggle('active');
  };
  $('#ex-pickcancel').onclick = () => loadExam();
  $('#ex-picksave').onclick = async () => {
    const picks = [...$('#ex-pickbox').querySelectorAll('.chip.active')].map(x => x.dataset.exp);
    try {
      await api('/api/exam/follow', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ regions: picks }),
      });
      exFollow = picks; exRegion = 'follow';
      toast(picks.length ? '已关注 ' + picks.join('、') : '已清空关注地区');
    } catch (e) { toast(errMsg(e), true); }
    await loadExam();      // await 掉，否则调用方以为存完了、列表其实还在重画
  };
};

$('#ex-refresh').onclick = async () => {
  const b = $('#ex-refresh'); b.disabled = true;
  // 只抓当前筛选的那个省时快得多；「我关注的 / 不限」才跑全国
  const picks = (exRegion && exRegion !== 'follow') ? [exRegion]
    : (exRegion === 'follow' ? exFollow.concat('全国') : []);
  $('#ex-meta').textContent = '正在抓取…（' + (picks.length ? picks.join('、') : '全国 30 多个源，约几分钟') + '）';
  try {
    const d = await api('/api/exam/refresh', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ regions: picks }),
    });
    clearInterval(exPoll);
    exPoll = setInterval(async () => {
      try {
        const t = await api('/api/write/task/' + d.task);       // 后台任务表是共用的
        $('#ex-meta').textContent = t.message || '';
        if (t.status === 'done' || t.status === 'error') {
          clearInterval(exPoll); exPoll = 0; b.disabled = false;
          loadExam();
          toast(t.status === 'done' ? '抓取完成' : t.message, t.status !== 'done');
        }
      } catch (_) { clearInterval(exPoll); exPoll = 0; b.disabled = false; }
    }, 3000);
  } catch (e) { toast(errMsg(e), true); b.disabled = false; loadExam(); }
};

/* 桌面壳里 target="_blank" 是死的（WebKit 把新窗口请求吞掉）。desktop.js 有个全局拦截
   会把外链交给系统浏览器，这里不用再管——但列表里的链接全是外站，值得在这儿写一句，
   免得下次有人看到「点了没反应」时又去 exam.js 里找原因。 */
