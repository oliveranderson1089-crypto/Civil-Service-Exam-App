#!/usr/bin/env python3
"""把 data/classics.json（唐诗宋词·四书五经，已转简体）导入 app.db 的 classics 表。
用法：.venv/bin/python3 build_classics.py   （GONGKAO_DB 可指定数据库路径）
重复运行会先清空 classics 再重建（收藏表 classic_stars 不动）。"""
import json
import os
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
SRC = os.path.join(BASE, "data", "classics.json")


def main():
    data = json.load(open(SRC, encoding="utf-8"))
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS classics(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT, title TEXT, author TEXT, dynasty TEXT, content TEXT, sub TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_classics_cat ON classics(category);
        """
    )
    con.execute("DELETE FROM classics")
    con.executemany(
        "INSERT INTO classics(category,title,author,dynasty,content,sub) VALUES(?,?,?,?,?,?)",
        [(r["category"], r["title"], r["author"], r["dynasty"], r["content"], r.get("sub", ""))
         for r in data])
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM classics").fetchone()[0]
    cats = con.execute("SELECT category, COUNT(*) FROM classics GROUP BY category").fetchall()
    con.close()
    print("导入完成：%d 条 -> %s" % (n, DB))
    for c, k in cats:
        print("  %s: %d" % (c, k))


if __name__ == "__main__":
    main()
