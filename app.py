#!/usr/bin/env python3
"""公考助手 —— 后端服务（多用户）

- 行测 / 申论 两大板块，下设若干小板块
- 言语理解与表达：成语/词语积累（拼音+释义+PDF 导出）
- 每个板块：资料库（上传图片/文档/网页，应用内直接查看，Office 自动转 PDF）
- 多用户 + 密保问题找回密码 + 管理员后台
"""
import io
import json
import os
import re
import secrets
import sqlite3
import subprocess
import tempfile
import time
import uuid
from datetime import datetime

from flask import (Flask, g, jsonify, redirect, request, session,
                   send_file, send_from_directory, Response)
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

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
STATIC = os.path.join(BASE, "static")
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))
CONFIG = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 单文件最大 64MB

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

# 文件查看
INLINE_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
              ".bmp", ".txt", ".md", ".html", ".htm", ".csv", ".json"}
OFFICE_EXT = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
              ".odt", ".ods", ".odp", ".rtf"}
TEXT_EXT = {".txt", ".md", ".csv", ".json"}


# ---------------------------------------------------------------- 配置（仅密钥）
def load_secret():
    cfg = {}
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    if not cfg.get("secret_key"):
        cfg["secret_key"] = secrets.token_hex(32)
        try:
            with open(CONFIG, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return cfg


CFG = load_secret()
app.secret_key = CFG["secret_key"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
    SEND_FILE_MAX_AGE_DEFAULT=0,  # 静态文件不长期缓存，浏览器每次校验，避免旧样式
)

_login_fails = {}  # username -> {count, locked_until}


# ---------------------------------------------------------------- 数据库
def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DB)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def _cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}


def init_db():
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            sec_question TEXT,
            sec_answer_hash TEXT,
            email TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS entries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            word TEXT NOT NULL, pinyin TEXT, category TEXT,
            explanation TEXT, derivation TEXT, example TEXT,
            note TEXT, source TEXT, starred INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS materials(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            section TEXT, board TEXT,
            title TEXT, orig_name TEXT, stored_name TEXT,
            ext TEXT, mime TEXT, size INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_mat_user ON materials(user_id, board);
        CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            board TEXT,
            content TEXT,
            images TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, board);
        """
    )
    # entries 老表可能缺 user_id 列（先补列，再建索引）
    if "user_id" not in _cols(con, "entries"):
        con.execute("ALTER TABLE entries ADD COLUMN user_id INTEGER")
    con.execute("CREATE INDEX IF NOT EXISTS idx_entries_user ON entries(user_id)")
    # notes 表补充字段：标签 / 附件 / 待办清单
    for col in ("tags", "attachments", "todos"):
        if col not in _cols(con, "notes"):
            con.execute(f"ALTER TABLE notes ADD COLUMN {col} TEXT")

    # 迁移：把旧的单账号(config.json)迁入 users 表，并把无主收录归给它
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        old = {}
        if os.path.exists(CONFIG):
            try:
                old = json.load(open(CONFIG, encoding="utf-8"))
            except Exception:
                old = {}
        if old.get("registered") and old.get("username") and old.get("password_hash"):
            con.execute(
                "INSERT INTO users(username,password_hash,role,email) VALUES(?,?,?,?)",
                (old["username"], old["password_hash"], "admin", old.get("email", "")),
            )
            uid = con.execute("SELECT id FROM users WHERE username=?",
                              (old["username"],)).fetchone()[0]
            con.execute("UPDATE entries SET user_id=? WHERE user_id IS NULL", (uid,))
    con.commit()
    con.close()


def users_count():
    return get_db().execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def uid():
    return session.get("user_id")


def is_admin():
    return session.get("role") == "admin"


# ---------------------------------------------------------------- 访问控制
_PUBLIC_EXACT = {"/register", "/api/register", "/login", "/api/login",
                 "/forgot", "/api/forgot/question", "/api/forgot/reset",
                 "/api/sec_questions",
                 "/apk", "/download/gongkao.apk",
                 "/style.css", "/manifest.webmanifest", "/sw.js", "/favicon.ico"}


def _is_public(path):
    return path in _PUBLIC_EXACT or path.startswith("/icon-")


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
        pass
    PDF_FONT = "STSong-Light"
    _font_ready = True
    return PDF_FONT


# ---------------------------------------------------------------- 成语/词语工具
CJK_RE = re.compile(r"^[一-鿿]+$")


def to_pinyin(word):
    try:
        parts = _pinyin(word, style=Style.TONE, heteronym=False, errors="default")
        return " ".join(p[0] for p in parts)
    except Exception:
        return ""


def lookup(word):
    word = (word or "").strip()
    db = get_db()
    info = {"word": word, "pinyin": "", "category": "词语", "explanation": "",
            "derivation": "", "example": "", "source": "manual", "found": False}
    if not word:
        return info
    row = db.execute("SELECT * FROM ref_idiom WHERE word=?", (word,)).fetchone()
    if row:
        info.update(pinyin=row["pinyin"] or to_pinyin(word), category="成语",
                    explanation=row["explanation"] or "", derivation=row["derivation"] or "",
                    example=row["example"] or "", source="idiom", found=True)
        return info
    row = db.execute("SELECT * FROM ref_ci WHERE word=?", (word,)).fetchone()
    if row:
        info.update(pinyin=to_pinyin(word), category="词语",
                    explanation=row["explanation"] or "", source="ci", found=True)
        return info
    info["pinyin"] = to_pinyin(word)
    if len(word) == 4 and CJK_RE.match(word):
        info["category"] = "成语"
    return info


def row_to_dict(row):
    d = dict(row)
    if "starred" in d:
        d["starred"] = bool(d.get("starred"))
    return d


# ---------------------------------------------------------------- 注册/登录/找回
@app.get("/register")
def register_page():
    return send_from_directory(STATIC, "register.html")


@app.post("/api/register")
def api_register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    pw = data.get("password") or ""
    sec_q = (data.get("sec_question") or "").strip()
    sec_a = (data.get("sec_answer") or "").strip()
    email = (data.get("email") or "").strip()
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
    return jsonify({"username": u["username"], "role": u["role"],
                    "is_admin": u["role"] == "admin", "email": u["email"] or ""})


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
@app.get("/admin")
def admin_page():
    return send_from_directory(STATIC, "admin.html")


@app.get("/api/admin/users")
def admin_users():
    rows = get_db().execute(
        "SELECT id,username,role,email,sec_question,created_at,"
        "(SELECT COUNT(*) FROM entries e WHERE e.user_id=users.id) entry_cnt,"
        "(SELECT COUNT(*) FROM materials m WHERE m.user_id=users.id) mat_cnt "
        "FROM users ORDER BY id").fetchall()
    return jsonify({"users": [dict(r) for r in rows]})


@app.post("/api/admin/users/<int:user_id>/reset")
def admin_reset_pw(user_id):
    db = get_db()
    if not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
        return jsonify({"error": "用户不存在"}), 404
    db.execute("UPDATE users SET password_hash=? WHERE id=?",
               (generate_password_hash("123456"), user_id))
    db.commit()
    return jsonify({"ok": True, "password": "123456"})


@app.post("/api/admin/users/<int:user_id>/role")
def admin_set_role(user_id):
    data = request.get_json(silent=True) or {}
    role = "admin" if data.get("admin") else "user"
    db = get_db()
    if role == "user":  # 不能取消最后一个管理员
        admins = db.execute("SELECT COUNT(*) c FROM users WHERE role='admin'").fetchone()["c"]
        cur = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if cur and cur["role"] == "admin" and admins <= 1:
            return jsonify({"error": "至少保留一个管理员"}), 400
    db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    db.commit()
    return jsonify({"ok": True, "role": role})


@app.post("/api/admin/users/<int:user_id>/secq")
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


@app.delete("/api/admin/users/<int:user_id>")
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


# ---------------------------------------------------------------- 资料库
def _user_dir(user_id):
    d = os.path.join(UPLOADS, str(user_id))
    os.makedirs(d, exist_ok=True)
    return d


def _remove_file(user_id, stored_name):
    try:
        p = os.path.join(UPLOADS, str(user_id), stored_name)
        if os.path.exists(p):
            os.remove(p)
        base = os.path.splitext(p)[0]
        if os.path.exists(base + ".pdf"):  # 缓存的转换结果
            os.remove(base + ".pdf")
    except Exception:
        pass


@app.post("/api/materials")
def material_upload():
    section = (request.form.get("section") or "").strip()
    board = (request.form.get("board") or "").strip()
    title = (request.form.get("title") or "").strip()
    if board and board not in ALL_BOARDS:
        return jsonify({"error": "板块无效"}), 400
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择文件"}), 400
    orig = f.filename
    ext = os.path.splitext(orig)[1].lower()
    stored = uuid.uuid4().hex + ext
    path = os.path.join(_user_dir(uid()), stored)
    f.save(path)
    size = os.path.getsize(path)
    db = get_db()
    cur = db.execute(
        "INSERT INTO materials(user_id,section,board,title,orig_name,stored_name,ext,mime,size) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (uid(), section, board, title or orig, orig, stored, ext, f.mimetype or "", size))
    db.commit()
    row = db.execute("SELECT * FROM materials WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.get("/api/materials")
def material_list():
    board = (request.args.get("board") or "").strip()
    db = get_db()
    sql = "SELECT * FROM materials WHERE user_id=?"
    args = [uid()]
    if board:
        sql += " AND board=?"
        args.append(board)
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["viewable"] = (r["ext"] in INLINE_EXT) or (r["ext"] in OFFICE_EXT)
        out.append(d)
    return jsonify({"items": out})


def _get_material(mid):
    return get_db().execute(
        "SELECT * FROM materials WHERE id=? AND user_id=?", (mid, uid())).fetchone()


def _office_to_pdf(src):
    pdf = os.path.splitext(src)[0] + ".pdf"
    if os.path.exists(pdf) and os.path.getmtime(pdf) >= os.path.getmtime(src):
        return pdf
    prof = "file://" + os.path.join(tempfile.gettempdir(), "lo_profile")
    try:
        subprocess.run(
            ["soffice", "--headless", "-env:UserInstallation=" + prof,
             "--convert-to", "pdf", "--outdir", os.path.dirname(src), src],
            timeout=120, check=True, capture_output=True)
    except Exception:
        return None
    return pdf if os.path.exists(pdf) else None


@app.get("/api/materials/<int:mid>/view")
def material_view(mid):
    m = _get_material(mid)
    if not m:
        return "未找到", 404
    path = os.path.join(UPLOADS, str(uid()), m["stored_name"])
    if not os.path.exists(path):
        return "文件丢失", 404
    ext = m["ext"]
    if ext in OFFICE_EXT:
        pdf = _office_to_pdf(path)
        if not pdf:
            return "文档转换失败，请下载查看", 500
        return send_file(pdf, mimetype="application/pdf", as_attachment=False)
    if ext in (".html", ".htm"):
        with open(path, "rb") as fp:
            return Response(fp.read(), mimetype="text/html; charset=utf-8")
    if ext in TEXT_EXT:
        with open(path, "rb") as fp:
            return Response(fp.read(), mimetype="text/plain; charset=utf-8")
    # pdf / 图片等：浏览器内联打开
    return send_file(path, as_attachment=False,
                     download_name=m["orig_name"])


@app.get("/api/materials/<int:mid>/download")
def material_download(mid):
    m = _get_material(mid)
    if not m:
        return "未找到", 404
    path = os.path.join(UPLOADS, str(uid()), m["stored_name"])
    if not os.path.exists(path):
        return "文件丢失", 404
    return send_file(path, as_attachment=True, download_name=m["orig_name"])


@app.delete("/api/materials/<int:mid>")
def material_delete(mid):
    m = _get_material(mid)
    if not m:
        return jsonify({"error": "未找到"}), 404
    _remove_file(uid(), m["stored_name"])
    get_db().execute("DELETE FROM materials WHERE id=?", (mid,))
    get_db().commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 小记（仿语雀）
NOTE_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def _jl(row, key):
    try:
        return json.loads(row[key] or "[]")
    except Exception:
        return []


def _note_dict(row):
    imgs = _jl(row, "images")
    atts = _jl(row, "attachments")
    return {
        "id": row["id"], "board": row["board"] or "", "content": row["content"] or "",
        "images": ["/api/notes/%d/img/%d" % (row["id"], i) for i in range(len(imgs))],
        "img_files": imgs,
        "attachments": [{"name": a.get("name"), "ext": a.get("ext", ""),
                         "viewable": (a.get("ext") in INLINE_EXT) or (a.get("ext") in OFFICE_EXT),
                         "url": "/api/notes/%d/file/%d" % (row["id"], i)}
                        for i, a in enumerate(atts)],
        "att_files": atts,
        "todos": _jl(row, "todos"),
        "tags": _jl(row, "tags"),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _save_note_images(files):
    names = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in NOTE_IMG_EXT:
            continue
        stored = "note_" + uuid.uuid4().hex + ext
        f.save(os.path.join(_user_dir(uid()), stored))
        names.append(stored)
    return names


def _save_note_atts(files):
    out = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        stored = "natt_" + uuid.uuid4().hex + ext
        f.save(os.path.join(_user_dir(uid()), stored))
        out.append({"file": stored, "name": f.filename, "ext": ext,
                    "size": os.path.getsize(os.path.join(_user_dir(uid()), stored))})
    return out


def _parse_json(s, default):
    try:
        v = json.loads(s)
        return v if v is not None else default
    except Exception:
        return default


def _get_note(nid):
    return get_db().execute("SELECT * FROM notes WHERE id=? AND user_id=?", (nid, uid())).fetchone()


@app.post("/api/notes")
def note_create():
    board = (request.form.get("board") or "").strip()
    content = (request.form.get("content") or "").strip()
    todos = _parse_json(request.form.get("todos"), [])
    tags = _parse_json(request.form.get("tags"), [])
    imgs = _save_note_images(request.files.getlist("images"))
    atts = _save_note_atts(request.files.getlist("attachments"))
    if not (content or imgs or atts or todos):
        return jsonify({"error": "内容不能为空"}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO notes(user_id,board,content,images,attachments,todos,tags) VALUES(?,?,?,?,?,?,?)",
        (uid(), board, content, json.dumps(imgs), json.dumps(atts),
         json.dumps(todos), json.dumps(tags)))
    db.commit()
    return jsonify(_note_dict(db.execute("SELECT * FROM notes WHERE id=?", (cur.lastrowid,)).fetchone())), 201


@app.get("/api/notes")
def note_list():
    board = (request.args.get("board") or "").strip()
    tag = (request.args.get("tag") or "").strip()
    db = get_db()
    sql = "SELECT * FROM notes WHERE user_id=?"
    args = [uid()]
    if board:
        sql += " AND board=?"
        args.append(board)
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, args).fetchall()
    items = [_note_dict(r) for r in rows]
    if tag:
        items = [n for n in items if tag in n["tags"]]
    return jsonify({"items": items})


@app.get("/api/notes/counts")
def note_counts():
    rows = get_db().execute(
        "SELECT board, COUNT(*) c FROM notes WHERE user_id=? GROUP BY board", (uid(),)).fetchall()
    return jsonify({"counts": {(r["board"] or ""): r["c"] for r in rows},
                    "total": sum(r["c"] for r in rows)})


@app.get("/api/notes/tags")
def note_tags():
    board = (request.args.get("board") or "").strip()
    sql = "SELECT tags FROM notes WHERE user_id=?"
    args = [uid()]
    if board:
        sql += " AND board=?"
        args.append(board)
    seen, out = set(), []
    for r in get_db().execute(sql, args).fetchall():
        for t in _jl(r, "tags"):
            if t not in seen:
                seen.add(t)
                out.append(t)
    return jsonify({"tags": out})


@app.get("/api/notes/<int:nid>/img/<int:idx>")
def note_img(nid, idx):
    n = _get_note(nid)
    if not n:
        return "未找到", 404
    imgs = _jl(n, "images")
    if idx < 0 or idx >= len(imgs):
        return "未找到", 404
    path = os.path.join(UPLOADS, str(uid()), imgs[idx])
    if not os.path.exists(path):
        return "文件丢失", 404
    return send_file(path, as_attachment=False)


@app.get("/api/notes/<int:nid>/file/<int:idx>")
def note_file(nid, idx):
    n = _get_note(nid)
    if not n:
        return "未找到", 404
    atts = _jl(n, "attachments")
    if idx < 0 or idx >= len(atts):
        return "未找到", 404
    a = atts[idx]
    path = os.path.join(UPLOADS, str(uid()), a["file"])
    if not os.path.exists(path):
        return "文件丢失", 404
    ext = a.get("ext", "")
    dl = request.args.get("dl") == "1"
    if not dl and ext in OFFICE_EXT:
        pdf = _office_to_pdf(path)
        if pdf:
            return send_file(pdf, mimetype="application/pdf", as_attachment=False)
    if not dl and ext in (".html", ".htm"):
        with open(path, "rb") as fp:
            return Response(fp.read(), mimetype="text/html; charset=utf-8")
    if not dl and ext in TEXT_EXT:
        with open(path, "rb") as fp:
            return Response(fp.read(), mimetype="text/plain; charset=utf-8")
    if not dl and ext in INLINE_EXT:
        return send_file(path, as_attachment=False, download_name=a.get("name"))
    return send_file(path, as_attachment=True, download_name=a.get("name") or a["file"])


@app.put("/api/notes/<int:nid>")
def note_update(nid):
    n = _get_note(nid)
    if not n:
        return jsonify({"error": "未找到"}), 404
    content = (request.form.get("content") or "").strip()
    todos = _parse_json(request.form.get("todos"), [])
    tags = _parse_json(request.form.get("tags"), [])
    # 图片：保留 keep_imgs 中的，删其余，加新上传
    old_i = _jl(n, "images")
    keep_i = _parse_json(request.form.get("keep_imgs"), old_i)
    keep_i = [x for x in old_i if x in keep_i]
    for fn in old_i:
        if fn not in keep_i:
            _remove_file(uid(), fn)
    final_i = keep_i + _save_note_images(request.files.getlist("images"))
    # 附件：同理
    old_a = _jl(n, "attachments")
    keep_af = _parse_json(request.form.get("keep_atts"), [a["file"] for a in old_a])
    keep_a = [a for a in old_a if a["file"] in keep_af]
    for a in old_a:
        if a["file"] not in keep_af:
            _remove_file(uid(), a["file"])
    final_a = keep_a + _save_note_atts(request.files.getlist("attachments"))
    if not (content or final_i or final_a or todos):
        return jsonify({"error": "内容不能为空"}), 400
    db = get_db()
    db.execute("UPDATE notes SET content=?,images=?,attachments=?,todos=?,tags=?,"
               "updated_at=datetime('now','localtime') WHERE id=? AND user_id=?",
               (content, json.dumps(final_i), json.dumps(final_a),
                json.dumps(todos), json.dumps(tags), nid, uid()))
    db.commit()
    return jsonify(_note_dict(db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()))


@app.post("/api/notes/<int:nid>/todo")
def note_toggle_todo(nid):
    n = _get_note(nid)
    if not n:
        return jsonify({"error": "未找到"}), 404
    data = request.get_json(silent=True) or {}
    idx = data.get("idx")
    todos = _jl(n, "todos")
    if isinstance(idx, int) and 0 <= idx < len(todos):
        todos[idx]["done"] = bool(data.get("done"))
        get_db().execute("UPDATE notes SET todos=? WHERE id=? AND user_id=?",
                         (json.dumps(todos), nid, uid()))
        get_db().commit()
    return jsonify({"ok": True})


@app.delete("/api/notes/<int:nid>")
def note_delete(nid):
    n = _get_note(nid)
    if not n:
        return jsonify({"error": "未找到"}), 404
    for fn in _jl(n, "images"):
        _remove_file(uid(), fn)
    for a in _jl(n, "attachments"):
        _remove_file(uid(), a.get("file", ""))
    db = get_db()
    db.execute("DELETE FROM notes WHERE id=? AND user_id=?", (nid, uid()))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 安卓包下载
@app.get("/apk")
@app.get("/download/gongkao.apk")
def download_apk():
    apk = os.path.join(BASE, "dist", "gongkao.apk")
    if not os.path.exists(apk):
        return "APK 尚未构建", 404
    return send_file(apk, mimetype="application/vnd.android.package-archive",
                     as_attachment=True, download_name="gongkao.apk")


# ---------------------------------------------------------------- 静态前端
@app.route("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.route("/<path:fname>")
def static_files(fname):
    return send_from_directory(STATIC, fname)


# ---------------------------------------------------------------- 成语/词语 API（按用户隔离）
@app.get("/api/lookup")
def api_lookup():
    return jsonify(lookup(request.args.get("word", "")))


@app.post("/api/entries")
def api_add():
    data = request.get_json(force=True, silent=True) or {}
    word = (data.get("word") or "").strip()
    if not word:
        return jsonify({"error": "请输入成语或词语"}), 400
    info = lookup(word)
    for k in ("pinyin", "category", "explanation", "derivation", "example"):
        if data.get(k) is not None and str(data.get(k)).strip() != "":
            info[k] = data[k]
    note = (data.get("note") or "").strip()
    db = get_db()
    cur = db.execute(
        "INSERT INTO entries(user_id,word,pinyin,category,explanation,derivation,example,note,source) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (uid(), word, info["pinyin"], info["category"], info["explanation"],
         info["derivation"], info["example"], note, info["source"]))
    db.commit()
    row = db.execute("SELECT * FROM entries WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(row_to_dict(row)), 201


@app.get("/api/entries")
def api_list():
    db = get_db()
    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    starred = request.args.get("starred")
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        page_size = int(request.args.get("page_size", 5))
    except ValueError:
        page_size = 5
    page_size = max(1, min(page_size, 100))

    where = "WHERE user_id=?"
    args = [uid()]
    if q:
        where += " AND (word LIKE ? OR pinyin LIKE ? OR explanation LIKE ? OR note LIKE ?)"
        like = f"%{q}%"
        args += [like, like, like, like]
    if category in ("成语", "词语"):
        where += " AND category=?"
        args.append(category)
    if starred == "1":
        where += " AND starred=1"

    total = db.execute(f"SELECT COUNT(*) c FROM entries {where}", args).fetchone()["c"]
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    offset = (page - 1) * page_size
    rows = db.execute(
        f"SELECT * FROM entries {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        args + [page_size, offset]).fetchall()
    items = [row_to_dict(r) for r in rows]
    stats = db.execute(
        "SELECT COUNT(*) total, SUM(category='成语') idiom, SUM(category='词语') ci,"
        " SUM(starred=1) starred FROM entries WHERE user_id=?", (uid(),)).fetchone()
    return jsonify({
        "items": items, "page": page, "page_size": page_size, "pages": pages, "total": total,
        "stats": {"total": stats["total"] or 0, "idiom": stats["idiom"] or 0,
                  "ci": stats["ci"] or 0, "starred": stats["starred"] or 0},
    })


@app.put("/api/entries/<int:eid>")
def api_update(eid):
    data = request.get_json(force=True, silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id=? AND user_id=?", (eid, uid())).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    fields = ["word", "pinyin", "category", "explanation", "derivation",
              "example", "note", "starred"]
    updates, args = [], []
    for f in fields:
        if f in data:
            updates.append(f"{f}=?")
            args.append(int(bool(data[f])) if f == "starred" else data[f])
    if updates:
        args += [eid, uid()]
        db.execute(f"UPDATE entries SET {', '.join(updates)} WHERE id=? AND user_id=?", args)
        db.commit()
    row = db.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
    return jsonify(row_to_dict(row))


@app.delete("/api/entries/<int:eid>")
def api_delete(eid):
    db = get_db()
    db.execute("DELETE FROM entries WHERE id=? AND user_id=?", (eid, uid()))
    db.commit()
    return jsonify({"ok": True})


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
        serve(app, host=a.host, port=a.port, threads=8)
