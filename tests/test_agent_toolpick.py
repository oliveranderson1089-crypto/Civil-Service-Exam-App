"""AI 工具按意图裁剪，以及「没干完」的标记（方案乙尾项）。

四十多个工具的 schema 每轮都发一遍，既是固定开销，也让模型在一堆相近的 list_*/get_*
里挑。裁剪的红线是：**宁可多给，也不能让模型因为工具被裁而回一句「我做不到」**。
"""
import mods.agent  # noqa: F401  写工具在这里注册，不导入的话注册表只有一半
from mods.agent_tools import TOOL_REGISTRY, tool_specs, tool_specs_for


def _names(specs):
    return {s["function"]["name"] for s in specs}


def test_没命中主题就原样全给():
    assert len(tool_specs_for("你好呀")) == len(tool_specs())
    assert len(tool_specs_for("")) == len(tool_specs())


def test_命中主题只留相关的读工具():
    n = _names(tool_specs_for("我判断推理错得最多的是哪类"))
    assert "list_wrong_questions" in n and "get_study_stats" in n
    assert "search_classics" not in n, "问错题不该还带着古诗文检索"
    assert len(n) < len(tool_specs())


def test_写改删导航一律不裁():
    """裁掉写工具就成了「它突然不会做这件事了」——比多花几个 token 严重得多。"""
    writes = {k for k, v in TOOL_REGISTRY.items() if v["kind"] != "read"}
    for q in ("我判断推理错得最多的是哪类", "帮我找一首关于坚持的古诗", "今天要复习什么"):
        assert writes <= _names(tool_specs_for(q)), q


def test_兜底工具永远在():
    for q in ("我判断推理错哪最多", "帮我找一首关于坚持的古诗"):
        n = _names(tool_specs_for(q))
        assert "global_search" in n and "get_user_overview" in n, "不知道去哪找时的兜底不能裁"


def test_裁得太狠就不裁():
    """只剩几个反而更容易选错——模型会硬套手上有的那个。"""
    assert len(tool_specs_for("古诗", min_tools=99)) == len(tool_specs())


def test_没干完会打上_truncated(monkeypatch):
    """轮数用完还在调工具 = 活没干完，前端据此给「继续」。"""
    from mods import agent

    def always_tool(msgs, tools=None, **kw):
        return iter([("done", {"tool_calls": [{"id": "1", "function":
                                               {"name": "x", "arguments": "{}"}}]})])

    monkeypatch.setattr(agent, "_ai_stream", always_tool)
    monkeypatch.setattr(agent, "exec_tool", lambda n, a, db: ("查到一批", None))
    monkeypatch.setattr(agent, "tool_specs_for", lambda t, **k: [{"x": 1}])
    done = [p for k, p in agent.ai_chat_agentic_stream([], None, max_rounds=2) if k == "done"][-1]
    assert done["truncated"] is True


def test_正常答完不会打_truncated(monkeypatch):
    from mods import agent

    def plain(msgs, tools=None, **kw):
        return iter([("content", "答完了"), ("done", {"content": "答完了"})])

    monkeypatch.setattr(agent, "_ai_stream", plain)
    monkeypatch.setattr(agent, "tool_specs_for", lambda t, **k: [{"x": 1}])
    done = [p for k, p in agent.ai_chat_agentic_stream([], None) if k == "done"][-1]
    assert done["truncated"] is False


def test_等用户确认删除不算没干完(monkeypatch):
    """停下来是为了等确认，不是没干完——这时候弹「继续」会让人以为要接着删。"""
    from mods import agent

    def ask(msgs, tools=None, **kw):
        return iter([("done", {"tool_calls": [{"id": "1", "function":
                                               {"name": "delete_note", "arguments": '{"id":1}'}}]})])

    monkeypatch.setattr(agent, "_ai_stream", ask)
    monkeypatch.setattr(agent, "exec_tool",
                        lambda n, a, db: ("需要确认", {"type": "confirm", "tool": n, "args": a}))
    monkeypatch.setattr(agent, "tool_specs_for", lambda t, **k: [{"x": 1}])
    done = [p for k, p in agent.ai_chat_agentic_stream([], None, max_rounds=3) if k == "done"][-1]
    assert done["truncated"] is False


# ---------------- 新工具必须挑得到（2026-08 扩了 10 个工具） ----------------
# 这个函数只裁**读**工具。加了读工具却忘了加触发词，表现是「明明有这个工具，
# 它却回一句我做不到」—— 比压根没有这个工具更让人火大，而且从日志里看不出来。

def _picked(text):
    """这句话会拿到哪些工具。（别叫 _names —— 文件开头已经有一个同名的，参数还不一样）"""
    return {sp["function"]["name"] for sp in tool_specs_for(text)}


def test_问真题要给真题工具():
    for q in ["找几道言语理解的真题", "有没有考过基尼系数", "来两道逻辑填空练练",
              "出几道类似的题"]:
        assert "search_real_questions" in _picked(q), q


def test_问考点要给讲义工具():
    for q in ["工程问题书上怎么讲的", "削弱论证有哪些方法", "资料分析的速算技巧"]:
        assert "search_basics" in _picked(q), q


def test_问最近的事要给联网工具():
    """漏掉这一组，模型会拿两年前的印象回答「最近怎么样」，而且答得很笃定。"""
    for q in ["2026 国考公告出了吗", "最近有什么时政热点", "今年省考报名什么时候",
              "帮我查一下网上怎么说"]:
        assert "web_search" in _picked(q), q


def test_问云盘要给云盘工具():
    for q in ["我云盘里有没有申论的资料", "我上传过的那个文档讲了啥"]:
        assert "list_drive" in _picked(q), q


def test_问倒计时要给倒计时工具():
    for q in ["还有多少天考试", "我的考试时间是什么时候"]:
        assert "get_exam_countdown" in _picked(q), q


def test_老的组没被新工具挤掉():
    """加组是往上叠，不是替换 —— 原来能挑到的还得挑得到。"""
    assert "list_wrong_questions" in _picked("看看我最近错的题")
    assert "search_classics" in _picked("背两句古诗")
    assert "get_today_review" in _picked("我今天该复习什么")


def test_写和删的工具从来不裁():
    """裁掉写工具 = 它突然不会做这件事了。用户明确要求时才会用到，没必要省这点 token。"""
    n = _picked("看看我最近错的题")
    for w in ("create_file", "deliver_file", "add_word", "create_note", "delete_note"):
        assert w in n, w
