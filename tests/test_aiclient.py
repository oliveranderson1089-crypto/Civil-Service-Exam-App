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
import socket
import threading
import time
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


class Test额度:
    """业务传的 max_tokens 是**正文**额度，推理段的额度由 aiclient 另外加。

    这条约束是「规划助手排不出计划」那次事故的根：全站三十多处调用方的额度都是
    照非推理的 deepseek-chat 定的（200~2000 居多），换成 v4 之后推理段一占，
    正文就是空串——而报出来的话是「AI 返回格式异常」，根本指不到额度上。
    """

    @pytest.mark.parametrize("model", ["deepseek-v4-flash", "deepseek-v4-pro",
                                       "deepseek-reasoner", "deepseek-r1", "qwen3-thinking"])
    def test_推理模型另给推理段额度(self, model):
        assert aiclient.is_reasoning(model), model
        assert aiclient.budget(model, 2000) > 2000

    @pytest.mark.parametrize("model", ["deepseek-chat", "glm-4-plus", "qwen-max"])
    def test_非推理模型的额度原样发(self, model):
        # 这些地方（智谱核验模型等）的额度是拿来兜住输出长度的，别替它加
        assert not aiclient.is_reasoning(model), model
        assert aiclient.budget(model, 600) == 600

    def test_推理段余量够装下实测峰值(self):
        """REASON_MIN 是拿 ai_calls 的账定的，不是拍的——所以别再拍小回去。

        成功调用里推理段的实际用量：fast 档最高 14140、pro 档最高 18668。
        原来定的 4000 让应用文批改（正文额度 3500 → 总额度 10500）有 13% 的调用
        把额度一口气烧干、正文一个字没出：白等 120~180 秒 + 白烧一万个 token，
        然后才由加额度重试再跑一遍。用户那头看到的就是「批改老是失败、还特别慢」。
        往宽了给不多花钱（模型写完就停），给窄了要赔上一整轮。
        """
        assert aiclient.budget("deepseek-v4-pro", 3500) - 3500 >= 18668
        assert aiclient.budget("deepseek-v4-flash", 1600) - 1600 >= 14140

    def test_额度不越过接口上限(self):
        assert aiclient.budget("deepseek-v4-pro", 300000) == aiclient.HARD_CAP
        assert aiclient.budget("deepseek-chat", 500000) == aiclient.HARD_CAP

    def test_真发出去的额度确实变大了(self, monkeypatch):
        """budget() 算对了但没接进 payload 的话，线上照样是空正文。"""
        seen = []

        def fake(c, payload, timeout):
            seen.append(payload["max_tokens"])
            return _FakeResp(_ok("ok"))

        monkeypatch.setattr(aiclient, "_open", fake)
        aiclient.chat([], cfg={"ai_model": "deepseek-v4-flash", "ai_key": "k"}, max_tokens=200)
        assert seen == [aiclient.budget("deepseek-v4-flash", 200)]


class Test调用:
    CFG = {"ai_model": "old-name", "ai_model_pro": "old-pro",
           "ai_base": "https://x.test", "ai_key": "k"}

    def test_正常返回正文(self, monkeypatch):
        monkeypatch.setattr(aiclient, "_open",
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

        def fake_open(c, payload, timeout):
            seen.append(payload["model"])
            if seen[-1] == "old-name":
                raise _http_error(400, '{"error":{"message":"Model Not Exist"}}')
            return _FakeResp(_ok("救回来了"))

        monkeypatch.setattr(aiclient, "_open", fake_open)
        assert aiclient.chat([], cfg=self.CFG) == "救回来了"
        assert seen == ["old-name", "deepseek-v4-flash"], "应当换成清单里的 fast 档重试"

    def test_retries为0也照样探活换名(self, monkeypatch):
        """自愈不该占用「网络重试」的次数。

        原来两者共用 `for attempt in range(retries+1)`，探活换名靠 continue 进下一轮——
        于是 retries=0 的调用方（find/drill 这些自己在外层管重试的）一探活就直接
        掉出循环，第三层防线等于没有：官方改名时它们照样整条链失败。
        """
        monkeypatch.setattr(aiclient, "list_models", lambda *a, **k: ["deepseek-v4-flash"])
        seen = []

        def fake(c, payload, timeout):
            seen.append(payload["model"])
            if seen[-1] == "old-name":
                raise _http_error(400, '{"error":{"message":"Model Not Exist"}}')
            return _FakeResp(_ok("救回来了"))

        monkeypatch.setattr(aiclient, "_open", fake)
        assert aiclient.chat([], cfg=self.CFG, retries=0) == "救回来了"

    def test_只探活一次不会无限换名(self, monkeypatch):
        monkeypatch.setattr(aiclient, "list_models", lambda *a, **k: ["another"])
        n = []

        def always_bad(c, payload, timeout):
            n.append(1)
            raise _http_error(400, '{"error":{"message":"model not found"}}')

        monkeypatch.setattr(aiclient, "_open", always_bad)
        with pytest.raises(urllib.error.HTTPError):
            aiclient.chat([], cfg=self.CFG)
        assert len(n) == 2, "第一次 + 探活后一次，不能再多"

    def test_读取阶段超时会重试(self, monkeypatch):
        """长任务（出题/批改）最容易撞的一种失败，原来一次抖动就整轮报废。

        坑在异常类型：**连接**阶段超时会被 urllib 包成 URLError，可**读取**阶段超时
        （"The read operation timed out"）抛的是裸的 socket.timeout —— 它是 TimeoutError
        的别名、不是 URLError 的子类，原来那条 `except urllib.error.URLError` 根本接不住。
        实测小题出题连跑 4 次有 1 次栽在这儿，整道题白出、还得从头再来一遍。
        """
        n = []

        def flaky(c, payload, timeout):
            n.append(1)
            if len(n) == 1:
                raise TimeoutError("The read operation timed out")
            return _FakeResp(_ok("第二次成功"))

        monkeypatch.setattr(aiclient, "_open", flaky)
        monkeypatch.setattr(aiclient.time, "sleep", lambda *_: None)
        assert aiclient.chat([], cfg=self.CFG) == "第二次成功"
        assert len(n) == 2, "读超时该重试一次，实际调了 %d 次" % len(n)

    def test_读取超时重试用尽后照样抛出去(self, monkeypatch):
        """能重试不等于能吞掉：一直超时就得让上层看见，而不是返回空串。"""
        def always_slow(c, payload, timeout):
            raise TimeoutError("The read operation timed out")

        monkeypatch.setattr(aiclient, "_open", always_slow)
        monkeypatch.setattr(aiclient.time, "sleep", lambda *_: None)
        with pytest.raises(TimeoutError):
            aiclient.chat([], cfg=self.CFG)

    def test_余额不足这类错误不去探活(self, monkeypatch):
        """402 跟模型名无关，探活只会白白多打一次接口、多等一轮。"""
        called = []
        monkeypatch.setattr(aiclient, "list_models",
                            lambda *a, **k: called.append(1) or [])

        def broke(c, payload, timeout):
            raise _http_error(402, '{"error":{"message":"Insufficient Balance"}}')

        monkeypatch.setattr(aiclient, "_open", broke)
        with pytest.raises(urllib.error.HTTPError):
            aiclient.chat([], cfg=self.CFG, retries=0)
        assert not called, "402 不该触发探活"

    def test_推理模型把额度吃光时报明确的错(self, monkeypatch):
        """deepseek-v4 会先产 reasoning_content。max_tokens 给小了正文就是空串，
        上游 json.loads('') 只会得到一句莫名其妙的解析失败。"""
        monkeypatch.setattr(
            aiclient, "_open",
            lambda *a, **k: _FakeResp({
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"completion_tokens_details": {"reasoning_tokens": 199}}}))
        with pytest.raises(RuntimeError, match="截断"):
            aiclient.chat([], cfg=self.CFG, max_tokens=200, retries=0)

    def test_被推理段挤空时自己加额度重试(self, monkeypatch):
        """规划助手那次事故：正文额度 2000，推理段自己就用了 2001，正文一个字没出。

        全站三十多处调用方的额度都是按非推理的 deepseek-chat 定的，不可能一处一处
        去猜推理段要烧多少，所以得让这一次调用自己爬起来——跟「官方改名了就探活换名」
        是同一条原则。
        """
        seen = []

        def fake(c, payload, timeout):
            seen.append(payload["max_tokens"])
            if len(seen) == 1:
                return _FakeResp({
                    "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                    "usage": {"completion_tokens_details": {"reasoning_tokens": 2001}}})
            return _FakeResp(_ok("这回写出来了"))

        monkeypatch.setattr(aiclient, "_open", fake)
        cfg = dict(self.CFG, ai_model="deepseek-v4-flash")
        assert aiclient.chat([], cfg=cfg, max_tokens=2000, retries=0) == "这回写出来了"
        assert len(seen) == 2, "该重试一次"
        assert seen[1] >= 2001 * 3, "加的额度要够装下实测烧掉的推理段，别只翻一点点"

    def test_加额度也不越过接口上限(self, monkeypatch):
        """超上限不是截断，是整个请求 400（deepseek-v4 实测上限 393216）。
        为了救一次截断反而把请求打成 400，是把一个能报错的问题换成一个更难查的。"""
        seen = []

        def fake(c, payload, timeout):
            seen.append(payload["max_tokens"])
            return _FakeResp({
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"completion_tokens_details": {"reasoning_tokens": 300000}}})

        monkeypatch.setattr(aiclient, "_open", fake)
        cfg = dict(self.CFG, ai_model="deepseek-v4-flash")
        with pytest.raises(RuntimeError, match="截断"):
            aiclient.chat([], cfg=cfg, max_tokens=200000, retries=0)
        assert max(seen) <= aiclient.HARD_CAP

    def test_正文写了一半的截断不加额度重试(self, monkeypatch):
        """出题/扫材料那边有 salvage，能从截断的 JSON 里把写完整的几条捞回来。
        这种情况再跑一遍只是多花一次钱，捞回来的还未必更多。"""
        n = []

        def fake(c, payload, timeout):
            n.append(1)
            return _FakeResp(_ok('{"items":[{"title":"写到一半', finish="length"))

        monkeypatch.setattr(aiclient, "_open", fake)
        cfg = dict(self.CFG, ai_model="deepseek-v4-flash")
        assert aiclient.chat([], cfg=cfg, retries=0).startswith('{"items"')
        assert len(n) == 1, "半截正文该原样交给上游 salvage，不该重试"

    def test_错误话术是给用户看的中文(self):
        assert "余额" in aiclient.error_message(_http_error(402, ""))
        assert "Key" in aiclient.error_message(_http_error(401, ""))
        assert "模型名" in aiclient.error_message(_http_error(400, ""))
        # 裸 OSError 不经 URLError 包装，漏掉的话用户看到的是
        # "AI 调用失败：[Errno 104] Connection reset by peer"
        assert "连接中断" in aiclient.error_message(ConnectionResetError(104, "reset"))

    def test_连接被RST会重试且算作网络故障(self, monkeypatch):
        """ConnectionResetError 既不是 URLError 也不是 TimeoutError。

        原来那条 `except (URLError, TimeoutError)` 接不住它，于是对端一 RST，
        这次调用**既不记账也不重试**，直接把一句英文 errno 冒到业务层。
        """
        import aimeter
        n = []

        def flaky(c, payload, timeout):
            n.append(1)
            if len(n) == 1:
                raise ConnectionResetError(104, "Connection reset by peer")
            return _FakeResp(_ok("第二次成功"))

        monkeypatch.setattr(aiclient, "_open", flaky)
        monkeypatch.setattr(aiclient.time, "sleep", lambda *_: None)
        assert aiclient.chat([], cfg=self.CFG) == "第二次成功"
        assert len(n) == 2, "RST 该重试一次"
        assert aimeter.err_kind(ConnectionResetError(104, "x")) == "network"


# ---------------------------------------------------------------- 连接阶段
class Test连接阶段:
    """「连不上」和「模型在想」必须用两份独立的预算。

    这一族盯的是 2026-08 那次线上故障：urlopen 只有一个 timeout，连接、TLS 握手、
    读取共用一份，于是握手静默卡死时，整份**读取**预算被它一个人吃光——
    AI 助手每次尝试卡满 33.4 秒（连吃 3 次 = 100 秒白等、成功率 36.7%），
    小题批改每次尝试卡满 300 秒。ai_calls 里每条 err_kind=timeout 的 elapsed_ms
    都精确等于调用方配的 timeout，一个 token 都没收到，就是这么查出来的。
    """

    CFG = {"ai_model": "deepseek-v4-flash", "ai_base": "https://x.test", "ai_key": "k"}

    @staticmethod
    def _deaf_server():
        """接了 TCP 就晾着、永不回 ServerHello —— 复现线上那句
        `_ssl.c:1063: The handshake operation timed out`。"""
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        held = []

        def loop():
            while True:
                try:
                    held.append(srv.accept()[0])
                except OSError:
                    return

        threading.Thread(target=loop, daemon=True).start()
        return srv, srv.getsockname()[1], held

    def test_握手卡死不吃读取预算(self, monkeypatch):
        """这条红了，就说明连接阶段又跟读取共用一份超时了。"""
        srv, port, _ = self._deaf_server()
        try:
            monkeypatch.setattr(aiclient, "CONNECT_TIMEOUT", 1)
            monkeypatch.setattr(aiclient, "_addrs", lambda *a, **k: ["127.0.0.1"])
            cfg = dict(self.CFG, ai_base="https://api.deepseek.com:%d" % port)
            t0 = time.time()
            with pytest.raises(urllib.error.URLError):
                # 读取预算 300 秒（批改就是这个数）：握手卡死绝不能等满 300 秒
                aiclient.chat([], cfg=cfg, retries=0, timeout=300)
            dt = time.time() - t0
        finally:
            srv.close()
        assert dt < 30, "握手卡死等了 %.1f 秒，连接阶段没有独立限时" % dt

    def test_钉IP真的生效了(self, monkeypatch):
        """`_Pinned` 稍不留神就会静默失效，那才是最坏的情况——看不出来。

        http.client 在 HTTPConnection.__init__ 里做的是
        `self._create_connection = socket.create_connection`（实例属性），
        它会把同名的**子类方法**整个盖掉。写成方法的话这里一声不响地退回普通连接，
        换 IP 自愈全部失灵，而日志上什么都看不出来。
        用一个解析不出来的域名当靶子：钉 IP 只要没生效，就会是 DNS 错误。
        """
        srv, port, held = self._deaf_server()
        try:
            conn = aiclient._Pinned("nonexistent.invalid", "127.0.0.1",
                                    port=port, timeout=1)
            with pytest.raises(OSError) as ei:
                conn.connect()          # 对端不握手，这里必然失败——要看的是它连到了哪
            assert "Name or service not known" not in str(ei.value), \
                "走了 DNS，说明钉 IP 没生效（多半是被实例属性盖掉了）"
            time.sleep(0.2)
            assert held, "本地靶子没收到连接，钉 IP 没生效"
        finally:
            srv.close()

    def test_一个IP握手卡死就换下一个(self, monkeypatch):
        """api.deepseek.com 背后挂着十几个 IP，卡死的往往只是其中一两个。

        socket.create_connection 只在**连接失败**时才往下一个地址走，握手失败不算，
        所以原来的重试次次撞在同一个坏 IP 上——线上就是连着失败三次。
        """
        tried = []

        def fake_connect(url, ip, timeout):
            tried.append(ip)
            if ip in ("1.1.1.1", "2.2.2.2"):
                raise TimeoutError("_ssl.c:1063: The handshake operation timed out")
            return _FakeConn(), "/v1/chat/completions"

        monkeypatch.setattr(aiclient, "_addrs",
                            lambda *a, **k: ["1.1.1.1", "2.2.2.2", "3.3.3.3"])
        monkeypatch.setattr(aiclient, "_connect", fake_connect)
        monkeypatch.setattr(aiclient.random, "randrange", lambda n: 0)
        assert aiclient.chat([], cfg=self.CFG, retries=0) == "换IP救回来了"
        assert tried == ["1.1.1.1", "2.2.2.2", "3.3.3.3"]

    def test_全部IP都连不上时归类为超时(self, monkeypatch):
        """包成 URLError(原异常) 才能让 err_kind 和用户话术都认出「这是超时」。"""
        import aimeter
        monkeypatch.setattr(aiclient, "_addrs", lambda *a, **k: ["1.1.1.1", "2.2.2.2"])
        monkeypatch.setattr(aiclient, "_connect", _raise_handshake_timeout)
        monkeypatch.setattr(aiclient.time, "sleep", lambda *_: None)
        with pytest.raises(urllib.error.URLError) as ei:
            aiclient.chat([], cfg=self.CFG, retries=0)
        assert aimeter.err_kind(ei.value) == "timeout"
        assert "超时" in aiclient.error_message(ei.value)

    def test_请求发出去之后不再换IP(self, monkeypatch):
        """换 IP 只在连接阶段做。请求都发出去了还闷头重发，
        「出一道题」会变成出两道、「加入错题本」会加两条。"""
        tried = []

        def fake_connect(url, ip, timeout):
            tried.append(ip)
            return _FakeConn(fail_on_request=True), "/x"

        monkeypatch.setattr(aiclient, "_addrs", lambda *a, **k: ["1.1.1.1", "2.2.2.2"])
        monkeypatch.setattr(aiclient, "_connect", fake_connect)
        monkeypatch.setattr(aiclient.time, "sleep", lambda *_: None)
        with pytest.raises(OSError):
            aiclient.chat([], cfg=self.CFG, retries=0)
        assert len(tried) == 1, "请求已发出，不该在 _open 里换 IP 重发"

    def test_地址被重定向时说清楚该改哪(self, monkeypatch):
        """urlopen 会自动跟重定向，http.client 不会。

        不单列的话，跳转页的 HTML 会被当成回复正文带到上游，报出来是
        「AI 返回格式异常」——一句指不到根因、也不知道该改哪儿的话。
        """
        class _Redir(_FakeConn):
            def getresponse(self):
                r = _FakeHTTPResp({})
                r.status = 301
                r.getheader = lambda h: "https://api.deepseek.com/v1/chat/completions"
                return r

        monkeypatch.setattr(aiclient, "_addrs", lambda *a, **k: ["1.1.1.1"])
        monkeypatch.setattr(aiclient, "_connect", lambda *a: (_Redir(), "/x"))
        with pytest.raises(RuntimeError, match="重定向"):
            aiclient.chat([], cfg=self.CFG, retries=0)

    def test_走代理时交回urllib(self, monkeypatch):
        """代理下「连哪个 IP」由代理说了算，钉 IP 没有意义还会连错地方。"""
        monkeypatch.setattr(aiclient.urllib.request, "getproxies",
                            lambda: {"https": "http://127.0.0.1:7897"})
        monkeypatch.setattr(aiclient.urllib.request, "proxy_bypass", lambda h: False)
        used = []
        monkeypatch.setattr(aiclient.urllib.request, "urlopen",
                            lambda req, **k: used.append(req.full_url) or _FakeResp(_ok("走代理")))
        monkeypatch.setattr(aiclient, "_connect",
                            lambda *a: pytest.fail("走代理时不该自己建连接"))
        assert aiclient.chat([], cfg=self.CFG, retries=0) == "走代理"
        assert used == ["https://x.test/v1/chat/completions"]


class _FakeConn:
    """假连接：握手已过，剩下发请求/读响应。"""

    def __init__(self, fail_on_request=False):
        self.sock = type("S", (), {"settimeout": lambda self, t: None})()
        self._fail = fail_on_request

    def request(self, method, path, body=None, headers=None):
        if self._fail:
            raise ConnectionResetError(104, "Connection reset by peer")

    def getresponse(self):
        return _FakeHTTPResp(_ok("换IP救回来了"))

    def close(self):
        pass


class _FakeHTTPResp:
    status, reason, msg = 200, "OK", {}

    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def close(self):
        pass


def _raise_handshake_timeout(url, ip, timeout):
    raise TimeoutError("_ssl.c:1063: The handshake operation timed out")


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
