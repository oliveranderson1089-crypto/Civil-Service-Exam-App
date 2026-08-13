#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日古诗文预热：把今天（和往后几天）的「申论运用 / 常识考点」两行注解提前生成好。

为什么要有这个脚本：这两行注解要调一次 AI，实测 3.7 秒。它原先是写在
/api/classics/daily 里现场调的 —— 而那个接口挂的是首屏「今日」卡片，
于是每天第一个打开 App 的人，要盯着 3.7 秒的空白才看到内容（之后全天 11 毫秒，
因为落库了）。跟专项练题库一样的处理：**接口只读库，库由这个脚本提前填**
（见 warm_drill_bank.py 开头那段）。

默认多备 2 天：定时器某天没跑成、或 AI 那天抽风，还有存货顶着，
不至于立刻退回「没有注解」。注解缺了不算故障，前端本来就是条件渲染，
少两行不影响读诗 —— 但能备着就备着。

用法：
    python3 warm_classic_daily.py              # 补今天 + 往后 2 天
    python3 warm_classic_daily.py --days 5     # 多备几天
    python3 warm_classic_daily.py --plan       # 只看缺哪几天，不调 AI
    python3 warm_classic_daily.py --force      # 已有注解也重新生成
"""
import argparse
import os
import sqlite3
import sys
from datetime import date, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from mods.classics import (_ensure_classic_freq, fill_daily_note,   # noqa: E402
                           pick_daily)

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3,
                    help="从今天起备几天（默认 3 = 今天 + 往后 2 天）")
    ap.add_argument("--plan", action="store_true", help="只报告缺哪几天，不调 AI")
    ap.add_argument("--force", action="store_true", help="已有注解也重新生成")
    a = ap.parse_args()

    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    _ensure_classic_freq(con)

    ok = skipped = failed = 0
    for i in range(max(1, a.days)):
        day = (date.today() + timedelta(days=i)).strftime("%Y-%m-%d")
        row = pick_daily(con, day)
        if not row:
            print("%s  ✗ 古诗文库是空的，没得选" % day)
            failed += 1
            continue
        title = "《%s》%s·%s" % (row["title"], row["dynasty"] or "", row["author"] or "")
        has = bool(row["apply"] and row["common"])
        if has and not a.force:
            print("%s  – %s 已有注解" % (day, title))
            skipped += 1
            continue
        if a.plan:
            print("%s  ? %s 待生成" % (day, title))
            continue
        if a.force:
            con.execute("UPDATE classic_daily SET apply='', common='' WHERE date=?", (day,))
            con.commit()
            row = pick_daily(con, day)
        good, msg = fill_daily_note(con, row, day)
        print("%s  %s %s %s" % (day, "✓" if good else "✗", title, msg))
        ok += good
        failed += (not good)

    con.close()
    print("完成：生成 %d，跳过 %d，失败 %d" % (ok, skipped, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
