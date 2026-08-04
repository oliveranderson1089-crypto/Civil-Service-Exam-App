#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把真题参考答案灌进 yy_items 的「范文」类。零 AI 调用。

这批是**阅卷认可的写法**，价值在两处：
  ① 用户能看到「这道题标准答案长什么样」——比自产范文可靠
  ② 自产的 63 篇终于有了可比的标尺

**带一道乱码闸**。有的答案是从 OCR 出来的扫描件配对过来的，带识别错字：
「从工商执法到部门吾合为工商和质检…食药监等部分隘合成并市场利过局」
（应为「部门合并」「整合成市场监管局」）。范文里有错字会教错，
所以按「拉丁字符占比 / 汉字占比」筛——真题答案几乎全是汉字，
OCR 乱码会混进成片的拉丁字符。实测 47 条里中位数是拉丁 0%、汉字 89%，
坏的那条是拉丁 9%、汉字 75%，次高才 3.4%，界限很清楚。

用法：
    python3 build_yy_fanwen.py --dry
    python3 build_yy_fanwen.py
"""
import argparse
import os
import re
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))

# 乱码闸。阈值定在实测的空档里：好的最高拉丁 3.4%，坏的 9.0%
MAX_LATIN, MIN_CJK = 0.05, 0.78


def garbled(text):
    """→ (是否乱码, 原因)。"""
    a = re.sub(r"\s", "", text or "")
    if len(a) < 40:
        return True, "太短(%d 字)" % len(a)
    lat = len(re.findall(r"[A-Za-z]", a)) / len(a)
    cjk = len(re.findall(r"[一-龥]", a)) / len(a)
    if lat > MAX_LATIN:
        return True, "拉丁字符 %.0f%%（疑 OCR 乱码）" % (lat * 100)
    if cjk < MIN_CJK:
        return True, "汉字只占 %.0f%%（疑 OCR 乱码）" % (cjk * 100)
    return False, ""


def first_line_title(text):
    """答案自带的标题：第一行短句、不带句末标点、不是称谓。"""
    for ln in [x.strip() for x in (text or "").split("\n") if x.strip()][:2]:
        s = re.sub(r"\s", "", ln)
        if 4 <= len(s) <= 34 and not s.endswith(("：", ":", "。", "；")) \
                and not re.match(r"^[一二三四五六（(]", s):
            return s
    return ""


def run(con, dry=False):
    seen, keep, drop = set(), [], []
    for r in con.execute(
            "SELECT p.year, p.exam, COALESCE(p.kind,'') k, p.era, q.seq, q.doctype, "
            "q.family, q.words, q.score, q.answer, q.ans_note "
            "FROM slreal_questions q JOIN slreal_papers p ON p.id=q.paper_id "
            "WHERE q.qkind='贯彻执行' AND q.answer!='' ORDER BY p.year DESC"):
        key = (r["year"], r["exam"], r["k"], r["seq"])
        if key in seen:
            continue
        seen.add(key)
        bad, why = garbled(r["answer"])
        (drop if bad else keep).append((dict(r), why))

    print("去重后 %d 条真题参考答案：可用 %d 条 · 乱码剔除 %d 条"
          % (len(seen), len(keep), len(drop)))
    if drop:
        print("\n== 剔除的（范文里有错字会教错） ==")
        for d, why in drop:
            print("   %s %s %-12s %s" % (d["year"], d["exam"], d["doctype"] or "?", why))
            if d["ans_note"]:
                print("       来源：%s" % d["ans_note"])
    print("\n== 入库样例 ==")
    for d, _w in keep[:4]:
        t = first_line_title(d["answer"]) or "（无标题）"
        print("   [%s %s·%s] %s（%s 分 / 限 %s 字）"
              % (d["year"], d["exam"], d["doctype"] or "?", t, d["score"], d["words"]))
    if dry:
        print("\n（--dry，没写库）")
        return

    ins = upd = 0
    for d, _w in keep:
        title = "%s%s%s·%s" % (d["year"], d["exam"], d["k"], d["doctype"] or "应用文")
        note = ("真题参考答案（%s 分 / 限 %s 字 / 实际 %d 字）%s"
                % (d["score"] or "?", d["words"] or "?",
                   len(re.sub(r"\s", "", d["answer"])),
                   "。" + d["ans_note"] if d["ans_note"] else ""))
        cur = con.execute(
            "INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,note,example,"
            "src,src_ref,freq) VALUES('范文',?,'',?,?,?,?,'real',?,?)",
            (d["doctype"] or "", title, d["answer"], note,
             first_line_title(d["answer"]),
             "%s%s Q%s" % (d["year"], d["exam"], d["seq"]),
             2 if d["era"] == "new" else 1))
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
