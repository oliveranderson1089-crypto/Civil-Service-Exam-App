"""tabhome 蓝图：「库」和「我的」两个标签页的首屏聚合（集成）。

这两个接口是**首屏**，最不该 500 的地方（这库上出过：少一张表 → 返 HTML → 前端一律弹
「请求失败」）。所以这里盯三件事：
  1) 只算自己的东西 —— 别人的小记/云盘文件不能出现在我的库里；
  2) 完成度不许注水 —— 本周没排计划就得给 pct=null，而不是 0% 或者拿别的凑一个数；
  3) 最近打开是**跨容器按时间排**的，不是先小记再云盘那种按类别排。
"""
import sqlite3

import pytest

from conftest import DB


def _uid():
    con = sqlite3.connect(DB, timeout=10)
    try:
        return con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    finally:
        con.close()


def _sql(*stmts):
    con = sqlite3.connect(DB, timeout=10)
    try:
        for s, args in stmts:
            con.execute(s, args)
        con.commit()
    finally:
        con.close()


@pytest.fixture(autouse=True)
def _clean(auth_client):
    con = sqlite3.connect(DB, timeout=10)
    try:
        for t in ("notes", "kb_nodes", "drafts", "materials", "drive_files",
                  "plan_items", "task_templates", "task_done", "ck_stars"):
            con.execute("DELETE FROM %s" % t)
        con.commit()
    finally:
        con.close()


# ---------------- /api/lib/home ----------------

def test_空库也给完整结构不报错(auth_client):
    d = auth_client.get("/api/lib/home").get_json()
    assert d["recent"] == []
    assert d["counts"]["note"] == 0 and d["counts"]["drive"] == 0


def test_各容器分别计数(auth_client):
    u = _uid()
    _sql(("INSERT INTO notes(user_id,content) VALUES(?,'今天背了三个成语')", (u,)),
         ("INSERT INTO drafts(user_id,title,data_json) VALUES(?,'演算 1','{}')", (u,)),
         ("INSERT INTO drive_files(owner_id,name,is_dir) VALUES(?,'讲义.pdf',0)", (u,)),
         ("INSERT INTO drive_files(owner_id,name,is_dir) VALUES(?,'资料夹',1)", (u,)))
    c = auth_client.get("/api/lib/home").get_json()["counts"]
    assert c["note"] == 1 and c["draft"] == 1
    assert c["drive"] == 1, "文件夹被当成文件数进去了"


def test_只数自己的(auth_client):
    _sql(("INSERT INTO notes(user_id,content) VALUES(99999,'别人的小记')", ()),
         ("INSERT INTO drive_files(owner_id,name,is_dir) VALUES(99999,'别人的文件',0)", ()))
    d = auth_client.get("/api/lib/home").get_json()
    assert d["counts"]["note"] == 0 and d["counts"]["drive"] == 0
    assert d["recent"] == [], "别人的东西出现在我的「最近打开」里"


def test_回收站里的云盘文件不算(auth_client):
    u = _uid()
    _sql(("INSERT INTO drive_files(owner_id,name,is_dir,deleted_at) "
          "VALUES(?,'删掉的.pdf',0,'2026-08-01 10:00:00')", (u,)))
    assert auth_client.get("/api/lib/home").get_json()["counts"]["drive"] == 0


def test_最近打开跨容器按时间倒序(auth_client):
    u = _uid()
    _sql(("INSERT INTO notes(user_id,content,updated_at) VALUES(?,'旧小记','2026-08-01 09:00:00')", (u,)),
         ("INSERT INTO drafts(user_id,title,data_json,updated_at) "
          "VALUES(?,'新草稿','{}','2026-08-03 09:00:00')", (u,)),
         ("INSERT INTO kb_nodes(user_id,notebook_id,type,title,updated_at) "
          "VALUES(?,1,'doc','中间那篇文档','2026-08-02 09:00:00')", (u,)))
    its = auth_client.get("/api/lib/home").get_json()["recent"]
    assert [x["title"] for x in its] == ["新草稿", "中间那篇文档", "旧小记"]
    assert [x["kind"] for x in its] == ["draft", "kbdoc", "note"]


def test_小记拿正文首行当标题(auth_client):
    u = _uid()
    _sql(("INSERT INTO notes(user_id,content) VALUES(?,'第一行要点\n第二行完全是另一件事')", (u,)))
    it = auth_client.get("/api/lib/home").get_json()["recent"][0]
    assert it["title"] == "第一行要点", "把第二行也拼进标题了，读起来不通"


def test_只贴图没写字的小记给图片小记(auth_client):
    u = _uid()
    _sql(("INSERT INTO notes(user_id,content,images) VALUES(?,'','[\"a.jpg\"]')", (u,)))
    assert auth_client.get("/api/lib/home").get_json()["recent"][0]["title"] == "图片小记"


def test_知识库只要文档不要分组(auth_client):
    u = _uid()
    _sql(("INSERT INTO kb_nodes(user_id,notebook_id,type,title) VALUES(?,1,'group','一个分组')", (u,)),
         ("INSERT INTO kb_nodes(user_id,notebook_id,type,title) VALUES(?,1,'doc','一篇文档')", (u,)))
    d = auth_client.get("/api/lib/home").get_json()
    assert d["counts"]["kb"] == 1
    assert [x["title"] for x in d["recent"]] == ["一篇文档"]


# ---------------- /api/lib/stars ----------------

def test_收藏并成一张单子(auth_client):
    u = _uid()
    _sql(("INSERT INTO ck_stars(user_id,board,item_id,title,created_at) "
          "VALUES(?,'上位词',1,'统筹兼顾','2026-08-02 10:00:00')", (u,)),
         ("INSERT INTO ck_stars(user_id,board,item_id,title,created_at) "
          "VALUES(99999,'上位词',2,'别人收藏的','2026-08-03 10:00:00')", ()))
    its = auth_client.get("/api/lib/stars").get_json()["items"]
    assert [x["title"] for x in its] == ["统筹兼顾"], "串到别人的收藏了"
    assert its[0]["kind"] == "ck" and its[0]["ref"] == "上位词"


# ---------------- /api/me/home ----------------

def test_本周没排计划就不给完成度(auth_client):
    d = auth_client.get("/api/me/home").get_json()
    assert d["week"]["pct"] is None, "没有计划却给了个完成度，等于每周发一张假成绩单"
    assert d["week"]["total"] == 0


def test_本周计划完成度按条算(auth_client):
    u = _uid()
    d0 = auth_client.get("/api/me/home").get_json()["week"]["from"]
    _sql(("INSERT INTO plan_items(user_id,date,title,done) VALUES(?,?,'练言语',1)", (u, d0)),
         ("INSERT INTO plan_items(user_id,date,title,done) VALUES(?,?,'背成语',1)", (u, d0)),
         ("INSERT INTO plan_items(user_id,date,title,done) VALUES(?,?,'写申论',0)", (u, d0)))
    w = auth_client.get("/api/me/home").get_json()["week"]
    assert (w["done"], w["total"], w["pct"]) == (2, 3, 67)


def test_上周的计划不算进本周(auth_client):
    u = _uid()
    _sql(("INSERT INTO plan_items(user_id,date,title,done) VALUES(?,'2020-01-01','很久以前',1)", (u,)))
    assert auth_client.get("/api/me/home").get_json()["week"]["pct"] is None


def test_任务清单给的是今天的进度(auth_client):
    u = _uid()
    _sql(("INSERT INTO task_templates(id,user_id,text,active) VALUES(70001,?,'早读',1)", (u,)),
         ("INSERT INTO task_templates(id,user_id,text,active) VALUES(70002,?,'刷题',1)", (u,)))
    t = auth_client.get("/api/me/home").get_json()["tasks"]
    assert (t["done"], t["total"]) == (0, 2)
