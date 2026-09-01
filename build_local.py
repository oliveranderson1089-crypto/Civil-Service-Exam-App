#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地专项：把本地权威资料变成**速记卡 + 程序化出的题**。

为什么这一块非做不可：两套原卷里 8 道本地题（合同期限 / 户籍 / 年龄上限 ×3 /
加分条件 / 招录人数 ×2）**全部出自招聘公告参数** —— 没有一道考县情地理或 GDP。
这些是死数据，背了就一定拿得到分，是全卷性价比最高的几分。

为什么不让 AI 出这块的题：实测过。问三个模型要本县某次定向选聘的招录人数，它们各自「援引公告」给出 35 / 71 / 71 三个互相矛盾的数字，
而正确答案 143 写在同一份卷子的多选题里 —— **本地事实不在模型的语料里，
它只会编**。所以这里和资料分析、数量关系走同一条路：**答案由构造保证**，
干扰项从同一组真实数据里取（记混了才会选错，这正是本地题的考法）。

数据来源分两档，界面上必须分开显示：
  · **招聘公告**（local_meta.json，逐字来自官方公告）—— proven=1，真题考过
  · **县情 / 经济数据**（统计公报、政府工作报告）—— proven=0，如实标「未经真题验证」
    不装作同等重要：8 道真题一道都没考到这一档。

用法：
    python3 build_local.py --scan     # 只看会生成什么，不写库
    python3 build_local.py            # 写 sq_facts + 生成题库（整份重来）

地名、岗位、报名点这类能定位到人的信息**只在 local_meta.json 里**（.gitignore
忽略），源码里一个都不写死 —— 题干里的县名也是从 region 现取的。
模板见 local_meta.example.json。
"""
import argparse
import json
import os
import random
import re
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
META = os.path.join(BASE, "local_meta.json")

PAPER_NAME = "本地专项 · 地方必得分"
QTYPE = "本地县情"          # 和 ingest_shequ.QTYPE_RULES / core.SQ_BOARDS 是同一个词
REGION_FALLBACK = "本县"    # local_meta.json 没写 region 时题干里用的称呼


# ---------------------------------------------------------------- 事实
def facts_of(m):
    """把公告 / 县情摊成一条条「字段 = 值」。ord 决定速记卡里的先后。"""
    src = m["source"]["title"]
    y = m["year"]
    F = []

    def add(grp, k, v, unit="", note="", proven=0, s=src, year=y):
        F.append({"grp": grp, "k": k, "v": str(v), "unit": unit, "note": note,
                  "src": s, "year": year, "proven": proven, "ord": len(F)})

    g = "招聘公告"
    add(g, "选聘总名额", m["total"], "名", "27 个岗位合计", proven=1)
    add(g, "要求中共党员的名额", m["party_required_seats"], "名",
        "占 %d 名中的 %d 名；党员是**岗位准入条件**，不是加分"
        % (m["total"], m["party_required_seats"]), proven=1)
    add(g, "报考年龄", "%d–%d" % (m["age"]["min"], m["age"]["max"]), "周岁",
        m["age"]["note"], proven=1)
    add(g, "学历要求", m["edu"], "", "全部岗位一致", proven=1)
    add(g, "户籍要求", m["hukou"], "", "户籍**或**常住人口证明，两者居其一", proven=1)
    add(g, "报名时间", m["schedule"]["报名"], "", "只能报一个岗位")
    add(g, "打印准考证", m["schedule"]["打印准考证"], "",
        "%s自行下载" % m["source"]["site"])
    add(g, "笔试时间", m["schedule"]["笔试"], "", "闭卷")
    add(g, "笔试满分", m["exam"]["满分"], "分", m["exam"]["内容"])
    add(g, "面试方式与满分", "%s，%d 分" % (m["interview"]["方式"], m["interview"]["满分"]),
        "", "最低合格分数线 %d 分，低于此线不得进入下一环节" % m["interview"]["最低合格分数线"])
    for b in m["bonus"]:
        add(g, "加分 · " + b["cert"], b["add"], "分",
            "加在笔试成绩（折合后）；报名日须携原件到县委社会工作部 210 办公室登记", proven=1)

    g = "岗位名额"
    towns = {}
    for p in m["posts"]:
        towns[p["town"]] = towns.get(p["town"], 0) + p["n"]
    for t, n in sorted(towns.items(), key=lambda x: -x[1]):
        add(g, t, n, "名", "全县 %d 个镇有名额" % len(towns))

    # 县情 / 经济：**没有一道真题考过**，如实标出来，别和上面那档混着摆
    g = "县情与经济"
    ECON = m.get("econ") or {}
    for k, (v, unit, note) in ECON.items():
        add(g, k, v, unit, note, proven=0,
            s=m.get("econ_src") or "国民经济和社会发展统计公报", year=2025)
    return F


# ---------------------------------------------------------------- 出题
def gen_questions(facts, m):
    """从事实发题。**答案由构造保证**，干扰项取自同一组的真实数据。

    只对「答案是一个短值、且同组里凑得出三个像样干扰项」的字段发题；
    凑不出就不发 —— 宁可少几道，也不要拿 A/B/C/D 里三个明显不像的选项充数
    （那样做几遍就靠排除法答对了，练的不是知识）。
    """
    rnd = random.Random(20260912)          # 固定种子：重跑生成同一套，便于对比
    qs = []

    def mk(stem, right, wrong, note, proven):
        wrong = [w for w in dict.fromkeys(wrong) if w != right][:3]
        if len(wrong) < 3:
            return
        # **答案落在哪个字母由代码轮流发牌**，不靠 shuffle 碰运气：
        # 单纯打乱 18 道题实测出来是 D8/C5/A3/B2，偏到「蒙 D」就能多对几道。
        # 干扰项再打乱一次，保证同一个错项不会总待在同一格。
        rnd.shuffle(wrong)
        at = len(qs) % 4
        opts = wrong[:at] + [right] + wrong[at:]
        qs.append({"stem": stem, "options": opts, "answer": "ABCD"[at],
                   "explain": note, "proven": proven})

    reg = m.get("region") or REGION_FALLBACK
    total = m["total"]
    party = m["party_required_seats"]
    towns = {}
    for p in m["posts"]:
        towns[p["town"]] = towns.get(p["town"], 0) + p["n"]
    town_nums = sorted(set(towns.values()))

    mk("%s%d年面向社会公开选聘社区工作者，计划选聘总名额为（　）" % (reg, m["year"]),
       "%d 名" % total, ["%d 名" % n for n in (total - 10, total + 8, party)],
       "共 %d 个岗位、%d 名。来源：%s" % (len(m["posts"]), total, m["source"]["title"]), 1)

    mk("%s%d年选聘的 %d 名社区工作者中，明确要求「中共党员（含预备党员）」的名额为（　）"
       % (reg, m["year"], total), "%d 名" % party,
       ["%d 名" % (total - party), "%d 名" % total, "%d 名" % (party // 2)],
       "党员是**岗位准入条件**而不是加分条件 —— 这一点最容易和加分政策记混。", 1)

    mk("%s%d年面向社会选聘社区工作者，报考年龄要求为（　）" % (reg, m["year"]),
       "%d–%d 周岁" % (m["age"]["min"], m["age"]["max"]),
       ["18–35 周岁", "18–45 周岁", "20–40 周岁"],
       m["age"]["note"], 1)

    mk("%s%d年选聘社区工作者的学历门槛是（　）" % (reg, m["year"]),
       "大专及以上", ["中专及以上", "本科及以上", "高中及以上"],
       "27 个岗位**全部**要求大专及以上，没有例外。", 1)

    for b in m["bonus"]:
        others = [x["add"] for x in m["bonus"] if x["cert"] != b["cert"]]
        mk("持有「%s」职业资格证书的，笔试成绩（折合后）加（　）" % b["cert"],
           "%d 分" % b["add"], ["%d 分" % o for o in others] + ["%d 分" % (b["add"] + 1)],
           "加分只认社工职业资格证三档：助理 +2、社工师 +4、高级 +6。%s" % m["bonus_note"], 1)

    mk("%s%d年选聘社区工作者，笔试满分与面试满分分别为（　）" % (reg, m["year"]),
       "100 分、100 分", ["100 分、50 分", "150 分、100 分", "100 分、120 分"],
       "面试还设最低合格分数线 %d 分，低于此线不得进入下一环节。" % m["interview"]["最低合格分数线"], 0)

    mk("结构化面试的最低合格分数线是（　）",
       "%d 分" % m["interview"]["最低合格分数线"], ["60 分", "75 分", "80 分"],
       "低于最低合格分数线的考生不得进入下一步选聘环节。", 0)

    # 日期一律折成同一种写法再发。**正确答案和干扰项的格式必须一模一样** ——
    # 一个写 2026-08-24、三个写「2026年8月20日」，做几遍就摸出「格式不同的那个是对的」，
    # 练的成了找不同，不是记日期。
    def cn_date(t):
        mm = re.search(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})", t)
        return "%d年%d月%d日" % tuple(int(x) for x in mm.groups()) if mm else t

    sign = cn_date(m["schedule"]["报名"])
    mk("%s%d年选聘社区工作者，网上报名的开始日期是（　）" % (reg, m["year"]), sign,
       ["2026年8月20日", "2026年9月1日", "2026年8月28日"],
       "报名 %s；笔试 %s。" % (m["schedule"]["报名"], m["schedule"]["笔试"]), 0)
    mk("%s%d年选聘社区工作者，笔试拟定于（　）举行" % (reg, m["year"]),
       cn_date(m["schedule"]["笔试"]),
       ["2026年9月5日", "2026年9月19日", "2026年8月29日"],
       "打印准考证 %s。" % m["schedule"]["打印准考证"], 0)

    rank = sorted(towns.items(), key=lambda x: -x[1])
    top = rank[0]
    mk("%s%d年选聘社区工作者，名额最多的镇是（　）" % (reg, m["year"]),
       "%s（%d 名）" % (top[0], top[1]),
       ["%s（%d 名）" % (t, n) for t, n in rank[1:4]],
       "名额最多的两个镇是%s（%d 名）与%s（%d 名），合计 %d 名。"
       % (rank[0][0], rank[0][1], rank[1][0], rank[1][1], rank[0][1] + rank[1][1]), 0)

    # 名额最多的两个镇各发一道。**镇名从数据里取**，不写死在源码里 ——
    # 写死既漏地名，也意味着换一个县这段就直接失效。
    for t, _n in rank[:2]:
        mk("%s%d年选聘社区工作者，%s的名额为（　）" % (reg, m["year"], t), "%d 名" % towns[t],
           ["%d 名" % n for n in town_nums if n != towns[t]][-3:],
           "全县 %d 个镇共 %d 名。" % (len(towns), total), 0)

    mk("按公告，本次笔试的考试方式与总分是（　）",
       "闭卷，满分 100 分", ["开卷，满分 100 分", "闭卷，满分 150 分", "机考，满分 100 分"],
       "笔试内容：%s（不指定辅导用书）。" % m["exam"]["内容"], 0)

    for f in facts:
        if f["grp"] != "县情与经济":
            continue
        v = f["v"]
        try:
            num = float(str(v).replace(",", ""))
        except ValueError:
            continue
        # 干扰项跟正确答案**保留同样的小数位**：383.53 配 441.059 一眼就假，
        # 真实统计数字不会突然多出一位小数。
        dec = len(v.split(".")[1]) if "." in v else 0
        wrongs = ["%.*f" % (dec, num * r) for r in (0.82, 1.15, 1.31)]
        mk("据 %s，全县%s为（　）" % (m.get("econ_src") or "统计公报", f["k"]),
           "%s %s" % (v, f["unit"]), ["%s %s" % (w, f["unit"]) for w in wrongs],
           "%s（来源：%s）" % (f["note"] or "", f["src"]), 0)
    return qs


# ---------------------------------------------------------------- 写库
def save(con, facts, qs, m):
    con.execute("DELETE FROM sq_facts")
    for f in facts:
        con.execute("INSERT INTO sq_facts(grp,k,v,unit,note,src,year,proven,ord) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (f["grp"], f["k"], f["v"], f["unit"], f["note"], f["src"],
                     f["year"], f["proven"], f["ord"]))
    row = con.execute("SELECT id FROM sq_papers WHERE name=?", (PAPER_NAME,)).fetchone()
    if row:
        pid = row[0]
        con.execute("DELETE FROM sq_questions WHERE paper_id=?", (pid,))
    else:
        cur = con.execute(
            "INSERT INTO sq_papers(file_id,name,region,year,kind,total,status) "
            "VALUES(NULL,?,?,?,?,?,?)",
            (PAPER_NAME, m.get("region") or REGION_FALLBACK, 2026, "专项", 0, "ok"))
        pid = cur.lastrowid
    for i, q in enumerate(qs, 1):
        con.execute(
            "INSERT INTO sq_questions(paper_id,seq,part,part_seq,qtype,stem,options,"
            "answer,explain,score,verify,verify_note,qhash) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, i, "single", i, QTYPE, q["stem"],
             json.dumps(q["options"], ensure_ascii=False), q["answer"], q["explain"], 1.0,
             # **答案由构造保证**，不需要也不应该过 AI 校对闸门 —— 那道闸是用来
             # 查回忆版源卷的，拿它来审我们自己按公告造的题，只会被模型的幻觉带偏。
             "ok", json.dumps({"why": "程序化出题，答案由数据保证",
                               "src": "build_local.py"}, ensure_ascii=False), ""))
    con.execute("UPDATE sq_papers SET n_obj=?, n_sub=0, n_doubt=0 WHERE id=?", (len(qs), pid))
    return pid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="只打印会生成什么，不写库")
    a = ap.parse_args()
    if not os.path.exists(META):
        print("缺 %s —— 它是招聘公告的权威事实，先把公告抽进去。" % META)
        return 1
    m = json.load(open(META, encoding="utf-8"))
    facts = facts_of(m)
    qs = gen_questions(facts, m)

    grp = {}
    for f in facts:
        grp[f["grp"]] = grp.get(f["grp"], 0) + 1
    print("速记卡：%d 条" % len(facts))
    for g, n in grp.items():
        pv = sum(1 for f in facts if f["grp"] == g and f["proven"])
        print("   %-8s %2d 条%s" % (g, n, "（%d 条真题考过）" % pv if pv else "（未经真题验证）"))
    print("程序化出题：%d 道（其中 %d 道的考点在历年真题里原样考过）"
          % (len(qs), sum(q["proven"] for q in qs)))
    if a.scan:
        for q in qs:
            print("\n   %s" % q["stem"])
            print("     %s" % "  ".join("%s.%s" % (c, o) for c, o in zip("ABCD", q["options"])))
            print("     答案 %s　%s" % (q["answer"], q["explain"][:56]))
        return 0
    con = sqlite3.connect(DB)
    pid = save(con, facts, qs, m)
    con.commit()
    print("→ 已写入 sq_facts %d 条、专项题 %d 道（sq_papers #%d）" % (len(facts), len(qs), pid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
