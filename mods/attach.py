"""AI 附件文本提取（/api/ai/extract）+ 常识积累的板块目录（/api/changshi/*）。

两件不相干的事凑在一个文件里——拆分时按 app.py 的旧区段边界切的，那个边界
把常识积累的板块目录跟附件提取划在了一起。常识积累的其余部分在别处，
这里只有板块目录和 _CS_META。真要动常识积累时，把这两个路由单独拎出去。
"""
import json
import os
import tempfile
import time
import uuid

from flask import Blueprint, jsonify, request, send_file

from core import BASE, get_db, log
from mods.ai import vision_configured, vision_ocr
from mods.files import IMAGE_EXT, _extract_text, _ocr_image

bp = Blueprint("attach", __name__)

# 发给 AI 看的原图暂存处。**只是暂存**：留 3 天足够一场对话里反复追问，
# 再久就是白占盘 —— 会话历史里存的是文件名和抽出的文字，不靠这些图。
AI_IMG_DIR = os.path.join(BASE, "uploads", "_aiimg")
AI_IMG_KEEP_DAYS = 3


def _sweep_ai_imgs():
    """顺手清掉过期的暂存图。跟着上传走，不另起定时器。"""
    try:
        cutoff = time.time() - AI_IMG_KEEP_DAYS * 86400
        for fn in os.listdir(AI_IMG_DIR):
            p = os.path.join(AI_IMG_DIR, fn)
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                os.remove(p)
    except Exception:
        log.debug("暂存图清理失败", exc_info=True)


def ai_img_path(name):
    """把前端带回来的文件名还原成磁盘路径。挡掉路径穿越 —— 这个名字是从请求里来的。"""
    name = os.path.basename(name or "")
    if not name:
        return ""
    p = os.path.join(AI_IMG_DIR, name)
    return p if os.path.exists(p) else ""

# 常识积累的板块元数据（changshi_meta.json）——这块路由也在本模块里
_CS_META = {}
try:
    with open(os.path.join(BASE, "changshi_meta.json"), encoding="utf-8") as _f:
        _CS_META = json.load(_f)
except Exception:
    _CS_META = {"tiers": [], "boards": {}}


@bp.get("/api/ai/img/<path:name>")
def ai_img_get(name):
    """把发给 AI 看过的那张原图读回来 —— 前端的附件缩略图要它。

    只认 AI_IMG_DIR 下的文件（ai_img_path 会挡路径穿越），过期清掉的就 404，
    前端那边显示成一个文件角标，不会碎图。"""
    p = ai_img_path(name)
    if not p:
        return jsonify({"error": "图片已过期"}), 404
    return send_file(p, max_age=86400)


@bp.post("/api/ai/extract")
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
    keep = ""
    try:
        # 图片：**原图留下来**，不像以前那样抽完文字就删。抽文字够应付文字题，但图形推理和
        # 资料分析的图表在抽取那一步就没了 —— 行测两个大板块恰恰全在图里。留着路径，
        # 对话那边把原图直接交给视觉模型（aisession 的 vision 分支），文字继续当兜底。
        if is_img:
            os.makedirs(AI_IMG_DIR, exist_ok=True)
            keep = uuid.uuid4().hex + ext
            os.replace(tmp, os.path.join(AI_IMG_DIR, keep))
            _sweep_ai_imgs()
        else:
            os.remove(tmp)
    except Exception as e:
        keep = ""
        log.info("附件临时文件处理失败：%r", e)
    text = (text or "").strip()
    if is_img and (keep or text):
        return jsonify({"text": text[:6000], "name": f.filename, "image": keep})
    if not text:
        return jsonify({"error": err or "没能从附件中提取到文字"}), 200
    return jsonify({"text": text[:6000], "name": f.filename})


@bp.get("/api/changshi/boards")
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


@bp.get("/api/changshi/board")
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
