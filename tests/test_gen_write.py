"""成文定时器脚本（gen_write.py）的冒烟测试 + 成文的编辑/对齐接口。

gen_write.py 是 systemd 定时器（gongkao-write.timer，每天 08:40）直接拉起的**独立脚本**，
没人 import 它 —— 和 summarize_ai.py 一个处境。那次 AI 工具重构把公共符号挪了窝，
它连崩两晚没人知道（见 test_summarize_ai.py 的教训）。所以这里**真跑**一遍：
桩掉 AI、走测试库，既拦 import 断链，也拦「函数体里才炸」的断链。

定时器现在一次跑四篇：议论文的每日成文/综合应用 + 应用文的每日成文/综合应用能力大题。
四条支路的分发只要错一条，那一篇就整天不生成，而且是静默的。
"""
import json
import sqlite3

import gen_write
import mods.align as A
from conftest import DB

_OL = ["总论点：以创新实干推动高质量发展。",
       "分论点1：创新是引领发展的第一动力。",
       "分论点2：实干是成就事业的基石。",
       "分论点3：开放是繁荣发展的必由之路。"]
_TXT = "\n".join([
    "当前形势复杂多变。以创新实干推动高质量发展。",
    "创新是引领发展的第一动力。某地靠制度创新突破了瓶颈。唯有创新方能致远。",
    "善除害者察其本，善理疾者绝其源。廖俊波扎根基层三年，使县域经济跃至全省前列。",
    "以开放拓展发展空间，靠合作积蓄共赢势能。某自贸区吸引外资连年增长。",
    "让我们以创新实干书写新篇。",
])


def _seed(mode="daily", date="2099-03-01"):
    db = sqlite3.connect(DB)
    db.execute("DELETE FROM daily_essays WHERE date=?", (date,))
    db.execute("INSERT INTO daily_essays(mode,date,topic,title,outline,content,words,used,note) "
               "VALUES(?,?,?,?,?,?,?,?,?)",
               (mode, date, "创新实干", "冒烟范文", json.dumps(_OL, ensure_ascii=False),
                _TXT, len(_TXT), "[]", ""))
    db.commit()
    eid = db.execute("SELECT id FROM daily_essays WHERE mode=? AND date=?", (mode, date)).fetchone()[0]
    db.close()
    return eid


def test_write_gen_真跑一遍(monkeypatch, flask_app):
    """_write_gen 是定时器每天 08:40 跑的**主生成路径**，之前一条测试都没有：
       test_write.py 只测 _kw_of / _used_hit 两个纯函数，整个函数体从没被执行过。
       它末尾有 align()（现在只展示不改写正文）、字数硬压、INSERT 11 列 —— 任何一处写错，
       都要等次日早上定时任务静默失败才发现（summarize_ai.py 就是这么连崩两晚的）。"""
    import mods.write as W
    date = "2099-03-09"
    db = sqlite3.connect(DB)
    db.execute("DELETE FROM daily_essays WHERE date=?", (date,))
    for kind, topic, c in (("人物事例", "创新", "廖俊波扎根基层三年，使县域经济跃至全省前列。"),
                           ("理论论据", "实干", "空谈误国，实干兴邦。"),
                           ("衔接表达", "过渡", "不仅…而且…")):
        db.execute("INSERT INTO sucai_items(date,kind,topic,content) VALUES(?,?,?,?)",
                   (date, kind, topic, c))
    db.commit()
    db.close()

    # _TXT 五段、_OL 四条，三条分论点都各有一段对应 —— 对齐只做展示、正文一字不改。
    gen = {"title": "以创新实干铸就发展新篇", "topic": "创新实干", "outline": _OL,
           "content": _TXT, "used": [1], "note": "选材说明"}

    def fake_write(_msgs, **_kw):
        return json.dumps(gen, ensure_ascii=False), None

    def boom_align(*_a, **_k):
        raise AssertionError("对齐不该调 AI：三条分论点都有对应段落，没有要补写的")

    monkeypatch.setattr(W, "_ai_call_or_error", fake_write)
    monkeypatch.setattr(A, "_ai_call_or_error", boom_align)

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    with flask_app.app_context():
        e, err = W._write_gen(con, "daily", date)
    assert err is None, err
    r = con.execute("SELECT * FROM daily_essays WHERE id=?", (e["id"],)).fetchone()
    con.close()
    # 对齐只展示、不改写：正文原样入库（提纲归提纲、全文归全文）
    assert r["content"] == _TXT, "对齐动了正文——现在应当只展示、不改写"
    assert r["words"] == len("".join(r["content"].split())), "字数没重算"
    assert json.loads(r["align"]), "对齐报告没写进 align 列"
    # 提纲原样入库（不再回改），四条齐全
    ol = json.loads(r["outline"])
    assert isinstance(ol, list) and len(ol) == 4, ol
    # 换了说法的分论点标 same（另一种写作思路），段首原样命中的是 exact
    items = {(x["kind"], x["i"]): x for x in json.loads(r["align"])}
    assert items[("sub", 0)]["state"] == "exact"
    assert items[("sub", 1)]["state"] == "same" and items[("sub", 1)]["quote"]
    # oi 是前端对号入座的依据，必须覆盖每一条提纲，且不重号
    assert sorted(x["oi"] for x in items.values()) == [0, 1, 2, 3]


def test_align_all_真跑一遍(monkeypatch, flask_app):
    """--align-all：定时器之外最容易断的一条，因为它同时碰 mods.align 和 mods.write._e_row。
       现在它专挑「有分论点在正文里没有对应段落」的存量文章，参考提纲补写那一段。"""
    # 正文只有两个论证段，提纲三条分论点 —— 分论点3（开放）在正文里没段落
    txt_miss = "\n".join([
        "开头段引材料。以创新实干推动高质量发展。",
        "创新是引领发展的第一动力。某地靠制度创新突破了瓶颈。",
        "实干是成就事业的基石。廖俊波扎根基层三年，使县域经济跃至全省前列。",
        "让我们以创新实干书写新篇。"])
    date = "2099-03-08"
    db = sqlite3.connect(DB)
    db.execute("DELETE FROM daily_essays WHERE date=?", (date,))
    db.execute("INSERT INTO daily_essays(mode,date,topic,title,outline,content,words,used,note) "
               "VALUES('daily',?,?,?,?,?,?,?,?)",
               (date, "创新实干", "冒烟范文", json.dumps(_OL, ensure_ascii=False),
                txt_miss, len(txt_miss), "[]", ""))
    db.commit()
    eid = db.execute("SELECT id FROM daily_essays WHERE date=?", (date,)).fetchone()[0]
    db.close()

    def fake(_msgs, **_kw):
        return json.dumps({"items": [
            {"i": 3, "para": "开放是繁荣发展的必由之路。某自贸区吸引外资连年增长，"
                             "区域合作释放共赢红利。"}]}, ensure_ascii=False), None
    monkeypatch.setattr(A, "_ai_call_or_error", fake)

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    gen_write.align_all(con)
    r = con.execute("SELECT content,outline,words,align FROM daily_essays WHERE id=?", (eid,)).fetchone()
    con.close()
    assert "开放是繁荣发展的必由之路" in r["content"], "缺失的分论点没补写落库"
    assert A.paras(r["content"])[-1] == "让我们以创新实干书写新篇。", "补写段应插在结尾段之前"
    assert "廖俊波" in r["content"], "已有段落被动过了"
    assert r["words"] == len("".join(r["content"].split())), "字数没跟着重算"
    assert any(x["state"] == "added" for x in json.loads(r["align"])), "对齐报告没记补写"


def test_gen_yy_分发到对的生成函数(monkeypatch):
    """应用文两条支路（每日成文 / 综合应用能力大题）走的是不同函数、不同 mode。
       分发接错了不会报错，只会整天少一篇 —— 静默失败，所以这里盯死。"""
    eid = _seed(mode="yingyong-daily", date="2099-03-02")
    called = {}

    def compose(db, date):
        called["compose"] = date
        return eid, None

    def daily(db, spec, mode=None, date=None):
        called["daily"] = (mode, date)
        return eid, None

    monkeypatch.setattr(gen_write, "_gen_yy_compose", compose)
    monkeypatch.setattr(gen_write, "_gen_yingyong", daily)
    monkeypatch.setattr(gen_write, "_pick_daily_yy", lambda db, date: {"doctype": "通知"})

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    assert gen_write.gen_yy(con, "compose", "2099-03-02") is True
    assert called["compose"] == "2099-03-02"
    assert gen_write.gen_yy(con, "daily", "2099-03-02") is True
    assert called["daily"] == ("yingyong-daily", "2099-03-02"), "每日应用文的 mode/date 传错了"
    con.close()


def test_编辑接口重算字数并摘掉失配的素材(auth_client):
    """改完正文，「用到的素材」不能还挂着正文里已经没有的条目 —— 那份清单是给人回查素材用的，
       有水分就没意义了（和 _used_hit 一个道理）。"""
    eid = _seed(date="2099-03-03")
    db = sqlite3.connect(DB)
    db.execute("UPDATE daily_essays SET used=? WHERE id=?",
               (json.dumps([{"sec": "人物事例", "text": "廖俊波扎根基层三年"},
                            {"sec": "人物事例", "text": "某位早就被删掉的人物事例"}],
                           ensure_ascii=False), eid))
    db.commit()
    db.close()

    new = _TXT.replace("以开放拓展发展空间，靠合作积蓄共赢势能。", "开放是繁荣发展的必由之路。")
    r = auth_client.put("/api/write/%d" % eid, json={
        "title": "改过的标题", "topic": "创新", "content": new,
        "outline": "\n".join(_OL), "note": "手改了一版"})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    d = r.get_json()
    assert d["title"] == "改过的标题"
    assert d["words"] == len("".join(new.split())), "字数没重算"
    assert [u["text"] for u in d["used"]] == ["廖俊波扎根基层三年"], "失配的素材没摘掉"
    # 提纲的对照位置要跟着重算（不调 AI）：分论点3 现在原样在第 4 段段首了
    sub3 = [x for x in d["align"] if x["kind"] == "sub" and x["i"] == 2][0]
    assert sub3["state"] == "exact" and sub3["para"] == 3


def test_编辑接口只改传了的字段(auth_client):
    """漏传和「显式改成空」得分开。只想改正文的调用不该把标题、话题、说明一起抹掉 ——
       应用文的 topic 存的是文种名，抹了连文种大全的分组都掉一档。"""
    eid = _seed(date="2099-03-06")
    r = auth_client.put("/api/write/%d" % eid, json={"content": _TXT})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    d = r.get_json()
    assert d["title"] == "冒烟范文" and d["topic"] == "创新实干", "没传的字段被清空了"
    # 显式传空串才算「改成空」
    d2 = auth_client.put("/api/write/%d" % eid, json={"content": _TXT, "title": ""}).get_json()
    assert d2["title"] == ""


def test_编辑接口不传提纲也要刷新段号(auth_client):
    """align 里存的是段号。正文一改段号就挪位，提纲传没传都得重算，
       否则提纲页会指着「正文第 3 段」，而那句已经跑到第 4 段去了。"""
    eid = _seed(date="2099-03-07")
    before = json.loads(sqlite3.connect(DB).execute(
        "SELECT align FROM daily_essays WHERE id=?", (eid,)).fetchone()[0] or "[]")
    assert not before          # 种子数据没写 align

    new = "新插进来的第一段。\n" + _TXT      # 每段都往后挪一位
    d = auth_client.put("/api/write/%d" % eid, json={"content": new}).get_json()
    sub1 = [x for x in d["align"] if x["kind"] == "sub" and x["i"] == 0][0]
    ps = A.paras(new)
    assert ps[sub1["para"]].startswith("创新是引领发展的第一动力"), \
        "段号没跟着正文重算，对照会指错段落"


def test_编辑接口拒绝空正文(auth_client):
    eid = _seed(date="2099-03-04")
    r = auth_client.put("/api/write/%d" % eid, json={"content": "   "})
    assert r.status_code == 400


def test_对齐接口不碰应用文(auth_client):
    """应用文的 outline 存的是逐段批注 segs，不是论点。当成提纲去对会把批注冲掉。"""
    eid = _seed(mode="yingyong-daily", date="2099-03-05")
    r = auth_client.post("/api/write/%d/align" % eid)
    assert r.status_code == 400
