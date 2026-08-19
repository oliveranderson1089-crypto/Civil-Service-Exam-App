"""超时的两个口径，以及心跳一路转到浏览器。

背景（近 14 天 ai_calls）：助手 162 次调用里 33 次 timeout，elapsed 最大 41.7 秒 ——
正正卡在当时那条 40 秒线上；而成功调用最慢 34.5 秒，两者只差 16%。原因是一个数当两个用：
「等第一个字节」（死连接，该早点放弃）和「等下一片」（模型在写，该多等）共用一份预算，
再被重试次数一除，每次尝试只剩 33 秒。
"""
import time

import aiclient
from mods import agent


def test_两个口径是分开的且首字节明显更短():
    assert agent.AI_FIRST_BYTE < agent.AI_TIMEOUT
    assert agent.AI_FIRST_BYTE <= 15, "等首字节等太久，死连接就发现不及时"
    # 成功调用实测最慢 34.5 秒，片间预算得留出余量，否则又是「稍慢就误杀」
    assert agent.AI_TIMEOUT >= 50


def test_只有首字节按尝试次数分摊(monkeypatch):
    """重试只在一个字都没吐出去时发生，所以会被乘以三的只有首字节那一段。
    以前连片间超时也一起除，100 秒预算落到每次调用只剩 33 秒。"""
    got = {}

    def fake_stream(messages, **kw):
        got.update(kw)
        return iter(())

    monkeypatch.setattr(aiclient, "stream", fake_stream)
    list(agent._ai_stream([{"role": "user", "content": "x"}],
                          deadline=time.time() + agent.AI_BUDGET))
    assert got["first_byte"] <= agent.AI_BUDGET / (agent.AI_RETRIES + 1) + 0.1
    assert got["first_byte"] <= agent.AI_FIRST_BYTE
    assert got["timeout"] == agent.AI_TIMEOUT, "片间超时不该再被尝试次数除一遍"


def test_预算见底时两个数都跟着缩(monkeypatch):
    got = {}
    monkeypatch.setattr(aiclient, "stream", lambda messages, **kw: (got.update(kw), iter(()))[1])
    list(agent._ai_stream([{"role": "user", "content": "x"}], deadline=time.time() + 9))
    assert got["timeout"] <= 10, "只剩 9 秒还敢等 60 秒，会把总预算撑爆"
    assert got["first_byte"] >= 4, "再紧也得给首字节留一点，否则必然次次超时"


def test_上游心跳被转成事件而不是丢掉(monkeypatch):
    """上游发的 `: keep-alive` 注释帧以前直接丢。转出去是为了让我们自己发给浏览器的
    那条 SSE 一直有字节流动 —— 隧道和前端的空闲超时都只看「有没有字节」。"""
    kinds = [k for k, _ in _fake_stream_lines(
        [b": keep-alive\n", b"\n",
         b'data: {"choices":[{"delta":{"content":"\xe5\x97\xa8"}}]}\n',
         b"data: [DONE]\n"], monkeypatch)]
    assert "ping" in kinds, "心跳被丢掉了，长时间推理时下游会静默到被掐断"
    assert "content" in kinds


def _fake_stream_lines(lines, monkeypatch):
    """拿**真的** stream() 跑一遍，只把「连接 + 响应」换成给定的几行。

    桩一律用 *a/**kw 收参数：conf() 的签名是 (tier, cfg, who)，写死两个参数的桩
    会在别人给它加一个关键字时炸掉，而报错信息（「lambda 收到了意外的 who」）
    离真正的原因隔了十万八千里。
    """
    class R:
        def __iter__(self):
            return iter(lines)

    class Ctx:
        def __enter__(self):
            return R()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(aiclient, "_open", lambda *a, **kw: Ctx())
    monkeypatch.setattr(aiclient, "conf",
                        lambda *a, **kw: {"key": "k", "url": "http://x", "model": "m"})
    return list(aiclient.stream([{"role": "user", "content": "x"}], cfg={}))


# ---------------- SSE 这一头：隧道最怕的是「久久没有字节」 ----------------

def test_一连上就先发一个字节(auth_client, monkeypatch):
    """Cloudflare 掐的是「多久没有响应」。开库、跑视觉模型都在第一帧之前，
    不先递一个字节出去，隧道可能等不到就 524 了。"""
    from mods import aisession
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    monkeypatch.setattr(aisession, "ai_chat_agentic_stream",
                        lambda *a, **k: iter([("done", {"reply": "好", "actions": [],
                                                        "trace": [], "truncated": False})]))
    body = auth_client.post("/api/aichat/chats/%d/stream" % cid,
                            json={"content": "在吗"}).get_data(as_text=True)
    assert body.startswith(": open"), "第一帧不是立刻发出去的"


def test_模型在想的时候心跳照样发到浏览器(auth_client, monkeypatch):
    from mods import aisession
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    monkeypatch.setattr(aisession, "ai_chat_agentic_stream",
                        lambda *a, **k: iter([("ping", ""), ("ping", ""),
                                              ("delta", "嗨"),
                                              ("done", {"reply": "嗨", "actions": [],
                                                        "trace": [], "truncated": False})]))
    body = auth_client.post("/api/aichat/chats/%d/stream" % cid,
                            json={"content": "在吗"}).get_data(as_text=True)
    assert body.count(": ping") == 2, "心跳没转出去，长推理时连接会被中间层掐掉"
    assert "event: delta" in body and "event: done" in body
    # 心跳绝不能被当成正文：它要是混进 reply，落库的回答里就会多出几个冒号
    import sqlite3
    from conftest import DB
    con = sqlite3.connect(DB, timeout=10)
    reply = con.execute("SELECT content FROM ai_msgs WHERE chat_id=? AND role='assistant' "
                        "ORDER BY id DESC LIMIT 1", (cid,)).fetchone()[0]
    con.close()
    assert reply == "嗨"
