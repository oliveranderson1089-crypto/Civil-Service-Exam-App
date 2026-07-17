"""每日任务：当天要做的事。


"""
from datetime import datetime

from flask import Blueprint, jsonify, request

from core import get_db, uid

bp = Blueprint("tasks", __name__)


@bp.get("/api/daily_tasks")
def daily_tasks():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    tpls = db.execute("SELECT * FROM task_templates WHERE user_id=? AND active=1 ORDER BY sort, id",
                      (uid(),)).fetchall()
    done = {r["tpl_id"] for r in db.execute(
        "SELECT tpl_id FROM task_done WHERE user_id=? AND date=?", (uid(), today))}
    items = [{"id": t["id"], "text": t["text"], "done": t["id"] in done} for t in tpls]
    return jsonify({"date": today, "items": items, "done_n": len(done), "total": len(tpls)})


@bp.post("/api/daily_tasks/templates")
def daily_task_add():
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return jsonify({"error": "请输入任务"}), 400
    db = get_db()
    cur = db.execute("INSERT INTO task_templates(user_id,text) VALUES(?,?)", (uid(), text[:120]))
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@bp.delete("/api/daily_tasks/templates/<int:tid>")
def daily_task_del(tid):
    db = get_db()
    db.execute("DELETE FROM task_templates WHERE id=? AND user_id=?", (tid, uid()))
    db.execute("DELETE FROM task_done WHERE tpl_id=? AND user_id=?", (tid, uid()))
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/daily_tasks/<int:tid>/toggle")
def daily_task_toggle(tid):
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    r = db.execute("SELECT 1 FROM task_done WHERE user_id=? AND tpl_id=? AND date=?",
                   (uid(), tid, today)).fetchone()
    if r:
        db.execute("DELETE FROM task_done WHERE user_id=? AND tpl_id=? AND date=?", (uid(), tid, today))
        on = False
    else:
        db.execute("INSERT OR IGNORE INTO task_done(user_id,tpl_id,date) VALUES(?,?,?)", (uid(), tid, today))
        on = True
    db.commit()
    return jsonify({"done": on})
