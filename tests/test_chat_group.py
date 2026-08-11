"""学习小组（群聊）：会话模型、成员、@提及、未读水位。

消息从「from_uid/to_uid 两列指人」改成「属于某个会话」。一对一那些路径原样保留，
所以这里既要测群聊本身，也要确认一对一没被带坏。
"""
import sqlite3

import pytest

from conftest import DB

A, B = 92001, 92002        # 两个好友


def _exec(*stmts):
    con = sqlite3.connect(DB, timeout=10)
    try:
        last = None
        for st in stmts:
            sql, params = (st, ()) if isinstance(st, str) else st
            last = con.execute(sql, params).lastrowid
        con.commit()
        return last
    finally:
        con.close()


def _uid():
    con = sqlite3.connect(DB, timeout=10)
    try:
        return con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    finally:
        con.close()


@pytest.fixture
def me(auth_client):
    u = _uid()
    _exec("DELETE FROM chat_msgs", "DELETE FROM friends", "DELETE FROM conv_members",
          "DELETE FROM conversations", "DELETE FROM notifications")
    for f, name in ((A, "友甲92001"), (B, "友乙92002")):
        _exec(("INSERT OR REPLACE INTO users(id,username,password_hash) VALUES(?,?,?)", (f, name, "x")),
              ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (u, f)),
              ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (f, u)))
    return u


def _group(c, name="省考冲刺小组", members=(A, B)):
    return c.post("/api/chat/groups", json={"name": name, "members": list(members)}).get_json()["id"]


def test_建组只能拉好友(auth_client, me):
    d = auth_client.post("/api/chat/groups",
                         json={"name": "小组", "members": [A, B, 99999]}).get_json()
    assert d["members"] == 3, "陌生人不该被拉进来（自己 + 两个好友 = 3）"
    info = auth_client.get("/api/chat/groups/%d" % d["id"]).get_json()
    assert {m["id"] for m in info["members"]} == {me, A, B}
    assert info["is_owner"] is True


def test_群消息收发与成员署名(auth_client, me):
    g = _group(auth_client)
    auth_client.post("/api/chat/g/%d" % g, json={"body": "今晚八点对答案"})
    _exec(("INSERT INTO chat_msgs(from_uid,to_uid,conv_id,kind,body) VALUES(?,?,?,'text',?)",
           (A, 0, g, "收到")))
    d = auth_client.get("/api/chat/g/%d" % g).get_json()
    assert [m["body"] for m in d["messages"]] == ["今晚八点对答案", "收到"]
    assert d["messages"][1]["who"] == "友甲92001", "群里要看得出是谁说的"
    assert d["messages"][0]["mine"] is True and d["messages"][1]["mine"] is False
    assert d["name"] == "省考冲刺小组"


def test_不是成员就进不去(auth_client, me):
    g = _group(auth_client, members=())
    _exec(("DELETE FROM conv_members WHERE conv_id=? AND user_id=?", (g, me)))
    assert auth_client.get("/api/chat/g/%d" % g).status_code == 403
    assert auth_client.post("/api/chat/g/%d" % g, json={"body": "混进来"}).status_code == 403


def test_未读按水位算读完就清零(auth_client, me):
    g = _group(auth_client)
    for i in range(5):
        _exec(("INSERT INTO chat_msgs(from_uid,to_uid,conv_id,kind,body) VALUES(?,?,?,'text',?)",
               (A, 0, g, "第%d条" % i)))
    row = [x for x in auth_client.get("/api/chat/conversations").get_json()["conversations"]
           if x.get("group") and x["id"] == g][0]
    assert row["unread"] == 5 and row["n_mem"] == 3
    assert auth_client.get("/api/chat/unread").get_json()["unread"] >= 5
    auth_client.get("/api/chat/g/%d" % g)          # 读一次
    row = [x for x in auth_client.get("/api/chat/conversations").get_json()["conversations"]
           if x.get("group") and x["id"] == g][0]
    assert row["unread"] == 0
    # 自己发的不算自己的未读
    auth_client.post("/api/chat/g/%d" % g, json={"body": "我说的"})
    row = [x for x in auth_client.get("/api/chat/conversations").get_json()["conversations"]
           if x.get("group") and x["id"] == g][0]
    assert row["unread"] == 0


def test_翻旧页不清未读(auth_client, me):
    g = _group(auth_client)
    for i in range(60):
        _exec(("INSERT INTO chat_msgs(from_uid,to_uid,conv_id,kind,body) VALUES(?,?,?,'text',?)",
               (A, 0, g, "第%d条" % i)))
    first = auth_client.get("/api/chat/g/%d" % g).get_json()
    assert len(first["messages"]) == 50 and first["has_more"] is True
    assert first["messages"][0]["body"] == "第10条", "首屏要给最近的 50 条"
    _exec(("INSERT INTO chat_msgs(from_uid,to_uid,conv_id,kind,body) VALUES(?,?,?,'text',?)",
           (A, 0, g, "翻页时来的新消息")))
    auth_client.get("/api/chat/g/%d?before=%d" % (g, first["messages"][0]["id"]))
    row = [x for x in auth_client.get("/api/chat/conversations").get_json()["conversations"]
           if x.get("group") and x["id"] == g][0]
    assert row["unread"] == 1, "往上翻历史不该把翻页期间到达的新消息标成已读"


def test_at_提及给单独通知并在列表标记(auth_client, me):
    g = _group(auth_client)
    # 别人 @ 我：用 A 的身份写一条（直接落库 + 手动触发通知逻辑走接口不方便，这里查通知表）
    auth_client.post("/api/chat/g/%d" % g, json={"body": "@友甲92001 你看下这题"})
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    n = con.execute("SELECT * FROM notifications WHERE user_id=? AND dkey LIKE '%:at'", (A,)).fetchall()
    con.close()
    assert len(n) == 1 and "@ 你" in n[0]["title"]


def test_at_所有人(auth_client, me):
    g = _group(auth_client)
    auth_client.post("/api/chat/g/%d" % g, json={"body": "@所有人 今晚 21:00"})
    con = sqlite3.connect(DB, timeout=10)
    ats = con.execute("SELECT user_id FROM notifications WHERE dkey LIKE '%:at'").fetchall()
    con.close()
    assert {r[0] for r in ats} == {A, B}, "@所有人 要通知到组里每个人（除了自己）"


def test_群主退出即解散普通成员退出只走自己(auth_client, me):
    g = _group(auth_client)
    # 普通成员退出
    assert auth_client.delete("/api/chat/groups/%d/members/%d" % (g, A)).status_code == 200
    info = auth_client.get("/api/chat/groups/%d" % g).get_json()
    assert {m["id"] for m in info["members"]} == {me, B}
    # 群主退出 → 解散
    d = auth_client.delete("/api/chat/groups/%d/members/%d" % (g, me)).get_json()
    assert d.get("dissolved") is True
    assert auth_client.get("/api/chat/groups/%d" % g).status_code == 403


def test_只有群主能改名和公告(auth_client, me):
    g = _group(auth_client)
    assert auth_client.patch("/api/chat/groups/%d" % g,
                             json={"announce": "每晚 21:00 对答案"}).status_code == 200
    assert auth_client.get("/api/chat/g/%d" % g).get_json()["announce"] == "每晚 21:00 对答案"
    _exec(("UPDATE conversations SET owner_id=? WHERE id=?", (A, g)))
    assert auth_client.patch("/api/chat/groups/%d" % g, json={"name": "改名"}).status_code == 403


def test_群消息也能撤回和搜索(auth_client, me):
    g = _group(auth_client)
    mid = auth_client.post("/api/chat/g/%d" % g,
                           json={"body": "资料分析速算要练熟"}).get_json()["id"]
    got = auth_client.get("/api/chat/search?q=资料分析").get_json()["results"]
    assert got and got[0]["group"] is True and got[0]["peer_name"] == "省考冲刺小组"
    assert auth_client.delete("/api/chat/msg/%d" % mid).status_code == 200
    assert auth_client.get("/api/chat/search?q=资料分析").get_json()["results"] == []


def test_群里也能发内容卡片(auth_client, me):
    g = _group(auth_client)
    auth_client.post("/api/chat/g/%d" % g,
                     json={"card": {"kind": "wrongq", "id": 5, "title": "定义判断那道"}})
    m = auth_client.get("/api/chat/g/%d" % g).get_json()["messages"][-1]
    assert m["kind"] == "card" and m["card"]["title"] == "定义判断那道"


def test_一对一没被带坏(auth_client, me):
    """新消息要挂上 conv_id，但一对一的取法、已读回执一切照旧。"""
    mid = auth_client.post("/api/chat/%d" % A, json={"body": "在吗"}).get_json()["id"]
    con = sqlite3.connect(DB, timeout=10)
    conv = con.execute("SELECT conv_id FROM chat_msgs WHERE id=?", (mid,)).fetchone()[0]
    con.close()
    assert conv, "一对一的新消息也要挂到会话上"
    d = auth_client.get("/api/chat/%d" % A).get_json()
    assert d["messages"][-1]["body"] == "在吗" and d["messages"][-1]["mine"] is True
    row = [x for x in auth_client.get("/api/chat/conversations").get_json()["conversations"]
           if x["id"] == A][0]
    assert row["preview"] == "在吗" and row["last_mine"] is True
