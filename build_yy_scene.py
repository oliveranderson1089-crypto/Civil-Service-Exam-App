#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从真题题干里抽「发文情景」三要素，灌进 yy_items 的「情景」类。

为什么这批值钱：应用文出题的三件事是**就什么事发文 / 我是谁 / 写给谁**，
而现在 `write_gwspec` 是从新闻标题截 22 个字当发文场景、身份和对象直接退回 demo 默认值。
真题题干里这三样是**现成的**：
「假如你是花湖区政府办工作人员，A 市要召开打通基层法律服务"最后一公里"座谈会，
撰写一篇经验交流材料」——身份、场合、事由齐了，还自带该配哪个文种。

零 AI 调用，纯正则。

**抽不准的就留空**，不猜。情景是要喂进出题提示词的，猜错了等于给用户一个假题面；
留空的话调用方还能退回 demo，损失小得多。
"""
import argparse
import json
import os
import re
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))

# 我是谁。「假如你是X，」是最常见的写法；「以X的名义」是组织发文
_ROLE = [
    re.compile(r"(?:假如|如果|假设)你是([^，,。；]{2,26}?)[，,。；]"),
    re.compile(r"以\s*([^，,。；]{2,24}?)\s*的名义"),
    # 「请为X写」有歧义：「请为小赵写发言提纲」里小赵是身份，
    # 「请为该报撰写短评」里该报是刊发方（受文对象）。实测只有 1 道靠它才抽到身份，
    # 却会把「该报」这类误当成身份。所以收紧：只认**人称式短称呼**（小X／老X／X同志），
    # 机构名一律不认——宁可少抽一条，也不给用户一个假身份。
    re.compile(r"请为((?:小|老)[一-龥]{1,3}|[一-龥]{2,4}(?:同志|老师|书记|主任|经理))"
               r"(?:写|撰写|拟写)"),
]
# 写给谁 / 给谁看
_AUD = [
    re.compile(r"供([^，,。；]{1,14}?)(?:参阅|参考|阅示|使用)"),
    re.compile(r"(?:写给|致)([^，,。；]{2,20}?)(?:写|的|，|$)"),
    re.compile(r"给([^，,。；]{2,22}?)(?:写|撰写)(?:一[封份篇则])?"),
    re.compile(r"向([^，,。；]{2,18}?)(?:汇报|反馈|报告|介绍)"),
    re.compile(r"([^，,。；]{2,18}?)(?:准备|拟)?到[^，,。；]{2,12}?(?:学习|考察|参观)"),
    re.compile(r"面向([^，,。；]{2,18}?)(?:的|，|发布|宣传)"),
    re.compile(r"为([^，,。；]{2,16}?)(?:撰写|拟写)(?:一[封份篇则])?(?:回信|公开信|信)"),
]
# 什么场合 / 就什么事
_SCENE = [
    re.compile(r"(?:召开|举办|开展|举行)(?:一[场次])?([^，,。；]{4,30}?(?:座谈会|研讨会|推进会|"
               r"现场会|交流会|大会|会议|活动|评选|行动))"),
    re.compile(r"关于([^，,。；]{4,34}?)的(?:调研报告|建议|通知|方案|材料|提案|情况)"),
    re.compile(r"就([^，,。；]{4,30}?)(?:提出|撰写|拟写|写)"),
    re.compile(r"以[“\"]([^”\"]{4,30})[”\"]为(?:主题|题)"),
    re.compile(r"(?:针对|围绕)([^，,。；]{4,30}?)(?:，|撰写|拟写|提出|写)"),
    re.compile(r"([^，,。；]{4,26}?(?:工作|项目|改革|试点|行动|建设|治理|服务))"
               r"(?:的有关情况|情况|方面)"),
]
# 题干里的套话，抽 scene 时要避开
_BOILER = re.compile(r"给定资料|给定材料|定资料|定材料|不超过|分\s*[)）]|请根据|请你|作答|以下|如下")


def _first(pats, text):
    for p in pats:
        m = p.search(text)
        if m:
            got = re.sub(r"\s+", "", m.group(1)).strip("的了着，,。；;")
            if got and not _BOILER.search(got):
                return got
    return ""


def extract(stem):
    s = re.sub(r"\s+", "", stem or "")
    return {"role": _first(_ROLE, s), "audience": _first(_AUD, s),
            "scene": _first(_SCENE, s)}


def run(con, dry=False):
    seen, rows = set(), []
    for r in con.execute(
            "SELECT p.year, p.exam, COALESCE(p.kind,'') k, p.era, q.seq, q.doctype, "
            "q.family, q.stem, q.words, q.score "
            "FROM slreal_questions q JOIN slreal_papers p ON p.id=q.paper_id "
            "WHERE q.qkind='贯彻执行' AND q.stem!='' ORDER BY p.year DESC"):
        key = (r["year"], r["exam"], r["k"], r["seq"])
        if key in seen:
            continue
        seen.add(key)
        d = extract(r["stem"])
        d.update(year=r["year"], exam=r["exam"], kind=r["k"], era=r["era"],
                 seq=r["seq"], doctype=r["doctype"] or "", family=r["family"] or "",
                 words=r["words"], score=r["score"])
        rows.append(d)

    n = len(rows)
    got3 = [x for x in rows if x["role"] and x["scene"]]
    print("去重后 %d 道应用文真题" % n)
    for f in ("role", "audience", "scene"):
        c = sum(1 for x in rows if x[f])
        print("  %-9s 抽到 %2d/%d = %.0f%%" % (f, c, n, 100.0 * c / n))
    print("  身份+事由都有的：%d 道（这些才够当完整题面用）" % len(got3))

    print("\n== 抽出来的样例 ==")
    for x in [y for y in rows if y["role"] and y["scene"]][:6]:
        print("  [%s %s] %s" % (x["year"], x["doctype"], x["scene"]))
        print("      我是：%s ／ 写给：%s" % (x["role"], x["audience"] or "（未写明）"))
    bad = [x for x in rows if not x["role"] and not x["scene"]]
    if bad:
        print("\n== 三要素一个都没抽到的 %d 道（留空，不猜） ==" % len(bad))
        for x in bad[:4]:
            print("  %s %s Q%s" % (x["year"], x["doctype"] or "?", x["seq"]))

    if dry:
        print("\n（--dry，没写库）")
        return

    ins = upd = 0
    for x in rows:
        if not (x["role"] or x["scene"]):
            continue                       # 空的不入库，占位没意义
        title = "%s%s·%s" % (x["year"], x["exam"], x["doctype"] or "应用文")
        payload = {"scene": x["scene"], "role": x["role"], "audience": x["audience"],
                   "doctype": x["doctype"], "words": x["words"], "score": x["score"]}
        note = ("真题原题的发文情景（%s%s%s Q%s）。适配文种：%s"
                % (x["year"], x["exam"], x["kind"], x["seq"], x["doctype"] or "未标注"))
        cur = con.execute(
            "INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,note,src,src_ref,freq) "
            "VALUES('情景',?,'',?,?,?,'real',?,?)",
            (x["doctype"], title, json.dumps(payload, ensure_ascii=False), note,
             "%s%s Q%s" % (x["year"], x["exam"], x["seq"]),
             2 if x["era"] == "new" else 1))       # 2018+ 的排前面
        if cur.rowcount:
            ins += 1
        else:
            upd += 1
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
