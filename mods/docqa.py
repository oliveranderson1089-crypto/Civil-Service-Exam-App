"""文档识题：抽出例题 → AI 解答 → 回填成副本。

有「（　）」「A．」「下列…正确的是」这类特征的页面才值得送去问 AI，省一大笔调用
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid

from flask import Blueprint, jsonify, request

from core import DB, UPLOADS, bg_new, bg_set, get_db, log, uid
from mods.ai import _ai_call_or_error, vision_chat, vision_configured
from mods.files import (OFFICE_EXT, _ocr_image_page, _office_to_pdf,
                        _strip_artifacts, _user_dir)
from mods.pdfkit import ensure_pdf_font

bp = Blueprint("docqa", __name__)


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


@bp.post("/api/docqa/upload")
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


@bp.get("/api/docqa/tasks")
def docqa_tasks():
    rows = get_db().execute(
        "SELECT * FROM bg_tasks WHERE user_id=? AND kind='docqa' ORDER BY id DESC LIMIT 30",
        (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@bp.get("/api/docqa/task/<int:tid>")
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


@bp.delete("/api/docqa/task/<int:tid>")
def docqa_task_del(tid):
    db = get_db()
    db.execute("DELETE FROM doc_questions WHERE task_id=?", (tid,))
    db.execute("DELETE FROM bg_tasks WHERE id=? AND user_id=?", (tid, uid()))
    db.commit()
    return jsonify({"ok": True})
