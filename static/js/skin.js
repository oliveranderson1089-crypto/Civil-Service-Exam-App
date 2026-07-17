/* 外观：头像 / 壁纸
 *
 * 由 app.js 按它自己的区段边界切出（原 L10191-10270）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, appConfirm, lsGet, lsSet, toast */

/* ================= 外观：头像 / 壁纸 =================
   壁纸铺在 body 上（fixed，不跟着滚），上面盖一层可调浓度的蒙版保证正文看得清。
   登录页在没登录时读不到接口，所以把壁纸 URL 缓存进 localStorage，login.html 自己取。 */
let SKIN = { avatar: '', wall_app: '', wall_login: '' };
const skinDim = () => Math.min(90, Math.max(0, parseInt(lsGet('skinDim') || '55', 10)));

function applySkin() {
  // 头像出现在两处：左上角的 logo 和账户页顶部的大圆。
  // （原来只更新了 logo，账户页那个是 HTML 里写死的「公」，换了头像也不变。）
  [$('#brand-logo'), $('#acct-avatar')].forEach(el => {
    if (!el) return;
    if (SKIN.avatar) {
      el.style.backgroundImage = 'url("' + SKIN.avatar + '")';
      el.classList.add('has-img');
      el.textContent = '';
    } else {
      el.style.backgroundImage = '';
      el.classList.remove('has-img');
      el.textContent = '公';
    }
  });
  // 应用内壁纸
  const b = document.body;
  b.classList.toggle('has-wall', !!SKIN.wall_app);
  b.style.setProperty('--wall', SKIN.wall_app ? 'url("' + SKIN.wall_app + '")' : 'none');
  b.style.setProperty('--wall-dim', (skinDim() / 100).toFixed(2));
  // 登录页要用的，缓存到本地（它没登录，拿不到接口）
  lsSet('wallLogin', SKIN.wall_login || '');
  lsSet('skinDim', String(skinDim()));
}
async function loadSkin() {
  try {
    SKIN = await api('/api/skin');
    applySkin();
  } catch (_) {}
}
function renderSkinPrev() {
  [['avatar', '公'], ['wall_app', '无'], ['wall_login', '无']].forEach(([k, empty]) => {
    const el = $('#sk-' + k);
    if (!el) return;
    if (SKIN[k]) { el.style.backgroundImage = 'url("' + SKIN[k] + '")'; el.innerHTML = ''; }
    else { el.style.backgroundImage = ''; el.innerHTML = '<span>' + empty + '</span>'; }
  });
  $('#skin-dim').value = skinDim();
  $('#skin-dimv').textContent = skinDim() + '%';
  $('#skin-dim-row').classList.toggle('hidden', !SKIN.wall_app && !SKIN.wall_login);
}
document.addEventListener('change', async e => {
  const inp = e.target.closest('input[data-skin]');
  if (!inp || !inp.files || !inp.files[0]) return;
  const kind = inp.dataset.skin, f = inp.files[0];
  inp.value = '';
  if (f.size > 12 * 1024 * 1024) { toast('图片太大了（超过 12MB）', true); return; }
  toast('上传中…');
  try {
    const fd = new FormData(); fd.append('file', f);
    const d = await api('/api/skin/' + kind, { method: 'POST', body: fd });
    SKIN[kind] = d.url + '?t=' + Date.now();      // 加时间戳，绕过缓存立刻看到新图
    applySkin(); renderSkinPrev();
    toast(kind === 'avatar' ? '头像已更换' : '壁纸已更换');
  } catch (err) { toast(err.message, true); }
});
$('#view-account').addEventListener('click', async e => {
  const del = e.target.closest('[data-skindel]');
  if (!del) return;
  const kind = del.dataset.skindel;
  if (!SKIN[kind]) return;
  if (!await appConfirm(kind === 'avatar' ? '恢复成默认头像？' : '清除这张壁纸？', { title: '外观定制' })) return;
  try {
    await api('/api/skin/' + kind, { method: 'DELETE' });
    SKIN[kind] = ''; applySkin(); renderSkinPrev();
    toast('已恢复默认');
  } catch (err) { toast(err.message, true); }
});
$('#skin-dim').addEventListener('input', e => {
  lsSet('skinDim', e.target.value);
  $('#skin-dimv').textContent = e.target.value + '%';
  applySkin();
});
