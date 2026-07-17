"""管理后台：用户管理 + AI 设置 + 注册开关。


"""
from flask import Blueprint, jsonify, request, send_from_directory
from werkzeug.security import generate_password_hash

from core import STATIC, get_db, uid
from mods.files import _remove_file

bp = Blueprint("admin", __name__)


@bp.get("/admin")
def admin_page():
    return send_from_directory(STATIC, "admin.html")


@bp.get("/api/admin/users")
def admin_users():
    rows = get_db().execute(
        "SELECT id,username,role,email,sec_question,created_at,"
        "(SELECT COUNT(*) FROM entries e WHERE e.user_id=users.id) entry_cnt,"
        "(SELECT COUNT(*) FROM materials m WHERE m.user_id=users.id) mat_cnt "
        "FROM users ORDER BY id").fetchall()
    return jsonify({"users": [dict(r) for r in rows]})


@bp.post("/api/admin/users/<int:user_id>/reset")
def admin_reset_pw(user_id):
    db = get_db()
    if not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
        return jsonify({"error": "用户不存在"}), 404
    db.execute("UPDATE users SET password_hash=? WHERE id=?",
               (generate_password_hash("123456"), user_id))
    db.commit()
    return jsonify({"ok": True, "password": "123456"})


@bp.post("/api/admin/users/<int:user_id>/role")
def admin_set_role(user_id):
    data = request.get_json(silent=True) or {}
    role = "admin" if data.get("admin") else "user"
    db = get_db()
    if role == "user":  # 不能取消最后一个管理员
        admins = db.execute("SELECT COUNT(*) c FROM users WHERE role='admin'").fetchone()["c"]
        cur = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if cur and cur["role"] == "admin" and admins <= 1:
            return jsonify({"error": "至少保留一个管理员，请先把另一位用户设为管理员，再撤销当前管理员"}), 400
    db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    db.commit()
    return jsonify({"ok": True, "role": role})


@bp.post("/api/admin/users/<int:user_id>/secq")
def admin_set_secq(user_id):
    data = request.get_json(silent=True) or {}
    q = (data.get("question") or "").strip()
    a = (data.get("answer") or "").strip()
    if not q or not a:
        return jsonify({"error": "请填写密保问题与答案"}), 400
    db = get_db()
    if not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
        return jsonify({"error": "用户不存在"}), 404
    db.execute("UPDATE users SET sec_question=?, sec_answer_hash=? WHERE id=?",
               (q, generate_password_hash(a.lower()), user_id))
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/admin/users/<int:user_id>")
def admin_delete_user(user_id):
    if user_id == uid():
        return jsonify({"error": "不能删除自己"}), 400
    db = get_db()
    # 删除其资料文件
    for m in db.execute("SELECT stored_name FROM materials WHERE user_id=?", (user_id,)).fetchall():
        _remove_file(user_id, m["stored_name"])
    db.execute("DELETE FROM materials WHERE user_id=?", (user_id,))
    db.execute("DELETE FROM entries WHERE user_id=?", (user_id,))
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    return jsonify({"ok": True})
