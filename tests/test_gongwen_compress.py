"""应用文「超字数就压一轮」这两个循环的冒烟测试。

为什么要有这一份：这两个循环（`_gen_yingyong` 的 3 轮、`_gen_yy_compose` 的 2 轮）
是**只有联网才会走到的分支**，此前一条测试都没盖住——而它们刚被改过口径：

  原来第 2、3 轮发的是「原 prompt + 上一版超了多少字」，上一版正文**根本没进消息体**，
  模型是拿着原题从零再写一篇。也就是说那两轮不是在压缩，是在重出。
  现在改成把上一版正文整篇喂回去、只准删，于是这两轮不再产出新内容，档位降到 fast
  （立意选材的钱第 1 轮已经花过 pro 了）。

这份测试钉死的正是这个口径，因为它一旦悄悄改回去，症状是「范文偶尔跑题/材料换了」
而不是报错——线上看不出来，只有对着历史稿子读才会发现。盯四件事：
  ① 第 1 轮 pro、压缩轮 fast（档位反了就是白花钱或掉质量）
  ② 压缩轮的消息体里**必须带着上一版正文**（不带就退回成"重出"了）
  ③ 综合应用的压缩轮只换范文，**给定材料和作答要求原样留着**
  ④ 压缩轮把正文压没了要守住第 1 轮的稿子，不许出残篇
"""
import json

import pytest

from conftest import DB  # noqa: F401  import 它顺带确认测试库隔离生效


def _seg(text):
    return [{"part": "主体·举措", "text": text, "why": "阅卷看举措是否具体"}]


def _essay(db, eid):
    """_gen_yy_compose 只回 eid，题面（材料/要求）落在 spec 那个 JSON 列里。"""
    r = db.execute("SELECT content, spec FROM daily_essays WHERE id=?", (eid,)).fetchone()
    return dict(r["content"] and {"content": r["content"]} or {"content": ""},
                **json.loads(r["spec"] or "{}"))


class _Stub:
    """替掉 _ai_call_or_error，按调用顺序吐预设的 JSON，并记下每次的 (档位, 消息体)。"""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []            # [(tier, user_content)]

    def __call__(self, messages, **kw):
        self.calls.append((kw.get("tier"), messages[-1]["content"]))
        return json.dumps(self.replies[len(self.calls) - 1], ensure_ascii=False), None

    @property
    def tiers(self):
        return [t for t, _ in self.calls]


@pytest.fixture
def gw(flask_app, monkeypatch):
    from mods import gongwen as G
    return G


def test_压缩轮走fast且带着上一版正文(gw, flask_app, monkeypatch):
    """第 1 轮 pro 写、第 2 轮 fast 删；删的那轮必须看得见上一版正文。"""
    long_body = "一、健全机制。" + "推动落实各项举措并持续深化。" * 60      # 稳超上限
    short_body = "一、健全机制。推动落实各项举措。"
    stub = _Stub(
        {"title": "关于加强垃圾分类的通知", "content": long_body,
         "segs": _seg(long_body), "note": "格式最容易丢分"},
        {"title": "关于加强垃圾分类的通知", "content": short_body,
         "segs": _seg(short_body), "note": "格式最容易丢分"},
    )
    monkeypatch.setattr(gw, "_ai_call_or_error", stub)

    with flask_app.app_context():
        from core import get_db
        # mode 用独立的一档：_gen_yingyong 存的是 UNIQUE(mode, date)，而 date 在不传日期时
        # 精确到**秒**——和 test_gongwen_fentiao 同一秒跑就会撞 UNIQUE，那边的裸连接
        # 又会带着没回滚的写事务泄漏出去，整个 session 后面全变「database is locked」。
        _, err = gw._gen_yingyong(get_db(), {"doctype": "通知"}, mode="yingyong-test-compress")

    assert err is None, "生成不该失败：%r" % (err,)
    assert stub.tiers == ["pro", "fast"], \
        "第 1 轮该是 pro（真在写）、压缩轮该是 fast（只做减法），实际 %s" % stub.tiers
    # ② 压缩轮的消息体里要有上一版正文——这是"压缩"和"重出"的分水岭
    compress_msg = stub.calls[1][1]
    assert long_body[:30] in compress_msg, \
        "压缩轮没把上一版正文喂回去，等于又变成了拿原题重写一篇"
    assert "只做减法" in compress_msg


def test_综合应用压缩轮不换给定材料(gw, flask_app, monkeypatch):
    """③ 第 2 轮只压范文：材料和作答要求得是第 1 轮那份，不能跟着换新的。"""
    long_body = "各位居民：\n" + "我们倡议积极参与社区治理共建美好家园。" * 60
    stub = _Stub(
        {"doctype": "倡议书", "material": "【原始材料】某社区推行垃圾分类……",
         "task": "【原始要求】写一份倡议书，不超过500字",
         "title": "垃圾分类倡议书", "content": long_body,
         "segs": _seg(long_body), "note": "倡议书要有感染力"},
        # 压缩轮只回正文/批注这几个键——就算它多嘴回了材料，也不该被采信
        {"title": "垃圾分类倡议书", "content": "各位居民：\n我们倡议参与社区治理。",
         "segs": _seg("各位居民：\n我们倡议参与社区治理。"), "note": "倡议书要有感染力",
         "material": "【它自己新编的材料】", "task": "【它自己新编的要求】"},
    )
    monkeypatch.setattr(gw, "_ai_call_or_error", stub)

    with flask_app.app_context():
        from core import get_db
        db = get_db()
        eid, err = gw._gen_yy_compose(db, "2026-08-04")
        assert err is None, "生成不该失败：%r" % (err,)
        row = _essay(db, eid)

    assert stub.tiers == ["pro", "fast"], "档位该是 pro→fast，实际 %s" % stub.tiers
    assert "原始材料" in (row.get("material") or ""), \
        "压缩轮把给定材料也换掉了——那是重出一整道题，不是压范文"
    assert "原始要求" in (row.get("task") or "")


def test_压缩轮压没了要守住第一轮的稿子(gw, flask_app, monkeypatch):
    """④ 宁可长几十字，也不能因为压缩轮返回空正文就出残篇。"""
    long_body = "各位居民：\n" + "我们倡议积极参与社区治理共建美好家园。" * 60
    stub = _Stub(
        {"doctype": "倡议书", "material": "【原始材料】某社区推行垃圾分类……",
         "task": "【原始要求】写一份倡议书", "title": "垃圾分类倡议书",
         "content": long_body, "segs": _seg(long_body), "note": "要有感染力"},
        {"title": "", "content": "", "segs": [], "note": ""},      # 压缩轮翻车
    )
    monkeypatch.setattr(gw, "_ai_call_or_error", stub)

    with flask_app.app_context():
        from core import get_db
        db = get_db()
        eid, err = gw._gen_yy_compose(db, "2026-08-05")
        assert err is None, "压缩轮翻车不该让整篇失败：%r" % (err,)
        row = _essay(db, eid)

    assert "倡议" in (row.get("content") or ""), "该退回第 1 轮的稿子，实际正文空了"
