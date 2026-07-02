#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""常识积累内容生成器（DeepSeek）。
用法:
  python3 gen_changshi.py seed          # 一次性：为所有还没内容的 板块×专题 生成基础考点条目
  python3 gen_changshi.py seed 法律常识  # 只生成某板块
  python3 gen_changshi.py daily         # 每日：人文/科技 各按当日轮换专题新增 3 条（避开已有标题）
  python3 gen_changshi.py newlaw        # 每周：扫新闻源里《××法》通过/施行文章→整理进 法律常识·其他新出法律
数据写入 changshi_items（UNIQUE(board,topic,title) 幂等去重）。
"""
import re, os, sys, json, sqlite3, time, html, urllib.request
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
CFG_PATH = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))
os.environ.setdefault("NO_PROXY", "*")
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android) AppleWebKit/537.36 Chrome/120 Mobile"}

CFG = json.load(open(CFG_PATH, encoding="utf-8")) if os.path.exists(CFG_PATH) else {}
AI_BASE = (CFG.get("ai_base") or "https://api.deepseek.com").rstrip("/")
AI_MODEL = CFG.get("ai_model") or "deepseek-chat"
AI_KEY = CFG.get("ai_key") or os.environ.get("GONGKAO_AI_KEY", "")
AI_URL = AI_BASE if AI_BASE.endswith("/chat/completions") else (
    AI_BASE + "/chat/completions" if AI_BASE.endswith("/v1") else AI_BASE + "/v1/chat/completions")

META = json.load(open(os.path.join(BASE, "changshi_meta.json"), encoding="utf-8"))
TODAY = date.today().isoformat()


def ai(messages, max_tokens=3000, json_mode=True, temperature=0.4):
    payload = {"model": AI_MODEL, "temperature": temperature, "max_tokens": max_tokens,
               "messages": messages}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(AI_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + AI_KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as resp:
        j = json.loads(resp.read().decode("utf-8"))
    return j["choices"][0]["message"]["content"]


def save_items(con, board, topic, items, source="ai"):
    n = 0
    for it in items:
        t = (it.get("title") or "").strip()[:60]
        c = (it.get("content") or "").strip()
        if not t or not c:
            continue
        cur = con.execute("INSERT OR IGNORE INTO changshi_items(board,topic,title,content,date,source) "
                          "VALUES(?,?,?,?,?,?)", (board, topic, t, c, TODAY, source))
        n += cur.rowcount
    con.commit()
    return n


def gen_topic(con, board, topic_meta, count=12, avoid=None):
    topic = topic_meta["name"]
    special = ""
    if topic == "法定文种":
        count = 15
        special = ("15 条必须正好对应 15 个法定文种：决议、决定、命令（令）、公报、公告、通告、意见、通知、"
                   "通报、报告、请示、批复、议案、函、纪要。每条 title 就是文种名，content 讲清"
                   "【适用范围】【特点】【分类】三部分。")
    avoid_txt = ""
    if avoid:
        avoid_txt = "\n【去重】以下考点已经收录过，绝对不要重复（换新的考点）：" + "、".join(list(avoid)[:80])
    prompt = (
        "为公务员/事业单位考试的常识判断备考，生成「%s · %s」的高频考点知识条目 %d 条。\n"
        "参考该专题考查要点：%s\n%s"
        "要求：每条聚焦一个具体考点；title 是考点名（不超过 20 字）；content 是 80~200 字的精炼讲解，"
        "包含关键数字/对比/易错点，书面化、准确、可直接背诵；内容必须真实准确，不确定的不要写。%s\n"
        '只输出 JSON：{"items":[{"title":"...","content":"..."},...]}'
    ) % (board, topic_meta["name"], count, topic_meta.get("map", "")[:400], special, avoid_txt)
    reply = ai([{"role": "system", "content": "你是资深公考常识辅导老师，知识准确、讲解精炼，严格输出 JSON，用简体中文。"},
                {"role": "user", "content": prompt}], max_tokens=4000)
    try:
        items = json.loads(reply).get("items", [])
    except Exception:
        items = []
    return save_items(con, board, topic, items)


def cmd_seed(con, only_board=None):
    for board, meta in META["boards"].items():
        if only_board and board != only_board:
            continue
        for tm in meta["topics"]:
            if tm["name"] == "其他新出法律":
                continue  # 由 newlaw 模式负责
            have = con.execute("SELECT COUNT(*) FROM changshi_items WHERE board=? AND topic=?",
                               (board, tm["name"])).fetchone()[0]
            if have >= 8:
                print("· %s/%s 已有 %d 条，跳过" % (board, tm["name"], have))
                continue
            try:
                n = gen_topic(con, board, tm)
                print("✓ %s/%s +%d 条" % (board, tm["name"], n))
            except Exception as e:
                print("✗ %s/%s 失败: %s" % (board, tm["name"], e))
            time.sleep(0.5)


def cmd_daily(con):
    """人文/科技 每日各挑一个专题新增 3 条（按当日序数轮换专题，传已有标题去重）。"""
    doy = date.today().toordinal()
    for board in ("人文常识", "科技常识"):
        meta = META["boards"][board]
        tm = meta["topics"][doy % len(meta["topics"])]
        avoid = [r[0] for r in con.execute(
            "SELECT title FROM changshi_items WHERE board=? AND topic=? ORDER BY id DESC LIMIT 80",
            (board, tm["name"]))]
        try:
            n = gen_topic(con, board, tm, count=3, avoid=avoid)
            print("✓ 每日 %s/%s +%d 条" % (board, tm["name"], n))
        except Exception as e:
            print("✗ 每日 %s/%s 失败: %s" % (board, tm["name"], e))


def _fetch(url):
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25).read()
    m = re.search(rb'charset=["\']?([a-zA-Z0-9\-]+)', raw[:2000])
    cs = (m.group(1).decode() if m else "utf-8").lower()
    if cs in ("gb2312", "gbk"):
        cs = "gb18030"
    return raw.decode(cs, "ignore")


def cmd_newlaw(con):
    """扫新闻源标题里的《××法》通过/施行/修订类文章，AI 整理进 法律常识·其他新出法律。
    另：首次运行时生成一份近年重要新法基线。"""
    board, topic = "法律常识", "其他新出法律"
    have_titles = {r[0] for r in con.execute(
        "SELECT title FROM changshi_items WHERE board=? AND topic=?", (board, topic))}
    # 基线（只跑一次）
    if not have_titles:
        prompt = (
            "整理近三年我国新出台或重要修订、且已公布施行的法律（如爱国主义教育法、粮食安全保障法、学位法、"
            "关税法、能源法、学前教育法、民营经济促进法等，你确定真实存在的才写），每部一条。\n"
            "title=《法律名》；content 含【施行日期】【核心制度/亮点】【备考要点】，100~180字，"
            "必须真实准确，不确定的宁可不写。\n只输出 JSON：{\"items\":[{\"title\":\"...\",\"content\":\"...\"}]}")
        try:
            reply = ai([{"role": "system", "content": "你是公考法律辅导老师，只写你确定真实的法律信息，严格输出 JSON。"},
                        {"role": "user", "content": prompt}], max_tokens=4000)
            items = json.loads(reply).get("items", [])
            n = save_items(con, board, topic, items, source="ai基线")
            print("✓ 新法基线 +%d 条" % n)
        except Exception as e:
            print("✗ 新法基线失败: %s" % e)
    # 扫新闻源
    pat = re.compile(r"《([^《》]{2,18}法)》")
    act = re.compile(r"(通过|公布|施行|实施|表决|修订|颁布)")
    srcs = [("https://www.12371.cn/", r'href="(https://www\.12371\.cn/\d{4}/\d{2}/\d{2}/(?:ARTI|STUD)[^"]+\.shtml)"[^>]*>([^<]{6,60})</a>'),
            ("http://www.people.com.cn/", r'href="(https?://[a-z]+\.people\.com\.cn/n1/\d{4}/\d{4}/c\d+-\d+\.html)"[^>]*>([^<]{6,60})</a>'),
            ("https://www.gov.cn/", r'href="((?:https://www\.gov\.cn)?/[a-z]+/[^"]+?\.htm)"[^>]*>([^<]{6,60})</a>')]
    found = 0
    for home, rx in srcs:
        try:
            h = _fetch(home)
        except Exception:
            continue
        for m in re.finditer(rx, h):
            url, t = m.group(1), html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
            lm = pat.search(t)
            if not lm or not act.search(t):
                continue
            law = "《%s》" % lm.group(1)
            if law in have_titles:
                continue
            if url.startswith("/"):
                url = "https://www.gov.cn" + url
            try:
                page = _fetch(url)
                ps = re.findall(r"<p[^>]*>(.*?)</p>", page, re.S)
                body = "\n".join(x for x in (re.sub(r"<[^>]+>", "", html.unescape(p)).strip() for p in ps)
                                 if len(x) > 12)[:3500]
                if len(body) < 150:
                    continue
                reply = ai([{"role": "system", "content": "你是公考法律辅导老师，严格输出 JSON，用简体中文。"},
                            {"role": "user", "content":
                             "根据下面新闻整理这部新法律的备考条目。title=%s；content 含【施行日期(如新闻里有)】"
                             "【核心制度/亮点】【备考要点】，100~180字，只基于新闻内容不要编造。\n"
                             '只输出 JSON：{"items":[{"title":"...","content":"..."}]}\n\n新闻标题：%s\n正文：\n%s'
                             % (law, t, body)}], max_tokens=800)
                items = json.loads(reply).get("items", [])
                n = save_items(con, board, topic, items, source="新法跟踪")
                if n:
                    have_titles.add(law); found += n
                    print("✓ 新法 %s（来源：%s）" % (law, t[:30]))
            except Exception as e:
                print("✗ 新法 %s: %s" % (law, e))
    print("本次新法跟踪 +%d 条" % found)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "seed"
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS changshi_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT, board TEXT, topic TEXT, title TEXT, content TEXT,
        date TEXT, source TEXT DEFAULT 'ai', created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(board, topic, title))""")
    if mode == "seed":
        cmd_seed(con, sys.argv[2] if len(sys.argv) > 2 else None)
    elif mode == "daily":
        cmd_daily(con)
    elif mode == "newlaw":
        cmd_newlaw(con)
    total = con.execute("SELECT COUNT(*) FROM changshi_items").fetchone()[0]
    print("库内共 %d 条常识。" % total)
    con.close()


if __name__ == "__main__":
    main()
