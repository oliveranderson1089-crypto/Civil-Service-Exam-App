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
import urllib.error
import urllib.request
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


# ---------------------------------------------------------------- AI（云端大模型，OpenAI 兼容）
def _save_cfg():
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(CFG, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _ai_conf():
    return {
        "base": (CFG.get("ai_base") or "https://api.deepseek.com").rstrip("/"),
        "model": CFG.get("ai_model") or "deepseek-chat",
        "key": CFG.get("ai_key") or os.environ.get("GONGKAO_AI_KEY", ""),
    }


def ai_configured():
    return bool(_ai_conf()["key"])


def ai_chat(messages, temperature=0.4, max_tokens=1600, timeout=120):
    """调用 OpenAI 兼容的对话接口（默认 DeepSeek），返回回复文本。"""
    conf = _ai_conf()
    if not conf["key"]:
        raise RuntimeError("AI 未配置，请管理员在「后台 → AI 设置」填写 API Key")
    b = conf["base"]
    if b.endswith("/chat/completions"):
        url = b
    elif b.endswith("/v1"):
        url = b + "/chat/completions"
    else:
        url = b + "/v1/chat/completions"
    body = json.dumps({"model": conf["model"], "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens,
                       "stream": False}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + conf["key"],
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d["choices"][0]["message"]["content"].strip()


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
        CREATE TABLE IF NOT EXISTS notebooks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            intro TEXT,
            cover INTEGER DEFAULT 0,
            sort INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_nb_user ON notebooks(user_id);
        CREATE TABLE IF NOT EXISTS kb_nodes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            notebook_id INTEGER NOT NULL,
            parent_id INTEGER,
            type TEXT NOT NULL,            -- 'group' 分组 | 'doc' 文档
            title TEXT,
            content TEXT,                 -- 文档块 JSON（doc 才有）
            sort INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_kbn_book ON kb_nodes(user_id, notebook_id, parent_id);
        CREATE TABLE IF NOT EXISTS classics(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT, title TEXT, author TEXT, dynasty TEXT, content TEXT, sub TEXT,
            translation TEXT, appreciation TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_classics_cat ON classics(category);
        CREATE TABLE IF NOT EXISTS classic_stars(
            user_id INTEGER NOT NULL,
            classic_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, classic_id)
        );
        -- AI 讲解全局缓存（同一首诗只算一次，省钱）
        CREATE TABLE IF NOT EXISTS classic_ai(
            classic_id INTEGER PRIMARY KEY,
            content TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
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
    # classics 表补充字段：译文 / 赏析
    if "classics" in [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
        for col in ("translation", "appreciation"):
            if col not in _cols(con, "classics"):
                con.execute(f"ALTER TABLE classics ADD COLUMN {col} TEXT")

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
            return jsonify({"error": "至少保留一个管理员，请先把另一位用户设为管理员，再撤销当前管理员"}), 400
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


def _extract_pdf_text(pdf_path):
    """用 pdftotext 提取 PDF 文字（-layout 尽量保留版式），供阅读模式用。"""
    try:
        out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", pdf_path, "-"],
                             capture_output=True, timeout=90)
        return out.stdout.decode("utf-8", "ignore")
    except Exception:
        return ""


def _extract_text(path, ext):
    """把文件转成纯文本：pdf 直接提取；Office 先转 pdf 再提取；文本类直接读。"""
    if not os.path.exists(path):
        return None
    if ext == ".pdf":
        return _extract_pdf_text(path)
    if ext in OFFICE_EXT:
        pdf = _office_to_pdf(path)
        return _extract_pdf_text(pdf) if pdf else ""
    if ext in TEXT_EXT or ext in (".html", ".htm"):
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""
    return ""


@app.get("/api/materials/<int:mid>/text")
def material_text(mid):
    m = _get_material(mid)
    if not m:
        return jsonify({"error": "未找到"}), 404
    t = _extract_text(os.path.join(UPLOADS, str(uid()), m["stored_name"]), m["ext"])
    if t is None:
        return jsonify({"error": "文件丢失"}), 404
    return jsonify({"text": t})


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


@app.put("/api/materials/<int:mid>")
def material_update(mid):
    m = _get_material(mid)
    if not m:
        return jsonify({"error": "未找到"}), 404
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "名称不能为空"}), 400
    db = get_db()
    if "board" in data:
        board = (data.get("board") or "").strip()
        if board and board not in ALL_BOARDS:
            return jsonify({"error": "板块无效"}), 400
        db.execute("UPDATE materials SET title=?, board=? WHERE id=? AND user_id=?",
                   (title, board, mid, uid()))
    else:
        db.execute("UPDATE materials SET title=? WHERE id=? AND user_id=?", (title, mid, uid()))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/materials/<int:mid>/duplicate")
def material_duplicate(mid):
    import shutil
    m = _get_material(mid)
    if not m:
        return jsonify({"error": "未找到"}), 404
    src = os.path.join(UPLOADS, str(uid()), m["stored_name"])
    if not os.path.exists(src):
        return jsonify({"error": "源文件丢失"}), 404
    ext = m["ext"] or ""
    stored = uuid.uuid4().hex + ext
    dst = os.path.join(_user_dir(uid()), stored)
    shutil.copy2(src, dst)
    title = (m["title"] or m["orig_name"] or "文档") + " 副本"
    db = get_db()
    cur = db.execute(
        "INSERT INTO materials(user_id,section,board,title,orig_name,stored_name,ext,mime,size) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (uid(), m["section"], m["board"], title, m["orig_name"], stored, ext,
         m["mime"], os.path.getsize(dst)))
    db.commit()
    return jsonify(dict(db.execute("SELECT * FROM materials WHERE id=?", (cur.lastrowid,)).fetchone())), 201


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
            # 相册/content URI 选图常无扩展名：按 mimetype 兜底
            mt = (f.mimetype or "").lower()
            if mt.startswith("image/"):
                ext = "." + mt.split("/", 1)[1].split("+")[0]
                if ext not in NOTE_IMG_EXT:
                    ext = ".jpg"
            else:
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


@app.get("/api/notes/<int:nid>/file/<int:idx>/text")
def note_file_text(nid, idx):
    n = _get_note(nid)
    if not n:
        return jsonify({"error": "未找到"}), 404
    atts = _jl(n, "attachments")
    if idx < 0 or idx >= len(atts):
        return jsonify({"error": "未找到"}), 404
    a = atts[idx]
    t = _extract_text(os.path.join(UPLOADS, str(uid()), a["file"]), a.get("ext", ""))
    if t is None:
        return jsonify({"error": "文件丢失"}), 404
    return jsonify({"text": t})


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


# ================================================================ 知识库（笔记本 + 文档树）
def _kb_notebook(nb_id):
    return get_db().execute(
        "SELECT * FROM notebooks WHERE id=? AND user_id=?", (nb_id, uid())).fetchone()


def _kb_get_node(node_id):
    return get_db().execute(
        "SELECT * FROM kb_nodes WHERE id=? AND user_id=?", (node_id, uid())).fetchone()


def _notebook_dict(row):
    n = get_db().execute(
        "SELECT COUNT(*) c FROM kb_nodes WHERE notebook_id=? AND type='doc'",
        (row["id"],)).fetchone()["c"]
    return {"id": row["id"], "name": row["name"], "intro": row["intro"] or "",
            "cover": row["cover"] or 0, "doc_count": n,
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def _node_dict(row, with_content=False):
    d = {"id": row["id"], "notebook_id": row["notebook_id"],
         "parent_id": row["parent_id"], "type": row["type"],
         "title": row["title"] or "", "updated_at": row["updated_at"]}
    if with_content:
        d["content"] = _jl(row, "content")
    return d


def _kb_tree(nb_id):
    rows = get_db().execute(
        "SELECT * FROM kb_nodes WHERE notebook_id=? AND user_id=? ORDER BY sort, id",
        (nb_id, uid())).fetchall()
    nodes = {r["id"]: {**_node_dict(r), "children": []} for r in rows}
    roots = []
    for r in rows:
        nd = nodes[r["id"]]
        p = r["parent_id"]
        if p and p in nodes:
            nodes[p]["children"].append(nd)
        else:
            roots.append(nd)
    return roots


def _kb_assets_in_content(content):
    """从文档块 JSON 里收集引用的存储文件名，便于删除时清理。"""
    out = []
    for b in (content or []):
        data = b.get("data") or {}
        s = data.get("stored")
        if s:
            out.append(s)
    return out


@app.get("/api/kb/notebooks")
def kb_notebooks():
    rows = get_db().execute(
        "SELECT * FROM notebooks WHERE user_id=? ORDER BY sort, id DESC", (uid(),)).fetchall()
    return jsonify({"items": [_notebook_dict(r) for r in rows]})


@app.post("/api/kb/notebooks")
def kb_notebook_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "请填写知识库名称"}), 400
    intro = (data.get("intro") or "").strip()
    cover = int(data.get("cover") or 0)
    db = get_db()
    cur = db.execute("INSERT INTO notebooks(user_id,name,intro,cover) VALUES(?,?,?,?)",
                     (uid(), name, intro, cover))
    db.commit()
    return jsonify(_notebook_dict(db.execute(
        "SELECT * FROM notebooks WHERE id=?", (cur.lastrowid,)).fetchone())), 201


@app.put("/api/kb/notebooks/<int:nb_id>")
def kb_notebook_update(nb_id):
    if not _kb_notebook(nb_id):
        return jsonify({"error": "未找到"}), 404
    data = request.get_json(silent=True) or {}
    sets, args = [], []
    if "name" in data:
        nm = (data.get("name") or "").strip()
        if not nm:
            return jsonify({"error": "名称不能为空"}), 400
        sets.append("name=?"); args.append(nm)
    if "intro" in data:
        sets.append("intro=?"); args.append((data.get("intro") or "").strip())
    if "cover" in data:
        sets.append("cover=?"); args.append(int(data.get("cover") or 0))
    if sets:
        sets.append("updated_at=datetime('now','localtime')")
        args += [nb_id, uid()]
        get_db().execute("UPDATE notebooks SET %s WHERE id=? AND user_id=?" % ",".join(sets), args)
        get_db().commit()
    return jsonify(_notebook_dict(_kb_notebook(nb_id)))


@app.delete("/api/kb/notebooks/<int:nb_id>")
def kb_notebook_delete(nb_id):
    if not _kb_notebook(nb_id):
        return jsonify({"error": "未找到"}), 404
    db = get_db()
    for r in db.execute("SELECT content FROM kb_nodes WHERE notebook_id=? AND user_id=?",
                        (nb_id, uid())).fetchall():
        for s in _kb_assets_in_content(_jl(r, "content")):
            _remove_file(uid(), s)
    db.execute("DELETE FROM kb_nodes WHERE notebook_id=? AND user_id=?", (nb_id, uid()))
    db.execute("DELETE FROM notebooks WHERE id=? AND user_id=?", (nb_id, uid()))
    db.commit()
    return jsonify({"ok": True})


@app.get("/api/kb/notebooks/<int:nb_id>")
def kb_notebook_detail(nb_id):
    nb = _kb_notebook(nb_id)
    if not nb:
        return jsonify({"error": "未找到"}), 404
    return jsonify({"notebook": _notebook_dict(nb), "tree": _kb_tree(nb_id)})


@app.post("/api/kb/nodes")
def kb_node_create():
    data = request.get_json(silent=True) or {}
    nb_id = data.get("notebook_id")
    if not _kb_notebook(nb_id):
        return jsonify({"error": "知识库不存在"}), 404
    ntype = data.get("type")
    if ntype not in ("group", "doc"):
        return jsonify({"error": "类型错误"}), 400
    parent_id = data.get("parent_id") or None
    if parent_id is not None:
        p = _kb_get_node(parent_id)
        if not p or p["type"] != "group" or p["notebook_id"] != nb_id:
            return jsonify({"error": "父分组无效"}), 400
    title = (data.get("title") or "").strip()
    if not title:
        title = "未命名分组" if ntype == "group" else "无标题文档"
    db = get_db()
    nxt = db.execute("SELECT COALESCE(MAX(sort),0)+1 s FROM kb_nodes "
                     "WHERE notebook_id=? AND IFNULL(parent_id,0)=IFNULL(?,0)",
                     (nb_id, parent_id)).fetchone()["s"]
    cur = db.execute(
        "INSERT INTO kb_nodes(user_id,notebook_id,parent_id,type,title,content,sort) "
        "VALUES(?,?,?,?,?,?,?)",
        (uid(), nb_id, parent_id, ntype, title, "[]" if ntype == "doc" else None, nxt))
    db.execute("UPDATE notebooks SET updated_at=datetime('now','localtime') WHERE id=?", (nb_id,))
    db.commit()
    return jsonify(_node_dict(db.execute(
        "SELECT * FROM kb_nodes WHERE id=?", (cur.lastrowid,)).fetchone(), with_content=True)), 201


@app.get("/api/kb/nodes/<int:node_id>")
def kb_node_get(node_id):
    r = _kb_get_node(node_id)
    if not r:
        return jsonify({"error": "未找到"}), 404
    return jsonify(_node_dict(r, with_content=True))


@app.put("/api/kb/nodes/<int:node_id>")
def kb_node_update(node_id):
    r = _kb_get_node(node_id)
    if not r:
        return jsonify({"error": "未找到"}), 404
    data = request.get_json(silent=True) or {}
    sets, args = [], []
    if "title" in data:
        sets.append("title=?"); args.append((data.get("title") or "").strip())
    if "content" in data:
        # 清理被移除的资源文件
        old = _kb_assets_in_content(_jl(r, "content"))
        new = _kb_assets_in_content(data.get("content") or [])
        for s in old:
            if s not in new:
                _remove_file(uid(), s)
        sets.append("content=?"); args.append(json.dumps(data.get("content") or []))
    if "parent_id" in data:
        pid = data.get("parent_id") or None
        if pid is not None:
            p = _kb_get_node(pid)
            if not p or p["type"] != "group" or p["notebook_id"] != r["notebook_id"] or pid == node_id:
                return jsonify({"error": "目标分组无效"}), 400
        sets.append("parent_id=?"); args.append(pid)
    if "sort" in data:
        sets.append("sort=?"); args.append(int(data.get("sort") or 0))
    if sets:
        sets.append("updated_at=datetime('now','localtime')")
        args += [node_id, uid()]
        db = get_db()
        db.execute("UPDATE kb_nodes SET %s WHERE id=? AND user_id=?" % ",".join(sets), args)
        db.execute("UPDATE notebooks SET updated_at=datetime('now','localtime') WHERE id=?",
                   (r["notebook_id"],))
        db.commit()
    return jsonify(_node_dict(_kb_get_node(node_id), with_content=True))


@app.delete("/api/kb/nodes/<int:node_id>")
def kb_node_delete(node_id):
    r = _kb_get_node(node_id)
    if not r:
        return jsonify({"error": "未找到"}), 404
    db = get_db()
    # 递归收集子孙
    to_del, stack = [], [node_id]
    while stack:
        cur = stack.pop()
        to_del.append(cur)
        for ch in db.execute("SELECT id FROM kb_nodes WHERE parent_id=? AND user_id=?",
                             (cur, uid())).fetchall():
            stack.append(ch["id"])
    for nid in to_del:
        row = db.execute("SELECT content FROM kb_nodes WHERE id=?", (nid,)).fetchone()
        if row:
            for s in _kb_assets_in_content(_jl(row, "content")):
                _remove_file(uid(), s)
        db.execute("DELETE FROM kb_nodes WHERE id=? AND user_id=?", (nid, uid()))
    db.commit()
    return jsonify({"ok": True})


KB_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")


@app.post("/api/kb/upload")
def kb_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "没有文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    stored = "kb_" + uuid.uuid4().hex + ext
    path = os.path.join(_user_dir(uid()), stored)
    f.save(path)
    is_img = ext in KB_IMG_EXT
    return jsonify({
        "stored": stored, "name": f.filename, "ext": ext,
        "size": os.path.getsize(path), "is_image": is_img,
        "viewable": is_img or (ext in INLINE_EXT) or (ext in OFFICE_EXT),
        "url": "/api/kb/asset/" + stored,
    })


@app.get("/api/kb/asset/<path:stored>")
def kb_asset(stored):
    stored = os.path.basename(stored)
    path = os.path.join(UPLOADS, str(uid()), stored)
    if not os.path.exists(path):
        return "文件丢失", 404
    ext = os.path.splitext(stored)[1].lower()
    if request.args.get("text") == "1":      # 阅读模式取文字
        return jsonify({"text": _extract_text(path, ext) or ""})
    dl = request.args.get("dl") == "1"
    if not dl and ext in OFFICE_EXT:
        pdf = _office_to_pdf(path)
        if pdf:
            return send_file(pdf, mimetype="application/pdf", as_attachment=False)
    if not dl and (ext in KB_IMG_EXT or ext in INLINE_EXT):
        return send_file(path, as_attachment=False)
    return send_file(path, as_attachment=True)


# ================================================================ 全文搜索
def _snippet(text, q, span=42):
    if not text:
        return ""
    low = text.lower()
    i = low.find(q.lower())
    if i < 0:
        return (text[:90].replace("\n", " ")).strip()
    start = max(0, i - span)
    end = min(len(text), i + len(q) + span)
    s = text[start:end].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + s + ("…" if end < len(text) else "")


def _block_text(b):
    t = re.sub(r"<[^>]+>", "", b.get("text", "") or "")
    data = b.get("data") or {}
    if b.get("type") == "table":
        for row in (data.get("rows") or []):
            t += " " + " ".join(str(c) for c in row)
    return t


@app.get("/api/notes/<int:nid>")
def note_get(nid):
    n = _get_note(nid)
    if not n:
        return jsonify({"error": "未找到"}), 404
    return jsonify(_note_dict(n))


@app.get("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"results": []})
    ql = q.lower()
    db = get_db()
    results = []
    # 小记
    for r in db.execute("SELECT * FROM notes WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall():
        content = r["content"] or ""
        tags = _jl(r, "tags")
        todos = " ".join(t.get("text", "") for t in _jl(r, "todos"))
        hay = content + " " + " ".join(tags) + " " + todos
        if ql in hay.lower():
            results.append({"type": "note", "id": r["id"],
                            "title": (content[:24].strip() or "（图片/附件小记）"),
                            "snippet": _snippet(content or todos, q),
                            "tags": tags, "board": r["board"] or ""})
    # 资料库（文本类读内容搜，其它搜文件名/标题）
    for r in db.execute("SELECT * FROM materials WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall():
        name = (r["title"] or "") + " " + (r["orig_name"] or "")
        body = ""
        if r["ext"] in TEXT_EXT or r["ext"] in (".html", ".htm"):
            try:
                p = os.path.join(UPLOADS, str(uid()), r["stored_name"])
                with open(p, encoding="utf-8", errors="ignore") as fp:
                    body = fp.read()
            except Exception:
                body = ""
        hit_body = body and ql in body.lower()
        if ql in name.lower() or hit_body:
            results.append({"type": "material", "id": r["id"],
                            "title": r["title"] or r["orig_name"], "ext": r["ext"],
                            "viewable": (r["ext"] in INLINE_EXT) or (r["ext"] in OFFICE_EXT) or (r["ext"] in TEXT_EXT),
                            "board": r["board"] or "",
                            "snippet": _snippet(body, q) if hit_body else ""})
    # 知识库文档
    nb_names = {row["id"]: row["name"] for row in
                db.execute("SELECT id,name FROM notebooks WHERE user_id=?", (uid(),)).fetchall()}
    for r in db.execute("SELECT * FROM kb_nodes WHERE user_id=? AND type='doc'", (uid(),)).fetchall():
        title = r["title"] or ""
        body = " ".join(_block_text(b) for b in _jl(r, "content"))
        hay = title + " " + body
        if ql in hay.lower():
            results.append({"type": "doc", "id": r["id"], "notebook_id": r["notebook_id"],
                            "notebook": nb_names.get(r["notebook_id"], ""),
                            "title": title or "无标题文档", "snippet": _snippet(body, q)})
    return jsonify({"results": results, "q": q})


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
    rows = db.execute("SELECT c.* FROM classics c %s%s ORDER BY c.id LIMIT ? OFFSET ?" % (join, wsql),
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
         {"role": "user", "content": prompt}], temperature=0.5, max_tokens=1300)
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
    return db.execute("SELECT c.* FROM classics c %s%s ORDER BY c.id LIMIT 400" % (join, wsql), args).fetchall()


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


# ================================================================ AI 助手
def _ai_call_or_error(messages, **kw):
    """统一封装：调用 AI，出错时返回 (None, (json, code))。"""
    try:
        return ai_chat(messages, **kw), None
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:300]
        except Exception:
            pass
        msg = "AI 服务返回错误 %d" % e.code
        if e.code == 401:
            msg = "API Key 无效或未授权，请在后台重新填写"
        elif e.code == 402:
            msg = "账户余额不足，请到 DeepSeek 充值"
        elif e.code == 429:
            msg = "请求过于频繁，请稍后再试"
        return None, (jsonify({"error": msg, "detail": detail}), 502)
    except urllib.error.URLError as e:
        return None, (jsonify({"error": "连不上 AI 服务：" + str(e.reason)}), 502)
    except Exception as e:
        return None, (jsonify({"error": "AI 调用失败：" + str(e)}), 502)


@app.get("/api/ai/status")
def ai_status():
    return jsonify({"configured": ai_configured(), "model": _ai_conf()["model"]})


@app.post("/api/ai/chat")
def api_ai_chat():
    data = request.get_json(silent=True) or {}
    msgs = data.get("messages")
    if not isinstance(msgs, list) or not msgs:
        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"error": "请输入内容"}), 400
        msgs = [{"role": "user", "content": prompt}]
    sys = data.get("system") or "你是「公考助手」里的 AI 学习助理，服务正在备考公务员的用户。回答简洁、准确、条理清晰，用简体中文。"
    full = [{"role": "system", "content": sys}] + msgs
    reply, err = _ai_call_or_error(full, temperature=data.get("temperature", 0.6),
                                   max_tokens=data.get("max_tokens", 1600))
    if err:
        return err
    return jsonify({"reply": reply})


@app.get("/api/admin/ai")
def admin_ai_get():
    c = _ai_conf()
    return jsonify({"base": c["base"], "model": c["model"], "has_key": bool(c["key"])})


@app.post("/api/admin/ai")
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


# ================================================================ OCR 识图（tesseract）
@app.post("/api/ocr")
def api_ocr():
    f = request.files.get("file") or request.files.get("image")
    if not f or not f.filename:
        return jsonify({"error": "没有图片"}), 400
    ext = os.path.splitext(f.filename)[1].lower() or ".jpg"
    tmp = os.path.join(tempfile.gettempdir(), "ocr_" + uuid.uuid4().hex + ext)
    f.save(tmp)
    text = ""
    try:
        out = subprocess.run(["tesseract", tmp, "stdout", "-l", "chi_sim+eng", "--psm", "6"],
                             capture_output=True, timeout=90)
        text = out.stdout.decode("utf-8", "ignore")
    except Exception as e:
        try:
            os.remove(tmp)
        except Exception:
            pass
        return jsonify({"error": "识别失败：" + str(e)}), 500
    try:
        os.remove(tmp)
    except Exception:
        pass
    # tesseract 中文常在汉字间插空格，去掉相邻汉字间的空白
    text = re.sub(r"(?<=[一-鿿，。！？；：、（）《》“”])[ \t]+(?=[一-鿿，。！？；：、（）《》“”])", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return jsonify({"text": text})


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
