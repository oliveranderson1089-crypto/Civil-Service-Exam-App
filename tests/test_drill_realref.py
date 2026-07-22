"""专项练拿真题当范例时，**不能跨模块捞题**。

这守的是一个不报错、不崩、只让题慢慢跑偏的坑：题型标签有两个来源，
rq.qtype（解析器按规则判的）和 re.qtype（AI 顺手判的兜底），而后者不受模块约束。
线上实测「2012—2020年，中国IC封装市场规模同比增量最大的年份是：」被判成了
「语境分析」——它会作为**选词填空的真题范例**喂给出题模型，把出题风格带跑。

audit_qtype.py 量过：不卡模块时捞到的 5325 道里只有 68.7% 是对模块的。
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mods import realprofile  # noqa: E402
from mods.drill import _real_examples  # noqa: E402

# 篇幅画像走 realprofile（带进程级缓存），这里直接用它，别再包一层
_real_style = realprofile.get


@pytest.fixture(autouse=True)
def _no_cache():
    """画像缓存是进程级的，键只有 (板块, 题型)，不含库 —— 不清就会跨用例串。

    实测：预先往 _CACHE 塞一条假画像，TestStyleSample 当场失败。
    现在全绿只是因为 pytest 按文件名排序恰好让本文件先跑，
    加 -p randomly 或 xdist 分片就会变成偶发失败。
    """
    realprofile.clear()
    yield
    realprofile.clear()

OPTS = json.dumps(["甲说法", "乙说法", "丙说法", "丁说法"], ensure_ascii=False)


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE real_questions(id INTEGER PRIMARY KEY, module TEXT, qtype TEXT, "
                "stem TEXT, material TEXT, options TEXT, answer TEXT, has_answer INT, "
                "needs_asset INT, year_max INT)")
    con.execute("CREATE TABLE real_explains(qid INT, answer TEXT, qtype TEXT, agree INT)")
    return con


def _add(con, qid, module, qtype, stem, *, material="", ai_qtype=None, agree=1,
         has_answer=1, needs_asset=0, year=2024):
    con.execute("INSERT INTO real_questions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (qid, module, qtype, stem, material, OPTS, "A", has_answer, needs_asset, year))
    if ai_qtype is not None:
        con.execute("INSERT INTO real_explains VALUES(?,?,?,?)", (qid, "A", ai_qtype, agree))


class TestModuleFilter:
    def test_别的模块的题不能当本题型的范例(self):
        con = _db()
        # 干净的：言语理解与表达 的选词填空，rq.qtype 是规则判出来的
        _add(con, 1, "言语理解与表达", "语境分析", "填入划横线部分最恰当的一项是" + "语" * 60)
        # 脏的：资料分析的题，rq.qtype 为空，被 AI 兜底判成了「语境分析」
        _add(con, 2, "资料分析", "", "2012—2020年，中国IC封装市场规模同比增量最大的年份是：",
             ai_qtype="语境分析")
        got = _real_examples(con, "言语理解与表达", "语境分析", n=5)
        assert len(got) == 1, "资料分析的题被当成选词填空范例捞出来了"
        assert "IC封装" not in got[0]["q"]

    def test_同题型名跨模块也要分得开(self):
        """「削弱论证」在判断推理和常识判断底下都可能被判出来，捞的时候必须只要本模块的。"""
        con = _db()
        _add(con, 1, "判断推理", "削弱论证", "以下哪项如果为真，最能削弱上述结论？" + "推" * 40)
        _add(con, 2, "常识判断", "", "下列关于宪法的说法正确的是：", ai_qtype="削弱论证")
        got = _real_examples(con, "判断推理", "削弱论证", n=5)
        assert [g["q"][:6] for g in got] == ["以下哪项如果为真"[:6]]

    def test_政治理论要映射到常识判断(self):
        """政治理论在真题卷面上不是独立模块，题混在常识判断里。
           不映射的话 rq.module='政治理论' 永远查不到，一道范例都取不到。"""
        con = _db()
        _add(con, 1, "常识判断", "马克思主义基本原理", "关于唯物辩证法，下列说法正确的是：" + "马" * 30)
        assert len(_real_examples(con, "政治理论", "马克思主义基本原理", n=3)) == 1


class TestStyleSample:
    def test_篇幅分位只统计本模块的题(self):
        """脏样本会把分位数拉歪：资料分析题干很短，混进选词填空的样本里会把下限压低，
           于是模型写出来的短题也能过护栏。"""
        con = _db()
        for i in range(20):                       # 本模块：长题干
            _add(con, i + 1, "言语理解与表达", "语境分析", "语" * 200)
        for i in range(20):                       # 脏样本：短题干，混进来会把 10% 分位拉到 20 左右
            _add(con, 100 + i, "资料分析", "", "问哪年最大？", ai_qtype="语境分析")
        st = _real_style(con, "言语理解与表达", "语境分析")
        assert st is not None
        assert st["stem"][0] >= 200, "分位数被别的模块的短题干拉低了：%r" % (st["stem"],)

    def test_样本不足就不卡篇幅(self):
        """卡了模块之后政治理论会掉到样本线以下。**没有约束好过用错模块的约束** ——
           返回 None 让 _style_ok 直接放行，别拿常识判断的体量去要求马原题。"""
        con = _db()
        for i in range(5):
            _add(con, i + 1, "常识判断", "毛泽东思想", "毛" * 80)
        assert _real_style(con, "政治理论", "毛泽东思想") is None


class TestMaterial:
    """片段阅读/文章阅读的**文段存在 material 列**，题干只剩一句设问。

    只取 stem 的话，「范例」就是光秃秃一句「根据文章，下列说法正确的是：」——
    文段整个丢了，模型学不到任何东西，还会以为这类题的题干就该 14 个字。
    """
    PASSAGE = "文" * 400

    def test_范例要把材料一起给(self):
        con = _db()
        _add(con, 1, "言语理解与表达", "查找细节", "根据文章，下列说法正确的是：",
             material=self.PASSAGE)
        got = _real_examples(con, "言语理解与表达", "查找细节", n=3)
        assert len(got) == 1
        assert self.PASSAGE in got[0]["q"], "材料没给出去，范例只剩一句设问"
        assert got[0]["q"].endswith("根据文章，下列说法正确的是："), "设问要接在材料后面"

    def test_材料是字符串None时不能当材料(self):
        """这列早期存进过 Python None 格式化出来的 'None' 四个字。"""
        con = _db()
        _add(con, 1, "言语理解与表达", "概括主旨", "这" * 120, material="None")
        got = _real_examples(con, "言语理解与表达", "概括主旨", n=3)
        assert "None" not in got[0]["q"]

    def test_同一篇材料的多道题只留一道范例(self):
        """文章阅读是一篇文章配多问，这些行 material 完全相同。
           三道同文章的范例没有价值，但去重要显式按材料认，别靠前缀碰撞顺带实现。"""
        con = _db()
        for i in range(6):
            _add(con, i + 1, "言语理解与表达", "文章阅读", "第%d问，下列说法正确的是：" % i,
                 material=self.PASSAGE)
        _add(con, 99, "言语理解与表达", "文章阅读", "另一篇的问题：", material="另" * 400)
        got = _real_examples(con, "言语理解与表达", "文章阅读", n=3)
        assert len(got) == 2, "同一篇材料出了 %d 道范例" % len(got)

    def test_篇幅分位按材料加题干算(self):
        """短题干 + 长材料的题，不能被当成「这类题很短」。

        这是护栏自己失效的根因：分位下限被压到 20 上下，
        于是模型把片段阅读写成一句话也能过 _style_ok。
        """
        con = _db()
        for i in range(20):
            _add(con, i + 1, "言语理解与表达", "查找细节", "下列说法正确的是：",
                 material=self.PASSAGE)
        st = _real_style(con, "言语理解与表达", "查找细节")
        assert st["stem"][0] > 300, "材料没算进篇幅，下限被短题干拉到了 %d" % st["stem"][0]


class TestServable:
    """SERVABLE 口径：答案靠不住的题绝不当范例——拿去学错的答案比不学还糟。"""

    def test_没答案也没解析的不要(self):
        con = _db()
        _add(con, 1, "判断推理", "定义判断", "根据上述定义，下列属于……的是：" + "定" * 40,
             has_answer=0, ai_qtype=None)
        assert _real_examples(con, "判断推理", "定义判断", n=5) == []

    def test_缺图的不要(self):
        con = _db()
        _add(con, 1, "判断推理", "定义判断", "缺图的那道" + "图" * 40, needs_asset=1)
        assert _real_examples(con, "判断推理", "定义判断", n=5) == []

    def test_双模核验不一致的不要(self):
        """有解析行但 agree=0 —— 两个模型答案对不上，这题存疑。

        这条是 `has_answer=1 OR agree=1` 里最容易写错的一支：写成
        `agree IS NOT NULL` 的话，核验判为不一致的题会照发不误。
        """
        con = _db()
        _add(con, 1, "判断推理", "定义判断", "存疑的那道" + "疑" * 40,
             has_answer=0, ai_qtype="定义判断", agree=0)
        assert _real_examples(con, "判断推理", "定义判断", n=5) == []

    def test_原卷有答案就行不必等核验(self):
        con = _db()
        _add(con, 1, "判断推理", "定义判断", "原卷带答案的" + "答" * 40,
             has_answer=1, ai_qtype="定义判断", agree=0)
        assert len(_real_examples(con, "判断推理", "定义判断", n=5)) == 1
