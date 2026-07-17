"""批注：行为测试，不只是「不 500」。

这块前后修了五轮，主题始终是同一个——批注无声消失
（ebf9da5 配额撑满 setItem 静默失败、565ab42「两个会让批注再次无声消失」、
219e88c「两个又是静默」）。所以这里盯的不是接口通不通，而是：
圈过的东西还在不在、是不是原样、会不会被别人动。
"""
import json
import sqlite3

import pytest

from conftest import DB, appmod, pass_captcha
from mods import annots as annmod   # 批注已拆到 mods/annots.py，常量和 get_db 都在那儿

TARGET = "mat:/api/materials/1/view"
ANCHOR = {"quote": "依法治国", "prefix": "坚持", "suffix": "，建设法治政府。", "start": 12}


def _mk(client, target=TARGET, kind="hl", at="text", anchor=None, data=None):
    return client.post("/api/annots", json={
        "target": target, "kind": kind, "anchor_type": at,
        "anchor": ANCHOR if anchor is None else anchor,
        "data": {"color": "yellow", "text": "重点"} if data is None else data,
    })


def _list(client, target=TARGET):
    r = client.get("/api/annots", query_string={"target": target})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    return r.get_json()["items"]


@pytest.fixture(autouse=True)
def _clean_annots():
    """测试库是 session 级共享的，每条用例前清干净，免得互相看见对方的批注。"""
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM annotations")
    con.commit()
    con.close()


@pytest.fixture
def other_client(flask_app, auth_client):
    """第二个用户。依赖 auth_client，保证 tester 先占掉首个用户(admin)。"""
    c = flask_app.test_client()
    cred = {"username": "other", "password": "Other-passw0rd!"}
    r = c.post("/api/register", json=pass_captcha(
        dict(cred, sec_question="问", sec_answer="答")))
    if r.status_code != 200:                       # 已注册过（同 session 复用库）
        r = c.post("/api/login", json=pass_captcha(dict(cred)))
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    return c


class TestRoundTrip:
    def test_圈了就能原样读回来(self, auth_client):
        aid = _mk(auth_client).get_json()["id"]
        items = _list(auth_client)
        assert len(items) == 1
        it = items[0]
        assert it["id"] == aid
        assert it["anchor"] == ANCHOR, "anchor 往返失真了——锚一歪批注就飘"
        assert it["data"] == {"color": "yellow", "text": "重点"}
        assert it["kind"] == "hl" and it["anchor_type"] == "text"

    def test_中文和特殊字符不被吃掉(self, auth_client):
        anchor = {"quote": "「引号」和\\反斜杠", "prefix": "emoji✍️", "suffix": '双引号"'}
        _mk(auth_client, anchor=anchor)
        assert _list(auth_client)[0]["anchor"] == anchor

    def test_改完读回来是新的(self, auth_client):
        aid = _mk(auth_client).get_json()["id"]
        r = auth_client.put(f"/api/annots/{aid}", json={
            "target": TARGET, "kind": "note", "anchor_type": "text",
            "anchor": ANCHOR, "data": {"text": "改过了"}})
        assert r.status_code == 200
        it = _list(auth_client)[0]
        assert it["data"] == {"text": "改过了"} and it["kind"] == "note"

    def test_删了就真没了(self, auth_client):
        aid = _mk(auth_client).get_json()["id"]
        assert auth_client.delete(f"/api/annots/{aid}").status_code == 200
        assert _list(auth_client) == []

    def test_删不存在的要报404而不是假装成功(self, auth_client):
        assert auth_client.delete("/api/annots/999999").status_code == 404

    def test_不同资料的批注互不串门(self, auth_client):
        _mk(auth_client, target="mat:/api/materials/1/view")
        _mk(auth_client, target="mat:/api/materials/2/view")
        assert len(_list(auth_client, "mat:/api/materials/1/view")) == 1
        assert len(_list(auth_client, "mat:/api/materials/2/view")) == 1


class TestIsolation:
    """别人的批注碰不得——所有写操作都带 AND user_id=?，这里守住它。"""

    def test_看不到别人的批注(self, auth_client, other_client):
        _mk(auth_client)
        assert _list(other_client) == []

    def test_改不动别人的批注(self, auth_client, other_client):
        aid = _mk(auth_client).get_json()["id"]
        r = other_client.put(f"/api/annots/{aid}", json={
            "target": TARGET, "kind": "note", "anchor_type": "text",
            "anchor": {}, "data": {"text": "篡改"}})
        assert r.status_code == 404
        assert _list(auth_client)[0]["data"] == {"color": "yellow", "text": "重点"}

    def test_删不掉别人的批注(self, auth_client, other_client):
        aid = _mk(auth_client).get_json()["id"]
        assert other_client.delete(f"/api/annots/{aid}").status_code == 404
        assert len(_list(auth_client)) == 1

    def test_replace不会连累别人同名target的批注(self, auth_client, other_client):
        """整页替换是 DELETE + INSERT，删的时候必须只删自己的。"""
        _mk(other_client)
        _mk(auth_client)
        r = auth_client.post("/api/annots/replace", json={
            "target": TARGET,
            "items": [{"kind": "ink", "anchor_type": "pdf",
                       "anchor": {"page": 1}, "data": {"d": "M0 0"}}]})
        assert r.status_code == 200
        assert len(_list(other_client)) == 1, "把别人同 target 的批注一起删了"


class TestReplace:
    def test_整页替换换掉旧的(self, auth_client):
        _mk(auth_client)
        _mk(auth_client)
        r = auth_client.post("/api/annots/replace", json={
            "target": TARGET,
            "items": [{"kind": "ink", "anchor_type": "pdf",
                       "anchor": {"page": 2}, "data": {"d": "M1 1"}}]})
        assert r.status_code == 200 and r.get_json()["n"] == 1
        items = _list(auth_client)
        assert len(items) == 1 and items[0]["anchor"] == {"page": 2}

    def test_replace空列表等于清页(self, auth_client):
        _mk(auth_client)
        r = auth_client.post("/api/annots/replace", json={"target": TARGET, "items": []})
        assert r.status_code == 200
        assert _list(auth_client) == []

    def test_中途炸了旧批注不能丢(self, auth_client, monkeypatch):
        """DELETE 完 INSERT 前失败——旧的一页必须原样还在，靠的是没 commit 就 close 会回滚。
        这条要是红了，就是「批注无声消失」本失。"""
        aid = _mk(auth_client).get_json()["id"]
        assert len(_list(auth_client)) == 1

        # sqlite3.Connection 是 C 类型、属性改不动，从 get_db 这层套一个壳：
        # DELETE 照样走到真连接（正是要模拟的「删完才炸」），executemany 抛。
        real_get_db = annmod.get_db

        class BoomDB:
            def __init__(self, real):
                self._real = real

            def __getattr__(self, k):
                return getattr(self._real, k)

            def executemany(self, *a, **k):
                raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(annmod, "get_db", lambda: BoomDB(real_get_db()))
        with pytest.raises(sqlite3.OperationalError):
            auth_client.post("/api/annots/replace", json={
                "target": TARGET,
                "items": [{"kind": "ink", "anchor_type": "pdf",
                           "anchor": {"page": 1}, "data": {"d": "M0 0"}}]})
        monkeypatch.undo()

        items = _list(auth_client)
        assert len(items) == 1 and items[0]["id"] == aid, "写新的失败了，旧的却也没了"


class TestLimits:
    """超限要明说，不能默默截断——静默截断就是下一个「批注消失」。"""

    def test_单条太大要拒绝(self, auth_client):
        r = _mk(auth_client, data={"d": "x" * (annmod._ANN_MAX + 10)})
        assert r.status_code == 400
        assert _list(auth_client) == []

    def test_整页太大要拒绝且不落库(self, auth_client):
        each = "y" * 100_000
        n = annmod._ANN_TOTAL_MAX // 100_000 + 2
        r = auth_client.post("/api/annots/replace", json={
            "target": TARGET,
            "items": [{"kind": "ink", "anchor_type": "pdf",
                       "anchor": {}, "data": {"d": each}} for _ in range(n)]})
        assert r.status_code == 400
        assert _list(auth_client) == []

    def test_replace超限时旧批注要留着(self, auth_client):
        """校验在 DELETE 之前完成，别为了一次非法写入把好好的一页删了。"""
        aid = _mk(auth_client).get_json()["id"]
        auth_client.post("/api/annots/replace", json={
            "target": TARGET,
            "items": [{"kind": "ink", "anchor_type": "pdf", "anchor": {},
                       "data": {"d": "z" * (annmod._ANN_MAX + 10)}}]})
        items = _list(auth_client)
        assert len(items) == 1 and items[0]["id"] == aid, "非法 replace 把旧批注删了"


class TestValidation:
    @pytest.mark.parametrize("kind", ["", "bogus", "script"])
    def test_乱来的kind要挡掉(self, auth_client, kind):
        assert _mk(auth_client, kind=kind).status_code == 400

    @pytest.mark.parametrize("at", ["", "bogus"])
    def test_乱来的anchor_type要挡掉(self, auth_client, at):
        assert _mk(auth_client, at=at).status_code == 400

    def test_target必填(self, auth_client):
        assert _mk(auth_client, target="").status_code == 400
        assert auth_client.get("/api/annots").status_code == 400

    def test_target过长要挡掉(self, auth_client):
        assert _mk(auth_client, target="m" * 201).status_code == 400

    def test_未登录碰不了批注(self, client):
        assert client.get("/api/annots", query_string={"target": TARGET}).status_code == 401
        assert _mk(client).status_code == 401
