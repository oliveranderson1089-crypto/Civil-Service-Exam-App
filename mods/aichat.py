"""AI 助手：全局问答。


"""
from flask import Blueprint, jsonify, request

import aiclient
from core import CFG, _save_cfg, _study_stats, get_db, uid
from mods.ai import _ai_call_or_error, _ai_conf, ai_configured, vision_configured

bp = Blueprint("aichat", __name__)


@bp.get("/api/ai/status")
def ai_status():
    """前端的档位条要它：现在用的是哪个模型、今天一共调了多少次。

    次数从 ai_calls 数（那张表没有 user_id，所以是**全应用**的量，不是某个人的）——
    这个应用本来就是自用的，比起精确归属，"今天已经用掉多少"更值得摆出来。"""
    today = 0
    try:
        db = get_db()
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_calls'").fetchone():
            today = db.execute("SELECT COUNT(*) c FROM ai_calls "
                               "WHERE ts >= date('now','localtime')").fetchone()["c"]
    except Exception:
        today = 0
    return jsonify({"configured": ai_configured(), "model": _ai_conf()["model"],
                    "model_pro": aiclient.conf("pro").get("model", ""),
                    "today": today, "vision": vision_configured()})


def _user_stats():
    """给 AI 一句用户概况钩子。细节别堆在 prompt 里——精确数字/明细交给查询工具：
    个人明细走 get_user_overview / 各 list_*，本应用库总量走 get_library_stats。"""
    db = get_db()
    u = uid()
    if not u:
        return ""
    try:
        wq = db.execute("SELECT COUNT(*) FROM wrong_questions WHERE user_id=?", (u,)).fetchone()[0]
        ent = db.execute("SELECT COUNT(*) FROM entries WHERE user_id=?", (u,)).fetchone()[0]
        notes = db.execute("SELECT COUNT(*) FROM notes WHERE user_id=?", (u,)).fetchone()[0]
        streak = _study_stats(db, u)["streak"]
    except Exception:
        return ""
    return ("【用户概况（只给你估个规模，别拿这里的约数硬答；要准确数字或明细，必须调查询工具：个人数据用 "
            "get_user_overview / list_*，本应用库总量用 get_library_stats）】"
            "错题 %d 道 · 收录 %d 条 · 小记 %d 条 · 连续学习 %d 天。" % (wq, ent, notes, streak))


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
    return jsonify({"base": c["base"], "model": c["model"], "model_pro": c["pro"],
                    "has_key": bool(c["key"])})


@bp.get("/api/admin/ai/models")
def admin_ai_models():
    """问接口「你现在到底有哪些模型」，并指出当前两个档位配得对不对。

    这就是「deepseek-chat 被下线」那次真正缺的东西：当时只能看到一句
    400，没法在后台确认新名字叫什么，只好去翻官网。现在一点就知道。
    """
    ids = aiclient.list_models(CFG, ttl=0)          # ttl=0：这是人手点的，要现拉不要缓存
    if not ids:
        return jsonify({"error": "拉不到模型清单：Key 无效、网络不通，或该接口不支持 /v1/models",
                        "models": []}), 502
    cur = {t: aiclient.conf(t, CFG)["model"] for t in ("fast", "pro")}
    return jsonify({
        "models": ids,
        "current": cur,
        "invalid": {t: m for t, m in cur.items() if m not in ids},
        "suggest": {t: aiclient.pick_model(ids, t) for t in ("fast", "pro")},
    })


@bp.post("/api/admin/ai")
def admin_ai_set():
    data = request.get_json(silent=True) or {}
    if "base" in data:
        CFG["ai_base"] = (data.get("base") or "").strip() or aiclient.DEFAULT_BASE
    # 兜底名取自 aiclient.TIERS——真实模型名全项目只有那一处，别在这儿再抄一遍。
    # normalize 顺手把粘错的旧名/斜杠写法就地改对，省得存下去下次再炸。
    if "model" in data:
        CFG["ai_model"] = (aiclient.normalize(data.get("model")) or aiclient.TIERS["fast"][1])
    if "model_pro" in data:
        CFG["ai_model_pro"] = (aiclient.normalize(data.get("model_pro")) or aiclient.TIERS["pro"][1])
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
