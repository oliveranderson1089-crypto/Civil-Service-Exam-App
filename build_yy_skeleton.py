#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「骨架」类素材：每个文种由哪几块组成、哪块必需。零 AI 调用。

**不造新数据**——每个文种的 `parts`（哪几块、哪些必需）本来就定在
`mods/gongwen.GW_DOCTYPES` 里，只是活在代码里没进库。这里把它落成条目，
让素材库页能显示、AI 工具能查、和其他七类摆在同一个索引下。

**证据强度必须跟着一起落库**。20 个文种里只有 8 个的部件清单有真题参考答案支撑
（`parts_src='real'`，n≥3），其余 12 个是先验设定。设计文档里反复强调的一条：
拿先验当标准答案教给用户，是这个方案里最不能做的事。所以：
  · 真题实证的标 src='real'
  · 先验设定的标 src='seed'，note 里写明「样本还不够，仅供参考」

每个文种落两种条目：
  · 一条 part='' 的**总骨架**（fmt 那句人话 + 字数区间 + 真题频次）
  · 每个部件一条，标必需/可选

用法：
    python3 build_yy_skeleton.py --dry
    python3 build_yy_skeleton.py
"""
import argparse
import os
import sqlite3
import sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))

from mods.gongwen import GW_DOCTYPES, parts_of  # noqa: E402

# 各部件该放什么。写在这儿是因为它是**跨文种通用**的常识（「标题」就是点明发文事由），
# 和「这个文种要不要这一块」是两件事——后者才需要真题实证。
PART_HINT = {
    "标题": "点明发文事由和文种，单独一行居中，不写「标题：」这种标签",
    "主送机关": "收文的机关名，顶格写、冒号结尾",
    "称谓": "写给谁看，顶格写、冒号结尾；面向群众用「尊敬的…」「广大…」",
    "开头·缘由": "为什么发这个文——背景、依据、问题",
    "开头·目的": "想达到什么效果",
    "开头·概述": "一句话把整件事说清楚：什么时间、谁、做了什么、结果如何",
    "开头·点题": "开门见山亮出观点或主题",
    "开头·导语": "新闻稿专用：何时·何地·何事·何果，一段话交代完",
    "主体·举措": "做法分条写，每条先亮做法再讲怎么落地，用「一、二、三、」规范序号",
    "主体·成效": "做出来的结果，能给数据给数据",
    "主体·问题": "存在的短板，要具体、不空泛",
    "主体·建议": "针对问题提对策，要可落地",
    "主体·背景": "事情的来龙去脉",
    "主体·启示": "别人能学走的经验",
    "主体·目标": "要达到什么标准",
    "主体·保障": "组织领导、责任分工、督导考核",
    "主体·内容介绍": "把对象说清楚：是什么、怎么运行",
    "主体·评价意义": "为什么值得关注",
    "主体·析原因": "为什么会这样",
    "主体·提办法": "该怎么办",
    "主体·引出事项": "承上启下，「现将有关事项通知如下」",
    "主体·下一步": "接下来打算怎么做",
    "结尾·号召": "面向群众发出倡议，靠感染力不靠命令",
    "结尾·要求": "下行文提要求，「请遵照执行」这类只能对下级说",
    "结尾·收束": "收个尾，「特此报告」「以上意见妥否，请批示」",
    "结尾·引导阅读": "编者按专用：引出下文，让人接着读",
    "结尾·展望": "对未来的期待",
    "落款": "署名机关单独一行、日期再单独一行，放全文最后；单位用「××」代替",
}


def run(con, dry=False):
    recs = []
    for g in GW_DOCTYPES:
        real = g.get("parts_src") == "real"
        src = "real" if real else "seed"
        evi = ("**真题实证**：这个文种的部件清单有真题参考答案支撑"
               if real else
               "先验设定：真题样本还不够（n<3），仅供参考，别当标准答案")
        ps = parts_of(g["k"])
        # 总骨架
        recs.append(dict(
            doctype=g["k"], part="", title="%s的格式骨架" % g["k"],
            text=g["fmt"],
            note="%s｜字数 %d~%d 字｜%s｜%s" % (
                g["d"], g["min"], g["max"],
                ("真题考过 %d 次" % g["freq"]) if g.get("freq")
                else ("2018 后未考，更早 %d 次" % g.get("freq_all", 0))
                if g.get("freq_all") else "近五年未考",
                evi),
            src=src, freq=g.get("freq", 0) * 10 + 5))     # 总骨架排在部件前面
        for p, req in ps:
            recs.append(dict(
                doctype=g["k"], part=p,
                title="%s·%s（%s）" % (g["k"], p, "必需" if req else "可选"),
                text=PART_HINT.get(p, PART_HINT.get(p.split("·")[0], "")),
                note="%s｜%s" % ("**必需部件**，缺整块要扣格式分" if req
                                else "可选部件，视题目要求", evi),
                src=src, freq=g.get("freq", 0) * 10 + (1 if req else 0)))

    n_real = sum(1 for x in recs if x["src"] == "real")
    print("骨架 %d 条（%d 个文种）：真题实证 %d 条 · 先验设定 %d 条"
          % (len(recs), len(GW_DOCTYPES), n_real, len(recs) - n_real))
    print("  没有部件说明的：%s"
          % (", ".join(sorted({x["part"] for x in recs if x["part"] and not x["text"]}))
             or "无"))
    print("\n== 样例 ==")
    for x in [y for y in recs if y["doctype"] == "简报"][:4]:
        print("  [%s] %s" % (x["title"], x["text"][:44]))
    if dry:
        print("\n（--dry，没写库）")
        return

    ins = upd = 0
    for x in recs:
        cur = con.execute(
            "INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,note,src,src_ref,freq) "
            "VALUES('骨架',?,?,?,?,?,?,'GW_DOCTYPES',?)",
            (x["doctype"], x["part"], x["title"], x["text"], x["note"], x["src"], x["freq"]))
        if cur.rowcount:
            ins += 1
        else:
            con.execute("UPDATE yy_items SET text=?, note=?, src=?, freq=? "
                        "WHERE kind='骨架' AND doctype=? AND part=? AND title=?",
                        (x["text"], x["note"], x["src"], x["freq"],
                         x["doctype"], x["part"], x["title"]))
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
