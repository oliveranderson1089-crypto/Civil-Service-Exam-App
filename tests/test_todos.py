"""todos 蓝图：互监共享待办（集成）。

todos 改动 1 次、零测试。互监是「组队 + 交叉确认」：待办谁都能加，但打勾只能给**搭档**打、
不能给自己打（防自己给自己刷完成），而且谁确认的谁才能撤销。这些是这个功能的安全/公平
核心 —— 前端 team.js 也有对应提示，但真正的门必须在后端。

happy path 要两个真实登录用户，这里用「库里直接建队：tester + 假搭档 99999」测错误路径
与自打勾规则（不需要第二个真会话）。
"""
import sqlite3

import pytest

from conftest import DB

PARTNER = 99999


def _exec(*stmts):
    """在一个连接里跑几条写语句、提交、关闭。try/finally 保证不泄漏（泄漏会持锁死后面的测试）。
    stmts 每项是 (sql, params) 或单个 sql 串。返回最后一条的 lastrowid。"""
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


def _query(sql, params=()):
    con = sqlite3.connect(DB, timeout=10)
    try:
        return con.execute(sql, params).fetchone()
    finally:
        con.close()


def _uid():
    return _query("SELECT id FROM users WHERE username='tester'")[0]


def _make_team(with_partner=True):
    """给 tester 建一个队；with_partner 时再塞一个假搭档。返回 team_id。"""
    me = _uid()                                       # 先在独立连接取完 uid（不在写事务里嵌套开连接）
    tid = _exec("INSERT INTO teams DEFAULT VALUES")
    _exec(("INSERT INTO team_members(team_id, user_id) VALUES(?,?)", (tid, me)))
    if with_partner:
        _exec(("INSERT OR IGNORE INTO users(id, username, password_hash) VALUES(?,?,?)", (PARTNER, "搭档", "x")),
              ("INSERT INTO team_members(team_id, user_id) VALUES(?,?)", (tid, PARTNER)))
    return tid


@pytest.fixture(autouse=True)
def _clean(auth_client):
    _exec(*[f"DELETE FROM {t}" for t in ("shared_todos", "shared_todo_done", "teams", "team_members")],
          ("DELETE FROM users WHERE id=?", (PARTNER,)))


def test_没组队不能加共享待办(auth_client):
    r = auth_client.post("/api/shared_todos", json={"text": "一起做两套题"})
    assert r.status_code == 400
    assert "组队" in r.get_json()["error"]


def test_组队后能加共享待办(auth_client):
    _make_team()
    r = auth_client.post("/api/shared_todos", json={"text": "一起做两套题"})
    assert r.status_code == 201


def test_不能给自己打勾(auth_client):
    _make_team()
    tid = auth_client.post("/api/shared_todos", json={"text": "背单词"}).get_json()["id"]
    r = auth_client.post(f"/api/shared_todos/{tid}/toggle", json={"user_id": _uid()})
    assert r.status_code == 403
    assert "自己" in r.get_json()["error"], "自己给自己打勾没被挡住 —— 互监就形同虚设"


def test_能给搭档打勾(auth_client):
    _make_team()
    tid = auth_client.post("/api/shared_todos", json={"text": "背单词"}).get_json()["id"]
    r = auth_client.post(f"/api/shared_todos/{tid}/toggle", json={"user_id": PARTNER})
    assert r.status_code == 200
    d = r.get_json()
    assert d["done"] is True
    assert PARTNER in d["done_ids"]


def test_没组队不能打勾(auth_client):
    # 直接塞一条无主待办，未组队的人 toggle 该 403
    _exec("INSERT INTO shared_todos(id, text, team_id) VALUES(777, 'x', 1)")
    r = auth_client.post("/api/shared_todos/777/toggle", json={"user_id": PARTNER})
    assert r.status_code == 403


def test_不能给非互监成员打勾(auth_client):
    _make_team()
    tid = auth_client.post("/api/shared_todos", json={"text": "背单词"}).get_json()["id"]
    r = auth_client.post(f"/api/shared_todos/{tid}/toggle", json={"user_id": 55555})  # 55555 不在队里
    assert r.status_code == 400
    assert "成员" in r.get_json()["error"]


def test_打勾不存在的待办返回404(auth_client):
    _make_team()
    r = auth_client.post("/api/shared_todos/123456/toggle", json={"user_id": PARTNER})
    assert r.status_code == 404


def test_别人确认的勾只有确认人能撤(auth_client):
    _make_team()
    tid = auth_client.post("/api/shared_todos", json={"text": "背单词"}).get_json()["id"]
    # 塞一条「搭档的完成，由另一个人(88)确认」的记录，tester 撤不动
    _exec(("INSERT INTO shared_todo_done(todo_id, user_id, username, by_user, by_name) VALUES(?,?,?,?,?)",
           (tid, PARTNER, "partner", 88, "someone")))
    r = auth_client.post(f"/api/shared_todos/{tid}/toggle", json={"user_id": PARTNER})
    assert r.status_code == 403
    assert "确认人" in r.get_json()["error"]
