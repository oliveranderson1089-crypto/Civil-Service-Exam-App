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
