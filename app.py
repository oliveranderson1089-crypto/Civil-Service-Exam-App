#!/usr/bin/env python3
"""公考·选词填空 成语/词语积累 —— 后端服务

功能：
  - 输入成语/词语，自动标注拼音 + 给出释义（出处、例句）
  - 收录、查看、编辑笔记、收藏、删除
  - 按条件导出 PDF（学习版 / 默写版），方便复习打印
"""
import io
import json
import os
import re
import secrets
import smtplib
import sqlite3
import time
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText

from flask import (Flask, g, jsonify, redirect, request, session,
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
from reportlab.lib.enums import TA_LEFT

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "app.db")
STATIC = os.path.join(BASE, "static")
CONFIG = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))

app = Flask(__name__, static_folder=None)


# ---------------------------------------------------------------- 配置 / 账号
def save_config(cfg):
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_config():
    """读取 config.json；只保证有随机密钥。账号由用户首次注册时设置。

    也支持用环境变量直接设定账号（设置后即视为已注册）：GONGKAO_USER、GONGKAO_PASSWORD。
    """
    cfg = {}
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    if not cfg.get("secret_key"):
        cfg["secret_key"] = secrets.token_hex(32)
    env_user = os.environ.get("GONGKAO_USER")
    env_pw = os.environ.get("GONGKAO_PASSWORD")
    if env_user and env_pw:
        cfg["username"] = env_user
        cfg["password_hash"] = generate_password_hash(env_pw)
        cfg["registered"] = True
    save_config(cfg)
    return cfg


CFG = load_config()
app.secret_key = CFG["secret_key"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,  # 记住登录 30 天
)


def is_registered():
    return bool(CFG.get("registered") and CFG.get("username") and CFG.get("password_hash"))


def mask_email(e):
    try:
        name, dom = e.split("@", 1)
        masked = (name[0] + "***" + name[-1]) if len(name) > 1 else (name + "***")
        return masked + "@" + dom
    except Exception:
        return e


def try_send_email(to_addr, subject, body):
    """用 config 里的 SMTP 配置发一封邮件。返回 (ok, err)。"""
    try:
        host = CFG.get("smtp_host")
        port = int(CFG.get("smtp_port") or 465)
        user = CFG.get("smtp_user") or CFG.get("email")
        pw = CFG.get("smtp_pass")
        if not (host and user and pw):
            return False, "未配置发信邮箱"
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = user
        msg["To"] = to_addr
        if port == 465:
            s = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            s = smtplib.SMTP(host, port, timeout=20)
            s.ehlo()
            s.starttls()
        s.login(user, pw)
        s.sendmail(user, [to_addr], msg.as_string())
        s.quit()
        return True, ""
    except Exception as e:
        return False, str(e)


# 找回密码验证码（内存，重启失效）：username -> {code, expires, attempts, last_sent}
_reset_codes = {}

# 无需登录即可访问的路径
_PUBLIC_EXACT = {"/login", "/api/login", "/register", "/api/register",
                 "/forgot", "/api/forgot/send", "/api/forgot/reset",
                 "/style.css", "/manifest.webmanifest", "/sw.js", "/favicon.ico"}


def _is_public(path):
    return path in _PUBLIC_EXACT or path.startswith("/icon-")


@app.before_request
def guard():
    if _is_public(request.path):
        return None
    if not is_registered():
        if request.path.startswith("/api/"):
            return jsonify({"error": "未注册", "register": True}), 401
        return redirect("/register")
    if session.get("auth"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "未登录", "login": True}), 401
    return redirect("/login")

# ---------------------------------------------------------------- 字体
# 必须字形完整且含拼音声调符号(ǎ ě ǐ ǒ ǔ ǚ…)的 TrueType 字体。
# AR PL UMing/UKai CN 经 fontTools 校验为全覆盖；放在最前。
EMBED_FONT_CANDIDATES = [
    ("CN", "/usr/share/fonts/truetype/arphic/uming.ttc", 0),  # 文鼎宋体 CN
    ("CN", "/usr/share/fonts/truetype/arphic/ukai.ttc", 0),   # 文鼎楷体 CN
]
PDF_FONT = "STSong-Light"  # 兜底（reportlab 内置 CID 简体）
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


def init_entries_table():
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS entries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL,
            pinyin TEXT,
            category TEXT,
            explanation TEXT,
            derivation TEXT,
            example TEXT,
            note TEXT,
            source TEXT,
            starred INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_entries_word ON entries(word);
        CREATE INDEX IF NOT EXISTS idx_entries_cat ON entries(category);
        """
    )
    con.commit()
    con.close()


# ---------------------------------------------------------------- 工具
CJK_RE = re.compile(r"^[一-鿿]+$")


def to_pinyin(word):
    try:
        parts = _pinyin(word, style=Style.TONE, heteronym=False, errors="default")
        return " ".join(p[0] for p in parts)
    except Exception:
        return ""


def lookup(word):
    """在参考词典中查 word，返回收录所需的字段。"""
    word = (word or "").strip()
    db = get_db()
    info = {
        "word": word,
        "pinyin": "",
        "category": "词语",
        "explanation": "",
        "derivation": "",
        "example": "",
        "source": "manual",
        "found": False,
    }
    if not word:
        return info
    row = db.execute("SELECT * FROM ref_idiom WHERE word=?", (word,)).fetchone()
    if row:
        info.update(
            pinyin=row["pinyin"] or to_pinyin(word),
            category="成语",
            explanation=row["explanation"] or "",
            derivation=row["derivation"] or "",
            example=row["example"] or "",
            source="idiom",
            found=True,
        )
        return info
    row = db.execute("SELECT * FROM ref_ci WHERE word=?", (word,)).fetchone()
    if row:
        info.update(
            pinyin=to_pinyin(word),
            category="词语",
            explanation=row["explanation"] or "",
            source="ci",
            found=True,
        )
        return info
    # 未收录：自动拼音，按长度猜测类别
    info["pinyin"] = to_pinyin(word)
    if len(word) == 4 and CJK_RE.match(word):
        info["category"] = "成语"
    return info


def row_to_dict(row):
    d = dict(row)
    d["starred"] = bool(d.get("starred"))
    return d


# ---------------------------------------------------------------- 注册 / 登录 / 找回
@app.get("/register")
def register_page():
    if is_registered():
        return redirect("/login")
    return send_from_directory(STATIC, "register.html")


@app.post("/api/register")
def api_register():
    if is_registered():
        return jsonify({"error": "已注册，请直接登录"}), 400
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    pw = data.get("password") or ""
    email = (data.get("email") or "").strip()
    if len(username) < 2:
        return jsonify({"error": "用户名至少 2 个字符"}), 400
    if len(pw) < 6:
        return jsonify({"error": "密码至少 6 位"}), 400
    if "@" not in email:
        return jsonify({"error": "请填写正确的邮箱"}), 400
    CFG["username"] = username
    CFG["password_hash"] = generate_password_hash(pw)
    CFG["email"] = email
    CFG["smtp_host"] = (data.get("smtp_host") or "").strip()
    CFG["smtp_port"] = int(data.get("smtp_port") or 465)
    CFG["smtp_user"] = (data.get("smtp_user") or email).strip()
    CFG["smtp_pass"] = data.get("smtp_pass") or ""  # 邮箱授权码
    CFG["registered"] = True
    save_config(CFG)
    session.permanent = True
    session["auth"] = True
    session["user"] = username
    warn = ""
    if CFG["smtp_host"] and CFG["smtp_pass"]:
        ok, err = try_send_email(
            email, "公考积累 · 注册成功",
            "你已成功注册「公考积累」，今后找回密码的验证码会发到此邮箱。")
        if not ok:
            warn = "账号已创建，但测试邮件发送失败，找回密码可能不可用：" + err
    return jsonify({"ok": True, "warn": warn})


@app.get("/login")
def login_page():
    if not is_registered():
        return redirect("/register")
    if session.get("auth"):
        return redirect("/")
    return send_from_directory(STATIC, "login.html")


@app.post("/login")
@app.post("/api/login")
def login_submit():
    data = request.get_json(silent=True) or request.form
    user = (data.get("username") or "").strip()
    pw = data.get("password") or ""
    if user == CFG.get("username") and check_password_hash(CFG.get("password_hash", ""), pw):
        session.permanent = True
        session["auth"] = True
        session["user"] = user
        return jsonify({"ok": True})
    return jsonify({"error": "用户名或密码错误"}), 401


@app.post("/logout")
@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/forgot")
def forgot_page():
    if not is_registered():
        return redirect("/register")
    return send_from_directory(STATIC, "forgot.html")


@app.post("/api/forgot/send")
def api_forgot_send():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    if username != CFG.get("username"):
        return jsonify({"error": "用户名不存在"}), 400
    email = CFG.get("email")
    if not (email and CFG.get("smtp_host") and CFG.get("smtp_pass")):
        return jsonify({"error": "未配置邮箱，无法邮件找回；请在电脑上重置密码"}), 400
    now = time.time()
    rec = _reset_codes.get(username)
    if rec and now - rec.get("last_sent", 0) < 60:
        return jsonify({"error": "发送过于频繁，请 1 分钟后再试"}), 429
    code = "%06d" % secrets.randbelow(1000000)
    _reset_codes[username] = {"code": code, "expires": now + 600,
                              "attempts": 0, "last_sent": now}
    ok, err = try_send_email(
        email, "公考积累 · 找回密码验证码",
        f"你的验证码是：{code}\n10 分钟内有效。若非本人操作请忽略本邮件。")
    if not ok:
        return jsonify({"error": "邮件发送失败：" + err}), 500
    return jsonify({"ok": True, "email": mask_email(email)})


@app.post("/api/forgot/reset")
def api_forgot_reset():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    code = (data.get("code") or "").strip()
    new_pw = data.get("password") or ""
    rec = _reset_codes.get(username)
    if not rec:
        return jsonify({"error": "请先获取验证码"}), 400
    if time.time() > rec["expires"]:
        _reset_codes.pop(username, None)
        return jsonify({"error": "验证码已过期，请重新获取"}), 400
    if rec["attempts"] >= 5:
        _reset_codes.pop(username, None)
        return jsonify({"error": "尝试次数过多，请重新获取验证码"}), 400
    rec["attempts"] += 1
    if code != rec["code"]:
        return jsonify({"error": "验证码错误"}), 400
    if len(new_pw) < 6:
        return jsonify({"error": "新密码至少 6 位"}), 400
    CFG["password_hash"] = generate_password_hash(new_pw)
    save_config(CFG)
    _reset_codes.pop(username, None)
    return jsonify({"ok": True})


@app.get("/api/account")
def api_account_get():
    return jsonify({
        "username": CFG.get("username", ""),
        "email": CFG.get("email", ""),
        "smtp_host": CFG.get("smtp_host", ""),
        "smtp_port": CFG.get("smtp_port", 465),
        "smtp_user": CFG.get("smtp_user", ""),
        "has_smtp_pass": bool(CFG.get("smtp_pass")),
    })


@app.post("/api/account")
def api_account_update():
    data = request.get_json(silent=True) or {}
    # 改密码需校验旧密码
    new_pw = data.get("new_password")
    if new_pw:
        if not check_password_hash(CFG.get("password_hash", ""), data.get("old_password") or ""):
            return jsonify({"error": "原密码不正确"}), 400
        if len(new_pw) < 6:
            return jsonify({"error": "新密码至少 6 位"}), 400
        CFG["password_hash"] = generate_password_hash(new_pw)
    if "email" in data and data.get("email"):
        CFG["email"] = data["email"].strip()
    for k in ("smtp_host", "smtp_user"):
        if k in data:
            CFG[k] = (data.get(k) or "").strip()
    if "smtp_port" in data and data.get("smtp_port"):
        CFG["smtp_port"] = int(data["smtp_port"])
    if data.get("smtp_pass"):  # 留空表示不修改
        CFG["smtp_pass"] = data["smtp_pass"]
    save_config(CFG)
    return jsonify({"ok": True})


@app.post("/api/account/test_email")
def api_test_email():
    to = CFG.get("email")
    if not to:
        return jsonify({"error": "未设置邮箱"}), 400
    ok, err = try_send_email(to, "公考积累 · 测试邮件", "这是一封测试邮件，收到说明邮箱配置正确。")
    return (jsonify({"ok": True, "email": mask_email(to)}) if ok
            else (jsonify({"error": err}), 500))


# ---------------------------------------------------------------- 静态前端
@app.route("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.route("/<path:fname>")
def static_files(fname):
    return send_from_directory(STATIC, fname)


# ---------------------------------------------------------------- API
@app.get("/api/lookup")
def api_lookup():
    """实时预览：查询但不收录。"""
    return jsonify(lookup(request.args.get("word", "")))


@app.post("/api/entries")
def api_add():
    data = request.get_json(force=True, silent=True) or {}
    word = (data.get("word") or "").strip()
    if not word:
        return jsonify({"error": "请输入成语或词语"}), 400
    info = lookup(word)
    # 允许前端覆盖（用户手动改了拼音/释义/类别/笔记）
    for k in ("pinyin", "category", "explanation", "derivation", "example"):
        if data.get(k) is not None and str(data.get(k)).strip() != "":
            info[k] = data[k]
    note = (data.get("note") or "").strip()
    db = get_db()
    cur = db.execute(
        """INSERT INTO entries(word,pinyin,category,explanation,derivation,example,note,source)
           VALUES(?,?,?,?,?,?,?,?)""",
        (word, info["pinyin"], info["category"], info["explanation"],
         info["derivation"], info["example"], note, info["source"]),
    )
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

    where = "WHERE 1=1"
    args = []
    if q:
        where += " AND (word LIKE ? OR pinyin LIKE ? OR explanation LIKE ? OR note LIKE ?)"
        like = f"%{q}%"
        args += [like, like, like, like]
    if category in ("成语", "词语"):
        where += " AND category=?"
        args.append(category)
    if starred == "1":
        where += " AND starred=1"

    total = db.execute(
        f"SELECT COUNT(*) c FROM entries {where}", args).fetchone()["c"]
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    offset = (page - 1) * page_size
    rows = db.execute(
        f"SELECT * FROM entries {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        args + [page_size, offset],
    ).fetchall()
    items = [row_to_dict(r) for r in rows]
    stats = db.execute(
        "SELECT COUNT(*) total,"
        " SUM(category='成语') idiom,"
        " SUM(category='词语') ci,"
        " SUM(starred=1) starred FROM entries"
    ).fetchone()
    return jsonify({
        "items": items,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "total": total,
        "stats": {
            "total": stats["total"] or 0,
            "idiom": stats["idiom"] or 0,
            "ci": stats["ci"] or 0,
            "starred": stats["starred"] or 0,
        },
    })


@app.put("/api/entries/<int:eid>")
def api_update(eid):
    data = request.get_json(force=True, silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    fields = ["word", "pinyin", "category", "explanation", "derivation",
              "example", "note", "starred"]
    updates, args = [], []
    for f in fields:
        if f in data:
            updates.append(f"{f}=?")
            val = int(bool(data[f])) if f == "starred" else data[f]
            args.append(val)
    if updates:
        args.append(eid)
        db.execute(f"UPDATE entries SET {', '.join(updates)} WHERE id=?", args)
        db.commit()
    row = db.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
    return jsonify(row_to_dict(row))


@app.delete("/api/entries/<int:eid>")
def api_delete(eid):
    db = get_db()
    db.execute("DELETE FROM entries WHERE id=?", (eid,))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- PDF 导出
def build_pdf(entries, opts):
    ensure_pdf_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title="公考选词填空·成语词语积累",
    )
    f = PDF_FONT
    st_title = ParagraphStyle("t", fontName=f, fontSize=20, leading=26,
                              alignment=1, spaceAfter=2)
    st_sub = ParagraphStyle("s", fontName=f, fontSize=10, leading=14,
                            alignment=1, textColor=colors.grey, spaceAfter=10)
    st_word = ParagraphStyle("w", fontName=f, fontSize=15, leading=20)
    st_py = ParagraphStyle("py", fontName=f, fontSize=11, leading=20,
                           textColor=colors.HexColor("#1a6fb5"), alignment=2)
    st_label = ParagraphStyle("lb", fontName=f, fontSize=10.5, leading=16,
                              textColor=colors.HexColor("#444444"))
    st_blank = ParagraphStyle("bk", fontName=f, fontSize=10.5, leading=22,
                              textColor=colors.HexColor("#bbbbbb"))

    story = []
    story.append(Paragraph("公考·选词填空　成语 / 词语积累", st_title))
    story.append(Paragraph(
        datetime.now().strftime("导出于 %Y-%m-%d %H:%M") +
        f"　共 {len(entries)} 条" +
        ("　【默写版】" if opts.get("mode") == "recite" else ""), st_sub))

    recite = opts.get("mode") == "recite"
    inc_der = opts.get("derivation", True)
    inc_exa = opts.get("example", True)
    inc_note = opts.get("note", True)

    for i, e in enumerate(entries, 1):
        word = (e.get("word") or "").replace("\n", " ")
        py = (e.get("pinyin") or "")
        head = Table(
            [[Paragraph(f'<b>{i}. {word}</b>', st_word),
              Paragraph(py, st_py)]],
            colWidths=[None, 55 * mm])
        head.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(head)

        def field(label, value):
            value = (value or "").strip().replace("\n", " ")
            if not value:
                return
            story.append(Paragraph(
                f'<font color="#888888">{label}</font>　{value}', st_label))

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
        story.append(HRFlowable(width="100%", thickness=0.4,
                                color=colors.HexColor("#dddddd")))
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
        data = {
            "mode": a.get("mode", "study"),
            "category": a.get("category", ""),
            "starred": _truthy(a.get("starred"), False),
            "derivation": _truthy(a.get("der")),
            "example": _truthy(a.get("exa")),
            "note": _truthy(a.get("note")),
        }
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
            f"SELECT * FROM entries WHERE id IN ({qmarks}) ORDER BY id DESC", ids
        ).fetchall()
    else:
        sql = "SELECT * FROM entries WHERE 1=1"
        args = []
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
    opts = {
        "mode": data.get("mode", "study"),
        "derivation": data.get("derivation", True),
        "example": data.get("example", True),
        "note": data.get("note", True),
    }
    pdf = build_pdf(entries, opts)
    fname = "公考积累_%s%s.pdf" % (
        datetime.now().strftime("%Y%m%d_%H%M"),
        "_默写版" if opts["mode"] == "recite" else "",
    )
    return send_file(pdf, mimetype="application/pdf",
                     as_attachment=True, download_name=fname)


if __name__ == "__main__":
    init_entries_table()
    ensure_pdf_font()
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
        print(f" * 公考积累服务已启动： http://{a.host}:{a.port}")
        serve(app, host=a.host, port=a.port, threads=8)
