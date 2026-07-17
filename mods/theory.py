"""理论基础：马原 / 毛中特 / 习思想。


"""
from flask import Blueprint, jsonify, request

from core import get_db

bp = Blueprint("theory", __name__)


TH_BOARDS = [
    {"name": "马克思主义基本原理", "short": "马原", "icon": "compass",
     "desc": "唯物论 · 辩证法 · 认识论 · 唯物史观 · 政治经济学"},
    {"name": "毛泽东思想", "short": "毛概", "icon": "flag",
     "desc": "新民主主义革命 · 社会主义改造 · 活的灵魂"},
    {"name": "中国特色社会主义理论体系", "short": "中特", "icon": "layers",
     "desc": "邓小平理论 · 三个代表 · 科学发展观"},
    {"name": "习近平新时代中国特色社会主义思想", "short": "习思想", "icon": "star",
     "desc": "十个明确 · 十四个坚持 · 十三个方面成就"},
]


@bp.get("/api/theory/boards")
def theory_boards():
    db = get_db()
    counts = {r["board"]: r["c"] for r in
              db.execute("SELECT board, COUNT(*) c FROM theory_items GROUP BY board")}
    return jsonify({"boards": [dict(b, count=counts.get(b["name"], 0)) for b in TH_BOARDS]})


@bp.get("/api/theory/items")
def theory_items():
    board = (request.args.get("board") or "").strip()
    if not board:
        return jsonify({"error": "缺少板块"}), 400
    rows = get_db().execute("SELECT id, topic, title, content FROM theory_items WHERE board=? "
                            "ORDER BY id", (board,)).fetchall()
    groups, order = {}, []
    for r in rows:
        t = r["topic"] or "其他"
        if t not in groups:
            groups[t] = []
            order.append(t)
        groups[t].append({"id": r["id"], "title": r["title"], "content": r["content"]})
    meta = next((b for b in TH_BOARDS if b["name"] == board), {"name": board, "desc": ""})
    return jsonify({"board": board, "desc": meta.get("desc", ""), "count": len(rows),
                    "topics": [{"name": t, "items": groups[t]} for t in order]})
