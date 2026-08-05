"""导航页的状态数字（界面重构 P2）：「练」和「积累」两个标签页要显示的东西。

P0 的标签页只是一份目录，能到达但看不出该去哪。这里补的是**选择的依据**：
  · 练  —— 每个板块近 30 天的正确率和错题存量。正确率低的那个才是今天该练的。
  · 积累 —— 每个模块今天新增了几条。没有这个就得挨个点进去看有没有更新。

和 mods/today.py 分开，是因为口径不同：today 回答「今天做了什么」（本人、当天），
这里回答「该往哪使劲」（近 30 天的成绩 + 今天的库存变化）。合成一个接口的话，
首屏会为了两个标签页才要的数字多算一遍。

兜底策略沿用 today.py：只读，每格各自 try，缺表只赔那一格。导航页 500 等于整个
标签栏点不动，比首页挂了还难受。
"""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify

from core import get_db, uid
# 复用 today.py 那个「取不到就算 0」的小工具。跨模块引私有名在这套代码里是有先例的
# （mods/plan.py 就从 mods/review 引 _review_due），比抄一份两头改要好。
from mods.today import _num

bp = Blueprint("hub", __name__)

WINDOW_DAYS = 30        # 正确率看多久：太短一两次手滑就翻脸，太长练完了还显示旧水平

# 「积累」各模块今天新增了多少。key 必须和前端 tabs.js 里条目的 acc 键对上。
# 分两类：全局内容（cron 每天产出的）和本人收录（自己攒的），SQL 里带不带 user_id 就是区别。
_ACC_GLOBAL = {
    "hyper": "SELECT COUNT(*) FROM hyper_items WHERE date(created_at)=?",
    "sucai": "SELECT COUNT(*) FROM sucai_items WHERE date=? AND kind<>'衔接表达'",
    "lianjie": "SELECT COUNT(*) FROM sucai_items WHERE date=? AND kind='衔接表达'",
    "gaikuo": "SELECT COUNT(*) FROM gaikuo_items WHERE date=?",
    "changshi": "SELECT COUNT(*) FROM changshi_items WHERE date=?",
    "yylib": "SELECT COUNT(*) FROM yy_items WHERE date(created_at)=?",
    "news": "SELECT COUNT(*) FROM news_items WHERE date(created_at)=?",
    "videos": "SELECT COUNT(*) FROM video_items WHERE pick_date=?",
    "fanwen": "SELECT COUNT(*) FROM essay_models WHERE date(created_at)=?",
}
_ACC_MINE = {
    # 成语是自己收录的：这一格显示「我今天收了几条」，不是「库里多了几条」
    "idiom": "SELECT COUNT(*) FROM entries WHERE user_id=? AND date(created_at)=?",
}


@bp.get("/api/hub")
def hub():
    db = get_db()
    u = uid()
    today = datetime.now().strftime("%Y-%m-%d")
    since = (datetime.now() - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")

    # —— 各板块近 30 天的专项练成绩
    boards = {}
    try:
        for r in db.execute(
                "SELECT board, COALESCE(SUM(total),0) q, COALESCE(SUM(correct),0) c "
                "FROM drill_records WHERE user_id=? AND created_at>=? AND board IS NOT NULL "
                "GROUP BY board", (u, since)):
            q, c = int(r[1] or 0), int(r[2] or 0)
            if q:
                boards[r[0]] = {"q": q, "correct": c, "rate": round(c * 100 / q), "wrong": 0}
    except Exception:
        boards = {}

    # —— 错题本里各板块的存量。板块可能一道题都没练过但有错题，所以要补出这一格
    try:
        for r in db.execute("SELECT board, COUNT(*) n FROM wrong_questions "
                            "WHERE user_id=? AND board IS NOT NULL GROUP BY board", (u,)):
            boards.setdefault(r[0], {"q": 0, "correct": 0, "rate": None, "wrong": 0})
            boards[r[0]]["wrong"] = int(r[1] or 0)
    except Exception:
        pass

    acc = {}
    for k, sql in _ACC_GLOBAL.items():
        n = _num(db, sql, (today,))
        if n:
            acc[k] = n
    for k, sql in _ACC_MINE.items():
        n = _num(db, sql, (u, today))
        if n:
            acc[k] = n

    return jsonify({"date": today, "window_days": WINDOW_DAYS, "boards": boards, "acc": acc})
