"""tasks 蓝图：每日任务模板的增删改查（集成，走真实登录态）。

tasks 改动 1 次、零测试。每日任务是「模板 + 每天打勾」两张表：模板长期在，打勾按日期
记。测：加空任务被拒、增查往返、勾/取消当日完成、删模板连带清打勾、所有操作限本人
（AND user_id=?）。
"""
import sqlite3

import pytest

from conftest import DB


@pytest.fixture(autouse=True)
def _clean(auth_client):
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM task_templates")
    con.execute("DELETE FROM task_done")
    con.commit()
    con.close()


def test_加空任务返回400(auth_client):
    r = auth_client.post("/api/daily_tasks/templates", json={"text": "   "})
    assert r.status_code == 400


def test_增查往返(auth_client):
    r = auth_client.post("/api/daily_tasks/templates", json={"text": "做两套行测"})
    assert r.status_code == 201
    d = auth_client.get("/api/daily_tasks").get_json()
    assert d["total"] == 1
    assert d["items"][0]["text"] == "做两套行测"
    assert d["items"][0]["done"] is False, "刚加的任务不该是已完成"


def test_勾选与取消当日完成(auth_client):
    tid = auth_client.post("/api/daily_tasks/templates", json={"text": "背成语"}).get_json()["id"]
    assert auth_client.post(f"/api/daily_tasks/{tid}/toggle").get_json()["done"] is True
    assert auth_client.get("/api/daily_tasks").get_json()["done_n"] == 1
    assert auth_client.post(f"/api/daily_tasks/{tid}/toggle").get_json()["done"] is False, "再点没取消"
    assert auth_client.get("/api/daily_tasks").get_json()["done_n"] == 0


def test_删模板连带清掉打勾记录(auth_client):
    tid = auth_client.post("/api/daily_tasks/templates", json={"text": "刷题"}).get_json()["id"]
    auth_client.post(f"/api/daily_tasks/{tid}/toggle")
    auth_client.delete(f"/api/daily_tasks/templates/{tid}")
    d = auth_client.get("/api/daily_tasks").get_json()
    assert d["total"] == 0
    con = sqlite3.connect(DB)
    left = con.execute("SELECT COUNT(*) FROM task_done WHERE tpl_id=?", (tid,)).fetchone()[0]
    con.close()
    assert left == 0, "删了模板却留着打勾记录 —— 数据残留"


def test_看不到删不掉别人的任务(auth_client):
    # 直接在库里塞一条别的用户(user_id=99999)的任务，验证本人的接口碰不到它
    con = sqlite3.connect(DB)
    con.execute("INSERT INTO task_templates(id, user_id, text) VALUES(88888, 99999, '别人的任务')")
    con.commit()
    con.close()
    # 列表里看不到
    items = auth_client.get("/api/daily_tasks").get_json()["items"]
    assert all(i["id"] != 88888 for i in items), "看到了别人的任务"
    # 删不掉（DELETE 带 AND user_id=?，删不动别人的）
    auth_client.delete("/api/daily_tasks/templates/88888")
    con = sqlite3.connect(DB)
    still = con.execute("SELECT COUNT(*) FROM task_templates WHERE id=88888").fetchone()[0]
    con.close()
    assert still == 1, "删掉了别人的任务 —— 归属隔离失效"


def test_text超长截断到120(auth_client):
    tid = auth_client.post("/api/daily_tasks/templates", json={"text": "字" * 300}).get_json()["id"]
    con = sqlite3.connect(DB)
    text = con.execute("SELECT text FROM task_templates WHERE id=?", (tid,)).fetchone()[0]
    con.close()
    assert len(text) == 120, "超长文本没截断"
