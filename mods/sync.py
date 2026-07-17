"""数据版本：浏览器/手机自动同步用。


"""
import hashlib

from flask import Blueprint, jsonify

from core import get_db, log, uid

bp = Blueprint("sync", __name__)


@bp.get("/api/sync")
def api_sync():
    """返回当前用户可见数据的版本指纹；变化了说明有别的端改过，前端自动刷新当前视图。"""
    db = get_db()
    u = uid()
    parts = []
    for sql, args in [
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM notes WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM materials WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(MAX(LENGTH(content)),0) FROM kb_nodes WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM entries WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM wrong_questions WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM board_points WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM news_items", ()),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM gaikuo_items", ()),
        ("SELECT COUNT(*), COALESCE(MAX(news_id),0) FROM news_stars WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM sucai_items", ()),
        ("SELECT COUNT(*), COALESCE(MAX(rowid),0) FROM review_state WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM changshi_items", ()),
        # 组队/互监：申请或成员一变，指纹就变，对端能自动刷新
        ("SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(MAX(status),'') FROM team_requests WHERE from_uid=? OR to_uid=?", (u, u)),
        ("SELECT COUNT(*) FROM team_members WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(SUM(done),0) FROM shared_todos", ()),
    ]:
        try:
            parts.append(",".join(str(x) for x in db.execute(sql, args).fetchone()))
        except Exception:
            parts.append("-")
    # kb_nodes 编辑不改行数时靠内容长度粗判；notes 同理用 updated 时间戳（若无列则忽略）
    try:
        parts.append(str(db.execute("SELECT COALESCE(MAX(created_at),'') FROM notes WHERE user_id=?", (u,)).fetchone()[0]))
    except Exception:
        log.debug("notes 时间戳取不到，同步指纹少一项", exc_info=True)
    return jsonify({"token": hashlib.md5("|".join(parts).encode()).hexdigest()})
