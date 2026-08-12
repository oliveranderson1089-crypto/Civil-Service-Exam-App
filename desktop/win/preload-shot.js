/* 框选覆盖窗的桥。只有三件事：拿图、交框、取消。 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('__shot', {
  onImage: (cb) => ipcRenderer.on('shot:image', (e, dataUrl) => cb(dataUrl)),
  done: (rect) => ipcRenderer.send('shot:done', rect),
  cancel: () => ipcRenderer.send('shot:cancel'),
});
