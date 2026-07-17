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
from datetime import datetime

from flask import (Flask, jsonify, redirect, request, session,
                   send_file, send_from_directory)

# ---- reportlab (PDF) ----
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)
from reportlab.lib.styles import ParagraphStyle

from mods.ai import _ai_call_or_error
from mods.pdfkit import PDF_FONT, ensure_pdf_font
from schema import init_db
from core import (ALL_BOARDS, BASE, CFG, SECTIONS, STATIC, UPLOADS, _truthy,
                  close_db, get_db, uid, users_count)
from mods.classics_lookup import bp as classics_lookup_bp
from mods.dailytest import bp as dailytest_bp
from mods.docqa import bp as docqa_bp
from mods.todos import bp as todos_bp
from mods.attach import bp as attach_bp
from mods.auth import bp as auth_bp
from mods.me import bp as me_bp
from mods.zinnia import bp as zinnia_bp
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
app.secret_key = CFG["secret_key"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
    SEND_FILE_MAX_AGE_DEFAULT=0,  # 静态文件不长期缓存，浏览器每次校验，避免旧样式
)
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
app.register_blueprint(attach_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(me_bp)
app.register_blueprint(zinnia_bp)
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
# 已拆到 mods/auth.py。

# ---------------------------------------------------------------- 当前用户/板块
# 已拆到 mods/me.py。

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
# 已拆到 mods/zinnia.py。

# ---------------------------------------------------------------- 理论基础（马原/毛中特/习思想）
# 已拆到 mods/theory.py。

# ---------------------------------------------------------------- AI 附件文本提取（图片OCR/文件抽取）
# 已拆到 mods/attach.py。

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
