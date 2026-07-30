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
RE_TOC = re.compile(r"[.．·]{6,}\s*-?\s*\d{1,3}\s*-?\s*$")
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
def nkey(board, level, title, dup, parent=""):
    """节点身份键：对齐结果（basic_map）挂在它上面，所以它**必须扛得住重新解析**。

    ⚠️ 别把 sort（节点在书里的全局序号）编进来：解析规则一改，前面多一个或少一个
    节点，后面每一个的 sort 全体位移，nkey 跟着全变 —— 对齐结果（含人工改过的）
    在下一次 --reparse 时静默清零，正是 nkey 这套设计要防的事。

    改成「父标题 + 本标题 + 同名第几个」：同名标题在一册里确实会重复（各章都有
    「一、」），但重名只在**同一个父节点下**才需要区分，`dup` 是同父同名的出现序号，
    与书里别处增删无关。
    """
    t = re.sub(r"\s+", "", title)
    p = re.sub(r"\s+", "", parent or "")
    return "%s|%d|%s|%s|%d" % (board, level, p, t, dup)


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def scan(con):
    """认云盘里的资料 → [(source, board(s), file_id, name, stored)]。"""
    rows = con.execute(
        "SELECT id,name,stored_name FROM drive_files "
        "WHERE deleted_at IS NULL AND is_dir=0 AND folder LIKE '公考/%'").fetchall()
    found = []
    for r in rows:
        if r["name"] in YOULU_BOARD:
            found.append(("youlu", [YOULU_BOARD[r["name"]]], r["id"], r["name"], r["stored_name"]))
        elif r["name"] in SANSE_BOOK:
            found.append(("sanse", SANSE_BOOK[r["name"]], r["id"], r["name"], r["stored_name"]))
    return found


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
        sid = con.execute("SELECT id FROM basic_sources WHERE source=? AND board=?",
                          (source, boards[0])).fetchone()["id"]
        have = con.execute("SELECT COUNT(*) c FROM basic_raw WHERE source_id=?",
                           (sid,)).fetchone()["c"]
        if have >= n and not force:
            print("跳过（原文已在库）：%-30s %d 页" % (name, n))
            continue
        print("抽原文：%-30s %d 页 …" % (name, n), end="", flush=True)
        for p in range(1, n + 1):
            txt = page_text(path, p)
            xml = page_xml(path, p) if source == "sanse" else None
            con.execute("INSERT OR REPLACE INTO basic_raw(source_id,page,text,xml) "
                        "VALUES(?,?,?,?)", (sid, p, txt, xml))
        con.commit()
        print(" 完成")


def parse_all(con, only=None):
    """从 basic_raw 解析 → {(source, board): (nodes, blocks)}。"""
    out = {}
    for source, boards, _fid, name, _stored in scan(con):
        if only and source != only:
            continue
        sid = con.execute("SELECT id FROM basic_sources WHERE source=? AND board=?",
                          (source, boards[0])).fetchone()
        if not sid:
            print("!! %s 还没抽原文，先跑 --load" % name)
            continue
        rows = con.execute("SELECT page,text,xml FROM basic_raw WHERE source_id=? "
                           "ORDER BY page", (sid["id"],)).fetchall()
        if not rows:
            continue
        if source == "sanse":
            nodes, blocks = parse_sanse([(r["page"], r["xml"] or "") for r in rows], boards)
        else:
            nodes, blocks = parse_youlu([(r["page"], r["text"] or "") for r in rows], boards[0])
        for i, n in enumerate(nodes):                       # 块挂到节点上，按板块分组
            n["_i"] = i
        for b in blocks:
            b["board"] = nodes[b["node"]]["board"] if nodes else boards[0]
        for board in boards:
            bn = [n for n in nodes if n["board"] == board]
            idx = {n["_i"] for n in bn}
            out[(source, board)] = (bn, [b for b in blocks if b["node"] in idx])
    return out


def report(parsed):
    print("\n%-6s %-12s %6s %6s %6s   %s" % ("来源", "板块", "章", "考点", "块", "前 3 个考点"))
    print("-" * 88)
    for (source, board), (nodes, blocks) in sorted(parsed.items()):
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
    print("\n%-6s %-24s %8s %8s %7s  %s"
          % ("来源", "册 → 板块", "原文字", "入库字", "覆盖率", "提示"))
    print("-" * 84)
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
            n_got += len(re.sub(r"\s", "", re.sub(r"\{\{[rbg]\|", "", got).replace("}}", "")))
        pct = n_got / n_raw * 100 if n_raw else 0
        tip = "偏低，查解析" if pct < 70 else ("超 100%，可能重复入库" if pct > 115 else "")
        print("%-6s %-24s %8d %8d %6.1f%%  %s"
              % (source, "/".join(r["board"] for r in rows), n_raw, n_got, pct, tip))


def save(con, parsed):
    for (source, board), (nodes, blocks) in parsed.items():
        sid = con.execute("SELECT id FROM basic_sources WHERE source=? AND board=?",
                          (source, board)).fetchone()
        if not sid:
            con.execute("INSERT INTO basic_sources(source,board,title) VALUES(?,?,?)",
                        (source, board, board))
            con.commit()
            sid = con.execute("SELECT id FROM basic_sources WHERE source=? AND board=?",
                              (source, board)).fetchone()
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
            k = nkey(board, n["level"], n["title"], seen[base], parent)
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
        print("入库 %-6s %-12s 节点 %d 块 %d（保留人工对齐 %d）"
              % (source, board, len(nodes), len(blocks), len(keep)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="只列出认到的资料，不动库")
    ap.add_argument("--load", action="store_true", help="抽 PDF 原文进 basic_raw")
    ap.add_argument("--reparse", action="store_true", help="从 basic_raw 重新解析")
    ap.add_argument("--dry-run", action="store_true", help="只报告解析结果，不写库")
    ap.add_argument("--source", choices=["youlu", "sanse"], help="只处理一套资料")
    ap.add_argument("--force", action="store_true", help="原文已在库也重抽")
    ap.add_argument("--audit", action="store_true", help="覆盖率体检：入库正文 / 原文")
    ap.add_argument("--align", action="store_true", help="AI 建考点大纲并挂靠两套资料")
    ap.add_argument("--linkq", action="store_true", help="把考点接到真题题型上（学完就能练）")
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


if __name__ == "__main__":
    main()
