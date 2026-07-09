#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日时政爬虫（三板块）：国内 / 四川 / 国际，各抓权威源最新时政，
交 DeepSeek 提炼成申论「三行式」(事件/角度/素材)，存入 news_items（全局共享，去重，带 board 板块字段）。
- 国内：共产党员网 12371.cn
- 四川：四川省人民政府网 sc.gov.cn（要闻 /10462）
- 国际：人民网国际频道 world.people.com.cn
设计为 systemd timer 每天后台跑，省 token。同一份库供 APP 三板块展示 + 微信每日推送共用。
用法: python3 crawl_news.py [每板块最多处理的新文章数, 默认 4] [板块名(可选,只跑某板块)]
"""
import re, os, sys, json, sqlite3, time, html, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
CFG_PATH = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))
os.environ.setdefault("NO_PROXY", "*")
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android) AppleWebKit/537.36 Chrome/120 Mobile"}
FOOTER = re.compile(r"(版权所有|ICP备|公网安备|责任编辑|扫一扫|分享到|来源[:：]|返回|打印|字号|视频加载|上一篇|下一篇|相关(报道|新闻)|点击进入专题|网站地图|违法和不良信息)")
# 选材过滤：纯人事任免/程序性内容对申论积累价值低，直接跳过（用户 2026-07-02 指定）
SKIP_TITLE = re.compile(r"(任免|任命|免去.*职务|人事|讣告|逝世|唁电|吊唁|治丧|遗体送别)")
# 正文杂质：人民网视频播放器参数等 JS 片段混进 <p>
JSJUNK = re.compile(r"(width\s*:|height\s*:|\}\);|createPlayer|videoUrl|\bvar\s|function\s*\()")

# 三板块数据源。每个 re 必须捕获 4 组：(完整或相对url, 年, 月, 日)
BOARDS = {
    "党内": {
        "source": "共产党员网", "home": "https://www.12371.cn/", "base": "https://www.12371.cn",
        "re": r'href="(https://www\.12371\.cn/(\d{4})/(\d{2})/(\d{2})/(?:ARTI|STUD)[^"]+\.shtml)"',
    },
    "国内": {  # 人民网时政（文章在人民网主站首页聚合，politics 子站首页是专题页抓不到）
        "source": "人民网时政", "home": "http://www.people.com.cn/", "base": "https://politics.people.com.cn",
        "re": r'href="(https?://politics\.people\.com\.cn/n1/(\d{4})/(\d{2})(\d{2})/c\d+-\d+\.html)"',
    },
    "四川": {
        "source": "四川省人民政府网", "home": "https://www.sc.gov.cn/", "base": "https://www.sc.gov.cn",
        "re": r'href="((?:https://www\.sc\.gov\.cn)?/10462/c\d+s?/(\d{4})/(\d{1,2})/(\d{1,2})/[a-z0-9]+\.shtml)"',
    },
    "国际": {
        "source": "人民网国际", "home": "http://world.people.com.cn/", "base": "https://world.people.com.cn",
        "re": r'href="(https://world\.people\.com\.cn/n1/(\d{4})/(\d{2})(\d{2})/c\d+-\d+\.html)"',
    },
}

CFG = {}
try:
    CFG = json.load(open(CFG_PATH, encoding="utf-8"))
except Exception:
    pass
AI_BASE = (CFG.get("ai_base") or "https://api.deepseek.com").rstrip("/")
AI_MODEL = CFG.get("ai_model") or "deepseek-chat"
AI_KEY = CFG.get("ai_key") or os.environ.get("GONGKAO_AI_KEY", "")
AI_URL = AI_BASE if AI_BASE.endswith("/chat/completions") else (
    AI_BASE + "/chat/completions" if AI_BASE.endswith("/v1") else AI_BASE + "/v1/chat/completions")


def fetch(url):
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25).read()
    m = re.search(rb'charset=["\']?([a-zA-Z0-9\-]+)', raw[:2000])
    cs = (m.group(1).decode() if m else "utf-8").lower()
    if cs in ("gb2312", "gbk"):
        cs = "gb18030"
    return raw.decode(cs, "ignore")


def clean(x):
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", "", html.unescape(x)).replace("\xa0", " ").replace("　", " ")).strip()


def list_articles(board):
    """列表页提取文章 [{url, pub_date}]，按日期新→旧。"""
    cfg = BOARDS[board]
    try:
        h = fetch(cfg["home"])
    except Exception as e:
        print("  ✗ 列表页抓取失败 [%s]: %s" % (board, e))
        return []
    out, seen = [], set()
    for m in re.finditer(cfg["re"], h):
        url = m.group(1)
        if url.startswith("/"):
            url = cfg["base"] + url
        if url in seen:
            continue
        seen.add(url)
        pub = "%s-%s-%s" % (m.group(2), m.group(3).zfill(2), m.group(4).zfill(2))
        out.append({"url": url, "pub_date": pub})
    out.sort(key=lambda a: a["pub_date"], reverse=True)
    return out


def fetch_article(url):
    """通用正文提取：<title> 作标题（去站名后缀），正文取 <p> 段落并过滤页脚。返回 (title, body)。"""
    h = fetch(url)
    mt = re.search(r"<title>(.*?)</title>", h, re.S)
    title = clean(mt.group(1)) if mt else ""
    title = re.split(r"[-_—|｜]", title)[0].strip()  # 去掉「_人民网」「-四川省…」等站名后缀
    # 优先正文容器，取不到则退回全页 <p>
    mb = re.search(r"<!--repaste\.body\.begin-->(.*?)<!--repaste\.body\.end-->", h, re.S)
    seg = mb.group(1) if mb else h
    ps = re.findall(r"<p[^>]*>(.*?)</p>", seg, re.S)
    lines = []
    for p in ps:
        t = clean(p)
        if len(t) >= 12 and not FOOTER.search(t) and not JSJUNK.search(t):
            lines.append(t)
    return title, "\n".join(lines)


def ai_extract(board, title, content, pub_date=""):
    """DeepSeek 提炼申论「三行式」：事件 / 角度 / 素材。与微信推送规格一致。"""
    if not AI_KEY:
        return ""
    prompt = (
        "下面是一篇%s时政新闻（发布日期 %s，事件时间以此为准、不要臆测年份），"
        "面向公务员【国考+省考】申论积累，用简体中文按固定格式输出（不要多余文字、不要标题）：\n"
        "① 事件：一句话讲清是什么（真实、含时间/主体）\n"
        "② 角度：可切入的申论主题方向（尽量多角度，如治理/民生/创新/生态/文化/法治/开放等）\n"
        "③ 素材：一句可直接用于申论的书面化表述（不口语、可积累）\n\n"
        "标题：%s\n正文：\n%s"
    ) % (board, pub_date or "近期", title, content[:4000])
    payload = {"model": AI_MODEL, "temperature": 0.4, "max_tokens": 600,
               "messages": [{"role": "system", "content": "你是资深公考申论辅导老师，提炼准确精炼、书面化，用简体中文。"},
                            {"role": "user", "content": prompt}]}
    req = urllib.request.Request(AI_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + AI_KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        j = json.loads(resp.read().decode("utf-8"))
    return j["choices"][0]["message"]["content"].strip()


def ensure_schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS news_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, url TEXT UNIQUE, source TEXT,
        pub_date TEXT, content TEXT, ai_summary TEXT, board TEXT DEFAULT '国内',
        created_at TEXT DEFAULT (datetime('now','localtime')))""")
    cols = {r[1] for r in con.execute("PRAGMA table_info(news_items)")}
    if "board" not in cols:  # 旧库迁移：补 board 列，历史数据归为「国内」
        con.execute("ALTER TABLE news_items ADD COLUMN board TEXT DEFAULT '国内'")
        con.execute("UPDATE news_items SET board='国内' WHERE board IS NULL OR board=''")
    # 板块调整(2026-07-02)：原「国内」拆为「党内(12371)」+「国内(央视)」，把 12371 历史数据迁到党内
    con.execute("UPDATE news_items SET board='党内' WHERE source LIKE '%共产党员%' AND board='国内'")
    con.commit()


def crawl_board(con, board, max_new):
    have = {r[0] for r in con.execute("SELECT url FROM news_items")}
    arts = list_articles(board)
    done = 0
    for a in arts:
        if done >= max_new:
            break
        if a["url"] in have:
            continue
        try:
            title, body = fetch_article(a["url"])
            if len(body) < 120 or not title:
                continue
            if SKIP_TITLE.search(title):
                print("  ⏭ [%s] 跳过程序性/人事类：%s" % (board, title[:26]))
                continue
            summ = ai_extract(board, title, body, a["pub_date"])
            con.execute("INSERT OR IGNORE INTO news_items(title,url,source,pub_date,content,ai_summary,board) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (title, a["url"], BOARDS[board]["source"], a["pub_date"], body, summ, board))
            con.commit()
            done += 1
            print("  ✓ [%s·%s] %s (%d字)" % (board, a["pub_date"], title[:26], len(body)))
            time.sleep(0.5)
        except Exception as e:
            print("  ✗ [%s] %s : %s" % (board, a["url"][-30:], e))
    return done


def gen_gaikuo(con):
    """申论概括句积累：取当天抓到的时政做素材，AI 提炼「材料原句→规范概括句」若干条。
    一天只生成一次（表里已有当天数据则跳过）；一次 AI 调用，省 token。"""
    if not AI_KEY:
        return
    con.execute("""CREATE TABLE IF NOT EXISTS gaikuo_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, topic TEXT, raw TEXT,
        sentence TEXT, tip TEXT, created_at TEXT DEFAULT (datetime('now','localtime')))""")
    today = time.strftime("%Y-%m-%d")
    if con.execute("SELECT COUNT(*) FROM gaikuo_items WHERE date=?", (today,)).fetchone()[0]:
        print("── 概括句：今日(%s)已生成，跳过" % today)
        return
    rows = con.execute(
        "SELECT title, substr(content,1,600) FROM news_items ORDER BY id DESC LIMIT 6").fetchall()
    if not rows:
        return
    material = "\n\n".join("【%s】\n%s" % (t, c) for t, c in rows)
    prompt = (
        "下面是今天的几篇时政新闻素材。请面向公务员申论「概括归纳题」，从中提炼 5 条「概括句积累」，"
        "只输出 JSON 数组（不要多余文字），每条字段：\n"
        '{"topic":"主题领域，2-4字，如 基层治理/科技创新/生态环保/民生保障/文化建设",'
        '"raw":"材料里的原始表述（口语化/描述性的一句，可轻度改写但保持材料味）",'
        '"sentence":"提炼后的规范概括句（书面化、动宾结构、可直接写进申论答案，20-35字）",'
        '"tip":"一句用法点拨：这类表述适合什么题型/怎么迁移"}\n\n素材：\n%s') % material[:5000]
    payload = {"model": AI_MODEL, "temperature": 0.4, "max_tokens": 1500,
               "messages": [{"role": "system", "content": "你是资深申论辅导老师，擅长把材料语言提炼成规范概括句。严格输出 JSON 数组，用简体中文。"},
                            {"role": "user", "content": prompt}]}
    req = urllib.request.Request(AI_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + AI_KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=150) as resp:
        j = json.loads(resp.read().decode("utf-8"))
    text = j["choices"][0]["message"]["content"].strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        items = json.loads(text)
    except Exception as e:
        print("── 概括句：解析失败", e)
        return
    n = 0
    for it in items if isinstance(items, list) else []:
        if not (it.get("sentence") and it.get("topic")):
            continue
        con.execute("INSERT INTO gaikuo_items(date,topic,raw,sentence,tip) VALUES(?,?,?,?,?)",
                    (today, it.get("topic", "").strip(), it.get("raw", "").strip(),
                     it.get("sentence", "").strip(), it.get("tip", "").strip()))
        n += 1
    con.commit()
    print("── 概括句：今日新增 %d 条" % n)


def main():
    max_new = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 4
    only = sys.argv[2] if len(sys.argv) > 2 else (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].isdigit() else None)
    con = sqlite3.connect(DB)
    ensure_schema(con)
    boards = [only] if only in BOARDS else list(BOARDS.keys())
    total = 0
    for b in boards:
        print("── 板块：%s（%s）" % (b, BOARDS[b]["source"]))
        total += crawl_board(con, b, max_new)
    n = con.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]
    per = {b: con.execute("SELECT COUNT(*) FROM news_items WHERE board=?", (b,)).fetchone()[0] for b in BOARDS}
    print("本次新增 %d 篇；库内共 %d 篇（%s）。" % (total, n, "，".join("%s%d" % (k, v) for k, v in per.items())))
    try:
        gen_gaikuo(con)
    except Exception as e:
        print("── 概括句生成失败:", e)
    try:
        gen_xiyu(con)
    except Exception as e:
        print("── 习语金句生成失败:", e)
    con.close()


XIYU_CATS = ["经济", "文化", "社会", "党建", "科教", "生态", "国防", "国际"]


def gen_xiyu(con):
    """习语金句（学习强国风格）：每日从人民网「习近平系列重要讲话数据库」(jhsjk.people.cn)
    抓最新讲话原文，AI 逐字摘录金句并按 经济/文化/社会/党建/科教/生态/国防/国际 分类。
    一天只生成一次；金句必须出自原文，杜绝编造。"""
    if not AI_KEY:
        return
    con.execute("""CREATE TABLE IF NOT EXISTS xiyu_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, category TEXT,
        quote TEXT, note TEXT, source_url TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')), UNIQUE(quote))""")
    _cols = {r[1] for r in con.execute("PRAGMA table_info(xiyu_items)")}
    for _c in ("keyword", "apply"):   # keyword=新提法/关键词标签；apply=申论运用点拨
        if _c not in _cols:
            con.execute("ALTER TABLE xiyu_items ADD COLUMN %s TEXT" % _c)
    today = time.strftime("%Y-%m-%d")
    if con.execute("SELECT COUNT(*) FROM xiyu_items WHERE date=?", (today,)).fetchone()[0]:
        print("── 习语金句：今日(%s)已生成，跳过" % today)
        return
    # 双源：人民网习近平讲话数据库 + 求是网（学习强国反爬无法直抓，用户 2026-07-03 指定求是替代）
    art_urls = []
    try:
        h = fetch("http://jhsjk.people.cn/")
        seen = set()
        for m in re.finditer(r'href="article/(\d+)', h):
            if m.group(1) not in seen:
                seen.add(m.group(1))
                art_urls.append("http://jhsjk.people.cn/article/" + m.group(1))
        art_urls = art_urls[:8]
    except Exception as e:
        print("── 习语：jhsjk 列表页失败", e)
    try:
        h = fetch("https://www.qstheory.cn/")
        seen = set()
        qs = []
        for m in re.finditer(r'href="(20\d{6}/[0-9a-f]{16,40}/c\.html)"', h):
            if m.group(1) not in seen:
                seen.add(m.group(1))
                qs.append("https://www.qstheory.cn/" + m.group(1))
        art_urls += qs[-6:]  # 求是首页链接大致按时间排，取最新几篇
    except Exception as e:
        print("── 习语：求是网列表页失败", e)
    corpus = []
    for url in art_urls:
        try:
            page = fetch(url)
            ps = re.findall(r"<p[^>]*>(.*?)</p>", page, re.S)
            body = "\n".join(x for x in (clean(p) for p in ps) if len(x) > 15)
            if len(body) > 250:  # 过滤视频页/短讯
                corpus.append((url, body[:2200]))
        except Exception:
            continue
        time.sleep(0.3)
    if not corpus:
        print("── 习语：没有抓到讲话原文")
        return
    material = "\n\n".join("【文章%d｜%s】\n%s" % (i + 1, u, b) for i, (u, b) in enumerate(corpus))
    # 近 90 天已收录的金句，交给 AI 去重（避免天天摘同几句套话）
    had = [r[0] for r in con.execute(
        "SELECT quote FROM xiyu_items WHERE date >= date('now','localtime','-90 day') ORDER BY id DESC LIMIT 60")]
    avoid = ("\n【已收录，不要重复】\n" + "\n".join("・" + q[:30] for q in had)) if had else ""
    prompt = (
        "下面是习近平总书记近期重要讲话/报道的真实原文素材。请以【公务员申论·面试应试】为目标，"
        "从中摘录 8~12 条最具背诵价值的金句。\n"
        "【什么是金句】一句话即可独立成立、含判断或主张、书面化、可以直接抄进申论文章。例如：\n"
        "  ✓「江山就是人民，人民就是江山。」\n"
        "  ✓「绿水青山就是金山银山。」\n"
        "  ✓「科技创新是发展新质生产力的核心要素。」\n"
        "【什么不是金句·必须排除】\n"
        "  ✗ 工作部署流水句：「要深入学习贯彻……，聚焦……，把……贯穿全过程。」\n"
        "  ✗ 会议报道、礼节性表述、纯口语句、没有观点的动员令。\n"
        "  ✗ 超过 70 字的整段话——只摘其中最凝练的一句，不要整段照搬。\n"
        "【优先】含新提法/新概念/新论断的句子（新质生产力、乡村振兴战略、粤港澳大湾区、"
        "中国式现代化、全过程人民民主、共同富裕、高质量发展等），以及总书记当前关注的重点领域。\n"
        "按类别归类：经济、文化、社会、党建、科教、生态、国防、国际。\n"
        "每条字段：\n"
        "quote=金句原文（必须逐字出自素材、不得改写编造；15~70字；是一个完整句子，最多一个句号）；\n"
        "keyword=其中的新提法或核心关键词（4~14字）；\n"
        "category=八类之一；\n"
        "note=出处与背景（这句话在什么场合、针对什么问题讲的，25字内，不要与 apply 重复）；\n"
        "apply=申论/面试怎么用（可用于哪类主题、放在文章什么位置，30~55字，不要与 note 重复）；\n"
        "src=来源文章编号(数字)。\n"
        '只输出 JSON：{"items":[{"category":"...","keyword":"...","quote":"...","note":"...","apply":"...","src":1},...]}'
        + avoid + "\n\n" + material)
    payload = {"model": AI_MODEL, "temperature": 0.3, "max_tokens": 2800,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": "你是严谨的公考时政编辑，金句必须逐字摘自给定素材，宁缺毋滥，严格输出 JSON。"},
                            {"role": "user", "content": prompt}]}
    req = urllib.request.Request(AI_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + AI_KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        j = json.loads(resp.read().decode("utf-8"))
    try:
        items = json.loads(j["choices"][0]["message"]["content"]).get("items", [])
    except Exception:
        items = []
    n = 0
    for it in items:
        cat = (it.get("category") or "").strip()
        quote = (it.get("quote") or "").strip().strip("“”\"'")
        # 质量闸门：太短没信息量，太长是整段部署句；句号过多说明摘了一整段
        if cat not in XIYU_CATS or not (12 <= len(quote) <= 90):
            continue
        if quote.count("。") > 1 or quote.startswith(("要深入", "要聚焦", "要坚持不懈地把")):
            continue
        try:
            src = corpus[int(it.get("src", 1)) - 1][0]
        except Exception:
            src = corpus[0][0]
        note = (it.get("note") or "").strip()
        apply_txt = (it.get("apply") or "").strip()
        if note == apply_txt:          # 两栏重复 → 背景栏留空，前端只显示运用
            note = ""
        cur = con.execute(
            "INSERT OR IGNORE INTO xiyu_items(date,category,quote,note,keyword,apply,source_url) "
            "VALUES(?,?,?,?,?,?,?)",
            (today, cat, quote, note, (it.get("keyword") or "").strip(), apply_txt, src))
        n += cur.rowcount
    con.commit()
    print("── 习语金句 +%d 条" % n)


if __name__ == "__main__":
    main()
