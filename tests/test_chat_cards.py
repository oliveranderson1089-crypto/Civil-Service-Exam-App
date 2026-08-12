"""聊天内容卡片 + AI 长期记忆 / 主动开场 / 项目资料（方案丙）。

内容卡片是这个聊天区别于微信的理由：发过去的不是一段文字，是应用里那一条，点开直达。
"""
import sqlite3

import pytest

from conftest import DB

FRIEND = 91003


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
    _exec("DELETE FROM chat_msgs", "DELETE FROM friends", "DELETE FROM ai_memories",
          ("INSERT OR REPLACE INTO users(id,username,password_hash) VALUES(?,?,?)",
           (FRIEND, "friend91003", "x")),
          ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (u, FRIEND)),
          ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (FRIEND, u)))
    return u


def test_发一张错题卡片(auth_client, me):
    card = {"kind": "wrongq", "id": 42, "title": "下列关于我国古代科技成就的表述", "sub": "常识判断"}
    r = auth_client.post("/api/chat/%d" % FRIEND, json={"card": card})
    assert r.status_code == 200
    m = auth_client.get("/api/chat/%d" % FRIEND).get_json()["messages"][-1]
    assert m["kind"] == "card" and m["card"]["kind"] == "wrongq" and m["card"]["id"] == 42
    row = [x for x in auth_client.get("/api/chat/conversations").get_json()["conversations"]
           if x["id"] == FRIEND][0]
    assert row["preview"].startswith("[错题]")


def test_不认识的卡片类型不收(auth_client, me):
    r = auth_client.post("/api/chat/%d" % FRIEND, json={"card": {"kind": "恶意", "id": 1}})
    assert r.status_code == 400, "未知类型该被当成空消息挡掉，而不是存进库里"


def test_卡片也能被撤回和引用(auth_client, me):
    mid = auth_client.post("/api/chat/%d" % FRIEND,
                           json={"card": {"kind": "note", "id": 7, "title": "行政复议期限"}}).get_json()["id"]
    auth_client.post("/api/chat/%d" % FRIEND, json={"body": "这条我也记一下", "reply_to": mid})
    m = auth_client.get("/api/chat/%d" % FRIEND).get_json()["messages"][-1]
    assert "行政复议期限" in m["quote"]["text"]
    assert auth_client.delete("/api/chat/msg/%d" % mid).status_code == 200


# ---------------------------------------------------------------- AI 长期记忆
def test_记忆会带进上下文而且可删(auth_client, monkeypatch):
    from mods import aisession
    seen = {}

    def fake(messages, db, **kw):
        seen["sys"] = messages[0]["content"]
        return "好", [], [], None

    monkeypatch.setattr(aisession, "_ai_agentic_or_error", fake)
    r = auth_client.post("/api/aichat/memories", json={"text": "目标岗位是四川省考，2026 年 3 月笔试"})
    mid = r.get_json()["id"]
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    auth_client.post("/api/aichat/chats/%d/send" % cid, json={"content": "帮我看看"})
    assert "四川省考" in seen["sys"], "长期记忆没进上下文，等于白记"
    assert "他随时可以删" in seen["sys"]
    # 用过几次要留痕（用户才能判断哪条真在起作用）
    got = auth_client.get("/api/aichat/memories").get_json()["memories"]
    assert got[0]["hits"] >= 1
    auth_client.delete("/api/aichat/memories/%d" % mid)
    auth_client.post("/api/aichat/chats/%d/send" % cid, json={"content": "再看看"})
    assert "四川省考" not in seen["sys"], "删掉的记忆必须立刻失效"


def test_同一条记忆不重复记(auth_client):
    auth_client.post("/api/aichat/memories", json={"text": "行测弱项是资料分析"})
    auth_client.post("/api/aichat/memories", json={"text": "行测弱项是资料分析"})
    n = [m for m in auth_client.get("/api/aichat/memories").get_json()["memories"]
         if m["text"] == "行测弱项是资料分析"]
    assert len(n) == 1


@pytest.fixture
def clean_mem():
    """记忆是跨测试留在库里的，挑选逻辑又跟条数有关——前后都清一遍，别互相污染。"""
    _exec("DELETE FROM ai_memories")
    yield
    _exec("DELETE FROM ai_memories")


def test_AI记住一件事要先经用户点头(auth_client, monkeypatch, clean_mem):
    """AI 悄悄记错一条，之后**每一轮**都拿它答——比没记更难发现。所以必须停下来问一句。"""
    from mods import aisession
    from mods.agent_tools import exec_tool

    def fake(messages, db, **kw):
        # 假装模型调了 remember_fact：exec_tool 是真的，确认闸门也是真的
        txt, action = exec_tool("remember_fact", {"text": "目标是四川省考，2026 年 3 月笔试"}, db)
        return txt, ([action] if action else []), [], None

    monkeypatch.setattr(aisession, "_ai_agentic_or_error", fake)
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    d = auth_client.post("/api/aichat/chats/%d/send" % cid, json={"content": "我报的是四川省考"}).get_json()
    a = d["actions"][0]
    assert a["type"] == "confirm" and a["tool"] == "remember_fact"
    assert "四川省考" in a["summary"], "确认框得让人看清要记的是哪一句"
    assert a["kind"] == "write", "记忆随时能删，前端不该照删除那样说「不可撤销」"
    assert not auth_client.get("/api/aichat/memories").get_json()["memories"], "没点头就先落库了"
    auth_client.post("/api/aichat/chats/%d/confirm" % cid,
                     json={"tool": "remember_fact", "args": a["args"]})
    got = auth_client.get("/api/aichat/memories").get_json()["memories"]
    assert len(got) == 1 and "四川省考" in got[0]["text"]
    assert "AI" in (got[0]["source"] or ""), "得看得出这条是 AI 记的还是自己加的"


def test_AI不重复记同一件事(auth_client, clean_mem):
    auth_client.post("/api/aichat/memories", json={"text": "目标是四川省考"})
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    for _ in range(2):
        auth_client.post("/api/aichat/chats/%d/confirm" % cid,
                         json={"tool": "remember_fact", "args": {"text": "目标是四川省考"}})
    assert len(auth_client.get("/api/aichat/memories").get_json()["memories"]) == 1


def test_记忆记满了也不会把常用的那条挤掉(auth_client, monkeypatch, clean_mem):
    """老规矩是 `ORDER BY id DESC LIMIT 20`：记满之后，一条天天用得上的老记忆
    会被新记忆挤出去，而且永远回不来。"""
    from mods import aisession
    seen = {}
    monkeypatch.setattr(aisession, "_ai_agentic_or_error",
                        lambda messages, db, **kw: (seen.update(sys=messages[0]["content"]),
                                                    ("好", [], [], None))[1])
    auth_client.post("/api/aichat/memories", json={"text": "资料分析是我最大的弱项，要多练速算"})
    for i in range(25):     # 之后又记了一堆新的，把它压到第 26 位
        auth_client.post("/api/aichat/memories", json={"text": "随手记的第 %d 件小事" % i})
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    auth_client.post("/api/aichat/chats/%d/send" % cid, json={"content": "资料分析怎么提速"})
    assert "最大的弱项" in seen["sys"], "跟这轮问的正相关，再老也得带上"
    assert seen["sys"].count("随手记的第") <= aisession.MEM_LIMIT, "带上限就是带上限，别一次全灌进去"


def test_没记满时一条都不挑掉(auth_client, monkeypatch, clean_mem):
    """长期记忆大多是「跟这轮无关但一直成立」的（考四川省考不会因为这句没提就不成立），
    条数没超就全带上，别自作聪明按相关度筛。"""
    from mods import aisession
    seen = {}
    monkeypatch.setattr(aisession, "_ai_agentic_or_error",
                        lambda messages, db, **kw: (seen.update(sys=messages[0]["content"]),
                                                    ("好", [], [], None))[1])
    auth_client.post("/api/aichat/memories", json={"text": "目标是四川省考，2026 年 3 月笔试"})
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    auth_client.post("/api/aichat/chats/%d/send" % cid, json={"content": "背几个成语给我"})
    assert "四川省考" in seen["sys"]


def test_主动开场不调模型也能出(auth_client):
    d = auth_client.get("/api/aichat/opener").get_json()
    assert d["greet"] and len(d["chips"]) >= 2
    assert any(x in d["greet"] for x in ("早上好", "下午好", "晚上好"))


def test_项目资料会注入(auth_client, monkeypatch):
    from mods import aisession
    seen = {}
    monkeypatch.setattr(aisession, "_ai_agentic_or_error",
                        lambda messages, db, **kw: (seen.update(sys=messages[0]["content"]),
                                                    ("好", [], [], None))[1])
    pid = auth_client.post("/api/aichat/projects", json={"name": "申论批改"}).get_json()["id"]
    auth_client.post("/api/aichat/projects/%d/files" % pid,
                     json={"name": "评分标准.txt", "text": "采分点：对策要具体可行"})
    cid = auth_client.post("/api/aichat/chats", json={"project_id": pid}).get_json()["id"]
    auth_client.post("/api/aichat/chats/%d/send" % cid, json={"content": "帮我批"})
    assert "采分点：对策要具体可行" in seen["sys"]
