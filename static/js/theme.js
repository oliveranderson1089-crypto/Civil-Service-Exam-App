/* 主题（日间/夜间/跟随系统）+ AI 面板分层返回
 *
 * 由 app.js 按它自己的区段边界切出（原 L8388-8439）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, aiProjectId, aiShow, loadAiHome, lsGet, lsSet,
   openAiProject, renderAiProjects, toast */

/* ================= 主题：日间 / 夜间 / 跟随系统 ================= */
const _themeMedia = window.matchMedia ? matchMedia('(prefers-color-scheme: dark)') : null;
/* Android WebView 里 prefers-color-scheme 恒为 light（除非 app 显式开启），
   所以「跟随系统」在 APK 中失灵。原生壳会把系统夜间状态写进 window.__sysDark，优先采信它。 */
function sysIsDark() {
  if (typeof window.__sysDark === 'boolean') return window.__sysDark;
  try {
    if (window.GongkaoNative && typeof GongkaoNative.sysDark === 'function') return !!GongkaoNative.sysDark();
  } catch (_) {}
  return !!(_themeMedia && _themeMedia.matches);
}
function applyTheme() {
  const mode = lsGet('theme') || 'auto';
  const dark = mode === 'dark' || (mode === 'auto' && sysIsDark());
  document.body.classList.toggle('dark', dark);
  document.querySelectorAll('.theme-opt').forEach(b => b.classList.toggle('on', b.dataset.theme === mode));
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = dark ? '#0f141e' : '#1a6fb5';
  if (window.__padTheme) window.__padTheme();      // 草稿纸墨色跟着日/夜间翻转（钩子在脚本末尾才挂，早期调用自动跳过）
}
// 原生壳在系统深色模式切换时调用
window.__onSysTheme = function (dark) { window.__sysDark = !!dark; applyTheme(); };
document.addEventListener('click', e => {
  const b = e.target.closest('.theme-opt'); if (!b || !b.dataset.theme) return;
  lsSet('theme', b.dataset.theme);
  applyTheme();
  toast(b.textContent.trim() + ' 已应用');
});
if (_themeMedia) {
  try { _themeMedia.addEventListener('change', applyTheme); }
  catch (_) { _themeMedia.addListener(applyTheme); }  // 旧 WebView
}
// 回到前台时系统可能已切到夜间（跟随系统模式下重新判定一次）
document.addEventListener('visibilitychange', () => { if (!document.hidden) applyTheme(); });
applyTheme();

/* ================= AI 面板分层返回（返回上一级而非直接关闭） ================= */
function aiBack() {
  if ($('#ai-panel').classList.contains('hidden')) return false;
  if (!$('#aiv-chat').classList.contains('hidden')) {
    // 会话 → 所属项目详情（若有）或首页
    if (aiProjectId && ($('#ai-panel')._projects || []).some(p => p.id === aiProjectId)) {
      loadAiHome().then(() => openAiProject(aiProjectId));
    } else { aiShow('home'); loadAiHome(); }
    return true;
  }
  if (!$('#aiv-project').classList.contains('hidden')) { renderAiProjects(); aiShow('projects'); return true; }
  if (!$('#aiv-projects').classList.contains('hidden')) { aiShow('home'); loadAiHome(); return true; }
  $('#ai-panel').classList.add('hidden');
  return true;
}
