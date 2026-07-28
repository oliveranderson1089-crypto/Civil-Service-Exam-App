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
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

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

    extra 直接并进 payload，给 function calling 这类要塞 tools/tool_choice 的场合用；
    它们配 raw=True 拿整个响应，自己读 tool_calls。

    撞上「模型名无效」会探活一次并换名重试——这条是为了让系统在官方改名时
    能自己爬起来，而不是等人去后台改配置。
    """
    c = conf(tier, cfg)
    if not c["key"]:
        raise RuntimeError("AI 未配置，请管理员在「后台 → AI 设置」填写 API Key")
    model, healed = c["model"], False
    last = None
    for attempt in range(retries + 1):
        payload = {"model": model, "messages": messages, "temperature": temperature,
                   "max_tokens": max_tokens, "stream": False}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if extra:
            payload.update(extra)
        req = urllib.request.Request(
            c["url"], data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + c["key"]})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
            if raw:
                return d
            ch = (d.get("choices") or [{}])[0]
            out = (ch.get("message", {}).get("content") or "").strip()
            # deepseek-v4 是推理模型：reasoning_content 也吃 max_tokens 配额。额度给小了
            # 就会推理没推完、正文一个字没出，content 是空串。旧的 max_tokens 是按
            # 非推理的 deepseek-chat 定的，这种截断必须报出来——否则上游 json.loads("")
            # 只会得到一句莫名其妙的解析失败。
            if not out and ch.get("finish_reason") == "length":
                rt = (d.get("usage", {}).get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
                raise RuntimeError(
                    "模型输出被 max_tokens=%d 截断，正文为空（推理段占了 %s token）；"
                    "%s 是推理模型，需要更大的 max_tokens" % (max_tokens, rt, model))
            return out
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "ignore")[:400]
            except Exception:
                pass
            last = e
            if _is_bad_model(e.code, detail) and not healed:
                alt = pick_model(list_models(cfg), tier)
                if alt and alt != model:
                    _log("模型 %s 被接口拒绝，探活后改用 %s；请到「后台 → AI 设置」"
                         "把 %s 档改成它" % (model, alt, tier))
                    model, healed = alt, True
                    continue
            e.gk_detail = detail       # 供上层拼错误提示，省一次 read()（body 只能读一次）
            raise
        except urllib.error.URLError as e:
            last = e
            if attempt < retries:
                time.sleep(1 + attempt)
                continue
            raise
    raise last


def error_message(e):
    """把异常翻成给用户看的一句话。原先散落在 mods/ai.py 和 agent.py 两处。"""
    if isinstance(e, urllib.error.HTTPError):
        return {
            400: "请求被 AI 服务拒绝（模型名或参数无效），请检查后台 AI 设置",
            401: "API Key 无效或未授权，请在后台重新填写",
            402: "账户余额不足，请到 DeepSeek 充值",
            429: "请求过于频繁，请稍后再试",
        }.get(e.code, "AI 服务返回错误 %d" % e.code)
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
        print("%-5s → %-24s (config.json: %s = %r)" % (tier, c["model"], key, cfg.get(key)))
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
