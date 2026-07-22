"""专项练：资料分析 / 判断推理 / 数量关系。

难度三档是**真改题**：程序化那三块由 figgen 按 level 造，AI 那三块写进提示词。
AI 出的题必须过第二个模型独立核验才发给人做——实测单模型出题一致率只有 89%，
每 9 道就有 1 道值得怀疑，而且真抓到过事实错误。

_dtest_to_wrongq（做错的题进错题本）也放这儿：专项练和每日巩固测试都用它，
留在 app.py 的话这个模块就得回头 import app，绕成环。
"""
import hashlib
import json
import random
import re
import secrets
import sqlite3
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from flask import Blueprint, jsonify, request

from core import DB, get_db, log, uid
from figgen import _gen_figure_q, _gen_math_q, _gen_ziliao
from mods import realprofile, realref
from mods.ai import _ai_call_or_error, _vision_conf

bp = Blueprint("drill", __name__)


# 这三块和常识不一样：**题型固定、有套路、拼速度**。所以按题型分开刷、每题计时、
# 做完给这一类的秒杀技巧，并统计「哪个题型最弱、平均要多久」——弱的排前面。
# 题都是**程序化生成**的（figgen.py），答案由构造保证；AI 出这类题会算错，不用它。
DRILL_LIMIT = {"资料分析": 60, "判断推理": 45, "数量关系": 70,
               "常识判断": 30, "政治理论": 30, "言语理解与表达": 50}   # 每题限时（秒），按真题节奏

# ---- 难度：三档，**真正改变题目**（程序化的三块由 figgen 按 level 造，AI 的三块写进提示词）----
# 「难度系数」在公考里就是**得分率**（0~1，越高越简单）。这里给每个板块一个真实基准，
# 让人心里有数：数量关系考场真实难度只有 0.40，做对 4 成不是你菜，是这题本来就难。
DRILL_LEVELS = ["easy", "mid", "real"]
DRILL_LV_NAME = {"easy": "入门", "mid": "进阶", "real": "考场真实"}
# 难度的说明要**分板块写** —— 「数字整、要动笔」这话套到常识判断上驴唇不对马嘴
DRILL_LV_DESC = {
    "计算": {"easy": "一步套公式、数字整、干扰项一眼排除",
             "mid": "常规两步、需要动笔算",
             "real": "多步/要用技巧、数字不整得估算、干扰项贴着常见错法"},
    "图形": {"easy": "规律直观（数元素、数边），干扰项差异明显",
             "mid": "五类规律都可能，需要比对两三个属性",
             "real": "偏隐蔽规律（线条数、封闭区域），且有镜像干扰项"},
    "知识": {"easy": "单个知识点正面直问，四选项差异明显",
             "mid": "需要辨析或两步推理，有一个较像的干扰项",
             "real": "真题水平：干扰项贴着常见错法（易混概念、偷换时间/主体/范围），要真懂才选得对"},
}
_LV_KIND = {"资料分析": "计算", "数量关系": "计算", "判断推理": "图形",
            "常识判断": "知识", "政治理论": "知识", "言语理解与表达": "知识"}


def drill_levels(board):
    d = DRILL_LV_DESC[_LV_KIND.get(board, "知识")]
    return [{"k": k, "name": DRILL_LV_NAME[k], "desc": d[k], "coef": drill_coef(board, k)}
            for k in DRILL_LEVELS]
DRILL_BASE = {            # 该板块「考场真实难度」的得分率基准（接近真题平均正确率）
    "资料分析": 0.65, "判断推理": 0.60, "数量关系": 0.40,
    "常识判断": 0.55, "政治理论": 0.60, "言语理解与表达": 0.62,
}
_LV_BONUS = {"easy": 0.25, "mid": 0.10, "real": 0.0}


def drill_coef(board, level):
    """难度系数 = 预期得分率。入门在基准上加 25 个点，进阶加 10 个点，真实就是基准。"""
    return round(min(0.92, DRILL_BASE.get(board, 0.6) + _LV_BONUS.get(level, 0.1)), 2)


# 题型**按讲义目录的顺序**排（循序渐进，别一上来就啃最难的）。
# 每项 = (题型, 一句话说明, 引擎)：prog = 程序化生成（答案由构造保证）；ai = AI 出题 + 题库缓存。
# 判断推理是**混合**的：图形推理能构造，定义/类比/逻辑判断只能让 AI 出。
DRILL_TYPES = {
    # ---- 资料分析（讲义第二章 常考概念）----
    "资料分析": [
        ("基期量", "已知现期和增长率，倒推去年", "prog"),
        ("现期量", "直接读数，别自己加戏", "prog"),
        ("增长率", "(今年−去年)÷**去年**", "prog"),
        ("增长量", "今年−去年，直接减", "prog"),
        ("间隔增长", "隔一年的增长率：r₁+r₂+r₁r₂", "prog"),
        ("年均增长", "÷ 年份差（2021→2024 是 3 不是 4）", "prog"),
        ("混合增长", "整体增速必在两部分之间", "prog"),
        ("倍数与翻番", "「是几倍」用除，「多几倍」再减 1", "prog"),
        ("比重", "部分 ÷ 整体", "prog"),
        ("比重变化", "单位是**百分点**，不是百分比", "prog"),
        ("平均数", "人均 = 总量 ÷ 人口，同一年", "prog"),
        ("比较大小", "比重上升 ⇔ 部分增速快于整体", "prog"),
    ],
    # ---- 言语理解与表达（讲义四篇：选词填空 / 片段阅读 / 语句表达 / 文章阅读）----
    "言语理解与表达": [
        ("语境分析", "选词填空：靠上下文的呼应、提示定词", "ai"),
        ("词语辨析", "选词填空：近义词的词义/搭配/色彩差别", "ai"),
        ("查找细节", "片段阅读：回原文核对，别凭印象", "ai"),
        ("概括主旨", "片段阅读：找中心句，转折词后面十有八九是", "ai"),
        ("判断意图", "片段阅读：作者想让你干什么/信什么", "ai"),
        ("推断隐含信息", "片段阅读：由已知推未知，不能过度引申", "ai"),
        ("理解词句", "片段阅读：指定词句在文中什么意思", "ai"),
        ("句子填空", "语句表达：补上最连贯的一句", "ai"),
        ("句子排序", "语句表达：先排除不能当首句的", "ai"),
        ("文章阅读", "一篇长文配多问", "ai"),
    ],
    # ---- 判断推理（讲义四章：图形推理 / 定义判断 / 类比推理 / 逻辑判断）----
    "判断推理": [
        ("位置变化", "图形：旋转、平移", "prog"),
        ("样式规律", "图形：加减同异（去同存异）", "prog"),
        ("属性规律", "图形：对称性、开闭性", "prog"),
        ("数量规律", "图形：点 / 线 / 面 / 素", "prog"),
        ("定义判断", "对着定义逐字抠要件", "ai"),
        ("类比推理", "逻辑关系 / 言语关系 / 常识关系", "ai"),
        ("翻译推理", "「若A则B」的推理规则", "ai"),
        ("分析推理", "排除法 + 列表法", "ai"),
        ("削弱论证", "找最能削弱结论的那一项", "ai"),
        ("加强论证", "找最能支持结论的那一项", "ai"),
        ("解释说明", "解释看似矛盾的现象", "ai"),
    ],
    # ---- 数量关系（讲义第二章 高频题型 → 第三章 数字推理）----
    "数量关系": [
        ("工程", "设总量为最小公倍数", "prog"),
        ("行程", "相遇看速度和，追及看速度差", "prog"),
        ("利润", "成本设成 100", "prog"),
        ("容斥", "先算「至少参加一项」", "prog"),
        ("最值", "要谁最大就让别人尽量小", "prog"),
        ("几何", "边长×k → 面积×k²", "prog"),
        ("排列组合", "换个顺序算不算新方案？", "prog"),
        ("概率", "放回还是不放回？", "prog"),
        ("浓度", "十字交叉法", "prog"),
        ("等差数列", "(首+末)×项数÷2", "prog"),
        ("周期日期", "只看余数", "prog"),
        ("植树方阵", "两端都种 = 段数+1", "prog"),
        ("年龄", "年龄差永远不变", "prog"),
        ("数字推理", "先看差、再看商、看平方、看递推", "prog"),
    ],
    # ---- 常识判断（七大板块，全靠 AI 出题）----
    "常识判断": [(b, "", "ai") for b in ("人文常识", "科技常识", "法律常识", "地理常识",
                                         "经济常识", "管理常识", "公文常识")],
    # ---- 政治理论 ----
    "政治理论": [(b, "", "ai") for b in ("马克思主义基本原理", "毛泽东思想",
                                         "中国特色社会主义理论体系", "习近平新时代中国特色社会主义思想")],
}
# 某个题型用哪个引擎（题型名 → prog/ai）；同名题型不会跨板块冲突
DRILL_ENGINE = {(b, t[0]): t[2] for b, ts in DRILL_TYPES.items() for t in ts}
# 讲义里的「解题方法」章 —— 是方法不是题型，单独摆出来（做题时的秒杀技巧就来自这里）
DRILL_METHODS = {
    "资料分析": ["尾数法：只算末几位，选项末位不同就直接出答案",
                 "截位直除：分子分母各取前 2~3 位，够用了",
                 "百化分：1/7≈14.3%、1/8=12.5%、1/9≈11.1% —— 背下来省一半时间",
                 "错位加减：a×1.1 = a + a的十分之一"],
    "数量关系": ["代入排除：选项就是答案，从最好算的那个开始代",
                 "倍数特性：结果必须是 3 的倍数 → 不是的直接划掉",
                 "特值法：题里没给具体数 → 自己设一个（总量设 100 或最小公倍数）",
                 "方程法：实在没招才设未知数，能设一个别设两个"],
}
# 有些题型讲义里有、但**没法可靠地程序化构造**，硬做出来答案站不住 —— 老实说明，不假装有
DRILL_MISSING = {
    "判断推理": "立体图形（折纸盒 / 三视图）：二维 SVG 构造不出可靠的立体题，答案站不住脚，所以不出。",
}
AI_BOARDS = ("常识判断", "政治理论", "言语理解与表达")     # 这三块整块都靠 AI 出题

# 每个题型的秒杀技巧（做完立刻给 —— 不是解析，是「下次怎么更快」）。
# 程序化出的题会自带 tip；这里兜底 + 给 AI 题型用。
DRILL_TIP = {
    # 资料分析
    "基期量": "基期 = 现期 ÷ (1+r)。**最经典的错法是「现期 ×(1−r)」** —— 增长率的分母是基期，不是现期。",
    "现期量": "**直接读数**。这类题不用算，别自己给自己加戏。",
    "增长率": "(今年 − 去年) ÷ **去年**。除的是去年，不是今年 —— 最经典的坑。",
    "增长量": "今年 − 去年，直接减。别去套增长率公式绕远路。",
    "间隔增长": "隔一年的增长率 = **r₁ + r₂ + r₁×r₂**。不能把两年的增长率直接相加。",
    "年均增长": "(末年 − 首年) ÷ **年份差**。2021→2024 是 **3** 年，不是 4。",
    "混合增长": "**整体增速必定介于两部分之间**，且更靠近权重大的那一边。绝不等于简单平均数。",
    "倍数与翻番": "「是几倍」用除，「多几倍」再减 1。「翻一番」=×2，「翻两番」=**×4**（不是 ×3）。",
    "比重": "部分 ÷ 整体。**先看清年份和单位** —— 这类题错的多半不是算错，是看错行。",
    "比重变化": "两个比重直接相减，单位是**百分点**，不是百分比。",
    "平均数": "人均 = 总量 ÷ 人口，**分子分母必须同一年**。错位取数是最常见的失分点。",
    "比较大小": "**比重上升 ⇔ 部分的增速快于整体**。看出这一条，很多题不用算。",
    # 判断推理 · 图形（四大类）
    "位置变化": "先看**旋转还是平移**；旋转题必看是不是**镜像** —— 镜像靠旋转永远得不到。",
    "样式规律": "**去同存异 / 求同存异**：把两个图叠起来，相同的抵消还是保留？先定这个。",
    "属性规律": "对称性（轴对称/中心对称）、开闭性、曲直性 —— 三个属性挨个过一遍。",
    "数量规律": "数**点、线、面、素**：交点数、线条数、封闭区域数、元素种类。数之前先想清楚数的是什么。",
    # 判断推理 · 文字
    "定义判断": "**对着定义逐字抠要件**：主体、行为、对象、目的，缺一个就不符合。别凭常识判断。",
    "类比推理": "先想**这两个词是什么关系**（种属/组成/功能/对应），再去选项里找**同一种**关系。",
    "翻译推理": "「A→B」的两条铁律：**肯前必肯后、否后必否前**。肯后否前都是耍流氓。",
    "分析推理": "有确定信息就**从确定的入手**；没有就**代入排除**（选项就是答案）。列表法最稳。",
    "削弱论证": "先找出**论点和论据**，再看哪一项**切断了两者的联系**（拆桥）—— 那才是最强削弱。",
    "加强论证": "补上论点和论据之间缺的那一环（搭桥），比举例子有力得多。",
    "解释说明": "找一个**能让矛盾双方同时成立**的原因。只解释一半的都不选。",
    # 言语理解
    "语境分析": "先找**呼应/提示**：转折、并列、递进、解释 —— 空缺处的意思由上下文钉死。",
    "词语辨析": "近义词看三样：**词义轻重、搭配对象、感情色彩**。别只凭语感。",
    "查找细节": "**回原文核对**，一个字一个字对。「绝对化」「偷换概念」「无中生有」是三大错项。",
    "概括主旨": "找**转折词后面**那句（但是/然而/其实）—— 主旨十有八九在那儿。",
    "判断意图": "主旨是「说了什么」，意图是「**想让你怎么样**」。问意图就要往「呼吁/建议」上靠。",
    "推断隐含信息": "只能**由已知推未知**，不能过度引申。选项里带「必然」「一定」的先警惕。",
    "理解词句": "**回到原文那一句**，看它前后是怎么解释的。别拿词典义硬套。",
    "句子填空": "看空缺**在段首、段中还是段尾**：段首领起、段中承接、段尾总结。",
    "句子排序": "先找**不能当首句的**（含指代词、关联词后半句）—— 排除法比正着排快得多。",
    "文章阅读": "**先看题目再读文**，带着问题找答案，别通读。",
    # 数量关系（程序化的题自带 tip，这里兜底）
    "工程": "**设总量为最小公倍数**，效率立刻变整数。",
    "行程": "相遇看**速度和**，追及看**速度差**。",
    "利润": "**成本设成 100**，全是百分比乘除。",
    "容斥": "先算**至少参加一项**（总数 − 都不参加），再套 A+B−A∪B。",
    "最值": "**要谁最大，就让别人尽量小**。",
    "几何": "**边长 ×k → 面积 ×k²，体积 ×k³**。",
    "排列组合": "先问：**换个顺序算不算新方案？** 算→排列 A，不算→组合 C。",
    "概率": "先问：**放回还是不放回？**",
    "浓度": "**十字交叉法**：两溶液质量比 = 浓度差的反比。",
    "等差数列": "求和 = **(首 + 末) × 项数 ÷ 2**。项数 = (末−首)÷公差 **+1**。",
    "周期日期": "**只看余数**，商是多少不用管。",
    "植树方阵": "两端都种 = **段数 + 1**；空心方阵最外层 = **每边 ×4 − 4**。",
    "年龄": "抓住**年龄差不变**这个不变量。",
    "数字推理": "四步：**先看差 → 再看商 → 看是不是平方/立方 → 看是不是前两项组合**。四步不出就跳过。",
}

_LV_PROMPT = {
    "easy": "**入门难度**：只考单个知识点，正面直问，四个选项差异明显，一眼能排除两个。",
    "mid": "**进阶难度**：需要辨析或两步推理，有一个较像的干扰项。",
    "real": "**考场真实难度**：按真题水平出——设置**贴着常见错法**的干扰项（易混概念、"
            "偷换时间/主体/范围），正确项不能一眼看出，要真懂才选得对。",
}


# ---- 双模型核验：AI 出的题，必须由**另一家模型**独立做一遍，答案一致才发给人做 ----
# 为什么非做不可：135 道抽检下来，单模型出题的答案一致率只有 **89%** —— 每 9 道就有 1 道存疑。
# 而且真抓到过硬伤（「生态文明八个坚持」里说「山水林田湖草沙」多了个「沙」，那是错的）。
# 出题：DeepSeek；核验：智谱 glm-4-plus。**绝不把原答案给核验模型看**，否则它会被锚定。
AUDIT_MODEL = "glm-4-plus"      # 智谱旗舰非推理版（glm-4.6 是推理模型，一道要 15~30 秒，太慢）


def _audit_q(q, options, board, qtype):
    """让核验模型独立作答 + 独立判断题目有没有毛病。返回 (答案, flaw, 说明) 或 None。"""
    c = _vision_conf()
    if not c.get("key") or not c.get("base"):
        return None
    prompt = (
        "【板块】%s · %s\n【题目】%s\n【选项】\n%s\n\n"
        "这道题**不告诉你答案**，请你自己独立做一遍，并判断题目本身有没有毛病。\n"
        "1. answer：A/B/C/D\n"
        "2. flaw：ok（没问题）/ fact（有事实错误）/ multi（不止一个选项说得通）/ "
        "none（一个正确答案都没有）/ vague（有歧义）\n"
        "3. note：一句话说明理由（或问题在哪）\n\n"
        '只输出 JSON：{"answer":"A","flaw":"ok","note":""}'
        % (board, qtype, q, "\n".join(options)))
    payload = {"model": AUDIT_MODEL, "temperature": 0.1, "max_tokens": 600,
               "messages": [{"role": "user", "content": prompt}],
               "response_format": {"type": "json_object"}}
    url = c["base"] + ("" if c["base"].endswith("/chat/completions") else "/chat/completions")
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + c["key"]})
        with urllib.request.urlopen(req, timeout=45) as r:
            d = json.loads(r.read().decode("utf-8"))
        txt = (d["choices"][0]["message"].get("content") or "").strip()
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return None
        j = json.loads(m.group())
        a = (j.get("answer") or "").strip().upper()[:1]
        return (a if a in "ABCD" else "", (j.get("flaw") or "ok").strip(),
                (j.get("note") or "").strip()[:160])
    except Exception:
        return None


def _bank_material(db, board, qtype, n=14):
    """从已有素材里取出题的原料 —— 题必须**考我们库里有的东西**，不然练了也对不上。
       片段阅读/逻辑判断这类不依赖词库，AI 自己命制。"""
    if board == "常识判断":
        rows = db.execute("SELECT title, content FROM changshi_items WHERE board=? "
                          "ORDER BY RANDOM() LIMIT ?", (qtype, n)).fetchall()
        return ["%s：%s" % (r["title"], (r["content"] or "")[:110]) for r in rows]
    if board == "政治理论":
        rows = db.execute("SELECT title, content FROM theory_items WHERE board=? "
                          "ORDER BY RANDOM() LIMIT ?", (qtype, n)).fetchall()
        return ["%s：%s" % (r["title"], (r["content"] or "")[:110]) for r in rows]
    if qtype in ("语境分析", "词语辨析"):     # 选词填空：正确答案要从我们积累的词里出
        rows = db.execute("SELECT title, content FROM changkao_items WHERE board IN ('成语','实词') "
                          "ORDER BY RANDOM() LIMIT ?", (n * 2,)).fetchall()
        return ["%s：%s" % (r["title"], (r["content"] or "")[:60]) for r in rows]
    return []


# 各 AI 题型的出题要点 —— 不写清楚，AI 出的题型会跑偏（比如把「判断意图」出成「概括主旨」）
_AI_SPEC = {
    # ⚠️ 下面这两条的空数是**数过真题才定的**，别凭印象改回「一个空」：
    #    词语辨析 379 道真题里，两空 64%、三空 29%，一空只占 6%（题干中位数 134 字）；
    #    语境分析 257 道里一空 56%、两空 35%。原先两条都写着「一个空」，
    #    于是 AI 出的全是 30 字题干配单个词的一空题 —— 和真题差着一个量级，
    #    练它不解决考场上的问题（考场上你面对的是两三个空互相牵制）。
    "语境分析": "选词填空。**一半是一个空、一半是两个空**（两空的话四个选项写成"
                "「词A 词B」用空格分开）。**空缺处的意思必须由上下文钉死**"
                "（转折/并列/递进/解释的呼应关系），四个选项都是近义词，只有一个全都符合语境。"
                "文段要写足 100 字上下，把呼应关系铺出来。",
    "词语辨析": "选词填空，**必须是两个空或三个空**（真题里九成以上都是，一空的几乎不考）。"
                "每个选项写成「词A 词B」或「词A 词B 词C」，用空格分开。"
                "靠**词义轻重 / 搭配对象 / 感情色彩**区分，而且**要让多个空互相牵制**："
                "单看某一个空可能有两个词都行，合起来只有一组全对 —— 这才是真题的考法。"
                "文段写足 130 字上下。",
    "查找细节": "片段阅读（150~250 字），问「符合/不符合原文的是」。错项要用**绝对化、偷换概念、"
                "无中生有**这三种典型手法造。",
    "概括主旨": "片段阅读（150~250 字），问「这段文字主要说明了什么」。文段里要有明确的中心句"
                "（常在转折词之后）。",
    "判断意图": "片段阅读（150~250 字），问「作者意在强调/说明什么」。注意**意图不是主旨** —— "
                "答案要往「呼吁 / 建议 / 提醒」上落，只复述内容的是干扰项。",
    "推断隐含信息": "片段阅读（150~250 字），问「可以推出的是」。正确项必须**由文段严格推出**，"
                    "干扰项要有「过度引申」「绝对化」的。",
    "理解词句": "片段阅读（150~250 字），问文中某个加引号的词/句是什么意思。答案要回到原文语境。",
    "句子填空": "给一段话，中间或结尾挖掉一句，选最连贯的。要考**承上启下**。",
    "句子排序": "给 5~6 个打乱的句子（用①②③…标号），选正确顺序。要有**明显的首句线索**"
                "（指代词、关联词后半句不能当首句）。",
    "文章阅读": "一篇 400~600 字的文章，配一个问题（主旨或细节）。",
    "定义判断": "先给一个**完整的定义**（含主体、行为、对象、目的），再给四个例子，"
                "问哪个**符合/不符合**该定义。要靠**逐字抠要件**才能判，不能靠常识。",
    "类比推理": "给一组词（如「医生：手术刀」），四个选项里选**关系最相似**的一组。"
                "关系要明确（种属 / 组成 / 功能 / 对应 / 因果）。",
    "翻译推理": "给若干「若…则…」的条件，问能推出什么。考**肯前必肯后、否后必否前**，"
                "干扰项要用**肯后、否前**这两种典型错误。",
    "分析推理": "给若干条件（如四个人的座位/职业），问确定的结论。要能靠**排除法/列表法**做出来。",
    "削弱论证": "先给论点和论据，问哪一项**最能削弱**。最强削弱应该是**切断论点与论据的联系**（拆桥），"
                "干扰项用「削弱力度弱」「无关项」。",
    "加强论证": "先给论点和论据，问哪一项**最能支持**。最强加强应该是**补上论点与论据之间缺的一环**（搭桥）。",
    "解释说明": "给一个看似矛盾的现象，问哪一项**最能解释**。正确项要能让矛盾双方**同时成立**。",
}


def _salvage_items(rep):
    """JSON 被 max_tokens 截断时，把已经写完整的那几道抢救出来。

    分析推理是重灾区：模型会在 explain 里把所有情况枚举一遍，一道解析就几百字，
    整批 JSON 写不完就断在半路。原先 json.loads 一失败就整批丢弃 ——
    12 道里写好的 8 道也跟着没了，表现出来就是这个题型「一道都出不来」。
    """
    # 用栈记每一层花括号的起点：题目对象嵌在 {"items":[ … ]} 里面，
    # 只盯「深度回到 0」的话，外层那个 { 永远等不到它的 }（就是它被截断的），一道也捞不出来。
    out, stack, instr, esc = [], [], False, False
    for i, ch in enumerate(rep):
        if instr:                       # 字符串里的花括号不算层级
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            try:
                o = json.loads(rep[start:i + 1])
            except Exception:
                continue
            # 只收长得像题目的：外层的 {"items":…} 和解析里嵌的小对象都会走到这儿
            # 新格式是 q + right + wrong，老格式是 q + options —— 两种都要认，
            # 只认老的话，截断时新格式一道也捞不回来
            if isinstance(o, dict) and o.get("q") and (o.get("right") or o.get("options")):
                out.append(o)
    return out


def _split_rw(it):
    """把模型交的一道题拆成 (正确项, 三个干扰项, 为什么对, 三条为什么错, 能不能重排)。

    新格式是 right/wrong/why_right/why_wrong —— **字母一个都不出现**，
    这样正确项排第几位完全由我们说了算（见 _bank_fill 里那段）。
    仍然认老格式（options + answer + explain），因为：
      · 模型偶尔会退回去按老样子输出；
      · _salvage_items 从截断的 JSON 里捞出来的可能是任一种。
    老格式下解析里带着字母引用，所以**位置只能照它自己排的来**，不重排。
    """
    right = (it.get("right") or "").strip()
    wrong = [str(x).strip() for x in (it.get("wrong") or []) if str(x).strip()]
    if right and len(wrong) == 3:
        why_w = [str(x).strip() for x in (it.get("why_wrong") or [])]
        return right, wrong, (it.get("why_right") or "").strip(), why_w, True

    # 老格式兜底：从 options + answer 还原
    opts = it.get("options") or []
    ans = (it.get("answer") or "").strip().upper()[:1]
    if len(opts) != 4 or ans not in "ABCD":
        return "", [], "", [], False
    body = [re.sub(r"^[A-D][.、．)]\s*", "", str(o)).strip() for o in opts]
    i = "ABCD".index(ans)
    # ⚠️ 最后那个 False = **不许重排**。老格式的解析正文里带着字母引用
    #    （「故 D 错误」「A、B、C 均为…」），一重排就全对不上号了。
    #    这类题只能保持模型自己排的顺序，代价是它们仍然偏 A —— 但那也远好过解析指错选项。
    return body[i], body[:i] + body[i + 1:], (it.get("explain") or "").strip(), [], False


def _compose_explain(ans, why_right, why_wrong, wrong, body):
    """按**最终排好的位置**拼解析文字。

    为什么要自己拼：模型不写字母，我们才敢重排选项；重排之后解析里的字母当然也得由我们填。
    反过来说，如果直接拿模型写好的带字母解析去重排选项，就得回头改写解析正文，
    而正文里还有「A股」「DNA」「B超」这类不能动的字母 —— 那条路比字母倾斜更危险。

    why_wrong 是空的（老格式兜底）就把原解析原样返回，不硬拼。
    """
    if not why_wrong:
        return why_right

    def clean(t):
        # 模型每条都自带句号，直接用「；」拼会拼出「…符合语境。；B 项错在…」
        return str(t).strip().rstrip("。；;，,")

    parts = ["正确答案 %s：%s" % (ans, clean(why_right))] if why_right else []
    for w, why in zip(wrong, why_wrong):
        if not clean(why):
            continue
        try:
            letter = "ABCD"[body.index(w)]
        except ValueError:
            continue                     # 干扰项文本对不上（模型改了写法），跳过这条
        parts.append("%s 项错在：%s" % (letter, clean(why)))
    return "；".join(parts) + "。" if parts else ""


def _bank_avoid(db, board, qtype, n=25):
    """已经出过的题干开头，喂给模型让它别再出一样的。

    sig 指纹是 md5(板块+题型+题干) —— **不含难度**，这是故意的：同一道题不该在
    「入门」和「考场真实」里各出现一次。但代价是模型一旦收敛到那几道经典题
    （定义判断的「行政处罚」、类比推理的「医生：手术刀」），换个难度再出还是它们，
    12 道全撞 UNIQUE 被跳过 —— 日志上看就是「一道都没出来」。
    所以把已有的题干告诉它，逼它换新的。
    """
    rows = db.execute("SELECT q FROM drill_bank WHERE board=? AND qtype=? "
                      "ORDER BY id DESC LIMIT ?", (board, qtype, n)).fetchall()
    return [re.sub(r"\s+", "", (r["q"] or ""))[:40] for r in rows if r["q"]]


# ---- 以真题为基准出题 --------------------------------------------------------
# AI 题跑偏的根子不在提示词写得不够细，而在**它没见过真题长什么样**。
# 光靠 _AI_SPEC 那种抽象规则（「干扰项要贴着常见错法」），模型只会照字面理解；
# 直接把同题型的真题摆给它看，出来的题风格立刻就近了 —— 这是最省事也最有效的一招。
#
# 只取「答案靠得住」的真题（原卷带答案，或 AI 出解析且过了双模型核验）。
#
# ⚠️ **必须连模块一起卡**，只按题型捞会捞出一堆别的模块的题。
# 题型标签有两个来源：rq.qtype（解析器按规则判的，可信）和 re.qtype（AI 顺手判的兜底）。
# 后者**不受模块约束** —— 实测把「2012—2020年，中国IC封装市场规模同比增量最大的年份是：」
# 判成了「语境分析」，于是它会作为「选词填空真题范例」喂给出题模型。
# 跑 audit_qtype.py 量过：不卡模块的话，捞到的 5325 道里只有 68.7% 是对模块的，
# 语境分析 46%、查找细节 58% 都是脏的。这种脏数据不报错也不崩，只让题一点点跑偏。
_REAL_OK = (realref.servable("rq", "re")
            + " AND " + realref.qtype_expr("rq", "re") + "=? AND rq.module=?")

# ⚠️ **module 为空的真题（实测 156 道有题型标签但没模块）就此不参与范例和分位统计。**
# 这是有意的：不知道属于哪个模块的题，正是标签最不可信的那批。代价要认：
# 政治理论·习近平思想因此少 4 道（原池才 7 道）、语境分析少 34 道。P1 回填模块后自然恢复。
#
# 「这道真题让人读多少字」= 材料 + 题干，**必须合起来算**。
# 只量 stem 是不对的：片段阅读/文章阅读的文段存在 material 列里，题干只剩
# 「根据文章，下列说法正确的是：」14 个字，拿它算分位会把篇幅下限压到 20 上下，
# 而出题提示词和 _style_ok 都吃这个数 —— 那道「别把片段阅读压成一句话」的护栏，
# 就变成了**放行一句话的题**。出题时要求模型把文段写进题干，两边口径必须一致。
# ⚠️ material 这列**存过字符串 'None'**（早期入库把 Python 的 None 直接格式化进去了）。
_REAL_TEXT = "COALESCE(NULLIF(rq.material,'None'),'')"
_REAL_LEN = "(LENGTH(%s) + LENGTH(rq.stem))" % _REAL_TEXT


def _real_args(board, qtype):
    """_REAL_OK 里两个 ? 的实参，顺序不能反。"""
    return (qtype, realref.board_module(board))


def _real_examples(db, board, qtype, n=3):
    """抽 n 道**同模块同题型**的真题当范例。近年的优先 —— 出题风格是会变的。

    ⚠️ 别退回 `ORDER BY year_max DESC LIMIT n*4`：那样 RANDOM() 只在同一年内洗牌，
    取到的永远是最新的那十几道。实测定义判断连跑 8 轮，617 道里只出现过 17 道不同的题
    —— 「以真题为基准」长期锚在十来道上，模型反复看同几道，风格多样性根本拿不到。
    改成**近 5 年优先、年段内整体随机**，既保住「近年优先」又把池子放开。
    """
    try:
        rows = db.execute(
            "SELECT rq.stem, %s AS mat, rq.options, rq.answer, re.answer AS ai_answer "
            "FROM real_questions rq LEFT JOIN real_explains re ON re.qid=rq.id "
            "WHERE %s AND %s BETWEEN ? AND ? "
            # 上限是给提示词兜底的：文章阅读的原文能有一千多字，三道范例就把提示词撑得很大。
            # 长度闸**写在 SQL 里**，别一半在 SQL 一半在 Python —— 两道闸口径不一致时，
            # 取回来又被丢掉的行会白占 LIMIT 名额，最终范例数不足 n 且没有任何日志。
            "ORDER BY (rq.year_max >= ?) DESC, RANDOM() LIMIT ?"
            % (_REAL_TEXT, _REAL_OK, _REAL_LEN),
            _real_args(board, qtype) + (20, 1800, date.today().year - 5, n * 4)).fetchall()
    except sqlite3.Error:
        return []                       # 真题库还没导入（新库），照老路子出题
    # 去重要**分开认材料和设问**：文章阅读是一篇文章配多问，这些行 material 完全相同，
    # 拿合并后的前缀当键会把它们全判成同一道题（前缀取到的是材料开头）。
    # 同一篇材料只留一道是对的（三道同文章的范例没有价值），但要显式表达，
    # 别靠前缀碰撞顺带实现 —— 否则范例数会悄悄少于 n 且没有任何日志。
    out, seen_mat, seen_stem = [], set(), set()
    for r in rows:
        # 材料要一起给：范例的价值就在文段怎么写、设问怎么问，只给设问等于没给
        mat = r["mat"] or ""
        stem_key = (r["stem"] or "")[:20]
        if (mat and mat[:40] in seen_mat) or stem_key in seen_stem:
            continue
        seen_mat.add(mat[:40])
        seen_stem.add(stem_key)
        out.append({"q": ("%s\n%s" % (mat, r["stem"])).strip(),
                    "options": json.loads(r["options"]),
                    "answer": r["answer"] or r["ai_answer"] or ""})
        if len(out) >= n:
            break
    return out


def _style_ok(prof, q, opts):
    """生成的题在不在真题的体量范围里。

    ⚠️ **下限不能留太多余量**。原先写的是 `p10 × 0.4`，意思是「只拦离谱的」——
    可实测下来，AI 出的题**系统性地往短里写**，根本不是偶发离谱：
    语境分析真题中位数 123 字，AI 出 54~63 字；而 76×0.4=30，护栏一道都拦不下，
    旧题库里 116 道语境分析只有 9% 落在真题区间，91% 偏短。

    下限就用**真题的 10% 分位本身**，不乘系数。这个数自带校准含义 ——
    「只有一成真题比这还短」，低于它就不该叫这个题型的题了。
    试过用「中位数 × 0.7」，结果削弱论证的下限算成 101 字，比它自己的 10% 分位（96）
    还高，把 97 字、100 字的题也拦了 —— 那是在拒绝比一成真题还长的题，纯属过严。
    提示词那边给的是**中位数**（更高），两者配合：告诉模型往中位数写，按 p10 收。
    上限仍然宽松：写长了不像真题，但至少是道能做的题，危害小得多。
    """
    if not prof:
        return True
    lo, hi = prof["stem"]
    if not (lo <= len(q) <= hi * 2.0 + 40):
        return False
    olo, ohi = prof["opt"]
    avg = sum(len(o) for o in opts) / 4.0
    return olo * 0.3 <= avg <= ohi * 2.5 + 20


def _slot_letters():
    """源源不断地给出正确答案该放的位置：**每发完一副 ABCD 就重新洗一副**。

    ⚠️ 别按题数铺一张固定表。原先写的 `["ABCD"[i % 4] for i in range(max(1, want))]`
    再整体洗牌，在 want < 4 时会塌掉：实测 want=1 喂 8 道题 → 答案**全是 A**；
    want=2 → BABABABA（只用两个字母且严格交替）；want=4 → DBACDBAC，
    前四道之后完全可预测，背下来就能蒙。
    每日巩固测试是按模块分配名额的（资料分析 1 道、数量关系 1 道…），
    P5 接进来就必然踩到 want=1 那一档。改成无界发牌，与题数彻底解耦。
    """
    while True:
        deck = list("ABCD")
        random.shuffle(deck)
        for c in deck:
            yield c


def _assemble_items(got, prof, stat=None):
    """把模型交的原始 items 变成可发的题：拆右/错 → **按均衡位置放正确项** → 拼解析 → 过篇幅护栏。

    抽出来是**为 P5 让每日巩固测试复用**（那边现在完全没有双模核验和答案均衡）；
    在 P5 落地之前，唯一调用方仍是 _bank_fill —— 别照着 docstring 以为两边已经打通了。

    返回 (ready, stat)：ready 是 [(item, q, ans, options)]，item 的 explain 已按最终位置拼好；
    stat 是 bad/style 计数（调用方要能分清「格式不合格」和「体量不像真题」）。
    **计数一并返回而不是只靠改写入参** —— 只靠副作用的话，调用方忘了传 stat 就会
    静默丢题，而日志里 bad/style 恒为 0，「产出为什么这么低」正好查不出来。
    """
    stat = stat if stat is not None else {}
    # ★ 正确项放哪个位置**由我们定**，不问模型。模型自己排的话正确项严重偏前：
    #   实测专项练题库 A 39.3% / D 7.4%，真题则是各占四分之一。
    #   试过在提示词里逐题指定位置，**实测无效** —— 照做之后 A 反而升到 45%。
    #   所以让模型只交「正确项 + 三个干扰项」、字母一个不写，这里插到指定位置、
    #   自己拼字母和解析。构造性保证，和模型听不听话无关。
    slots = _slot_letters()
    ready = []
    for it in got:
        q = (it.get("q") or "").strip()
        right, wrong, why_r, why_w, can_place = _split_rw(it)
        if not q or not right or len(wrong) != 3:
            stat["bad"] = stat.get("bad", 0) + 1
            continue
        # 老格式（options+answer）的解析里带字母引用，一重排就全指错，只能保持原位。
        # 注意：**只有入选的题才从 slots 取一张牌** —— 被拒的题不该消耗名额，
        # 否则一批里刷掉一半时，剩下那半的字母分布又会失衡（正是要修的毛病）。
        pos = "ABCD".index(next(slots)) if can_place else 0
        body = wrong[:pos] + [right] + wrong[pos:]
        ans = "ABCD"[pos]
        if len(set(body)) != 4 or not all(body):
            stat["bad"] = stat.get("bad", 0) + 1
            continue
        it = dict(it, explain=_compose_explain(ans, why_r, why_w, wrong, body))
        if not _style_ok(prof, q, body):
            stat["style"] = stat.get("style", 0) + 1
            continue
        ready.append((it, q, ans, ["%s. %s" % ("ABCD"[i], body[i]) for i in range(4)]))
    return ready, stat


def _audit_items(ready, board, qtype):
    """双模型核验：另一家模型**独立作答**一遍。返回和 ready 等长的结果列表。

    **并发**跑 —— 核验是网络往返，一道 5~40 秒，串行做 8 道能拖到十分钟以上。
    """
    if not ready:
        return []
    with ThreadPoolExecutor(max_workers=min(6, len(ready))) as pool:
        return list(pool.map(lambda r: _audit_q(r[1], r[3], board, qtype), ready))


def _parse_items(rep, tag=""):
    """解析模型返回的 JSON；被 max_tokens 截断时把写完整的那几道抢救回来。

    名字带下划线是**故意**的：gen_real_explain.py 里另有一个同名的 parse_items，
    两者对截断和字段的处理并不一样，同名公开会让人 import 错了也不报错。
    """
    try:
        return json.loads(rep).get("items") or []
    except Exception:
        got = _salvage_items(rep)
        if got and tag:
            log.info("%s：JSON 截断，抢救回 %d 道", tag, len(got))
        return got


def _bank_fill(db, board, qtype, level, want=8):
    """题库不够了就补一批。返回 {"ok":可用, "dup":撞已有题, "bad":格式不合格, "flaw":没过核验}。

    调用方要能分清「AI 出不了这个题型」和「出的全是重复题」—— 两者的处置完全不同：
    前者该放弃，后者该换个角度再出。原先只返回一个数字，两种情况都显示成 0。

    **每个题型的出题要点不一样**（见 _AI_SPEC）——不写清楚，AI 会把「判断意图」出成「概括主旨」。
    """
    stat = {"ok": 0, "dup": 0, "bad": 0, "flaw": 0, "style": 0}
    mat = _bank_material(db, board, qtype)
    examples = _real_examples(db, board, qtype)
    prof = realprofile.get(db, board, qtype)   # 真题画像：篇幅/惯用问法/空数，样本不足时是 None
    tip = DRILL_TIP.get(qtype, "")
    spec = _AI_SPEC.get(qtype, "")
    extra = ""
    if board in ("常识判断", "政治理论"):
        if not mat:
            return 0
        extra = ("\n【只能考下面这些考点】（一道题考一个，别超纲）\n"
                 + "\n".join("· " + x for x in mat))
    elif qtype in ("语境分析", "词语辨析"):
        # ⚠️ 从词库随机抽的词彼此**不相关**，直接丢给 AI 当四个选项，它就拿来凑数了
        #    （实测出过「施行 / 掩饰 / 减轻 / 接二连三」—— 一眼就能选，这题白出）。
        #    正确答案从我们库里挑（保证考的是积累过的词），**另外三个近义混淆项让 AI 自己造**。
        # 这段必须和 _AI_SPEC 的「两空/三空」说法一致 —— 原先写的是「正确答案从这些词里挑一个」
        # 外加「另外三个选项是它的近义词」，那是**一空题**的说法，和 spec 直接打架，
        # 模型听哪一半都不对（听 extra 就退回一空题，听 spec 则词表约束形同虚设）。
        extra = ("\n【每个空的正确用词，尽量从下面这些他积累过的词里挑】\n"
                 + "\n".join("· " + x for x in mat[:12])
                 + "\n\n⚠️ 四个选项是**四组词**（每组两三个词，对应两三个空）。"
                   "同一个空的四个候选词**必须是近义词/易混词**，"
                   "**放在一起才需要辨析**（如「施行/实行/执行/推行」）；"
                   "**绝不能**拿不相干的词凑数（「施行/掩饰/减轻/接二连三」一眼就能排除，这题就白出了）。"
                   "解析要讲清**每个空为什么只能填那个词**。")

    prompt = (
        "给四川省考考生出 %d 道**%s · %s**的单选题。\n\n"
        "【这个题型怎么出】%s\n\n"
        "【难度】%s\n\n"
        "【每道题】\n"
        "· q：题干%s（题型要求见上；片段阅读/文章阅读要把**文段原文写进题干**）\n"
        "· right：**正确选项的内容**（只写内容，前面不要加 A/B/C/D，也不要提任何字母）\n"
        "· wrong：三个干扰项的内容，数组（同样只写内容、不带字母）\n"
        "· why_right：这一项为什么对（不要出现字母）\n"
        "· why_wrong：三个干扰项各自错在哪，数组，**顺序和 wrong 一一对应**（不要出现字母）\n"
        "· source：这题考的具体考点（如「人文常识-唐宋八大家」「词语辨析-一蹴而就」）\n"
        "⚠️ 解析合计**控制在 150 字以内** —— 写太长会把整批输出撑爆、后面的题一道都收不到。\n\n"
        "【硬要求】\n"
        "1. 答案**唯一且经得起推敲**，不能出现两个都对或都说得通的选项。\n"
        "2. 四个选项**互不相同**、长度相当（别让正确项特别长，那等于送分）。\n"
        "3. 一道题**围绕一个考点**。四个选项可以是关于同一事物的四种说法（这很常见），"
        "但**不能横跨四个不相干的知识点**——那是在考运气，不是考掌握。\n"
        "4. **必须真的是「%s」这个题型**，不要出成别的题型。\n\n"
        "5. **通篇不要出现 A/B/C/D 这样的选项字母**，正确项写进 right、干扰项写进 wrong 就行 —— "
        "选项排到第几位、答案是哪个字母，由我来定。\n\n"
        '只输出 JSON：{"items":[{"q":"","right":"","wrong":["","",""],'
        '"why_right":"","why_wrong":["","",""],"source":""}]}'
        % (want, board, qtype, spec or "按这个题型的常规考法出",
           _LV_PROMPT.get(level, ""),
           # 篇幅要求**贴在 q 这一行**再说一遍。后面的【篇幅按真题来】那段离得远，
           # 模型写 q 的时候未必还记着；实测削弱论证写 78~86 字，而下限是 96。
           realprofile.q_hint(prof), qtype)) + extra

    # ★ 以真题为基准：把同题型的真题原样摆出来，让它照着这个路子出。
    #   比在提示词里描述「要像真题」有效得多 —— 风格是看会的，不是讲会的。
    # 把真题画像**当成硬指标写进去**，不能只在事后拦。
    # ⚠️ 给区间没用：原先写的是「题干 76~226 字」，模型一律往下限以下写 ——
    #    实测语境分析真题中位数 123 字，AI 出 54~63 字，旧题库 116 道里只有 9%
    #    落在真题区间、91% 偏短。改成给**中位数**这个具体数 + 明确的不合格线，
    #    再要求照真题的惯用问法收尾，一次调用出的 4 道全部达标（命中率 0%→100%）。
    prompt += realprofile.prompt_lines(prof)

    if examples:
        prompt += ("\n\n【下面是这个题型的**真题**，照着这个路子出新题】\n"
                   + "\n\n".join(
                       "· 真题%d\n%s\n%s\n（答案 %s）"
                       % (i, e["q"],
                          "\n".join("%s. %s" % ("ABCD"[j], o) for j, o in enumerate(e["options"])),
                          e["answer"])
                       for i, e in enumerate(examples, 1))
                   + "\n\n**要学的是**：题干的体量和文风、设问的措辞、干扰项是怎么造的"
                     "（改主体/改范围/改时间/贴着常见错法）。"
                     "**不要照抄**上面这几道，要出**新的**题，考点也换掉。")

    # 避重：不告诉它已经出过什么，它就会一直出那几道经典题，全撞指纹被跳过
    avoid = _bank_avoid(db, board, qtype)
    if avoid:
        prompt += ("\n\n【这些题已经出过了，**换新的**，别再出意思一样的】\n"
                   + "\n".join("· " + x + "…" for x in avoid))

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是四川省考命题老师。答案唯一、干扰项讲究，"
                                       "解析要说清其他三个为什么错。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        # 接了真题画像之后题干按中位数写（选词填空 123 字、判断意图 211 字，都比原来长
        # 一倍多），8 道题加解析在 4096 里放不下，后半批会被截断 —— 表现是
        # _salvage_items 一直在抢救，产出白白少一半。所以提到 8000。
        # 上限依据：deepseek-chat 单次输出上限 8192，留一点余量。**换模型前先确认它的上限**，
        # 超了不是截断而是整批 400，日志只会显示「+0 可用」，看不出是参数越界。
        temperature=0.6, max_tokens=8000, timeout=180, json_mode=True)
    if err:
        return stat
    got = _parse_items(rep, "题库补充 %s·%s/%s" % (board, qtype, level))
    if not got:
        return stat

    ready, stat = _assemble_items(got, prof, stat)
    if not ready:
        return stat
    audits = _audit_items(ready, board, qtype)

    # strict=True：两边长度不一致就当场抛，别静默截断。
    # 不加的话，audits 短一截只表现为「这批出了 8 道、入库只有 5 道」，
    # 而 stat 里三个计数加起来对不上 8，查起来毫无线索。
    for (it, q, ans, opts_std), au in zip(ready, audits, strict=True):
        # 答案不一致 → **入库但标为存疑，不发给人做**。
        # （不直接丢弃：存疑的题本身是有价值的数据，可以回查；但绝不能让人拿去背。）
        if au is None:
            agree, aans, flaw, note = 0, "", "unchecked", "核验模型没响应"
            checked = 0
        else:
            aans, flaw, note = au
            checked = 1
            agree = 1 if (aans == ans and flaw == "ok") else 0
        sig = hashlib.md5((board + qtype + re.sub(r"\s", "", q)).encode()).hexdigest()
        try:
            db.execute(
                "INSERT INTO drill_bank(board,qtype,level,q,options,answer,explain,tip,source,sig,"
                "checked,agree,audit_ans,audit_note,flaw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (board, qtype, level, q, json.dumps(opts_std, ensure_ascii=False),
                 ans, (it.get("explain") or "").strip(), tip,
                 (it.get("source") or ("%s-%s" % (board, qtype))).strip(), sig,
                 str(checked), str(agree), aans, note, flaw))
            if agree:
                stat["ok"] += 1      # 只把「过了核验的」算作有效产出
            else:
                stat["flaw"] += 1    # 入库了，但存疑，不发给人做
        except sqlite3.IntegrityError:
            stat["dup"] += 1         # 撞指纹 = 这道题出过了（跨难度也算），跳过
    db.commit()
    return stat


# ---- 后台补库：出题请求里**绝不**调 AI ----------------------------------------
# 原先库里没题就当场生成：DeepSeek 出一批 + 每道题串行核验，最坏能跑十几分钟，
# 而前端的 fetch 没有超时，用户看到的就是「点了出题，没反应」。
# 现在改成：取到多少给多少，缺口排进后台队列，下次进来就有了。
_FILL_LOCK = threading.Lock()
_FILL_INFLIGHT = set()          # 正在补的 (board,qtype,level)，同一格不重复排队
_FILL_POOL = None


def _fill_pool():
    """**必须在 _FILL_LOCK 里调用**：waitress 跑 32 个线程，两个请求同时首次触发补库时
       都会看到 None，各建一个池，其中一个虽被覆盖但已提交的任务照跑 ——
       实际并发变成 4，「并发 2」这个刻意的限流约束就形同虚设了。"""
    global _FILL_POOL
    if _FILL_POOL is None:       # 并发 2：再多就把 AI 接口的限流打满，反而更慢
        _FILL_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="drillfill")
    return _FILL_POOL


def _bank_warm(board, qtype, level, want=12):
    """排一次后台补库，**立刻返回**。同一格已在排队的不重复排。
       用自己的 sqlite 连接：请求线程的连接绑在 flask.g 上，请求一结束就关了。"""
    if DRILL_ENGINE.get((board, qtype)) != "ai":
        return False
    key = (board, qtype, level)
    with _FILL_LOCK:
        if key in _FILL_INFLIGHT:
            return False
        _FILL_INFLIGHT.add(key)
        pool = _fill_pool()

    def job():
        con = None
        try:
            con = sqlite3.connect(DB, timeout=30)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            s = _bank_fill(con, board, qtype, level, want=want)
            log.info("题库补充 %s·%s/%s：+%d 可用（重复 %d、存疑 %d、格式不合格 %d、"
                     "体量不像真题 %d）",
                     board, qtype, level, s["ok"], s["dup"], s["flaw"], s["bad"], s["style"])
        except Exception as e:
            log.warning("题库补充失败 %s·%s/%s：%s", board, qtype, level, e)
        finally:
            if con is not None:
                con.close()
            with _FILL_LOCK:
                _FILL_INFLIGHT.discard(key)

    try:
        pool.submit(job)
    except Exception as e:
        # submit 抛了（线程池已关闭等）→ job 永远不会跑，finally 里的 discard 也就不会执行。
        # 不在这儿补一刀的话，这一格会**在整个进程生命周期内**卡在「正在补库」，
        # 再也排不进队，用户反复点只会一直看到「题库还没预热好」。
        with _FILL_LOCK:
            _FILL_INFLIGHT.discard(key)
        log.warning("题库补充没能排队 %s·%s/%s：%s", board, qtype, level, e)
        return False
    return True


def _bank_take(db, board, qtype, level, n):
    """从题库取 n 道 —— **只取过了双模型核验的**（agree=1）。
       **取不够也立刻返回**，缺口交给后台补库：让人等十分钟不如先给他 4 道能做的。
       存疑的题留在库里可以回查，但绝不发给人做（拿去背错的答案，比不做还糟）。"""
    got = [dict(r) for r in db.execute(
        "SELECT * FROM drill_bank WHERE board=? AND qtype=? AND level=? AND agree='1' "
        "ORDER BY RANDOM() LIMIT ?", (board, qtype, level, n))]
    if len(got) < n:                      # 核验会刷掉一部分，所以多补一些
        # ×4 而不是 ×2：接了真题画像、护栏按真题 10% 分位收紧之后，一批里有一半
        # 会因为「写太短」或没过双模核验被刷掉（实测词语辨析 10 道只留下 2 道）。
        # 按老的 ×2 排队，补一轮还是填不满，用户就会一直看到「题库还没预热好」。
        _bank_warm(board, qtype, level, want=max(12, (n - len(got)) * 4))
    out = []
    for r in got:
        out.append({"q": r["q"], "options": json.loads(r["options"]), "answer": r["answer"],
                    "explain": r["explain"], "tip": r["tip"], "module": board,
                    "source": r["source"], "qtype": qtype, "level": level, "src": "ai"})
    return out


# ---- 题源之一：真题本身 --------------------------------------------------------
# 「真题练习」和「AI 出题」是同一个板块下的两个**题源**，不是两套功能：
#   real —— 答案权威、风格 100% 真实，但**就那么几千道，做完不会再有**
#   ai   —— 无限量、考点可控，风格靠 realprofile 那套画像往真题上对齐
# 真题模式下**没有 easy/mid/real 三档**：真题没有难度标签，硬套是假的
# （原先「考场真实」这一档发的其实是 AI 题，名不副实）。改成按年份筛。
_REAL_SRC_MIN = 5          # 少于这么多道就别开真题模式了，刷两轮就重复


def _real_count(db, board, qtype):
    """这个(板块,题型)有多少道能发的真题 —— 前端据此决定要不要把「真题练习」置灰。"""
    try:
        return db.execute(
            "SELECT COUNT(*) FROM real_questions rq LEFT JOIN real_explains re ON re.qid=rq.id "
            "WHERE " + _REAL_OK, _real_args(board, qtype)).fetchone()[0]
    except sqlite3.Error:
        return 0               # 真题库还没导入（新库）


def _real_counts(db, board):
    """整个板块每个题型有多少道能发的真题 —— 一次 GROUP BY，别逐题型查。
       前端据此决定要不要把「真题练习」这个题源置灰。"""
    try:
        return {r[0]: r[1] for r in db.execute(
            "SELECT %s t, COUNT(*) FROM real_questions rq "
            "LEFT JOIN real_explains re ON re.qid=rq.id "
            "WHERE %s AND rq.module=? GROUP BY 1"
            % (realref.qtype_expr("rq", "re"), realref.servable("rq", "re")),
            (realref.board_module(board),))}
    except sqlite3.Error:
        return {}              # 真题库还没导入（新库）


def _real_take(db, board, qtype, n, year_min=0):
    """从真题库取 n 道，转成专项练的题目格式。

    排序**就是这个模式的价值所在**，不是随便抽（和 realq 同一套思路）：
    没做过的 > 做错过的 > 做对过的。随机抽的话，刷三遍等于把第一遍重刷三次。
    每次作答都会写进 real_attempts，所以**和「历年真题」模块的进度是通的** ——
    在专项练里做过的题，去真题模块不会再当新题推给你。
    """
    where, args = [_REAL_OK], list(_real_args(board, qtype))
    if year_min:
        where.append("rq.year_max>=?")
        args.append(year_min)
    try:
        rows = [dict(r) for r in db.execute(
            "SELECT rq.id, rq.stem, rq.material, rq.options, rq.answer, rq.module, "
            "  rq.explain AS official, re.answer AS ai_answer, re.keypoint, re.steps, re.tip, "
            "  (SELECT COUNT(*) FROM real_attempts a WHERE a.qid=rq.id AND a.user_id=?) tries, "
            "  (SELECT a.correct FROM real_attempts a WHERE a.qid=rq.id AND a.user_id=? "
            "   ORDER BY a.id DESC LIMIT 1) last_ok "
            "FROM real_questions rq LEFT JOIN real_explains re ON re.qid=rq.id "
            "WHERE " + " AND ".join(where), [uid(), uid()] + args)]
    except sqlite3.Error:
        return []
    # 0 没做过 → 1 做错过 → 2 做对了。同档内随机，免得每次都是同一批
    rows.sort(key=lambda r: (0 if not r["tries"] else (1 if not r["last_ok"] else 2),
                             random.random()))
    figs = realref.figs_of(db, [r["id"] for r in rows[:n]])
    out = []
    for r in rows[:n]:
        ans = (r["answer"] or r["ai_answer"] or "").strip().upper()[:1]
        # ⚠️ 别写 `ans not in "ABCD"` —— **空串是任何字符串的子串**，`"" in "ABCD"` 是 True，
        #    那个写法对空答案完全不设防（这条是被测试抓出来的）。
        if ans not in ("A", "B", "C", "D"):
            # 答案取不出来的题**绝不能发**：drill_done 判分时 your == "" 恒为 False，
            # 用户做对也算错，还会被塞进错题本。_REAL_OK 保证「有答案」，
            # 但挡不住个别行 answer 被后续流程清成空串。
            continue
        mat = (r["material"] or "").strip()
        out.append({
            "q": r["stem"], "options": json.loads(r["options"]),
            "answer": ans,
            "explain": _real_explain(r), "tip": r["tip"] or DRILL_TIP.get(qtype, ""),
            "module": board, "qtype": qtype, "level": "real", "src": "real",
            "real_id": r["id"],            # 交卷时靠它写 real_attempts，和真题模块共享进度
            "material": "" if mat in ("", "None") else mat,
            "figs": figs.get(r["id"], []),
            "source": "真题 · %s" % qtype,
        })
    return out


def _real_explain(r):
    """真题的解析。**别只发 keypoint 那一句**。

    实测定义判断 628 道里 562 道带完整的原卷解析（「第一步，看提问方式…A 项：…B 项：…」
    这种逐项辨析），re.steps 也有。原先这里只取 keypoint（一句话概括），
    同一道题在「历年真题」模块看到的是完整解析、在专项练里只剩一句 —— 像缩水了。

    优先给结构化的（关键 + 分步，手机上好读），没有再退回原卷那一整段。
    """
    parts = []
    if r["keypoint"]:
        parts.append("关键：%s" % r["keypoint"].strip())
    try:
        steps = json.loads(r["steps"] or "[]")
    except (ValueError, TypeError):
        steps = []
    parts += ["%d. %s" % (i, str(s).strip()) for i, s in enumerate(steps, 1) if str(s).strip()]
    if parts:
        return "\n".join(parts)
    return (r["official"] or "").strip()      # 原卷那一整段兜底


def _drill_gen(db, board, qtype, n, level="mid", src="ai", year_min=0):
    """出 n 道题。

    src 是**题源开关**（这是 P3 的核心）：
      real —— 全部发真题。答案权威、风格 100% 真实，但题量有限、做完不会再有
      ai   —— 老路子：AI 题库（_bank_take）或程序化构造（figgen）
      mix  —— 真题优先填，不够的用 ai 补。默认给 mix 之外的老行为留 ai

    src=ai 时仍然**按题型决定引擎** —— 判断推理是混合的：图形推理能构造（prog），
    定义/类比/逻辑判断只能让 AI 出（ai）。
    """
    types = [t[0] for t in DRILL_TYPES[board]]
    if not qtype:                                  # 混合练：题型轮着来，但**每个题型一次取够**
        # 原先是逐题递归（一道题调一次 _drill_gen），10 道题就可能触发 10 轮补库；
        # 判断推理前 4 个题型是图形（秒出）、第 5 个撞上空库，整个请求就卡死在那儿了。
        need = {}
        for i in range(n):
            t = types[i % len(types)]
            need[t] = need.get(t, 0) + 1
        out = []
        for t, k in need.items():
            out += _drill_gen(db, board, t, k, level, src, year_min)
        random.shuffle(out)                        # 混合练就该乱序，别一坨一坨按题型来
        return out[:n]
    if qtype not in types:
        return []

    got = []
    if src in ("real", "mix"):
        got = _real_take(db, board, qtype, n, year_min)
        if src == "real" or len(got) >= n:
            return got[:n]
        # mix：真题不够（这个题型本来就没几道，或者都做过了），剩下的名额交给 AI/程序化。
        # **不静默降级**——调用方能从 item 的 src 字段看出每道题是哪来的。

    need_n = n - len(got)                          # 还差几道；别把参数 n 改名顶掉
    eng = DRILL_ENGINE.get((board, qtype), "ai")
    if eng == "ai":
        return got + _bank_take(db, board, qtype, level, need_n)

    out = []
    for _ in range(need_n):
        if board == "数量关系":
            q = _gen_math_q(qtype, level)
        elif board == "判断推理":
            q = _gen_figure_q(qtype, level)        # kind = 目录里的大类（位置变化/样式规律/…）
        else:
            q = _gen_ziliao(1, level)[0]
            for _ in range(15):                    # 摇到指定考点为止
                if q["source"].split("-")[-1] == qtype:
                    break
                q = _gen_ziliao(1, level)[0]
        q["qtype"] = qtype                         # 统计要按「目录里的题型名」记，不是生成器的细目
        q.setdefault("tip", DRILL_TIP.get(qtype, ""))
        q["level"] = level
        q["src"] = "prog"
        out.append(q)
    return got + out


@bp.get("/api/drill/types")
def drill_types():
    """题型清单 + 我在每个题型上的正确率和平均用时。弱的排前面 —— 该练哪个不用自己想。"""
    board = (request.args.get("board") or "").strip()
    level = (request.args.get("level") or "mid").strip()
    if board not in DRILL_TYPES:
        return jsonify({"error": "这个板块没有专项练"}), 400
    db = get_db()
    stat = {r["qtype"]: dict(r) for r in db.execute(
        "SELECT qtype, COUNT(*) n, SUM(correct) ok, AVG(seconds) sec FROM drill_log "
        "WHERE user_id=? AND board=? AND level=? GROUP BY qtype", (uid(), board, level))}
    # 题库里每个题型有多少道过了双模型核验（AI 题型才有）
    bank = {r["qtype"]: dict(r) for r in db.execute(
        "SELECT qtype, SUM(agree='1') ok, COUNT(*) c FROM drill_bank "
        "WHERE board=? AND level=? GROUP BY qtype", (board, level))}
    # 整个板块的真题存量**一次 GROUP BY 算完**，别每个题型各查一次：
    # 一个板块最多 14 个题型，这里是专项练首页的同步路径。
    real_cnt = _real_counts(db, board)
    items = []
    for i, (k, desc, eng) in enumerate(DRILL_TYPES[board]):
        st = stat.get(k) or {}
        bk = bank.get(k) or {}
        n = st.get("n") or 0
        acc = round(100.0 * (st.get("ok") or 0) / n) if n else None
        n_real = real_cnt.get(k, 0)
        items.append({"type": k, "desc": desc, "eng": eng, "ord": i, "n": n, "acc": acc,
                      "sec": round(st.get("sec") or 0) if n else None,
                      "tip": DRILL_TIP.get(k, ""),
                      "bank_ok": bk.get("ok") or 0,          # 过了双模型核验的
                      "bank_all": bk.get("c") or 0,
                      # 真题存量：前端据此决定「真题练习」这个题源要不要置灰。
                      # 政治理论四个题型真题只有个位数、文章阅读一道都没有，
                      # 这种就该明说「没有」，不该假装有。
                      "real_n": n_real,
                      "real_ok": n_real >= _REAL_SRC_MIN})
    # 默认按**讲义目录顺序**（循序渐进）；练过之后，薄弱的（低于该难度预期得分率）才提到前面
    exp = round(drill_coef(board, level) * 100)
    items.sort(key=lambda x: (0 if (x["acc"] is not None and x["acc"] < exp) else 1,
                              x["acc"] if x["acc"] is not None else 999, x["ord"]))
    coef = drill_coef(board, level)
    return jsonify({"board": board, "limit": DRILL_LIMIT.get(board, 60), "types": items,
                    "levels": drill_levels(board),
                    "level": level, "coef": coef, "base": DRILL_BASE.get(board, 0.6),
                    "ai": board in AI_BOARDS,
                    "methods": DRILL_METHODS.get(board, []),
                    "missing": DRILL_MISSING.get(board, "")})


@bp.get("/api/drill/boards")
def drill_boards():
    """哪些板块有专项练（首页/板块页要用）。"""
    return jsonify({"boards": [{"board": b, "n_types": len(DRILL_TYPES[b]),
                                "ai": b in AI_BOARDS, "base": DRILL_BASE.get(b, 0.6)}
                               for b in DRILL_TYPES]})


@bp.post("/api/drill/quiz")
def drill_quiz():
    d = request.get_json(silent=True) or {}
    board = (d.get("board") or "").strip()
    if board not in DRILL_TYPES:
        return jsonify({"error": "这个板块没有专项练"}), 400
    qtype = (d.get("type") or "").strip()
    # 题型名不认识就当场说清楚。**别混进下面那条「题库还没预热好」**——
    # 那句话承诺了「已经在后台出题了，过一两分钟回来再点」，而这种情况根本没排队，
    # 用户等一辈子也不会好，换难度也没用。
    if qtype and qtype not in [t[0] for t in DRILL_TYPES[board]]:
        return jsonify({"error": "「%s」板块里没有「%s」这个题型" % (board, qtype)}), 400
    level = d.get("level") if d.get("level") in ("easy", "mid", "real") else "mid"
    n = max(1, min(30, int(d.get("n") or 5)))
    exam = bool(d.get("exam"))                    # 测试模式：答案不下发
    src = d.get("src") if d.get("src") in ("real", "ai", "mix") else "ai"
    # 真题模式没有难度档（真题不带难度标签，硬套是假的），改成按年份筛。
    # 用 str+isdigit 而不是裸 int()：前端年份选择器传个「2021年」就 500，
    # 而这是参数问题，该说清楚，不该崩。
    ys = str(d.get("year_min") or "").strip()
    year_min = max(0, min(2030, int(ys))) if ys.isdigit() else 0
    items = _drill_gen(get_db(), board, qtype, n, level, src, year_min)
    if not items:
        if src == "real":
            # 真题模式取不到 ≠ 题库没预热。**别混用下面那句**——那句承诺「后台正在出题，
            # 过两分钟再来」，而真题是死的，等一辈子也不会多出来。
            # 混合练时 qtype 是空的，按**板块**统计——原先直接给 0，会说成
            # 「真题库里没有这个题型的题」，可该板块明明有两千道，只是被年份筛没了
            # 或者都做完了。提示不能撒谎，否则用户按提示去放宽年份也不对症。
            if qtype:
                n_real = _real_count(get_db(), board, qtype)
                why = ("这个题型真题库里只有 %d 道" % n_real) if n_real \
                    else "真题库里没有这个题型的题"
            else:
                n_real = sum(_real_count(get_db(), board, t[0]) for t in DRILL_TYPES[board])
                why = ("这个板块 %d 道真题你都做过了" % n_real) if n_real \
                    else "真题库里还没有这个板块的题"
            if year_min:
                why += "（还限定了 %d 年以后）" % year_min
            return jsonify({"error": "「%s · %s」%s，换「AI 出题」或放宽年份吧。"
                                     % (board, qtype or "混合练", why)}), 404
        # 走到这儿说明这一格题库是空的。**绝不在请求里现场调 AI 补**——那要几分钟，
        # 前端只会表现为「点了没反应」。_bank_take 已经把补库排进后台了，这里只管说清楚。
        lv = DRILL_LV_NAME.get(level, level)
        return jsonify({"error": "「%s · %s」在「%s」难度下题库还没预热好，已经在后台出题了，"
                                 "过一两分钟回来再点。想现在就练，可以换「考场真实」难度，"
                                 "或先做本板块程序出题的题型。" % (board, qtype or "混合练", lv),
                        "warming": True}), 503
    pub = []
    for it in items:
        x = dict(it)
        if exam:
            x.pop("answer", None)
            x.pop("explain", None)
            x.pop("tip", None)
        pub.append(x)
    return jsonify({"board": board, "type": qtype, "level": level, "exam": exam,
                    "src": src, "year_min": year_min,
                    "coef": drill_coef(board, level),
                    "limit": DRILL_LIMIT.get(board, 60), "items": pub,
                    # 要 n 道只凑出 len(items) 道 = 题库这一格还没满，后台正在补。
                    # 照常让人先做，但要说一声，别让他以为题量设置没生效。
                    "short": max(0, n - len(items)),
                    "full": items if not exam else None,
                    "token": _drill_stash(items) if exam else ""})


# 测试模式下答案不下发，题目暂存在服务端（进程内，够用；重启就没了，反正是当次做的）
_DRILL_STASH = {}


def _drill_stash(items):
    tok = secrets.token_hex(8)
    _DRILL_STASH[tok] = items
    if len(_DRILL_STASH) > 400:                   # 别无限涨
        for k in list(_DRILL_STASH)[:100]:
            _DRILL_STASH.pop(k, None)
    return tok


@bp.post("/api/drill/done")
def drill_done():
    """交卷：判分、记成绩（用来算薄弱题型）、错题自动进错题本、**留一条完整记录**。"""
    d = request.get_json(silent=True) or {}
    board = (d.get("board") or "").strip()
    level = d.get("level") if d.get("level") in ("easy", "mid", "real") else "mid"
    mode = "exam" if d.get("exam") else "study"
    items = _DRILL_STASH.pop(d.get("token"), None) if d.get("token") else None
    if items is None:
        items = d.get("items") or []              # 背题模式：题目本来就在前端手里
    answers = d.get("answers") or {}
    if board not in DRILL_TYPES or not items:
        return jsonify({"error": "参数不对"}), 400

    db = get_db()
    results, secs = [], []
    for i, it in enumerate(items):
        your = (answers.get(str(i)) or answers.get(i) or it.get("your") or "").strip().upper()[:1]
        sec = float((d.get("seconds") or {}).get(str(i)) or it.get("seconds") or 0)
        ok = bool(your) and your == (it.get("answer") or "")
        secs.append(sec)
        # 难度按**题目自己的** level 记，不按请求参数。真题模式下题目是 level="real"，
        # 而请求里带的可能还是 easy/mid —— 记错档会把真题成绩混进 AI 题那一档的正确率，
        # 而 /api/drill/types 正是按 level 算「薄弱题型」排序的，会被带偏。
        db.execute("INSERT INTO drill_log(user_id,board,qtype,level,correct,seconds) VALUES(?,?,?,?,?,?)",
                   (uid(), board, it.get("qtype") or "", it.get("level") or level,
                    1 if ok else 0, sec))
        # 真题模式做的题**同时记进 real_attempts**，这样专项练和「历年真题」模块的进度是通的：
        # 在这边做过的题，去那边不会再当没做过推给你，反过来也一样。
        # 不这么记的话，同一道题会在两个入口各刷一遍，而「智能刷」最该练的题反而遇不上。
        if it.get("real_id") and your:
            try:
                # ⚠️ 背题模式下 items 整个来自客户端，real_id 也是 ——
                #    不校验就等于让前端随便往「历年真题」的进度表里写。那边靠
                #    real_attempts 判「这题做过没」，脏数据会让真该练的题再也不推给你。
                rid = int(it["real_id"])
                if db.execute("SELECT 1 FROM real_questions WHERE id=?", (rid,)).fetchone():
                    db.execute("INSERT INTO real_attempts(user_id,qid,choice,correct,seconds) "
                               "VALUES(?,?,?,?,?)", (uid(), rid, your, 1 if ok else 0, sec))
            except (ValueError, TypeError):
                pass                       # real_id 不是数字：客户端传脏了，跳过就是
            except sqlite3.OperationalError as e:
                # 只放过「新库还没导真题」。裸 sqlite3.Error 会把 database is locked、
                # 约束冲突一起吞掉，表现是作答记录静默丢失而日志一个字都没有。
                if "no such table" not in str(e):
                    raise
        results.append({"correct": ok, "your": your, "answer": it.get("answer") or "",
                        "explain": it.get("explain") or "", "tip": it.get("tip") or ""})
    for it, r in zip(items, results):
        it["your"], it["seconds"] = r["your"], 0
    added = _dtest_to_wrongq(db, items, results)
    ok_n = sum(1 for r in results if r["correct"])
    cur = db.execute(
        "INSERT INTO drill_records(user_id,board,qtype,level,mode,total,correct,seconds,items,answers) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (uid(), board, (d.get("type") or "").strip(), level, mode, len(items), ok_n,
         sum(secs), json.dumps(items, ensure_ascii=False), json.dumps(results, ensure_ascii=False)))
    db.commit()
    acc = ok_n / len(items) if items else 0
    coef = drill_coef(board, level)
    return jsonify({"ok": ok_n, "total": len(items), "wrong_added": added, "results": results,
                    "rid": cur.lastrowid, "coef": coef, "acc": round(acc, 2),
                    "vs": round(acc - coef, 2)})     # 和难度系数（预期得分率）比，高出多少


@bp.get("/api/drill/records")
def drill_records():
    rows = get_db().execute(
        "SELECT id,board,qtype,level,mode,total,correct,seconds,created_at FROM drill_records "
        "WHERE user_id=? ORDER BY id DESC LIMIT 60", (uid(),)).fetchall()
    lv = DRILL_LV_NAME
    return jsonify({"items": [dict(r, level_name=lv.get(r["level"], r["level"]),
                                   coef=drill_coef(r["board"], r["level"])) for r in rows]})


@bp.get("/api/drill/record/<int:rid>")
def drill_record(rid):
    r = get_db().execute("SELECT * FROM drill_records WHERE id=? AND user_id=?",
                         (rid, uid())).fetchone()
    if not r:
        return jsonify({"error": "记录不存在"}), 404
    d = dict(r)
    d["items"] = json.loads(d["items"] or "[]")
    d["answers"] = json.loads(d["answers"] or "[]")
    d["coef"] = drill_coef(r["board"], r["level"])
    return jsonify(d)


def _dtest_to_wrongq(db, items, results):
    """巩固测试做错的题自动进错题本：带题干、选项、正确答案、解析和板块。
       图形推理的题干是图，没法存成文字，改存一句说明 + 考点（错题本只认文字/图片）。"""
    n = 0
    for it, r in zip(items, results):
        if r.get("correct") or not r.get("your"):     # 答对的、没作答的都不收
            continue
        opts = "\n".join(it.get("options") or [])
        q = (it.get("q") or "").strip()
        # ⚠️ 这两个字段**有两种形状**，按形状分，别只判真假：
        #    figgen 出的图形题 figs 是 {seq, opts}（内联 SVG）、material 是
        #    {type:'table', headers, rows}；而真题的 figs 是文件名数组、material 是纯文本。
        #    原先 `m.get("title")` 碰上真题的字符串材料直接 AttributeError，
        #    /api/drill/done 整个 500，本次成绩和作答记录全丢（实测必现）。
        if isinstance(it.get("figs"), dict) and it["figs"].get("seq"):
            q = "【图形推理】" + q + "\n（图形题：%s。到「巩固测试记录」里可回看原图）" % (it.get("source") or "")
        elif it.get("material"):
            m = it["material"]
            title = m.get("title") if isinstance(m, dict) else ""
            body = "" if isinstance(m, dict) else str(m)[:600]
            q = "【材料题】材料：%s\n%s\n%s" % (title or "", body, q)
        text = (q + ("\n" + opts if opts else ""))[:2000]
        board = it.get("module") or "行测"
        # 同一道题别重复收
        dup = db.execute("SELECT 1 FROM wrong_questions WHERE user_id=? AND question=?", (uid(), text)).fetchone()
        if dup:
            continue
        db.execute("INSERT INTO wrong_questions(user_id,board,question,answer,qtype,points,note) "
                   "VALUES(?,?,?,?,?,?,?)",
                   (uid(), board, text,
                    "正确答案 %s。%s" % (r.get("answer") or "", it.get("explain") or ""),
                    it.get("source") or board, (it.get("source") or "").split("-")[-1],
                    "来自巩固测试（我选了 %s）" % (r.get("your") or "")))
        n += 1
    return n
