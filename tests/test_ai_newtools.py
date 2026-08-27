"""2026-08 新加的那批工具。

重点不在「能不能查到」，而在两条红线：
  · 真题库是这个应用最硬的资产，AI 以前完全够不着 —— 够不着它就只能凭印象编题。
  · 联网这条：搜不到 ≠ 连不上，而且**任何一种失败都不许退回「拿训练记忆冒充搜索结果」**。
"""
import sqlite3

import pytest

import mods.agent  # noqa: F401  写工具在这里注册
from conftest import DB
from mods import websearch
from mods.agent_tools import exec_tool


@pytest.fixture
def ctx(auth_client):
    import app as appmod
    from core import get_db
    con = sqlite3.connect(DB, timeout=10)
    uid = con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    con.close()
    with appmod.app.test_request_context():
        from flask import session
        session["user_id"] = uid
        yield get_db()


# ---------------- 真题库 ----------------

@pytest.fixture
def real_q(ctx):
    ctx.execute("INSERT INTO real_questions(module,qtype,stem,options,answer,year_max,needs_asset) "
                "VALUES('言语理解与表达','逻辑填空','他做事一向~，从不拖延','A 雷厉风行 B 优柔寡断','A',2024,0)")
    ctx.execute("INSERT INTO real_questions(module,qtype,stem,options,answer,year_max,needs_asset) "
                "VALUES('资料分析','增长率','根据下图，增长率为~','A 5% B 8%','B',2023,1)")
    ctx.commit()
    return ctx


def test_按模块和关键词翻真题(real_q):
    msg, _ = exec_tool("search_real_questions",
                       {"keyword": "拖延", "module": "言语理解与表达"}, real_q)
    assert "雷厉风行" in msg and "逻辑填空" in msg


def test_要图要材料的题不发给纯文字对话(real_q):
    """needs_asset=1 的题脱离图/材料就是残的，发出去用户根本没法做。"""
    msg, _ = exec_tool("search_real_questions", {"module": "资料分析"}, real_q)
    assert "根据下图" not in msg


def test_真题没找到就直说不编题(real_q):
    msg, _ = exec_tool("search_real_questions", {"keyword": "量子纠缠"}, real_q)
    assert "没找到" in msg


# ---------------- 讲义知识点 ----------------

def test_标题没命中就翻正文(ctx):
    cur = ctx.execute("INSERT INTO basic_nodes(source_id,source,board,title,nkey) "
                      "VALUES(1,'优路','数量关系','工程问题','gcwt')")
    nid = cur.lastrowid
    ctx.execute("INSERT INTO basic_blocks(node_id,sort,kind,content_md) VALUES(?,0,'skill',?)",
                (nid, "赋值法：把总量设成工作时间的最小公倍数"))
    ctx.commit()
    assert "赋值法" in exec_tool("search_basics", {"keyword": "工程问题"}, ctx)[0]
    # 书里的说法和用户嘴里的考点名常常对不上，所以标题没命中要接着翻正文
    assert "工程问题" in exec_tool("search_basics", {"keyword": "赋值法"}, ctx)[0]


# ---------------- 倒计时 ----------------

def test_没填考试日期就说没填别硬算(ctx):
    ctx.execute("DELETE FROM plan_profile WHERE user_id=(SELECT id FROM users WHERE username='tester')")
    ctx.commit()
    msg, _ = exec_tool("get_exam_countdown", {}, ctx)
    assert "还没" in msg and "填" in msg


def test_填了就算得出天数(ctx):
    from datetime import date, timedelta
    d = (date.today() + timedelta(days=30)).isoformat()
    uid = ctx.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    ctx.execute("INSERT OR REPLACE INTO plan_profile(user_id,exam,exam_date) VALUES(?,?,?)",
                (uid, "四川省考", d))
    ctx.commit()
    assert "30 天" in exec_tool("get_exam_countdown", {}, ctx)[0]


def test_日期写歪了不炸(ctx):
    uid = ctx.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    ctx.execute("INSERT OR REPLACE INTO plan_profile(user_id,exam,exam_date) VALUES(?,?,?)",
                (uid, "省考", "下个月吧"))
    ctx.commit()
    msg, _ = exec_tool("get_exam_countdown", {}, ctx)
    assert "看不懂" in msg


# ---------------- 联网 ----------------

def test_搜到了就把标题和链接给模型(ctx, monkeypatch):
    monkeypatch.setattr(websearch, "search",
                        lambda q, n=5: [{"title": "2026国考公告", "url": "https://x/y",
                                         "snippet": "10 月 15 日起报名", "age": ""}])
    msg, _ = exec_tool("web_search", {"query": "2026 国考公告"}, ctx)
    assert "2026国考公告" in msg and "https://x/y" in msg


def test_连不上要说连不上并且明令不许拿印象顶替(ctx, monkeypatch):
    def boom(q, n=5):
        raise websearch.SearchError("连不上搜索服务（代理挂了）")
    monkeypatch.setattr(websearch, "search", boom)
    msg, _ = exec_tool("web_search", {"query": "国考公告"}, ctx)
    assert "没能去搜" in msg
    assert "不要用你自己的印象代替搜索结果" in msg, \
        "不把这句话摆给模型，它会自信地拿两年前的记忆当搜索结果答"


def test_搜了但没有结果和连不上是两回事(ctx, monkeypatch):
    monkeypatch.setattr(websearch, "search", lambda q, n=5: [])
    msg, _ = exec_tool("web_search", {"query": "abcdefg"}, ctx)
    assert "一条结果也没有" in msg
    assert "没能去搜" not in msg, "「网上没有」和「我去不了」不能混为一谈"


def test_没配key时说清是没配(monkeypatch):
    monkeypatch.setattr(websearch, "CFG", {})
    with pytest.raises(websearch.SearchError) as e:
        websearch.search("x")
    assert "key" in str(e.value)


def test_读网页会剥标签并在截断时留痕(ctx, monkeypatch):
    long_body = "正文内容" * 20
    monkeypatch.setattr(websearch, "fetch", lambda u: ("某公告", long_body, True))
    msg, _ = exec_tool("web_fetch", {"url": "https://x/y"}, ctx)
    assert "某公告" in msg and "只是开头一部分" in msg


def test_剥标签是真的能用(monkeypatch):
    html = ("<html><head><title>测试页</title></head><body><script>var a=1</script>"
            "<p>第一段</p><p>第二段&amp;结尾</p></body></html>")

    class R:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def read(self, n=None):
            return html.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    # 打在 `_DIRECT.open` 上，不是 `urllib.request.urlopen`：搜索这一路现在自己建
    # opener（服务单元的 `NO_PROXY=*` 会让 urlopen 那条把显式代理静默绕过，
    # 见 tests/test_websearch_proxy.py）。打错地方的话，这里会去真的连外网。
    monkeypatch.setattr(websearch._DIRECT, "open", lambda req, timeout=None: R())
    title, body, cut = websearch.fetch("https://example.com")
    assert title == "测试页"
    assert "第一段" in body and "第二段&结尾" in body
    assert "var a=1" not in body, "script 里的东西不该当正文喂给模型"
    assert cut is False
