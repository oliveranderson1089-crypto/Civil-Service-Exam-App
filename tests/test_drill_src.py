"""专项练的**题源开关**：真题练习 / AI 出题 / 混合。

这不是两套功能，是同一个板块下的两个题源：
  real —— 答案权威、风格 100% 真实，但就那么几千道，做完不会再有
  ai   —— 无限量、考点可控，风格靠 realprofile 那套画像往真题上对齐
  mix  —— 真题优先填，不够的用 ai 补

真题模式**没有 easy/mid/real 三档**：真题不带难度标签，硬套是假的
（原先「考场真实」这一档发的其实是 AI 题，名不副实）。改成按年份筛。
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mods.drill as D  # noqa: E402

OPTS = json.dumps(["甲说法", "乙说法", "丙说法", "丁说法"], ensure_ascii=False)


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(D, "uid", lambda: 1)      # 取题要按「我做过没」排序
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE real_questions(id INTEGER PRIMARY KEY, module TEXT, qtype TEXT,
            stem TEXT, material TEXT, options TEXT, answer TEXT, has_answer INT,
            needs_asset INT, year_max INT);
        CREATE TABLE real_explains(qid INT, answer TEXT, qtype TEXT, agree INT,
            keypoint TEXT, steps TEXT, tip TEXT);
        CREATE TABLE real_attempts(id INTEGER PRIMARY KEY, user_id INT, qid INT,
            choice TEXT, correct INT, seconds REAL);
        CREATE TABLE real_figs(id INTEGER PRIMARY KEY, qid INT, ord INT, sha TEXT, ext TEXT);
        CREATE TABLE drill_bank(id INTEGER PRIMARY KEY, board TEXT, qtype TEXT, level TEXT,
            q TEXT, options TEXT, answer TEXT, explain TEXT, tip TEXT, source TEXT,
            sig TEXT, agree TEXT);
    """)
    return con


def _real(con, qid, qtype="语境分析", module="言语理解与表达", year=2024, material=""):
    con.execute("INSERT INTO real_questions VALUES(?,?,?,?,?,?,'A',1,0,?)",
                (qid, module, qtype, "真题题干%d" % qid, material, OPTS, year))


def _bank(con, board, qtype, n, level="mid"):
    for i in range(n):
        con.execute("INSERT INTO drill_bank(board,qtype,level,q,options,answer,explain,tip,"
                    "source,sig,agree) VALUES(?,?,?,?,?,'B','解析','技巧','来源',?, '1')",
                    (board, qtype, level, "AI题干%d" % i, OPTS, "sig%d" % i))


class TestSrc:
    def test_real只发真题(self, db):
        for i in range(6):
            _real(db, i + 1)
        _bank(db, "言语理解与表达", "语境分析", 6)
        got = D._drill_gen(db, "言语理解与表达", "语境分析", 4, "mid", "real")
        assert len(got) == 4 and {x["src"] for x in got} == {"real"}
        assert all(x["real_id"] for x in got), "少了 real_id，交卷时没法写 real_attempts"

    def test_ai不发真题(self, db):
        for i in range(6):
            _real(db, i + 1)
        _bank(db, "言语理解与表达", "语境分析", 6)
        got = D._drill_gen(db, "言语理解与表达", "语境分析", 4, "mid", "ai")
        assert {x["src"] for x in got} == {"ai"}

    def test_mix真题优先不够才用AI补(self, db):
        """毛泽东思想这类题型真题只有个位数，正是 mix 的用武之地。"""
        for i in range(2):
            _real(db, i + 1, qtype="毛泽东思想", module="常识判断")
        _bank(db, "政治理论", "毛泽东思想", 6)
        got = D._drill_gen(db, "政治理论", "毛泽东思想", 5, "mid", "mix")
        kinds = [x["src"] for x in got]
        assert kinds.count("real") == 2 and kinds.count("ai") == 3
        assert kinds[:2] == ["real", "real"], "真题没排在前面"

    def test_真题不够时mix不静默降级(self, db):
        """每道题都带 src，调用方能看出哪道是真题、哪道是 AI 出的。"""
        _real(db, 1)
        _bank(db, "言语理解与表达", "语境分析", 6)
        got = D._drill_gen(db, "言语理解与表达", "语境分析", 4, "mid", "mix")
        assert all("src" in x for x in got)


class TestOrder:
    def test_没做过的排前面(self, db):
        for i in range(1, 5):
            _real(db, i)
        db.execute("INSERT INTO real_attempts(user_id,qid,choice,correct) VALUES(1,1,'A',1)")
        db.execute("INSERT INTO real_attempts(user_id,qid,choice,correct) VALUES(1,2,'B',0)")
        got = D._drill_gen(db, "言语理解与表达", "语境分析", 4, "mid", "real")
        order = [x["real_id"] for x in got]
        assert set(order[:2]) == {3, 4}, "做过的题排到前面去了：%s" % order
        assert order[2] == 2, "做错过的应该排在做对过的前面：%s" % order

    def test_年份筛选(self, db):
        _real(db, 1, year=2018)
        _real(db, 2, year=2024)
        got = D._drill_gen(db, "言语理解与表达", "语境分析", 4, "mid", "real", year_min=2021)
        assert [x["real_id"] for x in got] == [2]


class TestPayload:
    def test_材料是纯文本原样带出(self, db):
        """真题的材料是一段文字，不是 figgen 那种 {type:'table'} 结构体 ——
           前端 dtMaterial 要能认字符串，否则会渲染出一张空图。"""
        _real(db, 1, qtype="比重", module="资料分析", material="2023 年甲市 GDP 为…")
        got = D._drill_gen(db, "资料分析", "比重", 1, "mid", "real")
        assert got[0]["material"] == "2023 年甲市 GDP 为…"

    def test_材料是字符串None时当没有(self, db):
        _real(db, 1, material="None")
        assert D._drill_gen(db, "言语理解与表达", "语境分析", 1, "mid", "real")[0]["material"] == ""

    def test_没有真题表也不崩(self, monkeypatch):
        """新库还没导真题，专项练本身照常能用。"""
        monkeypatch.setattr(D, "uid", lambda: 1)
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        assert D._real_take(con, "言语理解与表达", "语境分析", 4) == []
        assert D._real_count(con, "言语理解与表达", "语境分析") == 0


class TestCount:
    def test_存量少的要报出来给前端置灰(self, db):
        """政治理论四个题型真题只有个位数、文章阅读一道都没有 ——
           这种就该明说「没有」，不该假装有。"""
        for i in range(3):
            _real(db, i + 1)
        assert D._real_count(db, "言语理解与表达", "语境分析") == 3
        assert 3 < D._REAL_SRC_MIN, "阈值定得太低，两三道题刷两轮就重复了"
