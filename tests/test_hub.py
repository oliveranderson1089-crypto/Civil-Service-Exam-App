"""/api/hub：「练」「积累」两个标签页的状态数字（集成，走真实登录态）。

这个接口回答的是「该往哪使劲」，所以它最该防的是**说反话**：

  · 一道题没练过的板块必须没有正确率，不能显示 0% —— 那会让人以为自己练砸了，
    正好把该练的和没练的调了个个儿；
  · 正确率只看近 30 天。全时段算的话，两个月前突击过的板块会一直显示高分，
    而这一格的全部意义就是提醒「现在」哪儿弱；
  · 数只能数自己的。别人的成绩混进来，这一屏就成了摆设。

外加一条兜底：缺表只赔那一格。导航页 500 等于整个标签栏点不动，比首页挂了还难受。
"""
import sqlite3
from datetime import datetime, timedelta

import pytest

from conftest import DB


def _db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _me(con, account):
    return con.execute("SELECT id FROM users WHERE username=?", (account["username"],)).fetchone()["id"]


@pytest.fixture(autouse=True)
def _clean(auth_client):
    con = _db()
    con.execute("DELETE FROM drill_records")
    con.execute("DELETE FROM wrong_questions")
    today = datetime.now().strftime("%Y-%m-%d")
    con.execute("DELETE FROM sucai_items WHERE date=?", (today,))
    con.execute("DELETE FROM entries WHERE date(created_at)=?", (today,))
    con.commit()
    con.close()


def _drill(con, u, board, total, correct, days_ago=0):
    at = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    con.execute("INSERT INTO drill_records(user_id,board,total,correct,seconds,created_at)"
                " VALUES(?,?,?,?,60,?)", (u, board, total, correct, at))


def test_没练过的板块不给正确率而不是给0(auth_client, account):
    con = _db()
    u = _me(con, account)
    con.execute("INSERT INTO wrong_questions(user_id,board,question) VALUES(?,'数量关系','x')", (u,))
    con.commit(); con.close()
    b = auth_client.get("/api/hub").get_json()["boards"]
    assert b["数量关系"]["rate"] is None, "一道题没练过却报了个正确率，等于说人家练砸了"
    assert b["数量关系"]["wrong"] == 1, "有错题的板块也该出现，不能因为没练过就整个不列"


def test_正确率按近30天算(auth_client, account):
    con = _db()
    u = _me(con, account)
    _drill(con, u, "资料分析", 10, 10, days_ago=0)     # 今天：10/10
    _drill(con, u, "资料分析", 10, 0, days_ago=90)     # 三个月前：0/10，不该算进来
    con.commit(); con.close()
    b = auth_client.get("/api/hub").get_json()["boards"]
    assert b["资料分析"]["rate"] == 100, "把三个月前的旧账算进了当前水平"
    assert b["资料分析"]["q"] == 10


def test_正确率四舍五入到整数(auth_client, account):
    con = _db()
    u = _me(con, account)
    _drill(con, u, "言语理解与表达", 3, 2)
    con.commit(); con.close()
    assert auth_client.get("/api/hub").get_json()["boards"]["言语理解与表达"]["rate"] == 67


def test_只数自己的成绩(auth_client, account):
    con = _db()
    u = _me(con, account)
    _drill(con, u + 999, "判断推理", 100, 100)
    con.commit(); con.close()
    assert auth_client.get("/api/hub").get_json()["boards"] == {}, "别人的成绩混进了我的看板"


def test_积累角标分全局内容和本人收录(auth_client, account):
    d0 = auth_client.get("/api/hub").get_json()["date"]
    con = _db()
    u = _me(con, account)
    # 素材是 cron 每天产出的全局内容
    con.execute("INSERT INTO sucai_items(date,kind,topic,content) VALUES(?,'人物','a','x')", (d0,))
    con.execute("INSERT INTO sucai_items(date,kind,topic,content) VALUES(?,'衔接表达','b','y')", (d0,))
    # 成语是自己收的，得挂 user_id
    con.execute("INSERT INTO entries(user_id,word) VALUES(?,'络绎不绝')", (u,))
    con.execute("INSERT INTO entries(user_id,word) VALUES(?,'名副其实')", (u + 999,))
    con.commit(); con.close()

    acc = auth_client.get("/api/hub").get_json()["acc"]
    assert acc["sucai"] == 1, "衔接表达被算进了素材积累（两个是不同的入口）"
    assert acc["lianjie"] == 1
    assert acc["idiom"] == 1, "别人收的成语算到了我的今日新增"


def test_没有新增的模块不出现在角标里(auth_client, account):
    acc = auth_client.get("/api/hub").get_json()["acc"]
    assert 0 not in acc.values(), "0 条也回了，前端还得自己再过滤一遍"


def test_一张表坏了只赔那一格(auth_client, monkeypatch):
    from mods import hub as hubmod
    bad = dict(hubmod._ACC_GLOBAL)
    bad["news"] = "SELECT COUNT(*) FROM 根本没有这张表 WHERE date(created_at)=?"
    monkeypatch.setattr(hubmod, "_ACC_GLOBAL", bad)
    r = auth_client.get("/api/hub")
    assert r.status_code == 200, "缺一张表就把整个导航页的状态打成 500 了"
    assert "news" not in r.get_json()["acc"]
