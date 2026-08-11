"""AI 助手：附件与正文分家、失败占位不进上下文、删除确认要说清删什么（方案甲）。

原先前端把「附件全文 + 问题」拼成一句发出去，落库存的就是那一整坨，标题还从它截前
24 字 —— 屏幕上显示的和存下来的不是一回事，刷新会话后自己那句话变成了整篇 PDF。
"""
import json
import sqlite3

import pytest

from conftest import DB
from mods import aisession
from mods.agent_tools import exec_tool


def _q(sql, args=()):
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


@pytest.fixture
def chat(auth_client):
    """开一个空会话，返回 (client, chat_id)。"""
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    return auth_client, cid


@pytest.fixture
def fake_ai(monkeypatch):
    """把模型换成一句固定回复，并把送进模型的 messages 录下来供断言。"""
    seen = {}

    def fake(messages, db, **kw):
        seen["msgs"] = messages
        return "好的。", [], [], None

    monkeypatch.setattr(aisession, "_ai_agentic_or_error", fake)
    return seen


def test_附件全文不进正文也不污染标题(chat, fake_ai):
    c, cid = chat
    long_text = "附件正文" * 500
    r = c.post("/api/aichat/chats/%d/send" % cid,
               json={"content": "📎 行测真题.pdf", "attachments": [{"name": "行测真题.pdf", "text": long_text}]})
    assert r.status_code == 200
    assert r.get_json()["title"] == "📎 行测真题.pdf", "标题该取人看的那句，不是附件全文"
    row = _q("SELECT content, attach FROM ai_msgs WHERE chat_id=? AND role='user'", (cid,))[0]
    assert row["content"] == "📎 行测真题.pdf"
    assert long_text not in row["content"], "附件全文不该留在用户那句话里"
    assert json.loads(row["attach"])[0]["name"] == "行测真题.pdf"
    # 但这一轮**送给模型**的那条里必须带全文，否则它读不到附件
    assert "附件正文" in fake_ai["msgs"][-1]["content"]


def test_历史里只展开最近一条附件(chat, fake_ai):
    c, cid = chat
    c.post("/api/aichat/chats/%d/send" % cid,
           json={"content": "看看这个", "attachments": [{"name": "旧.pdf", "text": "老附件内容XYZ"}]})
    c.post("/api/aichat/chats/%d/send" % cid,
           json={"content": "再看这个", "attachments": [{"name": "新.pdf", "text": "新附件内容ABC"}]})
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "总结一下"})
    sent = "\n".join(m["content"] for m in fake_ai["msgs"])
    assert "新附件内容ABC" in sent, "最近一条附件要展开，追问才答得上"
    assert "老附件内容XYZ" not in sent, "更早的附件不该每轮重发"
    assert "此前上传过附件" in sent


def test_失败占位留给用户看但不回喂给模型(chat, fake_ai):
    c, cid = chat
    con = sqlite3.connect(DB, timeout=10)
    con.execute("INSERT INTO ai_msgs(chat_id,role,content,kind) VALUES(?,?,?,?)",
                (cid, "user", "上一句问题", "text"))
    con.execute("INSERT INTO ai_msgs(chat_id,role,content,kind) VALUES(?,?,?,?)",
                (cid, "assistant", "（本次回答失败：网络超时）", "error"))
    con.commit()
    con.close()
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "接着说"})
    sent = "\n".join(m["content"] for m in fake_ai["msgs"])
    assert "上一句问题" in sent, "用户问过的话照常进上下文"
    assert "本次回答失败" not in sent, "失败占位进了上下文，模型会以为自己真这么答过"
    # 但界面上还看得见（不然用户回头发现自己问过什么都没了）
    got = c.get("/api/aichat/chats/%d" % cid).get_json()["msgs"]
    assert any(m["kind"] == "error" for m in got)


def test_att_text_摊平与截断():
    raw = json.dumps([{"name": "a.txt", "text": "内容甲"}, {"name": "b.txt", "text": "内容乙"}])
    out = aisession._att_text(raw)
    assert "【附件：a.txt】" in out and "内容乙" in out
    assert aisession._att_text("坏JSON") == ""
    assert len(aisession._att_text(json.dumps([{"name": "x", "text": "字" * 999}]), limit=10)) < 40


def test_删除确认带上那条数据的原文(auth_client):
    """没有 summary，删错题/删小记只能弹「确认删除这条内容？」，用户只能盲点确定。"""
    con = sqlite3.connect(DB, timeout=10)
    uid = con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    cur = con.execute("INSERT INTO notes(user_id,content) VALUES(?,?)",
                      (uid, "行政复议期限：知道之日起 60 日内提出"))
    nid = cur.lastrowid
    con.commit()
    con.close()
    with auth_client.application.test_request_context():
        from flask import session
        session["user_id"] = uid
        from core import get_db
        _, action = exec_tool("delete_note", {"id": nid}, get_db())
    assert action["type"] == "confirm"
    assert "行政复议期限" in action["summary"], "确认框要摆出要删的那条原文"
    assert action["label"] == "删除小记"


def test_preview_取不到时不炸(auth_client):
    with auth_client.application.test_request_context():
        from flask import session
        session["user_id"] = 1
        from core import get_db
        _, action = exec_tool("delete_note", {"id": 99999999}, get_db())
    assert action["type"] == "confirm" and action["summary"] == ""
