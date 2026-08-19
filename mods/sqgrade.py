"""社区主观题的**采分点**与批改口径。

和申论那套（mods/find.py）最大的不同在于采分点从哪来：

  申论    材料几千字、答案要自己从里面挖，所以采分点得靠 AI 逐块扫材料标定，
          而且标完要存库，否则同一份答案两次批改分数会飘。
  社区    参考答案**本身就是分点写的** ——

              1. 安抚接待：分别约谈高层老人、低层住户，倾听诉求…
              2. 政策宣讲：讲解四川省老旧小区加装电梯补贴政策…

          所以采分点**规则拆就行，不必让 AI 提炼**。少一次 AI 调用、少一处
          不确定性，而且拆出来的点逐字来自参考答案，谁都能核对。

两套骨架是从四道真题的参考答案上读出来的，不是我们编的：网格/纠纷类走
「分类建档 → 逐项处置 → 长效机制」，个人帮扶类走「接案 → 预估 → 分层介入 →
跟进结案」。练几次就成肌肉记忆 —— 这门考试主观题占 40 分，骨架比辞藻值钱。
"""
import re

# 顶层采分点的三种写法（四道真题各占其一两种）：
#   `1. 安抚接待：…`      2023 两道
#   `分类建档：建立网格隐患台账…`   2025 案例 1（无编号，靠「短标题 + 冒号」认）
#   `接案建立专业关系：耐心倾听…`   2025 案例 2
_NUMBERED = re.compile(r"^[\s　]*(\d{1,2})[.、．)）][\s　]*(.+)$")
_TITLED = re.compile(r"^[\s　]*([^：:，。；\s]{2,12})[：:][\s　]*(.*)$")
# 子要素：`（1）…` / `①…` —— 归到上一个采分点里，不单独算一个点
_SUB = re.compile(r"^[\s　]*[（(]\s*\d{1,2}\s*[）)]|^[\s　]*[①②③④⑤⑥⑦⑧⑨⑩]")

# 骨架。key 用于挂到题上；判定靠题面关键词，判不出来就不显示 —— **宁可不给，
# 也不要给错的骨架**，给错了比不给更误导。
SKELETONS = {
    "grid": {
        "name": "网格 / 纠纷处置类",
        "steps": ["分类建档：建台账，标风险等级、责任人、整改时限",
                  "逐项处置：一个隐患一条办法，写清联动了谁",
                  "长效机制：巡查制度、上报—处置—销号闭环、宣讲普法"],
        "hint": "题面里出现「排查发现 N 项问题」「矛盾激化」「多次报警」这类，走这条。",
    },
    "case": {
        "name": "个人帮扶 / 个案类",
        "steps": ["接案建立专业关系：倾听情绪、建立信任",
                  "问题预估：核心问题是什么（认知 / 能力 / 支持网络）",
                  "分层介入：心理疏导 + 资源链接 + 支持网络，一层一条",
                  "跟进结案：回访周期、建档归档"],
        "hint": "题面聚焦**一个人**（独居老人、失业青年、困境儿童）时走这条。",
    },
}
_GRID_KW = ("网格", "隐患", "排查", "占道", "纠纷", "矛盾", "上访", "整治", "加装电梯", "调解")
_CASE_KW = ("小李", "王大爷", "独居", "失业", "情绪低落", "自我否定", "求助社区", "个案")


def skeleton_of(stem):
    """这道案例题该套哪套骨架。判不出来返回 None（前端就不显示）。"""
    s = stem or ""
    g = sum(1 for k in _GRID_KW if k in s)
    c = sum(1 for k in _CASE_KW if k in s)
    if g == c:
        return None
    return "grid" if g > c else "case"


def split_points(answer, full):
    """把参考答案拆成采分点。返回 [{point, detail, score, subs}]。

    拆不出两个以上的点就返回空 —— **拆不动就说拆不动**，让调用方退回
    「只给参考答案对照、不判分」，而不是硬凑一个点然后把满分全压上去。
    """
    pts = []
    for raw in (answer or "").splitlines():
        line = raw.replace("\x0c", "").rstrip()
        if not line.strip():
            continue
        if _SUB.match(line) and pts:                 # 子要素归上一个点
            pts[-1]["subs"].append(line.strip())
            continue
        m = _NUMBERED.match(line)
        body = m.group(2) if m else None
        if body is None:
            m2 = _TITLED.match(line)
            # 没编号时要求「短标题 + 冒号」，否则正文里随便一个冒号都成新采分点
            body = m2.group(0).strip() if m2 else None
        if body is None:
            # 续行（PDF 折行造成的）。**有子要素时要接到最后一个子要素后面**，
            # 不能一律接到点的正文上 —— 否则「（1）…上门更换线路，张贴安全」的下半句
            # 「提示，纳入每周巡查清单」会跑到点的正文里，读出来前言不搭后语。
            if pts and pts[-1]["subs"]:
                pts[-1]["subs"][-1] += line.strip()
            elif pts:
                pts[-1]["detail"] += line.strip()
            continue
        cut = re.search(r"[：:]", body)
        head = body[:cut.start()].strip() if cut else body[:14].strip()
        tail = body[cut.end():].strip() if cut else body.strip()
        pts.append({"point": head or body[:14], "detail": tail, "subs": []})

    if len(pts) < 2:
        return []
    # 分值：平均分，取到 0.5；余数补给第一个点，保证加起来正好是满分
    n = len(pts)
    each = round(full / n * 2) / 2
    for p in pts:
        p["score"] = each
        p["detail"] = (p["detail"] + ("　" if p["detail"] and p["subs"] else "")
                       + "　".join(p["subs"])).strip()
    pts[0]["score"] = round(full - each * (n - 1), 1)
    if pts[0]["score"] <= 0:                         # 平均分取整取过头了，退回严格均分
        for p in pts:
            p["score"] = round(full / n, 2)
    return pts


def rubric_text(points):
    """给 AI 的采分点清单。逐字来自参考答案，**不许它另立点**。"""
    return "\n".join(
        "%d. %s（%g 分）：%s" % (i + 1, p["point"], p["score"], (p["detail"] or "")[:120])
        for i, p in enumerate(points))


def total_of(result):
    """把逐点得分加起来。AI 给的总分不算数 —— 它经常和逐点对不上。"""
    return round(sum(float(p.get("got") or 0) for p in (result or [])), 1)


# ---------------------------------------------------------------- 批改
SYS = ("你是社区工作者招聘考试的阅卷老师。只输出 JSON，不要解释。"
       "评分**只能照给定的采分点**，不许自己另立点、不许增删条数。")

PROMPT = """【题目】%(stem)s

【本题满分】%(full)g 分

【标准答案采分点】（阅卷组已定，考生看不到；**必须逐条照抄这几个点评分**）
%(rubric)s

【考生答案】
%(answer)s

逐条对照，一个采分点一条，顺序不变。判定分三档：
  hit     写到了这一点的核心做法 → got 给满
  partial 沾边：提到了方向但没写出具体做法（比如只说「上门劝导」却没写联合执法）
          → got 给一半，**这是这门考试最常见的丢分方式，务必和 miss 区分开**
  miss    整块没写 → got 给 0

只输出 JSON：{"points":[{"name":"采分点原话（照抄）","max":该点分值,"got":实际得分,
"verdict":"hit|partial|miss","yours":"考生原文里对应这一点的话（没写到填空字符串）",
"why":"一句话说清为什么这么判"}],"advice":"一句最该改的建议"}"""


def build_prompt(stem, answer, points, full):
    return PROMPT % {"stem": (stem or "")[:900], "full": full,
                     "rubric": rubric_text(points), "answer": (answer or "")[:2500]}


def merge(points, raw):
    """把 AI 的判定合回采分点。**以我们的点为准**：AI 少给、多给、改名一律不认，
       按序号对齐；对不上的点当 miss 处理，绝不因为 AI 漏了一条就少扣分。"""
    got = {i: r for i, r in enumerate(raw or []) if isinstance(r, dict)}
    out = []
    for i, p in enumerate(points):
        r = got.get(i) or {}
        v = str(r.get("verdict") or "").lower()
        v = v if v in ("hit", "partial", "miss") else "miss"
        # 分数由**我们**按判定算，不采信 AI 报的 got —— 它经常和 verdict 对不上
        sc = p["score"] if v == "hit" else (round(p["score"] / 2, 2) if v == "partial" else 0)
        out.append({"name": p["point"], "detail": p["detail"], "max": p["score"],
                    "got": sc, "verdict": v,
                    "yours": str(r.get("yours") or "")[:200],
                    "why": str(r.get("why") or "")[:160]})
    return out


# ---------------------------------------------------------------- 公文写作（15 分）
# 公文的参考答案是一整篇**范文**，不是分点写的，所以拆不出采分点 —— 改成按
# **结构部件**给分。这六条不是我们编的，是从两篇真题范文上读出来的（2023 重阳慰问
# 通知、2025 网格员季度推进会通知），两篇的骨架完全一致：
#   标题 → 主送机关 → 开头缘由 → 分条事项 → 工作要求 → 落款与日期
GONGWEN_POINTS = [
    {"point": "标题", "detail": "「关于＋事由＋文种」，不加书名号；如"
                                "「关于开展重阳节高龄老人走访慰问活动的通知」"},
    {"point": "主送机关", "detail": "顶格写、后加冒号；如「社区全体工作人员、网格员：」"},
    {"point": "开头缘由", "detail": "先讲依据/目的，再用「现将有关事项通知如下：」收束引出下文"},
    {"point": "分条事项", "detail": "用「一、二、三、」分条写清时间、地点、对象、内容"},
    {"point": "工作要求", "detail": "单列一条讲落实要求（分组包片、时限、结果上报）"},
    {"point": "落款与日期", "detail": "**以社区居委会/社区党委名义**各自成行，"
                                      "不能签个人姓名"},
]
GONGWEN_FULL = 15.0


def gongwen_points(full=GONGWEN_FULL):
    """公文的采分点。分值均摊到 0.5，余数补第一条。"""
    n = len(GONGWEN_POINTS)
    each = round(full / n * 2) / 2
    pts = [dict(p, score=each, subs=[]) for p in GONGWEN_POINTS]
    pts[0]["score"] = round(full - each * (n - 1), 1)
    return pts


def format_issues(content, doctype="通知"):
    """跑现成的应用文格式检查器。**它是纯代码判定，不花 AI 一次调用**，
       而且判据都有真题实证（见 mods/yycheck 的文件头）。"""
    try:
        from mods.yycheck import check_all
    except Exception:
        return []
    out = []
    for e in check_all(content, doctype) or []:
        if isinstance(e, dict):
            out.append({"check": str(e.get("check") or e.get("where") or "格式")[:40],
                        "bad": str(e.get("bad") or "")[:120],
                        "good": str(e.get("good") or "")[:120],
                        "why": str(e.get("why") or "")[:160]})
    return out
