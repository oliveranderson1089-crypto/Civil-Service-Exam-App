#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""专项练题库预热：把每个「板块 × 题型 × 难度」**还没被做过**的题补到目标数量。

水位按人算，不按库存：做题**不消耗库存**（题发出去既不删也不标记），
所以纯库存数一旦补满就永远是满的 —— 实际发生过：一格 30 道躺着，人早做掉 18 道，
这个脚本连着一周判「已经都满了，不用补」，而库里其实只剩 12 道新题。
补出来的是谁都没做过的新题，所以按「做过题的人里最少的那个」算就够了。

为什么必须有这个脚本：出题接口已经改成**只从库里取、绝不现场调 AI**（现场出题要几分钟，
用户看到的就是「点了没反应」）。代价是库空了就没题可发 —— 所以库得提前填满。

原先的空档正是踩坑现场：判断推理和言语理解的 AI 题型**只有 real 档有题**，
而前端默认难度是 mid，于是默认档位必然撞空库、必然卡住。表现出来就是「判断推理出不了题」。

只补 AI 引擎的题型：资料分析/数量关系/图形推理是程序化生成的，答案由构造保证，随时能出，
不需要也不应该进题库。

用法：
    python3 warm_drill_bank.py                    # 每格补到 30 道没做过的
    python3 warm_drill_bank.py --plan --ignore-seen   # 只看纯库存有多大（老口径）
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

from mods.drill import (DRILL_LEVELS, DRILL_TYPES, FRESH_DAYS,   # noqa: E402
                        _bank_fill, fresh_material_n)

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


def active_users(con):
    """做过 AI 题的人。

    补出来的是**谁都没做过**的新题，所以按「最惨的那个人」算就够了：
    把他补够，所有人自然都够。没人做过题（新库）就返回空 —— 那时按纯库存补，
    跟以前一样。
    """
    try:
        return [r[0] for r in con.execute("SELECT DISTINCT user_id FROM drill_seen")]
    except sqlite3.Error:
        return []           # drill_seen 还没建（旧库）：退回纯库存口径


def order_cells(con, short):
    """补库顺序：**今天有新知识点的格子先补**。

    一晚上的轮次和额度都有限，可能补不完所有缺口，那就先把今天学的变成题
    （出题原料本来也是取最近新学的，见 mods/drill.py 的 _material_mix —— 两头要同向，
    不然排在前面的格子拿到的还是三个月前的素材）。
    同等新鲜度下**缺得最多的先补**：那些才是最可能「点了出不了题」的。
    """
    return sorted(short, key=lambda x: (-fresh_material_n(con, x[0], x[1]), x[3]))


def usable(con, board, qtype, lv, users=()):
    """这一格还能发出多少道**新题** —— 这才是「够不够用」的真口径。

    两个筛子叠着：
      agree='1'   过了双模型核验的（存疑的不算，它们不会发给人做）
      没被做过     做题**不消耗库存**，所以纯库存数会一直是满的：
                  你那格 30 道做掉 18 道，库存还是 30，脚本永远判「不用补」，
                  而你实际只剩 12 道新题可做。库存满 ≠ 有题做，别拿它当水位。
    """
    sql = "SELECT COUNT(*) FROM drill_bank WHERE board=? AND qtype=? AND level=? AND agree='1'"
    n = con.execute(sql, (board, qtype, lv)).fetchone()[0]
    for u in users:
        n = min(n, con.execute(
            sql + " AND sig NOT IN (SELECT sig FROM drill_seen WHERE user_id=?)",
            (board, qtype, lv, u)).fetchone()[0])
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=30, help="每格补到多少道可用（默认 30）")
    ap.add_argument("--board", help="只补这个板块")
    ap.add_argument("--level", choices=DRILL_LEVELS, help="只补这个难度")
    ap.add_argument("--max-rounds", type=int, default=4,
                    help="单格最多补几轮 —— 有些题型 AI 就是出不好，核验一直过不了，"
                         "不设上限会在一个格子里空转烧钱（默认 4）")
    ap.add_argument("--plan", action="store_true", help="只报告缺口，不调 AI")
    ap.add_argument("--ignore-seen", action="store_true",
                    help="只看纯库存，不管谁做过（老口径，想单纯看库有多大时用）")
    a = ap.parse_args()

    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")

    # 按人算：补的是新题，所以看「最活跃的那个人还剩多少没做过的」，不是库有多大。
    # 库存口径下这个脚本从 7 月 28 日起再没补过一道题 —— 每格 30 道躺着，
    # 而人早就做掉了 18 道。夜里补好，白天点开就是新题，不用等即时补库那几分钟。
    users = [] if a.ignore_seen else active_users(con)
    cells = list(ai_cells(a.board, a.level))
    gaps = [(b, t, lv, usable(con, b, t, lv, users)) for b, t, lv in cells]
    short = order_cells(con, [(b, t, lv, n) for b, t, lv, n in gaps if n < a.target])

    print("目标每格 %d 道%s；共 %d 格，其中 %d 格不足。"
          % (a.target,
             "可用" if not users else "没做过的（按 %d 个做过题的人里最少的那个算）" % len(users),
             len(gaps), len(short)))
    if a.plan or not short:
        for b, t, lv, n in short:
            fr = fresh_material_n(con, b, t)
            print("  缺 %-8s %-12s %-5s 现有 %2d / %d%s"
                  % (b, t, lv, n, a.target,
                     "   ← 最近 %d 天新学 %d 条，先补它" % (FRESH_DAYS, fr) if fr else ""))
        if not short:
            print("已经都满了，不用补。")
        return

    t0 = time.time()
    filled = failed = 0
    for i, (b, t, lv, have) in enumerate(short, 1):
        rounds = 0
        while have < a.target and rounds < a.max_rounds:
            rounds += 1
            # ×4 且按 4 的倍数取，和 mods/drill.py 的 _bank_take 同一个口径：
            # 接了真题画像、护栏按真题 10% 分位收紧之后，一批要被刷掉一半以上
            # （实测词语辨析 10 道只留 2 道）。按老的 ×2、上限 12 补，一轮出 2~7 道，
            # max_rounds 用完还是填不满 target，夜间补库跑完题库依旧缺。
            # 取 4 的倍数是因为出题时正确答案的位置表按 want 均匀铺（见 _bank_fill），
            # 不是 4 的倍数就会有某个字母分得少。
            want = min(16, max(8, ((a.target - have) * 4 + 3) // 4 * 4))
            try:
                s = _bank_fill(con, b, t, lv, want=want)
            except Exception as e:
                print("  [%d/%d] %s·%s/%s 第 %d 轮出错：%s" % (i, len(short), b, t, lv, rounds, e))
                failed += 1
                break
            # ⚠️ 口径必须跟上面 short 那次一致。这里漏传 users 的话，补完一轮
            # 拿库存数一比就「够了」，循环当场退出 —— 缺口一道没补上，日志还写着补完了。
            have = usable(con, b, t, lv, users)
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
    rest = [(b, t, lv, usable(con, b, t, lv, users)) for b, t, lv in cells]
    still = [x for x in rest if x[3] < a.target]
    if still:
        print("仍不足 %d 道的格子（%d 个）：" % (a.target, len(still)))
        for b, t, lv, n in still:
            print("  %-8s %-12s %-5s %2d" % (b, t, lv, n))
    con.close()


if __name__ == "__main__":
    main()
