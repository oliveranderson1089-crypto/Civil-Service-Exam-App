"""内容质检（mods/quality.py）。

盯三件事：

1. **可用率口径必须和线上取题一致**。realq / drill / audit_qtype 都用
   realref.servable()，这块是第四个用它的地方。抄一份的表现是「审计数字和线上
   实际取到的题对不上」——而审计存在的全部意义就是当那个唯一可信的数字。
2. **反向统计不能被 SQL 三值逻辑坑掉**。LEFT JOIN 没匹配上时 e.agree 是 NULL，
   `WHERE NOT (has_answer=1 OR e.agree=1)` 会把「没答案也没解析」的题两边都漏掉
   （生产库上实测漏了 40 道）。
3. **只读**。这块绝不能有改数据的路径。
"""
import re
import sqlite3

import pytest

from conftest import BASE, DB, appmod
from mods import quality


@pytest.fixture
def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    yield con
    con.close()


def _seed(con, rows, explains=()):
    """rows: (id, has_answer, needs_asset)；explains: (qid, agree)"""
    con.execute("DELETE FROM real_questions")
    con.execute("DELETE FROM real_explains")
    for qid, has_ans, needs in rows:
        con.execute("INSERT INTO real_questions(id,module,qtype,stem,has_answer,needs_asset) "
                    "VALUES(?,'常识判断','',?,?,?)", (qid, "题干%d" % qid, has_ans, needs))
    for qid, agree in explains:
        con.execute("INSERT INTO real_explains(qid,answer,agree) VALUES(?,'A',?)", (qid, agree))
    con.commit()


def test_非管理员进不来(flask_app):
    assert flask_app.test_client().get("/api/admin/quality").status_code == 401


def test_接口结构完整(auth_client):
    d = auth_client.get("/api/admin/quality").get_json()
    assert "counts" in d and len(d["checks"]) == len(quality.CHECKS) + 1  # +1 是续航
    for c in d["checks"]:
        assert c["state"] in ("ok", "warn", "bad", "unknown")
        assert c["fix"], "每一项都得告诉人该敲什么命令——这块不给按钮"


def test_空库不崩(auth_client, db):
    _seed(db, [])
    d = auth_client.get("/api/admin/quality").get_json()
    # 分母为 0 不是质量问题，是「还没有这类内容」
    assert all(c["state"] in ("ok", "unknown") for c in d["checks"])


class Test可用率口径:
    def test_和realref同源(self):
        """口径别抄第二份：改了 realref 这里要自动跟着变。"""
        from mods import realref
        assert realref.servable("q", "e") in quality._UNSERVABLE

    def test_没答案也没解析的题必须算进不可用(self, auth_client, db):
        """三值逻辑陷阱：这类题 e.agree 是 NULL，用 NOT(...) 反向查会两边都漏掉。
        生产库上曾因此少算 40 道（7231 可用 + 335 不可用 ≠ 7606 总数）。"""
        _seed(db, [(1, 1, 0),      # 有答案 → 可用
                   (2, 0, 0),      # 没答案、没解析 → 不可用（就是会被漏掉的那类）
                   (3, 0, 0),      # 同上
                   (4, 0, 0)],     # 有解析且核验通过 → 可用
              explains=[(4, 1)])
        d = auth_client.get("/api/admin/quality").get_json()
        row = next(c for c in d["checks"] if c["key"] == "servable")
        assert row["total"] == 4
        assert row["n"] == 2, "id=2、3 没答案也没解析，必须算不可用；漏掉它们=虚报可用率"

    def test_缺资产的题不算可用(self, auth_client, db):
        _seed(db, [(1, 1, 1)])     # 有答案但缺图/缺材料 → 发不出去
        d = auth_client.get("/api/admin/quality").get_json()
        assert next(c for c in d["checks"] if c["key"] == "servable")["n"] == 1

    def test_存疑解析不算可用(self, auth_client, db):
        _seed(db, [(1, 0, 0)], explains=[(1, 0)])   # agree=0：留库回查，绝不发给人做
        d = auth_client.get("/api/admin/quality").get_json()
        assert next(c for c in d["checks"] if c["key"] == "servable")["n"] == 1


class Test阈值判定:
    @pytest.mark.parametrize("bad_n,total,expect", [
        (0, 100, "ok"),      # 0%
        (4, 100, "ok"),      # 4% ≤ warn 线(5%)
        (10, 100, "warn"),   # 10%：过了 warn、没到 bad(15%)
        (30, 100, "bad"),
    ])
    def test_缺答案按比例分档(self, db, bad_n, total, expect):
        _seed(db, [(i, 0 if i <= bad_n else 1, 0) for i in range(1, total + 1)])
        with appmod.app.app_context():
            rows = quality.snapshot()
        assert next(r for r in rows if r["key"] == "answer")["state"] == expect


def test_表不存在时标unknown而不是ok(auth_client):
    """schema 漂移时必须说出来。标成 ok 等于谎报军情——这块本身就是防静默的。"""
    with appmod.app.app_context():
        from core import get_db
        row = quality._one(get_db(), "x", "测试项", "SELECT COUNT(*) FROM 不存在的表",
                           "SELECT COUNT(*) FROM 也不存在", 0.1, 0.2, "说明", "修法")
    assert row["state"] == "unknown" and "查不了" in row["note"]


def test_只读没有写库路径():
    """破坏性动作不进后台：这个模块里不该出现任何写操作。"""
    src = (BASE / "mods" / "quality.py").read_text(encoding="utf-8")
    # 只看真正的 SQL 语句，注释里提到 --reset 之类的字样不算
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE "):
        assert not re.search(verb, code, re.I), "质检模块必须只读，出现了 %s" % verb.strip()
