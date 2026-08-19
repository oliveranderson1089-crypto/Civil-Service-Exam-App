#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""社区专职工作者真题入库：把云盘「内江资中县社区备考资料」下的整卷解析进 sq_* 表。

和 ingest_real.py 的分工：那份处理**行测**卷（只有单选、要跨卷去重），这份处理
**社区**卷（一张卷子五种题型、单选/多选/判断/案例/公文，只有两套、不需要去重）。

这份卷子有两件事和行测卷不一样，代码里到处都在迁就它们：

  ① **答案本身可能是错的。** 源卷是网传回忆版，抽查就有好几处答案与选项对不上
     （「小组工作社会目标模式主要应用于」标注 D 职业规划，选项 A 才是对的）。
     所以解析只负责「原样抠出来」，对错交给 verify_shequ.py 的校对闸门，
     入库时 verify='' —— 前端把空值一律当存疑看待，不发给人做。

  ② **五种题型五种形状。** 单选/多选有 A-D 选项、判断题没有选项、案例和公文
     连答案都是整段文字。所以每条都带 part，下游按 part 分派，不按题型名猜。

用法：
    python3 ingest_shequ.py --scan          # 只解析并打印体检单，不写库
    python3 ingest_shequ.py --scan -v       # 连每道题的题干头都打出来，用于人工核对
    python3 ingest_shequ.py                 # 写库（同一份卷子重跑=覆盖，靠 file_id）
    python3 ingest_shequ.py --reparse       # 同上；语义一样，留着和真题库的口径对齐
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

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))
ROOT = "内江资中县社区备考资料"

# 卷面结构。分值和题数写死在这儿是**故意的**：它是一把尺子，解析出来对不上就报警。
# 两套真题（2023 公开选聘、2025 招聘）卷面完全一致，不是巧合——这是该考试的固定格式。
BLUEPRINT = [
    ("single",  "单项选择题", 40, 1.0),
    ("multi",   "多项选择题", 10, 1.0),
    ("judge",   "判断题",     10, 1.0),
    ("case",    "案例分析题",  2, 12.5),   # 实际是 12 + 13，逐题解析时按题面给的分覆盖
    ("gongwen", "公文写作",    1, 15.0),
]
PART_NAME = {p: n for p, n, _, _ in BLUEPRINT}

# 章节标题：`一、单项选择题（每题 1 分，共 40 分）`。两套卷的标题措辞略有出入
# （2023 那套多一句「多选、少选、错选均不得分」），所以只锚定题型名本身。
_SEC_HEAD = re.compile(
    r"^[\s　]*[一二三四五六][、.．][\s　]*"
    r"(单项选择题|多项选择题|判断题|案例分析题|公文写作)", re.M)
_SEC_KEY = {"单项选择题": "single", "多项选择题": "multi", "判断题": "judge",
            "案例分析题": "case", "公文写作": "gongwen"}
# 章节标题只锚到题型名，后面那句 `（每题 1 分，共 40 分）` 还留在正文里，
# 不剥掉就会粘到**每一节第一题**的题干头上。单独一条正则而不是并进 _SEC_HEAD，
# 是因为两套卷这句话的写法不一样（2023 判断题那节还写着「对打√，错打 ×」），
# 并进去等于要求它必须存在，缺了反而整节切不出来。
_SEC_NOTE = re.compile(r"^[\s　]*[（(][^（）()]{0,60}[）)]")
# 立成检查项：题干开头若还挂着带「分」的括号，就是这段没剥干净。
_STUCK_NOTE = re.compile(r"^[（(][^（）()]{0,60}分[^（）()]{0,30}[）)]")

# 客观题的答案锚点。**必须允许多个字母**——多选题是 `答案：ABCD`。
_ANS = re.compile(r"答案[：:][\s　]*([A-DＡ-Ｄ]{1,4})")
# 判断题的答案是内嵌的：`1. 居民委员会是基层国家行政机关。（×） 解析：…`
_TF = re.compile(r"[（(][\s　]*([√×✓✗对错])[\s　]*[）)]")
# 题号。**按序号剥，不按长相剥**——「长得像题号就剥」这条路两头都出错：
#   · 分隔符写成可选，`2025 年资中社区招聘…` 会被当成题号 20 剥成 `25 年…`
#   · 加了「后面不许跟数字」的保护，`30.2023 年资中社区招聘…` 又剥不掉
# 而这一题应该是第几题，是我们自己数出来的，拿它当锚才准。
_LEAD_NO = re.compile(r"^[\s　]*(\d{1,2})[\s　]*[.、．)）][\s　]*")
# 立成检查项：正常题干不会以「两位数+年」开头，出现了就是上面这个坑又犯了。
_EATEN_YEAR = re.compile(r"^\d{2}[\s　]*年")
_CASE_HEAD = re.compile(r"^[\s　]*案例[\s　]*([一二三四1-4])[\s　]*[（(](\d+)[\s　]*分[）)]", re.M)
_REF = re.compile(r"^[\s　]*参考(?:答案|范文)[：:]?[\s　]*$", re.M)

# 考点大类。**顺序即优先级**：一道题命中多类时取先命中的，
# 所以「资中县情」必须排最前 —— 「2025 年资中面向社会招聘…年龄上限」既像县情也像社区知识，
# 但它的价值在于「这是本地题」，归错类就进不了资中专项。
QTYPE_RULES = [
    ("资中县情", ("资中", "内江", "重龙", "水南镇", "罗泉", "县情")),
    ("党建党务", ("党组织", "党支部", "党员", "党章", "三会一课", "主题党日", "党建", "党委",
                  "党工委", "党课", "党内")),
    ("公文写作", ("公文", "请示", "报告", "通知", "通告", "批复", "纪要", "上行文", "下行文",
                  "文种", "行文", "版头", "主送")),
    ("法律法规", ("民法典", "组织法", "条例", "暂行办法", "法律", "违法", "侵权", "合同",
                  "治安管理", "信访", "救助", "抚恤", "优抚", "监护", "赔偿", "表决比例",
                  "冷静期", "劳动")),
    ("应急安全", ("应急", "突发", "消防", "火灾", "119", "隐患", "安全", "诈骗", "燃气",
                  "洪涝", "灾害")),
    ("社会工作", ("社会工作", "社工", "个案", "小组工作", "社区工作模式", "介入", "预估",
                  "接案", "结案", "同理", "强化", "服务对象", "督导", "地区发展模式",
                  "社会策划", "社区照顾")),
    ("时政理论", ("城镇化", "一老一小", "智慧社区", "现代化", "共同富裕", "文明实践")),
]
QTYPE_FALLBACK = "社区知识"


def strip_seq(stem, want):
    """剥掉题干头上的题号，但只在它正好等于「这一题应有的序号」时才剥。
       对不上就原样留着——宁可留个多余的数字，也不要把题干的第一个词吃掉。"""
    m = _LEAD_NO.match(stem)
    if m and int(m.group(1)) == want:
        return stem[m.end():]
    return stem.lstrip()


def qtype_of(stem, options=()):
    """给一道题贴考点大类。命中不了就落到「社区知识」——它是这门考试的底色，
       不是「未分类」的委婉说法。"""
    text = stem + " " + " ".join(options or ())
    for name, kws in QTYPE_RULES:
        if any(k in text for k in kws):
            return name
    return QTYPE_FALLBACK


# ---------------------------------------------------------------- 切章节
def split_sections(text):
    """返回 [(part, 正文), ...]，按卷面顺序。找不到的题型不出现在结果里。"""
    hits = list(_SEC_HEAD.finditer(text))
    out = []
    for i, m in enumerate(hits):
        part = _SEC_KEY[m.group(1)]
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        out.append((part, _SEC_NOTE.sub("", text[m.end():end], count=1)))
    return out


# ---------------------------------------------------------------- 单选 / 多选
def parse_choice(body, part):
    """按 `答案：X` 把整段切成一道道题。

    为什么以答案为锚而不是以题号为锚：**2025 那套卷的单选题根本没有题号**
    （2023 那套有）。答案行是两套卷唯一都有、且一题一个的稳定标记。
    """
    # **先把空行压掉**。这份 PDF 是每行之间都插一个空行的排版，而
    # realbank._trim_tail 把「空行」当段落结束，会从那儿把 D 选项截断 ——
    # 「D. 宣传方\n\n式」变成「宣传方」，题数照样对、体检单全绿，只有选项少了两个字。
    # 对行测卷那条规则是对的，对这份卷子不是，所以在进 _split_options 之前就压掉。
    body = re.sub(r"\n[ \t\u3000]*\n", "\n", body)
    items, pos = [], 0
    for m in _ANS.finditer(body):
        block = body[pos:m.start()]
        pos = m.end()
        ans = "".join(chr(ord(c) - 0xFEE0) if "Ａ" <= c <= "Ｄ" else c
                      for c in m.group(1))
        stem, opts = R._split_options(block)
        stem = strip_seq(R.norm(stem), len(items) + 1)
        # 题干和选项里夹着的换行都是 PDF 排版造成的，不是语义换行 ——
        # 选项本来就是一行一个短语，留着换行会让「宣传方\n式」这样显示出来。
        flat = lambda x: re.sub(r"\s*\n\s*", "", x)          # noqa: E731
        stem = flat(stem)
        opts = [flat(o) for o in opts]
        if not stem:
            continue
        # 覆盖率：抠出来的题干+选项，应当覆盖原文块的绝大部分字。
        # 少太多就是有文字被吃掉了（D 选项被截断就是这么露出来的）。
        # 只数汉字与数字，忽略空白和 A./B. 这类标记。
        keep = re.sub(r"[^\u4e00-\u9fa5\d]", "", stem + "".join(opts))
        raw = re.sub(r"[^\u4e00-\u9fa5\d]", "", re.sub(r"^\s*\d{1,2}\s*[.、．)）]", "", block))
        lost = len(raw) - len(keep)

        bad = ""
        if _STUCK_NOTE.match(stem):
            bad = "题干头上粘着章节分值说明"
        elif _EATEN_YEAR.match(stem):
            bad = "题干开头的年份被当成题号剥掉了"
        elif len(opts) < 4:
            bad = "选项没抠全（%d 个）" % len(opts)
        elif lost > 2:
            bad = "解析后少了 %d 个字（多半是选项被截断）" % lost
        elif part == "single" and len(ans) != 1:
            bad = "单选题答案有 %d 个字母" % len(ans)
        elif any(c not in "ABCD" for c in ans):
            bad = "答案含非法字母 %s" % ans
        items.append({"part": part, "stem": stem, "options": opts,
                      "answer": ans, "explain": "", "bad": bad})
    return items


# ---------------------------------------------------------------- 判断
def parse_judge(body):
    """判断题的答案内嵌在题干里：`…。（×） 解析：基层群众性自治组织`。

    一行一题，但 PDF 会把长题折行，所以先按「含 √/× 标记」找到题尾，
    再把上一题尾到这一题尾之间的所有文字并成一题。
    """
    lines = [ln for ln in body.split("\n")]
    items, buf = [], []
    for ln in lines:
        buf.append(ln)
        m = _TF.search(ln)
        if not m:
            continue
        chunk = R.norm(" ".join(buf))
        buf = []
        mark = m.group(1)
        ans = "T" if mark in "√✓对" else "F"
        # 切掉答案标记本身，再把「解析：…」摘出去
        chunk = _TF.sub("", chunk, count=1)
        explain = ""
        if "解析" in chunk:
            head, _, tail = chunk.partition("解析")
            chunk, explain = head, tail.lstrip("：: ").strip()
        stem = re.sub(r"\s*\n\s*", "", strip_seq(chunk, len(items) + 1)).strip()
        bad = ("题干头上粘着章节分值说明" if _STUCK_NOTE.match(stem)
               else "题干开头的年份被当成题号剥掉了" if _EATEN_YEAR.match(stem)
               else "" if len(stem) >= 6 else "题干过短（%d 字）" % len(stem))
        items.append({"part": "judge", "stem": stem, "options": [],
                      "answer": ans, "explain": explain, "bad": bad})
    return items


# ---------------------------------------------------------------- 案例 / 公文
def _subjective(body, part, default_score):
    """主观题：题面到「参考答案 / 参考范文」为止，后面整段都是答案。

    案例题一节里有两道（案例 1 / 案例 2），公文一节只有一道。
    """
    heads = list(_CASE_HEAD.finditer(body)) if part == "case" else []
    if not heads:                       # 公文，或案例没打「案例 N（M 分）」的标
        segs = [(body, default_score)]
    else:
        segs = []
        for i, h in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
            segs.append((body[h.end():end], float(h.group(2))))
    items = []
    for seg, score in segs:
        ref = _REF.search(seg)
        stem = seg[:ref.start()] if ref else seg
        answer = seg[ref.end():] if ref else ""
        stem = re.sub(r"\n{2,}", "\n", R.norm(stem)).strip()
        answer = re.sub(r"\n{2,}", "\n", R.norm(answer)).strip()
        bad = ""
        if _STUCK_NOTE.match(stem):
            bad = "题面头上粘着章节分值说明"
        elif not answer:
            bad = "没找到参考答案锚点"
        elif len(stem) < 20:
            bad = "题面过短（%d 字）" % len(stem)
        items.append({"part": part, "stem": stem, "options": [],
                      "answer": answer, "explain": "", "score": score, "bad": bad})
    return items


# ---------------------------------------------------------------- 一份卷子
def parse_paper(text):
    """返回 (题目列表, 体检单)。体检单是给人看的，别只看题数。"""
    got = {}
    for part, body in split_sections(text):
        if part in ("single", "multi"):
            got[part] = parse_choice(body, part)
        elif part == "judge":
            got[part] = parse_judge(body)
        else:
            want = dict((p, sc) for p, _, _, sc in BLUEPRINT)
            got[part] = _subjective(body, part, want[part])

    items, report = [], []
    seq = 0
    for part, name, want_n, want_sc in BLUEPRINT:
        rows = got.get(part, [])
        for i, it in enumerate(rows, 1):
            seq += 1
            it["seq"] = seq
            it["part_seq"] = i
            it.setdefault("score", want_sc)
            it["qtype"] = qtype_of(it["stem"], it.get("options"))
            it["qhash"] = hashlib.sha1(
                R.qhash_text(it["stem"]).encode("utf-8")).hexdigest()[:16]
            items.append(it)
        nbad = sum(1 for r in rows if r["bad"])
        report.append({"part": part, "name": name, "want": want_n,
                       "got": len(rows), "bad": nbad,
                       "ok": len(rows) == want_n and nbad == 0})
    return items, report


# ---------------------------------------------------------------- 找卷子
def find_papers(con):
    """云盘里哪些是「整卷真题」。P0 只认资中那两套 —— 模拟卷和押题卷等 P1 再说，
       它们大多是扫描件，得先过 OCR。"""
    rows = con.execute(
        "SELECT id, name, folder, ext, stored_name FROM drive_files "
        "WHERE folder LIKE ? AND is_dir=0 AND deleted_at IS NULL "
        "  AND name LIKE '%真题%' AND ext='.pdf' ORDER BY name",
        (ROOT + "/%",)).fetchall()
    out = []
    for r in rows:
        path = None
        for d in os.listdir(os.path.join(UPLOADS, "drive")):
            cand = os.path.join(UPLOADS, "drive", d, r["stored_name"])
            if os.path.exists(cand):
                path = cand
                break
        if not path:
            print("  ! 文件不在盘上：", r["name"])
            continue
        ym = re.search(r"(20\d{2})", r["name"])
        out.append({"file_id": r["id"], "name": r["name"], "folder": r["folder"],
                    "ext": r["ext"], "path": path,
                    "year": int(ym.group(1)) if ym else 0,
                    "kind": "公开选聘" if "选聘" in r["name"] else "招聘",
                    "region": "资中县" if "资中" in r["name"] else "通用"})
    return out


# ---------------------------------------------------------------- 写库
def save(con, paper, items, reparse=False):
    cur = con.execute("SELECT id FROM sq_papers WHERE file_id=?", (paper["file_id"],))
    row = cur.fetchone()
    n_obj = sum(1 for it in items if it["part"] in ("single", "multi", "judge"))
    n_sub = len(items) - n_obj
    n_bad = sum(1 for it in items if it["bad"])
    fields = (paper["name"], paper["folder"], paper["ext"], paper["region"],
              paper["year"], paper["kind"], n_obj, n_sub, n_bad,
              "ok" if not n_bad else "partial")
    if row:
        pid = row["id"]
        con.execute(
            "UPDATE sq_papers SET name=?,folder=?,ext=?,region=?,year=?,kind=?,"
            "n_obj=?,n_sub=?,n_bad=?,status=? WHERE id=?", fields + (pid,))
        # 重跑=整卷重来。**先删再插**，不做增量合并：卷子只有一份来源，
        # 增量合并只会让「上一版解析残留的题」神不知鬼不觉地留在库里。
        #
        # 但校对结果（verify / verify_note）是**花了 37 分钟、两家模型跑出来的**，
        # 还带着人工裁决，不能跟着解析一起丢。--reparse 就是为这个：
        # 先把旧的按 seq 记下来，题面没变的原样搬回去，**变了的重置成未校对**
        # —— 内容改了却继续沿用旧结论，等于拿 A 题的核验给 B 题背书。
        old = {}
        if reparse:
            for r in con.execute("SELECT * FROM sq_questions WHERE paper_id=?", (pid,)):
                old[r["seq"]] = dict(r)
        con.execute("DELETE FROM sq_questions WHERE paper_id=?", (pid,))
    else:
        old = {}
        cur = con.execute(
            "INSERT INTO sq_papers(file_id,name,folder,ext,region,year,kind,"
            "n_obj,n_sub,n_bad,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (paper["file_id"],) + fields)
        pid = cur.lastrowid
    kept = reset = 0
    for it in items:
        opts = json.dumps(it.get("options") or [], ensure_ascii=False)
        o = old.get(it["seq"])
        same = bool(o) and o["stem"] == it["stem"] and (o["options"] or "[]") == opts \
            and o["answer"] == it["answer"]
        verify = "bad" if it["bad"] else ""
        note = json.dumps({"parse": it["bad"]}, ensure_ascii=False) if it["bad"] else None
        explain = it.get("explain", "")
        if same:
            verify, note = o["verify"], o["verify_note"]
            # 人工在解析后面补过话（比如「按 2026 公告这题的答案已不适用」），
            # 那份补充比重新解析出来的更值钱，别覆盖掉。
            if (o["explain"] or "").startswith(explain) and len(o["explain"] or "") > len(explain):
                explain = o["explain"]
            kept += 1
        elif o:
            reset += 1
        con.execute(
            "INSERT INTO sq_questions(paper_id,seq,part,part_seq,qtype,stem,options,"
            "answer,explain,score,verify,verify_note,qhash) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, it["seq"], it["part"], it["part_seq"], it["qtype"], it["stem"], opts,
             it["answer"], explain, it.get("score", 1.0), verify, note, it["qhash"]))
    con.execute("UPDATE sq_papers SET n_doubt=(SELECT COUNT(*) FROM sq_questions q "
                "WHERE q.paper_id=? AND q.part IN ('single','multi','judge') "
                "AND q.verify<>'ok') WHERE id=?", (pid, pid))
    return pid, kept, reset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="只解析并打印体检单，不写库")
    ap.add_argument("--reparse", action="store_true", help="重新解析并覆盖（默认行为）")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印每道题的题干头")
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    papers = find_papers(con)
    if not papers:
        print("云盘里没找到社区真题卷（找的是 %s/**/*真题*.pdf）" % ROOT)
        return 1

    total_bad = 0
    skipped = []
    for p in papers:
        text = R.pdf_text(p["path"])
        # 没有文字层的扫描件在这儿就拦掉，不要让它走完解析再报「五项全 ✗」——
        # 那样体检单会被一堆假失败刷屏，真正解析坏了的卷子反而看不见。
        # 判据用「取不到字」而不是「解析不出题」：前者是文件的事实，后者是规则的结论。
        if len(text.strip()) < 500:
            skipped.append((p["name"], "无文字层（取到 %d 字），待 OCR" % len(text.strip())))
            continue
        if not split_sections(text):
            skipped.append((p["name"], "没有卷面章节标题，不是整卷真题"))
            continue
        items, report = parse_paper(text)
        print("\n=== %s ===" % p["name"])
        print("    %d 年 · %s · %s · 原文 %d 字" % (p["year"], p["region"], p["kind"], len(text)))
        for r in report:
            flag = "✓" if r["ok"] else "✗"
            note = "" if not r["bad"] else "，其中 %d 道有问题" % r["bad"]
            print("    %s %-6s 解析 %2d / 应有 %2d%s" % (flag, r["name"], r["got"], r["want"], note))
        bad = [it for it in items if it["bad"]]
        total_bad += len(bad)
        for it in bad:
            print("      ! 第 %d 题（%s 第 %d）%s ← %s"
                  % (it["seq"], PART_NAME[it["part"]], it["part_seq"], it["bad"], it["stem"][:34]))
        kinds = {}
        for it in items:
            kinds[it["qtype"]] = kinds.get(it["qtype"], 0) + 1
        print("    考点分布：" + "　".join("%s %d" % kv for kv in
                                          sorted(kinds.items(), key=lambda x: -x[1])))
        if a.verbose:
            for it in items:
                print("      %2d [%-7s] %s" % (it["seq"], it["part"], it["stem"][:46]))
        if not a.scan:
            _, kept, reset = save(con, p, items, reparse=True)
            print("    → 已写入 sq_questions %d 条（沿用旧校对 %d 条，内容变了重置 %d 条）"
                  % (len(items), kept, reset))
    if not a.scan:
        con.commit()
    if skipped:
        print("\n跳过 %d 份（不是整卷、或还取不出字）：" % len(skipped))
        for name, why in skipped:
            print("    · %s —— %s" % (name, why))
    print("\n合计有问题的题：%d 道%s" % (total_bad, "（scan 模式，未写库）" if a.scan else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
