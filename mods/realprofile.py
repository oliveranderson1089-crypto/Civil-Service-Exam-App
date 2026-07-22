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
  wrongs 干扰项手法频次 —— 真题的难度不在题干，在**错项是怎么造的**。
         实测概括主旨的干扰项两成是「无中生有」、一成是「非重点」，
         削弱/加强论证一成是「无关项」；而定义判断、法律常识全在 1% 上下 = 没有信号，
         那种就不给（硬给等于让模型去凑一个真题里不存在的套路）
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

# 画像只随真题库变，而真题库是离线重导的 —— 每小时重算一次足够，
# 免得每次补库都把几百行题干拉出来算一遍
_TTL = 3600
_CACHE = {}


def _pct(a, p):
    return a[min(len(a) - 1, int(len(a) * p))]


# 惯用问法要够集中才给：前几名加起来占不到这个比例，说明这个题型的设问五花八门，
# 硬给几个「高频句式」等于让模型照抄某一种问法
_ASK_MIN = 0.25
# 多空题占不到这个比例，就判定这个题型根本不是选词填空（中文选项本来没空格，
# 整句选项里夹个多余空格也会被数成「两空」）
_BLANK_MIN = 0.4


def _ask_forms(stems, top=3):
    """高频设问句：取题干最后一个分句的末尾。

    只在**够集中**时才返回 —— 常识判断那种设问五花八门的题型，硬给几个「高频句式」
    等于让模型照抄某一种问法，反而更不像真题。
    """
    # 按**问法开头**归组，不按整串精确计数。削弱论证的问法只在末尾名词上变
    #（「…最能削弱上述结论 / 上述论证 / 上述观点」「…最能质疑上述结论」），
    # 精确计数会把它打散成 9+8+6+5 四小堆，集中度算下来只有 12%，直接被判「太分散」
    # 而拿不到提示 —— 可它明明有惯用问法。取前 12 字当组键就并到一起了。
    # 组内仍然报**完整的那句**当范例：给模型看半截问法它照抄半截，反而更糟。
    groups = collections.defaultdict(collections.Counter)
    for s in stems:
        parts = [x for x in re.split(r"[。？?！!；;]", re.sub(r"\s+", "", s)) if x.strip()]
        if not parts:
            continue
        tail = parts[-1][-24:]
        # 「（）」「____」这类占位符会排到最前面，当成「惯用问法」写进提示词就是喂噪声。
        # 要求里面真有汉字，且不是短到没信息量的残段。
        if len(tail) < 6 or not re.search(r"[一-龥]{4}", tail):
            continue
        groups[tail[:12]][tail] += 1
    cnt = collections.Counter({k: sum(v.values()) for k, v in groups.items()})
    tot = sum(cnt.values())
    if not tot:
        return []
    most = [(groups[k].most_common(1)[0][0], n) for k, n in cnt.most_common(top)]
    # ⚠️ 分母必须是**真正计入统计的行数**，不是全部样本。用 len(stems) 的话，
    #    某题型若有一半题干以占位符结尾（真题库里这类确实存在），分子最多只能到 50%，
    #    再要求 ≥25% 等于把有效阈值悄悄抬到 50%，本来有惯用问法的题型会拿不到提示。
    if sum(n for _f, n in most) < tot * _ASK_MIN:
        return []                        # 太分散，这个题型没有惯用问法
    return [f for f, n in most if n >= 2]


# 干扰项手法的词表 —— **是数出来的，不是拍脑袋列的**。
# 真题解析里的错因是 AI 写的自由文字（「独特优势是引出任务的铺垫」），
# 它描述的是这一项具体错在哪，而不是点名手法，所以只能靠这些关键词去认。
#
# ⚠️ 特征词必须**用完整搭配，别用单字高频词**。原先「程度不符」写的是裸的「程度」，
#    把「题干未提及受欢迎程度，无关」「未说影响普及程度」这类句子也算了进去
#    （那其实是无中生有 / 无关项）；「因果倒置」写了裸的「因果关系」，
#    而论证题的解析里天天在谈因果关系——「未质疑…的因果关系，反而可能支持」
#    说的是这一项没切断因果链，恰恰不是因果倒置。这两处都实测抽样确认过误报。
#    这类误报眼下被 _WAY_MIN 的阈值挡住了（两桶都只有 1~2%），但那是侥幸不是正确。
#
# TODO(下次重生成解析时一并做)：更根本的做法是让 gen_real_explain.py 在写 wrong 时
# 直接输出一个 way 字段（从固定枚举里选）——它判自己刚写的错因，比事后正则猜准得多。
# P1 那次全量重生成 6897 条时顺手加是免费的，现在再要就得再跑一遍全量，所以先记下。
_WRONG_WAYS = {k: re.compile(v) for k, v in {           # 预编译：一次画像要跑上万次匹配
    "无中生有": r"无中生有|文中未提|未提及|没有提到|原文未",
    "偷换概念": r"偷换概念|概念错误|混淆概念|张冠李戴",
    "偷换时间": r"偷换时间|时间错误|偷换时态",
    "偷换主体": r"偷换主体|主体错误|主体不符|主体不对",
    "范围偏差": r"以偏概全|范围扩大|范围缩小|扩大范围|部分.{0,4}整体",
    "表述绝对": r"绝对化|表述绝对|过于绝对|说法绝对",
    "因果倒置": r"因果倒置|颠倒因果|强加因果|因果关系倒置",
    "非重点": r"非重点|不是重点|非主要|只是.{0,6}(铺垫|细节|之一)|片面",
    "无关项": r"与.{0,6}无关|不相关|无关项",
    "程度不符": r"程度过重|程度过轻|程度不符|程度不当|夸大|弱化",
}.items()}
# 一种手法占比不到这个数就不报：低于此就是噪声（定义判断/法律常识各手法都在 1% 上下）
_WAY_MIN = 5
# **认得出手法的错因**占比不到这个数，说明这个题型的错项没有可归纳的套路，整个不给
_WAY_COVER_MIN = 10


def _wrong_ways(wrongs):
    """干扰项手法频次：这个题型的错项都是怎么造的。

    分母是**错项条数**（一道题三个错项各算一条），不是题数 —— 说的是
    「这个题型的干扰项里有多少比例用了某种手法」，用题数当分母会把比例算大三倍。

    ⚠️ 一条错因**可以同时命中多种手法**（「无中生有，且表述绝对」），所以每个数字是
    **命中率**、不是互斥占比，加起来可以超过 100%。因此「够不够格给提示」不能拿
    百分比之和去判（那是个可以靠模式重叠刷上去的数），要看**至少命中一种的错因占比**。
    """
    cnt = collections.Counter()
    n = matched = 0
    for w in wrongs:
        try:
            d = json.loads(w or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(d, dict):
            continue
        for v in d.values():
            n += 1
            hit = False
            for name, pat in _WRONG_WAYS.items():
                if pat.search(str(v)):
                    cnt[name] += 1
                    hit = True
            matched += hit
    if not n or matched / n * 100 < _WAY_COVER_MIN:
        return {}                        # 这个题型的错项没有可归纳的套路
    # **先按占比过滤、再取前四**：不依赖「所有桶共用同一个分母」这个隐含前提
    ok = sorted(((k, v) for k, v in cnt.items() if v / n * 100 >= _WAY_MIN),
                key=lambda kv: -kv[1])[:4]
    return {k: round(v / n * 100) for k, v in ok}


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
    if sum(v for k, v in cnt.items() if k >= 2) / tot < _BLANK_MIN:
        return {}
    return {k: round(v / tot * 100) for k, v in sorted(cnt.items())}


def build(db, board, qtype):
    """算一次画像。样本不足返回 None —— 调用方按「不卡」处理。

    ⚠️ 这里**故意**把整列 stem/material/options 拉进内存，撤销了之前「长度交给 SQLite 算」
    那版优化（drill.py 的 _REAL_LEN 现在只剩 _real_examples 一个用户）。原因是
    ask / blanks / wrongs 这三项必须看原文（题干、选项、逐项错因），SQL 算不出来；
    长度顺带一起算，不额外多取一次。代价实测：定义判断 628 行约 285 KB
    （其中 wrong 占 64 KB）、词语辨析 509 行约 163 KB。由 _TTL 缓存兜住 ——
    每个题型每小时最多算一次。**改这里的 SELECT 时记得回来更新这两个数。**

    DB 出错时**抛出去**，不返回 None：调用方 get() 要能分清「样本不够」（可以缓存）
    和「库暂时读不到」（绝不能缓存，否则一锁就锁掉一小时的护栏）。
    """
    rows = db.execute(
        "SELECT rq.stem, COALESCE(NULLIF(rq.material,'None'),'') mat, rq.options, re.wrong "
        "FROM real_questions rq LEFT JOIN real_explains re ON re.qid=rq.id "
        "WHERE %s AND %s=? AND rq.module=?"
        % (realref.servable("rq", "re"), realref.qtype_expr("rq", "re")),
        (qtype, realref.board_module(board))).fetchall()
    if len(rows) < realref.STYLE_MIN:   # 样本太少，分位和频次都不可信，宁可不给约束
        return None

    # 长度按**材料+题干**算：片段阅读的文段存在 material 列，只量 stem 会把中位数
    # 压到十几个字（那正是护栏失效的根因）。出题时要求把文段写进题干，两边口径要一致。
    lens = sorted(len(r["mat"]) + len(r["stem"] or "") for r in rows)
    # 剔残题：有一批题入库时材料没跟过来，只剩一句设问。按中位数的几分之一剔，
    # 每个题型自适应，不用逐个调参数。剔完不够样本就不剔。
    floor = lens[len(lens) // 2] / realref.SHORT_FRAC
    kept = [x for x in lens if x >= floor]
    if len(kept) >= realref.STYLE_MIN:
        lens = kept

    opts_list = []
    for r in rows:
        try:
            got = json.loads(r["options"])
        except (ValueError, TypeError):
            continue                     # 个别行 options 存坏了，跳过就是，别让整张画像算不出来
        # 解析成功不等于形状对：库里存过 "[1,2,3,4]" 这种，后面 len(o) 会抛 TypeError，
        # 一路冒到 _bank_warm 的宽 except 里，日志只剩一句「题库补充失败」——
        # 表现是这个题型从此再也补不进题，而完全看不出是画像挂了。
        if isinstance(got, list) and all(isinstance(o, str) for o in got):
            opts_list.append(got)
    olens = sorted(len(o) for opts in opts_list for o in opts)

    return {
        "n": len(rows),
        "med": lens[len(lens) // 2],
        "stem": (_pct(lens, .1), _pct(lens, .9)),
        "opt": (_pct(olens, .1), _pct(olens, .9)) if olens else (4, 30),
        "ask": _ask_forms([r["stem"] or "" for r in rows]),
        "blanks": _blank_dist(opts_list),
        "wrongs": _wrong_ways([r["wrong"] for r in rows]),
    }


def get(db, board, qtype):
    """带缓存的画像。画像只随真题库变（离线重导），每小时重算一次足够。

    ⚠️ **库读不到时绝不能把 None 缓存下来。** _style_ok 遇到 None 是直接放行的
    （`if not style: return True`），所以一次 "database is locked" 如果被缓存，
    这个题型接下来一小时**完全没有篇幅护栏**，任意长度的题都会入库 ——
    正是这套画像要堵的洞。真题库还没导入（表不存在）也走这条路：不缓存，下次再试。
    """
    key = (board, qtype)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    try:
        prof = build(db, board, qtype)
    except sqlite3.Error:
        return None                      # 不写缓存
    _CACHE[key] = (time.time(), prof)     # 样本不够算出的 None 可以缓存，那是稳定结论
    return prof


def clear():
    """重导真题后调一下，或测试里用。"""
    _CACHE.clear()


def prompt_lines(prof):
    """把画像翻译成**写进提示词的硬指标**。给区间模型就往下限以下写，得给具体数。"""
    if not prof:
        return ""
    # 不合格线取「中位数×0.8」和「护栏真实下限（p10）」里更大的那个。
    # 只用前者的话，右偏分布下会算出比 p10 还低的数（如 p10=100、med=110 → 88），
    # 于是模型按 88 字写、再被 100 的护栏成批拦掉，产出崩掉而日志只显示「体量不像真题」。
    lo = max(int(prof["med"] * 0.8), prof["stem"][0])
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
    if prof["wrongs"]:
        # 真题的难度不在题干，在**错项是怎么造的**。不说清楚的话，模型造的错项
        # 往往「一眼就能排除」——那种题练了不解决考场上的问题。
        out.append("干扰项**按真题的套路造**：这个题型的错项里，%s。"
                   "别造一眼就能排除的选项。"
                   % "、".join("%d%% 是「%s」" % (v, k) for k, v in prof["wrongs"].items()))
    return "\n".join(out)


def q_hint(prof):
    """贴在提示词 q 字段那一行的短提示。

    完整的【篇幅按真题来】那段在后面，离 q 的字段说明隔了十几行；模型写 q 的时候
    未必还记着那个数 —— 实测削弱论证要求 144 字，它写 78~86 字（下限 96）。
    所以在字段旁边再钉一次，只说最关键的那个数字，不重复整段。
    """
    return "" if not prof else "（**写足 %d 字左右**）" % prof["med"]
