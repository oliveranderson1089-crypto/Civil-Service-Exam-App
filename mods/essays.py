"""范文推荐：仿真卷 + 全套参考答案。


"""
from flask import Blueprint, jsonify, request

from core import get_db, uid
from mods.shenlun import _SL_META

bp = Blueprint("essays", __name__)


@bp.get("/api/essays/topics")
def essays_topics():
    db = get_db()
    rows = db.execute("SELECT p.id, p.topic, p.spec, p.title, p.words, "
                      "(SELECT COUNT(*) FROM essays e WHERE e.paper_id=p.id) n "
                      "FROM essay_papers p ORDER BY p.id").fetchall()
    specs = _SL_META.get("specs", {})
    return jsonify({"papers": [dict(r, spec_name=specs.get(r["spec"], {}).get("name", "")) for r in rows]})


@bp.get("/api/essays")
def essays_list():
    """kind=zuowen 只看大作文范文；kind=yingyong 看应用文/小题的完整题目+参考答案。"""
    kind = (request.args.get("kind") or "").strip()
    topic = (request.args.get("topic") or "").strip()
    w, args = [], []
    if kind == "zuowen":
        w.append("e.qtype='zuowen'")
    elif kind == "yingyong":
        w.append("e.qtype<>'zuowen'")
    if topic:
        w.append("p.topic=?")
        args.append(topic)
    sql = ("SELECT e.id, e.seq, e.qtype, e.type_name, e.stem, e.full, e.word_min, e.word_max, "
           "e.answer_words, e.outline, p.topic, p.title paper_title, p.id paper_id "
           "FROM essays e JOIN essay_papers p ON p.id=e.paper_id "
           + ("WHERE " + " AND ".join(w) if w else "") +
           " ORDER BY p.id, e.seq")
    rows = get_db().execute(sql, args).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@bp.get("/api/essays/<int:eid>")
def essay_detail(eid):
    db = get_db()
    r = db.execute("SELECT e.*, p.topic, p.material, p.title paper_title, p.spec, p.words material_words "
                   "FROM essays e JOIN essay_papers p ON p.id=e.paper_id WHERE e.id=?", (eid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    d = dict(r)
    d["spec_name"] = _SL_META.get("specs", {}).get(d["spec"], {}).get("name", "")
    return jsonify(d)


@bp.post("/api/essays/paper/<int:pid>/practice")
def essay_practice(pid):
    """把这套仿真卷复制成一份「我的真题卷」，直接进入逐题作答 + AI 批改。"""
    db = get_db()
    p = db.execute("SELECT * FROM essay_papers WHERE id=?", (pid,)).fetchone()
    if not p:
        return jsonify({"error": "未找到"}), 404
    old = db.execute("SELECT id FROM shenlun_papers WHERE user_id=? AND title=?",
                     (uid(), p["title"])).fetchone()
    if old:
        return jsonify({"id": old["id"], "existed": True})
    cur = db.execute("INSERT INTO shenlun_papers(user_id,title,material,source) VALUES(?,?,?,?)",
                     (uid(), p["title"], p["material"], "范文推荐"))
    npid = cur.lastrowid
    for e in db.execute("SELECT * FROM essays WHERE paper_id=? ORDER BY seq", (pid,)):
        db.execute("INSERT INTO shenlun_questions(paper_id,seq,qtype,type_name,stem,requirement,"
                   "full,word_min,word_max) VALUES(?,?,?,?,?,'',?,?,?)",
                   (npid, e["seq"], e["qtype"], e["type_name"], e["stem"],
                    e["full"], e["word_min"], e["word_max"]))
    db.commit()
    return jsonify({"id": npid, "existed": False}), 201
