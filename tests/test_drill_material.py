"""AI 出题的**原料**：今天学的东西，要能变成今天的题。

题必须考我们库里有的东西，所以出题时喂素材 —— 但原先是全库 `ORDER BY RANDOM()`，
今天新学的 30 条常识淹在四百多条里，「今天学了 → 题库里出现」纯属碰运气。
dailytest 那边治过一次同样的病（原先全库 RANDOM，「巩固」两个字白叫），drill 这边还留着。

治法不是「只要新的」：连着几天拿同一批素材出题，AI 会翻来覆去出那几道，
全被判重复刷掉，一轮下来一道都进不了库。所以**一半新的、一半随机**。
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mods.drill as D  # noqa: E402


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE changshi_items(id INTEGER PRIMARY KEY, board TEXT, title TEXT,
            content TEXT, topic TEXT, date TEXT);
        CREATE TABLE theory_items(id INTEGER PRIMARY KEY, board TEXT, title TEXT,
            content TEXT, created_at TEXT);
        CREATE TABLE changkao_items(id INTEGER PRIMARY KEY, board TEXT, title TEXT,
            content TEXT, created_at TEXT);
    """)
    return c


def _cs(c, n, board="法律常识", when="2000-01-01", tag="旧"):
    for i in range(n):
        c.execute("INSERT INTO changshi_items(board,title,content,date) VALUES(?,?,?,?)",
                  (board, "%s考点%d" % (tag, i), "正文", when))


def _today(days=0):
    return "date('now','localtime','-%d day')" % days


class Test出题原料:
    def test_今天学的一定进得来(self, con):
        """400 条旧的压不住今天新学的 —— 这条不成立，「今天学了明天考」就是空话。"""
        _cs(con, 400, tag="旧")
        con.execute("INSERT INTO changshi_items(board,title,content,date) "
                    "VALUES('法律常识','今天新学的','正文',%s)" % _today())
        got = D._bank_material(con, "常识判断", "法律常识", n=14)
        assert any("今天新学的" in x for x in got)

    def test_不能全是新的(self, con):
        """一半随机是**故意**留的：连着几天喂同一批素材，AI 出的题会全被判重复刷掉。"""
        _cs(con, 50, when="2000-01-01", tag="旧")
        _cs(con, 50, when="2026-01-01", tag="新")     # 假装一大批都是「最近」的
        con.execute("UPDATE changshi_items SET date=%s WHERE title LIKE '新%%'" % _today())
        got = D._bank_material(con, "常识判断", "法律常识", n=14)
        assert len(got) == 14
        assert any("旧考点" in x for x in got), "全给新素材会让 AI 反复出同几道题"

    def test_不够就有多少给多少(self, con):
        _cs(con, 3)
        assert len(D._bank_material(con, "常识判断", "法律常识", n=14)) == 3

    def test_按题型取自己的素材(self, con):
        """题型名和素材表的 board 是同一套词，格子直接对得上，别串味。"""
        _cs(con, 5, board="法律常识", tag="法")
        _cs(con, 5, board="科技常识", tag="科")
        got = D._bank_material(con, "常识判断", "科技常识", n=14)
        assert got and all("科" in x for x in got)

    def test_政治理论走理论表(self, con):
        con.execute("INSERT INTO theory_items(board,title,content,created_at) "
                    "VALUES('毛泽东思想','实事求是','正文','2026-01-01 08:00:00')")
        assert D._bank_material(con, "政治理论", "毛泽东思想", n=14)

    def test_选词填空走常考词(self, con):
        con.execute("INSERT INTO changkao_items(board,title,content,created_at) "
                    "VALUES('成语','不孚众望','正文','2026-01-01 08:00:00')")
        assert D._bank_material(con, "言语理解与表达", "语境分析", n=4)

    def test_自己命制的题型不喂素材(self, con):
        """片段阅读这类不依赖词库，AI 自己写文段。"""
        assert D._bank_material(con, "言语理解与表达", "查找细节", n=14) == []


class Test新鲜度计数:
    """夜间补库靠它排序：一晚上的额度有限，先把今天学的变成题。"""

    def test_数最近几天新增的(self, con):
        _cs(con, 7, when="2000-01-01")
        _cs(con, 3, tag="新")
        con.execute("UPDATE changshi_items SET date=%s WHERE title LIKE '新%%'" % _today())
        assert D.fresh_material_n(con, "常识判断", "法律常识") == 3

    def test_对不上素材表的板块是0(self, con):
        """言语的片段阅读没有「今天学的」这回事，排在有新素材的后面天经地义。"""
        assert D.fresh_material_n(con, "言语理解与表达", "查找细节") == 0

    def test_表不存在也不炸(self):
        """这函数在夜间脚本的排序键里跑 —— 它抛异常，整晚的补库就没了。"""
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        assert D.fresh_material_n(c, "常识判断", "法律常识") == 0
