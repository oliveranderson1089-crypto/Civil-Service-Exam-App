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
    return seq, right, wrong, "图形每次顺时针旋转 90°：0°→90°→180°，问号处应是 270°。注意有个选项是它的镜像——镜像靠旋转是得不到的。", "图形推理-旋转"


def _figq_dots():
    def f(n):
        s = '<rect x="10" y="10" width="68" height="68" rx="8" %s/>' % _FIG_STROKE
        for i in range(n):
            a = math.radians(-90 + i * 360.0 / n)
            s += '<circle cx="%.1f" cy="%.1f" r="6" fill="currentColor"/>' % (44 + 24 * math.cos(a), 44 + 24 * math.sin(a))
        return _fig(s)
    return [f(2), f(3), f(4)], f(5), [f(3), f(4), f(6)], "框里的黑点数依次是 2、3、4，成等差数列，问号处应有 5 个。", "图形推理-元素数量"


def _figq_sides():
    def f(n):
        pts = [(44 + 30 * math.cos(math.radians(-90 + i * 360.0 / n)),
                44 + 30 * math.sin(math.radians(-90 + i * 360.0 / n))) for i in range(n)]
        return _fig(_fig_poly(pts))
    return [f(3), f(4), f(5)], f(6), [f(5), f(7), f(8)], "边数依次为 3、4、5，问号处应是六边形。", "图形推理-边数递增"


def _figq_lines():
    def f(n):
        s = '<circle cx="44" cy="44" r="34" %s/>' % _FIG_STROKE
        for i in range(n):
            a = math.radians(-90 + i * 360.0 / n)
            s += ('<line x1="44" y1="44" x2="%.1f" y2="%.1f" stroke="currentColor" '
                  'stroke-width="2.6" stroke-linecap="round"/>' % (44 + 32 * math.cos(a), 44 + 32 * math.sin(a)))
        return _fig(s)
    return [f(2), f(3), f(4)], f(5), [f(4), f(6), f(3)], "圆里的线段数依次为 2、3、4，问号处应有 5 条。", "图形推理-线条数"


def _figq_regions():
    def f(n):
        s = '<rect x="10" y="24" width="68" height="40" %s/>' % _FIG_STROKE
        for i in range(1, n):
            x = 10 + 68.0 * i / n
            s += ('<line x1="%.1f" y1="24" x2="%.1f" y2="64" stroke="currentColor" stroke-width="2.4"/>' % (x, x))
        return _fig(s)
    return [f(1), f(2), f(3)], f(4), [f(3), f(5), f(2)], "封闭区域数依次为 1、2、3，问号处应有 4 个封闭区域。", "图形推理-封闭区域数"


# ---------------------------------------------------------------- 资料分析：程序化出题
# 同样不让 AI 出：它会写「根据材料…」却根本不给材料，或者数字对不上。
# 这里先造一份**内部自洽的统计数据**（等差设计，比重/增长率都是整数），再由代码算出答案。
_ZL_CITY = ["A 市", "B 市", "C 市", "甲市", "乙市"]


def _gen_ziliao(n_q=1):
    """造一份材料 + n_q 道题（题目共用同一份材料）。数字都是设计好的，答案精确。"""
    city = random.choice(_ZL_CITY)
    rate = random.choice([4, 5, 6, 8])                 # 2024 年同比增速（%）
    g2 = random.choice([2500, 3000, 3200, 3600, 4000])  # 2023 年 GDP
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

    mtype = random.choice(["table", "bar", "line"])
    if mtype == "table":
        material = {"type": "table", "title": "%s 2021—2024 年地区生产总值构成" % city, "unit": "亿元",
                    "headers": ["年份", "地区生产总值", "第一产业", "第二产业", "第三产业"],
                    "rows": [[years[i], gdp[i], first[i], second[i], third[i]] for i in range(4)]}
    else:
        material = {"type": mtype, "title": "%s 2021—2024 年地区生产总值与第三产业增加值" % city,
                    "unit": "亿元", "labels": years,
                    "series": [{"name": "地区生产总值", "data": gdp},
                               {"name": "第三产业增加值", "data": third}]}

    kinds = random.sample(["比重", "增长率", "年均增长量", "倍数", "增长量", "比重变化"], k=min(n_q, 6))
    out = []
    for k in kinds:
        if k == "比重":
            ans = "%d%%" % pct3
            wrong = ["%d%%" % (pct3 - 5), "%d%%" % (pct3 + 5),
                     "%.1f%%" % (third[3] / gdp[2] * 100)]          # 分母用错年份
            q = "2024 年 %s 第三产业增加值占地区生产总值的比重约为：" % city
            ex = "比重 = 第三产业 ÷ 地区生产总值 = %d ÷ %d = %d%%。" % (third[3], gdp[3], pct3)
        elif k == "增长率":
            ans = "%d%%" % rate
            wrong = ["%d%%" % (rate + 2), "%d%%" % max(1, rate - 2),
                     "%.1f%%" % ((gdp[3] - gdp[1]) / gdp[1] * 100)]  # 多算了一年
            q = "2024 年 %s 地区生产总值同比增长约：" % city
            ex = "同比增长率 =（2024 − 2023）÷ 2023 =（%d − %d）÷ %d = %d%%。" % (gdp[3], gdp[2], gdp[2], rate)
        elif k == "年均增长量":
            ans = "%d 亿元" % d
            wrong = ["%d 亿元" % (d * 2), "%d 亿元" % round((gdp[3] - gdp[0]) / 4),  # 除以 4 而不是 3
                     "%d 亿元" % round(d * 1.5)]
            q = "2021—2024 年 %s 地区生产总值的年均增长量约为：" % city
            ex = "年均增长量 =（末年 − 初年）÷ 间隔年数 =（%d − %d）÷ 3 = %d 亿元（注意是 3 年间隔，不是 4）。" % (gdp[3], gdp[0], d)
        elif k == "增长量":
            ans = "%d 亿元" % d
            wrong = ["%d 亿元" % (d * 2), "%d 亿元" % (gdp[3] - gdp[1]), "%d 亿元" % round(d / 2)]
            q = "2024 年 %s 地区生产总值比上年增加了多少亿元？" % city
            ex = "增长量 = 2024 − 2023 = %d − %d = %d 亿元。" % (gdp[3], gdp[2], d)
        elif k == "比重变化":
            # 数据是按「每年三产占比 +2 个百分点」造的，所以变化恒为 2 个百分点
            rel = (third[3] / gdp[3] - third[2] / gdp[2]) / (third[2] / gdp[2]) * 100
            ans = "提高约 2 个百分点"
            wrong = ["提高约 4 个百分点", "下降约 2 个百分点",
                     "提高约 %.1f%%" % rel]                       # 混淆「百分点」与「%」的经典陷阱
            q = "2024 年 %s 第三产业增加值占地区生产总值的比重，与上年相比：" % city
            ex = ("2024 年占比 %d%%，2023 年占比 %d%%，相差 %d − %d = 2 个百分点。"
                  "注意「百分点」是两个百分数直接相减，不是相对变化率（那是 %.1f%%）。"
                  % (pct3, pct3 - 2, pct3, pct3 - 2, rel))
        else:
            times = third[3] / first[3]
            ans = "%.1f 倍" % times
            wrong = ["%.1f 倍" % (times + 1), "%.1f 倍" % max(1.0, times - 1), "%.1f 倍" % (times / 2)]
            q = "2024 年 %s 第三产业增加值约为第一产业的多少倍？" % city
            ex = "倍数 = 第三产业 ÷ 第一产业 = %d ÷ %d ≈ %.1f 倍。" % (third[3], first[3], times)

        opts = wrong + [ans]
        random.shuffle(opts)
        out.append({
            "q": q,
            "options": ["%s. %s" % ("ABCD"[i], o) for i, o in enumerate(opts)],
            "answer": "ABCD"[opts.index(ans)], "explain": ex,
            "module": "资料分析", "source": "资料分析-" + k, "material": material,
        })
    return out


def _gen_figure_q():
    """出一道图形推理：答案由构造保证正确，AI 碰都不碰。"""
    seq, right, wrong, explain, source = random.choice(
        [_figq_rotate, _figq_dots, _figq_sides, _figq_lines, _figq_regions])()
    opts = wrong + [right]
    random.shuffle(opts)
    return {
        "q": "从所给的四个选项中，选择最合适的一个填入问号处，使之呈现一定的规律性。",
        "options": [], "figs": {"seq": seq, "opts": opts},
        "answer": "ABCD"[opts.index(right)], "explain": explain,
        "module": "判断推理", "source": source,
    }


