/* 主题风格（宣纸与印 / 天光琉璃 / 墨山 / 节气色）。
 *
 * 这一层最容易出的四种错，都不报错、只会「看着不对」或者「关不掉」：
 *
 *   1) **关不掉** —— 换回默认时不清 body 上那批 inline 变量，界面还挂着上一套的色。
 *      用户点了「默认」却没变回去，是这一整个功能最伤的失败。
 *   2) **日夜和主题打架** —— 主题开着且跟随天光时，日夜该由时刻决定；
 *      不然白天开夜间模式，主题算出来的浅色底配上 body.dark 的深色卡，一屏花的。
 *   3) **跨零点断掉** —— 和启动屏是同一个坑：23:00 的下一个锚点是次日 05:00。
 *   4) **色相被时间带跑** —— 节气色靠六个色相识别模块，色相全天必须锁死。
 *
 * 另外主题要在**第一帧**就位（在 core.js 之前），所以最后一条钉的是它不依赖 core。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { boot } = require('./harness');

const ROOT = path.resolve(__dirname, '../..');
/* 两端各自的全部主题。第二代那十套（五种画风 × 两端）也在里面 ——
   下面那些通用的用例（对比度、跨零点、壁纸、书封、清变量）本来就该一视同仁地扫过它们，
   加进来才是"加一套主题就自动多一份体检"。 */
const MODES = ['paper', 'glass', 'ink', 'hue',
  'meow', 'witch', 'pixel', 'tempura', 'garden'];
const DESK = ['celadon', 'dossier', 'night', 'studio',
  'meowdesk', 'witchdesk', 'pixeldesk', 'tempuradesk', 'gardendesk'];
const ALL = [...MODES, ...DESK];
const CLOCKED = ALL.filter(m => m !== 'night');              // 夜航只有一档，跟时刻无关
const isDesk = (m) => DESK.includes(m);

/* 把窗口宽度摆到某一端。jsdom 默认 1024（= 电脑端），手机端的用例要自己拧窄 ——
   两端出哪四套、写哪个键，全看这个数（js/daylight.js 的 dlIsDesk）。 */
function width(h, px) { h.window.innerWidth = px; }
function atEnd(h, desk) { width(h, desk ? 1280 : 390); }

/* 开一套主题：摆好宽度、写进 localStorage 再重刷。走的是真路径，和用户点一下一模一样。
   键名跟着这一端走：电脑端记在 artThemeDesk，手机端记在 artTheme。 */
function use(h, mode, clock = '1') {
  const desk = mode ? isDesk(mode) : h.window.innerWidth >= 761;
  atEnd(h, desk);
  h.run(`localStorage.setItem(${JSON.stringify(desk ? 'artThemeDesk' : 'artTheme')}, ${JSON.stringify(mode)});
         localStorage.setItem('artClock', ${JSON.stringify(clock)});
         dlArtApply(); applyTheme();`);
}
const cls = (h) => String(h.window.document.body.className);
const styleOf = (h, name) => h.run(`document.body.style.getPropertyValue(${JSON.stringify(name)})`);

test('默认不开任何主题：body 上没有 art-* 类，也没有主题变量', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.ok(!/\bart-/.test(cls(h)), '默认状态就带上了主题类：' + cls(h));
  assert.strictEqual(styleOf(h, '--bg'), '', '默认状态不该往 body 上写 --bg');
});

test('八套主题都能开起来，各自挂上自己的类和整套变量', (t) => {
  const h = boot(); t.after(() => h.close());
  /* 认**类名 token**，不认子串：art-meowdesk 里就含着 art-meow，
     用 includes 判断会把"电脑版开着"误报成"手机版没摘干净"。
     真实代码两边都是按 token 走的（classList.toggle、CSS 的类选择器），
     所以这里也必须按 token 断言，否则测的是一件不存在的事。 */
  const has = (c) => cls(h).split(/\s+/).includes(c);
  for (const m of ALL) {
    use(h, m);
    assert.ok(has('art-' + m), `${m}: 没挂上 art-${m}`);
    assert.ok(has('art-on'), `${m}: 没挂上 art-on`);
    // 横构图启动屏那一套布局只该给电脑端那几套
    assert.strictEqual(has('art-desk'), isDesk(m), `${m}: art-desk 挂错了`);
    // 别的那些套的类必须同时摘掉，不然 CSS 会两套一起生效
    for (const other of ALL.filter(x => x !== m)) {
      assert.ok(!has('art-' + other), `${m}: 上一套 art-${other} 没摘干净`);
    }
    for (const k of ['--bg', '--text', '--muted', '--blue', '--blue-fill']) {
      assert.ok(styleOf(h, k), `${m}: ${k} 没写上`);
    }
  }
});

test('换回默认要把痕迹清干净——不清就是「关不掉」', (t) => {
  const h = boot(); t.after(() => h.close());
  use(h, 'hue');
  assert.ok(styleOf(h, '--art-t0'), '节气色没写上模块色，这条测试就没意义了');
  use(h, '');
  assert.ok(!/\bart-/.test(cls(h)), '关掉后 body 上还挂着主题类：' + cls(h));
  // 电脑端那几套多用了 --art-band / --art-rule，清单里漏一个就是它们"关不掉"
  use(h, 'dossier');
  assert.ok(styleOf(h, '--art-band'), '卷宗没写上封条色，这条测试就没意义了');
  use(h, '');
  for (const k of ['--bg', '--bg2', '--card', '--line', '--text', '--muted', '--blue',
    '--blue-fill', '--art-t0', '--art-ink', '--art-blk', '--art-glass', '--art-band', '--art-rule']) {
    assert.strictEqual(styleOf(h, k), '', `关掉后 ${k} 还留在 body 上`);
  }
});

test('跟随天光时日夜由时刻定；关掉跟随则交还给「外观」', (t) => {
  const h = boot(); t.after(() => h.close());
  // 白昼该是亮的、夜里该是暗的——不管「外观」选的是什么
  h.run("localStorage.setItem('theme','dark')");
  use(h, 'paper');
  const now = h.run('dlArtDark()');
  assert.strictEqual(typeof now, 'boolean', '主题开着时 dlArtDark 应该给出结论');
  assert.strictEqual(h.run('dlArtAt("paper", 13).dark < 0.5'), true, '白昼算成了暗环境');
  assert.strictEqual(h.run('dlArtAt("paper", 23).dark > 0.5'), true, '夜里算成了亮环境');

  // 关掉跟随：dlArtDark 交出决定权（返回 null），日夜回到 theme 那三个按钮
  use(h, 'paper', '0');
  assert.strictEqual(h.run('dlArtDark()'), null, '关掉跟随后主题还在抢日夜的决定权');
  assert.ok(h.window.document.body.classList.contains('dark'), '交还之后没听「夜间」的');

  // 没开主题时也一样不该插手
  use(h, '');
  assert.strictEqual(h.run('dlArtDark()'), null, '没开主题却还在管日夜');
});

test('跨零点连续：凌晨两点仍在夜色里，不跳回白天', (t) => {
  const h = boot(); t.after(() => h.close());
  for (const m of CLOCKED) {
    const night = h.plain(`dlArtAt(${JSON.stringify(m)}, 23)`);
    const small = h.plain(`dlArtAt(${JSON.stringify(m)}, 2)`);
    const dawn = h.plain(`dlArtAt(${JSON.stringify(m)}, 5)`);
    assert.ok(small.dark > 0.5, `${m}: 凌晨两点被算成了亮环境`);
    assert.notStrictEqual(small.bg, dawn.bg, `${m}: 凌晨两点直接等于黎明，这一段没在插值`);
    assert.notStrictEqual(small.bg, night.bg, `${m}: 凌晨两点等于 23:00，跨零点那段断了`);
  }
});

test('相邻时刻之间没有跳变（整个一天扫一遍）', (t) => {
  const h = boot(); t.after(() => h.close());
  const lum = (c) => (c.match(/\d+/g) || [0, 0, 0]).slice(0, 3).reduce((a, b) => +a + +b, 0);
  for (const m of ALL) {
    let prev = null, worst = 0;
    for (let x = 0; x < 24; x += 0.25) {
      const v = h.plain(`dlArtAt(${JSON.stringify(m)}, ${x})`);
      const l = lum(v.bg);
      if (prev !== null) worst = Math.max(worst, Math.abs(l - prev));
      prev = l;
    }
    // 一天里最陡的那一步：15 分钟之内底色不该整块换掉
    assert.ok(worst < 90, `${m}: 某处 15 分钟内底色跳了 ${worst}，说明有一段不是插出来的`);
  }
});

/* 这一条是被渲染出来才发现的失效，也是这个功能最容易翻的车：
   晨昏两段是「暗环境 → 亮环境」，底色由深走浅、字色由浅走深，两条线在中间交叉。
   插值的话那一段卡片是中灰、字也是中灰，正文直接看不见 —— 6:00 那一版四套全中。
   现在读字的那一面（卡片底/字色/玻璃浓度）是到点硬翻的，只有远处的气氛还在滑。 */
test('全天任何一刻正文都读得清——晨昏交叉那一段尤其', (t) => {
  const h = boot(); t.after(() => h.close());
  /* 两种形态都要认：插出来的是 'rgb(r,g,b)'，硬翻的那些原样留着 '#rrggbb'。
     只按数字抓的话 '#e9f0f8' 会被抠成 [9,0,8]（踩过一次，报出来像是配色的问题）。 */
  const rgb = (c) => (c.charAt(0) === '#'
    ? [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16))
    : (c.match(/[\d.]+/g) || []).slice(0, 3).map(Number));
  const lin = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  const ratio = (c1, c2) => {
    const a = lum(c1), b = lum(c2);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };
  for (const m of ALL) {
    let worst = 99, worstAt = null;
    for (let x = 0; x < 24; x += 0.25) {
      const v = h.plain(`dlArtAt(${JSON.stringify(m)}, ${x})`);
      // 琉璃的卡片是半透明玻璃，得先压到背后那片天上，才是眼睛真正看到的那个颜色
      let card = v.card ? rgb(v.card) : null;
      if (!card && v.ga !== undefined) {
        const base = rgb(v.sky ? v.sky[1] : v.bg), tint = rgb(v.gc);
        card = base.map((c, i) => c + (tint[i] - c) * v.ga);
      }
      const r = ratio(card, rgb(v.text));
      if (r < worst) { worst = r; worstAt = x; }
    }
    assert.ok(worst >= 4.5,
      `${m}: ${worstAt} 点时正文只有 ${worst.toFixed(2)}:1（要 ≥4.5），那一刻字糊在卡片上`);
  }
});

test('节气色：六个模块的色相全天锁死，只有明度彩度跟着走', (t) => {
  const h = boot(); t.after(() => h.close());
  // 认色识别模块的前提是色相不动。用「六个色的排序」当色相的代理指标：
  // 排序一变，就说明某两个模块的颜色在一天里换过位置。
  const rankAt = (x) => h.plain(`(function(){
    const v = dlArtAt('hue', ${x});
    return [0,1,2,3,4,5].map(i => dlArtHue(v, i))
      .map(c => c.match(/\\d+/g).map(Number))
      .map(([r,g,b]) => (r > b ? 1 : 0) * 2 + (g > b ? 1 : 0));   // 粗粒度的色相签名
  })()`);
  const base = rankAt(13);
  for (const x of [5, 8, 18, 20.5, 23, 2]) {
    assert.deepStrictEqual(rankAt(x), base, `${x} 点时六个模块的色相签名变了`);
  }
  // 而明度确实该变：正午和午夜不能是同一批色，不然「随时间渐变」就是假的
  const noon = h.plain("dlArtHue(dlArtAt('hue', 13), 0)");
  const mid = h.plain("dlArtHue(dlArtAt('hue', 23), 0)");
  assert.notStrictEqual(noon, mid, '正午和夜里的模块色一模一样，没跟着时间走');
});

test('壁纸层：开主题才画，关了要擦干净', (t) => {
  const h = boot(); t.after(() => h.close());
  const wall = () => h.window.document.getElementById('art-wall');
  assert.ok(wall(), 'index.html 里少了 #art-wall 这一层');
  use(h, 'paper');
  assert.ok(wall().style.backgroundImage.includes('gradient'), '宣纸主题没画出壁纸');
  use(h, '');
  assert.strictEqual(wall().style.backgroundImage, '', '关掉主题后壁纸还留在那儿');
});

/* 这一条钉的是一个**静默**失效：给颜色加透明度的老工具只把 'rgb(' 换成 'rgba('，
   喂它一个 '#rrggbb' 就原样返回，透明度悄悄没了、不报错。而硬翻的那批字段
   （DL_ART_SNAP 里的 ink / card / tile…）恰恰留着十六进制。
   翻车现场：本该 5% 的界格和 10% 的远山变成满不透明的骨白 —— 整屏横条加一团大光斑。 */
test('壁纸上那些"淡痕"必须真的是淡的（不能是满不透明）', (t) => {
  const h = boot(); t.after(() => h.close());
  const wall = () => h.window.document.getElementById('art-wall');
  /* 白台不在名单里：它的壁纸**只有**一层渐变，一处半透明都没有 —— 那正是那一稿要的
     （"一点装饰都不要"）。它只查下面那条"不许留十六进制"。 */
  for (const [m, hour] of [['paper', 23], ['paper', 13], ['glass', 22], ['hue', 13],
    ['celadon', 13], ['celadon', 23], ['dossier', 13], ['night', 23]]) {
    atEnd(h, isDesk(m));
    h.run(`localStorage.setItem(${JSON.stringify(isDesk(m) ? 'artThemeDesk' : 'artTheme')},'${m}');
           localStorage.setItem('artClock','0');
           localStorage.setItem('theme','${hour > 18 ? 'dark' : 'light'}');dlArtApply();`);
    const bg = wall().style.backgroundImage;
    // 除了打底那一层 linear-gradient，其余每一层都该是半透明的叠加
    const solids = (bg.match(/#[0-9a-f]{6}/gi) || []);
    assert.deepStrictEqual(solids, [],
      `${m}@${hour}: 壁纸里还留着十六进制色 ${solids.join(' ')} —— 透明度被静默丢了`);
    const alphas = [...bg.matchAll(/rgba\([^)]*?,\s*([\d.]+)\)/g)].map(x => +x[1]);
    assert.ok(alphas.length, `${m}@${hour}: 一层半透明都没有，淡痕肯定没画出来`);
    assert.ok(alphas.every(a => a <= 1), `${m}@${hour}: 透明度算出了 >1 的值`);
  }
  use(h, 'studio');
  const flat = wall().style.backgroundImage;
  assert.deepStrictEqual(flat.match(/#[0-9a-f]{6}/gi) || [], [],
    '白台的壁纸里留着十六进制色 —— 那一层没走插值');
  assert.ok(flat.includes('gradient'), '白台连那一层渐变都没画');
});

test('墨山用 canvas 画山；没有 canvas 的壳里也不能炸', (t) => {
  // jsdom 的 getContext 返回 null，正好就是「老 WebView 没有 canvas」那个场景
  const h = boot(); t.after(() => h.close());
  use(h, 'ink');
  assert.ok(h.window.document.body.classList.contains('art-ink'), '墨山没开起来');
  assert.strictEqual(h.logs.error.length, 0, '开墨山时报了错：' + h.logs.error.join(' / '));
});

test('主题不依赖 core.js：它排在所有脚本最前面，单独跑也不能炸', () => {
  const src = fs.readFileSync(path.join(ROOT, 'static/js/daylight.js'), 'utf8');
  // lsGet/lsSet/$ /api/esc 都是 core.js 的，这个文件用了就说明次序假设已经破了
  for (const sym of ['lsGet(', 'lsSet(', 'esc(', 'api(']) {
    assert.ok(!src.includes(sym), `daylight.js 用到了 core.js 的 ${sym}，但它比 core.js 先跑`);
  }
  assert.ok(src.includes('localStorage.getItem'), '读设置应该直接用原生 localStorage');
});

/* 格数**从 DL_ART 现算**，不写死。原来这里钉的是「五格」，加第九套主题时它就红了 ——
   而那次红的不是 bug，是这条断言过时了。现在只钉两件真正要保证的事：
   每一端列的正是那一端登记过的全部主题、且两端互不出现。 */
test('设置页：默认 + 这一端登记的全部主题都在，当前那格是选中态', (t) => {
  const h = boot(); t.after(() => h.close());
  const opts = () => [...h.window.document.querySelectorAll('#art-grid [data-art]')]
    .map(b => b.dataset.art);
  const on = () => h.window.document.querySelector('#art-grid .art-opt.on').dataset.art;
  const listed = (desk) => h.run(
    `Object.keys(DL_ART).filter(k => !!DL_ART[k].desk === ${desk})`);

  // 电脑端（jsdom 默认 1024）只列电脑那几套
  h.run('artRenderPicker();');
  assert.deepStrictEqual(opts(), ['', ...listed(true)], '电脑端的主题选择格不对');
  assert.ok(opts().length > DESK.length, '电脑端一格都没多出来？第二代那几套没登记上');
  assert.strictEqual(on(), '', '默认状态下选中的不是「默认」');
  h.run("localStorage.setItem('artThemeDesk','celadon'); artRenderPicker();");
  assert.strictEqual(on(), 'celadon', '换了主题后选中态没跟上');

  // 拧到手机宽度：换成手机那几套，且**不该**看见刚才选的青瓷
  atEnd(h, false);
  h.run('artRenderPicker();');
  assert.deepStrictEqual(opts(), ['', ...listed(false)], '手机端的主题选择格不对');
  for (const d of DESK) assert.ok(!opts().includes(d), `手机端列出了电脑端的 ${d}`);
  assert.strictEqual(on(), '', '手机端把电脑端选的那套显示成了选中态');
  h.run("localStorage.setItem('artTheme','ink'); artRenderPicker();");
  assert.strictEqual(on(), 'ink', '换了主题后选中态没跟上');

  // 「跟随天光」那一行只在开了主题时才有意义
  const clockRow = h.window.document.getElementById('art-clock-row');
  assert.ok(!clockRow.classList.contains('hidden'), '开了主题却没露出「跟随天光」');
  h.run("localStorage.setItem('artTheme',''); artRenderPicker();");
  assert.ok(clockRow.classList.contains('hidden'), '关了主题还留着「跟随天光」那一行');
  // 只有一档的主题（夜航）也不该出现这一行：那个开关对它是空的
  use(h, 'night');
  h.run('artRenderPicker();');
  assert.ok(clockRow.classList.contains('hidden'), '夜航只有一档，却还摆着「跟随天光」');
});

/* 图标册（js/articons.js）。缺一枚**不会报错**：取用点会让那一枚静静退回默认图标，
   一屏里混进一枚别人家的字形，得盯着看才发现。所以这一条按槽位逐个数。 */
test('图标册：每套主题都有一册，十三个槽位一个不缺，且各册字形不重样', (t) => {
  const h = boot(); t.after(() => h.close());
  const SLOTS = ['note', 'kb', 'draft', 'material', 'drive', 'star',
    'today', 'drill', 'me', 'clock', 'check', 'cross', 'layers'];
  for (const m of ALL) {
    use(h, m);
    const set = h.run('artIconSet() && Object.keys(artIconSet())');
    assert.ok(set, `${m}: 取不到图标册 —— DL_ART 里少了 icons 字段？`);
    for (const s of SLOTS) assert.ok(set.includes(s), `${m}: 册子里缺 ${s} 这一枚`);
    /* 逐枚验：不光要是 svg，**里面得有能画的元素**。
       曾经有一册把光秃秃的 path 数据直接塞进 <svg>（浏览器当文本节点），
       结果十三枚全是空框：容器和边框照画、不报任何错，得盯着截图才发现。 */
    for (const s of SLOTS) {
      const svg = h.run(`artIcon('${s}','')`);
      assert.ok(/^<svg[\s\S]*<\/svg>$/.test(svg), `${m}: ${s} 那一枚不是一段完整的 svg`);
      assert.ok(/<(path|rect|circle|ellipse|polygon|polyline|line)\b/.test(svg),
        `${m}: ${s} 那一枚里没有可画的元素，渲出来会是个空框`);
    }
    // 底栏/左栏那些槽位名要能对到册子上（同物同形靠 ART_ICON_ALIAS）
    for (const alias of ['overview', 'target', 'word', 'folder', 'pen']) {
      assert.notStrictEqual(h.run(`artIcon('${alias}','兜底')`), '兜底',
        `${m}: 左栏的 ${alias} 没对上册子里的任何一枚`);
    }
  }
  /* 各册不能是同一批字形重新上色 —— 那正是这次要修掉的毛病。
     用「小记」那一枚横向比：十三册就该有十三种画法。 */
  const notes = h.run('Object.keys(ART_ICONS).map(k => ART_ICONS[k].note)');
  assert.strictEqual(new Set(notes).size, notes.length,
    '有两册的「小记」是同一段 svg —— 图标册退化成了换色');
});

/* 全应用的功能图标（.hc-logo）也得跟着主题走 —— 原来只有「库」那六格（.lb-ic）跟，
   全部功能九宫格、板块页、常识/理论/常考的板块卡还是那套通用的橙蓝紫。 */
test('大功能图标：八套主题都接管 .hc-logo，且压得过行内样式', () => {
  const css = fs.readFileSync(path.join(ROOT, 'static/style.css'), 'utf8');
  /* 认**选择器组**，不认"必须自己单独一条"：同一种画风的手机版和电脑版材质完全一样，
     逼它们各写一遍只会多出十条一模一样的规则（改一处漏一处）。 */
  const rules = [...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .map(m => [m[1], m[2]]);
  for (const m of ALL) {
    const hit = rules.filter(([sel]) => sel.split(',').some(s => s.trim() === `body.art-${m} .hc-logo`))
      .map(([, decl]) => decl);
    assert.ok(hit.length, `style.css 里没有 body.art-${m} .hc-logo 的规则`);
    if (m !== 'hue') {          // 节气色是盖一层 tint，不换底色，本来就不用抢
      assert.ok(/!important/.test(hit[0]),
        `art-${m} 的 .hc-logo 没用 !important —— 常识板块/申论类型/题库详情的底色是行内 style，压不过`);
    }
  }
  /* 角标是**故意探出图标外**的（rev-badge 在 top:-6px;right:-8px）。
     给 .hc-logo 加 overflow:hidden 会把「99+」和聊天未读整个裁掉。 */
  const seg = css.slice(css.indexOf('主题也要管「大功能图标」'));
  assert.ok(!/\.hc-logo\{[^}]*overflow:hidden/.test(seg),
    '主题给 .hc-logo 加了 overflow:hidden，今日复习的 99+ 和聊天未读角标会被裁掉');
});

test('emoji 图标：默认保留，开了主题才换成 SVG', (t) => {
  const h = boot(); t.after(() => h.close());
  const shell = fs.readFileSync(path.join(ROOT, 'static/js/shell.js'), 'utf8');
  const grid = shell.slice(shell.indexOf("$('#home-cards').innerHTML"), shell.indexOf('UI_ORDERS ='));
  /* 彩色 emoji（📣 ☁️ 💬）**任何主题都改不动它的颜色**，所以主题下要换成 SVG 字形。
     但默认外观是本来的样子，不该被主题这件事顺手改掉 —— 两套都进 DOM，CSS 决定露哪一套。 */
  assert.ok(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(grid), '默认外观的 emoji 被一起删掉了');
  for (const k of ['hc-em', 'hc-sv']) {
    assert.ok(grid.includes(k), `九宫格里没有 .${k} —— 两套字形的开关不在`);
  }
  const core = fs.readFileSync(path.join(ROOT, 'static/js/core.js'), 'utf8');
  for (const k of ['cloud:', 'chat:', 'flag:']) {
    assert.ok(core.includes(k), `core.js 的 IC 里少了 ${k}（主题下要用它替 emoji）`);
  }
  const css = fs.readFileSync(path.join(ROOT, 'static/style.css'), 'utf8');
  assert.ok(css.includes('.hc-sv{display:none;}'), 'SVG 那套默认没藏起来');
  assert.ok(/body\.art-on \.hc-em\{display:none/.test(css), '开了主题没把 emoji 收起来');
});


/* 启动屏是每天见几十次的第一眼。开了主题却还是默认那张天光，等于主题只做了一半。 */
test('启动屏跟着主题走，关掉主题又回到默认', (t) => {
  const h = boot(); t.after(() => h.close());
  const sp = () => h.window.document.getElementById('splash');
  assert.ok(sp(), 'index.html 里少了 #splash');
  const base = sp().style.backgroundImage;
  assert.ok(base.includes('gradient'), '默认启动屏没画出来');
  const logo = () => h.window.document.querySelector('.sp-logo').style.backgroundImage;
  const baseLogo = logo();

  const logos = new Set();
  for (const m of ALL) {
    atEnd(h, isDesk(m));
    h.run(`localStorage.setItem(${JSON.stringify(isDesk(m) ? 'artThemeDesk' : 'artTheme')},'${m}');
           localStorage.setItem('artClock','1');dlPaintSplash();`);
    const bg = sp().style.backgroundImage;
    assert.ok(bg.includes('gradient'), `${m}: 启动屏底色没画出来`);
    /* 方章是每一套都必须自己一枚：宣纸是朱印、琉璃是玻璃、墨山是墨块、节气色是靛。
       **底色不做这个要求** —— 天光琉璃的天就是照抄 DL_KEYS.sky（"一处改两处跟"是
       那一稿的立意），所以它的底和默认本来就一样，记号落在日/月和方章上。 */
    assert.notStrictEqual(logo(), baseLogo, `${m}: 方章还是默认那枚蓝印`);
    logos.add(logo());
    // 那串上升的光点是**默认**这一版的记号，主题里一律关掉
    assert.strictEqual(String(h.window.document.getElementById('sp-trail').style.opacity), '0',
      `${m}: 默认那串光点没关，四套主题会长得一样`);
    if (m !== 'glass') {
      assert.notStrictEqual(bg, base, `${m}: 启动屏还是默认那张天光（只有琉璃允许同底）`);
    }
  }
  assert.strictEqual(logos.size, ALL.length, '八套主题的方章有重样的');

  atEnd(h, false);
  h.run("localStorage.setItem('artTheme','');dlPaintSplash();");
  assert.strictEqual(sp().style.backgroundImage, base, '关掉主题后启动屏没回到默认');
});

/* 电脑端那四套的启动屏是**横构图**：正文靠左、右半留给美术层。布局挂在 body.art-desk 上，
   而这个类必须在 dlPaintSplash 这一趟里就翻好 —— 等 dlArtApply 再翻就是先居中画一帧、
   再跳到靠左，每天见几十次的那一下。 */
test('电脑端四套：横构图的类和美术层在同一趟里就位', (t) => {
  const h = boot(); t.after(() => h.close());
  const art = () => h.window.document.getElementById('sp-art');
  assert.ok(art(), 'index.html 里少了 #sp-art 这一层');
  for (const m of DESK) {
    atEnd(h, true);
    h.run(`localStorage.setItem('artThemeDesk','${m}');dlPaintSplash();`);
    assert.ok(h.window.document.body.classList.contains('art-desk'),
      `${m}: dlPaintSplash 这一趟没挂上 art-desk，启动屏会先居中画一帧`);
    /* 画法有两种，都算数：前四套把开片/装订线/地平线拼成 SVG 塞进 innerHTML，
       第二代十套把那幅卡通当 background-image 铺上去（不进 DOM，省一个常驻合成层）。
       这里钉的是"这一层上确实有东西"，不是"必须用哪种画法"。 */
    assert.ok(art().innerHTML.length > 0 || /url\(/.test(art().style.backgroundImage || ''),
      `${m}: 美术层是空的（开片/装订线/地平线/基线/卡通都没画）`);
    assert.strictEqual(String(art().style.opacity), '1', `${m}: 美术层画了却没点亮`);
  }
  // 换回手机那四套：美术层要撤干净，横构图也得摘掉
  atEnd(h, false);
  h.run("localStorage.setItem('artTheme','paper');dlPaintSplash();");
  assert.ok(!h.window.document.body.classList.contains('art-desk'), '手机端还留着横构图的类');
  assert.strictEqual(art().innerHTML, '', '换回手机主题后，电脑那套的美术层没撤');
});

/* 两端各出各的，是这次改动的**全部要点**：手机四套是竖构图大色块，电脑四套是横构图细边框，
   互相搬过去都不成立。所以选择要分开记 —— 共用一个键的话，拖窄窗口就会顶着一套
   没有 CSS 接住的主题（inline 变量还在，样式已经在 media 里失效了）。 */
test('电脑端不出现手机端那几套，反之亦然；两端各记各的', (t) => {
  const h = boot(); t.after(() => h.close());
  // 两端各选一套，互不干扰
  use(h, 'celadon');
  assert.strictEqual(h.run('dlArtMode()'), 'celadon', '电脑端没认出自己选的青瓷');
  use(h, 'paper');
  assert.strictEqual(h.run('dlArtMode()'), 'paper', '手机端没认出自己选的宣纸');
  // 拖回宽屏：还是电脑那套，手机选的不该跟过来
  atEnd(h, true);
  assert.strictEqual(h.run('dlArtMode()'), 'celadon', '手机选的主题跟到电脑端来了');
  assert.strictEqual(h.run("localStorage.getItem('artTheme')"), 'paper', '手机端的选择被覆盖了');

  /* 就算键被同步/导入串了（把电脑那套写进手机的键），也只能退回默认 ——
     宁可没有主题，也不要挂一套没有 CSS 接住的。 */
  atEnd(h, false);
  h.run("localStorage.setItem('artTheme','night');dlArtApply();");
  assert.strictEqual(h.run('dlArtMode()'), '', '手机端挂上了电脑端专用的夜航');
  assert.ok(!/\bart-/.test(cls(h)), '退回默认了却还挂着主题类：' + cls(h));
});

/* 夜航是唯一不跟天光的一套：它本来就是夜色，白天开着也成立（用户定的）。
   于是它还得**咬住日夜的决定权**——哪怕「跟随天光」是关着的：
   变量把界面刷成了夜色，body.dark 要是没跟上，写死深色的那批规则就会留在浅色态。 */
test('夜航只有一档：全天同一套色，且日夜不交还给「外观」', (t) => {
  const h = boot(); t.after(() => h.close());
  const at = (x) => h.plain(`dlArtAt('night', ${x})`);
  const noon = at(13);
  for (const x of [0, 5, 8, 18, 20.5, 23]) {
    assert.deepStrictEqual(at(x).bg, noon.bg, `${x} 点时夜航的底色变了 —— 它该只有一档`);
    assert.ok(at(x).dark > 0.5, `${x} 点时夜航被算成了亮环境`);
  }
  use(h, 'night', '0');            // 关掉「跟随天光」
  h.run("localStorage.setItem('theme','light'); applyTheme();");
  assert.strictEqual(h.run('dlArtDark()'), true, '夜航把日夜交还给了「外观」，界面会半亮半暗');
  assert.ok(h.window.document.body.classList.contains('dark'), '夜航开着却没挂上 .dark');
});

test('CSS：八套主题各自的模块图标规则都在，清变量的清单也没漏', () => {
  const css = fs.readFileSync(path.join(ROOT, 'static/style.css'), 'utf8');
  for (const m of ALL) {
    assert.ok(css.includes('body.art-' + m), `style.css 里没有 body.art-${m} 的规则`);
  }
  // 壁纸得能盖住 body 那条写死的 background，否则永远看不见
  assert.ok(/body\.art-on\{background:var\(--bg\)/.test(css.replace(/\s/g, '')),
    'body.art-on 没有把写死的 background 顶掉，壁纸会被盖住');
  // 两套字形的开关
  assert.ok(css.includes('.lb-gl{display:none;}'), '线描字形默认没藏起来');
  assert.ok(css.includes('body.art-paper .lb-gl'), '宣纸主题没把线描字形放出来');
  // 横构图那套布局必须锁在宽屏里：窄窗口下电脑那四套已经不生效，布局不该还留着
  const deskSeg = css.slice(css.indexOf('横构图的启动屏'));
  assert.ok(/@media\(min-width:761px\)\{[\s\S]*?body\.art-desk #splash/.test(
    css.slice(css.indexOf('电脑端专用的四套'))),
  '横构图的启动屏布局没锁在 761px 以上');
  assert.ok(deskSeg.includes('body.art-studio #splash'), '白台的贴线排版没写');
});

/* ---- 悬浮球 / 真题大按钮 / 常识字块：截图里点名的那三处 ---- */
test('悬浮球：图案是「＋」，八套主题都接管球和胶囊', (t) => {
  const h = boot(); t.after(() => h.close());
  const btn = h.window.document.getElementById('fab-btn');
  assert.ok(btn, 'index.html 里少了 #fab-btn');
  assert.ok(!/[✦✚+]/.test(btn.textContent), '悬浮球还是文字符号 —— 字形要跟主题的字色走，得用 SVG');
  const svg = btn.querySelector('svg');
  assert.ok(svg, '悬浮球里没有 SVG');
  assert.ok(/stroke="currentColor"/.test(svg.outerHTML), '悬浮球的字形没用 currentColor，主题改不了它的颜色');
  assert.ok(/M12 5v14M5 12h14/.test(svg.innerHTML), '悬浮球画的不是「＋」');

  const css = fs.readFileSync(path.join(ROOT, 'static/style.css'), 'utf8');
  /* 那四个胶囊是 #fab-pad / #fab-shot / #fab-ink 三条 **ID 选择器**。
     ID 的特异度比任何类组合都高，主题规则不加 !important 就压不过。 */
  const seg = css.match(/body\.art-on \.fab-main,body\.art-on \.fab-act\{[^}]*\}/);
  assert.ok(seg, 'style.css 里没有接管悬浮球的规则');
  assert.ok(/!important/.test(seg[0]), '悬浮球的主题规则没用 !important，压不过 #fab-pad 那几条 ID 选择器');

  // 八套主题都要报出球的材质，漏一套那一套的球就退回写死的紫蓝渐变
  for (const m of ALL) {
    use(h, m);
    assert.ok(styleOf(h, '--art-fab'), `${m}: 没报 --art-fab，悬浮球会留在默认的紫蓝渐变上`);
    assert.ok(styleOf(h, '--art-fab-ink'), `${m}: 没报 --art-fab-ink`);
  }
  use(h, '');
  assert.strictEqual(styleOf(h, '--art-fab'), '', '关掉主题后 --art-fab 还留在 body 上');
});

test('常识板块的色号按固定顺序给，不跟着接口返回的顺序变', (t) => {
  const h = boot(); t.after(() => h.close());
  /* 按色识别的前提是"人文永远是这个色"。若按接口返回的下标给，
     接口哪天换个排序，昨天的缃今天就成了赭。 */
  const idx = (n) => h.run(`CS_IDX(${JSON.stringify(n)})`);
  const a = ['人文常识', '科技常识', '法律常识'].map(idx);
  const b = ['法律常识', '人文常识', '科技常识'].map(idx);
  assert.deepStrictEqual([b[1], b[2], b[0]], a, '换个顺序问，色号跟着变了');
  for (const n of ['人文常识', '科技常识', '法律常识', '地理常识', '经济常识']) {
    const i = idx(n);
    assert.ok(Number.isInteger(i) && i >= 0 && i < 6, `${n} 的色号 ${i} 不在 0–5`);
  }
  // 表里没有的名字（以后新增板块）也要有个稳定的落点，不能是 undefined
  const x = idx('体育常识');
  assert.strictEqual(x, idx('体育常识'), '同一个新板块两次问出了不同的色号');
  assert.ok(Number.isInteger(x) && x >= 0 && x < 6, '新板块的色号越界了：' + x);
});

/* 这一条是**守门的**：这一轮之所以要返工，就是因为主题上线后，
   样式表里还散着几十处写死的彩色渐变，没人知道它们没跟上。
   以后新加一条写死的彩色，如果没在主题段里交代过，这里就红。 */
test('样式表里写死的彩色，必须都在主题段里交代过', () => {
  const css = fs.readFileSync(path.join(ROOT, 'static/style.css'), 'utf8');
  const at = css.indexOf('/* ================= 主题风格（美术方向） =================');
  assert.ok(at > 0, '找不到主题段的起点，这条测试就失效了');
  const body = css.slice(0, at), theme = css.slice(at);

  /* 豁免：这些不是"漏了"，是**换了个地方接管**，写清楚理由，别让后人以为可以随便加。 */
  const EXEMPT = {
    '.hc-exam': '和 .hc-logo 同时出现，由 .hc-logo 那条统一接管',
    '.hc-drive': '同上', '.hc-chat': '同上', '.hc-ck': '同上', '.hc-th': '同上',
    '.hc-sl': '同上', '.hc-real': '同上', '.hc-star': '同上',
    '.sp-logo': '启动屏的方章由 js/daylight.js 的 dlArtSplash 逐属性重画',
  };

  const miss = [];
  for (const [sel, decl] of [...body.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(m => [m[1], m[2]])) {
    if (!/#[0-9a-fA-F]{3,6}\b/.test(decl)) continue;
    if (!/(linear|radial)-gradient/.test(decl)) continue;
    for (const name of (sel.match(/[.#][A-Za-z_-][\w-]*/g) || [])) {
      if (EXEMPT[name] || theme.includes(name)) continue;
      if (!miss.includes(name)) miss.push(name);
    }
  }
  assert.deepStrictEqual(miss, [],
    '这些选择器写死了彩色渐变，但主题段里一个字都没提到 —— 开了主题它们会原样跳出来：\n    '
    + miss.join(' ') + '\n  要么在主题段里精确接管，要么加进长尾兜底那一串。');
});

/* ---- 知识库那一排书封 ----
   这是主题上线后漏得最久的一处，漏的方式也和别处不同：颜色不在样式表里，
   而在 js/kb.js 里以**行内 style** 渲染 —— 上面那条扫样式表的测试看不见它。
   下面两条一条钉行为（八套都得报色、关掉要清干净），一条堵根因（JS 里不许再写死渐变）。 */
test('书封：八套主题都报出八个封面色，关掉后一个都不留', (t) => {
  const h = boot(); t.after(() => h.close());
  for (const m of ALL) {
    use(h, m);
    for (let i = 0; i < 8; i++) {
      assert.ok(styleOf(h, '--kb-c' + i), `${m}: 没报第 ${i} 本的封面色，那一本会退回最初那套通用彩`);
      assert.ok(styleOf(h, '--kb-s' + i), `${m}: 没报第 ${i} 本的书脊色`);
    }
    for (const k of ['--kb-band', '--kb-band-ink', '--kb-ribbon', '--kb-rim', '--kb-shadow', '--kb-radius']) {
      assert.ok(styleOf(h, k), `${m}: ${k} 没写上`);
    }
    /* 八本必须**互不相同** —— 封面是用户自己挑的，八本长一样就等于没得挑。
       （白台是例外：那一稿八本同封，色只在书脊上，所以查的是书脊。） */
    const key = m === 'studio' ? '--kb-s' : '--kb-c';
    const set = new Set();
    for (let i = 0; i < 8; i++) set.add(styleOf(h, key + i));
    assert.strictEqual(set.size, 8, `${m}: 八本里有重样的（${key}）—— 挑封面就分不开了`);
  }
  use(h, '');
  for (let i = 0; i < 8; i++) {
    assert.strictEqual(styleOf(h, '--kb-c' + i), '', `关掉后 --kb-c${i} 还留在 body 上`);
    assert.strictEqual(styleOf(h, '--kb-s' + i), '', `关掉后 --kb-s${i} 还留在 body 上`);
  }
  for (const k of ['--kb-band', '--kb-band-ink', '--kb-band-line', '--kb-ribbon',
    '--kb-rim', '--kb-shadow', '--kb-radius']) {
    assert.strictEqual(styleOf(h, k), '', `关掉后 ${k} 还留在 body 上`);
  }
});

test('CSS：八个色号有兜底值，没开主题时外观分毫不变', () => {
  const css = fs.readFileSync(path.join(ROOT, 'static/style.css'), 'utf8');
  // 原来那八条渐变必须原样留作 var() 的兜底 —— 少一条就是那一本没开主题时变了色
  const OLD = ['#3f73b3,#2b5894', '#d3892f,#a9651b', '#c0473a,#982c22', '#2f8060,#21614a',
    '#7a5ea8,#5b4589', '#2c8c8c,#1f6e6e', '#b08a1e,#876900', '#46566a,#2f3b48'];
  OLD.forEach((g, i) => {
    const rule = css.match(new RegExp('\\.kbc' + i + '\\{[^}]*\\}'));
    assert.ok(rule, `style.css 里没有 .kbc${i} 这一条`);
    assert.ok(rule[0].includes('var(--kb-c' + i), `.kbc${i} 没去读主题变量，主题改不动它`);
    assert.ok(rule[0].includes(g), `.kbc${i} 丢了兜底色 ${g} —— 没开主题时这一本会变样`);
  });
  // 缎带/题签也得交回给变量（原来一个是写死的荧光绿，一个是 85% 纯白）
  assert.ok(/\.kbc-ribbon\{[^}]*var\(--kb-ribbon/.test(css.replace(/\s+/g, '')),
    '缎带还是写死的 #28c76f');
  assert.ok(/\.kbc-band\{[^}]*var\(--kb-band/.test(css.replace(/\s+/g, '')),
    '题签还是写死的 85% 白');
  // 悬浮球和底部胶囊条：复用悬浮球那套材质 / 主题的卡片面
  assert.ok(/body\.art-on \.kb-fab\{/.test(css), '知识库的新建球没接管');
  assert.ok(/body\.art-on \.notes-pill,body\.art-on \.kb-pill\{/.test(css), '底部胶囊条没接管');
});

/* 这一条和上面「样式表里写死的彩色」是一对：那条守样式表，这条守 JS。
   KB_COVERS 就是从这个口子漏出去的 —— 八条渐变住在 js 里，扫样式表的测试永远看不见。 */
test('JS 里也不许写死彩色渐变（KB_COVERS 就是从这漏的）', () => {
  const dir = path.join(ROOT, 'static/js');
  /* 豁免：写清楚各自为什么不算漏，别让后人以为可以随便加。 */
  const EXEMPT = {
    'daylight.js': '主题自己的算色文件，颜色本来就该在这儿',
    'quizdetail.js': '渲染的是 .hc-logo，由主题段里 body.art-* .hc-logo 那几条 !important 统一接管',
    'theme.js': '「默认」那一格的缩略图，画的就是没开主题时的样子，不该跟着主题变',
  };
  const miss = [];
  for (const f of fs.readdirSync(dir).filter(x => x.endsWith('.js'))) {
    if (EXEMPT[f]) continue;
    const src = fs.readFileSync(path.join(dir, f), 'utf8');
    const hit = src.match(/(?:linear|radial)-gradient\([^)]*#[0-9a-fA-F]{3,6}[^)]*\)/g);
    if (hit) miss.push(f + ' → ' + hit.slice(0, 2).join(' '));
  }
  assert.deepStrictEqual(miss, [],
    'JS 里写死了彩色渐变，主题压不过行内样式，开了主题它们会原样跳出来：\n    '
    + miss.join('\n    ') + '\n  颜色请搬进 style.css（留 var(--…) 兜底），或写进豁免表并说明理由。');
});


/* 字看不看得清，不能靠人挨个时刻去瞄：18 套主题 × 24 个时刻 = 432 屏。
   这一条就是那 432 屏的替身。曾经漏掉的正是黄昏那一段 —— 卡片底和字色到点硬翻，
   壁纸却是连续滑的，18~20 时那片底正好滑到和字差不多的一档，次要字只剩 1.2:1。 */
test('每套主题、每个时刻，正文和次要字都不低于对比度下限', t => {
  const h = boot(); t.after(() => h.close());
  const win = h.window;
  const RGB = c => {
    const m = String(c).match(/rgba?\(([^)]+)\)/);
    if (m) return m[1].split(',').slice(0, 3).map(Number);
    let h = String(c).replace('#', '');
    if (h.length === 3) h = h.split('').map(x => x + x).join('');
    return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16));
  };
  const lum = c => RGB(c).map(v => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  }).reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
  const ratio = (a, b) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);
  // 半透明的面（天光琉璃的玻璃卡）背后是壁纸，静态算不出真实底色，不参与判定
  const solid = c => typeof c === 'string' && !/rgba|hsla/.test(c) && !isNaN(lum(c));
  /* 推到纯黑/纯白还是不够的，就不算它的错 —— 那一刻的底色本身是中灰
     （晨昏的天光琉璃就是，纯白压上去也只有 4.33:1），再推没有意义，
     硬把字翻成反色反而会和这一刻其余按日/夜写死的颜色打架。 */
  const maxed = c => { const [r, g, b] = RGB(c); return (r > 250 && g > 250 && b > 250) || (r < 5 && g < 5 && b < 5); };
  const bad = [];
  for (const k of Object.keys(win.DL_ART)) {
    for (let h = 0; h < 24; h++) {
      const v = win.dlGuardInk(win.dlArtAt(k, h));
      const faces = [v.card, v.bg, v.bg2].filter(solid);
      faces.forEach(f => {
        if (ratio(v.text, f) < 4.4 && !maxed(v.text)) bad.push(`${win.DL_ART[k].name} ${h}时 正文 ${ratio(v.text, f).toFixed(2)}:1`);
        if (ratio(v.muted, f) < 3.3 && !maxed(v.muted)) bad.push(`${win.DL_ART[k].name} ${h}时 次要 ${ratio(v.muted, f).toFixed(2)}:1`);
      });
    }
  }
  assert.deepStrictEqual(bad.slice(0, 8), [],
    '这些时刻的字压在自己的底上看不清（dlGuardInk 没兜住）：\n    ' + bad.slice(0, 8).join('\n    '));
});
