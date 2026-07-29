"""产出健康探针。

要证的三件事：
1. 鉴权 —— 这是 /api/admin/*，非管理员碰不到；
2. 探针不因为库空、表少一列、systemctl 不在而崩 —— 它是「出事时才看」的东西，
   最不能挑环境；
3. **静默失败判得出来** —— 内容陈旧 + 单元成功，必须报 silent 而不是 ok。
   这是整块存在的理由，别的都可以退让，这条不行。
"""
import sqlite3

import pytest

from conftest import DB, appmod
from mods import health


@pytest.fixture
def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    yield con
    con.close()


def test_非管理员访问不到(flask_app):
    """裸 client 没登录 —— guard() 应该挡在 401。"""
    r = flask_app.test_client().get("/api/admin/health")
    assert r.status_code == 401


def test_接口能跑且结构完整(auth_client):
    r = auth_client.get("/api/admin/health")
    assert r.status_code == 200
    d = r.get_json()
    assert d["today"] and "counts" in d
    assert len(d["domains"]) == len(health.DOMAINS)
    for row in d["domains"]:
        assert row["state"] in ("ok", "warn", "down", "unknown")
        # 「立即补跑」必须指向 .service：restart 一个 .timer 只重置计时器，任务一次都不会跑
        assert row["svc"].endswith(".service")


def test_空库不崩且判为断供(auth_client):
    """测试库里这些表基本是空的 —— 空 = down（一条都没有），不是崩，也不是 ok。"""
    d = auth_client.get("/api/admin/health").get_json()
    empty = [r for r in d["domains"] if r["total"] == 0]
    assert empty, "测试库里应该有空的内容域"
    for r in empty:
        assert r["state"] == "down" and r["reason"] == "empty"


def test_表或列不存在时只是失效不崩():
    """schema 会漂移。改了表名而没回来改 DOMAINS，探针要说话，不能整块塌掉。"""
    with appmod.app.app_context():
        from core import get_db
        row = health._probe(get_db(), "x", "不存在的域", "no_such_table_xyz",
                            "created_at", 1, "gongkao-x.timer", "", "2026-07-29")
    assert row["state"] == "unknown"
    assert "不存在" in row["hint"]


class TestSLA判定:
    """宽限期就一天：sla 内为 ok，超一天 warn，再超就是 down。"""

    def _probe(self, db, table, last_day, sla, today="2026-07-29"):
        db.execute("DROP TABLE IF EXISTS %s" % table)
        db.execute("CREATE TABLE %s(id INTEGER PRIMARY KEY, created_at TEXT)" % table)
        db.execute("INSERT INTO %s(created_at) VALUES(?)" % table, (last_day,))
        db.commit()
        with appmod.app.app_context():
            from core import get_db
            return health._probe(get_db(), "t", "测试域", table, "created_at",
                                 sla, "gongkao-x.timer", "", today)

    @pytest.mark.parametrize("last,expect", [
        ("2026-07-29", "ok"),     # 今天出的
        ("2026-07-28", "ok"),     # 昨天出的，日更任务今天可能还没到点
        ("2026-07-27", "warn"),   # 落后 2 天，盯着
        ("2026-07-26", "down"),   # 落后 3 天，断供
        ("2026-07-01", "down"),
    ])
    def test_日更任务(self, db, last, expect):
        assert self._probe(db, "hl_t1", last, 1)["state"] == expect

    @pytest.mark.parametrize("last,expect", [
        ("2026-07-25", "ok"),     # 周二/周五跑，最长间隔 4 天
        ("2026-07-24", "warn"),
        ("2026-07-23", "down"),
    ])
    def test_周更任务(self, db, last, expect):
        assert self._probe(db, "hl_t2", last, 4)["state"] == expect


class Test故障归因:
    """陈旧的原因分三种，处置办法完全不同，不能混成一句「挂了」。"""

    ROW = {"state": "down", "reason": "", "last": "2026-07-20", "hint": ""}

    def _diag(self, timer, svc):
        row = dict(self.ROW)
        health._diagnose(row, timer, svc)
        return row["reason"]

    def test_单元报错(self):
        assert self._diag({"last_run": "2026-07-29 08:40:00"},
                          {"healthy": False, "last_run": "2026-07-29 08:40:00"}) == "unit_failed"

    def test_静默失败(self):
        """跑过了、没报错、就是不出货 —— 上游断供长这样，最容易被当成一切正常。"""
        assert self._diag({"last_run": "2026-07-29 08:40:00"},
                          {"healthy": True, "last_run": "2026-07-29 08:40:00"}) == "silent"

    def test_压根没跑(self):
        """自上次产出以来就没触发过：定时器停了或没 enable。"""
        assert self._diag({"last_run": "2026-07-19 08:40:00"},
                          {"healthy": True, "last_run": "2026-07-19 08:40:00"}) == "not_run"

    def test_从来没跑过(self):
        assert self._diag({"last_run": ""}, {"healthy": True, "last_run": ""}) == "never_run"

    def test_拿不到systemd(self):
        """systemctl 不可用（容器里、别的机器上）时，内容结论照给，别整块报错。"""
        assert self._diag(None, None) == "no_unit"

    def test_内容正常就不归因(self):
        row = {"state": "ok", "reason": "", "last": "2026-07-29", "hint": ""}
        health._diagnose(row, {"last_run": "2026-07-29 08:40:00"}, {"healthy": True})
        assert row["reason"] == ""

    def test_表不存在时不冒充silent(self):
        """_probe 遇到表/列不存在会先写好 hint 再返回；_diagnose 不该在这种
        「压根没查过内容」的情况下还编一个 silent/not_run 出来跟 hint 打架——
        即使负责的单元今天确实跑过、看着很健康。"""
        row = {"state": "unknown", "reason": "", "last": "",
               "hint": "表 ghost_table 或时间列 created_at 不存在，探针失效"}
        health._diagnose(row, {"last_run": "2026-07-29 08:40:00"},
                         {"healthy": True, "last_run": "2026-07-29 08:40:00"})
        assert row["reason"] == "", "有 hint 时 reason 应保持空，不能被 silent 之类的值覆盖"


def test_systemctl不可用时仍返回内容结论(auth_client, monkeypatch):
    """两条腿走路：systemd 那条断了，SQL 这条要照常。"""
    monkeypatch.setattr(health.ops, "status", lambda *a, **k: (_ for _ in ()).throw(OSError("no systemctl")))
    r = auth_client.get("/api/admin/health")
    assert r.status_code == 200
    assert len(r.get_json()["domains"]) == len(health.DOMAINS)
