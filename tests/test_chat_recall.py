"""聊天：撤回、引用回复、搜索、文件秒传（方案乙）。

撤回**不删行**——删了对方那侧的增量拉取就永远看不到这条的变化，气泡会一直留在
他屏幕上。所以是改 recalled_at，再单给一份「最近撤回的 id」让前端翻牌。
"""
import os
import sqlite3

import pytest

from conftest import DB

FRIEND = 91002


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
    _exec("DELETE FROM chat_msgs",
          "DELETE FROM friends",
          ("INSERT OR REPLACE INTO users(id,username,password_hash) VALUES(?,?,?)",
           (FRIEND, "friend91002", "x")),
          ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (u, FRIEND)),
          ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (FRIEND, u)))
    return u


def test_撤回自己发的消息(auth_client, me):
    mid = auth_client.post("/api/chat/%d" % FRIEND, json={"body": "发错了"}).get_json()["id"]
    r = auth_client.delete("/api/chat/msg/%d" % mid)
    assert r.status_code == 200
    assert r.get_json()["body"] == "发错了", "撤回要把原文还回来，好让「重新编辑」用"
    d = auth_client.get("/api/chat/%d" % FRIEND).get_json()
    m = d["messages"][-1]
    assert m["kind"] == "recalled" and m["body"] == "", "撤回后正文不能再发给前端"
    assert mid in d["recalled"], "要单独告诉前端哪几条刚被撤回（增量拉取带不回状态变化）"
    # 会话列表摘要也跟着变
    row = [x for x in auth_client.get("/api/chat/conversations").get_json()["conversations"]
           if x["id"] == FRIEND][0]
    assert row["preview"] == "[已撤回]"


def test_不能撤回别人的也不能撤超时的(auth_client, me):
    other = _exec(("INSERT INTO chat_msgs(from_uid,to_uid,kind,body) VALUES(?,?,'text',?)",
                   (FRIEND, me, "对方说的")))
    assert auth_client.delete("/api/chat/msg/%d" % other).status_code == 403
    old = _exec(("INSERT INTO chat_msgs(from_uid,to_uid,kind,body,created_at) "
                 "VALUES(?,?,'text',?,datetime('now','localtime','-10 minutes'))", (me, FRIEND, "很久以前")))
    r = auth_client.delete("/api/chat/msg/%d" % old)
    assert r.status_code == 400 and "2 分钟" in r.get_json()["error"]


def test_重复撤回不报错(auth_client, me):
    mid = auth_client.post("/api/chat/%d" % FRIEND, json={"body": "x"}).get_json()["id"]
    auth_client.delete("/api/chat/msg/%d" % mid)
    assert auth_client.delete("/api/chat/msg/%d" % mid).status_code == 200


def test_引用回复带回原文摘要(auth_client, me):
    src = _exec(("INSERT INTO chat_msgs(from_uid,to_uid,kind,body) VALUES(?,?,'text',?)",
                 (FRIEND, me, "这道题选什么")))
    auth_client.post("/api/chat/%d" % FRIEND, json={"body": "选 B", "reply_to": src})
    m = auth_client.get("/api/chat/%d" % FRIEND).get_json()["messages"][-1]
    assert m["quote"]["text"] == "这道题选什么" and m["quote"]["who"] == "friend91002"


def test_引用别的会话的消息会被挡掉(auth_client, me):
    """不校验的话，拿别人的消息 id 也能引用成功，引用条会把原文回显出来。"""
    outsider = _exec(("INSERT INTO chat_msgs(from_uid,to_uid,kind,body) VALUES(?,?,'text',?)",
                      (90099, 90098, "别人的私聊内容")))
    auth_client.post("/api/chat/%d" % FRIEND, json={"body": "试探", "reply_to": outsider})
    m = auth_client.get("/api/chat/%d" % FRIEND).get_json()["messages"][-1]
    assert m.get("quote") is None


def test_引用的原消息被撤回后只说一句(auth_client, me):
    src = auth_client.post("/api/chat/%d" % FRIEND, json={"body": "原话"}).get_json()["id"]
    auth_client.post("/api/chat/%d" % FRIEND, json={"body": "回应", "reply_to": src})
    auth_client.delete("/api/chat/msg/%d" % src)
    m = auth_client.get("/api/chat/%d" % FRIEND).get_json()["messages"][-1]
    assert m["quote"]["text"] == "原消息已撤回"


def test_搜索消息与文件名(auth_client, me):
    auth_client.post("/api/chat/%d" % FRIEND, json={"body": "资料分析速算要练熟"})
    auth_client.post("/api/chat/%d" % FRIEND, json={"body": "今晚八点对答案"})
    _exec(("INSERT INTO chat_msgs(from_uid,to_uid,kind,file_name) VALUES(?,?,'file',?)",
           (FRIEND, me, "资料分析技巧.pdf")))
    d = auth_client.get("/api/chat/search?q=资料分析").get_json()
    assert len(d["results"]) == 2
    assert {r["file"] for r in d["results"]} == {True, False}
    assert d["results"][0]["peer_name"] == "friend91002"
    # 撤回的不该再被搜出来
    mid = auth_client.post("/api/chat/%d" % FRIEND, json={"body": "资料分析撤回测试"}).get_json()["id"]
    auth_client.delete("/api/chat/msg/%d" % mid)
    assert len(auth_client.get("/api/chat/search?q=资料分析").get_json()["results"]) == 2


def test_搜索的通配符不被当语法(auth_client, me):
    auth_client.post("/api/chat/%d" % FRIEND, json={"body": "百分之百"})
    assert auth_client.get("/api/chat/search?q=%25").get_json()["results"] == [], "% 应当按字面搜"


def test_聊天发同一个文件不再各占一份盘(auth_client, me):
    """云盘上传早有 sha256 秒传，聊天这条路一直在无条件 copyfile。"""
    import io
    data = b"same-bytes-" + b"x" * 5000
    for _ in range(2):
        auth_client.post("/api/chat/%d" % FRIEND,
                         data={"file": (io.BytesIO(data), "讲义.pdf")},
                         content_type="multipart/form-data")
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT owner_id, stored_name, sha256 FROM drive_files WHERE source='chat'").fetchall()
    con.close()
    assert len(rows) == 4, "两次发送、两个人，各留一条记录"
    assert all(r["sha256"] for r in rows), "聊天文件也要落 sha256"
    for owner in {r["owner_id"] for r in rows}:
        stored = {r["stored_name"] for r in rows if r["owner_id"] == owner}
        assert len(stored) == 1, "同一个人的两条记录该共用同一份磁盘文件"
    # 物理文件确实只有一份（每人一份，共两份）
    from mods.social import _drive_dir
    files = set()
    for owner in {r["owner_id"] for r in rows}:
        for r in rows:
            if r["owner_id"] == owner:
                p = os.path.join(_drive_dir(owner), r["stored_name"])
                assert os.path.exists(p)
                files.add(p)
    assert len(files) == 2
