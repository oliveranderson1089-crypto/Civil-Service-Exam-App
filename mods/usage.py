"""使用观测：这个应用建了这么多东西，到底哪些**你真的在用**。

为什么要有这一块：后台已经有四块可观测，盯的全是「机器干得怎么样」——
产出健康盯定时器出没出货、AI 用量盯调用花了多少、内容质检盯出的题好不好、
备份容量盯数据丢不丢得起。唯独没有一块盯**人**：这些功能你到底碰不碰。

于是很容易出现这种局面：库里 7606 道真题、46 个题型的专项练、
一个 2000 行的申论找点模块，全都绿着、全都在按时补货，
而实际上其中大半个月没人点过一次。**建设的速度跑赢了使用的速度**，
这件事在别的面板里一个字都看不出来。

判据不靠埋点，靠**业务记录**：不问「你点开了几次」，问「你留下了什么」。
两个原因：
  · 点开看一眼不算用，做了一道题、收了一条词才算 —— 后者才是该拿来做决定的信号
  · 零埋点意味着**立刻就有两个月的历史**，不用等新数据慢慢攒

这块的用途是**做减法**，不是激励：哪些模块可以停止维护、哪天该把改代码的时间
换成做题。所以每个功能除了「用了多少」还给「多久没碰过」，
并且首屏那个数字是「今天该做多少题才追得上考试」，不是「你真棒」。

加一个功能 = 在 FEATURES 加一行，不写逻辑。
"""
from datetime import date, datetime

from flask import Blueprint, jsonify

from core import get_db, log, uid

bp = Blueprint("usage", __name__)

# key, 显示名, 表, 时间列, 分组, 一句话（这个功能「用了」是什么意思）
#
# 名字带 USAGE_ 前缀不是啰嗦：static/js/search.js 里已经有一个 FEATURES
# （全局搜索的功能索引，跟这个毫无关系）。tests/frontend/crossend.test.js 会
# 自动把前后端同名的大写常量配对、比内容 —— 两份不相干的表撞了名字，
# 它就会报「前后端走散了」。那条测试是对的，该让路的是这边。
#
# 时间列各表不一样：多数是 created_at，drill_seen 只有 last_at，
# gushi_log 用 added_on（「哪天进的复习」比「哪天入的库」更贴近使用）。
# 表名写错了不会报错、只会显示 0 —— 所以下面 _feature_row 里查不到表要说出来。
USAGE_FEATURES = [
    # ---- 练题 ----
    ("real",     "历年真题",   "real_attempts",  "created_at", "练题", "做一道真题记一次，带用时和对错"),
    ("drill",    "专项练",     "drill_log",      "created_at", "练题", "按题型刷，一题一条"),
    ("dtest",    "每日巩固",   "dtest_records",  "created_at", "练题", "按当天学的内容出的小测"),
    ("quiz",     "阶段测验",   "quiz_answers",   "created_at", "练题", "每周两次的套题"),
    ("wrongq",   "错题本",     "wrong_questions", "created_at", "练题", "收进来一道错题"),
    ("basics",   "基础知识点", "board_points",   "created_at", "练题", "在讲义考点下记一条要点"),
    # ---- 申论 ----
    ("find",     "申论找点",   "find_records",   "created_at", "申论", "在材料上标一次采分点"),
    ("shenlun",  "申论批改",   "shenlun_grade",  "created_at", "申论", "交一份答案让 AI 逐点批"),
    ("findp",    "申论套卷",   "find_papers",    "created_at", "申论", "开一份卷子"),
    # ---- 积累 ----
    ("entries",  "词语积累",   "entries",        "created_at", "积累", "收录一个成语/词语"),
    ("gushi",    "古诗积累",   "gushi_log",      "added_on",   "积累", "一首诗进了今日复习"),
    ("annots",   "划重点",     "annotations",    "created_at", "积累", "在正文上划一处"),
    ("bookmark", "收藏",       "bookmarks",      "updated_at", "积累", "收藏一条内容"),
    # ---- 工具 ----
    ("notes",    "小记",       "notes",          "created_at", "工具", "写一条随手记"),
    ("kb",       "知识库",     "kb_nodes",       "created_at", "工具", "建一个笔记块"),
    ("materials", "资料库",    "materials",      "created_at", "工具", "传一份资料"),
    ("aichat",   "AI 助手",    "ai_chats",       "updated_at", "工具", "跟 AI 聊一轮"),
    ("plan",     "备考规划",   "plan_log",       "created_at", "工具", "完成一项计划任务"),
    # ---- 社交 ----
    ("chat",     "聊天",       "chat_msgs",      "created_at", "社交", "发一条消息"),
]

# 「今天该做多少题」按这个总量倒推。真题是这个应用里唯一有明确「刷完」概念的东西，
# 其余（专项练、积累）是无底洞，拿来算进度只会得出一个假的完成率。
#
# 分母取 has_answer=1 而不是全部 7606：没答案的题做了也判不了对错，
# 把它们算进「还要刷多少」等于给自己派了一堆做不了的活。
# （needs_asset 那些不排除 —— 缺图的题配上图照样能做，不是永久不可用。）
_BANK_SQL = "SELECT COUNT(*) FROM real_questions WHERE has_answer=1"


def _num(db, sql, args=()):
    """取一个数。任何一格出问题都只赔这一格 —— 和 today.py 同一条规矩：
    缺一张表、脏一条数据，只该让那一格显示 0，不该把整页打成「请求失败」。"""
    try:
        r = db.execute(sql, args).fetchone()
        return int(r[0] or 0) if r and r[0] is not None else 0
    except Exception:
        return 0


def _table_exists(db, t):
    return bool(db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


def _feature_row(db, u, key, name, table, tcol, group, what):
    """一个功能的使用情况：7 天 / 30 天 / 总共几条，最后一次是几天前。"""
    if not _table_exists(db, table):
        # 表名写错、或者哪次重构把表改名了。显示 0 会被当成「没在用」，
        # 那是把一个 bug 伪装成一个结论 —— 必须说出来。
        return {"key": key, "name": name, "group": group, "what": what,
                "d7": 0, "d30": 0, "total": 0, "last": "", "idle_days": None,
                "state": "broken", "note": "表 %s 不存在" % table}

    where_u = ""
    args7 = args30 = argsT = ()
    cols = {c[1] for c in db.execute("PRAGMA table_info('%s')" % table)}
    if "user_id" in cols and u:
        where_u = " AND user_id=?"
        args7 = args30 = argsT = (u,)

    base = "SELECT COUNT(*) FROM '%s' WHERE 1=1%s" % (table, where_u)
    d7 = _num(db, base + " AND date(%s) >= date('now','localtime','-7 day')" % tcol, args7)
    d30 = _num(db, base + " AND date(%s) >= date('now','localtime','-30 day')" % tcol, args30)
    total = _num(db, base, argsT)

    last = ""
    try:
        r = db.execute("SELECT MAX(%s) FROM '%s' WHERE 1=1%s" % (tcol, table, where_u),
                       argsT).fetchone()
        last = (r[0] or "")[:10] if r else ""
    except Exception:
        log.debug("读 %s 最后使用时间失败", table, exc_info=True)

    idle = None
    if last:
        try:
            idle = (date.today() - datetime.strptime(last, "%Y-%m-%d").date()).days
        except ValueError:
            idle = None

    # 分档。阈值不是随便定的：7 天是「这周还在用」，30 天是「这个月还想得起来」。
    # 超过 30 天没碰、或者从来没碰过 —— 那就是这个模块对你不成立，该考虑停止维护了。
    if not total:
        state = "never"
    elif idle is None:
        state = "cold"
    elif idle <= 7:
        state = "hot"
    elif idle <= 30:
        state = "cold"
    else:
        state = "dead"

    return {"key": key, "name": name, "group": group, "what": what,
            "d7": d7, "d30": d30, "total": total, "last": last,
            "idle_days": idle, "state": state, "note": ""}


def _coverage(db, u):
    """真题覆盖率 + 按剩余天数倒推的「今天该做多少」。

    这是整块里唯一一个**能指导今天行动**的数字，所以放在最前面。
    算法刻意简单：剩下没做的题 ÷ 剩下的天数。不做加权、不排除节假日 ——
    一个能立刻验证对错的粗数字，比一个要解释半天的精确模型有用。
    """
    bank = _num(db, _BANK_SQL) or _num(db, "SELECT COUNT(*) FROM real_questions")
    done = _num(db, "SELECT COUNT(DISTINCT qid) FROM real_attempts WHERE user_id=?", (u,))

    exam, exam_date, days_left = "", "", None
    try:
        r = db.execute("SELECT exam, exam_date FROM plan_profile WHERE user_id=?", (u,)).fetchone()
        if r:
            exam = r["exam"] or ""
            exam_date = r["exam_date"] or ""
            if exam_date:
                days_left = (datetime.strptime(exam_date, "%Y-%m-%d").date() - date.today()).days
    except Exception:
        log.debug("读考试日期失败", exc_info=True)

    # 实际速度按**最近 30 天**算，不按历史总平均：总平均会被开头那阵新鲜劲拉高，
    # 而你要判断的是「照现在这个样子下去会怎样」。
    recent = _num(db, "SELECT COUNT(*) FROM real_attempts WHERE user_id=? "
                      "AND date(created_at) >= date('now','localtime','-30 day')", (u,))
    pace = round(recent / 30.0, 1)

    left = max(0, bank - done)
    need = None
    if days_left and days_left > 0 and left:
        need = int(-(-left // days_left))        # 向上取整：宁可多算一道
    # 按当前速度到考试日能覆盖到哪儿。这个数比「还剩多少」更能说明问题：
    # 它把「速度」和「时间」两件事合成了一个能对照目标的结论。
    projected = None
    if days_left and days_left > 0:
        projected = min(bank, done + int(pace * days_left))

    return {"bank": bank, "done": done, "left": left,
            "pct": round(done * 100.0 / bank, 1) if bank else 0.0,
            "exam": exam, "exam_date": exam_date, "days_left": days_left,
            "pace": pace, "need": need, "projected": projected,
            "projected_pct": round(projected * 100.0 / bank, 1) if (bank and projected) else 0.0}


def _daily(db, u, days=30):
    """最近 N 天每天做了多少题（真题 + 专项练）。给一条走势，看得出断没断。

    补零很重要：只返回有记录的那些天，画出来是一条虚假的连续曲线 ——
    中间那几天没做题恰恰是最该看见的信息。
    """
    hit = {}
    for sql in ("SELECT date(created_at) d, COUNT(*) n FROM real_attempts "
                "WHERE user_id=? AND date(created_at) >= date('now','localtime',?) GROUP BY d",
                "SELECT date(created_at) d, COUNT(*) n FROM drill_log "
                "WHERE user_id=? AND date(created_at) >= date('now','localtime',?) GROUP BY d"):
        try:
            for r in db.execute(sql, (u, "-%d day" % days)):
                hit[r[0]] = hit.get(r[0], 0) + int(r[1] or 0)
        except Exception:
            log.debug("读每日做题量失败", exc_info=True)
    out, today = [], date.today()
    for i in range(days, -1, -1):
        d = (today.toordinal() - i)
        k = date.fromordinal(d).isoformat()
        out.append({"date": k, "n": hit.get(k, 0)})
    return out


@bp.get("/api/admin/usage")
def usage():
    db, u = get_db(), uid()
    feats = []
    for row in USAGE_FEATURES:
        try:
            feats.append(_feature_row(db, u, *row))
        except Exception:
            log.debug("读功能 %s 使用情况失败", row[0], exc_info=True)

    cov = _coverage(db, u)
    daily = _daily(db, u)
    active_days = sum(1 for d in daily if d["n"])

    # 分档汇总。这三个数是这一屏的结论：**在用的有几个、凉了的有几个、白建的有几个。**
    tally = {"hot": 0, "cold": 0, "dead": 0, "never": 0, "broken": 0}
    for f in feats:
        tally[f["state"]] = tally.get(f["state"], 0) + 1

    return jsonify({
        "coverage": cov,
        "features": feats,
        "tally": tally,
        "daily": daily,
        "active_days_30": active_days,
        "states": _states(cov, tally, active_days),
    })


def _states(cov, tally, active_days):
    """红黄绿。口径和其余四块可观测一致：后端判，前端只显示。

    这里判的不是「系统好不好」，是**「照这个节奏走，考试那天会怎样」**。
    所以绿的条件很硬：按当前速度能覆盖到 80% 以上、且这个月一半以上的日子在练。
    """
    p = cov.get("projected_pct") or 0
    if not cov.get("days_left"):
        pace = "warn"                       # 连考试日期都没填，无从判断
    elif p >= 80:
        pace = "ok"
    elif p >= 50:
        pace = "warn"
    else:
        pace = "bad"
    habit = "ok" if active_days >= 15 else ("warn" if active_days >= 8 else "bad")
    idle = tally.get("dead", 0) + tally.get("never", 0)
    build = "ok" if idle <= 3 else ("warn" if idle <= 6 else "bad")
    return {"pace": pace, "habit": habit, "build": build}
