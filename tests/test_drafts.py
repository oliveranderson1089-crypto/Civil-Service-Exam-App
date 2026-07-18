"""drafts 蓝图：草稿纸的归属 CRUD（集成）。

drafts 改动 1 次、零测试。草稿是「本人私有」的：新建给默认标题、整本覆盖存笔迹、
读/存/删都必须限本人（AND user_id=?），否则能读到/改到/删掉别人的草稿。
"""
import sqlite3

import pytest

from conftest import DB


def _uid():
    con = sqlite3.connect(DB, timeout=10)
    try:
        return con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    finally:
        con.close()


def _seed_other_draft():
    """在库里塞一条别人(user_id=99999)的草稿，返回 id。"""
    con = sqlite3.connect(DB, timeout=10)
    try:
        cur = con.execute("INSERT INTO drafts(id, user_id, title, data_json, pages) VALUES(90001, 99999, '别人的草稿', '{}', 1)")
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


@pytest.fixture(autouse=True)
def _clean(auth_client):
    con = sqlite3.connect(DB, timeout=10)
    try:
        con.execute("DELETE FROM drafts")
        con.commit()
    finally:
        con.close()


def test_新建草稿给默认标题(auth_client):
    d = auth_client.post("/api/drafts", json={}).get_json()
    assert d["id"]
    assert "草稿" in d["title"], "没给默认标题（草稿 月-日 时:分）"


def test_新建后出现在列表(auth_client):
    auth_client.post("/api/drafts", json={"title": "我的草稿"})
    items = auth_client.get("/api/drafts").get_json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "我的草稿"


def test_存笔迹再读回来(auth_client):
    did = auth_client.post("/api/drafts", json={}).get_json()["id"]
    auth_client.post(f"/api/drafts/{did}", json={"data": {"bg": 2, "pages": [{"st": [1]}]}, "pages": 3})
    d = auth_client.get(f"/api/drafts/{did}").get_json()
    assert d["data"]["bg"] == 2, "存进去的笔迹没读回来"


def test_重命名(auth_client):
    did = auth_client.post("/api/drafts", json={}).get_json()["id"]
    auth_client.post(f"/api/drafts/{did}", json={"title": "改了名"})
    assert auth_client.get(f"/api/drafts/{did}").get_json()["title"] == "改了名"


def test_删除后读不到(auth_client):
    did = auth_client.post("/api/drafts", json={}).get_json()["id"]
    auth_client.delete(f"/api/drafts/{did}")
    assert auth_client.get(f"/api/drafts/{did}").status_code == 404


def test_读不到别人的草稿(auth_client):
    other = _seed_other_draft()
    assert auth_client.get(f"/api/drafts/{other}").status_code == 404, "读到了别人的草稿"
    # 列表里也看不到
    assert all(i["id"] != other for i in auth_client.get("/api/drafts").get_json()["items"])


def test_改不动删不掉别人的草稿(auth_client):
    other = _seed_other_draft()
    # 存（改名）别人的草稿 → 404，且实际没改
    assert auth_client.post(f"/api/drafts/{other}", json={"title": "黑进来改名"}).status_code == 404
    # 删别人的草稿 → 接口返回 ok 但 AND user_id=? 让它删不动
    auth_client.delete(f"/api/drafts/{other}")
    con = sqlite3.connect(DB, timeout=10)
    try:
        row = con.execute("SELECT title FROM drafts WHERE id=?", (other,)).fetchone()
    finally:
        con.close()
    assert row is not None and row[0] == "别人的草稿", "别人的草稿被改/删了 —— 归属隔离失效"
