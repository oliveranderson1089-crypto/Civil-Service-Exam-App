"""自选成文的「我写过的」列表。

为什么要有这一份：自选成文写出来的东西一直存在库里（mode='yingyong'），
但那一页只有一张空表单——写完看一眼、一返回就再也找不着，人只会以为白写了。
列表这个入口断了不报错、只是页面空一块，所以拿测试盯住：
① 写过的确实列得出来，spec 里的文种/场景/形态要跟着出来（列表全靠这三样区分是哪篇）；
② spec 是坏 JSON 时只丢这条的附加信息，不能连累整个列表 500。
"""
import json
import sqlite3

from conftest import DB


def _mk(spec, title="测试范文", words=300, date="2026-08-04 10:00:00"):
    con = sqlite3.connect(DB)
    con.execute("INSERT INTO daily_essays(mode,date,topic,title,content,words,spec) "
                "VALUES('yingyong',?,?,?,?,?,?)",
                (date, "通知", title, "正文", words, spec))
    con.commit()
    eid = con.execute("SELECT id FROM daily_essays WHERE date=?", (date,)).fetchone()[0]
    con.close()
    return eid


def test_mine_lists_and_deletes(auth_client):
    eid = _mk(json.dumps({"doctype": "倡议书", "scene": "垃圾分类",
                          "form": "full", "pos": "medium"}, ensure_ascii=False),
              title="关于垃圾分类的倡议书", date="2026-08-04 10:01:00")
    r = auth_client.get("/api/write/yingyong/mine")
    assert r.status_code == 200
    it = next(x for x in r.get_json()["items"] if x["id"] == eid)
    assert it["doctype"] == "倡议书" and it["scene"] == "垃圾分类"
    assert it["form"] == "full" and it["words"] == 300
    assert it["date"].startswith("2026-08-04 10:01")   # 同一天能写好几篇，得靠时间分辨

    # 删掉就不该再出现在列表里（列表上的「🗑 删掉」走的就是这个接口）
    assert auth_client.delete("/api/write/%d" % eid).status_code == 200
    assert all(x["id"] != eid for x in auth_client.get("/api/write/yingyong/mine").get_json()["items"])


def test_mine_survives_broken_spec(auth_client):
    eid = _mk("{坏掉的 JSON", title="spec 坏了的一篇", date="2026-08-04 10:02:00")
    r = auth_client.get("/api/write/yingyong/mine")
    assert r.status_code == 200, "一条 spec 坏了不能把整个列表打 500"
    it = next(x for x in r.get_json()["items"] if x["id"] == eid)
    assert it["title"] == "spec 坏了的一篇"
    assert it["doctype"] == "通知"      # spec 读不出来时退回 topic，别让这条显示成空白
    assert it["form"] == "full"
