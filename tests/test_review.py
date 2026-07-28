"""复习：间隔重复的状态机 + 每日额度。

这块的注释里记着三次真实教训，每条都对应下面一组用例：
- 「取词那边加了、提交这边忘了加，卡片点认识直接参数错误」→ TestKindWhitelist
- 「做完 40 条一刷新，池子里剩下的又冒出 40 条，像进度被重置」→ TestDailyQuota
- 「批注跟每日积累挤一个额度，7 条批注全被截掉」→ test_批注有自己的额度
"""
import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from conftest import DB, appmod
from mods import review as rvmod   # 复习已拆到 mods/review.py

TODAY = datetime.now().strftime("%Y-%m-%d")
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _db():
    return sqlite3.connect(DB)


def _uid(username="tester"):
    con = _db()
    r = con.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    con.close()
    return r[0]


@pytest.fixture(autouse=True)
def _clean(auth_client):
    """每条用例前把复习相关的表清空——库是 session 级共享的。"""
    con = _db()
    for t in ("review_state", "entries", "annotations", "sucai_items", "wrong_questions"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    con.close()


def _mk_entries(n, created=None, user=None):
    """造 n 条积累词。默认「昨天」收录——当天收录的按设计不进复习轮。"""
    con = _db()
    uid = user or _uid()
    ids = []
    for i in range(n):
        cur = con.execute(
            "INSERT INTO entries(word,pinyin,category,explanation,created_at,user_id) "
            "VALUES(?,?,?,?,?,?)",
            (f"词{i}", "cí", "成语", f"释义{i}", (created or YESTERDAY) + " 09:00:00", uid))
        ids.append(cur.lastrowid)
    con.commit()
    con.close()
    return ids


def _mk_annots(n, user=None):
    con = _db()
    uid = user or _uid()
    ids = []
    for i in range(n):
        cur = con.execute(
            "INSERT INTO annotations(user_id,target,anchor_type,anchor,kind,data,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (uid, "mat:/api/materials/1/view", "text",
             json.dumps({"quote": f"重点{i}"}), "hl", json.dumps({"color": "y"}),
             YESTERDAY + " 09:00:00"))
        ids.append(cur.lastrowid)
    con.commit()
    con.close()
    return ids


def _mk_sucai(n):
    con = _db()
    ids = []
    for i in range(n):
        cur = con.execute(
            "INSERT INTO sucai_items(date,kind,topic,content,created_at) VALUES(?,?,?,?,?)",
            (YESTERDAY, "金句", f"主题{i}", f"内容{i}", YESTERDAY + " 09:00:00"))
        ids.append(cur.lastrowid)
    con.commit()
    con.close()
    return ids


def _set_limits(client, **kw):
    r = client.post("/api/review/limits", json=kw)
    assert r.status_code == 200
    return r.get_json()


def _today(client):
    r = client.get("/api/review/today")
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    return r.get_json()


def _done(client, kind, rid, result="know"):
    return client.post("/api/review/done", json={"kind": kind, "id": rid, "result": result})


class TestStateMachine:
    def test_认识就往后推一轮(self, auth_client):
        eid = _mk_entries(1)[0]
        j = _done(auth_client, "entry", eid).get_json()
        assert j["stage"] == 1
        assert j["interval"] == rvmod.REVIEW_INTERVALS[1]      # 第一次「认识」→ 2 天后
        assert j["next_due"] == (datetime.now() + timedelta(days=j["interval"])).strftime("%Y-%m-%d")

    def test_连续认识一轮轮往上走(self, auth_client):
        eid = _mk_entries(1)[0]
        seen = []
        for _ in range(len(rvmod.REVIEW_INTERVALS) + 3):
            seen.append(_done(auth_client, "entry", eid).get_json()["interval"])
        # 间隔只增不减，且到顶后停在最大值，不越界
        assert seen[:3] == rvmod.REVIEW_INTERVALS[1:4]
        assert seen[-1] == rvmod.REVIEW_INTERVALS[-1]
        assert all(b >= a for a, b in zip(seen, seen[1:])), f"间隔倒退了: {seen}"

    def test_忘记就打回重来今天再出现(self, auth_client):
        eid = _mk_entries(1)[0]
        _done(auth_client, "entry", eid)
        _done(auth_client, "entry", eid)
        j = _done(auth_client, "entry", eid, "forget").get_json()
        assert j["stage"] == 0
        assert j["next_due"] == TODAY, "忘记的今天就该再出现"

    def test_模糊不升轮明天再看(self, auth_client):
        eid = _mk_entries(1)[0]
        j1 = _done(auth_client, "entry", eid).get_json()          # stage 1
        j2 = _done(auth_client, "entry", eid, "fuzzy").get_json()
        assert j2["stage"] == j1["stage"], "模糊不该升轮"
        assert j2["next_due"] == (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    def test_没背过就模糊也进第一轮(self, auth_client):
        eid = _mk_entries(1)[0]
        assert _done(auth_client, "entry", eid, "fuzzy").get_json()["stage"] == 1


class TestKindWhitelist:
    """RV_GROUP 是唯一白名单。加新来源只改那一处——这组用例盯着别再漏。"""

    @pytest.mark.parametrize("kind", sorted(rvmod.RV_GROUP))
    def test_每种来源都提交得动(self, auth_client, kind):
        r = _done(auth_client, kind, 1)
        assert r.status_code == 200, (
            f"kind={kind} 在 RV_GROUP 里，却提交不了（{r.get_data(as_text=True)[:80]}）——"
            "「取词那边加了、提交这边忘了加」又来了")

    def test_不在白名单的要挡掉(self, auth_client):
        assert _done(auth_client, "bogus", 1).status_code == 400
        assert _done(auth_client, "", 1).status_code == 400

    def test_没有id要挡掉(self, auth_client):
        assert _done(auth_client, "entry", 0).status_code == 400


class TestPickup:
    def test_当天收录的不进复习次日才进(self, auth_client):
        _mk_entries(2, created=TODAY)
        assert _today(auth_client)["count"] == 0, "当天收录的不该马上要背"
        _mk_entries(3, created=YESTERDAY)
        assert _today(auth_client)["count"] == 3

    def test_推到以后的今天就不出现了(self, auth_client):
        ids = _mk_entries(2)
        _done(auth_client, "entry", ids[0])       # 认识 → 2 天后
        j = _today(auth_client)
        assert [it["id"] for it in j["items"]] == [ids[1]]

    def test_忘记的今天还得再出现(self, auth_client):
        ids = _mk_entries(1)
        _done(auth_client, "entry", ids[0], "forget")
        assert _today(auth_client)["count"] == 1

    def test_背过的排在新词前面(self, auth_client):
        ids = _mk_entries(3)
        _done(auth_client, "entry", ids[2], "forget")   # stage 0 但今天还得出现
        _done(auth_client, "entry", ids[1], "fuzzy")    # stage 1
        con = _db()                                     # 把它拨回今天到期
        con.execute("UPDATE review_state SET next_due=? WHERE item_id=?", (TODAY, ids[1]))
        con.commit()
        con.close()
        got = [it["id"] for it in _today(auth_client)["items"]]
        assert got[0] == ids[1], f"stage 高的该排前面，实际 {got}"


class TestDailyQuota:
    def test_额度按组截断(self, auth_client):
        _mk_entries(10)
        _set_limits(auth_client, word=3)
        j = _today(auth_client)
        assert j["count"] == 3 and j["pool"]["word"] == 10, "池子里还有 10 条，今天只出 3 条"

    def test_做完的要占额度不能刷新又冒出来(self, auth_client):
        """做完 3 条一刷新又冒 3 条，用起来就像「进度被重置」。"""
        ids = _mk_entries(10)
        _set_limits(auth_client, word=3)
        first = [it["id"] for it in _today(auth_client)["items"]]
        assert len(first) == 3
        for i in first:
            _done(auth_client, "entry", i)
        j = _today(auth_client)
        assert j["count"] == 0, f"做完 3 条又冒出 {j['count']} 条——额度没扣"
        assert j["done_today"]["word"] == 3

    def test_忘记的不算做完(self, auth_client):
        ids = _mk_entries(5)
        _set_limits(auth_client, word=2)
        for i in [it["id"] for it in _today(auth_client)["items"]]:
            _done(auth_client, "entry", i, "forget")
        j = _today(auth_client)
        assert j["done_today"]["word"] == 0, "忘记的不该算完成"
        assert j["count"] == 2, "忘记的今天还得出现"

    def test_批注有自己的额度(self, auth_client):
        """批注若跟每日积累挤一个额度，素材排前面就能把批注全挤没（实测 7 条全被截）。"""
        _mk_sucai(25)
        _mk_annots(7)
        _set_limits(auth_client, daily=20, annot=10)
        j = _today(auth_client)
        assert j["groups"]["annot"] == 7, "圈过的重点被素材挤掉了"
        assert j["groups"]["daily"] == 20

    def test_上限0表示不限(self, auth_client):
        _mk_entries(30)
        _set_limits(auth_client, word=0)
        assert _today(auth_client)["count"] == 30

    def test_额度存得住(self, auth_client):
        _set_limits(auth_client, word=7, annot=3)
        lim = auth_client.get("/api/review/limits").get_json()["limits"]
        assert lim["word"] == 7 and lim["annot"] == 3

    def test_乱填的额度不落库(self, auth_client):
        before = auth_client.get("/api/review/limits").get_json()["limits"]["word"]
        _set_limits(auth_client, word="不是数字")
        assert auth_client.get("/api/review/limits").get_json()["limits"]["word"] == before


class TestIsolation:
    def test_看不到别人要背的词(self, flask_app, auth_client):
        from conftest import pass_captcha
        c = flask_app.test_client()
        cred = {"username": "rvother", "password": "Rv-passw0rd!"}
        r = c.post("/api/register", json=pass_captcha(dict(cred, sec_question="问", sec_answer="答")))
        if r.status_code != 200:
            c.post("/api/login", json=pass_captcha(dict(cred)))
        _mk_entries(4)                       # 都是 tester 的
        assert _today(c)["count"] == 0, "串到别的用户的复习池了"

    def test_未登录不能提交复习(self, client):
        assert client.post("/api/review/done",
                           json={"kind": "entry", "id": 1, "result": "know"}).status_code == 401


def _mk_changkao(idioms, words):
    """造常考词条。成语的 freq 是真题考频（个位数），实词的 freq 是词表权重（四位数）——
    量纲差两个数量级，这正是「成语被实词霸榜」的成因，测试必须照着造。"""
    con = _db()
    con.execute("DELETE FROM changkao_items")
    ids = {"成语": [], "实词": []}
    for i in range(idioms):
        cur = con.execute(
            "INSERT INTO changkao_items(board,title,content,freq) VALUES(?,?,?,?)",
            ("成语", f"成语{i}", f"释义{i}", idioms - i))          # freq 1~idioms
        ids["成语"].append(cur.lastrowid)
    for i in range(words):
        cur = con.execute(
            "INSERT INTO changkao_items(board,title,content,meaning,freq) VALUES(?,?,?,?,?)",
            ("实词", f"实词{i}", f"搭配{i}", f"词义{i}", 1000 - i))  # freq 四位数
        ids["实词"].append(cur.lastrowid)
    con.commit()
    con.close()
    return ids


def _burn(client, kind, ids):
    """把这些条目背到「以后再说」，模拟已经背熟的一批。"""
    for i in ids:
        _done(client, kind, i)


class TestChangkaoPool:
    """常考高频成语进复习轮。两条都是真实翻过的车：
    - 实词 freq 是词表权重（902~1000）、成语是真题考频（4~47），混着 ORDER BY freq 排，
      99 条实词全霸在前面，894 条成语只挤得进 21 条 → test_成语不会被实词霸榜
    - 池子固定取考频前 N 条，背熟这批就再没有新的了 → test_背熟一批就补新的进来

    这里直接查复习池（_review_due），不走 /api/review/today：那层还要按每日额度截断、
    还要扣掉「今天已背」的名额，测「池子里有没有新词」会被这两样搅浑。
    """

    @pytest.fixture(autouse=True)
    def _no_ck(self):
        yield
        con = _db()
        con.execute("DELETE FROM changkao_items")     # 别漏给后面的用例
        con.commit()
        con.close()

    def _pool(self):
        """池子里的常考词，按板块分组。"""
        con = _db()
        con.row_factory = sqlite3.Row
        try:
            due = rvmod._review_due(con, _uid(), TODAY)
        finally:
            con.close()
        got = {}
        for it in due:
            if it["kind"] == "changkao":
                got.setdefault(it["sub"], []).append(it["id"])
        return got

    def test_成语不会被实词霸榜(self, auth_client):
        _mk_changkao(300, 99)
        _set_limits(auth_client, word=40)
        got = self._pool()
        assert got.get("成语"), "一条成语都没进复习池"
        assert len(got["成语"]) >= len(got.get("实词", [])), \
            f"成语被实词挤掉了：成语 {len(got.get('成语', []))} / 实词 {len(got.get('实词', []))}"

    def test_按考频先背高频的(self, auth_client):
        _mk_changkao(300, 5)
        _set_limits(auth_client, word=40)
        con = _db()
        top = {r[0] for r in con.execute(
            "SELECT id FROM changkao_items WHERE board='成语' ORDER BY freq DESC, id LIMIT 40")}
        con.close()
        assert set(self._pool()["成语"]) == top, "没按真题考频从高到低排"

    def test_背熟一批就补新的进来(self, auth_client):
        _mk_changkao(300, 20)
        _set_limits(auth_client, word=40)
        first = self._pool()["成语"]
        for i in first:                                # 这批推到以后
            _done(auth_client, "changkao", i)
        second = self._pool().get("成语") or []
        assert second, "背熟一批之后就再也没有新成语了——池子没往后滚"
        assert not (set(second) & set(first)), "补进来的还是刚背过的那批"

    def test_已进轮的到期照常回来(self, auth_client):
        _mk_changkao(50, 5)
        _set_limits(auth_client, word=40)
        one = self._pool()["成语"][0]
        _done(auth_client, "changkao", one, "forget")  # 忘记 → 今天就该再出现
        assert one in self._pool()["成语"], "忘记的常考词没回到今天的复习里"
