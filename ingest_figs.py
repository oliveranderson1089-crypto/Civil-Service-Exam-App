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
import os
import shutil
import sqlite3
import subprocess
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
    big INTEGER DEFAULT 0,       -- 1 = 单张大图，多半是把整道题画在一起，一张就够
    -- kind='mat' = 资料分析的材料图（经过材料归属那条路挂上来的）；
    -- 空 = 按段落邻近挂给单题的图。两者不能混：材料齐不齐只能看前者。
    kind TEXT DEFAULT '',
    UNIQUE(qid, sha)
);
CREATE INDEX IF NOT EXISTS idx_rfig_q ON real_figs(qid);
"""

# 图太小基本是公式片段/项目符号。**滤掉要记一笔**：不记的话，一道题被滤掉了
# 选项图，上面的「图够不够」校验会误以为它本来就只有那么几张图。
_MIN_BYTES = 400
# 图形推理一道题至少要「题干序列图 + 四个选项图」，或者一张把全部内容画在一起的大图。
# 只有一两张零星小图的，多半是漏提了，放出去等于让人对着半截题干瞪眼。
_MIN_FIGS = 5
_BIG_ONE = 20000          # 单张这么大基本是整题合成图，一张也够


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
    # 题号识别**必须复用 realbank._Q_HEAD** —— real_raw.seq 就是它切出来的。
    # 这里另写一个正则的话，两边对「哪行算题号」的判断会不一致，图就挂到错的题上
    # （这类「两个解析器必须对齐」的错位，这个项目已经栽过两次）。
    heads = [(i, int(m.group(1))) for i, ln in enumerate(lines)
             for m in [R._Q_HEAD.match(ln)] if m]
    out, dropped = {}, {}
    for para, blob, ext in figs:
        prev = [seq for i, seq in heads if i <= para]
        if not prev:
            continue
        seq = prev[-1]
        if len(blob) < _MIN_BYTES:
            dropped[seq] = dropped.get(seq, 0) + 1     # 记一笔，别让校验被蒙混过去
            continue
        sha = hashlib.sha256(blob).hexdigest()[:32]
        out.setdefault(seq, []).append((sha, ext or ".png", blob))
    return out, dropped


def _to_png(blob, tmp):
    """emf/wmf 转 png（走 libreoffice）。转不了返回 None。"""
    src = os.path.join(tmp, "conv.emf")
    with open(src, "wb") as f:
        f.write(blob)
    try:
        subprocess.run(["libreoffice", "--headless", "--convert-to", "png",
                        "--outdir", tmp, src], capture_output=True, timeout=60)
        out = os.path.join(tmp, "conv.png")
        if os.path.exists(out):
            with open(out, "rb") as f:
                return f.read(), ".png"
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="只统计，不落盘不改库")
    a = ap.parse_args()

    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    # 后加的列：CREATE TABLE IF NOT EXISTS 对已存在的表什么都不做
    if "big" not in {r[1] for r in con.execute("PRAGMA table_info(real_figs)")}:
        con.execute("ALTER TABLE real_figs ADD COLUMN big INTEGER DEFAULT 0")
        con.commit()
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
        got, dropped = paper_figs(path, tmp)
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
            # ord 要在**这道题已有的图之后**续编：同一道题可能由多份卷子各贡献一批，
            # 每份都从 0 开始编的话 ord 会重复，而图形推理的图**顺序有意义**
            # （先题干序列、再四个选项），乱序等于题读不通。
            base = con.execute("SELECT COALESCE(MAX(ord),-1)+1 FROM real_figs WHERE qid=?",
                               (qid,)).fetchone()[0] if not a.plan else 0
            for k, (sha, ext, blob) in enumerate(items, base):
                if not a.plan:
                    fp = os.path.join(FIGDIR, sha + ext)
                    if not os.path.exists(fp):
                        if ext in (".emf", ".wmf"):
                            # 浏览器渲染不了 Windows 图元格式，现场转成 png；转不了就整张丢掉，
                            # 存下来只会让用户看到一个裂图（比「没有图」更难排查）
                            blob, ext = _to_png(blob, tmp) or (None, None)
                            if not blob:
                                continue
                            fp = os.path.join(FIGDIR, sha + ext)
                        with open(fp, "wb") as f:
                            f.write(blob)
                    con.execute(
                    "INSERT OR IGNORE INTO real_figs(qid,ord,sha,ext,big) VALUES(?,?,?,?,?)",
                    (qid, k, sha, ext, 1 if len(blob) >= _BIG_ONE else 0))
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
    # **图够用才放行**。一道图形推理要么有「题干图 + 四个选项图」，要么有一张画全的大图；
    # 只挂到一两张零星小图的，多半是漏提了，放出去就是让人对着半截题干瞪眼。
    # **双向**：图够了就放，图不够就锁回去。只会解封的话，早先按别的标准误放的题
    # 会被 dedup 的「原样搬运」永久固化下来。这个模块的标志位归本脚本负全责。
    ok_cond = ("(id IN (SELECT qid FROM real_figs GROUP BY qid HAVING COUNT(*)>=%d) "
               " OR id IN (SELECT qid FROM real_figs WHERE big=1))" % _MIN_FIGS)
    freed = con.execute("UPDATE real_questions SET needs_asset=0 "
                        "WHERE needs_asset=1 AND module='判断推理' AND " + ok_cond).rowcount
    relocked = con.execute(
        "UPDATE real_questions SET needs_asset=1 WHERE needs_asset=0 AND module='判断推理' "
        # 只管「本来就需要图」的那些：纯文字的判断推理题（定义判断/类比）不该被锁
        "AND (stem LIKE '%问号处%' OR stem LIKE '%图形%' OR stem LIKE '%下图%' "
        "     OR stem LIKE '%左图%' OR stem LIKE '%纸盒%' OR stem LIKE '%立体%' "
        "     OR stem LIKE '%正方体%' OR stem LIKE '%折叠%' OR stem LIKE '%展开图%') "
        "AND NOT " + ok_cond).rowcount
    con.commit()
    print("解除 needs_asset：判断推理 %d 道；锁回（图不全）：%d 道" % (freed, relocked))
    left = con.execute("SELECT COUNT(*) FROM real_questions WHERE needs_asset=1 "
                       "AND module='判断推理'").fetchone()[0]
    print("判断推理仍缺图的还有 %d 道（多半来自 PDF 版，要整页渲染才行）" % left)
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)      # .doc 转出来的 docx 用完就清，别在 /tmp 堆着


if __name__ == "__main__":
    main()
