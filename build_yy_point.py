#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「要点」类素材：正文的「肉」——举措句、成效表述、政策依据。零 AI 调用。

**不是从给定资料里现抽**，而是把库里已有的两批东西归类挂到 (文种, 部件) 上：

  · `gaikuo_items`（规范概括句）→ 主体·举措 / 主体·成效 / 主体·问题
    这批本来就是「材料表述 → 规范概括句」提炼出来的**做法概括**，
    正是应用文正文主体要写的东西。
  · `changkao_items`（提法）→ 开头·缘由（政策依据）
    这批是「新质生产力 / 乡村振兴战略」这类术语+定义，是发文的依据不是做法。

为什么不去给定资料里挖：「表述」那次已经用数据证明，语料一小，统计挖掘只会挖出
话题词（「生猪养殖管理」「凰河流域文化建设」）。给定资料是**原始材料**不是规范表述，
挖出来只会更杂。现成的这两批已经是提炼过的。

**部件怎么定**：先按句首动词族判「成效 / 问题」，都不是的**默认归举措**。
不堆一张长动词表去认举措——规范概括句按构造就是做法概括，
默认举措比「动词表里没有就认不出」诚实（实测那样 66% 认不出，
而认不出的那些「弘扬奋斗精神…」「发挥党员先锋模范作用…」明明也是举措）。

**domain（治理领域）是这一类的命门**：写垃圾分类的简报时，一条科技创新的举措句
毫无用处。所以每条都挂 topic 当 domain，取用时按领域匹配。

用法：
    python3 build_yy_point.py --dry
    python3 build_yy_point.py
"""
import argparse
import os
import re
import sqlite3
import sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))

# 成效句：说结果的。问题句：说不足的。都不是 → 举措（默认）
_EFF = re.compile(r"^(实现|取得|形成|提升|提高|增强|扩大|降低|减少|缩短|惠及|覆盖|"
                  r"迈上|跃居|位居)")
_PRB = re.compile(r"^(存在|缺乏|不足|亟需|亟待|尚未|滞后|薄弱|难以|面临.{0,6}(?:问题|挑战|困境))")


def part_of(sentence):
    s = re.sub(r"\s", "", sentence or "")
    if _PRB.match(s):
        return "主体·问题"
    if _EFF.match(s):
        return "主体·成效"
    return "主体·举措"


def run(con, dry=False):
    recs = []
    for r in con.execute("SELECT id, topic, sentence, tip FROM gaikuo_items "
                         "WHERE sentence!='' ORDER BY id"):
        s = re.sub(r"\s", "", r["sentence"])
        if len(s) < 12:
            continue
        recs.append(dict(part=part_of(s), domain=(r["topic"] or "").strip(),
                         title=s[:26], text=s, note=r["tip"] or "",
                         src="news", ref="gaikuo_items:%d" % r["id"]))
    n_gk = len(recs)
    for r in con.execute("SELECT id, title, content FROM changkao_items "
                         "WHERE board='提法' AND content!='' ORDER BY id"):
        recs.append(dict(part="开头·缘由", domain=(r["title"] or "").strip(),
                         title=(r["title"] or "")[:26],
                         text="%s：%s" % (r["title"], re.sub(r"\s", "", r["content"])),
                         note="政策依据/常考提法——写在开头交代发文依据，不是正文做法",
                         src="seed", ref="changkao_items:%d" % r["id"]))

    print("要点 %d 条：概括句 %d 条 · 常考提法 %d 条" % (len(recs), n_gk, len(recs) - n_gk))
    print("\n按部件：")
    for k, v in Counter(x["part"] for x in recs).most_common():
        print("   %-12s %3d (%.0f%%)" % (k, v, 100.0 * v / len(recs)))
    print("\n按治理领域（前 8，取用时靠它匹配）：")
    for k, v in Counter(x["domain"] for x in recs if x["domain"]).most_common(8):
        print("   %-10s %d" % (k, v))
    print("\n== 样例 ==")
    for x in recs[:3] + recs[n_gk:n_gk + 2]:
        print("  [%s|%s] %s" % (x["part"], x["domain"] or "?", x["text"][:52]))
    if dry:
        print("\n（--dry，没写库）")
        return

    ins = upd = 0
    for x in recs:
        cur = con.execute(
            "INSERT OR IGNORE INTO yy_items(kind,doctype,part,cat,domain,title,text,note,"
            "src,src_ref) VALUES('要点','',?,'',?,?,?,?,?,?)",
            (x["part"], x["domain"], x["title"], x["text"], x["note"], x["src"], x["ref"]))
        ins += 1 if cur.rowcount else 0
        upd += 0 if cur.rowcount else 1
    con.commit()
    print("\n入库 %d 条，已存在 %d 条" % (ins, upd))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    run(con, a.dry)


if __name__ == "__main__":
    main()
