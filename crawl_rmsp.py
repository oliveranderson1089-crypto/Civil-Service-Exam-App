#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日抓《人民日报》「人民时评」—— 标准的申论大作文范本，存进 essay_models 表。

为什么是「人民时评」：它篇篇都是「提出问题→分析问题→给对策」的完整议论文，
900~1500 字，还带可直接借鉴的过渡句和金句，是申论大作文最好的临摹对象。

怎么抓（都是实测出来的，见 README）：
  paper.people.com.cn 的版式很规整，一天分好几个版：
    1) 版面导航   /rmrb/pc/layout/YYYYMM/DD/node_01.html   ← 列出「05版：评论」这样的标签
    2) 评论版页面 /rmrb/pc/layout/YYYYMM/DD/node_05.html   ← 文章标题带栏目名「（人民时评）」
    3) 文章全文   /rmrb/pc/content/YYYYMM/DD/content_NNNNN.html
  评论版**不一定固定在 05 版**，所以先从 node_01 里按「评论」两字找到是第几版，别写死。

用法：
    .venv/bin/python3 crawl_rmsp.py            # 抓今天（没出报就抓昨天）
    .venv/bin/python3 crawl_rmsp.py --date 20260714
    .venv/bin/python3 crawl_rmsp.py --back 7   # 往前补 7 天（首次铺一批）
"""
import argparse
import os
import re
import sqlite3
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import DB  # noqa: E402

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")
BASE = "http://paper.people.com.cn/rmrb/pc"
COLUMN = "人民时评"


def _get(url, timeout=15):
    r = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(r, timeout=timeout) as x:
        return x.read().decode("utf-8", "ignore")


def find_comment_node(ym, d):
    """从版面导航里找出「评论」是第几版，返回它的 node 文件名（如 node_05.html）。"""
    nav = _get("%s/layout/%s/%s/node_01.html" % (BASE, ym, d))
    # 形如：node_05.html">05版：评论  （标签里带版名）
    for node, name in re.findall(r'(node_\d+\.html)"[^>]*>\s*([^<]{2,40})', nav):
        if "评论" in name:
            return node
    return None


def find_column_article(ym, d, node):
    """在评论版页面里，按标题末尾的「（人民时评）」定位那篇，返回 (content 文件名, 标题)。"""
    page = _get("%s/layout/%s/%s/%s" % (BASE, ym, d, node))
    for cont, title in re.findall(r'(content_\d+\.html)"[^>]*>\s*([^<]{2,60})', page):
        title = re.sub(r"\s+", " ", title).strip()
        if ("（%s）" % COLUMN) in title or ("(%s)" % COLUMN) in title:
            return cont, title
    return None, None


def _clean_p(p):
    """一个 <p>...</p> → 纯文本；顺手剥掉末尾常混进的页面元数据（「30168632http://…」）。"""
    t = re.sub(r"<[^>]+>", "", p)
    t = re.sub(r"\d{6,}https?://\S+", "", t)
    return re.sub(r"\s+", " ", t).strip()


def fetch_article(ym, d, cont):
    """取全文页：标题、作者、提要、正文。人民日报的正文都在 id="ozoom" 里。"""
    url = "%s/content/%s/%s/%s" % (BASE, ym, d, cont)
    h = _get(url)

    title = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
    if m:
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
    title = re.sub(r"[（(]%s[)）]\s*$" % COLUMN, "", title).strip()   # 去掉标题里的「（人民时评）」
    sub = ""
    m = re.search(r"<h2[^>]*>(.*?)</h2>", h, re.S)
    if m:
        sub = re.sub(r"<[^>]+>", "", m.group(1)).strip()
    if sub:
        title = title + " " + sub

    # 作者：页面里藏了个 <author>魏哲哲</author> 的元数据，最干净
    author = ""
    m = re.search(r"<author>\s*(.*?)\s*</author>", h, re.S)
    if m:
        author = re.sub(r"<[^>]+>|\s+", "", m.group(1))[:20]

    m = re.search(r'id=["\']ozoom["\'][^>]*>(.*?)</div>', h, re.S)
    if not m:
        return None
    # ⚠️ 先**保留空段**：人民时评的「提要」是第一段，紧跟一个空 <p> 作分隔 —— 这个空段就是识别信号。
    raw = [_clean_p(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", m.group(1), re.S)]

    pull = ""
    if len(raw) >= 3 and raw[0] and not raw[1]:      # 首段有字、次段空 → 首段是提要
        pull = raw[0]
        raw = raw[2:]
    paras = [p for p in raw if p]                    # 现在再把空段清掉
    if not paras:
        return None
    content = "\n".join(paras)
    return {"title": title, "author": author, "pullquote": pull,
            "content": content, "url": url}


def crawl_one(db, ym, d):
    """抓某一天的人民时评，入库。已收过（source_url 撞了）就跳过。返回 True=新入库。"""
    try:
        node = find_comment_node(ym, d)
    except Exception as e:
        print("  ✗ %s-%s 取版面导航失败：%s" % (ym, d, str(e)[:50]))
        return False
    if not node:
        print("  · %s-%s 没找到评论版（可能当天没出报）" % (ym, d))
        return False
    cont, listed = find_column_article(ym, d, node)
    if not cont:
        print("  · %s-%s 评论版里没有「%s」栏目" % (ym, d, COLUMN))
        return False
    url = "%s/content/%s/%s/%s" % (BASE, ym, d, cont)
    if db.execute("SELECT 1 FROM essay_models WHERE source_url=?", (url,)).fetchone():
        print("  · %s-%s 已收过：%s" % (ym, d, listed))
        return False
    try:
        art = fetch_article(ym, d, cont)
    except Exception as e:
        print("  ✗ %s-%s 取全文失败：%s" % (ym, d, str(e)[:50]))
        return False
    if not art or len(art["content"]) < 300:
        print("  ✗ %s-%s 正文太短，跳过" % (ym, d))
        return False
    pub = "%s-%s-%s" % (ym[:4], ym[4:6], d)
    db.execute(
        "INSERT INTO essay_models(pub_date,column_name,title,author,source_url,pullquote,content) "
        "VALUES(?,?,?,?,?,?,?)",
        (pub, COLUMN, art["title"], art["author"], art["url"], art["pullquote"], art["content"]))
    db.commit()
    print("  ✓ %s 《%s》%s（%d 字）"
          % (pub, art["title"][:30], ("· " + art["author"]) if art["author"] else "", len(art["content"])))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="指定日期 YYYYMMDD")
    ap.add_argument("--back", type=int, default=0, help="从今天往前补几天（首次铺量用）")
    a = ap.parse_args()

    db = sqlite3.connect(DB, timeout=60)
    db.row_factory = sqlite3.Row

    days = []
    if a.date:
        days = [a.date]
    else:
        # 今天的报早上才出；抓不到就退到昨天。--back 再往前补。
        for i in range(0, max(1, a.back) + 1):
            days.append(time.strftime("%Y%m%d", time.localtime(time.time() - i * 86400)))

    n = 0
    for ymd in days:
        ym, d = ymd[:6], ymd[6:8]
        if crawl_one(db, ym, d):
            n += 1
        time.sleep(1.0)          # 对人家服务器客气点
    print("\n入库 %d 篇人民时评" % n)


if __name__ == "__main__":
    main()
