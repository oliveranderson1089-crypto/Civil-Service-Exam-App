"""dailytest 模块：资料分析材料校验 _dtest_ok_material。

dailytest 改动 1 次、零测试。程序生成的图形/资料分析题，材料必须是干净的结构化数据 ——
表格要有表头和非空行、图表的每个系列 data 长度要对齐 labels 且**数字真是数字**。校验松了
就会生成出画不出来/对不上的坏题（前端 dtChart/dtTable 拿到脏数据会崩或错位）。

注：函数是「真值=合法/假值=非法」的契约，实际混用了 bool 与 [] 做返回值
（and 链短路会漏出空 rows 列表），所以断言用真假值而非 is True/False。
"""
from mods.dailytest import _dtest_ok_material


def test_合法表格通过():
    assert _dtest_ok_material({"type": "table", "headers": ["项目", "2023"], "rows": [["GDP", "100"]]})


def test_表格缺表头或空行不通过():
    assert not _dtest_ok_material({"type": "table", "headers": [], "rows": [["a"]]})
    assert not _dtest_ok_material({"type": "table", "headers": ["x"], "rows": []})


def test_合法柱状图通过():
    m = {"type": "bar", "labels": ["一季度", "二季度"], "series": [{"name": "增速", "data": [7.2, 6.8]}]}
    assert _dtest_ok_material(m)


def test_系列data长度与labels对不上不通过():
    m = {"type": "line", "labels": ["一", "二", "三"], "series": [{"name": "x", "data": [1, 2]}]}
    assert not _dtest_ok_material(m), "data 只有 2 个却有 3 个 labels，画出来会错位"


def test_data里混了非数字不通过():
    m = {"type": "pie", "labels": ["甲", "乙"], "series": [{"name": "x", "data": [50, "多"]}]}
    assert not _dtest_ok_material(m), "「多」不是数字，图表算不了"


def test_非dict或缺字段不通过_不炸():
    assert not _dtest_ok_material(None)
    assert not _dtest_ok_material("字符串")
    assert not _dtest_ok_material({"type": "bar", "labels": [], "series": []})
