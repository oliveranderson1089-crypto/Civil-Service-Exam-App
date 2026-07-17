"""衔接表达 · 例句。


"""
from flask import Blueprint, jsonify, request

from core import get_db
from mods.ai import _ai_call_or_error

bp = Blueprint("lianjie", __name__)


@bp.post("/api/sucai/<int:sid>/example")
def sucai_example(sid):
    db = get_db()
    r = db.execute("SELECT * FROM sucai_items WHERE id=?", (sid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    force = bool((request.get_json(silent=True) or {}).get("force"))
    if r["example"] and not force:
        return jsonify({"example": r["example"], "cached": True})
    prompt = ("下面是一句申论写作的衔接表达/万能句式：\n%s\n\n请用它写一个申论语境下的规范例句"
              "（书面化、紧扣治理/民生/发展类主题，30~60字），只输出例句本身。" % r["content"])
    if force and r["example"]:
        prompt += "\n注意：换一个主题和角度，不要写成：" + r["example"]
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论写作辅导老师，例句规范、书面化。"},
         {"role": "user", "content": prompt}], temperature=0.85, max_tokens=200)
    if err:
        return err
    ex = rep.strip()
    db.execute("UPDATE sucai_items SET example=? WHERE id=?", (ex, sid))
    db.commit()
    return jsonify({"example": ex, "cached": False})
