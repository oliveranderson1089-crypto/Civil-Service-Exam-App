"""今日：首屏仪表盘的聚合接口（界面重构 P1）。

首页从「13 张同权重的功能卡」换成「今天该做什么」之后，要显示的数字散在七八张表里。
做成一个接口一次取回，是因为它是**首屏**：手机上串行发七八个请求，启动页撤掉时
数字还在一格一格往外跳，比慢更难受。

只读，不写任何表。每个格子各自兜底 —— 首屏是最不该 500 的地方：
缺一张表、脏一条数据，只该让那一格显示 0，不该把整个首页打成「请求失败」。
（这库上真出过：少一张表 → 接口返 HTML → 前端一律弹「请求失败」，查半天。）

**复习条数不在这儿。** /api/review/today 除了算数还要记一笔古诗流水（_gushi_log），
在这儿照抄一遍逻辑就会把那笔流水记重、或者两处口径慢慢走散。前端照旧单独调它，
两个请求各管一段，谁也不用抄谁。
"""
from datetime import datetime

from flask import Blueprint, jsonify

from core import _study_stats, get_db, uid
from mods.plan import _plan_days_left

bp = Blueprint("today", __name__)


def _row(db, sql, args=()):
    """取一行。任何一格出问题都只赔这一格，不连坐整个首屏。"""
    try:
        return db.execute(sql, args).fetchone()
    except Exception:
        return None


def _num(db, sql, args=()):
    r = _row(db, sql, args)
    return int(r[0] or 0) if r and r[0] is not None else 0


# 「今天新更了什么」的来源。三元组：(前端跳哪个功能, 显示名, 数今天有多少条的 SQL)
# 日期列各表不一样：有的存 date 直接比，有的只有 created_at 要 date() 一下，
# 视频用 pick_date（「哪天选中的」比「哪天入库的」更贴近「今天推给你什么」）。
_UPDATES = [
    ("news", "每日时政", "SELECT COUNT(*) FROM news_items WHERE date(created_at)=?"),
    ("sucai", "素材积累", "SELECT COUNT(*) FROM sucai_items WHERE date=?"),
    ("fanwen", "人民时评", "SELECT COUNT(*) FROM essay_models WHERE date(created_at)=?"),
    ("videos", "新闻视频", "SELECT COUNT(*) FROM video_items WHERE pick_date=?"),
    ("gaikuo", "概括句", "SELECT COUNT(*) FROM gaikuo_items WHERE date=?"),
    ("changshi", "常识积累", "SELECT COUNT(*) FROM changshi_items WHERE date=?"),
]

# 今日做了多少题。真题和专项练是一个形状（total/correct/seconds），巩固测试另算。
_DONE_SRC = [
    ("real", "SELECT COALESCE(SUM(total),0), COALESCE(SUM(correct),0), COALESCE(SUM(seconds),0) "
             "FROM real_records WHERE user_id=? AND date(created_at)=?"),
    ("drill", "SELECT COALESCE(SUM(total),0), COALESCE(SUM(correct),0), COALESCE(SUM(seconds),0) "
              "FROM drill_records WHERE user_id=? AND date(created_at)=?"),
]

_WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


@bp.get("/api/today")
def today():
    db = get_db()
    u = uid()
    now = datetime.now()
    d = now.strftime("%Y-%m-%d")

    # —— 今日做题量：真题 + 专项练（逐题型），巩固测试单独一笔（它按套记分，不记秒）
    q = c = 0
    secs = 0.0
    for _, sql in _DONE_SRC:
        r = _row(db, sql, (u, d))
        if r:
            q += int(r[0] or 0)
            c += int(r[1] or 0)
            secs += float(r[2] or 0)
    # 巩固测试一天可以交多次（/api/dtest/grade 不拦重复），所以这里分两笔算：
    #   · 做题量按累计 —— 重做一遍就是又答了一遍，和真题/专项练的口径一致；
    #   · 成绩按最后一次 —— 首页那句「今天的巩固测试已完成 X/Y」问的是成绩，
    #     SUM 会算成 14/20 这种一眼假的数（一份 10 题的测验哪来的 20 题）。
    dt_n = _num(db, "SELECT COUNT(*) FROM dtest_records WHERE user_id=? AND date=?", (u, d))
    dt_sum = _row(db, "SELECT COALESCE(SUM(score),0), COALESCE(SUM(total),0) "
                      "FROM dtest_records WHERE user_id=? AND date=?", (u, d))
    if dt_sum:
        q += int(dt_sum[1] or 0)
        c += int(dt_sum[0] or 0)
    dt_last = _row(db, "SELECT score, total FROM dtest_records "
                       "WHERE user_id=? AND date=? ORDER BY id DESC LIMIT 1", (u, d))
    dt_score, dt_total = (int(dt_last[0] or 0), int(dt_last[1] or 0)) if dt_last else (0, 0)

    # —— 巩固测试：今天出没出、做没做（出了没做才值得在首页催一句）
    has_dt = bool(_num(db, "SELECT 1 FROM daily_quiz WHERE user_id=? AND date=?", (u, d)))

    # —— 任务清单 / 今日计划：都是「几件里做完了几件」
    t_total = _num(db, "SELECT COUNT(*) FROM task_templates WHERE user_id=? AND active=1", (u,))
    t_done = _num(db, "SELECT COUNT(*) FROM task_done WHERE user_id=? AND date=?", (u, d))
    p = _row(db, "SELECT COUNT(*), COALESCE(SUM(done),0) FROM plan_items WHERE user_id=? AND date=?", (u, d))
    p_total, p_done = (int(p[0] or 0), int(p[1] or 0)) if p else (0, 0)

    # —— 今天新更了什么。0 条的不回，前端就不必自己过滤
    ups = []
    for go, name, sql in _UPDATES:
        n = _num(db, sql, (d,))
        if n:
            ups.append({"go": go, "name": name, "n": n})

    # —— 上次练了什么。**不是「接着做」**：库里没有「做到一半」这个状态，
    #    只有交卷后的整组记录。写成「接着做」会骗人，就老实说「上次练习」。
    last = None
    lr = _row(db, "SELECT scope, total, correct, created_at FROM real_records "
                  "WHERE user_id=? ORDER BY id DESC LIMIT 1", (u,))
    if lr:
        last = {"go": "realq", "scope": lr[0] or "真题练习",
                "total": int(lr[1] or 0), "correct": int(lr[2] or 0), "at": lr[3]}

    # —— 距考试还有几天
    exam = None
    pf = _row(db, "SELECT exam, exam_date FROM plan_profile WHERE user_id=?", (u,))
    if pf and pf[1]:
        exam = {"name": pf[0] or "考试", "date": pf[1], "days_left": _plan_days_left(pf[1])}

    try:
        st = _study_stats(db, u)
    except Exception:
        st = {"streak": 0, "total": 0}

    return jsonify({
        "date": d, "weekday": _WEEK[now.weekday()],
        "exam": exam,
        "streak": st.get("streak", 0), "study_days": st.get("total", 0),
        "done": {"questions": q, "correct": c, "minutes": int(secs // 60)},
        "dtest": {"has": has_dt, "runs": dt_n, "score": dt_score, "total": dt_total},
        "tasks": {"done": t_done, "total": t_total},
        "plan": {"done": p_done, "total": p_total},
        "updates": ups,
        "last": last,
    })
