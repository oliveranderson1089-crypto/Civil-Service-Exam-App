"""党建理论学习词典（12371.cn）。


"""
from flask import Blueprint, jsonify, request

from core import get_db

bp = Blueprint("partydict", __name__)


@bp.get("/api/partydict/cats")
def partydict_cats():
    db = get_db()
    rows = db.execute("SELECT cat, COUNT(*) c FROM party_dict GROUP BY cat ORDER BY MIN(id)").fetchall()
    total = db.execute("SELECT COUNT(*) FROM party_dict").fetchone()[0]
    return jsonify({"total": total, "cats": [{"cat": r["cat"], "count": r["c"]} for r in rows]})


@bp.get("/api/partydict")
def partydict_list():
    cat = (request.args.get("cat") or "").strip()
    q = (request.args.get("q") or "").strip()
    sql = "SELECT id,cat,term,content,url FROM party_dict WHERE 1=1"
    args = []
    if cat and cat != "全部":
        sql += " AND cat=?"; args.append(cat)
    if q:
        sql += " AND (term LIKE ? OR content LIKE ?)"; args += ["%" + q + "%", "%" + q + "%"]
    sql += " ORDER BY ord, id LIMIT 600"
    rows = get_db().execute(sql, args).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})
