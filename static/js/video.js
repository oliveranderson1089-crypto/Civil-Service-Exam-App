/* 每日新闻视频 + APP 内播放器（播放器只服务于它）
 *
 * 由 app.js 按它自己的区段边界切出（原 L3312-3748）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, artEm, c, deskMsg, esc, fmtDay, push, toast */

/* ============= 每日新闻视频（抓 → AI 按公考价值筛 → 只留最值得看的）=============
   信源全是**白名单里的官方媒体**：央视网（新闻联播/焦点访谈/东方时空/今日关注/环球视线，
   走 api.cntv.cn 的开放 JSON 接口）+ 川观新闻（四川日报社）。
   为什么不接受「任意博主」：**没法自动确认一个账号是不是真的**，那等于把把关的活儿丢给用户。
   核心价值不是「有视频看」，而是**帮你把不值得看的滤掉** —— 每条都说清「为什么值得看」。 */
let vdBoard = '', vdPoll = 0;

function openVideos() {
  push({ view: 'videos', title: '每日新闻视频' });
  loadVideos();
}
async function loadVideos() {
  const box = $('#vd-list');
  box.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const q = vdBoard === 'star' ? '?star=1' : (vdBoard ? '?board=' + encodeURIComponent(vdBoard) : '');
    const d = await api('/api/videos' + q);
    $('#vd-last').textContent = d.last ? `· 最近更新 ${fmtDay(d.last)}` : '';
    document.querySelectorAll('#vd-tabs .chip').forEach(c => {
      const k = c.dataset.vdb;
      c.classList.toggle('active', k === vdBoard);
      if (k && k !== 'star') {
        const n = (d.counts || {})[k] || 0;
        c.textContent = c.textContent.replace(/\s\d+$/, '') + (n ? ' ' + n : '');
      } else if (k === 'star') {
        c.textContent = '⭐ 收藏' + (d.n_star ? ' ' + d.n_star : '');
      }
    });
    if (!d.items.length) {
      box.innerHTML = vdBoard === 'star'
        ? '<p class="empty">还没收藏。看到有用的点 ☆ 收起来，做申论素材。</p>'
        : '<p class="empty">还没有视频。点上面「手动刷新」抓一批，或等每天 07:20 自动更新。</p>';
      return;
    }
    box.innerHTML = d.items.map(v => {
      // 封面用 <img referrerpolicy=no-referrer>，不用 CSS 背景图 ——
      // B 站图床（i*.hdslb.com）有防盗链：**带我们域名的 Referer 会 403**，不带 Referer 反而 200。
      // CSS background-image 没法去掉 Referer，只有 <img referrerpolicy> 能。央视/川观封面不受影响。
      return `<div class="vd-card">
        <button class="vd-cover" data-vdplay="${v.id}">
          ${v.cover ? `<img class="vd-cover-img" src="${esc(v.cover)}" referrerpolicy="no-referrer" alt="">` : ''}
          <span class="vd-play">▶</span>
          ${v.duration ? `<span class="vd-dur">${esc(v.duration)}</span>` : ''}
        </button>
        <div class="vd-body">
          <div class="vd-top">
            <span class="vd-board vd-${esc(v.board)}">${esc(v.board)}</span>
            <span class="vd-col">${esc(v.column_name || '')}</span>
            <span class="vd-score" title="AI 打的「值得看」分">★ ${v.score}</span>
            <button class="vd-star${v.starred ? ' on' : ''}" data-vdstar="${v.id}"
              title="收藏（可当申论素材）">${v.starred ? '★' : '☆'}</button>
          </div>
          <a class="vd-title" href="#" data-vdplay="${v.id}">${esc(v.title)}</a>
          ${v.why ? `<div class="vd-why"><b>为什么值得看</b>${esc(v.why)}</div>` : ''}
          ${(v.tags || []).length ? `<div class="vd-tags">${v.tags.map(t =>
            `<span>${esc(t)}</span>`).join('')}</div>` : ''}
          <div class="vd-foot">
            <span class="vd-src-n">📺 ${esc(v.source || '')}</span>
            <span>${esc((v.pub_date || '').slice(0, 16))}</span>
            ${v.brief ? `<button class="vd-more" data-vdbrief="${v.id}">内容提要 ▾</button>` : ''}
          </div>
          ${v.brief ? `<div class="vd-brief hidden" id="vdb-${v.id}">${esc(v.brief)}</div>` : ''}
        </div>
      </div>`;
    }).join('');
    // 封面加载完再淡入（B 站封面要一两秒，硬闪出来不好看）
    box.querySelectorAll('.vd-cover-img').forEach(im => {
      if (im.complete && im.naturalWidth) im.classList.add('vd-loaded');
      else im.addEventListener('load', () => im.classList.add('vd-loaded'), { once: true });
    });
  } catch (e) { box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
$('#vd-tabs').addEventListener('click', e => {
  const c = e.target.closest('[data-vdb]'); if (!c) return;
  vdBoard = c.dataset.vdb;
  loadVideos();
});
$('#vd-list').addEventListener('click', async e => {
  const p = e.target.closest('[data-vdplay]');
  if (p) { e.preventDefault(); playVideo(p.dataset.vdplay); return; }
  const b = e.target.closest('[data-vdbrief]');
  if (b) {
    const box = $('#vdb-' + b.dataset.vdbrief);
    const open = box.classList.toggle('hidden');
    b.textContent = open ? '内容提要 ▾' : '收起 ▴';
    return;
  }
  const s = e.target.closest('[data-vdstar]');
  if (s) {
    e.preventDefault();
    s.disabled = true;
    try {
      const r = await api('/api/videos/' + s.dataset.vdstar + '/star', { method: 'POST' });
      s.textContent = r.starred ? '★' : '☆';
      s.classList.toggle('on', r.starred);
      toast(r.starred ? '已收藏（可当申论素材）' : '已取消收藏');
      if (vdBoard === 'star') loadVideos();
    } catch (err) { toast(err.message, true); }
    s.disabled = false;
  }
});
$('#vd-refresh').onclick = async () => {
  const b = $('#vd-refresh'); b.disabled = true;
  $('#vd-msg').textContent = '正在抓取（要开无头浏览器渲染川观新闻，约 1 分钟）…';
  try {
    const d = await api('/api/videos/refresh', { method: 'POST' });
    clearInterval(vdPoll);
    vdPoll = setInterval(async () => {
      try {
        const t = await api('/api/write/task/' + d.task);      // 后台任务表是共用的
        $('#vd-msg').textContent = t.message || '';
        if (t.status === 'done' || t.status === 'error') {
          clearInterval(vdPoll); vdPoll = 0;
          b.disabled = false;
          loadVideos();
          toast(t.status === 'done' ? '刷新完成' : t.message, t.status !== 'done');
        }
      } catch (_) { clearInterval(vdPoll); vdPoll = 0; b.disabled = false; }
    }, 3000);
  } catch (e) { toast(e.message, true); b.disabled = false; $('#vd-msg').textContent = ''; }
};

/* ---------------- APP 内播放器 ----------------
   以前点播放是往外跳浏览器（桌面壳里还跳不动 —— WebKit 把新窗口请求吞了）。现在自己放。

   三种片源，四种放法：
     央视  多数给的是**分段 mp4**（每段 5 分钟，一集切 4~6 段）。`<video>` 原生就能放 ——
           实测桌面壳那个 WebKit 也吃得下，所以优先走它。代价是得自己把几段接成一条
           连续的时间轴：进度条走的是**全片的秒数**，拖动时先算落在第几段、再跳到段内偏移；
           一段放完自动接下一段。
           但不是每条都有 mp4（《今日关注》四个画质档的地址全是空的），那种只能走 HLS：
           WebKit 和 Chrome 都不原生认 m3u8（实测 code=4 放不了），所以用 hls.js —— 它靠 MSE，
           而 MSE 在真壳里实测是有的。hls.js 放在我们自己域下，用到才加载。
     B站   嵌官方播放器（人家的 iframe 没有任何嵌入限制，实测可用）。
     川观   抓取时渲染页面截到直链就能放；没截到就只能跳出去（会老实说明）。       */
let vpS = null;                                  // 播放器状态（同一时刻只会有一个）
let hlsLib = null;                               // hls.js 用到才加载（400KB，别让没看视频的人也扛）

function loadHls() {
  if (hlsLib) return hlsLib;
  hlsLib = new Promise((ok, no) => {
    if (window.Hls) return ok(window.Hls);
    const s = document.createElement('script');
    s.src = '/vendor/hls.min.js';          // 静态文件挂在根上（app.py 里 static_folder=None），不是 /static/

    s.onload = () => ok(window.Hls);
    s.onerror = () => { hlsLib = null; no(new Error('播放组件加载失败')); };
    document.head.appendChild(s);
  });
  return hlsLib;
}

function vpFmt(s) {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  const p = n => String(n).padStart(2, '0');
  return h ? `${h}:${p(m)}:${p(x)}` : `${m}:${p(x)}`;
}

async function playVideo(id) {
  let d;
  try { d = await api('/api/videos/' + id + '/play'); }
  catch (e) { toast(e.message, true); return; }

  if (d.mode === 'external') {                   // 放不了就老实跳出去，别假装能放
    toast(d.note || '这条只能在浏览器里看');
    openOut(d.url);
    return;
  }
  // B 站是 iframe 官方播放器 —— 浏览器里能放，但桌面壳(WebKitGTK)缺 B 站要的编解码器，会黑屏
  // 且它自己会弹外部播放器。所以桌面壳里 B 站直接一键跳系统浏览器，不整那个黑屏。
  // （B 站的流是 DASH、约 2 小时过期、有风控，没法像央视那样取直连流内部播，只能这样。）
  if (d.mode === 'iframe' && window.__desktop) {
    toast('B 站视频在浏览器里打开（桌面版放不了 B 站内嵌播放器）');
    openOut(d.url);
    return;
  }
  vpClose();
  const wrap = document.createElement('div');
  wrap.className = 'vp-mask';
  wrap.innerHTML = `
    <div class="vp-box" role="dialog" aria-label="视频播放">
      <div class="vp-head">
        <div class="vp-t">${esc(d.title || '')}</div>
        <div class="vp-src">${esc(d.source || '')}</div>
        <button class="vp-x" title="关闭（Esc）">${artEm('✕')}</button>
      </div>
      <div class="vp-stage">
        ${d.mode === 'iframe'
      ? `<iframe class="vp-if" src="${esc(d.embed)}" allowfullscreen scrolling="no"
             frameborder="0" allow="autoplay; fullscreen; encrypted-media"></iframe>`
      : `<video class="vp-v" playsinline preload="auto"></video>
           <div class="vp-spin hidden">缓冲中…</div>
           <button class="vp-big" title="播放/暂停">▶</button>`}
      </div>
      ${d.mode === 'iframe' ? '' : `
      <div class="vp-bar">
        <button class="vp-pp" title="播放/暂停（空格）">▶</button>
        <span class="vp-time">0:00</span>
        <input class="vp-seek" type="range" min="0" max="1000" value="0" step="1"
               aria-label="进度">
        <span class="vp-total">${vpFmt(d.total)}</span>
        <select class="vp-rate" title="倍速">
          <option value="0.75">0.75×</option><option value="1" selected>1×</option>
          <option value="1.25">1.25×</option><option value="1.5">1.5×</option>
          <option value="2">2×</option>
        </select>
        <button class="vp-fs" title="全屏">${artEm('⛶')}</button>
      </div>`}
      <div class="vp-foot">
        <a href="#" class="vp-out">在浏览器里打开 ↗</a>
      </div>
    </div>`;
  document.body.appendChild(wrap);

  wrap.querySelector('.vp-x').onclick = vpClose;
  wrap.querySelector('.vp-out').onclick = ev => { ev.preventDefault(); openOut(d.url); };
  wrap.addEventListener('click', ev => { if (ev.target === wrap) vpClose(); });
  vpS = { wrap, mode: d.mode, esc: null };
  vpS.esc = ev => { if (ev.key === 'Escape') vpClose(); };
  document.addEventListener('keydown', vpS.esc);

  if (d.mode === 'iframe') return;               // B 站的播放器自己管，我们不插手
  vpMedia(wrap, d);
}

function vpMedia(wrap, d) {
  const stage = wrap.querySelector('.vp-stage');
  const seek = wrap.querySelector('.vp-seek');
  const tEl = wrap.querySelector('.vp-time');
  const totEl = wrap.querySelector('.vp-total');
  const pp = wrap.querySelector('.vp-pp');
  const big = wrap.querySelector('.vp-big');
  const spin = wrap.querySelector('.vp-spin');

  // HLS 只有一条连续的流，没有分段 —— 但为了不写两套播放逻辑，
  // 把它当成「只有一段的片子」，后面的时间轴/进度条代码就完全通用了。
  const hls = d.mode === 'hls';
  const chs = hls ? [{ url: d.src, dur: d.total || 0 }] : (d.chapters || []);
  const off = [];
  let acc = 0;
  chs.forEach(c => { off.push(acc); acc += c.dur || 0; });

  // 分段 mp4（央视一集切 4~6 段）切段时，单个 <video> 换 src 会黑屏一下。
  // 双缓冲消除它：主视频在放第 i 段时，**副视频后台预载第 i+1 段**（preload=auto，
  // 首帧早就解好了）；一段放完不重新加载，而是把副视频顶成主视频、直接播 —— 无缝。
  const va = wrap.querySelector('.vp-v');
  const multi = !hls && chs.length > 1;
  let vb = null;
  if (multi) {
    vb = document.createElement('video');
    vb.className = 'vp-v vp-hidden';
    vb.playsInline = true; vb.preload = 'auto';
    stage.insertBefore(vb, va.nextSibling);
  }
  const S = Object.assign(vpS, {
    v: va, vb, chs, off, cur: -1, preCh: -1, total: d.total || 0, seeking: false, hls: null,
  });

  function gnow() { return (S.off[S.cur] || 0) + (S.v.currentTime || 0); }
  function paint() {
    if (S.seeking) return;
    const g = gnow();
    tEl.textContent = vpFmt(g);
    if (S.total > 0) seek.value = Math.round(g / S.total * 1000);
  }
  function showActive() {                         // 主视频可见、副视频藏起来
    S.v.classList.remove('vp-hidden');
    if (S.vb) S.vb.classList.add('vp-hidden');
  }
  function ready(at, go) {
    if (!S.total && isFinite(S.v.duration)) { S.total = S.v.duration; totEl.textContent = vpFmt(S.total); }
    if (at) S.v.currentTime = at;
    if (go) S.v.play().catch(() => { });
  }
  function prefetch(j) {                          // 后台预载第 j 段到副视频（只对分段 mp4）
    if (!multi || !S.vb || j < 0 || j >= chs.length || S.preCh === j) return;
    S.preCh = j;
    S.vb.src = chs[j].url;
    S.vb.load();
  }
  function load(i, at, go) {                      // 把第 i 段装进**主视频**（首段、跨段拖动走这里）
    S.cur = i;
    if (hls) {                                    // m3u8：WebKit / Chrome 都不原生认，得靠 hls.js
      spin.classList.remove('hidden');
      loadHls().then(Hls => {
        if (!vpS || vpS.v !== S.v) return;        // 加载期间用户关掉了
        if (S.hls) S.hls.destroy();
        S.hls = new Hls({ maxBufferLength: 30 });
        S.hls.loadSource(chs[i].url);
        S.hls.attachMedia(S.v);
        S.hls.on(Hls.Events.MANIFEST_PARSED, () => ready(at, go));
        S.hls.on(Hls.Events.ERROR, (_e, data) => {
          if (!data.fatal) return;
          spin.classList.add('hidden');
          toast('这条流加载失败了，可以点「在浏览器里打开」', true);
        });
      }).catch(e => { spin.classList.add('hidden'); toast(e.message, true); });
      return;
    }
    showActive();
    S.v.src = chs[i].url;
    S.v.load();
    S.preCh = -1;                                 // 换了主视频，之前预载的作废
    S.v.addEventListener('loadedmetadata', () => { ready(at, go); prefetch(i + 1); }, { once: true });
  }
  function swap(next) {                           // 副视频（已预载好 next 段）顶成主视频，无缝续播
    unbind(S.v);
    const old = S.v;
    S.v = S.vb; S.vb = old;
    S.cur = next;
    showActive();
    bind();
    try { S.v.currentTime = 0; } catch (_) { /* 视频还没就绪，跳到 0 秒没意义也没影响 */ }
    S.v.play().catch(() => { });
    pp.textContent = big.textContent = '⏸'; big.classList.add('hide');
    S.preCh = -1;
    prefetch(next + 1);                           // 再预载下一段
  }
  function advance() {                            // 一段放完
    const next = S.cur + 1;
    if (next >= chs.length) { pp.textContent = big.textContent = '▶'; big.classList.remove('hide'); return; }
    if (multi && S.vb && S.preCh === next && S.vb.readyState >= 2) swap(next);   // 预载好了 → 无缝切
    else load(next, 0, true);                     // 没来得及预载 → 老实重载
  }
  function seekTo(g) {
    g = Math.max(0, Math.min((S.total || 1) - 0.4, g));
    let i = 0;
    while (i < S.off.length - 1 && g >= S.off[i + 1]) i++;
    const local = g - (S.off[i] || 0);
    if (i !== S.cur) load(i, local, !S.v.paused);
    else S.v.currentTime = local;
  }

  const toggle = () => { const v = S.v; v.paused ? v.play().catch(() => { }) : v.pause(); };
  function bind() {                               // 播放事件都绑在**当前主视频**上（切换时要跟着走）
    const v = S.v;
    v.onclick = toggle;
    v.onplay = () => { pp.textContent = big.textContent = '⏸'; big.classList.add('hide'); };
    v.onpause = () => { pp.textContent = big.textContent = '▶'; big.classList.remove('hide'); };
    v.ontimeupdate = paint;
    v.onwaiting = () => spin.classList.remove('hidden');
    v.onplaying = () => spin.classList.add('hidden');
    v.oncanplay = () => spin.classList.add('hidden');
    v.onended = advance;
    v.onerror = () => { spin.classList.add('hidden'); toast('这一段加载失败了，可以点「在浏览器里打开」', true); };
  }
  function unbind(v) {
    v.onclick = v.onplay = v.onpause = v.ontimeupdate = v.onwaiting =
      v.onplaying = v.oncanplay = v.onended = v.onerror = null;
  }
  bind();
  pp.onclick = toggle;
  big.onclick = toggle;
  seek.oninput = () => {
    S.seeking = true;
    tEl.textContent = vpFmt(seek.value / 1000 * S.total);
  };
  seek.onchange = () => { S.seeking = false; seekTo(seek.value / 1000 * S.total); };
  wrap.querySelector('.vp-rate').onchange = e => { S.v.playbackRate = +e.target.value; if (S.vb) S.vb.playbackRate = +e.target.value; };
  wrap.querySelector('.vp-fs').onclick = () => vpToggleFs(stage, S.v);
  // 空格播放/暂停、左右各跳 10 秒（跟常见播放器一致）
  S.keys = e => {
    if (/^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || ''))) return;
    if (e.key === ' ') { e.preventDefault(); toggle(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); seekTo(gnow() + 10); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); seekTo(gnow() - 10); }
  };
  document.addEventListener('keydown', S.keys);

  load(0, 0, true);
}

/** 全屏切换。手机上这条路特别容易点了没反应，得按平台分开走：
 *   · 桌面 / 安卓 Chrome / APK：给 .vp-stage 整个 div 请求全屏 —— 我们自制的进度条/倍速一起进去。
 *     APK 的 WebView 要壳里接了 onShowCustomView 才生效（已在 4.4 加上）。
 *   · iOS Safari：div 根本不支持全屏，只有 <video> 元素的原生全屏能用（webkitEnterFullscreen）。
 * 顺带：横屏视频（央视/B站 16:9）进全屏时把手机转成横屏；竖屏视频（川观 720x1280）保持不动。 */
function vpToggleFs(stage, v) {
  const doc = document;
  if (doc.fullscreenElement || doc.webkitFullscreenElement) {
    (doc.exitFullscreen || doc.webkitExitFullscreen || function () { }).call(doc);
    return;
  }
  if (v.webkitDisplayingFullscreen) { try { v.webkitExitFullscreen(); } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ } return; }

  const req = stage.requestFullscreen || stage.webkitRequestFullscreen;
  if (req) {
    let p;
    try { p = req.call(stage); } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ }
    // 请求失败（比如 iOS 的 div 全屏）就退回 <video> 原生全屏
    if (p && p.catch) p.catch(() => vpVideoFs(v));
  } else {
    vpVideoFs(v);
  }
}
function vpVideoFs(v) {
  if (v.webkitEnterFullscreen) { try { v.webkitEnterFullscreen(); } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ } }
  else if (v.requestFullscreen) { v.requestFullscreen().catch(() => { }); }
}
// 进/出全屏时：横屏视频转屏 + 同步全屏按钮图标。锁屏方向要在全屏态里才允许，所以放这。
document.addEventListener('fullscreenchange', () => {
  const on = !!document.fullscreenElement;
  if (vpS && vpS.wrap) {
    const b = vpS.wrap.querySelector('.vp-fs');
    if (b) { b.classList.toggle('on', on); b.title = on ? '退出全屏' : '全屏'; }
  }
  try {
    if (on && vpS && vpS.v && vpS.v.videoWidth > vpS.v.videoHeight
        && screen.orientation && screen.orientation.lock) {
      screen.orientation.lock('landscape').catch(() => { });
    } else if (!on && screen.orientation && screen.orientation.unlock) {
      screen.orientation.unlock();
    }
  } catch (_) { /* 这台设备不支持锁定横屏，就按竖屏放 */ }
});

function vpClose() {
  if (!vpS) return;
  const v = vpS.v;
  if (vpS.hls) { try { vpS.hls.destroy(); } catch (_) { /* hls 实例已经销毁过了 */ } }   // 不销毁会一直在后台下分片
  if (vpS.vb) { try { vpS.vb.pause(); vpS.vb.removeAttribute('src'); vpS.vb.load(); } catch (_) { /* 播放器已经关了/没在放，停它本来就没事可做 */ } }  // 副视频也要停，否则后台还在下一段
  if (v) { try { v.pause(); v.removeAttribute('src'); v.load(); } catch (_) { /* 播放器已经关了/没在放，停它本来就没事可做 */ } }
  document.removeEventListener('keydown', vpS.esc);
  if (vpS.keys) document.removeEventListener('keydown', vpS.keys);
  if (document.fullscreenElement) { (document.exitFullscreen || function () { }).call(document); }
  vpS.wrap.remove();
  vpS = null;
}

/** 真要跳出去的时候才用（播放器放不了的那种）。桌面壳靠消息桥叫系统浏览器。 */
function openOut(url) {
  if (!url) return;
  if (window.__desktop) deskMsg({ a: 'open', url });
  else window.open(url, '_blank', 'noopener');
}
