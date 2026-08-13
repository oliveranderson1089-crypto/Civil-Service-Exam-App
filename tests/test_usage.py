"""使用观测 + 服务并发：两块「撞上去不报错」的刻度。

使用观测判的不是系统好不好，是**照这个节奏走考试那天会怎样**。所以它的
每个结论都要能被一句话解释清楚，而且不能因为少一张表就把整页打成 500 ——
这一屏正是出事时要看的那一屏。
"""
import time

import pytest

from core import THREADS
from mods import capacity, usage


# ---------------------------------------------------------------- 服务并发
class Test服务并发:
    def _state(self, pct):
        out = {"backup": {"last": time.strftime("%Y-%m-%d")}, "disk": {"pct": 10},
               "stuck_tasks": [], "offsite": {"state": "ok", "at": time.strftime("%Y-%m-%d %H:%M")},
               "conc": {"pct": pct}}
        return capacity._states(out)["conc"]

    @pytest.mark.parametrize("pct,expect", [
        (0, "ok"), (59, "ok"), (60, "warn"), (84, "warn"), (85, "bad"), (100, "bad")])
    def test_按占用率分档(self, pct, expect):
        """阈值比磁盘早一截：磁盘满了会报错、看得见；线程池满了只是变慢，
        等到 90% 才提醒，人早就在骂「这破网站又卡了」。"""
        assert self._state(pct) == expect

    def test_取不到并发数时不崩(self):
        """少一格只该让那一格没结论，不该把 /api/admin/capacity 打成 500。"""
        out = {"backup": {"last": time.strftime("%Y-%m-%d")}, "disk": {"pct": 10},
               "stuck_tasks": [], "offsite": {"state": "off"}}
        assert capacity._states(out)["conc"] == "unknown"

    def test_分母就是真实线程数(self):
        """分母写死在两处迟早走散，走散了还不报错 —— 面板会用一个假的上限报占用率。"""
        c = capacity._concurrency()
        assert c["total"] == THREADS
        assert c["held"] == c["chat_sse"] + c["ai_stream"]
        assert c["free"] == max(0, c["total"] - c["held"])

    def test_线程数够放得下并发长连接(self):
        """一条 SSE 占一个线程。32 个的时候大约 15 人同时在线就见底了。"""
        assert THREADS >= 64, "线程池调小了？那并发上限也跟着降了"

    def test_聊天连接计数可用(self):
        from mods.social import listener_count
        assert listener_count() >= 0

    def test_AI流式计数加减配平(self):
        """+1 和 -1 分别在外层函数和生成器的 finally 里，最容易改漏一边——
        漏掉 -1 那边，计数只增不减，面板很快就报满，而实际一个人都没有。"""
        from mods.aisession import _streaming_delta, streaming_count
        base = streaming_count()
        _streaming_delta(1)
        assert streaming_count() == base + 1
        _streaming_delta(-1)
        assert streaming_count() == base


# ---------------------------------------------------------------- 使用观测
class Test功能冷热分档:
    def _row(self, db, table="real_attempts", tcol="created_at"):
        return usage._feature_row(db, 1, "k", "名", table, tcol, "组", "说明")

    def test_表不存在时说出来而不是显示0(self, auth_client):
        """显示 0 会被读成「这功能没在用」——那是把一个 bug 伪装成一个结论。
        表名写错、或哪次重构把表改了名，必须当场看得见。"""
        from core import get_db
        with auth_client.application.app_context():
            r = usage._feature_row(get_db(), 1, "k", "名", "根本没有这张表", "created_at", "组", "说明")
        assert r["state"] == "broken"
        assert "不存在" in r["note"]

    def test_从没用过和用过很久以前是两种(self, auth_client):
        """never 该考虑「是不是根本不该建」，dead 该考虑「是不是可以不再维护」。"""
        assert "never" != "dead"
        from core import get_db
        with auth_client.application.app_context():
            db = get_db()
            db.execute("CREATE TABLE IF NOT EXISTS _t_empty(user_id INT, created_at TEXT)")
            r = self._row(db, "_t_empty")
            assert r["state"] == "never", "一条记录都没有 = 从未用过"

    def test_七天内用过算在用(self, auth_client):
        from core import get_db
        with auth_client.application.app_context():
            db = get_db()
            db.execute("CREATE TABLE IF NOT EXISTS _t_hot(user_id INT, created_at TEXT)")
            db.execute("INSERT INTO _t_hot VALUES(1, datetime('now','localtime','-2 day'))")
            r = self._row(db, "_t_hot")
            assert r["state"] == "hot"
            assert r["d7"] == 1 and r["d30"] == 1

    def test_超过三十天没碰算停用(self, auth_client):
        from core import get_db
        with auth_client.application.app_context():
            db = get_db()
            db.execute("CREATE TABLE IF NOT EXISTS _t_dead(user_id INT, created_at TEXT)")
            db.execute("INSERT INTO _t_dead VALUES(1, datetime('now','localtime','-45 day'))")
            r = self._row(db, "_t_dead")
            assert r["state"] == "dead"
            assert r["d7"] == 0 and r["d30"] == 0 and r["total"] == 1

    def test_只统计自己的记录(self, auth_client):
        """别人的使用不能算进「我用没用过」。"""
        from core import get_db
        with auth_client.application.app_context():
            db = get_db()
            db.execute("CREATE TABLE IF NOT EXISTS _t_mine(user_id INT, created_at TEXT)")
            db.execute("INSERT INTO _t_mine VALUES(999, datetime('now','localtime'))")
            r = self._row(db, "_t_mine")
            assert r["total"] == 0, "统计到了别人的记录"


class Test覆盖率倒推:
    def test_每日配额是剩余题数除以剩余天数(self, auth_client):
        from core import get_db
        with auth_client.application.app_context():
            cov = usage._coverage(get_db(), 1)
        assert set(cov) >= {"bank", "done", "left", "need", "pace", "projected", "days_left"}
        assert cov["left"] == max(0, cov["bank"] - cov["done"])
        if cov["days_left"] and cov["days_left"] > 0 and cov["left"]:
            # 向上取整：宁可多算一道，也别给一个「刚好做不完」的配额
            assert cov["need"] * cov["days_left"] >= cov["left"]
            assert (cov["need"] - 1) * cov["days_left"] < cov["left"]

    def test_没填考试日期时不硬算(self, auth_client, monkeypatch):
        """算不出来就说算不出来，别编一个数字出来。"""
        from core import get_db
        with auth_client.application.app_context():
            db = get_db()
            db.execute("DELETE FROM plan_profile WHERE user_id=1")
            cov = usage._coverage(db, 1)
            assert cov["days_left"] is None
            assert cov["need"] is None

    def test_分母只算有答案的题(self, auth_client):
        """没答案的题做了也判不了对错，算进「还要刷多少」等于派了一堆做不了的活。"""
        assert "has_answer=1" in usage._BANK_SQL


class Test每日走势:
    def test_没做题的日子要补零(self, auth_client):
        """只返回有记录的那几天，画出来是一条虚假的连续曲线——
        中间断掉的那几天恰恰是这张图最该说的事。"""
        from core import get_db
        with auth_client.application.app_context():
            daily = usage._daily(get_db(), 1, days=10)
        assert len(daily) == 11, "10 天该给 11 个点（含今天）"
        assert all("date" in d and "n" in d for d in daily)
        dates = [d["date"] for d in daily]
        assert dates == sorted(dates), "日期要按时间正序，画图才不会左右颠倒"


class Test接口:
    def test_返回结构完整(self, auth_client):
        r = auth_client.get("/api/admin/usage")
        assert r.status_code == 200
        d = r.get_json()
        assert set(d) >= {"coverage", "features", "tally", "daily", "states"}
        assert len(d["features"]) == len(usage.USAGE_FEATURES)

    def test_每个功能都有分档(self, auth_client):
        d = auth_client.get("/api/admin/usage").get_json()
        ok = {"hot", "cold", "dead", "never", "broken"}
        for f in d["features"]:
            assert f["state"] in ok, "%s 的分档 %s 不认识" % (f["name"], f["state"])

    def test_配置里的表名都真实存在(self, auth_client):
        """USAGE_FEATURES 里写错一个表名，那一行就永远显示 broken。
        这条让它在 CI 里就红，而不是等你打开后台才发现。"""
        d = auth_client.get("/api/admin/usage").get_json()
        broken = [f["name"] for f in d["features"] if f["state"] == "broken"]
        assert broken == [], "这些功能的表名对不上：%s" % broken

    def test_非管理员进不来(self, client):
        """使用观测是后台的第五块，跟其余四块同一条门禁。"""
        assert client.get("/api/admin/usage").status_code in (401, 403)
