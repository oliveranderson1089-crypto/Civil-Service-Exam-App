/* 登录 / 注册 / 找回密码 三页的自定义壁纸。
 *
 * 登录后应用会把壁纸 URL 缓存进 localStorage；这三页在登录之前，问不到接口，
 * 只能从缓存里取。取到就盖住天光底（auth.css 里那条 body.has-wall #dl-sky）——
 * 用户自己选的图优先于美术底。
 *
 * 天光底本身不在这儿：那是 js/daylight.js 的 dlPaintAuth，和启动屏共用一张色表。
 */
(function () {
  try {
    const w = localStorage.getItem('wallLogin');
    if (!w) return;
    const dim = Math.min(90, Math.max(0, parseInt(localStorage.getItem('skinDim') || '55', 10))) / 100;
    document.body.style.setProperty('--wall', 'url("' + w + '")');
    document.body.style.setProperty('--wall-dim', dim.toFixed(2));
    document.body.classList.add('has-wall');
  } catch (_) { /* 隐私模式下 localStorage 会抛异常：那就用天光底，不该拦住登录 */ }
})();
