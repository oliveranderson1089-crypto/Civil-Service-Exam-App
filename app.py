#!/usr/bin/env python3
"""公考助手 —— 后端服务（多用户）：装配 + 访问控制 + 静态前端。

- 行测 / 申论 两大板块，下设若干小板块
- 言语理解与表达：成语/词语积累（拼音+释义+PDF 导出）
- 每个板块：资料库（上传图片/文档/网页，应用内直接查看，Office 自动转 PDF）
- 多用户 + 密保问题找回密码 + 管理员后台

本文件只管三件事：建 Flask app、挂 60 个业务蓝图、守 before_request 鉴权。
业务在 mods/ 各模块里，建表在 schema.py，共用地基在 core.py。
依赖单向流动：app.py → mods/* → core.py，没有环。

加新功能 = 在 mods/ 下建一个文件（一个蓝图）+ 本文件两行 import/注册。
"""
import gzip
import os

from flask import Flask, jsonify, redirect, request, send_from_directory, session

import assets
from mods.pdfkit import ensure_pdf_font
from schema import init_db
from core import CFG, STATIC, UPLOADS, close_db, users_count

# 各业务模块的蓝图。加新模块 = 在 mods/ 下建一个文件 + 这里两行；
# tests/test_wiring.py 会盯着别漏了注册（漏掉的话路由会静默消失）。
from mods.admin import bp as admin_bp
from mods.aichat import bp as aichat_bp
from mods.aisession import bp as aisession_bp
from mods.aistats import bp as aistats_bp
from mods.annots import bp as annots_bp
from mods.attach import bp as attach_bp
from mods.auth import bp as auth_bp
from mods.basics import bp as basics_bp
from mods.bookmarks import bp as bookmarks_bp
from mods.capacity import bp as capacity_bp
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
from mods.exam import bp as exam_bp
from mods.fanwen import bp as fanwen_bp
from mods.find import bp as find_bp
from mods.gaikuo import bp as gaikuo_bp
from mods.gongwen import bp as gongwen_bp
from mods.handwrite import bp as handwrite_bp
from mods.health import bp as health_bp
from mods.hub import bp as hub_bp
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
from mods.ops import bp as ops_bp
from mods.partydict import bp as partydict_bp
from mods.pdfexport import bp as pdfexport_bp
from mods.plan import bp as plan_bp
from mods.policydocs import bp as policydocs_bp
from mods.quality import bp as quality_bp
from mods.quiz import bp as quiz_bp
from mods.realq import bp as realq_bp
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
from mods.today import bp as today_bp
from mods.todos import bp as todos_bp
from mods.wrongq import bp as wrongq_bp
from mods.xiyu import bp as xiyu_bp
from mods.zinnia import bp as zinnia_bp

app = Flask(__name__, static_folder=None)
# 单文件最大 64MB。云盘/聊天要收更大的文件，在 mods/social.py 里按请求单独放宽
# （别在这儿改大：那等于给所有接口都开了口子）
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
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
app.register_blueprint(aistats_bp)
app.register_blueprint(annots_bp)
app.register_blueprint(attach_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(basics_bp)
app.register_blueprint(bookmarks_bp)
app.register_blueprint(capacity_bp)
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
app.register_blueprint(exam_bp)
app.register_blueprint(fanwen_bp)
app.register_blueprint(find_bp)
app.register_blueprint(gaikuo_bp)
app.register_blueprint(gongwen_bp)
app.register_blueprint(handwrite_bp)
app.register_blueprint(health_bp)
app.register_blueprint(hub_bp)
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
app.register_blueprint(ops_bp)
app.register_blueprint(partydict_bp)
app.register_blueprint(pdfexport_bp)
app.register_blueprint(plan_bp)
app.register_blueprint(policydocs_bp)
app.register_blueprint(quality_bp)
app.register_blueprint(quiz_bp)
app.register_blueprint(realq_bp)
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
app.register_blueprint(today_bp)
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
    # /s/ 是云盘分享链接：本来就是发给没账号的人的，靠 token 本身当凭证（见 drive_share_get）
    return (path in _PUBLIC_EXACT or path.startswith("/icon-")
            or path.startswith("/skin/") or path.startswith("/s/"))


# ---------------------------------------------------------------- 缓存策略
# 真·外壳（每次都要最新、体积也都很小）：绝不缓存。
_NOSTORE = {"/", "/index.html", "/login", "/register", "/forgot", "/admin"}
# 会变但可校验的资源：允许缓存，但每次带 ETag 回源校验（改了 200、没改 304）。
# 比 no-store 省一整份下载，又绝不会发旧的 —— Cloudflare 也会照 no-cache 回源校验。
# （/js/app.bundle.js 不在此列：它带内容哈希版本号，走 immutable 长缓存，见下方路由。）
_REVALIDATE = {"/style.css", "/sw.js", "/manifest.webmanifest"}


@app.after_request
def _cache_policy(resp):
    p = request.path
    if "immutable" in resp.headers.get("Cache-Control", ""):
        return resp                                   # bundle 自己设了长缓存，别覆盖
    if p in _NOSTORE:
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        resp.headers.pop("Expires", None)
    elif p in _REVALIDATE or (p.startswith("/js/") and p != "/js/app.bundle.js"):
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers.pop("Expires", None)
    return resp


# ---------------------------------------------------------------- gzip 压缩
# waitress 不压，Cloudflare 也只在它那段压；直连（App / 桌面壳 / 内网）时就是裸传。
# 这里在应用层压文本类响应：js bundle 636KB→190KB、style.css 200KB→46KB、
# 大 JSON（如 /api/review/today 80KB）也一并受益。二进制（图片/PDF）与 Range 不碰。
_GZIP_TYPES = {"text/html", "text/css", "application/javascript", "text/javascript",
               "application/json", "image/svg+xml", "text/plain"}


@app.after_request
def _compress(resp):
    if resp.headers.get("Content-Encoding"):
        return resp                                   # 已压过（如 bundle 路由自己压的）
    if resp.status_code != 200 or resp.headers.get("Content-Range"):
        return resp                                   # 304 / 206(Range) / 报错 都别动
    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
    if ctype not in _GZIP_TYPES or "gzip" not in request.headers.get("Accept-Encoding", ""):
        return resp
    resp.direct_passthrough = False                   # 静态文件是流式的，先关掉才能读出来
    data = resp.get_data()
    if len(data) < 600:
        return resp                                   # 太小压了不划算
    gz = gzip.compress(data, 6)
    if len(gz) >= len(data):
        return resp
    resp.set_data(gz)
    resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Content-Length"] = str(len(gz))
    resp.headers.add("Vary", "Accept-Encoding")
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


# 启动时预热打包：能拼就启用（首页发一个 bundle 标签），拼不了就退回逐个脚本。
try:
    assets.warm()
    _BUNDLE_OK = True
except Exception as _e:   # noqa: BLE001 —— 打包只是加速，出岔子也不能挡住应用启动
    _BUNDLE_OK = False
    print(" * [assets] 前端打包未启用，退回逐个脚本：", _e)


@app.route("/js/app.bundle.js")
def js_bundle():
    """56 个 js 合成的一个 bundle：带内容哈希 ETag + gzip，走 immutable 长缓存。"""
    js, js_gz, etag = assets.bundle()
    if etag and etag in request.headers.get("If-None-Match", ""):
        resp = app.response_class(status=304)
    elif "gzip" in request.headers.get("Accept-Encoding", ""):
        resp = app.response_class(js_gz, mimetype="application/javascript")
        resp.headers["Content-Encoding"] = "gzip"
    else:
        resp = app.response_class(js, mimetype="application/javascript")
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.headers["Vary"] = "Accept-Encoding"
    return resp


@app.route("/")
def index():
    if _BUNDLE_OK:
        try:
            return app.response_class(assets.index_html(), mimetype="text/html")
        except Exception:   # noqa: BLE001 —— 拼接万一出错，退回原始 index.html 照样能用
            pass
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
