#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日时政爬虫：抓取共产党员网 12371.cn 最新时政文章，交 DeepSeek 提炼摘要+考点，
存入 news_items（全局共享，去重）。设计为 systemd timer 每天后台跑，省 token。
用法: python3 crawl_news.py [每次最多处理的新文章数, 默认 6]
"""
import re, os, sys, json, sqlite3, time, html, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
CFG_PATH = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))
os.environ.setdefault("NO_PROXY", "*")
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android) AppleWebKit/537.36 Chrome/120 Mobile"}
HOME = "https://www.12371.cn/"
SOURCE = "共产党员网 12371.cn"
FOOTER = re.compile(r"(版权所有|ICP备|公网安备|责任编辑|扫一扫|分享|来源[:：]|返回|打印|字号|视频加载|上一篇|下一篇|相关(报道|新闻))")

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


def list_articles():
    h = fetch(HOME)
    pairs = re.findall(
        r'<a[^>]+href="(https://www\.12371\.cn/(\d{4})/(\d{2})/(\d{2})/(?:ARTI|STUD)[^"]+\.shtml)"[^>]*>([^<]{6,50})</a>', h)
    out, seen = [], set()
    for u, y, mo, d, t in pairs:
        t = clean(t)
        if u in seen or not t:
            continue
        seen.add(u)
        out.append({"url": u, "pub_date": "%s-%s-%s" % (y, mo, d), "title": t})
    return out


def article_body(url):
    h = fetch(url)
    mb = re.search(r"<!--repaste\.body\.begin-->(.*?)<!--repaste\.body\.end-->", h, re.S)
    seg = mb.group(1) if mb else h
    ps = re.findall(r"<p[^>]*>(.*?)</p>", seg, re.S)
    lines = []
    for p in ps:
        t = clean(p)
        if len(t) >= 10 and not FOOTER.search(t):
            lines.append(t)
    return "\n".join(lines)


def ai_summary(title, content):
    if not AI_KEY:
        return ""
    prompt = ("下面是一篇时政新闻，面向公务员考试考生，用简体中文、Markdown 输出：\n"
              "## 一句话摘要\n（40字以内，点明核心）\n"
              "## 公考考点\n（分条列出关联知识点/命题角度，3-5 条，精炼）\n\n"
              "标题：%s\n正文：\n%s") % (title, content[:4000])
    payload = {"model": AI_MODEL, "temperature": 0.4, "max_tokens": 700,
               "messages": [{"role": "system", "content": "你是资深公考时政辅导老师，提炼准确精炼，用简体中文 Markdown。"},
                            {"role": "user", "content": prompt}]}
    req = urllib.request.Request(AI_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + AI_KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        j = json.loads(resp.read().decode("utf-8"))
    return j["choices"][0]["message"]["content"]


def main():
    max_new = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS news_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, url TEXT UNIQUE, source TEXT,
        pub_date TEXT, content TEXT, ai_summary TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")
    have = {r[0] for r in con.execute("SELECT url FROM news_items")}
    arts = list_articles()
    done = 0
    for a in arts:
        if done >= max_new:
            break
        if a["url"] in have:
            continue
        try:
            body = article_body(a["url"])
            if len(body) < 120:
                continue
            summ = ai_summary(a["title"], body)
            con.execute("INSERT OR IGNORE INTO news_items(title,url,source,pub_date,content,ai_summary) "
                        "VALUES(?,?,?,?,?,?)",
                        (a["title"], a["url"], SOURCE, a["pub_date"], body, summ))
            con.commit()
            done += 1
            print("✓ [%s] %s (%d字)" % (a["pub_date"], a["title"][:30], len(body)))
            time.sleep(0.5)
        except Exception as e:
            print("✗ %s : %s" % (a["title"][:24], e))
    print("本次新增 %d 篇，库内共 %d 篇。" % (done, con.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]))
    con.close()


if __name__ == "__main__":
    main()
