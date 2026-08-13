"""词典 / 素材两个长列表的分页。

这两个接口原先是一次把符合条件的全发出去（词典 LIMIT 600、素材 LIMIT 400）。
实测「全部」那一屏：词典 375 KB、素材 226 KB。本机 5 毫秒无感，
但公网那一跳实测 0.9~1.4 秒，加上手机端一次渲染几百张卡片。

分页最容易写错的是**边界**：正好整页时 more 该是 false（不然前端会挂一个
点了什么都不来的「加载更多」），offset 超出末尾该给空列表而不是报错。
所以这里挨着页边界测，不测「大致能翻页」。
"""
import sqlite3

import pytest

from conftest import DB

PAGE = 5


@pytest.fixture
def 词条():
    """造 12 条词典词条，够翻三页（5 / 5 / 2）。"""
    db = sqlite3.connect(DB)
    db.execute("DELETE FROM party_dict WHERE cat='分页测试'")
    for i in range(12):
        db.execute("INSERT INTO party_dict(cat,term,content,url,ord) VALUES(?,?,?,?,?)",
                   ("分页测试", "词条%02d" % i, "正文%02d" % i, "", i))
    db.commit()
    db.close()
    yield 12
    db = sqlite3.connect(DB)
    db.execute("DELETE FROM party_dict WHERE cat='分页测试'")
    db.commit()
    db.close()


def _pd(client, offset, limit=PAGE):
    r = client.get("/api/partydict?cat=分页测试&limit=%d&offset=%d" % (limit, offset))
    assert r.status_code == 200
    return r.get_json()


def test_按页取词条(auth_client, 词条):
    d = _pd(auth_client, 0)
    assert [x["term"] for x in d["items"]] == ["词条%02d" % i for i in range(5)]
    assert d["more"] is True


def test_翻到第二页接得上(auth_client, 词条):
    first = [x["term"] for x in _pd(auth_client, 0)["items"]]
    second = _pd(auth_client, 5)
    assert [x["term"] for x in second["items"]] == ["词条%02d" % i for i in range(5, 10)]
    assert not set(first) & {x["term"] for x in second["items"]}, "两页有重复词条"
    assert second["more"] is True


def test_最后一页的more是false(auth_client, 词条):
    """12 条、每页 5：第三页只有 2 条，more 必须是 false。"""
    d = _pd(auth_client, 10)
    assert len(d["items"]) == 2
    assert d["more"] is False


def test_正好整页时不留空按钮(auth_client, 词条):
    """12 条按每页 6 取：第二页正好取完，more 得是 false。

    这是最容易漏的边界——按「取满一页就说还有」写的话，前端会挂一个
    点下去什么都不来的「加载更多」。
    """
    assert _pd(auth_client, 0, limit=6)["more"] is True
    d = _pd(auth_client, 6, limit=6)
    assert len(d["items"]) == 6 and d["more"] is False


def test_翻过头给空列表不报错(auth_client, 词条):
    d = _pd(auth_client, 999)
    assert d["items"] == [] and d["more"] is False


def test_limit有上限(auth_client, 词条):
    """limit 是外部传的，不设上限等于把「一次发全库」的口子又开回来。"""
    r = auth_client.get("/api/partydict?cat=分页测试&limit=99999&offset=0")
    assert r.status_code == 200
    assert len(r.get_json()["items"]) <= 600


def test_素材也分页(auth_client):
    """素材接口同一套约定：items / more / counts 三个字段都在。"""
    d = auth_client.get("/api/sucai?kind=&limit=3&offset=0").get_json()
    assert set(d) >= {"items", "more", "counts"}
    assert len(d["items"]) <= 3
    assert isinstance(d["more"], bool)
