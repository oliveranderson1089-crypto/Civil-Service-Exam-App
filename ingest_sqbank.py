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

# 哪些册子是**整卷**、哪些只是题册。分开是因为两者的用法根本不同：
# 整卷要能从头做到尾、有总倒计时、出一张成绩单；题册只喂「专项练」抽题。
# 判据是文件名里的原话，不是我们的猜测 —— 云盘那个文件夹就叫
# 「7.2026社区工作者模拟试题（共6套）」，卷名里写着「模拟试题」「押题试卷」。
MOCK_KIND = (("模拟试题", "模拟"), ("押题试卷", "押题"))


def kind_of(name):
    """这份资料按哪种 kind 入库。认不出来一律当题册 —— 宁可少认一份整卷，
       也不要把一本时政题库摆成「一套模拟卷」骗人去当整卷做。"""
    for key, kind in MOCK_KIND:
        if key in (name or ""):
            return kind
    return PAPER_KIND

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
# 解析册的写法：`56. C。公众号【…】解析，…` —— 答案紧跟题号，后面接一整段解析。
# 判断题的 √ 被 OCR 认成 Y 或 V（`51. Y 。解析:`），一并折成 T。
# 字符集里**必须含 X**：判断题的 × 被 OCR 认成大写 X（`1. X。解析:`）。
# 少了它，_OCR_TF 里的 X→F 那条映射永远轮不到执行 —— 87 道判断题就是这么丢的。
_ANS_EXP = re.compile(r"^[\s　]*(\d{1,4})[\s　]*[.、．][\s　]*([A-EＡ-ＥXYV√×]{1,4})[\s　]*[。．,，:：]")
_OCR_TF = {"Y": "T", "V": "T", "√": "T", "×": "F", "X": "F"}
# 「模拟试题」「押题试卷」那一批的写法：`1.【答案】A` / `94【答案】C。解析:`。
# 题号后面**可以没有点**（`94【答案】`），所以点是可选的；答案字母后面不许紧跟汉字，
# 挡住解析正文里的「【答案】B 项正确」那种引用。
_ANS_MARK = re.compile(r"^[\s　]*(\d{1,4})[\s　]*[、.．]?[\s　]*[【\[][\s　]*答案[\s　]*[】\]]"
                       r"[\s　]*[:：]?[\s　]*([A-EＡ-ＥXYV√×对错]{1,5})(?![A-Za-z\u4e00-\u9fa5])")
_ANS_HEAD = re.compile(r"参考答案|答案及解析|答案与解析|^[\s　]*答案[\s　]*$", re.M)
# 卷末没有「参考答案」大标题、答案却是逐题标着【答案】的（模拟试题第 3 套就是）：
# 拿**第一条 `N【答案】X`** 当答案区的起点。少了这条退路，整册答案一条都扫不到，
# 而且报出来是「答案 0 条」，看着像题册本身没答案 —— 实际上是我们没找到门。
_ANS_MARK_HEAD = re.compile(r"(?m)^[\s　]*\d{1,4}[\s　]*[、.．]?[\s　]*[【\[][\s　]*答案[\s　]*[】\]]")
# 章标题：`第二章 社会工作价值观与专业伦理`。千题斩那种「刷题册 + 解析册」两本的，
# 题号在**每章的每个题型里**各自从 1 编，所以键必须是三段：章 + 题型 + 题号。
_CHAP = re.compile(r"^[\s　]*第\s*([一二三四五六七八九十百]+|\d{1,2})\s*章")
# 解析册那种「题号 + 答案 + 一整段解析」挤在一行的：`10.D  考查社会工作专业知识…`
_ANS_LEAD = re.compile(r"^[\s　]*(\d{1,4})[、.．][\s　]*([A-EＡ-Ｅ]{1,5})[\s　]{2,}")
_JUNK = re.compile(r"官网|版权所有|www\.|支持电脑、手机|扫码|微信公众号")


def _half(s):
    return "".join(chr(ord(c) - 0xFEE0) if "Ａ" <= c <= "Ｚ" else c for c in s or "")


def _kind_by_shape(answers):
    """一段答案是什么题型 —— 按**答案本身长什么样**判，不看标题。

    只在标题缺失时才用得上（见 _scan_answers 里「题号回到 1」那条）。
    判据：过半是 T/F 就是判断题，过半有两个以上字母就是多选，否则单选。
    """
    if not answers:
        return "single"
    tf = sum(1 for a in answers if a in ("T", "F"))
    many = sum(1 for a in answers if len(a) > 1 and a not in ("T", "F"))
    if tf * 2 > len(answers):
        return "judge"
    return "multi" if many * 2 > len(answers) else "single"


def _scan_answers(tail):
    """答案区 → {(章, 题型, 题号): 答案}。

    题型分段有两个来源，**标题优先、题号回落**：

      · 正常情况看「二、多项选择题」这种小标题；
      · 标题被页脚吃掉时（扫描件很常见），看**题号有没有回到 1** ——
        单选答到 60 之后又冒出一个「1.」，那就是换段了。不加这条退路的话，
        多选的 1~40 会去撞单选已经占了的 1~40 号，setdefault 让先来的赢，
        于是**整段多选题一条答案都取不到**、还报成「答案区里没有这道题」。
        实测「模拟试题第 1 套」就丢了 32 道多选。

    回落判据卡得很死：**新号 ≤ 2 且上一个号 ≥ 10** 才算换段。松一点就会被
    OCR 认错的题号骗到 —— 同一册里「28. D」被认成「98. D」，下一条 29 比 98 小，
    按「只要变小就换段」的写法会在这儿凭空劈出一段来。
    """
    answers, akind, achap = {}, "single", ""
    seg, last_no = [], 0          # 当前段收了哪些答案 / 上一个题号
    for ln in tail.splitlines():
        if _JUNK.search(ln):
            continue
        mc = _CHAP.match(ln)
        if mc:
            achap, akind = mc.group(1), "single"
            seg, last_no = [], 0
            continue
        ms = _SEC.match(ln)
        if ms:
            akind = next((v for k, v in _SEC_KIND.items() if ms.group(1).startswith(k)), "single")
            seg, last_no = [], 0
            continue
        # **先试「一行多对」，再退回单对**。顺序反过来会出事：为解析册加的
        # _ANS_LEAD（`10.D  考查社会工作专业知识…`）也能匹配 `1.E    2.D   3.A`
        # 的开头，于是一行六个答案只取到第一个 —— 实测把一册的 93 条答案吃成 22 条，
        # 对齐率从 99% 掉到 23%，而且不报错。
        row = _ANS_ROW.findall(ln)
        if len(row) >= 2:
            pairs = row
        else:
            mm = (_ANS.match(ln) or _ANS_MARK.match(ln) or _ANS_BARE.match(ln)
                  or _ANS_LEAD.match(ln) or _ANS_EXP.match(ln))
            pairs = [(mm.group(1), mm.group(2))] if mm else []
        for no, raw in pairs:
            a = _half(raw).upper()
            # OCR 把判断题的 √ 认成 Y / V，先折回来再判
            a = _OCR_TF.get(a, a) if len(a) == 1 else a
            a = "T" if a in ("√", "对") else ("F" if a in ("×", "错") else a)
            no = int(no)
            if no <= 2 and last_no >= 10:
                # 题号回到 1 = 换了一个题型段，而标题没印出来（或被页脚吃了）。
                # 新段的题型按**这一段答案的形状**判，而且要**攒够几条再判** ——
                # 只看第一条会被 OCR 的单条错认带偏（第一条恰好认成一个字母，
                # 整段多选就会被判成单选，然后整段答案对不上）。
                akind, seg = "?", []
            last_no = no
            if akind == "?":
                seg.append((no, a))
                if len(seg) >= 3:
                    akind = _kind_by_shape([x[1] for x in seg])
                    for n2, a2 in seg:
                        answers.setdefault((achap, akind, n2), a2)
                    seg = []
                continue
            answers.setdefault((achap, akind, no), a)
    if seg:                                # 整段不足 3 条就到头了，按形状收尾
        akind = _kind_by_shape([x[1] for x in seg])
        for n2, a2 in seg:
            answers.setdefault((achap, akind, n2), a2)
    return answers


# 答案**紧跟在每道题后面**的写法（时政押题那几份就是）：
#     1.推动…必须坚持的…分别是()
#     A.… B.… C.… D.…
#     答案： D
# 这种没有卷末的「参考答案」区，得按题切、答案就地取。
_ANS_INLINE = re.compile(r"^[\s　]*(?:正确)?答案[：:\s]*([A-EＡ-Ｅ√×对错]{1,5})[\s　]*$", re.M)
# `【答案】B。A 项错误，…` —— 答案后面直接跟着整段解析。**必须要求答案字母后面
# 是句号/顿号/空白**，否则「【答案】B」和正文里的「B 项正确」分不开。
_ANS_BRACKET = re.compile(r"^[\s　]*[【\[]答案[】\]][\s　]*([A-EＡ-Ｅ√×对错]{1,5})"
                          r"(?=[。．，,、\s　]|$)", re.M)


_LEAD_PUNCT = re.compile(r"^[\s　]*[，,。、．.：:；;）)]+[\s　]*")


def repair_options(items):
    """把**混排**的选项切开。原地改 items。

    两种混排，来源不同、处理位置也不同：
      · 四个选项挤在同一行（`A.晋文公 B.楚庄王 C.齐桓公 D.秦穆公`）——
        上面的逐行扫只会抠出一个选项 A，剩下三个粘在 A 的正文里；
      · 选项混在题干那一行里（`2、社会工作是一种（）。 A 自发助人活动`）。
    两种都交给现成的 realbank._split_options 再切一次 —— 那个函数就是为「挤一行」写的。

    **两个解析器都要用这一份。** 原先只有 parse_inline 有这段，parse_bank 没有，
    于是「模拟试题第 3 套」那种单空格分隔的一行四选项整册都被判成「选项少于 2 个」——
    83 道题只活下来 20 道，而报出来的理由看着像题册本身残缺。
    """
    for it in items:
        # 选项开头的**残标点**：原卷印的是「A、澄清」，OCR 认成「A，澄清」——
        # `、．.` 在分隔符里、`，：)` 不在，于是逗号被当成正文留了下来，
        # 界面上就是「，澄清」。实测模拟卷里 16% 的选项带着这个尾巴。
        # 削在这儿而不是放宽 _OPT 的分隔符：那条正则同时管着「选项行认不认」，
        # 放宽它等于让更多正文行有机会被误认成选项。
        it["options"] = [_LEAD_PUNCT.sub("", o) for o in it["options"]]
        if not it["options"] and re.search(r"[\s　][A-EＡ-Ｅ][\s　]*[.、．]?[\s　]*\S", it["stem"]):
            st2, opts = R._split_options(it["stem"])
            if len(opts) >= 2 and len(st2) >= 6:
                it["stem"], it["options"] = st2, opts
        if len(it["options"]) == 1 and re.search(r"[B-EＢ-Ｅ][\s　]*[.、．]", it["options"][0]):
            # 前面垫一句占位题干：_split_options 的合理性检查要求题干至少 6 个字
            # （那条检查是防「题干里的 A 股被当成选项 A」的，对我们这儿不适用），
            # 直接传 "A.…" 会因为题干为空被判不合理而拒绝切分。
            _stem, opts = R._split_options("本题选项如下：A." + it["options"][0])
            if len(opts) >= 2:
                it["options"] = opts
    return items


def parse_inline(text):
    """答案跟在题后面的题册。返回 (题目列表, 体检单)，形状和 parse_bank 一致。"""
    items, cur, kind = [], None, "single"
    for raw in text.splitlines():
        ln = raw.rstrip()
        if not ln.strip() or _JUNK.search(ln):
            continue
        ms = _SEC.match(ln)
        if ms:
            kind = next((v for k, v in _SEC_KIND.items() if ms.group(1).startswith(k)), "single")
            continue
        ma = _ANS_INLINE.match(ln) or _ANS_BRACKET.match(ln)
        if ma and cur is not None:
            a = _half(ma.group(1)).upper()
            cur["answer"] = "T" if a in ("√", "对") else ("F" if a in ("×", "错") else a)
            # 多选/单选按**答案字母个数**回判，不看章节标题 —— 这几份押题里
            # 单选多选是混排的，标题靠不住
            if cur["answer"] not in ("T", "F"):
                cur["part"] = "multi" if len(cur["answer"]) > 1 else "single"
            items.append(cur)
            cur = None
            continue
        mo = _OPT.match(ln)
        if mo and cur is not None and len(cur["options"]) < 5:
            L = _half(mo.group(1)).upper()
            if L == "ABCDE"[len(cur["options"])]:
                cur["options"].append(R.norm(mo.group(2)))
                continue
        mq = _Q.match(ln)
        if mq:
            cur = {"no": int(mq.group(1)), "part": kind, "chap": "",
                   "stem": R.norm(mq.group(2)), "options": [], "answer": ""}
            continue
        if cur is not None:
            if cur["options"]:
                cur["options"][-1] += R.norm(ln)
            else:
                cur["stem"] += R.norm(ln)

    repair_options(items)

    ok, bad = [], []
    for it in items:
        n_opt = len(it["options"])
        if it["part"] == "judge":
            (ok if it["answer"] in ("T", "F") else bad).append(
                it if it["answer"] in ("T", "F") else (it, "判断题答案不是 √/×"))
            continue
        if n_opt < 2:
            bad.append((it, "选项少于 2 个"))
        elif any(c not in "ABCDE"[:n_opt] for c in it["answer"]):
            bad.append((it, "答案 %s 超出本题 %d 个选项" % (it["answer"], n_opt)))
        else:
            ok.append(it)
    rate = len(ok) / len(items) if items else 0.0
    return ok, {"n_all": len(items), "n_ok": len(ok), "n_ans": len(items), "n_skip": 0,
                "rate": rate, "bad": bad,
                "kinds": {k: sum(1 for i in ok if i["part"] == k)
                          for k in ("single", "multi", "judge")}}


# 千题斩专用：OCR 把选项 **C 系统性地认成了 5**（`5. 面质` 其实是 `C. 面质`）。
# 实测全书 799 行以「5.」开头，其中 748 行在选项序列里、51 行是真的第 5 题。
# 判据：同一行里还有 `D.`，或上一行是 `A.`/`B.` 开头 —— 那它就在选项序列里。
_C_AS_5 = re.compile(r"^([\s　]*)5([\s　]*[.、．])")


def fix_ocr_c(lines):
    """把被认成 5 的选项 C 还原。只动**确实在选项序列里**的那些，不碰真题号。"""
    out = []
    for i, l in enumerate(lines):
        if _C_AS_5.match(l):
            prev = out[-1] if out else ""
            in_opt = bool(re.search(r"(?:^|[\s　])D[\s　]*[.、．]", l)) or \
                bool(re.search(r"(?:^|[\s　])[AB][\s　]*[.、．]", prev))
            if in_opt:
                l = _C_AS_5.sub(r"\1C\2", l, count=1)
        out.append(l)
    return out


# 双栏排版：一行里并排两个选项（`A.支持    B. 同感`）。切成两行再交给下游，
# 下游那套「一行一个选项」的逻辑就不用动。
_TWO_COL = re.compile(r"(.*?[\s　]{2,})((?:^|[\s　])[B-DＢ-Ｄ][\s　]*[.、．].*)$")


def split_two_col(lines):
    """**必须在 fix_ocr_c 之后调用**：左半是「5. 面质」时（还没还原成 C），
       守卫条件认不出它是选项，那一行就切不开，右边的 D 也就跟着丢了。
       实测顺序反了的话 D 只认出 244 个，顺序对了是 843 个。"""
    out = []
    for l in lines:
        m = _TWO_COL.match(l)
        # 左半必须自己也是个选项（以 A-C 开头），否则「题干  D.某某」会被误切
        if m and re.match(r"^[\s　]*[A-CＡ-Ｃ][\s　]*[.、．]", m.group(1)):
            out.append(m.group(1).rstrip())
            out.append(m.group(2).strip())
        else:
            out.append(l)
    return out


def ocr_repair(text):
    """OCR 文本的通用修复：先还原被认成 5 的选项 C，再切开双栏。**顺序不能反。**"""
    lines = [l.rstrip() for l in (text or "").splitlines() if l.strip()]
    return "\n".join(split_two_col(fix_ocr_c(lines)))


def parse_bank(text, answer_text=None):
    """→ (题目列表, 体检单)。题干区和答案区**分开扫**，最后按（章, 题型, 题号）对齐。

    answer_text 给的是**另一本册子**的正文（千题斩那种「刷题册 + 解析册」分家的）。
    跨文件对齐是独立的一步，**不能默认按顺序就能配上** —— 两本的条数本来就不一样
    （刷题册 925 题、解析册 822 条），顺次配对等于整本答案错位。
    """
    if answer_text is not None:
        body, tail = text, answer_text
    else:
        m = _ANS_HEAD.search(text) or _ANS_MARK_HEAD.search(text)
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
    repair_options(items)

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
        elif any(re.search(r"(?:^|[\s　])[A-E][\s　]*[.、．]", o) for o in it["options"]):
            # 选项里混进了**别的选项标记**（`B.大众传媒5C.家庭 D. 朋`）——
            # 双栏切分在这一行失败了，C/D 被并进了 B。这种题**按题剔除**，
            # 不放宽整册的闸：闸是用来判「解析器懂不懂这本书」，
            # 逐题检查才是真正决定「这道题能不能发给人做」的东西。
            bad.append((it, "选项里混着别的选项标记（多半是双栏没切开）"))
        elif any(not o.strip() or len(o) > 80 for o in it["options"]):
            # 只挡**空选项**和**长到不像话的**。下限别设成 2 ——
            # 真实册子里「A.1」「B.对」这种一个字的选项是存在的，
            # 一刀切会把好题也剔掉（实测误伤了四条老测试用例）。
            bad.append((it, "选项长度异常（%s）" % "/".join(str(len(o)) for o in it["options"])))
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


def ocr_text(con, file_id):
    """从 sq_ocr 拼出整本的文字。**OCR 一次、解析多次** —— 调解析规则时从这儿重来，
       绝不重跑 OCR（那是 2331 页、半小时的活）。"""
    rows = con.execute("SELECT text FROM sq_ocr WHERE file_id=? ORDER BY page",
                       (file_id,)).fetchall()
    return "\n".join(r[0] or "" for r in rows)


def find_banks(con, from_ocr=False):
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
    if from_ocr:
        # 只留 OCR 过的那些：有文字层的那批已经由默认模式收过了，不必重来
        ocred = {r[0] for r in con.execute("SELECT DISTINCT file_id FROM sq_ocr")}
        out = [b for b in out if b["file_id"] in ocred]
    return out


def save(con, bank, items, from_ocr=False, n_bad=0):
    """入库。**标明这批题是不是 OCR 来的** —— OCR 那条链路比文字层长
       （识别 + 双栏切分 + 字符还原），做错时得看得出是题的问题还是自己的问题。

    n_bad 是**这册解析出来、但没能收下的题数**（OCR 把选项吃了之类）。存下来是为了
    界面上能说「这卷 96 题里只收下 37 道」—— 只存收下的那 37，卷子看着就是满的，
    人会以为自己做完了一整套。缺口要如实摆出来。
    """
    row = con.execute("SELECT id FROM sq_papers WHERE file_id=?", (bank["file_id"],)).fetchone()
    name = bank["name"].rsplit(".", 1)[0]
    if row:
        pid = row["id"]
        con.execute("DELETE FROM sq_questions WHERE paper_id=?", (pid,))
    else:
        cur = con.execute(
            "INSERT INTO sq_papers(file_id,name,folder,ext,region,year,kind,total,status) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (bank["file_id"], name, bank["folder"], ".pdf", "通用", 0, kind_of(name), 0, "ok"))
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
             "ok", json.dumps({"why": "练习册原册答案，按题号对齐入库",
                               "src": "ocr" if from_ocr else "pdf"}, ensure_ascii=False),
             hashlib.sha1(R.qhash_text(stem).encode("utf-8")).hexdigest()[:16]))
    con.execute("UPDATE sq_papers SET n_obj=?, n_sub=0, n_doubt=0, n_bad=?, kind=? WHERE id=?",
                (len(items), n_bad, kind_of(name), pid))
    return pid


def _misalign(rep):
    """这册里有多少道题**闻着像答案错位**（占全册的比例）。

    整册跳过的闸原本只看一个「对齐率」，可是掉下来的原因有两类，性质完全不同：

      OCR 把选项吃了 / 认错了字   → 这道题**收不进来**（丢题）
      答案区和题干区对错了位      → 这道题**收进来是错的**（发错题给人做）

    扫描件的对齐率天生就低，低的那部分几乎全是第一类；拿一个 85% 的总闸一刀切，
    等于因为「有些题 OCR 糊了」而把整卷扔掉。所以扫描件走 --loose 这条路时改看
    **第二类的占比** ——「答案 D 超出本题 3 个选项的范围」这种，是答案区串行的招牌症状。
    丢题可以忍（界面上如实写「96 题只收下 37 道」），发错题一道都不能忍。
    """
    n = sum(1 for _, why in rep["bad"] if "超出本题" in why)
    return n / rep["n_all"] if rep["n_all"] else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--min", type=float, default=0.85, help="对齐率低于它就整册跳过")
    # 扫描件专用的第二条路。**不是把闸门调松，是换了一条判据** —— 见 _misalign 的注释。
    ap.add_argument("--loose", type=float, default=0.0,
                    help="对齐率没到 --min，但可用率到了这个数、且错位嫌疑低于 "
                         "--max-misalign 时也收（扫描件用；默认 0 = 关闭）")
    ap.add_argument("--max-misalign", type=float, default=0.05,
                    help="「答案超出本题选项范围」的占比上限，--loose 那条路才看它")
    ap.add_argument("--from-ocr", action="store_true",
                    help="文字从 sq_ocr 读（扫描件走这条），不再碰 PDF")
    ap.add_argument("--only", default="", help="只处理文件名含这个词的册子")
    ap.add_argument("--pair", default="", help="答案在另一本册子里，给它的文件名关键词")
    ap.add_argument("--parts", default="",
                    help="只收这些题型（如 multi,judge）—— 加工链路长的题型可以只挑信得过的收")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    banks = find_banks(con, a.from_ocr)
    if a.only:
        banks = [b for b in banks if a.only in b["name"]]
    pair_text = None
    if a.pair:
        pr = con.execute("SELECT id FROM drive_files WHERE name LIKE ? AND deleted_at IS NULL "
                         "LIMIT 1", ("%" + a.pair + "%",)).fetchone()
        if pr:
            pair_text = ocr_repair(ocr_text(con, pr["id"])) if a.from_ocr \
                else R.pdf_text(find_banks.__globals__["UPLOADS"])
    want_parts = {x.strip() for x in a.parts.split(",") if x.strip()}
    if a.limit:
        banks = banks[:a.limit]
    print("候选 %d 份（已排除行测类）\n" % len(banks))

    took = skipped = total = 0
    kinds = {"single": 0, "multi": 0, "judge": 0}
    for b in banks:
        text = ocr_repair(ocr_text(con, b["file_id"])) if a.from_ocr else R.pdf_text(b["path"])
        if len(text.strip()) < 500:
            continue
        items, rep = parse_bank(text, pair_text)
        # 卷末没有「参考答案」区、却每题后面跟着「答案：X」的，换内联模式再试一次。
        # 判据是**结果**不是文件名：按对齐率挑更好的那一版，规则认不出的自然被闸门挡下。
        if rep["rate"] < a.min and (_ANS_INLINE.search(text) or _ANS_BRACKET.search(text)):
            it2, rep2 = parse_inline(text)
            if rep2["rate"] > rep["rate"]:
                items, rep = it2, rep2
        if rep["n_all"] < 5:
            continue
        if want_parts:
            # 只收指定题型：**逐题剔除，不放宽整册的闸** ——
            # 加工链路长的册子（OCR + 双栏切分 + 字符还原）可以只挑信得过的题型收。
            items = [x for x in items if x["part"] in want_parts]
            rep["n_ok"] = len(items)
            rep["kinds"] = {k: sum(1 for i in items if i["part"] == k)
                            for k in ("single", "multi", "judge")}
        mis = _misalign(rep)
        loose_ok = (a.loose > 0 and rep["rate"] >= a.loose and mis <= a.max_misalign)
        ok_gate = bool(items) if want_parts else (rep["rate"] >= a.min or loose_ok)
        flag = "✓" if ok_gate else "✗"
        if ok_gate:
            took += 1
            total += len(items)
            for k in kinds:
                kinds[k] += rep["kinds"][k]
            if not a.scan:
                save(con, b, items, a.from_ocr, n_bad=rep["n_all"] - len(items))
        else:
            skipped += 1
        why = ""
        if not ok_gate:
            why = "← 整册跳过" + ("（错位嫌疑 %.0f%%）" % (mis * 100)
                                 if a.loose > 0 and mis > a.max_misalign else "")
        elif loose_ok and rep["rate"] < a.min:
            why = "← 只收下 %d/%d（OCR 掉字），错位嫌疑 %.0f%%" % (
                len(items), rep["n_all"], mis * 100)
        print("%s %-44s 题 %3d 答案 %3d 可用 %3d 对齐 %3.0f%% %s"
              % (flag, b["name"][:44], rep["n_all"], rep["n_ans"], rep["n_ok"],
                 rep["rate"] * 100, why))
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
