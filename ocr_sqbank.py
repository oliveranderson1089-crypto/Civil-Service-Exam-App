#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把云盘里**没有文字层**的社区备考资料 OCR 成文字，落进 sq_ocr 表。

为什么单独一步、而且结果要落盘：OCR 很贵（2379 页），而解析规则还会改。
**OCR 一次、解析多次** —— 之后调解析规则一律从 sq_ocr 重来，绝不重跑 OCR。
真题库当年「改解析器却把 OCR 重跑一遍」的教训，这里不再犯。

配置是量出来的，不是抄来的：

    默认 tesseract                 一页 163 秒 → 2379 页 107 小时
    --oem 1 --psm 6 + DPI 150      一页  17 秒 → 2379 页  11 小时（单线程）

而且**快 10 倍的那版，识别结果和默认逐字相同**（同一页两种配置的输出完全一致）——
不是拿质量换速度，是默认配置在这类扫描件上做了无用功。

（第一次估「一页 1.4 秒」是测错了：那 1.4 秒只是 pdftoppm 转图，
tesseract 因为文件名写错根本没执行。所以这份文件头把真实数字写清楚。）

用法：
    python3 ocr_sqbank.py --scan             # 只列要跑哪些、预估多久
    python3 ocr_sqbank.py --top 12           # 先跑最高价值的 12 份
    python3 ocr_sqbank.py                    # 全跑
    python3 ocr_sqbank.py --jobs 3           # 并行度（默认按核数减一）
"""
import argparse
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from ingest_shequ import ROOT                                # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))

DPI = 150
TESS = ["-l", "chi_sim", "--oem", "1", "--psm", "6"]

# 先跑哪些：**能直接变成题或主观题素材的**排前面，大部头笔记排后面
# （四色笔记、黄金考点这些资料自己就标着「有时间就看」）。
PRIORITY = [
    (100, ("客观题复习题库", "模拟试题", "押题试卷", "考试题库", "出题必备")),
    (90, ("案例题", "主观题", "案例分析")),
    (80, ("题库", "练习题", "试题", "百题", "测试题")),
    (50, ("时政热点", "时政")),
    (20, ("四色笔记", "黄金考点", "思维导图")),
]
SKIP_NAME = ("言语理解", "资料分析", "判断推理", "数量关系", "图形推理",
             "行政职业能力", "常识判断练习")


def score_of(name):
    for sc, kws in PRIORITY:
        if any(k in name for k in kws):
            return sc
    return 60


def find_scans(con):
    rows = con.execute(
        "SELECT id,name,folder,stored_name FROM drive_files WHERE folder LIKE ? "
        "AND is_dir=0 AND deleted_at IS NULL AND ext='.pdf' ORDER BY name",
        (ROOT + "%",)).fetchall()
    out, seen = [], set()
    for r in rows:
        if r["name"] in seen or "行测职测" in r["folder"]:
            continue
        if any(k in r["name"] for k in SKIP_NAME):
            continue
        path = None
        for d in os.listdir(os.path.join(UPLOADS, "drive")):
            cand = os.path.join(UPLOADS, "drive", d, r["stored_name"])
            if os.path.exists(cand):
                path = cand
                break
        if not path:
            continue
        # 有文字层的不用 OCR。判据是「取得到字」，不是文件名或页数
        txt = subprocess.run(["pdftotext", "-f", "1", "-l", "3", path, "-"],
                             capture_output=True).stdout.decode("utf-8", "ignore")
        if len(re.sub(r"\s", "", txt)) >= 100:
            continue
        n = 0
        info = subprocess.run(["pdfinfo", path], capture_output=True).stdout.decode("utf-8", "ignore")
        m = re.search(r"^Pages:\s+(\d+)", info, re.M)
        if m:
            n = int(m.group(1))
        seen.add(r["name"])
        out.append({"file_id": r["id"], "name": r["name"], "folder": r["folder"],
                    "path": path, "pages": n, "score": score_of(r["name"])})
    out.sort(key=lambda x: (-x["score"], -x["pages"]))
    return out


def ocr_page(path, page, tmpd):
    """一页 → 文字。转图和识别都在临时目录里，跑完就删。"""
    stem = os.path.join(tmpd, "p%d" % page)
    subprocess.run(["pdftoppm", "-r", str(DPI), "-f", str(page), "-l", str(page),
                    "-png", path, stem], capture_output=True)
    png = None
    for cand in ("%s-%02d.png" % (stem, page), "%s-%d.png" % (stem, page),
                 "%s-%03d.png" % (stem, page)):
        if os.path.exists(cand):
            png = cand
            break
    if not png:
        return ""
    try:
        r = subprocess.run(["tesseract", png, "-"] + TESS, capture_output=True, timeout=300)
        return r.stdout.decode("utf-8", "ignore")
    except subprocess.TimeoutExpired:
        return ""
    finally:
        try:
            os.remove(png)
        except OSError:
            pass


def ensure_table(con):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS sq_ocr(
            file_id INTEGER NOT NULL, page INTEGER NOT NULL,
            text TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(file_id, page)
        );
    """)


def run_one(con, bank, jobs):
    have = {r[0] for r in con.execute("SELECT page FROM sq_ocr WHERE file_id=?",
                                      (bank["file_id"],))}
    todo = [p for p in range(1, bank["pages"] + 1) if p not in have]
    if not todo:
        return 0
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="sqocr-") as tmpd:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            texts = list(ex.map(lambda p: (p, ocr_page(bank["path"], p, tmpd)), todo))
    for p, t in texts:
        con.execute("INSERT OR REPLACE INTO sq_ocr(file_id,page,text) VALUES(?,?,?)",
                    (bank["file_id"], p, t))
    con.commit()
    got = sum(1 for _p, t in texts if len(re.sub(r"\s", "", t)) > 30)
    print("    %d 页，%d 页有字，用时 %.1f 分钟" % (len(todo), got, (time.time() - t0) / 60))
    return len(todo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--top", type=int, default=0, help="只跑优先级最高的前 N 份")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    ensure_table(con)
    banks = find_scans(con)
    if a.top:
        banks = banks[:a.top]
    pages = sum(b["pages"] for b in banks)
    done = con.execute("SELECT COUNT(*) FROM sq_ocr").fetchone()[0]
    print("待 OCR %d 份 %d 页（已 OCR 过 %d 页）；并行 %d 路，按 17 秒/页估约 %.1f 小时\n"
          % (len(banks), pages, done, a.jobs, pages * 17 / 3600 / max(a.jobs * 0.8, 1)))
    if a.scan:
        for b in banks[:20]:
            print("  [%3d] %4d 页  %s" % (b["score"], b["pages"], b["name"][:52]))
        return 0
    n = 0
    for i, b in enumerate(banks, 1):
        print("  (%d/%d) %s  %d 页" % (i, len(banks), b["name"][:48], b["pages"]))
        n += run_one(con, b, a.jobs)
    print("\n共 OCR %d 页，落在 sq_ocr 表里。改解析规则时从这张表重来，别重跑 OCR。" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
