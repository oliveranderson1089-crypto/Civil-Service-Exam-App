#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把真题里的图提出来，挂到对应的题上。

为什么单独一个脚本：解析入库（ingest_real.py）走的是纯文本，图是另一条线 ——
图要落盘、要去重、要和题号对上，混进去会让那边的去重逻辑更难读。

**图怎么和题对上**：图片锚在 docx 的某个 `<w:p>` 里，那一段之前最近的题号就是它所属的题。
docx_figures 和 docx_text 用的是**同一套段落切分**（都以 `</w:p>` 为界），
下标才对得上 —— 这类「两个列表用下标关联」的地方是错位事故高发区（核验答案那次就栽在这）。

图存进 uploads/realfig/，按内容 sha256 命名：同一张图在多份卷子里重复出现是常态
（副省级/地市级共题），按内容存一份就够。

跑完之后，**有图的题会解除 needs_asset**，真题练习那边立刻就能出这些题了。

用法：
    python3 ingest_figs.py --plan      # 只看能提多少，不落盘
    python3 ingest_figs.py             # 全量
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import realbank as R                                       # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))
FIGDIR = os.path.join(UPLOADS, "realfig")

SCHEMA = """
CREATE TABLE IF NOT EXISTS real_figs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qid INTEGER NOT NULL,        -- 属于哪道题（real_questions.id）
    ord INTEGER DEFAULT 0,       -- 同一题里的第几张
    sha TEXT NOT NULL,           -- 内容指纹，同时也是文件名
    ext TEXT,
    UNIQUE(qid, sha)
);
CREATE INDEX IF NOT EXISTS idx_rfig_q ON real_figs(qid);
"""

# 图太小基本是公式片段/项目符号，不是题目要看的图
_MIN_BYTES = 900


def find_path(stored):
    for d in sorted(os.listdir(os.path.join(UPLOADS, "drive"))):
        p = os.path.join(UPLOADS, "drive", d, stored)
        if os.path.exists(p):
            return p
    return None


def paper_figs(path, tmp):
    """一份卷子里 {卷面题号: [(sha, ext, 字节), ...]}。"""
    if path.lower().endswith(".doc"):
        # .doc 先转 docx（转换产物落在 tmp 里，用完即弃）
        try:
            R.doc_text(path, tmp)
        except Exception:
            return {}
        path = os.path.join(tmp, os.path.splitext(os.path.basename(path))[0] + ".docx")
        if not os.path.exists(path):
            return {}
    figs = R.docx_figures(path)
    if not figs:
        return {}
    try:
        lines = R.docx_text(path).split("\n")
    except Exception:
        return {}
    # 每个题号出现在第几段 —— 图落在哪两个题号之间，就归前面那个
    heads = [(i, int(m.group(1)))
             for i, ln in enumerate(lines)
             for m in [re.match(r"^[\s　]*(\d{1,3})[\s　]*[、.．：:]", ln)] if m]
    out = {}
    for para, blob, ext in figs:
        if len(blob) < _MIN_BYTES:
            continue
        prev = [seq for i, seq in heads if i <= para]
        if not prev:
            continue
        sha = hashlib.sha256(blob).hexdigest()[:32]
        out.setdefault(prev[-1], []).append((sha, ext or ".png", blob))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="只统计，不落盘不改库")
    a = ap.parse_args()

    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    os.makedirs(FIGDIR, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="realfig-")

    papers = con.execute(
        "SELECT p.id, p.name, d.stored_name FROM real_papers p "
        "JOIN drive_files d ON d.id=p.file_id "
        "WHERE p.role='q' AND p.ext IN ('.docx','.doc') AND p.n_item>0 "
        "ORDER BY p.year DESC").fetchall()
    print("扫 %d 份 word 版题目卷" % len(papers))

    n_fig = n_q = 0
    for p in papers:
        path = find_path(p["stored_name"])
        if not path:
            continue
        got = paper_figs(path, tmp)
        if not got:
            continue
        # 卷面题号 → real_questions.id（同一卷同一题号只会对一条）
        seq2qid = {r["seq"]: r["qid"] for r in con.execute(
            "SELECT seq, qid FROM real_raw WHERE paper_id=? AND qid IS NOT NULL", (p["id"],))}
        hit = 0
        for seq, items in got.items():
            qid = seq2qid.get(seq)
            if not qid:
                continue
            for k, (sha, ext, blob) in enumerate(items):
                if not a.plan:
                    fp = os.path.join(FIGDIR, sha + ext)
                    if not os.path.exists(fp):
                        with open(fp, "wb") as f:
                            f.write(blob)
                    con.execute("INSERT OR IGNORE INTO real_figs(qid,ord,sha,ext) VALUES(?,?,?,?)",
                                (qid, k, sha, ext))
                n_fig += 1
            hit += 1
        n_q += hit
        if hit:
            print("  %-46s %3d 道题配到图" % (p["name"][:46], hit))
    if not a.plan:
        con.commit()

    print("\n共 %d 张图挂到 %d 道题上" % (n_fig, n_q))
    if a.plan:
        return

    # 有图了就不再是「脱离图做不了」—— 放开 needs_asset，真题练习那边立刻能出这些题。
    # 只放开**判断推理**：资料分析光有图还不够，它要的是整段材料（表格里的数），
    # 那是另一件事，没做完之前放开只会让人对着半截材料做题。
    freed = con.execute(
        "UPDATE real_questions SET needs_asset=0 WHERE needs_asset=1 AND module='判断推理' "
        "AND id IN (SELECT qid FROM real_figs)").rowcount
    con.commit()
    print("解除 needs_asset：判断推理 %d 道（现在能出了）" % freed)
    left = con.execute("SELECT COUNT(*) FROM real_questions WHERE needs_asset=1 "
                       "AND module='判断推理'").fetchone()[0]
    print("判断推理仍缺图的还有 %d 道（多半来自 PDF 版，要整页渲染才行）" % left)
    con.close()


if __name__ == "__main__":
    main()
