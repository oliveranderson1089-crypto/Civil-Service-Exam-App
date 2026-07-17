"""申论概括句积累（每日生成，全局共享）。


"""
from flask import Blueprint, jsonify, request

from core import get_db

bp = Blueprint("gaikuo", __name__)


@bp.get("/api/gaikuo")
def gaikuo_list():
    date = (request.args.get("date") or "").strip()
    db = get_db()
    dates = [{"date": r["date"], "count": r["c"]} for r in db.execute(
        "SELECT date, COUNT(*) c FROM gaikuo_items GROUP BY date ORDER BY date DESC LIMIT 60").fetchall()]
    if not date and dates:
        date = dates[0]["date"]
    rows = db.execute("SELECT * FROM gaikuo_items WHERE date=? ORDER BY id", (date,)).fetchall() if date else []
    return jsonify({"dates": dates, "date": date, "items": [dict(r) for r in rows]})
