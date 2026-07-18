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
