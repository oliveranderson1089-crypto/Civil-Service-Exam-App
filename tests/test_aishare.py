"""分享一段 AI 对话，对方能接着往下问。

两条红线：
  · 快照是**副本**不是引用 —— 分享之后原对话继续聊，不能跟着漏出去。
  · 隐私边界 —— 只带正文，不带附件原文、工具轨迹、长期记忆、项目指令。
"""
import json
import sqlite3

import pytest

from conftest import DB


def _mkuser(name):
    """直接往库里塞一个用户（注册流程要验证码，这里只需要一个 id）。"""
    con = sqlite3.connect(DB, timeout=10)
    con.execute("INSERT OR IGNORE INTO users(username,password_hash,role) VALUES(?,'x','user')", (name,))
    con.commit()
    uid = con.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()[0]
    con.close()
    return uid


def _befriend(a, b):
    con = sqlite3.connect(DB, timeout=10)
    for x, y in ((a, b), (b, a)):
        con.execute("INSERT OR IGNORE INTO friends(user_id,friend_id) VALUES(?,?)", (x, y))
    con.commit()
    con.close()


@pytest.fixture
def talk(auth_client):
    """一段有内容的对话，外加一条工具轨迹和一条失败占位（都不该被分享出去）。"""
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    con = sqlite3.connect(DB, timeout=10)
    me = con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    con.execute("UPDATE ai_chats SET title='资料分析提速' WHERE id=?", (cid,))
    con.execute("INSERT INTO ai_msgs(chat_id,role,content,kind,attach) VALUES(?,?,?,'text',?)",
                (cid, "user", "资料分析总超时", json.dumps([{"name": "私密讲义.pdf", "text": "附件全文机密内容"}])))
    con.execute("INSERT INTO ai_msgs(chat_id,role,content,kind) VALUES(?,?,?,'text')",
                (cid, "assistant", "先练**截位直除**"))
    con.execute("INSERT INTO ai_msgs(chat_id,role,content,kind,meta) VALUES(?,?,?,'tool',?)",
                (cid, "assistant", "", json.dumps([{"name": "list_wrong_questions",
                                                    "result": "你的错题里资料分析占 62%"}])))
    con.execute("INSERT INTO ai_msgs(chat_id,role,content,kind) VALUES(?,?,?,'error')",
                (cid, "assistant", "（本次回答失败：网络超时）"))
    con.commit()
    con.close()
    return auth_client, cid, me


@pytest.fixture
def friend(talk, flask_app):
    c, cid, me = talk
    fid = _mkuser("shareee")
    _befriend(me, fid)
    other = flask_app.test_client()
    with other.session_transaction() as sess:
        sess["user_id"] = fid
    return other, fid


def test_分享后对方收到卡片并看得到正文(talk, friend):
    c, cid, me = talk
    other, fid = friend
    r = c.post("/api/aichat/chats/%d/share" % cid, json={"users": [fid]})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    assert r.get_json()["users"] == 1

    con = sqlite3.connect(DB, timeout=10)
    row = con.execute("SELECT kind, body FROM chat_msgs WHERE to_uid=? ORDER BY id DESC LIMIT 1",
                      (fid,)).fetchone()
    con.close()
    assert row[0] == "card"
    card = json.loads(row[1])
    assert card["kind"] == "aishare"

    d = other.get("/api/aishare/%d" % card["id"]).get_json()
    assert d["title"] == "资料分析提速"
    assert d["from"] == "tester"
    assert [m["content"] for m in d["msgs"]] == ["资料分析总超时", "先练**截位直除**"]


def test_附件原文和工具轨迹不跟着走(talk, friend):
    c, cid, me = talk
    other, fid = friend
    c.post("/api/aichat/chats/%d/share" % cid, json={"users": [fid]})
    con = sqlite3.connect(DB, timeout=10)
    body = con.execute("SELECT msgs FROM ai_shares ORDER BY id DESC LIMIT 1").fetchone()[0]
    con.close()
    assert "附件全文机密内容" not in body, "附件原文跟着分享出去了"
    assert "你的错题里资料分析占" not in body, "工具轨迹会暴露我自己的数据"
    assert "本次回答失败" not in body, "失败占位没必要分享给别人"


def test_分享之后原对话再聊什么对方看不到(talk, friend):
    """快照是副本不是引用 —— 这条要是错了，等于把之后所有的话都一起分享了。"""
    c, cid, me = talk
    other, fid = friend
    c.post("/api/aichat/chats/%d/share" % cid, json={"users": [fid]})
    con = sqlite3.connect(DB, timeout=10)
    sid = con.execute("SELECT id FROM ai_shares ORDER BY id DESC LIMIT 1").fetchone()[0]
    con.execute("INSERT INTO ai_msgs(chat_id,role,content,kind) VALUES(?,?,?,'text')",
                (cid, "user", "分享之后才说的悄悄话"))
    con.commit()
    con.close()
    d = other.get("/api/aishare/%d" % sid).get_json()
    assert all("悄悄话" not in m["content"] for m in d["msgs"])


def test_接着问是在自己名下复制一条(talk, friend):
    c, cid, me = talk
    other, fid = friend
    c.post("/api/aichat/chats/%d/share" % cid, json={"users": [fid]})
    con = sqlite3.connect(DB, timeout=10)
    sid = con.execute("SELECT id FROM ai_shares ORDER BY id DESC LIMIT 1").fetchone()[0]
    con.close()

    d = other.post("/api/aishare/%d/adopt" % sid).get_json()
    con = sqlite3.connect(DB, timeout=10)
    owner, title = con.execute("SELECT user_id, title FROM ai_chats WHERE id=?", (d["id"],)).fetchone()
    n = con.execute("SELECT COUNT(*) FROM ai_msgs WHERE chat_id=?", (d["id"],)).fetchone()[0]
    src = con.execute("SELECT COUNT(*) FROM ai_msgs WHERE chat_id=?", (cid,)).fetchone()[0]
    con.close()
    assert owner == fid, "复制出来的会话得归收件人，不能挂在分享者名下"
    assert "分享" in title
    assert n == 2
    assert src == 4, "接着问不该往原对话里写东西"


def test_不是发给我的就看不到(talk, flask_app, friend):
    c, cid, me = talk
    other, fid = friend
    c.post("/api/aichat/chats/%d/share" % cid, json={"users": [fid]})
    con = sqlite3.connect(DB, timeout=10)
    sid = con.execute("SELECT id FROM ai_shares ORDER BY id DESC LIMIT 1").fetchone()[0]
    con.close()

    third = flask_app.test_client()
    with third.session_transaction() as sess:
        sess["user_id"] = _mkuser("nosy")
    assert third.get("/api/aishare/%d" % sid).status_code == 404, "顺着 id 就能翻别人的分享"
    assert third.post("/api/aishare/%d/adopt" % sid).status_code == 404


def test_空对话不给分享(auth_client, friend):
    other, fid = friend
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    assert auth_client.post("/api/aichat/chats/%d/share" % cid, json={"users": [fid]}).status_code == 400


def test_没选人不给发(talk):
    c, cid, me = talk
    assert c.post("/api/aichat/chats/%d/share" % cid, json={}).status_code == 400


def test_分享别人的对话不行(flask_app, talk):
    c, cid, me = talk
    other = flask_app.test_client()
    with other.session_transaction() as sess:
        sess["user_id"] = _mkuser("thief")
    assert other.post("/api/aichat/chats/%d/share" % cid, json={"users": [me]}).status_code == 404
