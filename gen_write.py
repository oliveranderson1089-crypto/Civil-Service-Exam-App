#!/usr/bin/env python3
"""成文：把素材写成大作文（定时器跑这个）。

  --compose        今天的「综合应用」范文（AI 自己选题）
  --daily [日期]   按素材日期成文；不给日期就是今天
  --backfill       把所有还没写的日期全部补齐（第一次用会跑很久）
  --list           看已经写了哪些

生成逻辑全在 app.py 的 _write_gen() 里，这里只是个命令行入口——
两边共用一份实现，免得 App 里改了、定时器还在跑老的。
"""
import argparse
import sqlite3
import sys
import time

from app import app
from core import DB
from mods.write import _write_gen
from mods.sucai import _sucai_import


def _con():
    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def gen(con, mode, date):
    t0 = time.time()
    with app.app_context():
        e, err = _write_gen(con, mode, date)
    if err:
        body = err[0].get_json() if hasattr(err[0], "get_json") else {}
        print("  ✗ %s %s：%s" % (mode, date, body.get("error", err)))
        return False
    print("  ✓ %s %s《%s》%d 字 · 用了 %d 条素材 · %.0fs"
          % (mode, date, e["title"], e["words"],
             len(__import__("json").loads(e["used"])), time.time() - t0))
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--compose", action="store_true", help="今天的综合应用范文")
    p.add_argument("--daily", nargs="?", const="", metavar="日期", help="按素材日期成文")
    p.add_argument("--backfill", action="store_true", help="补齐所有还没写的日期")
    p.add_argument("--list", action="store_true")
    a = p.parse_args()
    con = _con()

    if a.list:
        for r in con.execute("SELECT mode,date,title,words FROM daily_essays "
                             "ORDER BY mode, date DESC"):
            print("%-8s %s  %-24s %4d 字" % (r["mode"], r["date"], r["title"], r["words"]))
        return

    if a.compose:
        gen(con, "compose", time.strftime("%Y-%m-%d"))

    if a.daily is not None:
        gen(con, "daily", a.daily or time.strftime("%Y-%m-%d"))

    if a.backfill:
        with app.app_context():
            _sucai_import(con)
        todo = [r[0] for r in con.execute(
            "SELECT DISTINCT s.date FROM sucai_items s WHERE NOT EXISTS("
            "SELECT 1 FROM daily_essays e WHERE e.mode='daily' AND e.date=s.date) "
            "ORDER BY s.date")]
        if not todo:
            print("已经全部写完了")
            return
        print("要补 %d 天：" % len(todo))
        ok = sum(1 for d in todo if gen(con, "daily", d))
        print("完成 %d/%d" % (ok, len(todo)))

    if not (a.compose or a.daily is not None or a.backfill):
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
