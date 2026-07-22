"""每个题型的**真题画像**：这类题在真题里到底长什么样。

出题模型不是不听话，是**没人给它具体数字**。原先提示词给的是区间（「题干 76~226 字」），
模型一律往下限以下写 —— 实测语境分析真题中位数 118 字，AI 出 54~63 字；
而护栏 `_style_ok` 的下限是 `p10 × 0.4` = 30 字，一道都拦不住。
改成「必须写到 118 字上下，少于 94 字不合格」+ 明确要求设问句收尾，
一次调用出的 4 道题全部落进真题区间（命中率 0% → 100%）。

所以画像存的是**能直接写进提示词的具体指标**，不是统计学摆设：

  med    题干中位数 —— 提示词给这个数，不给区间
  ask    高频设问句 —— 实测语境分析 60% 用「填入画横线部分最恰当的一项是」，
         判断意图 60% 用「这段文字意在说明/强调」。AI 出的题经常整句漏掉，一眼就不像真题
  blanks 选词填空的空数分布 —— 语境分析 1空55%/2空34%，词语辨析 2空62%/3空30%。
         这组数原先硬编码在 _AI_SPEC 的文案里，现在从真题数出来

统计口径（SERVABLE、题型、板块→模块）一律走 mods/realref.py，别在这儿另立一套。
"""
import collections
import json
import re
import sqlite3
import time

from mods import realref

# 样本少于这个数就不出画像：分位数和频次都不可信，宁可不给约束也别给错的
MIN_N = realref.STYLE_MIN

# 画像只随真题库变，而真题库是离线重导的 —— 每小时重算一次足够，
# 免得每次补库都把几百行题干拉出来算一遍
_TTL = 3600
_CACHE = {}


def _pct(a, p):
    return a[min(len(a) - 1, int(len(a) * p))]


def _ask_forms(stems, top=3):
    """高频设问句：取题干最后一个分句的末尾。

    只在**够集中**时才返回 —— 常识判断那种设问五花八门的题型，硬给几个「高频句式」
    等于让模型照抄某一种问法，反而更不像真题。
    """
    cnt = collections.Counter()
    for s in stems:
        parts = [x for x in re.split(r"[。？?！!；;]", re.sub(r"\s+", "", s)) if x.strip()]
        if not parts:
            continue
        tail = parts[-1][-24:]
        # 「（）」「____」这类占位符会排到最前面，当成「惯用问法」写进提示词就是喂噪声。
        # 要求里面真有汉字，且不是短到没信息量的残段。
        if len(tail) < 6 or not re.search(r"[一-龥]{4}", tail):
            continue
        cnt[tail] += 1
    if not cnt:
        return []
    most = cnt.most_common(top)
    if sum(n for _f, n in most) < len(stems) * 0.25:
        return []                        # 太分散，这个题型没有惯用问法
    return [f for f, n in most if n >= 2]


def _blank_dist(opts_list):
    """选词填空的空数分布 —— 按**选项里的词数**数，别数题干。

    题干里的空在库里就是个空格（真题原文「经济循环的 ，就像」），数不准；
    而选项形如「与众不同 言简意赅」，空格分隔的词数就是空数，可靠得多。
    """
    cnt = collections.Counter()
    for opts in opts_list:
        if not opts:
            continue
        # 取**四个选项里最少的那个**词数，不是最多的。真的两空题四个选项都是两个词
        # （「与众不同 言简意赅」「独树一帜 字斟句酌」…），min 和 max 一样是 2；
        # 而整句选项里只要有一个夹了多余空格，max 就变成 2、整道题被标成「两空」。
        n = min(len(str(o).split()) for o in opts)
        if n:
            cnt[min(n, 4)] += 1
    tot = sum(cnt.values())
    if not tot:
        return {}
    # ⚠️ 中文选项本来就没有空格，这个指标**只对选词填空有意义**。
    #    削弱论证那种整句选项里混进几个多余空格，也会被数成「2 空」——
    #    实测它算出 {1:85, 2:6, 3:2, 4:7}，看着像模像样，其实全是噪声，
    #    写进提示词就是让模型去凑根本不存在的空。
    #    所以要求**多空占到四成以上**才认：语境分析 45%、词语辨析 94% 都过得去，
    #    削弱论证只有 15%，直接判定「这题型不是选词填空」。
    if sum(v for k, v in cnt.items() if k >= 2) / tot < 0.4:
        return {}
    return {k: round(v / tot * 100) for k, v in sorted(cnt.items())}


def build(db, board, qtype):
    """算一次画像。样本不足返回 None —— 调用方按「不卡」处理。"""
    try:
        rows = db.execute(
            "SELECT rq.stem, COALESCE(NULLIF(rq.material,'None'),'') mat, rq.options "
            "FROM real_questions rq LEFT JOIN real_explains re ON re.qid=rq.id "
            "WHERE %s AND %s=? AND rq.module=?"
            % (realref.servable("rq", "re"), realref.qtype_expr("rq", "re")),
            (qtype, realref.board_module(board))).fetchall()
    except sqlite3.Error:
        return None                      # 真题库还没导入（新库）
    if len(rows) < MIN_N:
        return None

    # 长度按**材料+题干**算：片段阅读的文段存在 material 列，只量 stem 会把中位数
    # 压到十几个字（那正是护栏失效的根因）。出题时要求把文段写进题干，两边口径要一致。
    lens = sorted(len(r["mat"]) + len(r["stem"] or "") for r in rows)
    # 剔残题：有一批题入库时材料没跟过来，只剩一句设问。按中位数的几分之一剔，
    # 每个题型自适应，不用逐个调参数。剔完不够样本就不剔。
    floor = lens[len(lens) // 2] / realref.SHORT_FRAC
    kept = [x for x in lens if x >= floor]
    if len(kept) >= MIN_N:
        lens = kept

    opts_list = []
    for r in rows:
        try:
            opts_list.append(json.loads(r["options"]))
        except (ValueError, TypeError):
            pass                         # 个别行 options 存坏了，跳过就是，别让整张画像算不出来
    olens = sorted(len(o) for opts in opts_list for o in opts)

    return {
        "n": len(rows),
        "med": lens[len(lens) // 2],
        "stem": (_pct(lens, .1), _pct(lens, .9)),
        "opt": (_pct(olens, .1), _pct(olens, .9)) if olens else (4, 30),
        "ask": _ask_forms([r["stem"] or "" for r in rows]),
        "blanks": _blank_dist(opts_list),
    }


def get(db, board, qtype):
    """带缓存的画像。画像只随真题库变（离线重导），每小时重算一次足够。"""
    key = (board, qtype)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    prof = build(db, board, qtype)
    _CACHE[key] = (time.time(), prof)
    return prof


def clear():
    """重导真题后调一下，或测试里用。"""
    _CACHE.clear()


def prompt_lines(prof):
    """把画像翻译成**写进提示词的硬指标**。给区间模型就往下限以下写，得给具体数。"""
    if not prof:
        return ""
    lo = int(prof["med"] * 0.8)
    out = ["\n\n【篇幅按真题来 —— 这是硬指标，不是建议】",
           "题干**必须写到 %d 字上下**（同题型真题的中位数就是这个数），"
           "**少于 %d 字一律判不合格**。片段阅读要给完整文段，选词填空要把上下文的呼应关系写足。"
           "每个选项 %d~%d 字。" % (prof["med"], lo, prof["opt"][0], prof["opt"][1])]
    if prof["ask"]:
        out.append("题干**必须以设问句收尾**，真题这个题型惯用的问法是：%s"
                   "（照着这个措辞写，AI 出的题经常整句漏掉，一眼就不像真题）"
                   % "、".join("「%s」" % a for a in prof["ask"]))
    if prof["blanks"]:
        out.append("空数按真题的实际比例来：%s。"
                   % "、".join("%d 空占 %d%%" % (k, v) for k, v in prof["blanks"].items()))
    return "\n".join(out)
