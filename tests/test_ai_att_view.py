"""AI 助手的附件：秒回、逐字看图、点得开。

三件事都是同一句抱怨的三个面 ——「传完图要等半天，等完给的还是一整坨，
而且传上去的东西点也点不开、看不到里面是什么」：

1. **上传秒回**：图片的转写要十几到几十秒（实测 12~37s，见日志 `AI 附件（上传）`），
   以前它挡在上传响应里，用户对着「读取中…」干等。现在原图存好就返回，转写走后台。
2. **带图问答逐字出**：以前这一轮走 vision_chat（stream=False），整段算完才一次性推，
   同一个界面里不带图的问答逐字出、带图的反而像卡死。
3. **附件点得开**：正文不随历史回传（一份 PDF 六万字），改成按需取 —— 前端点开时
   才来 /att 这条路。跨会话拿不到别人的。
"""
import io
import json
import time

import pytest

from mods import ai as aimod
from mods import aisession, attach

PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture
def cid(auth_client):
    return auth_client.post("/api/aichat/chats", json={}).get_json()["id"]


def _upload(client, name="题.png", data=PNG, mime="image/png"):
    return client.post("/api/ai/extract", data={"file": (io.BytesIO(data), name, mime)},
                       content_type="multipart/form-data").get_json()


def _wait_ocr(image, secs=10):
    for _ in range(int(secs * 20)):
        if attach.ai_img_text(image):
            return True
        time.sleep(0.05)
    return False


def _drain(r):
    return "".join(chunk.decode() for chunk in r.response)


# ---------------------------------------------------------------- 1. 上传秒回
def test_传图不等转写(auth_client, monkeypatch):
    """转写慢得离谱，但它不该挡着用户 —— 视觉模型回答时看的是原图，转写只是兜底。"""
    slow = {"n": 0}

    def crawl(path, prefer="free"):
        slow["n"] += 1
        time.sleep(1.5)
        return "图里的字"

    monkeypatch.setattr(attach, "vision_configured", lambda: True)
    monkeypatch.setattr(attach, "vision_ocr", crawl)
    t0 = time.time()
    d = _upload(auth_client)
    took = time.time() - t0
    assert took < 1.0, "上传等了 %.1fs —— 转写又被挪回同步那条路上了" % took
    assert d["text"] == "" and d["ocr"] == "pending"
    assert d["image"], "原图必须留档，否则这一轮就看不成图了"
    assert _wait_ocr(d["image"]), "后台转写没落盘"
    assert slow["n"] == 1


def test_转写补进历史(auth_client, monkeypatch, cid):
    """图 3 天后就清了。落库那一刻要是没把转写补进去，这条历史往后就是一片空白。"""
    monkeypatch.setattr(attach, "vision_configured", lambda: True)
    monkeypatch.setattr(attach, "vision_ocr", lambda p, prefer="free": "第 21 题：下列说法正确的是")
    monkeypatch.setattr(aisession, "vision_configured", lambda: False)   # 这一轮别真去问模型
    monkeypatch.setattr(aisession, "_ai_agentic_or_error",
                        lambda *a, **kw: ("看到了。", [], [], None))
    d = _upload(auth_client)
    assert _wait_ocr(d["image"])
    r = auth_client.post("/api/aichat/chats/%d/send" % cid, json={
        "content": "这题怎么做", "attachments": [{"name": d["name"], "text": "", "image": d["image"]}]})
    assert r.status_code == 200
    mid = r.get_json()["user_mid"]
    att = auth_client.get("/api/aichat/chats/%d/att" % cid,
                          query_string={"mid": mid, "i": 0}).get_json()
    assert "第 21 题" in att["text"], "落库时没把后台补出来的转写带上"


# ------------------------------------------------------------ 2. 带图逐字出
def test_带图那一轮也是逐字推的(auth_client, monkeypatch, cid):
    seen = {}

    def fake_stream(text, images, **kw):
        seen["images"] = images
        seen["prefer"] = kw.get("prefer")
        yield "reasoning", "先数一下图形的对称轴…"
        yield "content", "先看图："
        yield "ping", ""
        yield "content", "选 B。"
        yield "done", "先看图：选 B。"

    monkeypatch.setattr(attach, "vision_configured", lambda: True)
    monkeypatch.setattr(attach, "vision_ocr", lambda p, prefer="free": "题干")
    monkeypatch.setattr(aisession, "vision_configured", lambda: True)
    monkeypatch.setattr(aisession, "vision_stream", fake_stream)
    d = _upload(auth_client)
    r = auth_client.post("/api/aichat/chats/%d/stream" % cid, buffered=False, json={
        "content": "这题选什么", "attachments": [{"name": d["name"], "text": "", "image": d["image"]}]})
    body = _drain(r)
    assert body.count("event: delta") == 2, "整段一次性推 = 用户对着骨架屏干等，白做流式"
    assert ": ping" in body, "上游心跳没转出去，隧道会把静默的连接掐掉"
    # 精准档是推理模型，正文之前能想几十秒。推理段不转出去 = 那几十秒里下游一个字节都没有
    assert "event: reasoning" in body, "看图的推理段被吞了，前端的推理卡和心跳都指望它"
    done = json.loads(body.split("event: done\ndata: ")[1].split("\n\n")[0])
    assert done["reply"] == "先看图：选 B。"
    assert seen["images"] and seen["images"][0].endswith(d["image"]), "给模型的得是原图"
    msgs = auth_client.get("/api/aichat/chats/%d" % cid).get_json()["msgs"]
    assert [m["content"] for m in msgs] == ["这题选什么", "先看图：选 B。"]


def test_看图断在半截也把已出的字留下(auth_client, monkeypatch, cid):
    """用户屏幕上已经看见的字是真的。整轮判失败的话，刷新之后它们就凭空没了。"""
    def half(text, images, **kw):
        yield "content", "这道题考的是"
        raise RuntimeError("上游断了")

    monkeypatch.setattr(attach, "vision_configured", lambda: False)
    monkeypatch.setattr(aisession, "vision_configured", lambda: True)
    monkeypatch.setattr(aisession, "vision_stream", half)
    d = _upload(auth_client)
    r = auth_client.post("/api/aichat/chats/%d/stream" % cid, buffered=False, json={
        "content": "这题选什么", "attachments": [{"name": d["name"], "image": d["image"]}]})
    body = _drain(r)
    assert "event: error" not in body
    done = json.loads(body.split("event: done\ndata: ")[1].split("\n\n")[0])
    assert done["reply"].startswith("这道题考的是") and "不完整" in done["reply"]
    msgs = auth_client.get("/api/aichat/chats/%d" % cid).get_json()["msgs"]
    assert len(msgs) == 2, "半截答案也得落库"


def test_一个字都没出才算失败(auth_client, monkeypatch, cid):
    def boom(text, images, **kw):
        raise RuntimeError("视觉识别失败（HTTP 429）")
        yield  # noqa: 让它是生成器

    monkeypatch.setattr(attach, "vision_configured", lambda: False)
    monkeypatch.setattr(aisession, "vision_configured", lambda: True)
    monkeypatch.setattr(aisession, "vision_stream", boom)
    d = _upload(auth_client)
    r = auth_client.post("/api/aichat/chats/%d/stream" % cid, buffered=False, json={
        "content": "这题选什么", "attachments": [{"name": d["name"], "image": d["image"]}]})
    body = _drain(r)
    assert "event: error" in body


def test_没有图就不走视觉那条路(auth_client, monkeypatch, cid):
    """纯文字提问必须照旧走带工具的文本流 —— 视觉那条路是没有工具的。"""
    monkeypatch.setattr(aisession, "vision_configured", lambda: True)
    monkeypatch.setattr(aisession, "vision_stream",
                        lambda *a, **kw: pytest.fail("纯文字问题被塞给视觉模型了"))
    monkeypatch.setattr(aisession, "ai_chat_agentic_stream",
                        lambda m, db, **kw: iter([("done", {"reply": "好", "actions": []})]))
    r = auth_client.post("/api/aichat/chats/%d/stream" % cid, buffered=False,
                         json={"content": "垣读什么"})
    assert "event: done" in _drain(r)


# ------------------------------------------------------------ 3. 附件看得见
def test_历史带得出附件的字数但不带正文(auth_client, monkeypatch, cid):
    monkeypatch.setattr(aisession, "_ai_agentic_or_error",
                        lambda *a, **kw: ("好的。", [], [], None))
    long_text = "讲义正文" * 200
    r = auth_client.post("/api/aichat/chats/%d/send" % cid, json={
        "content": "📎 讲义.pdf",
        "attachments": [{"name": "讲义.pdf", "text": long_text, "total": 5000, "pages": 14}]})
    mid = r.get_json()["user_mid"]
    m = auth_client.get("/api/aichat/chats/%d" % cid).get_json()["msgs"][0]
    a = m["atts"][0]
    assert "text" not in a, "六万字的正文跟着每次打开会话重下一遍，白占带宽"
    assert a["got"] == len(long_text) and a["total"] == 5000 and a["pages"] == 14
    # 点开才去取
    d = auth_client.get("/api/aichat/chats/%d/att" % cid,
                        query_string={"mid": mid, "i": 0}).get_json()
    assert d["text"] == long_text and d["name"] == "讲义.pdf" and d["pages"] == 14


def test_附件正文取不到别人的(auth_client, monkeypatch, cid):
    monkeypatch.setattr(aisession, "_ai_agentic_or_error",
                        lambda *a, **kw: ("好的。", [], [], None))
    mid = auth_client.post("/api/aichat/chats/%d/send" % cid, json={
        "content": "📎 私密.txt",
        "attachments": [{"name": "私密.txt", "text": "只有我能看"}]}).get_json()["user_mid"]
    other = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    # 换个会话号去拿同一条消息：mid 是全表自增的，光凭它取就等于谁都能读
    r = auth_client.get("/api/aichat/chats/%d/att" % other, query_string={"mid": mid, "i": 0})
    assert r.status_code == 404
    assert "只有我能看" not in r.get_data(as_text=True)


def test_转写还没跑完时说清楚在等什么(auth_client, monkeypatch, cid):
    """点开一张刚发的图，正文是空的 —— 得分清「还在转写」和「压根没有」。"""
    monkeypatch.setattr(attach, "vision_configured", lambda: False)
    monkeypatch.setattr(attach, "_ocr_image", lambda p: "")     # 转写不出东西
    monkeypatch.setattr(aisession, "vision_configured", lambda: False)
    monkeypatch.setattr(aisession, "_ai_agentic_or_error",
                        lambda *a, **kw: ("看到了。", [], [], None))
    d = _upload(auth_client)
    mid = auth_client.post("/api/aichat/chats/%d/send" % cid, json={
        "content": "看图", "attachments": [{"name": d["name"], "image": d["image"]}],
    }).get_json()["user_mid"]
    got = auth_client.get("/api/aichat/chats/%d/att" % cid,
                          query_string={"mid": mid, "i": 0}).get_json()
    assert got["text"] == "" and got["ocr"] == "pending" and got["image"] == d["image"]


# ---------------------------------------------------------- 流式视觉的档位
def test_流式视觉和非流式走同一套档位(monkeypatch):
    """退档规则各写一份的话，迟早出现「同一张图，问答能看、转写看不了」。"""
    seen = []
    monkeypatch.setattr(aimod, "_vision_lanes", lambda prefer: seen.append(prefer) or [])
    monkeypatch.setattr(aimod, "_vision_content", lambda t, i: [])
    with pytest.raises(RuntimeError):
        aimod.vision_chat("x", [], prefer="exact")
    with pytest.raises(RuntimeError):
        list(aimod.vision_stream("x", [], prefer="exact"))
    assert seen == ["exact", "exact"]
