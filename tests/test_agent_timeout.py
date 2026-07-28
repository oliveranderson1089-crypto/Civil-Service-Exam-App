"""AI 助手对话：流式输出，以及网络抖动下的行为。

起因是一次真实故障：手机上问一句「垣读什么？」，界面一直停在「思考中…」，最后
弹出「AI 调用失败：The read operation timed out」。实测这条路径正常只要 1~3 秒，
所以慢不是模型在想，是连接已经死了、read 干等到超时。

改成流式之后，「模型在写」和「连接已死」终于分得开了：每个 token 都是一次心跳。
这里钉住的东西：

  1. SSE 帧解析 + tool_calls 分片拼装（碎着到达的 function call 要能拼回去）。
  2. 单次超时短、会重试、且有总预算，不会叠成十分钟。
  3. 工具已经真的做了事、只是收尾那句话失败时，不能报「调用失败」——
     那是假话，用户会以为没做成而再做一遍。
  4. 非流式那条只是把流式跑干，两条路不能各写一份逻辑。
"""
import json
import time

import pytest

import aiclient
from mods import agent


# ---------------------------------------------------------------- 假的 HTTP 响应
class _FakeResp:
    """冒充 urlopen 的返回：可迭代出一行行字节，支持 with。"""

    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._lines)


def _sse(*objs):
    lines = []
    for o in objs:
        lines.append(("data: " + json.dumps(o, ensure_ascii=False)).encode())
        lines.append(b"")
    lines.append(b"data: [DONE]")
    return _FakeResp(lines)


def _delta(**d):
    return {"choices": [{"delta": d}]}


CFG = {"ai_key": "sk-test"}


# ---------------------------------------------------------------- 话术
def test_超时的错误话术是中文而不是英文原文():
    # 读取阶段超时抛的是裸 TimeoutError，不是 URLError，原来会漏到最后一行拼英文
    msg = aiclient.error_message(TimeoutError("The read operation timed out"))
    assert "超时" in msg and "timed out" not in msg


# ---------------------------------------------------------------- 流式底座
def test_流式把正文一片片吐出来(monkeypatch):
    monkeypatch.setattr(aiclient, "_open",
                        lambda c, p, t: _sse(_delta(content="垣读"), _delta(content="yuán")))
    got = list(aiclient.stream([{"role": "user", "content": "垣读什么"}], cfg=CFG))
    assert got[:2] == [("content", "垣读"), ("content", "yuán")]
    assert got[-1] == ("done", {"role": "assistant", "content": "垣读yuán"})


def test_推理段单独成一类事件不混进正文(monkeypatch):
    """v4 这类推理模型先产 reasoning_content。它是「它在想」，不是回答，
    混进正文会让用户看到一大段自言自语。"""
    monkeypatch.setattr(aiclient, "_open",
                        lambda c, p, t: _sse(_delta(reasoning_content="先查读音"), _delta(content="yuán")))
    got = list(aiclient.stream([], cfg=CFG))
    assert ("reasoning", "先查读音") in got
    assert got[-1][1]["content"] == "yuán"


def test_碎片到达的_tool_call_能拼回完整调用(monkeypatch):
    """一次 function call 是碎着来的：函数名和 arguments 都可能分片。
    用赋值而不是 += 拼的话，只会留下最后一片，表现为「工具名不存在」。"""
    monkeypatch.setattr(aiclient, "_open", lambda c, p, t: _sse(
        _delta(tool_calls=[{"index": 0, "id": "c1", "function": {"name": "add_", "arguments": ""}}]),
        _delta(tool_calls=[{"index": 0, "function": {"name": "word", "arguments": '{"wo'}}]),
        _delta(tool_calls=[{"index": 0, "function": {"arguments": 'rd":"垣"}'}}]),
    ))
    msg = list(aiclient.stream([], cfg=CFG))[-1][1]
    assert msg["tool_calls"] == [{"id": "c1", "type": "function",
                                  "function": {"name": "add_word", "arguments": '{"word":"垣"}'}}]


def test_脏帧不会毁掉整次回答(monkeypatch):
    monkeypatch.setattr(aiclient, "_open", lambda c, p, t: _FakeResp([
        b"data: {\xe5\x8d\x8a\xe6\x88\xaa JSON", b"", b": ping", b"",
        ("data: " + json.dumps(_delta(content="好"))).encode(), b"", b"data: [DONE]"]))
    assert list(aiclient.stream([], cfg=CFG))[-1][1]["content"] == "好"


def test_已经吐过字就不再重试(monkeypatch):
    """重试是为了救「一个字都没出来」的死连接；吐了一半再重来，用户会看到重复的半截话。"""
    calls = []

    def boom(c, p, t):
        calls.append(1)
        return _FakeResp([("data: " + json.dumps(_delta(content="半"))).encode(), b"",
                          _Boom()])

    class _Boom:
        def decode(self, *a, **k):
            raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(aiclient, "_open", boom)
    with pytest.raises(TimeoutError):
        list(aiclient.stream([], cfg=CFG, retries=2))
    assert len(calls) == 1


def test_一个字都没出来时才重试(monkeypatch):
    calls = []

    def flaky(c, p, t):
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("The read operation timed out")
        return _sse(_delta(content="好"))

    monkeypatch.setattr(aiclient, "_open", flaky)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert list(aiclient.stream([], cfg=CFG, retries=2))[-1][1]["content"] == "好"
    assert len(calls) == 3


# ---------------------------------------------------------------- 超时口径与预算
def test_对话路径用短超时并且会重试(monkeypatch):
    seen = []
    monkeypatch.setattr(aiclient, "stream", lambda messages, **kw: seen.append(kw) or iter([]))
    list(agent._ai_stream([{"role": "user", "content": "垣读什么？"}]))
    assert seen[0]["timeout"] <= 40, "对话是用户盯着屏幕等的，不该沿用离线脚本的 120 秒"
    assert seen[0]["retries"] >= 2, "一次网络抖动就该自己换连接重来，而不是直接失败"


def test_单次调用不会把总预算撑成三倍(monkeypatch):
    """timeout 是**每次尝试**的：带 2 次重试就是三份，必须摊开算。"""
    seen = []
    monkeypatch.setattr(aiclient, "stream", lambda messages, **kw: seen.append(kw) or iter([]))
    list(agent._ai_stream([], deadline=time.time() + 30))
    assert seen[0]["timeout"] * (seen[0]["retries"] + 1) <= 31


def _fake_stream(events):
    def f(msgs, tools=None, **kw):
        return iter(events(msgs, tools))
    return f


def test_预算耗尽就不再起新一轮工具(monkeypatch):
    calls = []

    def events(msgs, tools):
        calls.append(bool(tools))
        if tools:
            return [("done", {"tool_calls": [{"id": "1", "function": {"name": "x", "arguments": "{}"}}]})]
        return [("content", "收尾"), ("done", {"content": "收尾"})]

    monkeypatch.setattr(agent, "_ai_stream", _fake_stream(events))
    monkeypatch.setattr(agent, "exec_tool", lambda n, a, db: ("做完了", None))
    monkeypatch.setattr(agent, "tool_specs", lambda: [{"x": 1}])
    reply, actions = agent.ai_chat_agentic([], None, max_rounds=4, budget=0.01)
    assert calls == [False], "预算耗尽还继续调工具，就会叠出十分钟的请求"
    assert reply == "收尾"


def test_工具已执行时收尾失败不报调用失败(monkeypatch):
    """AI 真把词收录了，只是最后那句总结没拿到——这时候说「调用失败」是假话。"""
    def events(msgs, tools):
        if tools:
            return [("done", {"tool_calls": [{"id": "1", "function":
                                              {"name": "add_word", "arguments": '{"word":"垣"}'}}]})]
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(agent, "_ai_stream", _fake_stream(events))
    monkeypatch.setattr(agent, "exec_tool",
                        lambda n, a, db: ("已把「垣」加入成语词语积累。", {"type": "refresh", "what": "entries"}))
    monkeypatch.setattr(agent, "tool_specs", lambda: [{"x": 1}])
    reply, actions = agent.ai_chat_agentic([], None, max_rounds=1)
    assert "已把「垣」加入" in reply
    assert actions == [{"type": "refresh", "what": "entries"}], "动作必须照常带回前端去刷新列表"


def test_一个工具都没跑成时超时照旧报错(monkeypatch):
    """没有任何既成事实可交待，就老老实实抛出去，让上层翻成中文提示。"""
    def events(msgs, tools):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(agent, "_ai_stream", _fake_stream(events))
    monkeypatch.setattr(agent, "tool_specs", lambda: [{"x": 1}])
    with pytest.raises(TimeoutError):
        agent.ai_chat_agentic([], None, max_rounds=1)


# ---------------------------------------------------------------- 流式循环
def test_调工具前说的那句话也算进回复(monkeypatch):
    """模型常先说「我先查一下…」再调工具。那句已经出现在用户屏幕上了，
    落库时丢掉的话，刷新页面就会发现回答少了一截。"""
    def events(msgs, tools):
        if tools:
            return [("content", "我先查一下。"),
                    ("done", {"content": "我先查一下。",
                              "tool_calls": [{"id": "1", "function": {"name": "x", "arguments": "{}"}}]})]
        return [("content", "垣读 yuán。"), ("done", {"content": "垣读 yuán。"})]

    monkeypatch.setattr(agent, "_ai_stream", _fake_stream(events))
    monkeypatch.setattr(agent, "exec_tool", lambda n, a, db: ("查到了", None))
    monkeypatch.setattr(agent, "tool_specs", lambda: [{"x": 1}])
    got = list(agent.ai_chat_agentic_stream([], None, max_rounds=1))
    assert ("delta", "我先查一下。") in got
    assert ("tool", {"name": "x"}) in got
    reply = got[-1][1]["reply"]
    assert "我先查一下。" in reply and "垣读 yuán。" in reply


def test_非流式只是把流式跑干(monkeypatch):
    """两条路不能各写一份逻辑，否则会出现「网页版修好了、APK 还是老样子」。"""
    def events(msgs, tools):
        return [("content", "答"), ("done", {"content": "答"})]

    monkeypatch.setattr(agent, "_ai_stream", _fake_stream(events))
    monkeypatch.setattr(agent, "tool_specs", lambda: [{"x": 1}])
    assert agent.ai_chat_agentic([], None) == ("答", [])


# ---------------------------------------------------------------- SSE 端点
def _drain(r):
    """按**生产的方式**把流读完：buffered=False，即视图函数早已返回、请求上下文
    已经收尾之后才继续产出。用 get_data() 那种缓冲读法会掩盖掉「连接已关闭」这类
    只在真流式下才犯的错——这条 bug 就是这么漏过第一版测试的。"""
    return "".join(chunk.decode() for chunk in r.response)


def test_流式端点边推边落库(auth_client, monkeypatch):
    """整条链路：POST /stream → SSE 帧 → done 里带标题 → 历史里能读回来。"""
    from mods import aisession

    def fake(messages, db, **kw):
        yield "delta", "垣读 "
        yield "delta", "yuán。"
        yield "done", {"reply": "垣读 yuán。", "actions": [{"type": "refresh", "what": "entries"}]}

    monkeypatch.setattr(aisession, "ai_chat_agentic_stream", fake)
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    r = auth_client.post("/api/aichat/chats/%d/stream" % cid, json={"content": "垣读什么？"},
                         buffered=False)
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/event-stream")
    body = _drain(r)
    assert 'event: delta\ndata: "垣读 "' in body
    done = json.loads(body.split("event: done\ndata: ")[1].split("\n\n")[0])
    assert done["reply"] == "垣读 yuán。"
    assert done["title"] == "垣读什么？"          # 新会话顺手用首句起名
    assert done["actions"] == [{"type": "refresh", "what": "entries"}]
    msgs = auth_client.get("/api/aichat/chats/%d" % cid).get_json()["msgs"]
    assert [m["content"] for m in msgs] == ["垣读什么？", "垣读 yuán。"], "两句都得落库"


def test_流式端点响应头没被中间层攒着(auth_client, monkeypatch):
    """X-Accel-Buffering / no-cache 少一个，代理就会攒够一批才发，流式白做。"""
    from mods import aisession
    monkeypatch.setattr(aisession, "ai_chat_agentic_stream",
                        lambda m, db, **kw: iter([("done", {"reply": "好", "actions": []})]))
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    r = auth_client.post("/api/aichat/chats/%d/stream" % cid, json={"content": "在吗"},
                         buffered=False)
    _drain(r)
    assert r.headers.get("X-Accel-Buffering") == "no"
    assert r.headers.get("Cache-Control") == "no-cache"
    assert not r.headers.get("Content-Encoding"), "事件流被 gzip 攒起来就不是流了"


def test_流式端点出错走事件而不是状态码(auth_client, monkeypatch):
    """响应头早发出去了，这时候再想改 HTTP 状态码已经晚了，只能推 error 事件。"""
    from mods import aisession

    def boom(messages, db, **kw):
        raise TimeoutError("The read operation timed out")
        yield  # noqa: 让它是生成器

    monkeypatch.setattr(aisession, "ai_chat_agentic_stream", boom)
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    r = auth_client.post("/api/aichat/chats/%d/stream" % cid, json={"content": "在吗"},
                         buffered=False)
    assert r.status_code == 200
    body = _drain(r)
    assert "event: error" in body and "超时" in body


def test_流式里深层代码拿到的连接是活的(auth_client, monkeypatch):
    """工具底下的 core.lookup() / current_user() 是自己去 get_db() 的，几十处。
    生成器跑起来时 g 上那条早被 teardown 关了，不把它顶掉就会
    "Cannot operate on a closed database."——AI 说收录成功，库里其实什么都没有。"""
    from mods import aisession

    def uses_get_db(messages, db, **kw):
        from core import get_db as deep_get_db
        n = deep_get_db().execute("SELECT COUNT(*) c FROM ai_chats").fetchone()["c"]
        yield "done", {"reply": "会话数 %d" % n, "actions": []}

    monkeypatch.setattr(aisession, "ai_chat_agentic_stream", uses_get_db)
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    r = auth_client.post("/api/aichat/chats/%d/stream" % cid, json={"content": "几个会话"},
                         buffered=False)
    body = _drain(r)
    assert "event: error" not in body, body[:300]
    assert "会话数" in body


def test_客户端中途断开也要把这一轮存下来(auth_client, monkeypatch):
    """手机切后台、隧道抖一下，客户端就不读了。

    工具的副作用（词已入库）是**已经发生**的事实，可这一问一答如果没落库，
    历史里就凭空少一轮：用户回头看聊天记录，只看到自己问了、AI 没答，
    再问一遍就会重复收录。所以断开时也要把已经吐出去的字存下来。
    """
    from mods import aisession

    def fake(messages, db, **kw):
        db.execute("INSERT INTO entries(user_id,word,pinyin,category,explanation,"
                   "derivation,example,note,source) VALUES(1,'筚路蓝缕','','成语','','','','','ai')")
        db.commit()
        for ch in "已收录成功。":
            yield "delta", ch
        yield "done", {"reply": "已收录成功。", "actions": []}

    monkeypatch.setattr(aisession, "ai_chat_agentic_stream", fake)
    cid = auth_client.post("/api/aichat/chats", json={}).get_json()["id"]
    r = auth_client.post("/api/aichat/chats/%d/stream" % cid, json={"content": "收录筚路蓝缕"},
                         buffered=False)
    next(iter(r.response))          # 只收第一帧
    r.close()                       # …然后断开
    msgs = auth_client.get("/api/aichat/chats/%d" % cid).get_json()["msgs"]
    assert [m["role"] for m in msgs] == ["user", "assistant"], "断开后这一轮不能凭空消失"
    assert "已收录" in msgs[1]["content"]
