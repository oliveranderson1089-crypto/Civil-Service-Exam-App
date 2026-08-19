/* 录音与语音条 —— 聊天发语音、AI 助手语音输入共用这一份
 *
 * 分两半：
 *   录：voiceRecord() 打开录音浮层，返回一段音频（用户点「取消」就返回 null）。
 *       浮层的 DOM 由这里现建，不写进 index.html —— 打包器会把 <script> 整体前移，
 *       页面中间多一段 DOM 反而添乱（见 assets.py 里那道闸）。
 *   放：voicePlayer 全局只有一个 <audio>，点新的自动停旧的，
 *       不然点了三条就是三个人同时说话。
 *
 * 拿不到麦克风的场景比想象中多，一律给「为什么」而不是「失败了」：
 *   - http 局域网直连（192.168.x.x:8011）不是安全上下文，浏览器根本不给 mediaDevices
 *   - 桌面 WebKit / 老安卓 WebView 可能没有 MediaRecorder
 *   - 用户点了拒绝，或系统层面没给应用麦克风权限
 */
/* global $, appConfirm, artEm, esc, toast */

'use strict';

const VOICE_MAX_SEC = 300;          // 与 social.py 的 VOICE_MAX_SECONDS 一致
const VOICE_MIN_SEC = 0.6;          // 比这还短多半是误触，不发

/* 录出来的容器格式各端不同：Chrome/安卓是 webm+opus，Safari/iOS 是 mp4+aac。
   都让服务端的 ffmpeg 兜着，前端只挑一个当前浏览器真支持的。 */
const VOICE_TYPES = [
  ['audio/webm;codecs=opus', '.webm'], ['audio/webm', '.webm'],
  ['audio/ogg;codecs=opus', '.ogg'], ['audio/mp4', '.m4a'], ['', '.webm'],
];

function voicePickType() {
  for (const [t, ext] of VOICE_TYPES) {
    if (!t) return { type: '', ext };
    try { if (window.MediaRecorder && MediaRecorder.isTypeSupported(t)) return { type: t, ext }; } catch (_) { /* 老 WebView 没有 isTypeSupported，退到下一个 */ }
  }
  return { type: '', ext: '.webm' };
}

function voiceSupported() {
  return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
}

/* 不支持时到底缺哪一块 —— 用户拿这句话才知道该怎么办 */
function voiceWhyNot() {
  if (!window.isSecureContext && location.protocol === 'http:' && !/^(localhost|127\.)/.test(location.hostname)) {
    return '浏览器只在 https 或 localhost 下才给麦克风。用桌面版/手机 App 打开，或给服务配个 https 就能录了。';
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return '这个浏览器不支持录音（没有 getUserMedia）。';
  if (!window.MediaRecorder) return '这个浏览器不支持录音（没有 MediaRecorder）。';
  return '';
}

function voiceFmt(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  return (sec >= 60 ? Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0') : sec + '″');
}

/* ================= 录 ================= */
let voiceHud = null, voiceCur = null;

function voiceBuildHud() {
  if (voiceHud) return voiceHud;
  const d = document.createElement('div');
  d.className = 'voice-hud hidden';
  d.innerHTML =
    '<div class="voice-card">' +
      '<div class="voice-wave" id="voice-wave"></div>' +
      '<div class="voice-time" id="voice-time">0″</div>' +
      '<div class="voice-tip" id="voice-tip">正在录音，说完点「完成」</div>' +
      '<div class="voice-acts">' +
        '<button type="button" class="btn" id="voice-cancel">取消</button>' +
        '<button type="button" class="btn primary" id="voice-done">完成</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(d);
  voiceHud = d;
  return d;
}

/* 音量柱：纯装饰，但录音时没有任何动静会让人以为卡住了。
   AudioContext 出问题（桌面 WebKit 偶发）就安静地不画，绝不能影响录音本身。 */
function voiceMeter(stream, box) {
  const bars = [];
  box.innerHTML = '';
  for (let i = 0; i < 20; i++) {
    const b = document.createElement('i'); box.appendChild(b); bars.push(b);
  }
  let ctx, raf = 0;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return () => {};
    ctx = new AC();
    const an = ctx.createAnalyser();
    an.fftSize = 64;
    ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Uint8Array(an.frequencyBinCount);
    const tick = () => {
      an.getByteFrequencyData(buf);
      for (let i = 0; i < bars.length; i++) {
        const v = buf[i + 2] / 255;
        bars[i].style.transform = 'scaleY(' + (0.12 + v * 0.88).toFixed(3) + ')';
      }
      raf = requestAnimationFrame(tick);
    };
    tick();
  } catch (_) { return () => {}; }
  return () => {
    if (raf) cancelAnimationFrame(raf);
    try { ctx && ctx.close(); } catch (_) { /* 已经关了 */ }
  };
}

/* 权限被拒之后怎么办。

   在安卓/桌面壳里：拒过一次（尤其勾了「不再询问」）系统就再也不会弹了，光提示
   「去设置里允许」等于让用户自己在设置里翻应用列表。所以弹一句问清楚，点确定就
   由外壳直接跳到本应用的权限页。
   普通浏览器里没有这条路（权限在地址栏那个小锁里，程序跳不过去），还是给文字。 */
function voiceNative() {
  const na = window.GongkaoNative;
  return na && typeof na.openAppSettings === 'function' ? na : null;
}
async function voiceAskPermission() {
  const na = voiceNative();
  if (!na) {
    toast('没拿到麦克风权限：在系统/浏览器设置里允许本站使用麦克风', true);
    return;
  }
  const go = await appConfirm('录音需要麦克风权限，现在系统里是关着的。要去权限设置里打开吗？',
                              { title: '需要麦克风权限', okText: '去设置' });
  if (!go) return;
  try { na.openAppSettings(); } catch (_) { toast('打不开设置页，请到「设置 → 应用 → 公考助手 → 权限」里开麦克风', true); }
}

/* 开麦克风。失败一次先重试一次 —— 安卓 WebView 上「上一次录音的通道刚放开、新的还没
   接上」会瞬时报 NotReadableError（设备打不开），隔几百毫秒再要就成了。
   只重试这一种：权限被拒、没有设备，再试一百次也是同样的结果。 */
async function voiceOpenMic() {
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    if (!e || e.name !== 'NotReadableError') throw e;
    await new Promise(r => setTimeout(r, 400));
    return navigator.mediaDevices.getUserMedia({ audio: true });
  }
}

/* 「设备打不开」到底是谁的锅。

   浏览器只给一个笼统的 NotReadableError，网页这层分不出是别的应用占着、还是权限
   其实没给、还是 WebView 自己没接上。外壳能绕开 WebView 直接开一次 AudioRecord 实测
   （micProbe），把三者分开，每种给一条能照做的路。原始错误名一并带上，
   免得下次又只能凭「打不开」三个字猜。 */
async function voiceOpenFail(e) {
  const detail = (e && e.name) || '未知错误';
  const na = voiceNative();
  let st = '';
  if (na && typeof na.micProbe === 'function') {
    try { st = String(na.micProbe() || ''); } catch (_) { st = ''; }
  }
  if (st === 'denied') { await voiceAskPermission(); return; }
  if (st === 'busy') { toast('麦克风正被别的应用占着（通话、录音机、语音助手…），先退出那个再来', true); return; }
  if (st === 'ok') {
    // 系统这层能录、WebView 那层不行：重载网页救不了（音频通道挂在进程上），得整个应用重开
    toast('系统这层能录音，是应用内的录音通道没接上（' + detail + '）。把应用从后台完全退出再打开，通常就好了', true);
    return;
  }
  toast('打不开麦克风（' + detail + (st ? ' / ' + st : '') + '）：检查一下系统麦克风设置，或换个浏览器试试', true);
}

/* 开录 → 用户点完成/取消 → 返回 {blob, dur, ext} 或 null。
   同一时刻只允许一场录音。 */
async function voiceRecord(opt) {
  opt = opt || {};
  if (voiceCur) return null;
  if (!voiceSupported()) { toast(voiceWhyNot() || '这个环境不能录音', true); return null; }
  let stream;
  try {
    stream = await voiceOpenMic();
  } catch (e) {
    // 三类错因、三条出路：权限没给 → 劝去设置；没有设备 → 就一句话；
    // 设备打不开 → 到底是谁占着，问外壳去实测（voiceOpenFail）
    const n = e && e.name;
    if (n === 'NotFoundError' || n === 'DevicesNotFoundError') toast('没找到麦克风设备', true);
    else if (n === 'NotAllowedError' || n === 'SecurityError' || n === 'PermissionDeniedError') await voiceAskPermission();
    else await voiceOpenFail(e);
    return null;
  }
  const { type, ext } = voicePickType();
  let rec;
  try {
    rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
  } catch (_) {
    try { rec = new MediaRecorder(stream); } catch (_e2) { stream.getTracks().forEach(t => t.stop()); toast('这个浏览器不支持录音', true); return null; }
  }

  const hud = voiceBuildHud();
  hud.classList.remove('hidden');
  $('#voice-tip').textContent = opt.tip || '正在录音，说完点「完成」';
  const stopMeter = voiceMeter(stream, $('#voice-wave'));
  const t0 = Date.now();
  const chunks = [];
  rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };

  return new Promise(resolve => {
    let ticker = 0, settled = false;
    const finish = (keep) => {
      if (settled) return; settled = true;
      clearInterval(ticker);
      stopMeter();
      hud.classList.add('hidden');
      $('#voice-cancel').onclick = $('#voice-done').onclick = null;
      const dur = (Date.now() - t0) / 1000;
      rec.onstop = () => {
        stream.getTracks().forEach(t => t.stop());   // 不停轨，麦克风指示灯会一直亮着
        voiceCur = null;
        if (!keep) return resolve(null);
        const blob = new Blob(chunks, { type: rec.mimeType || type || 'audio/webm' });
        if (dur < VOICE_MIN_SEC || !blob.size) { toast('太短了，没录到东西'); return resolve(null); }
        resolve({ blob, dur: Math.round(dur * 10) / 10, ext });
      };
      try { rec.stop(); } catch (_) { rec.onstop(); }
    };
    voiceCur = { cancel: () => finish(false) };
    $('#voice-cancel').onclick = () => finish(false);
    $('#voice-done').onclick = () => finish(true);
    ticker = setInterval(() => {
      const s = (Date.now() - t0) / 1000;
      const left = VOICE_MAX_SEC - s;
      $('#voice-time').textContent = voiceFmt(s);
      // 到点自动收尾并**发出去**，不是丢掉：录满 5 分钟还给人丢了才最气人
      if (left <= 0) { toast('录满 ' + Math.round(VOICE_MAX_SEC / 60) + ' 分钟了，先发这一段'); finish(true); }
      else if (left <= 10) $('#voice-tip').textContent = '还能录 ' + Math.ceil(left) + ' 秒';
    }, 200);
    try { rec.start(); } catch (_) { finish(false); toast('录音起不来', true); }
  });
}

/* ================= 放 ================= */
/* 全局单例：谁在响、响到哪了，都记在这儿，界面上的进度条据此刷新 */
const voicePlayer = { el: null, key: '', onstate: null };

function voiceStop() {
  if (voicePlayer.el) { try { voicePlayer.el.pause(); } catch (_) { /* 已经停了 */ } }
  const k = voicePlayer.key;
  voicePlayer.key = '';
  if (voicePlayer.onstate && k) voicePlayer.onstate(k, 'stop', 0);
}

/* key 用来标识「哪一条在响」（聊天里就是消息 id）。再点同一条 = 停。 */
function voiceToggle(key, url, onstate) {
  if (voicePlayer.key === key) { voiceStop(); return; }
  voiceStop();
  if (!voicePlayer.el) voicePlayer.el = new Audio();
  const a = voicePlayer.el;
  voicePlayer.key = key;
  voicePlayer.onstate = onstate || null;
  a.onended = () => { const k = voicePlayer.key; voicePlayer.key = ''; if (onstate && k) onstate(k, 'stop', 1); };
  a.onerror = () => { const k = voicePlayer.key; voicePlayer.key = ''; if (onstate && k) onstate(k, 'stop', 0); toast('这段语音放不出来', true); };
  a.ontimeupdate = () => {
    if (voicePlayer.key !== key || !a.duration || !isFinite(a.duration)) return;
    if (onstate) onstate(key, 'progress', a.currentTime / a.duration);
  };
  a.src = url;
  const p = a.play();
  if (p && p.catch) p.catch(() => { voicePlayer.key = ''; if (onstate) onstate(key, 'stop', 0); toast('播放被浏览器拦住了，再点一下', true); });
  if (onstate) onstate(key, 'play', 0);
}

/* ================= 语音转文字（AI 助手的语音输入 / 聊天的「转文字」都问它） ================= */
/* null=还没问过。**只在用户真的点麦克风时才问**：放在页面初始化里问，
   一来为一颗按钮多打一趟接口，二来那次回调可能落在页面/视图已经拆掉之后。
   问一次就记住，同一次会话里不会重复问。 */
let voiceAsrOn = null;

async function voiceAsrEnabled() {
  if (voiceAsrOn !== null) return voiceAsrOn;
  try {
    const d = await fetch('/api/asr/status', { cache: 'no-store' }).then(r => r.json());
    voiceAsrOn = !!d.enabled;
  } catch (_) { voiceAsrOn = false; }
  return voiceAsrOn;
}

/* 一段音频换一段文字。失败抛错，调用方决定怎么提示。 */
async function voiceToText(blob, ext) {
  const fd = new FormData();
  fd.append('file', blob, 'voice' + (ext || '.webm'));
  const r = await fetch('/api/asr', { method: 'POST', body: fd });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || '识别失败');
  return d.text || '';
}

/* ===== 识别出来的文字怎么落进输入框（AI 助手和聊天共用这一份） =====
 *
 * 铁律：**不要拿「开始识别时的 value 快照」整个覆盖输入框**。
 * 识别是异步的（录一段 + 上传 + 转写要好几秒），这中间用户完全可能接着打字：
 *   · 覆盖 = 把人家刚打的字吞掉，而且没有任何提示
 *   · 正在用输入法拼的字也会被这一下打断，WebKit 直接把预编辑串按**原始字母**提交
 *     ——「输入法明明切到中文了，打出来还是 dfsdf」就是这么来的（手写板踩过，见 handwrite.js）
 * 一律插到**光标处**；异步回来之前，调用方还要先确认这个框是不是还归自己管
 * （会话可能已经切走了）。
 */
function voiceSep(v, at) {      // 紧挨着已有文字时补个空格，别把两句话黏死
  return (at > 0 && !/\s$/.test(v.slice(0, at))) ? ' ' : '';
}
function voiceInsert(el, text) {
  if (!el || !text) return;
  const v = el.value;
  let s = el.selectionStart, e = el.selectionEnd;
  if (s == null || e == null) s = e = v.length;   // 拿不到光标（没聚焦过）就接在末尾
  const ins = voiceSep(v, s) + text;
  el.value = v.slice(0, s) + ins + v.slice(e);
  el.selectionStart = el.selectionEnd = s + ins.length;
  el.dispatchEvent(new Event('input', { bubbles: true }));   // 输入框自动长高、草稿跟着存
}
/* 浏览器自带的实时识别：临时结果会被后来更好的结果不断替换，所以得记住
   「我上次写进去的是哪一段」，每次只改这一段 —— 而不是重写整个输入框。
   这样用户在后面接着打的字不会被一轮轮的临时结果冲掉。 */
function voiceLive(el) {
  if (!el) return { set() {} };
  const at = (el.selectionStart != null ? el.selectionStart : el.value.length);
  const sep = voiceSep(el.value, at);
  let len = 0;                  // 上一次写进去多少个字符（含那个分隔空格）
  return {
    set(txt) {
      const v = el.value;
      const body = txt ? sep + txt : '';
      el.value = v.slice(0, at) + body + v.slice(at + len);
      len = body.length;
      el.selectionStart = el.selectionEnd = at + len;
      el.dispatchEvent(new Event('input', { bubbles: true }));
    },
  };
}

/* 语音气泡的 HTML。聊天里用，样式在 style.css 的 .cr-voice。 */
function voiceBubbleHtml(m) {
  const w = Math.min(100, 26 + (m.dur || 0) * 2.2);      // 越长的条越宽，一眼看出长短
  return `<div class="cr-voice" data-voice="${m.id}" data-vurl="/api/chat/file/${m.file_id}?inline=1" style="width:${w}%">
      <span class="cr-vplay">${artEm('▶')}</span>
      <span class="cr-vbar"><i></i></span>
      <span class="cr-vsec">${voiceFmt(m.dur)}</span>
    </div>${m.text ? `<div class="cr-vtext">${esc(m.text)}</div>` : ''}`;
}
