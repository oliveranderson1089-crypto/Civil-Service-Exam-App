"""AI 助手：工具轨迹落库、上下文预算、档位、重答/改问/分支（方案乙）。

以前工具调用在生成结束就被丢掉：刷新会话看不到 AI 动过哪些数据，下一轮重建上下文时
模型也不知道自己查过什么，于是同一个查询反复调。这里把「轨迹是一等公民」钉住。
"""
import json
import sqlite3

import pytest

from conftest import DB
from mods import aisession

TRACE = [{"name": "list_wrong_questions", "label": "查你的错题本",
          "args": {"board": "判断推理"}, "result": "共 23 道，定义判断 11 道", "action": ""}]


def _q(sql, args=()):
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


@pytest.fixture
def chat(auth_client):
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    return auth_client, cid


@pytest.fixture
def fake_ai(monkeypatch):
    """录下送进模型的 messages 和档位，回一句固定答复 + 一条工具轨迹。"""
    seen = {"trace": TRACE}

    def fake(messages, db, **kw):
        seen["msgs"] = messages
        seen["tier"] = kw.get("tier")
        return "好的。", [], seen["trace"], None

    monkeypatch.setattr(aisession, "_ai_agentic_or_error", fake)
    return seen


def test_工具轨迹落库且能回放(chat, fake_ai):
    c, cid = chat
    r = c.post("/api/aichat/chats/%d/send" % cid, json={"content": "判断推理我错哪最多"})
    assert r.get_json()["trace"][0]["name"] == "list_wrong_questions"
    row = _q("SELECT kind, meta FROM ai_msgs WHERE chat_id=? AND kind='tool'", (cid,))
    assert len(row) == 1
    assert json.loads(row[0]["meta"])[0]["label"] == "查你的错题本"
    # 刷新会话（重进）时也带得回来
    msgs = c.get("/api/aichat/chats/%d" % cid).get_json()["msgs"]
    tool = [m for m in msgs if m["kind"] == "tool"][0]
    assert tool["trace"][0]["result"].startswith("共 23 道")


def test_轨迹回喂给模型免得重复调用(chat, fake_ai):
    c, cid = chat
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "判断推理我错哪最多"})
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "那定义判断怎么练"})
    sent = "\n".join(m["content"] for m in fake_ai["msgs"])
    assert "list_wrong_questions" in sent and "别重复调用" in sent


def test_上下文按预算装填而不是死板的二十条(chat, fake_ai, monkeypatch):
    c, cid = chat
    con = sqlite3.connect(DB, timeout=10)
    for i in range(40):     # 40 轮短消息：按字符预算能装下远超 20 条
        con.execute("INSERT INTO ai_msgs(chat_id,role,content,kind) VALUES(?,?,?,'text')",
                    (cid, "user", "第%d问" % i))
        con.execute("INSERT INTO ai_msgs(chat_id,role,content,kind) VALUES(?,?,?,'text')",
                    (cid, "assistant", "第%d答" % i))
    con.commit()
    con.close()
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "继续"})
    assert len(fake_ai["msgs"]) > 22, "短消息就该多带几轮，不该固定砍在 20 条"

    # 反过来：塞几条超长的，预算会把更早的挡掉，并留一句交代
    monkeypatch.setattr(aisession, "CTX_BUDGET", 3000)
    con = sqlite3.connect(DB, timeout=10)
    for i in range(6):
        con.execute("INSERT INTO ai_msgs(chat_id,role,content,kind) VALUES(?,?,?,'text')",
                    (cid, "user", "长" * 900))
    con.commit()
    con.close()
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "再继续"})
    sent = "\n".join(m["content"] for m in fake_ai["msgs"])
    assert "因篇幅未附上" in sent
    total = sum(len(m["content"]) for m in fake_ai["msgs"] if m["role"] != "system")
    assert total < 3000 + 900 * aisession.CTX_KEEP, "预算之外还带了太多历史"


def test_档位默认快_可切深度(chat, fake_ai):
    c, cid = chat
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "随便问问"})
    assert fake_ai["tier"] == "fast"
    c.put("/api/aichat/chats/%d" % cid, json={"tier": "pro"})
    assert c.get("/api/aichat/chats/%d" % cid).get_json()["tier"] == "pro"
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "这题难"})
    assert fake_ai["tier"] == "pro", "深度档要真的换模型，不能只是界面上变个样"
    c.put("/api/aichat/chats/%d" % cid, json={"tier": "乱填"})
    assert c.get("/api/aichat/chats/%d" % cid).get_json()["tier"] == "fast"


def test_重答把最后一轮退回去(chat, fake_ai):
    c, cid = chat
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "第一问"})
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "第二问"})
    d = c.post("/api/aichat/chats/%d/retry" % cid, json={}).get_json()
    assert d["content"] == "第二问"
    rows = _q("SELECT content, kind FROM ai_msgs WHERE chat_id=? ORDER BY id", (cid,))
    left = [r["content"] for r in rows]
    assert "第二问" not in left and "第一问" in left
    # 每轮落 3 行（问 + 轨迹 + 答）。退掉第二轮后只该剩第一轮那 3 行 ——
    # 轨迹要跟着那一轮一起退，不然会留下一条没有问题的工具记录。
    assert len(rows) == 3 and sum(1 for r in rows if r["kind"] == "tool") == 1


def test_改问题带新内容重来(chat, fake_ai):
    c, cid = chat
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "错的问法"})
    mid = _q("SELECT id FROM ai_msgs WHERE chat_id=? AND role='user'", (cid,))[0]["id"]
    d = c.post("/api/aichat/chats/%d/retry" % cid,
               json={"msg_id": mid, "content": "对的问法"}).get_json()
    assert d["content"] == "对的问法"
    assert _q("SELECT COUNT(*) n FROM ai_msgs WHERE chat_id=?", (cid,))[0]["n"] == 0


def test_分支复制历史到新会话原对话不动(chat, fake_ai):
    c, cid = chat
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "共同的前半段"})
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "想换个问法的这句"})
    mid = _q("SELECT id FROM ai_msgs WHERE chat_id=? AND role='user' ORDER BY id", (cid,))[1]["id"]
    nid = c.post("/api/aichat/chats/%d/branch" % cid, json={"msg_id": mid}).get_json()["id"]
    new = [m["content"] for m in c.get("/api/aichat/chats/%d" % nid).get_json()["msgs"]]
    assert "共同的前半段" in new and "想换个问法的这句" not in new
    old = [m["content"] for m in c.get("/api/aichat/chats/%d" % cid).get_json()["msgs"]]
    assert "想换个问法的这句" in old, "分支不该动原对话"


def test_删一条用户消息会带走那一整轮(chat, fake_ai):
    c, cid = chat
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "问题甲"})
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "问题乙"})
    first = _q("SELECT id FROM ai_msgs WHERE chat_id=? AND role='user' ORDER BY id", (cid,))[0]["id"]
    c.delete("/api/aichat/chats/%d/msgs/%d" % (cid, first))
    left = [r["content"] for r in _q("SELECT content FROM ai_msgs WHERE chat_id=? ORDER BY id", (cid,))]
    assert "问题甲" not in left and "问题乙" in left, "只删问题、留下答案，下一轮上下文会很怪"
