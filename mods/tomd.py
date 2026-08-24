"""文件 → Markdown：把上传的 PDF / Word / PPT / 扫描件转成有层级的 Markdown。

**为什么不是「再抽一次纯文本」**：云盘的阅读模式早就能取纯文字（files._extract_text），
可那份文本是平的 —— 「第一章 党的创新理论」和一句正文长得一模一样，没有目录、
搜索定位不到、字号也无从跟着分级。缺的从来不是文字，是层级。

层级从哪儿来：**原文的字号**。pdftohtml -xml 会给出每段文字的字号、字体和加粗，
先统计「哪一档字号占的字最多」当正文基准，其余按比正文大多少、是不是黑体加粗往上分级。
基准是算出来的不是写死的 —— 不同资料排版字号不一样，写死 14pt 的话，
一本 12pt 排的书会整本被判成标题。

扫描件没有字号可用（OCR 只给文字），退回中文序号规则（第 N 章 / 一、/（一）），
这套正则原本长在 basics.page_markdown 里，现在移到这里当单一来源，两边共用；
效果一定不如原生 PDF，所以成品开头会写明「标题是按序号推断的」，别让人以为层级是准的。

三个坑是拿真文件跑出来的，不处理就是一地碎行（细节见各函数注释）：
  ① 双栏排版按纵坐标排序，会把左右两栏的句子逐句穿插，整页读不成话；
  ② 页码、页眉水印字号偏大，会被判成标题；
  ③ 段落在页末被切断（「…加快构」/「建以国内大循环为主体…」），要接回去。

依赖单向：tomd → files（OCR / Office 转 PDF / 目录）→ core，无环。
外部程序全是云盘和 OCR 已经在用的：pdftohtml、pdftoppm、pdfinfo、soffice、tesseract。
"""
import html
import os
import re
import subprocess
import tempfile

from core import log
from mods.files import (IMAGE_EXT, OFFICE_EXT, TEXT_EXT, _extract_text, _ocr_image,
                        _ocr_image_page, _office_to_pdf, pdf_pages)

# ---------------------------------------------------------------- 中文标题规则
# 只认**四种资料都靠得住**的标题：部分/篇 → 章/节 → 第 N 条 → 一、 → （一）。
# `1.` 和 `（1）` **一律不当标题**，只作分段 —— 一册一个写法，照着教材排版定的
# 「短的算小标题、长的算正文」，套到党章知识点上就成了「12. 立国之本」是标题、
# 「10. 基本路线：…」是正文，同一种东西两种待遇。
#
# 这套正则原先住在 mods/basics.py（原书页转 Markdown 用）。整册转换要的是同一套口径，
# 两处各写一份的话，「1. 算不算标题」迟早在两边走样，所以定义放在这个设施模块里，
# basics.py 从这儿 import，行为一行没变（tests/test_basics.py 盯着）。
_PG_PART = re.compile(r"^\s*第\s*[一二三四五六七八九十百零〇\d]{1,4}\s*(?:部\s*分|篇|编)\s*[：:、.]?\s*\S*")
_PG_CHAP = re.compile(r"^\s*(第\s*[一二三四五六七八九十百零〇\d]{1,4}\s*[章节])\s*[”“\"'：:、.]*\s*(.*)$")
_PG_ART = re.compile(r"^\s*(第\s*[一二三四五六七八九十百零〇\d]{1,5}\s*条)\s*[”“\"'：:、.]*\s*(.*)$")
_PG_CN = re.compile(r"^\s*([一二三四五六七八九十]{1,3}\s*、)\s*(\S.*)$")
_PG_SUB = re.compile(r"^\s*[（(]\s*([一二三四五六七八九十]{1,3})\s*[)）]\s*(\S.*)$")
# 分段（不是标题）：序号条目、括号数字项、以及「考点名：要点串」那种一行一条的写法
_PG_NUM = re.compile(r"^\s*(\d{1,3})\s*[.、．]\s*(\S.*)$")
_PG_PAREN = re.compile(r"^\s*[（(]\s*(\d{1,2})\s*[)）]\s*(\S.*)$")
_PG_TERM = re.compile(r"^\s*([\u4e00-\u9fa5][\u4e00-\u9fa5A-Za-z（）()·、]{2,23})\s*[：:]\s*(\S.{5,})$")
_PG_JUNK = re.compile(r"^\s*(?:\d{1,4}|第?\s*\d{1,4}\s*页\s*共\s*\d{1,4}\s*页|[-－]\s*\d{1,4}\s*[-－])\s*$")
_PG_END = re.compile(r"[。；;！？!?：:）)】\]…]\s*$")
_PG_ANY_HEAD = re.compile(r"^\s*(?:第\s*[一二三四五六七八九十百零〇\d]{1,5}\s*(?:部\s*分|[篇编章节条])"
                          r"|[一二三四五六七八九十]{1,3}\s*、"
                          r"|[（(]\s*[一二三四五六七八九十\d]{1,3}\s*[)）]"
                          r"|\d{1,3}\s*[.、．])")

# 能转的格式。Office 先转 PDF 再走同一条路（云盘预览本来就在做这一步，结果还有缓存），
# 所以字号识别对 Word / PPT 同样有效。Excel 不在里面：表格文件转 Markdown 是另一条
# 代码路径（每张工作表一个表），和「按字号分标题」没有共用面。
SUPPORT_EXT = ({".pdf", ".html", ".htm"} | TEXT_EXT | IMAGE_EXT
               | (OFFICE_EXT - {".xls", ".xlsx", ".ods"}))
OCR_DEFAULT_LIMIT = 30      # 扫描页默认只识别前 30 页，超出要问过用户（和附件读取的口径一致）
SEC_PER_OCR_PAGE = 3        # 预估用：300dpi 一页 OCR 大约 1~3 秒，按上限估不容易让人空等


# ---------------------------------------------------------------- 版式抽取
_FONT_RE = re.compile(r'<fontspec id="(\d+)" size="([\d.]+)" family="([^"]*)"')
_PAGE_RE = re.compile(r'<page number="(\d+)"[^>]*height="(\d+)"[^>]*width="(\d+)"[^>]*>(.*?)</page>', re.S)
_TEXT_RE = re.compile(r'<text top="(-?\d+)" left="(-?\d+)" width="(-?\d+)" height="(-?\d+)" '
                      r'font="(\d+)">(.*?)</text>', re.S)


def layout_pages(pdf, first=1, last=0):
    """读出每一页的文字块，带字号 / 字体 / 加粗。

    pdftohtml 的 -xml 是这个功能的地基：pdftotext 只给字，给不了「这行有多大」。
    -i 是不导出图片（我们只要文字，导图会在临时目录里堆一堆 png）。
    """
    cmd = ["pdftohtml", "-xml", "-i", "-f", str(int(first))]
    if last:
        cmd += ["-l", str(int(last))]
    cmd += ["-stdout", pdf]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=600)
        xml = out.stdout.decode("utf-8", "ignore")
    except Exception:
        log.info("pdftohtml 取版式失败：%s", pdf, exc_info=True)
        return []
    fonts = {m.group(1): (float(m.group(2)), m.group(3)) for m in _FONT_RE.finditer(xml)}
    pages = []
    for pg in _PAGE_RE.finditer(xml):
        items = []
        for m in _TEXT_RE.finditer(pg.group(4)):
            raw = m.group(6)
            txt = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
            if not txt:
                continue
            size, fam = fonts.get(m.group(5), (12.0, ""))
            items.append({"top": int(m.group(1)), "left": int(m.group(2)),
                          "w": int(m.group(3)), "h": int(m.group(4)),
                          "size": size, "fam": fam, "bold": "<b>" in raw, "txt": txt})
        pages.append({"num": int(pg.group(1)), "w": int(pg.group(3)),
                      "h": int(pg.group(2)), "items": items})
    return pages


def _split_columns(page):
    """双栏检测：正文块在页中线两侧各成一簇、中线附近几乎没有字，就判为双栏。

    不做这一步，按纵坐标排序会把左右两栏逐句穿插 ——
    「习近平同志对…」后面接右栏的「8.明确党在新时代…」，整页读不成话。
    判据用「中线带里有多少字块」而不是「左右各有多少」：跨栏的大标题本来就压在中线上，
    只看两侧的话，有标题的页会被误判成单栏。
    """
    pw, items = page["w"], page["items"]
    if len(items) < 12:
        return [items]
    mid = pw / 2
    band = [it for it in items if abs(it["left"] + it["w"] / 2 - mid) < pw * 0.06]
    left = [it for it in items if it["left"] + it["w"] <= mid + pw * 0.02]
    right = [it for it in items if it["left"] >= mid - pw * 0.02]
    if len(left) > 6 and len(right) > 6 and len(band) < len(items) * 0.12:
        # 跨栏标题（横跨中线的块）要排在两栏前面，否则章标题会掉到左栏正文中间
        span = [it for it in items if it["left"] < mid < it["left"] + it["w"]]
        return [span, left, right]
    return [items]


def _merge_lines(items):
    """同一排的碎块拼成一行。

    pdftohtml 按视觉位置切块，一行里换个字体就断一块（「目」「录」是两块）。

    先按纵坐标把块聚成「行」，再在行内按横坐标排序拼接 —— 不能直接按 (top, left)
    排序：同一视觉行的两块 top 常差两三个像素（基线对齐、字号不同），
    排序结果就成了「右边那块在前」。页脚水印「官方网站」+「:www.youlu.com」
    正是这么被拼成「:www.youlu.com官方网站」的，顺序一乱，跨页去重也就认不出它了。

    行的字号取块里最大的：标题里夹一个小字号的括号注释，不该把整行降级成正文。
    """
    rows = []
    for it in sorted(items, key=lambda x: x["top"]):
        for r in rows:
            if abs(r["top"] - it["top"]) <= max(3, it["size"] * 0.4):
                r["cells"].append(it)
                r["top"] = min(r["top"], it["top"])
                break
        else:
            rows.append({"top": it["top"], "cells": [it]})

    lines = []
    for r in rows:
        cells = sorted(r["cells"], key=lambda x: x["left"])
        txt, prev = "", None
        for c in cells:
            if prev is not None:
                gap = c["left"] - (prev["left"] + prev["w"])
                if gap > c["size"] * 1.2:
                    txt += " "
            txt += c["txt"]
            prev = c
        lines.append({"top": r["top"], "left": cells[0]["left"],
                      "w": cells[-1]["left"] + cells[-1]["w"] - cells[0]["left"],
                      "size": max(c["size"] for c in cells),
                      "fam": max(cells, key=lambda c: c["size"])["fam"],
                      "bold": any(c["bold"] for c in cells),
                      "txt": txt.strip(), "cells": cells})
    return sorted(lines, key=lambda l: l["top"])


def _running_heads(page_lines):
    """找出页眉页脚：同样一行短文字，出现在多数页的天头或地脚。

    这份讲义每页角上都有「官方网站:www.youlu.com」，页脚还有「- 2 -」。
    靠关键词挡是挡不完的（换一份资料就换一个水印），所以按**位置 + 重复次数**认：
    在页面上下 12% 的短行，出现在三成以上的页上，一律当页眉页脚删掉。

    统计的是**合并成行之后**的文本，不是原始碎块 —— 水印在 PDF 里常被切成
    「官方网站」和「:www.youlu.com」两块，按碎块统计出来的 key 和后面过滤时
    拿到的整行对不上，结果就是「统计了个寂寞，水印照样进正文」。
    """
    if len(page_lines) < 3:
        return set()
    seen = {}
    for num, h, lines in page_lines:
        for ln in lines:
            t = ln["txt"].strip()
            if not t or len(t) > 40:
                continue
            rel = ln["top"] / (h or 1)
            if 0.12 < rel < 0.88:
                continue
            seen.setdefault(_norm_key(t), set()).add(num)
    need = max(2, int(len(page_lines) * 0.3))
    return {k for k, v in seen.items() if len(v) >= need}


def _norm_key(t):
    """页眉页脚比对用的归一化键：数字抹平（「- 2 -」和「- 3 -」是同一个页脚）。"""
    return re.sub(r"\d+", "#", t).strip()


_DOTS = re.compile(r"[.．·。]{6,}|…{3,}")


def _is_toc_page(lines):
    """目录页：多数行是「标题 ....... 页码」那种点线行。

    整页跳过，不是逐行清理 —— 目录项本身就是章节标题的字号，逐行清理会把它们
    当成真标题收进来，成品开头于是多出一份重复的、页码还对不上的假目录。
    阅读器按 Markdown 的标题层级自己就能生成目录，纸上那份不必搬过来。
    """
    if len(lines) < 5:
        return False
    dotted = sum(1 for ln in lines if _DOTS.search(ln["txt"]))
    return dotted >= max(3, len(lines) * 0.3)


def _body_size(pages):
    """正文字号 = 占字数最多的那一档。整份文档只算一次，逐页算会让某一页的标题变正文。"""
    tally = {}
    for pg in pages:
        for it in pg["items"]:
            k = round(it["size"])
            tally[k] = tally.get(k, 0) + len(it["txt"])
    return max(tally, key=tally.get) if tally else 12


def _is_heavy(fam, bold):
    return bool(bold) or bool(re.search(r"黑|Hei|Bold|Semibold|Medium|SimHei|YaHei", fam or ""))


def _level(size, fam, bold, body, text):
    """字号 → 标题级别。返回 None 表示这是正文。

    比的是**倍数**，不是差几个点：pdftohtml 给的 size 不是磅值，是按页面缩放后的
    像素（同样排 14pt 正文，A4 出来是 21，另一份可能是 16）。写成「比正文大 4 就算标题」
    的话，换一份缩放系数不同的 PDF，全书要么一个标题都认不出，要么整本都是标题。

    实测的两份资料：讲义正文 16、章标题 21（1.31 倍）、小标题 18（1.12 倍）；
    合成样例正文 21、大标题 36（1.71 倍）、章标题 30（1.43 倍）。分档就卡在这几档之间。

    同样大小的黑体/加粗算一档小标题，但要卡长度：正文里整段划重点的加粗不是标题。
    """
    if not body:
        return None
    r = size / body
    if r >= 1.6:
        return 1
    if r >= 1.25:
        return 2
    if r > 1.05:
        return 2 if _is_heavy(fam, bold) else 3
    if _is_heavy(fam, bold) and len(text) <= 30 and not _PG_END.search(text):
        return 4
    return None


# ---------------------------------------------------------------- 表格
def _table_block(lines, i):
    """从第 i 行起认一张表：连续几行都被切成同样多的列，且列的起点对得上。

    只认这种「规整框线表」。跨行合并的单元格认不出来，认不出就退回普通段落 ——
    宁可少转一张表，也不能把正文拆成一格一格的乱表。
    """
    def cols(ln):
        return [c for c in ln["cells"] if c["txt"].strip()]

    first = cols(lines[i])
    if len(first) < 2 or len(first) > 8:
        return None
    lefts = [c["left"] for c in first]
    rows = [first]
    j = i + 1
    while j < len(lines):
        cur = cols(lines[j])
        if len(cur) != len(first):
            break
        if any(abs(c["left"] - l) > 18 for c, l in zip(cur, lefts)):
            break
        rows.append(cur)
        j += 1
    if len(rows) < 3:          # 少于三行的「对齐」多半是巧合（页眉、目录点线）
        return None
    head = [c["txt"].strip().replace("|", "／") for c in rows[0]]
    md = ["| " + " | ".join(head) + " |",
          "| " + " | ".join("---" for _ in head) + " |"]
    for r in rows[1:]:
        md.append("| " + " | ".join(c["txt"].strip().replace("|", "／") for c in r) + " |")
    return "\n".join(md), j


# ---------------------------------------------------------------- 纯文本 → Markdown
def text_markdown(text):
    """没有字号可用时的退路：按中文序号规则分级（扫描件 OCR、txt、html 走这条）。

    和 basics.page_markdown 的区别只在输入规模：那边是**一页**，这边是整份文档。
    共用的是上面那套正则，不是流程。
    """
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln.strip() and not _PG_JUNK.match(ln)]
    out, para = [], []

    def flush():
        if not para:
            return
        txt = "".join(para)
        mt = _PG_TERM.match(txt)
        if mt and not txt.startswith("**"):
            txt = "**%s：**%s" % (mt.group(1), mt.group(2))
        out.append(txt)
        para.clear()

    i = 0
    while i < len(lines):
        cur = lines[i].strip()
        # 居中的大标题被按视觉行切开（「第一部分 公共管理与社会工作基」/「础知识」），接回去
        if (_PG_PART.match(cur) or _PG_CHAP.match(cur)) and not _PG_END.search(cur):
            while (i + 1 < len(lines) and len(lines[i + 1].strip()) <= 12
                   and not _PG_ANY_HEAD.match(lines[i + 1])):
                i += 1
                cur += lines[i].strip()
        if _PG_PART.match(cur):
            flush(); out.append("# " + cur)
        elif _PG_CHAP.match(cur):
            flush(); out.append("## " + cur)
        elif _PG_ART.match(cur):
            flush(); out.append("### " + cur)
        elif _PG_CN.match(cur):
            flush(); out.append("### " + cur)
        elif _PG_SUB.match(cur):
            flush(); out.append("#### " + cur)
        elif _PG_NUM.match(cur) or _PG_PAREN.match(cur) or _PG_TERM.match(cur):
            flush(); para.append(cur)
        else:
            para.append(cur)
            if _PG_END.search(cur):
                flush()
        i += 1
    flush()
    return "\n\n".join(out).strip()


# ---------------------------------------------------------------- 主流程
def _blocks_of_pdf(pdf, pages, ocr_pages, tmpdir, on_page=None):
    """PDF 逐页 → 块列表。pages 是 layout_pages 的结果，ocr_pages 是允许 OCR 的页号集合。

    两阶段：先把每页切栏、合并成行，再拿全书的行去认页眉页脚，最后才产出块。
    页眉页脚是**跨页**才认得出来的东西，一页一页边读边扔认不出来。

    版式由调用方解析好再传进来：一份 300 页的 PDF 解析一次要两秒，
    「找扫描页」和「产出块」各解析一遍就是白等一倍。
    """
    if not pages:
        return [], {}
    body = _body_size(pages)
    stats = {"body_size": body, "ocr_done": 0, "tables": 0, "heads": 0, "toc_pages": 0}

    # 阶段一：每页 → 若干栏 → 行
    page_lines, scanned = [], []
    for pg in pages:
        chars = sum(len(it["txt"]) for it in pg["items"])
        if chars < 20:
            scanned.append(pg["num"])
            page_lines.append((pg["num"], pg["h"], []))
            continue
        cols = [_merge_lines(col) for col in _split_columns(pg)]
        flat = [ln for c in cols for ln in c]
        page_lines.append((pg["num"], pg["h"], flat))
        pg["_cols"] = cols
    drop = _running_heads(page_lines)

    # 阶段二：产出
    blocks = []
    for pg in pages:
        if on_page:
            on_page(pg["num"])
        if pg["num"] in scanned:
            if pg["num"] in ocr_pages:
                txt = _ocr_image_page(pdf, pg["num"], tmpdir)
                if txt.strip():
                    stats["ocr_done"] += 1
                    for b in text_markdown(txt).split("\n\n"):
                        blocks.append({"md": b, "head": b.startswith("#")})
            continue
        cols = pg.get("_cols") or []
        if _is_toc_page([ln for c in cols for ln in c]):
            stats["toc_pages"] += 1
            continue
        for lines in cols:
            i = 0
            while i < len(lines):
                ln = lines[i]
                t = _DOTS.sub(" ", ln["txt"]).strip()
                if not t or _norm_key(t) in drop or _PG_JUNK.match(t):
                    i += 1
                    continue
                tb = _table_block(lines, i)
                if tb:
                    blocks.append({"md": tb[0], "head": False, "table": True})
                    stats["tables"] += 1
                    i = tb[1]
                    continue
                lvl = _level(ln["size"], ln["fam"], ln["bold"], body, t)
                if lvl:
                    blocks.append({"md": "#" * lvl + " " + t, "head": True})
                    stats["heads"] += 1
                else:
                    blocks.append({"md": t, "head": False})
                i += 1
    return blocks, stats


def _join_blocks(blocks):
    """把块拼成 Markdown，顺手接回被页切断的段落。

    规则：上一段不是以句末标点收尾、这一段也不是标题不是表格，就接上去。
    「…加快构」+「建以国内大循环为主体…」就是这么断的，不接回去读起来是两截。
    """
    out = []
    for b in blocks:
        if (out and not b["head"] and not b.get("table")
                and not out[-1].startswith("#") and not out[-1].startswith("|")
                and not _PG_END.search(out[-1]) and len(out[-1]) > 8):
            out[-1] += b["md"]
        else:
            out.append(b["md"])
    return "\n\n".join(x for x in out if x.strip()).strip()


def probe(path, ext):
    """预检：这份文件转起来要多久、有多少页要 OCR。给前端用来决定要不要问一句。"""
    ext = (ext or "").lower()
    info = {"pages": 0, "scan_pages": 0, "kind": "text", "est_sec": 2, "ext": ext}
    if ext in IMAGE_EXT:
        info.update(kind="image", pages=1, scan_pages=1, est_sec=SEC_PER_OCR_PAGE)
        return info
    if ext in TEXT_EXT or ext in (".html", ".htm"):
        return info
    if ext in OFFICE_EXT:
        # **故意不在这里转 PDF**：soffice 转一份大 PPT 要几十秒，预检是用户点完
        # 菜单就在等的一步，不能卡在这儿。页数和扫描页数留到任务里才知道，
        # 真遇上超限，成品开头会写明「还有 N 页没识别」，用户可以再转一次选全部转。
        info.update(kind="office", scan_pages=-1,
                    est_sec=20 + int(os.path.getsize(path) / 400000))
        return info
    src = path
    info["kind"] = "pdf"
    info["pages"] = pdf_pages(src) or 0
    pages = layout_pages(src, 1, min(info["pages"], 40) or 40)
    if pages:
        blank = sum(1 for p in pages if sum(len(it["txt"]) for it in p["items"]) < 20)
        ratio = blank / len(pages)
        # 抽样前 40 页估整本：一本 300 页的扫描书没必要为了预检先跑一遍全书
        info["scan_pages"] = int(round(ratio * info["pages"])) if info["pages"] else blank
    info["est_sec"] += max(1, info["pages"] // 20) + info["scan_pages"] * SEC_PER_OCR_PAGE
    return info


def convert(path, ext, name="", ocr_limit=OCR_DEFAULT_LIMIT, on_page=None):
    """把一个文件转成 Markdown。

    ocr_limit：允许 OCR 的扫描页数上限，0 表示不限（用户明确要求「全部转」时才是 0）。
    on_page(页号) 用来报进度 —— 扫描件一页几秒，不报进度界面就是干等。
    返回 {"md":…, "stats":{…}}；stats 里的 note 是要写给用户看的话，别丢。
    """
    ext = (ext or os.path.splitext(path)[1]).lower()
    stats = {"pages": 0, "heads": 0, "tables": 0, "ocr_done": 0, "body_size": 0,
             "scanned": False, "truncated_pages": 0, "toc_pages": 0, "note": ""}
    if ext not in SUPPORT_EXT:
        raise ValueError("这个格式还不能转成 Markdown")

    if ext in TEXT_EXT or ext in (".html", ".htm"):
        raw = _extract_text(path, ext) or ""
        if ext in (".html", ".htm"):
            raw = re.sub(r"<[^>]+>", "", raw)
            raw = html.unescape(raw)
        if ext == ".md":
            return {"md": raw.strip(), "stats": stats}     # 本来就是 Markdown，原样给回
        return {"md": text_markdown(raw), "stats": stats}

    if ext in IMAGE_EXT:
        txt = _ocr_image(path)
        stats.update(scanned=True, ocr_done=1, pages=1,
                     note="这是图片，标题是按中文序号推断的，不一定准。")
        return {"md": text_markdown(txt), "stats": stats}

    pdf = path
    if ext in OFFICE_EXT:
        pdf = _office_to_pdf(path)
        if not pdf:
            raise ValueError("这个格式转不了，下载后再看")

    total = pdf_pages(pdf) or 0
    stats["pages"] = total
    tmpdir = tempfile.mkdtemp(prefix="tomd_")
    try:
        # 先看哪些页没有文字层（扫描页），再按 ocr_limit 决定这次识别到第几页
        pages = layout_pages(pdf, 1, 0)
        scan = [p["num"] for p in pages
                if sum(len(it["txt"]) for it in p["items"]) < 20]
        allow = set(scan) if not ocr_limit else set(scan[:ocr_limit])
        stats["truncated_pages"] = len(scan) - len(allow)
        blocks, st = _blocks_of_pdf(pdf, pages, allow, tmpdir, on_page=on_page)
        stats.update({k: v for k, v in st.items() if k in stats})
        stats["scanned"] = bool(scan)
        md = _join_blocks(blocks)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    notes = []
    if stats["ocr_done"]:
        notes.append("其中 %d 页是扫描件，文字由识别得到，标题按中文序号推断，不一定准。"
                     % stats["ocr_done"])
    if stats["truncated_pages"]:
        notes.append("还有 %d 页扫描页这次没识别（可以再转一次并选「全部转」）。"
                     % stats["truncated_pages"])
    stats["note"] = "".join(notes)
    if stats["note"]:
        # 说明写进正文开头，而不是只弹个 toast：成品会被投放、下载、发给别人看，
        # 「这份只转了前 30 页」必须跟着文件走，不能只活在当时那一下提示里。
        md = "> " + stats["note"] + "\n\n" + md
    return {"md": md, "stats": stats}
