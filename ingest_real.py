#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真题入库：把云盘「公考/」下的历年行测卷解析进库，**先全量提取、再统一去重**。

分两步走是刻意的（也是需求方点名要的）：同一道题在这批素材里会重复好几次，
而且是三种不同的重复，边解析边判重会漏掉后两种 ——

  ① 同一份卷子既有 word 版又有 PDF 版（四川那批 07-23 就是两套并存）
  ② 同一年既有「无答案的试题卷」又有「带答案解析卷」，题目部分是同一批题
  ③ 同一年不同卷种（国考副省级/地市级/行政执法）之间**大面积共题**，
     省考和联考之间也串题

所以：real_raw 存**原样提取**的每一条（哪份卷子第几题，一条不落），
real_questions 存**去重合并后**的题库，一道题只留一条，
但把它在哪些卷子里出现过全记在 sources 里 —— 「这题 2023 副省和地市都考了」
是有用的信息，不能在去重时丢掉。

用法：
    python3 ingest_real.py --scan            # 只看要处理哪些文件，不动库
    python3 ingest_real.py --ext docx,doc    # 先跑 word 版（准、快）
    python3 ingest_real.py                   # 全量（含 PDF）
    python3 ingest_real.py --dedup-only      # 素材没变，只重跑去重
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import sqlite3
import statistics
import sys
import tempfile
import time
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import realbank as R                                       # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS real_papers(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER UNIQUE,          -- drive_files.id，重跑时靠它认出「这份处理过了」
    name TEXT, folder TEXT, ext TEXT,
    exam TEXT, year INTEGER, season TEXT, paper TEXT, kind TEXT,
    pkey TEXT,                       -- 卷子身份（规范化文件名+卷别令牌），同一场考试的多个副本一致
    role TEXT,                       -- q=题目卷 / a=答案卷
    n_item INTEGER DEFAULT 0,        -- 解析出多少条
    answers_ok INTEGER DEFAULT 1,    -- 0 = 答案被判定错位，dedup 时屏蔽（底稿仍保留）
    status TEXT, note TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS real_raw(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER, seq INTEGER,
    module TEXT, stem TEXT, options TEXT, answer TEXT, explain TEXT,
    qhash TEXT, ohash TEXT,
    fighash TEXT DEFAULT '',         -- 这道题配的图的指纹（图形推理靠它才分得开）
    qid INTEGER,                     -- 去重后归到哪条 real_questions
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_raw_paper ON real_raw(paper_id);
CREATE INDEX IF NOT EXISTS idx_raw_hash ON real_raw(qhash);
CREATE INDEX IF NOT EXISTS idx_raw_ohash ON real_raw(ohash);
"""

# real_questions 是**纯推导表**：内容全部来自 real_raw，去重规则一改就得整张重算。
# 所以不做增量迁移，每次 dedup 直接重建 —— 改判重逻辑时不用操心历史残留。
# 注意 qhash 上**没有 UNIQUE**：图形推理那种通用题干（「把下面的六个图形分为两类…」）
# 天然会有很多条题干一模一样、内容却不同的题，判重靠的是 (qhash, ohash) 两个一起。
SCHEMA_Q = """
CREATE TABLE IF NOT EXISTS real_questions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT, qtype TEXT,
    stem TEXT, options TEXT, answer TEXT, explain TEXT,
    qhash TEXT, ohash TEXT, fighash TEXT DEFAULT '',
    dkey TEXT,
    material TEXT,                   -- 资料分析的给定资料（ingest_material.py 灌）                       -- 判重键本身：内容没变就靠它把 id 认回来
    sources TEXT,                    -- JSON：这道题在哪些卷子里出现过（去重时合并进来）
    n_src INTEGER DEFAULT 1,
    year_min INTEGER, year_max INTEGER,
    has_answer INTEGER DEFAULT 0,
    needs_asset INTEGER DEFAULT 0,   -- 1 = 脱离图/材料就做不了，出题时要过滤掉
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_rq_mod ON real_questions(module, qtype);
CREATE INDEX IF NOT EXISTS idx_rq_year ON real_questions(year_max);
CREATE INDEX IF NOT EXISTS idx_rq_hash ON real_questions(qhash, ohash);
"""


# real_papers 是长期表（real_raw.paper_id 指着它），不能像 real_questions 那样重建，
# 后加的列只能补 —— CREATE TABLE IF NOT EXISTS 对已存在的表什么都不做。
_ADDCOL = [("real_papers", "answers_ok", "INTEGER DEFAULT 1"),
           ("real_papers", "pkey", "TEXT"),
           ("real_raw", "fighash", "TEXT DEFAULT ''"),
           ("real_questions", "fighash", "TEXT DEFAULT ''"),
           ("real_questions", "dkey", "TEXT"),
           ]


def migrate(con):
    for tab, col, decl in _ADDCOL:
        cols = {r[1] for r in con.execute("PRAGMA table_info(%s)" % tab)}
        if col not in cols:
            con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (tab, col, decl))
    con.commit()


def md5(s):
    return hashlib.md5((s or "").encode("utf-8")).hexdigest()


def ohash_of(options):
    """选项指纹。**按原顺序算，绝不排序。**

    排序看着更聪明（「A/B 卷互换了选项顺序也能认出是同一道题」），实际是个陷阱：
    答案存的是**字母**，而字母指的是位置。2003 国考 A/B 卷同一道「倾销」定义题，
    A 卷正确项排在 D、B 卷排在 C —— 排序后两版指纹相同被合并成一条，
    合并时留下的答案字母就有一半是错的（实测这类冲突真的发生了）。

    宁可同一道题按两种选项顺序各留一条：重复一条只是稍微碍眼，答案错了是致命的。
    """
    return md5("|".join(R.qhash_text(o) for o in options))


def find_path(stored_name):
    for d in sorted(os.listdir(os.path.join(UPLOADS, "drive"))):
        p = os.path.join(UPLOADS, "drive", d, stored_name)
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------- 第一步：全量提取
def scan_files(con, exts):
    rows = con.execute(
        "SELECT id, name, folder, ext, stored_name FROM drive_files "
        "WHERE is_dir=0 AND deleted_at IS NULL AND ext IN (%s) "
        "  AND (folder LIKE '%%行测%%' OR name LIKE '%%行测%%' OR name LIKE '%%行政职业能力%%') "
        "ORDER BY name" % ",".join("?" * len(exts)), exts).fetchall()
    out = []
    for r in rows:
        meta = R.paper_meta(r["name"], r["folder"])
        if meta["kind"] == "申论":            # 申论没有 ABCD，不归这条管线
            continue
        out.append((dict(r), meta))
    return out


def _fig_hashes(path, text):
    """{卷面题号: 该题所有图的内容指纹}。图落在哪一段，那一段之前最近的题号就是它的题。

    题号识别**必须复用 realbank._Q_HEAD**：real_raw.seq 就是它切出来的，
    这里另写一个正则的话，两边对「哪行算题号」的判断会不一致，图就挂到错的题上
    （这类「两个解析器必须对齐」的错位，这个项目已经栽过两次）。
    """
    figs = R.docx_figures(path)
    if not figs:
        return {}
    lines = text.split("\n")
    heads = [(i, int(m.group(1))) for i, ln in enumerate(lines)
             for m in [R._Q_HEAD.match(ln)] if m]
    if not heads:
        return {}
    out = {}
    for para, blob, _ext in figs:
        prev = [seq for i, seq in heads if i <= para]
        if prev:
            out.setdefault(prev[-1], []).append(hashlib.sha256(blob).hexdigest()[:16])
    return {seq: md5("|".join(sorted(v))) for seq, v in out.items()}


def _ocr_answers(con, file_id):
    """取 ocr_answers.py 识别好的扫描件答案，返回 (答案字典, 题号是否按顺序编的)。

    识别结果照样要过后面那两道对齐闸 —— 是 OCR 出来的不代表可以放宽，
    错位的答案比没有答案更糟。
    """
    try:
        row = con.execute("SELECT ans_json, synth FROM real_ocr WHERE file_id=?",
                          (file_id,)).fetchone()
    except sqlite3.Error:
        return {}, False               # 还没建表 = 还没跑过 OCR
    if not row or not row["ans_json"]:
        return {}, False
    try:
        return ({int(k): (v, "") for k, v in json.loads(row["ans_json"]).items()},
                bool(row["synth"]))
    except Exception:
        return {}, False


def _find_answer(answers, name, meta):
    """给一份题目卷找它的答案卷。

    先按规范化文件名精确配；配不上再在**同考试、同年份、卷别令牌完全相同**的范围内
    按名字相似度兜一把 —— 命名并不总是严丝合缝，见过题目卷写「行政执法类」而
    答案卷写「行政执法」这种差一个字的。

    令牌和年份始终是**硬约束**，不参与相似度：「卷（一）」和「卷（二）」的文件名
    只差一个字，相似度高达 0.97，光靠相似度必然配错——那正是这套配对要防的头号事故。
    """
    key = (R.pair_key(name), R.variant_tokens(name))
    if key in answers:
        return answers[key]
    ranked = sorted(
        (difflib.SequenceMatcher(None, key[0], k[0]).ratio(), k)
        for k, v in answers.items()
        if k[1] == key[1] and v[3] == meta["exam"] and v[4] == meta["year"])
    if not ranked or ranked[-1][0] < 0.85:
        return None
    # 两个候选咬得太紧就谁也不选：宁可这卷没答案，也不能挂错
    if len(ranked) > 1 and ranked[-1][0] - ranked[-2][0] < 0.05:
        return None
    return answers[ranked[-1][1]]


def _match_answers(qs, ent):
    """决定这份题目卷能不能用配对到的答案。返回 (答案字典, 不能用的理由)。

    宁可判「不能用」：错位一格的答案会让人背错，比没有答案更糟。
    """
    if not ent:
        return {}, ""
    a, synth, aname = ent[0], ent[1], ent[2]
    if not a:
        return {}, ""
    max_seq = max((q["seq"] for q in qs), default=0)
    if qs and qs[0].get("synth_seq"):
        return {}, "本卷没印题号、题号是解析时按顺序编的，不能拿去对答案卷"
    if synth:
        # 答案卷题号在转档时丢了、只能按顺序编。**这时才做文档里承诺的那道核对**：
        # 解析块数正好等于本卷最大题号 ⇒ 一块对一题，序号天然对齐，可以用。
        # （原先无条件丢弃，白扔掉 13 份卷子约 1300 条答案。）
        if len(a) != max_seq:
            return {}, "答案卷题号丢失，且解析块数 %d 与本卷最大题号 %d 对不上" % (len(a), max_seq)
        return a, ""
    hit = sum(1 for q in qs if q["seq"] in a)
    if hit < len(qs) * 0.6:
        return {}, "答案卷《%s》题号与本卷对不上（命中 %d/%d）" % (aname[:30], hit, len(qs))
    return a, ""


def extract_all(con, exts, force=False):
    """把每份文件解析成 real_raw 里的一条条记录。**不判重**，原样收下。"""
    files = scan_files(con, exts)
    tmp = tempfile.mkdtemp(prefix="realbank-")
    done = {r[0] for r in con.execute("SELECT file_id FROM real_papers WHERE role='q'")} \
        if not force else set()
    stats = {"paper": 0, "q": 0, "a": 0, "skip": 0, "fail": 0}

    # 答案卷**每次都重新解析**，不受 done 跳过：它只进内存的配对表、不写 real_raw，
    # 跳过它没有任何好处，代价却是增量跑时新加进来的题目卷一道答案都拿不到。
    answers = {}                       # (pair_key, variant) -> (答案字典, 是否合成序号, 文件名)
    for r, meta in files:
        if not meta["is_answer"]:
            continue
        p = find_path(r["stored_name"])
        if not p:
            continue
        try:
            a, synth = R.parse_answers(R.file_text(p, tmp)[0])
            if not a:
                # 扫描件（pdftotext 出 0 字符）——用 ocr_answers.py 事先识别好的结果。
                # synth 要一并取回：OCR 出来的题号常常是按顺序编的，
                # 得走「块数必须等于本卷最大题号」那道闸，不能当成真题号直接用。
                a, synth = _ocr_answers(con, r["id"])
        except Exception as e:
            _paper_row(con, r, meta, "a", 0, "failed", str(e)[:200])
            stats["fail"] += 1
            continue
        _paper_row(con, r, meta, "a", len(a),
                   "ok" if a else "empty",
                   ("题号在转档时丢了，按顺序编号，能否使用由题目卷的题数决定" if synth and a else
                    "" if a else "提取不到答案（多半是扫描件、没有文字层，需要 OCR）"))
        stats["a"] += len(a)
        if a:
            # 按**文件名**配对：答案卷名 = 题目卷名 + 「答案及解析」。
            # 卷别令牌必须完全一致，否则《卷（一）》会配上《卷（二）》的答案。
            key = (R.pair_key(r["name"]), R.variant_tokens(r["name"]))
            # 同一份卷子常有多个副本（word 一份 PDF 一份、两个目录各存一份），留解析条数多的
            if len(a) > len(answers.get(key, ({},))[0]):
                answers[key] = (a, synth, r["name"], meta["exam"], meta["year"])

    for r, meta in files:
        if meta["is_answer"]:
            continue
        if r["id"] in done:
            stats["skip"] += 1
            continue
        p = find_path(r["stored_name"])
        if not p:
            _paper_row(con, r, meta, "q", 0, "failed", "云盘里没有这个文件")
            stats["fail"] += 1
            continue
        try:
            text, real_path = R.file_text(p, tmp)
            qs = R.parse_paper(text)
            # 图形推理的题**题干和选项全都一样**（「从所给的四个选项中…」+「如上图所示」×4），
            # 光靠文字判重会把几十道不同的题并成一条。所以在这里就把每道题配的图算成指纹，
            # 让判重看得见图 —— 否则等到提图阶段再补救已经晚了（那时题已经并掉了）。
            # 传 real_path：.doc 已经在 file_text 里转成 docx 了，别再转一遍
            figs = _fig_hashes(real_path, text) if r["ext"] in (".docx", ".doc") else {}
        except Exception as e:
            _paper_row(con, r, meta, "q", 0, "failed", str(e)[:200])
            stats["fail"] += 1
            traceback.print_exc()
            continue

        ent = _find_answer(answers, r["name"], meta)
        ans, why = _match_answers(qs, ent)

        note = "" if qs else "提取不到题目（多半是扫描件，需要 OCR）"
        pid = _paper_row(con, r, meta, "q", len(qs),
                         "ok" if len(qs) >= 50 else ("thin" if qs else "empty"),
                         note or why)
        for q in qs:
            a = ans.get(q["seq"], ("", ""))
            con.execute(
                "INSERT INTO real_raw(paper_id,seq,module,stem,options,answer,explain,"
                "qhash,ohash,fighash) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (pid, q["seq"], q["module"], q["stem"],
                 json.dumps(q["options"], ensure_ascii=False), a[0], a[1],
                 md5(R.qhash_text(q["stem"])), ohash_of(q["options"]),
                 figs.get(q["seq"], "")))
        stats["paper"] += 1
        stats["q"] += len(qs)
        con.commit()
        got = sum(1 for q in qs if ans.get(q["seq"]))
        print("  %-52s %4d 题%s" % (r["name"][:52], len(qs),
                                    "，含答案 %d" % got if got else ("，无答案：" + why if why else "")))
    return stats


def _paper_row(con, r, meta, role, n, status, note=""):
    """写一份卷子的记录。**必须保住 id**：real_raw.paper_id 指着它。

    原先用 INSERT OR REPLACE —— SQLite 的 REPLACE 是 DELETE+INSERT，AUTOINCREMENT
    主键必然换新，上一轮插进 real_raw 的行当场变成孤儿（dedup 的 JOIN 静默丢掉它们，
    report 的「原样提取 N 条」却还在数它们，而且每 --force 一次就积一批死行）。
    """
    con.execute(
        "INSERT INTO real_papers(file_id,name,folder,ext,exam,year,season,paper,kind,"
        "pkey,role,n_item,status,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(file_id) DO UPDATE SET name=excluded.name, folder=excluded.folder, "
        "ext=excluded.ext, exam=excluded.exam, year=excluded.year, season=excluded.season, "
        "paper=excluded.paper, kind=excluded.kind, pkey=excluded.pkey, role=excluded.role, "
        "n_item=excluded.n_item, status=excluded.status, note=excluded.note, "
        # 重新解析过了，上一轮的「答案错位」判定作废，让这一轮的对账重新裁决
        "answers_ok=1",
        (r["id"], r["name"], r["folder"], r["ext"], meta["exam"], meta["year"], meta["season"],
         meta["paper"], meta["kind"] or "行测",
         # 卷子身份：和答案配对用的是同一套 —— (exam,year,paper,season) 不足以区分同一年的两场考试
         # （2020 四川 0725 和 1206 的这四项全一样），必须落到文件名规范化 + 卷别令牌
         "%s|%s" % (R.pair_key(r["name"]), ",".join(sorted(R.variant_tokens(r["name"])))),
         role, n, status, note))
    con.commit()
    pid = con.execute("SELECT id FROM real_papers WHERE file_id=?", (r["id"],)).fetchone()[0]
    # 重跑同一份卷子时，先清掉它上一轮的题 —— 不清就会和新解析的题重复入库
    if role == "q":
        con.execute("DELETE FROM real_raw WHERE paper_id=?", (pid,))
    return pid


# ---------------------------------------------------------------- 第二步：去重合并
def cjk_len(s):
    return sum(1 for c in s if "一" <= c <= "鿿")


# 题干里出现这些字眼 = 题目本体在图里或在材料里，光有这段文字做不了。
# 图形推理的图、资料分析的表格都还没提取，这类题先入库、但标出来别发给人做。
_ASSET_RE = re.compile(r"图形|问号处|下图|上图|如图|图中|所给的?图|"
                       r"上述资料|以上资料|所给资料|根据(?:上述|以上|所给)|下列图|该表|上表")


def needs_asset(stem, is_generic, module=""):
    """这道题脱离图/材料还能不能做。宁可多标：标错了只是少发几道题，
       漏标了就是让人对着「能够从上述资料中推出的是：」四个选项干瞪眼。

    资料分析**整个模块**都要标：这个模块的定义就是「给一段材料再问几个问题」，
    题干里往往连「资料」两个字都不出现（「2011 年该省 GDP 同比增长约：」），
    靠题干措辞根本筛不出来，只能按模块一刀切。
    """
    if module == "资料分析":
        return 1
    return 1 if (is_generic or _ASSET_RE.search(stem or "")) else 0


def dedup(con):
    """把 real_raw 合并进 real_questions。同一道题只留一条，来源全记下。

    判重有三条路，走通任意一条就算同一道题 —— 但每条都带**防误合并**的条件，
    这些条件是踩出来的，不是想出来的：

    ① qhash + ohash 都相同 → 铁定同一道题。最常见，三种重复（word/PDF 同卷、
       有答案/无答案同卷、同年不同卷同题）绝大多数走这条。

    ② 只有 qhash 相同（题干一字不差，选项对不上）→ **默认不合并**。
       图形推理和资料分析的题干是通用句式：「把下面的六个图形分为两类…」
       「能够从上述资料中推出的是：」—— 真正的区别在图里、在材料里，题干完全一样。
       只按 qhash 合的话，92 道不同的图形题会被并成 1 道。
       所以先扫一遍：**一个 qhash 底下出现过不止一种 ohash 的，就是通用题干**，
       这类永不按题干合并。这是从数据里数出来的，不用维护「通用句式」词表。

    ③ 只有 ohash 相同（选项一字不差，题干有出入）→ 用来兜 word 版和 PDF 版之间的
       转写差异。但要求选项**含实打实的汉字**（≥12 个）：图形题的选项是
       「①③④，②⑤⑥」这种符号串，不同题之间撞车是常事，按它合并必错。
    """
    # 重建前先把「内容指纹 → 旧 id」记下来，**重建时按原 id 插回去**。
    # real_questions 是推导表、每次 dedup 都重建，但 real_explains（几千条 AI 解析）、
    # real_figs、real_attempts、review_state 全都拿 qid 指着它 —— 让 id 随重建乱跳的话，
    # 每改一次判重规则，下游引用就全成孤儿。内容没变就沿用原来的号。
    # 键必须是**判重键本身**，不能是 (qhash,ohash,fighash)：
    # 「永不合并」那一类（通用题干/通用选项且没有图）用的是 raw<行号>，
    # 多条行共享同一组 (q,o,fh)，用它当键会撞车、每次跑抢到 id 的行都不一样，
    # 于是 dedup 就不幂等了（实测每跑一次都有几条解析变孤儿）。
    keep = {}
    try:
        for r in con.execute("SELECT id, dkey, material, needs_asset FROM real_questions "
                             "WHERE dkey IS NOT NULL"):
            keep[r["dkey"]] = (r["id"], r["material"], r["needs_asset"])
    except sqlite3.Error:
        pass
    # 资产（图/材料）是另外三个脚本灌进来的，**重建时必须原样带回来**：
    # material 存在 real_questions 自己身上，一 DROP 就没了；
    # needs_asset 更隐蔽 —— 它是那三个脚本按各自的标准「翻」的标志位
    # （图形题要 ≥5 张图或一张大图；资料分析要材料正文和表格图都到位），
    # 而这里原先每次都按题干重算一遍，跑一次 ingest_real 就把它们的产出全部悄悄锁回去。
    #
    # 这里**不重新判定「资产够不够」**：那套标准归资产脚本管，在两个地方各写一份
    # 迟早会打架（实测就打过：这边按「有图或有材料」放行，比 ingest_material 自己的
    # 「材料和图都要有」松，解封数比有材料的题还多）。dedup 只负责一件事 ——
    # 内容没变就把上一轮的判定原样搬回来。
    con.execute("UPDATE real_raw SET qid=NULL")
    con.execute("DROP TABLE IF EXISTS real_questions")
    con.executescript(SCHEMA_Q)
    con.commit()
    used = set()

    # 先数两遍，**两个方向都要数**：
    #   · 通用题干：同一题干配过多种选项 → 题干区分不了题，不按题干合并
    #   · 通用选项：同一组选项配过多种题干 → 选项区分不了题，不按选项合并
    # 只数第一个方向会漏掉镜像情况，而且漏得很惨：图形推理的选项**全是「如上图所示」**，
    # 于是「立体图形剖开」「饼图」「纸盒展开」「正方体堆叠」12 道完全不同的题
    # 因为选项指纹相同被并成一条 —— 每道题各自只有一种选项组，谁也没被判成通用题干。
    generic = {r[0] for r in con.execute(
        "SELECT qhash FROM real_raw GROUP BY qhash HAVING COUNT(DISTINCT ohash) > 1")}
    generic_opts = {r[0] for r in con.execute(
        "SELECT ohash FROM real_raw GROUP BY ohash HAVING COUNT(DISTINCT qhash) > 1")}
    print("  通用题干 %d 种、通用选项组 %d 种（这两类都不能单独拿来判重）"
          % (len(generic), len(generic_opts)))

    rows = con.execute(
        # answers_ok=0 的卷子（被判定题号错位）**只屏蔽答案、题目照常收**。
        # 屏蔽而不是把 real_raw 改掉：那一层是「原样提取、一条不落」的底稿，
        # 改坏了就再也调不了阈值、也没法复查误判，只能整条管线重跑。
        "SELECT rr.id, rr.paper_id, rr.seq, rr.module, rr.stem, rr.options, rr.qhash, rr.ohash, "
        "       COALESCE(rr.fighash,'') fighash, "
        "       CASE WHEN p.answers_ok=0 THEN '' ELSE rr.answer END AS answer, "
        "       CASE WHEN p.answers_ok=0 THEN '' ELSE rr.explain END AS explain, "
        "       p.exam, p.year, p.season, p.paper, p.name AS pname "
        "FROM real_raw rr JOIN real_papers p ON p.id=rr.paper_id "
        # 有答案的排前面：同一道题留哪一条，优先留带答案解析的那条
        "ORDER BY (answer<>'') DESC, p.year DESC, rr.id").fetchall()

    by_qo, by_q, by_o, merged = {}, {}, {}, 0
    by_fig = {}
    conflicts = []
    for r in rows:
        opts = json.loads(r["options"])
        # 图指纹进判重键：图形推理的题干和选项全都一样，**只有图不一样**。
        # 不带图的话，25 道不同的图形题会被并成一条，然后 25 份卷子的图全堆到它头上，
        # 答案也只属于其中一道 —— 那道题就废了（实测 qid=271 就是这么来的）。
        fh = r["fighash"] or ""
        # 通用题干（题干和选项都区分不出题目）**又没提到图** ⇒ 我们手上根本没有任何
        # 能区分它们的信息。这时合并等于凭空断言「这几道是同一题」，造出来的是缝合怪：
        # 答案只属于其中一道、图会堆一堆。宁可各留各的（反正 needs_asset=1 不会发出去），
        # 将来提到图了还能各自挂对。
        # **两个方向都通用**才叫「手上没有任何能区分它们的信息」。
        # 写成 or 的话，题干本来能标识题、只是选项恰好撞进 generic_opts 的普通题
        # 也会被拆开（实测 68 组 word 版/PDF 版就是这么分家的）。
        if r["qhash"] in generic and r["ohash"] in generic_opts and not fh:
            qo = "raw%d" % r["id"]
        else:
            qo = r["qhash"] + r["ohash"] + fh
        qid = by_qo.get(qo)
        # 题干/选项相同但**图不同** ⇒ 铁定不是同一道题，后面两条模糊路一律不走
        # 用「(题干,选项) → 见过哪些图指纹」的索引判，别遍历整个集合（那是 O(n²)，10 万次起）
        seen_figs = by_fig.get((r["qhash"], r["ohash"]))
        fig_differs = bool(fh and seen_figs and fh not in seen_figs)
        if not qid and not fig_differs and r["qhash"] not in generic:
            qid = by_q.get(r["qhash"])
        # ohash-only 这条路是用来兜「题干转写有出入、选项一字不差」的，
        # 对**通用题干**毫无意义：它的题干本来就一模一样，选项也是通用的
        # （图形题四个选项全是「如上图所示」，20 个汉字轻松过阈值），
        # 于是这条路会把上面刚按图分开的题又原样并回去。
        if not qid and not fig_differs and r["qhash"] not in generic \
                and r["ohash"] not in generic_opts and cjk_len("".join(opts)) >= 12:
            qid = by_o.get(r["ohash"])
        src = {"exam": r["exam"], "year": r["year"], "paper": r["paper"],
               "season": r["season"], "seq": r["seq"], "file": r["pname"]}

        if qid:
            merged += 1
            row = con.execute("SELECT sources,answer,explain,year_min,year_max FROM real_questions "
                              "WHERE id=?", (qid,)).fetchone()
            srcs = json.loads(row["sources"])
            srcs.append(src)
            # ★ 免费的对账：同一道题在两份卷里都有答案，两个答案却不一样 →
            #   一定有一份的题号对齐错了。这是唯一不用人工看就能发现错位的信号，
            #   （答案错位的坑真踩过：整卷答案错开一位，抽查五道全错）
            if row["answer"] and r["answer"] and row["answer"] != r["answer"]:
                conflicts.append((qid, row["answer"], r["answer"], src))
            # 先前那条没答案、这条有 → 把答案补上（「无答案版 + 答案版」正是这么合的）
            ans = row["answer"] or r["answer"]
            ex = row["explain"] or r["explain"]
            yrs = [s["year"] for s in srcs if s["year"]]
            con.execute("UPDATE real_questions SET sources=?, n_src=?, answer=?, explain=?, "
                        "has_answer=?, year_min=?, year_max=? WHERE id=?",
                        (json.dumps(srcs, ensure_ascii=False), len(srcs), ans, ex,
                         1 if ans else 0, min(yrs or [0]), max(yrs or [0]), qid))
        else:
            # 内容没变就用回原来的 id（见上面 keep 的注释）
            old_id, old_mat, old_na = keep.get(qo, (None, None, None))
            qid = old_id if (old_id and old_id not in used) else None
            cur = con.execute(
                "INSERT INTO real_questions(id,module,qtype,stem,options,answer,explain,"
                "qhash,ohash,fighash,dkey,material,"
                "sources,n_src,year_min,year_max,has_answer,needs_asset) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)",
                (qid,
                 r["module"], R.classify_qtype(r["module"], r["stem"], json.loads(r["options"])),
                 r["stem"], r["options"], r["answer"], r["explain"],
                 r["qhash"], r["ohash"], fh, qo, old_mat,
                 json.dumps([src], ensure_ascii=False), r["year"], r["year"],
                 1 if r["answer"] else 0,
                 # 这道题上一轮是什么判定就还是什么；全新的题才按题干算
                 old_na if old_na is not None
                 else needs_asset(r["stem"], r["qhash"] in generic, r["module"])))
            qid = qid or cur.lastrowid
            used.add(qid)
            by_qo[qo] = qid
            by_fig.setdefault((r["qhash"], r["ohash"]), set()).add(fh)
            by_q.setdefault(r["qhash"], qid)
            by_o.setdefault(r["ohash"], qid)
        con.execute("UPDATE real_raw SET qid=? WHERE id=?", (qid, r["id"]))
    con.commit()
    uniq = con.execute("SELECT COUNT(*) FROM real_questions").fetchone()[0]
    return {"raw": len(rows), "uniq": uniq, "merged": merged, "conflicts": conflicts}


_CJK_RUN = re.compile(r"[一-鿿]{2,}")


def _bigrams(s):
    out = set()
    for run in _CJK_RUN.findall(s or ""):
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
    return out


def alignment_scores(con, min_q=20):
    """每份卷子的「解析 ↔ 题干 词汇重合度」。

    答案错位的卷子，每道题配到的是**别的题**的解析，用词自然对不上，重合度断崖式下跌。
    实测：错位的两份是 0.083 / 0.084，其余 39 份全在 0.23 ~ 0.47，中间隔着 3 倍。

    这条检测的价值在于**不需要第二份卷子**。跨卷投票（quarantine_bad_answers）有个
    死角：2023 国考副省级和地市级两份答案卷**同时**错位，互相对照时谁也证不了谁的伪，
    18 处冲突还够不上 20% 的阈值，就那么混过去了。
    """
    acc = {}
    for r in con.execute(
            "SELECT rr.paper_id, rr.stem, rr.explain FROM real_raw rr "
            "WHERE rr.answer<>'' AND LENGTH(rr.explain)>60"):
        s = _bigrams(r["stem"])
        if len(s) < 5:
            continue
        acc.setdefault(r["paper_id"], []).append(len(s & _bigrams(r["explain"])) / len(s))
    return {p: sum(v) / len(v) for p, v in acc.items() if len(v) >= min_q}


def quarantine_misaligned(con, floor=0.12, rel=0.45):
    """整卷解析都对不上题干 → 答案错位，屏蔽。返回是否动过手。

    阈值取「地板值」和「全库中位数的 45%」里更大的那个 —— 不写死绝对值：
    素材换一批，解析的详略程度会整体平移，写死的线要么失灵要么误伤。
    """
    scores = alignment_scores(con)
    if len(scores) < 5:                      # 样本太少，中位数不可信，不做判断
        return False
    med = statistics.median(scores.values())
    cut = max(floor, med * rel)
    hit = [(p, s) for p, s in scores.items() if s < cut]
    if not hit:
        return False
    print("\n⚠️ 以下卷子的解析和题干对不上号（整卷答案错位），屏蔽其答案："
          "（全库中位数 %.3f，判定线 %.3f）" % (med, cut))
    for pid, s in sorted(hit, key=lambda x: x[1]):
        name = con.execute("SELECT name FROM real_papers WHERE id=?", (pid,)).fetchone()["name"]
        print("   重合度 %.3f  %s" % (s, name[:56]))
        con.execute("UPDATE real_papers SET answers_ok=0, status='answers_bad', "
                    "note='解析与题干词汇重合度仅 %.3f（全库中位数 %.3f），判定为整卷答案错位' "
                    "WHERE id=?" % (s, med), (pid,))
    con.commit()
    return True


def quarantine_bad_answers(con, bad_rate=0.2, min_check=5):
    """把「答案成片对不上」的卷子整份作废。返回是否动过手。

    一份卷子的答案对不对，单看它自己是看不出来的。但国考副省级/地市级/行政执法
    三卷之间大面积共题，省考和联考也串题 —— 同一道题在别的卷子里也有答案，
    两边一比就露馅：**超过 20% 的题和多数意见不一致，就是这份卷子自己错位了**。
    （2022 四川下半年那份错了 70%，2023 国考地市级错了 56%，都是这么抓出来的。）
    """
    rows = con.execute(
        "SELECT rr.qid, rr.answer, rr.paper_id FROM real_raw rr "
        "JOIN real_papers p ON p.id=rr.paper_id "
        "WHERE rr.answer<>'' AND rr.qid IS NOT NULL AND p.answers_ok=1").fetchall()
    by_q = {}
    for r in rows:
        by_q.setdefault(r["qid"], []).append(r)

    bad, tot = {}, {}
    for lst in by_q.values():
        if len(lst) < 2:
            continue
        votes = {}
        for r in lst:
            votes[r["answer"]] = votes.get(r["answer"], 0) + 1
        ranked = sorted(votes.values(), reverse=True)
        # **必须是严格多数**：2 票对 2 票时谁也说服不了谁，按 max() 取到的「赢家」
        # 只是字典序靠前而已，照此判负方两卷有罪等于掷硬币定罪。
        if len(ranked) > 1 and ranked[0] == ranked[1]:
            continue
        win = max(votes, key=votes.get)
        for r in lst:
            tot[r["paper_id"]] = tot.get(r["paper_id"], 0) + 1
            if r["answer"] != win:
                bad[r["paper_id"]] = bad.get(r["paper_id"], 0) + 1

    hit = [(p, bad[p], tot[p]) for p in bad
           if tot[p] >= min_check and bad[p] / tot[p] > bad_rate]
    if not hit:
        return False
    print("\n⚠️ 以下卷子的答案成片对不上，屏蔽其答案（题目保留，底稿不动）：")
    for pid, b, t in sorted(hit, key=lambda x: -x[1] / x[2]):
        name = con.execute("SELECT name FROM real_papers WHERE id=?", (pid,)).fetchone()["name"]
        print("   %5.1f%% 不一致（%d/%d）  %s" % (100.0 * b / t, b, t, name[:52]))
        con.execute("UPDATE real_papers SET answers_ok=0, status='answers_bad', "
                    "note='答案与其他卷子成片冲突（%d/%d），判定为题号错位，已屏蔽其答案' "
                    "WHERE id=?" % (b, t), (pid,))
    con.commit()
    return True


# ---------------------------------------------------------------- 报告
def report(con):
    print("\n" + "=" * 62)
    q = con.execute("SELECT COUNT(*) c, SUM(has_answer) a FROM real_questions").fetchone()
    raw = con.execute("SELECT COUNT(*) FROM real_raw").fetchone()[0]
    print("原样提取 %d 条 → 去重后 %d 道真题，其中 %d 道带答案解析（%.0f%%）"
          % (raw, q["c"], q["a"] or 0, 100.0 * (q["a"] or 0) / max(1, q["c"])))

    print("\n【按模块】")
    for r in con.execute("SELECT module, COUNT(*) c, SUM(has_answer) a FROM real_questions "
                         "GROUP BY module ORDER BY c DESC"):
        print("  %-14s %5d 道，带答案 %d" % (r["module"] or "（未归类）", r["c"], r["a"] or 0))

    print("\n【重复情况】同一道题出现过几次")
    for r in con.execute("SELECT n_src, COUNT(*) c FROM real_questions GROUP BY n_src "
                         "ORDER BY n_src LIMIT 8"):
        print("  出现 %d 次：%d 道" % (r["n_src"], r["c"]))
    print("  最常重复的几道：")
    for r in con.execute("SELECT n_src, stem, sources FROM real_questions "
                         "ORDER BY n_src DESC LIMIT 3"):
        yrs = sorted({"%s%s" % (s["year"], s["paper"] or "") for s in json.loads(r["sources"])})
        print("    ×%d  %s… \n         出自 %s" % (r["n_src"], r["stem"][:40], "、".join(yrs)))

    # answers_bad 必须在列：那是**最该人工复核**的一档（答案被判错位、整卷屏蔽），
    # 漏掉它等于把最需要看的几份藏起来。answers_bad 排最前。
    bad = con.execute(
        "SELECT name, status, note FROM real_papers "
        "WHERE status IN ('answers_bad','failed','empty','thin') "
        "ORDER BY CASE status WHEN 'answers_bad' THEN 0 WHEN 'failed' THEN 1 "
        "                     WHEN 'thin' THEN 2 ELSE 3 END, name").fetchall()
    if bad:
        print("\n【需要人工看一眼的 %d 份】" % len(bad))
        for r in bad:
            print("  [%-11s] %-46s %s" % (r["status"], r["name"][:46], (r["note"] or "")[:46]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ext", default="docx,doc,pdf", help="处理哪些格式（默认全部）")
    ap.add_argument("--scan", action="store_true", help="只列出要处理的文件，不动库")
    ap.add_argument("--dedup-only", action="store_true", help="不重新解析，只重跑去重")
    ap.add_argument("--force", action="store_true", help="已处理过的文件也重新解析")
    a = ap.parse_args()
    exts = ["." + e.strip(". ") for e in a.ext.split(",") if e.strip()]

    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    migrate(con)

    if a.scan:
        files = scan_files(con, exts)
        print("共 %d 份：" % len(files))
        for r, m in files:
            print("  [%s] %s %s%s %-8s %s" % ("答案" if m["is_answer"] else "题目", m["exam"],
                                              m["year"], m["season"], m["paper"], r["name"][:52]))
        return

    t0 = time.time()
    if not a.dedup_only:
        print("【第一步】全量提取（不判重）")
        s = extract_all(con, exts, a.force)
        print("提取完成：%d 份卷子、%d 道题、%d 条答案，跳过 %d，失败 %d"
              % (s["paper"], s["q"], s["a"], s["skip"], s["fail"]))

    print("\n【第二步】去重合并")
    # 隔离判定是**每次重新裁决**的（纯粹由当前数据推出），先把上一轮的结论清空，
    # 否则调了阈值也翻不了案。
    con.execute("UPDATE real_papers SET answers_ok=1")
    con.commit()
    # 先做**不依赖第二份卷子**的自检：整卷解析都对不上题干 = 答案错位。
    # 放在跨卷投票之前，因为投票有死角（两份卷子同时错位时互相证不了伪）。
    quarantine_misaligned(con)
    d = dedup(con)
    # 去重顺带把答案对了一遍账。某份卷子的答案**成片**和别人不一致 = 它自己错位了，
    # 屏蔽它的答案重来 —— 单看一份卷子是发现不了错位的，只有互相对照才看得出。
    # 循环到稳定：屏蔽掉一份之后，剩下的多数票可能变，进而暴露出下一份。
    for _ in range(3):
        if not quarantine_bad_answers(con):
            break
        print("\n【第二步·重跑】屏蔽掉错位的答案卷之后重新去重")
        d = dedup(con)
    print("%d 条原始记录 → %d 道不重复的题（合并掉 %d 条重复）"
          % (d["raw"], d["uniq"], d["merged"]))
    if d["conflicts"]:
        print("⚠️ %d 处答案打架（同一道题在不同卷里答案不同）—— 多半是某份答案卷题号错位："
              % len(d["conflicts"]))
        for qid, a1, a2, src in d["conflicts"][:10]:
            print("   题 %s：%s vs %s  （后者出自 %s %s %s 第%s题）"
                  % (qid, a1, a2, src["exam"], src["year"], src["paper"], src["seq"]))
    else:
        print("✓ 答案对账：多来源的题，答案全部一致")
    report(con)
    print("\n耗时 %.1f 分钟" % ((time.time() - t0) / 60))
    con.close()


if __name__ == "__main__":
    main()
