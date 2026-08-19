"""「库」和「我的」两个标签页的首屏聚合接口（界面重构 P4）。

走的是 mods/today.py 那条路子：一屏要显示的东西散在七八张表里，做成一个接口一次取回。
手机上串行发五六个请求，数字会一格一格往外跳，比慢更难受。

只读，不写任何表。每一格各自兜底 —— 缺一张表、脏一条数据，只该让那一格空着，
不该把整页打成「请求失败」（这库上真出过：少一张表 → 接口返 HTML → 前端一律弹「请求失败」）。
"""
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

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


def _brief(s, alt="无标题", n=34):
    """小记没有标题，拿正文首行当标题：先去掉图片和标签，再截断。
    截断前先掐到第一个换行 —— 长笔记的第二行往往和第一行毫无关系，混在一行里读不通。
    只贴了张图、一个字没写的小记不少（截图记录居多），这种给「图片小记」而不是「无标题」。"""
    s = _TAG.sub("", _IMG.sub("", s or "")).strip()
    s = s.split("\n", 1)[0].strip()
    return (s[:n] + "…") if len(s) > n else (s or alt)


# 「库」里五个容器各自怎么取最近的几条。
# 六元组：(前端认的 kind, 显示用的分类名, 表, 取 id/标题/时间的 SQL)
# 时间列各表不一样：小记/知识库/草稿本有 updated_at（改过就算最近打开），
# 资料库和云盘只有 created_at（它们是「传进来」的，没有编辑动作）。
_RECENT = [
    ("note", "小记",
     "SELECT id, COALESCE(content,''), updated_at, COALESCE(images,'') FROM notes "
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
    ("aiout", "AI 产出",
     "SELECT id, COALESCE(title,''), created_at FROM ai_outputs "
     "WHERE user_id=? ORDER BY id DESC LIMIT 6"),
]


# ---------------- 「最近打开」的打点 ----------------
#
# 上面那份 _RECENT 是**最近新增/改过**，不是打开。两者差得最远的是云盘和资料库：
# 它们只有 created_at，东西传上去时间就定死了，翻一下午也不会动一格。
# 真正的「打开」记在 lib_visits 里（见 schema.py），这里是它的读写两头。
#
# 三元组：(显示用的分类名, 拿标题的 SQL, 这张表认不认人)
# **每次都去源表查标题，不在打点时存快照**：改了名要跟着变，删掉的东西要从列表里消失。
# 一屏最多 8 条、全是主键点查，比留一份会过期的快照划算得多。
# 查不到行 = 这东西没了（删了 / 进了回收站 / 换了主人），那一条直接不出现，
# 不用去 lib_visits 里清理 —— 清理是写操作，而这是个只读接口。
_VISIT = {
    "note": ("小记", "SELECT COALESCE(content,''), COALESCE(images,'') FROM notes "
                     "WHERE id=? AND user_id=?", True),
    "kbdoc": ("知识库", "SELECT COALESCE(NULLIF(title,''),'无标题文档') FROM kb_nodes "
                        "WHERE id=? AND user_id=? AND type='doc'", True),
    "draft": ("草稿本", "SELECT COALESCE(NULLIF(title,''),'未命名草稿') FROM drafts "
                        "WHERE id=? AND user_id=?", True),
    "material": ("资料库", "SELECT COALESCE(NULLIF(title,''),COALESCE(orig_name,'')) FROM materials "
                           "WHERE id=? AND user_id=?", True),
    "drive": ("云盘", "SELECT COALESCE(name,'') FROM drive_files "
                      "WHERE id=? AND owner_id=? AND is_dir=0 AND COALESCE(deleted_at,'')=''", True),
    # 文件夹的身份是路径，不是 id。drive_files 里存的是「父目录 + 名字」两截，
    # 这里拼回完整路径来对 —— 根目录下的文件夹 folder 是空串，拼的时候不能多带一个斜杠。
    "drivedir": ("云盘", "SELECT COALESCE(name,'') FROM drive_files "
                         "WHERE (CASE WHEN COALESCE(folder,'')='' THEN name "
                         "            ELSE folder||'/'||name END)=? "
                         "AND owner_id=? AND is_dir=1 AND COALESCE(deleted_at,'')=''", True),
    "aiout": ("AI 产出", "SELECT COALESCE(title,'') FROM ai_outputs WHERE id=? AND user_id=?", True),
    # 收藏那一格里的东西：它们躺在公共表里（大家读的是同一篇时评），没有 user_id 可对。
    # 打点仍然是按人记的 —— 分人的是 lib_visits 那一行，不是内容本身。
    "classic": ("古诗文", "SELECT COALESCE(title,'') FROM classics WHERE id=?", False),
    "fanwen": ("人民时评", "SELECT COALESCE(title,'') FROM essay_models WHERE id=?", False),
    "news": ("时政", "SELECT COALESCE(title,'') FROM news_items WHERE id=?", False),
}


def _visit_title(db, kind, ref, u):
    """按 kind 去源表要一个现在的标题。东西没了就返回 None（这条不进列表）。"""
    label, sql, need_user = _VISIT[kind]
    rows = _rows(db, sql, (ref, u) if need_user else (ref,))
    if not rows:
        return None
    r = rows[0]
    if kind == "note":
        return _brief(r[0], "图片小记" if len(r) > 1 and r[1] not in ("", "[]") else "无标题")
    return r[0] or "无标题"


@bp.post("/api/lib/touch")
def lib_touch():
    """记一次「打开」。前端在每个真正打开东西的地方调它。

    **它坏了也不许影响正在打开的那个东西**：kind 不认、表没建好、ref 是空的，
    一律安静返回 ok:false，不返 4xx/5xx —— 前端那边 api() 一见非 2xx 就抛，
    而调用方是「点开一篇文档」这种路径，为一次记录失败弹个红条完全不成比例。
    """
    d = request.get_json(silent=True) or {}
    kind = str(d.get("kind") or "")
    ref = str(d.get("ref") or "").strip()
    if kind not in _VISIT or not ref:
        return jsonify({"ok": False})
    try:
        db = get_db()
        db.execute(
            "INSERT INTO lib_visits(user_id,kind,ref,extra,n,at) "
            "VALUES(?,?,?,?,1,datetime('now','localtime')) "
            "ON CONFLICT(user_id,kind,ref) DO UPDATE SET "
            "  n=n+1, at=datetime('now','localtime'), "
            # 目录会变（文件被挪走过），每次覆盖成最新的一次。
            # 但空的 extra 不许把已有的覆盖掉：有的入口拿不到目录，别让它把好数据抹了
            "  extra=CASE WHEN excluded.extra='' THEN lib_visits.extra ELSE excluded.extra END",
            (uid(), kind, ref, str(d.get("extra") or "")))
        db.commit()
    except Exception:
        return jsonify({"ok": False})
    return jsonify({"ok": True})


def _recent(db, u, want=8):
    """「最近打开」这一列：先真打开过的，不够再拿最近新增的垫底。

    为什么要垫底：打点是从这一版才开始记的，老用户库里塞满了东西、lib_visits 却是空的。
    如果只读打点表，升级后第一眼看到的是「库里还没有东西」—— 比原来那份不准的列表更糟。
    真打开的记录攒够 8 条之后，垫底的自然就被挤没了。
    """
    out, seen = [], set()
    for r in _rows(db, "SELECT kind, ref, COALESCE(extra,''), at FROM lib_visits "
                       "WHERE user_id=? ORDER BY at DESC LIMIT 40", (u,)):
        # 取 40 不取 8：删掉的东西会在下面被筛掉，只取 8 条的话
        # 删几个文件就能把这张列表打出一片空白
        kind = r[0]
        if kind not in _VISIT or (kind, str(r[1])) in seen:
            continue
        title = _visit_title(db, kind, r[1], u)
        if title is None:
            continue
        seen.add((kind, str(r[1])))
        out.append({"kind": kind, "label": _VISIT[kind][0], "id": r[1],
                    "title": title, "at": r[3] or "", "extra": r[2], "opened": True})
        if len(out) >= want:
            return out

    fill = []
    for kind, label, sql in _RECENT:
        for r in _rows(db, sql, (u,)):
            if (kind, str(r[0])) in seen:
                continue
            title = _brief(r[1], "图片小记" if len(r) > 3 and r[3] not in ("", "[]") else "无标题") \
                if kind == "note" else (r[1] or "无标题")
            fill.append({"kind": kind, "label": label, "id": r[0],
                         "title": title, "at": r[2] or "", "extra": "", "opened": False})
    fill.sort(key=lambda x: x["at"], reverse=True)
    return out + fill[:want - len(out)]


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
        "aiout": _num(db, "SELECT COUNT(*) FROM ai_outputs WHERE user_id=?", (u,)),
    }
    return jsonify({"counts": counts, "recent": _recent(db, u)})


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
    """收藏总数。

    **不能拿 _rows(sql) 的行数来数**：_STARS 里每条 SQL 都带着 LIMIT 60（那是给
    「最近收藏」列表用的），照着数的话每类最多 60、总数永远卡在 360，收藏得越多越不准。
    把 LIMIT 之前的部分包一层 COUNT(*)，数的才是真实总数。
    """
    n = 0
    for _, _, sql in _STARS:
        body = re.sub(r"\s+ORDER\s+BY\b.*$", "", sql, flags=re.I | re.S)
        n += _num(db, "SELECT COUNT(*) FROM (%s)" % body, (u,))
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
