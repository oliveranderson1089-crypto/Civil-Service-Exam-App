"""社区卷的**判分口径 —— 全站唯一一份**。

单独一个文件、不 import flask，是为了让三种调用方都能吃同一份：
接口（mods/shequ.py）、入库脚本、以及将来那些没人 import 的定时器脚本。
判分写两处的下场不是报错，是**算错分而毫无声响**——用户只会觉得
「我明明选对了怎么没给分」，查都没处查。

两条规则是从资中真题原卷上抄下来的，不是我们定的：
  · 多选题「多选、少选、错选均不得分」（2023 卷第二大题标题里写着）
  · 判断题对打 √、错打 ×（同上，第三大题标题）
"""

# 题型 → 卷面名。前端要显示哪个词也从这儿取，别在 JS 里再写一份。
#
# **short（简答论述题）不是资中的题型。** 两套资中原卷上只有单选/多选/判断/案例/公文
# 五种，简答论述是外省题库带进来的（见 ingest_sqsub.py）。留着它是因为那 49 道题
# 本身是好的知识点自测材料，但界面上必须和资中考的四十分主观题**分开摆、标明白**，
# 不能让人以为资中会考简答 —— 卷面上没有的题型，混进「主观题 40 分」就是在编考情。
PART_NAME = {"single": "单项选择题", "multi": "多项选择题", "judge": "判断题",
             "case": "案例分析题", "gongwen": "公文写作", "short": "简答论述题"}
OBJ_PARTS = ("single", "multi", "judge")          # 客观题：能当场判分的
SUB_PARTS = ("case", "gongwen", "short")          # 主观题：交卷后给参考答案对照
# 资中卷面**真有**的题型，按卷面顺序。整卷渲染、分部统计都按它排 ——
# 各处各写一份 ("single","multi",…) 的下场是加了题型后有的地方显示、有的地方不显示。
PAPER_PARTS = ("single", "multi", "judge", "case", "gongwen")


def sql_in(parts):
    """拼 `IN ('a','b')`。题型清单只有这一份，SQL 里别再手写字面量。"""
    return "(%s)" % ",".join("'%s'" % p for p in parts)

# 判分规则的**人话版本**，由接口下发给前端显示。写在这儿是为了让
# 「规则怎么说」和「代码怎么判」同源——两边各写一份迟早说的不是一回事。
RULE_TEXT = {
    "single": "四选一，选对得分。",
    "multi": "多选、少选、错选均不得分 —— 与资中真题判分口径一致。",
    "judge": "判对得分，判错不得分，不倒扣。",
}


def norm_chosen(part, chosen):
    """把用户交上来的答案折成标准形。折不出来返回空串 = 没作答。"""
    s = (chosen or "").strip().upper().replace(" ", "")
    if part == "judge":
        if s in ("T", "对", "√", "TRUE", "正确"):
            return "T"
        if s in ("F", "错", "×", "X", "FALSE", "错误"):
            return "F"
        return ""
    letters = "".join(sorted(set(c for c in s if c in "ABCD")))
    if part == "single" and len(letters) > 1:
        # 单选题交上来多个字母：当没作答，**不要挑第一个**当他的答案。
        # 挑第一个等于替用户做决定，而且他永远不知道自己被改过。
        return ""
    return letters


def is_correct(part, chosen, answer):
    """这道题对不对。多选题**全对才算对**，少一个都不给分。"""
    c = norm_chosen(part, chosen)
    a = norm_chosen(part, answer)
    if not c or not a:
        return False
    return c == a


def score_of(part, chosen, answer, full):
    """这道题得几分。客观题非零即满，没有部分分 —— 练的口径要和考的口径一致。"""
    if part not in OBJ_PARTS:
        return 0.0                    # 主观题不在这儿判，交给采分点批改
    return float(full or 0) if is_correct(part, chosen, answer) else 0.0


def miss_and_extra(part, chosen, answer):
    """多选题专用：漏选了哪些、多选了哪些。给「漏选」那个揭晓态用。

    现有的对/错两态说不清「少选」，而少选恰恰是这类题最常见的丢分方式。
    """
    if part != "multi":
        return "", ""
    c = set(norm_chosen(part, chosen))
    a = set(norm_chosen(part, answer))
    return "".join(sorted(a - c)), "".join(sorted(c - a))


# ---------------------------------------------------------------- 能不能发给人做
# 「答案靠得住」的唯一判据。真题库那边同样的口径住在 mods/realref.py，
# 这儿是社区卷的那一份：**只有过了校对闸门的题才发**。
# verify 为空 = 还没校对过，一律当存疑看待，不是「默认可用」。
SERVABLE_SQL = "q.verify='ok'"


def servable(row):
    """给 Python 侧用的同一判据（SQL 那份见 SERVABLE_SQL，两者必须同义）。"""
    return (row["verify"] if hasattr(row, "keys") else row.get("verify")) == "ok"
