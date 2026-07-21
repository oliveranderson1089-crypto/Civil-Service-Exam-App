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

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))
CFG = json.load(open(os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json")),
                     encoding="utf-8"))
V_BASE = (CFG.get("vision_base") or "").rstrip("/")
V_KEY = CFG.get("vision_key") or ""
V_MODEL = CFG.get("vision_model") or "glm-4.6v"
DPI = 160          # 再高识别率没明显提升，图却大一倍、传得慢


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
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if not V_KEY:
        raise SystemExit("config.json 里没有 vision_key（OCR 要视觉模型，DeepSeek 读不了图）")

    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    if "ocr_json" not in {r[1] for r in con.execute("PRAGMA table_info(real_papers)")}:
        # OCR 结果单独存一列：贵、慢、不该每次重跑；后面对齐规则改了也能直接复用
        con.execute("ALTER TABLE real_papers ADD COLUMN ocr_json TEXT")
        con.commit()

    rows = con.execute(
        "SELECT p.id, p.name, d.stored_name FROM real_papers p "
        "JOIN drive_files d ON d.id=p.file_id "
        "WHERE p.role='a' AND p.status='empty' AND p.ext='.pdf' "
        "  AND (p.ocr_json IS NULL OR p.ocr_json='') "
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
            pngs = pages_of(path, tmp)
            if not pngs:
                continue
            got = {}
            with ThreadPoolExecutor(max_workers=a.workers) as pool:
                for f in as_completed({pool.submit(ocr_page, p): p for p in pngs}):
                    got.update(f.result() or {})
            # 状态沿用既有的 ok/empty，不新造 'ocr' —— report() 的人工复核清单只认
            # ('answers_bad','failed','empty','thin')，新值会让 OCR 只识出三五条的
            # 那种明显失败的卷子在报告里彻底隐身
            con.execute("UPDATE real_papers SET ocr_json=?, n_item=?, status=?, note=? WHERE id=?",
                        (json.dumps(got), len(got), "ok" if len(got) >= 20 else "empty",
                         ("扫描件 OCR（视觉模型 %s）识出 %d 条" % (V_MODEL, len(got))) if got
                         else "扫描件 OCR 也没识出答案（图太糊或不是答案页）", r["id"]))
            con.commit()
            print("  [%d/%d] %-44s %3d 页 → %3d 条答案  （已跑 %.1f 分钟）"
                  % (n, len(rows), r["name"][:44], len(pngs), len(got), (time.time() - t0) / 60))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    done = con.execute("SELECT COUNT(*), SUM(n_item) FROM real_papers WHERE ocr_json<>''").fetchone()
    print("\n完成：%s 份卷子识出 %s 条答案，耗时 %.1f 分钟"
          % (done[0], done[1] or 0, (time.time() - t0) / 60))
    print("接下来跑 `python3 ingest_real.py` —— OCR 出来的答案会和 word 版答案一样"
          "过题号对齐和跨卷对账两道闸，对不上的照样不会用。")
    con.close()


if __name__ == "__main__":
    main()
