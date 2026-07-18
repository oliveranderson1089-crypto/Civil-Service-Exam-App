"""team 蓝图：组队申请/解散的校验（集成）。

team 改动 2 次、零测试。组队是邀请制，发申请前有一串门要过：不能组队自己、账号要存在、
自己没在队里、对方也没组队、没有重复申请。解散：没组队不能发、独队直接散。full 的
接受/拒绝流程要两个真会话，这里用库直接建队/建用户测这些校验（单会话可覆盖）。
"""
import sqlite3

import pytest

from conftest import DB

OTHER = 90002       # 一个真实存在但没组队的账号
TEAMMATE = 90003    # 已经和别人组队的账号


def _uid():
    con = sqlite3.connect(DB, timeout=10)
    try:
        return con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    finally:
        con.close()


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


@pytest.fixture(autouse=True)
def _clean(auth_client):
    _exec(*[f"DELETE FROM {t}" for t in ("teams", "team_members", "team_requests")],
          ("DELETE FROM users WHERE id IN (?,?)", (OTHER, TEAMMATE)))
    # 一个可被邀请的空闲账号
    _exec(("INSERT OR IGNORE INTO users(id, username, password_hash) VALUES(?,?,?)", (OTHER, "小明", "x")))


def _make_my_team():
    tid = _exec("INSERT INTO teams DEFAULT VALUES")
    _exec(("INSERT INTO team_members(team_id, user_id) VALUES(?,?)", (tid, _uid())))
    return tid


def test_不能组队自己(auth_client):
    r = auth_client.post("/api/team/request", json={"to_uid": _uid()})
    assert r.status_code == 400


def test_组队不存在的账号返回404(auth_client):
    r = auth_client.post("/api/team/request", json={"to_uid": 999999})
    assert r.status_code == 404


def test_正常发起组队申请返回201(auth_client):
    r = auth_client.post("/api/team/request", json={"to_uid": OTHER})
    assert r.status_code == 201


def test_自己已在队里不能再组队(auth_client):
    _make_my_team()
    r = auth_client.post("/api/team/request", json={"to_uid": OTHER})
    assert r.status_code == 400
    assert "已经在一个队" in r.get_json()["error"]


def test_对方已组队不能拉他(auth_client):
    # OTHER 已经和 TEAMMATE 组了队
    tid = _exec("INSERT INTO teams DEFAULT VALUES")
    _exec(("INSERT OR IGNORE INTO users(id, username, password_hash) VALUES(?,?,?)", (TEAMMATE, "小红", "x")),
          ("INSERT INTO team_members(team_id, user_id) VALUES(?,?)", (tid, OTHER)),
          ("INSERT INTO team_members(team_id, user_id) VALUES(?,?)", (tid, TEAMMATE)))
    r = auth_client.post("/api/team/request", json={"to_uid": OTHER})
    assert r.status_code == 400
    assert "对方已经组队" in r.get_json()["error"]


def test_重复申请被拒(auth_client):
    auth_client.post("/api/team/request", json={"to_uid": OTHER})
    r = auth_client.post("/api/team/request", json={"to_uid": OTHER})
    assert r.status_code == 400
    assert "待处理的组队申请" in r.get_json()["error"]


def test_没组队不能发解散(auth_client):
    r = auth_client.post("/api/team/disband", json={})
    assert r.status_code == 400
    assert "还没组队" in r.get_json()["error"]


def test_队里只剩自己直接解散(auth_client):
    _make_my_team()   # 只有 tester 一个人
    r = auth_client.post("/api/team/disband", json={})
    assert r.status_code == 200
    assert r.get_json().get("disbanded") is True
