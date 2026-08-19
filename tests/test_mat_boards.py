"""资料库分类顺序：/api/materials/boards 的 items。

分类栏外面只摆得下几个，摆哪几个全看这个接口给的顺序 —— 排序放在服务端就是为了
前后端不各排一次（小记同理，见 mods/notes.py）。这里钉住三件事：
用得多的在前、一样多看最近传的、一份都没有的沉底但仍在册（上传时要能选）。
"""
import io

import pytest


def _up(c, board, name="a.txt"):
    r = c.post("/api/materials", data={
        "file": (io.BytesIO(b"x"), name), "board": board, "section": "", "title": "",
    }, content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    return r.get_json()["id"]


@pytest.fixture
def boarded(auth_client):
    """甲 3 份、乙 1 份、丙 1 份（丙比乙晚传）。"""
    for i in range(3):
        _up(auth_client, "甲", f"a{i}.txt")
    _up(auth_client, "乙")
    _up(auth_client, "丙")
    return auth_client


def _items(c):
    r = c.get("/api/materials/boards")
    assert r.status_code == 200
    return r.get_json()["items"]


def test_用得多的排前面(boarded):
    order = [x["board"] for x in _items(boarded)]
    assert order[0] == "甲", f"份数最多的没排第一：{order[:3]}"
    assert order.index("乙") < order.index("资料分析"), "有资料的该排在空板块前面"


def test_份数一样就看最近传的(boarded):
    order = [x["board"] for x in _items(boarded)]
    # 乙丙都是 1 份，丙传得晚 —— 手头正在攒的那个要浮上来，
    # 否则并列的一堆会退化成建库顺序（最老的排最前，正好最没用）
    assert order.index("丙") < order.index("乙"), f"并列时没按最近排：{order}"


def test_空板块在册但份数为0(boarded):
    items = {x["board"]: x for x in _items(boarded)}
    assert "数量关系" in items, "固定板块掉了，上传时就选不到它"
    assert items["数量关系"]["n"] == 0
    assert items["甲"]["n"] >= 3   # 同一个库跨用例累积，只看下界


def test_自建分类标了custom(boarded):
    items = {x["board"]: x for x in _items(boarded)}
    assert items["甲"]["custom"] is True, "自建分类没标出来，前端就不知道哪个能删"
    assert items["议论文"]["custom"] is False


def test_新建的空分类不会丢(auth_client):
    """建了但还没往里传东西的分类，重启也得在 —— 这是踩过的坑。"""
    auth_client.post("/api/materials/boards", json={"boards": ["晨读"]})
    items = {x["board"]: x for x in _items(auth_client)}
    assert "晨读" in items and items["晨读"]["n"] == 0


def test_boards字段还在(boarded):
    """老前端（装了旧 APK 的手机）只认 boards，不能把它掐了。"""
    d = boarded.get("/api/materials/boards").get_json()
    assert d["boards"] == [x["board"] for x in d["items"]]
