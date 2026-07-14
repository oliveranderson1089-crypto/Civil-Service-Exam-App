#!/usr/bin/env python3
"""公考助手 —— 后端服务（多用户）

- 行测 / 申论 两大板块，下设若干小板块
- 言语理解与表达：成语/词语积累（拼音+释义+PDF 导出）
- 每个板块：资料库（上传图片/文档/网页，应用内直接查看，Office 自动转 PDF）
- 多用户 + 密保问题找回密码 + 管理员后台
"""
import base64
import hashlib
import io
import json
import math
import os
import random
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta

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
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif",
             ".heic", ".heif", ".tif", ".tiff", ".avif"}


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


def ai_chat(messages, temperature=0.4, max_tokens=1600, timeout=120, json_mode=False):
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
    payload = {"model": conf["model"], "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens, "stream": False}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + conf["key"],
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------- 视觉模型（智谱 GLM-4.6V，OpenAI 兼容）
# DeepSeek 没有视觉，图片相关（拍照识题、图形推理、图片附件）走这里。文字任务仍走 DeepSeek。
def _vision_conf():
    return {
        "base": (CFG.get("vision_base") or "").rstrip("/"),
        "key": CFG.get("vision_key") or "",
        "model": CFG.get("vision_model") or "glm-4.6v",       # 旗舰：图形推理这类硬任务
        "free": CFG.get("vision_model_free") or "",           # 免费 flash：读图/OCR 足够
    }


def vision_configured():
    c = _vision_conf()
    return bool(c["key"] and c["base"])


def _img_data_url(path, maxpx=1600):
    """读图 → 摆正/压到合理尺寸 → base64 data URL（省流量、够清晰）。"""
    from PIL import Image, ImageOps
    im = Image.open(path)
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    w, h = im.size
    if max(w, h) > maxpx:
        s = maxpx / float(max(w, h))
        im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def vision_chat(text, images, prefer="free", temperature=0.2, max_tokens=1500, timeout=90, json_mode=False):
    """智谱视觉对话。images 为文件路径或 data-url 列表。
    prefer='free' 先用免费 flash（省钱、读图够用），429/失败自动退到旗舰 glm-4.6v。"""
    conf = _vision_conf()
    if not conf["key"] or not conf["base"]:
        raise RuntimeError("视觉模型未配置")
    content = [{"type": "text", "text": text}]
    for im in images:
        u = im if isinstance(im, str) and im.startswith("data:") else _img_data_url(im)
        content.append({"type": "image_url", "image_url": {"url": u}})
    url = conf["base"] + ("" if conf["base"].endswith("/chat/completions") else "/chat/completions")
    order = ([conf["free"], conf["model"]] if prefer == "free" and conf["free"]
             else [conf["model"]] + ([conf["free"]] if conf["free"] and conf["free"] != conf["model"] else []))
    last = "未知错误"
    for model in [m for m in order if m]:
        for attempt in range(3):
            payload = {"model": model, "messages": [{"role": "user", "content": content}],
                       "temperature": temperature, "max_tokens": max_tokens, "stream": False}
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={
                "Content-Type": "application/json", "Authorization": "Bearer " + conf["key"]})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    d = json.loads(r.read().decode("utf-8"))
                return (d["choices"][0]["message"]["content"] or "").strip()
            except urllib.error.HTTPError as e:
                last = "HTTP %d" % e.code
                if e.code == 429 and attempt < 2:
                    time.sleep(2 + attempt * 2)
                    continue
                break     # 其它错误：换下一个模型再试
            except Exception as e:
                last = str(e)
                time.sleep(1)
                continue
    raise RuntimeError("视觉识别失败（%s）" % last)


VISION_OCR_PROMPT = (
    "请把这张图片里的文字**原样转写**出来：题干、选项(A/B/C/D)、数字、数学式、标点都要，按阅读顺序分行。"
    "若有图形/表格但没有文字，用【图形】【表格】占位标注。"
    "只输出图片中的文字内容，不要解释、不要作答、不要加任何前后缀。")


def vision_ocr(path):
    """用视觉模型把图片转写成文字（手写、排版、公式都比 tesseract 强）。"""
    return vision_chat(VISION_OCR_PROMPT, [path], prefer="free", temperature=0.1, max_tokens=1800)


# ---------------------------------------------------------------- 数据库
def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DB, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
    return db


@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def _cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}


# 应用文上位词起步词库：把口语/具体写法归纳为公文规范上位提法
# (场景, 规范上位表述, 适用文种, 用法说明, 例句)
_GONGWEN_SEED = [
    ("开头·缘由（依据）", "为深入贯彻…、为进一步…、为切实…、根据…精神、按照…部署、结合…实际",
     "通知/通报/报告/意见", "开头交代行文缘由，先亮依据再讲目的，不要直接铺陈内容。",
     "为深入贯彻绿色发展理念、进一步改善城乡人居环境，结合我市实际，现就开展垃圾分类工作通知如下。"),
    ("开头·目的", "旨在…、以…为目标、着力…、致力于…、力争…",
     "通知/意见/倡议书", "承接缘由，点明要达到的效果，动词开头更有力。",
     "旨在形成全社会共同参与的良好氛围，着力提升基层治理效能。"),
    ("过渡·引出事项", "现将有关事项通知如下、现提出如下意见、具体安排如下、现将有关情况报告如下",
     "通知/意见/报告", "缘由与正文之间的固定过渡句，一句收束、引出下文分条。",
     "现将有关事项通知如下："),
    ("主体·工作举措", "健全…机制、完善…制度、创新…方式、强化…保障、压实…责任、凝聚…合力",
     "工作方案/意见/讲话", "写对策/举措时的动宾规范搭配，避免“搞好、弄好”这类口语。",
     "健全联防联控机制，压实属地管理责任，凝聚多方参与合力。"),
    ("主体·工作成效", "取得显著成效、实现新突破、迈上新台阶、亮点纷呈、由…向…转变、提质增效",
     "总结/报告/推荐材料", "写成绩时的上位概括词，配数据更有说服力。",
     "各项工作取得显著成效，群众满意度实现新突破。"),
    ("主体·存在问题", "仍存在短板、有待加强、亟需破解、还不够…、尚未根本扭转、存在…的问题",
     "报告/分析/自查", "客观指出不足的委婉规范说法，先肯定再指出。",
     "个别环节衔接仍存在短板，长效机制有待进一步加强。"),
    ("主体·分条领起", "一是…二是…三是…、其一…其二…、首先…其次…再次…、坚持…、突出…、注重…",
     "意见/方案/讲话", "分条作答的领起词，同一份材料内保持句式一致。",
     "一是加强组织领导，二是细化任务分工，三是强化督导考核。"),
    ("结尾·号召（倡议）", "让我们…、携手…、共同…、从我做起、从现在做起、以实际行动…",
     "倡议书/演讲稿", "倡议、演讲类的结尾动员语，有感染力、有画面感。",
     "让我们携手行动起来，从点滴做起，共建美丽家园。"),
    ("结尾·要求（通知）", "请…遵照执行、请…抓好落实、请…及时…、务必…、确保…",
     "通知/通报", "布置类文书的结尾要求语，对象明确、要求具体。",
     "请各单位高度重视，结合实际抓好落实，确保各项任务落到实处。"),
    ("结尾·收束（报告/请示）", "特此报告、特此通知、特此函告、以上意见妥否，请批示、当否，请示",
     "报告/请示/函", "上行/平行文的固定收束语，用错文种是硬伤。",
     "以上报告妥否，请批示。"),
    ("称谓·抬头落款", "各…、全体…、尊敬的…、此致敬礼、特此、（落款：单位+日期）",
     "通知/倡议书/书信", "格式要素，抬头顶格、落款右对齐、日期写全。",
     "各县（区）人民政府，市政府各部门："),
    ("态度·重视强调", "高度重视、充分认识…的重要性、切实增强…的自觉、深刻领会、扛牢…责任",
     "讲话/意见/通知", "强调重要性时的规范表述，避免“很重要、要注意”。",
     "各级各部门要充分认识此项工作的重要性和紧迫性。"),
    ("数据·概括表述", "同比增长…、覆盖率达…、惠及…群众、办结…件、压缩…时间、下降…个百分点",
     "总结/报告/推荐材料", "用数据说话时的规范句式，动词+数据，别堆形容词。",
     "累计惠及群众12万人次，平均办理时限压缩60%。"),
    ("分析·原因归纳", "根本原因在于…、既有…也有…、主观上…客观上…、深层次…、既受…影响，又…",
     "综合分析/报告", "综合分析题挖原因的规范框架，分层次、分主客观。",
     "问题的根源，既有制度设计上的不完善，也有执行环节的不到位。"),
    ("影响·意义表述", "有利于…、为…提供…、对…具有重要意义、是…的必然要求、是…的重要举措",
     "综合分析/讲话", "谈意义、影响时的上位句式，正向排比更饱满。",
     "此举有利于优化营商环境，为高质量发展提供有力支撑。"),
    ("对策·落实保障", "加强组织领导、明确责任分工、加大投入力度、强化督导考核、注重宣传引导、建立长效机制",
     "对策题/方案/意见", "提对策的“万能”保障维度，按“人财物、督宣制”展开。",
     "要加强组织领导，明确责任分工，建立常态化督导考核机制。"),
]


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
        -- 错题本
        CREATE TABLE IF NOT EXISTS wrong_questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            board TEXT, question TEXT, image TEXT, answer TEXT,
            qtype TEXT, points TEXT, method TEXT, skill TEXT, steps TEXT,
            note TEXT, starred INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_wq_user ON wrong_questions(user_id, board);
        -- 各板块基础知识点：AI 生成的概览(全局共享缓存) + 用户补充(按人)
        CREATE TABLE IF NOT EXISTS board_kb(
            board TEXT PRIMARY KEY, content TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS board_points(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, board TEXT, content TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_bp_user ON board_points(user_id, board);
        -- 党建理论学习词典（爬自共产党员网 12371.cn，全局共享）
        CREATE TABLE IF NOT EXISTS party_dict(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cat TEXT, term TEXT, content TEXT, url TEXT, ord INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_pd_cat ON party_dict(cat);
        -- 词典未收录的词/成语：AI 解释后全局缓存，lookup 也会命中（生成一次全站可查）
        CREATE TABLE IF NOT EXISTS ci_ai(
            word TEXT PRIMARY KEY, pinyin TEXT, category TEXT, explanation TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 每日时政：爬虫抓取 + AI 处理（全局共享，定时后台跑，省 token）
        CREATE TABLE IF NOT EXISTS news_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, url TEXT UNIQUE, source TEXT, pub_date TEXT,
            content TEXT, ai_summary TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 时政要文库：重要文件全文 + AI 政策解读（全局共享）
        CREATE TABLE IF NOT EXISTS policy_docs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, category TEXT, source_url TEXT,
            content TEXT, interpretation TEXT, ord INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 每日时政收藏（按人）
        CREATE TABLE IF NOT EXISTS news_stars(
            user_id INTEGER NOT NULL, news_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, news_id)
        );
        -- 每日写作素材（人物事例/具体事例/理论论据/衔接表达）：与微信 08:00 推送共用
        -- 同一份生成结果（~/.openclaw/kaogong-cache/*.txt），App 端解析入库展示
        CREATE TABLE IF NOT EXISTS sucai_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, kind TEXT, topic TEXT, content TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(date, kind, content)
        );
        CREATE INDEX IF NOT EXISTS idx_sc_date ON sucai_items(date);
        -- 专项练：资料分析/判断推理/数量关系这三块靠**练**提分（有固定题型、有秒杀技巧、要计时），
        -- 不像常识靠背。每做一题记一条，用来算「哪个题型最弱、平均要花多久」，弱的排前面。
        CREATE TABLE IF NOT EXISTS drill_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, board TEXT, qtype TEXT,
            correct INTEGER DEFAULT 0, seconds REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_dr_u ON drill_log(user_id, board, qtype);
        -- 每日新闻视频：抓 → AI 按公考价值筛 → 只留最值得看的几条。
        -- 信源只用白名单里的官方媒体（央视网 / 川观新闻）—— 没法自动确认「某个博主是不是真的」，
        -- 所以不接受任意来源，那等于把把关的活儿丢给用户自己。
        CREATE TABLE IF NOT EXISTS video_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board TEXT,              -- 国内 / 国际 / 四川
            column_name TEXT,        -- 栏目（新闻联播 / 今日关注 / 川观新闻…）
            source TEXT,             -- 信源（央视网 · CCTV-1 …）
            title TEXT, url TEXT, cover TEXT, duration TEXT,
            pub_date TEXT,
            brief TEXT,              -- 本期内容提要（央视网自带，是筛选的依据）
            why TEXT,                -- AI 说的「为什么值得看」（考点在哪）
            tags TEXT, score INTEGER DEFAULT 5,
            guid TEXT UNIQUE,        -- 同一条视频不重复收
            pick_date TEXT,          -- 哪天选中的
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_vid ON video_items(pick_date DESC, board);
        CREATE TABLE IF NOT EXISTS video_stars(
            user_id INTEGER NOT NULL, video_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, video_id)
        );
        -- 专项练题库：常识/政治理论/言语这三块出不了程序化题（考的是知识，不是构造），
        -- 只能让 AI 出。但每次现出要等 20 秒 —— 所以**攒进题库**，用的时候直接取，
        -- 不够了再后台补。按 (板块, 题型, 难度) 分桶。
        CREATE TABLE IF NOT EXISTS drill_bank(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board TEXT, qtype TEXT, level TEXT,
            q TEXT, options TEXT, answer TEXT, explain TEXT, tip TEXT, source TEXT,
            sig TEXT UNIQUE,                 -- 题干指纹，防止重复题
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_bank ON drill_bank(board, qtype, level);
        -- 一次专项练的完整记录（题目 + 我的作答 + 用时），不做完就丢
        CREATE TABLE IF NOT EXISTS drill_records(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            board TEXT, qtype TEXT, level TEXT, mode TEXT,
            total INTEGER, correct INTEGER, seconds REAL,
            items TEXT, answers TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_drrec ON drill_records(user_id, id DESC);
        -- 小题训练（找点 + 写点）：归纳概括/综合分析/提出对策的共同难点都是「从材料里找要点」。
        -- 要能判「找漏了/找错了/找重了」，就必须存下**采分点 ↔ 材料原文的逐字依据**：
        -- points = [{point:概括后的要点, evidence:逐字来自材料的原句, score:分值}]
        -- 没有 evidence 就只能凭感觉批，那等于没批。
        CREATE TABLE IF NOT EXISTS find_papers(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            qtype TEXT, type_name TEXT, stem TEXT, requirement TEXT,
            full INTEGER, word_min INTEGER, word_max INTEGER,
            material TEXT, points TEXT, source TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS find_records(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            paper_id INTEGER NOT NULL,
            marks TEXT,          -- 我勾画的句子下标
            find_result TEXT,    -- 找点判定结果
            answer TEXT,         -- 我写的点子
            grade TEXT,          -- 写点批改结果
            score REAL, full INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 常考收藏：六个小模块的数据来自三张不同的表（changkao_items / hyper_items / classics），
        -- 所以这里按 (board, item_id) 存，并把标题正文快照下来 —— 收藏列表要能直接显示，
        -- 不用回头去三张表里各查一遍。
        CREATE TABLE IF NOT EXISTS ck_stars(
            user_id INTEGER NOT NULL, board TEXT NOT NULL, item_id INTEGER NOT NULL,
            title TEXT, content TEXT, note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, board, item_id)
        );
        -- 成文：把散落的素材真正写成一篇大作文（不然素材背了也不会用）
        --   mode=daily    按「素材日期」成文，一天一篇，用当天更新的那批素材
        --   mode=compose  综合应用，AI 自己选题，跨全部素材库挑最合适的
        --   mode=yingyong 应用文，导航位先占着，生成逻辑待定
        CREATE TABLE IF NOT EXISTS daily_essays(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL, date TEXT NOT NULL,
            topic TEXT, title TEXT, outline TEXT, content TEXT,
            words INTEGER DEFAULT 0,
            used TEXT,            -- JSON：真正用进文章的素材（服务端逐条核对过）
            note TEXT,            -- AI 的选材说明
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(mode, date)
        );
        -- 常识积累（7板块×专题，条目由 AI 生成/每日更新/新法跟踪，全局共享）
        CREATE TABLE IF NOT EXISTS changshi_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board TEXT, topic TEXT, title TEXT, content TEXT,
            date TEXT, source TEXT DEFAULT 'ai',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(board, topic, title)
        );
        CREATE INDEX IF NOT EXISTS idx_cs_bt ON changshi_items(board, topic);
        -- 题库（四川省考卷面结构，每周自动更新两次）
        CREATE TABLE IF NOT EXISTS quiz_sets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, kind TEXT DEFAULT '行测',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS quiz_questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, set_id INTEGER, seq INTEGER,
            module TEXT, qtype TEXT, material TEXT, question TEXT,
            options TEXT, answer TEXT, explanation TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_qq_set ON quiz_questions(set_id, seq);
        -- 共享待办（两账号互相监督，全局共享）
        CREATE TABLE IF NOT EXISTS shared_todos(
            id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT,
            created_by TEXT, done INTEGER DEFAULT 0, done_by TEXT, done_at TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 每日任务模板（用户自定义，每天生成当日任务）
        CREATE TABLE IF NOT EXISTS task_templates(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            text TEXT, sort INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 每日任务完成记录（按天）
        CREATE TABLE IF NOT EXISTS task_done(
            user_id INTEGER NOT NULL, tpl_id INTEGER NOT NULL, date TEXT NOT NULL,
            done_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, tpl_id, date)
        );
        -- 古诗文每日推荐（全局，按日期）
        CREATE TABLE IF NOT EXISTS classic_daily(
            date TEXT PRIMARY KEY, classic_id INTEGER, apply TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS quiz_answers(
            user_id INTEGER NOT NULL, set_id INTEGER, qid INTEGER NOT NULL,
            choice TEXT, correct INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, qid)
        );
        -- 习语金句（学习强国风格：每日从习近平讲话数据库真实原文提炼，分八类）
        CREATE TABLE IF NOT EXISTS xiyu_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, category TEXT, quote TEXT, note TEXT, source_url TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(quote)
        );
        -- 经典著作（毛泽东选集等）：全文 + AI 解读缓存
        CREATE TABLE IF NOT EXISTS works(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book TEXT, ord INTEGER, title TEXT, content TEXT, interpretation TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 全局 AI 会话中心（仿 Claude：项目 / 会话 / 消息）
        CREATE TABLE IF NOT EXISTS ai_projects(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            name TEXT, instructions TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS ai_chats(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            project_id INTEGER, title TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS ai_msgs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
            role TEXT, content TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_aim_chat ON ai_msgs(chat_id);
        -- 遗忘曲线复习进度（艾宾浩斯间隔：1/2/4/7/15/30/60 天）
        CREATE TABLE IF NOT EXISTS review_state(
            user_id INTEGER NOT NULL, kind TEXT NOT NULL, item_id INTEGER NOT NULL,
            stage INTEGER DEFAULT 0, next_due TEXT, last_done TEXT,
            PRIMARY KEY(user_id, kind, item_id)
        );
        -- 申论概括句积累：每日由当天时政素材生成（全局共享，按日期查看）
        CREATE TABLE IF NOT EXISTS gaikuo_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, topic TEXT, raw TEXT, sentence TEXT, tip TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_gk_date ON gaikuo_items(date);
        """
    )
    # entries 老表可能缺 user_id 列（先补列，再建索引）
    if "user_id" not in _cols(con, "entries"):
        con.execute("ALTER TABLE entries ADD COLUMN user_id INTEGER")
    con.execute("CREATE INDEX IF NOT EXISTS idx_entries_user ON entries(user_id)")
    # ai_chats 补 starred（置顶）
    if "starred" not in _cols(con, "ai_chats"):
        con.execute("ALTER TABLE ai_chats ADD COLUMN starred INTEGER DEFAULT 0")
    # 应用文比大作文多一层：得先有「文种 + 发文场景 + 我是谁 + 写给谁」才谈得上选素材
    if "spec" not in _cols(con, "daily_essays"):
        con.execute("ALTER TABLE daily_essays ADD COLUMN spec TEXT")
    # 每日复习量：一天能背多少是因人而异的，原来写死 120 条（只能改环境变量），堆起来就不想背了
    if "rv_limits" not in _cols(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN rv_limits TEXT")
    # 专项练加了难度档，统计要按难度分开（不然入门刷出来的高正确率会盖住真实水平）
    if "level" not in _cols(con, "drill_log"):
        con.execute("ALTER TABLE drill_log ADD COLUMN level TEXT DEFAULT 'mid'")
    # AI 出的题要过**第二个模型的独立核验**才能发给人做（实测抽检：单模型出题一致率只有 89%，
    # 也就是每 9 道就有 1 道值得怀疑；而且真抓到过事实错误 —— 「山水林田湖草沙」那道就是错的）。
    for col, dflt in (("checked", "0"), ("agree", "0"), ("audit_ans", "''"),
                      ("audit_note", "''"), ("flaw", "''")):
        if col not in _cols(con, "drill_bank"):
            con.execute("ALTER TABLE drill_bank ADD COLUMN %s TEXT DEFAULT %s" % (col, dflt))
    # 成语/实词的例句：光有释义记不住怎么用。**先从真实官方语料里找**（人民日报时政、时政要文、
    # 习语金句都是真文本），找到就是真出处；找不到才让 AI 仿写，并**明说是仿写**。
    for col in ("example", "example_src", "confuse"):
        if col not in _cols(con, "changkao_items"):
            con.execute("ALTER TABLE changkao_items ADD COLUMN %s TEXT" % col)
    # 资料库的自定义分类（原来只存在前端内存里，从已有资料反推 → 新建了但还没传东西的分类，重启就没了）
    if "mat_boards" not in _cols(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN mat_boards TEXT")
    # 外观定制：头像 / 应用内壁纸 / 登录页壁纸（存文件名，图片放 uploads/skin/<uid>/）
    for col in ("avatar", "wall_app", "wall_login"):
        if col not in _cols(con, "users"):
            con.execute("ALTER TABLE users ADD COLUMN %s TEXT" % col)
    # ci_ai 结构化：补 出处/例句 列
    for col in ("derivation", "example"):
        if col not in _cols(con, "ci_ai"):
            con.execute("ALTER TABLE ci_ai ADD COLUMN %s TEXT" % col)
    # 视频要能在 APP 里直接播（原来点播放键是往外跳浏览器 —— 桌面版还跳不动）。
    #   kind: 决定用哪种播法 —— cctv=自己拿 mp4 分段放；bili=嵌官方播放器；sc=川观（抓到直链才能放）
    #   play: 抓取时就把播放地址算好存下来，用户点播放时不用现去请求人家的接口（快，也不容易失败）
    for col in ("kind", "play"):
        if col not in _cols(con, "video_items"):
            con.execute("ALTER TABLE video_items ADD COLUMN %s TEXT" % col)
    # 老数据没有 kind：按 guid 的长相反推（BV 开头是 B 站，32 位十六进制是央视，剩下的是川观）
    con.execute("UPDATE video_items SET kind = CASE "
                "WHEN guid LIKE 'BV%' THEN 'bili' "
                "WHEN guid GLOB '[0-9a-f]*' AND length(guid)=32 THEN 'cctv' "
                "ELSE 'sc' END WHERE kind IS NULL OR kind=''")
    # 习语金句：补 关键词/申论运用 列
    for col in ("keyword", "apply"):
        if col not in _cols(con, "xiyu_items"):
            con.execute("ALTER TABLE xiyu_items ADD COLUMN %s TEXT" % col)
    # 上位词：补「典故/来源」列（AI 讲一次就缓存，像古诗文赏析那样点开即看）
    if "story" not in _cols(con, "hyper_items"):
        con.execute("ALTER TABLE hyper_items ADD COLUMN story TEXT")
    # 常考成语/实词：补「典故」列（看懂来历自然就记住了，不用死背）
    if "story" not in _cols(con, "changkao_items"):
        con.execute("ALTER TABLE changkao_items ADD COLUMN story TEXT")
    # 每日时政：补「重点标注」列（在原文里划出考点，不用通读全文）
    if "marks" not in _cols(con, "news_items"):
        con.execute("ALTER TABLE news_items ADD COLUMN marks TEXT")
    # 古诗文考频排序
    if "freq" not in _cols(con, "classics"):
        con.execute("ALTER TABLE classics ADD COLUMN freq INTEGER DEFAULT 0")
        con.execute("CREATE INDEX IF NOT EXISTS idx_cls_freq ON classics(freq)")
    # 衔接表达例句
    if "example" not in _cols(con, "sucai_items"):
        con.execute("ALTER TABLE sucai_items ADD COLUMN example TEXT")
    # 每日一诗：常识判断考点
    if "common" not in _cols(con, "classic_daily"):
        con.execute("ALTER TABLE classic_daily ADD COLUMN common TEXT")
    # 首页卡片自定义排序（拖拽保存，JSON 数组）
    if "home_order" not in _cols(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN home_order TEXT")
    # 各功能页卡片排序（JSON 对象：网格键→顺序数组）
    if "ui_orders" not in _cols(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN ui_orders TEXT")
    con.executescript("""
        -- 互监待办：每人独立打勾（旧 shared_todos.done 保留兼容）
        CREATE TABLE IF NOT EXISTS shared_todo_done(
            todo_id INTEGER NOT NULL, user_id INTEGER NOT NULL, username TEXT,
            done_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(todo_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS todo_members(
            user_id INTEGER PRIMARY KEY,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 组队（互监）：邀请制，一个用户同一时间只在一个队里
        CREATE TABLE IF NOT EXISTS teams(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS team_members(
            team_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            joined_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(team_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS team_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_uid INTEGER, to_uid INTEGER, kind TEXT,   -- join 组队 / disband 解散
            team_id INTEGER, status TEXT DEFAULT 'pending', -- pending/accepted/rejected/cancelled
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_treq ON team_requests(to_uid, status);
        -- 常考（高频考点合集）
        CREATE TABLE IF NOT EXISTS changkao_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board TEXT, title TEXT, content TEXT, note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(board, title)
        );
        CREATE INDEX IF NOT EXISTS idx_ck_board ON changkao_items(board);
        -- 上位词积累（逻辑填空「概括词/上位词」提示）
        CREATE TABLE IF NOT EXISTS hyper_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hyper TEXT UNIQUE, subs TEXT, note TEXT, example TEXT,
            source TEXT DEFAULT 'ai',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 应用文上位词（公文规范上位表述：口语/具体表述 → 规范提法，按场景归类）
        CREATE TABLE IF NOT EXISTS gongwen_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scene TEXT UNIQUE, phrases TEXT, doctype TEXT, note TEXT, example TEXT,
            source TEXT DEFAULT 'seed',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 理论基础（马原/毛中特/习思想…）
        CREATE TABLE IF NOT EXISTS theory_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board TEXT, topic TEXT, title TEXT, content TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(board, title)
        );
        CREATE INDEX IF NOT EXISTS idx_th_board ON theory_items(board, topic);
        -- 申论 AI 逐点批改记录
        CREATE TABLE IF NOT EXISTS shenlun_grade(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            qtype TEXT, type_name TEXT, question TEXT, material TEXT, answer TEXT,
            score REAL, full INTEGER, result TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_sl_user ON shenlun_grade(user_id, id DESC);
        -- 上传的申论真题卷（材料 + 各小题）
        CREATE TABLE IF NOT EXISTS shenlun_papers(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            title TEXT, material TEXT, source TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS shenlun_questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id INTEGER NOT NULL,
            seq INTEGER, qtype TEXT, type_name TEXT, stem TEXT, requirement TEXT,
            full INTEGER, word_min INTEGER, word_max INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_slq_paper ON shenlun_questions(paper_id, seq);
        -- 站内消息：内容库有更新、复习/任务到点，都在这里提醒，点开直达
        CREATE TABLE IF NOT EXISTS notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            kind TEXT, dkey TEXT, title TEXT, body TEXT, link TEXT,
            read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, kind, dkey)
        );
        CREATE INDEX IF NOT EXISTS idx_ntf_user ON notifications(user_id, read, id DESC);
        -- 后台长任务（文档识题解析、范文生成）：前端轮询进度
        CREATE TABLE IF NOT EXISTS bg_tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            kind TEXT, title TEXT, status TEXT DEFAULT 'running',
            progress INTEGER DEFAULT 0, total INTEGER DEFAULT 0,
            message TEXT, result_id INTEGER, extra TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_bg_user ON bg_tasks(user_id, id DESC);
        -- 范文推荐：一套仿真卷（材料按真题字数规格） + 各题完整参考答案
        CREATE TABLE IF NOT EXISTS essay_papers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT UNIQUE, spec TEXT, title TEXT, material TEXT, words INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS essays(
            id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id INTEGER NOT NULL,
            seq INTEGER, qtype TEXT, type_name TEXT, stem TEXT,
            full INTEGER, word_min INTEGER, word_max INTEGER,
            answer TEXT, answer_words INTEGER, outline TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_essay_paper ON essays(paper_id, seq);
        -- 文档识题：从讲义/资料里抽出的例题 + AI 答案解析
        CREATE TABLE IF NOT EXISTS doc_questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
            page INTEGER, seq INTEGER, stem TEXT, options TEXT,
            answer TEXT, explain TEXT, qtype TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_dq_task ON doc_questions(task_id, page, seq);
        -- 备考规划：一份个人档案 + 每天一份 AI 排的学习计划
        CREATE TABLE IF NOT EXISTS plan_profile(
            user_id INTEGER PRIMARY KEY,
            exam TEXT, exam_date TEXT, minutes INTEGER DEFAULT 120,
            weak TEXT, note TEXT,
            summary TEXT, summary_date TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS plan_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            date TEXT NOT NULL, seq INTEGER, title TEXT, module TEXT,
            minutes INTEGER, reason TEXT, link TEXT,
            done INTEGER DEFAULT 0, done_at TEXT, source TEXT DEFAULT 'ai',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_plan_user ON plan_items(user_id, date, seq);
        -- 每日计划快照：重排/换天前把旧计划存一份，方便回看和被覆盖后还能找回
        CREATE TABLE IF NOT EXISTS plan_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            date TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now','localtime')),
            summary TEXT, minutes_total INTEGER, done_n INTEGER, total INTEGER,
            items_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_plan_log ON plan_log(user_id, date DESC, id DESC);
        -- 每日巩固测试：按当天学的内容出一份小测，按 用户+日期 缓存
        CREATE TABLE IF NOT EXISTS daily_quiz(
            user_id INTEGER NOT NULL, date TEXT NOT NULL,
            questions_json TEXT, created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, date)
        );
        -- 巩固测试记录：每交一次卷存一条，可回看
        CREATE TABLE IF NOT EXISTS dtest_records(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            date TEXT, score INTEGER, total INTEGER, detail_json TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_dtrec ON dtest_records(user_id, id DESC);
        -- 学习天数：完成备考规划/互监待办的当天记一笔，用来算连续与累计
        CREATE TABLE IF NOT EXISTS study_days(
            user_id INTEGER NOT NULL, date TEXT NOT NULL,
            PRIMARY KEY(user_id, date)
        );
        -- 资料库共享：把某份资料共享给指定的人（队友），对方在资料库看得到「共享给我的」
        CREATE TABLE IF NOT EXISTS material_shares(
            material_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, to_user INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(material_id, to_user)
        );
        CREATE INDEX IF NOT EXISTS idx_mshare_to ON material_shares(to_user);
        -- 通用「划重点」缓存：按内容哈希存，同一段内容全局只算一次（哪个模块打开都直接命中）
        CREATE TABLE IF NOT EXISTS marks_cache(
            ref TEXT PRIMARY KEY, scope TEXT, data_json TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 书签：看到哪了（阅读类页面自动记位置，也可手动打点）
        CREATE TABLE IF NOT EXISTS bookmarks(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            kind TEXT NOT NULL, ref TEXT NOT NULL, title TEXT, pos REAL DEFAULT 0, note TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, kind, ref)
        );
        -- 40 天冲刺路线图：阶段/每日定额/正确率目标，规划助手每天照它排任务
        CREATE TABLE IF NOT EXISTS plan_roadmap(
            user_id INTEGER PRIMARY KEY, start_date TEXT, days INTEGER DEFAULT 40,
            data_json TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 草稿本（错题本里，平时打草稿用）：笔迹按向量存，不做识别
        CREATE TABLE IF NOT EXISTS drafts(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            title TEXT, data_json TEXT, pages INTEGER DEFAULT 1, thumb TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_drafts ON drafts(user_id, updated_at DESC);
    """)
    # 备考规划：把 AI 给出的今日重点存下来，刷新后还能看到
    for col in ("summary", "summary_date"):
        if col not in _cols(con, "plan_profile"):
            con.execute("ALTER TABLE plan_profile ADD COLUMN %s TEXT" % col)
    # 批改记录挂到真题卷上，并记下字数与题目要求的字数区间
    for col, typ in (("paper_id", "INTEGER"), ("question_id", "INTEGER"),
                     ("words", "INTEGER"), ("word_min", "INTEGER"), ("word_max", "INTEGER"),
                     ("requirement", "TEXT")):
        if col not in _cols(con, "shenlun_grade"):
            con.execute("ALTER TABLE shenlun_grade ADD COLUMN %s %s" % (col, typ))
    # 互监待办：交叉确认——记录这个勾是谁打的（只能由搭档打）
    for col, typ in (("by_user", "INTEGER"), ("by_name", "TEXT")):
        if col not in _cols(con, "shared_todo_done"):
            con.execute("ALTER TABLE shared_todo_done ADD COLUMN %s %s" % (col, typ))
    # 互监待办：来源标记——把「备考规划」的今日计划同步进来给搭档监督
    for col, typ in (("source", "TEXT"), ("src_uid", "INTEGER"), ("plan_date", "TEXT"),
                     ("team_id", "INTEGER")):
        if col not in _cols(con, "shared_todos"):
            con.execute("ALTER TABLE shared_todos ADD COLUMN %s %s" % (col, typ))
    # 学习天数回填：从历史完成记录补一次（备考规划完成 + 互监任务被确认）
    try:
        if not con.execute("SELECT COUNT(*) FROM study_days").fetchone()[0]:
            con.execute("INSERT OR IGNORE INTO study_days(user_id,date) "
                        "SELECT user_id, date(done_at) FROM plan_items "
                        "WHERE done=1 AND done_at IS NOT NULL")
            con.execute("INSERT OR IGNORE INTO study_days(user_id,date) "
                        "SELECT user_id, date(done_at) FROM shared_todo_done "
                        "WHERE user_id IS NOT NULL AND done_at IS NOT NULL")
    except Exception:
        pass
    # 老数据迁移：把已有的 todo_members 成员组成一个队，现有待办归到这个队
    try:
        if not con.execute("SELECT COUNT(*) FROM teams").fetchone()[0]:
            old = [r[0] for r in con.execute("SELECT user_id FROM todo_members ORDER BY user_id LIMIT 2")]
            if len(old) >= 2:
                tid = con.execute("INSERT INTO teams DEFAULT VALUES").lastrowid
                for u in old:
                    con.execute("INSERT OR IGNORE INTO team_members(team_id,user_id) VALUES(?,?)", (tid, u))
                con.execute("UPDATE shared_todos SET team_id=? WHERE team_id IS NULL", (tid,))
    except Exception:
        pass
    # 老数据迁移：shared_todos.done=1 → 记到完成人名下
    try:
        if not con.execute("SELECT COUNT(*) FROM shared_todo_done").fetchone()[0]:
            for r in con.execute("SELECT id, done_by, done_at FROM shared_todos WHERE done=1").fetchall():
                u = con.execute("SELECT id FROM users WHERE username=?", (r[1],)).fetchone()
                if u:
                    con.execute("INSERT OR IGNORE INTO shared_todo_done(todo_id,user_id,username,done_at) "
                                "VALUES(?,?,?,?)", (r[0], u[0], r[1], r[2]))
    except Exception:
        pass
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

    # 应用文上位词起步词库：口语/具体表述 → 公文规范上位提法，按场景归类
    if con.execute("SELECT COUNT(*) FROM gongwen_items").fetchone()[0] == 0:
        for scene, phrases, doctype, note, example in _GONGWEN_SEED:
            con.execute("INSERT OR IGNORE INTO gongwen_items(scene,phrases,doctype,note,example,source) "
                        "VALUES(?,?,?,?,?,'seed')", (scene, phrases, doctype, note, example))
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
    row = db.execute("SELECT * FROM ci_ai WHERE word=?", (word,)).fetchone()
    if row:
        rk = row.keys()
        info.update(pinyin=row["pinyin"] or to_pinyin(word), category=row["category"] or info["category"],
                    explanation=row["explanation"] or "",
                    derivation=(row["derivation"] if "derivation" in rk else "") or "",
                    example=(row["example"] if "example" in rk else "") or "",
                    source="ai", found=True)
        return info
    info["pinyin"] = to_pinyin(word)
    # 词典都查不到时按长度猜类别：≥4 字多为「词组」（如 生理功能），2-3 字按词语
    if len(word) >= 4 and CJK_RE.match(word):
        info["category"] = "词组"
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
    # 板块支持自定义分类（如「晨读」），不再限定固定板块
    if len(board) > 20:
        return jsonify({"error": "分类名太长"}), 400
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


@app.get("/api/materials/boards")
def material_boards():
    """分类 = 已有资料反推出来的 + 用户自己存下来的。
       只反推的话，新建了但还没往里传东西的分类（如「其它」）重启就没了 —— 这正是踩过的坑。"""
    db = get_db()
    rows = db.execute(
        "SELECT DISTINCT board FROM materials WHERE user_id=? AND board<>'' ORDER BY board", (uid(),)).fetchall()
    boards = [r["board"] for r in rows]
    r = db.execute("SELECT mat_boards FROM users WHERE id=?", (uid(),)).fetchone()
    try:
        for b in json.loads((r["mat_boards"] if r else None) or "[]"):
            if b and b not in boards:
                boards.append(b)
    except Exception:
        pass
    return jsonify({"boards": boards})


@app.get("/api/materials")
def material_list():
    board = (request.args.get("board") or "").strip()
    db = get_db()
    # 自己的 + 队友共享给我的（共享来的标 shared_from，不能改不能删）
    sql = ("SELECT m.*, 0 AS shared, '' AS shared_from FROM materials m WHERE m.user_id=?"
           + (" AND m.board=?" if board else "")
           + " UNION ALL "
           + "SELECT m.*, 1 AS shared, u.username AS shared_from FROM materials m "
             "JOIN material_shares s ON s.material_id=m.id "
             "JOIN users u ON u.id=m.user_id WHERE s.to_user=?"
           + (" AND m.board=?" if board else "")
           + " ORDER BY id DESC")
    args = [uid()] + ([board] if board else []) + [uid()] + ([board] if board else [])
    rows = db.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["viewable"] = (r["ext"] in INLINE_EXT) or (r["ext"] in OFFICE_EXT)
        out.append(d)
    return jsonify({"items": out})


def _get_material(mid):
    """自己的资料，或队友共享给我的（共享来的只读：查看/下载可以，改名删除不行）。"""
    return get_db().execute(
        "SELECT m.* FROM materials m WHERE m.id=? AND ("
        "  m.user_id=? OR EXISTS(SELECT 1 FROM material_shares s "
        "                        WHERE s.material_id=m.id AND s.to_user=?))",
        (mid, uid(), uid())).fetchone()


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


def _clean_ocr(text):
    text = re.sub(r"(?<=[一-鿿，。！？；：、（）《》“”])[ \t]+(?=[一-鿿，。！？；：、（）《》“”])", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _tess(img_path, psm):
    try:
        out = subprocess.run(["tesseract", img_path, "stdout", "-l", "chi_sim+eng",
                              "--oem", "1", "--psm", str(psm)], capture_output=True, timeout=150)
        return _clean_ocr(out.stdout.decode("utf-8", "ignore"))
    except Exception:
        return ""


def _ocr_image(path):
    """预处理+tesseract OCR。兼容 HEIC/RGBA/超大图；单一版面识别不到时换 psm 重试。"""
    proc = None
    try:
        from PIL import Image, ImageOps, ImageFilter
        try:                                   # iPhone HEIC / HEIF
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            pass
        im = Image.open(path)
        im.load()                              # 多帧 GIF/TIFF 只取第一帧
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):     # 透明底 → 铺白，否则变全黑
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im)
        im = im.convert("L")
        w, h = im.size
        if max(w, h) < 2200:                   # 太小 → 放大，提升小字识别率
            sc = min(3.0, 2200.0 / max(w, h))
            im = im.resize((int(w * sc), int(h * sc)), Image.LANCZOS)
        elif max(w, h) > 5000:                 # 太大 → 缩小，避免 tesseract 超时
            sc = 5000.0 / max(w, h)
            im = im.resize((int(w * sc), int(h * sc)), Image.LANCZOS)
        im = ImageOps.autocontrast(im, cutoff=2).filter(ImageFilter.SHARPEN)
        proc = path + ".ocr.png"
        im.save(proc)
    except Exception:
        proc = None
    src = proc or path
    try:
        text = _tess(src, 6)                   # 统一版面（题目/文档截图）
        if len(text) < 8:
            text = _tess(src, 3) or text       # 自动分栏
        if len(text) < 8:
            text = _tess(src, 11) or text      # 稀疏文字（照片/海报）
        return text
    finally:
        if proc:
            try:
                os.remove(proc)
            except Exception:
                pass


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
    t = _extract_text(os.path.join(UPLOADS, str(m["user_id"]), m["stored_name"]), m["ext"])
    if t is None:
        return jsonify({"error": "文件丢失"}), 404
    return jsonify({"text": t})


# 朗读 TTS polyfill：APK 内（有 GongkaoNative 桥）用 Android TTS 实现 window.speechSynthesis，
# 让上传 HTML 里现成的朗读代码无需改动即可发声；普通浏览器不注入、保留原生。
# 注入到 <head> 最前，早于页面脚本执行；回调经 window.top 中转以支持 iframe 内的资料页。
_TTS_POLYFILL = """<script>(function(){
if(!(window.GongkaoNative&&window.GongkaoNative.ttsSpeak))return;
var T=window.top||window;
if(!T.__ttsReg){T.__ttsReg={};T.__ttsEvent=function(id,ev){var u=T.__ttsReg[id];if(!u)return;if(ev==='end'){delete T.__ttsReg[id];if(u.__sp)u.__sp.speaking=false;if(typeof u.onend==='function'){try{u.onend({});}catch(e){}}}};}
function U(t){this.text=t||'';this.rate=1;this.pitch=1;this.volume=1;this.lang='zh-CN';this.onend=null;this.onstart=null;this.onerror=null;this.onboundary=null;this._id='u'+Date.now()+'_'+Math.floor(Math.random()*1e6);this.__sp=null;}
var SP={speaking:false,pending:false,paused:false,
speak:function(u){if(!u||!u.text)return;u.__sp=this;T.__ttsReg[u._id]=u;this.speaking=true;if(typeof u.onstart==='function'){try{u.onstart({});}catch(e){}}try{window.GongkaoNative.ttsSpeak(u._id,String(u.text),u.rate||1);}catch(e){this.speaking=false;if(typeof u.onend==='function'){try{u.onend({});}catch(_){}}}},
cancel:function(){this.speaking=false;T.__ttsReg={};try{window.GongkaoNative.ttsCancel();}catch(e){}},
pause:function(){},resume:function(){},getVoices:function(){return[];}};
window.SpeechSynthesisUtterance=U;window.speechSynthesis=SP;
})();</script>"""


def _inject_tts(html_txt):
    low = html_txt.lower()
    for tag in ("<head", "<html"):
        i = low.find(tag)
        if i >= 0:
            j = html_txt.find(">", i)
            if j >= 0:
                return html_txt[:j + 1] + _TTS_POLYFILL + html_txt[j + 1:]
    return _TTS_POLYFILL + html_txt


def _cacheable(resp, days=30):
    """文件内容不可变（stored_name 是 uuid），让浏览器长期本地缓存。
    用 private：不进 CDN 边缘，避免带登录态的资料被别人按 URL 命中。"""
    resp.headers["Cache-Control"] = "private, max-age=%d" % (days * 86400)
    resp.headers.pop("Expires", None)
    return resp


def _linearized(pdf):
    """线性化（Fast Web View）：xref 前置，配合 Range 让阅读器先出首页再拉后面。
    服务器在家里、上行只有一百多 KB/s，这个优化对大 PDF 是决定性的。"""
    web = os.path.splitext(pdf)[0] + ".web.pdf"
    if os.path.exists(web) and os.path.getmtime(web) >= os.path.getmtime(pdf):
        return web
    try:
        subprocess.run(["qpdf", "--linearize", pdf, web], timeout=180, capture_output=True)
    except Exception:
        return pdf
    return web if os.path.exists(web) and os.path.getsize(web) > 0 else pdf


def _material_pdf(m, path):
    """拿到这份资料对应的 PDF（office 先转换），失败返回 None。"""
    if m["ext"] == ".pdf":
        return path
    if m["ext"] in OFFICE_EXT:
        return _office_to_pdf(path)
    return None


@app.get("/api/materials/<int:mid>/view")
def material_view(mid):
    m = _get_material(mid)
    if not m:
        return "未找到", 404
    path = os.path.join(UPLOADS, str(m["user_id"]), m["stored_name"])
    if not os.path.exists(path):
        return "文件丢失", 404
    ext = m["ext"]
    if ext in OFFICE_EXT:
        pdf = _office_to_pdf(path)
        if not pdf:
            return "文档转换失败，请下载查看", 500
        return _cacheable(send_file(_linearized(pdf), mimetype="application/pdf", as_attachment=False))
    if ext in (".html", ".htm"):
        with open(path, "rb") as fp:
            html_txt = fp.read().decode("utf-8", "ignore")
        return Response(_inject_tts(html_txt), mimetype="text/html; charset=utf-8")
    if ext in TEXT_EXT:
        with open(path, "rb") as fp:
            return Response(fp.read(), mimetype="text/plain; charset=utf-8")
    if ext == ".pdf":
        return _cacheable(send_file(_linearized(path), mimetype="application/pdf",
                                    as_attachment=False, download_name=m["orig_name"]))
    # 图片等：浏览器内联打开
    return _cacheable(send_file(path, as_attachment=False, download_name=m["orig_name"]))


# ---------------------------------------------------------------- 幻灯片播放（PPT/PDF 逐页出图）
def _pages_dir(m):
    d = os.path.join(UPLOADS, str(uid()), ".pages", os.path.splitext(m["stored_name"])[0])
    os.makedirs(d, exist_ok=True)
    return d


@app.get("/api/materials/<int:mid>/pages")
def material_pages(mid):
    """返回总页数；PPT/PDF 才支持幻灯片播放。"""
    m = _get_material(mid)
    if not m:
        return jsonify({"error": "未找到"}), 404
    path = os.path.join(UPLOADS, str(m["user_id"]), m["stored_name"])
    pdf = _material_pdf(m, path) if os.path.exists(path) else None
    if not pdf:
        return jsonify({"pages": 0, "slides": False})
    try:
        out = subprocess.run(["pdfinfo", pdf], capture_output=True, timeout=60)
        txt = out.stdout.decode("utf-8", "ignore")
        n = int(re.search(r"Pages:\s+(\d+)", txt).group(1))
    except Exception:
        return jsonify({"pages": 0, "slides": False})
    return jsonify({"pages": n, "slides": True,
                    "ppt": m["ext"] in (".ppt", ".pptx", ".odp")})


@app.get("/api/materials/<int:mid>/page/<int:n>")
def material_page(mid, n):
    """单页渲染成 JPEG（约 100~200KB），比整份 PDF 小两个数量级，首屏立刻可见。"""
    m = _get_material(mid)
    if not m:
        return "未找到", 404
    if n < 1 or n > 3000:
        return "页码越界", 400
    path = os.path.join(UPLOADS, str(m["user_id"]), m["stored_name"])
    if not os.path.exists(path):
        return "文件丢失", 404
    pdf = _material_pdf(m, path)
    if not pdf:
        return "该格式不支持逐页预览", 400
    dpi = 110 if request.args.get("hd") else 90
    cache = os.path.join(_pages_dir(m), "p%04d_%d.jpg" % (n, dpi))
    if not os.path.exists(cache):
        prefix = cache[:-4]
        try:
            subprocess.run(["pdftoppm", "-jpeg", "-jpegopt", "quality=72",
                            "-r", str(dpi), "-f", str(n), "-l", str(n),
                            "-singlefile", pdf, prefix],
                           check=True, timeout=120, capture_output=True)
        except Exception:
            return "渲染失败", 500
    if not os.path.exists(cache):
        return "页码超出范围", 404
    return _cacheable(send_file(cache, mimetype="image/jpeg"))


@app.get("/api/materials/<int:mid>/download")
def material_download(mid):
    m = _get_material(mid)
    if not m:
        return "未找到", 404
    path = os.path.join(UPLOADS, str(m["user_id"]), m["stored_name"])
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
        if len(board) > 20:
            return jsonify({"error": "分类名太长"}), 400
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
    src = os.path.join(UPLOADS, str(m["user_id"]), m["stored_name"])
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
    if m["user_id"] != uid():          # 共享给我的只读：能看能下，不能删（否则会把别人的文件删了）
        return jsonify({"error": "这是队友共享给你的资料，不能删除"}), 403
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
    # 错题本
    for r in db.execute("SELECT * FROM wrong_questions WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall():
        hay = " ".join(str(r[k] or "") for k in ("question", "points", "method", "skill", "steps", "note", "qtype", "board"))
        if ql in hay.lower():
            qtext = (r["question"] or "").strip()
            results.append({"type": "wrongq", "id": r["id"],
                            "title": (qtext[:26] or "（图片错题）"),
                            "board": r["board"] or r["qtype"] or "",
                            "snippet": _snippet(qtext or r["points"] or "", q)})
    # 基础知识点（各板块 · 全站共享）+ 我的补充
    for r in db.execute("SELECT * FROM board_kb").fetchall():
        body = r["content"] or ""
        if ql in body.lower() or ql in (r["board"] or "").lower():
            results.append({"type": "boardkb", "id": 0, "board": r["board"],
                            "title": (r["board"] or "") + " · 基础知识点",
                            "snippet": _snippet(body, q)})
    for r in db.execute("SELECT * FROM board_points WHERE user_id=?", (uid(),)).fetchall():
        if ql in (r["content"] or "").lower():
            results.append({"type": "boardkb", "id": 0, "board": r["board"],
                            "title": (r["board"] or "") + " · 我的补充",
                            "snippet": _snippet(r["content"] or "", q)})
    like = "%" + q + "%"
    # 每日时政
    for r in db.execute("SELECT id,title,board,pub_date,content,ai_summary FROM news_items "
                        "WHERE title LIKE ? OR content LIKE ? OR ai_summary LIKE ? "
                        "ORDER BY id DESC LIMIT 15", (like, like, like)):
        body = r["content"] or r["ai_summary"] or ""
        results.append({"type": "news", "id": r["id"], "title": r["title"],
                        "board": "%s · %s" % (r["board"] or "时政", r["pub_date"] or ""),
                        "snippet": _snippet(body if ql in body.lower() else r["title"], q)})
    # 时政要文库（全文+AI解读）
    for r in db.execute("SELECT id,title,category,content,interpretation FROM policy_docs "
                        "WHERE title LIKE ? OR content LIKE ? OR interpretation LIKE ? LIMIT 10",
                        (like, like, like)):
        body = r["content"] or ""
        if ql not in body.lower():
            body = r["interpretation"] or r["title"]
        results.append({"type": "policydoc", "id": r["id"], "title": r["title"],
                        "board": r["category"] or "要文", "snippet": _snippet(body, q)})
    # 党的创新理论学习词典
    for r in db.execute("SELECT id,term,cat,content FROM party_dict "
                        "WHERE term LIKE ? OR content LIKE ? LIMIT 15", (like, like)):
        results.append({"type": "partydict", "id": r["id"], "title": r["term"],
                        "board": r["cat"] or "", "snippet": _snippet(r["content"] or "", q)})
    # 古诗文库
    for r in db.execute("SELECT id,title,author,category,content FROM classics "
                        "WHERE title LIKE ? OR content LIKE ? OR author LIKE ? LIMIT 15",
                        (like, like, like)):
        results.append({"type": "classic", "id": r["id"], "title": r["title"],
                        "board": "%s · %s" % (r["category"] or "", r["author"] or ""),
                        "snippet": _snippet(r["content"] or "", q)})
    # 常识积累
    for r in db.execute("SELECT id,board,topic,title,content FROM changshi_items "
                        "WHERE title LIKE ? OR content LIKE ? LIMIT 15", (like, like)):
        results.append({"type": "changshi", "id": r["id"], "title": r["title"],
                        "board": "%s · %s" % (r["board"], r["topic"]),
                        "cs_board": r["board"], "cs_topic": r["topic"],
                        "snippet": _snippet(r["content"] or "", q)})
    # 写作素材 / 衔接表达
    for r in db.execute("SELECT id,kind,topic,content,date FROM sucai_items "
                        "WHERE topic LIKE ? OR content LIKE ? LIMIT 10", (like, like)):
        results.append({"type": "sucai", "id": r["id"], "title": (r["topic"] or r["kind"]),
                        "board": "%s · %s" % (r["kind"], r["date"] or ""), "kind": r["kind"],
                        "snippet": _snippet(r["content"] or "", q)})
    # 概括句
    try:
        for r in db.execute("SELECT id,topic,raw,sentence FROM gaikuo_items "
                            "WHERE topic LIKE ? OR sentence LIKE ? OR raw LIKE ? LIMIT 10",
                            (like, like, like)):
            results.append({"type": "gaikuo", "id": r["id"], "title": r["topic"] or "概括句",
                            "board": "概括句积累", "snippet": _snippet(r["sentence"] or r["raw"] or "", q)})
    except Exception:
        pass
    # 我的成语词语收录
    for r in db.execute("SELECT id,word,category,explanation FROM entries "
                        "WHERE user_id=? AND (word LIKE ? OR explanation LIKE ? OR note LIKE ?) LIMIT 10",
                        (uid(), like, like, like)):
        results.append({"type": "entry", "id": r["id"], "title": r["word"],
                        "board": r["category"] or "收录", "snippet": _snippet(r["explanation"] or "", q)})
    # 草稿本（笔迹不识别，只能按本子名搜）
    for r in db.execute("SELECT id,title,pages,updated_at FROM drafts WHERE user_id=? AND title LIKE ? "
                        "ORDER BY updated_at DESC LIMIT 10", (uid(), like)):
        results.append({"type": "draft", "id": r["id"], "title": r["title"] or "未命名草稿",
                        "board": "草稿本 · %d 页" % (r["pages"] or 1),
                        "snippet": "最近更新 " + (r["updated_at"] or "")[:16]})
    # 范文（题干 / 参考答案）
    for r in db.execute("SELECT e.id, e.type_name, e.stem, e.answer, p.topic, p.title "
                        "FROM essays e LEFT JOIN essay_papers p ON p.id=e.paper_id "
                        "WHERE e.stem LIKE ? OR e.answer LIKE ? OR p.topic LIKE ? OR p.title LIKE ? LIMIT 10",
                        (like, like, like, like)):
        body = r["answer"] or ""
        results.append({"type": "essay", "id": r["id"],
                        "title": "%s · %s" % (r["title"] or r["topic"] or "范文", r["type_name"] or ""),
                        "board": "范文推荐 · AI 仿真卷（非真题）",
                        "snippet": _snippet(body if ql in body.lower() else (r["stem"] or ""), q)})
    # 应用文上位词（场景规范表述）
    for r in db.execute("SELECT id,scene,phrases,doctype,note,example FROM gongwen_items "
                        "WHERE scene LIKE ? OR phrases LIKE ? OR doctype LIKE ? OR note LIKE ? OR example LIKE ? "
                        "LIMIT 10", (like, like, like, like, like)):
        results.append({"type": "gongwen", "id": r["id"], "title": r["scene"] or "应用文表述",
                        "board": "应用文上位词 · " + (r["doctype"] or ""), "term": r["scene"] or "",
                        "snippet": _snippet(r["phrases"] or r["note"] or r["example"] or "", q)})
    # 上位词（常考·逻辑填空）
    for r in db.execute("SELECT id,hyper,subs,note FROM hyper_items "
                        "WHERE hyper LIKE ? OR subs LIKE ? OR note LIKE ? OR example LIKE ? LIMIT 10",
                        (like, like, like, like)):
        results.append({"type": "changkao", "id": r["id"], "title": r["hyper"] or "上位词",
                        "board": "常考 · 上位词", "ck_board": "上位词",
                        "snippet": _snippet(r["subs"] or r["note"] or "", q)})
    # 习语金句
    for r in db.execute("SELECT id,quote,note,category,apply FROM xiyu_items "
                        "WHERE quote LIKE ? OR note LIKE ? OR apply LIKE ? OR keyword LIKE ? LIMIT 10",
                        (like, like, like, like)):
        results.append({"type": "xiyu", "id": r["id"], "title": (r["quote"] or "")[:30],
                        "board": "习语金句 · " + (r["category"] or ""),
                        "snippet": _snippet(r["note"] or r["apply"] or "", q)})
    # 常考（高频成语/实词/提法…）
    for r in db.execute("SELECT id,board,title,content,note FROM changkao_items "
                        "WHERE title LIKE ? OR content LIKE ? OR note LIKE ? LIMIT 15", (like, like, like)):
        results.append({"type": "changkao", "id": r["id"], "title": r["title"] or "常考",
                        "board": "常考 · " + (r["board"] or ""), "ck_board": r["board"] or "",
                        "snippet": _snippet(r["content"] or r["note"] or "", q)})
    # 理论基础（马原/毛概/中特/习思想）
    for r in db.execute("SELECT id,board,topic,title,content FROM theory_items "
                        "WHERE title LIKE ? OR content LIKE ? OR topic LIKE ? LIMIT 15", (like, like, like)):
        results.append({"type": "theory", "id": r["id"], "title": r["title"] or r["topic"] or "理论",
                        "board": "理论基础 · " + (r["board"] or ""), "th_board": r["board"] or "",
                        "snippet": _snippet(r["content"] or "", q)})
    # 经典著作（毛选等）
    for r in db.execute("SELECT id,book,title,content,interpretation FROM works "
                        "WHERE title LIKE ? OR content LIKE ? OR interpretation LIKE ? LIMIT 10",
                        (like, like, like)):
        body = r["content"] or ""
        results.append({"type": "work", "id": r["id"], "title": r["title"] or "篇目",
                        "board": "经典著作 · " + (r["book"] or ""),
                        "snippet": _snippet(body if ql in body.lower() else (r["interpretation"] or ""), q)})
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
    return jsonify({"configured": ai_configured(), "model": _ai_conf()["model"],
                    "vision": vision_configured()})


def _user_stats():
    """汇总用户与本应用的数据，供 AI 助手回答“我收录了多少…/这个应用有多少…”。"""
    db = get_db()
    u = uid()
    try:
        # 全局库总量
        cls = db.execute("SELECT category, COUNT(*) c FROM classics GROUP BY category ORDER BY c DESC").fetchall()
        cls_lib = "、".join("%s%d" % (r["category"], r["c"]) for r in cls)
        cls_total = sum(r["c"] for r in cls)
        idi = db.execute("SELECT COUNT(*) FROM ref_idiom").fetchone()[0]
        ci = db.execute("SELECT COUNT(*) FROM ref_ci").fetchone()[0]
        pdict = db.execute("SELECT COUNT(*) FROM party_dict").fetchone()[0]
        pdoc = db.execute("SELECT COUNT(*) FROM policy_docs").fetchone()[0]
        # 用户个人
        ent = db.execute("SELECT category, COUNT(*) c FROM entries WHERE user_id=? GROUP BY category", (u,)).fetchall()
        ent_by = "、".join("%s%d" % (r["category"], r["c"]) for r in ent) or "无"
        ent_total = sum(r["c"] for r in ent)
        star_ent = db.execute("SELECT COUNT(*) FROM entries WHERE user_id=? AND starred=1", (u,)).fetchone()[0]
        cstar = db.execute("SELECT c.category cat, COUNT(*) c FROM classic_stars s JOIN classics c ON c.id=s.classic_id "
                           "WHERE s.user_id=? GROUP BY c.category", (u,)).fetchall()
        cstar_by = "、".join("%s%d" % (r["cat"], r["c"]) for r in cstar) or "无"
        cstar_total = sum(r["c"] for r in cstar)
        wq = db.execute("SELECT COUNT(*) FROM wrong_questions WHERE user_id=?", (u,)).fetchone()[0]
        notes = db.execute("SELECT COUNT(*) FROM notes WHERE user_id=?", (u,)).fetchone()[0]
        docs = db.execute("SELECT COUNT(*) FROM kb_nodes WHERE user_id=? AND type='doc'", (u,)).fetchone()[0]
        mats = db.execute("SELECT COUNT(*) FROM materials WHERE user_id=?", (u,)).fetchone()[0]
    except Exception:
        return ""
    return "\n".join([
        "【本应用的数据（用户若问“这个应用有多少…”，用这些数）】",
        "· 古诗文库共 %d 首：%s。" % (cls_total, cls_lib),
        "· 成语库 %d 条、词语库 %d 条；党建理论学习词典 %d 条；时政要文库 %d 篇。" % (idi, ci, pdict, pdoc),
        "【当前用户个人的数据（用户若问“我收录/收藏了多少…”，用这些数）】",
        "· 成语词语收录共 %d 条（%s），其中收藏 %d 条。" % (ent_total, ent_by, star_ent),
        "· 收藏古诗文共 %d 首（%s）。" % (cstar_total, cstar_by),
        "· 错题本 %d 道、小记 %d 条、知识库文档 %d 篇、资料库文件 %d 个。" % (wq, notes, docs, mats),
        "注意：区分“本应用库总量”与“用户个人收录/收藏量”，按提问对象选用；数字以上面为准。",
    ])


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
    stats = _user_stats()
    if stats:
        sys = sys + "\n\n" + stats
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


@app.get("/api/admin/registration")
def admin_reg_get():
    return jsonify({"open": bool(CFG.get("registration_open", True)),
                    "invite_code": CFG.get("invite_code", "")})


@app.post("/api/admin/registration")
def admin_reg_set():
    data = request.get_json(silent=True) or {}
    if "open" in data:
        CFG["registration_open"] = bool(data.get("open"))
    if "invite_code" in data:
        CFG["invite_code"] = (data.get("invite_code") or "").strip()[:32]
    _save_cfg()
    return jsonify({"ok": True, "open": bool(CFG.get("registration_open", True)),
                    "invite_code": CFG.get("invite_code", "")})


# ================================================================ OCR 识图（tesseract）
@app.post("/api/ocr")
def api_ocr():
    f = request.files.get("file") or request.files.get("image")
    if not f or not f.filename:
        return jsonify({"error": "没有图片"}), 400
    ext = os.path.splitext(f.filename)[1].lower() or ".jpg"
    tmp = os.path.join(tempfile.gettempdir(), "ocr_" + uuid.uuid4().hex + ext)
    f.save(tmp)
    # 优先用视觉模型识别（手写 / 排版 / 公式都比 tesseract 强），失败再退 tesseract
    if vision_configured():
        try:
            vt = vision_ocr(tmp)
            if vt.strip():
                try:
                    os.remove(tmp)
                except Exception:
                    pass
                return jsonify({"text": vt.strip(), "engine": "vision"})
        except Exception:
            pass
    # 预处理：摆正方向 / 灰度 / 放大 / 拉对比度 / 锐化 —— 显著提升拍照识别率
    proc = tmp
    try:
        from PIL import Image, ImageOps, ImageFilter
        im = Image.open(tmp)
        im = ImageOps.exif_transpose(im)
        im = im.convert("L")
        w, h = im.size
        if max(w, h) < 2200:
            s = min(3.0, 2200.0 / max(w, h))
            im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
        im = ImageOps.autocontrast(im, cutoff=2)
        im = im.filter(ImageFilter.SHARPEN)
        proc = tmp + ".png"
        im.save(proc)
    except Exception:
        proc = tmp
    text = ""
    try:
        out = subprocess.run(["tesseract", proc, "stdout", "-l", "chi_sim+eng",
                              "--oem", "1", "--psm", "6"],
                             capture_output=True, timeout=120)
        text = out.stdout.decode("utf-8", "ignore")
    except Exception as e:
        for p in {tmp, proc}:
            try:
                os.remove(p)
            except Exception:
                pass
        return jsonify({"error": "识别失败：" + str(e)}), 500
    for p in {tmp, proc}:
        try:
            os.remove(p)
        except Exception:
            pass
    # tesseract 中文常在汉字间插空格，去掉相邻汉字间的空白
    text = re.sub(r"(?<=[一-鿿，。！？；：、（）《》“”])[ \t]+(?=[一-鿿，。！？；：、（）《》“”])", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return jsonify({"text": text})


# ================================================================ 错题本
WQ_BOARDS = ["常识判断", "资料分析", "判断推理", "数量关系", "政治理论", "言语理解与表达", "申论"]


def _wq_analyze(question, answer=""):
    prompt = (
        "你是公务员考试(行测/申论)辅导老师。分析下面这道题"
        + ("（附我的作答或参考解析）" if answer else "")
        + "，只输出一个 JSON 对象（不要多余文字），字段如下：\n"
        '{"board":"所属板块，取值之一：' + "/".join(WQ_BOARDS) + '",\n'
        ' "qtype":"具体题型（如：资料分析-增长率、判断推理-类比推理、逻辑填空 等）",\n'
        ' "points":"涉及的核心知识点",\n'
        ' "method":"用到的公式或方法",\n'
        ' "skill":"解题技巧与易错点",\n'
        ' "steps":"清晰的解题步骤，分条，用\\n换行"}\n\n题目：\n' + question
        + (("\n\n我的作答/参考解析：\n" + answer) if answer else ""))
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考辅导老师，只输出规范的 JSON 对象。"},
         {"role": "user", "content": prompt}],
        temperature=0.3, max_tokens=1500, json_mode=True)
    if err:
        return None, err
    try:
        d = json.loads(reply)
    except Exception:
        m = re.search(r"\{.*\}", reply or "", re.S)
        try:
            d = json.loads(m.group(0)) if m else {}
        except Exception:
            d = {}
    out = {}
    for k in ("board", "qtype", "points", "method", "skill", "steps"):
        v = d.get(k)
        out[k] = v.strip() if isinstance(v, str) else ("" if v is None else str(v))
    return out, None


def _wq_dict(r):
    return {"id": r["id"], "board": r["board"] or "", "question": r["question"] or "",
            "image": ("/api/wrongq/%d/image" % r["id"]) if r["image"] else "",
            "answer": r["answer"] or "", "qtype": r["qtype"] or "", "points": r["points"] or "",
            "method": r["method"] or "", "skill": r["skill"] or "", "steps": r["steps"] or "",
            "note": r["note"] or "", "starred": bool(r["starred"]),
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def _get_wq(wid):
    return get_db().execute("SELECT * FROM wrong_questions WHERE id=? AND user_id=?",
                            (wid, uid())).fetchone()


@app.get("/api/wrongq/boards")
def wq_boards():
    db = get_db()
    rows = db.execute("SELECT board,COUNT(*) c FROM wrong_questions WHERE user_id=? "
                      "GROUP BY board ORDER BY c DESC", (uid(),)).fetchall()
    return jsonify({"boards": [{"name": r["board"] or "未分类", "count": r["c"]} for r in rows],
                    "total": db.execute("SELECT COUNT(*) c FROM wrong_questions WHERE user_id=?", (uid(),)).fetchone()["c"],
                    "star": db.execute("SELECT COUNT(*) c FROM wrong_questions WHERE user_id=? AND starred=1", (uid(),)).fetchone()["c"]})


@app.get("/api/wrongq")
def wq_list():
    board = (request.args.get("board") or "").strip()
    star = request.args.get("star") == "1"
    q = (request.args.get("q") or "").strip()
    try:
        page = max(1, int(request.args.get("page") or 1))
    except Exception:
        page = 1
    size = 10
    where, args = ["user_id=?"], [uid()]
    if board:
        where.append("board=?"); args.append(board)
    if star:
        where.append("starred=1")
    if q:
        where.append("(question LIKE ? OR qtype LIKE ? OR points LIKE ?)")
        L = "%" + q + "%"; args += [L, L, L]
    wsql = " WHERE " + " AND ".join(where)
    db = get_db()
    total = db.execute("SELECT COUNT(*) n FROM wrong_questions" + wsql, args).fetchone()["n"]
    rows = db.execute("SELECT * FROM wrong_questions" + wsql + " ORDER BY id DESC LIMIT ? OFFSET ?",
                      args + [size, (page - 1) * size]).fetchall()
    return jsonify({"items": [_wq_dict(r) for r in rows], "total": total, "page": page,
                    "pages": max(1, (total + size - 1) // size)})


@app.post("/api/wrongq")
def wq_create():
    question = (request.form.get("question") or "").strip()
    answer = (request.form.get("answer") or "").strip()
    board = (request.form.get("board") or "").strip()
    do_ai = request.form.get("analyze", "1") != "0"
    img = request.files.get("image")
    stored = ""
    if img and img.filename:
        ext = os.path.splitext(img.filename)[1].lower() or ".jpg"
        stored = "wq_" + uuid.uuid4().hex + ext
        img.save(os.path.join(_user_dir(uid()), stored))
    if not question and not stored:
        return jsonify({"error": "请填写题目或上传图片"}), 400
    f = {"board": board, "qtype": "", "points": "", "method": "", "skill": "", "steps": ""}
    if do_ai and question:
        res, err = _wq_analyze(question, answer)
        if res:
            for k, v in res.items():
                if v:
                    f[k] = v
            if not board and res.get("board"):
                f["board"] = res["board"]
    db = get_db()
    cur = db.execute(
        "INSERT INTO wrong_questions(user_id,board,question,image,answer,qtype,points,method,skill,steps) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (uid(), f["board"], question, stored, answer, f["qtype"], f["points"], f["method"], f["skill"], f["steps"]))
    db.commit()
    return jsonify(_wq_dict(db.execute("SELECT * FROM wrong_questions WHERE id=?", (cur.lastrowid,)).fetchone())), 201


@app.post("/api/wrongq/<int:wid>/analyze")
def wq_reanalyze(wid):
    r = _get_wq(wid)
    if not r:
        return jsonify({"error": "未找到"}), 404
    if not (r["question"] or "").strip():
        return jsonify({"error": "没有题目文字，请先填写题干或对图片做 OCR"}), 400
    res, err = _wq_analyze(r["question"], r["answer"] or "")
    if err:
        return err
    board = r["board"] or res.get("board") or ""
    get_db().execute(
        "UPDATE wrong_questions SET board=?,qtype=?,points=?,method=?,skill=?,steps=?,"
        "updated_at=datetime('now','localtime') WHERE id=? AND user_id=?",
        (board, res["qtype"], res["points"], res["method"], res["skill"], res["steps"], wid, uid()))
    get_db().commit()
    return jsonify(_wq_dict(_get_wq(wid)))


@app.get("/api/wrongq/<int:wid>")
def wq_get(wid):
    r = _get_wq(wid)
    return (jsonify(_wq_dict(r)) if r else (jsonify({"error": "未找到"}), 404))


@app.put("/api/wrongq/<int:wid>")
def wq_update(wid):
    r = _get_wq(wid)
    if not r:
        return jsonify({"error": "未找到"}), 404
    d = request.get_json(silent=True) or {}
    sets, args = [], []
    for fld in ("board", "question", "answer", "qtype", "points", "method", "skill", "steps", "note"):
        if fld in d:
            sets.append(fld + "=?"); args.append((d.get(fld) or "").strip())
    if "starred" in d:
        sets.append("starred=?"); args.append(1 if d.get("starred") else 0)
    if sets:
        sets.append("updated_at=datetime('now','localtime')")
        args += [wid, uid()]
        get_db().execute("UPDATE wrong_questions SET %s WHERE id=? AND user_id=?" % ",".join(sets), args)
        get_db().commit()
    return jsonify(_wq_dict(_get_wq(wid)))


@app.delete("/api/wrongq/<int:wid>")
def wq_delete(wid):
    r = _get_wq(wid)
    if not r:
        return jsonify({"error": "未找到"}), 404
    if r["image"]:
        _remove_file(uid(), r["image"])
    get_db().execute("DELETE FROM wrong_questions WHERE id=? AND user_id=?", (wid, uid()))
    get_db().commit()
    return jsonify({"ok": True})


@app.get("/api/wrongq/<int:wid>/image")
def wq_image(wid):
    r = _get_wq(wid)
    if not r or not r["image"]:
        return "未找到", 404
    p = os.path.join(UPLOADS, str(uid()), r["image"])
    if not os.path.exists(p):
        return "文件丢失", 404
    return send_file(p, as_attachment=False)


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


# ---------------------------------------------------------------- 每日时政（爬虫 + AI，全局共享）
# ---------------------------------------------------------------- 每日新闻视频（筛过的）
VIDEO_BOARDS = ["国内", "国际", "四川"]
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")


@app.get("/api/videos")
def videos_list():
    """每日新闻视频：只给**筛过的**（AI 按公考价值挑的），并附「为什么值得看」。
       信源全是白名单里的官方媒体 —— 没法自动确认「某个博主是不是真的」，
       所以不接受任意来源，那等于把把关的活儿丢给你自己。"""
    db = get_db()
    board = (request.args.get("board") or "").strip()
    star = request.args.get("star") in ("1", "true")
    where, args = [], []
    if board in VIDEO_BOARDS:
        where.append("v.board=?")
        args.append(board)
    if star:
        where.append("s.user_id IS NOT NULL")
    sql = ("SELECT v.*, (s.user_id IS NOT NULL) starred FROM video_items v "
           "LEFT JOIN video_stars s ON s.video_id=v.id AND s.user_id=? ")
    args = [uid()] + args
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY v.pick_date DESC, v.score DESC, v.id DESC LIMIT 120"
    rows = db.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except Exception:
            d["tags"] = []
        d["starred"] = bool(d.get("starred"))
        out.append(d)
    cnt = {r[0]: r[1] for r in db.execute(
        "SELECT board, COUNT(*) FROM video_items GROUP BY board")}
    last = db.execute("SELECT MAX(pick_date) FROM video_items").fetchone()[0] or ""
    return jsonify({"items": out, "counts": cnt, "boards": VIDEO_BOARDS, "last": last,
                    "n_star": db.execute("SELECT COUNT(*) FROM video_stars WHERE user_id=?",
                                         (uid(),)).fetchone()[0]})


@app.post("/api/videos/<int:vid>/star")
def video_star(vid):
    db = get_db()
    have = db.execute("SELECT 1 FROM video_stars WHERE user_id=? AND video_id=?",
                      (uid(), vid)).fetchone()
    if have:
        db.execute("DELETE FROM video_stars WHERE user_id=? AND video_id=?", (uid(), vid))
        db.commit()
        return jsonify({"starred": False})
    db.execute("INSERT OR IGNORE INTO video_stars(user_id, video_id) VALUES(?,?)", (uid(), vid))
    db.commit()
    return jsonify({"starred": True})


# 画质档：chapters=418kbps、chapters2=818kbps、chapters3=1.2M、chapters4=2M。
# 优先 chapters2 —— 清晰度够看字幕，又不至于卡。
CCTV_TIERS = ("chapters2", "chapters3", "chapters", "chapters4")


def cctv_play(guid):
    """问央视网要这条片子的可播地址。

    优先拿 **mp4 分段**：那是普通渐进式 mp4，`<video>` 原生就能放 —— 不用 hls.js、
    不依赖 MSE，桌面壳那个 WebKit 也吃得下。代价是一集切成好几段，得自己接成一条时间轴。

    但**不是每条都有 mp4**：像《今日关注》，四个画质档的 url 全是空串（没转码），
    只有 HLS。所以拿不到 mp4 时退回 m3u8，前端用 hls.js 放。
    两种流实测都没有防盗链、CORS 全开，能直接放进我们自己的页面。
    """
    r = urllib.request.Request(
        "https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do?pid=" + str(guid),
        headers={"User-Agent": UA})
    with urllib.request.urlopen(r, timeout=12) as x:
        d = json.loads(x.read().decode("utf-8", "ignore"))
    vid = d.get("video") or {}
    title = (d.get("title") or "").strip()

    for tier in CCTV_TIERS:
        chs = [{"url": c["url"], "dur": float(c.get("duration") or 0)}
               for c in (vid.get(tier) or []) if c.get("url")]
        if chs:
            return {"mode": "mp4", "chapters": chs,
                    "total": sum(c["dur"] for c in chs), "title": title}

    if d.get("hls_url"):
        return {"mode": "hls", "src": d["hls_url"],
                "total": float(vid.get("totalLength") or 0), "title": title}
    raise RuntimeError("央视网这条既没有 mp4 也没有 HLS")


@app.get("/api/videos/<int:vid>/play")
def video_play(vid):
    """给前端播放器：这条视频怎么播。

    三种播法（`kind` 决定）：
      cctv → 自己放：央视网给的 mp4 分段，我们的播放器把它们接成一条连续的时间轴
      bili → 嵌 B 站官方播放器（人家的 iframe 没有任何嵌入限制，实测可用）
      sc   → 川观：抓取时如果拿到了直链就自己放；没拿到就只能跳出去（老实说明）
    """
    db = get_db()
    r = db.execute("SELECT * FROM video_items WHERE id=?", (vid,)).fetchone()
    if not r:
        return jsonify({"error": "视频不存在"}), 404
    row = dict(r)
    kind = row.get("kind") or "sc"
    base = {"id": vid, "kind": kind, "title": row.get("title") or "",
            "url": row.get("url") or "", "source": row.get("source") or ""}

    if kind == "bili":
        bv = row.get("guid") or ""
        return jsonify(dict(base, mode="iframe", embed=(
            "https://player.bilibili.com/player.html?bvid=%s&autoplay=0&danmaku=0&high_quality=1"
            % bv)))

    # 抓取时算好的播放地址，直接用（不用每次点播放都去请求人家的接口）
    try:
        cached = json.loads(row.get("play") or "null")
    except Exception:
        cached = None
    if cached and (cached.get("chapters") or cached.get("src")):
        return jsonify(dict(base, **cached))

    if kind == "cctv":
        try:
            info = cctv_play(row.get("guid") or "")
        except Exception as e:
            app.logger.warning("央视取流失败 vid=%s: %s", vid, e)
            return jsonify(dict(base, mode="external",
                                note="央视网这会儿没给出播放地址，先在浏览器里看")), 200
        db.execute("UPDATE video_items SET play=? WHERE id=?",
                   (json.dumps(info, ensure_ascii=False), vid))
        db.commit()
        return jsonify(dict(base, **info))

    # 川观：抓取时没拿到直链就没辙了（它的直链藏在 JS 里，得渲染页面才拿得到）
    return jsonify(dict(base, mode="external", note="这条只能在浏览器里看"))


@app.post("/api/videos/refresh")
def videos_refresh():
    """手动刷一次（平时是定时器每天跑）。抓取要开无头浏览器，放后台。"""
    tid = _bg_new(get_db(), "video", "刷新每日新闻视频", 1)

    def run():
        con = sqlite3.connect(DB, timeout=60)
        try:
            _bg_set(con, tid, status="running", message="正在抓取央视网 / B站官方号 / 川观新闻…")
            r = subprocess.run(
                [os.path.join(BASE, ".venv/bin/python3"), os.path.join(BASE, "crawl_video.py")],
                cwd=BASE, capture_output=True, text=True, timeout=600)
            tail = (r.stdout or r.stderr or "").strip().splitlines()
            _bg_set(con, tid, status="done", progress=1,
                    message=(tail[-1] if tail else "完成"))
        except Exception as ex:
            _bg_set(con, tid, status="error", message=str(ex)[:150])
        finally:
            con.close()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"task": tid}), 202


@app.get("/api/news")
def news_list():
    board = (request.args.get("board") or "").strip()
    date = (request.args.get("date") or "").strip()
    star_only = request.args.get("star") == "1"
    db = get_db()
    if star_only:
        # 收藏夹：跨板块跨日期，按收藏时间倒序
        rows = db.execute(
            "SELECT n.id,n.title,n.source,n.pub_date,n.ai_summary,COALESCE(n.board,'国内') board,"
            "length(n.content) chars, 1 starred FROM news_items n "
            "JOIN news_stars s ON s.news_id=n.id AND s.user_id=? "
            "ORDER BY s.created_at DESC LIMIT 200", (uid(),)).fetchall()
        counts = {r[0]: r[1] for r in
                  db.execute("SELECT COALESCE(board,'国内'), COUNT(*) FROM news_items GROUP BY COALESCE(board,'国内')")}
        return jsonify({"items": [dict(r) for r in rows], "dates": [], "date": "", "star_total": len(rows),
                        "counts": {b: counts.get(b, 0) for b in ("党内", "国内", "四川", "国际")}})
    where, args = [], []
    if board in ("党内", "国内", "四川", "国际"):
        where.append("board=?"); args.append(board)
    # 该板块下有哪些日期（号数导航用）
    dsql = "SELECT pub_date, COUNT(*) c FROM news_items %s GROUP BY pub_date ORDER BY pub_date DESC LIMIT 30" % (
        ("WHERE " + " AND ".join(where)) if where else "")
    dates = [{"date": r["pub_date"], "count": r["c"]} for r in db.execute(dsql, args).fetchall()]
    if not date and dates:
        date = dates[0]["date"]  # 默认最新一天
    if date:
        where.append("pub_date=?"); args.append(date)
    sql = ("SELECT n.id,n.title,n.source,n.pub_date,n.ai_summary,COALESCE(n.board,'国内') board,"
           "length(n.content) chars,(s.news_id IS NOT NULL) starred "
           "FROM news_items n LEFT JOIN news_stars s ON s.news_id=n.id AND s.user_id=%d %s "
           "ORDER BY n.id DESC LIMIT 60") % (uid(), ("WHERE " + " AND ".join("n." + w for w in where)) if where else "")
    rows = db.execute(sql, args).fetchall()
    counts = {r[0]: r[1] for r in
              db.execute("SELECT COALESCE(board,'国内'), COUNT(*) FROM news_items GROUP BY COALESCE(board,'国内')")}
    star_total = db.execute("SELECT COUNT(*) FROM news_stars WHERE user_id=?", (uid(),)).fetchone()[0]
    return jsonify({"items": [dict(r) for r in rows], "dates": dates, "date": date, "star_total": star_total,
                    "counts": {b: counts.get(b, 0) for b in ("党内", "国内", "四川", "国际")}})


@app.post("/api/news/<int:nid>/star")
def news_star(nid):
    on = bool((request.get_json(silent=True) or {}).get("starred"))
    db = get_db()
    if on:
        db.execute("INSERT OR IGNORE INTO news_stars(user_id,news_id) VALUES(?,?)", (uid(), nid))
    else:
        db.execute("DELETE FROM news_stars WHERE user_id=? AND news_id=?", (uid(), nid))
    db.commit()
    return jsonify({"starred": on})


@app.get("/api/news/<int:nid>")
def news_detail(nid):
    r = get_db().execute("SELECT * FROM news_items WHERE id=?", (nid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    try:
        marks = json.loads(r["marks"] or "[]") if "marks" in r.keys() else []
    except Exception:
        marks = []
    return jsonify({"id": r["id"], "title": r["title"], "url": r["url"], "source": r["source"],
                    "pub_date": r["pub_date"], "content": r["content"] or "",
                    "ai_summary": r["ai_summary"] or "", "marks": marks})


# 时政重点标注的四类考点（颜色/含义在前端一一对应）
NEWS_MARK_KINDS = ["提法", "数据", "政策", "金句"]


@app.post("/api/news/<int:nid>/marks")
def news_marks(nid):
    """在原文里划重点：让 AI **逐字挑出**原文中的要害句，并说明是什么考点。
       关键是「逐字」——挑出来的句子必须能在原文里原样找到，否则前端根本标不上去。
       服务端会逐条核对，对不上的直接丢掉（宁可少标，不能标错位置）。"""
    db = get_db()
    r = db.execute("SELECT * FROM news_items WHERE id=?", (nid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    content = (r["content"] or "").strip()
    if len(content) < 40:
        return jsonify({"marks": []})
    try:
        old = json.loads(r["marks"] or "[]")
    except Exception:
        old = []
    if old and not request.args.get("force"):
        return jsonify({"marks": old, "cached": True})

    prompt = (
        "下面是一篇时政原文。考生没时间通读，请在原文里**划重点**：挑出 4~8 处最该记的地方，"
        "每处**必须从原文里逐字复制**（一字不差，含标点），否则没法在原文上标出来。\n\n"
        "每处给：\n"
        "· quote：从原文逐字复制的句子或短语（10~60 字，别整段抄）\n"
        "· kind：属于哪类考点，只能填 提法 / 数据 / 政策 / 金句 之一\n"
        "  （提法=新表述新概念，常识判断爱考；数据=具体数字时间，容易出选项；"
        "政策=文件名/举措/目标；金句=可直接用进申论的表述）\n"
        "· why：为什么要记它（一句话，讲清考点在哪，别复述原文）\n\n"
        '只输出 JSON：{"marks":[{"quote":"","kind":"","why":""}]}\n\n【原文】\n' + content[:4000])
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考时政老师，只从原文里逐字摘句，绝不改写、不编造。严格输出 JSON。"},
         {"role": "user", "content": prompt}], temperature=0.3, max_tokens=2000, timeout=180, json_mode=True)
    if err:
        return err
    try:
        got = json.loads(rep).get("marks") or []
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502

    marks, seen = [], set()
    for m in got:
        q = (m.get("quote") or "").strip()
        if not q or q in seen:
            continue
        if q not in content:                 # 对不上原文就丢掉——标错位置比不标更糟
            q2 = re.sub(r"\s+", "", q)
            hit = next((x for x in [q2] if q2 and q2 in re.sub(r"\s+", "", content)), None)
            if not hit:
                continue
            q = q2                            # 只是空白差异，用去空白版再试
            if q not in content:
                continue
        seen.add(q)
        kind = m.get("kind") if m.get("kind") in NEWS_MARK_KINDS else "提法"
        marks.append({"quote": q, "kind": kind, "why": (m.get("why") or "").strip()[:120]})
    if not marks:
        return jsonify({"error": "AI 挑出的句子和原文对不上，请重试"}), 502
    db.execute("UPDATE news_items SET marks=? WHERE id=?", (json.dumps(marks, ensure_ascii=False), nid))
    db.commit()
    return jsonify({"marks": marks})


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
KAOGONG_CACHE = os.environ.get("KAOGONG_CACHE", os.path.expanduser("~/.openclaw/kaogong-cache"))
_SUCAI_KIND_MAP = {"人物事例": "人物事例", "事实论据": "人物事例", "具体事例": "具体事例",
                   "理论论据": "理论论据", "衔接表达": "衔接表达"}


def _sucai_parse(text):
    """解析 kaogong-cache 每日素材文本 → [(kind, topic, content)]；兼容早期无小节头的格式。"""
    items, kind = [], "人物事例"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^【(人物事例|事实论据|具体事例|理论论据|衔接表达)】$", line)
        if m:
            kind = _SUCAI_KIND_MAP[m.group(1)]
            continue
        m = re.match(r"^(?:\d+[.、．]\s*|[·•]\s*)(.+)$", line)
        if not m:
            continue
        body = m.group(1).strip()
        topic = ""
        tm = re.match(r"^【(.+?)】\s*(.*)$", body)
        if tm and tm.group(2).strip():
            topic, body = tm.group(1), tm.group(2).strip()
        if body:
            items.append((kind, topic, body))
    return items


def _sucai_import(db):
    """扫描缓存目录，把还没入库的日期解析进 sucai_items（幂等）。"""
    try:
        files = [f for f in os.listdir(KAOGONG_CACHE) if re.match(r"^\d{4}-\d{2}-\d{2}\.txt$", f)]
    except Exception:
        return
    have = {r[0] for r in db.execute("SELECT DISTINCT date FROM sucai_items")}
    changed = False
    for f in sorted(files):
        d = f[:10]
        if d in have:
            continue
        try:
            text = open(os.path.join(KAOGONG_CACHE, f), encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for kind, topic, content in _sucai_parse(text):
            db.execute("INSERT OR IGNORE INTO sucai_items(date,kind,topic,content) VALUES(?,?,?,?)",
                       (d, kind, topic, content))
        changed = True
    if changed:
        db.commit()
        _spawn_fill_examples()   # 新导入的衔接表达后台补例句，用户不用挨个点


_FILL_RUNNING = False


def _spawn_fill_examples():
    """后台线程给缺例句的「衔接表达」补 AI 例句（每天素材更新后自动跑一次）。"""
    global _FILL_RUNNING
    if _FILL_RUNNING or not ai_configured():
        return
    _FILL_RUNNING = True

    def run():
        global _FILL_RUNNING
        try:
            con = sqlite3.connect(DB, timeout=30)
            rows = con.execute("SELECT id, content FROM sucai_items WHERE kind='衔接表达' "
                               "AND (example IS NULL OR example='') ORDER BY id DESC LIMIT 20").fetchall()
            for sid, content in rows:
                prompt = ("下面是一句申论写作的衔接表达/万能句式：\n%s\n\n请用它写一个申论语境下的规范例句"
                          "（书面化、紧扣治理/民生/发展类主题，30~60字），只输出例句本身。" % content)
                try:
                    rep = ai_chat([{"role": "system", "content": "你是申论写作辅导老师，例句规范、书面化。"},
                                   {"role": "user", "content": prompt}], temperature=0.6, max_tokens=200)
                    con.execute("UPDATE sucai_items SET example=? WHERE id=?", (rep.strip(), sid))
                    con.commit()
                except Exception:
                    continue
            con.close()
        except Exception:
            pass
        finally:
            _FILL_RUNNING = False

    threading.Thread(target=run, daemon=True).start()


@app.get("/api/sucai")
def sucai_list():
    kind = (request.args.get("kind") or "").strip()
    db = get_db()
    _sucai_import(db)
    counts = {r[0]: r[1] for r in db.execute("SELECT kind, COUNT(*) FROM sucai_items GROUP BY kind")}
    where, args = "", []
    if kind and kind != "全部":
        where = "WHERE kind=?"; args = [kind]
    rows = db.execute("SELECT * FROM sucai_items %s ORDER BY date DESC, id LIMIT 400" % where, args).fetchall()
    return jsonify({"items": [dict(r) for r in rows], "counts": counts})


# ---------------------------------------------------------------- 成文（素材 → 大作文）
# 素材背了不会用，等于没背。这里把散落在各库的素材真正拼成一篇能交卷的大作文。
WRITE_MIN, WRITE_MAX = 1000, 1200      # 省考大作文常规字数

# 政治理论和常考提法**不是按天更新的**（都是一次性铺进去的），
# 所以它们不能按日期取——要按当天素材的话题去检索，这样每篇都用得上。
_STOP = set(["我们", "他们", "这个", "那个", "一个", "可以", "因为", "所以", "如果", "需要",
             "进行", "具有", "成为", "不断", "更加", "已经", "以及", "其中", "这样", "通过",
             "实现", "称号", "荣获", "表示", "指出", "以来", "以后", "同时", "但是", "而且"])


def _kw_of(sucai, news, n=8):
    """抠出检索用的关键词，拿去政治理论/常考提法里捞相关内容。

    首选素材自带的 topic 标签（「创新·实干」「奉献·为民」这种，是人工归好类的，干净）；
    不够再从正文里补高频词——但正文里抠出来的多半是「通过」「实现」这类虚词，捞不到东西，
    所以只当补充，且过一遍停用词。"""
    kws = []
    for x in sucai:
        for w in re.split(r"[·、,，/]", x.get("topic") or ""):
            w = w.strip()
            if 2 <= len(w) <= 6 and w not in kws:
                kws.append(w)
    if len(kws) >= 4:
        return kws[:n]
    cnt = {}
    for t in [x.get("content") or "" for x in sucai] + [x.get("title") or "" for x in news]:
        for w in re.findall(r"[一-龥]{2,4}", t):
            if w in _STOP:
                continue
            cnt[w] = cnt.get(w, 0) + 1
    for w, _ in sorted(cnt.items(), key=lambda x: -x[1]):
        if w not in kws:
            kws.append(w)
        if len(kws) >= n:
            break
    return kws


def _like_any(db, sql, kws, cols, limit):
    """按关键词 OR LIKE 去某张表捞素材；一个都没命中就退回默认取法。"""
    if not kws:
        return []
    where = " OR ".join("(%s)" % " OR ".join("%s LIKE ?" % c for c in cols) for _ in kws)
    args = []
    for k in kws:
        args += ["%" + k + "%"] * len(cols)
    return db.execute(sql % where + " LIMIT %d" % limit, args).fetchall()


def _write_pool(db, date):
    """凑齐一天的素材池。date=None 表示综合应用（不限日期，跨全库挑）。"""
    p = {"date": date, "sucai": [], "lianjie": [], "gaikuo": [], "xiyu": [],
         "theory": [], "tifa": [], "idiom": [], "news": []}
    if date:
        rows = db.execute("SELECT kind,topic,content FROM sucai_items WHERE date=? ORDER BY id",
                          (date,)).fetchall()
        for r in rows:
            (p["lianjie"] if r["kind"] == "衔接表达" else p["sucai"]).append(dict(r))
        p["gaikuo"] = [dict(r) for r in db.execute(
            "SELECT topic,sentence FROM gaikuo_items WHERE date=? LIMIT 6", (date,))]
        p["xiyu"] = [dict(r) for r in db.execute(
            "SELECT category,quote,note FROM xiyu_items WHERE date=? LIMIT 6", (date,))]
        p["news"] = [dict(r) for r in db.execute(
            "SELECT title,ai_summary FROM news_items WHERE date(created_at)=? LIMIT 8", (date,))]
    else:
        # 综合应用：素材不限日期，但优先近期（AI 自己选题，选材范围要够宽）
        p["sucai"] = [dict(r) for r in db.execute(
            "SELECT kind,topic,content FROM sucai_items WHERE kind!='衔接表达' "
            "ORDER BY date DESC LIMIT 40")]
        p["lianjie"] = [dict(r) for r in db.execute(
            "SELECT kind,topic,content FROM sucai_items WHERE kind='衔接表达' "
            "ORDER BY RANDOM() LIMIT 14")]
        p["xiyu"] = [dict(r) for r in db.execute(
            "SELECT category,quote,note FROM xiyu_items ORDER BY date DESC LIMIT 10")]
        p["news"] = [dict(r) for r in db.execute(
            "SELECT title,ai_summary FROM news_items ORDER BY id DESC LIMIT 12")]

    kws = _kw_of(p["sucai"], p["news"])
    p["kws"] = kws
    th = _like_any(db, "SELECT board,topic,title,content FROM theory_items WHERE %s", kws,
                   ["topic", "title", "content"], 6)
    if not th:
        th = db.execute("SELECT board,topic,title,content FROM theory_items "
                        "ORDER BY RANDOM() LIMIT 4").fetchall()
    p["theory"] = [dict(r) for r in th]
    tf = _like_any(db, "SELECT title,content FROM changkao_items WHERE board='提法' AND (%s)", kws,
                   ["title", "content"], 6)
    if not tf:
        tf = db.execute("SELECT title,content FROM changkao_items WHERE board='提法' "
                        "ORDER BY RANDOM() LIMIT 4").fetchall()
    p["tifa"] = [dict(r) for r in tf]
    p["idiom"] = [dict(r) for r in db.execute(
        "SELECT title,content FROM changkao_items WHERE board='成语' "
        "ORDER BY freq DESC LIMIT 12")]
    return p


def _pool_text(p):
    """素材池 → 喂给 AI 的清单。每条都编号，写完要报告用了哪几条，好核对。"""
    L, idx = [], []

    def sec(name, items, fmt):
        if not items:
            return
        L.append("【%s】" % name)
        for it in items:
            n = len(idx) + 1
            idx.append((name, fmt(it)))
            L.append("%d. %s" % (n, fmt(it)))
        L.append("")

    sec("人物事例/具体事例/理论论据", p["sucai"],
        lambda x: "（%s·%s）%s" % (x.get("kind") or "", x.get("topic") or "", x["content"]))
    sec("衔接表达（写作时必须用上，不要自己造口语过渡）", p["lianjie"], lambda x: x["content"])
    sec("政治理论（行测·理论基础）", p["theory"],
        lambda x: "（%s）%s：%s" % (x.get("board") or "", x.get("title") or "", x.get("content") or ""))
    sec("常考提法", p["tifa"], lambda x: "%s：%s" % (x.get("title") or "", x.get("content") or ""))
    sec("高频成语（用在恰当处，别堆砌）", p["idiom"],
        lambda x: "%s：%s" % (x.get("title") or "", (x.get("content") or "")[:40]))
    sec("规范概括句", p["gaikuo"], lambda x: x.get("sentence") or "")
    sec("金句（习语/权威表述）", p["xiyu"], lambda x: x.get("quote") or "")
    sec("当日时政（可作背景，不必强用）", p["news"], lambda x: x.get("title") or "")
    return "\n".join(L), idx


def _used_hit(item, content):
    """AI 报的「我用了这条素材」到底是不是真的？逐条回正文里核对。
       它很爱把没用上的也报进来（实测 24 条里有 4 条是虚报的），这个清单是给人回查素材用的，
       有水分就没意义了 —— 宁可少列，不能列错。"""
    t = (item or "").strip()
    if not t:
        return False
    if "…" in t:                       # 衔接表达是带省略号的模板：拆成骨架片段，一半以上出现才算用了
        frag = [x for x in re.split(r"…+", re.sub(r"[（(].*?[)）]", "", t)) if len(x.strip()) >= 2]
        if not frag:
            return False
        hit = sum(1 for f in frag if f.strip(" ，,。.、—-") and f.strip(" ，,。.、—-") in content)
        return hit * 2 >= len(frag)
    head = t.split("：")[0].strip("（）() ")   # 成语/提法：词本身出现即可
    if 2 <= len(head) <= 8 and "：" in t:
        return head in content
    body = re.sub(r"^[（(].*?[)）]", "", t)   # 事例/金句：里面任意一个 4 字以上的实词短语出现
    return any(x in content for x in re.findall(r"[一-龥]{4,12}", body))


def _write_lack(p, content):
    """检查「综合运用」的硬指标到底达没达标 —— 模型对「必须用上 N 条」极不敏感，
       光在提示词里说一遍它就照抄要求、该不用还是不用（字数也是同一个毛病）。
       所以生成完要真去数，缺什么就回头让它补什么。

       ⚠️ 缺项里**必须把候选原文摆出来**：只说「要用 2~3 个成语」，它得回头自己去几十条池子里翻，
       实测就是不翻；把「就用这几个」摆到面前，它才会用。"""
    need = []
    n_ex = sum(1 for x in p["sucai"] if _used_hit(
        "（%s·%s）%s" % (x.get("kind") or "", x.get("topic") or "", x["content"]), content))
    if n_ex < 3:
        need.append("事例只用了 %d 条，至少要 3 条，且分散在三个分论点里" % n_ex)
    n_th = sum(1 for x in p["theory"] + p["tifa"]
               if (x.get("title") or "") and x["title"] in content)
    if n_th < 2:
        cand = [x["title"] for x in (p["tifa"] + p["theory"]) if x.get("title")][:5]
        need.append("政治理论/常考提法只用了 %d 条，至少要 2 条（支撑分论点的道理，不是贴标签）。"
                    "从这些里挑：%s" % (n_th, "、".join(cand)))
    n_jj = sum(1 for x in p["xiyu"] if (x.get("quote") or "")[:12] in content)
    if not n_jj and p["xiyu"]:
        cand = [x["quote"] for x in p["xiyu"] if x.get("quote")][:3]
        need.append("一句金句都没用，开头或结尾至少原样引 1 句。就从这几句里挑：\n  - "
                    + "\n  - ".join(cand))
    # 成语只要求「至少用上 1 个」：申论大作文堆成语反而扣分，用对一个就够了。
    # （初始提示词里仍写「2~3 个」引导，但检查不卡这个数，免得为了凑数多跑一轮重写。）
    n_id = sum(1 for x in p["idiom"] if x["title"] in content)
    if n_id < 1:
        cand = [x["title"] for x in p["idiom"]][:8]
        need.append("一个成语都没用，恰当处用上 1~3 个（别堆砌）。就从这些里挑：%s" % "、".join(cand))
    w = len(re.sub(r"\s", "", content))
    if w < WRITE_MIN:
        need.append("字数只有 %d，要写到 %d~%d" % (w, WRITE_MIN, WRITE_MAX))
    elif w > WRITE_MAX + 80:
        need.append("字数 %d 超了，压到 %d~%d" % (w, WRITE_MIN, WRITE_MAX))
    return need


def _write_gen(db, mode, date):
    """生成一篇。返回 (essay_dict, None) 或 (None, (json, code))。"""
    p = _write_pool(db, date if mode == "daily" else None)
    if mode == "daily" and not p["sucai"] and not p["lianjie"]:
        return None, (jsonify({"error": "这一天没有素材，写不了"}), 400)
    pool, idx = _pool_text(p)

    if mode == "daily":
        head = ("下面是 %s 这一天更新的备考素材。请**只用这些素材**，写一篇申论大作文。\n"
                "立意从素材里长出来——先看这批素材共同指向什么问题，再定题目，"
                "不要硬凑一个宏大题目再往里塞素材。\n" % date)
    else:
        head = ("下面是素材库里挑出来的一批素材（跨越多日）。请自己**选一个有价值的话题**"
                "——要是省考真考的方向（基层治理、科技创新、乡村振兴、文化自信、"
                "民生保障、绿色发展、法治建设这类），不要选空泛口号；"
                "然后从素材里挑真正用得上的写一篇大作文。用不上的素材就不要用，别硬塞。\n")

    prompt = (head + "\n" + pool + "\n\n"
              "【要求】\n"
              "1. 标题：8~16 字，观点鲜明，不要「浅谈」「论」这种套话开头。\n"
              "2. 结构：开头（引材料+亮总论点）→ 三个分论点（每段：分论点句+素材论证+回扣）→ 结尾升华。\n"
              "3. 每个分论点段**必须实打实用上面素材里的事例或理论**，写清是谁、做了什么、说明什么；"
              "不要写「某地某人」这种空壳。\n"
              "4. 段落之间**必须使用上面给的衔接表达**，不要自己造「首先其次最后」这种口水过渡。\n"
              "5. **各类素材都要用上**（这是「综合运用」的硬指标，不许只挑事例和衔接表达省事）：\n"
              "   · 事例（人物/具体）≥3 条，且分散在三个分论点里，不要堆在一段\n"
              "   · 政治理论 或 常考提法 ≥2 条，用来支撑分论点的道理，不是贴标签\n"
              "   · 金句（习语/权威表述）≥1 条，放在开头或结尾\n"
              "   · 高频成语 2~3 个，用在恰当处，别堆砌\n"
              "6. 字数 %d~%d 字，**必须达标**（这是评分硬指标）。\n"
              "7. 正文用 \\n 分段，不要 markdown 标记、不要小标题、不要「分论点一」这种标签。\n\n"
              "只输出 JSON：\n"
              '{"title":"","topic":"话题标签，4~8字","outline":["总论点","分论点1","分论点2","分论点3"],'
              '"content":"正文全文","used":[序号,...],"note":"一句话说明为什么这么选材"}\n'
              "used 里填你**真正用进文章**的素材序号（就是上面每条前面的数字），没用的别写。"
              % (WRITE_MIN, WRITE_MAX))

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论阅卷组的范文作者。文章要能直接当范文用："
                                       "论点立得住、素材是真的、衔接不生硬、字数达标。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.6, max_tokens=4000, timeout=300, json_mode=True)
    if err:
        return None, err
    try:
        d = json.loads(rep)
    except Exception:
        return None, (jsonify({"error": "AI 返回格式异常，请重试"}), 502)

    content = (d.get("content") or "").strip()
    if not content:
        return None, (jsonify({"error": "AI 没写出正文，请重试"}), 502)

    # 数一遍「综合运用」的硬指标。缺了就把缺项（连同候选原文）摆到它面前让它补。
    # 最多补两轮：一轮通常能把理论/提法补进去，第二轮才轮到金句和成语；再补就是浪费调用了。
    for _ in range(2):
        lack = _write_lack(p, content)
        if not lack:
            break
        fix, ferr = _ai_call_or_error(
            [{"role": "system", "content": "你是申论阅卷组的范文作者。严格输出 JSON。"},
             {"role": "user", "content":
              "这是你刚写的文章，还差几处没达标：\n· " + "\n· ".join(lack) +
              "\n\n【可用素材】（还是这些，序号不变）\n" + pool +
              "\n\n【你的文章】\n" + content +
              "\n\n请在**不打乱原有结构和论点**的前提下改好上面每一条：该补的素材织进对应段落里"
              "（要自然，不是硬贴一句）。\n"
              "⚠️ 补内容会撑长篇幅——**补一句就删一句冗余的**，全文仍要控制在 %d~%d 字，"
              "不许为了塞素材把字数写超。\n"
              '只输出 JSON：{"content":"改好的正文全文","used":[序号,...]}'
              % (WRITE_MIN, WRITE_MAX)}],
            temperature=0.5, max_tokens=4000, timeout=300, json_mode=True)
        if ferr:
            break
        try:
            f = json.loads(fix)
            c2 = (f.get("content") or "").strip()
        except Exception:
            break
        if not c2 or len(_write_lack(p, c2)) >= len(lack):
            break                       # 没改好就别越改越乱，保住上一版
        content, d["used"] = c2, f.get("used") or d.get("used")

    words = len(re.sub(r"\s", "", content))

    # 「用了哪些素材」——**能自己数出来的就别问 AI**。
    # AI 自报这份清单两头都不靠谱：会把没用的报上来（虚报），也会用了不报（漏报，实测正文里
    # 明明有提法和成语，它一个都不提）。所以：
    #   · 成语/提法/理论/金句/概括句/衔接表达 —— 词或句子是确定的，直接回正文里扫，谁在就是谁
    #   · 事例 —— 只能靠 AI 指认（它是被改写着用进去的，没法精确匹配），但仍要过一遍核对
    ai_used = set()
    for i in (d.get("used") or []):
        try:
            ai_used.add(int(i) - 1)
        except Exception:
            pass
    used = []
    for k, (sec, text) in enumerate(idx):
        fuzzy = sec.startswith("人物事例")          # 事例这一档没法精确匹配
        if fuzzy and k not in ai_used:
            continue
        if _used_hit(text, content):
            used.append({"sec": sec, "text": text})
    e = {"mode": mode, "date": date, "topic": (d.get("topic") or "").strip(),
         "title": (d.get("title") or "").strip(), "outline": json.dumps(d.get("outline") or [],
                                                                        ensure_ascii=False),
         "content": content, "words": words,
         "used": json.dumps(used, ensure_ascii=False), "note": (d.get("note") or "").strip()}
    db.execute("INSERT OR REPLACE INTO daily_essays"
               "(id,mode,date,topic,title,outline,content,words,used,note) VALUES("
               "(SELECT id FROM daily_essays WHERE mode=? AND date=?),?,?,?,?,?,?,?,?,?)",
               (mode, date, mode, date, e["topic"], e["title"], e["outline"],
                e["content"], e["words"], e["used"], e["note"]))
    db.commit()
    e["id"] = db.execute("SELECT id FROM daily_essays WHERE mode=? AND date=?",
                         (mode, date)).fetchone()[0]
    return e, None


def _e_row(r):
    d = dict(r)
    for k in ("outline", "used"):        # 应用文的 outline 存的是逐段批注 segs
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except Exception:
            d[k] = []
    try:
        d["spec"] = json.loads(d.get("spec") or "{}")
    except Exception:
        d["spec"] = {}
    return d


# ---------------------------------------------------------------- 应用文成文
# 应用文和大作文**根本不是一回事**：大作文考「怎么论证」，应用文考「格式 + 要点 + 语言得体」。
# 所以不能照搬那套「给一堆素材让它写」——必须先定三件事：
#   ① 文种（通知？倡议书？讲话稿？）—— 决定格式骨架和语气
#   ② 发文场景（就什么事发文）    —— 决定要点从哪来
#   ③ 我是谁 / 写给谁            —— 决定称谓、语气、能不能用「请遵照执行」这种话
# 产出也不一样：正文之外**必须给逐段批注**（这段是哪个部件、为什么这么写），
# 不然就又是一篇「看完不知道怎么学」的范文。
# 文种按「考什么」分四大类。每种都带一个**示范情景**（demo）——
# 第一次一键铺开时就用它，目的是先把「这个文种长什么样、格式怎么摆」看明白；
# 之后再针对同一文种换话题积累。
GW_DOCTYPES = [
    # ---- 宣传演讲类：面向人，讲究感染力和现场感 ----
    dict(k="讲话稿", cat="宣传演讲类", d="领导在某场合讲，有听众、有现场感",
         fmt="标题 / 称谓（同志们）/ 正文（开场→分条讲→结尾鼓劲）/ 无落款", min=500, max=800,
         demo=dict(scene="全区基层治理推进会", role="区政府分管副区长", audience="各街道、各部门负责同志")),
    dict(k="宣传稿", cat="宣传演讲类", d="贴在社区、发在公众号，给群众看的",
         fmt="标题 / 正文（引出→讲清楚→号召）/ 落款", min=400, max=600,
         demo=dict(scene="垃圾分类进社区", role="社区居委会工作人员", audience="全体社区居民")),
    dict(k="公开信", cat="宣传演讲类", d="以组织名义写给公众，语气恳切、有来有往",
         fmt="标题 / 称谓 / 正文（缘由→说明→呼吁）/ 落款（署名+日期）", min=400, max=600,
         demo=dict(scene="致全市市民的文明养犬公开信", role="市城市管理局", audience="全体市民")),
    dict(k="新闻稿", cat="宣传演讲类", d="报道一件事，客观、有导语、有数据和引语",
         fmt="标题（实题）/ 导语（何时·何地·何事·何果）/ 主体（展开+数据+引语）/ 结语", min=400, max=600,
         demo=dict(scene="我区数字政务服务大厅正式启用", role="区融媒体中心记者", audience="社会公众")),
    dict(k="倡议书", cat="宣传演讲类", d="面向公众发出号召，靠感染力不靠命令",
         fmt="标题 / 称谓 / 正文（缘由→倡议内容分条→号召）/ 落款", min=400, max=600,
         demo=dict(scene="节约用水", role="市水务局", audience="全体市民")),
    # ---- 总结说明类：面向上级/同行，讲究条理和成效 ----
    dict(k="汇报", cat="总结说明类", d="把一段工作向上级说清楚：做了什么、效果如何、下一步",
         fmt="标题 / 称谓 / 正文（概述→做法分条→成效→下一步）/ 落款", min=500, max=800,
         demo=dict(scene="老旧小区改造工作", role="区住建局", audience="市住建局")),
    dict(k="调研报告", cat="总结说明类", d="调查了什么、发现什么问题、建议怎么办",
         fmt="标题 / 正文（背景→现状→问题→建议）/ 落款", min=500, max=800,
         demo=dict(scene="农村电商发展现状调研", role="县商务局调研组", audience="县政府")),
    dict(k="简报", cat="总结说明类", d="短平快，一件事一页纸，给上级看",
         fmt="标题 / 正文（概述→做法分条→成效）/ 落款", min=400, max=600,
         demo=dict(scene="防汛应急演练", role="县应急管理局", audience="县委县政府")),
    dict(k="案例介绍", cat="总结说明类", d="讲一个能被别人学走的做法：背景→做法→成效→启示",
         fmt="标题 / 正文（背景→做法→成效→启示）", min=400, max=600,
         demo=dict(scene="某镇「一网通办」便民服务经验", role="镇政府办公室", audience="全县各乡镇")),
    dict(k="编者按", cat="总结说明类", d="放在文章前面的一小段，点题+评价+引导读下去",
         fmt="短标题或无标题 / 正文（点明主题→评价意义→引导阅读）", min=200, max=400,
         demo=dict(scene="为一组基层减负报道写编者按", role="报社编辑", audience="读者")),
    # ---- 方案建议类：面向执行，讲究可落地 ----
    dict(k="方案", cat="方案建议类", d="怎么干的通盘安排：目标、措施、分工、保障",
         fmt="标题 / 正文（指导思想→工作目标→主要措施→组织保障）/ 落款", min=500, max=800,
         demo=dict(scene="社区养老服务提升行动", role="街道办事处", audience="辖区各社区")),
    dict(k="建议书", cat="方案建议类", d="向某单位提意见，要有理有据、可执行",
         fmt="标题 / 称谓 / 正文（问题→建议分条→结语）/ 落款", min=400, max=600,
         demo=dict(scene="改善校园周边交通秩序", role="学校家长委员会", audience="区交警大队")),
    dict(k="通知", cat="方案建议类", d="上级发给下级，告知事项并要求落实",
         fmt="标题（发文机关+事由+文种）/ 主送机关 / 正文（缘由→事项→要求）/ 落款", min=400, max=600,
         demo=dict(scene="开展安全生产大检查", role="市安全生产委员会办公室", audience="各县区、各成员单位")),
    # ---- 观点主张类：面向读者，讲究观点鲜明 ----
    dict(k="短评", cat="观点主张类", d="就一件事表态：观点鲜明、篇幅短、有回味",
         fmt="标题 / 正文（亮观点→析原因→提办法）", min=300, max=500,
         demo=dict(scene="如何看待「指尖上的形式主义」", role="评论员", audience="读者")),
]
GW_CATS = ["宣传演讲类", "总结说明类", "方案建议类", "观点主张类"]
GW_MAP = {d["k"]: d for d in GW_DOCTYPES}


@app.get("/api/write/gwspec")
def write_gwspec():
    """文种清单 + 推荐的发文场景（从最近的概括句话题和时政标题里来，不用自己想）。"""
    db = get_db()
    scenes = [r[0] for r in db.execute(
        "SELECT DISTINCT topic FROM gaikuo_items WHERE topic!='' ORDER BY date DESC LIMIT 10")]
    for r in db.execute("SELECT title FROM news_items ORDER BY id DESC LIMIT 6"):
        t = (r[0] or "").split("｜")[-1].strip()
        if t and len(t) <= 22 and t not in scenes:
            scenes.append(t)
    return jsonify({"doctypes": GW_DOCTYPES, "cats": GW_CATS, "scenes": scenes[:12]})


def _gen_yingyong(db, spec):
    """form='full' 出完整范文；form='outline' 出**提纲纲要**。

    提纲纲要**本身不是文种**，是一种呈现方式（框架式、要点式），任何文种都能套。
    所以它和范文共用一套「文种 + 场景 + 身份」，只是产出从「成篇的文章」换成「骨架 + 要点」。
    先看提纲再看范文，才知道一篇文章是怎么长出来的。"""
    doctype = spec.get("doctype") or "通知"
    if doctype not in GW_MAP:
        return None, (jsonify({"error": "不认识这个文种"}), 400)
    form = "outline" if spec.get("form") == "outline" else "full"
    g = GW_MAP[doctype]
    demo = g["demo"]
    scene = (spec.get("scene") or "").strip() or demo["scene"]
    role = (spec.get("role") or "").strip() or demo["role"]
    audience = (spec.get("audience") or "").strip() or demo["audience"]
    desc, fmt, wmin, wmax = g["d"], g["fmt"], g["min"], g["max"]

    # 公文规范表述按「结构部件」归好类了（开头·缘由 / 主体·举措 / 结尾·号召…），正好是骨架
    gw = [dict(r) for r in db.execute(
        "SELECT scene, phrases, doctype FROM gongwen_items ORDER BY id")]
    pool = "\n".join("· 【%s】%s" % (x["scene"], x["phrases"]) for x in gw)
    # 场景相关的素材（有就用，没有不强求）
    kw = "%" + scene[:6] + "%"
    facts = [dict(r) for r in db.execute(
        "SELECT sentence FROM gaikuo_items WHERE topic LIKE ? OR sentence LIKE ? LIMIT 5", (kw, kw))]
    quotes = [dict(r) for r in db.execute(
        "SELECT quote FROM xiyu_items WHERE quote LIKE ? LIMIT 3", (kw,))]

    head = ("写一篇申论**应用文**范文。\n\n" if form == "full" else
            "给这个文种写一份**提纲纲要**。\n"
            "⚠️ 提纲**不是**缩写版的文章：它是**框架式、要点式**的呈现——把骨架摆出来，"
            "每个部件下面用短句列要点（这一块放什么、写到什么程度、用哪种表述），"
            "**不要写成成篇的段落**。目的是让人一眼看清「这个文种由哪几块组成、每块该放什么」。\n\n")

    setting = (
        "【题目设定】\n"
        "· 文种：%s（%s）\n"
        "· 就什么事发文：%s\n"
        "· 我的身份：%s\n"
        "· 写给谁看：%s\n"
        "· 格式骨架：%s\n"
        "· %s\n\n"
        "【可用的规范表述】（公文的「零件」，按结构部件归好类了，请对号入座地用）\n%s\n\n"
        "%s%s"
        % (doctype, desc, scene, role, audience, fmt,
           ("字数：%d~%d 字（正文，不含标题落款）" % (wmin, wmax)) if form == "full"
           else "提纲总字数控制在 300 字以内，要点短、密度高",
           pool,
           ("【这个话题的规范表述】\n" + "\n".join("· " + f["sentence"] for f in facts) + "\n\n") if facts else "",
           ("【可用金句】\n" + "\n".join("· " + q["quote"] for q in quotes) + "\n\n") if quotes else ""))

    if form == "full":
        req = (
            "【硬要求】\n"
            "1. **格式必须对**：该有标题就有标题、该有称谓就有称谓、该有落款就有落款。"
            "落款单位用「××」代替（不要编真单位名）。\n"
            "2. **语气必须对身份**：上级发下级可以「请遵照执行」；面向群众的倡议书、公开信"
            "**不能用命令口气**，要靠感染力；讲话稿要有现场感（同志们、大家）；"
            "新闻稿要客观，不许抒情。\n"
            "3. 正文要点**分条写**（一是…二是…／1. 2. 3.），每条先亮做法再讲怎么落地，不要空喊。\n"
            "4. 上面的规范表述要**用进去**，别自己造大白话。\n\n"
            "【最重要的一条】除了正文，还要给**逐段批注**：把全文拆成若干段，每段说清楚\n"
            "· part：这一段是哪个部件（标题 / 称谓 / 开头·缘由 / 主体·举措 / 主体·成效 / "
            "结尾·号召 / 结尾·要求 / 落款 …）\n"
            "· text：这一段的原文（**从正文里逐字复制**，一字不差）\n"
            "· why：为什么这么写、阅卷看的是什么（一句话，讲考点，别复述原文）\n"
            "—— 没有批注的范文，看完还是不知道怎么学。\n\n"
            "只输出 JSON：\n"
            '{"title":"","content":"全文（含标题、称谓、落款，用 \\n 分行）",'
            '"segs":[{"part":"","text":"","why":""}],'
            '"note":"一句话说明这个文种最容易丢分的地方"}')
    else:
        req = (
            "【硬要求】\n"
            "1. **按格式骨架逐块列**，一块都不能少（该有称谓就写「称谓：…」，该有落款就写「落款：…」）。\n"
            "2. 每块下面用「· 」列 2~4 条要点，每条是**短句**（10~25 字），说清这一块放什么、"
            "怎么起头。**不要写成完整段落，不要展开论述**。\n"
            "3. 主体部分要标出**分条的条数和每条讲什么**（一是…／二是…／三是…）。\n"
            "4. 该用规范表述的地方，直接把表述写进要点里（如「开头用『为深入贯彻…、结合…实际』」）。\n\n"
            "还要给**逐块说明**：\n"
            "· part：这一块是哪个部件\n"
            "· text：提纲里这一块的原文（**逐字复制**，一字不差）\n"
            "· why：这一块阅卷看什么、最容易丢分在哪（一句话）\n\n"
            "只输出 JSON：\n"
            '{"title":"","content":"提纲全文（用 \\n 分行，块名顶格、要点用「· 」缩进）",'
            '"segs":[{"part":"","text":"","why":""}],'
            '"note":"一句话说明这个文种的提纲最关键的是哪一块"}')

    prompt = head + setting + req

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论阅卷组的应用文范文作者。格式是第一位的，"
                                       "语气要合身份。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.5, max_tokens=3500, timeout=300, json_mode=True)
    if err:
        return None, err
    try:
        d = json.loads(rep)
    except Exception:
        return None, (jsonify({"error": "AI 返回格式异常，请重试"}), 502)
    content = (d.get("content") or "").strip()
    if not content:
        return None, (jsonify({"error": "AI 没写出正文，请重试"}), 502)

    # 批注的 text 必须真的来自正文，否则点了跳不过去、也说明它在瞎编
    flat = re.sub(r"\s", "", content)
    segs = []
    for s in (d.get("segs") or []):
        t = (s.get("text") or "").strip()
        if not t or re.sub(r"\s", "", t) not in flat:
            continue
        segs.append({"part": (s.get("part") or "").strip()[:12],
                     "text": t, "why": (s.get("why") or "").strip()[:140]})
    # 用了哪些规范表述：直接回正文里扫（别问 AI，它虚报也漏报）
    used = []
    for x in gw:
        hit = [p for p in re.split(r"[、,，]", x["phrases"])
               if len(p.replace("…", "").strip()) >= 2
               and all(y in content for y in p.split("…") if len(y.strip()) >= 2)]
        if hit:
            used.append({"sec": x["scene"], "text": "、".join(hit[:4])})

    words = len(re.sub(r"\s", "", content))
    date = time.strftime("%Y-%m-%d %H:%M:%S")
    db.execute("INSERT INTO daily_essays(mode,date,topic,title,outline,content,words,used,note,spec) "
               "VALUES('yingyong',?,?,?,?,?,?,?,?,?)",
               (date, doctype, (d.get("title") or "").strip(),
                json.dumps(segs, ensure_ascii=False), content, words,
                json.dumps(used, ensure_ascii=False), (d.get("note") or "").strip(),
                json.dumps({"doctype": doctype, "scene": scene, "role": role,
                            "audience": audience, "form": form,
                            "cat": g["cat"]}, ensure_ascii=False)))
    db.commit()
    eid = db.execute("SELECT id FROM daily_essays WHERE mode='yingyong' AND date=?", (date,)).fetchone()[0]
    return eid, None


@app.get("/api/write/yylist")
def write_yylist():
    """按「类别 → 文种」把已有的范文和提纲摆出来 —— 哪个文种还没见过，一眼看见。"""
    rows = [_e_row(r) for r in get_db().execute(
        "SELECT * FROM daily_essays WHERE mode='yingyong' ORDER BY id DESC")]
    by = {}
    for r in rows:
        k = (r["spec"] or {}).get("doctype") or r["topic"]
        by.setdefault(k, {"full": [], "outline": []})
        f = (r["spec"] or {}).get("form") or "full"
        by[k][f].append({"id": r["id"], "title": r["title"],
                         "scene": (r["spec"] or {}).get("scene") or "", "words": r["words"]})
    cats = []
    for c in GW_CATS:
        ds = []
        for g in GW_DOCTYPES:
            if g["cat"] != c:
                continue
            got = by.get(g["k"]) or {"full": [], "outline": []}
            ds.append({"k": g["k"], "d": g["d"], "fmt": g["fmt"],
                       "full": got["full"], "outline": got["outline"]})
        cats.append({"cat": c, "doctypes": ds})
    n_full = sum(1 for g in GW_DOCTYPES if (by.get(g["k"]) or {}).get("full"))
    n_out = sum(1 for g in GW_DOCTYPES if (by.get(g["k"]) or {}).get("outline"))
    return jsonify({"cats": cats, "total": len(GW_DOCTYPES),
                    "have_full": n_full, "have_outline": n_out})


@app.post("/api/write/yingyong/batch")
def write_yy_batch():
    """第一次用：把**每个文种**各铺一篇（范文 + 提纲），先把格式和结构看明白。
       之后就是针对同一文种换话题积累了，不用再跑这个。"""
    db = get_db()
    have = set()
    for r in db.execute("SELECT spec FROM daily_essays WHERE mode='yingyong'"):
        try:
            sp = json.loads(r[0] or "{}")
            have.add((sp.get("doctype"), sp.get("form") or "full"))
        except Exception:
            pass
    todo = [(g["k"], f) for g in GW_DOCTYPES for f in ("outline", "full")
            if (g["k"], f) not in have]                   # 先出提纲再出范文：先看骨架，再看成品
    if not todo:
        return jsonify({"error": "所有文种的提纲和范文都齐了"}), 400
    tid = _bg_new(db, "yingyong", "铺开应用文 %d 篇" % len(todo), len(todo))

    def run():
        con = sqlite3.connect(DB, timeout=60)
        con.row_factory = sqlite3.Row
        ok = 0
        try:
            for i, (dt, form) in enumerate(todo):
                _bg_set(con, tid, status="running", progress=i,
                        message="正在写 %s·%s（%d/%d）"
                                % (dt, "提纲" if form == "outline" else "范文", i + 1, len(todo)))
                try:
                    with app.app_context():
                        _, err = _gen_yingyong(con, {"doctype": dt, "form": form})
                    if not err:
                        ok += 1
                except Exception:
                    pass                      # 单篇失败不拖垮整批，再点一次会补上没写的
            bad = len(todo) - ok
            _bg_set(con, tid, status="done", progress=len(todo),
                    message="写好 %d 篇%s" % (ok, "（%d 篇失败，可再点一次补）" % bad if bad else ""))
        except Exception as ex:
            _bg_set(con, tid, status="error", message=str(ex)[:200])
        finally:
            con.close()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"task": tid, "total": len(todo)}), 202


@app.post("/api/write/yingyong")
def write_yingyong():
    db = get_db()
    eid, err = _gen_yingyong(db, request.get_json(silent=True) or {})
    if err:
        return err
    return jsonify(_e_row(db.execute("SELECT * FROM daily_essays WHERE id=?", (eid,)).fetchone()))


@app.get("/api/write/days")
def write_days():
    """每日成文：列出有素材的日期 + 每天写了没有。"""
    db = get_db()
    _sucai_import(db)
    rows = db.execute(
        "SELECT s.date, COUNT(*) n, "
        "SUM(CASE WHEN s.kind='衔接表达' THEN 1 ELSE 0 END) nl, "
        "e.id eid, e.title, e.topic, e.words "
        "FROM sucai_items s LEFT JOIN daily_essays e ON e.mode='daily' AND e.date=s.date "
        "GROUP BY s.date ORDER BY s.date DESC").fetchall()
    return jsonify({"days": [dict(r) for r in rows]})


@app.post("/api/write/daily")
def write_daily():
    d = request.get_json(silent=True) or {}
    date = (d.get("date") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return jsonify({"error": "日期不对"}), 400
    db = get_db()
    if not d.get("force"):
        r = db.execute("SELECT * FROM daily_essays WHERE mode='daily' AND date=?", (date,)).fetchone()
        if r:
            return jsonify(_e_row(r))
    e, err = _write_gen(db, "daily", date)
    if err:
        return err
    return jsonify(_e_row(db.execute("SELECT * FROM daily_essays WHERE id=?", (e["id"],)).fetchone()))


@app.post("/api/write/backfill")
def write_backfill():
    """把过去攒下的素材一天一篇全部补齐（22 天 × 一次 AI，得在后台慢慢跑）。"""
    db = get_db()
    _sucai_import(db)
    todo = [r[0] for r in db.execute(
        "SELECT DISTINCT s.date FROM sucai_items s "
        "WHERE NOT EXISTS(SELECT 1 FROM daily_essays e WHERE e.mode='daily' AND e.date=s.date) "
        "ORDER BY s.date")]
    if not todo:
        return jsonify({"error": "已经全部写完了"}), 400
    tid = _bg_new(db, "write", "补齐每日成文 %d 天" % len(todo), len(todo))

    def run():
        con = sqlite3.connect(DB, timeout=60)
        con.row_factory = sqlite3.Row
        ok = 0
        try:
            for i, dt in enumerate(todo):
                _bg_set(con, tid, status="running", progress=i,
                        message="正在写 %s（第 %d/%d 篇）" % (dt, i + 1, len(todo)))
                try:
                    with app.app_context():
                        e, err = _write_gen(con, "daily", dt)
                    if not err:
                        ok += 1
                except Exception:
                    pass                      # 单天失败不拖垮整批，下次再点一次补
            bad = len(todo) - ok
            _bg_set(con, tid, status="done", progress=len(todo),
                    message="写好 %d 篇%s" % (ok, "（%d 天失败，可再点一次补）" % bad if bad else ""))
        except Exception as ex:
            _bg_set(con, tid, status="error", message=str(ex)[:200])
        finally:
            con.close()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"task": tid, "total": len(todo)}), 202


@app.get("/api/write/task/<int:tid>")
def write_task(tid):
    r = get_db().execute("SELECT * FROM bg_tasks WHERE id=? AND user_id=?", (tid, uid())).fetchone()
    if not r:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(dict(r))


@app.post("/api/write/compose")
def write_compose():
    """综合应用：AI 自己选题，跨全部素材库挑最合适的，每天一篇。"""
    d = request.get_json(silent=True) or {}
    date = time.strftime("%Y-%m-%d")
    db = get_db()
    if not d.get("force"):
        r = db.execute("SELECT * FROM daily_essays WHERE mode='compose' AND date=?", (date,)).fetchone()
        if r:
            return jsonify(_e_row(r))
    e, err = _write_gen(db, "compose", date)
    if err:
        return err
    return jsonify(_e_row(db.execute("SELECT * FROM daily_essays WHERE id=?", (e["id"],)).fetchone()))


@app.get("/api/write/list")
def write_list():
    mode = (request.args.get("mode") or "compose").strip()
    rows = get_db().execute(
        "SELECT id,mode,date,topic,title,words,created_at FROM daily_essays "
        "WHERE mode=? ORDER BY date DESC LIMIT 200", (mode,)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.get("/api/write/<int:eid>")
def write_get(eid):
    r = get_db().execute("SELECT * FROM daily_essays WHERE id=?", (eid,)).fetchone()
    if not r:
        return jsonify({"error": "文章不存在"}), 404
    return jsonify(_e_row(r))


@app.delete("/api/write/<int:eid>")
def write_del(eid):
    db = get_db()
    db.execute("DELETE FROM daily_essays WHERE id=?", (eid,))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 题库（四川省考卷面）
@app.get("/api/quiz/sets")
def quiz_sets():
    db = get_db()
    rows = db.execute(
        "SELECT s.id, s.name, s.kind, s.created_at,"
        "(SELECT COUNT(*) FROM quiz_questions q WHERE q.set_id=s.id) total,"
        "(SELECT COUNT(*) FROM quiz_answers a JOIN quiz_questions q2 ON q2.id=a.qid "
        " WHERE a.user_id=? AND q2.set_id=s.id) done,"
        "(SELECT COUNT(*) FROM quiz_answers a JOIN quiz_questions q3 ON q3.id=a.qid "
        " WHERE a.user_id=? AND q3.set_id=s.id AND a.correct=1) right_n "
        "FROM quiz_sets s ORDER BY s.id DESC", (uid(), uid())).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.get("/api/quiz/sets/<int:sid>")
def quiz_set_detail(sid):
    db = get_db()
    s = db.execute("SELECT * FROM quiz_sets WHERE id=?", (sid,)).fetchone()
    if not s:
        return jsonify({"error": "未找到"}), 404
    qs = db.execute("SELECT id,seq,module,qtype,material,question,options,answer,explanation "
                    "FROM quiz_questions WHERE set_id=? ORDER BY seq", (sid,)).fetchall()
    mine = {r["qid"]: dict(r) for r in db.execute(
        "SELECT qid, choice, correct FROM quiz_answers WHERE user_id=? AND set_id=?", (uid(), sid))}
    items = []
    for q in qs:
        d = dict(q)
        try:
            d["options"] = json.loads(d["options"] or "[]")
        except Exception:
            d["options"] = []
        m = mine.get(q["id"])
        d["my_choice"] = m["choice"] if m else ""
        items.append(d)
    return jsonify({"id": s["id"], "name": s["name"], "kind": s["kind"], "questions": items})


@app.post("/api/quiz/answer")
def quiz_answer():
    data = request.get_json(silent=True) or {}
    qid = int(data.get("qid") or 0)
    choice = (data.get("choice") or "").strip()
    db = get_db()
    q = db.execute("SELECT * FROM quiz_questions WHERE id=?", (qid,)).fetchone()
    if not q:
        return jsonify({"error": "题目不存在"}), 404
    correct = 1 if choice and choice == (q["answer"] or "") else 0
    db.execute("INSERT OR REPLACE INTO quiz_answers(user_id,set_id,qid,choice,correct) VALUES(?,?,?,?,?)",
               (uid(), q["set_id"], qid, choice, correct))
    db.commit()
    return jsonify({"correct": bool(correct), "answer": q["answer"], "explanation": q["explanation"] or ""})


# ---------------------------------------------------------------- 习语金句 / 经典著作
@app.get("/api/xiyu")
def xiyu_list():
    cat = (request.args.get("cat") or "").strip()
    db = get_db()
    where, args = "", []
    if cat and cat != "全部":
        where = "WHERE category=?"; args = [cat]
    rows = db.execute("SELECT * FROM xiyu_items %s ORDER BY date DESC, id LIMIT 200" % where, args).fetchall()
    counts = {r[0]: r[1] for r in db.execute("SELECT category, COUNT(*) FROM xiyu_items GROUP BY category")}
    return jsonify({"items": [dict(r) for r in rows], "counts": counts})


@app.get("/api/works")
def works_list():
    rows = get_db().execute(
        "SELECT id, book, ord, title, length(content) chars,"
        "(interpretation IS NOT NULL AND interpretation<>'') has_ai "
        "FROM works ORDER BY book, ord").fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.get("/api/works/<int:wid>")
def works_detail(wid):
    r = get_db().execute("SELECT * FROM works WHERE id=?", (wid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    return jsonify({"id": r["id"], "book": r["book"], "title": r["title"],
                    "content": r["content"] or "", "interpretation": r["interpretation"] or ""})


@app.post("/api/works/<int:wid>/ai")
def works_ai(wid):
    r = get_db().execute("SELECT * FROM works WHERE id=?", (wid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    force = (request.get_json(silent=True) or {}).get("force")
    if r["interpretation"] and not force:
        return jsonify({"content": r["interpretation"], "cached": True})
    excerpt = (r["content"] or "")[:8000]
    prompt = (
        "下面是《%s》中《%s》一文（可能为节选）。请面向公务员考试考生，用简体中文、Markdown 输出"
        "「导读解读」，分节：\n## 一、写作背景\n## 二、核心观点（分条）\n"
        "## 三、名句与经典表述（摘原文）\n## 四、公考如何运用（申论/面试引用角度）\n"
        "要求准确、精炼、完整不截断。\n\n全文：\n%s") % (r["book"], r["title"], excerpt)
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是理论功底扎实的公考辅导老师，解读准确精炼，用简体中文 Markdown。"},
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=4000)
    if err:
        return err
    db = get_db()
    db.execute("UPDATE works SET interpretation=? WHERE id=?", (reply, wid))
    db.commit()
    return jsonify({"content": reply, "cached": False})


# ---------------------------------------------------------------- 全局 AI 会话中心
@app.get("/api/aichat/home")
def aichat_home():
    db = get_db()
    db.execute("DELETE FROM ai_chats WHERE user_id=? AND created_at < datetime('now','localtime','-1 hour') "
               "AND NOT EXISTS(SELECT 1 FROM ai_msgs m WHERE m.chat_id=ai_chats.id)", (uid(),))
    db.commit()
    chats = db.execute(
        "SELECT c.id, c.title, c.updated_at, c.project_id, c.starred, p.name pname FROM ai_chats c "
        "LEFT JOIN ai_projects p ON p.id=c.project_id "
        "WHERE c.user_id=? AND EXISTS(SELECT 1 FROM ai_msgs m WHERE m.chat_id=c.id) "
        "ORDER BY c.starred DESC, c.updated_at DESC LIMIT 50", (uid(),)).fetchall()
    projects = db.execute(
        "SELECT p.id, p.name, p.instructions,"
        "(SELECT COUNT(*) FROM ai_chats c WHERE c.project_id=p.id) cnt "
        "FROM ai_projects p WHERE p.user_id=? ORDER BY p.id DESC", (uid(),)).fetchall()
    return jsonify({"chats": [dict(r) for r in chats], "projects": [dict(r) for r in projects]})


@app.post("/api/aichat/chats")
def aichat_new():
    data = request.get_json(silent=True) or {}
    pid = data.get("project_id")
    db = get_db()
    cur = db.execute("INSERT INTO ai_chats(user_id,project_id,title) VALUES(?,?,?)",
                     (uid(), pid, ""))
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.get("/api/aichat/chats/<int:cid>")
def aichat_get(cid):
    db = get_db()
    c = db.execute("SELECT * FROM ai_chats WHERE id=? AND user_id=?", (cid, uid())).fetchone()
    if not c:
        return jsonify({"error": "未找到"}), 404
    msgs = db.execute("SELECT role, content FROM ai_msgs WHERE chat_id=? ORDER BY id", (cid,)).fetchall()
    return jsonify({"id": c["id"], "title": c["title"], "project_id": c["project_id"],
                    "msgs": [dict(r) for r in msgs]})


@app.put("/api/aichat/chats/<int:cid>")
def aichat_update(cid):
    data = request.get_json(silent=True) or {}
    db = get_db()
    c = db.execute("SELECT * FROM ai_chats WHERE id=? AND user_id=?", (cid, uid())).fetchone()
    if not c:
        return jsonify({"error": "未找到"}), 404
    if "title" in data:
        t = (data.get("title") or "").strip()[:40]
        if t:
            db.execute("UPDATE ai_chats SET title=? WHERE id=?", (t, cid))
    if "project_id" in data:
        pid = data.get("project_id")
        db.execute("UPDATE ai_chats SET project_id=? WHERE id=?", (pid, cid))
    if "starred" in data:
        db.execute("UPDATE ai_chats SET starred=? WHERE id=?", (1 if data.get("starred") else 0, cid))
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/aichat/chats/<int:cid>")
def aichat_del(cid):
    db = get_db()
    db.execute("DELETE FROM ai_msgs WHERE chat_id IN (SELECT id FROM ai_chats WHERE id=? AND user_id=?)", (cid, uid()))
    db.execute("DELETE FROM ai_chats WHERE id=? AND user_id=?", (cid, uid()))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/aichat/chats/<int:cid>/send")
def aichat_send(cid):
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "请输入内容"}), 400
    db = get_db()
    c = db.execute("SELECT * FROM ai_chats WHERE id=? AND user_id=?", (cid, uid())).fetchone()
    if not c:
        return jsonify({"error": "会话不存在"}), 404
    sys_prompt = "你是「公考助手」里的 AI 学习助理，服务正在备考公务员的用户。回答简洁、准确、条理清晰，用简体中文。"
    if c["project_id"]:
        p = db.execute("SELECT * FROM ai_projects WHERE id=?", (c["project_id"],)).fetchone()
        if p and (p["instructions"] or "").strip():
            sys_prompt += "\n\n【本项目要求】" + p["instructions"].strip()
    stats = _user_stats()
    if stats:
        sys_prompt += "\n\n" + stats
    hist = db.execute("SELECT role, content FROM ai_msgs WHERE chat_id=? ORDER BY id DESC LIMIT 20",
                      (cid,)).fetchall()
    msgs = [{"role": r["role"], "content": r["content"]} for r in reversed(hist)]
    msgs.append({"role": "user", "content": content})
    reply, err = _ai_call_or_error([{"role": "system", "content": sys_prompt}] + msgs,
                                   temperature=0.6, max_tokens=2000)
    if err:
        return err
    db.execute("INSERT INTO ai_msgs(chat_id,role,content) VALUES(?,?,?)", (cid, "user", content))
    db.execute("INSERT INTO ai_msgs(chat_id,role,content) VALUES(?,?,?)", (cid, "assistant", reply))
    title = c["title"]
    if not title:
        title = content[:24]
        db.execute("UPDATE ai_chats SET title=? WHERE id=?", (title, cid))
    db.execute("UPDATE ai_chats SET updated_at=datetime('now','localtime') WHERE id=?", (cid,))
    db.commit()
    return jsonify({"reply": reply, "title": title})


@app.post("/api/aichat/projects")
def aiproj_new():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "请输入项目名"}), 400
    db = get_db()
    cur = db.execute("INSERT INTO ai_projects(user_id,name,instructions) VALUES(?,?,?)",
                     (uid(), name, (data.get("instructions") or "").strip()))
    db.commit()
    return jsonify({"id": cur.lastrowid, "name": name}), 201


@app.delete("/api/aichat/projects/<int:pid>")
def aiproj_del(pid):
    db = get_db()
    db.execute("UPDATE ai_chats SET project_id=NULL WHERE project_id=? AND user_id=?", (pid, uid()))
    db.execute("DELETE FROM ai_projects WHERE id=? AND user_id=?", (pid, uid()))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 常识积累（7板块）
_CS_META = {}
try:
    with open(os.path.join(BASE, "changshi_meta.json"), encoding="utf-8") as _f:
        _CS_META = json.load(_f)
except Exception:
    _CS_META = {"tiers": [], "boards": {}}


# ---------------------------------------------------------------- 古诗文每日推荐
# 高频 & 适合申论的古诗文标题池（命中即抬高 freq，并作为每日推荐来源）
CLASSIC_HOT = [
    "登鹳雀楼", "望岳", "登高", "行路难", "将进酒", "茅屋为秋风所破歌", "石灰吟", "竹石",
    "己亥杂诗", "赤壁", "过零丁洋", "题西林壁", "游山西村", "观书有感", "水调歌头", "念奴娇",
    "满江红", "破阵子", "永遇乐", "定风波", "登飞来峰", "泊船瓜洲", "酬乐天扬州初逢席上见赠",
    "劝学", "爱莲说", "陋室铭", "岳阳楼记", "醉翁亭记", "出师表", "论语", "孟子", "荀子",
    "生于忧患死于安乐", "鱼我所欲也", "曹刿论战", "得道多助失道寡助", "赋得古原草送别",
    "无题", "春望", "闻官军收河南河北", "秋词", "浣溪沙", "卜算子", "青玉案", "沁园春",
]


def _ensure_classic_freq(db):
    if db.execute("SELECT COUNT(*) FROM classics WHERE freq>0").fetchone()[0]:
        return
    # 首次：命中高频标题的抬到高分；其余名家名篇给中分
    for t in CLASSIC_HOT:
        db.execute("UPDATE classics SET freq=100 WHERE title LIKE ?", ("%" + t + "%",))
    hot_authors = ["李白", "杜甫", "白居易", "苏轼", "辛弃疾", "李清照", "王安石", "陆游",
                   "王维", "孟浩然", "刘禹锡", "杜牧", "李商隐", "范仲淹", "毛泽东"]
    for a in hot_authors:
        db.execute("UPDATE classics SET freq=freq+30 WHERE author LIKE ?", ("%" + a + "%",))
    # 四书五经/蒙学等经典整体抬一档
    db.execute("UPDATE classics SET freq=freq+20 WHERE category IN ('论语','孟子','大学','中庸','诗经','增广贤文')")
    db.commit()


@app.get("/api/classics/daily")
def classics_daily():
    db = get_db()
    _ensure_classic_freq(db)
    today = datetime.now().strftime("%Y-%m-%d")
    sel = ("SELECT d.classic_id, d.apply, d.common, c.title, c.author, c.dynasty, c.category, c.content "
           "FROM classic_daily d JOIN classics c ON c.id=d.classic_id WHERE d.date=?")
    row = db.execute(sel, (today,)).fetchone()
    if not row:
        # 从高频池里按日期确定性选一首（尽量适合申论）
        pool = db.execute("SELECT id FROM classics WHERE freq>=100 ORDER BY id").fetchall()
        if not pool:
            pool = db.execute("SELECT id FROM classics ORDER BY freq DESC, id LIMIT 300").fetchall()
        if not pool:
            return jsonify({"error": "暂无"}), 404
        idx = datetime.now().toordinal() % len(pool)
        cid = pool[idx]["id"]
        db.execute("INSERT OR REPLACE INTO classic_daily(date, classic_id) VALUES(?,?)", (today, cid))
        db.commit()
        row = db.execute(sel, (today,)).fetchone()
    apply_txt, common_txt = row["apply"] or "", row["common"] or ""
    if (not apply_txt or not common_txt) and ai_configured():
        prompt = ("这是《%s》（%s·%s）：\n%s\n\n请输出 JSON："
                  '{"apply":"一句话40字内，说明它适合申论/面试的哪类主题、怎么引用",'
                  '"common":"一句话60字内，本篇在行测常识判断里的常考点：作者朝代/文学地位/名句出处/'
                  '所属文体或流派/易混淆点，任选最可能考的写"}。只输出 JSON。' %
                  (row["title"], row["dynasty"], row["author"], (row["content"] or "")[:200]))
        rep, err = _ai_call_or_error(
            [{"role": "system", "content": "你是公考辅导老师，兼顾申论运用与常识判断考点，精炼实用。"},
             {"role": "user", "content": prompt}], temperature=0.5, max_tokens=260, json_mode=True)
        if not err:
            try:
                d = json.loads(rep)
                apply_txt = (d.get("apply") or apply_txt).strip()
                common_txt = (d.get("common") or common_txt).strip()
                db.execute("UPDATE classic_daily SET apply=?, common=? WHERE date=?",
                           (apply_txt, common_txt, today))
                db.commit()
            except Exception:
                pass
    return jsonify({"id": row["classic_id"], "title": row["title"], "author": row["author"],
                    "dynasty": row["dynasty"], "category": row["category"],
                    "first_line": (row["content"] or "").split("\n")[0],
                    "apply": apply_txt, "common": common_txt})


# ---------------------------------------------------------------- 衔接表达 · 例句
@app.post("/api/sucai/<int:sid>/example")
def sucai_example(sid):
    db = get_db()
    r = db.execute("SELECT * FROM sucai_items WHERE id=?", (sid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    force = bool((request.get_json(silent=True) or {}).get("force"))
    if r["example"] and not force:
        return jsonify({"example": r["example"], "cached": True})
    prompt = ("下面是一句申论写作的衔接表达/万能句式：\n%s\n\n请用它写一个申论语境下的规范例句"
              "（书面化、紧扣治理/民生/发展类主题，30~60字），只输出例句本身。" % r["content"])
    if force and r["example"]:
        prompt += "\n注意：换一个主题和角度，不要写成：" + r["example"]
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论写作辅导老师，例句规范、书面化。"},
         {"role": "user", "content": prompt}], temperature=0.85, max_tokens=200)
    if err:
        return err
    ex = rep.strip()
    db.execute("UPDATE sucai_items SET example=? WHERE id=?", (ex, sid))
    db.commit()
    return jsonify({"example": ex, "cached": False})


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
def _uname(db, u):
    r = db.execute("SELECT username FROM users WHERE id=?", (u,)).fetchone()
    return r["username"] if r else "?"


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
    incoming = [{"id": r["id"], "from_uid": r["from_uid"], "from_name": _uname(db, r["from_uid"]),
                 "kind": r["kind"]} for r in db.execute(
        "SELECT * FROM team_requests WHERE to_uid=? AND status='pending' ORDER BY id DESC", (me,))]
    outgoing = [{"id": r["id"], "to_uid": r["to_uid"], "to_name": _uname(db, r["to_uid"]),
                 "kind": r["kind"]} for r in db.execute(
        "SELECT * FROM team_requests WHERE from_uid=? AND status='pending' ORDER BY id DESC", (me,))]
    return jsonify({"team": tinfo, "incoming": incoming, "outgoing": outgoing,
                    "me": _uname(db, me), "me_id": me, "study": _study_stats(db, me)})


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
                           "VALUES(?,?,'plan',?,?,?)", (txt[:200], _uname(db, u), u, today, tid))
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
@app.get("/api/daily_tasks")
def daily_tasks():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    tpls = db.execute("SELECT * FROM task_templates WHERE user_id=? AND active=1 ORDER BY sort, id",
                      (uid(),)).fetchall()
    done = {r["tpl_id"] for r in db.execute(
        "SELECT tpl_id FROM task_done WHERE user_id=? AND date=?", (uid(), today))}
    items = [{"id": t["id"], "text": t["text"], "done": t["id"] in done} for t in tpls]
    return jsonify({"date": today, "items": items, "done_n": len(done), "total": len(tpls)})


@app.post("/api/daily_tasks/templates")
def daily_task_add():
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return jsonify({"error": "请输入任务"}), 400
    db = get_db()
    cur = db.execute("INSERT INTO task_templates(user_id,text) VALUES(?,?)", (uid(), text[:120]))
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.delete("/api/daily_tasks/templates/<int:tid>")
def daily_task_del(tid):
    db = get_db()
    db.execute("DELETE FROM task_templates WHERE id=? AND user_id=?", (tid, uid()))
    db.execute("DELETE FROM task_done WHERE tpl_id=? AND user_id=?", (tid, uid()))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/daily_tasks/<int:tid>/toggle")
def daily_task_toggle(tid):
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    r = db.execute("SELECT 1 FROM task_done WHERE user_id=? AND tpl_id=? AND date=?",
                   (uid(), tid, today)).fetchone()
    if r:
        db.execute("DELETE FROM task_done WHERE user_id=? AND tpl_id=? AND date=?", (uid(), tid, today))
        on = False
    else:
        db.execute("INSERT OR IGNORE INTO task_done(user_id,tpl_id,date) VALUES(?,?,?)", (uid(), tid, today))
        on = True
    db.commit()
    return jsonify({"done": on})


# ---------------------------------------------------------------- 申论（四大题型讲义 + AI 逐点批改）
try:
    with open(os.path.join(BASE, "shenlun_meta.json"), encoding="utf-8") as _fp:
        _SL_META = json.load(_fp)
except Exception:
    _SL_META = {"types": []}

_SL_TYPES = {t["key"]: t for t in _SL_META.get("types", [])}


@app.get("/api/shenlun/types")
def shenlun_types():
    db = get_db()
    n = db.execute("SELECT COUNT(*) FROM shenlun_grade WHERE user_id=?", (uid(),)).fetchone()[0]
    return jsonify({"types": [{k: v for k, v in t.items() if k != "map"} for t in _SL_META["types"]],
                    "graded": n})


@app.get("/api/shenlun/type/<key>")
def shenlun_type(key):
    t = _SL_TYPES.get(key)
    if not t:
        return jsonify({"error": "没有这个题型"}), 404
    return jsonify(t)


# ---------------------------------------------------------------- 范文推荐（仿真卷 + 全套参考答案）
@app.get("/api/essays/topics")
def essays_topics():
    db = get_db()
    rows = db.execute("SELECT p.id, p.topic, p.spec, p.title, p.words, "
                      "(SELECT COUNT(*) FROM essays e WHERE e.paper_id=p.id) n "
                      "FROM essay_papers p ORDER BY p.id").fetchall()
    specs = _SL_META.get("specs", {})
    return jsonify({"papers": [dict(r, spec_name=specs.get(r["spec"], {}).get("name", "")) for r in rows]})


@app.get("/api/essays")
def essays_list():
    """kind=zuowen 只看大作文范文；kind=yingyong 看应用文/小题的完整题目+参考答案。"""
    kind = (request.args.get("kind") or "").strip()
    topic = (request.args.get("topic") or "").strip()
    w, args = [], []
    if kind == "zuowen":
        w.append("e.qtype='zuowen'")
    elif kind == "yingyong":
        w.append("e.qtype<>'zuowen'")
    if topic:
        w.append("p.topic=?")
        args.append(topic)
    sql = ("SELECT e.id, e.seq, e.qtype, e.type_name, e.stem, e.full, e.word_min, e.word_max, "
           "e.answer_words, e.outline, p.topic, p.title paper_title, p.id paper_id "
           "FROM essays e JOIN essay_papers p ON p.id=e.paper_id "
           + ("WHERE " + " AND ".join(w) if w else "") +
           " ORDER BY p.id, e.seq")
    rows = get_db().execute(sql, args).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.get("/api/essays/<int:eid>")
def essay_detail(eid):
    db = get_db()
    r = db.execute("SELECT e.*, p.topic, p.material, p.title paper_title, p.spec, p.words material_words "
                   "FROM essays e JOIN essay_papers p ON p.id=e.paper_id WHERE e.id=?", (eid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    d = dict(r)
    d["spec_name"] = _SL_META.get("specs", {}).get(d["spec"], {}).get("name", "")
    return jsonify(d)


@app.post("/api/essays/paper/<int:pid>/practice")
def essay_practice(pid):
    """把这套仿真卷复制成一份「我的真题卷」，直接进入逐题作答 + AI 批改。"""
    db = get_db()
    p = db.execute("SELECT * FROM essay_papers WHERE id=?", (pid,)).fetchone()
    if not p:
        return jsonify({"error": "未找到"}), 404
    old = db.execute("SELECT id FROM shenlun_papers WHERE user_id=? AND title=?",
                     (uid(), p["title"])).fetchone()
    if old:
        return jsonify({"id": old["id"], "existed": True})
    cur = db.execute("INSERT INTO shenlun_papers(user_id,title,material,source) VALUES(?,?,?,?)",
                     (uid(), p["title"], p["material"], "范文推荐"))
    npid = cur.lastrowid
    for e in db.execute("SELECT * FROM essays WHERE paper_id=? ORDER BY seq", (pid,)):
        db.execute("INSERT INTO shenlun_questions(paper_id,seq,qtype,type_name,stem,requirement,"
                   "full,word_min,word_max) VALUES(?,?,?,?,?,'',?,?,?)",
                   (npid, e["seq"], e["qtype"], e["type_name"], e["stem"],
                    e["full"], e["word_min"], e["word_max"]))
    db.commit()
    return jsonify({"id": npid, "existed": False}), 201


# ---------------------------------------------------------------- 文档识题：抽出例题 → AI 解答 → 回填成副本
def _bg_new(db, kind, title, total=0):
    cur = db.execute("INSERT INTO bg_tasks(user_id,kind,title,total) VALUES(?,?,?,?)",
                     (uid(), kind, title, total))
    db.commit()
    return cur.lastrowid


def _bg_set(con, tid, **kw):
    if not kw:
        return
    cols = ", ".join("%s=?" % k for k in kw)
    con.execute("UPDATE bg_tasks SET %s, updated_at=datetime('now','localtime') WHERE id=?" % cols,
                list(kw.values()) + [tid])
    con.commit()


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
            except Exception:
                pass   # 视觉失败 → 退回纯文字，别让整批崩掉

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
    _bg_set(con, tid, message="排队中…")
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
        _bg_set(con, tid, total=scan, message="正在读取文字…")

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
            _bg_set(con, tid, progress=p, message="读取第 %d/%d 页" % (p, scan))
        if not cand:
            raise RuntimeError("没在文档里找到像题目的内容（前 %d 页）" % scan)

        # 配了视觉模型：把候选页渲染成图，好让模型「看图做题」（图形推理靠这个）
        page_images = {}
        if vision_configured():
            for p in cand:
                try:
                    page_images[p] = _render_page(pdf, p, tmpdir)
                except Exception:
                    pass

        _bg_set(con, tid, progress=0, total=len(cand), message="AI 解题中…")
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
            _bg_set(con, tid, progress=done, message="AI 解题中… 已找到 %d 题" % len(found))
        if not found:
            raise RuntimeError("AI 没能从中识别出可解答的题目")

        # 每页一张解析页，插到原页后面
        by_page = {}
        for it in found:
            by_page.setdefault(it["page"], []).append(it)
        _bg_set(con, tid, message="正在生成副本…")
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
        _bg_set(con, tid, status="done", result_id=new_mid, progress=len(cand),
                message="识别 %d 道题，已生成副本" % len(found),
                extra=json.dumps({"src_mid": mid, "out_mid": new_mid, "n": len(found)}))
        con.commit()
    except Exception as e:
        try:
            _bg_set(con, tid, status="error", message=str(e)[:200])
            # 解析失败就把刚上传的原件也收走，别在资料库里留一堆没用的文件
            row = con.execute("SELECT stored_name FROM materials WHERE id=?", (mid,)).fetchone()
            if row:
                con.execute("DELETE FROM materials WHERE id=?", (mid,))
                con.commit()
                try:
                    os.remove(os.path.join(UPLOADS, str(user_id), row["stored_name"]))
                except Exception:
                    pass
        except Exception:
            pass
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


def _ocr_image_page(pdf, p, tmpdir):
    """没有文字层的页（扫描件）走 OCR。"""
    try:
        pre = os.path.join(tmpdir, "sc_%d" % p)
        subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", "-f", str(p), "-l", str(p),
                        "-singlefile", pdf, pre], check=True, timeout=180, capture_output=True)
        return _ocr_image(pre + ".png")
    except Exception:
        return ""


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

    tid = _bg_new(db, "docqa", f.filename)
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
    g = {"word": 0, "daily": 0, "wrongq": 0}
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
from figgen import _gen_figure_q, _gen_math_q, _gen_ziliao, _MATH_GEN  # noqa: E402

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
# 这三块和常识不一样：**题型固定、有套路、拼速度**。所以按题型分开刷、每题计时、
# 做完给这一类的秒杀技巧，并统计「哪个题型最弱、平均要多久」——弱的排前面。
# 题都是**程序化生成**的（figgen.py），答案由构造保证；AI 出这类题会算错，不用它。
DRILL_LIMIT = {"资料分析": 60, "判断推理": 45, "数量关系": 70,
               "常识判断": 30, "政治理论": 30, "言语理解与表达": 50}   # 每题限时（秒），按真题节奏

# ---- 难度：三档，**真正改变题目**（程序化的三块由 figgen 按 level 造，AI 的三块写进提示词）----
# 「难度系数」在公考里就是**得分率**（0~1，越高越简单）。这里给每个板块一个真实基准，
# 让人心里有数：数量关系考场真实难度只有 0.40，做对 4 成不是你菜，是这题本来就难。
DRILL_LEVELS = ["easy", "mid", "real"]
DRILL_LV_NAME = {"easy": "入门", "mid": "进阶", "real": "考场真实"}
# 难度的说明要**分板块写** —— 「数字整、要动笔」这话套到常识判断上驴唇不对马嘴
DRILL_LV_DESC = {
    "计算": {"easy": "一步套公式、数字整、干扰项一眼排除",
             "mid": "常规两步、需要动笔算",
             "real": "多步/要用技巧、数字不整得估算、干扰项贴着常见错法"},
    "图形": {"easy": "规律直观（数元素、数边），干扰项差异明显",
             "mid": "五类规律都可能，需要比对两三个属性",
             "real": "偏隐蔽规律（线条数、封闭区域），且有镜像干扰项"},
    "知识": {"easy": "单个知识点正面直问，四选项差异明显",
             "mid": "需要辨析或两步推理，有一个较像的干扰项",
             "real": "真题水平：干扰项贴着常见错法（易混概念、偷换时间/主体/范围），要真懂才选得对"},
}
_LV_KIND = {"资料分析": "计算", "数量关系": "计算", "判断推理": "图形",
            "常识判断": "知识", "政治理论": "知识", "言语理解与表达": "知识"}


def drill_levels(board):
    d = DRILL_LV_DESC[_LV_KIND.get(board, "知识")]
    return [{"k": k, "name": DRILL_LV_NAME[k], "desc": d[k], "coef": drill_coef(board, k)}
            for k in DRILL_LEVELS]
DRILL_BASE = {            # 该板块「考场真实难度」的得分率基准（接近真题平均正确率）
    "资料分析": 0.65, "判断推理": 0.60, "数量关系": 0.40,
    "常识判断": 0.55, "政治理论": 0.60, "言语理解与表达": 0.62,
}
_LV_BONUS = {"easy": 0.25, "mid": 0.10, "real": 0.0}


def drill_coef(board, level):
    """难度系数 = 预期得分率。入门在基准上加 25 个点，进阶加 10 个点，真实就是基准。"""
    return round(min(0.92, DRILL_BASE.get(board, 0.6) + _LV_BONUS.get(level, 0.1)), 2)


# 题型**按讲义目录的顺序**排（循序渐进，别一上来就啃最难的）。
# 每项 = (题型, 一句话说明, 引擎)：prog = 程序化生成（答案由构造保证）；ai = AI 出题 + 题库缓存。
# 判断推理是**混合**的：图形推理能构造，定义/类比/逻辑判断只能让 AI 出。
DRILL_TYPES = {
    # ---- 资料分析（讲义第二章 常考概念）----
    "资料分析": [
        ("基期量", "已知现期和增长率，倒推去年", "prog"),
        ("现期量", "直接读数，别自己加戏", "prog"),
        ("增长率", "(今年−去年)÷**去年**", "prog"),
        ("增长量", "今年−去年，直接减", "prog"),
        ("间隔增长", "隔一年的增长率：r₁+r₂+r₁r₂", "prog"),
        ("年均增长", "÷ 年份差（2021→2024 是 3 不是 4）", "prog"),
        ("混合增长", "整体增速必在两部分之间", "prog"),
        ("倍数与翻番", "「是几倍」用除，「多几倍」再减 1", "prog"),
        ("比重", "部分 ÷ 整体", "prog"),
        ("比重变化", "单位是**百分点**，不是百分比", "prog"),
        ("平均数", "人均 = 总量 ÷ 人口，同一年", "prog"),
        ("比较大小", "比重上升 ⇔ 部分增速快于整体", "prog"),
    ],
    # ---- 言语理解与表达（讲义四篇：选词填空 / 片段阅读 / 语句表达 / 文章阅读）----
    "言语理解与表达": [
        ("语境分析", "选词填空：靠上下文的呼应、提示定词", "ai"),
        ("词语辨析", "选词填空：近义词的词义/搭配/色彩差别", "ai"),
        ("查找细节", "片段阅读：回原文核对，别凭印象", "ai"),
        ("概括主旨", "片段阅读：找中心句，转折词后面十有八九是", "ai"),
        ("判断意图", "片段阅读：作者想让你干什么/信什么", "ai"),
        ("推断隐含信息", "片段阅读：由已知推未知，不能过度引申", "ai"),
        ("理解词句", "片段阅读：指定词句在文中什么意思", "ai"),
        ("句子填空", "语句表达：补上最连贯的一句", "ai"),
        ("句子排序", "语句表达：先排除不能当首句的", "ai"),
        ("文章阅读", "一篇长文配多问", "ai"),
    ],
    # ---- 判断推理（讲义四章：图形推理 / 定义判断 / 类比推理 / 逻辑判断）----
    "判断推理": [
        ("位置变化", "图形：旋转、平移", "prog"),
        ("样式规律", "图形：加减同异（去同存异）", "prog"),
        ("属性规律", "图形：对称性、开闭性", "prog"),
        ("数量规律", "图形：点 / 线 / 面 / 素", "prog"),
        ("定义判断", "对着定义逐字抠要件", "ai"),
        ("类比推理", "逻辑关系 / 言语关系 / 常识关系", "ai"),
        ("翻译推理", "「若A则B」的推理规则", "ai"),
        ("分析推理", "排除法 + 列表法", "ai"),
        ("削弱论证", "找最能削弱结论的那一项", "ai"),
        ("加强论证", "找最能支持结论的那一项", "ai"),
        ("解释说明", "解释看似矛盾的现象", "ai"),
    ],
    # ---- 数量关系（讲义第二章 高频题型 → 第三章 数字推理）----
    "数量关系": [
        ("工程", "设总量为最小公倍数", "prog"),
        ("行程", "相遇看速度和，追及看速度差", "prog"),
        ("利润", "成本设成 100", "prog"),
        ("容斥", "先算「至少参加一项」", "prog"),
        ("最值", "要谁最大就让别人尽量小", "prog"),
        ("几何", "边长×k → 面积×k²", "prog"),
        ("排列组合", "换个顺序算不算新方案？", "prog"),
        ("概率", "放回还是不放回？", "prog"),
        ("浓度", "十字交叉法", "prog"),
        ("等差数列", "(首+末)×项数÷2", "prog"),
        ("周期日期", "只看余数", "prog"),
        ("植树方阵", "两端都种 = 段数+1", "prog"),
        ("年龄", "年龄差永远不变", "prog"),
        ("数字推理", "先看差、再看商、看平方、看递推", "prog"),
    ],
    # ---- 常识判断（七大板块，全靠 AI 出题）----
    "常识判断": [(b, "", "ai") for b in ("人文常识", "科技常识", "法律常识", "地理常识",
                                         "经济常识", "管理常识", "公文常识")],
    # ---- 政治理论 ----
    "政治理论": [(b, "", "ai") for b in ("马克思主义基本原理", "毛泽东思想",
                                         "中国特色社会主义理论体系", "习近平新时代中国特色社会主义思想")],
}
# 某个题型用哪个引擎（题型名 → prog/ai）；同名题型不会跨板块冲突
DRILL_ENGINE = {(b, t[0]): t[2] for b, ts in DRILL_TYPES.items() for t in ts}
# 讲义里的「解题方法」章 —— 是方法不是题型，单独摆出来（做题时的秒杀技巧就来自这里）
DRILL_METHODS = {
    "资料分析": ["尾数法：只算末几位，选项末位不同就直接出答案",
                 "截位直除：分子分母各取前 2~3 位，够用了",
                 "百化分：1/7≈14.3%、1/8=12.5%、1/9≈11.1% —— 背下来省一半时间",
                 "错位加减：a×1.1 = a + a的十分之一"],
    "数量关系": ["代入排除：选项就是答案，从最好算的那个开始代",
                 "倍数特性：结果必须是 3 的倍数 → 不是的直接划掉",
                 "特值法：题里没给具体数 → 自己设一个（总量设 100 或最小公倍数）",
                 "方程法：实在没招才设未知数，能设一个别设两个"],
}
# 有些题型讲义里有、但**没法可靠地程序化构造**，硬做出来答案站不住 —— 老实说明，不假装有
DRILL_MISSING = {
    "判断推理": "立体图形（折纸盒 / 三视图）：二维 SVG 构造不出可靠的立体题，答案站不住脚，所以不出。",
}
AI_BOARDS = ("常识判断", "政治理论", "言语理解与表达")     # 这三块整块都靠 AI 出题

# 每个题型的秒杀技巧（做完立刻给 —— 不是解析，是「下次怎么更快」）。
# 程序化出的题会自带 tip；这里兜底 + 给 AI 题型用。
DRILL_TIP = {
    # 资料分析
    "基期量": "基期 = 现期 ÷ (1+r)。**最经典的错法是「现期 ×(1−r)」** —— 增长率的分母是基期，不是现期。",
    "现期量": "**直接读数**。这类题不用算，别自己给自己加戏。",
    "增长率": "(今年 − 去年) ÷ **去年**。除的是去年，不是今年 —— 最经典的坑。",
    "增长量": "今年 − 去年，直接减。别去套增长率公式绕远路。",
    "间隔增长": "隔一年的增长率 = **r₁ + r₂ + r₁×r₂**。不能把两年的增长率直接相加。",
    "年均增长": "(末年 − 首年) ÷ **年份差**。2021→2024 是 **3** 年，不是 4。",
    "混合增长": "**整体增速必定介于两部分之间**，且更靠近权重大的那一边。绝不等于简单平均数。",
    "倍数与翻番": "「是几倍」用除，「多几倍」再减 1。「翻一番」=×2，「翻两番」=**×4**（不是 ×3）。",
    "比重": "部分 ÷ 整体。**先看清年份和单位** —— 这类题错的多半不是算错，是看错行。",
    "比重变化": "两个比重直接相减，单位是**百分点**，不是百分比。",
    "平均数": "人均 = 总量 ÷ 人口，**分子分母必须同一年**。错位取数是最常见的失分点。",
    "比较大小": "**比重上升 ⇔ 部分的增速快于整体**。看出这一条，很多题不用算。",
    # 判断推理 · 图形（四大类）
    "位置变化": "先看**旋转还是平移**；旋转题必看是不是**镜像** —— 镜像靠旋转永远得不到。",
    "样式规律": "**去同存异 / 求同存异**：把两个图叠起来，相同的抵消还是保留？先定这个。",
    "属性规律": "对称性（轴对称/中心对称）、开闭性、曲直性 —— 三个属性挨个过一遍。",
    "数量规律": "数**点、线、面、素**：交点数、线条数、封闭区域数、元素种类。数之前先想清楚数的是什么。",
    # 判断推理 · 文字
    "定义判断": "**对着定义逐字抠要件**：主体、行为、对象、目的，缺一个就不符合。别凭常识判断。",
    "类比推理": "先想**这两个词是什么关系**（种属/组成/功能/对应），再去选项里找**同一种**关系。",
    "翻译推理": "「A→B」的两条铁律：**肯前必肯后、否后必否前**。肯后否前都是耍流氓。",
    "分析推理": "有确定信息就**从确定的入手**；没有就**代入排除**（选项就是答案）。列表法最稳。",
    "削弱论证": "先找出**论点和论据**，再看哪一项**切断了两者的联系**（拆桥）—— 那才是最强削弱。",
    "加强论证": "补上论点和论据之间缺的那一环（搭桥），比举例子有力得多。",
    "解释说明": "找一个**能让矛盾双方同时成立**的原因。只解释一半的都不选。",
    # 言语理解
    "语境分析": "先找**呼应/提示**：转折、并列、递进、解释 —— 空缺处的意思由上下文钉死。",
    "词语辨析": "近义词看三样：**词义轻重、搭配对象、感情色彩**。别只凭语感。",
    "查找细节": "**回原文核对**，一个字一个字对。「绝对化」「偷换概念」「无中生有」是三大错项。",
    "概括主旨": "找**转折词后面**那句（但是/然而/其实）—— 主旨十有八九在那儿。",
    "判断意图": "主旨是「说了什么」，意图是「**想让你怎么样**」。问意图就要往「呼吁/建议」上靠。",
    "推断隐含信息": "只能**由已知推未知**，不能过度引申。选项里带「必然」「一定」的先警惕。",
    "理解词句": "**回到原文那一句**，看它前后是怎么解释的。别拿词典义硬套。",
    "句子填空": "看空缺**在段首、段中还是段尾**：段首领起、段中承接、段尾总结。",
    "句子排序": "先找**不能当首句的**（含指代词、关联词后半句）—— 排除法比正着排快得多。",
    "文章阅读": "**先看题目再读文**，带着问题找答案，别通读。",
    # 数量关系（程序化的题自带 tip，这里兜底）
    "工程": "**设总量为最小公倍数**，效率立刻变整数。",
    "行程": "相遇看**速度和**，追及看**速度差**。",
    "利润": "**成本设成 100**，全是百分比乘除。",
    "容斥": "先算**至少参加一项**（总数 − 都不参加），再套 A+B−A∪B。",
    "最值": "**要谁最大，就让别人尽量小**。",
    "几何": "**边长 ×k → 面积 ×k²，体积 ×k³**。",
    "排列组合": "先问：**换个顺序算不算新方案？** 算→排列 A，不算→组合 C。",
    "概率": "先问：**放回还是不放回？**",
    "浓度": "**十字交叉法**：两溶液质量比 = 浓度差的反比。",
    "等差数列": "求和 = **(首 + 末) × 项数 ÷ 2**。项数 = (末−首)÷公差 **+1**。",
    "周期日期": "**只看余数**，商是多少不用管。",
    "植树方阵": "两端都种 = **段数 + 1**；空心方阵最外层 = **每边 ×4 − 4**。",
    "年龄": "抓住**年龄差不变**这个不变量。",
    "数字推理": "四步：**先看差 → 再看商 → 看是不是平方/立方 → 看是不是前两项组合**。四步不出就跳过。",
}

_LV_PROMPT = {
    "easy": "**入门难度**：只考单个知识点，正面直问，四个选项差异明显，一眼能排除两个。",
    "mid": "**进阶难度**：需要辨析或两步推理，有一个较像的干扰项。",
    "real": "**考场真实难度**：按真题水平出——设置**贴着常见错法**的干扰项（易混概念、"
            "偷换时间/主体/范围），正确项不能一眼看出，要真懂才选得对。",
}


# ---- 双模型核验：AI 出的题，必须由**另一家模型**独立做一遍，答案一致才发给人做 ----
# 为什么非做不可：135 道抽检下来，单模型出题的答案一致率只有 **89%** —— 每 9 道就有 1 道存疑。
# 而且真抓到过硬伤（「生态文明八个坚持」里说「山水林田湖草沙」多了个「沙」，那是错的）。
# 出题：DeepSeek；核验：智谱 glm-4-plus。**绝不把原答案给核验模型看**，否则它会被锚定。
AUDIT_MODEL = "glm-4-plus"      # 智谱旗舰非推理版（glm-4.6 是推理模型，一道要 15~30 秒，太慢）


def _audit_q(q, options, board, qtype):
    """让核验模型独立作答 + 独立判断题目有没有毛病。返回 (答案, flaw, 说明) 或 None。"""
    c = _vision_conf()
    if not c.get("key") or not c.get("base"):
        return None
    prompt = (
        "【板块】%s · %s\n【题目】%s\n【选项】\n%s\n\n"
        "这道题**不告诉你答案**，请你自己独立做一遍，并判断题目本身有没有毛病。\n"
        "1. answer：A/B/C/D\n"
        "2. flaw：ok（没问题）/ fact（有事实错误）/ multi（不止一个选项说得通）/ "
        "none（一个正确答案都没有）/ vague（有歧义）\n"
        "3. note：一句话说明理由（或问题在哪）\n\n"
        '只输出 JSON：{"answer":"A","flaw":"ok","note":""}'
        % (board, qtype, q, "\n".join(options)))
    payload = {"model": AUDIT_MODEL, "temperature": 0.1, "max_tokens": 600,
               "messages": [{"role": "user", "content": prompt}],
               "response_format": {"type": "json_object"}}
    url = c["base"] + ("" if c["base"].endswith("/chat/completions") else "/chat/completions")
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + c["key"]})
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.loads(r.read().decode("utf-8"))
        txt = (d["choices"][0]["message"].get("content") or "").strip()
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return None
        j = json.loads(m.group())
        a = (j.get("answer") or "").strip().upper()[:1]
        return (a if a in "ABCD" else "", (j.get("flaw") or "ok").strip(),
                (j.get("note") or "").strip()[:160])
    except Exception:
        return None


def _bank_material(db, board, qtype, n=14):
    """从已有素材里取出题的原料 —— 题必须**考我们库里有的东西**，不然练了也对不上。
       片段阅读/逻辑判断这类不依赖词库，AI 自己命制。"""
    if board == "常识判断":
        rows = db.execute("SELECT title, content FROM changshi_items WHERE board=? "
                          "ORDER BY RANDOM() LIMIT ?", (qtype, n)).fetchall()
        return ["%s：%s" % (r["title"], (r["content"] or "")[:110]) for r in rows]
    if board == "政治理论":
        rows = db.execute("SELECT title, content FROM theory_items WHERE board=? "
                          "ORDER BY RANDOM() LIMIT ?", (qtype, n)).fetchall()
        return ["%s：%s" % (r["title"], (r["content"] or "")[:110]) for r in rows]
    if qtype in ("语境分析", "词语辨析"):     # 选词填空：正确答案要从我们积累的词里出
        rows = db.execute("SELECT title, content FROM changkao_items WHERE board IN ('成语','实词') "
                          "ORDER BY RANDOM() LIMIT ?", (n * 2,)).fetchall()
        return ["%s：%s" % (r["title"], (r["content"] or "")[:60]) for r in rows]
    return []


# 各 AI 题型的出题要点 —— 不写清楚，AI 出的题型会跑偏（比如把「判断意图」出成「概括主旨」）
_AI_SPEC = {
    "语境分析": "选词填空，一个空。**空缺处的意思必须由上下文钉死**（转折/并列/递进/解释的呼应关系），"
                "四个选项都是近义词，只有一个符合语境。",
    "词语辨析": "选词填空，一个空。四个选项是**近义词**，靠**词义轻重 / 搭配对象 / 感情色彩**区分。",
    "查找细节": "片段阅读（150~250 字），问「符合/不符合原文的是」。错项要用**绝对化、偷换概念、"
                "无中生有**这三种典型手法造。",
    "概括主旨": "片段阅读（150~250 字），问「这段文字主要说明了什么」。文段里要有明确的中心句"
                "（常在转折词之后）。",
    "判断意图": "片段阅读（150~250 字），问「作者意在强调/说明什么」。注意**意图不是主旨** —— "
                "答案要往「呼吁 / 建议 / 提醒」上落，只复述内容的是干扰项。",
    "推断隐含信息": "片段阅读（150~250 字），问「可以推出的是」。正确项必须**由文段严格推出**，"
                    "干扰项要有「过度引申」「绝对化」的。",
    "理解词句": "片段阅读（150~250 字），问文中某个加引号的词/句是什么意思。答案要回到原文语境。",
    "句子填空": "给一段话，中间或结尾挖掉一句，选最连贯的。要考**承上启下**。",
    "句子排序": "给 5~6 个打乱的句子（用①②③…标号），选正确顺序。要有**明显的首句线索**"
                "（指代词、关联词后半句不能当首句）。",
    "文章阅读": "一篇 400~600 字的文章，配一个问题（主旨或细节）。",
    "定义判断": "先给一个**完整的定义**（含主体、行为、对象、目的），再给四个例子，"
                "问哪个**符合/不符合**该定义。要靠**逐字抠要件**才能判，不能靠常识。",
    "类比推理": "给一组词（如「医生：手术刀」），四个选项里选**关系最相似**的一组。"
                "关系要明确（种属 / 组成 / 功能 / 对应 / 因果）。",
    "翻译推理": "给若干「若…则…」的条件，问能推出什么。考**肯前必肯后、否后必否前**，"
                "干扰项要用**肯后、否前**这两种典型错误。",
    "分析推理": "给若干条件（如四个人的座位/职业），问确定的结论。要能靠**排除法/列表法**做出来。",
    "削弱论证": "先给论点和论据，问哪一项**最能削弱**。最强削弱应该是**切断论点与论据的联系**（拆桥），"
                "干扰项用「削弱力度弱」「无关项」。",
    "加强论证": "先给论点和论据，问哪一项**最能支持**。最强加强应该是**补上论点与论据之间缺的一环**（搭桥）。",
    "解释说明": "给一个看似矛盾的现象，问哪一项**最能解释**。正确项要能让矛盾双方**同时成立**。",
}


def _bank_fill(db, board, qtype, level, want=8):
    """题库不够了就补一批。返回新增数量。
       **每个题型的出题要点不一样**（见 _AI_SPEC）——不写清楚，AI 会把「判断意图」出成「概括主旨」。"""
    mat = _bank_material(db, board, qtype)
    tip = DRILL_TIP.get(qtype, "")
    spec = _AI_SPEC.get(qtype, "")
    extra = ""
    if board in ("常识判断", "政治理论"):
        if not mat:
            return 0
        extra = ("\n【只能考下面这些考点】（一道题考一个，别超纲）\n"
                 + "\n".join("· " + x for x in mat))
    elif qtype in ("语境分析", "词语辨析"):
        # ⚠️ 从词库随机抽的词彼此**不相关**，直接丢给 AI 当四个选项，它就拿来凑数了
        #    （实测出过「施行 / 掩饰 / 减轻 / 接二连三」—— 一眼就能选，这题白出）。
        #    正确答案从我们库里挑（保证考的是积累过的词），**另外三个近义混淆项让 AI 自己造**。
        extra = ("\n【正确答案必须从下面这些词里挑一个】（这是他积累过的词，要考这些）\n"
                 + "\n".join("· " + x for x in mat[:12])
                 + "\n\n⚠️ 另外三个选项**必须是正确答案的近义词/易混词**（你自己造），"
                   "四个词要**放在一起才需要辨析**（如「施行/实行/执行/推行」）。"
                   "**绝不能**拿不相干的词凑数（「施行/掩饰/减轻/接二连三」这种一眼就能排除，这题就白出了）。"
                   "解析要讲清**这四个词的区别**在哪。")

    prompt = (
        "给四川省考考生出 %d 道**%s · %s**的单选题。\n\n"
        "【这个题型怎么出】%s\n\n"
        "【难度】%s\n\n"
        "【每道题】\n"
        "· q：题干（题型要求见上；片段阅读/文章阅读要把**文段原文写进题干**）\n"
        "· options：四个选项，形如 \"A. …\"\n"
        "· answer：正确选项字母\n"
        "· explain：解析，讲清**为什么对、为什么其他三个错**（不是只说答案）\n"
        "· source：这题考的具体考点（如「人文常识-唐宋八大家」「词语辨析-一蹴而就」）\n\n"
        "【硬要求】\n"
        "1. 答案**唯一且经得起推敲**，不能出现两个都对或都说得通的选项。\n"
        "2. 四个选项**互不相同**、长度相当（别让正确项特别长，那等于送分）。\n"
        "3. 一道题**围绕一个考点**。四个选项可以是关于同一事物的四种说法（这很常见），"
        "但**不能横跨四个不相干的知识点**——那是在考运气，不是考掌握。\n"
        "4. **必须真的是「%s」这个题型**，不要出成别的题型。\n\n"
        '只输出 JSON：{"items":[{"q":"","options":["A. …","B. …","C. …","D. …"],'
        '"answer":"A","explain":"","source":""}]}'
        % (want, board, qtype, spec or "按这个题型的常规考法出",
           _LV_PROMPT.get(level, ""), qtype)) + extra

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是四川省考命题老师。答案唯一、干扰项讲究，"
                                       "解析要说清其他三个为什么错。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.6, max_tokens=3500, timeout=300, json_mode=True)
    if err:
        return 0
    try:
        got = json.loads(rep).get("items") or []
    except Exception:
        return 0
    n = 0
    for it in got:
        q = (it.get("q") or "").strip()
        opts = it.get("options") or []
        ans = (it.get("answer") or "").strip().upper()[:1]
        # 逐条把关：四选项、答案字母合法、选项不重复 —— AI 这三样都会翻车
        if not q or len(opts) != 4 or ans not in "ABCD":
            continue
        body = [re.sub(r"^[A-D][.、．)]\s*", "", str(o)).strip() for o in opts]
        if len(set(body)) != 4 or not all(body):
            continue
        opts_std = ["%s. %s" % ("ABCD"[i], body[i]) for i in range(4)]
        # ★ 双模型核验：另一家模型独立做一遍。答案不一致 → **入库但标为存疑，不发给人做**。
        #   （不直接丢弃：存疑的题本身是有价值的数据，可以回查；但绝不能让人拿去背。）
        au = _audit_q(q, opts_std, board, qtype)
        if au is None:
            agree, aans, flaw, note = 0, "", "unchecked", "核验模型没响应"
            checked = 0
        else:
            aans, flaw, note = au
            checked = 1
            agree = 1 if (aans == ans and flaw == "ok") else 0
        sig = hashlib.md5((board + qtype + re.sub(r"\s", "", q)).encode()).hexdigest()
        try:
            db.execute(
                "INSERT INTO drill_bank(board,qtype,level,q,options,answer,explain,tip,source,sig,"
                "checked,agree,audit_ans,audit_note,flaw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (board, qtype, level, q, json.dumps(opts_std, ensure_ascii=False),
                 ans, (it.get("explain") or "").strip(), tip,
                 (it.get("source") or ("%s-%s" % (board, qtype))).strip(), sig,
                 str(checked), str(agree), aans, note, flaw))
            if agree:
                n += 1          # 只把「过了核验的」算作有效产出
        except sqlite3.IntegrityError:
            pass               # 撞指纹 = 出过一样的题，跳过
    db.commit()
    return n


def _bank_take(db, board, qtype, level, n):
    """从题库取 n 道 —— **只取过了双模型核验的**（agree=1）。不够就现补。
       存疑的题留在库里可以回查，但绝不发给人做（拿去背错的答案，比不做还糟）。"""
    def grab():
        return [dict(r) for r in db.execute(
            "SELECT * FROM drill_bank WHERE board=? AND qtype=? AND level=? AND agree='1' "
            "ORDER BY RANDOM() LIMIT ?", (board, qtype, level, n))]
    got = grab()
    tries = 0
    while len(got) < n and tries < 2:      # 核验会刷掉一部分，所以多出一些
        tries += 1
        _bank_fill(db, board, qtype, level, want=max(10, (n - len(got)) * 2))
        got = grab()
    out = []
    for r in got:
        out.append({"q": r["q"], "options": json.loads(r["options"]), "answer": r["answer"],
                    "explain": r["explain"], "tip": r["tip"], "module": board,
                    "source": r["source"], "qtype": qtype, "level": level})
    return out


def _drill_gen(db, board, qtype, n, level="mid"):
    """出 n 道题。**按题型决定用哪个引擎** —— 判断推理是混合的：
       图形推理能构造（prog），定义/类比/逻辑判断只能让 AI 出（ai）。"""
    types = [t[0] for t in DRILL_TYPES[board]]
    if not qtype:                                  # 混合练：题型按目录顺序轮着来
        out = []
        for i in range(n):
            out += _drill_gen(db, board, types[i % len(types)], 1, level)
        return out[:n]
    if qtype not in types:
        return []
    eng = DRILL_ENGINE.get((board, qtype), "ai")
    if eng == "ai":
        return _bank_take(db, board, qtype, level, n)

    out = []
    for _ in range(n):
        if board == "数量关系":
            q = _gen_math_q(qtype, level)
        elif board == "判断推理":
            q = _gen_figure_q(qtype, level)        # kind = 目录里的大类（位置变化/样式规律/…）
        else:
            q = _gen_ziliao(1, level)[0]
            for _ in range(15):                    # 摇到指定考点为止
                if q["source"].split("-")[-1] == qtype:
                    break
                q = _gen_ziliao(1, level)[0]
        q["qtype"] = qtype                         # 统计要按「目录里的题型名」记，不是生成器的细目
        q.setdefault("tip", DRILL_TIP.get(qtype, ""))
        q["level"] = level
        out.append(q)
    return out


@app.get("/api/drill/types")
def drill_types():
    """题型清单 + 我在每个题型上的正确率和平均用时。弱的排前面 —— 该练哪个不用自己想。"""
    board = (request.args.get("board") or "").strip()
    level = (request.args.get("level") or "mid").strip()
    if board not in DRILL_TYPES:
        return jsonify({"error": "这个板块没有专项练"}), 400
    db = get_db()
    stat = {r["qtype"]: dict(r) for r in db.execute(
        "SELECT qtype, COUNT(*) n, SUM(correct) ok, AVG(seconds) sec FROM drill_log "
        "WHERE user_id=? AND board=? AND level=? GROUP BY qtype", (uid(), board, level))}
    # 题库里每个题型有多少道过了双模型核验（AI 题型才有）
    bank = {r["qtype"]: dict(r) for r in db.execute(
        "SELECT qtype, SUM(agree='1') ok, COUNT(*) c FROM drill_bank "
        "WHERE board=? AND level=? GROUP BY qtype", (board, level))}
    items = []
    for i, (k, desc, eng) in enumerate(DRILL_TYPES[board]):
        st = stat.get(k) or {}
        bk = bank.get(k) or {}
        n = st.get("n") or 0
        acc = round(100.0 * (st.get("ok") or 0) / n) if n else None
        items.append({"type": k, "desc": desc, "eng": eng, "ord": i, "n": n, "acc": acc,
                      "sec": round(st.get("sec") or 0) if n else None,
                      "tip": DRILL_TIP.get(k, ""),
                      "bank_ok": bk.get("ok") or 0,          # 过了双模型核验的
                      "bank_all": bk.get("c") or 0})
    # 默认按**讲义目录顺序**（循序渐进）；练过之后，薄弱的（低于该难度预期得分率）才提到前面
    exp = round(drill_coef(board, level) * 100)
    items.sort(key=lambda x: (0 if (x["acc"] is not None and x["acc"] < exp) else 1,
                              x["acc"] if x["acc"] is not None else 999, x["ord"]))
    coef = drill_coef(board, level)
    return jsonify({"board": board, "limit": DRILL_LIMIT.get(board, 60), "types": items,
                    "levels": drill_levels(board),
                    "level": level, "coef": coef, "base": DRILL_BASE.get(board, 0.6),
                    "ai": board in AI_BOARDS,
                    "methods": DRILL_METHODS.get(board, []),
                    "missing": DRILL_MISSING.get(board, "")})


@app.get("/api/drill/boards")
def drill_boards():
    """哪些板块有专项练（首页/板块页要用）。"""
    return jsonify({"boards": [{"board": b, "n_types": len(DRILL_TYPES[b]),
                                "ai": b in AI_BOARDS, "base": DRILL_BASE.get(b, 0.6)}
                               for b in DRILL_TYPES]})


@app.post("/api/drill/quiz")
def drill_quiz():
    d = request.get_json(silent=True) or {}
    board = (d.get("board") or "").strip()
    if board not in DRILL_TYPES:
        return jsonify({"error": "这个板块没有专项练"}), 400
    qtype = (d.get("type") or "").strip()
    level = d.get("level") if d.get("level") in ("easy", "mid", "real") else "mid"
    n = max(1, min(30, int(d.get("n") or 5)))
    exam = bool(d.get("exam"))                    # 测试模式：答案不下发
    items = _drill_gen(get_db(), board, qtype, n, level)
    if not items:
        return jsonify({"error": "这个题型暂时出不了题，换一个或稍后再试"}), 502
    pub = []
    for it in items:
        x = dict(it)
        if exam:
            x.pop("answer", None)
            x.pop("explain", None)
            x.pop("tip", None)
        pub.append(x)
    return jsonify({"board": board, "type": qtype, "level": level, "exam": exam,
                    "coef": drill_coef(board, level),
                    "limit": DRILL_LIMIT.get(board, 60), "items": pub,
                    "full": items if not exam else None,
                    "token": _drill_stash(items) if exam else ""})


# 测试模式下答案不下发，题目暂存在服务端（进程内，够用；重启就没了，反正是当次做的）
_DRILL_STASH = {}


def _drill_stash(items):
    tok = secrets.token_hex(8)
    _DRILL_STASH[tok] = items
    if len(_DRILL_STASH) > 400:                   # 别无限涨
        for k in list(_DRILL_STASH)[:100]:
            _DRILL_STASH.pop(k, None)
    return tok


@app.post("/api/drill/done")
def drill_done():
    """交卷：判分、记成绩（用来算薄弱题型）、错题自动进错题本、**留一条完整记录**。"""
    d = request.get_json(silent=True) or {}
    board = (d.get("board") or "").strip()
    level = d.get("level") if d.get("level") in ("easy", "mid", "real") else "mid"
    mode = "exam" if d.get("exam") else "study"
    items = _DRILL_STASH.pop(d.get("token"), None) if d.get("token") else None
    if items is None:
        items = d.get("items") or []              # 背题模式：题目本来就在前端手里
    answers = d.get("answers") or {}
    if board not in DRILL_TYPES or not items:
        return jsonify({"error": "参数不对"}), 400

    db = get_db()
    results, secs = [], []
    for i, it in enumerate(items):
        your = (answers.get(str(i)) or answers.get(i) or it.get("your") or "").strip().upper()[:1]
        sec = float((d.get("seconds") or {}).get(str(i)) or it.get("seconds") or 0)
        ok = bool(your) and your == (it.get("answer") or "")
        secs.append(sec)
        db.execute("INSERT INTO drill_log(user_id,board,qtype,level,correct,seconds) VALUES(?,?,?,?,?,?)",
                   (uid(), board, it.get("qtype") or "", level, 1 if ok else 0, sec))
        results.append({"correct": ok, "your": your, "answer": it.get("answer") or "",
                        "explain": it.get("explain") or "", "tip": it.get("tip") or ""})
    for it, r in zip(items, results):
        it["your"], it["seconds"] = r["your"], 0
    added = _dtest_to_wrongq(db, items, results)
    ok_n = sum(1 for r in results if r["correct"])
    cur = db.execute(
        "INSERT INTO drill_records(user_id,board,qtype,level,mode,total,correct,seconds,items,answers) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (uid(), board, (d.get("type") or "").strip(), level, mode, len(items), ok_n,
         sum(secs), json.dumps(items, ensure_ascii=False), json.dumps(results, ensure_ascii=False)))
    db.commit()
    acc = ok_n / len(items) if items else 0
    coef = drill_coef(board, level)
    return jsonify({"ok": ok_n, "total": len(items), "wrong_added": added, "results": results,
                    "rid": cur.lastrowid, "coef": coef, "acc": round(acc, 2),
                    "vs": round(acc - coef, 2)})     # 和难度系数（预期得分率）比，高出多少


@app.get("/api/drill/records")
def drill_records():
    rows = get_db().execute(
        "SELECT id,board,qtype,level,mode,total,correct,seconds,created_at FROM drill_records "
        "WHERE user_id=? ORDER BY id DESC LIMIT 60", (uid(),)).fetchall()
    lv = DRILL_LV_NAME
    return jsonify({"items": [dict(r, level_name=lv.get(r["level"], r["level"]),
                                   coef=drill_coef(r["board"], r["level"])) for r in rows]})


@app.get("/api/drill/record/<int:rid>")
def drill_record(rid):
    r = get_db().execute("SELECT * FROM drill_records WHERE id=? AND user_id=?",
                         (rid, uid())).fetchone()
    if not r:
        return jsonify({"error": "记录不存在"}), 404
    d = dict(r)
    d["items"] = json.loads(d["items"] or "[]")
    d["answers"] = json.loads(d["answers"] or "[]")
    d["coef"] = drill_coef(r["board"], r["level"])
    return jsonify(d)


def _dtest_to_wrongq(db, items, results):
    """巩固测试做错的题自动进错题本：带题干、选项、正确答案、解析和板块。
       图形推理的题干是图，没法存成文字，改存一句说明 + 考点（错题本只认文字/图片）。"""
    n = 0
    for it, r in zip(items, results):
        if r.get("correct") or not r.get("your"):     # 答对的、没作答的都不收
            continue
        opts = "\n".join(it.get("options") or [])
        q = (it.get("q") or "").strip()
        if it.get("figs"):
            q = "【图形推理】" + q + "\n（图形题：%s。到「巩固测试记录」里可回看原图）" % (it.get("source") or "")
        elif it.get("material"):
            m = it["material"]
            q = "【资料分析】材料：%s\n%s" % (m.get("title") or "", q)
        text = (q + ("\n" + opts if opts else ""))[:2000]
        board = it.get("module") or "行测"
        # 同一道题别重复收
        dup = db.execute("SELECT 1 FROM wrong_questions WHERE user_id=? AND question=?", (uid(), text)).fetchone()
        if dup:
            continue
        db.execute("INSERT INTO wrong_questions(user_id,board,question,answer,qtype,points,note) "
                   "VALUES(?,?,?,?,?,?,?)",
                   (uid(), board, text,
                    "正确答案 %s。%s" % (r.get("answer") or "", it.get("explain") or ""),
                    it.get("source") or board, (it.get("source") or "").split("-")[-1],
                    "来自巩固测试（我选了 %s）" % (r.get("your") or "")))
        n += 1
    return n


@app.get("/api/dtest/records")
def dtest_records():
    db = get_db()
    rows = db.execute("SELECT id,date,score,total,created_at FROM dtest_records "
                      "WHERE user_id=? ORDER BY id DESC LIMIT 60", (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.get("/api/dtest/record/<int:rid>")
def dtest_record_detail(rid):
    db = get_db()
    r = db.execute("SELECT * FROM dtest_records WHERE id=? AND user_id=?", (rid, uid())).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    d = dict(r)
    try:
        d["detail"] = json.loads(d.pop("detail_json") or "[]")
    except Exception:
        d["detail"] = []
    return jsonify(d)


@app.get("/api/plan/history")
def plan_history():
    """每天的计划 + 完成情况；今天被重排覆盖掉的旧版本也一并带出来。"""
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    days = {}
    for r in db.execute("SELECT date,seq,title,module,minutes,reason,link,source,done,done_at "
                        "FROM plan_items WHERE user_id=? ORDER BY date DESC, seq, id", (uid(),)):
        d = days.setdefault(r["date"], {"date": r["date"], "live": [], "archived": []})
        d["live"].append({k: r[k] for k in
                          ("seq", "title", "module", "minutes", "reason", "link", "source", "done", "done_at")})
    for r in db.execute("SELECT id,date,created_at,summary,minutes_total,done_n,total,items_json "
                        "FROM plan_log WHERE user_id=? ORDER BY date DESC, id DESC", (uid(),)):
        d = days.setdefault(r["date"], {"date": r["date"], "live": [], "archived": []})
        try:
            items = json.loads(r["items_json"] or "[]")
        except Exception:
            items = []
        d["archived"].append({"id": r["id"], "created_at": r["created_at"], "summary": r["summary"],
                              "minutes_total": r["minutes_total"], "done_n": r["done_n"],
                              "total": r["total"], "items": items})
    out = []
    for date in sorted(days, reverse=True):
        d = days[date]
        live = d["live"]
        out.append({"date": date, "is_today": date == today, "items": live,
                    "done_n": sum(1 for x in live if x["done"]), "total": len(live),
                    "minutes_total": sum(x["minutes"] or 0 for x in live),
                    "minutes_done": sum((x["minutes"] or 0) for x in live if x["done"]),
                    "archived": d["archived"]})
    return jsonify({"days": out, "today": today})


# 计划能覆盖的模块 → 用关键词从任务标题/模块名里认出来，算「最近有没有安排到」
PLAN_MODULES = [
    ("每日复习", ["复习", "遗忘曲线", "背诵", "回忆"]),
    ("错题订正", ["错题", "订正"]),
    ("成语词语", ["成语", "词语", "实词", "选词填空"]),
    ("上位词", ["上位词", "概括词"]),
    ("古诗文", ["古诗", "诗词", "名句", "文学常识"]),
    ("数量关系", ["数量关系", "数学运算", "行程", "工程问题", "浓度", "排列组合", "概率"]),
    ("资料分析", ["资料分析", "速算", "增长率", "比重"]),
    ("判断推理", ["图形推理", "类比推理", "定义判断", "逻辑判断", "判断推理"]),
    ("言语理解", ["言语理解", "逻辑填空", "片段阅读", "语句表达"]),
    ("常识判断", ["常识"]),
    ("政治理论/时政", ["时政", "政治理论", "理论基础", "马原", "毛概", "习思想", "党的创新"]),
    ("申论", ["申论", "归纳概括", "综合分析", "提出对策", "贯彻执行", "大作文", "应用文", "作文", "批改"]),
    ("素材/积累", ["素材", "积累", "概括句", "金句", "习语"]),
]


@app.post("/api/plan/analyze")
def plan_analyze():
    db = get_db()
    today_d = datetime.now().date()
    since = (today_d - timedelta(days=13)).strftime("%Y-%m-%d")
    rows = db.execute("SELECT date,title,module,minutes,done FROM plan_items "
                      "WHERE user_id=? AND date>=? ORDER BY date", (uid(), since)).fetchall()
    # 把被覆盖的历史版本也纳入「安排过什么」的判断（避免漏掉今天早些版本里的成语等）
    for r in db.execute("SELECT date,items_json FROM plan_log WHERE user_id=? AND date>=?", (uid(), since)):
        try:
            for it in json.loads(r["items_json"] or "[]"):
                rows.append({"date": r["date"], "title": it.get("title", ""),
                             "module": it.get("module", ""), "minutes": it.get("minutes", 0),
                             "done": it.get("done", 0)})
        except Exception:
            pass
    if not rows:
        return jsonify({"error": "还没有计划记录，先让规划助手排几天计划再来分析"}), 400

    dates = sorted({r["date"] for r in rows})
    ndays = len(dates)
    cover = {}
    for name, kws in PLAN_MODULES:
        hit = sorted({r["date"] for r in rows
                      if any(k in ((r["title"] or "") + "|" + (r["module"] or "")) for k in kws)})
        cover[name] = {"days": len(hit), "last": hit[-1] if hit else None}
    total_items = len(rows)
    done_items = sum(1 for r in rows if r["done"])

    prof = db.execute("SELECT exam,exam_date,weak,note FROM plan_profile WHERE user_id=?", (uid(),)).fetchone()
    cov_txt = "\n".join(
        "· %s：%d 天里安排了 %d 天%s" %
        (n, ndays, c["days"], ("，最近一次 %s" % c["last"]) if c["last"] else "，从没安排过")
        for n, c in cover.items())
    per_day = {}
    for r in rows:
        per_day.setdefault(r["date"], [0, 0])
        per_day[r["date"]][0] += 1
        per_day[r["date"]][1] += 1 if r["done"] else 0
    day_txt = "\n".join("· %s：%d 条，完成 %d 条" % (d, per_day[d][0], per_day[d][1])
                        for d in sorted(per_day))

    prompt = (
        "这是一名公考考生最近 %d 天（%s ~ %s）的每日备考计划完成情况，请你做一次进度分析。\n\n"
        "【备考信息】考试：%s；薄弱环节：%s；备注：%s\n"
        "【每天完成】\n%s\n\n"
        "【各模块被安排的频率】（days 越少说明越少练到）\n%s\n\n"
        "共 %d 条任务、完成 %d 条。请分析：\n"
        "1. overview：两三句总体评价（完成率、坚持度）。\n"
        "2. keep：坚持得好、完成率高的方面（数组，各一句）。\n"
        "3. neglected：被冷落或长期没安排的模块，尤其点名那些「从没安排过」或很久没练的（如成语、古诗文等日积累项），"
        "说明长期不练的风险（数组，各一句，带模块名）。\n"
        "4. suggestions：给明天/近几天的具体建议，包含该补上的日积累项和薄弱环节（数组，3~5 条，可执行）。\n"
        '只输出 JSON：{"overview":"","keep":[],"neglected":[],"suggestions":[]}'
        % (ndays, dates[0], dates[-1],
           prof["exam"] if prof else "未填", (prof["weak"] if prof else "") or "未填",
           (prof["note"] if prof else "") or "无", day_txt, cov_txt, total_items, done_items))

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考备考教练，善于从学习记录里发现坚持得好的地方和被忽视的短板，"
          "建议具体可执行。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.5, max_tokens=1400, timeout=120, json_mode=True)
    if err:
        return err
    try:
        d = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502
    return jsonify({
        "overview": (d.get("overview") or "").strip(),
        "keep": [str(x).strip() for x in (d.get("keep") or []) if str(x).strip()],
        "neglected": [str(x).strip() for x in (d.get("neglected") or []) if str(x).strip()],
        "suggestions": [str(x).strip() for x in (d.get("suggestions") or []) if str(x).strip()],
        "days": ndays, "total": total_items, "done": done_items,
        "coverage": [{"name": n, "days": c["days"], "last": c["last"]} for n, c in cover.items()],
    })


# ---------------------------------------------------------------- 消息中心（有新内容就提醒，点开直达）
def _n(db, kind, dkey, title, body, link):
    """写一条通知；同一个用户、同一类、同一天只会有一条。"""
    db.execute("INSERT OR IGNORE INTO notifications(user_id,kind,dkey,title,body,link) "
               "VALUES(?,?,?,?,?,?)", (uid(), kind, dkey, title, body, link))


def _topic_brief(rows, n=3):
    """把「板块·专题」列成一句人话：人文常识·文学常识、科技常识·物理常识 等"""
    parts = ["%s·%s" % (r["board"], r["topic"]) for r in rows[:n]]
    return "、".join(parts) + ("　等" if len(rows) > n else "")


def _gen_notifications(db):
    """按各内容库的当日数据现算通知——不用改那一堆定时脚本，也不会漏。"""
    today = datetime.now().strftime("%Y-%m-%d")

    # 常识积累（人文/科技/法律 每天新增）
    rows = db.execute("SELECT board, topic, COUNT(*) c FROM changshi_items WHERE date=? "
                      "GROUP BY board, topic ORDER BY c DESC", (today,)).fetchall()
    if rows:
        total = sum(r["c"] for r in rows)
        _n(db, "changshi", today, "常识积累更新了 %d 条" % total,
           _topic_brief(rows), "changshi")

    # 新出法律单独提醒（考前一年新法是必考点）
    nl = db.execute("SELECT title FROM changshi_items WHERE date=? AND board='法律常识' "
                    "AND topic='其他新出法律'", (today,)).fetchall()
    if nl:
        _n(db, "newlaw", today, "新增 %d 部新法要点" % len(nl),
           "、".join(r["title"] for r in nl[:3]), "changshi:法律常识")

    # 每日时政
    c = db.execute("SELECT COUNT(*) FROM news_items WHERE date(created_at)=?", (today,)).fetchone()[0]
    if c:
        _n(db, "news", today, "每日时政更新了 %d 条" % c, "党内 / 国内 / 四川 / 国际", "news")

    # 习语金句
    c = db.execute("SELECT COUNT(*) FROM xiyu_items WHERE date=?", (today,)).fetchone()[0]
    if c:
        _n(db, "xiyu", today, "习语金句更新了 %d 条" % c, "总书记重要讲话金句 + 申论运用", "xiyu")

    # 议论文素材 / 概括句
    c = db.execute("SELECT COUNT(*) FROM sucai_items WHERE date=?", (today,)).fetchone()[0]
    if c:
        _n(db, "sucai", today, "议论文素材更新了 %d 条" % c, "人物事例 / 具体事例 / 理论论据 / 衔接表达", "sucai")
    c = db.execute("SELECT COUNT(*) FROM gaikuo_items WHERE date=?", (today,)).fetchone()[0]
    if c:
        _n(db, "gaikuo", today, "概括句积累更新了 %d 条" % c, "材料表述 → 规范概括句", "gaikuo")

    # 范文推荐：每日更新一套新话题（含大作文 + 应用文小题）
    ep = db.execute("SELECT topic FROM essay_papers WHERE date(created_at)=? ORDER BY id DESC LIMIT 1",
                    (today,)).fetchone()
    if ep:
        _n(db, "essay", today, "范文更新了新话题：%s" % ep["topic"],
           "大作文范文 + 应用文小题完整参考答案", "essays")

    # 今日复习（遗忘曲线到期）
    due = _review_due(db, uid(), today)
    if due:
        g = {"word": 0, "daily": 0, "wrongq": 0}
        for it in due:
            g[RV_GROUP.get(it["kind"], "wrongq")] += 1
        _n(db, "review", today, "今天有 %d 条要复习" % len(due),
           "词语句子 %d · 每日积累 %d · 错题 %d" % (g["word"], g["daily"], g["wrongq"]), "review")

    # 今日学习计划
    pl = db.execute("SELECT COUNT(*) n, SUM(done) d, SUM(minutes) m FROM plan_items "
                    "WHERE user_id=? AND date=?", (uid(), today)).fetchone()
    if pl and pl["n"]:
        undone = pl["n"] - (pl["d"] or 0)
        if undone:
            _n(db, "plan", today, "今日计划还剩 %d 项" % undone,
               "共 %d 项 · %d 分钟，已完成 %d 项" % (pl["n"], pl["m"] or 0, pl["d"] or 0), "tasks")
    elif db.execute("SELECT 1 FROM plan_profile WHERE user_id=?", (uid(),)).fetchone():
        _n(db, "plan", today, "今天还没有学习计划",
           "让规划助手看着你的复习进度和错题排一份", "tasks")

    # 每日任务未打卡
    tpls = db.execute("SELECT COUNT(*) FROM task_templates WHERE user_id=? AND active=1", (uid(),)).fetchone()[0]
    if tpls:
        done = db.execute("SELECT COUNT(*) FROM task_done WHERE user_id=? AND date=?", (uid(), today)).fetchone()[0]
        if done < tpls:
            _n(db, "tasks", today, "今日任务还剩 %d 项" % (tpls - done),
               "已完成 %d / %d，别断卡" % (done, tpls), "tasks")

    # 题库新卷
    q = db.execute("SELECT name FROM quiz_sets WHERE date(created_at)=? ORDER BY id DESC", (today,)).fetchall()
    if q:
        _n(db, "quiz", today, "题库新增 %d 套卷" % len(q), q[0]["name"], "quiz")

    db.commit()


@app.get("/api/notifications")
def notifications_list():
    db = get_db()
    try:
        _gen_notifications(db)
    except Exception:
        pass                       # 生成失败不能影响读消息
    rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY read, id DESC LIMIT 60",
                      (uid(),)).fetchall()
    unread = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0",
                        (uid(),)).fetchone()[0]
    return jsonify({"items": [dict(r) for r in rows], "unread": unread})


@app.get("/api/notifications/unread")
def notifications_unread():
    """轻量角标：只数未读，不触发生成。"""
    n = get_db().execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0",
                         (uid(),)).fetchone()[0]
    return jsonify({"unread": n})


@app.post("/api/notifications/<int:nid>/read")
def notification_read(nid):
    db = get_db()
    db.execute("UPDATE notifications SET read=1 WHERE id=? AND user_id=?", (nid, uid()))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/notifications/read_all")
def notifications_read_all():
    db = get_db()
    db.execute("UPDATE notifications SET read=1 WHERE user_id=?", (uid(),))
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/notifications")
def notifications_clear():
    db = get_db()
    db.execute("DELETE FROM notifications WHERE user_id=? AND read=1", (uid(),))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 申论真题卷：上传 → 自动拆题
def _sl_words(t):
    """申论字数：不含空白，标点计入（与考试口径一致）。"""
    return len(re.sub(r"\s+", "", t or ""))


# 页眉页脚、水印、答题卡行号 —— 从真题里抽出来的杂质，混进材料/题干会很难看
_JUNK_KW = re.compile(r"申公宝|优路教育|仅供学习|智能批改|都说得清来源|版权所有|www\.|扫码|关注公众号")
_JUNK_PAGE = re.compile(r"^第\s*\d+\s*页(?:\s*[·・.]?\s*共\s*\d+\s*页)?$")
_JUNK_GRID = re.compile(r"^(?:\d{1,2}00[ \t]*)+$")        # 答题卡行号：100 200 300 …


def _strip_artifacts(text):
    """去掉页眉页脚 / 水印 / 答题卡行号，保留正文与空行结构。"""
    out = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if s and (_JUNK_KW.search(s) or _JUNK_PAGE.fullmatch(s) or _JUNK_GRID.fullmatch(s)):
            continue
        out.append(ln)
    return "\n".join(out)


def _reflow(text):
    """把 PDF 版式的硬换行拼回自然段：段内换行去掉（中文可任意断行），空行分段。
    这样前端渲染时每一排都排满了再换行，不会中途留半截。"""
    text = (text or "").strip()
    # 「材料N / 资料N」序号标题单独成段，别和正文粘在一起
    text = re.sub(r"[ \t]*\n?[ \t]*((?:给定)?(?:材|资)料\s*[一二三四五六七八九十\d]{1,3})[.、：:]?[ \t]*",
                  r"\n\n\1\n\n", text)
    paras = re.split(r"\n[ \t]*\n+", text)
    out = []
    for p in paras:
        p = re.sub(r"[ \t]*\n[ \t]*", "", p.strip())
        if p:
            out.append(p)
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(out)).strip()


def _pdf_text_or_ocr(path, ext):
    """先按文本抽取；扫描件抽不出字就逐页 OCR（最多 30 页）。"""
    txt = (_extract_text(path, ext) or "").strip()
    if len(txt) >= 200 or ext != ".pdf":
        return txt
    tmp = tempfile.mkdtemp(prefix="slocr_")
    try:
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-png", "-l", "30", path,
                        os.path.join(tmp, "p")], check=True, timeout=900, capture_output=True)
        out = []
        for f in sorted(x for x in os.listdir(tmp) if x.endswith(".png")):
            out.append(_ocr_image(os.path.join(tmp, f)))
        return "\n".join(out).strip()
    except Exception:
        return txt
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# 「给定资料」「作答要求」在注意事项里也会被提一嘴，所以优先认独占一行的大标题
_SL_TITLE_MAT = re.compile(r"^[ \t]*(?:[二2][、.．]\s*)?给\s*定\s*资\s*料[ \t]*$", re.M)
_SL_TITLE_REQ = re.compile(r"^[ \t]*(?:[三3][、.．]\s*)?作\s*答\s*(?:要\s*求|任\s*务)[ \t]*$", re.M)
_SL_HEAD_MAT = re.compile(r"给\s*定\s*资\s*料")
_SL_HEAD_REQ = re.compile(r"作\s*答\s*要\s*求|作\s*答\s*任\s*务")
_SL_MAT_1 = re.compile(r"^[ \t]*(?:给定)?材\s*料\s*[一1][ \t]*$|^[ \t]*(?:给定)?材\s*料\s*[一1][：:，,]", re.M)
# 题号形式：第一题 / 1. / （2） / 三、  —— 只在「作答要求」之后的文本里找，不会误伤材料
_SL_Q_HEAD = re.compile(
    r"^[ \t]*(?:第\s*([一二三四五六七八九十\d]+)\s*题[.、．:：]?"
    r"|[（(]?\s*(\d{1,2})\s*[.、．)）]"
    r"|([一二三四五六七八九十]{1,3})\s*[、.．])\s*", re.M)
_SL_SCORE = re.compile(r"[（(]\s*(\d{1,2})\s*分\s*[）)]")
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _sl_word_range(text):
    """从「字数1000-1200字」「不超过200字」这类要求里读出字数区间。"""
    m = re.search(r"(\d{2,4})\s*[-~—－至]\s*(\d{2,4})\s*字", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"不\s*超\s*过\s*(\d{2,4})\s*字", text)
    if m:
        n = int(m.group(1))
        return int(n * 0.8), n
    m = re.search(r"不\s*少\s*于\s*(\d{2,4})\s*字", text)
    if m:
        n = int(m.group(1))
        return n, int(n * 1.3)
    m = re.search(r"(\d{2,4})\s*字\s*(?:左右|以内|以下)", text)
    if m:
        n = int(m.group(1))
        return int(n * 0.85), n
    return None, None


def _sl_sections(text):
    """定位材料段起点与作答要求起点。独立成行的大标题最可信；退一步用「材料1」；再退一步宽松匹配。"""
    req = None
    tr = list(_SL_TITLE_REQ.finditer(text))
    if tr:
        req = tr[-1]
    else:
        loose = list(_SL_HEAD_REQ.finditer(text))
        if loose:
            req = loose[-1]          # 注意事项里那次在前，真正的标题在后
    req_start = req.start() if req else max(0, len(text) - 3000)
    req_end = req.end() if req else req_start

    mat_start = 0
    tm = [m for m in _SL_TITLE_MAT.finditer(text) if m.end() < req_start]
    if tm:
        mat_start = tm[-1].end()
    m1 = _SL_MAT_1.search(text[:req_start])
    if m1 and (not tm or m1.start() >= mat_start):
        mat_start = m1.start()       # 直接从「材料1」开始，把注意事项甩掉
    if not tm and not m1:
        lm = [m for m in _SL_HEAD_MAT.finditer(text) if m.end() < req_start]
        if lm:
            mat_start = lm[-1].end()
    return mat_start, req_start, req_end


def _split_paper(text):
    """本地切分：材料段 / 作答要求段 / 各小题。AI 只负责判题型，省钱也更稳。"""
    text = _strip_artifacts(text)    # 先洗掉页眉页脚 / 答题卡行号
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    mat_start, req_start, req_end = _sl_sections(text)
    material = _reflow(text[mat_start:req_start].strip())
    if len(material) < 60:           # 切歪了，宁可把作答要求之前的全文当材料
        material = _reflow(text[:req_start].strip())
    qtext = text[req_end:].strip()

    heads = list(_SL_Q_HEAD.finditer(qtext))
    qs = []
    for i, h in enumerate(heads):
        cn = h.group(1) or h.group(3) or ""
        seq = _CN_NUM.get(cn, 0) or (int(h.group(2)) if h.group(2) else 0)
        body = qtext[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(qtext)].strip()
        if len(body) < 15:            # 误命中列表项
            continue
        qs.append({"seq": seq or (len(qs) + 1), "body": body})
    # 题号乱了就按出现顺序重编
    if not qs or len({q["seq"] for q in qs}) != len(qs):
        for i, q in enumerate(qs, 1):
            q["seq"] = i
    return material, qtext, qs


def _classify_questions(qs):
    """一次 AI 调用给所有小题定题型（题干短，很便宜）。"""
    lines = ["%d. %s" % (q["seq"], q["body"][:300].replace("\n", " ")) for q in qs]
    prompt = ("下面是一份申论真题的各道小题。请判断每题的题型，只能从这五个里选：\n"
              "guina=归纳概括题，zonghe=综合分析题，duice=提出对策题，guanche=贯彻执行题（要写公文/文书），"
              "zuowen=文章写作（大作文）。\n"
              "同时给出这道题的满分（题干里有「（X分）」就用它），以及题目要求的字数区间"
              "（题干里有「1000-1200字」「不超过200字」就照抄成 word_min/word_max，没有就填 0）。\n"
              '只输出 JSON：{"items":[{"seq":1,"qtype":"guina","full":15,"word_min":150,"word_max":200}]}\n\n'
              + "\n\n".join(lines))
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论教研老师，熟悉各题型的判别特征，严格输出 JSON。"},
         {"role": "user", "content": prompt}], temperature=0.1, max_tokens=1200, json_mode=True)
    if err:
        return {}
    try:
        return {int(x["seq"]): x for x in json.loads(rep).get("items", [])}
    except Exception:
        return {}


# ---------------------------------------------------------------- 小题训练：找点 + 写点
# 归纳概括 / 综合分析 / 提出对策，难点是同一个：**从材料里把要点找出来**。
# 所以拆成两步练，每步都能单独纠错：
#   第一步「找点」——在材料上勾画，判**找漏 / 找错 / 找重**（这一步不写字，只找）
#   第二步「写点」——照着勾画的地方写要点，判**概括到不到位**（抄原文、并成一坨、漏关键词）
#
# 判定的前提是：出题时就得存下「采分点 ↔ 材料原文的逐字依据」。没有依据就只能凭感觉批，
# 等于没批。所以 AI 出的每个采分点都要给 evidence，且**必须逐字出现在材料里**，服务端逐条核对。
FIND_TYPES = {
    "guina": ("归纳概括题", 15, 150, 250,
              "把材料里的同类信息抽出来、合并、分条 —— 不评价、不引申，材料有什么就写什么"),
    "zonghe": ("综合分析题", 20, 250, 350,
               "先亮观点/解释，再分层分析（是什么→为什么→怎么样），最后落回结论"),
    "duice": ("提出对策题", 20, 300, 400,
              "对策必须**从材料的问题里长出来**，一个问题对一条对策；要具体可执行，不许喊口号"),
}
# 断句：申论找点就是找句子，句子边界明确才判得准（自由划词区间对不齐，判定必然是玄学）。
# 两个坑（实测踩出来的）：
#   · 引号里的句号会把句子劈开，末尾剩个孤零零的「”」——闭引号/闭括号要并回上一句
#   · 「材料一」这种标题行也会成为「可勾画的句子」——要标成 head，不让点
_SENT_END = re.compile(r"(?<=[。！？；!?;])")
_CLOSERS = "”’\"'）)》】」』"
_MAT_HEAD = re.compile(r"^[（(]?\s*(?:给定)?[材资]\s*料\s*[一二三四五六七八九十\d]{1,3}\s*[）)]?[.、：:]?$")


def _find_sents(material):
    """材料 → 句子数组。前端按句渲染，勾画粒度就是句。head=True 的是标题行，不可勾画。"""
    out = []
    for pi, para in enumerate(material.split("\n")):
        para = para.strip()
        if not para:
            continue
        if _MAT_HEAD.match(para) or (len(para) <= 8 and not re.search(r"[。！？；，]", para)):
            out.append({"p": pi, "t": para, "head": True})
            continue
        parts = [x for x in _SENT_END.split(para) if x]
        merged = []
        for x in parts:
            # 「…了。」「”」被切成两段 —— 闭引号/闭括号开头的碎片并回上一句
            if merged and x[0] in _CLOSERS:
                merged[-1] += x
            elif merged and len(x.strip()) <= 3 and not re.search(r"[\u4e00-\u9fa5]", x):
                merged[-1] += x                     # 纯标点碎片也并回去
            else:
                merged.append(x)
        for x in merged:
            x = x.strip()
            if x:
                out.append({"p": pi, "t": x, "head": False})
    return out


def _find_locate(sents, evidence):
    """采分点的原文依据 → 落到哪几句上。整句包含、或句子被依据包含，都算。"""
    ev = re.sub(r"\s", "", evidence)
    hit = []
    for i, s in enumerate(sents):
        t = re.sub(r"\s", "", s["t"])
        if not t:
            continue
        if t in ev or ev in t:
            hit.append(i)
    return hit


def _find_build(db, uid_, qtype, stem, material, full, wmin, wmax, source, requirement=""):
    """材料 + 题干 → AI 标出采分点（逐字依据），存成一套可判的题。"""
    name, dfull, dmin, dmax = FIND_TYPES[qtype][0], FIND_TYPES[qtype][1], FIND_TYPES[qtype][2], FIND_TYPES[qtype][3]
    prompt = (
        "下面是一道申论**%s**的给定资料和题干。请像阅卷组一样，把**采分点**标出来。\n\n"
        "【题干】%s\n\n【给定资料】\n%s\n\n"
        "【要求】\n"
        "1. 一个采分点 = 一个独立的得分要点。%d 分的题一般 5~8 个点。\n"
        "2. 每个点给：\n"
        "   · point：概括后的要点表述（12~30 字，这是**答案里该写的话**，不是原文）\n"
        "   · evidence：这个点在材料里的依据，**从材料里逐字复制**（一句或连续两句，"
        "一字不差，含标点）—— 对不上原文的点我会直接丢掉\n"
        "   · score：分值（所有点加起来 = %d 分）\n"
        "3. **材料里有干扰信息**（背景铺垫、无关细节、重复表述），不要把它们标成采分点。\n"
        "4. 同一个意思在材料里出现两次的，**只标一个点**，evidence 取最完整的那处。\n\n"
        '只输出 JSON：{"points":[{"point":"","evidence":"","score":0}]}'
        % (name, stem, material[:8000], full or dfull, full or dfull))
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论阅卷组组长。采分点的依据必须逐字来自材料，"
                                       "绝不改写、不编造。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.3, max_tokens=2500, timeout=300, json_mode=True)
    if err:
        return None, err
    try:
        got = json.loads(rep).get("points") or []
    except Exception:
        return None, (jsonify({"error": "AI 返回格式异常，请重试"}), 502)

    sents = _find_sents(material)
    flat = re.sub(r"\s", "", material)
    points = []
    for p in got:
        ev = (p.get("evidence") or "").strip()
        pt = (p.get("point") or "").strip()
        if not ev or not pt:
            continue
        if re.sub(r"\s", "", ev) not in flat:      # 对不上原文的直接丢（宁可少，不能错）
            continue
        hit = _find_locate(sents, ev)
        if not hit:
            continue
        points.append({"point": pt, "evidence": ev, "score": float(p.get("score") or 0), "sents": hit})
    if len(points) < 3:
        return None, (jsonify({"error": "AI 标出的采分点太少或对不上原文，请重试"}), 502)

    cur = db.execute(
        "INSERT INTO find_papers(user_id,qtype,type_name,stem,requirement,full,word_min,word_max,"
        "material,points,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (uid_, qtype, name, stem, requirement, full or dfull, wmin or dmin, wmax or dmax,
         material, json.dumps(points, ensure_ascii=False), source))
    db.commit()
    return cur.lastrowid, None


@app.get("/api/find/types")
def find_types():
    db = get_db()
    n = {r["qtype"]: r["c"] for r in db.execute(
        "SELECT qtype, COUNT(*) c FROM find_papers WHERE user_id=? GROUP BY qtype", (uid(),))}
    return jsonify({"types": [
        {"key": k, "name": v[0], "full": v[1], "word_min": v[2], "word_max": v[3],
         "tip": v[4], "n": n.get(k, 0)} for k, v in FIND_TYPES.items()]})


@app.post("/api/find/gen")
def find_gen():
    """AI 按考试标准出一道：先造材料（含干扰信息），再标采分点。"""
    d = request.get_json(silent=True) or {}
    qtype = (d.get("qtype") or "guina").strip()
    if qtype not in FIND_TYPES:
        return jsonify({"error": "题型不对"}), 400
    topic = (d.get("topic") or "").strip()
    name, full, wmin, wmax, tip = FIND_TYPES[qtype]

    db = get_db()
    if not topic:                                    # 话题从最近的时政/概括句里挑，贴近真考
        r = db.execute("SELECT topic FROM gaikuo_items WHERE topic!='' "
                       "ORDER BY RANDOM() LIMIT 1").fetchone()
        topic = r[0] if r else "基层治理"

    prompt = (
        "命制一道申论**%s**（%d 分，%d~%d 字）。话题：%s。\n\n"
        "【给定资料要求】\n"
        "1. 3~4 则材料，每则 200~350 字，**总共 900~1200 字**。\n"
        "2. 要像真题：有具体的人、地、事、数据，有干部/群众的原话。\n"
        "3. **必须掺入干扰信息**——背景铺垫、无关细节、和要点重复的同义表述。"
        "找点训练的价值全在这儿：材料里如果句句是要点，那就没什么可练的。\n"
        "4. 每则材料用「材料一」「材料二」…开头，各占一段。\n\n"
        "【题干要求】一句话，明确作答对象和范围。%s\n\n"
        '只输出 JSON：{"stem":"题干","material":"给定资料全文（材料N 各占一行）"}'
        % (name, full, wmin, wmax, topic, tip))
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论命题人。材料要像真题：有细节、有原话、"
                                       "**有干扰信息**。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.7, max_tokens=3000, timeout=300, json_mode=True)
    if err:
        return err
    try:
        j = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502
    material = (j.get("material") or "").strip()
    stem = (j.get("stem") or "").strip()
    if len(material) < 400 or not stem:
        return jsonify({"error": "AI 没出好材料，请重试"}), 502

    pid, err = _find_build(db, uid(), qtype, stem, material, full, wmin, wmax, "AI 命题 · " + topic)
    if err:
        return err
    return jsonify({"id": pid}), 201


@app.get("/api/find/papers")
def find_papers():
    rows = get_db().execute(
        "SELECT id,qtype,type_name,stem,full,source,created_at,"
        "(SELECT COUNT(*) FROM find_records r WHERE r.paper_id=find_papers.id) done "
        "FROM find_papers WHERE user_id=? ORDER BY id DESC LIMIT 100", (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


def _find_paper(db, pid):
    r = db.execute("SELECT * FROM find_papers WHERE id=? AND user_id=?", (pid, uid())).fetchone()
    return r


@app.get("/api/find/paper/<int:pid>")
def find_paper(pid):
    """做题用：只给材料（按句切好）和题干 —— **采分点绝不下发**，否则前端一翻就看见答案了。"""
    db = get_db()
    r = _find_paper(db, pid)
    if not r:
        return jsonify({"error": "题目不存在"}), 404
    sents = _find_sents(r["material"])
    npt = len(json.loads(r["points"] or "[]"))
    return jsonify({"id": r["id"], "qtype": r["qtype"], "type_name": r["type_name"],
                    "stem": r["stem"], "full": r["full"],
                    "word_min": r["word_min"], "word_max": r["word_max"],
                    "source": r["source"], "n_points": npt,
                    "sents": [{"i": i, "p": s["p"], "t": s["t"]} for i, s in enumerate(sents)]})


@app.post("/api/find/check")
def find_check():
    """第一步判定：我勾画的这些句子，找对了没有？找漏了什么？找错了什么？找重了什么？"""
    d = request.get_json(silent=True) or {}
    pid = int(d.get("paper_id") or 0)
    picked = sorted({int(x) for x in (d.get("sents") or [])})
    db = get_db()
    r = _find_paper(db, pid)
    if not r:
        return jsonify({"error": "题目不存在"}), 404
    if not picked:
        return jsonify({"error": "先在材料里勾画你认为的要点句"}), 400
    points = json.loads(r["points"] or "[]")
    sents = _find_sents(r["material"])

    hit_by_point = []          # 每个采分点被我勾中了几句
    for p in points:
        ps = set(p["sents"])
        got = [i for i in picked if i in ps]
        hit_by_point.append(got)

    got_points = [i for i, g in enumerate(hit_by_point) if g]
    missed = [i for i, g in enumerate(hit_by_point) if not g]
    # 找错：勾了但不属于任何采分点 —— 这就是被干扰信息骗了
    all_pt_sents = {i for p in points for i in p["sents"]}
    wrong = [i for i in picked if i not in all_pt_sents]
    # 找重：同一个采分点勾了不止一句（同义重复／把整段都涂了）
    dup = [{"point": points[i]["point"], "sents": g} for i, g in enumerate(hit_by_point) if len(g) > 1]

    acc = round(100.0 * len(got_points) / len(points)) if points else 0
    return jsonify({
        "total": len(points), "found": len(got_points), "acc": acc,
        "ok": [{"point": points[i]["point"], "score": points[i]["score"],
                "sents": hit_by_point[i]} for i in got_points],
        "missed": [{"point": points[i]["point"], "score": points[i]["score"],
                    "sents": points[i]["sents"],
                    "evidence": points[i]["evidence"]} for i in missed],
        "wrong": [{"i": i, "t": sents[i]["t"]} for i in wrong if i < len(sents)],
        "dup": dup,
    })


@app.post("/api/find/grade")
def find_grade():
    """第二步判定：照着找到的点写出来的答案，概括到不到位。"""
    d = request.get_json(silent=True) or {}
    pid = int(d.get("paper_id") or 0)
    answer = (d.get("answer") or "").strip()
    picked = sorted({int(x) for x in (d.get("sents") or [])})
    db = get_db()
    r = _find_paper(db, pid)
    if not r:
        return jsonify({"error": "题目不存在"}), 404
    if len(answer) < 20:
        return jsonify({"error": "答案太短了"}), 400
    points = json.loads(r["points"] or "[]")
    std = "\n".join("%d. %s（%g 分）依据：%s" % (i + 1, p["point"], p["score"], p["evidence"][:60])
                    for i, p in enumerate(points))

    prompt = (
        "批改一道申论**%s**（%d 分，要求 %d~%d 字）。\n\n"
        "【题干】%s\n\n"
        "【采分点】（阅卷标准，考生看不到）\n%s\n\n"
        "【考生答案】\n%s\n\n"
        "【怎么批】\n"
        "1. 逐个采分点判：**写到了 / 沾边但不到位 / 没写**。判「写到了」的标准是"
        "**意思对上**，不要求用词一样。\n"
        "2. 「沾边但不到位」要说清差在哪：是抄原文没概括？是几个点并成了一坨？"
        "还是漏了关键限定词？\n"
        "3. 另外指出**表述问题**：有没有抄原文、有没有加自己的评论（归纳概括题不许评价）、"
        "有没有分条、字数够不够（当前 %d 字）。\n"
        "4. 给分要实在，别送分。\n\n"
        "只输出 JSON：\n"
        '{"score":0,"items":[{"point":"采分点原话","got":"full|part|miss","score":0,'
        '"comment":"一句话说清写到没写到、差在哪"}],'
        '"style":["表述问题，每条一句话"],"advice":"一句话：下次怎么改进"}'
        % (r["type_name"], r["full"], r["word_min"], r["word_max"], r["stem"], std, answer,
           len(re.sub(r"\s", "", answer))))
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论阅卷组组长。逐个采分点对照批改，"
                                       "给分实在，说清差在哪。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.3, max_tokens=2500, timeout=300, json_mode=True)
    if err:
        return err
    try:
        g = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502

    score = float(g.get("score") or 0)
    db.execute("INSERT INTO find_records(user_id,paper_id,marks,find_result,answer,grade,score,full) "
               "VALUES(?,?,?,?,?,?,?,?)",
               (uid(), pid, json.dumps(picked), json.dumps(d.get("find_result") or {}, ensure_ascii=False),
                answer, json.dumps(g, ensure_ascii=False), score, r["full"]))
    db.commit()
    g["full"] = r["full"]
    return jsonify(g)


@app.post("/api/find/upload")
def find_upload():
    """上传真题文档 → 拆出材料和小题 → 只留归纳概括/综合分析/提出对策，各标一套采分点。
       抽文本、拆题、判题型全部复用真题批改那条管线（_split_paper / _classify_questions）。"""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    mime = (f.mimetype or "").lower()
    tmp = os.path.join(tempfile.gettempdir(), "find_" + uuid.uuid4().hex + ext)
    f.save(tmp)
    try:
        text = _ocr_image(tmp) if (mime.startswith("image/") or ext in IMAGE_EXT) \
            else _pdf_text_or_ocr(tmp, ext)
    except Exception:
        text = ""
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass
    text = (text or "").strip()
    if len(text) < 200:
        return jsonify({"error": "没能从文件里读到足够的文字（扫描件太糊或是纯图片）"}), 400

    material, _qtext, qs = _split_paper(text)
    if not qs:
        return jsonify({"error": "没识别出题目。请确认文件里有「作答要求」部分"}), 400
    cls = _classify_questions(qs)

    db = get_db()
    made, skipped = [], []
    for q in qs:
        c = cls.get(q["seq"], {})
        key = c.get("qtype") or "guina"
        if key not in FIND_TYPES:                 # 贯彻执行、大作文不属于「找点」训练
            skipped.append(_SL_TYPES.get(key, {}).get("name") or key)
            continue
        lo, hi = _sl_word_range(q["body"])
        m = _SL_SCORE.search(q["body"])
        full = int(m.group(1)) if m else int(c.get("full") or FIND_TYPES[key][1])
        pid, err = _find_build(db, uid(), key, q["body"][:1200], material, full,
                               lo or int(c.get("word_min") or 0), hi or int(c.get("word_max") or 0),
                               "真题 · " + os.path.splitext(f.filename)[0][:40])
        if not err:
            made.append({"id": pid, "type": FIND_TYPES[key][0], "seq": q["seq"]})
    if not made:
        return jsonify({"error": "这份卷子里没有归纳概括/综合分析/提出对策题"
                                 + ("（识别到：%s）" % "、".join(skipped) if skipped else "")}), 400
    return jsonify({"made": made, "skipped": skipped}), 201


@app.post("/api/shenlun/paper/upload")
def shenlun_paper_upload():
    """上传真题（PDF/Word/图片/文本）→ 拆出给定资料与各小题，自动判题型和字数要求。"""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    mime = (f.mimetype or "").lower()
    tmp = os.path.join(tempfile.gettempdir(), "slpaper_" + uuid.uuid4().hex + ext)
    f.save(tmp)
    try:
        if mime.startswith("image/") or ext in IMAGE_EXT:
            text = _ocr_image(tmp)
        else:
            text = _pdf_text_or_ocr(tmp, ext)
    except Exception as e:
        text = ""
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass
    text = (text or "").strip()
    if len(text) < 200:
        return jsonify({"error": "没能从文件里读到足够的文字（扫描件太糊或是纯图片）"}), 400

    material, qtext, qs = _split_paper(text)
    if not qs:
        return jsonify({"error": "没识别出题目。请确认文件里有「作答要求」部分"}), 400
    cls = _classify_questions(qs)

    title = (request.form.get("title") or "").strip() or os.path.splitext(f.filename)[0][:60]
    db = get_db()
    cur = db.execute("INSERT INTO shenlun_papers(user_id,title,material,source) VALUES(?,?,?,?)",
                     (uid(), title, material[:60000], f.filename))
    pid = cur.lastrowid
    for q in qs:
        c = cls.get(q["seq"], {})
        key = c.get("qtype") if c.get("qtype") in _SL_TYPES else "guina"
        t = _SL_TYPES[key]
        lo, hi = _sl_word_range(q["body"])
        lo = lo or int(c.get("word_min") or 0) or t["word_min"]
        hi = hi or int(c.get("word_max") or 0) or t["word_max"]
        m = _SL_SCORE.search(q["body"])
        full = int(m.group(1)) if m else int(c.get("full") or t["full"])
        db.execute("INSERT INTO shenlun_questions(paper_id,seq,qtype,type_name,stem,requirement,"
                   "full,word_min,word_max) VALUES(?,?,?,?,?,?,?,?,?)",
                   (pid, q["seq"], key, t["name"], q["body"][:3000], "", full, lo, hi))
    db.commit()
    return jsonify(_paper_detail(db, pid)), 201


def _paper_detail(db, pid):
    p = db.execute("SELECT * FROM shenlun_papers WHERE id=? AND user_id=?", (pid, uid())).fetchone()
    if not p:
        return None
    qs = db.execute("SELECT * FROM shenlun_questions WHERE paper_id=? ORDER BY seq", (pid,)).fetchall()
    best = {}
    for r in db.execute("SELECT question_id, id, score, full FROM shenlun_grade "
                        "WHERE user_id=? AND paper_id=? ORDER BY id", (uid(), pid)):
        best[r["question_id"]] = {"grade_id": r["id"], "score": r["score"], "full": r["full"]}
    def clean_q(q):
        q = dict(q)
        q["body"] = _strip_artifacts(q.get("body") or "")
        return dict(q, done=best.get(q["id"]))
    # 老数据也顺手洗一遍：页眉页脚 / 答题卡行号去掉，材料硬换行拼回自然段
    return {"id": p["id"], "title": p["title"],
            "material": _reflow(_strip_artifacts(p["material"] or "")),
            "created_at": p["created_at"],
            "questions": [clean_q(q) for q in qs]}


@app.get("/api/shenlun/papers")
def shenlun_papers():
    rows = get_db().execute(
        "SELECT p.id, p.title, p.created_at,"
        "(SELECT COUNT(*) FROM shenlun_questions q WHERE q.paper_id=p.id) total,"
        "(SELECT COUNT(DISTINCT g.question_id) FROM shenlun_grade g "
        " WHERE g.paper_id=p.id AND g.user_id=p.user_id) done "
        "FROM shenlun_papers p WHERE p.user_id=? ORDER BY p.id DESC LIMIT 40", (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.get("/api/shenlun/paper/<int:pid>")
def shenlun_paper(pid):
    d = _paper_detail(get_db(), pid)
    return (jsonify(d), 200) if d else (jsonify({"error": "未找到"}), 404)


@app.delete("/api/shenlun/paper/<int:pid>")
def shenlun_paper_del(pid):
    db = get_db()
    if not db.execute("SELECT 1 FROM shenlun_papers WHERE id=? AND user_id=?", (pid, uid())).fetchone():
        return jsonify({"error": "未找到"}), 404
    db.execute("DELETE FROM shenlun_questions WHERE paper_id=?", (pid,))
    db.execute("DELETE FROM shenlun_papers WHERE id=?", (pid,))
    db.execute("UPDATE shenlun_grade SET paper_id=NULL, question_id=NULL WHERE paper_id=?", (pid,))
    db.commit()
    return jsonify({"ok": True})


def _gen_reference(t, question, material, wmin, wmax, tries=2):
    """单独生成参考范文，按题目要求的字数区间严格校验，超/欠就让它重写。
    塞进批改那个 JSON 里是行不通的——模型为了不把 JSON 撑爆，总会把范文写短。"""
    target = wmin + int((wmax - wmin) * 0.4)      # 目标压在区间偏下，模型习惯性写多
    is_essay = t["key"] == "zuowen"
    frame = ("按「开头点题 — 分论点1 — 分论点2 — 分论点3 — 结尾升华」写一篇完整议论文，自拟标题。"
             if is_essay else "按该题型的规范答案框架分条作答，要点齐全、语言书面化。")
    mat = ("【给定资料】\n" + material[:9000]) if material else ""
    base = ("你是申论阅卷老师，现在写一份可以拿满分的参考答案。\n\n【题干】\n%s\n\n%s\n\n"
            "%s\n题目要求字数 %d~%d 字，请写到 %d 字左右——字数是硬性要求，宁可略少也不要超。\n"
            "只输出答案正文：不要 Markdown 记号（不要 ** ##），不要任何解释、标注或字数统计。" %
            (question[:2000], mat, frame, wmin, wmax, target))
    msgs = [{"role": "system", "content": "你是资深申论老师，参考答案规范、切题、字数精准。"},
            {"role": "user", "content": base}]
    best, budget = "", max(1200, int(wmax * 2.2))
    for _ in range(tries + 1):
        rep, err = _ai_call_or_error(msgs, temperature=0.4, max_tokens=budget, timeout=300)
        if err:
            break
        ref = re.sub(r"[*#`]+", "", rep).strip()
        n = _sl_words(ref)
        if wmin <= n <= wmax:
            return ref
        # 留着离区间最近的那版兜底
        if not best or _sl_gap(n, wmin, wmax) < _sl_gap(_sl_words(best), wmin, wmax):
            best = ref
        how = "扩写到" if n < wmin else "压缩到"
        msgs = msgs[:1] + [
            {"role": "user", "content": base},
            {"role": "assistant", "content": ref},
            {"role": "user", "content": "这份答案 %d 字，不符合要求。请%s %d~%d 字（目标 %d 字），"
                                        "保持要点与结构，只输出答案正文。" % (n, how, wmin, wmax, target)}]
    return best


def _sl_gap(n, lo, hi):
    return 0 if lo <= n <= hi else (lo - n if n < lo else n - hi)


# 大作文固定四维（与主流阅卷口径一致，合计 35 分）
_SL_DIMS = [("立意", 10), ("结构", 7), ("论证与材料运用", 10), ("语言", 8)]

SL_SYS = ("你是阅卷经验丰富的申论老师，严格对照给定资料的采分点批改，只认材料里有的要点，"
          "不编造材料里没有的内容。评分克制、有依据，严格输出 JSON。")


@app.post("/api/shenlun/grade")
def shenlun_grade():
    """逐点批改：像阅卷老师一样对照采分点，逐条说清答到没答到、错在哪、怎么补。
    传 question_id 时，题干/材料/满分/字数要求都从真题卷里取，批完顺带告诉前端下一题是哪道。"""
    d = request.get_json(silent=True) or {}
    db = get_db()

    qrow = None
    qid = int(d.get("question_id") or 0)
    if qid:
        qrow = db.execute(
            "SELECT q.*, p.material, p.id pid FROM shenlun_questions q "
            "JOIN shenlun_papers p ON p.id=q.paper_id WHERE q.id=? AND p.user_id=?",
            (qid, uid())).fetchone()
        if not qrow:
            return jsonify({"error": "题目不存在"}), 404

    key = (qrow["qtype"] if qrow else (d.get("type") or "")).strip()
    t = _SL_TYPES.get(key)
    if not t:
        return jsonify({"error": "请选择题型"}), 400

    question = (qrow["stem"] if qrow else (d.get("question") or "")).strip()
    material = (qrow["material"] if qrow else (d.get("material") or "")).strip()
    answer = (d.get("answer") or "").strip()
    if not question:
        return jsonify({"error": "请填写题干"}), 400
    if len(answer) < 10:
        return jsonify({"error": "请填写你的答案（至少 10 个字）"}), 400

    full = int((qrow["full"] if qrow else 0) or d.get("full") or t["full"])
    wmin = int((qrow["word_min"] if qrow else 0) or d.get("word_min") or t["word_min"])
    wmax = int((qrow["word_max"] if qrow else 0) or d.get("word_max") or t["word_max"])
    words = _sl_words(answer)

    is_essay = key == "zuowen"
    if is_essay:
        dims = "、".join("%s（0-%d 分）" % (n, m) for n, m in _SL_DIMS)
        rubric = ("按固定的四个维度打分，points 里每个维度一条，顺序不变：%s。\n"
                  "（若本题满分不是 35 分，请按比例折算各维度满分。）\n"
                  'name=维度名，max=该维度满分，got=实际得分，yours=引用考生原文中最能体现该维度的一句，\n'
                  'hits=做得好的地方，misses=扣分点，material=（留空字符串）。' % dims)
    else:
        rubric = ("先从给定资料中提炼出这道题的采分点（每个采分点一条），再逐条对照考生答案：\n"
                  'name=采分点名（如「总领」「接近、启发村民」），max=该点分值，got=实际得分，\n'
                  'yours=考生答案里对应这一点的原文（没写到就填空字符串），\n'
                  'hits=已写到的要点，misses=未写到的要点，partial=部分写到的要点，\n'
                  'material=支撑这个采分点的给定资料原文（务必逐字摘自材料）。')

    # 字数是硬性要求，超/欠都要在「语言」或总分上体现
    wtip = ("本题要求 %d~%d 字，考生实际写了 %d 字。%s\n" %
            (wmin, wmax, words,
             "字数达标。" if wmin <= words <= wmax else
             ("字数不足，请在评分与建议中指出。" if words < wmin else "字数超出，请在评分与建议中指出。")))

    mat = ("【给定资料】\n" + material[:9000]) if material else "（考生没有提供给定资料，请基于题干与常识判断，material 一律留空）"
    prompt = (
        "题型：%s（满分 %d 分）\n\n【题干】\n%s\n\n%s\n\n%s\n【考生答案】（%d 字）\n%s\n\n"
        "%s\n\n"
        "另外给出 advice（不超过 3 条、具体可操作的改进建议）、level（优秀/达标/待提升）。\n"
        "points 不超过 6 条，每条 material 摘录不超过 80 字。不要输出参考答案。\n"
        '严格只输出这个结构的 JSON：{"score":9,"full":%d,"level":"优秀","points":[{"name":"","max":2,"got":1,'
        '"yours":"","hits":[],"misses":[],"partial":[],"material":""}],"advice":[]}'
        % (t["name"], full, question[:2000], mat, wtip, words, answer[:8000], rubric, full))

    msgs = [{"role": "system", "content": SL_SYS}, {"role": "user", "content": prompt}]
    res = None
    for attempt in range(2):
        rep, err = _ai_call_or_error(msgs, temperature=0.2, max_tokens=4000,
                                     timeout=300, json_mode=True)
        if err:
            return err
        try:
            res = json.loads(rep)
            break
        except Exception:
            msgs = msgs[:2] + [
                {"role": "assistant", "content": rep[:200]},
                {"role": "user", "content": "上次的 JSON 没有输出完整。请重新输出完整、合法的 JSON："
                                            "points 精简到 4 条、每条 hits/misses 各不超过 2 句、material 不超过 40 字。"}]
    if res is None:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502
    # 参考范文单独生成：塞进同一个 JSON 里，模型为了不超长会把范文写短，字数根本压不住
    res["reference"] = _gen_reference(t, question, material, wmin, wmax)

    res["full"] = full
    try:
        res["score"] = max(0, min(full, float(res.get("score") or 0)))
    except Exception:
        res["score"] = 0
    pts = res.get("points") or []
    res["hit_n"] = sum(1 for p in pts if not (p.get("misses") or p.get("partial")))
    res["part_n"] = sum(1 for p in pts if p.get("partial"))
    res["miss_n"] = sum(1 for p in pts if p.get("misses") and not p.get("yours"))
    res.update({"words": words, "word_min": wmin, "word_max": wmax,
                "ref_words": _sl_words(res.get("reference") or ""),
                "question": question, "material": material, "answer": answer,
                "type_name": t["name"], "qtype": key})

    cur = db.execute(
        "INSERT INTO shenlun_grade(user_id,qtype,type_name,question,material,answer,score,full,result,"
        "paper_id,question_id,words,word_min,word_max) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid(), key, t["name"], question, material, answer, res["score"], full,
         json.dumps(res, ensure_ascii=False),
         qrow["pid"] if qrow else None, qid or None, words, wmin, wmax))
    db.commit()
    res["id"] = cur.lastrowid

    # 做完一题，告诉前端下一题是哪道
    if qrow:
        nx = db.execute("SELECT id, seq, type_name, full FROM shenlun_questions "
                        "WHERE paper_id=? AND seq>? ORDER BY seq LIMIT 1",
                        (qrow["pid"], qrow["seq"])).fetchone()
        res["paper_id"] = qrow["pid"]
        res["seq"] = qrow["seq"]
        res["next"] = dict(nx) if nx else None
    return jsonify(res)


@app.post("/api/shenlun/record/<int:rid>/reference")
def sl_regen_reference(rid):
    """单独重生成参考范文：批改时这一步是独立的一次 AI 调用，超时/失败就会是空的，
       没必要为了一篇范文把整个批改重跑一遍（那要两次调用）。"""
    db = get_db()
    r = db.execute("SELECT * FROM shenlun_grade WHERE id=? AND user_id=?", (rid, uid())).fetchone()
    if not r:
        return jsonify({"error": "记录不存在"}), 404
    res = json.loads(r["result"] or "{}")
    t = _SL_TYPES.get(r["qtype"]) or {"name": r["type_name"] or "申论", "key": r["qtype"]}
    ref = _gen_reference(t, r["question"] or "", r["material"] or "",
                         r["word_min"] or 200, r["word_max"] or 400)
    if not ref:
        return jsonify({"error": "AI 还是没给出范文，请稍后再试"}), 502
    res["reference"] = ref
    res["ref_words"] = _sl_words(ref)
    db.execute("UPDATE shenlun_grade SET result=? WHERE id=?", (json.dumps(res, ensure_ascii=False), rid))
    db.commit()
    return jsonify({"reference": ref, "ref_words": res["ref_words"]})


@app.get("/api/shenlun/history")
def shenlun_history():
    rows = get_db().execute(
        "SELECT g.id, g.qtype, g.type_name, substr(g.question,1,60) question, g.score, g.full, "
        "g.words, g.word_min, g.word_max, g.created_at, g.paper_id, g.question_id, "
        "p.title paper_title, q.seq "
        "FROM shenlun_grade g "
        "LEFT JOIN shenlun_papers p ON p.id=g.paper_id "
        "LEFT JOIN shenlun_questions q ON q.id=g.question_id "
        "WHERE g.user_id=? ORDER BY g.id DESC LIMIT 60", (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.get("/api/shenlun/record/<int:rid>")
def shenlun_record(rid):
    db = get_db()
    r = db.execute("SELECT * FROM shenlun_grade WHERE id=? AND user_id=?", (rid, uid())).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    d = dict(r)
    try:
        d["result"] = json.loads(d["result"])
    except Exception:
        d["result"] = {}
    # 老记录的 result 里没有原题/材料/作答原文，从行里补上，保证回看时四个页签都有内容
    res = d["result"]
    res.setdefault("question", d["question"])
    res.setdefault("material", d["material"])
    res.setdefault("answer", d["answer"])
    res.setdefault("type_name", d["type_name"])
    res.setdefault("words", d.get("words") or _sl_words(d["answer"]))
    res.setdefault("word_min", d.get("word_min"))
    res.setdefault("word_max", d.get("word_max"))
    res["id"] = d["id"]
    if d.get("question_id"):
        nx = db.execute("SELECT id, seq, type_name, full FROM shenlun_questions WHERE paper_id=? AND seq>"
                        "(SELECT seq FROM shenlun_questions WHERE id=?) ORDER BY seq LIMIT 1",
                        (d["paper_id"], d["question_id"])).fetchone()
        res["paper_id"] = d["paper_id"]
        res["next"] = dict(nx) if nx else None
    return jsonify(d)


@app.delete("/api/shenlun/record/<int:rid>")
def shenlun_record_del(rid):
    db = get_db()
    db.execute("DELETE FROM shenlun_grade WHERE id=? AND user_id=?", (rid, uid()))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 常考（高频考点合集）
CK_BOARDS = [
    {"key": "成语", "name": "高频成语", "icon": "quote", "desc": "老师讲义 · 按真题考频排序"},
    {"key": "实词", "name": "实词搭配", "icon": "edit", "desc": "老师讲义 · 常见动宾搭配"},
    {"key": "上位词", "name": "上位词", "icon": "layers", "desc": "概括词提示 · 下位词归类"},
    {"key": "古诗文", "name": "高频古诗文", "icon": "book", "desc": "按考频排序的名篇名句"},
    {"key": "常识", "name": "高频常识", "icon": "bulb", "desc": "常识判断反复出现的考点"},
    {"key": "提法", "name": "高频提法", "icon": "feather", "desc": "时政新提法 · 申论高频表述"},
]


@app.get("/api/changkao/boards")
def changkao_boards():
    db = get_db()
    counts = {r["board"]: r["c"] for r in
              db.execute("SELECT board, COUNT(*) c FROM changkao_items GROUP BY board")}
    counts["古诗文"] = db.execute("SELECT COUNT(*) FROM classics WHERE freq>=100").fetchone()[0]
    counts["上位词"] = db.execute("SELECT COUNT(*) FROM hyper_items").fetchone()[0]
    return jsonify({"boards": [dict(b, count=counts.get(b["key"], 0)) for b in CK_BOARDS]})


@app.get("/api/changkao/items")
def changkao_items():
    board = (request.args.get("board") or "成语").strip()
    db = get_db()
    if board == "古诗文":
        _ensure_classic_freq(db)
        rows = db.execute("SELECT id, title, author, dynasty, content FROM classics "
                          "WHERE freq>=100 ORDER BY freq DESC, id LIMIT 300").fetchall()
        return jsonify({"board": board, "kind": "classic", "items": [
            {"id": r["id"], "title": r["title"],
             "content": (r["content"] or "").split("\n")[0][:60],
             "note": ((r["dynasty"] or "") + " · " + (r["author"] or "")).strip(" ·")} for r in rows]})
    if board == "上位词":
        rows = db.execute("SELECT id, hyper, subs, note FROM hyper_items ORDER BY id DESC LIMIT 300").fetchall()
        return jsonify({"board": board, "kind": "hyper", "items": [
            {"id": r["id"], "title": r["hyper"], "content": r["subs"], "note": r["note"]} for r in rows]})
    # 成语/实词来自老师讲义，插入顺序就是考频从高到低的顺序
    rows = db.execute("SELECT id, title, content, note, freq FROM changkao_items WHERE board=? "
                      "ORDER BY id LIMIT 1000", (board,)).fetchall()
    return jsonify({"board": board, "kind": "text", "items": [dict(r) for r in rows]})


# ⚠️ 别叫 CK_BOARDS —— 那个名字已经被上面的板块元数据（字典列表）占了，
#    重名会把它整个盖掉，changkao_boards 里的 b["key"] 就会拿字符串去取下标。
CK_STAR_BOARDS = ["成语", "实词", "上位词", "古诗文", "常识", "提法"]
# 成语/实词收藏时，同步收进「言语理解 → 成语词语积累」，并落到对应分类里
CK_TO_ENTRY = {"成语": "成语", "实词": "词语"}


def _ck_one(db, board, iid):
    """按 (板块, id) 取回那一条 —— 六个模块散在三张表里，这里统一取。"""
    if board == "古诗文":
        r = db.execute("SELECT id, title, author, dynasty, content FROM classics WHERE id=?", (iid,)).fetchone()
        if not r:
            return None
        return {"title": r["title"], "content": (r["content"] or "").split("\n")[0][:60],
                "note": ((r["dynasty"] or "") + " · " + (r["author"] or "")).strip(" ·")}
    if board == "上位词":
        r = db.execute("SELECT hyper, subs, note FROM hyper_items WHERE id=?", (iid,)).fetchone()
        return {"title": r["hyper"], "content": r["subs"], "note": r["note"]} if r else None
    r = db.execute("SELECT title, content, note FROM changkao_items WHERE id=? AND board=?",
                   (iid, board)).fetchone()
    return {"title": r["title"], "content": r["content"], "note": r["note"]} if r else None


@app.post("/api/changkao/star")
def changkao_star():
    """收藏 / 取消收藏。成语和实词**同时**收进「成语词语积累」的对应分类里
       —— 收藏的目的就是拿去背，散在两处等于没收。"""
    d = request.get_json(silent=True) or {}
    board = (d.get("board") or "").strip()
    iid = int(d.get("id") or 0)
    if board not in CK_STAR_BOARDS or not iid:
        return jsonify({"error": "参数错误"}), 400
    db = get_db()
    have = db.execute("SELECT 1 FROM ck_stars WHERE user_id=? AND board=? AND item_id=?",
                      (uid(), board, iid)).fetchone()
    if have:
        db.execute("DELETE FROM ck_stars WHERE user_id=? AND board=? AND item_id=?", (uid(), board, iid))
        # 成语/实词：**同步从「成语词语积累」里删掉**（两边是同一份收藏，只删一边等于没删）
        removed = 0
        if board in CK_TO_ENTRY:
            it0 = _ck_one(db, board, iid)
            if it0:
                cur = db.execute("DELETE FROM entries WHERE user_id=? AND word=?",
                                 (uid(), it0["title"]))
                removed = cur.rowcount or 0
        db.commit()
        return jsonify({"starred": False, "removed_entry": removed})
    it = _ck_one(db, board, iid)
    if not it:
        return jsonify({"error": "这一条不存在"}), 404
    db.execute("INSERT OR REPLACE INTO ck_stars(user_id,board,item_id,title,content,note) "
               "VALUES(?,?,?,?,?,?)",
               (uid(), board, iid, it["title"], it["content"], it["note"]))
    to_entry = False
    cat = CK_TO_ENTRY.get(board)
    if cat:
        dup = db.execute("SELECT 1 FROM entries WHERE user_id=? AND word=?", (uid(), it["title"])).fetchone()
        if not dup:
            info = lookup(it["title"]) or {}
            db.execute(
                "INSERT INTO entries(user_id,word,pinyin,category,explanation,derivation,example,note,source) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (uid(), it["title"], info.get("pinyin") or "", cat,
                 info.get("explanation") or it["content"] or "",
                 info.get("derivation") or "", info.get("example") or "",
                 it["note"] or "", "常考收藏"))
            to_entry = True
    db.commit()
    return jsonify({"starred": True, "to_entry": to_entry, "category": cat or ""})


@app.get("/api/changkao/stars")
def changkao_stars():
    """我收藏的（按板块分组）。只要 ids 时用 ?ids=1，页面上标星用。"""
    db = get_db()
    rows = db.execute("SELECT * FROM ck_stars WHERE user_id=? ORDER BY board, created_at DESC",
                      (uid(),)).fetchall()
    if request.args.get("ids"):
        return jsonify({"ids": ["%s:%d" % (r["board"], r["item_id"]) for r in rows]})
    by = {}
    for r in rows:
        by.setdefault(r["board"], []).append(dict(r))
    return jsonify({"total": len(rows),
                    "boards": [{"board": b, "items": by[b]} for b in CK_STAR_BOARDS if b in by]})


def _real_example(db, word):
    """在**真实语料**里找含这个词的句子：人民日报等时政原文、时政要文、习语金句。
       找到了就是真出处 —— 比 AI 编一句强得多（AI 编的句子读着像那么回事，但不是真的）。"""
    like = "%" + word + "%"
    srcs = [
        ("SELECT content AS t, title AS s, source AS src FROM news_items WHERE content LIKE ? LIMIT 3",
         "news"),
        ("SELECT content AS t, title AS s, '' AS src FROM policy_docs WHERE content LIKE ? LIMIT 2",
         "policy"),
        ("SELECT quote AS t, category AS s, source_url AS src FROM xiyu_items WHERE quote LIKE ? LIMIT 2",
         "xiyu"),
    ]
    for sql, kind in srcs:
        try:
            rows = db.execute(sql, (like,)).fetchall()
        except Exception:
            continue
        for r in rows:
            text = (r["t"] or "").replace("\n", "")
            # 把含这个词的**那一句**切出来（前后到句号为止），太长的截断
            for sent in re.split(r"(?<=[。！？；])", text):
                if word in sent and 12 <= len(sent) <= 120:
                    if kind == "news":
                        src = (r["src"] or "时政报道") + "《" + (r["s"] or "")[:22] + "》"
                    elif kind == "policy":
                        src = "时政要文《" + (r["s"] or "")[:22] + "》"
                    else:
                        src = "习语金句"
                    return sent.strip(), src
    return None, None


@app.get("/api/changkao/<int:cid>/example")
def changkao_example(cid):
    """例句：真语料优先，AI 仿写兜底（会标明来源，不糊弄）。"""
    db = get_db()
    r = db.execute("SELECT * FROM changkao_items WHERE id=?", (cid,)).fetchone()
    if not r:
        return jsonify({"error": "词条不存在"}), 404
    if r["example"] and not request.args.get("force"):
        return jsonify({"example": r["example"], "src": r["example_src"] or "", "cached": True})

    word = r["title"]
    ex, src = _real_example(db, word)
    if not ex:
        rep, err = _ai_call_or_error(
            [{"role": "system", "content": "你是公考语文老师。例句要像《人民日报》《政府工作报告》"
                                           "那样的规范书面语（时政/公文语境），一句话，20~45 字。"
                                           "严格输出 JSON。"},
             {"role": "user", "content":
              "给「%s」（%s）写一个例句。\n"
              "要求：\n"
              "1. **时政/公文语境**（乡村振兴、基层治理、科技创新这类），像人民日报社论的句子。\n"
              "2. 用法必须准确（褒贬、搭配对象、能不能用于否定句，都要对）。\n"
              "3. 20~45 字，一句话。\n\n"
              '只输出 JSON：{"example":""}' % (word, (r["content"] or "")[:60])}],
            temperature=0.5, max_tokens=300, timeout=120, json_mode=True)
        if err:
            return err
        try:
            ex = (json.loads(rep).get("example") or "").strip()
        except Exception:
            return jsonify({"error": "AI 返回格式异常"}), 502
        if not ex or word not in ex:
            return jsonify({"error": "没造出合格的例句，请重试"}), 502
        # ⚠️ 老实标注：这是 AI 仿写的，不是真的从人民日报摘的
        src = "AI 仿写（人民日报文风）"

    db.execute("UPDATE changkao_items SET example=?, example_src=? WHERE id=?", (ex, src, cid))
    db.commit()
    return jsonify({"example": ex, "src": src})


@app.get("/api/changkao/<int:cid>/confuse")
def changkao_confuse(cid):
    """相似辨析：逻辑填空考的就是「这几个近义词该用哪个」。
       给出 2~3 个易混词，逐个对比：**词义侧重 / 感情色彩 / 搭配对象 / 语体**，
       并给一道「填空自测」（把这几个词摆一起，看你选不选得对）。
       易混词**优先从我们自己的成语库里挑**（这样辨析完这几个词都在你的复习范围内）。"""
    db = get_db()
    r = db.execute("SELECT * FROM changkao_items WHERE id=?", (cid,)).fetchone()
    if not r:
        return jsonify({"error": "词条不存在"}), 404
    if r["confuse"] and not request.args.get("force"):
        try:
            return jsonify(dict(json.loads(r["confuse"]), cached=True))
        except Exception:
            pass

    word = r["title"]
    # 库里的候选（同板块、考频高的）—— 让 AI 优先从这里面挑，辨析完的词都在复习范围内
    pool = [x[0] for x in db.execute(
        "SELECT title FROM changkao_items WHERE board=? AND title!=? "
        "ORDER BY COALESCE(freq,0) DESC LIMIT 300", (r["board"], word))]

    prompt = (
        "考生在背「%s」（%s）。请做一份**易混词辨析**。\n\n"
        "【选谁来对比】挑 2~3 个**最容易和它混**的词。**优先从下面这个词库里挑**"
        "（这样辨析完的词都在他的复习范围内）；库里实在没有合适的，才可以用库外的词。\n"
        "词库：%s\n\n"
        "【每个对比词要说清四件事】\n"
        "· focus：**词义侧重**在哪不一样（这是最关键的）\n"
        "· color：感情色彩（褒义/贬义/中性），有没有区别\n"
        "· collocation：**搭配对象**不一样在哪（能修饰什么、不能修饰什么）\n"
        "· wrong：一个**用错的例子**——把它误用在该用「%s」的地方，说清为什么不行\n\n"
        "【还要给】\n"
        "· key：一句话的**辨析口诀**（考场上 3 秒能想起来的那种）\n"
        "· quiz：一道填空自测 —— stem（一句话，中间一个空 ______）、"
        "options（把这几个词都列上，形如 \"A. …\"）、answer（正确选项字母）、"
        "why（为什么是它，其他为什么不行）\n\n"
        "只输出 JSON：\n"
        '{"key":"","items":[{"word":"","focus":"","color":"","collocation":"","wrong":""}],'
        '"quiz":{"stem":"","options":["A. …","B. …","C. …"],"answer":"A","why":""}}'
        % (word, (r["content"] or "")[:60], "、".join(pool[:150]), word))

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考言语理解老师。辨析要说到**用哪个**的层面，"
                                       "别只复述释义。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.4, max_tokens=2000, timeout=180, json_mode=True)
    if err:
        return err
    try:
        d = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502

    items = [x for x in (d.get("items") or []) if (x.get("word") or "").strip()][:3]
    if not items:
        return jsonify({"error": "没找到易混词"}), 502
    quiz = d.get("quiz") or {}
    # 自测题也要过一遍格式关：选项和答案对得上，否则不给（宁可不给，也不给一道错题）
    opts = quiz.get("options") or []
    ans = (quiz.get("answer") or "").strip().upper()[:1]
    if not (quiz.get("stem") and 2 <= len(opts) <= 5 and ans and ans in "ABCDE"[:len(opts)]):
        quiz = None

    # 库里有的对比词，带上 id —— 前端可以直接点过去看它的释义/典故
    ids = {}
    for x in items:
        row = db.execute("SELECT id FROM changkao_items WHERE board=? AND title=?",
                         (r["board"], x["word"])).fetchone()
        if row:
            ids[x["word"]] = row["id"]
        x["in_lib"] = bool(row)
        x["id"] = row["id"] if row else 0

    out = {"word": word, "board": r["board"], "key": (d.get("key") or "").strip(),
           "items": items, "quiz": quiz}
    db.execute("UPDATE changkao_items SET confuse=? WHERE id=?",
               (json.dumps(out, ensure_ascii=False), cid))
    db.commit()
    return jsonify(out)


@app.get("/api/changkao/<int:cid>/story")
def changkao_story(cid):
    """成语/实词的典故：出处原文、故事、本义→引申义怎么来的、易错点。
       看懂来历自然就记住了，比死背释义牢。AI 讲一次就缓存进 changkao_items.story。"""
    db = get_db()
    r = db.execute("SELECT * FROM changkao_items WHERE id=?", (cid,)).fetchone()
    if not r:
        return jsonify({"error": "词条不存在"}), 404
    if r["story"]:
        return jsonify({"id": cid, "title": r["title"], "board": r["board"],
                        "content": r["content"], "note": r["note"],
                        "freq": r["freq"], "story": json.loads(r["story"])})
    word, mean = r["title"] or "", (r["content"] or "")[:120]
    is_idiom = (r["board"] or "") == "成语"
    prompt = (
        "讲清「%s」的来历，让考生理解了再记，而不是死背释义。释义：%s\n\n"
        "给这几项：\n"
        "· origin：出处（哪本书、哪个人、什么年代；有原文就把**原句**引出来，注明篇目）\n"
        "· story：%s（80~160 字，有人物有情节，讲得让人记得住）\n"
        "· evolve：本义是什么 → 怎么引申成今天这个意思的（这一步最关键，理解了就不会用错）\n"
        "· usage：公考里怎么考它——常和哪些词辨析、什么语境用、褒贬中性、易错点\n\n"
        '只输出 JSON：{"origin":"","story":"","evolve":"","usage":""}'
        % (word, mean,
           "典故 / 历史故事" if is_idiom else "这个词的来源与用法演变（没有典故就讲它的构词与语感来源）"))
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是语文与公考言语老师，讲典故有据可查、不编造出处，语言生动。严格输出 JSON。"},
         {"role": "user", "content": prompt}], temperature=0.5, max_tokens=1600, timeout=180, json_mode=True)
    if err:
        return err
    try:
        st = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502
    if not (st.get("story") or st.get("origin")):
        return jsonify({"error": "没能讲出典故，请重试"}), 502
    db.execute("UPDATE changkao_items SET story=? WHERE id=?", (json.dumps(st, ensure_ascii=False), cid))
    db.commit()
    return jsonify({"id": cid, "title": r["title"], "board": r["board"],
                    "content": r["content"], "note": r["note"], "freq": r["freq"], "story": st})


@app.get("/api/hyper/<int:hid>")
def hyper_detail(hid):
    """上位词详解：每个下位词的**典故 / 出处 / 背景**。第一次点开时让 AI 讲一遍并缓存，
       之后直接读库——像古诗文那样点开就能看原文与赏析，理解了才记得住。"""
    db = get_db()
    r = db.execute("SELECT * FROM hyper_items WHERE id=?", (hid,)).fetchone()
    if not r:
        return jsonify({"error": "词条不存在"}), 404
    if r["story"]:
        return jsonify({"id": hid, "hyper": r["hyper"], "subs": r["subs"], "note": r["note"],
                        "story": json.loads(r["story"])})
    subs = [x.strip() for x in re.split(r"[、,，/]", r["subs"] or "") if x.strip()][:10]
    if not subs:
        return jsonify({"error": "这条没有下位词"}), 400
    prompt = (
        "上位词「%s」下面这些下位词，逐个讲清楚它的**来历与背景**，"
        "让考生理解了再记，而不是死背。\n下位词：%s\n\n"
        "每条给：\n"
        "· origin：出处 / 起源（哪个朝代、哪个地方、由什么演变而来，有史实就写史实）\n"
        "· story：典故或历史背景故事（60~120 字，讲得生动一点，有人物有情节最好；"
        "确实没有典故的，就讲它的形成过程或代表人物/代表作）\n"
        "· point：公考里怎么考它（常识题的考点，或逻辑填空里它作为「%s」这个概括词时的用法）\n\n"
        '只输出 JSON：{"items":[{"name":"","origin":"","story":"","point":""}]}'
        % (r["hyper"], "、".join(subs), r["hyper"]))
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考常识与文化通识老师，讲典故有史实、不编造，语言生动。严格输出 JSON。"},
         {"role": "user", "content": prompt}], temperature=0.5, max_tokens=3000, timeout=180, json_mode=True)
    if err:
        return err
    try:
        items = [x for x in (json.loads(rep).get("items") or []) if x.get("name")]
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502
    if not items:
        return jsonify({"error": "没能讲出典故，请重试"}), 502
    db.execute("UPDATE hyper_items SET story=? WHERE id=?", (json.dumps(items, ensure_ascii=False), hid))
    db.commit()
    return jsonify({"id": hid, "hyper": r["hyper"], "subs": r["subs"], "note": r["note"], "story": items})


# ---------------------------------------------------------------- 上位词积累
@app.get("/api/hyper")
def hyper_list():
    q = (request.args.get("q") or "").strip()
    db = get_db()
    if q:
        rows = db.execute("SELECT * FROM hyper_items WHERE hyper LIKE ? OR subs LIKE ? "
                          "ORDER BY id DESC LIMIT 200", ("%" + q + "%", "%" + q + "%")).fetchall()
    else:
        rows = db.execute("SELECT * FROM hyper_items ORDER BY id DESC LIMIT 200").fetchall()
    return jsonify({"items": [dict(r) for r in rows],
                    "total": db.execute("SELECT COUNT(*) FROM hyper_items").fetchone()[0]})


@app.get("/api/hyper/daily")
def hyper_daily():
    """每日推荐 3 组：按日期确定性轮换，全站一致。"""
    db = get_db()
    ids = [r[0] for r in db.execute("SELECT id FROM hyper_items ORDER BY id")]
    if not ids:
        return jsonify({"items": []})
    start = (datetime.now().toordinal() * 3) % len(ids)
    pick = [ids[(start + i) % len(ids)] for i in range(min(3, len(ids)))]
    rows = db.execute("SELECT * FROM hyper_items WHERE id IN (%s)" %
                      ",".join("?" * len(pick)), pick).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.post("/api/hyper/ai")
def hyper_ai():
    """输入一个词/一组词 → AI 给出上位词、同类下位词、辨析与例句，并收录。"""
    word = ((request.get_json(silent=True) or {}).get("word") or "").strip()
    if not word:
        return jsonify({"error": "请输入词语"}), 400
    db = get_db()
    hit = db.execute("SELECT * FROM hyper_items WHERE hyper=?", (word,)).fetchone()
    if hit:
        return jsonify(dict(hit, cached=True))
    prompt = ("公考「逻辑填空」中，题干出现一个类别名词（上位词），空格要填该类别下的具体成员（下位词）。\n"
              "示范：戏曲 → 京剧、越剧、黄梅戏、豫剧、昆曲；文房四宝 → 笔、墨、纸、砚。\n"
              "注意 hyper 必须是可数的类别名词，subs 必须是具体事物名称，不能是形容词。\n\n"
              "给定词语：%s\n请输出 JSON：\n"
              '{"hyper":"它所属的类别名词（若它本身就是类别名词，则原样输出）",'
              '"subs":"该类别下常见的具体成员，用顿号分隔，6~10个",'
              '"note":"一句话说明题干出现这个类别词时答案该选什么（40字内）",'
              '"example":"一个含空格的逻辑填空式例句，用____表示空（30~50字）"}\n只输出 JSON。' % word)
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考言语理解老师，熟悉逻辑填空的上下文提示逻辑。"},
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=400, json_mode=True)
    if err:
        return err
    try:
        d = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常"}), 502
    hyper = (d.get("hyper") or word).strip()
    db.execute("INSERT OR REPLACE INTO hyper_items(hyper,subs,note,example,source) VALUES(?,?,?,?,?)",
               (hyper, (d.get("subs") or "").strip(), (d.get("note") or "").strip(),
                (d.get("example") or "").strip(), "ai"))
    db.commit()
    r = db.execute("SELECT * FROM hyper_items WHERE hyper=?", (hyper,)).fetchone()
    return jsonify(dict(r, cached=False))


@app.delete("/api/hyper/<int:hid>")
def hyper_del(hid):
    db = get_db()
    db.execute("DELETE FROM hyper_items WHERE id=?", (hid,))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 应用文上位词
@app.get("/api/gongwen")
def gongwen_list():
    q = (request.args.get("q") or "").strip()
    db = get_db()
    if q:
        like = "%" + q + "%"
        rows = db.execute("SELECT * FROM gongwen_items WHERE scene LIKE ? OR phrases LIKE ? OR doctype LIKE ? "
                          "ORDER BY id LIMIT 200", (like, like, like)).fetchall()
    else:
        rows = db.execute("SELECT * FROM gongwen_items ORDER BY id LIMIT 200").fetchall()
    return jsonify({"items": [dict(r) for r in rows],
                    "total": db.execute("SELECT COUNT(*) FROM gongwen_items").fetchone()[0]})


@app.get("/api/gongwen/daily")
def gongwen_daily():
    """每日推荐 3 组：按日期确定性轮换，全站一致。"""
    db = get_db()
    ids = [r[0] for r in db.execute("SELECT id FROM gongwen_items ORDER BY id")]
    if not ids:
        return jsonify({"items": []})
    start = (datetime.now().toordinal() * 3) % len(ids)
    pick = [ids[(start + i) % len(ids)] for i in range(min(3, len(ids)))]
    rows = db.execute("SELECT * FROM gongwen_items WHERE id IN (%s)" %
                      ",".join("?" * len(pick)), pick).fetchall()
    order = {v: i for i, v in enumerate(pick)}
    return jsonify({"items": sorted([dict(r) for r in rows], key=lambda x: order.get(x["id"], 0))})


@app.post("/api/gongwen/ai")
def gongwen_ai():
    """输入口语句/场景 → AI 给出公文规范上位表述，并收录。"""
    text = ((request.get_json(silent=True) or {}).get("input") or "").strip()
    if not text:
        return jsonify({"error": "请输入一句口语表述，或一个应用文场景"}), 400
    db = get_db()
    prompt = ("公考申论应用文（公文）写作要求用词规范、书面化。考生给你一句口语化表述或一个写作场景，"
              "请把它归纳成公文里的「规范上位表述」，帮助考生答题时替换掉大白话。\n\n"
              "输入：%s\n\n请输出 JSON：\n"
              '{"scene":"这属于应用文的哪个场景（如「主体·工作举措」「结尾·号召」，10字内）",'
              '"phrases":"该场景常用的规范上位表述，用顿号分隔，6~10个，都要是书面公文用语",'
              '"doctype":"最常出现在哪些文种（如 通知/意见/倡议书，3个内）",'
              '"note":"一句话点明用法或易错点（40字内）",'
              '"example":"一个用上这些规范表述的完整示范句（30~60字）"}\n只输出 JSON。' % text[:200])
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论应用文（公文写作）阅卷老师，熟悉各文种的规范用语。"},
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=500, json_mode=True)
    if err:
        return err
    try:
        d = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常"}), 502
    scene = (d.get("scene") or text[:10]).strip()
    # 场景重名就并入（避免 UNIQUE 冲突覆盖种子），改标一个带序号的场景名
    if db.execute("SELECT 1 FROM gongwen_items WHERE scene=?", (scene,)).fetchone():
        scene = scene + "·" + datetime.now().strftime("%m%d%H%M")
    db.execute("INSERT INTO gongwen_items(scene,phrases,doctype,note,example,source) VALUES(?,?,?,?,?,'ai')",
               (scene, (d.get("phrases") or "").strip(), (d.get("doctype") or "").strip(),
                (d.get("note") or "").strip(), (d.get("example") or "").strip()))
    db.commit()
    r = db.execute("SELECT * FROM gongwen_items WHERE scene=?", (scene,)).fetchone()
    return jsonify(dict(r))


@app.delete("/api/gongwen/<int:gid>")
def gongwen_del(gid):
    db = get_db()
    db.execute("DELETE FROM gongwen_items WHERE id=? AND source='ai'", (gid,))  # 种子词库不许删
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 手写识别（申论作答）
# 本机直连 Google 不通、走本地代理可达；代理端口会变，做成可配 + 多端口兜底，记住能用的那个
_HW_ITC = "zh-t-i0-handwrit"
_hw_proxy_ok = None   # 上次跑通的代理，命中就先用它


def _hw_proxies():
    env = os.environ.get("GONGKAO_HW_PROXY", "").strip()
    cfg = ""
    try:
        cfg = (json.load(open(CONFIG, encoding="utf-8")).get("hw_proxy") or "").strip()
    except Exception:
        pass
    cand = [p for p in (_hw_proxy_ok, env, cfg) if p]
    cand += ["http://127.0.0.1:7897", "http://127.0.0.1:7890",
             "http://127.0.0.1:1080", "http://127.0.0.1:8080"]
    seen, out = set(), []
    for p in cand:
        if p and p not in seen:
            seen.add(p); out.append(p)
    return out


def _hw_recognize(ink, w, h):
    """把画布笔迹交给 Google 手写识别，返回候选字列表。经本地代理出网。"""
    global _hw_proxy_ok
    payload = {"options": "enable_pre_space", "requests": [{
        "writing_guide": {"writing_area_width": w, "writing_area_height": h},
        "ink": ink, "language": "zh"}]}
    data = json.dumps(payload).encode()
    saved = {k: os.environ.pop(k) for k in ("NO_PROXY", "no_proxy") if k in os.environ}
    try:
        for proxy in _hw_proxies():
            try:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
                req = urllib.request.Request(
                    "https://inputtools.google.com/request?itc=%s&app=demopage" % _HW_ITC,
                    data=data, headers={"Content-Type": "application/json"})
                raw = opener.open(req, timeout=10).read().decode("utf-8", "ignore")
                arr = json.loads(raw)
                if arr and arr[0] == "SUCCESS":
                    _hw_proxy_ok = proxy
                    return arr[1][0][1] or []
            except Exception:
                continue
        return None
    finally:
        os.environ.update(saved)


@app.post("/api/handwrite")
def handwrite():
    d = request.get_json(silent=True) or {}
    ink = d.get("ink") or []
    if not ink:
        return jsonify({"candidates": []})
    try:
        w = max(1, int(d.get("w") or 400))
        h = max(1, int(d.get("h") or 400))
    except Exception:
        w = h = 400
    cands = _hw_recognize(ink, w, h)
    if cands is None:
        return jsonify({"candidates": [], "error": "手写识别服务连不上，请稍后再试或直接键盘输入"}), 200
    return jsonify({"candidates": cands[:12]})


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
TH_BOARDS = [
    {"name": "马克思主义基本原理", "short": "马原", "icon": "compass",
     "desc": "唯物论 · 辩证法 · 认识论 · 唯物史观 · 政治经济学"},
    {"name": "毛泽东思想", "short": "毛概", "icon": "flag",
     "desc": "新民主主义革命 · 社会主义改造 · 活的灵魂"},
    {"name": "中国特色社会主义理论体系", "short": "中特", "icon": "layers",
     "desc": "邓小平理论 · 三个代表 · 科学发展观"},
    {"name": "习近平新时代中国特色社会主义思想", "short": "习思想", "icon": "star",
     "desc": "十个明确 · 十四个坚持 · 十三个方面成就"},
]


@app.get("/api/theory/boards")
def theory_boards():
    db = get_db()
    counts = {r["board"]: r["c"] for r in
              db.execute("SELECT board, COUNT(*) c FROM theory_items GROUP BY board")}
    return jsonify({"boards": [dict(b, count=counts.get(b["name"], 0)) for b in TH_BOARDS]})


@app.get("/api/theory/items")
def theory_items():
    board = (request.args.get("board") or "").strip()
    if not board:
        return jsonify({"error": "缺少板块"}), 400
    rows = get_db().execute("SELECT id, topic, title, content FROM theory_items WHERE board=? "
                            "ORDER BY id", (board,)).fetchall()
    groups, order = {}, []
    for r in rows:
        t = r["topic"] or "其他"
        if t not in groups:
            groups[t] = []
            order.append(t)
        groups[t].append({"id": r["id"], "title": r["title"], "content": r["content"]})
    meta = next((b for b in TH_BOARDS if b["name"] == board), {"name": board, "desc": ""})
    return jsonify({"board": board, "desc": meta.get("desc", ""), "count": len(rows),
                    "topics": [{"name": t, "items": groups[t]} for t in order]})


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
            pass
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
REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30, 60]  # 达到第 n 阶后，下次间隔天数


def _review_due(db, u, today):
    states = {(r["kind"], r["item_id"]): r for r in
              db.execute("SELECT * FROM review_state WHERE user_id=?", (u,)).fetchall()}
    due = []

    def check(kind, rid, created, payload):
        st = states.get((kind, rid))
        if st:
            if (st["next_due"] or "") <= today:
                due.append(dict(payload, kind=kind, id=rid, stage=st["stage"]))
        elif (created or "")[:10] < today:  # 收录次日进入第一轮复习
            due.append(dict(payload, kind=kind, id=rid, stage=0))

    for r in db.execute("SELECT * FROM entries WHERE user_id=?", (u,)):
        back = "\n".join(x for x in [
            (r["explanation"] or "").strip(),
            ("出处：" + r["derivation"]) if r["derivation"] else "",
            ("例句：" + r["example"]) if r["example"] else "",
            ("📝 " + r["note"]) if r["note"] else ""] if x)
        check("entry", r["id"], r["created_at"], {
            "title": r["word"], "sub": r["category"] or "词语", "body": (r["explanation"] or "")[:90],
            "front": r["word"], "front_sub": (r["pinyin"] or "") + " · " + (r["category"] or "词语"),
            "back": back or "（无释义）"})
    # 常考里的高频成语 / 实词搭配：按真题考频排的，比自己零散收录的更该背。
    # 只取考频最高的一批进复习轮，背完一轮会随考频往后推。
    # 池子开到「用户设的每日量」的 3 倍（自己收录的词也占这一组，得留位置）；
    # 真正每天出多少由 review_today 按上限截。设 0（不限）就把这批全放进来。
    _lw = _rv_limits(db, u)["word"]
    n_ck = 894 if _lw == 0 else max(120, _lw * 3)
    if n_ck > 0:
        for r in db.execute(
                "SELECT id, board, title, content, note, example, example_src FROM changkao_items "
                "WHERE board IN ('成语','实词') "
                "ORDER BY COALESCE(freq,0) DESC, id LIMIT ?", (n_ck,)):
            body = (r["content"] or "").strip()
            back = body + (("\n\n📌 " + r["note"]) if r["note"] else "")
            if r["example"]:                       # 光有释义记不住怎么用，背面给个例句
                back += "\n\n✍️ 例句：" + r["example"] + (
                    ("\n　　—— " + r["example_src"]) if r["example_src"] else "")
            check("changkao", r["id"], "2000-01-01", {          # 全局内容，不按收录时间等一天
                "title": r["title"] or "", "sub": r["board"] or "常考",
                "body": body[:90],
                "front": r["title"] or "", "front_sub": "常考 · " + (r["board"] or ""),
                "back": back or "（无释义）"})

    for r in db.execute("SELECT * FROM wrong_questions WHERE user_id=?", (u,)):
        back = "\n".join(x for x in [
            ("【知识点】" + r["points"]) if r["points"] else "",
            ("【方法】" + r["method"]) if r["method"] else "",
            ("【技巧】" + r["skill"]) if r["skill"] else "",
            ("【步骤】" + r["steps"]) if r["steps"] else "",
            ("【答案】" + r["answer"]) if r["answer"] else ""] if x)
        check("wrongq", r["id"], r["created_at"], {
            "title": (r["question"] or "（图片错题）")[:36], "sub": r["qtype"] or r["board"] or "错题",
            "body": (r["points"] or "")[:90],
            "front": (r["question"] or "（图片错题）"), "front_sub": r["qtype"] or r["board"] or "错题",
            "back": back or "（无解析，可回错题本重新分析）"})
    for r in db.execute("SELECT s.classic_id cid, s.created_at ca, c.title t, c.author a, c.dynasty dy, "
                        "c.content ct, c.translation tr FROM classic_stars s "
                        "JOIN classics c ON c.id=s.classic_id WHERE s.user_id=?", (u,)):
        back = (r["ct"] or "")
        if r["tr"]:
            back += "\n\n【译文】" + r["tr"][:300]
        check("classic", r["cid"], r["ca"], {
            "title": r["t"], "sub": r["a"] or "古诗文", "body": (r["ct"] or "").split("\n")[0][:44],
            "front": r["t"], "front_sub": ((r["dy"] or "") + " · " + (r["a"] or "")).strip(" ·"),
            "back": back or "（无内容）"})
    # 议论文素材（全局每日更新，人人都要背）：最近 60 天的进入复习轮
    for r in db.execute("SELECT * FROM sucai_items WHERE date >= date('now','localtime','-60 day') "
                        "ORDER BY id DESC LIMIT 300"):
        body = (r["content"] or "").strip()
        back = body + (("\n\n【例句】" + r["example"]) if r["example"] else "")
        # 正面给「人名/地名 + 首句」当回忆线索（素材开头就是主体），光给「为民·担当」这种主题回忆不起来
        cue = re.split(r"[，,。；;、]", body, 1)[0][:22]
        front = cue or (r["topic"] or "").strip() or (r["kind"] or "素材")
        front_sub = (r["kind"] or "素材") + ((" · " + r["topic"]) if r["topic"] else "")
        if r["kind"] == "衔接表达":          # 句式类：正面给用途，背面给句式本身
            front, front_sub = "衔接表达 · 回忆句式", (r["kind"] or "素材")
            back = body + (("\n\n【例句】" + r["example"]) if r["example"] else "")
        check("sucai", r["id"], r["created_at"], {
            "title": (r["topic"] or r["kind"] or "素材")[:36], "sub": r["kind"] or "素材",
            "body": body[:90], "front": front, "front_sub": front_sub,
            "back": back or "（无内容）"})
    return due


# 复习分组：词语句子 / 每日积累 / 错题，分开背，不混在一副牌里
RV_GROUP = {"entry": "word", "classic": "word", "changkao": "word", "sucai": "daily", "wrongq": "wrongq"}
RV_NAMES = {"word": "词语句子", "daily": "每日积累", "wrongq": "错题"}
RV_LIMIT_DEF = {"word": 40, "daily": 20, "wrongq": 10}     # 每日复习量默认值（0 = 不限）


def _rv_limits(db, u):
    r = db.execute("SELECT rv_limits FROM users WHERE id=?", (u,)).fetchone()
    try:
        got = json.loads((r["rv_limits"] if r else "") or "{}")
    except Exception:
        got = {}
    out = {}
    for k, v in RV_LIMIT_DEF.items():
        n = got.get(k)
        out[k] = v if n is None else max(0, min(500, int(n)))
    return out


@app.get("/api/review/limits")
def review_limits_get():
    db = get_db()
    lim = _rv_limits(db, uid())
    due = _review_due(db, uid(), datetime.now().strftime("%Y-%m-%d"))
    pool = {"word": 0, "daily": 0, "wrongq": 0}
    for it in due:
        pool[RV_GROUP.get(it["kind"], "wrongq")] += 1
    return jsonify({"limits": lim, "default": RV_LIMIT_DEF, "names": RV_NAMES, "due": pool})


@app.post("/api/review/limits")
def review_limits_set():
    d = request.get_json(silent=True) or {}
    cur = _rv_limits(get_db(), uid())
    for k in RV_LIMIT_DEF:
        if k in d:
            try:
                cur[k] = max(0, min(500, int(d[k])))
            except Exception:
                pass
    db = get_db()
    db.execute("UPDATE users SET rv_limits=? WHERE id=?",
               (json.dumps(cur, ensure_ascii=False), uid()))
    db.commit()
    return jsonify({"limits": cur})


@app.get("/api/review/today")
def review_today():
    today = datetime.now().strftime("%Y-%m-%d")
    db = get_db()
    due = _review_due(db, uid(), today)
    order = {"entry": 0, "classic": 1, "sucai": 2, "wrongq": 3}
    # 组内排序：**已经在复习轮里的排前面**（stage>0 说明背过一遍了，别让它一直往后堆），
    # 然后才是新词。被上限截掉的不动 next_due —— 只是今天不出现，明天照样在。
    due.sort(key=lambda x: (order.get(x["kind"], 9), -int(x.get("stage") or 0), x["id"]))
    lim = _rv_limits(db, uid())
    pool = {"word": 0, "daily": 0, "wrongq": 0}
    for it in due:
        it["group"] = RV_GROUP.get(it["kind"], "wrongq")
        pool[it["group"]] += 1
    kept, used = [], {"word": 0, "daily": 0, "wrongq": 0}
    for it in due:
        g = it["group"]
        if lim[g] and used[g] >= lim[g]:      # 上限 0 = 不限
            continue
        used[g] += 1
        kept.append(it)
    return jsonify({"today": today, "count": len(kept), "items": kept,
                    "groups": used, "pool": pool, "limits": lim})


@app.post("/api/review/done")
def review_done():
    data = request.get_json(silent=True) or {}
    kind, rid = (data.get("kind") or "").strip(), int(data.get("id") or 0)
    result = (data.get("result") or "know").strip()  # know认识 / fuzzy模糊 / forget忘记
    # 白名单直接取自 RV_GROUP，别手抄第二份 —— 上次加「常考」这一路复习来源时，
    # 取词那边（_review_due）加了、提交这边忘了加，结果卡片点「认识」直接「参数错误」。
    if kind not in RV_GROUP or not rid:
        return jsonify({"error": "参数错误"}), 400
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    st = db.execute("SELECT stage FROM review_state WHERE user_id=? AND kind=? AND item_id=?",
                    (uid(), kind, rid)).fetchone()
    cur = st["stage"] if st else 0
    if result == "forget":       # 忘记：重置，今日稍后重现
        stage, iv, nd = 0, 0, today
    elif result == "fuzzy":      # 模糊：不升轮，明天再看
        stage, iv = max(cur, 1), 1
        nd = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    else:                        # 认识：进入下一轮（1/2/4/7/15/30/60）
        stage = cur + 1
        iv = REVIEW_INTERVALS[min(stage, len(REVIEW_INTERVALS) - 1)]
        nd = (datetime.now() + timedelta(days=iv)).strftime("%Y-%m-%d")
    db.execute("INSERT OR REPLACE INTO review_state(user_id,kind,item_id,stage,next_due,last_done) "
               "VALUES(?,?,?,?,?,?)", (uid(), kind, rid, stage, nd, today))
    db.commit()
    return jsonify({"stage": stage, "next_due": nd, "interval": iv, "result": result})


# ---------------------------------------------------------------- 数据版本（浏览器/手机自动同步用）
@app.get("/api/sync")
def api_sync():
    """返回当前用户可见数据的版本指纹；变化了说明有别的端改过，前端自动刷新当前视图。"""
    db = get_db()
    u = uid()
    parts = []
    for sql, args in [
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM notes WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM materials WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(MAX(LENGTH(content)),0) FROM kb_nodes WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM entries WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM wrong_questions WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM board_points WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM news_items", ()),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM gaikuo_items", ()),
        ("SELECT COUNT(*), COALESCE(MAX(news_id),0) FROM news_stars WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM sucai_items", ()),
        ("SELECT COUNT(*), COALESCE(MAX(rowid),0) FROM review_state WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0) FROM changshi_items", ()),
        # 组队/互监：申请或成员一变，指纹就变，对端能自动刷新
        ("SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(MAX(status),'') FROM team_requests WHERE from_uid=? OR to_uid=?", (u, u)),
        ("SELECT COUNT(*) FROM team_members WHERE user_id=?", (u,)),
        ("SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(SUM(done),0) FROM shared_todos", ()),
    ]:
        try:
            parts.append(",".join(str(x) for x in db.execute(sql, args).fetchone()))
        except Exception:
            parts.append("-")
    # kb_nodes 编辑不改行数时靠内容长度粗判；notes 同理用 updated 时间戳（若无列则忽略）
    try:
        parts.append(str(db.execute("SELECT COALESCE(MAX(created_at),'') FROM notes WHERE user_id=?", (u,)).fetchone()[0]))
    except Exception:
        pass
    return jsonify({"token": hashlib.md5("|".join(parts).encode()).hexdigest()})


# ---------------------------------------------------------------- 时政要文库（重要文件全文 + AI 政策解读）
@app.get("/api/policydocs")
def policydocs_list():
    rows = get_db().execute(
        "SELECT id,title,category,source_url,length(content) chars,"
        "(interpretation IS NOT NULL AND interpretation<>'') has_ai "
        "FROM policy_docs ORDER BY ord, id").fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.get("/api/policydocs/<int:did>")
def policydocs_detail(did):
    r = get_db().execute("SELECT * FROM policy_docs WHERE id=?", (did,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    return jsonify({"id": r["id"], "title": r["title"], "category": r["category"],
                    "source_url": r["source_url"], "content": r["content"] or "",
                    "interpretation": r["interpretation"] or ""})


@app.post("/api/policydocs/<int:did>/ai")
def policydocs_ai(did):
    r = get_db().execute("SELECT * FROM policy_docs WHERE id=?", (did,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    force = (request.get_json(silent=True) or {}).get("force")
    if r["interpretation"] and not force:
        return jsonify({"content": r["interpretation"], "cached": True})
    excerpt = (r["content"] or "")[:9000]
    prompt = (
        "下面是《%s》的全文（可能为节选）。请面向公务员考试考生，用简体中文、Markdown 输出该文件的"
        "「政策解读」，分这几节：\n"
        "## 一、文件地位与背景\n## 二、核心要点/主要内容（分条提炼）\n"
        "## 三、公考高频考点与命题角度\n## 四、可直接引用的金句/关键表述\n"
        "## 五、申论/面试答题如何运用\n"
        "要求：准确、具体、条理清晰，紧扣原文，写完整不要截断。\n\n全文：\n%s"
    ) % (r["title"], excerpt)
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是资深公考时政辅导老师，解读权威文件准确、精炼、实用，用简体中文 Markdown，务必完整不截断。"},
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=6000)
    if err:
        return err
    db = get_db()
    db.execute("UPDATE policy_docs SET interpretation=? WHERE id=?", (reply, did))
    db.commit()
    return jsonify({"content": reply, "cached": False})


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
@app.post("/api/materials/boards")
def mat_boards_set():
    d = request.get_json(silent=True) or {}
    boards = [str(x).strip()[:20] for x in (d.get("boards") or []) if str(x).strip()][:30]
    db = get_db()
    db.execute("UPDATE users SET mat_boards=? WHERE id=?", (json.dumps(boards, ensure_ascii=False), uid()))
    db.commit()
    return jsonify({"ok": True, "boards": boards})


# ---------------------------------------------------------------- 资料库：共享给指定成员
@app.get("/api/materials/<int:mid>/share")
def mat_share_get(mid):
    """能共享给谁：我的队友。顺带返回已经共享给了谁。"""
    db = get_db()
    if not db.execute("SELECT 1 FROM materials WHERE id=? AND user_id=?", (mid, uid())).fetchone():
        return jsonify({"error": "只能共享自己的资料"}), 403
    mates = db.execute(
        "SELECT u.id, u.username FROM team_members m1 "
        "JOIN team_members m2 ON m2.team_id=m1.team_id AND m2.user_id!=m1.user_id "
        "JOIN users u ON u.id=m2.user_id WHERE m1.user_id=?", (uid(),)).fetchall()
    shared = {r["to_user"] for r in db.execute(
        "SELECT to_user FROM material_shares WHERE material_id=?", (mid,))}
    return jsonify({"members": [{"id": r["id"], "username": r["username"],
                                 "shared": r["id"] in shared} for r in mates]})


@app.post("/api/materials/<int:mid>/share")
def mat_share_set(mid):
    """整份覆盖：传 to=[用户id...]，没在里面的就取消共享。"""
    db = get_db()
    if not db.execute("SELECT 1 FROM materials WHERE id=? AND user_id=?", (mid, uid())).fetchone():
        return jsonify({"error": "只能共享自己的资料"}), 403
    to = (request.get_json(silent=True) or {}).get("to") or []
    mates = {r["id"] for r in db.execute(
        "SELECT u.id FROM team_members m1 "
        "JOIN team_members m2 ON m2.team_id=m1.team_id AND m2.user_id!=m1.user_id "
        "JOIN users u ON u.id=m2.user_id WHERE m1.user_id=?", (uid(),))}
    to = [int(x) for x in to if int(x) in mates]        # 只能共享给队友，防越权
    db.execute("DELETE FROM material_shares WHERE material_id=?", (mid,))
    for t in to:
        db.execute("INSERT OR IGNORE INTO material_shares(material_id,owner_id,to_user) VALUES(?,?,?)",
                   (mid, uid(), t))
    db.commit()
    return jsonify({"ok": True, "n": len(to)})


# ---------------------------------------------------------------- 通用「划重点」
# 划重点：**按模块给不同的考点类型**。
# 一套「提法/数据/政策/金句」套到常识、理论、范文、错题上就是驴唇不对马嘴 ——
# 常识要划的是「定义、数字、易混、之最」，错题要划的是「陷阱、正解、知识点」，根本不是一回事。
# key = 前端的视图名（scope）；name=模块叫什么；kinds=[(类型, 什么算这一类)]；focus=这个模块特有的看点。
MK_PROFILES = {
    "newsd": ("每日时政", [
        ("提法", "新表述/新概念，常识判断爱考"),
        ("数据", "具体数字/时间，最容易做成选项"),
        ("政策", "文件名/举措/目标"),
        ("金句", "能直接写进申论的表述"),
    ], "时政题考的是「谁在什么时候提出了什么」，所以新提法、时间数字、文件名优先。"),
    "policydocd": ("时政要文库", [
        ("提法", "首次出现的新表述、新概念"),
        ("目标", "到某年要达成什么（数字目标优先）"),
        ("举措", "具体怎么干的部署"),
        ("金句", "可直接写进申论的权威表述"),
    ], "这是中央文件原文，考点集中在「新提法」和「量化目标」。"),
    "csboard": ("常识积累", [
        ("定义", "概念本身、判断标准（选项就照这个改一个字）"),
        ("数字", "年份、数量、排名、之最"),
        ("易混", "容易和别的搞混的点，成对出现的"),
        ("常考", "真题反复考过的那一句"),
    ], "常识判断是**细节题**：选项往往只改一个字（把「最早」改成「唯一」）。"
       "所以要划的是**能被改动的那个词**，不是整段结论。"),
    "thboard": ("理论基础", [
        ("论断", "经典结论、核心命题（原话）"),
        ("时间", "会议/著作/提出的年份"),
        ("首提", "谁在哪首次提出（最爱考的就是这个）"),
        ("关系", "A 是 B 的什么（基础/前提/核心/根本）—— 位置关系一换就是错项"),
    ], "马原毛概中特习思想，考的是**归属和位置**：哪句话是谁说的、哪个是核心哪个是基础。"
       "「××是××的核心」这类句子必划。"),
    "workd": ("经典著作", [
        ("观点", "作者的核心主张"),
        ("背景", "什么时候、针对什么问题写的"),
        ("金句", "可以直接引用进申论的原话"),
        ("常考", "真题里出现过的段落"),
    ], "经典著作既考常识（哪篇哪年讲了什么），也是申论的引用来源。"),
    "partydict": ("创新理论词典", [
        ("定义", "这个术语到底指什么"),
        ("提法", "完整的官方表述（一个字都不能改）"),
        ("出处", "哪次会议/哪份文件提出的"),
    ], "术语题就考「完整表述」和「出处」，短语要连着划，别割裂。"),
    "essayd": ("范文", [
        ("分论点", "每段的论点句 —— 学的就是这个句式"),
        ("论证", "怎么把素材和论点扣上的那句话"),
        ("素材", "可以搬走复用的事例/数据"),
        ("表达", "亮点句式、衔接、结尾升华"),
    ], "看范文不是看内容，是**看它怎么写的**。要划的是可以搬走复用的「结构件」。"),
    "writed": ("成文", [
        ("分论点", "每段的论点句"),
        ("论证", "素材和论点怎么扣上的"),
        ("素材", "用进去的事例/理论/金句"),
        ("衔接", "段与段之间的过渡表达"),
    ], "这是用你自己的素材写的文章，要看清**素材是怎么被用进去的**。"),
    "wqdetail": ("错题", [
        ("陷阱", "题目在哪里下的套（你就是在这栽的）"),
        ("正解", "正确的思路是什么"),
        ("知识点", "这题背后要记住的那条"),
    ], "错题复盘只有一个目的：**下次别再错**。所以先划陷阱，再划正解。"),
    "slresult": ("批改结果", [
        ("扣分", "被扣分的地方，具体在哪一句"),
        ("亮点", "写得好、下次继续保持的"),
        ("改法", "应该怎么改"),
    ], "批改结果要划的是**可执行的动作**，不是分数。"),
    "sltype": ("题型讲义", [
        ("方法", "答题步骤、固定套路"),
        ("格式", "这个题型的作答格式要求"),
        ("易错", "阅卷最常扣分的地方"),
    ], "讲义要划的是**照着能做题的东西**。"),
    "boardkb": ("基础知识点", [
        ("概念", "定义、判断标准"),
        ("公式", "公式、口诀、速算技巧"),
        ("方法", "解题步骤"),
        ("易错", "最容易踩的坑"),
    ], "基础知识点要划的是**能直接拿去做题的**。"),
    "docqad": ("题目解析", [
        ("考点", "这题考的是什么"),
        ("陷阱", "干扰项是怎么设计的"),
        ("方法", "最快的解法"),
    ], "解析要划的是**方法**，不是答案。"),
    "cdetail": ("古诗文", [
        ("名句", "最常考、可引用的句子"),
        ("典故", "背后的故事/出处"),
        ("考点", "常识判断怎么考它（作者/朝代/体裁/主旨）"),
    ], "古诗文两头考：常识判断考作者朝代，申论要引用名句。"),
    "ckboard": ("常考", [
        ("释义", "到底什么意思"),
        ("易错", "最容易用错的地方（褒贬/对象/程度）"),
        ("辨析", "和近义词的区别"),
    ], "成语实词就考**用得对不对**，所以易错点和辨析最重要。"),
    "viewer": ("资料阅读", [
        ("结论", "可以直接背下来的结论"),
        ("方法", "怎么做的步骤"),
        ("数据", "数字、时间"),
        ("易错", "提醒注意的地方"),
    ], ""),
}
_MK_FALLBACK = ("备考材料", [
    ("提法", "新表述/新概念、关键定义"),
    ("数据", "具体数字/时间"),
    ("结论", "该记住的结论"),
    ("金句", "可以引用的表述"),
], "")


def mk_profile(scope):
    return MK_PROFILES.get(scope, _MK_FALLBACK)


def _mark_text(content, scope=""):
    """让 AI 在给定文字里**逐字挑出**要害句，标出考点类型。
       逐字是硬要求——挑出来的句子要能在原文里原样找到，否则前端标不上去；
       服务端逐条核对，对不上的直接丢弃（宁可少标，不能标错位置）。

       考点类型**按模块走**（见 MK_PROFILES）：常识划「定义/数字/易混」，
       错题划「陷阱/正解」，范文划「分论点/论证/表达」…… 一套模板套所有模块是没用的。"""
    content = (content or "").strip()
    if len(content) < 60:
        return [], "这页文字太少，不用划重点"
    name, kinds, focus = mk_profile(scope)
    names = [k for k, _ in kinds]
    prompt = (
        "下面是「%s」模块里的一段备考材料。考生没时间通读，请**划重点**：\n"
        "挑出 4~8 处最该记的地方，每处**必须从原文里逐字复制**（一字不差，含标点），"
        "否则没法在原文上标出来。\n\n"
        "%s\n"
        "每处给：\n"
        "· quote：从原文逐字复制的句子或短语（10~60 字，别整段抄）\n"
        "· kind：只能填 %s 之一\n%s"
        "· why：为什么要记它（一句话，讲清考点在哪，别复述原文）\n\n"
        '只输出 JSON：{"marks":[{"quote":"","kind":"","why":""}]}\n\n【原文】\n'
        % (name,
           ("【这个模块该看什么】%s\n" % focus) if focus else "",
           " / ".join(names),
           "".join("  · %s = %s\n" % (k, d) for k, d in kinds))
    ) + content[:5000]
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考老师，只从原文里逐字摘句，绝不改写、不编造。严格输出 JSON。"},
         {"role": "user", "content": prompt}], temperature=0.3, max_tokens=2000, timeout=180, json_mode=True)
    if err:
        return None, err
    try:
        got = json.loads(rep).get("marks") or []
    except Exception:
        return None, "AI 返回格式异常，请重试"
    marks, seen = [], set()
    for m in got:
        q = (m.get("quote") or "").strip()
        if not q or q in seen or q not in content:      # 对不上原文的直接丢
            continue
        seen.add(q)
        marks.append({"quote": q,
                      "kind": m.get("kind") if m.get("kind") in names else names[0],
                      "why": (m.get("why") or "").strip()[:120]})
    return marks, ("" if marks else "AI 挑出的句子和原文对不上，请重试")


@app.get("/api/marks/profile")
def marks_profile():
    """前端要知道当前模块划哪几类（好渲染颜色和说明），别在两边各写一份。"""
    name, kinds, focus = mk_profile((request.args.get("scope") or "")[:30])
    return jsonify({"name": name, "focus": focus,
                    "kinds": [{"k": k, "d": d} for k, d in kinds]})


@app.post("/api/marks")
def marks_any():
    """通用划重点：任何模块的正文都能划。按内容哈希缓存，同一段内容全局只算一次。"""
    d = request.get_json(silent=True) or {}
    text = (d.get("text") or "").strip()
    scope = (d.get("scope") or "")[:30]
    if not text:
        return jsonify({"error": "没有可划的正文"}), 400
    # 缓存 key 要带 scope：同一段文字在不同模块划法不一样（常识划定义、错题划陷阱），
    # 只按文字哈希会串味
    ref = hashlib.md5((scope + "\x00" + text).encode("utf-8")).hexdigest()
    db = get_db()
    if not d.get("force"):
        r = db.execute("SELECT data_json FROM marks_cache WHERE ref=?", (ref,)).fetchone()
        if r:
            return jsonify({"marks": json.loads(r["data_json"]), "cached": True})
    marks, err = _mark_text(text, scope)
    if marks is None:
        return err if isinstance(err, tuple) else (jsonify({"error": err}), 502)
    if not marks:
        return jsonify({"error": err or "没能划出重点"}), 502
    db.execute("INSERT OR REPLACE INTO marks_cache(ref,scope,data_json) VALUES(?,?,?)",
               (ref, scope, json.dumps(marks, ensure_ascii=False)))
    db.commit()
    return jsonify({"marks": marks})


# ---------------------------------------------------------------- 书签（看到哪了）
@app.get("/api/bookmarks")
def bm_list():
    rows = get_db().execute(
        "SELECT * FROM bookmarks WHERE user_id=? ORDER BY updated_at DESC LIMIT 100", (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.post("/api/bookmarks")
def bm_save():
    """一个 (kind, ref) 只留一条：自动记「看到哪了」，手动打点则把 note 填上。"""
    d = request.get_json(silent=True) or {}
    kind = (d.get("kind") or "").strip()[:20]
    ref = str(d.get("ref") or "").strip()[:60]
    if not kind or not ref:
        return jsonify({"error": "缺少参数"}), 400
    db = get_db()
    db.execute(
        "INSERT INTO bookmarks(user_id,kind,ref,title,pos,note,updated_at) "
        "VALUES(?,?,?,?,?,?,datetime('now','localtime')) "
        "ON CONFLICT(user_id,kind,ref) DO UPDATE SET title=excluded.title, pos=excluded.pos, "
        "note=COALESCE(NULLIF(excluded.note,''), bookmarks.note), updated_at=datetime('now','localtime')",
        (uid(), kind, ref, (d.get("title") or "")[:120], float(d.get("pos") or 0), (d.get("note") or "")[:120]))
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/bookmarks/<int:bid>")
def bm_del(bid):
    db = get_db()
    db.execute("DELETE FROM bookmarks WHERE id=? AND user_id=?", (bid, uid()))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 外观：头像 / 壁纸
SKIN_DIR = os.path.join(UPLOADS, "skin")
SKIN_KINDS = {                     # 各自的最大边长与用途
    "avatar": 320,                 # 左上角头像
    "wall_app": 2000,              # 应用内壁纸（首页背景）
    "wall_login": 2000,            # 登录/加载页壁纸
}


def _skin_urls(row):
    """把库里存的文件名变成可访问的 URL；没设置就返回空。"""
    out = {}
    for k in SKIN_KINDS:
        fn = (row[k] if row and k in row.keys() else None) or ""
        out[k] = ("/skin/%d/%s" % (row["id"], fn)) if fn else ""
    return out


@app.get("/api/skin")
def skin_get():
    r = get_db().execute("SELECT id, avatar, wall_app, wall_login FROM users WHERE id=?", (uid(),)).fetchone()
    return jsonify(_skin_urls(r))


@app.post("/api/skin/<kind>")
def skin_set(kind):
    """上传头像 / 壁纸：统一压成 JPEG（头像保正方形），文件名随机，旧图删掉。"""
    if kind not in SKIN_KINDS:
        return jsonify({"error": "不支持的类型"}), 400
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择图片"}), 400
    try:
        from PIL import Image, ImageOps
        im = Image.open(f.stream)
        im = ImageOps.exif_transpose(im)           # 手机拍的照片会带旋转信息
        im = im.convert("RGB")
        side = SKIN_KINDS[kind]
        if kind == "avatar":
            im = ImageOps.fit(im, (side, side), Image.LANCZOS)   # 居中裁成正方形
        else:
            im.thumbnail((side, side), Image.LANCZOS)
    except Exception:
        return jsonify({"error": "这不是有效的图片"}), 400

    d = os.path.join(SKIN_DIR, str(uid()))
    os.makedirs(d, exist_ok=True)
    db = get_db()
    old = (db.execute("SELECT %s FROM users WHERE id=?" % kind, (uid(),)).fetchone() or [None])[0]
    fn = "%s-%s.jpg" % (kind, secrets.token_urlsafe(10))         # 文件名不可猜 → 登录页可公开读
    im.save(os.path.join(d, fn), "JPEG", quality=84, optimize=True)
    if old:
        try:
            os.remove(os.path.join(d, old))
        except Exception:
            pass
    db.execute("UPDATE users SET %s=? WHERE id=?" % kind, (fn, uid()))
    db.commit()
    return jsonify({"url": "/skin/%d/%s" % (uid(), fn), "kind": kind})


@app.delete("/api/skin/<kind>")
def skin_del(kind):
    if kind not in SKIN_KINDS:
        return jsonify({"error": "不支持的类型"}), 400
    db = get_db()
    old = (db.execute("SELECT %s FROM users WHERE id=?" % kind, (uid(),)).fetchone() or [None])[0]
    if old:
        try:
            os.remove(os.path.join(SKIN_DIR, str(uid()), old))
        except Exception:
            pass
    db.execute("UPDATE users SET %s=NULL WHERE id=?" % kind, (uid(),))
    db.commit()
    return jsonify({"ok": True})


@app.get("/skin/<int:sid>/<path:fname>")
def skin_file(sid, fname):
    """公开可读（文件名随机不可猜）——登录页在没登录时也要显示壁纸。"""
    if "/" in fname or ".." in fname:
        return "", 404
    p = os.path.join(SKIN_DIR, str(sid))
    if not os.path.exists(os.path.join(p, fname)):
        return "", 404
    return send_from_directory(p, fname, max_age=2592000)


# ---------------------------------------------------------------- 草稿本（错题本里，平时打草稿）
@app.get("/api/drafts")
def drafts_list():
    """列表只带缩略图，不带笔迹，省流量。"""
    rows = get_db().execute(
        "SELECT id, title, pages, thumb, updated_at FROM drafts WHERE user_id=? ORDER BY updated_at DESC",
        (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.post("/api/drafts")
def draft_new():
    d = request.get_json(silent=True) or {}
    title = (d.get("title") or "").strip() or datetime.now().strftime("草稿 %m-%d %H:%M")
    db = get_db()
    cur = db.execute("INSERT INTO drafts(user_id, title, data_json, pages) VALUES(?,?,?,1)",
                     (uid(), title, json.dumps({"bg": 1, "pages": [{"st": []}]})))
    db.commit()
    return jsonify({"id": cur.lastrowid, "title": title})


@app.get("/api/drafts/<int:did>")
def draft_get(did):
    r = get_db().execute("SELECT id, title, data_json, pages, updated_at FROM drafts WHERE id=? AND user_id=?",
                         (did, uid())).fetchone()
    if not r:
        return jsonify({"error": "草稿不存在"}), 404
    return jsonify({"id": r["id"], "title": r["title"], "updated_at": r["updated_at"],
                    "data": json.loads(r["data_json"] or "{}")})


@app.post("/api/drafts/<int:did>")
def draft_save(did):
    """保存笔迹（整本覆盖写）。title 单独传就是重命名。"""
    db = get_db()
    r = db.execute("SELECT id FROM drafts WHERE id=? AND user_id=?", (did, uid())).fetchone()
    if not r:
        return jsonify({"error": "草稿不存在"}), 404
    d = request.get_json(silent=True) or {}
    sets, args = [], []
    if d.get("title") is not None:
        sets.append("title=?"); args.append((d["title"] or "").strip() or "未命名草稿")
    if d.get("data") is not None:
        sets.append("data_json=?"); args.append(json.dumps(d["data"], ensure_ascii=False))
        sets.append("pages=?"); args.append(int(d.get("pages") or 1))
    if d.get("thumb") is not None:
        sets.append("thumb=?"); args.append(d["thumb"][:400000])   # 缩略图别无限大
    if not sets:
        return jsonify({"ok": True})
    sets.append("updated_at=datetime('now','localtime')")
    args += [did, uid()]
    db.execute("UPDATE drafts SET %s WHERE id=? AND user_id=?" % ",".join(sets), args)
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/drafts/<int:did>")
def draft_del(did):
    db = get_db()
    db.execute("DELETE FROM drafts WHERE id=? AND user_id=?", (did, uid()))
    db.commit()
    return jsonify({"ok": True})


def _deb_meta():
    """从 dist/deb.json 读桌面版发布信息（build_deb.sh 生成）。"""
    p = os.path.join(BASE, "dist", "deb.json")
    try:
        with open(p, encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return {}


def _sw_version():
    """读 static/sw.js 里的前端缓存版本号（gongkao-vNN），用于判断网页端有没有更新。"""
    try:
        with open(os.path.join(STATIC, "sw.js"), encoding="utf-8") as fp:
            m = re.search(r"gongkao-v(\d+)", fp.read())
            return "gongkao-v" + m.group(1) if m else ""
    except Exception:
        return ""


@app.get("/api/desktop/version")
def desktop_version():
    """桌面版启动/手动检查更新时来问：前端有没有更新(刷新即可)、桌面壳有没有新版(需重下)。"""
    deb = os.path.join(BASE, "dist", "gongkao.deb")
    meta = _deb_meta()
    return jsonify({
        "sw": _sw_version(),                                  # 当前网页端版本；和启动时不同 → 刷新即更新
        "deb_code": int(meta.get("version_code") or 0),       # 桌面壳版本；比本机新 → 需重新下载 .deb
        "deb_name": meta.get("version_name") or "",
        "deb_notes": meta.get("notes") or "",
        "deb_size": os.path.getsize(deb) if os.path.exists(deb) else 0,
        "deb_url": "/download/gongkao.deb",
        "deb_available": os.path.exists(deb),
    })


@app.get("/apk")
@app.get("/download/gongkao.apk")
def download_apk():
    apk = os.path.join(BASE, "dist", "gongkao.apk")
    if not os.path.exists(apk):
        return "APK 尚未构建", 404
    return send_file(apk, mimetype="application/vnd.android.package-archive",
                     as_attachment=True, download_name="gongkao.apk")


@app.get("/deb")
@app.get("/download/gongkao.deb")
def download_deb():
    """电脑桌面版（Linux .deb）。"""
    deb = os.path.join(BASE, "dist", "gongkao.deb")
    if not os.path.exists(deb):
        return "桌面版尚未构建", 404
    return send_file(deb, mimetype="application/vnd.debian.binary-package",
                     as_attachment=True, download_name="gongkao.deb")


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


@app.post("/api/lookup/ai")
def api_lookup_ai():
    """词典未收录时用 AI 解释，写入全局 ci_ai 缓存（此后 lookup 可直接命中）。"""
    data = request.get_json(silent=True) or {}
    word = (data.get("word") or "").strip()
    if not word:
        return jsonify({"error": "请输入词语"}), 400
    db = get_db()
    cached = db.execute("SELECT * FROM ci_ai WHERE word=?", (word,)).fetchone()
    if cached and not data.get("force"):
        ck = cached.keys()
        return jsonify({"word": word, "pinyin": cached["pinyin"], "category": cached["category"],
                        "explanation": cached["explanation"] or "",
                        "derivation": (cached["derivation"] if "derivation" in ck else "") or "",
                        "example": (cached["example"] if "example" in ck else "") or "",
                        "found": True, "cached": True})
    cat = (data.get("category") or "").strip()
    if cat not in ("成语", "词语", "词组"):
        cat = "词组" if (len(word) >= 4 and CJK_RE.match(word)) else "词语"
    prompt = (
        "请解释%s「%s」，面向公务员考试考生，用简体中文，只输出 JSON（不要多余文字），字段：\n"
        '{"explanation":"准确通顺的释义，一到三句，可含近义辨析",'
        '"derivation":"出处/典故；没有则留空字符串",'
        '"example":"一个规范例句；没有则留空字符串"}') % (cat, word)
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是权威的汉语词典与公考词汇助手，释义准确、简洁，严格输出 JSON，用简体中文。"},
         {"role": "user", "content": prompt}], temperature=0.3, max_tokens=700, json_mode=True)
    if err:
        return err
    try:
        obj = json.loads(reply)
    except Exception:
        obj = {"explanation": reply, "derivation": "", "example": ""}
    exp = (obj.get("explanation") or "").strip()
    der = (obj.get("derivation") or "").strip()
    exa = (obj.get("example") or "").strip()
    py = to_pinyin(word)
    db.execute("INSERT OR REPLACE INTO ci_ai(word,pinyin,category,explanation,derivation,example) VALUES(?,?,?,?,?,?)",
               (word, py, cat, exp, der, exa))
    # 重新生成(force)时，同步刷新该用户已收录的同名词条（保留其笔记），
    # 让「重新生成」对已收录条目真正生效，覆盖历史未规范化的旧解释。
    if data.get("force"):
        db.execute("UPDATE entries SET pinyin=?, category=?, explanation=?, derivation=?, example=? "
                   "WHERE user_id=? AND word=?", (py, cat, exp, der, exa, uid(), word))
    db.commit()
    return jsonify({"word": word, "pinyin": py, "category": cat, "explanation": exp,
                    "derivation": der, "example": exa, "found": True, "cached": False})


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
    if category in ("成语", "词语", "词组"):
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
    """从「成语词语积累」删词 → **同步取消常考那边的 ★**。
       两边是同一份收藏，只删一边等于没删（下次打开常考还是实心星，再点一下又加回来）。"""
    db = get_db()
    r = db.execute("SELECT word FROM entries WHERE id=? AND user_id=?", (eid, uid())).fetchone()
    db.execute("DELETE FROM entries WHERE id=? AND user_id=?", (eid, uid()))
    unstarred = 0
    if r:
        cur = db.execute(
            "DELETE FROM ck_stars WHERE user_id=? AND board IN ('成语','实词') AND title=?",
            (uid(), r["word"]))
        unstarred = cur.rowcount or 0
    db.commit()
    return jsonify({"ok": True, "unstarred": unstarred})


@app.post("/api/entries/sync")
def entries_sync():
    """对账：把两边补齐（谁有谁没有都补上），并报告补了多少。
       历史数据是两边各存各的，直接开双向同步会「有的对得上、有的对不上」，所以给个对账入口。"""
    db = get_db()
    ents = {r["word"] for r in db.execute(
        "SELECT word FROM entries WHERE user_id=? AND category IN ('成语','词语')", (uid(),))}
    stars = {r["title"]: r for r in db.execute(
        "SELECT * FROM ck_stars WHERE user_id=? AND board IN ('成语','实词')", (uid(),))}
    add_star, add_entry = 0, 0
    # entries 里有、常考没标星 → 去常考里找到这个词，补上星
    for w in ents - set(stars):
        row = db.execute("SELECT id, board, title, content, note FROM changkao_items "
                         "WHERE board IN ('成语','实词') AND title=?", (w,)).fetchone()
        if row:
            db.execute("INSERT OR REPLACE INTO ck_stars(user_id,board,item_id,title,content,note) "
                       "VALUES(?,?,?,?,?,?)",
                       (uid(), row["board"], row["id"], row["title"], row["content"], row["note"]))
            add_star += 1
    # 常考标了星、entries 里没有 → 补进成语词语积累
    for w, r in stars.items():
        if w in ents:
            continue
        cat = CK_TO_ENTRY.get(r["board"])
        if not cat:
            continue
        info = lookup(w) or {}
        db.execute(
            "INSERT INTO entries(user_id,word,pinyin,category,explanation,derivation,example,note,source) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (uid(), w, info.get("pinyin") or "", cat,
             info.get("explanation") or r["content"] or "", info.get("derivation") or "",
             info.get("example") or "", r["note"] or "", "常考收藏"))
        add_entry += 1
    db.commit()
    return jsonify({"add_star": add_star, "add_entry": add_entry})


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
