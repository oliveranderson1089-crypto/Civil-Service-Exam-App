"""时政要文库：重要文件全文 + AI 政策解读。


"""
from flask import Blueprint, jsonify, request

from core import get_db
from mods.ai import _ai_call_or_error

bp = Blueprint("policydocs", __name__)


@bp.get("/api/policydocs")
def policydocs_list():
    rows = get_db().execute(
        "SELECT id,title,category,source_url,length(content) chars,"
        "(interpretation IS NOT NULL AND interpretation<>'') has_ai "
        "FROM policy_docs ORDER BY ord, id").fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@bp.get("/api/policydocs/<int:did>")
def policydocs_detail(did):
    r = get_db().execute("SELECT * FROM policy_docs WHERE id=?", (did,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    return jsonify({"id": r["id"], "title": r["title"], "category": r["category"],
                    "source_url": r["source_url"], "content": r["content"] or "",
                    "interpretation": r["interpretation"] or ""})


@bp.post("/api/policydocs/<int:did>/ai")
def policydocs_ai(did):
    r = get_db().execute("SELECT * FROM policy_docs WHERE id=?", (did,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    force = (request.get_json(silent=True) or {}).get("force")
    if r["interpretation"] and not force:
        return jsonify({"content": r["interpretation"], "cached": True})
    excerpt = (r["content"] or "")[:9000]
    prompt = (
        "下面是《%s》的全文（可能为节选）。请面向公务员考试考生，用简体中文、Markdown 输出该文件的"
        "「政策解读」，分这几节：\n"
        "## 一、文件地位与背景\n## 二、核心要点/主要内容（分条提炼）\n"
        "## 三、公考高频考点与命题角度\n## 四、可直接引用的金句/关键表述\n"
        "## 五、申论/面试答题如何运用\n"
        "要求：准确、具体、条理清晰，紧扣原文，写完整不要截断。\n\n全文：\n%s"
    ) % (r["title"], excerpt)
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是资深公考时政辅导老师，解读权威文件准确、精炼、实用，用简体中文 Markdown，务必完整不截断。"},
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=6000)
    if err:
        return err
    db = get_db()
    db.execute("UPDATE policy_docs SET interpretation=? WHERE id=?", (reply, did))
    db.commit()
    return jsonify({"content": reply, "cached": False})
