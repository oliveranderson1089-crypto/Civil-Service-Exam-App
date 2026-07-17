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

from core import (BASE, CFG, CJK_RE, CONFIG, DB, STATIC, UPLOADS, _cols,
                  bg_new, bg_set, close_db, current_user, get_db, log, lookup,
                  row_to_dict, to_pinyin, uid, uname)
from mods.admin import bp as admin_bp
from mods.aichat import _user_stats
from mods.aichat import bp as aichat_bp
from mods.essays import bp as essays_bp
from mods.hyper import bp as hyper_bp
from mods.policydocs import bp as policydocs_bp
from mods.quiz import bp as quiz_bp
from mods.skin import bp as skin_bp
from mods.tasks import bp as tasks_bp
from mods.theory import bp as theory_bp
from mods.xiyu import bp as xiyu_bp
from mods.ai import (_ai_call_or_error, _ai_conf, vision_chat,
                     vision_configured, vision_ocr)
from mods.changkao import CK_TO_ENTRY
from mods.files import (IMAGE_EXT, INLINE_EXT, OFFICE_EXT, TEXT_EXT,
                        _extract_text, _ocr_image, _ocr_image_page,
                        _office_to_pdf, _remove_file, _strip_artifacts,
                        _user_dir)
from mods.dist import bp as dist_bp
from mods.drafts import bp as drafts_bp
from mods.find import bp as find_bp
from mods.marks import bp as marks_bp
from mods.notes import _get_note, _jl, _note_dict
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
from mods.annots import _ann_sentence, _ann_where
from mods.annots import bp as annots_bp

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 单文件最大 64MB
app.teardown_appcontext(close_db)
app.register_blueprint(annots_bp)
app.register_blueprint(admin_bp)
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


# ---------------------------------------------------------------- AI 工具调用（让 AI 真能操作应用）
# 原来 AI 只会「嘴上说」帮你做了（比如说「已把成语加入收录」其实没写库）。
# 给它 function calling：服务端能直接做的（加收录…）就执行；只能前端做的（跳到某功能）
# 记成一个 action 交回前端执行。这样 AI 说「已加入」就是真的加了。
def _ai_raw(messages, tools=None, temperature=0.4, max_tokens=1600, timeout=120):
    """底层调用，返回完整 message 对象（可能含 tool_calls）。"""
    conf = _ai_conf()
    if not conf["key"]:
        raise RuntimeError("AI 未配置，请管理员在「后台 → AI 设置」填写 API Key")
    b = conf["base"]
    url = b if b.endswith("/chat/completions") else (
        b + "/chat/completions" if b.endswith("/v1") else b + "/v1/chat/completions")
    payload = {"model": conf["model"], "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens, "stream": False}
    if tools:
        payload["tools"] = tools
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + conf["key"]})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d["choices"][0]["message"]


# 应用里能让 AI 帮你打开的功能（名字 → 前端的 openXxx 函数）
AI_FEATURES = {
    "成语词语积累": "openIdiom", "每日时政": "openNews", "每日新闻视频": "openVideos",
    "人民时评范文": "openFanwen", "今日复习": "openReview", "常识积累": "openChangshi",
    "错题本": "openWrongq", "小记": "openNotes", "资料库": "openMaterials",
    "古诗文名句": "openClassics", "时政要文库": "openPolicyDocs", "任务清单": "openTasks",
    "党的创新理论学习词典": "openPartyDict", "常考": "openChangkao",
}

AI_TOOLS = [
    {"type": "function", "function": {
        "name": "add_word",
        "description": "把一个成语/词语/词组加入用户的「成语词语积累」收录。当用户说「收录/加入/记下这个词」时调用。",
        "parameters": {"type": "object", "properties": {
            "word": {"type": "string", "description": "要收录的成语或词语本身，如「佶屈聱牙」"},
            "note": {"type": "string", "description": "可选备注"}},
            "required": ["word"]}}},
    {"type": "function", "function": {
        "name": "open_feature",
        "description": "帮用户打开应用里的某个功能页面，省得他自己在菜单里找。当用户说「打开/去/进入某功能」时调用。",
        "parameters": {"type": "object", "properties": {
            "feature": {"type": "string", "enum": list(AI_FEATURES.keys()),
                        "description": "功能名"}},
            "required": ["feature"]}}},
    {"type": "function", "function": {
        "name": "create_note",
        "description": "帮用户在「小记」里记一条笔记。当用户说「帮我记下/记一条/存到小记」时调用。",
        "parameters": {"type": "object", "properties": {
            "content": {"type": "string", "description": "要记的内容"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "可选标签"}},
            "required": ["content"]}}},
    {"type": "function", "function": {
        "name": "add_wrong_question",
        "description": ("把一道**完整的**题目加入用户的「错题本」。当用户发来的（或截图 OCR 出来的）内容"
                        "确实是一道完整题目——有题干、通常还有选项——时调用。只有能确定是完整题目才调用；"
                        "若拿不准这是不是题目、或题目残缺不全，**不要调用**，而是用文字反问用户确认。"),
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "完整题干（含选项 A/B/C/D，若有）。尽量保留原文。"},
            "answer": {"type": "string", "description": "正确答案（如 C；不确定就留空）"},
            "board": {"type": "string", "description": "所属板块，如「行测·资料分析」「行测·言语理解」「常识判断」，判断不了就留空"},
            "qtype": {"type": "string", "description": "题型，如「资料分析-增长率」「逻辑填空」，判断不了就留空"},
            "analysis": {"type": "string", "description": "解题方法/思路/易错点（可选，简要写）"}},
            "required": ["question"]}}},
]


def _gen_ai_explanation(db, word, cat=""):
    """词典查不到时，用 AI 生成释义并写进全局 ci_ai 缓存（此后 lookup 直接命中）。
    返回 dict(explanation/derivation/example/category/pinyin)；失败时释义为空串。"""
    cat = (cat or "").strip()
    if cat not in ("成语", "词语", "词组"):
        cat = "词组" if (len(word) >= 4 and CJK_RE.match(word)) else "词语"
    py = to_pinyin(word)
    out = {"explanation": "", "derivation": "", "example": "", "category": cat, "pinyin": py}
    prompt = (
        "请解释%s「%s」，面向公务员考试考生，用简体中文，只输出 JSON（不要多余文字），字段：\n"
        '{"explanation":"准确通顺的释义，一到三句，可含近义辨析",'
        '"derivation":"出处/典故；没有则留空字符串",'
        '"example":"一个规范例句；没有则留空字符串"}') % (cat, word)
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是权威的汉语词典与公考词汇助手，释义准确、简洁，严格输出 JSON，用简体中文。"},
         {"role": "user", "content": prompt}], temperature=0.3, max_tokens=700, json_mode=True)
    if err:
        return out
    try:
        obj = json.loads(reply)
    except Exception:
        obj = {"explanation": reply, "derivation": "", "example": ""}
    out["explanation"] = (obj.get("explanation") or "").strip()
    out["derivation"] = (obj.get("derivation") or "").strip()
    out["example"] = (obj.get("example") or "").strip()
    if out["explanation"]:
        db.execute("INSERT OR REPLACE INTO ci_ai(word,pinyin,category,explanation,derivation,example) "
                   "VALUES(?,?,?,?,?,?)",
                   (word, py, cat, out["explanation"], out["derivation"], out["example"]))
        db.commit()
    return out


def _ai_add_entry(db, word, note):
    info = lookup(word)
    # AI 收录时若词典查不到释义，先让 AI 生成释义再入库（用户要求：没释义的不能裸收录）
    if not (info.get("explanation") or "").strip():
        gen = _gen_ai_explanation(db, word, info.get("category") or "")
        if gen["explanation"]:
            info["explanation"] = gen["explanation"]
            info["derivation"] = gen["derivation"]
            info["example"] = gen["example"]
            info["category"] = gen["category"]
            info["pinyin"] = info["pinyin"] or gen["pinyin"]
            info["source"] = "ai"
    db.execute(
        "INSERT INTO entries(user_id,word,pinyin,category,explanation,derivation,example,note,source) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (uid(), word, info["pinyin"], info["category"], info["explanation"],
         info["derivation"], info["example"], note, info["source"]))
    db.commit()
    return bool((info.get("explanation") or "").strip())


def _ai_exec_tool(name, args, db):
    """执行一个工具。返回 (给模型看的结果文本, 给前端的 action 或 None)。"""
    if name == "add_word":
        word = (args.get("word") or "").strip()
        if not word:
            return "没有指定要收录的词。", None
        has_exp = _ai_add_entry(db, word, (args.get("note") or "").strip())
        n = db.execute("SELECT COUNT(*) FROM entries WHERE user_id=?", (uid(),)).fetchone()[0]
        tail = "（已附上释义）" if has_exp else "（暂未查到释义，先收录）"
        return ("已把「%s」加入成语词语积累%s，在 行测→言语理解与表达→成语词语积累 里能看到，当前共 %d 条。"
                % (word, tail, n)), {"type": "refresh", "what": "entries"}
    if name == "open_feature":
        f = (args.get("feature") or "").strip()
        fn = AI_FEATURES.get(f)
        if not fn:
            return "没有这个功能：" + f, None
        return "已为用户打开「%s」。" % f, {"type": "navigate", "fn": fn, "label": f}
    if name == "create_note":
        content = (args.get("content") or "").strip()
        if not content:
            return "没有要记的内容。", None
        tags = [str(t)[:20] for t in (args.get("tags") or [])][:6]
        db.execute(
            "INSERT INTO notes(user_id,board,content,images,attachments,todos,tags) "
            "VALUES(?,?,?,?,?,?,?)",
            (uid(), "", content, "[]", "[]", "[]", json.dumps(tags, ensure_ascii=False)))
        db.commit()
        return "已记进小记。", {"type": "refresh", "what": "notes"}
    if name == "add_wrong_question":
        q = (args.get("question") or "").strip()
        if not q:
            return "没拿到题目内容。", None
        db.execute(
            "INSERT INTO wrong_questions(user_id,board,question,image,answer,qtype,points,method,skill,steps) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (uid(), (args.get("board") or "").strip(), q, "", (args.get("answer") or "").strip(),
             (args.get("qtype") or "").strip(), "", (args.get("analysis") or "").strip(), "", ""))
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM wrong_questions WHERE user_id=?", (uid(),)).fetchone()[0]
        return ("已把这道题加入错题本（当前共 %d 道），在「错题本」里能看到并继续补充答案/解析。" % n,
                {"type": "refresh", "what": "wrongq"})
    return "未知工具：" + str(name), None


def ai_chat_agentic(messages, db, max_rounds=4, temperature=0.5, max_tokens=2000):
    """带工具调用的对话循环。返回 (最终回复文本, [前端要执行的 action])。"""
    msgs = list(messages)
    actions = []
    for _ in range(max_rounds):
        m = _ai_raw(msgs, tools=AI_TOOLS, temperature=temperature, max_tokens=max_tokens)
        tcs = m.get("tool_calls")
        if not tcs:
            return (m.get("content") or "").strip(), actions
        msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
        for tc in tcs:
            fn = tc.get("function") or {}
            try:
                a = json.loads(fn.get("arguments") or "{}")
            except Exception:
                a = {}
            result, action = _ai_exec_tool(fn.get("name"), a, db)
            if action:
                actions.append(action)
            msgs.append({"role": "tool", "tool_call_id": tc.get("id"), "content": result})
    # 轮数用完还在调工具：再要一次纯文本收尾
    m = _ai_raw(msgs, temperature=temperature, max_tokens=max_tokens)
    return (m.get("content") or "").strip(), actions


def _ai_agentic_or_error(messages, db, **kw):
    """带工具的对话 + 统一错误封装。返回 (reply, actions, None) 或 (None, None, (json,code))。"""
    try:
        reply, actions = ai_chat_agentic(messages, db, **kw)
        return reply, actions, None
    except urllib.error.HTTPError as e:
        msg = "AI 服务返回错误 %d" % e.code
        if e.code == 401:
            msg = "API Key 无效或未授权，请在后台重新填写"
        elif e.code == 402:
            msg = "账户余额不足，请到 DeepSeek 充值"
        elif e.code == 429:
            msg = "请求过于频繁，请稍后再试"
        return None, None, (jsonify({"error": msg}), 502)
    except urllib.error.URLError as e:
        return None, None, (jsonify({"error": "连不上 AI 服务：" + str(e.reason)}), 502)
    except Exception as e:
        return None, None, (jsonify({"error": "AI 调用失败：" + str(e)}), 502)


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
        -- 人民时评·申论范文：每天从人民日报评论版（paper.people.com.cn）抓「人民时评」那篇。
        -- 它是标准的申论大作文范本 —— 提出问题、分析问题、给对策，还有可直接借鉴的过渡句和金句。
        -- pullquote=报纸上那段highlight的提要；analysis=AI 拆的结构/亮点/可仿写表达（生成一次全局缓存）。
        CREATE TABLE IF NOT EXISTS essay_models(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pub_date TEXT,                   -- 见报日期 YYYY-MM-DD
            column_name TEXT,                -- 栏目（人民时评）
            title TEXT, author TEXT,
            source_url TEXT UNIQUE,          -- 同一篇不重复收
            pullquote TEXT,                  -- 报纸上那段提要
            content TEXT,                    -- 正文全文
            analysis TEXT,                   -- AI 拆解（结构/亮点/可仿写表达），按需生成后缓存
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS essay_model_stars(
            user_id INTEGER NOT NULL, model_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, model_id)
        );
        -- ============ 好友 / 聊天 / 云盘（QQ·微信式）============
        -- 好友：请求 + 关系（关系存双向两条，查「我的好友」直接一句）
        CREATE TABLE IF NOT EXISTS friend_reqs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_uid INTEGER, to_uid INTEGER, msg TEXT,
            status TEXT DEFAULT 'pending',        -- pending/accepted/rejected
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS friends(
            user_id INTEGER, friend_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, friend_id)
        );
        -- 云盘文件（任意格式）。聊天「发文件」也存这张表（一份存储两处用）：
        --   owner_id 是属主；is_dir=1 是文件夹（stored_name 空）；folder 是所在文件夹路径。
        CREATE TABLE IF NOT EXISTS drive_files(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            folder TEXT DEFAULT '',               -- '' / '安装包' / '文档/公考'
            name TEXT, stored_name TEXT,
            ext TEXT, mime TEXT, size INTEGER DEFAULT 0,
            is_dir INTEGER DEFAULT 0,
            source TEXT DEFAULT 'drive',          -- drive=用户上传 / chat=聊天收到的文件
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_drive ON drive_files(owner_id, folder);
        -- 一对一聊天消息。文件类消息引用 drive_files.id（收到的文件也会进对方云盘的「聊天文件」夹）
        CREATE TABLE IF NOT EXISTS chat_msgs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_uid INTEGER, to_uid INTEGER,
            kind TEXT DEFAULT 'text',             -- text / file / image
            body TEXT,                            -- 文本内容
            file_id INTEGER, file_name TEXT, file_size INTEGER, file_mime TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            read_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_chat ON chat_msgs(from_uid, to_uid, id);
        CREATE INDEX IF NOT EXISTS idx_chat2 ON chat_msgs(to_uid, from_uid, id);
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
        -- 标注（手写批注/高亮/笔记）。存服务器＝换设备不丢、多端同步、能进复习/搜索。
        -- 锚（anchor）决定这条标注"贴在哪"，三种：
        --   text  ：{quote,prefix,suffix,start} 按文本定位。字号/字体/宽度/设备随便变都贴着那句话。
        --           （同 AI 划重点的做法，见 app.js mkWrapOne；也就是 W3C Web Annotation 的
        --            TextQuoteSelector。）文本类内容一律走这条。
        --   pdf   ：{page,x,y} 归一化到页内 —— PDF 是固定版式，但缩放会变像素，所以按页归一化。
        --   pixel ：{} 兜底（图片等固定内容，或画在空白处锚不住文本时）＝老的视口坐标行为。
        -- data 存这条标注自己的内容：手写＝笔迹点（相对锚，不是相对屏幕）；笔记＝文字。
        CREATE TABLE IF NOT EXISTS annotations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            target TEXT NOT NULL,          -- 标注挂在哪份内容上（mat:<id> / view:<视图>:<id>）
            anchor_type TEXT NOT NULL,     -- text | pdf | pixel
            anchor TEXT NOT NULL,          -- JSON，按 anchor_type 解释
            kind TEXT NOT NULL,            -- ink 手写 | hl 高亮 | note 文字
            data TEXT,                     -- JSON，见上
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_ann_target ON annotations(user_id, target);
        """
    )
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
    # ↓↓ 到这里为止所有表都建好了，下面才开始「补列」（ALTER）。
    # 顺序很要紧：changkao_items / hyper_items / xiyu_items 的建表在上面第二个 executescript 里，
    # 而它们的 ALTER 原本排在那之前 —— 全新空库上 _cols() 对不存在的表返回空集合，
    # 于是 "col not in set()" 成立、直接 ALTER 一张还没有的表 → init_db() 必崩。
    # 生产库因为表早就在所以从没暴露，换机/新部署就会炸。
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
    # freq/source 原先只由 import_teacher.py 建，可 app.py 自己要查 freq（复习轮按考频排序）。
    # 没导过讲义的新库 → /api/changkao/items、/api/review/today 全 500。schema 得在这儿自洽。
    for col, decl in (("freq", "INTEGER DEFAULT 0"), ("source", "TEXT")):
        if col not in _cols(con, "changkao_items"):
            con.execute("ALTER TABLE changkao_items ADD COLUMN %s %s" % (col, decl))
    # 高频实词的词义：原来只有 content=常用搭配（履行→责任/职责/使命…），没有这个词本身是啥意思。
    # 加一列 meaning，由 build_ck_meaning.py 先查内置词典、查不到用 AI 补齐。
    if "meaning" not in _cols(con, "changkao_items"):
        con.execute("ALTER TABLE changkao_items ADD COLUMN meaning TEXT")
    # 人民时评范文的「逐段批注」（对照精读）：analysis 是整篇拆解，看着和正文割裂；
    # annotations 是 JSON {段号: 这段在做什么/好在哪/可仿写点}，渲染时跟在对应段落后面。
    if "annotations" not in _cols(con, "essay_models"):
        con.execute("ALTER TABLE essay_models ADD COLUMN annotations TEXT")
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
    # board 同理原先只由 crawl_news.py 建，没跑过爬虫的新库进 /api/news 就 500
    if "board" not in _cols(con, "news_items"):
        con.execute("ALTER TABLE news_items ADD COLUMN board TEXT DEFAULT '国内'")
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
        log.exception("study_days 回填迁移失败：学习天数统计可能不全")
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
        log.exception("teams 迁移失败：旧的组队数据可能没并过来")
    # 老数据迁移：shared_todos.done=1 → 记到完成人名下
    try:
        if not con.execute("SELECT COUNT(*) FROM shared_todo_done").fetchone()[0]:
            for r in con.execute("SELECT id, done_by, done_at FROM shared_todos WHERE done=1").fetchall():
                u = con.execute("SELECT id FROM users WHERE username=?", (r[1],)).fetchone()
                if u:
                    con.execute("INSERT OR IGNORE INTO shared_todo_done(todo_id,user_id,username,done_at) "
                                "VALUES(?,?,?,?)", (r[0], u[0], r[1], r[2]))
    except Exception:
        log.exception("shared_todo_done 迁移失败：互监完成记录可能没并过来")
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
        log.exception("搜索的概括句分支出错：结果里会静默少这一类")
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
    # 手写批注：搜「我在哪儿圈过这句话」。锚里存着压着的原文（PDF 的取自 textLayer），
    # 所以这里搜的是**你标过的内容**，不只是文件名。同一处只出一条（一句话上可能划了好几笔）。
    seen_ann = set()
    for r in db.execute("SELECT id,target,anchor_type,anchor FROM annotations "
                        "WHERE user_id=? AND anchor LIKE ? ORDER BY id DESC LIMIT 200",
                        (uid(), like)):
        try:
            a = json.loads(r["anchor"] or "{}")
        except Exception:
            continue
        quote = (a.get("quote") or "").strip()
        if not quote or ql not in quote.lower():
            continue
        sent = _ann_sentence(a) or quote        # 同一段上的好几笔＝同一处，按句子去重（见 _ann_sentence）
        key = (r["target"], sent)
        if key in seen_ann:
            continue
        seen_ann.add(key)
        where, mat = _ann_where(db, uid(), r["target"])
        if a.get("page"):
            where += " · 第 %d 页" % a["page"]
        results.append({"type": "annot", "id": r["id"], "title": sent[:40],
                        "board": where, "target": r["target"], "mat": mat,
                        "snippet": _snippet((a.get("prefix") or "") + quote + (a.get("suffix") or ""), q)})
        if len(seen_ann) >= 12:
            break
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


# ---------------------------------------------------------------- AI 助手
# 已拆到 mods/aichat.py。

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
                    log.debug("临时文件没删掉", exc_info=True)
                return jsonify({"text": vt.strip(), "engine": "vision"})
        except Exception:
            log.warning("vision OCR 失败，回退到本地 OCR", exc_info=True)
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
                log.debug("临时文件没删掉", exc_info=True)
        return jsonify({"error": "识别失败：" + str(e)}), 500
    for p in {tmp, proc}:
        try:
            os.remove(p)
        except Exception:
            log.debug("临时文件没删掉", exc_info=True)
    # tesseract 中文常在汉字间插空格，去掉相邻汉字间的空白
    text = re.sub(r"(?<=[一-鿿，。！？；：、（）《》“”])[ \t]+(?=[一-鿿，。！？；：、（）《》“”])", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return jsonify({"text": text})


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
    sys_prompt = ("你是「公考助手」里的 AI 学习助理，服务正在备考公务员的用户。回答简洁、准确、条理清晰，用简体中文。\n"
                  "【排版要求】用 Markdown 让回答层次分明、重点突出：\n"
                  "· 用 `##`/`###` 小标题分段，用有序/无序列表列要点，别写成一大坨。\n"
                  "· **把关键结论、术语、重点内容加粗**（`**这样**`）—— 不只是加粗标题；比如给古诗词就把**整首诗**"
                  "或关键名句加粗突出，讲知识点就把**核心结论和易错点**加粗。\n"
                  "· 需要时用 `>` 引用来突出原文/诗句，用表格对比。\n"
                  "你能**真的操作这个应用**（通过给你的工具）：用户让你收录成语/词语就用 add_word 真的加进去、"
                  "让你打开某个功能就用 open_feature 打开、让你记笔记就用 create_note。别只是嘴上说做了 —— 要调用工具真做。做完再简短告诉用户结果。\n"
                  "【错题识别】当用户发来一段内容（常常是截图 OCR 出来的文字）时，判断它是不是一道完整的题目：\n"
                  "· 如果**确实是一道完整题目**（有题干，通常还有 A/B/C/D 选项），就用 add_wrong_question 把它加入错题本，"
                  "并顺手判断板块/题型、能定的话给出答案与简要解析；加完简短告诉用户已收录。\n"
                  "· 如果**拿不准这是不是题目**、或内容残缺（只有半道题、只是知识点/材料），**不要**调用工具，"
                  "而是用一句话反问用户：「这看起来像是……，需要我把它加入错题本吗？」等用户确认再决定。")
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
    reply, actions, err = _ai_agentic_or_error(
        [{"role": "system", "content": sys_prompt}] + msgs, db, temperature=0.6, max_tokens=2000)
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
    return jsonify({"reply": reply, "title": title, "actions": actions})


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
# 已拆到 mods/drill.py。_dtest_to_wrongq 一并搬了过去——每日巩固测试也用它，
# 从那儿 import 回来（依赖单向：app.py → mods/*）。

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
            log.warning("plan_log.items_json 解析失败，这天不计入分析", exc_info=True)
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
        g = dict.fromkeys(RV_GROUPS, 0)
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
    except Exception:              # 生成失败不能影响读消息
        log.warning("生成通知失败，本次只返回已有消息", exc_info=True)
    rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY read, id DESC LIMIT 60",
                      (uid(),)).fetchall()
    # 聊天消息另有专属角标（聊天入口红点），别再让消息铃铛重复计数
    unread = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0 AND kind IS NOT 'chat'",
                        (uid(),)).fetchone()[0]
    return jsonify({"items": [dict(r) for r in rows], "unread": unread})


@app.get("/api/notifications/unread")
def notifications_unread():
    """轻量角标：只数未读，不触发生成。聊天消息不计入（它有自己的红点）。"""
    n = get_db().execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0 AND kind IS NOT 'chat'",
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
# 本机直连 Google 不通、走本地代理可达；代理端口会变，做成可配 + 多端口兜底，记住能用的那个
_HW_ITC = "zh-t-i0-handwrit"
_hw_proxy_ok = None   # 上次跑通的代理，命中就先用它


def _hw_proxies():
    env = os.environ.get("GONGKAO_HW_PROXY", "").strip()
    cfg = ""
    try:
        cfg = (json.load(open(CONFIG, encoding="utf-8")).get("hw_proxy") or "").strip()
    except Exception:
        log.debug("读 config.json 的 hw_proxy 失败", exc_info=True)
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
                "SELECT id, board, title, content, note, example, example_src, meaning "
                "FROM changkao_items WHERE board IN ('成语','实词') "
                "ORDER BY COALESCE(freq,0) DESC, id LIMIT ?", (n_ck,)):
            body = (r["content"] or "").strip()
            # 实词的 content 是「常用搭配」，词义单独放在 meaning —— 背面先给词义、再给搭配，才记得住
            mean = (r["meaning"] or "").strip()
            parts = []
            if mean:
                parts.append(("释义：" if r["board"] == "实词" else "") + mean)
            if body:
                parts.append(("搭配：" + body) if r["board"] == "实词" and mean else body)
            back = "\n".join(parts)
            if r["note"]:
                back += "\n\n📌 " + r["note"]
            if r["example"]:                       # 光有释义记不住怎么用，背面给个例句
                back += "\n\n✍️ 例句：" + r["example"] + (
                    ("\n　　—— " + r["example_src"]) if r["example_src"] else "")
            check("changkao", r["id"], "2000-01-01", {          # 全局内容，不按收录时间等一天
                "title": r["title"] or "", "sub": r["board"] or "常考",
                "body": (mean or body)[:90],
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
        cue = re.split(r"[，,。；;、]", body, maxsplit=1)[0][:22]
        front = cue or (r["topic"] or "").strip() or (r["kind"] or "素材")
        front_sub = (r["kind"] or "素材") + ((" · " + r["topic"]) if r["topic"] else "")
        if r["kind"] == "衔接表达":          # 句式类：正面给用途，背面给句式本身
            front, front_sub = "衔接表达 · 回忆句式", (r["kind"] or "素材")
            back = body + (("\n\n【例句】" + r["example"]) if r["example"] else "")
        check("sucai", r["id"], r["created_at"], {
            "title": (r["topic"] or r["kind"] or "素材")[:36], "sub": r["kind"] or "素材",
            "body": body[:90], "front": front, "front_sub": front_sub,
            "back": back or "（无内容）"})
    # 手写批注：你圈过的地方按遗忘曲线回来找你 —— 圈重点本来就是「这里要紧」的意思，
    # 圈完再也不见面就白圈了。这是张「回看卡」：正面是你圈的那句话，翻开是它的上下文。
    #   · 只有带原文的才进（pixel 锚是一坨没内容的像素，进了也没得看）；PDF 的原文取自 textLayer。
    #   · 同一句话上划了好几笔只提醒一次，按**最早**那一笔的 id 记进度 —— 用升序取，
    #     这样以后在同一句上再补几笔也不会让复习进度重来。
    seen_ann = set()
    # 没 quote 的（pixel 锚）在 SQL 里就滤掉：存量老批注全是 pixel 锚，光一个用户就有好几百条，
    # 不滤的话 LIMIT 会被它们占满，带原文的新批注一条也取不到。
    for r in db.execute("SELECT id, target, anchor, created_at FROM annotations "
                        "WHERE user_id=? AND anchor LIKE '%\"quote\"%' ORDER BY id LIMIT 500", (u,)):
        try:
            a = json.loads(r["anchor"] or "{}")
        except Exception:
            continue
        quote = (a.get("quote") or "").strip()
        if not quote:
            continue
        sent = _ann_sentence(a) or quote        # 按句子去重＋卡片给整句（见 _ann_sentence）
        key = (r["target"], sent)
        if key in seen_ann:
            continue
        seen_ann.add(key)
        where, _mat = _ann_where(db, u, r["target"])
        if a.get("page"):
            where += " · 第 %d 页" % a["page"]
        ctx = ((a.get("prefix") or "") + quote + (a.get("suffix") or "")).strip()
        check("annot", r["id"], r["created_at"], {
            "title": sent[:36], "sub": where, "body": sent[:90],
            "front": sent, "front_sub": where,
            "back": ctx or sent})
    return due


# 复习分组：词语句子 / 每日积累 / 错题，分开背，不混在一副牌里。
# 加新来源时**只改这里**：/api/review/done 的白名单直接取自它（见那儿的注释）。
RV_GROUP = {"entry": "word", "classic": "word", "changkao": "word", "sucai": "daily",
            "annot": "annot", "wrongq": "wrongq"}
RV_NAMES = {"word": "词语句子", "daily": "每日积累", "annot": "批注", "wrongq": "错题"}
# 每日复习量默认值（0 = 不限）。批注单独一组：跟「每日积累」挤一个额度的话，素材排在前面，
# 20 条一占满，圈过的重点一条也出不来（实测过 —— 7 条批注全被截掉）。
RV_LIMIT_DEF = {"word": 40, "daily": 20, "annot": 10, "wrongq": 10}
RV_GROUPS = list(RV_LIMIT_DEF)                             # 分组名单只此一份，别再手抄


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
    pool = dict.fromkeys(RV_GROUPS, 0)
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
                log.debug("复习上限收到非法值，已忽略", exc_info=True)
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
    order = {"entry": 0, "classic": 1, "sucai": 2, "annot": 3, "wrongq": 4}
    # 组内排序：**已经在复习轮里的排前面**（stage>0 说明背过一遍了，别让它一直往后堆），
    # 然后才是新词。被上限截掉的不动 next_due —— 只是今天不出现，明天照样在。
    due.sort(key=lambda x: (order.get(x["kind"], 9), -int(x.get("stage") or 0), x["id"]))
    lim = _rv_limits(db, uid())
    pool = dict.fromkeys(RV_GROUPS, 0)
    for it in due:
        it["group"] = RV_GROUP.get(it["kind"], "wrongq")
        pool[it["group"]] += 1
    # 今天已经复习过、且成功推到以后的（认识/模糊 → next_due>today）算已完成，要**从每日额度里扣掉**。
    # 不然「每日复习量 40」只截断每次显示多少 —— 做完 40 条一刷新，池子里剩下的又冒出 40 条，
    # 感觉像「进度被重置」。忘记的（next_due=today）不算完成，它本来就该今天再出现。
    done_today = dict.fromkeys(RV_GROUPS, 0)
    for r in db.execute(
            "SELECT kind, COUNT(*) c FROM review_state "
            "WHERE user_id=? AND last_done=? AND next_due>? GROUP BY kind",
            (uid(), today, today)):
        done_today[RV_GROUP.get(r["kind"], "wrongq")] += r["c"]
    kept, used = [], dict.fromkeys(RV_GROUPS, 0)
    for it in due:
        g = it["group"]
        if lim[g] and (used[g] + done_today[g]) >= lim[g]:   # 上限 0 = 不限；今天做过的占额度
            continue
        used[g] += 1
        kept.append(it)
    return jsonify({"today": today, "count": len(kept), "items": kept,
                    "groups": used, "pool": pool, "limits": lim,
                    "done_today": done_today})


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
        log.debug("notes 时间戳取不到，同步指纹少一项", exc_info=True)
    return jsonify({"token": hashlib.md5("|".join(parts).encode()).hexdigest()})


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
    gen = _gen_ai_explanation(db, word, data.get("category") or "")
    cat, py = gen["category"], gen["pinyin"]
    exp, der, exa = gen["explanation"], gen["derivation"], gen["example"]
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
