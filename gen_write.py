#!/usr/bin/env python3
"""成文：把素材写成文章（定时器跑这个）。

议论文（大作文）：
  --daily [日期]   按素材日期成文；不给日期就是今天
  --compose        今天的「综合应用」范文（AI 自己选题）
  --backfill       把所有还没写的日期全部补齐（第一次用会跑很久）
应用文（公文）：
  --yy-daily [日期] 每天轮一个文种的应用文；不给日期就是今天
  --yy-compose     今天的「综合应用能力」大题（AI 出材料 + 要求 + 范文）
其它：
  --align-all      把已有议论文的「提纲 ↔ 正文」全部对一遍（见 mods/align）
  --list           看已经写了哪些

生成逻辑全在 mods/write、mods/gongwen、mods/align 里，这里只是个命令行入口——
两边共用一份实现，免得 App 里改了、定时器还在跑老的。
"""
import argparse
import json
import re
import sqlite3
import sys
import time

from app import app
from core import DB
from mods.align import survey
from mods.gongwen import _align_one, _gen_yingyong, _gen_yy_compose, _pick_daily_yy
from mods.sucai import _sucai_import
from mods.write import _e_row, _write_gen


def _con():
    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def gen(con, mode, date):
    """议论文一篇。"""
    t0 = time.time()
    with app.app_context():
        e, err = _write_gen(con, mode, date)
    if err:
        body = err[0].get_json() if hasattr(err[0], "get_json") else {}
        print("  ✗ %s %s：%s" % (mode, date, body.get("error", err)))
        return False
    print("  ✓ %s %s《%s》%d 字 · 用了 %d 条素材 · %.0fs"
          % (mode, date, e["title"], e["words"], len(json.loads(e["used"])), time.time() - t0))
    return True


def gen_yy(con, kind, date):
    """应用文一篇。kind='daily' 每日轮一个文种；kind='compose' 综合应用能力大题。"""
    t0 = time.time()
    with app.app_context():
        if kind == "compose":
            eid, err = _gen_yy_compose(con, date)
        else:
            eid, err = _gen_yingyong(con, _pick_daily_yy(con, date),
                                     mode="yingyong-daily", date=date)
    if err:
        body = err[0].get_json() if hasattr(err[0], "get_json") else {}
        print("  ✗ 应用文-%s %s：%s" % (kind, date, body.get("error", err)))
        return False
    r = con.execute("SELECT title,topic,words FROM daily_essays WHERE id=?", (eid,)).fetchone()
    print("  ✓ 应用文-%s %s《%s》%s %d 字 · %.0fs"
          % (kind, date, r["title"], r["topic"] or "", r["words"], time.time() - t0))
    return True


def align_all(con):
    """存量议论文的「提纲 ↔ 正文」对一遍。

    先用字面筛一道（survey 不调 AI）：段首已经原样是提纲那句的直接跳过，
    只有真对不上的才值得花一次 AI。落库走 _align_one —— 和界面上那个「对齐提纲」
    按钮共用一份实现，不然两边迟早各写各的（用不用重核 used、字数怎么算就已经会分叉）。"""
    todo = []
    for r in con.execute("SELECT * FROM daily_essays WHERE mode IN ('daily','compose') "
                         "ORDER BY date DESC"):
        e = _e_row(r)
        if any(not x["exact"] and x["para"] is not None
               for x in survey(e["content"], e["outline"])):
            todo.append((e["id"], e["date"][:10], e["title"]))
    if not todo:
        print("所有文章的提纲和正文都对得上")
        return
    print("要对 %d 篇：" % len(todo))
    ok = 0
    for i, (eid, date, title) in enumerate(todo, 1):
        with app.app_context():
            rep, err = _align_one(con, eid)
        if err:
            body = err[0].get_json() if hasattr(err[0], "get_json") else {}
            print("  [%d/%d] ✗ %s《%s》%s" % (i, len(todo), date, title, body.get("error", err)))
            continue
        ok += 1
        print("  [%d/%d] %s《%s》%s" % (i, len(todo), date, title,
                                        "；".join(rep["log"]) or "本来就对得上"))
    print("完成 %d/%d" % (ok, len(todo)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--compose", action="store_true", help="今天的综合应用范文（议论文）")
    p.add_argument("--daily", nargs="?", const="", metavar="日期", help="按素材日期成文（议论文）")
    p.add_argument("--backfill", action="store_true", help="补齐所有还没写的日期（议论文）")
    p.add_argument("--yy-daily", nargs="?", const="", metavar="日期", help="每日应用文")
    p.add_argument("--yy-compose", action="store_true", help="今天的综合应用能力大题")
    p.add_argument("--align-all", action="store_true", help="存量议论文的提纲↔正文全部对一遍")
    p.add_argument("--list", action="store_true")
    a = p.parse_args()
    con = _con()
    today = time.strftime("%Y-%m-%d")

    def day(v):
        """日期得当场校验。写歪一位（2026-7-3）不会报错，只会在 date 列里留一条
        谁也列不出来的孤儿记录 —— 界面按标准格式列最近 14 天，永远匹配不上它，
        你只会看到「这天没写」，再点一次又生成一条正常的。HTTP 路由早就校验了，命令行也得校验。"""
        v = (v or "").strip() or today
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            print("日期格式不对：%s（要 YYYY-MM-DD）" % v)
            sys.exit(2)
        return v

    if a.list:
        for r in con.execute("SELECT mode,date,title,words FROM daily_essays "
                             "ORDER BY mode, date DESC"):
            print("%-18s %s  %-24s %4d 字" % (r["mode"], r["date"][:10], r["title"], r["words"]))
        return

    if a.compose:
        gen(con, "compose", today)

    if a.daily is not None:
        gen(con, "daily", day(a.daily))

    # 应用文和议论文各跑各的：一个失败不该拖垮另一个（定时器一次把四篇都跑了）
    if a.yy_daily is not None:
        gen_yy(con, "daily", day(a.yy_daily))

    if a.yy_compose:
        gen_yy(con, "compose", today)

    if a.align_all:
        align_all(con)

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

    if not (a.compose or a.daily is not None or a.backfill or a.align_all
            or a.yy_daily is not None or a.yy_compose):
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
