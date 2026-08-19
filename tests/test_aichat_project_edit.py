"""项目的自定义指令要改得动。

原先只有「建」和「删」：指令在新建那一刻问过一次，之后没有任何改法 —— 想调一句话
只能删了重建，而删项目会把底下所有对话解绑。
"""
import sqlite3

import pytest

from conftest import DB
from mods import aisession


@pytest.fixture
def proj(auth_client):
    pid = auth_client.post("/api/aichat/projects",
                           json={"name": "申论批改", "instructions": "按采分点打分"}).get_json()["id"]
    return auth_client, pid


@pytest.fixture
def fake_ai(monkeypatch):
    seen = {}
    monkeypatch.setattr(aisession, "_ai_agentic_or_error",
                        lambda messages, db, **kw: (seen.update(msgs=messages), ("好的。", [], [], None))[1])
    return seen


def test_改指令并且下一轮就生效(proj, fake_ai):
    c, pid = proj
    r = c.put("/api/aichat/projects/%d" % pid, json={"instructions": "先给分，再说扣在哪"})
    assert r.status_code == 200
    assert r.get_json()["instructions"] == "先给分，再说扣在哪"

    cid = c.post("/api/aichat/chats", json={"project_id": pid}).get_json()["id"]
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "批一下"})
    sys_prompt = fake_ai["msgs"][0]["content"]
    assert "先给分，再说扣在哪" in sys_prompt, "改完指令没进系统提示词，等于没改"
    assert "按采分点打分" not in sys_prompt, "旧指令还在，说明是叠加不是替换"


def test_指令可以清空(proj):
    c, pid = proj
    assert c.put("/api/aichat/projects/%d" % pid, json={"instructions": ""}).get_json()["instructions"] == ""


def test_改名不动指令改指令不动名字(proj):
    c, pid = proj
    d = c.put("/api/aichat/projects/%d" % pid, json={"name": "申论精批"}).get_json()
    assert d["name"] == "申论精批"
    assert d["instructions"] == "按采分点打分", "只传了 name 却把指令冲掉了"


def test_名字不许改成空(proj):
    c, pid = proj
    assert c.put("/api/aichat/projects/%d" % pid, json={"name": "   "}).status_code == 400
    assert c.put("/api/aichat/projects/%d" % pid, json={"name": ""}).status_code == 400


def test_改不了别人的项目(proj, flask_app, account):
    c, pid = proj
    other = flask_app.test_client()          # 没登录
    assert other.put("/api/aichat/projects/%d" % pid, json={"name": "偷改"}).status_code in (401, 302, 404)
    con = sqlite3.connect(DB, timeout=10)
    name = con.execute("SELECT name FROM ai_projects WHERE id=?", (pid,)).fetchone()[0]
    con.close()
    assert name == "申论批改"


def test_项目不存在时给404(auth_client):
    assert auth_client.put("/api/aichat/projects/999999", json={"name": "x"}).status_code == 404
