#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从真题「作答要求」里提取评分维度，灌进 yy_items 的「要求」类。

为什么这批数据值钱：真题题干里「要求：(1)内容全面，条理清晰；(2)简明扼要，格式规范」
这些条款**是出题人自己写的评分标准**，不是二手总结、更不是 AI 编的。
小题批改现在用的判分口径是提示词里手写的一段话；换成真题原话，尺子才是真的。

零 AI 调用，纯提取。

存法：一行一个 (文种, 要求项)，`freq` 记它在这个文种下出现过几次。
这样「简报的要求最常见是哪几条」就是一句 ORDER BY freq。
另外单独存一份 doctype='' 的**通用**统计（全部贯彻执行题合起来的高频要求项）。

用法：
    python3 build_yy_require.py --dry      # 只看会入哪些
    python3 build_yy_require.py            # 入库（幂等）
    python3 build_yy_require.py --stats    # 看库里现有的
"""
import argparse
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))

# 条款之间的分隔：分号、编号项、逗号都可能。真题里三种写法都有：
#   「内容全面，要点突出，条理清晰，语言简洁；不超过500字。」
#   「(1)内容全面，条理清晰；(2)简明扼要，格式规范；(3)不超过500字。」
_SPLIT = re.compile(r"[；;。]|[（(]\s*\d+\s*[)）]|，|,")
# 字数那一项不要——它已经单独存在 slreal_questions.words 里了，在这儿是噪声
_WORDS = re.compile(r"\d{2,4}\s*字|字数|不超过|不多于|左右")
# 真题要求项都是四字/五字的短评价语。太长的是句子（如「梳理完所有问题后再提出建议」），
# 那是**答题指令**不是评分维度，另存一类
_MAXLEN = 8


# 异体字：PDF 里混着 CJK 部首区的字（⾯ U+2FA1 而不是 面 U+9762），
# 不归一的话「内容全面」和「内容全⾯」会被当成两个不同的维度
_VARIANT = {"⾯": "面", "⼀": "一", "⽂": "文", "⼒": "力", "⽤": "用", "⾼": "高"}


def clean(s):
    s = re.sub(r"\s+", "", s or "")
    for a, b in _VARIANT.items():
        s = s.replace(a, b)
    s = s.strip("；;。，,、()（）0123456789.")
    return s


# 分值标记和题干指令的残渣：「分）要求：」「写一篇文章」都不是评分维度
_JUNK = re.compile(r"要求|^分[）)]|[（(]\s*分|^写一篇|^作答|^根据|^结合")


# 带【】的「要求」不是真题原文，是出版社的解析批注混进来了。
# 实测 2017 国考地市 Q6 那两条就是这么来的——它的「题干」本身也是答案文本（切错了），
# 不滤掉的话，「完善"亲水"设施」「组织水上游览线路」这些**答案内容**会被当成评分维度入库。
_ANNOT = re.compile(r"[【】]")
# 评分维度是短评价语，不会带引号或书名号。带引号的多半是标题/内容片段
# （「以"岁月失语，惟石能言"为题」被逗号一切就成了两个假维度）
_QUOTED = re.compile(r"[“”\"《》‘’]")


def extract(require):
    """→ (评分维度[], 答题指令[])。看到解析批注就整条弃掉。"""
    if _ANNOT.search(require or ""):
        return [], []
    dims, orders = [], []
    for piece in _SPLIT.split(require or ""):
        p = clean(piece)
        if len(p) < 2 or _WORDS.search(p) or _QUOTED.search(p) or _JUNK.search(p):
            continue
        (dims if len(p) <= _MAXLEN else orders).append(p)
    return dims, orders


def run(con, dry=False):
    rows = con.execute(
        "SELECT q.doctype, q.family, q.require, p.era, p.year, p.exam, q.seq "
        "FROM slreal_questions q JOIN slreal_papers p ON p.id=q.paper_id "
        "WHERE q.qkind='贯彻执行' AND q.require!=''").fetchall()
    # 去重：同一场考试的 .doc/.pdf 两版会把一条要求数成两条
    seen, per_dt, allc, orders = set(), defaultdict(Counter), Counter(), Counter()
    src_of = {}
    for r in rows:
        key = (r["year"], r["exam"], r["seq"], (r["require"] or "")[:20])
        if key in seen:
            continue
        seen.add(key)
        dims, ords = extract(r["require"])
        dt = r["doctype"] or ""
        for d in dims:
            per_dt[dt][d] += 1
            allc[d] += 1
            src_of.setdefault((dt, d), "%s%s Q%s" % (r["year"], r["exam"], r["seq"]))
        for o in ords:
            orders[o] += 1

    print("去重后 %d 道题的要求 → %d 个文种 · %d 种评分维度"
          % (len(seen), len(per_dt), len(allc)))
    print("\n== 全部贯彻执行题的高频评分维度 ==")
    for k, v in allc.most_common(14):
        print("  %-8s %d 次" % (k, v))
    print("\n== 按文种（取样本最多的几个）==")
    for dt in sorted(per_dt, key=lambda d: -sum(per_dt[d].values()))[:6]:
        if not dt:
            continue
        print("  【%s】%s" % (dt, "、".join("%s×%d" % kv for kv in per_dt[dt].most_common(6))))
    if orders:
        print("\n== 答题指令（长句，不是评分维度，单独存）==")
        for k, v in orders.most_common(6):
            print("  %s ×%d" % (k[:40], v))

    if dry:
        print("\n（--dry，没写库）")
        return

    ins = dup = 0
    def put(dt, title, text, note, freq, ref):
        nonlocal ins, dup
        cur = con.execute(
            "INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,note,src,src_ref,freq) "
            "VALUES('要求',?,'',?,?,?,'real',?,?)", (dt, title, text, note, ref, freq))
        if cur.rowcount:
            ins += 1
        else:                      # 已存在：freq 可能变了（补了新真题），更新它
            con.execute("UPDATE yy_items SET freq=?, src_ref=? "
                        "WHERE kind='要求' AND doctype=? AND part='' AND title=?",
                        (freq, ref, dt, title))
            dup += 1

    for dt, c in per_dt.items():
        for title, n in c.items():
            put(dt, title, "%s的作答要求里出现 %d 次" % (dt or "贯彻执行题", n),
                "真题原话的评分维度——批改时按这个口径判，比自己编的标准可靠",
                n, src_of.get((dt, title), ""))
    for title, n in allc.most_common():
        put("", title, "全部贯彻执行题里出现 %d 次" % n,
            "跨文种通用的评分维度", n, "全部真题统计")
    for title, n in orders.most_common():
        put("", title, "答题指令（非评分维度）",
            "这是题干里的**答题指令**，不是评分维度——照着做，但别当判分标准", n, "")
    con.commit()
    print("\n入库 %d 条，更新 %d 条" % (ins, dup))


def stats(con):
    n = con.execute("SELECT COUNT(*) FROM yy_items WHERE kind='要求'").fetchone()[0]
    print("库内「要求」%d 条" % n)
    for r in con.execute("SELECT doctype, title, freq FROM yy_items WHERE kind='要求' "
                         "AND doctype='' ORDER BY freq DESC LIMIT 10"):
        print("  通用 %-8s %s 次" % (r[1], r[2]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    stats(con) if a.stats else run(con, a.dry)


if __name__ == "__main__":
    main()
