#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""社区**主观题**入库：把云盘里的案例分析 / 公文写作 / 简答论述解析成能写、能批改的题。

为什么单起一份而不是塞进 ingest_sqbank.py：那份收的是选择题，命门是「答案字母落没落在
选项范围内」；主观题连选项都没有，命门换成了另一件事 ——

    **题干在一本册子里，参考答案在另一本册子里。**

「近五年多省份主观题真题题库」是分家的两本 PDF（题干册 45 页 / 答案册 71 页），
顺次配对等于整本答案错位，而且**题数照样对得上**、体检单照样全绿。所以这儿的规矩是：

  · 键是**（分节, 题号）两段**。两本册子里题号都在每一节里各自从 1 编，
    只按题号做键的话「案例分析第 1 题」会拿到「简答论述第 1 题」的答案；
  · 两边都不空才收。题干册的「写作题」那一节有 30 道，答案册对应的那节
    压根没给参考答案 —— 那 30 道**一道都不收**，宁可少收也不发没答案的题；
  · 分节标题必须**认全**。少认一个节，后面所有题都会挂到上一节的号段上，
    然后安安静静地全部错位。实测把「案例分析题真题题库」漏认成上一节时，
    45 道题的答案全挂错，对齐率反而看不出异常。

OCR 修复放在**取采分点之前**（顺序不能反）：这批册子把「(1)」认成 `(1T)`、`(TD)`、
`(4`，把「①」认成 `@`。不修的话 mods/sqgrade.split_points 一个顶层点都拆不出来，
34 道案例题里有 24 道会退化成「只能对照参考答案、不能逐点批改」。实测修完
可批改从 29 道涨到 73 道。

分值的实话：外省原册**没标分值**。库里写的分数是照本地真题的口径给的
（案例 12 分、公文 15 分），简答论述本地根本没考过、连口径都没有，按 10 分记。
界面上必须把这件事说出来，别让人以为 12 分是原卷印着的。

用法：
    python3 ingest_sqsub.py --scan        # 只解析并报对齐率，不写库
    python3 ingest_sqsub.py --scan -v     # 连丢掉的题也列出来
    python3 ingest_sqsub.py               # 写库（同一来源重跑会先删旧的，幂等）
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import realbank as R                                        # noqa: E402
from mods import sqgrade                                     # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))

PAPER_KIND = "主观题库"

# 分值口径。**不是原册印的**，是照本地真题给的 —— 见文件头。
SCORE = {"case": 12.0, "gongwen": 15.0, "short": 10.0}

# 页眉页脚里的广告。这批册子每一页都印着卖家 QQ，不滤掉会被当成题干续行接进去。
JUNK = re.compile(r"卖家唯一联系|淘宝店|明俐教育|明便教育|明例教育|公众号|www\.|taobao|QQ[:：]")
PAGE = re.compile(r"第\s*\d+\s*页\s*共\s*\d+\s*页")


# ---------------------------------------------------------------- OCR 修复
# 「(1)」的各种认错形状：(1T) / (TD) / (T) / (4  （右括号被吃掉）
_PAREN = re.compile(r"^[\s　]*[（(][\s　]*(?:T[D]?|(\d{1,2})[\s　]*T?)[\s　]*[）)]?[\s　]*(?=\S)")
# 「①②③」被认成 @ / @@ —— **行首和句中要分开处理**。行首那种是采分点的边界，
# 必须变成能被 sqgrade 认出的 `(N)`；句中那种（`包括: @家庭矛盾，@教育方式不当`）
# 只是个项目符号，**按顺序补号就是在编数字了** —— 一律折成「·」，
# 如实表示「这儿原本有个圈码，圈的几号认不出来」。
_CIRCLE = re.compile(r"^[\s　]*[@]+[\s　]*(?=\S)")
_CIRCLE_MID = re.compile(r"[@]+")


def ocr_points(text):
    """把被 OCR 认花的条目号还原成规整的 `(N)`。

    认不出号码的（`(T)`、`@`）按**出现顺序**补号 —— 这不是猜答案，是补一个
    本来就靠顺序读的序号；补错了顶多是编号错位一格，不会让答案变成另一道题的。
    """
    out, auto = [], 0
    for ln in (text or "").splitlines():
        m = _PAREN.match(ln)
        if m:
            no = m.group(1)
            if no is None:
                auto += 1
                no = str(auto)
            else:
                auto = int(no)
            out.append("(%s)%s" % (no, ln[m.end():]))
            continue
        m2 = _CIRCLE.match(ln)
        if m2:
            auto += 1
            out.append("(%d)%s" % (auto, _CIRCLE_MID.sub("·", ln[m2.end():])))
            continue
        out.append(_CIRCLE_MID.sub("·", ln))
    return "\n".join(out)


# 题干断行：OCR 是按**版面**换行的，一句话常被劈成三行。整篇拼成一行读着累，
# 照原样留着又全是硬折行。折中：只在下一行**自己就是一个结构标记**时才断开
# （`问题:`、`(1)请…`、`1.`、`一、`），其余接到上一行末尾。
_STEM_KEEP = re.compile(r"^[\s　]*(?:问题|请回答|要求)[:：]|"
                        r"^[\s　]*[（(]?\d{1,2}[）)][\s　]*[请试简谈结分]|"
                        r"^[\s　]*\d{1,2}[、.．][\s　]*[请试简谈结分]|"
                        r"^[\s　]*[一二三四五][、.．]")


def join_stem(text):
    out = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if out and not _STEM_KEEP.match(ln):
            out[-1] += ln
        else:
            out.append(ln)
    return "\n".join(out)


_TOP_PAREN = re.compile(r"^[\s　]*[（(](\d{1,2})[）)][\s　]*(\S.*)$")


def promote_points(text):
    """整篇没有顶层「N.」编号、却有两条以上「(N)」时，把 (N) 提成顶层采分点。

    为什么要提：sqgrade 把「（N）」当**子要素**（归到上一个采分点里），这条规则
    是为本地真题的参考答案写的、没错；但外省这批答案顶层就是用「(1)(2)(3)」编的，
    照原样喂进去等于一个顶层点都没有，整道题变成「拆不出采分点」。

    **只在没有顶层编号时才提。** 两种编号都有的答案（`1.` 底下挂 `(1)(2)`）
    照原样交给 sqgrade，别把人家的层级压平了。
    """
    lines = (text or "").splitlines()
    if sum(1 for l in lines if sqgrade._NUMBERED.match(l)) >= 2:
        return text
    if sum(1 for l in lines if _TOP_PAREN.match(l)) < 2:
        return text
    return "\n".join(_TOP_PAREN.sub(lambda m: "%s. %s" % (m.group(1), m.group(2)), l)
                     for l in lines)


# ---------------------------------------------------------------- 来源一：多省主观题真题（题干册 + 答案册）
# 分节名 → (库里的 part, 对外的题型说明)。**顺序有讲究**：判断一行属于哪一节时
# 「公文写作」必须排在「写作」前面，否则「公文写作题库参考答案」会被判成「写作」节。
SECS = [("简答", "short"), ("公文写作", "gongwen"), ("写作", None),
        ("案例分析", "case"), ("实践应用", "case")]
SEC_NAME = {"简答": "简答论述", "公文写作": "公文写作", "写作": "写作",
            "案例分析": "案例分析", "实践应用": "实践应用"}

_Q_NO = re.compile(r"^[\s　]*(\d{1,3})[\s　]*[、.．][\s　]*(\S.*)$")
_A_NO = re.compile(r"^[\s　]*(\d{1,3})[\s　]*[、.．]?[\s　]*[\[【]+[\s　]*参考答案[\s　]*[】\]]+")


def _sec_of(line):
    """这一行是不是分节标题。是就返回节名，不是返回 None。

    判据是「短行 + 含『题库』」而不是精确匹配整句：两本册子的标题写法本来就不一样
    （题干册叫「案例分析题真题题库」，答案册叫「案例分析题题库参考答案」），
    再加上 OCR 会把页脚粘到同一行上。精确匹配漏一个节，后面整节都会错位。
    """
    s = PAGE.sub("", line).strip()
    if "题库" not in s or len(s) > 40:
        return None
    for key, _ in SECS:
        if key in s:
            return key
    return None


def scan_pair(qtext, atext):
    """题干册 + 答案册 → {(节, 题号): {"stem":…, "answer":…}}。"""
    def scan(text, is_ans):
        sec, cur, out = "简答", None, {}
        for raw in text.splitlines():
            if not raw.strip() or JUNK.search(raw):
                continue
            s = _sec_of(raw)
            if s:
                sec, cur = s, None
                continue
            ln = PAGE.sub(" ", raw)
            m = _A_NO.match(ln) if is_ans else _Q_NO.match(ln)
            if m:
                cur = (sec, int(m.group(1)))
                out.setdefault(cur, [])
                if not is_ans:
                    out[cur].append(m.group(2).strip())
                continue
            if cur is not None:
                out[cur].append(ln.strip())
        return {k: "\n".join(v).strip() for k, v in out.items()}

    qs, ans = scan(qtext, False), scan(atext, True)
    merged, drop = {}, []
    for k in sorted(qs):
        part = dict(SECS).get(k[0])
        if part is None:                       # 「写作」节：答案册没给参考答案
            drop.append((k, "这一节整节没有参考答案"))
            continue
        a = ans.get(k, "")
        if len(a) < 30:
            drop.append((k, "答案册里没有这一条" if k not in ans else "答案太短，多半是没抠全"))
            continue
        if len(qs[k]) < 15:
            drop.append((k, "题干太短，多半是 OCR 把题面吃了"))
            continue
        merged[k] = {"part": part, "sec": k[0], "no": k[1],
                     "stem": R.norm(join_stem(ocr_points(qs[k]))),
                     "answer": promote_points(ocr_points(a))}
    orphan = [k for k in ans if k not in qs and dict(SECS).get(k[0])]
    return merged, drop, orphan


# ---------------------------------------------------------------- 来源清单
# 每份来源写清楚**它是什么形状**，别指望一套正则打天下。
SOURCES = [
    {"key": "多省主观题真题",
     "name": "近五年多省份主观题真题题库",
     "q_file": "近五年多省份主观题真题题库", "a_file": "近五年多省份主观题真题题库参考答案",
     "note": "外省真题，与本地「案例分析 + 公文写作」同型；简答论述本地未考过。"},
]


def _text(con, keyword):
    """按文件名关键词取一份资料的文字。**先 OCR 表、后文字层** ——
       这批册子都是扫描件，OCR 一次、解析多次（见 ocr_sqbank.py 的文件头）。"""
    row = con.execute(
        "SELECT id,name,stored_name FROM drive_files WHERE name LIKE ? "
        "AND is_dir=0 AND deleted_at IS NULL ORDER BY LENGTH(name) LIMIT 1",
        ("%" + keyword + "%",)).fetchone()
    if not row:
        return None, None
    got = "\n".join(r[0] or "" for r in con.execute(
        "SELECT text FROM sq_ocr WHERE file_id=? ORDER BY page", (row["id"],)))
    if len(got.strip()) < 500:
        path = None
        for d in os.listdir(os.path.join(UPLOADS, "drive")):
            cand = os.path.join(UPLOADS, "drive", d, row["stored_name"])
            if os.path.exists(cand):
                path = cand
                break
        got = R.pdf_text(path) if path else ""
    return row["id"], got


def save(con, src, items):
    """入库。一份来源一张 sq_papers，重跑先清空 —— 幂等，不会越跑越多。"""
    row = con.execute("SELECT id FROM sq_papers WHERE name=? AND kind=?",
                      (src["name"], PAPER_KIND)).fetchone()
    if row:
        pid = row["id"]
        con.execute("DELETE FROM sq_questions WHERE paper_id=?", (pid,))
    else:
        pid = con.execute(
            "INSERT INTO sq_papers(file_id,name,folder,ext,region,year,kind,total,status,note) "
            "VALUES(NULL,?,?,?,?,?,?,?,?,?)",
            (src["name"], "", ".pdf", "通用", 0, PAPER_KIND, 0, "ok", src["note"])).lastrowid
    for i, it in enumerate(items, 1):
        con.execute(
            "INSERT INTO sq_questions(paper_id,seq,part,part_seq,qtype,stem,options,answer,"
            "explain,score,verify,verify_note,qhash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, i, it["part"], it["no"], it["qtype"], it["stem"], "", it["answer"], "",
             SCORE[it["part"]], "ok",
             # 和练习册同一个口径：原册印着的参考答案，不过 AI 校对闸门。
             # 闸门是查回忆版真题用的，主观题也没有「唯一正确答案」可校。
             json.dumps({"why": "外省题库原册参考答案，按（分节, 题号）与答案册对齐",
                         "src": "ocr", "sec": it["sec"],
                         "score_from": "本地真题口径，外省原册未标分值"},
                        ensure_ascii=False),
             hashlib.sha1(R.qhash_text(it["stem"]).encode("utf-8")).hexdigest()[:16]))
    con.execute("UPDATE sq_papers SET n_obj=0, n_sub=?, n_doubt=0 WHERE id=?", (len(items), pid))
    return pid


# 考点大类：主观题按**题面关键词**归，和选择题共用 ingest_shequ.qtype_of 那套会把
# 大半归进兜底桶（案例题题面全是叙事，命中不了考点关键词）。这儿单给一套粗分类，
# 分不出来就写「社会工作」——**不硬塞进「本地县情」**，外省题里不会有本地题。
_QT = [("党建党务", ("党员", "党章", "党支部", "党组织", "党委", "十九大", "党的建设")),
       ("公文写作", ("通知", "请示", "报告", "函", "纪要", "公文", "介绍信", "倡议书")),
       ("法律法规", ("组织法", "民法典", "法律援助", "宪法", "条例规定", "依法")),
       ("社区知识", ("居委会", "业委会", "物业", "网格", "社区服务", "社区治理", "社区建设")),
       ("时政理论", ("习近平", "总书记", "二十大", "时政")),
       ("应急安全", ("火灾", "疫情", "隐患", "消防", "治安", "扫黑除恶"))]


def qtype_of(stem, part):
    if part == "gongwen":
        return "公文写作"
    hit = [(sum(stem.count(k) for k in kws), t) for t, kws in _QT]
    n, t = max(hit)
    return t if n else "社会工作"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="只解析并报账，不写库")
    ap.add_argument("-v", "--verbose", action="store_true", help="连丢掉的题也列出来")
    ap.add_argument("--only", default="", help="只处理 key 含这个词的来源")
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    grand = {}
    for src in SOURCES:
        if a.only and a.only not in src["key"]:
            continue
        qid, qtext = _text(con, src["q_file"])
        aid, atext = _text(con, src["a_file"])
        if not qtext or not atext:
            print("✗ %s：云盘里找不到%s" % (src["key"], "题干册" if not qtext else "答案册"))
            continue
        merged, drop, orphan = scan_pair(qtext, atext)
        items = []
        for k in sorted(merged, key=lambda x: (x[0], x[1])):
            it = merged[k]
            it["qtype"] = qtype_of(it["stem"], it["part"])
            it["gradable"] = bool(sqgrade.split_points(it["answer"], SCORE[it["part"]])) \
                if it["part"] != "gongwen" else True      # 公文按结构部件给分，不拆点
            items.append(it)
        n_all = len(merged) + len(drop)
        print("\n%s %s" % ("○" if a.scan else "●", src["name"]))
        print("   题干册 %d 条 / 答案册对上 %d 条 / 丢 %d 条 / 答案册多出 %d 条"
              % (n_all, len(items), len(drop), len(orphan)))
        by = {}
        for it in items:
            key = (SEC_NAME[it["sec"]], it["part"])
            by.setdefault(key, [0, 0])
            by[key][0] += 1
            by[key][1] += 1 if it["gradable"] else 0
        for key in sorted(by):
            print("     %-6s → %-8s %3d 道，其中 %d 道能逐点批改"
                  % (key[0], key[1], by[key][0], by[key][1]))
            grand[key[1]] = grand.get(key[1], 0) + by[key][0]
        if a.verbose:
            for k, why in drop[:12]:
                print("     ! %s 第 %d 题 ← %s" % (SEC_NAME.get(k[0], k[0]), k[1], why))
            if len(drop) > 12:
                print("     ! …另有 %d 条同类" % (len(drop) - 12))
        if not a.scan:
            save(con, src, items)
    if not a.scan:
        con.commit()
    print("\n合计入库 %s%s" % (
        "、".join("%s %d 道" % (k, v) for k, v in sorted(grand.items())) or "0 道",
        "（scan 模式，未写库）" if a.scan else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
