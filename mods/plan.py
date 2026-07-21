"""40 天冲刺路线图：按剩余天数铺学习计划。

对标「考公 140 分」的强度贴，但按人能扛住的节奏重排：6 天推进 + 第 7 天复盘日。
所有「积累类」任务都落到 App 里现成的模块，不用再去外面找资料。
"""
import json
from datetime import datetime

from flask import Blueprint, jsonify, request

from core import _mark_study, _study_stats, current_user, get_db, uid
from mods.ai import _ai_call_or_error
from mods.review import RV_GROUP, RV_GROUPS, _review_due
from mods.team import _my_team

PLAN_EXAMS = ["四川省考", "国考", "事业单位", "其他"]

# 计划条目可以直达 App 里的对应功能，和消息中心用同一套 link 约定
PLAN_LINKS = ["review", "quiz", "changshi", "news", "sucai", "gaikuo",
              "wrongq", "idiom", "changkao", "shenlun", "find", "classics", "theory",
              "essays", "gongwen", "dtest", "drafts", "works", "partydict", "policydoc", ""]

bp = Blueprint("plan", __name__)


ROADMAP_40 = {
    "name": "40 天冲刺路线（对标 140 分强度）",
    "days": 40,
    "rhythm": "工作日推进 + 周末复盘：周一到周五学新内容，周六日不排新任务，回过头把本周的错题、"
              "新词、素材、真题再过一遍。周六复盘可略满（上午限时套题、下午全套订正归因、晚上错题过筛），"
              "周日更轻（错题再过一遍 + 本周新词素材快速回看 + 休半天）。不设「全天不休」——连轴转 40 天必"
              "塌方，周末复盘就是让你能扛完全程的那颗螺丝。",
    "priority": "资料分析 ＞ 言语理解 ＞ 判断推理 ＞ 常识判断(积累型) ＞ 数量关系(战略选做)",
    "priority_why": "资料分析题型固定、练了就稳、分值大，是性价比最高的；数量关系耗时最长、提升最慢，"
                    "只保 10 题左右的会做题，其余果断放弃换时间——140 分不是靠数量关系堆出来的。",
    # 每日固定动作：直接用 App 里已有的内容，不用另外找资料
    "fixed": [
        {"t": "晨读 30 分钟：读「常考」里的高频成语 / 实词 / 上位词", "link": "changkao",
         "note": "起床先背，别碰手机。读 App「常考」里按真题考频排的新词（不是复习你已收录的——那是「今日复习」的活，别重复）"},
        {"t": "碎片时间刷时政（替代刷短视频）", "link": "news",
         "note": "App「每日时政」每天自动更新，通勤/排队/洗漱时看，相当于半月谈每日时政"},
        {"t": "睡前 20 分钟：理论 / 要文 / 习语金句", "link": "theory",
         "note": "App「理论基础」「时政要文库」「习语金句」，睡前过一遍，常识和申论都吃这口"},
        {"t": "错题当天进错题本，绝不过夜", "link": "wrongq",
         "note": "App 错题本会自动判题型、给解析；错因写进「方法/技巧」栏，后面复盘全靠它"},
        {"t": "到期复习（遗忘曲线）", "link": "review",
         "note": "App「今日复习」按艾宾浩斯到期推送，先清它再学新的"},
        {"t": "巩固测试 10~15 题", "link": "dtest",
         "note": "在「任务清单 → 每日任务」里，按当天计划出题（行测五个板块都有），用「测试模式」自测"},
        {"t": "演算用草稿纸 / 草稿本", "link": "drafts",
         "note": "做题时左下角「📝 草稿纸」，平时演算用错题本里的「📓 草稿本」"},
    ],
    # 状态纪律（原贴的「140 分强度」，挑能长期执行的）
    "discipline": [
        "7:30 起 / 23:00 睡，作息固定——熬夜刷题第二天正确率必掉，得不偿失",
        "关掉朋友圈入口、不刷短视频、不看小说游戏；学崩了就去跑步，不是去玩手机",
        "行测每周至少 3 套限时套题，严格按考场时间（上午行测 / 下午申论）",
        "近 5 年真题反复刷（目标 3 遍以上），第二遍起用不同颜色重标难点与模糊点",
        "口诀/公式背到看见题眼就条件反射；资料分析的速算技巧必须形成肌肉记忆",
    ],
    "phases": [
        {
            "key": "P1", "name": "打牢根基", "d0": 1, "d1": 12,
            "focus": "系统课过一遍 + 建立每日积累与错题闭环。这一段不追速度，追「方法对不对、错因说不说得清」。",
            "quota": {"言语理解": 30, "判断推理": 30, "资料分析": 15, "数量关系": 10, "常识判断": 15},
            "shenlun": "每天 1 道小题（归纳概括/提出对策优先），用 App「真题批改」逐点批改，看采分点",
            "accuracy": {"言语理解": "70%", "判断推理": "70%", "资料分析": "80%", "数量关系": "50%", "常识判断": "55%"},
            "weekly": ["第 7 天复盘日：1 套行测限时套题（摸底，别怕分低）+ 全套订正归因"],
            "output": "错题本立起来（每题都有错因）；成语/实词日读不断；申论小题会「按点作答」",
        },
        {
            "key": "P2", "name": "专项拔高", "d0": 13, "d1": 28,
            "focus": "按薄弱模块死磕（App 会用你的错题分布告诉你哪块最弱）。资料分析先拉满，数量关系只练会做的题型。",
            "quota": {"言语理解": 30, "判断推理": 30, "资料分析": 20, "数量关系": 10, "常识判断": 15},
            "shenlun": "每天 2 小时：三天一套真题（小题是重心，分清主次）；每周一篇大作文（背模板 + 攒好词好句）",
            "accuracy": {"言语理解": "78%", "判断推理": "78%", "资料分析": "88%", "数量关系": "60%", "常识判断": "60%"},
            "weekly": ["每周 1~2 套行测限时套题", "错题第二轮：不同颜色重标难点 / 知识模糊点"],
            "output": "薄弱模块正确率追平其他模块；资料分析稳定 85%+；大作文有自己的模板与素材库",
        },
        {
            "key": "P3", "name": "套题强化", "d0": 29, "d1": 40,
            "focus": "进考场状态：上午行测、下午申论、晚上复盘。开始按「整套」训练节奏与取舍，而不是按模块。",
            "quota": {"言语理解": 25, "判断推理": 25, "资料分析": 20, "数量关系": 10, "常识判断": 20},
            "shenlun": "每天 2 小时，小题为重心；三天一篇大作文，掐时间写",
            "accuracy": {"言语理解": "85%", "判断推理": "80%", "资料分析": "90%+", "数量关系": "选做 10 题 ≥60%", "常识判断": "60%+"},
            "weekly": ["每周 3 套行测限时套题（严格 120 分钟，上午做）",
                       "错题本完整过 1 遍；变型多 / 复杂题型重点盯",
                       "时政 + 理论冲刺：要文库、理论基础、习语金句"],
            "output": "行测有稳定的做题顺序与放弃策略；套题成绩进入目标区间；错题不再重复错",
        },
    ],
    "after": "40 天只是把「根基 + 专项」做扎实。之后按原计划推进：9 月套题冲刺（每周 3 套 + 常识时政热点课），"
             "10 月起考前冲刺（严格按考试时间，早上行测、下午申论、晚上复盘，错题再过 3 遍）。"
             "省考在 12 月 7 日，时间够——别在 40 天里把自己榨干。",
}


def _plan_days_left(exam_date):
    if not exam_date:
        return None
    try:
        d = datetime.strptime(exam_date[:10], "%Y-%m-%d").date()
        return (d - datetime.now().date()).days
    except Exception:
        return None


def _plan_stats(db, today):
    """给 AI 的「学情快照」：全部来自真实数据，不让它凭空想象。"""
    st = {}
    due = _review_due(db, uid(), today)
    g = dict.fromkeys(RV_GROUPS, 0)
    for it in due:
        g[RV_GROUP.get(it["kind"], "wrongq")] += 1
    st["review_due"] = len(due)
    st["review_groups"] = g

    st["wrong_by_board"] = {r["board"]: r["c"] for r in db.execute(
        "SELECT COALESCE(NULLIF(board,''),'未分类') board, COUNT(*) c FROM wrong_questions "
        "WHERE user_id=? GROUP BY board ORDER BY c DESC", (uid(),))}

    st["quiz_undone"] = db.execute(
        "SELECT COUNT(*) FROM quiz_sets s WHERE NOT EXISTS("
        " SELECT 1 FROM quiz_answers a JOIN quiz_questions q ON q.id=a.qid "
        " WHERE q.set_id=s.id AND a.user_id=?)", (uid(),)).fetchone()[0]

    st["new_today"] = {
        "常识积累": db.execute("SELECT COUNT(*) FROM changshi_items WHERE date=?", (today,)).fetchone()[0],
        "每日时政": db.execute("SELECT COUNT(*) FROM news_items WHERE date(created_at)=?", (today,)).fetchone()[0],
        "议论文素材": db.execute("SELECT COUNT(*) FROM sucai_items WHERE date=?", (today,)).fetchone()[0],
        "概括句": db.execute("SELECT COUNT(*) FROM gaikuo_items WHERE date=?", (today,)).fetchone()[0],
    }
    st["entries"] = db.execute("SELECT COUNT(*) FROM entries WHERE user_id=?", (uid(),)).fetchone()[0]
    st["daily_tasks"] = [r["text"] for r in db.execute(
        "SELECT text FROM task_templates WHERE user_id=? AND active=1 ORDER BY sort,id", (uid(),))]
    st["graded"] = db.execute("SELECT COUNT(*) FROM shenlun_grade WHERE user_id=?", (uid(),)).fetchone()[0]
    st["find_done"] = db.execute("SELECT COUNT(*) FROM find_records WHERE user_id=?", (uid(),)).fetchone()[0]
    return st


@bp.get("/api/plan/profile")
def plan_profile_get():
    r = get_db().execute("SELECT * FROM plan_profile WHERE user_id=?", (uid(),)).fetchone()
    d = dict(r) if r else None
    if d:
        d["days_left"] = _plan_days_left(d.get("exam_date"))
    return jsonify({"profile": d, "exams": PLAN_EXAMS})


@bp.post("/api/plan/profile")
def plan_profile_set():
    d = request.get_json(silent=True) or {}
    exam = (d.get("exam") or "").strip() or "四川省考"
    exam_date = (d.get("exam_date") or "").strip()
    try:
        minutes = max(20, min(720, int(d.get("minutes") or 120)))
    except Exception:
        minutes = 120
    db = get_db()
    db.execute("INSERT INTO plan_profile(user_id,exam,exam_date,minutes,weak,note,updated_at) "
               "VALUES(?,?,?,?,?,?,datetime('now','localtime')) "
               "ON CONFLICT(user_id) DO UPDATE SET exam=excluded.exam, exam_date=excluded.exam_date, "
               "minutes=excluded.minutes, weak=excluded.weak, note=excluded.note, "
               "updated_at=excluded.updated_at",
               (uid(), exam, exam_date, minutes,
                (d.get("weak") or "").strip()[:120], (d.get("note") or "").strip()[:200]))
    db.commit()
    return plan_profile_get()


@bp.get("/api/plan/today")
def plan_today():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    p = db.execute("SELECT * FROM plan_profile WHERE user_id=?", (uid(),)).fetchone()
    prof = dict(p) if p else None
    if prof:
        prof["days_left"] = _plan_days_left(prof.get("exam_date"))
    rows = db.execute("SELECT * FROM plan_items WHERE user_id=? AND date=? ORDER BY seq, id",
                      (uid(), today)).fetchall()
    items = [dict(r) for r in rows]
    # 重点只属于生成它的那一天，隔天不再显示
    summary = (prof or {}).get("summary") if (prof or {}).get("summary_date") == today else ""
    return jsonify({
        "date": today, "profile": prof, "items": items, "summary": summary or "",
        "done_n": sum(1 for x in items if x["done"]),
        "total": len(items),
        "minutes_total": sum(x["minutes"] or 0 for x in items),
        "minutes_done": sum((x["minutes"] or 0) for x in items if x["done"]),
        "stats": _plan_stats(db, today),
        "study": _study_stats(db, uid()),
        "roadmap": _roadmap_state(db),        # 40 天冲刺：今天第几天、什么阶段、今日定额
    })


def _sync_plan_to_shared(db, date):
    """把我今天的备考规划镜像进「互监待办」，搭档就能交叉打勾监督我完成。
    只镜像当前用户的当天计划；旧的规划条目先清掉，保持同步。没组队就不同步。"""
    me = uid()
    old = [r[0] for r in db.execute(
        "SELECT id FROM shared_todos WHERE source='plan' AND src_uid=?", (me,))]
    if old:
        qs = ",".join("?" * len(old))
        db.execute("DELETE FROM shared_todo_done WHERE todo_id IN (%s)" % qs, old)
        db.execute("DELETE FROM shared_todos WHERE id IN (%s)" % qs, old)
    team = _my_team(db)
    if not team:
        return
    name = current_user()["username"]
    for r in db.execute("SELECT title, minutes FROM plan_items WHERE user_id=? AND date=? ORDER BY seq, id",
                        (me, date)):
        txt = (r["title"] or "").strip()
        if r["minutes"]:
            txt += "（%d 分钟）" % r["minutes"]
        db.execute("INSERT INTO shared_todos(text,created_by,source,src_uid,plan_date,team_id) "
                   "VALUES(?,?,'plan',?,?,?)", (txt[:200], name, me, date, team))


def _plan_snapshot(db, date, note=""):
    """把某天当前的计划存一份进 plan_log（重排/覆盖前调用，避免旧版丢失）。"""
    rows = db.execute("SELECT seq,title,module,minutes,reason,link,source,done FROM plan_items "
                      "WHERE user_id=? AND date=? ORDER BY seq, id", (uid(), date)).fetchall()
    if not rows:
        return
    items = [dict(r) for r in rows]
    prof = db.execute("SELECT summary, summary_date FROM plan_profile WHERE user_id=?", (uid(),)).fetchone()
    summary = (prof["summary"] if prof and prof["summary_date"] == date else "") or note
    db.execute("INSERT INTO plan_log(user_id,date,summary,minutes_total,done_n,total,items_json) "
               "VALUES(?,?,?,?,?,?,?)",
               (uid(), date, summary,
                sum(x["minutes"] or 0 for x in items),
                sum(1 for x in items if x["done"]), len(items),
                json.dumps(items, ensure_ascii=False)))


def _roadmap_state(db):
    """今天在 40 天路线图的第几天、属于哪个阶段、今天的定额是多少。"""
    r = db.execute("SELECT * FROM plan_roadmap WHERE user_id=?", (uid(),)).fetchone()
    if not r:
        return None
    try:
        data = json.loads(r["data_json"] or "{}")
        start = datetime.strptime((r["start_date"] or "")[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    total = r["days"] or 40
    now = datetime.now()
    n = (now.date() - start).days + 1
    phase = None
    if 1 <= n <= total:
        for p in data.get("phases", []):
            if p["d0"] <= n <= p["d1"]:
                phase = p
                break
    # 复盘日改按自然周末：周六 / 周日不排新任务，复盘本周内容（周六稍多、周日更轻）
    wd = now.weekday()                              # 周一=0 … 周六=5、周日=6
    weekend = "sat" if wd == 5 else ("sun" if wd == 6 else None)
    return {
        "start_date": r["start_date"], "days": total, "day": n,
        "over": n > total, "not_started": n < 1,
        "phase": phase,
        "review_day": bool(phase) and weekend is not None,   # 周末即复盘日
        "weekend": weekend,                                  # 'sat' / 'sun' / None
        "data": data,
    }


@bp.get("/api/plan/roadmap")
def roadmap_get():
    return jsonify({"roadmap": _roadmap_state(get_db())})


@bp.post("/api/plan/roadmap")
def roadmap_start():
    """开启（或重开）40 天冲刺路线。可顺带把「每天可学时长」一起设好。"""
    d = request.get_json(silent=True) or {}
    db = get_db()
    start = (d.get("start_date") or datetime.now().strftime("%Y-%m-%d"))[:10]
    days = max(7, min(120, int(d.get("days") or ROADMAP_40["days"])))
    db.execute("INSERT INTO plan_roadmap(user_id,start_date,days,data_json) VALUES(?,?,?,?) "
               "ON CONFLICT(user_id) DO UPDATE SET start_date=excluded.start_date, "
               "days=excluded.days, data_json=excluded.data_json, "
               "created_at=datetime('now','localtime')",
               (uid(), start, days, json.dumps(ROADMAP_40, ensure_ascii=False)))
    mins = d.get("minutes")
    if mins:
        db.execute("UPDATE plan_profile SET minutes=? WHERE user_id=?",
                   (max(20, min(720, int(mins))), uid()))
    db.commit()
    return jsonify({"roadmap": _roadmap_state(db)})


@bp.delete("/api/plan/roadmap")
def roadmap_stop():
    db = get_db()
    db.execute("DELETE FROM plan_roadmap WHERE user_id=?", (uid(),))
    db.commit()
    return jsonify({"ok": True})


def _roadmap_prompt(rm):
    """把今天在路线图里的位置，翻译成给规划助手看的硬约束。"""
    if not rm or not rm["phase"]:
        return ""
    p, d = rm["phase"], rm["data"]
    quota = "、".join("%s %d 题" % (k, v) for k, v in p["quota"].items())
    acc = "、".join("%s %s" % (k, v) for k, v in p["accuracy"].items())
    review = rm["review_day"]
    lines = [
        "\n【40 天冲刺路线·今天的硬约束】",
        "· 今天是第 %d / %d 天，阶段：%s（%s）" % (rm["day"], rm["days"], p["name"], p["focus"]),
    ]
    if review:   # 周末复盘：定额只当「复盘本周做过的题」的参考量，不是上新题
        lines.append("· 今日行测定额仅作复盘参考（复盘本周做过 / 错过的题，不排新题）：%s" % quota)
    else:
        lines.append("· 今日行测定额（必须排进去，可按薄弱模块微调，但总题量别少于八成）：%s" % quota)
    lines += [
        "· 申论：%s" % p["shenlun"],
        "· 本阶段正确率目标（写进 reason 里提醒他）：%s" % acc,
        "· 模块优先级：%s" % d.get("priority", ""),
        "· 每日固定动作（这些也要排成任务）：%s" % "；".join(x["t"] for x in d.get("fixed", [])),
    ]
    lines.append("· link 必须选对地方：晨读/背高频词 → changkao（读「常考」里的新词，"
                 "**不要**和「到期复习」重复，那是 review 的活）；巩固测试 → dtest（在「任务清单·每日任务」里，"
                 "**不是**题库 quiz）；到期复习 → review；错题 → wrongq；刷套卷 → quiz；申论 → shenlun。")
    if review:
        if rm.get("weekend") == "sat":
            lines.append("· ★ 今天是【周六复盘日】：周末不排新任务、不上新知识，回头复盘本周。可略满一点——"
                         "上午一套行测限时套题（严格 120 分钟）→ 下午全套订正 + 错因归因 → 晚上把本周错题过一遍。"
                         "排的任务都要指向「复习本周内容」（错题、真题订正、本周新词/素材回看），不要出现学新知识/上新题。")
        else:
            lines.append("· ★ 今天是【周日复盘日】：周末不排新任务，且要比周六更轻——本周错题再过一遍、"
                         "快速回看这周的新词/素材/时政，然后留出半天休息。任务别排满、时长比平日少，"
                         "同样不要出现学新知识/上新题的任务。")
    if p.get("weekly"):
        lines.append("· 本阶段每周要做到：%s" % "；".join(p["weekly"]))
    return "\n".join(lines) + "\n"


PLAN_SYS = ("你是公考备考规划师。只根据给出的「学情快照」排计划，不编造学生没有的数据；"
            "任务要具体到可执行（写清做什么、做多少），总时长贴近可用时间。"
            "若给了「40 天冲刺路线」的硬约束，必须照它的定额和优先级排，不得擅自缩水。严格输出 JSON。")


@bp.post("/api/plan/generate")
def plan_generate():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    p = db.execute("SELECT * FROM plan_profile WHERE user_id=?", (uid(),)).fetchone()
    if not p:
        return jsonify({"error": "请先填写备考信息（考试、日期、每天可学时长）"}), 400

    days = _plan_days_left(p["exam_date"])
    st = _plan_stats(db, today)
    minutes = p["minutes"] or 120

    phase = "基础打底"
    if days is None:
        phase = "常规推进"
    elif days <= 14:
        phase = "冲刺（以真题、错题、时政为主，少上新知识）"
    elif days <= 45:
        phase = "强化（模块专项 + 套卷训练）"
    elif days <= 120:
        phase = "提高（补短板 + 积累）"

    rm = _roadmap_state(db)
    road = _roadmap_prompt(rm)
    if rm and rm["phase"]:
        phase = "40 天冲刺路线 · 第 %d/%d 天 · %s" % (rm["day"], rm["days"], rm["phase"]["name"])
    # 任务条数跟着可学时长走：6~8 小时就该排 8~11 条，别再固定 4~6 条
    n_task = max(4, min(12, round(minutes / 45)))

    prompt = (
        "【备考信息】\n考试：%s\n距考试：%s\n今天可学习：%d 分钟\n薄弱环节：%s\n备注：%s\n阶段：%s\n\n"
        "【学情快照·今天】\n"
        "· 遗忘曲线到期需复习：%d 条（词语句子 %d / 每日积累 %d / 错题 %d）\n"
        "· 错题分布：%s\n"
        "· 题库里还没做过的套卷：%d 套\n"
        "· 今天新增内容：常识 %d 条、时政 %d 条、议论文素材 %d 条、概括句 %d 条\n"
        "· 已收录成语词语：%d 条；申论批改记录：%d 次；小题找点/写点练习：%d 次\n"
        "· 用户已有的每日固定打卡：%s\n"
        "%s\n"
        "请为今天排一份学习计划：\n"
        "· %d 条左右的任务，总时长控制在 %d 分钟上下（可 ±10%%）；\n"
        "· 到期复习和错题优先安排，其次按模块优先级补薄弱环节，再安排当天新增内容的积累；\n"
        "· 不要和「已有的每日固定打卡」重复；\n"
        "· 每条写清楚做什么、做多少（如「做 30 道图形推理并全部订正，错题进错题本」）；\n"
        "· reason 一句话说明为什么现在做这件事（引用上面的数字或正确率目标）；\n"
        "· link 从这个列表里选一个最相关的，选不出就填空字符串：%s\n"
        "  （其中：申论小题练找点/写点 → find；上传真题逐点批改 → shenlun）；\n"
        "· module 填所属模块（如「言语理解」「常识判断」「申论」「复习」「错题」）。\n"
        '只输出 JSON：{"summary":"一句话today的重点","items":[{"title":"","module":"","minutes":30,"reason":"","link":""}]}'
        % (p["exam"], ("%d 天" % days) if days is not None else "未设置考试日期",
           minutes, p["weak"] or "未填写", p["note"] or "无", phase,
           st["review_due"], st["review_groups"]["word"], st["review_groups"]["daily"],
           st["review_groups"]["wrongq"],
           (", ".join("%s %d 道" % (k, v) for k, v in st["wrong_by_board"].items()) or "暂无错题"),
           st["quiz_undone"],
           st["new_today"]["常识积累"], st["new_today"]["每日时政"],
           st["new_today"]["议论文素材"], st["new_today"]["概括句"],
           st["entries"], st["graded"], st["find_done"],
           ("、".join(st["daily_tasks"]) or "无"),
           road, n_task, minutes, "/".join(x for x in PLAN_LINKS if x)))

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": PLAN_SYS}, {"role": "user", "content": prompt}],
        temperature=0.4, max_tokens=2000, timeout=180, json_mode=True)
    if err:
        return err
    try:
        d = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502

    items = [x for x in (d.get("items") or []) if (x.get("title") or "").strip()][:14]
    if not items:
        return jsonify({"error": "AI 没有排出计划，请重试"}), 502

    # 重排会覆盖今天「AI 排的」那部分：先把当前这一版存进历史，别让它丢了
    _plan_snapshot(db, today)
    db.execute("DELETE FROM plan_items WHERE user_id=? AND date=? AND source='ai'", (uid(), today))
    base = db.execute("SELECT COALESCE(MAX(seq),0) FROM plan_items WHERE user_id=? AND date=?",
                      (uid(), today)).fetchone()[0]
    for i, x in enumerate(items, 1):
        link = (x.get("link") or "").strip()
        if link not in PLAN_LINKS:
            link = ""
        try:
            mins = max(5, min(300, int(x.get("minutes") or 20)))
        except Exception:
            mins = 20
        db.execute("INSERT INTO plan_items(user_id,date,seq,title,module,minutes,reason,link,source) "
                   "VALUES(?,?,?,?,?,?,?,?,'ai')",
                   (uid(), today, base + i, (x.get("title") or "").strip()[:120],
                    (x.get("module") or "").strip()[:20], mins,
                    (x.get("reason") or "").strip()[:200], link))
    db.execute("UPDATE plan_profile SET summary=?, summary_date=? WHERE user_id=?",
               ((d.get("summary") or "").strip()[:200], today, uid()))
    _sync_plan_to_shared(db, today)      # 同步进互监待办，方便搭档监督
    db.commit()
    return jsonify(plan_today().get_json())


@bp.post("/api/plan/item")
def plan_item_add():
    d = request.get_json(silent=True) or {}
    title = (d.get("title") or "").strip()
    if not title:
        return jsonify({"error": "请输入任务"}), 400
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM plan_items WHERE user_id=? AND date=?",
                     (uid(), today)).fetchone()[0]
    try:
        mins = max(5, min(300, int(d.get("minutes") or 20)))
    except Exception:
        mins = 20
    db.execute("INSERT INTO plan_items(user_id,date,seq,title,module,minutes,reason,link,source) "
               "VALUES(?,?,?,?,?,?,'','','manual')",
               (uid(), today, seq, title[:120], (d.get("module") or "").strip()[:20], mins))
    _sync_plan_to_shared(db, today)
    db.commit()
    return jsonify({"ok": True}), 201


@bp.post("/api/plan/<int:pid>/toggle")
def plan_toggle(pid):
    db = get_db()
    r = db.execute("SELECT done FROM plan_items WHERE id=? AND user_id=?", (pid, uid())).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    on = not r["done"]
    db.execute("UPDATE plan_items SET done=?, done_at=CASE WHEN ? THEN datetime('now','localtime') END "
               "WHERE id=?", (1 if on else 0, 1 if on else 0, pid))
    if on:      # 完成一项就算今天学习过了
        _mark_study(db, uid(), datetime.now().strftime("%Y-%m-%d"))
    db.commit()
    return jsonify({"done": on})


@bp.delete("/api/plan/<int:pid>")
def plan_del(pid):
    db = get_db()
    db.execute("DELETE FROM plan_items WHERE id=? AND user_id=?", (pid, uid()))
    today = datetime.now().strftime("%Y-%m-%d")
    _sync_plan_to_shared(db, today)
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/plan/restore/<int:log_id>")
def plan_restore(log_id):
    """把历史里的某一版（限当天）恢复成今天的计划；当前这版先存一份进历史。"""
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    r = db.execute("SELECT * FROM plan_log WHERE id=? AND user_id=?", (log_id, uid())).fetchone()
    if not r:
        return jsonify({"error": "未找到该版本"}), 404
    if r["date"] != today:
        return jsonify({"error": "只能恢复今天的版本"}), 400
    try:
        items = json.loads(r["items_json"] or "[]")
    except Exception:
        items = []
    _plan_snapshot(db, today)     # 当前版本也留一份，别覆盖丢了
    db.execute("DELETE FROM plan_items WHERE user_id=? AND date=? AND source='ai'", (uid(), today))
    base = db.execute("SELECT COALESCE(MAX(seq),0) FROM plan_items WHERE user_id=? AND date=?",
                      (uid(), today)).fetchone()[0]
    for i, x in enumerate([it for it in items if it.get("source") != "manual"], 1):
        db.execute("INSERT INTO plan_items(user_id,date,seq,title,module,minutes,reason,link,source,done,done_at) "
                   "VALUES(?,?,?,?,?,?,?,?,'ai',?,CASE WHEN ? THEN datetime('now','localtime') END)",
                   (uid(), today, base + i, (x.get("title") or "")[:120], (x.get("module") or "")[:20],
                    x.get("minutes") or 20, (x.get("reason") or "")[:200], x.get("link") or "",
                    1 if x.get("done") else 0, 1 if x.get("done") else 0))
    if r["summary"]:
        db.execute("UPDATE plan_profile SET summary=?, summary_date=? WHERE user_id=?",
                   (r["summary"].replace("【找回】", ""), today, uid()))
    _sync_plan_to_shared(db, today)
    db.commit()
    return jsonify({"ok": True})
