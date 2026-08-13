/* 党的创新理论学习词典（12371.cn）
 *
 * 由 app.js 按它自己的区段边界切出（原 L7706-7809）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, c, emKey, esc, lsGet, lsSet, push, uiError */

/* ================= 党的创新理论学习词典（12371.cn） ================= */
let pdCat = '全部', pdTimer = null, pdOffset = 0;
const PD_PAGE = 60;    // 一屏取多少条。词条正文长，120 条就有 204KB；60 条约 100KB
async function openPartyDict() {
  push({ view: 'partydict', title: '创新理论词典' });
  $('#pd-q').value = ''; pdCat = '全部';
  try {
    const d = await api('/api/partydict/cats');
    const chips = [`<button class="pd-chip on" data-cat="全部">全部 ${d.total}</button>`]
      .concat(d.cats.map(c => `<button class="pd-chip" data-cat="${esc(c.cat)}">${esc(c.cat)} ${c.count}</button>`));
    $('#pd-cats').innerHTML = chips.join('');
  } catch (e) { console.debug('[党建词典] 分类加载失败：%s', (e && e.message) || e); }
  loadPartyDict();
}
function pdCard(it) {
  return `<div class="pd-item"><div class="pd-term">${esc(it.term)}<span class="pd-tag">${esc(it.cat)}</span></div>
        <div class="pd-body">${emKey(it.content)}</div></div>`;
}
/* more=true 是「加载更多」：往后接着取、追加渲染，不重画已经在屏幕上的卡片
   （重画会把背诵模式翻开过的那些又盖回去）。切分类 / 改搜索词走 more=false，从头来。 */
async function loadPartyDict(more) {
  const q = $('#pd-q').value.trim();
  if (!more) { pdOffset = 0; $('#pd-list').innerHTML = '<p class="empty">加载中…</p>'; }
  try {
    const d = await api('/api/partydict?cat=' + encodeURIComponent(pdCat) + '&q=' + encodeURIComponent(q)
      + '&limit=' + PD_PAGE + '&offset=' + pdOffset);
    if (!more && !d.items.length) { $('#pd-list').innerHTML = '<p class="empty">没有匹配的词条，换个关键词试试。</p>'; return; }
    const html = d.items.map(pdCard).join('')
      + (d.more ? '<button class="pd-more" data-pdmore="1">加载更多词条</button>' : '');
    if (more) {
      const btn = $('#pd-list').querySelector('.pd-more');
      if (btn) btn.remove();
      $('#pd-list').insertAdjacentHTML('beforeend', html);
    } else {
      $('#pd-list').innerHTML = html;
    }
    pdOffset += d.items.length;
  } catch (e) {
    if (more) { const btn = $('#pd-list').querySelector('.pd-more'); if (btn) { btn.disabled = false; btn.textContent = '加载更多词条'; } }
    else { $('#pd-list').innerHTML = uiError(e); }
  }
}
$('#pd-cats').addEventListener('click', e => {
  const b = e.target.closest('.pd-chip'); if (!b) return;
  pdCat = b.dataset.cat;
  $('#pd-cats').querySelectorAll('.pd-chip').forEach(x => x.classList.toggle('on', x === b));
  loadPartyDict();
});
$('#pd-q').addEventListener('input', () => { clearTimeout(pdTimer); pdTimer = setTimeout(loadPartyDict, 250); });
// 背诵模式：隐藏释义、点卡片显示/收起
let pdRecite = false;
$('#pd-recite').onclick = () => {
  pdRecite = !pdRecite;
  $('#pd-list').classList.toggle('reciting', pdRecite);
  $('#pd-recite').classList.toggle('on', pdRecite);
  $('#pd-recite').textContent = pdRecite ? '✓ 背诵中' : '🎯 背诵模式';
  $('#pd-recite-hint').classList.toggle('hidden', !pdRecite);
  $('#pd-list').querySelectorAll('.pd-item.revealed').forEach(x => x.classList.remove('revealed'));
};
$('#pd-list').addEventListener('click', e => {
  const more = e.target.closest('[data-pdmore]');
  if (more) { more.disabled = true; more.textContent = '加载中…'; loadPartyDict(true); return; }
  if (!pdRecite) return;
  const it = e.target.closest('.pd-item'); if (it) it.classList.toggle('revealed');
});

/* 桌面版（GTK/WebKit）没有 speechSynthesis，朗读要借壳调系统 TTS */
const deskTTS = () => !!(window.__desktopTTS && window.webkit && window.webkit.messageHandlers
  && window.webkit.messageHandlers.gk);
function deskMsg(o) {
  try { window.webkit.messageHandlers.gk.postMessage(JSON.stringify(o)); } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }
}
// 引擎：piper=离线神经语音（默认，不联网、起声快）／edge=微软在线（音质最好，要联网）
// ⚠️ 曾经有第三档「系统默认」= speech-dispatcher，已删除：它的 PulseAudio 输出模块会段错误
//    （内核日志实锤 spd_pulse.so segfault），是 Ubuntu 自带组件的 bug，点一下就把朗读弄挂。
const TTS_ENGS = [
  { id: 'piper', name: 'Piper 离线', desc: '本机合成，不联网，起声快' },
  { id: 'edge', name: '微软在线', desc: '音质最自然，需要联网' },
];
const TTS_VOICES = [
  { id: 'zh-CN-XiaoxiaoNeural', name: '晓晓（女）' },
  { id: 'zh-CN-YunxiNeural', name: '云希（男）' },
  { id: 'zh-CN-XiaoyiNeural', name: '晓伊（女·活泼）' },
  { id: 'zh-CN-YunjianNeural', name: '云健（男·浑厚）' },
];
const ttsHas = (id) => (window.__ttsEngines || []).includes(id);
const ttsEng = () => {
  const v = lsGet('ttsEngine');
  if (v && ttsHas(v)) return v;
  return (TTS_ENGS.find(e => ttsHas(e.id)) || {}).id || 'piper';
};
const ttsVoice = () => lsGet('ttsVoice') || TTS_VOICES[0].id;
const deskSay = (text, rate, id) =>
  deskMsg({ a: 'tts', text, rate, id, engine: ttsEng(), voice: ttsVoice() });
const deskStop = () => { if (deskTTS()) deskMsg({ a: 'tts_stop' }); };
// 壳读完一段会回调这里（比按字数估时长准，段间衔接才不断不叠）
window.__ttsEnd = (id) => { const f = window.Reader && Reader._deskCb; if (f && id === Reader._deskId) f(); };

/* 账户页「朗读音色」：只有桌面版有得选（手机走安卓 TTS，网页走浏览器自带） */
function ttsSetup() {
  const sec = $('#acct-tts'); if (!sec) return;
  const engs = TTS_ENGS.filter(e => ttsHas(e.id));
  sec.classList.toggle('hidden', !deskTTS() || engs.length < 2);
  if (!deskTTS()) return;
  const cur = ttsEng();
  $('#tts-eng-row').innerHTML = engs.map(e =>
    `<button class="theme-opt tts-opt${e.id === cur ? ' on' : ''}" data-tts="${e.id}" title="${e.desc}">${e.name}</button>`).join('');
  const vs = $('#tts-voice');
  vs.classList.toggle('hidden', cur !== 'edge');       // 音色只有微软在线那档能挑
  vs.innerHTML = TTS_VOICES.map(v =>
    `<option value="${v.id}"${v.id === ttsVoice() ? ' selected' : ''}>${v.name}</option>`).join('');
}
document.addEventListener('click', e => {
  const b = e.target.closest('.tts-opt');
  if (b) { lsSet('ttsEngine', b.dataset.tts); ttsSetup(); return; }
  if (e.target.closest('#tts-try')) {
    Reader.stop();
    deskSay('金无足赤，人无完人。这是朗读试听。', 1.0, '');
  }
});
document.addEventListener('change', e => {
  if (e.target.id === 'tts-voice') { lsSet('ttsVoice', e.target.value); }
});
