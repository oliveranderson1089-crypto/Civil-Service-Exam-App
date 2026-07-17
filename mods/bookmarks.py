"""书签：看到哪了。


"""
from flask import Blueprint, jsonify, request

from core import get_db, uid

bp = Blueprint("bookmarks", __name__)


@bp.get("/api/bookmarks")
def bm_list():
    rows = get_db().execute(
        "SELECT * FROM bookmarks WHERE user_id=? ORDER BY updated_at DESC LIMIT 100", (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@bp.post("/api/bookmarks")
def bm_save():
    """一个 (kind, ref) 只留一条：自动记「看到哪了」，手动打点则把 note 填上。"""
    d = request.get_json(silent=True) or {}
    kind = (d.get("kind") or "").strip()[:20]
    ref = str(d.get("ref") or "").strip()[:60]
    if not kind or not ref:
        return jsonify({"error": "缺少参数"}), 400
    db = get_db()
    db.execute(
        "INSERT INTO bookmarks(user_id,kind,ref,title,pos,note,updated_at) "
        "VALUES(?,?,?,?,?,?,datetime('now','localtime')) "
        "ON CONFLICT(user_id,kind,ref) DO UPDATE SET title=excluded.title, pos=excluded.pos, "
        "note=COALESCE(NULLIF(excluded.note,''), bookmarks.note), updated_at=datetime('now','localtime')",
        (uid(), kind, ref, (d.get("title") or "")[:120], float(d.get("pos") or 0), (d.get("note") or "")[:120]))
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/bookmarks/<int:bid>")
def bm_del(bid):
    db = get_db()
    db.execute("DELETE FROM bookmarks WHERE id=? AND user_id=?", (bid, uid()))
    db.commit()
    return jsonify({"ok": True})
