"""真题当基准时的**公共口径**：哪些真题能用、板块对应卷面上哪个模块。

为什么单独一个模块：同一套口径有三个地方要用 ——
  · realq.py     真题练习，决定哪些题发给人做
  · drill.py     AI 出题时拿真题当范例 / 算篇幅分位
  · audit_qtype.py 体检表，报告这套机制吃到了多少干净数据
原先三处各写各的（还各用各的表别名），改口径就得同步三处。漏一处的表现是
**审计数字和线上实际取到的题对不上** —— 而审计脚本存在的全部意义就是当那个唯一可信的数字。
"""
import sqlite3

# 表别名各处不一样（realq 用 q/e，drill 和审计用 rq/re），所以口径写成按别名拼的函数，
# 不写成裸字符串常量 —— 常量只能服务一种别名，于是必然被复制第二份。


def servable(q="q", e="e"):
    """「这道真题靠不靠得住」：原卷带答案，或 AI 出解析且过了双模型核验。

    答案存疑的题留在库里可以回查，但绝不发给人做，也绝不当出题范例 ——
    拿去背错的答案，比不做还糟。
    """
    return "%s.needs_asset=0 AND (%s.has_answer=1 OR %s.agree=1)" % (q, q, e)


def qtype_expr(q="q", e="e"):
    """题型：优先用解析器按规则判的，判不出来的用 AI 顺手判的补。

    ⚠️ **它不带模块约束**，AI 判的那部分会跨模块乱标（实测把「2012—2020年，中国IC
    封装市场规模同比增量最大的年份是：」标成「语境分析」）。所以凡是按题型取题的地方，
    都必须**再加一条模块条件**，别只信这个表达式。
    """
    return "COALESCE(NULLIF(%s.qtype,''), %s.qtype, '')" % (q, e)


# 板块 → 真题卷面上的模块名。**政治理论在卷面上不是独立模块**，它的题混在常识判断里，
# 不映射过去就一道真题都取不到。gen_real_explain.py 分类时也按这个映射合并候选题型，
# 两边必须同源 —— 各写一份的话，哪天这里改了归属，那边不会跟着变，
# 表现是政治理论四个题型的范例数突然归零而没有任何报错。
BOARD_MODULE = {"资料分析": "资料分析", "言语理解与表达": "言语理解与表达",
                "判断推理": "判断推理", "数量关系": "数量关系",
                "常识判断": "常识判断", "政治理论": "常识判断"}


def board_module(board):
    return BOARD_MODULE.get(board, board)


def merged_qtypes(qtypes):
    """把子板块的题型并进它在卷面上所属的模块（政治理论 → 常识判断）。

    给 gen_real_explain.py 判题型时用：常识判断的卷面里混着大量时政/理论题，
    只给常识那七类会硬塞进不合适的桶。
    """
    out = {}
    for board, ts in qtypes.items():
        out.setdefault(board_module(board), []).extend(ts)
    return out


# _real_style 算篇幅分位的样本下限：少于这些道数就不算分位、直接放弃篇幅约束。
# 审计脚本要按同一个数标注「样本不足」，所以放这儿共用 —— 各写一份的话，
# 哪天下限调到 20，审计表还按 12 判，会报告「一切正常」而实际已有一批题型不卡篇幅了。
STYLE_MIN = 12

# 比中位数还短这么多倍的样本，当**残题**丢掉，不参与分位统计。
# 为什么需要：片段阅读的文段存在 material 列，而有一批题入库时材料没跟过来，
# 剩下光秃秃一句设问（实测查找细节有 7 道只有 17~27 字，紧接着就跳到 76 字）。
# 这些残题不是「这个题型的真实体量」，是数据缺陷。57 道样本里混 7 道残题，
# 10% 分位就落在残题堆里（实测 25 字），_style_ok 再乘 0.4 → 10 字的假片段阅读照过。
# 用「中位数的几分之一」而不是写死字数，是为了让每个题型自适应，不必逐个调参。
SHORT_FRAC = 4


def figs_of(db, qids):
    """哪些真题带图（从 docx 里提出来的，见 ingest_figs.py）。一次查完，别逐题查。

    ⚠️ 返回的是**图片文件名列表**，前端走 /api/real/fig/<name> 取 ——
    和 figgen 程序化出的图形题**不是一回事**（那边是内联 SVG 的 {seq, opts} 结构体）。
    渲染方要按形状分，别只判真假。

    realq（真题模块）和 drill（专项练的真题题源）都要用，所以放这儿共用：
    哪天配图的存储方式变了（比如加 kind 过滤），改一处就够，不会出现
    「真题模块改了、专项练还在发旧图」这种静默不一致。
    """
    if not qids:
        return {}
    out = {}
    try:
        for f in db.execute(
                "SELECT qid, sha, ext FROM real_figs WHERE qid IN (%s) ORDER BY qid, ord"
                % ",".join("?" * len(qids)), list(qids)):
            out.setdefault(f["qid"], []).append(f["sha"] + f["ext"])
    except sqlite3.OperationalError as e:
        # 只放过「表还没建」这一种（没跑过提图脚本的库）。裸 except 会把 JSON 损坏、
        # 磁盘错误、SQL 写错一起吞掉，表现是「图突然全没了」而日志里一个字都没有。
        if "no such table" not in str(e):
            raise
    return out
