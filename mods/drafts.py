"""草稿本：错题本里平时打草稿用。


"""
import json
from datetime import datetime

from flask import Blueprint, jsonify, request

from core import get_db, uid

bp = Blueprint("drafts", __name__)


@bp.get("/api/drafts")
def drafts_list():
    """列表只带缩略图，不带笔迹，省流量。"""
    rows = get_db().execute(
        "SELECT id, title, pages, thumb, updated_at FROM drafts WHERE user_id=? ORDER BY updated_at DESC",
        (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@bp.post("/api/drafts")
def draft_new():
    d = request.get_json(silent=True) or {}
    title = (d.get("title") or "").strip() or datetime.now().strftime("草稿 %m-%d %H:%M")
    db = get_db()
    cur = db.execute("INSERT INTO drafts(user_id, title, data_json, pages) VALUES(?,?,?,1)",
                     (uid(), title, json.dumps({"bg": 1, "pages": [{"st": []}]})))
    db.commit()
    return jsonify({"id": cur.lastrowid, "title": title})


@bp.get("/api/drafts/<int:did>")
def draft_get(did):
    r = get_db().execute("SELECT id, title, data_json, pages, updated_at FROM drafts WHERE id=? AND user_id=?",
                         (did, uid())).fetchone()
    if not r:
        return jsonify({"error": "草稿不存在"}), 404
    return jsonify({"id": r["id"], "title": r["title"], "updated_at": r["updated_at"],
                    "data": json.loads(r["data_json"] or "{}")})


@bp.post("/api/drafts/<int:did>")
def draft_save(did):
    """保存笔迹（整本覆盖写）。title 单独传就是重命名。"""
    db = get_db()
    r = db.execute("SELECT id FROM drafts WHERE id=? AND user_id=?", (did, uid())).fetchone()
    if not r:
        return jsonify({"error": "草稿不存在"}), 404
    d = request.get_json(silent=True) or {}
    sets, args = [], []
    if d.get("title") is not None:
        sets.append("title=?"); args.append((d["title"] or "").strip() or "未命名草稿")
    if d.get("data") is not None:
        sets.append("data_json=?"); args.append(json.dumps(d["data"], ensure_ascii=False))
        sets.append("pages=?"); args.append(int(d.get("pages") or 1))
    if d.get("thumb") is not None:
        sets.append("thumb=?"); args.append(d["thumb"][:400000])   # 缩略图别无限大
    if not sets:
        return jsonify({"ok": True})
    sets.append("updated_at=datetime('now','localtime')")
    args += [did, uid()]
    db.execute("UPDATE drafts SET %s WHERE id=? AND user_id=?" % ",".join(sets), args)
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/drafts/<int:did>")
def draft_del(did):
    db = get_db()
    db.execute("DELETE FROM drafts WHERE id=? AND user_id=?", (did, uid()))
    db.commit()
    return jsonify({"ok": True})
