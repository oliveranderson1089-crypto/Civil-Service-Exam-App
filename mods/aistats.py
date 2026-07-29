"""AI 用量与故障报表：钱花在哪、哪儿在失败。

数据由 aimeter.py 写入（每次真实发出的请求一行，含重试）。这边只读、只聚合。

为什么值得有：十几个 gen_*/crawl_* 脚本全靠同一个 AI，出问题时最先要回答的
三个问题是「今天调了多少次」「谁在烧」「失败的是哪一类」。在此之前这些一个都
答不上来——usage 明明拿到了，用完就扔。

口径说明（报表上也写着，免得看的人自己去猜）：
  · 一次重试算一次调用——重试是实打实又发了一次请求、又烧了一次 token。
  · 推理 token 单独一列：v4 是推理模型，混进 completion 里就看不见了。
  · 失败行的 token 多半是 0（请求就没成功），所以「token 总量」看的是成功的那些。
"""
from flask import Blueprint, jsonify, request

from core import get_db

bp = Blueprint("aistats", __name__)

# 报表只认这几个窗口。天数直接拼进 SQL，所以必须是白名单里的整数，
# 不能拿请求里的值去拼——那就是注入。
_WINDOWS = {"today": 0, "7d": 7, "30d": 30}


# 空报表也要跟有数据时结构一致，前端才不用为「还没数据」写一套分支。
_EMPTY_TOTALS = {"calls": 0, "ok": 0, "failed": 0, "fail_rate": 0.0,
                 "prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0,
                 "tokens": 0, "avg_ms": 0}


def _has_table(db):
    """还没发生过任何 AI 调用时这张表可能不存在（aimeter 是首次调用才建）。
    这不是错误，是「还没数据」——报表要照常出，全 0 就行。"""
    return bool(db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_calls'").fetchone())


def _where(win):
    """窗口 → SQL 条件。today 按自然日算（跟 P0 的产出健康同一个口径）。"""
    if win == "today":
        return "ts >= date('now','localtime')"
    return "ts >= datetime('now','localtime','-%d day')" % _WINDOWS[win]


def _totals(db, cond):
    r = db.execute(
        "SELECT COUNT(*) calls, SUM(ok) ok_calls, "
        "SUM(prompt_tokens) pt, SUM(completion_tokens) ct, SUM(reasoning_tokens) rt, "
        "AVG(CASE WHEN ok=1 THEN elapsed_ms END) avg_ms "
        "FROM ai_calls WHERE %s" % cond).fetchone()
    calls = r["calls"] or 0
    ok = r["ok_calls"] or 0
    return {
        "calls": calls,
        "ok": ok,
        "failed": calls - ok,
        "fail_rate": round((calls - ok) * 100.0 / calls, 1) if calls else 0.0,
        "prompt_tokens": r["pt"] or 0,
        "completion_tokens": r["ct"] or 0,
        "reasoning_tokens": r["rt"] or 0,
        "tokens": (r["pt"] or 0) + (r["ct"] or 0),
        "avg_ms": int(r["avg_ms"] or 0),
    }


def _by(db, cond, col, limit=12):
    """按某一列排名。用于「谁在烧钱」（caller）和「哪个档位」（tier）。"""
    rows = db.execute(
        "SELECT %s k, COUNT(*) calls, SUM(ok) ok_calls, "
        "SUM(prompt_tokens+completion_tokens) tokens, SUM(reasoning_tokens) rt "
        "FROM ai_calls WHERE %s GROUP BY %s ORDER BY tokens DESC, calls DESC "
        "LIMIT %d" % (col, cond, col, limit)).fetchall()
    return [{"key": r["k"] or "?", "calls": r["calls"], "ok": r["ok_calls"] or 0,
             "failed": r["calls"] - (r["ok_calls"] or 0),
             "tokens": r["tokens"] or 0, "reasoning_tokens": r["rt"] or 0}
            for r in rows]


def _errors(db, cond):
    rows = db.execute(
        "SELECT err_kind k, COUNT(*) n FROM ai_calls "
        "WHERE ok=0 AND %s GROUP BY err_kind ORDER BY n DESC" % cond).fetchall()
    return [{"kind": r["k"] or "other", "n": r["n"]} for r in rows]


def _recent_failures(db, limit=20):
    """最近的失败，不限窗口——出事时要看的是「最近怎么了」，不是「今天怎么了」。"""
    rows = db.execute(
        "SELECT ts, caller, tier, model, mode, err_kind, elapsed_ms "
        "FROM ai_calls WHERE ok=0 ORDER BY id DESC LIMIT %d" % limit).fetchall()
    return [dict(r) for r in rows]


def _daily(db, days=14):
    """按天的趋势：调用数 + token 量。给前端画一条小柱子。"""
    rows = db.execute(
        "SELECT substr(ts,1,10) d, COUNT(*) calls, "
        "SUM(prompt_tokens+completion_tokens) tokens, SUM(ok) ok_calls "
        "FROM ai_calls WHERE ts >= datetime('now','localtime','-%d day') "
        "GROUP BY d ORDER BY d" % days).fetchall()
    return [{"day": r["d"], "calls": r["calls"], "tokens": r["tokens"] or 0,
             "failed": r["calls"] - (r["ok_calls"] or 0)} for r in rows]


@bp.get("/api/admin/ai/stats")
def ai_stats():
    win = request.args.get("win", "today")
    if win not in _WINDOWS:
        win = "today"
    db = get_db()
    if not _has_table(db):
        # 一次 AI 调用都还没发生过。给一份空报表，别让前端看到 500。
        return jsonify({"win": win, "empty": True, "totals": dict(_EMPTY_TOTALS),
                        "by_caller": [], "by_tier": [], "by_model": [],
                        "errors": [], "recent_failures": [], "daily": []})
    cond = _where(win)
    return jsonify({
        "win": win,
        "empty": False,
        "totals": _totals(db, cond),
        "by_caller": _by(db, cond, "caller"),
        "by_tier": _by(db, cond, "tier"),
        "by_model": _by(db, cond, "model"),
        "errors": _errors(db, cond),
        "recent_failures": _recent_failures(db),
        "daily": _daily(db),
    })
