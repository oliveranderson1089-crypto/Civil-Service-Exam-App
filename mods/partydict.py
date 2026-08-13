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
    # 分页取。原先一口气发 600 条：实测「全部」这一屏就是 375 KB（词条正文全带着），
    # 本机 5 毫秒无感，但公网那一跳实测 0.9~1.4 秒，加上手机端一次渲染几百张卡片。
    # 多取一条用来判断「还有没有」，省一次 COUNT。
    limit = max(1, min(int(request.args.get("limit") or 60), 600))
    offset = max(0, int(request.args.get("offset") or 0))
    sql += " ORDER BY ord, id LIMIT ? OFFSET ?"
    rows = get_db().execute(sql, args + [limit + 1, offset]).fetchall()
    return jsonify({"items": [dict(r) for r in rows[:limit]], "more": len(rows) > limit})
