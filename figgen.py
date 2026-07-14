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



# ---------------------------------------------------------------- 数量关系：程序化出题
# 同样不交给 AI：它算错的概率高得离谱（尤其排列组合、容斥、浓度），而且答案和解析常常自相矛盾。
# 这里**先定答案、再倒推题面**，数字都挑成能整除的，保证：算得出、算得整、解析和答案必然一致。
# 每类都附「秒杀技巧」——数量关系提分靠的就是这个，不是硬算。
def _mq(q, ans, wrong, ex, kind, tip, unit="", step=1):
    """选项统一在这里格式化。两条硬约束（都是实测踩出来的）：
       · 四个选项**必须互不相同** —— 干扰项撞上答案，这题就有两个正确选项了；
       · 四个选项**格式必须一致** —— 「29.0% / 23.0% / 35.0% / 26%」等于把答案写脸上。"""
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


def _mq_engineer():
    """工程问题：设总量为工期的最小公倍数，效率就都是整数。"""
    a, b = random.choice([(10, 15), (12, 18), (20, 30), (6, 12), (15, 10)])
    total = a * b // math.gcd(a, b)
    ea, eb = total // a, total // b
    together = round(total / (ea + eb), 1)
    return _mq(
        "一项工程，甲单独做需 %d 天完成，乙单独做需 %d 天完成。两人合作，需多少天完成？" % (a, b),
        together, [(a + b) / 2, together + 2, together + 4],
        "设工程总量为 %d（%d 和 %d 的最小公倍数）。甲效率 %d/天，乙效率 %d/天，"
        "合作效率 %d/天。%d ÷ %d = {ans}。" % (total, a, b, ea, eb, ea + eb, total, ea + eb),
        "工程", "**设总量为最小公倍数**，效率立刻变整数——别去通分算 1/a+1/b，那是给自己找麻烦。",
        unit="天", step=0.5)


def _mq_travel():
    """行程：相遇/追及。速度和距离都挑成整除的。"""
    if random.random() < 0.5:
        v1, v2 = random.choice([(60, 40), (50, 30), (70, 50), (45, 35)])
        t = random.choice([2, 3, 4])
        d = (v1 + v2) * t
        return _mq(
            "甲、乙两地相距 %d 千米。两车分别从两地同时相向出发，速度分别为 %d 千米/时和 %d 千米/时，"
            "多少小时后相遇？" % (d, v1, v2),
            t, [t + 1, t + 2, round(d / v1, 1)],
            "相遇问题：路程 ÷ 速度和 = %d ÷ (%d+%d) = {ans}。" % (d, v1, v2),
            "行程", "相遇看**速度和**，追及看**速度差**——先判断是哪一类，公式就出来了。",
            unit="小时", step=0.5)
    v1, v2 = random.choice([(60, 40), (75, 50), (80, 60)])
    t = random.choice([3, 4, 5])
    d = (v1 - v2) * t
    return _mq(
        "乙先出发，甲在乙出发时落后 %d 千米，同向追赶。甲速 %d 千米/时，乙速 %d 千米/时，"
        "甲多少小时追上乙？" % (d, v1, v2),
        t, [t + 1, round(d / (v1 + v2), 1), t * 2],
        "追及问题：路程差 ÷ 速度差 = %d ÷ (%d−%d) = {ans}。" % (d, v1, v2),
        "行程", "相遇看**速度和**，追及看**速度差**——先判断是哪一类，公式就出来了。",
        unit="小时", step=0.5)


def _mq_profit():
    """利润：成本取整百，折扣取整。"""
    cost = random.choice([200, 300, 400, 500])
    up = random.choice([50, 80, 100])          # 加价率 %
    disc = random.choice([8, 9, 7])            # 打几折
    price = cost * (100 + up) // 100
    sell = price * disc // 10
    profit = sell - cost
    return _mq(
        "某商品进价 %d 元，按进价提高 %d%% 标价，再打 %d 折出售。每件的利润是多少？" % (cost, up, disc),
        profit, [price - cost, profit + cost // 10, sell // 2],
        "标价 = %d × (1+%d%%) = %d 元；售价 = %d × %d折 = %d 元；"
        "利润 = 售价 − 进价 = %d − %d = {ans}。" % (cost, up, price, price, disc, sell, sell, cost),
        "利润", "**成本设成 100**（或题给的整数），标价、折扣、利润全是百分比乘除，别设未知数。",
        unit="元", step=10)


def _mq_solution():
    """浓度：用十字交叉法，溶质守恒。"""
    c1, c2 = random.choice([(10, 30), (20, 50), (5, 25), (15, 40)])
    m1, m2 = random.choice([(200, 300), (100, 300), (300, 200), (400, 100)])
    solute = c1 * m1 + c2 * m2
    c = round(solute / (m1 + m2), 1)
    return _mq(
        "把 %d 克浓度 %d%% 的盐水和 %d 克浓度 %d%% 的盐水混合，混合后的浓度是多少？" % (m1, c1, m2, c2),
        c, [(c1 + c2) / 2, c + 3, c - 3],
        "溶质守恒：(%d×%d%% + %d×%d%%) ÷ (%d+%d) = {ans}。"
        "注意**不是两个浓度的平均数**——那是最常见的错法（%.1f%%）。"
        % (m1, c1, m2, c2, m1, m2, (c1 + c2) / 2),
        "浓度", "**十字交叉法**：两溶液质量比 = 浓度差的反比。看到「混合」先想它，比列方程快得多。",
        unit="%", step=1)


def _mq_incl():
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
        unit="人", step=2)


def _mq_combi():
    """排列组合：小数字，能手算验证。"""
    n = random.choice([5, 6, 7])
    k = random.choice([2, 3])
    val = math.comb(n, k)
    return _mq(
        "从 %d 个人中选出 %d 人组成一个小组（不分职务），有多少种不同的选法？" % (n, k),
        val, [math.perm(n, k), val + n, max(1, val - k)],
        "不分职务 = **组合**：C(%d,%d) = {ans}。"
        "如果分职务（比如选组长和副组长）才是排列 A(%d,%d) = %d 种——"
        "这两个混淆是最常见的错。" % (n, k, n, k, math.perm(n, k)),
        "排列组合", "先问一句：**换个顺序算不算新方案？** 算 → 排列 A；不算 → 组合 C。",
        unit="种", step=3)


def _mq_cycle():
    """周期：星期/余数。"""
    start = random.choice(["星期一", "星期二", "星期三", "星期四", "星期五"])
    week = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    days = random.choice([100, 200, 365, 500])
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


def _mq_age():
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
        "年龄", "抓住**年龄差不变**这个不变量——所有年龄题都是围着它转的。", unit="年", step=2)


_MATH_GEN = {
    "工程": _mq_engineer, "行程": _mq_travel, "利润": _mq_profit, "浓度": _mq_solution,
    "容斥": _mq_incl, "排列组合": _mq_combi, "周期": _mq_cycle, "年龄": _mq_age,
}


def _gen_math_q(kind=None):
    """出一道数量关系。kind 不给就随机。"""
    if kind not in _MATH_GEN:
        kind = random.choice(list(_MATH_GEN))
    return _MATH_GEN[kind]()
