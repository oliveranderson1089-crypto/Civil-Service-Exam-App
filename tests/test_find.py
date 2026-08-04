"""find 模块：材料分句 _find_sents。

find 改动 1 次、零测试。「找要点」题把材料按句渲染，用户逐句勾画 —— 所以分句粒度
直接决定能不能勾对。标题行不可勾画（标 head=True）；被 OCR/排版切碎的闭引号、纯标点
碎片要并回上一句，否则会多出一堆勾不了的碎句。
"""
from mods.find import _find_sents


def test_按句号叹号问号分号切句():
    sents = _find_sents("坚持依法治国。建设法治政府！走对了吗？")
    texts = [s["t"] for s in sents if not s.get("head")]
    assert len(texts) == 3, f"该切成 3 句，实际 {texts}"


def test_标题行标记为head不可勾画():
    # 短且无句末标点 → 当标题
    sents = _find_sents("一、给定资料\n某地推进垃圾分类，成效显著。")
    assert sents[0]["head"] is True, "标题行没标 head，会被当成可勾画的要点句"
    assert sents[1].get("head") is not True, "正文句被误当标题了"


def test_闭引号碎片并回上一句():
    # 「……分类。」被切成「……分类。」+「」」两段，后者要并回去
    sents = _find_sents('他说“要搞好垃圾分类。”然后走了。')
    for s in sents:
        assert s["t"].strip() != "”", "闭引号单独成了一句碎片，用户会看到一句勾不了的「」"


def test_空材料不炸():
    assert _find_sents("") == []
    assert _find_sents("\n\n  \n") == []


def test_每句带原始段落号():
    sents = _find_sents("第一段句子。\n第二段句子。")
    ps = {s["p"] for s in sents}
    assert len(ps) == 2, "两段的句子该带不同的段落号（p），否则定位会串段"


# ---------------------------------------------------------------- 采分点的覆盖度
# 实测出来的病：采分点会全挤在材料前段。2026 国考副省级第 1 题 23 句材料标了 5 个点、
# 数量对，却全落在句 3~9，智慧照明整段和长效机制整段一个点没标 —— 而那正是真题标准
# 答案的第 4、5 点。全库体检 11 道题里 8 道有整块材料零覆盖。
# 数字判据（_find_coverage / _find_needs_more）现在同时当出题闸门和 audit 验收标准，
# 它要是算错了，两边一起错还谁都发现不了 —— 所以这几条必须钉死。
from mods.find import (_FIND_GAP_MAX, _find_coverage, _find_guard,
                       _find_needs_more)


def _sents(n):
    """n 个可勾画的句子（够长，不会被当成标题行）。"""
    return [{"p": 0, "t": "这是第%d句材料，写得够长以免被当成标题行。" % i, "head": False}
            for i in range(n)]


def test_最长空白带按可勾画句数算():
    # 20 句，只有句 0 和句 19 有采分点 → 中间 18 句是空白带
    cov = _find_coverage(_sents(20), [{"sents": [0]}, {"sents": [19]}])
    assert cov["max_gap"] == 18, f"最长空白带该是 18 句，实际 {cov['max_gap']}"
    assert cov["gap_range"] == (1, 18)


def test_标题行不算进覆盖():
    ss = _sents(3)
    ss.insert(1, {"p": 0, "t": "材料一", "head": True})
    cov = _find_coverage(ss, [{"sents": [0]}])
    assert cov["n_sents"] == 3, "标题行不该计入可勾画句数，否则覆盖率被稀释"


def test_铺满全材料就不触发补点():
    ss = _sents(21)
    pts = [{"sents": [i]} for i in (0, 5, 10, 15, 20)]
    assert not _find_needs_more(_find_coverage(ss, pts)), "均匀铺开的题不该被判成要补点"


def test_全挤在开头必须触发补点():
    # H 市那道题的形状：23 句，点全在前 1/3
    ss = _sents(23)
    pts = [{"sents": [i]} for i in (3, 4, 5, 6, 9)]
    cov = _find_coverage(ss, pts)
    assert cov["max_gap"] >= _FIND_GAP_MAX, "句 10~22 连续 13 句没点，必须被算成空白带"
    assert _find_needs_more(cov), "这正是要拦下来的那种题，闸门却放过了"


def test_guard把合并砍掉的覆盖面补回来():
    # 合并阶段常把后半段的点砍光（实测有一道 coverage 掉到 2/6、空白带 26 句）。
    # 候选里明明有落在空白处的点，guard 要不依赖 AI 直接补回去。
    ss = _sents(30)
    points = [{"point": "开头的点", "evidence": "x", "score": 2.0, "sents": [i]} for i in (0, 1, 2)]
    cands = [{"sent": i, "sents": [i], "point": "候选%d" % i, "evidence": "x"} for i in range(30)]
    out = _find_guard(ss, points, cands, n_hi=8)
    assert len(out) > 3, "空白处有现成候选，guard 一个都没补回来"
    assert _find_coverage(ss, out)["max_gap"] < 27, "补完仍是一大片空白，等于没补"
    assert [p["sents"][0] for p in out] == sorted(p["sents"][0] for p in out), \
        "采分点该按材料顺序排（参考答案是照这个顺序拼的）"


def test_guard在候选也没覆盖时不硬凑():
    # 空白处扫描时本来就没找到东西 —— 宁可空着，也不许编个空话点糊上去
    ss = _sents(30)
    points = [{"point": "开头", "evidence": "x", "score": 2.0, "sents": [0]}]
    cands = [{"sent": 0, "sents": [0], "point": "开头", "evidence": "x"}]
    out = _find_guard(ss, points, cands, n_hi=8)
    assert len(out) == 1, "候选里没有可补的点，却凭空多出了采分点"


def test_合并结果的句号只从候选查_不信模型回报的数字(monkeypatch):
    """合并阶段最阴的一个坑：模型把「候选编号」当成「句子序号」填回来。

    实测一道 58 句的对策题，合并出的 12 个点里有 8 个中招 ——「借鉴公交电梯模式」
    被标到句 10，可那段原文在句 35~37。采分点整体锚错位，学生勾对了句子反被判找错，
    比找点不全还糟，而且从分数上完全看不出来。
    所以 _find_merge 现在只让模型回报候选编号（from），句号由服务端查候选。
    这条测试就是钉死它：哪怕模型回报的数字长得像句号，也不许被当成句号用。
    """
    from mods import find as F
    sents = _sents(60)
    cands = [{"sent": 35, "sents": [35, 36], "point": "借鉴公交电梯模式", "evidence": "x"},
             {"sent": 50, "sents": [50], "point": "建立维护基金", "evidence": "y"}]
    # 模型把候选编号 1、2 原样丢回来 —— 它们看起来完全像合法句号
    monkeypatch.setattr(F, "_find_merge",
                        lambda *a, **k: [{"from": [1], "point": "借鉴公交电梯模式", "score": 5},
                                         {"from": [2], "point": "建立维护基金", "score": 5}])
    points, _dropped = F._find_finalize("提出对策题", "题干", sents, cands, 10, 1, 1)
    got = sorted(i for p in points for i in p["sents"])
    assert got == [35, 36, 50], f"句号该从候选查出 35/36/50，实际锚到了 {got}"


def test_跨句依据要打省略号不能硬粘():
    """一个采分点覆盖句 22、28、47、50 这种很常见，原来一路 "".join 会把不挨着的
    半句粘成一句读不通的话：「…工商人员核查经营资质，卫生监督2014年初，县工商局与…」。
    小题训练那边材料按句渲染高亮、看不出来；真题批改把它当一整段引文显示就露馅了。
    """
    from mods.find import _ev_text
    ss = [{"p": 0, "t": "第%d句。" % i, "head": False} for i in range(10)]
    assert _ev_text(ss, [1, 2, 3]) == "第1句。第2句。第3句。", "连续的句子不该插省略号"
    assert _ev_text(ss, [1, 5]) == "第1句。……第5句。", "不相邻的句子之间必须有省略号"
    assert _ev_text(ss, [1, 2, 5, 6]) == "第1句。第2句。……第5句。第6句。"
    assert _ev_text(ss, [3]) == "第3句。"
    assert _ev_text(ss, []) == ""


def test_大作文选备料要保三类且铺开位置():
    """跳过合并后落到 `cands[:n_hi]` 兜底，等于按材料顺序截断 —— 实测 34 句的材料
    12 条备料全挤在句 5~24，题干引语的出处（句 33，立意的根）被截没了。
    这正是当初给小题修好的「集中在前段」，在大作文这条路上又被引回来一次。
    """
    from mods.find import _zw_select
    # 前面全是论据，立意只有最后一条 —— 按位置截断必然把它丢掉
    cands = [{"sents": [i], "sent": i, "point": "【论据】证据%d" % i, "evidence": "x"}
             for i in range(20)]
    cands.append({"sents": [33], "sent": 33, "point": "【立意】题干那句话的出处", "evidence": "y"})
    cands.append({"sents": [30], "sent": 30, "point": "【分论点】某个侧面", "evidence": "z"})
    got = _zw_select(cands, 8)
    pts = [c["point"] for c in got]
    assert any(p.startswith("【立意】") for p in pts), "立意被截没了 —— 它最要紧也最容易被论据淹掉"
    assert any(p.startswith("【分论点】") for p in pts), "分论点一条都没留"
    assert len(got) <= 8, "超出名额上限"
    assert [c["sents"][0] for c in got] == sorted(c["sents"][0] for c in got), "该按材料顺序排"
    assert max(c["sents"][0] for c in got) > 20, "备料仍全挤在材料前段，没铺开"


class Test沾边判定:
    """勾了但没进采分点的句子，要再分「沾边」和「真找错」。

    原来一刀切：不在采分点里 = 找错 = 「这些是干扰信息」。**这个反馈是错的。**
    实测（audit_find.py --baseline，5 道题各连出 3 次）扫描扫出的候选有一半以上会在
    收口时被丢掉 —— 贯彻执行 14~17 个候选只留 5~7 个点。被丢掉的句子确实含要点，
    只是这一次标定没让它独立成点（「设施农业」和「星光合作社」都是正当举措，只有一个入选）。
    用户勾中它却被告知「这是干扰信息」，等于教错了。
    """

    def test_近似句判沾边而不是找错(self):
        from mods.find import _find_split_wrong
        near, wrong = _find_split_wrong({"near": "[5, 7]"}, [3, 5, 7, 9], {3})
        assert near == [5, 7], "扫描认过的句子该判沾边，实际 %s" % near
        assert wrong == [9], "只有两边都不沾的才是真找错，实际 %s" % wrong

    def test_采分点内的句子不进沾边也不进找错(self):
        from mods.find import _find_split_wrong
        near, wrong = _find_split_wrong({"near": "[5]"}, [1, 5], {1})
        assert 1 not in near and 1 not in wrong, "已命中采分点的句子不该再被归类"
        assert near == [5]

    def test_老题目没有near列时退回老行为(self):
        """这一列是后加的，存量题目没有 —— 不能因此炸，也不能凭空冒出沾边。"""
        from mods.find import _find_split_wrong
        for row in ({"near": None}, {"near": ""}, {"near": "坏掉的json"}):
            near, wrong = _find_split_wrong(row, [2, 4], set())
            assert near == [], "没有 near 数据却报了沾边：%s" % near
            assert wrong == [2, 4], "老题目该维持原来的「全判找错」行为"


# ============ 真题材料：接回 PDF 硬折行 + 一题只喂它那一则 ============
import re as _re

from mods.find import _q_scoped_material, _split_materials, _unwrap

# 真题 PDF 的版式：段首缩进 4 空格，续行顶格 —— 缩进行够多才走「缩进=段首」这一路
_PDF_LIKE = (
    "1. 2025年10月的一天，鲁师傅办公桌上的电脑屏幕弹出市监局发来的“体检报告”，那是他所\n"
    "经营的三家门店的“检测指标”。\n"
    "    2000年春节前，鲁师傅务工结束返乡。回到县城时，一阵烧饼香气飘来。广合烧饼在当地\n"
    "世代相传，是当地人最爱的日常小吃，风味声名远\n"
    "播。\n"
    "    春节后，鲁师傅做了个简易烤炉，在县汽车站旁支起烧饼摊。\n"
    "    转折出现在2003年夏天，县工商局开展“百日整治”行动。\n"
    "2. 近日，D县民政局开展了养老机构检查整治工作。\n"
)


def test_硬折行接回整段_缩进才是段首():
    out = _unwrap(_PDF_LIKE).split("\n")
    assert out[0].endswith("“检测指标”。")          # 续行接回来了
    # 一句被拆到三行，整段接回来，中间不留断点
    assert out[1].endswith("风味声名远播。") and "远播" in out[1]
    assert out[2].startswith("春节后")               # 缩进行另起一段
    assert out[-1].startswith("2.")                  # 材料编号行永远另起


def test_接回折行不动一个字():
    """只重排换行，内容必须逐字不变 —— 全库 128 份卷子跑过这条。"""
    assert _re.sub(r"\s", "", _unwrap(_PDF_LIKE)) == _re.sub(r"\s", "", _PDF_LIKE)


def test_空行分段的版式_收了句也不算段落结束():
    """没缩进、靠空行分段的卷子（2025 国考行政执法就是）。
    只看句末标点会在「上一行正好收句、下一行仍是同段」处断错 —— 一句话成一段。"""
    txt = ("材料1. 近年来，A市把科技创新摆在核心位置，创新优势从无到有。\n"
           "\n"
           "两年前，方教授团队取得了一项科研成果，新技术既节能环保。\n"
           "如何将这项成果推向市场呢？“转化专班的支持帮我们跨越了鸿沟。”方教授说。\n"
           "专班工作人员常态化登门入室，深\n"
           "度对接市内外高校院所。\n"
           "\n"
           "远达信息技术有限公司选择落户A市，源于一次合作对接。\n")
    out = [x for x in _unwrap(txt).split("\n") if x.strip()]
    assert len(out) == 3                                  # 三段，不是七段
    assert out[1].endswith("深度对接市内外高校院所。")      # 段内收过句也照样接着走
    assert out[2].startswith("远达信息")


def test_没有缩进的版式退回看句末标点():
    txt = "甲乙丙丁戊己庚辛，这一句还没写完\n所以下一行是它的续行。\n另起一句写在这里。"
    out = _unwrap(txt).split("\n")
    assert out[0] == "甲乙丙丁戊己庚辛，这一句还没写完所以下一行是它的续行。"
    assert out[1] == "另起一句写在这里。"


def test_一题只喂它引用的那一则材料():
    mats = _split_materials(_unwrap(_PDF_LIKE))
    assert sorted(mats) == [1, 2]
    got = _q_scoped_material("请根据“给定资料2”，梳理存在的问题。", mats, "整卷")
    assert got.startswith("近日，D县民政局") and "鲁师傅" not in got


def test_题干没写引用哪则就退回整份():
    mats = _split_materials(_unwrap(_PDF_LIKE))
    assert _q_scoped_material("请自拟题目写一篇文章。", mats, "整卷") == "整卷"
