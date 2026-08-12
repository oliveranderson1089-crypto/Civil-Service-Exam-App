/* 滚动日志：%APPDATA%\gongkao-assistant\logs\main-YYYYMMDD.log，保留 7 天。
 *
 * 为什么要有这东西：Windows 端出问题时人不在机器旁，网页里那句「xxx失败」的 toast
 * 背后是什么错，不开 DevTools 根本看不到。这里把主进程的每一步、渲染进程的每条
 * console 全部落盘，出错兜底页可以一键打开这个目录。
 *
 * 用 appendFileSync 而不是流：壳崩了的那一刻恰恰是最需要看到最后几行的时候，
 * 缓冲区里没落盘的日志等于没有。
 */
const fs = require('fs');
const path = require('path');

const KEEP_DAYS = 7;
const RING_MAX = 400;          // 内存里留最近这么多行，兜底页「复制诊断信息」直接带走

let dir = '';
let file = '';
let day = '';
const ring = [];

const two = (n) => String(n).padStart(2, '0');
const stamp = (d) => `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} `
  + `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}.`
  + String(d.getMilliseconds()).padStart(3, '0');
const dayKey = (d) => `${d.getFullYear()}${two(d.getMonth() + 1)}${two(d.getDate())}`;

function init(logDir) {
  dir = logDir;
  try { fs.mkdirSync(dir, { recursive: true }); } catch (_) { /* 建不出来就只往控制台打，不该拦住启动 */ }
  rotate();
  sweep();
}

/* 跨零点要换文件：壳经常开一整天，不换的话日期就没意义了 */
function rotate() {
  const k = dayKey(new Date());
  if (k === day && file) return;
  day = k;
  file = path.join(dir, `main-${k}.log`);
}

function sweep() {
  try {
    const cut = Date.now() - KEEP_DAYS * 86400_000;
    for (const f of fs.readdirSync(dir)) {
      if (!/^main-\d{8}\.log$/.test(f)) continue;
      const p = path.join(dir, f);
      if (fs.statSync(p).mtimeMs < cut) fs.unlinkSync(p);
    }
  } catch (_) { /* 清不掉旧日志无所谓，不值得为此报错 */ }
}

function write(level, tag, ...parts) {
  const msg = parts.map((x) => (typeof x === 'string' ? x : safeJson(x))).join(' ');
  const line = `[${stamp(new Date())}] [${level.padEnd(5)}] [${tag}] ${msg}`;
  ring.push(line);
  if (ring.length > RING_MAX) ring.shift();
  if (!process.env.GK_QUIET) console.log(line);       // 开发时直接看终端
  if (!dir) return;
  try { rotate(); fs.appendFileSync(file, line + '\n'); } catch (_) { /* 磁盘满/被占用：宁可丢日志也不能崩 */ }
}

function safeJson(x) {
  try { return JSON.stringify(x); } catch (_) { return String(x); }
}

module.exports = {
  init,
  info: (tag, ...a) => write('INFO', tag, ...a),
  warn: (tag, ...a) => write('WARN', tag, ...a),
  error: (tag, ...a) => write('ERROR', tag, ...a),
  tail: (n = RING_MAX) => ring.slice(-n).join('\n'),
  logDir: () => dir,
  logFile: () => file,
};
