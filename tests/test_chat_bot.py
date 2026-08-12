"""群里 @助手：AI 当场在群里回一条，全组都看得见。

这条路径有三个容易出事的地方，正是这里要钉住的：
  1. **谁的身份**：答案落库成 from_uid=0 / kind='ai'。要是借提问人的身份存，
     提问人那侧就会把 AI 的回答渲染成自己发的（右边的绿气泡）。
  2. **不要误伤**：`@AIleen`、邮箱 `a@b.com` 不能把助手叫起来。
  3. **答不出来也要落一条**：群里 @ 了它却什么都不出现，用户看着像应用坏了。

AI 调用整个打桩——测的是这条链路怎么接，不是模型答得好不好。
"""
import sqlite3
import time

import pytest

from conftest import DB
from mods import social

A, B = 93001, 93002        # 组里另外两个人


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


def _rows(sql, params=()):
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


@pytest.fixture
def group(auth_client):
    """一个我在里面的三人小组，库里干干净净。"""
    con = sqlite3.connect(DB, timeout=10)
    u = con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    con.close()
    _exec("DELETE FROM chat_msgs", "DELETE FROM conv_members", "DELETE FROM conversations",
          "DELETE FROM notifications")
    for f, name in ((A, "友甲93001"), (B, "友乙93002")):
        _exec(("INSERT OR REPLACE INTO users(id,username,password_hash) VALUES(?,?,?)", (f, name, "x")),
              ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (u, f)),
              ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (f, u)))
    cid = _exec(("INSERT INTO conversations(kind,title,owner_id) VALUES('group',?,?)", ("打卡组", u)))
    for m in (u, A, B):
        _exec(("INSERT INTO conv_members(conv_id,user_id) VALUES(?,?)", (cid, m)))
    return {"me": u, "cid": cid, "client": auth_client}


def _wait_ai(cid, timeout=6):
    """AI 是在后台线程里答的，等它落库（别用死 sleep：慢机器上会假红）。"""
    end = time.time() + timeout
    while time.time() < end:
        rows = _rows("SELECT * FROM chat_msgs WHERE conv_id=? AND kind='ai'", (cid,))
        if rows:
            return rows
        time.sleep(0.05)
    return []


@pytest.mark.parametrize("text,hit", [
    ("@助手 这题怎么算", True),
    ("@AI 讲讲不孚众望", True),
    ("@ai", True),
    ("@AI助手 在吗", True),
    ("@AIleen 你好", False),          # 别人的名字里带 AI，不是在叫它
    ("@助手长 明天几点", False),
    ("我的邮箱 a@b.com", False),
    ("今天做了 20 道题", False),
])
def test_asks_bot(text, hit):
    assert social._asks_bot(text) is hit


def test_at_bot_replies_in_group(group, monkeypatch):
    """@助手 → 群里多一条 AI 的消息，且它不属于任何人。"""
    monkeypatch.setattr(social, "ai_chat", lambda *a, **k: "孚是使人信服，负是辜负。")
    r = group["client"].post("/api/chat/g/%d" % group["cid"], json={"body": "@助手 这两个词怎么分"})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]

    rows = _wait_ai(group["cid"])
    assert rows, "@ 了助手，群里却没有它的回复"
    ai = rows[0]
    assert ai["from_uid"] == 0, "AI 的回答借了别人的身份，提问人那侧会看成自己发的"
    assert ai["to_uid"] == 0 and ai["conv_id"] == group["cid"]
    assert "孚" in ai["body"]

    # 组里每个人（含提问的人）都该收到一条消息中心通知
    got = {r["user_id"] for r in _rows(
        "SELECT user_id FROM notifications WHERE link=?", ("chatgroup:%d" % group["cid"],))}
    assert {group["me"], A, B} <= got


def test_normal_message_does_not_wake_bot(group, monkeypatch):
    called = []
    monkeypatch.setattr(social, "ai_chat", lambda *a, **k: called.append(1) or "不该被叫起来")
    r = group["client"].post("/api/chat/g/%d" % group["cid"], json={"body": "今天做了 20 道题"})
    assert r.status_code == 200
    time.sleep(0.3)
    assert not called, "普通消息把 AI 叫起来了 —— 每说一句话都要烧一次模型"
    assert not _rows("SELECT 1 FROM chat_msgs WHERE conv_id=? AND kind='ai'", (group["cid"],))


def test_ai_failure_still_posts_something(group, monkeypatch):
    """模型报错也要落一条：群里 @ 了它却毫无反应，用户只会以为应用坏了。"""
    def boom(*a, **k):
        raise RuntimeError("模型欠费")
    monkeypatch.setattr(social, "ai_chat", boom)
    r = group["client"].post("/api/chat/g/%d" % group["cid"], json={"body": "@助手 在吗"})
    assert r.status_code == 200
    rows = _wait_ai(group["cid"])
    assert rows, "AI 调用失败时群里什么都没出现"
    assert "没答上来" in rows[0]["body"]


def test_bot_answer_is_not_mine_for_anyone(group, monkeypatch):
    """从提问人自己的视角拉历史，AI 那条也必须 mine=False。"""
    monkeypatch.setattr(social, "ai_chat", lambda *a, **k: "答案")
    group["client"].post("/api/chat/g/%d" % group["cid"], json={"body": "@助手 问一句"})
    assert _wait_ai(group["cid"])
    d = group["client"].get("/api/chat/g/%d" % group["cid"]).get_json()
    ai = [m for m in d["messages"] if m["kind"] == "ai"]
    assert ai and ai[0]["mine"] is False, "提问人那侧把 AI 的回答当成了自己发的"


def test_one_answer_at_a_time(group, monkeypatch):
    """连问两句，同一个群同时只跑一条 —— 否则连着 @ 几下就是几个并发模型调用。"""
    started, release = [], {"go": False}

    def slow(*a, **k):
        started.append(1)
        while not release["go"]:
            time.sleep(0.01)
        return "慢答案"
    monkeypatch.setattr(social, "ai_chat", slow)
    group["client"].post("/api/chat/g/%d" % group["cid"], json={"body": "@助手 第一问"})
    for _ in range(100):                       # 等第一条真的进了模型调用
        if started:
            break
        time.sleep(0.01)
    group["client"].post("/api/chat/g/%d" % group["cid"], json={"body": "@助手 第二问"})
    time.sleep(0.3)
    assert len(started) == 1, "同一个群里并发跑了多条 AI 回复"
    release["go"] = True
    assert _wait_ai(group["cid"])
