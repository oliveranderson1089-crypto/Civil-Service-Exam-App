#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图形推理 / 资料分析的**程序化出题**（巩固测试与题库·模拟卷共用）。

为什么不交给 AI：
· 图形推理——它画得出 SVG，但「图形规律」和它自己给的答案经常对不上，自己骗自己；
· 资料分析——它会写「根据材料…」却根本不给材料，或者数字前后矛盾。
这里由代码按规律构造图形 / 造一份内部自洽的统计数据，**答案是算出来的，必然正确**。
"""
import math
import random
import re

# 难度分三档，**真正改变题目**（不是只换个标签）：
#   easy 入门 —— 一步就能算、数字整、干扰项差得远
#   mid  进阶 —— 常规两步、数字仍整
#   real 考场真实 —— 多步/需要技巧、数字更「脏」（要估算）、干扰项贴着常见错法造
LEVELS = ("easy", "mid", "real")


def _lv(level):
    return level if level in LEVELS else "mid"

# ---------------------------------------------------------------- 图形推理：程序化出题
# 不让 AI 画图：它画得出 SVG，但「图形规律」和它自己给的答案经常对不上。
# 这里由代码按规律生成图形，**答案是构造出来的，必然正确**；干扰项也是按「差一个属性」造的。
_FIG_STROKE = 'fill="none" stroke="currentColor" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"'


def _fig(inner):
    return '<svg viewBox="0 0 88 88" xmlns="http://www.w3.org/2000/svg" class="fg">%s</svg>' % inner


def _fig_rot(pts, deg, cx=44.0, cy=44.0):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    return [((x - cx) * ca - (y - cy) * sa + cx, (x - cx) * sa + (y - cy) * ca + cy) for x, y in pts]


def _fig_poly(pts):
    return '<polygon points="%s" %s/>' % (" ".join("%.1f,%.1f" % p for p in pts), _FIG_STROKE)


_FIG_L = [(26, 18), (64, 18), (64, 34), (42, 34), (42, 70), (26, 70)]      # 不对称的 L 形


def _figq_rotate():
    seq = [_fig(_fig_poly(_fig_rot(_FIG_L, d))) for d in (0, 90, 180)]
    right = _fig(_fig_poly(_fig_rot(_FIG_L, 270)))
    wrong = [_fig(_fig_poly(_fig_rot(_FIG_L, 0))),
             _fig(_fig_poly(_fig_rot(_FIG_L, 90))),
             _fig(_fig_poly([(88 - x, y) for x, y in _fig_rot(_FIG_L, 270)]))]   # 镜像，旋转得不到
    return seq, right, wrong, "图形每次顺时针旋转 90°：0°→90°→180°，问号处应是 270°。注意有个选项是它的镜像——镜像靠旋转是得不到的。", "图形推理-位置变化-旋转"


def _figq_dots():
    def f(n):
        s = '<rect x="10" y="10" width="68" height="68" rx="8" %s/>' % _FIG_STROKE
        for i in range(n):
            a = math.radians(-90 + i * 360.0 / n)
            s += '<circle cx="%.1f" cy="%.1f" r="6" fill="currentColor"/>' % (44 + 24 * math.cos(a), 44 + 24 * math.sin(a))
        return _fig(s)
    return [f(2), f(3), f(4)], f(5), [f(3), f(4), f(6)], "框里的黑点数依次是 2、3、4，成等差数列，问号处应有 5 个。", "图形推理-数量规律-元素数"


def _figq_sides():
    def f(n):
        pts = [(44 + 30 * math.cos(math.radians(-90 + i * 360.0 / n)),
                44 + 30 * math.sin(math.radians(-90 + i * 360.0 / n))) for i in range(n)]
        return _fig(_fig_poly(pts))
    return [f(3), f(4), f(5)], f(6), [f(5), f(7), f(8)], "边数依次为 3、4、5，问号处应是六边形。", "图形推理-数量规律-边数"


def _figq_lines():
    def f(n):
        s = '<circle cx="44" cy="44" r="34" %s/>' % _FIG_STROKE
        for i in range(n):
            a = math.radians(-90 + i * 360.0 / n)
            s += ('<line x1="44" y1="44" x2="%.1f" y2="%.1f" stroke="currentColor" '
                  'stroke-width="2.6" stroke-linecap="round"/>' % (44 + 32 * math.cos(a), 44 + 32 * math.sin(a)))
        return _fig(s)
    return [f(2), f(3), f(4)], f(5), [f(4), f(6), f(3)], "圆里的线段数依次为 2、3、4，问号处应有 5 条。", "图形推理-数量规律-线条数"


def _figq_regions():
    def f(n):
        s = '<rect x="10" y="24" width="68" height="40" %s/>' % _FIG_STROKE
        for i in range(1, n):
            x = 10 + 68.0 * i / n
            s += ('<line x1="%.1f" y1="24" x2="%.1f" y2="64" stroke="currentColor" stroke-width="2.4"/>' % (x, x))
        return _fig(s)
    return [f(1), f(2), f(3)], f(4), [f(3), f(5), f(2)], "封闭区域数依次为 1、2、3，问号处应有 4 个封闭区域。", "图形推理-数量规律-面(封闭区域)"


# ---------------------------------------------------------------- 资料分析：程序化出题
# 同样不让 AI 出：它会写「根据材料…」却根本不给材料，或者数字对不上。
# 这里先造一份**内部自洽的统计数据**（等差设计，比重/增长率都是整数），再由代码算出答案。
_ZL_CITY = ["A 市", "B 市", "C 市", "甲市", "乙市"]


# 资料分析的考点按**讲义目录**排（第二章 常考概念，循序渐进）：
#   基期量 → 现期量 → 增长率 → 增长量 → 间隔增长 → 年均增长 → 混合增长
#   → 倍数与翻番 → 比重 → 比重变化 → 平均数 → 比较大小
# 难度分档 = 要几步：入门直接读数/一步；进阶两步；真实多步或最容易搞混的那几个
_ZL_ORDER = ["基期量", "现期量", "增长率", "增长量", "间隔增长", "年均增长", "混合增长",
             "倍数与翻番", "比重", "比重变化", "平均数", "比较大小"]
_ZL_BY_LEVEL = {
    "easy": ["现期量", "基期量", "增长量", "比重", "倍数与翻番"],
    "mid":  ["基期量", "增长率", "增长量", "倍数与翻番", "比重", "平均数", "间隔增长"],
    "real": ["年均增长", "混合增长", "比重变化", "比较大小", "间隔增长", "增长率"],
}


def _gen_ziliao(n_q=1, level="mid"):
    """造一份材料 + n_q 道题（题目共用同一份材料）。数字都是设计好的，答案精确。"""
    lv = _lv(level)
    city = random.choice(_ZL_CITY)
    rate = random.choice([4, 5, 6, 8] if lv != "real" else [3, 7, 9, 11])   # 2024 同比增速（%）
    g2 = random.choice([2500, 3000, 3200, 3600, 4000])                      # 2023 年 GDP
    d = g2 * rate // 100                                # 等差步长，保证增速是整数
    years = ["2021", "2022", "2023", "2024"]
    gdp = [g2 - 2 * d, g2 - d, g2, g2 + d]
    pct3 = random.choice([55, 60, 65])                  # 2024 年三产占比（整数）
    s3 = gdp[3] * pct3 // 100
    while gdp[3] * pct3 % 100:                          # 保证三产是整数
        gdp = [x + 1 for x in gdp]
        s3 = gdp[3] * pct3 // 100
    third = [round(gdp[i] * (pct3 - 6 + 2 * i) / 100) for i in range(3)] + [s3]
    first = [round(g * 0.05) for g in gdp]
    second = [gdp[i] - first[i] - third[i] for i in range(4)]
    pop = [round(gdp[i] / random.choice([6, 8, 10])) for i in range(1)] * 4   # 人口（万人），四年不变太假
    base_pop = random.choice([600, 800, 1000])
    pop = [base_pop + 10 * i for i in range(4)]         # 人口逐年 +10 万，算人均用

    mtype = random.choice(["table", "bar", "line"])
    if mtype == "table":
        material = {"type": "table", "title": "%s 2021—2024 年地区生产总值构成" % city, "unit": "亿元",
                    "headers": ["年份", "地区生产总值", "第一产业", "第二产业", "第三产业", "常住人口(万人)"],
                    "rows": [[years[i], gdp[i], first[i], second[i], third[i], pop[i]] for i in range(4)]}
    else:
        material = {"type": mtype, "title": "%s 2021—2024 年地区生产总值与第三产业增加值" % city,
                    "unit": "亿元", "labels": years,
                    "series": [{"name": "地区生产总值", "data": gdp},
                               {"name": "第三产业增加值", "data": third}]}

    pool = _ZL_BY_LEVEL[lv]
    kinds = random.sample(pool, k=min(n_q, len(pool)))
    while len(kinds) < n_q:                       # 要的题比池子里的题型多，就允许重复
        kinds.append(random.choice(pool))
    out = []
    for k in kinds:
        if k == "现期量":
            ans = "%d 亿元" % gdp[3]
            wrong = ["%d 亿元" % gdp[2], "%d 亿元" % (gdp[3] + d), "%d 亿元" % gdp[0]]
            q = "2024 年 %s 地区生产总值为多少亿元？" % city
            ex = "直接从材料里读：2024 年地区生产总值 = %d 亿元。**现期量题不用算，别自己给自己加戏**。" % gdp[3]
        elif k == "基期量":
            # 基期 = 现期 ÷ (1+增长率)。这里 2023 的值材料里就有，考的是「别用现期×(1−r)」
            ans = "%d 亿元" % gdp[2]
            # ⚠️ gdp[1] 和 gdp[3]−2d 恒等（都是 g2−d），并排放就是两个一样的选项。多给几个候选，组装时去重。
            wrong = ["%d 亿元" % round(gdp[3] * (1 - rate / 100)),   # 经典错法：现期×(1−r)
                     "%d 亿元" % gdp[1], "%d 亿元" % gdp[0],
                     "%d 亿元" % (gdp[3] + d), "%d 亿元" % round(gdp[3] / (1 + 2 * rate / 100))]
            q = "2024 年 %s 地区生产总值为 %d 亿元，同比增长 %d%%。2023 年为多少亿元？" % (city, gdp[3], rate)
            ex = ("基期量 = 现期量 ÷ (1 + 增长率) = %d ÷ (1+%d%%) = %d 亿元。\n"
                  "**最经典的错法是「现期 × (1 − 增长率)」= %d 亿元** —— 那是错的，"
                  "因为增长率的分母是基期，不是现期。"
                  % (gdp[3], rate, gdp[2], round(gdp[3] * (1 - rate / 100))))
        elif k == "增长率":
            ans = "%d%%" % rate
            wrong = ["%d%%" % (rate + 2), "%d%%" % max(1, rate - 2),
                     "%.1f%%" % ((gdp[3] - gdp[2]) / gdp[3] * 100)]   # 分母用了现期
            q = "2024 年 %s 地区生产总值同比增长约：" % city
            ex = ("增长率 =（现期 − 基期）÷ **基期** =（%d − %d）÷ %d = %d%%。\n"
                  "**除的是去年，不是今年** —— 拿今年当分母算出来是 %.1f%%，这是最经典的坑。"
                  % (gdp[3], gdp[2], gdp[2], rate, (gdp[3] - gdp[2]) / gdp[3] * 100))
        elif k == "增长量":
            ans = "%d 亿元" % d
            # ⚠️ gdp[3]−gdp[1] 恒等于 2d，和 d*2 是同一个数。多给候选，组装时去重。
            wrong = ["%d 亿元" % (d * 2), "%d 亿元" % round(d / 2), "%d 亿元" % (gdp[3] - gdp[0]),
                     "%d 亿元" % (d + 10), "%d 亿元" % max(1, d - 10)]
            q = "2024 年 %s 地区生产总值比上年增加了多少亿元？" % city
            ex = "增长量 = 现期 − 基期 = %d − %d = %d 亿元。直接减，别去套增长率公式绕远路。" % (gdp[3], gdp[2], d)
        elif k == "间隔增长":
            # 间隔增长率：2024 相对 2022（隔一年）。r_间隔 = r1 + r2 + r1·r2
            r1 = (gdp[2] - gdp[1]) / gdp[1]
            r2 = (gdp[3] - gdp[2]) / gdp[2]
            gap = (gdp[3] - gdp[1]) / gdp[1] * 100
            ans = "%.1f%%" % gap
            wrong = ["%.1f%%" % ((r1 + r2) * 100),          # 只把两年增长率相加（漏了乘积项）
                     "%.1f%%" % (gap + 3), "%.1f%%" % max(0.5, gap - 3)]
            q = "2024 年 %s 地区生产总值比 2022 年增长约：" % city
            ex = ("间隔增长率 = r₁ + r₂ + r₁×r₂ = %.1f%% + %.1f%% + %.1f%%×%.1f%% = %.1f%%。\n"
                  "**不能直接把两年的增长率相加**（那样得 %.1f%%）—— 少了 r₁×r₂ 这一项。"
                  % (r1 * 100, r2 * 100, r1 * 100, r2 * 100, gap, (r1 + r2) * 100))
        elif k == "年均增长":
            ans = "%d 亿元" % d
            wrong = ["%d 亿元" % (d * 2), "%d 亿元" % round((gdp[3] - gdp[0]) / 4),   # 除以 4 而不是 3
                     "%d 亿元" % round(d * 1.5)]
            q = "2021—2024 年 %s 地区生产总值的年均增长量约为：" % city
            ex = ("年均增长量 =（末年 − 首年）÷ **年份差** =（%d − %d）÷ 3 = %d 亿元。\n"
                  "**年份差 = 末年 − 首年**：2021→2024 是 **3**，不是 4 个数就除以 4（那样得 %d）。"
                  % (gdp[3], gdp[0], d, round((gdp[3] - gdp[0]) / 4)))
        elif k == "混合增长":
            # 整体增速必在两部分增速之间（十字交叉的核心结论）
            r1 = round((third[3] - third[2]) / third[2] * 100, 1)     # 三产增速
            other2, other3 = gdp[2] - third[2], gdp[3] - third[3]
            r2 = round((other3 - other2) / other2 * 100, 1)           # 其余部分增速
            lo, hi = (min(r1, r2), max(r1, r2))
            ans = "介于 %.1f%% 和 %.1f%% 之间" % (lo, hi)
            wrong = ["等于两者的平均数 %.1f%%" % ((r1 + r2) / 2),
                     "大于 %.1f%%" % hi, "小于 %.1f%%" % lo]
            q = ("2024 年 %s 第三产业增速为 %.1f%%，其余产业合计增速为 %.1f%%。"
                 "则地区生产总值的增速：" % (city, r1, r2))
            ex = ("**混合增长率必定介于两个部分之间**（十字交叉法的核心结论），"
                  "而且更靠近**权重大**的那一边 —— 但绝不会等于简单平均数 %.1f%%，"
                  "除非两部分的量正好相等。" % ((r1 + r2) / 2))
        elif k == "倍数与翻番":
            times = third[3] / first[3]
            ans = "%.1f 倍" % times
            wrong = ["%.1f 倍" % (times - 1),          # 「是几倍」和「多几倍」差 1
                     "%.1f 倍" % (times + 1), "%.1f 倍" % (times / 2)]
            q = "2024 年 %s 第三产业增加值约为第一产业的多少倍？" % city
            ex = ("倍数 = A ÷ B = %d ÷ %d ≈ %.1f 倍。\n"
                  "**「是几倍」用除，「多几倍」要再减 1**（那是 %.1f 倍）—— 一字之差。\n"
                  "另外「翻一番」= ×2，「翻两番」= ×4（不是 ×3）。"
                  % (third[3], first[3], times, times - 1))
        elif k == "比重":
            ans = "%d%%" % pct3
            wrong = ["%d%%" % (pct3 - 5), "%d%%" % (pct3 + 5),
                     "%.1f%%" % (third[3] / gdp[2] * 100)]          # 分母用错年份
            q = "2024 年 %s 第三产业增加值占地区生产总值的比重约为：" % city
            ex = ("比重 = 部分 ÷ 整体 = %d ÷ %d = %d%%。\n"
                  "**先看清年份和单位** —— 这类题错的多半不是算错，是看错行。" % (third[3], gdp[3], pct3))
        elif k == "比重变化":
            rel = (third[3] / gdp[3] - third[2] / gdp[2]) / (third[2] / gdp[2]) * 100
            ans = "提高约 2 个百分点"
            wrong = ["提高约 4 个百分点", "下降约 2 个百分点",
                     "提高约 %.1f%%" % rel]                       # 混淆「百分点」与「%」
            q = "2024 年 %s 第三产业增加值占地区生产总值的比重，与上年相比：" % city
            ex = ("2024 年占比 %d%%，2023 年占比 %d%%，相差 %d − %d = **2 个百分点**。\n"
                  "**「百分点」是两个百分数直接相减**，不是相对变化率（那是 %.1f%%）。"
                  % (pct3, pct3 - 2, pct3, pct3 - 2, rel))
        elif k == "平均数":
            avg = gdp[3] / pop[3]                    # 人均 GDP（亿元/万人 = 万元/人）
            ans = "%.2f 万元" % avg
            wrong = ["%.2f 万元" % (gdp[3] / pop[0]),      # 人口用错年份
                     "%.2f 万元" % (gdp[2] / pop[3]),      # GDP 用错年份
                     "%.2f 万元" % (avg * 1.5)]
            q = "2024 年 %s 的人均地区生产总值约为多少万元？" % city
            ex = ("人均 = 总量 ÷ 人口 = %d 亿元 ÷ %d 万人 = %.2f 万元/人。\n"
                  "**分子分母必须是同一年** —— 错位取数是这类题最常见的失分点。"
                  % (gdp[3], pop[3], avg))
        else:   # 比较大小
            r_gdp = (gdp[3] - gdp[2]) / gdp[2] * 100
            r_3rd = (third[3] - third[2]) / third[2] * 100
            faster = "第三产业" if r_3rd > r_gdp else "地区生产总值"
            ans = "%s 增速更快" % faster
            wrong = ["%s 增速更快" % ("地区生产总值" if faster == "第三产业" else "第三产业"),
                     "两者增速相同", "无法判断"]
            q = "2024 年 %s 第三产业增加值与地区生产总值相比，哪个同比增速更快？" % city
            ex = ("地区生产总值增速 %.1f%%，第三产业增速 %.1f%% → **%s 更快**。\n"
                  "技巧：**比重上升 ⇔ 部分的增速快于整体**。这题三产比重在上升，"
                  "所以不用算也知道三产更快。"
                  % (r_gdp, r_3rd, faster))

        # 干扰项去重：撞上答案、或彼此相同的都剔掉（实测「基期量」「增长量」有必然重复的构造）。
        # 剔完不够 3 个就补 —— 宁可题少一个花样，也不能出现两个一样的选项。
        seen, keep = {ans}, []
        for w in wrong:
            if w not in seen:
                seen.add(w)
                keep.append(w)
            if len(keep) == 3:
                break
        _guard = 0
        while len(keep) < 3 and _guard < 20:          # 极端情况兜底：在答案上做数值扰动造一个
            _guard += 1
            m = re.search(r"-?\d+\.?\d*", ans)
            if not m:
                break
            v = float(m.group()) * (1 + 0.07 * (len(keep) + 1) * random.choice([1, -1]))
            cand = ans[:m.start()] + (("%d" % round(v)) if "." not in m.group() else ("%.1f" % v)) + ans[m.end():]
            if cand not in seen:
                seen.add(cand)
                keep.append(cand)
        opts = keep[:3] + [ans]
        random.shuffle(opts)
        out.append({
            "q": q,
            "options": ["%s. %s" % ("ABCD"[i], o) for i, o in enumerate(opts)],
            "answer": "ABCD"[opts.index(ans)], "explain": ex,
            "module": "资料分析", "source": "资料分析-" + k, "material": material, "level": lv,
        })
    return out


def _figq_shift():
    """位置变化 · 平移：黑点沿格子逐格移动 —— 位置变、形状不变。"""
    def f(i):
        cells = ""
        for r in range(3):
            for c in range(3):
                cells += ('<rect x="%d" y="%d" width="22" height="22" %s/>'
                          % (11 + c * 22, 11 + r * 22, _FIG_STROKE))
        k = i % 9
        cells += ('<circle cx="%.1f" cy="%.1f" r="7" fill="currentColor"/>'
                  % (22 + (k % 3) * 22, 22 + (k // 3) * 22))
        return _fig(cells)
    seq = [f(0), f(1), f(2)]
    right = f(3)
    wrong = [f(4), f(5), f(0)]           # 位置差一格 / 差两格 / 回到起点
    return seq, right, wrong, "黑点在九宫格里**按顺序逐格平移**（左上→右移一格→再右移）。问号处应是第 4 格的位置。", "图形推理-位置变化-平移"


def _figq_style():
    """样式规律 · 加减同异：第三个图 = 前两个图「去同存异」（相同的抵消，不同的保留）。"""
    def grid(bits):
        cells = ""
        for r in range(2):
            for c in range(2):
                cells += ('<rect x="%d" y="%d" width="30" height="30" %s/>'
                          % (13 + c * 31, 13 + r * 31, _FIG_STROKE))
                if bits[r * 2 + c]:
                    cells += ('<line x1="%d" y1="%d" x2="%d" y2="%d" %s/>'
                              % (18 + c * 31, 18 + r * 31, 38 + c * 31, 38 + r * 31, _FIG_STROKE))
        return _fig(cells)
    # ⚠️ and/or/not 这三种「错法」在某些 bit 组合下会**撞成同一个图**（比如 a、b 无交集时
    #    and 全 0，而 or 恰好 == xor）。所以：先摇出一组让四个图两两不同的 a、b，摇不到就换定式。
    def four(a, b):
        x = [a[i] ^ b[i] for i in range(4)]
        cands = [x,
                 [a[i] & b[i] for i in range(4)],
                 [a[i] | b[i] for i in range(4)],
                 [1 - v for v in x]]
        return (x, cands) if len({tuple(c) for c in cands}) == 4 else (None, None)

    a = b = xor = None
    for _ in range(40):
        a = [random.randint(0, 1) for _ in range(4)]
        b = [random.randint(0, 1) for _ in range(4)]
        xor, cands = four(a, b)
        if xor:
            break
    if not xor:                                      # 兜底：这一组必然四图互异
        a, b = [1, 1, 0, 1], [1, 0, 1, 0]
        xor, cands = four(a, b)
    seq = [grid(a), grid(b)]
    right = grid(xor)
    wrong = [grid(c) for c in cands[1:]]     # 求同 / 相加 / 取反 —— 三种典型错法
    return seq, right, wrong, ("**去同存异**：两个格子里的斜线，**位置相同的抵消掉、只剩不同的**。"
                               "干扰项分别是「求同（都有才留）」「相加（有一个就留）」和「取反」。"), "图形推理-样式规律-加减同异"


def _figq_symmetry():
    """属性规律 · 对称性：一组图形都是轴对称的，选项里只有一个也是。"""
    def sym(n, rot=0):        # 正 n 边形：轴对称
        pts = []
        for i in range(n):
            a = math.radians(-90 + rot + i * 360.0 / n)
            pts.append((44 + 30 * math.cos(a), 44 + 30 * math.sin(a)))
        return _fig(_fig_poly(pts))

    def asym():               # 不规则四边形：不对称
        return _fig(_fig_poly([(16, 20), (70, 14), (60, 68), (26, 54)]))

    def asym2():
        return _fig(_fig_poly([(20, 16), (68, 30), (44, 72), (18, 50)]))

    def asym3():
        return _fig(_fig_poly([(14, 40), (52, 12), (72, 58), (30, 70)]))

    seq = [sym(3), sym(4), sym(5)]
    right = sym(6)
    wrong = [asym(), asym2(), asym3()]
    return seq, right, wrong, ("这一组图形**都是轴对称图形**（正三角形、正方形、正五边形）。"
                               "问号处也必须是轴对称的 —— 其余三个选项都是不规则图形，一条对称轴都没有。"), "图形推理-属性规律-对称性"


# 图形推理按**讲义目录**的四大类规律归位（第一章 图形推理）：
#   位置变化（旋转/平移）→ 样式规律（加减同异）→ 属性规律（对称性）→ 数量规律（点/线/面/素）
# 目录里还有「元素分布」和「立体图形」—— 立体图形（折纸盒/三视图）没法用二维 SVG 可靠构造，
# 硬做出来的题答案站不住，宁可不出（专项练页面会注明）。
_FIG_CAT = {
    "位置变化": [_figq_rotate, _figq_shift],
    "样式规律": [_figq_style],
    "属性规律": [_figq_symmetry],
    "数量规律": [_figq_dots, _figq_sides, _figq_lines, _figq_regions],
}
_FIG_ORDER = ["位置变化", "样式规律", "属性规律", "数量规律"]
# 难度 = 规律好不好看出来：入门给最直观的，真实档给最隐蔽的（线条数/封闭区域是真题重灾区）
_FIG_BY_LEVEL = {
    "easy": [_figq_dots, _figq_sides, _figq_rotate, _figq_shift],
    "mid":  [_figq_rotate, _figq_shift, _figq_dots, _figq_sides, _figq_style, _figq_symmetry],
    "real": [_figq_style, _figq_lines, _figq_regions, _figq_rotate, _figq_symmetry],
}


def _gen_figure_q(kind=None, level="mid"):
    """出一道图形推理：答案由构造保证正确，AI 碰都不碰。
       kind 可以是目录里的大类（位置变化/样式规律/属性规律/数量规律）。"""
    lv = _lv(level)
    pool = _FIG_CAT.get(kind) or _FIG_BY_LEVEL[lv]
    seq, right, wrong, explain, source = random.choice(pool)()
    if lv == "easy":
        # 入门：干扰项只留「差一个属性」的，把镜像这种最容易看走眼的去掉
        wrong = [w for w in wrong if "镜像" not in explain][:3] or wrong[:3]
    opts = list(wrong)[:3] + [right]
    random.shuffle(opts)
    return {
        "q": "从所给的四个选项中，选择最合适的一个填入问号处，使之呈现一定的规律性。",
        "options": [], "figs": {"seq": seq, "opts": opts},
        "answer": "ABCD"[opts.index(right)], "explain": explain,
        "module": "判断推理", "source": source, "level": lv,
    }



# ---------------------------------------------------------------- 数量关系：程序化出题
# 同样不交给 AI：它算错的概率高得离谱（尤其排列组合、容斥、浓度），而且答案和解析常常自相矛盾。
# 这里**先定答案、再倒推题面**，数字都挑成能整除的，保证：算得出、算得整、解析和答案必然一致。
# 每类都附「秒杀技巧」——数量关系提分靠的就是这个，不是硬算。
def _mq(q, ans, wrong, ex, kind, tip, unit="", step=1, level="mid"):
    """选项统一在这里格式化。三条硬约束（前两条是实测踩出来的）：
       · 四个选项**必须互不相同** —— 干扰项撞上答案，这题就有两个正确选项了；
       · 四个选项**格式必须一致** —— 「29.0% / 23.0% / 35.0% / 26%」等于把答案写脸上；
       · **干扰项的贴近程度按难度走** —— 入门把干扰项推远（一眼排除），
         考场真实则贴着常见错法（用平均数、用错公式），逼你真算。"""
    lv = _lv(level)
    if lv == "easy":                 # 入门：把干扰项推开，别在几个相近数之间纠结
        wrong = [w + (i + 1) * step * 2 for i, w in enumerate(float(x) for x in wrong)]
    vals = [float(ans)]
    for w in wrong:                       # 撞车的就挪开，直到四个都不一样
        v, guard = float(w), 0
        while any(abs(v - x) < 1e-9 for x in vals) and guard < 40:
            v += step
            guard += 1
        vals.append(v)
    dec = 0 if all(abs(v - round(v)) < 1e-9 for v in vals) else 1     # 有小数就全带一位
    fmt = (lambda v: "%d%s" % (round(v), unit)) if not dec else (lambda v: "%.1f%s" % (v, unit))
    opts = [fmt(v) for v in vals]
    right = opts[0]
    random.shuffle(opts)
    return {
        "q": q,
        "options": ["%s. %s" % ("ABCD"[i], o) for i, o in enumerate(opts)],
        "answer": "ABCD"[opts.index(right)],
        # 解析里的答案由这里统一填（{ans}），保证和选项**一个写法**
        "explain": ex.replace("{ans}", right),
        "module": "数量关系", "source": "数量关系-" + kind, "tip": tip,
    }


def _mq_engineer(level="mid"):
    """工程问题：设总量为工期的最小公倍数，效率就都是整数。"""
    a, b = random.choice({                       # 入门：合作天数是整数；真实：会出小数，得算准
        "easy": [(6, 12), (10, 15), (12, 4)],
        "mid":  [(10, 15), (12, 18), (20, 30), (6, 12), (15, 10)],
        "real": [(9, 14), (13, 17), (21, 28), (11, 16), (18, 24)],
    }[_lv(level)])
    total = a * b // math.gcd(a, b)
    ea, eb = total // a, total // b
    together = round(total / (ea + eb), 1)
    return _mq(
        "一项工程，甲单独做需 %d 天完成，乙单独做需 %d 天完成。两人合作，需多少天完成？" % (a, b),
        together, [(a + b) / 2, together + 2, together + 4],
        "设工程总量为 %d（%d 和 %d 的最小公倍数）。甲效率 %d/天，乙效率 %d/天，"
        "合作效率 %d/天。%d ÷ %d = {ans}。" % (total, a, b, ea, eb, ea + eb, total, ea + eb),
        "工程", "**设总量为最小公倍数**，效率立刻变整数——别去通分算 1/a+1/b，那是给自己找麻烦。",
        unit="天", step=0.5, level=level)


def _mq_travel(level="mid"):
    """行程：相遇/追及。速度和距离都挑成整除的。"""
    if random.random() < 0.5:
        v1, v2 = random.choice({
            "easy": [(60, 40), (50, 50), (70, 30)],       # 速度和是整百，好算
            "mid":  [(60, 40), (50, 30), (70, 50), (45, 35)],
            "real": [(68, 47), (53, 39), (72, 58), (46, 37)],   # 数字「脏」，逼你估算
        }[_lv(level)])
        t = random.choice([2, 3, 4] if _lv(level) != "real" else [3, 4, 5, 6])
        d = (v1 + v2) * t
        return _mq(
            "甲、乙两地相距 %d 千米。两车分别从两地同时相向出发，速度分别为 %d 千米/时和 %d 千米/时，"
            "多少小时后相遇？" % (d, v1, v2),
            t, [t + 1, t + 2, round(d / v1, 1)],
            "相遇问题：路程 ÷ 速度和 = %d ÷ (%d+%d) = {ans}。" % (d, v1, v2),
            "行程", "相遇看**速度和**，追及看**速度差**——先判断是哪一类，公式就出来了。",
            unit="小时", step=0.5, level=level)
    v1, v2 = random.choice([(60, 40), (75, 50), (80, 60)])
    t = random.choice([3, 4, 5])
    d = (v1 - v2) * t
    return _mq(
        "乙先出发，甲在乙出发时落后 %d 千米，同向追赶。甲速 %d 千米/时，乙速 %d 千米/时，"
        "甲多少小时追上乙？" % (d, v1, v2),
        t, [t + 1, round(d / (v1 + v2), 1), t * 2],
        "追及问题：路程差 ÷ 速度差 = %d ÷ (%d−%d) = {ans}。" % (d, v1, v2),
        "行程", "相遇看**速度和**，追及看**速度差**——先判断是哪一类，公式就出来了。",
        unit="小时", step=0.5, level=level)


def _mq_profit(level="mid"):
    """利润：成本取整百，折扣取整。"""
    lv = _lv(level)
    cost = random.choice({"easy": [100, 200], "mid": [200, 300, 400, 500],
                          "real": [180, 260, 340, 480]}[lv])
    up = random.choice({"easy": [100], "mid": [50, 80, 100], "real": [40, 60, 75, 120]}[lv])
    disc = random.choice({"easy": [8], "mid": [8, 9, 7], "real": [6, 7, 8, 9]}[lv])
    price = cost * (100 + up) // 100
    sell = price * disc // 10
    profit = sell - cost
    return _mq(
        "某商品进价 %d 元，按进价提高 %d%% 标价，再打 %d 折出售。每件的利润是多少？" % (cost, up, disc),
        profit, [price - cost, profit + cost // 10, sell // 2],
        "标价 = %d × (1+%d%%) = %d 元；售价 = %d × %d折 = %d 元；"
        "利润 = 售价 − 进价 = %d − %d = {ans}。" % (cost, up, price, price, disc, sell, sell, cost),
        "利润", "**成本设成 100**（或题给的整数），标价、折扣、利润全是百分比乘除，别设未知数。",
        unit="元", step=10, level=level)


def _mq_solution(level="mid"):
    """浓度：用十字交叉法，溶质守恒。"""
    lv = _lv(level)
    c1, c2 = random.choice({"easy": [(10, 30), (20, 40)],
                            "mid": [(10, 30), (20, 50), (5, 25), (15, 40)],
                            "real": [(8, 27), (13, 42), (6, 31), (17, 44)]}[lv])
    m1, m2 = random.choice({"easy": [(100, 100), (200, 200)],   # 等量混合，就是平均数
                            "mid": [(200, 300), (100, 300), (300, 200), (400, 100)],
                            "real": [(240, 360), (150, 350), (320, 180)]}[lv])
    solute = c1 * m1 + c2 * m2
    c = round(solute / (m1 + m2), 1)
    return _mq(
        "把 %d 克浓度 %d%% 的盐水和 %d 克浓度 %d%% 的盐水混合，混合后的浓度是多少？" % (m1, c1, m2, c2),
        c, [(c1 + c2) / 2, c + 3, c - 3],
        "溶质守恒：(%d×%d%% + %d×%d%%) ÷ (%d+%d) = {ans}。"
        "注意**不是两个浓度的平均数**——那是最常见的错法（%.1f%%）。"
        % (m1, c1, m2, c2, m1, m2, (c1 + c2) / 2),
        "浓度", "**十字交叉法**：两溶液质量比 = 浓度差的反比。看到「混合」先想它，比列方程快得多。",
        unit="%", step=1, level=level)


def _mq_incl(level="mid"):
    """容斥：两集合。"""
    total = random.choice([40, 50, 60])
    a = random.choice([25, 30, 32])
    b = random.choice([20, 24, 28])
    neither = random.choice([3, 5, 8])
    both = a + b - (total - neither)
    if both <= 0 or both > min(a, b):
        both, a, b, neither = 10, 30, 25, 5
        total = 50
    return _mq(
        "某班 %d 人，参加数学竞赛的有 %d 人，参加物理竞赛的有 %d 人，两项都没参加的有 %d 人。"
        "两项都参加的有多少人？" % (total, a, b, neither),
        both, [both + 3, max(1, both - 3), a + b - total],
        "两集合容斥：|A∪B| = 总数 − 都不参加 = %d − %d = %d；"
        "|A∩B| = |A| + |B| − |A∪B| = %d + %d − %d = {ans}。"
        % (total, neither, total - neither, a, b, total - neither),
        "容斥", "先算**至少参加一项**（总数 − 都不参加），再套 A+B−A∪B。别一上来就画文氏图。",
        unit="人", step=2, level=level)


def _mq_combi(level="mid"):
    """排列组合：小数字，能手算验证。"""
    lv = _lv(level)
    n = random.choice({"easy": [4, 5], "mid": [5, 6, 7], "real": [7, 8, 9]}[lv])
    k = random.choice({"easy": [2], "mid": [2, 3], "real": [3, 4]}[lv])
    val = math.comb(n, k)
    return _mq(
        "从 %d 个人中选出 %d 人组成一个小组（不分职务），有多少种不同的选法？" % (n, k),
        val, [math.perm(n, k), val + n, max(1, val - k)],
        "不分职务 = **组合**：C(%d,%d) = {ans}。"
        "如果分职务（比如选组长和副组长）才是排列 A(%d,%d) = %d 种——"
        "这两个混淆是最常见的错。" % (n, k, n, k, math.perm(n, k)),
        "排列组合", "先问一句：**换个顺序算不算新方案？** 算 → 排列 A；不算 → 组合 C。",
        unit="种", step=3, level=level)


def _mq_cycle(level="mid"):
    """周期：星期/余数。"""
    start = random.choice(["星期一", "星期二", "星期三", "星期四", "星期五"])
    week = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    days = random.choice({"easy": [10, 15, 20], "mid": [100, 200, 365, 500],
                          "real": [1234, 2025, 3650, 8888]}[_lv(level)])
    idx = (week.index(start) + days) % 7
    ans = week[idx]
    # 答案是「星期几」不是数值，_mq 那套数值去重用不上；这三个偏移量本来就互不相同，直接拼
    opts = [ans, week[(idx + 1) % 7], week[(idx + 2) % 7], week[(idx - 1) % 7]]
    random.shuffle(opts)
    return {
        "q": "今天是%s，%d 天后是星期几？" % (start, days),
        "options": ["%s. %s" % ("ABCD"[i], o) for i, o in enumerate(opts)],
        "answer": "ABCD"[opts.index(ans)],
        "explain": "周期是 7。%d ÷ 7 = %d 余 %d，从%s往后推 %d 天 → %s。"
                   % (days, days // 7, days % 7, start, days % 7, ans),
        "module": "数量关系", "source": "数量关系-周期",
        "tip": "**只看余数**，商是多少完全不用管。%d 天后 = 往后推 (%d mod 7) 天。" % (days, days),
    }


def _mq_age(level="mid"):
    """年龄：年龄差不变。"""
    diff = random.choice([24, 26, 28, 30])
    k = random.choice([3, 4, 5])                # 若干年后父是子的 k 倍
    son_then = diff // (k - 1)
    while diff % (k - 1):
        diff += 1
        son_then = diff // (k - 1)
    son_now = random.choice([5, 6, 8])
    after = son_then - son_now
    if after <= 0:
        son_now, after = 5, son_then - 5
    dad_now = son_now + diff
    return _mq(
        "今年父亲 %d 岁，儿子 %d 岁。多少年后父亲的年龄是儿子的 %d 倍？" % (dad_now, son_now, k),
        after, [after + 2, max(1, after - 2), after * 2],
        "**年龄差永远不变**，是 %d 岁。设那时儿子 x 岁，父亲 %dx 岁，"
        "%dx − x = %d → x = %d。所以是 %d − %d = {ans}后。"
        % (diff, k, k, diff, son_then, son_then, son_now),
        "年龄", "抓住**年龄差不变**这个不变量——所有年龄题都是围着它转的。",
        unit="年", step=2, level=level)


_MATH_GEN = {
    "工程": _mq_engineer, "行程": _mq_travel, "利润": _mq_profit, "浓度": _mq_solution,
    "容斥": _mq_incl, "排列组合": _mq_combi, "周期": _mq_cycle, "年龄": _mq_age,
}

def _mq_extreme(level="mid"):
    """最值问题：和一定，求某个量的最大值 —— 「其余尽量小」是唯一思路。"""
    lv = _lv(level)
    n = random.choice({"easy": [3, 4], "mid": [5, 6], "real": [7, 8]}[lv])
    total = random.choice([50, 60, 80, 100, 120])
    # 名次不同、都是正整数、各不相同 → 第一名最大 = 总数 − (最小的 n−1 个互异正整数之和)
    others = sum(range(1, n))          # 1+2+…+(n−1)
    mx = total - others
    return _mq(
        "%d 个人共得 %d 分，每人得分是**互不相同的正整数**。得分最高的人最多能得多少分？" % (n, total),
        mx, [total - (n - 1), mx - n, mx + n],
        "要让最高的最多，**其余的就要尽量少**。其余 %d 人得分互不相同且为正整数，"
        "最少是 1,2,…,%d，合计 %d 分。所以最高 = %d − %d = {ans}。"
        % (n - 1, n - 1, others, total, others),
        "最值", "**要谁最大，就让别人尽量小**（反之亦然）。「互不相同的正整数」= 从 1 开始连着排。",
        unit="分", step=2, level=lv)


def _mq_geometry(level="mid"):
    """几何问题：边长按比例放大，面积按平方倍 —— 这是最常考也最常错的点。"""
    lv = _lv(level)
    a = random.choice({"easy": [4, 6], "mid": [6, 8, 10], "real": [7, 9, 12]}[lv])
    k = random.choice([2, 3] if lv != "real" else [2, 3, 4])
    s1 = a * a
    s2 = s1 * k * k
    return _mq(
        "一个正方形的边长为 %d，若把边长扩大到原来的 %d 倍，面积变为多少？" % (a, k),
        s2, [s1 * k, s1 * k * k * k, s1 + k * k],
        "边长 ×%d → 面积 ×%d²= ×%d。原面积 %d×%d = %d，新面积 = %d × %d = {ans}。\n"
        "**面积是平方关系，不是线性关系** —— 直接乘 %d（得 %d）是最常见的错。"
        % (k, k, k * k, a, a, s1, s1, k * k, k, s1 * k),
        "几何", "**边长 ×k → 面积 ×k²，体积 ×k³**。看到「扩大几倍」先问一句：问的是长度、面积还是体积？",
        unit="", step=max(4, s1 // 4), level=lv)


def _mq_prob(level="mid"):
    """概率：古典概型，摸球。数字小，能手算验证。"""
    lv = _lv(level)
    r = random.choice({"easy": [2, 3], "mid": [3, 4], "real": [4, 5]}[lv])
    b = random.choice({"easy": [2, 3], "mid": [3, 5], "real": [5, 6]}[lv])
    tot = r + b
    # 摸 2 个都是红球的概率 = C(r,2)/C(tot,2)，化成百分数并保证是「干净」的
    p = math.comb(r, 2) / math.comb(tot, 2) * 100
    return _mq(
        "袋中有 %d 个红球、%d 个白球。一次摸出 2 个球，**两个都是红球**的概率约为：" % (r, b),
        round(p, 1),
        [round(r / tot * 100, 1),                     # 只算了一个球是红的
         round((r / tot) * (r / tot) * 100, 1),       # 当成有放回
         round(p + 12, 1)],
        "古典概型：P = C(%d,2) ÷ C(%d,2) = %d ÷ %d = {ans}。\n"
        "**摸出后不放回**，所以第二次的分母要减 1 —— 当成有放回算是最常见的错。"
        % (r, tot, math.comb(r, 2), math.comb(tot, 2)),
        "概率", "先问：**放回还是不放回？** 不放回用组合数 C 直接算，别去连乘。",
        unit="%", step=3, level=lv)


def _mq_arith(level="mid"):
    """等差数列：求和。中项公式最快。"""
    lv = _lv(level)
    a1 = random.choice({"easy": [1, 2], "mid": [3, 5], "real": [7, 11]}[lv])
    dd = random.choice({"easy": [1, 2], "mid": [2, 3], "real": [4, 6]}[lv])
    n = random.choice({"easy": [10], "mid": [10, 20], "real": [15, 25, 30]}[lv])
    an = a1 + (n - 1) * dd
    ssum = n * (a1 + an) // 2
    return _mq(
        "一个等差数列首项为 %d，公差为 %d，共 %d 项。所有项之和是多少？" % (a1, dd, n),
        ssum, [n * a1 + dd * n, (a1 + an) * n, ssum + n * dd],
        "末项 aₙ = %d + (%d−1)×%d = %d。\n"
        "求和 = (首项 + 末项) × 项数 ÷ 2 = (%d + %d) × %d ÷ 2 = {ans}。\n"
        "**别忘了除以 2** —— 漏掉就得 %d 了。"
        % (a1, n, dd, an, a1, an, n, (a1 + an) * n),
        "等差数列", "求和只记一个：**(首 + 末) × 项数 ÷ 2**。项数 = (末 − 首) ÷ 公差 + 1，**那个 +1 别丢**。",
        unit="", step=max(5, ssum // 10), level=lv)


def _mq_tree(level="mid"):
    """植树/方阵：两端都种 = 段数 + 1。这个 +1 是全部考点。"""
    lv = _lv(level)
    if random.random() < 0.5:
        length = random.choice({"easy": [100, 120], "mid": [200, 300], "real": [420, 560]}[lv])
        gap = random.choice([4, 5, 6, 8])
        while length % gap:
            length += 1
        n = length // gap + 1                      # 两端都种
        return _mq(
            "一条 %d 米长的路，**两端都要种树**，每隔 %d 米种一棵。一共要种多少棵？" % (length, gap),
            n, [n - 1, n - 2, n + 1],
            "**两端都种：棵数 = 段数 + 1** = %d ÷ %d + 1 = {ans}。\n"
            "如果只种一端就是 %d 棵，两端都不种是 %d 棵 —— 这个 ±1 就是全部考点。"
            % (length, gap, n - 1, n - 2),
            "植树方阵", "**两端都种 = 段数 + 1；只种一端 = 段数；两端都不种 = 段数 − 1。**"
                        "封闭路线（一圈）**棵数 = 段数**，没有 +1。",
            unit="棵", step=1, level=lv)
    side = random.choice({"easy": [5, 6], "mid": [8, 10], "real": [12, 15]}[lv])
    outer = 4 * side - 4                           # 空心方阵最外层人数
    return _mq(
        "一个方阵的最外层每边站 %d 人。最外层一共有多少人？" % side,
        outer, [4 * side, side * side, outer - 4],
        "**四个角会被数两遍**：最外层人数 = 每边 × 4 − 4 = %d×4 − 4 = {ans}。\n"
        "直接 %d×4 = %d 是错的（角上重复计了）；%d×%d = %d 那是整个实心方阵。"
        % (side, side, 4 * side, side, side, side * side),
        "植树方阵", "空心方阵最外层 = **每边 × 4 − 4**（四个角别数两遍）。相邻两层相差 8 人。",
        unit="人", step=2, level=lv)


_NUMSEQ = {
    "等差": lambda: (lambda a, d: ([a + i * d for i in range(5)], a + 5 * d,
                                   "相邻两项差 %d（等差数列）" % d))(
        random.randint(2, 9), random.randint(2, 9)),
    "等比": lambda: (lambda a, q: ([a * q ** i for i in range(5)], a * q ** 5,
                                   "相邻两项比 %d（等比数列）" % q))(
        random.randint(1, 3), random.choice([2, 3])),
    "平方": lambda: (lambda b: ([(b + i) ** 2 for i in range(5)], (b + 5) ** 2,
                                "分别是 %d²、%d²、…（平方数列）" % (b, b + 1)))(random.randint(2, 6)),
    "递推和": lambda: (lambda a, b: (lambda seq: (seq[:5], seq[5],
                                                 "每一项 = 前两项之和（%d+%d=%d…）" % (seq[0], seq[1], seq[2])))(
        [a, b, a + b, a + 2 * b, 2 * a + 3 * b, 3 * a + 5 * b]))(
        random.randint(1, 5), random.randint(2, 7)),
}


def _mq_numseq(level="mid"):
    """数字推理：找规律填下一个数。规律由构造保证，不存在「多解」。"""
    lv = _lv(level)
    pool = {"easy": ["等差", "等比"], "mid": ["等差", "等比", "平方"],
            "real": ["等比", "平方", "递推和"]}[lv]
    kind = random.choice(pool)
    seq, ans, why = _NUMSEQ[kind]()
    return _mq(
        "找规律，填出下一个数：%s，( )" % "、".join(str(x) for x in seq),
        ans, [ans + seq[-1] - seq[-2], ans - 1, seq[-1] * 2],
        "%s，所以下一个是 {ans}。" % why,
        "数字推理",
        "数字推理只看四步：**先看差**（等差）→ **再看商**（等比）→ **看是不是平方/立方数** → "
        "**看是不是前两项组合出来的**。四步走完还没头绪就跳过，别耗时间。",
        unit="", step=max(2, abs(ans) // 8 or 2), level=lv)


_MATH_GEN = {
    "工程": _mq_engineer, "行程": _mq_travel, "利润": _mq_profit, "容斥": _mq_incl,
    "最值": _mq_extreme, "几何": _mq_geometry, "排列组合": _mq_combi, "概率": _mq_prob,
    "浓度": _mq_solution, "等差数列": _mq_arith, "周期日期": _mq_cycle,
    "植树方阵": _mq_tree, "年龄": _mq_age, "数字推理": _mq_numseq,
}
# 题型顺序 = 讲义目录（第二章 高频题型 → 第三章 数字推理），循序渐进
_MATH_ORDER = ["工程", "行程", "利润", "容斥", "最值", "几何", "排列组合", "概率",
               "浓度", "等差数列", "周期日期", "植树方阵", "年龄", "数字推理"]
_MATH_BY_LEVEL = {
    "easy": ["工程", "行程", "利润", "周期日期", "等差数列", "植树方阵"],
    "mid":  ["工程", "行程", "利润", "容斥", "几何", "排列组合", "浓度", "等差数列",
             "周期日期", "植树方阵", "年龄", "数字推理"],
    "real": ["容斥", "最值", "排列组合", "概率", "浓度", "年龄", "数字推理", "几何"],
}


def _gen_math_q(kind=None, level="mid"):
    """出一道数量关系。kind 不给就按难度从对应题型池里随机。"""
    lv = _lv(level)
    if kind not in _MATH_GEN:
        kind = random.choice(_MATH_BY_LEVEL[lv])
    q = _MATH_GEN[kind](lv)
    q["level"] = lv
    return q
