#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把规范表述灌进 yy_items 的「表述」类，**每条带真题实证**。

做法不是「让 AI 生成一批提法」，而是拿现有 16 条种子里的 89 个提法，
去 38 份真题参考答案里逐条核对**到底出不出现、出现几次**。

实测结果值得记在这儿：**89 条里只有 30 条在真题答案里出现过，59 条一次没有**。
没出现的正好是教科书式套话——「为深入贯彻…」「按照…部署」「健全…机制」
「压实…责任」「凝聚…合力」「现提出如下意见」。
这和「落款」那次是同一个模式：**种子数据反映的是公文教材的写法，
不是申论真题参考答案的写法**。

但**不删那 59 条**：38 份答案、1.7 万字是很小的语料，一条提法零出现不等于它错
（真出现率 5% 的提法，在 38 份里一次不出现的概率也有 14%）。
所以改成标注证据强度，让取用时**优先**用有实证的那些。

另外试过从真题答案里**统计挖掘新提法**（动词+公文抽象宾语的搭配），**失败了**：
挖出的高频项全是话题词（「生猪养殖管理」「凰河流域文化建设」「综合平台」），
最高频才 2/38。语料这么小，挖出来的必然被具体考题绑死。这条路记下来，别再试。

零 AI 调用。

用法：
    python3 build_yy_phrase.py --dry
    python3 build_yy_phrase.py
"""
import argparse
import os
import re
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))

from mods.gongwen import norm_part  # noqa: E402


def real_answers(con):
    """去重后的应用文真题参考答案 [(文种, 去空白正文)]。
    同一场考试的 .doc/.pdf 两版要去掉，否则出现次数翻倍。"""
    seen, out = set(), []
    for r in con.execute(
            "SELECT p.year, p.exam, COALESCE(p.kind,'') k, q.seq, q.doctype, q.answer "
            "FROM slreal_questions q JOIN slreal_papers p ON p.id=q.paper_id "
            "WHERE q.qkind='贯彻执行' AND q.answer!=''"):
        key = (r["year"], r["exam"], r["k"], r["seq"])
        if key in seen:
            continue
        seen.add(key)
        out.append((r["doctype"] or "", re.sub(r"\s", "", r["answer"] or "")))
    return out


def hits(phrase, answers):
    """这条提法在几份真题答案里出现。「健全…机制」这种带省略号的，
    要求各段都出现才算（顺序不卡——真题里中间填的内容长短不一）。"""
    core = [x.strip() for x in phrase.split("…") if len(x.strip()) >= 2]
    if not core:
        return 0, []
    got = [dt for dt, a in answers if all(c in a for c in core)]
    return len(got), got


def run(con, dry=False):
    answers = real_answers(con)
    print("语料：%d 份真题参考答案 / %d 字" % (len(answers), sum(len(a) for _, a in answers)))
    rows = con.execute("SELECT scene, phrases, doctype, note, example "
                       "FROM gongwen_items ORDER BY id").fetchall()
    recs, n_real, n_seed = [], 0, 0
    for r in rows:
        part = norm_part(r["scene"])          # 「开头·缘由（依据）」→「开头·缘由」
        for ph in re.split(r"[、,，]", r["phrases"] or ""):
            ph = ph.strip()
            if len(ph.replace("…", "")) < 2:
                continue
            n, dts = hits(ph, answers)
            if n:
                n_real += 1
                note = ("**真题实证**：%d/%d 份参考答案里出现过%s"
                        % (n, len(answers),
                           "（%s）" % "、".join(sorted({d for d in dts if d})[:4]) if any(dts) else ""))
                src, ref = "real", "真题参考答案 ×%d" % n
            else:
                n_seed += 1
                note = ("未见于真题：%d 份参考答案里一次没出现。语料小，不代表它错，"
                        "但**优先用有实证的**" % len(answers))
                src, ref = "seed", "gongwen_items 种子"
            recs.append(dict(part=part, title=ph, scene=r["scene"], n=n,
                             note=note, src=src, ref=ref,
                             doctype=(r["doctype"] or "").strip()))
    print("提法 %d 条：真题实证 %d 条 · 仅种子 %d 条（%.0f%% 没在真题里出现过）"
          % (len(recs), n_real, n_seed, 100.0 * n_seed / max(1, len(recs))))
    top = sorted([x for x in recs if x["n"]], key=lambda x: -x["n"])[:10]
    print("\n== 真题实证最强的 ==")
    for x in top:
        print("  %-12s %-14s %d 份" % (x["part"], x["title"], x["n"]))
    if dry:
        print("\n（--dry，没写库）")
        return

    ins = upd = 0
    for x in recs:
        cur = con.execute(
            "INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,note,src,src_ref,freq) "
            "VALUES('表述','',?,?,?,?,?,?,?)",
            (x["part"], x["title"], x["title"], x["note"], x["src"], x["ref"], x["n"]))
        if cur.rowcount:
            ins += 1
        else:
            con.execute("UPDATE yy_items SET freq=?, note=?, src=?, src_ref=? "
                        "WHERE kind='表述' AND doctype='' AND part=? AND title=?",
                        (x["n"], x["note"], x["src"], x["ref"], x["part"], x["title"]))
            upd += 1
    con.commit()
    print("\n入库 %d 条，更新 %d 条" % (ins, upd))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    run(con, a.dry)


if __name__ == "__main__":
    main()
