"""每日古诗文（warm_classic_daily.py）的冒烟测试。

两件事要盯：

一是**接口不许再调 AI**。这两行注解原先是在 /api/classics/daily 里现场生成的，
一次实测 3687 毫秒，而它挂着首屏「今日」卡片——等于每天第一个打开 App 的人
白等 3.7 秒（之后全天 11 毫秒，因为落了库，所以平时自测根本发现不了）。
现在改成接口只读库、注解由定时器提前备好。这里桩一个「一旦被调用就炸」的 AI，
把这条不变量钉死：谁要是哪天又把 AI 塞回请求路径，这个用例立刻红。

二是 warm_classic_daily.py 跟 summarize_ai.py 一样是 systemd 直接拉起的独立脚本，
没人 import 它，公共符号搬家不会有任何编译期报错（见 test_summarize_ai.py 开头
那段踩坑记录）。所以这里真跑一遍它的 main()，import 断链和「函数体里才炸」都能拦住。
"""
import sqlite3
import sys

import pytest

import warm_classic_daily
from conftest import DB
from mods import classics as C

TEST_DAY = "2099-03-04"          # 远期日期，绝不撞真实数据 / 别的用例
FAKE_JSON = '{"apply":"适合写「坚守」类主题","common":"作者是唐代人，考朝代归属"}'


@pytest.fixture
def a_poem():
    """造一首 freq 够高的诗，让 pick_daily 一定选得到它。"""
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO classics(title,author,dynasty,category,content,freq) "
               "VALUES(?,?,?,?,?,?)",
               ("冒烟诗", "测试作者", "唐代", "唐诗", "第一句\n第二句", 100))
    cid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute("DELETE FROM classic_daily WHERE date=?", (TEST_DAY,))
    db.commit()
    db.close()
    yield cid
    db = sqlite3.connect(DB)
    db.execute("DELETE FROM classic_daily WHERE date=?", (TEST_DAY,))
    db.execute("DELETE FROM classics WHERE id=?", (cid,))
    db.commit()
    db.close()


def _conn():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def test_接口不调AI(auth_client, monkeypatch):
    """首屏那条接口只读库。AI 一旦被调用就当场炸。"""
    def 别调我(*a, **k):
        raise AssertionError("/api/classics/daily 又在请求里调 AI 了——"
                             "注解该由 warm_classic_daily.py 提前备好")
    monkeypatch.setattr(C, "_ai_call_or_error", 别调我)
    r = auth_client.get("/api/classics/daily")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        d = r.get_json()
        # 注解可以是空的（还没预热），但绝不能因此变成错误
        assert "apply" in d and "common" in d


def test_没预热也照样能读诗(auth_client, monkeypatch, a_poem):
    """注解缺席不算故障：诗本身要照常返回，前端那两行只是不显示。"""
    monkeypatch.setattr(C, "_ai_call_or_error",
                        lambda *a, **k: pytest.fail("不该调 AI"))
    con = _conn()
    row = C.pick_daily(con, TEST_DAY)
    con.close()
    assert row["title"] == "冒烟诗"
    assert not (row["apply"] or "")          # 没预热，注解就是空的


def test_预热脚本真跑一遍(monkeypatch, a_poem):
    """走 main()，不是只 import ——「函数体里才炸」的断链只有真跑才拦得住。"""
    calls = []

    def 假AI(messages, **kw):
        calls.append(messages)
        return FAKE_JSON, None
    monkeypatch.setattr(C, "_ai_call_or_error", 假AI)
    monkeypatch.setattr(C, "ai_configured", lambda: True)
    monkeypatch.setattr(warm_classic_daily, "DB", DB)
    monkeypatch.setattr(sys, "argv", ["warm_classic_daily.py", "--days", "1"])

    # 脚本按「今天」算日期，这里把它挪到远期测试日，免得动到真实数据
    import datetime as _dt

    class 假date(_dt.date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(TEST_DAY)
    monkeypatch.setattr(warm_classic_daily, "date", 假date)

    assert warm_classic_daily.main() == 0
    assert len(calls) == 1, "应当只为这一天调一次 AI"

    con = _conn()
    row = C.pick_daily(con, TEST_DAY)
    con.close()
    assert row["apply"] == "适合写「坚守」类主题"
    assert row["common"] == "作者是唐代人，考朝代归属"


def test_预热过就不再重复烧钱(monkeypatch, a_poem):
    """已有注解的日子直接跳过——定时器每天跑，不能每天都重生成一遍。"""
    con = _conn()
    row = C.pick_daily(con, TEST_DAY)
    con.execute("UPDATE classic_daily SET apply='已有', common='已有' WHERE date=?", (TEST_DAY,))
    con.commit()
    row = C.pick_daily(con, TEST_DAY)

    monkeypatch.setattr(C, "_ai_call_or_error",
                        lambda *a, **k: pytest.fail("已有注解还去调 AI"))
    good, msg = C.fill_daily_note(con, row, TEST_DAY)
    con.close()
    assert good and msg == "已有"


def test_同一天选中的诗是固定的(a_poem):
    """按日期确定性挑选：谁先访问、访问几次，选中的都得是同一首。"""
    con = _conn()
    first = C.pick_daily(con, TEST_DAY)["classic_id"]
    assert all(C.pick_daily(con, TEST_DAY)["classic_id"] == first for _ in range(3))
    con.close()
