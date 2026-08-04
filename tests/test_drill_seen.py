"""AI 题的「我做过没」——drill_seen。

为什么非有不可：做题**不消耗库存**（题发出去既不删也不标记），而一格的目标水位就是
30 道、取题又是 ORDER BY RANDOM()。不排掉做过的，做到第 31 道起就是永远的复习，
夜里的 warm_drill_bank 还一直判「满了，不用补」——靠它等不来新题。

所以这里要钉死三件事：
1. 没做过的优先，做过的排在后面（够的时候压根不发）；
2. 没做过的不够时**照样发满**，拿最久没做的顶上，并标 again ——
   少发题会让界面上的「还差 N 道」变成假话（那一格其实是满的）；
3. 记做过时 sig 必须验明正身：它是从客户端收回来的。
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mods.drill as D  # noqa: E402

OPTS = json.dumps(["甲说法", "乙说法", "丙说法", "丁说法"], ensure_ascii=False)
BOARD, QTYPE = "政治理论", "毛泽东思想"


@pytest.fixture
def db(monkeypatch):
    # 取不够会排补库 —— 测试里绝不能真去调 AI
    monkeypatch.setattr(D, "_bank_warm", lambda *a, **k: False)
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE drill_bank(id INTEGER PRIMARY KEY, board TEXT, qtype TEXT, level TEXT,
            q TEXT, options TEXT, answer TEXT, explain TEXT, tip TEXT, source TEXT,
            sig TEXT UNIQUE, agree TEXT);
        CREATE TABLE drill_seen(user_id INTEGER NOT NULL, sig TEXT NOT NULL,
            n INTEGER DEFAULT 1, last_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, sig));
    """)
    return con


def _bank(con, n, level="mid", agree="1"):
    for i in range(n):
        con.execute("INSERT INTO drill_bank(board,qtype,level,q,options,answer,explain,tip,"
                    "source,sig,agree) VALUES(?,?,?,?,?,'B','解析','技巧','来源',?,?)",
                    (BOARD, QTYPE, level, "AI题干%d" % i, OPTS, "sig%d" % i, agree))


def _seen(con, user, sigs, at="2026-01-01 00:00:00"):
    for s in sigs:
        con.execute("INSERT INTO drill_seen(user_id,sig,last_at) VALUES(?,?,?)", (user, s, at))


def _take(con, n, user=1, level="mid"):
    return D._bank_take(con, BOARD, QTYPE, level, n, user)


class Test取题避开做过的:
    def test_做过的不发(self, db):
        _bank(db, 5)
        _seen(db, 1, ["sig0", "sig1", "sig2"])
        got = _take(db, 2)
        assert {it["q"] for it in got} == {"AI题干3", "AI题干4"}
        assert not any(it.get("again") for it in got)

    def test_只避开自己做过的(self, db):
        """别人做过不算 —— 题池是按人算的，多用户下一个人刷完不能把别人的池子也清空。"""
        _bank(db, 3)
        _seen(db, 2, ["sig0", "sig1", "sig2"])
        assert len(_take(db, 3, user=1)) == 3

    def test_不认人就是老行为(self, db):
        """脚本和测试不带 user 直接调：照旧纯随机取，不碰 drill_seen。"""
        _bank(db, 3)
        _seen(db, 1, ["sig0", "sig1", "sig2"])
        got = D._bank_take(db, BOARD, QTYPE, "mid", 3)
        assert len(got) == 3 and not any(it.get("again") for it in got)

    def test_存疑题依然不发(self, db):
        """agree≠1 的题不发给人做，这条不因为「没做过的不够」而松动。"""
        _bank(db, 2, agree="0")
        assert _take(db, 2) == []


class Test没做过的不够时:
    def test_拿最久没做的顶上并标again(self, db):
        _bank(db, 3)
        _seen(db, 1, ["sig0"], at="2026-03-01 00:00:00")
        _seen(db, 1, ["sig1"], at="2026-01-01 00:00:00")     # 最久没做的
        _seen(db, 1, ["sig2"], at="2026-02-01 00:00:00")
        got = _take(db, 2)
        assert len(got) == 2, "这一格是满的，不能少发"
        assert [it["q"] for it in got] == ["AI题干1", "AI题干2"]
        assert all(it["again"] == 1 for it in got)

    def test_没做过的先来复习题在后(self, db):
        _bank(db, 3)
        _seen(db, 1, ["sig0", "sig1"], at="2026-01-01 00:00:00")
        got = _take(db, 3)
        assert got[0]["q"] == "AI题干2" and not got[0].get("again")
        assert all(it["again"] == 1 for it in got[1:])

    def test_排一次补库(self, db, monkeypatch):
        """题都做过了 = 这一格被刷穿了 —— 用户做题**驱动补库**，就靠这一下。"""
        calls = []
        monkeypatch.setattr(D, "_bank_warm", lambda *a, **k: calls.append(a) or True)
        _bank(db, 2)
        _seen(db, 1, ["sig0", "sig1"])
        _take(db, 2)
        assert calls and calls[0][:3] == (BOARD, QTYPE, "mid")

    def test_库真空着就还是空的(self, db):
        """空库 → 发不出题，让上层去说「题库还没预热好」，别硬凑。"""
        assert _take(db, 3) == []


class Test记做过:
    def _items(self, sigs, src="ai"):
        return [{"sig": s, "src": src} for s in sigs]

    def test_记下并可去重(self, db):
        _bank(db, 3)
        assert D._seen_mark(db, 1, self._items(["sig0", "sig1"])) == 2
        assert {r[0] for r in db.execute("SELECT sig FROM drill_seen WHERE user_id=1")} \
            == {"sig0", "sig1"}

    def test_再做一遍累加次数(self, db):
        _bank(db, 2)
        D._seen_mark(db, 1, self._items(["sig0"]))
        D._seen_mark(db, 1, self._items(["sig0"]))
        assert db.execute("SELECT n FROM drill_seen WHERE user_id=1 AND sig='sig0'").fetchone()[0] == 2

    def test_库里没有的sig不认(self, db):
        """背题模式整份 items 都来自前端。不校验的话，塞几个假 sig 就能污染自己的题池。"""
        _bank(db, 1)
        D._seen_mark(db, 1, self._items(["sig0", "伪造的sig", "'; DROP TABLE drill_seen; --"]))
        assert [r[0] for r in db.execute("SELECT sig FROM drill_seen")] == ["sig0"]

    def test_只记AI题(self, db):
        """真题走 real_attempts 那套（能记第几遍做的），别在这儿记第二份。"""
        _bank(db, 1)
        assert D._seen_mark(db, 1, self._items(["sig0"], src="real")) == 0

    def test_没登录不记(self, db):
        _bank(db, 1)
        assert D._seen_mark(db, None, self._items(["sig0"])) == 0

    def test_题目没带sig也不炸(self, db):
        """老版本前端缓存里的题没有 sig 字段 —— 记不了就记不了，别让交卷失败。"""
        _bank(db, 1)
        assert D._seen_mark(db, 1, [{"src": "ai"}, {"src": "ai", "sig": None}]) == 0


def test_取题带sig好让交卷记得回来(db):
    """发题和记做过是一条链：sig 断在中间，drill_seen 永远是空的，去重形同虚设。"""
    _bank(db, 1)
    got = _take(db, 1)
    assert got[0]["sig"] == "sig0"
    assert D._seen_mark(db, 1, got) == 1
    assert _take(db, 1)[0].get("again") == 1
