"""模型别名层（aiclient.py）+ 服务管理（mods/ops.py）的测试。

为什么要有这一份：2026 年 7 月 DeepSeek 把 deepseek-chat 下线，主应用当天改好了，
但 gen_quiz / crawl_news 等 8 个定时器脚本各自抄了一份
`AI_MODEL = CFG.get("ai_model") or "deepseek-chat"`，没人 import 它们，
所以没有任何测试拦得住——直到定时任务连着几天不出内容才被发现。

这里最要紧的不是 normalize 那几个单元用例，而是 `test_没有硬编码模型名`：
它盯着「真实模型名只准出现在 aiclient.py 一处」这条约束本身。
下次谁再图省事把模型名写进业务代码，这条会红。
"""
import json
import re
import urllib.error
from io import BytesIO
from pathlib import Path

import pytest

import aiclient

BASE = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- 别名解析
class Test别名与纠正:
    def test_档位映射到配置里的模型名(self):
        cfg = {"ai_model": "m-fast", "ai_model_pro": "m-pro", "ai_key": "k"}
        assert aiclient.conf("fast", cfg)["model"] == "m-fast"
        assert aiclient.conf("pro", cfg)["model"] == "m-pro"

    def test_配置缺键时用内置兜底而不是下线的名字(self):
        c = aiclient.conf("fast", {"ai_key": "k"})
        assert c["model"] == "deepseek-v4-flash"
        assert "deepseek-chat" not in c["model"]

    def test_未知档位退回fast而不是崩(self):
        cfg = {"ai_model": "m-fast", "ai_key": "k"}
        assert aiclient.conf("不存在的档位", cfg)["model"] == "m-fast"

    @pytest.mark.parametrize("old,new", [
        ("deepseek-chat", "deepseek-v4-flash"),
        ("deepseek-reasoner", "deepseek-v4-pro"),
        ("deepseek-v3", "deepseek-v4-flash"),
    ])
    def test_配置里残留下线名会就地纠正(self, old, new):
        assert aiclient.normalize(old) == new
        assert aiclient.conf("fast", {"ai_model": old, "ai_key": "k"})["model"] == new

    def test_斜杠写法纠正成连字符(self):
        # 官方用 deepseek-v4-flash；写成 deepseek/v4-flash 会被判无效模型
        assert aiclient.normalize("deepseek/v4-flash") == "deepseek-v4-flash"
        assert aiclient.normalize("deepseek/v9-pro") == "deepseek-v9-pro"

    def test_没见过的名字原样放行(self):
        # 不能自作聪明改掉用户换的第三方模型
        assert aiclient.normalize("qwen-max") == "qwen-max"
        assert aiclient.normalize("") == ""

    @pytest.mark.parametrize("base,want", [
        ("https://api.deepseek.com", "https://api.deepseek.com/v1/chat/completions"),
        ("https://api.deepseek.com/", "https://api.deepseek.com/v1/chat/completions"),
        ("https://x.cn/api/paas/v4", "https://x.cn/api/paas/v4/v1/chat/completions"),
        ("https://x.cn/v1", "https://x.cn/v1/chat/completions"),
        ("https://x.cn/v1/chat/completions", "https://x.cn/v1/chat/completions"),
    ])
    def test_接口地址补全(self, base, want):
        assert aiclient.chat_url(base) == want


class Test挑模型:
    IDS = ["deepseek-v4-flash", "deepseek-v4-pro"]

    def test_按命名习惯分档(self):
        assert aiclient.pick_model(self.IDS, "fast") == "deepseek-v4-flash"
        assert aiclient.pick_model(self.IDS, "pro") == "deepseek-v4-pro"

    def test_清单里没有对应档位时也要给出一个能用的(self):
        # 宁可档位挑偏，也不能返回空串让整条链失败
        assert aiclient.pick_model(["some-model"], "pro") == "some-model"
        assert aiclient.pick_model([], "fast") == ""


# ---------------------------------------------------------------- 调用与自愈
class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok(content="好的", finish="stop"):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}]}


def _http_error(code, body):
    return urllib.error.HTTPError("u", code, "e", {}, BytesIO(body.encode()))


class Test调用:
    CFG = {"ai_model": "old-name", "ai_model_pro": "old-pro",
           "ai_base": "https://x.test", "ai_key": "k"}

    def test_正常返回正文(self, monkeypatch):
        monkeypatch.setattr(aiclient.urllib.request, "urlopen",
                            lambda *a, **k: _FakeResp(_ok(" 答案 ")))
        assert aiclient.chat([{"role": "user", "content": "hi"}], cfg=self.CFG) == "答案"

    def test_没配Key直接报可操作的错(self):
        with pytest.raises(RuntimeError, match="AI 未配置"):
            aiclient.chat([], cfg={"ai_model": "m"})

    def test_模型名失效会探活换名重试(self, monkeypatch):
        """这条就是「官方改名后系统能不能自己爬起来」。"""
        monkeypatch.setattr(aiclient, "list_models",
                            lambda *a, **k: ["deepseek-v4-flash", "deepseek-v4-pro"])
        seen = []

        def fake_urlopen(req, **k):
            seen.append(json.loads(req.data)["model"])
            if seen[-1] == "old-name":
                raise _http_error(400, '{"error":{"message":"Model Not Exist"}}')
            return _FakeResp(_ok("救回来了"))

        monkeypatch.setattr(aiclient.urllib.request, "urlopen", fake_urlopen)
        assert aiclient.chat([], cfg=self.CFG) == "救回来了"
        assert seen == ["old-name", "deepseek-v4-flash"], "应当换成清单里的 fast 档重试"

    def test_只探活一次不会无限换名(self, monkeypatch):
        monkeypatch.setattr(aiclient, "list_models", lambda *a, **k: ["another"])
        n = []

        def always_bad(req, **k):
            n.append(1)
            raise _http_error(400, '{"error":{"message":"model not found"}}')

        monkeypatch.setattr(aiclient.urllib.request, "urlopen", always_bad)
        with pytest.raises(urllib.error.HTTPError):
            aiclient.chat([], cfg=self.CFG)
        assert len(n) == 2, "第一次 + 探活后一次，不能再多"

    def test_余额不足这类错误不去探活(self, monkeypatch):
        """402 跟模型名无关，探活只会白白多打一次接口、多等一轮。"""
        called = []
        monkeypatch.setattr(aiclient, "list_models",
                            lambda *a, **k: called.append(1) or [])

        def broke(req, **k):
            raise _http_error(402, '{"error":{"message":"Insufficient Balance"}}')

        monkeypatch.setattr(aiclient.urllib.request, "urlopen", broke)
        with pytest.raises(urllib.error.HTTPError):
            aiclient.chat([], cfg=self.CFG, retries=0)
        assert not called, "402 不该触发探活"

    def test_推理模型把额度吃光时报明确的错(self, monkeypatch):
        """deepseek-v4 会先产 reasoning_content。max_tokens 给小了正文就是空串，
        上游 json.loads('') 只会得到一句莫名其妙的解析失败。"""
        monkeypatch.setattr(
            aiclient.urllib.request, "urlopen",
            lambda *a, **k: _FakeResp({
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"completion_tokens_details": {"reasoning_tokens": 199}}}))
        with pytest.raises(RuntimeError, match="截断"):
            aiclient.chat([], cfg=self.CFG, max_tokens=200, retries=0)

    def test_错误话术是给用户看的中文(self):
        assert "余额" in aiclient.error_message(_http_error(402, ""))
        assert "Key" in aiclient.error_message(_http_error(401, ""))
        assert "模型名" in aiclient.error_message(_http_error(400, ""))


# ---------------------------------------------------------------- 全局约束
_REAL_NAME = re.compile(r"deepseek[-/](chat|coder|reasoner|r1|v\d)", re.I)
_ALLOWED = {"aiclient.py"}          # 真实模型名只准住在这儿


def _py_files():
    for p in BASE.rglob("*.py"):
        rel = p.relative_to(BASE)
        if {"node_modules", "__pycache__", ".venv", "dist", "android",
            "tests"} & set(rel.parts):
            continue
        yield rel, p.read_text(encoding="utf-8")


def _code_only(src):
    """去掉注释和文档字符串，其余照留。

    注意**不能**把字符串字面量一起去掉：要抓的正是
    `AI_MODEL = CFG.get("ai_model") or "deepseek-chat"` 这种写法，
    模型名恰恰就在字符串里，滤掉字符串这条检查就永远是绿的。

    要滤的只有「解释历史的散文」——文档字符串里正当地写着
    「deepseek-chat 当年被下线」，那是说明不是违规。用 ast 精确定位
    docstring 的行范围，而不是「这行有没有三引号」那种土办法。
    """
    import ast
    import io
    import tokenize

    doc_lines = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            doc_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT or tok.start[0] in doc_lines:
                continue
            if tok.type in (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT,
                            tokenize.DEDENT, tokenize.ENDMARKER):
                continue
            out.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError):
        return []
    return out


class Test全局约束:
    def test_没有硬编码模型名(self):
        """真实模型名只准出现在 aiclient.py。

        这是整套设计的**唯一约束**：只要它成立，官方下次再改名就只用改一处。
        注释和文档字符串里提到旧名是可以的（那是在解释历史），代码里不行。
        """
        bad = []
        for rel, src in _py_files():
            if rel.name in _ALLOWED:
                continue
            for lineno, text in _code_only(src):
                if _REAL_NAME.search(text):
                    bad.append("%s:%d  %s" % (rel, lineno, text))
        assert not bad, ("以下代码里硬编码了真实模型名，应改成 tier（fast/pro）"
                         "并让 aiclient 解析：\n" + "\n".join(bad))

    def test_这条检查本身是有效的(self):
        """守卫的守卫。

        一条永远为真的断言比没有断言更糟——它让人以为有人在看着。
        所以这里正反两面都验一次：该抓的抓得到，该放的放得过。
        """
        def hits(src):
            return [t for _, t in _code_only(src) if _REAL_NAME.search(t)]

        # 该抓：模型名写死在代码里（就是当年那 8 个脚本的写法）
        assert hits('AI_MODEL = CFG.get("ai_model") or "deepseek-chat"\n')
        assert hits('payload = {"model": "deepseek-v4-pro"}\n')
        # 该放：注释和文档字符串里讲历史
        assert not hits('"""当年 deepseek-chat 被下线。"""\nX = 1\n')
        assert not hits("X = 1  # deepseek-chat 已下线\n")
        assert not hits('def f():\n    """用 deepseek-reasoner 的那阵子。"""\n    return 1\n')

    def test_每个定时器脚本的模型都解析得出来(self):
        """光「能 import」防不住——模型名是模块级算出来的，得真取一次看值对不对。"""
        import importlib
        cfg = {"ai_model": "deepseek-v4-flash", "ai_model_pro": "deepseek-v4-pro",
               "ai_key": "k"}
        for name, tier in [("gen_quiz", "pro"), ("gen_essays", "pro"),
                           ("gen_real_explain", "pro"), ("gen_theory", "fast"),
                           ("gen_changshi", "fast"), ("gen_changkao", "fast"),
                           ("crawl_news", "fast"), ("fill_examples", "fast")]:
            m = importlib.import_module(name)
            assert getattr(m, "TIER", None) == tier, "%s 的档位应为 %s" % (name, tier)
            assert m.AI_MODEL == aiclient.conf(tier, cfg)["model"], \
                "%s 拿到的模型名和 aiclient 解析的不一致" % name

    @pytest.mark.parametrize("mod,tier,kwargs,wants_dict", [
        ("gen_quiz", "pro", {"prompt": "出题"}, True),
        ("gen_essays", "pro", {"messages": [{"role": "user", "content": "写"}],
                               "json_mode": True}, True),
        ("gen_essays", "pro", {"messages": [{"role": "user", "content": "写"}]}, False),
        ("gen_theory", "fast", {"messages": [{"role": "user", "content": "讲"}]}, True),
        ("gen_changkao", "fast", {"messages": [{"role": "user", "content": "讲"}]}, True),
        ("gen_changshi", "fast", {"messages": [{"role": "user", "content": "讲"}]}, False),
        ("fill_examples", "fast", {"content": "囫囵吞枣"}, False),
    ])
    def test_桩掉AI真跑一遍每个脚本的ai函数(self, monkeypatch, mod, tier, kwargs, wants_dict):
        """光「能 import」防不住——模型名和调用逻辑都在函数体里，import 阶段不执行。

        summarize_ai.py 当年就是这么连崩两晚的：`app.DB` 藏在 main() 里，
        导入测试全绿，定时任务每晚照崩。所以这儿桩掉 AI 真调一次每个 ai()，
        既验参数传对了（尤其是档位），也验返回类型没变。
        """
        import importlib
        m = importlib.import_module(mod)
        seen = {}

        def fake_chat(messages, **kw):
            seen.update(kw)
            seen["messages"] = messages
            return '{"items":[{"k":"v"}]}'

        monkeypatch.setattr(m.aiclient, "chat", fake_chat)
        out = m.ai(**kwargs)

        assert seen["tier"] == tier, "%s 应当用 %s 档，实际传了 %s" % (mod, tier, seen.get("tier"))
        assert seen["messages"], "%s 没把消息传下去" % mod
        assert isinstance(out, dict if wants_dict else str), \
            "%s 的返回类型变了（改造前后必须一致，否则调用方静默出错）" % mod

    def test_脚本自己重试时不叠加aiclient的重试(self):
        """两层重试都放开的话次数相乘，一个长任务能从几分钟拖成半小时。"""
        import importlib
        import inspect
        for mod in ("gen_quiz", "gen_essays", "gen_theory", "gen_changkao", "fill_examples"):
            src = inspect.getsource(importlib.import_module(mod).ai)
            assert "retries=0" in src, "%s 的 ai() 自带重试循环，调 aiclient 时要 retries=0" % mod

    def test_命题和写作走旗舰档(self):
        """出题/范文/真题解析是质量敏感的，掉到 flash 上题目会明显变差——
        这条是防「为了省钱顺手全改成 fast」。"""
        import importlib
        for name in ("gen_quiz", "gen_essays", "gen_real_explain"):
            assert importlib.import_module(name).TIER == "pro"


# ---------------------------------------------------------------- 服务管理
class Test服务管理:
    def test_单元名白名单只认本项目(self):
        from mods import ops
        ok = ["gongkao.service", "gongkao-news.timer", "gongkao-quiz.service"]
        no = ["ssh.service", "gongkaox.service", "dbus.socket",
              "gongkao.service; rm -rf /", "../../etc/passwd"]
        assert all(ops.UNIT_RE.match(n) for n in ok)
        assert not any(ops.UNIT_RE.match(n) for n in no)

    def test_show输出解析成状态行(self, monkeypatch):
        from mods import ops
        out = ("Id=gongkao-news.timer\nDescription=每日时政\nActiveState=active\n"
               "SubState=waiting\nUnitFileState=enabled\nResult=success\n"
               "LastTriggerUSec=Tue 2026-07-28 06:30:46 CST\n"
               "NextElapseUSecRealtime=Wed 2026-07-29 06:30:00 CST\n"
               "\n"
               "Id=gongkao-quiz.service\nDescription=题库生成\nActiveState=failed\n"
               "SubState=dead\nResult=exit-code\n")
        monkeypatch.setattr(ops, "_systemctl", lambda *a, **k: (0, out, ""))
        rows = {r["name"]: r for r in ops.status(["a", "b"])}

        t = rows["gongkao-news.timer"]
        assert t["kind"] == "timer" and t["healthy"] and t["running"]
        # NextElapseUSecRealtime 名字带 USec，值却是时间串——按微秒 int() 会全空
        assert t["next_run"] == "2026-07-29 06:30:00"
        assert t["last_run"] == "2026-07-28 06:30:46"

        q = rows["gongkao-quiz.service"]
        assert not q["healthy"], "Result=exit-code 必须标成不健康"

    def test_定时任务跑完的dead不算失败(self, monkeypatch):
        """oneshot 跑完就是 inactive(dead)，这是正常的。
        当成失败的话后台会满屏红，真出事反而看不见。"""
        from mods import ops
        out = ("Id=gongkao-news.service\nDescription=时政\nActiveState=inactive\n"
               "SubState=dead\nResult=success\n")
        monkeypatch.setattr(ops, "_systemctl", lambda *a, **k: (0, out, ""))
        r = ops.status(["x"])[0]
        assert r["healthy"] and not r["running"]

    def test_重启只接受已发现的单元名(self, auth_client, monkeypatch):
        """请求里的名字只用于筛选 systemd 报出来的集合，绝不拼进命令行。"""
        from mods import ops
        called = []
        monkeypatch.setattr(ops, "discover", lambda: ["gongkao-news.timer"])
        monkeypatch.setattr(ops, "self_unit", lambda: "gongkao.service")
        monkeypatch.setattr(ops, "_systemctl",
                            lambda *a, **k: (called.append(a), (0, "", ""))[1])

        r = auth_client.post("/api/admin/services/restart",
                             json={"names": ["ssh.service", "gongkao-news.timer"]})
        assert r.status_code == 200
        assert list(r.get_json()["results"]) == ["gongkao-news.timer"]
        assert not any("ssh.service" in a for a in called), "白名单外的单元被放进去了"

    def test_全是非法名时拒绝而不是变成全部重启(self, auth_client, monkeypatch):
        """names 给了但一个都没匹配上，绝不能退化成「重启全部」。"""
        from mods import ops
        monkeypatch.setattr(ops, "discover", lambda: ["gongkao-news.timer"])
        r = auth_client.post("/api/admin/services/restart", json={"names": ["ssh.service"]})
        assert r.status_code == 400

    def test_非管理员摸不到运维接口(self, client):
        assert client.get("/api/admin/services").status_code in (401, 403)
        assert client.post("/api/admin/services/restart", json={"all": True}).status_code in (401, 403)
