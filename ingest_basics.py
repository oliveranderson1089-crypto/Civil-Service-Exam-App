#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基础知识点入库：把云盘「公考/」下的两套机构资料解析成考点树。

两套资料、两种形态，所以是两个 parser、一个框架：

  优路讲义（youlu）  6 册，一册一个行测板块，章/节两级目录 + 【例 N】【答案】【解析】
  三色笔记（sanse）  2 册（文/理），一册装两个板块，层级靠「一、」「▲」「（一）」，
                    重点靠红蓝绿三色 —— 颜色是这套资料的核心价值，必须留住

**原文层和解析层分开**（basic_raw ← → basic_nodes/basic_blocks）：PDF 只读一次，
之后调解析规则一律 --reparse 从库里的原文重来。真题库那边「改解析器却把 OCR
重跑一遍」的教训，这里不再犯。

三色的颜色：pdftohtml -xml 每个 <text> 带 font id，fontspec 里有 color。
所以三色**不用 -layout 文本，直接拿 XML 重建正文**（单栏，按 top 分行、left 排序），
重点词包成 {{r|…}} {{b|…}} {{g|…}}，前端渲染时再变成 <mark>。

用法：
    python3 ingest_basics.py --scan              # 只认文件、探板块边界，不动库
    python3 ingest_basics.py --load              # 抽原文进 basic_raw（慢，一次就够）
    python3 ingest_basics.py --reparse --dry-run # 只解析、只对比，不写库
    python3 ingest_basics.py --reparse           # 解析入库
    python3 ingest_basics.py --reparse --source sanse   # 只跑一套
"""
import argparse
import html
import os
import re
import sqlite3
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import localprofile                                        # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))
CONFIG = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))

# 云盘里的文件名 → 行测板块。认文件名，不认路径：资料以后挪文件夹也不影响。
YOULU_BOARD = {
    "判断-理论精讲-讲义.pdf": "判断推理",
    "常识-理论精讲-讲义.pdf": "常识判断",
    "政治理论讲义.pdf": "政治理论",
    "数量讲义_-解析版-彭老师.pdf": "数量关系",
    "言语解析版-张老师.pdf": "言语理解与表达",
    "资料分析习题-技巧-解析.pdf": "资料分析",
}
# 三色一册两板块，页段靠正文里那张大字扉页（「言语理解三色笔记」）自动探，
# 探不到才用这里的兜底顺序。
SANSE_BOOK = {
    "言语+判断 三色笔记42页（文）.pdf": ["言语理解与表达", "判断推理"],
    "资料+数量 三色笔记55页（理）.pdf": ["资料分析", "数量关系"],
}
SANSE_TITLE = {"言语理解": "言语理解与表达", "判断推理": "判断推理",
               "资料分析": "资料分析", "数量关系": "数量关系"}

# ---------------------------------------------------------------- 正则
# WPS 导出的 PDF 会在字之间塞空格（【 答 案 】、【例 2】都真实出现过），
# 所有标记正则一律容忍内部空白。
# 社区专职工作者那条线的速记资料（第三种形态，parse_shequ）。
# **只收有文字层的**：四色笔记（117 页 / 76 页）和黄金考点（292 页）是纯扫描件，
# 而资料自己就标着「有时间就看」—— 等 P5 批量 OCR 时再补，不为它们提前上 OCR。
# 认文件名不认路径，和上面两套一个规矩：资料以后挪文件夹也不影响。
SHEQU_BOARD = {
    # 公告点名的核心：社工职业资格考试**初级**知识
    "1.2024 初级社会工作者初级实务 考前5页纸（特别特别特别重要）.pdf": "社会工作",
    "2.2024 初级实务考前12页纸（特别重要）.pdf": "社会工作",
    "1.2026社会工作知识-必记66条知识点.pdf": "社会工作",
    "5.社会综合能力与实务考点资料.pdf": "社会工作",
    # 党建党务（公告点名的考试范围）。讲义和知识点总结走 parse_notes，
    # 党章和几部条例是「第 N 条」的法条形态，parse_shequ 现成能吃。
    "3.党史党建讲义.pdf": "党建党务",
    "5.党章知识点总结.pdf": "党建党务",
    "党章修改的13个要点(重点划线版).pdf": "党建党务",
    "社工：党章.pdf": "党建党务",
    "社工：党支部工作条例（试行）.pdf": "党建党务",
    "党纪律处分条例.pdf": "党建党务",
    "《关于新形势下党内政治生活的若干准则》原文重点标注版.pdf": "党建党务",
    # 公文写作（卷面 15 分）
    "公文知识点总结_.pdf": "公文写作",
    "3.公文写作与处理知识.pdf": "公文写作",
    # 社区建设 / 基层治理
    "【5】2026社区知识-高频考点集锦.pdf": "社区知识",
    "【1】社区知识14页必背（三色笔记）.pdf": "社区知识",
    "1.（重点）社区社会工作知识.pdf": "社区知识",
    "2.社区建设与管理.pdf": "社区知识",
    "3.社区居委会工作实用基础知识.pdf": "社区知识",
    "4.社区基础治理.pdf": "社区知识",
    # 社工初级的重点笔记与四色笔记（扫描件，走 sq_ocr → parse_notes）
    "12.社会工作综合能力重点笔记.pdf": "社会工作",
    "6.社会工作实务重点笔记.pdf": "社会工作",
    "4.2024 初级社会工作实务 四色笔记（重要）.pdf": "社会工作",
    "4.2024 新版初级综合能力 四色笔记（有时间需要看）.pdf": "社会工作",
    # 这两份有文字层，直接 pdftotext；形态是「易混淆点 A vs B」，走 parse_shequ
    "3.2024 年社会工作者初级实务 易混淆考点（重要）.pdf": "社会工作",
    "3.2024 新版初级综合能力 易混淆考点（需看）.pdf": "社会工作",
    # 法律常识
    "7.信访工作条例.pdf": "法律法规",
    "民法典考点整理.pdf": "法律法规",
    "【6】中华人民共和国城市居民委员会组织法.pdf": "法律法规",
    "【7】社区建设基础知识百题问答.pdf": "社区知识",
    # 时政（公告点名「时事政治」）。**只收有文字层的那几个月** ——
    # 3/5/6 月那三份是纯扫描件，等 OCR 那一档再补，不为它们提前上 OCR。
    "1月份时政热点.pdf": "时政理论",
    "2月份时政热点.pdf": "时政理论",
    "2026年4月时事政治考点汇总.pdf": "时政理论",
}
# 第四种形态（parse_notes）：**扫描件笔记**。这批是整本没有文字层的重点笔记／四色
# 笔记，文字来自 `sq_ocr`（8 月 19 号那次 OCR 的产物，这里只读不重跑）。
# 它们和上面速记资料最大的不同：**考点行没有序号**，原书靠加粗区分标题，
# 而加粗过不了 OCR —— 剩下的只有「短名词 + 冒号 + 一长串要点」这个形状。
# 所以不能塞进 parse_shequ（那个认序号），单开一个 parser。
SHEQU_NOTES = {
    "3.党史党建讲义.pdf",
    "5.党章知识点总结.pdf",
    "党章修改的13个要点(重点划线版).pdf",
    "公文知识点总结_.pdf",
    "3.公文写作与处理知识.pdf",
    "12.社会工作综合能力重点笔记.pdf",
    "6.社会工作实务重点笔记.pdf",
    "4.2024 初级社会工作实务 四色笔记（重要）.pdf",
    "4.2024 新版初级综合能力 四色笔记（有时间需要看）.pdf",
    "【7】社区建设基础知识百题问答.pdf",
}
# **登记了但暂不入库**：OCR 没认动的书。放在这儿而不是从 SHEQU_BOARD 里删掉，
# 是为了留下判断的痕迹 —— 哪天换了 OCR 引擎重跑，把名字从这里挪走就能放行。
#
# 两本四色笔记是彩色版式 + 侧边竖排栏，tesseract 认出来的考点名大面积是错字
# （「了乞对生的问题代出角征」原文是「针对服务对象的问题作出解释」、
# 「人 G@)闪辣选择适当的目标」原文是「（2）选择适当的目标」），而 751 个考点名里
# 这类错**全是合法汉字**，任何字符类判据都抓不到，只能人看。抽样看下来正文也串味、
# 例题混进考点，入库等于往考点树里掺沙子 —— 备考资料错一个字就是错一道题。
# 资料本身也标着「有时间需要看」，不是主力。
SHEQU_HOLD = {
    "4.2024 初级社会工作实务 四色笔记（重要）.pdf",
    "4.2024 新版初级综合能力 四色笔记（有时间需要看）.pdf",
    # 同样是 OCR 没认动：「歪曲」成了「牌曲」、「邪路」成了「敢路」，
    # 11 页里错到连句子都读不通。党内政治生活准则的内容在党章和党史讲义里都有覆盖。
    "《关于新形势下党内政治生活的若干准则》原文重点标注版.pdf",
}
# 走 parse_notes 且**序号行就是考点**的册子。党史讲义、党章知识点总结、公文知识点
# 都是「1.南昌起义」「10. 基本路线：…」这个写法，标题独占一行、正文跟在后面。
SHEQU_NUMBERED = {
    "3.党史党建讲义.pdf",
    "5.党章知识点总结.pdf",
    "党章修改的13个要点(重点划线版).pdf",
    "公文知识点总结_.pdf",
    "3.公文写作与处理知识.pdf",
}
SHEQU_ROOT = localprofile.drive_root()

# 章/部分：`第一章 社会工作实务的通用过程` / `第一部分 社会工作综合能力` /
# `一、总则亮点`（民法典考点整理用的是这种）
# `部分` 要整个吃掉：只写 `部` 的话「第一部分 社会工作综合能力」会被切成
# 「第一部」+ 标题「分 社会工作综合能力」，多出一个「分」字。
RE_SQ_SEC = re.compile(r"^[\s　]*第\s*([一二三四五六七八九十百零〇\d]+)\s*(部\s*分|[章编篇部])"
                       r"[\s　]*[：:、.]?[\s　]*(.*)$")
RE_SQ_SEC2 = re.compile(r"^[\s　]*([一二三四五六七八九十]{1,3})[、.．][\s　]*(\S.{2,28})$")

# 考点行。这批资料**一册一个写法**，所以是一串模式按顺序试，不是一条正则包打天下：
#   `1、会谈的主要任务：…`      考前 5 页纸 / 必记 66 条
#   `4社会工作的重要目标：…`     社区知识 14 页必背（序号后面**没有分隔符**）
#   `考点 3——遗失物拾得`         民法典考点整理
#   `第一条 为了坚持和加强…`      信访工作条例（法规原文，条即考点）
RE_SQ_PTS = [
    re.compile(r"^[\s　]*\d{1,3}[、.．][\s　]*(.+)$"),
    re.compile(r"^[\s　]*考点[\s　]*\d{1,3}[\s　]*[—－\-]{1,3}[\s　]*(.+)$"),
    # 条号和正文之间**不一定是空格**：扫描件里原书的缩进被 OCR 认成了中文引号
    # （`第三条”党员必须履行下列义务:`），只认空白的话党章 55 条里 40 条认不出来。
    # 分隔符仍然必须有一个 —— 空集合会把「第三条件」这种词也切成法条。
    # 全量对比过：21360 行里新版只多认 41 行，全是真法条。
    re.compile(r"^[\s　]*第[\s　]*([一二三四五六七八九十百零〇\d]+)[\s　]*条[\s　”“\"'：:，,]+[\s　]*(.+)$"),
    # 序号紧跟汉字、中间什么都没有。**必须要求下一个字符是汉字**，
    # 否则「2020 年 5 月」这种正文行会被当成考点 2020。
    re.compile(r"^[\s　]*(\d{1,3})(?=[\u4e00-\u9fa5])(.+)$"),
]


def _lax(s):
    """把 '【答案】' 变成能匹配 '【 答 案 】' 的正则。"""
    return r"\s*".join(re.escape(c) for c in s)


RE_HEAD = re.compile(r"^\s*第\s*([一二三四五六七八九十百]+)\s*([篇章节])\s*(.*)")
RE_CN_NUM = re.compile(r"^\s*([一二三四五六七八九十]+)\s*、\s*(\S.*)")
RE_SANSE_PT = re.compile(r"^\s*▲\s*(\S.*)")
RE_SUB = re.compile(r"^\s*[（(]\s*([一二三四五六七八九十]+)\s*[)）]\s*(.*)")
RE_HFKD = re.compile(r"^\s*高频考点\s*(\d+)\s*[：:]\s*(.*)")
RE_EX = re.compile(r"^\s*(?:%s|%s|%s)" % (
    _lax("【例"), r"例\s*题\s*\d+\s*[．.、]", r"◆\s*例\s*[：:]"))
RE_ANS = re.compile(r"^\s*(?:%s|%s|%s)" % (_lax("【答案】"), _lax("【解析】"),
                                           r"※\s*" + _lax("【解析】")))
RE_PRACT = re.compile(r"^\s*(?:随笔练习|◆?\s*实战运用\s*◆?|优路小结|章节演练|课后练习)\s*$")
# 页眉页脚：优路每页都印网址和口号，三色每页印「三色笔记」，页码单独成行。
# **网址和口号在同一行**（`www.youlu.com      优路公考 “公”无不克`），原先按「整行只有
# 网址」匹配，一行都没滤掉，正文里每隔几段就横插一条广告。所以改成：整行由这几样
# 页眉零件拼成就算页眉（顺序不限、中间是空白）。
_HDR = r"(?:www\.youlu\.com|官方网站\s*[:：]\S*|优路教育|优路公考|[“\"]公[”\"]无不克|三色笔记)"
RE_JUNK = re.compile(r"^\s*(?:%s\s*)+$|^\s*[-－]?\s*\d{1,3}\s*[-－]?\s*$" % _HDR)
# 行内混着页眉的（页眉和正文被 pdftotext 拼进同一行）：把页眉零件抠掉，正文留下
RE_HDR_INLINE = re.compile(r"\s*%s\s*" % _HDR)
# 目录行：标题后面拖一串点、末尾是页码。三色的目录里也有「高频考点1：对称性......16」，
# 不滤掉就会跟正文标题一起建出一棵重复的树。
# **必须连页码一起要求**：只看省略号会误杀正文 —— 「②“通过对比”“经与……对比”」
# 这一行就被吃掉过，行文里的「……」很常见。
# 省略线不止点号：社区那本《（重点）社区社会工作知识》整页目录用的是连字符
# （`第一章 公共管理概述 ------ 2`），只认点号的话 25 行目录全被当成考点建了树，
# 一本书 359 个节点里 148 个是点开没正文的空壳。扩到连字符/破折号族前做过全量
# 新旧对比：28265 行里新版只多杀这 25 行，全在那本书的目录页，零误杀。
# 空壳剪枝的阈值：标题短于这个字数、又没正文没孩子，才算「点开一片空白」的碎片。
# 定在 4 是量出来的：这批资料里最短的真考点是「界定隐私」（民法典，4 字），
# 阈值一旦调到 8 就会连它一起杀。**宁可留几个碎片，不能杀一个考点。**
MIN_KEEP_TITLE = 4
RE_TOC = re.compile(r"[.．·\-－—–_]{6,}\s*-?\s*\d{1,3}\s*-?\s*$")
# 例题题号：答案讲完接着出下一题，题号行就是分界（不切的话答案块会把下一题吞进去）
RE_QNO = re.compile(r"^\s*(\d{1,2})\s*[．.、]\s*\S")

# 三色的三色：从 fontspec 的 color 归到红/蓝/绿三档（书里同色有深浅两三种）
COLOR_TAG = [("r", (0xE0, 0x00, 0x00), (0xFF, 0x99, 0x99)),   # 红：结论/易错
             ("b", (0x00, 0x00, 0x60), (0x77, 0xAA, 0xE0)),   # 蓝：标题/术语
             ("g", (0x00, 0x80, 0x00), (0x99, 0xE0, 0x99))]   # 绿：补充


def color_tag(hexstr):
    """#ed2228 → 'r'；黑/灰返回 ''（正文默认色不标记）。"""
    try:
        r, g, b = (int(hexstr[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return ""
    if max(r, g, b) - min(r, g, b) < 40:          # 三通道接近 = 黑白灰
        return ""
    if r > g + 40 and r > b + 40:
        return "r"
    if b > r + 40 and b > g + 30:
        return "b"
    if g > r + 30 and g > b + 20:
        return "g"
    return ""


# ---------------------------------------------------------------- 取原文
def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace").stdout


def pdf_pages(path):
    m = re.search(r"Pages:\s+(\d+)", run(["pdfinfo", path]))
    return int(m.group(1)) if m else 0


def page_text(path, page):
    return run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), path, "-"])


def page_xml(path, page):
    return run(["pdftohtml", "-xml", "-i", "-f", str(page), "-l", str(page),
                "-stdout", path])


def find_file(stored):
    """云盘文件按 owner 分子目录存，挨个找。"""
    root = os.path.join(UPLOADS, "drive")
    if not os.path.isdir(root):        # 全新部署还没人传过东西，别抛 FileNotFoundError
        return None
    for d in sorted(os.listdir(root)):
        p = os.path.join(root, d, stored)
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------- XML → 带色文本
_FONTSPEC = re.compile(r'<fontspec id="(\d+)"[^>]*size="([\d.]+)"[^>]*color="(#[0-9a-fA-F]{6})"')
_TEXT = re.compile(r'<text top="(-?[\d.]+)" left="(-?[\d.]+)"[^>]*font="(\d+)">(.*?)</text>', re.S)
_TAGS = re.compile(r"<[^>]+>")


def xml_lines(xml):
    """XML 一页 → [(字号, [(颜色档, 文字), ...]), ...]，按 top 分行、left 排序。

    行的字号取该行最大 span 的字号 —— 标题行里混着小字注音之类，取最大才对得上层级。
    """
    fonts = {fid: (float(sz), col) for fid, sz, col in _FONTSPEC.findall(xml)}
    rows = {}
    for top, left, fid, raw in _TEXT.findall(xml):
        txt = html.unescape(_TAGS.sub("", raw))
        if not txt.strip():
            continue
        size, col = fonts.get(fid, (0.0, "#000000"))
        # top 有 1-2px 抖动，按 8px 一档归行
        rows.setdefault(round(float(top) / 8), []).append(
            (float(left), size, color_tag(col), txt))
    out = []
    for key in sorted(rows):
        spans = sorted(rows[key])
        merged, size = [], max(s[1] for s in spans)
        for _l, _s, tag, txt in spans:                     # 相邻同色合并，少几十个标记
            if merged and merged[-1][0] == tag:
                merged[-1] = (tag, merged[-1][1] + txt)
            else:
                merged.append((tag, txt))
        out.append((size, merged))
    return out


def spans_md(spans):
    """[(颜色,文字)] → '{{r|重点}}正文'。前端 mdToHtml 后再换成 <mark>。"""
    buf = []
    for tag, txt in spans:
        t = txt.replace("{{", "").replace("}}", "")
        buf.append("{{%s|%s}}" % (tag, t) if tag and t.strip() else t)
    return "".join(buf)


def plain(spans):
    return "".join(t for _tag, t in spans)


# ---------------------------------------------------------------- 三色 parser
def parse_sanse(rows, boards):
    """rows: [(page, xml)] → (nodes, blocks)。

    层级：一、xxx = 章(1) / ▲xxx = 考点(2)；（一）和正文都进考点的块。
    板块边界：扉页那行超大字「言语理解三色笔记」，切到下一个板块。
    """
    nodes, blocks = [], []
    board = boards[0]
    cur1 = cur2 = None
    buf, kind = [], "concept"
    span = [None, None]                                   # 块的起止页，同 parse_youlu

    def flush():
        nonlocal buf, kind
        if cur2 is not None and buf:
            md = "\n".join(buf).strip()
            if md:
                blocks.append({"node": cur2, "kind": kind, "md": md,
                               "page": span[0] or page, "page_to": span[1] or page})
        buf, kind = [], "concept"
        span[0] = span[1] = None

    def add_node(level, title, page):
        nonlocal cur1, cur2
        n = {"level": level, "title": title.strip(), "page": page,
             "parent": cur1 if level == 2 else None, "board": board,
             "sort": len(nodes)}
        nodes.append(n)
        idx = len(nodes) - 1
        if level == 1:
            cur1, cur2 = idx, None
        else:
            cur2 = idx
        return idx

    for page, xml in rows:
        lines = xml_lines(xml)
        big = max((sz for sz, _s in lines), default=0)
        for size, spans in lines:
            text = plain(spans).strip()
            if not text or RE_JUNK.match(text) or RE_TOC.search(text):
                continue
            # 扉页：整页最大字，且命中书名 → 切板块（实测扉页 24pt，正文 16pt）
            if size >= 22 and size >= big:
                hit = next((b for k, b in SANSE_TITLE.items() if k in text.replace(" ", "")), None)
                if hit and hit in boards:
                    flush()
                    board, cur1, cur2 = hit, None, None
                    continue
            m = RE_CN_NUM.match(text)
            if m and size >= 17:                     # 「一、关系思维」是加大字号的
                flush()
                add_node(1, m.group(2), page)
                continue
            m = RE_SANSE_PT.match(text)
            if m:
                flush()
                if cur1 is None:                     # 有的册子考点直接顶格，没有章
                    add_node(1, board, page)
                add_node(2, m.group(1), page)
                continue
            m = RE_HFKD.match(text)
            if m:
                flush()
                if cur1 is None:
                    add_node(1, board, page)
                add_node(2, m.group(2) or ("高频考点" + m.group(1)), page)
                continue
            if cur2 is None:
                continue                              # 目录页等，落不到考点上就丢
            if RE_PRACT.match(text):
                flush()
                kind = "example"
                continue
            if RE_EX.match(text):
                flush()
                kind = "example"
            elif RE_ANS.match(text):
                flush()
                kind = "answer"
            elif kind in ("answer", "example") and RE_QNO.match(text):
                flush()                                  # 一题一块（含解析后接着的下一题）
                kind = "example"
            elif RE_SUB.match(text) and kind != "example":
                flush()
                kind = "concept"
            if not buf:
                span[0] = page
            span[1] = page
            buf.append(spans_md(spans))
        flush()
    return nodes, blocks


# ---------------------------------------------------------------- 优路 parser
def parse_youlu(rows, board):
    """rows: [(page, text)] → (nodes, blocks)。块按【例】【答案】切。

    **层级是按册自适应的**：多数册是「章→节」两级，言语册却是「篇→章」（16 章、
    一个节都没有）。写死 章=1 的话言语册会解析出 0 个考点 —— 实测踩过。
    所以先扫一遍这册用了哪几种标题字，再从大到小分配层级。

    目录页不解析（正文标题自带层级，目录只会多出一份重复的树）。
    """
    lines_all = []
    for p, t in rows:
        for ln in t.splitlines():
            ln = RE_HDR_INLINE.sub(" ", ln.rstrip())    # 抠掉夹在正文行里的页眉
            if ln.strip() and not RE_JUNK.match(ln) and not RE_TOC.search(ln):
                lines_all.append((p, ln))
    used = {m.group(2) for _p, ln in lines_all for m in [RE_HEAD.match(ln)] if m}
    order = [c for c in "篇章节" if c in used]
    depth = {c: i + 1 for i, c in enumerate(order)}      # 篇/章/节 → 1/2/3

    nodes, blocks = [], []
    cur = {}                                            # level → nodes 下标
    buf, kind, page = [], "concept", 1
    span = [None, None]                                 # 这个块从哪页起、到哪页止

    def flush():
        nonlocal buf, kind
        host = max(cur.values(), key=lambda i: nodes[i]["level"]) if cur else None
        if host is not None and buf:
            md = "\n".join(buf).strip()
            if md:
                # 页码取**块自己的起止**，不是 flush 那一刻的当前页：块跨页时后者
                # 指向块结尾的下一节，「看原书这一页」就和内容对不上了
                blocks.append({"node": host, "kind": kind, "md": md,
                               "page": span[0] or page, "page_to": span[1] or page})
        buf, kind = [], "concept"
        span[0] = span[1] = None

    def add_node(level, title, page):
        parent = max((lv for lv in cur if lv < level), default=None)
        nodes.append({"level": level, "title": title.strip() or "（无标题）",
                      "page": page, "parent": cur.get(parent),
                      "board": board, "sort": len(nodes)})
        for lv in [lv for lv in cur if lv >= level]:    # 开了新的上级，下级作废
            cur.pop(lv)
        cur[level] = len(nodes) - 1

    # 块可以跨页：讲解经常在页脚断开、下一页接着写，按页 flush 会把一段话劈两半
    for page, line in lines_all:
        m = RE_HEAD.match(line)
        if m:
            flush()
            add_node(depth[m.group(2)], m.group(3), page)
            continue
        if RE_PRACT.match(line.strip()):
            flush()
            kind = "example"
            continue
        if RE_EX.match(line):
            flush()
            kind = "example"
        elif RE_ANS.match(line):
            flush()
            kind = "answer"
        elif kind in ("answer", "example") and RE_QNO.match(line):
            # 一题一块。原先只在「解析后」切，于是「章节演练」十道题连成一个块，
            # 跨了 6 页，点「看原书」只能给出其中一页 —— 图形推理那边就是这么
            # 让题目和图对不上的。
            flush()
            kind = "example"
        elif kind == "concept" and buf and (RE_CN_NUM.match(line) or RE_SUB.match(line)):
            flush()          # 「一、」「（一）」再切一刀：不建节点，只把巨块分段，
                             # 否则常识册一节就是一个几千字的块，前端没法读
        if not buf:
            span[0] = page
        span[1] = page
        buf.append(line.strip())
    flush()
    return nodes, blocks


# ---------------------------------------------------------------- 库
def parse_shequ(rows, board, title=""):
    """rows: [(page, text)] → (nodes, blocks)。第三种形态：**浓缩速记**。

    这批资料（考前 5 页纸 / 必记 66 条 / 高频考点集锦）不像机构讲义那样有完整的
    章节树，它们是「一条一个考点」的清单：

        第一章 社会工作实务的通用过程          ← 章（level 1）
        1、会谈的主要任务：界定问题、澄清角色…  ← 考点（level 2），冒号后面就是正文
        2、会谈的技巧：主动介绍自己、治疗性沟通…

    所以**序号行本身就是考点标题**，正文往往和标题挤在同一行 —— 这是它和优路讲义
    最大的不同（那边标题独占一行、讲解在下面）。切法：冒号前当标题、冒号后当正文；
    没有冒号就整行当标题、后续行当正文。

    树是三层：**书 → 章 → 考点**。书名单独占一层，是因为社区这条线一个板块下有
    好几册（「社会工作」板块就有四册），不分书的话四本的章节混成一棵树，
    看不出这个考点是「考前 5 页纸」里的还是「必记 66 条」里的。
    没有章的册子（高频考点集锦一路 1、2、3 编下去）自动补一个「全书」章节，
    否则考点成了没爹的孤儿。
    """
    lines_all = []
    for p, t in rows:
        for ln in t.splitlines():
            ln = RE_HDR_INLINE.sub(" ", ln.rstrip())
            # 目录行必须滤掉，否则整页目录会跟正文建出第二棵重复的树 ——
            # 《（重点）社区社会工作知识》的目录页就这么变成了 148 个点开没内容的节点。
            # 另两个 parser 一直在滤，唯独这里漏了。
            if ln.strip() and not RE_JUNK.match(ln) and not RE_TOC.search(ln):
                lines_all.append((p, ln))

    nodes, blocks = [], []
    cur = {}
    buf, page, span = [], 1, [None, None]

    def flush():
        nonlocal buf
        host = max(cur.values(), key=lambda i: nodes[i]["level"]) if cur else None
        if host is not None and buf:
            md = "\n".join(buf).strip()
            if md:
                blocks.append({"node": host, "kind": "concept", "md": md,
                               "page": span[0] or page, "page_to": span[1] or page})
        buf.clear()
        span[0] = span[1] = None

    def add_node(level, title, pg):
        parent = max((lv for lv in cur if lv < level), default=None)
        nodes.append({"level": level, "title": (title or "").strip()[:80] or "（无标题）",
                      "page": pg, "parent": cur.get(parent), "board": board,
                      "sort": len(nodes)})
        for lv in [lv for lv in cur if lv >= level]:
            cur.pop(lv)
        cur[level] = len(nodes) - 1

    # 书名占第一层。标题里的「.pdf」和前面的编号去掉，树上读着才像书名。
    book = re.sub(r"\.pdf$", "", title or board, flags=re.I)
    book = re.sub(r"^[\s【】\d.、]*", "", book).strip() or board
    add_node(1, book, 1)

    for page, line in lines_all:
        m = RE_SQ_SEC.match(line)
        if m:
            flush()
            add_node(2, "第%s%s %s" % (m.group(1), m.group(2).replace(" ", ""),
                                       m.group(3)), page)
            continue
        m2 = RE_SQ_SEC2.match(line)
        if m2 and not re.search(r"[：:，,。；]", m2.group(2)):   # 带标点的多半是正文
            flush()
            add_node(2, "%s、%s" % (m2.group(1), m2.group(2).strip()), page)
            continue
        m, body = None, ""
        for rx in RE_SQ_PTS:
            m = rx.match(line)
            if m:
                g = m.groups()
                # 法条那条有两个捕获组（条号 + 正文），标题要带上「第 N 条」
                body = ("第%s条 %s" % (g[0], g[1])) if len(g) == 2 and rx is RE_SQ_PTS[2] \
                    else (g[-1] if len(g) == 1 else "".join(g[1:]))
                break
        # 只有「序号 + 够长的标题」才算考点行：`1、2、3` 这种纯枚举、
        # 以及正文里的「（1）」不能当成考点，否则一页能切出几十个空节点
        if m and len(body.strip()) >= 4:
            flush()
            body = body.strip()
            # 冒号前是考点名、冒号后是正文。
            # 没冒号的整句（「了解服务对象的来源（主动、转介、外展）和类型…」）不能整条
            # 当标题 —— 树节点会长到一行放不下。取首个短语当标题，整句照样进正文，
            # 一个字都不丢。
            cut = re.search(r"[：:]", body)
            if cut:
                head, tail = body[:cut.start()], body[cut.end():]
            elif len(body) > 28:
                brk = re.search(r"[（(，,、。]", body)
                head = body[:brk.start()] if brk and brk.start() >= 4 else body[:24]
                tail = body
            else:
                head, tail = body, ""
            if 2 not in cur:                  # 没有章的册子：补一章，别让考点成孤儿
                add_node(2, "全书", page)
            add_node(3, head.strip() or body, page)
            if tail.strip():
                buf.append(tail.strip())
                span[0] = span[1] = page
            continue
        if cur:
            buf.append(line.strip())
            span[0] = span[0] or page
            span[1] = page
    flush()
    return nodes, blocks


def nkey(board, level, title, dup, parent="", book=None):
    """节点身份键：对齐结果（basic_map）挂在它上面，所以它**必须扛得住重新解析**。

    ⚠️ 别把 sort（节点在书里的全局序号）编进来：解析规则一改，前面多一个或少一个
    节点，后面每一个的 sort 全体位移，nkey 跟着全变 —— 对齐结果（含人工改过的）
    在下一次 --reparse 时静默清零，正是 nkey 这套设计要防的事。

    改成「父标题 + 本标题 + 同名第几个」：同名标题在一册里确实会重复（各章都有
    「一、」），但重名只在**同一个父节点下**才需要区分，`dup` 是同父同名的出现序号，
    与书里别处增删无关。

    ⚠️ 一个板块下不止一册时**必须带 book**（传 basic_sources.id）：社区那条线
    「社会工作」板块有 12 册，四本书都写「第四章 老年社会工作 → 老年人的需要」，
    不带册号的话 49 组考点的 nkey 完全相同，basic_map 会把它们当成同一个考点，
    对照页上四本书的内容互相顶替。youlu/sanse 一板块一册，不传 book 保持原样 ——
    它们的人工对齐结果就挂在老 nkey 上，一改全丢。
    """
    t = re.sub(r"\s+", "", title)
    p = re.sub(r"\s+", "", parent or "")
    head = "%s#%s" % (board, book) if book else board
    return "%s|%d|%s|%s|%d" % (head, level, p, t, dup)


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def scan(con):
    """认云盘里的资料 → [(source, board(s), file_id, name, stored)]。"""
    # 同一份资料在云盘里常有好几条（聊天转存过、两个文件夹各放一份）。按文件名去重时
    # **优先要 OCR 页数多的那条** —— 「社工：党章.pdf」就有两条，一条 OCR 过 15 页、
    # 一条一页没有，按 id 撞运气的话扫描件会变成一本空书，而且不报错。
    rows = con.execute(
        "SELECT f.id,f.name,f.stored_name, "
        "  (SELECT COUNT(*) FROM sq_ocr o WHERE o.file_id=f.id) nocr "
        "FROM drive_files f "
        "WHERE f.deleted_at IS NULL AND f.is_dir=0 "
        "  AND (f.folder LIKE '公考/%' OR f.folder LIKE ?) "
        "ORDER BY nocr DESC, f.id",
        (SHEQU_ROOT + "%",)).fetchall()
    found, seen = [], set()
    for r in rows:
        if r["name"] in YOULU_BOARD:
            found.append(("youlu", [YOULU_BOARD[r["name"]]], r["id"], r["name"], r["stored_name"]))
        elif r["name"] in SANSE_BOOK:
            found.append(("sanse", SANSE_BOOK[r["name"]], r["id"], r["name"], r["stored_name"]))
        elif r["name"] in SHEQU_HOLD:
            continue
        elif r["name"] in SHEQU_BOARD and r["name"] not in seen:
            # 同一份资料在云盘里可能出现在多个文件夹（聊天转存过一次就多一条），
            # 按文件名去重：认的是资料本身，不是它躺在哪儿
            seen.add(r["name"])
            found.append(("shequ", [SHEQU_BOARD[r["name"]]], r["id"], r["name"], r["stored_name"]))
    return found


def ocr_pages(con, file_id):
    """这份文件的 OCR 文本 {页码: 文本}。没跑过 OCR 就是空字典。"""
    return {r["page"]: r["text"] for r in con.execute(
        "SELECT page,text FROM sq_ocr WHERE file_id=? AND text IS NOT NULL AND text<>''",
        (file_id,))}


def load_raw(con, only=None, force=False):
    """PDF → basic_raw。一册一次，之后全靠 --reparse。"""
    for source, boards, fid, name, stored in scan(con):
        if only and source != only:
            continue
        path = find_file(stored)
        if not path:
            print("!! 找不到文件：%s（stored=%s）" % (name, stored))
            continue
        n = pdf_pages(path)
        for board in boards:
            con.execute(
                "INSERT OR IGNORE INTO basic_sources(source,board,title,file_id,"
                "stored_name,pages) VALUES(?,?,?,?,?,?)",
                (source, board, name, fid, stored, n))
        # 社区那条线**一个板块下有好几册**（社会工作板块就有 4 册），
        # 按 (source, board) 取会永远拿到第一册的 id，把 4 册的原文全写进同一条。
        # 所以带上 file_id 一起认。
        sid = con.execute(
            "SELECT id FROM basic_sources WHERE source=? AND board=? AND file_id=?",
            (source, boards[0], fid)).fetchone()["id"]
        have = con.execute("SELECT COUNT(*) c FROM basic_raw WHERE source_id=?",
                           (sid,)).fetchone()["c"]
        if have >= n and not force:
            print("跳过（原文已在库）：%-30s %d 页" % (name, n))
            continue
        print("抽原文：%-30s %d 页 …" % (name, n), end="", flush=True)
        ocr = ocr_pages(con, fid)
        n_ocr = 0
        for p in range(1, n + 1):
            txt = page_text(path, p)
            # 没有文字层就找 OCR。**逐页回退不是整本回退**：有的册子正文是文字层、
            # 插页是扫描图，整本二选一会白丢一半。OCR 那 2331 页 8 月 19 号已经跑完
            # 落在 sq_ocr 里，这里只读不重跑。
            if len(re.sub(r"\s", "", txt or "")) < 20 and ocr.get(p):
                txt = ocr[p]
                n_ocr += 1
            xml = page_xml(path, p) if source == "sanse" else None
            con.execute("INSERT OR REPLACE INTO basic_raw(source_id,page,text,xml) "
                        "VALUES(?,?,?,?)", (sid, p, txt, xml))
        con.commit()
        print(" 完成%s" % ("（其中 %d 页取自 OCR）" % n_ocr if n_ocr else ""))


# ---------------------------------------------------------------- 扫描件笔记
# OCR 出来的行尾长这样：句子没写完就断（PDF 的软换行），或者以句号收尾。
# 判「这一行还没说完」靠的是**行尾没有终止符**，不是行长 —— 笔记体里一条要点
# 常常正好占一行半。
RE_NOTE_END = re.compile(r"[。；;！？!?：:】)）\]…]\s*$")
# 「像新起一条」的行首：编号、章节、括号序号。这类行即使上一行没收尾也要断开。
RE_NOTE_NEW = re.compile(r"^\s*(?:\d{1,3}\s*[、.．)）]|[（(]\s*[\d一二三四五六七八九十]{1,3}\s*[）)]"
                         r"|[一二三四五六七八九十]{1,3}\s*[、.．]|第\s*[一二三四五六七八九十百\d]+\s*[章节条部篇])")
# 章行。OCR 常把书名号/引号糊在章号后面（`第一章，”社会工作的内涵`），一并吃掉。
RE_NOTE_CH = re.compile(r"^\s*第\s*([一二三四五六七八九十百零〇\d]{1,4})\s*(章|节|部\s*分)"
                        r"\s*[,，.。”“\"'：:、]*\s*(.*)$")
# 表格：pdftotext / tesseract 都把表格列之间留成一大片空白。3 个以上连续空格＝换列。
RE_NOTE_COL = re.compile(r"\s{3,}")
# 页码页眉：`第 1 页 共 36 页`、`- 12 -`、孤零零一个数字
RE_NOTE_JUNK = re.compile(r"^\s*(?:第?\s*\d{1,3}\s*页\s*共\s*\d{1,3}\s*页"
                          r"|[-－]\s*\d{1,3}\s*[-－]|\d{1,3})\s*$")
# 考点名和要点之间的分隔符。OCR 把全角冒号认成 : ; ， . 都见过，所以都收，
# **但只在行首 3~24 字这个窗口里认**——再往后就是正文里的顿号了。
RE_NOTE_SEP = re.compile(r"[：:；;，,]")
# 四色笔记的正文考点锚点是「知识点一、」，后面常拖一串 OCR 糊掉的页码引用（`2219`）。
# 这本书的章标题是彩色美术字，OCR 一个都没认出来，只有目录页有 —— 所以正文全靠
# 「知识点N、」和「第N节」立骨架，不然 117 页内容会全堆在「全书」一个节点下面。
RE_NOTE_KP = re.compile(r"^[\s　]*知\s*识\s*点\s*([一二三四五六七八九十百\d]{1,3})\s*[、,.，]?\s*(.+)$")
# 章节行**允许行首粘一小段噪声**：四色笔记的侧边栏图标被 OCR 认成了字，
# 「川上 第三节 计划」「中 第一节 介入」这种前缀出现了 79 次里的 70 多次。
# 卡死 `^第` 的话这本书 117 页只认得出 2 个章节，722 个考点全平铺在「全书」下面。
# 两条防线挡住例题题干里的「第X节」：前缀不超过 6 个字符、标题不超过 30 字且不带句末标点。
RE_NOTE_SEC = re.compile(r"^[\s　]{0,4}(?:\S{0,6}?[\s　]+)?第\s*([一二三四五六七八九十百\d]{1,3})"
                         r"\s*([章节])\s*[”“\"',，、。.]*\s*(.*)$")


def _note_sec(line):
    """行 →（层级, 标题）或 None。章 level 2、节也归 level 2（这批书章下就是节，不再分层）。"""
    m = RE_NOTE_SEC.match(line)
    if not m:
        return None
    t = m.group(3).strip(" ,，。.；;”“\"'")
    body = re.sub(r"[\s　]", "", t)
    if not (2 <= len(body) <= 30) or re.search(r"[。？！?!]", t):
        return None                                  # 例题题干里的「第X节」，不是标题
    return "第%s%s %s" % (m.group(1), m.group(2), t)
# 例题：这批笔记里穿插着真题（占 13~20%）。它们是**块**不是考点 —— 当考点会把
# 目录撑爆，丢掉又可惜（那是配套练习）。所以单独标 kind=example。
RE_NOTE_EX = re.compile(r"^[\s　]*[\[【(（]?\s*(?:\d{4}\s*年|经典习题|真题)")
# 页边竖排噪声。四色笔记每页侧边印着竖排的「社工实务」，OCR 一字一行吐出来，
# 还夹着认花的乱码（`TE7` `Eeea` `ppm`）。判据只敢用两条，宁可漏滤不敢错杀：
#   ① 去掉空白后不超过 2 个字符 —— 正文里没有这么短的独立行
#   ② 短行且一个中日文字符都没有 —— 「(1)」这类编号有括号数字，不会被误伤
RE_NOTE_CJK = re.compile(r"[\u4e00-\u9fa5]")
# 序号条目：`1.南昌起义` / `10. 基本路线：…` / `★总纲`。★ 是党史讲义标重点用的。
RE_NOTE_NUM = re.compile(r"^[\s　]*(?:\d{1,3}[\s　]*[、.．)）]|[★☆◆]+)[\s　]*(\S.*)$")


def _note_noise(ln):
    t = re.sub(r"\s", "", ln)
    if len(t) <= 2:
        return True
    return len(t) <= 6 and not RE_NOTE_CJK.search(t) and not re.search(r"\d", t)


def _note_head(t):
    """考点名清洗：剥掉行首的编号和 OCR 残渣，剩下真正的名字。

    原书的 ①②③ 圈码 OCR 一律吐成 `@`（`@资料准备` `@@达成初步协议`），
    数字编号则被括号包着单独成行。这些都不是考点名的一部分。
    """
    t = re.sub(r"^[\s　@＠•·◆■□●○*\-—－]+", "", t or "")
    t = re.sub(r"^[（(]\s*[\d一二三四五六七八九十]{1,3}\s*[）)]\s*", "", t)
    t = re.sub(r"^[\d]{1,3}\s*[、.．)）]\s*", "", t)
    return re.sub(r"^[\s　”“\"']+|[\s　”“\"']+$", "", t)


def _note_table(rows):
    """连续的表格行 → Markdown 表。列宽不齐是常态，按最宽的补齐。"""
    grid = [[c.strip() for c in RE_NOTE_COL.split(ln.strip()) if c.strip()] for ln in rows]
    grid = [g for g in grid if g]
    if not grid:
        return ""
    w = max(len(g) for g in grid)
    grid = [g + [""] * (w - len(g)) for g in grid]
    # 掐掉垃圾列：整列全空，或者整列每格都只剩一个字符。后者是页边竖排的噪声
    # 被切进了表里（`_ | 本 | 本 | 、`）—— 真表格的列里总会有一格是个词。
    # **AI 校对救不了这种**：结构闸门不许它删列，它只能把垃圾原样抄回来。
    # 至少留两列，否则就不是表了。实测 253 列里掐掉 41 列，涉及 29 张表。
    keep = [c for c in range(w)
            if any(len(re.sub(r"[\s　]", "", g[c])) > 1 for g in grid)]
    if len(keep) >= 2:
        grid = [[g[c] for c in keep] for g in grid]
        w = len(keep)
    if w < 2:                                   # 只有一列，那不是表，是被误判的正文
        return ""
    out = ["| " + " | ".join(g) + " |" for g in grid]
    # Markdown 表要一行分隔线才渲染得出来；这批表大多没有表头行，
    # 所以统一把第一行当表头 —— 反正内容一个字没动。
    out.insert(1, "|" + "---|" * w)
    return "\n".join(out)


def parse_notes(rows, board, title="", numbered=False):
    """rows: [(page, text)] → (nodes, blocks)。第四种形态：**扫描件重点笔记**。

    和 parse_shequ 的分工：那个认序号（`1、会谈的主要任务：…`），这个认**形状** ——
    原书的考点名是加粗的，加粗过不了 OCR，只剩下

        社会工作的特点: 专业助人活动; 注重专业价值; 强调专业方法; …
        └─ 考点名 ─┘ ↑分隔符  └────────── 要点串 ──────────┘

    三件必须在切条目**之前**做完的事，每一件都是真跑出来的：

      ① **跨行重排。** PDF 软换行把「…社会层面的目 / 标 (解决社会问题」劈成两行，
         直接切的话「标 (解决社会问题」会变成一个新考点。原型第一版就这么错的。
      ② **表格单独走。** 这批笔记的价值一大半在表里（家庭类型、人生八阶段），
         按行读的话表格塌成一串空格被当噪声扔掉。
      ③ **页眉页脚先滤。** 每页一个「第 N 页 共 36 页」，不滤就成了考点。

    OCR 的错字（「家许数关模区」其实是竖排的「家庭教养模式」）这里**不修**：
    规则改不动它，交给 --fixtable 那一档让 AI 只改字不改结构。

    `numbered`：把「1.南昌起义」这样的序号行也当考点。**默认关**，只给写法确实
    如此的册子开（见 SHEQU_NUMBERED）—— 百题问答那类资料的答案里全是分点编号，
    一开这个开关考点数直接翻倍，多出来的全是「1.」「2.」这种碎节点。
    """
    book = re.sub(r"\.pdf$", "", title or board, flags=re.I)
    book = re.sub(r"^[\s【】\d.、]*", "", book).strip() or board
    nodes, blocks = [], []
    cur = {}

    def add_node(level, t, pg):
        parent = max((lv for lv in cur if lv < level), default=None)
        nodes.append({"level": level, "title": (t or "").strip()[:80] or "（无标题）",
                      "page": pg, "parent": cur.get(parent), "board": board,
                      "sort": len(nodes)})
        for lv in [lv for lv in cur if lv >= level]:
            cur.pop(lv)
        cur[level] = len(nodes) - 1

    def host():
        return max(cur.values(), key=lambda i: nodes[i]["level"]) if cur else None

    def add_block(kind, md, pg):
        h = host()
        if h is not None and md.strip():
            blocks.append({"node": h, "kind": kind, "md": md.strip(), "page": pg, "page_to": pg})

    add_node(1, book, 1)
    for page, text in rows:
        # ① 先按「行 / 表格行」分类，同时把软换行接回去
        segs = []
        for ln in (text or "").splitlines():
            ln = RE_HDR_INLINE.sub(" ", ln.rstrip())
            if (not ln.strip() or RE_NOTE_JUNK.match(ln) or RE_JUNK.match(ln)
                    or RE_TOC.search(ln) or _note_noise(ln)):
                continue
            kind = "tbl" if RE_NOTE_COL.search(ln.strip()) else "txt"
            # 章节行**只封口不吸收**：章标题几乎不带句末标点，让它参与合并的话，
            # 紧跟其后的正文首段会被吸进标题里，长成
            # 「第一章 社会工作的内涵、原则及主要领域社会工作在一定的社会福利制度框架下…」
            prev_head = bool(segs) and (RE_NOTE_CH.match(segs[-1][1]) or _note_sec(segs[-1][1])
                                        or RE_NOTE_KP.match(segs[-1][1])
                                        or (numbered and RE_NOTE_NUM.match(segs[-1][1])))
            if (segs and segs[-1][0] == "txt" and kind == "txt" and not prev_head
                    and not RE_NOTE_END.search(segs[-1][1])
                    and not RE_NOTE_NEW.match(ln) and not RE_NOTE_CH.match(ln)):
                segs[-1][1] += ln.strip()
            else:
                segs.append([kind, ln.strip()])
        # ② 表格连续行合成一张，其余按考点行切
        i = 0
        while i < len(segs):
            if segs[i][0] == "tbl":
                blk = []
                while i < len(segs) and segs[i][0] == "tbl":
                    blk.append(segs[i][1])
                    i += 1
                # **一行不成表。** 「1.   在公文的分类中…」这种序号后拖一大段缩进的
                # 排版，孤零零一行也满足「多空格＝换列」，整本公文知识点就这么被
                # 切成了几十张单行表。真表格总是连着好几行。
                md = _note_table(blk) if len(blk) >= 2 else ""
                if md:
                    add_block("table", md, page)
                else:                                   # 误判：把缩进压回普通正文
                    add_block("concept", re.sub(r"[\s　]{2,}", " ", "\n".join(blk)), page)
                continue
            line = segs[i][1]
            i += 1
            m = RE_NOTE_CH.match(line)
            if m:
                add_node(2, "第%s%s %s" % (m.group(1), m.group(2).replace(" ", ""),
                                           m.group(3).strip(" ,，。.”“\"'")), page)
                continue
            sec = _note_sec(line)
            if sec:
                add_node(2, sec, page)
                continue
            m = RE_NOTE_KP.match(line)
            if m:
                if 2 not in cur:
                    add_node(2, "全书", page)
                # 尾巴上那串「2219」「po2l」是原书页码引用，OCR 糊成什么样都有，
                # 不是考点名的一部分
                t = re.sub(r"[\s　]*[Pp0-9olI]{2,8}[\s　]*$", "", m.group(2)).strip()
                add_node(3, t or m.group(2).strip(), page)
                continue
            if RE_NOTE_EX.match(line):
                add_block("example", line, page)
                continue
            # 序号开头的条目（`1.南昌起义`、`10. 基本路线：…`）：**先把序号剥掉再判分隔符**。
            # 不剥的话「10. 基本路线」里的那个点会被当成名/值的分界。
            num = RE_NOTE_NUM.match(line) if numbered else None
            body = num.group(1) if num else line
            if numbered and not num:
                # 这类册子的写法是「序号行＝考点、后面几行＝它的正文」。不带序号的行
                # 一律当正文 —— 否则「又称八一起义，1927 年…」里那个逗号会被当成
                # 名/值分界，正文自己又变成一个考点。
                add_block("concept", line, page)
                continue
            sep = RE_NOTE_SEP.search(body[:30])
            head = _note_head(body[:sep.start()]) if sep else ""
            if not sep and num and len(re.sub(r"[\s　]", "", body)) >= 3:
                # 标题独占一行、正文在后续行（党史讲义就是这个写法）
                if 2 not in cur:
                    add_node(2, "全书", page)
                add_node(3, _note_head(body)[:60] or body[:60], page)
                continue
            # 标题剥完符号还剩两个字才算考点。剥出来是空的（`(3)` `@@`）说明这只是
            # 正文里的一个编号，当考点会在树上堆出一排点开没内容的「(1)(2)(3)」
            if sep and 3 <= sep.start() <= 24 and len(body) - sep.end() >= 6 and len(head) >= 2:
                if 2 not in cur:                        # 没有章的册子，补一层免得考点成孤儿
                    add_node(2, "全书", page)
                add_node(3, head, page)
                add_block("concept", body[sep.end():], page)
            else:
                add_block("concept", line, page)         # 接着上一个考点往下写
    return nodes, blocks


# 纯日期的考点名：「1920 年初」「2026 年 1 月 5 日」。时政和党史年表里成片出现，
# 树上摆着一排日期看不出讲了什么。
RE_DATE_ONLY = re.compile(r"^[\s　]*\d{1,4}\s*年(\s*\d{1,2}\s*月)?(\s*\d{1,2}\s*日)?"
                          r"[\s　]*(初|末|底|电|前后)?[\s　]*$")


def date_titles(nodes, blocks):
    """把「1920 年初」这种纯日期考点名补成「1920 年初 · 中国共产党上海发起组成立」。

    日期本身不是考点，它是这条考点**发生在什么时候**。正文的头一句才是内容，
    拼上去树上才认得出。原文一个字不动，只动展示用的标题。
    """
    first = {}
    for b in blocks:
        first.setdefault(b["node"], b)
    n_fix = 0
    for i, n in enumerate(nodes):
        if n["level"] < 3 or not RE_DATE_ONLY.match(n["title"] or ""):
            continue
        b = first.get(i)
        if not b or b.get("kind") == "table":
            continue
        # 正文头一句常常把日期又写了一遍（时政稿就是这个体例），
        # 直接拼会得到「2025 年 12 月 31 日 · 2025 年 12 月 31 日」。往后再取一句。
        flat = re.sub(r"[\s　]+", " ", b["md"]).strip()
        bare = re.sub(r"[\s　]", "", n["title"])
        head = ""
        for seg in re.split(r"[，,。；;]", flat):
            seg = seg.strip()
            t = re.sub(r"[\s　]", "", seg)
            if not t or RE_DATE_ONLY.match(seg) or t in bare or bare in t:
                continue
            head = seg
            break
        if 2 <= len(head) <= 40:
            n["title"] = "%s · %s" % (n["title"].strip(), head)
            n_fix += 1
    return n_fix


def prune_empty(nodes, blocks):
    """剪掉「点开什么都没有」的节点：无正文块、又没有子节点。

    目录页滤干净之后仍会剩一批空壳 —— 书里的过渡标题（「第二节」下面直接跟着
    「一、」，中间那层什么都不挂）、以及考点行正则误命中的短行。它们在树上占一格、
    点进去一片空白，比少一个考点更烦人。

    只剪**没有子节点**的，所以剪掉谁都不会让别人的 parent 悬空；剪完可能让上一层
    变成新的空壳（父节点唯一的孩子被剪了），所以要迭代到不动点。
    level 1 是书名，永远留着 —— 它是树根，剪了整本书就没入口了。

    **「没有正文」不等于「没有内容」**：这批速记资料里大量考点是一句话说完的
    （「明确 30 日的离婚冷静期」「一般在 100 户至 700 户的范围内设立居民委员会」），
    解析时整句当了标题、正文自然是空 —— 而它们恰恰是最该背的判断题素材。
    第一版判据把这类连同真空壳一起剪了 213 个，抽查才发现。所以标题够长的一律留下，
    只剪标题短到不成话的（「全书」「二」「（三）」这种正则误命中的碎片）。
    """
    have_block = {b["node"] for b in blocks}
    def is_junk(n):
        return len(re.sub(r"[\s　]", "", n["title"] or "")) < MIN_KEEP_TITLE
    dropped = set()
    while True:
        alive = [n for n in nodes if n["_i"] not in dropped]
        have_kid = {n["parent"] for n in alive if n["parent"] is not None}
        drop = {n["_i"] for n in alive
                if n["level"] >= 2 and n["_i"] not in have_block
                and n["_i"] not in have_kid and is_junk(n)}
        if not drop:
            return [n for n in nodes if n["_i"] not in dropped], len(dropped)
        dropped |= drop


def parse_all(con, only=None):
    """从 basic_raw 解析 → {(source, board): (nodes, blocks)}。"""
    out = {}
    for source, boards, _fid, name, _stored in scan(con):
        if only and source != only:
            continue
        sid = con.execute(
            "SELECT id FROM basic_sources WHERE source=? AND board=? AND file_id=?",
            (source, boards[0], _fid)).fetchone()
        if not sid:
            print("!! %s 还没抽原文，先跑 --load" % name)
            continue
        rows = con.execute("SELECT page,text,xml FROM basic_raw WHERE source_id=? "
                           "ORDER BY page", (sid["id"],)).fetchall()
        if not rows:
            continue
        if source == "sanse":
            nodes, blocks = parse_sanse([(r["page"], r["xml"] or "") for r in rows], boards)
        elif source == "shequ":
            pages = [(r["page"], r["text"] or "") for r in rows]
            if name in SHEQU_NOTES:
                nodes, blocks = parse_notes(pages, boards[0], name,
                                            numbered=name in SHEQU_NUMBERED)
            else:
                nodes, blocks = parse_shequ(pages, boards[0], name)
            n_dt = date_titles(nodes, blocks)
            if n_dt:
                print("   补名 %-30s 纯日期考点 %d 个" % (name[:30], n_dt))
        else:
            nodes, blocks = parse_youlu([(r["page"], r["text"] or "") for r in rows], boards[0])
        for i, n in enumerate(nodes):                       # 块挂到节点上，按板块分组
            n["_i"] = i
        for b in blocks:
            b["board"] = nodes[b["node"]]["board"] if nodes else boards[0]
        for board in boards:
            bn = [n for n in nodes if n["board"] == board]
            bb = [b for b in blocks if b["node"] in {n["_i"] for n in bn}]
            bn, n_cut = prune_empty(bn, bb)
            if n_cut:
                print("   剪枝 %-30s 去掉空壳节点 %d 个" % (name[:30], n_cut))
            idx = {n["_i"] for n in bn}
            # 键必须带上 file_id：社区那条线一个板块下有四册，只按 (source,board)
            # 做键的话四册互相覆盖，最后只剩一册 —— 而且不报错，只是考点少了四分之三。
            out[(source, board, _fid)] = (bn, [b for b in blocks if b["node"] in idx])
    return out


def report(parsed):
    print("\n%-6s %-12s %6s %6s %6s   %s" % ("来源", "板块", "章", "考点", "块", "前 3 个考点"))
    print("-" * 88)
    for (source, board, _fid), (nodes, blocks) in sorted(parsed.items(), key=lambda x: x[0][:2]):
        l1 = [n for n in nodes if n["level"] == 1]
        l2 = [n for n in nodes if n["level"] == 2]
        head = " / ".join(n["title"][:12] for n in l2[:3])
        print("%-6s %-12s %6d %6d %6d   %s" % (source, board, len(l1), len(l2), len(blocks), head))
        kinds = {}
        for b in blocks:
            kinds[b["kind"]] = kinds.get(b["kind"], 0) + 1
        print("%-19s 块类型：%s" % ("", "  ".join("%s=%d" % kv for kv in sorted(kinds.items()))))


ALIGN_SYS = ("你是公务员考试行测教研组长，熟悉各机构讲义的考点划分。"
             "只输出 JSON，不要解释。")


def align(con, board=None, dry=False):
    """建板块考点大纲，并把两套资料的考点挂上去。

    **不是标题匹配**：实测两套书的划分维度就不一样 —— 优路言语按题型分（语境分析、
    查找细节能力），三色按思维分（转折关系思维、因果关系思维），完全同名 0 个。
    所以让 AI 先归纳出一份该板块的标准考点大纲，再把两边的节点各自挂上去（多对一）。

    人工改过的（by='manual'）一律不动，AI 重跑也覆盖不掉。
    """
    import json
    import aiclient
    cfg = json.load(open(CONFIG, encoding="utf-8")) if os.path.exists(CONFIG) else {}
    boards = [board] if board else [r["board"] for r in con.execute(
        "SELECT DISTINCT board FROM basic_nodes ORDER BY board")]
    for bd in boards:
        rows = con.execute(
            "SELECT n.id,n.source,n.title,n.nkey,p.title ptitle FROM basic_nodes n "
            "LEFT JOIN basic_nodes p ON n.parent_id=p.id "
            "WHERE n.board=? AND n.level>=2 ORDER BY n.source,n.sort", (bd,)).fetchall()
        if not rows:
            continue
        listing = "\n".join(
            "%d. [%s] %s（出自：%s）" % (i, "优路" if r["source"] == "youlu" else "三色",
                                    r["title"], r["ptitle"] or "-")
            for i, r in enumerate(rows))
        prompt = (
            "板块：%s\n\n下面是两套讲义各自的考点条目（编号 → 条目）：\n%s\n\n"
            "请归纳出这个板块的标准考点大纲（%d~%d 个考点，按考试常见顺序排），"
            "并把上面每个条目挂到大纲考点下。一个条目只挂一个最贴切的考点；"
            "两套讲义划分维度不同是正常的，允许一个考点下只有一套讲义的条目。\n"
            "输出 JSON：{\"topics\":[{\"name\":\"考点名\",\"items\":[编号,编号]}]}"
            % (bd, listing, max(6, len(rows) // 4), max(10, len(rows) // 2)))
        try:
            data = json.loads(aiclient.chat(
                [{"role": "system", "content": ALIGN_SYS}, {"role": "user", "content": prompt}],
                tier="fast", temperature=0.2, max_tokens=3000, timeout=300,
                json_mode=True, cfg=cfg, retries=1))
        except Exception as e:                       # 一个板块失败不该带走其余板块
            print("!! %s 对齐失败：%s" % (bd, str(e)[:120]))
            continue
        topics = [t for t in data.get("topics", []) if t.get("name")]
        n_map = 0
        print("\n== %s：%d 个考点" % (bd, len(topics)))
        if not dry:
            # AI 挂的映射先整体清掉再重挂：AI 把某条从考点 A 改判到 B 时，
            # INSERT OR REPLACE 只会写 (B,…)，(A,…) 那行留在库里 —— 于是这条
            # 同时挂在两个考点下，对照页的计数虚高，回填 topic_id 的子查询
            # 也会在两行里随机取一行。人工挂的（manual）不动。
            con.execute("DELETE FROM basic_map WHERE board=? AND \"by\"<>'manual'", (bd,))
        for k, t in enumerate(topics):
            items = [rows[i] for i in t.get("items", [])
                     if isinstance(i, int) and 0 <= i < len(rows)]
            ny = sum(1 for r in items if r["source"] == "youlu")
            print("   %-22s 优路%d 三色%d" % (t["name"][:20], ny, len(items) - ny))
            n_map += len(items)
            if dry:
                continue
            con.execute("INSERT OR IGNORE INTO basic_topics(board,name,sort) VALUES(?,?,?)",
                        (bd, t["name"], k))
            tid = con.execute("SELECT id FROM basic_topics WHERE board=? AND name=?",
                              (bd, t["name"])).fetchone()["id"]
            con.execute("UPDATE basic_topics SET sort=? WHERE id=?", (k, tid))
            for r in items:
                # by 是 SQL 关键字的一半（GROUP BY），列名一律加引号，不然语法报错
                keep = con.execute('SELECT 1 FROM basic_map WHERE nkey=? AND source=? '
                                   'AND "by"=\'manual\'', (r["nkey"], r["source"])).fetchone()
                if keep:                              # 人工挂过的，AI 不许动
                    continue
                con.execute(
                    'INSERT OR REPLACE INTO basic_map(topic_id,board,source,nkey,"by",'
                    'confidence) VALUES(?,?,?,?,\'ai\',0.8)',
                    (tid, bd, r["source"], r["nkey"]))
        if not dry:
            # 重跑时 AI 常给出**不同名**的考点划分，旧考点会留成孤儿（一条映射都没有）
            # —— 对照页照样把它们列出来，点进去两边都是空的。没人挂的就删掉。
            gone = con.execute(
                "DELETE FROM basic_topics WHERE board=? AND id NOT IN "
                "(SELECT topic_id FROM basic_map)", (bd,)).rowcount
            # 回填 nodes.topic_id：接口按它一次 join 就能拿到，省得每次去 map 里绕。
            # **必须带 source**：nkey 只在一册内唯一，跨册同名会认错人。
            con.execute("UPDATE basic_nodes SET topic_id=(SELECT topic_id FROM basic_map "
                        "WHERE basic_map.nkey=basic_nodes.nkey "
                        "AND basic_map.source=basic_nodes.source) WHERE board=?", (bd,))
            con.commit()
            print("   已挂 %d 条%s" % (n_map, "，清掉 %d 个没人挂的旧考点" % gone if gone else ""))


SQALIGN_SYS = ("你是社区工作者招聘考试的教研组长，熟悉社工初级、社区建设、基层治理、"
               "党建和法律常识这几门的考点划分。你的判断依据是考试怎么考，不是书怎么排版。")


def _align_ask(cfg, prompt, chunk, listing, have, board, book):
    """问一次 AI；**返回空就把这批对半劈了再问**。

    这类「给我 N 条的归类」任务，输出长度跟着 N 走。推理模型的正文额度还要跟
    推理段抢，条目一多就整批返回空串 —— 表现出来是 `Expecting value: line 1
    column 1`，看着像模型不听话，其实是被截断了。批次越小越稳，所以失败就减半重问，
    而不是整批丢掉。
    """
    import json
    import aiclient
    for size in (len(chunk), max(1, len(chunk) // 2), max(1, len(chunk) // 4)):
        if size < len(chunk):
            print("      返回空，把这批 %d 条劈成 %d 条再问" % (len(chunk), size), flush=True)
            return _align_split(cfg, chunk, have, board, book, size)
        try:
            txt = aiclient.chat(
                [{"role": "system", "content": SQALIGN_SYS}, {"role": "user", "content": prompt}],
                tier="fast", temperature=0.2, max_tokens=8000, timeout=240,
                json_mode=True, cfg=cfg, retries=1)
            return json.loads(txt)
        except Exception:                                        # noqa: BLE001
            continue
    return None


def _align_split(cfg, chunk, have, board, book, size):
    """把一批切成小份分别问，结果合并回原批的下标。"""
    import json
    import aiclient
    out = {"assign": []}
    for a in range(0, len(chunk), size):
        part = chunk[a:a + size]
        listing = "\n".join("%d. %s（所在章节：%s）"
                            % (i, r["title"][:60], (r["ptitle"] or "-")[:30])
                            for i, r in enumerate(part))
        prompt = ("板块：%s\n这一批条目出自《%s》。\n\n%s"
                  "下面是这一册的考点条目：\n%s\n\n"
                  "请把每个条目挂到一个标准考点下：能挂到已有考点就挂，"
                  "确实是新题目才新增考点名（新增要克制）。考点名用考试里的通用说法，6~14 个字。\n"
                  '输出 JSON：{"assign":[{"i":编号,"topic":"考点名"}]}'
                  % (board, book[:40], have, listing))
        try:
            d = json.loads(aiclient.chat(
                [{"role": "system", "content": SQALIGN_SYS}, {"role": "user", "content": prompt}],
                tier="fast", temperature=0.2, max_tokens=8000, timeout=240,
                json_mode=True, cfg=cfg, retries=1))
        except Exception:                                        # noqa: BLE001
            continue
        for it in d.get("assign", []):
            if isinstance(it.get("i"), int) and 0 <= it["i"] < len(part):
                out["assign"].append({"i": a + it["i"], "topic": it.get("topic")})
    return out if out["assign"] else None


def align_shequ(con, board=None, dry=False, batch=60):
    """社区线的考点对照：把十几册资料里讲同一件事的考点归到一个标准考点下。

    和 align()（行测那套）的两点不同，都是被资料形态逼出来的：

      ① **一个板块摞着十几册**，不是两套。所以来源标签得用书名，
         「优路/三色」那种二选一的写法在这儿没有意义。
      ② **考点太多，一次喂不下。** 社会工作板块 1239 个考点，一个 prompt 装不下，
         硬塞进去模型只会敷衍。所以逐册分批，**每批都带上已经攒出来的大纲**，
         让它优先往已有考点上挂、真挂不上才新增 —— 分批建大纲最怕的就是
         每批各造一套名字，最后一个考点在库里有五个近义词。

    先量过才决定走 AI：这批资料跨册**同名**考点只有 85/1239（法律法规 0 个），
    靠标题匹配对不起来 —— 和行测那次「两套书同名 0 个」是同一个结论。
    """
    import json
    import aiclient
    cfg = aiclient.load_cfg()
    boards = [board] if board else [r["board"] for r in con.execute(
        "SELECT DISTINCT board FROM basic_nodes WHERE source='shequ' ORDER BY board")]
    for bd in boards:
        books = con.execute(
            "SELECT DISTINCT s.id, s.title FROM basic_sources s "
            "JOIN basic_nodes n ON n.source_id=s.id WHERE n.board=? AND n.source='shequ' "
            "ORDER BY s.id", (bd,)).fetchall()
        outline, assign = [], {}          # 考点名列表 / nkey → 考点名
        for bk in books:
            rows = con.execute(
                "SELECT n.nkey, n.title, p.title ptitle FROM basic_nodes n "
                "LEFT JOIN basic_nodes p ON p.id=n.parent_id "
                "WHERE n.source_id=? AND n.level>=3 ORDER BY n.sort", (bk["id"],)).fetchall()
            for a in range(0, len(rows), batch):
                chunk = rows[a:a + batch]
                listing = "\n".join("%d. %s（所在章节：%s）"
                                    % (i, r["title"][:60], (r["ptitle"] or "-")[:30])
                                    for i, r in enumerate(chunk))
                have = ("已经归纳出的考点（**优先往这些上面挂**）：\n%s\n\n"
                        % "、".join(outline)) if outline else ""
                prompt = (
                    "板块：%s\n这一批条目出自《%s》。\n\n%s"
                    "下面是这一册的考点条目：\n%s\n\n"
                    "请把每个条目挂到一个标准考点下：能挂到已有考点就挂，"
                    "确实是新题目才新增考点名（新增要克制，一个板块总共不超过 60 个考点）。"
                    "考点名用考试里的通用说法，6~14 个字。\n"
                    '输出 JSON：{"assign":[{"i":编号,"topic":"考点名"}]}'
                    % (bd, bk["title"][:40], have, listing))
                data = _align_ask(cfg, prompt, chunk, listing, have, bd, bk["title"])
                if data is None:                    # 一批失败不带走其余批次
                    print("!! %s / %s 第 %d 批放弃"
                          % (bd, bk["title"][:20], a // batch + 1), flush=True)
                    continue
                for it in data.get("assign", []):
                    i, name = it.get("i"), (it.get("topic") or "").strip()
                    if not isinstance(i, int) or not (0 <= i < len(chunk)) or not name:
                        continue
                    if name not in outline:
                        outline.append(name)
                    assign[chunk[i]["nkey"]] = name
                print("   %-28s 第 %d 批 %3d 条 → 大纲累计 %d 个"
                      % (bk["title"][:26], a // batch + 1, len(chunk), len(outline)), flush=True)
        print("== %s：%d 个考点，挂上 %d 条" % (bd, len(outline), len(assign)), flush=True)
        if dry or not assign:
            continue
        con.execute("DELETE FROM basic_map WHERE board=? AND source='shequ' "
                    "AND \"by\"<>'manual'", (bd,))
        for k, name in enumerate(outline):
            con.execute("INSERT OR IGNORE INTO basic_topics(board,name,sort) VALUES(?,?,?)",
                        (bd, name, k))
            con.execute("UPDATE basic_topics SET sort=? WHERE board=? AND name=?", (k, bd, name))
        for nk, name in assign.items():
            t = con.execute("SELECT id FROM basic_topics WHERE board=? AND name=?",
                            (bd, name)).fetchone()
            if not t:
                continue
            if con.execute('SELECT 1 FROM basic_map WHERE nkey=? AND source=\'shequ\' '
                           'AND "by"=\'manual\'', (nk,)).fetchone():
                continue                              # 人工挂过的不动
            con.execute('INSERT OR REPLACE INTO basic_map(topic_id,board,source,nkey,"by",'
                        'confidence) VALUES(?,?,\'shequ\',?,\'ai\',0.75)', (t["id"], bd, nk))
        gone = con.execute("DELETE FROM basic_topics WHERE board=? AND id NOT IN "
                           "(SELECT topic_id FROM basic_map)", (bd,)).rowcount
        con.execute("UPDATE basic_nodes SET topic_id=(SELECT topic_id FROM basic_map "
                    "WHERE basic_map.nkey=basic_nodes.nkey AND basic_map.source='shequ') "
                    "WHERE board=? AND source='shequ'", (bd,))
        con.commit()
        print("   已写库%s" % ("，清掉 %d 个没人挂的考点" % gone if gone else ""), flush=True)


def linkq(con, board=None, dry=False):
    """把考点接到真题题型上：basic_topics.qtypes_json ← real_questions.qtype。

    **不给 7606 道题逐题打考点标签**：真题的 qtype 已经细到「语境分析 / 排列组合 /
    削弱论证」，和考点大纲多数同名（大纲本来就是从讲义目录归纳的），一个考点记下
    它对应哪几个 qtype 就够用，也看得懂、改得动。

    先规则（归一化后同名或包含），剩下的才问 AI —— 实测规则能命中一半以上。
    """
    import json

    import aiclient

    from mods import realref

    def norm(s):
        s = re.sub(r"\s+", "", s or "")
        s = re.sub(r"^[（(]?[一二三四五六七八九十\d]+[)）、.．]", "", s)
        return re.sub(r"(问题|推理|判断|分析|法|题)$", "", s)

    cfg = json.load(open(CONFIG, encoding="utf-8")) if os.path.exists(CONFIG) else {}
    boards = [board] if board else [r["board"] for r in con.execute(
        "SELECT DISTINCT board FROM basic_topics ORDER BY board")]
    for bd in boards:
        # 口径走 realref（能不能发给人做 / 板块→卷面模块），别在这儿另写一份。
        # HAVING/GROUP BY 里不能写别名 qtype：和 q.qtype / e.qtype 撞名，SQLite 直接
        # 报 ambiguous（realq.py 那边同一个坑已经踩过一次）
        qexpr = realref.qtype_expr("q", "e")
        qts = [r["qt"] for r in con.execute(
            "SELECT %s qt, COUNT(*) c "
            "FROM real_questions q LEFT JOIN real_explains e ON e.qid=q.id "
            "WHERE q.module=? AND %s "
            "GROUP BY %s HAVING %s<>'' ORDER BY c DESC"
            % (qexpr, realref.servable("q", "e"), qexpr, qexpr),
            (realref.BOARD_MODULE.get(bd, bd),))]
        tops = con.execute("SELECT id,name FROM basic_topics WHERE board=? ORDER BY sort",
                           (bd,)).fetchall()
        if not qts or not tops:
            print("== %-12s 题型 %d 个 / 考点 %d 个，跳过" % (bd, len(qts), len(tops)))
            continue
        hit = {t["id"]: [] for t in tops}
        left = []
        for q in qts:                                    # 第一遍：规则
            nq = norm(q)
            got = [t["id"] for t in tops
                   if norm(t["name"]) == nq or (len(nq) > 1 and nq in norm(t["name"]))]
            if got:
                hit[got[0]].append(q)
            else:
                left.append(q)
        if left:                                         # 第二遍：剩下的问 AI
            prompt = ("板块：%s\n考点大纲：\n%s\n\n真题里还没归位的题型：\n%s\n\n"
                      "把每个题型归到最贴切的考点下（归不进去就不归）。"
                      "输出 JSON：{\"map\":{\"题型名\":\"考点名\"}}"
                      % (bd, "\n".join("- " + t["name"] for t in tops),
                         "\n".join("- " + q for q in left)))
            try:
                data = json.loads(aiclient.chat(
                    [{"role": "system", "content": ALIGN_SYS},
                     {"role": "user", "content": prompt}],
                    tier="fast", temperature=0.2, max_tokens=1500, timeout=200,
                    json_mode=True, cfg=cfg, retries=1))
                byname = {t["name"]: t["id"] for t in tops}
                for q, tname in (data.get("map") or {}).items():
                    if q in left and tname in byname:
                        hit[byname[tname]].append(q)
            except Exception as e:
                print("!! %s 题型归位的 AI 那一步失败（规则的结果照常写）：%s" % (bd, str(e)[:90]))
        n_t = sum(1 for v in hit.values() if v)
        print("== %-12s 题型 %d 个 → 挂上 %d 个考点" % (bd, len(qts), n_t))
        for t in tops:
            if hit[t["id"]]:
                print("   %-22s ← %s" % (t["name"][:20], " / ".join(hit[t["id"]])))
        if dry:
            continue
        for t in tops:
            con.execute("UPDATE basic_topics SET qtypes_json=? WHERE id=?",
                        (json.dumps(hit[t["id"]], ensure_ascii=False), t["id"]))
        con.commit()


def audit(con):
    """覆盖率：入库正文字数 / 原文字数。丢内容是这类管线最容易犯又最难发现的错 ——
    解析器一个正则写宽了就能把整段吃掉，报告里看不出来（节点数照样好看）。

    分母扣掉页眉页脚和目录页；三色的 {{r|…}} 标记也要扣，不然虚高。

    **按册聚合，不按板块**：三色一册装两个板块，原文只挂在册子第一个 source_id 上，
    逐板块算的话另一半分母是 0 —— 审计器自己先报了个假警。
    """
    print("\n%-6s %-30s %8s %8s %7s  %s"
          % ("来源", "册", "原文字", "入库字", "覆盖率", "提示"))
    print("-" * 92)
    books = {}
    for r in con.execute("SELECT id,source,board,title,stored_name FROM basic_sources "
                         "ORDER BY source,id"):
        books.setdefault((r["source"], r["stored_name"] or r["board"]), []).append(r)
    for (source, _stored), rows in books.items():
        n_raw = 0
        for r in rows:
            raw = "".join(x["text"] or "" for x in con.execute(
                "SELECT text FROM basic_raw WHERE source_id=? ORDER BY page", (r["id"],)))
            # 口径必须和 parser 一模一样（先抠行内页眉、再滤整行页眉/页码/目录），
            # 否则分母把「官方网站:www.youlu.com  -2-」这类算进去，覆盖率白掉几个点
            lines = [RE_HDR_INLINE.sub(" ", ln).strip() for ln in raw.splitlines()]
            lines = [ln for ln in lines
                     if ln and not RE_JUNK.match(ln) and not RE_TOC.search(ln)]
            n_raw += sum(len(re.sub(r"\s", "", ln)) for ln in lines)
        n_got = 0
        for r in rows:
            got = "".join(x["content_md"] or "" for x in con.execute(
                "SELECT content_md FROM basic_blocks b JOIN basic_nodes n ON b.node_id=n.id "
                "WHERE n.source_id=?", (r["id"],)))
            # 表格的 `|` 和 `|---|` 是渲染用的骨架，不是原文的字，计进去会让带表的书
            # 覆盖率虚高十几个点（12.社会工作综合能力重点笔记 141 张表就抬了 5 个点）
            got = re.sub(r"^\|[\s:|-]+\|$", "", got, flags=re.M).replace("|", "")
            n_got += len(re.sub(r"\s", "", re.sub(r"\{\{[rbg]\|", "", got).replace("}}", "")))
            # **节点标题也是入库的正文。** 速记和笔记这两种形态把「考点名」放进 title、
            # 只有冒号后面的要点串进 block —— 只数 block 的话，考点名那部分字数凭空
            # 蒸发，整批书被系统性低估十几个点（实测 6.社会工作实务重点笔记 75.8%
            # → 92.4%）。level 1 是书名、「全书」是解析器补的占位，都不是原文，不算。
            n_got += sum(len(re.sub(r"\s", "", x["title"] or "")) for x in con.execute(
                "SELECT title FROM basic_nodes WHERE source_id=? AND level>=2 "
                "AND title<>'全书'", (r["id"],)))
        pct = n_got / n_raw * 100 if n_raw else 0
        held = (rows[0]["title"] or "") in SHEQU_HOLD
        tip = "暂缓入库（见 SHEQU_HOLD）" if held else (
            "偏低，查解析" if pct < 70 else ("超 100%，可能重复入库" if pct > 115 else ""))
        print("%-6s %-30s %8d %8d %6.1f%%  %s"
              % (source, (rows[0]["title"] or rows[0]["board"])[:30], n_raw, n_got, pct, tip))


def drop_held(con):
    """把已经进了 SHEQU_HOLD 的书从考点树上撤下来。

    往 HOLD 里加一本书只是让 scan 不再返回它，**库里上一轮入的节点不会自己消失**
    —— 审计单上它照样显示 100%，看着像正常入库的。
    只删解析层（basic_nodes/blocks），`basic_sources` 和 `basic_raw` 原样留着：
    原文抽一次很贵，哪天换了 OCR 引擎，从 HOLD 里挪走名字就能直接 --reparse 放行。
    """
    for r in con.execute("SELECT id,title FROM basic_sources WHERE title IN (%s)"
                         % ",".join("?" * len(SHEQU_HOLD)), sorted(SHEQU_HOLD)):
        n = con.execute("SELECT COUNT(*) c FROM basic_nodes WHERE source_id=?",
                        (r["id"],)).fetchone()["c"]
        if not n:
            continue
        con.execute("DELETE FROM basic_blocks WHERE node_id IN "
                    "(SELECT id FROM basic_nodes WHERE source_id=?)", (r["id"],))
        con.execute("DELETE FROM basic_nodes WHERE source_id=?", (r["id"],))
        con.commit()
        print("撤下 %-40s 节点 %d（原文层保留）" % (r["title"][:40], n))


# ---------------------------------------------------------------- 表格校对
FIXTBL_SYS = (
    "你是社会工作者职业资格考试的教研编辑，正在校对一份从扫描版笔记 OCR 出来的表格。"
    "OCR 会认错字（「盲目」认成「言目」、「尊重」认成「苯重」），"
    "也会把竖排的合并单元格糊成一串乱码（「家庭教养模式」认成「家许数关模区」）。"
    "你的唯一任务是**把错字改回它本来的字**。"
)
FIXTBL_RULES = (
    "严格遵守：\n"
    "1. 只改字，不改结构。行数、每行的列数、单元格的先后顺序必须和原表一模一样。\n"
    "2. 不许增删行或列，不许合并或拆分单元格，空单元格保持为空。\n"
    "3. 只在确信原字是什么时才改；看不出来就原样抄回，**不许猜、不许补写内容**。\n"
    "4. 不解释、不加表头、不写任何表格以外的字，直接输出改好的 Markdown 表格。\n"
)


def _tbl_shape(md):
    """表格的形状：每行几列。校对前后必须完全一致 —— 这是唯一的验收标准。"""
    rows = []
    for ln in (md or "").splitlines():
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        if re.fullmatch(r"\|[\s:|-]+\|", ln):        # 分隔线不算数据行
            continue
        rows.append(len(ln.strip("|").split("|")))
    return rows


def fixtable(con, limit=0, board=None, dry=False):
    """把 OCR 出来的表格交给 AI 只改字不改结构。

    **结构是硬闸门**：校对回来的表只要行数或列数和原表对不上，一律丢弃、留原文。
    模型很容易顺手把表「整理」得更好看 —— 合并重复的表头、补一列说明、删掉空单元格 ——
    那样改出来的就不是原书的表了。备考资料错一个字就是错一道题，宁可留着脏字。

    只动 kind='table' 的块，正文一个字不碰（正文规则已经切得很干净，没有让 AI
    改写的理由，那只会引进幻觉）。
    """
    import aiclient
    cfg = aiclient.load_cfg()
    q = ("SELECT b.id, b.content_md, n.title, s.title book FROM basic_blocks b "
         "JOIN basic_nodes n ON n.id=b.node_id JOIN basic_sources s ON s.id=n.source_id "
         "WHERE b.kind='table' AND n.source='shequ'")
    args = []
    if board:
        q += " AND n.board=?"
        args.append(board)
    q += " ORDER BY b.id"
    rows = con.execute(q, args).fetchall()
    if limit:
        rows = rows[:limit]
    print("待校对表格 %d 张%s" % (len(rows), "（dry-run，不写库）" if dry else ""), flush=True)

    def one(r):
        """一张表 →（block_id, 改好的 md）或 None。异常一律当「留原文」。"""
        want = _tbl_shape(r["content_md"])
        if not want:
            return None
        try:
            out = aiclient.chat(
                [{"role": "system", "content": FIXTBL_SYS},
                 {"role": "user", "content": "%s\n这张表出自《%s》，所在考点是「%s」。\n\n%s"
                  % (FIXTBL_RULES, r["book"], r["title"], r["content_md"])}],
                # 超时给到 90 秒：单张实测 2~7 秒，个别表能让模型想上两分钟。
                # （早先把「94 张里 79 张失败」归咎于并发太高，降到 2 路照样失败 ——
                #  真正的原因是账户额度用尽、服务端秒回 402，被 except 压成了「超时」。
                #  见 one() 里的 fatal 分支。并发本身没问题。）
                tier="fast", temperature=0.1, max_tokens=2000, timeout=90,
                cfg=cfg, retries=0)
        except Exception as e:                                   # noqa: BLE001
            # **不要把所有异常都记成超时。** 额度用完时服务端秒回 402，整批 94 张
            # 全部记成「超时留原文」跑完还报 exit 0 —— 看日志会以为是网络慢，
            # 实际上一次都没调通。账户类的错误要原样喊出来并让整批停下。
            msg = str(e)
            if any(k in msg for k in ("402", "401", "403", "Payment", "quota",
                                      "insufficient", "Unauthorized")):
                return ("fatal", r["id"], msg[:120])
            return ("timeout", r["id"], None)
        md = re.sub(r"^```[a-z]*\s*|\s*```$", "", (out or "").strip(), flags=re.M).strip()
        if _tbl_shape(md) != want:
            return ("shape", r["id"], None)
        if md == r["content_md"].strip():
            return ("same", r["id"], None)
        return ("ok", r["id"], md)

    # 写库留在主线程：sqlite 的连接不跨线程用。线程只负责等网络。
    from concurrent.futures import ThreadPoolExecutor
    tally = {"ok": 0, "same": 0, "shape": 0, "timeout": 0, "fatal": 0}
    fatal = None
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, res in enumerate(pool.map(one, rows), 1):
            if not res:
                continue
            kind, bid, md = res
            tally[kind] += 1
            if kind == "fatal":
                fatal = fatal or md
                continue
            if kind == "ok":
                print("  [%d/%d] 改写 block %d" % (i, len(rows), bid), flush=True)
                if not dry:
                    # **每条都 commit**：不提交的话这个连接会攥着写锁跑完全程，
                    # 而工作线程里 aiclient 的用量记账要写同一个库 —— 整批调用的
                    # 账全部记不上，只在日志里留一行「database is locked」。
                    con.execute("UPDATE basic_blocks SET content_md=? WHERE id=?", (md, bid))
                    con.commit()
    if not dry:
        con.commit()
    print("校对完成：改写 %d 张，本来就对 %d 张，结构不符丢弃 %d 张，超时留原文 %d 张"
          % (tally["ok"], tally["same"], tally["shape"], tally["timeout"]))
    if fatal:
        print("!! %d 张没能校对：AI 调用被拒 —— %s\n"
              "   这不是网络慢，是账户/额度的问题。表格原文一个字没动，"
              "额度恢复后重跑 --fixtable 即可（幂等）。" % (tally["fatal"], fatal))
        return 1
    return 0


def save(con, parsed):
    for (source, board, fid), (nodes, blocks) in parsed.items():
        sid = con.execute(
            "SELECT id FROM basic_sources WHERE source=? AND board=? AND file_id IS ?",
            (source, board, fid)).fetchone()
        if not sid:
            con.execute("INSERT INTO basic_sources(source,board,title,file_id) VALUES(?,?,?,?)",
                        (source, board, board, fid))
            con.commit()
            sid = con.execute(
                "SELECT id FROM basic_sources WHERE source=? AND board=? AND file_id IS ?",
                (source, board, fid)).fetchone()
        sid = sid["id"]
        # 人工对齐结果要留住：先记下 nkey → topic_id，重建后按 nkey 认回来
        keep = {r["nkey"]: r["topic_id"] for r in con.execute(
            "SELECT nkey,topic_id FROM basic_nodes WHERE source_id=? AND topic_id IS NOT NULL",
            (sid,))}
        con.execute("DELETE FROM basic_blocks WHERE node_id IN "
                    "(SELECT id FROM basic_nodes WHERE source_id=?)", (sid,))
        con.execute("DELETE FROM basic_nodes WHERE source_id=?", (sid,))
        # nodes 是**按板块过滤后**的子列表，而 n["parent"] 记的是解析时的全局下标
        # （三色一册两板块，过滤后下标全变）—— 所以按 _i 建索引找父节点，别用位置
        by_i = {n["_i"]: n for n in nodes}
        ids, seen = {}, {}
        for i, n in enumerate(nodes):
            parent = (by_i.get(n["parent"]) or {}).get("title", "") if n["parent"] is not None else ""
            base = (n["level"], parent, n["title"])
            seen[base] = seen.get(base, -1) + 1        # 同父同名的第几个
            # 社区线一个板块摞着十几册，nkey 必须带册号才不会串（见 nkey 的注释）
            k = nkey(board, n["level"], n["title"], seen[base], parent,
                     book=sid if source == "shequ" else None)
            cur = con.execute(
                "INSERT INTO basic_nodes(source_id,source,board,parent_id,level,title,"
                "sort,page_from,topic_id,nkey) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (sid, source, board, ids.get(n["parent"]), n["level"], n["title"],
                 n["sort"], n["page"], keep.get(k), k))
            ids[n["_i"]] = cur.lastrowid
        for j, b in enumerate(blocks):
            con.execute("INSERT INTO basic_blocks(node_id,sort,kind,content_md,page,page_to) "
                        "VALUES(?,?,?,?,?,?)", (ids[b["node"]], j, b["kind"], b["md"],
                                                b["page"], b.get("page_to") or b["page"]))
        con.commit()
        title = con.execute("SELECT title FROM basic_sources WHERE id=?", (sid,)).fetchone()[0]
        print("入库 %-6s %-8s %-34s 节点 %d 块 %d（保留人工对齐 %d）"
              % (source, board, (title or "")[:34], len(nodes), len(blocks), len(keep)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="只列出认到的资料，不动库")
    ap.add_argument("--load", action="store_true", help="抽 PDF 原文进 basic_raw")
    ap.add_argument("--reparse", action="store_true", help="从 basic_raw 重新解析")
    ap.add_argument("--dry-run", action="store_true", help="只报告解析结果，不写库")
    ap.add_argument("--source", choices=["youlu", "sanse", "shequ"], help="只处理一套资料")
    ap.add_argument("--force", action="store_true", help="原文已在库也重抽")
    ap.add_argument("--audit", action="store_true", help="覆盖率体检：入库正文 / 原文")
    ap.add_argument("--align", action="store_true", help="AI 建考点大纲并挂靠两套资料")
    ap.add_argument("--linkq", action="store_true", help="把考点接到真题题型上（学完就能练）")
    ap.add_argument("--fixtable", action="store_true", help="AI 校对 OCR 表格的错字（只改字不改结构）")
    ap.add_argument("--align-shequ", dest="align_shequ", action="store_true",
                    help="社区线考点对照：十几册资料归到一份标准考点大纲")
    ap.add_argument("--limit", type=int, default=0, help="配合 --fixtable：只处理前 N 张")
    ap.add_argument("--board", help="只处理一个板块（配合 --align）")
    a = ap.parse_args()
    con = db()
    if a.audit:
        audit(con)
        return
    if a.align:
        align(con, a.board, a.dry_run)
        return
    if a.linkq:
        linkq(con, a.board, a.dry_run)
        return
    if a.fixtable:
        fixtable(con, limit=a.limit, board=a.board, dry=a.dry_run)
        return
    if a.align_shequ:
        align_shequ(con, a.board, a.dry_run)
        return
    if a.scan or not (a.load or a.reparse):
        for source, boards, fid, name, stored in scan(con):
            path = find_file(stored)
            print("%-6s %-24s %-30s %s" % (source, "/".join(boards), name,
                                           "%d 页" % pdf_pages(path) if path else "!! 文件不在"))
        if not a.load and not a.reparse:
            return
    if a.load:
        load_raw(con, a.source, a.force)
    if a.reparse:
        parsed = parse_all(con, a.source)
        report(parsed)
        if not a.dry_run:
            save(con, parsed)
            drop_held(con)


if __name__ == "__main__":
    main()
