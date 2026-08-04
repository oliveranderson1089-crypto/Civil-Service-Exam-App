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

from core import get_db, log, uid
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

def _drill_cells():
    from mods.drill import DRILL_LEVELS, DRILL_TYPES
    return [(b, t, lv)
            for b, types in DRILL_TYPES.items()
            for t, _desc, eng in types if eng == "ai"
            for lv in DRILL_LEVELS]


def _mine_left(db, cells, user):
    """这个人每格还剩多少道**没做过**的题。拿不到就返回 None（当作不知道，别瞎报）。

    跟库存是两个问题：库存问「题库健不健康」（空格子＝谁点都出不了题，是故障），
    这里问「我还有多少新题可刷」（见底不是故障，是该补新题的预警）。
    """
    if not user:
        return None
    try:
        got = {(r["board"], r["qtype"], r["level"]): r["n"] for r in db.execute(
            "SELECT board, qtype, level, COUNT(*) n FROM drill_bank "
            "WHERE agree='1' AND sig NOT IN (SELECT sig FROM drill_seen WHERE user_id=?) "
            "GROUP BY board, qtype, level", (user,))}
    except Exception:
        log.debug("按人算题库余量失败（drill_seen 还没建？）", exc_info=True)
        return None
    return {c: got.get(c, 0) for c in cells}


def _stock_drill(db, user=None):
    """练习题库的水位：每个「板块×题型×难度」格子还剩多少道过了核验的题。

    返回 (state, hint, usable)。usable 是**能发给人做的**道数 —— 卡片上的「存量」
    原先是 COUNT(*)，把 689 道存疑题也算了进去（虚高 24%），而那些题永远不会发出去。
    存疑题该留在库里（能回查、出新题时还拿它们避重），但不能冒充库存。

    口径必须跟 warm_drill_bank.py 对齐（agree='1' 才算可用、每格目标 30 道），
    两边对不上，就会出现「这里说库满、那边还在补」的自相矛盾。

    传了 user 就**再按人算一遍余量**。刷得快不是故障，所以它不把卡片刷红，
    只多说一个实数；只有真被刷穿（某格一道没做过的都不剩、只能发复习题）才降级 ——
    那种情况否则完全看不见：即时补库每次都排队，但 AI 可能一直出不出新题
    （被判重复/存疑刷掉），你只会一直拿到复习题，而这儿还一片绿。
    """
    target = 30
    cells = _drill_cells()
    have = {(r["board"], r["qtype"], r["level"]): r["n"] for r in db.execute(
        "SELECT board, qtype, level, COUNT(*) n FROM drill_bank "
        "WHERE agree='1' GROUP BY board, qtype, level")}
    # 只数格子里的：板块/题型改过名之后，库里会留下对不上任何格子的旧题，
    # 它们同样发不出去，不该算进「可用」。
    usable = sum(have.get(c, 0) for c in cells)
    short = [(c, have.get(c, 0)) for c in cells if have.get(c, 0) < target]
    empty = [c for c, n in short if n == 0]
    if empty:
        # 空格子 = 用户点这个题型直接出不了题，这是真故障，不是「待观察」
        return "down", "%d 格一道可用题都没有，点了会出不了题：%s" % (
            len(empty), "、".join("%s·%s/%s" % c for c in empty[:3])), usable
    if short:
        return "warn", "%d/%d 格不足 %d 道（最少的一格 %d 道），等下次补库" % (
            len(short), len(cells), target, min(n for _, n in short)), usable

    # ⚠️ 别把「今日新增 0」写死进这句话：补过库的当天新增就不是 0（实测 87 道），
    #    卡片会一边显示「今日 87」一边说「今日新增 0 是正常的」，自己打自己的脸。
    ok = "%d 格每格都有 ≥%d 道可用；补满就不再出题，今日没有新增也正常" % (len(cells), target)
    left = _mine_left(db, cells, user)
    if left is None:
        return "ok", ok, usable
    dry = [c for c, n in left.items() if n == 0]
    if dry:
        # 「立即补跑」在这儿**真的有用**（warmbank 已改成按人算余量：把最惨的那个人
        # 补够为止），但 AI 出题要几分钟，所以照实说等多久、以及夜里本来也会补。
        return "warn", ("%d 格你已经全做过了，只能发复习题：%s。今晚 03:20 会自动补；"
                        "等不及就点「立即补跑」，出题要几分钟"
                        % (len(dry), "、".join("%s·%s/%s" % c for c in dry[:3]))), usable
    return "ok", ok + "。你还没做过的：最少的一格剩 %d 道" % min(left.values()), usable


# 水位型内容域：脚本的职责是把库存补到阈值，不是每天出新货。
# 这类域拿「最新产出日期」量必然误报——库一填满，补库脚本就该什么都不干，
# created_at 于是永远停在最后一次补库那天，过几天必报断供（练习题库真踩过：
# 每天正常跑完、每格都满 30 道，界面上却一直红着说断供）。
# 它们要问的是另一个问题：水位还够不够发题。
STOCK = {"drill": _stock_drill}

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


def snapshot(user=None):
    """全量体检。systemd 拿不到也照常返回内容结论——两条腿，断一条不瘫。

    user 只给水位型域用来「按人算余量」（我还有多少新题可刷），不传就只报库存。
    参数化而不是在里头 uid()：这函数得能在请求之外跑（测试、以后可能的巡检脚本）。
    """
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
        if key in STOCK and not row["hint"]:
            # hint 非空说明表/列失效，_probe 已经把话说清楚了，别拿水位盖掉
            try:
                row["state"], row["hint"], row["usable"] = STOCK[key](db, user)
                row["reason"] = ""
            except Exception as e:
                log.warning("水位探针 %s 失败", key, exc_info=True)
                row["state"], row["hint"] = "unknown", "水位探针失败：%s" % e
            if s and not s.get("healthy"):
                # 水位够不够是一回事，补库任务本身报错是另一回事，两件都得说
                row["reason"] = "unit_failed"
                row["hint"] = _HINTS["unit_failed"] + "；" + row["hint"]
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
    # 按人算的那部分算的是**看这个页面的人**自己的余量：后台是管理员自己在看，
    # 「我还有多少新题可刷」问的就是他自己，不是全站最惨的那个用户。
    today, rows = snapshot(uid())
    counts = {"ok": 0, "warn": 0, "down": 0, "unknown": 0}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    return jsonify({"today": today, "counts": counts, "domains": rows})
