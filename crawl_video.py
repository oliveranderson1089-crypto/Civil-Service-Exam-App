#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日新闻视频：抓 → AI 按公考价值筛 → 只留最值得看的几条。

**信源必须可验证**，所以只用白名单里的官方媒体（不接受「随便什么博主」——
无法自动确认一个账号是不是真的，那就等于把把关的活儿丢给你自己）：

  国内  央视网《新闻联播》《焦点访谈》《东方时空》     ← api.cntv.cn 官方 JSON 接口
  国际  央视网《今日关注》《环球视线》（CCTV-4）       ← 同上
  四川  川观新闻（四川日报社官方）                     ← 网页是 JS 渲染的，要用无头浏览器
  B 站  央视新闻 / 人民日报 / 新华社 / 中国日报 / 四川观察 …（都是**官方认证**号）

为什么是这几个源（都是实测出来的，不是拍脑袋）：
· 央视网的 api.cntv.cn 是**真·开放 JSON 接口**，每条都带 brief（本期内容提要）——
  这份提要正是「值不值得看」的判断依据，比标题有用得多。
· YouTube 官媒频道：网络不稳，而且用它拿央视内容对公考很绕。
· 人民网/新华网视频频道：JS 渲染 + 结构常变，正则抓不住。

B 站为什么这么绕（**不需要登录，也不需要账号密码**）：
  想拿某个 UP 的投稿列表，正规接口是 x/space/wbi/arc/search —— 但它**认登录**：
  哪怕用真浏览器打开人家主页、让页面自己带着 WBI 签名去请求，照样 -352 风控校验失败。
  绕开的办法：**搜索接口不认登录**。所以改成「搜 UP 主的名字 → 拿一堆结果 →
  只留 mid 在白名单里的」。搜索结果里混着野生 UP（搜「四川观察」会混进个人号），
  但按 mid 一过滤，剩下的就只有官方号的最新投稿 —— 等价于拿到了投稿列表，
  而且完全不用登录。风控 cookie（buvid3 等）由真实 Chrome 打开 b 站首页时自动拿到。
  mid 是搜出来核对过的（都带「官方账号」认证），不是猜的。

用法：
    .venv/bin/python3 crawl_video.py            # 抓 + 筛（定时器跑这个）
    .venv/bin/python3 crawl_video.py --no-ai    # 只抓不筛（调试用）
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as A  # noqa: E402

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")

# ---- 信源白名单：只有这些。栏目 id 是用无头浏览器从央视网真实请求里抓出来的，不是猜的 ----
CCTV_COLUMNS = [
    ("国内", "新闻联播", "TOPC1451528971114112", "央视网 · CCTV-1"),
    ("国内", "焦点访谈", "TOPC1451558976694518", "央视网 · CCTV-1"),
    ("国内", "东方时空", "TOPC1451558532019883", "央视网 · CCTV-13"),
    ("国际", "今日关注", "TOPC1451540389082713", "央视网 · CCTV-4"),
    ("国际", "环球视线", "TOPC1451558926200436", "央视网 · CCTV-4"),
]
SC_HOME = "https://cbgc.scol.com.cn/"       # 川观新闻（四川日报社）


def _get(url, timeout=15):
    r = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(r, timeout=timeout) as x:
        return x.read().decode("utf-8", "ignore")


def fetch_cctv(n=6):
    """央视网各栏目的最新几期。每条都带 brief（本期内容提要）—— 这是筛选的依据。"""
    out = []
    for board, col, cid, src in CCTV_COLUMNS:
        url = ("https://api.cntv.cn/NewVideo/getVideoListByColumn"
               "?id=%s&n=%d&sort=desc&p=1&mode=0&serviceId=tvcctv" % (cid, n))
        try:
            d = json.loads(_get(url))
        except Exception as e:
            print("  ✗ %s：%s" % (col, str(e)[:50]))
            continue
        for v in (d.get("data") or {}).get("list") or []:
            brief = re.sub(r"\s+", " ", (v.get("brief") or "")).strip()
            out.append({
                "board": board, "column": col, "source": src,
                "title": re.sub(r"\s+", " ", v.get("title") or "").strip(),
                "url": v.get("url") or "", "cover": v.get("image") or "",
                "duration": v.get("length") or "", "pub": (v.get("time") or "")[:19],
                "brief": brief,
                "guid": v.get("guid") or v.get("id") or (v.get("url") or ""),
                "kind": "cctv",
            })
        print("  ✓ %-6s %-6s %d 条" % (board, col, len(out)))
    return out


class Chrome:
    """一个可复用的无头 Chrome 会话。

    B 站和川观都得靠它（一个要真实浏览器的 cookie，一个是 JS 渲染的页面），
    所以开一个共用 —— 每开一次 Chrome 要 10 来秒，没必要开三回。
    """

    def __init__(self, port=9333):
        self.proc = subprocess.Popen(
            ["google-chrome", "--headless=new", "--remote-debugging-port=%d" % port,
             "--remote-allow-origins=*", "--no-sandbox", "--disable-gpu",
             "--disable-dev-shm-usage", "--window-size=1400,2200",
             "--disable-blink-features=AutomationControlled", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        from websocket import create_connection
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        tgt = None
        for _ in range(30):
            try:
                lst = json.load(op.open("http://127.0.0.1:%d/json" % port, timeout=3))
                tgt = next((t for t in lst if t.get("type") == "page"), None)
                if tgt:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not tgt:
            self.close()
            raise RuntimeError("Chrome 没起来")
        self.ws = create_connection(tgt["webSocketDebuggerUrl"], suppress_origin=True, timeout=60)
        self.n = 0
        self.events = []
        self._cmd("Page.enable")
        self._cmd("Network.enable")
        # 抹掉 navigator.webdriver（有些站认这个）
        self._cmd("Page.addScriptToEvaluateOnNewDocument",
                  {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"})

    def _cmd(self, m, p=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": m, "params": p or {}}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get("id") == self.n:
                return r
            if r.get("method"):
                self.events.append(r)

    def _pump(self, sec):
        """等 sec 秒，期间把页面发出的事件都收下来（要靠它抓网络请求）。"""
        end = time.time() + sec
        self.ws.settimeout(1)
        while time.time() < end:
            try:
                self.events.append(json.loads(self.ws.recv()))
            except Exception:
                pass
        self.ws.settimeout(60)

    def go(self, url, wait=8):
        self.events = []
        self._cmd("Page.navigate", {"url": url})
        self._pump(wait)

    def js(self, expr):
        r = self._cmd("Runtime.evaluate", {
            "expression": expr, "awaitPromise": True, "returnByValue": True}).get("result", {})
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"].get("exception", {}).get("description"))[:120])
        return (r.get("result") or {}).get("value")

    def media_url(self, url, wait=12):
        """打开一个页面，看它去请求了哪个视频文件 —— 直链藏在 JS 里时只能这么拿。"""
        self.go(url, wait)
        for e in self.events:
            if e.get("method") != "Network.requestWillBeSent":
                continue
            u = ((e.get("params") or {}).get("request") or {}).get("url") or ""
            if re.search(r"\.(mp4|m3u8)(\?|$)", u) and not u.startswith("blob:"):
                return u
        return ""

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def fetch_sichuan(ch, limit=20):
    """川观新闻的视频条目。页面是 JS 渲染的，只能用无头浏览器 —— 一天跑一次，值得。"""
    # ⚠️ 卡片的 innerText 里混着一堆东西：排序序号、来源媒体、「1小时前」、时长。
    #    直接当标题会得到「4 零食凉面一起上 …」「… 川观新闻 1小时前」这种垃圾 —— 得逐样剥掉。
    js = r"""
    (() => {
      const out = [];
      document.querySelectorAll('a[href*="/news/"]').forEach(a => {
        const raw = (a.innerText || '');
        const m = raw.match(/\b(\d{1,2}:\d{2})\b/);        // 有时长标记的才是视频
        if (!m) return;
        let t = raw
          .replace(m[0], '')                                  // 时长
          .replace(/\d+\s*(小时|分钟|天)前/g, '')            // 「1小时前」
          .replace(/\s+/g, ' ')
          .trim();
        t = t.replace(/^\d{1,3}\s+/, '');                    // 开头的排序序号「4 」
        // 结尾的来源媒体（川观新闻 / 精神文明报社 / 中国天气网 …）
        t = t.replace(/\s+[一-龥]{2,12}(新闻|日报|报社|电视台|网|台|社)\s*$/, '').trim();
        if (t.length < 6) return;
        const img = a.querySelector('img');
        out.push({ title: t.slice(0, 80), url: a.href, duration: m[1],
                   cover: img ? (img.src || img.dataset.src || '') : '' });
      });
      const seen = new Set();
      return JSON.stringify(out.filter(x => !seen.has(x.url) && seen.add(x.url)));
    })()
    """
    try:
        ch.go(SC_HOME, wait=9)
        items = json.loads(ch.js(js) or "[]")
    except Exception as e:
        print("  ✗ 川观新闻：%s" % str(e)[:60])
        return []
    out = []
    for x in items[:limit]:
        out.append({
            "board": "四川", "column": "川观新闻", "source": "川观新闻 · 四川日报社",
            "title": x["title"], "url": x["url"], "cover": x.get("cover") or "",
            "duration": x.get("duration") or "", "pub": time.strftime("%Y-%m-%d %H:%M:%S"),
            "brief": "", "guid": x["url"], "kind": "sc",
        })
    print("  ✓ 四川   川观新闻 %d 条" % len(out))
    return out


# ---- B 站：只认这些**官方认证**号（mid 是搜出来核对过的，都带「官方账号」认证标）----
#      注意 board 这里先不定 —— 四川观察也会发国际新闻（比如世界杯），
#      按「谁发的」定板块必错。板块交给 AI 逐条判（见 bili_boards）。
BILI_UPS = [
    ("央视新闻", 456664753, "B站 · 央视新闻官方账号"),
    ("人民日报", 1131457022, "B站 · 人民日报官方账号"),
    ("新华社", 473837611, "B站 · 新华社官方账号"),
    ("中国日报", 21778636, "B站 · 中国日报官方账号"),
    ("央视网快看", 451320374, "B站 · 央视网新闻频道官方账号"),
    ("四川观察", 487614876, "B站 · 四川广播电视台官方账号"),
]
BILI_MIDS = {mid: (name, src) for name, mid, src in BILI_UPS}


def fetch_bili(ch, per_up=6):
    """B 站官方号的最新投稿。**不需要登录，也不用账号密码。**

    投稿列表的正规接口（x/space/wbi/arc/search）认登录：哪怕用真浏览器打开人家主页、
    让页面自己带着 WBI 签名去请求，照样 -352。而**搜索接口不认登录** —— 所以改成
    「搜 UP 主的名字 → 只留 mid 在白名单里的」，等价于拿到了他的最新投稿。
    风控要的 cookie（buvid3 等）由真实 Chrome 打开 b 站首页时自动拿到。
    """
    try:
        ch.go("https://www.bilibili.com/", wait=8)          # 先拿风控 cookie
    except Exception as e:
        print("  ✗ B 站打不开：%s" % str(e)[:50])
        return []

    names = json.dumps([n for n, _, _ in BILI_UPS], ensure_ascii=False)
    expr = """(async () => {
      const out = [];
      for (const k of %s) {
        try {
          const u = 'https://api.bilibili.com/x/web-interface/search/type?search_type=video'
            + '&keyword=' + encodeURIComponent(k) + '&order=pubdate&page=1&page_size=30';
          const j = await (await fetch(u, {credentials:'include'})).json();
          for (const v of ((j.data||{}).result||[])) out.push({
            mid: v.mid, bvid: v.bvid, pubdate: v.pubdate,
            title: (v.title||'').replace(/<[^>]+>/g,''),
            desc: v.description||'', duration: v.duration||'',
            cover: (v.pic||'').replace(/^\\/\\//,'https://'), play: v.play,
          });
        } catch(e) {}
        await new Promise(r => setTimeout(r, 700));   // 别把人家接口打急了
      }
      return JSON.stringify(out);
    })()""" % names
    try:
        raw = json.loads(ch.js(expr) or "[]")
    except Exception as e:
        print("  ✗ B 站搜索失败：%s" % str(e)[:60])
        return []

    # 关键的一刀：搜索结果里混着野生 UP（搜「四川观察」会混进个人号），只留白名单 mid
    per, out = {}, []
    for v in raw:
        info = BILI_MIDS.get(v.get("mid"))
        if not info or not v.get("bvid"):
            continue
        name, src = info
        if per.get(name, 0) >= per_up:
            continue
        per[name] = per.get(name, 0) + 1
        out.append({
            "board": "",                    # 交给 AI 判（见 bili_boards）
            "column": name, "source": src,
            "title": re.sub(r"\s+", " ", v["title"]).strip()[:90],
            "url": "https://www.bilibili.com/video/%s" % v["bvid"],
            "cover": v.get("cover") or "",
            "duration": _bili_dur(v.get("duration") or ""),
            "pub": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v.get("pubdate") or 0)),
            "brief": re.sub(r"\s+", " ", v.get("desc") or "").strip()[:240],
            "guid": v["bvid"], "kind": "bili",
        })
    for name, n in per.items():
        print("  ✓ B站   %-6s %d 条" % (name, n))
    if not out:
        print("  ✗ B 站一条都没抓到（可能被风控了，明天再试）")
    return out


def _bili_dur(s):
    """B 站给的是「1:2」这种（1分2秒），补成 01:02。"""
    p = [x for x in str(s).split(":") if x != ""]
    if len(p) == 2:
        try:
            return "%02d:%02d" % (int(p[0]), int(p[1]))
        except Exception:
            pass
    return str(s)


def bili_boards(cands):
    """B 站这些条目属于哪个板块，得**逐条判**。

    不能按「谁发的」定：四川观察一样会发世界杯、发国际新闻。所以让 AI 看标题+简介来归类，
    判不出来的就丢掉（宁可少给，也别把国际新闻塞进四川板块）。
    """
    if not cands:
        return []
    lines = ["%d.【%s】%s %s" % (i + 1, c["column"], c["title"], (c["brief"][:60] or ""))
             for i, c in enumerate(cands)]
    prompt = (
        "给下面每条新闻视频判一个板块，只能是这三个之一：国内 / 国际 / 四川。\n"
        "· 四川：发生在四川、或与四川直接相关的\n"
        "· 国际：涉外、国际时事、他国内政\n"
        "· 国内：其余的国内新闻\n"
        "· 娱乐、体育花边、生活趣闻这类**对公考没用**的，board 填「无」\n\n"
        "%s\n\n"
        '只输出 JSON：{"r":[{"i":序号,"board":"国内|国际|四川|无"}]}' % "\n".join(lines))
    rep, err = A._ai_call_or_error(
        [{"role": "system", "content": "你给新闻分类。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.1, max_tokens=1200, timeout=120, json_mode=True)
    if err:
        print("  ✗ B 站板块归类失败，这批先跳过")
        return []
    try:
        rs = json.loads(rep).get("r") or []
    except Exception:
        return []
    out = []
    for r in rs:
        try:
            k = int(r.get("i")) - 1
        except Exception:
            continue
        b = (r.get("board") or "").strip()
        if 0 <= k < len(cands) and b in ("国内", "国际", "四川"):
            cands[k]["board"] = b
            out.append(cands[k])
    print("  · B 站 %d 条 → 归类后留下 %d 条" % (len(cands), len(out)))
    return out


# ---------------------------------------------------------------- AI 筛选
PICK_N = {"国内": 4, "国际": 3, "四川": 3}


def ai_pick(db, board, cands):
    """让 AI 从候选里挑出**对公考最值得看的**，并说清「为什么值得看」。
       挑不出来就宁可少给几条 —— 凑数没有意义。"""
    if not cands:
        return []
    lines = []
    for i, c in enumerate(cands):
        b = (" 内容提要：" + c["brief"][:220]) if c["brief"] else ""
        lines.append("%d.【%s】%s（%s）%s" % (i + 1, c["column"], c["title"], c["duration"], b))

    prompt = (
        "下面是今天「%s」板块的新闻视频候选。请挑出**对四川省考考生最值得看的 %d 条**。\n\n"
        "【怎么算值得看】\n"
        "· 和**考点**沾边：时政热点、重大会议、新政策、新提法、国际大事（常识判断和申论都要）\n"
        "· 能当**申论素材**：有具体案例、数据、做法、金句\n"
        "· 有**信息增量**：不是重复报道、不是纯程序性播报\n"
        "· 时长合理：太长的（超过 30 分钟）除非特别重要，否则往后排\n\n"
        "【对每条被选中的，要说清】\n"
        "· why：**为什么值得看**（一句话，讲清考点在哪 / 能当什么素材）—— 不要复述标题\n"
        "· tags：2~3 个考点标签（如「人工智能」「基层治理」「南海问题」）\n"
        "· score：值得看的程度 1~10\n\n"
        "**宁缺毋滥**：如果今天的候选里没那么多值得看的，就少挑几条，别凑数。\n\n"
        "候选：\n%s\n\n"
        '只输出 JSON：{"picks":[{"i":序号,"why":"","tags":["",""],"score":0}]}'
        % (board, PICK_N.get(board, 3), "\n".join(lines)))

    rep, err = A._ai_call_or_error(
        [{"role": "system", "content": "你是公考时政老师。只挑真正对考试有用的，宁缺毋滥。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.3, max_tokens=1500, timeout=180, json_mode=True)
    if err:
        print("  ✗ AI 筛选失败")
        return []
    try:
        picks = json.loads(rep).get("picks") or []
    except Exception:
        return []
    out = []
    for p in picks:
        try:
            k = int(p.get("i")) - 1
        except Exception:
            continue
        if not (0 <= k < len(cands)):
            continue
        c = dict(cands[k])
        c["why"] = (p.get("why") or "").strip()[:160]
        c["tags"] = [str(t)[:12] for t in (p.get("tags") or [])][:3]
        c["score"] = max(1, min(10, int(p.get("score") or 5)))
        out.append(c)
    out.sort(key=lambda x: -x["score"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ai", action="store_true", help="只抓不筛（调试）")
    ap.add_argument("--days", type=int, default=2, help="只要最近几天的")
    a = ap.parse_args()

    db = sqlite3.connect(A.DB, timeout=60)
    db.row_factory = sqlite3.Row

    print("抓取信源（都是白名单里的官方媒体）：")
    cands = fetch_cctv()
    ch = None
    try:
        ch = Chrome()                       # B 站和川观共用一个（开一次要 10 来秒，不重复开）
        cands += fetch_bili_classified(ch, a.no_ai)
        cands += fetch_sichuan(ch)
    except Exception as e:
        print("  ✗ 无头浏览器不可用：%s（这轮只有央视网的）" % str(e)[:60])
    print("  合计候选 %d 条" % len(cands))

    # 太老的不要（新闻联播那种每天一期的，只看最近两天）
    cut = time.strftime("%Y-%m-%d", time.localtime(time.time() - a.days * 86400))
    cands = [c for c in cands if (c["pub"][:10] or "9999") >= cut]
    print("  最近 %d 天的：%d 条" % (a.days, len(cands)))

    today = time.strftime("%Y-%m-%d")
    n_new = 0
    try:
        for board in ("国内", "国际", "四川"):
            sub = [c for c in cands if c["board"] == board]
            if not sub:
                continue
            picks = sub if a.no_ai else ai_pick(db, board, sub)
            print("\n【%s】候选 %d → 选中 %d" % (board, len(sub), len(picks)))
            for c in picks:
                print("  ★%d %s（%s）%s" % (c.get("score", 0), c["title"][:36],
                                           c["duration"], c["source"][:12]))
                if c.get("why"):
                    print("      %s" % c["why"][:70])
                # 只给**选中的**解析播放地址：这一步要请求人家的接口 / 渲染页面，
                # 给几十条候选全做太浪费；而且存下来之后，用户点播放是**秒开**的。
                play = resolve_play(ch, c)
                try:
                    db.execute(
                        "INSERT INTO video_items(board,column_name,source,title,url,cover,duration,"
                        "pub_date,brief,why,tags,score,guid,pick_date,kind,play) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (c["board"], c["column"], c["source"], c["title"], c["url"], c["cover"],
                         c["duration"], c["pub"], c["brief"], c.get("why", ""),
                         json.dumps(c.get("tags", []), ensure_ascii=False), c.get("score", 5),
                         c["guid"], today, c.get("kind", "sc"),
                         json.dumps(play, ensure_ascii=False) if play else None))
                    n_new += 1
                except sqlite3.IntegrityError:
                    pass          # 同一条视频已经收过了
    finally:
        if ch:
            ch.close()
    db.commit()
    print("\n入库 %d 条新视频" % n_new)


def fetch_bili_classified(ch, no_ai=False):
    """B 站：抓 → 逐条判板块（不能按「谁发的」定，四川观察也发国际新闻）。"""
    raw = fetch_bili(ch)
    if not raw:
        return []
    if no_ai:                                # 调试时不调 AI，全塞进「国内」凑合看
        for c in raw:
            c["board"] = "国内"
        return raw
    return bili_boards(raw)


def resolve_play(ch, c):
    """把这条视频**怎么播**算出来，存进库里 —— 用户点播放时就不用现去请求了。

    cctv：央视网给的 mp4 分段（渐进式 mp4，`<video>` 直接放，不用 hls.js，桌面壳也能放）
    bili：不用解析，前端嵌官方播放器就行（人家的 iframe 没有嵌入限制）
    sc  ：川观的直链藏在 JS 里 —— 只能渲染页面、看它去请求了哪个视频文件
    """
    kind = c.get("kind")
    if kind == "cctv":
        # 一条一条挨着问会被限流（单独测每条都好好的，连着问就有一半返回空分段）—— 慢一点，别催
        for attempt in range(3):
            time.sleep(1.5 if attempt == 0 else 4.0)
            try:
                return A.cctv_play(c["guid"])
            except Exception as e:
                err = str(e)[:40]
        print("      ⚠ 取央视流失败（点播放时会退回浏览器）：%s" % err)
    elif kind == "sc" and ch:
        try:
            u = ch.media_url(c["url"], wait=12)
            if u:
                return {"mode": "mp4", "chapters": [{"url": u, "dur": 0}], "total": 0}
            print("      ⚠ 川观这条没抓到直链（点播放时会退回浏览器）")
        except Exception as e:
            print("      ⚠ 川观取流失败：%s" % str(e)[:40])
    return None


if __name__ == "__main__":
    main()
