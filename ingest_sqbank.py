#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""社区题库入库：把云盘里**有文字层**的练习册解析成可刷的题。

和 ingest_shequ.py（整卷真题）分工不同：那份处理两套 63 题的原卷，这份处理
一百多份练习册，形状也不一样 ——

  真题卷   四个选项挤在一行，`答案：A` 就跟在题后面
  练习册   **选项一行一个**，答案统一放在卷末的「参考答案及解析」里

所以这份的**命门是答案对齐**，不是抠出多少条题。题干和答案分处两地，错位一格
就是整册答案全错，而且题数照样对得上、体检单全绿 —— 真题库当年就栽在这上面。
对策：

  · 题号和答案号**逐一对照**，对不上的题**不入库**（而不是顺次配对）；
  · 答案字母必须落在这道题实际有的选项范围内（三个选项的题不许答案是 D）；
  · 每册都报「对齐率」，低于阈值整册跳过，宁可不要也不要错的。

范围：**只收公告点名的科目**。公告写明笔试内容是「社会工作者职业资格考试初级
知识，党的建设、社区建设、基层治理、法律常识、时事政治等」，没有行测 ——
所以言语理解、资料分析、判断推理、数量关系那几百份练习册一概不收。

用法：
    python3 ingest_sqbank.py --scan            # 只解析并报对齐率，不写库
    python3 ingest_sqbank.py --scan -v         # 连每册的坏样例也打出来
    python3 ingest_sqbank.py                   # 写库
    python3 ingest_sqbank.py --min 0.9         # 调整对齐率阈值（默认 0.85）
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

import realbank as R                                       # noqa: E402
from ingest_shequ import ROOT, qtype_of                    # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))

PAPER_KIND = "题库"

# 不收的科目：公告里没有它们。**按文件夹和文件名双重排除** —— 只看其一会漏，
# 「材料分析练习」躺在公基/法律知识下面，而「常识判断练习」在行测文件夹里。
SKIP_DIR = ("行测职测",)
SKIP_NAME = ("言语理解", "资料分析", "判断推理", "数量关系", "图形推理", "类比推理",
             "逻辑填空", "片段阅读", "语句表达", "常识判断练习", "行政职业能力")
# 正向筛：**得先是一本题册**。不加这条的话讲义、政府工作报告、县情都会被当候选，
# 靠对齐闸挡下来虽然也不会出错，但每份都要 pdftotext 跑一遍，白花几分钟。
# 真题卷由 ingest_shequ.py 管，这儿要排掉，免得同一份卷子进库两次。
TAKE_NAME = ("题", "练习", "问答", "母题", "千题", "试卷", "点题", "押题")
SKIP_NAME2 = ("真题", "考点集锦", "必背（三色笔记）", "知识点", "工作报告", "县情", "公报")

# 文件夹 → 考点大类。**路径里写着真正的分类**，比按题干猜关键词准得多：
# 「含磷洗衣粉那道题」按关键词会落到兜底的「社区知识」，而它躺在
# 「公基/1.章节练习/7、科技与生活」下面 —— 一看就知道该归哪儿。
# 兜底桶吞掉大半题量的话，「按考点练」就成了一个大杂烩，等于没有分类。
FOLDER_QTYPE = [
    ("1、社区概论", "社区知识"), ("2、社区建设", "社区知识"),
    ("3、社区居民自治", "社区知识"), ("4、社区组织", "社区知识"),
    ("5、社区管理与社区服务", "社区知识"), ("6、社会工作基础知识", "社会工作"),
    ("1、道德建设", "公基常识"), ("2、政治知识", "党建党务"),
    ("3、法律知识", "法律法规"), ("4、经济知识", "公基常识"),
    ("5、管理知识", "公基常识"), ("6、公文知识", "公文写作"),
    ("7、科技与生活", "公基常识"), ("8、计算机知识", "公基常识"),
    ("9、国情与地理", "公基常识"), ("10、人文与历史", "公基常识"),
    ("11、公文写作", "公文写作"),
    ("民法典", "法律法规"), ("居民委员会组织法", "法律法规"),
    ("党章", "党建党务"), ("党建", "党建党务"), ("党务", "党建党务"),
    ("时政", "时政理论"), ("社会工作知识", "社会工作"), ("社会工作", "社会工作"),
]


def qtype_by_folder(folder, name):
    """先按文件夹判考点，判不出来再按题干关键词猜。"""
    hay = (folder or "") + "/" + (name or "")
    for k, v in FOLDER_QTYPE:
        if k in hay:
            return v
    return ""


# 题型分节
_SEC = re.compile(r"^[\s　]*[一二三四五六]\s*[、.．]\s*"
                  r"(单项?选择题?|选择单项题|多项?选择题?|不定项选择题?|判断题?|"
                  r"单选题?|多选题?|共享题干题?|案例分析题?|材料分析题?|简答题?|论述题?)")
# 共享题干 / 案例 / 简答那几节**整节丢掉**：它们的题干在别处（几道题共用一段材料），
# 单独抠出来的题面是残缺的，收进来就是发一道做不了的题。宁可不要。
_SEC_KIND = {"单": "single", "多": "multi", "不": "multi", "判": "judge",
             "选择单项": "single", "共享": "skip", "案例": "skip", "材料": "skip",
             "简答": "skip", "论述": "skip"}
# 题干：`1、社会工作又可称为（ ）。` / `12.公文拟制包括…`
_Q = re.compile(r"^[\s　]*(\d{1,3})[、.．][\s　]*(\S.*)$")
# 选项：一行一个 `A.社会服务` / `A、社会服务` / `A 社会服务`
_OPT = re.compile(r"^[\s　]*([A-EＡ-Ｅ])[\s　]*[、.．]?[\s　]*(\S.*)$")
# 答案：`1.答案：A` / `4.答案 B。解析：…` / `1、A` / `正确答案：ABD`
_ANS = re.compile(r"^[\s　]*(\d{1,3})[、.．][\s　]*(?:正确)?答案[：:\s]*([A-EＡ-Ｅ√×对错]{1,5})")
_ANS_BARE = re.compile(r"^[\s　]*(\d{1,3})[、.．][\s　]*([A-EＡ-Ｅ]{1,5})[\s　]*$")
# 一行排好几个：`1.E    2.D   3.A   4.A`。**只在一行里凑够两对时才认** ——
# 单独一对的写法交给上面两条严格的正则，免得把解析正文里的「…见第 3 条 B 项」
# 这种也当成答案。后面不许紧跟汉字或字母，挡住「1.E 类社区」这种。
_ANS_ROW = re.compile(r"(\d{1,3})[、.．][\s　]*([A-EＡ-Ｅ]{1,5})(?![A-Za-z\u4e00-\u9fa5])")
_ANS_HEAD = re.compile(r"参考答案|答案及解析|答案与解析|^[\s　]*答案[\s　]*$", re.M)
# 章标题：`第二章 社会工作价值观与专业伦理`。千题斩那种「刷题册 + 解析册」两本的，
# 题号在**每章的每个题型里**各自从 1 编，所以键必须是三段：章 + 题型 + 题号。
_CHAP = re.compile(r"^[\s　]*第\s*([一二三四五六七八九十百]+|\d{1,2})\s*章")
# 解析册那种「题号 + 答案 + 一整段解析」挤在一行的：`10.D  考查社会工作专业知识…`
_ANS_LEAD = re.compile(r"^[\s　]*(\d{1,4})[、.．][\s　]*([A-EＡ-Ｅ]{1,5})[\s　]{2,}")
_JUNK = re.compile(r"官网|版权所有|www\.|支持电脑、手机|扫码|微信公众号")


def _half(s):
    return "".join(chr(ord(c) - 0xFEE0) if "Ａ" <= c <= "Ｚ" else c for c in s or "")


def _scan_answers(tail):
    """答案区 → {(章, 题型, 题号): 答案}。"""
    answers, akind, achap = {}, "single", ""
    for ln in tail.splitlines():
        if _JUNK.search(ln):
            continue
        mc = _CHAP.match(ln)
        if mc:
            achap, akind = mc.group(1), "single"
            continue
        ms = _SEC.match(ln)
        if ms:
            akind = next((v for k, v in _SEC_KIND.items() if ms.group(1).startswith(k)), "single")
            continue
        # **先试「一行多对」，再退回单对**。顺序反过来会出事：为解析册加的
        # _ANS_LEAD（`10.D  考查社会工作专业知识…`）也能匹配 `1.E    2.D   3.A`
        # 的开头，于是一行六个答案只取到第一个 —— 实测把一册的 93 条答案吃成 22 条，
        # 对齐率从 99% 掉到 23%，而且不报错。
        row = _ANS_ROW.findall(ln)
        if len(row) >= 2:
            pairs = row
        else:
            mm = _ANS.match(ln) or _ANS_BARE.match(ln) or _ANS_LEAD.match(ln)
            pairs = [(mm.group(1), mm.group(2))] if mm else []
        for no, raw in pairs:
            a = _half(raw).upper()
            a = "T" if a in ("√", "对") else ("F" if a in ("×", "错") else a)
            answers.setdefault((achap, akind, int(no)), a)
    return answers


def parse_bank(text, answer_text=None):
    """→ (题目列表, 体检单)。题干区和答案区**分开扫**，最后按（章, 题型, 题号）对齐。

    answer_text 给的是**另一本册子**的正文（千题斩那种「刷题册 + 解析册」分家的）。
    跨文件对齐是独立的一步，**不能默认按顺序就能配上** —— 两本的条数本来就不一样
    （刷题册 925 题、解析册 822 条），顺次配对等于整本答案错位。
    """
    if answer_text is not None:
        body, tail = text, answer_text
    else:
        m = _ANS_HEAD.search(text)
        body, tail = (text[:m.start()], text[m.start():]) if m else (text, "")

    # ---- 答案区：(章, 题型, 题号) → 答案 ----
    # **键必须三段**：题号在每章的每个题型里各自从 1 编。只按题号做键的话，
    # 多选第 1 题会拿到单选第 1 题的答案 —— 题数对得上、字母也在选项范围内，
    # 只是答案全错。真题库当年栽的就是这类错位。
    answers = _scan_answers(tail)

    # ---- 题干区 ----
    items, kind, cur, chap = [], "single", None, ""

    def close():
        if cur and cur["stem"]:
            items.append(cur)

    for raw in body.splitlines():
        ln = raw.rstrip()
        if not ln.strip() or _JUNK.search(ln):
            continue
        mc = _CHAP.match(ln)
        if mc:
            close()
            cur, chap, kind = None, mc.group(1), "single"
            continue
        ms = _SEC.match(ln)
        if ms:
            close()
            cur = None
            name = ms.group(1)
            kind = next((v for k, v in _SEC_KIND.items() if name.startswith(k)), "single")
            continue
        mo = _OPT.match(ln)
        # 选项行要在题干之后，且不能是「A 股」这种正文里的字母开头 —— 靠「已经开了一道题」
        # 和「选项按 A→B→C 顺序」两个条件卡住
        if mo and cur is not None and len(cur["options"]) < 5:
            L = _half(mo.group(1)).upper()
            want = "ABCDE"[len(cur["options"])]
            if L == want:
                cur["options"].append(R.norm(mo.group(2)))
                continue
        mq = _Q.match(ln)
        if mq:
            close()
            cur = {"no": int(mq.group(1)), "part": kind, "chap": chap,
                   "stem": R.norm(mq.group(2)), "options": []}
            continue
        if cur is not None:
            # 续行：还没出选项就接题干，出了就接最后一个选项
            if cur["options"]:
                cur["options"][-1] += R.norm(ln)
            else:
                cur["stem"] += R.norm(ln)
    close()

    # ---- 对齐 ----
    ok, bad = [], []
    for it in items:
        if it["part"] == "skip":
            continue
        a = answers.get((it.get("chap", ""), it["part"], it["no"]), "")
        if not a:
            # 章标题只在一侧出现时（题干区分了章、答案区没分，或反过来），三键会全部落空。
            # 退一步按（题型, 题号）找，但**只在全书唯一时才认** —— 有歧义就宁可判它没答案，
            # 那才是错位的高危区。加这条之前实测有一册从 99% 掉到 23%。
            cand = {k: v for k, v in answers.items()
                    if k[1] == it["part"] and k[2] == it["no"]}
            if len(cand) == 1:
                a = next(iter(cand.values()))
        n_opt = len(it["options"])
        if it["part"] == "judge":
            # 这批册子的判断题印成「A.正确 / B.错误」两个选项、答案给 A/B，
            # 而不是 √/×。按**选项文字**折成 T/F —— 靠字母顺序猜会在
            # 「A.错误 / B.正确」这种反着印的册子上全判反。
            if a in ("T", "F"):
                it["answer"] = a
            elif len(a) == 1 and a in "AB" and len(it["options"]) == 2:
                pick = it["options"]["AB".index(a)]
                it["answer"] = "T" if ("正确" in pick or pick.strip() in ("对", "√")) else \
                    ("F" if ("错误" in pick or pick.strip() in ("错", "×")) else "")
            if it.get("answer") in ("T", "F"):
                it["options"] = []          # 判断题不带选项，走两键作答态
                ok.append(it)
            else:
                bad.append((it, "判断题的答案折不成 √/×（答案=%r 选项=%r）"
                            % (a, it["options"][:2])))
            continue
        if n_opt < 2:
            bad.append((it, "选项少于 2 个"))
        elif not a:
            bad.append((it, "答案区的%s%s里没有第 %d 题"
                        % (("第%s章 " % it["chap"]) if it.get("chap") else "", it["part"], it["no"])))
        elif any(c not in "ABCDE"[:n_opt] for c in a):
            # 三个选项的题答案是 D —— 多半是答案区错位了，**这种题一道都不能要**
            bad.append((it, "答案 %s 超出本题 %d 个选项的范围" % (a, n_opt)))
        elif it["part"] == "single" and len(a) != 1:
            bad.append((it, "单选题答案有 %d 个字母" % len(a)))
        else:
            it["answer"] = a
            ok.append(it)
    live = [i for i in items if i["part"] != "skip"]
    rate = len(ok) / len(live) if live else 0.0
    return ok, {"n_all": len(live), "n_ok": len(ok), "n_ans": len(answers),
                "n_skip": len(items) - len(live),
                "rate": rate, "bad": bad,
                "kinds": {k: sum(1 for i in ok if i["part"] == k)
                          for k in ("single", "multi", "judge")}}


def find_banks(con):
    rows = con.execute(
        "SELECT id,name,folder,stored_name FROM drive_files WHERE folder LIKE ? "
        "AND is_dir=0 AND deleted_at IS NULL AND ext='.pdf' ORDER BY folder,name",
        (ROOT + "%",)).fetchall()
    out, seen = [], set()
    for r in rows:
        if any(k in r["folder"] for k in SKIP_DIR) or any(k in r["name"] for k in SKIP_NAME):
            continue
        if not any(k in r["name"] for k in TAKE_NAME) or any(k in r["name"] for k in SKIP_NAME2):
            continue
        if r["name"] in seen:
            continue
        path = None
        for d in os.listdir(os.path.join(UPLOADS, "drive")):
            cand = os.path.join(UPLOADS, "drive", d, r["stored_name"])
            if os.path.exists(cand):
                path = cand
                break
        if not path:
            continue
        seen.add(r["name"])
        out.append({"file_id": r["id"], "name": r["name"], "folder": r["folder"], "path": path})
    return out


def save(con, bank, items):
    row = con.execute("SELECT id FROM sq_papers WHERE file_id=?", (bank["file_id"],)).fetchone()
    name = bank["name"].rsplit(".", 1)[0]
    if row:
        pid = row["id"]
        con.execute("DELETE FROM sq_questions WHERE paper_id=?", (pid,))
    else:
        cur = con.execute(
            "INSERT INTO sq_papers(file_id,name,folder,ext,region,year,kind,total,status) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (bank["file_id"], name, bank["folder"], ".pdf", "通用", 0, PAPER_KIND, 0, "ok"))
        pid = cur.lastrowid
    fixed = qtype_by_folder(bank["folder"], bank["name"])
    for i, it in enumerate(items, 1):
        stem = it["stem"]
        con.execute(
            "INSERT INTO sq_questions(paper_id,seq,part,part_seq,qtype,stem,options,answer,"
            "explain,score,verify,verify_note,qhash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, i, it["part"], it["no"], fixed or qtype_of(stem, it["options"]), stem,
             json.dumps(it["options"], ensure_ascii=False), it["answer"], "", 1.0,
             # 练习册的答案是**原册印着的**，不是回忆版：不过 AI 校对闸门。
             # 闸门是用来查回忆版真题的；拿它审一百多份正规练习册，钱和时间都不划算，
             # 而且模型对社工细则的把握还不如册子本身。对齐率就是这里的质量闸。
             "ok", json.dumps({"why": "练习册原册答案，按题号对齐入库"}, ensure_ascii=False),
             hashlib.sha1(R.qhash_text(stem).encode("utf-8")).hexdigest()[:16]))
    con.execute("UPDATE sq_papers SET n_obj=?, n_sub=0, n_doubt=0 WHERE id=?", (len(items), pid))
    return pid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--min", type=float, default=0.85, help="对齐率低于它就整册跳过")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    banks = find_banks(con)
    if a.limit:
        banks = banks[:a.limit]
    print("候选 %d 份（已排除行测类）\n" % len(banks))

    took = skipped = total = 0
    kinds = {"single": 0, "multi": 0, "judge": 0}
    for b in banks:
        text = R.pdf_text(b["path"])
        if len(text.strip()) < 500:
            continue
        items, rep = parse_bank(text)
        if rep["n_all"] < 5:
            continue
        flag = "✓" if rep["rate"] >= a.min else "✗"
        if rep["rate"] >= a.min:
            took += 1
            total += len(items)
            for k in kinds:
                kinds[k] += rep["kinds"][k]
            if not a.scan:
                save(con, b, items)
        else:
            skipped += 1
        print("%s %-44s 题 %3d 答案 %3d 可用 %3d 对齐 %3.0f%% %s"
              % (flag, b["name"][:44], rep["n_all"], rep["n_ans"], rep["n_ok"],
                 rep["rate"] * 100, "" if rep["rate"] >= a.min else "← 整册跳过"))
        if a.verbose and rep["bad"]:
            for it, why in rep["bad"][:3]:
                print("      ! 第%d题 %s ← %s" % (it["no"], why, it["stem"][:32]))
    if not a.scan:
        con.commit()
    print("\n收下 %d 份、跳过 %d 份；共 %d 道（单选 %d / 多选 %d / 判断 %d）%s"
          % (took, skipped, total, kinds["single"], kinds["multi"], kinds["judge"],
             "（scan 模式，未写库）" if a.scan else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
