"""两件事：失败那一轮能原样重试；附件被截断时模型必须知道自己没看全。

前者原先只留一句「请再发一次」，用户得把刚才那句手打一遍（截图里「C、B、B」打了三遍）。
后者原先是默默 text[:6000] —— 模型看到的是「一份完整的短资料」，于是自信地答出
「这份 PDF 里只有 12 个易混淆点」，谁也看不出它压根没读完。
"""
import json
import sqlite3

import pytest

from conftest import DB
from mods import aisession


def _q(sql, args=()):
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


@pytest.fixture
def chat(auth_client):
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    return auth_client, cid


@pytest.fixture
def fake_ai(monkeypatch):
    seen = {}

    def fake(messages, db, **kw):
        seen["msgs"] = messages
        return "好的。", [], [], None

    monkeypatch.setattr(aisession, "_ai_agentic_or_error", fake)
    return seen


def _add(cid, role, content, kind="text"):
    con = sqlite3.connect(DB, timeout=10)
    con.execute("INSERT INTO ai_msgs(chat_id,role,content,kind) VALUES(?,?,?,?)",
                (cid, role, content, kind))
    con.commit()
    con.close()


# ---------------- 重试失败的那一轮 ----------------

def test_重试把失败那半轮退掉(chat):
    c, cid = chat
    _add(cid, "user", "C、B、B")
    _add(cid, "assistant", "（本次回答失败：网络超时）", "error")
    r = c.post("/api/aichat/chats/%d/retry" % cid, json={"failed": True})
    d = r.get_json()
    assert d["rewound"] is True
    assert d["content"] == "C、B、B", "得把原话还回来，不然还是要用户重打"
    assert not _q("SELECT 1 FROM ai_msgs WHERE chat_id=?", (cid,)), "失败那半轮该被退干净"


def test_末尾不是失败占位时一条都不许删(chat):
    """非流式那条路失败时压根没落库，末尾是**上一轮成功的**问答。
    照「退最后一轮」处理会把好好的一轮删掉，用户还以为只是重试了一下。"""
    c, cid = chat
    _add(cid, "user", "上一轮的问题")
    _add(cid, "assistant", "上一轮的回答")
    r = c.post("/api/aichat/chats/%d/retry" % cid, json={"failed": True})
    d = r.get_json()
    assert d["rewound"] is False, "没有失败占位就不该退"
    assert d["content"] == ""
    assert len(_q("SELECT 1 FROM ai_msgs WHERE chat_id=?", (cid,))) == 2, "成功的那一轮被误删了"


def test_普通重答不受影响(chat):
    c, cid = chat
    _add(cid, "user", "原来的问题")
    _add(cid, "assistant", "原来的回答")
    d = c.post("/api/aichat/chats/%d/retry" % cid, json={}).get_json()
    assert d["content"] == "原来的问题"
    assert not _q("SELECT 1 FROM ai_msgs WHERE chat_id=?", (cid,))


# ---------------- 截断要留痕 ----------------

def test_附件被截断时明确告诉模型还有后续(chat, fake_ai):
    c, cid = chat
    body = "易混淆点内容" * 6000                      # 36000 字，超过 ATT_LIMIT
    c.post("/api/aichat/chats/%d/send" % cid,
           json={"content": "这份资料里一共有几个易混淆点？",
                 "attachments": [{"name": "社工.pdf", "text": body,
                                  "total": len(body), "pages": 48}]})
    sent = fake_ai["msgs"][-1]["content"]
    assert "共 48 页" in sent, "页数要报给模型"
    assert "后面还有没给你的内容" in sent, "截断没留痕 —— 模型会拿半截当全文下结论"
    assert "不要拿这半截当成全文下结论" in sent


def test_没截断就别画蛇添足(chat, fake_ai):
    c, cid = chat
    body = "很短的一份资料"
    c.post("/api/aichat/chats/%d/send" % cid,
           json={"content": "看看", "attachments": [{"name": "短.txt", "text": body,
                                                     "total": len(body)}]})
    sent = fake_ai["msgs"][-1]["content"]
    assert body in sent
    assert "后面还有" not in sent, "全文都给了还说没给全，会让模型无谓地打折扣"


def test_历史附件走小闸而本轮走大闸(chat, fake_ai):
    """本轮附件是用户正等着被读完的，历史那份只是回放 —— 两道闸口径不同。"""
    assert aisession.ATT_LIMIT > aisession.ATT_HIST
    c, cid = chat
    body = "甲" * (aisession.ATT_HIST + 5000)
    c.post("/api/aichat/chats/%d/send" % cid,
           json={"content": "读这个", "attachments": [{"name": "长.pdf", "text": body,
                                                       "total": len(body)}]})
    now = fake_ai["msgs"][-1]["content"]
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "接着说"})
    hist = "\n".join(m["content"] for m in fake_ai["msgs"])
    assert now.count("甲") > aisession.ATT_HIST, "本轮附件该按大闸给"
    assert hist.count("甲") <= aisession.ATT_HIST + 10, "历史回放该按小闸收着"


def test_客户端报的总量畸形时不炸(chat, fake_ai):
    c, cid = chat
    for bad in ("abc", None, -5, 10 ** 12, [1]):
        r = c.post("/api/aichat/chats/%d/send" % cid,
                   json={"content": "看", "attachments": [{"name": "x.txt", "text": "内容",
                                                           "total": bad}]})
        assert r.status_code == 200, "total=%r 把接口打挂了" % (bad,)


# ---------------- 附件原图不能悄悄丢 ----------------

def test_临时文件跨文件系统时原图照样留得住(auth_client, monkeypatch, tmp_path):
    """/tmp 和 uploads 常常不在同一个文件系统（这台机器就是），os.replace 会抛
    OSError(18, 'Invalid cross-device link')。原来抛了就把 keep 清空 —— 表现是
    **图片被静默降级**：视觉模型再也看不到原图，只剩 OCR 文字，而图形推理和资料分析
    恰恰全在图里。日志里只有一行 INFO，界面上什么都不说。"""
    import io as _io
    import os

    from mods import attach

    real_replace = os.replace

    def cross_device(src, dst):
        if str(dst).startswith(str(attach.AI_IMG_DIR)):
            raise OSError(18, "Invalid cross-device link")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", cross_device)
    monkeypatch.setattr(attach, "vision_configured", lambda: False)
    monkeypatch.setattr(attach, "_ocr_image", lambda p: "识别出来的字")

    r = auth_client.post("/api/ai/extract", content_type="multipart/form-data",
                         data={"file": (_io.BytesIO(b"\x89PNG\r\n\x1a\nfake"), "题目.png")})
    d = r.get_json()
    assert d.get("image"), "原图没留下，这一轮就用不上视觉模型了"
    assert os.path.exists(os.path.join(attach.AI_IMG_DIR, d["image"]))
    assert d["text"] == "识别出来的字"
