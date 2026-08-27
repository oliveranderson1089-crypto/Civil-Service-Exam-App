"""联网搜索必须**显式**走代理，而且要能在 `NO_PROXY=*` 下走通。

2026-08-27 的真实故障，值得完整记一笔，因为它骗过了第一轮排查：
  · 用户报「搜索服务连接不上」；
  · 在终端里 `python -c "websearch.search(...)"` 一跑 —— **通的**，于是判断「底层没问题」；
  · 真相是交互式 shell 里有 `HTTP(S)_PROXY`，而 `gongkao.service` 的单元文件里写着
    `Environment=NO_PROXY=*`（AI 那几家直连更快，是有意为之）。Brave 直连不通，
    服务里于是每次都超时 —— **量错了环境，就会得出「已经修好了」这种结论**。

第二个坑套在第一个里面：光把代理传给 `ProxyHandler` 还不够。
`ProxyHandler.proxy_open` 里有一道 `proxy_bypass(host)`，`NO_PROXY=*` 会让它对所有主机
返回真，于是显式传进去的代理被**静默绕过**，请求照样直连、照样超时 ——
看起来像「代理不通」，其实代理好好的。只有 `Request.set_proxy` 不经过那道检查。

所以这里锁的不是「能不能搜到」（那要真网络），而是**请求到底有没有真的挂上代理**。
"""
import urllib.request

import pytest

from mods import websearch


@pytest.fixture(autouse=True)
def _clean_cache():
    websearch._PROXY.update(url="", at=0.0)
    yield
    websearch._PROXY.update(url="", at=0.0)


def test_配了就用配的不去猜(monkeypatch):
    monkeypatch.setattr(websearch, "CFG", {"search_proxy": "http://10.0.0.1:9999"})
    monkeypatch.setattr(websearch, "_alive", lambda *a, **k: pytest.fail("配了还去探端口"))
    assert websearch._proxy_url() == "http://10.0.0.1:9999"


def test_没配就探常见端口(monkeypatch):
    monkeypatch.setattr(websearch, "CFG", {})
    monkeypatch.setattr(urllib.request, "getproxies", dict)
    seen = []

    def alive(host, port, timeout=0.3):
        seen.append(port)
        return port == websearch.PROXY_PORTS[1]      # 第二个端口才通

    monkeypatch.setattr(websearch, "_alive", alive)
    assert websearch._proxy_url() == "http://127.0.0.1:%d" % websearch.PROXY_PORTS[1]
    assert seen[0] == websearch.PROXY_PORTS[0], "该按顺序探，先试最常用的那个"


def test_探到了要记住别每次都探一遍(monkeypatch):
    monkeypatch.setattr(websearch, "CFG", {})
    monkeypatch.setattr(urllib.request, "getproxies", dict)
    n = []
    monkeypatch.setattr(websearch, "_alive", lambda h, p, timeout=0.3: (n.append(p), True)[1])
    websearch._proxy_url()
    websearch._proxy_url()
    assert len(n) == 1, "每次搜索都重探一遍端口，等于给每次搜索加一串 TCP 超时"


def test_一个都探不到就说找不到代理(monkeypatch):
    monkeypatch.setattr(websearch, "CFG", {})
    monkeypatch.setattr(urllib.request, "getproxies", dict)
    monkeypatch.setattr(websearch, "_alive", lambda *a, **k: False)
    assert websearch._proxy_url() == ""
    req = urllib.request.Request("https://api.search.brave.com/x")
    with pytest.raises(websearch.SearchError) as e:
        websearch._open(req, 5, use_proxy=True)
    assert "代理" in str(e.value), "得说清是代理的事，别混进「没搜到」里"


def test_挂代理用的是set_proxy而不是ProxyHandler(monkeypatch):
    """这是本文件的**核心断言**。`NO_PROXY=*` 下 ProxyHandler 会被 proxy_bypass 静默绕过，
    只有 set_proxy 真的挂得上（https 走 CONNECT 隧道）。"""
    monkeypatch.setattr(websearch, "CFG", {"search_proxy": "http://127.0.0.1:7897"})
    got = {}

    def fake_open(req, timeout=None):
        got["host"] = req.host
        got["tunnel"] = getattr(req, "_tunnel_host", None)
        return "resp"

    monkeypatch.setattr(websearch._DIRECT, "open", fake_open)
    req = urllib.request.Request("https://api.search.brave.com/res/v1/web/search?q=x")
    assert websearch._open(req, 5, use_proxy=True) == "resp"
    assert got["host"] == "127.0.0.1:7897", "请求没打到代理上 —— 那就是又被 bypass 绕过去了"
    assert got["tunnel"] == "api.search.brave.com", "https 得走 CONNECT 隧道"


def test_直连那条明确不走代理(monkeypatch):
    """读网页绝大多数是国内站，直连更快；也不能被别处的环境变量顺手带去走代理。"""
    monkeypatch.setattr(websearch, "CFG", {"search_proxy": "http://127.0.0.1:7897"})
    got = {}
    monkeypatch.setattr(websearch._DIRECT, "open",
                        lambda req, timeout=None: got.update(host=req.host) or "resp")
    req = urllib.request.Request("https://www.njpta.org.cn/")
    websearch._open(req, 5, use_proxy=False)
    assert got["host"] == "www.njpta.org.cn"


def test_重试不会把代理地址再套一层(monkeypatch):
    """set_proxy 会改写 req 自身。拿同一个 req 挂第二次，host 就成了代理的代理。"""
    monkeypatch.setattr(websearch, "CFG", {"search_proxy": "http://127.0.0.1:7897"})
    hosts = []
    monkeypatch.setattr(websearch._DIRECT, "open",
                        lambda req, timeout=None: hosts.append(req.host) or "resp")
    req = urllib.request.Request("https://api.search.brave.com/x")
    websearch._open(req, 5, use_proxy=True)
    websearch._open(req, 5, use_proxy=True)
    assert hosts == ["127.0.0.1:7897", "127.0.0.1:7897"]


def test_读网页直连失败会借代理再试一次(monkeypatch):
    """国内站直连就够，但偶尔要读国外来源 —— 直连一失败就放弃等于读不了它们。"""
    monkeypatch.setattr(websearch, "CFG", {"search_proxy": "http://127.0.0.1:7897"})
    calls = []

    class R:
        headers = {"Content-Type": "text/html; charset=utf-8"}
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=None): return "<title>ok</title><p>正文</p>".encode("utf-8")

    def fake_open(req, timeout=None):
        calls.append(req.host)
        if len(calls) == 1:
            raise OSError("timed out")       # 直连那次
        return R()

    monkeypatch.setattr(websearch._DIRECT, "open", fake_open)
    title, body, cut = websearch.fetch("https://example.com/a")
    assert title == "ok" and "正文" in body
    assert calls == ["example.com", "127.0.0.1:7897"], "第二次该改走代理"
