"""tabhome 蓝图：「库」和「我的」两个标签页的首屏聚合（集成）。

这两个接口是**首屏**，最不该 500 的地方（这库上出过：少一张表 → 返 HTML → 前端一律弹
「请求失败」）。所以这里盯三件事：
  1) 只算自己的东西 —— 别人的小记/云盘文件不能出现在我的库里；
  2) 完成度不许注水 —— 本周没排计划就得给 pct=null，而不是 0% 或者拿别的凑一个数；
  3) 最近打开是**跨容器按时间排**的，不是先小记再云盘那种按类别排；
  4) 「最近打开」记的得是**打开**。这一条以前是错的：它读各表的 updated_at/created_at，
     云盘文件传上去时间就定死了，点一百次也不动，列表长年被小记霸榜。
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
        # 「库」新增一个容器就要往这张清单里加一项，否则「空库」那几条会被别处测试
        # 留下的数据带偏（ai_outputs 就是这么让四条测试变成看天吃饭的）
        for t in ("notes", "kb_nodes", "drafts", "materials", "drive_files",
                  "plan_items", "task_templates", "task_done", "ck_stars", "ai_outputs",
                  "lib_visits"):
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


# ---------------- /api/lib/touch ----------------

def _touch(cli, kind, ref, extra=""):
    return cli.post("/api/lib/touch", json={"kind": kind, "ref": str(ref), "extra": extra})


def test_打点过的排在最近新增前面(auth_client):
    """这一条是这套东西存在的理由。

    云盘那个文件是**一个月前**传的，小记是刚写的。按老口径（比时间戳）小记稳赢，
    可人刚刚打开的是那份 PDF —— 列表第一行就该是它。
    """
    u = _uid()
    _sql(("INSERT INTO drive_files(id,owner_id,name,is_dir,created_at) "
          "VALUES(9001,?,'讲义.pdf',0,'2026-07-01 09:00:00')", (u,)),
         ("INSERT INTO notes(user_id,content,updated_at) "
          "VALUES(?,'刚写的小记','2026-08-19 09:00:00')", (u,)))
    assert _touch(auth_client, "drive", 9001).get_json()["ok"] is True
    its = auth_client.get("/api/lib/home").get_json()["recent"]
    assert its[0]["kind"] == "drive" and its[0]["title"] == "讲义.pdf"
    assert its[0]["opened"] is True
    assert [x["kind"] for x in its[1:]] == ["note"], "垫底的最近新增没跟上来"
    assert its[1]["opened"] is False


def test_同一样东西翻十遍也只占一行(auth_client):
    u = _uid()
    _sql(("INSERT INTO drive_files(id,owner_id,name,is_dir) VALUES(9002,?,'真题.pdf',0)", (u,)),)
    for _ in range(10):
        _touch(auth_client, "drive", 9002)
    its = auth_client.get("/api/lib/home").get_json()["recent"]
    assert len(its) == 1, "同一份文件把整张列表刷成了十行一样的东西"


def test_云盘文件夹进得来(auth_client):
    """老口径写死 is_dir=0，文件夹**永远**不可能出现在列表里 —— 而人天天点的就是文件夹。"""
    u = _uid()
    _sql(("INSERT INTO drive_files(owner_id,folder,name,is_dir) "
          "VALUES(?,'','内江资中县社区备考资料',1)", (u,)),
         ("INSERT INTO drive_files(owner_id,folder,name,is_dir) "
          "VALUES(?,'内江资中县社区备考资料','5.社会实务（初级）',1)", (u,)))
    _touch(auth_client, "drivedir", "内江资中县社区备考资料/5.社会实务（初级）")
    its = auth_client.get("/api/lib/home").get_json()["recent"]
    assert its[0]["kind"] == "drivedir"
    assert its[0]["title"] == "5.社会实务（初级）", "标题该是文件夹名，不是整条路径"
    assert its[0]["id"] == "内江资中县社区备考资料/5.社会实务（初级）"


def test_根目录下的文件夹路径不带前导斜杠(auth_client):
    u = _uid()
    _sql(("INSERT INTO drive_files(owner_id,folder,name,is_dir) VALUES(?,'','安装包',1)", (u,)))
    _touch(auth_client, "drivedir", "安装包")
    assert auth_client.get("/api/lib/home").get_json()["recent"][0]["title"] == "安装包"


def test_删掉的东西不再出现(auth_client):
    """标题是现查的，不是打点时存的快照 —— 所以删了就该从列表里消失，改名就该跟着变。"""
    u = _uid()
    _sql(("INSERT INTO drive_files(id,owner_id,name,is_dir) VALUES(9003,?,'待删.pdf',0)", (u,)))
    _touch(auth_client, "drive", 9003)
    assert len(auth_client.get("/api/lib/home").get_json()["recent"]) == 1
    _sql(("UPDATE drive_files SET deleted_at='2026-08-19 10:00:00' WHERE id=9003", ()))
    assert auth_client.get("/api/lib/home").get_json()["recent"] == [], \
        "进了回收站的文件还挂在「最近打开」里，点下去是个空壳"


def test_改名之后标题跟着变(auth_client):
    u = _uid()
    _sql(("INSERT INTO drive_files(id,owner_id,name,is_dir) VALUES(9004,?,'旧名字.pdf',0)", (u,)))
    _touch(auth_client, "drive", 9004)
    _sql(("UPDATE drive_files SET name='新名字.pdf' WHERE id=9004", ()))
    assert auth_client.get("/api/lib/home").get_json()["recent"][0]["title"] == "新名字.pdf"


def test_打不到别人的东西上(auth_client):
    _sql(("INSERT INTO drive_files(id,owner_id,name,is_dir) VALUES(9005,99999,'别人的.pdf',0)", ()))
    _touch(auth_client, "drive", 9005)
    assert auth_client.get("/api/lib/home").get_json()["recent"] == [], \
        "打点表按人存，但标题是从公共查询里捞的 —— 串到别人的文件了"


def test_云盘文件记着它在哪一层(auth_client):
    """extra 是给「点回去」用的：没有它，从最近打开点一份三层深的文件会落到云盘根目录。"""
    u = _uid()
    _sql(("INSERT INTO drive_files(id,owner_id,folder,name,is_dir) "
          "VALUES(9006,?,'内江资中县社区备考资料/5.社会实务（初级）','四色笔记.pdf',0)", (u,)))
    _touch(auth_client, "drive", 9006, "内江资中县社区备考资料/5.社会实务（初级）")
    assert auth_client.get("/api/lib/home").get_json()["recent"][0]["extra"] \
        == "内江资中县社区备考资料/5.社会实务（初级）"


def test_空的extra不许覆盖已有的(auth_client):
    """有的入口拿不到所在目录。它不该把上一次记好的抹成空。"""
    u = _uid()
    _sql(("INSERT INTO drive_files(id,owner_id,folder,name,is_dir) "
          "VALUES(9007,?,'讲义','真题.pdf',0)", (u,)))
    _touch(auth_client, "drive", 9007, "讲义")
    _touch(auth_client, "drive", 9007, "")
    assert auth_client.get("/api/lib/home").get_json()["recent"][0]["extra"] == "讲义"


def test_打点接口不认的东西也不许报错(auth_client):
    """调它的地方下一句就是「打开这篇文档」。为一次记录失败让前端弹红条完全不成比例。"""
    for body in ({"kind": "不存在的类型", "ref": "1"}, {"kind": "drive", "ref": ""},
                 {}, {"kind": "drive"}):
        r = auth_client.post("/api/lib/touch", json=body)
        assert r.status_code == 200, "打点失败返了 %d，前端 api() 见非 2xx 就抛" % r.status_code
        assert r.get_json()["ok"] is False


def test_打点表空着就回落到最近新增(auth_client):
    """升级那天所有人的 lib_visits 都是空的。只读打点表的话，
    老用户升完级看到的是「库里还没有东西」—— 比原来那份不准的列表更糟。"""
    u = _uid()
    _sql(("INSERT INTO notes(user_id,content) VALUES(?,'一条小记')", (u,)))
    its = auth_client.get("/api/lib/home").get_json()["recent"]
    assert [x["title"] for x in its] == ["一条小记"]
    assert its[0]["opened"] is False, "没打开过却标成打开过了"


def test_垫底的不许和打点过的重复(auth_client):
    u = _uid()
    _sql(("INSERT INTO notes(id,user_id,content) VALUES(9008,?,'同一条小记')", (u,)))
    _touch(auth_client, "note", 9008)
    its = auth_client.get("/api/lib/home").get_json()["recent"]
    assert len(its) == 1, "同一条小记既算打开过、又被最近新增垫了一遍"


def test_收藏那格的东西也进得来(auth_client):
    """时评/时政/古诗文躺在公共表里（没有 user_id），分人的是打点记录本身。"""
    _sql(("INSERT INTO news_items(id,title,source) VALUES(9009,'今日时政要闻','人民日报')", ()))
    _touch(auth_client, "news", 9009)
    it = auth_client.get("/api/lib/home").get_json()["recent"][0]
    assert (it["kind"], it["label"], it["title"]) == ("news", "时政", "今日时政要闻")
