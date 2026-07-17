"""当前用户 / 板块结构。


"""
import json

from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from core import IDIOM_BOARD, SECTIONS, current_user, get_db, uid

bp = Blueprint("me", __name__)


@bp.get("/api/me")
def api_me():
    u = current_user()
    if not u:
        return jsonify({"error": "未登录"}), 401
    try:
        home_order = json.loads(u["home_order"]) if u["home_order"] else None
    except Exception:
        home_order = None
    try:
        ui_orders = json.loads(u["ui_orders"]) if u["ui_orders"] else {}
    except Exception:
        ui_orders = {}
    if home_order and "home" not in ui_orders:   # 兼容旧版存的首页顺序
        ui_orders["home"] = home_order
    return jsonify({"username": u["username"], "role": u["role"],
                    "is_admin": u["role"] == "admin", "email": u["email"] or "",
                    "home_order": home_order, "ui_orders": ui_orders})


@bp.post("/api/home_order")
def api_home_order():
    data = request.get_json(silent=True) or {}
    order = data.get("order")
    if (not isinstance(order, list) or len(order) > 50
            or not all(isinstance(x, str) and 0 < len(x) <= 40 for x in order)):
        return jsonify({"error": "无效顺序"}), 400
    db = get_db()
    db.execute("UPDATE users SET home_order=? WHERE id=?",
               (json.dumps(order, ensure_ascii=False), uid()))
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/ui_order")
def api_ui_order():
    data = request.get_json(silent=True) or {}
    key, order = data.get("key"), data.get("order")
    if (not isinstance(key, str) or not 0 < len(key) <= 60
            or not isinstance(order, list) or len(order) > 80
            or not all(isinstance(x, str) and 0 < len(x) <= 80 for x in order)):
        return jsonify({"error": "无效顺序"}), 400
    db = get_db()
    row = db.execute("SELECT ui_orders FROM users WHERE id=?", (uid(),)).fetchone()
    try:
        cur = json.loads(row["ui_orders"]) if row and row["ui_orders"] else {}
    except Exception:
        cur = {}
    cur[key] = order
    db.execute("UPDATE users SET ui_orders=? WHERE id=?",
               (json.dumps(cur, ensure_ascii=False), uid()))
    db.commit()
    return jsonify({"ok": True})


@bp.get("/api/sections")
def api_sections():
    return jsonify({"sections": SECTIONS, "idiom_board": IDIOM_BOARD})


@bp.get("/api/account")
def api_account_get():
    u = current_user()
    return jsonify({"username": u["username"], "email": u["email"] or "",
                    "sec_question": u["sec_question"] or ""})


@bp.post("/api/account")
def api_account_update():
    data = request.get_json(silent=True) or {}
    db = get_db()
    u = current_user()
    new_pw = data.get("new_password")
    if new_pw:
        if not check_password_hash(u["password_hash"], data.get("old_password") or ""):
            return jsonify({"error": "原密码不正确"}), 400
        if len(new_pw) < 6:
            return jsonify({"error": "新密码至少 6 位"}), 400
        db.execute("UPDATE users SET password_hash=? WHERE id=?",
                   (generate_password_hash(new_pw), u["id"]))
    if data.get("email") is not None:
        db.execute("UPDATE users SET email=? WHERE id=?", (data["email"].strip(), u["id"]))
    if data.get("sec_question") and data.get("sec_answer"):
        db.execute("UPDATE users SET sec_question=?, sec_answer_hash=? WHERE id=?",
                   (data["sec_question"].strip(),
                    generate_password_hash(data["sec_answer"].strip().lower()), u["id"]))
    db.commit()
    return jsonify({"ok": True})
