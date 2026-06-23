#!/usr/bin/env python3
"""把 chinese-xinhua 的 idiom.json / ci.json 导入 SQLite 参考词典。

只负责构建/重建参考表 ref_idiom、ref_ci，不触碰用户收录表 entries。
可重复运行（幂等）。
"""
import json
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
DB = os.path.join(BASE, "app.db")


def load_json(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        print(f"[跳过] 找不到 {path}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # 参考表：成语
    cur.execute("DROP TABLE IF EXISTS ref_idiom")
    cur.execute(
        """CREATE TABLE ref_idiom(
            word TEXT PRIMARY KEY,
            pinyin TEXT,
            explanation TEXT,
            derivation TEXT,
            example TEXT
        )"""
    )
    idioms = load_json("idiom.json") or []
    rows = {}
    for it in idioms:
        w = (it.get("word") or "").strip()
        if not w:
            continue
        rows[w] = (
            w,
            (it.get("pinyin") or "").strip(),
            (it.get("explanation") or "").strip(),
            (it.get("derivation") or "").strip(),
            (it.get("example") or "").strip(),
        )
    cur.executemany(
        "INSERT OR REPLACE INTO ref_idiom VALUES (?,?,?,?,?)", rows.values()
    )
    print(f"[成语] 导入 {len(rows)} 条")

    # 参考表：词语（同词多义合并）
    cur.execute("DROP TABLE IF EXISTS ref_ci")
    cur.execute(
        "CREATE TABLE ref_ci(word TEXT PRIMARY KEY, explanation TEXT)"
    )
    ci = load_json("ci.json") or []
    merged = {}
    for it in ci:
        w = (it.get("ci") or "").strip()
        exp = (it.get("explanation") or "").strip()
        if not w or not exp:
            continue
        if w in merged:
            if exp not in merged[w]:
                merged[w].append(exp)
        else:
            merged[w] = [exp]
    ci_rows = [(w, "；".join(v)) for w, v in merged.items()]
    cur.executemany("INSERT OR REPLACE INTO ref_ci VALUES (?,?)", ci_rows)
    print(f"[词语] 导入 {len(ci_rows)} 条")

    con.commit()
    # 优化体积与查询
    cur.execute("VACUUM")
    con.commit()
    con.close()
    size = os.path.getsize(DB) / 1024 / 1024
    print(f"[完成] {DB}  ({size:.1f} MB)")


if __name__ == "__main__":
    build()
