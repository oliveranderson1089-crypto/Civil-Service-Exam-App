#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把云盘里**没有文字层**的社区备考资料 OCR 成文字，落进 sq_ocr 表。

为什么单独一步、而且结果要落盘：OCR 很贵（2379 页），而解析规则还会改。
**OCR 一次、解析多次** —— 之后调解析规则一律从 sq_ocr 重来，绝不重跑 OCR。
真题库当年「改解析器却把 OCR 重跑一遍」的教训，这里不再犯。

配置是量出来的：`--oem 1 --psm 6` + DPI 150，比默认快一个数量级，而且**识别结果和
默认逐字相同**（同一页两种配置的输出完全一致）—— 不是拿质量换速度，是默认配置在
这类扫描件上做了无用功。

**并行方式比配置更要命。** tesseract 默认自己是多线程的，外面再开 N 路并行，
同一批核就被抢 N 遍 —— 实测（同一份文件、同样 12 页）：

    4 路并行 × tesseract 多线程      48 秒/页   （2331 页要 31 小时）
    4 路并行 × OMP_THREAD_LIMIT=1   0.72 秒/页  （2331 页要 28 分钟）

**差 67 倍**，而且慢的那版是我自己写出来的。所以 tesseract 一律限成单线程，
并行度交给外面的线程池。

估时长这件事在这个脚本上错过四次，教训写在这儿：
    「1.4 秒/页」  只给 pdftoppm 计了时，tesseract 因文件名写错根本没执行
    「163 秒/页」  拿默认配置测的，换 --oem 1 --psm 6 后不成立
    「17 秒/页」   只拿一页测
    「48 秒/页」   是自己造成的资源争抢，不是真实成本
**每次都是「只给我以为慢的那一步计时」。** 所以这份脚本逐页落盘、每 5 页打一次
真实速率 —— 实报比预估可靠。单页超过 120 秒直接跳过。

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
        # **每个 tesseract 只给一个线程**，并行度交给外面的线程池。
        # tesseract 默认自己就是多线程的，再开 N 路并行等于同一批核被抢 N 遍 ——
        # 实测 4 路 × 多线程是 48 秒/页，4 路 × 单线程是 0.72 秒/页，差 67 倍。
        r = subprocess.run(["tesseract", png, "-"] + TESS, capture_output=True,
                           timeout=120, env=dict(os.environ, OMP_THREAD_LIMIT="1"))
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
    t0, got, n = time.time(), 0, 0
    # **逐页落盘 + 实时报进度**，不是整份跑完再写。第一版是后者，结果第一份 118 页
    # 的册子跑了 25 分钟、库里还是 0 页 —— 分不清是在干活还是卡死了，崩了还全丢。
    # 而且页与页的耗时**差得极大**（同一份里抽样 1.8 秒/页，实跑却有页要几分钟），
    # 单页抽样根本估不准总时长，只能边跑边看真实速率。
    with tempfile.TemporaryDirectory(prefix="sqocr-") as tmpd:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            for p, t in ex.map(lambda pg: (pg, ocr_page(bank["path"], pg, tmpd)), todo):
                con.execute("INSERT OR REPLACE INTO sq_ocr(file_id,page,text) VALUES(?,?,?)",
                            (bank["file_id"], p, t))
                con.commit()
                n += 1
                if len(re.sub(r"\s", "", t)) > 30:
                    got += 1
                if n % 5 == 0:
                    print("      …%d/%d 页　%.1f 秒/页" % (n, len(todo), (time.time() - t0) / n),
                          flush=True)
    print("    %d 页，%d 页有字，用时 %.1f 分钟" % (n, got, (time.time() - t0) / 60), flush=True)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--top", type=int, default=0, help="只跑优先级最高的前 N 份")
    # 并行度默认给满核：每个 tesseract 已被限成单线程，核数就是并行度
    ap.add_argument("--jobs", type=int, default=(os.cpu_count() or 2))
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    ensure_table(con)
    banks = find_scans(con)
    if a.top:
        banks = banks[:a.top]
    pages = sum(b["pages"] for b in banks)
    done = con.execute("SELECT COUNT(*) FROM sq_ocr").fetchone()[0]
    # 不给总时长预估：页与页差两个数量级，估出来的数只会误导（已经错过三次）。
    print("待 OCR %d 份 %d 页（已 OCR 过 %d 页）；并行 %d 路，速率跑起来才知道\n"
          % (len(banks), pages, done, a.jobs))
    if a.scan:
        for b in banks[:20]:
            print("  [%3d] %4d 页  %s" % (b["score"], b["pages"], b["name"][:52]))
        return 0
    n = 0
    for i, b in enumerate(banks, 1):
        print("  (%d/%d) %s  %d 页" % (i, len(banks), b["name"][:48], b["pages"]), flush=True)
        n += run_one(con, b, a.jobs)
    print("\n共 OCR %d 页，落在 sq_ocr 表里。改解析规则时从这张表重来，别重跑 OCR。" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
