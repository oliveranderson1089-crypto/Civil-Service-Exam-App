"""write 模块：关键词抽取 _kw_of + 素材命中核对 _used_hit。

write 改动 1 次、零测试。_kw_of 抠检索关键词（优先素材自带的干净 topic 标签，不够再从
正文补高频词、过停用词）。_used_hit 核对 AI 报「我用了这条素材」是不是真的 —— 注释里
实测「24 条里有 4 条虚报」，这份清单给人回查素材用，宁可少列不能列错，所以判定要严。
"""
from mods.write import _kw_of, _used_hit


def test_kw_of_优先用素材的topic标签():
    sucai = [{"topic": "创新·实干"}, {"topic": "奉献·为民"}, {"topic": "担当"}, {"topic": "坚持"}]
    kws = _kw_of(sucai, [])
    assert "创新" in kws and "实干" in kws, "topic 里的词没抠出来"
    assert "奉献" in kws


def test_kw_of_topic不够时从正文补高频词():
    # topic 只有一个，不足 4 个 → 从 content 补。注意 [一-龥]{2,4} 贪婪，
    # "基层治理" 会被整体抓成一个 4 字词（不是拆成"基层"+"治理"）。
    sucai = [{"topic": "创新", "content": "基层治理基层治理基层治理"}]
    kws = _kw_of(sucai, [], n=8)
    assert len(kws) >= 2, "topic 不够时没从正文补词"
    assert "基层治理" in kws, f"补的词不对：{kws}"


def test_used_hit_成语词头出现即算用了():
    # 「高瞻远瞩：形容…」这类，词本身出现在正文即可
    assert _used_hit("高瞻远瞩：形容眼光远大", "领导干部要有高瞻远瞩的战略眼光") is True
    assert _used_hit("高瞻远瞩：形容眼光远大", "这段正文里根本没提那个词") is False


def test_used_hit_模板要半数以上片段命中():
    tpl = "只有…才能…"
    assert _used_hit(tpl, "只有坚持改革才能实现发展") is True, "两个骨架片段都在，该算命中"
    assert _used_hit(tpl, "这里什么骨架都没有") is False


def test_used_hit_事例要实词短语出现():
    # body 里 [一-龥]{4,12} 贪婪抓成整串短语，要正文含这个短语才算命中
    # （靠自然标点断句：这里 body 无标点，整串「绿水青山就是金山银山」是一个 token）
    item = "（理论·生态）绿水青山就是金山银山"
    assert _used_hit(item, "牢固树立绿水青山就是金山银山的理念") is True, "事例短语出现了却没判命中"
    assert _used_hit(item, "完全无关的一段话") is False


def test_used_hit_空输入算没用():
    assert _used_hit("", "任意正文") is False
    assert _used_hit(None, "任意正文") is False
