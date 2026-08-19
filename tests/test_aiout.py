"""AI 产出：生成 → 看/改/归档 → 投放。

它是**中转站不是第二个云盘**：没归档的 30 天自己清掉，投放一律复用各容器自己的
入库助手（配额、去重、目录归它们管）。
"""
import sqlite3

import pytest

from conftest import DB
from mods import aiout


@pytest.fixture
def out(auth_client):
    """造一份产出，返回 (client, id)。

    先清空这个用户的产出：库是整场测试共用的，不清的话「列表里有几条」这类断言
    会被前一条测试留下的东西带偏（第一次写就踩了）。
    """
    con = sqlite3.connect(DB, timeout=10)
    uid = con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    con.execute("DELETE FROM ai_outputs WHERE user_id=?", (uid,))
    cur = con.execute("INSERT INTO ai_outputs(user_id,kind,title,body,size) VALUES(?,?,?,?,?)",
                      (uid, "md", "资料分析速算", "# 速算\n\n- 截位直除\n- **化除为乘**", 20))
    oid = cur.lastrowid
    con.commit()
    con.close()
    return auth_client, oid


def test_列表能看到并带上保留期限(out):
    c, oid = out
    d = c.get("/api/aiout").get_json()
    assert d["retain_days"] == aiout.RETAIN_DAYS
    assert [x["id"] for x in d["items"]] == [oid]
    assert d["items"][0]["title"] == "资料分析速算"
    assert "body" not in d["items"][0], "列表不该把每份全文都发下来"


def test_看全文与改名(out):
    c, oid = out
    assert "截位直除" in c.get("/api/aiout/%d" % oid).get_json()["body"]
    assert c.put("/api/aiout/%d" % oid, json={"title": "速算三招"}).get_json()["title"] == "速算三招"
    assert c.put("/api/aiout/%d" % oid, json={"title": "  "}).status_code == 400


def test_归档就免于自动清理(out):
    c, oid = out
    assert c.put("/api/aiout/%d" % oid, json={"kept": True}).get_json()["kept"] is True
    con = sqlite3.connect(DB, timeout=10)
    con.execute("UPDATE ai_outputs SET created_at=datetime('now','localtime','-99 day') WHERE id=?", (oid,))
    con.commit()
    con.close()
    assert [x["id"] for x in c.get("/api/aiout").get_json()["items"]] == [oid], "归过档的被清掉了"

    c.put("/api/aiout/%d" % oid, json={"kept": False})
    assert c.get("/api/aiout").get_json()["items"] == [], "没归档的过期了该清掉"


def test_下载md和pdf都出得来(out):
    c, oid = out
    r = c.get("/api/aiout/%d/download" % oid)
    assert r.status_code == 200 and "截位直除" in r.get_data(as_text=True)

    con = sqlite3.connect(DB, timeout=10)
    con.execute("UPDATE ai_outputs SET kind='pdf' WHERE id=?", (oid,))
    con.commit()
    con.close()
    r = c.get("/api/aiout/%d/download" % oid)
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    assert r.get_data()[:4] == b"%PDF", "PDF 没生成出来（中文字体那条路断了？）"


def test_投到资料库并留下痕迹(out):
    c, oid = out
    d = c.post("/api/aiout/%d/send" % oid, json={"dest": "material"}).get_json()
    assert d["where"] == "资料库"
    con = sqlite3.connect(DB, timeout=10)
    row = con.execute("SELECT sent, kept FROM ai_outputs WHERE id=?", (oid,)).fetchone()
    n = con.execute("SELECT COUNT(*) FROM materials WHERE title='资料分析速算'").fetchone()[0]
    con.close()
    assert n == 1, "资料库里没落下东西"
    assert "资料库" in row[0], "投过哪儿要留痕，不然用户会重复投"
    assert row[1] == 1, "投出去了显然还想留着，该顺手归档"


def test_投到小记(out):
    c, oid = out
    assert c.post("/api/aiout/%d/send" % oid, json={"dest": "note"}).get_json()["where"] == "小记"
    con = sqlite3.connect(DB, timeout=10)
    n = con.execute("SELECT COUNT(*) FROM notes WHERE content LIKE '%截位直除%'").fetchone()[0]
    con.close()
    assert n == 1


def test_乱填目的地不投(out):
    c, oid = out
    assert c.post("/api/aiout/%d/send" % oid, json={"dest": "云盘"}).status_code == 400
    assert c.post("/api/aiout/%d/send" % oid, json={}).status_code == 400


def test_别人的产出看不到也删不掉(auth_client, flask_app):
    con = sqlite3.connect(DB, timeout=10)
    cur = con.execute("INSERT INTO ai_outputs(user_id,kind,title,body) VALUES(9999,'md','别人的','x')")
    oid = cur.lastrowid
    con.commit()
    con.close()
    assert auth_client.get("/api/aiout/%d" % oid).status_code == 404
    auth_client.delete("/api/aiout/%d" % oid)
    con = sqlite3.connect(DB, timeout=10)
    still = con.execute("SELECT COUNT(*) FROM ai_outputs WHERE id=?", (oid,)).fetchone()[0]
    con.close()
    assert still == 1, "把别人的产出删掉了"
