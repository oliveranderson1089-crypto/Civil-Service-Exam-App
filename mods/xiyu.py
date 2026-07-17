"""习语金句 / 经典著作。


"""
from flask import Blueprint, jsonify, request

from core import get_db
from mods.ai import _ai_call_or_error

bp = Blueprint("xiyu", __name__)


@bp.get("/api/xiyu")
def xiyu_list():
    cat = (request.args.get("cat") or "").strip()
    db = get_db()
    where, args = "", []
    if cat and cat != "全部":
        where = "WHERE category=?"; args = [cat]
    rows = db.execute("SELECT * FROM xiyu_items %s ORDER BY date DESC, id LIMIT 200" % where, args).fetchall()
    counts = {r[0]: r[1] for r in db.execute("SELECT category, COUNT(*) FROM xiyu_items GROUP BY category")}
    return jsonify({"items": [dict(r) for r in rows], "counts": counts})


@bp.get("/api/works")
def works_list():
    rows = get_db().execute(
        "SELECT id, book, ord, title, length(content) chars,"
        "(interpretation IS NOT NULL AND interpretation<>'') has_ai "
        "FROM works ORDER BY book, ord").fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@bp.get("/api/works/<int:wid>")
def works_detail(wid):
    r = get_db().execute("SELECT * FROM works WHERE id=?", (wid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    return jsonify({"id": r["id"], "book": r["book"], "title": r["title"],
                    "content": r["content"] or "", "interpretation": r["interpretation"] or ""})


@bp.post("/api/works/<int:wid>/ai")
def works_ai(wid):
    r = get_db().execute("SELECT * FROM works WHERE id=?", (wid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    force = (request.get_json(silent=True) or {}).get("force")
    if r["interpretation"] and not force:
        return jsonify({"content": r["interpretation"], "cached": True})
    excerpt = (r["content"] or "")[:8000]
    prompt = (
        "下面是《%s》中《%s》一文（可能为节选）。请面向公务员考试考生，用简体中文、Markdown 输出"
        "「导读解读」，分节：\n## 一、写作背景\n## 二、核心观点（分条）\n"
        "## 三、名句与经典表述（摘原文）\n## 四、公考如何运用（申论/面试引用角度）\n"
        "要求准确、精炼、完整不截断。\n\n全文：\n%s") % (r["book"], r["title"], excerpt)
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是理论功底扎实的公考辅导老师，解读准确精炼，用简体中文 Markdown。"},
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=4000)
    if err:
        return err
    db = get_db()
    db.execute("UPDATE works SET interpretation=? WHERE id=?", (reply, wid))
    db.commit()
    return jsonify({"content": reply, "cached": False})
