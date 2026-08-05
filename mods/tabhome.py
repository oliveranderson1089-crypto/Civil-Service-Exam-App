"""「库」和「我的」两个标签页的首屏聚合接口（界面重构 P4）。

走的是 mods/today.py 那条路子：一屏要显示的东西散在七八张表里，做成一个接口一次取回。
手机上串行发五六个请求，数字会一格一格往外跳，比慢更难受。

只读，不写任何表。每一格各自兜底 —— 缺一张表、脏一条数据，只该让那一格空着，
不该把整页打成「请求失败」（这库上真出过：少一张表 → 接口返 HTML → 前端一律弹「请求失败」）。
"""
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify

from core import _study_stats, get_db, uid

bp = Blueprint("tabhome", __name__)


def _rows(db, sql, args=()):
    """取一批行。任何一格出问题都只赔这一格，不连坐整屏。"""
    try:
        return db.execute(sql, args).fetchall()
    except Exception:
        return []


def _num(db, sql, args=()):
    r = _rows(db, sql, args)
    try:
        return int(r[0][0] or 0) if r and r[0][0] is not None else 0
    except Exception:
        return 0


_TAG = re.compile(r"<[^>]+>")
_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _brief(s, n=34):
    """小记没有标题，拿正文首行当标题：先去掉图片和标签，再截断。
    截断前先掐到第一个换行 —— 长笔记的第二行往往和第一行毫无关系，混在一行里读不通。"""
    s = _TAG.sub("", _IMG.sub("", s or "")).strip()
    s = s.split("\n", 1)[0].strip()
    return (s[:n] + "…") if len(s) > n else (s or "无标题")


# 「库」里五个容器各自怎么取最近的几条。
# 六元组：(前端认的 kind, 显示用的分类名, 表, 取 id/标题/时间的 SQL)
# 时间列各表不一样：小记/知识库/草稿本有 updated_at（改过就算最近打开），
# 资料库和云盘只有 created_at（它们是「传进来」的，没有编辑动作）。
_RECENT = [
    ("note", "小记",
     "SELECT id, COALESCE(content,''), updated_at FROM notes "
     "WHERE user_id=? ORDER BY updated_at DESC, id DESC LIMIT 6"),
    ("kbdoc", "知识库",
     "SELECT id, COALESCE(NULLIF(title,''),'无标题文档'), updated_at FROM kb_nodes "
     "WHERE user_id=? AND type='doc' ORDER BY updated_at DESC, id DESC LIMIT 6"),
    ("draft", "草稿本",
     "SELECT id, COALESCE(NULLIF(title,''),'未命名草稿'), updated_at FROM drafts "
     "WHERE user_id=? ORDER BY updated_at DESC, id DESC LIMIT 6"),
    ("material", "资料库",
     "SELECT id, COALESCE(NULLIF(title,''),COALESCE(orig_name,'')), created_at FROM materials "
     "WHERE user_id=? ORDER BY id DESC LIMIT 6"),
    ("drive", "云盘",
     "SELECT id, COALESCE(name,''), created_at FROM drive_files "
     "WHERE owner_id=? AND is_dir=0 AND COALESCE(deleted_at,'')='' ORDER BY id DESC LIMIT 6"),
]


@bp.get("/api/lib/home")
def lib_home():
    """库首屏：五个容器各有多少东西 + 最近打开过什么。"""
    db = get_db()
    u = uid()
    counts = {
        "note": _num(db, "SELECT COUNT(*) FROM notes WHERE user_id=?", (u,)),
        "kb": _num(db, "SELECT COUNT(*) FROM kb_nodes WHERE user_id=? AND type='doc'", (u,)),
        "draft": _num(db, "SELECT COUNT(*) FROM drafts WHERE user_id=?", (u,)),
        "material": _num(db, "SELECT COUNT(*) FROM materials WHERE user_id=?", (u,)),
        "drive": _num(db, "SELECT COUNT(*) FROM drive_files WHERE owner_id=? AND is_dir=0 "
                          "AND COALESCE(deleted_at,'')=''", (u,)),
        "star": _star_count(db, u),
    }
    recent = []
    for kind, label, sql in _RECENT:
        for r in _rows(db, sql, (u,)):
            title = _brief(r[1]) if kind == "note" else (r[1] or "无标题")
            recent.append({"kind": kind, "label": label, "id": r[0],
                           "title": title, "at": r[2] or ""})
    recent.sort(key=lambda x: x["at"], reverse=True)
    return jsonify({"counts": counts, "recent": recent[:8]})


# 收藏散在六个模块里，各存各的表 —— 这是把它们并成一张单子的地方。
# 五元组：(kind, 分类名, SQL；取 标题/副标题/跳转用的 id 或板块名/收藏时间)
_STARS = [
    ("ck", "词语",
     "SELECT title, COALESCE(board,''), COALESCE(board,''), created_at FROM ck_stars "
     "WHERE user_id=? ORDER BY created_at DESC LIMIT 60"),
    ("entry", "成语词语",
     "SELECT word, COALESCE(explanation,''), CAST(id AS TEXT), COALESCE(created_at,'') FROM entries "
     "WHERE user_id=? AND starred=1 ORDER BY id DESC LIMIT 60"),
    ("classic", "古诗文",
     "SELECT c.title, COALESCE(c.author,''), CAST(c.id AS TEXT), s.created_at "
     "FROM classic_stars s JOIN classics c ON c.id=s.classic_id "
     "WHERE s.user_id=? ORDER BY s.created_at DESC LIMIT 60"),
    ("fanwen", "人民时评",
     "SELECT m.title, COALESCE(m.column_name,''), CAST(m.id AS TEXT), s.created_at "
     "FROM essay_model_stars s JOIN essay_models m ON m.id=s.model_id "
     "WHERE s.user_id=? ORDER BY s.created_at DESC LIMIT 60"),
    ("news", "时政",
     "SELECT n.title, COALESCE(n.source,''), CAST(n.id AS TEXT), s.created_at "
     "FROM news_stars s JOIN news_items n ON n.id=s.news_id "
     "WHERE s.user_id=? ORDER BY s.created_at DESC LIMIT 60"),
    ("video", "新闻视频",
     "SELECT v.title, COALESCE(v.column_name,''), CAST(v.id AS TEXT), s.created_at "
     "FROM video_stars s JOIN video_items v ON v.id=s.video_id "
     "WHERE s.user_id=? ORDER BY s.created_at DESC LIMIT 60"),
]


def _star_count(db, u):
    n = 0
    for _, _, sql in _STARS:
        n += len(_rows(db, sql, (u,)))
    return n


@bp.get("/api/lib/stars")
def lib_stars():
    """收藏夹：六个模块的星标并成一张单子，按收藏时间倒序。"""
    db = get_db()
    u = uid()
    items = []
    for kind, label, sql in _STARS:
        for r in _rows(db, sql, (u,)):
            items.append({"kind": kind, "label": label, "title": r[0] or "",
                          "sub": r[1] or "", "ref": r[2] or "", "at": r[3] or ""})
    items.sort(key=lambda x: x["at"], reverse=True)
    return jsonify({"items": items})


def _week_range(now=None):
    """本周：周一到周日。用 ISO 的周一起算 —— 备考的一周就是这么排的。"""
    now = now or datetime.now()
    mon = (now - timedelta(days=now.weekday())).date()
    return mon.isoformat(), (mon + timedelta(days=6)).isoformat()


@bp.get("/api/me/home")
def me_home():
    """我的首屏：本周计划完成度 + 今天的任务 + 两处未读。

    完成度**只算备考规划（plan_items）**：没排计划就返回 pct=null，
    让前端说「本周还没有计划」。糊一个 0% 或者拿任务清单凑一个漂亮的数，
    都是在骗自己 —— 首页那个环当初就是为这条定的规矩。
    """
    db = get_db()
    u = uid()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    mon, sun = _week_range(now)

    p = _rows(db, "SELECT COUNT(*), COALESCE(SUM(done),0) FROM plan_items "
                  "WHERE user_id=? AND date BETWEEN ? AND ?", (u, mon, sun))
    total, done = (int(p[0][0] or 0), int(p[0][1] or 0)) if p else (0, 0)
    week = {"from": mon, "to": sun, "done": done, "total": total,
            "pct": round(done * 100 / total) if total else None}

    # 本周练了多少：真题 + 专项练（按秒）+ 巩固测试（按套，不记秒）
    q = 0
    secs = 0.0
    for tbl in ("real_records", "drill_records"):
        r = _rows(db, "SELECT COALESCE(SUM(total),0), COALESCE(SUM(seconds),0) FROM %s "
                      "WHERE user_id=? AND date(created_at) BETWEEN ? AND ?" % tbl, (u, mon, sun))
        if r:
            q += int(r[0][0] or 0)
            secs += float(r[0][1] or 0)
    q += _num(db, "SELECT COALESCE(SUM(total),0) FROM dtest_records "
                  "WHERE user_id=? AND date BETWEEN ? AND ?", (u, mon, sun))

    t_total = _num(db, "SELECT COUNT(*) FROM task_templates WHERE user_id=? AND active=1", (u,))
    t_done = _num(db, "SELECT COUNT(*) FROM task_done WHERE user_id=? AND date=?", (u, today))

    return jsonify({
        "week": week,
        "questions": q,
        "minutes": int(secs // 60),
        "tasks": {"done": t_done, "total": t_total},
        "study": _study_stats(db, u),
        "unread": {
            "notify": _num(db, "SELECT COUNT(*) FROM notifications "
                               "WHERE user_id=? AND read=0 AND kind IS NOT 'chat'", (u,)),
            "chat": _num(db, "SELECT COUNT(*) FROM chat_msgs WHERE to_uid=? AND read_at IS NULL", (u,)),
        },
    })
