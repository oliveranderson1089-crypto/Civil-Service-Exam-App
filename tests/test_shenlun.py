"""shenlun 模块：字数统计 _sl_words + 字数要求解析 _sl_word_range。

shenlun 改动 1 次、零测试。_sl_words 是前端 slWords 的后端对子 —— 考场超字数是真扣分的，
两端口径必须一致（去所有空白、标点计入）。前端已有 shenlun.test.js 钉同一口径，这里钉
后端这份，两边对齐就不会「前端说达标、后端判超」。
_sl_word_range 从「1000-1200字」「不超过200字」这类花样措辞里读出字数区间。
"""
import re

from mods.shenlun import _sl_words, _sl_word_range


def test_sl_words_去所有空白_标点计入():
    assert _sl_words("依法治国") == 4
    assert _sl_words("依法 治国") == 4, "半角空格算进去了"
    assert _sl_words("依法\n治国") == 4, "换行算进去了 —— 分段作答会被误判超字"
    assert _sl_words("依法治国，建设法治政府。") == 12, "标点该计入（与阅卷口径一致）"
    assert _sl_words("") == 0
    assert _sl_words(None) == 0


def test_sl_words_与前端口径一致():
    # 前端 slWords 与后端 _sl_words 都是「去 \s 空白后数长度」；同输入两端必须相等。
    # 这里用同一条正则算期望值，等于把前端那份口径钉在后端这份上。
    for s in ["依法治国", "  首尾空格  ", "标点，。！也算", "跨\n行\t作答"]:
        assert _sl_words(s) == len(re.sub(r"\s+", "", s)), f"「{s}」的字数与去空白长度不符"


def test_word_range_区间式():
    assert _sl_word_range("字数1000-1200字") == (1000, 1200)
    assert _sl_word_range("要求 800~1000 字") == (800, 1000)


def test_word_range_不超过_取八成到上限():
    lo, hi = _sl_word_range("概括，不超过200字")
    assert (lo, hi) == (160, 200), "「不超过N字」该给 [0.8N, N]"


def test_word_range_不少于_取下限到1点3倍():
    lo, hi = _sl_word_range("不少于1000字")
    assert (lo, hi) == (1000, 1300)


def test_word_range_左右以内():
    assert _sl_word_range("300字左右") == (255, 300)


def test_word_range_读不出返回None():
    assert _sl_word_range("请概括主要内容") == (None, None)
