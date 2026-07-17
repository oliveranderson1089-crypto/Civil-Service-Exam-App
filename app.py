#!/usr/bin/env python3
"""公考助手 —— 后端服务（多用户）：装配 + 访问控制 + 静态前端。

- 行测 / 申论 两大板块，下设若干小板块
- 言语理解与表达：成语/词语积累（拼音+释义+PDF 导出）
- 每个板块：资料库（上传图片/文档/网页，应用内直接查看，Office 自动转 PDF）
- 多用户 + 密保问题找回密码 + 管理员后台

本文件只管三件事：建 Flask app、挂 53 个业务蓝图、守 before_request 鉴权。
业务在 mods/ 各模块里，建表在 schema.py，共用地基在 core.py。
依赖单向流动：app.py → mods/* → core.py，没有环。

加新功能 = 在 mods/ 下建一个文件（一个蓝图）+ 本文件两行 import/注册。
"""
import os

from flask import Flask, jsonify, redirect, request, send_from_directory, session

from mods.pdfkit import ensure_pdf_font
from schema import init_db
from core import CFG, STATIC, UPLOADS, close_db, users_count

# 各业务模块的蓝图。加新模块 = 在 mods/ 下建一个文件 + 这里两行；
# tests/test_wiring.py 会盯着别漏了注册（漏掉的话路由会静默消失）。
from mods.admin import bp as admin_bp
from mods.aichat import bp as aichat_bp
from mods.aisession import bp as aisession_bp
from mods.annots import bp as annots_bp
from mods.attach import bp as attach_bp
from mods.auth import bp as auth_bp
from mods.basics import bp as basics_bp
from mods.bookmarks import bp as bookmarks_bp
from mods.changkao import bp as changkao_bp
from mods.classics import bp as classics_bp
from mods.classics_lookup import bp as classics_lookup_bp
from mods.dailytest import bp as dailytest_bp
from mods.dist import bp as dist_bp
from mods.docqa import bp as docqa_bp
from mods.drafts import bp as drafts_bp
from mods.drill import bp as drill_bp
from mods.dtest import bp as dtest_bp
from mods.entries import bp as entries_bp
from mods.essays import bp as essays_bp
from mods.fanwen import bp as fanwen_bp
from mods.find import bp as find_bp
from mods.gaikuo import bp as gaikuo_bp
from mods.gongwen import bp as gongwen_bp
from mods.handwrite import bp as handwrite_bp
from mods.hyper import bp as hyper_bp
from mods.kb import bp as kb_bp
from mods.lianjie import bp as lianjie_bp
from mods.marks import bp as marks_bp
from mods.materials import bp as materials_bp
from mods.me import bp as me_bp
from mods.news import bp as news_bp
from mods.notes import bp as notes_bp
from mods.notifications import bp as notifications_bp
from mods.ocr import bp as ocr_bp
from mods.partydict import bp as partydict_bp
from mods.pdfexport import bp as pdfexport_bp
from mods.plan import bp as plan_bp
from mods.policydocs import bp as policydocs_bp
from mods.quiz import bp as quiz_bp
from mods.review import bp as review_bp
from mods.search import bp as search_bp
from mods.shenlun import bp as shenlun_bp
from mods.skin import bp as skin_bp
from mods.social import bp as social_bp
from mods.sucai import bp as sucai_bp
from mods.sync import bp as sync_bp
from mods.tasks import bp as tasks_bp
from mods.team import bp as team_bp
from mods.theory import bp as theory_bp
from mods.todos import bp as todos_bp
from mods.wrongq import bp as wrongq_bp
from mods.xiyu import bp as xiyu_bp
from mods.zinnia import bp as zinnia_bp

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 单文件最大 64MB
app.secret_key = CFG["secret_key"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
    SEND_FILE_MAX_AGE_DEFAULT=0,  # 静态文件不长期缓存，浏览器每次校验，避免旧样式
)
app.teardown_appcontext(close_db)

# ---------------------------------------------------------------- 装配蓝图
app.register_blueprint(admin_bp)
app.register_blueprint(aichat_bp)
app.register_blueprint(aisession_bp)
app.register_blueprint(annots_bp)
app.register_blueprint(attach_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(basics_bp)
app.register_blueprint(bookmarks_bp)
app.register_blueprint(changkao_bp)
app.register_blueprint(classics_bp)
app.register_blueprint(classics_lookup_bp)
app.register_blueprint(dailytest_bp)
app.register_blueprint(dist_bp)
app.register_blueprint(docqa_bp)
app.register_blueprint(drafts_bp)
app.register_blueprint(drill_bp)
app.register_blueprint(dtest_bp)
app.register_blueprint(entries_bp)
app.register_blueprint(essays_bp)
app.register_blueprint(fanwen_bp)
app.register_blueprint(find_bp)
app.register_blueprint(gaikuo_bp)
app.register_blueprint(gongwen_bp)
app.register_blueprint(handwrite_bp)
app.register_blueprint(hyper_bp)
app.register_blueprint(kb_bp)
app.register_blueprint(lianjie_bp)
app.register_blueprint(marks_bp)
app.register_blueprint(materials_bp)
app.register_blueprint(me_bp)
app.register_blueprint(news_bp)
app.register_blueprint(notes_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(ocr_bp)
app.register_blueprint(partydict_bp)
app.register_blueprint(pdfexport_bp)
app.register_blueprint(plan_bp)
app.register_blueprint(policydocs_bp)
app.register_blueprint(quiz_bp)
app.register_blueprint(review_bp)
app.register_blueprint(search_bp)
app.register_blueprint(shenlun_bp)
app.register_blueprint(skin_bp)
app.register_blueprint(social_bp)
app.register_blueprint(sucai_bp)
app.register_blueprint(sync_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(team_bp)
app.register_blueprint(theory_bp)
app.register_blueprint(todos_bp)
app.register_blueprint(wrongq_bp)
app.register_blueprint(xiyu_bp)
app.register_blueprint(zinnia_bp)

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
_SHELL_NOSTORE = {"/", "/index.html", "/style.css", "/sw.js",
                  "/manifest.webmanifest", "/login", "/register", "/forgot", "/admin"}


def _is_shell(path):
    """前端脚本原先是一个 /app.js，现在拆成了 /js/*.js（15 个，还会增减）。
    所以按前缀判断，别再逐个登记 —— 上次就是漏了这一步：拆完 15 个文件全都
    只剩 no-cache，CDN 可以存副本，正是这行当初要防的事。"""
    return path in _SHELL_NOSTORE or path.startswith("/js/")


@app.after_request
def _shell_no_store(resp):
    if _is_shell(request.path):
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


@app.route("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.route("/<path:fname>")
def static_files(fname):
    return send_from_directory(STATIC, fname)


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
