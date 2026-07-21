"""真题入库的回归测试：配对、指纹、去重判据。

和 test_realbank.py 一样，每条都对应一个真踩过的坑。最贵的两条：
· 答案卷配错 —— 2005 国考卷（一）拿到了卷（二）的答案，124 题里 123 题相同；
· 选项指纹排序 —— A/B 卷同题不同选项顺序被并成一条，答案字母当场失效。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ingest_real as I  # noqa: E402


class TestOhash:
    def test_选项顺序不同就不是同一条(self):
        """**绝不能排序**。答案存的是字母、字母指的是位置：
        2003 国考 A/B 卷的「倾销」定义题，正确项 A 卷排在 D、B 卷排在 C，
        排序后指纹相同被合并，留下的答案字母就有一半是错的。"""
        a = ["低于成本销售", "科技降低成本", "垄断定价", "政府补贴"]
        b = ["科技降低成本", "低于成本销售", "垄断定价", "政府补贴"]
        assert I.ohash_of(a) != I.ohash_of(b)

    def test_同样顺序同样内容才算同一条(self):
        a = ["甲选项", "乙选项", "丙选项", "丁选项"]
        assert I.ohash_of(a) == I.ohash_of(list(a))

    def test_排版差异不影响指纹(self):
        assert I.ohash_of(["甲（ ）", "乙", "丙", "丁"]) == I.ohash_of(["甲(  )", "乙", "丙", "丁"])


class TestFindAnswer:
    """_find_answer：精确配 → 同考试同年同卷别范围内按名字相似度兜底。"""

    @staticmethod
    def _idx(*names):
        import realbank as R
        out = {}
        for n, exam, year in names:
            out[(R.pair_key(n), R.variant_tokens(n))] = ({1: ("A", "")}, False, n, exam, year)
        return out

    def test_差一个字也能兜住(self):
        """题目卷写「行政执法类」、答案卷写「行政执法」——精确配不上，靠相似度兜。"""
        idx = self._idx(("2022年国家公务员考试《行测》真题（行政执法）【答案+解析】.pdf", "国考", 2022))
        got = I._find_answer(idx, "2022 年国家公务员考试行测真题（行政执法类）.docx",
                             {"exam": "国考", "year": 2022})
        assert got is not None and "行政执法" in got[2]

    def test_卷别不同绝不兜底(self):
        """名字相似度 0.97 也不许配 —— 卷别令牌是硬约束，这是头号事故的防线。"""
        idx = self._idx(("2005年国家公务员考试《行测》真题卷（二）答案及解析.pdf", "国考", 2005))
        got = I._find_answer(idx, "2005年国家公务员考试《行测》真题卷（一）.doc",
                             {"exam": "国考", "year": 2005})
        assert got is None

    def test_年份不同绝不兜底(self):
        idx = self._idx(("2021年国家公务员考试《行测》真题（副省级）答案及解析.pdf", "国考", 2021))
        got = I._find_answer(idx, "2022年国家公务员考试《行测》真题（副省级）.doc",
                             {"exam": "国考", "year": 2022})
        assert got is None


class TestMatchAnswers:
    QS = [{"seq": i, "synth_seq": 0} for i in range(1, 101)]

    def test_题号对得上就用(self):
        ans = {i: ("A", "") for i in range(1, 101)}
        got, why = I._match_answers(self.QS, (ans, False, "x.pdf", "国考", 2020))
        assert got and not why

    def test_题号对不上就整份不用(self):
        ans = {i: ("A", "") for i in range(500, 600)}
        got, why = I._match_answers(self.QS, (ans, False, "x.pdf", "国考", 2020))
        assert got == {} and "对不上" in why

    def test_本卷题号是编的就不敢挂答案(self):
        qs = [{"seq": i, "synth_seq": 1} for i in range(1, 101)]
        ans = {i: ("A", "") for i in range(1, 101)}
        got, why = I._match_answers(qs, (ans, False, "x.pdf", "国考", 2020))
        assert got == {} and "按顺序编" in why

    def test_答案卷题号丢了但块数对得上就能用(self):
        """文档里承诺过这道核对，先前没实现，白扔掉 13 份卷子约 1300 条答案。"""
        ans = {i: ("A", "") for i in range(1, 101)}      # 100 块，本卷最大题号也是 100
        got, why = I._match_answers(self.QS, (ans, True, "x.pdf", "国考", 2020))
        assert got and not why

    def test_答案卷题号丢了且块数对不上就拒用(self):
        ans = {i: ("A", "") for i in range(1, 98)}       # 97 块 ≠ 最大题号 100
        got, why = I._match_answers(self.QS, (ans, True, "x.pdf", "国考", 2020))
        assert got == {} and "对不上" in why


class TestMisalignGuard:
    """整卷答案错位的自检 —— 靠「解析和题干说的是不是一回事」。

    这条补的是跨卷投票的死角：2023 国考副省级和地市级两份答案卷**同时**错位，
    互相对照时谁也证不了谁的伪，18 处冲突又够不上 20% 阈值，就那么混过去了。
    实测错位的两份重合度 0.083/0.084，正常的 39 份在 0.23~0.47。
    """
    @staticmethod
    def _db(good_papers=6, bad_paper=True):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(I.SCHEMA)
        for p in range(1, good_papers + 1):
            con.execute("INSERT INTO real_papers(file_id,name,role,status) VALUES(?,?,'q','ok')",
                        (p, "好卷%d.docx" % p))
            for i in range(25):
                # 解析复述题干里的说法 = 对得上号。**两边都得超过 60 字**，
                # 否则被 alignment_scores 的长度门槛滤掉，压根进不了统计。
                stem = "关于宪法序言的法律效力第%d题下列说法正确的是" % i
                con.execute(
                    "INSERT INTO real_raw(paper_id,seq,stem,options,answer,explain,qhash,ohash) "
                    "VALUES(?,?,?,'[]','A',?,'','')",
                    (p, i, stem,
                     "本题考查宪法序言的法律效力。宪法序言是宪法的组成部分，"
                     "其中关于国家根本任务、根本制度的规定虽然大都不直接规定权利义务，"
                     "但同样具有法律效力。因此" + stem + "这一说法成立。"))
        if bad_paper:
            con.execute("INSERT INTO real_papers(file_id,name,role,status) VALUES(99,'错位卷.docx','q','ok')")
            for i in range(25):
                con.execute(
                    "INSERT INTO real_raw(paper_id,seq,stem,options,answer,explain,qhash,ohash) "
                    "VALUES(?,?,?,'[]','A',?,'','')",
                    (good_papers + 1, i,
                     "关于宪法序言的法律效力第%d题下列说法正确的是" % i,
                     # 必须超过 60 字，否则被 alignment_scores 的长度门槛滤掉，压根进不了统计
                     "本题考查经济常识。紧缩性货币政策是中央银行在经济过热、总需求大于总供给、"
                     "出现通货膨胀时采用的政策手段，旨在控制货币供应量、抬高利率，"
                     "从而减少投资、压缩需求。刺激社会总需求应当采用扩张性货币政策。"))
        con.commit()
        return con

    def test_错位卷被抓出来(self):
        con = self._db()
        assert I.quarantine_misaligned(con) is True
        bad = [r["name"] for r in con.execute("SELECT name FROM real_papers WHERE answers_ok=0")]
        assert bad == ["错位卷.docx"]

    def test_不误伤正常卷(self):
        con = self._db(bad_paper=False)
        assert I.quarantine_misaligned(con) is False
        assert con.execute("SELECT COUNT(*) FROM real_papers WHERE answers_ok=0").fetchone()[0] == 0

    def test_样本太少时不下判断(self):
        """卷子太少，中位数不可信，宁可不判 —— 免得把小样本里的正常卷冤枉了。"""
        con = self._db(good_papers=2)
        assert I.quarantine_misaligned(con) is False

    def test_屏蔽的是答案不是底稿(self):
        con = self._db()
        I.quarantine_misaligned(con)
        # real_raw 是「原样提取、一条不落」的底稿，判定错位不该动它一个字
        n = con.execute("SELECT COUNT(*) FROM real_raw WHERE answer<>''").fetchone()[0]
        assert n == 25 * 7


class TestNeedsAsset:
    def test_资料分析整模块都要标(self):
        """题干里常连「资料」二字都不出现，靠措辞根本筛不出来。"""
        assert I.needs_asset("2011年该省GDP同比增长约：", False, "资料分析") == 1

    def test_通用题干要标(self):
        assert I.needs_asset("把下面的六个图形分为两类", True, "判断推理") == 1

    def test_普通文字题不标(self):
        assert I.needs_asset("下列关于宪法的说法正确的是：", False, "常识判断") == 0
