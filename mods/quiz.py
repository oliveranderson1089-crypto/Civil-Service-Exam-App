"""题库：四川省考卷面。


"""
import json

from flask import Blueprint, jsonify, request

from core import get_db, uid

bp = Blueprint("quiz", __name__)


@bp.get("/api/quiz/sets")
def quiz_sets():
    db = get_db()
    rows = db.execute(
        "SELECT s.id, s.name, s.kind, s.created_at,"
        "(SELECT COUNT(*) FROM quiz_questions q WHERE q.set_id=s.id) total,"
        "(SELECT COUNT(*) FROM quiz_answers a JOIN quiz_questions q2 ON q2.id=a.qid "
        " WHERE a.user_id=? AND q2.set_id=s.id) done,"
        "(SELECT COUNT(*) FROM quiz_answers a JOIN quiz_questions q3 ON q3.id=a.qid "
        " WHERE a.user_id=? AND q3.set_id=s.id AND a.correct=1) right_n "
        "FROM quiz_sets s ORDER BY s.id DESC", (uid(), uid())).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@bp.get("/api/quiz/sets/<int:sid>")
def quiz_set_detail(sid):
    db = get_db()
    s = db.execute("SELECT * FROM quiz_sets WHERE id=?", (sid,)).fetchone()
    if not s:
        return jsonify({"error": "未找到"}), 404
    qs = db.execute("SELECT id,seq,module,qtype,material,question,options,answer,explanation "
                    "FROM quiz_questions WHERE set_id=? ORDER BY seq", (sid,)).fetchall()
    mine = {r["qid"]: dict(r) for r in db.execute(
        "SELECT qid, choice, correct FROM quiz_answers WHERE user_id=? AND set_id=?", (uid(), sid))}
    items = []
    for q in qs:
        d = dict(q)
        try:
            d["options"] = json.loads(d["options"] or "[]")
        except Exception:
            d["options"] = []
        m = mine.get(q["id"])
        d["my_choice"] = m["choice"] if m else ""
        items.append(d)
    return jsonify({"id": s["id"], "name": s["name"], "kind": s["kind"], "questions": items})


@bp.post("/api/quiz/answer")
def quiz_answer():
    data = request.get_json(silent=True) or {}
    qid = int(data.get("qid") or 0)
    choice = (data.get("choice") or "").strip()
    db = get_db()
    q = db.execute("SELECT * FROM quiz_questions WHERE id=?", (qid,)).fetchone()
    if not q:
        return jsonify({"error": "题目不存在"}), 404
    correct = 1 if choice and choice == (q["answer"] or "") else 0
    db.execute("INSERT OR REPLACE INTO quiz_answers(user_id,set_id,qid,choice,correct) VALUES(?,?,?,?,?)",
               (uid(), q["set_id"], qid, choice, correct))
    db.commit()
    return jsonify({"correct": bool(correct), "answer": q["answer"], "explanation": q["explanation"] or ""})
