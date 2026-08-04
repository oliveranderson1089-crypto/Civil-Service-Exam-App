"""P1：从**真题参考答案**里量出每个文种的格式骨架（只读库，不改数据）。

为什么必须用真题答案、不能用自产范文：P0 已经量过——63 篇自产应用文里
只有 2 个文种够样本量（倡议书 8 篇、建议书 5 篇），而这两个恰好是真题低频文种。
真题最高频的交流材料自产 0 篇。所以「每个文种由哪几块必需组成」只能靠真题答案定。

**能量什么、不能量什么，要分清**：
  · 能量（纯格式，正则可判）：标题 / 称谓 / 主送机关 / 落款 / 日期 / 分条方式
    —— 这几块正好是应用文最大的得分点，也是最容易整块丢分的地方
  · 不能量（语义，正则判不了）：主体下面是「举措」还是「成效」还是「问题」
    —— 这部分继续用 P0 那套（63 篇 segs 聚合 + AI 补 + 9 份带审题的解析校准）
不硬猜第二类，是因为猜错了会写进提示词、直接影响出稿。

去重很关键：同一场考试在云盘里常有 .doc/.pdf 两份，题面卷和答案卷又各一份，
不去重会把一个样本数成四个，"必需"的判定就虚高了。按 (年份, 考试, 卷种, 题号) 去重。

用法：
    python3 docs/data/yy_parts_from_real.py            # 出报告
    python3 docs/data/yy_parts_from_real.py --csv      # 另落 CSV
    python3 docs/data/yy_parts_from_real.py --era all  # 含 2000-2017 老卷（默认只看 2018+）
"""
import argparse
import csv
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(os.path.dirname(HERE))
DB = os.path.join(APP, "app.db")
sys.path.insert(0, APP)
os.environ.setdefault("GONGKAO_DB", DB)

MIN_N = 3          # 少于这么多份答案的文种不出判定（沿用「支撑不足就不给」）
REQ, OPT = 80, 30  # 出现率 ≥80% 记必需，30~79% 记可选，更低视作噪声


def lines(ans):
    return [x.strip() for x in re.split(r"[\n\r]+", ans or "") if x.strip()]


# ---- 各格式部件的判据。都只认**字面特征**，不猜语义 ----

def has_title(ans):
    """标题：开头有一行短句、不带句末标点、不是称谓。
    真题答案的标题多是「关于…的建议书」「致…的一封公开信」这种。"""
    for ln in lines(ans)[:2]:
        s = re.sub(r"\s", "", ln)
        if not (4 <= len(s) <= 34):
            continue
        if s.endswith(("：", ":", "。", "；", "!", "！", "?", "？")):
            continue
        if re.match(r"^[一二三四五六（(]", s):        # 分条项不是标题
            continue
        return True
    return False


_CALL = re.compile(r"^(尊敬的|各位|全体|亲爱的|同志们|市民朋友|广大|亲爱|"
                   r"[^\s，。]{0,10}(?:朋友们|同志|居民|市民|网友|读者|同学|家长))"
                   r"[^\n]{0,16}[：:]$")


def has_call(ans):
    """称谓：单独一行、以冒号结尾、指向人。"""
    return any(_CALL.match(re.sub(r"\s", "", ln)) for ln in lines(ans)[:4])


_TO = re.compile(r"^(各|全体|[^\s，。]{2,18}(?:局|厅|委|办|部|处|科|乡|镇|街道|"
                 r"县|市|区|政府|单位|公司|学校))[^\n]{0,12}[：:]$")


def has_to(ans):
    """主送机关：机关名 + 冒号（通知类才有）。和称谓的区别是指向单位不指向人。"""
    for ln in lines(ans)[:4]:
        s = re.sub(r"\s", "", ln)
        if _CALL.match(s):
            continue
        if _TO.match(s):
            return True
    return False


_SIGN = re.compile(r"(××|XX|ＸＸ|某某|[^\s，。]{2,16}(?:局|厅|委|办|部|处|科|"
                   r"政府|中心|办公室|委员会|工作组|调研组|课题组))$")
_DATE = re.compile(r"(\d{4}|××××|XXXX|ＸＸＸＸ)\s*年\s*(\d{1,2}|××|XX)\s*月"
                   r"\s*(\d{1,2}|××|XX)\s*日$|^\d{4}年\d{1,2}月\d{1,2}日$")


def has_sign(ans):
    """落款署名：末尾若干行里有单位名/××。"""
    return any(_SIGN.search(re.sub(r"\s", "", ln)) for ln in lines(ans)[-3:])


def has_date(ans):
    return any(_DATE.search(re.sub(r"\s", "", ln)) for ln in lines(ans)[-3:])


def fentiao(ans):
    """分条方式：规范序号 / 括号序号 / 阿拉伯 / 一是二是（后者是扣分项）。"""
    s = re.sub(r"\s", "", ans or "")
    out = []
    if len(re.findall(r"[一二三四五六]、", s)) >= 2:
        out.append("汉字序号")
    if len(re.findall(r"[（(][一二三四五六][)）]", s)) >= 2:
        out.append("括号序号")
    if len(re.findall(r"[1-9][、.．]", s)) >= 2:
        out.append("阿拉伯序号")
    if "一是" in s and "二是" in s:
        out.append("一是二是（扣分项）")
    return out or ["不分条"]


CHECKS = [("标题", has_title), ("称谓", has_call), ("主送机关", has_to),
          ("落款·署名", has_sign), ("落款·日期", has_date)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true")
    ap.add_argument("--era", default="new", choices=["new", "old", "all"])
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    where = "" if a.era == "all" else "AND p.era=?"
    args = [] if a.era == "all" else [a.era]
    rows = con.execute(
        "SELECT p.year, p.exam, COALESCE(p.kind,'') kind, q.seq, q.doctype, q.family, "
        "q.form, q.words, q.score, q.answer, q.label_src "
        "FROM slreal_questions q JOIN slreal_papers p ON p.id=q.paper_id "
        "WHERE q.qkind='贯彻执行' AND q.answer!='' %s ORDER BY p.year, q.seq" % where,
        args).fetchall()

    # 去重：同一场考试的 .doc/.pdf 两版 + 题面/答案两份，会把 1 个样本数成 4 个
    seen, items = {}, []
    for r in rows:
        key = (r["year"], r["exam"], r["kind"], r["seq"])
        if key in seen:
            continue
        seen[key] = 1
        items.append(dict(r))

    print("== 样本 ==")
    print("  贯彻执行·带答案：%d 条（去重前 %d）· era=%s" % (len(items), len(rows), a.era))
    print("  人工标注 %d · 规则判 %d"
          % (sum(1 for x in items if x["label_src"] == "human"),
             sum(1 for x in items if x["label_src"] == "rule")))

    by = defaultdict(list)
    for x in items:
        by[x["family"] or x["doctype"] or "?"].append(x)

    print("\n== 文种族 × 格式部件（出现率；≥%d%% 必需，%d~%d%% 可选）==" % (REQ, OPT, REQ - 1))
    print("   ⚠️ 少于 %d 份答案的族只列数字、**不出判定**\n" % MIN_N)
    out = []
    for fam in sorted(by, key=lambda f: -len(by[f])):
        xs = by[fam]
        note = "" if len(xs) >= MIN_N else "  ⚠️ 样本不足"
        print("  【%s】%d 份%s" % (fam, len(xs), note))
        for pname, fn in CHECKS:
            c = sum(1 for x in xs if fn(x["answer"]))
            rate = 100.0 * c / len(xs)
            verdict = ("样本不足" if len(xs) < MIN_N else
                       "必需" if rate >= REQ else "可选" if rate >= OPT else "不用")
            print("      %-10s %3.0f%%  (%d/%d)  %s" % (pname, rate, c, len(xs), verdict))
            out.append(dict(family=fam, n=len(xs), part=pname, hits=c,
                            rate=round(rate), verdict=verdict))
        ft = Counter(t for x in xs for t in fentiao(x["answer"]))
        print("      分条方式：%s" % "、".join("%s×%d" % kv for kv in ft.most_common()))

    print("\n== 全样本汇总（%d 份真题答案）==" % len(items))
    for pname, fn in CHECKS:
        c = sum(1 for x in items if fn(x["answer"]))
        print("  %-10s %3.0f%%  (%d/%d)" % (pname, 100.0 * c / max(1, len(items)),
                                            c, len(items)))
    ft = Counter(t for x in items for t in fentiao(x["answer"]))
    print("  分条方式：%s" % "、".join("%s×%d" % kv for kv in ft.most_common()))
    bad = [x for x in items if "一是二是（扣分项）" in fentiao(x["answer"])]
    print("  ⚠️ 参考答案里用「一是…二是…」的：%d/%d —— %s"
          % (len(bad), len(items),
             "fix_fentiao 那条硬替换要重新审：真题答案自己也这么写"
             if bad else "一份都没有，印证 fix_fentiao 的硬替换是对的"))

    print("\n== 字数：真题限值 vs 参考答案实际 ==")
    pair = [(x["words"], len(re.sub(r"\s", "", x["answer"]))) for x in items if x["words"]]
    if pair:
        ratio = sorted(b / a2 for a2, b in pair)
        print("  n=%d  答案/限值 比例：最小 %.2f 中位 %.2f 最大 %.2f"
              % (len(ratio), ratio[0], ratio[len(ratio) // 2], ratio[-1]))
        print("  → 参考答案通常写到限值的 %.0f%%，**不是顶着上限写**"
              % (100 * ratio[len(ratio) // 2]))
    by_score = defaultdict(list)
    for x in items:
        if x["score"] and x["words"]:
            by_score[x["score"]].append(x["words"])
    for s in sorted(by_score):
        v = sorted(by_score[s])
        print("  %2d 分 n=%-2d 字数限值 %s" % (s, len(v), "/".join(map(str, v))))

    if a.csv and out:
        p = os.path.join(HERE, "yy-真题格式骨架.csv")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(out[0]))
            w.writeheader()
            w.writerows(out)
        print("\n矩阵 → %s" % p)


if __name__ == "__main__":
    main()
