"""夜间补库的**水位口径**：按人算，不按库存。

为什么换：做题不消耗库存（题发出去既不删也不标记），所以纯库存数一旦补满就永远是满的。
真实发生过 —— 一格 30 道躺着、人早做掉 18 道，这个脚本连着一周判「已经都满了，不用补」，
而库里其实只剩 12 道新题可做。库存满 ≠ 有题做。

补出来的是**谁都没做过**的新题，所以按「做过题的人里最少的那个」算就够了：
把他补够，所有人自然都够。
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import warm_drill_bank as W  # noqa: E402

BOARD, QTYPE, LV = "政治理论", "毛泽东思想", "mid"


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE drill_bank(id INTEGER PRIMARY KEY, board TEXT, qtype TEXT, level TEXT,
            sig TEXT UNIQUE, agree TEXT);
        CREATE TABLE drill_seen(user_id INTEGER, sig TEXT, n INTEGER DEFAULT 1,
            last_at TEXT, PRIMARY KEY(user_id, sig));
    """)
    return c


def _bank(c, n, agree="1"):
    for i in range(n):
        c.execute("INSERT INTO drill_bank(board,qtype,level,sig,agree) VALUES(?,?,?,?,?)",
                  (BOARD, QTYPE, LV, "sig%d" % i, agree))


def _seen(c, user, k):
    """这个人做掉头 k 道。"""
    for i in range(k):
        c.execute("INSERT INTO drill_seen(user_id,sig,last_at) VALUES(?,?,'2026-01-01')",
                  (user, "sig%d" % i))


def _usable(c, users=()):
    return W.usable(c, BOARD, QTYPE, LV, users)


class Test水位口径:
    def test_没人做过题就是纯库存(self, con):
        """新库、或者谁都还没开始刷：行为跟以前一模一样。"""
        _bank(con, 30)
        assert _usable(con) == 30 and W.active_users(con) == []

    def test_做过的不算数(self, con):
        """就是这条让脚本从「永远满」变回会补：30 道做掉 18 道 → 只剩 12 道新题。"""
        _bank(con, 30)
        _seen(con, 1, 18)
        assert _usable(con, [1]) == 12

    def test_按最惨的那个人算(self, con):
        """补的是谁都没做过的新题：把最惨的补够，其他人自然够。"""
        _bank(con, 30)
        _seen(con, 1, 18)
        _seen(con, 2, 5)
        assert _usable(con, [1, 2]) == 12

    def test_存疑题一如既往不算(self, con):
        """两个筛子是叠着的，不是二选一。"""
        _bank(con, 10)
        con.execute("INSERT INTO drill_bank(board,qtype,level,sig,agree) "
                    "VALUES(?,?,?,'sig-bad','0')", (BOARD, QTYPE, LV))
        _seen(con, 1, 4)
        assert _usable(con, [1]) == 6

    def test_做过题的人认得出(self, con):
        _bank(con, 5)
        _seen(con, 2, 3)
        assert W.active_users(con) == [2]

    def test_没有drill_seen表也不炸(self):
        """旧库还没跑迁移：退回纯库存口径，别让夜里的定时任务整个失败。"""
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute("CREATE TABLE drill_bank(id INTEGER PRIMARY KEY, board TEXT, qtype TEXT, "
                  "level TEXT, sig TEXT, agree TEXT)")
        _bank(c, 7)
        assert W.active_users(c) == [] and _usable(c) == 7


class Test补库顺序:
    """一晚上的轮次和额度都有限，可能补不完所有缺口 —— 那就先把今天学的变成题。"""

    SHORT = [("常识判断", "经济常识", "mid", 24),
             ("言语理解与表达", "查找细节", "mid", 21),
             ("常识判断", "科技常识", "mid", 12),
             ("常识判断", "法律常识", "mid", 16)]

    @pytest.fixture
    def con(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute("CREATE TABLE changshi_items(id INTEGER PRIMARY KEY, board TEXT, "
                  "title TEXT, content TEXT, date TEXT)")
        for board, n in (("法律常识", 44), ("科技常识", 30)):
            for i in range(n):
                c.execute("INSERT INTO changshi_items(board,title,content,date) "
                          "VALUES(?,?,'正文',date('now','localtime'))", (board, "考点%d" % i))
        return c

    def test_今天学的排前面_其余按缺口大小(self, con):
        got = W.order_cells(con, self.SHORT)
        assert [x[1] for x in got] == ["法律常识", "科技常识", "查找细节", "经济常识"]

    def test_没有新素材时就按缺口大小(self, con):
        con.execute("DELETE FROM changshi_items")
        got = W.order_cells(con, self.SHORT)
        assert [x[3] for x in got] == [12, 16, 21, 24]
