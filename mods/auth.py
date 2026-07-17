"""注册 / 登录 / 找回密码。


"""
import base64
import io
import secrets
import time

from flask import (Blueprint, jsonify, redirect, request, send_from_directory,
                   session)
from werkzeug.security import check_password_hash, generate_password_hash

from core import CFG, STATIC, get_db, users_count

bp = Blueprint("auth", __name__)

# 密保问题选项

SEC_QUESTIONS = [
    "你的出生城市是？",
    "你母亲的名字是？",
    "你小学的名字是？",
    "你最好朋友的名字是？",
    "你最喜欢的一本书是？",
    "你的幸运数字是？",
]

_login_fails = {}  # username -> {count, locked_until}


_captchas = {}  # cid -> {"code": 小写答案, "exp": 过期时间戳}
_CAP_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # 去掉易混的 I O 0 1


def _captcha_new():
    """生成一个 4 位图形验证码，返回 (cid, dataURL)。答案存服务端，前端只拿图片。"""
    import random
    now = time.time()
    for k in [k for k, v in _captchas.items() if v["exp"] < now]:   # 顺手清过期
        _captchas.pop(k, None)
    code = "".join(random.choice(_CAP_CHARS) for _ in range(4))
    cid = secrets.token_urlsafe(12)
    _captchas[cid] = {"code": code.lower(), "exp": now + 300}
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    W, H = 130, 44
    img = Image.new("RGB", (W, H), (245, 248, 252))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
    for i, ch in enumerate(code):
        col = (random.randint(20, 90), random.randint(30, 90), random.randint(90, 160))
        y = random.randint(2, 10)
        ci = Image.new("RGBA", (30, 40), (0, 0, 0, 0))
        cd = ImageDraw.Draw(ci)
        cd.text((4, 2), ch, font=font, fill=col)
        ci = ci.rotate(random.randint(-28, 28), expand=1, resample=Image.BICUBIC)
        img.paste(ci, (10 + i * 28, y), ci)
    for _ in range(4):                                # 干扰线
        d.line([(random.randint(0, W), random.randint(0, H)) for _ in range(2)],
               fill=(random.randint(120, 200),) * 3, width=1)
    for _ in range(90):                               # 噪点
        d.point((random.randint(0, W), random.randint(0, H)),
                fill=(random.randint(120, 200),) * 3)
    img = img.filter(ImageFilter.SMOOTH)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return cid, "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _captcha_ok(cid, ans):
    """一次性校验：对了就作废，防重放。"""
    rec = _captchas.pop((cid or "").strip(), None)
    return bool(rec and rec["exp"] >= time.time() and (ans or "").strip().lower() == rec["code"])


@bp.get("/register")
def register_page():
    return send_from_directory(STATIC, "register.html")


@bp.get("/api/captcha")
def api_captcha():
    cid, url = _captcha_new()
    return jsonify({"id": cid, "image": url})


@bp.get("/api/register/status")
def register_status():
    # 首个用户（管理员）注册永远放行，且不需要邀请码
    first = users_count() == 0
    open_ = first or bool(CFG.get("registration_open", True))
    return jsonify({"open": open_,
                    "invite": (not first) and open_ and bool(CFG.get("invite_code"))})


@bp.post("/api/register")
def api_register():
    data = request.get_json(silent=True) or {}
    if users_count() > 0 and not CFG.get("registration_open", True):
        return jsonify({"error": "注册暂未开放，请联系管理员"}), 403
    username = (data.get("username") or "").strip()
    pw = data.get("password") or ""
    sec_q = (data.get("sec_question") or "").strip()
    sec_a = (data.get("sec_answer") or "").strip()
    email = (data.get("email") or "").strip()
    if not _captcha_ok(data.get("captcha_id"), data.get("captcha")):
        return jsonify({"error": "验证码错误或已过期", "captcha": True}), 400
    # 邀请码校验放在验证码之后：每试一次都要过一次验证码，无法脚本枚举
    if users_count() > 0 and CFG.get("invite_code"):
        if (data.get("invite_code") or "").strip() != CFG["invite_code"]:
            return jsonify({"error": "邀请码错误，请向管理员索取", "invite": True}), 403
    if len(username) < 2:
        return jsonify({"error": "用户名至少 2 个字符"}), 400
    if len(pw) < 6:
        return jsonify({"error": "密码至少 6 位"}), 400
    if not sec_q or len(sec_a) < 1:
        return jsonify({"error": "请设置密保问题与答案"}), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        return jsonify({"error": "用户名已存在"}), 400
    role = "admin" if users_count() == 0 else "user"  # 第一个用户=管理员
    cur = db.execute(
        "INSERT INTO users(username,password_hash,role,sec_question,sec_answer_hash,email) VALUES(?,?,?,?,?,?)",
        (username, generate_password_hash(pw), role, sec_q,
         generate_password_hash(sec_a.lower()), email))
    db.commit()
    session.permanent = True
    session["user_id"] = cur.lastrowid
    session["username"] = username
    session["role"] = role
    return jsonify({"ok": True, "role": role})


@bp.get("/login")
def login_page():
    if users_count() == 0:
        return redirect("/register")
    return send_from_directory(STATIC, "login.html")


@bp.post("/login")
@bp.post("/api/login")
def login_submit():
    data = request.get_json(silent=True) or request.form
    username = (data.get("username") or "").strip()
    pw = data.get("password") or ""
    now = time.time()
    rec = _login_fails.get(username)
    if rec and rec.get("locked_until", 0) > now:
        left = int((rec["locked_until"] - now) / 60) + 1
        return jsonify({"error": f"登录失败次数过多，请 {left} 分钟后再试"}), 429
    if not _captcha_ok(data.get("captcha_id"), data.get("captcha")):
        return jsonify({"error": "验证码错误或已过期", "captcha": True}), 400
    u = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if u and check_password_hash(u["password_hash"], pw):
        _login_fails.pop(username, None)
        session.permanent = True
        session["user_id"] = u["id"]
        session["username"] = u["username"]
        session["role"] = u["role"]
        return jsonify({"ok": True, "role": u["role"]})
    rec = _login_fails.setdefault(username, {"count": 0, "locked_until": 0})
    rec["count"] += 1
    if rec["count"] >= 8:
        rec["locked_until"] = now + 600
        rec["count"] = 0
    return jsonify({"error": "用户名或密码错误"}), 401


@bp.post("/logout")
@bp.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@bp.get("/forgot")
def forgot_page():
    if users_count() == 0:
        return redirect("/register")
    return send_from_directory(STATIC, "forgot.html")


@bp.post("/api/forgot/question")
def api_forgot_question():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    u = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not u or not u["sec_question"]:
        return jsonify({"error": "用户名不存在或未设置密保问题"}), 400
    return jsonify({"ok": True, "question": u["sec_question"]})


@bp.post("/api/forgot/reset")
def api_forgot_reset():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    answer = (data.get("answer") or "").strip().lower()
    new_pw = data.get("password") or ""
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not u or not u["sec_answer_hash"]:
        return jsonify({"error": "用户名不存在或未设置密保"}), 400
    if not check_password_hash(u["sec_answer_hash"], answer):
        return jsonify({"error": "密保答案不正确"}), 400
    if len(new_pw) < 6:
        return jsonify({"error": "新密码至少 6 位"}), 400
    db.execute("UPDATE users SET password_hash=? WHERE id=?",
               (generate_password_hash(new_pw), u["id"]))
    db.commit()
    return jsonify({"ok": True})


@bp.get("/api/sec_questions")
def api_sec_questions():
    return jsonify({"questions": SEC_QUESTIONS})
