/* 账户 / 个人信息页
 *
 * 由 app.js 按它自己的区段边界切出（原 L7997-8053）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, DESKTOP_VER, IN_APP, IS_DESKTOP, ME, api,
   doLogout, esc, goHome, push, refreshNotifyBtn, renderSkinPrev,
   toast, ttsSetup */

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
    $('#acct-app-t').textContent = IS_DESKTOP ? '💻 桌面版' : '📱 App';
    document.querySelectorAll('#acct-app .apk-only')            // 通知/切服务器只有安卓壳有
      .forEach(b => b.classList.toggle('hidden', !IN_APP));
    $('#acct-app-hint').classList.toggle('hidden', !IS_DESKTOP);
    $('#acct-dver').textContent = 'v' + (DESKTOP_VER || '?');
    renderSkinPrev();
    ttsSetup();
    refreshNotifyBtn();
  } catch (e) { toast(e.message, true); }
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
  } catch (e) { toast(e.message, true); }
};
$('#acct-pw-save').onclick = async () => {
  const np = $('#acct-newpw').value;
  if (!np) { toast('请输入新密码', true); return; }
  try {
    await api('/api/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ new_password: np, old_password: $('#acct-oldpw').value }) });
    $('#acct-oldpw').value = ''; $('#acct-newpw').value = ''; toast('密码已修改');
  } catch (e) { toast(e.message, true); }
};
$('#acct-sec-save').onclick = async () => {
  if (!$('#acct-seca').value.trim()) { toast('请输入密保答案', true); return; }
  try {
    await api('/api/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sec_question: $('#acct-secq').value, sec_answer: $('#acct-seca').value }) });
    $('#acct-seca').value = ''; toast('密保已保存');
  } catch (e) { toast(e.message, true); }
};
$('#acct-refresh').onclick = () => {
  if (window.GongkaoNative && window.GongkaoNative.reload) { try { window.GongkaoNative.reload(); return; } catch (_) {} }
  location.reload();
};
$('#acct-server').onclick = () => { try { window.GongkaoNative && window.GongkaoNative.changeServer(); } catch (_) {} };
$('#acct-logout').onclick = doLogout;
