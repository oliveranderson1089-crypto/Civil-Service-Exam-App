"""每日巩固测试的**组卷器**：配额、素材日期、答案位置。

改造前这三件事全靠 AI 自觉，实测的后果：
  · 配额：历史 78 道里 **23 道连 module 都没填**，配额形同虚设；
  · 答案：A 37.2% / D 5.1%，蒙 A 的期望正确率快四成；
  · 素材：理论和成语都是全库 ORDER BY RANDOM()，「今天巩固」考的是三个月前记的词。
现在三件都由代码保证，这组测试钉住它们。
"""
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mods.dailytest as DT  # noqa: E402
from mods.drill import assemble_items  # noqa: E402

TODAY = "2026-07-22"


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(DT, "uid", lambda: 1)
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE plan_items(id INTEGER PRIMARY KEY, user_id INT, date TEXT,
            title TEXT, module TEXT, done INT DEFAULT 0);
        CREATE TABLE theory_items(id INTEGER PRIMARY KEY, title TEXT, content TEXT,
            board TEXT, created_at TEXT);
        CREATE TABLE entries(id INTEGER PRIMARY KEY, user_id INT, word TEXT,
            explanation TEXT, created_at TEXT);
        CREATE TABLE changkao_items(id INTEGER PRIMARY KEY, board TEXT, title TEXT,
            content TEXT, created_at TEXT);
        CREATE TABLE changshi_items(id INTEGER PRIMARY KEY, board TEXT, title TEXT,
            topic TEXT, content TEXT, date TEXT);
        CREATE TABLE news_items(id INTEGER PRIMARY KEY, title TEXT, ai_summary TEXT,
            date TEXT, created_at TEXT);
        CREATE TABLE wrong_questions(id INTEGER PRIMARY KEY, user_id INT, board TEXT,
            qtype TEXT, question TEXT, points TEXT);
    """)
    return con


class TestQuota:
    def test_总数不变(self, db):
        for n in (10, 15):
            assert sum(DT._dtest_quota(db, TODAY, n).values()) == n

    def test_今天勾完成的任务对应板块加权(self, db):
        """C 方案：今天真做完了资料分析，就该多考它两道。"""
        base = DT._dtest_quota(db, TODAY, 10)
        db.execute("INSERT INTO plan_items(user_id,date,title,module,done) "
                   "VALUES(1,?,'资料分析15题','资料分析',1)", (TODAY,))
        after = DT._dtest_quota(db, TODAY, 10)
        assert after["资料分析"] > base["资料分析"], "已完成的板块没加权"
        assert sum(after.values()) == 10, "加权把总数搅乱了"

    def test_没勾完成就不动配额(self, db):
        db.execute("INSERT INTO plan_items(user_id,date,title,module,done) "
                   "VALUES(1,?,'资料分析15题','资料分析',0)", (TODAY,))
        assert DT._dtest_quota(db, TODAY, 10) == DT.DTEST_QUOTA[10]

    def test_每个板块都还留着题(self, db):
        """巩固测试的意义是全面回顾，不是把弱项刷成偏科。"""
        for m in ("资料分析", "数量关系", "常识判断"):
            db.execute("INSERT INTO plan_items(user_id,date,title,module,done) "
                       "VALUES(1,?,'x',?,1)", (TODAY, m))
        q = DT._dtest_quota(db, TODAY, 10)
        assert all(v >= 1 for v in q.values()), q

    def test_没有任务清单表也不崩(self, monkeypatch):
        monkeypatch.setattr(DT, "uid", lambda: 1)
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        assert sum(DT._dtest_quota(con, TODAY, 10).values()) == 10


class TestMaterialDate:
    def _seed_common(self, db):
        db.execute("INSERT INTO changshi_items(board,title,topic,content,date) "
                   "VALUES('人文常识','今天的常识','','内容',?)", (TODAY,))

    def test_理论优先取今天新增的(self, db):
        """原先是全库 ORDER BY RANDOM()，268 条里随便抽 4 条 ——
           那就成了「随机常识题」，「巩固」两个字白叫了。"""
        self._seed_common(db)
        db.execute("INSERT INTO theory_items(title,content,created_at) "
                   "VALUES('旧理论','x','2026-01-01 10:00:00')")
        db.execute("INSERT INTO theory_items(title,content,created_at) "
                   "VALUES('今天的理论','y',?)", (TODAY + " 09:00:00",))
        got = "\n".join(DT._dtest_material(db, TODAY)["常识"])
        assert "今天的理论" in got
        assert "旧理论" not in got, "混进了今天没学的理论"

    def test_今天没新增理论就退回最近的(self, db):
        self._seed_common(db)
        db.execute("INSERT INTO theory_items(title,content,created_at) "
                   "VALUES('旧理论','x','2026-01-01 10:00:00')")
        assert "旧理论" in "\n".join(DT._dtest_material(db, TODAY)["常识"]), "退不回去就没素材了"

    def test_成语优先取今天收录的(self, db):
        self._seed_common(db)
        for i in range(5):
            db.execute("INSERT INTO entries(user_id,word,explanation,created_at) "
                       "VALUES(1,?,'释义','2026-01-01 10:00:00')", ("旧词%d" % i,))
        for i in range(5):
            db.execute("INSERT INTO entries(user_id,word,explanation,created_at) "
                       "VALUES(1,?,'释义',?)", ("今日词%d" % i, TODAY + " 09:00:00"))
        got = "\n".join(DT._dtest_material(db, TODAY)["言语"])
        assert "今日词0" in got and "旧词0" not in got


class TestGlobalPlacement:
    """答案位置要**对整份卷子统一放**，不是每个板块各放各的。

    分板块放的话每块才 2~3 道，根本均衡不了 —— 实测出过一份 B 53% / D 0% 的卷子。
    """
    def _raw(self, i, module):
        return {"q": "第%d题的题干" % i, "right": "对%d" % i,
                "wrong": ["错%da" % i, "错%db" % i, "错%dc" % i],
                "why_right": "因为对", "why_wrong": ["a错", "b错", "c错"],
                "module": module, "source": "考点%d" % i}

    def test_整卷答案不会全落在同一个字母(self, db):
        raws = [self._raw(i, "常识判断") for i in range(12)]
        got = assemble_items(raws, len(raws), None)
        letters = Counter(a for _it, _q, a, _o in got)
        assert len(letters) == 4, "一整份卷子只用到了 %s" % dict(letters)
        assert max(letters.values()) - min(letters.values()) <= 1, dict(letters)

    def test_板块标签跟着题目走(self, db):
        """全局重排不能把 module 弄丢——丢了配额统计和排序就全乱。"""
        raws = [self._raw(i, m) for i, m in enumerate(["言语理解", "判断推理", "常识判断"])]
        got = assemble_items(raws, len(raws), None)
        assert [it.get("module") for it, _q, _a, _o in got] == ["言语理解", "判断推理", "常识判断"]

    def test_解析字母跟着最终位置走(self, db):
        got = assemble_items([self._raw(1, "常识判断")], 1, None)
        it, _q, ans, _o = got[0]
        assert it["explain"].startswith("正确答案 %s：" % ans)


def test_出不出题都不写坏缓存(db):
    """AI 全挂时 _gen_dtest 要返回错误，而不是把空卷子存进 daily_quiz 让人第二天做。"""
    db.execute("CREATE TABLE daily_quiz(user_id INT, date TEXT, questions_json TEXT, "
               "created_at TEXT)")
    db.execute("INSERT INTO changshi_items(board,title,topic,content,date) "
               "VALUES('人文常识','今天的常识','','内容',?)", (TODAY,))
    DT._dtest_one = lambda *a, **k: []          # 五个板块全部出不来
    DT._gen_figure_q = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("figgen 也挂了"))
    try:
        items, err = DT._gen_dtest(db, TODAY, 10)
    except RuntimeError:
        return                                  # figgen 挂了直接抛也可以，反正没写缓存
    assert items is None and err
    assert db.execute("SELECT COUNT(*) FROM daily_quiz").fetchone()[0] == 0, \
        "把空卷子写进缓存了，用户第二天点开是空的还以为已经做过"


def test_json可序列化(db):
    """题目要存进 daily_quiz 的 questions_json，带不进去的字段会当场炸。"""
    raws = [{"q": "题", "right": "对", "wrong": ["a", "b", "c"],
             "why_right": "r", "why_wrong": ["x", "y", "z"], "module": "常识判断"}]
    got = assemble_items(raws, 1, None)
    it, q, ans, opts = got[0]
    json.dumps({"q": q, "options": opts, "answer": ans, "explain": it["explain"]},
               ensure_ascii=False)
