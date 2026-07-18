"""sucai 模块：每日素材解析 _sucai_parse。

sucai 改动 1 次、零测试。把 kaogong-cache 生成的素材文本解析成 [(类别, 主题, 正文)]。
文本用【人物事例】这类小节头分类，条目是「1. …」或「· …」，条目里若带【主题】要拆出来。
兼容早期没有小节头的旧格式。解析错了素材库分类就乱、主题标签丢。
"""
from mods.sucai import _sucai_parse


def test_按小节头分类():
    text = "【人物事例】\n1. 张三的故事\n【理论论据】\n2. 某句名言"
    items = _sucai_parse(text)
    kinds = [k for k, _, _ in items]
    assert len(items) == 2
    assert kinds[0] != kinds[1], "两个小节的类别没区分开"


def test_拆出条目里的主题():
    items = _sucai_parse("【人物事例】\n1. 【坚持】王进喜铁人精神")
    assert len(items) == 1
    kind, topic, body = items[0]
    assert topic == "坚持", "主题【坚持】没拆出来"
    assert "王进喜" in body
    assert "【坚持】" not in body, "主题标记残留在正文里"


def test_编号和圆点两种条目符号都认():
    assert len(_sucai_parse("【事实论据】\n1. 甲\n2、乙\n· 丙")) == 3


def test_没主题的条目topic为空():
    items = _sucai_parse("【人物事例】\n1. 没有主题标记的一条")
    assert items[0][1] == ""


def test_空行和无关行忽略_不炸():
    items = _sucai_parse("\n\n随便一行没编号的\n\n【人物事例】\n1. 有效条目\n")
    assert len(items) == 1
    assert "有效条目" in items[0][2]
