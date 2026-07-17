/* 特征化测试：给 app.js 现在的行为拍快照，拆模块时用它对比。
 *
 * 拆模块唯一该保证的事，是**行为一个字节都没变**。而 app.js 有 377 条顶层执行语句
 * （415 个事件绑定）、694 个顶层符号，人眼盯不住哪个掉了。这里不测「功能对不对」
 * （那是别的测试的事），只测「跟拆之前一模一样」。
 *
 * 快照存在 __snapshots__/ 下，是 git 里的文件 —— 拆分时它变红，就说明动了不该动的。
 * 要是确实有意改变（比如加了新功能），跑 UPDATE_SNAPSHOT=1 npm test 重拍。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { boot } = require('./harness');

const SNAP_DIR = path.join(__dirname, '__snapshots__');
const UPDATE = process.env.UPDATE_SNAPSHOT === '1';

function snapshot(name, actual) {
  fs.mkdirSync(SNAP_DIR, { recursive: true });
  const file = path.join(SNAP_DIR, name + '.txt');
  const text = Array.isArray(actual) ? actual.join('\n') : String(actual);
  if (UPDATE || !fs.existsSync(file)) {
    fs.writeFileSync(file, text + '\n');
    return { created: true };
  }
  const want = fs.readFileSync(file, 'utf8').trimEnd();
  if (text !== want) {
    // 只报差异，别把几百行糊到终端上
    const a = text.split('\n'), b = want.split('\n');
    const added = a.filter(x => !b.includes(x));
    const gone = b.filter(x => !a.includes(x));
    assert.fail(`${name} 与快照不符：\n  多了 ${added.length} 条: ${added.slice(0,5).join(' | ')}\n` +
                `  少了 ${gone.length} 条: ${gone.slice(0,5).join(' | ')}\n` +
                `  （确认是有意改动就跑 UPDATE_SNAPSHOT=1 npm test 重拍）`);
  }
  return { created: false };
}

test('事件绑定：415 条，一条都不能少（顺序也不能变）', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.ok(h.bindings.length > 400, `只绑上了 ${h.bindings.length} 条，掉了一大片`);
  snapshot('bindings', h.bindings);
});

test('全局契约：挂到 window 上的符号（改这些 = 改跟安卓/桌面壳的协议）', (t) => {
  const h = boot(); t.after(() => h.close());
  const own = Object.keys(h.window).filter(k =>
    (k.startsWith('__') || /^(appBack|toast|checkUpdate|fabClose|Reader)$/.test(k)) && k !== '__T' && k !== '__run' && k !== '__toasts');
  snapshot('window-contract', own.sort());
});

test('顶层符号：694 个，拆分后一个都不能丢', (t) => {
  const h = boot(); t.after(() => h.close());
  const src = fs.readFileSync(path.join(__dirname, '../../static/app.js'), 'utf8');
  const names = new Set();
  for (const m of src.matchAll(/^(?:async )?function ([\w$]+)\s*\(/gm)) names.add(m[1]);
  for (const m of src.matchAll(/^(?:const|let|var) ([\w$]+)\s*=/gm)) names.add(m[1]);
  assert.ok(names.size > 650, `只剩 ${names.size} 个顶层符号`);
  snapshot('top-symbols', [...names].sort());
});

test('启动时只打这些接口（多打 = 白费流量，少打 = 界面空着）', (t) => {
  const h = boot(); t.after(() => h.close());
  snapshot('boot-requests', h.calls.map(c => c.method + ' ' + c.url.replace(/\d+/g, 'N')).sort());
});

test('SYNC_REFRESH 的视图清单', (t) => {
  const h = boot(); t.after(() => h.close());
  snapshot('sync-views', h.run('Object.keys(SYNC_REFRESH)').sort());
});
