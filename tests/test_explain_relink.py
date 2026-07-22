"""解析必须挂在**不变的锚**上，不能挂在 real_questions.id 上。

这守的是一次真实事故。real_questions 是纯推导表，去重规则或解析器一改就整张重建、
id 重发；解析靠 qid 关联却没有任何机制跟着回指，于是整张解析表静默挂到别的题上：
原卷答案与解析答案的一致率掉到 24~26%（四选一撞对就是 25%，等于完全随机），
id=3004 那道「梳理百年党史」的言语题，配的是 id=3572 类比推理题的解析
（「莲蓬是荷花的组成部分」）。靠 agree=1 才发出去的 233 道题，答案全部来自别的题。

锚点取 (paper_id, seq) —— 「哪份卷子的第几题」。real_papers 是长期表、id 保得住，
seq 是卷面印的题号，两者都不随解析器变。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest_real import explain_health, migrate, relink_explains  # noqa: E402


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE real_papers(id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE real_raw(id INTEGER PRIMARY KEY, paper_id INT, seq INT, qid INT);
        CREATE TABLE real_questions(id INTEGER PRIMARY KEY, answer TEXT, has_answer INT);
        CREATE TABLE real_explains(qid INTEGER PRIMARY KEY, answer TEXT, src TEXT);
    """)
    migrate(con)                      # 补出 anchor_paper / anchor_seq
    return con


# 具名列写入：migrate() 会给这两张表补列（fighash/dkey），位置插入会当场炸
def _raw(con, rid, paper, seq, qid):
    con.execute("INSERT INTO real_raw(id,paper_id,seq,qid) VALUES(?,?,?,?)",
                (rid, paper, seq, qid))


def _q(con, qid, answer="A"):
    con.execute("INSERT INTO real_questions(id,answer,has_answer) VALUES(?,?,1)", (qid, answer))


def _ex(con, qid, answer="A", paper=None, seq=None):
    con.execute("INSERT INTO real_explains(qid,answer,src,anchor_paper,anchor_seq) "
                "VALUES(?,?,'official',?,?)", (qid, answer, paper, seq))


class TestMigrate:
    def test_补出锚点两列(self):
        con = _db()
        cols = {r[1] for r in con.execute("PRAGMA table_info(real_explains)")}
        assert {"anchor_paper", "anchor_seq"} <= cols

    def test_解析表还不存在时不报错(self):
        """real_explains 是 gen_real_explain 建的，ingest 可能先跑。"""
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE real_papers(id INTEGER PRIMARY KEY)")
        migrate(con)                  # 不该抛


class TestRelink:
    def test_题的id变了解析要跟着挂过去(self):
        """核心场景：重导后同一道题（1号卷第5题）拿到了新 id。"""
        con = _db()
        _q(con, 200)
        _raw(con, 1, paper=1, seq=5, qid=200)      # 现在 1号卷第5题 = 题200
        _ex(con, qid=100, paper=1, seq=5)          # 解析还指着旧 id 100
        st = relink_explains(con)
        assert st["relinked"] == 1
        assert con.execute("SELECT qid FROM real_explains").fetchone()[0] == 200

    def test_id没变就不动(self):
        con = _db()
        _q(con, 200)
        _raw(con, 1, paper=1, seq=5, qid=200)
        _ex(con, qid=200, paper=1, seq=5)
        assert relink_explains(con)["relinked"] == 0

    def test_那份卷子这轮没解析出这道题就算无主(self):
        """不能瞎猜一个 qid 挂上去——挂错答案比没答案更糟。"""
        con = _db()
        _q(con, 200)
        _raw(con, 1, paper=1, seq=9, qid=200)      # 第5题这轮没出来
        _ex(con, qid=100, paper=1, seq=5)
        st = relink_explains(con)
        assert st["orphan"] == 1 and st["relinked"] == 0
        assert con.execute("SELECT qid FROM real_explains").fetchone()[0] == 100

    def test_没有锚点的老数据单独计数且不动它(self):
        """事故发生前生成的 6281 条解析就是这样——没锚点，救不回来，只能重生成。"""
        con = _db()
        _q(con, 200)
        _raw(con, 1, paper=1, seq=5, qid=200)
        _ex(con, qid=100, paper=None, seq=None)
        st = relink_explains(con)
        assert st["noanchor"] == 1 and st["relinked"] == 0

    def test_同一道题出自多份卷子只认一个锚(self):
        """副省级/地市级共题：两份卷子都有这道题，锚定其中一份就够了。"""
        con = _db()
        _q(con, 200)
        _raw(con, 1, paper=1, seq=5, qid=200)
        _raw(con, 2, paper=7, seq=23, qid=200)
        _ex(con, qid=100, paper=7, seq=23)
        assert relink_explains(con)["relinked"] == 1
        assert con.execute("SELECT qid FROM real_explains").fetchone()[0] == 200


class TestHealth:
    def test_全对是100(self):
        con = _db()
        for i in (1, 2, 3):
            _q(con, i, "B")
            _ex(con, i, "B")
        assert explain_health(con)["pct"] == 100.0

    def test_挂错题时掉到随机水平(self):
        """这一行就是事故当场能免费发现的信号：掉到 25% 附近 = 解析和题对不上号。"""
        con = _db()
        for i in range(1, 101):
            _q(con, i, "ABCD"[i % 4])
            _ex(con, i, "ABCD"[(i + 1) % 4])       # 整体错开一位 = 全不一致
        assert explain_health(con)["pct"] == 0.0

    def test_没有解析表时返回None而不是崩(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE real_questions(id INT, answer TEXT, has_answer INT)")
        assert explain_health(con) is None
