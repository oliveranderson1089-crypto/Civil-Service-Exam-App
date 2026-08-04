#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「得体」类素材：每个文种的称谓 / 落款 / 语气怎么写才合身份。零 AI 调用。

**能从真题范文里量出来的就量，量不出来的写种子并标清楚**——
这一类最容易变成「我以为公文该这么说」，所以证据强度必须写在每条上。

从 36 份真题参考答案里实测到的三件事：
  ① 各文种实际用的**称谓**（讲话稿「尊敬的各位来宾：」「各位领导、同志们：」，
     公开信「市民朋友们：」「广大市民：」，建议「尊敬的领导：」）
  ② 各文种实际用的**落款**（公开信「Ｇ市市场监管局」，建议「建议人：叶某某」）
  ③ **命令口气 0/36**——「请…遵照执行」「务必落实」「限期整改」这类下行文说法，
     36 份真题参考答案里一处都没出现

第 ③ 条只按「面向群众的文种」入库，不推广到通知等下行文：
通知在样本里只有 1 份，拿 1 份去断言「通知也不能用命令口气」是过度延伸。

用法：
    python3 build_yy_detide.py --dry
    python3 build_yy_detide.py
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))

from mods.yycheck import _CALL, _ORDER_CMD, _SIGN, _SOFT_DOCTYPES, lines  # noqa: E402

# 人工种子：真题样本覆盖不到的文种/维度。**必须标 src='seed'**，
# 界面和 AI 工具都要能看出「这条是先验设定，不是真题实证」。
SEED = [
    ("", "结尾·号召", "面向群众的文种靠感染力，不靠命令",
     "让我们携手…／欢迎广大市民…／期待您的参与",
     "请遵照执行／务必落实／限期整改",
     "倡议书、公开信、宣传稿这类是写给群众看的，用下行文的命令口气是语言不得体"),
    ("通知", "结尾·要求", "通知是下行文，可以提要求",
     "请各单位遵照执行／请于X月X日前将落实情况报送我办",
     "让我们携手共建（对下级说这话不合身份）",
     "上级发给下级，明确要求是本分；反过来用商量口气才是不得体"),
    ("汇报", "称谓", "向上行文的称谓要写受文机关",
     "市住建局：／尊敬的各位领导：",
     "同志们：（那是平级或对下的讲话用语）",
     "汇报是上行文，称谓指向的是收文的上级机关"),
    ("", "落款", "落款单位用「××」代替，不要编真单位名",
     "××市××局／××县人民政府",
     "编一个看起来像真的单位名",
     "考场上编真实单位名没有意义，规范做法是用××占位"),
]


def real_answers(con):
    out = []
    for r in con.execute("SELECT doctype, text FROM yy_items WHERE kind='范文'"):
        out.append((r["doctype"] or "", r["text"] or ""))
    return out


def mine(answers):
    """→ (称谓 by 文种, 落款 by 文种, 命令口气命中数)。"""
    calls, signs, n_cmd = defaultdict(list), defaultdict(list), 0
    for dt, txt in answers:
        ls = lines(txt)
        for ln in ls[:4]:
            s = re.sub(r"\s", "", ln)
            if _CALL.match(s) and s not in calls[dt]:
                calls[dt].append(s)
        for ln in ls[-3:]:
            s = re.sub(r"\s", "", ln)
            if _SIGN.search(s) and len(s) <= 20 and s not in signs[dt]:
                signs[dt].append(s)
        n_cmd += len(_ORDER_CMD.findall(txt))
    return calls, signs, n_cmd


def run(con, dry=False):
    answers = real_answers(con)
    calls, signs, n_cmd = mine(answers)
    recs = []
    for dt, v in calls.items():
        recs.append(dict(doctype=dt, part="称谓", title="%s的称谓怎么写" % dt,
                         do="／".join(v[:4]), dont="",
                         note="真题实证：%d 份 %s 参考答案里实际这么写" % (len(v), dt),
                         src="real", freq=len(v)))
    for dt, v in signs.items():
        recs.append(dict(doctype=dt, part="落款", title="%s的落款怎么写" % dt,
                         do="／".join(v[:4]), dont="",
                         note="真题实证：%d 份 %s 参考答案里实际这么写" % (len(v), dt),
                         src="real", freq=len(v)))
    # 命令口气：0/36 是**实证的否定证据**，比人工规则硬
    recs.append(dict(
        doctype="", part="结尾·号召", title="面向群众的文种别用命令口气",
        do="让我们携手…／欢迎广大市民…／期待您的参与",
        dont="请…遵照执行／务必落实／限期整改／一律严禁",
        note=("真题实证：%d 份参考答案里，下行文的命令式说法出现 **%d 次**。"
              "适用于%s；通知等下行文不在此列（样本只有 1 份，不做延伸）"
              % (len(answers), n_cmd, "、".join(sorted(_SOFT_DOCTYPES)))),
        src="real", freq=len(answers)))
    for dt, part, title, do, dont, note in SEED:
        recs.append(dict(doctype=dt, part=part, title=title, do=do, dont=dont,
                         note=note + "（**人工种子**，真题样本没覆盖到，仅供参考）",
                         src="seed", freq=0))

    n_real = sum(1 for x in recs if x["src"] == "real")
    print("得体 %d 条：真题实证 %d 条 · 人工种子 %d 条"
          % (len(recs), n_real, len(recs) - n_real))
    print("  命令口气在 %d 份真题参考答案里出现 %d 次" % (len(answers), n_cmd))
    print("\n== 样例 ==")
    for x in recs[:5]:
        print("  [%s|%s] %s" % (x["doctype"] or "通用", x["part"], x["title"]))
        print("      ✓ %s" % x["do"][:56])
        if x["dont"]:
            print("      ✗ %s" % x["dont"][:56])
    if dry:
        print("\n（--dry，没写库）")
        return

    ins = upd = 0
    for x in recs:
        cur = con.execute(
            "INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,note,src,src_ref,freq) "
            "VALUES('得体',?,?,?,?,?,?,?,?)",
            (x["doctype"], x["part"], x["title"],
             json.dumps({"do": x["do"], "dont": x["dont"]}, ensure_ascii=False),
             x["note"], x["src"],
             "36 份真题参考答案" if x["src"] == "real" else "人工种子", x["freq"]))
        ins += 1 if cur.rowcount else 0
        upd += 0 if cur.rowcount else 1
    con.commit()
    print("\n入库 %d 条，已存在 %d 条" % (ins, upd))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    run(con, a.dry)


if __name__ == "__main__":
    main()
