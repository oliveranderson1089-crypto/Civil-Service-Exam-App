"""人工归类：30 套申论真题里的应用文（贯彻执行）题。

键是 q.tsv 的行号（NR），逐道读题干判定，不靠关键词匹配——
「案例」「报告」这类词在题干里大量出现在非文种位置（"请结合案例…"），
关键词法实测 7 次误命中、10 余道漏判。
form: full=成篇 / outline=提纲（真题明确要「提纲」的）/ part=只写某几个部件
"""
import csv
import os
import sys
from collections import Counter, defaultdict

SCR = os.path.dirname(os.path.abspath(__file__))

# 行号: (归一化文种, 文种族, form, 备注)
YY = {
    3:   ("调研报告", "调研报告", "part", "只写「问题」和「建议」两个部件"),
    4:   ("简报", "简报", "full", "供领导参阅"),
    8:   ("短评", "短评", "full", "为省日报撰写，自拟题目"),
    11:  ("编者按", "编者按", "full", "为专题通讯写"),
    13:  ("经验交流材料", "交流材料", "full", "座谈会经验交流"),
    16:  ("交流发言", "交流材料", "full", "研讨会大会交流发言"),
    20:  ("宣传材料", "宣传", "full", "向参会企业和游客推介"),
    25:  ("编者按", "编者按", "full", "为简报写"),
    # 30 是**改判**的：初判归了「提出对策」，因为题干只说「提出工作建议」。
    # 但云盘里 2022 国考行政执法卷的参考答案，这道题的标题是
    # 《关于 J 市巩固税收服务成果的建议书》——有标题就是应用文，改回贯彻执行。
    # （是规则分类器和人工标注打架时，去翻参考答案裁出来的，见 ingest_shenlun.py --eval）
    30:  ("建议书", "建议", "full", "题干只说「撰写一份工作建议」，靠参考答案的标题裁定"),
    31:  ("经验交流材料", "交流材料", "outline", "明确要提纲"),
    32:  ("公开信", "公开信", "full", "以局的名义，回应社会关切；800-1000字"),
    34:  ("实施方案", "方案", "outline", "明确要提纲"),
    37:  ("整改方案", "方案", "outline", "明确要提纲"),
    41:  ("经验交流材料", "交流材料", "full", ""),
    44:  ("简报", "简报", "full", ""),
    45:  ("参评材料", "推荐/参评", "full", "典型案例评选参评"),
    48:  ("情况介绍", "介绍", "full", "对某模式作简要介绍"),
    49:  ("宣传稿", "宣传", "full", ""),
    53:  ("建议书", "建议", "full", "《关于加强…的建议》"),
    54:  ("汇报", "汇报", "full", "调研情况汇报"),
    57:  ("案例摘要", "推荐/参评", "full", "入选优秀案例"),
    59:  ("短评", "短评", "full", "以专栏编辑身份"),
    62:  ("座谈会发言", "交流材料", "full", "参会代表发言"),
    63:  ("汇报", "汇报", "outline", "明确要提纲"),
    64:  ("案例摘要", "推荐/参评", "full", "同 57（国考跨卷种共用材料）"),
    69:  ("交流发言", "交流材料", "full", "现场会交流发言"),
    72:  ("工作简报", "简报", "full", ""),
    78:  ("汇报", "汇报", "full", "调研情况汇报+改进建议"),
    82:  ("情况报告", "汇报", "full", "成效、不足和改进建议"),
    89:  ("工作简报", "简报", "full", "供领导参阅"),
    93:  ("调研报告", "调研报告", "outline", "明确要提纲"),
    101: ("展板文稿", "宣传", "full", "宣传介绍粮仓前世今生"),
    107: ("提案", "提案", "part", "只写「提案案由」和「具体建议」"),
    111: ("工作指南", "指南", "part", "只写「工作事项及相应工作内容」"),
    112: ("谈话提纲", "谈话", "outline", "当面谈话反馈的内容提纲"),
    116: ("短评", "短评", "full", "指定标题"),
    121: ("发布词", "宣传", "full", "呼吁公众报名参加"),
    126: ("执法情况汇报", "汇报", "outline", "明确要提纲"),
    127: ("推荐材料", "推荐/参评", "full", "先进集体评选推荐"),
}
# 边界带：有身份/有对象但**没指定文种**的对策题。不算贯彻执行，
# 但它们的「身份+对象」三元组同样能喂情景库，所以单独记一类。
ROLE_DUICE = {12, 40, 68, 88, 97}
# 大作文（文章论述）
ESSAY = {5, 9, 17, 22, 27, 35, 38, 42, 46, 50, 55, 60, 65, 70, 74, 79, 84, 90,
         94, 98, 103, 108, 113, 118, 123, 128}

rows = list(csv.reader(open(SCR + "/yy-真题切题.tsv", encoding="utf-8"), delimiter="\t"))
recs = []
for nr, r in enumerate(rows[1:], start=2):
    paper, seq, score, words, _kw, stem = r[0], int(r[1]), int(r[2]), int(r[3]), r[4], r[5]
    if nr in YY:
        dt, fam, form, note = YY[nr]
        kind = "贯彻执行"
    elif nr in ESSAY:
        dt, fam, form, note, kind = "", "", "", "", "文章论述"
    elif nr in ROLE_DUICE:
        dt, fam, form, note, kind = "", "", "", "有身份/对象", "提出对策·带身份"
    else:
        dt, fam, form, note, kind = "", "", "", "", "小题（概括/分析/对策）"
    recs.append(dict(nr=nr, paper=paper, seq=seq, score=score, words=words,
                     kind=kind, doctype=dt, family=fam, form=form, note=note, stem=stem))

with open(SCR + "/yy-真题标注.tsv", "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, delimiter="\t", fieldnames=list(recs[0]))
    w.writeheader()
    w.writerows(recs)

yy = [r for r in recs if r["kind"] == "贯彻执行"]
print("总题数 %d ／ 应用文 %d（%.0f%%）／ 大作文 %d ／ 带身份的对策题 %d ／ 其他小题 %d"
      % (len(recs), len(yy), 100.0 * len(yy) / len(recs), len(ESSAY), len(ROLE_DUICE),
         len(recs) - len(yy) - len(ESSAY) - len(ROLE_DUICE)))

print("\n== 文种族频次（30 套） ==")
for k, v in Counter(r["family"] for r in yy).most_common():
    dts = Counter(r["doctype"] for r in yy if r["family"] == k)
    print("%-10s %2d  ← %s" % (k, v, "、".join("%s×%d" % (a, b) for a, b in dts.most_common())))

print("\n== form ==")
for k, v in Counter(r["form"] for r in yy).most_common():
    print("%-8s %d" % (k, v))

print("\n== 字数分布 ==")
ws = sorted(r["words"] for r in yy if r["words"])
print("样本 %d  最小 %d  p25 %d  中位 %d  p75 %d  最大 %d"
      % (len(ws), ws[0], ws[len(ws) // 4], ws[len(ws) // 2], ws[len(ws) * 3 // 4], ws[-1]))
for k, v in sorted(Counter(ws).items()):
    print("  %4d 字 × %d" % (k, v))

print("\n== 分值 × 字数（题位画像） ==")
by = defaultdict(list)
for r in yy:
    if r["words"]:
        by[r["score"]].append(r["words"])
for s in sorted(by):
    v = sorted(by[s])
    print("  %2d 分  n=%-2d  字数 %s  中位 %d" % (s, len(v), "/".join(map(str, v)), v[len(v) // 2]))

print("\n== 题序位置 ==")
for k, v in sorted(Counter(r["seq"] for r in yy).items()):
    print("  第%d题 × %d" % (k, v))

print("\n== 每套应用文题数 ==")
per = Counter(r["paper"] for r in yy)
for k, v in sorted(Counter(per.get(p, 0) for p in set(r["paper"] for r in recs)).items()):
    print("  %d 道 × %d 套" % (k, v))
