#!/usr/bin/env python3
"""公考助手 —— 后端服务（多用户）

- 行测 / 申论 两大板块，下设若干小板块
- 言语理解与表达：成语/词语积累（拼音+释义+PDF 导出）
- 每个板块：资料库（上传图片/文档/网页，应用内直接查看，Office 自动转 PDF）
- 多用户 + 密保问题找回密码 + 管理员后台
"""
import base64
import io
import json
import os
import secrets
import tempfile
import threading
import time
import uuid
from datetime import datetime

from flask import (Flask, jsonify, redirect, request, session,
                   send_file, send_from_directory)
from werkzeug.security import check_password_hash, generate_password_hash

# ---- reportlab (PDF) ----
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)
from reportlab.lib.styles import ParagraphStyle

from mods.pdfkit import PDF_FONT, ensure_pdf_font
from schema import init_db
from core import (BASE, CFG, STATIC, UPLOADS, _truthy, close_db,
                  current_user, get_db, log, uid, users_count)
from mods.classics_lookup import bp as classics_lookup_bp
from mods.dailytest import bp as dailytest_bp
from mods.docqa import bp as docqa_bp
from mods.todos import bp as todos_bp
from mods.bookmarks import bp as bookmarks_bp
from mods.plan import bp as plan_bp
from mods.team import bp as team_bp
from mods.dtest import bp as dtest_bp
from mods.kb import bp as kb_bp
from mods.review import bp as review_bp
from mods.search import bp as search_bp
from mods.sync import bp as sync_bp
from mods.aisession import bp as aisession_bp
from mods.entries import bp as entries_bp
from mods.handwrite import bp as handwrite_bp
from mods.lianjie import bp as lianjie_bp
from mods.notifications import bp as notifications_bp
from mods.ocr import bp as ocr_bp
from mods.admin import bp as admin_bp
from mods.aichat import bp as aichat_bp
from mods.essays import bp as essays_bp
from mods.hyper import bp as hyper_bp
from mods.policydocs import bp as policydocs_bp
from mods.quiz import bp as quiz_bp
from mods.skin import bp as skin_bp
from mods.tasks import bp as tasks_bp
from mods.theory import bp as theory_bp
from mods.xiyu import bp as xiyu_bp
from mods.ai import _ai_call_or_error, vision_configured, vision_ocr
from mods.files import IMAGE_EXT, _extract_text, _ocr_image
from mods.dist import bp as dist_bp
from mods.drafts import bp as drafts_bp
from mods.find import bp as find_bp
from mods.marks import bp as marks_bp
from mods.notes import bp as notes_bp
from mods.wrongq import bp as wrongq_bp
from mods.gongwen import bp as gongwen_bp
from mods.materials import bp as materials_bp
from mods.shenlun import bp as shenlun_bp
from mods.sucai import bp as sucai_bp
from mods.changkao import bp as changkao_bp
from mods.classics import bp as classics_bp
from mods.drill import bp as drill_bp
from mods.fanwen import bp as fanwen_bp
from mods.news import bp as news_bp
from mods.social import bp as social_bp
from mods.annots import bp as annots_bp

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 单文件最大 64MB
app.teardown_appcontext(close_db)
app.register_blueprint(annots_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(aisession_bp)
app.register_blueprint(entries_bp)
app.register_blueprint(handwrite_bp)
app.register_blueprint(lianjie_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(ocr_bp)
app.register_blueprint(bookmarks_bp)
app.register_blueprint(classics_lookup_bp)
app.register_blueprint(dailytest_bp)
app.register_blueprint(docqa_bp)
app.register_blueprint(todos_bp)
app.register_blueprint(plan_bp)
app.register_blueprint(team_bp)
app.register_blueprint(dtest_bp)
app.register_blueprint(kb_bp)
app.register_blueprint(review_bp)
app.register_blueprint(search_bp)
app.register_blueprint(sync_bp)
app.register_blueprint(aichat_bp)
app.register_blueprint(essays_bp)
app.register_blueprint(hyper_bp)
app.register_blueprint(policydocs_bp)
app.register_blueprint(quiz_bp)
app.register_blueprint(skin_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(theory_bp)
app.register_blueprint(xiyu_bp)
app.register_blueprint(changkao_bp)
app.register_blueprint(classics_bp)
app.register_blueprint(drill_bp)
app.register_blueprint(fanwen_bp)
app.register_blueprint(dist_bp)
app.register_blueprint(drafts_bp)
app.register_blueprint(find_bp)
app.register_blueprint(marks_bp)
app.register_blueprint(notes_bp)
app.register_blueprint(wrongq_bp)
app.register_blueprint(gongwen_bp)
app.register_blueprint(materials_bp)
app.register_blueprint(shenlun_bp)
app.register_blueprint(sucai_bp)
app.register_blueprint(news_bp)
app.register_blueprint(social_bp)

# ---------------------------------------------------------------- 板块结构
SECTIONS = [
    {"key": "xingce", "name": "行测", "icon": "测", "desc": "行政职业能力测验",
     "boards": ["常识判断", "资料分析", "判断推理", "数量关系", "政治理论", "言语理解与表达"]},
    {"key": "shenlun", "name": "申论", "icon": "申", "desc": "申论写作",
     "boards": ["应用文", "议论文"]},
]
ALL_BOARDS = {b for s in SECTIONS for b in s["boards"]}
IDIOM_BOARD = "言语理解与表达"  # 带成语/词语工具的板块

# 密保问题选项
SEC_QUESTIONS = [
    "你的出生城市是？",
    "你母亲的名字是？",
    "你小学的名字是？",
    "你最好朋友的名字是？",
    "你最喜欢的一本书是？",
    "你的幸运数字是？",
]



app.secret_key = CFG["secret_key"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
    SEND_FILE_MAX_AGE_DEFAULT=0,  # 静态文件不长期缓存，浏览器每次校验，避免旧样式
)

_login_fails = {}  # username -> {count, locked_until}

# ---------------------------------------------------------------- 图形验证码（防机器人）
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


# ---------------------------------------------------------------- AI 工具调用
# 已拆到 mods/agent.py。

# ---------------------------------------------------------------- 建表 / 迁移
# 全部 77 张表的 schema 已挪到 schema.py。

# ---------------------------------------------------------------- 访问控制
_PUBLIC_EXACT = {"/register", "/api/register", "/login", "/api/login",
                 "/forgot", "/api/forgot/question", "/api/forgot/reset",
                 "/api/sec_questions", "/api/captcha", "/api/register/status",
                 "/apk", "/download/gongkao.apk", "/deb", "/download/gongkao.deb",
                 "/api/app/version", "/api/desktop/version",
                 "/style.css", "/manifest.webmanifest", "/sw.js", "/favicon.ico"}


def _is_public(path):
    # /skin/ 是壁纸和头像：文件名随机不可猜，登录页没登录时也要能显示壁纸
    return path in _PUBLIC_EXACT or path.startswith("/icon-") or path.startswith("/skin/")


# 外壳文件不缓存（让 Cloudflare 与浏览器都不要缓存，避免旧样式/旧脚本）
_SHELL_NOSTORE = {"/", "/index.html", "/style.css", "/app.js", "/sw.js",
                  "/manifest.webmanifest", "/login", "/register", "/forgot", "/admin"}


@app.after_request
def _shell_no_store(resp):
    if request.path in _SHELL_NOSTORE:
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        resp.headers.pop("Expires", None)
    return resp


@app.before_request
def guard():
    p = request.path
    if _is_public(p):
        return None
    # 后台仅管理员
    if p == "/admin" or p.startswith("/api/admin"):
        if not session.get("user_id"):
            return (jsonify({"error": "未登录", "login": True}), 401) if p.startswith("/api/") else redirect("/login")
        if session.get("role") != "admin":
            return (jsonify({"error": "需要管理员权限"}), 403) if p.startswith("/api/") else redirect("/")
        return None
    if not session.get("user_id"):
        # 一个用户都没有 → 引导去注册
        if users_count() == 0 and not p.startswith("/api/"):
            return redirect("/register")
        if p.startswith("/api/"):
            return jsonify({"error": "未登录", "login": True}), 401
        return redirect("/login")
    return None


# ---------------------------------------------------------------- 注册/登录/找回
@app.get("/register")
def register_page():
    return send_from_directory(STATIC, "register.html")


@app.get("/api/captcha")
def api_captcha():
    cid, url = _captcha_new()
    return jsonify({"id": cid, "image": url})


@app.get("/api/register/status")
def register_status():
    # 首个用户（管理员）注册永远放行，且不需要邀请码
    first = users_count() == 0
    open_ = first or bool(CFG.get("registration_open", True))
    return jsonify({"open": open_,
                    "invite": (not first) and open_ and bool(CFG.get("invite_code"))})


@app.post("/api/register")
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


@app.get("/login")
def login_page():
    if users_count() == 0:
        return redirect("/register")
    return send_from_directory(STATIC, "login.html")


@app.post("/login")
@app.post("/api/login")
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


@app.post("/logout")
@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/forgot")
def forgot_page():
    if users_count() == 0:
        return redirect("/register")
    return send_from_directory(STATIC, "forgot.html")


@app.post("/api/forgot/question")
def api_forgot_question():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    u = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not u or not u["sec_question"]:
        return jsonify({"error": "用户名不存在或未设置密保问题"}), 400
    return jsonify({"ok": True, "question": u["sec_question"]})


@app.post("/api/forgot/reset")
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


@app.get("/api/sec_questions")
def api_sec_questions():
    return jsonify({"questions": SEC_QUESTIONS})


# ---------------------------------------------------------------- 当前用户/板块
@app.get("/api/me")
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


@app.post("/api/home_order")
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


@app.post("/api/ui_order")
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


@app.get("/api/sections")
def api_sections():
    return jsonify({"sections": SECTIONS, "idiom_board": IDIOM_BOARD})


@app.get("/api/account")
def api_account_get():
    u = current_user()
    return jsonify({"username": u["username"], "email": u["email"] or "",
                    "sec_question": u["sec_question"] or ""})


@app.post("/api/account")
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


# ---------------------------------------------------------------- 管理后台
# 已拆到 mods/admin.py。

# ---------------------------------------------------------------- 资料库
# 已拆到 mods/materials.py。

# ---------------------------------------------------------------- 幻灯片播放（PPT/PDF 逐页出图）
# 已拆到 mods/materials.py。

# ---------------------------------------------------------------- 小记（仿语雀）
# 已拆到 mods/notes.py。

# ---------------------------------------------------------------- 知识库（笔记本 + 文档树）
# 已拆到 mods/kb.py。

# ---------------------------------------------------------------- 全文搜索
# 已拆到 mods/search.py。

# ---------------------------------------------------------------- 古诗文速查（唐诗宋词·四书五经）
# 已拆到 mods/classics_lookup.py。

# ---------------------------------------------------------------- AI 助手
# 已拆到 mods/aichat.py。

# ---------------------------------------------------------------- OCR 识图（tesseract）
# 已拆到 mods/ocr.py。

# ---------------------------------------------------------------- 错题本
# 已拆到 mods/wrongq.py。

# ================================================================ 各板块基础知识点
_BOARD_SEC = {b: s["name"] for s in SECTIONS for b in s["boards"]}


@app.get("/api/boardkb")
def boardkb_get():
    board = (request.args.get("board") or "").strip()
    if board not in ALL_BOARDS:
        return jsonify({"error": "板块无效"}), 400
    db = get_db()
    ai = db.execute("SELECT content FROM board_kb WHERE board=?", (board,)).fetchone()
    pts = db.execute("SELECT id,content,created_at FROM board_points WHERE user_id=? AND board=? ORDER BY id DESC",
                     (uid(), board)).fetchall()
    return jsonify({"board": board, "ai": ai["content"] if ai else "",
                    "points": [{"id": r["id"], "content": r["content"], "created_at": r["created_at"]} for r in pts]})


@app.post("/api/boardkb/generate")
def boardkb_generate():
    data = request.get_json(silent=True) or {}
    board = (data.get("board") or "").strip()
    if board not in ALL_BOARDS:
        return jsonify({"error": "板块无效"}), 400
    cached = get_db().execute("SELECT content FROM board_kb WHERE board=?", (board,)).fetchone()
    if cached and not data.get("force"):
        return jsonify({"content": cached["content"], "cached": True})
    sec = _BOARD_SEC.get(board, "行测")
    prompt = (
        "你是资深公务员考试辅导老师。请为「%s · %s」板块系统梳理"
        "「基础知识 + 方法技巧」，面向基础薄弱的考生，用简体中文、Markdown 输出，"
        "分这几节，内容要具体可操作：\n"
        "## 一、这个板块考什么\n## 二、必备基础知识（概念/公式/常识要点）\n"
        "## 三、核心方法与解题技巧\n## 四、常见题型与应对思路\n"
        "## 五、易错点与提分建议\n"
        "要求：每节都要写完整、写到位，覆盖该板块主要考点，不要中途省略或截断。" % (sec, board))
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考辅导老师，讲解系统、具体、条理清晰，用简体中文 Markdown。务必输出完整、不要截断。"},
         {"role": "user", "content": prompt}], temperature=0.5, max_tokens=8000)
    if err:
        return err
    db = get_db()
    db.execute("INSERT OR REPLACE INTO board_kb(board,content) VALUES(?,?)", (board, reply))
    db.commit()
    return jsonify({"content": reply, "cached": False})


@app.post("/api/boardkb/point")
def boardkb_add_point():
    data = request.get_json(silent=True) or {}
    board = (data.get("board") or "").strip()
    content = (data.get("content") or "").strip()
    if board not in ALL_BOARDS or not content:
        return jsonify({"error": "请填写内容"}), 400
    db = get_db()
    cur = db.execute("INSERT INTO board_points(user_id,board,content) VALUES(?,?,?)", (uid(), board, content))
    db.commit()
    return jsonify({"id": cur.lastrowid, "content": content}), 201


@app.delete("/api/boardkb/point/<int:pid>")
def boardkb_del_point(pid):
    get_db().execute("DELETE FROM board_points WHERE id=? AND user_id=?", (pid, uid()))
    get_db().commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 党建理论学习词典（12371.cn）
@app.get("/api/partydict/cats")
def partydict_cats():
    db = get_db()
    rows = db.execute("SELECT cat, COUNT(*) c FROM party_dict GROUP BY cat ORDER BY MIN(id)").fetchall()
    total = db.execute("SELECT COUNT(*) FROM party_dict").fetchone()[0]
    return jsonify({"total": total, "cats": [{"cat": r["cat"], "count": r["c"]} for r in rows]})


@app.get("/api/partydict")
def partydict_list():
    cat = (request.args.get("cat") or "").strip()
    q = (request.args.get("q") or "").strip()
    sql = "SELECT id,cat,term,content,url FROM party_dict WHERE 1=1"
    args = []
    if cat and cat != "全部":
        sql += " AND cat=?"; args.append(cat)
    if q:
        sql += " AND (term LIKE ? OR content LIKE ?)"; args += ["%" + q + "%", "%" + q + "%"]
    sql += " ORDER BY ord, id LIMIT 600"
    rows = get_db().execute(sql, args).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


# ---------------------------------------------------------------- 每日时政（新闻 + 新闻视频）
# 已拆到 mods/news.py。原本这儿有两个连着写的区段标题，新闻路由全归在
# 「每日新闻视频」名下——实际是一块。

# ---------------------------------------------------------------- 申论概括句积累（每日生成，全局共享）
@app.get("/api/gaikuo")
def gaikuo_list():
    date = (request.args.get("date") or "").strip()
    db = get_db()
    dates = [{"date": r["date"], "count": r["c"]} for r in db.execute(
        "SELECT date, COUNT(*) c FROM gaikuo_items GROUP BY date ORDER BY date DESC LIMIT 60").fetchall()]
    if not date and dates:
        date = dates[0]["date"]
    rows = db.execute("SELECT * FROM gaikuo_items WHERE date=? ORDER BY id", (date,)).fetchall() if date else []
    return jsonify({"dates": dates, "date": date, "items": [dict(r) for r in rows]})


# ---------------------------------------------------------------- 每日写作素材（与微信 08:00 推送共用一份生成结果）
# 已拆到 mods/sucai.py。

# ---------------------------------------------------------------- 成文（素材 → 大作文）
# 已拆到 mods/write.py（生成逻辑，无自己的路由）。写作接口从那儿 import。

# ---------------------------------------------------------------- 应用文成文
# 已拆到 mods/gongwen.py。

# ---------------------------------------------------------------- 题库（四川省考卷面）
# 已拆到 mods/quiz.py。

# ---------------------------------------------------------------- 习语金句 / 经典著作
# 已拆到 mods/xiyu.py。

# ---------------------------------------------------------------- 全局 AI 会话中心
# 已拆到 mods/aisession.py。

# ---------------------------------------------------------------- 标注（手写批注/高亮/笔记）
# 已拆到 mods/annots.py。_ann_sentence / _ann_where 在下面的搜索和复习里还要用，
# 从那儿 import 进来（依赖只朝一个方向：app.py → mods/* → core.py）。

# ---------------------------------------------------------------- 常识积累（7板块）
_CS_META = {}
try:
    with open(os.path.join(BASE, "changshi_meta.json"), encoding="utf-8") as _f:
        _CS_META = json.load(_f)
except Exception:
    _CS_META = {"tiers": [], "boards": {}}


# ---------------------------------------------------------------- 古诗文每日推荐
# 已拆到 mods/classics.py。_ensure_classic_freq 跟着走了——古诗文速查和常考
# 都用它，从那儿 import 回来。

# ---------------------------------------------------------------- 衔接表达 · 例句
# 已拆到 mods/lianjie.py。

# ---------------------------------------------------------------- 共享待办（互相监督，每人独立打勾）
# 已拆到 mods/todos.py。

# ---------------------------------------------------------------- 组队（互监搭档：邀请制）
# 已拆到 mods/team.py。

# ---------------------------------------------------------------- 每日任务
# 已拆到 mods/tasks.py。

# ---------------------------------------------------------------- 申论（四大题型讲义 + AI 逐点批改）
# 已拆到 mods/shenlun.py。

# ---------------------------------------------------------------- 范文推荐（仿真卷 + 全套参考答案）
# 已拆到 mods/essays.py。

# ---------------------------------------------------------------- 文档识题：抽出例题 → AI 解答 → 回填成副本
# 已拆到 mods/docqa.py。

# ---------------------------------------------------------------- 备考规划（AI 按你的真实学习数据排当天计划）

# ---------------------------------------------------------------- 40 天冲刺路线图
# 已拆到 mods/plan.py。

# ---------------------------------------------------------------- 每日巩固测试（按当天学的内容出小测）
# 已拆到 mods/dailytest.py。

# ---------------------------------------------------------------- 专项练（资料/判断/数量）
# 已拆到 mods/dtest.py。

# ---------------------------------------------------------------- 消息中心（有新内容就提醒，点开直达）
# 已拆到 mods/notifications.py。

# ---------------------------------------------------------------- 申论真题卷：上传 → 自动拆题
# 已拆到 mods/shenlun.py。

# ---------------------------------------------------------------- 小题训练：找点 + 写点
# 已拆到 mods/find.py。

# ---------------------------------------------------------------- 常考（高频考点合集）
# 已拆到 mods/changkao.py（含上位词 /api/hyper 的详情——它本就是常考的一个板块）。
# CK_TO_ENTRY 被复习那边用，从那儿 import 回来。

# ---------------------------------------------------------------- 上位词积累
# 已拆到 mods/hyper.py。

# ---------------------------------------------------------------- 应用文上位词
# 已拆到 mods/gongwen.py。

# ---------------------------------------------------------------- 手写识别（申论作答）
# 已拆到 mods/handwrite.py。

# ---------------------------------------------------------------- 本地手写识别（Zinnia，离线瞬时）
# 电脑端不出网、毫秒级；准度不如 Google/ML Kit，作为"快"的选项，拿不准可切云端兜准。
_ZINNIA = None
_zinnia_lock = threading.Lock()
_ZINNIA_MODEL = os.environ.get("GONGKAO_ZINNIA_MODEL",
                               "/usr/share/tegaki/models/zinnia/handwriting-zh_CN.model")


def _zinnia():
    """懒加载 Zinnia 识别器（ctypes 直调 libzinnia）。装不上就返回 None，前端自动退云端。"""
    global _ZINNIA
    if _ZINNIA is not None:
        return _ZINNIA or None
    try:
        import ctypes
        z = ctypes.CDLL("libzinnia.so.0")
        z.zinnia_recognizer_new.restype = ctypes.c_void_p
        z.zinnia_recognizer_open.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        z.zinnia_recognizer_open.restype = ctypes.c_int
        z.zinnia_character_new.restype = ctypes.c_void_p
        z.zinnia_character_clear.argtypes = [ctypes.c_void_p]
        z.zinnia_character_set_width.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        z.zinnia_character_set_height.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        z.zinnia_character_add.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int]
        z.zinnia_recognizer_classify.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        z.zinnia_recognizer_classify.restype = ctypes.c_void_p
        z.zinnia_result_size.argtypes = [ctypes.c_void_p]
        z.zinnia_result_size.restype = ctypes.c_size_t
        z.zinnia_result_value.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        z.zinnia_result_value.restype = ctypes.c_char_p
        z.zinnia_result_destroy.argtypes = [ctypes.c_void_p]
        z.zinnia_character_destroy.argtypes = [ctypes.c_void_p]
        rec = z.zinnia_recognizer_new()
        if not rec or not z.zinnia_recognizer_open(rec, _ZINNIA_MODEL.encode()):
            _ZINNIA = False
            return None
        _ZINNIA = (z, rec)
        return _ZINNIA
    except Exception:
        _ZINNIA = False
        return None


def _zinnia_norm(ink, side=256, pad_ratio=0.12):
    """按字的外接框把笔迹居中归一化到一个正方形里——不管写在画布哪、多大，
    喂给 Zinnia 的都是"框好、居中、统一大小"的字，识别率比拿画布尺寸归一化高很多。"""
    xs_all, ys_all = [], []
    for st in ink:
        xs_all += list(st[0]) if len(st) > 0 else []
        ys_all += list(st[1]) if len(st) > 1 else []
    if not xs_all:
        return [], side
    minx, maxx = min(xs_all), max(xs_all)
    miny, maxy = min(ys_all), max(ys_all)
    bw, bh = max(1.0, maxx - minx), max(1.0, maxy - miny)
    span = max(bw, bh)
    pad = span * pad_ratio
    scale = side / (span + 2 * pad)
    ox = pad + (span - bw) / 2.0        # 居中：短边两侧补空
    oy = pad + (span - bh) / 2.0
    out = []
    for st in ink:
        xs = st[0] if len(st) > 0 else []
        ys = st[1] if len(st) > 1 else []
        pts = []
        for i in range(min(len(xs), len(ys))):
            nx = int((xs[i] - minx + ox) * scale)
            ny = int((ys[i] - miny + oy) * scale)
            pts.append((nx, ny))
        out.append(pts)
    return out, side


def _zinnia_recognize(ink, w, h, n=12):
    zz = _zinnia()
    if not zz:
        return None
    z, rec = zz
    strokes, side = _zinnia_norm(ink)      # 外接框居中归一化，跟画布大小无关
    with _zinnia_lock:      # zinnia 识别器非线程安全，串行化
        ch = z.zinnia_character_new()
        z.zinnia_character_clear(ch)
        z.zinnia_character_set_width(ch, side)
        z.zinnia_character_set_height(ch, side)
        for si, pts in enumerate(strokes):
            for (x, y) in pts:
                z.zinnia_character_add(ch, si, x, y)
        res = z.zinnia_recognizer_classify(rec, ch, n)
        out = []
        if res:
            for i in range(z.zinnia_result_size(res)):
                v = z.zinnia_result_value(res, i)
                if v:
                    out.append(v.decode("utf-8", "ignore"))
            z.zinnia_result_destroy(res)
        z.zinnia_character_destroy(ch)
        return out


@app.post("/api/handwrite/local")
def handwrite_local():
    d = request.get_json(silent=True) or {}
    ink = d.get("ink") or []
    if not ink:
        return jsonify({"candidates": []})
    try:
        w = max(1, int(d.get("w") or 300))
        h = max(1, int(d.get("h") or 300))
    except Exception:
        w = h = 300
    cands = _zinnia_recognize(ink, w, h)
    if cands is None:
        return jsonify({"candidates": [], "error": "本地手写引擎未就绪"}), 200
    return jsonify({"candidates": cands[:12], "engine": "zinnia"})


# ---------------------------------------------------------------- 理论基础（马原/毛中特/习思想）
# 已拆到 mods/theory.py。

# ---------------------------------------------------------------- AI 附件文本提取（图片OCR/文件抽取）
@app.post("/api/ai/extract")
def ai_extract_attachment():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "没有文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    mime = (f.mimetype or "").lower()
    # 拍照/粘贴的图片常常没有扩展名，按 MIME 兜底判断
    is_img = mime.startswith("image/") or ext in IMAGE_EXT
    if is_img and ext not in IMAGE_EXT:
        ext = "." + (mime.split("/")[-1].split("+")[0] or "png")
    tmp = os.path.join(tempfile.gettempdir(), "aiatt_" + uuid.uuid4().hex + ext)
    f.save(tmp)
    text, err = "", ""
    try:
        if is_img:
            if vision_configured():          # 视觉模型：比 OCR 更能读懂图片（含手写、排版）
                try:
                    text = vision_ocr(tmp)
                except Exception:
                    text = ""
            if not text.strip():
                text = _ocr_image(tmp)       # 兜底
            if not text.strip():
                err = "图片里没识别出文字（可能是纯图形、字太小或太模糊，可放大后重拍）"
        else:
            text = _extract_text(tmp, ext) or ""
            if not text.strip():
                err = "这个格式（%s）暂时提取不出文字，可先转成 PDF 或截图上传" % (ext or "未知")
    except Exception as e:
        err = "解析失败：%s" % e
    finally:
        try:
            os.remove(tmp)
        except Exception:
            log.debug("临时文件没删掉", exc_info=True)
    text = (text or "").strip()
    if not text:
        return jsonify({"error": err or "没能从附件中提取到文字"}), 200
    return jsonify({"text": text[:6000], "name": f.filename})


@app.get("/api/changshi/boards")
def changshi_boards():
    db = get_db()
    counts = {}
    for r in db.execute("SELECT board, COUNT(*) c FROM changshi_items GROUP BY board"):
        counts[r["board"]] = r["c"]
    tiers = []
    for t in _CS_META.get("tiers", []):
        tiers.append({"name": t["name"], "boards": [
            {"name": b, "count": counts.get(b, 0),
             "topics": len(_CS_META["boards"].get(b, {}).get("topics", []))}
            for b in t["boards"]]})
    return jsonify({"tiers": tiers})


@app.get("/api/changshi/board")
def changshi_board():
    board = (request.args.get("board") or "").strip()
    topic = (request.args.get("topic") or "").strip()
    meta = _CS_META.get("boards", {}).get(board)
    if not meta:
        return jsonify({"error": "板块无效"}), 404
    db = get_db()
    tcounts = {r["topic"]: r["c"] for r in db.execute(
        "SELECT topic, COUNT(*) c FROM changshi_items WHERE board=? GROUP BY topic", (board,))}
    topics = [{"name": t["name"], "tezheng": t.get("tezheng", ""), "silu": t.get("silu", ""),
               "map": t.get("map", ""), "count": tcounts.get(t["name"], 0)}
              for t in meta.get("topics", [])]
    if not topic and topics:
        topic = topics[0]["name"]
    rows = db.execute("SELECT id,title,content,date,source FROM changshi_items "
                      "WHERE board=? AND topic=? ORDER BY date DESC, id DESC LIMIT 300",
                      (board, topic)).fetchall()
    return jsonify({"board": board, "overview": meta.get("overview", ""), "daily": bool(meta.get("daily")),
                    "topics": topics, "topic": topic, "items": [dict(r) for r in rows]})


# ---------------------------------------------------------------- 遗忘曲线复习（艾宾浩斯间隔）
# 已拆到 mods/review.py。

# ---------------------------------------------------------------- 数据版本（浏览器/手机自动同步用）
# 已拆到 mods/sync.py。

# ---------------------------------------------------------------- 时政要文库（重要文件全文 + AI 政策解读）
# 已拆到 mods/policydocs.py。

# ---------------------------------------------------------------- 人民时评·申论范文
# 已拆到 mods/fanwen.py（零反向依赖）。

# ================================================================ 好友 / 聊天 / 云盘
# 已拆到 mods/social.py（三者内聚：网盘文件能发进聊天、聊天文件能存回网盘）。

# ---------------------------------------------------------------- 安卓包下载 / 应用内更新
def _apk_meta():
    """从 dist/apk.json 读当前发布的版本信息（构建脚本生成）。"""
    p = os.path.join(BASE, "dist", "apk.json")
    try:
        with open(p, encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return {}


@app.get("/api/app/version")
def app_version():
    """APP 启动时来问一次：有没有新版本。"""
    apk = os.path.join(BASE, "dist", "gongkao.apk")
    meta = _apk_meta()
    return jsonify({
        "version_code": int(meta.get("version_code") or 0),
        "version_name": meta.get("version_name") or "",
        "notes": meta.get("notes") or "",
        "size": os.path.getsize(apk) if os.path.exists(apk) else 0,
        "url": "/download/gongkao.apk",
        "available": os.path.exists(apk),
    })


# ---------------------------------------------------------------- 资料库：自定义分类
# 已拆到 mods/materials.py。

# ---------------------------------------------------------------- 资料库：共享给指定成员
# 已拆到 mods/materials.py。

# ---------------------------------------------------------------- 通用「划重点」
# 已拆到 mods/marks.py。

# ---------------------------------------------------------------- 书签（看到哪了）
# 已拆到 mods/bookmarks.py。

# ---------------------------------------------------------------- 外观：头像 / 壁纸
# 已拆到 mods/skin.py。

# ---------------------------------------------------------------- 草稿本（错题本里，平时打草稿）
# 已拆到 mods/drafts.py。

# ---------------------------------------------------------------- 静态前端
@app.route("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.route("/<path:fname>")
def static_files(fname):
    return send_from_directory(STATIC, fname)


# ---------------------------------------------------------------- 成语/词语 API（按用户隔离）
# 已拆到 mods/entries.py。

# ---------------------------------------------------------------- PDF 导出
def build_pdf(entries, opts):
    ensure_pdf_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title="公考·成语词语积累")
    f = PDF_FONT
    st_title = ParagraphStyle("t", fontName=f, fontSize=20, leading=26, alignment=1, spaceAfter=2)
    st_sub = ParagraphStyle("s", fontName=f, fontSize=10, leading=14, alignment=1,
                            textColor=colors.grey, spaceAfter=10)
    st_word = ParagraphStyle("w", fontName=f, fontSize=15, leading=20)
    st_py = ParagraphStyle("py", fontName=f, fontSize=11, leading=20,
                           textColor=colors.HexColor("#1a6fb5"), alignment=2)
    st_label = ParagraphStyle("lb", fontName=f, fontSize=10.5, leading=16,
                              textColor=colors.HexColor("#444444"))
    st_blank = ParagraphStyle("bk", fontName=f, fontSize=10.5, leading=22,
                              textColor=colors.HexColor("#bbbbbb"))
    story = [Paragraph("公考·选词填空　成语 / 词语积累", st_title),
             Paragraph(datetime.now().strftime("导出于 %Y-%m-%d %H:%M") +
                       f"　共 {len(entries)} 条" +
                       ("　【默写版】" if opts.get("mode") == "recite" else ""), st_sub)]
    recite = opts.get("mode") == "recite"
    inc_der, inc_exa, inc_note = opts.get("derivation", True), opts.get("example", True), opts.get("note", True)
    for i, e in enumerate(entries, 1):
        word = (e.get("word") or "").replace("\n", " ")
        head = Table([[Paragraph(f'<b>{i}. {word}</b>', st_word),
                       Paragraph(e.get("pinyin") or "", st_py)]], colWidths=[None, 55 * mm])
        head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        story.append(head)

        def field(label, value):
            value = (value or "").strip().replace("\n", " ")
            if value:
                story.append(Paragraph(f'<font color="#888888">{label}</font>　{value}', st_label))
        if recite:
            story.append(Paragraph("释义：______________________________________________", st_blank))
        else:
            field("释义", e.get("explanation"))
            if inc_der:
                field("出处", e.get("derivation"))
            if inc_exa:
                field("例句", e.get("example"))
        if inc_note and e.get("note"):
            field("笔记", e.get("note"))
        story.append(Spacer(1, 4))
        story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#dddddd")))
        story.append(Spacer(1, 6))
    doc.build(story)
    buf.seek(0)
    return buf



@app.route("/api/export", methods=["GET", "POST"])
def api_export():
    if request.method == "GET":
        a = request.args
        data = {"mode": a.get("mode", "study"), "category": a.get("category", ""),
                "starred": _truthy(a.get("starred"), False), "derivation": _truthy(a.get("der")),
                "example": _truthy(a.get("exa")), "note": _truthy(a.get("note"))}
        ids_s = a.get("ids", "")
        if ids_s:
            data["ids"] = [int(x) for x in ids_s.split(",") if x.strip().isdigit()]
    else:
        data = request.get_json(force=True, silent=True) or {}
    db = get_db()
    ids = data.get("ids")
    if ids:
        qmarks = ",".join("?" * len(ids))
        rows = db.execute(
            f"SELECT * FROM entries WHERE id IN ({qmarks}) AND user_id=? ORDER BY id DESC",
            ids + [uid()]).fetchall()
    else:
        sql = "SELECT * FROM entries WHERE user_id=?"
        args = [uid()]
        cat = (data.get("category") or "").strip()
        if cat in ("成语", "词语"):
            sql += " AND category=?"
            args.append(cat)
        if data.get("starred"):
            sql += " AND starred=1"
        sql += " ORDER BY id DESC"
        rows = db.execute(sql, args).fetchall()
    entries = [dict(r) for r in rows]
    if not entries:
        return jsonify({"error": "没有可导出的内容"}), 400
    opts = {"mode": data.get("mode", "study"), "derivation": data.get("derivation", True),
            "example": data.get("example", True), "note": data.get("note", True)}
    pdf = build_pdf(entries, opts)
    fname = "公考积累_%s%s.pdf" % (datetime.now().strftime("%Y%m%d_%H%M"),
                                 "_默写版" if opts["mode"] == "recite" else "")
    return send_file(pdf, mimetype="application/pdf", as_attachment=True, download_name=fname)


# 启动时初始化
init_db()
ensure_pdf_font()
os.makedirs(UPLOADS, exist_ok=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    if a.debug:
        app.run(host=a.host, port=a.port, debug=True)
    else:
        from waitress import serve
        print(f" * 公考助手已启动： http://{a.host}:{a.port}")
        serve(app, host=a.host, port=a.port, threads=32)
