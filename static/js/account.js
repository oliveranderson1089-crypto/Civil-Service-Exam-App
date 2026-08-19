/* 账户 / 个人信息页
 *
 * 由 app.js 按它自己的区段边界切出（原 L7997-8053）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, DESKTOP_VER, doLogout, errMsg, esc, goHome, IN_APP, IS_DESKTOP, ME, push,
   refreshNotifyBtn, renderSkinPrev, toast, ttsSetup */

/* ================= 账户 / 个人信息页 ================= */
async function openAccount() {
  push({ view: 'account', title: '账户' });
  try {
    const d = await api('/api/account');
    const qs = (await api('/api/sec_questions')).questions;
    $('#acct-name').textContent = d.username || (ME && ME.username) || '';
    $('#acct-email').textContent = d.email ? ('📧 ' + d.email) : '未绑定邮箱';
    $('#acct-role').textContent = (ME && ME.is_admin) ? '管理员' : '普通用户';
    $('#acct-email-in').value = d.email || '';
    $('#acct-secq').innerHTML = qs.map(q => `<option ${q === d.sec_question ? 'selected' : ''}>${esc(q)}</option>`).join('');
    $('#acct-oldpw').value = ''; $('#acct-newpw').value = ''; $('#acct-seca').value = '';
    $('#acct-app').classList.toggle('hidden', !(IN_APP || IS_DESKTOP));
    /* 「检查更新」在三端做的事不一样，按钮上的字也要跟着说实话：
       壳里是查新版本，浏览器里是清离线缓存重载（见 update.js 的 webReload）。 */
    const web = !(IN_APP || IS_DESKTOP);
    $('#acct-update').textContent = web ? '重新加载（清离线缓存）' : '检查更新';
    $('#acct-upd-hint').textContent = web
      ? '网页版每次打开就是最新的。界面卡在旧版本时，用这个把离线缓存清掉再载一次。'
      : '';
    $('#acct-app-t').textContent = IS_DESKTOP ? '💻 桌面版' : '📱 App';
    document.querySelectorAll('#acct-app .apk-only')            // 通知/切服务器只有安卓壳有
      .forEach(b => b.classList.toggle('hidden', !IN_APP));
    $('#acct-app-hint').classList.toggle('hidden', !IS_DESKTOP);
    $('#acct-dver').textContent = 'v' + (DESKTOP_VER || '?');
    renderSkinPrev();
    ttsSetup();
    refreshNotifyBtn();
  } catch (e) { toast(errMsg(e), true); }
}
$('#brand-logo').onclick = openAccount;
$('#account-btn').onclick = openAccount;
$('#home-btn').onclick = goHome;

$('#acct-email-save').onclick = async () => {
  try {
    await api('/api/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: $('#acct-email-in').value.trim() }) });
    const em = $('#acct-email-in').value.trim();
    $('#acct-email').textContent = em ? ('📧 ' + em) : '未绑定邮箱';
    toast('邮箱已保存');
  } catch (e) { toast(errMsg(e), true); }
};
$('#acct-pw-save').onclick = async () => {
  const np = $('#acct-newpw').value;
  if (!np) { toast('请输入新密码', true); return; }
  try {
    await api('/api/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ new_password: np, old_password: $('#acct-oldpw').value }) });
    $('#acct-oldpw').value = ''; $('#acct-newpw').value = ''; toast('密码已修改');
  } catch (e) { toast(errMsg(e), true); }
};
$('#acct-sec-save').onclick = async () => {
  if (!$('#acct-seca').value.trim()) { toast('请输入密保答案', true); return; }
  try {
    await api('/api/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sec_question: $('#acct-secq').value, sec_answer: $('#acct-seca').value }) });
    $('#acct-seca').value = ''; toast('密保已保存');
  } catch (e) { toast(errMsg(e), true); }
};
$('#acct-refresh').onclick = () => {
  if (window.GongkaoNative && window.GongkaoNative.reload) { try { window.GongkaoNative.reload(); return; } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ } }
  location.reload();
};
$('#acct-server').onclick = () => { try { window.GongkaoNative && window.GongkaoNative.changeServer(); } catch (_) { /* 外壳没注入这个桥就是在普通浏览器里，不该走这条路 */ } };
$('#acct-logout').onclick = doLogout;

/* ---------------- 分组：一次只显示一组，不再一屏堆八张卡 ----------------
   原来八张卡（邮箱 / 密码 / 密保 / 外观 / 朗读 / 外观定制 / 下载 / App）一路铺下去，
   改个头像要滚过密码和密保 —— 而这几件事互相之间根本没关系。

   分组标记写在 HTML 的 data-ag 上，这里只负责「显示哪一组」。
   **一套分组、两种呈现**：电脑上导航是左侧竖栏，手机上是顶部横向 chips，
   谁出现由 CSS 断点决定 —— 和底部标签栏 / 左侧导航栏是同一个路子。 */
let agCur = '';
function agGroups() {
  const out = [];
  document.querySelectorAll('#view-account [data-ag]').forEach(el => {
    if (!out.includes(el.dataset.ag)) out.push(el.dataset.ag);
  });
  return out;
}
function agShow(g) {
  agCur = g;
  document.querySelectorAll('#view-account [data-ag]').forEach(el => {
    /* 用 acct-off 而不是 hidden：#acct-tts / #acct-app 那两张卡的 hidden 是
       别处按「是不是桌面版」控制的，两边抢同一个类会互相踩。 */
    el.classList.toggle('acct-off', el.dataset.ag !== g);
  });
  document.querySelectorAll('#acct-nav [data-agb]').forEach(b =>
    b.classList.toggle('on', b.dataset.agb === g));
  const v = $('#view-account');
  if (v) v.scrollTop = 0;
}
function agRender() {
  const gs = agGroups();
  $('#acct-nav').innerHTML = gs.map(g =>
    `<button data-agb="${esc(g)}">${esc(g)}</button>`).join('');
  agShow(gs.includes(agCur) ? agCur : gs[0]);
}
$('#acct-nav').addEventListener('click', e => {
  const b = e.target.closest('[data-agb]'); if (b) agShow(b.dataset.agb);
});
agRender();
