/* 截图：抓屏 + 框选。
 *
 * Linux 壳走的是 xdg-desktop-portal（GNOME 自带的区域选择）；Windows 没有这种东西，
 * 只能自己来：desktopCapturer 抓一张整屏 → 铺一个覆盖整个显示器的窗口显示这张**静止的图**
 * → 人在上面拖矩形 → 按框裁下来交回网页。
 *
 * 覆盖窗显示的是抓好的图，所以它自己不会被拍进去；应用主窗口照常留在画面里
 * （和 Linux 那边一样：截的是「此刻屏幕上的样子」）。
 */
const path = require('path');
const { BrowserWindow, desktopCapturer, screen, ipcMain } = require('electron');

const SAFETY_MS = 2 * 60 * 1000;      // 没人操作就自己关掉：一个永远置顶的全屏窗会把人困住

/* 抓屏那一下单独拎出来：① 好加超时（Linux 壳那边 portal 调用也是 8 秒），
   ② 测试可以塞一张假图进来，不必真去抓屏（抓屏在无人值守的环境里会弹系统授权框）。 */
async function grabScreen(disp, scale) {
  const sources = await desktopCapturer.getSources({
    types: ['screen'],
    thumbnailSize: { width: Math.round(disp.size.width * scale),
                     height: Math.round(disp.size.height * scale) },
  });
  const src = sources.find((s) => String(s.display_id) === String(disp.id)) || sources[0];
  return src ? src.thumbnail : null;
}

const withTimeout = (p, ms, what) => Promise.race([
  p, new Promise((_r, rej) => setTimeout(() => rej(new Error(what + '超时')), ms)),
]);

module.exports = ({ log, js, toast, grab }) => {
  const capture = grab || grabScreen;
  let overlay = null;
  let shot = null;
  let scale = 1;

  function close() {
    if (!overlay) return;
    const w = overlay;
    overlay = null; shot = null;
    try { w.destroy(); } catch (_) { /* 已经关了 */ }
  }

  async function take() {
    if (overlay) { overlay.focus(); return; }
    const disp = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());  // 鼠标在哪个屏就截哪个
    scale = disp.scaleFactor || 1;
    let img;
    try {
      img = await withTimeout(capture(disp, scale), 8000, '抓屏');
    } catch (e) {
      log.error('shot', '抓屏失败', String(e));
      toast('截图失败：' + String(e).slice(0, 60));
      return;
    }
    if (!img || img.isEmpty()) {
      log.error('shot', '抓到的是空图');
      toast('抓不到屏幕内容（可能被系统的隐私设置挡了）');
      return;
    }
    shot = img;
    log.info('shot', '抓屏成功', `${shot.getSize().width}x${shot.getSize().height}`, 'scale=' + scale);

    overlay = new BrowserWindow({
      x: disp.bounds.x, y: disp.bounds.y,
      width: disp.bounds.width, height: disp.bounds.height,
      frame: false, resizable: false, movable: false, minimizable: false,
      skipTaskbar: true, alwaysOnTop: true, backgroundColor: '#000000', show: false,
      webPreferences: {
        preload: path.join(__dirname, 'preload-shot.js'),
        sandbox: true, contextIsolation: true,
      },
    });
    overlay.setAlwaysOnTop(true, 'screen-saver');
    overlay.loadFile(path.join(__dirname, 'shot.html'));
    overlay.webContents.once('did-finish-load', () => {
      if (!overlay) return;
      overlay.webContents.send('shot:image', shot.toDataURL());
      overlay.show();
      overlay.focus();
    });
    const timer = setTimeout(() => {
      if (overlay) { log.info('shot', '两分钟没动作，自己关掉'); close(); }
    }, SAFETY_MS);
    overlay.on('closed', () => clearTimeout(timer));
  }

  ipcMain.on('shot:cancel', () => { log.info('shot', '取消'); close(); });

  ipcMain.on('shot:done', (e, r) => {
    if (!shot || !overlay) return;
    // 页面里的坐标是 CSS 像素（=DIP），图是物理像素，差一个缩放比。
    // 不乘这个比例，在 125%/150% 缩放的 Windows 上会裁错位置。
    const rect = {
      x: Math.round(r.x * scale), y: Math.round(r.y * scale),
      width: Math.round(r.width * scale), height: Math.round(r.height * scale),
    };
    let cut;
    try { cut = shot.crop(rect); } catch (err) {
      log.error('shot', '裁剪失败', JSON.stringify(rect), String(err));
      toast('截图裁剪失败');
      close();
      return;
    }
    log.info('shot', '截好', `${rect.width}x${rect.height}`);
    close();
    js(`window.__onShot && window.__onShot(${JSON.stringify(cut.toDataURL())})`);
  });

  return { take };
};
