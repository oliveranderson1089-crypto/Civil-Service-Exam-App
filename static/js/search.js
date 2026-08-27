/* 全文搜索
 *
 * 由 app.js 按它自己的区段边界切出（原 L2916-3088）。
 * index.html 里的引入次序 = 这里的原次序，不能调换：app.js 的 415 个事件绑定
 * 依赖执行先后，顺序变了行为就变了。
 *
 * 下面那行 global 是本模块的依赖清单：用到、但定义在别处的符号。
 * eslint 靠它继续抓 no-undef；将来若转 ES modules，它就是现成的 import 表。
 */
/* global $, api, c, csBoard, csTopic, draft, dvDownload, dvGo, dvJump, dvOpenFile,
   errMsg, esc, loadCsBoard, loadDraft,
   loadEntries, loadPartyDict, openAccount, openBoardKb, openChangkao, openChangshi,
   openCkBoard, openClassicDetail, openClassics, openDoc, openDocqa, openDraft, openDrafts,
   openEssay, openEssays, openGaikuo, openGongwen, openIdiom, openKb, openMaterials,
   openDrive, openNews, openNewsItem, openNotebook, openNotes, openPartyDict, openPlanLog,
   openPolicyDoc, openPolicyDocs, openReview, openSection, openShenlun, openSucai,
   openTasks, openThBoard, openTheory, openViewer, openWorkDetail, openWorks, openWqDetail,
   openWrongq, openYyLib, push, SECTIONS, state, tkSwitch, toast */

/* ================= 全文搜索 ================= */
let searchData = { q: '', filter: 'all', results: [], fuzzy: false, terms: [] };
function openSearch() {
  searchData = { q: '', filter: 'all', results: [], fuzzy: false, terms: [] };
  $('#search-input').value = '';
  $('#search-results').innerHTML = '';
  $('#search-empty').classList.add('hidden');
  document.querySelectorAll('#search-filter .chip').forEach(x => x.classList.toggle('active', x.dataset.sf === 'all'));
  push({ view: 'search' });
  setTimeout(() => $('#search-input').focus(), 80);
}
$('#tb-search').onclick = openSearch;   // 搜索入口挪进了顶栏（原 #home-search 在「今日」页里）
let searchTimer2;
$('#search-input').addEventListener('input', e => {
  clearTimeout(searchTimer2);
  const q = e.target.value.trim();
  searchTimer2 = setTimeout(() => runSearch(q), 250);
});
$('#search-filter').addEventListener('click', e => {
  const c = e.target.closest('[data-sf]'); if (!c) return;
  searchData.filter = c.dataset.sf;
  document.querySelectorAll('#search-filter .chip').forEach(x => x.classList.toggle('active', x.dataset.sf === searchData.filter));
  renderSearch();
});
async function runSearch(q) {
  searchData.q = q;
  if (!q) { searchData.results = []; searchData.fuzzy = false; searchData.terms = []; renderSearch(); return; }
  try {
    const d = await api('/api/search?q=' + encodeURIComponent(q));
    // 功能入口匹配（名称/关键词），置顶
    const fhits = FEATURES.filter(f => f.name.includes(q) || f.kw.includes(q))
      .map(f => ({ type: 'feature', title: f.name, snippet: f.desc, _open: f.open }));
    // fuzzy＝整串一条都没搜到，后端换成分词又搜了一轮（见 mods/search.py）
    searchData.fuzzy = !!d.fuzzy;
    searchData.terms = d.terms || [];
    searchData.results = fhits.concat(d.results);
    renderSearch();
  } catch (e) { toast(errMsg(e), true); }
}
function hl(text, q) {
  const t = esc(text || '');
  // 相近结果里没有整串，只有后端切出来的词；不按词高亮的话通篇看不出命中在哪
  const src = (searchData.fuzzy && searchData.terms.length) ? searchData.terms : (q ? [q] : []);
  if (!src.length) return t;
  try {
    const pat = src.slice().sort((a, b) => b.length - a.length)
      .map(x => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
    return t.replace(new RegExp('(' + pat + ')', 'gi'), '<mark>$1</mark>');
  } catch (_) { return t; }
}
const SR_TYPE = { note: '小记', material: '资料', doc: '知识库', wrongq: '错题', boardkb: '基础知识', news: '时政', policydoc: '要文', partydict: '理论词典', classic: '古诗文', changshi: '常识', sucai: '素材', gaikuo: '概括句', entry: '成语词语', feature: '功能',
  draft: '草稿本', essay: '范文', gongwen: '应用文', yy: '应用文素材', changkao: '常考', theory: '理论', xiyu: '习语', work: '经典著作',
  annot: '批注', drive: '云盘' };
// 功能入口索引：搜索时匹配名称/关键词，结果置顶直达
const FEATURES = [
  { name: '备考规划', desc: '任务清单 · AI 按你的学情排当天计划', kw: '规划助手备考计划学习计划每日计划安排时间距考试', open: () => { openTasks(); setTimeout(() => tkSwitch('plan'), 60); } },
  { name: '范文推荐', desc: '申论 · 热门话题仿真卷 + 全套参考答案', kw: '范文推荐大作文议论文应用文参考答案话题基层治理科技创新乡村振兴', open: () => openEssays() },
  { name: '题目解析', desc: '题库 · 上传讲义让 AI 解出没答案的例题', kw: '题目解析讲义识题答案解析上传pdfword副本', open: () => openDocqa() },
  { name: '真题批改', desc: '申论 · 四大题型讲义 + AI 逐点批改', kw: '申论真题批改归纳概括综合分析提出对策贯彻执行大作文阅卷采分点范文', open: () => openShenlun() },
  { name: '常考', desc: '高频成语/实词/上位词/古诗文/常识/提法', kw: '常考高频考点成语实词上位词提法', open: () => openChangkao() },
  { name: '上位词积累', desc: '常考 · 逻辑填空概括词提示', kw: '上位词概括词下位词逻辑填空', open: () => openCkBoard('上位词') },
  { name: '理论基础', desc: '政治理论 · 马原/毛概/中特/习思想', kw: '理论马原马克思毛概毛泽东思想邓小平三个代表科学发展观习近平新时代中特公基', open: () => openTheory() },
  { name: '每日时政', desc: '政治理论 · 每天自动更新 AI 三行式', kw: '时政新闻党内国内四川国际', open: () => openNews() },
  { name: '时政要文库', desc: '政治理论 · 重要文件全文+AI解读', kw: '要文二十大报告十五五规划政府工作报告一号文件讲话', open: () => openPolicyDocs() },
  { name: '党的创新理论学习词典', desc: '政治理论 · 12371 术语速查+背诵', kw: '词典理论两个确立四个意识党章党史', open: () => openPartyDict() },
  { name: '常识积累', desc: '常识判断 · 七大板块考情+考点', kw: '常识人文科技法律地理经济公文管理', open: () => openChangshi() },
  { name: '成语词语积累', desc: '言语理解 · 查询收录+AI解释', kw: '成语词语词组选词填空', open: () => openIdiom() },
  { name: '古诗文·名句速查', desc: '议论文 · 唐诗宋词四书五经', kw: '古诗文诗词名句唐诗宋词论语', open: () => openClassics() },
  { name: '素材积累', desc: '议论文 · 人物/事例/理论论据 每日更新', kw: '素材人物事例理论论据写作', open: () => openSucai('全部') },
  { name: '衔接表达', desc: '议论文 · 过渡/转折/万能句式', kw: '衔接过渡转折句式', open: () => openSucai('衔接表达') },
  { name: '概括句积累', desc: '应用文 · 材料表述→规范概括句', kw: '概括句申论', open: () => openGaikuo() },
  { name: '应用文上位词', desc: '应用文 · 公文规范上位表述，按场景归类', kw: '应用文上位词公文规范表述通知意见倡议书规范用语提法', open: () => openGongwen() },
  { name: '错题本', desc: '拍照/输入 · AI 判题型给解析', kw: '错题刷题', open: () => openWrongq() },
  { name: '草稿本', desc: '错题本 · 平时打草稿/演算，手写不识别，自动保存', kw: '草稿本草稿纸打草稿演算竖式手写画板白板涂鸦计算', open: () => openDrafts() },
  { name: '巩固测试', desc: '任务清单 · 每日任务里，按当天计划出题，背题/测试两种模式', kw: '巩固测试测验做题背题模式服务端判分每日测试', open: () => { openTasks(); setTimeout(() => tkSwitch('daily'), 60); } },
  { name: '计划记录', desc: '任务清单 · 历史计划回看 + 进度分析', kw: '计划记录历史回看进度分析冷落模块', open: () => openPlanLog() },
  { name: '经典著作', desc: '毛泽东选集 · 全文精读 + AI 导读', kw: '经典著作毛选毛泽东选集精读朗读', open: () => openWorks() },
  { name: '今日复习', desc: '遗忘曲线 · 该复习的都在这', kw: '复习遗忘曲线艾宾浩斯背诵', open: () => openReview() },
  { name: '小记', desc: '随手记 · 标签归类', kw: '笔记记录', open: () => openNotes() },
  { name: '知识库', desc: '笔记本 · 文档 · 分组整理', kw: '文档笔记本', open: () => openKb() },
  { name: '资料库', desc: '图片/文档/网页 应用内查看', kw: '资料文件上传', open: () => openMaterials() },
  { name: '云盘', desc: '任意格式文件 · 文件夹 / 分享 / 回收站', kw: '云盘网盘文件上传下载文件夹分享回收站安装包', open: () => openDrive() },
  { name: '基础知识点', desc: '各板块 基础知识+方法技巧', kw: '基础知识方法技巧', open: () => { openSection(SECTIONS[0] && SECTIONS[0].key); toast('进入任意板块即可看「基础知识点」'); } },
  { name: '账户', desc: '个人信息 · 改密码/邮箱/密保', kw: '账号设置密码退出登录', open: () => openAccount() },
];
function renderSearch() {
  const box = $('#search-results');
  // 筛选条只留「这次搜到东西」的类别，免得十几个 chip 排满一屏
  document.querySelectorAll('#search-filter .chip').forEach(c => {
    const t = c.dataset.sf;
    c.classList.toggle('hidden', !!searchData.q && t !== 'all'
      && !searchData.results.some(r => r.type === t));
  });
  if (!searchData.q) { box.innerHTML = ''; $('#search-empty').classList.add('hidden'); return; }
  let items = searchData.results;
  if (searchData.filter !== 'all') items = items.filter(r => r.type === searchData.filter);
  if (!items.length) {
    box.innerHTML = '';
    $('#search-empty').classList.remove('hidden');
    $('#search-empty').textContent = '没有匹配「' + searchData.q + '」的内容';
    return;
  }
  $('#search-empty').classList.add('hidden');
  const tip = searchData.fuzzy
    ? `<div class="sr-tip">没有完全匹配「${esc(searchData.q)}」，下面是内容相近的结果</div>` : '';
  box.innerHTML = tip + items.map((r, i) => {
    const meta = r.type === 'doc' ? ('知识库：' + esc(r.notebook || ''))
      : r.type === 'material' ? ((r.ext || '').replace('.', '').toUpperCase() + (r.board ? ' · ' + esc(r.board) : ''))
        : r.type === 'note' ? (r.tags && r.tags.length ? r.tags.map(t => '#' + esc(t)).join(' ') : (r.board ? esc(r.board) : ''))
          : (r.board ? esc(r.board) : '');
    return `<div class="sr-item" data-sri="${i}">
      <div class="sr-head"><span class="sr-type ${r.type}">${SR_TYPE[r.type]}</span>
        <span class="sr-title">${hl(r.title, searchData.q)}</span></div>
      ${r.snippet ? `<div class="sr-snip">${hl(r.snippet, searchData.q)}</div>` : ''}
      ${meta ? `<div class="sr-meta">${meta}</div>` : ''}
    </div>`;
  }).join('');
  box._items = items;
}
$('#search-results').addEventListener('click', async e => {
  const it = e.target.closest('[data-sri]'); if (!it) return;
  const r = ($('#search-results')._items || [])[+it.dataset.sri]; if (!r) return;
  if (r.type === 'feature') {
    if (r._open) r._open();
  } else if (r.type === 'material') {
    if (r.viewable) openViewer(r.id, r.title, r.ext);
    else { const a = document.createElement('a'); a.href = '/api/materials/' + r.id + '/download'; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); }
  } else if (r.type === 'doc') {
    await openNotebook(r.notebook_id);
    openDoc(r.id);
  } else if (r.type === 'note') {
    try {
      const note = await api('/api/notes/' + r.id);
      openNotes();
      setTimeout(() => loadDraft(note), 120);
    } catch (e) { toast(errMsg(e), true); }
  } else if (r.type === 'wrongq') {
    openWqDetail(r.id);
  } else if (r.type === 'boardkb') {
    openBoardKb(r.board);
  } else if (r.type === 'news') {
    openNewsItem(r.id);
  } else if (r.type === 'policydoc') {
    openPolicyDoc(r.id);
  } else if (r.type === 'classic') {
    openClassicDetail(r.id);
  } else if (r.type === 'partydict') {
    await openPartyDict();
    $('#pd-q').value = r.title; loadPartyDict();
  } else if (r.type === 'changshi') {
    csBoard = r.cs_board; csTopic = r.cs_topic;
    push({ view: 'csboard', title: csBoard });
    loadCsBoard();
  } else if (r.type === 'sucai') {
    openSucai(r.kind || '全部');
  } else if (r.type === 'gaikuo') {
    openGaikuo();
  } else if (r.type === 'entry') {
    openIdiom();
    state.q = r.title; $('#search').value = r.title; loadEntries();
  } else if (r.type === 'draft') {
    openDrafts();
    setTimeout(() => openDraft(r.id), 80);
  } else if (r.type === 'essay') {
    openEssay(r.id);
  } else if (r.type === 'yy') {
    // 落到素材库那个文种的格子里。doctype 从 board（「应用文·错例 · 简报 主体·举措」）里取
    openYyLib((r.board || '').split(' · ')[1]?.split(' ')[0] || '');
  } else if (r.type === 'gongwen') {
    openGongwen();
    setTimeout(() => { $('#gw-q').value = r.term || r.title; $('#gw-q').dispatchEvent(new Event('input')); }, 120);
  } else if (r.type === 'changkao') {
    openCkBoard(r.ck_board || '上位词');
  } else if (r.type === 'theory') {
    openThBoard(r.th_board || '');
  } else if (r.type === 'xiyu') {
    openNews();
    setTimeout(() => { const b = document.querySelector('#news-boards [data-nb="习语"]'); if (b) b.click(); }, 260);
  } else if (r.type === 'work') {
    openWorkDetail(r.id);
  } else if (r.type === 'drive') {
    // 文件夹＝走进去；文件＝先落到它所在那层再预览（关掉预览器时人还站在原处），
    // 不能预览的（压缩包、安装包…）只剩下载这一条路
    if (r.is_dir) dvGo(r.path);
    else if (r.viewable) dvOpenFile(r.id, r.title, r.folder);
    else { dvJump(r.folder || ''); dvDownload('/api/drive/' + r.id + '/download', r.title); }
  } else if (r.type === 'annot') {
    // 批注：打开它所在的那份资料，笔迹会自己按锚贴回原处（PDF 按页、阅读模式按那句话）
    if (r.mat) openViewer(r.mat.id, r.mat.name, r.mat.ext);
    else toast('这条批注不在资料库里', true);
  }
});
