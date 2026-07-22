"""真题画像：出题模型不是不听话，是没人给它具体数字。

实测：提示词给区间（「题干 76~226 字」）时，模型一律往下限以下写 ——
语境分析真题中位数 123 字，AI 出 54~63 字，旧题库 116 道里只有 9% 落在真题区间。
改成给中位数 + 明确的不合格线 + 真题惯用设问句之后，区间内命中率 11% → 62%。

所以画像存的都是**能直接写进提示词的具体指标**，这里守的就是这几个指标别算歪。
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mods import realprofile  # noqa: E402


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE real_questions(id INTEGER PRIMARY KEY, module TEXT, qtype TEXT, "
                "stem TEXT, material TEXT, options TEXT, answer TEXT, has_answer INT, "
                "needs_asset INT, year_max INT)")
    con.execute("CREATE TABLE real_explains(qid INT, answer TEXT, qtype TEXT, agree INT)")
    return con


def _add(con, qid, stem, opts=("甲说法", "乙说法", "丙说法", "丁说法"), material="",
         module="言语理解与表达", qtype="语境分析"):
    con.execute("INSERT INTO real_questions VALUES(?,?,?,?,?,?,'A',1,0,2024)",
                (qid, module, qtype, stem, material,
                 json.dumps(list(opts), ensure_ascii=False)))


@pytest.fixture(autouse=True)
def _no_cache():
    """画像有进程级缓存，用例之间必须清掉。

    ⚠️ 别用 setup_function —— 那个只对模块级测试函数生效，类里的方法根本不会调用它，
    于是上一个用例的画像会漏给下一个（实测断言 med==100 拿到了 309）。
    """
    realprofile.clear()
    yield
    realprofile.clear()


class TestSample:
    def test_样本不足返回None(self):
        con = _db()
        for i in range(5):
            _add(con, i + 1, "语" * 100)
        assert realprofile.get(con, "言语理解与表达", "语境分析") is None

    def test_只统计本模块的题(self):
        """跨模块捞题是这套机制栽过的坑，画像这层也要挡住。"""
        con = _db()
        for i in range(20):
            _add(con, i + 1, "语" * 200)
        for i in range(20):        # 资料分析的短题，被 AI 兜底误判成语境分析
            _add(con, 100 + i, "问哪年最大？", module="资料分析", qtype="")
            con.execute("INSERT INTO real_explains VALUES(?,'A','语境分析',1)", (100 + i,))
        p = realprofile.get(con, "言语理解与表达", "语境分析")
        assert p["med"] == 200, "中位数被别的模块的短题拉歪了：%d" % p["med"]


class TestLength:
    def test_长度按材料加题干算(self):
        """片段阅读的文段存在 material 列，只量 stem 会把中位数压到十几个字。"""
        con = _db()
        for i in range(20):
            _add(con, i + 1, "下列说法正确的是：", material="文" * 300)
        p = realprofile.get(con, "言语理解与表达", "语境分析")
        assert p["med"] > 300

    def test_材料是字符串None时不算数(self):
        con = _db()
        for i in range(20):
            _add(con, i + 1, "语" * 100, material="None")
        assert realprofile.get(con, "言语理解与表达", "语境分析")["med"] == 100

    def test_残题不参与分位(self):
        """有一批题入库时材料没跟过来，只剩一句设问。它们不是「这类题的真实体量」，
           是数据缺陷 —— 混进来会把 10% 分位压到残题堆里，护栏跟着失效。"""
        con = _db()
        for i in range(20):
            _add(con, i + 1, "语" * 200)
        for i in range(6):         # 残题：只有 20 字
            _add(con, 100 + i, "语" * 20)
        p = realprofile.get(con, "言语理解与表达", "语境分析")
        assert p["stem"][0] > 100, "10%% 分位落在残题堆里了：%d" % p["stem"][0]


class TestAskForms:
    def test_惯用问法要数出来(self):
        con = _db()
        for i in range(20):
            _add(con, i + 1, "语" * 100 + "。填入画横线部分最恰当的一项是：")
        assert "填入画横线部分最恰当的一项是：" in realprofile.get(
            con, "言语理解与表达", "语境分析")["ask"]

    def test_问法太分散就不给(self):
        """常识判断那种设问五花八门的题型，硬给几个「高频句式」等于让模型照抄某一种问法。"""
        con = _db()
        for i in range(30):
            _add(con, i + 1, "语" * 100 + "。第%d种完全不同的问法是什么呢：" % i)
        assert realprofile.get(con, "言语理解与表达", "语境分析")["ask"] == []

    def test_只在末尾名词上变的问法要归到一起(self):
        """削弱论证的问法是「…最能削弱上述结论 / 上述论证 / 上述观点」「…最能质疑上述结论」。

        按整串精确计数会打散成 9+8+6+5 四小堆，集中度只有 12%，直接被判「太分散」
        而拿不到提示——可它明明有惯用问法。按前 12 字归组就并到一起了。
        """
        con = _db()
        tails = ["最能削弱上述结论", "最能削弱上述论证", "最能削弱上述观点", "最能削弱上述看法"]
        for i in range(24):
            _add(con, i + 1, "论" * 100 + "。以下哪项如果为真，" + tails[i % 4])
        ask = realprofile.get(con, "言语理解与表达", "语境分析")["ask"]
        assert ask, "四种变体被打散，一条惯用问法都没认出来"
        assert ask[0].startswith("以下哪项如果为真"), ask
        assert len(ask[0]) > 12, "报的是半截问法，模型会照抄半截：%r" % ask[0]

    def test_占位符不能当问法(self):
        """「（）」「____」会排到最前面，写进提示词就是喂噪声。"""
        con = _db()
        for i in range(20):
            _add(con, i + 1, "语" * 100 + "。（）")
        assert realprofile.get(con, "言语理解与表达", "语境分析")["ask"] == []


class TestBlanks:
    def test_选词填空数得出空数(self):
        con = _db()
        for i in range(20):        # 两空：选项是「词A 词B」
            _add(con, i + 1, "语" * 100, opts=("与众不同 言简意赅", "独树一帜 字斟句酌",
                                              "遥遥领先 删繁就简", "迎难而上 惜墨如金"))
        assert realprofile.get(con, "言语理解与表达", "语境分析")["blanks"] == {2: 100}

    def test_整句选项里的空格不算空(self):
        """中文选项本来没空格。削弱论证那种整句选项混进几个多余空格，
           会被数成「2 空」——实测算出 {1:85,2:6,3:2,4:7}，看着像模像样其实全是噪声，
           写进提示词就是让模型去凑根本不存在的空。"""
        con = _db()
        for i in range(20):
            opts = ("以下哪项 如果为真", "第二个完整的句子选项", "第三个完整的句子选项",
                    "第四个完整的句子选项")
            _add(con, i + 1, "语" * 100, opts=opts)
        assert realprofile.get(con, "言语理解与表达", "语境分析")["blanks"] == {}


class TestPromptLines:
    def test_给中位数而不是区间(self):
        con = _db()
        for i in range(20):                       # 100~290 字，中位数 200、p10 约 110
            _add(con, i + 1, "语" * (100 + i * 10))
        p = realprofile.get(con, "言语理解与表达", "语境分析")
        txt = realprofile.prompt_lines(p)
        assert "%d 字上下" % p["med"] in txt, txt
        assert "%d 字一律判不合格" % int(p["med"] * 0.8) in txt, "缺少不合格线，模型会一路往短里写"

    def test_不合格线不能低于护栏真实下限(self):
        """提示词说的线和 _style_ok 收的线必须同向。

        右偏分布下 med×0.8 会算出比 p10 还低的数，模型照着写就会被护栏成批拦掉，
        产出崩掉而日志只显示「体量不像真题」—— 白白烧一次 AI 调用。
        """
        con = _db()
        for i in range(19):                       # 挤在 100 字：p10=100
            _add(con, i + 1, "语" * 100)
        _add(con, 99, "语" * 900)                  # 一条超长的把中位数往上拽
        p = realprofile.get(con, "言语理解与表达", "语境分析")
        txt = realprofile.prompt_lines(p)
        assert "%d 字一律判不合格" % max(int(p["med"] * 0.8), p["stem"][0]) in txt
        assert p["stem"][0] <= max(int(p["med"] * 0.8), p["stem"][0]), "不合格线低于护栏下限"

    def test_没画像就不加任何指标(self):
        assert realprofile.prompt_lines(None) == ""
