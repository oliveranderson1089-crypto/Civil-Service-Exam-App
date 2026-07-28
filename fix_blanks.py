#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把老库里**丢掉的填空横线**补回去。

选词填空的横线在 word 里不是字符，是一串不断行空格（\xa0）。realbank.norm 早先
把它和普通空白一起压成一个空格，于是「市场主体越要\xa0×8。」入库成
「市场主体越要 。」—— 卷面上最要紧的信息（该填几个空、填在哪）就没了，
做题时看着像题干少打了两个字。norm 现在会把它还原成 ＿＿＿＿，但**只对以后
新导入的卷子生效**，库里已有的 7600 道题还是旧样子。这个脚本负责回填。

**绝不动题的身份**：只在指纹（qhash/ohash）分毫不差时才写回文本。
指纹的算法（realbank.qhash_text）会把下划线和空白一起当标点删掉，所以
「加几条横线」天然不改指纹 —— 也正因如此，这里能拿指纹当「确实是同一道题」的
铁证：对不上就跳过，宁可少补一道，也不能把 A 卷的题干写到 B 卷的题上去。

用法：
    python3 fix_blanks.py --plan     # 只看会改多少，不写库
    python3 fix_blanks.py
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import realbank as R                                       # noqa: E402
from ingest_real import md5, ohash_of                      # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))

BLANK = "＿"


def find_path(stored):
    for d in sorted(os.listdir(os.path.join(UPLOADS, "drive"))):
        p = os.path.join(UPLOADS, "drive", d, stored)
        if os.path.exists(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="只统计，不写库")
    a = ap.parse_args()

    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    papers = con.execute(
        "SELECT p.id, p.name, d.stored_name FROM real_papers p "
        "JOIN drive_files d ON d.id=p.file_id "
        "WHERE p.role='q' AND p.n_item>0 ORDER BY p.year DESC").fetchall()
    print("扫 %d 份题目卷" % len(papers))
    tmp = tempfile.mkdtemp(prefix="blanks-")

    n_raw_q = n_raw_o = n_q = n_o = 0
    skipped = 0
    for p in papers:
        path = find_path(p["stored_name"])
        if not path:
            continue
        try:
            text, _ = R.file_text(path, tmp)
            qs = R.parse_paper(text)
        except Exception:
            continue
        # 这一遍只认「补横线」这一件事，别的差异（解析器别处的漂移）一律不碰
        qs = [q for q in qs if BLANK in q["stem"]
              or any(BLANK in o for o in q["options"])]
        if not qs:
            continue
        hit = 0
        for q in qs:
            qh = md5(R.qhash_text(q["stem"]))
            oh = ohash_of(q["options"])
            opts = json.dumps(q["options"], ensure_ascii=False)
            # real_raw：这份卷子第 seq 题。指纹是入库时算的，对得上才是同一道题
            raw = con.execute(
                "SELECT id, qid, stem, options, qhash, ohash FROM real_raw "
                "WHERE paper_id=? AND seq=?", (p["id"], q["seq"])).fetchone()
            if not raw or raw["qhash"] != qh:
                skipped += 1
                continue
            if raw["stem"] != q["stem"]:
                if not a.plan:
                    con.execute("UPDATE real_raw SET stem=? WHERE id=?",
                                (q["stem"], raw["id"]))
                n_raw_q += 1
            if raw["ohash"] == oh and raw["options"] != opts:
                if not a.plan:
                    con.execute("UPDATE real_raw SET options=? WHERE id=?",
                                (opts, raw["id"]))
                n_raw_o += 1
            # real_questions：去重后的那一条。同一道题可能来自好几份卷子，
            # 所以这里也要各自比指纹 —— raw 对上了不代表 question 就是这一条。
            if raw["qid"]:
                rq = con.execute("SELECT stem, options, qhash, ohash FROM real_questions "
                                 "WHERE id=?", (raw["qid"],)).fetchone()
                if rq and rq["qhash"] == qh and rq["stem"] != q["stem"]:
                    if not a.plan:
                        con.execute("UPDATE real_questions SET stem=? WHERE id=?",
                                    (q["stem"], raw["qid"]))
                    n_q += 1
                if rq and rq["ohash"] == oh and rq["options"] != opts:
                    if not a.plan:
                        con.execute("UPDATE real_questions SET options=? WHERE id=?",
                                    (opts, raw["qid"]))
                    n_o += 1
            hit += 1
        if not a.plan:
            con.commit()
        if hit:
            print("  %-46s %3d 道带横线" % (p["name"][:46], hit))

    print("\n补回横线：题库题干 %d 道、选项 %d 道；卷面流水题干 %d 道、选项 %d 道"
          % (n_q, n_o, n_raw_q, n_raw_o))
    print("指纹对不上、按兵不动的：%d 道" % skipped)
    if a.plan:
        print("（--plan：一个字都没写）")
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
