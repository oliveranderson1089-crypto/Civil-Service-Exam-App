"""备考方向：**两条线并存，互不打搅，谁也不删谁**。

背景：这个应用原本只服务公务员考试；2026 年 8 月加了第二条线（社区专职工作者，
另一场笔试，日期由公告定死、存在 local_meta.json 里）。考完社区还要回头接着
考公 —— 所以两条线的数据必须
**都留着**，只是不能混在一起看：

  · 错题本混在一起 → 复习社区时一半是行测题，翻不动；
  · 今日复习混在一起 → 遗忘曲线把两门课的卡片交替推，哪门都记不牢；
  · 每日测试混在一起 → 一份小测里既有资料分析又有社会工作，练的是切换成本；
  · 备考规划混在一起 → 两个考试日期、两套配额，排出来的计划自相矛盾。

所以这里只做一件事：**给出「当前这条线包含哪些板块」**，让上面那四处按它过滤。
它是个视图开关，不是数据开关 —— 切过去切回来，两边的记录一条不少。

三条硬规矩：

  1. **切换不改数据。** 只写 users.exam_line 一个字段，任何题目、错题、复习进度
     都不动。这条是用户明确要求的：「考了之后我还要复习公考」。
  2. **不认识的板块两边都显示。** 错题本里有用户手打的板块名（「社会工作实务
     （社区工作者）」这种），它不在任何一条线的清单里。宁可让它在两条线里都出现，
     也不能因为我们的分类不认识它就把用户的数据藏起来。
  3. **板块清单只有一份。** 公考那两组直接取 core.SECTIONS，社区取 core.SQ_BOARDS，
     不在这儿另抄一份 —— 抄了迟早和上游走散，而走散的表现是「某个板块的错题
     两条线里都看不见」。
"""
from core import SECTIONS, SQ_BOARDS, get_db, uid

GONGKAO = "gongkao"
SHEQU = "shequ"
DEFAULT = GONGKAO          # 老用户维持原样：不切就是原来那套，什么都没变

LINES = {
    GONGKAO: {"key": GONGKAO, "name": "公务员考试", "short": "公考",
              "desc": "行测 + 申论"},
    SHEQU: {"key": SHEQU, "name": "社区工作者", "short": "社区",
            "desc": "社工初级 + 社区建设 + 基层治理 + 法律常识"},
}


def line_boards(line):
    """这条线包含哪些板块。取自 core，不另抄一份。"""
    if line == SHEQU:
        return set(SQ_BOARDS)
    return {b for s in SECTIONS if s["key"] != SHEQU for b in s["boards"]}


def all_known():
    return line_boards(GONGKAO) | line_boards(SHEQU)


def current(db=None, u=None):
    """当前方向。读不到就按默认，**绝不因为读不到就把人挡在外面**。"""
    db = db or get_db()
    try:
        r = db.execute("SELECT exam_line FROM users WHERE id=?", (u or uid(),)).fetchone()
    except Exception:
        return DEFAULT
    v = (r["exam_line"] if r and r["exam_line"] else "") or DEFAULT
    return v if v in LINES else DEFAULT


def set_current(line, db=None, u=None):
    if line not in LINES:
        return False
    db = db or get_db()
    db.execute("UPDATE users SET exam_line=? WHERE id=?", (line, u or uid()))
    db.commit()
    return True


def guess_line(board):
    """认不出的板块名归到哪条线。返回线名，实在认不出返回 ""。

    错题本里有一批**用户自己打的板块名**：「行测·数量关系」「言语理解」
    「社会工作实务（社区工作者）」。一律「两边都显示」的话，社区那条线里会混进
    明显是行测的错题（实测：社区方向下 10 条错题全是「言语理解 6 / 行测·数量关系 4」）。
    所以先按**名字里含不含已知板块**归队 —— 「行测·数量关系」含「数量关系」，
    「社会工作实务（社区工作者）」含「社会工作」，都认得出来。
    双向包含都试：用户打的名字可能比标准名短（「言语理解」是「言语理解与表达」的前缀）。
    """
    b = (board or "").strip()
    if not b:
        return ""
    for ln in (GONGKAO, SHEQU):
        for known in line_boards(ln):
            if known in b or (len(b) >= 3 and b in known):
                return ln
    return ""


def in_line(board, line):
    """这个板块该不该在这条线里出现。

    认不出归属的（既不在清单里、名字也套不上）**两边都显示** —— 因为我们的分类
    不认识它就把人家记的错题藏起来，是最糟的做法。
    """
    b = (board or "").strip()
    if not b:
        return True
    if b in all_known():
        return b in line_boards(line)
    g = guess_line(b)
    return (g == line) if g else True


def board_names(db, table="wrong_questions", col="board"):
    """库里实际出现过的板块名（含用户手打的）。SQL 过滤要拿它做归队。"""
    try:
        return [r[0] for r in db.execute(
            "SELECT DISTINCT %s FROM %s WHERE %s IS NOT NULL AND %s<>''"
            % (col, table, col, col)) if r[0]]
    except Exception:
        return []


def sql_filter(col, line, db=None, table="wrong_questions"):
    """给 SQL 用的判据，和 in_line() **必须同义**。

    做法是先把库里出现过的板块名逐个用 in_line() 判一遍，再拼成一条 IN。
    比在 SQL 里重写一遍归队规则可靠：规则只存在于 in_line() 一处，
    两处各写一份的话，列表条数和统计数字会对不上而且不报错。
    """
    names = set(board_names(db or get_db(), table, col)) | all_known()
    keep = sorted(n for n in names if in_line(n, line))
    if not keep:
        return "1=0", []
    return ("(%s IS NULL OR %s='' OR %s IN (%s))"
            % (col, col, col, ",".join(["?"] * len(keep)))), keep


def pub(db=None, u=None):
    """下发给前端：当前方向 + 两条线的元信息。"""
    cur = current(db, u)
    return {"line": cur, "lines": [LINES[GONGKAO], LINES[SHEQU]],
            "boards": sorted(line_boards(cur))}

