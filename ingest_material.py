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


def split_materials(text, figs_by_para):
    """切出 [(材料正文, 材料图的段落集合, 归它管的题号集合)]。

    归属规则：一个材料头之后、下一个材料头之前的所有题号都归它。
    材料正文 = 材料头到**第一个题号**之间的文字；那之后是题，不是材料。
    """
    lines = text.split("\n")
    heads = [i for i, ln in enumerate(lines) if _MAT_HEAD.match(ln)]
    if not heads:                       # 本卷没有明确材料头，才退到「图1／表1」兜底
        heads = [i for i, ln in enumerate(lines) if _MAT_HEAD_WEAK.match(ln)]
    if not heads:
        return []
    qmark = [(i, int(m.group(1))) for i, ln in enumerate(lines)
             for m in [R._Q_HEAD.match(ln)] if m]
    out = []
    for k, start in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        qs = [(i, seq) for i, seq in qmark if start < i < end]
        if not qs:
            continue
        body_end = qs[0][0]                       # 第一个题号之前都是材料
        body = R.norm(" ".join(lines[start + 1:body_end]))
        paras = set(range(start, body_end + 1))   # 材料图就在这个段落区间里
        if len(body) < _MIN_MAT and not (paras & set(figs_by_para)):
            continue                              # 既没正文又没图，不是材料
        out.append((body[:4000], paras, {seq for _i, seq in qs}))
    return out


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
    a = ap.parse_args()

    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    if "material" not in {r[1] for r in con.execute("PRAGMA table_info(real_questions)")}:
        con.execute("ALTER TABLE real_questions ADD COLUMN material TEXT")
        con.commit()
    os.makedirs(FIGDIR, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="realmat-")

    papers = con.execute(
        "SELECT p.id, p.name, p.ext, d.stored_name FROM real_papers p "
        "JOIN drive_files d ON d.id=p.file_id "
        "WHERE p.role='q' AND p.ext IN ('.docx','.doc','.pdf') AND p.n_item>0 "
        "ORDER BY p.year DESC").fetchall()
    print("扫 %d 份题目卷（word 版抠嵌入图，PDF 版按坐标裁页）" % len(papers))

    n_mat = n_q = 0
    seen_sha = set()          # 按**内容**计数：同一张表挂给材料下的每道题，不该算成很多张
    for p in papers:
        path = find_path(p["stored_name"])
        if not path:
            continue
        seq2qid = {r["seq"]: r["qid"] for r in con.execute(
            "SELECT seq, qid FROM real_raw WHERE paper_id=? AND qid IS NOT NULL", (p["id"],))}
        try:
            if p["ext"] == ".pdf":
                # PDF 版的表是**印在页面上**的，没有嵌入图片可取，只能按坐标裁页
                seq_module = {r["seq"]: (r["module"] or "") for r in con.execute(
                    "SELECT rr.seq, q.module FROM real_raw rr "
                    "LEFT JOIN real_questions q ON q.id=rr.qid WHERE rr.paper_id=?", (p["id"],))}
                mats = pdf_materials(path, seq_module, tmp)
            else:
                if p["ext"] == ".doc":
                    path = R.doc_to_docx(path, tmp)
                text = R.docx_text(path)
                figs_by_para = {}
                for para, blob, ext in R.docx_figures(path):
                    figs_by_para.setdefault(para, []).append((blob, ext))
                mats = [(body,
                         [x for para in sorted(paras) for x in figs_by_para.get(para, [])],
                         seqs)
                        for body, paras, seqs in split_materials(text, figs_by_para)]
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
                        "INSERT OR IGNORE INTO real_figs(qid,ord,sha,ext,big) VALUES(?,?,?,?,1)",
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
    ok_cond = ("(LENGTH(COALESCE(material,'')) >= %d "
               " OR (COALESCE(material,'')<>'' AND id IN (SELECT qid FROM real_figs)))"
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
