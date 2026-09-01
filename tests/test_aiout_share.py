"""AI 产出 → 分享出去：发到聊天（好友 / 小组）、共享给队友。

这一页是**中转站**：没归档的 30 天就清掉，磁盘上也没有对应的文件。分享因此有两条
绕不过去的前提，测试盯的就是它们：

· 发到聊天前必须先把产出渲染成字节、登记进自己云盘（群消息只存发送方那一行；
  就算是发给好友，对方点开时产出也可能已经被清理带走了）；
· 「共享给队友」不另造一套共享表，而是先投进自己的资料库再挂 material_shares ——
  否则队友看到的是一个随时会消失的东西。

越权是这里最要紧的一条线：不是好友、不在组里、不是队友的，混进请求也得被丢掉。
"""
import os
import sqlite3

import pytest

from conftest import DB
from mods import social

A, B = 94001, 94002        # 两个好友
MATE = 94003               # 队友（同时也是好友，组队和加好友是两回事）
OUT = 94009                # 陌生人：不是好友、不在组里、不是队友


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


def _q(sql, params=()):
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


@pytest.fixture
def me(auth_client):
    """一个干净的场子：我 + 两个好友 + 一个队友 + 一个陌生人。

    库是整场测试共用的，产出、消息、资料、队伍全清一遍 —— 不清的话「资料库里有几份」
    这类断言会被别的测试留下的东西带偏（test_aiout 那边第一次写就踩过）。
    """
    u = _q("SELECT id FROM users WHERE username='tester'")[0]["id"]
    _exec("DELETE FROM ai_outputs", "DELETE FROM chat_msgs", "DELETE FROM friends",
          "DELETE FROM conv_members", "DELETE FROM conversations", "DELETE FROM notifications",
          "DELETE FROM drive_files", "DELETE FROM materials", "DELETE FROM material_shares",
          "DELETE FROM team_members", "DELETE FROM teams")
    for f, name in ((A, "友甲94001"), (B, "友乙94002"),
                    (MATE, "队友94003"), (OUT, "路人94009")):
        _exec(("INSERT OR REPLACE INTO users(id,username,password_hash) VALUES(?,?,?)",
               (f, name, "x")))
    for f in (A, B, MATE):
        _exec(("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (u, f)),
              ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (f, u)))
    return u


@pytest.fixture
def out(me):
    """一份 md 产出，返回它的 id。"""
    return _exec(("INSERT INTO ai_outputs(user_id,kind,title,body,size) VALUES(?,?,?,?,?)",
                  (me, "md", "资料分析速算", "# 速算\n\n- 截位直除\n- **化除为乘**", 20)))


def _team(me, *mates):
    """把我和这些人塞进同一个队。"""
    tid = _exec("INSERT INTO teams DEFAULT VALUES")
    for x in (me,) + mates:
        _exec(("INSERT OR REPLACE INTO team_members(team_id,user_id) VALUES(?,?)", (tid, x)))
    return tid


def _as(flask_app, user_id):
    c = flask_app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = user_id
    return c


def _group(c, name="省考冲刺组", members=(A, B)):
    return c.post("/api/chat/groups", json={"name": name, "members": list(members)}).get_json()["id"]


# ---- 发到聊天 ----

def test_一次发给多个好友和多个小组(auth_client, me, out):
    g1, g2 = _group(auth_client, "甲组"), _group(auth_client, "乙组")
    r = auth_client.post("/api/aiout/%d/chat" % out, json={"users": [A, B], "groups": [g1, g2]})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    assert r.get_json()["n"] == 4

    direct = _q("SELECT to_uid, file_name, kind FROM chat_msgs WHERE from_uid=? AND to_uid<>0", (me,))
    assert {x["to_uid"] for x in direct} == {A, B}
    assert all(x["kind"] == "file" and x["file_name"] == "资料分析速算.md" for x in direct)
    grp = _q("SELECT conv_id FROM chat_msgs WHERE from_uid=? AND to_uid=0", (me,))
    assert {x["conv_id"] for x in grp} == {g1, g2}


def test_发出去要先在自己云盘登记一行(auth_client, me, out):
    """产出只活在数据库里，磁盘上没有文件。群消息只存发送方那一行、file_id 指的就是它，
    这一步少了群里点开就是 404。"""
    g = _group(auth_client)
    assert auth_client.post("/api/aiout/%d/chat" % out, json={"groups": [g]}).status_code == 200
    mine = _q("SELECT id, folder, name FROM drive_files WHERE owner_id=? AND is_dir=0", (me,))
    assert [(x["folder"], x["name"]) for x in mine] == [("聊天文件", "资料分析速算.md")]
    assert _q("SELECT file_id FROM chat_msgs WHERE conv_id=?", (g,))[0]["file_id"] == mine[0]["id"]


def test_收件人那边下得到东西(auth_client, me, out, flask_app):
    """30 天后产出就没了，对方点开的必须是一份实体文件，不是指回产出表的一个 id。"""
    auth_client.post("/api/aiout/%d/chat" % out, json={"users": [A]})
    got = _q("SELECT id, folder, name FROM drive_files WHERE owner_id=?", (A,))
    assert [(x["folder"], x["name"]) for x in got] == [("聊天文件", "资料分析速算.md")]
    r = _as(flask_app, A).get("/api/drive/%d/download" % got[0]["id"])
    assert r.status_code == 200 and "截位直除" in r.get_data(as_text=True)


def test_pdf产出发出去的是真pdf(auth_client, me, out):
    """pdf 不落盘、每次现渲染。发聊天这条路要是没走 output_bytes，发出去的就是 markdown 源码。"""
    _exec(("UPDATE ai_outputs SET kind='pdf' WHERE id=?", (out,)))
    assert auth_client.post("/api/aiout/%d/chat" % out, json={"users": [A]}).status_code == 200
    row = _q("SELECT name, stored_name FROM drive_files WHERE owner_id=? AND is_dir=0", (me,))[0]
    assert row["name"] == "资料分析速算.pdf"
    with open(os.path.join(social._drive_dir(me), row["stored_name"]), "rb") as f:
        assert f.read(4) == b"%PDF"


def test_发过就顺手归档并留痕(auth_client, me, out):
    """都发给人了显然还想留着 —— 不归档的话 30 天后自己没了，对方也就下不到。"""
    auth_client.post("/api/aiout/%d/chat" % out, json={"users": [A]})
    row = _q("SELECT sent, kept FROM ai_outputs WHERE id=?", (out,))[0]
    assert "聊天" in (row["sent"] or ""), "投过哪儿要留痕，不然用户会重复发"
    assert row["kept"] == 1


def test_越权的目标被丢掉(auth_client, me, out):
    other = _exec(("INSERT INTO conversations(kind,title,owner_id) VALUES('group','别人的组',?)", (OUT,)))
    r = auth_client.post("/api/aiout/%d/chat" % out,
                         json={"users": [A, OUT], "groups": [other]})
    assert r.get_json()["n"] == 1, "只有那个好友该收到"
    assert not _q("SELECT 1 FROM chat_msgs WHERE to_uid=? OR conv_id=?", (OUT, other))


def test_一个人都没选就别发(auth_client, me, out):
    assert auth_client.post("/api/aiout/%d/chat" % out, json={"users": [], "groups": []}).status_code == 400
    assert not _q("SELECT 1 FROM drive_files WHERE owner_id=?", (me,)), \
        "没发成还在云盘里登记了一行，等于白占盘"


def test_别人的产出发不了(auth_client, me):
    oid = _exec(("INSERT INTO ai_outputs(user_id,kind,title,body) VALUES(?,'md','别人的','x')", (OUT,)))
    assert auth_client.post("/api/aiout/%d/chat" % oid, json={"users": [A]}).status_code == 404
    assert not _q("SELECT 1 FROM chat_msgs")


def test_云盘满了说清楚且不留残骸(auth_client, me, out, monkeypatch):
    def full(*a, **kw):
        raise social.QuotaFull()
    monkeypatch.setattr(social, "_register_blob", full)
    r = auth_client.post("/api/aiout/%d/chat" % out, json={"users": [A]})
    assert r.status_code == 400 and "空间不足" in r.get_json()["error"]
    left = [f for f in os.listdir(social._drive_dir(me)) if f.startswith(".tmp_aiout_")]
    assert not left, "临时文件没删掉：%s" % left


def test_渲染失败不算发成功(auth_client, me, out, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("字体没了")
    monkeypatch.setattr(social, "output_bytes", boom)
    r = auth_client.post("/api/aiout/%d/chat" % out, json={"users": [A]})
    assert r.status_code == 400 and "生成文件失败" in r.get_json()["error"]
    assert not _q("SELECT 1 FROM chat_msgs")
    assert _q("SELECT kept FROM ai_outputs WHERE id=?", (out,))[0]["kept"] == 0, "没发出去却归了档"


# ---- 共享给队友 ----

def test_能共享给谁就是我的队友(auth_client, me, out):
    _team(me, MATE)
    d = auth_client.get("/api/aiout/%d/team" % out).get_json()
    assert [(m["id"], m["username"]) for m in d["members"]] == [(MATE, "队友94003")]


def test_没队伍时列表是空的(auth_client, me, out):
    """好友≠队友。这一条错了，界面会把所有好友都摆上去。"""
    assert auth_client.get("/api/aiout/%d/team" % out).get_json()["members"] == []


def test_共享等于先投进自己资料库再挂共享(auth_client, me, out, flask_app):
    _team(me, MATE)
    r = auth_client.post("/api/aiout/%d/team" % out, json={"to": [MATE]})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    d = r.get_json()
    assert d["n"] == 1

    mine = _q("SELECT id, title FROM materials WHERE user_id=?", (me,))
    assert [x["title"] for x in mine] == ["资料分析速算"], "共享的东西得先在资料库里落一份"
    assert d["material_id"] == mine[0]["id"]
    assert _q("SELECT to_user FROM material_shares WHERE material_id=?",
              (d["material_id"],))[0]["to_user"] == MATE

    # 端到端：队友在自己的资料库里确实看得到，且标着「共享来的、只读」
    items = _as(flask_app, MATE).get("/api/materials").get_json()["items"]
    assert [(x["title"], x["shared"], x["shared_from"]) for x in items] == \
        [("资料分析速算", 1, "tester")]


def test_共享完也归档留痕(auth_client, me, out):
    _team(me, MATE)
    auth_client.post("/api/aiout/%d/team" % out, json={"to": [MATE]})
    row = _q("SELECT sent, kept FROM ai_outputs WHERE id=?", (out,))[0]
    assert "资料库" in (row["sent"] or "") and row["kept"] == 1


def test_不是队友的混进来也共享不出去(auth_client, me, out):
    _team(me, MATE)
    r = auth_client.post("/api/aiout/%d/team" % out, json={"to": [MATE, OUT, A]})
    assert r.get_json()["n"] == 1, "只有队友该拿到"
    assert {x["to_user"] for x in _q("SELECT to_user FROM material_shares")} == {MATE}


def test_全是非队友就当没选人(auth_client, me, out):
    """400 要挡在投放**之前** —— 不然资料库里凭空多一份没共享给任何人的副本。"""
    _team(me, MATE)
    assert auth_client.post("/api/aiout/%d/team" % out, json={"to": [OUT, A]}).status_code == 400
    assert auth_client.post("/api/aiout/%d/team" % out, json={}).status_code == 400
    assert not _q("SELECT 1 FROM materials"), "没共享成却在资料库留下了副本"


def test_每点一次都是新的一份副本(auth_client, me, out):
    """产出改了再共享是常事，硬去认「上次投的是哪一份」只会认错，所以这里就是投两份。
    刻意的行为，写下来免得以后当 bug「修」掉。"""
    _team(me, MATE)
    a = auth_client.post("/api/aiout/%d/team" % out, json={"to": [MATE]}).get_json()
    b = auth_client.post("/api/aiout/%d/team" % out, json={"to": [MATE]}).get_json()
    assert a["material_id"] != b["material_id"]
    assert len(_q("SELECT 1 FROM materials WHERE user_id=?", (me,))) == 2
    assert len(_q("SELECT 1 FROM material_shares WHERE to_user=?", (MATE,))) == 2


def test_别人的产出共享不出去(auth_client, me, flask_app):
    """拿到 id 也不行 —— 共享是越权最要紧的地方。"""
    _team(me, MATE)
    oid = _exec(("INSERT INTO ai_outputs(user_id,kind,title,body) VALUES(?,'md','别人的','x')", (OUT,)))
    assert auth_client.get("/api/aiout/%d/team" % oid).status_code == 404
    assert auth_client.post("/api/aiout/%d/team" % oid, json={"to": [MATE]}).status_code == 400
    assert not _q("SELECT 1 FROM materials"), "把别人的产出投进了我的资料库"
    assert not _q("SELECT 1 FROM material_shares")
