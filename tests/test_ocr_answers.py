# -*- coding: utf-8 -*-
"""ocr_answers.py 的返回值契约。

写这个文件的由头是一个真事：tess_answers 从「返回 dict」改成「返回 (dict, synth)」时，
函数里三个 return 只改了最后一个，两个早退分支还在 `return {}`。
调用方 `got, synth = tess_answers(...)` 撞上就是 ValueError —— 而它只在
「pdftoppm 失败 / 渲不出页」时才走到，正常卷子一路顺，跑几十份都不一定碰上一次。
这种「返回值改了、早退分支没跟上」的静默断链，靠人眼复查是拦不住的。
"""
import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ocr_answers as O          # noqa: E402


def test_tess_answers_所有分支返回元数一致():
    """静态扫一遍所有 return —— 包括那些平时跑不到的早退分支。

    这里**不写死元数**：真正要守的不变式是「所有出口长得一样」，
    而不是「必须是二元组」。写死的话，往返回值里加一项时这个测试自己就先坏了，
    改测试的顺手一改，反而把它本来要防的漏改放过去。
    """
    src = open(O.__file__, encoding="utf-8").read()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "tess_answers")
    rets = [r for r in ast.walk(fn) if isinstance(r, ast.Return)]
    assert rets, "函数里一个 return 都没有？"
    arity = {(r.lineno, len(r.value.elts) if isinstance(r.value, ast.Tuple) else 1)
             for r in rets}
    assert len({n for _ln, n in arity}) == 1, \
        "各个 return 的元数对不上，调用方解包会炸：%s" % sorted(arity)


def test_tess_answers_渲染失败时不抛异常(tmp_path):
    """pdftoppm 渲不出东西（文件不存在/损坏）时，要安静地返回空，别把整轮带崩。"""
    out = O.tess_answers(str(tmp_path / "根本不存在.pdf"), str(tmp_path))
    assert out[0] == {} and out[1] is False


@pytest.mark.parametrize("name", ["PX_W", "PX_W_VIS", "PAPER_TIMEOUT", "LOW_YIELD"])
def test_关键常量还在(name):
    """按像素宽渲染是为了治 A0 页面（2381×3367pt）—— 谁要是改回固定 DPI，
    2024 国考那批会从 4 秒退回 50 秒，而且 tesseract 直接认不出来。"""
    assert getattr(O, name) > 0
