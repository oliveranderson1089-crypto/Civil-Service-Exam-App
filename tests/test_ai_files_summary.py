"""AI 出文件 / 投放，以及「汇总这段对话」。

生成和投放拆成两个工具：生成随时能重来，投放是**东西离开这个助手**的动作，
所以只有投放要用户点头。合成一个的话，AI 每写一版都会往资料库堆一份。
"""
import sqlite3

import pytest

from conftest import DB
from mods import aisession
from mods.agent_tools import TOOL_REGISTRY, exec_tool


def _uid():
    con = sqlite3.connect(DB, timeout=10)
    try:
        return con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    finally:
        con.close()


@pytest.fixture
def ctx(auth_client):
    """在请求上下文里跑工具（工具内部要 uid() / get_db()）。"""
    import app as appmod
    from core import get_db
    with appmod.app.test_request_context():
        from flask import session
        session["user_id"] = _uid()
        yield get_db()


# ---------------- 生成 ----------------

def test_生成文件落进AI产出(ctx):
    msg, action = exec_tool("create_file", {"title": "速算三招", "content": "# 速算\n- 截位直除"}, ctx)
    assert "已存进" in msg and "速算三招" in msg
    assert action["type"] == "refresh"
    row = ctx.execute("SELECT title, kind, body FROM ai_outputs ORDER BY id DESC LIMIT 1").fetchone()
    assert row["title"] == "速算三招" and row["kind"] == "md"
    assert "截位直除" in row["body"]


def test_生成不要确认投放才要确认():
    """生成写进的是用户自己的产出库，随时能删；投放会让东西进到别的容器。"""
    assert TOOL_REGISTRY["create_file"]["confirm"] is False
    assert TOOL_REGISTRY["deliver_file"]["confirm"] is True
    assert TOOL_REGISTRY["deliver_file"]["preview"] is not None, "确认弹窗得说清哪份东西去哪儿"


def test_确认弹窗说得出是哪份东西去哪儿(ctx):
    exec_tool("create_file", {"title": "行测公式", "content": "x"}, ctx)
    oid = ctx.execute("SELECT id FROM ai_outputs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    pv = TOOL_REGISTRY["deliver_file"]["preview"]({"id": oid, "dest": "material"}, ctx)
    assert "行测公式" in pv and "资料库" in pv


def test_标题或正文空着就不生成(ctx):
    before = ctx.execute("SELECT COUNT(*) c FROM ai_outputs").fetchone()["c"]
    exec_tool("create_file", {"title": "", "content": "有正文"}, ctx)
    exec_tool("create_file", {"title": "有标题", "content": "   "}, ctx)
    assert ctx.execute("SELECT COUNT(*) c FROM ai_outputs").fetchone()["c"] == before


# ---------------- 投放 ----------------

def test_投放走的是资料库自己的入库助手(ctx):
    exec_tool("create_file", {"title": "申论模板", "content": "开头段…"}, ctx)
    oid = ctx.execute("SELECT id FROM ai_outputs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    msg, action = exec_tool("deliver_file", {"id": oid, "dest": "material", "_confirmed": True}, ctx)
    assert "资料库" in msg
    assert action["type"] == "refresh"
    n = ctx.execute("SELECT COUNT(*) c FROM materials WHERE title='申论模板'").fetchone()["c"]
    assert n == 1, "没真的落进资料库"


def test_投放不存在的产出只是说找不到不炸(ctx):
    msg, action = exec_tool("deliver_file", {"id": 99999, "dest": "note", "_confirmed": True}, ctx)
    assert "找不到" in msg and action is None


def test_list_files列得出刚生成的(ctx):
    exec_tool("create_file", {"title": "常识清单", "content": "一、"}, ctx)
    msg, _ = exec_tool("list_files", {}, ctx)
    assert "常识清单" in msg


# ---------------- 汇总 ----------------

@pytest.fixture
def chat_with_talk(auth_client):
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    con = sqlite3.connect(DB, timeout=10)
    for role, body in [("user", "资料分析总是超时怎么办"),
                       ("assistant", "先练截位直除，**误差控制在 5% 以内**"),
                       ("user", "那增长率呢"),
                       ("assistant", "用 a/(1+r) 估算")]:
        con.execute("INSERT INTO ai_msgs(chat_id,role,content,kind) VALUES(?,?,?,'text')",
                    (cid, role, body))
    con.execute("UPDATE ai_chats SET title='资料分析提速' WHERE id=?", (cid,))
    con.commit()
    con.close()
    return auth_client, cid


def test_汇总落进AI产出而不是塞回对话(chat_with_talk, monkeypatch):
    c, cid = chat_with_talk
    monkeypatch.setattr(aisession, "_sum_call", lambda prompt, text: "## 结论\n**截位直除**")
    d = c.post("/api/aichat/chats/%d/summary" % cid, json={}).get_json()
    assert d["title"] == "资料分析提速 · 纪要"
    assert d["parts"] == 1, "这么短的对话不该分段（白多花一次钱）"
    con = sqlite3.connect(DB, timeout=10)
    row = con.execute("SELECT title, chat_id FROM ai_outputs WHERE id=?", (d["id"],)).fetchone()
    n = con.execute("SELECT COUNT(*) FROM ai_msgs WHERE chat_id=?", (cid,)).fetchone()[0]
    con.close()
    assert row[1] == cid, "产出要记得自己是哪次对话来的，不然点不回去"
    assert n == 4, "汇总不该往对话历史里塞东西"


def test_长对话分段汇总再合并(chat_with_talk, monkeypatch):
    c, cid = chat_with_talk
    con = sqlite3.connect(DB, timeout=10)
    for i in range(6):
        con.execute("INSERT INTO ai_msgs(chat_id,role,content,kind) VALUES(?,'assistant',?,'text')",
                    (cid, "长内容" * 2000))
    con.commit()
    con.close()
    calls = []
    monkeypatch.setattr(aisession, "_sum_call",
                        lambda prompt, text: calls.append(len(text)) or "## 结论\n要点")
    d = c.post("/api/aichat/chats/%d/summary" % cid, json={}).get_json()
    assert d["parts"] > 1, "超预算了还整段塞，会被截或者直接超上下文"
    assert len(calls) == d["parts"] + 1, "该是「每段各出要点 + 合并一次」"
    assert max(calls[:-1]) <= aisession.SUM_CHUNK + 8000, "分段没起作用"


def test_空对话不给汇总(auth_client):
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    assert auth_client.post("/api/aichat/chats/%d/summary" % cid, json={}).status_code == 400
