#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 模型的**唯一真源**：别名解析 + 下线名纠正 + 调用。

为什么单独一个顶层模块、且只用标准库：
mods/ai.py 走 `from core import CFG`，core.py 要 flask + pypinyin。而 gen_quiz.py
这类定时器脚本是脱离 Flask 跑的，import 不动 core。结果就是它们各抄了一份
`AI_MODEL = CFG.get("ai_model") or "deepseek-chat"` + 一份 HTTP 调用——2026 年 7 月
DeepSeek 把 deepseek-chat 下线时，主应用改完了，这 8 个脚本还在原地。
所以真源必须零依赖，两边才都能 import。

**业务代码永远不写真实模型名**，只说档位（tier）：
    fast — 提取/解读/查询/抓取，便宜够用
    pro  — 命题/写作/批改/定标尺，质量敏感
档位 → 真名的映射在 config.json（ai_model / ai_model_pro），后台可改、改完即生效。

三层防线，对付「官方又改名了」：
  1. 别名层：业务只认 tier，换名只动配置一处。
  2. 纠正层：配置里若残留已下线/写错的名（deepseek-chat、带斜杠的
     deepseek/v4-flash），resolve() 当场归一化，不等 400。
  3. 探活层：真撞上 400 invalid model，拉一次 /v1/models 拿官方现有清单，
     选最像的重试——本次调用自己救回来，并在日志里写清楚该去后台改成什么。
     只在内存里纠正，不回写 config.json：Web 和 8 个脚本可能同时在跑，
     并发写配置文件的风险远大于每进程多一次 GET 的成本。

**额度也归这儿管**：业务传的 max_tokens 一律当「正文额度」，推理模型要烧的
reasoning_content 由 budget() 另外加，截断了还会自己加额度重试一次。理由见下面
REASON_MIN 那一段——三十多处调用方各自去猜推理段要多少 token 是不现实的。

**连接阶段也归这儿管**：见下面 CONNECT_TIMEOUT 那一段——「连不上」和「模型在想」
必须用两份独立的预算，混成一个数是本文件历史上最贵的一个 bug。
"""
import http.client
import io
import json
import os
import random
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import aimeter          # 记账，同样零依赖（只标准库）；出岔子也只是少一行账，见 aimeter.record

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))

DEFAULT_BASE = "https://api.deepseek.com"

# 档位 → (config.json 的键, 内置兜底真名)。兜底只在配置缺键时用，跟着官方现名走。
TIERS = {
    "fast": ("ai_model", "deepseek-v4-flash"),
    "pro":  ("ai_model_pro", "deepseek-v4-pro"),
}

# 已下线/写错的名 → 现名。配置里读到这些就地换掉，不让它发出去换一个 400。
# 官方再下线新名时，往这儿加一行即可，全站（含定时器脚本）一起生效。
LEGACY = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-coder": "deepseek-v4-flash",
    "deepseek-v3": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
    "deepseek-r1": "deepseek-v4-pro",
}


def _log(msg):
    """脚本里没有 Flask 的 log，统一打到 stderr，systemd 会收进 journal。"""
    sys.stderr.write("[aiclient] %s\n" % msg)
    sys.stderr.flush()


def load_cfg():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def normalize(name):
    """把模型名归一化成官方现在认的写法。

    两类脏数据：一是已下线的旧名（deepseek-chat）；二是写成
    `deepseek/v4-flash` 的斜杠版——官方用的是连字符，斜杠会被判无效模型。
    """
    n = (name or "").strip()
    if not n:
        return n
    if n in LEGACY:
        _log("模型 %s 已下线，自动改用 %s（请到「后台 → AI 设置」改掉）" % (n, LEGACY[n]))
        return LEGACY[n]
    # deepseek/v4-flash → deepseek-v4-flash
    if re.fullmatch(r"deepseek/v\d+-\w+", n):
        fixed = n.replace("/", "-", 1)
        _log("模型名 %s 写法有误（官方用连字符），自动改用 %s" % (n, fixed))
        return fixed
    return n


# ---------------------------------------------------------------- 服务级档位覆盖（管理员控成本）
# config.json 的 ai_tiers：{"服务": "fast|pro|"}，空串/缺席 = 跟随代码里写的默认档。
# 为什么放在这一层而不是去改各业务的调用点：调用点有三十多处、还分散在 13 个
# 没人 import 的定时器脚本里（见 [[gongkao-timer-scripts]] 那次事故）。档位是
# 「成本旋钮」，旋钮只该有一个，而全站唯一都要经过的地方就是这儿。
OVERRIDE_KEY = "ai_tiers"

# 键的三种写法，按这个顺序取第一个命中的（精确的赢）：
#   "write:pro"  只改这个服务里**本来走 pro** 的那些调用（降级批改但不动它的提取）
#   "write"      这个服务的全部调用
#   "*"          全站兜底（一键省钱模式）
def _override(who, tier, cfg, key, allowed):
    ov = (cfg or {}).get(key)
    if not isinstance(ov, dict):
        return ""
    for k in ("%s:%s" % (who, tier), who, "*"):
        v = ov.get(k)
        v = v.strip().lower() if isinstance(v, str) else ""
        if v in allowed:
            return v
    return ""


def _resolve(tier, cfg, who, key, allowed):
    if who == "":
        return tier
    c = cfg if cfg is not None else load_cfg()
    return _override(who if who is not None else aimeter.caller(), tier, c, key, allowed) or tier


def effective_tier(tier="fast", cfg=None, who=None):
    """业务要的档位 → 管理员实际允许的档位。

    who=None 表示自己顺调用栈找发起方（跟记账用的是同一套口径，所以后台报表里
    看到的服务名，和这里能设置的服务名天然对得上）；who="" 表示不查覆盖——
    「当前配的是哪个模型」这类**展示**用途要的是原样，不能被覆盖染色。
    """
    return _resolve(tier, cfg, who, OVERRIDE_KEY, TIERS)


# ---------------------------------------------------------------- 视觉模型的同款旋钮
# 读图走的是另一家（智谱，配置在 vision_* 那几个键），但「成本旋钮」的道理一样，
# 所以键的形状、优先级、清除方式都跟上面一致，后台一页管两家。
#   free —— 免费的 flash 档优先，读图/OCR 够用（vision_chat 会在它失败时自己退到旗舰）
#   pro  —— 直接上旗舰，图形推理这类硬任务用
# 真实模型名不在这儿：视觉那两个名字住在 mods/ai.py 的 _vision_conf，这里只管档位。
VISION_KEY = "ai_vision_tiers"
VISION_TIERS = ("free", "pro")


def effective_vision(prefer="free", cfg=None, who=None):
    return _resolve(prefer if prefer in VISION_TIERS else "free",
                    cfg, who, VISION_KEY, VISION_TIERS)


def conf(tier="fast", cfg=None, who=None):
    """解析出一次调用需要的全部东西：接口地址、真实模型名、Key。

    默认会应用管理员在后台设的服务级档位覆盖（who 的含义见 effective_tier）。
    脚本里 `_AI = aiclient.conf(TIER, CFG)` 这种模块级常量也因此自动跟随——
    它们是每次定时唤醒新起的进程，读的就是当时的配置。
    """
    c = cfg if cfg is not None else load_cfg()
    tier = effective_tier(tier, c, who)
    key, fallback = TIERS.get(tier) or TIERS["fast"]
    base = (c.get("ai_base") or DEFAULT_BASE).rstrip("/")
    model = normalize(c.get(key) or "") or fallback
    return {
        "base": base,
        "url": chat_url(base),
        "model": model,
        "tier": tier,
        "key": c.get("ai_key") or os.environ.get("GONGKAO_AI_KEY", ""),
    }


def chat_url(base):
    """接口地址补全成 /v1/chat/completions。用户在后台可能只填到域名或 /v1。"""
    b = (base or DEFAULT_BASE).rstrip("/")
    if b.endswith("/chat/completions"):
        return b
    if b.endswith("/v1"):
        return b + "/chat/completions"
    return b + "/v1/chat/completions"


def configured(cfg=None):
    return bool(conf("fast", cfg, who="")["key"])


# ---------------------------------------------------------------- 探活：官方现在到底有哪些模型
_models_cache = {"at": 0.0, "ids": []}


def list_models(cfg=None, timeout=20, ttl=300):
    """GET /v1/models 拿官方现有清单。带 5 分钟缓存，别在重试里反复拉。"""
    now = time.time()
    if _models_cache["ids"] and now - _models_cache["at"] < ttl:
        return _models_cache["ids"]
    c = conf("fast", cfg, who="")
    if not c["key"]:
        return []
    url = c["base"] + ("/models" if c["base"].endswith("/v1") else "/v1/models")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + c["key"]})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        ids = [m.get("id") for m in (d.get("data") or []) if m.get("id")]
    except Exception as e:
        _log("拉取模型清单失败：%s" % e)
        return []
    _models_cache.update(at=now, ids=ids)
    return ids


def pick_model(ids, tier):
    """从官方清单里挑一个当前档位该用的。

    规则按「官方一贯的命名习惯」来，不是猜：轻量档带 flash/lite/mini/turbo，
    旗舰档带 pro/max/plus，其余按名字排序取最后一个（版本号大的通常在后）。
    挑不准也没关系——挑错顶多质量档位偏一点，总好过整条任务链直接失败。
    """
    if not ids:
        return ""
    light = [i for i in ids if re.search(r"flash|lite|mini|turbo|air", i, re.I)]
    heavy = [i for i in ids if re.search(r"pro|max|plus|ultra", i, re.I)]
    pool = (light or ids) if tier == "fast" else (heavy or ids)
    return sorted(pool)[-1]


# ---------------------------------------------------------------- 额度：正文 vs 推理段
# max_tokens 的合法上限。实测 2026-07-28（`aiclient.py` 直接打接口测的）：
# deepseek-v4-flash 和 deepseek-v4-pro 都是 [1, 393216]，超了不是截断，是整个请求 400。
# 代码里几处注释写的「上限 8192」是 deepseek-chat 时代的旧数，别再照着它定额度。
HARD_CAP = 393216

# 推理模型：reasoning_content 和正文**共吃** max_tokens。实测让 v4-flash「回一个字」
# 都要烧掉 80~180 个推理 token；业务里那些按非推理的 deepseek-chat 定的 200~2000，
# 推理段一占就把正文挤成空串（规划助手给了 2000，推理段自己就用掉 2001）。
_REASONING = re.compile(r"(?:^|[-_/])(?:v[4-9]\d*|r1|reasoner|think\w*)", re.I)

# 推理段起码留 REASON_MIN；正文额度大的任务（出题、扫材料）推理通常也更长，
# 所以再按倍数放。**max_tokens 是上限不是花销**：给宽了不会多花钱（模型该写多长
# 写多长），给窄了正文直接是空串。所以这里一律往宽了给。
#
# REASON_MIN 原来是 4000，**定小了**——这句话是 ai_calls 的账算出来的，不是拍的：
# 成功调用里推理段的实际用量，fast 档最高 14140、pro 档最高 18668；而应用文批改
# （max_tokens=3500 → 额度 10500）有 13% 的调用把 10500 一口气烧干、正文一个字没出。
# 代价不是"截断"这么轻：每次 starved 都是白等 120~180 秒 + 白烧一万个 token，
# 然后才由下面的加额度重试再跑一遍，用户看到的就是"批改老是失败、还特别慢"。
# 24000 覆盖实测峰值还留三成余量。往宽了给不多花一分钱（模型写完就停），
# 而给窄了要赔上一整轮的时间和 token——这买卖是单向的。
REASON_MIN = 24000
REASON_RATIO = 2


def is_reasoning(model):
    """这个模型会不会先产 reasoning_content。认不出也不要紧：chat() 撞上截断会自己加额度重试。"""
    return bool(_REASONING.search(model or ""))


def budget(model, max_tokens):
    """把业务给的「正文额度」换算成真正要发出去的 max_tokens。"""
    mt = max(1, int(max_tokens or 1))
    if not is_reasoning(model):
        return min(HARD_CAP, mt)
    return min(HARD_CAP, mt + max(REASON_MIN, REASON_RATIO * mt))


def _starved(d):
    """判断这次响应是不是「推理段吃光额度、正文一个字没出」。返回 (是否, 推理段 token 数)。

    只认 finish_reason=length 且正文空、也没有 tool_calls 的情况：正文写了一半被截断，
    上游各自有 salvage 能捞；tool_calls 有值说明模型是去调工具了，不是被饿死。
    """
    ch = (d.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    if ch.get("finish_reason") != "length":
        return False, 0
    if (msg.get("content") or "").strip() or msg.get("tool_calls"):
        return False, 0
    rt = (d.get("usage", {}).get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    return True, rt


# ---------------------------------------------------------------- 连接阶段：连不上 ≠ 模型在想
# 业务传的 timeout 是**读取**预算（"模型最多可以想多久"），批改类给到 300 秒。
# 可 urllib.request.urlopen 只认一个 timeout：连接、TLS 握手、读取共用这一份。
# 于是线上故障全长一个样（2026-07 的账查出来的，ai_calls 里每一条 err_kind=timeout
# 的 elapsed_ms 都**精确等于**调用方配的 timeout，一个 token 都没收到）：
#     journal: URLError(TimeoutError('_ssl.c:1063: The handshake operation timed out'))
#     · AI 助手  每次尝试卡满 33.4 秒（=100 秒预算 ÷ 3 次），连吃 3 次 = 100 秒白等
#     · 小题批改 每次尝试卡满 300 秒，用户对着转圈等 5 分钟，最后一句"超时"
# TCP 是通的（实测 12 个 IP 全部 0.05~0.11 秒握完手），是握手静默卡死。
# 也就是说：整份读取预算被**握手**一个人吃光了，而握手根本用不了那么久。
#
# 所以连接阶段单独给一份小预算，并且失败了**换一个 IP** 再来——api.deepseek.com
# 背后挂着十几个 IP，卡死的往往只是其中一两个，而 socket.create_connection 一旦
# TCP 连上就不会再换地址了（它只在**连接失败**时才往下一个走，握手失败不算）。
# 原来的重试次次撞在同一个 IP 上，所以才会一连失败三次。
CONNECT_TIMEOUT = 8         # 实测握手 0.05~0.11 秒，8 秒是 70 倍余量；卡死的一秒也等不出结果
# 读取阶段同样有两个口径，混用一个数是 2026-08 那批超时的直接原因：
#   · 等**第一个字节** —— 正常 1~3 秒。等久了不是「模型在想」，是这条 TCP 已经死了。
#   · 等**下一片** —— 已经在吐字了，模型写长文本时片与片之间空几十秒是正常的。
# 以前两者共用一个 40 秒：既没能早点发现死连接（要等满 40 秒才重试，重试完预算也没了），
# 又只比「最慢的一次成功」（实测 34.5 秒）高 16%，稍慢一点的正常回答直接被误杀。
FIRST_BYTE_TIMEOUT = 12     # 12 秒还没有第一个字节 → 判定这条连接死了，换一条重来
CONNECT_TRIES = 3           # 最坏 24 秒，仍远小于任何一处的读取预算

_addr_cache = {"host": "", "at": 0.0, "ips": []}


def _addrs(host, port, ttl=60):
    """域名背后的 IP 列表，缓存 60 秒。解析不出来就返回空，退回让系统自己选。"""
    now = time.time()
    if _addr_cache["host"] == host and _addr_cache["ips"] and now - _addr_cache["at"] < ttl:
        return _addr_cache["ips"]
    try:
        ips = sorted({i[4][0] for i in
                      socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    except Exception as e:
        _log("解析 %s 失败：%s" % (host, e))
        return []
    if ips:
        _addr_cache.update(host=host, at=now, ips=ips)
    return ips


class _Pinned(http.client.HTTPSConnection):
    """连到指定 IP，但 SNI 和证书校验照旧按域名走——换 IP 不能换成不验证书。

    **必须在 __init__ 里覆盖实例属性**，不能写成子类方法：http.client 在
    HTTPConnection.__init__ 里做的是 `self._create_connection = socket.create_connection`
    （3.14 的 http/client.py:908），实例属性会把同名的子类方法整个盖掉。
    写成方法的话这里一声不响地退回普通连接——钉 IP 全部失效，而且看不出来。
    """

    def __init__(self, host, ip, **kw):
        super().__init__(host, **kw)
        self._create_connection = (
            lambda address, timeout, source_address:
            socket.create_connection((ip, address[1]), timeout, source_address))


def _retime(r, sec):
    """把这条响应底下 socket 的读超时改成 sec，返回改没改成。

    用途只有一个：收到第一个字节之后，把「等首字节」那份小超时换成「等下一片」那份
    大超时。找不到 socket 就当没发生 —— 超时仍然是开着的，只是还用着旧的那份，
    行为不比改之前差。
    """
    for path in (("fp", "raw", "_sock"), ("fp", "_sock"), ("_sock",)):
        o = r
        try:
            for a in path:
                o = getattr(o, a)
            o.settimeout(sec)
            return True
        except Exception:
            continue
    return False


class _Resp:
    """响应 + 它底下那条连接。只 close 响应的话 socket 要留到 GC 才释放，
    而流式那条一次对话能开四五次连接。`with _open(...) as r` 拿到的是响应本身。"""

    def __init__(self, r, conn):
        self.r, self.conn = r, conn

    def __enter__(self):
        return self.r

    def __exit__(self, *exc):
        try:
            self.r.close()
        finally:
            self.conn.close()
        return False


def _via_proxy(url):
    """这个地址是不是要走代理。走代理就交回 urllib——代理下「连哪个 IP」由代理说了算，
    我们钉 IP 没有意义。服务和定时器都是直连（NO_PROXY=*），只有人在终端里手跑脚本
    才会撞上代理。"""
    p = urllib.parse.urlsplit(url)
    if not urllib.request.getproxies().get(p.scheme):
        return False
    try:
        return not urllib.request.proxy_bypass(p.hostname)
    except Exception:
        return True


def _connect(url, ip, timeout):
    """建连接（TCP + TLS 都在 timeout 之内），返回 (连接, 请求路径)。"""
    p = urllib.parse.urlsplit(url)
    port = p.port or (443 if p.scheme == "https" else 80)
    if p.scheme != "https":
        conn = http.client.HTTPConnection(p.hostname, port, timeout=timeout)
    elif ip:
        conn = _Pinned(p.hostname, ip, port=port, timeout=timeout)
    else:
        conn = http.client.HTTPSConnection(p.hostname, port, timeout=timeout)
    conn.connect()
    return conn, (p.path or "/") + (("?" + p.query) if p.query else "")


def _open(c, payload, timeout):
    """发出去并拿到响应对象。流式那条要边读边处理，不能像 chat() 那样一口气 read()，
    所以建请求这段得单独拎出来给两边共用。

    timeout 只管**读取**：连接和握手用上面那份小预算，失败就换 IP 重来。
    换 IP 只在连接阶段做——请求一旦发出去，重不重试是 chat()/stream() 的事，
    在这儿闷头重发会把「出一道题」变成出两道。
    """
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer " + c["key"]}
    if _via_proxy(c["url"]):
        req = urllib.request.Request(c["url"], data=body, method="POST", headers=headers)
        return urllib.request.urlopen(req, timeout=timeout)

    p = urllib.parse.urlsplit(c["url"])
    ips = _addrs(p.hostname, p.port or 443) or [None]
    # 随机起点：13 个定时器脚本几乎同时醒来，都从 ips[0] 开始的话，
    # 坏的那个 IP 会被所有进程一起撞上。
    start = random.randrange(len(ips))
    # 连接阶段整体也别超过调用方那份读取预算：对话那条只给 33 秒，
    # 花 24 秒在连接上就没时间听回答了。批改那种 300 秒的取不到这个下限。
    ct = max(2.0, min(CONNECT_TIMEOUT, (timeout or CONNECT_TIMEOUT) / CONNECT_TRIES))
    last = None
    for k in range(min(CONNECT_TRIES, len(ips))):
        ip = ips[(start + k) % len(ips)]
        try:
            conn, path = _connect(c["url"], ip, ct)
        except OSError as e:            # TimeoutError / ssl.SSLError 都是 OSError 的子类
            last = e
            more = k + 1 < min(CONNECT_TRIES, len(ips))
            _log("连 %s 失败（%s）%s" % (ip or p.hostname, e,
                                        "，换个 IP 重来" if more else "，没有别的 IP 可换了"))
            continue
        # 握手过了，剩下的路交给调用方那份长得多的读取预算
        conn.sock.settimeout(timeout)
        try:
            conn.request("POST", path, body=body, headers=headers)
            r = conn.getresponse()
        except Exception:
            conn.close()
            raise
        if 300 <= r.status < 400:
            # urlopen 会自动跟重定向，http.client 不会。不单列的话，跳转页的 HTML
            # 会被当成回复正文一路带到上游，报出来是「AI 返回格式异常」——查不到根因。
            # 后台的接口地址是人手填的，把 https 写成 http、或域名少一段都会跳转。
            loc = r.getheader("Location") or "别处"
            r.read()
            conn.close()
            raise RuntimeError("AI 接口地址 %s 被重定向到 %s（常见于 https 写成了 http）；"
                               "请到「后台 → AI 设置」把地址直接填成最终地址"
                               % (c["url"], loc))
        if r.status >= 400:
            # body 当场读干净再关连接：HTTPError 的 fp 只能读一次，_detail() 在上层等着它。
            detail = r.read()
            conn.close()
            raise urllib.error.HTTPError(c["url"], r.status, r.reason, r.msg,
                                         io.BytesIO(detail))
        return _Resp(r, conn)
    # 包成 URLError(原异常) —— 跟 urlopen 原来抛的形状一致，上层那几处
    # `except (URLError, TimeoutError)` 和 aimeter.err_kind 的超时判定都不用改。
    raise urllib.error.URLError(last or OSError("连不上 %s" % p.hostname))


def _detail(e):
    """HTTPError 的 body 只能读一次，读出来挂回异常上供上层拼提示。"""
    try:
        d = e.read().decode("utf-8", "ignore")[:400]
    except Exception:
        d = ""
    e.gk_detail = d
    return d


def _is_bad_model(code, detail):
    """这个 400/404 是不是「模型名无效」——是的话才值得探活重试。"""
    if code not in (400, 404):
        return False
    d = (detail or "").lower()
    return "model" in d and any(w in d for w in
                                ("not exist", "not found", "invalid", "unsupported",
                                 "deprecated", "unavailable", "无效", "不存在"))


# ---------------------------------------------------------------- 调用
def chat(messages, tier="fast", temperature=0.4, max_tokens=1600, timeout=120,
         json_mode=False, cfg=None, retries=1, raw=False, extra=None):
    """调用 OpenAI 兼容的对话接口，返回回复文本（raw=True 返回整个响应 dict）。

    **max_tokens 是「正文」额度**，推理段的额度由 budget() 另外加——业务侧不该、
    也没法知道模型这次要想多久。

    extra 直接并进 payload，给 function calling 这类要塞 tools/tool_choice 的场合用；
    它们配 raw=True 拿整个响应，自己读 tool_calls。

    两处自愈，都遵循同一条原则「本次调用自己爬起来，别等人去改配置或改代码」：
      · 「模型名无效」→ 探活一次换名重试（官方改名时用）。
      · 「推理段吃光额度、正文空串」→ 按实际烧掉的推理 token 加额度重试一次。
        没有它的话，换成推理模型之后全站几十处按老模型定的额度会一处一处地炸，
        且报出来的都是「AI 返回格式异常」这种查不出根因的话。
    """
    # 谁发起的这次调用，在进循环前就问清楚：记账点在下面的 except 里，
    # 那时的调用栈已经是异常处理栈，caller() 未必还能看到业务模块那一帧。
    # 档位也要它——管理员是按「服务」调档位的（后台 → 档位控制）。
    who = aimeter.caller()
    cfg = cfg if cfg is not None else load_cfg()
    tier = effective_tier(tier, cfg, who)
    c = conf(tier, cfg, who="")          # 覆盖上一行已经解析过了，别再查一次
    if not c["key"]:
        raise RuntimeError("AI 未配置，请管理员在「后台 → AI 设置」填写 API Key")
    model, healed = c["model"], False
    cap, grown = budget(model, max_tokens), False
    tried = 0
    while True:
        payload = {"model": model, "messages": messages, "temperature": temperature,
                   "max_tokens": cap, "stream": False}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if extra:
            payload.update(extra)
        t = aimeter.Timer()
        try:
            with t, _open(c, payload, timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
            starved, rt = _starved(d)
            # 一次 HTTP 请求恰好记一行——记两行会让调用数翻倍、失败率减半。
            # starved 是「HTTP 200 但正文空」：token 照烧所以 token 照记，
            # 但它不是一次成功的调用，ok=0。成本和故障率两边都不失真。
            aimeter.record(tier=tier, model=model, mode="chat", usage=d.get("usage"),
                           elapsed_ms=t.ms, ok=not starved,
                           err="starved" if starved else None, who=who)
            if starved and not grown and cap < HARD_CAP:
                # 按实测的推理消耗来加，而不是盲目翻倍：这次烧了 rt，下次给它 3 倍的
                # 推理空间再加上正文额度，一次到位，别连着重试好几轮浪费时间和钱。
                grown, cap = True, min(HARD_CAP, max(cap * 3, rt * 3 + max_tokens))
                _log("正文被推理段挤空（推理段 %d token / 额度 %d），"
                     "把额度提到 %d 重试一次" % (rt, payload["max_tokens"], cap))
                continue
            if starved:
                raise RuntimeError(
                    "模型输出被 max_tokens=%d 截断，正文为空（推理段占了 %s token）；"
                    "%s 是推理模型，需要更大的 max_tokens" % (cap, rt, model))
            if raw:
                return d
            return (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        except urllib.error.HTTPError as e:
            aimeter.record(tier=tier, model=model, mode="chat", elapsed_ms=t.ms,
                           ok=False, err=e, who=who)
            detail = _detail(e)
            if _is_bad_model(e.code, detail) and not healed:
                alt = pick_model(list_models(cfg), tier)
                if alt and alt != model:
                    _log("模型 %s 被接口拒绝，探活后改用 %s；请到「后台 → AI 设置」"
                         "把 %s 档改成它" % (model, alt, tier))
                    model, healed = alt, True
                    # 换了模型就重算额度：新模型可能是推理的、也可能不是。
                    # 已经加过额度的不往回缩。
                    cap = max(cap, budget(model, max_tokens))
                    continue
            raise                      # detail 已由 _detail() 挂在 e.gk_detail 上供上层用
        except OSError as e:
            aimeter.record(tier=tier, model=model, mode="chat", elapsed_ms=t.ms,
                           ok=False, err=e, who=who)
            # 接 OSError 这一整族，而不是列举 (URLError, TimeoutError)：网络出岔子的形状
            # 太多，列举法每漏一种，那种异常就**既不记账也不重试**地直接冒到业务层。
            # 已经踩到的三种：
            #   · 读取阶段超时抛裸 TimeoutError（socket.timeout 的别名，不是 URLError 子类）
            #   · 对端中途 RST 抛 ConnectionResetError
            #   · TLS 层出错抛 ssl.SSLError
            # 三者都是 OSError 的子类，URLError 自己也是（class URLError(OSError)），
            # 所以这一条既涵盖旧的两种、又不再漏。HTTPError 是 URLError 的子类，
            # 但它在上面一条已经先接走了，顺序不能反。
            tried += 1
            if tried <= retries:
                time.sleep(tried)
                continue
            raise


# ---------------------------------------------------------------- 流式
def _merge_tool_calls(slots, deltas):
    """把分片到达的 tool_calls 按 index 拼回完整的那几个调用。

    流式下一次 function call 是碎着来的：先来 id 和函数名，再来十几片 arguments
    字符串（`{"wo`、`rd":"筚`…）。名字本身也可能分片，所以一律用 += 拼，
    不能用赋值——赋值会只留下最后一片，表现为「工具名不存在」。
    """
    for d in deltas or []:
        i = d.get("index") or 0
        s = slots.setdefault(i, {"id": "", "type": "function",
                                 "function": {"name": "", "arguments": ""}})
        if d.get("id"):
            s["id"] = d["id"]
        fn = d.get("function") or {}
        s["function"]["name"] += fn.get("name") or ""
        s["function"]["arguments"] += fn.get("arguments") or ""


def stream(messages, tier="fast", temperature=0.4, max_tokens=1600, timeout=40,
           cfg=None, retries=2, extra=None, first_byte=FIRST_BYTE_TIMEOUT):
    """流式调用：边生成边往外吐。产出 (kind, payload) 二元组：

        ("reasoning", 片段)  推理段（v4 这类推理模型才有；正文之前的「它在想」）
        ("content",   片段)  正文
        ("ping",      "")    上游的心跳注释帧，原样转出去（见下面「为什么要转」）
        ("done",      message)  完整的 assistant message，含拼好的 tool_calls

    为什么值得单独写一条而不是复用 chat()：非流式下，「模型在写」和「连接已经死了」
    在客户端看起来一模一样——都是没有字。流式下每个 token 都是一次心跳，socket 超时
    从「整次请求的上限」变成「两个 token 之间的间隔」，连接一死几十秒内就报出来，
    用户也不用对着「思考中…」干等。

    重试只在**一个字都还没吐出去**时做：已经吐了一半再重来会出现重复的半截话。
    这也正是 first_byte 和 timeout 分开的理由：会被重试放大的只有「等首字节」这一段，
    所以只有它需要按尝试次数分摊；开始吐字之后不会再重试，那一段拿满预算就行。

    ping：上游本来就会发 `: keep-alive` 这样的注释帧，我们以前直接丢掉。转出去是为了
    让**我们自己**发给浏览器的那条 SSE 也一直有字节流动 —— 中间隔着 Cloudflare 隧道，
    静默太久会被边缘掐断（前端还有一层空闲超时），而模型在想的时候本来就没有正文可发。
    """
    who = aimeter.caller()
    cfg = cfg if cfg is not None else load_cfg()
    tier = effective_tier(tier, cfg, who)
    c = conf(tier, cfg, who="")
    if not c["key"]:
        raise RuntimeError("AI 未配置，请管理员在「后台 → AI 设置」填写 API Key")
    model, healed = c["model"], False
    cap, grown = budget(model, max_tokens), False
    tried = 0
    while True:
        payload = {"model": model, "messages": messages, "temperature": temperature,
                   "max_tokens": cap, "stream": True,
                   # 要 usage：推理段把正文挤空时得知道它到底烧了多少 token 才能算新额度
                   "stream_options": {"include_usage": True}}
        if extra:
            payload.update(extra)
        emitted = False
        text, slots, finish, usage = [], {}, "", {}
        t = aimeter.Timer()
        try:
            # 先按「等首字节」那份小预算开；收到第一行就换成「等下一片」那份。
            with t, _open(c, payload, min(first_byte, timeout) if first_byte else timeout) as r:
                widened = not first_byte or first_byte >= timeout
                for raw in r:
                    if not widened:
                        widened = _retime(r, timeout) or True   # 换不成也只试这一次
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line.startswith("data:"):
                        if line.startswith(":"):
                            yield "ping", ""          # 上游心跳：转出去，别让下游静默太久
                        continue                      # 空行是帧分隔
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    try:
                        d = json.loads(body)
                    except Exception:
                        continue                      # 半截 JSON 就丢掉，别让一帧脏数据毁掉整次回答
                    usage = d.get("usage") or usage
                    ch = (d.get("choices") or [{}])[0]
                    finish = ch.get("finish_reason") or finish
                    delta = ch.get("delta") or {}
                    if delta.get("reasoning_content"):
                        yield "reasoning", delta["reasoning_content"]
                    if delta.get("content"):
                        text.append(delta["content"])
                        emitted = True
                        yield "content", delta["content"]
                    if delta.get("tool_calls"):
                        _merge_tool_calls(slots, delta["tool_calls"])
        except GeneratorExit:
            # 客户端中途断开（用户关掉 SSE / 切走页面）。生成器在 yield 处收到这个，
            # 它继承 BaseException，下面两条 except 都接不住——不单列的话，这次调用
            # 既不算成本也不算故障，在账上凭空消失。已经吐出去的 token 是真收费的。
            aimeter.record(tier=tier, model=model, mode="stream", usage=usage,
                           elapsed_ms=t.ms, ok=False, err="aborted", who=who)
            raise                      # GeneratorExit 必须放行，不能吞
        except urllib.error.HTTPError as e:
            aimeter.record(tier=tier, model=model, mode="stream", usage=usage,
                           elapsed_ms=t.ms, ok=False, err=e, who=who)
            detail = _detail(e)
            if _is_bad_model(e.code, detail) and not healed and not emitted:
                alt = pick_model(list_models(cfg), tier)
                if alt and alt != model:
                    _log("模型 %s 被接口拒绝，探活后改用 %s；请到「后台 → AI 设置」"
                         "把 %s 档改成它" % (model, alt, tier))
                    model, healed = alt, True
                    cap = max(cap, budget(model, max_tokens))
                    continue
            raise
        except OSError as e:
            # 同 chat()：接 OSError 这一整族，别列举——漏掉的那种会既不记账也不重试。
            # 流式断在半路时 usage 多半是空的，但已吐出去的 token 照样收费——
            # 有多少记多少，别因为记不全就整条丢掉。
            aimeter.record(tier=tier, model=model, mode="stream", usage=usage,
                           elapsed_ms=t.ms, ok=False, err=e, who=who)
            tried += 1
            if tried <= retries and not emitted:
                time.sleep(tried)
                continue
            raise
        tcs = [slots[i] for i in sorted(slots)]
        content = "".join(text)
        # 这一趟连接走完了（token 已经烧掉），记一行——和 chat() 同一条口径：
        # 一次请求一行，正文空串记 ok=0 但 token 照记。
        starved = (finish == "length" and not content and not tcs)
        aimeter.record(tier=tier, model=model, mode="stream", usage=usage,
                       elapsed_ms=t.ms, ok=not starved,
                       err="starved" if starved else None, who=who)
        if starved and not grown and cap < HARD_CAP:
            # 跟 chat() 同一套自愈：推理段吃光额度、正文一个字没出 → 按实测消耗加额度重来。
            rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
            grown, cap = True, min(HARD_CAP, max(cap * 3, rt * 3 + max_tokens))
            _log("正文被推理段挤空（推理段 %d token），把额度提到 %d 重试一次" % (rt, cap))
            continue
        msg = {"role": "assistant", "content": content}
        if tcs:
            msg["tool_calls"] = tcs
        yield "done", msg
        return


def error_message(e):
    """把异常翻成给用户看的一句话。原先散落在 mods/ai.py 和 agent.py 两处。"""
    if isinstance(e, urllib.error.HTTPError):
        return {
            400: "请求被 AI 服务拒绝（模型名或参数无效），请检查后台 AI 设置",
            401: "API Key 无效或未授权，请在后台重新填写",
            402: "账户余额不足，请到 DeepSeek 充值",
            429: "请求过于频繁，请稍后再试",
        }.get(e.code, "AI 服务返回错误 %d" % e.code)
    # 超时要单列且排在 URLError 前面：连接阶段超时被包成 URLError(reason=timeout)，
    # 读取阶段超时是裸 TimeoutError。漏掉它，用户看到的就是原样的英文
    # "AI 调用失败：The read operation timed out"——一句既看不懂、也不知道该干嘛的话。
    if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
        return "AI 服务响应超时（网络不稳），请再发一次"
    if isinstance(e, urllib.error.URLError):
        return "连不上 AI 服务：" + str(e.reason)
    # 裸 OSError（对端 RST、TLS 报错）不经 URLError 包装，漏掉的话用户看到的是
    # "AI 调用失败：[Errno 104] Connection reset by peer"——又是一句看不懂的英文。
    if isinstance(e, OSError):
        return "与 AI 服务的连接中断（网络不稳），请再发一次"
    return "AI 调用失败：" + str(e)


# ---------------------------------------------------------------- 自检：出事时不依赖 Web 也不依赖 AI
def selfcheck():
    """`python3 aiclient.py` 直接跑：配置对不对、接口通不通、模型名还在不在。"""
    cfg = load_cfg()
    print("配置文件 : %s" % CONFIG)
    print("接口地址 : %s" % conf("fast", cfg)["url"])
    print("API Key  : %s" % ("已配置" if configured(cfg) else "**未配置**"))
    for tier in ("fast", "pro"):
        c = conf(tier, cfg)
        key = TIERS[tier][0]
        print("%-5s → %-24s (config.json: %s = %r) %s" % (
            tier, c["model"], key, cfg.get(key),
            "推理模型，正文额度 2000 → 实发 %d" % budget(c["model"], 2000)
            if is_reasoning(c["model"]) else "非推理模型，额度照发"))
    ids = list_models(cfg)
    if not ids:
        print("\n**拉不到官方模型清单**（Key 无效 / 断网 / 代理挡了）")
        return 1
    print("\n官方现有模型：%s" % ", ".join(ids))
    bad = [(t, conf(t, cfg)["model"]) for t in ("fast", "pro")
           if conf(t, cfg)["model"] not in ids]
    if bad:
        for t, m in bad:
            print("**%s 档的 %s 已不在清单里** → 建议改成 %s" % (t, m, pick_model(ids, t)))
        print("\n改法：后台 → AI 设置，或跑 ./emergency.sh model %s %s"
              % (pick_model(ids, "fast"), pick_model(ids, "pro")))
        return 1
    print("两个档位都有效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(selfcheck())
