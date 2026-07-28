# -*- coding: utf-8 -*-
"""材料归属：一份给定资料到底管哪几道题。

两条路各测各的 —— gap_materials 靠题与题之间的空隙找（卷子没写材料头时），
split_materials 靠材料头找（写了的时候）。后者出过的事故最贵：
一份材料一路管到下一个材料头为止，把言语理解的文章阅读挂到了后面 60 道
数量关系/判断推理题上，做定义判断前先读一篇讲云层细菌的文章。
"""
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


# ---------------------------------------------------------------- split_materials
def _q(seq):
    return ["%d、这里是第%d题的题干。" % (seq, seq), "A 甲    B 乙    C 丙    D 丁"]


def _split(lines, seqs, modules, figs=None):
    return M.split_materials("\n".join(lines), figs or {},
                             set(seqs), dict(modules))


def test_材料不许越过模块分节标题():
    """2023 国考副省级的原样：文章阅读的材料后面**紧跟着换模块**。

    原先一份材料一直管到下一个材料头（资料分析那份）为止，于是 56~115 共 60 道题
    全挂上了「降雨来源于云层」，连材料里那三张 -40℃/-15℃/-2℃ 的小图一起。
    """
    lines = ["言语理解与表达", "材料", "降雨来源于云层，云层中的水蒸气遇到冷空气" + "文" * 60]
    for s in (56, 57, 58, 59, 60):
        lines += _q(s)
    lines.append("数量关系")                      # ← 闸在这儿
    for s in (61, 62, 63):
        lines += _q(s)
    lines += ["资料分析", "材料", "某年统计表" + "数" * 40]
    for s in (116, 117, 118, 119, 120):
        lines += _q(s)

    mods = {s: "言语理解与表达" for s in (56, 57, 58, 59, 60)}
    mods.update({s: "数量关系" for s in (61, 62, 63)})
    mods.update({s: "资料分析" for s in (116, 117, 118, 119, 120)})
    got = _split(lines, mods, mods)
    assert [sorted(s) for _b, _p, s in got] == [
        [56, 57, 58, 59, 60], [116, 117, 118, 119, 120]], got


def test_材料头写明了范围就以它为准():
    """老卷子（2001~2008 国考）的材料是一张大表，表格行「5.4」「0.9」会被
       当成题号 5、0 —— 而 5 在这份卷子上真实存在。只有认头里那句
       「回答116～120题」才切得对。"""
    lines = ["资料分析", "一、根据下表回答116～120题。",
             "2001年、2002年全国高等学校各学科学生数(单位：千人)",
             "0.9", "5.4", "57.3", "359.9"]
    for s in (116, 117, 118, 119, 120):
        lines += _q(s)
    mods = {s: "资料分析" for s in (116, 117, 118, 119, 120)}
    mods.update({0: "言语理解与表达", 5: "言语理解与表达"})
    got = _split(lines, mods, mods)
    assert [sorted(s) for _b, _p, s in got] == [[116, 117, 118, 119, 120]], got
    assert "高等学校各学科学生数" in got[0][0], got[0][0]


def test_写明范围时题号断档也不丢尾巴():
    """老扫描卷里范围内有两道题没解析出来（题号断档 >2），也不能把材料头
       声明过的尾巴丢掉 —— 头写了「回答111~120题」就以它为准，不再套连续性兜底。"""
    lines = ["资料分析", "一、根据下表回答111～120题。", "某统计表" + "数" * 40,
             "1.1", "2.2", "3.3"]
    present = [111, 112, 115, 116, 117, 118, 119, 120]   # 113、114 没解析出来
    for s in present:
        lines += _q(s)
    mods = {s: "资料分析" for s in present}
    got = _split(lines, mods, mods)
    assert [sorted(s) for _b, _p, s in got] == [present], got


def test_题号行不是材料头():
    """「52、根据所给材料，以下哪一项…」是题干：前缀那段「52、」正好被材料头
       正则里的可选序号吃掉。当成材料头的话，这道题自己的四个选项成了材料正文
       （实测存出来「A、实时成像 B、检测大脑氧气含量…」）。"""
    lines = ["言语理解与表达", "材料", "①注意力不集中是常有之事。" + "文" * 60]
    lines += ["56、根据所给材料，功能性核磁共振成像技术能够：",
              "A、实时成像   B、检测大脑氧气含量   C、判断脑区   D、监测磁导率"]
    lines += _q(57)
    mods = {56: "言语理解与表达", 57: "言语理解与表达"}
    got = _split(lines, mods, mods)
    assert len(got) == 1, got
    assert "注意力不集中" in got[0][0] and "实时成像" not in got[0][0], got[0][0]


def test_以阿拉伯题号打头但写了范围的仍是材料头():
    """「题号行不是材料头」那条闸不能一刀切：材料头本身以阿拉伯数字编号、
       又写明了范围（「116、根据下表回答117~120题」）时，它是真材料头，不能误杀。
       靠「写没写范围」把它和真题干（「52、根据所给材料，以下哪一项…」）区分开。"""
    lines = ["资料分析", "116、根据下表回答117～120题。", "某统计表" + "数" * 40]
    for s in (117, 118, 119, 120):
        lines += _q(s)
    mods = {s: "资料分析" for s in (117, 118, 119, 120)}
    got = _split(lines, mods, mods)
    assert [sorted(s) for _b, _p, s in got] == [[117, 118, 119, 120]], got
    assert "某统计表" in got[0][0], got[0][0]


def test_材料只管它所在模块的题():
    """材料长在资料分析节里，就管不到言语理解的第 2~5 题 ——
       表格里的「2.5」「3.2」被当成题号时，靠这条闸兜住。"""
    lines = ["言语理解与表达"] + _q(2) + _q(3)
    lines += ["资料分析", "（四）", "表1：2001至2005年世界主要国家经济增长率" + "数" * 40,
              "2.5", "3.2"]
    for s in (131, 132, 133, 134, 135):
        lines += _q(s)
    mods = {2: "言语理解与表达", 3: "言语理解与表达"}
    mods.update({s: "资料分析" for s in (131, 132, 133, 134, 135)})
    got = _split(lines, mods, mods)
    assert [sorted(s) for _b, _p, s in got] == [[131, 132, 133, 134, 135]], got
