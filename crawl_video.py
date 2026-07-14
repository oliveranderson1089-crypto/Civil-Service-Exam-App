#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日新闻视频：抓 → AI 按公考价值筛 → 只留最值得看的几条。

**信源必须可验证**，所以只用白名单里的官方媒体（不接受「随便什么博主」——
无法自动确认一个账号是不是真的，那就等于把把关的活儿丢给你自己）：

  国内  央视网《新闻联播》《焦点访谈》《东方时空》     ← api.cntv.cn 官方 JSON 接口
  国际  央视网《今日关注》《环球视线》（CCTV-4）       ← 同上
  四川  川观新闻（四川日报社官方）                     ← 网页是 JS 渲染的，要用无头浏览器

为什么是这几个源（都是实测出来的，不是拍脑袋）：
· B 站官媒号（四川观察、央视新闻）**有风控**：不带登录 cookie 就 -352，靠不住。
· YouTube 官媒频道：网络不稳，而且用它拿央视内容对公考很绕。
· 人民网/新华网视频频道：JS 渲染 + 结构常变，正则抓不住。
· 央视网的 api.cntv.cn 是**真·开放 JSON 接口**，而且每条都带 brief（本期内容提要）——
  这份提要正是「值不值得看」的判断依据，比标题有用得多。

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
            })
        print("  ✓ %-6s %-6s %d 条" % (board, col, len(out)))
    return out


def fetch_sichuan(limit=20):
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
        t = t.replace(/\s+[\u4e00-\u9fa5]{2,12}(新闻|日报|报社|电视台|网|台|社)\s*$/, '').trim();
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
        raw = _chrome_eval(SC_HOME, js, wait=9)
        items = json.loads(raw or "[]")
    except Exception as e:
        print("  ✗ 川观新闻：%s" % str(e)[:60])
        return []
    out = []
    for x in items[:limit]:
        out.append({
            "board": "四川", "column": "川观新闻", "source": "川观新闻 · 四川日报社",
            "title": x["title"], "url": x["url"], "cover": x.get("cover") or "",
            "duration": x.get("duration") or "", "pub": time.strftime("%Y-%m-%d %H:%M:%S"),
            "brief": "", "guid": x["url"],
        })
    print("  ✓ 四川   川观新闻 %d 条" % len(out))
    return out


def _chrome_eval(url, expr, wait=8):
    """开一个临时无头 Chrome，渲染页面后跑一段 JS 取结果。用完就关。"""
    import websocket   # noqa: F401  （venv 里已有）
    from websocket import create_connection
    port = 9333
    proc = subprocess.Popen(
        ["google-chrome", "--headless=new", "--remote-debugging-port=%d" % port,
         "--remote-allow-origins=*", "--no-sandbox", "--disable-gpu",
         "--disable-dev-shm-usage", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        tgt = None
        for _ in range(20):
            try:
                lst = json.load(op.open("http://127.0.0.1:%d/json" % port, timeout=3))
                tgt = next((t for t in lst if t.get("type") == "page"), None)
                if tgt:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not tgt:
            raise RuntimeError("Chrome 没起来")
        ws = create_connection(tgt["webSocketDebuggerUrl"], suppress_origin=True, timeout=30)
        n = [0]

        def cmd(m, p=None):
            n[0] += 1
            ws.send(json.dumps({"id": n[0], "method": m, "params": p or {}}))
            while True:
                r = json.loads(ws.recv())
                if r.get("id") == n[0]:
                    return r
        cmd("Page.enable")
        cmd("Page.navigate", {"url": url})
        time.sleep(wait)
        r = cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        ws.close()
        return (r.get("result") or {}).get("result", {}).get("value")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


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
    cands = fetch_cctv() + fetch_sichuan()
    print("  合计候选 %d 条" % len(cands))

    # 太老的不要（新闻联播那种每天一期的，只看最近两天）
    cut = time.strftime("%Y-%m-%d", time.localtime(time.time() - a.days * 86400))
    cands = [c for c in cands if (c["pub"][:10] or "9999") >= cut]
    print("  最近 %d 天的：%d 条" % (a.days, len(cands)))

    today = time.strftime("%Y-%m-%d")
    n_new = 0
    for board in ("国内", "国际", "四川"):
        sub = [c for c in cands if c["board"] == board]
        if not sub:
            continue
        picks = sub if a.no_ai else ai_pick(db, board, sub)
        print("\n【%s】候选 %d → 选中 %d" % (board, len(sub), len(picks)))
        for c in picks:
            print("  ★%d %s（%s）" % (c.get("score", 0), c["title"][:40], c["duration"]))
            if c.get("why"):
                print("      %s" % c["why"][:70])
            try:
                db.execute(
                    "INSERT INTO video_items(board,column_name,source,title,url,cover,duration,"
                    "pub_date,brief,why,tags,score,guid,pick_date) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (c["board"], c["column"], c["source"], c["title"], c["url"], c["cover"],
                     c["duration"], c["pub"], c["brief"], c.get("why", ""),
                     json.dumps(c.get("tags", []), ensure_ascii=False), c.get("score", 5),
                     c["guid"], today))
                n_new += 1
            except sqlite3.IntegrityError:
                pass          # 同一条视频已经收过了
    db.commit()
    print("\n入库 %d 条新视频" % n_new)


if __name__ == "__main__":
    main()
