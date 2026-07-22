"""按题型的限时，和错题本的「来源身份」。

这两件事都属于**坏了也不报错**的那一类，所以得有测试盯着：
  · 限时回退链断了 —— 界面照样出一个钟，只是所有题都变成 60 秒，看不出来；
  · 来源身份对不上 —— 做题界面显示「未收录」，点一下收出第二条，
    错题本越刷越多重复题，也是一声不响。
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mods.drill as D  # noqa: E402
from mods import timing  # noqa: E402
from mods.wrongq import wq_key, wq_upsert  # noqa: E402


class TestTiming:
    """限时按题型给，不是板块一刀切。"""

    def test_题型优先于板块基准(self):
        # 同一个板块里差着两倍多：类比推理该抢时间，分析推理要列表排除
        assert timing.limit_of("判断推理", "类比推理") == 25
        assert timing.limit_of("判断推理", "分析推理") == 70
        assert timing.BOARD_SEC["判断推理"] == 45      # 板块基准夹在中间

    def test_题型判不出来时退回板块(self):
        """真题库里有 300 多道 module 有、qtype 空的题，不能因此没有计时。"""
        assert timing.limit_of("资料分析", "") == 60
        assert timing.limit_of("资料分析", "查无此题型") == 60

    def test_板块也没有时用默认值(self):
        assert timing.limit_of("", "") == timing.DEFAULT_SEC

    def test_板块简称要归一(self):
        """巩固测试的板块名是简称（「言语理解」），真题/专项练用全称。
           不归一的话，巩固测试的言语题会全部掉到默认值上。"""
        assert timing.limit_of("言语理解", "词语辨析") == timing.limit_of("言语理解与表达", "词语辨析")

    def test_题型名对板块名空也认得出(self):
        """真题库里 module 为空但 qtype 判出来了的题，按题型名跨板块找。"""
        assert timing.limit_of("", "定义判断") == 50

    def test_同名题型跨板块给的秒数一致(self):
        """政治四科在「常识判断」和「政治理论」两张表里都有。
           限时不一样的话，同一道题从两个入口进来会拿到两个倒计时。"""
        for t in ("马克思主义基本原理", "毛泽东思想", "中国特色社会主义理论体系",
                  "习近平新时代中国特色社会主义思想"):
            assert timing.limit_of("常识判断", t) == timing.limit_of("政治理论", t)


class TestWrongRef:
    """错题的来源身份 (src_kind, src_key)。"""

    def test_真题按真题id认不按题干(self):
        """在专项练的真题模式做错、和从「历年真题」做错，必须是同一条错题。
           按题干指纹认的话，两个入口拼出来的文本不同（一个带【真题】前缀），
           同一道题会各存一份，改了这条那条还在。"""
        it = {"q": "题干", "options": ["A", "B"], "real_id": 42}
        assert D.wrong_ref(it, "drill") == ("realq", "42")
        assert D.wrong_ref(it, "dtest") == ("realq", "42")     # 哪个模块进来都一样

    def test_没有真题id才用题干指纹(self):
        it = {"q": "AI 出的题", "options": ["A", "B"], "module": "常识判断"}
        kind, key = D.wrong_ref(it, "drill")
        assert kind == "drill" and len(key) == 16

    def test_指纹忽略标点和空白差异(self):
        """题干里改一个标点不算另一道题 —— 否则同一道题会收进来两条。"""
        assert wq_key("甲、乙合作，需要几天？") == wq_key("甲 乙合作 需要几天")

    def test_下发和入库算出同一个指纹(self):
        """/api/drill/quiz 下发时算的 key，必须和交卷入库时算的对得上。
           两边各拼一遍题干的话，图形题/材料题那两个前缀最容易漏。"""
        it = {"q": "选出问号处", "options": ["A", "B"], "module": "判断推理",
              "figs": {"seq": ["<svg/>"], "opts": []}, "source": "样式规律"}
        assert D.wrong_ref(it, "drill")[1] == wq_key(D.wrong_text(it))


@pytest.fixture
def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE wrong_questions(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT,
            board TEXT, question TEXT, image TEXT, answer TEXT, qtype TEXT, points TEXT,
            method TEXT, skill TEXT, steps TEXT, note TEXT, starred INT DEFAULT 0,
            src_kind TEXT, src_key TEXT, created_at TEXT, updated_at TEXT);
    """)
    return con


class TestUpsert:
    """同一道题只留一条，且不洗掉人工写过的内容。"""

    def test_重复收只留一条(self, db):
        f = {"board": "资料分析", "question": "题干", "note": "第一次"}
        wid1, new1 = wq_upsert(db, 1, "realq", "7", f)
        wid2, new2 = wq_upsert(db, 1, "realq", "7", dict(f, note="第二次"))
        assert new1 is True and new2 is False and wid1 == wid2
        assert db.execute("SELECT COUNT(*) FROM wrong_questions").fetchone()[0] == 1

    def test_第二遍做错不覆盖我写的笔记(self, db):
        """错题的价值在人工写的错因。第二遍又做错时自动收一次，
           如果把 note 覆盖成「来自真题练习」，写过的复盘就没了。"""
        wq_upsert(db, 1, "realq", "7", {"question": "题干", "note": "自动收的"})
        db.execute("UPDATE wrong_questions SET note='我总结的错因' WHERE src_key='7'")
        wq_upsert(db, 1, "realq", "7", {"question": "题干", "note": "又自动收一次"})
        assert db.execute("SELECT note FROM wrong_questions").fetchone()[0] == "我总结的错因"

    def test_空字段会被补上(self, db):
        """反过来，原先空着的字段该补 —— 第一次收时没解析，后来有了就该填进去。"""
        wq_upsert(db, 1, "realq", "7", {"question": "题干", "answer": ""})
        wq_upsert(db, 1, "realq", "7", {"question": "题干", "answer": "正确答案 C"})
        assert db.execute("SELECT answer FROM wrong_questions").fetchone()[0] == "正确答案 C"

    def test_认领没有来源的老错题(self, db):
        """加 src 列之前收的错题（当时靠全文相等去重）要能被认领，
           否则同一道题会以「有来源」「无来源」各存一条。"""
        db.execute("INSERT INTO wrong_questions(user_id,question,note) VALUES(1,'老题干','老笔记')")
        wid, new = wq_upsert(db, 1, "realq", "9", {"question": "老题干"})
        assert new is False, "没认领，又收了一条新的"
        row = db.execute("SELECT * FROM wrong_questions").fetchone()
        assert row["src_key"] == "9" and row["note"] == "老笔记"

    def test_不同用户互不干扰(self, db):
        wq_upsert(db, 1, "realq", "7", {"question": "题干"})
        _, new = wq_upsert(db, 2, "realq", "7", {"question": "题干"})
        assert new is True
        assert db.execute("SELECT COUNT(*) FROM wrong_questions").fetchone()[0] == 2
