/* AI 助手 —— 一份组件，两种外壳
 *
 * 2026-08 改版（评审页方案 A3 + M1）。改之前这块有四个平级视图（首页 / 项目 /
 * 项目详情 / 会话）轮流显示，换个会话要走两层；现在会话列表是**一栏**：
 *   · 电脑端「侧栏」（dock）：列表作抽屉滑出，做题时右半屏问一句
 *   · 电脑端「工作台」（⛶ 切过去）：列表常驻左侧，右侧再多一栏「AI 用了我哪些数据」
 *   · 手机端：全屏对话，点标题下拉切会话，➕ 的工具面板占位在键盘处
 * 三种壳共用同一批组件（消息、输入栏、轨迹卡、会话行），只有外面那层不同 ——
 * 靠 #ai-panel[data-shell] 切，不是三份代码。
 *
 * 滚动一律走 js/convo.js 的滚动契约：贴着底才自动跟，翻上去了就出「↓ N 条新消息」。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, anchorMenu, api, appConfirm, applyPush, appPrompt, artEm, avoidFab, CAN_ABORT,
   composing, compressImage, convoAvatar, convoStick, createDock, errMsg, esc, getAppClip,
   growAndSync, IS_MOBILE,
   loadClassics, loadDaily, loadEntries, loadFeed, loadPlan, loadWrongq, lsGet, lsSet,
   mdToHtml, navHomeCard, openAiChatMenu, stack, toast, uiError, voiceAsrEnabled,
   voiceInsert, voiceLive, voiceRecord, voiceSupported, voiceToText, voiceWhyNot */

/* ================= AI 助手 ================= */
let aiMsgs = [], aiBusy = false, aiChatId = null, aiProjectId = null;
/* 晚到的回调先确认窗口还在。这几处（开场白、会话列表、档位小字、记忆）都是
   「发出去就不管」的请求，回来时用户可能已经关了面板、甚至关了页面 ——
   再去摸 DOM 在桌面壳里是一条无源的报错，在测试里是「测试结束后的异步活动」。 */
function aiAlive() { return typeof document !== 'undefined' && !!(document && document.querySelector); }
/* 项目图标：sync.js 的「移动到项目」菜单也用它，所以留在这儿当共用常量 */
const AI_FOLDER = '<svg class="ai-folder" viewBox="0 0 48 48"><rect x="2" y="2" width="44" height="44" rx="13" fill="#5b6cf0"/><path fill="#7d8cf8" opacity=".5" d="M2 15C2 7.8 7.8 2 15 2h18c7.2 0 13 5.8 13 13v2H2z"/><rect x="11" y="11" width="11.5" height="11.5" rx="3.5" fill="#fff"/><rect x="25.5" y="11" width="11.5" height="11.5" rx="3.5" fill="#fff" opacity=".82"/><rect x="11" y="25.5" width="11.5" height="11.5" rx="3.5" fill="#fff" opacity=".82"/><circle cx="31.2" cy="31.2" r="5.8" fill="#ffd66b"/></svg>';

/* ---------------- 外壳：停靠侧栏 / 全屏工作台 ---------------- */
let aiDk = null;
function aiInitDock() {
  if (aiDk) return;
  $('#ai-shot').classList.toggle('hidden', !window.__desktopShot);   // 截图只有桌面版有
  aiVoiceAvail();                    // 麦克风按钮该不该出现（见下面「语音输入」那节）
  aiDk = createDock($('#ai-panel'), 'aiDock', IS_MOBILE ? 'bottom' : 'right', aiSyncShell);
  document.querySelectorAll('#ai-panel .ai-dock').forEach(b =>
    b.addEventListener('pointerdown', (e) => aiDk.dockDrag(e)));
  document.querySelectorAll('#ai-panel .ai-full').forEach(b =>
    b.onclick = () => { aiDk.toggleFull(); aiSyncShell(); });
  aiSyncShell();
}
/* 壳跟着停靠状态走：占满整屏（dk-full）且不是手机 → 工作台（列表常驻 + 右上下文栏），
   否则就是侧栏。手机端永远是「全屏对话 + 抽屉」那一套，不给三栏。 */
function aiSyncShell() {
  const p = $('#ai-panel');
  const desk = !IS_MOBILE && p.classList.contains('dk-full');
  p.dataset.shell = desk ? 'desk' : 'dock';
  if (desk) aiSideClose(true);        // 工作台里列表是常驻的，不需要抽屉那层遮罩
  renderAiCtx();
}
/* 会话抽屉（侧栏壳 / 手机端）。手机端点标题也是开它 —— 标题本身就是切会话的入口。 */
function aiSideOpen() {
  if ($('#ai-panel').dataset.shell === 'desk') return;
  $('#ai-panel').classList.add('side-on');
  $('#ai-sidemask').classList.remove('hidden');
  if (!IS_MOBILE) setTimeout(() => $('#aih-search').focus(), 80);
}
function aiSideClose(quiet) {
  $('#ai-panel').classList.remove('side-on');
  $('#ai-sidemask').classList.add('hidden');
  if (!quiet && IS_MOBILE) $('#ai-text').blur();
}
function aiSideToggle() {
  if ($('#ai-panel').classList.contains('side-on')) aiSideClose();
  else aiSideOpen();
}

async function openAI(preset) {
  aiInitDock();
  $('#ai-panel').classList.remove('hidden');
  aiDk.apply(false);
  aiSyncShell();
  /* 落点是输入框，不是列表：最高频的动作是「问一句」。列表随时能从 ☰ / 标题拉出来。
     （旧版打开先看到一张列表，要问一句得先点「＋ 新对话」——AD14） */
  if (!aiChatId || preset) await aiNewChat(preset ? null : aiProjectId);
  if (preset) { $('#ai-text').value = preset; aiGrow(); }
  loadAiHome();
  aiSyncClipChip();       // 面板常常是「复制完」才打开的，光等 appclip 事件会漏掉这一次
  setTimeout(() => { const el = aiAlive() && $('#ai-text'); if (el && !IS_MOBILE) el.focus(); }, 60);
}

/* ---------------- 会话与项目 ---------------- */
async function aiNewChat(projectId) {
  // 懒创建：先进界面，第一次发送消息时才真正建会话（不产生空记录）
  aiChatId = null; aiProjectId = projectId || null; aiMsgs = [];
  aiTraceOpen = {}; aiStreamText = ''; aiBusy = false; aiLastMs = 0;
  aiLoadOpener();
  const p = (($('#ai-panel')._projects) || []).find(x => x.id === aiProjectId);
  aiSetTitle(p ? p.name + ' · 新对话' : '新对话');
  aiSideClose(true); aiStick().seen(); renderAI(); renderAiList();
  setTimeout(() => { const el = aiAlive() && $('#ai-text'); if (el) el.focus(); }, 60);
}
async function aiOpenChat(id) {
  try {
    const d = await api('/api/aichat/chats/' + id);
    aiChatId = d.id; aiMsgs = d.msgs; aiProjectId = d.project_id;
    aiTier = d.tier || 'fast'; aiTraceOpen = {}; aiStreamText = ''; aiBusy = false; aiLastMs = 0;
    renderAiTier();
    aiSetTitle(d.title || '对话');
    aiSideClose(true); aiStick().seen(); renderAI(); renderAiList();
  } catch (e) { toast(errMsg(e), true); }
}
/* 标题下面那行小字说清「哪个档位、第几轮、这轮多久」——
   旧版档位是标题栏里 11.5px 的小胶囊，切了什么、慢在哪都看不出来（AD12）。 */
let aiLastMs = 0;
function aiSetTitle(t) {
  $('#aic-title').textContent = t || '新对话';
  aiSetSub();
}
function aiSetSub(extra) {
  const rounds = aiMsgs.filter(m => m.role === 'user').length;
  const bits = [aiTier === 'pro' ? '深度档' : '快档'];
  if (rounds) bits.push('第 ' + rounds + ' 轮');
  if (aiLastMs) bits.push('用时 ' + (aiLastMs / 1000).toFixed(1) + 's');
  if (extra) bits.push(extra);
  const p = (($('#ai-panel')._projects) || []).find(x => x.id === aiProjectId);
  $('#aic-sub').textContent = (p ? '📁 ' + p.name + ' · ' : '') + bits.join(' · ');
}

let aiHomeQ = '', aiHomeTimer = 0;
async function loadAiHome() {
  try {
    const d = await api('/api/aichat/home' + (aiHomeQ ? '?q=' + encodeURIComponent(aiHomeQ) : ''));
    if (!aiAlive()) return;
    $('#ai-panel')._projects = d.projects;
    $('#ai-panel')._chats = d.chats;
    renderAiList();
    aiSetSub();
  } catch (e) { toast(errMsg(e), true); }
}
/* 会话按时间分组（今天 / 昨天 / 近 7 天 / 更早），置顶的单独一组排最上，项目在最前面。
   旧版是一张不分组的长列表，翻旧对话只能一路滚（AD11）。 */
function aiDayGroup(s) {
  const day = String(s || '').slice(0, 10);
  if (!day) return '更早';
  const d = new Date(day + 'T00:00:00'), now = new Date();
  const days = Math.round((new Date(now.getFullYear(), now.getMonth(), now.getDate()) - d) / 86400000);
  if (days <= 0) return '今天';
  if (days === 1) return '昨天';
  if (days <= 7) return '近 7 天';
  if (days <= 30) return '近 30 天';
  return '更早';
}
function aiChatRow(c) {
  const on = c.id === aiChatId ? ' on' : '';
  const when = String(c.updated_at || '').slice(5, 16);
  return `<div class="ais-row${on}" data-aichat="${c.id}">
    ${convoAvatar(c.title || 'AI', '', 'ai', 'sm')}
    <div class="ais-m">
      <div class="ais-n">${c.starred ? '<span class="ais-pin" title="置顶">⭐</span>' : ''}${esc(c.title || '（新对话）')}</div>
      <div class="ais-p">${c.pname ? '<span class="ais-proj">' + esc(c.pname) + '</span> · ' : ''}${esc(when)}</div>
    </div>
    <button class="ais-more" data-aimenu="${c.id}" data-atitle="${esc(c.title || '')}"
      data-aproj="${c.project_id || ''}" data-astar="${c.starred ? 1 : 0}" title="更多">⋮</button>
  </div>`;
}
function renderAiList() {
  const box = $('#aih-recents'); if (!box) return;
  const projects = $('#ai-panel')._projects || [];
  const chats = $('#ai-panel')._chats || [];
  let html = '';
  if (!aiHomeQ && projects.length) {
    html += '<div class="ais-sec">' + AI_FOLDER + ' 项目 · ' + projects.length + '</div>';
    html += projects.map(p => `<div class="ais-row ais-projrow" data-aiproj="${p.id}">
      ${convoAvatar(p.name, '', 'group', 'sm')}
      <div class="ais-m"><div class="ais-n">${esc(p.name)}</div>
        <div class="ais-p">${p.cnt} 个对话${p.instructions ? ' · 有指令' : ''}</div></div>
      <button class="ais-more" data-aipdel="${p.id}" title="删除项目">✕</button>
    </div>`).join('');
  }
  if (aiHomeQ) html += '<div class="ais-sec">搜索结果 · ' + chats.length + '</div>';
  if (!chats.length) {
    html += `<p class="ais-empty">${aiHomeQ ? '没找到「' + esc(aiHomeQ) + '」' : '还没有对话。上面「＋ 新对话」开始。'}</p>`;
  } else if (aiHomeQ) {
    html += chats.map(aiChatRow).join('');
  } else {
    const star = chats.filter(c => c.starred), rest = chats.filter(c => !c.starred);
    if (star.length) html += '<div class="ais-sec">置顶</div>' + star.map(aiChatRow).join('');
    let cur = '';
    rest.forEach(c => {
      const g = aiDayGroup(c.updated_at);
      if (g !== cur) { cur = g; html += '<div class="ais-sec">' + g + '</div>'; }
      html += aiChatRow(c);
    });
  }
  box.innerHTML = html;
}
/* 项目：点项目名 = 只看这个项目下的对话（空项目直接开新对话）。
   旧版这是一个独立视图，进去还要再退回来两层。 */
let aiCurProject = null;
function openAiProject(pid) {
  const p = ($('#ai-panel')._projects || []).find(x => x.id === pid);
  if (!p) return;
  const chats = ($('#ai-panel')._chats || []).filter(c => c.project_id === pid);
  aiCurProject = p;
  aiHomeQ = ''; $('#aih-search').value = '';
  /* 空项目以前是「点进去直接开新对话」，于是它的设置永远够不到 —— 而空项目恰恰
     是最需要先把指令写好的那个。现在照常显示项目页，只是列表位置换成一句话。 */
  $('#aih-recents').innerHTML =
    `<div class="ais-sec">${AI_FOLDER} ${esc(p.name)}</div>` +
    (p.instructions ? `<p class="ais-tip">${artEm('📋')} ${esc(p.instructions)}</p>` : '') +
    (p.files ? `<p class="ais-tip">${artEm('📎')} 挂着 ${p.files} 份参考资料，
       这个项目下的每个对话都读得到</p>` : '') +
    `<button class="ais-new ais-subnew" id="aipd-set">${artEm('⚙')} 项目设置（指令 / 参考资料）</button>` +
    '<button class="ais-new ais-subnew" id="aipd-new">＋ 在这个项目下开新对话</button>' +
    (chats.length ? chats.map(aiChatRow).join('')
      : '<p class="ais-empty">这个项目下还没有对话。</p>') +
    '<button class="ais-back" id="ais-back">‹ 回到全部对话</button>';
}

/* ---------------- 项目设置：指令是这个项目每一轮的开场白，得随时改得动 ---------------- */
async function openAiProjSet(pid) {
  const p = ($('#ai-panel')._projects || []).find(x => x.id === pid);
  if (!p) return;
  const box = $('#ai-projsheet');
  box.dataset.pid = pid;
  box.classList.remove('hidden');
  box.innerHTML = `<div class="cp-box"><div class="cp-head">项目设置<button data-psx>✕</button></div>
    <div class="cp-list">
      <label class="ps-l">项目名</label>
      <input id="ps-name" maxlength="60" value="${esc(p.name || '')}">
      <label class="ps-l">自定义指令</label>
      <p class="mem-tip">这段话会加在<b>这个项目</b>每一轮对话的最前面。留空就是不加。</p>
      <textarea id="ps-ins" rows="5" maxlength="4000"
        placeholder="例：你是申论阅卷老师，对我提交的答案按采分点批改打分，先给分再说扣在哪">${esc(p.instructions || '')}</textarea>
      <label class="ps-l">参考资料</label>
      <p class="mem-tip">挂在<b>项目</b>上：这个项目下的<b>每一个对话</b>都读得到，
        AI 需要时会自己去翻（跟输入框那个回形针不一样，那个只属于当时那一次对话）。
        可以直接传 PDF / Word / 图片，也可以粘一段文字。大文件不会整段塞进对话，
        AI 会按需一段段读。</p>
      <div id="ps-files"><p class="empty">加载中…</p></div>
      <input type="file" id="ps-upfile" class="hidden"
        accept=".pdf,.doc,.docx,.txt,.md,.ppt,.pptx,.xls,.xlsx,image/*">
    </div>
    <div class="mem-add"><button id="ps-addfile">＋ 传文件</button>
      <button id="ps-addtext">＋ 粘贴文本</button>
      <button id="ps-save" class="primary">保存</button></div></div>`;
  await aiProjFiles(pid);        // await 着：调用方（和测试）能等到整个弹层真的画完
}
async function aiProjFiles(pid) {
  const box = $('#ai-projsheet').querySelector('#ps-files'); if (!box) return;
  try {
    const d = await api('/api/aichat/projects/' + pid + '/files');
    box.innerHTML = (d.files || []).length
      ? d.files.map(f => `<div class="ai-mem"><div class="c"><div class="t">${esc(f.name)}</div>
          <div class="s">${aiProjFileMeta(f)}</div></div>
          <button class="x" data-psfdel="${f.id}">✕</button></div>`).join('')
      : '<p class="empty">还没挂资料。</p>';
  } catch (e) { box.innerHTML = uiError(e); }
}
function aiProjFileMeta(f) {
  // 一行把「这份到底读进去了多少」说清楚。扫描件只认了前几页这件事**必须写在脸上**：
  // 不写的话，用户以为整本都挂上了，AI 却只看得到前 20 页，谁也不知道差在哪。
  const bits = [f.size + ' 字'];
  if (f.pages) bits.push(f.pages + ' 页');
  if (f.ocr_pages) bits.push('扫描件·已认前 ' + f.ocr_pages + ' 页，其余 AI 用到时现场识别');
  if (f.orig_name) bits.push(esc(f.orig_name));
  return bits.join(' · ');
}
async function aiProjUpload(pid, file) {
  if (!file) return;
  toast('正在读取「' + file.name + '」…');
  try {
    const fd = new FormData(); fd.append('file', file);
    const d = await api('/api/aichat/projects/' + pid + '/files/upload', { method: 'POST', body: fd });
    if (d.error) { toast(d.error, true); return; }
    await aiProjFiles(pid);
    toast(d.ocr_pages
      ? ('已挂上，但这是扫描件：先认了前 ' + d.ocr_pages + ' 页，后面的 AI 要用时会现场识别')
      : ('已挂上（' + (d.chars || 0) + ' 字），这个项目下的每个对话都读得到'), !!d.ocr_pages);
  } catch (err) { toast(errMsg(err), true); }
}
$('#ai-projsheet').addEventListener('change', e => {
  const inp = e.target.closest('#ps-upfile'); if (!inp) return;
  const f = inp.files[0]; inp.value = '';        // 清空：同一个文件连传两次也要触发
  aiProjUpload(+$('#ai-projsheet').dataset.pid, f);
});
$('#ai-projsheet').addEventListener('click', async e => {
  const box = $('#ai-projsheet'), pid = +box.dataset.pid;
  if (e.target.closest('[data-psx]') || e.target === box) { box.classList.add('hidden'); return; }
  const del = e.target.closest('[data-psfdel]');
  if (del) {
    if (!(await appConfirm('删掉这份参考资料？'))) return;
    try { await api('/api/aichat/projects/' + pid + '/files/' + del.dataset.psfdel, { method: 'DELETE' }); aiProjFiles(pid); }
    catch (err) { toast(errMsg(err), true); }
    return;
  }
  if (e.target.closest('#ps-addfile')) {
    $('#ps-upfile').click();
    return;
  }
  if (e.target.closest('#ps-addtext')) {
    const name = await appPrompt('资料名', '例：申论评分标准');
    if (!name || !name.trim()) return;
    const text = await appPrompt('内容（直接粘贴进来）', '');
    if (!text || !text.trim()) return;
    try {
      await api('/api/aichat/projects/' + pid + '/files', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), text: text })
      });
      aiProjFiles(pid);
    } catch (err) { toast(errMsg(err), true); }
    return;
  }
  if (e.target.closest('#ps-save')) {
    const name = ($('#ps-name').value || '').trim();
    if (!name) { toast('项目名不能为空', true); return; }
    try {
      await api('/api/aichat/projects/' + pid, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        // instructions 允许改成空串（= 这个项目不再加前缀），所以照原样发，别过滤掉空值
        body: JSON.stringify({ name: name, instructions: $('#ps-ins').value || '' })
      });
      box.classList.add('hidden');
      toast('已保存，下一轮对话就按新指令来');
      await loadAiHome();
      if (aiCurProject && aiCurProject.id === pid) openAiProject(pid);
      aiSetSub();                       // 标题下那行也带着项目名
    } catch (err) { toast(errMsg(err), true); }
  }
});

/* 主动开场：打开助手先给一句基于今天复习/错题的判断 + 几个可点的起手式。
   空白输入框是最大的使用门槛。这一条不调模型（数字本来就在库里），所以立刻就出来。 */
let aiOpener = null;
async function aiLoadOpener() {
  try { aiOpener = await api('/api/aichat/opener'); }
  catch (_) { aiOpener = null; }               // 拿不到就退回那句固定问候
  if (aiAlive() && !aiMsgs.length) renderAI();
}

/* ---------------- 消息渲染（K3 消息体系）---------------- */
let aiTraceOpen = {}, aiStickH = null, aiNewCount = 0;
function aiStick() {
  if (!aiStickH) aiStickH = convoStick($('#ai-msgs'), $('#ai-main'));
  return aiStickH;
}
/* 一轮工具调用的卡片：收起时一行「查了你的错题本 · 3 步」，点开看每一步调了什么、拿到什么。
   结果不再硬截 200 字（AD7）—— 长的先折起来，点「看全部」展开。 */
function aiTraceHtml(m, i) {
  const t = m.trace || [];
  if (!t.length) return '';
  const names = [...new Set(t.map(s => s.label || s.name))];
  const head = names.slice(0, 2).join('、') + (names.length > 2 ? ' 等' : '') + ' · ' + t.length + ' 步';
  const open = aiTraceOpen[i];
  return `<div class="ai-trace${open ? ' open' : ''}" data-trace="${i}">
    <div class="ai-th"><span class="ic">🔧</span><b>${esc(head)}</b><span class="ar">${open ? '收起 ▴' : '展开 ▾'}</span></div>
    ${open ? '<div class="ai-tb">' + t.map((s, n) => aiStepHtml(s, n)).join('') + '</div>' : ''}
  </div>`;
}
function aiStepHtml(s, n) {
  const bad = s.result && /失败|错误|未找到|没找到/.test(s.result);
  const args = s.args && Object.keys(s.args).length
    ? '（' + esc(Object.entries(s.args).filter(([k]) => k !== '_confirmed')
      .map(([k, v]) => k + '=' + String(v).slice(0, 40)).join('，')) + '）' : '';
  const r = String(s.result || '');
  const longR = r.length > 200;
  return `<div class="ai-step${bad ? ' bad' : ''}">
    <span class="n">${n + 1}</span>
    <span class="c"><span class="k">${esc(s.name || '')}</span>${args}
      <span class="r${longR ? ' clip' : ''}">${esc(r)}</span>
      ${longR ? '<button class="ai-rmore" type="button">看全部</button>' : ''}</span>
  </div>`;
}
/* 附件缩略图（AD5）：图片直接显示原图，文件给个类型角标。发出去之后气泡里也留着。 */
/* 这份附件是不是只读到了一半。抽取那一步就可能截（字数上限），扫描件还可能只 OCR 了
   前几页 —— 两种都得让用户看见：以前截了不吭声，AI 拿着半份资料给出的结论看着很确定，
   谁也不知道它压根没读完。 */
function aiAttCut(a) {
  if (!a) return '';
  const bits = [];
  const got = (a.text || '').length;
  if (a.total && a.total > got) bits.push('全文约 ' + a.total + ' 字，只读到前 ' + got + ' 字');
  if (a.pages && a.ocr_pages && a.pages > a.ocr_pages) bits.push('共 ' + a.pages + ' 页，只识别了前 ' + a.ocr_pages + ' 页');
  return bits.join('；');
}
function aiAttsHtml(atts, small) {
  if (!atts || !atts.length) return '';
  return '<div class="ai-attrow' + (small ? ' sm' : '') + '">' + atts.map((a, i) => {
    // pending = 本地这份还在压缩 / 上传 / 识别。先拿本地 objectURL 占住位子：
    // 这一段合起来常有几十秒（手机照片走隧道更久），中间一片空白的话，
    // 用户看到的就是「选完图没动静」，只会反复再选一次。
    const src = a.pending ? (a.url || '') : (a.image ? '/api/ai/img/' + encodeURIComponent(a.image) : '');
    const img = src ? `<img src="${esc(src)}" alt="">`
      : `<span class="ai-attic">${/\.pdf$/i.test(a.name || '') ? '📕' : '📄'}</span>`;
    const cut = aiAttCut(a);
    return `<span class="ai-att${cut ? ' cut' : ''}${a.pending ? ' busy' : ''}" title="${esc((a.name || '') + (cut ? '（' + cut + '）' : ''))}">
      ${img}<span class="nm">${a.pending ? '读取中…' : esc(a.name || '附件')}</span>
      ${cut ? '<span class="cutflag" aria-hidden="true">半</span>' : ''}
      ${(small || a.pending) ? '' : `<button class="x" data-aiattdel="${i}" title="移除">×</button>`}</span>`;
  }).join('') + '</div>';
}
function aiActsHtml(m, i, last) {
  if (aiBusy) return '';
  if (m.role === 'user') {
    return `<div class="ai-acts uacts" data-mi="${i}"><button data-act="edit">✎ 改问题</button>` +
      '<button data-act="copy">复制</button></div>';
  }
  /* 失败那条不给「复制/分支/存进积累」（没有内容可存），但**一定要给「重试」** ——
     以前这里返回空，用户只剩一句「请再发一次」，只能手动把刚才那句重打一遍。 */
  if (m.kind === 'error') {
    return last ? `<div class="ai-acts" data-mi="${i}"><button data-act="again">↻ 重试</button></div>` : '';
  }
  return `<div class="ai-acts" data-mi="${i}">
    <button data-act="copy">${artEm('📋')} 复制</button>
    ${last ? '<button data-act="retry">↻ 重答</button>' : ''}
    <button data-act="branch">⑂ 分支</button>
    <button data-act="keep">＋ 存进积累</button>
    <button data-act="drill">🎯 出两道题练</button>
  </div>`;
}
function renderAI() {
  const chips = (aiOpener && aiOpener.chips && aiOpener.chips.length) ? aiOpener.chips
    : ['我今天该复习什么？', '看看我的错题都错在哪', '「不孚众望」和「不负众望」怎么分', '帮我出两道言语题'];
  const openHtml = `<div class="ai-open">
      <div class="t">${esc((aiOpener && aiOpener.greet) || '我是你的公考 AI 助手 👋 讲知识点、出题、翻译古文、分析错题都行 —— 我还看得到你的收录、错题和复习进度。')}</div>
      <div class="a-chips">${chips.map(c => `<button class="a-chip" data-chip="${esc(c)}">${esc(c)}</button>`).join('')}</div>
    </div>`;

  $('#ai-msgs').innerHTML = (aiMsgs.length ? '' : openHtml)
    + aiMsgs.map((m, i) => {
      if (m.kind === 'tool') return aiTraceHtml(m, i);
      if (m.kind === 'reason') return aiReasonHtml(m, i);
      const last = i === aiMsgs.length - 1;
      if (m.role === 'user') {
        return `<div class="ai-row user">
          <div class="ai-bub">${aiAttsHtml(m.atts, true)}${esc(m.content)}</div>
          ${aiActsHtml(m, i, last)}</div>`;
      }
      const tag = `<div class="ai-tag">${convoAvatar('AI', '', 'ai', 'sm')}<span>助手</span>` +
        `<span class="dim">${m.tier === 'pro' ? '深度' : '快'}${m.ms ? ' · ' + (m.ms / 1000).toFixed(1) + 's' : ''}</span></div>`;
      const cont = (m.truncated && last && !aiBusy)
        ? '<div class="ai-contwrap"><button class="ai-contbtn" id="ai-continue">▸ 继续（上一轮没做完）</button></div>' : '';
      return `<div class="ai-row bot${m.kind === 'error' ? ' ai-err' : ''}">
        ${tag}<div class="ai-body">${mdToHtml(m.content)}</div>
        ${aiActsHtml(m, i, last)}${cont}</div>`;
    }).join('')
    + (aiReasonLive ? `<div class="ai-reason live open"><div class="rh">🧠 正在推理…</div><div class="rb" id="ai-reasonlive">${esc(aiReasonLive)}</div></div>` : '')
    + (aiStreamText ? `<div class="ai-row bot"><div class="ai-tag">${convoAvatar('AI', '', 'ai', 'sm')}<span>助手</span><span class="dim">正在写</span></div><div class="ai-body" id="ai-stream">${mdToHtml(aiStreamText)}</div></div>` : '')
    + (aiBusy && !aiStreamText ? aiWaitHtml() : '');

  aiCodeTools();
  /* 滚动：走共用的滚动契约（js/convo.js）。原先这里是无条件 `scrollTop = scrollHeight`，
     配上流式每 80 毫秒重绘一次，等于「你想往上翻，它每 80 毫秒把你拽回来一次」（AD1）。 */
  aiStick().follow(aiNewCount);
  aiNewCount = 0;
  $('#ai-send').disabled = aiBusy;
  $('#ai-panel').classList.toggle('ai-busy', aiBusy);   // 「停止生成」是固定件，见 CSS（AD8）
  aiTickStart();
  aiSetSub();
  renderAiCtx();
}
/* 等待态（K6）：三行骨架 + 阶段文案，比一行「思考中…」更能说明它在干嘛 */
function aiWaitHtml() {
  return `<div class="ai-row bot ai-wait" id="ai-typing">
    <div class="ai-tag">${convoAvatar('AI', '', 'ai', 'sm')}<span>助手</span><span class="dim" id="ai-phase">${esc(aiPhase || '思考中…')}</span></div>
    <div class="ai-body"><span class="ai-sk" style="width:86%"></span><span class="ai-sk" style="width:72%"></span><span class="ai-sk" style="width:48%"></span></div>
  </div>`;
}
/* 深度档的推理过程（AD6）：服务端本来就推 reasoning，以前只拿它改一句文案就丢了。
   现在实时写进一张可收起的卡，答完自动折起来 —— 想看的时候点开。 */
let aiReasonLive = '';
function aiReasonHtml(m, i) {
  const open = aiTraceOpen['r' + i];
  const kb = Math.max(0.1, Math.round((m.content || '').length / 100) / 10);
  return `<div class="ai-reason${open ? ' open' : ''}" data-reason="${i}">
    <div class="rh">🧠 推理过程 · ${kb}k 字<span class="ar">${open ? '收起 ▴' : '展开 ▾'}</span></div>
    ${open ? '<div class="rb">' + esc(m.content) + '</div>' : ''}
  </div>`;
}
/* 代码块 / 公式各自带复制（AD9）。渲染完补挂，不进 mdToHtml —— 那是共用的 Markdown 渲染器，
   聊天、小记、阅读器都用它，不该为 AI 面板长出一颗按钮。 */
function aiCodeTools() {
  $('#ai-msgs').querySelectorAll('.ai-body pre.md-code').forEach(pre => {
    if (pre.querySelector('.ai-copybtn')) return;
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'ai-copybtn'; b.textContent = '复制';
    const code = pre.textContent;
    b.addEventListener('click', async (e) => {
      e.stopPropagation();
      try { await navigator.clipboard.writeText(code); b.textContent = '已复制'; }
      catch (_) { b.textContent = '复制不了'; }
      setTimeout(() => { b.textContent = '复制'; }, 1500);
    });
    pre.appendChild(b);
  });
}
/* 右上下文栏（工作台壳）：本轮工具轨迹 + 长期记忆。
   「AI 用了我哪些数据」是这个助手区别于通用聊天机器人的地方，值得常驻。 */
function renderAiCtx() {
  const box = $('#ai-ctx'); if (!box) return;
  if ($('#ai-panel').dataset.shell !== 'desk') { box.innerHTML = ''; return; }
  const lastTrace = [...aiMsgs].reverse().find(m => m.kind === 'tool');
  const steps = (lastTrace && lastTrace.trace) || [];
  box.innerHTML =
    '<div class="aic-grp"><div class="aic-lbl">本轮做了什么</div>' +
    (steps.length ? steps.map((s, n) => aiStepHtml(s, n)).join('')
      : '<p class="aic-empty">这一轮没动你的数据。</p>') + '</div>' +
    `<div class="aic-grp"><div class="aic-lbl">长期记忆 · <span id="aic-memn">…</span></div>
       <div id="aic-mems" class="aic-mems"><p class="aic-empty">加载中…</p></div>
       <button class="aic-more" id="aic-memopen">管理记忆 ›</button></div>`;
  aiLoadCtxMems();
}
async function aiLoadCtxMems() {
  const box = $('#aic-mems'); if (!box) return;
  try {
    const d = await api('/api/aichat/memories');
    if (!aiAlive()) return;
    const n = $('#aic-memn'); if (n) n.textContent = d.memories.length + ' 条';
    box.innerHTML = d.memories.length
      ? d.memories.slice(0, 6).map(m => `<div class="aic-mem">· ${esc(m.text)}</div>`).join('')
      : '<p class="aic-empty">还没记住关于你的事。</p>';
  } catch (_) { box.innerHTML = '<p class="aic-empty">读不到记忆</p>'; }
}

/* 「思考中…」原来是一句死字：网络一抖，它就那么停在那儿，用户分不清是 AI 在想、
   还是这次请求已经悄悄死了。超过 5 秒就把已等的秒数显出来，让「还在动」可见。 */
let aiTimer = 0;
function aiTickStart() {
  clearInterval(aiTimer); aiTimer = 0;
  if (!aiBusy) return;
  const t0 = Date.now();
  aiTimer = setInterval(() => {
    const el = $('#ai-phase');
    if (!el) { clearInterval(aiTimer); aiTimer = 0; return; }
    const s = Math.round((Date.now() - t0) / 1000);
    const base = aiPhase || '思考中…';
    el.textContent = s < 5 ? base : (s < 20 ? base + '（' + s + ' 秒）' : base + '（' + s + ' 秒，网络较慢）');
  }, 1000);
}
/* 流式收到的正文。逐字重画整个消息列表太贵（每片都要把全部历史过一遍 Markdown），
   所以只改那一个气泡的 innerHTML，并且最多 80 毫秒画一次。 */
let aiStreamText = '', aiPhase = '', aiPaintAt = 0, aiPaintTimer = 0;
/* 已经写完的那些段落渲染一次就冻结，之后每次重绘只解析**最后一个没写完的段落**。
   切点只取 \n\n（段落边界），且必须在代码块之外 —— 从 ``` 中间切开会把代码块拆坏。 */
let aiDoneHtml = '', aiDoneLen = 0;
function aiPaintReset() { aiDoneHtml = ''; aiDoneLen = 0; aiReasonLive = ''; }
function aiPaint() {
  clearTimeout(aiPaintTimer); aiPaintTimer = 0;
  const now = Date.now();
  if (now - aiPaintAt < 80) { aiPaintTimer = setTimeout(aiPaint, 80); return; }
  aiPaintAt = now;
  const el = $('#ai-stream');
  if (!el) { renderAI(); return; }            // 第一片到达：先让气泡本身出现
  const s = aiStreamText;
  const cut = s.lastIndexOf('\n\n');
  // 代码围栏必须成对，否则这一刀正落在代码块里
  if (cut > aiDoneLen && (s.slice(0, cut).split('```').length - 1) % 2 === 0) {
    aiDoneHtml += mdToHtml(s.slice(aiDoneLen, cut));
    aiDoneLen = cut;
  }
  el.innerHTML = aiDoneHtml + mdToHtml(s.slice(aiDoneLen));
  aiStick().follow(0);          // 贴底才跟着字往下走；翻上去看前文时不打扰
}

/* ---------------- 附件 ---------------- */
let aiAtts = [];  // [{name, text, image}]
function renderAiAtts() {
  // 角标只是提醒「这份没读全」，具体差多少写在下面这一行 —— 60×60 的小方块塞不下
  const cuts = aiAtts.map(aiAttCut).filter(Boolean);
  $('#ai-atts').innerHTML = aiAttsHtml(aiAtts, false)
    + (cuts.length ? '<p class="ai-attcut">⚠ ' + esc(cuts.join('｜'))
       + '。AI 会被告知它没看全，需要后面的内容就把文件存进资料库再让它按页读。</p>' : '');
  $('#ai-atts').classList.toggle('on', !!aiAtts.length);
}
$('#ai-atts').addEventListener('click', e => {
  const b = e.target.closest('[data-aiattdel]'); if (!b) return;
  e.stopPropagation();
  aiAtts.splice(+b.dataset.aiattdel, 1); renderAiAtts();
});
$('#ai-attach').onclick = () => anchorMenu($('#ai-attsheet'), $('#ai-attach'));
$('#ai-attsheet').addEventListener('click', e => {
  const b = e.target.closest('[data-aiatt]'); if (!b) return;
  $('#ai-attsheet').classList.add('hidden');
  aiSheetClose();
  if (b.dataset.aiatt === 'photo') $('#ai-camfile').click();
  else if (b.dataset.aiatt === 'image') { $('#ai-attfile').accept = 'image/*'; $('#ai-attfile').click(); }
  else { $('#ai-attfile').accept = '.pdf,.doc,.docx,.txt,.md,.ppt,.pptx,.xls,.xlsx'; $('#ai-attfile').click(); }
});
/* /api/ai/extract 的结果 → 一条附件。上传的文件和云盘/资料库里的文件走同一个出口，
   免得提示语和「没读全」的角标在两处各写一份、日后慢慢走散。 */
function aiPushAtt(d, fallbackName) {
  // image 是留下来的原图文件名：带着它，这一轮就走视觉模型（模型真看得见图形和图表），
  // 抽出来的文字继续当兜底一起发过去。
  // total/pages 要一路带到服务端：注入给模型的正文靠它交代「这份文件其实有多大」
  const att = { name: d.name || fallbackName || '附件', text: d.text || '', image: d.image || '',
    total: d.total || 0, pages: d.pages || 0, ocr_pages: d.ocr_pages || 0 };
  aiAtts.push(att);
  renderAiAtts();
  return att;
}
function aiAttDone(att, isImg) {
  const cut = aiAttCut(att);
  toast(cut ? ('已附加，但没读全：' + cut)
    : (isImg ? '已附加，发送时 AI 会直接看这张图' : '已附加，发送时 AI 会读取其内容'), !!cut);
}
/* 选图 / 拍照 / 选文件都走这里。三件事必须都做，缺一件在手机上就是「选完没动静」：
   ① 图片先在本地缩到 2000px 再传 —— 手机原图动辄 5~10MB，实测 8.4MB 走隧道光上传
      就要 22 秒（还没算服务端 20~30 秒的识别）。聊天、小记、云盘早就都先压了，
      只有这条路一直在传原图。2000px 视觉模型看得清，OCR 也够用。
   ② 选完立刻在输入框上方摆一个「读取中」的位子，别让这几十秒里屏幕上什么都不变。
   ③ 请求给超时 —— api() 默认不超时，隧道一断这个 fetch 就永远挂着，
      连那句错误提示都等不到。 */
async function aiHandleAttach(file) {
  if (!file) return;
  const isImg = /^image\//.test(file.type || '');
  // 缩略图只是让人看见「进来了」。createObjectURL 拿不到就空着显示个文件图标 ——
  // 占位失败绝不能把上传本身带下去（老 WebView 上真有没有它的）。
  let url = '';
  if (isImg) { try { url = URL.createObjectURL(file); } catch (_) { url = ''; } }
  const ph = { name: file.name || (isImg ? '图片' : '附件'), pending: true, url: url };
  aiAtts.push(ph); renderAiAtts();
  const drop = () => {
    const i = aiAtts.indexOf(ph);
    if (i >= 0) aiAtts.splice(i, 1);
    if (ph.url) { try { URL.revokeObjectURL(ph.url); } catch (_) { /* 撤不掉就算了 */ } }
    renderAiAtts();
  };
  let blob = file, name = file.name || 'image.jpg';
  if (isImg) {
    try { blob = await compressImage(file, 2000, 0.85); } catch (_) { blob = file; }
    if (blob !== file && !/\.jpe?g$/i.test(name)) name = name.replace(/\.[^.]+$/, '') + '.jpg';
  }
  const fd = new FormData(); fd.append('file', blob, name);
  try {
    const d = await api('/api/ai/extract', { method: 'POST', body: fd, timeoutMs: 180000 });
    drop();
    if (d.error) { toast(d.error, true); return; }
    aiAttDone(aiPushAtt(d, file.name), !!d.image);
  } catch (e) { drop(); toast(errMsg(e), true); }
}

/* 云盘 / 资料库里**已经有的**文件 → 直接挂成附件。
   只把 id 发过去：文件本来就躺在服务器上，先下下来再原样传回去既慢又白烧一遍流量
   （云盘里的讲义动辄几十 MB）。云盘右键「发给 AI 助手」和在助手里粘贴都走这里。
   items: [{kind:'drive'|'material', id, name}]，返回成功的条数。 */
async function aiAttachLib(items, opts) {
  const list = (items || []).filter(it => it && it.id);
  if (!list.length) return 0;
  if (!(opts && opts.keepPanel)) await openAI();   // 从云盘/资料库点过来的，得先把助手打开
  toast(list.length > 1 ? ('正在读取 ' + list.length + ' 个文件…') : '正在读取附件…');
  let ok = 0, last = null;
  for (const it of list) {
    const body = it.kind === 'material' ? { material_id: it.id } : { drive_id: it.id };
    try {
      const d = await api('/api/ai/extract', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body), timeoutMs: 180000 });
      if (d.error) { toast(d.error, true); continue; }
      last = { att: aiPushAtt(d, it.name), img: !!d.image }; ok++;
    } catch (e) { toast(errMsg(e), true); }
  }
  if (ok === 1 && last) aiAttDone(last.att, last.img);
  else if (ok > 1) toast('已附加 ' + ok + ' 个文件，发送时 AI 会读取它们');
  return ok;
}

/* 输入框上方那条「剪贴板里还有 N 个文件」的提示条。
   右键菜单里的「粘贴」是 WebKit 自己的，够不着应用内剪贴板（它只认文本和图片）——
   所以复制完给一个看得见、点得着的入口，不让人对着输入框反复右键。 */
function aiSyncClipChip() {
  const el = $('#ai-clipchip'); if (!el) return;
  const clip = getAppClip();
  el.classList.toggle('hidden', !clip.length);
  if (!clip.length) return;
  el.innerHTML = `<span>${artEm('📋')} 剪贴板里有 ${clip.length} 个文件</span>` +
    '<button type="button" id="ai-clipadd">附给 AI</button>' +
    '<button type="button" class="x" id="ai-clipx" title="不附">✕</button>';
}
document.addEventListener('appclip', aiSyncClipChip);
$('#ai-clipchip').addEventListener('click', async e => {
  if (e.target.closest('#ai-clipx')) { $('#ai-clipchip').classList.add('hidden'); return; }
  if (!e.target.closest('#ai-clipadd')) return;
  const clip = getAppClip();
  // 附完不清空应用剪贴板：云盘那边还指望它粘文件（同一份剪贴板两处用），只把提示条收起来
  if (await aiAttachLib(clip, { keepPanel: true })) $('#ai-clipchip').classList.add('hidden');
});
$('#ai-attfile').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; aiHandleAttach(f); });
$('#ai-camfile').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; aiHandleAttach(f); });

// ===== AI 工具面板：把 AI 能调的工具做成可点的快捷入口，既能一键让 AI 做、也能直接打开 =====
// go=打开首页某功能（复用 navHomeCard，跟点首页图标一样跳转，含往下的二三级）；
// ask=一键发预设问题让 AI 调工具作答；input=先弹输入框收集内容，再让 AI 记进去。带 sub:'AI' 的走大模型。
// 「打开功能」组不写死：直接读首页卡片，天然镜像首页（含用户拖拽排序），日后加新功能自动出现。
const HOME_IC = { changkao: '⭐', notes: '🗒️', kb: '📚', wrongq: '📓', materials: '📁',
  quiz: '📝', tasks: '✅', drive: '☁️', chat: '💬', review: '🔁', idiom: '📖' };
function aiHomeNavItems() {
  return [...document.querySelectorAll('#home-cards .home-card[data-go]')].map(c => {
    const go = c.dataset.go;
    let ic = HOME_IC[go] || '📂';
    if (go.startsWith('sec:')) { const t = ((c.querySelector('.hc-logo') || {}).textContent || '').trim(); if (t) ic = t; }
    return { go, ic, label: ((c.querySelector('.hc-name') || {}).textContent || '').trim() };
  }).filter(x => x.label);
}
const AI_TOOL_GROUPS = [
  { name: '问我的数据', items: [
    { ic: '📊', label: '我的数据总览', sub: 'AI', ask: '帮我看看我的数据总览' },
    { ic: '🔁', label: '今天要复习什么', sub: 'AI', ask: '我今天有哪些要复习的？' },
    { ic: '🗓️', label: '今天的备考计划', sub: 'AI', ask: '我今天的备考计划是什么？' },
    { ic: '✅', label: '今天还有什么任务', sub: 'AI', ask: '我今天有哪些任务还没做？' },
    { ic: '📈', label: '我的进度和坚持天数', sub: 'AI', ask: '看看我的备考进度和连续学习天数' },
    { ic: '🎯', label: '我的刷题正确率/成绩', sub: 'AI', ask: '我的刷题正确率和最近测验成绩怎么样？' },
    { ic: '🏛️', label: '本应用有多少资源', sub: 'AI', ask: '这个应用的题库、古诗文库、常识库各有多少？' },
  ] },
  { name: '快捷记录', items: [
    { ic: '➕', label: '收录一个词', sub: 'AI', input: '输入要收录的成语/词语', ask: v => `帮我把「${v}」收录到成语词语积累` },
    { ic: '📝', label: '记一条小记', sub: 'AI', input: '要记的内容', ask: v => `帮我在小记里记一条：${v}` },
    { ic: '📅', label: '加一个每日任务', sub: 'AI', input: '每日任务内容，如「刷20道判断推理」', ask: v => `帮我加个每日任务：${v}` },
    { ic: '🔍', label: '查词释义', sub: 'AI', input: '要查释义的词', ask: v => `「${v}」是什么意思？` },
  ] },
];

let _aiToolG = [];   // 当前渲染用的分组（打开功能是动态的，点击时按这份索引，避免错位）
function renderAiTools(kw) {
  kw = (kw || '').trim().toLowerCase();
  _aiToolG = [{ name: '打开功能', items: aiHomeNavItems() }, ...AI_TOOL_GROUPS];
  let html = '';
  _aiToolG.forEach((g, gi) => {
    const rows = g.items.map((it, ii) => ({ it, ii })).filter(({ it }) => !kw || it.label.toLowerCase().includes(kw));
    if (!rows.length) return;
    html += `<div class="ai-tool-group">${g.name}</div>` + rows.map(({ it, ii }) =>
      `<button class="ai-tool-item" data-g="${gi}" data-i="${ii}"><span class="tl-ic">${artEm(it.ic)}</span>` +
      `<span class="tl-tx">${esc(it.label)}</span>${it.sub ? `<span class="tl-sub">${it.sub}</span>` : ''}</button>`).join('');
  });
  $('#ai-tool-list').innerHTML = html || '<div class="ai-tool-empty">没有匹配的工具</div>';
}

function aiToolRun(it) {
  $('#ai-toolsheet').classList.add('hidden');
  if (it.go) {                       // 打开首页某功能：跟点首页图标一样跳转（含往下的二三级），先收起 AI 面板
    $('#ai-panel').classList.add('hidden');
    if (window.applyPush) applyPush();
    if (window.avoidFab) avoidFab();
    try { navHomeCard(it.go); toast('已打开「' + it.label + '」'); }
    catch (e) { console.error('[AI工具] 打开失败', it.go, e); toast('打开「' + it.label + '」没成功', true); }
    return;
  }
  if (it.input) {                    // 快捷记录：先问用户要内容，再让 AI 记
    appPrompt(it.input).then(v => { v = (v || '').trim(); if (v) aiToolSend(it.ask(v)); });
    return;
  }
  aiToolSend(it.ask);                // 快捷提问：把预设问题一键发给 AI
}

function aiToolSend(text) { $('#ai-text').value = text; aiGrow(); aiSend(); }

function openAiTools() {
  renderAiTools(''); $('#ai-tool-filter').value = '';
  $('#ai-toolsheet').classList.remove('hidden');
  aiSheetClose();
  if (!IS_MOBILE) setTimeout(() => $('#ai-tool-filter').focus(), 60);   // 手机端不自动聚焦，免得弹键盘遮列表
}
$('#ai-tools').onclick = openAiTools;
$('#ai-tool-filter').addEventListener('input', e => renderAiTools(e.target.value));
$('#ai-toolsheet').addEventListener('click', e => {
  if (e.target.closest('[data-sheet-close]') || e.target.id === 'ai-toolsheet') { $('#ai-toolsheet').classList.add('hidden'); return; }
  const b = e.target.closest('.ai-tool-item'); if (!b) return;
  const it = (_aiToolG[+b.dataset.g] || { items: [] }).items[+b.dataset.i];
  if (it) aiToolRun(it);
});

/* 手机端 ➕：页内的一块面板，占位在键盘的位置（旧版是 position:fixed 的小浮层，
   跟输入法抢地方 —— AD13）。八格把工具、记忆、档位、导出都摆出来。 */
const AI_SHEET_ITEMS = [
  { ic: '🖼', name: '相册', go: () => { $('#ai-attfile').accept = 'image/*'; $('#ai-attfile').click(); } },
  { ic: '📷', name: '拍照', go: () => $('#ai-camfile').click() },
  { ic: '📄', name: '文件', go: () => { $('#ai-attfile').accept = '.pdf,.doc,.docx,.txt,.md,.ppt,.pptx,.xls,.xlsx'; $('#ai-attfile').click(); } },
  { ic: '✍️', name: '手写', go: () => { const b = document.querySelector('#ai-input .hw-open-btn'); if (b) b.click(); } },
  { ic: '🧰', name: '工具', go: () => openAiTools() },
  { ic: '🧠', name: '记忆', go: () => openAiMemories() },
  { ic: '⚡', name: '档位', go: () => aiAskTier() },
  { ic: '📤', name: '导出', go: () => aiExport() },
];
function aiSheetOpen() {
  $('#ai-sheet-grid').innerHTML = AI_SHEET_ITEMS.map((it, i) =>
    `<button class="ai-g4" data-sh="${i}"><em>${artEm(it.ic)}</em>${esc(it.name)}</button>`).join('');
  $('#ai-sheet').classList.remove('hidden');
  $('#ai-panel').classList.add('sheet-on');
  $('#ai-plus').classList.add('on');      // ＋ 转 45° 变成 ✕：同一颗按钮既开又关
  aiStick().follow(0);
}
function aiSheetClose() {
  $('#ai-sheet').classList.add('hidden');
  $('#ai-panel').classList.remove('sheet-on');
  $('#ai-plus').classList.remove('on');
}
function aiSheetToggle() { if ($('#ai-sheet').classList.contains('hidden')) aiSheetOpen(); else aiSheetClose(); }
$('#ai-sheet').addEventListener('click', e => {
  const b = e.target.closest('[data-sh]'); if (!b) return;
  aiSheetClose();
  const it = AI_SHEET_ITEMS[+b.dataset.sh]; if (it) it.go();
});

/* 流式读一次对话。返回 {reply, title, actions}。

   为什么不用 EventSource：它只能 GET，而问题文本可以很长（截图 OCR 出来的整道题），
   塞进 query string 会被各段代理截断。所以 POST + 自己解 SSE 帧。

   安卓壳 minSdk21，老 WebView 可能没有 ReadableStream —— 那就抛 noStream，
   调用方退回非流式 /send，功能一样只是没有逐字效果。 */
/* 停止生成用的把手：aiSendStream 建好 AbortController 就存这儿，
   #ai-stop 按下时 abort 它（声明放在使用它的函数**之前**，免得将来有人在顶层提前调用踩 TDZ）。 */
let aiCtl = null, aiStopped = false;
const CAN_STREAM = !!(window.fetch && window.TextDecoder && typeof ReadableStream !== 'undefined');
const noStream = () => Object.assign(new Error('NO_STREAM'), { noStream: true });
async function aiSendStream(content, atts) {
  let ctl = null, timer = 0;
  /* 空闲超时，不是总超时：任何一个字节（正文、推理段、心跳注释帧）都会把它重新上弦，
     所以「这么久一个字节都没有」才叫连接死了。模型写得再长也不会被误杀。
     这个数必须**大于服务端那份**（mods/agent.py 的 AI_TIMEOUT，两片之间 60 秒），
     否则服务端还在合理等待，前端先把连接掐了 —— 用户看到的是「响应超时」，
     而服务端那边其实马上就要出字。 */
  const arm = () => { if (ctl) { clearTimeout(timer); timer = setTimeout(() => ctl.abort(), 75000); } };
  /* 切后台去用别的应用时，WebView 的 JS 和定时器被系统一起按住：这 75 秒不在后台走完，
     而是**回到前台那一刻集中兑现** —— 一解锁就看见「响应超时」，连接其实可能还好好的。
     所以看不见时把弦卸掉，回到前台重新上，从「你真的在看」那一刻起重新算。
     真死了也不会一直挂着：回前台 75 秒内没有字节照样判死，再由 aiRecoverAnswered 对账。 */
  const onVis = () => { if (!ctl) return; if (document.hidden) clearTimeout(timer); else arm(); };
  const stopArm = () => { clearTimeout(timer); document.removeEventListener('visibilitychange', onVis); };
  if (CAN_ABORT) {                       // 同一个 ctl 也给「停止生成」用
    ctl = new AbortController(); arm(); aiCtl = ctl;
    document.addEventListener('visibilitychange', onVis);
  }
  let r;
  try {
    r = await fetch('/api/aichat/chats/' + aiChatId + '/stream', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: content, attachments: atts || [] }), signal: ctl ? ctl.signal : undefined
    });
  } catch (e) { stopArm(); throw e; }
  if (r.status === 401) { stopArm(); location.href = '/login'; throw new Error('未登录'); }
  if (!r.ok) {
    stopArm();
    let msg = '请求失败';
    try { msg = (await r.json()).error || msg; } catch (_) { /* 不是 JSON 就用默认话术 */ }
    throw new Error(msg);
  }
  if (!r.body || !r.body.getReader) { stopArm(); throw noStream(); }
  const reader = r.body.getReader(), dec = new TextDecoder();
  let buf = '', done = null, err = '';
  for (;;) {
    const chunk = await reader.read();
    arm();
    if (chunk.done) break;
    buf += dec.decode(chunk.value, { stream: true });
    const frames = buf.split('\n\n');
    buf = frames.pop();                        // 最后一段可能只收到一半，留着跟下一片拼
    for (const f of frames) {
      let ev = 'message', data = '';
      for (const line of f.split('\n')) {
        if (line.indexOf('event:') === 0) ev = line.slice(6).trim();
        else if (line.indexOf('data:') === 0) data += line.slice(5).trim();
      }
      if (!data) continue;
      let d; try { d = JSON.parse(data); } catch (_) { continue; }
      if (ev === 'delta') { aiStreamText += d; aiPaint(); }
      /* 推理过程：以前只拿它改一句文案就丢了（AD6）。现在实时贴进那张卡，
         答完 aiSend 把它折起来存进消息流。 */
      else if (ev === 'reasoning') {
        aiPhase = '正在推理…';
        aiReasonLive += (typeof d === 'string' ? d : (d && d.text) || '');
        const el = $('#ai-reasonlive');
        if (el) { el.textContent = aiReasonLive; el.scrollTop = el.scrollHeight; }
        else renderAI();
      }
      // 后端把工具名连人话标签一起推过来了。以前这里一律显示「正在操作…」——
      // 查错题和删小记长得一模一样，用户不知道它在动谁的数据。
      else if (ev === 'tool') { aiPhase = '正在' + ((d && d.label) || '操作') + '…'; }
      else if (ev === 'done') { done = d; }
      else if (ev === 'error') { err = d.error || 'AI 调用失败'; }
    }
  }
  stopArm();
  if (err) throw new Error(err);
  // 把服务端 done 里的东西**整包带走**，别一个个挑：漏掉 user_mid/msg_id 会让
  // 「改问题 / 分支」在流式路径（也就是所有现代浏览器）上永远报「还没同步好」，
  // 漏掉 truncated 则「继续」按钮永远不出现 —— 服务端明明都发了。
  if (done) return Object.assign({}, done, { reply: done.reply || aiStreamText,
    actions: done.actions || [], trace: done.trace || [] });
  // 连接在收完之前断了：已经出来的字是真的，别丢掉重来，标一句「可能不完整」就行。
  if (aiStreamText) return { reply: aiStreamText + '\n\n（连接中断，回答可能不完整）', title: '', actions: [] };
  throw noStream();                            // 一个字节都没有 → 当没流过，退回非流式
}

async function aiSend() {
  const t = $('#ai-text').value.trim();
  if ((!t && !aiAtts.length) || aiBusy) return;
  // 占位的那份还没变成真附件（里头没有 text/image），跟着发出去 AI 就是拿着个空壳
  if (aiAtts.some(a => a.pending)) { toast('附件还在读取，等它读完再发', true); return; }
  /* 附件全文**不再拼进问题正文**。以前 payload（含整篇 PDF）既发出去又落库，而屏幕上
     显示的是精简的 shown —— 刷新会话后自己那句话就变成了几千字的正文。
     现在两者分开：content 是人看的那句，附件走 attachments 单独传、单独存。 */
  const atts = aiAtts.slice();
  const shown = (t ? t : '') + (atts.length ? (t ? '\n' : '') + '📎 ' + atts.map(a => a.name).join('、') : '');
  if (atts.length) { aiAtts = []; renderAiAtts(); }
  if (!aiChatId) {
    try {
      const d = await api('/api/aichat/chats', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: aiProjectId || null, tier: aiTier }) });
      aiChatId = d.id;
    } catch (e) { toast(errMsg(e), true); return; }
  }
  aiMsgs.push({ role: 'user', content: shown, atts: atts });
  aiStick().seen();              // 自己发的这条，一定要看得见（哪怕刚才翻在半山腰）
  $('#ai-text').value = ''; aiGrow(); aiSheetClose();
  aiBusy = true; aiStreamText = ''; aiPhase = ''; aiPaintReset(); renderAI();
  const t0 = Date.now();
  try {
    let d = null;
    if (CAN_STREAM) {
      try { d = await aiSendStream(shown, atts); }
      catch (e) { if (!e.noStream) throw e; }   // 只有「这条路走不通」才退回，真错误照报
    }
    if (!d) {
      d = await api('/api/aichat/chats/' + aiChatId + '/send', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        // 非流式没有逐字心跳，只能靠总超时兜底：服务端自己封顶 100 秒
        // （mods/agent.py AI_BUDGET），这里多给 30 秒。
        body: JSON.stringify({ content: shown, attachments: atts }), timeoutMs: 130000
      });
    }
    aiLastMs = Date.now() - t0;
    // 把服务端刚落库的行号补给本地这两条。没有它，「改问题 / 分支」拿到的 m.id 是
    // undefined → 服务端按「最后一轮」处理，改第一个问题会把后面几轮一起删掉还不吭声。
    for (let k = aiMsgs.length - 1; k >= 0; k--) {
      if (aiMsgs[k].role === 'user') { aiMsgs[k].id = d.user_mid || aiMsgs[k].id; break; }
    }
    if (aiReasonLive) { aiMsgs.push({ role: 'assistant', kind: 'reason', content: aiReasonLive }); aiReasonLive = ''; }
    // 工具轨迹排在回答**前面**（跟服务端落库的顺序一致：先查，再答）
    if (d.trace && d.trace.length) { aiMsgs.push({ role: 'assistant', kind: 'tool', trace: d.trace }); aiNewCount++; }
    // truncated：轮数/预算用完它还在调工具 —— 活没干完，给个「继续」而不是让用户对着半截总结
    aiMsgs.push({ role: 'assistant', id: d.msg_id, content: d.reply || '（空回复）',
      truncated: !!d.truncated, tier: aiTier, ms: aiLastMs });
    aiNewCount++;
    if (d.title) aiSetTitle(d.title);
    aiStreamText = ''; aiBusy = false; aiCtl = null; renderAI();
    aiRunActions(d.actions);          // AI 真做了事（加收录 / 打开某功能）→ 前端跟着执行/刷新
    aiAutoTitle();                    // 首轮结束后再让模型起个名字
    loadAiHome();                     // 列表里这条要跳到最前面
    return;
  } catch (e) {
    /* 断了先问服务端一句：这一轮到底答完没有。流式的 done 分支可能早把问答落了库，
       只是最后那帧没送到（客户端超时、切后台、隧道抖）。直接报「失败」的话，用户点
       「重试」就会把同一个问题原样再问一遍 —— 模型看见自己刚讲完、用户又发一次，
       就会另作解释，实测它把这当成「你是要收录这个词」，真去写了库。 */
    if (!aiStopped && await aiRecoverAnswered()) {
      aiStreamText = ''; aiBusy = false; aiStopped = false; aiCtl = null;
      toast('刚才那轮其实答完了，已经取回来');
      return;
    }
    const partial = aiStreamText;     // 断在半截时，已经出来的字是真的，别连它一起丢掉
    if (partial) aiMsgs.push({ role: 'assistant', content: partial + (aiStopped ? '\n\n（已停止）' : ''), tier: aiTier });
    // 用户自己按的「停止生成」不是错误，别报「响应超时，请再发一次」
    if (!aiStopped) {
      /* 原话留一份：服务端**不一定**存下了这一轮 —— 流式那条在生成器里补存了一行
         kind='error'，非流式那条（老 WebView）压根没落库。「重试」优先用服务端退回来的，
         退不出来就用这份本地副本，两条路都不用你重打一遍。 */
      aiLastFailed = { content: shown, atts: atts };
      aiMsgs.push({ role: 'assistant', kind: 'error', content: '⚠️ ' + (e.name === 'AbortError' ? 'AI 响应超时（网络不稳），点下面的「重试」' : e.message) });
    } else if (!partial) {
      aiMsgs.push({ role: 'assistant', content: '（已停止）' });
    }
  }
  aiStreamText = ''; aiBusy = false; aiStopped = false; aiCtl = null; renderAI();
}
/* 跟服务端对账：这一轮答完了没有。probe 只问不动（不会退历史），
   答完了就整段取回来 —— 服务端那份比本地半截的完整。 */
async function aiRecoverAnswered() {
  if (!aiChatId) return false;
  try {
    const d = await api('/api/aichat/chats/' + aiChatId + '/retry', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ probe: true })
    });
    if (!d.answered) return false;
    await aiOpenChat(aiChatId);
    return true;
  } catch (_) { return false; }      // 对不上账就照常报失败，别把错误咽掉
}
/* 停止生成：复用流式那条 AbortController。按钮现在是**固定件**（钉在输入栏上方），
   不再跟着消息流走 —— 旧版你翻上去就找不着它了（AD8）。 */
function aiStop() {
  if (!aiCtl) return;
  aiStopped = true;
  try { aiCtl.abort(); } catch (_) { /* 已经结束了就不用停 */ }
  aiCtl = null;
}
// 执行 AI 工具产生的动作：收录类刷新对应列表，导航类打开功能页
function aiRunActions(actions) {
  if (!actions || !actions.length) return;
  // 收录了新词：如果正看着「成语词语积累」，刷新一下让新词立刻出现
  const v = (stack[stack.length - 1] || {}).view;
  if (v === 'idiom' && typeof loadEntries === 'function') loadEntries();
  for (const a of actions) {
    if (a.type === 'navigate' && a.fn && typeof window[a.fn] === 'function') {
      // 打开功能页前先收起 AI 面板（不然盖在上面看不到）
      $('#ai-panel').classList.add('hidden'); if (window.applyPush) applyPush(); if (window.avoidFab) avoidFab();
      // 说打开了就得真打开：函数一抛异常就报失败，不再无条件 toast「已为你打开」
      try {
        window[a.fn]();
        toast('已为你打开「' + (a.label || '') + '」');
      } catch (e) {
        console.error('[AI] 打开「%s」失败：', a.label || a.fn, e);
        toast('打开「' + (a.label || '') + '」没成功', true);
      }
    } else if (a.type === 'refresh') {
      // 用户正看着对应视图才刷新（省得白重绘）。tasks/plan 同属「任务清单」view=tasks 的两个页签。
      if (a.what === 'entries' && v === 'idiom' && typeof loadEntries === 'function') loadEntries();
      else if (a.what === 'notes' && v === 'notes' && typeof loadFeed === 'function') loadFeed();
      else if (a.what === 'wrongq' && v === 'wrongq' && typeof loadWrongq === 'function') loadWrongq();
      else if (a.what === 'tasks' && v === 'tasks' && typeof loadDaily === 'function') loadDaily();
      else if (a.what === 'plan' && v === 'tasks' && typeof loadPlan === 'function') loadPlan();
      else if (a.what === 'classics' && v === 'classics' && typeof loadClassics === 'function') loadClassics();
      // 记忆不在某个 view 里，是 AI 面板侧边那一栏——面板开着就让新记的那条立刻出现
      else if (a.what === 'memories') aiLoadCtxMems();
      // 文案由后端按实际动作给（收录/收藏/删除各不同），不再前端硬编码
      if (a.toast) toast(a.toast);
    } else if (a.type === 'confirm') {
      aiConfirm(a);   // AI 要删东西：弹确认框，用户点确认后才真删
    }
  }
}

// AI 要做一件得先点头的事（删数据 / 记进长期记忆）→ 弹美化确认框；
// 点确认才调后端带 _confirmed 真执行，结果补进对话并刷新
async function aiConfirm(a) {
  /* 后端在 confirm 动作里带了 summary（那条数据的原文摘要）、label（这是什么操作）和 kind。
     删除不可逆，得让用户看清删的是哪一条；写记忆虽然可逆，但那句话会跟着之后**每一轮**
     对话走，记错了比没记更难发现——所以同样停下来问一句。 */
  const w = a.args && a.args.word;
  const del = a.kind !== 'write' && a.kind !== 'update';  // 没带 kind 的旧动作按删除处理：宁可多问
  const head = del ? `确认${a.label || '删除'}？此操作不可撤销。`
                   : `让 AI「${a.label || '执行这个操作'}」？`;
  const msg = a.summary ? `${head}\n\n${a.summary}`
    : (del ? (w ? `删除「${w}」？此操作不可撤销。` : '确认删除这条内容？此操作不可撤销。') : head);
  if (!(await appConfirm(msg))) return;   // 取消：什么都不做，AI 那句「确定吗」留在对话里
  try {
    const d = await api('/api/aichat/chats/' + aiChatId + '/confirm', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool: a.tool, args: a.args || {} }),
    });
    aiMsgs.push({ role: 'assistant', content: d.reply || (del ? '已删除。' : '已完成。') });
    aiNewCount++; renderAI();
    aiRunActions(d.actions);   // 跑它带回的 refresh（刷新对应列表）
  } catch (e) { toast(errMsg(e) || (del ? '删除失败' : '没执行成功'), true); }
}
function aiGrow() { growAndSync('#ai-text', '#ai-input'); }
// 输入框可拖高（**仅桌面**）：顶边加一条把手，拖动改高度。最小约 3 行、最高半屏，记住上次高度。
// 内容多时自动增高（不低于拖拽设定的高度、不超过半屏）。聊天和 AI 助手共用。
function makeInputResizable(bar, ta, key) {
  if (!bar || !ta || bar.querySelector('.input-grip')) return;
  const MIN = 74;
  const maxH = () => Math.round(window.innerHeight * 0.5);   // 最高半屏
  const base = () => Math.max(MIN, Math.min(maxH(), parseInt(lsGet(key) || '', 10) || MIN));
  ta._grow = () => { ta.style.height = 'auto'; ta.style.height = Math.max(base(), Math.min(maxH(), ta.scrollHeight)) + 'px'; };
  ta.addEventListener('input', ta._grow);
  const grip = document.createElement('div');
  grip.className = 'input-grip'; grip.title = '拖动上边可调高输入框（最高半屏）';
  bar.appendChild(grip);
  let sy = 0, sh = 0, dragging = false;
  grip.addEventListener('pointerdown', e => {
    dragging = true; sy = e.clientY; sh = ta.getBoundingClientRect().height;
    try { grip.setPointerCapture(e.pointerId); } catch (_) { /* 捕获失败不影响画线，指针事件照样收得到 */ }
    document.body.classList.add('resizing-ns'); e.preventDefault();
  });
  grip.addEventListener('pointermove', e => {
    if (!dragging) return;
    const h = Math.max(MIN, Math.min(maxH(), Math.round(sh + (sy - e.clientY))));  // 往上拖=变高
    ta.style.height = h + 'px'; lsSet(key, h);
  });
  const end = e => { if (!dragging) return; dragging = false; document.body.classList.remove('resizing-ns'); try { grip.releasePointerCapture(e.pointerId); } catch (_) { /* 同上 */ } };
  grip.addEventListener('pointerup', end); grip.addEventListener('pointercancel', end);
  ta._grow();                          // 初始高度 = 上次拖到的高度（或最小）
}
// 只在**桌面**装拖高把手（手机端保持紧凑的自动增高）
if (!IS_MOBILE) {
  makeInputResizable(document.querySelector('.ai-input'), $('#ai-text'), 'aiInputH');
  makeInputResizable($('#cr-input'), $('#cr-text'), 'crInputH');
}
$('#ai-send').onclick = aiSend;
/* 消息区里的东西每次 renderAI 都重建 —— 一律委托绑定，别绑在具体按钮上 */
$('#ai-msgs').addEventListener('click', async e => {
  if (!$('#ai-sheet').classList.contains('hidden')) aiSheetClose();   // 点消息区＝收起面板
  if (e.target.closest('#ai-continue')) {      // 接着上一轮往下做（服务端的 4 轮/100 秒上限重新计）
    $('#ai-text').value = '继续，把上面没做完的做完'; aiGrow(); aiSend(); return;
  }
  const more = e.target.closest('.ai-rmore');
  if (more) { const r = more.previousElementSibling; if (r) r.classList.remove('clip'); more.remove(); return; }
  const chip = e.target.closest('[data-chip]');
  if (chip) { $('#ai-text').value = chip.dataset.chip; aiGrow(); aiSend(); return; }
  const rs = e.target.closest('[data-reason]');
  if (rs) { const i = 'r' + rs.dataset.reason; aiTraceOpen[i] = !aiTraceOpen[i]; renderAI(); return; }
  const tr = e.target.closest('[data-trace]');
  if (tr) { const i = +tr.dataset.trace; aiTraceOpen[i] = !aiTraceOpen[i]; renderAI(); return; }
  const a = e.target.closest('[data-act]'); if (!a) return;
  const i = +a.closest('[data-mi]').dataset.mi, m = aiMsgs[i]; if (!m) return;
  const act = a.dataset.act;
  if (act === 'copy') {
    try { await navigator.clipboard.writeText(m.content || ''); toast('已复制'); }
    catch (_) { toast('这个浏览器不让复制，长按选中吧', true); }
  } else if (act === 'retry') {
    aiRetry('');
  } else if (act === 'again') {
    aiRetryFailed();
  } else if (act === 'keep') {
    // 存进积累：把这段回答交给 AI 自己去落库（它手里有 add_entry / add_note 这些工具）
    aiToolSend('把上面这段整理成一条积累存起来（挑最值得记的那部分，标好板块）');
  } else if (act === 'drill') {
    aiToolSend('针对上面这段，出两道同考点的题让我练，先只给题目和选项');
  } else if (act === 'edit') {
    // 没有 id 就别发：服务端会把 msg_id=0 当成「退最后一轮」，改前面的问题反而删掉后面的
    if (!m.id) { toast('这条还没同步好，稍等一下再改', true); return; }
    const v = await appPrompt('改一下问题再发', '', m.content || '');
    if (v && v.trim()) aiRetry(v.trim(), m.id);
  } else if (act === 'branch') {
    if (!m.id) { toast('这条还没同步好，稍等一下再分支', true); return; }
    try {
      const d = await api('/api/aichat/chats/' + aiChatId + '/branch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ msg_id: m.id })
      });
      toast('已新开一条分支对话');
      await loadAiHome(); aiOpenChat(d.id);
    } catch (err) { toast(errMsg(err), true); }
  }
});
/* 重答 / 改问：先让服务端把历史退回到那一轮之前，再用（新的或原来的）问题正常重发。
   生成只有一条路（/stream），这里不复制一份对话逻辑。 */
/* 落库的那句里带着「📎 文件名」那一行 —— 它是**给人看的显示串**，重发时 aiSend 会按
   当前附件重新拼一遍。回填输入框前先把旧的那行摘掉，否则每重试一次就多叠一行。 */
const aiStripClip = (t) => String(t || '').replace(/\n?📎 [^\n]*$/, '');

let aiLastFailed = null;      // 最近一次失败的原话 {content, atts}，给「重试」兜底
/* 「刚才那次失败了，再来一次」。跟「重答」不是一回事：重答是对**成功**的回答不满意，
   这个是这一轮压根没答出来 —— 服务端得先把那半轮（问题 + 失败占位）退掉再重发，
   否则会话里会留下一串「问一次、失败一次」的残骸。 */
async function aiRetryFailed() {
  if (aiBusy) return;
  let content = '', atts = [];
  if (aiChatId) {
    try {
      const d = await api('/api/aichat/chats/' + aiChatId + '/retry', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ failed: true })
      });
      if (d.answered) {           // 服务端答完了，只是刚才没送到 —— 取回来，不能重发
        await aiOpenChat(aiChatId);
        toast('刚才那轮其实答完了，已经取回来');
        return;
      }
      if (d.rewound) { content = aiStripClip(d.content); atts = d.attachments || []; }
    } catch (e) { toast(errMsg(e), true); return; }
  }
  if (!content && !atts.length && aiLastFailed) {          // 服务端没存下这轮 → 用本地那份
    content = aiStripClip(aiLastFailed.content); atts = (aiLastFailed.atts || []).slice();
  }
  if (!content && !atts.length) { toast('找不到刚才那句话，直接再问一次吧', true); return; }
  // 本地也退回去：把失败那一轮（用户那句 + 报错气泡）一起摘掉，别在屏幕上留一串残骸
  for (let i = aiMsgs.length - 1; i >= 0; i--) {
    if (aiMsgs[i].role === 'user') { aiMsgs = aiMsgs.slice(0, i); break; }
  }
  aiLastFailed = null;
  aiAtts = atts; renderAiAtts();
  $('#ai-text').value = content; aiGrow();
  renderAI();
  aiSend();
}
async function aiRetry(newContent, msgId) {
  if (aiBusy) return;
  try {
    const d = await api('/api/aichat/chats/' + aiChatId + '/retry', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: newContent || '', msg_id: msgId || 0 })
    });
    // 本地历史也退回去：退到最后一条 user 之前
    let cut = -1;
    for (let i = aiMsgs.length - 1; i >= 0; i--) {
      if (aiMsgs[i].role === 'user' && (!msgId || aiMsgs[i].id === msgId)) { cut = i; break; }
    }
    if (cut >= 0) aiMsgs = aiMsgs.slice(0, cut);
    aiAtts = (d.attachments || []).slice();
    renderAiAtts();
    $('#ai-text').value = aiStripClip(d.content);
    renderAI();
    aiSend();
  } catch (e) { toast(errMsg(e), true); }
}
/* ---- 长期记忆：AI 记住的关于我的事，可查可删 ----
   记忆最怕悄悄记错还一直用，所以来源和「被用过几次」都摆出来。 */
async function openAiMemories() {
  const box = $('#ai-memsheet');
  box.classList.remove('hidden');
  box.innerHTML = `<div class="cp-box"><div class="cp-head">AI 记住的关于我的事<button data-memx>✕</button></div>
    <div class="cp-list"><p class="empty">加载中…</p></div>
    <div class="mem-add"><input id="mem-new" placeholder="想让它长期记住什么？"><button id="mem-addbtn">添加</button></div></div>`;
  try {
    const d = await api('/api/aichat/memories');
    box.querySelector('.cp-list').innerHTML =
      '<p class="mem-tip">这些会在每次对话开头带给 AI。删掉的立刻失效。</p>' +
      (d.memories.length ? d.memories.map(m => `
        <div class="ai-mem"><div class="c"><div class="t">${esc(m.text)}</div>
          <div class="s">${esc(m.source || '')}${m.hits ? ' · 已用 ' + m.hits + ' 次' : ''}</div></div>
          <button class="x" data-memdel="${m.id}">✕</button></div>`).join('')
        : '<p class="empty">还没有记住任何事。</p>');
  } catch (e) { box.querySelector('.cp-list').innerHTML = uiError(e); }
}
$('#ai-memsheet').addEventListener('click', async e => {
  if (e.target.closest('[data-memx]') || e.target.id === 'ai-memsheet') { $('#ai-memsheet').classList.add('hidden'); return; }
  const del = e.target.closest('[data-memdel]');
  if (del) {
    try { await api('/api/aichat/memories/' + del.dataset.memdel, { method: 'DELETE' }); openAiMemories(); aiLoadCtxMems(); }
    catch (err) { toast(errMsg(err), true); }
    return;
  }
  if (e.target.closest('#mem-addbtn')) {
    const v = ($('#mem-new').value || '').trim(); if (!v) return;
    try {
      await api('/api/aichat/memories', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: v })
      });
      openAiMemories(); aiLoadCtxMems();
    } catch (err) { toast(errMsg(err), true); }
  }
});
$('#aih-mem').onclick = openAiMemories;

/* 导出这段对话（F7）：存进「小记」，或复制全文发给队友。 */
async function aiExport() {
  if (!aiMsgs.length) { toast('这段对话还是空的'); return; }
  const md = '# ' + ($('#aic-title').textContent || '对话') + '\n\n' + aiMsgs
    .filter(m => m.kind !== 'tool' && m.kind !== 'reason')
    .map(m => (m.role === 'user' ? '**我：**' : '**AI：**') + '\n\n' + (m.content || ''))
    .join('\n\n---\n\n');
  const how = await appConfirm('把这段对话导出到哪儿？', { okText: '存进小记', altText: '复制全文' });
  if (how === 'alt') {
    try { await navigator.clipboard.writeText(md); toast('已复制全文'); }
    catch (_) { toast('这个浏览器不让复制', true); }
    return;
  }
  if (how !== true) return;
  try {
    const fd = new FormData();
    fd.append('content', md);
    fd.append('tags', JSON.stringify(['AI对话']));
    await api('/api/notes', { method: 'POST', body: fd });
    toast('已存进小记');
  } catch (e) { toast(errMsg(e), true); }
}

/* 首轮结束后让模型给会话起个名（原先是把用户第一句话切前 24 字）。 */
async function aiAutoTitle() {
  if (!aiChatId || aiMsgs.filter(m => m.role === 'user').length !== 1) return;
  try {
    const d = await api('/api/aichat/chats/' + aiChatId + '/title', { method: 'POST' });
    if (aiAlive() && d.title) { aiSetTitle(d.title); loadAiHome(); }
  } catch (_) { /* 起名失败不影响对话本身 */ }
}
/* 档位：快 / 深度。深度走推理模型（aiclient 的 pro 档），慢但想得清楚。
   旁边那行小字说清「现在用的是哪个模型」（AD12）。 */
let aiTier = 'fast';
function renderAiTier() {
  const el = $('#ai-tier'); if (!el) return;
  el.querySelectorAll('[data-tier]').forEach(b => b.classList.toggle('on', b.dataset.tier === aiTier));
  aiSetSub();
  aiLoadTierNote();
}
let aiTierNoteAt = 0;
async function aiLoadTierNote() {
  const el = $('#ai-tiernote'); if (!el) return;
  if (Date.now() - aiTierNoteAt < 60000 && el.textContent) return;   // 一分钟内不重复问
  aiTierNoteAt = Date.now();
  try {
    const d = await api('/api/ai/status');
    if (!aiAlive()) return;
    el.textContent = (aiTier === 'pro' ? (d.model_pro || '') : (d.model || ''))
      + (d.today ? ' · 今日 ' + d.today + ' 次' : '');
  } catch (_) { el.textContent = ''; }
}
async function aiAskTier() {
  const r = await appConfirm('这段对话用哪个档位？\n\n快：日常问答，秒回\n深度：推理模型，复杂题目更稳，但要多等十几秒',
    { okText: '深度', altText: '快' });
  if (r !== true && r !== 'alt') return;
  aiTier = r === true ? 'pro' : 'fast';
  renderAiTier(); aiSaveTier();
}
async function aiSaveTier() {
  if (!aiChatId) return;          // 还没建会话，等发送时一起带过去
  try {
    await api('/api/aichat/chats/' + aiChatId, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tier: aiTier })
    });
  } catch (err) { toast(errMsg(err), true); }
}
$('#ai-tier').addEventListener('click', e => {
  const b = e.target.closest('[data-tier]'); if (!b || aiBusy) return;
  aiTier = b.dataset.tier; aiTierNoteAt = 0; renderAiTier(); aiSaveTier();
});

/* ---- 语音输入（F1）：说话转文字填进输入框 ----
   两条路，能走哪条走哪条：
     live  浏览器自带识别（Chrome / Edge）。边说边出字、不花钱，优先。
     asr   录一段音传给服务端识别。桌面壳的 WebKit、安卓 WebView、Firefox 都没有
           自带识别，以前这些端只能把按钮藏起来；现在只要管理员在后台开了语音识别，
           它们也能用。
   两条都没有就还是**不显示按钮** —— 摆一颗按不动的麦克风是最差的一种（AD10）。 */
function aiSpeechOK() { return !!(window.SpeechRecognition || window.webkitSpeechRecognition); }
/* 按钮该不该出现：有自带识别一定出现；没有的话只要能录音就先留着，
   点下去才去问服务端开没开 —— 为一颗按钮先打一趟接口不值当。 */
function aiVoiceAvail() {
  const ok = aiSpeechOK() || voiceSupported();
  $('#ai-voice').classList.toggle('hidden', !ok);
  $('#ai-mic2').classList.toggle('no-speech', !ok);
}
/* 录一段 → 传服务端识别 → 填进输入框（不自动发送：识别难免有错，让人先看一眼）
   转写要好几秒，这中间用户可能接着打字、也可能切走会话，所以：
   进度画在按钮上（别拿「识别中…」去占输入框，那也是在改用户的内容）、
   结果回来先认会话、最后插到光标处而不是覆盖整个框。 */
async function aiVoiceByServer() {
  const rec = await voiceRecord({ tip: '正在录音，说完点「完成」转成文字' });
  if (!rec) return;
  const el = $('#ai-text'), chat = aiChatId;
  aiVoiceWait(true);
  try {
    const txt = await voiceToText(rec.blob, rec.ext);
    if (chat !== aiChatId) { toast('会话已经切走了，这段话没填进去', true); return; }
    if (!txt) { toast('没识别出内容'); return; }
    voiceInsert(el, txt);
    el.focus();
  } catch (e) {
    toast(errMsg(e), true);
  } finally {
    aiVoiceWait(false);
    aiGrow();
  }
}
function aiVoiceWait(on) {   // 转写中：两颗麦克风都转成「在忙」，免得再点一次又录一段
  document.querySelectorAll('#ai-voice, #ai-mic2').forEach(b => b.classList.toggle('rec', on));
}
let aiRec = null, aiRecOn = false;
async function aiVoiceToggle() {
  if (!aiSpeechOK()) {
    if (voiceSupported() && await voiceAsrEnabled()) { aiVoiceByServer(); return; }
    toast(voiceSupported() ? '语音转文字还没开启（管理员可在后台 → 语音识别 里配置）'
      : (voiceWhyNot() || '这个浏览器不支持语音输入'), true);
    return;
  }
  if (aiRecOn) { try { aiRec.stop(); } catch (_) { /* 已经停了 */ } return; }
  const R = window.SpeechRecognition || window.webkitSpeechRecognition;
  aiRec = new R();
  aiRec.lang = 'zh-CN'; aiRec.interimResults = true; aiRec.continuous = true;
  const live = voiceLive($('#ai-text'));   // 只改「自己写进去的那一段」，别重写整个框
  aiRec.onresult = (ev) => {
    let txt = '';
    for (let i = 0; i < ev.results.length; i++) txt += ev.results[i][0].transcript;
    live.set(txt);
    aiGrow();
  };
  aiRec.onend = () => { aiRecOn = false; aiVoicePaint(); };
  aiRec.onerror = (ev) => { aiRecOn = false; aiVoicePaint(); if (ev.error !== 'aborted') toast('没听清（' + ev.error + '）', true); };
  try { aiRec.start(); aiRecOn = true; aiVoicePaint(); toast('在听了，说完再点一下'); }
  catch (_) { toast('麦克风没打开', true); }
}
function aiVoicePaint() {
  document.querySelectorAll('#ai-voice, #ai-mic2').forEach(b => b.classList.toggle('rec', aiRecOn));
}
$('#ai-voice').onclick = aiVoiceToggle;
$('#ai-mic2').onclick = aiVoiceToggle;

/* ---- 事件绑定 ---- */
$('#ai-sidebtn').onclick = aiSideToggle;
$('#ai-titlebtn').onclick = () => { if ($('#ai-panel').dataset.shell !== 'desk') aiSideToggle(); };
$('#ais-close').onclick = () => aiSideClose();
$('#ai-sidemask').onclick = () => aiSideClose();
$('#ai-newbtn').onclick = () => aiNewChat(aiProjectId);
/* 汇总这段对话（第 10 条）。产物落进「AI 产出」，不是往聊天流里再塞一段
   —— 纪要是要拿去用的东西，塞回对话里下次还得翻。 */
$('#ai-sumbtn').onclick = async () => {
  if (aiBusy) { toast('等这一轮答完再汇总'); return; }
  if (!aiChatId || !aiMsgs.length) { toast('这段对话还是空的'); return; }
  const btn = $('#ai-sumbtn');
  btn.disabled = true;
  toast('正在汇总…长对话会分段做，稍等一下');
  try {
    const d = await api('/api/aichat/chats/' + aiChatId + '/summary', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
    });
    // 汇总本身也贴回对话里给你当场看一眼；要拿去用就去 库 → AI 产出
    aiMsgs.push({ role: 'assistant', content: d.body + '\n\n---\n已存进「库 → AI 产出」：**'
      + d.title + '**' + (d.parts > 1 ? '（分 ' + d.parts + ' 段汇总后合并）' : '') });
    aiNewCount++; renderAI();
    toast('汇总好了，已存进「AI 产出」');
  } catch (e) { toast(errMsg(e), true); }
  btn.disabled = false;
};
$('#aih-new').onclick = () => aiNewChat();
$('#ai-close').onclick = () => { $('#ai-panel').classList.add('hidden'); applyPush(); avoidFab(); };
$('#ai-plus').onclick = aiSheetToggle;
$('#aih-search').addEventListener('input', e => {
  aiHomeQ = e.target.value.trim();
  clearTimeout(aiHomeTimer);
  aiHomeTimer = setTimeout(loadAiHome, 220);      // 打字防抖
});
$('#aip-new').onclick = async () => {
  const name = await appPrompt('新建项目', '项目名，如：申论批改');
  if (!name || !name.trim()) return;
  const ins = await appPrompt('项目自定义指令（可留空）', '例：你是申论阅卷老师，对我提交的答案按采分点批改打分');
  try {
    await api('/api/aichat/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim(), instructions: (ins || '').trim() }) });
    await loadAiHome();
  } catch (e) { toast(errMsg(e), true); }
};
$('#ai-panel').addEventListener('click', async e => {
  if (e.target.closest('#ai-stop')) { aiStop(); return; }
  if (e.target.closest('#aipd-new')) { if (aiCurProject) aiNewChat(aiCurProject.id); return; }
  if (e.target.closest('#aipd-set')) { if (aiCurProject) openAiProjSet(aiCurProject.id); return; }
  if (e.target.closest('#ais-back')) { aiCurProject = null; renderAiList(); return; }
  if (e.target.closest('#aic-memopen')) { openAiMemories(); return; }
  const menu = e.target.closest('[data-aimenu]');
  if (menu) {
    e.stopPropagation();
    openAiChatMenu(menu, +menu.dataset.aimenu, menu.dataset.atitle, menu.dataset.aproj, menu.dataset.astar === '1');
    return;
  }
  const pdel = e.target.closest('[data-aipdel]');
  if (pdel) {
    e.stopPropagation();
    if (!(await appConfirm('删除这个项目？（对话会保留，只是不再归组）'))) return;
    try { await api('/api/aichat/projects/' + pdel.dataset.aipdel, { method: 'DELETE' }); await loadAiHome(); } catch (err) { toast(errMsg(err), true); }
    return;
  }
  const chat = e.target.closest('[data-aichat]');
  if (chat) { aiOpenChat(+chat.dataset.aichat); return; }
  const proj = e.target.closest('[data-aiproj]');
  if (proj) { openAiProject(+proj.dataset.aiproj); return; }
});
$('#ai-text').addEventListener('input', aiGrow);
$('#ai-text').addEventListener('focus', aiSheetClose);
$('#ai-text').addEventListener('keydown', e => { if (!composing(e) && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); aiSend(); } });
/* AI 面板：从上方下滑关闭（替代点右上角✕）。抽屉开着时下滑先收抽屉。 */
(function () {
  const panel = $('#ai-panel'); if (!panel) return;
  let sy = 0, sx = 0, tracking = false;
  panel.addEventListener('touchstart', e => {
    if (e.touches.length !== 1) { tracking = false; return; }
    const y = e.touches[0].clientY;
    tracking = y < 160;              // 仅在顶部起手，避免和列表滚动冲突
    sy = y; sx = e.touches[0].clientX;
  }, { passive: true });
  panel.addEventListener('touchend', e => {
    if (!tracking) return; tracking = false;
    const t = e.changedTouches[0];
    const dy = t.clientY - sy, dx = Math.abs(t.clientX - sx);
    if (dy > 70 && dy > dx) {
      if (panel.classList.contains('side-on')) { aiSideClose(); return; }
      panel.classList.add('hidden'); applyPush(); avoidFab();
    }
  }, { passive: true });
})();
