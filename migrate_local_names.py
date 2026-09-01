#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把库里几个**代码要精确匹配**的旧名字换成中性写法。

背景：源码里原来写死了考区的地名（考点大类叫「XX 县情」、专项卷叫「XX 专项 · 地方
必得分」）。仓库是公开的，这些名字连同镇名、报名点合起来能定位到人，所以全部换成
「本地县情」「本地专项 · 地方必得分」，真地名只留在 local_meta.json 里（.gitignore
忽略）。

**为什么非跑这一趟不可**：这两个字符串是 code 和 data 的接缝 ——
`core.SQ_BOARDS`、`ingest_shequ.QTYPE_RULES`、`build_local.QTYPE` 用新名字查，
库里存的还是旧名字，对不上的下场不是报错，是**「本地县情」这一格永远查不到题**。

**这个脚本自己也不许写死旧地名。** 写死了等于把刚清掉的东西又提交回公开仓库一份。
所以两条路子：能靠形状认的（`%县情`、`%专项 · 地方必得分`）就按形状认；认不出形状的
（备考路线那段 JSON），临时从 local_meta.json 里读出县名**在运行时**拼出旧写法。
没有那份文件就只跑前一半，并如实说哪几项跳过了。

不动的东西（说清楚，免得以为漏了）：
  · `sq_papers.region`、卷名里的 PDF 原文件名、题干、AI 会话 —— 那些是**本地数据**，
    app.db 本来就在 .gitignore 里，不出这台机器，换掉反而丢信息。
  · 云盘目录名 —— 它得和盘上真实的目录对得上，改了入库脚本就扫不到卷子。

用法：
    python3 migrate_local_names.py            # 只看会改什么，不写库
    python3 migrate_local_names.py --apply    # 真改（先自动备份 app.db）
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import localprofile                                        # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))

QTYPE_NEW = "本地县情"
PAPER_NEW = "本地专项 · 地方必得分"


def old_words():
    """旧写法：`地名短写 + 后缀`。地名从 local_meta.json 现取，源码里不留。

    没有那份文件就返回 []，靠形状认的那两项照跑。
    """
    reg = localprofile.meta().get("region")
    if not reg:
        return []
    short = reg.rstrip("县市区旗") or reg
    # (旧, 新)。长的排前面，先换长的免得被短的截胡。
    return [(short + "社区专职工作者", "社区专职工作者"),
            (short + "专项 · 地方必得分", PAPER_NEW),
            (short + "县情", QTYPE_NEW),
            (short + "专项", "本地专项"),
            (short + "真题", "本地真题")]


def plan(con):
    """列出要改的活儿：(说明, 查计数的 SQL, 参数, 干活的函数)。"""
    jobs = []

    # ① 考点大类：凡是以「县情」结尾、又不是新名字的，都是旧的
    jobs.append((
        "sq_questions.qtype  %s → %r" % ("以「县情」结尾的", QTYPE_NEW),
        "SELECT COUNT(*) FROM sq_questions WHERE qtype LIKE '%县情' AND qtype<>?",
        (QTYPE_NEW,),
        lambda c: c.execute("UPDATE sq_questions SET qtype=? "
                            "WHERE qtype LIKE '%县情' AND qtype<>?", (QTYPE_NEW, QTYPE_NEW))))

    # ② 专项卷名：kind='专项' 且卷名是「…专项 · 地方必得分」这个形状
    jobs.append((
        "sq_papers.name      形如「…专项 · 地方必得分」→ %r" % PAPER_NEW,
        "SELECT COUNT(*) FROM sq_papers WHERE kind='专项' "
        "AND name LIKE '%专项 · 地方必得分' AND name<>?",
        (PAPER_NEW,),
        lambda c: c.execute("UPDATE sq_papers SET name=? WHERE kind='专项' "
                            "AND name LIKE '%专项 · 地方必得分' AND name<>?",
                            (PAPER_NEW, PAPER_NEW))))

    # ③ 出处标记：verify_note 里的 "src" 指向改名前的脚本。**只认 build_*.py 这个形状**
    #    —— src 是个通用字段，同一列里还躺着 'docx' / 'ocr' / 'ABCD'（题目从哪儿来、
    #    校对是谁给的答案），一律改掉会把一千多行的出处抹平。整条 JSON 读出来改字段，
    #    不做字符串替换：替换要先知道旧文件名，那又是一处写死。
    jobs.append((
        'sq_questions.verify_note  "src" 指向旧的 build_*.py → "build_local.py"',
        "SELECT COUNT(*) FROM sq_questions WHERE verify_note LIKE ? "
        "AND verify_note NOT LIKE ?",
        # LIKE 里 `_` 是「任意一个字符」，正好也匹配字面的下划线；
        # 真正把关的是 _fix_src 里那行 startswith/endswith。
        ('%"src": "build_%.py%', "%build_local.py%"),
        _fix_src))

    # ④ 备考路线快照：一整块 JSON，认不出形状，只能拿现取的地名去替
    for old, new in old_words():
        jobs.append((
            "plan_roadmap.data_json  含旧写法 → %r" % new,
            "SELECT COUNT(*) FROM plan_roadmap WHERE data_json LIKE ?",
            ("%" + old + "%",),
            (lambda o, n: lambda c: c.execute(
                "UPDATE plan_roadmap SET data_json=REPLACE(data_json,?,?) "
                "WHERE data_json LIKE ?", (o, n, "%" + o + "%")))(old, new)))
    return jobs


def _fix_src(con):
    rows = con.execute("SELECT id, verify_note FROM sq_questions "
                       "WHERE verify_note LIKE ? AND verify_note NOT LIKE ?",
                       ('%"src": "build_%.py%', "%build_local.py%")).fetchall()
    for qid, note in rows:
        try:
            d = json.loads(note)
        except (ValueError, TypeError):
            continue                      # 不是 JSON 就别动它
        src = d.get("src") if isinstance(d, dict) else None
        # 再确认一次形状：SQL 的 LIKE 只是粗筛，真正决定改不改的是这一行
        if not (isinstance(src, str) and src.startswith("build_") and src.endswith(".py")):
            continue
        d["src"] = "build_local.py"
        con.execute("UPDATE sq_questions SET verify_note=? WHERE id=?",
                    (json.dumps(d, ensure_ascii=False), qid))


def counts(con, jobs):
    return [(desc, con.execute(sql, args).fetchone()[0]) for desc, sql, args, _ in jobs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真改（不加就只看）")
    a = ap.parse_args()

    if not os.path.exists(DB):
        print("找不到库：%s" % DB)
        return 1
    if not old_words():
        print("! 没读到 local_meta.json 里的 region：备考路线那几项跳过，"
              "其余照形状认，照跑。")

    con = sqlite3.connect(DB)
    jobs = plan(con)
    rows = counts(con, jobs)
    total = sum(n for _, n in rows)

    for desc, n in rows:
        print("%s%s：%d 行" % ("  " if n else "· ", desc, n))
    print("合计 %d 行" % total)

    if not a.apply:
        print("\n（只看不改。真要改：python3 migrate_local_names.py --apply）")
        return 0
    if not total:
        print("\n没有要改的，库已经是新名字了。")
        return 0

    bak = "%s.bak.rename-%s" % (DB, time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(DB, bak)
    print("\n已备份 → %s" % bak)

    for _, _, _, run in jobs:
        run(con)
    con.commit()

    left = sum(n for _, n in counts(con, jobs))
    print("改完。复查残留：%d 行" % left)
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
