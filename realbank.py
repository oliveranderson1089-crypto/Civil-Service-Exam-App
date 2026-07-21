#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真题解析：把云盘「公考/」下的历年行测试卷拆成一道道题。

只做**解析**，不碰数据库 —— 入库和去重在 ingest_real.py 里，两件事分开：
解析要反复调参数、看产出率，混着入库改起来很痛苦。

三种来源，三条路：
· .docx  → zipfile 直接读 word/document.xml（零依赖，最准）
· .doc   → libreoffice 转 docx 再走上面那条（本机 4 秒/个）
· .pdf   → pdftotext -layout（答案解析卷基本都是 PDF，格式反而最规整）

卷面格式二十几年里换过好几轮，所以识别规则都写得比较松：
题号见过 `1、` `1.` `1：单选、`，选项见过 `A、` `A.` `A ` 而且**经常四个挤在一行**。
"""
import os
import re
import subprocess
import unicodedata
import zipfile

# 康熙部首（U+2F00–U+2FD5）长得和汉字一模一样，但码位不同：2022 四川那份卷子的
# 「⼀.常识判断」用的就是 U+2F00，不是 U+4E00 —— 肉眼看不出来，正则全都匹配不上。
# 这个块是 1:1 映射到统一汉字的，逐字转换不会改变长度（位置能对得上）。
_KANGXI = {c: unicodedata.normalize("NFKC", c)
           for c in map(chr, range(0x2F00, 0x2FD6))
           if unicodedata.normalize("NFKC", c) != c and len(unicodedata.normalize("NFKC", c)) == 1}
_KANGXI_TAB = str.maketrans(_KANGXI)

# 行测卷面**真实存在的五个模块**。别和 drill.py 的 DRILL_TYPES 混：那里还有一个
# 「政治理论」板块（专项练自己分的），行测卷面上没有这个分节 —— 让模型判模块时
# 必须对着这份白名单卡，否则时政题会被判成「政治理论」，回填进 real_questions.module
# 之后，按模块刷的清单里就会冒出一个卷面上不存在的桶。
MODULES = ["常识判断", "言语理解与表达", "数量关系", "判断推理", "资料分析"]
# 认不出分节的卷子，题目的 module 就留空 —— 宁可空着，
# 也不猜：猜错了整块题的模块归属都是错的，比没有归类更难查。
_MOD = r"(常识判断|言语理解(?:与表达)?|数量关系|判断推理|资料分析)"
# 分节标题二十年里有三种写法，都得认，不然模块归属全是空的：
#   「第一部分 常识判断」（2002~2004 老卷）
#   「一、常识判断，根据题目要求…」「一.常识判断：…」（2009 年后绝大多数）
#   单独一行只写模块名
_MOD_HEAD = re.compile(
    r"第[一二三四五六七]部分[\s　]*[^\n]{0,30}?" + _MOD
    + r"|^[\s　]*[一二三四五六七][、.．，,：:][\s　]*" + _MOD
    + r"|^[\s　]*" + _MOD + r"[\s　]*$", re.M)

# 题号：行首的 1~200，后面跟 、. ： 之一。`1：单选、` 这种把「单选、」一起吃掉。
_Q_HEAD = re.compile(r"^[\s　]*(\d{1,3})[\s　]*[、.．：:][\s　]*(?:单选|多选|不定项)?[、.．]?[\s　]*", re.M)


def norm(s):
    """统一空白与全角标点 —— 同一道题在 word 版和 PDF 版里空格数往往不一样，
       不归一化的话去重时会当成两道题。"""
    if not s:
        return ""
    s = s.replace("\xa0", " ").replace("　", " ").replace("﻿", "")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


# ---------------------------------------------------------------- 取文字
def docx_text(path):
    """docx 直接读 XML。段落边界要保住（题号靠行首识别），所以先把 </w:p> 换成换行。"""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    xml = re.sub(r"</w:p>", "\n", xml)
    txt = re.sub(r"<[^>]+>", "", xml)
    txt = (txt.replace("&lt;", "<").replace("&gt;", ">")
              .replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&"))
    return re.sub(r"\n{3,}", "\n\n", txt)


# ---- 题目里的图 -------------------------------------------------------------
# 图形推理的图、资料分析的图表都嵌在 docx 里。只提图不够，还得知道**每张图属于哪道题**：
# 靠的是段落位置 —— 图片锚在某个 <w:p> 里，那一段之前最近的题号就是它所属的题。
# （PDF 版没有这个结构，只能整页渲染，先不做。）
_EMBED = re.compile(r'r:(?:embed|link)="(rId\d+)"')
_REL = re.compile(r'Id="(rId\d+)"[^>]*Target="([^"]+)"')


def docx_figures(path):
    """返回 [(段落序号, 图片字节, 扩展名)]，段落序号和 docx_text 切出来的行号对得上。

    **不在这儿按体积过滤**：图形推理的选项常常是极简线条图，压完几百字节很正常，
    按体积一刀切会切出「题干图在、D 选项图没了」的半截题，而调用方还不知道少了图。
    要滤请调用方自己滤，并且滤了要记一笔。

    两边必须用**同一套段落切分**（都以 </w:p> 为界），否则图和题对不上号 ——
    这类「两个列表用下标关联」的地方是错位事故的高发区，所以这里直接复用同一个正则。
    """
    out = []
    try:
        with zipfile.ZipFile(path) as z:
            rels = dict(_REL.findall(
                z.read("word/_rels/document.xml.rels").decode("utf-8", "ignore")))
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
            xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
            for i, para in enumerate(re.sub(r"</w:p>", "\n", xml).split("\n")):
                for rid in _EMBED.findall(para):
                    tgt = rels.get(rid, "")
                    if not tgt or "media/" not in tgt:
                        continue
                    name = "word/" + tgt.lstrip("./")
                    try:
                        out.append((i, z.read(name), os.path.splitext(name)[1].lower()))
                    except KeyError:
                        pass
    except Exception:
        pass
    return out


def doc_to_docx(path, tmpdir):
    """老的二进制 .doc 转成 docx，返回转换后的路径。国考 2000-2023 有 25 份是这个格式。

    单独暴露出来是因为**提图也要用它**：提图只需要转换产物，不需要文字。
    原先提图那边靠调 doc_text() 触发转换、再把返回的文字扔掉，等于把整篇文字白抽一遍。
    """
    r = subprocess.run(["libreoffice", "--headless", "--convert-to", "docx",
                        "--outdir", tmpdir, path],
                       capture_output=True, timeout=180)
    out = os.path.join(tmpdir, os.path.splitext(os.path.basename(path))[0] + ".docx")
    if not os.path.exists(out):
        raise RuntimeError("libreoffice 转换失败：%s" % r.stderr.decode("utf-8", "ignore")[:200])
    return out


def doc_text(path, tmpdir):
    return docx_text(doc_to_docx(path, tmpdir))


def pdf_text(path):
    r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
                       capture_output=True, timeout=300)
    return r.stdout.decode("utf-8", "ignore")


def file_text(path, tmpdir=None):
    """返回 (文字, 实际解析的文件路径)。

    第二个返回值是给**提图**用的：.doc 要先转 docx 才能提图，而转换在这里已经做过一次。
    不把路径带出去的话，调用方只能再转一遍 —— 27 份 .doc 每份多花 4 秒 libreoffice。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return docx_text(path), path
    if ext == ".doc":
        out = doc_to_docx(path, tmpdir or "/tmp")
        return docx_text(out), out
    if ext == ".pdf":
        return pdf_text(path), path
    raise ValueError("不认识的格式：" + ext)


# ---------------------------------------------------------------- 拆题
def _find_marks(block, pos=0):
    """顺着 A→B→C→D 找四个选项标记的位置，找不全就返回 None。

    **选项经常四个挤在同一行**，像
        A、烟雾的颗粒本身是蓝色的B、烟雾将光线中其他色光滤掉，只有蓝光透射出来
    所以不能按行拆。按顺序找还能避开正文里出现的字母（「A股」「维生素D」这类）——
    只有出现在**上一个选项之后**的那个才算数。
    """
    marks = []
    for ch in "ABCD":
        # 选项标记 = 字母 + 分隔符（、.）等）/ 空格 / 后面直接跟汉字。
        # 前后都要卡住，缺一不可：
        #   · 前面必须是行首或非字母数字 —— 否则 "DNA" 的 A、"3D" 的 D 会被当成选项；
        #   · 后面**不能紧跟字母数字** —— 否则「C、DNA由脱氧核糖…」里 C 刚匹配完，
        #     紧跟着的 "DNA" 的 D 就被当成 D 选项了，C 选项被压成空串，整道题作废。
        #     （分隔符是可选的，所以零宽也能匹配上，这个坑不卡后面根本堵不住）
        m = re.compile(r"(?:(?<=^)|(?<=[^0-9A-Za-z]))" + ch
                       + r"(?:[\s　]*[、.．。)）:：][\s　]*|[\s　]+|(?![0-9A-Za-z]))",
                       re.M).search(block, pos)
        if not m:
            return None
        marks.append(m)
        pos = m.end()
    return marks


# D 选项后面跟着的「不属于这道题」的东西。D 是最后一个标记，天然一直取到块尾，
# 于是下一节的说明、例题、页脚全被吞进 D 的正文里 —— 实测 4.6% 的题中招，
# 存出来的 D 选项长这样：「指引起深深的共鸣\n\n第二部分 数量关系\n(共15题…)【例题】…」。
# 这既让 D 选项显示成一坨垃圾，也污染 ohash（同一道题的两个版本因此配不上对）。
_TAIL_CUT = re.compile(
    r"\n[\s　]*\n"                                     # 空行 = 段落结束
    r"|\n[\s　]*第[一二三四五六七八九十]+部分"
    r"|\n[\s　]*[（(]?共\s*\d+\s*题"
    r"|\n[\s　]*【例题】|\n[\s　]*请开始答题|\n[\s　]*本部分(?:包括|包含)"
    r"|\n[\s　]*[一二三四五六七][、.．][^\n]{0,24}?"
    r"(?:数字推理|数学运算|图形推理|定义判断|类比推理|逻辑判断|事件排序|"
    r"常识判断|言语理解|资料分析|选词填空|片段阅读|语句表达)"
    r"|\n[\s　]*获取试卷更新|\n[\s　]*-\s*\d+\s*-\s*\n")   # PDF 页脚


def _trim_tail(s):
    """把 D 选项后面窜进来的分节说明/例题/页脚切掉。"""
    m = _TAIL_CUT.search(s)
    return s[:m.start()] if m else s


def _sane_split(stem, opts):
    """这组切分看着靠不靠谱。

    专治「A 把题干吞了」：题干里出现孤零零一个 A（「A、B 两地」「A 股」这类），
    _find_marks 从块首找 A 就会命中它，于是题干被截断、真正的 A 选项内容跑进了
    stem，B/C/D 整体错位一格。这种切分的特征很明显：**A 选项比其余三个长得离谱**。
    """
    if not stem or len(stem) < 6 or not all(opts):
        return False
    rest = max(len(o) for o in opts[1:])
    return len(opts[0]) <= rest * 3 + 20


def _split_options(block):
    """把 A/B/C/D 四个选项从一段文字里拆出来，返回 (题干, [四个选项]) 或 (整段, [])。

    第一次切出来不合理就**换下一个 A 往后再试** —— 只认第一个 A 的话，
    题干里随便一个字母 A 就能把整道题切坏。最多退让 4 次，够用且不会退化成 O(n²)。
    """
    pos, last = 0, (block.strip(), [])
    for _ in range(5):
        marks = _find_marks(block, pos)
        if not marks:
            return last
        stem = block[:marks[0].start()].strip()
        opts = []
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(block)
            body = block[m.end():end]
            if i == 3:                       # D 一直取到块尾，得把不属于它的尾巴切掉
                body = _trim_tail(body)
            opts.append(norm(body))
        if _sane_split(stem, opts):
            return stem, opts
        pos = marks[0].end()                 # A 选错了，从它后面重新找
    return last


def module_spans(text):
    """卷子里每个模块从第几个字符开始。没有分节标题就返回空。"""
    spans = []
    for m in _MOD_HEAD.finditer(text):
        name = next((g for g in m.groups() if g), "")
        if name == "言语理解":
            name = "言语理解与表达"
        if name:
            spans.append((m.start(), name))
    return spans


def module_at(spans, pos):
    cur = ""
    for start, name in spans:
        if start <= pos:
            cur = name
        else:
            break
    return cur


# 分节说明里的**例题**长得和真题一模一样（有题干有 ABCD），会被原样收进题库 ——
# 实测收进来过「ABCD 二、演绎推理：共15题…【例题】对于穿鞋来说…解答：只有C…」这种，
# 而且不同年份的说明文字一字不差，去重时还会把它们合并、再挂上不相干的答案。
_JUNK_STEM = re.compile(r"【例题】|例题[：:]|解答[：:]|参考时限|请开始答题|"
                        r"本部分(?:包括|包含)|共\s*\d+\s*题[，,、]")


def _looks_like_question(stem):
    """这段像不像一道真题（而不是分节说明/例题）。"""
    return not _JUNK_STEM.search(stem)


def _cut_by_heads(text, heads, spans):
    out = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        block = text[h.end():end]
        if len(block) > 4000:            # 明显不是一道题（多半是切错了）
            block = block[:4000]
        stem, opts = _split_options(block)
        if len(opts) != 4:
            continue
        stem = norm(re.sub(r"\n+", " ", stem))
        if len(stem) < 6 or not _looks_like_question(stem):
            continue
        out.append({"seq": int(h.group(1)), "synth_seq": 0,
                    "module": module_at(spans, h.start()),
                    "stem": stem, "options": opts})
    return out


def _cut_unnumbered(text, spans):
    """兜底切法：有的卷子**整份没有题号**（2022 四川那两份就是），题干直接跟在上一题的选项后面。

    那就反过来切 —— 一路往下找「A→B→C→D 四个标记」，找到一组就是一道题，
    切到 D 选项所在行的行尾，再从那儿接着找下一组。不能靠「行首的 D、」来切：
    2022 上半年那份的选项是「A ①②③④   B ①③②④   C ③①②④   D ③②①④」，
    四个挤在一行、还只用空格分隔，D 根本不在行首。
    """
    out, pos = [], 0
    while pos < len(text):
        marks = _find_marks(text, pos)
        if not marks:
            break
        d_end = text.find("\n", marks[3].end())
        d_end = len(text) if d_end < 0 else d_end
        stem, opts = _split_options(text[pos:d_end])
        pos = d_end + 1
        if len(opts) != 4:
            continue
        stem = norm(re.sub(r"\n+", " ", stem))
        if len(stem) < 6 or not _looks_like_question(stem):
            continue
        # seq 是**按顺序编的，不是卷子上的真题号** —— 中间有拆不出的题就会整体错位，
        # 所以标成 synth_seq，调用方绝不能拿它去挂答案卷的题号。
        out.append({"seq": len(out) + 1, "synth_seq": 1,
                    "module": module_at(spans, marks[0].start()),
                    "stem": stem, "options": opts})
    return out


def parse_paper(text):
    """拆一整份**题目卷**。返回 [{seq, module, stem, options}]。

    只收「拆得出四个选项」的题：行测全是单选，拆不出四个选项的多半是把材料/说明
    误当成了题（资料分析的材料段、卷首的注意事项），也可能是题干里的数字/图形
    是以图片存的（2009 四川的数字推理就整段丢字）。宁可少收也别收进垃圾。
    """
    text = text.translate(_KANGXI_TAB).replace("\xa0", " ").replace("　", " ")
    spans = module_spans(text)
    out = _cut_by_heads(text, list(_Q_HEAD.finditer(text)), spans)
    if len(out) < 20:                    # 按题号切几乎没切出东西 → 这份卷子没题号
        alt = _cut_unnumbered(text, spans)
        if len(alt) > len(out):
            out = alt
    return out


# ---------------------------------------------------------------- 拆答案
# 答案卷有**六种**排版，都得认 —— 少认一种就会退到最弱的兜底模式去，整卷答案错位：
#   ① 1、【答案】B                （绝大多数 PDF，最规整）
#   ② 第【1】题 / 正确答案:【B】   （2023 国考 docx）
#   ③ 1.解析 … 因此，选择 C 选项。 （2022 国考 docx —— 答案字母在这一段的**末尾**）
#   ④ 1、解析 … 故正确答案为 B
#   ⑤ 只剩光秃秃的「解析」当分隔，题号在转档时丢了（2025 国考那三份、四川 2017 那批）
#   ⑥ 1.A【解析】……           （2000/2001 国考的 PDF，连「【答案】」都不写）
# 「正确答案」「参考答案」都要认 —— 少了那两个字，最常见的一种答案卷（粉笔/公考通导出的
# 「1 、正确答案：D，全站正确率：45%」）就会漏掉，然后退到最弱的兜底模式去，整卷答案错位。
_ANS_INLINE = re.compile(r"^[\s　]*(\d{1,3})[\s　]*[、.．][\s　]*"
                         r"(?:【[\s　]*(?:正确|参考)?答案[\s　]*】|(?:正确|参考)?答案[：:]?)"
                         r"[\s　]*[【\[]?([A-D])", re.M)
_ANS_BRACKET = re.compile(r"第[【\[]?(\d{1,3})[】\]]?题[\s\S]{0,20}?"
                          r"正确答案[：:]?[\s　]*[【\[]?([A-D])[】\]]?")
# ③④：先按「N、解析」切段，再从段里把答案字母抠出来
_ANS_SEG = re.compile(r"^[\s　]*(\d{1,3})[\s　]*[、.．][\s　]*解析", re.M)
_ANS_BARE = re.compile(r"^[\s　]*解析[\s　]*$", re.M)      # ⑤ 题号丢了，只剩分隔用的「解析」
# ⑦ 第1 题 / 第 12 题 —— 独占一行的题头。扫描件 OCR 出来的基本都是这种
#    （原卷是「第【1】题」，tesseract 认不出方括号，出来就是「第1 题」）
_ANS_NOBR = re.compile(r"^[\s　]*第[\s　]*(\d{1,3})[\s　]*题[\s　]*$", re.M)
# ⑧ **答案速览表**：卷首常有一块「题号区间 + 连续字母」的总表，
#      【1-5】ACDAD  [6-10] BCCCA  [11-15] BBBDB …
#    20 行就是 100 道题的答案，比逐题去抠可靠得多、也快得多（一页顶全卷）。
#    左右括号写得很随意（【】[] {} ()），OCR 还会把 [ 认成 {，所以两边都放宽。
_ANS_TABLE = re.compile(
    r"[【\[{(（][\s　]*(\d{1,3})[\s　]*[-–—~－][\s　]*(\d{1,3})[\s　]*[】\]}）)][\s　]*"
    r"([A-D][A-D\s　]{1,30})")
# ⑥ 1.A【解析】…… —— 答案字母紧跟题号，连「【答案】」都不写（2000/2001 国考的 PDF）
_ANS_TIGHT = re.compile(r"^[\s　]*(\d{1,3})[\s　]*[、.．][\s　]*([A-D])[\s　]*(?=【解析】|解析)", re.M)
_ANS_TAIL = re.compile(r"(?:因此[，,]?\s*选择|故正确答案(?:为|是)|故本题选|所以本题选|"
                       r"因此本题选|正确答案(?:为|是)|故答案为)[\s　]*[【\[]?([A-D])")


def _clean_explain(s):
    s = re.sub(r"【拓展】.*", "", s, flags=re.S)          # 拓展是延伸阅读，不是解析
    s = re.sub(r"\n?\s*-\s*\d+\s*-\s*\n?", "\n", s)      # PDF 页码 "-1-"
    return norm(re.sub(r"\n{2,}", "\n", s))[:1500]


# 下一道题的题头长什么样。切段时必须**先把它切掉**：
# 兜底模式是按「解析」这一行切的，而题头（「44 、正确答案：B」）在它前面，
# 于是上一题的正文里就带着下一题的答案 —— 取「最后一个答案字母」正好取到下一题的，
# 整卷错开一位。这个 bug 抽查五道题五道全错，比没有答案还糟。
_NEXT_HEAD = re.compile(r"\n[\s　]*(\d{1,3})[\s　]*[、.．][\s　]*"
                        r"(?:【?[\s　]*(?:正确|参考)?答案|解析|[A-D][\s　]*【)")


def _trim_next(body, cur_seq=0):
    """把窜进来的下一道题截掉。

    **必须带上当前题号**：解析正文里完全可能出现「…参见下述三种情形：\n3、解析该条款时…」
    这种行，光看长相和题头一模一样。只有题号**大于当前题**才可能是下一题的开头，
    否则就是正文，切了会把解析拦腰截断（而且不像答案字母有跨卷对账兜底，没人发现）。
    """
    for m in _NEXT_HEAD.finditer(body):
        if int(m.group(1)) > cur_seq:
            return body[:m.start()]
    return body


def _seg_answers(text, hits, letter_from_body):
    """按切分点把 (题号 → 答案, 解析) 抠出来。letter_from_body 决定答案字母怎么取。"""
    out = {}
    for i, m in enumerate(hits):
        seq = int(m.group(1))
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        body = _trim_next(text[m.end():end], seq)
        letter = letter_from_body(m, body)
        if not letter:
            continue
        ex = re.search(r"(?:【解析】|解析[：:]?)(.*)", body, re.S)
        out[seq] = (letter, _clean_explain(ex.group(1) if ex else body))
    return out


def parse_answers(text):
    """拆**答案解析卷**，返回 ({题号: (答案字母, 解析)}, 题号是否为合成的)。

    合成序号（第 ⑤ 种排版：题号在转档时丢了，只能按出现顺序编）**不能用来挂题**：
    中间少解析一条，后面全体错位一格。调用方拿到 synth=True 就该拒绝按题号对齐。
    """
    text = text.translate(_KANGXI_TAB).replace("\xa0", " ").replace("　", " ")
    cands = []

    h = list(_ANS_INLINE.finditer(text))
    if h:
        cands.append((_seg_answers(text, h, lambda m, b: m.group(2)), False))

    h = list(_ANS_BRACKET.finditer(text))
    if h:
        cands.append((_seg_answers(text, h, lambda m, b: m.group(2)), False))

    h = list(_ANS_TIGHT.finditer(text))
    if h:
        cands.append((_seg_answers(text, h, lambda m, b: m.group(2)), False))

    # 答案字母藏在解析末尾的「因此，选择 C 选项」里。取**最后一个**：
    # 解析中途会引用别的选项（「A 项错误」），只有收尾那句才是结论。
    def tail(m, b):
        hits = _ANS_TAIL.findall(b)
        return hits[-1] if hits else ""

    h = list(_ANS_SEG.finditer(text))
    if h:
        cands.append((_seg_answers(text, h, tail), False))

    # ⑦「第N题」独占一行：题头里的答案字母往往被 OCR 糊掉（【B】→【8B]了】），
    #    但正文结尾那句「故正确答案为 B」是干净的，靠它抠。
    h = list(_ANS_NOBR.finditer(text))
    if h:
        cands.append((_seg_answers(text, h, tail), False))

    # ⑤ 题号在转档时丢了，只剩一行一个光秃秃的「解析」当分隔（2025 国考那三份）。
    #    只能**按出现顺序**编号 —— 所以调用方必须拿题目卷的题数核一下，
    #    对不上就别用，否则整卷答案会错位一格，比没有答案还糟。
    h = list(_ANS_BARE.finditer(text))
    if len(h) > 20:
        seq = {}
        for i, m in enumerate(h, 1):
            end = h[i].start() if i < len(h) else len(text)
            body = _trim_next(text[m.end():end], i)
            letter = tail(m, body)
            if letter:
                seq[i] = (letter, _clean_explain(body))
        cands.append((seq, True))   # ← 唯一一种题号是我们自己编的

    # ⑧ 答案速览表。放在最后加入候选，但它常常一举拿下整卷 —— 后面按条数挑最多的那个，
    #    所以只要表在，它自然会赢。
    tbl = {}
    for m in _ANS_TABLE.finditer(text):
        lo, hi = int(m.group(1)), int(m.group(2))
        letters = re.sub(r"[\s　]", "", m.group(3))[:hi - lo + 1]
        # 区间长度和字母个数必须严丝合缝 —— 对不上说明 OCR 把字母认漏或认多了，
        # 这时候硬填会让整段答案错位，宁可整段不要
        if hi >= lo and len(letters) == hi - lo + 1:
            for i, a in enumerate(letters):
                tbl[lo + i] = (a, "")
    if len(tbl) >= 10:
        cands.append((tbl, False))   # 表里的题号是原卷明写的，不是编的

    if not cands:
        return {}, False
    # 每个候选自带「题号是不是我们编的」这个标记，**不要靠它在列表里的下标去推**：
    # 原先用 `best >= bare_i` 推，而速览表恰好落在裸「解析」那一档没添加时的同一个下标上，
    # 于是最可靠的一种排版被判成了合成序号 —— 调用方那道错位闸会直接弃用整卷答案。
    return max(cands, key=lambda c: len(c[0]))


# ---------------------------------------------------------------- 卷子的身份
_YEAR = re.compile(r"(19|20)\d{2}")
_PAPER_KIND = [
    ("副省级", r"副省"), ("地市级", r"地市"), ("行政执法", r"行政执法"),
    ("招警", r"招警"), ("选调", r"选调"), ("A卷", r"[（(]?A\s*卷"), ("B卷", r"[（(]?B\s*卷"),
]


# ---- 题目卷 ↔ 答案卷 的配对 -------------------------------------------------
# 原先按 (考试, 年份, 卷种, 半年) 配对，**同一年的不同卷子会撞进同一个桶**：
# 《2005 国考真题卷（一）》和《卷（二）》两份内容完全不同的卷子拿到了同一份答案，
# 124 题里 123 题答案一模一样 —— 至少一整卷是错的，而「题号命中率」这类校验
# 根本拦不住（两卷题号都是 1..124，命中率 100%）。
#
# 好在命名极规整：**答案卷名 = 题目卷名 + 「答案及解析」**。所以改成按文件名配对，
# 把答案类词去掉后两边应当完全相同。
_ANSWER_WORDS = re.compile(
    r"(?:参考|标准)?答案(?:及|和|\+|与)?(?:解析)?|解析|试题|题目|"
    r"无答案版?|考生回忆版?|网友回忆版?|已?更新|已?完整|较完整")
_NAME_JUNK = re.compile(r"[\s　_\-—－、,，。\.·+＋/\\|｜:：;；!！?？'\"“”‘’()（）《》〈〉\[\]【】]+")
_LEAD_NO = re.compile(r"^\d{1,2}(?=[^\d])")        # 「1-【行政执法】…」这种排序前缀

# 判别令牌：**必须完全一致才允许配对**。名字再像，卷别不同就是两份卷子 ——
# 「卷（一）」和「卷（二）」的文件名只差一个字，任何相似度算法都会认成同一份。
_VARIANT_PATS = [
    ("副省级", r"副省"), ("地市级", r"地市|市地"), ("行政执法", r"行政执法"),
    ("招警", r"招警"), ("选调", r"选调"), ("证监会", r"证监会"),
    ("卷一", r"卷[（(]?\s*[一1]\s*[）)]?(?![0-9])"), ("卷二", r"卷[（(]?\s*[二2]\s*[）)]?(?![0-9])"),
    ("A卷", r"[（(]?\bA\s*卷"), ("B卷", r"[（(]?\bB\s*卷"),
    ("上半年", r"上半年"), ("下半年", r"下半年"),
]
_MMDD = re.compile(r"(?:19|20)\d{2}\s*年?\s*(\d{3,4})(?=\D)")   # 「2020年0725四川…」


def variant_tokens(name):
    """卷别指纹。两份卷子的令牌集不同 → 绝不配对，哪怕文件名只差一个字。"""
    toks = {label for label, pat in _VARIANT_PATS if re.search(pat, name)}
    m = _MMDD.search(name)
    if m:
        toks.add("d" + m.group(1))     # 同年两场考试靠日期区分（0725 / 1206）
    return frozenset(toks)


def pair_key(name):
    """把文件名规范成「这是哪一份卷子」—— 去掉答案类词后，题目卷和答案卷应当一致。"""
    s = os.path.splitext(name)[0]
    s = _LEAD_NO.sub("", s.strip())
    s = _ANSWER_WORDS.sub("", s)
    return _NAME_JUNK.sub("", s)


def paper_meta(name, folder=""):
    """从文件名 + 所在目录认出：哪一年、国考还是川考、什么卷、是题还是答案。

    这几样是**去重的依据**，认错了会把两份不同的卷子当成同一份合并掉。
    """
    s = name + " " + folder
    y = _YEAR.search(name) or _YEAR.search(folder)
    exam = "四川省考" if ("四川" in s or "川" == s[:1]) else ("国考" if "国" in s else "")
    kind = "申论" if "申论" in name else ("行测" if ("行测" in s or "行政职业能力" in s) else "")
    paper = ""
    for label, pat in _PAPER_KIND:
        if re.search(pat, name):
            paper = label
            break
    season = ""
    if "下半年" in name:
        season = "下半年"
    elif "上半年" in name:
        season = "上半年"
    # 「无答案版」「不含答案」说的是**没有**答案，可它里面就带着「答案」二字 ——
    # 直接 search("答案") 会把 2024 国考那三份「无答案版」题目卷判成答案卷，
    # 白跑一遍 OCR 不说，抠出来的东西还会当成答案去和题目卷配对。
    if re.search(r"无答案|不含答案|没有答案", name):
        return {"year": int(y.group()) if y else 0, "exam": exam, "kind": kind,
                "paper": paper, "season": season, "is_answer": False}

    # 是题目卷还是答案卷。文件名说了算；文件名没说才看目录 —— 但**不能只看「目录里有没有答案二字」**：
    # 「1、2025国考【行测】真题试卷及答案」这种是**混装目录**，题目卷和答案卷都在里面，
    # 按它判会把《2025国考行测题（副省级）》这类题目卷全判成答案卷 ——
    # 后果不只是白跑 OCR，这些卷子的**题目从此不会被解析**（提取只处理 role='q'）。
    # 判据：某一段目录名**只说答案、不说试卷/真题**，才算答案目录。
    # 逐段看而不是看整条路径，是为了照顾「…/答案（已更新）/国考地市卷」这种嵌套。
    is_ans = bool(re.search(r"答案|解析", name)) or any(
        re.search(r"答案|解析", seg) and not re.search(r"试卷|真题", seg)
        for seg in folder.split("/") if seg)
    return {"year": int(y.group()) if y else 0, "exam": exam, "kind": kind,
            "paper": paper, "season": season, "is_answer": is_ans}


# ---------------------------------------------------------------- 题型判定
# 判到的题型名**必须和 mods/drill.py 的 DRILL_TYPES 完全一致** —— 真题要能走
# 现成的「专项练」界面和统计（薄弱题型排序、每题限时、秒杀技巧都按这个名字挂）。
# 规则法：不花钱、可复现、判错了一眼能看出来是哪条规则的锅。判不出就留空，不硬猜。
_QT = {
    "言语理解与表达": [
        # 选词填空：先看空的个数——一个空考语境呼应，多个空基本都要靠近义词辨析
        ("句子排序", r"排列组合最连贯|语句排序|重新排列.{0,8}顺序|将以上.{0,6}句子.{0,10}排列"),
        ("句子填空", r"填入.{0,6}划?横线.{0,10}(?:句子|一句)|接下来.{0,6}最可能讲|下文最可能"),
        ("词语辨析", r"依次填入.{0,20}(?:最恰当|恰当的一项)"),
        ("语境分析", r"填入.{0,12}划?横线|填入画横线"),
        ("理解词句", r"[“\"「].{1,12}[”\"」].{0,12}(?:指的是|是指|含义|理解)"),
        ("判断意图", r"意在(?:说明|强调|阐述|表明)|旨在(?:说明|强调)|主要想表达"),
        ("概括主旨", r"主要(?:说明|讲述|介绍|阐述)|主旨|概括.{0,6}恰当|这段文字.{0,6}(?:主要|意思)"),
        ("推断隐含信息", r"可以推出|可以得出|能够推出|由此可知"),
        ("查找细节", r"符合(?:这段|上述|原)文(?:意|字)|不符合.{0,4}原文|与原文.{0,4}相符"),
    ],
    "判断推理": [
        ("类比推理", r"^[^，。]{1,10}[：:][^，。]{1,10}$|与.{0,10}[：:].{0,10}(?:逻辑关系|关系最为?相似)"),
        ("定义判断", r"是指|定义|下列.{0,10}(?:属于|不属于).{0,10}的是"),
        ("削弱论证", r"最能?(?:削弱|反驳|质疑)|不能削弱"),
        ("加强论证", r"最能?(?:加强|支持|证明)|前提是|需要.{0,4}假设"),
        ("解释说明", r"最能?解释|解释上述(?:现象|矛盾)"),
        ("翻译推理", r"如果.{0,30}那么|只有.{0,20}才|除非.{0,20}否则"),
        ("分析推理", r"由此可以?推出|下列.{0,6}(?:一定|必然)(?:为真|正确)"),
    ],
    "数量关系": [
        ("数字推理", r"^[\d\s，,.、（(?？]+$|填入括号.{0,10}数字"),
        ("工程", r"工程|工作效率|合作.{0,6}完成|单独完成"),
        ("行程", r"相遇|追及|速度|千米/小时|出发.{0,10}(?:小时|分钟).{0,6}后"),
        ("利润", r"利润|成本|售价|打\s*\d\s*折|进价"),
        ("浓度", r"浓度|溶液|盐水|酒精"),
        ("容斥", r"既.{0,10}又|至少.{0,6}(?:参加|选修)|两项都"),
        ("排列组合", r"排列|组合|有多少种|不同的.{0,6}方法|种排法"),
        ("概率", r"概率|possibility|摸出|抽到.{0,6}的可能"),
        ("几何", r"面积|体积|周长|正方形|长方形|圆柱|三角形|边长"),
        ("年龄", r"年龄|岁"),
        ("周期日期", r"星期|礼拜|周期|哪一天|月.{0,2}日"),
        ("植树方阵", r"植树|方阵|每隔.{0,6}米"),
        ("等差数列", r"等差|公差|数列.{0,6}和"),
        ("最值", r"最多.{0,6}(?:多少|几)|至少.{0,6}(?:多少|几)"),
    ],
    "常识判断": [
        ("法律常识", r"法律|宪法|刑法|民法典|条例|依法|诉讼|合同|行政处罚|侵权|《.{0,10}法》"),
        ("科技常识", r"物理|化学|生物|细胞|光合|电磁|卫星|航天|基因|元素|病毒|计算机|人工智能"),
        ("地理常识", r"气候|地形|河流|山脉|季风|经纬|海洋|地震|省份|自治区"),
        ("经济常识", r"通货膨胀|货币政策|财政|GDP|供给|需求|市场经济|税收|汇率|价格"),
        ("公文常识", r"公文|请示|批复|通知|函|意见|纪要|发文字号|行文"),
        ("管理常识", r"管理|行政组织|绩效|决策|领导体制|公共政策"),
        ("人文常识", r"诗|词|文学|历史|朝代|唐|宋|明|清|哲学|成语|典故|《.{0,12}》"),
    ],
}
# 资料分析的题型（基期量/增长率/比重…）要看材料才判得准，而材料还没提取，
# 所以整块留空 —— 判不准就别判，写个错的比空着更误导人。


def classify_qtype(module, stem, options=()):
    """判这道真题属于哪个题型。判不出返回 ""（宁可空着）。"""
    rules = _QT.get(module or "")
    if not rules:
        return ""
    text = (stem or "") + " " + " ".join(options or ())
    # 类比推理要看**选项**长什么样（「医生：手术刀」这种冒号词对），题干反而没特征
    if module == "判断推理" and options:
        pair = sum(1 for o in options if re.match(r"^[^，。；]{1,12}[：:][^，。；]{1,12}$", o.strip()))
        if pair >= 3:
            return "类比推理"
    for name, pat in rules:
        if re.search(pat, text):
            return name
    return ""


# ---------------------------------------------------------------- 去重用的指纹
_PUNCT = re.compile(r"[\s，。、；：？！,.;:?!（）()【】\[\]「」“”‘’\"'—－\-_·…]+")


def qhash_text(stem):
    """题干指纹用的归一化形式：去掉所有空白和标点，全角数字/字母转半角。

    为什么标点也要去：同一道题在 word 版是「（  ）」、PDF 版是「(   )」，
    OCR 出来的还可能是「（ ）」—— 留着标点，同一道题会算出三个不同的指纹。
    """
    s = stem or ""
    s = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in s)
    s = _PUNCT.sub("", s)
    return s.lower()
