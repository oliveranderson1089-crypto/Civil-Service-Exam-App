#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""错例库入库：把已有的 63 篇自产应用文过一遍格式检查器，把命中的做成成对错例。

为什么这批数据是白捡的：`fix_fentiao` 每天都在把「一是…二是…」改成规范序号，
**改之前那句话本身就是一条真实的错例**，而且是模型真犯过的错，比让 AI 编错例真实得多。
63 篇里 42 篇正文还留着这种串（fix_fentiao 上线前的存量）。

但 42 篇里有 4 篇是**讲话稿**——P1 拿 36 份真题参考答案回测发现，
用「一是…二是…」的唯一一场考试就是讲话稿（口语文种，这么写是对的）。
所以这 4 篇不能算错例，`mods/yycheck` 里按 GW_SPOKEN 豁免掉了。

错例必须**成对**（错句 + 改正 + 扣分理由），孤立的错句不入库——
看不到该怎么写的错例没有教学价值。

用法：
    python3 build_yy_errors.py --dry      # 只看会入哪些，不写库
    python3 build_yy_errors.py            # 入库（幂等，靠 UNIQUE 去重）
    python3 build_yy_errors.py --stats    # 只看库里现有的错例分布
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ.setdefault("GONGKAO_DB", os.path.join(BASE, "app.db"))

from mods.yycheck import check_all  # noqa: E402

DB = os.environ["GONGKAO_DB"]


def _title(pair, doctype):
    """UNIQUE(kind,doctype,part,title) 要靠 title 区分同一部件下的多条错例。
    用「检查项 + 错句摘要 + 短哈希」：可读，且同一条错句重跑不会重复入库。"""
    brief = re.sub(r"\s", "", pair["bad"])[:14]
    h = hashlib.sha1((doctype + pair["bad"]).encode("utf-8")).hexdigest()[:6]
    return "%s·%s·%s" % (pair["check"], brief, h)


def harvest(con, dry=False):
    rows = con.execute("SELECT id, topic, spec, content FROM daily_essays "
                       "WHERE mode LIKE 'yingyong%' AND content!=''").fetchall()
    by_check, by_dt, n_essay, ins, dup = Counter(), Counter(), 0, 0, 0
    for r in rows:
        try:
            doctype = (json.loads(r["spec"] or "{}").get("doctype")
                       or r["topic"] or "")
        except Exception:
            doctype = r["topic"] or ""
        pairs = check_all(r["content"], doctype)
        if not pairs:
            continue
        n_essay += 1
        for p in pairs:
            by_check[p["check"]] += 1
            by_dt[doctype] += 1
            if dry:
                continue
            cur = con.execute(
                "INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,note,"
                "src,src_ref) VALUES('错例',?,?,?,?,?,'essay',?)",
                (doctype, p["part"], _title(p, doctype),
                 json.dumps({"bad": p["bad"], "good": p["good"]}, ensure_ascii=False),
                 p["why"], "daily_essays:%d" % r["id"]))
            if cur.rowcount:
                ins += 1
            else:
                dup += 1
    if not dry:
        con.commit()
    print("扫了 %d 篇，%d 篇命中检查器" % (len(rows), n_essay))
    print("按检查项：%s" % "、".join("%s×%d" % kv for kv in by_check.most_common()))
    print("按文种（前 8）：%s"
          % "、".join("%s×%d" % kv for kv in by_dt.most_common(8)))
    if dry:
        print("（--dry，没写库）")
    else:
        print("入库 %d 条，已存在 %d 条（幂等）" % (ins, dup))


def stats(con):
    n = con.execute("SELECT COUNT(*) FROM yy_items WHERE kind='错例'").fetchone()[0]
    print("库内错例 %d 条" % n)
    for row in con.execute("SELECT part, COUNT(*) c FROM yy_items WHERE kind='错例' "
                           "GROUP BY part ORDER BY c DESC"):
        print("  部件 %-12s %d" % (row[0] or "（无）", row[1]))
    for row in con.execute("SELECT doctype, COUNT(*) c FROM yy_items WHERE kind='错例' "
                           "GROUP BY doctype ORDER BY c DESC LIMIT 8"):
        print("  文种 %-12s %d" % (row[0] or "（通用）", row[1]))
    bad = con.execute("SELECT title, text, note FROM yy_items WHERE kind='错例' "
                      "ORDER BY RANDOM() LIMIT 2").fetchall()
    for b in bad:
        d = json.loads(b[1] or "{}")
        print("\n  样例 [%s]\n    ✗ %s\n    ✓ %s\n    因为 %s"
              % (b[0], d.get("bad", "")[:60], d.get("good", "")[:60], (b[2] or "")[:70]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    if a.stats:
        stats(con)
    else:
        harvest(con, a.dry)


if __name__ == "__main__":
    main()
