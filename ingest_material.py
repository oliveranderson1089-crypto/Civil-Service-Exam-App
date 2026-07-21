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
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import realbank as R                                       # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))
FIGDIR = os.path.join(UPLOADS, "realfig")

# 材料的起头。同一批卷子里见过四种写法，少认一种就少一批材料：
#   (材料1) （材料一）        —— 四川卷常见
#   （一）（二）（三）         —— 国考/联考常见，光秃秃一个序号占一行
#   根据以下资料回答…          —— 老卷子
#   图1  2010-2018年…／表1 … —— 有的卷子干脆没有材料头，直接以图表标题起头
_MAT_HEAD = re.compile(
    r"^[\s　]*[（(]?\s*材料\s*[一二三四五六七八九十\d]+\s*[）)]?[\s　:：]*$"
    r"|^[\s　]*[（(]\s*[一二三四五六七八九十]\s*[）)][\s　]*$"
    r"|^[\s　]*根据(?:以下|下列|下面)(?:资料|材料)"
    r"|^[\s　]*(?:以下|下列|下面)(?:资料|材料)[^\n]{0,12}$"
    r"|^[\s　]*[图表]\s*\d+[\s　]")
_MIN_MAT = 20          # 太短的不算材料（多半是个孤零零的小标题）


def find_path(stored):
    for d in sorted(os.listdir(os.path.join(UPLOADS, "drive"))):
        p = os.path.join(UPLOADS, "drive", d, stored)
        if os.path.exists(p):
            return p
    return None


def split_materials(text, figs_by_para):
    """切出 [(材料正文, 材料图的段落集合, 归它管的题号集合)]。

    归属规则：一个材料头之后、下一个材料头之前的所有题号都归它。
    材料正文 = 材料头到**第一个题号**之间的文字；那之后是题，不是材料。
    """
    lines = text.split("\n")
    heads = [i for i, ln in enumerate(lines) if _MAT_HEAD.match(ln)]
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
        "WHERE p.role='q' AND p.ext IN ('.docx','.doc') AND p.n_item>0 "
        "ORDER BY p.year DESC").fetchall()
    print("扫 %d 份 word 版题目卷" % len(papers))

    n_mat = n_q = n_fig = 0
    for p in papers:
        path = find_path(p["stored_name"])
        if not path:
            continue
        try:
            if p["ext"] == ".doc":
                path = R.doc_to_docx(path, tmp)
            text = R.docx_text(path)
            figs = R.docx_figures(path)
        except Exception:
            continue
        figs_by_para = {}
        for para, blob, ext in figs:
            figs_by_para.setdefault(para, []).append((blob, ext))
        mats = split_materials(text, figs_by_para)
        if not mats:
            continue
        seq2qid = {r["seq"]: r["qid"] for r in con.execute(
            "SELECT seq, qid FROM real_raw WHERE paper_id=? AND qid IS NOT NULL", (p["id"],))}
        hit = 0
        for body, paras, seqs in mats:
            qids = [seq2qid[s] for s in seqs if s in seq2qid]
            if not qids:
                continue
            mat_figs = [x for para in sorted(paras) for x in figs_by_para.get(para, [])]
            if a.plan:
                n_mat += 1
                n_q += len(qids)
                n_fig += len(mat_figs)
                continue
            for qid in qids:
                con.execute("UPDATE real_questions SET material=? WHERE id=? "
                            "AND (material IS NULL OR material='')", (body, qid))
                # 材料图挂到**这份材料下的每一道题**上：做题时得能直接看到表
                base = con.execute("SELECT COALESCE(MAX(ord),-1)+1 FROM real_figs WHERE qid=?",
                                   (qid,)).fetchone()[0]
                for k, (blob, ext) in enumerate(mat_figs, base):
                    if len(blob) < 400:
                        continue
                    sha = hashlib.sha256(blob).hexdigest()[:32]
                    ext = ext if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp") else ".png"
                    fp = os.path.join(FIGDIR, sha + ext)
                    if not os.path.exists(fp):
                        with open(fp, "wb") as f:
                            f.write(blob)
                    con.execute(
                        "INSERT OR IGNORE INTO real_figs(qid,ord,sha,ext,big) VALUES(?,?,?,?,1)",
                        (qid, k, sha, ext))
                    n_fig += 1
            n_mat += 1
            n_q += len(qids)
            hit += 1
        con.commit()
        if hit:
            print("  %-46s %2d 份材料" % (p["name"][:46], hit))

    print("\n%d 份材料，覆盖 %d 道题，配 %d 张表格图" % (n_mat, n_q, n_fig))
    if a.plan:
        return
    # 材料**正文和表格图都到位**才放行：只有正文没有表，数还是在图里、题照样做不了
    freed = con.execute(
        "UPDATE real_questions SET needs_asset=0 WHERE needs_asset=1 AND module='资料分析' "
        "AND material IS NOT NULL AND material<>'' "
        "AND id IN (SELECT qid FROM real_figs)").rowcount
    con.commit()
    print("解除 needs_asset：资料分析 %d 道（现在能出了）" % freed)
    left = con.execute("SELECT COUNT(*) FROM real_questions WHERE needs_asset=1 "
                       "AND module='资料分析'").fetchone()[0]
    print("资料分析仍缺材料的还有 %d 道" % left)
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
