#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""专项练题库预热：把每个「板块 × 题型 × 难度」的可用题补到目标数量。

为什么必须有这个脚本：出题接口已经改成**只从库里取、绝不现场调 AI**（现场出题要几分钟，
用户看到的就是「点了没反应」）。代价是库空了就没题可发 —— 所以库得提前填满。

原先的空档正是踩坑现场：判断推理和言语理解的 AI 题型**只有 real 档有题**，
而前端默认难度是 mid，于是默认档位必然撞空库、必然卡住。表现出来就是「判断推理出不了题」。

只补 AI 引擎的题型：资料分析/数量关系/图形推理是程序化生成的，答案由构造保证，随时能出，
不需要也不应该进题库。

用法：
    python3 warm_drill_bank.py                    # 全部补到 30 道可用
    python3 warm_drill_bank.py --target 50
    python3 warm_drill_bank.py --board 判断推理 --level mid
    python3 warm_drill_bank.py --plan             # 只看差多少，不调 AI（先估成本）
"""
import argparse
import os
import sqlite3
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from mods.drill import DRILL_LEVELS, DRILL_TYPES, _bank_fill   # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))


def ai_cells(board=None, level=None):
    """所有需要预热的格子 = (板块, 题型, 难度)，只含 AI 引擎的题型。"""
    for b, types in DRILL_TYPES.items():
        if board and b != board:
            continue
        for t, _desc, eng in types:
            if eng != "ai":
                continue
            for lv in DRILL_LEVELS:
                if level and lv != level:
                    continue
                yield b, t, lv


def usable(con, board, qtype, lv):
    """这一格有多少道**过了双模型核验**的题（存疑的不算，它们不会发给人做）。"""
    return con.execute("SELECT COUNT(*) FROM drill_bank WHERE board=? AND qtype=? AND level=? "
                       "AND agree='1'", (board, qtype, lv)).fetchone()[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=30, help="每格补到多少道可用（默认 30）")
    ap.add_argument("--board", help="只补这个板块")
    ap.add_argument("--level", choices=DRILL_LEVELS, help="只补这个难度")
    ap.add_argument("--max-rounds", type=int, default=4,
                    help="单格最多补几轮 —— 有些题型 AI 就是出不好，核验一直过不了，"
                         "不设上限会在一个格子里空转烧钱（默认 4）")
    ap.add_argument("--plan", action="store_true", help="只报告缺口，不调 AI")
    a = ap.parse_args()

    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")

    cells = list(ai_cells(a.board, a.level))
    gaps = [(b, t, lv, usable(con, b, t, lv)) for b, t, lv in cells]
    short = [(b, t, lv, n) for b, t, lv, n in gaps if n < a.target]

    print("目标每格 %d 道可用；共 %d 格，其中 %d 格不足。" % (a.target, len(gaps), len(short)))
    if a.plan or not short:
        for b, t, lv, n in short:
            print("  缺 %-8s %-12s %-5s 现有 %2d / %d" % (b, t, lv, n, a.target))
        if not short:
            print("已经都满了，不用补。")
        return

    t0 = time.time()
    filled = failed = 0
    for i, (b, t, lv, have) in enumerate(short, 1):
        rounds = 0
        while have < a.target and rounds < a.max_rounds:
            rounds += 1
            want = min(12, max(6, (a.target - have) * 2))   # 核验会刷掉一部分，多出一些
            try:
                s = _bank_fill(con, b, t, lv, want=want)
            except Exception as e:
                print("  [%d/%d] %s·%s/%s 第 %d 轮出错：%s" % (i, len(short), b, t, lv, rounds, e))
                failed += 1
                break
            have = usable(con, b, t, lv)
            filled += s["ok"]
            print("  [%d/%d] %s·%s/%s 第 %d 轮 +%d → %d/%d（重复 %d、存疑 %d、不合格 %d、"
                  "体量不像真题 %d）"
                  % (i, len(short), b, t, lv, rounds, s["ok"], have, a.target,
                     s["dup"], s["flaw"], s["bad"], s.get("style", 0)))
            if s["ok"] == 0:
                # 一道都没进 —— 但原因不同，处置也不同，别混为一谈
                if s["dup"] >= max(1, s["dup"] + s["flaw"] + s["bad"] + s.get("style", 0)) * 0.8:
                    print("       ↑ 几乎全是重复题：模型收敛到那几道经典题了。"
                          "已把已有题干喂进提示词避重，再来一轮试试")
                    continue          # 值得再试：下一轮的避重清单更长了
                print("       ↑ 这轮颗粒无收，跳过这一格（题型/难度组合可能超出模型能力）")
                break
    print("\n完成：新增 %d 道可用，%d 格出错，耗时 %.1f 分钟。" % (filled, failed, (time.time() - t0) / 60))

    # 收尾报告：还剩哪些格子没填满 —— 这些就是「点了出不了题」的候选，得盯着
    rest = [(b, t, lv, usable(con, b, t, lv)) for b, t, lv in cells]
    still = [x for x in rest if x[3] < a.target]
    if still:
        print("仍不足 %d 道的格子（%d 个）：" % (a.target, len(still)))
        for b, t, lv, n in still:
            print("  %-8s %-12s %-5s %2d" % (b, t, lv, n))
    con.close()


if __name__ == "__main__":
    main()
