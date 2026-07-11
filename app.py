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
import os
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
    # ci_ai 结构化：补 出处/例句 列
    for col in ("derivation", "example"):
        if col not in _cols(con, "ci_ai"):
            con.execute("ALTER TABLE ci_ai ADD COLUMN %s TEXT" % col)
    # 习语金句：补 关键词/申论运用 列
    for col in ("keyword", "apply"):
        if col not in _cols(con, "xiyu_items"):
            con.execute("ALTER TABLE xiyu_items ADD COLUMN %s TEXT" % col)
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


def is_admin():
    return session.get("role") == "admin"


# ---------------------------------------------------------------- 访问控制
_PUBLIC_EXACT = {"/register", "/api/register", "/login", "/api/login",
                 "/forgot", "/api/forgot/question", "/api/forgot/reset",
                 "/api/sec_questions", "/api/captcha",
                 "/apk", "/download/gongkao.apk", "/api/app/version",
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


@app.post("/api/register")
def api_register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    pw = data.get("password") or ""
    sec_q = (data.get("sec_question") or "").strip()
    sec_a = (data.get("sec_answer") or "").strip()
    email = (data.get("email") or "").strip()
    if not _captcha_ok(data.get("captcha_id"), data.get("captcha")):
        return jsonify({"error": "验证码错误或已过期", "captcha": True}), 400
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
    rows = get_db().execute(
        "SELECT DISTINCT board FROM materials WHERE user_id=? AND board<>'' ORDER BY board", (uid(),)).fetchall()
    return jsonify({"boards": [r["board"] for r in rows]})


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
    t = _extract_text(os.path.join(UPLOADS, str(uid()), m["stored_name"]), m["ext"])
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
    path = os.path.join(UPLOADS, str(uid()), m["stored_name"])
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
    path = os.path.join(UPLOADS, str(uid()), m["stored_name"])
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
    path = os.path.join(UPLOADS, str(uid()), m["stored_name"])
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
    return jsonify({"id": r["id"], "title": r["title"], "url": r["url"], "source": r["source"],
                    "pub_date": r["pub_date"], "content": r["content"] or "",
                    "ai_summary": r["ai_summary"] or ""})


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
def _todo_members(db):
    """互监成员：未设置时自动选出最活跃的两个账号。"""
    rows = db.execute("SELECT m.user_id, u.username FROM todo_members m "
                      "JOIN users u ON u.id=m.user_id ORDER BY m.user_id").fetchall()
    if not rows:
        pick = db.execute("""
            SELECT u.id, u.username,
                   (SELECT COUNT(*) FROM entries e WHERE e.user_id=u.id)
                 + (SELECT COUNT(*) FROM wrong_questions w WHERE w.user_id=u.id)
                 + (SELECT COUNT(*) FROM task_templates t WHERE t.user_id=u.id)
                 + (SELECT COUNT(*) FROM ai_chats c WHERE c.user_id=u.id) act
            FROM users u ORDER BY act DESC, u.id LIMIT 2""").fetchall()
        for p in pick:
            db.execute("INSERT OR IGNORE INTO todo_members(user_id) VALUES(?)", (p["id"],))
        db.commit()
        rows = db.execute("SELECT m.user_id, u.username FROM todo_members m "
                          "JOIN users u ON u.id=m.user_id ORDER BY m.user_id").fetchall()
    return [{"id": r["user_id"], "name": r["username"]} for r in rows]


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
    members = _todo_members(db)
    rows = db.execute("SELECT * FROM shared_todos ORDER BY done, id DESC LIMIT 200").fetchall()
    marks, by = {}, {}
    for r in db.execute("SELECT todo_id, user_id, by_name FROM shared_todo_done"):
        marks.setdefault(r["todo_id"], []).append(r["user_id"])
        by.setdefault(r["todo_id"], {})[str(r["user_id"])] = r["by_name"] or ""
    items = []
    for r in rows:
        d = dict(r)
        d["done_ids"] = marks.get(r["id"], [])
        d["done_by_map"] = by.get(r["id"], {})   # {被确认人id: 确认人}
        items.append(d)
    return jsonify({"items": items, "members": members,
                    "me": current_user()["username"], "me_id": uid()})


@app.post("/api/shared_todos")
def shared_todos_add():
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return jsonify({"error": "请输入内容"}), 400
    db = get_db()
    cur = db.execute("INSERT INTO shared_todos(text,created_by) VALUES(?,?)",
                     (text[:200], current_user()["username"]))
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
        return jsonify({"error": "你不是互监成员，去「👥 成员」里把自己加进来"}), 403
    if len(mids) < 2:
        return jsonify({"error": "互监需要至少两个成员，去「👥 成员」里加上搭档"}), 400
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


@app.get("/api/todo_members")
def todo_members_get():
    db = get_db()
    members = _todo_members(db)
    users = [{"id": r["id"], "name": r["username"]}
             for r in db.execute("SELECT id, username FROM users ORDER BY id")]
    return jsonify({"members": members, "users": users})


@app.post("/api/todo_members")
def todo_members_set():
    ids = (request.get_json(silent=True) or {}).get("user_ids") or []
    ids = [int(i) for i in ids][:6]
    if not ids:
        return jsonify({"error": "至少选一个成员"}), 400
    db = get_db()
    db.execute("DELETE FROM todo_members")
    for i in ids:
        db.execute("INSERT OR IGNORE INTO todo_members(user_id) VALUES(?)", (i,))
    # 成员变了，重算每条待办的整体完成状态
    for r in db.execute("SELECT id FROM shared_todos").fetchall():
        _sync_todo_done(db, r[0], ids)
    db.commit()
    return jsonify({"members": _todo_members(db)})


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
              "wrongq", "idiom", "changkao", "shenlun", "classics", "theory", ""]


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
    })


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


PLAN_SYS = ("你是公考备考规划师。只根据给出的「学情快照」排计划，不编造学生没有的数据；"
            "任务要具体到可执行（写清做什么、做多少），总时长贴近可用时间。严格输出 JSON。")


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

    prompt = (
        "【备考信息】\n考试：%s\n距考试：%s\n今天可学习：%d 分钟\n薄弱环节：%s\n备注：%s\n阶段：%s\n\n"
        "【学情快照·今天】\n"
        "· 遗忘曲线到期需复习：%d 条（词语句子 %d / 每日积累 %d / 错题 %d）\n"
        "· 错题分布：%s\n"
        "· 题库里还没做过的套卷：%d 套\n"
        "· 今天新增内容：常识 %d 条、时政 %d 条、议论文素材 %d 条、概括句 %d 条\n"
        "· 已收录成语词语：%d 条；申论批改记录：%d 次\n"
        "· 用户已有的每日固定打卡：%s\n\n"
        "请为今天排一份学习计划：\n"
        "· 4~6 条任务，总时长控制在 %d 分钟上下（可 ±10%%）；\n"
        "· 到期复习和错题优先安排，其次补薄弱环节，再安排当天新增内容的积累；\n"
        "· 不要和「已有的每日固定打卡」重复；\n"
        "· 每条写清楚做什么、做多少（如「做 15 道图形推理并订正」）；\n"
        "· reason 一句话说明为什么现在做这件事（引用上面的数字）；\n"
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
           minutes, "/".join(x for x in PLAN_LINKS if x)))

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": PLAN_SYS}, {"role": "user", "content": prompt}],
        temperature=0.4, max_tokens=2000, timeout=180, json_mode=True)
    if err:
        return err
    try:
        d = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502

    items = [x for x in (d.get("items") or []) if (x.get("title") or "").strip()][:8]
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
    db.commit()
    return jsonify({"done": on})


@app.delete("/api/plan/<int:pid>")
def plan_del(pid):
    db = get_db()
    db.execute("DELETE FROM plan_items WHERE id=? AND user_id=?", (pid, uid()))
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
    db.commit()
    return jsonify({"ok": True})


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
RV_GROUP = {"entry": "word", "classic": "word", "sucai": "daily", "wrongq": "wrongq"}


@app.get("/api/review/today")
def review_today():
    today = datetime.now().strftime("%Y-%m-%d")
    due = _review_due(get_db(), uid(), today)
    order = {"entry": 0, "classic": 1, "sucai": 2, "wrongq": 3}
    due.sort(key=lambda x: (order.get(x["kind"], 9), x["id"]))
    groups = {"word": 0, "daily": 0, "wrongq": 0}
    for it in due:
        it["group"] = RV_GROUP.get(it["kind"], "wrongq")
        groups[it["group"]] += 1
    return jsonify({"today": today, "count": len(due), "items": due, "groups": groups})


@app.post("/api/review/done")
def review_done():
    data = request.get_json(silent=True) or {}
    kind, rid = (data.get("kind") or "").strip(), int(data.get("id") or 0)
    result = (data.get("result") or "know").strip()  # know认识 / fuzzy模糊 / forget忘记
    if kind not in ("entry", "wrongq", "classic", "sucai") or not rid:
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
