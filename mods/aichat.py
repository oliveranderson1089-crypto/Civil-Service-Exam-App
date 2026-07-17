"""AI 助手：全局问答。


"""
from flask import Blueprint, jsonify, request

from core import CFG, _save_cfg, get_db, uid
from mods.ai import _ai_call_or_error, _ai_conf, ai_configured, vision_configured

bp = Blueprint("aichat", __name__)


@bp.get("/api/ai/status")
def ai_status():
    return jsonify({"configured": ai_configured(), "model": _ai_conf()["model"],
                    "vision": vision_configured()})


def _user_stats():
    """汇总用户与本应用的数据，供 AI 助手回答“我收录了多少…/这个应用有多少…”。"""
    db = get_db()
    u = uid()
    try:
        # 全局库总量
        cls = db.execute("SELECT category, COUNT(*) c FROM classics GROUP BY category ORDER BY c DESC").fetchall()
        cls_lib = "、".join("%s%d" % (r["category"], r["c"]) for r in cls)
        cls_total = sum(r["c"] for r in cls)
        idi = db.execute("SELECT COUNT(*) FROM ref_idiom").fetchone()[0]
        ci = db.execute("SELECT COUNT(*) FROM ref_ci").fetchone()[0]
        pdict = db.execute("SELECT COUNT(*) FROM party_dict").fetchone()[0]
        pdoc = db.execute("SELECT COUNT(*) FROM policy_docs").fetchone()[0]
        # 用户个人
        ent = db.execute("SELECT category, COUNT(*) c FROM entries WHERE user_id=? GROUP BY category", (u,)).fetchall()
        ent_by = "、".join("%s%d" % (r["category"], r["c"]) for r in ent) or "无"
        ent_total = sum(r["c"] for r in ent)
        star_ent = db.execute("SELECT COUNT(*) FROM entries WHERE user_id=? AND starred=1", (u,)).fetchone()[0]
        cstar = db.execute("SELECT c.category cat, COUNT(*) c FROM classic_stars s JOIN classics c ON c.id=s.classic_id "
                           "WHERE s.user_id=? GROUP BY c.category", (u,)).fetchall()
        cstar_by = "、".join("%s%d" % (r["cat"], r["c"]) for r in cstar) or "无"
        cstar_total = sum(r["c"] for r in cstar)
        wq = db.execute("SELECT COUNT(*) FROM wrong_questions WHERE user_id=?", (u,)).fetchone()[0]
        notes = db.execute("SELECT COUNT(*) FROM notes WHERE user_id=?", (u,)).fetchone()[0]
        docs = db.execute("SELECT COUNT(*) FROM kb_nodes WHERE user_id=? AND type='doc'", (u,)).fetchone()[0]
        mats = db.execute("SELECT COUNT(*) FROM materials WHERE user_id=?", (u,)).fetchone()[0]
    except Exception:
        return ""
    return "\n".join([
        "【本应用的数据（用户若问“这个应用有多少…”，用这些数）】",
        "· 古诗文库共 %d 首：%s。" % (cls_total, cls_lib),
        "· 成语库 %d 条、词语库 %d 条；党建理论学习词典 %d 条；时政要文库 %d 篇。" % (idi, ci, pdict, pdoc),
        "【当前用户个人的数据（用户若问“我收录/收藏了多少…”，用这些数）】",
        "· 成语词语收录共 %d 条（%s），其中收藏 %d 条。" % (ent_total, ent_by, star_ent),
        "· 收藏古诗文共 %d 首（%s）。" % (cstar_total, cstar_by),
        "· 错题本 %d 道、小记 %d 条、知识库文档 %d 篇、资料库文件 %d 个。" % (wq, notes, docs, mats),
        "注意：区分“本应用库总量”与“用户个人收录/收藏量”，按提问对象选用；数字以上面为准。",
    ])


@bp.post("/api/ai/chat")
def api_ai_chat():
    data = request.get_json(silent=True) or {}
    msgs = data.get("messages")
    if not isinstance(msgs, list) or not msgs:
        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"error": "请输入内容"}), 400
        msgs = [{"role": "user", "content": prompt}]
    sys = data.get("system") or "你是「公考助手」里的 AI 学习助理，服务正在备考公务员的用户。回答简洁、准确、条理清晰，用简体中文。"
    stats = _user_stats()
    if stats:
        sys = sys + "\n\n" + stats
    full = [{"role": "system", "content": sys}] + msgs
    reply, err = _ai_call_or_error(full, temperature=data.get("temperature", 0.6),
                                   max_tokens=data.get("max_tokens", 1600))
    if err:
        return err
    return jsonify({"reply": reply})


@bp.get("/api/admin/ai")
def admin_ai_get():
    c = _ai_conf()
    return jsonify({"base": c["base"], "model": c["model"], "has_key": bool(c["key"])})


@bp.post("/api/admin/ai")
def admin_ai_set():
    data = request.get_json(silent=True) or {}
    if "base" in data:
        CFG["ai_base"] = (data.get("base") or "").strip() or "https://api.deepseek.com"
    if "model" in data:
        CFG["ai_model"] = (data.get("model") or "").strip() or "deepseek-chat"
    if data.get("clear_key"):
        CFG["ai_key"] = ""
    elif (data.get("key") or "").strip():
        CFG["ai_key"] = data.get("key").strip()
    _save_cfg()
    return jsonify({"ok": True, "configured": ai_configured()})


@bp.get("/api/admin/registration")
def admin_reg_get():
    return jsonify({"open": bool(CFG.get("registration_open", True)),
                    "invite_code": CFG.get("invite_code", "")})


@bp.post("/api/admin/registration")
def admin_reg_set():
    data = request.get_json(silent=True) or {}
    if "open" in data:
        CFG["registration_open"] = bool(data.get("open"))
    if "invite_code" in data:
        CFG["invite_code"] = (data.get("invite_code") or "").strip()[:32]
    _save_cfg()
    return jsonify({"ok": True, "open": bool(CFG.get("registration_open", True)),
                    "invite_code": CFG.get("invite_code", "")})
