#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全国考情：把各地的招考公告抓回来，理成一张能筛能查的表。

**为什么不按站点写正则**（crawl_news.py 是那么干的，这里故意不）：
时政只有 4 个源，考情有 30 多个，而且这类站改版比新闻站勤。一站一条正则 =
每次改版都要有人来改代码，而没人会天天盯着——坏了只会表现为「某个省再也不更新了」，
安静得像本来就没公告。所以这里用**通用抽取**：以 <a> 为单位，标题过关键词、
日期从链接文字/邻近文本/URL 路径里捞。抽得糙一点没关系，后面还有 AI 那道筛子。

**源怎么选的**（2026-07-28 实测）：
· 官方源里 www.scs.gov.cn（国家公务员局）和 www.mohrss.gov.cn（人社部）都挂着
  一段反爬 JS，直接抓只能拿到 900 多字节的脚本——绕它属于对抗人家的防护，不做。
· 各省人社厅官网可达的有 20 来个，但首页版式各异、公告混在通知里，命中率忽高忽低。
· 华图有**按省分站**的招考公告列表（sc.huatu.com/gwy/ 这种），31 个省 + 事业单位
  专版全部实测可达、版式统一、带日期。所以主力用它，官方省厅作为**补充源**并存
  （同一条公告两边都出，靠 URL 去重；官方源的条目 source 写明来处，可信度更高）。

跑法：
    python3 crawl_exam.py                # 全量跑一遍（systemd timer 每天两次）
    python3 crawl_exam.py 四川 北京       # 只跑指定地区
    python3 crawl_exam.py --check        # 只探活：哪些源还活着、各能抽出几条，不写库
    python3 crawl_exam.py --no-ai        # 不调 AI，只把原始条目入库（调源时用）
"""
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

import aiclient

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
CFG_PATH = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))
os.environ.setdefault("NO_PROXY", "*")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# 省级行政区 → 华图分站二级域。顺序即前端筛选条的顺序（按华北→东北→华东…的习惯排）。
PROVINCES = [
    ("北京", "bj"), ("天津", "tj"), ("河北", "he"), ("山西", "sx"), ("内蒙古", "nmg"),
    ("辽宁", "ln"), ("吉林", "jl"), ("黑龙江", "hlj"),
    ("上海", "sh"), ("江苏", "js"), ("浙江", "zj"), ("安徽", "ah"), ("福建", "fj"),
    ("江西", "jx"), ("山东", "sd"),
    ("河南", "ha"), ("湖北", "hb"), ("湖南", "hn"), ("广东", "gd"), ("广西", "gx"), ("海南", "hi"),
    ("重庆", "cq"), ("四川", "sc"), ("贵州", "gz"), ("云南", "yn"), ("西藏", "xz"),
    ("陕西", "sn"), ("甘肃", "gs"), ("青海", "qh"), ("宁夏", "nx"), ("新疆", "xj"),
]

# 各省人社厅/人事考试官网。只放 2026-07-28 实测能直连、且首页确实挂着通知公告列表的，
# 抓不到的宁可不列——列一个死链接，探活报表上就多一行永远红着的噪音。
OFFICIAL = {
    "北京": ("北京市人社局", "https://rsj.beijing.gov.cn/"),
    "天津": ("天津市人社局", "https://hrss.tj.gov.cn/"),
    "山西": ("山西省人社厅", "http://rst.shanxi.gov.cn/"),
    "辽宁": ("辽宁省人社厅", "https://rst.ln.gov.cn/"),
    "吉林": ("吉林省人社厅", "http://hrss.jl.gov.cn/"),
    "上海": ("上海市人社局", "https://rsj.sh.gov.cn/"),
    "江苏": ("江苏省人社厅", "http://jshrss.jiangsu.gov.cn/"),
    "浙江": ("浙江省人社厅", "http://rlsbt.zj.gov.cn/"),
    "安徽": ("安徽省人社厅", "https://hrss.ah.gov.cn/"),
    "山东": ("山东省人社厅", "http://hrss.shandong.gov.cn/"),
    "河南": ("河南省人社厅", "https://hrss.henan.gov.cn/"),
    "湖北": ("湖北省人社厅", "https://rst.hubei.gov.cn/"),
    "湖南": ("湖南省人社厅", "http://rst.hunan.gov.cn/"),
    "广东": ("广东省人社厅", "https://hrss.gd.gov.cn/"),
    "广西": ("广西人社厅", "http://rst.gxzf.gov.cn/"),
    "海南": ("海南省人社厅", "https://hrss.hainan.gov.cn/"),
    "重庆": ("重庆市人社局", "https://rlsbj.cq.gov.cn/"),
    "四川": ("四川省人社厅", "https://rst.sc.gov.cn/"),
    "贵州": ("贵州省人社厅", "https://rst.guizhou.gov.cn/"),
    "云南": ("云南省人社厅", "https://hrss.yn.gov.cn/"),
    "西藏": ("西藏自治区人社厅", "http://hrss.xizang.gov.cn/"),
    "新疆": ("新疆人社厅", "http://rst.xinjiang.gov.cn/"),
}


def sources():
    """一条源 = (地区, 源名, 列表页, 默认考试类型)。类型只是**默认值**，
       最终以 AI 从标题里判出来的为准（省厅首页上省考、事考、选调是混着发的）。"""
    out = [("全国", "华图·国考", "https://www.huatu.com/gwy/", "国考"),
           ("全国", "华图·事业单位", "https://sydw.huatu.com/zt/sydwggk/", "事考")]
    for name, code in PROVINCES:
        out.append((name, "华图·%s" % name, "https://%s.huatu.com/gwy/" % code, "省考"))
    for name, (label, url) in OFFICIAL.items():
        out.append((name, label, url, ""))
    return out


# ---------------------------------------------------------------- 通用列表抽取
A_TAG = re.compile(r"<a\b[^>]*href=[\"']([^\"'#][^\"']*)[\"'][^>]*>(.*?)</a>", re.S | re.I)
DATE_TXT = re.compile(r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})")
# 两种路径都要认：华图的 /2026/0728/xxx.html 和政务站的 /2026/7/28/xxx.shtml。
# 中间那个 /? 就是为了同时吃下「粘在一起的月日」和「用斜杠分开的月日」。
DATE_URL = re.compile(r"/(20\d{2})/(\d{1,2})/?(\d{1,2})[/_-]")
# 标题必须带这些词之一。**不能只认「公告」**：省厅首页上「公告」满天飞——仲裁公告、
# 采购比选公告、流标公告，一条招考都没有却全被收进来（实测四川省厅首页 5 条命中里
# 3 条是这种）。所以认的是「招/录/聘/考」这类动作词。
# 「招收」是人行的用词（「中国人民银行2026年度招收人员公告」），漏了它人行一条都进不来。
KEYWORD = re.compile(r"(招录|招聘|招收|录用|聘用|遴选|选调|补录|递补|职位表|简章|"
                     r"笔试|面试|报名|考试|考录)")
# 明显不是「一次招考」的：培训广告、经验帖、峰会；以及采购/仲裁/招投标这类同样带
# 「公告」但和考试无关的政务公告；商业银行/保险/券商的社会招聘也不属于公考范畴。
NOISE = re.compile(r"(峰会|讲座|直播|课程|辅导|培训|网课|教材|图书|礼包|领取|"
                   r"技巧|备考|资料下载|每日一练|模拟题|真题下载|解读|"
                   r"采购|中标|流标|比选|询价|招标|仲裁|"
                   r"银行|分行|支行|保险|证券|券商)")
# 但「银行」不能一刀切：**人行和政策性银行是公考序列**——人民银行招录每年和国考同期
# 报名，是必看的一类；国开行/进出口行/农发行的招聘公考人也常报。只按「银行」二字过滤，
# 会把它们连同渤海银行、民生银行的社招一起丢掉，而且丢得悄无声息。
KEEP = re.compile(r"(人民银行|央行|国家开发银行|进出口银行|农业发展银行|政策性银行)")
# 列表页常把日期粘在链接文字尾巴上（「…公告 07-28」）。留着它标题会重复带日期，
# 也会让同一条公告在不同页面上长得不一样、去重失效。
TAIL_DATE = re.compile(r"[\s\[（(]*((20)?\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?|\d{1,2}[-/.月]\d{1,2}日?)[\s\])）]*$")


def txt(x):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(x))).strip()


def fetch(url, timeout=25):
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
    m = re.search(rb'charset=["\']?([a-zA-Z0-9\-]+)', raw[:3000])
    cs = (m.group(1).decode() if m else "utf-8").lower()
    if cs in ("gb2312", "gbk"):
        cs = "gb18030"
    return raw.decode(cs, "ignore")


def abs_url(u, page):
    """把相对链接补全。`//host/path` 这种「跟随协议」的写法也要认——
       它既不是绝对地址也不以单斜杠开头，漏掉的话整站的链接全是坏的。"""
    if u.startswith("//"):
        return ("https:" if page.startswith("https") else "http:") + u
    if u.startswith("http"):
        return u
    root = re.match(r"(https?://[^/]+)", page)
    if not root:
        return u
    return root.group(1) + (u if u.startswith("/") else "/" + u.lstrip("./"))


def pick_date(title, near, url):
    """发布日期三处捞：URL 路径 → 标题 → 链接旁边的文本。捞不到返回空串。

    **URL 排第一**：它是发布日，最可靠。旁边那段文本里出现的日期未必是发布日——
    实测抓到过「2026-12-30」，那是公告里的报名截止日，当成发布日排序就窜到列表最顶上了。
    同理，**未来的日期一概不认**：发布日不可能在明天。
    """
    today = time.strftime("%Y-%m-%d")
    for m in (DATE_URL.search(url), DATE_TXT.search(title), DATE_TXT.search(near)):
        if not m:
            continue
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        s = "%04d-%02d-%02d" % (y, mo, d)
        if s <= today:
            return s
    return ""


def extract(page_html, page_url):
    """从一个列表页抽出 [{title, url, pub_date}]，按 URL 去重、保留出现顺序。"""
    out, seen = [], set()
    for m in A_TAG.finditer(page_html):
        t = txt(m.group(2))
        # 「推荐」「置顶」这类角标会粘在标题前面、日期会粘在后面，都切掉，
        # 不然去重和 AI 都受它干扰
        t = TAIL_DATE.sub("", re.sub(r"^(推荐|置顶|热|NEW|新)\s*", "", t)).strip()
        if not (8 <= len(t) <= 90) or not KEYWORD.search(t):
            continue
        if NOISE.search(t) and not KEEP.search(t):
            continue
        u = abs_url(m.group(1), page_url)
        if u in seen or u.rstrip("/") == page_url.rstrip("/"):
            continue
        seen.add(u)
        near = txt(page_html[m.end():m.end() + 160]) + " " + txt(page_html[max(0, m.start() - 160):m.start()])
        out.append({"title": t, "url": u, "pub_date": pick_date(t, near, u)})
    return out


def fresh(items, days):
    """只留最近 days 天内发布的。**没日期的一律丢掉**：考情的价值全在时效上，
       一条不知道什么时候发的公告，摆在列表里只会让人误以为还能报。"""
    if days <= 0:
        return items
    floor = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    return [x for x in items if x["pub_date"] and x["pub_date"] >= floor]


# ---------------------------------------------------------------- AI 归类
CFG = {}
try:
    CFG = json.load(open(CFG_PATH, encoding="utf-8"))
except Exception:
    pass
TIER = "fast"        # 只做归类和抽日期，flash 够用；每天几十条，别用 pro 烧钱

KINDS = ["国考", "省考", "事考", "选调", "教师", "医疗", "警法", "其他"]

_SYS = ("你是公考资讯编辑。只做一件事：把招考公告的标题理成结构化字段。"
        "拿不准的字段一律留空字符串，**不要猜、不要编**。严格输出 JSON。")


def ai_classify(batch, default_kind, region):
    """一批标题（最多 25 条）一次调用，返回和输入等长的字段数组。

    为什么按标题判而不是抓正文：正文要再发 N 个请求、还常是 PDF/附件，而
    招考公告的标题本身信息密度极高（年份、地区、单位、人数、类型都在里面）。
    真正需要的细节（报名时间、考试时间）用户点进原文看，我们不该复述——
    抄错了比不写更糟。所以这里只抽标题里**写明了的**。
    """
    if not batch:
        return []
    lines = "\n".join("%d. %s" % (i + 1, x["title"]) for i, x in enumerate(batch))
    prompt = (
        "下面是「%s」的招考公告标题（来源默认类型：%s）。逐条判断，输出 JSON 数组，"
        "元素个数必须和标题条数一致、顺序一一对应。每个元素：\n"
        '{"kind":"考试类型，只能从 %s 里选一个",'
        '"region":"地区，省级名称如 四川/北京；全国性的写 全国",'
        '"headcount":"招录人数，只要标题里写了就填纯数字，没写留空",'
        '"brief":"12 字以内的一句话，说清是哪个单位招什么，不要重复地区和年份"}\n\n'
        # 「民政部所属单位公开招聘」实测被判成了国考。国考只包含**公务员考录**，
        # 部委直属的事业单位招聘是事考——考的科目、报的系统都不一样，混了会误导备考方向。
        "判断口径：**先看是不是事业单位**——只要是事业单位/事业编（哪怕主管单位是部委、"
        "省厅），一律 事考；中央机关及其直属机构**录用公务员** → 国考；"
        "省市县各级机关录用公务员/参照管理人员 → 省考；选调生/定向选调 → 选调；教师招聘/特岗 → 教师；"
        "卫健委/医院/护士 → 医疗；公安/司法/辅警 → 警法；实在归不进去的 → 其他。\n\n"
        "标题：\n%s" % (region, default_kind or "未知", "/".join(KINDS), lines))
    try:
        rep = aiclient.chat(
            [{"role": "system", "content": _SYS}, {"role": "user", "content": prompt}],
            tier=TIER, temperature=0.2, max_tokens=200 * len(batch) + 400,
            timeout=180, json_mode=True, cfg=CFG)
    except Exception as e:
        print("  ⚠ AI 归类失败（先按默认类型入库）：%s" % str(e)[:90])
        return []
    return _parse_rows(rep, len(batch))


def _parse_rows(rep, n):
    """AI 说好了给数组，实际常给 {"items":[...]} 或裹一层 ```json。都接住。

    条数对不上时**整批作废**：错位比缺失危险得多——把 A 省的报名时间安到 B 省头上，
    用户是照着它去报名的。
    """
    rep = re.sub(r"^```(?:json)?\s*|\s*```$", "", (rep or "").strip())
    try:
        d = json.loads(rep)
    except Exception:
        return []
    if isinstance(d, dict):
        for k in ("items", "list", "data", "result"):
            if isinstance(d.get(k), list):
                d = d[k]
                break
    if not isinstance(d, list) or len(d) != n:
        print("  ⚠ AI 返回 %s 条、要 %d 条，对不上，这批按默认类型入库"
              % (len(d) if isinstance(d, list) else "非数组", n))
        return []
    return [x if isinstance(x, dict) else {} for x in d]


# ---------------------------------------------------------------- 入库
def ensure_schema(con):
    """建表。爬虫是 systemd 直接拉起的独立进程，可能**先于**主应用碰到新库，
       所以它自己也要能把表建出来（crawl_news.py 同理）。"""
    con.execute("""CREATE TABLE IF NOT EXISTS exam_notices(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT DEFAULT '其他', region TEXT DEFAULT '全国',
        title TEXT, url TEXT UNIQUE, source TEXT, pub_date TEXT,
        headcount TEXT DEFAULT '', brief TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime')))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_exam_notices_pub "
                "ON exam_notices(pub_date DESC)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_exam_notices_region "
                "ON exam_notices(region, kind)")
    con.commit()


def save(con, rows):
    n = 0
    for r in rows:
        cur = con.execute(
            "INSERT OR IGNORE INTO exam_notices(kind,region,title,url,source,pub_date,headcount,brief) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (r["kind"], r["region"], r["title"], r["url"], r["source"],
             r["pub_date"], r["headcount"], r["brief"]))
        n += cur.rowcount
    con.commit()
    return n


def crawl_source(con, src, days, use_ai, batch_size=25):
    region, name, url, default_kind = src
    try:
        items = extract(fetch(url), url)
    except Exception as e:
        print("  ✗ [%s] 抓不到：%s" % (name, str(e)[:70]))
        return 0, 0
    got = len(items)
    items = fresh(items, days)
    have = {u for (u,) in con.execute("SELECT url FROM exam_notices")}
    items = [x for x in items if x["url"] not in have]
    if not items:
        print("  · [%s] 抽到 %d 条，没有新的" % (name, got))
        return got, 0

    rows = []
    for i in range(0, len(items), batch_size):
        chunk = items[i:i + batch_size]
        info = ai_classify(chunk, default_kind, region) if use_ai else []
        for j, it in enumerate(chunk):
            d = info[j] if j < len(info) else {}
            kind = (d.get("kind") or "").strip()
            rows.append({
                "kind": kind if kind in KINDS else (default_kind or "其他"),
                # AI 判出来的地区只在**源本身是全国性的**时候采信：省级源已经知道自己是哪个省，
                # 让 AI 改写它只会把「四川省考」判成「全国」这种倒退。
                "region": ((d.get("region") or "").strip() or "全国") if region == "全国" else region,
                "title": it["title"], "url": it["url"], "source": name,
                "pub_date": it["pub_date"],
                "headcount": re.sub(r"\D", "", str(d.get("headcount") or ""))[:6],
                "brief": (d.get("brief") or "").strip()[:24],
            })
    n = save(con, rows)
    print("  ✓ [%s] 抽到 %d 条 → 新增 %d 条" % (name, got, n))
    return got, n


def check():
    """探活：每个源现在还能抽出几条。源站改版是**静默**的故障，得有办法一眼看出来。"""
    print("源探活（%s）" % time.strftime("%Y-%m-%d %H:%M"))
    dead = []
    for region, name, url, kind in sources():
        try:
            items = extract(fetch(url, timeout=20), url)
        except Exception as e:
            print("  ✗ %-16s %s" % (name, str(e)[:60]))
            dead.append(name)
            continue
        recent = fresh(items, 180)
        flag = "✓" if recent else "⚠"
        if not recent:
            dead.append(name)
        print("  %s %-16s 抽到 %3d 条，近半年 %3d 条" % (flag, name, len(items), len(recent)))
    print("\n共 %d 个源，%d 个需要看一眼：%s"
          % (len(sources()), len(dead), "、".join(dead) or "无"))
    return dead


def main(argv):
    if "--check" in argv:
        check()
        return
    use_ai = "--no-ai" not in argv
    days = 90
    for a in argv:
        if a.startswith("--days="):
            days = int(a.split("=", 1)[1])
    only = [a for a in argv if not a.startswith("--")]

    con = sqlite3.connect(DB)
    ensure_schema(con)
    total_new = 0
    for src in sources():
        if only and src[0] not in only:
            continue
        _, n = crawl_source(con, src, days, use_ai)
        total_new += n
        time.sleep(0.4)      # 别把人家站点打疼了
    print("── 考情：本轮新增 %d 条" % total_new)
    con.close()


if __name__ == "__main__":
    main(sys.argv[1:])
