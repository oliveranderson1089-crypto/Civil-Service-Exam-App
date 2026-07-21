/* mdToHtml：把 AI 生成的 Markdown 渲染成 HTML。
 *
 * 为什么这块要当安全边界看：它被 5 个模块用来渲染 **AI 生成的内容**
 * （AI 助手对话、新闻摘要三行式、范文拆解、古诗文讲解、板块基础知识点），
 * 而新闻那一路的源头是爬虫抓的外站页面（12371.cn / 人民网）——
 * 等于外部文本经 AI 转手流进了 innerHTML。
 *
 * 原先的 href 是直接拼的：`<a href="$2">`，两条路都能打穿（都实测过）：
 *   [x](javascript:alert%281%29)              点一下就执行
 *   [x](https://a"onmouseover="alert(1))      E() 只转义 &<>、不管 "，引号一闭合就能注入
 *                                            事件处理器（浏览器真把它解析成了 onmouseover 属性）
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

function html(h, src) { return h.run('mdToHtml')(src); }

// 光看输出字符串不够 —— 得让浏览器真去解析，才知道注入成没成
function attrsOf(h, src) {
  const box = h.window.document.createElement('div');
  box.innerHTML = html(h, src);
  const a = box.querySelector('a');
  return a ? [...a.attributes].map(x => x.name.toLowerCase()) : [];
}

test('正常链接照常工作（别为了安全把功能废了）', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.match(html(h, '[百度](https://baidu.com)'), /href="https:\/\/baidu\.com"/);
  assert.match(html(h, '[看图](/api/materials/1/view)'), /href="\/api\/materials\/1\/view"/);
  assert.match(html(h, '[跳转](#top)'), /href="#top"/);
  assert.match(html(h, '[写信](mailto:a@b.c)'), /href="mailto:a@b\.c"/);
});

test('javascript: 链接不许出现在 href 里', (t) => {
  const h = boot(); t.after(() => h.close());
  for (const p of ['[点我](javascript:alert(1))', '[点我](javascript:alert%281%29)',
                   '[点我](JavaScript:alert(1))', '[点我](  javascript:alert(1))']) {
    assert.doesNotMatch(html(h, p), /href="javascript:/i, `${p} 打穿了 —— 点一下就执行`);
  }
});

test('data: / vbscript: 也挡掉', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.doesNotMatch(html(h, '[点我](data:text/html,<script>alert(1)</script>)'), /href="data:/i);
  assert.doesNotMatch(html(h, '[点我](vbscript:msgbox(1))'), /href="vbscript:/i);
});

test('URL 里塞引号注入不了事件处理器（解析成 DOM 后验）', (t) => {
  const h = boot(); t.after(() => h.close());
  for (const p of ['[点我](https://a"onmouseover="alert(1))',
                   "[点我](https://a'onclick='alert(1))"]) {
    const attrs = attrsOf(h, p);
    const evil = attrs.filter(n => n.startsWith('on'));
    assert.deepStrictEqual(evil, [], `${p} 注入出了 ${evil} —— 鼠标划过就执行`);
    assert.deepStrictEqual(attrs.sort(), ['href', 'rel', 'target']);
  }
});

test('挡掉的链接落到 # 上，文字还在（不能整段消失）', (t) => {
  const h = boot(); t.after(() => h.close());
  const out = html(h, '[这是链接文字](javascript:alert(1))');
  assert.match(out, /href="#"/);
  assert.match(out, /这是链接文字/, '把整个链接吞了，用户会以为内容丢了');
});

test('尖括号标签一律转义，进不了 DOM', (t) => {
  const h = boot(); t.after(() => h.close());
  const box = h.window.document.createElement('div');
  box.innerHTML = html(h, '<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>');
  assert.strictEqual(box.querySelector('script'), null);
  assert.strictEqual(box.querySelector('img'), null);
});

test('Markdown 该有的功能都在', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.match(html(h, '# 标题'), /<h1>标题<\/h1>/);
  assert.match(html(h, '**粗**'), /<strong>粗<\/strong>/);
  assert.match(html(h, '`码`'), /<code>码<\/code>/);
  assert.match(html(h, '> 引用'), /<blockquote>/);
  assert.match(html(h, '- 一项'), /<ul><li>一项<\/li>/);
  assert.match(html(h, '1. 一项'), /<ol><li>一项<\/li>/);
  assert.match(html(h, '普通一段'), /<p>普通一段<\/p>/);
});

test('AI 常出的那种混排内容不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  const real = '## 三行式\n\n**事件**：某地推进垃圾分类。\n\n- 角度：基层治理\n- 素材：[原文](https://example.com/a?b=1&c=2)\n\n```\n代码块\n```\n';
  const out = html(h, real);
  assert.match(out, /<h2>三行式<\/h2>/);
  assert.match(out, /href="https:\/\/example\.com\/a\?b=1&amp;c=2"/, 'URL 里的 & 该转义成 &amp;');
  assert.match(out, /<pre|<code/);
});

test('空输入 / 奇怪输入不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.strictEqual(typeof html(h, ''), 'string');
  assert.strictEqual(typeof html(h, '[没闭合的链接]('), 'string');
  assert.strictEqual(typeof html(h, '[]()'), 'string');
});

// ---- 数学公式：AI 讲数量关系爱用 LaTeX，原来 $...$ 原样漏出一堆反斜杠没法读 ----
function box(h, src) { const b = h.window.document.createElement('div'); b.innerHTML = html(h, src); return b; }

test('行内 $\\frac{}{}$ 渲染成分数（分子/分母各就各位）', (t) => {
  const h = boot(); t.after(() => h.close());
  const b = box(h, '男生占全班的 $\\frac{5}{8}$，也就是 62.5%。');
  const fr = b.querySelector('.tfr');
  assert.ok(fr, '没渲染出分数结构');
  assert.strictEqual(fr.querySelector('.tfn').textContent, '5');
  assert.strictEqual(fr.querySelector('.tfd').textContent, '8');
  assert.doesNotMatch(b.textContent, /\\frac|\$/, '还漏着原始 LaTeX');
});

test('\\text{中文} 与上标/根号/符号都认', (t) => {
  const h = boot(); t.after(() => h.close());
  const b = box(h, '$\\frac{\\text{男生}}{\\text{全班}} = \\frac{5}{8}$，$x^2$，$\\sqrt{9}=3$，$5 \\times 3$');
  assert.match(b.textContent, /男生/);
  assert.match(b.textContent, /全班/);
  assert.ok(b.querySelector('sup'), '上标没出来');
  assert.ok(b.querySelector('.tsq'), '根号没出来');
  assert.match(b.textContent, /×/, '\\times 没转成 ×');
});

test('块级 $$...$$ 单独成块居中', (t) => {
  const h = boot(); t.after(() => h.close());
  const b = box(h, '推导如下：\n\n$$\\frac{A}{B} = \\frac{m}{n}$$\n\n所以成立。');
  const blk = b.querySelector('.tex-block');
  assert.ok(blk, '块级公式没成块');
  assert.strictEqual(b.querySelectorAll('.tfr').length, 2, '两个分数都该在');
});

test('公式里的下划线/星号不被 markdown 啃掉', (t) => {
  const h = boot(); t.after(() => h.close());
  const b = box(h, '设 $a_1$ 与 $a_2$，$P(A_i)$ 表示概率。');
  assert.ok(b.querySelector('sub'), '下标被 markdown 吞了');
  assert.doesNotMatch(b.textContent, /_/, '还漏着裸下划线');
});

test('数学不炸 + XSS：公式里的尖括号照样转义', (t) => {
  const h = boot(); t.after(() => h.close());
  const b = box(h, '$a < b$ 且 $<img src=x onerror=alert(1)>$');
  assert.strictEqual(b.querySelector('img'), null, '公式里注入了 img');
  assert.match(b.textContent, /a\s*<\s*b|a[−–-]?\s*<\s*b|a.*b/);
  assert.strictEqual(typeof html(h, '$\\frac{1'), 'string', '残缺公式把渲染搞崩了');
});

test('转义美元 \\$ 不当公式定界符', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.match(html(h, '花了 \\$5 又花了 \\$10'), /\$5|\$10/);
});
