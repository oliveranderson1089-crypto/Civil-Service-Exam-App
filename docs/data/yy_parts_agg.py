"""P0：从 63 篇自产应用文的逐段批注里，聚合出**真实的结构部件分布**（只读库，不改数据）。

为什么不直接手写一张 GW_PARTS 表：手写的是"我以为公文由哪几块组成"，
这里聚合的是"模型在 63 篇里实际标出了哪几块、每个文种实际用了哪几块"。
后者才是校准部件清单的依据——顺带能看出哪些部件名是同一个东西的变体。

`daily_essays.outline` 对应用文存的就是 segs（结构化逐段批注），
议论文那边存的是提纲字符串数组，所以只取 mode LIKE 'yingyong%'。

用法：
    python3 docs/data/yy_parts_agg.py            # 出报告
    python3 docs/data/yy_parts_agg.py --csv      # 另落一份「文种×部件」矩阵 CSV
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(os.path.dirname(HERE))
DB = os.path.join(APP, "app.db")

# 真题实测的文种族频次（来自 docs/data/yy-真题标注.tsv，见设计文档 3.2）。
# 放在这儿是为了让报告直接回答「练的和考的对不对得上」——不用再去翻另一张表。
REAL_FREQ = {"交流材料": 6, "汇报": 5, "简报": 4, "宣传": 4, "推荐/参评": 4, "短评": 3,
             "调研报告": 2, "编者按": 2, "方案": 2, "公开信": 1, "介绍": 1, "建议": 1,
             "提案": 1, "指南": 1, "谈话": 1}
# 现有 14 文种 → 真题文种族。没对上的写 ''，就是"练了但真题里没这一族"
DT2FAM = {"讲话稿": "", "宣传稿": "宣传", "公开信": "公开信", "新闻稿": "", "倡议书": "",
          "汇报": "汇报", "调研报告": "调研报告", "简报": "简报", "案例介绍": "推荐/参评",
          "编者按": "编者按", "方案": "方案", "建议书": "建议", "通知": "", "短评": "短评"}


# 归一化用**生产代码里的那一份**（mods/gongwen.norm_part），不在这儿再写一遍——
# 第一版这里有个"保守版"，和生产版两套实现，改一边忘一边就会让报告和线上说法不一致。
# 脚本先按 raw（只去空白）统计一遍，再按 norm 统计一遍，两栏对照才看得出归一化收了多少。
sys.path.insert(0, APP)
os.environ.setdefault("GONGKAO_DB", DB)
from mods.gongwen import norm_part as _norm  # noqa: E402


def raw_part(p):
    """只做无损清洗，用来统计"归一化之前有多少种名字"。"""
    p = re.sub(r"\s+", "", p or "")
    p = re.sub(r"[（(].*?[)）]", "", p)          # 「落款（署名+日期）」→「落款」
    return p.replace("・", "·").replace("/", "·").replace("-", "·").strip("·")


def norm_part(p):
    return _norm(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT id, mode, topic, spec, outline, content, words "
                       "FROM daily_essays WHERE mode LIKE 'yingyong%' ORDER BY id").fetchall()

    essays = []
    for r in rows:
        try:
            spec = json.loads(r["spec"] or "{}")
        except Exception:
            spec = {}
        try:
            segs = json.loads(r["outline"] or "[]")
        except Exception:
            segs = []
        dt = spec.get("doctype") or r["topic"] or ""
        raws = [raw_part(s.get("part")) for s in segs if isinstance(s, dict)]
        essays.append(dict(id=r["id"], mode=r["mode"], doctype=dt,
                           form=spec.get("form") or "full", words=r["words"] or 0,
                           content=r["content"] or "",
                           raws=[x for x in raws if x],
                           parts=[y for x in raws for y in _norm(x, split=True)],
                           nseg=len(segs)))

    print("== 样本 ==")
    print("  篇数 %d；按 mode：%s" % (len(essays), "、".join(
        "%s×%d" % kv for kv in Counter(e["mode"] for e in essays).most_common())))
    print("  按 form：%s" % "、".join(
        "%s×%d" % kv for kv in Counter(e["form"] for e in essays).most_common()))
    noseg = [e for e in essays if not e["parts"]]
    if noseg:
        print("  ⚠️ 有 %d 篇一条批注都没有（生成时被「text 必须命中正文」那道闸全滤掉了）："
              % len(noseg))
        for e in noseg:
            print("     id=%d %s/%s" % (e["id"], e["doctype"], e["form"]))

    # ---- 归一化前后对照：这是 P0b 那套词表到底管不管用的唯一证据 ----
    rc = Counter(p for e in essays for p in e["raws"])
    pc = Counter(p for e in essays for p in e["parts"])
    print("\n== 归一化效果 ==")
    print("  归一化前：%3d 种名字 / %d 条批注" % (len(rc), sum(rc.values())))
    print("  归一化后：%3d 种名字 / %d 条（合成名拆成多条，所以条数会变多）"
          % (len(pc), sum(pc.values())))
    print("  收敛率：%.0f%%（%d → %d 种）"
          % (100.0 * (len(rc) - len(pc)) / max(1, len(rc)), len(rc), len(pc)))
    slot_only = [p for p in pc if "·" not in p and p not in ("标题", "称谓", "落款", "主送机关")]
    if slot_only:
        print("  ⚠️ 只落到槽位级（二级角色没认出来）：%s"
              % "、".join("%s(%d)" % (p, pc[p]) for p in sorted(slot_only, key=lambda x: -pc[x])))
        print("     占 %d/%d 条 = %.0f%%——这些是 GW_ROLES 词表还没覆盖的说法"
              % (sum(pc[p] for p in slot_only), sum(pc.values()),
                 100.0 * sum(pc[p] for p in slot_only) / max(1, sum(pc.values()))))

    print("\n== 部件名频次（归一化后，全样本）==")
    for p, n in pc.most_common():
        print("  %-14s %3d  （出现在 %d 篇）"
              % (p, n, sum(1 for e in essays if p in e["parts"])))

    # ---- 变体检测：前缀相同的部件名，很可能是同一块的不同叫法 ----
    fam = defaultdict(list)
    for p in pc:
        fam[p.split("·")[0]].append(p)
    multi = {k: v for k, v in fam.items() if len(v) > 1}
    if multi:
        print("\n== 疑似同一块的不同叫法（前缀相同，要不要并由人定）==")
        for k, v in sorted(multi.items(), key=lambda x: -sum(pc[p] for p in x[1])):
            print("  %s：%s" % (k, "、".join("%s(%d)" % (p, pc[p]) for p in sorted(v, key=lambda p: -pc[p]))))

    # ---- 文种 × 部件矩阵 + 必需/可选判定 ----
    by_dt = defaultdict(list)
    for e in essays:
        if e["form"] == "full":          # 只用成篇的定部件；提纲的块名是另一套
            by_dt[e["doctype"]].append(e)
    print("\n== 文种 × 部件（只看 form=full；出现率 = 出现篇数/该文种篇数）==")
    print("   ≥80% 记必需(1)，30~79% 记可选(0)，<30% 视作噪声不进清单")
    # 沿用「支撑不足就不给」：n<MIN_N 时出现率的**分辨率**就不够——n=3 只有 33/67/100 三档，
    # 30% 那条线永远筛不掉任何东西（实测：所有 3 篇的文种都是「噪声 0 个」，是假的干净）。
    # 这种文种一律标「样本不足」，不出必需/可选结论，等篇数补上来再判。
    print("   ⚠️ 少于 %d 篇的文种只列频次、**不出判定**（出现率分辨率不够）\n" % 5)
    MIN_N = 5
    matrix = []
    for dt in sorted(by_dt, key=lambda d: -len(by_dt[d])):
        es = by_dt[dt]
        cnt = Counter(p for e in es for p in set(e["parts"]))
        fam_name = DT2FAM.get(dt, "?")
        rf = REAL_FREQ.get(fam_name, 0) if fam_name else 0
        print("  【%s】%d 篇 · 真题族=%s(考%d次)%s"
              % (dt, len(es), fam_name or "（真题未考）", rf,
                 "  ⚠️ 样本不足" if len(es) < MIN_N else ""))
        for p, c in cnt.most_common():
            rate = 100.0 * c / len(es)
            if len(es) < MIN_N:
                tag = "样本不足"
            else:
                tag = "必需" if rate >= 80 else ("可选" if rate >= 30 else "噪声")
            print("      %-14s %3.0f%%  %s" % (p, rate, tag))
            matrix.append(dict(doctype=dt, n_essay=len(es), part=p, hits=c,
                               rate=round(rate), verdict=tag,
                               family=fam_name, real_freq=rf))

    # ---- 覆盖缺口：真题考了但一篇没练的族 ----
    practiced = {DT2FAM.get(dt) for dt in by_dt}
    print("\n== 覆盖缺口：真题考过、但 63 篇里一篇没练的文种族 ==")
    for f, n in sorted(REAL_FREQ.items(), key=lambda x: -x[1]):
        if f not in practiced:
            print("  %-10s 真题考 %d 次 · 已练 0 篇" % (f, n))

    # ---- 白捡的错例：正文里还留着「一是…二是」的（fix_fentiao 之前生成的存量） ----
    bad = [e for e in essays
           if "一是" in e["content"] and "二是" in e["content"]]
    print("\n== 白捡的错例候选（正文仍有「一是…二是…」串，是 fix_fentiao 上线前的存量）==")
    print("  %d/%d 篇；这些原句可直接进错例库（错句 + 规范序号改法 + 扣分理由）"
          % (len(bad), len(essays)))
    for e in bad[:8]:
        m = re.search(r"[^。；\n]{0,18}一是[^。；\n]{0,26}", e["content"])
        print("     id=%-4d %-8s %s" % (e["id"], e["doctype"], (m.group(0) if m else "")[:46]))
    if len(bad) > 8:
        print("     …… 另 %d 篇" % (len(bad) - 8))

    # ---- 批注密度：一篇标几块 ----
    ns = sorted(len(e["parts"]) for e in essays if e["parts"])
    if ns:
        print("\n== 批注密度 ==")
        print("  每篇标出的部件数：最小 %d 中位 %d 最大 %d" % (ns[0], ns[len(ns) // 2], ns[-1]))

    if args.csv:
        p = os.path.join(HERE, "yy-部件矩阵.csv")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(matrix[0]))
            w.writeheader()
            w.writerows(matrix)
        print("\n矩阵 → %s" % p)


if __name__ == "__main__":
    main()
