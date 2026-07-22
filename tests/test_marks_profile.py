"""划重点的「模块画像」：每个模块划哪几类考点。

两件容易悄悄坏掉的事：
1. 议论文（范文/成文/范文精读）必须把**总论点和分论点分开**。混成一类的时候，
   AI 会把统摄全文的那句也标成「分论点」，学范文最该学的结构就丢了。
2. 结果是按「内容哈希」缓存的 —— 画像改了、内容没变，key 不变就还发旧结果，
   改了等于没改。所以 key 里必须掺画像指纹。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mods import marks  # noqa: E402

ESSAY_SCOPES = ["essayd", "writed", "fanwend"]


@pytest.mark.parametrize("scope", ESSAY_SCOPES)
def test_议论文画像里总论点和分论点是两类(scope):
    name, kinds, focus = marks.mk_profile(scope)
    ks = [k for k, _ in kinds]
    assert "总论点" in ks, f"{scope}（{name}）没有「总论点」，总论点会被标成分论点"
    assert "分论点" in ks, f"{scope}（{name}）连分论点都没了"
    assert ks.index("总论点") < ks.index("分论点"), "总论点该排在分论点前面（颜色和阅读顺序都按它）"
    assert "总论点" in focus and "分论点" in focus, "focus 里没交代两者怎么分，AI 照样会混"


@pytest.mark.parametrize("scope", ESSAY_SCOPES)
def test_议论文画像类型数不超过前端配色数(scope):
    # 前端 MK_COLORS 只有 5 个颜色，第 6 类会和第 1 类撞色 —— 撞了就分不清哪句是哪类
    _, kinds, _ = marks.mk_profile(scope)
    assert len(kinds) <= 5, f"{scope} 有 {len(kinds)} 类，超过前端 MK_COLORS 的 5 个颜色"


def test_范文精读不再落到通用兜底():
    name, kinds, _ = marks.mk_profile("fanwend")
    assert (name, kinds) != (marks._MK_FALLBACK[0], marks._MK_FALLBACK[1]), \
        "范文精读用了通用兜底画像（提法/数据/结论/金句），跟议论文不沾边"


def test_画像变了缓存指纹就变():
    sig = marks.mk_profile_sig("writed")
    old = marks.MK_PROFILES["writed"]
    try:
        marks.MK_PROFILES["writed"] = (old[0], old[1] + [("新类型", "随便加的")], old[2])
        assert marks.mk_profile_sig("writed") != sig, \
            "画像改了指纹没变 —— 已经划过的文章会一直返回按旧类型划的缓存"
    finally:
        marks.MK_PROFILES["writed"] = old
    assert marks.mk_profile_sig("writed") == sig, "复原后指纹该回到原值（指纹不能带随机性）"


def test_不同模块指纹不同():
    assert marks.mk_profile_sig("writed") != marks.mk_profile_sig("csboard")


def test_范文精读的类型清单是独立一份():
    # 直接引用同一个 list 的话，谁原地改一下「范文」，「范文精读」会跟着无声变掉
    assert marks.MK_PROFILES["fanwend"][1] is not marks.MK_PROFILES["essayd"][1]


# ---- 缓存：画像改了要作废，但**同一篇文章始终只占一行** ----
TEXT = "议论文正文。" * 30


def _cache_rows(client):
    from core import get_db
    with client.application.app_context():
        return get_db().execute("SELECT ref,data_json FROM marks_cache WHERE scope='writed'").fetchall()


def test_画像改了旧缓存作废且不留垃圾行(auth_client, monkeypatch):
    calls = []

    def fake(content, scope=""):
        calls.append(scope)
        return [{"quote": "议论文正文。", "kind": "总论点", "why": "第 %d 次" % len(calls)}], ""

    monkeypatch.setattr(marks, "_mark_text", fake)
    post = lambda: auth_client.post("/api/marks", json={"text": TEXT, "scope": "writed"})  # noqa: E731

    assert post().get_json()["marks"][0]["why"] == "第 1 次"
    assert post().get_json()["cached"] is True, "第二次没走缓存 —— 每开一篇都要重跑一次 AI"
    assert len(calls) == 1
    rows = _cache_rows(auth_client)
    assert len(rows) == 1

    # 画像一改：旧结果必须作废（不然「总论点」这类改动等于没做），且**覆盖**那一行
    old = marks.MK_PROFILES["writed"]
    try:
        marks.MK_PROFILES["writed"] = (old[0], old[1] + [("新类型", "加的")], old[2])
        d = post().get_json()
        assert d.get("cached") is not True, "画像改了还在发旧结果"
        assert d["marks"][0]["why"] == "第 2 次"
    finally:
        marks.MK_PROFILES["writed"] = old
    rows2 = _cache_rows(auth_client)
    assert len(rows2) == 1, "同一篇文章按画像版本堆出了 %d 行垃圾" % len(rows2)
    assert rows2[0]["ref"] == rows[0]["ref"], "ref 变了 —— 老行读不到也删不掉，会永远留在表里"


def test_老格式缓存行不会被当成有效结果(auth_client, monkeypatch):
    """改动之前存的是一个裸 list（没有指纹），要能识别出来重算，而不是当成好数据发出去。"""
    import hashlib
    import json as _json

    from core import get_db
    text = TEXT + "老格式"
    ref = hashlib.md5(("writed\x00" + text).encode("utf-8")).hexdigest()
    with auth_client.application.app_context():
        db = get_db()
        db.execute("INSERT OR REPLACE INTO marks_cache(ref,scope,data_json) VALUES(?,?,?)",
                   (ref, "writed", _json.dumps([{"quote": "旧", "kind": "分论点", "why": "老格式"}])))
        db.commit()
    monkeypatch.setattr(marks, "_mark_text",
                        lambda content, scope="": ([{"quote": "新", "kind": "总论点", "why": "重算的"}], ""))
    d = auth_client.post("/api/marks", json={"text": text, "scope": "writed"}).get_json()
    assert d.get("cached") is not True and d["marks"][0]["why"] == "重算的"
