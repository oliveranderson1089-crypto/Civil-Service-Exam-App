"""代码评审抓出来的几处（后端部分）。

都不是「不够好」，是会给出错答案的：收藏数永远卡在 360、?page=x 打成 500、
「改问题」因为拿不到消息 id 而把后面几轮一起删掉。
"""
import sqlite3

import pytest

from conftest import DB
from mods import aisession


def _uid():
    con = sqlite3.connect(DB, timeout=10)
    try:
        return con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    finally:
        con.close()


def test_收藏数不再卡在每类六十(auth_client):
    """_STARS 里每条 SQL 都带 LIMIT 60（那是给「最近收藏」列表用的），
    拿行数当总数的话，收藏越多越不准。

    造完数据一定要收拾干净：这张表是共享的，留着会让别的用例（test_tabhome
    那条「收藏并成一张单子」）看到不属于它的行。
    """
    u = _uid()
    con = sqlite3.connect(DB, timeout=10)
    try:
        for i in range(75):
            con.execute("INSERT OR REPLACE INTO classics(id,title,author,content) VALUES(?,?,?,?)",
                        (900000 + i, "诗%d" % i, "某人", "内容"))
            con.execute("INSERT OR REPLACE INTO classic_stars(user_id,classic_id) VALUES(?,?)",
                        (u, 900000 + i))
        con.commit()
        con.close()
        n = auth_client.get("/api/lib/home").get_json()["counts"]["star"]
        assert n >= 75, "收了 75 条却只数出 %d —— LIMIT 60 被当成总数了" % n
    finally:
        con = sqlite3.connect(DB, timeout=10)
        con.execute("DELETE FROM classic_stars WHERE classic_id>=900000")
        con.execute("DELETE FROM classics WHERE id>=900000")
        con.commit()
        con.close()


def test_会话列表的_page_参数乱填不该五百(auth_client):
    for bad in ("x", "", "-3", "9999999999999999999999"):
        r = auth_client.get("/api/aichat/home?page=" + bad)
        assert r.status_code == 200, "page=%r 打成了 %d" % (bad, r.status_code)


def test_落库带回两条消息的_id(auth_client, monkeypatch):
    """前端本地那份 aiMsgs 是自己 push 的、没有 id。不把行号带回去，
    「改问题」就会退化成「退最后一轮」。"""
    monkeypatch.setattr(aisession, "_ai_agentic_or_error",
                        lambda messages, db, **kw: ("答", [], [], None))
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    d = auth_client.post("/api/aichat/chats/%d/send" % cid, json={"content": "第一问"}).get_json()
    assert d["user_mid"] > 0 and d["msg_id"] > d["user_mid"]
    assert d["title"] == "第一问"


def test_改问题只退那一轮不动后面(auth_client, monkeypatch):
    """这是评审里最凶的一条：改 Q1 会把 Q2/Q3 一起删掉，还不吭声。"""
    monkeypatch.setattr(aisession, "_ai_agentic_or_error",
                        lambda messages, db, **kw: ("答", [], [], None))
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    ids = []
    for q in ("第一问", "第二问", "第三问"):
        ids.append(auth_client.post("/api/aichat/chats/%d/send" % cid,
                                    json={"content": q}).get_json()["user_mid"])
    # 带着**第一问**的 id 去改
    d = auth_client.post("/api/aichat/chats/%d/retry" % cid,
                         json={"msg_id": ids[0], "content": "改过的第一问"}).get_json()
    assert d["content"] == "改过的第一问"
    left = [m["content"] for m in auth_client.get("/api/aichat/chats/%d" % cid).get_json()["msgs"]]
    assert left == [], "从第一问往后本来就该全退掉（重问会重新生成）"

    # 反过来：带最后一轮的 id，前面两轮必须留着
    cid2 = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    ids2 = [auth_client.post("/api/aichat/chats/%d/send" % cid2,
                             json={"content": q}).get_json()["user_mid"]
            for q in ("甲", "乙", "丙")]
    auth_client.post("/api/aichat/chats/%d/retry" % cid2, json={"msg_id": ids2[2]})
    left2 = [m["content"] for m in auth_client.get("/api/aichat/chats/%d" % cid2).get_json()["msgs"]]
    assert "甲" in left2 and "乙" in left2 and "丙" not in left2


def test_分支按指定那条切而不是整份复制(auth_client, monkeypatch):
    monkeypatch.setattr(aisession, "_ai_agentic_or_error",
                        lambda messages, db, **kw: ("答", [], [], None))
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    first = auth_client.post("/api/aichat/chats/%d/send" % cid,
                             json={"content": "共同前半段"}).get_json()["user_mid"]
    second = auth_client.post("/api/aichat/chats/%d/send" % cid,
                              json={"content": "想换问法的那句"}).get_json()["user_mid"]
    assert second > first
    nid = auth_client.post("/api/aichat/chats/%d/branch" % cid,
                           json={"msg_id": second}).get_json()["id"]
    new = [m["content"] for m in auth_client.get("/api/aichat/chats/%d" % nid).get_json()["msgs"]]
    assert "共同前半段" in new and "想换问法的那句" not in new


@pytest.mark.parametrize("path", ["/api/aichat/home", "/api/lib/home"])
def test_两个首页接口都还活着(auth_client, path):
    assert auth_client.get(path).status_code == 200
