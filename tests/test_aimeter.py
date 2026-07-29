"""AI 调用记账（aimeter.py）+ 用量报表（mods/aistats.py）。

这块的价值全在「记得准」上，所以测试盯三件事：

1. **caller 要穿透转发层**。Web 侧 18 个业务模块全经 mods/ai.py 的
   _ai_call_or_error → ai_chat 转发，不跳过它，报表上就是一坨 "ai"，
   「谁在烧钱」这个问题直接问不出答案——这是整块最容易悄悄失效的地方。
2. **记账绝不能连累 AI 调用**。库锁了、盘满了、表被删了，AI 都得照常返回。
3. **重试要记成多行**。重试是又发了一次请求、又烧了一次 token，
   按「一次调用一行」记会把成本记少。
"""
import json
import sqlite3
import urllib.error
from io import BytesIO
from unittest.mock import patch

import pytest

import aiclient
import aimeter
from conftest import DB


class _Resp(BytesIO):
    """假的 urlopen 返回值：支持 with，read() 给一段 JSON。"""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok_body(pt=100, ct=20, rt=0):
    u = {"prompt_tokens": pt, "completion_tokens": ct}
    if rt:
        u["completion_tokens_details"] = {"reasoning_tokens": rt}
    return json.dumps({"choices": [{"message": {"content": "答案"},
                                    "finish_reason": "stop"}], "usage": u}).encode()


@pytest.fixture
def meter_db():
    """每个用例从干净的 ai_calls 开始——aimeter 写的是 conftest 那个测试库。"""
    con = sqlite3.connect(DB)
    aimeter.ensure_schema(con)
    con.execute("DELETE FROM ai_calls")
    con.commit()
    yield con
    con.close()


def _rows(con):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute("SELECT * FROM ai_calls ORDER BY id")]


# ---------------------------------------------------------------- caller 探测
class Test调用方探测:
    """真实形状的栈是伪造出来的：compile() 能指定 co_filename，
    这样不用真去跑 gen_essays.py 也能验证跳过规则。"""

    def _stack(self, *layers):
        g = {"aimeter": aimeter}
        prev = None
        for fname, func in layers:
            body = ("def %s():\n    return %s()\n" % (func, prev) if prev
                    else "def %s():\n    return aimeter.caller()\n" % func)
            exec(compile(body, fname, "exec"), g)
            prev = func
        return g[prev]()

    def test_定时脚本直调(self):
        assert self._stack(("/app/aiclient.py", "chat"),
                           ("/app/gen_essays.py", "go")) == "gen_essays"

    def test_穿透mods_ai转发层(self):
        """18 个业务模块都经这条链。跳不过去的话，报表上全是 "ai"。"""
        assert self._stack(("/app/aiclient.py", "chat"),
                           ("/app/mods/ai.py", "ai_chat"),
                           ("/app/mods/ai.py", "_ai_call_or_error"),
                           ("/app/mods/find.py", "find_do")) == "find"

    def test_跳过记账模块自己(self):
        assert self._stack(("/app/aimeter.py", "rec"),
                           ("/app/aiclient.py", "chat"),
                           ("/app/mods/drill.py", "quiz")) == "drill"

    def test_探测出岔子也不抛异常(self):
        """caller() 是在 AI 调用路径上跑的，它自己绝不能成为故障源。
        （注意：pytest 下栈底总有测试文件这一帧，所以「全是被跳过的模块」
        这种栈在测试里造不出来，只能从降级路径这头验。）"""
        import sys as _sys
        with patch.object(_sys, "_getframe", side_effect=RuntimeError("no frame")):
            assert aimeter.caller() == "?"


# ---------------------------------------------------------------- 记账正确性
class Test记账:
    def test_成功调用记一行且token对得上(self, meter_db):
        with patch.object(aiclient, "_open", lambda c, p, t: _Resp(_ok_body(100, 20, 300))):
            aiclient.chat([{"role": "user", "content": "x"}], cfg={"ai_key": "k"})
        r = _rows(meter_db)
        assert len(r) == 1
        assert (r[0]["prompt_tokens"], r[0]["completion_tokens"]) == (100, 20)
        # 推理 token 必须单独一列：v4 是推理模型，混进 completion 里就看不见了
        assert r[0]["reasoning_tokens"] == 300
        assert r[0]["ok"] == 1 and r[0]["err_kind"] == ""

    def test_档位和模型名都记下来(self, meter_db):
        with patch.object(aiclient, "_open", lambda c, p, t: _Resp(_ok_body())):
            aiclient.chat([{"role": "user", "content": "x"}], tier="pro",
                          cfg={"ai_key": "k", "ai_model_pro": "m-pro"})
        r = _rows(meter_db)[0]
        assert r["tier"] == "pro" and r["model"] == "m-pro" and r["mode"] == "chat"

    @pytest.mark.parametrize("exc,kind", [
        (urllib.error.HTTPError("u", 429, "rate", {}, None), "http_429"),
        (urllib.error.HTTPError("u", 401, "auth", {}, None), "http_401"),
        (TimeoutError("read timed out"), "timeout"),
        (urllib.error.URLError("refused"), "network"),
    ])
    def test_失败按类型分桶(self, meter_db, exc, kind):
        """err_kind 的名字是报表的分组键，得稳定。"""
        def boom(c, p, t):
            raise exc
        with patch.object(aiclient, "_open", boom):
            with pytest.raises(Exception):
                aiclient.chat([{"role": "user", "content": "x"}],
                              cfg={"ai_key": "k"}, retries=0)
        r = _rows(meter_db)
        assert r and r[-1]["ok"] == 0 and r[-1]["err_kind"] == kind

    def test_超时重试记成多行(self, meter_db):
        """重试是实打实又发了一次请求。按一次调用一行记会把成本记少。"""
        def boom(c, p, t):
            raise TimeoutError("timed out")
        with patch.object(aiclient, "_open", boom):
            with pytest.raises(Exception):
                aiclient.chat([{"role": "user", "content": "x"}],
                              cfg={"ai_key": "k"}, retries=2)
        # 首次 + 2 次重试 = 3 行
        assert len(_rows(meter_db)) == 3

    def test_正文被推理段挤空要记成故障(self, meter_db):
        """HTTP 200、token 照烧、正文却是空串——本项目最难查的一类失败。
        不记的话它在报表里是一次「成功调用」，失败率永远好看。

        关键是**一次请求只记一行**：曾经记成「成本一行 + 故障一行」，
        结果 10 次 starved 报成 20 次调用 / 50% 失败率，两个数都是错的。
        """
        body = json.dumps({
            "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 0,
                      "completion_tokens_details": {"reasoning_tokens": 4000}},
        }).encode()
        with patch.object(aiclient, "_open", lambda c, p, t: _Resp(body)):
            with pytest.raises(RuntimeError, match="截断"):
                # HARD_CAP 起步，没有加额度重试的余地，直接走到最终失败
                aiclient.chat([{"role": "user", "content": "x"}], cfg={"ai_key": "k"},
                              max_tokens=aiclient.HARD_CAP)
        r = _rows(meter_db)
        assert len(r) == 1, "一次 HTTP 请求只该记一行，记两行会让调用数翻倍、失败率减半"
        # 这一行同时承担成本和故障：token 是真烧了的，但它不是一次成功调用
        assert r[0]["ok"] == 0 and r[0]["err_kind"] == "starved"
        assert r[0]["prompt_tokens"] == 10 and r[0]["reasoning_tokens"] == 4000

    def test_starved重试也是一次请求一行(self, meter_db):
        """加额度重试后成功：两次请求 = 两行，第一行 starved、第二行成功。"""
        starved_body = json.dumps({
            "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 0,
                      "completion_tokens_details": {"reasoning_tokens": 900}},
        }).encode()
        seq = [starved_body, _ok_body(10, 8)]
        with patch.object(aiclient, "_open", lambda c, p, t: _Resp(seq.pop(0))):
            out = aiclient.chat([{"role": "user", "content": "x"}], cfg={"ai_key": "k"},
                                max_tokens=100)
        assert out == "答案"
        r = _rows(meter_db)
        assert len(r) == 2
        assert (r[0]["ok"], r[0]["err_kind"]) == (0, "starved")
        assert (r[1]["ok"], r[1]["err_kind"]) == (1, "")

    def test_流式被客户端掐断要留痕(self, meter_db):
        """SSE 断连时生成器收到 GeneratorExit（继承 BaseException，两条 except
        都接不住）。不单列的话这次调用既不算成本也不算故障，在账上凭空消失。"""
        chunks = ['data: {"choices":[{"delta":{"content":"半"}}]}\n'.encode(),
                  'data: {"choices":[{"delta":{"content":"截"}}]}\n'.encode(),
                  b'data: [DONE]\n']

        class _Stream:
            def __enter__(self):
                return iter(chunks)

            def __exit__(self, *a):
                return False

        with patch.object(aiclient, "_open", lambda c, p, t: _Stream()):
            g = aiclient.stream([{"role": "user", "content": "x"}], cfg={"ai_key": "k"})
            next(g)              # 收到第一片就走人，模拟用户切走页面
            g.close()            # 触发 GeneratorExit
        r = _rows(meter_db)
        assert len(r) == 1 and r[0]["ok"] == 0 and r[0]["err_kind"] == "aborted"
        assert r[0]["mode"] == "stream"


class Test一次请求一行:
    """这个错犯过三次（aiclient.chat 的 starved、ocr_answers、vision_chat）：
    先记 ok=True 再解析响应体，解析一抛异常就为同一个请求补记一行 ok=False，
    结果调用数翻倍、失败率减半。四个记账点用同一条规矩：**成功那行等解析走完再记**。
    """

    def test_视觉响应缺字段只记一行失败(self, meter_db):
        """HTTP 200 但 JSON 里没有 choices —— 解析会炸，这仍是一次请求。"""
        from mods import ai as aimod
        import core
        core.CFG.update({"vision_base": "https://x/v4", "vision_key": "k",
                         "vision_model": "glm-4.6v", "vision_model_free": ""})
        bad = json.dumps({"usage": {"prompt_tokens": 900}}).encode()   # 没有 choices
        with patch.object(aiclient.urllib.request, "urlopen",
                          lambda req, timeout=None: _Resp(bad)):
            with pytest.raises(RuntimeError):
                aimod.vision_chat("读图", ["data:image/png;base64,AA"])
        r = _rows(meter_db)
        # 解析失败会重试，每次尝试都是一次真实请求 → 一次一行，行数 == 尝试次数
        assert len(r) == 3, "3 次尝试该记 3 行，实际 %d 行" % len(r)
        # ★ 真正要防的回归：修复前每次尝试记两行，其中一行 ok=1 —— 一次都没成功过，
        #   报表上却有成功记录，失败率直接减半。
        assert all(x["ok"] == 0 for x in r), "一次都没成功，不该有 ok=1 的行"
        # HTTP 成功、解析失败：token 是真烧了的，别丢
        assert all(x["prompt_tokens"] == 900 for x in r)

    def test_视觉正常时记成功且带token(self, meter_db):
        from mods import ai as aimod
        import core
        core.CFG.update({"vision_base": "https://x/v4", "vision_key": "k",
                         "vision_model": "glm-4.6v", "vision_model_free": ""})
        good = json.dumps({"choices": [{"message": {"content": "识别结果"}}],
                           "usage": {"prompt_tokens": 1500, "completion_tokens": 60}}).encode()
        with patch.object(aiclient.urllib.request, "urlopen",
                          lambda req, timeout=None: _Resp(good)):
            assert aimod.vision_chat("读图", ["data:image/png;base64,AA"]) == "识别结果"
        r = _rows(meter_db)
        assert len(r) == 1 and r[0]["ok"] == 1
        assert r[0]["mode"] == "vision" and r[0]["tier"] == "vision"
        assert r[0]["prompt_tokens"] == 1500


class Test记账不许连累AI:
    """这块是来观测的，不是来添乱的。"""

    def test_写库失败也不影响返回(self, meter_db):
        def broken(*a, **k):
            raise sqlite3.OperationalError("database is locked")
        with patch.object(aimeter, "_connect", broken):
            with patch.object(aiclient, "_open", lambda c, p, t: _Resp(_ok_body())):
                out = aiclient.chat([{"role": "user", "content": "x"}], cfg={"ai_key": "k"})
        assert out == "答案", "记账失败时 AI 结果必须照常返回"

    def test_关掉开关就不写(self, meter_db, monkeypatch):
        monkeypatch.setenv("GONGKAO_AI_METER", "0")
        with patch.object(aiclient, "_open", lambda c, p, t: _Resp(_ok_body())):
            aiclient.chat([{"role": "user", "content": "x"}], cfg={"ai_key": "k"})
        assert _rows(meter_db) == []


# ---------------------------------------------------------------- 报表接口
class Test用量报表:
    def test_非管理员进不来(self, flask_app):
        assert flask_app.test_client().get("/api/admin/ai/stats").status_code == 401

    def test_没有数据也给完整结构(self, auth_client, meter_db):
        """一次 AI 都没调过时，前端不该看到 500，也不该为空数据写一套分支。"""
        d = auth_client.get("/api/admin/ai/stats").get_json()
        assert d["totals"]["calls"] == 0 and d["totals"]["fail_rate"] == 0.0
        assert d["by_caller"] == [] and d["daily"] == []

    def test_按调用方排名(self, auth_client, meter_db):
        meter_db.executemany(
            "INSERT INTO ai_calls(caller,tier,model,prompt_tokens,completion_tokens,ok) "
            "VALUES(?,?,?,?,?,?)",
            [("gen_essays", "pro", "m", 1000, 500, 1),
             ("gen_essays", "pro", "m", 800, 400, 1),
             ("drill", "fast", "m", 50, 20, 1)])
        meter_db.commit()
        d = auth_client.get("/api/admin/ai/stats?win=today").get_json()
        top = d["by_caller"][0]
        assert top["key"] == "gen_essays" and top["tokens"] == 2700
        assert d["totals"]["calls"] == 3

    def test_失败率与错误分桶(self, auth_client, meter_db):
        meter_db.executemany(
            "INSERT INTO ai_calls(caller,ok,err_kind) VALUES(?,?,?)",
            [("a", 1, ""), ("a", 0, "timeout"), ("a", 0, "timeout"), ("a", 0, "http_429")])
        meter_db.commit()
        d = auth_client.get("/api/admin/ai/stats").get_json()
        assert d["totals"]["failed"] == 3 and d["totals"]["fail_rate"] == 75.0
        assert d["errors"][0] == {"kind": "timeout", "n": 2}
        assert len(d["recent_failures"]) == 3

    def test_窗口参数只认白名单(self, auth_client, meter_db):
        """天数是拼进 SQL 的，绝不能拿请求里的值去拼。"""
        d = auth_client.get("/api/admin/ai/stats?win=1;DROP TABLE ai_calls").get_json()
        assert d["win"] == "today"
        assert meter_db.execute("SELECT 1 FROM sqlite_master WHERE name='ai_calls'").fetchone()
