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
import urllib.error
import urllib.parse
import urllib.request

from core import CFG, log

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
TIMEOUT = 12                # 用户盯着等，超过这个数不如早点说「没搜着」
MAX_RESULTS = 8
FETCH_MAX = 20000           # 单个网页取回的正文上限（字符）
UA = "Mozilla/5.0 (X11; Linux x86_64) gongkao-assistant/1.0"


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
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
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
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            raw = r.read(4 * 1024 * 1024)
    except Exception as e:
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
