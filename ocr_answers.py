#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描版答案卷的 OCR：把「第几题选什么」读出来。

71 份答案卷是纯扫描件（pdftotext 出 0 个字符），这是真题答案覆盖率上不去的唯一原因。

**为什么不用 DeepSeek**：deepseek-chat 是纯文本模型，读不了图。项目里配的
glm-4.6v 才是视觉模型（config.json 的 vision_model），OCR 只能走它。

**只读答案，不读解析**。答案卷上一道题的解析动辄两三百字，让视觉模型逐页抄下来
既慢又容易抄错；而「第几题选什么」是页面上最醒目、最结构化的信息，识别率高得多。
解析那一步已经有 gen_real_explain.py 用文本模型按题目现写，比抄扫描件靠谱。

识别结果照样要过既有的两道闸（题号对不对得上、跨卷对账），不因为是 OCR 就放宽 ——
错位的答案比没有答案更糟，这条在这个项目里已经用血换过教训了。

用法：
    python3 ocr_answers.py --plan            # 只统计要处理哪些卷
    python3 ocr_answers.py --limit 1         # 先跑一份看识别率
    python3 ocr_answers.py
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import realbank as R                                       # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))
CFG = json.load(open(os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json")),
                     encoding="utf-8"))
V_BASE = (CFG.get("vision_base") or "").rstrip("/")
V_KEY = CFG.get("vision_key") or ""
V_MODEL = CFG.get("vision_model") or "glm-4.6v"
DPI = 160          # 视觉模型用：再高识别率没明显提升，图却大一倍、传得慢
LOW_YIELD = 20     # tesseract 抠出的答案少于这个数，才值得花钱上视觉模型

# ⚠️ OCR 结果**必须存在独立表里、按云盘文件 id 挂**，不能挂在 real_papers 上：
#    那张表会被 ingest_real.py 整表重建（改卷别判定、改判重规则都得重跑），
#    一重建 ocr_json 就没了 —— 实测这么丢过一次，45 分钟的视觉模型调用白烧。
#    「贵且不可重现」的产物，一律别放在会被推导重建的表上。
SCHEMA = """
CREATE TABLE IF NOT EXISTS real_ocr(
    file_id INTEGER PRIMARY KEY,     -- drive_files.id，跟着云盘文件走，最稳
    name TEXT,
    n_item INTEGER DEFAULT 0,
    ans_json TEXT,                   -- {题号: 答案}
    model TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""


def url_of(base):
    if base.endswith("/chat/completions"):
        return base
    return base + ("/chat/completions" if re.search(r"/v\d+$", base) else "/v1/chat/completions")


def find_path(stored):
    for d in sorted(os.listdir(os.path.join(UPLOADS, "drive"))):
        p = os.path.join(UPLOADS, "drive", d, stored)
        if os.path.exists(p):
            return p
    return None


PROMPT = ("这是一份公务员考试答案解析卷的扫描页。请把页面上**每道题的题号和正确答案**读出来。\n"
          "· 只要题号和答案字母，**解析文字一律不要**\n"
          "· 页面上写「1、【答案】B」「1.正确答案：B」「1．B」都算\n"
          "· 看不清的宁可跳过，**绝不要猜** —— 错的答案比没有答案更糟\n"
          '只输出 JSON：{"items":[{"seq":1,"answer":"B"}]}')


def ocr_page(png, tries=3):
    """一页 → {题号: 答案}。识别不出就返回空。

    **必须重试**：71 份卷子上千页要跑几个小时，网络抖动是必然事件
    （同一个项目里 gen_real_explain 就是撞到 SSL UNEXPECTED_EOF 才加的重试）。
    这里失败即静默丢页，而外层写完 ocr_json 之后重跑会跳过整份卷子，
    缺的那几页就永远缺着了。
    """
    import base64
    with open(png, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {"model": V_MODEL, "temperature": 0.1, "max_tokens": 2000,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "user", "content": [
                   {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
                   {"type": "text", "text": PROMPT}]}]}
    req = urllib.request.Request(
        url_of(V_BASE), data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + V_KEY})
    for k in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode("utf-8"))
            txt = (d["choices"][0]["message"].get("content") or "").strip()
            m = re.search(r"\{.*\}", txt, re.S)
            got = json.loads(m.group()) if m else {}
            out = {}
            for it in got.get("items") or []:
                try:
                    seq = int(it["seq"])
                except (KeyError, TypeError, ValueError):
                    continue
                a = (it.get("answer") or "").strip().upper()[:1]
                if a in "ABCD":
                    out[seq] = a
            return out
        except Exception:
            if k == tries - 1:
                return {}
            time.sleep(3 * (k + 1))
    return {}


# tesseract 是本机装的、免费、还快 —— 同一份 37 页的卷子它 228 秒跑完，
# 视觉模型要 28 分钟。而答案卷是**高对比度印刷体**，正是 tesseract 的强项。
# 所以顺序是：先用它，抠不出足够的答案再上视觉模型兜底。
TESS_DPI = 300          # 300 比 160 明显准，本地跑不心疼


def tess_answers(pdf, tmp, first=0, last=0):
    """tesseract 识别 → {题号: 答案}。抠不出来返回空，调用方去上视觉模型。

    first/last 限定页码：很多卷子**卷首就有答案速览表**（20 行 = 100 道题的答案），
    先只读前两页，够了就不用把三四十页全渲一遍 —— 快十几倍。
    """
    base = os.path.join(tmp, "t")
    cmd = ["pdftoppm", "-png", "-r", str(TESS_DPI)]
    if first and last:
        cmd += ["-f", str(first), "-l", str(last)]
    try:
        subprocess.run(cmd + [pdf, base], capture_output=True, timeout=900)
    except Exception:
        return {}
    pngs = sorted(f for f in os.listdir(tmp) if f.startswith("t") and f.endswith(".png"))
    if not pngs:
        return {}
    txt = []
    for f in pngs:
        try:
            o = subprocess.run(["tesseract", os.path.join(tmp, f), "stdout",
                                "-l", "chi_sim+eng", "--psm", "6"],
                               capture_output=True, timeout=180)
            txt.append(o.stdout.decode("utf-8", "ignore"))
        except Exception:
            pass
    for f in pngs:                      # 识别完就删，一份卷子几十张 300dpi 大图很占地方
        try:
            os.remove(os.path.join(tmp, f))
        except OSError:
            pass
    ans, synth = R.parse_answers("\n".join(txt))
    return {} if synth else {k: v[0] for k, v in ans.items()}


def pages_of(pdf, tmp):
    try:
        subprocess.run(["pdftoppm", "-png", "-r", str(DPI), pdf, os.path.join(tmp, "p")],
                       capture_output=True, timeout=600)
    except Exception:
        return []
    return sorted(os.path.join(tmp, f) for f in os.listdir(tmp) if f.startswith("p") and
                  f.endswith(".png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--limit", type=int, help="只跑前 N 份")
    ap.add_argument("--workers", type=int, default=4, help="视觉模型的并发（tesseract 不用）")
    ap.add_argument("--tess-only", action="store_true",
                    help="只用本机 tesseract，一分钱不花（识别不出的卷子就先放着）")
    a = ap.parse_args()
    if not V_KEY:
        raise SystemExit("config.json 里没有 vision_key（OCR 要视觉模型，DeepSeek 读不了图）")

    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)

    rows = con.execute(
        "SELECT p.file_id, p.name, d.stored_name FROM real_papers p "
        "JOIN drive_files d ON d.id=p.file_id "
        "WHERE p.role='a' AND p.status='empty' AND p.ext='.pdf' "
        "  AND p.file_id NOT IN (SELECT file_id FROM real_ocr) "
        "ORDER BY p.year DESC").fetchall()
    if a.limit:
        rows = rows[:a.limit]
    print("待 OCR 的扫描版答案卷：%d 份" % len(rows))
    if a.plan or not rows:
        return

    t0 = time.time()
    for n, r in enumerate(rows, 1):
        path = find_path(r["stored_name"])
        if not path:
            continue
        tmp = tempfile.mkdtemp(prefix="ocr-")
        try:
            # ① 先扫前两页找**答案速览表**：很多卷子卷首就有，一页顶全卷
            got, how = tess_answers(path, tmp, 1, 2), "tesseract表"
            # ② 没有速览表才整卷识别（仍然是免费的 tesseract）
            if len(got) < LOW_YIELD:
                got, how = tess_answers(path, tmp), "tesseract"
            # ③ 还是太少才上视觉模型 —— 有的扫描件糊到 tesseract 认不动
            if len(got) < LOW_YIELD and not a.tess_only:
                pngs = pages_of(path, tmp)
                if pngs:
                    vis = {}
                    with ThreadPoolExecutor(max_workers=a.workers) as pool:
                        for f in as_completed({pool.submit(ocr_page, q): q for q in pngs}):
                            vis.update(f.result() or {})
                    if len(vis) > len(got):
                        got, how = vis, V_MODEL
            # 状态沿用既有的 ok/empty，不新造 'ocr' —— report() 的人工复核清单只认
            # ('answers_bad','failed','empty','thin')，新值会让 OCR 只识出三五条的
            # 那种明显失败的卷子在报告里彻底隐身
            con.execute(
                "INSERT OR REPLACE INTO real_ocr(file_id,name,n_item,ans_json,model) "
                "VALUES(?,?,?,?,?)",
                (r["file_id"], r["name"], len(got), json.dumps(got), how))
            con.commit()
            print("  [%d/%d] %-40s %3d 条答案 by %s （已跑 %.1f 分钟）"
                  % (n, len(rows), r["name"][:40], len(got), how, (time.time() - t0) / 60))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    done = con.execute("SELECT COUNT(*), COALESCE(SUM(n_item),0) FROM real_ocr").fetchone()
    print("\n完成：%s 份卷子识出 %s 条答案，耗时 %.1f 分钟"
          % (done[0], done[1] or 0, (time.time() - t0) / 60))
    print("接下来跑 `python3 ingest_real.py` —— OCR 出来的答案会和 word 版答案一样"
          "过题号对齐和跨卷对账两道闸，对不上的照样不会用。")
    con.close()


if __name__ == "__main__":
    main()
