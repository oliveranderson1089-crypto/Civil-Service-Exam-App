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
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta

from flask import (Flask, jsonify, redirect, request, session,
                   send_file, send_from_directory)
from werkzeug.security import check_password_hash, generate_password_hash
from pypinyin import Style, pinyin as _pinyin

# ---- reportlab (PDF) ----
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)
from reportlab.lib.styles import ParagraphStyle

from schema import init_db
from core import (BASE, CFG, DB, STATIC, UPLOADS, bg_new, bg_set, close_db,
                  current_user, get_db, log, uid, uname)
from mods.bookmarks import bp as bookmarks_bp
from mods.dtest import bp as dtest_bp
from mods.kb import bp as kb_bp
from mods.review import RV_GROUP, RV_GROUPS, _review_due
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
from mods.ai import (_ai_call_or_error, vision_chat, vision_configured,
                     vision_ocr)
from mods.files import (IMAGE_EXT, OFFICE_EXT, _extract_text, _ocr_image,
                        _ocr_image_page, _office_to_pdf, _strip_artifacts,
                        _user_dir)
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
from mods.classics import _ensure_classic_freq
from mods.classics import bp as classics_bp
from mods.drill import _dtest_to_wrongq
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

def users_count():
    return get_db().execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def _bump_sync():
    """组队/互监有变动时想让对端尽快刷新——版本指纹本身就含这些表（见 /api/sync），
    这里留空即可，作为语义标记。"""
    pass


def _mark_study(db, u, date):
    """记一个学习日（完成备考规划任务、或互监任务被确认）。一天一条，重复无副作用。"""
    if u and date:
        db.execute("INSERT OR IGNORE INTO study_days(user_id,date) VALUES(?,?)", (u, date))


def _study_stats(db, u):
    """连续学习天数（到今天或昨天为止未断）+ 累计学习天数。"""
    days = {r[0] for r in db.execute("SELECT date FROM study_days WHERE user_id=?", (u,))}
    total = len(days)
    if not total:
        return {"streak": 0, "total": 0}
    today = datetime.now().date()
    cur = today
    if today.isoformat() not in days:            # 今天还没学，连胜看到昨天为止
        cur = today - timedelta(days=1)
        if cur.isoformat() not in days:
            return {"streak": 0, "total": total}
    streak = 0
    while cur.isoformat() in days:
        streak += 1
        cur = cur - timedelta(days=1)
    return {"streak": streak, "total": total}


def is_admin():
    return session.get("role") == "admin"


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


# ---------------------------------------------------------------- 字体（PDF）
EMBED_FONT_CANDIDATES = [
    ("CN", "/usr/share/fonts/truetype/arphic/uming.ttc", 0),
    ("CN", "/usr/share/fonts/truetype/arphic/ukai.ttc", 0),
]
PDF_FONT = "STSong-Light"
_font_ready = False


def ensure_pdf_font():
    global PDF_FONT, _font_ready
    if _font_ready:
        return PDF_FONT
    for name, path, idx in EMBED_FONT_CANDIDATES:
        try:
            if not os.path.exists(path):
                continue
            f = TTFont(name, path) if idx is None else TTFont(name, path, subfontIndex=idx)
            pdfmetrics.registerFont(f)
            PDF_FONT = name
            _font_ready = True
            return PDF_FONT
        except Exception:
            continue
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    except Exception:
        log.error("中文字体全部注册失败：导出的 PDF 会是乱码方框")
    PDF_FONT = "STSong-Light"
    _font_ready = True
    return PDF_FONT


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

# ================================================================ 古诗文速查（唐诗宋词·四书五经）
CLASSIC_ORDER = ["唐诗", "宋词", "元曲", "诗经", "先秦", "汉魏六朝", "明清",
                 "论语", "孟子", "大学", "中庸", "孙子兵法", "资治通鉴", "增广贤文"]


@app.get("/api/classics/categories")
def classics_categories():
    rows = get_db().execute("SELECT category, COUNT(*) c FROM classics GROUP BY category").fetchall()
    cats = [{"name": r["category"], "count": r["c"]} for r in rows]
    cats.sort(key=lambda x: CLASSIC_ORDER.index(x["name"]) if x["name"] in CLASSIC_ORDER else 99)
    star_cnt = get_db().execute("SELECT COUNT(*) c FROM classic_stars WHERE user_id=?", (uid(),)).fetchone()["c"]
    return jsonify({"categories": cats, "star_count": star_cnt})


@app.get("/api/classics")
def classics_list():
    cat = (request.args.get("category") or "").strip()
    q = (request.args.get("q") or "").strip()
    star = request.args.get("star") == "1"
    try:
        page = max(1, int(request.args.get("page") or 1))
    except Exception:
        page = 1
    size = 10
    db = get_db()
    _ensure_classic_freq(db)   # 首次访问即按考频给古诗文打分
    where, args = [], []
    join = ""
    if star:
        join = "JOIN classic_stars s ON s.classic_id=c.id AND s.user_id=?"
        args.append(uid())
    if cat:
        where.append("c.category=?"); args.append(cat)
    if q:
        where.append("(c.content LIKE ? OR c.title LIKE ? OR c.author LIKE ?)")
        like = "%" + q + "%"; args += [like, like, like]
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    total = db.execute("SELECT COUNT(*) n FROM classics c %s%s" % (join, wsql), args).fetchone()["n"]
    rows = db.execute("SELECT c.* FROM classics c %s%s ORDER BY c.freq DESC, c.id LIMIT ? OFFSET ?" % (join, wsql),
                      args + [size, (page - 1) * size]).fetchall()
    starred = set(r["classic_id"] for r in
                  db.execute("SELECT classic_id FROM classic_stars WHERE user_id=?", (uid(),)).fetchall())
    items = [{"id": r["id"], "category": r["category"], "title": r["title"], "author": r["author"],
              "dynasty": r["dynasty"], "content": r["content"], "sub": r["sub"],
              "starred": r["id"] in starred} for r in rows]
    return jsonify({"items": items, "total": total, "page": page,
                    "pages": max(1, (total + size - 1) // size)})


@app.post("/api/classics/<int:cid>/star")
def classics_star(cid):
    if not get_db().execute("SELECT 1 FROM classics WHERE id=?", (cid,)).fetchone():
        return jsonify({"error": "未找到"}), 404
    starred = bool((request.get_json(silent=True) or {}).get("starred"))
    db = get_db()
    if starred:
        db.execute("INSERT OR IGNORE INTO classic_stars(user_id,classic_id) VALUES(?,?)", (uid(), cid))
    else:
        db.execute("DELETE FROM classic_stars WHERE user_id=? AND classic_id=?", (uid(), cid))
    db.commit()
    return jsonify({"ok": True, "starred": starred})


def _py_line(line):
    """一行文字的拼音（仅汉字，标点忽略），空格分隔。"""
    out = []
    for seg in _pinyin(line or "", style=Style.TONE, errors="ignore"):
        if seg and seg[0]:
            out.append(seg[0])
    return " ".join(out)


@app.get("/api/classics/<int:cid>/detail")
def classics_detail(cid):
    r = get_db().execute("SELECT * FROM classics WHERE id=?", (cid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    lines = (r["content"] or "").split("\n")
    ai = get_db().execute("SELECT content FROM classic_ai WHERE classic_id=?", (cid,)).fetchone()
    starred = bool(get_db().execute(
        "SELECT 1 FROM classic_stars WHERE user_id=? AND classic_id=?", (uid(), cid)).fetchone())
    return jsonify({
        "id": r["id"], "category": r["category"], "title": r["title"], "author": r["author"],
        "dynasty": r["dynasty"], "sub": r["sub"] or "",
        "lines": lines, "pinyin": [_py_line(l) for l in lines],
        "translation": (r["translation"] or "") if "translation" in r.keys() else "",
        "appreciation": (r["appreciation"] or "") if "appreciation" in r.keys() else "",
        "ai_explain": ai["content"] if ai else "", "starred": starred,
    })


@app.post("/api/classics/<int:cid>/ai")
def classics_ai(cid):
    r = get_db().execute("SELECT * FROM classics WHERE id=?", (cid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    force = (request.get_json(silent=True) or {}).get("force")
    cached = get_db().execute("SELECT content FROM classic_ai WHERE classic_id=?", (cid,)).fetchone()
    if cached and not force:
        return jsonify({"content": cached["content"], "cached": True})
    prompt = (
        "请为下面这篇《%s》（%s·%s）做讲解，面向备考公务员的考生，用简体中文，"
        "分三部分并用小标题：\n【译文】通顺白话，完整翻译全文。\n"
        "【注释】解释重点字词、典故（分条）。\n"
        "【赏析·可用于申论】点出主旨，以及可引用的角度/场景。\n\n原文：\n%s"
    ) % (r["title"], r["dynasty"], r["author"], r["content"])
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是古诗文讲解助手，准确、简洁、条理清晰，用简体中文。"},
         {"role": "user", "content": prompt}], temperature=0.5, max_tokens=1800)
    if err:
        return err
    db = get_db()
    db.execute("INSERT OR REPLACE INTO classic_ai(classic_id,content) VALUES(?,?)", (cid, reply))
    db.commit()
    return jsonify({"content": reply, "cached": False})


def _classics_query(category, q, star, ids):
    db = get_db()
    if ids:
        qmarks = ",".join("?" * len(ids))
        return db.execute("SELECT * FROM classics WHERE id IN (%s) ORDER BY id" % qmarks, ids).fetchall()
    where, args, join = [], [], ""
    if star:
        join = "JOIN classic_stars s ON s.classic_id=c.id AND s.user_id=?"
        args.append(uid())
    if category:
        where.append("c.category=?"); args.append(category)
    if q:
        where.append("(c.content LIKE ? OR c.title LIKE ? OR c.author LIKE ?)")
        like = "%" + q + "%"; args += [like, like, like]
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    return db.execute("SELECT c.* FROM classics c %s%s ORDER BY c.freq DESC, c.id LIMIT 400" % (join, wsql), args).fetchall()


def build_classics_pdf(rows, opts):
    ensure_pdf_font()
    f = PDF_FONT
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title="古诗文积累")
    st_title = ParagraphStyle("t", fontName=f, fontSize=20, leading=26, alignment=1, spaceAfter=2)
    st_sub = ParagraphStyle("s", fontName=f, fontSize=10, leading=14, alignment=1,
                            textColor=colors.grey, spaceAfter=10)
    st_h = ParagraphStyle("h", fontName=f, fontSize=15, leading=20, spaceBefore=2)
    st_meta = ParagraphStyle("m", fontName=f, fontSize=10, leading=14, textColor=colors.grey)
    st_line = ParagraphStyle("l", fontName=f, fontSize=13, leading=20)
    st_py = ParagraphStyle("py", fontName=f, fontSize=9.5, leading=13,
                           textColor=colors.HexColor("#1a6fb5"))
    st_label = ParagraphStyle("lb", fontName=f, fontSize=10.5, leading=16, textColor=colors.HexColor("#444444"))
    inc_py = opts.get("pinyin", True)
    inc_tr = opts.get("translation", True)
    story = [Paragraph("古诗文积累", st_title),
             Paragraph(datetime.now().strftime("导出于 %Y-%m-%d %H:%M") + f"　共 {len(rows)} 篇", st_sub)]
    for i, r in enumerate(rows, 1):
        story.append(Paragraph(f"<b>{i}. {r['title']}</b>", st_h))
        meta = " · ".join(x for x in [r["dynasty"], r["author"], r["category"]] if x)
        story.append(Paragraph(meta, st_meta))
        story.append(Spacer(1, 3))
        for line in (r["content"] or "").split("\n"):
            if not line.strip():
                continue
            if inc_py:
                py = _py_line(line)
                if py:
                    story.append(Paragraph(py, st_py))
            story.append(Paragraph(line, st_line))
        tr = (r["translation"] or "") if "translation" in r.keys() else ""
        if inc_tr and tr.strip():
            story.append(Spacer(1, 3))
            story.append(Paragraph('<font color="#888888">译文</font>　' + tr.replace("\n", "<br/>"), st_label))
        story.append(Spacer(1, 5))
        story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#dddddd")))
        story.append(Spacer(1, 6))
    doc.build(story)
    buf.seek(0)
    return buf


@app.route("/api/classics/export", methods=["GET", "POST"])
def classics_export():
    if request.method == "GET":
        a = request.args
        category = a.get("category", ""); q = a.get("q", "")
        star = _truthy(a.get("star"), False)
        ids = [int(x) for x in a.get("ids", "").split(",") if x.strip().isdigit()]
        opts = {"pinyin": _truthy(a.get("py")), "translation": _truthy(a.get("tr"))}
    else:
        d = request.get_json(silent=True) or {}
        category = d.get("category", ""); q = d.get("q", "")
        star = bool(d.get("star")); ids = d.get("ids") or []
        opts = {"pinyin": d.get("pinyin", True), "translation": d.get("translation", True)}
    rows = _classics_query(category, q, star, ids)
    if not rows:
        return jsonify({"error": "没有可导出的内容"}), 400
    pdf = build_classics_pdf(rows, opts)
    fname = "古诗文积累_%s.pdf" % datetime.now().strftime("%Y%m%d_%H%M")
    return send_file(pdf, mimetype="application/pdf", as_attachment=True, download_name=fname)


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
def _my_team(db, u=None):
    """当前用户所在的队 id（一人最多在一个队里）。"""
    u = u or uid()
    r = db.execute("SELECT team_id FROM team_members WHERE user_id=? LIMIT 1", (u,)).fetchone()
    return r["team_id"] if r else None


def _team_members(db, team_id):
    rows = db.execute("SELECT m.user_id, u.username FROM team_members m "
                      "JOIN users u ON u.id=m.user_id WHERE m.team_id=? ORDER BY m.user_id", (team_id,))
    return [{"id": r["user_id"], "name": r["username"]} for r in rows]


def _todo_members(db):
    """互监成员 = 我所在队的成员；没组队就是空。"""
    t = _my_team(db)
    return _team_members(db, t) if t else []


def _sync_todo_done(db, tid, member_ids):
    """所有成员都打勾 → 整条标记完成（推送脚本与排序依赖 done 字段）。"""
    got = {r[0] for r in db.execute("SELECT user_id FROM shared_todo_done WHERE todo_id=?", (tid,))}
    all_done = bool(member_ids) and set(member_ids) <= got
    if all_done:
        db.execute("UPDATE shared_todos SET done=1, done_at=datetime('now','localtime') WHERE id=?", (tid,))
    else:
        db.execute("UPDATE shared_todos SET done=0, done_at=NULL WHERE id=?", (tid,))


@app.get("/api/shared_todos")
def shared_todos_list():
    db = get_db()
    team = _my_team(db)
    members = _team_members(db, team) if team else []
    if not team:
        return jsonify({"items": [], "members": [], "me": current_user()["username"],
                        "me_id": uid(), "no_team": True})
    rows = db.execute("SELECT * FROM shared_todos WHERE team_id=? ORDER BY done, id DESC LIMIT 200",
                      (team,)).fetchall()
    marks, by = {}, {}
    for r in db.execute("SELECT todo_id, user_id, by_name FROM shared_todo_done"):
        marks.setdefault(r["todo_id"], []).append(r["user_id"])
        by.setdefault(r["todo_id"], {})[str(r["user_id"])] = r["by_name"] or ""
    items = []
    for r in rows:
        d = dict(r)
        d["done_ids"] = marks.get(r["id"], [])
        d["done_by_map"] = by.get(r["id"], {})   # {被确认人id: 确认人}
        d["is_plan"] = (r["source"] == "plan")   # 来自备考规划的条目，前端加标记
        items.append(d)
    return jsonify({"items": items, "members": members,
                    "me": current_user()["username"], "me_id": uid()})


@app.post("/api/shared_todos")
def shared_todos_add():
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return jsonify({"error": "请输入内容"}), 400
    db = get_db()
    team = _my_team(db)
    if not team:
        return jsonify({"error": "先组队才能加共享待办"}), 400
    cur = db.execute("INSERT INTO shared_todos(text,created_by,team_id) VALUES(?,?,?)",
                     (text[:200], current_user()["username"], team))
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.post("/api/shared_todos/<int:tid>/toggle")
def shared_todos_toggle(tid):
    """body: {user_id} —— 交叉确认：只能给**搭档**打勾，不能给自己打勾。"""
    db = get_db()
    if not db.execute("SELECT 1 FROM shared_todos WHERE id=?", (tid,)).fetchone():
        return jsonify({"error": "未找到"}), 404
    members = _todo_members(db)
    mids = [m["id"] for m in members]
    me = uid()
    if me not in mids:
        return jsonify({"error": "你还没组队，先去互监待办里搜账号组队"}), 403
    if len(mids) < 2:
        return jsonify({"error": "组队里还没有搭档，先邀请一个搭档"}), 400
    who = int((request.get_json(silent=True) or {}).get("user_id") or 0)
    if who not in mids:
        return jsonify({"error": "不是互监成员"}), 400
    if who == me:
        return jsonify({"error": "不能给自己打勾，等搭档来确认 🤝"}), 403
    name = next(m["name"] for m in members if m["id"] == who)
    hit = db.execute("SELECT by_user FROM shared_todo_done WHERE todo_id=? AND user_id=?",
                     (tid, who)).fetchone()
    if hit:
        # 谁确认的谁才能撤销（防止互相把对方的确认取消掉）
        if hit["by_user"] and hit["by_user"] != me:
            return jsonify({"error": "这个勾是别人确认的，只有确认人能撤销"}), 403
        db.execute("DELETE FROM shared_todo_done WHERE todo_id=? AND user_id=?", (tid, who))
        on = False
    else:
        db.execute("INSERT OR IGNORE INTO shared_todo_done(todo_id,user_id,username,by_user,by_name) "
                   "VALUES(?,?,?,?,?)", (tid, who, name, me, current_user()["username"]))
        on = True
        # 被确认完成的人（who）今天算学习过了（组队期间互监也计入学习天数）
        _mark_study(db, who, datetime.now().strftime("%Y-%m-%d"))
    _sync_todo_done(db, tid, mids)
    db.commit()
    rows = db.execute("SELECT user_id, by_name FROM shared_todo_done WHERE todo_id=?", (tid,)).fetchall()
    return jsonify({"done": on, "user_id": who, "done_ids": [r["user_id"] for r in rows]})


@app.delete("/api/shared_todos/<int:tid>")
def shared_todos_del(tid):
    db = get_db()
    db.execute("DELETE FROM shared_todo_done WHERE todo_id=?", (tid,))
    db.execute("DELETE FROM shared_todos WHERE id=?", (tid,))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 组队（互监搭档：邀请制）
@app.get("/api/team")
def team_info():
    """我的组队状态 + 收到/发出的申请（前端据此渲染组队 UI）。"""
    db = get_db()
    me = uid()
    team = _my_team(db)
    tinfo = None
    if team:
        tinfo = {"id": team, "members": _team_members(db, team),
                 "partner": next((m for m in _team_members(db, team) if m["id"] != me), None)}
    incoming = [{"id": r["id"], "from_uid": r["from_uid"], "from_name": uname(db, r["from_uid"]),
                 "kind": r["kind"]} for r in db.execute(
        "SELECT * FROM team_requests WHERE to_uid=? AND status='pending' ORDER BY id DESC", (me,))]
    outgoing = [{"id": r["id"], "to_uid": r["to_uid"], "to_name": uname(db, r["to_uid"]),
                 "kind": r["kind"]} for r in db.execute(
        "SELECT * FROM team_requests WHERE from_uid=? AND status='pending' ORDER BY id DESC", (me,))]
    return jsonify({"team": tinfo, "incoming": incoming, "outgoing": outgoing,
                    "me": uname(db, me), "me_id": me, "study": _study_stats(db, me)})


@app.get("/api/team/search")
def team_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"users": []})
    db = get_db()
    me = uid()
    like = "%" + q + "%"
    rows = db.execute("SELECT id, username FROM users WHERE (username LIKE ? OR CAST(id AS TEXT)=?) "
                      "AND id<>? ORDER BY id LIMIT 20", (like, q, me)).fetchall()
    out = []
    for r in rows:
        out.append({"id": r["id"], "name": r["username"], "in_team": bool(_my_team(db, r["id"]))})
    return jsonify({"users": out})


@app.post("/api/team/request")
def team_request():
    """发组队申请：{to_uid}。"""
    db = get_db()
    me = uid()
    to = int((request.get_json(silent=True) or {}).get("to_uid") or 0)
    if not to or to == me:
        return jsonify({"error": "请选择要组队的账号"}), 400
    if not db.execute("SELECT 1 FROM users WHERE id=?", (to,)).fetchone():
        return jsonify({"error": "账号不存在"}), 404
    if _my_team(db):
        return jsonify({"error": "你已经在一个队里了，先解散才能重新组队"}), 400
    if _my_team(db, to):
        return jsonify({"error": "对方已经组队了"}), 400
    dup = db.execute("SELECT 1 FROM team_requests WHERE kind='join' AND status='pending' "
                     "AND ((from_uid=? AND to_uid=?) OR (from_uid=? AND to_uid=?))",
                     (me, to, to, me)).fetchone()
    if dup:
        return jsonify({"error": "已经有一条待处理的组队申请了"}), 400
    db.execute("INSERT INTO team_requests(from_uid,to_uid,kind) VALUES(?,?,'join')", (me, to))
    db.commit()
    _bump_sync()
    return jsonify({"ok": True}), 201


@app.post("/api/team/request/<int:rid>/accept")
def team_accept(rid):
    db = get_db()
    me = uid()
    r = db.execute("SELECT * FROM team_requests WHERE id=? AND status='pending'", (rid,)).fetchone()
    if not r or r["to_uid"] != me:
        return jsonify({"error": "申请不存在或无权处理"}), 404
    if r["kind"] == "join":
        if _my_team(db) or _my_team(db, r["from_uid"]):
            db.execute("UPDATE team_requests SET status='rejected' WHERE id=?", (rid,))
            db.commit()
            return jsonify({"error": "你或对方已在其它队里，无法组队"}), 400
        tid = db.execute("INSERT INTO teams DEFAULT VALUES").lastrowid
        db.execute("INSERT INTO team_members(team_id,user_id) VALUES(?,?)", (tid, r["from_uid"]))
        db.execute("INSERT INTO team_members(team_id,user_id) VALUES(?,?)", (tid, me))
        db.execute("UPDATE team_requests SET status='accepted' WHERE id=?", (rid,))
        # 组队成功：把双方今天的规划同步进这个队的互监待办
        today = datetime.now().strftime("%Y-%m-%d")
        for u in (r["from_uid"], me):
            for p in db.execute("SELECT title, minutes FROM plan_items WHERE user_id=? AND date=? ORDER BY seq, id",
                                (u, today)):
                txt = (p["title"] or "").strip()
                if p["minutes"]:
                    txt += "（%d 分钟）" % p["minutes"]
                db.execute("INSERT INTO shared_todos(text,created_by,source,src_uid,plan_date,team_id) "
                           "VALUES(?,?,'plan',?,?,?)", (txt[:200], uname(db, u), u, today, tid))
        db.commit()
        _bump_sync()
        return jsonify({"ok": True, "team_id": tid})
    else:  # disband
        tid = r["team_id"]
        _disband_team(db, tid)
        db.execute("UPDATE team_requests SET status='accepted' WHERE id=?", (rid,))
        db.commit()
        _bump_sync()
        return jsonify({"ok": True, "disbanded": True})


@app.post("/api/team/request/<int:rid>/reject")
def team_reject(rid):
    db = get_db()
    r = db.execute("SELECT * FROM team_requests WHERE id=? AND status='pending'", (rid,)).fetchone()
    if not r or r["to_uid"] != uid():
        return jsonify({"error": "申请不存在或无权处理"}), 404
    db.execute("UPDATE team_requests SET status='rejected' WHERE id=?", (rid,))
    db.commit()
    _bump_sync()
    return jsonify({"ok": True})


@app.post("/api/team/request/<int:rid>/cancel")
def team_cancel(rid):
    db = get_db()
    r = db.execute("SELECT * FROM team_requests WHERE id=? AND status='pending'", (rid,)).fetchone()
    if not r or r["from_uid"] != uid():
        return jsonify({"error": "申请不存在或无权撤回"}), 404
    db.execute("UPDATE team_requests SET status='cancelled' WHERE id=?", (rid,))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/team/disband")
def team_disband_request():
    """发解散申请给搭档，对方同意才真正解散。"""
    db = get_db()
    me = uid()
    team = _my_team(db)
    if not team:
        return jsonify({"error": "你还没组队"}), 400
    partner = next((m["id"] for m in _team_members(db, team) if m["id"] != me), None)
    if not partner:
        _disband_team(db, team)          # 队里只剩自己，直接散
        db.commit()
        _bump_sync()
        return jsonify({"ok": True, "disbanded": True})
    if db.execute("SELECT 1 FROM team_requests WHERE kind='disband' AND status='pending' AND team_id=?",
                  (team,)).fetchone():
        return jsonify({"error": "已经发过解散申请了，等对方处理"}), 400
    db.execute("INSERT INTO team_requests(from_uid,to_uid,kind,team_id) VALUES(?,?,'disband',?)",
               (me, partner, team))
    db.commit()
    _bump_sync()
    return jsonify({"ok": True})


def _disband_team(db, team_id):
    """真正解散：清掉这个队的成员、共享待办、以及相关的待处理申请。"""
    ids = [r[0] for r in db.execute("SELECT id FROM shared_todos WHERE team_id=?", (team_id,))]
    if ids:
        qs = ",".join("?" * len(ids))
        db.execute("DELETE FROM shared_todo_done WHERE todo_id IN (%s)" % qs, ids)
        db.execute("DELETE FROM shared_todos WHERE team_id=?", (team_id,))
    db.execute("UPDATE team_requests SET status='cancelled' WHERE team_id=? AND status='pending'", (team_id,))
    db.execute("DELETE FROM team_members WHERE team_id=?", (team_id,))
    db.execute("DELETE FROM teams WHERE id=?", (team_id,))


# ---------------------------------------------------------------- 每日任务
# 已拆到 mods/tasks.py。

# ---------------------------------------------------------------- 申论（四大题型讲义 + AI 逐点批改）
# 已拆到 mods/shenlun.py。

# ---------------------------------------------------------------- 范文推荐（仿真卷 + 全套参考答案）
# 已拆到 mods/essays.py。

# ---------------------------------------------------------------- 文档识题：抽出例题 → AI 解答 → 回填成副本
# 有「（　）」「A．」「下列…正确的是」这类特征的页面才值得送去问 AI，省一大笔调用
_Q_HINT = re.compile(
    r"[（(]\s{0,6}[）)]|[ABCD]\s*[．.、]|下列|以下|不属于|正确的是|错误的是|"
    r"填入划?横线|依次填入|最恰当的|最合适的?|说法正确|说法错误|"
    # 图形推理 / 类比 / 定义判断这类题干，往往没有 A. B. 文本选项，靠这些提法识别
    r"呈现\s*一?\s*定\s*的?\s*规律|规律性|从所给|所给的?\s*[四4]\s*个选项|填入问号|问号处|"
    r"分为两类|每一类|类比推理|与之?相?对应|关系最为?相似|恰当的一项|符合的一项|"
    r"\(\s*20\d\d[^)]{0,6}(?:国考|省考|联考|事业单位|吉林|广东|安徽|甘肃|江苏|浙江)")


def _page_text(pdf, n):
    try:
        out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-f", str(n), "-l", str(n), pdf, "-"],
                             capture_output=True, timeout=60)
        return out.stdout.decode("utf-8", "ignore")
    except Exception:
        return ""


def _pdf_pages(pdf):
    try:
        out = subprocess.run(["pdfinfo", pdf], capture_output=True, timeout=60)
        return int(re.search(r"Pages:\s+(\d+)", out.stdout.decode("utf-8", "ignore")).group(1))
    except Exception:
        return 0


DOCQA_SYS = ("你是公考各科目的资深讲师。只处理文档里真实存在的例题，绝不虚构题目；"
             "答案要有把握，解析要讲清怎么想、为什么排除其他选项。严格输出 JSON。")


_DOCQA_RULES = (
    "对每一道题：\n"
    "· 若原文已给出答案，answer 用原文答案，并补写解析；\n"
    "· 若原文没有答案（常见），请你作答给出正确答案与解析；\n"
    "· stem 写清题干（可精简断行，不要改意思）；options 按原文照抄，没有文字选项就给空数组；\n"
    "· qtype 写题目所属模块，如「言语理解-逻辑填空」「判断推理-图形推理」「常识判断-法律」。\n"
    "文档里没有题目就返回空数组，不要编造。\n"
    '只输出 JSON：{"items":[{"page":12,"stem":"","options":["A. …"],"answer":"B","explain":"","qtype":""}]}')


def _ask_questions(chunk, page_images=None):
    """chunk = [(页码, 该页文字)]。配了视觉模型就看图作答（图形推理靠它），否则退纯文字。"""
    body = "\n\n".join("【第 %d 页】\n%s" % (p, t[:3500]) for p, t in chunk)

    # 有视觉模型 + 页面图 → 让它真的「看图做题」，图形推理/图表题才有救
    if vision_configured() and page_images:
        imgs = [page_images[p] for p, _ in chunk if page_images.get(p)]
        if imgs:
            vprompt = (
                "下面每张图片是一份公考讲义的一页（按页码顺序），另附从图片里抽取的文字（可能有错字）。\n"
                "请**看着图片**找出其中的【例题】并作答，尤其是图形推理 / 类比推理 / 图表题——"
                "直接根据图形本身选出正确选项，并在 explain 里讲清规律（遍历/样式/位置/数量等）。\n"
                "普通带 A/B/C/D 的文字题也要收进来。\n" + _DOCQA_RULES + "\n\n【各页文字】\n" + body)
            try:
                rep = vision_chat(vprompt, imgs, prefer="pro", temperature=0.2,
                                  max_tokens=4000, timeout=200, json_mode=True)
                return json.loads(rep).get("items", []) or []
            except Exception:   # 视觉失败 → 退回纯文字，别让整批崩掉
                log.warning("docqa 视觉识别失败，退回纯文字出题", exc_info=True)

    prompt = (
        "下面是一份公考讲义/资料中连续几页的文字（OCR 或 PDF 抽取，可能有断行和错字）。\n"
        "请找出其中的【例题】——有题干，通常带 A/B/C/D 选项，或是填空/判断/图形/类比题。\n"
        "注意：图形推理、类比推理、部分定义判断题的选项是图片，文字里可能看不到 A/B/C/D，"
        "但只要有「从所给的四个选项中…」「使之呈现一定的规律性」「分为两类」这类题干，也算一道题，要收进来。\n"
        "· 若这是你熟悉的历年真题（题干里常标有年份和省份，如「2020国考」），"
        "请依据该真题的公认答案作答，answer 直接给字母，explain 讲清规律。\n"
        "· 若这是图形/图片类题目、文字里没有图形信息、你也不能确定题源答案，"
        "answer 填「见原图」，explain 给出该题型的解题思路，绝不要瞎猜一个字母，也不要只写「无法判断」。\n"
        + _DOCQA_RULES + "\n\n" + body)
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": DOCQA_SYS}, {"role": "user", "content": prompt}],
        temperature=0.2, max_tokens=6000, timeout=300, json_mode=True)
    if err:
        return []
    try:
        return json.loads(rep).get("items", []) or []
    except Exception:
        return []


def _ans_pdf(out_path, page_no, items):
    """给某一页生成配套的「答案解析」页，插在原页之后。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    font = ensure_pdf_font()
    doc = SimpleDocTemplate(out_path, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title="第%d页 答案解析" % page_no)
    h = ParagraphStyle("h", fontName=font, fontSize=13, leading=19, spaceAfter=8,
                       textColor=colors.HexColor("#1a6fb5"))
    lab = ParagraphStyle("lab", fontName=font, fontSize=10.5, leading=17, spaceAfter=3,
                         textColor=colors.HexColor("#6b7280"))
    body = ParagraphStyle("b", fontName=font, fontSize=11, leading=18, spaceAfter=6)
    ans = ParagraphStyle("a", fontName=font, fontSize=11.5, leading=18, spaceAfter=4,
                         textColor=colors.HexColor("#12813f"))

    def esc(t):
        return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    flow = [Paragraph("第 %d 页 · 答案与解析（AI 生成）" % page_no, h)]
    for i, it in enumerate(items, 1):
        flow.append(Paragraph("%d. %s" % (i, esc(it.get("stem", ""))[:400]), body))
        for o in (it.get("options") or [])[:6]:
            flow.append(Paragraph(esc(o)[:200], lab))
        flow.append(Paragraph("【答案】%s" % esc(it.get("answer", "")), ans))
        flow.append(Paragraph("【解析】%s" % esc(it.get("explain", "")), body))
        if it.get("qtype"):
            flow.append(Paragraph("【模块】%s" % esc(it["qtype"]), lab))
        flow.append(Spacer(1, 6))
    doc.build(flow)
    return out_path


def _merge_interleaved(src, page_ans, out):
    """qpdf 按 原页1, 解析页1, 原页2, … 的顺序拼成副本，原版式一页不动。"""
    args = ["qpdf", "--empty", "--pages"]
    total = _pdf_pages(src)
    for p in range(1, total + 1):
        args += [src, str(p)]
        if p in page_ans:
            args += [page_ans[p], "1-z"]
    args += ["--", out]
    subprocess.run(args, check=True, timeout=600, capture_output=True)
    return out


DOCQA_MAX_PAGES = int(os.environ.get("GONGKAO_DOCQA_MAX_PAGES", "80"))
# 多份讲义同时上传时排队处理：一次只跑一份，别同时挤爆视觉接口（429）
_docqa_gate = threading.Semaphore(1)


def _docqa_run(tid, user_id, mid, orig_name, board):
    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    tmpdir = tempfile.mkdtemp(prefix="docqa_")
    bg_set(con, tid, message="排队中…")
    _docqa_gate.acquire()          # 前面还有讲义在解就排队等
    try:
        m = con.execute("SELECT * FROM materials WHERE id=?", (mid,)).fetchone()
        path = os.path.join(UPLOADS, str(user_id), m["stored_name"])
        pdf = path if m["ext"] == ".pdf" else _office_to_pdf(path)
        if not pdf or not os.path.exists(pdf):
            raise RuntimeError("这个格式转不成 PDF，暂时只支持 PDF / Word / PPT")

        total = _pdf_pages(pdf)
        if not total:
            raise RuntimeError("读不出页数")
        scan = min(total, DOCQA_MAX_PAGES)
        bg_set(con, tid, total=scan, message="正在读取文字…")

        # 先本地筛出「像有题目」的页，只把这些页送去问 AI
        texts, cand = {}, []
        for p in range(1, scan + 1):
            t = _page_text(pdf, p)
            if len(re.sub(r"\s", "", t)) < 20:      # 扫描件：这一页没有文字层
                t = _ocr_image_page(pdf, p, tmpdir)
            t = _strip_artifacts(t)                 # 去掉页眉页脚 / 水印，别干扰识题
            texts[p] = t
            if _Q_HINT.search(t):
                cand.append(p)
            bg_set(con, tid, progress=p, message="读取第 %d/%d 页" % (p, scan))
        if not cand:
            raise RuntimeError("没在文档里找到像题目的内容（前 %d 页）" % scan)

        # 配了视觉模型：把候选页渲染成图，好让模型「看图做题」（图形推理靠这个）
        page_images = {}
        if vision_configured():
            for p in cand:
                try:
                    page_images[p] = _render_page(pdf, p, tmpdir)
                except Exception:
                    log.debug("第 %s 页渲染失败，这页不进 vision", p, exc_info=True)

        bg_set(con, tid, progress=0, total=len(cand), message="AI 解题中…")
        found, done = [], 0
        for i in range(0, len(cand), 3):            # 三页一批，省调用
            if i and page_images:
                time.sleep(1.5)                     # 视觉批次间留点间隔，少触发限流(429)
            chunk = [(p, texts[p]) for p in cand[i:i + 3]]
            for it in _ask_questions(chunk, page_images):
                try:
                    it["page"] = int(it.get("page") or chunk[0][0])
                except Exception:
                    it["page"] = chunk[0][0]
                if it.get("stem") and it.get("answer"):
                    found.append(it)
            done = min(len(cand), i + 3)
            bg_set(con, tid, progress=done, message="AI 解题中… 已找到 %d 题" % len(found))
        if not found:
            raise RuntimeError("AI 没能从中识别出可解答的题目")

        # 每页一张解析页，插到原页后面
        by_page = {}
        for it in found:
            by_page.setdefault(it["page"], []).append(it)
        bg_set(con, tid, message="正在生成副本…")
        page_ans = {}
        for p, items in sorted(by_page.items()):
            ap = os.path.join(tmpdir, "ans_%03d.pdf" % p)
            page_ans[p] = _ans_pdf(ap, p, items)

        stored = uuid.uuid4().hex + ".pdf"
        out = os.path.join(_user_dir(user_id), stored)
        _merge_interleaved(pdf, page_ans, out)

        base = os.path.splitext(orig_name)[0]
        title = base + " · 含答案解析"
        cur = con.execute(
            "INSERT INTO materials(user_id,section,board,title,orig_name,stored_name,ext,mime,size) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (user_id, "", board, title, title + ".pdf", stored, ".pdf", "application/pdf",
             os.path.getsize(out)))
        new_mid = cur.lastrowid
        for seq, it in enumerate(found, 1):
            con.execute("INSERT INTO doc_questions(task_id,page,seq,stem,options,answer,explain,qtype) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (tid, it["page"], seq, it.get("stem", ""),
                         json.dumps(it.get("options") or [], ensure_ascii=False),
                         it.get("answer", ""), it.get("explain", ""), it.get("qtype", "")))
        bg_set(con, tid, status="done", result_id=new_mid, progress=len(cand),
                message="识别 %d 道题，已生成副本" % len(found),
                extra=json.dumps({"src_mid": mid, "out_mid": new_mid, "n": len(found)}))
        con.commit()
    except Exception as e:
        try:
            bg_set(con, tid, status="error", message=str(e)[:200])
            # 解析失败就把刚上传的原件也收走，别在资料库里留一堆没用的文件
            row = con.execute("SELECT stored_name FROM materials WHERE id=?", (mid,)).fetchone()
            if row:
                con.execute("DELETE FROM materials WHERE id=?", (mid,))
                con.commit()
                try:
                    os.remove(os.path.join(UPLOADS, str(user_id), row["stored_name"]))
                except Exception:
                    log.debug("删上传文件失败（残留不影响功能）", exc_info=True)
        except Exception:
            log.exception("docqa 后台任务异常退出")
    finally:
        _docqa_gate.release()
        shutil.rmtree(tmpdir, ignore_errors=True)
        con.close()


def _render_page(pdf, p, tmpdir, dpi=150):
    """把 PDF 某页渲染成 PNG，返回图片路径（给视觉模型看图用）。"""
    out = os.path.join(tmpdir, "pg_%d" % p)
    subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-f", str(p), "-l", str(p),
                    "-singlefile", pdf, out], check=True, timeout=180, capture_output=True)
    return out + ".png"


@app.post("/api/docqa/upload")
def docqa_upload():
    """上传讲义 → 后台识题解题 → 生成「含答案解析」副本，原件保留。"""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".pdf",) and ext not in OFFICE_EXT:
        return jsonify({"error": "只支持 PDF / Word / PPT"}), 400
    board = (request.form.get("board") or "").strip()

    stored = uuid.uuid4().hex + ext
    path = os.path.join(_user_dir(uid()), stored)
    f.save(path)
    db = get_db()
    cur = db.execute(
        "INSERT INTO materials(user_id,section,board,title,orig_name,stored_name,ext,mime,size) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (uid(), "", board, f.filename, f.filename, stored, ext, f.mimetype or "",
         os.path.getsize(path)))
    mid = cur.lastrowid
    db.commit()

    tid = bg_new(db, "docqa", f.filename)
    threading.Thread(target=_docqa_run, args=(tid, uid(), mid, f.filename, board), daemon=True).start()
    return jsonify({"task_id": tid, "material_id": mid}), 201


@app.get("/api/docqa/tasks")
def docqa_tasks():
    rows = get_db().execute(
        "SELECT * FROM bg_tasks WHERE user_id=? AND kind='docqa' ORDER BY id DESC LIMIT 30",
        (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.get("/api/docqa/task/<int:tid>")
def docqa_task(tid):
    db = get_db()
    t = db.execute("SELECT * FROM bg_tasks WHERE id=? AND user_id=?", (tid, uid())).fetchone()
    if not t:
        return jsonify({"error": "未找到"}), 404
    d = dict(t)
    d["questions"] = []
    for r in db.execute("SELECT * FROM doc_questions WHERE task_id=? ORDER BY page, seq", (tid,)):
        q = dict(r)
        try:
            q["options"] = json.loads(q["options"] or "[]")
        except Exception:
            q["options"] = []
        d["questions"].append(q)
    try:
        d["extra"] = json.loads(d["extra"] or "{}")
    except Exception:
        d["extra"] = {}
    return jsonify(d)


@app.delete("/api/docqa/task/<int:tid>")
def docqa_task_del(tid):
    db = get_db()
    db.execute("DELETE FROM doc_questions WHERE task_id=?", (tid,))
    db.execute("DELETE FROM bg_tasks WHERE id=? AND user_id=?", (tid, uid()))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 备考规划（AI 按你的真实学习数据排当天计划）
PLAN_EXAMS = ["四川省考", "国考", "事业单位", "其他"]

# 计划条目可以直达 App 里的对应功能，和消息中心用同一套 link 约定
PLAN_LINKS = ["review", "quiz", "changshi", "news", "sucai", "gaikuo",
              "wrongq", "idiom", "changkao", "shenlun", "classics", "theory",
              "essays", "gongwen", "dtest", "drafts", "works", "partydict", "policydoc", ""]

# ---------------------------------------------------------------- 40 天冲刺路线图
# 对标「考公 140 分」的强度贴，但按人能扛住的节奏重排：6 天推进 + 第 7 天复盘日。
# 所有「积累类」任务都落到 App 里现成的模块，不用再去外面找资料。
ROADMAP_40 = {
    "name": "40 天冲刺路线（对标 140 分强度）",
    "days": 40,
    "rhythm": "6 天推进 + 第 7 天复盘日（上午限时套题、下午全套订正归因、晚上错题过筛 + 半天休息）。"
              "不设「全天不休」——连轴转 40 天必塌方，复盘日就是让你能扛完全程的那颗螺丝。",
    "priority": "资料分析 ＞ 言语理解 ＞ 判断推理 ＞ 常识判断(积累型) ＞ 数量关系(战略选做)",
    "priority_why": "资料分析题型固定、练了就稳、分值大，是性价比最高的；数量关系耗时最长、提升最慢，"
                    "只保 10 题左右的会做题，其余果断放弃换时间——140 分不是靠数量关系堆出来的。",
    # 每日固定动作：直接用 App 里已有的内容，不用另外找资料
    "fixed": [
        {"t": "晨读 30 分钟：读「常考」里的高频成语 / 实词 / 上位词", "link": "changkao",
         "note": "起床先背，别碰手机。读 App「常考」里按真题考频排的新词（不是复习你已收录的——那是「今日复习」的活，别重复）"},
        {"t": "碎片时间刷时政（替代刷短视频）", "link": "news",
         "note": "App「每日时政」每天自动更新，通勤/排队/洗漱时看，相当于半月谈每日时政"},
        {"t": "睡前 20 分钟：理论 / 要文 / 习语金句", "link": "theory",
         "note": "App「理论基础」「时政要文库」「习语金句」，睡前过一遍，常识和申论都吃这口"},
        {"t": "错题当天进错题本，绝不过夜", "link": "wrongq",
         "note": "App 错题本会自动判题型、给解析；错因写进「方法/技巧」栏，后面复盘全靠它"},
        {"t": "到期复习（遗忘曲线）", "link": "review",
         "note": "App「今日复习」按艾宾浩斯到期推送，先清它再学新的"},
        {"t": "巩固测试 10~15 题", "link": "dtest",
         "note": "在「任务清单 → 每日任务」里，按当天计划出题（行测五个板块都有），用「测试模式」自测"},
        {"t": "演算用草稿纸 / 草稿本", "link": "drafts",
         "note": "做题时左下角「📝 草稿纸」，平时演算用错题本里的「📓 草稿本」"},
    ],
    # 状态纪律（原贴的「140 分强度」，挑能长期执行的）
    "discipline": [
        "7:30 起 / 23:00 睡，作息固定——熬夜刷题第二天正确率必掉，得不偿失",
        "关掉朋友圈入口、不刷短视频、不看小说游戏；学崩了就去跑步，不是去玩手机",
        "行测每周至少 3 套限时套题，严格按考场时间（上午行测 / 下午申论）",
        "近 5 年真题反复刷（目标 3 遍以上），第二遍起用不同颜色重标难点与模糊点",
        "口诀/公式背到看见题眼就条件反射；资料分析的速算技巧必须形成肌肉记忆",
    ],
    "phases": [
        {
            "key": "P1", "name": "打牢根基", "d0": 1, "d1": 12,
            "focus": "系统课过一遍 + 建立每日积累与错题闭环。这一段不追速度，追「方法对不对、错因说不说得清」。",
            "quota": {"言语理解": 30, "判断推理": 30, "资料分析": 15, "数量关系": 10, "常识判断": 15},
            "shenlun": "每天 1 道小题（归纳概括/提出对策优先），用 App「真题批改」逐点批改，看采分点",
            "accuracy": {"言语理解": "70%", "判断推理": "70%", "资料分析": "80%", "数量关系": "50%", "常识判断": "55%"},
            "weekly": ["第 7 天复盘日：1 套行测限时套题（摸底，别怕分低）+ 全套订正归因"],
            "output": "错题本立起来（每题都有错因）；成语/实词日读不断；申论小题会「按点作答」",
        },
        {
            "key": "P2", "name": "专项拔高", "d0": 13, "d1": 28,
            "focus": "按薄弱模块死磕（App 会用你的错题分布告诉你哪块最弱）。资料分析先拉满，数量关系只练会做的题型。",
            "quota": {"言语理解": 30, "判断推理": 30, "资料分析": 20, "数量关系": 10, "常识判断": 15},
            "shenlun": "每天 2 小时：三天一套真题（小题是重心，分清主次）；每周一篇大作文（背模板 + 攒好词好句）",
            "accuracy": {"言语理解": "78%", "判断推理": "78%", "资料分析": "88%", "数量关系": "60%", "常识判断": "60%"},
            "weekly": ["每周 1~2 套行测限时套题", "错题第二轮：不同颜色重标难点 / 知识模糊点"],
            "output": "薄弱模块正确率追平其他模块；资料分析稳定 85%+；大作文有自己的模板与素材库",
        },
        {
            "key": "P3", "name": "套题强化", "d0": 29, "d1": 40,
            "focus": "进考场状态：上午行测、下午申论、晚上复盘。开始按「整套」训练节奏与取舍，而不是按模块。",
            "quota": {"言语理解": 25, "判断推理": 25, "资料分析": 20, "数量关系": 10, "常识判断": 20},
            "shenlun": "每天 2 小时，小题为重心；三天一篇大作文，掐时间写",
            "accuracy": {"言语理解": "85%", "判断推理": "80%", "资料分析": "90%+", "数量关系": "选做 10 题 ≥60%", "常识判断": "60%+"},
            "weekly": ["每周 3 套行测限时套题（严格 120 分钟，上午做）",
                       "错题本完整过 1 遍；变型多 / 复杂题型重点盯",
                       "时政 + 理论冲刺：要文库、理论基础、习语金句"],
            "output": "行测有稳定的做题顺序与放弃策略；套题成绩进入目标区间；错题不再重复错",
        },
    ],
    "after": "40 天只是把「根基 + 专项」做扎实。之后按原计划推进：9 月套题冲刺（每周 3 套 + 常识时政热点课），"
             "10 月起考前冲刺（严格按考试时间，早上行测、下午申论、晚上复盘，错题再过 3 遍）。"
             "省考在 12 月 7 日，时间够——别在 40 天里把自己榨干。",
}


def _plan_days_left(exam_date):
    if not exam_date:
        return None
    try:
        d = datetime.strptime(exam_date[:10], "%Y-%m-%d").date()
        return (d - datetime.now().date()).days
    except Exception:
        return None


def _plan_stats(db, today):
    """给 AI 的「学情快照」：全部来自真实数据，不让它凭空想象。"""
    st = {}
    due = _review_due(db, uid(), today)
    g = dict.fromkeys(RV_GROUPS, 0)
    for it in due:
        g[RV_GROUP.get(it["kind"], "wrongq")] += 1
    st["review_due"] = len(due)
    st["review_groups"] = g

    st["wrong_by_board"] = {r["board"]: r["c"] for r in db.execute(
        "SELECT COALESCE(NULLIF(board,''),'未分类') board, COUNT(*) c FROM wrong_questions "
        "WHERE user_id=? GROUP BY board ORDER BY c DESC", (uid(),))}

    st["quiz_undone"] = db.execute(
        "SELECT COUNT(*) FROM quiz_sets s WHERE NOT EXISTS("
        " SELECT 1 FROM quiz_answers a JOIN quiz_questions q ON q.id=a.qid "
        " WHERE q.set_id=s.id AND a.user_id=?)", (uid(),)).fetchone()[0]

    st["new_today"] = {
        "常识积累": db.execute("SELECT COUNT(*) FROM changshi_items WHERE date=?", (today,)).fetchone()[0],
        "每日时政": db.execute("SELECT COUNT(*) FROM news_items WHERE date(created_at)=?", (today,)).fetchone()[0],
        "议论文素材": db.execute("SELECT COUNT(*) FROM sucai_items WHERE date=?", (today,)).fetchone()[0],
        "概括句": db.execute("SELECT COUNT(*) FROM gaikuo_items WHERE date=?", (today,)).fetchone()[0],
    }
    st["entries"] = db.execute("SELECT COUNT(*) FROM entries WHERE user_id=?", (uid(),)).fetchone()[0]
    st["daily_tasks"] = [r["text"] for r in db.execute(
        "SELECT text FROM task_templates WHERE user_id=? AND active=1 ORDER BY sort,id", (uid(),))]
    st["graded"] = db.execute("SELECT COUNT(*) FROM shenlun_grade WHERE user_id=?", (uid(),)).fetchone()[0]
    return st


@app.get("/api/plan/profile")
def plan_profile_get():
    r = get_db().execute("SELECT * FROM plan_profile WHERE user_id=?", (uid(),)).fetchone()
    d = dict(r) if r else None
    if d:
        d["days_left"] = _plan_days_left(d.get("exam_date"))
    return jsonify({"profile": d, "exams": PLAN_EXAMS})


@app.post("/api/plan/profile")
def plan_profile_set():
    d = request.get_json(silent=True) or {}
    exam = (d.get("exam") or "").strip() or "四川省考"
    exam_date = (d.get("exam_date") or "").strip()
    try:
        minutes = max(20, min(720, int(d.get("minutes") or 120)))
    except Exception:
        minutes = 120
    db = get_db()
    db.execute("INSERT INTO plan_profile(user_id,exam,exam_date,minutes,weak,note,updated_at) "
               "VALUES(?,?,?,?,?,?,datetime('now','localtime')) "
               "ON CONFLICT(user_id) DO UPDATE SET exam=excluded.exam, exam_date=excluded.exam_date, "
               "minutes=excluded.minutes, weak=excluded.weak, note=excluded.note, "
               "updated_at=excluded.updated_at",
               (uid(), exam, exam_date, minutes,
                (d.get("weak") or "").strip()[:120], (d.get("note") or "").strip()[:200]))
    db.commit()
    return plan_profile_get()


@app.get("/api/plan/today")
def plan_today():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    p = db.execute("SELECT * FROM plan_profile WHERE user_id=?", (uid(),)).fetchone()
    prof = dict(p) if p else None
    if prof:
        prof["days_left"] = _plan_days_left(prof.get("exam_date"))
    rows = db.execute("SELECT * FROM plan_items WHERE user_id=? AND date=? ORDER BY seq, id",
                      (uid(), today)).fetchall()
    items = [dict(r) for r in rows]
    # 重点只属于生成它的那一天，隔天不再显示
    summary = (prof or {}).get("summary") if (prof or {}).get("summary_date") == today else ""
    return jsonify({
        "date": today, "profile": prof, "items": items, "summary": summary or "",
        "done_n": sum(1 for x in items if x["done"]),
        "total": len(items),
        "minutes_total": sum(x["minutes"] or 0 for x in items),
        "minutes_done": sum((x["minutes"] or 0) for x in items if x["done"]),
        "stats": _plan_stats(db, today),
        "study": _study_stats(db, uid()),
        "roadmap": _roadmap_state(db),        # 40 天冲刺：今天第几天、什么阶段、今日定额
    })


def _sync_plan_to_shared(db, date):
    """把我今天的备考规划镜像进「互监待办」，搭档就能交叉打勾监督我完成。
    只镜像当前用户的当天计划；旧的规划条目先清掉，保持同步。没组队就不同步。"""
    me = uid()
    old = [r[0] for r in db.execute(
        "SELECT id FROM shared_todos WHERE source='plan' AND src_uid=?", (me,))]
    if old:
        qs = ",".join("?" * len(old))
        db.execute("DELETE FROM shared_todo_done WHERE todo_id IN (%s)" % qs, old)
        db.execute("DELETE FROM shared_todos WHERE id IN (%s)" % qs, old)
    team = _my_team(db)
    if not team:
        return
    name = current_user()["username"]
    for r in db.execute("SELECT title, minutes FROM plan_items WHERE user_id=? AND date=? ORDER BY seq, id",
                        (me, date)):
        txt = (r["title"] or "").strip()
        if r["minutes"]:
            txt += "（%d 分钟）" % r["minutes"]
        db.execute("INSERT INTO shared_todos(text,created_by,source,src_uid,plan_date,team_id) "
                   "VALUES(?,?,'plan',?,?,?)", (txt[:200], name, me, date, team))


def _plan_snapshot(db, date, note=""):
    """把某天当前的计划存一份进 plan_log（重排/覆盖前调用，避免旧版丢失）。"""
    rows = db.execute("SELECT seq,title,module,minutes,reason,link,source,done FROM plan_items "
                      "WHERE user_id=? AND date=? ORDER BY seq, id", (uid(), date)).fetchall()
    if not rows:
        return
    items = [dict(r) for r in rows]
    prof = db.execute("SELECT summary, summary_date FROM plan_profile WHERE user_id=?", (uid(),)).fetchone()
    summary = (prof["summary"] if prof and prof["summary_date"] == date else "") or note
    db.execute("INSERT INTO plan_log(user_id,date,summary,minutes_total,done_n,total,items_json) "
               "VALUES(?,?,?,?,?,?,?)",
               (uid(), date, summary,
                sum(x["minutes"] or 0 for x in items),
                sum(1 for x in items if x["done"]), len(items),
                json.dumps(items, ensure_ascii=False)))


def _roadmap_state(db):
    """今天在 40 天路线图的第几天、属于哪个阶段、今天的定额是多少。"""
    r = db.execute("SELECT * FROM plan_roadmap WHERE user_id=?", (uid(),)).fetchone()
    if not r:
        return None
    try:
        data = json.loads(r["data_json"] or "{}")
        start = datetime.strptime((r["start_date"] or "")[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    total = r["days"] or 40
    n = (datetime.now().date() - start).days + 1
    phase = None
    if 1 <= n <= total:
        for p in data.get("phases", []):
            if p["d0"] <= n <= p["d1"]:
                phase = p
                break
    return {
        "start_date": r["start_date"], "days": total, "day": n,
        "over": n > total, "not_started": n < 1,
        "phase": phase,
        "review_day": bool(phase) and n % 7 == 0,      # 每 7 天一个复盘日
        "data": data,
    }


@app.get("/api/plan/roadmap")
def roadmap_get():
    return jsonify({"roadmap": _roadmap_state(get_db())})


@app.post("/api/plan/roadmap")
def roadmap_start():
    """开启（或重开）40 天冲刺路线。可顺带把「每天可学时长」一起设好。"""
    d = request.get_json(silent=True) or {}
    db = get_db()
    start = (d.get("start_date") or datetime.now().strftime("%Y-%m-%d"))[:10]
    days = max(7, min(120, int(d.get("days") or ROADMAP_40["days"])))
    db.execute("INSERT INTO plan_roadmap(user_id,start_date,days,data_json) VALUES(?,?,?,?) "
               "ON CONFLICT(user_id) DO UPDATE SET start_date=excluded.start_date, "
               "days=excluded.days, data_json=excluded.data_json, "
               "created_at=datetime('now','localtime')",
               (uid(), start, days, json.dumps(ROADMAP_40, ensure_ascii=False)))
    mins = d.get("minutes")
    if mins:
        db.execute("UPDATE plan_profile SET minutes=? WHERE user_id=?",
                   (max(20, min(720, int(mins))), uid()))
    db.commit()
    return jsonify({"roadmap": _roadmap_state(db)})


@app.delete("/api/plan/roadmap")
def roadmap_stop():
    db = get_db()
    db.execute("DELETE FROM plan_roadmap WHERE user_id=?", (uid(),))
    db.commit()
    return jsonify({"ok": True})


def _roadmap_prompt(rm):
    """把今天在路线图里的位置，翻译成给规划助手看的硬约束。"""
    if not rm or not rm["phase"]:
        return ""
    p, d = rm["phase"], rm["data"]
    quota = "、".join("%s %d 题" % (k, v) for k, v in p["quota"].items())
    acc = "、".join("%s %s" % (k, v) for k, v in p["accuracy"].items())
    lines = [
        "\n【40 天冲刺路线·今天的硬约束】",
        "· 今天是第 %d / %d 天，阶段：%s（%s）" % (rm["day"], rm["days"], p["name"], p["focus"]),
        "· 今日行测定额（必须排进去，可按薄弱模块微调，但总题量别少于八成）：%s" % quota,
        "· 申论：%s" % p["shenlun"],
        "· 本阶段正确率目标（写进 reason 里提醒他）：%s" % acc,
        "· 模块优先级：%s" % d.get("priority", ""),
        "· 每日固定动作（这些也要排成任务）：%s" % "；".join(x["t"] for x in d.get("fixed", [])),
    ]
    lines.append("· link 必须选对地方：晨读/背高频词 → changkao（读「常考」里的新词，"
                 "**不要**和「到期复习」重复，那是 review 的活）；巩固测试 → dtest（在「任务清单·每日任务」里，"
                 "**不是**题库 quiz）；到期复习 → review；错题 → wrongq；刷套卷 → quiz；申论 → shenlun。")
    if rm["review_day"]:
        lines.append("· ★ 今天是【复盘日】：上午一套行测限时套题（严格 120 分钟），下午全套订正 + 错因归因，"
                     "晚上错题过筛 + 看进度分析；把刷新题的量减下来，别再堆新知识。")
    if p.get("weekly"):
        lines.append("· 本阶段每周要做到：%s" % "；".join(p["weekly"]))
    return "\n".join(lines) + "\n"


PLAN_SYS = ("你是公考备考规划师。只根据给出的「学情快照」排计划，不编造学生没有的数据；"
            "任务要具体到可执行（写清做什么、做多少），总时长贴近可用时间。"
            "若给了「40 天冲刺路线」的硬约束，必须照它的定额和优先级排，不得擅自缩水。严格输出 JSON。")


@app.post("/api/plan/generate")
def plan_generate():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    p = db.execute("SELECT * FROM plan_profile WHERE user_id=?", (uid(),)).fetchone()
    if not p:
        return jsonify({"error": "请先填写备考信息（考试、日期、每天可学时长）"}), 400

    days = _plan_days_left(p["exam_date"])
    st = _plan_stats(db, today)
    minutes = p["minutes"] or 120

    phase = "基础打底"
    if days is None:
        phase = "常规推进"
    elif days <= 14:
        phase = "冲刺（以真题、错题、时政为主，少上新知识）"
    elif days <= 45:
        phase = "强化（模块专项 + 套卷训练）"
    elif days <= 120:
        phase = "提高（补短板 + 积累）"

    rm = _roadmap_state(db)
    road = _roadmap_prompt(rm)
    if rm and rm["phase"]:
        phase = "40 天冲刺路线 · 第 %d/%d 天 · %s" % (rm["day"], rm["days"], rm["phase"]["name"])
    # 任务条数跟着可学时长走：6~8 小时就该排 8~11 条，别再固定 4~6 条
    n_task = max(4, min(12, round(minutes / 45)))

    prompt = (
        "【备考信息】\n考试：%s\n距考试：%s\n今天可学习：%d 分钟\n薄弱环节：%s\n备注：%s\n阶段：%s\n\n"
        "【学情快照·今天】\n"
        "· 遗忘曲线到期需复习：%d 条（词语句子 %d / 每日积累 %d / 错题 %d）\n"
        "· 错题分布：%s\n"
        "· 题库里还没做过的套卷：%d 套\n"
        "· 今天新增内容：常识 %d 条、时政 %d 条、议论文素材 %d 条、概括句 %d 条\n"
        "· 已收录成语词语：%d 条；申论批改记录：%d 次\n"
        "· 用户已有的每日固定打卡：%s\n"
        "%s\n"
        "请为今天排一份学习计划：\n"
        "· %d 条左右的任务，总时长控制在 %d 分钟上下（可 ±10%%）；\n"
        "· 到期复习和错题优先安排，其次按模块优先级补薄弱环节，再安排当天新增内容的积累；\n"
        "· 不要和「已有的每日固定打卡」重复；\n"
        "· 每条写清楚做什么、做多少（如「做 30 道图形推理并全部订正，错题进错题本」）；\n"
        "· reason 一句话说明为什么现在做这件事（引用上面的数字或正确率目标）；\n"
        "· link 从这个列表里选一个最相关的，选不出就填空字符串：%s\n"
        "· module 填所属模块（如「言语理解」「常识判断」「申论」「复习」「错题」）。\n"
        '只输出 JSON：{"summary":"一句话today的重点","items":[{"title":"","module":"","minutes":30,"reason":"","link":""}]}'
        % (p["exam"], ("%d 天" % days) if days is not None else "未设置考试日期",
           minutes, p["weak"] or "未填写", p["note"] or "无", phase,
           st["review_due"], st["review_groups"]["word"], st["review_groups"]["daily"],
           st["review_groups"]["wrongq"],
           (", ".join("%s %d 道" % (k, v) for k, v in st["wrong_by_board"].items()) or "暂无错题"),
           st["quiz_undone"],
           st["new_today"]["常识积累"], st["new_today"]["每日时政"],
           st["new_today"]["议论文素材"], st["new_today"]["概括句"],
           st["entries"], st["graded"],
           ("、".join(st["daily_tasks"]) or "无"),
           road, n_task, minutes, "/".join(x for x in PLAN_LINKS if x)))

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": PLAN_SYS}, {"role": "user", "content": prompt}],
        temperature=0.4, max_tokens=2000, timeout=180, json_mode=True)
    if err:
        return err
    try:
        d = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502

    items = [x for x in (d.get("items") or []) if (x.get("title") or "").strip()][:14]
    if not items:
        return jsonify({"error": "AI 没有排出计划，请重试"}), 502

    # 重排会覆盖今天「AI 排的」那部分：先把当前这一版存进历史，别让它丢了
    _plan_snapshot(db, today)
    db.execute("DELETE FROM plan_items WHERE user_id=? AND date=? AND source='ai'", (uid(), today))
    base = db.execute("SELECT COALESCE(MAX(seq),0) FROM plan_items WHERE user_id=? AND date=?",
                      (uid(), today)).fetchone()[0]
    for i, x in enumerate(items, 1):
        link = (x.get("link") or "").strip()
        if link not in PLAN_LINKS:
            link = ""
        try:
            mins = max(5, min(300, int(x.get("minutes") or 20)))
        except Exception:
            mins = 20
        db.execute("INSERT INTO plan_items(user_id,date,seq,title,module,minutes,reason,link,source) "
                   "VALUES(?,?,?,?,?,?,?,?,'ai')",
                   (uid(), today, base + i, (x.get("title") or "").strip()[:120],
                    (x.get("module") or "").strip()[:20], mins,
                    (x.get("reason") or "").strip()[:200], link))
    db.execute("UPDATE plan_profile SET summary=?, summary_date=? WHERE user_id=?",
               ((d.get("summary") or "").strip()[:200], today, uid()))
    _sync_plan_to_shared(db, today)      # 同步进互监待办，方便搭档监督
    db.commit()
    return jsonify(plan_today().get_json())


@app.post("/api/plan/item")
def plan_item_add():
    d = request.get_json(silent=True) or {}
    title = (d.get("title") or "").strip()
    if not title:
        return jsonify({"error": "请输入任务"}), 400
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM plan_items WHERE user_id=? AND date=?",
                     (uid(), today)).fetchone()[0]
    try:
        mins = max(5, min(300, int(d.get("minutes") or 20)))
    except Exception:
        mins = 20
    db.execute("INSERT INTO plan_items(user_id,date,seq,title,module,minutes,reason,link,source) "
               "VALUES(?,?,?,?,?,?,'','','manual')",
               (uid(), today, seq, title[:120], (d.get("module") or "").strip()[:20], mins))
    _sync_plan_to_shared(db, today)
    db.commit()
    return jsonify({"ok": True}), 201


@app.post("/api/plan/<int:pid>/toggle")
def plan_toggle(pid):
    db = get_db()
    r = db.execute("SELECT done FROM plan_items WHERE id=? AND user_id=?", (pid, uid())).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    on = not r["done"]
    db.execute("UPDATE plan_items SET done=?, done_at=CASE WHEN ? THEN datetime('now','localtime') END "
               "WHERE id=?", (1 if on else 0, 1 if on else 0, pid))
    if on:      # 完成一项就算今天学习过了
        _mark_study(db, uid(), datetime.now().strftime("%Y-%m-%d"))
    db.commit()
    return jsonify({"done": on})


@app.delete("/api/plan/<int:pid>")
def plan_del(pid):
    db = get_db()
    db.execute("DELETE FROM plan_items WHERE id=? AND user_id=?", (pid, uid()))
    today = datetime.now().strftime("%Y-%m-%d")
    _sync_plan_to_shared(db, today)
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/plan/restore/<int:log_id>")
def plan_restore(log_id):
    """把历史里的某一版（限当天）恢复成今天的计划；当前这版先存一份进历史。"""
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    r = db.execute("SELECT * FROM plan_log WHERE id=? AND user_id=?", (log_id, uid())).fetchone()
    if not r:
        return jsonify({"error": "未找到该版本"}), 404
    if r["date"] != today:
        return jsonify({"error": "只能恢复今天的版本"}), 400
    try:
        items = json.loads(r["items_json"] or "[]")
    except Exception:
        items = []
    _plan_snapshot(db, today)     # 当前版本也留一份，别覆盖丢了
    db.execute("DELETE FROM plan_items WHERE user_id=? AND date=? AND source='ai'", (uid(), today))
    base = db.execute("SELECT COALESCE(MAX(seq),0) FROM plan_items WHERE user_id=? AND date=?",
                      (uid(), today)).fetchone()[0]
    for i, x in enumerate([it for it in items if it.get("source") != "manual"], 1):
        db.execute("INSERT INTO plan_items(user_id,date,seq,title,module,minutes,reason,link,source,done,done_at) "
                   "VALUES(?,?,?,?,?,?,?,?,'ai',?,CASE WHEN ? THEN datetime('now','localtime') END)",
                   (uid(), today, base + i, (x.get("title") or "")[:120], (x.get("module") or "")[:20],
                    x.get("minutes") or 20, (x.get("reason") or "")[:200], x.get("link") or "",
                    1 if x.get("done") else 0, 1 if x.get("done") else 0))
    if r["summary"]:
        db.execute("UPDATE plan_profile SET summary=?, summary_date=? WHERE user_id=?",
                   (r["summary"].replace("【找回】", ""), today, uid()))
    _sync_plan_to_shared(db, today)
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 每日巩固测试（按当天学的内容出小测）
# 巩固测试的模块配额：行测五个板块都要有，不能只出常识
DTEST_QUOTA = {
    10: {"言语理解": 3, "判断推理": 2, "资料分析": 1, "数量关系": 1, "常识判断": 3},
    15: {"言语理解": 4, "判断推理": 3, "资料分析": 2, "数量关系": 2, "常识判断": 4},
}

# 图形推理 / 资料分析的程序化出题已抽到 figgen.py（题库·模拟卷也要用，见 gen_quiz.py）
from figgen import _gen_figure_q, _gen_ziliao  # noqa: E402

def _dtest_material(db, today):
    """凑出可考素材，按板块分开给：常识/时政（常识判断）、成语实词上位词（言语理解）、我的错题（出变式题）。"""
    m = {"常识": [], "言语": [], "错题": []}
    cs = db.execute("SELECT board, COALESCE(NULLIF(title,''),topic) t, content FROM changshi_items "
                    "WHERE date=? LIMIT 12", (today,)).fetchall()
    if len(cs) < 4:
        cs = db.execute("SELECT board, COALESCE(NULLIF(title,''),topic) t, content FROM changshi_items "
                        "WHERE date>=date('now','localtime','-3 day') ORDER BY date DESC LIMIT 12").fetchall()
    for r in cs:
        m["常识"].append("【常识·%s】%s：%s" % (r["board"] or "", r["t"] or "", (r["content"] or "")[:110]))
    nw = db.execute("SELECT title, ai_summary FROM news_items "
                    "WHERE date(created_at)>=date('now','localtime','-3 day') ORDER BY id DESC LIMIT 8").fetchall()
    for r in nw:
        m["常识"].append("【时政】%s：%s" % (r["title"] or "", (r["ai_summary"] or "")[:110]))
    for r in db.execute("SELECT title, content FROM theory_items ORDER BY RANDOM() LIMIT 4"):
        m["常识"].append("【理论】%s：%s" % (r["title"] or "", (r["content"] or "")[:90]))
    # 言语：我收录的成语词语 + 常考里的高频成语/实词/上位词
    for r in db.execute("SELECT word, explanation FROM entries WHERE user_id=? ORDER BY RANDOM() LIMIT 8", (uid(),)):
        m["言语"].append("【成语/词语】%s：%s" % (r["word"] or "", (r["explanation"] or "")[:90]))
    for r in db.execute("SELECT board, title, content FROM changkao_items "
                        "WHERE board IN ('成语','实词','上位词') ORDER BY RANDOM() LIMIT 10"):
        m["言语"].append("【常考·%s】%s：%s" % (r["board"] or "", r["title"] or "", (r["content"] or "")[:90]))
    # 错题：按板块给，出「同考点变式题」最有价值
    for r in db.execute("SELECT board, qtype, question, points FROM wrong_questions "
                        "WHERE user_id=? ORDER BY id DESC LIMIT 8", (uid(),)):
        m["错题"].append("【错题·%s】%s｜考点：%s" % (r["board"] or r["qtype"] or "", (r["question"] or "")[:80],
                                              (r["points"] or "")[:50]))
    return m


DTEST_ORDER = ["言语理解", "判断推理", "资料分析", "数量关系", "常识判断"]


def _gen_dtest(db, today, n=10):
    n = 15 if int(n) >= 15 else 10          # 题量只支持 10 / 15
    m = _dtest_material(db, today)
    quota = dict(DTEST_QUOTA[n])
    if not m["常识"] and not m["言语"]:
        return None, "还没积累够可测的内容（常识/时政/成语等），先学一会儿再来测～"

    # 图形推理、资料分析都由代码出：答案是构造出来的，必然正确，材料也一定在
    figs = [_gen_figure_q() for _ in range(1 if quota["判断推理"] >= 2 else 0)]
    quota["判断推理"] -= len(figs)
    zl = _gen_ziliao(quota["资料分析"]) if quota["资料分析"] else []
    quota["资料分析"] = 0

    mat = ""
    for k, title in (("常识", "常识 / 时政 / 理论素材（出常识判断题用）"),
                     ("言语", "成语 / 实词 / 上位词素材（出言语理解题用）"),
                     ("错题", "他最近做错的题（优先出同考点的变式题）")):
        if m[k]:
            mat += "\n【%s】\n" % title + "\n".join("· " + x for x in m[k][:14]) + "\n"

    n_ai = n - len(figs) - len(zl)          # 图形题/资料分析已由程序出好，AI 只出剩下的
    prompt = (
        "给一名四川省考考生出一份「每日巩固小测」的一部分：正好 %d 道**单选题**，"
        "**严格按这个配额出，不要多出、不要凑数**：%s。\n\n"
        "每个板块怎么出：\n"
        "· 常识判断：只能考下面给的常识/时政/理论素材里的考点。\n"
        "· 言语理解：用下面给的成语/实词/上位词，出**逻辑填空**（题干要有完整语境，四个近义词选项）"
        "或**语句衔接/病句**，考的是辨析而不是背释义。\n"
        "· 判断推理：出**纯文字**题型——类比推理 / 定义判断 / 逻辑判断（翻译推理、削弱加强）。"
        "图形推理已经由程序另外出好了，你**不要**出图形推理。\n"
        "· 资料分析：已由程序另外出好（带真表格 / 图表），你**不要**出资料分析题。\n"
        "· 数量关系：出工程 / 行程 / 利润 / 排列组合 / 容斥这类经典计算题。\n"
        "· **计算题必须自查一遍**：把数字设计成能算出**干净答案**的（整数或标准百分数）；"
        "正确选项要明显唯一，不能出现两个选项都「约等于」结果的情况；"
        "如果结果不是整数，题干要问「约为多少」并保证正确项明显最接近；工程/人数这类必须是整数的，题目就设计成整除。\n"
        "· 如果给了「他做错的题」，优先出**同考点的变式题**（换个数据/换个情境，考同一个知识点）。\n\n"
        "每题字段：q 题干；options 四个选项（形如 \"A. …\"）；answer 正确选项字母；"
        "explain 一句话解析（讲清为什么，别只说答案）；module 板块名（必须是 言语理解/判断推理/资料分析/数量关系/常识判断 之一）；"
        "source 这题考什么（如「时政-乡村振兴」「成语-抑扬顿挫」「错题变式-资料分析比重」）。\n"
        '只输出 JSON：{"items":[{"q":"","options":["A. …","B. …","C. …","D. …"],"answer":"A",'
        '"explain":"","module":"","source":""}]}\n'
        % (n_ai, "、".join("%s %d 题" % (k, v) for k, v in quota.items() if v)) + mat)

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是四川省考命题老师。按要求的板块配额出单选题，"
                                       "答案唯一且经得起推敲，计算题的数字必须算得出来。严格输出 JSON。"},
         {"role": "user", "content": prompt}], temperature=0.5, max_tokens=6000, timeout=240, json_mode=True)
    if err:
        return None, "AI 出题失败，请稍后再试"
    try:
        items = [x for x in (json.loads(rep).get("items") or [])
                 if x.get("q") and (x.get("options") or []) and x.get("answer")]
    except Exception:
        return None, "AI 返回格式异常，请重试"
    if not items:
        return None, "没能出出题目，请重试"

    for it in items:                                  # 材料数据不干净就退回纯文字题干，别渲染出个空图
        if not _dtest_ok_material(it.get("material")):
            it.pop("material", None)

    seen, uniq = set(), []
    for it in items:                                  # AI 偶尔会重复出同一道题，去掉
        k = (it.get("q") or "").strip()[:40]
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)
    items = uniq[:n_ai] + figs + zl
    items.sort(key=lambda x: DTEST_ORDER.index(x.get("module")) if x.get("module") in DTEST_ORDER else 99)
    db.execute("INSERT OR REPLACE INTO daily_quiz(user_id,date,questions_json) VALUES(?,?,?)",
               (uid(), today, json.dumps(items, ensure_ascii=False)))
    db.commit()
    return items, None


def _dtest_ok_material(m):
    """资料分析的材料必须是干净的结构化数据，数字得真是数字。"""
    if not isinstance(m, dict):
        return False
    t = m.get("type")
    if t == "table":
        rows = m.get("rows") or []
        return bool(m.get("headers")) and rows and all(isinstance(r, list) and r for r in rows)
    if t in ("bar", "line", "pie"):
        labels, series = m.get("labels") or [], m.get("series") or []
        if not labels or not series:
            return False
        for s in series:
            data = s.get("data") or []
            if len(data) != len(labels) or not all(isinstance(v, (int, float)) for v in data):
                return False
        return True
    return False


def _dtest_public(items, exam):
    """服务端判分模式(exam)下，发到前端的题目去掉答案与解析，交卷才由服务端判（板块标签保留）。"""
    if not exam:
        return items
    out = []
    for it in items:
        x = {"q": it.get("q", ""), "options": it.get("options") or [], "module": it.get("module", "")}
        if it.get("material"):
            x["material"] = it["material"]        # 资料分析的表格/图表要看得见
        if it.get("figs"):
            x["figs"] = it["figs"]                # 图形推理的图要看得见
        out.append(x)
    return out


@app.get("/api/dtest")
def dtest_get():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    exam = request.args.get("exam") in ("1", "true")
    r = db.execute("SELECT questions_json FROM daily_quiz WHERE user_id=? AND date=?", (uid(), today)).fetchone()
    items = json.loads(r["questions_json"]) if r else []
    return jsonify({"date": today, "items": _dtest_public(items, exam), "has": bool(items), "exam": exam})


@app.post("/api/dtest")
def dtest_gen():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    d = request.get_json(silent=True) or {}
    force = bool(d.get("force"))
    exam = bool(d.get("exam"))
    count = 15 if int(d.get("count") or 10) >= 15 else 10
    if not force:
        r = db.execute("SELECT questions_json FROM daily_quiz WHERE user_id=? AND date=?", (uid(), today)).fetchone()
        if r:
            return jsonify({"date": today, "items": _dtest_public(json.loads(r["questions_json"]), exam),
                            "cached": True, "exam": exam})
    items, err = _gen_dtest(db, today, count)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"date": today, "items": _dtest_public(items, exam), "exam": exam})


@app.post("/api/dtest/grade")
def dtest_grade():
    """判分并记录：收到 {answers:{题号:字母}}，对照缓存的正确答案判分、存一条记录并回传结果。"""
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    r = db.execute("SELECT questions_json FROM daily_quiz WHERE user_id=? AND date=?", (uid(), today)).fetchone()
    if not r:
        return jsonify({"error": "今天还没有测试"}), 400
    items = json.loads(r["questions_json"])
    ans = (request.get_json(silent=True) or {}).get("answers") or {}
    results, score, detail = [], 0, []
    for i, it in enumerate(items):
        your = (str(ans.get(str(i), ans.get(i, ""))) or "").strip().upper()
        correct_letter = (it.get("answer") or "").strip().upper()
        ok = bool(your) and your == correct_letter
        if ok:
            score += 1
        res = {"your": your, "answer": correct_letter, "correct": ok,
               "explain": it.get("explain", ""), "source": it.get("source", "")}
        results.append(res)
        detail.append({"q": it.get("q", ""), "options": it.get("options") or [], **res})
    db.execute("INSERT INTO dtest_records(user_id,date,score,total,detail_json) VALUES(?,?,?,?,?)",
               (uid(), today, score, len(items), json.dumps(detail, ensure_ascii=False)))
    _dtest_to_wrongq(db, items, results)      # 做错的自动收进错题本
    db.commit()
    return jsonify({"score": score, "total": len(items), "results": results})


@app.post("/api/dtest/wrong")
def dtest_wrong():
    """背题模式（做一题看一题答案）里选错了，也要进错题本。"""
    d = request.get_json(silent=True) or {}
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    r = db.execute("SELECT questions_json FROM daily_quiz WHERE user_id=? AND date=?", (uid(), today)).fetchone()
    if not r:
        return jsonify({"ok": False})
    items = json.loads(r["questions_json"])
    try:
        i = int(d.get("idx"))
        it = items[i]
    except Exception:
        return jsonify({"ok": False})
    your = (str(d.get("choice") or "")).strip().upper()
    ans = (it.get("answer") or "").strip().upper()
    if not your or your == ans:
        return jsonify({"ok": True, "added": 0})
    n = _dtest_to_wrongq(db, [it], [{"your": your, "answer": ans, "correct": False}])
    db.commit()
    return jsonify({"ok": True, "added": n})


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


def _truthy(v, default=True):
    if v is None:
        return default
    return str(v).lower() not in ("0", "false", "no", "")


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
