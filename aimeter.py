#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 调用记账：每次真实发出去的请求记一行。

**为什么零依赖**：理由和 aiclient.py 一模一样——记账要盖住的正是那 13 个
定时器脚本（它们才是烧 token 的大头），而它们 import 不动 core（core 要
flask + pypinyin）。所以这里只用标准库，Web 和脚本两边都能 import。

**为什么记每次尝试而不是每次调用**：aiclient 有两处自愈重试（模型名失效换名、
推理段挤空加额度）。重试是实打实又发了一次请求、又烧了一次 token——按「调用」
记会把成本记少，按「尝试」记才对得上账单。

**记账绝不能影响 AI 调用本身**：所有写库路径整个包在 try 里，失败只打一行日志。
宁可丢一行账，也不能让 AI 因为记账失败而失败——这块是来观测的，不是来添乱的。

关表：环境变量 GONGKAO_AI_METER=0。
"""
import os
import random
import sqlite3
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))

# 留 90 天。这张表是「每次尝试一行」，跑久了比业务表还大，
# 而超过一个季度的单条调用记录没人会去翻——聚合结论早就看过了。
KEEP_DAYS = 90

# 建表语句同时存在于 schema.py（主应用）和这里（脚本先跑的情况），
# tests/test_schema_drift.py 盯着两份别漂。改这儿记得同步改那儿。
DDL = """CREATE TABLE IF NOT EXISTS ai_calls(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT DEFAULT (datetime('now','localtime')),
    caller TEXT DEFAULT '',
    tier TEXT DEFAULT '',
    model TEXT DEFAULT '',
    mode TEXT DEFAULT 'chat',
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    elapsed_ms INTEGER DEFAULT 0,
    ok INTEGER DEFAULT 1,
    err_kind TEXT DEFAULT ''
)"""

# 这三个是「路过的」不是「发起的」：aiclient 是调用层、aimeter 是本模块、
# ai 是 mods/ai.py 那个转发层（_ai_call_or_error → ai_chat → aiclient.chat，
# 18 个业务模块全从它过）。不跳过它，所有 Web 侧调用都会记成 "ai" 一坨，
# 「谁在烧钱」这个问题就问不出答案了。
_SKIP = {"aiclient", "aimeter", "ai"}


def enabled():
    return os.environ.get("GONGKAO_AI_METER", "1") != "0"


def _log(msg):
    sys.stderr.write("[aimeter] %s\n" % msg)
    sys.stderr.flush()


def caller():
    """顺着调用栈往上找第一个「真正发起调用」的模块名。

    取模块文件名（gen_essays.py → gen_essays、mods/find.py → find），
    跳过 _SKIP 里那几层管道。找不到就给 "?"，绝不抛异常。
    """
    try:
        f = sys._getframe(1)
        while f:
            name = os.path.basename(f.f_code.co_filename)
            if name.endswith(".py"):
                name = name[:-3]
                if name not in _SKIP:
                    return name
            f = f.f_back
    except Exception:
        pass
    return "?"


def _connect():
    # timeout：另一个进程正在写时等一会儿，别当场放弃（13 个定时器脚本 + Web 可能撞车）。
    # isolation_level=None 走自动提交，一行一个短事务，不长期占着写锁。
    con = sqlite3.connect(DB, timeout=5, isolation_level=None)
    con.execute("PRAGMA busy_timeout=5000")
    return con


def ensure_schema(con):
    """脚本可能先于主应用碰到新库，所以它自己也要能把表建出来（同 crawl_exam.py 的做法）。"""
    con.execute(DDL)
    con.execute("CREATE INDEX IF NOT EXISTS idx_ai_calls_ts ON ai_calls(ts DESC)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ai_calls_caller ON ai_calls(caller, ts DESC)")


def err_kind(exc):
    """把异常归成几个能拿来做分桶统计的类别。名字要稳定——报表按它分组。

    也接受直接传进来的字符串（如 "starved"）：有些失败不是异常，是「HTTP 200
    但正文空」这种，调用方比这里更清楚它该叫什么。
    """
    import urllib.error
    if isinstance(exc, str):
        return exc
    if isinstance(exc, urllib.error.HTTPError):
        return "http_%d" % exc.code
    # 顺序要紧：连接阶段超时被包成 URLError(reason=timeout)，读取阶段超时是裸
    # TimeoutError（不是 URLError 的子类）。先判超时，否则前者会被记成 network。
    if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
        return "timeout"
    if isinstance(exc, urllib.error.URLError):
        return "network"
    return "other"


def _tokens(usage):
    """从 OpenAI 兼容的 usage 里取三个数。推理 token 藏在二级字典里，单独算一列——
    v4 是推理模型，这块常被低估，混进 completion 里就看不见了。"""
    u = usage or {}
    det = u.get("completion_tokens_details") or {}
    return (int(u.get("prompt_tokens") or 0),
            int(u.get("completion_tokens") or 0),
            int(det.get("reasoning_tokens") or 0))


def record(tier="", model="", mode="chat", usage=None, elapsed_ms=0,
           ok=True, err=None, who=None):
    """记一行。任何异常都吞掉——这块出问题不该连累 AI 调用。"""
    if not enabled():
        return
    try:
        pt, ct, rt = _tokens(usage)
        row = (who or caller(), tier or "", model or "", mode or "chat",
               pt, ct, rt, int(elapsed_ms or 0),
               1 if ok else 0, "" if ok else err_kind(err) if err else "other")
        con = _connect()
        try:
            ensure_schema(con)
            con.execute(
                "INSERT INTO ai_calls(caller,tier,model,mode,prompt_tokens,"
                "completion_tokens,reasoning_tokens,elapsed_ms,ok,err_kind) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)", row)
            _maybe_prune(con)
        finally:
            con.close()
    except Exception as e:      # noqa: BLE001 —— 记账失败绝不能让 AI 调用失败
        _log("记账失败（不影响本次调用）：%s" % e)


def _maybe_prune(con):
    """按概率清理过期记录。

    不挂定时器、不在每次调用里都删：前者又多一个要维护的单元，后者让每次 AI
    调用都背一次全表扫描。1/500 的概率意味着大约每 500 次调用清一次，
    而这张表一天也到不了几百行——足够了。
    """
    if random.randint(1, 500) != 1:
        return
    con.execute("DELETE FROM ai_calls WHERE ts < datetime('now','localtime','-%d day')"
                % KEEP_DAYS)


class Timer:
    """量一次尝试的耗时。`with Timer() as t: ...` 之后 t.ms 就是毫秒数。"""

    def __enter__(self):
        self.t0 = time.time()
        self.ms = 0
        return self

    def __exit__(self, *exc):
        self.ms = int((time.time() - self.t0) * 1000)
        return False
