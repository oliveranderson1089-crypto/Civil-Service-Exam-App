"""zinnia 模块：手写笔迹归一化 _zinnia_norm。

zinnia 改动 1 次、零测试。手写识别前要把笔迹按外接框居中、缩放到统一大小的方框里
（不管写在画布哪、写多大，喂给识别引擎的都一样），识别率比按画布尺寸归一化高很多。
盯：空笔迹不炸、缩放后落在方框内、居中（短边两侧均匀补空）、等比不拉伸。

输入 ink：每个笔画是 [xs, ys]（两条平行数组）。
输出 out：每个笔画是 [(x, y), …] 点列表。—— 两头格式不同，别搞混。
"""
from mods.zinnia import _zinnia_norm


def _xy(stroke):
    """从输出笔画（点列表）里拆出 xs, ys。"""
    return [p[0] for p in stroke], [p[1] for p in stroke]


def test_空笔迹返回空不炸():
    out, side = _zinnia_norm([])
    assert out == []
    assert side == 256


def test_归一化后所有点落在方框内():
    # 一条斜线，写在画布右下角一小块
    ink = [[[500, 520, 540], [600, 620, 640]]]
    out, side = _zinnia_norm(ink, side=256)
    for st in out:
        for x, y in st:
            assert 0 <= x <= side, f"x={x} 跑出方框 [0,{side}]"
            assert 0 <= y <= side, f"y={y} 跑出方框 [0,{side}]"


def test_居中_短边两侧补空对称():
    # 宽扁的字（宽 100、高 20，非退化）：归一化后纵向该居中，上下留白对称。
    # 用非零高度避开 bh=max(1.0,…) 对退化笔画的钳位；容差留 3 覆盖 int() 截断。
    ink = [[[0, 100, 100, 0], [0, 0, 20, 20]]]
    out, side = _zinnia_norm(ink, side=256, pad_ratio=0.0)
    _, ys = _xy(out[0])
    top_gap = min(ys)
    bot_gap = side - max(ys)
    assert abs(top_gap - bot_gap) < 3.0, f"没居中：上留白 {top_gap} vs 下留白 {bot_gap}"


def test_保持长宽比_不拉伸():
    # 正方形轮廓归一化后仍是正方形（等比缩放，不各拉各的）
    ink = [[[0, 100, 100, 0], [0, 0, 100, 100]]]
    out, side = _zinnia_norm(ink, side=256, pad_ratio=0.0)
    xs, ys = _xy(out[0])
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    assert abs(w - h) < 2.0, f"正方形被拉伸成了 {w}x{h}"
