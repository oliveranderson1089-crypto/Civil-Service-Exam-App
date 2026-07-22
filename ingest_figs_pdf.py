#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 PDF 真题里按题裁出图（word 版没有的那些卷子靠它）。

docx 里图片是独立文件、能直接提；PDF 不行 —— 图和文字压在同一张页面上。
所以换个思路：**把整页渲染成图，再按题号的纵坐标裁出这道题那一条**。

  pdftotext -bbox-layout  →  每一行的 (xMin,yMin,xMax,yMax)，还有页面尺寸
  找到第 N 题那行的 yMin、和第 N+1 题那行的 yMin  →  这就是这道题占的纵向区间
  pdftoppm 渲染整页  →  PIL 按比例裁出这一条

裁出来的图**包含题干文字**（没法只留图形），所以只给「脱离图做不了」的题用 ——
用户看到的是原卷那一条，图和题干都在，反而比只给图更接近做真题的感觉。

只处理 needs_asset=1 且**没有 word 版图**的题：word 版提出来的是干净的独立图片，
比裁页更好，有就不用这个。

用法：
    python3 ingest_figs_pdf.py --plan          # 只统计
    python3 ingest_figs_pdf.py --limit 5       # 先跑 5 份卷子看效果
    python3 ingest_figs_pdf.py
"""
import argparse
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))
FIGDIR = os.path.join(UPLOADS, "realfig")

DPI = 150
_PAGE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', re.S)
# **必须用 word 级坐标，不能用 line 级**：实测有的 PDF 里 <line> 的 yMin 大量重复
# （整页几十行全是 42.0，只有个位数的不同取值），拿它切出来的「题条」就是整页；
# 而同一份 PDF 的 <word> yMin 有 35 种取值、分布正常。
_WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="[\d.]+" yMax="([\d.]+)">([^<]*)</word>')
# 题号：和 realbank._Q_HEAD 一个路子，但这里匹配的是**一行的合并文字**
_QNO = re.compile(r"^[\s　]*(\d{1,3})[\s　]*[、.．：:]")


def find_path(stored):
    for d in sorted(os.listdir(os.path.join(UPLOADS, "drive"))):
        p = os.path.join(UPLOADS, "drive", d, stored)
        if os.path.exists(p):
            return p
    return None


def page_lines(pdf):
    """[(页码, 页高, [(yMin, 文字), ...]), ...] —— 只关心纵坐标的调用方用这个。"""
    return [(pno, h, [(y, t) for y, _x, _fh, t in ws]) for pno, h, ws in page_words(pdf)]


def page_words(pdf):
    """[(页码, 页高, [(yMin, xMin, 字高, 文字), ...]), ...]

    **x 坐标不能丢**：pdftotext 把一行拆成好几个 word，只按 y 排的话同一行内部
    是乱的 —— 「2022年，S省各级12315工作机构共接收诉求220.4万件」会变成
    「2022 12315 220.4 年，S 省各级 工作机构共接收诉求 万件」，读都读不通。
    """
    try:
        out = subprocess.run(["pdftotext", "-bbox-layout", pdf, "-"],
                             capture_output=True, timeout=300)
    except Exception:
        return []
    xml = out.stdout.decode("utf-8", "ignore")
    pages = []
    for i, m in enumerate(_PAGE.finditer(xml), 1):
        h = float(m.group(2))
        ws = [(float(y), float(x), float(y2) - float(y), t)
              for x, y, y2, t in _WORD.findall(m.group(3))]
        pages.append((i, h, ws))
    return pages


def crop_for(pdf, pages, want_seqs, tmp):
    """把 want_seqs 里每道题所在的那一条裁出来，返回 {题号: png 字节}。

    题的纵向区间 = 「本题题号那行的顶」到「下一题题号那行的顶」。
    跨页的题只取它在本页的部分 —— 图形推理的图基本都紧跟题干，够用了。
    """
    # 先把「第几题在第几页、从哪个 y 开始」找出来
    marks = []                    # (页码, 页高, y, 题号)
    for pno, h, lines in pages:
        for y0, text in lines:
            m = _QNO.match(text)
            if m:
                marks.append((pno, h, y0, int(m.group(1))))
    out = {}
    for i, (pno, h, y0, seq) in enumerate(marks):
        if seq not in want_seqs:
            continue
        # 下一个题号：同页的话用它的 y 当下边界，否则裁到页底
        y1 = h
        if i + 1 < len(marks) and marks[i + 1][0] == pno:
            y1 = marks[i + 1][2]
        if y1 - y0 < 40 or y1 - y0 > h * 0.75:
            # 太窄 = 把选项行当题号了；太宽 = 下一题没在本页、退化成整页，
            # 那样会把同页别的题一起露出来，不如不给
            continue
        im = _page_image(pdf, pno, tmp)
        if im is None:
            continue
        try:
            sc = im.height / h                       # 渲染图高 ÷ PDF 页高
            box = (0, max(0, int(y0 * sc) - 4), im.width,
                   min(im.height, int(y1 * sc) + 4))
            piece = im.crop(box)
            if piece.height < 40:
                continue
            fp = os.path.join(tmp, "crop_%d_%d.png" % (pno, seq))
            piece.save(fp, optimize=True)
            with open(fp, "rb") as f:
                out[seq] = f.read()
        except Exception:
            continue
    return out


_RENDERED = {}
_IMAGES = {}


def _page_image(pdf, pno, tmp):
    """整页的 PIL 图。**渲染和解码都只做一次** —— 一页上通常有 4~6 道图形题，
       每道题各自 Image.open 一遍等于把 1241×1754 的位图反复解码。"""
    key = (pdf, pno)
    if key not in _IMAGES:
        png = _render(pdf, pno, tmp)
        try:
            from PIL import Image
            _IMAGES[key] = Image.open(png) if png else None
        except Exception:
            _IMAGES[key] = None
    return _IMAGES[key]


def _render(pdf, pno, tmp):
    """整页渲染成 png（一页只渲一次，同一页上的题共用）。

    文件名带上卷子的哈希：tmp 是所有卷子共用的，只用 pg<页码> 的话，
    下一份卷子的第 3 页若 pdftoppm 失败，后面的 os.path.exists 会捡到**上一份卷子**
    留下的同名旧文件，静默裁出一张张冠李戴的题图。
    """
    key = (pdf, pno)
    if key in _RENDERED:
        return _RENDERED[key]
    tag = hashlib.sha256(pdf.encode()).hexdigest()[:8]
    base = os.path.join(tmp, "pg_%s_%d" % (tag, pno))
    try:
        subprocess.run(["pdftoppm", "-png", "-r", str(DPI), "-f", str(pno), "-l", str(pno),
                        pdf, base], capture_output=True, timeout=120)
    except Exception:
        _RENDERED[key] = None
        return None
    for suffix in ("-%d.png" % pno, "-%02d.png" % pno, "-%03d.png" % pno, ".png"):
        p = base + suffix
        if os.path.exists(p):
            _RENDERED[key] = p
            return p
    _RENDERED[key] = None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--limit", type=int, help="只处理前 N 份卷子")
    a = ap.parse_args()

    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    os.makedirs(FIGDIR, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="pdffig-")

    # 只找 PDF 卷子里那些「还缺图」的题：word 版能提出干净的独立图片，有就不用裁页
    rows = con.execute(
        "SELECT p.id pid, p.name, d.stored_name, rr.seq, rr.qid "
        "FROM real_papers p JOIN drive_files d ON d.id=p.file_id "
        "JOIN real_raw rr ON rr.paper_id=p.id "
        "JOIN real_questions q ON q.id=rr.qid "
        # 只裁**真正要看图的图形题**。needs_asset=1 的判断推理里混着大量定义判断
        # （题干带「是指」被当成通用句式标上的），那些是纯文字题，裁页毫无意义。
        "WHERE p.role='q' AND p.ext='.pdf' AND q.needs_asset=1 AND q.module='判断推理' "
        "  AND (q.stem LIKE '%问号处%' OR q.stem LIKE '%图形%' OR q.stem LIKE '%下图%' "
        "       OR q.stem LIKE '%左图%' OR q.stem LIKE '%纸盒%' OR q.stem LIKE '%立体%' "
        "       OR q.stem LIKE '%正方体%' OR q.stem LIKE '%折叠%' OR q.stem LIKE '%展开图%') "
        "  AND q.id NOT IN (SELECT qid FROM real_figs) "
        "ORDER BY p.id, rr.seq").fetchall()
    by_paper = {}
    for r in rows:
        by_paper.setdefault((r["pid"], r["name"], r["stored_name"]), []).append((r["seq"], r["qid"]))
    papers = list(by_paper.items())
    if a.limit:
        papers = papers[:a.limit]
    print("%d 份 PDF 卷子里有 %d 道判断推理还缺图" % (len(papers), len(rows)))
    if a.plan:
        return

    n_fig, made = 0, set()
    for (pid, name, stored), items in papers:
        path = find_path(stored)
        if not path:
            continue
        pages = page_lines(path)
        if not pages:
            continue
        want = {seq for seq, _ in items}
        got = crop_for(path, pages, want, tmp)
        seq2qid = dict(items)
        for seq, blob in got.items():
            qid = seq2qid.get(seq)
            if not qid:
                continue
            sha = hashlib.sha256(blob).hexdigest()[:32]
            fp = os.path.join(FIGDIR, sha + ".png")
            if not os.path.exists(fp):
                with open(fp, "wb") as f:
                    f.write(blob)
            # 裁出来的是**整条题**（题干+图都在），所以按大图算，一张就够
            con.execute("INSERT OR IGNORE INTO real_figs(qid,ord,sha,ext,big) VALUES(?,0,?,'.png',1)",
                        (qid, sha))
            made.add(sha)
            n_fig += 1
        con.commit()
        if got:
            print("  %-46s 裁出 %3d 道" % (name[:46], len(got)))
        _RENDERED.clear()          # 换卷子就清，别把上一份的渲染缓存留着占内存
        for im in _IMAGES.values():
            if im is not None:
                im.close()
        _IMAGES.clear()

    # 只算**本次裁出来的**那些：real_figs 里 big=1 的还有 ingest_figs.py 早先写入的
    # 整题合成图，一起 UPDATE 的话打印出来的数字混了两个来源，出问题时定位不到是哪一步
    freed = con.execute(
        "UPDATE real_questions SET needs_asset=0 WHERE needs_asset=1 AND module='判断推理' "
        "AND id IN (SELECT qid FROM real_figs WHERE sha IN (%s))"
        % (",".join("?" * len(made)) or "''"), list(made)).rowcount if made else 0
    con.commit()
    print("\n裁出 %d 张整题图，解除 needs_asset：判断推理 %d 道" % (n_fig, freed))
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
