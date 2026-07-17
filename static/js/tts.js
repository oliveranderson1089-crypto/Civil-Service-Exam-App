/* 逐条朗读（安卓 TTS 桥 / 浏览器 speechSynthesis）
 *
 * 由 app.js 按它自己的区段边界切出（原 L7810-7996）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, c, deskSay, deskStop, deskTTS, push,
   toast */

/* ================= 逐条朗读（安卓 TTS 桥 / 浏览器 speechSynthesis） ================= */
// 会自动注入 🔊 按钮的内容条目选择器（新渲染的列表/卡片自动获得朗读按钮）
const READ_ITEM_SEL = '.gk-card, .pd-item, .poly-card, .cd-sec, .cd-body, .item, .poly-reader, #viewer-reader, .cs-ov-body, .cs-kq, .ai-msg.assistant, .sc-body-solo, .rv-flash';
const READ_RATES = [1.0, 1.2, 1.5, 0.8];
window.Reader = {
  playing: false, segs: [], idx: 0, gen: 0, rateIdx: 0, card: null,
  native() { return !!(window.GongkaoNative && window.GongkaoNative.ttsSpeak); },
  rate() { return READ_RATES[this.rateIdx]; },
  split(text) {
    // 按句切分（细粒度：切语速时从当前句继续，不用重头）；超长句再按逗号拆。
    // 用「捕获组切分 + 把标点拼回前一段」保留标点，避开正则「后行断言」——
    // iOS 16.4 以前的 Safari 不支持后行断言，含它的脚本会整份解析报错。
    const t = (text || '').replace(/\s+/g, ' ').trim();
    const splitKeep = (str, re) => {
      const out = [];
      str.split(re).forEach((part, i) => {
        if (i % 2 === 0) out.push(part);
        else if (out.length) out[out.length - 1] += part;   // 标点拼回前一段
      });
      return out;
    };
    const segs = [];
    for (let s of splitKeep(t, /([。！？；.!?;\n]+)/)) {
      s = s.trim(); if (!s) continue;
      if (s.length <= 120) { segs.push(s); continue; }
      let cur = '';
      for (const p of splitKeep(s, /([，,、]+)/)) {
        if ((cur + p).length > 120) { if (cur.trim()) segs.push(cur.trim()); cur = p; }
        else cur += p;
      }
      if (cur.trim()) segs.push(cur.trim());
    }
    return segs;
  },
  textOf(card) {
    const c = card.cloneNode(true);
    c.querySelectorAll('button, .read-item-btn, .item-actions, .news-star, .iconbtn, .rv-stage').forEach(x => x.remove());
    return c.innerText || '';
  },
  readCard(card) {
    if (this.card === card && this.playing) { this.stop(); return; }  // 再点同一条 = 停止
    this.stop();
    const segs = this.split(this.textOf(card));
    if (!segs.length) { toast('这一条没有可朗读的文字', true); return; }
    this.card = card; card.classList.add('reading-src');
    this.segs = segs; this.idx = 0; this.playing = true;
    this.ui(); this.next();
  },
  next() {
    if (!this.playing) return;
    if (this.idx >= this.segs.length) { this.stop(); return; }
    const myGen = ++this.gen; const seg = this.segs[this.idx];
    if (this.native()) {
      this._waitId = 'r' + myGen;
      try { window.GongkaoNative.ttsSpeak(this._waitId, seg, this.rate()); }
      catch (_) { this.stop(); }
    } else if (deskTTS()) {
      // 电脑桌面版：WebKit 根本没有 speechSynthesis，借壳去调系统 TTS（Piper/微软/espeak）。
      // 壳读完这段会回调 __ttsEnd，接着读下一段；超时只是兜底（万一壳挂了不至于卡死）。
      const adv = () => {
        if (!this.playing || myGen !== this.gen) return;
        clearTimeout(this._deskT); this._deskCb = null;
        this.idx++; this.next();
      };
      this._deskId = 'r' + myGen; this._deskCb = adv;
      deskSay(seg, this.rate(), this._deskId);
      this._deskT = setTimeout(adv, Math.max(4000, seg.length * 600 / this.rate()));
    } else if (window.speechSynthesis) {
      const u = new SpeechSynthesisUtterance(seg);
      u.lang = 'zh-CN'; u.rate = this.rate();
      u.onend = () => { if (this.playing && myGen === this.gen) { this.idx++; this.next(); } };
      u.onerror = () => { if (this.playing && myGen === this.gen) { this.idx++; this.next(); } };
      speechSynthesis.speak(u);
    } else { toast('当前环境不支持语音朗读', true); this.stop(); }
  },
  reRate() {
    // 调语速：取消当前发声，但 idx 不动 → 从当前这句接着读，不从头
    if (!this.playing) return;
    this.gen++;
    try { if (this.native()) window.GongkaoNative.ttsCancel(); } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }
    try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }
    deskStop(); clearTimeout(this._deskT); this._deskCb = null;
    setTimeout(() => this.next(), 60);
  },
  stop() {
    this.playing = false; this.gen++; this.segs = []; this.idx = 0;
    if (this.card) { this.card.classList.remove('reading-src'); this.card = null; }
    try { if (this.native()) window.GongkaoNative.ttsCancel(); } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }
    try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }
    deskStop(); clearTimeout(this._deskT); this._deskCb = null;
    this.ui();
  },
  ui() {
    $('#read-ctrl').classList.toggle('hidden', !this.playing);
    $('#read-rate').textContent = this.rate().toFixed(1) + '×';
  },
};
// 安卓 TTS 段落结束回调
window.__ttsEvent = function (id, ev) {
  if (ev === 'end' && Reader.playing && id === Reader._waitId) { Reader.idx++; Reader.next(); }
};
$('#read-stop').onclick = () => Reader.stop();
$('#read-rate').onclick = () => {
  Reader.rateIdx = (Reader.rateIdx + 1) % READ_RATES.length;
  $('#read-rate').textContent = Reader.rate().toFixed(1) + '×';
  Reader.reRate();
};
// 自动给内容条目注入 🔊 朗读按钮（MutationObserver 覆盖所有现在/将来渲染的列表）
const READ_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>';
const SHARE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.6" y1="10.5" x2="15.4" y2="6.5"/><line x1="8.6" y1="13.5" x2="15.4" y2="17.5"/></svg>';
async function shareCard(card) {
  const text = (Reader.textOf(card) || '').trim();
  if (!text) { toast('这一条没有可分享的文字', true); return; }
  const payload = text + '\n\n—— 来自「公考助手」';
  try {
    if (window.GongkaoNative && typeof GongkaoNative.share === 'function') { GongkaoNative.share(payload); return; }
  } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }
  if (navigator.share) {
    try { await navigator.share({ text: payload }); return; } catch (e) { if (e && e.name === 'AbortError') return; }
  }
  // 剪贴板兜底（旧 APK / 无分享面板环境）
  let copied = false;
  try { await navigator.clipboard.writeText(payload); copied = true; } catch (_) { /* clipboard API 不给用，下面退回 execCommand */ }
  if (!copied) {
    try {
      const ta = document.createElement('textarea');
      ta.value = payload; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      copied = document.execCommand('copy'); ta.remove();
    } catch (_) { /* execCommand 也不行就是真复制不了，copied 保持 false，下面会提示 */ }
  }
  toast(copied ? '已复制内容，去微信等应用粘贴即可（更新 APK 后可直接弹分享面板）' : '分享失败', !copied);
}
/* ---- 朗读：两条路，覆盖所有带文字的地方（不放进悬浮球）----
   ① 卡片/整篇上的 🔊 —— READ_ITEM_SEL 里已经包含 .poly-reader / #viewer-reader / .cd-body
      这些整篇容器，所以「读整篇」本来就有，不用再做一个「朗读本页」
   ② 选中一段文字 —— 冒出「🔊 朗读选中」，只读选中的那段 */
// 选中文字 → 冒出朗读气泡（手写笔/鼠标划选都行）
let _selBub = null;
function selBubHide() { if (_selBub) { _selBub.remove(); _selBub = null; } }
document.addEventListener('selectionchange', () => {
  clearTimeout(window._selT);
  window._selT = setTimeout(() => {
    const sel = window.getSelection();
    const txt = sel && String(sel).trim();
    if (!txt || txt.length < 6 || sel.isCollapsed) { selBubHide(); return; }
    // 输入框里的选中不算（那是在编辑，不是在读）
    const a = sel.anchorNode;
    if (a && a.parentElement && a.parentElement.closest('input, textarea, [contenteditable]')) return;
    let r;
    try { r = sel.getRangeAt(0).getBoundingClientRect(); } catch (_) { return; }
    if (!r || (!r.width && !r.height)) return;
    if (!_selBub) {
      _selBub = document.createElement('button');
      _selBub.className = 'sel-read';
      _selBub.innerHTML = '🔊 朗读选中';
      _selBub.onmousedown = e => e.preventDefault();     // 别把选区点没了
      _selBub.onclick = () => {
        const t = String(window.getSelection()).trim();
        selBubHide();
        if (!t) return;
        Reader.stop();
        Reader.segs = Reader.split(t); Reader.idx = 0; Reader.playing = true;
        Reader.card = null; Reader.ui(); Reader.next();
      };
      document.body.appendChild(_selBub);
    }
    const top = r.top - 42 < 6 ? r.bottom + 8 : r.top - 42;
    _selBub.style.left = Math.max(8, Math.min(window.innerWidth - 110, r.left + r.width / 2 - 52)) + 'px';
    _selBub.style.top = top + 'px';
  }, 220);
});
document.addEventListener('scroll', selBubHide, true);

function injectReadBtns() {
  document.querySelectorAll(READ_ITEM_SEL).forEach(card => {
    if (card.classList.contains('ai-typing')) return;  // 「思考中…」气泡不加按钮
    if (card.querySelector(':scope > .read-item-btn')) return;
    if (!(card.innerText || '').trim()) return;
    const b = document.createElement('button');
    b.className = 'read-item-btn'; b.title = '朗读这一条'; b.innerHTML = READ_ICON;
    b.onclick = e => { e.stopPropagation(); e.preventDefault(); Reader.readCard(card); };
    card.appendChild(b);
    const sb = document.createElement('button');
    sb.className = 'read-item-btn share-item-btn'; sb.title = '分享这一条'; sb.innerHTML = SHARE_ICON;
    sb.onclick = e => { e.stopPropagation(); e.preventDefault(); shareCard(card); };
    card.appendChild(sb);
  });
}
let _readInjTimer = null;
new MutationObserver(() => {
  clearTimeout(_readInjTimer);
  _readInjTimer = setTimeout(injectReadBtns, 120);
}).observe(document.body, { childList: true, subtree: true });
injectReadBtns();
