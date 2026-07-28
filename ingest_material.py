#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资料分析的「材料」提取：一份材料 + 它底下那几道题。

资料分析和别的模块不一样：**题干本身没有信息量**（「2019 年该省 GDP 同比增长约：」），
真正的题目在前面那段材料里。所以这些题一直挂着 needs_asset、发不出去。

材料长这样：

    (材料1)
    〔一段表格图片〕
    注：化学需氧量：……
    116、2019年，平均每个综合类直排海污染物排口排放污水量约是工业类的多少倍？
    …
    120、…
    (材料2)

所以：`(材料N)` 到下一个 `(材料N+1)` 之间，**第一个题号之前**的部分就是材料正文，
这段范围内的图就是材料的表格图，题号之后的就是题。

**表格拿不到文字形式**：实测 12 份 docx 里只有 1 个真 Word 表格、却有 235 处图片 ——
表格基本都是贴图。所以材料 = 正文 + 表格图，两样都给才够做题（考场上也是看表算数）。

用法：
    python3 ingest_material.py --plan
    python3 ingest_material.py
"""
import argparse
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import realbank as R
from ingest_figs_pdf import _page_image, page_words
from ingest_figs_pdf import _QNO as _PDF_QNO                                       # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))
FIGDIR = os.path.join(UPLOADS, "realfig")

# 材料的起头。同一批卷子里见过四种写法，少认一种就少一批材料：
#   (材料1) （材料一）        —— 四川卷常见
#   （一）（二）（三）         —— 国考/联考常见，光秃秃一个序号占一行
#   根据以下资料回答…          —— 老卷子
#   图1  2010-2018年…／表1 … —— 有的卷子干脆没有材料头，直接以图表标题起头
# 前三种是**明确的材料头**，一眼能认；「图1／表1」是兜底 —— 有的卷子干脆没有材料头，
# 直接以图表标题起头。但它**不能和前三种混用**：材料正文里往往还有第二第三个图表标题
# （「图1 …」「图2 …」连着两行），当成材料头就会把一份材料从中间劈成两半，
# 前半段分不到题号被丢弃、图也跟着丢，用户拿到残缺的材料。
# 所以分两级：本卷能认出明确材料头就只用它们，认不出才退到图表标题。
# 材料头后面的编号**可以没有**：2023 国考三卷和 2012 四川都直接写「(材料)」
# 独占一行（13 份卷子）。所以编号那段用 * 而不是 +。
# 「根据以下资料」前面**常带一个序号**：「（一）根据以下资料，完成各题。」（2010 国考）、
# 「一、根据以下材料，回答 111—115 题。」（2024 国考）。原先要求「根据」顶在行首，
# 这两类整份卷子一个材料头都认不出来（实测 89 份缺材料的卷子里有 23 份栽在这）。
# 中间那个「以下/下列/下面/所给」**必须要**：写成可选的话，正文里的
# 「根据材料可知…」也会被当成材料头，把一份材料从中间劈开。
_MAT_HEAD = re.compile(
    r"^[\s　]*[（(]?\s*材料\s*[一二三四五六七八九十\d]*\s*[）)]?[\s　:：]*$"
    r"|^[\s　]*[（(]\s*[一二三四五六七八九十]\s*[）)][\s　]*$"
    r"|^[\s　]*(?:[（(]?\s*[一二三四五六七八九十\d]+\s*[）)、.．]\s*)?"
    r"根据(?:以下|下列|下面|所给)(?:资料|材料|图表|统计)"
    r"|^[\s　]*(?:以下|下列|下面)(?:资料|材料)[^\n]{0,12}$"
    # 老卷子（2001~2006 国考）写的是「一、根据下表回答116～120题。」——
    # 说的是「下表」「下图」而不是「资料/材料」，前面那几条一条都不认。
    # **必须带「回答」**：只写「根据下表…」的话，解析正文里的
    # 「根据下表可知，甲比乙多出 20%，因此选 A」也会被当成材料头，把材料劈成两半。
    r"|^[\s　]*(?:[（(]?\s*[一二三四五六七八九十\d]+\s*[）)、.．]\s*)?"
    r"根据(?:下|上|本|该)(?:表|图|图表)[^\n]{0,12}?回答[^\n]{0,20}$")
_MAT_HEAD_WEAK = re.compile(r"^[\s　]*[图表]\s*\d+[\s　]")
# 材料头**自己写明了管哪几道题**：「根据下表回答116～120题」「回答第111—115题」。
# 有它就以它为准，别再去猜边界 —— 老卷子（2001~2008 国考）的材料是一张大表格，
# 表格里每一行都以数字打头（「5.4」「0.9」），_Q_HEAD 会把它们当成题号，
# 于是材料正文在第一行数据处就被截断、归属也落到一堆根本不存在的题号上。
_HEAD_RANGE = re.compile(r"(?:回答|完成)[\s　]*第?[\s　]*(\d{1,3})[\s　]*"
                         r"[-–—~～、,，至到][\s　]*第?[\s　]*(\d{1,3})[\s　]*题")
_MIN_MAT = 20          # 太短的不算材料（多半是个孤零零的小标题）
# 材料正文到这个长度就认为「自成一体」，没有表格图也能做题（文字型资料分析）。
# 300 字是看着分布定的：<300 字的基本是图表型材料的那句「注：…」，数还在图里。
_SELF_CONTAINED = 300


def find_path(stored):
    for d in sorted(os.listdir(os.path.join(UPLOADS, "drive"))):
        p = os.path.join(UPLOADS, "drive", d, stored)
        if os.path.exists(p):
            return p
    return None


# 排版噪声：材料正文里不该混进这些
_NOISE = re.compile(r"^[\s　]*(?:第[一二三四五六七八九十]部分|资料分析|请开始答题|"
                    r"所给出的[图表]|[（(]共\s*\d+\s*题)")
_OPT_LINE = re.compile(r"^[\s　]*[ABCD][\s　]*[、.．)）]?[\s　]*\S")


def gap_materials(lines, figs_by_para, qmark, zl_seqs):
    """**没有任何文字材料头**时的兜底：靠「题与题之间的空隙」找材料。

    2004 国考那种卷子，资料分析部分连一句「根据以下资料」都没有，材料就是一张
    统计表图片，最多配一行表标题；2022 国考更干脆，图前面什么字都没有。
    但排版顺序是死的：[上一题题号][题干][选项][材料][下一题题号]。
    所以从下一道题的题号行往回走，一路收到撞上上一题的最后一个选项行为止，
    收到的就是材料 —— 图和文字一起收，两者有其一就算一份材料。

    **不能只认图**：实测同一份卷子里，有的材料是图、有的是纯文字段落
    （2004 A 卷第 97~101 题那份是 602 字的文字材料，一张图都没有）。
    只按图分组的话，那 5 道题会被并进上一份材料，整组配错表。
    """
    qs = [(i, s) for i, s in qmark if s in zl_seqs]
    if len(qs) < 4:
        return []
    out, cur = [], None
    for k, (i, seq) in enumerate(qs):
        # 下界要**取到**：首题前面没有「上一题」，往回最多看 40 行，
        # 而循环是 j > lo，所以 lo 要再减 1，否则第 0 行那张图永远扫不到。
        lo = qs[k - 1][0] if k else max(0, i - 40) - 1
        txt, paras = [], []
        j = i - 1
        while j > lo and not _OPT_LINE.match(lines[j]):
            if lines[j].strip() and not _NOISE.match(lines[j]):
                txt.insert(0, lines[j].strip())
            if j in figs_by_para:
                paras.insert(0, j)
            j -= 1
        body = R.norm(" ".join(txt))
        if len(body) >= _MIN_MAT or paras:          # 这儿开始一份新材料
            cur = [body[:4000], [x for pa in paras for x in figs_by_para[pa]], set()]
            out.append(cur)
        if cur is not None:
            cur[2].add(seq)
    return [(b, f, sq) for b, f, sq in out if sq]


def pdf_materials(pdf, seq_module, tmp):
    """PDF 版的材料：正文按坐标抠文字，表格**按坐标裁成图**。

    word 版的表是嵌进去的独立图片，docx_figures 能直接取；PDF 版的表是印在页面上的，
    只能连同它所在的那块页面一起裁下来。区间 = 材料头那行的顶 → 本材料第一道题那行的顶。

    seq_module 是这份卷子 {题号: 模块}。定边界光靠正则不行 —— 材料正文里全是数字，
    「投诉 55. 6 万件」和「55.」题头长得一模一样，表格单元格里的「2」「27」也是。
    所以要三重约束：题号得**真实存在**、得是**连续的一段**（资料分析的材料总是管
    连着的 4~6 道题）、而且这批题得**确实属于资料分析**。
    """
    pages = page_words(pdf)
    if not pages:
        return []
    flat = []              # (页码, 页高, y, 文字)：页内排成阅读顺序
    for pno, h, words in pages:
        for y, t in _reading_order(words):
            flat.append((pno, h, y, t))
    heads = [i for i, f in enumerate(flat) if _MAT_HEAD.match(f[3])]
    if not heads:
        return []
    out = []
    for k, hi in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(flat)
        cand = [(i, int(m.group(1))) for i in range(hi + 1, end)
                for m in [_PDF_QNO.match(flat[i][3])] if m and int(m.group(1)) in seq_module]
        qs = _consecutive_run(cand)
        if len(qs) < 3:
            continue                     # 连不成一段 = 匹配到的是表格里的数字，不是题号
        mods = [seq_module[seq] for _i, seq in qs]
        if sum(1 for m in mods if m == "资料分析") < len(mods) * 0.6:
            continue                     # 这份材料主要不归资料分析管，交给别的脚本
        body = R.norm(" ".join(flat[i][3] for i in range(hi + 1, qs[0][0])))
        imgs = [x for x in _crop_region(pdf, flat, hi, qs[0][0], tmp) if len(x[0]) > 2000]
        if not imgs and len(body) < _MIN_MAT:
            continue
        out.append((body[:4000], imgs, {seq for _i, seq in qs}))
    return out


def _consecutive_run(cand):
    """从候选题号里取出**连续递增**的那一段（资料分析的材料总是管连着的几道题）。

    表格单元格、页码都会被题号正则匹配上，但它们连不成 111、112、113 这样的序列。
    """
    run = []
    for i, seq in cand:
        if not run:
            run = [(i, seq)]
        elif seq == run[-1][1] + 1:
            run.append((i, seq))
        elif len(run) < 3:
            run = [(i, seq)]             # 前面那截太短，多半是噪声，从这儿重来
        else:
            break
    return run


def _reading_order(words):
    """把一页的词排成人读的顺序：先分行，行内再按 x 从左到右。

    **不能按 yMin 直接排**，也不能简单量化：同一行里数字和汉字用的字体不同，
    yMin 会差一两磅，量化到固定档位时会掉进相邻档，于是
    「2022年，京津冀地区生产总值合计10.0万亿元」被排成
    「2022 10.0 年，京津冀地区生产总值合计 万亿元」，读都读不通。
    改成按**纵向重叠**聚行：字高的一半以内算同一行，这个尺度随字号自适应。
    """
    lines = []                       # [(基准 y, 该行字高, [(x, 文字)])]
    for y, x, fh, t in sorted(words, key=lambda w: w[0]):
        tol = max(fh, 1.0) * 0.5
        if lines and abs(y - lines[-1][0]) <= tol:
            lines[-1][2].append((x, t))
        else:
            lines.append((y, fh, [(x, t)]))
    return [(y, " ".join(t for _x, t in sorted(items)))
            for y, _fh, items in lines]


def _crop_region(pdf, flat, i0, i1, tmp, max_imgs=3):
    """把 flat[i0]（材料头）到 flat[i1]（第一道题）之间那块页面裁出来。

    跨页的材料要裁成好几张：头所在页裁到页底，中间整页，末页从页顶裁到题号。
    """
    p0, h0, y0, _ = flat[i0]
    p1, _h1, y1, _ = flat[i1]
    spans = []
    if p0 == p1:
        spans.append((p0, y0, y1))
    else:
        spans.append((p0, y0, h0))
        for pno in range(p0 + 1, min(p1, p0 + max_imgs)):
            spans.append((pno, 0, None))
        spans.append((p1, 0, y1))
    out = []
    for pno, a, b in spans[:max_imgs]:
        im = _page_image(pdf, pno, tmp)
        if im is None:
            continue
        try:
            ph = next(h for p, h, _y, _t in flat if p == pno)
            sc = im.height / ph
            top = max(0, int(a * sc) - 4)
            bot = im.height if b is None else min(im.height, int(b * sc) + 4)
            if bot - top < 60:          # 太薄 = 材料头和题号挨着，中间没有表
                continue
            piece = im.crop((0, top, im.width, bot))
            fp = os.path.join(tmp, "mat_%d_%d.png" % (pno, top))
            piece.save(fp, optimize=True)
            with open(fp, "rb") as f:
                out.append((f.read(), ".png"))
        except Exception:
            continue
    return out


def _line_modules(lines):
    """每一行落在哪个模块里 + 分节标题所在的行号。一趟扫完，两样都要 ——
       secs 给「材料别越过分节」用，line_mod 给「材料只管本模块」用，
       别各扫一遍 _MOD_HEAD。认不出分节的卷子 line_mod 全是空串。

    材料头**长在哪个模块里，就只能管那个模块的题**。老卷子（2008/2009 国考）的
    资料分析材料是一张大表，表格行「2.5」「3.2」会被 _Q_HEAD 认成题号 2、3 ——
    这些题号在卷子上真实存在（是言语理解的第 2、3 题），光靠「题号得存在」拦不住，
    得靠「这份材料长在资料分析节里，管不到言语理解」。
    """
    out, secs, cur = [], [], ""
    for i, ln in enumerate(lines):
        m = R._MOD_HEAD.match(ln)
        if m:
            name = next((g for g in m.groups() if g), "") or cur
            cur = "言语理解与表达" if name == "言语理解" else name
            secs.append(i)
        out.append(cur)
    return out, secs


def _is_head(ln, head_re):
    """这行是不是材料头：形态对得上，且不是**披着材料头外衣的题干**。

    「52、根据所给材料，以下哪一项…」这种题干会误配 _MAT_HEAD（「根据所给材料」那条），
    当成材料头就把它自己的四个选项收成了材料正文。靠「它没写题号范围」把它认出来 ——
    真材料头要么不以阿拉伯题号打头（「一、根据…」用汉字），要么写了范围
    （「116、根据下表回答117~120题」）。只用「不以题号打头」一刀切，会连带把
    以阿拉伯数字编号、又确实写了范围的材料头也误杀。
    """
    return bool(head_re.match(ln)) and (
        not R._Q_HEAD.match(ln) or bool(_HEAD_RANGE.search(ln)))


def _leading_run(qs):
    """从第一道题起、题号一路往上涨的那一段；断档就停。

    一份材料管的永远是**卷面上连着的几道题**（116~120）。题号一旦倒退或跳一大截，
    说明已经越过这份材料的地界，后面那些是别的题。留 2 的余量是给
    「中间那道题的题号行没被认出来」留的，跳得更远就不再是同一组了。
    """
    out = [qs[0]]
    for i, seq in qs[1:]:
        if seq <= out[-1][1] or seq - out[-1][1] > 2:
            break
        out.append((i, seq))
    return out


def split_materials(text, figs_by_para, valid_seqs=None, seq_module=None):
    """切出 [(材料正文, 材料图的段落集合, 归它管的题号集合)]。

    材料正文 = 材料头到**第一个题号**之间的文字；那之后是题，不是材料。
    难的是「归它管的题号」到哪儿为止 —— 四道闸依次卡：

      ① 材料头自己写了范围（「根据下表回答116～120题」）就以它为准，别猜；
      ② 只认**这份卷子上真实存在的题号**。老卷子的材料是一张大表格，每行数据
         都以数字打头（「5.4」→ 题号 5），不卡这一条，材料正文会在第一行数据处
         被截断，归属还会落到一堆不存在的题上；
      ③ 不许越过**模块分节标题**。原先一份材料一直管到下一个材料头为止 ——
         对背靠背排列的资料分析没问题，可言语理解的文章阅读后面跟着的是
         数量关系、判断推理的独立题，于是 2023 国考副省级那篇「降雨来源于云层」
         被挂到了 56~115 共 60 道题上（连同材料里那三张 -40℃/-15℃/-2℃ 的小图），
         做定义判断时先读一篇讲云层细菌的文章；
      ④ 题号得是**连续的一段**、且**同属一个模块**。一份给定资料横跨两个模块，
         在行测卷面上不存在。

    valid_seqs / seq_module 由调用方从 real_raw 查好传进来（哪些题号真的存在、
    各属哪个模块）。传空就退化成「只有 ①③ 两道闸」，不会报错。
    """
    lines = text.split("\n")
    # 题号行**基本不是材料头**（详见 _is_head）：「52、根据所给材料，以下哪一项…」
    # 会误配 _MAT_HEAD，当成材料头就把它自己的四个选项收成材料正文（实测 2019 国考
    # 省级中招 4 处，存出来是「A、实时成像 B、检测大脑氧气含量 …」）。
    heads = [i for i, ln in enumerate(lines) if _is_head(ln, _MAT_HEAD)]
    if not heads:                       # 本卷没有明确材料头，才退到「图1／表1」兜底
        heads = [i for i, ln in enumerate(lines) if _is_head(ln, _MAT_HEAD_WEAK)]
    if not heads:
        return []
    # 模块分节标题（「第二部分　数量关系」「一、判断推理」「资料分析」独占一行）+
    # 每行落在哪个模块。复用 realbank 那份 _MOD_HEAD —— real_raw.module 就是它切
    # 出来的，另写一个的话两边对「这儿是不是换模块了」的判断会不一致。
    line_mod, secs = _line_modules(lines)
    qmark = [(i, int(m.group(1))) for i, ln in enumerate(lines)
             for m in [R._Q_HEAD.match(ln)] if m
             if valid_seqs is None or int(m.group(1)) in valid_seqs]
    out = []
    for k, start in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        nxt_sec = next((i for i in secs if i > start), None)
        if nxt_sec is not None:
            end = min(end, nxt_sec)
        qs = [(i, seq) for i, seq in qmark if start < i < end]
        rng = _HEAD_RANGE.search(lines[start])
        if rng:
            lo, hi = sorted((int(rng.group(1)), int(rng.group(2))))
            # 写明了范围就只认范围内的题；**不受 end 约束** —— 老卷子的材料头
            # 和它管的那几道题之间隔着整张表格，中间还可能夹着别的材料头。
            qs = [(i, seq) for i, seq in qmark if i > start and lo <= seq <= hi]
        if not qs:
            continue
        # 材料只管**它自己所在模块**的题；认不出分节的卷子退而求其次，
        # 用「第一道题是哪个模块，就都得是哪个模块」把一份材料锁在一个模块里。
        if seq_module:
            m0 = line_mod[start] or seq_module.get(qs[0][1], "")
            qs = [(i, seq) for i, seq in qs if seq_module.get(seq, "") == m0]
            if not qs:
                continue
        # 材料头**没写范围**时才用连续性兜边界（防表格行漏进来）。写了范围的，
        # [lo,hi] 就是权威 —— 再套 _leading_run，一旦范围内有两道题没解析出来
        # （老扫描卷常见），题号断档 >2 会把声明过的尾巴（如 115~120）整段丢掉。
        if not rng:
            qs = _leading_run(qs)
        body_end = qs[0][0]                       # 第一个题号之前都是材料
        body = R.norm(" ".join(lines[start + 1:body_end]))
        paras = set(range(start, body_end + 1))   # 材料图就在这个段落区间里
        if len(body) < _MIN_MAT and not (paras & set(figs_by_para)):
            continue                              # 既没正文又没图，不是材料
        out.append((body[:4000], paras, {seq for _i, seq in qs}))
    return out


def word_read(path, ext, tmp):
    """word 版卷子读一次：正文行 + 每段挂了哪些图。"""
    if ext == ".doc":
        path = R.doc_to_docx(path, tmp)
    text = R.docx_text(path)
    figs_by_para = {}
    for para, blob, ext2 in R.docx_figures(path):
        figs_by_para.setdefault(para, []).append((blob, ext2))
    return text, text.split("\n"), figs_by_para


def word_materials(text, lines, figs_by_para, seq2qid, seq_module, zl_seqs):
    """word 版这份卷子的 [(材料正文, 材料图, 归它管的题号)]。

    两条路：有材料头的走 split_materials，剩下**没分到材料的资料分析题**再走
    gap_materials 兜一次。抽成函数是因为 --reset 要用同一套口径算出「修好之后
    这张表该长什么样」，两边各写一份的话，清理和重建会按不同规则跑。
    """
    mats = [(body,
             [x for para in sorted(paras) for x in figs_by_para.get(para, [])],
             seqs)
            for body, paras, seqs in split_materials(
                text, figs_by_para, set(seq2qid), seq_module)]
    # 材料头认不出来的资料分析题，退到「靠题与题之间的空隙找材料」。
    # **按题补，不是整卷二选一**：原先只有「一个材料头都没有」才走兜底，
    # 可现代卷子（2020/2022 国考）常常是判断推理里有个「（一）」被当成材料头、
    # 而资料分析那四份材料一个头都没写 —— 有头的那份把兜底整个挡掉，
    # 那 20 道资料分析题于是分到了判断推理那份材料。
    todo = zl_seqs - {s for _b, _f, sq in mats for s in sq}
    if todo:
        qmark = [(i, int(m.group(1))) for i, ln in enumerate(lines)
                 for m in [R._Q_HEAD.match(ln)] if m]
        mats += gap_materials(lines, figs_by_para, qmark, todo)
    return mats


def reset_figs(con, papers, tmp):
    """把 word 版留下的**过期材料图**删掉，为 main() 重建腾地方。返回删了多少行。

    为什么不能只 `DELETE WHERE kind='mat'`：kind 这列是后加的，更早那几轮
    ingest_material 插的行 kind 是空的，和 ingest_figs 按段落邻近挂的图混在一起
    分不出来 —— 而串题最狠的正是那批（2023 国考副省级那三张 -40℃/-15℃/-2℃
    的小图，跟着「降雨来源于云层」那篇材料挂到了 58 道题上）。

    所以按**内容**判、只保一样东西：**ingest_figs 按题邻近挂的图**（图形推理等，
    本脚本不重建它们，删了就没人补）。材料图一律删掉、交给 main() 随后按修好的
    归属重新挂 —— 「谁先写谁赢、正文对不上就不挂图」这套归属只有 main() 一处说了算，
    reset 不再自己算一份材料归属（算重了就会把败者卷的表格图留成串图）。
    删除面 = 来自某份 word 卷、又不是 ingest_figs 那份的图；PDF 整页裁的图 sha
    不在 word 图里，不会被误伤。
    """
    from ingest_figs import paper_figs                      # 只有 --reset 用得上
    good, word_shas = set(), set()
    for p in papers:
        if p["ext"] not in (".docx", ".doc"):
            continue
        path = find_path(p["stored_name"])
        if not path:
            continue
        seq2qid = {r["seq"]: r["qid"] for r in con.execute(
            "SELECT seq, qid FROM real_raw WHERE paper_id=? AND qid IS NOT NULL", (p["id"],))}
        # paper_figs 自己把 .doc 转好 docx 再抠图 —— 别再单独 word_read 一趟，
        # 那样 27 份 .doc 每份要多跑一次 libreoffice。它返回的 {seq: [(sha,...)]}
        # 覆盖了这份卷子所有 ≥400 的嵌入图，既是「谁不能删」的白名单（按题邻近那份），
        # 又凑齐了「哪些 sha 是 word 来的」这张删除底片（<400 的图库里本就没有）。
        try:
            got, _dropped = paper_figs(path, tmp)
        except Exception:
            continue
        for seq, items in got.items():
            qid = seq2qid.get(seq)
            for sha, _e, _b in items:
                word_shas.add(sha)
                if qid:
                    good.add((qid, sha))
    drop = [(r["qid"], r["sha"]) for r in con.execute("SELECT qid, sha FROM real_figs")
            if (r["qid"], r["sha"]) not in good and r["sha"] in word_shas]
    con.executemany("DELETE FROM real_figs WHERE qid=? AND sha=?", drop)
    return len(drop)


def _to_png(blob, tmp):
    """emf/wmf 转 png（走 libreoffice）。转不了返回 None —— 宁可没有图，也别给裂图。"""
    src = os.path.join(tmp, "matconv.emf")
    with open(src, "wb") as f:
        f.write(blob)
    try:
        subprocess.run(["libreoffice", "--headless", "--convert-to", "png", "--outdir", tmp, src],
                       capture_output=True, timeout=60)
        out = os.path.join(tmp, "matconv.png")
        if os.path.exists(out):
            with open(out, "rb") as f:
                return f.read(), ".png"
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--reset", action="store_true",
                    help="先清空已挂的材料正文与过期配图再重建（改了归属规则之后要跑这个："
                         "平时是「只填空着的」，不清的话旧规则串错的材料一条都不会被覆盖）")
    a = ap.parse_args()

    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    if "material" not in {r[1] for r in con.execute("PRAGMA table_info(real_questions)")}:
        con.execute("ALTER TABLE real_questions ADD COLUMN material TEXT")
        con.commit()
    if "kind" not in {r[1] for r in con.execute("PRAGMA table_info(real_figs)")}:
        con.execute("ALTER TABLE real_figs ADD COLUMN kind TEXT DEFAULT ''")
        con.commit()
    os.makedirs(FIGDIR, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="realmat-")

    papers = con.execute(
        "SELECT p.id, p.name, p.ext, d.stored_name FROM real_papers p "
        "JOIN drive_files d ON d.id=p.file_id "
        "WHERE p.role='q' AND p.ext IN ('.docx','.doc','.pdf') AND p.n_item>0 "
        "ORDER BY p.year DESC").fetchall()
    print("扫 %d 份题目卷（word 版抠嵌入图，PDF 版按坐标裁页）" % len(papers))

    if a.reset and not a.plan:
        gone = reset_figs(con, papers, tmp)
        cleared = con.execute("UPDATE real_questions SET material='' "
                              "WHERE COALESCE(material,'')<>''").rowcount
        con.commit()
        print("--reset：清空 %d 道题的材料正文，删掉 %d 张过期配图" % (cleared, gone))

    n_mat = n_q = 0
    seen_sha = set()          # 按**内容**计数：同一张表挂给材料下的每道题，不该算成很多张
    for p in papers:
        path = find_path(p["stored_name"])
        if not path:
            continue
        seq2qid = {r["seq"]: r["qid"] for r in con.execute(
            "SELECT seq, qid FROM real_raw WHERE paper_id=? AND qid IS NOT NULL", (p["id"],))}
        # 这份卷子上每个题号属于哪个模块。word 版和 PDF 版都要用：
        # 前者拿它卡「材料不跨模块」，后者拿它认「这份材料归不归资料分析管」。
        seq_module = {r["seq"]: (r["module"] or "") for r in con.execute(
            "SELECT rr.seq, q.module FROM real_raw rr "
            "LEFT JOIN real_questions q ON q.id=rr.qid WHERE rr.paper_id=?", (p["id"],))}
        try:
            if p["ext"] == ".pdf":
                # PDF 版的表是**印在页面上**的，没有嵌入图片可取，只能按坐标裁页
                mats = pdf_materials(path, seq_module, tmp)
            else:
                text, lines, figs_by_para = word_read(path, p["ext"], tmp)
                zl = {s for s, m in seq_module.items()
                      if m == "资料分析" and s in seq2qid}
                mats = word_materials(text, lines, figs_by_para,
                                      seq2qid, seq_module, zl)
        except Exception:
            continue
        if not mats:
            continue
        hit = 0
        for body, mat_figs, seqs in mats:
            qids = [seq2qid[s] for s in seqs if s in seq2qid]
            if not qids:
                continue
            if a.plan:
                n_mat += 1
                n_q += len(qids)
                seen_sha.update(hashlib.sha256(b).hexdigest()[:32] for b, _e in mat_figs)
                continue
            for qid in qids:
                con.execute("UPDATE real_questions SET material=? WHERE id=? "
                            "AND (material IS NULL OR material='')", (body, qid))
                # **正文和图必须来自同一份卷子**。同一道题常常在两份卷子里都出现
                # （2023 国考副省级第 132 题 = 行政执法卷第 127 题，去重后是一道题），
                # 而正文只认先到的那份（上面那句 WHERE material IS NULL），
                # 图却每份卷子都往上追加 —— 于是正文是 A 卷的、图混着 A+B 两卷的，
                # 用户看到一张风马牛不相及的表（实测：题问纺织品出口，配了张宽带用户数的表）。
                if (con.execute("SELECT material FROM real_questions WHERE id=?",
                                (qid,)).fetchone()[0] or "") != body:
                    continue
                # 材料图挂到**这份材料下的每一道题**上：做题时得能直接看到表
                base = con.execute("SELECT COALESCE(MAX(ord),-1)+1 FROM real_figs WHERE qid=?",
                                   (qid,)).fetchone()[0]
                for k, (blob, ext) in enumerate(mat_figs, base):
                    if len(blob) < 400:
                        continue
                    if ext in (".emf", ".wmf"):
                        # **不能只改扩展名**：浏览器解不了图元格式，改名成 .png 只会
                        # 让它以 image/png 发出去、显示成裂图。要么真转，要么整张丢掉。
                        got = _to_png(blob, tmp)
                        if not got:
                            continue
                        blob, ext = got
                    elif ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
                        continue
                    sha = hashlib.sha256(blob).hexdigest()[:32]
                    fp = os.path.join(FIGDIR, sha + ext)
                    if not os.path.exists(fp):
                        with open(fp, "wb") as f:
                            f.write(blob)
                    con.execute(
                        # kind='mat' 是材料图的标记。**必须和题目图区分开**：
                        # ingest_figs 会按段落邻近给资料分析题也挂上图（实测 178 道），
                        # 那些图没经过材料归属验证，不能拿来当「材料齐了」的凭据。
                        "INSERT OR IGNORE INTO real_figs(qid,ord,sha,ext,big,kind) "
                        "VALUES(?,?,?,?,1,'mat')",
                        (qid, k, sha, ext))
                    seen_sha.add(sha)
            n_mat += 1
            n_q += len(qids)
            hit += 1
        con.commit()
        if hit:
            print("  %-46s %2d 份材料" % (p["name"][:46], hit))

    print("\n%d 份材料，覆盖 %d 道题，配 %d 张表格图（按内容去重计）"
          % (n_mat, n_q, len(seen_sha)))
    if a.plan:
        return
    # 这个闸**双向生效**：该放的放、该锁的锁回去。
    # 只会解封的话，早先在别的规则下误放的题会一直留着 —— dedup 现在把上一轮的判定
    # 原样搬运（正是为了别抹掉资产脚本的产出），于是那个错误判定也就永久固化了
    # （实测有 118 道资料分析解封了却根本没有材料）。
    # 「资产够不够」这套标准归本脚本管，那它就得对这个模块的标志位负全责。
    # 资料分析有两种材料，闸要都认，否则会把一大批好题误锁：
    #   图表型 —— 数在表里，正文往往只有一句「注：…」，所以必须有图；
    #   文字型 —— 一整段带数字的叙述，自成一体，没有图也能做（实测 82 道是这种，
    #             随手抽一条：「2020年1—2月…累计实现投资1078.6亿元，同比增长1.8%…」）。
    # 所以：**有图，或者材料正文够长**。只认前者会把文字型材料全判成资产不全。
    # ⚠️ 一律用 COALESCE，别写 `material IS NOT NULL AND …`：
    #    material 为 NULL 时 `NOT (NULL AND x)` 在 SQL 三值逻辑里求值成 **NULL 而不是 TRUE**，
    #    锁回那条 UPDATE 就匹配不到这些行 —— 实测漏了 88 道「解封了却没有材料」的题。
    # 图表型材料常常一个字都没有（2022 国考副省级那几份，图前面连表标题都没有），
    # 所以「有材料图」这一条不能再附加「正文非空」——只要图是**材料图**（kind='mat'，
    # 经过材料归属的那条路挂上去的）就算数。
    ok_cond = ("(LENGTH(COALESCE(material,'')) >= %d "
               " OR id IN (SELECT qid FROM real_figs WHERE kind='mat'))"
               % _SELF_CONTAINED)
    freed = con.execute("UPDATE real_questions SET needs_asset=0 "
                        "WHERE needs_asset=1 AND module='资料分析' AND " + ok_cond).rowcount
    relocked = con.execute("UPDATE real_questions SET needs_asset=1 "
                           "WHERE needs_asset=0 AND module='资料分析' AND NOT (%s)"
                           % ok_cond).rowcount
    con.commit()
    print("解除 needs_asset：资料分析 %d 道；锁回（资产不全）：%d 道" % (freed, relocked))
    left = con.execute("SELECT COUNT(*) FROM real_questions WHERE needs_asset=1 "
                       "AND module='资料分析'").fetchone()[0]
    print("资料分析仍缺材料的还有 %d 道" % left)
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
