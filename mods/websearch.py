"""联网搜索 + 读网页正文。

用的是 DeepSeek，**它自己不带联网**，所以搜索这件事得我们做。两个动作分开：
search 只给标题和摘要，模型光看摘要照样会编，所以必须配一个 fetch 能把正文读回来。

后端可插拔（provider）：现在只接了 Brave（config.json 的 search_provider/search_key），
将来换别家只改这个文件。**没配 key 就老实说没配**，绝不许悄悄退回「拿训练记忆当搜索
结果」——那比搜不到糟得多：用户以为这是刚查的，其实是模型两年前记下的。

网络这一层单独说一句：这台机器的出网状态时好时坏（代理端口会变）。所以要把
「搜不到结果」和「根本连不上」分开报，前者是事实，后者是环境问题，用户的处置完全不同。
"""
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from core import CFG, log

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
TIMEOUT = 12                # 用户盯着等，超过这个数不如早点说「没搜着」
MAX_RESULTS = 8
FETCH_MAX = 20000           # 单个网页取回的正文上限（字符）
UA = "Mozilla/5.0 (X11; Linux x86_64) gongkao-assistant/1.0"

# ---------------------------------------------------------------- 代理
# **Brave 在这台机器上直连不通**，必须走代理。而服务单元写死了 `NO_PROXY=*`
# （AI 那几家直连更快也更稳，见 aiclient._via_proxy 的注释），所以靠环境变量是指望不上的：
# 环境变量恰恰被那一行关掉了。
#
# 这正是 2026-08-27「联网搜索连不上」的真相 —— 而且它骗过了第一轮排查：在终端里手跑
# `python -c "websearch.search(...)"` 是**通的**，因为交互式 shell 里有 HTTP(S)_PROXY；
# 服务进程里没有。**测这一路必须清掉代理变量、或者直接打服务的接口**，
# 否则量到的是自己 shell 的网络，不是服务的。
#
# 端口会变（见记忆「网络代理环境」），所以不写死：配了 search_proxy 就用配的，
# 没配就按常见端口探一遍，探到哪个用哪个并记住；失效了再探。
PROXY_PORTS = (7897, 7890, 7891, 10808, 10809, 1080, 8080)
_PROXY = {"url": "", "at": 0.0, "ttl": 300}


def _alive(host, port, timeout=0.3):
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def _proxy_url(force=False):
    """找一个能用的本机代理。找不到返回空串（调用方据此报「连不上」）。"""
    cfg = (CFG.get("search_proxy") or "").strip()
    if cfg:
        return cfg                      # 管理员明确配了就照办，不去猜
    now = time.time()
    if not force and _PROXY["url"] and now - _PROXY["at"] < _PROXY["ttl"]:
        return _PROXY["url"]
    # 环境里有就先信环境（终端手跑脚本的场景），再退回探端口
    env = (urllib.request.getproxies().get("https")
           or urllib.request.getproxies().get("http") or "")
    cands = ([env] if env else []) + ["http://127.0.0.1:%d" % p for p in PROXY_PORTS]
    for u in cands:
        sp = urllib.parse.urlsplit(u if "://" in u else "http://" + u)
        if sp.hostname and _alive(sp.hostname, sp.port or 80):
            _PROXY.update(url=u, at=now)
            log.debug("联网搜索走代理 %s", u)
            return u
    _PROXY.update(url="", at=now)
    return ""


# ProxyHandler({}) = 明确不走代理，免得别处的环境变量把这一路带跑
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _open(req, timeout, use_proxy):
    """发请求。use_proxy=True 时**显式**挂代理。

    为什么用 `req.set_proxy` 而不是 `ProxyHandler({"https": …})`：
    `ProxyHandler.proxy_open` 里有一道 `proxy_bypass(req.host)` 检查，而服务单元设的
    `NO_PROXY=*` 会让它对**所有**主机返回真 —— 于是显式传进去的代理被静默绕过，
    请求照样直连、照样超时。**这个坑看起来像「代理不通」，其实代理好好的**：
    端口探活是通的、curl 走同一个代理 6 秒就回来了，只有 urllib 这条路在空转。
    `set_proxy` 不经过那道检查（https 会走 CONNECT 隧道），才是真的挂上了。
    """
    if not use_proxy:
        return _DIRECT.open(req, timeout=timeout)
    p = _proxy_url()
    if not p:
        raise SearchError("这台机器上找不到可用的代理（搜索服务直连不通）。"
                          "请在后台把 search_proxy 配成你的代理地址，或先把代理开起来")
    sp = urllib.parse.urlsplit(p if "://" in p else "http://" + p)
    # 每次新建一份 Request：set_proxy 会改写 req 自身（_tunnel_host / host），
    # 拿同一个 req 重试第二次就会把代理地址当成目标主机再套一层。
    r2 = urllib.request.Request(req.full_url, data=req.data, headers=dict(req.header_items()),
                                method=req.get_method())
    r2.set_proxy("%s:%d" % (sp.hostname, sp.port or 80), sp.scheme or "http")
    return _DIRECT.open(r2, timeout=timeout)


class SearchError(RuntimeError):
    """区别于「没有结果」：这是**没能去搜**（没配 key / 连不上 / 被限流）。"""


def configured():
    return bool((CFG.get("search_key") or "").strip())


def _provider():
    return (CFG.get("search_provider") or "brave").strip().lower()


def search(query, count=5):
    """返回 [{title, url, snippet, age}]。搜不到就返回空表；去不了就抛 SearchError。"""
    q = (query or "").strip()
    if not q:
        return []
    if not configured():
        raise SearchError("还没配搜索服务的 key（后台 → AI 设置里的 search_key）")
    if _provider() != "brave":
        raise SearchError("不认识的搜索后端：%s" % _provider())
    n = max(1, min(int(count or 5), MAX_RESULTS))
    url = BRAVE_URL + "?" + urllib.parse.urlencode(
        {"q": q, "count": n, "country": "cn", "search_lang": "zh-hans"})
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "X-Subscription-Token": (CFG.get("search_key") or "").strip(),
        "User-Agent": UA})
    try:
        with _open(req, TIMEOUT, use_proxy=True) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
    except SearchError:
        raise                            # 「找不到代理」这类已经是人话，别再包一层
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")[:200]
        except Exception:
            pass
        if e.code in (401, 403):
            raise SearchError("搜索服务拒绝了这个 key（%d）：%s" % (e.code, body))
        if e.code == 429:
            raise SearchError("搜索服务限流了（429），过一会儿再试")
        raise SearchError("搜索服务返回 %d：%s" % (e.code, body))
    except Exception as e:
        # 代理可能刚换了端口（这台机器上是常事）。重探一次再来，还不行才认输 ——
        # 否则用户得等下一个 TTL 到期，中间每次搜索都白等一个超时。
        try:
            if _proxy_url(force=True):
                with _open(req, TIMEOUT, use_proxy=True) as r:
                    data = json.loads(r.read().decode("utf-8", "ignore"))
            else:
                raise e
        except SearchError:
            raise
        except Exception:
            # 连不上 ≠ 没搜到。这台机器出网状态时好时坏，两者的处置完全不同
            raise SearchError("连不上搜索服务（%s）—— 多半是这台机器的网络/代理问题" % e)
    out = []
    for it in ((data.get("web") or {}).get("results") or [])[:n]:
        out.append({"title": (it.get("title") or "")[:200],
                    "url": it.get("url") or "",
                    "snippet": re.sub(r"<[^>]+>", "", it.get("description") or "")[:400],
                    "age": it.get("age") or ""})
    return out


_TAG = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")
_BR = re.compile(r"(?i)</(p|div|li|h[1-6]|tr|br)\s*>|<br\s*/?>")


def fetch(url):
    """把一个网页读成纯文本。返回 (标题, 正文, 是否截断)。

    只做最土的标签剥离：装 readability 之类是另一条依赖，而这里的用途是给模型看
    个大概 —— 剥不干净的边角料它自己会忽略。
    """
    u = (url or "").strip()
    if not re.match(r"^https?://", u, re.I):
        raise SearchError("只支持 http/https 链接")
    req = urllib.request.Request(u, headers={"User-Agent": UA,
                                             "Accept-Language": "zh-CN,zh;q=0.9"})
    # 读网页跟搜索不一样：绝大多数是国内站（公告原文），**直连更快**，
    # 走代理反而绕一圈。所以先直连，不成再借代理试一次（国外站才需要）。
    try:
        with _open(req, TIMEOUT, use_proxy=False) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            raw = r.read(4 * 1024 * 1024)
    except Exception as e:
        try:
            with _open(req, TIMEOUT, use_proxy=True) as r:
                ctype = (r.headers.get("Content-Type") or "").lower()
                raw = r.read(4 * 1024 * 1024)
        except Exception:
            raise SearchError("打不开这个网页（%s）" % e)
    if "html" not in ctype and "text" not in ctype:
        raise SearchError("这个链接不是网页（%s）" % (ctype or "未知类型"))
    m = re.search(r"charset=([\w-]+)", ctype)
    html = raw.decode(m.group(1) if m else "utf-8", "ignore")
    title = ""
    mt = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if mt:
        title = re.sub(r"\s+", " ", mt.group(1)).strip()[:200]
    body = _TAG.sub(" ", html)
    body = _BR.sub("\n", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"')):
        body = body.replace(a, b)
    body = re.sub(r"[ \t　]+", " ", body)
    body = re.sub(r"\n\s*\n\s*", "\n\n", body).strip()
    log.debug("读网页 %s → %d 字", u, len(body))
    return title, body[:FETCH_MAX], len(body) > FETCH_MAX
