#!/usr/bin/env python3
"""真题题型标签的体检表 —— 「以真题为基准出题」这套机制到底吃到了多少干净数据。

为什么需要它：drill.py 的 _real_examples / _real_style 是**按题型**去真题库捞范例的，
而真题的题型标签有两个来源 —— real_questions.qtype（解析器按规则判的）和
real_explains.qtype（AI 顺手判的兜底）。后者**不受模块约束**，实测把
「2012—2020年，中国IC封装市场规模同比增量最大的年份是：」判成了「语境分析」。
于是出选词填空题时，喂给模型的「真题范例」里混着资料分析的题。

这种脏数据不会报错、不会崩，只会让出的题一点点跑偏，肉眼根本看不出来。
所以必须有个能反复跑的数字：**模块相符率** —— 按题型捞出来的真题里，
有多少道的模块和这个题型该属于的模块对得上。

用法：
    python3 audit_qtype.py              # 打体检表
    python3 audit_qtype.py --check 95   # 相符率低于 95% 就退出码 1（给 CI / 改完自查用）
    python3 audit_qtype.py --board 言语理解与表达
"""
import argparse
import sqlite3
import sys

from core import DB
from mods import realref
from mods.drill import DRILL_TYPES

# 口径一律从 mods/realref.py 取，别在这儿另立一套 —— 审计脚本存在的全部意义
# 就是当那个唯一可信的数字，它自己和线上跑的判定不一致就彻底没用了
SERVABLE = realref.servable("rq", "re")
_JOIN = "FROM real_questions rq LEFT JOIN real_explains re ON re.qid=rq.id"
_QTYPE = realref.qtype_expr("rq", "re")


def audit(con, only_board=""):
    """返回 [(板块, 题型, 现在捞到几道, 其中模块相符几道, 相符的里面有几道是 rq.qtype 判的)]

    一条 GROUP BY 统计完再在内存里配 —— 原先每个题型各跑一次全表 JOIN，
    28 个题型就是 28 遍 7606 行的扫描。这脚本是要进「改完自查」循环的，跑得慢就会被跳过。
    """
    stat = {}
    for r in con.execute(
            "SELECT COALESCE(rq.module,'') m, %s t, COUNT(*) n, "
            "  SUM(CASE WHEN COALESCE(rq.qtype,'')<>'' THEN 1 ELSE 0 END) byrule "
            "%s WHERE %s AND %s<>'' GROUP BY 1, 2" % (_QTYPE, _JOIN, SERVABLE, _QTYPE)):
        stat[(r["m"], r["t"])] = (r["n"], r["byrule"])

    rows = []
    for board, types in DRILL_TYPES.items():
        if only_board and board != only_board:
            continue
        module = realref.board_module(board)
        for qtype, _desc, engine in types:
            if engine != "ai":           # 程序化出的题不看真题范例，不在这套机制里
                continue
            # 「捞到」= 不卡模块时按题型能命中的全部（含别的模块的），「相符」= 只算本模块的
            got = sum(n for (m, t), (n, _b) in stat.items() if t == qtype)
            fit, byrule = stat.get((module, qtype), (0, 0))
            rows.append((board, qtype, got, fit, byrule))
    return rows


def unlabeled(con):
    """各模块还有多少道题的 rq.qtype 是空的 —— 这就是 P1「补题型」的工作量。"""
    return con.execute(
        "SELECT COALESCE(NULLIF(rq.module,''),'(无模块)') m, COUNT(*) n, "
        "  SUM(CASE WHEN rq.qtype='' THEN 1 ELSE 0 END) blank, "
        "  SUM(CASE WHEN rq.qtype='' AND COALESCE(re.qtype,'')<>'' THEN 1 ELSE 0 END) byai "
        "%s WHERE %s GROUP BY 1 ORDER BY 2 DESC" % (_JOIN, SERVABLE)).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", type=float, metavar="PCT",
                    help="总体模块相符率低于这个百分比就退出码 1")
    ap.add_argument("--board", default="", help="只看这一个板块")
    ap.add_argument("--db", default=DB)
    a = ap.parse_args()

    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    rows = audit(con, a.board)
    if not rows:
        # 板块名拼错时**必须在这儿死掉**：再往下走 tot 会是 0，pct 算出 0.0，
        # --check 于是报「相符率 0%」的红灯 —— 把「传参写错」伪装成「数据烂透了」
        print("--board %r 没匹配到任何 AI 出题的板块，可选：%s"
              % (a.board, "、".join(DRILL_TYPES)), file=sys.stderr)
        return 2

    print("=" * 78)
    print("真题范例的模块相符率（按题型捞出来的真题，有几道真是这个模块的）")
    print("=" * 78)
    print("%-14s%-12s%8s%8s%8s  %s" % ("板块", "题型", "捞到", "相符", "污染率", "备注"))
    tot = fit_tot = 0
    thin = []
    for board, qtype, n, fit, byrule in rows:
        tot += n
        fit_tot += fit
        note = []
        if fit < realref.STYLE_MIN:
            # 样本不足 _real_style 会返回 None：不卡篇幅了。这不是 bug，是它该有的保守行为，
            # 但要说出来 —— 这些题型的「像不像真题」目前完全没人管
            note.append("样本不足→不卡篇幅")
            thin.append("%s·%s(%d)" % (board, qtype, fit))
        if fit == 0:
            note.append("**一道范例都没有**")
        if n:
            note.append("规则判的 %d/%d" % (byrule, fit))
        print("%-14s%-12s%8d%8d%7.0f%%  %s"
              % (board, qtype, n, fit, (1 - fit / n) * 100 if n else 0, "，".join(note)))
    print("-" * 78)
    pct = fit_tot / tot * 100 if tot else 0
    print("合计：捞到 %d 道，模块相符 %d 道，**相符率 %.1f%%**（污染 %.1f%%）"
          % (tot, fit_tot, pct, 100 - pct))
    if thin:
        print("样本不足 %d 道的题型共 %d 个：%s" % (realref.STYLE_MIN, len(thin), "、".join(thin)))

    print()
    print("=" * 78)
    print("还没打题型标签的真题（P1 的工作量）")
    print("=" * 78)
    print("%-14s%8s%8s%8s" % ("模块", "可发", "qtype空", "靠AI兜底"))
    for r in unlabeled(con):
        print("%-14s%8d%8d%8d" % (r["m"], r["n"], r["blank"], r["byai"]))

    con.close()
    if a.check is not None and pct < a.check:
        print("\n✗ 相符率 %.1f%% 低于要求的 %.1f%%" % (pct, a.check), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
