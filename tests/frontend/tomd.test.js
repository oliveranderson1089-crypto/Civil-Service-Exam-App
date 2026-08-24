/* 云盘「转成 Markdown」的那条路。
 *
 * 三件事在界面上点得到、坏了却没声音：
 *   ① 菜单项该出现在能转的文件上，不该出现在 zip、也不该出现在文件夹上；
 *   ② 扫描页多的时候必须**先问一句**再开跑 —— 一本 300 页的扫描书全转要十几分钟，
 *      替用户做主两个方向都是错的（擅自全转 = 干等，擅自截断 = 给一份缺了半本的文件）；
 *   ③ 用户按了取消，就一个请求都不许发出去。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// probe / 建任务 / 查任务 三个接口的假回应
function server({ scan = 0, pages = 10, status = 'done' } = {}) {
  return (url) => {
    if (url.includes('/tomd/probe')) {
      return { json: { pages, scan_pages: scan, kind: 'pdf', est_sec: 3, ocr_limit: 30 } };
    }
    if (/\/api\/drive\/tomd\/\d+/.test(url)) {
      return { json: { id: 1, status, message: '转好了 · 10 页 · 8 个标题' } };
    }
    if (/\/api\/drive\/\d+\/tomd$/.test(url)) return { json: { task_id: 1 } };
    return {};
  };
}

function menuHtml(h, name, isDir = false) {
  h.run(`dvMenu(0, 0, 7, ${JSON.stringify(name)}, true, ${isDir})`);
  return h.window.document.getElementById('dv-menu').innerHTML;
}

test('菜单：能转的格式才给这一项', (t) => {
  const h = boot({ fetch: server() }); t.after(() => h.close());
  assert.match(menuHtml(h, '讲义.pdf'), /dvm-md/);
  assert.match(menuHtml(h, '笔记.docx'), /dvm-md/);
  assert.doesNotMatch(menuHtml(h, '资料包.zip'), /dvm-md/, 'zip 转不了，不该出现在菜单里');
  assert.doesNotMatch(menuHtml(h, '四川省考', true), /dvm-md/, '文件夹转不了');
});

test('原生 PDF：不问直接转，转完带去 AI 产出', async (t) => {
  const h = boot({ fetch: server({ scan: 0 }) }); t.after(() => h.close());
  h.run('appConfirm = async () => true');
  h.run('openAiOut = () => { window.__opened = true; }');
  h.run('dvToMd(7, "讲义.pdf")');
  await sleep(1600);
  const posts = h.calls.filter(c => c.method === 'POST');
  assert.strictEqual(posts.length, 1);
  assert.strictEqual(JSON.parse(posts[0].body).all_pages, false, '没扫描页就别开全量 OCR');
  assert.ok(h.window.__opened, '转完该能一键去看成品');
});

test('扫描页超上限：先问一句，选「只转前 30 页」', async (t) => {
  const h = boot({ fetch: server({ scan: 180, pages: 300 }) }); t.after(() => h.close());
  /* 这条路上会问两次：先问「要不要全部识别」，转完再问「现在去看吗」。
     桩要把两次都记下来，只留最后一次的话，断言到的是完成提示，问的那句反而丢了。 */
  h.run('window.__asks = []; appConfirm = async (msg, o) => '
        + '{ window.__asks.push([msg, JSON.stringify(o || {})]); return "alt"; }');
  h.run('openAiOut = () => {}');
  h.run('dvToMd(7, "扫描讲义.pdf")');
  await sleep(1600);
  const [msg, opts] = h.window.__asks[0];
  assert.match(msg, /180 页/, '要把页数说清楚');
  assert.match(msg, /分钟/, '要把要等多久说清楚');
  assert.match(opts, /只转前 30 页/);
  const posts = h.calls.filter(c => c.method === 'POST');
  assert.strictEqual(JSON.parse(posts[0].body).all_pages, false);
});

test('扫描页超上限：选「全部转」就全转', async (t) => {
  const h = boot({ fetch: server({ scan: 180, pages: 300 }) }); t.after(() => h.close());
  h.run('appConfirm = async () => true');
  h.run('openAiOut = () => {}');
  h.run('dvToMd(7, "扫描讲义.pdf")');
  await sleep(1600);
  const posts = h.calls.filter(c => c.method === 'POST');
  assert.strictEqual(JSON.parse(posts[0].body).all_pages, true);
});

test('按了取消，一个请求都不发', async (t) => {
  const h = boot({ fetch: server({ scan: 180, pages: 300 }) }); t.after(() => h.close());
  h.run('appConfirm = async () => false');
  h.run('dvToMd(7, "扫描讲义.pdf")');
  await sleep(300);
  assert.strictEqual(h.calls.filter(c => c.method === 'POST').length, 0);
});

test('转换失败要说出来，不能静悄悄', async (t) => {
  const h = boot({ fetch: server({ status: 'error' }) }); t.after(() => h.close());
  h.run('appConfirm = async () => true');
  h.run('dvToMd(7, "坏文件.pdf")');
  await sleep(1600);
  assert.match(h.toasts.map(x => x.msg).join(' '), /转换失败/);
});

/* 成品是在「AI 产出」里读的（转换结果就落在那儿）。整本书转出来一屏几十行，
   固定字号读不下去 —— 这一段盯的是「字号跟着层级走」这件事本身：
   标题得真的渲染成 h1/h2（而不是把 ## 原样印出来），A+ 调的是正文基准，
   标题在 CSS 里是 em，会跟着一起缩放。 */
test('AI 产出：Markdown 渲染成标题，A+ / A− 调字号并记住', async (t) => {
  const md = '# 第一章 总纲\n\n正文一段。\n\n## 第一节 前言\n\n正文两段。';
  const h = boot({
    fetch: (url) => (url.includes('/api/aiout/9')
      ? { json: { id: 9, title: '讲义', body: md } }
      : { json: { items: [], retain_days: 30 } }),
  });
  t.after(() => h.close());
  h.run('aoView({ id: 9, title: "讲义" })');
  await sleep(60);
  const doc = h.window.document;
  const body = doc.getElementById('ao-rb');
  assert.ok(body, '产出正文容器要在');
  assert.strictEqual(body.querySelectorAll('h1').length, 1);
  assert.strictEqual(body.querySelectorAll('h2').length, 1);
  assert.doesNotMatch(body.textContent, /^#/m, 'Markdown 记号不该原样印出来');

  const before = parseFloat(body.style.fontSize);
  doc.getElementById('ao-fplus').click();
  const after = parseFloat(h.window.document.getElementById('ao-rb').style.fontSize);
  assert.ok(after > before, 'A+ 该把正文调大');
  assert.strictEqual(h.window.localStorage.getItem('ao:font'), String(after),
                     '下次进来还得是这个字号');
});
