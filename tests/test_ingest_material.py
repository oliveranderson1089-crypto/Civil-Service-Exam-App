# -*- coding: utf-8 -*-
"""gap_materials：没有文字材料头时，靠题与题之间的空隙找材料。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ingest_material as M          # noqa: E402


def _paper(groups):
    """造一份资料分析卷：groups = [(材料行, 有没有图, [题号])]。"""
    lines, figs, qmark = [], {}, []
    for body, has_fig, seqs in groups:
        if body:
            lines.append(body)
        if has_fig:
            figs[len(lines)] = [(b"\x89PNG" + b"x" * 900, ".png")]
            lines.append("")
        for s in seqs:
            qmark.append((len(lines), s))
            lines.append("%d、这里是第%d题的题干。" % (s, s))
            lines.append("A 甲    B 乙    C 丙    D 丁")
    return lines, figs, qmark


def test_图和纯文字材料混在一起也要各归各的():
    """实测 2004 国考 A 卷：前两份材料是统计表图片，第三份是 602 字的纯文字段落。

    只按图分组的话，纯文字那 5 道题会被并进上一份材料，整组配错表。
    """
    lines, figs, qmark = _paper([
        ("1998～2002年广东省各类投资增长变化情况表％", True, [87, 88, 89, 90, 91]),
        ("注：增速指与去年同期相比" + "补" * 30, True, [92, 93, 94, 95, 96]),
        ("2003年6月份国房景气指数达到107.04" + "文" * 300, False, [97, 98, 99, 100, 101]),
    ])
    got = M.gap_materials(lines, figs, qmark, set(range(87, 102)))
    assert len(got) == 3, [(len(b), len(f), sorted(s)) for b, f, s in got]
    assert [sorted(s) for _b, _f, s in got] == [
        [87, 88, 89, 90, 91], [92, 93, 94, 95, 96], [97, 98, 99, 100, 101]]
    assert len(got[0][1]) == 1 and len(got[2][1]) == 0, "图没有各归各的材料"


def test_材料可以一个字都没有():
    """2022 国考副省级那几份，图前面连表标题都没有 —— 图本身就是材料。"""
    lines, figs, qmark = _paper([
        ("", True, [116, 117, 118, 119, 120]),
        ("", True, [121, 122, 123, 124, 125]),
    ])
    got = M.gap_materials(lines, figs, qmark, set(range(116, 126)))
    assert len(got) == 2 and all(len(f) == 1 for _b, f, _s in got), got


def test_只在资料分析的题上找():
    """别的模块的题不参与分组 —— 它们的「空隙」是题干，不是材料。"""
    lines, figs, qmark = _paper([("某材料" + "文" * 40, True, [1, 2, 3, 4, 5])])
    assert M.gap_materials(lines, figs, qmark, set()) == []


def test_题太少就不猜():
    lines, figs, qmark = _paper([("某材料" + "文" * 40, True, [1, 2])])
    assert M.gap_materials(lines, figs, qmark, {1, 2}) == []


def test_排版噪声不进材料正文():
    """「第五部分 资料分析」「请开始答题」这些是版面说明，不是材料。"""
    lines, figs, qmark = _paper([("", True, [116, 117, 118, 119, 120])])
    lines.insert(0, "第五部分 资料分析")
    lines.insert(1, "请开始答题：")
    qmark = [(i + 2, s) for i, s in qmark]
    figs = {k + 2: v for k, v in figs.items()}
    got = M.gap_materials(lines, figs, qmark, set(range(116, 121)))
    assert got and "资料分析" not in got[0][0] and "请开始答题" not in got[0][0], got[0][0]
