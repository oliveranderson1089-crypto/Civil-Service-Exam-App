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
"""
import json
import os
import re
import sys
import time
import urllib.error
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


def conf(tier="fast", cfg=None):
    """解析出一次调用需要的全部东西：接口地址、真实模型名、Key。"""
    c = cfg if cfg is not None else load_cfg()
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
    return bool(conf("fast", cfg)["key"])


# ---------------------------------------------------------------- 探活：官方现在到底有哪些模型
_models_cache = {"at": 0.0, "ids": []}


def list_models(cfg=None, timeout=20, ttl=300):
    """GET /v1/models 拿官方现有清单。带 5 分钟缓存，别在重试里反复拉。"""
    now = time.time()
    if _models_cache["ids"] and now - _models_cache["at"] < ttl:
        return _models_cache["ids"]
    c = conf("fast", cfg)
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
REASON_MIN = 4000
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


def _open(c, payload, timeout):
    """发出去并拿到响应对象。流式那条要边读边处理，不能像 chat() 那样一口气 read()，
    所以建请求这段得单独拎出来给两边共用。"""
    req = urllib.request.Request(
        c["url"], data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + c["key"]})
    return urllib.request.urlopen(req, timeout=timeout)


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
    c = conf(tier, cfg)
    if not c["key"]:
        raise RuntimeError("AI 未配置，请管理员在「后台 → AI 设置」填写 API Key")
    model, healed = c["model"], False
    cap, grown = budget(model, max_tokens), False
    tried = 0
    # 谁发起的这次调用，在进循环前就问清楚：记账点在下面的 except 里，
    # 那时的调用栈已经是异常处理栈，caller() 未必还能看到业务模块那一帧。
    who = aimeter.caller()
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
        except (urllib.error.URLError, TimeoutError) as e:
            aimeter.record(tier=tier, model=model, mode="chat", elapsed_ms=t.ms,
                           ok=False, err=e, who=who)
            # TimeoutError 必须单列：连接阶段超时会被 urllib 包成 URLError，可**读取阶段**
            # 超时（"The read operation timed out"）抛的是裸的 socket.timeout —— 它是
            # TimeoutError 的别名、不是 URLError 的子类，原来这条分支根本接不住，
            # 一次网络抖动就让整轮调用失败。实测小题出题连跑 4 次，有 1 次栽在这儿，
            # 整道题白出。长任务（出题/批改）耗时越久越容易撞上，越该重试。
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
           cfg=None, retries=2, extra=None):
    """流式调用：边生成边往外吐。产出 (kind, payload) 二元组：

        ("reasoning", 片段)  推理段（v4 这类推理模型才有；正文之前的「它在想」）
        ("content",   片段)  正文
        ("done",      message)  完整的 assistant message，含拼好的 tool_calls

    为什么值得单独写一条而不是复用 chat()：非流式下，「模型在写」和「连接已经死了」
    在客户端看起来一模一样——都是没有字。流式下每个 token 都是一次心跳，socket 超时
    从「整次请求的上限」变成「两个 token 之间的间隔」，连接一死几十秒内就报出来，
    用户也不用对着「思考中…」干等。

    重试只在**一个字都还没吐出去**时做：已经吐了一半再重来会出现重复的半截话。
    """
    c = conf(tier, cfg)
    if not c["key"]:
        raise RuntimeError("AI 未配置，请管理员在「后台 → AI 设置」填写 API Key")
    model, healed = c["model"], False
    cap, grown = budget(model, max_tokens), False
    tried = 0
    who = aimeter.caller()
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
            with t, _open(c, payload, timeout) as r:
                for raw in r:
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line.startswith("data:"):
                        continue                      # 空行是帧分隔，": ping" 是心跳
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
        except (urllib.error.URLError, TimeoutError) as e:
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
