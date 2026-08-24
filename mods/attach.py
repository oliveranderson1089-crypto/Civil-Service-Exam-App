"""AI 附件文本提取（/api/ai/extract）+ 常识积累的板块目录（/api/changshi/*）。

两件不相干的事凑在一个文件里——拆分时按 app.py 的旧区段边界切的，那个边界
把常识积累的板块目录跟附件提取划在了一起。常识积累的其余部分在别处，
这里只有板块目录和 _CS_META。真要动常识积累时，把这两个路由单独拎出去。
"""
import json
import os
import shutil
import tempfile
import time
import uuid

from flask import Blueprint, jsonify, request, send_file

from core import BASE, UPLOADS, get_db, log, uid
from mods.ai import vision_configured, vision_ocr
from mods.files import IMAGE_EXT, _ocr_image, _pdf_text_or_ocr, pdf_pages
from mods.materials import _get_material
from mods.social import _drive_dir

bp = Blueprint("attach", __name__)

# 发给 AI 看的原图暂存处。**只是暂存**：留 3 天足够一场对话里反复追问，
# 再久就是白占盘 —— 会话历史里存的是文件名和抽出的文字，不靠这些图。
AI_IMG_DIR = os.path.join(BASE, "uploads", "_aiimg")
AI_IMG_KEEP_DAYS = 3

# 扫描件逐页 OCR 的页数上限。这条路是**用户盯着等**的（300dpi 一页要跑几秒），
# 跟资料库那种离线入库不是一个口径，所以单独给一个数。
ATT_OCR_PAGES = 20
# 单个附件回传给前端的正文上限。原先是 6000 且**截了不说**——模型看到的是一份
# 「完整的短资料」，于是会照着半截内容下结论（"这份 PDF 里只有 12 个易混淆点"），
# 用户还以为是模型偷懒。现在放宽到这个数，并且一律把 total/truncated 一起带回去，
# 让前端和模型都知道自己没看全（真正决定注入多少的是 aisession 的 ATT_LIMIT）。
ATT_TEXT_MAX = 60000
# 「云盘/资料库里已有的文件」当附件时的体积上限。上传那条路由由 Flask 的
# MAX_CONTENT_LENGTH（64MB）挡着，这条路根本没走 HTTP 上传，得自己挡一道 ——
# 否则一份 96MB 的讲义会让人对着转圈等到以为坏了。数字跟上传口对齐，别各写各的。
ATT_SRC_MAX = 64 * 1024 * 1024


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


def extract_file(path, ext, is_img, max_pages=ATT_OCR_PAGES):
    """把磁盘上的一个文件抽成文字。返回 (text, pages, err)。

    对话附件（/api/ai/extract）和项目资料上传共用这一份。**必须共用**：
    两处各写一份的话，「扫描件能不能读」「图片走不走视觉模型」这种事就会一处能一处不能，
    而用户看到的只是「同一份 PDF，传给对话能读、挂到项目上就读不出来」。

    pages 只对 PDF 有值（其余给 0）——它是向用户和模型交代「这份文件一共多少页」用的。
    """
    text, pages, err = "", 0, ""
    try:
        if is_img:
            if vision_configured():          # 视觉模型：比 OCR 更能读懂图片（含手写、排版）
                try:
                    text = vision_ocr(path)
                except Exception:
                    text = ""
            if not text.strip():
                text = _ocr_image(path)      # 兜底
            if not text.strip():
                err = "图片里没识别出文字（可能是纯图形、字太小或太模糊，可放大后重拍）"
        else:
            # 用 _pdf_text_or_ocr 而不是 _extract_text：后者只抽文字层，纯扫描件
            # （手机拍的讲义、影印的真题卷）在这里会一个字都读不到，直接回一句
            # 「提取不出文字」—— 而项目里明明有逐页 OCR 的能力，只是这条路没接上。
            if ext == ".pdf":
                pages = pdf_pages(path)
            text = _pdf_text_or_ocr(path, ext, max_pages=max_pages) or ""
            if not text.strip():
                err = "这个格式（%s）暂时提取不出文字，可先转成 PDF 或截图上传" % (ext or "未知")
    except Exception as e:
        err = "解析失败：%s" % e
    return (text or "").strip(), pages, err


def guess_ext(filename, mimetype):
    """(是不是图片, 扩展名)。拍照/粘贴来的图片常常没有扩展名，按 MIME 兜底判断。"""
    ext = os.path.splitext(filename or "")[1].lower()
    mime = (mimetype or "").lower()
    is_img = mime.startswith("image/") or ext in IMAGE_EXT
    if is_img and ext not in IMAGE_EXT:
        ext = "." + (mime.split("/")[-1].split("+")[0] or "png")
    return is_img, ext


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


def _lib_file():
    """请求点名的「应用里已经有的文件」：云盘 drive_id / 资料库 material_id。

    这条路是为「在云盘复制一份、到 AI 助手粘上」准备的：文件本来就躺在服务器上，
    再让浏览器下下来又原样传回去，既慢又白烧一遍流量（云盘里的讲义动辄几十 MB）。
    返回 ((path, name, ext, mime), "")；没点名回 (None, "")，点名但拿不到回 (None, 话术)。
    """
    body = request.get_json(silent=True) or {}

    def val(k):
        v = request.form.get(k) or request.args.get(k) or body.get(k)
        return str(v).strip() if v not in (None, "") else ""

    did, mid = val("drive_id"), val("material_id")
    if not did and not mid:
        return None, ""
    if did:
        if not did.isdigit():
            return None, "云盘文件不存在"
        r = get_db().execute(
            "SELECT * FROM drive_files WHERE id=? AND owner_id=? AND deleted_at IS NULL",
            (int(did), uid())).fetchone()
        if not r:
            return None, "这个云盘文件不在了（可能已被删除）"
        if r["is_dir"]:
            return None, "文件夹不能整个当附件，进去挑里面的文件"
        path = os.path.join(_drive_dir(uid()), r["stored_name"] or "")
        name, ext, mime = r["name"], (r["ext"] or ""), (r["mime"] or "")
    else:
        m = _get_material(int(mid)) if mid.isdigit() else None
        if not m:
            return None, "这份资料不在了"
        path = os.path.join(os.path.join(UPLOADS, str(m["user_id"])), m["stored_name"] or "")
        name, ext, mime = (m["title"] or m["orig_name"]), (m["ext"] or ""), ""
    if not os.path.exists(path):
        return None, "文件丢了：服务器上找不到「%s」的内容" % name
    size = os.path.getsize(path)
    if size > ATT_SRC_MAX:
        return None, ("「%s」有 %.0f MB，超过附件上限 %d MB。可以先预览它，把要问的那几页截图发给 AI"
                      % (name, size / 1048576.0, ATT_SRC_MAX // 1048576))
    return (path, name, (ext or "").lower(), mime), ""


def _att_extract(path, name, ext, mime, keep_src=False):
    """把磁盘上的一份文件读成 AI 附件（抽出的文字 + 可能留档的原图）。

    抽文字一律走 extract_file（项目资料那边用的也是它）；这里额外管两件事：
    原图留不留档，以及**path 那份文件动不动得**。

    keep_src=True 表示 path 是用户的原件（云盘/资料库里那一份）：只许读，
    留原图得复制一份走 —— 照着临时文件那套 os.replace 搬走的话，用户的文件
    会当场从云盘里消失。上传上来的临时文件传 False，读完就地清掉。
    """
    is_img = (mime or "").lower().startswith("image/") or ext in IMAGE_EXT
    text, pages, err = extract_file(path, ext, is_img)
    keep = ""
    try:
        # 图片：**原图留下来**，不像以前那样抽完文字就删。抽文字够应付文字题，但图形推理和
        # 资料分析的图表在抽取那一步就没了 —— 行测两个大板块恰恰全在图里。留着路径，
        # 对话那边把原图直接交给视觉模型（aisession 的 vision 分支），文字继续当兜底。
        if is_img:
            os.makedirs(AI_IMG_DIR, exist_ok=True)
            keep = uuid.uuid4().hex + ext
            dst = os.path.join(AI_IMG_DIR, keep)
            if keep_src:
                shutil.copyfile(path, dst)
            else:
                try:
                    os.replace(path, dst)
                except OSError:
                    # 临时文件在 /tmp，暂存目录在 uploads 底下 —— 两者常常不在同一个文件系统
                    # （这台机器就是），os.replace 会抛 OSError(18, 'Invalid cross-device link')。
                    # 原来抛了就把 keep 清空，表现是**图片被静默降级**：视觉模型再也看不到原图，
                    # 只剩 OCR 出来的文字，而行测的图形推理和资料分析恰恰全在图里。
                    # 日志里只有一行 INFO，界面上什么都不说。资料库那条路早就这么兜底了。
                    shutil.copyfile(path, dst)
                    os.remove(path)
            _sweep_ai_imgs()
        elif not keep_src:
            os.remove(path)
    except Exception as e:
        keep = ""
        log.info("附件临时文件处理失败：%r", e)
    if not text and not (is_img and keep):
        return {"error": err or "没能从附件中提取到文字"}
    out = {"text": text[:ATT_TEXT_MAX], "name": name,
           # total/truncated 是**给人和模型看的交代**，不是内部字段：前端拿它在附件条上
           # 标一行「已读取 X / 共 Y 字」，服务端拿它在注入给模型的正文末尾写明还有后续。
           # 少了它，截断就是无声的，而无声的截断会让模型自信地答错。
           "total": len(text), "truncated": len(text) > ATT_TEXT_MAX}
    if pages:
        out["pages"] = pages
        out["ocr_pages"] = ATT_OCR_PAGES        # 超过这个页数的扫描件只 OCR 了前这些页
    if is_img:
        out["image"] = keep
    return out


@bp.post("/api/ai/extract")
def ai_extract_attachment():
    """把一份文件变成 AI 附件。两种来源：

    - 传上来的文件（multipart 的 file）—— 拍照、选图、选文件走这条；
    - 应用里已有的文件（drive_id / material_id）—— 云盘、资料库里点「发给 AI 助手」
      或复制后在助手里粘贴走这条，不重传一遍。
    """
    # 这条路是用户盯着等的：上传要走网络（手机走隧道时几十 MB 的照片能传半分钟），
    # 识别本身又要一二十秒。出问题时「到底有没有传上来、慢在哪一段」全靠这行日志 ——
    # 没有它，手机端一句「选完图没动静」在服务器上查无此事。
    t0 = time.time()
    src, err = _lib_file()
    if err:
        return jsonify({"error": err}), 404
    if src:
        path, name, ext, mime = src
        out = _att_extract(path, name, ext, mime, keep_src=True)
        log.info("AI 附件（库内）：%s 用时 %.1fs", name, time.time() - t0)
        return jsonify(out)
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "没有文件"}), 400
    _, ext = guess_ext(f.filename, f.mimetype)     # 拍照/粘贴来的图常常没有扩展名
    tmp = os.path.join(tempfile.gettempdir(), "aiatt_" + uuid.uuid4().hex + ext)
    f.save(tmp)
    size = os.path.getsize(tmp)
    t1 = time.time()
    out = _att_extract(tmp, f.filename, ext, f.mimetype)
    # 只记得到「服务端这一段」：body 在进视图之前就被读完了，网络上传那几十秒不在这个数里。
    # 所以真正该看的是 MB 数 —— 手机传上来的还是好几 MB，说明前端没压，卡的是路上。
    log.info("AI 附件（上传）：%s %.2fMB 识别 %.1fs%s",
             f.filename, size / 1048576.0, time.time() - t1,
             "" if out.get("text") or out.get("image") else " 【没提取到内容】")
    return jsonify(out)


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
