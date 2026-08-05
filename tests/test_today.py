"""/api/today：首屏仪表盘的聚合接口（集成，走真实登录态）。

这个接口的价值全在「不出错」上——它是首屏，挂了整个应用看着就是死的。所以测的重点
不是数字多漂亮，而是三件事：

  1. **空账号也得有个完整的形状**。刚注册、什么都没做的人打开应用，每个格子都该是 0
     而不是 500、也不是缺字段（前端直接读 d.done.questions，少一层就是 undefined）。

  2. **数据只算今天的、只算自己的**。做题量跨天累加或串到别人头上，首页就在骗人；
     而「今天做了多少」正是这一屏存在的理由。

  3. **一格坏了不连坐**。缺表/脏数据在这库上真发生过（接口返 HTML → 前端一律弹
     「请求失败」）。首屏必须降级成 0，不能整屏打不开。
"""
import sqlite3
from datetime import datetime

import pytest

from conftest import DB


def _db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _me(con, account):
    """登录用户的 id。**不能写 users LIMIT 1** —— 整套跑的时候别的测试会先建用户，
    LIMIT 1 抓到的是别人，做题量就插到了别人名下，单跑绿、全量红。"""
    return con.execute("SELECT id FROM users WHERE username=?", (account["username"],)).fetchone()["id"]


@pytest.fixture(autouse=True)
def _clean(auth_client):
    con = _db()
    for t in ("real_records", "drill_records", "dtest_records", "daily_quiz",
              "task_templates", "task_done", "plan_items", "plan_profile", "study_days"):
        con.execute(f"DELETE FROM {t}")
    # 「今日更新」数的是**全局**内容表，不是本账号的数据：别的测试文件往里塞了今天的
    # 素材/时政，这边就会莫名其妙多出几格。把今天的清掉，要测更新的自己插。
    today = datetime.now().strftime("%Y-%m-%d")
    con.execute("DELETE FROM sucai_items WHERE date=?", (today,))
    con.execute("DELETE FROM gaikuo_items WHERE date=?", (today,))
    con.execute("DELETE FROM changshi_items WHERE date=?", (today,))
    con.execute("DELETE FROM video_items WHERE pick_date=?", (today,))
    con.execute("DELETE FROM news_items WHERE date(created_at)=?", (today,))
    con.execute("DELETE FROM essay_models WHERE date(created_at)=?", (today,))
    con.commit()
    con.close()


def test_空账号也回完整形状而不是报错(auth_client, account):
    r = auth_client.get("/api/today")
    assert r.status_code == 200
    d = r.get_json()
    # 前端是直接 d.done.questions 这样读的，少一层就是 undefined 显示成 NaN
    assert d["done"] == {"questions": 0, "correct": 0, "minutes": 0}
    assert d["tasks"] == {"done": 0, "total": 0}
    assert d["plan"] == {"done": 0, "total": 0}
    assert d["dtest"]["has"] is False
    assert d["updates"] == []
    assert d["last"] is None
    assert d["exam"] is None
    assert d["streak"] == 0
    assert d["weekday"].startswith("周")


def test_今日做题量把真题专项练巩固测试加在一起(auth_client, account):
    d0 = auth_client.get("/api/today").get_json()["date"]
    con = _db()
    u = _me(con, account)
    con.execute("INSERT INTO real_records(user_id,mode,scope,total,correct,seconds,created_at)"
                " VALUES(?,'smart','资料分析',10,8,600,?)", (u, d0 + " 09:00:00"))
    con.execute("INSERT INTO drill_records(user_id,board,total,correct,seconds,created_at)"
                " VALUES(?,'言语理解与表达',20,14,900,?)", (u, d0 + " 20:00:00"))
    con.execute("INSERT INTO dtest_records(user_id,date,score,total) VALUES(?,?,4,5)", (u, d0))
    con.commit(); con.close()

    d = auth_client.get("/api/today").get_json()
    assert d["done"]["questions"] == 35, "10 + 20 + 5 没加齐"
    assert d["done"]["correct"] == 26
    assert d["done"]["minutes"] == 25, "秒该折成分钟（600+900=1500 秒）"


def test_只算今天的不把昨天的算进来(auth_client, account):
    con = _db()
    u = _me(con, account)
    con.execute("INSERT INTO real_records(user_id,mode,scope,total,correct,seconds,created_at)"
                " VALUES(?,'smart','昨天那套',30,30,1800,'2000-01-01 09:00:00')", (u,))
    con.commit(); con.close()
    d = auth_client.get("/api/today").get_json()
    assert d["done"]["questions"] == 0, "昨天的题算进了今天，首页在骗人"
    # 但「上次练习」该看得见它——那一格问的就是「我上回练的是什么」
    assert d["last"]["scope"] == "昨天那套"


def test_做题量不串到别人头上(auth_client, account):
    con = _db()
    u = _me(con, account)
    d0 = auth_client.get("/api/today").get_json()["date"]
    con.execute("INSERT INTO real_records(user_id,mode,scope,total,correct,seconds,created_at)"
                " VALUES(?,'smart','别人的',50,50,3000,?)", (u + 999, d0 + " 10:00:00"))
    con.commit(); con.close()
    d = auth_client.get("/api/today").get_json()
    assert d["done"]["questions"] == 0, "别人的做题量算到我头上了"
    assert d["last"] is None


def test_任务与计划各报各的完成度(auth_client, account):
    con = _db()
    u = _me(con, account)
    d0 = auth_client.get("/api/today").get_json()["date"]
    for i in range(3):
        con.execute("INSERT INTO task_templates(user_id,text,active) VALUES(?,?,1)", (u, f"任务{i}"))
    tid = con.execute("SELECT id FROM task_templates WHERE user_id=? LIMIT 1", (u,)).fetchone()["id"]
    con.execute("INSERT INTO task_done(user_id,tpl_id,date) VALUES(?,?,?)", (u, tid, d0))
    con.execute("INSERT INTO plan_items(user_id,date,seq,title,done) VALUES(?,?,1,'刷资料分析',1)", (u, d0))
    con.execute("INSERT INTO plan_items(user_id,date,seq,title,done) VALUES(?,?,2,'背成语',0)", (u, d0))
    con.commit(); con.close()
    d = auth_client.get("/api/today").get_json()
    assert d["tasks"] == {"done": 1, "total": 3}
    assert d["plan"] == {"done": 1, "total": 2}


def test_距考试天数来自备考档案(auth_client, account):
    con = _db()
    u = _me(con, account)
    con.execute("INSERT INTO plan_profile(user_id,exam,exam_date) VALUES(?,'四川省考','2099-01-01')", (u,))
    con.commit(); con.close()
    d = auth_client.get("/api/today").get_json()
    assert d["exam"]["name"] == "四川省考"
    assert d["exam"]["days_left"] > 0


def test_没设考试日期就不回这一格而不是回个假天数(auth_client, account):
    con = _db()
    u = _me(con, account)
    con.execute("INSERT INTO plan_profile(user_id,exam,exam_date) VALUES(?,'四川省考','')", (u,))
    con.commit(); con.close()
    assert auth_client.get("/api/today").get_json()["exam"] is None


def test_今日更新只回有内容的来源(auth_client, account):
    d0 = auth_client.get("/api/today").get_json()["date"]
    con = _db()
    con.execute("INSERT INTO sucai_items(date,kind,topic,content) VALUES(?,'人物','测试','内容')", (d0,))
    con.commit(); con.close()
    ups = {u["go"]: u["n"] for u in auth_client.get("/api/today").get_json()["updates"]}
    assert ups.get("sucai", 0) >= 1
    assert 0 not in ups.values(), "0 条的来源不该回，前端还得自己再过滤一遍"


def test_一张表坏了只赔那一格不打崩整个首屏(auth_client, monkeypatch):
    """这库上真出过：少一张表 → 接口 500 返 HTML → 前端一律弹「请求失败」。
    首屏必须降级，不能整屏打不开。"""
    from mods import today as todaymod
    bad = list(todaymod._UPDATES)
    bad[0] = ("news", "每日时政", "SELECT COUNT(*) FROM 根本没有这张表 WHERE date(created_at)=?")
    monkeypatch.setattr(todaymod, "_UPDATES", bad)
    r = auth_client.get("/api/today")
    assert r.status_code == 200, "一张表缺了就把首屏打成 500 了"
    assert r.get_json()["done"]["questions"] == 0


def test_巩固测试交两次成绩取最后一次而不是加起来(auth_client, account):
    """/api/dtest/grade 不拦重复提交。SUM 的话首页会写「已完成 14/20」——
    一份 10 题的测验哪来的 20 题，一眼就是假的。"""
    d0 = auth_client.get("/api/today").get_json()["date"]
    con = _db()
    u = _me(con, account)
    con.execute("INSERT INTO dtest_records(user_id,date,score,total) VALUES(?,?,6,10)", (u, d0))
    con.execute("INSERT INTO dtest_records(user_id,date,score,total) VALUES(?,?,8,10)", (u, d0))
    con.commit(); con.close()

    d = auth_client.get("/api/today").get_json()
    assert d["dtest"]["total"] == 10, "总题数被加成了 20"
    assert d["dtest"]["score"] == 8, "成绩该是最后一次那 8 分，不是两次相加"
    assert d["dtest"]["runs"] == 2
    # 做题量是另一个口径：重做一遍确实又答了 10 道，和真题/专项练一样按累计
    assert d["done"]["questions"] == 20
