"""产出健康：每个内容域今天到底出货了没有。

为什么要有这一块：systemd 只认退出码，**退出码 0 不等于有产出**。上游断供、
抓到空、AI 返回空正文，脚本照样 exit 0、服务管理里一片绿，界面上还会反过来
显示「都写齐了」——素材链路真实踩过这个坑，而且是无声的。

所以这里换一个角度：不问「任务跑了没」，问「库里有没有新东西」。
判据只有两条 SQL（最新一条的日期 + 今天新增几条），不依赖 AI、不依赖脚本埋点，
所以 AI 挂了、脚本改了，这块照样能说话。

把内容日期和 systemd 的触发时间**对起来**，才能分清三种完全不同的故障：
  - 任务报错     → 单元 failed，去看 journal
  - 静默失败     → 单元成功、内容产出之后还跑过，但没出新东西（上游断供多半长这样）
  - 根本没跑     → 自上次产出以来就没触发过（定时器停了/没 enable）
前两种在服务管理页面长得一模一样，这里必须区分开——这是整块的价值所在。

加一个内容域 = 在 DOMAINS 加一行，不写逻辑。
"""
from datetime import date, datetime

from flask import Blueprint, jsonify

from core import get_db, log
from mods import ops

bp = Blueprint("health", __name__)

# key, 显示名, 表, 时间列, SLA(允许的最大陈旧天数), 负责单元, 一句话说明
# SLA 按定时器频率给，并留一天容错：每天早上跑的任务，昨天的货算正常（今天的可能还没到点）。
DOMAINS = [
    ("sucai",  "每日素材",   "sucai_items",    "date",       1, "gongkao-write.timer",
     "每天 08:40，上游是 OpenClaw 的 kaogong 缓存"),
    ("essay",  "每日成文",   "daily_essays",   "date",       1, "gongkao-write.timer",
     "每天 08:40，议论文＋应用文，用当天素材写"),
    ("news",   "时政新闻",   "news_items",     "created_at", 1, "gongkao-news.timer",
     "每天 06:30 / 12:40 / 18:40 抓三次"),
    ("gaikuo", "概括练习",   "gaikuo_items",   "created_at", 1, "gongkao-news.timer",
     "跟着新闻一起出，新闻有货它就该有"),
    ("changshi", "常识速记", "changshi_items", "date",       1, "gongkao-changshi.timer",
     "每天 06:50"),
    ("shenlun", "申论套卷",  "essay_papers",   "created_at", 1, "gongkao-essay.timer",
     "每天 05:40"),
    ("fanwen", "时评范文",   "essay_models",   "created_at", 2, "gongkao-fanwen.timer",
     "每天 07:10 抓人民时评，偶尔当天没更新"),
    ("video",  "视频资源",   "video_items",    "created_at", 2, "gongkao-video.timer",
     "每天 07:20，抓不到新的属正常"),
    ("exam",   "考试公告",   "exam_notices",   "created_at", 2, "gongkao-exam.timer",
     "每天 07:20 / 19:20，非招考季本来就少"),
    ("drill",  "练习题库",   "drill_bank",     "created_at", 2, "gongkao-warmbank.timer",
     "每天 03:20 补到 30 道可用；库存见下方数字"),
    ("quiz",   "阶段测验",   "quiz_sets",      "created_at", 4, "gongkao-quiz.timer",
     "每周二、周五 07:40"),
]

_HINTS = {
    "unit_failed": "定时任务报错了——点单元名看日志",
    "silent": "任务跑过但没出新内容：多半是上游断供或 AI 返回空，看日志确认",
    "not_run": "自上次产出以来就没触发过：检查定时器是否还 enabled",
    "never_run": "这个单元从来没跑过",
    "no_unit": "拿不到 systemd 状态（systemctl 不可用？）",
    "empty": "这个域一条数据都没有",
}


def _cols(db, table):
    """表存在返回它的列名集合，不存在返回空集——schema 会漂移，探针不能因此崩掉。"""
    try:
        return {r["name"] for r in db.execute("PRAGMA table_info(%s)" % table).fetchall()}
    except Exception:
        log.debug("PRAGMA table_info(%s) 失败", table, exc_info=True)
        return set()


def _daydiff(a, b):
    """a - b，按天。两边都是 YYYY-MM-DD。"""
    try:
        return (datetime.strptime(a, "%Y-%m-%d").date()
                - datetime.strptime(b, "%Y-%m-%d").date()).days
    except ValueError:
        return None


def _probe(db, key, name, table, col, sla, unit, note, today):
    """量一个内容域：最新产出日期、今日新增、存量。只读，两条 SQL。"""
    # unit 是 .timer（判新鲜度要它的上次触发时间），svc 是对应的 .service：
    # 「立即补跑」必须对 service 下手——restart 一个 timer 只会重置计时器，任务一次都不会跑。
    row = {"key": key, "name": name, "table": table, "unit": unit, "sla": sla,
           "svc": unit.replace(".timer", ".service"),
           "note": note, "last": "", "lag": None, "today_n": 0, "total": 0,
           "state": "unknown", "reason": "", "hint": ""}
    if col not in _cols(db, table):
        # 表或列没了（改名/删表），当场说出来，别静悄悄跳过——静默正是这块要治的病
        row["hint"] = "表 %s 或时间列 %s 不存在，探针失效" % (table, col)
        return row
    try:
        # 时间列有的是 'YYYY-MM-DD'、有的是 'YYYY-MM-DD HH:MM:SS'，一律截前 10 位比日期
        r = db.execute(
            "SELECT MAX(substr(%s,1,10)) last, COUNT(*) total, "
            "SUM(CASE WHEN substr(%s,1,10)=? THEN 1 ELSE 0 END) today_n "
            "FROM %s" % (col, col, table), (today,)).fetchone()
    except Exception as e:
        row["hint"] = "查询失败：%s" % e
        return row
    row["total"] = r["total"] or 0
    row["today_n"] = r["today_n"] or 0
    row["last"] = r["last"] or ""
    if not row["last"]:
        row["state"], row["reason"] = "down", "empty"
        return row
    lag = _daydiff(today, row["last"])
    row["lag"] = lag
    if lag is None:
        row["hint"] = "时间列 %s 的值不是日期（%s）" % (col, row["last"])
        return row
    # ok / warn / down：宽限期就一天。每日任务落后 2 天算待观察、3 天算断供。
    row["state"] = "ok" if lag <= sla else ("warn" if lag <= sla + 1 else "down")
    return row


def _diagnose(row, timer_row, svc_row):
    """内容不新鲜时，把锅分给 systemd 还是分给上游。

    看 service 而不是 timer：失败的、有执行时间的都是 service，timer 只负责按点戳它。
    """
    # state=="ok" 不用归因；reason=="empty" 或已有 hint（表/列不存在、查询失败）
    # 说明 _probe 已经把话说清楚了——不能再往下跑，否则会把 reason 错写成
    # silent/not_run 之类，跟 hint 自相矛盾（这里的陈旧跟 systemd 没有任何关系）。
    if row["state"] == "ok" or row["reason"] == "empty" or row["hint"]:
        return
    if not (svc_row or timer_row):
        row["reason"] = "no_unit"
        return
    if svc_row and not svc_row.get("healthy"):
        row["reason"] = "unit_failed"
        return
    last_run = ((svc_row or {}).get("last_run")
                or (timer_row or {}).get("last_run") or "")[:10]
    if not last_run:
        row["reason"] = "never_run"
    elif last_run > row["last"]:
        # 内容产出之后单元还跑过，却没出新东西 —— 这就是静默失败
        row["reason"] = "silent"
    else:
        row["reason"] = "not_run"


def snapshot():
    """全量体检。systemd 拿不到也照常返回内容结论——两条腿，断一条不瘫。"""
    db = get_db()
    today = date.today().isoformat()
    try:
        units = {u["name"]: u for u in ops.status()}
    except Exception:
        log.warning("读 systemd 状态失败，健康看板只给内容结论", exc_info=True)
        units = {}

    rows = []
    for key, name, table, col, sla, unit, note in DOMAINS:
        row = _probe(db, key, name, table, col, sla, unit, note, today)
        t, s = units.get(unit), units.get(row["svc"])
        _diagnose(row, t, s)
        if t or s:
            row["unit_healthy"] = bool((s or t).get("healthy"))
            row["last_run"] = (s or {}).get("last_run") or (t or {}).get("last_run") or ""
            row["next_run"] = (t or {}).get("next_run") or ""
        if row["reason"] and not row["hint"]:
            row["hint"] = _HINTS.get(row["reason"], "")
        rows.append(row)
    # 出事的排前面：手机上第一屏就该是要处理的东西
    order = {"down": 0, "unknown": 1, "warn": 2, "ok": 3}
    rows.sort(key=lambda r: (order.get(r["state"], 9), -(r["lag"] or 0)))
    return today, rows


@bp.get("/api/admin/health")
def health():
    today, rows = snapshot()
    counts = {"ok": 0, "warn": 0, "down": 0, "unknown": 0}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    return jsonify({"today": today, "counts": counts, "domains": rows})
