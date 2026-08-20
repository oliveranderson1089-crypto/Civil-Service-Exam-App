#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公文题库入库：把「04.社区写作全套资料」下的 docx 练习解析成可刷的题。

为什么单开一份，而不是并进 ingest_sqbank.py：

  ingest_sqbank  吃 PDF 练习册，题干在前、答案统一在卷末，**命门是答案对齐**；
  这一份         吃 docx，答案就跟在每道题后面，不存在错位风险 ——
                 命门变成了「**同一批文件里混着两种写法**」。

两种写法（同一个文件夹里都有，得一套代码全吃下）：

    ① 1.（单选题）下列不属于行政公文的是（  ）。      ② 慰问信中可以使用：(    )。
       A. 公告                                          A.感谢用语 B.关心鼓励用语
       B. 通告                                          C.祝愿用语 D.适度的抒情手法
       【答案】C【解析】…                                【答案】BCD。解析：…
       有题号、有题型标注、选项一行一个              没题号没标注、选项挤在一行、解析不带书名号

所以**不按题号切题，按【答案】行往回倒**：答案行是每道题确定的终点，
往上到上一道题结束为止就是这道题的题干和选项。两种写法就统一了。

一个数出来的坑：部分文件同一道题印了**两条**答案标记（`【答案】B【解析】…` 之后
又来一条 `【解析】【答案】B。解析：…`），全库 1612 个标记里有 305 个是这种重复。
按行倒推时它们表现为「空块」—— 不能当成新题，也不能扔掉：第二条的解析往往更全，
拿它补上一道题的解析。1307 + 305 = 1612，对得上才算没漏收。

用法：
    python3 ingest_gongwen.py --scan       # 只解析并报体检单，不写库
    python3 ingest_gongwen.py --scan -v    # 连坏样例一起打出来
    python3 ingest_gongwen.py              # 写库（重跑=按 file_id 覆盖）
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import realbank as R                                       # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))
FOLDER = "04.社区写作全套资料"
QTYPE = "公文写作"                     # 整个文件夹都是公文，不用逐题猜考点
PAPER_KIND = "题库"

RE_ANS = re.compile(r"【\s*答\s*案\s*】\s*[:：]?\s*([A-Z]{1,6}|正确|错误|对|错|[√×])")
RE_ANS_MARK = re.compile(r"【\s*答\s*案\s*】")
# 解析可能写成 `【解析】…`，也可能写成 `解析：…`（后者是第二种写法用的）
RE_EXP = re.compile(r"(?:【\s*解\s*析\s*】|解析\s*[:：])\s*(.*)$")
RE_OPT_HEAD = re.compile(r"^\s*[A-Z]\s*[.、．]")
RE_OPT_SPLIT = re.compile(r"(?=[A-Z]\s*[.、．])")
RE_TYPE = re.compile(r"[（(]\s*(单选题|多选题|判断题|不定项选择题|填空题)\s*[)）]")
RE_NO = re.compile(r"^\s*(\d{1,4})\s*[.、．]\s*")
# 判断题的题干常以「(判断)」开头，或者答案本身就是对错 —— 两个信号都要看：
# 只看答案的话，「A」既可能是单选答案也可能是判断题被排版成了选择题
RE_JUDGE_HINT = re.compile(r"^[\s（(]*判\s*断[)）\s]*")
# 解析的收尾话。用来在没有题号可切的文件里，认出「上一题的解析到哪儿结束」
RE_TAIL = re.compile(r"(?:故本题|本题答案|答案为|答案选|【\s*解\s*析\s*】|解析\s*[:：])")
# 判断题题干后面印的作答提示
RE_TF_TAIL = re.compile(r"[\s　]*(?:正确\s*错误|对\s*错|[（(]\s*[）)])\s*$")
RE_TF_LINE = re.compile(r"^[\s　]*[（(]?\s*(?:正确|错误|对|错|[√×AB]\s*[.、．]?\s*(?:正确|错误))"
                        r"\s*[)）]?[\s　。.]*$")
# 选择题题干该有的样子：句中留了空位，或者以问句/冒号收尾
RE_BLANK = re.compile(r"[（(][\s　]*[）)]|_{3,}|[?？]|[：:]\s*$")
RE_NUMLIST = re.compile(r"\d\s*[.、．][^0-9]{4,}?\d\s*[.、．]")
ANS_MAP = {"正确": "T", "对": "T", "√": "T", "Y": "T",
           "错误": "F", "错": "F", "×": "F", "N": "F"}


def docx_text(path):
    """docx → 纯文本。段落和软换行都还原成换行，其余标签一律去掉。

    不引第三方库：docx 就是个 zip，正文在 word/document.xml，
    这点活不值得给项目加一个依赖。
    """
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def parse(lines):
    """[行] → [题]。以【答案】行为终点往回倒，见模块头的说明。"""
    out, start = [], 0
    for i, ln in enumerate(lines):
        if not RE_ANS_MARK.search(ln):
            continue
        blk, start = lines[start:i], i + 1
        ma = RE_ANS.search(ln)
        me = RE_EXP.search(ln)
        if not blk:
            # 同一道题的第二条答案标记：拿它更全的解析补上一道题，不算新题
            if out and me and len(me.group(1)) > len(out[-1]["explain"]):
                out[-1]["explain"] = me.group(1).strip()[:2000]
            continue
        if not ma:
            continue
        oi = next((j for j, x in enumerate(blk) if RE_OPT_HEAD.match(x)), len(blk))
        head = blk[:oi]
        # **题干从最后一个题号行开始。** 上一道题的解析常常续到下一行，而那一行
        # 落在本题的块里 —— 不掐掉的话题干会长成
        # 「【解析】专用公文是指…故本题判断正确。 5. 广义的公文一般指…」。
        # 抽查 6 道中了 4 道，而体检单全绿（题干够长、选项齐、答案在范围内），
        # 光看数字发现不了。没有题号的那种写法（选项挤一行的）不受影响，整段就是题干。
        last_no = next((j for j in range(len(head) - 1, -1, -1) if RE_NO.match(head[j])), None)
        if last_no is not None:
            head = head[last_no:]
        else:
            # 没有题号的写法（选项挤在一行那种）：从后往前收，**碰到解析就停**。
            # 上一题的解析没有题号可以切，只能靠「故本题…」「解析：…」这些收尾话认。
            cut = next((j for j in range(len(head) - 1, -1, -1) if RE_TAIL.search(head[j])), None)
            if cut is not None:
                head = head[cut + 1:]
        # 判断题的「正确 / 错误」是印在题干后面的作答选项，不是题干的一部分。
        # word 里它们**各占一行**（不是「正确 错误」同一行），所以既要按整行滤，
        # 也要按行尾滤 —— 只做后者的话题干会拖着一句「正确 错误」进库。
        head = [x for x in head if not RE_TF_LINE.match(x)]
        head = [RE_TF_TAIL.sub("", x).strip() for x in head]
        stem = " ".join(x for x in head if x).strip()
        opts = []
        for x in blk[oi:]:
            for p in RE_OPT_SPLIT.split(x):
                p = p.strip()
                if RE_OPT_HEAD.match(p):
                    opts.append(re.sub(r"^\s*([A-Z])\s*[.、．]\s*", r"\1. ", p))
        t = RE_TYPE.search(stem)
        stem = RE_NO.sub("", RE_TYPE.sub("", stem)).strip()
        ans = ANS_MAP.get(ma.group(1), ma.group(1))
        judge = bool(RE_JUDGE_HINT.match(stem)) or ans in ("T", "F")
        stem = RE_JUDGE_HINT.sub("", stem).strip()
        if t and t.group(1) == "判断题":
            judge = True
        part = "judge" if judge else ("multi" if len(ans) > 1 else "single")
        if part == "judge" and ans not in ("T", "F"):
            # 题干说是判断题、答案却给了字母：这种题谁也说不准，宁可不要
            continue
        out.append({"stem": stem, "options": [] if part == "judge" else opts,
                    "answer": ans, "explain": (me.group(1).strip()[:2000] if me else ""),
                    "part": part})
    return out


def check(items):
    """体检：**不合格的题不入库**。数量对不代表内容对，见 realbank 的教训。"""
    ok, bad = [], []
    for it in items:
        why = ""
        if len(it["stem"]) < 8:
            why = "题干过短"
        elif it["part"] != "judge" and len(it["options"]) < 2:
            why = "选项少于 2 个"
        elif it["part"] != "judge" and any(
                c not in [o[0] for o in it["options"]] for c in it["answer"]):
            why = "答案落在选项范围之外"
        elif it["part"] == "single" and len(it["answer"]) != 1:
            why = "单选答案不是单个字母"
        elif (it["part"] != "judge" and not RE_BLANK.search(it["stem"])
              and (len(it["stem"]) > 110 or RE_NUMLIST.search(it["stem"]))):
            # 选择题的题干总得有个空位（括号、下划线）或以问句收尾。又长、又没有空位、
            # 还带着「1.… 2.…」的编号列表 —— 这是上一题的**参考答案范文**被当成了题干。
            # 判据故意收得很紧：1104 道里只命中 7 道，其中还有几道是题干很长的材料题，
            # 一并剔掉。**宁可少收几道，也别把范文当题发给人做。**
            why = "题干像范文正文，不像题目"
        (bad if why else ok).append(dict(it, why=why) if why else it)
    return ok, bad


def find_file(stored):
    """云盘文件按 owner 分子目录存（uploads/drive/<uid>/<stored_name>），挨个找。"""
    root = os.path.join(UPLOADS, "drive")
    if not os.path.isdir(root):
        return None
    for d in sorted(os.listdir(root)):
        p = os.path.join(root, d, stored or "")
        if os.path.exists(p):
            return p
    return None


def scan(con):
    return con.execute(
        "SELECT id,name,folder,stored_name FROM drive_files "
        "WHERE deleted_at IS NULL AND is_dir=0 AND folder LIKE ? AND name LIKE '%.docx' "
        "ORDER BY folder,name", ("%" + FOLDER + "%",)).fetchall()


def save(con, f, items):
    row = con.execute("SELECT id FROM sq_papers WHERE file_id=?", (f["id"],)).fetchone()
    if row:
        pid = row["id"]
        con.execute("DELETE FROM sq_questions WHERE paper_id=?", (pid,))
    else:
        pid = con.execute(
            "INSERT INTO sq_papers(file_id,name,folder,ext,region,year,kind,total,status) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (f["id"], f["name"].rsplit(".", 1)[0], f["folder"], ".docx",
             "通用", 0, PAPER_KIND, 0, "ok")).lastrowid
    for i, it in enumerate(items, 1):
        con.execute(
            "INSERT INTO sq_questions(paper_id,seq,part,part_seq,qtype,stem,options,answer,"
            "explain,score,verify,verify_note,qhash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, i, it["part"], i, QTYPE, it["stem"],
             json.dumps(it["options"], ensure_ascii=False), it["answer"], it["explain"], 1.0,
             # 和 ingest_sqbank 同一个口径：**练习册答案是原册印的，不是回忆版**，
             # 不过 AI 校对闸门。闸门是用来查回忆版真题的。
             "ok", json.dumps({"why": "公文练习原册答案，答案紧跟题目、无错位风险",
                               "src": "docx"}, ensure_ascii=False),
             hashlib.sha1(R.qhash_text(it["stem"]).encode("utf-8")).hexdigest()[:16]))
    con.execute("UPDATE sq_papers SET n_obj=?, n_sub=0, n_doubt=0, n_bad=0 WHERE id=?",
                (len(items), pid))
    return pid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="只解析并报体检单，不写库")
    ap.add_argument("-v", "--verbose", action="store_true", help="连坏样例一起打出来")
    a = ap.parse_args()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    # 去重集合要**排除本次自己要覆盖的那几份卷子** —— 否则重跑时，上一轮入库的题
    # 会把这一轮（解析改好了的）同一道题判成「已有，跳过」，于是库里留着旧版、
    # 新版进不来，而且日志显示「重复 1115」看着一切正常。
    mine = [r["id"] for r in scan(con)]
    have = {r[0] for r in con.execute(
        "SELECT qhash FROM sq_questions WHERE qhash IS NOT NULL AND paper_id NOT IN "
        "(SELECT id FROM sq_papers WHERE file_id IN (%s))"
        % (",".join("?" * len(mine)) or "NULL"), mine)}

    n_ok = n_bad = n_dup = n_file = 0
    kinds = {}
    print("%-46s %5s %5s %5s %5s" % ("文件", "解析", "入库", "剔除", "重复"))
    print("-" * 74)
    for f in scan(con):
        path = find_file(f["stored_name"])
        if not path:
            print("!! 找不到文件：%s" % f["name"][:44])
            continue
        try:
            items = parse([x.strip() for x in docx_text(path).splitlines() if x.strip()])
        except (zipfile.BadZipFile, KeyError) as e:
            print("!! %s 读不出来：%s" % (f["name"][:34], e))
            continue
        if not items:
            continue
        ok, bad = check(items)
        # 去重按 qhash：同一道题在好几份练习里重复出现是常事
        fresh, dup = [], 0
        for it in ok:
            h = hashlib.sha1(R.qhash_text(it["stem"]).encode("utf-8")).hexdigest()[:16]
            if h in have:
                dup += 1
                continue
            have.add(h)
            fresh.append(it)
        n_file += 1
        n_ok += len(fresh)
        n_bad += len(bad)
        n_dup += dup
        for it in fresh:
            kinds[it["part"]] = kinds.get(it["part"], 0) + 1
        print("%-46s %5d %5d %5d %5d"
              % (f["name"][:44], len(items), len(fresh), len(bad), dup))
        if a.verbose and bad:
            for b in bad[:3]:
                print("      剔除（%s）：%s" % (b["why"], b["stem"][:52]))
        if not a.scan and fresh:
            save(con, f, fresh)
    if not a.scan:
        con.commit()
    print("-" * 74)
    print("%d 份文件：入库 %d 道（%s），剔除 %d，与已有题重复 %d%s"
          % (n_file, n_ok, "，".join("%s %d" % kv for kv in sorted(kinds.items())),
             n_bad, n_dup, "（--scan，未写库）" if a.scan else ""))


if __name__ == "__main__":
    main()
