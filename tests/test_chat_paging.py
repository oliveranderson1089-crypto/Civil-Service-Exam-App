"""聊天：取历史的分页口径、会话列表、送达/已读、字数上限（方案甲）。

这几条都是**读**的一侧出的问题，光看代码不明显、用起来第一眼就撞上：
首屏原先是 `id>0 ORDER BY id LIMIT 200`，也就是从最老那条开始截 —— 聊过几百条的
会话进去看到的是几个月前的对话。会话列表原先每个好友 4 次查询。这里把新口径钉死。
"""
import sqlite3

import pytest

from conftest import DB

FRIEND = 91001      # 一个真好友


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
    """建一个好友关系，清掉历史消息。返回自己的 uid。"""
    u = _uid()
    _exec("DELETE FROM chat_msgs",
          "DELETE FROM friends",
          ("INSERT OR REPLACE INTO users(id,username,password_hash) VALUES(?,?,?)",
           (FRIEND, "friend91001", "x")),
          ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (u, FRIEND)),
          ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (FRIEND, u)))
    return u


def _seed(me_id, n):
    """灌 n 条对方发来的消息，正文是序号，方便断言拿到的是哪一批。"""
    con = sqlite3.connect(DB, timeout=10)
    try:
        for i in range(n):
            con.execute("INSERT INTO chat_msgs(from_uid,to_uid,kind,body) VALUES(?,?,'text',?)",
                        (FRIEND, me_id, "第%d条" % i))
        con.commit()
    finally:
        con.close()


def test_首屏给的是最近的那批不是最老的(auth_client, me):
    _seed(me, 120)
    d = auth_client.get("/api/chat/%d" % FRIEND).get_json()
    bodies = [m["body"] for m in d["messages"]]
    assert len(bodies) == 50
    assert bodies[-1] == "第119条", "最后一条应该是最新的那条"
    assert bodies[0] == "第70条", "首屏应该是最近 50 条，不是最老的 50 条"
    assert d["has_more"] is True


def test_before_往上翻页(auth_client, me):
    _seed(me, 120)
    first = auth_client.get("/api/chat/%d" % FRIEND).get_json()
    oldest_id = first["messages"][0]["id"]
    page2 = auth_client.get("/api/chat/%d?before=%d" % (FRIEND, oldest_id)).get_json()
    b = [m["body"] for m in page2["messages"]]
    assert len(b) == 50
    assert b[-1] == "第69条" and b[0] == "第20条"
    assert page2["has_more"] is True
    # 再翻一页就见底了（剩 20 条）
    page3 = auth_client.get("/api/chat/%d?before=%d" % (FRIEND, page2["messages"][0]["id"])).get_json()
    assert len(page3["messages"]) == 20 and page3["has_more"] is False


def test_after_仍是增量拉新(auth_client, me):
    _seed(me, 5)
    d = auth_client.get("/api/chat/%d" % FRIEND).get_json()
    mid = d["messages"][2]["id"]
    inc = auth_client.get("/api/chat/%d?after=%d" % (FRIEND, mid)).get_json()
    assert [m["body"] for m in inc["messages"]] == ["第3条", "第4条"]


def test_翻旧页不会把新消息标成已读(auth_client, me):
    _seed(me, 60)
    auth_client.get("/api/chat/%d" % FRIEND)          # 首屏：标已读
    _seed(me, 1)                                       # 又来一条新的（未读）
    oldest = auth_client.get("/api/chat/%d" % FRIEND).get_json()["messages"][0]["id"]
    _seed(me, 1)                                       # 再来一条，翻页期间到达
    auth_client.get("/api/chat/%d?before=%d" % (FRIEND, oldest))
    n = auth_client.get("/api/chat/unread").get_json()["unread"]
    assert n == 1, "向上翻历史不该顺手把翻页期间到达的新消息标成已读"


def test_发送带回_id_和时间(auth_client, me):
    r = auth_client.post("/api/chat/%d" % FRIEND, json={"body": "你好"})
    d = r.get_json()
    assert r.status_code == 200 and d["id"] > 0 and d["time"]


def test_超长消息明说不再悄悄切一半(auth_client, me):
    r = auth_client.post("/api/chat/%d" % FRIEND, json={"body": "字" * 4001})
    assert r.status_code == 400 and "太长" in r.get_json()["error"]
    # 卡在上限之内的照常发，且**完整**入库（原先是 body[:4000] 静默截断）
    ok = auth_client.post("/api/chat/%d" % FRIEND, json={"body": "字" * 4000})
    assert ok.status_code == 200
    d = auth_client.get("/api/chat/%d" % FRIEND).get_json()
    assert len(d["messages"][-1]["body"]) == 4000


def test_会话列表带送达与已读(auth_client, me):
    auth_client.post("/api/chat/%d" % FRIEND, json={"body": "在吗"})
    c = auth_client.get("/api/chat/conversations").get_json()
    row = [x for x in c["conversations"] if x["id"] == FRIEND][0]
    assert row["preview"] == "在吗" and row["last_mine"] is True and row["last_read"] is False
    assert row["username"] == "friend91001"
    # 对方读了 → 列表和 read_upto 都翻成已读
    _exec("UPDATE chat_msgs SET read_at=datetime('now','localtime') WHERE from_uid=%d" % me)
    row = [x for x in auth_client.get("/api/chat/conversations").get_json()["conversations"]
           if x["id"] == FRIEND][0]
    assert row["last_read"] is True
    assert auth_client.get("/api/chat/%d" % FRIEND).get_json()["read_upto"] > 0


def test_会话列表含文件传输助手且不受好友数影响(auth_client, me):
    c = auth_client.get("/api/chat/conversations").get_json()
    assert c["conversations"][0].get("self") is True, "文件传输助手永远置顶"
    assert len(c["conversations"]) == 2      # 自己 + 一个好友


def test_首屏带得出未读水位_一对一(auth_client, me):
    """「以下是未读消息」那条线要能算得出来，而且进过一次就得往下走。

    前端按 `!m.read` 找第一条未读；曾经它读的是后端根本不存在的 `read_at_self`，
    取到永远是 undefined，于是每条对方的消息都算未读 —— 红线钉死在首屏第一条上，
    每次点开会话都从一个月前那儿开始。这里钉住两点：首屏给的是**进来之前**的已读
    状态（否则线永远无处可画），进过之后再拉就全是已读了。
    """
    _seed(me, 3)
    first = auth_client.get("/api/chat/%d" % FRIEND).get_json()["messages"]
    assert [m["read"] for m in first] == [False, False, False], "首屏必须是进来之前的状态"
    again = auth_client.get("/api/chat/%d" % FRIEND).get_json()["messages"]
    assert all(m["read"] for m in again), "读过的消息不该再被当成未读"


def test_群首屏带得出未读水位(auth_client, me):
    """群里没有逐条 read_at，线只能靠 my_read（我读到哪条）来画 —— 后端得把它返回来。"""
    cid = auth_client.post("/api/chat/groups",
                           json={"name": "小组", "members": [FRIEND]}).get_json()["id"]
    _exec(*[("INSERT INTO chat_msgs(conv_id,from_uid,kind,body) VALUES(?,?,'text',?)",
             (cid, FRIEND, "第%d条" % i)) for i in range(3)])
    d = auth_client.get("/api/chat/g/%d" % cid).get_json()
    assert d["my_read"] == 0, "第一次进群：水位在最前面，三条都在线下面"
    ids = [m["id"] for m in d["messages"]]
    d2 = auth_client.get("/api/chat/g/%d" % cid).get_json()
    assert d2["my_read"] == max(ids), "进过一次之后水位要推到最新，线不该再停在原地"
