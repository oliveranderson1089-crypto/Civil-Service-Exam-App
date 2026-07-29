"""消息中心：有新内容就提醒，点开直达。


"""
from datetime import datetime

from flask import Blueprint, jsonify

from core import get_db, log, uid
from mods.review import RV_GROUP, RV_GROUPS, RV_NAMES, _review_due

bp = Blueprint("notifications", __name__)


def _n(db, kind, dkey, title, body, link):
    """写一条通知；同一个用户、同一类、同一天只会有一条。"""
    db.execute("INSERT OR IGNORE INTO notifications(user_id,kind,dkey,title,body,link) "
               "VALUES(?,?,?,?,?,?)", (uid(), kind, dkey, title, body, link))


def _topic_brief(rows, n=3):
    """把「板块·专题」列成一句人话：人文常识·文学常识、科技常识·物理常识 等"""
    parts = ["%s·%s" % (r["board"], r["topic"]) for r in rows[:n]]
    return "、".join(parts) + ("　等" if len(rows) > n else "")


def _gen_notifications(db):
    """按各内容库的当日数据现算通知——不用改那一堆定时脚本，也不会漏。"""
    today = datetime.now().strftime("%Y-%m-%d")

    # 常识积累（人文/科技/法律 每天新增）
    rows = db.execute("SELECT board, topic, COUNT(*) c FROM changshi_items WHERE date=? "
                      "GROUP BY board, topic ORDER BY c DESC", (today,)).fetchall()
    if rows:
        total = sum(r["c"] for r in rows)
        _n(db, "changshi", today, "常识积累更新了 %d 条" % total,
           _topic_brief(rows), "changshi")

    # 新出法律单独提醒（考前一年新法是必考点）
    nl = db.execute("SELECT title FROM changshi_items WHERE date=? AND board='法律常识' "
                    "AND topic='其他新出法律'", (today,)).fetchall()
    if nl:
        _n(db, "newlaw", today, "新增 %d 部新法要点" % len(nl),
           "、".join(r["title"] for r in nl[:3]), "changshi:法律常识")

    # 每日时政
    c = db.execute("SELECT COUNT(*) FROM news_items WHERE date(created_at)=?", (today,)).fetchone()[0]
    if c:
        _n(db, "news", today, "每日时政更新了 %d 条" % c, "党内 / 国内 / 四川 / 国际", "news")

    # 习语金句
    c = db.execute("SELECT COUNT(*) FROM xiyu_items WHERE date=?", (today,)).fetchone()[0]
    if c:
        _n(db, "xiyu", today, "习语金句更新了 %d 条" % c, "总书记重要讲话金句 + 申论运用", "xiyu")

    # 议论文素材 / 概括句
    c = db.execute("SELECT COUNT(*) FROM sucai_items WHERE date=?", (today,)).fetchone()[0]
    if c:
        _n(db, "sucai", today, "议论文素材更新了 %d 条" % c, "人物事例 / 具体事例 / 理论论据 / 衔接表达", "sucai")
    c = db.execute("SELECT COUNT(*) FROM gaikuo_items WHERE date=?", (today,)).fetchone()[0]
    if c:
        _n(db, "gaikuo", today, "概括句积累更新了 %d 条" % c, "材料表述 → 规范概括句", "gaikuo")

    # 范文推荐：每日更新一套新话题（含大作文 + 应用文小题）
    ep = db.execute("SELECT topic FROM essay_papers WHERE date(created_at)=? ORDER BY id DESC LIMIT 1",
                    (today,)).fetchone()
    if ep:
        _n(db, "essay", today, "范文更新了新话题：%s" % ep["topic"],
           "大作文范文 + 应用文小题完整参考答案", "essays")

    # 今日复习（遗忘曲线到期）
    due = _review_due(db, uid(), today)
    if due:
        g = dict.fromkeys(RV_GROUPS, 0)
        for it in due:
            g[RV_GROUP.get(it["kind"], "wrongq")] += 1
        # 明细按 RV_NAMES 现拼，别手抄组名：原先写死「词语句子·每日积累·错题」，
        # 后来加的批注、古诗在这条通知里根本不露面。只列有货的组，省得一串 0。
        _n(db, "review", today, "今天有 %d 条要复习" % len(due),
           " · ".join("%s %d" % (RV_NAMES[k], g[k]) for k in RV_GROUPS if g[k]), "review")

    # 今日学习计划
    pl = db.execute("SELECT COUNT(*) n, SUM(done) d, SUM(minutes) m FROM plan_items "
                    "WHERE user_id=? AND date=?", (uid(), today)).fetchone()
    if pl and pl["n"]:
        undone = pl["n"] - (pl["d"] or 0)
        if undone:
            _n(db, "plan", today, "今日计划还剩 %d 项" % undone,
               "共 %d 项 · %d 分钟，已完成 %d 项" % (pl["n"], pl["m"] or 0, pl["d"] or 0), "tasks")
    elif db.execute("SELECT 1 FROM plan_profile WHERE user_id=?", (uid(),)).fetchone():
        _n(db, "plan", today, "今天还没有学习计划",
           "让规划助手看着你的复习进度和错题排一份", "tasks")

    # 每日任务未打卡
    tpls = db.execute("SELECT COUNT(*) FROM task_templates WHERE user_id=? AND active=1", (uid(),)).fetchone()[0]
    if tpls:
        done = db.execute("SELECT COUNT(*) FROM task_done WHERE user_id=? AND date=?", (uid(), today)).fetchone()[0]
        if done < tpls:
            _n(db, "tasks", today, "今日任务还剩 %d 项" % (tpls - done),
               "已完成 %d / %d，别断卡" % (done, tpls), "tasks")

    # 题库新卷
    q = db.execute("SELECT name FROM quiz_sets WHERE date(created_at)=? ORDER BY id DESC", (today,)).fetchall()
    if q:
        _n(db, "quiz", today, "题库新增 %d 套卷" % len(q), q[0]["name"], "quiz")

    db.commit()


@bp.get("/api/notifications")
def notifications_list():
    db = get_db()
    try:
        _gen_notifications(db)
    except Exception:              # 生成失败不能影响读消息
        log.warning("生成通知失败，本次只返回已有消息", exc_info=True)
    rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY read, id DESC LIMIT 60",
                      (uid(),)).fetchall()
    # 聊天消息另有专属角标（聊天入口红点），别再让消息铃铛重复计数
    unread = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0 AND kind IS NOT 'chat'",
                        (uid(),)).fetchone()[0]
    return jsonify({"items": [dict(r) for r in rows], "unread": unread})


@bp.get("/api/notifications/unread")
def notifications_unread():
    """轻量角标：只数未读，不触发生成。聊天消息不计入（它有自己的红点）。"""
    n = get_db().execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0 AND kind IS NOT 'chat'",
                         (uid(),)).fetchone()[0]
    return jsonify({"unread": n})


@bp.post("/api/notifications/<int:nid>/read")
def notification_read(nid):
    db = get_db()
    db.execute("UPDATE notifications SET read=1 WHERE id=? AND user_id=?", (nid, uid()))
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/notifications/read_all")
def notifications_read_all():
    db = get_db()
    db.execute("UPDATE notifications SET read=1 WHERE user_id=?", (uid(),))
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/notifications")
def notifications_clear():
    db = get_db()
    db.execute("DELETE FROM notifications WHERE user_id=? AND read=1", (uid(),))
    db.commit()
    return jsonify({"ok": True})
