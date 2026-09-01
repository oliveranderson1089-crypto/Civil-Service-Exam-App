"""「联网」这一路：按钮真的接上了线，工具调用标记不许漏到屏幕上。

背景是一次真实故障。用户说「AI 联网搜索用不了」，查下来底层全是好的 ——
Brave 有 key、搜得到结果、模型也肯调 web_search（trace 里几条都带回了真链接）。
坏在最后一步：轮数用完后那次收尾调用**不带 tools**，而 DeepSeek 照旧想调工具，
于是把工具调用当正文吐了出来 ——

    <｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="web_fetch">…

用户屏幕上就是这么一串乱码，答案没了。所以这里锁三件事：
  1. 标记一个字都不许推给前端（而且要在**流式那一层**挡住，攒完再洗已经晚了）；
  2. 收尾那轮什么也没说出来时，得把查到的来源自己交代出去，不能让人对着半句话收场；
  3. web=True 时 web_search/web_fetch **必须在手上** —— 按钮是明示的意图，
     不能再交给关键词正则去猜，猜漏一次就等于这个按钮没接线。
"""
import json

import pytest

import mods.agent  # noqa: F401  工具在这里注册
from mods import agent


# ---------------- 标记不许漏出去 ----------------

def test_截断工具调用标记():
    vis, cut = agent._cut_markup("先说结论。<｜｜DSML｜｜tool_calls>后面全是标记")
    assert cut is True
    assert vis == "先说结论。"
    assert "DSML" not in vis


def test_正常正文一个字都不动():
    t = "答案是 A，因为 3 < 5 且 a<b。"
    vis, cut = agent._cut_markup(t)
    assert (vis, cut) == (t, False), "别把普通的小于号当成标记开头"


def test_标记被切在两片之间也挡得住(monkeypatch):
    """流式是一片一片来的，`<｜` 和 `｜DSML` 很可能分在两片里。
    只看单片的话这道闸形同虚设 —— 拼起来才认得出。"""
    def split_stream(msgs, tools=None, **kw):
        return iter([("content", "结论在这。<｜"), ("content", "｜DSML｜｜tool_calls>"),
                     ("content", "<invoke name=\"web_fetch\">"),
                     ("done", {"content": "x"})])

    monkeypatch.setattr(agent, "_ai_stream", split_stream)
    monkeypatch.setattr(agent, "tool_specs_for", lambda t, **k: [{"x": 1}])
    out = "".join(p for k, p in agent.ai_chat_agentic_stream([], None) if k == "delta")
    assert "DSML" not in out and "invoke" not in out
    assert "结论在这。" in out


def test_扣住的尾巴最后要补发(monkeypatch):
    """尾部的 `<` 会被先扣住等下一片。流结束了还扣着不发，就等于把话截了半句。"""
    def tail_stream(msgs, tools=None, **kw):
        return iter([("content", "区间是 [0, 1)，注意 a<"), ("content", "b 这个前提"),
                     ("done", {"content": "x"})])

    monkeypatch.setattr(agent, "_ai_stream", tail_stream)
    monkeypatch.setattr(agent, "tool_specs_for", lambda t, **k: [{"x": 1}])
    out = "".join(p for k, p in agent.ai_chat_agentic_stream([], None) if k == "delta")
    assert out.endswith("a<b 这个前提")


# ---------------- 收尾空了要兜底 ----------------

def test_攒命中要趁结果还完整():
    bag = []
    agent._collect_hits(bag, json.dumps(
        [{"title": "某县公告", "url": "https://x/y", "snippet": "8月11日"}], ensure_ascii=False))
    assert bag and bag[0]["url"] == "https://x/y"


def test_没搜着那类人话不会被当成命中():
    bag = []
    agent._collect_hits(bag, "没能去搜（连不上搜索服务）。请如实告诉用户这一点")
    assert bag == [], "这是给模型看的人话，不是 JSON，别硬塞进来源清单"


def test_兜底把来源列出来():
    md = agent._fallback_from_hits([
        {"title": "某县公告", "url": "https://x/y", "snippet": "8月11日发布"},
        {"title": "重复的", "url": "https://x/y"},
    ])
    assert "https://x/y" in md and md.count("https://x/y") == 1, "同一个链接别列两遍"


def test_收尾一个字没说就把来源交代出去(monkeypatch):
    """真实故障的样子：搜到了，但收尾那轮还在写工具调用、被闸门整段挡掉。
    这时候不兜底，用户看到的就只有几句「我再查一下」。"""
    rounds = []

    def stream(msgs, tools=None, **kw):
        rounds.append(bool(tools))
        if tools:
            return iter([("content", "我先查一下。"),
                         ("done", {"tool_calls": [{"id": "1", "function": {
                             "name": "web_search", "arguments": '{"query":"某县 公告"}'}}]})])
        # 收尾轮：它还想调工具，于是整段都是标记 —— 可见正文为空
        return iter([("content", "<｜｜DSML｜｜tool_calls>"), ("done", {"content": ""})])

    monkeypatch.setattr(agent, "_ai_stream", stream)
    monkeypatch.setattr(agent, "exec_tool", lambda n, a, db: (json.dumps(
        [{"title": "某县选聘公告", "url": "https://example/1", "snippet": "8-11"}],
        ensure_ascii=False), None))
    monkeypatch.setattr(agent, "tool_specs_for", lambda t, **k: [{"x": 1}])
    done = [p for k, p in agent.ai_chat_agentic_stream([], None, max_rounds=1) if k == "done"][-1]
    assert "DSML" not in done["reply"], "标记不许进落库的正文"
    assert "https://example/1" in done["reply"], "查到的来源必须交代给用户"


def test_收尾说清楚了就不画蛇添足(monkeypatch):
    def stream(msgs, tools=None, **kw):
        if tools:
            return iter([("done", {"tool_calls": [{"id": "1", "function": {
                "name": "web_search", "arguments": '{"query":"x"}'}}]})])
        return iter([("content", "公告 8 月 11 日发布，见 https://example/1，报名 8-24 起。"),
                     ("done", {"content": "…"})])

    monkeypatch.setattr(agent, "_ai_stream", stream)
    monkeypatch.setattr(agent, "exec_tool", lambda n, a, db: (json.dumps(
        [{"title": "公告", "url": "https://example/1"}], ensure_ascii=False), None))
    monkeypatch.setattr(agent, "tool_specs_for", lambda t, **k: [{"x": 1}])
    done = [p for k, p in agent.ai_chat_agentic_stream([], None, max_rounds=1) if k == "done"][-1]
    assert "先把出处给你" not in done["reply"], "话说全了还贴一份原始清单是噪音"


# ---------------- 按钮真的接上了线 ----------------

def test_开了联网就一定拿得到联网工具(monkeypatch):
    got = {}

    def spy(text, min_tools=12, always=()):
        got["always"] = tuple(always)
        return [{"x": 1}]

    monkeypatch.setattr(agent, "tool_specs_for", spy)
    monkeypatch.setattr(agent, "_ai_stream",
                        lambda msgs, tools=None, **kw: iter([("done", {"content": ""})]))
    list(agent.ai_chat_agentic_stream([{"role": "user", "content": "在吗"}], None, web=True))
    assert "web_search" in got["always"] and "web_fetch" in got["always"], \
        "按钮是明示的意图，不能再让关键词正则去猜 —— 猜漏一次就等于按钮没接线"


def test_没开联网就别硬塞(monkeypatch):
    got = {}

    def spy(text, min_tools=12, always=()):
        got["always"] = tuple(always)
        return [{"x": 1}]

    monkeypatch.setattr(agent, "tool_specs_for", spy)
    monkeypatch.setattr(agent, "_ai_stream",
                        lambda msgs, tools=None, **kw: iter([("done", {"content": ""})]))
    list(agent.ai_chat_agentic_stream([{"role": "user", "content": "在吗"}], None))
    assert "web_search" not in got["always"]


def test_开了联网要把硬指令递到模型面前(monkeypatch):
    seen = {}

    def stream(msgs, tools=None, **kw):
        seen["msgs"] = list(msgs)
        return iter([("done", {"content": ""})])

    monkeypatch.setattr(agent, "_ai_stream", stream)
    monkeypatch.setattr(agent, "tool_specs_for", lambda t, **k: [{"x": 1}])
    list(agent.ai_chat_agentic_stream([{"role": "user", "content": "今年公告出了没"}],
                                      None, web=True))
    sys_msgs = [m["content"] for m in seen["msgs"] if m.get("role") == "system"]
    assert any("必须先调用 web_search" in c for c in sys_msgs)
    assert "必须先调用 web_search" in seen["msgs"][-1]["content"], \
        "指令要放在最后一条、贴着用户那句话 —— 排在千字系统提示里模型会当耳边风"


def test_收尾轮要明说不许再调工具(monkeypatch):
    """光是不给 tools 治不了：它照旧想调，然后把调用当正文吐出来。"""
    seen = []

    def stream(msgs, tools=None, **kw):
        if tools:
            seen.append(None)
            return iter([("done", {"tool_calls": [{"id": "1", "function": {
                "name": "web_search", "arguments": "{}"}}]})])
        seen.append([m["content"] for m in msgs if m.get("role") == "system"])
        return iter([("content", "好了"), ("done", {"content": "好了"})])

    monkeypatch.setattr(agent, "_ai_stream", stream)
    monkeypatch.setattr(agent, "exec_tool", lambda n, a, db: ("[]", None))
    monkeypatch.setattr(agent, "tool_specs_for", lambda t, **k: [{"x": 1}])
    list(agent.ai_chat_agentic_stream([], None, max_rounds=1))
    final_sys = seen[-1]
    assert any("不要再调用任何工具" in c for c in final_sys)
