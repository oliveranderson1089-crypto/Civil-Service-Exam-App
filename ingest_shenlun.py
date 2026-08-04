#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""申论真题入库：把云盘里的历年申论卷解析进 slreal_papers / slreal_questions。

**答案文件才是主源**，不是那 30 套题面。云盘 `公考/真题` 那 30 套是「申公宝APP」
整理的纯题面（无答案），而 `2000-2023国考申论PDF` 这类目录里的 140 个「真题及答案」
文件本身就是完整卷子——注意事项 + 给定资料 + 作答要求 + 参考答案 + 解析都在一份里。
所以先灌答案文件，再用 30 套题面补它们盖不到的年份/卷种（2026、山东）。

题型标注分两路，**必须分清哪条是人判的、哪条是规则判的**（label_src 列）：
  · human —— docs/data/yy-真题标注.tsv 里那 127 道（我逐道读题干归的类，见设计文档 3.2）
  · rule  —— 其余卷子靠规则判。规则的准确率**用那 127 道当测试集量出来**，
             不靠感觉（`--eval` 就是干这个的）。

用法：
    python3 ingest_shenlun.py --scan          # 只看要处理哪些文件，不动库
    python3 ingest_shenlun.py --eval          # 只评规则分类器的准确率，不动库
    python3 ingest_shenlun.py --answers       # 灌答案文件（主源）
    python3 ingest_shenlun.py --papers        # 灌 30 套题面（补充）
    python3 ingest_shenlun.py                 # 两步都跑
"""
import argparse
import csv
import os
import re
import sqlite3
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
BLOB = os.path.join(BASE, "uploads", "drive")
# 文本缓存**不能放会话临时目录**。第一版默认取 TMPDIR，实测那个目录会被整体清掉——
# 170 份提取好的文本和 89 页 OCR 结果（跑了十几分钟）一起没了。
# 现在默认落在 uploads/ 下：uploads/ 已经在 .gitignore 里，是这个项目放运行时数据的地方。
CACHE = os.environ.get("SL_TXT_CACHE", os.path.join(BASE, "uploads", "sltxt"))
LABELS = os.path.join(BASE, "docs", "data", "yy-真题标注.tsv")

# 题面卷：那 30 套。答案卷：名字带「答案」的申论文件，排掉行测和「无答案版」
# （这两个排除是体检时实测出来的假阳性，各 3 个 / 2 个）
SQL_PAPERS = """
SELECT id, owner_id, folder, name, stored_name, ext FROM drive_files
 WHERE deleted_at IS NULL AND is_dir=0 AND folder='公考/真题' ORDER BY name
"""
SQL_ANSWERS = """
SELECT id, owner_id, folder, name, stored_name, ext FROM drive_files
 WHERE deleted_at IS NULL AND is_dir=0 AND folder LIKE '公考%'
   AND (name LIKE '%申论%' OR folder LIKE '%申论%')
   AND name LIKE '%答案%' AND name NOT LIKE '%行测%' AND name NOT LIKE '%无答案%'
 ORDER BY name
"""

# 页眉页脚水印 + **答题卡的字数格标记**。后者是单独成行的 100/200/300…，
# 印在答题区旁边给考生数字数用的。不清掉的话它会跟着「要求」一起显示到做题界面上
# （实测：「(3)不超过450字。」后面拖着一串 100 200 300 400）。
NOISE = [r"申公宝APP.*?来源", r"第\s*\d+\s*页\s*共\s*\d+\s*页.*?仅供学习",
         r"^[ \t]*(?:100|200|300|400|500|600|700|800|900|1000|1100|1200)[ \t]*$"]


# ---------- 取文本 ----------

def _cache(key):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, key + ".txt")


def _pdftotext(path):
    out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
                         capture_output=True, timeout=180)
    return out.stdout.decode("utf-8", "ignore")


def _office(path, key):
    """doc/docx 走 soffice → pdf → pdftotext，和 mods/files.py 那条链路同源。"""
    outdir = os.path.join(CACHE, "conv")
    os.makedirs(outdir, exist_ok=True)
    pdf = os.path.join(outdir, key + ".pdf")
    if not os.path.exists(pdf):
        tmp = os.path.join(outdir, key + os.path.splitext(path)[1])
        if not os.path.exists(tmp):
            with open(path, "rb") as a, open(tmp, "wb") as b:
                b.write(a.read())
        subprocess.run(["soffice", "--headless",
                        "-env:UserInstallation=file://" + os.path.join(CACHE, "lo"),
                        "--convert-to", "pdf", "--outdir", outdir, tmp],
                       timeout=240, check=True, capture_output=True)
    return _pdftotext(pdf) if os.path.exists(pdf) else ""


MIN_CHARS = 1500          # 少于这么多字就当没有文字层（扫描件），要走 OCR


def _ocr_pdf(src, dpi=220):
    """扫描件走 pdftoppm → tesseract(chi_sim)。和 mods/ocr.py 用同一套工具，
    但那边是单张图的接口，这里要整本 PDF，所以另写一份循环。

    dpi 取 220：原图多是 96dpi，放到 220 识别率明显好过原尺寸，再高只是变慢。
    """
    import glob
    import tempfile
    out = []
    with tempfile.TemporaryDirectory(prefix="slocr-") as td:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", src,
                        os.path.join(td, "p")], timeout=2400, check=True)
        pages = sorted(glob.glob(os.path.join(td, "p*.png")))
        for i, img in enumerate(pages, 1):
            try:
                t = subprocess.run(["tesseract", img, "stdout", "-l", "chi_sim+eng",
                                    "--psm", "6"], capture_output=True, timeout=240)
                out.append(t.stdout.decode("utf-8", "ignore"))
            except Exception:
                print("    第 %d/%d 页 OCR 失败，跳过" % (i, len(pages)), file=sys.stderr)
    txt = "\n".join(out)
    # tesseract 认中文常在汉字之间插空格，不去掉的话后面所有正则都对不上
    txt = re.sub(r"(?<=[一-鿿，。！？；：、（）《》“”])[ \t]+"
                 r"(?=[一-鿿，。！？；：、（）《》“”])", "", txt)
    return re.sub(r"\n{3,}", "\n\n", txt)


def _office_pdf(src, key):
    """doc/docx 先转 PDF 才能 OCR，复用 _office 那条转换链路。"""
    pdf = os.path.join(CACHE, "conv", key + ".pdf")
    if os.path.exists(pdf):
        return pdf
    try:
        _office(src, key)
    except Exception:
        return None
    return pdf if os.path.exists(pdf) else None


def get_text(r, allow_ocr=False):
    key = r["stored_name"].rsplit(".", 1)[0]
    p = _cache(key)
    if os.path.exists(p):
        got = open(p, encoding="utf-8", errors="ignore").read()
        if len(re.sub(r"\s", "", got)) >= MIN_CHARS or not allow_ocr:
            return got
    src = os.path.join(BLOB, str(r["owner_id"]), r["stored_name"])
    if not os.path.exists(src):
        return ""
    try:
        t = _pdftotext(src) if (r["ext"] or "").lower() == ".pdf" else _office(src, key)
    except Exception:
        return ""
    # 文字层太薄 = 扫描件。只在显式允许时才 OCR（89 页要跑十几分钟，不能在普通入库里顺手跑）
    if allow_ocr and len(re.sub(r"\s", "", t)) < MIN_CHARS:
        pdf = src if (r["ext"] or "").lower() == ".pdf" else _office_pdf(src, key)
        if pdf:
            print("  OCR：%s" % r["name"][:56], flush=True)
            try:
                t = _ocr_pdf(pdf) or t
            except Exception as e:
                print("    OCR 失败：%s" % str(e)[:70], file=sys.stderr)
    for pat in NOISE:
        t = re.sub(pat, "", t, flags=re.M)
    t = re.sub(r"\n{3,}", "\n\n", t)
    if t:
        open(p, "w", encoding="utf-8").write(t)
    return t


# ---------- 解析卷子 ----------

# 「作答要求」段头和题号**都有一把变体**，各家排版不一样。第一版只认
# 「三、作答要求」+「一、」，21 份切不出来（含 2025 国考三卷这类标尺窗口内的关键卷）。
# 变体是把失败文件全量枚举出来数的，不是猜的：
#   段头  裸「作答要求」6 · 「【作答要求】」3 · 行内「作答要求」4 · 「申论要求」2
#   题号  「一、」6 · 「1、」4 · 「问题一：」4 · 「（一）」2
_SEC_TASK = [
    re.compile(r"【\s*作答要求\s*】"),
    re.compile(r"^[ \t]*[三二一]?、?\s*作答要求\s*$", re.M),
    re.compile(r"[三二一]、\s*(?:作答|申论)要求"),
    re.compile(r"(?:作答|申论)要求[：:]?"),
]
_SEC_MAT = re.compile(r"【\s*给定资料\s*】|[二一]、\s*(?:给定资料|阅读资料|给定材料)")
# 题号候选，按可靠性排。只有**数出来的条数落在 3~8**才采用（申论一卷 3~5 题）——
# 不然「（一）」这类会把答案里的分条也数进来
_QNUMS = [
    re.compile(r"^[ \t]*问题([一二三四五六])[：:]", re.M),
    re.compile(r"^[ \t]*([一二三四五六])、", re.M),
    re.compile(r"^[ \t]*第([一二三四五六])题", re.M),
    re.compile(r"^[ \t]*([1-6])[、．.]", re.M),
    re.compile(r"^[ \t]*[（(]([一二三四五六])[)）]", re.M),
]


ANS_HEAD = r"参考答案|答案要点|【答案|参考例文"
# 申论一卷 3~5 题。切出来的数目超出这个范围就是**切错了**，不是卷子特殊——
# 与其把垃圾题灌进库（污染文种频次这把标尺），不如把这份卷子标成 suspect 让人来看。
Q_LO, Q_HI = 2, 6
# 「这一段是题目而不是答案分条」的判据：真题题干必带分值或字数要求，答案分条不带。
_Q_MARK = re.compile(r"[（(]\s*\d{1,2}\s*分\s*[)）]|不超过\d+字|不多于\d+字|"
                     r"\d{3,4}字(?:左右|以[上内])|\d{3,4}[-~—]\d{3,4}字|要求[：:]")


def _looks_q(seg):
    return bool(_Q_MARK.search(re.sub(r"\s+", "", seg)))


def split_paper(text):
    """→ (给定资料, [题干原文])。切不出作答要求就返回 (材料, [])。"""
    mt = None
    for pat in _SEC_TASK:                 # 段头按可靠性顺序试，先中的赢
        mt = pat.search(text)
        if mt:
            break
    mm = _SEC_MAT.search(text)
    material = ""
    if mm:
        material = text[mm.end():mt.start()] if mt and mt.start() > mm.end() else text[mm.end():]
    if not mt:
        return material.strip(), []
    body = text[mt.end():]
    # 怎么把「题目」和「答案里的分条」分开，试过两版：
    #  ① 在第一个「参考答案」处硬截 —— 对「题面在前、答案在后」的卷子管用，
    #     但有 16 份卷子是**题目和答案交错排**的（一道题紧跟它的答案），
    #     硬截只剩第一题，反而把这 16 份整份丢掉。
    #  ② 现在：不截，改用「这一段像不像题目」来筛 —— 真题的题干必带**分值或字数要求**，
    #     答案的分条不带。两种排版都能过。
    cands = []
    for pat in _QNUMS:
        idx = [(m.start(), m.group(1)) for m in pat.finditer(body)]
        if len(idx) < 2:
            continue
        segs = []
        for i, (pos, _n) in enumerate(idx):
            end = idx[i + 1][0] if i + 1 < len(idx) else len(body)
            seg = re.sub(r"[ \t]+", " ", body[pos:end]).strip()
            # 段内如果接着写了答案，只留答案之前那部分
            ma = re.search(ANS_HEAD, seg)
            if ma:
                seg = seg[:ma.start()].strip()
            if len(re.sub(r"\s", "", seg)) >= 20 and _looks_q(seg):
                segs.append(seg)
        if Q_LO <= len(segs) <= Q_HI:
            return material.strip(), segs
        cands.append(segs)
    # 一个都不落区间：交出最接近的那组，由调用方按 Q_LO/Q_HI 判 suspect
    best = max(cands, key=len) if cands else []
    return material.strip(), best



def find_words(q):
    """PDF 会把「不超过500字」折行成「不超 过500字」，比对前先去空白（实测漏 7 道）。"""
    s = re.sub(r"\s+", "", q)
    m = re.findall(r"(?:不超过|不多于|控制在|限)(\d{2,4})(?:字|个字)", s)
    if m:
        return max(int(x) for x in m)
    m = re.findall(r"(\d{3,4})[-~—](\d{3,4})字", s)
    if m:
        return int(m[0][1])
    m = re.findall(r"(\d{3,4})字(?:左右|以[上内])", s)
    return int(m[0]) if m else 0


def find_score(q):
    m = re.search(r"[（(]\s*(\d{1,2})\s*分\s*[)）]", q)
    return int(m.group(1)) if m else 0


def split_require(q):
    """题干里「要求：」之后的是作答要求条款——真题原话就是评分标准，单独存。"""
    m = re.search(r"要求[：:]", q)
    if not m:
        return q.strip(), ""
    return q[:m.start()].strip(), q[m.end():].strip()


# ---------- 参考答案对齐 ----------

# 多锚点候选，按可靠性排。**不能只用一个**：各家格式差得远，体检时实测要 5 个分支
# （参考答案 86 / 行首序号 13 / 试题号 3 / 题号 2 / 答案要点 1，31 个切不开）
ANCHORS = [
    ("试题号", re.compile(r"【试题([一二三四五六])】")),
    # 「一、(15 分)」——答案区里带分值的题号。**必须排在「参考答案」前面**：
    # 有的卷子「参考答案」既是小节标题又是每题标记，数出 n_q+1 个，
    # 落在容差内就被接受，结果整份答案**错位一格**（2022 国考行执把 Q4 的答案挂到了 Q5）。
    ("题号分值", re.compile(r"^[ \t]*([一二三四五六])、\s*[（(]\s*\d{1,2}\s*分", re.M)),
    ("题号", re.compile(r"^[ \t]*第([一二三四五六])题", re.M)),
    ("答案要点", re.compile(r"^[ \t]*([一二三四五六])、[^\n]{0,6}答案要点", re.M)),
    ("参考答案", re.compile(r"(?:【?试题)?([一二三四五六])?】?\s*参考答案(?!说明)")),
    ("行首序号", re.compile(r"^[ \t]*([一二三四五六1-9])[、．.](?=\S)", re.M)),
]
_CN = {c: i for i, c in enumerate("一二三四五六", 1)}


def split_answers(text, n_q):
    """→ (锚点名, {seq: 答案原文})。切不出就返回 ('', {})。

    判据是「切出来的段数落在题数附近」，不是「正则匹配上了」——
    体检第一版就是只看匹配，结果「参考答案说明」把 5 道题数成 21 段。
    """
    m = re.search(ANS_HEAD, text)
    if not m:
        return "", {}
    seg = text[m.start():]
    for name, pat in ANCHORS:
        hits = list(pat.finditer(seg))
        # 多出来的那一个、且不带题号的，是**小节标题**（如单独一行的「参考答案」），
        # 留着会让整份答案错位一格。带题号的锚点不受影响。
        if len(hits) == n_q + 1 and not (hits[0].group(1) or ""):
            hits = hits[1:]
        if not (max(2, n_q - 1) <= len(hits) <= n_q + 1):
            continue
        out = {}
        for i, h in enumerate(hits):
            end = hits[i + 1].start() if i + 1 < len(hits) else len(seg)
            body = seg[h.end():end].strip()
            # 锚点吃不干净的头要剥掉，剥两轮：
            #   ·「试题号」只吃到「【试题一】」，后面紧跟的「参考答案」留在正文里
            #   ·「题号分值」只吃到「一、(15」，剩下「分)【参考答案】」
            # 实测不剥的话 283 条里 13 条以「参考答案」开头、更多带着「) 【参考答案】」。
            for _ in range(2):
                body = re.sub(r"^[\s）)\]】、：:分]*(?:(?:%s)[】：:]*)?\s*" % ANS_HEAD,
                              "", body, count=1)
            # 解析部分（审题/找点）不属于答案正文，切掉
            body = re.split(r"第一步|【审题|解析[：:]|参考答案说明", body)[0].strip()
            key = _CN.get(h.group(1) or "", 0) or (int(h.group(1)) if (h.group(1) or "").isdigit() else 0)
            out[key or (i + 1)] = body
        if out:
            return name, out
    return "", {}


def ans_fits(answer, limit):
    """答案字数对不对得上题目的字数要求——**对齐的最后一道闸**。

    真题库那次的教训是「命门是答案对齐」。锚点数对了不等于挂对了：
    实测过整份错位一格（Q4 的答案挂到 Q5），而 Q4 限 500 字、Q5 限 1000 字，
    一比字数就露馅。所以凡是题目给了字数上限的，答案必须落在合理区间，
    否则**宁可不挂**——挂错比没有更糟，它会让后面所有"从真题答案定部件"的活全歪。
    """
    if not answer:
        return False, "空"
    n = len(re.sub(r"\s", "", answer))
    if n < 40:
        return False, "太短(%d)" % n
    if not limit:
        return True, ""
    if n > limit * 1.6:
        return False, "超限太多(%d>%d×1.6)" % (n, limit)
    if n < limit * 0.25:
        return False, "远低于限(%d<%d×0.25)" % (n, limit)
    return True, ""


def split_answers_all(text):
    """所有锚点各自的切分结果，**不卡段数**。给配对场景用。

    入库时卡段数是对的（整份卷子，段数应该等于题数）。配对时不行：
    有的答案文件只覆盖部分题（「副省级 4-5 题」），有的对应题面卷本身残缺
    （2024 国考地市级只解析出 2 道题）——卡段数会把这些全拒掉，实测 13 份里拒了 7 份。
    配对场景有更强的判据：**每条答案都能和对应题目的字数要求对一遍**。
    所以这里把所有候选都交出去，由调用方按「通过字数校验的条数最多」来选。
    """
    m = re.search(ANS_HEAD, text)
    if not m:
        return []
    seg = text[m.start():]
    out = []
    for name, pat in ANCHORS:
        hits = list(pat.finditer(seg))
        if len(hits) < 2:
            continue
        if len(hits) >= 3 and not (hits[0].group(1) or ""):
            hits = hits[1:]          # 不带题号的第一个是小节标题
        got = {}
        for i, h in enumerate(hits):
            end = hits[i + 1].start() if i + 1 < len(hits) else len(seg)
            body = seg[h.end():end].strip()
            for _ in range(2):
                body = re.sub(r"^[\s）)\]】、：:分]*(?:(?:%s)[】：:]*)?\s*" % ANS_HEAD,
                              "", body, count=1)
            body = re.split(r"第一步|【审题|解析[：:]|参考答案说明", body)[0].strip()
            g = h.group(1) or ""
            key = _CN.get(g, 0) or (int(g) if g.isdigit() else 0) or (i + 1)
            if body:
                got.setdefault(key, body)
        if got:
            out.append((name, got))
    return out


def find_ans_note(text, seq):
    """「参考答案说明」——权威的逐部件批注，只有少数卷子有（实测 8 份）。"""
    for m in re.finditer(r"参考答案说明[：:]?\s*(.{40,900}?)(?=\n\s*\n|第一步|【试题|$)",
                         text, re.S):
        yield re.sub(r"\s+", "", m.group(1))


# ---------- 题型分类 ----------

# 应用文的判据是**两条同时成立**：有身份/受文对象的交办语，且点名了文种。
# 只看文种词不行——「请结合案例…」「国务院研究室的调研报告显示」里的「案例」
# 「报告」都不是文种（实测纯关键词法 7 次误命中、10 余道漏判）。
_TASKY = re.compile(r"假如你是|如果你是|假设你是|请你?为|请你?就|拟写|草拟|撰写|编写|起草|"
                    r"以.{0,12}名义|供领导参[阅考]|请你根据.{0,20}写")
_DOCTYPE_PAT = [
    ("经验交流材料", "交流材料"), ("交流材料", "交流材料"), ("交流发言", "交流材料"),
    ("发言稿", "交流材料"), ("发言", "交流材料"), ("讲话稿", "交流材料"),
    ("调研报告", "调研报告"), ("工作简报", "简报"), ("简报", "简报"),
    ("情况报告", "汇报"), ("汇报提纲", "汇报"), ("汇报", "汇报"),
    ("宣传稿", "宣传"), ("宣传材料", "宣传"), ("展板", "宣传"), ("发布词", "宣传"),
    ("解说稿", "宣传"), ("倡议书", "倡议"), ("公开信", "公开信"), ("回信", "公开信"),
    ("感谢信", "公开信"), ("新闻稿", "新闻稿"), ("短评", "短评"), ("评论", "短评"),
    ("编者按", "编者按"), ("案例摘要", "推荐/参评"), ("参评材料", "推荐/参评"),
    ("推荐材料", "推荐/参评"), ("推荐语", "推荐/参评"), ("实施方案", "方案"),
    ("整改方案", "方案"), ("工作方案", "方案"), ("方案", "方案"),
    ("建议书", "建议"), ("提案", "提案"), ("工作指南", "指南"), ("指南", "指南"),
    ("谈话提纲", "谈话"), ("谈话内容", "谈话"), ("导言", "介绍"), ("介绍", "介绍"),
    ("通知", "通知"), ("倡议", "倡议"), ("总结", "汇报"), ("手册", "指南"),
    ("建议", "建议"),          # 「起草一份《关于…的建议》」——比「建议书」常见
]
# 弱词：出现在「非文种位置」的概率很高，要求近旁有交办语才认。
# **上下文一词一条，不共用一条通用正则**——共用过一版，为了捞回 1 道「建议书」
# 把「就…提出建议，供领导参阅」这类**对策题**误判成贯彻执行 6 道，精确率 100%→86%。
# 假的贯彻执行会直接污染文种频次这把标尺，所以这里宁可漏不可错。
_WEAK_DEFAULT = r"一[份则篇个]|拟写|草拟|撰写|编写|起草|写一"
_WEAK = {
    "案例摘要": _WEAK_DEFAULT,
    "方案": _WEAK_DEFAULT,
    "指南": _WEAK_DEFAULT,
    "评论": _WEAK_DEFAULT,
    "总结": _WEAK_DEFAULT,
    # 「起草一份《关于加强…的建议》」认；「就…提出建议」不认——差别在有没有书名号/一份
    "建议": r"一[份则篇]|《",
    # 「对B省『工业上楼』模式进行简要介绍」
    "介绍": _WEAK_DEFAULT + r"|进行[^，。]{0,6}$",
    # 「将在座谈会上发言」
    "发言": _WEAK_DEFAULT + r"|在[^，。]{0,12}$|作[^，。]{0,6}$",
}


def classify(stem):
    """→ (题型, 文种, 文种族, form)。判不了就给 ('', '', '', '')。"""
    s = re.sub(r"\s+", "", stem)
    if re.search(r"自拟题目|自选角度|写一篇文章|撰写一篇文章|写一篇议论文|联系实际", s) \
            and not re.search(r"短评|评论员文章", s):
        return "文章论述", "", "", ""
    doctype = family = ""
    for name, fam in _DOCTYPE_PAT:
        p = s.find(name)
        if p < 0:
            continue
        if name in _WEAK:
            # 前窗匹配；或者这词后面紧跟书名号右半——「《关于加强…的建议》」这种
            # 长标题里，「一份」和「《」离词有二十几个字，前窗怎么开都够不着
            if not (re.search(_WEAK[name], s[max(0, p - 14):p])
                    or s[p + len(name):p + len(name) + 1] in "》」"):
                continue
        doctype, family = name, fam
        break
    if doctype and _TASKY.search(s):
        form = "outline" if re.search(r"提纲", s) else "full"
        if re.search(r"部分|案由|工作事项", s) and not re.search(r"提纲", s):
            form = "part"
        return "贯彻执行", doctype, family, form
    if re.search(r"提出.{0,6}建议|提出.{0,6}对策|提出.{0,6}措施|如何解决|怎么办", s):
        return "提出对策", "", "", ""
    if re.search(r"谈谈|理解|看法|为什么|分析|启示|体现", s):
        return "综合分析", "", "", ""
    if re.search(r"概括|概述|归纳|梳理|总结", s):
        return "归纳概括", "", "", ""
    return "", "", "", ""


# ---------- 文件名元信息 ----------

def meta_of(name):
    m = re.search(r"(19|20)\d{2}", name)
    year = int(m.group(0)) if m else 0
    exam = ("四川" if "四川" in name or "川" in name else
            "山东" if "山东" in name else
            "多省联考" if "多省联考" in name or "联考" in name else
            "国考" if "国家" in name or "国考" in name else "其他")
    kind = ""
    # 卷种名**必须归一**。同一场考试在不同文件里叫法不一样：
    # 「地市卷」/「地市级」/「地市」是一个东西，「副省卷」/「副省级」/「副省」也是。
    # 不归一的话答案卷和题面卷的 (年份,考试,卷种) 对不上——实测因此配不上两份
    # OCR 出来的大文件（4-【地市卷】2024 国考 36165 字、6-【副省卷】35954 字）。
    for k, norm in (("副省级", "副省"), ("副省卷", "副省"), ("副省", "副省"),
                    ("地市级", "地市"), ("地市卷", "地市"), ("地市", "地市"),
                    ("行政执法", "行政执法"), ("县乡", "县乡"), ("省市", "省市"),
                    ("省部级", "省级"), ("省级", "省级"),
                    ("A类", "A类"), ("B类", "B类"), ("选调", "选调")):
        if k in name:
            kind = norm
            break
    return exam, year, kind, ("new" if year >= 2018 else "old")


# ---------- 人工标注 ----------

def load_labels():
    """(卷名, 题号) → 标注。人工标的那 127 道，优先级高于规则。"""
    out = {}
    if not os.path.exists(LABELS):
        return out
    for r in csv.DictReader(open(LABELS, encoding="utf-8"), delimiter="\t"):
        out[(r["paper"], int(r["seq"]))] = r
    return out


# ---------- 主流程 ----------

def ingest(con, rows, role, labels, verbose=True):
    done = {r[0] for r in con.execute("SELECT file_id FROM slreal_papers WHERE file_id IS NOT NULL")}
    stat = {"skip": 0, "noq": 0, "ok": 0, "q": 0, "ans": 0, "human": 0, "rule": 0, "none": 0}
    for r in rows:
        if r["id"] in done:
            stat["skip"] += 1
            continue
        text = get_text(r)
        if len(re.sub(r"\s", "", text)) < 1500:
            stat["noq"] += 1
            if verbose:
                print("  ⚠️ 文字层太少（疑扫描件，要 OCR）：%s" % r["name"][:52])
            continue
        material, qs = split_paper(text)
        if not qs:
            stat["noq"] += 1
            if verbose:
                print("  ⚠️ 切不出作答要求：%s" % r["name"][:52])
            continue
        exam, year, kind, era = meta_of(r["name"])
        suspect = not (Q_LO <= len(qs) <= Q_HI)
        if suspect:
            stat["suspect"] = stat.get("suspect", 0) + 1
            if verbose:
                print("  ⚠️ 切出 %d 道题（不在 %d~%d），判定切错，只记卷子不记题：%s"
                      % (len(qs), Q_LO, Q_HI, r["name"][:48]))
        anchor, answers = split_answers(text, len(qs)) if role == "a" else ("", {})
        cur = con.execute(
            "INSERT INTO slreal_papers(file_id,name,folder,ext,exam,year,kind,era,"
            "has_answer,material,n_q,n_ans,anchor,status,note) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["id"], r["name"], r["folder"], r["ext"], exam, year, kind, era,
             1 if answers else 0, material, len(qs), len(answers), anchor,
             "suspect" if suspect else "ok",
             "切出 %d 道题，超出 %d~%d" % (len(qs), Q_LO, Q_HI) if suspect else ""))
        pid = cur.lastrowid
        if suspect:
            continue
        for i, q in enumerate(qs, 1):
            stem, require = split_require(q)
            words = find_words(q)
            ans = (answers.get(i) or "").strip()
            if ans:
                ok, why = ans_fits(ans, words)
                if not ok:
                    stat["ans_drop"] = stat.get("ans_drop", 0) + 1
                    if verbose:
                        print("  · 答案对不上字数要求，丢掉：%s Q%d（%s）"
                              % (r["name"][:34], i, why))
                    ans = ""
            lab = labels.get((r["name"], i))
            if lab and lab.get("kind"):
                qkind, dt, fam, form = (lab["kind"], lab["doctype"], lab["family"],
                                        lab["form"])
                src = "human"
            else:
                qkind, dt, fam, form = classify(stem)
                src = "rule" if qkind else ""
            stat[src or "none"] = stat.get(src or "none", 0) + 1
            con.execute(
                "INSERT OR IGNORE INTO slreal_questions(paper_id,seq,qkind,doctype,family,"
                "form,stem,require,score,words,answer,label_src) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, i, qkind, dt, fam, form, stem, require,
                 find_score(q), words, ans[:8000], src))
            stat["q"] += 1
            if ans:
                stat["ans"] += 1
        stat["ok"] += 1
    con.commit()
    return stat


def evaluate(con, rows, labels):
    """规则分类器的准确率，用人工标的 127 道当测试集。不动库。"""
    tot = hit = yy_tp = yy_fp = yy_fn = 0
    dt_hit = dt_tot = 0
    for r in rows:
        text = get_text(r)
        _m, qs = split_paper(text)
        for i, q in enumerate(qs, 1):
            lab = labels.get((r["name"], i))
            if not lab or not lab.get("kind"):
                continue
            stem, _req = split_require(q)
            got_kind, got_dt, got_fam, _f = classify(stem)
            want = lab["kind"]
            # 人工标注的粒度是**故意不均匀**的：应用文标到文种，非应用文只标到
            # 「小题（概括/分析/对策）」这个粗桶（当时只需要把应用文拣出来）。
            # 所以比对时要按粗桶比，否则规则输出细分类永远不相等——第一版就是这么
            # 把整体准确率算成 52% 的，那是评测的错，不是分类器的错。
            COARSE = {"归纳概括", "综合分析", "提出对策"}
            if want.startswith("小题"):
                ok = got_kind in COARSE
            elif want.startswith("提出对策"):      # 「带身份的对策题」是边界带，两边都算对
                ok = got_kind in ("提出对策", "贯彻执行")
            else:
                ok = got_kind == want
            tot += 1
            hit += 1 if ok else 0
            if want == "贯彻执行":
                if got_kind == "贯彻执行":
                    yy_tp += 1
                    dt_tot += 1
                    dt_hit += 1 if got_fam == lab["family"] else 0
                else:
                    yy_fn += 1
                    print("  漏判 %s Q%d [%s] %s" % (r["name"][:24], i, lab["doctype"],
                                                    stem[:52]))
            elif got_kind == "贯彻执行":
                yy_fp += 1
                print("  误判 %s Q%d 判成%s：%s" % (r["name"][:24], i, got_dt, stem[:52]))
    p = yy_tp / max(1, yy_tp + yy_fp)
    rc = yy_tp / max(1, yy_tp + yy_fn)
    print("\n== 规则分类器 vs 127 道人工标注 ==")
    print("  题型整体准确率：%d/%d = %.0f%%" % (hit, tot, 100.0 * hit / max(1, tot)))
    print("  应用文 精确率 %.0f%%（%d/%d）· 召回率 %.0f%%（%d/%d）· F1 %.2f"
          % (100 * p, yy_tp, yy_tp + yy_fp, 100 * rc, yy_tp, yy_tp + yy_fn,
             2 * p * rc / max(1e-9, p + rc)))
    print("  文种族判对：%d/%d = %.0f%%" % (dt_hit, dt_tot, 100.0 * dt_hit / max(1, dt_tot)))


def run_ocr(con, rows):
    """把文字层太薄的扫描件 OCR 出来写进文本缓存。之后普通入库直接读缓存，链路不用改。"""
    todo, seen = [], set()
    for r in rows:
        if r["stored_name"] in seen:
            continue
        seen.add(r["stored_name"])
        if len(re.sub(r"\s", "", get_text(r))) < MIN_CHARS:   # 先看现有文字层
            todo.append(r)
    print("需要 OCR 的：%d 份" % len(todo), flush=True)
    ok = 0
    for r in todo:
        p = _cache(r["stored_name"].rsplit(".", 1)[0])
        if os.path.exists(p):
            os.remove(p)          # 删掉那份几十字的空壳缓存，逼它重跑
        n = len(re.sub(r"\s", "", get_text(r, allow_ocr=True)))
        print("    → %d 字 %s" % (n, "✅" if n >= MIN_CHARS else "❌ 仍然太少"), flush=True)
        ok += 1 if n >= MIN_CHARS else 0
    print("OCR 成功 %d/%d" % (ok, len(todo)), flush=True)


def pair_answers(con):
    """把「纯答案文件」的答案配到已入库的题面卷上。

    有一批文件本身没有作答要求段（如「2、2024国考申论（地市级）-参考答案」），
    切不出题目，入库时被跳过——但它们**有答案**。按 (年份, 考试, 卷种) 找到同一场
    考试的卷子，把答案挂过去。配错比不配更糟，所以每条答案都要过 ans_fits 的字数校验。
    """
    have = con.execute("SELECT id, name, year, exam, kind, n_q FROM slreal_papers "
                       "WHERE n_q>0 AND status='ok'").fetchall()
    idx = {}
    for p in have:
        idx.setdefault((p["year"], p["exam"], p["kind"] or ""), []).append(p)
    filled = paired = 0
    for r in con.execute(SQL_ANSWERS).fetchall():
        text = get_text(r)
        if len(re.sub(r"\s", "", text)) < MIN_CHARS:
            continue
        if split_paper(text)[1]:
            continue              # 自己就能切出题的，入库时已经处理过
        exam, year, kind, _era = meta_of(r["name"])
        cands = idx.get((year, exam, kind or "")) or []
        if not cands:             # 卷种没写全时退一步：同年同考试且只有一份候选才认
            same = [p for k, v in idx.items() if k[0] == year and k[1] == exam for p in v]
            cands = same if len(same) == 1 else []
        if not cands:
            print("  配不上（找不到同场考试的卷子）：%s" % r["name"][:48])
            continue
        p = cands[0]
        qs_of = {q["seq"]: q for q in con.execute(
            "SELECT seq, id, words, answer FROM slreal_questions WHERE paper_id=?",
            (p["id"],))}
        # 每个锚点都试，选**通过字数校验的条数最多**的那个。字数是对齐的硬判据。
        best = ("", [])
        for name, cand in split_answers_all(text):
            passed = [(qs_of[s]["id"], a) for s, a in cand.items()
                      if s in qs_of and not qs_of[s]["answer"]
                      and ans_fits(a, qs_of[s]["words"])[0]]
            if len(passed) > len(best[1]):
                best = (name, passed)
        anchor, passed = best
        if not passed:
            # 「一条都没通过」和「这些题早就有答案了」要分开报，不然重跑时满屏假失败
            if sum(1 for q in qs_of.values() if q["answer"]) >= len(qs_of):
                print("  · 跳过（对应卷子的答案已经齐了）：%s" % r["name"][:46])
            else:
                print("  配不上（锚点都试过，没有一条能对上字数要求）：%s" % r["name"][:44])
            continue
        for qid, ans in passed:
            # ans_note 记来源：配对来的答案**必须留出处**。第一版没记，
            # 结果 OCR 文件里带识别错字的答案挂到题面卷上（2026 行执那条「部门吾合」
            # 「食药监等部分隘合成并市场利过局」），事后从卷名根本看不出它是 OCR 来的。
            con.execute("UPDATE slreal_questions SET answer=?, ans_note=? WHERE id=?",
                        (ans[:8000], "配对自：%s" % r["name"], qid))
        con.execute("UPDATE slreal_papers SET has_answer=1, n_ans=n_ans+?, anchor=? "
                    "WHERE id=?", (len(passed), anchor, p["id"]))
        paired += 1
        filled += len(passed)
        print("  ✅ %s → 挂到《%s》%d 条（锚点 %s）"
              % (r["name"][:38], p["name"][:32], len(passed), anchor))
    con.commit()
    print("配对完成：%d 份答案文件 → 补上 %d 条参考答案" % (paired, filled))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--ocr", action="store_true", help="OCR 扫描件（慢，十几分钟）")
    ap.add_argument("--pair", action="store_true", help="把纯答案文件配到题面卷上")
    ap.add_argument("--papers", action="store_true")
    ap.add_argument("--answers", action="store_true")
    ap.add_argument("--reset", action="store_true", help="清空两张表重灌")
    a = ap.parse_args()

    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    papers = con.execute(SQL_PAPERS).fetchall()
    answers = con.execute(SQL_ANSWERS).fetchall()
    labels = load_labels()

    if a.scan:
        print("题面卷 %d 份（公考/真题）· 答案卷 %d 份 · 人工标注 %d 道"
              % (len(papers), len(answers), len(labels)))
        for r in answers[:5]:
            print("  a  %s" % r["name"][:60])
        return
    if a.eval:
        evaluate(con, papers, labels)
        return
    if a.ocr:
        run_ocr(con, list(answers) + list(papers))
        return
    if a.pair:
        pair_answers(con)
        return
    if a.reset:
        con.executescript("DELETE FROM slreal_questions; DELETE FROM slreal_papers;")
        con.commit()
        print("已清空")

    both = not (a.papers or a.answers)
    if a.answers or both:
        print("== 灌答案卷（主源，%d 份）==" % len(answers))
        print("  ", ingest(con, answers, "a", labels))
    if a.papers or both:
        print("== 灌题面卷（补充，%d 份）==" % len(papers))
        print("  ", ingest(con, papers, "q", labels))

    print("\n== 入库结果 ==")
    for row in con.execute(
            "SELECT COUNT(*) n, SUM(has_answer) a, SUM(n_q) q FROM slreal_papers"):
        print("  卷子 %s 份（带答案 %s）· 题 %s 道" % (row[0], row[1], row[2]))
    for row in con.execute("SELECT qkind, COUNT(*) c, SUM(answer!='') a "
                           "FROM slreal_questions GROUP BY qkind ORDER BY c DESC"):
        print("  %-14s %4d 道（有答案 %s）" % (row[0] or "（未判定）", row[1], row[2]))
    for row in con.execute("SELECT label_src, COUNT(*) FROM slreal_questions "
                           "GROUP BY label_src"):
        print("  标注来源 %-6s %d" % (row[0] or "（无）", row[1]))


if __name__ == "__main__":
    main()
